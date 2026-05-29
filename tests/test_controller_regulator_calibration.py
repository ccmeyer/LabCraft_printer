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
    def __init__(self, prepared, calls, *, ok=True):
        self.prepared = prepared
        self.calls = calls
        self.ok = ok
        self.stage = FakeSignal()
        self.output = FakeSignal()
        self.run_finished = FakeSignal()
        self._running = False
        self.cancel_called = False

    def isRunning(self):
        return self._running

    def cancel(self):
        self.cancel_called = True
        self.calls.append(("trace_cancel",))

    def start(self):
        self._running = True
        self.calls.append(("trace_start", self.prepared.trace_case.test_id))
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


def _controller(tmp_path, *, trace_ok=True, reconnect_ok=True):
    calls = []
    machine = _FakeMachine(calls)
    controller = Controller.__new__(Controller)
    controller.machine = machine
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(is_connected=lambda: True),
        regulator_profiles=rp.factory_default_document(),
    )
    controller._repo_root = tmp_path
    controller._regulator_calibration_worker = None
    controller._regulator_calibration_state = None
    controller.regulator_calibration_stage = FakeSignal()
    controller.regulator_calibration_output = FakeSignal()
    controller.regulator_calibration_finished = FakeSignal()
    controller.check_if_all_completed = lambda: True
    controller.disconnect_machine = lambda: (calls.append(("disconnect",)), machine.disconnect_complete_signal.emit())
    controller.connect_machine = lambda port: (
        calls.append(("connect", port)),
        machine.machine_connected_signal.emit(reconnect_ok),
    )

    def factory(prepared, port, baud, repo_root, run_selftest_path):
        return _FakeTraceWorker(prepared, calls, ok=trace_ok)

    return controller, machine, calls, factory


def _config(**overrides):
    config = {
        "profile_id": "stream_default",
        "mode": "stream",
        "trace_case_id": 2102,
        "calibrated_head_confirmed": True,
    }
    config.update(overrides)
    return config


def test_controller_sequences_apply_trace_reconnect_and_restore(tmp_path):
    controller, machine, calls, factory = _controller(tmp_path)
    finished = []
    controller.regulator_calibration_finished.connect(lambda *args: finished.append(args))

    assert controller.start_regulator_calibration_run(_config(), trace_worker_factory=factory) is True
    assert calls[:3] == [
        ("recovery", "print", True),
        ("slew", "print", True),
        ("ready", "print", True),
    ]

    machine.ready_handlers[-1]()

    assert calls[3:] == [
        ("disconnect",),
        ("trace_start", 2102),
        ("connect", "COM7"),
        ("restore", ("print",), "baseline", True),
    ]
    assert finished[-1][0] is True
    payload = finished[-1][2]
    assert payload["trace_case_id"] == 2102
    assert payload["metadata"]["outcome"]["restored_previous_profile"] is True


def test_controller_restores_after_trace_failure(tmp_path):
    controller, machine, calls, factory = _controller(tmp_path, trace_ok=False)
    finished = []
    controller.regulator_calibration_finished.connect(lambda *args: finished.append(args))

    assert controller.start_regulator_calibration_run(_config(), trace_worker_factory=factory) is True
    machine.ready_handlers[-1]()

    assert ("restore", ("print",), "baseline", True) in calls
    assert finished[-1][0] is False
    assert finished[-1][2]["metadata"]["outcome"]["status"] == "failed"
    assert finished[-1][2]["metadata"]["outcome"]["restored_previous_profile"] is True


def test_controller_cancel_after_candidate_apply_skips_trace_and_restores(tmp_path):
    controller, machine, calls, factory = _controller(tmp_path)
    finished = []
    controller.regulator_calibration_finished.connect(lambda *args: finished.append(args))

    assert controller.start_regulator_calibration_run(_config(), trace_worker_factory=factory) is True
    assert controller.cancel_regulator_calibration_run() is True
    machine.ready_handlers[-1]()

    assert not any(call[0] == "trace_start" for call in calls)
    assert ("restore", ("print",), "baseline", True) in calls
    assert finished[-1][2]["metadata"]["outcome"]["status"] == "canceled"


def test_controller_reconnect_failure_records_restore_failed(tmp_path):
    controller, machine, calls, factory = _controller(tmp_path, reconnect_ok=False)
    finished = []
    controller.regulator_calibration_finished.connect(lambda *args: finished.append(args))

    assert controller.start_regulator_calibration_run(_config(), trace_worker_factory=factory) is True
    machine.ready_handlers[-1]()

    assert not any(call[0] == "restore" for call in calls)
    assert finished[-1][0] is False
    assert finished[-1][2]["metadata"]["outcome"]["status"] == "restore_failed"
    assert finished[-1][2]["metadata"]["outcome"]["restored_previous_profile"] is False


def test_controller_rejects_invalid_start_without_queueing(tmp_path):
    controller, _machine, calls, factory = _controller(tmp_path)

    assert controller.start_regulator_calibration_run(
        _config(calibrated_head_confirmed=False),
        trace_worker_factory=factory,
    ) is False
    assert calls == []
