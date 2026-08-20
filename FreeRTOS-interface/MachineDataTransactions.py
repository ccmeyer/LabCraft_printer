"""Transactional, auditable post-activation machine configuration.

This module is deliberately hardware-free.  It owns only canonical config,
history, pending journals, backups, and exact saved-target authorization state.
"""

from __future__ import annotations

import copy
import getpass
import json
import os
import shutil
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Callable, Mapping, Sequence
from uuid import UUID, uuid4

import LocalConfig
from MachineData import ActiveMachine, MachineDataPaths, MachineIdentity
from MachineDataArchive import (
    ArchiveVerificationError,
    DurableFileOps,
    canonical_json_bytes,
    semantic_json_sha256,
    sha256_bytes,
    sha256_file,
)
from MachineDataLock import AcquiredConfigurationLock
from MachineDataVerification import (
    MachineVerification,
    SavedTargetAuthorizationDecision,
    SavedTargetAuthorizationRequest,
    VerificationError,
    build_target_snapshot_from_documents,
    canonical_value_sha256,
)
from ConfigurationSafetyPolicy import (
    ConfigurationSafetyError,
    RESTORE_PRECONDITION_SCHEMA_NAME,
    RESTORE_PRECONDITION_SCHEMA_VERSION,
    parse_guard_assessment,
    parse_restore_guard_precondition,
    proposal_sha256,
)


EVENT_SCHEMA_NAME = "labcraft.configuration_event"
EVENT_SCHEMA_VERSION = 1
HEAD_SCHEMA_NAME = "labcraft.configuration_head"
HEAD_SCHEMA_VERSION = 1
JOURNAL_SCHEMA_NAME = "labcraft.configuration_transaction_journal"
JOURNAL_SCHEMA_VERSION = 1
BACKUP_SCHEMA_NAME = "labcraft.configuration_backup"
BACKUP_SCHEMA_VERSION = 1

EVENT_TYPES = frozenset(
    {"change", "import", "restore", "verification", "cancelled", "rejected", "recovery"}
)
NONMUTATING_EVENT_TYPES = frozenset({"verification", "cancelled", "rejected", "recovery"})
CURRENT_VERIFIED_STATES = frozenset(
    {
        "verified_from_trusted_existing_calibration",
        "verified_against_service_record",
        "verified_by_controlled_calibration",
        "operator_verified",
    }
)
REVOKED_STATE = "revoked_pending_verification"
CONFIG_FILENAMES = tuple(sorted(LocalConfig.machine_config_top_level_types()))
_WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class ConfigurationTransactionError(RuntimeError):
    """Base error for configuration history and transactions."""


class ConfigurationConflictError(ConfigurationTransactionError):
    """The proposal was based on a stale head or stale config bytes."""


class ConfigurationRecoveryRequired(ConfigurationTransactionError):
    """Configuration/history state is ambiguous and must fail closed."""


class ConfigurationValidationError(ConfigurationTransactionError):
    """A proposed or recorded configuration document is invalid."""


@dataclass(frozen=True)
class ConfigurationState:
    sequence: int
    latest_event_id: str | None
    latest_event_path: str | None
    latest_event_sha256: str | None
    config_sha256: Mapping[str, str]
    authorization: Mapping[str, Mapping[str, object]]
    baseline_verification_sha256: str
    has_history: bool
    pending: Mapping[str, object] | None
    inventory: Mapping[str, tuple[int, str]]


@dataclass(frozen=True)
class ConfigurationTransactionResult:
    status: str
    event_id: str
    transaction_id: str
    event_type: str
    state: ConfigurationState
    documents: Mapping[str, object]
    changed_targets: tuple[str, ...] = ()
    message: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationRecoveryRequired(f"{label} must be UUID text.")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ConfigurationRecoveryRequired(f"{label} is invalid.") from exc


