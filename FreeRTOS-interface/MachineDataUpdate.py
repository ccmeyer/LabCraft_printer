"""Checkout-independent preservation and deployment authority for app updates.

This module never imports the MVC, communications, camera, balance, GPIO, or
firmware layers.  It operates only on an already-authorized external machine
store while holding the update lock followed by the configuration lock.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Callable, Mapping, Sequence
from uuid import UUID, uuid4

from MachineData import (
    ActiveMachine,
    MachineDataBasePaths,
    MachineDataPaths,
    build_machine_data_paths,
    parse_machine_identity,
    require_authorized_active_machine,
    resolve_machine_data_base,
)
from MachineDataArchive import (
    ArchiveLimitError,
    ArchivePolicy,
    ArchiveSafetyError,
    ArchiveVerificationError,
    DurableFileOps,
    canonical_json_bytes,
    semantic_json_sha256,
    sha256_bytes,
    sha256_file,
)
from MachineDataLock import (
    AcquiredConfigurationLock,
    AcquiredUpdateLock,
    acquire_configuration_lock,
    acquire_update_lock,
)
from MachineDataTransactions import inspect_configuration_state, read_governed_documents
from MachineDataMigration import MigrationState, load_migration_receipt
from MachineDataVerification import (
    build_target_snapshot,
    load_activation_receipt,
    load_machine_verification,
)


UPDATE_CONTRACT_NAME = "labcraft.machine_data_update.v1"
UPDATE_COMPATIBILITY_SCHEMA_VERSION = "labcraft_update_compatibility_v1"
UPDATE_RELEASE_SCHEMA_VERSION = 1
UPDATE_STAGE_SCHEMA_NAME = "labcraft.machine_data_update_stage"
UPDATE_STAGE_SCHEMA_VERSION = 1
UPDATE_MANIFEST_SCHEMA_NAME = "labcraft.machine_data_update_manifest"
UPDATE_MANIFEST_SCHEMA_VERSION = 1
UPDATE_BACKUP_SCHEMA_NAME = "labcraft.machine_data_update_backup"
UPDATE_BACKUP_SCHEMA_VERSION = 1
DEPLOYMENT_ANCHOR_SCHEMA_NAME = "labcraft.deployment_anchor"
DEPLOYMENT_ANCHOR_SCHEMA_VERSION = 1
LATEST_RESULT_SCHEMA_NAME = "labcraft.machine_data_update_latest_result"
LATEST_RESULT_SCHEMA_VERSION = 1
GENESIS_ENROLLMENT_VERSION = "v1.3.0-rc.2"
GENESIS_ENROLLMENT_VERSIONS = frozenset(
    {GENESIS_ENROLLMENT_VERSION, "v1.3.0-rc.3", "v1.3.0-rc.8"}
)
GENESIS_MIGRATION_SOURCE_VERSIONS = frozenset(
    {"v1.2.0", "v1.2.0-rc.6", "v1.3.0-rc.1"}
)
RELEASE_VERSION_RE = re.compile(
    r"v[0-9]+(?:\.[0-9]+){2}(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?"
)

TRANSITION_NONE = "none"
TRANSITION_BOOTSTRAP_RECOVERY = "bootstrap_recovery"
SUPPORTED_TRANSITIONS = frozenset({TRANSITION_NONE, TRANSITION_BOOTSTRAP_RECOVERY})

TERMINAL_RESULT_FILENAME = "terminal_result.json"
RELAUNCH_STAGE_FILENAME = "06_relaunch_authorization.json"
RECOVERY_REQUIRED_STAGES = frozenset(
    {"git_applied", "target_bootstrap_required", "recovery_required"}
)
_WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_COPY_CHUNK_SIZE = 1024 * 1024


class MachineDataUpdateError(RuntimeError):
    """A preservation, deployment, or recovery contract failed closed."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        recovery_required: bool = False,
    ) -> None:
        self.code = str(code)
        self.recovery_required = bool(recovery_required)
        super().__init__(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _uuid_text(value: object, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError) as exc:
        raise MachineDataUpdateError("invalid_binding", f"{label} must be UUID text.") from exc


def _sha256_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise MachineDataUpdateError("invalid_binding", f"{label} must be lowercase SHA-256 text.")
    return value


def _commit_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MachineDataUpdateError("invalid_binding", f"{label} is required.")
    return text


def commit_identities_match(recorded: object, actual: object) -> bool:
    """Match an exact commit or rc.2's historical 12-hex commit prefix."""

    recorded_text = str(recorded or "").strip()
    actual_text = str(actual or "").strip()
    if not recorded_text or not actual_text:
        return False
    if recorded_text == actual_text:
        return True
    return (
        len(recorded_text) == 12
        and len(actual_text) == 40
        and recorded_text == recorded_text.lower()
        and actual_text == actual_text.lower()
        and all(character in "0123456789abcdef" for character in recorded_text)
        and all(character in "0123456789abcdef" for character in actual_text)
        and actual_text.startswith(recorded_text)
    )


def _json_safe(value: object) -> object:
    """Return a plain JSON-safe deep copy, including MappingProxyType values."""

    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return json.loads(canonical_json_bytes(value))


def _read_json(path: Path, label: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MachineDataUpdateError("recovery_required", f"Cannot read {label}: {exc}", recovery_required=True) from exc


def parse_release_machine_data_contract(
    payload: object,
    *,
    required: bool,
) -> Mapping[str, object] | None:
    """Validate the release manifest's M6 declaration."""

    if payload in (None, ""):
        if required:
            raise MachineDataUpdateError(
                "target_contract_missing",
                "The target release does not declare the required machine-data preservation contract.",
            )
        return None
    if not isinstance(payload, dict):
        raise MachineDataUpdateError("target_contract_invalid", "Release machine_data must be an object.")
    expected = {
        "preservation_contract",
        "data_schema_version",
        "transition",
        "transition_id",
    }
    if set(payload) != expected:
        raise MachineDataUpdateError(
            "target_contract_invalid",
            "Release machine_data fields differ from the v1 contract.",
        )
    if payload.get("preservation_contract") != UPDATE_CONTRACT_NAME:
        raise MachineDataUpdateError("target_contract_invalid", "Unknown preservation_contract.")
    schema_version = payload.get("data_schema_version")
    if type(schema_version) is not int or schema_version <= 0:
        raise MachineDataUpdateError("target_contract_invalid", "data_schema_version must be a positive integer.")
    transition = payload.get("transition")
    if transition not in SUPPORTED_TRANSITIONS:
        raise MachineDataUpdateError("target_contract_invalid", "Unknown machine-data transition mode.")
    transition_id = payload.get("transition_id")
    if transition == TRANSITION_NONE:
        if transition_id is not None:
            raise MachineDataUpdateError("target_contract_invalid", "transition_id must be null when transition is none.")
    elif not isinstance(transition_id, str) or not transition_id.strip():
        raise MachineDataUpdateError("target_contract_invalid", "bootstrap_recovery requires transition_id.")
    return MappingProxyType(dict(payload))


def parse_release_update_compatibility(
    payload: object,
    *,
    required: bool,
) -> Mapping[str, object] | None:
    """Validate a release manifest's explicit direct-legacy bridge authority."""

    if payload in (None, ""):
        if required:
            raise MachineDataUpdateError(
                "target_compatibility_missing",
                "This release is not explicitly authorized as a direct legacy-update bridge.",
                recovery_required=True,
            )
        return None
    if not isinstance(payload, Mapping):
        raise MachineDataUpdateError(
            "target_compatibility_invalid",
            "Release update_compatibility must be an object.",
            recovery_required=True,
        )
    expected = {"schema_version", "direct_legacy_sources"}
    if set(payload) != expected:
        raise MachineDataUpdateError(
            "target_compatibility_invalid",
            "Release update_compatibility fields differ from the v1 contract.",
            recovery_required=True,
        )
    if payload.get("schema_version") != UPDATE_COMPATIBILITY_SCHEMA_VERSION:
        raise MachineDataUpdateError(
            "target_compatibility_invalid",
            "Release update_compatibility has an unsupported schema_version.",
            recovery_required=True,
        )
    raw_sources = payload.get("direct_legacy_sources")
    if not isinstance(raw_sources, (list, tuple)) or not raw_sources:
        raise MachineDataUpdateError(
            "target_compatibility_invalid",
            "Release direct_legacy_sources must be a nonempty list.",
            recovery_required=True,
        )
    sources: list[str] = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, str):
            raise MachineDataUpdateError(
                "target_compatibility_invalid",
                "Release direct_legacy_sources entries must be version strings.",
                recovery_required=True,
            )
        source = raw_source.strip()
        if (
            not source
            or source != raw_source
            or "/" in source
            or "\\" in source
            or ".." in source
            or RELEASE_VERSION_RE.fullmatch(source) is None
        ):
            raise MachineDataUpdateError(
                "target_compatibility_invalid",
                f"Unsupported direct legacy source version: {raw_source!r}.",
                recovery_required=True,
            )
        if source in sources:
            raise MachineDataUpdateError(
                "target_compatibility_invalid",
                f"Release direct_legacy_sources lists {source} more than once.",
                recovery_required=True,
            )
        sources.append(source)
    return MappingProxyType(
        {
            "schema_version": UPDATE_COMPATIBILITY_SCHEMA_VERSION,
            "direct_legacy_sources": tuple(sources),
        }
    )


@dataclass(frozen=True)
class UpdateLaunchBinding:
    machine_data_root: Path
    machine_id: str
    machine_uuid: str
    activation_id: str
    migration_id: str
    active_pointer_sha256: str
    source_app_version: str
    source_commit: str
    request_id: str

    def __post_init__(self) -> None:
        root = Path(self.machine_data_root).expanduser()
        if not root.is_absolute():
            raise MachineDataUpdateError("invalid_binding", "machine_data_root must be absolute.")
        object.__setattr__(self, "machine_data_root", root.resolve(strict=False))
        if not isinstance(self.machine_id, str) or not self.machine_id.strip():
            raise MachineDataUpdateError("invalid_binding", "machine_id is required.")
        object.__setattr__(self, "machine_id", self.machine_id.strip())
        object.__setattr__(self, "machine_uuid", _uuid_text(self.machine_uuid, "machine_uuid"))
        object.__setattr__(self, "activation_id", _uuid_text(self.activation_id, "activation_id"))
        object.__setattr__(self, "migration_id", _uuid_text(self.migration_id, "migration_id"))
        object.__setattr__(
            self,
            "active_pointer_sha256",
            _sha256_text(self.active_pointer_sha256, "active_pointer_sha256"),
        )
        object.__setattr__(self, "source_app_version", _commit_text(self.source_app_version, "source_app_version"))
        object.__setattr__(self, "source_commit", _commit_text(self.source_commit, "source_commit"))
        object.__setattr__(self, "request_id", _uuid_text(self.request_id, "request_id"))

    def to_payload(self) -> dict[str, object]:
        return {
            "machine_data_root": str(self.machine_data_root),
            "machine_id": self.machine_id,
            "machine_uuid": self.machine_uuid,
            "activation_id": self.activation_id,
            "migration_id": self.migration_id,
            "active_pointer_sha256": self.active_pointer_sha256,
            "source_app_version": self.source_app_version,
            "source_commit": self.source_commit,
            "request_id": self.request_id,
        }


def build_update_launch_binding(
    authorized_context: object,
    *,
    source_app_version: str,
    source_commit: str,
    request_id: str | None = None,
) -> UpdateLaunchBinding:
    paths = getattr(authorized_context, "paths", None)
    active = getattr(authorized_context, "active_machine", None)
    identity = getattr(authorized_context, "identity", None)
    if not isinstance(paths, MachineDataPaths) or not isinstance(active, ActiveMachine):
        raise MachineDataUpdateError("invalid_binding", "An authorized machine context is required.")
    if identity is None or active.activation_id is None or active.migration_id is None:
        raise MachineDataUpdateError("invalid_binding", "Authorized identity evidence is incomplete.")
    pointer_sha, _ = sha256_file(paths.base.active_machine_path)
    return UpdateLaunchBinding(
        machine_data_root=paths.base.root,
        machine_id=identity.machine_id,
        machine_uuid=identity.machine_uuid,
        activation_id=active.activation_id,
        migration_id=active.migration_id,
        active_pointer_sha256=pointer_sha,
        source_app_version=source_app_version,
        source_commit=source_commit,
        request_id=request_id or str(uuid4()),
    )


@dataclass(frozen=True)
class UpdateTarget:
    operation: str
    version: str
    tag: str
    commit: str
    update_source: str
    release_manifest_sha256: str
    machine_data_contract: Mapping[str, object]
    requires_firmware: object = None

    def __post_init__(self) -> None:
        if self.operation not in {"update", "rollback"}:
            raise MachineDataUpdateError("invalid_target", "Update operation is invalid.")
        for label in ("version", "tag", "commit", "update_source"):
            if not str(getattr(self, label) or "").strip():
                raise MachineDataUpdateError("invalid_target", f"Target {label} is required.")
        _sha256_text(self.release_manifest_sha256, "release_manifest_sha256")
        parse_release_machine_data_contract(dict(self.machine_data_contract), required=True)

    def to_payload(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "version": self.version,
            "tag": self.tag,
            "commit": self.commit,
            "update_source": self.update_source,
            "release_manifest_sha256": self.release_manifest_sha256,
            "machine_data_contract": dict(self.machine_data_contract),
            "requires_firmware": _json_safe(self.requires_firmware),
        }


@dataclass(frozen=True)
class ProtectedMember:
    relative_path: str
    source_path: Path
    size: int
    raw_sha256: str
    semantic_json_sha256: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "relative_path": self.relative_path,
            "size": self.size,
            "raw_sha256": self.raw_sha256,
        }
        if self.semantic_json_sha256 is not None:
            payload["semantic_json_sha256"] = self.semantic_json_sha256
        return payload


