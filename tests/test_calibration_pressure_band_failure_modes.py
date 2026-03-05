from types import SimpleNamespace

import numpy as np

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
        "stream_like_count": 0,
        "max_aspect_h_over_w": None,
        "min_circularity": None,
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


def test_pressure_band_reacquire_too_close_is_reclassified_none_not_stop():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._discard_next = False
    proc._phase = "reacquire_up"
    proc._prev_verdict = "none"
    proc._current_pressure = 1.10
    proc.safety_clearance_px = 350
    proc.nozzle_center_px = (100, 100)
    proc.nozzle_area_threshold = 8000
    proc.background_image = np.zeros((220, 220), dtype=np.uint8)
    proc.droplet_image = np.zeros((220, 220), dtype=np.uint8)
    proc.reps = []
    proc._invalid_skip_count = 0
    proc._invalid_skip_cap = 6
    proc._active_classify_delay_us = 5850
    proc.classify_delay_us = 5850
    proc.stageChanged = Recorder()
    proc.replicateReady = Recorder()
    proc.finalize = Recorder()
    proc.calibrationError = Recorder()
    proc.presentImageSignal = Recorder()
    decision_calls = []
    proc._record_decision = lambda *args, **kwargs: decision_calls.append((args, kwargs))
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: ([(100, 120)], 0, np.zeros((220, 220), dtype=np.uint8))
        )
    )

    proc.onAnalyzeReplicate()

    assert proc.finalize.calls == []
    assert proc.replicateReady.calls
    assert len(proc.reps) == 1
    assert proc.reps[0]["cls"] == "none"
    assert proc.reps[0]["dy_min_px"] is None
    assert decision_calls


def test_pressure_band_reacquire_guard_resumes_scan_after_max_steps():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._phase = "reacquire_up"
    proc._current_pressure = 1.20
    proc._prev_pressure = None
    proc._prev_verdict = None
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.dp_min = 0.01
    proc._reacquire_step = 0.10
    proc._reacquire_growth = 1.7
    proc._reacquire_step_max = 0.30
    proc._reacquire_steps_taken = 17
    proc._reacquire_max_steps = 18
    proc.stageChanged = Recorder()
    decision_calls = []
    proc._record_decision = lambda *args, **kwargs: decision_calls.append((args, kwargs))

    transitioned = proc._maybe_start_or_update_brackets("none")

    assert transitioned is True
    assert proc._phase == "scan"
    assert proc._next_pressure < 1.20
    assert decision_calls
    assert decision_calls[0][0][0] == "reacquire_guard_resume_scan"


def test_pressure_band_seek_upper_guard_resumes_scan_after_span_or_steps():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._phase = "seek_upper"
    proc._current_pressure = 2.05
    proc._prev_pressure = None
    proc._prev_verdict = "single"
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.dp_min = 0.01
    proc._seek_step = 0.08
    proc._seek_growth = 1.7
    proc._seek_step_max = 0.20
    proc._seek_upper_steps = 9
    proc._seek_upper_max_steps = 10
    proc._seek_upper_max_span_psi = 0.80
    proc._first_single_pressure = 1.10
    proc.stageChanged = Recorder()
    decision_calls = []
    proc._record_decision = lambda *args, **kwargs: decision_calls.append((args, kwargs))

    transitioned = proc._maybe_start_or_update_brackets("single")

    assert transitioned is True
    assert proc._phase == "scan"
    assert proc._next_pressure <= 1.10
    assert decision_calls
    assert decision_calls[0][0][0] == "seek_upper_guard_resume_scan"


def test_pressure_band_retest_does_not_request_second_earlier_step_after_cap():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5350
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc.delay_retest_max_earlier_steps = 1
    proc._delay_retest_earlier_steps_done_for_pressure = 1
    proc._delay_retest_context = {
        "prior_verdict": "multiple",
        "prior_counts": {"none": 0, "single": 3, "multiple": 2},
        "prior_decision": {"has_upper_multiple_evidence": True},
        "trigger_reason": "mixed_single_multiple",
    }

    reason = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )

    assert reason is None


