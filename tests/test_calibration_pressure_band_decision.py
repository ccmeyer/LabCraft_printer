from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import PressureBandCalibrationProcess  # noqa: E402


def _rep(
    cls_name: str,
    *,
    dy: int | None = None,
    cy: int | None = None,
    h: int = 1536,
    center=None,
    nozzle_contact: bool = False,
    near_nozzle_residue: bool = False,
    near_nozzle_residue_area: int | None = None,
    nozzle_wet: bool = False,
    too_close: bool = False,
    nozzle_attached_area: int = 0,
    stream_like_count: int = 0,
    free_blob_count: int = 1,
    largest_free_blob_area_px: int = 20000,
    largest_free_blob_bbox=None,
    bottom_edge_or_clipped: bool = False,
):
    if center is not None:
        center_value = tuple(center)
    else:
        center_value = None if cy is None else (550, int(cy))
    residue_area = (
        int(near_nozzle_residue_area)
        if near_nozzle_residue_area is not None
        else (12000 if near_nozzle_residue else 0)
    )
    bbox = (
        list(largest_free_blob_bbox)
        if largest_free_blob_bbox is not None
        else [500, 500, 140, 150]
    )
    return {
        "cls": str(cls_name),
        "center_px": center_value,
        "dy_min_px": dy,
        "nozzle_attached_area": int(nozzle_attached_area),
        "nozzle_contact": bool(nozzle_contact or nozzle_wet),
        "near_nozzle_residue": bool(near_nozzle_residue),
        "near_nozzle_residue_area": int(residue_area),
        "near_nozzle_residue_components": 1 if near_nozzle_residue else 0,
        "nozzle_wet": bool(nozzle_wet),
        "too_close": bool(too_close),
        "frame_height_px": int(h),
        "free_blob_count": int(free_blob_count),
        "largest_free_blob_area_px": int(largest_free_blob_area_px),
        "largest_free_blob_bbox": [int(v) for v in bbox[:4]],
        "largest_free_blob_bbox_area_px": int(max(0, int(bbox[2])) * max(0, int(bbox[3]))),
        "largest_free_blob_bottom_px": int(h - 1 if bottom_edge_or_clipped else 550),
        "bottom_edge_or_clipped": bool(bottom_edge_or_clipped),
        "stream_like_count": int(stream_like_count),
        "max_aspect_h_over_w": None,
        "min_circularity": None,
    }


def _build_decide_proc(reps):
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.min_reps = 5
    proc.initial_reps_target = 3
    proc.escalate_to = 9
    proc.replicates_target = proc.min_reps
    proc.single_confidence_min = 0.70
    proc.none_confidence_min = 0.70
    proc.multiple_confidence_min = 0.40
    proc.multiple_min_count = 2
    proc.reps = list(reps)
    proc.samples = []
    proc._current_pressure = 1.23
    proc._prev_verdict = None
    proc._prev_pressure = None
    proc.classify_delay_us = 5850
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5850
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc.delay_retest_max_earlier_steps = 1
    proc.delay_retest_max_later_steps = 2
    proc.delay_retest_max_later_offset_us = 1000
    proc._delay_retest_done_for_pressure = False
    proc._delay_retest_steps_done_for_pressure = 0
    proc._delay_retest_earlier_steps_done_for_pressure = 0
    proc._delay_retest_later_steps_done_for_pressure = 0
    proc._delay_retest_in_progress = False
    proc._delay_retest_context = None
    proc._retest_mode_active = False
    proc._phase = "scan"
    proc.edge_retest_scan_only = True
    proc.edge_retest_cooldown_psi = 0.03
    proc.edge_retest_max_per_run = 3
    proc.edge_retest_proximity_window_psi = 0.03
    proc._edge_retest_pressures = []
    proc._edge_retest_count = 0
    proc.retest_min_reps = 3
    proc.pre_ejection_attached_area_px = 8000
    proc.pre_ejection_attached_ratio = 0.60
    proc.fast_single_bottom_margin_px = 220
    proc.fast_single_risk_fraction = 0.60
    proc.fast_single_risk_min_count = 3
    proc.fast_single_dy_threshold_px = 1000
    proc.large_move_px = 40
    proc._carry_forward_classify_delay_us = None
    proc._carry_forward_delay_anchor_pressure = None
    proc._edge_retest_side_counts = {"upper": 0, "lower": 0}
    proc.stageChanged = Recorder()
    proc.continueReplicate = Recorder()
    proc._record_decision = lambda *args, **kwargs: None

    proc._store_calls = []
    proc._choose_calls = []
    proc._advance_calls = []

    def _store(verdict, escalated, decision=None):
        proc._store_calls.append(
            {
                "verdict": str(verdict),
                "escalated": bool(escalated),
                "decision": dict(decision or {}),
            }
        )

    proc._store_pressure_summary = _store
    proc._maybe_start_or_update_brackets = lambda _verdict: False
    proc._choose_next_pressure = lambda verdict: proc._choose_calls.append(str(verdict))
    proc._advance_or_finish = lambda: proc._advance_calls.append(True)
    return proc