@dataclass(frozen=True)
class ProtectedSnapshot:
    members: tuple[ProtectedMember, ...]
    directories: tuple[str, ...]
    fingerprint: str
    safety_snapshot: Mapping[str, object]
    safety_snapshot_sha256: str
    total_bytes: int

    def manifest_payload(self) -> dict[str, object]:
        return {
            "members": [member.to_payload() for member in self.members],
            "directories": list(self.directories),
            "fingerprint": self.fingerprint,
            "safety_snapshot": _json_safe(self.safety_snapshot),
            "safety_snapshot_sha256": self.safety_snapshot_sha256,
            "total_bytes": self.total_bytes,
            "excluded_paths": ["machine/locks/**", "machine/update_history/**"],
        }


def _is_link_or_reparse(path: Path) -> bool:
    details = Path(path).lstat()
    attributes = getattr(details, "st_file_attributes", 0)
    return stat.S_ISLNK(details.st_mode) or bool(attributes & _WINDOWS_REPARSE_POINT)


def _safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise ArchiveSafetyError(f"Unsafe protected path: {value!r}")
    pure = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in pure.parts) or ":" in pure.parts[0]:
        raise ArchiveSafetyError(f"Unsafe protected path: {value!r}")
    if pure.as_posix() != value:
        raise ArchiveSafetyError(f"Non-normal protected path: {value!r}")
    return value


