import csv
import json

from tools.qualification.artifacts import create_run_artifacts
from tools.qualification.identity import load_or_create_identity
from tools.qualification.manifest import load_manifest
from tools.qualification.report import normalize_report, write_qualification_artifacts


def _raw_selftest():
    return {
        "run_id": 1234,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:00:05Z",
        "aborted": False,
        "summary": {"total": 1, "passed": 1, "failed": 0},
        "results": [
            {
                "test_id": 1001,
                "name": "comm_crc_known_vector",
                "pass": True,
                "metrics": {"crc": 19255},
            }
        ],
        "host_checks": [
            {
                "name": "hello_ack",
                "pass": True,
                "details": {"seq8": 1},
            }
        ],
    }


def _identity(tmp_path):
    return load_or_create_identity(
        tmp_path / "local" / "machine_identity.json",
        machine_id="LC-0001",
        now_fn=lambda: "2026-05-13T00:00:00Z",
        uuid_fn=lambda: "uuid-1",
    )


def test_normalize_report_preserves_raw_summary_and_rows(tmp_path):
    manifest = load_manifest("factory_acceptance_v0")
    artifacts = create_run_artifacts("LC-0001", output_root=tmp_path, timestamp="20260513T120000Z")

    report = normalize_report(_raw_selftest(), manifest, _identity(tmp_path), artifacts)

    assert report["schema_version"] == "qualification_report_v0"
    assert report["overall_status"] == "pass"
    assert report["raw_summary"] == {"total": 1, "passed": 1, "failed": 0}
    assert report["results"][0]["test_id"] == 1001
    assert report["host_checks"][0]["name"] == "hello_ack"
    assert 2006 in report["manifest_checks"]["missing_test_ids"]
    assert report["manifest_checks"]["enforced"] is False


def test_write_qualification_artifacts_writes_json_and_summary_csv(tmp_path):
    manifest = load_manifest("factory_acceptance_v0")
    artifacts = create_run_artifacts("LC-0001", output_root=tmp_path, timestamp="20260513T120000Z")

    report = write_qualification_artifacts(_raw_selftest(), manifest, _identity(tmp_path), artifacts)

    assert artifacts.raw_selftest_path.exists()
    assert artifacts.report_path.exists()
    assert artifacts.summary_csv_path.exists()
    assert json.loads(artifacts.report_path.read_text(encoding="utf-8"))["schema_version"] == "qualification_report_v0"
    assert report["machine"]["machine_id"] == "LC-0001"

    rows = list(csv.DictReader(artifacts.summary_csv_path.open(newline="", encoding="utf-8")))
    assert [row["item_kind"] for row in rows] == ["firmware_result", "host_check"]
    assert rows[0]["machine_id"] == "LC-0001"
    assert rows[0]["manifest_id"] == "factory_acceptance_v0"
    assert rows[0]["item_id"] == "1001"
    assert json.loads(rows[0]["payload_json"]) == {"crc": 19255}
