from __future__ import annotations

import json

import pytest

from tools.stream_analysis import online_tail as mod
from tools.stream_analysis import segmented_tail as segmented_tail_mod


def _flow_fit_result(**overrides):
    result = {
        "fit_status": "ok",
        "steady_width_baseline_px": 74.0,
        "flow_rate_nl_per_us": 0.0187,
        "flow_intercept_nl": -1.2,
    }
    result.update(overrides)
    return result


def _flow_delay_summary(
    *,
    delay_us: int,
    delay_from_emergence_us: int,
    width_px: float = 74.0,
    accepted: bool = True,
):
    accepted_replicates = 1 if accepted else 0
    return {
        "delay_us": int(delay_us),
        "delay_from_emergence_us": int(delay_from_emergence_us),
        "attempted_replicates": 1,
        "accepted_replicates": accepted_replicates,
        "rejected_replicates": 1 - accepted_replicates,
        "median_width_px": float(width_px) if accepted else None,
        "delay_accepted": bool(accepted),
        "warnings": [],
    }


def _tail_frame_row(
    *,
    delay_us: int,
    delay_from_emergence_us: int,
    phase: str = "tail_scout",
    status: str = "accepted",
    width_px=None,
    tail_width_usable: bool | None = None,
    separated_from_nozzle_landmark: bool = False,
    tail_landmark_usable: bool | None = None,
    warnings=None,
    **extra,
):
    if tail_width_usable is None:
        tail_width_usable = bool(status == "accepted" and width_px is not None)
    if tail_landmark_usable is None:
        tail_landmark_usable = bool(status == "accepted" and separated_from_nozzle_landmark)
    row = {
        "phase": str(phase),
        "status": str(status),
        "delay_us": int(delay_us),
        "delay_from_emergence_us": int(delay_from_emergence_us),
        "replicate_index": 1,
        "qc": {
            "tail_qc_pass": bool(tail_width_usable),
            "tail_width_usable": bool(tail_width_usable),
            "tail_landmark_usable": bool(tail_landmark_usable),
        },
        "image_ref": {"capture_id": f"cap_{delay_us}"},
        "warnings": list(warnings or []),
        "attached_width_px": width_px,
        "tail_width_usable": bool(tail_width_usable),
        "separated_from_nozzle_landmark": bool(separated_from_nozzle_landmark),
        "tail_landmark_usable": bool(tail_landmark_usable),
        "landmark_reason": "separated_from_nozzle" if tail_landmark_usable else None,
    }
    row.update(dict(extra or {}))
    return row


def _window_candidate(step_index, width_px, *, y0_px=None, usable=True):
    y0 = 100 + int(step_index) * 20 if y0_px is None else int(y0_px)
    return {
        "step_index": int(step_index),
        "mode": "root_band" if int(step_index) == 0 else "lower_consistent_window",
        "y0_px": int(y0),
        "y1_px": int(y0 + 40),
        "median_width_px": None if width_px is None else float(width_px),
        "iqr_px": 0.5 if width_px is not None else None,
        "half_delta_px": 0.5 if width_px is not None else None,
        "valid_row_count": 40 if usable else 8,
        "width_usable": bool(usable and width_px is not None),
        "eligible_as_selected_window": bool(usable and width_px is not None),
    }


def _tail_summary_with_window_bank(
    *,
    delay_from_emergence_us,
    selected_width_px,
    selected_step_index,
    lower_step3_width_px,
    lower_step4_width_px=None,
    phase="tail_backtrack",
):
    delay_us = 3200 + int(delay_from_emergence_us)
    candidates = [
        _window_candidate(0, selected_width_px if int(selected_step_index) == 0 else selected_width_px + 20.0),
        _window_candidate(3, lower_step3_width_px),
    ]
    if lower_step4_width_px is not None:
        candidates.append(_window_candidate(4, lower_step4_width_px))
    return mod.summarize_online_stream_tail_delay(
        [
            _tail_frame_row(
                delay_us=delay_us,
                delay_from_emergence_us=int(delay_from_emergence_us),
                phase=phase,
                width_px=float(selected_width_px),
                attached_width_mode=(
                    "root_band" if int(selected_step_index) == 0 else "lower_consistent_window"
                ),
                selected_band_step_index=int(selected_step_index),
                selected_band_y0_px=100 + int(selected_step_index) * 20,
                selected_band_y1_px=140 + int(selected_step_index) * 20,
                tail_width_window_candidates=candidates,
            )
        ],
        baseline_width_px=95.0,
    )


def _segmented_tail_rows(widths, *, start_delay_us=0, step_us=100):
    return [
        {
            "phase": "tail_backtrack",
            "status": "accepted",
            "delay_from_emergence_us": int(start_delay_us + index * step_us),
            "attached_width_px": float(width),
            "tail_width_usable": True,
        }
        for index, width in enumerate(widths)
    ]


def _segmented_tail_pairs(pairs):
    return [
        {
            "phase": "tail_backtrack",
            "status": "accepted",
            "delay_from_emergence_us": int(delay_us),
            "attached_width_px": float(width),
            "tail_width_usable": True,
        }
        for delay_us, width in pairs
    ]


def test_segmented_tail_plateau_only_returns_no_tail_start():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_rows([70.0, 70.1, 69.9, 70.0, 70.1, 69.95]),
        baseline_width_px=70.0,
    )

    assert result["fit_status"] == "ok"
    assert result["model_name"] == segmented_tail_mod.MODEL_PLATEAU
    assert result["tail_start_delay_from_emergence_us"] is None


def test_segmented_tail_one_breakpoint_collapse_selects_breakpoint():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_rows([70, 70, 70, 66, 62, 58, 54]),
        baseline_width_px=70.0,
    )

    assert result["fit_status"] == "ok"
    assert result["model_name"] == segmented_tail_mod.MODEL_PLATEAU_DECLINE
    assert result["tail_start_delay_from_emergence_us"] == 200
    assert result["knee_delay_from_emergence_us"] is None


def test_segmented_tail_one_breakpoint_uses_25us_refined_breakpoint():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_rows([70, 70, 70, 67, 63, 59, 55]),
        baseline_width_px=70.0,
    )

    assert result["model_name"] == segmented_tail_mod.MODEL_PLATEAU_DECLINE
    assert result["tail_start_delay_from_emergence_us"] == 225
    assert result["tail_start_observed_delay"] is False
    assert result["breakpoint_observed_delays"] == [False]
    assert result["breakpoint_refinement_step_us"] == 25


def test_segmented_tail_shoulder_collapse_selects_earlier_shoulder_start():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_rows([70, 70, 70, 69, 68, 63, 58]),
        baseline_width_px=70.0,
    )

    assert result["fit_status"] == "ok"
    assert result["model_name"] == segmented_tail_mod.MODEL_PLATEAU_SHOULDER_COLLAPSE
    assert result["tail_start_delay_from_emergence_us"] == 200
    assert result["knee_delay_from_emergence_us"] == 400
    assert result["second_knee_delay_from_emergence_us"] is None


def test_segmented_tail_two_break_model_uses_25us_refined_knee():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_rows([70, 70, 70, 70, 69, 67, 63, 59, 55]),
        baseline_width_px=70.0,
    )
    two_break = result["models"][segmented_tail_mod.MODEL_PLATEAU_SHOULDER_COLLAPSE]

    assert two_break["tail_start_delay_from_emergence_us"] == 300
    assert two_break["knee_delay_from_emergence_us"] == 475
    assert two_break["breakpoint_observed_delays"] == [True, False]


def test_segmented_tail_multi_stage_shoulder_selects_three_break_model():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_rows([70, 70, 70, 70, 69.8, 69.4, 69.0, 68.6, 66, 62, 58, 54]),
        baseline_width_px=70.0,
    )

    assert result["fit_status"] == "ok"
    assert (
        result["model_name"]
        == segmented_tail_mod.MODEL_PLATEAU_GRADUAL_SHOULDER_STEEP_SHOULDER_COLLAPSE
    )
    assert result["tail_start_delay_from_emergence_us"] == 325
    assert result["knee_delay_from_emergence_us"] == 700
    assert result["second_knee_delay_from_emergence_us"] == 800
    assert result["breakpoint_delays_from_emergence_us"] == [325, 700, 800]
    assert result["breakpoint_observed_delays"] == [False, True, True]


def test_segmented_tail_three_break_uses_25us_refined_breakpoints_and_local_confirmation():
    pairs = []
    for delay_us in range(0, 1000, 100):
        width = 70.0
        if delay_us > 275:
            width += -15.0 * float(delay_us - 275) / 1000.0
        if delay_us > 475:
            width += -45.0 * float(delay_us - 475) / 1000.0
        if delay_us > 675:
            width += -100.0 * float(delay_us - 675) / 1000.0
        pairs.append((delay_us, width))

    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_pairs(pairs),
        baseline_width_px=70.0,
    )

    assert (
        result["model_name"]
        == segmented_tail_mod.MODEL_PLATEAU_GRADUAL_SHOULDER_STEEP_SHOULDER_COLLAPSE
    )
    assert result["tail_start_source"] == segmented_tail_mod.TAIL_START_SOURCE_THREE_BREAK_TAU1
    assert result["breakpoint_delays_from_emergence_us"] == [275, 475, 675]
    assert result["breakpoint_observed_delays"] == [False, False, False]
    assert result["tail_start_observed_delay"] is False
    assert result["local_confirmation"]["passed"] is True