def _semantic_hash_if_json(path: Path, data: bytes) -> str | None:
    if path.suffix.casefold() != ".json":
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return semantic_json_sha256(payload)


def _inventory_tree(
    root: Path,
    *,
    prefix: str,
    policy: ArchivePolicy,
    excluded_top_level: frozenset[str] = frozenset(),
) -> tuple[list[ProtectedMember], list[str]]:
    root = Path(root)
    if not root.is_dir() or _is_link_or_reparse(root):
        raise ArchiveSafetyError(f"Protected root is missing or unsafe: {root}")
    members: list[ProtectedMember] = []
    directories: list[str] = []
    casefolded: dict[str, str] = {}
    total = 0

    def visit(directory: Path, relative_parent: PurePosixPath) -> None:
        nonlocal total
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise ArchiveSafetyError(f"Cannot enumerate protected root {directory}: {exc}") from exc
        for entry in entries:
            if not relative_parent.parts and entry.name in excluded_top_level:
                continue
            path = Path(entry.path)
            relative_local = (relative_parent / entry.name).as_posix()
            relative = _safe_relative(f"{prefix}/{relative_local}")
            if entry.is_symlink() or _is_link_or_reparse(path):
                raise ArchiveSafetyError(f"Protected tree contains link/reparse point: {relative}")
            folded = relative.casefold()
            if folded in casefolded:
                raise ArchiveSafetyError(
                    f"Protected tree contains case-colliding paths: {casefolded[folded]!r}, {relative!r}"
                )
            casefolded[folded] = relative
            if entry.is_dir(follow_symlinks=False):
                directories.append(relative)
                visit(path, relative_parent / entry.name)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise ArchiveSafetyError(f"Protected tree contains special file: {relative}")
            before = path.stat()
            data = path.read_bytes()
            after = path.stat()
            if (
                before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or len(data) != after.st_size
            ):
                raise ArchiveVerificationError(f"Protected file changed while captured: {relative}")
            size = len(data)
            total += size
            if len(members) + 1 > policy.max_files:
                raise ArchiveLimitError("Protected inventory exceeds max_files.")
            if size > policy.max_member_bytes or total > policy.max_total_bytes:
                raise ArchiveLimitError("Protected inventory exceeds archive size limits.")
            members.append(
                ProtectedMember(
                    relative,
                    path,
                    size,
                    sha256_bytes(data),
                    _semantic_hash_if_json(path, data),
                )
            )

    visit(root, PurePosixPath())
    return members, directories


def _build_safety_snapshot(
    paths: MachineDataPaths,
    active: ActiveMachine,
) -> Mapping[str, object]:
    identity = parse_machine_identity(_read_json(paths.identity_path, "machine identity"))
    verification = load_machine_verification(paths.verification_path)
    state = inspect_configuration_state(
        paths,
        identity,
        active,
        verification,
        allow_pending=False,
    )
    documents = read_governed_documents(paths)
    targets = build_target_snapshot(paths)
    target_payload = {
        key: {
            "kind": kind,
            "source_file": source_file,
            "value": _json_safe(value),
            "authorization": _json_safe(state.authorization[key]),
        }
        for key, (kind, source_file, value) in sorted(targets.items())
    }
    settings = documents["Settings.json"]
    return MappingProxyType(
        {
            "machine_id": identity.machine_id,
            "machine_uuid": identity.machine_uuid,
            "activation_id": active.activation_id,
            "migration_id": active.migration_id,
            "hardware_profile": settings.get("HARDWARE_PROFILE", "current"),
            "governed_semantic_sha256": {
                filename: semantic_json_sha256(payload)
                for filename, payload in sorted(documents.items())
            },
            "locations": _json_safe(documents["Locations.json"]),
            "plates": _json_safe(documents["Plates.json"]),
            "obstacles": _json_safe(documents["Obstacles.json"]),
            "targets": target_payload,
            "configuration": {
                "sequence": state.sequence,
                "latest_event_id": state.latest_event_id,
                "latest_event_sha256": state.latest_event_sha256,
                "config_sha256": _json_safe(state.config_sha256),
                "authorization": _json_safe(state.authorization),
                "has_history": state.has_history,
            },
        }
    )


def capture_protected_snapshot(
    paths: MachineDataPaths,
    active: ActiveMachine,
    *,
    policy: ArchivePolicy | None = None,
) -> ProtectedSnapshot:
    policy = policy or ArchivePolicy()
    pointer = paths.base.active_machine_path
    if not pointer.is_file() or _is_link_or_reparse(pointer):
        raise ArchiveSafetyError(f"Active pointer is missing or unsafe: {pointer}")
    pointer_data = pointer.read_bytes()
    if len(pointer_data) > policy.max_member_bytes:
        raise ArchiveLimitError("Active pointer exceeds archive member limit.")
    members = [
        ProtectedMember(
            "active_machine.json",
            pointer,
            len(pointer_data),
            sha256_bytes(pointer_data),
            _semantic_hash_if_json(pointer, pointer_data),
        )
    ]
    tree_members, directories = _inventory_tree(
        paths.machine_root,
        prefix="machine",
        policy=policy,
        excluded_top_level=frozenset({"locks", "update_history"}),
    )
    members.extend(tree_members)
    members.sort(key=lambda item: item.relative_path)
    total = sum(item.size for item in members)
    if len(members) > policy.max_files or total > policy.max_total_bytes:
        raise ArchiveLimitError("Protected snapshot exceeds archive limits.")
    fingerprints = [member.to_payload() for member in members]
    fingerprint = sha256_bytes(canonical_json_bytes(fingerprints))
    safety = _json_safe(_build_safety_snapshot(paths, active))
    safety_hash = sha256_bytes(canonical_json_bytes(safety))
    return ProtectedSnapshot(
        tuple(members),
        tuple(sorted(directories)),
        fingerprint,
        MappingProxyType(safety),
        safety_hash,
        total,
    )


def _copy_member_to_zip(
    archive: zipfile.ZipFile,
    member: ProtectedMember,
) -> None:
    info = zipfile.ZipInfo(f"payload/{member.relative_path}")
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    digest = hashlib.sha256()
    size = 0
    with member.source_path.open("rb") as source, archive.open(info, "w", force_zip64=True) as target:
        while True:
            chunk = source.read(_COPY_CHUNK_SIZE)
            if not chunk:
                break
            target.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    if size != member.size or digest.hexdigest() != member.raw_sha256:
        raise ArchiveVerificationError(f"Protected file changed while archived: {member.relative_path}")


