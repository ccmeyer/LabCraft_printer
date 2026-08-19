"""Pure contracts for checkout-independent LabCraft machine data.

Milestone 1 intentionally keeps these helpers side-effect free. Production
startup continues to use the legacy checkout-local configuration until the
later migration/activation milestone supplies these paths explicitly.
"""

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


@dataclass(frozen=True)
class MachineDataPaths:
    """Canonical path contract for one UUID-keyed physical machine."""

    base: MachineDataBasePaths
    machine_uuid: str
    machine_root: Path
    config_root: Path
    calibration_memory_root: Path
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

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_name": ACTIVE_MACHINE_SCHEMA_NAME,
            "schema_version": ACTIVE_MACHINE_SCHEMA_VERSION,
            "machine_id": self.machine_id,
            "machine_uuid": self.machine_uuid,
            "selected_at_utc": self.selected_at_utc,
            "selection_source": self.selection_source,
        }


def parse_active_machine(payload: object) -> ActiveMachine:
    """Validate a canonical active-machine pointer payload."""

    if not isinstance(payload, dict):
        raise ActiveMachineError("Active machine must be a JSON object.")
    _require_schema(
        payload,
        schema_name=ACTIVE_MACHINE_SCHEMA_NAME,
        schema_version=ACTIVE_MACHINE_SCHEMA_VERSION,
        label="Active machine",
        error_type=ActiveMachineError,
    )

    source = payload.get("selection_source")
    if not isinstance(source, str) or source not in ACTIVE_MACHINE_SELECTION_SOURCES:
        supported = ", ".join(sorted(ACTIVE_MACHINE_SELECTION_SOURCES))
        raise ActiveMachineError(
            f"selection_source must be one of: {supported}."
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
    )


__all__ = [
    "ACTIVE_MACHINE_SCHEMA_NAME",
    "ACTIVE_MACHINE_SCHEMA_VERSION",
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
    "resolve_machine_data_base",
]