def test_segmented_tail_highlighted_184202_shape_moves_start_earlier():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_pairs(
            [
                (1950, 66.0),
                (2450, 66.0),
                (2850, 66.0),
                (2900, 66.0),
                (2950, 66.0),
                (3000, 65.0),
                (3050, 64.5),
                (3100, 64.0),
                (3150, 63.0),
                (3200, 61.5),
                (3250, 58.0),
                (3300, 51.5),
                (3350, 39.0),
                (3400, 25.0),
            ]
        ),
        baseline_width_px=66.0,
    )

    assert (
        result["model_name"]
        == segmented_tail_mod.MODEL_PLATEAU_GRADUAL_SHOULDER_STEEP_SHOULDER_COLLAPSE
    )
    assert result["tail_start_delay_from_emergence_us"] == 2950
    assert result["knee_delay_from_emergence_us"] == 3225
    assert result["second_knee_delay_from_emergence_us"] == 3325


def test_segmented_tail_highlighted_184023_shape_moves_start_earlier():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_pairs(
            [
                (1950, 67.0),
                (2350, 67.0),
                (2400, 67.0),
                (2450, 67.0),
                (2500, 67.0),
                (2550, 67.0),
                (2600, 67.0),
                (2650, 67.0),
                (2700, 66.0),
                (2750, 66.0),
                (2800, 66.0),
                (2850, 66.0),
                (2900, 66.0),
                (2950, 66.0),
                (3000, 66.0),
                (3050, 66.0),
                (3100, 64.0),
                (3150, 64.0),
                (3200, 62.0),
                (3250, 58.0),
                (3300, 52.0),
                (3350, 39.0),
                (3400, 25.0),
            ]
        ),
        baseline_width_px=67.0,
    )

    assert (
        result["model_name"]
        == segmented_tail_mod.MODEL_PLATEAU_GRADUAL_SHOULDER_STEEP_SHOULDER_COLLAPSE
    )
    assert result["tail_start_delay_from_emergence_us"] == 3025
    assert result["knee_delay_from_emergence_us"] == 3200
    assert result["second_knee_delay_from_emergence_us"] == 3300


def test_segmented_tail_three_break_gate_blocks_early_weak_shoulder_overfit():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_pairs(
            [
                (1950, 67.0),
                (2050, 67.0),
                (2150, 67.0),
                (2250, 66.0),
                (2350, 66.5),
                (2450, 66.25),
                (2550, 66.5),
                (2650, 67.0),
                (2750, 66.5),
                (2850, 65.5),
                (2950, 65.5),
                (3050, 65.0),
                (3100, 65.0),
                (3150, 63.5),
                (3200, 62.5),
                (3250, 59.0),
                (3300, 53.0),
                (3350, 41.0),
                (3400, 27.0),
            ]
        ),
        baseline_width_px=66.5,
    )

    three_break = result["models"][
        segmented_tail_mod.MODEL_PLATEAU_GRADUAL_SHOULDER_STEEP_SHOULDER_COLLAPSE
    ]
    assert three_break["tail_start_delay_from_emergence_us"] == 2775
    assert result["model_name"] == segmented_tail_mod.MODEL_PLATEAU_SHOULDER_COLLAPSE
    assert result["tail_start_delay_from_emergence_us"] == 3075
    assert result["three_break_selection_gate"]["passed"] is False
    assert result["three_break_selection_gate"]["reason"] == "tail_start_advance_too_large"


def test_segmented_tail_local_rebound_uses_midpoint_between_three_and_two_breaks():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_pairs(
            [
                (2050, 66.0),
                (2550, 66.0),
                (2950, 65.5),
                (3000, 65.0),
                (3050, 65.5),
                (3100, 64.0),
                (3150, 63.5),
                (3200, 62.5),
                (3250, 59.0),
                (3300, 53.0),
                (3350, 41.0),
                (3400, 26.0),
            ]
        ),
        baseline_width_px=66.0,
    )

    assert result["model_name"] == segmented_tail_mod.MODEL_THREE_BREAK_TWO_BREAK_MIDPOINT
    assert result["tail_start_source"] == segmented_tail_mod.TAIL_START_SOURCE_THREE_TWO_MIDPOINT
    assert result["three_break_tail_start_delay_from_emergence_us"] == 2975
    assert result["two_break_tail_start_delay_from_emergence_us"] == 3125
    assert result["midpoint_tail_start_delay_from_emergence_us"] == 3050
    assert result["tail_start_delay_from_emergence_us"] == 3050
    assert result["knee_delay_from_emergence_us"] == 3225
    assert result["second_knee_delay_from_emergence_us"] == 3325
    assert result["local_confirmation"]["passed"] is False
    assert result["local_confirmation"]["reason"] == "final_drop_too_small"


def test_segmented_tail_weak_local_drop_uses_midpoint_between_three_and_two_breaks():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_pairs(
            [
                (1950, 67.0),
                (2350, 67.0),
                (2400, 67.0),
                (2450, 67.0),
                (2500, 67.0),
                (2550, 67.0),
                (2600, 67.0),
                (2650, 66.0),
                (2700, 66.0),
                (2750, 66.0),
                (2800, 66.0),
                (2850, 66.0),
                (2900, 66.0),
                (2950, 66.0),
                (3000, 66.0),
                (3050, 65.0),
                (3100, 64.5),
                (3150, 64.0),
                (3200, 62.0),
                (3250, 58.0),
                (3300, 52.0),
                (3350, 40.5),
                (3400, 26.0),
            ]
        ),
        baseline_width_px=67.0,
    )

    assert result["model_name"] == segmented_tail_mod.MODEL_THREE_BREAK_TWO_BREAK_MIDPOINT
    assert result["tail_start_source"] == segmented_tail_mod.TAIL_START_SOURCE_THREE_TWO_MIDPOINT
    assert result["three_break_tail_start_delay_from_emergence_us"] == 2975
    assert result["two_break_tail_start_delay_from_emergence_us"] == 3125
    assert result["midpoint_tail_start_delay_from_emergence_us"] == 3050
    assert result["tail_start_delay_from_emergence_us"] == 3050
    assert result["local_confirmation"]["passed"] is False
    assert result["local_confirmation"]["reason"] == "final_drop_too_small"


def test_segmented_tail_robust_to_plateau_outlier():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_rows([70.0, 70.1, 75.0, 70.0, 69.8, 67.0, 64.0, 61.0, 58.0]),
        baseline_width_px=70.0,
    )

    assert result["fit_status"] == "ok"
    assert result["tail_start_delay_from_emergence_us"] == 325


def test_segmented_tail_insufficient_points_returns_status():
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        _segmented_tail_rows([70.0, 69.5, 69.0]),
        baseline_width_px=70.0,
    )

    assert result["fit_status"] == "insufficient_usable_points"
    assert result["tail_start_delay_from_emergence_us"] is None


def test_segmented_tail_median_aggregates_duplicate_delays():
    rows = [
        {
            "phase": "tail_backtrack",
            "delay_from_emergence_us": 1000,
            "attached_width_px": width,
            "tail_width_usable": True,
        }
        for width in [70.0, 68.0, 69.0]
    ]
    rows.append(
        {
            "phase": "tail_backtrack",
            "delay_from_emergence_us": 1100,
            "attached_width_px": 67.0,
            "tail_width_usable": True,
        }
    )

    trace = segmented_tail_mod.build_tail_width_trace(rows)

    assert trace[0]["delay_from_emergence_us"] == 1000
    assert trace[0]["median_width_px"] == 69.0
    assert trace[0]["sample_count"] == 3


def test_plan_online_stream_tail_phase_anchors_on_last_accepted_flow_delay():
    plan = mod.plan_online_stream_tail_phase(
        flow_fit_result=_flow_fit_result(),
        priors={
            "condition_match": "exact",
            "tail_start_offset_us": 4200,
            "tail_coarse_step_us": 125,
        },
        emergence_time_us=3200,
        capture_budget={"captures_remaining_hard": 35},
        flow_delay_summaries=[
            _flow_delay_summary(delay_us=3850, delay_from_emergence_us=650),
            _flow_delay_summary(delay_us=4050, delay_from_emergence_us=850),
            _flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050),
        ],
    )

    assert plan["run_tail"] is True
    assert plan["search_method"] == "separation_landmark_backtrack_v1"
    assert plan["plan_source"] == "last_flow_delay_anchor"
    assert plan["scout_anchor_delay_us"] == 4250
    assert plan["scout_first_delay_us"] == 4750
    assert plan["scout_step_us"] == 500
    assert plan["backtrack_step_us"] == 50
    assert plan["planned_scout_delay_count"] == 10
    assert plan["max_scout_delay_count"] == 10
    assert plan["fine_prepad_us"] == 100
    assert plan["fine_postpad_us"] == 100
    assert plan["reserved_backtrack_capture_count"] == 15
    assert plan["recorded_tail_start_offset_us"] == 4200


