"""Inert, fail-closed migration domain for checkout-local machine data.

Nothing in production startup imports this module during Milestone 2.  The
public functions require explicit sources, destinations, identity, and lock
ownership and never write ``active_machine.json``.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

import LocalConfig
from MachineData import (
    MachineDataBasePaths,
    MachineDataPathError,
    MachineDataPaths,
    MachineIdentity,
    MachineIdentityError,
    UNASSIGNED_MACHINE_ID,
    build_machine_data_paths,
    parse_machine_identity,
)
from MachineDataArchive import (
    ArchivePolicy,
    ArchiveSafetyError,
    ArchiveVerificationError,
    DurableFileOps,
    FileEvidence,
    SourceLocator,
    SourceChangedDuringArchive,
    SourceSnapshot,
    VerifiedBackup,
    canonical_json_bytes,
    capture_source,
    create_backup_archive as _create_backup_archive,
    discover_zip_source,
    evidence_fingerprint,
    open_verified_backup,
    semantic_json_sha256,
    sha256_bytes,
    sha256_file,
    verify_backup_archive,
)


MIGRATION_JOURNAL_SCHEMA_NAME = "labcraft.migration_journal"
MIGRATION_JOURNAL_SCHEMA_VERSION = 1
MIGRATION_RECEIPT_SCHEMA_NAME = "labcraft.migration_receipt"
MIGRATION_RECEIPT_SCHEMA_VERSION = 1
MIGRATION_TREE_MANIFEST_SCHEMA_NAME = "labcraft.migration_tree_manifest"
MIGRATION_TREE_MANIFEST_SCHEMA_VERSION = 1
PRESET_CATALOG_SCHEMA_NAME = "labcraft.historical_machine_preset_fingerprints"
PRESET_CATALOG_SCHEMA_VERSION = 1

DEFAULT_PRESET_CATALOG_PATH = (
    Path(__file__).resolve().parent
    / "Presets"
    / "machine_data_historical_fingerprints.json"
)
REQUIRED_CONFIG_TYPES = MappingProxyType(
    dict(LocalConfig.machine_config_top_level_types())
)
CALIBRATION_MEMORY_SEED_TYPES = MappingProxyType(
    dict(LocalConfig.calibration_memory_seed_top_level_types())
)
REQUIRED_CONFIG_NAMES = tuple(REQUIRED_CONFIG_TYPES)
PLATE_CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")
_WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_FALSE_AUTHORIZATION_FIELDS = {
    "activation_authorized": False,
    "source_verified": False,
    "calibration_verified": False,
}


class CandidateSourceKind(str, Enum):
    CURRENT_CHECKOUT_LOCAL = "current_checkout_local"
    OPERATOR_SELECTED_LOCAL = "operator_selected_local"
    OPERATOR_SELECTED_WRAPPER = "operator_selected_wrapper"
    OPERATOR_SELECTED_ZIP = "operator_selected_zip"
    EXISTING_CANONICAL = "existing_canonical"


class CandidateIssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    FATAL = "fatal"


class MigrationState(str, Enum):
    CANDIDATE_SELECTED = "candidate_selected"
    SOURCE_VALIDATED = "source_validated"
    BACKUP_VERIFIED = "backup_verified"
    STAGED_COPY_VERIFIED = "staged_copy_verified"
    COPIED_UNVERIFIED = "copied_unverified"


class PublishedMigrationPhase(str, Enum):
    COPIED_UNVERIFIED = "copied_unverified"
    ACTIVATION_STAGED = "activation_staged"
    ACTIVE = "active"


_STATE_ORDER = tuple(MigrationState)
_LEGAL_NEXT_STATE = {
    MigrationState.CANDIDATE_SELECTED: MigrationState.SOURCE_VALIDATED,
    MigrationState.SOURCE_VALIDATED: MigrationState.BACKUP_VERIFIED,
    MigrationState.BACKUP_VERIFIED: MigrationState.STAGED_COPY_VERIFIED,
    MigrationState.STAGED_COPY_VERIFIED: MigrationState.COPIED_UNVERIFIED,
}


class MigrationError(RuntimeError):
    """Base fail-closed migration error with a stable classification."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class CandidateNotImportable(MigrationError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_source", message)


class MigrationRecoveryRequired(MigrationError):
    def __init__(self, message: str) -> None:
        super().__init__("recovery_required", message)


class MigrationLockToken(Protocol):
    def assert_owns(self, machine_uuid: str, expected_path: Path) -> None: ...


@dataclass(frozen=True)
class CandidateSelection:
    source_kind: CandidateSourceKind
    selected_path: Path
    label: str = ""

    def __post_init__(self) -> None:
        try:
            kind = CandidateSourceKind(self.source_kind)
        except ValueError as exc:
            raise ValueError(f"Unsupported candidate source kind: {self.source_kind!r}") from exc
        if not isinstance(self.label, str):
            raise ValueError("Candidate label must be text.")
        object.__setattr__(self, "source_kind", kind)
        object.__setattr__(
            self, "selected_path", Path(self.selected_path).resolve(strict=False)
        )


@dataclass(frozen=True)
class CandidateIssue:
    severity: CandidateIssueSeverity
    code: str
    message: str
    relative_path: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "relative_path": self.relative_path,
        }


@dataclass(frozen=True)
class PresetCohort:
    cohort: str
    declared_versions: tuple[str, ...]
    config_semantic_sha256: Mapping[str, str]
    camera_semantic_sha256: str


@dataclass(frozen=True)
class PresetFingerprintCatalog:
    cohorts: tuple[PresetCohort, ...]

    @classmethod
    def load(cls, path: Path = DEFAULT_PRESET_CATALOG_PATH) -> "PresetFingerprintCatalog":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot load historical preset catalog {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Historical preset catalog must be a JSON object.")
        if payload.get("schema_name") != PRESET_CATALOG_SCHEMA_NAME:
            raise ValueError("Unknown historical preset catalog schema_name.")
        if type(payload.get("schema_version")) is not int or payload.get(
            "schema_version"
        ) != PRESET_CATALOG_SCHEMA_VERSION:
            raise ValueError("Unknown historical preset catalog schema_version.")
        raw_cohorts = payload.get("cohorts")
        if not isinstance(raw_cohorts, list) or not raw_cohorts:
            raise ValueError("Historical preset catalog cohorts must be a nonempty list.")
        cohorts: list[PresetCohort] = []
        names: set[str] = set()
        for raw in raw_cohorts:
            if not isinstance(raw, dict):
                raise ValueError("Historical preset cohort must be an object.")
            name = raw.get("cohort")
            versions = raw.get("declared_versions")
            hashes = raw.get("config_semantic_sha256")
            camera_hash = raw.get("camera_semantic_sha256")
            if not isinstance(name, str) or not name or name in names:
                raise ValueError("Historical preset cohort name is missing or duplicated.")
            if not isinstance(versions, list) or not all(
                isinstance(value, str) and value for value in versions
            ):
                raise ValueError(f"Invalid declared_versions for cohort {name}.")
            if not isinstance(hashes, dict) or set(hashes) != set(REQUIRED_CONFIG_NAMES):
                raise ValueError(f"Preset cohort {name} must hash all required configs.")
            if not all(_is_sha256(value) for value in hashes.values()) or not _is_sha256(
                camera_hash
            ):
                raise ValueError(f"Invalid SHA-256 in preset cohort {name}.")
            names.add(name)
            cohorts.append(
                PresetCohort(
                    name,
                    tuple(versions),
                    MappingProxyType(dict(hashes)),
                    camera_hash,
                )
            )
        return cls(tuple(cohorts))


@dataclass(frozen=True)
class CandidateEvidence:
    candidate_id: str
    source_kind: CandidateSourceKind
    normalized_source: Path
    label: str
    inspected_at_utc: str
    version_text: str | None
    required_files: tuple[FileEvidence, ...]
    migratable_files: tuple[FileEvidence, ...]
    required_config_fingerprint: str
    migratable_tree_fingerprint: str
    full_source_fingerprint: str
    safety_snapshot: Mapping[str, object]
    identity_status: str
    legacy_identity: MachineIdentity | None
    calibration_memory_status: str
    missing_calibration_memory_seed_files: tuple[str, ...]
    preset_matches: tuple[str, ...]
    individual_preset_matches: tuple[str, ...]
    camera_preset_match: bool
    declared_version_mismatch: bool
    unclassified_source_paths: tuple[str, ...]
    issues: tuple[CandidateIssue, ...]
    _source_locator: SourceLocator | None = field(default=None, repr=False, compare=False)

    @property
    def preset_like(self) -> bool:
        return bool(self.preset_matches)

    @property
    def is_importable(self) -> bool:
        return self.source_kind != CandidateSourceKind.EXISTING_CANONICAL and not any(
            issue.severity == CandidateIssueSeverity.FATAL for issue in self.issues
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "source_kind": self.source_kind.value,
            "normalized_source": str(self.normalized_source),
            "label": self.label,
            "inspected_at_utc": self.inspected_at_utc,
            "version_text": self.version_text,
            "required_files": [item.to_payload() for item in self.required_files],
            "migratable_files": [item.to_payload() for item in self.migratable_files],
            "required_config_fingerprint": self.required_config_fingerprint,
            "migratable_tree_fingerprint": self.migratable_tree_fingerprint,
            "full_source_fingerprint": self.full_source_fingerprint,
            "safety_snapshot": dict(self.safety_snapshot),
            "identity_status": self.identity_status,
            "legacy_identity": (
                self.legacy_identity.to_payload() if self.legacy_identity else None
            ),
            "calibration_memory_status": self.calibration_memory_status,
            "missing_calibration_memory_seed_files": list(
                self.missing_calibration_memory_seed_files
            ),
            "preset_matches": list(self.preset_matches),
            "individual_preset_matches": list(self.individual_preset_matches),
            "camera_preset_match": self.camera_preset_match,
            "declared_version_mismatch": self.declared_version_mismatch,
            "unclassified_source_paths": list(self.unclassified_source_paths),
            "issues": [issue.to_payload() for issue in self.issues],
            "is_importable": self.is_importable,
        }


@dataclass(frozen=True)
class CandidateRelation:
    first_candidate_id: str
    second_candidate_id: str
    classification: str


@dataclass(frozen=True)
class CandidateComparison:
    relations: tuple[CandidateRelation, ...]


@dataclass(frozen=True)
class MigrationWorkspacePaths:
    base: MachineDataBasePaths
    machine_uuid: str
    migration_id: str
    root: Path
    journal_path: Path
    backup_path: Path
    staged_machine_root: Path

    def __post_init__(self) -> None:
        canonical_machine = _canonical_uuid(self.machine_uuid, "machine_uuid")
        canonical_migration = _canonical_uuid(self.migration_id, "migration_id")
        expected_root = (
            self.base.root
            / "migration_work"
            / canonical_machine
            / canonical_migration
        ).resolve(strict=False)
        expected = {
            "root": expected_root,
            "journal_path": expected_root / "journal.json",
            "backup_path": expected_root / "source_backup.zip",
            "staged_machine_root": expected_root / "staged_machine",
        }
        object.__setattr__(self, "machine_uuid", canonical_machine)
        object.__setattr__(self, "migration_id", canonical_migration)
        for name, expected_path in expected.items():
            actual = Path(getattr(self, name)).resolve(strict=False)
            if actual != expected_path:
                raise MachineDataPathError(
                    f"{name} must match the contained migration workspace: {actual}"
                )
            object.__setattr__(self, name, actual)


@dataclass(frozen=True)
class MigrationPolicy:
    archive_policy: ArchivePolicy = field(default_factory=ArchivePolicy)
    safety_margin_bytes: int = 64 * 1024**2

    def __post_init__(self) -> None:
        if type(self.safety_margin_bytes) is not int or self.safety_margin_bytes < 0:
            raise ValueError("safety_margin_bytes must be a nonnegative integer.")


@dataclass(frozen=True)
class MigrationReceipt:
    migration_id: str
    state: MigrationState
    machine_id: str
    machine_uuid: str
    source_kind: str
    source_version: str | None
    candidate_id: str
    required_config_fingerprint: str
    migratable_tree_fingerprint: str
    full_source_fingerprint: str
    backup_archive_sha256: str
    preset_like: bool
    camera_preset_match: bool
    unclassified_source_paths: tuple[str, ...]
    completed_at_utc: str
    activation_authorized: bool = field(default=False, init=False)
    source_verified: bool = field(default=False, init=False)
    calibration_verified: bool = field(default=False, init=False)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_name": MIGRATION_RECEIPT_SCHEMA_NAME,
            "schema_version": MIGRATION_RECEIPT_SCHEMA_VERSION,
            "migration_id": self.migration_id,
            "state": self.state.value,
            "machine_id": self.machine_id,
            "machine_uuid": self.machine_uuid,
            "source_kind": self.source_kind,
            "source_version": self.source_version,
            "candidate_id": self.candidate_id,
            "required_config_fingerprint": self.required_config_fingerprint,
            "migratable_tree_fingerprint": self.migratable_tree_fingerprint,
            "full_source_fingerprint": self.full_source_fingerprint,
            "backup_archive_sha256": self.backup_archive_sha256,
            "preset_like": self.preset_like,
            "camera_preset_match": self.camera_preset_match,
            "unclassified_source_paths": list(self.unclassified_source_paths),
            "activation_authorized": self.activation_authorized,
            "source_verified": self.source_verified,
            "calibration_verified": self.calibration_verified,
            "completed_at_utc": self.completed_at_utc,
        }


