from __future__ import annotations

import json

from tools.stream_analysis import online_calibration as online_cal_mod
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


def _tail_frame_row(
    *,
    delay_us: int,
    delay_from_emergence_us: int,
    status: str,
    width_px=None,
    warnings=None,
    **extra,
):
    row = {
        "phase": "tail_coarse",
        "status": status,
        "delay_us": int(delay_us),
        "delay_from_emergence_us": int(delay_from_emergence_us),
        "replicate_index": 1,
        "qc": {"tail_qc_pass": status == "accepted"},
        "image_ref": {"capture_id": f"cap_{delay_us}"},
        "warnings": list(warnings or []),
        "attached_width_px": width_px,
    }
    row.update(dict(extra or {}))
    return row


def test_plan_online_stream_tail_phase_uses_exact_prior_start_minus_lead():
    plan = mod.plan_online_stream_tail_phase(
        flow_fit_result=_flow_fit_result(),
        priors={
            "condition_match": "exact",
            "tail_start_offset_us": 4200,
            "tail_coarse_step_us": 125,
        },
        emergence_time_us=1000,
        capture_budget={"captures_remaining_hard": 12},
    )

    assert plan["run_tail"] is True
    assert plan["coarse_start_delay_us"] == 4900
    assert plan["coarse_step_us"] == 125
    assert plan["plan_source"] == "exact_prior_minus_lead"


def test_plan_online_stream_tail_phase_falls_back_to_emergence_plus_3800():
    plan = mod.plan_online_stream_tail_phase(
        flow_fit_result=_flow_fit_result(),
        priors={"condition_match": "none"},
        emergence_time_us=1000,
        capture_budget={"captures_remaining_hard": 12},
    )

    assert plan["coarse_start_delay_us"] == 4800
    assert plan["coarse_step_us"] == 100
    assert plan["refine_step_us"] == 50
    assert plan["plan_source"] == "fallback_default"


def test_plan_online_stream_tail_phase_skips_when_flow_fit_is_unresolved():
    plan = mod.plan_online_stream_tail_phase(
        flow_fit_result=_flow_fit_result(fit_status="unresolved_insufficient_delays"),
        priors=None,
        emergence_time_us=1000,
        capture_budget={"captures_remaining_hard": 12},
    )

    assert plan["run_tail"] is False
    assert plan["skip_reason"] == "missing_flow_baseline"


def test_plan_online_stream_tail_phase_allows_warning_quality_flow_fit():
    plan = mod.plan_online_stream_tail_phase(
        flow_fit_result=_flow_fit_result(fit_status="warning_quality_thresholds"),
        priors=None,
        emergence_time_us=1000,
        capture_budget={"captures_remaining_hard": 12},
    )

    assert plan["run_tail"] is True
    assert plan["planned_coarse_delay_count"] == 3


def test_plan_online_stream_tail_phase_reserves_full_refine_bracket_budget():
    capture_budget = online_cal_mod.consume_online_stream_budget(
        online_cal_mod.new_online_stream_budget(),
        phase="flow_phase",
        count=15,
    )

    plan = mod.plan_online_stream_tail_phase(
        flow_fit_result=_flow_fit_result(),
        priors=None,
        emergence_time_us=1000,
        capture_budget=capture_budget,
    )

    assert plan["reserved_refine_delay_count"] == 3
    assert plan["reserved_refine_capture_count"] == 6
    assert plan["planned_coarse_delay_count"] == 7
    assert (
        int(plan["planned_coarse_delay_count"]) * int(plan["coarse_replicates"])
        + int(plan["reserved_refine_capture_count"])
    ) <= int(capture_budget["captures_remaining_hard"])


def test_summarize_online_stream_tail_delay_marks_coarse_and_refine_triggers():
    summary = mod.summarize_online_stream_tail_delay(
        [
            _tail_frame_row(
                delay_us=7000,
                delay_from_emergence_us=3800,
                status="accepted",
                width_px=66.0,
            ),
            _tail_frame_row(
                delay_us=7000,
                delay_from_emergence_us=3800,
                status="accepted",
                width_px=68.0,
            ),
        ],
        baseline_width_px=74.0,
    )

    assert summary["delay_accepted"] is True
    assert summary["median_width_px"] == 67.0
    assert summary["width_ratio_to_baseline"] <= 0.95
    assert summary["triggered_refine"] is True