def test_plan_online_stream_tail_phase_skips_when_flow_fit_is_unresolved():
    plan = mod.plan_online_stream_tail_phase(
        flow_fit_result=_flow_fit_result(fit_status="unresolved_insufficient_delays"),
        priors=None,
        emergence_time_us=3200,
        capture_budget={"captures_remaining_hard": 12},
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
    )

    assert plan["run_tail"] is False
    assert plan["skip_reason"] == "missing_flow_baseline"


def test_plan_online_stream_tail_phase_skips_when_remaining_hard_budget_cannot_fit_dense_sweep():
    plan = mod.plan_online_stream_tail_phase(
        flow_fit_result=_flow_fit_result(),
        priors=None,
        emergence_time_us=3200,
        capture_budget={"captures_remaining_hard": 26},
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
    )

    assert plan["run_tail"] is False
    assert plan["skip_reason"] == "capture_budget_exhausted"
    assert plan["reserved_backtrack_capture_count"] == 15
    assert plan["planned_scout_delay_count"] == 10
    assert plan["required_tail_capture_count"] == 35
    assert plan["required_tail_backtrack_capture_count"] == 15
    assert plan["required_tail_left_extension_capture_count"] == 10


def test_estimate_online_stream_tail_capture_requirements_exceeds_fixed_tail_reserve():
    estimate = mod.estimate_online_stream_tail_capture_requirements(
        scout_anchor_delay_us=4250,
        scout_first_delay_us=4750,
        scout_step_us=500,
        scout_replicates=1,
        max_scout_delay_count=10,
        backtrack_step_us=50,
        backtrack_replicates=1,
        fine_prepad_us=100,
        fine_postpad_us=100,
    )

    assert estimate["required_tail_scout_capture_count"] == 10
    assert estimate["required_tail_backtrack_capture_count"] == 15
    assert estimate["required_tail_left_extension_capture_count"] == 10
    assert estimate["required_tail_capture_count"] == 35
    assert estimate["required_tail_capture_count"] > 25
    assert estimate["minimum_tail_capture_count"] == 27


def test_plan_online_stream_tail_phase_skips_without_accepted_flow_anchor():
    plan = mod.plan_online_stream_tail_phase(
        flow_fit_result=_flow_fit_result(),
        priors=None,
        emergence_time_us=3200,
        capture_budget={"captures_remaining_hard": 12},
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050, accepted=False)],
    )

    assert plan["run_tail"] is False
    assert plan["skip_reason"] == "missing_flow_tail_anchor"


def test_summarize_online_stream_tail_delay_detects_separation_landmark():
    summary = mod.summarize_online_stream_tail_delay(
        [
            _tail_frame_row(
                delay_us=4750,
                delay_from_emergence_us=1550,
                width_px=None,
                tail_width_usable=False,
                separated_from_nozzle_landmark=True,
                tail_landmark_usable=True,
            )
        ],
        baseline_width_px=74.0,
    )

    assert summary["delay_accepted"] is True
    assert summary["tail_width_usable"] is False
    assert summary["tail_landmark_usable"] is True
    assert summary["separated_from_nozzle_landmark"] is True
    assert summary["landmark_detected"] is True
    assert summary["landmark_reason"] == "separated_from_nozzle"


def test_summarize_online_stream_tail_delay_treats_detached_continuation_handoff_as_separation():
    summary = mod.summarize_online_stream_tail_delay(
        [
            _tail_frame_row(
                delay_us=4750,
                delay_from_emergence_us=1550,
                status="rejected_width_qc",
                width_px=None,
                tail_width_usable=False,
                separated_from_nozzle_landmark=True,
                tail_landmark_usable=True,
                warnings=["residue_stub_with_detached_continuation"],
                separation_mode="detached_continuation_below_stub",
                effective_stream_owner="detached_continuation",
                residue_stub_with_detached_continuation=True,
            )
        ],
        baseline_width_px=74.0,
    )

    assert summary["delay_accepted"] is True
    assert summary["tail_width_usable"] is False
    assert summary["tail_landmark_usable"] is True
    assert summary["separated_from_nozzle_landmark"] is True
    assert summary["attached_width_unavailable_landmark"] is False
    assert summary["landmark_detected"] is True
    assert summary["landmark_reason"] == "separated_from_nozzle"


def test_summarize_online_stream_tail_delay_suppresses_width_only_scout_landmark_by_default():
    summary = mod.summarize_online_stream_tail_delay(
        [
            _tail_frame_row(
                delay_us=4750,
                delay_from_emergence_us=1550,
                width_px=69.0,
            )
        ],
        baseline_width_px=74.0,
    )

    assert summary["tail_width_usable"] is True
    assert summary["width_ratio_to_baseline"] <= 0.95
    assert summary["separated_from_nozzle_landmark"] is False
    assert summary["width_only_collapse_candidate"] is True
    assert summary["width_only_collapse_suppressed_as_scout_landmark"] is True
    assert summary["backup_width_collapse_landmark"] is False
    assert summary["landmark_detected"] is False
    assert summary["landmark_reason"] is None


def test_summarize_online_stream_tail_delay_uses_attached_width_unavailable_as_landmark():
    summary = mod.summarize_online_stream_tail_delay(
        [
            _tail_frame_row(
                delay_us=4750,
                delay_from_emergence_us=1550,
                status="rejected_width_qc",
                width_px=None,
                tail_width_usable=False,
                tail_landmark_usable=False,
                warnings=["attached_width_unavailable", "detached_near_bottom_warning"],
                failure_reason="attached near-nozzle width unavailable",
            )
        ],
        baseline_width_px=74.0,
    )

    assert summary["delay_accepted"] is True
    assert summary["tail_landmark_usable"] is True
    assert summary["attached_width_unavailable_landmark"] is True
    assert summary["landmark_detected"] is True
    assert summary["landmark_reason"] == "attached_width_unavailable"


def test_summarize_online_stream_tail_delay_keeps_bottom_warnings_out_of_landmark_logic():
    summary = mod.summarize_online_stream_tail_delay(
        [
            _tail_frame_row(
                delay_us=4750,
                delay_from_emergence_us=1550,
                width_px=74.0,
                warnings=["attached_bottom_guard_hit"],
                attached_bottom_guard_hit=True,
            ),
            _tail_frame_row(
                delay_us=4750,
                delay_from_emergence_us=1550,
                width_px=74.0,
                warnings=["detached_near_bottom_warning"],
                detached_near_bottom_warning=True,
            ),
        ],
        baseline_width_px=74.0,
    )

    assert summary["late_frame_warning"] is True
    assert summary["landmark_detected"] is False
    assert summary["landmark_reason"] is None


def test_summarize_online_stream_tail_delay_keeps_strong_tail_transition_as_scout_diagnostic_only():
    summary = mod.summarize_online_stream_tail_delay(
        [
            _tail_frame_row(
                delay_us=4750,
                delay_from_emergence_us=1550,
                width_px=73.0,
            )
        ],
        baseline_width_px=74.0,
    )

    assert summary["width_ratio_to_baseline"] < 0.99
    assert summary["strong_tail_candidate"] is True
    assert summary["landmark_detected"] is False
    assert summary["landmark_reason"] is None


def test_summarize_online_stream_tail_delay_adds_resolver_width_drop_metrics():
    shoulder = mod.summarize_online_stream_tail_delay(
        [_tail_frame_row(delay_us=4750, delay_from_emergence_us=1550, width_px=72.5)],
        baseline_width_px=74.0,
    )
    transition = mod.summarize_online_stream_tail_delay(
        [_tail_frame_row(delay_us=4800, delay_from_emergence_us=1600, width_px=71.5)],
        baseline_width_px=74.0,
    )
    collapse = mod.summarize_online_stream_tail_delay(
        [_tail_frame_row(delay_us=4850, delay_from_emergence_us=1650, width_px=70.0)],
        baseline_width_px=74.0,
    )

    assert shoulder["width_drop_from_baseline_px"] == 1.5
    assert shoulder["resolver_plateau_candidate"] is False
    assert shoulder["resolver_transition_candidate"] is False
    assert shoulder["resolver_collapse_candidate"] is False
    assert transition["width_drop_from_baseline_px"] == 2.5
    assert transition["resolver_transition_candidate"] is True
    assert transition["resolver_collapse_candidate"] is False
    assert collapse["width_drop_from_baseline_px"] == 4.0
    assert collapse["resolver_collapse_candidate"] is True


def test_lower_window_width_drop_is_not_classified_from_root_flow_baseline_without_window_baseline():
    rows = mod._classify_trace_rows(
        [
            {
                "phase": "tail_backtrack",
                "delay_us": 4750,
                "delay_from_emergence_us": 1550,
                "median_width_px": 52.0,
                "width_ratio_to_baseline": 52.0 / 74.0,
                "width_drop_from_baseline_px": 22.0,
                "tail_width_usable": True,
                "attached_width_mode": "lower_consistent_window",
                "selected_band_step_index": 3,
            }
        ]
    )

    assert rows[0]["window_baseline_status"] == "insufficient_window_baseline"
    assert rows[0]["classification_width_drop_from_baseline_px"] is None
    assert rows[0]["resolver_collapse_candidate"] is False
    assert rows[0]["strong_tail_candidate"] is False


