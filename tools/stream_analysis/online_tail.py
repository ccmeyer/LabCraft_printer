from __future__ import annotations

import math

from tools.stream_analysis import online_calibration as online_cal_mod


SEARCH_METHOD = "separation_landmark_backtrack_v1"

DEFAULT_ONLINE_TAIL_POLICY = {
    "scout_landmark_width_frac": 0.95,
    "plateau_width_frac": 0.995,
    "departure_width_frac": 0.99,
    "consecutive_failed_tail_delays_stop": 2,
    "scout_step_us": 500,
    "scout_replicates": 1,
    "max_scout_delay_count": 10,
    "backtrack_step_us": 50,
    "backtrack_replicates": 1,
    "fine_prepad_us": 100,
    "fine_postpad_us": 100,
    "reserved_backtrack_capture_count": 15,
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
    alias_map = {
        "coarse_trigger_width_frac": "scout_landmark_width_frac",
        "coarse_step_us": "scout_step_us",
        "coarse_replicates": "scout_replicates",
        "refine_step_us": "backtrack_step_us",
        "refine_replicates": "backtrack_replicates",
        "reserved_refine_capture_count": "reserved_backtrack_capture_count",
    }
    provided = dict(policy or {})
    for old_key, new_key in alias_map.items():
        if old_key in provided and new_key not in provided:
            provided[new_key] = provided.get(old_key)
    for key, default_value in DEFAULT_ONLINE_TAIL_POLICY.items():
        if key not in provided:
            continue
        if isinstance(default_value, int):
            merged[key] = max(0, _to_int(provided.get(key), default_value))
        else:
            merged[key] = float(provided.get(key))
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


def _delay_from_emergence_from_plan(plan: dict | None, delay_us: int | None) -> int | None:
    resolved_plan = dict(plan or {})
    delay_value = _to_int(delay_us)
    scout_anchor_delay_us = _to_int(resolved_plan.get("scout_anchor_delay_us"))
    scout_anchor_delay_from_emergence_us = _to_int(
        resolved_plan.get("scout_anchor_delay_from_emergence_us")
    )
    if (
        delay_value is None
        or scout_anchor_delay_us is None
        or scout_anchor_delay_from_emergence_us is None
    ):
        return None
    return int(
        int(scout_anchor_delay_from_emergence_us)
        + int(delay_value)
        - int(scout_anchor_delay_us)
    )


def _legacy_tail_width_usable(row: dict) -> bool:
    qc = dict(row.get("qc") or {})
    if "tail_width_usable" in row:
        return bool(row.get("tail_width_usable"))
    if "tail_qc_pass" in row:
        return bool(row.get("tail_qc_pass"))
    if "tail_qc_pass" in qc:
        return bool(qc.get("tail_qc_pass"))
    return bool(str(row.get("status") or "") == "accepted" and row.get("attached_width_px") is not None)


def _legacy_tail_landmark_usable(row: dict) -> bool:
    if _attached_width_unavailable_landmark_row(row):
        return True
    if "tail_landmark_usable" in row:
        return bool(row.get("tail_landmark_usable"))
    return bool(row.get("separated_from_nozzle_landmark"))


def _attached_width_unavailable_landmark_row(row: dict) -> bool:
    summary = dict(row or {})
    if "attached_width_unavailable_landmark" in summary:
        return bool(summary.get("attached_width_unavailable_landmark"))
    qc = dict(summary.get("qc") or {})
    if bool(summary.get("tail_width_usable")) or bool(qc.get("tail_width_usable")):
        return False
    if summary.get("attached_width_px") is not None:
        return False
    warnings = list(summary.get("warnings") or [])
    if "attached_width_unavailable" in warnings:
        return True
    failure_reason = str(summary.get("failure_reason") or "").strip().lower()
    return "attached near-nozzle width unavailable" in failure_reason


def _width_ratio_to_baseline(width_px, baseline_width_px):
    width_value = _to_float_or_none(width_px)
    baseline_value = _to_float_or_none(baseline_width_px)
    if width_value in (None, 0.0) or baseline_value in (None, 0.0):
        return None
    return float(float(width_value) / float(baseline_value))


def _flow_anchor_summary(flow_summary: dict | None, baseline_width_px: float | int | None, *, phase_label: str):
    summary = dict(flow_summary or {})
    delay_us = _to_int(summary.get("delay_us"))
    delay_from_emergence_us = _to_int(summary.get("delay_from_emergence_us"))
    median_width_px = _to_float_or_none(summary.get("median_width_px"))
    width_ratio_to_baseline = _width_ratio_to_baseline(median_width_px, baseline_width_px)
    delay_accepted = bool(summary.get("delay_accepted"))
    return {
        "phase": str(phase_label),
        "delay_us": delay_us,
        "delay_from_emergence_us": delay_from_emergence_us,
        "attempted_replicates": _to_int(summary.get("attempted_replicates"), 0),
        "accepted_replicates": _to_int(summary.get("accepted_replicates"), 0),
        "tail_width_usable_replicates": _to_int(summary.get("accepted_replicates"), 0),
        "tail_landmark_usable_replicates": 0,
        "rejected_replicates": _to_int(summary.get("rejected_replicates"), 0),
        "median_width_px": median_width_px,
        "width_ratio_to_baseline": width_ratio_to_baseline,
        "tail_width_usable": bool(delay_accepted and median_width_px is not None),
        "tail_landmark_usable": False,
        "separated_from_nozzle_landmark": False,
        "attached_width_unavailable_landmark": False,
        "backup_width_collapse_landmark": False,
        "landmark_detected": False,
        "landmark_reason": None,
        "plateau_candidate": False,
        "early_departure_candidate": False,
        "strong_tail_candidate": False,
        "tail_affected": False,
        "tail_start_candidate": False,
        "attached_bottom_guard_hit": bool(summary.get("attached_bottom_guard_hit")),
        "detached_near_bottom_warning": bool(summary.get("detached_near_bottom_warning")),
        "near_nozzle_detached_warning": False,
        "late_frame_warning": False,
        "warnings": _copy_warnings(summary.get("warnings")),
        "delay_accepted": bool(delay_accepted),
        "triggered_scout": False,
        "triggered_backtrack": False,
        "triggered_coarse": False,
        "triggered_refine": False,
    }


def _classify_trace_rows(rows: list[dict], *, policy: dict | None = None) -> list[dict]:
    resolved_policy = _resolved_policy(policy)
    classified = []
    for row in list(rows or []):
        summary = dict(row or {})
        width_ratio_to_baseline = _to_float_or_none(summary.get("width_ratio_to_baseline"))
        tail_width_usable = bool(summary.get("tail_width_usable"))
        separated_from_nozzle_landmark = bool(summary.get("separated_from_nozzle_landmark"))
        attached_width_unavailable_landmark = bool(summary.get("attached_width_unavailable_landmark"))
        backup_width_collapse_landmark = bool(summary.get("backup_width_collapse_landmark"))
        plateau_candidate = bool(
            tail_width_usable
            and width_ratio_to_baseline is not None
            and float(width_ratio_to_baseline) >= float(resolved_policy["plateau_width_frac"])
            and not separated_from_nozzle_landmark
            and not attached_width_unavailable_landmark
        )
        early_departure_candidate = bool(
            tail_width_usable
            and width_ratio_to_baseline is not None
            and float(resolved_policy["departure_width_frac"]) <= float(width_ratio_to_baseline) < float(resolved_policy["plateau_width_frac"])
            and not separated_from_nozzle_landmark
            and not attached_width_unavailable_landmark
        )
        strong_tail_candidate = bool(
            (tail_width_usable and width_ratio_to_baseline is not None and float(width_ratio_to_baseline) < float(resolved_policy["departure_width_frac"]))
            or separated_from_nozzle_landmark
            or attached_width_unavailable_landmark
            or backup_width_collapse_landmark
        )
        summary["plateau_candidate"] = bool(plateau_candidate)
        summary["early_departure_candidate"] = bool(early_departure_candidate)
        summary["strong_tail_candidate"] = bool(strong_tail_candidate)
        summary["tail_affected"] = bool(strong_tail_candidate)
        summary["tail_start_candidate"] = bool(early_departure_candidate or strong_tail_candidate)
        classified.append(summary)
    classified.sort(
        key=lambda item: (
            _to_int(item.get("delay_from_emergence_us"), 10**9),
            _to_int(item.get("delay_us"), 10**9),
        )
    )
    return classified


def plan_online_stream_tail_phase(
    *,
    flow_fit_result: dict | None,
    priors: dict | None,
    emergence_time_us: int,
    capture_budget: dict | None,
    flow_delay_summaries: list[dict] | None = None,
    policy: dict | None = None,
) -> dict:
    fit = dict(flow_fit_result or {})
    normalized_priors = online_cal_mod.normalize_online_stream_prior(priors)
    resolved_policy = _resolved_policy(policy)
    steady_width_baseline_px = _to_float_or_none(fit.get("steady_width_baseline_px"))
    fit_status = str(fit.get("fit_status") or "")
    if steady_width_baseline_px is None or fit_status.startswith("unresolved"):
        return {
            "run_tail": False,
            "skip_reason": "missing_flow_baseline",
            "steady_width_baseline_px": steady_width_baseline_px,
            "tail_retarget_count": 0,
            "retargeted_coarse_start_delay_us": None,
        }

    accepted_flow_summaries = [
        dict(row or {})
        for row in list(flow_delay_summaries or [])
        if bool(dict(row or {}).get("delay_accepted")) and _to_int(dict(row or {}).get("delay_us")) is not None
    ]
    if not accepted_flow_summaries:
        return {
            "run_tail": False,
            "skip_reason": "missing_flow_tail_anchor",
            "steady_width_baseline_px": float(steady_width_baseline_px),
            "tail_retarget_count": 0,
            "retargeted_coarse_start_delay_us": None,
        }

    accepted_flow_summaries.sort(key=lambda item: _to_int(item.get("delay_us"), 0))
    last_flow_summary = dict(accepted_flow_summaries[-1])
    last_flow_delay_us = int(_to_int(last_flow_summary.get("delay_us"), 0))
    last_flow_delay_from_emergence_us = int(
        _to_int(last_flow_summary.get("delay_from_emergence_us"), int(last_flow_delay_us) - int(emergence_time_us))
    )
    scout_step_us = int(resolved_policy["scout_step_us"])
    scout_replicates = int(resolved_policy["scout_replicates"])
    max_scout_delay_count = int(resolved_policy["max_scout_delay_count"])
    backtrack_step_us = int(resolved_policy["backtrack_step_us"])
    backtrack_replicates = int(resolved_policy["backtrack_replicates"])
    fine_prepad_us = int(resolved_policy["fine_prepad_us"])
    fine_postpad_us = int(resolved_policy["fine_postpad_us"])
    reserved_backtrack_capture_count = int(resolved_policy["reserved_backtrack_capture_count"])
    remaining_hard = _remaining_hard_budget(capture_budget)
    required_capture_count = int(
        max(0, max_scout_delay_count) * max(1, scout_replicates)
        + max(0, reserved_backtrack_capture_count)
    )
    if remaining_hard < int(required_capture_count):
        return {
            "run_tail": False,
            "skip_reason": "capture_budget_exhausted",
            "steady_width_baseline_px": float(steady_width_baseline_px),
            "search_method": SEARCH_METHOD,
            "planned_scout_delay_count": int(max_scout_delay_count),
            "max_scout_delay_count": int(max_scout_delay_count),
            "reserved_backtrack_capture_count": int(reserved_backtrack_capture_count),
            "fine_prepad_us": int(fine_prepad_us),
            "fine_postpad_us": int(fine_postpad_us),
            "required_capture_count": int(required_capture_count),
            "tail_retarget_count": 0,
            "retargeted_coarse_start_delay_us": None,
        }
    planned_scout_delay_count = int(max(0, max_scout_delay_count))

    scout_first_delay_us = int(last_flow_delay_us + scout_step_us)
    scout_first_delay_from_emergence_us = int(last_flow_delay_from_emergence_us + scout_step_us)

    return {
        "run_tail": True,
        "skip_reason": None,
        "search_method": SEARCH_METHOD,
        "steady_width_baseline_px": float(steady_width_baseline_px),
        "plan_source": "last_flow_delay_anchor",
        "prior_condition_match": str(normalized_priors.get("condition_match") or "none"),
        "recorded_tail_start_offset_us": _to_int(normalized_priors.get("tail_start_offset_us")),
        "recorded_tail_coarse_step_us": _to_int(normalized_priors.get("tail_coarse_step_us")),
        "scout_anchor_delay_us": int(last_flow_delay_us),
        "scout_anchor_delay_from_emergence_us": int(last_flow_delay_from_emergence_us),
        "scout_first_delay_us": int(scout_first_delay_us),
        "scout_first_delay_from_emergence_us": int(scout_first_delay_from_emergence_us),
        "scout_step_us": int(scout_step_us),
        "scout_replicates": int(scout_replicates),
        "max_scout_delay_count": int(max_scout_delay_count),
        "backtrack_step_us": int(backtrack_step_us),
        "backtrack_replicates": int(backtrack_replicates),
        "fine_prepad_us": int(fine_prepad_us),
        "fine_postpad_us": int(fine_postpad_us),
        "planned_scout_delay_count": int(planned_scout_delay_count),
        "reserved_backtrack_capture_count": int(reserved_backtrack_capture_count),
        "tail_retarget_count": 0,
        "retargeted_coarse_start_delay_us": None,
        "coarse_start_delay_us": int(scout_first_delay_us),
        "coarse_step_us": int(scout_step_us),
        "coarse_replicates": int(scout_replicates),
        "refine_step_us": int(backtrack_step_us),
        "refine_replicates": int(backtrack_replicates),
        "planned_coarse_delay_count": int(planned_scout_delay_count),
        "reserved_refine_delay_count": int(reserved_backtrack_capture_count),
        "reserved_refine_capture_count": int(reserved_backtrack_capture_count),
    }


def summarize_online_stream_tail_delay(
    frame_rows: list[dict],
    baseline_width_px: float | int | None,
    *,
    policy: dict | None = None,
) -> dict:
    rows = [dict(row or {}) for row in list(frame_rows or [])]
    width_usable_rows = [row for row in rows if _legacy_tail_width_usable(row)]
    landmark_usable_rows = [row for row in rows if _legacy_tail_landmark_usable(row)]
    usable_rows = [
        row
        for row in rows
        if _legacy_tail_width_usable(row) or _legacy_tail_landmark_usable(row)
    ]
    attempted_replicates = int(len(rows))
    accepted_replicates = int(len(usable_rows))
    width_usable_replicates = int(len(width_usable_rows))
    landmark_usable_replicates = int(len(landmark_usable_rows))
    rejected_replicates = int(max(0, attempted_replicates - accepted_replicates))
    median_width_px = _median_or_none(row.get("attached_width_px") for row in width_usable_rows)
    width_ratio_to_baseline = _width_ratio_to_baseline(median_width_px, baseline_width_px)
    resolved_policy = _resolved_policy(policy)
    warnings = _unique_strings(
        warning
        for row in rows
        for warning in list(row.get("warnings") or [])
    )
    attached_bottom_guard_hit = any(
        str(row.get("status") or "") == "rejected_bottom_guard"
        or bool(row.get("attached_bottom_guard_hit"))
        or ("attached_bottom_guard_hit" in list(row.get("warnings") or []))
        for row in rows
    )
    detached_near_bottom_warning = any(
        bool(row.get("detached_near_bottom_warning"))
        or ("detached_near_bottom_warning" in list(row.get("warnings") or []))
        for row in rows
    )
    near_nozzle_detached_warning = any(
        bool(row.get("near_nozzle_detached_warning"))
        or ("near_nozzle_detached_warning" in list(row.get("warnings") or []))
        for row in rows
    )
    attached_width_unavailable_landmark = any(
        _attached_width_unavailable_landmark_row(row)
        for row in rows
    )
    late_frame_warning = bool(
        any(bool(row.get("late_frame_warning")) for row in rows)
        or attached_bottom_guard_hit
        or detached_near_bottom_warning
    )
    separated_from_nozzle_landmark = any(
        bool(row.get("separated_from_nozzle_landmark"))
        for row in rows
    )
    backup_width_collapse_landmark = bool(
        width_usable_replicates > 0
        and width_ratio_to_baseline is not None
        and float(width_ratio_to_baseline) <= float(resolved_policy["scout_landmark_width_frac"])
        and not separated_from_nozzle_landmark
        and not attached_width_unavailable_landmark
    )
    landmark_detected = bool(
        separated_from_nozzle_landmark
        or attached_width_unavailable_landmark
        or backup_width_collapse_landmark
    )
    landmark_reason = None
    if separated_from_nozzle_landmark:
        landmark_reason = "separated_from_nozzle"
    elif attached_width_unavailable_landmark:
        landmark_reason = "attached_width_unavailable"
    elif backup_width_collapse_landmark:
        landmark_reason = "strong_width_collapse_backup"

    delay_us = None
    delay_from_emergence_us = None
    phase = None
    if rows:
        delay_us = _to_int(rows[0].get("delay_us"))
        delay_from_emergence_us = _to_int(rows[0].get("delay_from_emergence_us"))
        phase = str(rows[0].get("phase") or "")

    summary = {
        "phase": phase,
        "delay_us": delay_us,
        "delay_from_emergence_us": delay_from_emergence_us,
        "attempted_replicates": int(attempted_replicates),
        "accepted_replicates": int(accepted_replicates),
        "tail_width_usable_replicates": int(width_usable_replicates),
        "tail_landmark_usable_replicates": int(landmark_usable_replicates),
        "rejected_replicates": int(rejected_replicates),
        "median_width_px": median_width_px,
        "width_ratio_to_baseline": width_ratio_to_baseline,
        "tail_width_usable": bool(width_usable_replicates > 0),
        "tail_landmark_usable": bool(landmark_usable_replicates > 0),
        "separated_from_nozzle_landmark": bool(separated_from_nozzle_landmark),
        "attached_width_unavailable_landmark": bool(attached_width_unavailable_landmark),
        "backup_width_collapse_landmark": bool(backup_width_collapse_landmark),
        "landmark_detected": bool(landmark_detected),
        "landmark_reason": landmark_reason,
        "attached_bottom_guard_hit": bool(attached_bottom_guard_hit),
        "detached_near_bottom_warning": bool(detached_near_bottom_warning),
        "near_nozzle_detached_warning": bool(near_nozzle_detached_warning),
        "late_frame_warning": bool(late_frame_warning),
        "warnings": warnings,
        "delay_accepted": bool(accepted_replicates > 0),
        "triggered_scout": bool(landmark_detected),
        "triggered_backtrack": False,
        "triggered_coarse": bool(landmark_detected),
        "triggered_refine": False,
    }
    classified = _classify_trace_rows([summary], policy=resolved_policy)
    if classified:
        summary.update(classified[0])
    return summary


def build_online_stream_tail_backtrack_plan(
    *,
    scout_anchor_delay_us: int | None = None,
    left_endpoint_delay_us: int | None,
    landmark_delay_us: int | None,
    backtrack_step_us: int,
    fine_prepad_us: int | None = None,
    fine_postpad_us: int | None = None,
) -> list[int]:
    scout_anchor_delay = _to_int(scout_anchor_delay_us)
    left_delay_us = _to_int(left_endpoint_delay_us)
    right_delay_us = _to_int(landmark_delay_us)
    step_us = max(1, _to_int(backtrack_step_us, DEFAULT_ONLINE_TAIL_POLICY["backtrack_step_us"]))
    prepad_us = max(0, _to_int(fine_prepad_us, DEFAULT_ONLINE_TAIL_POLICY["fine_prepad_us"]))
    postpad_us = max(0, _to_int(fine_postpad_us, DEFAULT_ONLINE_TAIL_POLICY["fine_postpad_us"]))
    if left_delay_us is None or right_delay_us is None or int(left_delay_us) > int(right_delay_us):
        return []
    start_delay_us = int(left_delay_us) - int(prepad_us)
    if scout_anchor_delay is not None:
        start_delay_us = max(int(scout_anchor_delay), int(start_delay_us))
    end_delay_us = int(right_delay_us) + int(postpad_us)
    if int(start_delay_us) > int(end_delay_us):
        return []
    return [
        int(delay_us)
        for delay_us in range(int(start_delay_us), int(end_delay_us) + int(step_us), int(step_us))
    ]


def build_online_stream_tail_refine_plan(
    *,
    last_coarse_nontrigger_delay_us: int | None,
    first_coarse_trigger_delay_us: int | None,
    refine_step_us: int,
    coarse_step_us: int | None = None,
    planned_coarse_start_delay_us: int | None = None,
) -> list[int]:
    del coarse_step_us, planned_coarse_start_delay_us
    return build_online_stream_tail_backtrack_plan(
        left_endpoint_delay_us=last_coarse_nontrigger_delay_us,
        landmark_delay_us=first_coarse_trigger_delay_us,
        backtrack_step_us=refine_step_us,
        fine_prepad_us=0,
        fine_postpad_us=0,
    )


def decide_online_stream_tail_next_action(
    *,
    mode: str,
    delay_summary: dict | None,
    capture_budget: dict | None,
    consecutive_failed_delays: int = 0,
    attempted_delay_count: int = 0,
    planned_delay_count: int = 0,
    policy: dict | None = None,
    **unused,
) -> dict:
    del unused
    summary = dict(delay_summary or {})
    budget = dict(capture_budget or {})
    resolved_policy = _resolved_policy(policy)
    mode_label = str(mode or "scout")
    if mode_label == "coarse":
        mode_label = "scout"
    if mode_label == "refine":
        mode_label = "backtrack"

    if mode_label == "scout":
        if bool(summary.get("delay_accepted")) and bool(summary.get("landmark_detected")):
            return {
                "action": "switch_to_backtrack",
                "tail_phase_status": None,
                "termination_reason": None,
                "landmark_reason": str(summary.get("landmark_reason") or ""),
            }
        if int(consecutive_failed_delays) >= int(resolved_policy["consecutive_failed_tail_delays_stop"]):
            return {
                "action": "stop",
                "tail_phase_status": "unresolved_qc_failure",
                "termination_reason": "repeated_tail_qc_failure",
            }
        if int(attempted_delay_count) >= int(max(0, planned_delay_count)):
            return {
                "action": "stop",
                "tail_phase_status": "unresolved_no_landmark",
                "termination_reason": "no_scout_landmark",
            }
        if bool(budget.get("exhausted")):
            return {
                "action": "stop",
                "tail_phase_status": "unresolved_budget_exhausted",
                "termination_reason": "capture_budget_exhausted",
            }
        return {
            "action": "continue",
            "tail_phase_status": None,
            "termination_reason": None,
        }

    if int(consecutive_failed_delays) >= int(resolved_policy["consecutive_failed_tail_delays_stop"]):
        return {
            "action": "stop",
            "tail_phase_status": "unresolved_qc_failure",
            "termination_reason": "repeated_tail_qc_failure",
        }
    if bool(budget.get("exhausted")):
        return {
            "action": "stop",
            "tail_phase_status": "unresolved_budget_exhausted",
            "termination_reason": "capture_budget_exhausted",
        }
    if int(attempted_delay_count) >= int(max(0, planned_delay_count)):
        return {
            "action": "finish_resolve",
            "tail_phase_status": None,
            "termination_reason": None,
        }
    return {
        "action": "continue",
        "tail_phase_status": None,
        "termination_reason": None,
    }


def resolve_online_stream_tail_result(
    *,
    flow_fit_result: dict | None,
    tail_plan: dict | None,
    scout_summaries: list[dict] | None = None,
    backtrack_summaries: list[dict] | None = None,
    coarse_summaries: list[dict] | None = None,
    refine_summaries: list[dict] | None = None,
    trigger_bracket: dict | None,
    flow_delay_summaries: list[dict] | None = None,
    phase: str = "online_stream_calibration",
) -> dict:
    fit = dict(flow_fit_result or {})
    plan = dict(tail_plan or {})
    scout_rows = [
        dict(row or {})
        for row in list(scout_summaries if scout_summaries is not None else coarse_summaries or [])
    ]
    backtrack_rows = [
        dict(row or {})
        for row in list(backtrack_summaries if backtrack_summaries is not None else refine_summaries or [])
    ]
    bracket = dict(trigger_bracket or {})
    resolved_policy = _resolved_policy(plan.get("policy") if isinstance(plan.get("policy"), dict) else None)

    scout_rows = _classify_trace_rows(scout_rows, policy=resolved_policy)
    backtrack_rows = _classify_trace_rows(backtrack_rows, policy=resolved_policy)

    requested_status = str(bracket.get("tail_phase_status") or bracket.get("status") or "").strip()
    termination_reason = str(bracket.get("termination_reason") or "").strip()
    landmark_delay_us = _to_int(bracket.get("landmark_delay_us"), _to_int(bracket.get("trigger_delay_us")))
    landmark_reason = str(bracket.get("landmark_reason") or bracket.get("trigger_reason") or "").strip() or None
    backtrack_left_delay_us = _to_int(
        bracket.get("backtrack_left_delay_us"),
        _to_int(bracket.get("last_nontrigger_delay_us")),
    )

    if landmark_delay_us is None:
        for row in scout_rows:
            if bool(row.get("landmark_detected")):
                landmark_delay_us = _to_int(row.get("delay_us"))
                landmark_reason = str(row.get("landmark_reason") or landmark_reason or "").strip() or None
                break
    landmark_summary = _find_delay_summary(scout_rows, landmark_delay_us)

    if backtrack_left_delay_us is None and landmark_delay_us is not None:
        scout_before_landmark = [
            int(dict(row or {}).get("delay_us"))
            for row in scout_rows
            if _to_int(dict(row or {}).get("delay_us")) is not None
            and _to_int(dict(row or {}).get("delay_us")) < int(landmark_delay_us)
        ]
        if scout_before_landmark:
            backtrack_left_delay_us = max(scout_before_landmark)
        else:
            backtrack_left_delay_us = _to_int(plan.get("scout_anchor_delay_us"))

    baseline_width_px = _to_float_or_none(fit.get("steady_width_baseline_px"))
    left_endpoint_summary = _find_delay_summary(backtrack_rows, backtrack_left_delay_us)
    if left_endpoint_summary is None:
        left_endpoint_summary = _find_delay_summary(scout_rows, backtrack_left_delay_us)
    if left_endpoint_summary is None:
        left_endpoint_summary = _flow_anchor_summary(
            _find_delay_summary(list(flow_delay_summaries or []), backtrack_left_delay_us),
            baseline_width_px,
            phase_label="flow_anchor",
        )

    local_trace_rows_by_delay = {}
    for row in list(backtrack_rows or []):
        summary = dict(row or {})
        delay_value = _to_int(summary.get("delay_us"))
        if delay_value is None:
            continue
        local_trace_rows_by_delay[int(delay_value)] = summary
    for row in [left_endpoint_summary, landmark_summary]:
        if not row:
            continue
        summary = dict(row or {})
        delay_value = _to_int(summary.get("delay_us"))
        if delay_value is None or int(delay_value) in local_trace_rows_by_delay:
            continue
        local_trace_rows_by_delay[int(delay_value)] = summary
    local_trace = list(local_trace_rows_by_delay.values())
    local_trace = _classify_trace_rows(local_trace, policy=resolved_policy)

    separation_landmark_delay_from_emergence_us = None
    for row in list(scout_rows) + list(backtrack_rows):
        if bool(row.get("separated_from_nozzle_landmark")):
            separation_landmark_delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
            break

    right_bracket_row = None
    for row in local_trace:
        row_delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
        if not bool(row.get("strong_tail_candidate")):
            continue
        if (
            separation_landmark_delay_from_emergence_us is not None
            and row_delay_from_emergence_us is not None
            and int(row_delay_from_emergence_us) >= int(separation_landmark_delay_from_emergence_us)
        ):
            continue
        right_bracket_row = dict(row)
        break

    if right_bracket_row is None and separation_landmark_delay_from_emergence_us is not None:
        for row in local_trace:
            row_delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
            if (
                bool(row.get("separated_from_nozzle_landmark"))
                and row_delay_from_emergence_us is not None
                and int(row_delay_from_emergence_us) == int(separation_landmark_delay_from_emergence_us)
            ):
                right_bracket_row = dict(row)
                break

    last_plateau_row = None
    if right_bracket_row is not None:
        right_bracket_delay_from_emergence_us = _to_int(right_bracket_row.get("delay_from_emergence_us"))
        for row in local_trace:
            row_delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
            if row_delay_from_emergence_us is None or right_bracket_delay_from_emergence_us is None:
                continue
            if int(row_delay_from_emergence_us) >= int(right_bracket_delay_from_emergence_us):
                break
            if bool(row.get("plateau_candidate")):
                last_plateau_row = dict(row)

    early_departure_rows = []
    if right_bracket_row is not None and last_plateau_row is not None:
        left_delay_from_emergence_us = _to_int(last_plateau_row.get("delay_from_emergence_us"))
        right_delay_from_emergence_us = _to_int(right_bracket_row.get("delay_from_emergence_us"))
        for row in local_trace:
            row_delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
            if (
                row_delay_from_emergence_us is None
                or left_delay_from_emergence_us is None
                or right_delay_from_emergence_us is None
            ):
                continue
            if int(row_delay_from_emergence_us) <= int(left_delay_from_emergence_us):
                continue
            if int(row_delay_from_emergence_us) >= int(right_delay_from_emergence_us):
                continue
            if bool(row.get("early_departure_candidate")):
                early_departure_rows.append(dict(row))

    captured_candidate = None
    midpoint_candidate_delay_from_emergence_us = None
    tail_start_selection_method = None
    if early_departure_rows:
        captured_candidate = dict(early_departure_rows[0])
        tail_start_selection_method = "earliest_early_departure_before_strong_tail"
    elif (
        right_bracket_row is not None
        and last_plateau_row is not None
        and not bool(right_bracket_row.get("separated_from_nozzle_landmark"))
    ):
        left_delay_from_emergence_us = _to_int(last_plateau_row.get("delay_from_emergence_us"))
        right_delay_from_emergence_us = _to_int(right_bracket_row.get("delay_from_emergence_us"))
        if left_delay_from_emergence_us is not None and right_delay_from_emergence_us is not None:
            midpoint_candidate_delay_from_emergence_us = int(
                (int(left_delay_from_emergence_us) + int(right_delay_from_emergence_us)) / 2
            )
            tail_start_selection_method = "plateau_strong_tail_midpoint"

    warnings = _unique_strings(
        list(plan.get("warnings") or [])
        + list(bracket.get("warnings") or [])
        + [warning for row in scout_rows for warning in list(row.get("warnings") or [])]
        + [warning for row in backtrack_rows for warning in list(row.get("warnings") or [])]
    )

    late_frame_warning = bool(
        any(bool(row.get("late_frame_warning")) for row in scout_rows)
        or any(bool(row.get("late_frame_warning")) for row in backtrack_rows)
    )

    tail_phase_status = requested_status or ""
    tail_start_delay_from_emergence_us = None
    tail_start_evidence = None
    if tail_phase_status in {
        "unresolved_missing_flow_baseline",
        "unresolved_budget_exhausted",
        "unresolved_qc_failure",
        "unresolved_no_landmark",
    }:
        pass
    elif landmark_summary is None:
        tail_phase_status = "unresolved_no_landmark"
        if not termination_reason:
            termination_reason = "no_scout_landmark"
        if "unresolved_no_landmark" not in warnings:
            warnings.append("unresolved_no_landmark")
    elif captured_candidate is not None:
        tail_phase_status = "captured"
        termination_reason = termination_reason or "backtrack_width_departure"
        tail_start_delay_from_emergence_us = _to_int(captured_candidate.get("delay_from_emergence_us"))
        if (
            _to_int(captured_candidate.get("delay_us")) == _to_int(landmark_summary.get("delay_us"))
            and str(landmark_summary.get("landmark_reason") or "") == "strong_width_collapse_backup"
        ):
            tail_start_evidence = "width_collapse_backup"
        else:
            tail_start_evidence = "backtrack_width_departure"
    elif midpoint_candidate_delay_from_emergence_us is not None:
        tail_phase_status = "captured"
        termination_reason = termination_reason or "plateau_strong_tail_midpoint"
        tail_start_delay_from_emergence_us = int(midpoint_candidate_delay_from_emergence_us)
        tail_start_evidence = "plateau_strong_tail_midpoint"
    elif str(landmark_summary.get("landmark_reason") or "") == "separated_from_nozzle":
        tail_phase_status = "advisory_landmark_only"
        termination_reason = termination_reason or "landmark_only"
        tail_start_delay_from_emergence_us = _to_int(landmark_summary.get("delay_from_emergence_us"))
        tail_start_evidence = "landmark_only"
        if "tail_landmark_only" not in warnings:
            warnings.append("tail_landmark_only")
    elif (
        str(landmark_summary.get("landmark_reason") or "") in {"strong_width_collapse_backup", "attached_width_unavailable"}
        and any(bool(row.get("plateau_candidate")) for row in local_trace)
    ):
        tail_phase_status = "captured"
        termination_reason = termination_reason or "backtrack_width_departure"
        tail_start_delay_from_emergence_us = _to_int(landmark_summary.get("delay_from_emergence_us"))
        tail_start_evidence = str(landmark_summary.get("landmark_reason") or "")
        tail_start_selection_method = tail_start_selection_method or "landmark_fallback"
    else:
        tail_phase_status = "unresolved_no_landmark"
        termination_reason = termination_reason or "no_scout_landmark"
        if "unresolved_no_landmark" not in warnings:
            warnings.append("unresolved_no_landmark")

    predicted_stream_duration_us = None
    predicted_volume_nl = None
    flow_rate = _to_float_or_none(fit.get("flow_rate_nl_per_us"))
    flow_intercept = _to_float_or_none(fit.get("flow_intercept_nl"))
    if (
        tail_phase_status in {"captured", "advisory_landmark_only"}
        and tail_start_delay_from_emergence_us is not None
        and flow_rate is not None
        and flow_intercept is not None
    ):
        predicted_stream_duration_us = int(tail_start_delay_from_emergence_us)
        predicted_volume_nl = float(
            float(flow_intercept) + (float(flow_rate) * float(predicted_stream_duration_us))
        )

    landmark_delay_from_emergence_us = _summary_delay_from_emergence(landmark_summary, landmark_delay_us)
    fine_window_delays_us = build_online_stream_tail_backtrack_plan(
        scout_anchor_delay_us=_to_int(plan.get("scout_anchor_delay_us")),
        left_endpoint_delay_us=backtrack_left_delay_us,
        landmark_delay_us=landmark_delay_us,
        backtrack_step_us=int(plan.get("backtrack_step_us") or DEFAULT_ONLINE_TAIL_POLICY["backtrack_step_us"]),
        fine_prepad_us=_to_int(plan.get("fine_prepad_us"), DEFAULT_ONLINE_TAIL_POLICY["fine_prepad_us"]),
        fine_postpad_us=_to_int(plan.get("fine_postpad_us"), DEFAULT_ONLINE_TAIL_POLICY["fine_postpad_us"]),
    )
    if backtrack_rows:
        sampled_backtrack_delays_us = sorted(
            int(dict(row or {}).get("delay_us"))
            for row in backtrack_rows
            if _to_int(dict(row or {}).get("delay_us")) is not None
        )
        if sampled_backtrack_delays_us:
            fine_window_delays_us = list(sampled_backtrack_delays_us)
    fine_window_start_delay_us = fine_window_delays_us[0] if fine_window_delays_us else backtrack_left_delay_us
    fine_window_end_delay_us = fine_window_delays_us[-1] if fine_window_delays_us else landmark_delay_us
    backtrack_window_start_delay_from_emergence_us = _delay_from_emergence_from_plan(
        plan,
        fine_window_start_delay_us,
    )
    if backtrack_window_start_delay_from_emergence_us is None:
        backtrack_window_start_delay_from_emergence_us = _summary_delay_from_emergence(
            left_endpoint_summary,
            fine_window_start_delay_us,
        )
    backtrack_window_end_delay_from_emergence_us = _delay_from_emergence_from_plan(
        plan,
        fine_window_end_delay_us,
    )
    if backtrack_window_end_delay_from_emergence_us is None:
        backtrack_window_end_delay_from_emergence_us = _summary_delay_from_emergence(
            landmark_summary,
            fine_window_end_delay_us,
        )

    all_summaries = list(scout_rows) + list(backtrack_rows)
    tail_phase = {
        "status": str(tail_phase_status or "unresolved_no_landmark"),
        "plan": _copy_jsonish(plan),
        "search_method": SEARCH_METHOD,
        "max_scout_delay_count": _to_int(plan.get("max_scout_delay_count")),
        "fine_prepad_us": _to_int(plan.get("fine_prepad_us")),
        "fine_postpad_us": _to_int(plan.get("fine_postpad_us")),
        "reserved_backtrack_capture_count": _to_int(plan.get("reserved_backtrack_capture_count")),
        "attempted_delay_count": int(len(all_summaries)),
        "attempted_capture_count": int(
            sum(max(0, _to_int(row.get("attempted_replicates"), 0)) for row in all_summaries)
        ),
        "accepted_delay_count": int(sum(1 for row in all_summaries if bool(row.get("delay_accepted")))),
        "accepted_measurement_count": int(
            sum(max(0, _to_int(row.get("accepted_replicates"), 0)) for row in all_summaries)
        ),
        "termination_reason": str(termination_reason),
        "scout_delay_summaries": _copy_jsonish(scout_rows),
        "backtrack_delay_summaries": _copy_jsonish(backtrack_rows),
        "coarse_delay_summaries": _copy_jsonish(scout_rows),
        "refine_delay_summaries": _copy_jsonish(backtrack_rows),
        "landmark_delay_from_emergence_us": landmark_delay_from_emergence_us,
        "landmark_reason": landmark_reason or (None if landmark_summary is None else landmark_summary.get("landmark_reason")),
        "backtrack_window_start_delay_from_emergence_us": backtrack_window_start_delay_from_emergence_us,
        "backtrack_window_end_delay_from_emergence_us": backtrack_window_end_delay_from_emergence_us,
        "fine_window_start_delay_from_emergence_us": backtrack_window_start_delay_from_emergence_us,
        "fine_window_end_delay_from_emergence_us": backtrack_window_end_delay_from_emergence_us,
        "tail_start_evidence": tail_start_evidence,
        "tail_start_selection_method": tail_start_selection_method,
        "trigger_delay_from_emergence_us": landmark_delay_from_emergence_us,
        "trigger_reason": landmark_reason or (None if landmark_summary is None else landmark_summary.get("landmark_reason")),
        "last_nontrigger_delay_from_emergence_us": backtrack_window_start_delay_from_emergence_us,
        "synthetic_left_bracket_used": False,
        "late_frame_warning": bool(late_frame_warning),
        "tail_retarget_count": 0,
        "retargeted_coarse_start_delay_us": None,
        "tail_start_delay_from_emergence_us": (
            None if tail_start_delay_from_emergence_us is None else int(tail_start_delay_from_emergence_us)
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
    scout_delay_summaries: list[dict] | None = None,
    backtrack_delay_summaries: list[dict] | None = None,
    coarse_delay_summaries: list[dict] | None = None,
    refine_delay_summaries: list[dict] | None = None,
    result: dict | None = None,
    warnings: list[str] | None = None,
    schema_version: int = 1,
    phase: str = "online_stream_calibration",
) -> dict:
    result_obj = dict(result or {})
    resolved_scout_rows = scout_delay_summaries if scout_delay_summaries is not None else coarse_delay_summaries or []
    resolved_backtrack_rows = (
        backtrack_delay_summaries if backtrack_delay_summaries is not None else refine_delay_summaries or []
    )
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
        "search_method": SEARCH_METHOD,
        "scout_delay_summaries": _copy_jsonish(resolved_scout_rows),
        "backtrack_delay_summaries": _copy_jsonish(resolved_backtrack_rows),
        "coarse_delay_summaries": _copy_jsonish(resolved_scout_rows),
        "refine_delay_summaries": _copy_jsonish(resolved_backtrack_rows),
        "result": _copy_jsonish(result_obj),
        "warnings": _copy_warnings(
            warnings if warnings is not None else result_obj.get("warnings")
        ),
    }
