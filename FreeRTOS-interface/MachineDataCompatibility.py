"""Exact, support-guided compatibility export for legacy checkout-local apps."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Callable, Mapping
from uuid import UUID

import LocalConfig
from MachineData import ActiveMachine, MachineDataPaths
from MachineDataArchive import (
    ArchivePolicy,
    ArchiveSafetyError,
    ArchiveVerificationError,
    DurableFileOps,
    canonical_json_bytes,
    semantic_json_sha256,
    sha256_bytes,
    sha256_file,
)
from MachineDataLock import AcquiredConfigurationLock
from MachineDataUpdate import (
    MachineDataUpdateError,
    PreparedUpdate,
    authorize_deployment_from_evidence,
    all_saved_targets_verified,
    parse_release_machine_data_contract,
    utc_now,
)


COMPATIBILITY_SCHEMA_NAME = "labcraft.legacy_compatibility_profiles"
COMPATIBILITY_SCHEMA_VERSION = 1
LEGACY_EXPORT_SCHEMA_NAME = "labcraft.legacy_compatibility_export"
LEGACY_EXPORT_SCHEMA_VERSION = 1
LEGACY_SESSION_SCHEMA_NAME = "labcraft.legacy_rollback_session"
LEGACY_SESSION_SCHEMA_VERSION = 1
LEGACY_COMPARISON_SCHEMA_NAME = "labcraft.legacy_return_comparison"
LEGACY_COMPARISON_SCHEMA_VERSION = 1
LEGACY_RESOLUTION_SCHEMA_NAME = "labcraft.legacy_return_resolution"
LEGACY_RESOLUTION_SCHEMA_VERSION = 1
DIRECTORY_BACKUP_SCHEMA_NAME = "labcraft.checkout_local_backup"
DIRECTORY_BACKUP_SCHEMA_VERSION = 1

DEFAULT_COMPATIBILITY_CATALOG_PATH = (
    Path(__file__).resolve().parent
    / "Policies"
    / "legacy_compatibility_profiles_v1.json"
)
_WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class LegacyCompatibilityError(MachineDataUpdateError):
    pass


@dataclass(frozen=True)
class LegacyMapping:
    source_path: str
    legacy_path: str
    required: bool
    is_prefix: bool


@dataclass(frozen=True)
class LegacyCompatibilityProfile:
    profile_id: str
    tag: str
    commit_sha: str
    release_manifest_sha256: str
    requires_firmware_attestation: bool
    mappings: tuple[LegacyMapping, ...]
    catalog_sha256: str


@dataclass(frozen=True)
class LegacyCompatibilityCatalog:
    profiles: tuple[LegacyCompatibilityProfile, ...]
    catalog_sha256: str

    def match(
        self,
        *,
        tag: str,
        commit_sha: str,
        release_manifest_sha256: str,
    ) -> LegacyCompatibilityProfile:
        matches = [profile for profile in self.profiles if profile.tag == tag]
        if len(matches) != 1:
            raise LegacyCompatibilityError(
                "legacy_target_unsupported",
                f"No exact reviewed compatibility profile exists for {tag}.",
            )
        profile = matches[0]
        if (
            profile.commit_sha != commit_sha
            or profile.release_manifest_sha256 != release_manifest_sha256
        ):
            raise LegacyCompatibilityError(
                "legacy_target_mismatch",
                "The legacy tag commit or release manifest differs from its reviewed profile.",
            )
        return profile


@dataclass(frozen=True)
class LegacyExportResult:
    profile: LegacyCompatibilityProfile
    export_manifest_path: Path
    export_manifest_sha256: str
    active_local_path: Path
    existing_local_backup_path: Path | None
    session_path: Path


@dataclass(frozen=True)
class LegacyComparison:
    session: Mapping[str, object]
    current_members: tuple[Mapping[str, object], ...]
    differences: tuple[Mapping[str, object], ...]
    comparison_payload: Mapping[str, object]

    @property
    def unchanged(self) -> bool:
        return not self.differences


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _safe_relative(value: object, label: str, *, allow_prefix: bool = False) -> tuple[str, bool]:
    if not isinstance(value, str) or not value:
        raise LegacyCompatibilityError("compatibility_profile_invalid", f"{label} is required.")
    is_prefix = allow_prefix and value.endswith("/")
    trimmed = value[:-1] if is_prefix else value
    if not trimmed or "\\" in trimmed or trimmed.startswith("/"):
        raise LegacyCompatibilityError("compatibility_profile_invalid", f"Unsafe {label}: {value!r}")
    pure = PurePosixPath(trimmed)
    if any(part in {"", ".", ".."} for part in pure.parts) or ":" in pure.parts[0] or pure.as_posix() != trimmed:
        raise LegacyCompatibilityError("compatibility_profile_invalid", f"Unsafe {label}: {value!r}")
    return trimmed, is_prefix


def _is_link_or_reparse(path: Path) -> bool:
    details = Path(path).lstat()
    attributes = getattr(details, "st_file_attributes", 0)
    return stat.S_ISLNK(details.st_mode) or bool(attributes & _WINDOWS_REPARSE_POINT)


def load_compatibility_catalog(
    path: Path = DEFAULT_COMPATIBILITY_CATALOG_PATH,
) -> LegacyCompatibilityCatalog:
    source = Path(path)
    try:
        raw = source.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LegacyCompatibilityError("compatibility_profile_invalid", f"Cannot load compatibility catalog: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_name", "schema_version", "profiles", "source_to_legacy"}:
        raise LegacyCompatibilityError("compatibility_profile_invalid", "Compatibility catalog fields are invalid.")
    if payload.get("schema_name") != COMPATIBILITY_SCHEMA_NAME or payload.get("schema_version") != COMPATIBILITY_SCHEMA_VERSION:
        raise LegacyCompatibilityError("compatibility_profile_invalid", "Compatibility catalog schema is unsupported.")
    raw_mappings = payload.get("source_to_legacy")
    if not isinstance(raw_mappings, list) or not raw_mappings:
        raise LegacyCompatibilityError("compatibility_profile_invalid", "Compatibility mappings are required.")
    mappings = []
    source_seen: set[str] = set()
    destination_seen: set[str] = set()
    for raw_mapping in raw_mappings:
        if not isinstance(raw_mapping, dict) or set(raw_mapping) != {"source_path", "legacy_path", "required"}:
            raise LegacyCompatibilityError("compatibility_profile_invalid", "Compatibility mapping fields are invalid.")
        source_path, source_prefix = _safe_relative(raw_mapping["source_path"], "source_path", allow_prefix=True)
        legacy_path, legacy_prefix = _safe_relative(raw_mapping["legacy_path"], "legacy_path", allow_prefix=True)
        if source_prefix != legacy_prefix or type(raw_mapping["required"]) is not bool:
            raise LegacyCompatibilityError("compatibility_profile_invalid", "Compatibility prefix/required fields are invalid.")
        if source_path.casefold() in source_seen or legacy_path.casefold() in destination_seen:
            raise LegacyCompatibilityError("compatibility_profile_invalid", "Compatibility mappings overlap or duplicate.")
        source_seen.add(source_path.casefold())
        destination_seen.add(legacy_path.casefold())
        mappings.append(LegacyMapping(source_path, legacy_path, raw_mapping["required"], source_prefix))

    catalog_sha = sha256_bytes(raw)
    profiles = []
    tags: set[str] = set()
    ids: set[str] = set()
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise LegacyCompatibilityError("compatibility_profile_invalid", "Compatibility profiles are required.")
    for raw_profile in raw_profiles:
        expected = {
            "profile_id", "tag", "commit_sha",
            "release_manifest_canonical_sha256", "requires_firmware_attestation",
        }
        if not isinstance(raw_profile, dict) or set(raw_profile) != expected:
            raise LegacyCompatibilityError("compatibility_profile_invalid", "Compatibility profile fields are invalid.")
        profile_id = raw_profile["profile_id"]
        tag = raw_profile["tag"]
        commit = raw_profile["commit_sha"]
        manifest_sha = raw_profile["release_manifest_canonical_sha256"]
        if not isinstance(profile_id, str) or not profile_id or profile_id in ids:
            raise LegacyCompatibilityError("compatibility_profile_invalid", "Profile IDs must be unique text.")
        if not isinstance(tag, str) or not tag.startswith("v") or tag in tags:
            raise LegacyCompatibilityError("compatibility_profile_invalid", "Profile tags must be unique release tags.")
        if not isinstance(commit, str) or len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
            raise LegacyCompatibilityError("compatibility_profile_invalid", "Profile commit SHA is invalid.")
        if not _is_sha256(manifest_sha) or type(raw_profile["requires_firmware_attestation"]) is not bool:
            raise LegacyCompatibilityError("compatibility_profile_invalid", "Profile manifest/firmware fields are invalid.")
        ids.add(profile_id)
        tags.add(tag)
        profiles.append(
            LegacyCompatibilityProfile(
                profile_id,
                tag,
                commit,
                manifest_sha,
                raw_profile["requires_firmware_attestation"],
                tuple(mappings),
                catalog_sha,
            )
        )
    return LegacyCompatibilityCatalog(tuple(profiles), catalog_sha)


def _capture_directory(root: Path, policy: ArchivePolicy) -> tuple[Mapping[str, object], ...]:
    root = Path(root)
    if not root.is_dir() or _is_link_or_reparse(root):
        raise ArchiveSafetyError(f"Directory is missing or unsafe: {root}")
    members: list[dict[str, object]] = []
    folded: set[str] = set()
    total = 0
    for directory, directory_names, filenames in os.walk(root, followlinks=False):
        directory_names.sort(key=str.casefold)
        filenames.sort(key=str.casefold)
        for name in list(directory_names):
            path = Path(directory) / name
            if _is_link_or_reparse(path):
                raise ArchiveSafetyError(f"Directory contains link/reparse point: {path}")
        for name in filenames:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            _safe_relative(relative, "directory member")
            if _is_link_or_reparse(path) or not path.is_file():
                raise ArchiveSafetyError(f"Directory contains unsafe member: {relative}")
            if relative.casefold() in folded:
                raise ArchiveSafetyError("Directory contains case-colliding members.")
            folded.add(relative.casefold())
            data = path.read_bytes()
            total += len(data)
            if len(members) + 1 > policy.max_files or len(data) > policy.max_member_bytes or total > policy.max_total_bytes:
                raise ArchiveSafetyError("Directory exceeds compatibility archive limits.")
            semantic = None
            if path.suffix.casefold() == ".json":
                try:
                    semantic = semantic_json_sha256(json.loads(data.decode("utf-8")))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    semantic = None
            item: dict[str, object] = {
                "relative_path": relative,
                "size": len(data),
                "raw_sha256": sha256_bytes(data),
            }
            if semantic is not None:
                item["semantic_json_sha256"] = semantic
            members.append(item)
    return tuple(sorted(members, key=lambda item: str(item["relative_path"])))


def _create_directory_backup(
    root: Path,
    destination: Path,
    *,
    update_id: str,
    policy: ArchivePolicy,
    io: DurableFileOps,
) -> tuple[str, tuple[Mapping[str, object], ...]]:
    members = _capture_directory(root, policy)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent))
    os.close(descriptor)
    temporary = Path(temporary_name)
    manifest = {
        "schema_name": DIRECTORY_BACKUP_SCHEMA_NAME,
        "schema_version": DIRECTORY_BACKUP_SCHEMA_VERSION,
        "update_id": str(UUID(update_id)),
        "members": list(members),
        "archive_policy": policy.to_payload(),
    }
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            for member in members:
                relative = str(member["relative_path"])
                data = (root / relative).read_bytes()
                if len(data) != member["size"] or sha256_bytes(data) != member["raw_sha256"]:
                    raise ArchiveVerificationError(f"Directory changed while archived: {relative}")
                info = zipfile.ZipInfo(f"payload/{relative}")
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                archive.writestr(info, data)
            info = zipfile.ZipInfo("manifest.json")
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, canonical_json_bytes(manifest) + b"\n")
        io.fsync_file(temporary)
        os.replace(temporary, destination)
        io.fsync_directory(destination.parent)
        _verify_directory_backup(destination, policy=policy)
        return sha256_file(destination)[0], members
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _verify_directory_backup(path: Path, *, policy: ArchivePolicy) -> Mapping[str, object]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = {info.filename: info for info in archive.infolist()}
            if "manifest.json" not in names:
                raise ArchiveVerificationError("Checkout-local backup lacks manifest.")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("schema_name") != DIRECTORY_BACKUP_SCHEMA_NAME or manifest.get("schema_version") != DIRECTORY_BACKUP_SCHEMA_VERSION:
                raise ArchiveVerificationError("Checkout-local backup manifest is invalid.")
            expected = {}
            total = 0
            for item in manifest.get("members", []):
                if not isinstance(item, dict):
                    raise ArchiveVerificationError("Checkout-local member evidence is invalid.")
                relative, _ = _safe_relative(item.get("relative_path"), "backup member")
                expected[f"payload/{relative}"] = item
                total += int(item.get("size", -1))
            if total > policy.max_total_bytes or set(names) != {"manifest.json", *expected}:
                raise ArchiveVerificationError("Checkout-local backup inventory differs.")
            for name, item in expected.items():
                data = archive.read(name)
                if len(data) != item.get("size") or sha256_bytes(data) != item.get("raw_sha256"):
                    raise ArchiveVerificationError(f"Checkout-local backup differs: {name}")
            return MappingProxyType(manifest)
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        if isinstance(exc, (ArchiveSafetyError, ArchiveVerificationError)):
            raise
        raise ArchiveVerificationError(f"Cannot verify checkout-local backup: {exc}") from exc


def _copy_mapping(source_root: Path, destination_root: Path, mapping: LegacyMapping, io: DurableFileOps) -> None:
    source = source_root / mapping.source_path
    destination = destination_root / mapping.legacy_path
    if mapping.is_prefix:
        if not source.exists():
            if mapping.required:
                raise LegacyCompatibilityError("legacy_export_invalid", f"Required canonical directory is missing: {mapping.source_path}")
            return
        if not source.is_dir() or _is_link_or_reparse(source):
            raise LegacyCompatibilityError("legacy_export_invalid", f"Canonical directory is unsafe: {mapping.source_path}")
        for item in _capture_directory(source, ArchivePolicy()):
            relative = str(item["relative_path"])
            data = (source / relative).read_bytes()
            io.atomic_write_bytes(destination / relative, data, checkpoint_prefix="legacy_export_member")
        return
    if not source.exists():
        if mapping.required:
            raise LegacyCompatibilityError("legacy_export_invalid", f"Required canonical file is missing: {mapping.source_path}")
        return
    if not source.is_file() or _is_link_or_reparse(source):
        raise LegacyCompatibilityError("legacy_export_invalid", f"Canonical file is unsafe: {mapping.source_path}")
    io.atomic_write_bytes(destination, source.read_bytes(), checkpoint_prefix="legacy_export_member")


def _validate_legacy_active_tree(local_root: Path, profile: LegacyCompatibilityProfile, policy: ArchivePolicy) -> tuple[Mapping[str, object], ...]:
    for filename, expected_type in LocalConfig.machine_config_top_level_types().items():
        path = local_root / filename
        payload = LocalConfig.validate_machine_config_file(path, filename)
        if not isinstance(payload, expected_type):
            raise LegacyCompatibilityError("legacy_export_invalid", f"Legacy {filename} has the wrong top-level type.")
    calibration_root = local_root / "CalibrationMemory"
    if not calibration_root.is_dir():
        raise LegacyCompatibilityError("legacy_export_invalid", "Legacy CalibrationMemory is missing.")
    for relative, expected_type in LocalConfig.calibration_memory_seed_top_level_types().items():
        path = calibration_root / relative
        if not path.is_file():
            raise LegacyCompatibilityError("legacy_export_invalid", f"Legacy CalibrationMemory seed is missing: {relative}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, expected_type):
            raise LegacyCompatibilityError("legacy_export_invalid", f"Legacy CalibrationMemory seed is invalid: {relative}")
    return _capture_directory(local_root, policy)


def create_legacy_compatibility_export(
    prepared: PreparedUpdate,
    *,
    repo_root: Path,
    operator: str,
    reason: str,
    machine_id_confirmation: str,
    service_record_reference: str,
    firmware_attestation: str,
    catalog: LegacyCompatibilityCatalog | None = None,
) -> LegacyExportResult:
    if prepared.target.operation != "rollback":
        raise LegacyCompatibilityError("legacy_export_invalid", "Compatibility export is only valid for rollback.")
    catalog = catalog or load_compatibility_catalog()
    profile = catalog.match(
        tag=prepared.target.tag,
        commit_sha=prepared.target.commit,
        release_manifest_sha256=prepared.target.release_manifest_sha256,
    )
    operator = str(operator or "").strip()
    reason = str(reason or "").strip()
    service_record_reference = str(service_record_reference or "").strip()
    firmware_attestation = str(firmware_attestation or "").strip()
    if not operator or not reason or not service_record_reference:
        raise LegacyCompatibilityError("legacy_authorization_missing", "Operator, reason, and support/service reference are required.")
    if machine_id_confirmation != prepared.binding.machine_id:
        raise LegacyCompatibilityError("legacy_authorization_missing", "Exact machine ID confirmation is required.")
    if profile.requires_firmware_attestation and not firmware_attestation:
        raise LegacyCompatibilityError("firmware_attestation_missing", "A reviewed firmware-pairing attestation is required.")
    verified, blocked = all_saved_targets_verified(prepared.snapshot)
    if not verified:
        raise LegacyCompatibilityError(
            "legacy_targets_unverified",
            "Legacy rollback is blocked because saved targets are not verified: " + ", ".join(blocked),
        )

    repo = Path(repo_root).resolve(strict=False)
    local_root = repo / "local"
    if local_root.exists() and _is_link_or_reparse(local_root):
        raise LegacyCompatibilityError("legacy_export_invalid", "Checkout local/ is a link/reparse point.")
    workspace_parent = repo.parent / ".labcraft-compatibility" / sha256_bytes(str(repo).encode("utf-8"))[:16]
    workspace = workspace_parent / prepared.update_id
    workspace.mkdir(parents=True, exist_ok=False)
    stage = workspace / "new-local"
    stage.mkdir()
    prior = workspace / "previous-local"

    existing_backup = None
    existing_backup_sha = None
    existing_members: tuple[Mapping[str, object], ...] = ()
    if local_root.exists():
        if not local_root.is_dir():
            raise LegacyCompatibilityError("legacy_export_invalid", "Checkout local path is not a directory.")
        existing_backup = prepared.transaction_root / "backup" / "existing_checkout_local.zip"
        existing_backup_sha, existing_members = _create_directory_backup(
            local_root,
            existing_backup,
            update_id=prepared.update_id,
            policy=prepared.policy,
            io=prepared.io,
        )

    for mapping in profile.mappings:
        _copy_mapping(prepared.paths.machine_root, stage, mapping, prepared.io)
    staged_members = _validate_legacy_active_tree(stage, profile, prepared.policy)
    export_manifest = {
        "schema_name": LEGACY_EXPORT_SCHEMA_NAME,
        "schema_version": LEGACY_EXPORT_SCHEMA_VERSION,
        "update_id": prepared.update_id,
        "profile_id": profile.profile_id,
        "profile_catalog_sha256": profile.catalog_sha256,
        "target_tag": profile.tag,
        "target_commit": profile.commit_sha,
        "machine_id": prepared.binding.machine_id,
        "machine_uuid": prepared.binding.machine_uuid,
        "activation_id": prepared.binding.activation_id,
        "migration_id": prepared.binding.migration_id,
        "checkout_root": str(repo),
        "local_path": str(local_root),
        "operator": operator,
        "reason": reason,
        "service_record_reference": service_record_reference,
        "firmware_attestation": firmware_attestation,
        "canonical_fingerprint": prepared.snapshot.fingerprint,
        "members": list(staged_members),
        "existing_local_backup": (
            None
            if existing_backup is None
            else {
                "relative_path": existing_backup.relative_to(prepared.paths.update_history_root).as_posix(),
                "sha256": existing_backup_sha,
                "members": list(existing_members),
            }
        ),
        "created_at_utc": prepared.clock(),
    }
    legacy_root = prepared.transaction_root / "legacy"
    legacy_root.mkdir(exist_ok=True)
    export_manifest_path = legacy_root / "export_manifest.json"
    prepared.io.create_bytes_exclusive(
        export_manifest_path,
        canonical_json_bytes(export_manifest) + b"\n",
        checkpoint_prefix="legacy_export_manifest",
    )
    export_manifest_sha = sha256_file(export_manifest_path)[0]

    try:
        prepared.io.checkpoint("before_legacy_local_exchange", local_root)
        if local_root.exists():
            os.replace(local_root, prior)
            prepared.io.checkpoint("after_legacy_prior_rename", local_root)
        os.replace(stage, local_root)
        prepared.io.checkpoint("after_legacy_stage_rename", local_root)
        prepared.io.fsync_directory(repo)
        active_members = _validate_legacy_active_tree(local_root, profile, prepared.policy)
        if active_members != staged_members:
            raise LegacyCompatibilityError("legacy_export_invalid", "Activated legacy local bytes differ from the staged export.")
    except Exception:
        try:
            if not local_root.exists() and prior.exists():
                os.replace(prior, local_root)
        except OSError:
            pass
        raise

    session = {
        "schema_name": LEGACY_SESSION_SCHEMA_NAME,
        "schema_version": LEGACY_SESSION_SCHEMA_VERSION,
        "update_id": prepared.update_id,
        "profile_id": profile.profile_id,
        "profile_catalog_sha256": profile.catalog_sha256,
        "legacy_tag": profile.tag,
        "legacy_commit": profile.commit_sha,
        "machine_id": prepared.binding.machine_id,
        "machine_uuid": prepared.binding.machine_uuid,
        "activation_id": prepared.binding.activation_id,
        "migration_id": prepared.binding.migration_id,
        "checkout_root": str(repo),
        "local_path": str(local_root),
        "export_manifest_relative_path": export_manifest_path.relative_to(prepared.paths.update_history_root).as_posix(),
        "export_manifest_sha256": export_manifest_sha,
        "baseline_members": list(staged_members),
        "canonical_fingerprint": prepared.snapshot.fingerprint,
        "firmware_attestation": firmware_attestation,
        "opened_at_utc": prepared.clock(),
    }
    prepared.io.atomic_write_json(
        prepared.paths.legacy_session_path,
        session,
        checkpoint_prefix="legacy_session",
    )
    prepared._write_stage(
        "03b_compatibility_export.json",
        "compatibility_export_verified",
        {
            "profile_id": profile.profile_id,
            "export_manifest_relative_path": session["export_manifest_relative_path"],
            "export_manifest_sha256": export_manifest_sha,
            "active_local_path": str(local_root),
        },
    )
    return LegacyExportResult(
        profile,
        export_manifest_path,
        export_manifest_sha,
        local_root,
        existing_backup,
        prepared.paths.legacy_session_path,
    )


def _load_legacy_session(paths: MachineDataPaths) -> Mapping[str, object]:
    try:
        payload = json.loads(paths.legacy_session_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacyCompatibilityError("legacy_session_invalid", f"Cannot read legacy session: {exc}", recovery_required=True) from exc
    expected = {
        "schema_name", "schema_version", "update_id", "profile_id",
        "profile_catalog_sha256", "legacy_tag", "legacy_commit", "machine_id",
        "machine_uuid", "activation_id", "migration_id", "checkout_root",
        "local_path", "export_manifest_relative_path", "export_manifest_sha256",
        "baseline_members", "canonical_fingerprint", "firmware_attestation",
        "opened_at_utc",
    }
    if not isinstance(payload, dict) or set(payload) != expected or payload.get("schema_name") != LEGACY_SESSION_SCHEMA_NAME or payload.get("schema_version") != LEGACY_SESSION_SCHEMA_VERSION:
        raise LegacyCompatibilityError("legacy_session_invalid", "Legacy session schema/fields are invalid.", recovery_required=True)
    try:
        UUID(str(payload["update_id"]))
    except ValueError as exc:
        raise LegacyCompatibilityError("legacy_session_invalid", "Legacy session update_id is invalid.", recovery_required=True) from exc
    if payload["machine_uuid"] != paths.machine_uuid or Path(str(payload["local_path"])).name != "local":
        raise LegacyCompatibilityError("legacy_session_invalid", "Legacy session machine/path binding is invalid.", recovery_required=True)
    export_manifest = paths.update_history_root / str(payload["export_manifest_relative_path"])
    if not export_manifest.is_file() or sha256_file(export_manifest)[0] != payload["export_manifest_sha256"]:
        raise LegacyCompatibilityError("legacy_session_invalid", "Legacy export manifest differs.", recovery_required=True)
    return MappingProxyType(payload)


def compare_legacy_session(
    paths: MachineDataPaths,
    *,
    policy: ArchivePolicy | None = None,
    clock: Callable[[], str] = utc_now,
) -> LegacyComparison:
    session = _load_legacy_session(paths)
    policy = policy or ArchivePolicy()
    local_root = Path(str(session["local_path"])).resolve(strict=False)
    current = _capture_directory(local_root, policy) if local_root.is_dir() else ()
    baseline = {
        str(item["relative_path"]): item
        for item in session["baseline_members"]
        if isinstance(item, dict) and isinstance(item.get("relative_path"), str)
    }
    current_by_path = {str(item["relative_path"]): item for item in current}
    differences = []
    for relative in sorted(set(baseline) | set(current_by_path)):
        before = baseline.get(relative)
        after = current_by_path.get(relative)
        if before == after:
            continue
        if before is None:
            kind = "added"
        elif after is None:
            kind = "deleted"
        elif before.get("raw_sha256") != after.get("raw_sha256"):
            kind = (
                "representation_only"
                if before.get("semantic_json_sha256") is not None
                and before.get("semantic_json_sha256") == after.get("semantic_json_sha256")
                else "changed"
            )
        else:
            continue
        differences.append({"relative_path": relative, "kind": kind, "before": before, "after": after})
    comparison_payload = {
        "schema_name": LEGACY_COMPARISON_SCHEMA_NAME,
        "schema_version": LEGACY_COMPARISON_SCHEMA_VERSION,
        "update_id": session["update_id"],
        "machine_id": session["machine_id"],
        "machine_uuid": session["machine_uuid"],
        "legacy_tag": session["legacy_tag"],
        "legacy_commit": session["legacy_commit"],
        "unchanged": not differences,
        "differences": differences,
        "compared_at_utc": clock(),
    }
    return LegacyComparison(session, current, tuple(differences), MappingProxyType(comparison_payload))


def resolve_legacy_session(
    paths: MachineDataPaths,
    active: ActiveMachine,
    configuration_lock: AcquiredConfigurationLock,
    *,
    app_version: str,
    app_commit: str,
    release_contract: Mapping[str, object],
    keep_canonical: bool = False,
    operator: str = "",
    reason: str = "",
    service_record_reference: str = "",
    policy: ArchivePolicy | None = None,
    io: DurableFileOps | None = None,
    clock: Callable[[], str] = utc_now,
) -> Mapping[str, object]:
    configuration_lock.assert_owns(paths)
    contract = parse_release_machine_data_contract(dict(release_contract), required=True)
    assert contract is not None
    operations = io or DurableFileOps()
    policy = policy or ArchivePolicy()
    comparison = compare_legacy_session(paths, policy=policy, clock=clock)
    if comparison.differences and not keep_canonical:
        update_id = str(comparison.session["update_id"])
        comparison_path = paths.update_transactions_root / update_id / "legacy" / "comparison.json"
        if not comparison_path.exists():
            operations.create_bytes_exclusive(
                comparison_path,
                canonical_json_bytes(dict(comparison.comparison_payload)) + b"\n",
                checkpoint_prefix="legacy_comparison",
            )
        raise LegacyCompatibilityError(
            "legacy_conflict",
            f"Legacy checkout-local data differs in {len(comparison.differences)} path(s); explicit resolution is required.",
            recovery_required=True,
        )
    operator = str(operator or "").strip()
    reason = str(reason or "").strip()
    service_record_reference = str(service_record_reference or "").strip()
    if keep_canonical and (not operator or not reason or not service_record_reference):
        raise LegacyCompatibilityError("legacy_resolution_invalid", "Keep-canonical resolution requires operator, reason, and support reference.")
    update_id = str(comparison.session["update_id"])
    transaction_root = paths.update_transactions_root / update_id
    legacy_root = transaction_root / "legacy"
    legacy_root.mkdir(parents=True, exist_ok=True)
    backup_payload = None
    if keep_canonical:
        local_root = Path(str(comparison.session["local_path"])).resolve(strict=False)
        backup_path = transaction_root / "backup" / "legacy_return_local.zip"
        backup_sha, backup_members = _create_directory_backup(
            local_root,
            backup_path,
            update_id=update_id,
            policy=policy,
            io=operations,
        )
        backup_payload = {
            "relative_path": backup_path.relative_to(paths.update_history_root).as_posix(),
            "sha256": backup_sha,
            "members": list(backup_members),
        }
    comparison_path = legacy_root / "comparison.json"
    if not comparison_path.exists():
        operations.create_bytes_exclusive(
            comparison_path,
            canonical_json_bytes(dict(comparison.comparison_payload)) + b"\n",
            checkpoint_prefix="legacy_comparison",
        )
    resolution = {
        "schema_name": LEGACY_RESOLUTION_SCHEMA_NAME,
        "schema_version": LEGACY_RESOLUTION_SCHEMA_VERSION,
        "update_id": update_id,
        "resolution": "keep_canonical" if keep_canonical else "legacy_return_unchanged",
        "machine_id": active.machine_id,
        "machine_uuid": active.machine_uuid,
        "operator": operator or "automatic_exact_comparison",
        "reason": reason or "Legacy export bytes are unchanged.",
        "service_record_reference": service_record_reference or None,
        "legacy_backup": backup_payload,
        "comparison_sha256": sha256_file(comparison_path)[0],
        "resolved_at_utc": clock(),
    }
    resolution_path = legacy_root / "resolution.json"
    operations.create_bytes_exclusive(
        resolution_path,
        canonical_json_bytes(resolution) + b"\n",
        checkpoint_prefix="legacy_resolution",
    )
    anchor = authorize_deployment_from_evidence(
        paths,
        active,
        configuration_lock,
        app_version=app_version,
        app_commit=app_commit,
        release_contract=contract,
        authorization_kind="keep_canonical" if keep_canonical else "legacy_return_unchanged",
        update_id=update_id,
        authority_path=resolution_path,
        io=operations,
        clock=clock,
    )
    resolved_pointer = legacy_root / "session_pointer.resolved.json"
    operations.checkpoint("before_legacy_session_resolve", paths.legacy_session_path)
    os.replace(paths.legacy_session_path, resolved_pointer)
    operations.fsync_directory(paths.update_history_root)
    return anchor


__all__ = [
    "DEFAULT_COMPATIBILITY_CATALOG_PATH",
    "LegacyComparison",
    "LegacyCompatibilityCatalog",
    "LegacyCompatibilityError",
    "LegacyCompatibilityProfile",
    "LegacyExportResult",
    "compare_legacy_session",
    "create_legacy_compatibility_export",
    "load_compatibility_catalog",
    "resolve_legacy_session",
]