def test_same_window_lower_band_collapse_is_classified_after_local_baseline():
    rows = mod._classify_trace_rows(
        [
            {
                "phase": "tail_backtrack",
                "delay_us": 4700,
                "delay_from_emergence_us": 1500,
                "median_width_px": 52.0,
                "tail_width_usable": True,
                "attached_width_mode": "lower_consistent_window",
                "selected_band_step_index": 3,
            },
            {
                "phase": "tail_backtrack",
                "delay_us": 4750,
                "delay_from_emergence_us": 1550,
                "median_width_px": 52.2,
                "tail_width_usable": True,
                "attached_width_mode": "lower_consistent_window",
                "selected_band_step_index": 3,
            },
            {
                "phase": "tail_backtrack",
                "delay_us": 4800,
                "delay_from_emergence_us": 1600,
                "median_width_px": 47.0,
                "tail_width_usable": True,
                "attached_width_mode": "lower_consistent_window",
                "selected_band_step_index": 3,
            },
        ]
    )

    assert rows[0]["window_baseline_status"] == "ok"
    assert rows[2]["window_width_drop_from_baseline_px"] == pytest.approx(5.1)
    assert rows[2]["resolver_collapse_candidate"] is True


def test_build_online_stream_tail_backtrack_plan_includes_dense_window_around_later_landmark():
    plan = mod.build_online_stream_tail_backtrack_plan(
        scout_anchor_delay_us=4250,
        left_endpoint_delay_us=4750,
        landmark_delay_us=5250,
        backtrack_step_us=50,
        fine_prepad_us=100,
        fine_postpad_us=100,
    )

    assert plan == [4650, 4700, 4750, 4800, 4850, 4900, 4950, 5000, 5050, 5100, 5150, 5200, 5250, 5300, 5350]


def test_build_online_stream_tail_backtrack_plan_clamps_dense_window_start_to_scout_anchor():
    plan = mod.build_online_stream_tail_backtrack_plan(
        scout_anchor_delay_us=4250,
        left_endpoint_delay_us=4250,
        landmark_delay_us=4750,
        backtrack_step_us=50,
        fine_prepad_us=100,
        fine_postpad_us=100,
    )

    assert plan == [4250, 4300, 4350, 4400, 4450, 4500, 4550, 4600, 4650, 4700, 4750, 4800, 4850]


def test_compress_online_stream_tail_backtrack_plan_preserves_dense_zone_near_landmark():
    plan = mod.build_online_stream_tail_backtrack_plan(
        scout_anchor_delay_us=4250,
        left_endpoint_delay_us=4250,
        landmark_delay_us=5250,
        backtrack_step_us=50,
        fine_prepad_us=100,
        fine_postpad_us=100,
    )

    compressed = mod.compress_online_stream_tail_backtrack_plan(
        delay_sequence=plan,
        left_endpoint_delay_us=4250,
        landmark_delay_us=5250,
        backtrack_step_us=50,
        backtrack_replicates=1,
        fine_postpad_us=100,
        available_capture_count=12,
    )

    assert compressed["compressed"] is True
    assert compressed["requested_capture_count"] == len(plan)
    assert compressed["applied_capture_count"] == 12
    assert compressed["delay_sequence"][0] == 4250
    assert compressed["delay_sequence"][-1] == 5350
    assert compressed["delay_sequence"][1:] == [4850, 4900, 4950, 5000, 5050, 5100, 5150, 5200, 5250, 5300, 5350]


def test_decide_online_stream_tail_next_action_switches_to_backtrack_on_landmark():
    decision = mod.decide_online_stream_tail_next_action(
        mode="scout",
        delay_summary={"delay_accepted": True, "landmark_detected": True, "landmark_reason": "separated_from_nozzle"},
        capture_budget={"exhausted": False},
        consecutive_failed_delays=0,
        attempted_delay_count=1,
        planned_delay_count=3,
    )

    assert decision["action"] == "switch_to_backtrack"
    assert decision["landmark_reason"] == "separated_from_nozzle"


def test_decide_online_stream_tail_next_action_keeps_width_only_scout_drop_scouting():
    summary = mod.summarize_online_stream_tail_delay(
        [_tail_frame_row(delay_us=4750, delay_from_emergence_us=1550, width_px=69.0)],
        baseline_width_px=74.0,
    )

    decision = mod.decide_online_stream_tail_next_action(
        mode="scout",
        delay_summary=summary,
        capture_budget={"exhausted": False},
        consecutive_failed_delays=0,
        attempted_delay_count=1,
        planned_delay_count=3,
        scout_summaries=[summary],
    )

    assert summary["width_only_collapse_candidate"] is True
    assert summary["landmark_reason"] is None
    assert decision["action"] == "continue"
    assert decision.get("tail_backup_landmark_confirmed", False) is False
    assert "tail_backup_landmark_unconfirmed" not in decision.get("warnings", [])


def test_decide_online_stream_tail_next_action_does_not_switch_on_severe_width_only_drop():
    summary = mod.summarize_online_stream_tail_delay(
        [_tail_frame_row(delay_us=4750, delay_from_emergence_us=1550, width_px=62.0)],
        baseline_width_px=74.0,
    )

    decision = mod.decide_online_stream_tail_next_action(
        mode="scout",
        delay_summary=summary,
        capture_budget={"exhausted": False},
        consecutive_failed_delays=0,
        attempted_delay_count=1,
        planned_delay_count=3,
        scout_summaries=[summary],
    )

    assert summary["width_only_collapse_candidate"] is True
    assert summary["landmark_detected"] is False
    assert decision["action"] == "continue"
    assert decision.get("tail_backup_landmark_confirmed", False) is False


def test_decide_online_stream_tail_next_action_does_not_switch_on_repeated_width_only_drop():
    first_summary = mod.summarize_online_stream_tail_delay(
        [_tail_frame_row(delay_us=4750, delay_from_emergence_us=1550, width_px=69.0)],
        baseline_width_px=74.0,
    )
    second_summary = mod.summarize_online_stream_tail_delay(
        [_tail_frame_row(delay_us=5250, delay_from_emergence_us=2050, width_px=68.5)],
        baseline_width_px=74.0,
    )

    decision = mod.decide_online_stream_tail_next_action(
        mode="scout",
        delay_summary=second_summary,
        capture_budget={"exhausted": False},
        consecutive_failed_delays=0,
        attempted_delay_count=2,
        planned_delay_count=4,
        scout_summaries=[first_summary, second_summary],
    )

    assert first_summary["width_only_collapse_candidate"] is True
    assert second_summary["width_only_collapse_candidate"] is True
    assert decision["action"] == "continue"
    assert decision.get("tail_backup_landmark_confirmed", False) is False


def test_decide_online_stream_tail_next_action_stops_when_scout_budget_ends_without_landmark():
    decision = mod.decide_online_stream_tail_next_action(
        mode="scout",
        delay_summary={"delay_accepted": True, "landmark_detected": False},
        capture_budget={"exhausted": False},
        consecutive_failed_delays=0,
        attempted_delay_count=3,
        planned_delay_count=3,
    )

    assert decision["action"] == "stop"
    assert decision["tail_phase_status"] == "unresolved_no_landmark"
    assert decision["termination_reason"] == "no_scout_landmark"


def test_decide_online_stream_tail_next_action_finishes_after_backtrack_window():
    decision = mod.decide_online_stream_tail_next_action(
        mode="backtrack",
        delay_summary={"delay_accepted": True},
        capture_budget={"exhausted": False},
        consecutive_failed_delays=0,
        attempted_delay_count=9,
        planned_delay_count=9,
    )

    assert decision["action"] == "finish_resolve"


def test_decide_online_stream_tail_next_action_keeps_scout_running_on_strong_tail_diagnostic_only():
    summary = mod.summarize_online_stream_tail_delay(
        [
            _tail_frame_row(
                delay_us=4750,
                delay_from_emergence_us=1550,
                width_px=73.0,
            )
        ],
        baseline_width_px=74.0,
    )

    decision = mod.decide_online_stream_tail_next_action(
        mode="scout",
        delay_summary=summary,
        capture_budget={"exhausted": False},
        consecutive_failed_delays=0,
        attempted_delay_count=1,
        planned_delay_count=3,
    )

    assert summary["strong_tail_candidate"] is True
    assert summary["landmark_detected"] is False
    assert decision["action"] == "continue"


def test_resolve_online_stream_tail_result_prefers_transition_before_confirmed_collapse():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=74.1)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=71.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=70.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=69.0)],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
    )

    assert resolved["tail_phase"]["status"] == "captured"
    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] == 1150
    assert resolved["tail_phase"]["confirmed_collapse_delay_from_emergence_us"] == 1200
    assert resolved["tail_phase"]["tail_start_evidence"] == "backtrack_width_departure"
    assert resolved["tail_phase"]["tail_start_selection_method"] == "latest_transition_before_confirmed_collapse"
    assert resolved["predicted_stream_duration_us"] == 1150
    assert resolved["predicted_volume_nl"] is not None


