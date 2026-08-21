"""Explicit, isolated development-store preparation and launch evidence."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping
from uuid import UUID, uuid4

from MachineData import require_authorized_active_machine
from DevelopmentHardwareAuthorization import (
    ATTENDED_CONFIRMATION,
    CLEAR_ENVELOPE_CONFIRMATION,
    DevelopmentHardwareAuthorizationError,
    validate_authorization,
)


DEVELOPMENT_MODE_ENV = "LABCRAFT_DEPLOYMENT_MODE"
DEVELOPMENT_OPERATOR_ENV = "LABCRAFT_DEVELOPMENT_OPERATOR"
DEVELOPMENT_HARDWARE_ENV = "LABCRAFT_DEVELOPMENT_HARDWARE"
DEVELOPMENT_HARDWARE_CONFIRMATION_ENV = (
    "LABCRAFT_DEVELOPMENT_HARDWARE_CONFIRMATION"
)
DEVELOPMENT_CLEAR_ENVELOPE_CONFIRMATION_ENV = (
    "LABCRAFT_DEVELOPMENT_CLEAR_ENVELOPE_CONFIRMATION"
)
DEVELOPMENT_HARDWARE_AUTHORIZATION_ENV = (
    "LABCRAFT_DEVELOPMENT_HARDWARE_AUTHORIZATION"
)
DEVELOPMENT_EXPECTED_COMMIT_ENV = "LABCRAFT_DEVELOPMENT_EXPECTED_COMMIT"
DEVELOPMENT_MODE = "development"
DEVELOPMENT_HARDWARE_CONFIRMATION = ATTENDED_CONFIRMATION
DEVELOPMENT_CLEAR_ENVELOPE_CONFIRMATION = CLEAR_ENVELOPE_CONFIRMATION

DEVELOPMENT_STORE_SCHEMA_NAME = "labcraft.development_machine_data_store"
DEVELOPMENT_STORE_SCHEMA_VERSION = 1
DEVELOPMENT_SESSION_SCHEMA_NAME = "labcraft.development_session"
DEVELOPMENT_SESSION_SCHEMA_VERSION = 1
DEVELOPMENT_RUNTIME_SCHEMA_NAME = "labcraft.development_no_hardware_runtime"
DEVELOPMENT_RUNTIME_SCHEMA_VERSION = 1
DEVELOPMENT_STORE_FILENAME = "development_store.json"

_WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class DevelopmentStoreError(RuntimeError):
    """Raised when an isolated development store or launch is unsafe."""


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _absolute_path(value: str | os.PathLike[str], label: str) -> Path:
    if value is None:
        raise DevelopmentStoreError(f"{label} is required.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise DevelopmentStoreError(f"{label} must be absolute: {path}")
    return path.resolve(strict=False)


def _is_beneath_or_equal(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _validate_distinct_roots(source: Path, target: Path, repo_root: Path) -> None:
    filesystem_root = Path(target.anchor).resolve(strict=False)
    home = Path.home().resolve(strict=False)
    if target in {filesystem_root, home, repo_root}:
        raise DevelopmentStoreError(
            f"Development root is too broad or unsafe: {target}"
        )
    if _is_beneath_or_equal(target, repo_root):
        raise DevelopmentStoreError(
            "Development machine data must be outside the repository."
        )
    if (
        source == target
        or _is_beneath_or_equal(source, target)
        or _is_beneath_or_equal(target, source)
    ):
        raise DevelopmentStoreError(
            "Production and development machine-data roots must be disjoint."
        )


def _regular_tree_inventory(root: Path) -> dict[str, tuple[int, str]]:
    inventory: dict[str, tuple[int, str]] = {}
    folded: set[str] = set()
    for path in sorted(root.rglob("*")):
        details = path.lstat()
        attributes = getattr(details, "st_file_attributes", 0)
        if stat.S_ISLNK(details.st_mode) or attributes & _WINDOWS_REPARSE_POINT:
            raise DevelopmentStoreError(
                f"Machine-data tree contains a link/reparse point: {path}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise DevelopmentStoreError(
                f"Machine-data tree contains a special file: {path}"
            )
        relative = path.relative_to(root).as_posix()
        if relative.casefold() in folded:
            raise DevelopmentStoreError(
                "Machine-data tree contains case-colliding paths."
            )
        folded.add(relative.casefold())
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                size += len(block)
        inventory[relative] = (size, digest.hexdigest())
    return inventory


def _inventory_fingerprint(inventory: Mapping[str, tuple[int, str]]) -> str:
    payload = [
        {"relative_path": path, "size": value[0], "raw_sha256": value[1]}
        for path, value in sorted(inventory.items())
    ]
    data = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (
        json.dumps(
            dict(payload),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    temporary = path.parent / f".{path.name}.{uuid4()}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class DevelopmentStore:
    root: Path
    source_machine_data_root: Path
    store_id: str
    created_at_utc: str
    created_by: str
    creation_commit: str
    source_tree_fingerprint: str
    source_active_pointer_sha256: str


@dataclass(frozen=True)
class DevelopmentLaunch:
    store: DevelopmentStore
    operator: str
    hardware_enabled: bool
    hardware_authorization_id: str | None = None


def prepare_development_store(
    source_root: str | os.PathLike[str],
    target_root: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str],
    operator: str,
    app_commit: str,
    clock: Callable[[], str] = utc_now,
    uuid_factory: Callable[[], object] = uuid4,
) -> DevelopmentStore:
    """Create a byte-verified, disjoint clone without overwriting any target."""

    source = _absolute_path(source_root, "Source machine-data root")
    target = _absolute_path(target_root, "Development machine-data root")
    repository = _absolute_path(repo_root, "Repository root")
    _validate_distinct_roots(source, target, repository)
    operator_text = str(operator or "").strip()
    commit_text = str(app_commit or "").strip()
    if not operator_text or not commit_text:
        raise DevelopmentStoreError("Operator and exact application commit are required.")
    if not source.is_dir() or not (source / "active_machine.json").is_file():
        raise DevelopmentStoreError(
            "Source must be an existing authorized machine-data root."
        )
    if (source / DEVELOPMENT_STORE_FILENAME).exists():
        raise DevelopmentStoreError(
            "Development stores cannot be used as production clone sources."
        )
    try:
        pointer_payload = json.loads(
            (source / "active_machine.json").read_text(encoding="utf-8")
        )
        require_authorized_active_machine(pointer_payload)
    except Exception as exc:
        raise DevelopmentStoreError(
            f"Source active-machine authority is invalid: {exc}"
        ) from exc
    if target.exists():
        raise DevelopmentStoreError(
            f"Development target already exists; refusing to overlay it: {target}"
        )
    if not target.parent.is_dir():
        raise DevelopmentStoreError(
            f"Development target parent does not exist: {target.parent}"
        )

    source_inventory = _regular_tree_inventory(source)
    pointer_evidence = source_inventory.get("active_machine.json")
    if pointer_evidence is None:
        raise DevelopmentStoreError("Source active-machine pointer is missing.")
    store_id = str(UUID(str(uuid_factory())))
    stage = target.parent / f".{target.name}.stage-{store_id}"
    if stage.exists():
        raise DevelopmentStoreError(f"Development staging path already exists: {stage}")

    try:
        shutil.copytree(source, stage, symlinks=False)
        staged_inventory = _regular_tree_inventory(stage)
        if staged_inventory != source_inventory:
            raise DevelopmentStoreError(
                "Development copy differs from its source; no store was published."
            )
        marker = {
            "schema_name": DEVELOPMENT_STORE_SCHEMA_NAME,
            "schema_version": DEVELOPMENT_STORE_SCHEMA_VERSION,
            "development_root": str(target),
            "source_machine_data_root": str(source),
            "store_id": store_id,
            "created_at_utc": clock(),
            "created_by": operator_text,
            "creation_commit": commit_text,
            "source_tree_fingerprint": _inventory_fingerprint(source_inventory),
            "source_active_pointer_sha256": pointer_evidence[1],
        }
        _atomic_json(stage / DEVELOPMENT_STORE_FILENAME, marker)
        os.replace(stage, target)
    except Exception:
        if stage.is_dir() and stage.parent == target.parent and stage.name.startswith(
            f".{target.name}.stage-"
        ):
            shutil.rmtree(stage)
        raise

    return load_development_store(target)


def load_development_store(root: str | os.PathLike[str]) -> DevelopmentStore:
    target = _absolute_path(root, "Development machine-data root")
    marker_path = target / DEVELOPMENT_STORE_FILENAME
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DevelopmentStoreError(
            f"Development-store marker cannot be read: {exc}"
        ) from exc
    expected = {
        "schema_name",
        "schema_version",
        "development_root",
        "source_machine_data_root",
        "store_id",
        "created_at_utc",
        "created_by",
        "creation_commit",
        "source_tree_fingerprint",
        "source_active_pointer_sha256",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or payload.get("schema_name") != DEVELOPMENT_STORE_SCHEMA_NAME
        or payload.get("schema_version") != DEVELOPMENT_STORE_SCHEMA_VERSION
    ):
        raise DevelopmentStoreError("Development-store marker schema is invalid.")
    marker_root = _absolute_path(payload["development_root"], "Marker development root")
    source = _absolute_path(
        payload["source_machine_data_root"], "Marker production root"
    )
    if (
        marker_root != target
        or source == target
        or _is_beneath_or_equal(source, target)
        or _is_beneath_or_equal(target, source)
    ):
        raise DevelopmentStoreError("Development-store root binding differs.")
    try:
        store_id = str(UUID(str(payload["store_id"])))
    except ValueError as exc:
        raise DevelopmentStoreError("Development store ID is invalid.") from exc
    for name in (
        "created_at_utc",
        "created_by",
        "creation_commit",
        "source_tree_fingerprint",
        "source_active_pointer_sha256",
    ):
        if not isinstance(payload.get(name), str) or not payload[name].strip():
            raise DevelopmentStoreError(f"Development marker {name} is invalid.")
    for name in ("source_tree_fingerprint", "source_active_pointer_sha256"):
        value = payload[name]
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise DevelopmentStoreError(f"Development marker {name} is invalid.")
    return DevelopmentStore(
        root=target,
        source_machine_data_root=source,
        store_id=store_id,
        created_at_utc=payload["created_at_utc"],
        created_by=payload["created_by"],
        creation_commit=payload["creation_commit"],
        source_tree_fingerprint=payload["source_tree_fingerprint"],
        source_active_pointer_sha256=payload["source_active_pointer_sha256"],
    )


def development_launch_from_environment(
    root: str | os.PathLike[str],
    environment: Mapping[str, str],
) -> DevelopmentLaunch | None:
    mode = str(environment.get(DEVELOPMENT_MODE_ENV, "")).strip().lower()
    if not mode:
        return None
    if mode != DEVELOPMENT_MODE:
        raise DevelopmentStoreError(
            f"Unsupported {DEVELOPMENT_MODE_ENV}: {mode!r}"
        )
    store = load_development_store(root)
    operator = str(environment.get(DEVELOPMENT_OPERATOR_ENV, "")).strip()
    if not operator:
        raise DevelopmentStoreError(
            f"{DEVELOPMENT_OPERATOR_ENV} is required in development mode."
        )
    hardware_text = str(environment.get(DEVELOPMENT_HARDWARE_ENV, "0")).strip()
    if hardware_text not in {"0", "1"}:
        raise DevelopmentStoreError(
            f"{DEVELOPMENT_HARDWARE_ENV} must be 0 or 1."
        )
    hardware_enabled = hardware_text == "1"
    authorization_id = None
    if hardware_enabled:
        if environment.get(
            DEVELOPMENT_HARDWARE_CONFIRMATION_ENV
        ) != DEVELOPMENT_HARDWARE_CONFIRMATION:
            raise DevelopmentStoreError(
                "Development hardware access requires the exact attended confirmation."
            )
        if environment.get(
            DEVELOPMENT_CLEAR_ENVELOPE_CONFIRMATION_ENV
        ) != DEVELOPMENT_CLEAR_ENVELOPE_CONFIRMATION:
            raise DevelopmentStoreError(
                "Development hardware access requires the exact clear-envelope confirmation."
            )
        expected_commit = str(
            environment.get(DEVELOPMENT_EXPECTED_COMMIT_ENV, "")
        ).strip()
        authorization_path = str(
            environment.get(DEVELOPMENT_HARDWARE_AUTHORIZATION_ENV, "")
        ).strip()
        if not expected_commit or not authorization_path:
            raise DevelopmentStoreError(
                "Development hardware access requires commit-bound external authorization."
            )
        try:
            authorization = validate_authorization(
                authorization_path,
                operator=operator,
                expected_commit=expected_commit,
                development_store_id=store.store_id,
                development_machine_data_root=store.root,
            )
        except DevelopmentHardwareAuthorizationError as exc:
            raise DevelopmentStoreError(
                f"Development hardware authorization is invalid: {exc}"
            ) from exc
        authorization_id = str(authorization["authorization_id"])
    return DevelopmentLaunch(store, operator, hardware_enabled, authorization_id)


def record_development_session(
    launch: DevelopmentLaunch,
    *,
    app_version: str,
    app_commit: str,
    clock: Callable[[], str] = utc_now,
    uuid_factory: Callable[[], object] = uuid4,
) -> Path:
    session_id = str(UUID(str(uuid_factory())))
    pointer = launch.store.root / "active_machine.json"
    marker = launch.store.root / DEVELOPMENT_STORE_FILENAME
    if not pointer.is_file() or not marker.is_file():
        raise DevelopmentStoreError("Development launch evidence is incomplete.")
    payload = {
        "schema_name": DEVELOPMENT_SESSION_SCHEMA_NAME,
        "schema_version": DEVELOPMENT_SESSION_SCHEMA_VERSION,
        "session_id": session_id,
        "store_id": launch.store.store_id,
        "development_root": str(launch.store.root),
        "source_machine_data_root": str(launch.store.source_machine_data_root),
        "operator": launch.operator,
        "hardware_enabled": launch.hardware_enabled,
        "hardware_authorization_id": launch.hardware_authorization_id,
        "app_version": str(app_version),
        "app_commit": str(app_commit),
        "started_at_utc": clock(),
        "os_account": getpass.getuser() or "unknown",
        "active_pointer_sha256": hashlib.sha256(pointer.read_bytes()).hexdigest(),
        "development_store_marker_sha256": hashlib.sha256(marker.read_bytes()).hexdigest(),
    }
    path = launch.store.root / "development_sessions" / f"{session_id}.json"
    if path.exists():
        raise DevelopmentStoreError("Development session evidence already exists.")
    _atomic_json(path, payload)
    return path


def record_no_hardware_runtime_evidence(
    session_path: str | os.PathLike[str],
    *,
    app_commit: str,
    machine_type: str,
    runtime_mode: str,
    identity_text: str,
    hardware_access_allowed: bool,
    updater_access_allowed: bool,
    peripheral_factories: Mapping[str, str],
    clock: Callable[[], str] = utc_now,
) -> Path:
    """Prove the development UI was composed without a hardware-capable path."""

    source = _absolute_path(session_path, "Development session evidence")
    if source.parent.name != "development_sessions" or not source.is_file():
        raise DevelopmentStoreError("Development session evidence path is invalid.")
    try:
        session_id = str(UUID(source.stem))
        session = json.loads(source.read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise DevelopmentStoreError(
            f"Development session evidence cannot be verified: {exc}"
        ) from exc
    if (
        not isinstance(session, dict)
        or session.get("schema_name") != DEVELOPMENT_SESSION_SCHEMA_NAME
        or session.get("schema_version") != DEVELOPMENT_SESSION_SCHEMA_VERSION
        or session.get("session_id") != session_id
        or session.get("hardware_enabled") is not False
        or session.get("app_commit") != str(app_commit)
    ):
        raise DevelopmentStoreError(
            "Development session does not authorize no-hardware runtime evidence."
        )
    factories = dict(peripheral_factories)
    expected_factories = {
        "serial", "refuel_camera", "droplet_camera", "log_reader",
        "balance", "experimental_balance", "legacy_calibration",
    }
    if set(factories) != expected_factories or any(
        not isinstance(value, str) or not value.startswith("blocked_")
        for value in factories.values()
    ):
        raise DevelopmentStoreError(
            "Development peripheral factories are not all fail-closed."
        )
    if (
        str(machine_type) != "SimulatedMachine"
        or str(runtime_mode) != "development"
        or hardware_access_allowed is not False
        or updater_access_allowed is not False
        or "DEVELOPMENT" not in str(identity_text)
        or "NO HARDWARE" not in str(identity_text)
    ):
        raise DevelopmentStoreError(
            "Development application composition is not no-hardware safe."
        )
    payload = {
        "schema_name": DEVELOPMENT_RUNTIME_SCHEMA_NAME,
        "schema_version": DEVELOPMENT_RUNTIME_SCHEMA_VERSION,
        "session_id": session_id,
        "session_evidence_path": str(source),
        "session_evidence_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "store_id": session["store_id"],
        "app_commit": str(app_commit),
        "verified_at_utc": clock(),
        "machine_type": str(machine_type),
        "runtime_mode": str(runtime_mode),
        "identity_text": str(identity_text),
        "hardware_access_allowed": False,
        "updater_access_allowed": False,
        "peripheral_factories": factories,
    }
    destination = source.with_suffix(".runtime.json")
    if destination.exists():
        raise DevelopmentStoreError("Development runtime evidence already exists.")
    _atomic_json(destination, payload)
    return destination


__all__ = [
    "DEVELOPMENT_HARDWARE_CONFIRMATION",
    "DEVELOPMENT_HARDWARE_CONFIRMATION_ENV",
    "DEVELOPMENT_CLEAR_ENVELOPE_CONFIRMATION",
    "DEVELOPMENT_CLEAR_ENVELOPE_CONFIRMATION_ENV",
    "DEVELOPMENT_EXPECTED_COMMIT_ENV",
    "DEVELOPMENT_HARDWARE_AUTHORIZATION_ENV",
    "DEVELOPMENT_HARDWARE_ENV",
    "DEVELOPMENT_MODE_ENV",
    "DEVELOPMENT_OPERATOR_ENV",
    "DEVELOPMENT_RUNTIME_SCHEMA_NAME",
    "DEVELOPMENT_RUNTIME_SCHEMA_VERSION",
    "DevelopmentLaunch",
    "DevelopmentStore",
    "DevelopmentStoreError",
    "development_launch_from_environment",
    "load_development_store",
    "prepare_development_store",
    "record_development_session",
    "record_no_hardware_runtime_evidence",
]
