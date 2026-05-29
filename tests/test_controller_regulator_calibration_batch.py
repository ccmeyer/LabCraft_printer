from types import SimpleNamespace

import RegulatorProfiles as rp
from Controller import Controller
from tests.fakes import FakeSignal


class _FakeMachine:
    def __init__(self, calls):
        self.calls = calls
        self.port = "COM7"
        self.baud = 115200
        self.disconnect_complete_signal = FakeSignal()
        self.machine_connected_signal = FakeSignal()
        self.ready_handlers = []

    def set_regulator_recovery_profile(self, channel, recovery, handler=None, kwargs=None, manual=False):
        self.calls.append(("recovery", channel, manual))
        return [SimpleNamespace(command_type="SET_REG_RECOVERY_PROFILE")]

    def set_regulator_slew_profile(self, channel, slew, handler=None, kwargs=None, manual=False):
        self.calls.append(("slew", channel, manual))
        return SimpleNamespace(command_type="SET_REG_SLEW_PROFILE")

    def set_regulator_ready_profile(self, channel, ready, handler=None, kwargs=None, manual=False):
        self.calls.append(("ready", channel, manual))
        if handler is not None:
            self.ready_handlers.append(handler)
        return SimpleNamespace(command_type="SET_REG_READY_PROFILE")

    def restore_regulator_profile(self, channels, source="baseline", handler=None, kwargs=None, manual=False):
        self.calls.append(("restore", tuple(channels), source, manual))
        if handler is not None:
            handler()
        return SimpleNamespace(command_type="RESTORE_REG_PROFILE")


class _FakeTraceWorker:
    def __init__(self, prepared, calls, ok_sequence):
        self.prepared = prepared
        self.calls = calls
        self.ok_sequence = ok_sequence
        self.stage = FakeSignal()
        self.output = FakeSignal()
        self.run_finished = FakeSignal()
        self._running = False
        self.cancel_called = False

    def isRunning(self):
        return self._running

    def cancel(self):
        self.cancel_called = True
        self.calls.append(("trace_cancel", self.prepared.run_id))

    def start(self):
        self._running = True
        ok = self.ok_sequence.pop(0) if self.ok_sequence else True
        self.calls.append(("trace_start", self.prepared.profile_id, self.prepared.run_id))
        trace_file = self.prepared.run_dir / f"{self.prepared.raw_selftest_path.stem}_trace_{self.prepared.trace_case.test_id}.json"
        trace_file.write_text("{}", encoding="utf-8")
        payload = {
            "returncode": 0 if ok else 3,
            "run_dir": str(self.prepared.run_dir),
            "raw_selftest_path": str(self.prepared.raw_selftest_path),
            "trace_files": [trace_file.name],
        }
        self._running = False
        self.run_finished.emit(ok, "trace ok" if ok else "trace failed", payload)


def _document():
    document = rp.factory_default_document()
    stream = document["profiles"]["stream_default"]
    for profile_id in ("stream_candidate_a", "stream_candidate_b"):
        document["profiles"][profile_id] = rp.validate_profile(
            {**stream, "profile_id": profile_id, "description": profile_id}
        )
    return rp.validate_document(document)


def _controller(tmp_path, *, ok_sequence=None, analysis_raises=False):
    calls = []
    machine = _FakeMachine(calls)
    controller = Controller.__new__(Controller)
    controller.machine = machine
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(is_connected=lambda: True),
        regulator_profiles=_document(),
    )
    controller._repo_root = tmp_path
    controller._regulator_calibration_worker = None
    controller._regulator_calibration_state = None
    controller._regulator_calibration_batch_state = None
    controller.regulator_calibration_stage = FakeSignal()
    controller.regulator_calibration_output = FakeSignal()
    controller.regulator_calibration_finished = FakeSignal()
    controller.regulator_calibration_batch_stage = FakeSignal()
    controller.regulator_calibration_batch_output = FakeSignal()
    controller.regulator_calibration_batch_progress = FakeSignal()
    controller.regulator_calibration_batch_finished = FakeSignal()
    controller.check_if_all_completed = lambda: True
    controller.disconnect_machine = lambda: (calls.append(("disconnect",)), machine.disconnect_complete_signal.emit())
    controller.connect_machine = lambda port: (
        calls.append(("connect", port)),
        machine.machine_connected_signal.emit(True),
    )
    sequence = list(ok_sequence if ok_sequence is not None else [True] * 10)

    def factory(prepared, port, baud, repo_root, run_selftest_path):
        return _FakeTraceWorker(prepared, calls, sequence)

    def analysis_runner(prepared):
        calls.append(("analysis", str(prepared.session_dir)))
        if analysis_raises:
            raise RuntimeError("analysis broke")
        return {
            "output_dir": prepared.session_dir / "analysis",
            "candidate_ranking_json": prepared.session_dir / "analysis" / "candidate_ranking.json",
            "candidate_ranking_csv": prepared.session_dir / "analysis" / "candidate_ranking.csv",
            "all_pulses_csv": prepared.session_dir / "analysis" / "all_pulses.csv",
        }

    return controller, machine, calls, factory, analysis_runner