def create_update_backup(
    snapshot: ProtectedSnapshot,
    destination: Path,
    *,
    update_id: str,
    binding: UpdateLaunchBinding,
    target: UpdateTarget,
    policy: ArchivePolicy,
    io: DurableFileOps,
) -> tuple[str, Mapping[str, object]]:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    manifest: dict[str, object] = {
        "schema_name": UPDATE_BACKUP_SCHEMA_NAME,
        "schema_version": UPDATE_BACKUP_SCHEMA_VERSION,
        "update_id": _uuid_text(update_id, "update_id"),
        "binding": binding.to_payload(),
        "target": target.to_payload(),
        "snapshot": snapshot.manifest_payload(),
        "archive_policy": policy.to_payload(),
        "created_at_utc": utc_now(),
    }
    try:
        io.checkpoint("before_update_backup_write", destination)
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            for member in snapshot.members:
                io.checkpoint("before_update_backup_member", destination)
                _copy_member_to_zip(archive, member)
                io.checkpoint("after_update_backup_member", destination)
            info = zipfile.ZipInfo("manifest.json")
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, canonical_json_bytes(manifest) + b"\n")
        io.fsync_file(temporary)
        os.replace(temporary, destination)
        io.fsync_directory(destination.parent)
        verified = verify_update_backup(destination, policy=policy)
        return verified[0], MappingProxyType(manifest)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def verify_update_backup(
    archive_path: Path,
    *,
    policy: ArchivePolicy | None = None,
) -> tuple[str, Mapping[str, object]]:
    policy = policy or ArchivePolicy()
    path = Path(archive_path).resolve(strict=False)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > policy.max_files + 1:
                raise ArchiveLimitError("Update backup exceeds max_files.")
            names: dict[str, zipfile.ZipInfo] = {}
            folded: set[str] = set()
            for info in infos:
                name = _safe_relative(info.filename)
                if name.casefold() in folded:
                    raise ArchiveSafetyError("Update backup contains duplicate/case-colliding paths.")
                folded.add(name.casefold())
                mode = (info.external_attr >> 16) & 0xFFFF
                if mode and stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                    raise ArchiveSafetyError(f"Update backup contains a non-regular member: {name}")
                if info.file_size > policy.max_member_bytes:
                    raise ArchiveLimitError("Update backup member exceeds limit.")
                names[name] = info
            if "manifest.json" not in names:
                raise ArchiveVerificationError("Update backup lacks manifest.json.")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if (
                not isinstance(manifest, dict)
                or manifest.get("schema_name") != UPDATE_BACKUP_SCHEMA_NAME
                or manifest.get("schema_version") != UPDATE_BACKUP_SCHEMA_VERSION
            ):
                raise ArchiveVerificationError("Update backup manifest schema is invalid.")
            snapshot = manifest.get("snapshot")
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("members"), list):
                raise ArchiveVerificationError("Update backup snapshot is invalid.")
            expected: dict[str, tuple[int, str]] = {}
            total = 0
            for raw in snapshot["members"]:
                if not isinstance(raw, dict):
                    raise ArchiveVerificationError("Update backup member evidence is invalid.")
                relative = _safe_relative(str(raw.get("relative_path") or ""))
                archive_name = f"payload/{relative}"
                size = raw.get("size")
                digest = raw.get("raw_sha256")
                if type(size) is not int or size < 0:
                    raise ArchiveVerificationError("Update backup member size is invalid.")
                _sha256_text(digest, "backup member raw_sha256")
                expected[archive_name] = (size, digest)
                total += size
            if total > policy.max_total_bytes:
                raise ArchiveLimitError("Update backup total exceeds limit.")
            if set(names) != {"manifest.json", *expected}:
                raise ArchiveVerificationError("Update backup members differ from its manifest.")
            for name, (size, digest) in expected.items():
                data = archive.read(name)
                if len(data) != size or sha256_bytes(data) != digest:
                    raise ArchiveVerificationError(f"Update backup member differs: {name}")
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        if isinstance(exc, (ArchiveSafetyError, ArchiveVerificationError, ArchiveLimitError)):
            raise
        raise ArchiveVerificationError(f"Cannot verify update backup {path}: {exc}") from exc
    digest, _ = sha256_file(path)
    return digest, MappingProxyType(manifest)


def _validate_binding_against_store(
    binding: UpdateLaunchBinding,
    *,
    repo_root: Path,
) -> tuple[MachineDataBasePaths, MachineDataPaths, ActiveMachine]:
    base = resolve_machine_data_base(
        app_local_data_root=binding.machine_data_root.parent,
        repo_root=Path(repo_root).resolve(strict=False),
        explicit_root=binding.machine_data_root,
    )
    pointer_bytes = base.active_machine_path.read_bytes()
    if sha256_bytes(pointer_bytes) != binding.active_pointer_sha256:
        raise MachineDataUpdateError("binding_mismatch", "Active-machine pointer hash differs.")
    try:
        active = require_authorized_active_machine(json.loads(pointer_bytes.decode("utf-8")))
    except Exception as exc:
        raise MachineDataUpdateError("binding_mismatch", f"Active-machine pointer is invalid: {exc}") from exc
    if (
        active.machine_uuid != binding.machine_uuid
        or active.machine_id != binding.machine_id
        or active.activation_id != binding.activation_id
        or active.migration_id != binding.migration_id
    ):
        raise MachineDataUpdateError("binding_mismatch", "Active-machine authority differs from the update request.")
    paths = build_machine_data_paths(base, active.machine_uuid)
    identity = parse_machine_identity(_read_json(paths.identity_path, "machine identity"))
    if identity.machine_uuid != binding.machine_uuid or identity.machine_id != binding.machine_id:
        raise MachineDataUpdateError("binding_mismatch", "Machine identity differs from the update request.")
    return base, paths, active


def _anchor_payload(
    *,
    paths: MachineDataPaths,
    active: ActiveMachine,
    app_version: str,
    app_commit: str,
    authorization_kind: str,
    update_id: str | None,
    authorization_relative_path: str | None,
    authorization_sha256: str | None,
    previous_anchor_sha256: str | None,
    release_contract: Mapping[str, object],
    clock: Callable[[], str],
) -> dict[str, object]:
    return {
        "schema_name": DEPLOYMENT_ANCHOR_SCHEMA_NAME,
        "schema_version": DEPLOYMENT_ANCHOR_SCHEMA_VERSION,
        "machine_data_root": str(paths.base.root),
        "machine_id": active.machine_id,
        "machine_uuid": active.machine_uuid,
        "activation_id": active.activation_id,
        "migration_id": active.migration_id,
        "app_version": str(app_version),
        "app_commit": str(app_commit),
        "authorization_kind": authorization_kind,
        "update_id": update_id,
        "authorization_relative_path": authorization_relative_path,
        "authorization_sha256": authorization_sha256,
        "previous_anchor_sha256": previous_anchor_sha256,
        "release_contract": dict(release_contract),
        "authorized_at_utc": clock(),
    }