def _build_single_candidate_proc(reps):
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.pressure_scan_mode = "single_candidate"
    proc.min_reps = 5
    proc.replicates_target = 1
    proc.single_candidate_confirmation_reps = 5
    proc.single_candidate_center_std_tol_px = 8.0
    proc.single_candidate_step_psi = 0.02
    proc.single_candidate_max_pressures = 12
    proc.single_candidate_max_span_psi = 0.30
    proc.single_candidate_residue_persistent_area_px = 8000
    proc.reps = list(reps)
    proc.samples = []
    proc._current_pressure = 1.00
    proc.start_pressure = 1.00
    proc.P_MIN = 0.30
    proc.P_MAX = 2.00
    proc.classify_delay_us = 5850
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5850
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc._pulse_width_us = 1600
    proc._early_stop = False
    proc._stop_reason = None
    proc._terminate_at_pressure = None
    proc._single_candidate_confirming = False
    proc._single_candidate_candidate_pressure = None
    proc._single_candidate_selected_pressure = None
    proc._single_candidate_confirmation_summary = {}
    proc._single_candidate_residue_checks = []
    proc._single_candidate_satellite_checks = []
    proc._single_candidate_satellite_probe_in_progress = False
    proc._single_candidate_pending_satellite_probe = None
    proc._single_candidate_pending_residue_check = None
    proc._single_candidate_failure_message = None
    proc._single_candidate_residue_check_in_progress = False
    proc._single_candidate_tested_pressures = []
    proc._single_candidate_attempt_count = 1
    proc._single_candidate_attempt_history = []
    proc._single_candidate_loop_detected = False
    proc._single_candidate_last_loop_escape = {}
    proc.single_candidate_residue_moderate_area_px = 2000
    proc.single_candidate_bottom_edge_margin_px = 24
    proc.single_candidate_satellite_min_area_px = 12000
    proc.single_candidate_satellite_min_bbox_area_px = 16000
    proc.single_candidate_satellite_probe_reps = 1
    proc.single_candidate_satellite_larger_area_ratio = 1.4
    proc.single_candidate_residue_artifact_free_count = 4
    proc.single_candidate_residue_artifact_component_count = 12
    proc.single_candidate_residue_artifact_large_bbox_area_px = 100000
    proc.single_candidate_residue_artifact_span_fraction = 0.65
    proc.continueReplicate = Recorder()
    proc.continueScan = Recorder()
    proc.finalize = Recorder()
    proc.stageChanged = Recorder()
    proc.calibrationError = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    proc._record_error = lambda *args, **kwargs: None
    proc._request_settings_with_recording = (
        lambda _settings, callback, **_kwargs: callback()
    )
    proc.calibration_manager = SimpleNamespace(
        set_primary_pressure_band=lambda _payload: None,
    )
    return proc


def test_single_candidate_triage_none_steps_up_after_one_capture():
    proc = _build_single_candidate_proc([_rep("none")])

    proc.onDecide()

    assert proc._next_pressure == 1.02
    assert proc.continueScan.calls
    assert proc.continueReplicate.calls == []


def test_single_candidate_triage_contact_and_too_close_step_up():
    for rep in (
        _rep("none", nozzle_contact=True),
        _rep("none", too_close=True),
    ):
        proc = _build_single_candidate_proc([rep])

        proc.onDecide()

        assert proc._next_pressure == 1.02
        assert proc.continueScan.calls
        assert proc.finalize.calls == []


def test_single_candidate_triage_multiple_steps_down_after_one_capture():
    proc = _build_single_candidate_proc([_rep("multiple")])

    proc.onDecide()

    assert proc._next_pressure == 0.98
    assert proc.continueScan.calls


def test_single_candidate_triage_single_collects_confirmation_reps():
    proc = _build_single_candidate_proc([_rep("single", center=(100, 200))])

    proc.onDecide()

    assert proc._single_candidate_confirming is True
    assert proc.replicates_target == 5
    assert proc.continueReplicate.calls
    assert proc.continueScan.calls == []


