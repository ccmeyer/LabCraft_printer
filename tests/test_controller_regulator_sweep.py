from types import SimpleNamespace
from pathlib import Path

import RegulatorProfiles as rp
from Controller import Controller
from tests.fakes import FakeSignal


class _FakeStore:
    def __init__(self, document):
        self.document = document
        self.upsert_called = False

    def upsert_profile(self, *_args, **_kwargs):
        self.upsert_called = True
        raise AssertionError("sweep candidates must not be persisted")


class _FakeMachine:
    def __init__(self, calls):
        self.calls = calls
        self.port = "COM7"
        self.baud = 115200
        self.disconnect_complete_signal = FakeSignal()
        self.machine_connected_signal = FakeSignal()
        self.ready_handlers = []

    def set_regulator_recovery_profile(self, channel, recovery, handler=None, kwargs=None, manual=False):
        self.calls.append(("recovery", channel, recovery["active_ticks"], manual))
        return [SimpleNamespace(command_type="SET_REG_RECOVERY_PROFILE")]

    def set_regulator_slew_profile(self, channel, slew, handler=None, kwargs=None, manual=False):
        self.calls.append(("slew", channel, slew["max_hz_delta_up_per_loop"], manual))
        return SimpleNamespace(command_type="SET_REG_SLEW_PROFILE")

    def set_regulator_ready_profile(self, channel, ready, handler=None, kwargs=None, manual=False):
        self.calls.append(("ready", channel, ready["ready_tol_raw"], manual))
        if handler is not None:
            self.ready_handlers.append(handler)
        return SimpleNamespace(command_type="SET_REG_READY_PROFILE")

    def restore_regulator_profile(self, channels, source="baseline", handler=None, kwargs=None, manual=False):
        self.calls.append(("restore", tuple(channels), source, manual))
        if handler is not None:
            handler()
        return SimpleNamespace(command_type="RESTORE_REG_PROFILE")

    def release_serial_for_external_owner(self, reason="external_owner"):
        self.calls.append(("soft_release", reason))
        return True


class _FakeTraceWorker:
    def __init__(self, prepared, calls, *, ok=True, skip_goodbye=False):
        self.prepared = prepared
        self.calls = calls
        self.ok = ok
        self.skip_goodbye = skip_goodbye
        self.stage = FakeSignal()
        self.output = FakeSignal()
        self.run_finished = FakeSignal()
        self._running = False

    def isRunning(self):
        return self._running

    def cancel(self):
        self.calls.append(("trace_cancel", self.prepared.profile_id))

    def start(self):
        self._running = True
        self.calls.append(("trace_start", self.prepared.profile_id, self.skip_goodbye))
        trace_file = self.prepared.run_dir / f"{self.prepared.raw_selftest_path.stem}_trace_{self.prepared.trace_case.test_id}.json"
        trace_file.write_text("{}", encoding="utf-8")
        payload = {
            "returncode": 0 if self.ok else 3,
            "run_dir": str(self.prepared.run_dir),
            "raw_selftest_path": str(self.prepared.raw_selftest_path),
            "trace_files": [trace_file.name],
        }
        self._running = False
        self.run_finished.emit(self.ok, "trace ok" if self.ok else "trace failed", payload)


def _controller(tmp_path, *, trace_ok=True, analysis_raises=False):
    calls = []
    document = rp.factory_default_document()
    store = _FakeStore(document)
    machine = _FakeMachine(calls)
    controller = Controller.__new__(Controller)
    controller.machine = machine
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(is_connected=lambda: True),
        regulator_profiles=document,
        regulator_profile_store=store,
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

    def factory(prepared, port, baud, repo_root, run_selftest_path, *, skip_goodbye=False):
        return _FakeTraceWorker(prepared, calls, ok=trace_ok, skip_goodbye=skip_goodbye)

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

    return controller, machine, calls, factory, analysis_runner, store


def _config(**overrides):
    config = {
        "mode": "stream",
        "baseline_profile_id": "stream_default",
        "trace_case_id": 2102,
        "mutated_channel": "print",
        "calibrated_head_confirmed": True,
        "baseline_before": True,
        "baseline_after": True,
        "repeat_count": 1,
        "order_strategy": "alternating",
        "sweep_strategy": "one_at_a_time",
        "sweep_fields": [
            {"field_path": "recovery.active_ticks", "values": [3, 4]},
            {"field_path": "slew.max_hz_delta_up_per_loop", "values": [800]},
        ],
    }
    config.update(overrides)
    return config


def _drain_ready_handlers(machine):
    while machine.ready_handlers:
        handler = machine.ready_handlers.pop(0)
        handler()


def test_controller_sweep_generates_session_profiles_runs_batch_and_analyzes(tmp_path):
    controller, machine, calls, factory, analysis_runner, store = _controller(tmp_path)
    finished = []
    controller.regulator_calibration_batch_finished.connect(lambda *args: finished.append(args))

    assert controller.start_regulator_calibration_sweep(
        _config(),
        trace_worker_factory=factory,
        analysis_runner=analysis_runner,
    ) is True
    _drain_ready_handlers(machine)

    trace_starts = [call for call in calls if call[0] == "trace_start"]
    assert [call[1] for call in trace_starts] == [
        "stream_default",
        "stream_default_sweep_001",
        "stream_default_sweep_002",
        "stream_default_sweep_003",
        "stream_default",
    ]
    assert {call[2] for call in trace_starts} == {True}
    assert store.upsert_called is False
    assert calls[-1][0] == "analysis"
    assert finished[-1][0] is True
    manifest = finished[-1][2]["manifest"]
    assert manifest["outcome"]["status"] == "completed"
    assert manifest["sweep"]["generated_candidate_ids"] == [
        "stream_default_sweep_001",
        "stream_default_sweep_002",
        "stream_default_sweep_003",
    ]
    session_dir = Path(finished[-1][2]["session_dir"])
    assert (session_dir / "sweep_manifest.json").exists()
    assert (session_dir / "sweep_profiles.json").exists()

    recovery_calls = [call for call in calls if call[0] == "recovery"]
    assert [call[2] for call in recovery_calls[:4]] == [2, 3, 4, 2]


def test_controller_sweep_rejects_invalid_config_without_starting_batch(tmp_path):
    controller, _machine, calls, factory, analysis_runner, _store = _controller(tmp_path)
    outputs = []
    controller.regulator_calibration_batch_output.connect(lambda msg: outputs.append(msg))

    assert controller.start_regulator_calibration_sweep(
        _config(sweep_fields=[{"field_path": "recovery.active_ticks", "values": [99]}]),
        trace_worker_factory=factory,
        analysis_runner=analysis_runner,
    ) is False

    assert calls == []
    assert "outside" in outputs[-1]


def test_controller_sweep_analysis_failure_records_analysis_failed(tmp_path):
    controller, machine, _calls, factory, analysis_runner, _store = _controller(tmp_path, analysis_raises=True)
    finished = []
    controller.regulator_calibration_batch_finished.connect(lambda *args: finished.append(args))

    assert controller.start_regulator_calibration_sweep(
        _config(sweep_fields=[{"field_path": "recovery.active_ticks", "values": [3]}]),
        trace_worker_factory=factory,
        analysis_runner=analysis_runner,
    ) is True
    _drain_ready_handlers(machine)

    assert finished[-1][0] is False
    assert finished[-1][2]["manifest"]["outcome"]["status"] == "analysis_failed"
    assert "sweep" in finished[-1][2]["manifest"]
