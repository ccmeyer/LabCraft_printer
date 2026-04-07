from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import CalibrationManager


class _FakeRecorder:
    def __init__(self, *, active=True):
        self._active = bool(active)
        self.finalized = []
        self.events = []
        self.verdicts = []

    def get_active_run_dir(self):
        return "run_dir" if self._active else None

    def append_event(self, event_type, payload):
        self.events.append((event_type, payload))

    def finalize_run(self, outcome, *, error_message=""):
        self.finalized.append((outcome, error_message))
        self._active = False

    def write_verdict(self, outcome, **kwargs):
        self.verdicts.append((outcome, kwargs))


def test_set_record_mode_enabled_updates_state_and_emits_stage():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr.record_mode_enabled = True
    mgr.calibrationStageChanged = SignalStub()

    mgr.set_record_mode_enabled(False)
    assert mgr.get_record_mode_enabled() is False
    assert mgr.calibrationStageChanged.calls
    assert "disabled" in mgr.calibrationStageChanged.calls[-1][0][0].lower()

    mgr.set_record_mode_enabled(True)
    assert mgr.get_record_mode_enabled() is True
    assert "enabled" in mgr.calibrationStageChanged.calls[-1][0][0].lower()


def test_finalize_process_recording_finalizes_active_run_even_when_disabled():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr.record_mode_enabled = False
    fake = _FakeRecorder(active=True)
    mgr._process_recorder = fake

    mgr._finalize_process_recording("completed", error_message="")

    assert fake.finalized == [("completed", "")]
    # No new event appended while recording is disabled.
    assert fake.events == []


def test_finalize_process_recording_is_idempotent_for_same_run():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr.record_mode_enabled = True
    fake = _FakeRecorder(active=True)
    mgr._process_recorder = fake
    mgr.activeCalibration = type(
        "_Proc",
        (),
        {
            "_recorder_run_dir": "run_dir",
            "_process_recording_finalized": False,
        },
    )()

    mgr._finalize_process_recording("stopped", error_message="Calibration terminated by user")
    mgr._finalize_process_recording("error", error_message="Calibration terminated by user")

    assert fake.finalized == [("stopped", "Calibration terminated by user")]
    assert fake.verdicts == []


def test_stop_requests_graceful_stop_without_finalizing_inline():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._pw_sweep_active = False
    mgr._pw_values = []
    mgr._pw_index = -1
    mgr._cancel_pw_apply_wait = lambda: None
    mgr.clear_pending_process_verdict = lambda **kwargs: None
    mgr.calibration_queue = []
    mgr.calibrationStageChanged = SignalStub()
    mgr.calibrationError = SignalStub()
    mgr.has_open_stream_gravimetric_capture = lambda: False
    fake = _FakeRecorder(active=True)
    mgr._process_recorder = fake
    called = {"reason": None}

    class _Proc:
        def requestGracefulStop(self, reason):
            called["reason"] = reason

    mgr.activeCalibration = _Proc()

    CalibrationManager.stop(mgr)

    assert called["reason"] == "User requested graceful stop"
    assert fake.finalized == []


def test_on_calibration_error_normalizes_user_stop_to_stopped_without_failed_verdict():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr.record_mode_enabled = True
    mgr.calibrationStageChanged = SignalStub()
    mgr.calibrationError = SignalStub()
    mgr._process_recorder = _FakeRecorder(active=True)
    mgr._pending_process_verdict = {"stale": True}
    mgr._build_pending_process_verdict_context = lambda *args, **kwargs: {"unexpected": True}
    mgr._record_stream_capture_process_result = lambda *args, **kwargs: None
    mgr._cleanup_finished_process = lambda process_obj: None
    mgr.has_open_stream_gravimetric_capture = lambda: False
    mgr._mark_stream_capture_terminal_state = lambda **kwargs: None
    mgr.calibration_queue = []
    mgr.activeCalibration = type(
        "_Proc",
        (),
        {
            "_recorder_run_dir": "run_dir",
            "_process_recording_finalized": False,
        },
    )()

    CalibrationManager.onCalibrationError(mgr, "Calibration terminated by user")

    assert mgr._process_recorder.finalized == [("stopped", "Calibration terminated by user")]
    assert mgr._process_recorder.verdicts == []
    assert mgr._pending_process_verdict is None
    assert mgr.activeCalibration is None
    assert mgr.calibrationStageChanged.calls[-1][0][0] == "Calibration stopped"