def _canonical_utc(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationRecoveryRequired(f"{label} must be UTC timestamp text.")
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ConfigurationRecoveryRequired(f"{label} is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ConfigurationRecoveryRequired(f"{label} must identify UTC.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _json_bytes(payload: object) -> bytes:
    return canonical_json_bytes(payload) + b"\n"


def _read_json(path: Path, label: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationRecoveryRequired(f"Cannot read {label}: {exc}") from exc


def _require_exact_keys(payload: Mapping[str, object], keys: set[str], label: str) -> None:
    if set(payload) != keys:
        missing = sorted(keys.difference(payload))
        extra = sorted(set(payload).difference(keys))
        raise ConfigurationRecoveryRequired(
            f"{label} keys differ; missing={missing}, extra={extra}."
        )


def _safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise ConfigurationRecoveryRequired(f"{label} is not a safe relative path.")
    pure = PurePosixPath(value)
    if pure.as_posix() != value or any(part in {"", ".", ".."} for part in pure.parts):
        raise ConfigurationRecoveryRequired(f"{label} is not normalized.")
    if ":" in pure.parts[0]:
        raise ConfigurationRecoveryRequired(f"{label} is drive-qualified.")
    return value


def _is_link_or_reparse(path: Path) -> bool:
    details = path.lstat()
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & _WINDOWS_REPARSE_POINT
    )


def _config_path(paths: MachineDataPaths, filename: str) -> Path:
    if filename not in CONFIG_FILENAMES:
        raise ConfigurationValidationError(f"Unsupported governed config: {filename!r}")
    target = (paths.config_root / filename).resolve(strict=False)
    root = paths.config_root.resolve(strict=False)
    if target.parent != root:
        raise ConfigurationRecoveryRequired("Governed config path escaped config root.")
    return target


def _read_documents(paths: MachineDataPaths) -> dict[str, object]:
    documents: dict[str, object] = {}
    for filename in CONFIG_FILENAMES:
        path = _config_path(paths, filename)
        payload = _read_json(path, filename)
        try:
            if filename == "RegulatorProfiles.json":
                from RegulatorProfiles import validate_document

                payload = validate_document(payload)
            else:
                payload = LocalConfig.validate_machine_config_payload(filename, payload)
        except Exception as exc:
            raise ConfigurationValidationError(f"Invalid {filename}: {exc}") from exc
        documents[filename] = payload
    try:
        build_target_snapshot_from_documents(
            documents["Locations.json"],
            documents["Plates.json"],
            documents["Settings.json"],
        )
    except VerificationError as exc:
        raise ConfigurationValidationError(str(exc)) from exc
    flagged_default = next(
        plate["name"] for plate in documents["Plates.json"] if plate["default"]
    )
    if flagged_default != documents["Settings.json"]["DEFAULT_PLATE"]:
        raise ConfigurationValidationError(
            "Plates.json default and Settings.json DEFAULT_PLATE must identify the same plate."
        )
    return documents


def read_governed_documents(paths: MachineDataPaths) -> dict[str, object]:
    """Return a validated, detached snapshot of every governed document."""

    return copy.deepcopy(_read_documents(paths))


def _validate_documents(documents: Mapping[str, object]) -> dict[str, object]:
    if set(documents) != set(CONFIG_FILENAMES):
        raise ConfigurationValidationError("A complete governed document set is required.")
    validated: dict[str, object] = {}
    for filename in CONFIG_FILENAMES:
        try:
            if filename == "RegulatorProfiles.json":
                from RegulatorProfiles import validate_document

                validated[filename] = validate_document(documents[filename])
            else:
                validated[filename] = LocalConfig.validate_machine_config_payload(
                    filename, documents[filename]
                )
        except Exception as exc:
            raise ConfigurationValidationError(f"Invalid {filename}: {exc}") from exc
    try:
        build_target_snapshot_from_documents(
            validated["Locations.json"],
            validated["Plates.json"],
            validated["Settings.json"],
        )
    except VerificationError as exc:
        raise ConfigurationValidationError(str(exc)) from exc
    flagged_default = next(
        plate["name"] for plate in validated["Plates.json"] if plate["default"]
    )
    if flagged_default != validated["Settings.json"]["DEFAULT_PLATE"]:
        raise ConfigurationValidationError(
            "Plates.json default and Settings.json DEFAULT_PLATE must identify the same plate."
        )
    return validated


def _raw_config_hashes(paths: MachineDataPaths) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for filename in CONFIG_FILENAMES:
        try:
            hashes[filename] = sha256_file(_config_path(paths, filename))[0]
        except OSError as exc:
            raise ConfigurationRecoveryRequired(f"Cannot hash {filename}: {exc}") from exc
    return hashes


def _canonical_config_bytes(documents: Mapping[str, object]) -> dict[str, bytes]:
    return {filename: _json_bytes(documents[filename]) for filename in CONFIG_FILENAMES}


def _authorization_from_verification(
    verification: MachineVerification,
) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for key, target in verification.targets.items():
        out[key] = {
            "target_key": key,
            "kind": target.kind,
            "value_sha256": target.value_sha256,
            "source_file": target.source_file,
            "source_file_sha256": target.source_file_sha256,
            "state": target.state.value,
            "verified_at_utc": target.verified_at_utc,
            "verified_by": target.verified_by,
            "verification_method": target.state.value,
            "evidence_reference": "metadata/verification.json",
            "service_record_reference": target.service_record_reference,
        }
    return out


_AUTH_KEYS = {
    "target_key",
    "kind",
    "value_sha256",
    "source_file",
    "source_file_sha256",
    "state",
    "verified_at_utc",
    "verified_by",
    "verification_method",
    "evidence_reference",
    "service_record_reference",
}


def _parse_authorization(payload: object) -> dict[str, dict[str, object]]:
    if not isinstance(payload, dict):
        raise ConfigurationRecoveryRequired("Authorization state must be an object.")
    parsed: dict[str, dict[str, object]] = {}
    for key, raw in payload.items():
        if not isinstance(key, str) or not key or not isinstance(raw, dict):
            raise ConfigurationRecoveryRequired("Authorization entry is invalid.")
        _require_exact_keys(raw, _AUTH_KEYS, f"authorization {key}")
        if raw.get("target_key") != key:
            raise ConfigurationRecoveryRequired("Authorization target key differs.")
        for text_key in ("kind", "source_file", "state", "evidence_reference"):
            if not isinstance(raw.get(text_key), str) or not raw[text_key]:
                raise ConfigurationRecoveryRequired(f"Authorization {text_key} is invalid.")
        if not _is_sha256(raw.get("value_sha256")) or not _is_sha256(
            raw.get("source_file_sha256")
        ):
            raise ConfigurationRecoveryRequired("Authorization hash is invalid.")
        if raw["state"] not in CURRENT_VERIFIED_STATES | {REVOKED_STATE}:
            raise ConfigurationRecoveryRequired("Authorization state is unknown.")
        for nullable_text in (
            "verified_at_utc",
            "verified_by",
            "verification_method",
            "service_record_reference",
        ):
            value = raw.get(nullable_text)
            if value is not None and not isinstance(value, str):
                raise ConfigurationRecoveryRequired(
                    f"Authorization {nullable_text} is invalid."
                )
        if raw.get("verified_at_utc") is not None:
            _canonical_utc(raw["verified_at_utc"], "authorization verified_at_utc")
        parsed[key] = copy.deepcopy(raw)
    return parsed


def _parse_hash_map(payload: object, label: str) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) != set(CONFIG_FILENAMES):
        raise ConfigurationRecoveryRequired(f"{label} must cover every governed file.")
    if any(not _is_sha256(value) for value in payload.values()):
        raise ConfigurationRecoveryRequired(f"{label} contains an invalid hash.")
    return dict(payload)


_EVENT_KEYS = {
    "schema_name",
    "schema_version",
    "event_id",
    "sequence",
    "previous_event_sha256",
    "transaction_id",
    "machine_id",
    "machine_uuid",
    "activation_id",
    "baseline_verification_sha256",
    "event_type",
    "outcome",
    "created_at_utc",
    "actor",
    "application",
    "workflow",
    "reason",
    "config_before_sha256",
    "config_after_sha256",
    "changes",
    "authorization_after",
    "backup_manifest",
    "restore_reference",
    "directory_sync_supported",
}


def parse_configuration_event(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ConfigurationRecoveryRequired("Configuration event must be an object.")
    _require_exact_keys(payload, _EVENT_KEYS, "configuration event")
    if payload.get("schema_name") != EVENT_SCHEMA_NAME or payload.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise ConfigurationRecoveryRequired("Unknown configuration event schema.")
    event_id = _canonical_uuid(payload.get("event_id"), "event_id")
    transaction_id = _canonical_uuid(payload.get("transaction_id"), "transaction_id")
    machine_uuid = _canonical_uuid(payload.get("machine_uuid"), "machine_uuid")
    activation_id = _canonical_uuid(payload.get("activation_id"), "activation_id")
    sequence = payload.get("sequence")
    if type(sequence) is not int or sequence <= 0:
        raise ConfigurationRecoveryRequired("Event sequence must be positive.")
    previous = payload.get("previous_event_sha256")
    if previous is not None and not _is_sha256(previous):
        raise ConfigurationRecoveryRequired("Previous event hash is invalid.")
    if not _is_sha256(payload.get("baseline_verification_sha256")):
        raise ConfigurationRecoveryRequired("Baseline verification hash is invalid.")
    if payload.get("event_type") not in EVENT_TYPES:
        raise ConfigurationRecoveryRequired("Configuration event type is unknown.")
    for key in ("machine_id", "outcome", "workflow", "reason"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise ConfigurationRecoveryRequired(f"Event {key} is invalid.")
    _canonical_utc(payload.get("created_at_utc"), "event created_at_utc")
    actor = payload.get("actor")
    application = payload.get("application")
    if not isinstance(actor, dict) or set(actor) != {"operator", "os_account", "session_id"}:
        raise ConfigurationRecoveryRequired("Event actor is invalid.")
    if any(not isinstance(actor.get(key), str) or not actor[key].strip() for key in actor):
        raise ConfigurationRecoveryRequired("Event actor fields are invalid.")
    if not isinstance(application, dict) or set(application) != {"version", "commit"}:
        raise ConfigurationRecoveryRequired("Event application provenance is invalid.")
    if any(not isinstance(application.get(key), str) or not application[key].strip() for key in application):
        raise ConfigurationRecoveryRequired("Event application fields are invalid.")
    before = _parse_hash_map(payload.get("config_before_sha256"), "event before hashes")
    after = _parse_hash_map(payload.get("config_after_sha256"), "event after hashes")
    if not isinstance(payload.get("changes"), list):
        raise ConfigurationRecoveryRequired("Event changes must be a list.")
    if not payload["changes"]:
        raise ConfigurationRecoveryRequired("Event changes must not be empty.")
    authorization = _parse_authorization(payload.get("authorization_after"))
    backup = payload.get("backup_manifest")
    if backup is not None:
        if not isinstance(backup, dict) or set(backup) != {"relative_path", "raw_sha256"}:
            raise ConfigurationRecoveryRequired("Event backup reference is invalid.")
        _safe_relative(backup.get("relative_path"), "backup relative_path")
        if not _is_sha256(backup.get("raw_sha256")):
            raise ConfigurationRecoveryRequired("Event backup hash is invalid.")
        expected_backup = f"backups/configuration/{transaction_id}/manifest.json"
        if backup["relative_path"] != expected_backup:
            raise ConfigurationRecoveryRequired("Event backup path differs from its transaction.")
    restore = payload.get("restore_reference")
    if restore is not None and (not isinstance(restore, str) or not restore):
        raise ConfigurationRecoveryRequired("Event restore reference is invalid.")
    if type(payload.get("directory_sync_supported")) is not bool:
        raise ConfigurationRecoveryRequired("Event directory-sync field is invalid.")
    event_type = payload["event_type"]
    expected_outcomes = {
        "change": "committed",
        "import": "committed",
        "restore": "committed",
        "verification": "verified",
        "cancelled": "cancelled",
        "rejected": "rejected",
        "recovery": "recovered_abort",
    }
    if payload["outcome"] != expected_outcomes[event_type]:
        raise ConfigurationRecoveryRequired("Event outcome differs from its type.")
    affected = {name for name in CONFIG_FILENAMES if before[name] != after[name]}
    if event_type in {"change", "import", "restore"}:
        if not affected or backup is None:
            raise ConfigurationRecoveryRequired("Committed mutation lacks changed bytes or backup.")
    elif event_type != "recovery" and (affected or backup is not None):
        raise ConfigurationRecoveryRequired("Non-mutating event changes bytes or references a backup.")
    if event_type == "recovery" and (affected or backup is None):
        raise ConfigurationRecoveryRequired("Recovery event must prove an unchanged backed-up state.")
    if event_type == "restore" and restore is None:
        raise ConfigurationRecoveryRequired("Restore event lacks its source transaction reference.")
    if event_type not in {"restore", "recovery"} and restore is not None:
        raise ConfigurationRecoveryRequired("Event has an unexpected restore reference.")
    parsed = copy.deepcopy(payload)
    parsed.update(
        event_id=event_id,
        transaction_id=transaction_id,
        machine_uuid=machine_uuid,
        activation_id=activation_id,
        config_before_sha256=before,
        config_after_sha256=after,
        authorization_after=authorization,
    )
    return parsed


_HEAD_KEYS = {
    "schema_name",
    "schema_version",
    "machine_id",
    "machine_uuid",
    "activation_id",
    "baseline_verification_sha256",
    "latest_event_sequence",
    "latest_event_id",
    "latest_event_path",
    "latest_event_sha256",
    "config_sha256",
    "authorization",
    "created_at_utc",
    "updated_at_utc",
    "application",
}


def parse_configuration_head(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ConfigurationRecoveryRequired("Configuration head must be an object.")
    _require_exact_keys(payload, _HEAD_KEYS, "configuration head")
    if payload.get("schema_name") != HEAD_SCHEMA_NAME or payload.get("schema_version") != HEAD_SCHEMA_VERSION:
        raise ConfigurationRecoveryRequired("Unknown configuration head schema.")
    if type(payload.get("latest_event_sequence")) is not int or payload["latest_event_sequence"] <= 0:
        raise ConfigurationRecoveryRequired("Configuration head sequence is invalid.")
    for key in ("machine_id", "latest_event_path"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise ConfigurationRecoveryRequired(f"Configuration head {key} is invalid.")
    _safe_relative(payload["latest_event_path"], "head latest_event_path")
    for key in ("baseline_verification_sha256", "latest_event_sha256"):
        if not _is_sha256(payload.get(key)):
            raise ConfigurationRecoveryRequired(f"Configuration head {key} is invalid.")
    parsed = copy.deepcopy(payload)
    parsed["machine_uuid"] = _canonical_uuid(payload.get("machine_uuid"), "machine_uuid")
    parsed["activation_id"] = _canonical_uuid(payload.get("activation_id"), "activation_id")
    parsed["latest_event_id"] = _canonical_uuid(payload.get("latest_event_id"), "latest_event_id")
    parsed["config_sha256"] = _parse_hash_map(payload.get("config_sha256"), "head config hashes")
    parsed["authorization"] = _parse_authorization(payload.get("authorization"))
    _canonical_utc(payload.get("created_at_utc"), "head created_at_utc")
    _canonical_utc(payload.get("updated_at_utc"), "head updated_at_utc")
    application = payload.get("application")
    if not isinstance(application, dict) or set(application) != {"version", "commit"}:
        raise ConfigurationRecoveryRequired("Head application provenance is invalid.")
    return parsed


def _event_relative(sequence: int, event_id: str) -> str:
    return f"history/configuration_events/{sequence:020d}-{event_id}.json"


def _event_path(paths: MachineDataPaths, sequence: int, event_id: str) -> Path:
    return paths.machine_root / _event_relative(sequence, event_id)


def _evidence(path: Path) -> tuple[int, str]:
    digest, size = sha256_file(path)
    return size, digest


def _all_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if _is_link_or_reparse(root):
        raise ConfigurationRecoveryRequired(f"History path is a link/reparse point: {root}")
    result = []
    for path in sorted(root.rglob("*")):
        if _is_link_or_reparse(path):
            raise ConfigurationRecoveryRequired(f"History contains a link/reparse point: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ConfigurationRecoveryRequired(f"History contains a special file: {path}")
        result.append(path)
    return result


def _parse_backup_manifest(paths: MachineDataPaths, reference: Mapping[str, object]) -> dict[str, object]:
    relative = _safe_relative(reference.get("relative_path"), "backup manifest path")
    path = (paths.machine_root / relative).resolve(strict=False)
    root = paths.configuration_backups_root.resolve(strict=False)
    if root not in path.parents or path.name != "manifest.json":
        raise ConfigurationRecoveryRequired("Backup manifest escaped configuration backup root.")
    if sha256_file(path)[0] != reference.get("raw_sha256"):
        raise ConfigurationRecoveryRequired("Backup manifest hash differs from event.")
    payload = _read_json(path, "configuration backup manifest")
    if not isinstance(payload, dict) or payload.get("schema_name") != BACKUP_SCHEMA_NAME or payload.get("schema_version") != BACKUP_SCHEMA_VERSION:
        raise ConfigurationRecoveryRequired("Unknown configuration backup schema.")
    required = {
        "schema_name", "schema_version", "transaction_id", "machine_id", "machine_uuid",
        "activation_id", "created_at_utc", "actor", "workflow", "reason", "files",
        "evidence_fingerprint", "directory_sync_supported",
    }
    _require_exact_keys(payload, required, "configuration backup manifest")
    transaction_id = _canonical_uuid(payload.get("transaction_id"), "backup transaction_id")
    if path.parent.name != transaction_id:
        raise ConfigurationRecoveryRequired("Backup directory and transaction UUID differ.")
    _canonical_uuid(payload.get("machine_uuid"), "backup machine_uuid")
    _canonical_uuid(payload.get("activation_id"), "backup activation_id")
    _canonical_utc(payload.get("created_at_utc"), "backup created_at_utc")
    if not isinstance(payload.get("machine_id"), str) or not payload["machine_id"].strip():
        raise ConfigurationRecoveryRequired("Backup machine ID is invalid.")
    actor = payload.get("actor")
    if not isinstance(actor, dict) or set(actor) != {"operator", "os_account", "session_id"}:
        raise ConfigurationRecoveryRequired("Backup actor is invalid.")
    if any(not isinstance(actor.get(key), str) or not actor[key].strip() for key in actor):
        raise ConfigurationRecoveryRequired("Backup actor fields are invalid.")
    for key in ("workflow", "reason"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise ConfigurationRecoveryRequired(f"Backup {key} is invalid.")
    if type(payload.get("directory_sync_supported")) is not bool:
        raise ConfigurationRecoveryRequired("Backup directory-sync field is invalid.")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ConfigurationRecoveryRequired("Backup manifest files are invalid.")
    filenames = [item.get("filename") for item in files if isinstance(item, dict)]
    if len(filenames) != len(set(filenames)):
        raise ConfigurationRecoveryRequired("Backup manifest repeats a governed file.")
    fingerprints = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {
            "filename", "relative_path", "size", "raw_sha256", "semantic_json_sha256"
        }:
            raise ConfigurationRecoveryRequired("Backup file evidence is invalid.")
        filename = item.get("filename")
        if filename not in CONFIG_FILENAMES:
            raise ConfigurationRecoveryRequired("Backup references an unmanaged file.")
        member_relative = _safe_relative(item.get("relative_path"), "backup member path")
        expected = f"backups/configuration/{transaction_id}/before/config/{filename}"
        if member_relative != expected:
            raise ConfigurationRecoveryRequired("Backup member path differs from contract.")
        member = (paths.machine_root / member_relative).resolve(strict=False)
        if root not in member.parents or type(item.get("size")) is not int:
            raise ConfigurationRecoveryRequired("Backup member evidence is invalid.")
        digest, size = sha256_file(member)
        if size != item["size"] or digest != item.get("raw_sha256"):
            raise ConfigurationRecoveryRequired("Backup member bytes differ from manifest.")
        try:
            semantic = semantic_json_sha256(json.loads(member.read_text(encoding="utf-8")))
        except Exception as exc:
            raise ConfigurationRecoveryRequired(f"Backup member JSON is invalid: {exc}") from exc
        if semantic != item.get("semantic_json_sha256"):
            raise ConfigurationRecoveryRequired("Backup member semantic hash differs.")
        fingerprints.append(
            {"relative_path": member_relative, "size": size, "raw_sha256": digest}
        )
    if sha256_bytes(canonical_json_bytes(sorted(fingerprints, key=lambda item: item["relative_path"]))) != payload.get("evidence_fingerprint"):
        raise ConfigurationRecoveryRequired("Backup evidence fingerprint differs.")
    return copy.deepcopy(payload)


def _parse_journal(paths: MachineDataPaths) -> dict[str, object] | None:
    root = paths.pending_transactions_root
    if not root.exists():
        return None
    children = [child for child in root.iterdir() if child.is_dir()]
    other = [child for child in root.iterdir() if not child.is_dir()]
    if other or len(children) > 1:
        raise ConfigurationRecoveryRequired("Pending transaction inventory is ambiguous.")
    if not children:
        return None
    directory = children[0]
    if _is_link_or_reparse(directory):
        raise ConfigurationRecoveryRequired("Pending transaction is a link/reparse point.")
    transaction_id = _canonical_uuid(directory.name, "pending transaction directory")
    journal_path = directory / "journal.json"
    payload = _read_json(journal_path, "pending transaction journal")
    if not isinstance(payload, dict) or payload.get("schema_name") != JOURNAL_SCHEMA_NAME or payload.get("schema_version") != JOURNAL_SCHEMA_VERSION:
        raise ConfigurationRecoveryRequired("Unknown pending transaction schema.")
    required = {
        "schema_name", "schema_version", "transaction_id", "event_id", "event_sequence",
        "event_relative_path", "machine_id", "machine_uuid", "activation_id",
        "baseline_verification_sha256", "expected_previous_event_sha256", "event_type",
        "created_at_utc", "affected_files", "before_sha256", "after_sha256",
        "backup_manifest", "planned_event", "planned_event_sha256", "checkpoint",
        "directory_sync_supported",
    }
    _require_exact_keys(payload, required, "pending transaction journal")
    if _canonical_uuid(payload.get("transaction_id"), "journal transaction_id") != transaction_id:
        raise ConfigurationRecoveryRequired("Journal transaction UUID differs from directory.")
    if _canonical_uuid(payload.get("machine_uuid"), "journal machine_uuid") != paths.machine_uuid:
        raise ConfigurationRecoveryRequired("Journal machine UUID differs from its store.")
    _canonical_uuid(payload.get("activation_id"), "journal activation_id")
    if not isinstance(payload.get("machine_id"), str) or not payload["machine_id"].strip():
        raise ConfigurationRecoveryRequired("Journal machine ID is invalid.")
    _canonical_utc(payload.get("created_at_utc"), "journal created_at_utc")
    if not _is_sha256(payload.get("baseline_verification_sha256")):
        raise ConfigurationRecoveryRequired("Journal verification hash is invalid.")
    previous = payload.get("expected_previous_event_sha256")
    if previous is not None and not _is_sha256(previous):
        raise ConfigurationRecoveryRequired("Journal previous-event hash is invalid.")
    if payload.get("checkpoint") != "commit_intent":
        raise ConfigurationRecoveryRequired("Journal checkpoint is invalid.")
    if type(payload.get("directory_sync_supported")) is not bool:
        raise ConfigurationRecoveryRequired("Journal directory-sync field is invalid.")
    event = parse_configuration_event(payload.get("planned_event"))
    if event["transaction_id"] != transaction_id:
        raise ConfigurationRecoveryRequired("Journal event transaction UUID differs.")
    if sha256_bytes(_json_bytes(payload["planned_event"])) != payload.get("planned_event_sha256"):
        raise ConfigurationRecoveryRequired("Journal planned event hash differs.")
    affected = payload.get("affected_files")
    if not isinstance(affected, list) or len(set(affected)) != len(affected) or any(
        filename not in CONFIG_FILENAMES for filename in affected
    ):
        raise ConfigurationRecoveryRequired("Journal affected files are invalid.")
    before = _parse_hash_map(payload.get("before_sha256"), "journal before hashes")
    after = _parse_hash_map(payload.get("after_sha256"), "journal after hashes")
    if before != event["config_before_sha256"] or after != event["config_after_sha256"]:
        raise ConfigurationRecoveryRequired("Journal hashes differ from planned event.")
    expected_relative = _event_relative(event["sequence"], event["event_id"])
    if payload.get("event_relative_path") != expected_relative:
        raise ConfigurationRecoveryRequired("Journal event path differs from contract.")
    backup = payload.get("backup_manifest")
    if affected:
        if not isinstance(backup, dict):
            raise ConfigurationRecoveryRequired("Mutating journal lacks a backup reference.")
        backup_payload = _parse_backup_manifest(paths, backup)
        if backup_payload["transaction_id"] != transaction_id:
            raise ConfigurationRecoveryRequired("Journal backup transaction UUID differs.")
    elif backup is not None:
        raise ConfigurationRecoveryRequired("Non-mutating journal has a backup reference.")
    proposed_root = directory / "proposed"
    for filename in affected:
        proposed_path = proposed_root / filename
        try:
            digest = sha256_file(proposed_path)[0]
        except OSError as exc:
            raise ConfigurationRecoveryRequired(
                f"Cannot read pending proposed {filename}: {exc}"
            ) from exc
        if digest != after[filename]:
            raise ConfigurationRecoveryRequired(
                f"Pending proposed {filename} differs from its after hash."
            )
        payload_value = _read_json(proposed_path, f"pending proposed {filename}")
        try:
            if filename == "RegulatorProfiles.json":
                from RegulatorProfiles import validate_document

                validate_document(payload_value)
            else:
                LocalConfig.validate_machine_config_payload(filename, payload_value)
        except Exception as exc:
            raise ConfigurationRecoveryRequired(
                f"Pending proposed {filename} is invalid: {exc}"
            ) from exc
    parsed = copy.deepcopy(payload)
    parsed["planned_event"] = event
    parsed["before_sha256"] = before
    parsed["after_sha256"] = after
    parsed["pending_root"] = str(directory)
    return parsed


def _validate_current_authorization(
    paths: MachineDataPaths,
    config_hashes: Mapping[str, str],
    authorization: Mapping[str, Mapping[str, object]],
) -> None:
    documents = _read_documents(paths)
    snapshot = build_target_snapshot_from_documents(
        documents["Locations.json"], documents["Plates.json"], documents["Settings.json"]
    )
    if set(snapshot) != set(authorization):
        raise ConfigurationRecoveryRequired("Current target coverage differs from authorization state.")
    for key, (kind, source_file, value) in snapshot.items():
        entry = authorization[key]
        filename = Path(source_file).name
        if (
            entry["kind"] != kind
            or entry["source_file"] != source_file
            or entry["value_sha256"] != canonical_value_sha256(value)
            or entry["source_file_sha256"] != config_hashes[filename]
        ):
            raise ConfigurationRecoveryRequired(f"Authorization state differs for {key}.")


def inspect_configuration_state(
    paths: MachineDataPaths,
    identity: MachineIdentity,
    active: ActiveMachine,
    verification: MachineVerification,
    *,
    allow_pending: bool = True,
) -> ConfigurationState:
    """Validate and replay current history without modifying the store."""

    verification_sha = sha256_file(paths.verification_path)[0]
    baseline_hashes = dict(verification.config_file_sha256)
    authorization = _authorization_from_verification(verification)
    sequence = 0
    latest_id = latest_path = latest_sha = None
    inventory: dict[str, tuple[int, str]] = {}
    expected_backup_paths: set[str] = set()
    pending = _parse_journal(paths)
    pending_event_prior: dict[str, object] | None = None

    event_files = _all_files(paths.configuration_events_root)
    for event_path in event_files:
        relative = event_path.relative_to(paths.machine_root).as_posix()
        payload = parse_configuration_event(_read_json(event_path, "configuration event"))
        expected_sequence = sequence + 1
        expected_relative = _event_relative(expected_sequence, payload["event_id"])
        if relative != expected_relative or payload["sequence"] != expected_sequence:
            raise ConfigurationRecoveryRequired("Configuration event order/path differs.")
        if payload["previous_event_sha256"] != latest_sha:
            raise ConfigurationRecoveryRequired("Configuration event hash chain is broken.")
        if (
            payload["machine_id"] != identity.machine_id
            or payload["machine_uuid"] != identity.machine_uuid
            or payload["activation_id"] != active.activation_id
            or payload["baseline_verification_sha256"] != verification_sha
            or payload["config_before_sha256"] != baseline_hashes
        ):
            raise ConfigurationRecoveryRequired("Configuration event baseline binding differs.")
        if pending is not None and relative == pending.get("event_relative_path"):
            if payload != pending["planned_event"]:
                raise ConfigurationRecoveryRequired(
                    "Durable pending event differs from its planned event."
                )
            pending_event_prior = {
                "sequence": sequence,
                "latest_event_id": latest_id,
                "latest_event_path": latest_path,
                "latest_event_sha256": latest_sha,
                "config_sha256": copy.deepcopy(baseline_hashes),
                "authorization": copy.deepcopy(authorization),
            }
        if payload.get("backup_manifest") is not None:
            backup = _parse_backup_manifest(paths, payload["backup_manifest"])
            if (
                backup["transaction_id"] != payload["transaction_id"]
                or backup["machine_id"] != identity.machine_id
                or backup["machine_uuid"] != identity.machine_uuid
                or backup["activation_id"] != active.activation_id
            ):
                raise ConfigurationRecoveryRequired("Configuration event backup binding differs.")
            backup_by_name = {item["filename"]: item for item in backup["files"]}
            changed_files = {
                name
                for name in CONFIG_FILENAMES
                if payload["config_before_sha256"][name]
                != payload["config_after_sha256"][name]
            }
            expected_backed_files = (
                set(backup_by_name) if payload["event_type"] == "recovery" else changed_files
            )
            if set(backup_by_name) != expected_backed_files or any(
                backup_by_name[name]["raw_sha256"]
                != payload["config_before_sha256"][name]
                for name in backup_by_name
            ):
                raise ConfigurationRecoveryRequired(
                    "Configuration event backup does not prove its exact before files."
                )
            expected_backup_paths.add(payload["backup_manifest"]["relative_path"])
            expected_backup_paths.update(item["relative_path"] for item in backup["files"])
        sequence = expected_sequence
        baseline_hashes = dict(payload["config_after_sha256"])
        authorization = copy.deepcopy(payload["authorization_after"])
        latest_id = payload["event_id"]
        latest_path = relative
        latest_sha = sha256_file(event_path)[0]
        inventory[relative] = _evidence(event_path)

    head_path = paths.configuration_head_path
    if sequence:
        if not head_path.is_file():
            planned_path = pending.get("event_relative_path") if pending else None
            if planned_path != latest_path:
                raise ConfigurationRecoveryRequired("Configuration history lacks its head.")
        else:
            head = parse_configuration_head(_read_json(head_path, "configuration head"))
            matches_latest = (
                head["machine_id"] != identity.machine_id
                or head["machine_uuid"] != identity.machine_uuid
                or head["activation_id"] != active.activation_id
                or head["baseline_verification_sha256"] != verification_sha
                or head["latest_event_sequence"] != sequence
                or head["latest_event_id"] != latest_id
                or head["latest_event_path"] != latest_path
                or head["latest_event_sha256"] != latest_sha
                or head["config_sha256"] != baseline_hashes
                or head["authorization"] != authorization
            ) is False
            matches_pending_prior = False
            if pending_event_prior is not None and pending_event_prior["sequence"] > 0:
                matches_pending_prior = (
                    head["machine_id"] == identity.machine_id
                    and head["machine_uuid"] == identity.machine_uuid
                    and head["activation_id"] == active.activation_id
                    and head["baseline_verification_sha256"] == verification_sha
                    and head["latest_event_sequence"] == pending_event_prior["sequence"]
                    and head["latest_event_id"] == pending_event_prior["latest_event_id"]
                    and head["latest_event_path"] == pending_event_prior["latest_event_path"]
                    and head["latest_event_sha256"] == pending_event_prior["latest_event_sha256"]
                    and head["config_sha256"] == pending_event_prior["config_sha256"]
                    and head["authorization"] == pending_event_prior["authorization"]
                )
            if not matches_latest and not matches_pending_prior:
                raise ConfigurationRecoveryRequired("Configuration head differs from replayed history.")
            inventory[head_path.relative_to(paths.machine_root).as_posix()] = _evidence(head_path)
    elif head_path.exists():
        raise ConfigurationRecoveryRequired("Configuration head exists without an event.")

    current_hashes = _raw_config_hashes(paths)
    if pending is None:
        if current_hashes != baseline_hashes:
            if sequence == 0:
                raise ConfigurationRecoveryRequired(
                    "Governed config changed without configuration history."
                )
            raise ConfigurationRecoveryRequired("Current config differs from configuration head.")
        _validate_current_authorization(paths, current_hashes, authorization)
    else:
        if not allow_pending:
            raise ConfigurationRecoveryRequired("A pending configuration transaction requires recovery.")
        if pending["event_sequence"] != sequence + 1:
            # The event may already be durable while the head is still old.
            if pending["event_sequence"] != sequence:
                raise ConfigurationRecoveryRequired("Pending event sequence is inconsistent.")
        affected = set(pending["affected_files"])
        for filename in CONFIG_FILENAMES:
            allowed = {pending["before_sha256"][filename], pending["after_sha256"][filename]}
            if filename not in affected:
                allowed = {pending["before_sha256"][filename]}
            if current_hashes[filename] not in allowed:
                raise ConfigurationRecoveryRequired(
                    f"Pending {filename} has neither its before nor after hash."
                )
        if (
            pending["machine_id"] != identity.machine_id
            or pending["machine_uuid"] != identity.machine_uuid
            or pending["activation_id"] != active.activation_id
            or pending["baseline_verification_sha256"] != verification_sha
            or pending["expected_previous_event_sha256"]
            != pending["planned_event"]["previous_event_sha256"]
        ):
            raise ConfigurationRecoveryRequired("Pending transaction binding differs.")
        pending_event = pending["planned_event"]
        if (
            pending_event["machine_id"] != identity.machine_id
            or pending_event["machine_uuid"] != identity.machine_uuid
            or pending_event["activation_id"] != active.activation_id
            or pending_event["baseline_verification_sha256"] != verification_sha
        ):
            raise ConfigurationRecoveryRequired("Pending event binding differs.")
        pending_root = Path(str(pending["pending_root"]))
        expected_pending_paths = {
            (pending_root / "journal.json").relative_to(paths.machine_root).as_posix(),
            *(
                (pending_root / "proposed" / filename)
                .relative_to(paths.machine_root)
                .as_posix()
                for filename in pending["affected_files"]
            ),
        }
        actual_pending_paths = {
            path.relative_to(paths.machine_root).as_posix()
            for path in _all_files(paths.pending_transactions_root)
        }
        if actual_pending_paths != expected_pending_paths:
            raise ConfigurationRecoveryRequired("Pending transaction inventory differs from its journal.")
        for relative in expected_pending_paths:
            inventory[relative] = _evidence(paths.machine_root / relative)
        if pending.get("backup_manifest") is not None:
            backup = _parse_backup_manifest(paths, pending["backup_manifest"])
            if (
                backup["transaction_id"] != pending["transaction_id"]
                or backup["machine_id"] != identity.machine_id
                or backup["machine_uuid"] != identity.machine_uuid
                or backup["activation_id"] != active.activation_id
            ):
                raise ConfigurationRecoveryRequired("Pending backup binding differs.")
            backup_by_name = {item["filename"]: item for item in backup["files"]}
            if set(backup_by_name) != set(pending["affected_files"]) or any(
                backup_by_name[name]["raw_sha256"] != pending["before_sha256"][name]
                for name in backup_by_name
            ):
                raise ConfigurationRecoveryRequired(
                    "Pending backup does not prove every exact before file."
                )
            expected_backup_paths.add(pending["backup_manifest"]["relative_path"])
            expected_backup_paths.update(item["relative_path"] for item in backup["files"])

    actual_backup_paths = {
        path.relative_to(paths.machine_root).as_posix()
        for path in _all_files(paths.configuration_backups_root)
    }
    if actual_backup_paths != expected_backup_paths:
        raise ConfigurationRecoveryRequired("Configuration backup inventory differs from history.")
    for relative in expected_backup_paths:
        inventory[relative] = _evidence(paths.machine_root / relative)

    return ConfigurationState(
        sequence=sequence,
        latest_event_id=latest_id,
        latest_event_path=latest_path,
        latest_event_sha256=latest_sha,
        config_sha256=MappingProxyType(dict(baseline_hashes)),
        authorization=MappingProxyType(
            {key: MappingProxyType(copy.deepcopy(value)) for key, value in authorization.items()}
        ),
        baseline_verification_sha256=verification_sha,
        has_history=bool(sequence),
        pending=MappingProxyType(pending) if pending is not None else None,
        inventory=MappingProxyType(dict(inventory)),
    )


def build_active_tree_overrides(
    paths: MachineDataPaths, state: ConfigurationState
) -> dict[str, tuple[int, str]]:
    """Return exact mutable/additional files accepted by active-tree validation."""

    overrides = dict(state.inventory)
    for filename in CONFIG_FILENAMES:
        path = _config_path(paths, filename)
        overrides[f"config/{filename}"] = _evidence(path)
    return overrides


def _make_authorization_after(
    before_documents: Mapping[str, object],
    after_documents: Mapping[str, object],
    before_authorization: Mapping[str, Mapping[str, object]],
    after_hashes: Mapping[str, str],
    affected_files: set[str],
    semantically_affected_files: set[str] | None = None,
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]], tuple[str, ...]]:
    semantic_files = (
        affected_files
        if semantically_affected_files is None
        else semantically_affected_files
    )
    before_snapshot = build_target_snapshot_from_documents(
        before_documents["Locations.json"], before_documents["Plates.json"], before_documents["Settings.json"]
    )
    after_snapshot = build_target_snapshot_from_documents(
        after_documents["Locations.json"], after_documents["Plates.json"], after_documents["Settings.json"]
    )
    revoke_all = bool({"Settings.json", "Obstacles.json"}.intersection(semantic_files))
    forced_dependency_changes: set[str] = set()
    if "Plates.json" in semantic_files:
        before_plates = {
            str(plate["name"]).casefold(): plate for plate in before_documents["Plates.json"]
        }
        after_plates = {
            str(plate["name"]).casefold(): plate for plate in after_documents["Plates.json"]
        }
        for name in set(before_plates) | set(after_plates):
            if semantic_json_sha256(before_plates.get(name)) != semantic_json_sha256(
                after_plates.get(name)
            ):
                forced_dependency_changes.add(f"plate:{name}")
    authorization: dict[str, dict[str, object]] = {}
    changes: list[dict[str, object]] = []
    changed_targets: list[str] = []
    for key in sorted(set(before_snapshot) | set(after_snapshot)):
        old = before_snapshot.get(key)
        new = after_snapshot.get(key)
        old_value = old[2] if old else None
        new_value = new[2] if new else None
        value_changed = (
            old is None
            or new is None
            or canonical_value_sha256(old_value) != canonical_value_sha256(new_value)
            or key in forced_dependency_changes
        )
        if value_changed:
            changed_targets.append(key)
            changes.append(
                {
                    "target_key": key,
                    "kind": new[0] if new else old[0],
                    "before": copy.deepcopy(old_value),
                    "after": copy.deepcopy(new_value),
                    "dependency_changed": key in forced_dependency_changes,
                }
            )
        if new is None:
            continue
        kind, source_file, value = new
        filename = Path(source_file).name
        prior = before_authorization.get(key)
        can_carry = not revoke_all and not value_changed and prior is not None
        if can_carry:
            entry = copy.deepcopy(dict(prior))
            entry["value_sha256"] = canonical_value_sha256(value)
            entry["source_file_sha256"] = after_hashes[filename]
        else:
            entry = {
                "target_key": key,
                "kind": kind,
                "value_sha256": canonical_value_sha256(value),
                "source_file": source_file,
                "source_file_sha256": after_hashes[filename],
                "state": REVOKED_STATE,
                "verified_at_utc": None,
                "verified_by": None,
                "verification_method": None,
                "evidence_reference": "pending configuration event",
                "service_record_reference": None,
            }
            if key not in changed_targets:
                changed_targets.append(key)
        authorization[key] = entry
    for filename in sorted(affected_files):
        changes.append(
            {
                "document": filename,
                "before": copy.deepcopy(before_documents[filename]),
                "after": copy.deepcopy(after_documents[filename]),
            }
        )
    return authorization, changes, tuple(sorted(changed_targets))


def _head_payload(
    *,
    identity: MachineIdentity,
    active: ActiveMachine,
    verification_sha: str,
    event: Mapping[str, object],
    event_relative: str,
    event_sha: str,
    created_at: str,
    app_version: str,
    app_commit: str,
) -> dict[str, object]:
    return {
        "schema_name": HEAD_SCHEMA_NAME,
        "schema_version": HEAD_SCHEMA_VERSION,
        "machine_id": identity.machine_id,
        "machine_uuid": identity.machine_uuid,
        "activation_id": active.activation_id,
        "baseline_verification_sha256": verification_sha,
        "latest_event_sequence": event["sequence"],
        "latest_event_id": event["event_id"],
        "latest_event_path": event_relative,
        "latest_event_sha256": event_sha,
        "config_sha256": copy.deepcopy(event["config_after_sha256"]),
        "authorization": copy.deepcopy(event["authorization_after"]),
        "created_at_utc": created_at,
        "updated_at_utc": event["created_at_utc"],
        "application": {"version": app_version, "commit": app_commit},
    }


class TransactionalSavedTargetAuthorizer:
    """Exact movement gate backed by the latest validated transaction state."""

    def __init__(self, service: "ConfigurationTransactionService") -> None:
        self.service = service

    def authorize(self, request: SavedTargetAuthorizationRequest) -> SavedTargetAuthorizationDecision:
        key = str(request.target_key or "")
        deny = lambda code, message: SavedTargetAuthorizationDecision(False, code, message, key, None)
        state = self.service.state
        if request.machine_uuid != self.service.paths.machine_uuid:
            return deny("machine_mismatch", "Saved target belongs to a different machine.")
        target = state.authorization.get(key)
        if target is None:
            return deny("target_unverified", f"Saved target {key!r} is not verified.")
        if target["state"] not in CURRENT_VERIFIED_STATES:
            return deny("target_revoked", f"Saved target {key!r} requires verification.")
        if target["kind"] != request.target_kind:
            return deny("target_kind_mismatch", "Saved target kind changed.")
        if canonical_value_sha256(dict(request.base_value)) != target["value_sha256"]:
            return deny("target_value_changed", "Saved target values changed after verification.")
        if target["kind"] == "location":
            try:
                expected = {
                    axis: int(request.base_value[axis]) + int(request.offsets.get(axis, 0))
                    for axis in ("X", "Y", "Z")
                }
                actual = {axis: int(request.final_coordinates[axis]) for axis in ("X", "Y", "Z")}
            except (KeyError, TypeError, ValueError):
                return deny("target_coordinates_invalid", "Saved target coordinates are invalid.")
            if actual != expected:
                return deny("target_derivation_changed", "Final coordinates differ from reviewed offsets.")
        source = self.service.paths.machine_root / str(target["source_file"])
        try:
            current_sha = sha256_file(source)[0]
        except OSError:
            return deny("source_file_missing", "Saved target source file is unavailable.")
        if current_sha != target["source_file_sha256"]:
            return deny("source_file_changed", "Saved target source file changed after authorization.")
        return SavedTargetAuthorizationDecision(
            True, "authorized", "Saved target matches current configuration history.", key, target["value_sha256"]
        )


class ConfigurationTransactionService:
    """Single writer for governed post-activation machine configuration."""

    def __init__(
        self,
        *,
        paths: MachineDataPaths,
        identity: MachineIdentity,
        active: ActiveMachine,
        verification: MachineVerification,
        configuration_lock: AcquiredConfigurationLock,
        app_version: str,
        app_commit: str,
        clock: Callable[[], str] = utc_now,
        uuid_factory: Callable[[], object] = uuid4,
        io: DurableFileOps | None = None,
        os_account: str | None = None,
    ) -> None:
        configuration_lock.assert_owns(paths)
        self.paths = paths
        self.identity = identity
        self.active = active
        self.verification = verification
        self.configuration_lock = configuration_lock
        self.app_version = str(app_version or "").strip()
        self.app_commit = str(app_commit or "").strip()
        if not self.app_version or not self.app_commit:
            raise ConfigurationTransactionError("Application provenance is required.")
        self.clock = clock
        self.uuid_factory = uuid_factory
        self.io = io or DurableFileOps()
        self.os_account = str(os_account or getpass.getuser() or "unknown").strip()
        self.session_id = str(uuid_factory())
        self._writer_mutex = threading.Lock()
        # Enabled only by the authorized production bootstrap after the tracked
        # policy and active documents have been validated. This keeps the pure
        # M4 repository independently testable without creating a permissive
        # production path.
        self.require_configuration_guard_evidence = False
        self.state = inspect_configuration_state(paths, identity, active, verification)
        self.saved_target_authorizer = TransactionalSavedTargetAuthorizer(self)

    def refresh(self, *, allow_pending: bool = False) -> ConfigurationState:
        self.configuration_lock.assert_owns(self.paths)
        self.state = inspect_configuration_state(
            self.paths,
            self.identity,
            self.active,
            self.verification,
            allow_pending=allow_pending,
        )
        return self.state

    def reconcile(self) -> ConfigurationState:
        self.configuration_lock.assert_owns(self.paths)
        state = inspect_configuration_state(
            self.paths, self.identity, self.active, self.verification, allow_pending=True
        )
        if state.pending is None:
            self.state = state
            return state
        if not self._writer_mutex.acquire(blocking=False):
            raise ConfigurationConflictError("A configuration operation is already active.")
        try:
            self._reconcile_pending(dict(state.pending), state)
            return self.refresh(allow_pending=False)
        finally:
            self._writer_mutex.release()

    def _reconcile_pending(self, journal: Mapping[str, object], state: ConfigurationState) -> None:
        affected = list(journal["affected_files"])
        current = _raw_config_hashes(self.paths)
        all_after = all(current[name] == journal["after_sha256"][name] for name in affected)
        event = dict(journal["planned_event"])
        event_path = self.paths.machine_root / str(journal["event_relative_path"])

        if affected and not all_after:
            backup = _parse_backup_manifest(self.paths, journal["backup_manifest"])
            by_name = {item["filename"]: item for item in backup["files"]}
            for filename in affected:
                item = by_name[filename]
                source = self.paths.machine_root / item["relative_path"]
                self.io.atomic_write_bytes(
                    _config_path(self.paths, filename),
                    source.read_bytes(),
                    checkpoint_prefix="configuration_recovery_restore",
                )
            restored = _raw_config_hashes(self.paths)
            if restored != journal["before_sha256"]:
                raise ConfigurationRecoveryRequired("Pending rollback could not restore exact before state.")
            event = copy.deepcopy(event)
            event["event_type"] = "recovery"
            event["outcome"] = "recovered_abort"
            event["reason"] = "Recovered interrupted configuration transaction to exact pre-change bytes."
            event["config_after_sha256"] = copy.deepcopy(journal["before_sha256"])
            # Use the previous validated authorization state.
            event["authorization_after"] = {
                key: dict(value) for key, value in state.authorization.items()
            }
            event["changes"] = [
                {"recovery": "restored_pre_change_backup", "affected_files": affected}
            ]

        event_bytes = _json_bytes(event)
        if event_path.exists():
            if event_path.read_bytes() != event_bytes:
                raise ConfigurationRecoveryRequired("Durable pending event differs from recovery plan.")
        else:
            self.io.create_bytes_exclusive(
                event_path, event_bytes, checkpoint_prefix="configuration_recovery_event"
            )
        event_sha = sha256_file(event_path)[0]
        prior_created = self.clock()
        if self.paths.configuration_head_path.exists():
            try:
                prior_created = parse_configuration_head(
                    _read_json(self.paths.configuration_head_path, "configuration head")
                )["created_at_utc"]
            except ConfigurationRecoveryRequired:
                # A stale/partial head is replaced only when the previous event
                # binding in the journal and the recovered event are exact.
                prior_created = event["created_at_utc"]
        head = _head_payload(
            identity=self.identity,
            active=self.active,
            verification_sha=state.baseline_verification_sha256,
            event=event,
            event_relative=journal["event_relative_path"],
            event_sha=event_sha,
            created_at=prior_created,
            app_version=self.app_version,
            app_commit=self.app_commit,
        )
        self.io.atomic_write_json(
            self.paths.configuration_head_path,
            head,
            checkpoint_prefix="configuration_recovery_head",
        )
        self._remove_pending(Path(str(journal["pending_root"])))

    def _remove_pending(self, directory: Path) -> None:
        root = self.paths.pending_transactions_root.resolve(strict=False)
        target = directory.resolve(strict=False)
        if target.parent != root:
            raise ConfigurationRecoveryRequired("Refusing unsafe pending cleanup target.")
        _canonical_uuid(target.name, "pending cleanup UUID")
        if target.exists() and _is_link_or_reparse(target):
            raise ConfigurationRecoveryRequired("Refusing pending link/reparse cleanup.")
        if target.exists():
            shutil.rmtree(target)
            self.io.fsync_directory(root)

    def _remove_precommit_directory(self, root: Path, transaction_id: str) -> None:
        """Remove only a known transaction directory before commit intent exists."""

        transaction_id = _canonical_uuid(transaction_id, "pre-commit cleanup UUID")
        resolved_root = root.resolve(strict=False)
        target = (root / transaction_id).resolve(strict=False)
        if target.parent != resolved_root:
            raise ConfigurationRecoveryRequired("Refusing unsafe pre-commit cleanup target.")
        if target.exists() and _is_link_or_reparse(target):
            raise ConfigurationRecoveryRequired("Refusing pre-commit link/reparse cleanup.")
        if target.exists():
            shutil.rmtree(target)
            self.io.fsync_directory(resolved_root)

    def _actor(self, operator: str) -> dict[str, str]:
        operator = str(operator or "").strip()
        if not operator:
            raise ConfigurationValidationError("Operator name is required.")
        return {
            "operator": operator,
            "os_account": self.os_account,
            "session_id": self.session_id,
        }

    def commit_documents(
        self,
        proposed: Mapping[str, object],
        *,
        operator: str,
        reason: str,
        workflow: str,
        event_type: str = "change",
        expected_config_sha256: Mapping[str, str] | None = None,
        restore_reference: str | None = None,
        guard_evidence: Mapping[str, object] | None = None,
    ) -> ConfigurationTransactionResult:
        return self._commit_documents(
            proposed,
            operator=operator,
            reason=reason,
            workflow=workflow,
            event_type=event_type,
            expected_config_sha256=expected_config_sha256,
            restore_reference=restore_reference,
            guard_evidence=guard_evidence,
        )

    def commit_schema_transition(
        self,
        exact_serialized: Mapping[str, bytes],
        *,
        transition_id: str,
        expected_config_sha256: Mapping[str, str] | None = None,
    ) -> ConfigurationTransactionResult:
        """Journal a reviewed representation-only schema adapter output."""

        transition_id = str(transition_id or "").strip()
        if not transition_id:
            raise ConfigurationValidationError("Schema transition ID is required.")
        proposed = {}
        before = _read_documents(self.paths)
        for filename, data in dict(exact_serialized).items():
            if filename not in CONFIG_FILENAMES or type(data) is not bytes:
                raise ConfigurationValidationError(
                    "Schema adapters may return only exact governed JSON bytes."
                )
            try:
                payload = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ConfigurationValidationError(
                    f"Schema adapter output is invalid JSON: {filename}: {exc}"
                ) from exc
            if semantic_json_sha256(payload) != semantic_json_sha256(before[filename]):
                raise ConfigurationValidationError(
                    f"Schema adapter changed safety semantics: {filename}"
                )
            proposed[filename] = payload
        if not proposed:
            raise ConfigurationValidationError("Schema adapter produced no governed files.")
        return self._commit_documents(
            proposed,
            operator="target_bootstrap_recovery",
            reason=f"Reviewed machine-data schema transition {transition_id}",
            workflow="machine_data_schema_transition",
            event_type="import",
            expected_config_sha256=expected_config_sha256,
            restore_reference=None,
            guard_evidence=None,
            exact_serialized=dict(exact_serialized),
        )

    def _commit_documents(
        self,
        proposed: Mapping[str, object],
        *,
        operator: str,
        reason: str,
        workflow: str,
        event_type: str,
        expected_config_sha256: Mapping[str, str] | None,
        restore_reference: str | None,
        guard_evidence: Mapping[str, object] | None,
        exact_serialized: Mapping[str, bytes] | None = None,
    ) -> ConfigurationTransactionResult:
        if event_type not in {"change", "import", "restore"}:
            raise ConfigurationValidationError("Invalid mutating event type.")
        exact_serialized = dict(exact_serialized or {})
        if exact_serialized and not (
            event_type == "restore"
            or (event_type == "import" and workflow == "machine_data_schema_transition")
        ):
            raise ConfigurationValidationError(
                "Exact serialized files are restricted to verified restore transactions."
            )
        if not set(exact_serialized).issubset(proposed):
            raise ConfigurationValidationError(
                "Every exact serialized file requires a matching proposed document."
            )
        reason = str(reason or "").strip()
        workflow = str(workflow or "").strip()
        if not reason or not workflow:
            raise ConfigurationValidationError("Workflow and reason are required.")
        actor = self._actor(operator)
        if not self._writer_mutex.acquire(blocking=False):
            raise ConfigurationConflictError("A configuration operation is already active.")
        try:
            self.configuration_lock.assert_owns(self.paths)
            current_state = self.refresh(allow_pending=False)
            before_documents = _read_documents(self.paths)
            before_hashes = _raw_config_hashes(self.paths)
            if expected_config_sha256 is not None and dict(expected_config_sha256) != before_hashes:
                raise ConfigurationConflictError("Configuration changed after the proposal was prepared.")
            complete = copy.deepcopy(before_documents)
            for filename, payload in proposed.items():
                if filename not in CONFIG_FILENAMES:
                    raise ConfigurationValidationError(f"Unsupported governed config: {filename}")
                complete[filename] = copy.deepcopy(payload)
            complete = _validate_documents(complete)
            active_guard = getattr(self, "configuration_safety_guard", None)
            if active_guard is not None:
                try:
                    active_guard.validate_active_documents(complete)
                except ConfigurationSafetyError as exc:
                    raise ConfigurationValidationError(
                        f"Configuration safety validation failed: {exc}"
                    ) from exc
            parsed_guard = None
            guarded_workflows = {
                "named_location_add",
                "named_location_modify",
                "rack_calibration",
                "plate_calibration",
            }
            guarded_coordinate_operation = workflow in guarded_workflows or (
                workflow in {"governed_configuration_import", "configuration_restore"}
                and bool(set(proposed).intersection({"Locations.json", "Plates.json"}))
            )
            if guard_evidence is not None:
                try:
                    parsed_guard = parse_guard_assessment(guard_evidence)
                except ConfigurationSafetyError as exc:
                    raise ConfigurationValidationError(
                        f"Guard evidence is invalid: {exc}"
                    ) from exc
                if parsed_guard["workflow"] != workflow:
                    raise ConfigurationValidationError(
                        "Guard evidence workflow differs from the transaction."
                    )
                if parsed_guard["result"] == "reject":
                    raise ConfigurationValidationError(
                        "A rejected guard assessment cannot authorize a commit."
                    )
                if parsed_guard["proposal_sha256"] != proposal_sha256(proposed):
                    raise ConfigurationConflictError(
                        "Guard evidence differs from the proposed documents."
                    )
                if dict(parsed_guard["governed_file_sha256"]) != before_hashes:
                    raise ConfigurationConflictError(
                        "Configuration changed after the guard preview was prepared."
                    )
                if active_guard is not None and (
                    parsed_guard["policy_id"] != active_guard.policy.policy_id
                    or parsed_guard["policy_sha256"] != active_guard.policy.raw_sha256
                ):
                    raise ConfigurationConflictError(
                        "The active configuration safety policy differs from the preview."
                    )
            elif guarded_coordinate_operation and bool(
                getattr(self, "require_configuration_guard_evidence", False)
            ):
                raise ConfigurationValidationError(
                    "This coordinate workflow requires configuration guard evidence."
                )
            if complete["Settings.json"].get("HARDWARE_PROFILE", "current") != before_documents["Settings.json"].get("HARDWARE_PROFILE", "current"):
                raise ConfigurationValidationError("HARDWARE_PROFILE cannot change while the application is active.")
            all_bytes = _canonical_config_bytes(complete)
            for filename, data in exact_serialized.items():
                if filename not in CONFIG_FILENAMES or type(data) is not bytes:
                    raise ConfigurationValidationError(
                        "Exact restore input must contain governed filenames and immutable bytes."
                    )
                try:
                    serialized_payload = json.loads(data.decode("utf-8"))
                    serialized_semantic_sha = semantic_json_sha256(serialized_payload)
                    validated_semantic_sha = semantic_json_sha256(complete[filename])
                except Exception as exc:
                    raise ConfigurationValidationError(
                        f"Exact restore bytes for {filename} are not valid JSON: {exc}"
                    ) from exc
                if serialized_semantic_sha != validated_semantic_sha:
                    raise ConfigurationValidationError(
                        f"Exact restore bytes for {filename} differ from the validated document."
                    )
                all_bytes[filename] = data
            semantically_affected = {
                name
                for name in CONFIG_FILENAMES
                if semantic_json_sha256(before_documents[name])
                != semantic_json_sha256(complete[name])
            }
            affected = [
                name for name in CONFIG_FILENAMES
                if (
                    name in semantically_affected
                    or (
                        name in exact_serialized
                        and before_hashes[name] != sha256_bytes(all_bytes[name])
                    )
                )
            ]
            if not affected:
                raise ConfigurationValidationError("The proposed configuration is unchanged.")
            after_hashes = dict(before_hashes)
            for filename in affected:
                after_hashes[filename] = sha256_bytes(all_bytes[filename])
            authorization, changes, changed_targets = _make_authorization_after(
                before_documents,
                complete,
                current_state.authorization,
                after_hashes,
                set(affected),
                semantically_affected,
            )
            transaction_id = str(self.uuid_factory())
            event_id = str(self.uuid_factory())
            _canonical_uuid(transaction_id, "transaction_id")
            _canonical_uuid(event_id, "event_id")
            now = _canonical_utc(self.clock(), "transaction time")
            sequence = current_state.sequence + 1
            event_relative = _event_relative(sequence, event_id)

            try:
                backup_reference = self._create_backup(
                    transaction_id=transaction_id,
                    filenames=affected,
                    before_documents=before_documents,
                    actor=actor,
                    workflow=workflow,
                    reason=reason,
                    created_at=now,
                )
            except ConfigurationTransactionError:
                raise
            except Exception as exc:
                raise ConfigurationTransactionError(
                    "The exact pre-change backup could not be prepared; active configuration was not changed."
                ) from exc
            event = {
                "schema_name": EVENT_SCHEMA_NAME,
                "schema_version": EVENT_SCHEMA_VERSION,
                "event_id": event_id,
                "sequence": sequence,
                "previous_event_sha256": current_state.latest_event_sha256,
                "transaction_id": transaction_id,
                "machine_id": self.identity.machine_id,
                "machine_uuid": self.identity.machine_uuid,
                "activation_id": self.active.activation_id,
                "baseline_verification_sha256": current_state.baseline_verification_sha256,
                "event_type": event_type,
                "outcome": "committed",
                "created_at_utc": now,
                "actor": actor,
                "application": {"version": self.app_version, "commit": self.app_commit},
                "workflow": workflow,
                "reason": reason,
                "config_before_sha256": before_hashes,
                "config_after_sha256": after_hashes,
                "changes": (
                    (changes or [{"affected_files": affected}])
                    + ([{"guard_assessment": parsed_guard}] if parsed_guard else [])
                ),
                "authorization_after": authorization,
                "backup_manifest": backup_reference,
                "restore_reference": restore_reference,
                "directory_sync_supported": bool(self.io.directory_fsync_supported),
            }
            parse_configuration_event(event)
            try:
                pending = self._prepare_pending(
                    transaction_id=transaction_id,
                    event=event,
                    event_relative=event_relative,
                    affected=affected,
                    before_hashes=before_hashes,
                    after_hashes=after_hashes,
                    backup_reference=backup_reference,
                    proposed_bytes=all_bytes,
                )
            except Exception as exc:
                self._remove_precommit_directory(
                    self.paths.pending_transactions_root, transaction_id
                )
                self._remove_precommit_directory(
                    self.paths.configuration_backups_root, transaction_id
                )
                if isinstance(exc, ConfigurationTransactionError):
                    raise
                raise ConfigurationTransactionError(
                    "Commit intent could not be prepared; active configuration was not changed."
                ) from exc
            replaced = False
            event_path = self.paths.machine_root / event_relative
            try:
                for filename in affected:
                    self.io.atomic_write_bytes(
                        _config_path(self.paths, filename),
                        all_bytes[filename],
                        checkpoint_prefix=f"configuration_{Path(filename).stem.lower()}",
                    )
                    replaced = True
                if _raw_config_hashes(self.paths) != after_hashes:
                    raise ConfigurationRecoveryRequired("Reopened config differs after transaction write.")
                self.io.create_bytes_exclusive(
                    event_path, _json_bytes(event), checkpoint_prefix="configuration_event"
                )
                event_sha = sha256_file(event_path)[0]
                created_at = now
                if self.paths.configuration_head_path.exists():
                    created_at = parse_configuration_head(
                        _read_json(self.paths.configuration_head_path, "configuration head")
                    )["created_at_utc"]
                head = _head_payload(
                    identity=self.identity,
                    active=self.active,
                    verification_sha=current_state.baseline_verification_sha256,
                    event=event,
                    event_relative=event_relative,
                    event_sha=event_sha,
                    created_at=created_at,
                    app_version=self.app_version,
                    app_commit=self.app_commit,
                )
                self.io.atomic_write_json(
                    self.paths.configuration_head_path,
                    head,
                    checkpoint_prefix="configuration_head",
                )
                self._remove_pending(pending)
            except Exception as exc:
                # Once an immutable event exists, keep the exact after-state so
                # startup can advance the head to that already-durable event.
                if replaced and not event_path.exists():
                    self._attempt_restore_from_backup(backup_reference, affected, before_hashes)
                raise ConfigurationRecoveryRequired(
                    "Configuration transaction did not complete; startup reconciliation is required."
                ) from exc
            new_state = self.refresh(allow_pending=False)
            documents = {name: copy.deepcopy(complete[name]) for name in affected}
            return ConfigurationTransactionResult(
                "committed", event_id, transaction_id, event_type, new_state,
                MappingProxyType(documents), changed_targets, "Configuration committed and audited."
            )
        finally:
            self._writer_mutex.release()

    def _create_backup(
        self,
        *,
        transaction_id: str,
        filenames: Sequence[str],
        before_documents: Mapping[str, object],
        actor: Mapping[str, str],
        workflow: str,
        reason: str,
        created_at: str,
    ) -> dict[str, str]:
        root = self.paths.configuration_backups_root / transaction_id
        root.mkdir(parents=True, exist_ok=False)
        try:
            entries = []
            fingerprints = []
            for filename in filenames:
                source = _config_path(self.paths, filename)
                data = source.read_bytes()
                relative = f"backups/configuration/{transaction_id}/before/config/{filename}"
                target = self.paths.machine_root / relative
                self.io.atomic_write_bytes(
                    target, data, checkpoint_prefix="configuration_backup_member"
                )
                digest = sha256_bytes(data)
                entry = {
                    "filename": filename,
                    "relative_path": relative,
                    "size": len(data),
                    "raw_sha256": digest,
                    "semantic_json_sha256": semantic_json_sha256(before_documents[filename]),
                }
                entries.append(entry)
                fingerprints.append(
                    {"relative_path": relative, "size": len(data), "raw_sha256": digest}
                )
            manifest = {
            "schema_name": BACKUP_SCHEMA_NAME,
            "schema_version": BACKUP_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "machine_id": self.identity.machine_id,
            "machine_uuid": self.identity.machine_uuid,
            "activation_id": self.active.activation_id,
            "created_at_utc": created_at,
            "actor": dict(actor),
            "workflow": workflow,
            "reason": reason,
            "files": entries,
            "evidence_fingerprint": sha256_bytes(
                canonical_json_bytes(sorted(fingerprints, key=lambda item: item["relative_path"]))
            ),
            "directory_sync_supported": bool(self.io.directory_fsync_supported),
            }
            manifest_path = root / "manifest.json"
            self.io.atomic_write_json(
                manifest_path, manifest, checkpoint_prefix="configuration_backup_manifest"
            )
            reference = {
                "relative_path": manifest_path.relative_to(self.paths.machine_root).as_posix(),
                "raw_sha256": sha256_file(manifest_path)[0],
            }
            _parse_backup_manifest(self.paths, reference)
            return reference
        except Exception:
            self._remove_precommit_directory(
                self.paths.configuration_backups_root, transaction_id
            )
            raise

    def _prepare_pending(
        self,
        *,
        transaction_id: str,
        event: Mapping[str, object],
        event_relative: str,
        affected: Sequence[str],
        before_hashes: Mapping[str, str],
        after_hashes: Mapping[str, str],
        backup_reference: Mapping[str, str] | None,
        proposed_bytes: Mapping[str, bytes],
    ) -> Path:
        root = self.paths.pending_transactions_root / transaction_id
        root.mkdir(parents=True, exist_ok=False)
        try:
            for filename in affected:
                self.io.atomic_write_bytes(
                    root / "proposed" / filename,
                    proposed_bytes[filename],
                    checkpoint_prefix="configuration_proposed",
                )
            journal = {
            "schema_name": JOURNAL_SCHEMA_NAME,
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "event_id": event["event_id"],
            "event_sequence": event["sequence"],
            "event_relative_path": event_relative,
            "machine_id": self.identity.machine_id,
            "machine_uuid": self.identity.machine_uuid,
            "activation_id": self.active.activation_id,
            "baseline_verification_sha256": event["baseline_verification_sha256"],
            "expected_previous_event_sha256": event["previous_event_sha256"],
            "event_type": event["event_type"],
            "created_at_utc": event["created_at_utc"],
            "affected_files": list(affected),
            "before_sha256": dict(before_hashes),
            "after_sha256": dict(after_hashes),
            "backup_manifest": copy.deepcopy(backup_reference),
            "planned_event": copy.deepcopy(event),
            "planned_event_sha256": sha256_bytes(_json_bytes(event)),
            "checkpoint": "commit_intent",
            "directory_sync_supported": bool(self.io.directory_fsync_supported),
            }
            self.io.atomic_write_json(
                root / "journal.json", journal, checkpoint_prefix="configuration_journal"
            )
            _parse_journal(self.paths)
            return root
        except Exception:
            self._remove_precommit_directory(
                self.paths.pending_transactions_root, transaction_id
            )
            raise

    def import_files(
        self,
        selected_files: Mapping[str, str | os.PathLike[str]],
        *,
        operator: str,
        reason: str,
    ) -> ConfigurationTransactionResult:
        """Import only explicitly named governed JSON files as one transaction."""

        if not selected_files:
            raise ConfigurationValidationError("At least one governed import file is required.")
        proposed: dict[str, object] = {}
        for filename, source_value in selected_files.items():
            if filename not in CONFIG_FILENAMES:
                raise ConfigurationValidationError(
                    f"Unsupported governed import target: {filename!r}"
                )
            source = Path(source_value).expanduser().resolve(strict=True)
            if not source.is_file() or _is_link_or_reparse(source):
                raise ConfigurationValidationError(
                    f"Import source must be a regular non-link file: {source}"
                )
            try:
                proposed[filename] = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ConfigurationValidationError(
                    f"Cannot read imported {filename}: {exc}"
                ) from exc
        return self.commit_documents(
            proposed,
            operator=operator,
            reason=reason,
            workflow="governed_configuration_import",
            event_type="import",
        )

    def _attempt_restore_from_backup(
        self,
        reference: Mapping[str, object],
        affected: Sequence[str],
        expected_hashes: Mapping[str, str],
    ) -> None:
        try:
            backup = _parse_backup_manifest(self.paths, reference)
            items = {item["filename"]: item for item in backup["files"]}
            for filename in affected:
                source = self.paths.machine_root / items[filename]["relative_path"]
                self.io.atomic_write_bytes(
                    _config_path(self.paths, filename),
                    source.read_bytes(),
                    checkpoint_prefix="configuration_live_rollback",
                )
            if _raw_config_hashes(self.paths) != dict(expected_hashes):
                raise ConfigurationRecoveryRequired("Live rollback hash differs.")
        except Exception as exc:
            raise ConfigurationRecoveryRequired(
                "Configuration changed but exact live rollback could not be proven."
            ) from exc

    def record_attempt(
        self,
        *,
        event_type: str,
        operator: str,
        reason: str,
        workflow: str,
        details: Mapping[str, object] | None = None,
    ) -> ConfigurationTransactionResult:
        if event_type not in {"cancelled", "rejected"}:
            raise ConfigurationValidationError("Attempt event must be cancelled or rejected.")
        return self._record_nonmutating(
            event_type=event_type,
            outcome=event_type,
            operator=operator,
            reason=reason,
            workflow=workflow,
            changes=[copy.deepcopy(dict(details or {}))],
            authorization_after=None,
        )

    def verify_targets(
        self,
        target_confirmations: Mapping[str, object],
        *,
        operator: str,
        reason: str,
        workflow: str = "configuration_target_verification",
        method: str = "physical_check",
        service_record_reference: str | None = None,
    ) -> ConfigurationTransactionResult:
        method = str(method or "").strip()
        if method not in {"physical_check", "independent_service_record"}:
            raise ConfigurationValidationError("Verification method is unsupported.")
        if method == "independent_service_record" and not str(
            service_record_reference or ""
        ).strip():
            raise ConfigurationValidationError(
                "Independent service-record verification requires its reference."
            )
        state = self.refresh(allow_pending=False)
        documents = _read_documents(self.paths)
        snapshot = build_target_snapshot_from_documents(
            documents["Locations.json"], documents["Plates.json"], documents["Settings.json"]
        )
        if not target_confirmations:
            raise ConfigurationValidationError("At least one target confirmation is required.")
        updated = {key: copy.deepcopy(dict(value)) for key, value in state.authorization.items()}
        changes = []
        now = _canonical_utc(self.clock(), "verification time")
        for key, confirmed in target_confirmations.items():
            if key not in snapshot or key not in updated:
                raise ConfigurationValidationError(f"Unknown current target: {key}")
            value = snapshot[key][2]
            if canonical_value_sha256(confirmed) != canonical_value_sha256(value):
                raise ConfigurationValidationError(f"Confirmation differs for {key}.")
            prior = updated[key]["state"]
            updated[key]["state"] = "operator_verified"
            updated[key]["verified_at_utc"] = now
            updated[key]["verified_by"] = str(operator or "").strip()
            updated[key]["verification_method"] = method
            updated[key]["evidence_reference"] = "current verification event"
            updated[key]["service_record_reference"] = (
                str(service_record_reference).strip() if service_record_reference else None
            )
            changes.append(
                {"target_key": key, "before_state": prior, "after_state": "operator_verified", "value": copy.deepcopy(value)}
            )
        return self._record_nonmutating(
            event_type="verification",
            outcome="verified",
            operator=operator,
            reason=reason,
            workflow=workflow,
            changes=changes,
            authorization_after=updated,
        )

    def _record_nonmutating(
        self,
        *,
        event_type: str,
        outcome: str,
        operator: str,
        reason: str,
        workflow: str,
        changes: list[object],
        authorization_after: Mapping[str, Mapping[str, object]] | None,
    ) -> ConfigurationTransactionResult:
        reason = str(reason or "").strip()
        workflow = str(workflow or "").strip()
        if not reason or not workflow:
            raise ConfigurationValidationError("Workflow and reason are required.")
        actor = self._actor(operator)
        if not self._writer_mutex.acquire(blocking=False):
            raise ConfigurationConflictError("A configuration operation is already active.")
        try:
            state = self.refresh(allow_pending=False)
            transaction_id = str(self.uuid_factory())
            event_id = str(self.uuid_factory())
            now = _canonical_utc(self.clock(), "event time")
            sequence = state.sequence + 1
            event_relative = _event_relative(sequence, event_id)
            authorization = (
                {key: copy.deepcopy(dict(value)) for key, value in authorization_after.items()}
                if authorization_after is not None
                else {key: copy.deepcopy(dict(value)) for key, value in state.authorization.items()}
            )
            event = {
                "schema_name": EVENT_SCHEMA_NAME,
                "schema_version": EVENT_SCHEMA_VERSION,
                "event_id": event_id,
                "sequence": sequence,
                "previous_event_sha256": state.latest_event_sha256,
                "transaction_id": transaction_id,
                "machine_id": self.identity.machine_id,
                "machine_uuid": self.identity.machine_uuid,
                "activation_id": self.active.activation_id,
                "baseline_verification_sha256": state.baseline_verification_sha256,
                "event_type": event_type,
                "outcome": outcome,
                "created_at_utc": now,
                "actor": actor,
                "application": {"version": self.app_version, "commit": self.app_commit},
                "workflow": workflow,
                "reason": reason,
                "config_before_sha256": dict(state.config_sha256),
                "config_after_sha256": dict(state.config_sha256),
                "changes": changes,
                "authorization_after": authorization,
                "backup_manifest": None,
                "restore_reference": None,
                "directory_sync_supported": bool(self.io.directory_fsync_supported),
            }
            parse_configuration_event(event)
            try:
                pending = self._prepare_pending(
                    transaction_id=transaction_id,
                    event=event,
                    event_relative=event_relative,
                    affected=[],
                    before_hashes=state.config_sha256,
                    after_hashes=state.config_sha256,
                    backup_reference=None,
                    proposed_bytes={},
                )
            except ConfigurationTransactionError:
                raise
            except Exception as exc:
                raise ConfigurationTransactionError(
                    "Audit commit intent could not be prepared; no event was recorded."
                ) from exc
            try:
                event_path = self.paths.machine_root / event_relative
                self.io.create_bytes_exclusive(
                    event_path, _json_bytes(event), checkpoint_prefix="configuration_event"
                )
                event_sha = sha256_file(event_path)[0]
                created_at = now
                if self.paths.configuration_head_path.exists():
                    created_at = parse_configuration_head(
                        _read_json(self.paths.configuration_head_path, "configuration head")
                    )["created_at_utc"]
                head = _head_payload(
                    identity=self.identity,
                    active=self.active,
                    verification_sha=state.baseline_verification_sha256,
                    event=event,
                    event_relative=event_relative,
                    event_sha=event_sha,
                    created_at=created_at,
                    app_version=self.app_version,
                    app_commit=self.app_commit,
                )
                self.io.atomic_write_json(
                    self.paths.configuration_head_path, head, checkpoint_prefix="configuration_head"
                )
                self._remove_pending(pending)
            except Exception as exc:
                raise ConfigurationRecoveryRequired(
                    "Audit event did not complete; startup reconciliation is required."
                ) from exc
            new_state = self.refresh(allow_pending=False)
            return ConfigurationTransactionResult(
                "recorded", event_id, transaction_id, event_type, new_state,
                MappingProxyType({}), tuple(), "Configuration event recorded."
            )
        finally:
            self._writer_mutex.release()

    def _restore_inputs(self, transaction_id: str):
        transaction_id = _canonical_uuid(transaction_id, "restore transaction_id")
        self.refresh(allow_pending=False)
        source_events = []
        for event_path in _all_files(self.paths.configuration_events_root):
            event = parse_configuration_event(
                _read_json(event_path, "configuration restore source event")
            )
            if event["transaction_id"] == transaction_id:
                source_events.append(event)
        if len(source_events) != 1:
            raise ConfigurationValidationError(
                "The requested configuration backup has no unique immutable source event."
            )
        reference = source_events[0].get("backup_manifest")
        if reference is None:
            raise ConfigurationValidationError(
                "The requested configuration event has no restorable backup."
            )
        manifest = _parse_backup_manifest(self.paths, reference)
        if (
            manifest["machine_id"] != self.identity.machine_id
            or manifest["machine_uuid"] != self.identity.machine_uuid
            or manifest["activation_id"] != self.active.activation_id
        ):
            raise ConfigurationRecoveryRequired(
                "Configuration backup identity differs from the active machine."
            )
        proposed = {}
        exact_serialized = {}
        for item in manifest["files"]:
            path = self.paths.machine_root / item["relative_path"]
            try:
                data = path.read_bytes()
                if len(data) != item["size"] or sha256_bytes(data) != item["raw_sha256"]:
                    raise ConfigurationRecoveryRequired(
                        "Configuration backup member changed after manifest verification."
                    )
                payload = json.loads(data.decode("utf-8"))
                if semantic_json_sha256(payload) != item["semantic_json_sha256"]:
                    raise ConfigurationRecoveryRequired(
                        "Configuration backup member semantic hash changed after verification."
                    )
            except ConfigurationRecoveryRequired:
                raise
            except Exception as exc:
                raise ConfigurationRecoveryRequired(
                    f"Configuration backup member cannot be reopened: {item['filename']}: {exc}"
                ) from exc
            proposed[item["filename"]] = payload
            exact_serialized[item["filename"]] = data
        restore_precondition = {
            "schema_name": RESTORE_PRECONDITION_SCHEMA_NAME,
            "schema_version": RESTORE_PRECONDITION_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "machine_id": manifest["machine_id"],
            "machine_uuid": manifest["machine_uuid"],
            "activation_id": manifest["activation_id"],
            "backup_manifest": copy.deepcopy(reference),
            "evidence_fingerprint": manifest["evidence_fingerprint"],
            "files": [
                {
                    "filename": item["filename"],
                    "size": item["size"],
                    "raw_sha256": item["raw_sha256"],
                    "semantic_json_sha256": item["semantic_json_sha256"],
                }
                for item in sorted(manifest["files"], key=lambda value: value["filename"])
            ],
        }
        parse_restore_guard_precondition(restore_precondition)
        return proposed, exact_serialized, restore_precondition

    def read_restore_proposal(self, transaction_id: str) -> dict[str, object]:
        proposed, _exact, _precondition = self._restore_inputs(transaction_id)
        return copy.deepcopy(proposed)

    def read_restore_preview(
        self, transaction_id: str
    ) -> tuple[dict[str, object], dict[str, object]]:
        proposed, _exact, precondition = self._restore_inputs(transaction_id)
        return copy.deepcopy(proposed), copy.deepcopy(precondition)

    def restore_transaction(
        self,
        transaction_id: str,
        *,
        operator: str,
        reason: str,
        machine_id_confirmation: str,
        expected_config_sha256: Mapping[str, str] | None = None,
        guard_evidence: Mapping[str, object] | None = None,
    ) -> ConfigurationTransactionResult:
        transaction_id = _canonical_uuid(transaction_id, "restore transaction_id")
        if machine_id_confirmation != self.identity.machine_id:
            raise ConfigurationValidationError("Exact machine ID confirmation is required.")
        proposed, exact_serialized, restore_precondition = self._restore_inputs(transaction_id)
        if guard_evidence is not None:
            try:
                parsed_guard = parse_guard_assessment(guard_evidence)
                preview_precondition = parse_restore_guard_precondition(
                    parsed_guard["preconditions"].get("restore")
                )
            except ConfigurationSafetyError as exc:
                raise ConfigurationValidationError(
                    f"Restore guard evidence is invalid: {exc}"
                ) from exc
            if preview_precondition != restore_precondition:
                raise ConfigurationConflictError(
                    "The selected backup differs from the verified restore preview."
                )
        return self._commit_documents(
            proposed,
            operator=operator,
            reason=reason,
            workflow="configuration_restore",
            event_type="restore",
            expected_config_sha256=expected_config_sha256,
            restore_reference=transaction_id,
            guard_evidence=guard_evidence,
            exact_serialized=exact_serialized,
        )


__all__ = [
    "BACKUP_SCHEMA_NAME",
    "ConfigurationConflictError",
    "ConfigurationRecoveryRequired",
    "ConfigurationState",
    "ConfigurationTransactionError",
    "ConfigurationTransactionResult",
    "ConfigurationTransactionService",
    "ConfigurationValidationError",
    "EVENT_SCHEMA_NAME",
    "HEAD_SCHEMA_NAME",
    "JOURNAL_SCHEMA_NAME",
    "TransactionalSavedTargetAuthorizer",
    "build_active_tree_overrides",
    "inspect_configuration_state",
    "parse_configuration_event",
    "parse_configuration_head",
    "read_governed_documents",
]