def test_resolve_online_stream_tail_result_promotes_segmented_shadow_to_controlling_runtime():
    backtrack_summaries = [
        mod.summarize_online_stream_tail_delay(
            [
                _tail_frame_row(
                    delay_us=delay_us,
                    delay_from_emergence_us=delay_us - 3200,
                    phase="tail_backtrack",
                    width_px=width_px,
                )
            ],
            baseline_width_px=74.0,
        )
        for delay_us, width_px in [
            (4300, 74.1),
            (4350, 73.8),
            (4400, 72.0),
            (4450, 70.0),
            (4500, 65.0),
            (4550, 60.0),
        ]
    ]

    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=backtrack_summaries,
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
    )

    runtime_tail_start = resolved["tail_phase"]["tail_start_delay_from_emergence_us"]
    legacy_tail_start = resolved["tail_phase"]["legacy_tail_start_delay_from_emergence_us"]
    legacy_predicted_volume = resolved["tail_phase"]["legacy_predicted_volume_nl"]
    segmented = resolved["tail_phase"]["segmented_tail"]
    assert segmented["status"] == "ok"
    assert segmented["usable_point_count"] >= 6
    assert segmented["tail_start_delay_from_emergence_us"] is not None
    assert segmented["fit_points"]
    assert resolved["tail_phase"]["segmented_tail_controlling"] is True
    assert resolved["tail_phase"]["segmented_tail_control_reason"] == "segmented_tail_promoted"
    assert resolved["tail_phase"]["segmented_tail_legacy_fallback_used"] is False
    assert resolved["tail_phase"]["tail_start_selection_method"] == "segmented_regression"
    assert str(resolved["tail_phase"]["tail_start_evidence"]).startswith("segmented_")
    assert runtime_tail_start == segmented["tail_start_delay_from_emergence_us"]
    assert resolved["predicted_stream_duration_us"] == segmented["tail_start_delay_from_emergence_us"]
    expected_segmented_volume = -1.2 + (
        0.0187 * float(segmented["tail_start_delay_from_emergence_us"])
    )
    assert segmented["predicted_stream_duration_us"] == segmented["tail_start_delay_from_emergence_us"]
    assert segmented["predicted_volume_nl"] == pytest.approx(expected_segmented_volume)
    assert segmented["runtime_predicted_volume_nl"] == pytest.approx(legacy_predicted_volume)
    assert resolved["predicted_volume_nl"] == pytest.approx(expected_segmented_volume)
    assert segmented["predicted_volume_delta_from_runtime_nl"] == pytest.approx(
        expected_segmented_volume - legacy_predicted_volume
    )
    assert legacy_tail_start is not None
    assert resolved["tail_phase"]["legacy_tail_start_selection_method"] is not None
    assert (
        resolved["tail_phase"]["segmented_tail_start_delay_from_emergence_us"]
        == segmented["tail_start_delay_from_emergence_us"]
    )
    assert resolved["tail_phase"]["segmented_tail_start_delta_from_runtime_us"] == (
        segmented["tail_start_delay_from_emergence_us"] - legacy_tail_start
    )
    assert (
        resolved["tail_phase"]["segmented_predicted_stream_duration_us"]
        == segmented["predicted_stream_duration_us"]
    )
    assert resolved["tail_phase"]["segmented_predicted_volume_nl"] == pytest.approx(
        segmented["predicted_volume_nl"]
    )
    assert resolved["tail_phase"]["segmented_predicted_volume_delta_from_runtime_nl"] == pytest.approx(
        segmented["predicted_volume_delta_from_runtime_nl"]
    )


def test_resolve_online_stream_tail_result_can_leave_segmented_shadow_noncontrolling(monkeypatch):
    def _segmented_tail(**kwargs):
        return {
            "status": "ok",
            "fit_status": "ok",
            "tail_start_source": segmented_tail_mod.TAIL_START_SOURCE_THREE_TWO_MIDPOINT,
            "tail_start_delay_from_emergence_us": 1175,
            "tail_start_delta_from_runtime_us": None,
            "usable_point_count": 6,
            "fit_points": [{"delay_from_emergence_us": 1175, "width_px": 70.0}],
            "trace": [{"delay_from_emergence_us": 1175, "median_width_px": 70.0}],
        }

    monkeypatch.setattr(mod, "evaluate_online_stream_segmented_tail_shadow", _segmented_tail)

    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=74.1)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=71.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=70.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=69.0)],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
        analysis_config={"segmented_tail_online_controlling_enabled": False},
    )

    assert resolved["tail_phase"]["segmented_tail_controlling"] is False
    assert resolved["tail_phase"]["segmented_tail_control_reason"] == "segmented_tail_control_disabled"
    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] == 1150
    assert resolved["predicted_stream_duration_us"] == 1150
    assert resolved["tail_phase"]["segmented_predicted_stream_duration_us"] == 1175


def test_summarize_online_stream_tail_delay_median_aggregates_window_candidates():
    summary = mod.summarize_online_stream_tail_delay(
        [
            _tail_frame_row(
                delay_us=6100,
                delay_from_emergence_us=2900,
                width_px=95.0,
                tail_width_window_candidates=[
                    _window_candidate(0, 95.0),
                    _window_candidate(3, 78.0),
                ],
            ),
            _tail_frame_row(
                delay_us=6100,
                delay_from_emergence_us=2900,
                width_px=94.0,
                tail_width_window_candidates=[
                    _window_candidate(0, 94.0),
                    _window_candidate(3, 76.0),
                ],
            ),
        ],
        baseline_width_px=95.0,
    )

    by_step = {
        int(candidate["step_index"]): candidate
        for candidate in summary["tail_width_window_candidates"]
    }
    assert by_step[0]["median_width_px"] == pytest.approx(94.5)
    assert by_step[3]["median_width_px"] == pytest.approx(77.0)
    assert by_step[3]["sample_count"] == 2
    assert by_step[3]["usable_sample_count"] == 2


def test_segmented_shadow_uses_uniform_lower_window_trace_for_mixed_selected_windows():
    delays = list(range(2800, 3600, 50))
    lower_widths = [
        77.0,
        77.0,
        77.0,
        77.0,
        76.5,
        77.0,
        76.0,
        76.0,
        75.0,
        73.5,
        72.0,
        69.0,
        65.0,
        57.0,
        43.5,
        26.0,
    ]
    selected_steps = [0] * 6 + [3] * 10
    selected_widths = [95.0] * 6 + lower_widths[6:]
    backtrack_summaries = [
        _tail_summary_with_window_bank(
            delay_from_emergence_us=delay,
            selected_width_px=selected_width,
            selected_step_index=selected_step,
            lower_step3_width_px=lower_width,
        )
        for delay, selected_width, selected_step, lower_width in zip(
            delays,
            selected_widths,
            selected_steps,
            lower_widths,
        )
    ]

    segmented = mod.evaluate_online_stream_segmented_tail_shadow(
        scout_summaries=[],
        backtrack_summaries=backtrack_summaries,
        baseline_width_px=95.0,
        runtime_tail_start_delay_from_emergence_us=3250,
        analysis_config={},
    )

    assert segmented["status"] == "ok"
    assert segmented["segmented_tail_source_trace_kind"] == "uniform_window"
    assert segmented["segmented_tail_source_window_step_index"] == 3
    assert segmented["segmented_tail_target_selected_window_step_index"] == 3
    assert segmented["segmented_tail_source_baseline_width_px"] == pytest.approx(77.0)
    assert segmented["segmented_tail_window_selection_reason"] == "selected_lowest_uniform_window"
    assert segmented["tail_start_delay_from_emergence_us"] >= 3150
    first_trace_widths = [
        point["median_width_px"]
        for point in segmented["trace"][:6]
    ]
    assert min(first_trace_widths) >= 76.5
    assert max(first_trace_widths) <= 77.0
    assert segmented["window_trace"][0]["selected_band_step_index"] == 3
    assert segmented["segmented_tail_candidate_window_traces"][0]["qualified"] is True


def test_segmented_shadow_uses_lowest_selected_lower_window_over_deeper_candidates():
    delays = list(range(2800, 3600, 50))
    lower_step3_widths = [
        77.0,
        77.0,
        77.0,
        77.0,
        76.5,
        77.0,
        76.0,
        76.0,
        75.0,
        73.5,
        72.0,
        69.0,
        65.0,
        57.0,
        43.5,
        26.0,
    ]
    lower_step4_widths = [
        70.0,
        70.0,
        70.0,
        70.0,
        70.0,
        70.0,
        69.0,
        69.0,
        68.0,
        67.0,
        65.0,
        62.0,
        58.0,
        50.0,
        35.0,
        20.0,
    ]
    backtrack_summaries = [
        _tail_summary_with_window_bank(
            delay_from_emergence_us=delay,
            selected_width_px=width,
            selected_step_index=3,
            lower_step3_width_px=width,
            lower_step4_width_px=step4_width,
        )
        for delay, width, step4_width in zip(delays, lower_step3_widths, lower_step4_widths)
    ]

    segmented = mod.evaluate_online_stream_segmented_tail_shadow(
        scout_summaries=[],
        backtrack_summaries=backtrack_summaries,
        baseline_width_px=95.0,
        runtime_tail_start_delay_from_emergence_us=3250,
        analysis_config={},
    )

    assert segmented["segmented_tail_source_trace_kind"] == "uniform_window"
    assert segmented["segmented_tail_source_window_step_index"] == 3
    assert segmented["segmented_tail_target_selected_window_step_index"] == 3
    assert [
        trace["step_index"]
        for trace in segmented["segmented_tail_candidate_window_traces"]
    ] == [3, 4]