def load_deployment_anchor(path: Path) -> Mapping[str, object]:
    payload = _read_json(path, "deployment anchor")
    if not isinstance(payload, dict):
        raise MachineDataUpdateError("deployment_anchor_invalid", "Deployment anchor must be an object.", recovery_required=True)
    expected = {
        "schema_name", "schema_version", "machine_data_root", "machine_id",
        "machine_uuid", "activation_id", "migration_id", "app_version",
        "app_commit", "authorization_kind", "update_id",
        "authorization_relative_path", "authorization_sha256",
        "previous_anchor_sha256", "release_contract", "authorized_at_utc",
    }
    if set(payload) != expected or payload.get("schema_name") != DEPLOYMENT_ANCHOR_SCHEMA_NAME or payload.get("schema_version") != DEPLOYMENT_ANCHOR_SCHEMA_VERSION:
        raise MachineDataUpdateError("deployment_anchor_invalid", "Deployment anchor schema/fields are invalid.", recovery_required=True)
    _uuid_text(payload.get("machine_uuid"), "anchor machine_uuid")
    _uuid_text(payload.get("activation_id"), "anchor activation_id")
    _uuid_text(payload.get("migration_id"), "anchor migration_id")
    parse_release_machine_data_contract(payload.get("release_contract"), required=True)
    if payload.get("authorization_kind") not in {"genesis", "update", "legacy_return_unchanged", "keep_canonical", "schema_transition"}:
        raise MachineDataUpdateError("deployment_anchor_invalid", "Deployment authorization kind is unknown.", recovery_required=True)
    if payload.get("update_id") is not None:
        _uuid_text(payload["update_id"], "anchor update_id")
    for name in ("authorization_sha256", "previous_anchor_sha256"):
        if payload.get(name) is not None:
            _sha256_text(payload[name], f"anchor {name}")
    return MappingProxyType(payload)


def validate_deployment_anchor(
    paths: MachineDataPaths,
    active: ActiveMachine,
    *,
    app_version: str,
    app_commit: str,
    release_contract: Mapping[str, object],
) -> Mapping[str, object]:
    anchor = load_deployment_anchor(paths.deployment_anchor_path)
    if (
        Path(str(anchor["machine_data_root"])).resolve(strict=False) != paths.base.root
        or anchor["machine_id"] != active.machine_id
        or anchor["machine_uuid"] != active.machine_uuid
        or anchor["activation_id"] != active.activation_id
        or anchor["migration_id"] != active.migration_id
        or anchor["app_version"] != app_version
        or not commit_identities_match(anchor["app_commit"], app_commit)
        or dict(anchor["release_contract"]) != dict(release_contract)
    ):
        raise MachineDataUpdateError(
            "deployment_anchor_mismatch",
            "The running application is not authorized by this machine-data deployment anchor.",
            recovery_required=True,
        )
    relative = anchor.get("authorization_relative_path")
    digest = anchor.get("authorization_sha256")
    if relative is not None:
        if not isinstance(relative, str) or not relative.startswith("transactions/"):
            raise MachineDataUpdateError("deployment_anchor_invalid", "Deployment authorization path is invalid.", recovery_required=True)
        authority = paths.update_history_root / relative
        if not authority.is_file() or sha256_file(authority)[0] != digest:
            raise MachineDataUpdateError("deployment_anchor_invalid", "Deployment authorization evidence differs.", recovery_required=True)
    return anchor


def _validate_genesis_enrollment_evidence(
    paths: MachineDataPaths,
    active: ActiveMachine,
    *,
    app_version: str,
    app_commit: str,
    update_compatibility: Mapping[str, object] | None,
) -> None:
    if app_version in GENESIS_ENROLLMENT_VERSIONS:
        authorized_sources = GENESIS_MIGRATION_SOURCE_VERSIONS
    else:
        compatibility = parse_release_update_compatibility(
            update_compatibility,
            required=True,
        )
        assert compatibility is not None
        authorized_sources = frozenset(compatibility["direct_legacy_sources"])
    try:
        migration = load_migration_receipt(paths.migration_receipt_path)
        activation = load_activation_receipt(paths.activation_receipt_path)
        verification = load_machine_verification(paths.verification_path)
        migration_sha = sha256_file(paths.migration_receipt_path)[0]
        activation_sha = sha256_file(paths.activation_receipt_path)[0]
        verification_sha = sha256_file(paths.verification_path)[0]
    except Exception as exc:
        raise MachineDataUpdateError(
            "deployment_anchor_missing",
            f"Genesis enrollment evidence could not be validated: {exc}",
            recovery_required=True,
        ) from exc
    if migration.source_version not in GENESIS_MIGRATION_SOURCE_VERSIONS:
        raise MachineDataUpdateError(
            "deployment_anchor_missing",
            "Genesis enrollment source release is not an approved legacy migration cohort.",
            recovery_required=True,
        )
    if migration.source_version not in authorized_sources:
        raise MachineDataUpdateError(
            "deployment_anchor_missing",
            f"Release {app_version} is not authorized for a direct migration from {migration.source_version}.",
            recovery_required=True,
        )
    if (
        migration.state is not MigrationState.COPIED_UNVERIFIED
        or migration.machine_id != active.machine_id
        or migration.machine_uuid != active.machine_uuid
        or migration.migration_id != active.migration_id
        or activation.machine_id != active.machine_id
        or activation.machine_uuid != active.machine_uuid
        or active.activation_receipt_sha256 != activation_sha
        or active.activation_id != activation.activation_id
        or active.migration_id != activation.migration_id
        or activation.migration_receipt_sha256 != migration_sha
        or activation.verification_sha256 != verification_sha
        or activation.backup_archive_sha256 != migration.backup_archive_sha256
        or verification.machine_id != active.machine_id
        or verification.machine_uuid != active.machine_uuid
        or verification.migration_id != active.migration_id
        or verification.migration_receipt_sha256 != migration_sha
        or verification.activation_ready is not True
        or activation.app_version != app_version
        or not commit_identities_match(activation.app_commit, app_commit)
        or verification.app_version != app_version
        or not commit_identities_match(verification.app_commit, app_commit)
    ):
        raise MachineDataUpdateError(
            "deployment_anchor_missing",
            "Genesis enrollment is not bound to this exact first-start application.",
            recovery_required=True,
        )


def _unresolved_transaction_directories(paths: MachineDataPaths) -> tuple[Path, ...]:
    root = paths.update_transactions_root
    if not root.exists():
        return ()
    if not root.is_dir() or _is_link_or_reparse(root):
        raise MachineDataUpdateError("recovery_required", "Update transaction root is unsafe.", recovery_required=True)
    unresolved = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if not child.is_dir() or _is_link_or_reparse(child):
            raise MachineDataUpdateError("recovery_required", f"Unexpected update-history entry: {child}", recovery_required=True)
        _uuid_text(child.name, "update transaction directory")
        if not (child / TERMINAL_RESULT_FILENAME).is_file():
            unresolved.append(child)
    return tuple(unresolved)


def _all_transaction_directories(paths: MachineDataPaths) -> tuple[Path, ...]:
    root = paths.update_transactions_root
    if not root.exists():
        return ()
    if not root.is_dir() or _is_link_or_reparse(root):
        raise MachineDataUpdateError("recovery_required", "Update transaction root is unsafe.", recovery_required=True)
    directories = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if not child.is_dir() or _is_link_or_reparse(child):
            raise MachineDataUpdateError("recovery_required", f"Unexpected update-history entry: {child}", recovery_required=True)
        _uuid_text(child.name, "update transaction directory")
        directories.append(child)
    return tuple(directories)


