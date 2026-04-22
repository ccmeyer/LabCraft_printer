from __future__ import annotations

import json

from tools.stream_analysis import online_tail as mod


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


def test_summarize_online_stream_tail_delay_uses_width_collapse_backup_landmark():
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
    assert summary["backup_width_collapse_landmark"] is True
    assert summary["landmark_detected"] is True
    assert summary["landmark_reason"] == "strong_width_collapse_backup"


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
        [_tail_frame_row(delay_us=4750, delay_from_emergence_us=1550, width_px=73.5)],
        baseline_width_px=74.0,
    )
    transition = mod.summarize_online_stream_tail_delay(
        [_tail_frame_row(delay_us=4800, delay_from_emergence_us=1600, width_px=73.0)],
        baseline_width_px=74.0,
    )
    collapse = mod.summarize_online_stream_tail_delay(
        [_tail_frame_row(delay_us=4850, delay_from_emergence_us=1650, width_px=72.0)],
        baseline_width_px=74.0,
    )

    assert shoulder["width_drop_from_baseline_px"] == 0.5
    assert shoulder["resolver_plateau_candidate"] is True
    assert shoulder["resolver_transition_candidate"] is False
    assert shoulder["resolver_collapse_candidate"] is False
    assert transition["width_drop_from_baseline_px"] == 1.0
    assert transition["resolver_transition_candidate"] is True
    assert transition["resolver_collapse_candidate"] is False
    assert collapse["width_drop_from_baseline_px"] == 2.0
    assert collapse["resolver_collapse_candidate"] is True


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
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=73.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=72.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=71.5)],
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
    assert resolved["tail_phase"]["tail_start_selection_method"] == "earliest_transition_before_confirmed_collapse"
    assert resolved["predicted_stream_duration_us"] == 1150
    assert resolved["predicted_volume_nl"] is not None


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
                [_tail_frame_row(delay_us=4750, delay_from_emergence_us=1550, phase="tail_backtrack", width_px=73.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4800, delay_from_emergence_us=1600, phase="tail_backtrack", width_px=72.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4850, delay_from_emergence_us=1650, phase="tail_backtrack", width_px=71.5)],
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
    assert resolved["tail_phase"]["tail_start_selection_method"] == "earliest_transition_before_confirmed_collapse"


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
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=72.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=74.2)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=73.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4500, delay_from_emergence_us=1300, phase="tail_backtrack", width_px=72.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4550, delay_from_emergence_us=1350, phase="tail_backtrack", width_px=71.5)],
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
    assert resolved["tail_phase"]["tail_start_selection_method"] == "earliest_transition_before_confirmed_collapse"

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
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=71.5)],
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
    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] == 1175
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
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=72.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=71.5)],
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
                [_tail_frame_row(delay_us=4300, delay_from_emergence_us=1100, phase="tail_backtrack", width_px=72.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=71.5)],
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
            "analysis_config": {"tail_settling_rule_enabled": True},
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
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=73.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=72.8)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=72.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4500, delay_from_emergence_us=1300, phase="tail_backtrack", width_px=71.8)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4550, delay_from_emergence_us=1350, phase="tail_backtrack", width_px=71.7)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4600, delay_from_emergence_us=1400, phase="tail_backtrack", width_px=71.0)],
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
            "analysis_config": {"tail_settling_rule_enabled": True},
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
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=73.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=72.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=71.5)],
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
    assert tail_phase["tail_start_selection_method"] == "earliest_transition_before_confirmed_collapse"
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
            "analysis_config": {"tail_settling_rule_enabled": True},
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
                [_tail_frame_row(delay_us=4350, delay_from_emergence_us=1150, phase="tail_backtrack", width_px=73.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4400, delay_from_emergence_us=1200, phase="tail_backtrack", width_px=72.8)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4450, delay_from_emergence_us=1250, phase="tail_backtrack", width_px=72.0)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4500, delay_from_emergence_us=1300, phase="tail_backtrack", width_px=71.8)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4550, delay_from_emergence_us=1350, phase="tail_backtrack", width_px=71.7)],
                baseline_width_px=74.0,
            ),
            mod.summarize_online_stream_tail_delay(
                [_tail_frame_row(delay_us=4600, delay_from_emergence_us=1400, phase="tail_backtrack", width_px=71.0)],
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
    assert tail_phase["tail_start_selection_method"] == "earliest_transition_before_confirmed_collapse"
    assert tail_phase["confirmed_collapse_delay_from_emergence_us"] == 1250


def test_build_online_stream_tail_fit_artifact_and_outputs_are_json_serializable():
    artifact = mod.build_online_stream_tail_fit_artifact(
        condition={"print_pressure_psi": 0.42},
        tail_plan={"scout_first_delay_us": 4750, "steady_width_baseline_px": 74.0},
        steady_width_baseline_px=74.0,
        scout_delay_summaries=[{"delay_us": 4750}],
        backtrack_delay_summaries=[{"delay_us": 4300}],
        result={"tail_phase": {"status": "captured"}, "warnings": ["tail_ok"]},
        warnings=["tail_ok"],
    )

    encoded = json.dumps({"artifact": artifact})

    assert isinstance(encoded, str)
    assert artifact["search_method"] == "separation_landmark_backtrack_v1"
    assert artifact["result"]["tail_phase"]["status"] == "captured"