def test_segmented_shadow_uses_lowest_selected_window_after_brief_shallower_selection():
    delays = list(range(2800, 3600, 50))
    step3_widths = [
        77.0,
        77.0,
        77.0,
        77.0,
        76.5,
        77.0,
        76.0,
        76.0,
        75.0,
        73.5,
        72.0,
        69.0,
        65.0,
        57.0,
        43.5,
        26.0,
    ]
    selected_steps = [0] * 5 + [2] * 3 + [3] * 8
    selected_widths = [
        95.0,
        95.0,
        95.0,
        95.0,
        95.0,
        80.0,
        79.5,
        79.0,
    ] + step3_widths[8:]
    backtrack_summaries = [
        _tail_summary_with_window_bank(
            delay_from_emergence_us=delay,
            selected_width_px=selected_width,
            selected_step_index=selected_step,
            lower_step3_width_px=step3_width,
        )
        for delay, selected_width, selected_step, step3_width in zip(
            delays,
            selected_widths,
            selected_steps,
            step3_widths,
        )
    ]

    segmented = mod.evaluate_online_stream_segmented_tail_shadow(
        scout_summaries=[],
        backtrack_summaries=backtrack_summaries,
        baseline_width_px=95.0,
        runtime_tail_start_delay_from_emergence_us=3250,
        analysis_config={},
    )

    assert segmented["segmented_tail_source_trace_kind"] == "uniform_window"
    assert segmented["segmented_tail_source_window_step_index"] == 3
    assert segmented["segmented_tail_target_selected_window_step_index"] == 3
    assert segmented["segmented_tail_window_selection_reason"] == "selected_lowest_uniform_window"


def test_segmented_shadow_falls_back_when_lowest_selected_window_is_unqualified():
    delays = list(range(2800, 3600, 50))
    unstable_step3_widths = [
        77.0,
        80.0,
        77.0,
        79.0,
        78.0,
        77.0,
        76.0,
        76.0,
        75.0,
        73.5,
        72.0,
        69.0,
        65.0,
        57.0,
        43.5,
        26.0,
    ]
    stable_step4_widths = [
        70.0,
        70.0,
        70.0,
        70.0,
        70.0,
        70.0,
        69.0,
        69.0,
        68.0,
        67.0,
        65.0,
        62.0,
        58.0,
        50.0,
        35.0,
        20.0,
    ]
    backtrack_summaries = [
        _tail_summary_with_window_bank(
            delay_from_emergence_us=delay,
            selected_width_px=width,
            selected_step_index=3,
            lower_step3_width_px=width,
            lower_step4_width_px=step4_width,
        )
        for delay, width, step4_width in zip(delays, unstable_step3_widths, stable_step4_widths)
    ]

    segmented = mod.evaluate_online_stream_segmented_tail_shadow(
        scout_summaries=[],
        backtrack_summaries=backtrack_summaries,
        baseline_width_px=95.0,
        runtime_tail_start_delay_from_emergence_us=3250,
        analysis_config={},
    )

    assert segmented["segmented_tail_source_trace_kind"] == "selected_window_fallback"
    assert segmented["segmented_tail_source_window_step_index"] is None
    assert segmented["segmented_tail_target_selected_window_step_index"] == 3
    assert segmented["segmented_tail_window_selection_reason"] == "selected_lowest_window_unqualified"
    diagnostics = {
        int(trace["step_index"]): trace
        for trace in segmented["segmented_tail_candidate_window_traces"]
    }
    assert diagnostics[3]["qualified"] is False
    assert diagnostics[3]["selection_reason"] == "unstable_window_baseline"
    assert diagnostics[4]["qualified"] is True


def test_segmented_shadow_falls_back_to_selected_trace_without_candidate_bank():
    backtrack_summaries = [
        mod.summarize_online_stream_tail_delay(
            [
                _tail_frame_row(
                    delay_us=6000 + 50 * index,
                    delay_from_emergence_us=2800 + 50 * index,
                    phase="tail_backtrack",
                    width_px=width_px,
                    attached_width_mode="lower_consistent_window" if index >= 6 else "root_band",
                    selected_band_step_index=3 if index >= 6 else 0,
                    selected_band_y0_px=160 if index >= 6 else 100,
                    selected_band_y1_px=200 if index >= 6 else 140,
                )
            ],
            baseline_width_px=95.0,
        )
        for index, width_px in enumerate([95, 95, 95, 95, 95, 95, 76, 75, 72, 68])
    ]

    segmented = mod.evaluate_online_stream_segmented_tail_shadow(
        scout_summaries=[],
        backtrack_summaries=backtrack_summaries,
        baseline_width_px=95.0,
        runtime_tail_start_delay_from_emergence_us=3250,
        analysis_config={},
    )

    assert segmented["segmented_tail_source_trace_kind"] == "selected_window_fallback"
    assert segmented["segmented_tail_window_selection_reason"] == "missing_window_candidate_bank"
    assert segmented["segmented_tail_source_window_step_index"] is None
    assert segmented["segmented_tail_target_selected_window_step_index"] == 3


def test_resolve_online_stream_tail_result_can_skip_segmented_shadow_for_previews():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4750, delay_from_emergence_us=1550, width_px=60.0)],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4300 + 50 * index,
                        delay_from_emergence_us=1100 + 50 * index,
                        phase="tail_backtrack",
                        width_px=width_px,
                    )
                ],
                baseline_width_px=74.0,
            )
            for index, width_px in enumerate([74, 73, 72, 70, 66, 61])
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
        run_segmented_tail_shadow=False,
    )

    assert "segmented_tail" not in resolved["tail_phase"]
    assert "segmented_tail_start_delay_from_emergence_us" not in resolved["tail_phase"]
    assert resolved["tail_phase"]["segmented_tail_controlling"] is False
    assert resolved["tail_phase"]["segmented_tail_control_reason"] == "segmented_tail_not_run"


def test_resolve_online_stream_tail_result_omits_segmented_shadow_when_disabled():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4750, delay_from_emergence_us=1550, width_px=60.0)],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4300 + 50 * index,
                        delay_from_emergence_us=1100 + 50 * index,
                        phase="tail_backtrack",
                        width_px=width_px,
                    )
                ],
                baseline_width_px=74.0,
            )
            for index, width_px in enumerate([74, 73, 72, 70, 66, 61])
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
        analysis_config={"segmented_tail_online_shadow_enabled": False},
    )

    assert "segmented_tail" not in resolved["tail_phase"]
    assert "segmented_tail_start_delay_from_emergence_us" not in resolved["tail_phase"]
    assert resolved["tail_phase"]["segmented_tail_controlling"] is False
    assert resolved["tail_phase"]["segmented_tail_control_reason"] == "segmented_tail_disabled"


def test_resolve_online_stream_tail_result_records_segmented_shadow_insufficient_points():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4300,
                        delay_from_emergence_us=1100,
                        phase="tail_backtrack",
                        width_px=74.1,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
    )

    segmented = resolved["tail_phase"]["segmented_tail"]
    assert segmented["status"] == "insufficient_usable_points"
    assert segmented["usable_point_count"] == 1
    assert resolved["tail_phase"]["segmented_tail_controlling"] is False
    assert resolved["tail_phase"]["segmented_tail_legacy_fallback_used"] is True
    assert resolved["tail_phase"]["segmented_tail_control_reason"] == "segmented_tail_insufficient_usable_points"
    assert resolved["predicted_stream_duration_us"] == resolved["tail_phase"]["legacy_predicted_stream_duration_us"]


def test_resolve_online_stream_tail_result_can_fail_closed_when_segmented_fallback_disabled():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4300,
                        delay_from_emergence_us=1100,
                        phase="tail_backtrack",
                        width_px=74.1,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
        analysis_config={"segmented_tail_online_legacy_fallback_enabled": False},
    )

    assert resolved["tail_phase"]["segmented_tail"]["status"] == "insufficient_usable_points"
    assert resolved["tail_phase"]["segmented_tail_controlling"] is False
    assert resolved["tail_phase"]["segmented_tail_legacy_fallback_used"] is False
    assert resolved["tail_phase"]["status"] == "unresolved_segmented_tail_unavailable"
    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] is None
    assert resolved["predicted_stream_duration_us"] is None
    assert resolved["predicted_volume_nl"] is None
    assert "unresolved_segmented_tail_unavailable" in resolved["warnings"]
    assert resolved["tail_phase"]["segmented_tail"]["min_usable_points"] == 6


def test_resolve_online_stream_tail_result_selects_latest_material_transition():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=74.1)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=71.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=70.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=70.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4500, delay_from_emergence_us=1300, phase="tail_backtrack", width_px=69.0)],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
    )

    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] == 1200
    assert resolved["tail_phase"]["confirmed_collapse_delay_from_emergence_us"] == 1250
    assert resolved["tail_phase"]["tail_start_selection_method"] == "latest_transition_before_confirmed_collapse"


