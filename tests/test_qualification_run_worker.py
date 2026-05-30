import json
from pathlib import Path
from types import SimpleNamespace

from QualificationRunWorker import QualificationRunWorker


REPO_ROOT = Path(__file__).resolve().parents[1]


def _raw_selftest():
    return {
        "run_id": 1234,
        "profile": "FULL",
        "started_at": "2026-05-15T00:00:00Z",
        "finished_at": "2026-05-15T00:00:05Z",
        "aborted": False,
        "summary": {"total": 1, "passed": 1, "failed": 0},
        "results": [{"test_id": 1001, "name": "comm_crc_known_vector", "pass": True, "metrics": {"crc": 1}}],
        "host_checks": [{"name": "hello_ack", "pass": True, "details": {"seq8": 1}}],
    }


def _raw_gripper_selftest():
    return {
        "run_id": 5678,
        "profile": "FULL",
        "started_at": "2026-05-15T00:00:00Z",
        "finished_at": "2026-05-15T00:05:00Z",
        "aborted": False,
        "summary": {"total": 3, "passed": 3, "failed": 0},
        "results": [
            {"test_id": 2501, "name": "gripper_seal_closed_decay_factory", "pass": True, "metrics": {"drop_raw": 25, "timeout": 0, "pulse_ms": 2000, "tick_us": 100, "reg_pause": 1}},
            {"test_id": 2502, "name": "gripper_seal_hold_duration_factory", "pass": True, "metrics": {"seal_ms": 60000, "drop_raw": 30, "timeout": 0, "reg_pause": 1}},
            {"test_id": 2503, "name": "gripper_seal_repeatability_factory", "pass": True, "metrics": {"repeat_span_raw": 12, "seal_ms_min": 5000, "timeout": 0, "reg_pause": 1}},
        ],
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


def _base_config(tmp_path, manifest_ref):
    return {
        "manifest_ref": str(manifest_ref),
        "port": "COM9",
        "baud": 57600,
        "machine_id": "LC-0001",
        "identity_path": tmp_path / "local" / "machine_identity.json",
        "output_root": tmp_path / "qualification",
        "timeout_ms": 120000,
    }


def _run_worker(worker):
    finished = []
    stages = []
    outputs = []
    worker.stage.connect(stages.append)
    worker.output.connect(outputs.append)
    worker.run_finished.connect(lambda ok, msg, payload: finished.append((ok, msg, payload)))
    worker.run()
    return finished[0], stages, outputs


def _run_worker_with_campaign_events(worker):
    finished = []
    events = []
    worker.campaign_event.connect(events.append)
    worker.run_finished.connect(lambda ok, msg, payload: finished.append((ok, msg, payload)))
    worker.run()
    return finished[0], events


def test_worker_successful_fake_run_emits_final_report(tmp_path):
    invocations = []

    def fake_invoker(invocation):
        invocations.append(invocation)
        invocation.raw_report_path.write_text(json.dumps(_raw_selftest()), encoding="utf-8")
        return 0

    worker = QualificationRunWorker(
        _base_config(tmp_path, _manifest_path(tmp_path)),
        repo_root=REPO_ROOT,
        invoker=fake_invoker,
    )

    (ok, _msg, payload), stages, outputs = _run_worker(worker)

    assert ok is True
    assert Path(payload["report_path"]).exists()
    assert payload["report"]["overall_status"] == "pass"
    assert "Running self-test" in stages
    assert any("Self-test invoker returned 0" in item for item in outputs)
    assert len(invocations) == 1
    assert "--progress-jsonl" in invocations[0].command


def test_worker_missing_raw_report_produces_failure_report(tmp_path):
    worker = QualificationRunWorker(
        _base_config(tmp_path, _manifest_path(tmp_path)),
        repo_root=REPO_ROOT,
        invoker=lambda _invocation: 3,
    )

    (ok, _msg, payload), _stages, _outputs = _run_worker(worker)

    assert ok is False
    assert payload["report"]["overall_status"] == "fail"
    assert payload["report"]["host_checks"][0]["name"] == "selftest_invoker"


def test_worker_gripper_suite_rejects_missing_required_fixture(tmp_path):
    called = False

    def fake_invoker(_invocation):
        nonlocal called
        called = True
        return 0

    config = _base_config(tmp_path, "gripper_seal_v1")
    config["operator_prompts"] = True
    worker = QualificationRunWorker(config, repo_root=REPO_ROOT, invoker=fake_invoker)

    (ok, _msg, payload), _stages, _outputs = _run_worker(worker)

    assert ok is False
    assert called is False
    assert payload["report"]["host_checks"][0]["name"] == "fixture_required"


def test_worker_gripper_prompt_flow_uses_operator_prompts(tmp_path):
    events = []

    def fake_invoker(invocation):
        events.append("self-test")
        invocation.raw_report_path.write_text(json.dumps(_raw_gripper_selftest()), encoding="utf-8")
        return 0

    def fake_prompter(message):
        events.append(f"prompt:{message[:7]}")

    def fake_gripper_control(action, port, baud):
        events.append(f"{action}:{port}:{baud}")
        return 0

    config = _base_config(tmp_path, "gripper_seal_v1")
    config.update({"fixture_id": "dummy_blocked_head_v1", "operator_prompts": True, "timeout_ms": 420000})
    worker = QualificationRunWorker(
        config,
        repo_root=REPO_ROOT,
        invoker=fake_invoker,
        prompter=fake_prompter,
        gripper_control=fake_gripper_control,
    )

    (ok, _msg, payload), _stages, _outputs = _run_worker(worker)

    assert ok is True
    assert payload["report"]["run"]["fixture_id"] == "dummy_blocked_head_v1"
    assert "self-test" in events
    assert events.count("preflight_print:COM9:57600") == 1
    assert [item["stage"] for item in payload["report"]["operator_interactions"]] == [
        "load_dummy_head",
        "confirm_valve_clicks",
        "support_before_release",
        "remove_dummy_head",
    ]


def test_worker_parses_selftest_event_lines(qapp):
    worker = QualificationRunWorker({}, repo_root=REPO_ROOT)
    events = []
    outputs = []
    worker.selftest_event.connect(events.append)
    worker.output.connect(outputs.append)

    worker._handle_selftest_output_line(
        'SELFTEST_EVENT {"schema":"selftest_event_v1","event":"selftest_result","test_id":2007,"pass":true}'
    )
    worker._handle_selftest_output_line("ordinary output")

    assert events == [{"schema": "selftest_event_v1", "event": "selftest_result", "test_id": 2007, "pass": True}]
    assert outputs == ["ordinary output"]


def test_worker_bridges_selftest_operator_prompt_to_subprocess_stdin(qapp):
    class FakeStdin:
        def __init__(self):
            self.writes = []
            self.flushed = False

        def write(self, text):
            self.writes.append(text)

        def flush(self):
            self.flushed = True

    prompts = []
    stdin = FakeStdin()
    worker = QualificationRunWorker(
        {},
        repo_root=REPO_ROOT,
        prompter=lambda message: prompts.append(message),
    )
    worker._active_process = SimpleNamespace(stdin=stdin)
    events = []
    worker.selftest_event.connect(events.append)

    worker._handle_selftest_output_line(
        'SELFTEST_EVENT {"schema":"selftest_event_v1","event":"selftest_operator_prompt","stage":"evap_plate_confirm","message":"Confirm plate"}'
    )

    assert prompts == ["Confirm plate"]
    assert stdin.writes == ["continue\n"]
    assert stdin.flushed is True
    assert events[0]["stage"] == "evap_plate_confirm"


def test_worker_writes_abort_when_selftest_operator_prompt_is_cancelled(qapp):
    class FakeStdin:
        def __init__(self):
            self.writes = []

        def write(self, text):
            self.writes.append(text)

        def flush(self):
            pass

    outputs = []
    stdin = FakeStdin()

    def reject_prompt(_message):
        raise RuntimeError("cancelled")

    worker = QualificationRunWorker({}, repo_root=REPO_ROOT, prompter=reject_prompt)
    worker._active_process = SimpleNamespace(stdin=stdin)
    worker.output.connect(outputs.append)

    worker._handle_selftest_output_line(
        'SELFTEST_EVENT {"schema":"selftest_event_v1","event":"selftest_operator_prompt","stage":"evap_plate_confirm","message":"Confirm plate"}'
    )

    assert stdin.writes == ["abort\n"]
    assert any("Operator prompt cancelled" in item for item in outputs)


def test_worker_malformed_event_line_stays_output(qapp):
    worker = QualificationRunWorker({}, repo_root=REPO_ROOT)
    events = []
    outputs = []
    worker.selftest_event.connect(events.append)
    worker.output.connect(outputs.append)

    worker._handle_selftest_output_line("SELFTEST_EVENT {bad")

    assert events == []
    assert outputs == ["SELFTEST_EVENT {bad"]


def test_campaign_worker_calls_campaign_runner_and_emits_events(tmp_path, qapp):
    campaign_report = tmp_path / "campaign_report.json"
    summary_csv = tmp_path / "campaign_summary.csv"
    child_report = tmp_path / "qualification" / "LC-0001" / "run" / "report.json"
    child_report.parent.mkdir(parents=True)
    child_report.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_campaign_runner(**kwargs):
        captured.update(kwargs)
        callback = kwargs["event_callback"]
        callback({"event": "campaign_started", "campaign_id": "campaign"})
        callback({"event": "campaign_step_started", "step": {"index": 1, "manifest_id": "motion_envelope_v1"}})
        callback(
            {
                "event": "campaign_step_finished",
                "step": {"index": 1, "manifest_id": "motion_envelope_v1"},
                "step_result": {"index": 1, "status": "pass", "report_path": str(child_report)},
                "report": {"overall_status": "pass", "warnings": []},
            }
        )
        callback({"event": "campaign_finished", "status": "pass", "campaign_report_path": str(campaign_report)})
        return SimpleNamespace(
            returncode=0,
            campaign_dir=tmp_path,
            report_path=campaign_report,
            summary_csv_path=summary_csv,
            report={"overall_status": "pass", "steps": [{"report_path": str(child_report)}]},
        )

    worker = QualificationRunWorker(
        {
            "run_kind": "campaign",
            "campaign_ref": "machine_full_qualification_v1",
            "port": "COM9",
            "baud": 57600,
            "machine_id": "LC-0001",
            "identity_path": tmp_path / "local" / "machine_identity.json",
            "campaign_output_root": tmp_path / "campaigns",
            "suite_output_root": tmp_path / "qualification",
            "operator_prompts": True,
            "continue_on_failure": True,
        },
        repo_root=REPO_ROOT,
        campaign_runner=fake_campaign_runner,
    )

    (ok, _msg, payload), events = _run_worker_with_campaign_events(worker)

    assert ok is True
    assert payload["run_kind"] == "campaign"
    assert payload["campaign_report_path"] == str(campaign_report)
    assert payload["report_path"] == str(child_report)
    assert captured["continue_on_failure"] is True
    assert [event["event"] for event in events] == [
        "campaign_started",
        "campaign_step_started",
        "campaign_step_finished",
        "campaign_finished",
    ]


def test_campaign_worker_enriches_selftest_events_with_active_step(qapp):
    worker = QualificationRunWorker({}, repo_root=REPO_ROOT)
    events = []
    worker.selftest_event.connect(events.append)
    worker._handle_campaign_event({"event": "campaign_step_started", "step": {"index": 3, "manifest_id": "valve_characterization_v1"}})
    worker._handle_selftest_output_line(
        'SELFTEST_EVENT {"schema":"selftest_event_v1","event":"selftest_result","test_id":2473,"pass":true}'
    )

    assert events[0]["campaign_step_index"] == 3
    assert events[0]["manifest_id"] == "valve_characterization_v1"