@dataclass(frozen=True)
class MigrationResult:
    state: MigrationState
    target_paths: MachineDataPaths
    receipt: MigrationReceipt
    backup_archive_path: Path
    reconciled: bool = False


@dataclass(frozen=True)
class PublishedMigrationEvidence:
    receipt: MigrationReceipt
    candidate: CandidateEvidence
    backup: VerifiedBackup
    migration_tree_manifest_sha256: str
    additional_paths: tuple[str, ...]


class MigrationFileOps(DurableFileOps):
    def disk_usage(self, path: Path):
        return shutil.disk_usage(path)

    def write_bytes_durable(
        self,
        path: Path,
        data: bytes,
        *,
        checkpoint_prefix: str,
    ) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
        )
        temporary = Path(temporary_name)
        try:
            self.checkpoint(f"before_{checkpoint_prefix}_write", target)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self.checkpoint(f"after_{checkpoint_prefix}_fsync", target)
            os.replace(temporary, target)
            self.checkpoint(f"after_{checkpoint_prefix}_replace", target)
            self.fsync_directory(target.parent)
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def copy_file_durable(
        self,
        source: Path,
        target: Path,
        *,
        checkpoint_prefix: str,
    ) -> None:
        destination = Path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
        )
        temporary = Path(temporary_name)
        try:
            self.checkpoint(f"before_{checkpoint_prefix}_copy", destination)
            with Path(source).open("rb") as incoming, os.fdopen(descriptor, "wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            os.replace(temporary, destination)
            self.checkpoint(f"after_{checkpoint_prefix}_replace", destination)
            self.fsync_directory(destination.parent)
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def publish_tree(self, staged_root: Path, target_root: Path) -> None:
        staged = Path(staged_root)
        target = Path(target_root)
        if target.exists():
            raise MigrationError("target_conflict", f"Target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint("before_target_rename", target)
        os.rename(staged, target)
        self.checkpoint("after_target_rename", target)
        self.fsync_directory(target.parent)


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _canonical_uuid(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise MachineDataPathError(f"{field_name} must be a UUID string.")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise MachineDataPathError(f"Invalid {field_name}: {value!r}") from exc


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _read_member_bytes(snapshot: SourceSnapshot, relative_path: str) -> bytes:
    member = snapshot.local_member(relative_path)
    with member.open_binary() as stream:
        data = stream.read()
    if len(data) != member.evidence.size or sha256_bytes(data) != member.evidence.raw_sha256:
        raise ArchiveVerificationError(f"Source changed while reading {relative_path}.")
    return data


def _read_json_member(snapshot: SourceSnapshot, relative_path: str) -> object:
    try:
        return json.loads(_read_member_bytes(snapshot, relative_path).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON in {relative_path}: {exc}") from exc


def _has_required_files(root: Path) -> bool:
    return all((root / name).is_file() for name in REQUIRED_CONFIG_NAMES)


def _normalize_selection(
    selection: CandidateSelection,
    policy: ArchivePolicy,
) -> tuple[SourceLocator, Path]:
    selected = selection.selected_path
    kind = selection.source_kind
    if kind == CandidateSourceKind.OPERATOR_SELECTED_ZIP:
        locator = discover_zip_source(
            selected,
            required_names=REQUIRED_CONFIG_NAMES,
            policy=policy,
        )
        return locator, selected
    if kind == CandidateSourceKind.CURRENT_CHECKOUT_LOCAL:
        local_root = selected / "local"
        version_path = selected / "VERSION"
    elif kind == CandidateSourceKind.OPERATOR_SELECTED_LOCAL:
        local_root = selected
        version_path = selected.parent / "VERSION"
        if _has_required_files(selected / "local"):
            raise ArchiveSafetyError(
                "Selected directory is both a direct candidate and a wrapper with local/."
            )
    elif kind == CandidateSourceKind.OPERATOR_SELECTED_WRAPPER:
        local_root = selected / "local"
        version_path = selected / "VERSION"
        if _has_required_files(selected):
            raise ArchiveSafetyError(
                "Selected wrapper is also a direct local candidate and is ambiguous."
            )
    elif kind == CandidateSourceKind.EXISTING_CANONICAL:
        local_root = selected / "config"
        version_path = selected / "VERSION"
    else:
        raise ArchiveSafetyError(f"Unsupported source kind: {kind.value}")
    locator = SourceLocator(
        container_kind="directory",
        selected_path=selected,
        local_root=local_root,
        version_path=version_path if version_path.exists() else None,
    )
    return locator, local_root.resolve(strict=False)


def _fatal_evidence(
    selection: CandidateSelection,
    message: str,
    *,
    inspected_at: str,
) -> CandidateEvidence:
    candidate_id = sha256_bytes(
        canonical_json_bytes(
            {"source_kind": selection.source_kind.value, "path": str(selection.selected_path)}
        )
    )
    return CandidateEvidence(
        candidate_id=candidate_id,
        source_kind=selection.source_kind,
        normalized_source=selection.selected_path,
        label=selection.label,
        inspected_at_utc=inspected_at,
        version_text=None,
        required_files=(),
        migratable_files=(),
        required_config_fingerprint=evidence_fingerprint(()),
        migratable_tree_fingerprint=evidence_fingerprint(()),
        full_source_fingerprint=evidence_fingerprint(()),
        safety_snapshot=MappingProxyType({}),
        identity_status="unknown",
        legacy_identity=None,
        calibration_memory_status="unknown",
        missing_calibration_memory_seed_files=(),
        preset_matches=(),
        individual_preset_matches=(),
        camera_preset_match=False,
        declared_version_mismatch=False,
        unclassified_source_paths=(),
        issues=(
            CandidateIssue(
                CandidateIssueSeverity.FATAL,
                "invalid_or_ambiguous_source",
                message,
            ),
        ),
    )


def _finite_coordinate(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _coordinate_object(value: object, label: str) -> dict[str, int | float]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    result: dict[str, int | float] = {}
    for axis in ("X", "Y", "Z"):
        coordinate = value.get(axis)
        if not _finite_coordinate(coordinate):
            raise ValueError(f"{label}.{axis} must be a finite numeric value.")
        result[axis] = coordinate
    return result


def _validate_safety_snapshot(payloads: Mapping[str, object]) -> dict[str, object]:
    locations = payloads["Locations.json"]
    assert isinstance(locations, dict)
    normalized_locations: dict[str, object] = {}
    for name, value in locations.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Every location name must be nonempty text.")
        normalized_locations[name] = _coordinate_object(value, f"location {name!r}")
    if "camera" not in locations:
        raise ValueError("Locations.json must contain the reserved lowercase 'camera'.")

    plates = payloads["Plates.json"]
    assert isinstance(plates, list)
    plate_snapshot: list[dict[str, object]] = []
    for index, plate in enumerate(plates):
        if not isinstance(plate, dict):
            raise ValueError(f"Plate index {index} must be an object.")
        calibrations = plate.get("calibrations", {})
        if not isinstance(calibrations, dict):
            raise ValueError(f"Plate index {index} calibrations must be an object.")
        normalized: dict[str, object] = {}
        if calibrations:
            if set(calibrations) != set(PLATE_CORNERS):
                raise ValueError(
                    f"Plate index {index} requires exactly four calibration corners."
                )
            for corner in PLATE_CORNERS:
                normalized[corner] = _coordinate_object(
                    calibrations[corner], f"plate index {index} {corner}"
                )
        plate_snapshot.append(
            {
                "name": plate.get("name", f"plate-{index}"),
                "calibrations": normalized,
            }
        )
    return {"locations": normalized_locations, "plates": plate_snapshot}


def _canonical_migratable_path(relative_path: str) -> str | None:
    if relative_path in REQUIRED_CONFIG_TYPES:
        return f"config/{relative_path}"
    if relative_path.startswith("CalibrationMemory/"):
        return relative_path
    if relative_path == "droplet_imager_optics.json":
        return "calibration/droplet_imager_optics.json"
    if relative_path.startswith("regulator_optimization/"):
        return f"calibration/{relative_path}"
    return None


def inspect_candidate(
    selection: CandidateSelection,
    *,
    preset_catalog: PresetFingerprintCatalog | None = None,
    archive_policy: ArchivePolicy | None = None,
    clock: Callable[[], str] = _utc_now,
) -> CandidateEvidence:
    policy = archive_policy or ArchivePolicy()
    catalog = preset_catalog or PresetFingerprintCatalog.load()
    inspected_at = clock()
    try:
        locator, normalized_source = _normalize_selection(selection, policy)
        snapshot = capture_source(locator, policy)
    except (OSError, ValueError, ArchiveSafetyError, ArchiveVerificationError) as exc:
        return _fatal_evidence(selection, str(exc), inspected_at=inspected_at)

    issues: list[CandidateIssue] = []
    by_path = {member.relative_path: member for member in snapshot.local_members}
    payloads: dict[str, object] = {}
    required_evidence: list[FileEvidence] = []
    for filename, expected_type in REQUIRED_CONFIG_TYPES.items():
        member = by_path.get(filename)
        if member is None:
            issues.append(
                CandidateIssue(
                    CandidateIssueSeverity.FATAL,
                    "missing_required_config",
                    f"Required machine config is missing: {filename}",
                    filename,
                )
            )
            continue
        try:
            payload = _read_json_member(snapshot, filename)
            if not isinstance(payload, expected_type):
                raise ValueError(
                    f"expected top-level {expected_type.__name__}, got {type(payload).__name__}"
                )
            semantic_hash = semantic_json_sha256(payload)
            payloads[filename] = payload
            required_evidence.append(
                FileEvidence(
                    filename,
                    member.evidence.size,
                    member.evidence.raw_sha256,
                    semantic_hash,
                )
            )
        except (ValueError, ArchiveVerificationError) as exc:
            issues.append(
                CandidateIssue(
                    CandidateIssueSeverity.FATAL,
                    "invalid_required_config",
                    f"Invalid {filename}: {exc}",
                    filename,
                )
            )

    safety_snapshot: dict[str, object] = {}
    if set(payloads) == set(REQUIRED_CONFIG_TYPES):
        try:
            safety_snapshot = _validate_safety_snapshot(payloads)
        except ValueError as exc:
            issues.append(
                CandidateIssue(
                    CandidateIssueSeverity.FATAL,
                    "invalid_safety_snapshot",
                    str(exc),
                )
            )

    calibration_members = {
        path: member
        for path, member in by_path.items()
        if path.startswith("CalibrationMemory/")
    }
    missing_seeds: list[str] = []
    calibration_directory_exists = "CalibrationMemory" in snapshot.local_directories
    if calibration_members or calibration_directory_exists:
        calibration_status = "present_complete"
        for relative, expected_type in CALIBRATION_MEMORY_SEED_TYPES.items():
            source_path = f"CalibrationMemory/{relative}"
            if source_path not in calibration_members:
                missing_seeds.append(relative)
                continue
            try:
                payload = _read_json_member(snapshot, source_path)
                if not isinstance(payload, expected_type):
                    raise ValueError(
                        f"expected top-level {expected_type.__name__}, got {type(payload).__name__}"
                    )
            except (ValueError, ArchiveVerificationError) as exc:
                issues.append(
                    CandidateIssue(
                        CandidateIssueSeverity.FATAL,
                        "invalid_calibration_memory_seed",
                        f"Invalid {source_path}: {exc}",
                        source_path,
                    )
                )
        if missing_seeds:
            calibration_status = "present_incomplete"
            issues.append(
                CandidateIssue(
                    CandidateIssueSeverity.WARNING,
                    "missing_calibration_memory_seeds",
                    "CalibrationMemory is missing known seed files: "
                    + ", ".join(missing_seeds),
                )
            )
    else:
        calibration_status = "absent"
        missing_seeds = list(CALIBRATION_MEMORY_SEED_TYPES)
        issues.append(
            CandidateIssue(
                CandidateIssueSeverity.WARNING,
                "calibration_memory_absent",
                "CalibrationMemory is absent and will not be synthesized.",
            )
        )

    identity_status = "absent"
    legacy_identity = None
    if "machine_identity.json" in by_path:
        try:
            identity_payload = _read_json_member(snapshot, "machine_identity.json")
            legacy_identity = parse_machine_identity(
                identity_payload, allow_legacy=True, allow_unassigned=True
            )
            identity_status = (
                "unassigned"
                if legacy_identity.machine_id.casefold() == UNASSIGNED_MACHINE_ID.casefold()
                else "assigned"
            )
            if identity_status == "unassigned":
                issues.append(
                    CandidateIssue(
                        CandidateIssueSeverity.WARNING,
                        "identity_unassigned",
                        "Legacy identity is LC-UNASSIGNED and cannot authorize import.",
                        "machine_identity.json",
                    )
                )
        except (ValueError, MachineIdentityError, ArchiveVerificationError) as exc:
            identity_status = "invalid"
            issues.append(
                CandidateIssue(
                    CandidateIssueSeverity.FATAL,
                    "invalid_legacy_identity",
                    f"Invalid legacy identity: {exc}",
                    "machine_identity.json",
                )
            )
    else:
        issues.append(
            CandidateIssue(
                CandidateIssueSeverity.WARNING,
                "identity_absent",
                "Legacy machine identity is absent; explicit target identity is required.",
            )
        )

    migratable: list[FileEvidence] = []
    unclassified: list[str] = []
    for path, member in sorted(by_path.items()):
        canonical_path = _canonical_migratable_path(path)
        if canonical_path is not None:
            semantic = next(
                (
                    evidence.semantic_json_sha256
                    for evidence in required_evidence
                    if evidence.relative_path == path
                ),
                None,
            )
            migratable.append(
                FileEvidence(
                    canonical_path,
                    member.evidence.size,
                    member.evidence.raw_sha256,
                    semantic,
                )
            )
        elif path != "machine_identity.json":
            unclassified.append(path)

    version_text = None
    if snapshot.version_member is not None:
        try:
            with snapshot.version_member.open_binary() as stream:
                version_text = stream.read().decode("utf-8").strip() or None
        except (UnicodeDecodeError, OSError, ArchiveVerificationError) as exc:
            issues.append(
                CandidateIssue(
                    CandidateIssueSeverity.WARNING,
                    "invalid_version_evidence",
                    f"VERSION evidence is unreadable: {exc}",
                )
            )
    else:
        issues.append(
            CandidateIssue(
                CandidateIssueSeverity.WARNING,
                "version_absent",
                "VERSION evidence is absent; the source cohort is not guessed.",
            )
        )

    semantic_by_name = {
        item.relative_path: item.semantic_json_sha256 for item in required_evidence
    }
    preset_matches = tuple(
        cohort.cohort
        for cohort in catalog.cohorts
        if all(
            semantic_by_name.get(name) == digest
            for name, digest in cohort.config_semantic_sha256.items()
        )
    )
    individual_matches = tuple(
        sorted(
            f"{name}:{cohort.cohort}"
            for cohort in catalog.cohorts
            for name, digest in cohort.config_semantic_sha256.items()
            if semantic_by_name.get(name) == digest
        )
    )
    camera_hash = None
    if "Locations.json" in payloads and isinstance(payloads["Locations.json"], dict):
        camera = payloads["Locations.json"].get("camera")
        if isinstance(camera, dict):
            camera_hash = semantic_json_sha256(camera)
    camera_preset_match = any(
        camera_hash == cohort.camera_semantic_sha256 for cohort in catalog.cohorts
    )
    declared_mismatch = bool(
        version_text
        and preset_matches
        and not any(
            version_text in cohort.declared_versions
            for cohort in catalog.cohorts
            if cohort.cohort in preset_matches
        )
    )
    if preset_matches:
        issues.append(
            CandidateIssue(
                CandidateIssueSeverity.WARNING,
                "preset_like",
                "Candidate completely matches historical preset cohort(s): "
                + ", ".join(preset_matches),
            )
        )
    if camera_preset_match:
        issues.append(
            CandidateIssue(
                CandidateIssueSeverity.WARNING,
                "camera_preset_match",
                "Camera coordinates match a historical preset and remain unverified.",
                "Locations.json",
            )
        )
    if declared_mismatch:
        issues.append(
            CandidateIssue(
                CandidateIssueSeverity.WARNING,
                "declared_version_preset_mismatch",
                "Declared VERSION does not match the detected complete preset cohort.",
            )
        )
    if unclassified:
        issues.append(
            CandidateIssue(
                CandidateIssueSeverity.WARNING,
                "unclassified_source_paths",
                "Unknown local paths are backup-only until ownership is reviewed.",
            )
        )
    if selection.source_kind == CandidateSourceKind.EXISTING_CANONICAL:
        issues.append(
            CandidateIssue(
                CandidateIssueSeverity.INFO,
                "existing_canonical_inspection_only",
                "Existing canonical roots are reconciliation evidence, not import candidates.",
            )
        )

    required_tuple = tuple(sorted(required_evidence, key=lambda item: item.relative_path))
    migratable_tuple = tuple(sorted(migratable, key=lambda item: item.relative_path))
    candidate_id = sha256_bytes(
        canonical_json_bytes(
            {
                "source_kind": selection.source_kind.value,
                "path": str(normalized_source),
                "full_source_fingerprint": snapshot.full_source_fingerprint,
            }
        )
    )
    return CandidateEvidence(
        candidate_id=candidate_id,
        source_kind=selection.source_kind,
        normalized_source=normalized_source,
        label=selection.label,
        inspected_at_utc=inspected_at,
        version_text=version_text,
        required_files=required_tuple,
        migratable_files=migratable_tuple,
        required_config_fingerprint=evidence_fingerprint(required_tuple),
        migratable_tree_fingerprint=evidence_fingerprint(migratable_tuple),
        full_source_fingerprint=snapshot.full_source_fingerprint,
        safety_snapshot=MappingProxyType(safety_snapshot),
        identity_status=identity_status,
        legacy_identity=legacy_identity,
        calibration_memory_status=calibration_status,
        missing_calibration_memory_seed_files=tuple(sorted(missing_seeds)),
        preset_matches=preset_matches,
        individual_preset_matches=individual_matches,
        camera_preset_match=camera_preset_match,
        declared_version_mismatch=declared_mismatch,
        unclassified_source_paths=tuple(unclassified),
        issues=tuple(issues),
        _source_locator=locator,
    )


def classify_candidates(candidates: Sequence[CandidateEvidence]) -> CandidateComparison:
    ids = [candidate.candidate_id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("Candidate IDs must be unique for comparison.")
    relations: list[CandidateRelation] = []
    for index, first in enumerate(candidates):
        for second in candidates[index + 1 :]:
            if (
                first.migratable_tree_fingerprint == second.migratable_tree_fingerprint
                and first.identity_status == second.identity_status
                and first.legacy_identity == second.legacy_identity
            ):
                classification = "exact_duplicate"
            elif first.required_config_fingerprint == second.required_config_fingerprint:
                classification = "config_duplicates_with_optional_conflict"
            else:
                classification = "conflict"
            relations.append(
                CandidateRelation(first.candidate_id, second.candidate_id, classification)
            )
    return CandidateComparison(tuple(relations))


def build_migration_workspace_paths(
    base: MachineDataBasePaths,
    machine_uuid: str,
    migration_id: str,
) -> MigrationWorkspacePaths:
    canonical_machine = build_machine_data_paths(base, machine_uuid).machine_uuid
    canonical_migration = _canonical_uuid(migration_id, "migration_id")
    root = base.root / "migration_work" / canonical_machine / canonical_migration
    return MigrationWorkspacePaths(
        base,
        canonical_machine,
        canonical_migration,
        root,
        root / "journal.json",
        root / "source_backup.zip",
        root / "staged_machine",
    )


def new_migration_workspace_paths(
    base: MachineDataBasePaths,
    machine_uuid: str,
    *,
    migration_id_factory: Callable[[], object] = uuid4,
) -> MigrationWorkspacePaths:
    return build_migration_workspace_paths(
        base, machine_uuid, str(migration_id_factory())
    )


def validate_state_transition(prior: MigrationState, current: MigrationState) -> None:
    if _LEGAL_NEXT_STATE.get(MigrationState(prior)) != MigrationState(current):
        raise MigrationRecoveryRequired(
            f"Illegal migration state transition: {prior.value} -> {current.value}"
        )


def _lock_path(workspace: MigrationWorkspacePaths) -> Path:
    return (
        workspace.base.root / "locks" / f"migration-{workspace.machine_uuid}.lock"
    ).resolve(strict=False)


def _assert_lock(workspace: MigrationWorkspacePaths, acquired_lock: MigrationLockToken) -> None:
    if acquired_lock is None or not callable(getattr(acquired_lock, "assert_owns", None)):
        raise MigrationError("lock_unavailable", "An acquired migration lock is required.")
    try:
        acquired_lock.assert_owns(workspace.machine_uuid, _lock_path(workspace))
    except Exception as exc:
        raise MigrationError("lock_unavailable", f"Migration lock is not owned: {exc}") from exc


def _relative_to_base(path: Path, base: MachineDataBasePaths) -> str:
    try:
        return Path(path).resolve(strict=False).relative_to(base.root).as_posix()
    except ValueError as exc:
        raise MachineDataPathError(f"Artifact escaped machine-data base: {path}") from exc


def _load_journal(workspace: MigrationWorkspacePaths) -> dict[str, object] | None:
    if not workspace.journal_path.exists():
        return None
    try:
        payload = json.loads(workspace.journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationRecoveryRequired(f"Cannot parse migration journal: {exc}") from exc
    if not isinstance(payload, dict):
        raise MigrationRecoveryRequired("Migration journal must be a JSON object.")
    if payload.get("schema_name") != MIGRATION_JOURNAL_SCHEMA_NAME or payload.get(
        "schema_version"
    ) != MIGRATION_JOURNAL_SCHEMA_VERSION:
        raise MigrationRecoveryRequired("Unknown migration journal schema.")
    if payload.get("migration_id") != workspace.migration_id or payload.get(
        "machine_uuid"
    ) != workspace.machine_uuid:
        raise MigrationRecoveryRequired("Migration journal identity does not match workspace.")
    try:
        state = MigrationState(payload.get("state"))
    except ValueError as exc:
        raise MigrationRecoveryRequired("Unknown migration journal state.") from exc
    if not _is_utc_timestamp(payload.get("updated_at_utc")):
        raise MigrationRecoveryRequired("Migration journal timestamp is not UTC.")
    directory_fsync_supported = payload.get("directory_fsync_supported")
    if directory_fsync_supported is not None and type(directory_fsync_supported) is not bool:
        raise MigrationRecoveryRequired(
            "Migration journal directory fsync capability is invalid."
        )
    candidate_id = payload.get("candidate_id")
    if not _is_sha256(candidate_id):
        raise MigrationRecoveryRequired("Migration journal candidate_id is invalid.")
    for name in ("required_config_fingerprint", "migratable_tree_fingerprint"):
        if not _is_sha256(payload.get(name)):
            raise MigrationRecoveryRequired(
                f"Migration journal {name} is invalid."
            )
    transitions = payload.get("transitions")
    if not isinstance(transitions, list):
        raise MigrationRecoveryRequired("Migration journal transitions must be a list.")
    expected_count = _STATE_ORDER.index(state)
    if len(transitions) != expected_count:
        raise MigrationRecoveryRequired(
            "Migration journal transition count does not match its current state."
        )
    for index, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            raise MigrationRecoveryRequired("Migration journal transition is invalid.")
        expected_prior = _STATE_ORDER[index]
        expected_current = _STATE_ORDER[index + 1]
        if (
            transition.get("prior") != expected_prior.value
            or transition.get("current") != expected_current.value
            or not _is_utc_timestamp(transition.get("at_utc"))
        ):
            raise MigrationRecoveryRequired(
                "Migration journal contains an illegal or malformed transition."
            )
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise MigrationRecoveryRequired("Migration journal artifacts must be an object.")
    for label, relative in artifacts.items():
        if not isinstance(label, str) or not isinstance(relative, str) or not relative:
            raise MigrationRecoveryRequired("Migration journal artifact entry is invalid.")
        pure = Path(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise MigrationRecoveryRequired("Migration journal artifact path is unsafe.")
        resolved = (workspace.base.root / pure).resolve(strict=False)
        if workspace.base.root not in resolved.parents:
            raise MigrationRecoveryRequired("Migration journal artifact escaped the base.")
    return payload


def _advance_journal(
    workspace: MigrationWorkspacePaths,
    state: MigrationState,
    *,
    io: MigrationFileOps,
    clock: Callable[[], str],
    candidate: CandidateEvidence | None = None,
    artifacts: Mapping[str, str] | None = None,
) -> None:
    existing = _load_journal(workspace)
    if existing is None:
        if state != MigrationState.CANDIDATE_SELECTED:
            raise MigrationRecoveryRequired("Migration journal must begin at candidate_selected.")
        transitions: list[object] = []
        payload: dict[str, object] = {
            "schema_name": MIGRATION_JOURNAL_SCHEMA_NAME,
            "schema_version": MIGRATION_JOURNAL_SCHEMA_VERSION,
            "migration_id": workspace.migration_id,
            "machine_uuid": workspace.machine_uuid,
            "state": state.value,
            "candidate_id": candidate.candidate_id if candidate else None,
            "required_config_fingerprint": (
                candidate.required_config_fingerprint if candidate else None
            ),
            "migratable_tree_fingerprint": (
                candidate.migratable_tree_fingerprint if candidate else None
            ),
            "transitions": transitions,
            "artifacts": dict(artifacts or {}),
            "directory_fsync_supported": io.directory_fsync_supported,
            "updated_at_utc": clock(),
        }
    else:
        prior = MigrationState(existing["state"])
        if candidate is not None and existing.get("candidate_id") != candidate.candidate_id:
            raise MigrationRecoveryRequired(
                "Migration journal belongs to different candidate evidence."
            )
        if prior == state:
            return
        if _STATE_ORDER.index(prior) > _STATE_ORDER.index(state):
            # Re-entering a completed earlier checkpoint is idempotent; it is
            # not a persisted state regression.
            return
        validate_state_transition(prior, state)
        payload = dict(existing)
        transitions = list(payload.get("transitions", []))
        transitions.append(
            {"prior": prior.value, "current": state.value, "at_utc": clock()}
        )
        payload["transitions"] = transitions
        payload["state"] = state.value
        payload["updated_at_utc"] = clock()
        payload["directory_fsync_supported"] = io.directory_fsync_supported
        merged = dict(payload.get("artifacts", {}))
        merged.update(artifacts or {})
        payload["artifacts"] = merged
    workspace.root.mkdir(parents=True, exist_ok=True)
    io.atomic_write_json(
        workspace.journal_path, payload, checkpoint_prefix="journal"
    )


def _preflight_space(
    workspace: MigrationWorkspacePaths,
    required_bytes: int,
    *,
    policy: MigrationPolicy,
    io: MigrationFileOps,
) -> None:
    workspace.base.root.mkdir(parents=True, exist_ok=True)
    available = io.disk_usage(workspace.base.root).free
    required = required_bytes + policy.safety_margin_bytes
    if available < required:
        raise MigrationError(
            "insufficient_space",
            f"Migration requires {required} bytes but only {available} are free.",
        )


def _target_identity(identity: MachineIdentity) -> MachineIdentity:
    try:
        return parse_machine_identity(identity.to_payload())
    except (AttributeError, MachineIdentityError) as exc:
        raise MigrationError("identity_conflict", f"Target identity is invalid: {exc}") from exc


def _candidate_manifest_metadata(
    candidate: CandidateEvidence,
    workspace: MigrationWorkspacePaths,
    target_identity: MachineIdentity | None,
    clock: Callable[[], str],
    directory_fsync_supported: bool | None,
) -> dict[str, object]:
    return {
        "migration_id": workspace.migration_id,
        "created_at_utc": clock(),
        "source_kind": candidate.source_kind.value,
        "source_path": str(candidate.normalized_source),
        "source_label": candidate.label,
        "source_version": candidate.version_text,
        "candidate_id": candidate.candidate_id,
        "target_identity": target_identity.to_payload() if target_identity else None,
        "required_config_fingerprint": candidate.required_config_fingerprint,
        "migratable_tree_fingerprint": candidate.migratable_tree_fingerprint,
        "full_source_fingerprint": candidate.full_source_fingerprint,
        "safety_snapshot": dict(candidate.safety_snapshot),
        "preset_matches": list(candidate.preset_matches),
        "camera_preset_match": candidate.camera_preset_match,
        "identity_status": candidate.identity_status,
        "calibration_memory_status": candidate.calibration_memory_status,
        "unclassified_source_paths": list(candidate.unclassified_source_paths),
        "candidate_evidence": candidate.to_payload(),
        "directory_fsync_supported": directory_fsync_supported,
        "intentionally_omitted_items": [
            "Files classified as archive-only are not copied into canonical config."
        ],
    }


def create_verified_backup(
    candidate: CandidateEvidence,
    *,
    workspace: MigrationWorkspacePaths,
    target_identity: MachineIdentity | None,
    acquired_lock: MigrationLockToken,
    io: MigrationFileOps | None = None,
    policy: MigrationPolicy | None = None,
    firmware_artifact: Path | None = None,
    clock: Callable[[], str] = _utc_now,
) -> VerifiedBackup:
    operations = io or MigrationFileOps()
    migration_policy = policy or MigrationPolicy()
    _assert_lock(workspace, acquired_lock)
    if workspace.machine_uuid != (
        _target_identity(target_identity).machine_uuid if target_identity else workspace.machine_uuid
    ):
        raise MigrationError("identity_conflict", "Target identity UUID differs from workspace.")
    if not candidate.is_importable or candidate._source_locator is None:
        raise CandidateNotImportable("Candidate has fatal issues or is inspection-only.")
    if candidate.legacy_identity and candidate.identity_status == "assigned" and target_identity:
        if (
            candidate.legacy_identity.machine_uuid != target_identity.machine_uuid
            or candidate.legacy_identity.machine_id != target_identity.machine_id
        ):
            raise MigrationError(
                "identity_conflict",
                "Assigned legacy identity differs from the explicit target identity.",
            )

    if workspace.backup_path.exists():
        try:
            existing = verify_backup_archive(
                workspace.backup_path, policy=migration_policy.archive_policy
            )
        except (ArchiveSafetyError, ArchiveVerificationError, OSError) as exc:
            raise MigrationRecoveryRequired(
                f"Existing workspace backup is not trustworthy: {exc}"
            ) from exc
        if (
            existing.manifest.get("candidate_id") == candidate.candidate_id
            and existing.manifest.get("migration_id") == workspace.migration_id
        ):
            _advance_journal(
                workspace,
                MigrationState.BACKUP_VERIFIED,
                io=operations,
                clock=clock,
                candidate=candidate,
                artifacts={
                    "backup": _relative_to_base(
                        workspace.backup_path, workspace.base
                    )
                },
            )
            return existing
        raise MigrationRecoveryRequired("Existing workspace backup belongs to different evidence.")

    _advance_journal(
        workspace,
        MigrationState.CANDIDATE_SELECTED,
        io=operations,
        clock=clock,
        candidate=candidate,
    )
    fresh_snapshot = capture_source(
        candidate._source_locator, migration_policy.archive_policy
    )
    if fresh_snapshot.full_source_fingerprint != candidate.full_source_fingerprint:
        raise MigrationError("source_changed", "Candidate changed after inspection.")
    _advance_journal(
        workspace,
        MigrationState.SOURCE_VALIDATED,
        io=operations,
        clock=clock,
        candidate=candidate,
    )
    firmware_peak_bytes = 0
    if firmware_artifact is not None:
        try:
            firmware_peak_bytes = Path(firmware_artifact).stat().st_size * 2
        except OSError as exc:
            raise MigrationError(
                "backup_failed", f"Cannot size firmware package evidence: {exc}"
            ) from exc
    _preflight_space(
        workspace,
        fresh_snapshot.total_local_bytes * 2
        + sum(item.size for item in candidate.migratable_files)
        + firmware_peak_bytes,
        policy=migration_policy,
        io=operations,
    )
    try:
        backup = _create_backup_archive(
            fresh_snapshot,
            workspace.backup_path,
            manifest_metadata=_candidate_manifest_metadata(
                candidate,
                workspace,
                target_identity,
                clock,
                operations.directory_fsync_supported,
            ),
            policy=migration_policy.archive_policy,
            io=operations,
            firmware_artifact=firmware_artifact,
        )
    except SourceChangedDuringArchive as exc:
        raise MigrationError("source_changed", str(exc)) from exc
    except Exception as exc:
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError("backup_failed", f"Backup creation failed: {exc}") from exc
    after_snapshot = capture_source(
        candidate._source_locator, migration_policy.archive_policy
    )
    if after_snapshot.full_source_fingerprint != candidate.full_source_fingerprint:
        raise MigrationError(
            "source_changed",
            "Candidate changed while the verified backup was being created.",
        )
    _advance_journal(
        workspace,
        MigrationState.BACKUP_VERIFIED,
        io=operations,
        clock=clock,
        candidate=candidate,
        artifacts={"backup": _relative_to_base(workspace.backup_path, workspace.base)},
    )
    return backup


def _parse_receipt(payload: object) -> MigrationReceipt:
    if not isinstance(payload, dict):
        raise MigrationRecoveryRequired("Migration receipt must be a JSON object.")
    if payload.get("schema_name") != MIGRATION_RECEIPT_SCHEMA_NAME or payload.get(
        "schema_version"
    ) != MIGRATION_RECEIPT_SCHEMA_VERSION:
        raise MigrationRecoveryRequired("Unknown migration receipt schema.")
    if any(payload.get(name) is not False for name in _FALSE_AUTHORIZATION_FIELDS):
        raise MigrationRecoveryRequired("Milestone 2 receipt cannot authorize activation.")
    try:
        state = MigrationState(payload.get("state"))
        if state != MigrationState.COPIED_UNVERIFIED:
            raise ValueError
        migration_id = _canonical_uuid(payload.get("migration_id"), "migration_id")
        machine_uuid = _canonical_uuid(payload.get("machine_uuid"), "machine_uuid")
    except (ValueError, MachineDataPathError) as exc:
        raise MigrationRecoveryRequired("Invalid migration receipt identity/state.") from exc
    required_text = (
        "machine_id",
        "source_kind",
        "candidate_id",
        "required_config_fingerprint",
        "migratable_tree_fingerprint",
        "full_source_fingerprint",
        "backup_archive_sha256",
        "completed_at_utc",
    )
    if not all(isinstance(payload.get(name), str) and payload.get(name) for name in required_text):
        raise MigrationRecoveryRequired("Migration receipt has missing text fields.")
    if payload.get("source_kind") not in {kind.value for kind in CandidateSourceKind}:
        raise MigrationRecoveryRequired("Migration receipt source_kind is unknown.")
    if payload.get("source_version") is not None and not isinstance(
        payload.get("source_version"), str
    ):
        raise MigrationRecoveryRequired("Migration receipt source_version is invalid.")
    for name in (
        "candidate_id",
        "required_config_fingerprint",
        "migratable_tree_fingerprint",
        "full_source_fingerprint",
        "backup_archive_sha256",
    ):
        if not _is_sha256(payload.get(name)):
            raise MigrationRecoveryRequired(f"Migration receipt {name} is invalid.")
    if type(payload.get("preset_like")) is not bool or type(
        payload.get("camera_preset_match")
    ) is not bool:
        raise MigrationRecoveryRequired("Migration receipt preset flags must be booleans.")
    if not _is_utc_timestamp(payload.get("completed_at_utc")):
        raise MigrationRecoveryRequired("Migration receipt completed_at_utc is invalid.")
    unclassified = payload.get("unclassified_source_paths")
    if not isinstance(unclassified, list) or not all(isinstance(item, str) for item in unclassified):
        raise MigrationRecoveryRequired("Invalid receipt unclassified path inventory.")
    return MigrationReceipt(
        migration_id=migration_id,
        state=state,
        machine_id=payload["machine_id"],
        machine_uuid=machine_uuid,
        source_kind=payload["source_kind"],
        source_version=payload.get("source_version"),
        candidate_id=payload["candidate_id"],
        required_config_fingerprint=payload["required_config_fingerprint"],
        migratable_tree_fingerprint=payload["migratable_tree_fingerprint"],
        full_source_fingerprint=payload["full_source_fingerprint"],
        backup_archive_sha256=payload["backup_archive_sha256"],
        preset_like=payload.get("preset_like") is True,
        camera_preset_match=payload.get("camera_preset_match") is True,
        unclassified_source_paths=tuple(unclassified),
        completed_at_utc=payload["completed_at_utc"],
    )


def parse_migration_receipt(payload: object) -> MigrationReceipt:
    """Public strict parser for immutable published M2 receipts."""

    return _parse_receipt(payload)


def load_migration_receipt(path: str | Path) -> MigrationReceipt:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationRecoveryRequired(f"Cannot read migration receipt: {exc}") from exc
    return parse_migration_receipt(payload)


def _parse_evidence_file_list(value: object, label: str) -> tuple[FileEvidence, ...]:
    if not isinstance(value, list):
        raise MigrationRecoveryRequired(f"Candidate {label} must be a list.")
    parsed: list[FileEvidence] = []
    paths: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise MigrationRecoveryRequired(f"Candidate {label} entry must be an object.")
        relative_path = raw.get("relative_path")
        size = raw.get("size")
        digest = raw.get("raw_sha256")
        semantic = raw.get("semantic_json_sha256")
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or relative_path.startswith(("/", "\\"))
            or ".." in Path(relative_path.replace("\\", "/")).parts
            or type(size) is not int
            or size < 0
            or not _is_sha256(digest)
            or (semantic is not None and not _is_sha256(semantic))
        ):
            raise MigrationRecoveryRequired(f"Candidate {label} evidence is invalid.")
        normalized = relative_path.replace("\\", "/")
        if normalized.casefold() in paths:
            raise MigrationRecoveryRequired(f"Candidate {label} paths collide.")
        paths.add(normalized.casefold())
        parsed.append(FileEvidence(normalized, size, digest, semantic))
    return tuple(parsed)


def _parse_text_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise MigrationRecoveryRequired(f"Candidate {label} must contain text values.")
    if len({item.casefold() for item in value}) != len(value):
        raise MigrationRecoveryRequired(f"Candidate {label} contains duplicates.")
    return tuple(value)


def parse_candidate_evidence(payload: object) -> CandidateEvidence:
    """Strictly reconstruct published candidate evidence without a live source."""

    if not isinstance(payload, dict):
        raise MigrationRecoveryRequired("Candidate evidence must be a JSON object.")
    try:
        source_kind = CandidateSourceKind(payload.get("source_kind"))
    except ValueError as exc:
        raise MigrationRecoveryRequired("Candidate source_kind is unknown.") from exc
    candidate_id = payload.get("candidate_id")
    normalized_source = payload.get("normalized_source")
    label = payload.get("label")
    inspected_at = payload.get("inspected_at_utc")
    if not _is_sha256(candidate_id):
        raise MigrationRecoveryRequired("Candidate ID must be SHA-256 text.")
    if not isinstance(normalized_source, str) or not Path(normalized_source).is_absolute():
        raise MigrationRecoveryRequired("Candidate normalized_source must be absolute.")
    if not isinstance(label, str) or not _is_utc_timestamp(inspected_at):
        raise MigrationRecoveryRequired("Candidate label/timestamp is invalid.")
    version_text = payload.get("version_text")
    if version_text is not None and not isinstance(version_text, str):
        raise MigrationRecoveryRequired("Candidate version_text is invalid.")

    fingerprint_fields = (
        "required_config_fingerprint",
        "migratable_tree_fingerprint",
        "full_source_fingerprint",
    )
    if not all(_is_sha256(payload.get(name)) for name in fingerprint_fields):
        raise MigrationRecoveryRequired("Candidate fingerprints are invalid.")
    safety_snapshot = payload.get("safety_snapshot")
    if not isinstance(safety_snapshot, dict):
        raise MigrationRecoveryRequired("Candidate safety snapshot must be an object.")
    identity_status = payload.get("identity_status")
    calibration_status = payload.get("calibration_memory_status")
    if not isinstance(identity_status, str) or not isinstance(calibration_status, str):
        raise MigrationRecoveryRequired("Candidate status fields must be text.")
    legacy_identity_payload = payload.get("legacy_identity")
    legacy_identity = None
    if legacy_identity_payload is not None:
        try:
            legacy_identity = parse_machine_identity(
                legacy_identity_payload,
                allow_legacy=True,
                allow_unassigned=True,
            )
        except MachineIdentityError as exc:
            raise MigrationRecoveryRequired(f"Candidate identity is invalid: {exc}") from exc
    booleans = (
        "camera_preset_match",
        "declared_version_mismatch",
    )
    if any(type(payload.get(name)) is not bool for name in booleans):
        raise MigrationRecoveryRequired("Candidate preset/version flags must be booleans.")

    raw_issues = payload.get("issues")
    if not isinstance(raw_issues, list):
        raise MigrationRecoveryRequired("Candidate issues must be a list.")
    issues: list[CandidateIssue] = []
    for raw in raw_issues:
        if not isinstance(raw, dict):
            raise MigrationRecoveryRequired("Candidate issue must be an object.")
        try:
            severity = CandidateIssueSeverity(raw.get("severity"))
        except ValueError as exc:
            raise MigrationRecoveryRequired("Candidate issue severity is invalid.") from exc
        code = raw.get("code")
        message = raw.get("message")
        relative_path = raw.get("relative_path")
        if (
            not isinstance(code, str)
            or not code
            or not isinstance(message, str)
            or not message
            or (relative_path is not None and not isinstance(relative_path, str))
        ):
            raise MigrationRecoveryRequired("Candidate issue fields are invalid.")
        issues.append(CandidateIssue(severity, code, message, relative_path))

    candidate = CandidateEvidence(
        candidate_id=candidate_id,
        source_kind=source_kind,
        normalized_source=Path(normalized_source).resolve(strict=False),
        label=label,
        inspected_at_utc=inspected_at,
        version_text=version_text,
        required_files=_parse_evidence_file_list(
            payload.get("required_files"), "required_files"
        ),
        migratable_files=_parse_evidence_file_list(
            payload.get("migratable_files"), "migratable_files"
        ),
        required_config_fingerprint=payload["required_config_fingerprint"],
        migratable_tree_fingerprint=payload["migratable_tree_fingerprint"],
        full_source_fingerprint=payload["full_source_fingerprint"],
        safety_snapshot=MappingProxyType(dict(safety_snapshot)),
        identity_status=identity_status,
        legacy_identity=legacy_identity,
        calibration_memory_status=calibration_status,
        missing_calibration_memory_seed_files=_parse_text_tuple(
            payload.get("missing_calibration_memory_seed_files"),
            "missing_calibration_memory_seed_files",
        ),
        preset_matches=_parse_text_tuple(payload.get("preset_matches"), "preset_matches"),
        individual_preset_matches=_parse_text_tuple(
            payload.get("individual_preset_matches"), "individual_preset_matches"
        ),
        camera_preset_match=payload["camera_preset_match"],
        declared_version_mismatch=payload["declared_version_mismatch"],
        unclassified_source_paths=_parse_text_tuple(
            payload.get("unclassified_source_paths"), "unclassified_source_paths"
        ),
        issues=tuple(issues),
    )
    if "is_importable" in payload and payload.get("is_importable") is not candidate.is_importable:
        raise MigrationRecoveryRequired("Candidate is_importable evidence is inconsistent.")
    return candidate


def load_candidate_evidence(path: str | Path) -> CandidateEvidence:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationRecoveryRequired(f"Cannot read candidate evidence: {exc}") from exc
    return parse_candidate_evidence(payload)


def _manifest_candidate(manifest: Mapping[str, object]) -> Mapping[str, object]:
    payload = manifest.get("candidate_evidence")
    if not isinstance(payload, dict):
        raise MigrationRecoveryRequired("Backup lacks candidate evidence.")
    return payload


def _write_stage_from_backup(
    backup: VerifiedBackup,
    *,
    workspace: MigrationWorkspacePaths,
    target_paths: MachineDataPaths,
    target_identity: MachineIdentity,
    io: MigrationFileOps,
    policy: MigrationPolicy,
    clock: Callable[[], str],
) -> MigrationReceipt:
    stage = workspace.staged_machine_root
    if stage.exists():
        return _verify_machine_tree(
            stage,
            expected_uuid=target_paths.machine_uuid,
            archive_policy=policy.archive_policy,
        )
    stage.mkdir(parents=True, exist_ok=False)
    try:
        manifest = backup.manifest
        candidate_payload = _manifest_candidate(manifest)
        migratable_items = candidate_payload.get("migratable_files")
        if not isinstance(migratable_items, list):
            raise MigrationRecoveryRequired("Backup candidate migratable inventory is invalid.")
        with open_verified_backup(backup, policy=policy.archive_policy) as reader:
            for item in migratable_items:
                if not isinstance(item, dict):
                    raise MigrationRecoveryRequired("Invalid migratable file evidence.")
                canonical_path = item.get("relative_path")
                if not isinstance(canonical_path, str):
                    raise MigrationRecoveryRequired("Migratable path must be text.")
                if canonical_path.startswith("config/"):
                    source_relative = canonical_path.removeprefix("config/")
                elif canonical_path.startswith("CalibrationMemory/"):
                    source_relative = canonical_path
                elif canonical_path == "calibration/droplet_imager_optics.json":
                    source_relative = "droplet_imager_optics.json"
                elif canonical_path.startswith("calibration/regulator_optimization/"):
                    source_relative = canonical_path.removeprefix("calibration/")
                else:
                    raise MigrationRecoveryRequired(
                        f"Unknown canonical migration path: {canonical_path}"
                    )
                data = reader.read(f"source/local/{source_relative}")
                if len(data) != item.get("size") or sha256_bytes(data) != item.get("raw_sha256"):
                    raise MigrationRecoveryRequired(
                        f"Verified backup evidence mismatch for {source_relative}."
                    )
                io.write_bytes_durable(
                    stage / canonical_path,
                    data,
                    checkpoint_prefix="staged_member",
                )

        io.write_bytes_durable(
            stage / "metadata" / "machine_identity.json",
            canonical_json_bytes(target_identity.to_payload()) + b"\n",
            checkpoint_prefix="staged_identity",
        )
        io.write_bytes_durable(
            stage / "metadata" / "candidate_evidence.json",
            canonical_json_bytes(candidate_payload) + b"\n",
            checkpoint_prefix="staged_candidate_evidence",
        )
        target_backup = (
            stage
            / "backups"
            / "migration"
            / workspace.migration_id
            / "source_backup.zip"
        )
        io.copy_file_durable(
            backup.archive_path,
            target_backup,
            checkpoint_prefix="staged_backup",
        )
        staged_backup_sha, _ = sha256_file(target_backup)
        if staged_backup_sha != backup.archive_sha256:
            raise MigrationRecoveryRequired("Staged backup archive hash mismatch.")
        receipt = MigrationReceipt(
            migration_id=workspace.migration_id,
            state=MigrationState.COPIED_UNVERIFIED,
            machine_id=target_identity.machine_id,
            machine_uuid=target_identity.machine_uuid,
            source_kind=str(manifest.get("source_kind")),
            source_version=manifest.get("source_version"),
            candidate_id=str(manifest.get("candidate_id")),
            required_config_fingerprint=str(
                manifest.get("required_config_fingerprint")
            ),
            migratable_tree_fingerprint=str(
                manifest.get("migratable_tree_fingerprint")
            ),
            full_source_fingerprint=str(manifest.get("full_source_fingerprint")),
            backup_archive_sha256=backup.archive_sha256,
            preset_like=bool(manifest.get("preset_matches")),
            camera_preset_match=manifest.get("camera_preset_match") is True,
            unclassified_source_paths=tuple(
                manifest.get("unclassified_source_paths", [])
            ),
            completed_at_utc=clock(),
        )
        io.atomic_write_json(
            stage / "metadata" / "migration_receipt.json",
            receipt.to_payload(),
            checkpoint_prefix="staged_receipt",
        )
        _write_tree_manifest(stage, io=io)
        verified = _verify_machine_tree(
            stage,
            expected_uuid=target_paths.machine_uuid,
            archive_policy=policy.archive_policy,
        )
        if verified != receipt:
            raise MigrationRecoveryRequired("Staged receipt changed during verification.")
        io.checkpoint("after_staged_copy_verification", stage)
        return receipt
    except Exception:
        raise


def _tree_files(root: Path) -> dict[str, tuple[int, str]]:
    root = Path(root)
    files: dict[str, tuple[int, str]] = {}
    folded: set[str] = set()
    for path in sorted(root.rglob("*")):
        details = path.lstat()
        attributes = getattr(details, "st_file_attributes", 0)
        if stat.S_ISLNK(details.st_mode) or attributes & _WINDOWS_REPARSE_POINT:
            raise MigrationRecoveryRequired(
                f"Machine tree contains a link/reparse point: {path}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise MigrationRecoveryRequired(f"Machine tree contains special file: {path}")
        relative = path.relative_to(root).as_posix()
        if relative.casefold() in folded:
            raise MigrationRecoveryRequired("Machine tree has case-colliding paths.")
        folded.add(relative.casefold())
        digest, size = sha256_file(path)
        files[relative] = (size, digest)
    return files


def _write_tree_manifest(root: Path, *, io: MigrationFileOps) -> None:
    manifest_path = Path(root) / "metadata" / "migration_tree_manifest.json"
    entries = _tree_files(root)
    entries.pop("metadata/migration_tree_manifest.json", None)
    payload = {
        "schema_name": MIGRATION_TREE_MANIFEST_SCHEMA_NAME,
        "schema_version": MIGRATION_TREE_MANIFEST_SCHEMA_VERSION,
        "files": [
            {"relative_path": path, "size": size, "raw_sha256": digest}
            for path, (size, digest) in sorted(entries.items())
        ],
    }
    io.atomic_write_json(
        manifest_path, payload, checkpoint_prefix="staged_tree_manifest"
    )


def _verify_machine_tree(
    root: Path,
    *,
    expected_uuid: str,
    archive_policy: ArchivePolicy | None = None,
    allowed_additional_paths: frozenset[str] = frozenset(),
    required_additional_paths: frozenset[str] = frozenset(),
    exact_active_overrides: Mapping[str, tuple[int, str]] | None = None,
    allowed_additional_prefixes: tuple[str, ...] = (),
    mutable_existing_prefixes: tuple[str, ...] = (),
    immutable_paths_within_mutable_prefixes: frozenset[str] = frozenset(),
) -> MigrationReceipt:
    machine_root = Path(root)
    manifest_path = machine_root / "metadata" / "migration_tree_manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationRecoveryRequired(f"Cannot read machine-tree manifest: {exc}") from exc
    if not isinstance(payload, dict) or payload.get(
        "schema_name"
    ) != MIGRATION_TREE_MANIFEST_SCHEMA_NAME or payload.get(
        "schema_version"
    ) != MIGRATION_TREE_MANIFEST_SCHEMA_VERSION:
        raise MigrationRecoveryRequired("Unknown machine-tree manifest schema.")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        raise MigrationRecoveryRequired("Machine-tree file inventory must be a list.")
    expected: dict[str, tuple[int, str]] = {}
    for item in raw_files:
        if not isinstance(item, dict):
            raise MigrationRecoveryRequired("Invalid machine-tree manifest entry.")
        path = item.get("relative_path")
        size = item.get("size")
        digest = item.get("raw_sha256")
        if not isinstance(path, str) or type(size) is not int or not _is_sha256(digest):
            raise MigrationRecoveryRequired("Invalid machine-tree manifest evidence.")
        if path in expected:
            raise MigrationRecoveryRequired("Duplicate machine-tree manifest path.")
        expected[path] = (size, digest)
    actual = _tree_files(machine_root)
    actual.pop("metadata/migration_tree_manifest.json", None)
    effective_expected = dict(expected)
    override_paths: frozenset[str] = frozenset()
    if exact_active_overrides is not None:
        overrides = dict(exact_active_overrides)
        for relative_path, evidence in overrides.items():
            if (
                not isinstance(relative_path, str)
                or not isinstance(evidence, tuple)
                or len(evidence) != 2
                or type(evidence[0]) is not int
                or not _is_sha256(evidence[1])
            ):
                raise MigrationRecoveryRequired("Invalid transactional active-tree evidence.")
            if relative_path in expected and not relative_path.startswith("config/"):
                raise MigrationRecoveryRequired(
                    f"Transactional state cannot replace immutable path: {relative_path}"
                )
            effective_expected[relative_path] = evidence
        override_paths = frozenset(overrides)
    comparison_expected = {
        path: evidence
        for path, evidence in effective_expected.items()
        if path in immutable_paths_within_mutable_prefixes
        or not any(path.startswith(prefix) for prefix in mutable_existing_prefixes)
    }
    baseline_actual = {path: actual.get(path) for path in comparison_expected}
    if baseline_actual != comparison_expected:
        raise MigrationRecoveryRequired("Machine tree differs from its immutable manifest.")
    additional = frozenset(actual).difference(expected)
    allowed_with_overrides = allowed_additional_paths | override_paths.difference(expected)
    unexpected_paths = {
        path
        for path in additional.difference(allowed_with_overrides)
        if not any(path.startswith(prefix) for prefix in allowed_additional_prefixes)
    }
    if unexpected_paths:
        unexpected = ", ".join(sorted(unexpected_paths))
        raise MigrationRecoveryRequired(
            f"Machine tree has unapproved phase files: {unexpected}"
        )
    if not required_additional_paths.issubset(additional):
        missing = ", ".join(sorted(required_additional_paths.difference(additional)))
        raise MigrationRecoveryRequired(
            f"Machine tree is missing required phase files: {missing}"
        )
    try:
        receipt_payload = json.loads(
            (machine_root / "metadata" / "migration_receipt.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationRecoveryRequired(f"Cannot read migration receipt: {exc}") from exc
    receipt = _parse_receipt(receipt_payload)
    if receipt.machine_uuid != expected_uuid:
        raise MigrationRecoveryRequired("Receipt UUID differs from target directory UUID.")
    try:
        identity_payload = json.loads(
            (machine_root / "metadata" / "machine_identity.json").read_text(
                encoding="utf-8"
            )
        )
        identity = parse_machine_identity(identity_payload)
    except (OSError, json.JSONDecodeError, MachineIdentityError) as exc:
        raise MigrationRecoveryRequired(
            f"Canonical machine identity is invalid: {exc}"
        ) from exc
    if (
        identity.machine_uuid != receipt.machine_uuid
        or identity.machine_id != receipt.machine_id
    ):
        raise MigrationRecoveryRequired(
            "Canonical identity and migration receipt identify different machines."
        )
    try:
        candidate_payload = json.loads(
            (machine_root / "metadata" / "candidate_evidence.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationRecoveryRequired(
            f"Canonical candidate evidence is invalid: {exc}"
        ) from exc
    if not isinstance(candidate_payload, dict):
        raise MigrationRecoveryRequired("Canonical candidate evidence must be an object.")
    candidate_receipt_pairs = {
        "candidate_id": receipt.candidate_id,
        "source_kind": receipt.source_kind,
        "version_text": receipt.source_version,
        "required_config_fingerprint": receipt.required_config_fingerprint,
        "migratable_tree_fingerprint": receipt.migratable_tree_fingerprint,
        "full_source_fingerprint": receipt.full_source_fingerprint,
        "camera_preset_match": receipt.camera_preset_match,
    }
    for field_name, expected_value in candidate_receipt_pairs.items():
        if candidate_payload.get(field_name) != expected_value:
            raise MigrationRecoveryRequired(
                f"Candidate evidence and receipt differ for {field_name}."
            )
    if bool(candidate_payload.get("preset_matches")) != receipt.preset_like:
        raise MigrationRecoveryRequired(
            "Candidate preset evidence and receipt differ."
        )
    if tuple(candidate_payload.get("unclassified_source_paths", [])) != (
        receipt.unclassified_source_paths
    ):
        raise MigrationRecoveryRequired(
            "Candidate unclassified inventory and receipt differ."
        )
    backup_path = (
        machine_root
        / "backups"
        / "migration"
        / receipt.migration_id
        / "source_backup.zip"
    )
    try:
        verified_backup = verify_backup_archive(
            backup_path, policy=archive_policy or ArchivePolicy()
        )
    except (ArchiveSafetyError, ArchiveVerificationError, OSError) as exc:
        raise MigrationRecoveryRequired(
            f"Published migration backup is invalid: {exc}"
        ) from exc
    if verified_backup.archive_sha256 != receipt.backup_archive_sha256:
        raise MigrationRecoveryRequired("Published backup differs from receipt hash.")
    backup_receipt_pairs = {
        "migration_id": receipt.migration_id,
        "candidate_id": receipt.candidate_id,
        "source_kind": receipt.source_kind,
        "source_version": receipt.source_version,
        "required_config_fingerprint": receipt.required_config_fingerprint,
        "migratable_tree_fingerprint": receipt.migratable_tree_fingerprint,
        "full_source_fingerprint": receipt.full_source_fingerprint,
        "camera_preset_match": receipt.camera_preset_match,
    }
    for field_name, expected_value in backup_receipt_pairs.items():
        if verified_backup.manifest.get(field_name) != expected_value:
            raise MigrationRecoveryRequired(
                f"Published backup and receipt differ for {field_name}."
            )
    return receipt


_ACTIVATION_PHASE_PATHS = frozenset(
    {
        "metadata/verification.json",
        "metadata/activation_receipt.json",
        "locks/configuration.lock",
    }
)
_ACTIVE_REQUIRED_PATHS = frozenset(
    {
        "metadata/verification.json",
        "metadata/activation_receipt.json",
    }
)
_ACTIVE_RUNTIME_MUTABLE_PREFIXES = (
    "CalibrationMemory/",
    "calibration/",
)
_ACTIVE_RUNTIME_IMMUTABLE_PATHS = frozenset(
    {
        # This is the on-disk format declaration. Runtime calibration records,
        # registries, indices, and operator settings beneath the same tree are
        # intentionally mutable, but the schema declaration changes only via a
        # reviewed migration/update transition.
        "CalibrationMemory/schema.json",
    }
)
_ACTIVE_ALLOWED_ADDITIONAL_PREFIXES = (
    "update_history/",
    *_ACTIVE_RUNTIME_MUTABLE_PREFIXES,
)


def verify_published_migration(
    paths: MachineDataPaths,
    *,
    phase: PublishedMigrationPhase = PublishedMigrationPhase.COPIED_UNVERIFIED,
    archive_policy: ArchivePolicy | None = None,
    active_tree_overrides: Mapping[str, tuple[int, str]] | None = None,
) -> PublishedMigrationEvidence:
    """Verify an installed migration with a fixed, versioned phase inventory."""

    if not isinstance(paths, MachineDataPaths):
        raise MachineDataPathError("paths must be a MachineDataPaths value.")
    try:
        selected_phase = PublishedMigrationPhase(phase)
    except ValueError as exc:
        raise MigrationRecoveryRequired(f"Unknown published migration phase: {phase!r}") from exc
    allowed = (
        frozenset()
        if selected_phase is PublishedMigrationPhase.COPIED_UNVERIFIED
        else _ACTIVATION_PHASE_PATHS
    )
    required = (
        _ACTIVE_REQUIRED_PATHS
        if selected_phase is PublishedMigrationPhase.ACTIVE
        else frozenset()
    )
    if active_tree_overrides is not None and selected_phase is not PublishedMigrationPhase.ACTIVE:
        raise MigrationRecoveryRequired(
            "Transactional active-tree evidence is valid only for the active phase."
        )
    if selected_phase is PublishedMigrationPhase.ACTIVE:
        try:
            LocalConfig.get_existing_calibration_memory_root(
                root=paths.calibration_memory_root
            )
        except (OSError, ValueError) as exc:
            raise MigrationRecoveryRequired(
                f"Active CalibrationMemory baseline is invalid: {exc}"
            ) from exc
    receipt = _verify_machine_tree(
        paths.machine_root,
        expected_uuid=paths.machine_uuid,
        archive_policy=archive_policy,
        allowed_additional_paths=allowed,
        required_additional_paths=required,
        exact_active_overrides=active_tree_overrides,
        allowed_additional_prefixes=(
            _ACTIVE_ALLOWED_ADDITIONAL_PREFIXES
            if selected_phase is PublishedMigrationPhase.ACTIVE
            else ()
        ),
        mutable_existing_prefixes=(
            _ACTIVE_RUNTIME_MUTABLE_PREFIXES
            if selected_phase is PublishedMigrationPhase.ACTIVE
            else ()
        ),
        immutable_paths_within_mutable_prefixes=(
            _ACTIVE_RUNTIME_IMMUTABLE_PATHS
            if selected_phase is PublishedMigrationPhase.ACTIVE
            else frozenset()
        ),
    )
    candidate = load_candidate_evidence(paths.candidate_evidence_path)
    if candidate.candidate_id != receipt.candidate_id:
        raise MigrationRecoveryRequired("Candidate evidence differs from migration receipt.")
    backup_path = (
        paths.backups_root
        / "migration"
        / receipt.migration_id
        / "source_backup.zip"
    )
    backup = verify_backup_archive(backup_path, policy=archive_policy or ArchivePolicy())
    manifest_sha256, _ = sha256_file(paths.migration_tree_manifest_path)
    actual = _tree_files(paths.machine_root)
    try:
        manifest_payload = json.loads(
            paths.migration_tree_manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationRecoveryRequired(f"Cannot reopen migration tree manifest: {exc}") from exc
    baseline_paths = {
        item["relative_path"]
        for item in manifest_payload.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("relative_path"), str)
    }
    additional = tuple(
        sorted(
            set(actual)
            .difference(baseline_paths)
            .difference({"metadata/migration_tree_manifest.json"})
        )
    )
    return PublishedMigrationEvidence(
        receipt=receipt,
        candidate=candidate,
        backup=backup,
        migration_tree_manifest_sha256=manifest_sha256,
        additional_paths=additional,
    )


def _cleanup_workspace(workspace: MigrationWorkspacePaths, *, io: MigrationFileOps) -> None:
    expected_parent = (
        workspace.base.root / "migration_work" / workspace.machine_uuid
    ).resolve(strict=False)
    if workspace.root.parent != expected_parent or workspace.root.name != workspace.migration_id:
        raise MachineDataPathError("Refusing to clean an unexpected migration workspace.")
    if not workspace.root.exists():
        return
    io.checkpoint("before_workspace_cleanup", workspace.root)
    shutil.rmtree(workspace.root)
    io.checkpoint("after_workspace_cleanup", workspace.root)
    try:
        expected_parent.rmdir()
        expected_parent.parent.rmdir()
    except OSError:
        pass


def _result_from_target(
    target_paths: MachineDataPaths,
    receipt: MigrationReceipt,
    *,
    reconciled: bool,
) -> MigrationResult:
    backup_path = (
        target_paths.backups_root
        / "migration"
        / receipt.migration_id
        / "source_backup.zip"
    )
    return MigrationResult(
        MigrationState.COPIED_UNVERIFIED,
        target_paths,
        receipt,
        backup_path,
        reconciled,
    )


def import_verified_candidate(
    candidate: CandidateEvidence,
    backup: VerifiedBackup,
    *,
    workspace: MigrationWorkspacePaths,
    target_paths: MachineDataPaths,
    target_identity: MachineIdentity,
    acquired_lock: MigrationLockToken,
    io: MigrationFileOps | None = None,
    policy: MigrationPolicy | None = None,
    clock: Callable[[], str] = _utc_now,
) -> MigrationResult:
    operations = io or MigrationFileOps()
    migration_policy = policy or MigrationPolicy()
    _assert_lock(workspace, acquired_lock)
    identity = _target_identity(target_identity)
    if (
        target_paths.machine_uuid != workspace.machine_uuid
        or identity.machine_uuid != workspace.machine_uuid
    ):
        raise MigrationError("identity_conflict", "Workspace, target, and identity UUIDs differ.")
    if target_paths.machine_root.exists():
        try:
            receipt = _verify_machine_tree(
                target_paths.machine_root,
                expected_uuid=target_paths.machine_uuid,
                archive_policy=migration_policy.archive_policy,
            )
        except MigrationRecoveryRequired as exc:
            raise MigrationError(
                "target_conflict", f"Existing target cannot be reconciled: {exc}"
            ) from exc
        if receipt.migration_id != workspace.migration_id or receipt.candidate_id != candidate.candidate_id:
            raise MigrationError("target_conflict", "Existing target belongs to different migration evidence.")
        if workspace.root.exists():
            journal = _load_journal(workspace)
            if journal and MigrationState(journal["state"]) == MigrationState.STAGED_COPY_VERIFIED:
                _advance_journal(
                    workspace,
                    MigrationState.COPIED_UNVERIFIED,
                    io=operations,
                    clock=clock,
                    candidate=candidate,
                    artifacts={
                        "target": _relative_to_base(
                            target_paths.machine_root, workspace.base
                        )
                    },
                )
            _cleanup_workspace(workspace, io=operations)
        return _result_from_target(target_paths, receipt, reconciled=True)
    if not candidate.is_importable:
        raise CandidateNotImportable("Candidate is not importable.")
    try:
        current_backup = verify_backup_archive(
            backup.archive_path, policy=migration_policy.archive_policy
        )
    except (ArchiveSafetyError, ArchiveVerificationError, OSError) as exc:
        raise MigrationRecoveryRequired(
            f"Verified backup cannot be reopened safely: {exc}"
        ) from exc
    if current_backup.archive_sha256 != backup.archive_sha256:
        raise MigrationRecoveryRequired("Verified backup changed before import.")
    manifest = current_backup.manifest
    if (
        manifest.get("candidate_id") != candidate.candidate_id
        or manifest.get("migration_id") != workspace.migration_id
        or manifest.get("required_config_fingerprint")
        != candidate.required_config_fingerprint
        or manifest.get("migratable_tree_fingerprint")
        != candidate.migratable_tree_fingerprint
    ):
        raise MigrationRecoveryRequired("Backup does not match selected candidate/workspace.")
    manifest_identity = manifest.get("target_identity")
    if manifest_identity is not None:
        try:
            recorded_identity = parse_machine_identity(manifest_identity)
        except MachineIdentityError as exc:
            raise MigrationRecoveryRequired("Backup target identity is invalid.") from exc
        if recorded_identity != identity:
            raise MigrationError("identity_conflict", "Backup target identity differs from import target.")
    if candidate.legacy_identity and candidate.identity_status == "assigned":
        if (
            candidate.legacy_identity.machine_uuid != identity.machine_uuid
            or candidate.legacy_identity.machine_id != identity.machine_id
        ):
            raise MigrationError("identity_conflict", "Legacy assigned identity differs from target.")
    _preflight_space(
        workspace,
        sum(item.size for item in candidate.migratable_files)
        + current_backup.archive_path.stat().st_size,
        policy=migration_policy,
        io=operations,
    )
    try:
        receipt = _write_stage_from_backup(
            current_backup,
            workspace=workspace,
            target_paths=target_paths,
            target_identity=identity,
            io=operations,
            policy=migration_policy,
            clock=clock,
        )
    except MigrationRecoveryRequired:
        raise
    except Exception as exc:
        raise MigrationError("copy_failed", f"Staged copy failed: {exc}") from exc
    _advance_journal(
        workspace,
        MigrationState.STAGED_COPY_VERIFIED,
        io=operations,
        clock=clock,
        candidate=candidate,
        artifacts={"stage": _relative_to_base(workspace.staged_machine_root, workspace.base)},
    )
    try:
        operations.publish_tree(workspace.staged_machine_root, target_paths.machine_root)
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError("copy_failed", f"Atomic target publication failed: {exc}") from exc
    published_receipt = _verify_machine_tree(
        target_paths.machine_root,
        expected_uuid=target_paths.machine_uuid,
        archive_policy=migration_policy.archive_policy,
    )
    if published_receipt != receipt:
        raise MigrationRecoveryRequired("Published receipt differs from verified stage.")
    operations.checkpoint("after_target_verification", target_paths.machine_root)
    _advance_journal(
        workspace,
        MigrationState.COPIED_UNVERIFIED,
        io=operations,
        clock=clock,
        candidate=candidate,
        artifacts={"target": _relative_to_base(target_paths.machine_root, workspace.base)},
    )
    _cleanup_workspace(workspace, io=operations)
    return _result_from_target(target_paths, published_receipt, reconciled=False)


def reconcile_migration(
    *,
    workspace: MigrationWorkspacePaths,
    target_paths: MachineDataPaths,
    acquired_lock: MigrationLockToken,
    io: MigrationFileOps | None = None,
    policy: MigrationPolicy | None = None,
    clock: Callable[[], str] = _utc_now,
) -> MigrationResult:
    operations = io or MigrationFileOps()
    migration_policy = policy or MigrationPolicy()
    _assert_lock(workspace, acquired_lock)
    if target_paths.machine_uuid != workspace.machine_uuid:
        raise MigrationRecoveryRequired("Workspace and target UUID differ.")
    if target_paths.machine_root.exists():
        receipt = _verify_machine_tree(
            target_paths.machine_root,
            expected_uuid=target_paths.machine_uuid,
            archive_policy=migration_policy.archive_policy,
        )
        if receipt.migration_id != workspace.migration_id:
            raise MigrationError("target_conflict", "Target belongs to another migration.")
        if workspace.root.exists():
            journal = _load_journal(workspace)
            if journal and MigrationState(journal["state"]) == MigrationState.STAGED_COPY_VERIFIED:
                _advance_journal(
                    workspace,
                    MigrationState.COPIED_UNVERIFIED,
                    io=operations,
                    clock=clock,
                    artifacts={
                        "target": _relative_to_base(target_paths.machine_root, workspace.base)
                    },
                )
            _cleanup_workspace(workspace, io=operations)
        return _result_from_target(target_paths, receipt, reconciled=True)
    journal = _load_journal(workspace)
    if journal is None:
        raise MigrationRecoveryRequired("No target or migration journal exists.")
    state = MigrationState(journal["state"])
    if state == MigrationState.STAGED_COPY_VERIFIED and workspace.staged_machine_root.exists():
        receipt = _verify_machine_tree(
            workspace.staged_machine_root,
            expected_uuid=target_paths.machine_uuid,
            archive_policy=migration_policy.archive_policy,
        )
        operations.publish_tree(workspace.staged_machine_root, target_paths.machine_root)
        published = _verify_machine_tree(
            target_paths.machine_root,
            expected_uuid=target_paths.machine_uuid,
            archive_policy=migration_policy.archive_policy,
        )
        if published != receipt:
            raise MigrationRecoveryRequired("Published recovered tree differs from stage.")
        _advance_journal(
            workspace,
            MigrationState.COPIED_UNVERIFIED,
            io=operations,
            clock=clock,
            artifacts={"target": _relative_to_base(target_paths.machine_root, workspace.base)},
        )
        _cleanup_workspace(workspace, io=operations)
        return _result_from_target(target_paths, published, reconciled=True)
    if state == MigrationState.BACKUP_VERIFIED and workspace.backup_path.exists():
        try:
            backup = verify_backup_archive(
                workspace.backup_path, policy=migration_policy.archive_policy
            )
        except (ArchiveSafetyError, ArchiveVerificationError, OSError) as exc:
            raise MigrationRecoveryRequired(
                f"Recorded backup is not trustworthy: {exc}"
            ) from exc
        raw_identity = backup.manifest.get("target_identity")
        if raw_identity is None:
            raise MigrationRecoveryRequired(
                "Verified backup has no assigned target identity for recovery."
            )
        try:
            identity = parse_machine_identity(raw_identity)
        except MachineIdentityError as exc:
            raise MigrationRecoveryRequired("Backup target identity is invalid.") from exc
        receipt = _write_stage_from_backup(
            backup,
            workspace=workspace,
            target_paths=target_paths,
            target_identity=identity,
            io=operations,
            policy=migration_policy,
            clock=clock,
        )
        _advance_journal(
            workspace,
            MigrationState.STAGED_COPY_VERIFIED,
            io=operations,
            clock=clock,
            artifacts={"stage": _relative_to_base(workspace.staged_machine_root, workspace.base)},
        )
        operations.publish_tree(workspace.staged_machine_root, target_paths.machine_root)
        published = _verify_machine_tree(
            target_paths.machine_root,
            expected_uuid=target_paths.machine_uuid,
            archive_policy=migration_policy.archive_policy,
        )
        if published != receipt:
            raise MigrationRecoveryRequired("Recovered publication differs from stage.")
        _advance_journal(
            workspace,
            MigrationState.COPIED_UNVERIFIED,
            io=operations,
            clock=clock,
            artifacts={"target": _relative_to_base(target_paths.machine_root, workspace.base)},
        )
        _cleanup_workspace(workspace, io=operations)
        return _result_from_target(target_paths, published, reconciled=True)
    raise MigrationRecoveryRequired(
        f"Migration cannot resume automatically from state {state.value}; evidence preserved."
    )


__all__ = [
    "CALIBRATION_MEMORY_SEED_TYPES",
    "DEFAULT_PRESET_CATALOG_PATH",
    "MIGRATION_JOURNAL_SCHEMA_NAME",
    "MIGRATION_JOURNAL_SCHEMA_VERSION",
    "MIGRATION_RECEIPT_SCHEMA_NAME",
    "MIGRATION_RECEIPT_SCHEMA_VERSION",
    "CandidateComparison",
    "CandidateEvidence",
    "CandidateIssue",
    "CandidateIssueSeverity",
    "CandidateNotImportable",
    "CandidateRelation",
    "CandidateSelection",
    "CandidateSourceKind",
    "MigrationError",
    "MigrationFileOps",
    "MigrationPolicy",
    "MigrationReceipt",
    "MigrationRecoveryRequired",
    "MigrationResult",
    "MigrationState",
    "MigrationWorkspacePaths",
    "PublishedMigrationEvidence",
    "PublishedMigrationPhase",
    "PresetFingerprintCatalog",
    "REQUIRED_CONFIG_NAMES",
    "build_migration_workspace_paths",
    "classify_candidates",
    "create_verified_backup",
    "import_verified_candidate",
    "inspect_candidate",
    "load_candidate_evidence",
    "load_migration_receipt",
    "new_migration_workspace_paths",
    "parse_candidate_evidence",
    "parse_migration_receipt",
    "reconcile_migration",
    "verify_published_migration",
    "validate_state_transition",
]
