"""Read and validate durable LabCraft firmware-state evidence.

Slice 6 consumes this schema without writing it. Slice 7 owns atomic state
transitions and restoration receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID


SCHEMA_NAME = "labcraft.firmware_state"
SCHEMA_VERSION = 1
ROLES = frozenset({"released", "development", "unknown", "recovery-required"})
SHA256_ZERO = "0" * 64


class FirmwareStateError(RuntimeError):
    """Raised when installed-firmware evidence is absent or unsafe."""


@dataclass(frozen=True)
class FirmwareState:
    path: Path
    sha256: str
    payload: Mapping[str, Any]

    @property
    def role(self) -> str:
        return str(self.payload["role"])


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_commit(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _absolute(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise FirmwareStateError(f"Firmware state {label} is invalid.")
    path = Path(value).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise FirmwareStateError(f"Firmware state {label} must be absolute.")
    return path.resolve(strict=False)


def validate_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    required = {
        "schema_name", "schema_version", "state_revision", "machine_id", "role",
        "source_commit", "artifact_path", "artifact_sha256", "flash_transaction_id",
        "operator", "flashed_at_utc", "verified_at_utc", "updated_at_utc",
        "flash_evidence_path", "flash_evidence_sha256", "safe_evidence_path",
        "safe_evidence_sha256", "previous_known_good_released",
    }
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise FirmwareStateError("Firmware state schema fields are invalid.")
    if payload.get("schema_name") != SCHEMA_NAME or payload.get("schema_version") != SCHEMA_VERSION:
        raise FirmwareStateError("Firmware state schema identity is invalid.")
    if not isinstance(payload.get("state_revision"), int) or payload["state_revision"] < 1:
        raise FirmwareStateError("Firmware state revision is invalid.")
    if not isinstance(payload.get("machine_id"), str) or not payload["machine_id"].strip():
        raise FirmwareStateError("Firmware state machine identity is invalid.")
    role = payload.get("role")
    if role not in ROLES:
        raise FirmwareStateError("Firmware state role is invalid.")
    if not _is_commit(payload.get("source_commit")):
        raise FirmwareStateError("Firmware state source commit is invalid.")
    _absolute(payload.get("artifact_path"), "artifact path")
    if not _is_sha256(payload.get("artifact_sha256")):
        raise FirmwareStateError("Firmware state artifact SHA-256 is invalid.")
    try:
        UUID(str(payload.get("flash_transaction_id")))
    except ValueError as exc:
        raise FirmwareStateError("Firmware state flash transaction ID is invalid.") from exc
    for name in ("operator", "flashed_at_utc", "verified_at_utc", "updated_at_utc"):
        if not isinstance(payload.get(name), str) or not payload[name].strip():
            raise FirmwareStateError(f"Firmware state {name} is invalid.")
    for prefix in ("flash_evidence", "safe_evidence"):
        _absolute(payload.get(f"{prefix}_path"), f"{prefix} path")
        if not _is_sha256(payload.get(f"{prefix}_sha256")):
            raise FirmwareStateError(f"Firmware state {prefix} SHA-256 is invalid.")
    previous = payload.get("previous_known_good_released")
    if not isinstance(previous, Mapping) or set(previous) != {
        "tag", "source_commit", "artifact_path", "artifact_sha256"
    }:
        raise FirmwareStateError("Previous known-good released binding is invalid.")
    if (
        not isinstance(previous.get("tag"), str) or not previous["tag"].startswith("v")
        or not _is_commit(previous.get("source_commit"))
        or not _is_sha256(previous.get("artifact_sha256"))
    ):
        raise FirmwareStateError("Previous known-good released provenance is invalid.")
    _absolute(previous.get("artifact_path"), "previous released artifact path")
    return payload


def load_state(path: str | Path) -> FirmwareState:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise FirmwareStateError("Firmware-state path must be absolute.")
    candidate = candidate.resolve(strict=False)
    try:
        raw = candidate.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise FirmwareStateError(f"Firmware state cannot be read: {exc}") from exc
    validate_payload(payload)
    return FirmwareState(candidate, hashlib.sha256(raw).hexdigest(), payload)


def require_hardware_compatible(
    state: FirmwareState,
    *,
    machine_id: str,
    development_commit: str,
    development_artifact_sha256: str,
    released_artifact_sha256: str,
) -> dict[str, Any]:
    payload = state.payload
    if payload["machine_id"] != machine_id:
        raise FirmwareStateError("Firmware state belongs to a different machine.")
    role = payload["role"]
    if role in {"unknown", "recovery-required"}:
        raise FirmwareStateError(f"Firmware role {role} cannot authorize hardware development.")
    firmware_differs = development_artifact_sha256 != released_artifact_sha256
    if firmware_differs:
        if (
            role != "development"
            or payload["source_commit"] != development_commit
            or payload["artifact_sha256"] != development_artifact_sha256
        ):
            raise FirmwareStateError(
                "Installed development firmware does not match the exact development commit/artifact."
            )
    elif role == "development" and (
        payload["source_commit"] != development_commit
        or payload["artifact_sha256"] != development_artifact_sha256
    ):
        raise FirmwareStateError("Development firmware evidence is stale.")
    elif role == "released" and payload["artifact_sha256"] != released_artifact_sha256:
        raise FirmwareStateError("Released firmware evidence differs from the released artifact.")
    return {
        "status": "compatible",
        "role": role,
        "state_path": str(state.path),
        "state_sha256": state.sha256,
        "source_commit": payload["source_commit"],
        "artifact_sha256": payload["artifact_sha256"],
        "flash_transaction_id": payload["flash_transaction_id"],
        "safe_evidence_sha256": payload["safe_evidence_sha256"],
        "firmware_differs_from_released": firmware_differs,
    }
