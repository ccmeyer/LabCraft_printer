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
    proc._delay_retest_done_for_pressure = False
    proc._delay_retest_in_progress = False
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
        lambda reason, verdict, counts, decision: retest_reasons.append(str(reason)) or True
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
        lambda reason, verdict, counts, decision: retest_reasons.append(str(reason)) or True
    )

    proc.onDecide()

    assert retest_reasons == ["edge_single_with_upper_multiple"]
    assert proc._store_calls == []
    assert proc._choose_calls == []
    assert proc._advance_calls == []
