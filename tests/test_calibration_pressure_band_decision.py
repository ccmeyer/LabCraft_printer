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
    nozzle_wet: bool = False,
    too_close: bool = False,
):
    if center is not None:
        center_value = tuple(center)
    else:
        center_value = None if cy is None else (550, int(cy))
    return {
        "cls": str(cls_name),
        "center_px": center_value,
        "dy_min_px": dy,
        "nozzle_attached_area": 0,
        "nozzle_contact": bool(nozzle_contact or nozzle_wet),
        "near_nozzle_residue": bool(near_nozzle_residue),
        "near_nozzle_residue_area": 12000 if near_nozzle_residue else 0,
        "near_nozzle_residue_components": 1 if near_nozzle_residue else 0,
        "nozzle_wet": bool(nozzle_wet),
        "too_close": bool(too_close),
        "frame_height_px": int(h),
        "stream_like_count": 0,
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
    proc._pulse_width_us = 1600
    proc._early_stop = False
    proc._stop_reason = None
    proc._terminate_at_pressure = None
    proc._single_candidate_confirming = False
    proc._single_candidate_candidate_pressure = None
    proc._single_candidate_selected_pressure = None
    proc._single_candidate_confirmation_summary = {}
    proc._single_candidate_residue_checks = []
    proc._single_candidate_failure_message = None
    proc._single_candidate_residue_check_in_progress = False
    proc._single_candidate_tested_pressures = []
    proc.continueReplicate = Recorder()
    proc.continueScan = Recorder()
    proc.finalize = Recorder()
    proc.stageChanged = Recorder()
    proc.calibrationError = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    proc._record_error = lambda *args, **kwargs: None
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
