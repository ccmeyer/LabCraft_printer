from __future__ import annotations


DEFAULT_ONLINE_STREAM_POLICY = {
    "flow_start_offset_us": 650,
    "flow_scout_step_us": 100,
    "flow_target_delay_count": 20,
    "flow_min_accepted_delays": 12,
    "flow_max_capture_count": 30,
    "flow_soft_bottom_clearance_px": 150,
    "flow_ci95_relative_width_target": 0.12,
    "flow_late_coverage_min_delay_us": 2250,
    "flow_late_coverage_min_visible_fluid_clearance_px": 300,
    "flow_late_coverage_confidence_min": 0.70,
    "flow_extension_confidence_floor": 0.55,
    "flow_safe_densify_window_us": 600,
    "flow_safe_densify_step_us": 50,
    "flow_tail_preserve_margin_captures": 2,
    "flow_late_slope_window_points": 4,
    "flow_late_slope_max_relative_gap": 0.07,
    "flow_late_slope_residual_trend_max_nl_per_us": 0.00015,
    "reserved_tail_capture_count": 25,
    "flow_ci_extension_step_us": 50,
    "flow_step_us": 57,
    "flow_delay_count": 15,
    "flow_replicates": 1,
    "tail_fallback_start_offset_us": 3600,
    "tail_exact_prior_start_lead_us": 400,
    "tail_coarse_step_us": 100,
    "tail_coarse_replicates": 2,
    "tail_refine_step_us": 50,
    "tail_refine_replicates": 2,
    "nominal_capture_budget": 55,
    "hard_capture_budget": 61,
    "bottom_of_fov_guard_px": 96,
}

DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG = {
    "settling_aware_fit_enabled": True,
    "nozzle_guard_px": 2,
    "min_component_area_px": 120,
    "attached_bottom_guard_px": 96,
    "detached_near_bottom_warning_px": 96,
    "near_nozzle_band_top_px": 24,
    "near_nozzle_band_height_px": 40,
    "min_band_valid_rows": 24,
    "attached_lower_centerline_row_fraction": 0.35,
    "attached_lower_centerline_min_rows": 12,
    "attached_lower_centerline_span_max_px": 50,
    "attached_geometry_confidence_full_span_px": 25,
    "attached_geometry_confidence_zero_span_px": 50,
    "detached_material_volume_min_nl": 0.5,
    "detached_material_volume_fraction_min": 0.25,
    "detached_axis_symmetry_min": 0.80,
    "detached_local_centerline_span_max_px": 20,
    "detached_axis_offset_warn_px": 25,
    "detached_geometry_confidence_full_symmetry": 0.90,
    "detached_geometry_confidence_zero_symmetry": 0.80,
    "detached_geometry_confidence_full_span_px": 10,
    "detached_geometry_confidence_zero_span_px": 20,
    "optical_activation_clearance_px": 400,
    "optical_lower_row_fraction": 0.25,
    "optical_lower_image_band_fraction": 0.25,
    "optical_edge_jitter_confidence_full_px": 0.75,
    "optical_edge_jitter_confidence_zero_px": 2.5,
    "optical_boundary_chroma_confidence_full": 12.0,
    "optical_boundary_chroma_confidence_zero": 32.0,
    "flow_volume_incomplete_material_volume_nl": 0.5,
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
            if isinstance(default_value, float):
                try:
                    merged[key] = float(policy.get(key))
                except Exception:
                    merged[key] = float(default_value)
            else:
                merged[key] = _to_int(policy.get(key), default_value)
    return merged


def _resolved_analysis_config(config: dict | None = None) -> dict:
    merged = dict(DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG)
    for key, default_value in DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG.items():
        if isinstance(config, dict) and key in config:
            if isinstance(default_value, bool):
                merged[key] = bool(config.get(key))
                continue
            if isinstance(default_value, float):
                try:
                    merged[key] = float(config.get(key))
                except Exception:
                    merged[key] = float(default_value)
            else:
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
    start_delay_us = int(emergence_time_us) + int(start_offset_us)
    default_start_offset_us = int(resolved_policy["flow_start_offset_us"])
    plan_source = "prior_adjusted" if int(start_offset_us) != int(default_start_offset_us) else "default"
    return {
        "emergence_time_us": int(emergence_time_us),
        "search_method": "adaptive_visible_span_v1",
        "start_offset_from_emergence_us": int(start_offset_us),
        "start_delay_us": int(start_delay_us),
        "delay_offsets_from_emergence_us": [int(start_offset_us)],
        "delays_us": [int(start_delay_us)],
        "replicates_per_delay": int(resolved_policy["flow_replicates"]),
        "point_count": int(resolved_policy["flow_target_delay_count"]),
        "scout_step_us": int(resolved_policy["flow_scout_step_us"]),
        "target_delay_count": int(resolved_policy["flow_target_delay_count"]),
        "min_accepted_delays": int(resolved_policy["flow_min_accepted_delays"]),
        "max_capture_count": int(resolved_policy["flow_max_capture_count"]),
        "soft_bottom_clearance_px": int(resolved_policy["flow_soft_bottom_clearance_px"]),
        "ci95_relative_width_target": float(resolved_policy["flow_ci95_relative_width_target"]),
        "late_coverage_min_delay_us": int(resolved_policy["flow_late_coverage_min_delay_us"]),
        "late_coverage_min_visible_fluid_clearance_px": int(
            resolved_policy["flow_late_coverage_min_visible_fluid_clearance_px"]
        ),
        "late_coverage_confidence_min": float(
            resolved_policy["flow_late_coverage_confidence_min"]
        ),
        "extension_confidence_floor": float(
            resolved_policy["flow_extension_confidence_floor"]
        ),
        "safe_densify_window_us": int(resolved_policy["flow_safe_densify_window_us"]),
        "safe_densify_step_us": int(resolved_policy["flow_safe_densify_step_us"]),
        "tail_preserve_margin_captures": int(resolved_policy["flow_tail_preserve_margin_captures"]),
        "late_slope_window_points": int(resolved_policy["flow_late_slope_window_points"]),
        "late_slope_max_relative_gap": float(
            resolved_policy["flow_late_slope_max_relative_gap"]
        ),
        "late_slope_residual_trend_max_nl_per_us": float(
            resolved_policy["flow_late_slope_residual_trend_max_nl_per_us"]
        ),
        "reserved_tail_capture_count": int(resolved_policy["reserved_tail_capture_count"]),
        "ci_extension_step_us": int(resolved_policy["flow_ci_extension_step_us"]),
        "legacy_flow_step_us": int(resolved_policy["flow_step_us"]),
        "legacy_flow_delay_count": int(resolved_policy["flow_delay_count"]),
        "plan_source": str(plan_source),
    }


def _sorted_unique_ints(values) -> list[int]:
    unique = []
    seen = set()
    for value in list(values or []):
        parsed = _to_int(value, None)
        if parsed is None:
            continue
        parsed = int(parsed)
        if parsed in seen:
            continue
        seen.add(parsed)
        unique.append(parsed)
    unique.sort()
    return unique


def is_online_stream_flow_hard_boundary(delay_summary: dict | None) -> bool:
    summary = dict(delay_summary or {})
    return bool(summary.get("attached_bottom_guard_hit"))


def is_online_stream_flow_soft_boundary(
    delay_summary: dict | None,
    *,
    policy: dict | None = None,
) -> bool:
    summary = dict(delay_summary or {})
    resolved_policy = _resolved_policy(policy)
    if not bool(summary.get("delay_accepted")):
        return False
    clearance_px = _to_float_or_none(summary.get("min_attached_bottom_clearance_px"))
    if bool(summary.get("detached_near_bottom_warning")):
        return True
    if clearance_px is None:
        return False
    return float(clearance_px) <= float(resolved_policy["flow_soft_bottom_clearance_px"])


def build_online_stream_flow_target_offsets(
    *,
    start_offset_us: int,
    end_offset_us: int,
    target_delay_count: int,
) -> list[int]:
    start_offset_us = int(start_offset_us)
    end_offset_us = int(end_offset_us)
    if end_offset_us < start_offset_us:
        end_offset_us = int(start_offset_us)
    target_delay_count = max(1, int(target_delay_count))
    max_unique_count = int(max(1, (end_offset_us - start_offset_us) + 1))
    if max_unique_count <= 1 or target_delay_count <= 1:
        return [int(start_offset_us)]
    if max_unique_count < target_delay_count:
        return [int(start_offset_us + idx) for idx in range(max_unique_count)]

    span = float(end_offset_us - start_offset_us)
    raw_offsets = [
        int(round(float(start_offset_us) + (span * float(idx) / float(target_delay_count - 1))))
        for idx in range(target_delay_count)
    ]
    offsets = []
    for idx, raw_offset_us in enumerate(raw_offsets):
        min_allowed = int(start_offset_us if idx == 0 else offsets[-1] + 1)
        remaining = int(target_delay_count - idx - 1)
        max_allowed = int(end_offset_us - remaining)
        offsets.append(int(max(min_allowed, min(int(raw_offset_us), max_allowed))))
    return offsets


def build_online_stream_flow_missing_offsets(
    *,
    target_offsets_from_emergence_us: list[int] | None,
    existing_offsets_from_emergence_us: list[int] | None,
) -> list[int]:
    target_offsets = _sorted_unique_ints(target_offsets_from_emergence_us)
    existing_offsets = set(_sorted_unique_ints(existing_offsets_from_emergence_us))
    return [int(offset_us) for offset_us in target_offsets if int(offset_us) not in existing_offsets]


def select_online_stream_flow_gap_midpoint(
    *,
    sampled_offsets_from_emergence_us: list[int] | None,
    start_offset_us: int,
    end_offset_us: int,
) -> int | None:
    start_offset_us = int(start_offset_us)
    end_offset_us = int(end_offset_us)
    if end_offset_us <= start_offset_us:
        return None

    sampled_offsets = _sorted_unique_ints(sampled_offsets_from_emergence_us)
    safe_offsets = [int(offset_us) for offset_us in sampled_offsets if start_offset_us <= int(offset_us) <= end_offset_us]
    if start_offset_us not in safe_offsets:
        safe_offsets.insert(0, int(start_offset_us))
    if end_offset_us not in safe_offsets:
        safe_offsets.append(int(end_offset_us))
    safe_offsets = _sorted_unique_ints(safe_offsets)

    best_gap = None
    best_midpoint = None
    sampled_set = set(_sorted_unique_ints(sampled_offsets_from_emergence_us))
    for left_offset_us, right_offset_us in zip(safe_offsets, safe_offsets[1:]):
        gap = int(right_offset_us - left_offset_us)
        if gap <= 1:
            continue
        midpoint = int((int(left_offset_us) + int(right_offset_us)) // 2)
        if midpoint in sampled_set:
            if int(midpoint - left_offset_us) > int(right_offset_us - midpoint):
                midpoint = int(midpoint - 1)
            else:
                midpoint = int(midpoint + 1)
        if midpoint in sampled_set or midpoint <= left_offset_us or midpoint >= right_offset_us:
            continue
        if best_gap is None or int(gap) > int(best_gap) or (
            int(gap) == int(best_gap) and int(midpoint) < int(best_midpoint)
        ):
            best_gap = int(gap)
            best_midpoint = int(midpoint)
    return None if best_midpoint is None else int(best_midpoint)


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
    min_accepted_fluid_distance_from_bottom_px: float | int | None = None,
    flow_geometry_confidence: float | int | None = None,
    flow_optical_confidence: float | int | None = None,
    flow_point_confidence: float | int | None = None,
    flow_optical_confidence_active: bool | None = None,
    optical_activation_clearance_px: float | int | None = None,
    lower_edge_jitter_px: float | int | None = None,
    boundary_chroma_aberration_score: float | int | None = None,
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
        "min_accepted_fluid_distance_from_bottom_px": (
            None
            if min_accepted_fluid_distance_from_bottom_px is None
            else float(min_accepted_fluid_distance_from_bottom_px)
        ),
        "flow_geometry_confidence": (
            None if flow_geometry_confidence is None else float(flow_geometry_confidence)
        ),
        "flow_optical_confidence": (
            None if flow_optical_confidence is None else float(flow_optical_confidence)
        ),
        "flow_point_confidence": (
            None if flow_point_confidence is None else float(flow_point_confidence)
        ),
        "flow_optical_confidence_active": (
            None if flow_optical_confidence_active is None else bool(flow_optical_confidence_active)
        ),
        "optical_activation_clearance_px": (
            None
            if optical_activation_clearance_px is None
            else float(optical_activation_clearance_px)
        ),
        "lower_edge_jitter_px": (
            None if lower_edge_jitter_px is None else float(lower_edge_jitter_px)
        ),
        "boundary_chroma_aberration_score": (
            None
            if boundary_chroma_aberration_score is None
            else float(boundary_chroma_aberration_score)
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
    accepted_rows = []
    geometry_rejected_replicates = 0
    geometry_boundary_triggered = False
    geometry_reasons = []
    volume_incomplete_rejected_replicates = 0
    flow_volume_completeness_reasons = []
    for row in rows:
        status = str(row.get("status") or "")
        if status != "accepted":
            continue
        flow_measurement_usable = row.get("flow_measurement_usable")
        if flow_measurement_usable is None:
            flow_measurement_usable = (
                bool(row.get("qc", {}).get("measurement_qc_pass"))
                and row.get("flow_volume_geometry_ok") is not False
            )
        if bool(flow_measurement_usable):
            accepted_rows.append(row)
            continue
        if row.get("flow_volume_geometry_ok") is False:
            geometry_rejected_replicates += 1
            geometry_boundary_triggered = True
            geometry_reasons.extend(list(row.get("flow_volume_geometry_reasons") or []))
        if row.get("flow_volume_complete_ok") is False:
            volume_incomplete_rejected_replicates += 1
            flow_volume_completeness_reasons.extend(
                list(row.get("flow_volume_completeness_reasons") or [])
            )
    attempted_replicates = int(len(rows))
    accepted_replicates = int(len(accepted_rows))
    rejected_replicates = int(max(0, attempted_replicates - accepted_replicates))
    median_visible_volume_nl = _median_or_none(
        row.get("visible_volume_nl") for row in accepted_rows
    )
    median_width_px = _median_or_none(
        row.get("attached_width_px") for row in accepted_rows
    )
    median_flow_geometry_confidence = _median_or_none(
        row.get("flow_geometry_confidence") for row in accepted_rows
    )
    median_flow_optical_confidence = _median_or_none(
        row.get("flow_optical_confidence") for row in accepted_rows
    )
    median_flow_point_confidence = _median_or_none(
        row.get("flow_point_confidence") for row in accepted_rows
    )
    flow_optical_confidence_active = any(
        bool(row.get("flow_optical_confidence_active")) for row in accepted_rows
    )
    optical_activation_clearance_px = _median_or_none(
        row.get("optical_activation_clearance_px") for row in accepted_rows
    )
    median_lower_edge_jitter_px = _median_or_none(
        row.get("lower_edge_jitter_px") for row in accepted_rows
    )
    median_boundary_chroma_aberration_score = _median_or_none(
        row.get("boundary_chroma_aberration_score") for row in accepted_rows
    )
    max_plausible_unaccepted_component_count = max(
        (
            int(_to_int(row.get("plausible_unaccepted_component_count"), 0))
            for row in rows
            if _to_int(row.get("plausible_unaccepted_component_count"), None) is not None
        ),
        default=None,
    )
    plausible_unaccepted_visible_volume_nl = None
    plausible_unaccepted_volumes = [
        _to_float_or_none(row.get("plausible_unaccepted_visible_volume_nl"))
        for row in rows
        if _to_float_or_none(row.get("plausible_unaccepted_visible_volume_nl")) is not None
    ]
    if plausible_unaccepted_volumes:
        plausible_unaccepted_visible_volume_nl = float(max(plausible_unaccepted_volumes))
    min_attached_bottom_clearance_px = None
    clearances = [
        _to_float_or_none(row.get("attached_bottom_clearance_px"))
        for row in rows
        if _to_float_or_none(row.get("attached_bottom_clearance_px")) is not None
    ]
    if clearances:
        min_attached_bottom_clearance_px = float(min(clearances))
    accepted_fluid_clearances = [
        _to_float_or_none(row.get("min_accepted_fluid_distance_from_bottom_px"))
        for row in accepted_rows
        if _to_float_or_none(row.get("min_accepted_fluid_distance_from_bottom_px")) is not None
    ]
    min_accepted_fluid_distance_from_bottom_px = None
    if accepted_fluid_clearances:
        min_accepted_fluid_distance_from_bottom_px = float(min(accepted_fluid_clearances))

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

    summary = {
        "delay_us": delay_us,
        "delay_from_emergence_us": delay_from_emergence_us,
        "attempted_replicates": attempted_replicates,
        "accepted_replicates": accepted_replicates,
        "rejected_replicates": rejected_replicates,
        "median_visible_volume_nl": median_visible_volume_nl,
        "median_width_px": median_width_px,
        "min_attached_bottom_clearance_px": min_attached_bottom_clearance_px,
        "min_accepted_fluid_distance_from_bottom_px": min_accepted_fluid_distance_from_bottom_px,
        "flow_geometry_confidence": median_flow_geometry_confidence,
        "flow_optical_confidence": median_flow_optical_confidence,
        "flow_point_confidence": median_flow_point_confidence,
        "flow_optical_confidence_active": bool(flow_optical_confidence_active),
        "optical_activation_clearance_px": optical_activation_clearance_px,
        "lower_edge_jitter_px": median_lower_edge_jitter_px,
        "boundary_chroma_aberration_score": median_boundary_chroma_aberration_score,
        "detached_near_bottom_warning": bool(detached_near_bottom_warning),
        "delay_accepted": bool(accepted_replicates > 0),
        "attached_bottom_guard_hit": bool(attached_bottom_guard_hit),
        "geometry_rejected_replicates": int(geometry_rejected_replicates),
        "volume_incomplete_rejected_replicates": int(volume_incomplete_rejected_replicates),
        "geometry_boundary_triggered": bool(geometry_boundary_triggered),
        "flow_volume_geometry_ok": (
            False
            if geometry_boundary_triggered
            else (True if accepted_replicates > 0 else None)
        ),
        "flow_volume_geometry_reasons": _unique_strings(geometry_reasons),
        "flow_volume_complete_ok": (
            False
            if volume_incomplete_rejected_replicates > 0
            else (True if accepted_replicates > 0 else None)
        ),
        "flow_volume_completeness_reasons": _unique_strings(flow_volume_completeness_reasons),
        "plausible_unaccepted_component_count": max_plausible_unaccepted_component_count,
        "plausible_unaccepted_visible_volume_nl": plausible_unaccepted_visible_volume_nl,
        "warnings": warnings,
    }
    late_coverage_candidate, late_coverage_metric = is_online_stream_flow_late_coverage_candidate(
        summary
    )
    summary["late_coverage_candidate"] = bool(late_coverage_candidate)
    summary["late_coverage_metric"] = late_coverage_metric
    return summary


def is_online_stream_flow_late_coverage_candidate(
    delay_summary: dict | None,
    *,
    policy: dict | None = None,
) -> tuple[bool, str | None]:
    summary = dict(delay_summary or {})
    resolved_policy = _resolved_policy(policy)
    if not bool(summary.get("delay_accepted")):
        return False, None
    confidence = _to_float_or_none(summary.get("flow_point_confidence"))
    if (
        confidence is None
        or float(confidence) < float(resolved_policy["flow_late_coverage_confidence_min"])
    ):
        return False, None
    delay_from_emergence_us = _to_int(summary.get("delay_from_emergence_us"), None)
    if (
        delay_from_emergence_us is not None
        and int(delay_from_emergence_us) >= int(resolved_policy["flow_late_coverage_min_delay_us"])
    ):
        return True, "delay_threshold"
    visible_fluid_clearance_px = _to_float_or_none(
        summary.get("min_accepted_fluid_distance_from_bottom_px")
    )
    if visible_fluid_clearance_px is None:
        visible_fluid_clearance_px = _to_float_or_none(summary.get("min_attached_bottom_clearance_px"))
    if (
        visible_fluid_clearance_px is not None
        and float(visible_fluid_clearance_px)
        <= float(resolved_policy["flow_late_coverage_min_visible_fluid_clearance_px"])
    ):
        return True, "visible_fluid_bottom_clearance"
    return False, None


def is_online_stream_flow_geometry_boundary(delay_summary: dict | None) -> bool:
    summary = dict(delay_summary or {})
    if bool(summary.get("geometry_boundary_triggered")):
        return True
    return summary.get("flow_volume_geometry_ok") is False


def decide_online_stream_flow_next_action(
    *,
    delay_summary: dict | None,
    capture_budget: dict | None,
    consecutive_failed_delays: int = 0,
    attempted_delay_count: int,
    planned_delay_count: int,
    accepted_delay_count: int = 0,
    remaining_delay_count: int | None = None,
    min_required_accepted_delays: int = 12,
) -> dict:
    summary = dict(delay_summary or {})
    budget = dict(capture_budget or {})
    if bool(budget.get("exhausted")):
        return {
            "action": "stop",
            "termination_reason": "hard_budget_exhausted",
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
    delay_summaries: list[dict] | None = None,
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
        "delay_summaries": _copy_jsonish(delay_summaries or []),
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
    flow_mode: str | None = None,
    scout_boundary_reason: str | None = None,
    right_boundary_delay_from_emergence_us: int | None = None,
    captured_delay_offsets_from_emergence_us: list[int] | None = None,
    target_delay_offsets_from_emergence_us: list[int] | None = None,
    ci_refinement_count: int = 0,
    fit_stop_reason: str | None = None,
    confidence_boundary_delay_from_emergence_us: int | None = None,
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
        "flow_mode": None if flow_mode in (None, "") else str(flow_mode),
        "scout_boundary_reason": None if scout_boundary_reason in (None, "") else str(scout_boundary_reason),
        "right_boundary_delay_from_emergence_us": _to_int(
            right_boundary_delay_from_emergence_us,
            None,
        ),
        "captured_delay_offsets_from_emergence_us": _copy_jsonish(
            _sorted_unique_ints(captured_delay_offsets_from_emergence_us)
        ),
        "target_delay_offsets_from_emergence_us": _copy_jsonish(
            _sorted_unique_ints(target_delay_offsets_from_emergence_us)
        ),
        "ci_refinement_count": int(max(0, _to_int(ci_refinement_count, 0))),
        "fit_stop_reason": None if fit_stop_reason in (None, "") else str(fit_stop_reason),
        "confidence_boundary_delay_from_emergence_us": _to_int(
            confidence_boundary_delay_from_emergence_us,
            None,
        ),
        "fit_status": str(fit_obj.get("fit_status") or "unresolved_fit_failed"),
        "flow_rate_nl_per_us": _to_float_or_none(fit_obj.get("flow_rate_nl_per_us")),
        "flow_intercept_nl": _to_float_or_none(fit_obj.get("flow_intercept_nl")),
        "lag_equivalent_us": _to_float_or_none(fit_obj.get("lag_equivalent_us")),
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
        "late_slope_nl_per_us": _to_float_or_none(fit_obj.get("late_slope_nl_per_us")),
        "late_slope_relative_gap": _to_float_or_none(fit_obj.get("late_slope_relative_gap")),
        "late_slope_stable": (
            None if fit_obj.get("late_slope_stable") is None else bool(fit_obj.get("late_slope_stable"))
        ),
        "late_coverage_reached": (
            None
            if fit_obj.get("late_coverage_reached") is None
            else bool(fit_obj.get("late_coverage_reached"))
        ),
        "late_coverage_delay_from_emergence_us": _to_int(
            fit_obj.get("late_coverage_delay_from_emergence_us"),
            None,
        ),
        "late_coverage_metric": None
        if fit_obj.get("late_coverage_metric") in (None, "")
        else str(fit_obj.get("late_coverage_metric")),
        "fit_weight_floor": _to_float_or_none(fit_obj.get("fit_weight_floor")),
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
