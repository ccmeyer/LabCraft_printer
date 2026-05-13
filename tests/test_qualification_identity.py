import json

import pytest

from tools.qualification.artifacts import create_run_artifacts, sanitize_machine_id
from tools.qualification.identity import load_or_create_identity


def test_identity_creation_and_reuse(tmp_path):
    identity_path = tmp_path / "local" / "machine_identity.json"

    first = load_or_create_identity(
        identity_path,
        machine_id="LC-0001",
        now_fn=lambda: "2026-05-13T00:00:00Z",
        uuid_fn=lambda: "uuid-1",
    )
    second = load_or_create_identity(
        identity_path,
        machine_id="LC-9999",
        now_fn=lambda: "2026-05-14T00:00:00Z",
        uuid_fn=lambda: "uuid-2",
    )

    assert first == second
    assert first["machine_id"] == "LC-0001"
    assert first["machine_uuid"] == "uuid-1"
    assert json.loads(identity_path.read_text(encoding="utf-8"))["machine_id"] == "LC-0001"


def test_identity_defaults_to_unassigned_machine_id(tmp_path):
    identity = load_or_create_identity(
        tmp_path / "local" / "machine_identity.json",
        now_fn=lambda: "2026-05-13T00:00:00Z",
        uuid_fn=lambda: "uuid-1",
    )

    assert identity["machine_id"] == "LC-UNASSIGNED"


def test_identity_rejects_invalid_existing_file(tmp_path):
    identity_path = tmp_path / "local" / "machine_identity.json"
    identity_path.parent.mkdir()
    identity_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="machine_id"):
        load_or_create_identity(identity_path)


def test_create_run_artifacts_sanitizes_machine_id_and_handles_collisions(tmp_path):
    first = create_run_artifacts(
        "LC 0001/$bad",
        output_root=tmp_path / "qualification",
        timestamp="20260513T120000Z",
    )
    second = create_run_artifacts(
        "LC 0001/$bad",
        output_root=tmp_path / "qualification",
        timestamp="20260513T120000Z",
    )

    assert sanitize_machine_id("LC 0001/$bad") == "LC_0001_bad"
    assert first.run_dir.name == "20260513T120000Z"
    assert second.run_dir.name == "20260513T120000Z_001"
    assert first.raw_selftest_path.name == "raw_selftest.json"
    assert first.report_path.name == "report.json"
    assert first.summary_csv_path.name == "summary.csv"
