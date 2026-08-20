"""Pure contracts for checkout-independent LabCraft machine data."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID


MACHINE_DATA_DIRNAME = "machine-data"
MACHINE_DATA_ROOT_ENV = "LABCRAFT_MACHINE_DATA_ROOT"

MACHINE_IDENTITY_SCHEMA_NAME = "labcraft.machine_identity"
MACHINE_IDENTITY_SCHEMA_VERSION = 1
ACTIVE_MACHINE_SCHEMA_NAME = "labcraft.active_machine"
ACTIVE_MACHINE_SCHEMA_VERSION = 1
ACTIVE_MACHINE_AUTHORIZED_SCHEMA_VERSION = 2

UNASSIGNED_MACHINE_ID = "LC-UNASSIGNED"
ACTIVE_MACHINE_SELECTION_SOURCES = frozenset(
    {
        "migration",
        "operator_selection",
        "managed_deployment",
        "test",
    }
)


class MachineDataContractError(ValueError):
    """Base error for invalid machine-data paths or metadata."""


class MachineDataPathError(MachineDataContractError):
    """Raised when a machine-data path is missing, broad, or unsafe."""


class MachineIdentityError(MachineDataContractError):
    """Raised when machine identity is invalid or cannot be activated."""


class ActiveMachineError(MachineDataContractError):
    """Raised when the active-machine pointer payload is invalid."""


def _absolute_path(value: str | os.PathLike[str], *, label: str) -> Path:
    if value is None:
        raise MachineDataPathError(f"{label} is required.")
    try:
        text = os.fspath(value)
    except TypeError as exc:
        raise MachineDataPathError(f"{label} must be a filesystem path.") from exc
    if not isinstance(text, str) or not text.strip():
        raise MachineDataPathError(f"{label} must not be empty.")

    path = Path(text).expanduser()
    if not path.is_absolute():
        raise MachineDataPathError(f"{label} must be an absolute path: {path}")
    return path.resolve(strict=False)


def _is_beneath_or_equal(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _reject_unsafe_machine_data_root(candidate: Path, *, repo_root: Path) -> None:
    filesystem_root = Path(candidate.anchor).resolve(strict=False)
    if candidate == filesystem_root:
        raise MachineDataPathError(
            f"Machine-data root cannot be a filesystem root: {candidate}"
        )

    user_home = Path.home().expanduser().resolve(strict=False)
    if candidate == user_home:
        raise MachineDataPathError(
            f"Machine-data root cannot be the user home directory itself: {candidate}"
        )

    if _is_beneath_or_equal(candidate, repo_root):
        raise MachineDataPathError(
            "Machine-data root must be outside the application repository: "
            f"{candidate}"
        )


@dataclass(frozen=True)
class MachineDataBasePaths:
    """Checkout-independent paths that do not depend on a selected machine."""

    root: Path
    active_machine_path: Path
    machines_root: Path

    def __post_init__(self) -> None:
        root = _absolute_path(self.root, label="Machine-data base root")
        active_machine_path = _absolute_path(
            self.active_machine_path,
            label="Active-machine path",
        )
        machines_root = _absolute_path(self.machines_root, label="Machines root")
        if active_machine_path != root / "active_machine.json":
            raise MachineDataPathError(
                "Active-machine path must be the active_machine.json child of "
                f"the machine-data root: {active_machine_path}"
            )
        if machines_root != root / "machines":
            raise MachineDataPathError(
                "Machines root must be the machines child of the machine-data "
                f"root: {machines_root}"
            )
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "active_machine_path", active_machine_path)
        object.__setattr__(self, "machines_root", machines_root)

    @property
    def activation_work_root(self) -> Path:
        return self.root / "activation_work"


@dataclass(frozen=True)
class MachineDataPaths:
    """Canonical path contract for one UUID-keyed physical machine."""

    base: MachineDataBasePaths
    machine_uuid: str
    machine_root: Path
    config_root: Path
    calibration_memory_root: Path
    calibration_root: Path
    droplet_imager_optics_path: Path
    regulator_optimization_root: Path
    metadata_root: Path
    identity_path: Path
    verification_path: Path
    migration_receipt_path: Path
    history_root: Path
    configuration_events_root: Path
    pending_transactions_root: Path
    backups_root: Path
    update_history_root: Path
    locks_root: Path
    configuration_lock_path: Path

    def __post_init__(self) -> None:
        if not isinstance(self.base, MachineDataBasePaths):
            raise MachineDataPathError("base must be a MachineDataBasePaths value.")

        canonical_uuid = _canonical_uuid(self.machine_uuid)
        machine_root = (
            self.base.machines_root / canonical_uuid
        ).resolve(strict=False)
        if not _is_beneath_or_equal(machine_root, self.base.machines_root):
            raise MachineDataPathError(
                "Machine directory escaped the configured machines root: "
                f"{machine_root}"
            )

        expected_paths = {
            "machine_root": machine_root,
            "config_root": machine_root / "config",
            "calibration_memory_root": machine_root / "CalibrationMemory",
            "calibration_root": machine_root / "calibration",
            "droplet_imager_optics_path": (
                machine_root / "calibration" / "droplet_imager_optics.json"
            ),
            "regulator_optimization_root": (
                machine_root / "calibration" / "regulator_optimization"
            ),
            "metadata_root": machine_root / "metadata",
            "identity_path": machine_root / "metadata" / "machine_identity.json",
            "verification_path": machine_root / "metadata" / "verification.json",
            "migration_receipt_path": (
                machine_root / "metadata" / "migration_receipt.json"
            ),
            "history_root": machine_root / "history",
            "configuration_events_root": (
                machine_root / "history" / "configuration_events"
            ),
            "pending_transactions_root": (
                machine_root / "history" / "pending_transactions"
            ),
            "backups_root": machine_root / "backups",
            "update_history_root": machine_root / "update_history",
            "locks_root": machine_root / "locks",
            "configuration_lock_path": (
                machine_root / "locks" / "configuration.lock"
            ),
        }

        object.__setattr__(self, "machine_uuid", canonical_uuid)
        for field, expected in expected_paths.items():
            actual = _absolute_path(getattr(self, field), label=field)
            if actual != expected:
                raise MachineDataPathError(
                    f"{field} must match the canonical machine-data layout: "
                    f"{actual}"
                )
            object.__setattr__(self, field, actual)

    @property
    def activation_receipt_path(self) -> Path:
        return self.metadata_root / "activation_receipt.json"

    @property
    def configuration_head_path(self) -> Path:
        """Current post-activation configuration-chain head."""

        return self.history_root / "configuration_head.json"

    @property
    def configuration_backups_root(self) -> Path:
        """Verified pre-change backups for configuration transactions."""

        return self.backups_root / "configuration"

    @property
    def candidate_evidence_path(self) -> Path:
        return self.metadata_root / "candidate_evidence.json"

    @property
    def migration_tree_manifest_path(self) -> Path:
        return self.metadata_root / "migration_tree_manifest.json"

    @property
    def update_lock_path(self) -> Path:
        """Exclusive lock held while application code or compatibility data changes."""

        return self.locks_root / "update.lock"

    @property
    def update_transactions_root(self) -> Path:
        """Immutable per-operation update evidence directories."""

        return self.update_history_root / "transactions"

    @property
    def deployment_anchor_path(self) -> Path:
        """Atomic pointer to the last application deployment authorized for this store."""

        return self.update_history_root / "deployment_anchor.json"

    @property
    def latest_update_result_path(self) -> Path:
        """Diagnostic pointer to the latest immutable update terminal result."""

        return self.update_history_root / "latest_result.json"

    @property
    def latest_update_ui_result_path(self) -> Path:
        """Disposable operator summary; never used as deployment authority."""

        return self.update_history_root / "latest_ui_result.json"

    @property
    def legacy_session_path(self) -> Path:
        """Atomic pointer to an unresolved checkout-local compatibility session."""

        return self.update_history_root / "legacy_session.json"


def resolve_machine_data_base(
    *,
    app_local_data_root: str | os.PathLike[str],
    repo_root: str | os.PathLike[str],
    explicit_root: str | os.PathLike[str] | None = None,
    environment: Mapping[str, str] | None = None,
) -> MachineDataBasePaths:
    """Resolve the external base without creating or modifying any path.

    Precedence is explicit argument, environment override, then a
    ``machine-data`` child beneath the Qt application-local directory supplied
    by the caller.
    """

    resolved_repo_root = _absolute_path(repo_root, label="Repository root")
    env = os.environ if environment is None else environment
    if not isinstance(env, Mapping):
        raise MachineDataPathError("Environment must be a string mapping.")

    if explicit_root is not None:
        candidate = _absolute_path(explicit_root, label="Explicit machine-data root")
    elif MACHINE_DATA_ROOT_ENV in env:
        candidate = _absolute_path(
            env[MACHINE_DATA_ROOT_ENV],
            label=f"{MACHINE_DATA_ROOT_ENV} override",
        )
    else:
        app_local = _absolute_path(
            app_local_data_root,
            label="Application-local data root",
        )
        candidate = (app_local / MACHINE_DATA_DIRNAME).resolve(strict=False)

    _reject_unsafe_machine_data_root(candidate, repo_root=resolved_repo_root)
    return MachineDataBasePaths(
        root=candidate,
        active_machine_path=candidate / "active_machine.json",
        machines_root=candidate / "machines",
    )


def _canonical_uuid(value: Any, *, error_type=MachineIdentityError) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type("machine_uuid must be a non-empty UUID string.")
    try:
        return str(UUID(value.strip()))
    except (ValueError, AttributeError) as exc:
        raise error_type(f"Invalid machine_uuid: {value!r}") from exc


def build_machine_data_paths(
    base: MachineDataBasePaths,
    machine_uuid: str,
) -> MachineDataPaths:
    """Build contained per-machine paths without touching the filesystem."""

    if not isinstance(base, MachineDataBasePaths):
        raise MachineDataPathError("base must be a MachineDataBasePaths value.")

    canonical_uuid = _canonical_uuid(machine_uuid)
    machine_root = (base.machines_root / canonical_uuid).resolve(strict=False)
    if not _is_beneath_or_equal(machine_root, base.machines_root):
        raise MachineDataPathError(
            f"Machine directory escaped the configured machines root: {machine_root}"
        )

    config_root = machine_root / "config"
    calibration_memory_root = machine_root / "CalibrationMemory"
    calibration_root = machine_root / "calibration"
    metadata_root = machine_root / "metadata"
    history_root = machine_root / "history"
    backups_root = machine_root / "backups"
    update_history_root = machine_root / "update_history"
    locks_root = machine_root / "locks"

    return MachineDataPaths(
        base=base,
        machine_uuid=canonical_uuid,
        machine_root=machine_root,
        config_root=config_root,
        calibration_memory_root=calibration_memory_root,
        calibration_root=calibration_root,
        droplet_imager_optics_path=(
            calibration_root / "droplet_imager_optics.json"
        ),
        regulator_optimization_root=(
            calibration_root / "regulator_optimization"
        ),
        metadata_root=metadata_root,
        identity_path=metadata_root / "machine_identity.json",
        verification_path=metadata_root / "verification.json",
        migration_receipt_path=metadata_root / "migration_receipt.json",
        history_root=history_root,
        configuration_events_root=history_root / "configuration_events",
        pending_transactions_root=history_root / "pending_transactions",
        backups_root=backups_root,
        update_history_root=update_history_root,
        locks_root=locks_root,
        configuration_lock_path=locks_root / "configuration.lock",
    )


def _canonical_utc_timestamp(
    value: Any,
    *,
    field: str,
    error_type: type[MachineDataContractError],
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{field} must be a non-empty UTC timestamp string.")

    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise error_type(f"{field} is not a valid RFC3339 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise error_type(f"{field} must identify UTC: {value!r}")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _machine_id(
    value: Any,
    *,
    allow_unassigned: bool,
    error_type: type[MachineDataContractError],
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type("machine_id must be a non-empty string.")
    machine_id = value.strip()
    if not allow_unassigned and machine_id.casefold() == UNASSIGNED_MACHINE_ID.casefold():
        raise error_type("An unassigned machine identity cannot become active.")
    return machine_id


def _require_schema(
    payload: Mapping[str, Any],
    *,
    schema_name: str,
    schema_version: int,
    label: str,
    error_type: type[MachineDataContractError],
) -> None:
    if payload.get("schema_name") != schema_name:
        raise error_type(
            f"{label} schema_name must be {schema_name!r}."
        )
    version = payload.get("schema_version")
    if type(version) is not int or version != schema_version:
        raise error_type(
            f"{label} schema_version must be {schema_version}."
        )


@dataclass(frozen=True)
class MachineIdentity:
    machine_id: str
    machine_uuid: str
    assigned_at: str
    notes: str = ""

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_name": MACHINE_IDENTITY_SCHEMA_NAME,
            "schema_version": MACHINE_IDENTITY_SCHEMA_VERSION,
            "machine_id": self.machine_id,
            "machine_uuid": self.machine_uuid,
            "assigned_at": self.assigned_at,
            "notes": self.notes,
        }


def parse_machine_identity(
    payload: object,
    *,
    allow_legacy: bool = False,
    allow_unassigned: bool = False,
) -> MachineIdentity:
    """Validate canonical or explicitly permitted legacy identity data."""

    if not isinstance(payload, dict):
        raise MachineIdentityError("Machine identity must be a JSON object.")

    has_schema_marker = "schema_name" in payload or "schema_version" in payload
    if has_schema_marker:
        _require_schema(
            payload,
            schema_name=MACHINE_IDENTITY_SCHEMA_NAME,
            schema_version=MACHINE_IDENTITY_SCHEMA_VERSION,
            label="Machine identity",
            error_type=MachineIdentityError,
        )
    elif not allow_legacy:
        raise MachineIdentityError(
            "A legacy machine identity requires allow_legacy=True."
        )

    notes = payload.get("notes", "")
    if not isinstance(notes, str):
        raise MachineIdentityError("notes must be text.")

    return MachineIdentity(
        machine_id=_machine_id(
            payload.get("machine_id"),
            allow_unassigned=allow_unassigned,
            error_type=MachineIdentityError,
        ),
        machine_uuid=_canonical_uuid(payload.get("machine_uuid")),
        assigned_at=_canonical_utc_timestamp(
            payload.get("assigned_at"),
            field="assigned_at",
            error_type=MachineIdentityError,
        ),
        notes=notes,
    )


@dataclass(frozen=True)
class ActiveMachine:
    machine_id: str
    machine_uuid: str
    selected_at_utc: str
    selection_source: str
    activation_id: str | None = None
    migration_id: str | None = None
    activation_receipt_sha256: str | None = None

    @property
    def authorizes_production(self) -> bool:
        return all(
            value is not None
            for value in (
                self.activation_id,
                self.migration_id,
                self.activation_receipt_sha256,
            )
        )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_name": ACTIVE_MACHINE_SCHEMA_NAME,
            "schema_version": (
                ACTIVE_MACHINE_AUTHORIZED_SCHEMA_VERSION
                if self.authorizes_production
                else ACTIVE_MACHINE_SCHEMA_VERSION
            ),
            "machine_id": self.machine_id,
            "machine_uuid": self.machine_uuid,
            "selected_at_utc": self.selected_at_utc,
            "selection_source": self.selection_source,
        }
        if self.authorizes_production:
            payload.update(
                {
                    "activation_id": self.activation_id,
                    "migration_id": self.migration_id,
                    "activation_receipt_sha256": self.activation_receipt_sha256,
                }
            )
        return payload


def parse_active_machine(payload: object) -> ActiveMachine:
    """Validate a canonical active-machine pointer payload."""

    if not isinstance(payload, dict):
        raise ActiveMachineError("Active machine must be a JSON object.")
    if payload.get("schema_name") != ACTIVE_MACHINE_SCHEMA_NAME:
        raise ActiveMachineError(
            f"Active machine schema_name must be {ACTIVE_MACHINE_SCHEMA_NAME!r}."
        )
    version = payload.get("schema_version")
    if type(version) is not int or version not in {
        ACTIVE_MACHINE_SCHEMA_VERSION,
        ACTIVE_MACHINE_AUTHORIZED_SCHEMA_VERSION,
    }:
        raise ActiveMachineError("Active machine schema_version is unsupported.")

    source = payload.get("selection_source")
    if not isinstance(source, str) or source not in ACTIVE_MACHINE_SELECTION_SOURCES:
        supported = ", ".join(sorted(ACTIVE_MACHINE_SELECTION_SOURCES))
        raise ActiveMachineError(
            f"selection_source must be one of: {supported}."
        )

    activation_id = migration_id = activation_receipt_sha256 = None
    if version == ACTIVE_MACHINE_AUTHORIZED_SCHEMA_VERSION:
        activation_id = _canonical_uuid(
            payload.get("activation_id"), error_type=ActiveMachineError
        )
        migration_id = _canonical_uuid(
            payload.get("migration_id"), error_type=ActiveMachineError
        )
        activation_receipt_sha256 = payload.get("activation_receipt_sha256")
        if (
            not isinstance(activation_receipt_sha256, str)
            or len(activation_receipt_sha256) != 64
            or any(character not in "0123456789abcdef" for character in activation_receipt_sha256)
        ):
            raise ActiveMachineError(
                "activation_receipt_sha256 must be lowercase SHA-256 text."
            )

    return ActiveMachine(
        machine_id=_machine_id(
            payload.get("machine_id"),
            allow_unassigned=False,
            error_type=ActiveMachineError,
        ),
        machine_uuid=_canonical_uuid(
            payload.get("machine_uuid"),
            error_type=ActiveMachineError,
        ),
        selected_at_utc=_canonical_utc_timestamp(
            payload.get("selected_at_utc"),
            field="selected_at_utc",
            error_type=ActiveMachineError,
        ),
        selection_source=source,
        activation_id=activation_id,
        migration_id=migration_id,
        activation_receipt_sha256=activation_receipt_sha256,
    )


def require_authorized_active_machine(payload: object) -> ActiveMachine:
    """Parse a pointer and reject diagnostic-only version 1 records."""

    active = parse_active_machine(payload)
    if not active.authorizes_production:
        raise ActiveMachineError(
            "Active-machine version 1 is diagnostic-only and cannot authorize production."
        )
    return active


__all__ = [
    "ACTIVE_MACHINE_SCHEMA_NAME",
    "ACTIVE_MACHINE_SCHEMA_VERSION",
    "ACTIVE_MACHINE_AUTHORIZED_SCHEMA_VERSION",
    "ACTIVE_MACHINE_SELECTION_SOURCES",
    "MACHINE_DATA_DIRNAME",
    "MACHINE_DATA_ROOT_ENV",
    "MACHINE_IDENTITY_SCHEMA_NAME",
    "MACHINE_IDENTITY_SCHEMA_VERSION",
    "UNASSIGNED_MACHINE_ID",
    "ActiveMachine",
    "ActiveMachineError",
    "MachineDataBasePaths",
    "MachineDataContractError",
    "MachineDataPathError",
    "MachineDataPaths",
    "MachineIdentity",
    "MachineIdentityError",
    "build_machine_data_paths",
    "parse_active_machine",
    "parse_machine_identity",
    "require_authorized_active_machine",
    "resolve_machine_data_base",
]