def test_pressure_band_retest_merge_keeps_multiple_when_prior_multiple_evidence_exists():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.multiple_confidence_min = 0.40
    proc._delay_retest_context = {
        "trigger_reason": "mixed_single_multiple",
        "prior_verdict": "multiple",
        "prior_counts": {"none": 0, "single": 2, "multiple": 3},
        "prior_decision": {"has_upper_multiple_evidence": True},
        "prior_confidence": 0.75,
        "prior_reason": "multiple_confident",
    }
    decision = {"reason": "single_confident"}

    verdict, confidence, merged = proc._merge_delay_retest_decision(
        "single",
        0.70,
        {"none": 0, "single": 5, "multiple": 0},
        decision,
    )

    assert verdict == "multiple"
    assert confidence >= 0.75
    assert merged["reason"] == "retest_conflict_keep_multiple"


def test_pressure_band_later_delay_candidate_moves_back_toward_base():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.classify_delay_us = 5850
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5350
    proc.delay_retest_step_us = 500
    proc.delay_retest_max_later_offset_us = 1000
    proc.delay_retest_abs_max_us = 20000

    assert proc._later_delay_candidate_us() == 5850


def test_pressure_band_edge_retest_only_allowed_in_scan_phase():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5850
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc.delay_retest_max_earlier_steps = 1
    proc._delay_retest_earlier_steps_done_for_pressure = 0
    proc._current_pressure = 1.50
    proc._edge_retest_pressures = []
    proc._edge_retest_count = 0
    proc.edge_retest_scan_only = True
    proc.edge_retest_cooldown_psi = 0.03
    proc.edge_retest_max_per_run = 3
    proc.edge_retest_proximity_window_psi = 0.03
    proc.samples = [{"pressure": 1.52, "verdict": "multiple"}]

    proc._phase = "refine_upper"
    r1 = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )
    assert r1 is None

    proc._phase = "scan"
    r2 = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )
    assert r2 == "edge_single_with_upper_multiple"


def test_pressure_band_edge_retest_cooldown_skips_nearby_pressure():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5850
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc.delay_retest_max_earlier_steps = 1
    proc._delay_retest_earlier_steps_done_for_pressure = 0
    proc._phase = "scan"
    proc.edge_retest_scan_only = True
    proc.edge_retest_cooldown_psi = 0.03
    proc.edge_retest_max_per_run = 3
    proc.edge_retest_proximity_window_psi = 0.03
    proc._edge_retest_count = 1
    proc._edge_retest_pressures = [1.50]
    proc.samples = [{"pressure": 1.56, "verdict": "multiple"}]
    proc._current_pressure = 1.515

    near = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )
    assert near is None

    proc._current_pressure = 1.55
    far = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )
    assert far == "edge_single_with_upper_multiple"

    proc.samples = [{"pressure": 1.575, "verdict": "multiple"}]
    near_edge = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )
    assert near_edge == "edge_single_with_upper_multiple"


def test_pressure_band_start_delay_retest_later_increments_later_counter():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.classify_delay_us = 5850
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5350
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc.delay_retest_max_earlier_steps = 1
    proc.delay_retest_max_later_steps = 2
    proc.delay_retest_max_later_offset_us = 1000
    proc.delay_retest_abs_max_us = 20000
    proc.delay_retest_timeout_ms = 15000
    proc._delay_retest_done_for_pressure = False
    proc._delay_retest_steps_done_for_pressure = 0
    proc._delay_retest_earlier_steps_done_for_pressure = 0
    proc._delay_retest_later_steps_done_for_pressure = 0
    proc._delay_retest_in_progress = False
    proc._delay_retest_context = None
    proc._retest_mode_active = False
    proc._current_pressure = 1.20
    proc.min_reps = 5
    proc.retest_min_reps = 3
    proc.reps = []
    proc._invalid_skip_count = 0
    proc._discard_next = False
    proc.stageChanged = Recorder()
    proc.continueReplicate = Recorder()
    proc.calibrationError = Recorder()
    proc.finalize = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    proc._record_error = lambda *args, **kwargs: None
    proc._cancel_timeout = lambda *_args, **_kwargs: None
    proc._start_timeout = lambda *_args, **_kwargs: "timer-token"
    proc._request_settings_with_recording = lambda _settings, cb, context=None: cb()

    ok = proc._start_delay_retest(
        "attached_stream_requires_later_delay",
        "single",
        {"single": 5, "none": 0, "multiple": 0},
        {"reason": "single_confident"},
        1.0,
        direction="later",
    )

    assert ok is True
    assert proc._active_classify_delay_us == 5850
    assert proc._delay_retest_later_steps_done_for_pressure == 1
    assert proc._delay_retest_earlier_steps_done_for_pressure == 0
    assert proc.replicates_target == 3
    assert proc._discard_next is False
    assert proc._retest_mode_active is True


