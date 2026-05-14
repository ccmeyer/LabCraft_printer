import json
from pathlib import Path

from tools.qualification import cli
from tools.qualification.runner import DEFAULT_MANIFEST_REF, run_qualification


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


def _raw_gripper_selftest():
    return {
        "run_id": 5678,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:05:00Z",
        "aborted": False,
        "summary": {"total": 3, "passed": 3, "failed": 0},
        "results": [
            {
                "test_id": 2501,
                "name": "gripper_seal_closed_decay_factory",
                "pass": True,
                "metrics": {
                    "target_psi_milli": 1000,
                    "target_raw": 2512,
                    "head_valve_mode": "both",
                    "head_valve_active": 1,
                    "reg_vent": 0,
                    "gripper_close_count": 1,
                    "refresh": 0,
                    "drop_raw": 20,
                    "slope_raw_min": 40,
                    "timeout": 0,
                },
            },
            {
                "test_id": 2502,
                "name": "gripper_seal_hold_duration_factory",
                "pass": True,
                "metrics": {"target_raw": 2512, "head_valve_mode": "both", "reg_vent": 0, "seal_ms": 60000, "drop_raw": 30, "timeout": 0},
            },
            {
                "test_id": 2503,
                "name": "gripper_seal_repeatability_factory",
                "pass": True,
                "metrics": {"repeat_span_raw": 12, "seal_ms_min": 5000, "timeout": 0},
            },
        ],
        "host_checks": [
            {"name": "hello_ack", "pass": True, "details": {"seq8": 1}},
            {"name": "goodbye_skipped", "pass": True, "details": {"reason": "operator_gated_gripper_teardown"}},
        ],
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


def _gripper_manifest_ref():
    return "gripper_seal_v1"


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


def test_default_qualification_manifest_is_factory_acceptance_v3():
    assert DEFAULT_MANIFEST_REF == "factory_acceptance_v3"
    parser = cli.build_parser()
    args = parser.parse_args([])

    assert args.manifest == "factory_acceptance_v3"
    gripper_args = parser.parse_args([
        "--manifest",
        "gripper_seal_v1",
        "--fixture",
        "dummy_blocked_head_v1",
        "--operator-prompts",
    ])
    assert gripper_args.manifest == "gripper_seal_v1"
    assert gripper_args.fixture == "dummy_blocked_head_v1"
    assert gripper_args.operator_prompts is True


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


def test_gripper_seal_manifest_rejects_hardware_run_without_operator_prompts(tmp_path):
    called = False

    def fake_invoker(_invocation):
        nonlocal called
        called = True
        return 0

    result = run_qualification(
        manifest_ref=_gripper_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        fixture_id="dummy_blocked_head_v1",
        operator_prompts=False,
        invoker=fake_invoker,
    )

    assert result.returncode == 3
    assert called is False
    assert result.report["overall_status"] == "fail"
    assert result.report["host_checks"][0]["name"] == "operator_prompts_required"


def test_gripper_seal_manifest_rejects_missing_required_fixture(tmp_path):
    result = run_qualification(
        manifest_ref=_gripper_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        operator_prompts=True,
        invoker=lambda _invocation: 0,
        prompter=lambda _message: None,
    )

    assert result.returncode == 3
    assert result.report["host_checks"][0]["name"] == "fixture_required"
    assert result.report["host_checks"][0]["details"]["allowed_fixture_ids"] == ["dummy_blocked_head_v1"]


def test_gripper_seal_operator_prompt_order_and_teardown(tmp_path):
    events = []

    def fake_prompter(message):
        if "Load" in message:
            events.append("prompt:load")
        elif "Support" in message:
            events.append("prompt:support")
        elif "Remove" in message:
            events.append("prompt:remove")
        else:
            events.append(f"prompt:{message}")

    def fake_invoker(invocation):
        events.append("self-test")
        assert "--gripper-seal-suite" in invocation.command
        invocation.raw_report_path.write_text(json.dumps(_raw_gripper_selftest()), encoding="utf-8")
        return 0

    def fake_gripper_control(action, port, baud):
        events.append(f"gripper:{action}:{port}:{baud}")
        return 0

    result = run_qualification(
        manifest_ref=_gripper_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=420000,
        fixture_id="dummy_blocked_head_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=fake_prompter,
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 0
    assert events == [
        "prompt:load",
        "self-test",
        "prompt:support",
        "gripper:release:/dev/ttyAMA0:115200",
        "prompt:remove",
        "gripper:off:/dev/ttyAMA0:115200",
    ]
    assert result.report["run"]["fixture_id"] == "dummy_blocked_head_v1"
    assert [item["stage"] for item in result.report["operator_interactions"]] == [
        "load_dummy_head",
        "support_before_release",
        "remove_dummy_head",
    ]
    host_checks = {item["name"]: item for item in result.report["host_checks"]}
    assert host_checks["gripper_teardown_release"]["pass"] is True
    assert host_checks["gripper_teardown_off"]["pass"] is True


def test_gripper_seal_raw_report_conversion_skips_prompts_and_invoker(tmp_path):
    raw_path = tmp_path / "gripper_raw.json"
    raw_path.write_text(json.dumps(_raw_gripper_selftest()), encoding="utf-8")
    called = False

    def fake_invoker(_invocation):
        nonlocal called
        called = True
        return 99

    result = run_qualification(
        manifest_ref=_gripper_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        raw_report_path=raw_path,
        fixture_id="dummy_blocked_head_v1",
        operator_prompts=False,
        invoker=fake_invoker,
        prompter=lambda _message: (_ for _ in ()).throw(AssertionError("raw conversion should not prompt")),
    )

    assert result.returncode == 0
    assert called is False
    assert result.report["run"]["fixture_id"] == "dummy_blocked_head_v1"
    assert result.report["operator_interactions"] == []


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
