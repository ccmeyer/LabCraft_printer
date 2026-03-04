from types import SimpleNamespace

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

import CalibrationClasses.Model as calibration_model
from CalibrationClasses.Model import PressureBandCalibrationProcess


class _DummyState:
    def __init__(self, *args, **kwargs):
        self.entered = SignalStub()

    def addTransition(self, *args, **kwargs):
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
