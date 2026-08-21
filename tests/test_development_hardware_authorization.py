from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from uuid import UUID

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "DevelopmentHardwareAuthorization",
    REPO_ROOT / "FreeRTOS-interface/DevelopmentHardwareAuthorization.py",
)
assert SPEC is not None and SPEC.loader is not None
authorization = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(authorization)
NOW = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)
AUTH_ID = UUID("a91f3b4d-99ba-43b4-aa17-6d3633e8c45b")
STORE_ID = "be5f7305-9046-4d62-8f7a-4e493859fc80"


def create(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = (tmp_path / "development-data").resolve()
    root.mkdir()
    state = (tmp_path / "firmware-state.json").resolve()
    state.write_text('{"state":"exact"}\n', encoding="utf-8")
    path = (tmp_path / "authorization.json").resolve()
    authorization.create_authorization(
        path,
        operator="Operator",
        expected_commit="a" * 40,
        development_store_id=STORE_ID,
        development_machine_data_root=root,
        firmware_state_path=state,
        firmware_compatibility={
            "role": "development",
            "source_commit": "a" * 40,
            "artifact_sha256": "b" * 64,
            "released_artifact_sha256": "c" * 64,
        },
        issued_at=NOW,
        uuid_factory=lambda: AUTH_ID,
    )
    return path, root, state


def test_short_lived_exact_authorization_passes(tmp_path: Path) -> None:
    path, root, _state = create(tmp_path)
    payload = authorization.validate_authorization(
        path, operator="Operator", expected_commit="a" * 40,
        development_store_id=STORE_ID, development_machine_data_root=root,
        now=NOW + timedelta(seconds=1),
    )
    assert payload["authorization_id"] == str(AUTH_ID)
    assert payload["attended_confirmation_sha256"] == authorization.confirmation_sha256(
        authorization.ATTENDED_CONFIRMATION
    )


@pytest.mark.parametrize(
    ("operator", "commit", "store"),
    [
        ("Wrong", "a" * 40, STORE_ID),
        ("Operator", "9" * 40, STORE_ID),
        ("Operator", "a" * 40, "fb17bf6b-3cc2-4c10-b033-af4855d6f07e"),
    ],
)
def test_identity_mismatch_fails_closed(
    tmp_path: Path, operator: str, commit: str, store: str
) -> None:
    path, root, _state = create(tmp_path)
    with pytest.raises(
        authorization.DevelopmentHardwareAuthorizationError, match="does not match"
    ):
        authorization.validate_authorization(
            path, operator=operator, expected_commit=commit,
            development_store_id=store, development_machine_data_root=root,
            now=NOW + timedelta(seconds=1),
        )


def test_expired_authorization_fails_closed(tmp_path: Path) -> None:
    path, root, _state = create(tmp_path)
    with pytest.raises(authorization.DevelopmentHardwareAuthorizationError):
        authorization.validate_authorization(
            path, operator="Operator", expected_commit="a" * 40,
            development_store_id=STORE_ID, development_machine_data_root=root,
            now=NOW + timedelta(minutes=6),
        )


def test_firmware_state_change_revokes_authorization(tmp_path: Path) -> None:
    path, root, state = create(tmp_path)
    state.write_text('{"state":"changed"}\n', encoding="utf-8")
    with pytest.raises(
        authorization.DevelopmentHardwareAuthorizationError,
        match="changed after",
    ):
        authorization.validate_authorization(
            path, operator="Operator", expected_commit="a" * 40,
            development_store_id=STORE_ID, development_machine_data_root=root,
            now=NOW + timedelta(seconds=1),
        )


def test_tampered_confirmation_hash_is_rejected(tmp_path: Path) -> None:
    path, root, _state = create(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["clear_envelope_confirmation_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(authorization.DevelopmentHardwareAuthorizationError):
        authorization.validate_authorization(
            path, operator="Operator", expected_commit="a" * 40,
            development_store_id=STORE_ID, development_machine_data_root=root,
            now=NOW + timedelta(seconds=1),
        )
