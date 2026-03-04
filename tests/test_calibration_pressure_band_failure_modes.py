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


def _build_choose_proc(*, verdict: str, min_single_pressure):
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._phase = "scan"
    proc._pulse_width_us = 1500
    proc._upper_bracket = None
    proc._lower_bracket = None
    proc._straddle_bracket = None
    proc.dp_min = 0.01
    proc.dp = 0.05
    proc.multiple_big_step = 0.10
    proc.none_jump_up = 0.10
    proc.small_move_px = 8
    proc.large_move_px = 40
    proc.near_nozzle_px = 560
    proc.far_nozzle_px = 1050
    proc._prev_dy = None
    proc._prev_pressure = None
    proc._current_pressure = 0.90
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.auto_stop_on_nozzle_wet = True
    proc._early_stop = False
    proc._stop_reason = None
    proc._terminate_at_pressure = None
    proc._min_single_pressure = min_single_pressure
    proc.reps = [
        _rep(verdict, dy=120, cy=320),
        _rep(verdict, dy=118, cy=318),
        _rep(verdict, dy=121, cy=322),
    ]
    for r in proc.reps:
        r["nozzle_wet"] = True
    proc.finalize = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    return proc


def test_pressure_band_nozzle_wet_is_deferred_while_high_multiple_and_no_single_seen():
    proc = _build_choose_proc(verdict="multiple", min_single_pressure=None)

    proc._choose_next_pressure("multiple")

    assert proc._early_stop is False
    assert proc.finalize.calls == []
    assert proc._next_pressure < 0.90


def test_pressure_band_nozzle_wet_still_stops_after_single_region_seen():
    proc = _build_choose_proc(verdict="multiple", min_single_pressure=0.82)

    proc._choose_next_pressure("multiple")

    assert proc._early_stop is True
    assert proc._stop_reason == "Nozzle wet detected during scan"
    assert proc.finalize.calls
