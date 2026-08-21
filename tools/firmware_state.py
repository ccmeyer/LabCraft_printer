"""Read and validate durable LabCraft firmware-state evidence.

Slice 6 consumes this schema without writing it. Slice 7 owns atomic state
transitions and restoration receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import os
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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    from uuid import uuid4

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4()}.tmp"
    data = json.dumps(dict(payload), indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def transition_state(
    path: str | Path,
    *,
    role: str,
    machine_id: str,
    source_commit: str,
    artifact_path: str | Path,
    artifact_sha256: str,
    flash_transaction_id: str,
    operator: str,
    flash_evidence_path: str | Path,
    safe_evidence_path: str | Path,
    previous_known_good_released: Mapping[str, Any],
    expected_previous_sha256: str | None = None,
    timestamp: str | None = None,
) -> FirmwareState:
    """Atomically record a verified role transition with stale-write refusal."""

    destination = Path(path).expanduser()
    if not destination.is_absolute():
        raise FirmwareStateError("Firmware-state path must be absolute.")
    destination = destination.resolve(strict=False)
    current = load_state(destination) if destination.exists() else None
    if expected_previous_sha256 is not None and (
        current is None or current.sha256 != expected_previous_sha256
    ):
        raise FirmwareStateError("Firmware state changed before the requested transition.")
    prior_role = current.role if current is not None else None
    allowed = {
        None: {"recovery-required", "released"},
        "released": {"released", "recovery-required"},
        "development": {"development", "recovery-required"},
        "unknown": {"recovery-required"},
        "recovery-required": {"recovery-required", "development", "released"},
    }
    if role not in allowed.get(prior_role, set()):
        raise FirmwareStateError(f"Firmware transition {prior_role!r} -> {role!r} is not allowed.")
    artifact = Path(artifact_path).expanduser().resolve(strict=False)
    flash_evidence = Path(flash_evidence_path).expanduser().resolve(strict=False)
    safe_evidence = Path(safe_evidence_path).expanduser().resolve(strict=False)
    if not artifact.is_file() or _file_sha256(artifact) != artifact_sha256:
        raise FirmwareStateError("Firmware transition artifact bytes do not match.")
    if not flash_evidence.is_file() or not safe_evidence.is_file():
        raise FirmwareStateError("Firmware transition evidence is missing.")
    previous = dict(previous_known_good_released)
    previous_artifact = Path(str(previous.get("artifact_path", ""))).expanduser()
    if (
        not previous_artifact.is_absolute()
        or not previous_artifact.is_file()
        or _file_sha256(previous_artifact.resolve()) != previous.get("artifact_sha256")
    ):
        raise FirmwareStateError("Previous known-good released artifact bytes do not match.")
    moment = timestamp or _utc_now()
    payload = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "state_revision": 1 if current is None else int(current.payload["state_revision"]) + 1,
        "machine_id": str(machine_id),
        "role": role,
        "source_commit": source_commit,
        "artifact_path": str(artifact),
        "artifact_sha256": artifact_sha256,
        "flash_transaction_id": str(UUID(str(flash_transaction_id))),
        "operator": str(operator).strip(),
        "flashed_at_utc": moment,
        "verified_at_utc": moment,
        "updated_at_utc": moment,
        "flash_evidence_path": str(flash_evidence),
        "flash_evidence_sha256": _file_sha256(flash_evidence),
        "safe_evidence_path": str(safe_evidence),
        "safe_evidence_sha256": _file_sha256(safe_evidence),
        "previous_known_good_released": previous,
    }
    validate_payload(payload)
    _atomic_json(destination, payload)
    written = load_state(destination)
    history = destination.parent / "firmware-state-history"
    receipt = history / (
        f"{payload['state_revision']:06d}-{payload['flash_transaction_id']}-{role}.json"
    )
    transition_receipt = {
        "schema_name": "labcraft.firmware_state_transition",
        "schema_version": 1,
        "state_revision": payload["state_revision"],
        "prior_role": prior_role,
        "new_role": role,
        "state_path": str(destination),
        "state_sha256": written.sha256,
        "flash_transaction_id": payload["flash_transaction_id"],
        "operator": payload["operator"],
        "recorded_at_utc": moment,
    }
    _atomic_json(receipt, transition_receipt)
    return written