def inspect_deployment_gate(
    paths: MachineDataPaths,
    active: ActiveMachine,
    *,
    app_version: str,
    app_commit: str,
    release_contract: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    """Read-only preflight used by bootstrap inspection before lock acquisition."""

    if release_contract is None:
        return None
    contract = parse_release_machine_data_contract(dict(release_contract), required=True)
    assert contract is not None
    if paths.legacy_session_path.exists():
        from MachineDataCompatibility import compare_legacy_session

        comparison = compare_legacy_session(paths)
        if comparison.unchanged:
            # open_ready() owns the configuration lock and will append the
            # immutable unchanged-return resolution before MVC construction.
            return None
        raise MachineDataUpdateError(
            "legacy_session_unresolved",
            f"Legacy checkout-local data differs in {len(comparison.differences)} path(s).",
            recovery_required=True,
        )
    unresolved = _unresolved_transaction_directories(paths)
    if unresolved:
        raise MachineDataUpdateError(
            "update_recovery_required",
            f"An update transaction requires recovery: {unresolved[0]}",
            recovery_required=True,
        )
    if paths.deployment_anchor_path.exists():
        return validate_deployment_anchor(
            paths,
            active,
            app_version=app_version,
            app_commit=app_commit,
            release_contract=contract,
        )
    if _all_transaction_directories(paths):
        raise MachineDataUpdateError(
            "deployment_anchor_missing",
            "Deployment history exists but its anchor is missing.",
            recovery_required=True,
        )
    raise MachineDataUpdateError(
        "deployment_anchor_missing",
        "A missing deployment anchor cannot be enrolled during ordinary startup.",
        recovery_required=True,
    )


def validate_or_enroll_deployment(
    paths: MachineDataPaths,
    active: ActiveMachine,
    configuration_lock: AcquiredConfigurationLock,
    *,
    app_version: str,
    app_commit: str,
    release_contract: Mapping[str, object] | None,
    update_compatibility: Mapping[str, object] | None = None,
    allow_genesis_enrollment: bool = False,
    io: DurableFileOps | None = None,
    clock: Callable[[], str] = utc_now,
) -> Mapping[str, object] | None:
    """Validate M6 authority or create a reviewed first-start genesis anchor."""

    if release_contract is None:
        return None
    if type(allow_genesis_enrollment) is not bool:
        raise MachineDataUpdateError(
            "deployment_anchor_invalid",
            "Genesis enrollment authority must be an explicit boolean.",
            recovery_required=True,
        )
    release_contract = parse_release_machine_data_contract(dict(release_contract), required=True)
    assert release_contract is not None
    configuration_lock.assert_owns(paths)
    if paths.legacy_session_path.exists():
        raise MachineDataUpdateError(
            "legacy_session_unresolved",
            "A legacy compatibility session requires explicit comparison and resolution.",
            recovery_required=True,
        )
    unresolved = _unresolved_transaction_directories(paths)
    if unresolved:
        raise MachineDataUpdateError(
            "update_recovery_required",
            f"An update transaction requires recovery: {unresolved[0]}",
            recovery_required=True,
        )
    if paths.deployment_anchor_path.exists():
        return validate_deployment_anchor(
            paths,
            active,
            app_version=app_version,
            app_commit=app_commit,
            release_contract=release_contract,
        )
    if _all_transaction_directories(paths):
        raise MachineDataUpdateError(
            "deployment_anchor_missing",
            "Deployment history exists but its anchor is missing.",
            recovery_required=True,
        )
    if not allow_genesis_enrollment:
        raise MachineDataUpdateError(
            "deployment_anchor_missing",
            "Genesis enrollment is permitted only during the current reviewed activation transaction.",
            recovery_required=True,
        )
    _validate_genesis_enrollment_evidence(
        paths,
        active,
        app_version=app_version,
        app_commit=app_commit,
        update_compatibility=update_compatibility,
    )
    operations = io or DurableFileOps()
    payload = _anchor_payload(
        paths=paths,
        active=active,
        app_version=app_version,
        app_commit=app_commit,
        authorization_kind="genesis",
        update_id=None,
        authorization_relative_path=None,
        authorization_sha256=None,
        previous_anchor_sha256=None,
        release_contract=release_contract,
        clock=clock,
    )
    operations.atomic_write_json(
        paths.deployment_anchor_path,
        payload,
        checkpoint_prefix="deployment_genesis",
    )
    return validate_deployment_anchor(
        paths,
        active,
        app_version=app_version,
        app_commit=app_commit,
        release_contract=release_contract,
    )


def authorize_deployment_from_evidence(
    paths: MachineDataPaths,
    active: ActiveMachine,
    configuration_lock: AcquiredConfigurationLock,
    *,
    app_version: str,
    app_commit: str,
    release_contract: Mapping[str, object],
    authorization_kind: str,
    update_id: str,
    authority_path: Path,
    io: DurableFileOps | None = None,
    clock: Callable[[], str] = utc_now,
) -> Mapping[str, object]:
    """Advance deployment authority from an immutable external evidence file."""

    configuration_lock.assert_owns(paths)
    contract = parse_release_machine_data_contract(dict(release_contract), required=True)
    assert contract is not None
    if authorization_kind not in {"legacy_return_unchanged", "keep_canonical", "schema_transition"}:
        raise MachineDataUpdateError("deployment_anchor_invalid", "Unsupported deployment authorization kind.")
    update_id = _uuid_text(update_id, "update_id")
    authority = Path(authority_path).resolve(strict=False)
    history_root = paths.update_history_root.resolve(strict=False)
    if history_root not in authority.parents or not authority.is_file() or _is_link_or_reparse(authority):
        raise MachineDataUpdateError("deployment_anchor_invalid", "Deployment authority must be an immutable update-history file.")
    authority_sha, _ = sha256_file(authority)
    previous_anchor_sha = (
        sha256_file(paths.deployment_anchor_path)[0]
        if paths.deployment_anchor_path.is_file()
        else None
    )
    payload = _anchor_payload(
        paths=paths,
        active=active,
        app_version=app_version,
        app_commit=app_commit,
        authorization_kind=authorization_kind,
        update_id=update_id,
        authorization_relative_path=authority.relative_to(history_root).as_posix(),
        authorization_sha256=authority_sha,
        previous_anchor_sha256=previous_anchor_sha,
        release_contract=contract,
        clock=clock,
    )
    operations = io or DurableFileOps()
    operations.atomic_write_json(
        paths.deployment_anchor_path,
        payload,
        checkpoint_prefix="deployment_anchor_reentry",
    )
    return validate_deployment_anchor(
        paths,
        active,
        app_version=app_version,
        app_commit=app_commit,
        release_contract=contract,
    )


def load_current_release_machine_data_contract(
    repo_root: Path,
    app_version: str,
) -> Mapping[str, object] | None:
    manifest_path = Path(repo_root) / "releases" / f"{app_version}.json"
    if not manifest_path.is_file():
        return None
    payload = _read_json(manifest_path, "current release manifest")
    if not isinstance(payload, dict) or payload.get("version") != app_version:
        return None
    return parse_release_machine_data_contract(payload.get("machine_data"), required=False)


def load_current_release_update_compatibility(
    repo_root: Path,
    app_version: str,
) -> Mapping[str, object] | None:
    manifest_path = Path(repo_root) / "releases" / f"{app_version}.json"
    if not manifest_path.is_file():
        return None
    payload = _read_json(manifest_path, "current release manifest")
    if not isinstance(payload, dict) or payload.get("version") != app_version:
        return None
    return parse_release_update_compatibility(
        payload.get("update_compatibility"), required=False
    )


@dataclass
class PreparedUpdate:
    binding: UpdateLaunchBinding
    target: UpdateTarget
    paths: MachineDataPaths
    active: ActiveMachine
    transaction_root: Path
    snapshot: ProtectedSnapshot
    archive_path: Path
    archive_sha256: str
    archive_manifest: Mapping[str, object]
    update_lock: AcquiredUpdateLock
    configuration_lock: AcquiredConfigurationLock
    io: DurableFileOps
    policy: ArchivePolicy
    clock: Callable[[], str] = utc_now
    _previous_stage_sha256: str | None = None
    _git_applied: bool = False
    _closed: bool = False
    _terminal: bool = False

    @property
    def update_id(self) -> str:
        return self.binding.request_id

    def _write_stage(self, filename: str, stage: str, payload: Mapping[str, object]) -> tuple[Path, str]:
        path = self.transaction_root / filename
        stage_payload = {
            "schema_name": UPDATE_STAGE_SCHEMA_NAME,
            "schema_version": UPDATE_STAGE_SCHEMA_VERSION,
            "update_id": self.update_id,
            "stage": stage,
            "previous_stage_sha256": self._previous_stage_sha256,
            "recorded_at_utc": self.clock(),
            **dict(payload),
        }
        data = canonical_json_bytes(stage_payload) + b"\n"
        self.io.create_bytes_exclusive(path, data, checkpoint_prefix=f"update_{stage}")
        digest = sha256_bytes(data)
        self._previous_stage_sha256 = digest
        return path, digest

    def record_git_result(self, *, before_commit: str, after_commit: str, command: Sequence[str]) -> None:
        if not commit_identities_match(self.binding.source_commit, before_commit):
            raise MachineDataUpdateError("source_commit_mismatch", "Git source commit differs from the launch binding.")
        if after_commit != self.target.commit:
            raise MachineDataUpdateError(
                "target_commit_mismatch",
                "Git HEAD does not equal the verified target commit.",
                recovery_required=True,
            )
        self._write_stage(
            "04_git_result.json",
            "git_applied",
            {"before_commit": before_commit, "after_commit": after_commit, "command": list(command)},
        )
        self._git_applied = True

    def verify_after(self) -> ProtectedSnapshot:
        _, current_paths, current_active = _validate_binding_against_store(
            self.binding,
            repo_root=self.transaction_root,
        )
        if current_paths != self.paths or current_active != self.active:
            raise MachineDataUpdateError("post_update_mismatch", "Post-update machine authority differs.", recovery_required=True)
        try:
            after = capture_protected_snapshot(self.paths, self.active, policy=self.policy)
        except Exception as exc:
            raise MachineDataUpdateError(
                "post_update_data_mismatch",
                f"Protected machine data failed post-update validation: {exc}",
                recovery_required=self._git_applied,
            ) from exc
        transition = self.target.machine_data_contract["transition"]
        if transition == TRANSITION_NONE:
            if (
                after.fingerprint != self.snapshot.fingerprint
                or after.safety_snapshot_sha256 != self.snapshot.safety_snapshot_sha256
            ):
                raise MachineDataUpdateError(
                    "post_update_data_mismatch",
                    "Protected machine-data bytes differ after a no-schema update.",
                    recovery_required=self._git_applied,
                )
            stage = "post_verified"
        else:
            if after.fingerprint != self.snapshot.fingerprint:
                raise MachineDataUpdateError(
                    "pre_transition_data_mismatch",
                    "Machine data changed before the declared bootstrap transition.",
                    recovery_required=True,
                )
            stage = "target_bootstrap_required"
        self._write_stage(
            "05_post_update_verification.json",
            stage,
            {
                "protected_fingerprint": after.fingerprint,
                "safety_snapshot_sha256": after.safety_snapshot_sha256,
                "transition": transition,
            },
        )
        return after

    def authorize_relaunch(self) -> Path:
        if self.target.machine_data_contract["transition"] != TRANSITION_NONE:
            raise MachineDataUpdateError(
                "schema_transition_required",
                "The target requires bootstrap recovery before normal relaunch.",
                recovery_required=True,
            )
        auth_path, auth_sha = self._write_stage(
            RELAUNCH_STAGE_FILENAME,
            "relaunch_authorized",
            {
                "target_commit": self.target.commit,
                "protected_fingerprint": self.snapshot.fingerprint,
                "archive_sha256": self.archive_sha256,
            },
        )
        previous_anchor_sha = (
            sha256_file(self.paths.deployment_anchor_path)[0]
            if self.paths.deployment_anchor_path.is_file()
            else None
        )
        anchor = _anchor_payload(
            paths=self.paths,
            active=self.active,
            app_version=self.target.version,
            app_commit=self.target.commit,
            authorization_kind="update",
            update_id=self.update_id,
            authorization_relative_path=auth_path.relative_to(self.paths.update_history_root).as_posix(),
            authorization_sha256=auth_sha,
            previous_anchor_sha256=previous_anchor_sha,
            release_contract=self.target.machine_data_contract,
            clock=self.clock,
        )
        self.io.atomic_write_json(
            self.paths.deployment_anchor_path,
            anchor,
            checkpoint_prefix="deployment_anchor",
        )
        terminal = self._write_terminal(
            status="relaunch_authorized",
            relaunch_authorized=True,
            recovery_required=False,
            message="Machine data and target application commit were verified.",
        )
        return terminal

    def _write_terminal(
        self,
        *,
        status: str,
        relaunch_authorized: bool,
        recovery_required: bool,
        message: str,
    ) -> Path:
        if self._terminal:
            return self.transaction_root / TERMINAL_RESULT_FILENAME
        terminal_path, terminal_sha = self._write_stage(
            TERMINAL_RESULT_FILENAME,
            status,
            {
                "message": str(message),
                "relaunch_authorized": bool(relaunch_authorized),
                "recovery_required": bool(recovery_required),
                "target_commit": self.target.commit,
            },
        )
        latest = {
            "schema_name": LATEST_RESULT_SCHEMA_NAME,
            "schema_version": LATEST_RESULT_SCHEMA_VERSION,
            "update_id": self.update_id,
            "terminal_relative_path": terminal_path.relative_to(self.paths.update_history_root).as_posix(),
            "terminal_sha256": terminal_sha,
            "status": status,
            "relaunch_authorized": bool(relaunch_authorized),
            "recovery_required": bool(recovery_required),
        }
        self.io.atomic_write_json(
            self.paths.latest_update_result_path,
            latest,
            checkpoint_prefix="latest_update_result",
        )
        self._terminal = True
        return terminal_path

    def fail(self, message: str, *, recovery_required: bool | None = None) -> Path:
        required = self._git_applied if recovery_required is None else bool(recovery_required)
        return self._write_terminal(
            status="recovery_required" if required else "failed_before_git",
            relaunch_authorized=False,
            recovery_required=required,
            message=message,
        )

    def close(self) -> None:
        if self._closed:
            return
        self.configuration_lock.release()
        self.update_lock.release()
        self._closed = True

    def __enter__(self) -> "PreparedUpdate":
        return self

    def __exit__(self, exc_type, exc, _traceback) -> None:
        if exc is not None and not self._terminal:
            try:
                self.fail(str(exc), recovery_required=self._git_applied)
            except Exception:
                pass
        self.close()


def begin_update_preservation(
    binding: UpdateLaunchBinding,
    target: UpdateTarget,
    *,
    repo_root: Path,
    policy: ArchivePolicy | None = None,
    io: DurableFileOps | None = None,
    clock: Callable[[], str] = utc_now,
    require_deployment_anchor: bool = True,
) -> PreparedUpdate:
    """Acquire locks and produce a verified backup before caller mutates Git."""

    policy = policy or ArchivePolicy()
    operations = io or DurableFileOps()
    _, paths, active = _validate_binding_against_store(binding, repo_root=repo_root)
    update_lock = acquire_update_lock(paths)
    configuration_lock: AcquiredConfigurationLock | None = None
    transaction_root: Path | None = None
    prepared: PreparedUpdate | None = None
    try:
        configuration_lock = acquire_configuration_lock(paths)
        _, locked_paths, locked_active = _validate_binding_against_store(binding, repo_root=repo_root)
        if locked_paths != paths or locked_active != active:
            raise MachineDataUpdateError("binding_mismatch", "Machine authority changed while locks were acquired.")
        if paths.legacy_session_path.exists():
            raise MachineDataUpdateError("legacy_session_unresolved", "Resolve the legacy session before updating.")
        unresolved = _unresolved_transaction_directories(paths)
        if unresolved:
            raise MachineDataUpdateError(
                "update_recovery_required",
                f"Resolve unfinished update transaction {unresolved[0].name} before updating.",
                recovery_required=True,
            )
        if require_deployment_anchor:
            validate_deployment_anchor(
                paths,
                active,
                app_version=binding.source_app_version,
                app_commit=binding.source_commit,
                release_contract=load_deployment_anchor(paths.deployment_anchor_path)["release_contract"],
            )
        snapshot = capture_protected_snapshot(paths, active, policy=policy)
        transaction_root = paths.update_transactions_root / binding.request_id
        transaction_root.mkdir(parents=True, exist_ok=False)
        (transaction_root / "backup").mkdir()
        (transaction_root / "logs").mkdir()
        prepared = PreparedUpdate(
            binding=binding,
            target=target,
            paths=paths,
            active=active,
            transaction_root=transaction_root,
            snapshot=snapshot,
            archive_path=transaction_root / "backup" / "pre_update.machine-data.zip",
            archive_sha256="",
            archive_manifest=MappingProxyType({}),
            update_lock=update_lock,
            configuration_lock=configuration_lock,
            io=operations,
            policy=policy,
            clock=clock,
        )
        prepared._write_stage(
            "01_intent.json",
            "requested",
            {"binding": binding.to_payload(), "target": target.to_payload()},
        )
        manifest_payload = {
            "schema_name": UPDATE_MANIFEST_SCHEMA_NAME,
            "schema_version": UPDATE_MANIFEST_SCHEMA_VERSION,
            "update_id": binding.request_id,
            "binding": binding.to_payload(),
            "target": target.to_payload(),
            "snapshot": snapshot.manifest_payload(),
            "archive_policy": policy.to_payload(),
        }
        prepared._write_stage(
            "02_preflight_manifest.json",
            "preflight_validated",
            manifest_payload,
        )
        archive_sha, archive_manifest = create_update_backup(
            snapshot,
            prepared.archive_path,
            update_id=binding.request_id,
            binding=binding,
            target=target,
            policy=policy,
            io=operations,
        )
        prepared.archive_sha256 = archive_sha
        prepared.archive_manifest = archive_manifest
        live = capture_protected_snapshot(paths, active, policy=policy)
        if live.fingerprint != snapshot.fingerprint or live.safety_snapshot_sha256 != snapshot.safety_snapshot_sha256:
            raise MachineDataUpdateError("source_changed", "Machine data changed while the update backup was created.")
        prepared._write_stage(
            "03_backup_verification.json",
            "backup_verified",
            {
                "archive_relative_path": prepared.archive_path.relative_to(paths.update_history_root).as_posix(),
                "archive_sha256": archive_sha,
                "protected_fingerprint": snapshot.fingerprint,
                "safety_snapshot_sha256": snapshot.safety_snapshot_sha256,
            },
        )
        return prepared
    except Exception as exc:
        if prepared is not None:
            try:
                prepared.fail(str(exc), recovery_required=False)
            except Exception:
                pass
        elif transaction_root is not None:
            try:
                payload = {
                    "schema_name": UPDATE_STAGE_SCHEMA_NAME,
                    "schema_version": UPDATE_STAGE_SCHEMA_VERSION,
                    "update_id": binding.request_id,
                    "stage": "failed_before_git",
                    "previous_stage_sha256": None,
                    "recorded_at_utc": clock(),
                    "message": str(exc),
                    "relaunch_authorized": False,
                    "recovery_required": False,
                }
                operations.create_bytes_exclusive(
                    transaction_root / TERMINAL_RESULT_FILENAME,
                    canonical_json_bytes(payload) + b"\n",
                    checkpoint_prefix="update_failed_before_git",
                )
            except Exception:
                pass
        if configuration_lock is not None:
            configuration_lock.release()
        update_lock.release()
        raise


def all_saved_targets_verified(snapshot: ProtectedSnapshot) -> tuple[bool, tuple[str, ...]]:
    targets = snapshot.safety_snapshot.get("targets", {})
    blocked = []
    if not isinstance(targets, Mapping):
        return False, ("authorization_state_invalid",)
    for key, payload in targets.items():
        authorization = payload.get("authorization", {}) if isinstance(payload, Mapping) else {}
        state = authorization.get("state") if isinstance(authorization, Mapping) else None
        if state == "revoked_pending_verification" or not isinstance(state, str):
            blocked.append(str(key))
    return not blocked, tuple(sorted(blocked))


__all__ = [
    "DEPLOYMENT_ANCHOR_SCHEMA_NAME",
    "DEPLOYMENT_ANCHOR_SCHEMA_VERSION",
    "LATEST_RESULT_SCHEMA_NAME",
    "GENESIS_ENROLLMENT_VERSION",
    "GENESIS_ENROLLMENT_VERSIONS",
    "GENESIS_MIGRATION_SOURCE_VERSIONS",
    "MachineDataUpdateError",
    "PreparedUpdate",
    "ProtectedMember",
    "ProtectedSnapshot",
    "TRANSITION_BOOTSTRAP_RECOVERY",
    "TRANSITION_NONE",
    "UPDATE_COMPATIBILITY_SCHEMA_VERSION",
    "UPDATE_CONTRACT_NAME",
    "UpdateLaunchBinding",
    "UpdateTarget",
    "all_saved_targets_verified",
    "authorize_deployment_from_evidence",
    "begin_update_preservation",
    "build_update_launch_binding",
    "capture_protected_snapshot",
    "create_update_backup",
    "inspect_deployment_gate",
    "load_current_release_machine_data_contract",
    "load_current_release_update_compatibility",
    "load_deployment_anchor",
    "parse_release_machine_data_contract",
    "parse_release_update_compatibility",
    "validate_deployment_anchor",
    "commit_identities_match",
    "validate_or_enroll_deployment",
    "verify_update_backup",
]