def test_single_candidate_confirmation_finalizes_degenerate_band():
    proc = _build_single_candidate_proc(
        [_rep("single", center=(100 + i % 2, 200 + i % 2)) for i in range(5)]
    )
    proc._single_candidate_confirming = True
    proc.replicates_target = 5
    persisted = []
    proc.calibration_manager = SimpleNamespace(
        set_primary_pressure_band=lambda payload: persisted.append(dict(payload)),
    )

    proc.onDecide()
    proc.onCalibrationCompleted()

    assert proc.finalize.calls
    assert proc.calibrationCompleted.calls
    payload = proc.calibrationDataUpdated.calls[0][0][0]["result"]
    assert payload["pressure_scan_mode"] == "single_candidate"
    assert payload["primary_band"] == [1.0, 1.0]
    assert payload["single_bands"] == [[1.0, 1.0]]
    assert payload["lock_pressure_for_trajectory"] is True
    assert persisted and persisted[0]["primary_band"] == [1.0, 1.0]


def test_single_candidate_unstable_confirmation_rejects_and_steps_up():
    proc = _build_single_candidate_proc(
        [_rep("single", center=(100 + i * 30, 200)) for i in range(5)]
    )
    proc._single_candidate_confirming = True
    proc.replicates_target = 5

    proc.onDecide()

    assert proc._next_pressure == 1.02
    assert proc.continueScan.calls
    assert proc.finalize.calls == []


def test_single_candidate_rejected_confirmation_after_higher_multiple_steps_down():
    proc = _build_single_candidate_proc(
        [_rep("single", center=(100 + i * 30, 200)) for i in range(5)]
    )
    proc._single_candidate_confirming = True
    proc.replicates_target = 5
    proc._single_candidate_attempt_history = [
        {
            "pressure": 1.02,
            "next_pressure": 1.00,
            "direction": "down",
            "reason": "multiple",
            "failure_kind": "high",
        }
    ]

    proc.onDecide()

    assert proc._next_pressure == 0.98
    assert proc.continueScan.calls


def test_single_candidate_bottom_edge_single_steps_down_after_one_capture():
    proc = _build_single_candidate_proc(
        [_rep("single", center=(100, 1500), bottom_edge_or_clipped=True)]
    )

    proc.onDecide()

    assert proc._next_pressure == 0.98
    assert proc.continueScan.calls
    assert proc.continueReplicate.calls == []


def test_single_candidate_small_single_triage_starts_satellite_probe():
    proc = _build_single_candidate_proc(
        [
            _rep(
                "single",
                center=(100, 200),
                largest_free_blob_area_px=8200,
                largest_free_blob_bbox=[500, 500, 90, 90],
            )
        ]
    )
    calls = []
    proc._start_single_candidate_satellite_probe = (
        lambda *, trigger, decision=None, summary=None: calls.append(
            {
                "trigger": trigger,
                "decision": dict(decision or {}),
                "summary": dict(summary or {}),
            }
        )
        or True
    )

    proc.onDecide()

    assert calls and calls[0]["trigger"] == "triage"
    assert calls[0]["summary"]["small_single_suspect_hits"] == 1
    assert proc._single_candidate_confirming is False
    assert proc.continueScan.calls == []


def test_single_candidate_small_confirmation_starts_satellite_probe_not_finalize():
    proc = _build_single_candidate_proc(
        [
            _rep(
                "single",
                center=(100 + i % 2, 200 + i % 2),
                largest_free_blob_area_px=8100,
                largest_free_blob_bbox=[500, 500, 90, 90],
            )
            for i in range(5)
        ]
    )
    proc._single_candidate_confirming = True
    proc.replicates_target = 5
    calls = []
    proc._start_single_candidate_satellite_probe = (
        lambda *, trigger, decision=None, summary=None: calls.append(
            {
                "trigger": trigger,
                "decision": dict(decision or {}),
                "summary": dict(summary or {}),
            }
        )
        or True
    )

    proc.onDecide()

    assert calls and calls[0]["trigger"] == "confirmation"
    assert calls[0]["summary"]["small_single_suspect_hits"] == 5
    assert proc.finalize.calls == []
    assert proc.continueScan.calls == []


