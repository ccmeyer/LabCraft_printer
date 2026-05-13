import json
from pathlib import Path

from tools.qualification import cli
from tools.qualification.runner import run_qualification


def _raw_selftest():
    return {
        "run_id": 1234,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:00:05Z",
        "aborted": False,
        "summary": {"total": 1, "passed": 1, "failed": 0},
        "results": [{"test_id": 1001, "name": "comm_crc_known_vector", "pass": True, "metrics": {"crc": 1}}],
        "host_checks": [{"name": "hello_ack", "pass": True, "details": {"seq8": 1}}],
    }


def _manifest_path(tmp_path):
    path = tmp_path / "unit_manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "qualification_manifest_v0",
                "manifest_id": "unit_manifest",
                "name": "Unit Manifest",
                "profile": "FULL",
                "expected_test_ids": [1001],
                "analysis_rules": {"1001": {"category": "protocol", "failure_domain": "infrastructure"}},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_run_qualification_wraps_fake_selftest_invoker(tmp_path):
    invocations = []

    def fake_invoker(invocation):
        invocations.append(invocation)
        invocation.raw_report_path.write_text(json.dumps(_raw_selftest()), encoding="utf-8")
        return 0

    result = run_qualification(
        manifest_ref=_manifest_path(tmp_path),
        port="COM9",
        baud=57600,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=120000,
        invoker=fake_invoker,
    )

    assert result.returncode == 0
    assert result.report["overall_status"] == "pass"
    assert result.raw_selftest_path.exists()
    assert result.report_path.exists()
    assert result.summary_csv_path.exists()
    assert len(invocations) == 1
    command = invocations[0].command
    assert "--port" in command
    assert "COM9" in command
    assert "--baud" in command
    assert "57600" in command
    assert "--profile" in command
    assert "FULL" in command
    assert str(result.raw_selftest_path) in command


def test_run_qualification_writes_failure_report_when_raw_missing(tmp_path):
    result = run_qualification(
        manifest_ref=_manifest_path(tmp_path),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        invoker=lambda _invocation: 3,
    )

    assert result.returncode == 3
    assert result.report["overall_status"] == "fail"
    raw = json.loads(result.raw_selftest_path.read_text(encoding="utf-8"))
    assert raw["aborted"] is True
    assert raw["host_checks"][0]["name"] == "selftest_invoker"


def test_qualification_cli_accepts_fake_invoker(tmp_path, capsys):
    def fake_invoker(invocation):
        invocation.raw_report_path.write_text(json.dumps(_raw_selftest()), encoding="utf-8")
        return 0

    rc = cli.main(
        [
            "--manifest",
            str(_manifest_path(tmp_path)),
            "--machine-id",
            "LC-0001",
            "--identity-path",
            str(tmp_path / "local" / "machine_identity.json"),
            "--output-root",
            str(tmp_path / "qualification"),
            "--run-selftest-path",
            str(Path("tools") / "run_selftest.py"),
        ],
        invoker=fake_invoker,
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "Wrote qualification report" in captured.out


def test_qualification_can_convert_existing_raw_report_without_invoker(tmp_path):
    raw_path = tmp_path / "existing_raw.json"
    raw_path.write_text(json.dumps(_raw_selftest()), encoding="utf-8")
    called = False

    def fake_invoker(_invocation):
        nonlocal called
        called = True
        return 99

    result = run_qualification(
        manifest_ref=_manifest_path(tmp_path),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        raw_report_path=raw_path,
        invoker=fake_invoker,
    )

    assert result.returncode == 0
    assert called is False
    assert result.raw_selftest_path.read_text(encoding="utf-8") == raw_path.read_text(encoding="utf-8")
    assert result.report["schema_version"] == "qualification_report_v1"


def test_qualification_cli_raw_report_skips_invoker(tmp_path):
    raw_path = tmp_path / "existing_raw.json"
    raw_path.write_text(json.dumps(_raw_selftest()), encoding="utf-8")

    def fake_invoker(_invocation):
        raise AssertionError("raw report conversion should not invoke hardware self-test")

    rc = cli.main(
        [
            "--manifest",
            str(_manifest_path(tmp_path)),
            "--machine-id",
            "LC-0001",
            "--identity-path",
            str(tmp_path / "local" / "machine_identity.json"),
            "--output-root",
            str(tmp_path / "qualification"),
            "--raw-report",
            str(raw_path),
        ],
        invoker=fake_invoker,
    )

    assert rc == 0


def test_gitignore_excludes_local_identity():
    text = Path(".gitignore").read_text(encoding="utf-8")

    assert "local/" in text
