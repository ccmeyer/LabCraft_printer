from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import PressureBandCalibrationProcess  # noqa: E402


def _rep(cls_name: str):
    return {
        "cls": str(cls_name),
        "center_px": None,
        "dy_min_px": None,
        "nozzle_attached_area": 0,
        "nozzle_wet": False,
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