def test_single_candidate_satellite_probe_larger_main_steps_down():
    original = _rep(
        "single",
        center=(100, 200),
        largest_free_blob_area_px=8200,
        largest_free_blob_bbox=[500, 500, 90, 90],
    )
    proc = _build_single_candidate_proc([original])
    summary = proc._build_single_candidate_confirmation_summary(proc.reps)

    proc._start_single_candidate_satellite_probe(
        trigger="triage",
        decision={"failure_kind": "low", "suggested_direction": "up"},
        summary=summary,
    )
    proc.reps = [
        _rep(
            "single",
            center=(100, 200),
            largest_free_blob_area_px=22000,
            largest_free_blob_bbox=[500, 500, 150, 150],
        )
    ]

    proc.onDecide()

    assert proc._next_pressure == 0.98
    assert proc.continueScan.calls
    assert proc._active_classify_delay_us == 5850
    assert proc._single_candidate_satellite_checks[-1]["result"] == "small_single_satellite_confirmed"
    assert proc._single_candidate_attempt_history[-1]["failure_kind"] == "high"


def test_single_candidate_satellite_probe_multiple_steps_down():
    original = _rep(
        "single",
        center=(100, 200),
        largest_free_blob_area_px=8200,
        largest_free_blob_bbox=[500, 500, 90, 90],
    )
    proc = _build_single_candidate_proc([original])
    summary = proc._build_single_candidate_confirmation_summary(proc.reps)

    proc._start_single_candidate_satellite_probe(
        trigger="triage",
        decision={"failure_kind": "low", "suggested_direction": "up"},
        summary=summary,
    )
    proc.reps = [_rep("multiple", free_blob_count=2, largest_free_blob_area_px=22000)]

    proc.onDecide()

    assert proc._next_pressure == 0.98
    assert proc._single_candidate_satellite_checks[-1]["evidence"] == "high_pressure_probe"
    assert proc._single_candidate_attempt_history[-1]["rejection_cause"] == "small_single_satellite_confirmed"


def test_single_candidate_unresolved_small_probe_uses_recent_low_history():
    original = _rep(
        "single",
        center=(100, 200),
        largest_free_blob_area_px=8200,
        largest_free_blob_bbox=[500, 500, 90, 90],
    )
    proc = _build_single_candidate_proc([original])
    proc._single_candidate_attempt_history = [
        {
            "pressure": 0.98,
            "next_pressure": 1.00,
            "direction": "up",
            "reason": "none",
            "failure_kind": "low",
        }
    ]
    summary = proc._build_single_candidate_confirmation_summary(proc.reps)

    proc._start_single_candidate_satellite_probe(
        trigger="triage",
        decision={"failure_kind": "low", "suggested_direction": "up"},
        summary=summary,
    )
    proc.reps = [
        _rep(
            "single",
            center=(100, 200),
            largest_free_blob_area_px=8300,
            largest_free_blob_bbox=[500, 500, 90, 90],
        )
    ]

    proc.onDecide()

    assert proc._next_pressure == 1.02
    assert proc._single_candidate_satellite_checks[-1]["result"] == "small_single_unresolved"
    assert proc._single_candidate_attempt_history[-1]["failure_kind"] == "low"


def test_single_candidate_loop_escape_moves_below_low_side():
    proc = _build_single_candidate_proc([_rep("none") for _ in range(5)])
    proc._current_pressure = 0.78
    proc.start_pressure = 0.80
    proc._single_candidate_confirming = True
    proc.replicates_target = 5
    proc._single_candidate_attempt_history = [
        {
            "pressure": 0.80,
            "next_pressure": 0.78,
            "direction": "down",
            "reason": "multiple",
            "failure_kind": "high",
        }
    ]

    proc.onDecide()

    assert proc._next_pressure == 0.76
    assert proc._single_candidate_loop_detected is True
    assert proc._single_candidate_attempt_history[-1]["loop_detected"] is True
    assert proc._single_candidate_attempt_history[-1]["loop_escape_direction"] == "down"


def test_single_candidate_repeated_attempts_consume_budget():
    proc = _build_single_candidate_proc([_rep("multiple")])
    proc._single_candidate_attempt_count = proc.single_candidate_max_pressures

    proc.onDecide()

    assert proc.finalize.calls
    assert "pressure attempts" in proc._single_candidate_failure_message
    assert proc.continueScan.calls == []


def test_single_candidate_residue_starts_background_verification():
    proc = _build_single_candidate_proc([_rep("single", center=(100, 200), near_nozzle_residue=True)])
    calls = []
    proc._start_single_candidate_residue_verification = (
        lambda *, trigger, decision=None: calls.append((trigger, dict(decision or {})))
    )

    proc.onDecide()

    assert calls and calls[0][0] == "triage"
    assert proc.continueScan.calls == []


