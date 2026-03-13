from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import (  # noqa: E402
    CalibrationManager,
    DropletCameraModel,
    PreBreakupMorphologyCalibrationProcess,
)


def _ready_cm():
    return SimpleNamespace(
        get_nozzle_center=lambda: {"X": 1, "Y": 2, "Z": 3},
        get_pressure_scan_nozzle_center_image_position=lambda: (160, 80),
        get_emergence_time=lambda: 3200,
        model=SimpleNamespace(
            droplet_camera_model=SimpleNamespace(get_image_size=lambda: (320, 320)),
        ),
    )


def _camera_stub():
    cam = DropletCameraModel.__new__(DropletCameraModel)
    cam._k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cam


def _proc_stub():
    proc = PreBreakupMorphologyCalibrationProcess.__new__(PreBreakupMorphologyCalibrationProcess)
    proc.min_signal_p95 = 10.0
    proc.min_protrusion_length_px = 14
    proc.min_candidate_protrusion_px = 28
    proc.min_candidate_bulb_width_px = 14
    proc.neck_ratio_risk_threshold = 0.42
    proc.nozzle_side_area_ratio_risk_threshold = 0.48
    proc.long_ligament_px = 36
    proc.max_secondary_lobes_for_clean = 0
    proc.late_stage_max_secondary_lobes_for_clean = 1
    proc.late_stage_min_protrusion_gain_ratio = 1.38
    proc.late_stage_risk_protrusion_gain_ratio = 1.75
    proc.delay_scout_min_protrusion_px = 14
    proc.pressure_scan_delay_step_back = 1
    proc._timing_mode = "auto_scout"
    proc.emergence_time_us = 3200
    proc.prebreakup_delay_us = 4200
    proc.fixed_prebreakup_delay_us = None
    proc._reversal_delay_us = 4300
    proc._pressure_scan_delay_reason = "pre_reversal_monitor_delay"
    proc.delay_scan_start_offset_us = 200
    proc.delay_scan_window_us = 2000
    proc.delay_scan_step_us = 100
    proc.delay_scan_replicates = 2
    proc.delay_scan_pulse_width_margin_us = 1000
    proc.delay_scan_extension_span_us = 1200
    proc.max_delay_scout_extensions = 4
    proc.max_delay_scout_pressure_retries = 2
    proc._delay_scout_selection = None
    proc._delay_scout_selection_meta = {}
    proc._delay_scout_selected_summary = {
        "protrusion_length_px": 286,
        "distance_nozzle_to_neck_px": 214,
    }
    proc._delay_scout_extension_count = 0
    proc._delay_scout_pressure_retry_count = 0
    proc._delay_scout_pressure = 0.42
    proc.delay_scout_pressure_retry_step_psi = 0.03
    proc.P_MIN = 0.30
    proc.P_MAX = 5.0
    proc.MAX_PREBREAKUP_DELAY_US = 12000
    proc._pulse_width_us = 1300
    return proc


