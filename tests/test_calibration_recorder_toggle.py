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