def test_single_candidate_persistent_residue_stops_with_cleanup_message():
    proc = _build_single_candidate_proc([_rep("single", center=(100, 200), near_nozzle_residue=True)])
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: (
                None,
                12000,
                np.zeros((20, 20), dtype=np.uint8),
                {
                    "near_nozzle_residue_detected": True,
                    "nozzle_contact_detected": False,
                    "nozzle_attached_area": 12000,
                },
            )
        )
    )
    proc.background_image = np.zeros((20, 20), dtype=np.uint8)
    proc.nozzle_center_px = (10, 10)

    proc._finish_single_candidate_residue_verification(
        np.zeros((20, 20), dtype=np.uint8),
        trigger="triage",
        decision={},
    )

    assert proc.finalize.calls
    assert "clean the printer head bottom" in proc._single_candidate_failure_message


def test_single_candidate_artifact_like_strong_residue_requests_second_verification():
    proc = _build_single_candidate_proc([_rep("single", center=(100, 200), near_nozzle_residue=True)])
    broad_components = [
        {
            "center": [544, 899],
            "bbox": [0, 342, 1088, 1114],
            "area_px": 426676,
        },
        {"center": [650, 500], "bbox": [610, 450, 90, 90], "area_px": 1600},
        {"center": [720, 600], "bbox": [690, 560, 80, 90], "area_px": 1400},
        {"center": [820, 700], "bbox": [790, 660, 80, 90], "area_px": 1400},
    ]
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: (
                [(544, 899), (650, 500), (720, 600), (820, 700)],
                193664,
                np.zeros((1536, 1088), dtype=np.uint8),
                {
                    "near_nozzle_residue_detected": False,
                    "near_nozzle_residue_area": 0,
                    "nozzle_contact_detected": True,
                    "nozzle_attached_area": 193664,
                    "component_count": 30,
                    "free_droplets": broad_components,
                },
            )
        )
    )
    proc.background_image = np.zeros((1536, 1088), dtype=np.uint8)
    proc.nozzle_center_px = (544, 320)
    recaptures = []
    proc._capture_single_candidate_residue_verification_frame = (
        lambda **kwargs: recaptures.append(dict(kwargs))
    )

    proc._finish_single_candidate_residue_verification(
        np.zeros((1536, 1088), dtype=np.uint8),
        trigger="triage",
        decision={"failure_kind": "low", "suggested_direction": "up"},
    )

    assert recaptures and recaptures[0]["repeated"] is True
    assert proc.finalize.calls == []
    assert proc.continueScan.calls == []
    assert proc._single_candidate_pending_residue_check["residue_severity"] == "artifact"
    assert proc._single_candidate_pending_residue_check["artifact_like"] is True


def test_single_candidate_repeated_artifact_like_residue_continues_up():
    proc = _build_single_candidate_proc([_rep("single", center=(100, 200), near_nozzle_residue=True)])
    response = (
        [(544, 899), (650, 500), (720, 600), (820, 700)],
        193664,
        np.zeros((1536, 1088), dtype=np.uint8),
        {
            "near_nozzle_residue_detected": False,
            "near_nozzle_residue_area": 0,
            "nozzle_contact_detected": True,
            "nozzle_attached_area": 193664,
            "component_count": 30,
            "free_droplets": [
                {"center": [544, 899], "bbox": [0, 342, 1088, 1114], "area_px": 426676},
                {"center": [650, 500], "bbox": [610, 450, 90, 90], "area_px": 1600},
                {"center": [720, 600], "bbox": [690, 560, 80, 90], "area_px": 1400},
                {"center": [820, 700], "bbox": [790, 660, 80, 90], "area_px": 1400},
            ],
        },
    )
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: response
        )
    )
    proc.background_image = np.zeros((1536, 1088), dtype=np.uint8)
    proc.nozzle_center_px = (544, 320)
    proc._capture_single_candidate_residue_verification_frame = lambda **_kwargs: None

    proc._finish_single_candidate_residue_verification(
        np.zeros((1536, 1088), dtype=np.uint8),
        trigger="triage",
        decision={"failure_kind": "low", "suggested_direction": "up"},
    )
    proc._finish_single_candidate_residue_verification(
        np.zeros((1536, 1088), dtype=np.uint8),
        trigger="triage",
        decision={"failure_kind": "low", "suggested_direction": "up"},
    )

    assert proc._next_pressure == 1.02
    assert proc.continueScan.calls
    assert proc.finalize.calls == []
    assert [c["residue_severity"] for c in proc._single_candidate_residue_checks] == [
        "artifact",
        "artifact",
    ]