def test_summarize_online_stream_tail_delay_triggers_on_morphology_without_width_collapse():
    summary = mod.summarize_online_stream_tail_delay(
        [
            _tail_frame_row(
                delay_us=7200,
                delay_from_emergence_us=4000,
                status="accepted",
                width_px=73.0,
                warnings=["detached_near_bottom_warning"],
                detached_near_bottom_warning=True,
            ),
            _tail_frame_row(
                delay_us=7200,
                delay_from_emergence_us=4000,
                status="accepted",
                width_px=72.0,
                warnings=["detached_near_bottom_warning"],
                detached_near_bottom_warning=True,
            ),
        ],
        baseline_width_px=74.0,
    )

    assert summary["width_ratio_to_baseline"] > 0.95
    assert summary["morphology_triggered_coarse"] is True
    assert summary["morphology_triggered_refine"] is True
    assert summary["triggered_coarse"] is True
    assert summary["triggered_refine"] is True
    assert summary["trigger_reason"] == "coarse_morphology_trigger"


def test_build_online_stream_tail_refine_plan_excludes_coarse_endpoints():
    plan = mod.build_online_stream_tail_refine_plan(
        last_coarse_nontrigger_delay_us=7000,
        first_coarse_trigger_delay_us=7200,
        refine_step_us=50,
    )

    assert plan == [7050, 7100, 7150]


def test_decide_online_stream_tail_next_action_switches_to_refine_on_coarse_trigger():
    decision = mod.decide_online_stream_tail_next_action(
        mode="coarse",
        delay_summary={"delay_accepted": True, "triggered_coarse": True},
        capture_budget={"exhausted": False},
        consecutive_failed_delays=0,
        attempted_delay_count=2,
        planned_delay_count=5,
        has_last_nontrigger=True,
    )

    assert decision["action"] == "switch_to_refine"
    assert decision["trigger_reason"] == "coarse_width_frac_le_0.90"


def test_decide_online_stream_tail_next_action_uses_synthetic_left_bracket_when_needed():
    decision = mod.decide_online_stream_tail_next_action(
        mode="coarse",
        delay_summary={
            "delay_us": 7200,
            "delay_accepted": True,
            "triggered_coarse": True,
            "width_ratio_to_baseline": 0.89,
            "morphology_triggered_coarse": False,
        },
        capture_budget={"exhausted": False},
        consecutive_failed_delays=0,
        attempted_delay_count=3,
        planned_delay_count=5,
        has_last_nontrigger=False,
        current_delay_us=7200,
        coarse_step_us=100,
        coarse_start_delay_us=7000,
    )

    assert decision["action"] == "switch_to_refine"
    assert decision["synthetic_left_bracket_used"] is True
    assert decision["synthetic_last_nontrigger_delay_us"] == 7100
    assert decision["trigger_reason"] == "coarse_width_frac_le_0.90"
    assert mod.build_online_stream_tail_refine_plan(
        last_coarse_nontrigger_delay_us=decision["synthetic_last_nontrigger_delay_us"],
        first_coarse_trigger_delay_us=7200,
        refine_step_us=50,
    ) == [7150]


