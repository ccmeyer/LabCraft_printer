from __future__ import annotations

import math

from tools.stream_analysis import online_calibration as online_cal_mod


DEFAULT_ONLINE_TAIL_POLICY = {
    "coarse_trigger_width_frac": 0.90,
    "refine_trigger_width_frac": 0.95,
    "consecutive_failed_tail_delays_stop": 2,
    "exact_prior_start_lead_us": 300,
    "fallback_start_offset_us": 3800,
    "coarse_step_us": 100,
    "coarse_replicates": 2,
    "refine_step_us": 50,
    "refine_replicates": 2,
}


def _to_int(value, default: int | None = None):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        return default


def _to_float_or_none(value):
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
        if not math.isfinite(parsed):
            return None
        return parsed
    except Exception:
        return None


def _copy_warnings(value) -> list[str]:
    warnings = []
    for item in list(value or []):
        label = str(item or "").strip()
        if label:
            warnings.append(label)
    return warnings


def _copy_jsonish(value):
    if isinstance(value, dict):
        return {str(key): _copy_jsonish(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_jsonish(item) for item in value]
    return value


def _unique_strings(values) -> list[str]:
    output = []
    seen = set()
    for value in list(values or []):
        label = str(value or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        output.append(label)
    return output


def _median_or_none(values):
    clean = []
    for value in list(values or []):
        parsed = _to_float_or_none(value)
        if parsed is not None:
            clean.append(float(parsed))
    if not clean:
        return None
    clean.sort()
    middle = len(clean) // 2
    if len(clean) % 2 == 1:
        return float(clean[middle])
    return float((clean[middle - 1] + clean[middle]) / 2.0)


def _resolved_policy(policy: dict | None = None) -> dict:
    merged = dict(DEFAULT_ONLINE_TAIL_POLICY)
    for key, default_value in DEFAULT_ONLINE_TAIL_POLICY.items():
        if not isinstance(policy, dict) or key not in policy:
            continue
        if isinstance(default_value, int):
            merged[key] = max(0, _to_int(policy.get(key), default_value))
        else:
            merged[key] = float(policy.get(key))
    return merged


def _remaining_hard_budget(capture_budget: dict | None) -> int:
    budget = dict(capture_budget or {})
    remaining_hard = _to_int(budget.get("captures_remaining_hard"))
    if remaining_hard is not None:
        return max(0, int(remaining_hard))
    hard_limit = _to_int(budget.get("hard_limit"), 0)
    captures_used = _to_int(budget.get("captures_used"), 0)
    return max(0, int(hard_limit - captures_used))


def _find_delay_summary(summaries: list[dict], delay_us: int | None) -> dict | None:
    if delay_us is None:
        return None
    for row in list(summaries or []):
        summary = dict(row or {})
        if _to_int(summary.get("delay_us")) == int(delay_us):
            return summary
    return None


def _summary_delay_from_emergence(summary: dict | None, delay_us: int | None) -> int | None:
    if summary:
        return _to_int(summary.get("delay_from_emergence_us"))
    return None


def plan_online_stream_tail_phase(
    *,
    flow_fit_result: dict | None,
    priors: dict | None,
    emergence_time_us: int,
    capture_budget: dict | None,
    policy: dict | None = None,
) -> dict:
    fit = dict(flow_fit_result or {})
    normalized_priors = online_cal_mod.normalize_online_stream_prior(priors)
    resolved_policy = _resolved_policy(policy)
    fit_status = str(fit.get("fit_status") or "")
    steady_width_baseline_px = _to_float_or_none(fit.get("steady_width_baseline_px"))
    if steady_width_baseline_px is None or fit_status.startswith("unresolved"):
        return {
            "run_tail": False,
            "skip_reason": "missing_flow_baseline",
            "steady_width_baseline_px": steady_width_baseline_px,
            "coarse_start_delay_us": None,
            "coarse_step_us": int(resolved_policy["coarse_step_us"]),
            "coarse_replicates": int(resolved_policy["coarse_replicates"]),
            "refine_step_us": int(resolved_policy["refine_step_us"]),
            "refine_replicates": int(resolved_policy["refine_replicates"]),
            "planned_coarse_delay_count": 0,
            "reserved_refine_capture_count": int(resolved_policy["refine_replicates"]),
            "plan_source": "skipped_missing_flow_baseline",
        }

    remaining_hard = _remaining_hard_budget(capture_budget)
    reserved_refine_capture_count = int(resolved_policy["refine_replicates"])
    coarse_replicates = int(resolved_policy["coarse_replicates"])
    planned_coarse_delay_count = max(
        0,
        int((max(0, remaining_hard - reserved_refine_capture_count)) // max(1, coarse_replicates)),
    )

    plan_source = "fallback_default"
    coarse_start_delay_us = int(emergence_time_us) + int(resolved_policy["fallback_start_offset_us"])
    if str(normalized_priors.get("condition_match") or "") == "exact":
        prior_offset_us = _to_int(
            normalized_priors.get("tail_start_offset_us"),
            resolved_policy["fallback_start_offset_us"],
        )
        coarse_start_delay_us = int(
            int(emergence_time_us)
            + int(prior_offset_us)
            - int(resolved_policy["exact_prior_start_lead_us"])
        )
        plan_source = "exact_prior_minus_lead"

    coarse_step_us = _to_int(
        normalized_priors.get("tail_coarse_step_us"),
        resolved_policy["coarse_step_us"],
    )

    return {
        "run_tail": True,
        "skip_reason": None,
        "steady_width_baseline_px": float(steady_width_baseline_px),
        "coarse_start_delay_us": int(coarse_start_delay_us),
        "coarse_step_us": int(coarse_step_us),
        "coarse_replicates": int(coarse_replicates),
        "refine_step_us": int(resolved_policy["refine_step_us"]),
        "refine_replicates": int(resolved_policy["refine_replicates"]),
        "planned_coarse_delay_count": int(planned_coarse_delay_count),
        "reserved_refine_capture_count": int(reserved_refine_capture_count),
        "plan_source": str(plan_source),
    }


def summarize_online_stream_tail_delay(
    frame_rows: list[dict],
    baseline_width_px: float | int | None,
    *,
    policy: dict | None = None,
) -> dict:
    rows = [dict(row or {}) for row in list(frame_rows or [])]
    accepted_rows = [row for row in rows if str(row.get("status") or "") == "accepted"]
    attempted_replicates = int(len(rows))
    accepted_replicates = int(len(accepted_rows))
    rejected_replicates = int(max(0, attempted_replicates - accepted_replicates))
    median_width_px = _median_or_none(row.get("attached_width_px") for row in accepted_rows)
    baseline = _to_float_or_none(baseline_width_px)
    width_ratio_to_baseline = None
    if baseline not in (None, 0.0) and median_width_px is not None:
        width_ratio_to_baseline = float(float(median_width_px) / float(baseline))
    resolved_policy = _resolved_policy(policy)
    warnings = _unique_strings(
        warning
        for row in rows
        for warning in list(row.get("warnings") or [])
    )
    delay_us = None
    delay_from_emergence_us = None
    if rows:
        delay_us = _to_int(rows[0].get("delay_us"))
        delay_from_emergence_us = _to_int(rows[0].get("delay_from_emergence_us"))

    return {
        "delay_us": delay_us,
        "delay_from_emergence_us": delay_from_emergence_us,
        "attempted_replicates": int(attempted_replicates),
        "accepted_replicates": int(accepted_replicates),
        "rejected_replicates": int(rejected_replicates),
        "median_width_px": median_width_px,
        "width_ratio_to_baseline": width_ratio_to_baseline,
        "triggered_coarse": bool(
            accepted_replicates > 0
            and width_ratio_to_baseline is not None
            and float(width_ratio_to_baseline) <= float(resolved_policy["coarse_trigger_width_frac"])
        ),
        "triggered_refine": bool(
            accepted_replicates > 0
            and width_ratio_to_baseline is not None
            and float(width_ratio_to_baseline) <= float(resolved_policy["refine_trigger_width_frac"])
        ),
        "warnings": warnings,
        "delay_accepted": bool(accepted_replicates > 0),
    }


def build_online_stream_tail_refine_plan(
    *,
    last_coarse_nontrigger_delay_us: int | None,
    first_coarse_trigger_delay_us: int | None,
    refine_step_us: int,
) -> list[int]:
    left_delay_us = _to_int(last_coarse_nontrigger_delay_us)
    right_delay_us = _to_int(first_coarse_trigger_delay_us)
    step_us = max(1, _to_int(refine_step_us, DEFAULT_ONLINE_TAIL_POLICY["refine_step_us"]))
    if left_delay_us is None or right_delay_us is None or int(left_delay_us) >= int(right_delay_us):
        return []
    return [
        int(delay_us)
        for delay_us in range(int(left_delay_us) + int(step_us), int(right_delay_us), int(step_us))
    ]


def decide_online_stream_tail_next_action(
    *,
    mode: str,
    delay_summary: dict | None,
    capture_budget: dict | None,
    consecutive_failed_delays: int = 0,
    attempted_delay_count: int = 0,
    planned_delay_count: int = 0,
    has_last_nontrigger: bool = False,
    policy: dict | None = None,
) -> dict:
    summary = dict(delay_summary or {})
    budget = dict(capture_budget or {})
    resolved_policy = _resolved_policy(policy)

    mode_label = str(mode or "coarse")
    if mode_label == "coarse":
        if bool(summary.get("delay_accepted")) and bool(summary.get("triggered_coarse")):
            if bool(has_last_nontrigger):
                return {
                    "action": "switch_to_refine",
                    "tail_phase_status": None,
                    "termination_reason": None,
                    "trigger_reason": "coarse_width_frac_le_0.90",
                }
            return {
                "action": "finish_captured_immediate",
                "tail_phase_status": "captured",
                    "termination_reason": "coarse_trigger_immediate",
                    "trigger_reason": "coarse_width_frac_le_0.90",
                }
        if int(consecutive_failed_delays) >= int(resolved_policy["consecutive_failed_tail_delays_stop"]):
            return {
                "action": "stop",
                "tail_phase_status": "unresolved_qc_failure",
                "termination_reason": "repeated_tail_qc_failure",
                "trigger_reason": None,
            }
        if int(attempted_delay_count) >= int(max(0, planned_delay_count)):
            return {
                "action": "stop",
                "tail_phase_status": "unresolved_no_trigger",
                "termination_reason": "no_coarse_trigger",
                "trigger_reason": None,
            }
        if bool(budget.get("exhausted")):
            return {
                "action": "stop",
                "tail_phase_status": "unresolved_budget_exhausted",
                "termination_reason": "capture_budget_exhausted",
                "trigger_reason": None,
            }
        return {
            "action": "continue",
            "tail_phase_status": None,
            "termination_reason": None,
            "trigger_reason": None,
        }

    if bool(summary.get("delay_accepted")) and bool(summary.get("triggered_refine")):
        return {
            "action": "finish_captured",
            "tail_phase_status": "captured",
            "termination_reason": "refine_trigger",
            "trigger_reason": "refine_width_frac_le_0.95",
        }
    if int(attempted_delay_count) >= int(max(0, planned_delay_count)):
        return {
            "action": "finish_using_coarse_trigger",
            "tail_phase_status": "captured",
            "termination_reason": "coarse_trigger_fallback",
            "trigger_reason": "coarse_width_frac_le_0.90",
        }
    if bool(budget.get("exhausted")):
        return {
            "action": "stop",
            "tail_phase_status": "unresolved_budget_exhausted",
            "termination_reason": "capture_budget_exhausted",
            "trigger_reason": None,
        }
    return {
        "action": "continue",
        "tail_phase_status": None,
        "termination_reason": None,
        "trigger_reason": None,
    }


def resolve_online_stream_tail_result(
    *,
    flow_fit_result: dict | None,
    tail_plan: dict | None,
    coarse_summaries: list[dict] | None,
    refine_summaries: list[dict] | None,
    trigger_bracket: dict | None,
    phase: str = "online_stream_calibration",
) -> dict:
    fit = dict(flow_fit_result or {})
    plan = dict(tail_plan or {})
    coarse_rows = [dict(row or {}) for row in list(coarse_summaries or [])]
    refine_rows = [dict(row or {}) for row in list(refine_summaries or [])]
    bracket = dict(trigger_bracket or {})
    tail_phase_status = str(bracket.get("tail_phase_status") or bracket.get("status") or "unresolved_no_trigger")
    termination_reason = str(bracket.get("termination_reason") or "")
    trigger_reason = str(bracket.get("trigger_reason") or "")

    trigger_delay_us = _to_int(bracket.get("trigger_delay_us"))
    last_nontrigger_delay_us = _to_int(bracket.get("last_nontrigger_delay_us"))
    trigger_summary = _find_delay_summary(coarse_rows, trigger_delay_us)
    last_nontrigger_summary = _find_delay_summary(coarse_rows, last_nontrigger_delay_us)
    trigger_delay_from_emergence_us = _summary_delay_from_emergence(trigger_summary, trigger_delay_us)
    last_nontrigger_delay_from_emergence_us = _summary_delay_from_emergence(
        last_nontrigger_summary,
        last_nontrigger_delay_us,
    )

    warnings = _unique_strings(
        list(plan.get("warnings") or [])
        + list(bracket.get("warnings") or [])
        + [warning for row in coarse_rows for warning in list(row.get("warnings") or [])]
        + [warning for row in refine_rows for warning in list(row.get("warnings") or [])]
    )

    final_tail_start_delay_us = None
    final_tail_start_delay_from_emergence_us = None
    if tail_phase_status == "captured":
        eligible_candidates = []
        if (
            last_nontrigger_summary
            and bool(last_nontrigger_summary.get("delay_accepted"))
            and bool(last_nontrigger_summary.get("triggered_refine"))
        ):
            eligible_candidates.append(dict(last_nontrigger_summary))
        for row in refine_rows:
            if bool(row.get("delay_accepted")) and bool(row.get("triggered_refine")):
                eligible_candidates.append(dict(row))
        if trigger_summary and bool(trigger_summary.get("delay_accepted")):
            eligible_candidates.append(dict(trigger_summary))
        eligible_candidates.sort(
            key=lambda row: (
                _to_int(row.get("delay_from_emergence_us"), 10**9),
                _to_int(row.get("delay_us"), 10**9),
            )
        )
        if eligible_candidates:
            final_row = dict(eligible_candidates[0])
            final_tail_start_delay_us = _to_int(final_row.get("delay_us"))
            final_tail_start_delay_from_emergence_us = _to_int(
                final_row.get("delay_from_emergence_us")
            )
        elif trigger_summary:
            final_tail_start_delay_us = _to_int(trigger_summary.get("delay_us"))
            final_tail_start_delay_from_emergence_us = _to_int(
                trigger_summary.get("delay_from_emergence_us")
            )
        else:
            tail_phase_status = "unresolved_no_trigger"
            if "tail_resolution_failed" not in warnings:
                warnings.append("tail_resolution_failed")

    predicted_stream_duration_us = None
    predicted_volume_nl = None
    flow_rate = _to_float_or_none(fit.get("flow_rate_nl_per_us"))
    flow_intercept = _to_float_or_none(fit.get("flow_intercept_nl"))
    if (
        tail_phase_status == "captured"
        and final_tail_start_delay_from_emergence_us is not None
        and flow_rate is not None
        and flow_intercept is not None
    ):
        predicted_stream_duration_us = int(final_tail_start_delay_from_emergence_us)
        predicted_volume_nl = float(
            float(flow_intercept) + (float(flow_rate) * float(predicted_stream_duration_us))
        )

    all_summaries = list(coarse_rows) + list(refine_rows)
    tail_phase = {
        "status": str(tail_phase_status),
        "plan": _copy_jsonish(plan),
        "attempted_delay_count": int(len(all_summaries)),
        "attempted_capture_count": int(
            sum(max(0, _to_int(row.get("attempted_replicates"), 0)) for row in all_summaries)
        ),
        "accepted_delay_count": int(sum(1 for row in all_summaries if bool(row.get("delay_accepted")))),
        "accepted_measurement_count": int(
            sum(max(0, _to_int(row.get("accepted_replicates"), 0)) for row in all_summaries)
        ),
        "termination_reason": str(termination_reason),
        "coarse_delay_summaries": _copy_jsonish(coarse_rows),
        "refine_delay_summaries": _copy_jsonish(refine_rows),
        "trigger_delay_from_emergence_us": trigger_delay_from_emergence_us,
        "trigger_reason": str(trigger_reason),
        "last_nontrigger_delay_from_emergence_us": last_nontrigger_delay_from_emergence_us,
        "tail_start_delay_from_emergence_us": (
            None
            if final_tail_start_delay_from_emergence_us is None
            else int(final_tail_start_delay_from_emergence_us)
        ),
        "warnings": _copy_warnings(warnings),
    }
    return {
        "phase": str(phase),
        "tail_phase": tail_phase,
        "predicted_stream_duration_us": (
            None if predicted_stream_duration_us is None else int(predicted_stream_duration_us)
        ),
        "predicted_volume_nl": None if predicted_volume_nl is None else float(predicted_volume_nl),
        "warnings": _copy_warnings(warnings),
    }


def build_online_stream_tail_fit_artifact(
    *,
    condition: dict | None = None,
    tail_plan: dict | None = None,
    steady_width_baseline_px: float | int | None = None,
    coarse_delay_summaries: list[dict] | None = None,
    refine_delay_summaries: list[dict] | None = None,
    result: dict | None = None,
    warnings: list[str] | None = None,
    schema_version: int = 1,
    phase: str = "online_stream_calibration",
) -> dict:
    result_obj = dict(result or {})
    return {
        "schema_version": int(schema_version),
        "phase": str(phase),
        "condition": _copy_jsonish(condition or {}),
        "tail_plan": _copy_jsonish(tail_plan or {}),
        "steady_width_baseline_px": _to_float_or_none(
            steady_width_baseline_px
            if steady_width_baseline_px is not None
            else (tail_plan or {}).get("steady_width_baseline_px")
        ),
        "coarse_delay_summaries": _copy_jsonish(coarse_delay_summaries or []),
        "refine_delay_summaries": _copy_jsonish(refine_delay_summaries or []),
        "result": _copy_jsonish(result_obj),
        "warnings": _copy_warnings(
            warnings if warnings is not None else result_obj.get("warnings")
        ),
    }