def test_pressure_band_analyze_reclassifies_stream_like_single_as_multiple():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._discard_next = False
    proc._phase = "scan"
    proc._prev_verdict = "single"
    proc._current_pressure = 1.55
    proc.safety_clearance_px = 350
    proc.nozzle_center_px = (100, 100)
    proc.nozzle_area_threshold = 8000
    proc.background_image = np.zeros((220, 220), dtype=np.uint8)
    proc.droplet_image = np.zeros((220, 220), dtype=np.uint8)
    proc.reps = []
    proc._invalid_skip_count = 0
    proc._invalid_skip_cap = 6
    proc._active_classify_delay_us = 5850
    proc.classify_delay_us = 5850
    proc.stream_aspect_hard = 2.0
    proc.stream_aspect_soft = 1.6
    proc.stream_circularity_max = 0.55
    proc.stream_min_area_px = 1200
    proc.stageChanged = Recorder()
    proc.replicateReady = Recorder()
    proc.finalize = Recorder()
    proc.calibrationError = Recorder()
    proc.presentImageSignal = Recorder()
    decision_calls = []
    proc._record_decision = lambda *args, **kwargs: decision_calls.append((args, kwargs))
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: (
                [(110, 540)],
                0,
                np.zeros((220, 220), dtype=np.uint8),
                {
                    "free_droplets": [
                        {
                            "area_px": 2600,
                            "aspect_h_over_w": 2.4,
                            "circularity": 0.31,
                            "is_stream_like": True,
                        }
                    ]
                },
            )
        )
    )

    proc.onAnalyzeReplicate()

    assert proc.finalize.calls == []
    assert proc.replicateReady.calls
    assert len(proc.reps) == 1
    rep = proc.reps[0]
    assert rep["cls"] == "multiple"
    assert rep["stream_like_count"] == 1
    assert rep["max_aspect_h_over_w"] >= 2.4
    assert rep["min_circularity"] <= 0.31
    assert decision_calls
    assert any(
        args and args[0] == "stream_like_single_reclassified_multiple"
        for args, _kwargs in decision_calls
    )


def test_pressure_band_completion_reports_conservative_primary_band_for_wide_band():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.samples = [
        {"pressure": 1.30, "verdict": "single"},
        {"pressure": 1.20, "verdict": "single"},
        {"pressure": 1.10, "verdict": "single"},
    ]
    proc.start_pressure = 1.30
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.classify_delay_us = 5850
    proc._pulse_width_us = 1600
    proc._early_stop = False
    proc._stop_reason = None
    proc._terminate_at_pressure = None
    proc.stageChanged = Recorder()
    proc.calibrationError = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.conservative_band_width_threshold_psi = 0.10
    proc.conservative_band_inset_psi = 0.02
    proc._record_error = lambda *args, **kwargs: None
    proc.calibration_manager = SimpleNamespace(
        set_primary_pressure_band=lambda _payload: None
    )
    proc._compute_single_bands = lambda: [[1.10, 1.30]]

    proc.onCalibrationCompleted()

    assert proc.calibrationError.calls == []
    assert proc.calibrationDataUpdated.calls
    result = proc.calibrationDataUpdated.calls[0][0][0]["result"]
    assert result["single_bands"] == [[1.1, 1.3]]
    assert result["raw_primary_band"] == [1.1, 1.3]
    assert result["primary_band"] == [1.12, 1.28]
    assert result["conservative_primary_band_applied"] is True
