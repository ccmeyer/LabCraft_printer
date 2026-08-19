"""Pure verification, activation, and saved-target authorization contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping
from uuid import UUID

import LocalConfig
from MachineData import MachineDataPaths, MachineIdentity
from MachineDataArchive import (
    DurableFileOps,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from MachineDataMigration import MigrationReceipt, PublishedMigrationEvidence
from MachineDataOwnership import OwnershipClassification, OwnershipDecision


VERIFICATION_SCHEMA_NAME = "labcraft.machine_verification"
VERIFICATION_SCHEMA_VERSION = 1
VERIFICATION_POLICY_NAME = "labcraft.initial_target_verification"
VERIFICATION_POLICY_VERSION = 1
ACTIVATION_RECEIPT_SCHEMA_NAME = "labcraft.activation_receipt"
ACTIVATION_RECEIPT_SCHEMA_VERSION = 1
ACTIVATION_RECEIPT_STATE = "ready_for_activation"
PLATE_CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")
VERIFIED_STATES = frozenset(
    {
        "verified_from_trusted_existing_calibration",
        "verified_against_service_record",
        "verified_by_controlled_calibration",
    }
)


class VerificationError(ValueError):
    """Raised when machine verification evidence is incomplete or inconsistent."""


class VerificationState(str, Enum):
    UNVERIFIED = "unverified"
    TRUSTED_EXISTING = "verified_from_trusted_existing_calibration"
    SERVICE_RECORD = "verified_against_service_record"
    CONTROLLED_CALIBRATION = "verified_by_controlled_calibration"
    REVOKED = "revoked"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _canonical_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise VerificationError(f"{label} must be UUID text.")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise VerificationError(f"{label} is not a UUID.") from exc


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_utc(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise VerificationError(f"{label} must be a UTC timestamp.")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise VerificationError(f"{label} is not a timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise VerificationError(f"{label} must identify UTC.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_value_sha256(value: object) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _coordinate(value: object, label: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"X", "Y", "Z"}:
        raise VerificationError(f"{label} must contain exactly X/Y/Z.")
    result: dict[str, int] = {}
    for axis in ("X", "Y", "Z"):
        raw = value.get(axis)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise VerificationError(f"{label}.{axis} must be numeric.")
        integer = int(raw)
        if integer != raw:
            raise VerificationError(f"{label}.{axis} must be an integer step value.")
        result[axis] = integer
    return result


def _read_json(path: Path, expected_type: type, label: str):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"Cannot read {label}: {exc}") from exc
    if not isinstance(payload, expected_type):
        raise VerificationError(f"{label} has the wrong top-level type.")
    return payload


@dataclass(frozen=True)
class SourceVerification:
    state: str
    verified_at_utc: str
    verified_by: str
    machine_id_confirmation: str
    reason: str

    def to_payload(self) -> dict[str, object]:
        return {
            "state": self.state,
            "verified_at_utc": self.verified_at_utc,
            "verified_by": self.verified_by,
            "machine_id_confirmation": self.machine_id_confirmation,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TargetVerification:
    target_key: str
    display_name: str
    kind: str
    state: VerificationState
    value: Mapping[str, object]
    value_sha256: str
    source_file: str
    source_file_sha256: str
    verified_at_utc: str
    verified_by: str
    preset_match: bool
    service_record_reference: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "display_name": self.display_name,
            "kind": self.kind,
            "state": self.state.value,
            "value": dict(self.value),
            "value_sha256": self.value_sha256,
            "source_file": self.source_file,
            "source_file_sha256": self.source_file_sha256,
            "verified_at_utc": self.verified_at_utc,
            "verified_by": self.verified_by,
            "preset_match": self.preset_match,
            "service_record_reference": self.service_record_reference,
        }


@dataclass(frozen=True)
class MachineVerification:
    machine_id: str
    machine_uuid: str
    migration_id: str
    migration_receipt_sha256: str
    required_config_fingerprint: str
    source_verification: SourceVerification
    config_file_sha256: Mapping[str, str]
    targets: Mapping[str, TargetVerification]
    ownership_decisions: tuple[OwnershipDecision, ...]
    activation_ready: bool
    created_at_utc: str
    app_version: str
    app_commit: str

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_name": VERIFICATION_SCHEMA_NAME,
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "policy_name": VERIFICATION_POLICY_NAME,
            "policy_version": VERIFICATION_POLICY_VERSION,
            "machine_id": self.machine_id,
            "machine_uuid": self.machine_uuid,
            "migration_id": self.migration_id,
            "migration_receipt_sha256": self.migration_receipt_sha256,
            "required_config_fingerprint": self.required_config_fingerprint,
            "source_verification": self.source_verification.to_payload(),
            "config_file_sha256": dict(self.config_file_sha256),
            "targets": {
                key: target.to_payload() for key, target in sorted(self.targets.items())
            },
            "ownership_decisions": [item.to_payload() for item in self.ownership_decisions],
            "activation_ready": self.activation_ready,
            "created_at_utc": self.created_at_utc,
            "app_version": self.app_version,
            "app_commit": self.app_commit,
        }


@dataclass(frozen=True)
class ActivationReceipt:
    activation_id: str
    migration_id: str
    machine_id: str
    machine_uuid: str
    migration_receipt_sha256: str
    migration_tree_manifest_sha256: str
    verification_sha256: str
    backup_archive_sha256: str
    ownership_policy_version: int
    directory_sync_supported: bool
    created_at_utc: str
    app_version: str
    app_commit: str
    state: str = ACTIVATION_RECEIPT_STATE

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_name": ACTIVATION_RECEIPT_SCHEMA_NAME,
            "schema_version": ACTIVATION_RECEIPT_SCHEMA_VERSION,
            "state": self.state,
            "activation_id": self.activation_id,
            "migration_id": self.migration_id,
            "machine_id": self.machine_id,
            "machine_uuid": self.machine_uuid,
            "migration_receipt_sha256": self.migration_receipt_sha256,
            "migration_tree_manifest_sha256": self.migration_tree_manifest_sha256,
            "verification_sha256": self.verification_sha256,
            "backup_archive_sha256": self.backup_archive_sha256,
            "ownership_policy_version": self.ownership_policy_version,
            "directory_sync_supported": self.directory_sync_supported,
            "created_at_utc": self.created_at_utc,
            "app_version": self.app_version,
            "app_commit": self.app_commit,
        }


def _parse_source_verification(payload: object) -> SourceVerification:
    if not isinstance(payload, dict) or payload.get("state") != "verified":
        raise VerificationError("Source verification is incomplete.")
    text_fields = ("verified_by", "machine_id_confirmation", "reason")
    if not all(isinstance(payload.get(name), str) and payload.get(name).strip() for name in text_fields):
        raise VerificationError("Source verification text fields are required.")
    return SourceVerification(
        state="verified",
        verified_at_utc=_canonical_utc(payload.get("verified_at_utc"), "source verified_at_utc"),
        verified_by=payload["verified_by"].strip(),
        machine_id_confirmation=payload["machine_id_confirmation"].strip(),
        reason=payload["reason"].strip(),
    )


def _parse_target(key: str, payload: object) -> TargetVerification:
    if not isinstance(payload, dict):
        raise VerificationError(f"Target {key} must be an object.")
    try:
        state = VerificationState(payload.get("state"))
    except ValueError as exc:
        raise VerificationError(f"Target {key} state is invalid.") from exc
    display_name = payload.get("display_name")
    kind = payload.get("kind")
    source_file = payload.get("source_file")
    verified_by = payload.get("verified_by")
    value = payload.get("value")
    if not all(isinstance(item, str) and item for item in (display_name, kind, source_file, verified_by)):
        raise VerificationError(f"Target {key} text fields are invalid.")
    if not isinstance(value, dict):
        raise VerificationError(f"Target {key} value must be an object.")
    if not _is_sha256(payload.get("value_sha256")) or canonical_value_sha256(value) != payload.get("value_sha256"):
        raise VerificationError(f"Target {key} value hash is invalid.")
    if not _is_sha256(payload.get("source_file_sha256")):
        raise VerificationError(f"Target {key} source hash is invalid.")
    preset_match = payload.get("preset_match")
    if type(preset_match) is not bool:
        raise VerificationError(f"Target {key} preset flag is invalid.")
    service_reference = payload.get("service_record_reference")
    if service_reference is not None and not isinstance(service_reference, str):
        raise VerificationError(f"Target {key} service reference is invalid.")
    if state is VerificationState.SERVICE_RECORD and not str(service_reference or "").strip():
        raise VerificationError(f"Target {key} requires a service record reference.")
    return TargetVerification(
        target_key=key,
        display_name=display_name,
        kind=kind,
        state=state,
        value=MappingProxyType(dict(value)),
        value_sha256=payload["value_sha256"],
        source_file=source_file,
        source_file_sha256=payload["source_file_sha256"],
        verified_at_utc=_canonical_utc(payload.get("verified_at_utc"), f"{key} verified_at_utc"),
        verified_by=verified_by,
        preset_match=preset_match,
        service_record_reference=service_reference,
    )


def parse_machine_verification(payload: object) -> MachineVerification:
    if not isinstance(payload, dict):
        raise VerificationError("Machine verification must be an object.")
    expected = {
        "schema_name": VERIFICATION_SCHEMA_NAME,
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "policy_name": VERIFICATION_POLICY_NAME,
        "policy_version": VERIFICATION_POLICY_VERSION,
    }
    if any(payload.get(name) != value for name, value in expected.items()):
        raise VerificationError("Unknown machine verification schema/policy.")
    machine_id = payload.get("machine_id")
    if not isinstance(machine_id, str) or not machine_id.strip():
        raise VerificationError("Verification machine_id is required.")
    machine_uuid = _canonical_uuid(payload.get("machine_uuid"), "machine_uuid")
    migration_id = _canonical_uuid(payload.get("migration_id"), "migration_id")
    if not _is_sha256(payload.get("migration_receipt_sha256")) or not _is_sha256(
        payload.get("required_config_fingerprint")
    ):
        raise VerificationError("Verification migration hashes are invalid.")
    source = _parse_source_verification(payload.get("source_verification"))
    if source.machine_id_confirmation != machine_id:
        raise VerificationError("Source confirmation does not match machine ID.")
    config_hashes = payload.get("config_file_sha256")
    if not isinstance(config_hashes, dict) or set(config_hashes) != set(
        LocalConfig.machine_config_top_level_types()
    ) or not all(_is_sha256(value) for value in config_hashes.values()):
        raise VerificationError("Verification config hash inventory is incomplete.")
    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, dict) or not raw_targets:
        raise VerificationError("Verification targets are required.")
    folded = [str(key).casefold() for key in raw_targets]
    if len(folded) != len(set(folded)):
        raise VerificationError("Verification target keys collide by case.")
    targets = {key: _parse_target(key, value) for key, value in raw_targets.items()}
    if any(target.state.value not in VERIFIED_STATES for target in targets.values()):
        raise VerificationError("Every activation target must have a verified state.")
    ownership_raw = payload.get("ownership_decisions")
    if not isinstance(ownership_raw, list):
        raise VerificationError("Ownership decisions must be a list.")
    # Ownership decisions are re-evaluated by bootstrap. Parse their persisted
    # representation strictly without treating it as policy authority.
    ownership_items = []
    for item in ownership_raw:
        if not isinstance(item, dict):
            raise VerificationError("Ownership decision payload is invalid.")
        relative_path = item.get("relative_path")
        reason = item.get("reason")
        rule_id = item.get("rule_id")
        destination = item.get("canonical_destination")
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or not isinstance(reason, str)
            or not reason
            or (rule_id is not None and not isinstance(rule_id, str))
            or (destination is not None and not isinstance(destination, str))
        ):
            raise VerificationError("Ownership decision fields are invalid.")
        try:
            classification = OwnershipClassification(item.get("classification"))
        except ValueError as exc:
            raise VerificationError("Ownership decision classification is invalid.") from exc
        ownership_items.append(
            OwnershipDecision(
                relative_path=relative_path,
                classification=classification,
                rule_id=rule_id,
                reason=reason,
                canonical_destination=destination,
            )
        )
    ownership = tuple(ownership_items)
    if payload.get("activation_ready") is not True:
        raise VerificationError("Verification is not activation ready.")
    app_version = payload.get("app_version")
    app_commit = payload.get("app_commit")
    if not isinstance(app_version, str) or not app_version or not isinstance(app_commit, str) or not app_commit:
        raise VerificationError("Verification app provenance is required.")
    return MachineVerification(
        machine_id=machine_id,
        machine_uuid=machine_uuid,
        migration_id=migration_id,
        migration_receipt_sha256=payload["migration_receipt_sha256"],
        required_config_fingerprint=payload["required_config_fingerprint"],
        source_verification=source,
        config_file_sha256=MappingProxyType(dict(config_hashes)),
        targets=MappingProxyType(targets),
        ownership_decisions=ownership,
        activation_ready=True,
        created_at_utc=_canonical_utc(payload.get("created_at_utc"), "created_at_utc"),
        app_version=app_version,
        app_commit=app_commit,
    )


def load_machine_verification(path: str | Path) -> MachineVerification:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"Cannot read machine verification: {exc}") from exc
    return parse_machine_verification(payload)


def parse_activation_receipt(payload: object) -> ActivationReceipt:
    if not isinstance(payload, dict):
        raise VerificationError("Activation receipt must be an object.")
    if (
        payload.get("schema_name") != ACTIVATION_RECEIPT_SCHEMA_NAME
        or payload.get("schema_version") != ACTIVATION_RECEIPT_SCHEMA_VERSION
        or payload.get("state") != ACTIVATION_RECEIPT_STATE
    ):
        raise VerificationError("Unknown activation receipt schema/state.")
    hashes = (
        "migration_receipt_sha256",
        "migration_tree_manifest_sha256",
        "verification_sha256",
        "backup_archive_sha256",
    )
    if not all(_is_sha256(payload.get(name)) for name in hashes):
        raise VerificationError("Activation receipt hashes are invalid.")
    machine_id = payload.get("machine_id")
    app_version = payload.get("app_version")
    app_commit = payload.get("app_commit")
    if not all(isinstance(item, str) and item for item in (machine_id, app_version, app_commit)):
        raise VerificationError("Activation receipt text fields are missing.")
    policy_version = payload.get("ownership_policy_version")
    directory_sync = payload.get("directory_sync_supported")
    if type(policy_version) is not int or policy_version < 1 or type(directory_sync) is not bool:
        raise VerificationError("Activation receipt policy/durability fields are invalid.")
    return ActivationReceipt(
        activation_id=_canonical_uuid(payload.get("activation_id"), "activation_id"),
        migration_id=_canonical_uuid(payload.get("migration_id"), "migration_id"),
        machine_id=machine_id,
        machine_uuid=_canonical_uuid(payload.get("machine_uuid"), "machine_uuid"),
        migration_receipt_sha256=payload["migration_receipt_sha256"],
        migration_tree_manifest_sha256=payload["migration_tree_manifest_sha256"],
        verification_sha256=payload["verification_sha256"],
        backup_archive_sha256=payload["backup_archive_sha256"],
        ownership_policy_version=policy_version,
        directory_sync_supported=directory_sync,
        created_at_utc=_canonical_utc(payload.get("created_at_utc"), "activation created_at_utc"),
        app_version=app_version,
        app_commit=app_commit,
    )


def load_activation_receipt(path: str | Path) -> ActivationReceipt:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"Cannot read activation receipt: {exc}") from exc
    return parse_activation_receipt(payload)


def _config_hashes(paths: MachineDataPaths) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for filename in LocalConfig.machine_config_top_level_types():
        path = paths.config_root / filename
        LocalConfig.validate_machine_config_file(path, filename)
        hashes[filename] = sha256_file(path)[0]
    return hashes


def build_target_snapshot(paths: MachineDataPaths) -> dict[str, tuple[str, str, object]]:
    """Return target_key -> (kind, source file, canonical value)."""

    locations = _read_json(paths.config_root / "Locations.json", dict, "Locations.json")
    plates = _read_json(paths.config_root / "Plates.json", list, "Plates.json")
    settings = _read_json(paths.config_root / "Settings.json", dict, "Settings.json")
    targets: dict[str, tuple[str, str, object]] = {}
    location_names: set[str] = set()
    for display_name, raw in locations.items():
        if not isinstance(display_name, str) or not display_name.strip():
            raise VerificationError("Location names must be nonempty text.")
        folded = display_name.casefold()
        if folded in location_names:
            raise VerificationError("Location names collide by case.")
        location_names.add(folded)
        targets[f"location:{folded}"] = (
            "location",
            "config/Locations.json",
            _coordinate(raw, f"location {display_name}"),
        )
    left = locations.get("rack_position_Left")
    right = locations.get("rack_position_Right")
    if left is None or right is None:
        raise VerificationError("Both rack anchors are required.")
    targets["rack:primary"] = (
        "rack",
        "config/Locations.json",
        {
            "Left": _coordinate(left, "rack Left"),
            "Right": _coordinate(right, "rack Right"),
        },
    )
    default_plate = settings.get("DEFAULT_PLATE")
    found_default = False
    plate_names: set[str] = set()
    for plate in plates:
        if not isinstance(plate, dict) or not isinstance(plate.get("name"), str):
            raise VerificationError("Plate entries require a name.")
        display_name = plate["name"].strip()
        folded = display_name.casefold()
        if not display_name or folded in plate_names:
            raise VerificationError("Plate names must be unique nonempty text.")
        plate_names.add(folded)
        calibrations = plate.get("calibrations") or {}
        if not isinstance(calibrations, dict):
            raise VerificationError(f"Plate {display_name} calibrations must be an object.")
        is_default = display_name == default_plate
        found_default = found_default or is_default
        if not calibrations:
            if is_default:
                raise VerificationError("The default plate requires calibration.")
            continue
        if set(calibrations) != set(PLATE_CORNERS):
            raise VerificationError(f"Plate {display_name} calibration is incomplete.")
        targets[f"plate:{folded}"] = (
            "plate",
            "config/Plates.json",
            {
                corner: _coordinate(calibrations[corner], f"plate {display_name} {corner}")
                for corner in PLATE_CORNERS
            },
        )
    if not found_default:
        raise VerificationError("Settings DEFAULT_PLATE does not identify a plate.")
    return targets


def create_machine_verification(
    *,
    paths: MachineDataPaths,
    identity: MachineIdentity,
    published: PublishedMigrationEvidence,
    ownership_decisions: tuple[OwnershipDecision, ...],
    operator: str,
    machine_id_confirmation: str,
    source_reason: str,
    camera_confirmation: Mapping[str, object],
    service_record_reference: str | None,
    app_version: str,
    app_commit: str,
    clock: Callable[[], str] = utc_now,
) -> MachineVerification:
    if identity.machine_uuid != paths.machine_uuid or identity.machine_uuid != published.receipt.machine_uuid:
        raise VerificationError("Verification identity/paths/migration UUIDs differ.")
    if identity.machine_id != published.receipt.machine_id:
        raise VerificationError("Verification identity differs from migration receipt.")
    operator = str(operator or "").strip()
    source_reason = str(source_reason or "").strip()
    if not operator or machine_id_confirmation != identity.machine_id or not source_reason:
        raise VerificationError("Exact machine ID, operator, and source reason are required.")
    if any(not decision.activation_allowed for decision in ownership_decisions):
        raise VerificationError("Unresolved/prohibited source paths block activation.")
    if published.candidate.calibration_memory_status != "present_complete":
        raise VerificationError("A complete migrated CalibrationMemory baseline is required.")
    config_hashes = _config_hashes(paths)
    target_snapshot = build_target_snapshot(paths)
    camera_value = target_snapshot.get("location:camera")
    settings = _read_json(paths.config_root / "Settings.json", dict, "Settings.json")
    if settings.get("HARDWARE_PROFILE", "current") != "legacy" and camera_value is None:
        raise VerificationError("The current hardware profile requires Camera.")
    if camera_value is not None and _coordinate(camera_confirmation, "Camera confirmation") != camera_value[2]:
        raise VerificationError("Camera confirmation does not match the copied Camera value.")

    now = _canonical_utc(clock(), "verification time")
    strong_service_evidence = bool(str(service_record_reference or "").strip())
    requires_service_for_all = published.receipt.preset_like
    if (published.receipt.camera_preset_match or requires_service_for_all) and not strong_service_evidence:
        raise VerificationError("Preset-matching calibration requires independent service evidence.")
    targets: dict[str, TargetVerification] = {}
    for key, (kind, source_file, value) in target_snapshot.items():
        is_camera = key == "location:camera"
        preset_match = requires_service_for_all or (
            is_camera and published.receipt.camera_preset_match
        )
        state = (
            VerificationState.SERVICE_RECORD
            if preset_match
            else VerificationState.TRUSTED_EXISTING
        )
        display_name = key.split(":", 1)[1] if ":" in key else key
        targets[key] = TargetVerification(
            target_key=key,
            display_name=display_name,
            kind=kind,
            state=state,
            value=MappingProxyType(dict(value)),
            value_sha256=canonical_value_sha256(value),
            source_file=source_file,
            source_file_sha256=config_hashes[Path(source_file).name],
            verified_at_utc=now,
            verified_by=operator,
            preset_match=preset_match,
            service_record_reference=(
                str(service_record_reference).strip() if state is VerificationState.SERVICE_RECORD else None
            ),
        )
    receipt_sha = sha256_file(paths.migration_receipt_path)[0]
    return MachineVerification(
        machine_id=identity.machine_id,
        machine_uuid=identity.machine_uuid,
        migration_id=published.receipt.migration_id,
        migration_receipt_sha256=receipt_sha,
        required_config_fingerprint=published.receipt.required_config_fingerprint,
        source_verification=SourceVerification(
            "verified", now, operator, machine_id_confirmation, source_reason
        ),
        config_file_sha256=MappingProxyType(config_hashes),
        targets=MappingProxyType(targets),
        ownership_decisions=ownership_decisions,
        activation_ready=True,
        created_at_utc=now,
        app_version=app_version,
        app_commit=app_commit,
    )


def write_machine_verification(
    paths: MachineDataPaths,
    verification: MachineVerification,
    *,
    io: DurableFileOps | None = None,
) -> tuple[str, bool]:
    operations = io or DurableFileOps()
    directory_synced = operations.atomic_write_json(
        paths.verification_path,
        verification.to_payload(),
        checkpoint_prefix="verification",
    )
    reopened = load_machine_verification(paths.verification_path)
    if reopened != verification:
        raise VerificationError("Reopened verification differs from memory.")
    return sha256_file(paths.verification_path)[0], directory_synced


def write_activation_receipt(
    paths: MachineDataPaths,
    receipt: ActivationReceipt,
    *,
    io: DurableFileOps | None = None,
) -> str:
    operations = io or DurableFileOps()
    operations.atomic_write_json(
        paths.activation_receipt_path,
        receipt.to_payload(),
        checkpoint_prefix="activation_receipt",
    )
    reopened = load_activation_receipt(paths.activation_receipt_path)
    if reopened != receipt:
        raise VerificationError("Reopened activation receipt differs from memory.")
    return sha256_file(paths.activation_receipt_path)[0]


def validate_verification_against_files(
    paths: MachineDataPaths,
    verification: MachineVerification,
) -> None:
    if verification.machine_uuid != paths.machine_uuid:
        raise VerificationError("Verification UUID differs from machine path.")
    current_hashes = _config_hashes(paths)
    if dict(verification.config_file_sha256) != current_hashes:
        raise VerificationError("Canonical config files changed after verification.")
    snapshot = build_target_snapshot(paths)
    if set(snapshot) != set(verification.targets):
        raise VerificationError("Current target coverage differs from verification.")
    for key, (_kind, source_file, value) in snapshot.items():
        target = verification.targets[key]
        if target.value_sha256 != canonical_value_sha256(value):
            raise VerificationError(f"Target {key} changed after verification.")
        if target.source_file != source_file:
            raise VerificationError(f"Target {key} source file changed.")


@dataclass(frozen=True)
class SavedTargetAuthorizationRequest:
    machine_uuid: str
    target_key: str
    target_kind: str
    base_value: Mapping[str, object]
    final_coordinates: Mapping[str, int]
    workflow: str
    offsets: Mapping[str, int]
    manual: bool = False
    override: bool = False
    ignore_safe_height: bool = False


@dataclass(frozen=True)
class SavedTargetAuthorizationDecision:
    allowed: bool
    reason_code: str
    message: str
    target_key: str
    verified_value_sha256: str | None = None


class SavedTargetAuthorizer:
    """Final exact-evidence gate for configuration-derived movement."""

    def __init__(self, paths: MachineDataPaths, verification: MachineVerification) -> None:
        self.paths = paths
        self.verification = verification

    def authorize(
        self, request: SavedTargetAuthorizationRequest
    ) -> SavedTargetAuthorizationDecision:
        key = str(request.target_key or "")
        deny = lambda code, message: SavedTargetAuthorizationDecision(
            False, code, message, key, None
        )
        if request.machine_uuid != self.paths.machine_uuid or request.machine_uuid != self.verification.machine_uuid:
            return deny("machine_mismatch", "Saved target belongs to a different machine.")
        target = self.verification.targets.get(key)
        if target is None:
            return deny("target_unverified", f"Saved target {key!r} is not verified.")
        if target.state.value not in VERIFIED_STATES:
            return deny("target_revoked", f"Saved target {key!r} is not currently authorized.")
        if target.kind != request.target_kind:
            return deny("target_kind_mismatch", "Saved target kind changed.")
        if canonical_value_sha256(dict(request.base_value)) != target.value_sha256:
            return deny("target_value_changed", "Saved target values changed after verification.")
        if target.kind == "location":
            try:
                expected_final = {
                    axis: int(request.base_value[axis])
                    + int(request.offsets.get(axis, 0))
                    for axis in ("X", "Y", "Z")
                }
                actual_final = {
                    axis: int(request.final_coordinates[axis])
                    for axis in ("X", "Y", "Z")
                }
            except (KeyError, TypeError, ValueError):
                return deny("target_coordinates_invalid", "Saved target coordinates are invalid.")
            if actual_final != expected_final:
                return deny(
                    "target_derivation_changed",
                    "Final saved-location coordinates do not match the reviewed offsets.",
                )
        source_path = self.paths.machine_root / target.source_file
        try:
            current_sha = sha256_file(source_path)[0]
        except OSError:
            return deny("source_file_missing", "Saved target source file is unavailable.")
        if current_sha != target.source_file_sha256:
            return deny("source_file_changed", "Saved target source file changed after verification.")
        return SavedTargetAuthorizationDecision(
            True,
            "authorized",
            "Saved target matches exact verification evidence.",
            key,
            target.value_sha256,
        )


__all__ = [
    "ACTIVATION_RECEIPT_SCHEMA_NAME",
    "ACTIVATION_RECEIPT_SCHEMA_VERSION",
    "ActivationReceipt",
    "MachineVerification",
    "SavedTargetAuthorizationDecision",
    "SavedTargetAuthorizationRequest",
    "SavedTargetAuthorizer",
    "SourceVerification",
    "TargetVerification",
    "VerificationError",
    "VerificationState",
    "build_target_snapshot",
    "canonical_value_sha256",
    "create_machine_verification",
    "load_activation_receipt",
    "load_machine_verification",
    "parse_activation_receipt",
    "parse_machine_verification",
    "utc_now",
    "validate_verification_against_files",
    "write_activation_receipt",
    "write_machine_verification",
]