def test_resolve_online_stream_tail_result_prefers_backtrack_rows_over_duplicate_scout_delays():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "scout_anchor_delay_from_emergence_us": 1050,
            "backtrack_step_us": 50,
            "fine_prepad_us": 100,
            "fine_postpad_us": 100,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4750, delay_from_emergence_us=1550, phase="tail_scout", width_px=74.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=5250,
                        delay_from_emergence_us=2050,
                        phase="tail_scout",
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            ),
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4700, delay_from_emergence_us=1500, phase="tail_backtrack", width_px=74.1)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4750, delay_from_emergence_us=1550, phase="tail_backtrack", width_px=71.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4800, delay_from_emergence_us=1600, phase="tail_backtrack", width_px=70.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4850, delay_from_emergence_us=1650, phase="tail_backtrack", width_px=69.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=5250,
                        delay_from_emergence_us=2050,
                        phase="tail_backtrack",
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 5250,
            "backtrack_left_delay_us": 4750,
            "landmark_reason": "separated_from_nozzle",
        },
    )

    assert resolved["tail_phase"]["status"] == "captured"
    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] == 1550
    assert resolved["tail_phase"]["confirmed_collapse_delay_from_emergence_us"] == 1600
    assert resolved["tail_phase"]["tail_start_evidence"] == "backtrack_width_departure"
    assert resolved["tail_phase"]["tail_start_selection_method"] == "latest_transition_before_confirmed_collapse"


def test_resolve_online_stream_tail_result_ignores_early_strong_tail_dip_before_later_plateau():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=74.1)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=70.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=74.2)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=71.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4500, delay_from_emergence_us=1300, phase="tail_backtrack", width_px=70.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4550, delay_from_emergence_us=1350, phase="tail_backtrack", width_px=69.0)],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
    )

    assert resolved["tail_phase"]["status"] == "captured"
    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] == 1250
    assert resolved["tail_phase"]["confirmed_collapse_delay_from_emergence_us"] == 1300
    assert resolved["tail_phase"]["right_bracket_delay_from_emergence_us"] == 1300
    assert resolved["tail_phase"]["right_bracket_reason"] == "strong_tail_transition"
    assert resolved["tail_phase"]["tail_start_selection_method"] == "latest_transition_before_confirmed_collapse"

def test_resolve_online_stream_tail_result_uses_midpoint_without_prelandmark_departure():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=74.1)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=73.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=72.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=70.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4500, delay_from_emergence_us=1300, phase="tail_backtrack", width_px=69.0)],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
    )

    assert resolved["tail_phase"]["status"] == "captured"
    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] == 1200
    assert resolved["tail_phase"]["tail_start_evidence"] == "plateau_right_bracket_midpoint"
    assert resolved["tail_phase"]["tail_start_selection_method"] == "plateau_confirmed_collapse_midpoint"


def test_resolve_online_stream_tail_result_uses_flow_anchor_when_tail_plateau_is_missing():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=70.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=69.0)],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4300,
            "landmark_reason": "separated_from_nozzle",
        },
    )

    assert resolved["tail_phase"]["status"] == "captured"
    assert resolved["tail_phase"]["synthetic_left_bracket_used"] is True
    assert resolved["tail_phase"]["synthetic_left_bracket_delay_from_emergence_us"] == 1050
    assert resolved["tail_phase"]["synthetic_left_bracket_source"] == "last_accepted_flow_anchor"
    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] == 1075
    assert resolved["tail_phase"]["confirmed_collapse_delay_from_emergence_us"] == 1100
    assert resolved["tail_phase"]["right_bracket_reason"] == "strong_tail_transition"
    assert resolved["tail_phase"]["tail_start_evidence"] == "flow_anchor_right_bracket_midpoint"
    assert (
        resolved["tail_phase"]["tail_start_selection_method"]
        == "flow_anchor_confirmed_collapse_midpoint"
    )
    assert resolved["predicted_volume_nl"] is not None
    assert "unresolved_missing_left_bracket" not in resolved["tail_phase"]["warnings"]


def test_resolve_online_stream_tail_result_keeps_missing_left_bracket_when_flow_anchor_is_not_plateau():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=70.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=69.0)],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[
            _flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050, width_px=73.0)
        ],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4300,
            "landmark_reason": "separated_from_nozzle",
        },
    )

    assert resolved["tail_phase"]["status"] == "unresolved_missing_left_bracket"
    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] is None
    assert resolved["tail_phase"]["synthetic_left_bracket_used"] is False
    assert "unresolved_missing_left_bracket" in resolved["tail_phase"]["warnings"]


def test_resolve_online_stream_tail_result_captures_backup_width_collapse_landmark():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4750, delay_from_emergence_us=1550, width_px=69.0)],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=74.1)],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "strong_width_collapse_backup",
        },
    )

    assert resolved["tail_phase"]["status"] == "captured"
    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] == 1325
    assert resolved["tail_phase"]["tail_start_evidence"] == "plateau_right_bracket_midpoint"
    assert resolved["tail_phase"]["tail_start_selection_method"] == "plateau_confirmed_collapse_midpoint"
    assert resolved["tail_phase"]["confirmed_collapse_delay_from_emergence_us"] is None


def test_resolve_online_stream_tail_result_uses_midpoint_when_width_unavailable_is_first_right_bracket():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        status="rejected_width_qc",
                        width_px=None,
                        tail_width_usable=False,
                        tail_landmark_usable=False,
                        warnings=["attached_width_unavailable"],
                        failure_reason="attached near-nozzle width unavailable",
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=74.1)],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "attached_width_unavailable",
        },
    )

    assert resolved["tail_phase"]["status"] == "captured"
    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] == 1325
    assert resolved["tail_phase"]["tail_start_evidence"] == "plateau_right_bracket_midpoint"
    assert resolved["tail_phase"]["tail_start_selection_method"] == "plateau_confirmed_collapse_midpoint"
    assert resolved["tail_phase"]["confirmed_collapse_delay_from_emergence_us"] is None


def test_resolve_online_stream_tail_result_applies_settling_rule_to_long_separated_shoulder():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
            "analysis_config": {
                "tail_settling_rule_enabled": True,
                "segmented_tail_online_controlling_enabled": False,
            },
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4650,
                        delay_from_emergence_us=1450,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=74.1)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=71.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=72.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=70.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4500, delay_from_emergence_us=1300, phase="tail_backtrack", width_px=69.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4550, delay_from_emergence_us=1350, phase="tail_backtrack", width_px=69.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4600, delay_from_emergence_us=1400, phase="tail_backtrack", width_px=68.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4650,
                        delay_from_emergence_us=1450,
                        phase="tail_backtrack",
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4650,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
    )

    tail_phase = resolved["tail_phase"]
    assert tail_phase["tail_start_selection_method"] == mod.TAIL_SETTLING_SELECTION_METHOD
    assert tail_phase["tail_settling_rule_applied"] is True
    assert tail_phase["tail_settling_rule_reason"] == "applied"
    assert tail_phase["tail_start_delay_from_emergence_us"] == 1250
    assert tail_phase["initial_confirmed_collapse_delay_from_emergence_us"] == 1250
    assert tail_phase["confirmed_collapse_delay_from_emergence_us"] == 1250
    assert tail_phase["tail_settling_candidate_delay_from_emergence_us"] == 1250
    assert tail_phase["tail_settling_trace_window_end_delay_from_emergence_us"] == 1250


def test_resolve_online_stream_tail_result_leaves_short_separated_collapse_on_existing_rule():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
            "analysis_config": {
                "tail_settling_rule_enabled": True,
                "segmented_tail_online_controlling_enabled": False,
            },
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=74.1)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=71.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=70.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=69.0)],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
    )

    tail_phase = resolved["tail_phase"]
    assert tail_phase["tail_settling_rule_applied"] is False
    assert tail_phase["tail_settling_rule_reason"] == "collapse_window_too_short"
    assert tail_phase["tail_start_selection_method"] == "latest_transition_before_confirmed_collapse"
    assert tail_phase["tail_start_delay_from_emergence_us"] == 1150
    assert tail_phase["initial_confirmed_collapse_delay_from_emergence_us"] == 1200
    assert tail_phase["confirmed_collapse_delay_from_emergence_us"] == 1200


def test_resolve_online_stream_tail_result_does_not_apply_settling_rule_to_backup_landmark():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={
            "steady_width_baseline_px": 74.0,
            "scout_anchor_delay_us": 4250,
            "backtrack_step_us": 50,
            "analysis_config": {
                "tail_settling_rule_enabled": True,
                "segmented_tail_online_controlling_enabled": False,
            },
        },
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4700, delay_from_emergence_us=1500, width_px=69.0)],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=[
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=74.1)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=71.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=70.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=70.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4500, delay_from_emergence_us=1300, phase="tail_backtrack", width_px=69.5)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4550, delay_from_emergence_us=1350, phase="tail_backtrack", width_px=69.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4600, delay_from_emergence_us=1400, phase="tail_backtrack", width_px=68.5)],
                baseline_width_px=74.0,
            ),
        ],
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4700,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "strong_width_collapse_backup",
        },
    )

    tail_phase = resolved["tail_phase"]
    assert tail_phase["tail_settling_rule_applied"] is False
    assert tail_phase["tail_settling_rule_reason"] == "selection_method_ineligible"
    assert tail_phase["landmark_reason"] == "strong_width_collapse_backup"
    assert tail_phase["tail_start_selection_method"] == "latest_transition_before_confirmed_collapse"
    assert tail_phase["confirmed_collapse_delay_from_emergence_us"] == 1250