def test_single_candidate_weak_residue_boolean_does_not_hard_stop():
    proc = _build_single_candidate_proc([_rep("single", center=(100, 200), near_nozzle_residue=True)])
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: (
                None,
                None,
                np.zeros((20, 20), dtype=np.uint8),
                {
                    "near_nozzle_residue_detected": True,
                    "near_nozzle_residue_area": 300,
                    "nozzle_contact_detected": False,
                    "nozzle_attached_area": 0,
                },
            )
        )
    )
    proc.background_image = np.zeros((20, 20), dtype=np.uint8)
    proc.nozzle_center_px = (10, 10)

    proc._finish_single_candidate_residue_verification(
        np.zeros((20, 20), dtype=np.uint8),
        trigger="triage",
        decision={"failure_kind": "low", "suggested_direction": "up"},
    )

    assert proc._next_pressure == 1.02
    assert proc.continueScan.calls
    assert proc.finalize.calls == []
    assert proc._single_candidate_residue_checks[-1]["residue_severity"] == "weak"


def test_single_candidate_moderate_residue_requests_second_verification():
    proc = _build_single_candidate_proc([_rep("single", center=(100, 200), near_nozzle_residue=True)])
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: (
                None,
                None,
                np.zeros((20, 20), dtype=np.uint8),
                {
                    "near_nozzle_residue_detected": True,
                    "near_nozzle_residue_area": 3000,
                    "nozzle_contact_detected": False,
                    "nozzle_attached_area": 0,
                },
            )
        )
    )
    proc.background_image = np.zeros((20, 20), dtype=np.uint8)
    proc.nozzle_center_px = (10, 10)
    recaptures = []
    proc._capture_single_candidate_residue_verification_frame = (
        lambda **kwargs: recaptures.append(dict(kwargs))
    )

    proc._finish_single_candidate_residue_verification(
        np.zeros((20, 20), dtype=np.uint8),
        trigger="triage",
        decision={},
    )

    assert recaptures and recaptures[0]["repeated"] is True
    assert proc.continueScan.calls == []
    assert proc.finalize.calls == []
    assert proc._single_candidate_pending_residue_check["residue_severity"] == "moderate"


def test_single_candidate_moderate_residue_that_clears_continues():
    proc = _build_single_candidate_proc([_rep("single", center=(100, 200), near_nozzle_residue=True)])
    responses = [
        (
            None,
            None,
            np.zeros((20, 20), dtype=np.uint8),
            {
                "near_nozzle_residue_detected": True,
                "near_nozzle_residue_area": 3000,
                "nozzle_contact_detected": False,
                "nozzle_attached_area": 0,
            },
        ),
        (
            None,
            None,
            np.zeros((20, 20), dtype=np.uint8),
            {
                "near_nozzle_residue_detected": False,
                "near_nozzle_residue_area": 0,
                "nozzle_contact_detected": False,
                "nozzle_attached_area": 0,
            },
        ),
    ]
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: responses.pop(0)
        )
    )
    proc.background_image = np.zeros((20, 20), dtype=np.uint8)
    proc.nozzle_center_px = (10, 10)
    proc._capture_single_candidate_residue_verification_frame = lambda **_kwargs: None

    proc._finish_single_candidate_residue_verification(
        np.zeros((20, 20), dtype=np.uint8),
        trigger="triage",
        decision={"failure_kind": "low", "suggested_direction": "up"},
    )
    proc._finish_single_candidate_residue_verification(
        np.zeros((20, 20), dtype=np.uint8),
        trigger="triage",
        decision={"failure_kind": "low", "suggested_direction": "up"},
    )

    assert proc._next_pressure == 1.02
    assert proc.continueScan.calls
    assert proc.finalize.calls == []
    assert [c["residue_severity"] for c in proc._single_candidate_residue_checks] == [
        "moderate",
        "clear",
    ]


def test_single_candidate_free_droplet_in_residue_check_is_transient_high_pressure():
    proc = _build_single_candidate_proc([_rep("single", center=(100, 200), near_nozzle_residue=True)])
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: (
                [(466, 896)],
                440,
                np.zeros((20, 20), dtype=np.uint8),
                {
                    "near_nozzle_residue_detected": True,
                    "near_nozzle_residue_area": 7373,
                    "nozzle_contact_detected": True,
                    "nozzle_attached_area": 440,
                },
            )
        )
    )
    proc.background_image = np.zeros((20, 20), dtype=np.uint8)
    proc.nozzle_center_px = (10, 10)

    proc._finish_single_candidate_residue_verification(
        np.zeros((20, 20), dtype=np.uint8),
        trigger="triage",
        decision={"failure_kind": "high", "suggested_direction": "down"},
    )

    assert proc._next_pressure == 0.98
    assert proc.continueScan.calls
    assert proc.finalize.calls == []
    assert proc._single_candidate_residue_checks[-1]["residue_severity"] == "weak"
    assert proc._single_candidate_residue_checks[-1]["free_droplet_count"] == 1