def test_resolve_online_stream_tail_result_prefers_earliest_refine_qualifying_delay():
    tail_plan = {
        "steady_width_baseline_px": 74.0,
        "coarse_start_delay_us": 7000,
    }
    coarse_summaries = [
        {
            "delay_us": 7000,
            "delay_from_emergence_us": 3800,
            "attempted_replicates": 2,
            "accepted_replicates": 2,
            "rejected_replicates": 0,
            "median_width_px": 71.0,
            "width_ratio_to_baseline": 71.0 / 74.0,
            "triggered_coarse": False,
            "triggered_refine": True,
            "warnings": [],
            "delay_accepted": True,
        },
        {
            "delay_us": 7200,
            "delay_from_emergence_us": 4000,
            "attempted_replicates": 2,
            "accepted_replicates": 2,
            "rejected_replicates": 0,
            "median_width_px": 66.0,
            "width_ratio_to_baseline": 66.0 / 74.0,
            "triggered_coarse": True,
            "triggered_refine": True,
            "warnings": [],
            "delay_accepted": True,
        },
    ]
    refine_summaries = [
        {
            "delay_us": 7050,
            "delay_from_emergence_us": 3850,
            "attempted_replicates": 2,
            "accepted_replicates": 2,
            "rejected_replicates": 0,
            "median_width_px": 70.0,
            "width_ratio_to_baseline": 70.0 / 74.0,
            "triggered_coarse": False,
            "triggered_refine": True,
            "warnings": [],
            "delay_accepted": True,
        }
    ]

    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan=tail_plan,
        coarse_summaries=coarse_summaries,
        refine_summaries=refine_summaries,
        trigger_bracket={
            "tail_phase_status": "captured",
            "termination_reason": "refine_trigger",
            "trigger_delay_us": 7200,
            "last_nontrigger_delay_us": 7000,
            "trigger_reason": "refine_width_frac_le_0.95",
        },
    )

    assert resolved["tail_phase"]["status"] == "captured"
    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] == 3800
    assert resolved["predicted_stream_duration_us"] == 3800
    assert resolved["predicted_volume_nl"] is not None


def test_resolve_online_stream_tail_result_falls_back_to_coarse_trigger_when_no_refine_point_qualifies():
    resolved = mod.resolve_online_stream_tail_result(
        flow_fit_result=_flow_fit_result(),
        tail_plan={"steady_width_baseline_px": 74.0},
        coarse_summaries=[
            {
                "delay_us": 7200,
                "delay_from_emergence_us": 4000,
                "attempted_replicates": 2,
                "accepted_replicates": 2,
                "rejected_replicates": 0,
                "median_width_px": 66.0,
                "width_ratio_to_baseline": 66.0 / 74.0,
                "triggered_coarse": True,
                "triggered_refine": True,
                "warnings": [],
                "delay_accepted": True,
            }
        ],
        refine_summaries=[
            {
                "delay_us": 7150,
                "delay_from_emergence_us": 3950,
                "attempted_replicates": 2,
                "accepted_replicates": 0,
                "rejected_replicates": 2,
                "median_width_px": None,
                "width_ratio_to_baseline": None,
                "triggered_coarse": False,
                "triggered_refine": False,
                "warnings": ["width_missing"],
                "delay_accepted": False,
            }
        ],
        trigger_bracket={
            "tail_phase_status": "captured",
            "termination_reason": "coarse_trigger_fallback",
            "trigger_delay_us": 7200,
            "last_nontrigger_delay_us": None,
            "trigger_reason": "coarse_width_frac_le_0.90",
        },
    )

    assert resolved["tail_phase"]["tail_start_delay_from_emergence_us"] == 4000


def test_build_online_stream_tail_fit_artifact_and_outputs_are_json_serializable():
    artifact = mod.build_online_stream_tail_fit_artifact(
        condition={"print_pressure_psi": 0.42},
        tail_plan={"coarse_start_delay_us": 7000, "steady_width_baseline_px": 74.0},
        steady_width_baseline_px=74.0,
        coarse_delay_summaries=[{"delay_us": 7000}],
        refine_delay_summaries=[{"delay_us": 7050}],
        result={"tail_phase": {"status": "captured"}, "warnings": ["tail_ok"]},
        warnings=["tail_ok"],
    )

    encoded = json.dumps(
        {
            "plan": mod.plan_online_stream_tail_phase(
                flow_fit_result=_flow_fit_result(),
                priors=None,
                emergence_time_us=1000,
                capture_budget={"captures_remaining_hard": 12},
            ),
            "artifact": artifact,
        }
    )

    assert isinstance(encoded, str)
    assert artifact["result"]["tail_phase"]["status"] == "captured"