def test_resolve_online_stream_tail_result_reports_right_extension_when_min_width_is_still_falling():
    backtrack_summaries = [
        mod.summarize_online_stream_tail_delay(
            [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=74.0)],
            baseline_width_px=74.0,
        ),
        mod.summarize_online_stream_tail_delay(
            [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=70.0)],
            baseline_width_px=74.0,
        ),
        mod.summarize_online_stream_tail_delay(
            [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=66.0)],
            baseline_width_px=74.0,
        ),
    ]
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={"steady_width_baseline_px": 74.0, "scout_anchor_delay_us": 4250, "backtrack_step_us": 50},
        scout_summaries=[
            mod.summarize_online_stream_tail_delay(
                [
                    _tail_frame_row(
                        delay_us=4750,
                        delay_from_emergence_us=1550,
                        width_px=None,
                        tail_width_usable=False,
                        separated_from_nozzle_landmark=True,
                        tail_landmark_usable=True,
                    )
                ],
                baseline_width_px=74.0,
            )
        ],
        backtrack_summaries=backtrack_summaries,
        flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
        },
    )

    tail_phase = resolved["tail_phase"]
    assert tail_phase["tail_collapse_coverage_ok"] is False
    assert tail_phase["tail_right_extension_needed"] is True
    assert tail_phase["tail_min_width_at_right_edge"] is True
    assert tail_phase["tail_width_still_falling_at_right_edge"] is True
    assert tail_phase["tail_selection_noise_floor_px"] >= 2.0

    decision = mod.decide_online_stream_tail_right_extension(
        resolve_result=resolved,
        tail_plan={"backtrack_step_us": 50},
        backtrack_summaries=backtrack_summaries,
        capture_budget={"captures_remaining_hard": 3},
        replicates_per_delay=1,
    )
    assert decision["extend"] is True
    assert decision["next_delay_us"] == 4450


def test_resolve_online_stream_tail_result_does_not_extend_after_plateau_or_unavailable_width():
    plateau_rows = [
        mod.summarize_online_stream_tail_delay(
            [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=74.0)],
            baseline_width_px=74.0,
        ),
        mod.summarize_online_stream_tail_delay(
            [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=66.0)],
            baseline_width_px=74.0,
        ),
        mod.summarize_online_stream_tail_delay(
            [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=66.5)],
            baseline_width_px=74.0,
        ),
    ]
    unavailable_rows = [
        plateau_rows[0],
        plateau_rows[1],
        mod.summarize_online_stream_tail_delay(
            [
                _tail_frame_row(
                    delay_us=4400,
                    delay_from_emergence_us=1200,
                    phase="tail_backtrack",
                    width_px=None,
                    tail_width_usable=False,
                    tail_landmark_usable=False,
                    warnings=["attached_width_unavailable"],
                    status="rejected_width_qc",
                )
            ],
            baseline_width_px=74.0,
        ),
    ]

    for rows in (plateau_rows, unavailable_rows):
        resolved = mod.resolve_online_stream_tail_result(
            flow_fit_result=_flow_fit_result(),
            tail_plan={"steady_width_baseline_px": 74.0, "scout_anchor_delay_us": 4250, "backtrack_step_us": 50},
            scout_summaries=[
                mod.summarize_online_stream_tail_delay(
                    [
                        _tail_frame_row(
                            delay_us=4750,
                            delay_from_emergence_us=1550,
                            width_px=None,
                            tail_width_usable=False,
                            separated_from_nozzle_landmark=True,
                            tail_landmark_usable=True,
                        )
                    ],
                    baseline_width_px=74.0,
                )
            ],
            backtrack_summaries=rows,
            flow_delay_summaries=[_flow_delay_summary(delay_us=4250, delay_from_emergence_us=1050)],
            trigger_bracket={
                "tail_phase_status": "",
                "termination_reason": "",
                "landmark_delay_us": 4750,
                "backtrack_left_delay_us": 4250,
                "landmark_reason": "separated_from_nozzle",
            },
        )
        assert resolved["tail_phase"]["tail_right_extension_needed"] is False


def test_build_online_stream_tail_fit_artifact_and_outputs_are_json_serializable():
    candidate = {
        "step_index": 3,
        "mode": "lower_consistent_window",
        "y0_px": 160,
        "y1_px": 200,
        "median_width_px": 72.5,
        "iqr_px": 3.25,
        "half_delta_px": 2.5,
        "valid_row_count": 39,
        "width_usable": True,
        "eligible_as_selected_window": True,
    }
    artifact = mod.build_online_stream_tail_fit_artifact(
        condition={"print_pressure_psi": 0.42},
        tail_plan={"scout_first_delay_us": 4750, "steady_width_baseline_px": 74.0},
        steady_width_baseline_px=74.0,
        scout_delay_summaries=[{"delay_us": 4750, "coarse_only_debug": "drop"}],
        backtrack_delay_summaries=[
            {
                "phase": "tail_backtrack",
                "delay_us": 4300,
                "delay_from_emergence_us": 1100,
                "attempted_replicates": 1,
                "accepted_replicates": 1,
                "median_width_px": 72.5,
                "tail_width_usable": True,
                "selected_band_step_index": 3,
                "tail_width_window_candidates": [candidate],
                "debug_blob": {"large": "drop"},
            }
        ],
        result={
            "tail_phase": {
                "status": "captured",
                "scout_delay_summaries": [{"delay_us": 4750, "debug_blob": "drop"}],
                "backtrack_delay_summaries": [{"delay_us": 4300, "debug_blob": "drop"}],
                "coarse_delay_summaries": [{"delay_us": 4750}],
                "refine_delay_summaries": [{"delay_us": 4300}],
                "segmented_tail": {
                    "status": "ok",
                    "tail_start_delay_from_emergence_us": 1125,
                    "tail_start_source": "three_two_midpoint",
                    "trace": [
                        {
                            "delay_from_emergence_us": 1100,
                            "median_width_px": 72.5,
                            "sample_count": 1,
                            "debug_blob": "drop",
                        }
                    ],
                    "fit_points": [
                        {
                            "delay_from_emergence_us": 1100,
                            "fitted_width_px": 72.4,
                            "debug_blob": "drop",
                        }
                    ],
                    "window_trace": [
                        {
                            "delay_us": 4300,
                            "delay_from_emergence_us": 1100,
                            "median_width_px": 72.5,
                            "tail_width_window_candidates": [candidate],
                            "debug_blob": "drop",
                        }
                    ],
                },
            },
            "warnings": ["tail_ok"],
        },
        warnings=["tail_ok"],
    )

    encoded = json.dumps({"artifact": artifact})

    assert isinstance(encoded, str)
    assert artifact["schema_version"] == 2
    assert artifact["search_method"] == "separation_landmark_backtrack_v1"
    assert artifact["result"]["tail_phase"]["status"] == "captured"
    assert "coarse_delay_summaries" not in artifact
    assert "refine_delay_summaries" not in artifact
    assert "scout_delay_summaries" not in artifact["result"]["tail_phase"]
    assert "backtrack_delay_summaries" not in artifact["result"]["tail_phase"]
    assert "coarse_delay_summaries" not in artifact["result"]["tail_phase"]
    assert "refine_delay_summaries" not in artifact["result"]["tail_phase"]
    compact_backtrack = artifact["backtrack_delay_summaries"][0]
    assert compact_backtrack["delay_us"] == 4300
    assert compact_backtrack["selected_band_step_index"] == 3
    assert "debug_blob" not in compact_backtrack
    compact_candidate = compact_backtrack["tail_width_window_candidates"][0]
    assert compact_candidate == {
        "step_index": 3,
        "mode": "lower_consistent_window",
        "y0_px": 160,
        "y1_px": 200,
        "median_width_px": 72.5,
        "width_usable": True,
        "eligible_as_selected_window": True,
        "valid_row_count": 39,
    }
    segmented = artifact["result"]["tail_phase"]["segmented_tail"]
    assert segmented["trace"][0]["sample_count"] == 1
    assert segmented["fit_points"][0]["fitted_width_px"] == 72.4
    assert "debug_blob" not in segmented["window_trace"][0]
    assert "iqr_px" not in segmented["window_trace"][0]["tail_width_window_candidates"][0]


def test_build_online_stream_tail_fit_artifact_accepts_legacy_summary_alias_inputs():
    artifact = mod.build_online_stream_tail_fit_artifact(
        tail_plan={"steady_width_baseline_px": 74.0},
        steady_width_baseline_px=74.0,
        coarse_delay_summaries=[{"delay_us": 4750, "delay_from_emergence_us": 1550}],
        refine_delay_summaries=[{"delay_us": 4300, "delay_from_emergence_us": 1100}],
        result={"tail_phase": {"status": "captured"}, "warnings": []},
        warnings=[],
    )

    assert artifact["schema_version"] == 2
    assert artifact["scout_delay_summaries"] == [
        {"delay_us": 4750, "delay_from_emergence_us": 1550}
    ]
    assert artifact["backtrack_delay_summaries"] == [
        {"delay_us": 4300, "delay_from_emergence_us": 1100}
    ]
    assert "coarse_delay_summaries" not in artifact
    assert "refine_delay_summaries" not in artifact
