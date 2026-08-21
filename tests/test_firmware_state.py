from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "firmware_state", REPO_ROOT / "tools/firmware_state.py"
)
assert SPEC is not None and SPEC.loader is not None
state_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = state_mod
SPEC.loader.exec_module(state_mod)


def state_payload(tmp_path: Path, **updates) -> dict:
    payload = {
        "schema_name": state_mod.SCHEMA_NAME,
        "schema_version": 1,
        "state_revision": 1,
        "machine_id": "LC-001",
        "role": "development",
        "source_commit": "a" * 40,
        "artifact_path": str(tmp_path / "development.bin"),
        "artifact_sha256": "b" * 64,
        "flash_transaction_id": str(uuid4()),
        "operator": "Operator",
        "flashed_at_utc": "2026-08-21T10:00:00Z",
        "verified_at_utc": "2026-08-21T10:01:00Z",
        "updated_at_utc": "2026-08-21T10:01:00Z",
        "flash_evidence_path": str(tmp_path / "flash.json"),
        "flash_evidence_sha256": "c" * 64,
        "safe_evidence_path": str(tmp_path / "safe.json"),
        "safe_evidence_sha256": "d" * 64,
        "previous_known_good_released": {
            "tag": "v1.3.0-rc.5",
            "source_commit": "e" * 40,
            "artifact_path": str(tmp_path / "released.bin"),
            "artifact_sha256": "f" * 64,
        },
    }
    payload.update(updates)
    return payload


def write_state(tmp_path: Path, **updates):
    path = (tmp_path / "firmware-state.json").resolve()
    path.write_text(json.dumps(state_payload(tmp_path, **updates)), encoding="utf-8")
    return state_mod.load_state(path)


def test_exact_development_state_authorizes_different_firmware(tmp_path: Path) -> None:
    state = write_state(tmp_path)
    evidence = state_mod.require_hardware_compatible(
        state, machine_id="LC-001", development_commit="a" * 40,
        development_artifact_sha256="b" * 64,
        released_artifact_sha256="f" * 64,
    )
    assert evidence["status"] == "compatible"
    assert evidence["firmware_differs_from_released"] is True


@pytest.mark.parametrize("role", ["released", "unknown", "recovery-required"])
def test_different_firmware_rejects_non_development_roles(tmp_path: Path, role: str) -> None:
    state = write_state(tmp_path, role=role)
    with pytest.raises(state_mod.FirmwareStateError):
        state_mod.require_hardware_compatible(
            state, machine_id="LC-001", development_commit="a" * 40,
            development_artifact_sha256="b" * 64,
            released_artifact_sha256="f" * 64,
        )


def test_rejects_stale_commit_and_artifact(tmp_path: Path) -> None:
    state = write_state(tmp_path)
    with pytest.raises(state_mod.FirmwareStateError, match="does not match"):
        state_mod.require_hardware_compatible(
            state, machine_id="LC-001", development_commit="9" * 40,
            development_artifact_sha256="8" * 64,
            released_artifact_sha256="f" * 64,
        )


def test_byte_identical_released_firmware_is_compatible(tmp_path: Path) -> None:
    state = write_state(
        tmp_path, role="released", source_commit="e" * 40,
        artifact_sha256="f" * 64,
    )
    evidence = state_mod.require_hardware_compatible(
        state, machine_id="LC-001", development_commit="a" * 40,
        development_artifact_sha256="f" * 64,
        released_artifact_sha256="f" * 64,
    )
    assert evidence["role"] == "released"
    assert evidence["firmware_differs_from_released"] is False


def test_corrupt_or_extra_state_fields_fail_closed(tmp_path: Path) -> None:
    payload = state_payload(tmp_path)
    payload["unexpected"] = True
    with pytest.raises(state_mod.FirmwareStateError, match="schema fields"):
        state_mod.validate_payload(payload)