def test_single_candidate_disappearing_residue_steps_up_as_under_ejection():
    proc = _build_single_candidate_proc([_rep("single", center=(100, 200), near_nozzle_residue=True)])
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: (
                None,
                None,
                np.zeros((20, 20), dtype=np.uint8),
                {
                    "near_nozzle_residue_detected": False,
                    "nozzle_contact_detected": False,
                    "nozzle_attached_area": 0,
                },
            )
        )
    )
    proc.background_image = np.zeros((20, 20), dtype=np.uint8)
    proc.nozzle_center_px = (10, 10)

    proc._finish_single_candidate_residue_verification(
        np.zeros((20, 20), dtype=np.uint8),
        trigger="triage",
        decision={},
    )

    assert proc._next_pressure == 1.02
    assert proc.continueScan.calls
    assert proc.finalize.calls == []


def test_pressure_band_on_decide_escalates_ambiguous_after_min_reps():
    proc = _build_decide_proc(
        [
            _rep("single"),
            _rep("single"),
            _rep("single"),
            _rep("none"),
            _rep("none"),
        ]
    )

    proc.onDecide()

    assert proc.replicates_target == proc.escalate_to
    assert proc.continueReplicate.calls
    assert proc._store_calls == []
    assert proc._choose_calls == []
    assert proc._advance_calls == []


def test_pressure_band_on_decide_accepts_confident_multiple_at_min_reps():
    proc = _build_decide_proc(
        [
            _rep("multiple"),
            _rep("multiple"),
            _rep("multiple"),
            _rep("multiple"),
            _rep("none"),
        ]
    )

    proc.onDecide()

    assert proc.continueReplicate.calls == []
    assert proc._store_calls and proc._store_calls[0]["verdict"] == "multiple"
    assert proc._store_calls[0]["decision"].get("reason") == "multiple_confident"
    assert proc._store_calls[0]["escalated"] is False
    assert proc._choose_calls == ["multiple"]
    assert len(proc._advance_calls) == 1


def test_pressure_band_on_decide_uses_fallback_when_still_ambiguous_at_cap():
    proc = _build_decide_proc(
        [
            _rep("single"),
            _rep("single"),
            _rep("single"),
            _rep("single"),
            _rep("none"),
            _rep("none"),
            _rep("none"),
            _rep("none"),
            _rep("none"),
        ]
    )

    proc.onDecide()

    assert proc.continueReplicate.calls == []
    assert proc._store_calls and proc._store_calls[0]["verdict"] == "none"
    decision = proc._store_calls[0]["decision"]
    assert decision.get("reason") == "ambiguous_fallback"
    assert decision.get("fallback_verdict") == "none"
    assert proc._store_calls[0]["escalated"] is True
    assert proc._choose_calls == ["none"]
    assert len(proc._advance_calls) == 1


def test_pressure_band_on_decide_triggers_delay_retest_for_mixed_single_multiple():
    proc = _build_decide_proc(
        [
            _rep("multiple"),
            _rep("multiple"),
            _rep("single"),
            _rep("single"),
            _rep("none"),
        ]
    )
    retest_reasons = []
    proc._start_delay_retest = (
        lambda reason, verdict, counts, decision, confidence: retest_reasons.append(str(reason)) or True
    )

    proc.onDecide()

    assert retest_reasons == ["mixed_single_multiple"]
    assert proc._store_calls == []
    assert proc._choose_calls == []
    assert proc._advance_calls == []


def test_pressure_band_on_decide_triggers_delay_retest_for_edge_single():
    proc = _build_decide_proc(
        [
            _rep("single"),
            _rep("single"),
            _rep("single"),
            _rep("single"),
            _rep("single"),
        ]
    )
    proc.samples = [{"pressure": 1.24, "verdict": "multiple"}]
    retest_reasons = []
    proc._start_delay_retest = (
        lambda reason, verdict, counts, decision, confidence: retest_reasons.append(str(reason)) or True
    )

    proc.onDecide()

    assert retest_reasons == ["edge_single_with_upper_multiple"]
    assert proc._store_calls == []
    assert proc._choose_calls == []
    assert proc._advance_calls == []


