import json
from pathlib import Path
from types import SimpleNamespace

from tools.qualification import cli
from tools.qualification.runner import DEFAULT_MANIFEST_REF, default_gripper_control, run_qualification


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
                    "valve_drive": "diagnostic_one_pulse",
                    "pulse_ms": 2000,
                    "tick_us": 100,
                    "bursts": 1,
                    "head_valve_mode": "both",
                    "reg_vent": 0,
                    "reg_pause": 1,
                    "grip": 1,
                    "refresh": 0,
                    "p_drop": 20,
                    "r_drop": 25,
                    "drop_raw": 25,
                    "timeout": 0,
                },
            },
            {
                "test_id": 2502,
                "name": "gripper_seal_hold_duration_factory",
                "pass": True,
                "metrics": {"target_raw": 2512, "valve_drive": "diagnostic_one_pulse", "pulse_ms": 2000, "tick_us": 100, "bursts": 6, "head_valve_mode": "both", "reg_vent": 0, "reg_pause": 1, "seal_ms": 60000, "drop_raw": 30, "timeout": 0},
            },
            {
                "test_id": 2503,
                "name": "gripper_seal_repeatability_factory",
                "pass": True,
                "metrics": {"valve_drive": "diagnostic_one_pulse", "pulse_ms": 2000, "tick_us": 100, "bursts": 3, "reg_pause": 1, "repeat_span_raw": 12, "seal_ms_min": 5000, "timeout": 0},
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


class FakeSerial:
    def __init__(self, inbound: bytes):
        self._buf = bytearray(inbound)
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, n: int) -> bytes:
        if not self._buf:
            return b""
        take = 1 if n > 0 else 0
        out = bytes(self._buf[:take])
        del self._buf[:take]
        return out

    def write(self, data: bytes):
        self.writes.append(bytes(data))
        return len(data)


def _frame(mod, payload: bytes) -> bytes:
    return mod.frame_payload(payload)


def _hello_ack(mod) -> bytes:
    return _frame(mod, bytes([mod.CMD_HELLO_ACK, 0x40]))


def _queue_ack(mod, seq8: int, seq32: int) -> bytes:
    payload = bytearray([mod.CMD_QUEUE_ACK, seq8])
    payload += bytes([mod.TAG_SEQ32, 4]) + seq32.to_bytes(4, "little")
    payload += bytes([mod.TAG_ACK_RESULT, 1, mod.ACK_RESULT_ACCEPTED])
    return _frame(mod, bytes(payload))


def _bye_ack(mod) -> bytes:
    return _frame(mod, bytes([mod.CMD_BYE_ACK, 0x43]))


def _bye_done(mod) -> bytes:
    payload = bytearray([mod.CMD_BYE_DONE, 0x43])
    payload += bytes([mod.TAG_SEQ32, 4]) + (1).to_bytes(4, "little")
    return _frame(mod, bytes(payload))


def _written_commands(mod, serial: FakeSerial):
    commands = []
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if frame:
                commands.append(frame[0])
                break
    return commands


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
    assert "--progress-jsonl" not in command


def test_run_qualification_can_request_progress_jsonl(tmp_path):
    invocations = []

    def fake_invoker(invocation):
        invocations.append(invocation)
        invocation.raw_report_path.write_text(json.dumps(_raw_selftest()), encoding="utf-8")
        return 0

    result = run_qualification(
        manifest_ref=_manifest_path(tmp_path),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        progress_jsonl=True,
        invoker=fake_invoker,
    )

    assert result.returncode == 0
    assert "--progress-jsonl" in invocations[0].command


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


def test_default_gripper_control_preflight_uses_hello_then_print(monkeypatch):
    import tools.run_selftest as mod

    serial = FakeSerial(_hello_ack(mod) + _queue_ack(mod, 0x31, 1))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    rc = default_gripper_control("preflight_print", "/dev/ttyAMA0", 115200)

    assert rc == 0
    assert _written_commands(mod, serial) == [mod.CMD_HELLO, 0x20]


def test_default_gripper_control_shutdown_sends_goodbye(monkeypatch):
    import tools.run_selftest as mod

    serial = FakeSerial(_hello_ack(mod) + _bye_ack(mod) + _bye_done(mod))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    rc = default_gripper_control("shutdown", "/dev/ttyAMA0", 115200)

    assert rc == 0
    assert _written_commands(mod, serial) == [mod.CMD_HELLO, mod.CMD_GOODBYE]


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
        elif "heard or felt" in message:
            events.append("prompt:valves")
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
        events.append(f"machine:{action}:{port}:{baud}")
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
        "machine:preflight_print:/dev/ttyAMA0:115200",
        "machine:preflight_refuel:/dev/ttyAMA0:115200",
        "prompt:valves",
        "self-test",
        "prompt:support",
        "machine:release:/dev/ttyAMA0:115200",
        "prompt:remove",
        "machine:off:/dev/ttyAMA0:115200",
        "machine:shutdown:/dev/ttyAMA0:115200",
    ]
    assert result.report["run"]["fixture_id"] == "dummy_blocked_head_v1"
    assert [item["stage"] for item in result.report["operator_interactions"]] == [
        "load_dummy_head",
        "confirm_valve_clicks",
        "support_before_release",
        "remove_dummy_head",
    ]
    host_checks = {item["name"]: item for item in result.report["host_checks"]}
    assert host_checks["gripper_valve_preflight_print"]["pass"] is True
    assert host_checks["gripper_valve_preflight_refuel"]["pass"] is True
    assert host_checks["gripper_teardown_release"]["pass"] is True
    assert host_checks["gripper_teardown_off"]["pass"] is True
    assert host_checks["gripper_teardown_shutdown"]["pass"] is True


def test_gripper_seal_preflight_failure_aborts_before_selftest(tmp_path):
    events = []

    def fake_invoker(_invocation):
        raise AssertionError("preflight failure should abort before self-test")

    def fake_gripper_control(action, port, baud):
        events.append(action)
        return 3 if action == "preflight_refuel" else 0

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
        prompter=lambda _message: events.append("prompt"),
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 3
    assert events == ["prompt", "preflight_print", "preflight_refuel"]
    host_checks = {item["name"]: item for item in result.report["host_checks"]}
    assert host_checks["gripper_valve_preflight_print"]["pass"] is True
    assert host_checks["gripper_valve_preflight_refuel"]["pass"] is False


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
