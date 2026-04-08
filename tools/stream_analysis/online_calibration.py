from __future__ import annotations


DEFAULT_ONLINE_STREAM_POLICY = {
    "flow_start_offset_us": 650,
    "flow_step_us": 57,
    "flow_delay_count": 15,
    "flow_replicates": 1,
    "tail_fallback_start_offset_us": 3600,
    "tail_exact_prior_start_lead_us": 400,
    "tail_coarse_step_us": 100,
    "tail_coarse_replicates": 2,
    "tail_refine_step_us": 50,
    "tail_refine_replicates": 2,
    "nominal_capture_budget": 30,
    "hard_capture_budget": 36,
    "bottom_of_fov_guard_px": 96,
}

DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG = {
    "nozzle_guard_px": 2,
    "min_component_area_px": 120,
    "attached_bottom_guard_px": 96,
    "detached_near_bottom_warning_px": 96,
    "near_nozzle_band_top_px": 24,
    "near_nozzle_band_height_px": 40,
    "min_band_valid_rows": 24,
}


def _to_int(value, default: int | None):
    try:
        if value in (None, ""):
            return None if default is None else int(default)
        return int(value)
    except Exception:
        return None if default is None else int(default)


def _to_float_or_none(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _copy_warnings(value) -> list[str]:
    warnings = []
    for item in list(value or []):
        warnings.append(str(item))
    return warnings


def _copy_jsonish(value):
    if isinstance(value, dict):
        return {str(key): _copy_jsonish(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_jsonish(item) for item in value]
    return value


def _resolved_policy(policy: dict | None = None) -> dict:
    merged = dict(DEFAULT_ONLINE_STREAM_POLICY)
    for key, default_value in DEFAULT_ONLINE_STREAM_POLICY.items():
        if isinstance(policy, dict) and key in policy:
            merged[key] = _to_int(policy.get(key), default_value)
    return merged


def _resolved_analysis_config(config: dict | None = None) -> dict:
    merged = dict(DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG)
    for key, default_value in DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG.items():
        if isinstance(config, dict) and key in config:
            merged[key] = _to_int(config.get(key), default_value)
    return merged


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


def _unique_strings(values) -> list[str]:
    output = []
    seen = set()
    for value in list(values or []):
        label = str(value)
        if label in seen:
            continue
        seen.add(label)
        output.append(label)
    return output


def normalize_online_stream_prior(prior: dict | None, policy: dict | None = None) -> dict:
    policy = _resolved_policy(policy)
    prior_obj = dict(prior or {})
    had_prior = bool(prior_obj)
    return {
        "condition_match": str(prior_obj.get("condition_match") or ("provided" if had_prior else "none")),
        "flow_start_offset_us": _to_int(
            prior_obj.get("flow_start_offset_us"),
            policy["flow_start_offset_us"],
        ),
        "flow_step_us": _to_int(
            prior_obj.get("flow_step_us"),
            policy["flow_step_us"],
        ),
        "flow_delay_count": _to_int(
            prior_obj.get("flow_delay_count"),
            policy["flow_delay_count"],
        ),
        "tail_start_offset_us": _to_int(
            prior_obj.get("tail_start_offset_us"),
            policy["tail_fallback_start_offset_us"],
        ),
        "tail_coarse_step_us": _to_int(
            prior_obj.get("tail_coarse_step_us"),
            policy["tail_coarse_step_us"],
        ),
        "source": str(prior_obj.get("source") or ("provided" if had_prior else "default")),
        "warnings": _copy_warnings(prior_obj.get("warnings")),
    }


def build_online_stream_flow_plan(
    *,
    emergence_time_us: int,
    prior: dict | None = None,
    policy: dict | None = None,
) -> dict:
    resolved_policy = _resolved_policy(policy)
    normalized_prior = normalize_online_stream_prior(prior, policy=resolved_policy)
    start_offset_us = _to_int(
        normalized_prior.get("flow_start_offset_us"),
        resolved_policy["flow_start_offset_us"],
    )
    step_us = int(resolved_policy["flow_step_us"])
    delay_count = max(1, int(resolved_policy["flow_delay_count"]))
    offsets = [int(start_offset_us + (idx * step_us)) for idx in range(delay_count)]
    delays = [int(emergence_time_us) + int(offset) for offset in offsets]
    default_offsets = [
        int(resolved_policy["flow_start_offset_us"] + (idx * resolved_policy["flow_step_us"]))
        for idx in range(int(resolved_policy["flow_delay_count"]))
    ]
    plan_source = "prior_adjusted" if offsets != default_offsets else "default"
    return {
        "emergence_time_us": int(emergence_time_us),
        "delay_offsets_from_emergence_us": offsets,
        "delays_us": delays,
        "replicates_per_delay": int(resolved_policy["flow_replicates"]),
        "point_count": int(len(delays)),
        "plan_source": str(plan_source),
    }


def build_online_stream_tail_plan(
    *,
    emergence_time_us: int,
    prior: dict | None = None,
    policy: dict | None = None,
) -> dict:
    resolved_policy = _resolved_policy(policy)
    normalized_prior = normalize_online_stream_prior(prior, policy=resolved_policy)
    coarse_step_us = _to_int(
        normalized_prior.get("tail_coarse_step_us"),
        resolved_policy["tail_coarse_step_us"],
    )
    coarse_start_offset_us = int(resolved_policy["tail_fallback_start_offset_us"])
    plan_source = "default"
    if str(normalized_prior.get("condition_match") or "") == "exact":
        coarse_start_offset_us = int(
            _to_int(
                normalized_prior.get("tail_start_offset_us"),
                resolved_policy["tail_fallback_start_offset_us"],
            )
            - int(resolved_policy["tail_exact_prior_start_lead_us"])
        )
        plan_source = "exact_prior_minus_lead"
    coarse_start_delay_us = int(emergence_time_us) + int(coarse_start_offset_us)
    return {
        "emergence_time_us": int(emergence_time_us),
        "coarse_start_offset_us": int(coarse_start_offset_us),
        "coarse_start_delay_us": int(coarse_start_delay_us),
        "coarse_step_us": int(coarse_step_us),
        "coarse_replicates": int(resolved_policy["tail_coarse_replicates"]),
        "refine_step_us": int(resolved_policy["tail_refine_step_us"]),
        "refine_replicates": int(resolved_policy["tail_refine_replicates"]),
        "plan_source": str(plan_source),
    }


def new_online_stream_budget(*, policy: dict | None = None) -> dict:
    resolved_policy = _resolved_policy(policy)
    nominal_limit = int(resolved_policy["nominal_capture_budget"])
    hard_limit = int(resolved_policy["hard_capture_budget"])
    return {
        "nominal_limit": nominal_limit,
        "hard_limit": hard_limit,
        "captures_used": 0,
        "captures_remaining_nominal": nominal_limit,
        "captures_remaining_hard": hard_limit,
        "exhausted": False,
        "history": [],
    }


def consume_online_stream_budget(budget: dict, *, phase: str, count: int = 1) -> dict:
    next_budget = dict(budget or {})
    history = [dict(item) for item in list(next_budget.get("history") or [])]
    nominal_limit = _to_int(next_budget.get("nominal_limit"), DEFAULT_ONLINE_STREAM_POLICY["nominal_capture_budget"])
    hard_limit = _to_int(next_budget.get("hard_limit"), DEFAULT_ONLINE_STREAM_POLICY["hard_capture_budget"])
    captures_used = _to_int(next_budget.get("captures_used"), 0)
    consume_count = max(0, _to_int(count, 1))
    captures_used_after = int(captures_used + consume_count)
    remaining_nominal = max(0, int(nominal_limit - captures_used_after))
    remaining_hard = max(0, int(hard_limit - captures_used_after))
    exhausted = bool(captures_used_after >= hard_limit)
    history.append(
        {
            "phase": str(phase),
            "count": int(consume_count),
            "captures_used_after": int(captures_used_after),
            "captures_remaining_nominal": int(remaining_nominal),
            "captures_remaining_hard": int(remaining_hard),
            "exhausted": bool(exhausted),
        }
    )
    next_budget["nominal_limit"] = int(nominal_limit)
    next_budget["hard_limit"] = int(hard_limit)
    next_budget["captures_used"] = int(captures_used_after)
    next_budget["captures_remaining_nominal"] = int(remaining_nominal)
    next_budget["captures_remaining_hard"] = int(remaining_hard)
    next_budget["exhausted"] = bool(exhausted)
    next_budget["history"] = history
    return next_budget


def build_online_stream_frame_row(
    *,
    phase: str,
    status: str,
    delay_us: int,
    delay_from_emergence_us: int,
    replicate_index: int,
    qc: dict | None = None,
    image_ref: dict | None = None,
    warnings: list[str] | None = None,
    **extra,
) -> dict:
    row = {
        "phase": str(phase),
        "status": str(status),
        "delay_us": int(delay_us),
        "delay_from_emergence_us": int(delay_from_emergence_us),
        "replicate_index": int(replicate_index),
        "qc": dict(qc or {}),
        "image_ref": dict(image_ref or {}),
        "warnings": _copy_warnings(warnings),
    }
    for key, value in dict(extra or {}).items():
        row[str(key)] = value
    return row


def build_online_stream_measurement_row(
    *,
    phase: str,
    delay_us: int,
    delay_from_emergence_us: int,
    replicate_index: int,
    width_px: float | int | None,
    visible_volume_nl: float | int | None,
    qc_pass: bool,
    image_ref: dict | None = None,
    nozzle_qc_pass: bool | None = None,
    silhouette_qc_pass: bool | None = None,
    attached_bottom_clearance_px: float | int | None = None,
) -> dict:
    return {
        "phase": str(phase),
        "delay_us": int(delay_us),
        "delay_from_emergence_us": int(delay_from_emergence_us),
        "replicate_index": int(replicate_index),
        "width_px": None if width_px is None else float(width_px),
        "visible_volume_nl": None if visible_volume_nl is None else float(visible_volume_nl),
        "qc_pass": bool(qc_pass),
        "image_ref": dict(image_ref or {}),
        "nozzle_qc_pass": None if nozzle_qc_pass is None else bool(nozzle_qc_pass),
        "silhouette_qc_pass": None if silhouette_qc_pass is None else bool(silhouette_qc_pass),
        "attached_bottom_clearance_px": (
            None
            if attached_bottom_clearance_px is None
            else float(attached_bottom_clearance_px)
        ),
    }


def build_online_stream_plan_snapshot(
    *,
    condition: dict | None = None,
    priors: dict | None = None,
    flow_plan: dict | None = None,
    tail_plan: dict | None = None,
    capture_budget: dict | None = None,
    analysis_config: dict | None = None,
    schema_version: int = 1,
    phase: str = "online_stream_calibration",
) -> dict:
    return {
        "schema_version": int(schema_version),
        "phase": str(phase),
        "condition": _copy_jsonish(condition or {}),
        "priors": _copy_jsonish(priors or {}),
        "flow_plan": _copy_jsonish(flow_plan or {}),
        "tail_plan": _copy_jsonish(tail_plan or {}),
        "capture_budget": _copy_jsonish(capture_budget or {}),
        "analysis_config": _copy_jsonish(_resolved_analysis_config(analysis_config)),
    }


def build_online_stream_prior_resolution_artifact(
    *,
    condition: dict | None = None,
    lookup: dict | None = None,
    candidate_prior: dict | None = None,
    applied_prior: dict | None = None,
    fallback_reason: str | None = None,
    warnings: list[str] | None = None,
    schema_version: int = 1,
    phase: str = "online_stream_calibration",
) -> dict:
    return {
        "schema_version": int(schema_version),
        "phase": str(phase),
        "condition": _copy_jsonish(condition or {}),
        "lookup": _copy_jsonish(lookup or {}),
        "candidate_prior": _copy_jsonish(candidate_prior or {}),
        "applied_prior": _copy_jsonish(applied_prior or {}),
        "fallback_reason": None if fallback_reason in (None, "") else str(fallback_reason),
        "warnings": _copy_warnings(warnings),
    }


def summarize_online_stream_flow_delay(frame_rows: list[dict]) -> dict:
    rows = [dict(row or {}) for row in list(frame_rows or [])]
    accepted_rows = [row for row in rows if str(row.get("status") or "") == "accepted"]
    attempted_replicates = int(len(rows))
    accepted_replicates = int(len(accepted_rows))
    rejected_replicates = int(max(0, attempted_replicates - accepted_replicates))
    median_visible_volume_nl = _median_or_none(
        row.get("visible_volume_nl") for row in accepted_rows
    )
    median_width_px = _median_or_none(
        row.get("attached_width_px") for row in accepted_rows
    )
    min_attached_bottom_clearance_px = None
    clearances = [
        _to_float_or_none(row.get("attached_bottom_clearance_px"))
        for row in rows
        if _to_float_or_none(row.get("attached_bottom_clearance_px")) is not None
    ]
    if clearances:
        min_attached_bottom_clearance_px = float(min(clearances))

    warnings = _unique_strings(
        warning
        for row in rows
        for warning in list(row.get("warnings") or [])
    )
    attached_bottom_guard_hit = any(
        str(row.get("status") or "") == "rejected_bottom_guard"
        or bool(row.get("attached_bottom_guard_hit"))
        for row in rows
    )
    detached_near_bottom_warning = any(
        bool(row.get("detached_near_bottom_warning"))
        or ("detached_near_bottom_warning" in list(row.get("warnings") or []))
        for row in rows
    )
    delay_us = None
    delay_from_emergence_us = None
    if rows:
        delay_us = _to_int(rows[0].get("delay_us"), 0)
        delay_from_emergence_us = _to_int(rows[0].get("delay_from_emergence_us"), 0)

    return {
        "delay_us": delay_us,
        "delay_from_emergence_us": delay_from_emergence_us,
        "attempted_replicates": attempted_replicates,
        "accepted_replicates": accepted_replicates,
        "rejected_replicates": rejected_replicates,
        "median_visible_volume_nl": median_visible_volume_nl,
        "median_width_px": median_width_px,
        "min_attached_bottom_clearance_px": min_attached_bottom_clearance_px,
        "detached_near_bottom_warning": bool(detached_near_bottom_warning),
        "delay_accepted": bool(accepted_replicates > 0),
        "attached_bottom_guard_hit": bool(attached_bottom_guard_hit),
        "warnings": warnings,
    }


def decide_online_stream_flow_next_action(
    *,
    delay_summary: dict | None,
    capture_budget: dict | None,
    consecutive_failed_delays: int = 0,
    attempted_delay_count: int,
    planned_delay_count: int,
    accepted_delay_count: int = 0,
    remaining_delay_count: int | None = None,
    min_required_accepted_delays: int = 3,
) -> dict:
    summary = dict(delay_summary or {})
    budget = dict(capture_budget or {})
    if bool(summary.get("attached_bottom_guard_hit")):
        return {
            "action": "stop",
            "termination_reason": "attached_bottom_guard_hit",
        }
    if bool(budget.get("exhausted")):
        return {
            "action": "stop",
            "termination_reason": "capture_budget_exhausted",
        }
    if remaining_delay_count is None:
        remaining_delay_count = max(0, int(planned_delay_count) - int(attempted_delay_count))
    if int(accepted_delay_count) + int(max(0, remaining_delay_count)) < int(
        max(0, min_required_accepted_delays)
    ):
        return {
            "action": "stop",
            "termination_reason": "insufficient_accepted_delays",
        }
    if int(attempted_delay_count) >= int(max(0, planned_delay_count)):
        return {
            "action": "stop",
            "termination_reason": "planned_delays_exhausted",
        }
    return {
        "action": "continue",
        "termination_reason": None,
    }


def build_online_stream_result_stub(
    *,
    condition: dict | None = None,
    priors: dict | None = None,
    flow_phase: dict | None = None,
    tail_phase: dict | None = None,
    predicted_stream_duration_us: int | None = None,
    predicted_volume_nl: float | int | None = None,
    learned_flow_start_offset_us: int | None = None,
    learned_tail_start_offset_us: int | None = None,
    warnings: list[str] | None = None,
) -> dict:
    return {
        "condition": dict(condition or {}),
        "priors": dict(priors or {}),
        "flow_phase": dict(flow_phase or {"status": "not_run"}),
        "tail_phase": dict(tail_phase or {"status": "not_run"}),
        "predicted_stream_duration_us": (
            None if predicted_stream_duration_us is None else int(predicted_stream_duration_us)
        ),
        "predicted_volume_nl": None if predicted_volume_nl is None else float(predicted_volume_nl),
        "learned_flow_start_offset_us": (
            None if learned_flow_start_offset_us is None else int(learned_flow_start_offset_us)
        ),
        "learned_tail_start_offset_us": (
            None if learned_tail_start_offset_us is None else int(learned_tail_start_offset_us)
        ),
        "warnings": _copy_warnings(warnings),
    }


def build_online_stream_flow_fit_artifact(
    *,
    condition: dict | None = None,
    flow_plan: dict | None = None,
    accepted_delay_points: list[dict] | None = None,
    fit: dict | None = None,
    warnings: list[str] | None = None,
    schema_version: int = 1,
    phase: str = "online_stream_calibration",
) -> dict:
    fit_obj = dict(fit or {})
    return {
        "schema_version": int(schema_version),
        "phase": str(phase),
        "condition": _copy_jsonish(condition or {}),
        "flow_plan": _copy_jsonish(flow_plan or {}),
        "accepted_delay_points": _copy_jsonish(
            accepted_delay_points
            if accepted_delay_points is not None
            else fit_obj.get("accepted_delay_points") or []
        ),
        "fit": _copy_jsonish(fit_obj),
        "warnings": _copy_warnings(
            warnings if warnings is not None else fit_obj.get("warnings")
        ),
    }


def build_online_stream_flow_phase_payload(
    *,
    status: str,
    plan: dict | None = None,
    attempted_delay_count: int,
    attempted_capture_count: int,
    accepted_delay_count: int,
    accepted_measurement_count: int,
    rejected_capture_count: int,
    termination_reason: str | None,
    delay_summaries: list[dict] | None = None,
    warnings: list[str] | None = None,
    fit: dict | None = None,
) -> dict:
    fit_obj = dict(fit or {})
    return {
        "status": str(status),
        "plan": _copy_jsonish(plan or {}),
        "attempted_delay_count": int(attempted_delay_count),
        "attempted_capture_count": int(attempted_capture_count),
        "accepted_delay_count": int(accepted_delay_count),
        "accepted_measurement_count": int(accepted_measurement_count),
        "rejected_capture_count": int(rejected_capture_count),
        "termination_reason": str(termination_reason or ""),
        "delay_summaries": _copy_jsonish(delay_summaries or []),
        "warnings": _copy_warnings(warnings),
        "fit_status": str(fit_obj.get("fit_status") or "unresolved_fit_failed"),
        "flow_rate_nl_per_us": _to_float_or_none(fit_obj.get("flow_rate_nl_per_us")),
        "flow_intercept_nl": _to_float_or_none(fit_obj.get("flow_intercept_nl")),
        "flow_fit_delay_start_from_emergence_us": _to_int(
            fit_obj.get("flow_fit_delay_start_from_emergence_us"),
            None,
        ),
        "flow_fit_delay_end_from_emergence_us": _to_int(
            fit_obj.get("flow_fit_delay_end_from_emergence_us"),
            None,
        ),
        "steady_width_baseline_px": _to_float_or_none(fit_obj.get("steady_width_baseline_px")),
        "steady_r2": _to_float_or_none(fit_obj.get("steady_r2")),
        "steady_nrmse": _to_float_or_none(fit_obj.get("steady_nrmse")),
        "steady_rate_ci95_low_nl_per_us": _to_float_or_none(
            fit_obj.get("steady_rate_ci95_low_nl_per_us")
        ),
        "steady_rate_ci95_high_nl_per_us": _to_float_or_none(
            fit_obj.get("steady_rate_ci95_high_nl_per_us")
        ),
        "steady_rate_ci95_relative_width": _to_float_or_none(
            fit_obj.get("steady_rate_ci95_relative_width")
        ),
        "flow_fit_point_count": _to_int(fit_obj.get("flow_fit_point_count"), 0),
        "flow_fit_outlier_prune_status": str(
            fit_obj.get("flow_fit_outlier_prune_status") or "not_attempted"
        ),
        "flow_fit_dropped_outlier_delay_from_emergence_us": _to_int(
            fit_obj.get("flow_fit_dropped_outlier_delay_from_emergence_us"),
            None,
        ),
        "fit_warnings": _copy_warnings(fit_obj.get("warnings")),
    }