class _SignalRecorder:
    def __init__(self):
        self.calls = []

    def emit(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def test_prebreakup_missing_requirements_reports_dependencies():
    cm = _ready_cm()
    cm.get_nozzle_center = lambda: None
    cm.get_pressure_scan_nozzle_center_image_position = lambda: None
    cm.get_emergence_time = lambda: None
    cm.model.droplet_camera_model.get_image_size = lambda: (_ for _ in ()).throw(RuntimeError("no camera"))

    missing = PreBreakupMorphologyCalibrationProcess.missing_requirements(cm)

    joined = " | ".join(missing).lower()
    assert "nozzle center" in joined
    assert "image coords" in joined
    assert "emergence" in joined
    assert "droplet camera" in joined


def test_start_prebreakup_uses_try_start_process_and_kwargs():
    mgr = CalibrationManager.__new__(CalibrationManager)
    called = {"proc_cls": None, "kwargs": None}

    def _stub(proc_cls, *args, **kwargs):
        called["proc_cls"] = proc_cls
        called["kwargs"] = dict(kwargs)
        return True

    mgr._try_start_process = _stub
    CalibrationManager.start_prebreakup_morphology_calibration(
        mgr,
        start_pressure=0.82,
        pressure_step_psi=0.025,
        prebreakup_lead_us=700,
        fixed_prebreakup_delay_us=4300,
        auto_scout_delay=False,
        replicates_per_pressure=4,
    )

    assert called["proc_cls"] is PreBreakupMorphologyCalibrationProcess
    assert called["kwargs"]["start_pressure"] == 0.82
    assert called["kwargs"]["pressure_step_psi"] == 0.025
    assert called["kwargs"]["prebreakup_lead_us"] == 700
    assert called["kwargs"]["fixed_prebreakup_delay_us"] == 4300
    assert called["kwargs"]["auto_scout_delay"] is False
    assert called["kwargs"]["replicates_per_pressure"] == 4


def test_analyze_prebreakup_morphology_extracts_attached_bulb_metrics():
    cam = _camera_stub()
    bg = np.full((320, 320, 3), 220, dtype=np.uint8)
    img = bg.copy()

    cv2.rectangle(img, (154, 80), (166, 126), (20, 20, 20), -1)
    cv2.circle(img, (160, 148), 26, (20, 20, 20), -1)

    metrics, _overlay, details = cam.analyze_prebreakup_morphology(
        bg,
        img,
        nozzle_center=(160, 80),
        return_details=True,
    )

    assert details["status"] == "ok"
    assert details["contour_class"] == "attached"
    assert metrics["protrusion_length_px"] >= 50
    assert metrics["max_width_px"] > metrics["neck_width_px"]
    assert metrics["bulb_present"] is True
    assert metrics["distance_nozzle_to_neck_px"] < metrics["protrusion_length_px"]
    assert details["tip_y_px"] > details["neck_y_px"]
    assert details["neck_selection_reason"] in {
        "local_min_before_distal_widening",
        "fallback_min_before_tail_guard",
    }


def test_analyze_prebreakup_morphology_recovers_weak_attachment_above_dark_bulb():
    cam = _camera_stub()
    bg = np.full((320, 320, 3), 220, dtype=np.uint8)
    img = bg.copy()

    cv2.rectangle(img, (154, 80), (166, 136), (130, 130, 130), -1)
    cv2.circle(img, (160, 156), 28, (20, 20, 20), -1)

    metrics, _overlay, details = cam.analyze_prebreakup_morphology(
        bg,
        img,
        nozzle_center=(160, 80),
        return_details=True,
    )

    assert details["status"] == "ok"
    assert details["mask_strategy"] == "nozzle_connected_dual_threshold"
    assert details["contour_class"] == "attached"
    assert details["seed_contact_detected"] is True
    assert details["threshold_weak"] <= details["threshold_strong"] <= details["threshold_hard"]
    assert metrics["protrusion_length_px"] >= 70


def test_analyze_prebreakup_morphology_handles_bright_attachment_segment():
    cam = _camera_stub()
    bg = np.full((320, 320, 3), 160, dtype=np.uint8)
    img = bg.copy()

    cv2.rectangle(img, (154, 80), (166, 136), (255, 255, 255), -1)
    cv2.circle(img, (160, 156), 28, (20, 20, 20), -1)

    metrics, _overlay, details = cam.analyze_prebreakup_morphology(
        bg,
        img,
        nozzle_center=(160, 80),
        return_details=True,
    )

    assert details["status"] == "ok"
    assert details["signal_mode"] == "absdiff"
    assert details["contour_class"] == "attached"
    assert details["seed_contact_detected"] is True
    assert metrics["protrusion_length_px"] >= 70


def test_analyze_prebreakup_morphology_marks_detached_contour():
    cam = _camera_stub()
    bg = np.full((320, 320, 3), 220, dtype=np.uint8)
    img = bg.copy()

    cv2.circle(img, (160, 150), 24, (20, 20, 20), -1)

    metrics, _overlay, details = cam.analyze_prebreakup_morphology(
        bg,
        img,
        nozzle_center=(160, 80),
        return_details=True,
    )

    assert details["status"] == "ok"
    assert details["contour_class"] == "detached"
    assert metrics["protrusion_length_px"] > 0


def test_analyze_prebreakup_morphology_extends_roi_to_fov_bottom_and_flags_clipping():
    cam = _camera_stub()
    bg = np.full((320, 320, 3), 220, dtype=np.uint8)
    img = bg.copy()

    cv2.rectangle(img, (154, 80), (166, 319), (20, 20, 20), -1)
    cv2.circle(img, (160, 302), 28, (20, 20, 20), -1)

    metrics, _overlay, details = cam.analyze_prebreakup_morphology(
        bg,
        img,
        nozzle_center=(160, 80),
        roi_below_px=None,
        return_details=True,
    )

    assert details["status"] == "ok"
    assert details["roi"][3] == 320
    assert details["bottom_clipped"] is True
    assert details["fov_bottom_clipped"] is True
    assert details["roi_bottom_gap_px"] == 0
    assert metrics["protrusion_length_px"] >= 200


def test_prebreakup_classify_morphology_distinguishes_candidate_and_risk():
    proc = _proc_stub()
    proc._timing_mode = "legacy_lead"

    candidate = proc._classify_morphology(
        {
            "status": "ok",
            "contour_class": "attached",
            "protrusion_length_px": 54,
            "max_width_px": 32,
            "neck_to_bulb_ratio": 0.55,
            "p95": 24.0,
            "nozzle_side_area_ratio": 0.24,
            "distance_nozzle_to_neck_px": 18,
            "secondary_lobe_count": 0,
            "bulb_present": True,
        }
    )
    risk = proc._classify_morphology(
        {
            "status": "ok",
            "contour_class": "attached",
            "protrusion_length_px": 62,
            "max_width_px": 36,
            "neck_to_bulb_ratio": 0.28,
            "p95": 24.0,
            "nozzle_side_area_ratio": 0.62,
            "distance_nozzle_to_neck_px": 42,
            "secondary_lobe_count": 2,
            "bulb_present": True,
        }
    )

    assert candidate == "candidate_clean"
    assert risk == "approaching_risk"


def test_prebreakup_classify_morphology_treats_bottom_clipped_stream_as_risk():
    proc = _proc_stub()

    state = proc._classify_morphology(
        {
            "status": "ok",
            "contour_class": "attached",
            "protrusion_length_px": 300,
            "max_width_px": 64,
            "neck_to_bulb_ratio": 0.32,
            "p95": 48.0,
            "nozzle_side_area_ratio": 0.44,
            "distance_nozzle_to_neck_px": 120,
            "secondary_lobe_count": 0,
            "bulb_present": True,
            "bottom_clipped": True,
        }
    )

    assert state == "approaching_risk"


def test_prebreakup_classify_morphology_late_stage_uses_scout_relative_band():
    proc = _proc_stub()

    too_low = proc._classify_morphology(
        {
            "status": "ok",
            "contour_class": "attached",
            "protrusion_length_px": 386,
            "reference_protrusion_length_px": 286,
            "protrusion_gain_ratio": 386.0 / 286.0,
            "max_width_px": 148,
            "neck_to_bulb_ratio": 0.142,
            "p95": 221.0,
            "nozzle_side_area_ratio": 0.908,
            "distance_nozzle_to_neck_px": 386,
            "secondary_lobe_count": 0,
            "bulb_present": True,
        }
    )
    candidate = proc._classify_morphology(
        {
            "status": "ok",
            "contour_class": "attached",
            "protrusion_length_px": 464,
            "reference_protrusion_length_px": 286,
            "protrusion_gain_ratio": 464.0 / 286.0,
            "max_width_px": 156,
            "neck_to_bulb_ratio": 0.132,
            "p95": 221.0,
            "nozzle_side_area_ratio": 0.918,
            "distance_nozzle_to_neck_px": 464,
            "secondary_lobe_count": 0,
            "bulb_present": True,
        }
    )
    risk = proc._classify_morphology(
        {
            "status": "ok",
            "contour_class": "attached",
            "protrusion_length_px": 538,
            "reference_protrusion_length_px": 286,
            "protrusion_gain_ratio": 538.0 / 286.0,
            "max_width_px": 159,
            "neck_to_bulb_ratio": 0.127,
            "p95": 221.0,
            "nozzle_side_area_ratio": 0.924,
            "distance_nozzle_to_neck_px": 538,
            "secondary_lobe_count": 0,
            "bulb_present": True,
        }
    )

    assert too_low == "too_low"
    assert candidate == "candidate_clean"
    assert risk == "approaching_risk"


def test_annotate_pressure_scan_details_adds_neck_and_protrusion_gain_ratios():
    proc = _proc_stub()

    details = proc._annotate_pressure_scan_details(
        {
            "protrusion_length_px": 464,
            "distance_nozzle_to_neck_px": 321,
        }
    )

    assert details["reference_protrusion_length_px"] == 286
    assert details["reference_neck_distance_px"] == 214
    assert round(details["protrusion_gain_ratio"], 3) == round(464.0 / 286.0, 3)
    assert round(details["neck_distance_gain_ratio"], 3) == round(321.0 / 214.0, 3)


def test_prebreakup_aggregate_replicates_prefers_risk_state_and_medians():
    proc = _proc_stub()
    proc.reps = [
        {"state": "candidate_clean", "details": {"protrusion_length_px": 42, "neck_to_bulb_ratio": 0.58, "bulb_present": True}},
        {"state": "approaching_risk", "details": {"protrusion_length_px": 50, "neck_to_bulb_ratio": 0.32, "bulb_present": True}},
        {"state": "approaching_risk", "details": {"protrusion_length_px": 48, "neck_to_bulb_ratio": 0.30, "bulb_present": True}},
    ]

    verdict, summary = proc._aggregate_replicates()

    assert verdict == "approaching_risk"
    assert summary["class_counts"]["approaching_risk"] == 2
    assert summary["feature_summary"]["protrusion_length_px"] == 48
    assert round(summary["feature_summary"]["neck_to_bulb_ratio"], 2) == 0.32
    assert summary["feature_summary"]["bulb_present"] is True


def test_prebreakup_aggregate_replicates_tracks_protrusion_gain_ratio():
    proc = _proc_stub()
    proc.reps = [
        {
            "state": "candidate_clean",
            "details": {
                "protrusion_length_px": 419,
                "reference_protrusion_length_px": 286,
                "protrusion_gain_ratio": 419.0 / 286.0,
                "bulb_present": True,
            },
        },
        {
            "state": "candidate_clean",
            "details": {
                "protrusion_length_px": 464,
                "reference_protrusion_length_px": 286,
                "protrusion_gain_ratio": 464.0 / 286.0,
                "bulb_present": True,
            },
        },
        {
            "state": "candidate_clean",
            "details": {
                "protrusion_length_px": 499,
                "reference_protrusion_length_px": 286,
                "protrusion_gain_ratio": 499.0 / 286.0,
                "bulb_present": True,
            },
        },
    ]

    verdict, summary = proc._aggregate_replicates()

    assert verdict == "candidate_clean"
    assert summary["feature_summary"]["reference_protrusion_length_px"] == 286
    assert round(summary["feature_summary"]["protrusion_gain_ratio"], 3) == round(464.0 / 286.0, 3)


def test_select_recommended_pressure_prefers_safe_window_midpoint():
    proc = _proc_stub()
    proc._first_candidate_pressure = 0.54
    proc._last_candidate_pressure = 0.60

    recommended = proc._select_recommended_pressure()

    assert recommended == pytest.approx(0.57)


def test_delay_scout_selects_turning_point_before_retraction():
    proc = _proc_stub()
    proc._delay_scout_samples = [
        {"delay_us": 3400, "feature_summary": {"attached_visible": True, "protrusion_length_px": 20}},
        {"delay_us": 3500, "feature_summary": {"attached_visible": True, "protrusion_length_px": 31}},
        {"delay_us": 3600, "feature_summary": {"attached_visible": True, "protrusion_length_px": 42}},
        {"delay_us": 3700, "feature_summary": {"attached_visible": True, "protrusion_length_px": 44}},
        {"delay_us": 3800, "feature_summary": {"attached_visible": True, "protrusion_length_px": 33}},
        {"delay_us": 3900, "feature_summary": {"attached_visible": True, "protrusion_length_px": 29}},
    ]

    selected, reason, meta = proc._select_delay_scout_candidate()

    assert selected["delay_us"] == 3700
    assert reason == "retraction_turning_point"
    assert meta["peak_protrusion_px"] == 44
    assert meta["reversal_delay_us"] == 3700
    assert meta["pressure_scan_delay_us"] == 3600
    assert meta["pressure_scan_delay_reason"] == "pre_reversal_monitor_delay"


def test_delay_scout_prefers_earliest_plateau_sample_with_confirmed_retraction():
    proc = _proc_stub()
    proc._delay_scout_samples = [
        {"delay_us": 3400, "feature_summary": {"attached_visible": True, "protrusion_length_px": 26}},
        {"delay_us": 3500, "feature_summary": {"attached_visible": True, "protrusion_length_px": 34}},
        {"delay_us": 3600, "feature_summary": {"attached_visible": True, "protrusion_length_px": 43}},
        {"delay_us": 3700, "feature_summary": {"attached_visible": True, "protrusion_length_px": 44}},
        {"delay_us": 3800, "feature_summary": {"attached_visible": True, "protrusion_length_px": 44}},
        {"delay_us": 3900, "feature_summary": {"attached_visible": True, "protrusion_length_px": 39}},
        {"delay_us": 4000, "feature_summary": {"attached_visible": True, "protrusion_length_px": 31}},
    ]

    selected, reason, meta = proc._select_delay_scout_candidate()

    assert selected["delay_us"] == 3700
    assert reason == "retraction_turning_point"
    assert meta["pressure_scan_delay_us"] == 3600


def test_delay_scout_requires_retraction_after_peak():
    proc = _proc_stub()
    proc._delay_scout_samples = [
        {"delay_us": 3400, "feature_summary": {"attached_visible": True, "protrusion_length_px": 18}},
        {"delay_us": 3500, "feature_summary": {"attached_visible": True, "protrusion_length_px": 26}},
        {"delay_us": 3600, "feature_summary": {"attached_visible": True, "protrusion_length_px": 31}},
        {"delay_us": 3700, "feature_summary": {"attached_visible": True, "protrusion_length_px": 33}},
    ]

    selected, reason, meta = proc._select_delay_scout_candidate()

    assert selected is None
    assert reason == "no_retraction_observed"
    assert meta["peak_delay_us"] == 3700


def test_build_delay_scan_schedule_expands_for_longer_pulse_widths():
    proc = _proc_stub()
    proc.emergence_time_us = 3600
    proc._pulse_width_us = 1800

    delays = proc._build_delay_scan_schedule()

    assert delays[0] == 3800
    assert delays[-1] == 6400


def test_delay_scout_extends_schedule_when_retraction_not_yet_seen_near_end():
    proc = _proc_stub()
    proc._pulse_width_us = 1800
    proc._delay_scout_delays = [3800, 3900, 4000, 4100, 4200, 4300, 4400]
    proc._delay_scout_extension_count = 0
    proc.stageChanged = _SignalRecorder()

    extended = proc._extend_delay_scan_schedule(
        reason="no_retraction_observed",
        meta={"peak_delay_us": 4400},
    )

    assert extended is True
    assert proc._delay_scout_delays[-1] > 4400
    assert proc._delay_scout_extension_count == 1
    assert proc.stageChanged.calls


def test_delay_scout_retries_at_lower_pressure_when_recent_frames_are_detached():
    proc = _proc_stub()
    proc._delay_scout_samples = [
        {
            "delay_us": 3400,
            "state_counts": {"not_attached": 2, "attached_visible": 0},
            "feature_summary": {"attached_visible": False},
        },
        {
            "delay_us": 3500,
            "state_counts": {"clipped": 2, "attached_visible": 0},
            "feature_summary": {"attached_visible": False},
        },
    ]
    proc._delay_scout_delays = [3400, 3500, 3600]
    proc._record_decision = lambda *args, **kwargs: None
    proc.stageChanged = _SignalRecorder()
    proc.continueScoutDelay = _SignalRecorder()

    should_retry, reason, meta = proc._should_retry_delay_scout_at_lower_pressure()

    assert should_retry is True
    assert reason == "scout_pressure_too_high"
    assert meta["retry_pressure_psi"] == pytest.approx(0.39)

    proc._restart_delay_scout_at_lower_pressure(reason, meta)

    assert proc._delay_scout_pressure == pytest.approx(0.39)
    assert proc._delay_scout_pressure_retry_count == 1
    assert proc._delay_scout_samples == []
    assert proc._delay_scout_index == 0
    assert proc.continueScoutDelay.calls


def test_delay_scout_stops_as_soon_as_retraction_is_confirmed():
    proc = _proc_stub()
    proc._delay_scout_pressure = 0.42
    proc._delay_scout_current_delay = 3800
    proc._delay_scout_delays = [3400, 3500, 3600, 3700, 3800, 3900]
    proc._delay_scout_index = 4
    proc._delay_scout_samples = [
        {"delay_us": 3400, "feature_summary": {"attached_visible": True, "protrusion_length_px": 20}},
        {"delay_us": 3500, "feature_summary": {"attached_visible": True, "protrusion_length_px": 31}},
        {"delay_us": 3600, "feature_summary": {"attached_visible": True, "protrusion_length_px": 42}},
        {"delay_us": 3700, "feature_summary": {"attached_visible": True, "protrusion_length_px": 44}},
    ]
    proc._delay_scout_reps = [
        {
            "state": "attached_visible",
            "details": {
                "protrusion_length_px": 33,
                "max_width_px": 36,
                "neck_width_px": 16,
                "neck_y_px": 180,
                "distance_nozzle_to_neck_px": 100,
                "nozzle_side_area_px": 240,
                "nozzle_side_area_ratio": 0.36,
                "distal_area_px": 420,
                "neck_to_bulb_ratio": 0.44,
                "secondary_lobe_count": 0,
                "p95": 24.0,
                "contour_class": "attached",
                "bulb_present": True,
            },
        },
        {
            "state": "attached_visible",
            "details": {
                "protrusion_length_px": 31,
                "max_width_px": 34,
                "neck_width_px": 15,
                "neck_y_px": 176,
                "distance_nozzle_to_neck_px": 96,
                "nozzle_side_area_px": 230,
                "nozzle_side_area_ratio": 0.34,
                "distal_area_px": 410,
                "neck_to_bulb_ratio": 0.46,
                "secondary_lobe_count": 0,
                "p95": 23.0,
                "contour_class": "attached",
                "bulb_present": True,
            },
        },
    ]
    proc._record_decision = lambda *args, **kwargs: None
    proc._record_error = lambda *args, **kwargs: None
    proc.stageChanged = _SignalRecorder()
    proc.startPressureSweep = _SignalRecorder()
    proc.continueScoutDelay = _SignalRecorder()
    proc.continueScoutReplicate = _SignalRecorder()
    proc.calibrationError = _SignalRecorder()

    proc.onDecideDelayScout()

    assert proc._reversal_delay_us == 3700
    assert proc.prebreakup_delay_us == 3600
    assert len(proc._delay_scout_samples) == 5
    assert proc._delay_scout_index == 4
    assert len(proc.startPressureSweep.calls) == 1
    assert len(proc.continueScoutDelay.calls) == 0
    assert len(proc.calibrationError.calls) == 0


def test_build_delay_scout_result_keeps_reversal_and_scan_delay():
    proc = _proc_stub()
    proc._delay_scout_delays = [3400, 3500, 3600, 3700]
    proc._delay_selection_reason = "retraction_turning_point"
    proc._delay_scout_selection_meta = {
        "reversal_delay_us": 3700,
        "pressure_scan_delay_us": 3600,
    }
    proc._delay_scout_selected_summary = {"protrusion_length_px": 44}
    proc._delay_scout_pressure = 0.42
    proc._delay_scout_samples = [{"delay_us": 3600}, {"delay_us": 3700}]

    result = proc._build_delay_scout_result()

    assert result["selected_delay_us"] == 4300
    assert result["reversal_delay_us"] == 4300
    assert result["pressure_scan_delay_us"] == 4200
    assert result["pressure_scan_delay_reason"] == "pre_reversal_monitor_delay"


def test_publish_safe_window_primary_band_makes_trajectory_handoff_available():
    proc = _proc_stub()
    published = []
    proc.phase_name = "pre_breakup_morphology"
    proc.calibration_manager = SimpleNamespace(
        set_primary_pressure_band=lambda payload: published.append(dict(payload)),
    )

    ok = proc._publish_safe_window_primary_band([0.41, 0.47], 0.44)

    assert ok is True
    assert published
    payload = published[-1]
    assert payload["primary_band"] == [0.41, 0.47]
    assert payload["single_bands"] == [[0.41, 0.47]]
    assert payload["recommended_pressure_psi"] == pytest.approx(0.44)
    assert payload["source_phase"] == "pre_breakup_morphology"