def test_pressure_band_on_decide_triggers_preemptive_delay_retest_for_bottom_edge_single():
    proc = _build_decide_proc(
        [
            _rep("single", dy=1100, cy=1310),
            _rep("single", dy=1090, cy=1300),
            _rep("single", dy=1080, cy=1290),
            _rep("single", dy=1070, cy=1285),
            _rep("single", dy=1060, cy=1280),
        ]
    )
    retest_reasons = []
    proc._start_delay_retest = (
        lambda reason, verdict, counts, decision, confidence: retest_reasons.append(str(reason)) or True
    )

    proc.onDecide()

    assert retest_reasons == ["single_bottom_edge_preemptive"]
    assert proc._store_calls == []
    assert proc._choose_calls == []
    assert proc._advance_calls == []


def test_pressure_band_on_decide_skips_edge_retest_when_upper_multiple_is_far():
    proc = _build_decide_proc(
        [
            _rep("single"),
            _rep("single"),
            _rep("single"),
            _rep("single"),
            _rep("single"),
        ]
    )
    proc.samples = [{"pressure": 1.35, "verdict": "multiple"}]
    retest_reasons = []
    proc._start_delay_retest = (
        lambda reason, verdict, counts, decision, confidence: retest_reasons.append(str(reason)) or True
    )

    proc.onDecide()

    assert retest_reasons == []
    assert proc._store_calls
    assert proc._store_calls[0]["verdict"] == "single"
    assert proc._choose_calls == ["single"]
    assert len(proc._advance_calls) == 1


def test_pressure_band_on_decide_attached_stream_triggers_later_delay_retest():
    proc = _build_decide_proc(
        [
            {
                **_rep("single"),
                "nozzle_attached_area": 20000,
                "nozzle_wet": True,
            }
            for _ in range(5)
        ]
    )
    proc._active_classify_delay_us = 5350
    proc._base_classify_delay_us = 5850

    calls = []

    def _start(reason, verdict, counts, decision, confidence, **kwargs):
        calls.append(
            {
                "reason": str(reason),
                "direction": str(kwargs.get("direction", "")),
            }
        )
        return True

    proc._start_delay_retest = _start

    proc.onDecide()

    assert calls
    assert calls[0]["reason"] == "attached_stream_requires_later_delay"
    assert calls[0]["direction"] == "later"
    assert proc._store_calls == []
    assert proc._choose_calls == []
    assert proc._advance_calls == []


def test_pressure_band_on_decide_ignores_residue_only_attached_area_for_timing():
    proc = _build_decide_proc(
        [
            {
                **_rep("single"),
                "nozzle_attached_area": 20000,
                "nozzle_contact": False,
                "nozzle_wet": False,
                "near_nozzle_residue": True,
            }
            for _ in range(5)
        ]
    )
    proc._active_classify_delay_us = 5350
    proc._base_classify_delay_us = 5850

    calls = []
    proc._start_delay_retest = (
        lambda reason, verdict, counts, decision, confidence, **kwargs: calls.append(str(reason)) or True
    )

    proc.onDecide()

    assert calls == []
    assert proc._store_calls
    assert proc._store_calls[0]["verdict"] == "single"
    assert proc._choose_calls == ["single"]
    assert len(proc._advance_calls) == 1


def test_pressure_band_on_decide_uses_retest_replicate_target_without_escalation():
    proc = _build_decide_proc(
        [
            _rep("single"),
            _rep("single"),
            _rep("single"),
        ]
    )
    proc.min_reps = 5
    proc.replicates_target = 3
    proc._retest_mode_active = True
    proc.samples = []

    proc.onDecide()

    assert proc.continueReplicate.calls == []
    assert proc._store_calls
    assert proc._store_calls[0]["verdict"] == "single"


def test_pressure_band_on_decide_expands_to_full_reps_for_boundary_adjacent_single():
    proc = _build_decide_proc(
        [
            _rep("single"),
            _rep("single"),
            _rep("single"),
        ]
    )
    proc.replicates_target = 3
    proc.samples = [{"pressure": 1.24, "verdict": "multiple"}]
    proc._start_delay_retest = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("delay retest should not run before full replicate expansion")
    )

    proc.onDecide()

    assert proc.replicates_target == 5
    assert proc.continueReplicate.calls
    assert proc._store_calls == []
    assert proc._choose_calls == []
    assert proc._advance_calls == []
