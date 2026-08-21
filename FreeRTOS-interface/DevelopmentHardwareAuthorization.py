"""Short-lived, external authorization for attended development hardware."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4


SCHEMA_NAME = "labcraft.development_hardware_authorization"
SCHEMA_VERSION = 1
ATTENDED_CONFIRMATION = "I UNDERSTAND THIS DEVELOPMENT BUILD CAN CONTROL HARDWARE"
CLEAR_ENVELOPE_CONFIRMATION = (
    "I CONFIRM MOTOR POWER IS INHIBITED, THE MOTION ENVELOPE IS CLEAR, "
    "THE EMERGENCY STOP IS IMMEDIATELY REACHABLE, AND I AM ATTENDING THE PI"
)


class DevelopmentHardwareAuthorizationError(RuntimeError):
    """Raised when attended hardware authorization is absent or stale."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DevelopmentHardwareAuthorizationError(f"Authorization {label} is invalid.")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise DevelopmentHardwareAuthorizationError(
            f"Authorization {label} is invalid."
        ) from exc


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def confirmation_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_hex(value: Any, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def create_authorization(
    path: str | os.PathLike[str],
    *,
    operator: str,
    expected_commit: str,
    development_store_id: str,
    development_machine_data_root: str | os.PathLike[str],
    firmware_state_path: str | os.PathLike[str],
    firmware_compatibility: Mapping[str, Any],
    issued_at: datetime | None = None,
    lifetime_seconds: int = 300,
    uuid_factory: Callable[[], object] = uuid4,
) -> Path:
    destination = Path(path).expanduser()
    state_path = Path(firmware_state_path).expanduser().resolve()
    root = Path(development_machine_data_root).expanduser().resolve()
    if not destination.is_absolute() or not state_path.is_file() or not root.is_dir():
        raise DevelopmentHardwareAuthorizationError("Authorization paths are invalid.")
    if not 30 <= lifetime_seconds <= 600:
        raise DevelopmentHardwareAuthorizationError("Authorization lifetime is invalid.")
    now = (issued_at or _utc_now()).astimezone(timezone.utc)
    authorization_id = str(UUID(str(uuid_factory())))
    payload = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "authorization_id": authorization_id,
        "status": "authorized",
        "action": "hardware-development-launch",
        "operator": str(operator).strip(),
        "issued_at_utc": now.isoformat().replace("+00:00", "Z"),
        "expires_at_utc": datetime.fromtimestamp(
            now.timestamp() + lifetime_seconds, timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "expected_commit": expected_commit,
        "development_store_id": development_store_id,
        "development_machine_data_root": str(root),
        "firmware_state_path": str(state_path),
        "firmware_state_sha256": _sha(state_path),
        "firmware_role": firmware_compatibility.get("role"),
        "firmware_source_commit": firmware_compatibility.get("source_commit"),
        "firmware_artifact_sha256": firmware_compatibility.get("artifact_sha256"),
        "released_artifact_sha256": firmware_compatibility.get("released_artifact_sha256"),
        "attended_confirmation_sha256": confirmation_sha256(ATTENDED_CONFIRMATION),
        "clear_envelope_confirmation_sha256": confirmation_sha256(
            CLEAR_ENVELOPE_CONFIRMATION
        ),
    }
    if not payload["operator"]:
        raise DevelopmentHardwareAuthorizationError("Authorization operator is required.")
    if not _is_hex(expected_commit, 40) or any(
        not _is_hex(payload[name], 64)
        for name in (
            "firmware_state_sha256", "firmware_artifact_sha256",
            "released_artifact_sha256", "attended_confirmation_sha256",
            "clear_envelope_confirmation_sha256",
        )
    ):
        raise DevelopmentHardwareAuthorizationError(
            "Authorization commit or SHA-256 binding is invalid."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{authorization_id}.tmp"
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return destination


def validate_authorization(
    path: str | os.PathLike[str],
    *,
    operator: str,
    expected_commit: str,
    development_store_id: str,
    development_machine_data_root: str | os.PathLike[str],
    now: datetime | None = None,
) -> Mapping[str, Any]:
    source = Path(path).expanduser()
    try:
        raw = source.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise DevelopmentHardwareAuthorizationError(
            f"Hardware authorization cannot be read: {exc}"
        ) from exc
    required = {
        "schema_name", "schema_version", "authorization_id", "status", "action",
        "operator", "issued_at_utc", "expires_at_utc", "expected_commit",
        "development_store_id", "development_machine_data_root",
        "firmware_state_path", "firmware_state_sha256", "firmware_role",
        "firmware_source_commit", "firmware_artifact_sha256",
        "released_artifact_sha256", "attended_confirmation_sha256",
        "clear_envelope_confirmation_sha256",
    }
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise DevelopmentHardwareAuthorizationError("Authorization schema fields are invalid.")
    try:
        UUID(str(payload["authorization_id"]))
        UUID(str(payload["development_store_id"]))
    except ValueError as exc:
        raise DevelopmentHardwareAuthorizationError("Authorization IDs are invalid.") from exc
    current = (now or _utc_now()).astimezone(timezone.utc)
    issued = _parse_time(payload["issued_at_utc"], "issued time")
    expires = _parse_time(payload["expires_at_utc"], "expiry")
    expected_root = Path(development_machine_data_root).expanduser().resolve()
    if not _is_hex(payload.get("expected_commit"), 40) or any(
        not _is_hex(payload.get(name), 64)
        for name in (
            "firmware_state_sha256", "firmware_artifact_sha256",
            "released_artifact_sha256", "attended_confirmation_sha256",
            "clear_envelope_confirmation_sha256",
        )
    ):
        raise DevelopmentHardwareAuthorizationError(
            "Authorization commit or SHA-256 binding is invalid."
        )
    if (
        payload["schema_name"] != SCHEMA_NAME
        or payload["schema_version"] != SCHEMA_VERSION
        or payload["status"] != "authorized"
        or payload["action"] != "hardware-development-launch"
        or payload["operator"] != str(operator).strip()
        or payload["expected_commit"] != expected_commit
        or payload["development_store_id"] != development_store_id
        or Path(payload["development_machine_data_root"]).resolve() != expected_root
        or issued > current
        or expires <= current
        or (expires - issued).total_seconds() > 600
        or payload["attended_confirmation_sha256"] != confirmation_sha256(ATTENDED_CONFIRMATION)
        or payload["clear_envelope_confirmation_sha256"]
        != confirmation_sha256(CLEAR_ENVELOPE_CONFIRMATION)
    ):
        raise DevelopmentHardwareAuthorizationError(
            "Hardware authorization does not match this exact attended launch."
        )
    state_path = Path(payload["firmware_state_path"]).expanduser()
    if not state_path.is_absolute() or not state_path.is_file():
        raise DevelopmentHardwareAuthorizationError("Authorized firmware state is unavailable.")
    if _sha(state_path) != payload["firmware_state_sha256"]:
        raise DevelopmentHardwareAuthorizationError(
            "Firmware state changed after hardware authorization."
        )
    return payload
