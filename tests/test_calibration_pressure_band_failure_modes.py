from types import SimpleNamespace

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import PressureBandCalibrationProcess  # noqa: E402


def _rep(cls_name: str, *, dy: int | None = None, cy: int | None = None, h: int = 1536):
    center = None if cy is None else (550, int(cy))
    return {
        "cls": str(cls_name),
        "center_px": center,
        "dy_min_px": dy,
        "nozzle_attached_area": 0,
        "nozzle_wet": False,
        "frame_height_px": int(h),
    }


def test_pressure_band_single_exit_risk_overrides_single_when_upper_multiple_exists():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.min_reps = 5
    proc.escalate_to = 9
    proc.replicates_target = 5
    proc.single_confidence_min = 0.70
    proc.none_confidence_min = 0.70
    proc.multiple_confidence_min = 0.40
    proc.multiple_min_count = 2
    proc.fast_single_bottom_margin_px = 220
    proc.fast_single_risk_fraction = 0.60
    proc.fast_single_risk_min_count = 3
    proc.fast_single_dy_threshold_px = 1000
    proc._current_pressure = 0.92
    proc._prev_verdict = None
    proc._prev_pressure = None
    proc.stageChanged = Recorder()
    proc.continueReplicate = Recorder()
    proc.samples = [
        {"pressure": 0.95, "verdict": "multiple"},
    ]
    proc.reps = [
        _rep("single", dy=1100, cy=1310),
        _rep("single", dy=1090, cy=1300),
        _rep("single", dy=1080, cy=1290),
        _rep("single", dy=1070, cy=1285),
        _rep("single", dy=1060, cy=1280),
    ]

    store_calls = []
    choose_calls = []
    advance_calls = []
    decision_calls = []

    proc._store_pressure_summary = lambda verdict, escalated, decision=None: store_calls.append(
        {"verdict": str(verdict), "escalated": bool(escalated), "decision": dict(decision or {})}
    )
    proc._record_decision = lambda *args, **kwargs: decision_calls.append((args, kwargs))
    proc._maybe_start_or_update_brackets = lambda _verdict: False
    proc._choose_next_pressure = lambda verdict: choose_calls.append(str(verdict))
    proc._advance_or_finish = lambda: advance_calls.append(True)

    proc.onDecide()

    assert proc.continueReplicate.calls == []
    assert store_calls and store_calls[0]["verdict"] == "multiple"
    assert store_calls[0]["decision"].get("reason") == "single_exit_risk_override"
    assert choose_calls == ["multiple"]
    assert len(advance_calls) == 1
    assert decision_calls


def test_pressure_band_completion_errors_when_no_single_band_found():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.samples = [
        {"pressure": 0.95, "verdict": "multiple"},
        {"pressure": 0.90, "verdict": "multiple"},
        {"pressure": 0.85, "verdict": "none"},
    ]
    proc.start_pressure = 0.95
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.stageChanged = Recorder()
    proc.calibrationError = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc._record_error = lambda *args, **kwargs: None
    proc.calibration_manager = SimpleNamespace(
        set_primary_pressure_band=lambda _payload: (_ for _ in ()).throw(AssertionError("should not set band"))
    )
    proc._compute_single_bands = lambda: []

    proc.onCalibrationCompleted()

    assert proc.calibrationError.calls
    assert "no valid single-droplet pressure band" in proc.calibrationError.calls[0][0][0].lower()
    assert proc.calibrationDataUpdated.calls == []
    assert proc.calibrationCompleted.calls == []
