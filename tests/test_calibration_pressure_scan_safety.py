from types import SimpleNamespace

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

import CalibrationClasses.Model as calibration_model
from CalibrationClasses.Model import PressureBandCalibrationProcess


class _DummyState:
    def __init__(self, *args, **kwargs):
        self.entered = SignalStub()
        self.transitions = []

    def addTransition(self, *args, **kwargs):
        self.transitions.append((args, kwargs))
        return None


class _DummyStateMachine:
    def __init__(self, *args, **kwargs):
        self.states = []
        self.initial = None

    def addState(self, st):
        self.states.append(st)

    def setInitialState(self, st):
        self.initial = st

    def start(self):
        return None

    def stop(self):
        return None


def _build_inputs():
    cm = SimpleNamespace(
        get_start_pressure=lambda: 0.9,
        get_nozzle_center=lambda: {"X": 1, "Y": 2, "Z": 3},
        get_nozzle_center_image_position=lambda: (100, 100),
        get_background_image=lambda: object(),
        get_emergence_time=lambda: 1500,
        get_current_settings=lambda: {
            "num_droplets": 7,
            "flash_delay": 4321,
            "print_pressure": 0.88,
            "print_width": 1600,
        },
        settingsChangeCompleted=SignalStub(),
        captureCompleted=SignalStub(),
        changeSettingsRequested=SignalStub(),
        emitSettingsChangeCompleted=lambda: None,
    )
    model = SimpleNamespace(
        machine_model=SimpleNamespace(
            get_print_pulse_width=lambda: 1800,
            get_print_pressure_bounds=lambda: (0.3, 2.0),
        ),
        droplet_camera_model=SimpleNamespace(),
    )
    return cm, model


def test_pressure_scan_constructor_honors_auto_stop_on_nozzle_wet_flag(monkeypatch):
    monkeypatch.setattr(calibration_model, "QState", _DummyState)
    monkeypatch.setattr(calibration_model, "QFinalState", _DummyState)
    monkeypatch.setattr(calibration_model, "QStateMachine", _DummyStateMachine)
    monkeypatch.setattr(
        PressureBandCalibrationProcess,
        "missing_requirements",
        staticmethod(lambda _cm: []),
    )

    cm, model = _build_inputs()
    p_true = PressureBandCalibrationProcess(cm, model, auto_stop_on_nozzle_wet=True)
    p_false = PressureBandCalibrationProcess(cm, model, auto_stop_on_nozzle_wet=False)

    assert p_true.auto_stop_on_nozzle_wet is True
    assert p_false.auto_stop_on_nozzle_wet is False


def test_pressure_scan_constructor_configures_single_candidate_mode(monkeypatch):
    monkeypatch.setattr(calibration_model, "QState", _DummyState)
    monkeypatch.setattr(calibration_model, "QFinalState", _DummyState)
    monkeypatch.setattr(calibration_model, "QStateMachine", _DummyStateMachine)
    monkeypatch.setattr(
        PressureBandCalibrationProcess,
        "missing_requirements",
        staticmethod(lambda _cm: []),
    )

    cm, model = _build_inputs()
    proc = PressureBandCalibrationProcess(cm, model, mode="single_candidate")

    assert proc.pressure_scan_mode == "single_candidate"
    assert proc.initial_reps_target == 1
    assert proc.replicates_target == 1
    assert proc.discard_first_after_major_pressure_change is False
    assert proc.backtrack_after_first_single is False
    assert proc._single_candidate_attempt_count == 0
    assert proc._single_candidate_attempt_history == []
    assert proc.single_candidate_center_retry_std_tol_px == 15.0
    assert proc.single_candidate_confirmation_retry_limit == 1
    assert proc._single_candidate_confirmation_retry_count == 0
    assert proc._single_candidate_confirmation_retry_history == []
    assert proc.single_candidate_max_stability_rejections == 2
    assert proc.single_candidate_stability_fallback_max_std_px == 100.0
    assert proc._single_candidate_stability_fallback_candidates == []
    assert proc._single_candidate_stability_rejection_count == 0
    assert proc._single_candidate_selected_by_fallback is False
    assert proc._single_candidate_triage_summary == {}
    assert proc.single_candidate_residue_moderate_area_px < proc.single_candidate_residue_persistent_area_px
    assert proc.single_candidate_satellite_min_area_px == 12000
    assert proc.single_candidate_satellite_min_bbox_area_px == 16000
    assert proc.single_candidate_satellite_probe_reps == 1
    assert proc._single_candidate_satellite_checks == []
    assert proc._build_pressure_scan_restore_settings() == {
        "num_droplets": 7,
        "flash_delay": 4321,
    }
    assert proc._restored_settings is False
    assert proc._restore_settings_confirmed is None
    assert proc.state_restore in proc.state_machine.states
    active_states = [
        proc.state_prepare_bg,
        proc.state_apply,
        proc.state_capture,
        proc.state_analyze,
        proc.state_decide,
    ]
    assert all(
        any(args and args[-1] is proc.state_restore for args, _kwargs in st.transitions)
        for st in active_states
    )
    assert any(
        args and args[-1] is proc.state_final
        for args, _kwargs in proc.state_restore.transitions
    )


def test_pressure_scan_restore_settings_restores_only_imaging_settings(monkeypatch):
    monkeypatch.setattr(calibration_model, "QState", _DummyState)
    monkeypatch.setattr(calibration_model, "QFinalState", _DummyState)
    monkeypatch.setattr(calibration_model, "QStateMachine", _DummyStateMachine)
    monkeypatch.setattr(
        PressureBandCalibrationProcess,
        "missing_requirements",
        staticmethod(lambda _cm: []),
    )

    cm, model = _build_inputs()
    completion_calls = []
    cm.emitSettingsChangeCompleted = lambda: completion_calls.append("done")
    proc = PressureBandCalibrationProcess(cm, model, mode="single_candidate")
    captured = {}

    def fake_request(settings, callback, **kwargs):
        captured["settings"] = dict(settings)
        captured["context"] = kwargs.get("context")
        captured["guard_timeout_ms"] = kwargs.get("guard_timeout_ms")
        callback()

    proc._request_settings_with_recording = fake_request

    proc.onRestoreSettings()

    assert captured["settings"] == {"num_droplets": 7, "flash_delay": 4321}
    assert "print_pressure" not in captured["settings"]
    assert captured["context"] == "pressure_scan_restore_settings"
    assert captured["guard_timeout_ms"] == 15_000
    assert proc._restored_settings is True
    assert proc._restore_settings_confirmed is True
    assert completion_calls == ["done"]


def test_pressure_scan_prefers_emergence_refined_nozzle_center(monkeypatch):
    monkeypatch.setattr(calibration_model, "QState", _DummyState)
    monkeypatch.setattr(calibration_model, "QFinalState", _DummyState)
    monkeypatch.setattr(calibration_model, "QStateMachine", _DummyStateMachine)
    monkeypatch.setattr(
        PressureBandCalibrationProcess,
        "missing_requirements",
        staticmethod(lambda _cm: []),
    )

    cm, model = _build_inputs()
    cm.get_pressure_scan_nozzle_center_image_position = lambda: (321, 123)
    cm.get_pressure_scan_nozzle_center_source = lambda: "emergence"

    proc = PressureBandCalibrationProcess(cm, model)

    assert proc.nozzle_center_px == (321, 123)
    assert proc.nozzle_center_source == "emergence"