def _config(**overrides):
    config = {
        "mode": "stream",
        "trace_case_id": 2102,
        "candidate_profile_ids": ["stream_candidate_a", "stream_candidate_b"],
        "repeat_count": 1,
        "order_strategy": "alternating",
        "baseline_before": True,
        "baseline_after": True,
        "calibrated_head_confirmed": True,
    }
    config.update(overrides)
    return config


def _drain_ready_handlers(machine):
    while machine.ready_handlers:
        handler = machine.ready_handlers.pop(0)
        handler()


def test_batch_sequences_baseline_candidates_analysis_and_manifest(tmp_path):
    controller, machine, calls, factory, analysis_runner = _controller(tmp_path)
    finished = []
    progress = []
    controller.regulator_calibration_batch_finished.connect(lambda *args: finished.append(args))
    controller.regulator_calibration_batch_progress.connect(lambda *args: progress.append(args))

    assert controller.start_regulator_calibration_batch(
        _config(),
        trace_worker_factory=factory,
        analysis_runner=analysis_runner,
    ) is True
    _drain_ready_handlers(machine)

    trace_starts = [call for call in calls if call[0] == "trace_start"]
    assert [call[1] for call in trace_starts] == [
        "stream_default",
        "stream_candidate_a",
        "stream_candidate_b",
        "stream_default",
    ]
    assert len([call for call in calls if call[0] == "restore"]) == 4
    assert calls[-1][0] == "analysis"
    assert finished[-1][0] is True
    manifest = finished[-1][2]["manifest"]
    assert manifest["outcome"]["status"] == "completed"
    assert [run["status"] for run in manifest["runs"]] == ["completed"] * 4
    assert manifest["analysis"]["candidate_ranking_csv"].endswith("candidate_ranking.csv")
    assert progress[0][0:2] == (1, 4)


def test_batch_fail_fast_on_trace_failure_and_marks_remaining_skipped(tmp_path):
    controller, machine, calls, factory, analysis_runner = _controller(tmp_path, ok_sequence=[True, False, True])
    finished = []
    controller.regulator_calibration_batch_finished.connect(lambda *args: finished.append(args))

    assert controller.start_regulator_calibration_batch(
        _config(),
        trace_worker_factory=factory,
        analysis_runner=analysis_runner,
    ) is True
    _drain_ready_handlers(machine)

    assert finished[-1][0] is False
    manifest = finished[-1][2]["manifest"]
    assert manifest["outcome"]["status"] == "failed"
    assert [run["status"] for run in manifest["runs"]] == ["completed", "failed", "skipped", "skipped"]
    assert not any(call[0] == "analysis" for call in calls)


def test_batch_cancel_during_active_run_restores_and_skips_remaining(tmp_path):
    controller, machine, _calls, factory, analysis_runner = _controller(tmp_path)
    finished = []
    controller.regulator_calibration_batch_finished.connect(lambda *args: finished.append(args))

    assert controller.start_regulator_calibration_batch(
        _config(),
        trace_worker_factory=factory,
        analysis_runner=analysis_runner,
    ) is True
    assert controller.cancel_regulator_calibration_batch() is True
    _drain_ready_handlers(machine)

    assert finished[-1][0] is False
    manifest = finished[-1][2]["manifest"]
    assert manifest["outcome"]["status"] == "canceled"
    assert manifest["runs"][0]["status"] == "canceled"
    assert [run["status"] for run in manifest["runs"][1:]] == ["skipped", "skipped", "skipped"]


def test_batch_analysis_failure_records_analysis_failed(tmp_path):
    controller, machine, _calls, factory, analysis_runner = _controller(tmp_path, analysis_raises=True)
    finished = []
    controller.regulator_calibration_batch_finished.connect(lambda *args: finished.append(args))

    assert controller.start_regulator_calibration_batch(
        _config(candidate_profile_ids=["stream_candidate_a"], baseline_after=False),
        trace_worker_factory=factory,
        analysis_runner=analysis_runner,
    ) is True
    _drain_ready_handlers(machine)

    assert finished[-1][0] is False
    manifest = finished[-1][2]["manifest"]
    assert manifest["outcome"]["status"] == "analysis_failed"
    assert manifest["outcome"]["error_message"] == "analysis broke"


def test_batch_rejects_start_while_single_run_active(tmp_path):
    controller, _machine, _calls, factory, analysis_runner = _controller(tmp_path)
    controller._regulator_calibration_state = {"active": True}

    assert controller.start_regulator_calibration_batch(
        _config(),
        trace_worker_factory=factory,
        analysis_runner=analysis_runner,
    ) is False
