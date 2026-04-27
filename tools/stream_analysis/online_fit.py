import math

import numpy as np
from scipy import stats


DEFAULT_ONLINE_FLOW_FIT_POLICY = {
    "min_accepted_delays": 12,
    "steady_fit_r2_min": 0.98,
    "steady_fit_nrmse_max": 0.05,
    "steady_rate_ci95_relative_width_warn": 0.12,
    "fit_weight_floor": 0.20,
    "late_coverage_min_delay_us": 2250,
    "late_coverage_min_visible_fluid_clearance_px": 300,
    "late_coverage_confidence_min": 0.70,
    "late_slope_window_points": 4,
    "late_slope_max_relative_gap": 0.07,
    "late_slope_residual_trend_max_nl_per_us": 0.00015,
    "min_delays_for_outlier_prune": 4,
    "outlier_local_deviation_floor_nl": 0.75,
    "outlier_improvement_fraction_min": 0.20,
    "settling_aware_fit_enabled": False,
    "settling_aware_early_window_points": 6,
    "settling_aware_late_window_points": 12,
    "settling_aware_early_vs_late_pct_min": 2.0,
    "settling_aware_mid_dev_max": 0.0,
}

_CENTRAL_RATE_TOL = 1e-12


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
    output = []
    for item in list(value or []):
        label = str(item or "").strip()
        if label:
            output.append(label)
    return output


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


def _resolved_quality_policy(policy: dict | None = None) -> dict:
    merged = dict(DEFAULT_ONLINE_FLOW_FIT_POLICY)
    for key, default_value in DEFAULT_ONLINE_FLOW_FIT_POLICY.items():
        if not isinstance(policy, dict) or key not in policy:
            continue
        if isinstance(default_value, bool):
            merged[key] = bool(policy.get(key))
            continue
        if isinstance(default_value, int):
            merged[key] = max(0, _to_int(policy.get(key), default_value))
        else:
            merged[key] = float(policy.get(key))
    return merged


def _median_or_none(values) -> float | None:
    clean = []
    for value in list(values or []):
        parsed = _to_float_or_none(value)
        if parsed is not None:
            clean.append(float(parsed))
    if not clean:
        return None
    return float(np.median(np.asarray(clean, dtype=float)))


def _accepted_delay_points_from_delay_summaries(delay_summaries: list[dict]) -> list[dict]:
    points = []
    for row in list(delay_summaries or []):
        summary = dict(row or {})
        if not bool(summary.get("delay_accepted")):
            continue
        delay_us = _to_int(summary.get("delay_us"))
        delay_from_emergence_us = _to_int(summary.get("delay_from_emergence_us"))
        median_visible_volume_nl = _to_float_or_none(summary.get("median_visible_volume_nl"))
        if (
            delay_us is None
            or delay_from_emergence_us is None
            or median_visible_volume_nl is None
        ):
            continue
        points.append(
            {
                "delay_us": int(delay_us),
                "delay_from_emergence_us": int(delay_from_emergence_us),
                "median_visible_volume_nl": float(median_visible_volume_nl),
                "median_width_px": _to_float_or_none(summary.get("median_width_px")),
                "accepted_replicates": max(0, _to_int(summary.get("accepted_replicates"), 0)),
                "rejected_replicates": max(0, _to_int(summary.get("rejected_replicates"), 0)),
                "min_attached_bottom_clearance_px": _to_float_or_none(
                    summary.get("min_attached_bottom_clearance_px")
                ),
                "min_accepted_fluid_distance_from_bottom_px": _to_float_or_none(
                    summary.get("min_accepted_fluid_distance_from_bottom_px")
                ),
                "detached_near_bottom_warning": bool(summary.get("detached_near_bottom_warning")),
                "flow_geometry_confidence": _to_float_or_none(summary.get("flow_geometry_confidence")),
                "flow_optical_confidence": _to_float_or_none(summary.get("flow_optical_confidence")),
                "flow_point_confidence": _to_float_or_none(summary.get("flow_point_confidence")),
                "lower_edge_jitter_px": _to_float_or_none(summary.get("lower_edge_jitter_px")),
                "boundary_chroma_aberration_score": _to_float_or_none(
                    summary.get("boundary_chroma_aberration_score")
                ),
                "late_coverage_candidate": bool(summary.get("late_coverage_candidate")),
                "late_coverage_metric": None
                if summary.get("late_coverage_metric") in (None, "")
                else str(summary.get("late_coverage_metric")),
            }
        )
    points.sort(key=lambda row: (int(row["delay_from_emergence_us"]), int(row["delay_us"])))
    return points


def _point_fit_weight(point: dict, *, weight_floor: float) -> float:
    confidence = _to_float_or_none(dict(point or {}).get("flow_point_confidence"))
    if confidence is None:
        confidence = 1.0
    return float(max(float(weight_floor), float(confidence) ** 2))


def _weighted_linear_fit(
    x_values: np.ndarray,
    y_values: np.ndarray,
    weights: np.ndarray,
) -> dict | None:
    if x_values.size < 2 or y_values.size < 2 or weights.size < 2:
        return None
    if np.any(~np.isfinite(x_values)) or np.any(~np.isfinite(y_values)) or np.any(~np.isfinite(weights)):
        return None
    if np.any(weights <= 0.0):
        return None

    design = np.column_stack((x_values, np.ones_like(x_values)))
    sqrt_w = np.sqrt(weights)
    weighted_design = design * sqrt_w[:, None]
    weighted_y = y_values * sqrt_w
    try:
        slope, intercept = np.linalg.lstsq(weighted_design, weighted_y, rcond=None)[0]
    except Exception:
        return None
    if not np.isfinite(slope) or not np.isfinite(intercept):
        return None

    predicted = (float(slope) * x_values) + float(intercept)
    residuals = y_values - predicted
    weighted_mean = float(np.average(y_values, weights=weights))
    ss_res = float(np.sum(weights * (residuals**2)))
    ss_tot = float(np.sum(weights * ((y_values - weighted_mean) ** 2)))
    value_span = float(np.max(y_values) - np.min(y_values))
    dof = int(max(0, x_values.size - 2))
    slope_se = None
    if dof > 0:
        try:
            xtwx = design.T @ (weights[:, None] * design)
            cov = (ss_res / float(dof)) * np.linalg.inv(xtwx)
            if np.isfinite(cov[0, 0]) and float(cov[0, 0]) >= 0.0:
                slope_se = float(np.sqrt(cov[0, 0]))
        except Exception:
            slope_se = None
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "predicted": predicted,
        "residuals": residuals,
        "ss_res": float(ss_res),
        "ss_tot": float(ss_tot),
        "value_span": float(value_span),
        "dof": dof,
        "slope_se": slope_se,
    }


def _fit_window_metrics(points: list[dict], *, policy: dict) -> dict | None:
    if len(points) < 2:
        return None

    x_values = np.asarray(
        [float(point["delay_from_emergence_us"]) for point in points],
        dtype=float,
    )
    y_values = np.asarray(
        [float(point["median_visible_volume_nl"]) for point in points],
        dtype=float,
    )
    weights = np.asarray(
        [_point_fit_weight(point, weight_floor=float(policy["fit_weight_floor"])) for point in points],
        dtype=float,
    )
    fit = _weighted_linear_fit(x_values, y_values, weights)
    if fit is None:
        return None
    slope = float(fit["slope"])
    intercept = float(fit["intercept"])
    if float(slope) <= 0.0:
        return None
    predicted = fit["predicted"]
    residuals = fit["residuals"]
    ss_res = float(fit["ss_res"])
    ss_tot = float(fit["ss_tot"])
    if ss_tot <= 0.0:
        return None
    value_span = float(fit["value_span"])
    if value_span <= 0.0:
        return None

    rmse = float(np.sqrt(np.average(residuals**2, weights=weights)))
    nrmse = float(rmse / value_span)
    r2 = float(1.0 - (ss_res / ss_tot))
    third_count = max(1, int(len(residuals)) // 3)
    residual_values = residuals.tolist()
    first_last_residual_delta_nl = float(
        (sum(residual_values[-third_count:]) / float(third_count))
        - (sum(residual_values[:third_count]) / float(third_count))
    )
    max_abs_residual_nl = float(max(abs(float(value)) for value in residual_values))
    residual_trend_nl_per_us = None
    time_mean = float(np.mean(x_values))
    residual_mean = float(np.mean(residuals))
    denominator = float(np.sum((x_values - time_mean) ** 2))
    if denominator > 0.0:
        residual_trend_nl_per_us = float(
            np.sum((x_values - time_mean) * (residuals - residual_mean)) / denominator
        )
    ci_low = None
    ci_high = None
    ci_relative_width = None
    if fit.get("slope_se") is not None and int(fit.get("dof") or 0) > 0:
        try:
            t_crit = float(stats.t.ppf(0.975, int(fit["dof"])))
            ci_low = float(slope - (t_crit * float(fit["slope_se"])))
            ci_high = float(slope + (t_crit * float(fit["slope_se"])))
            if float(slope) != 0.0:
                ci_relative_width = float((ci_high - ci_low) / abs(float(slope)))
        except Exception:
            ci_low = None
            ci_high = None
            ci_relative_width = None
    lag_equivalent_us = None
    if float(slope) > 0.0:
        lag_equivalent_us = float(-float(intercept) / float(slope))

    return {
        "flow_rate_nl_per_us": float(slope),
        "flow_intercept_nl": float(intercept),
        "lag_equivalent_us": lag_equivalent_us,
        "steady_r2": float(r2),
        "steady_nrmse": float(nrmse),
        "steady_fit_first_last_residual_delta_nl": float(first_last_residual_delta_nl),
        "steady_fit_max_abs_residual_nl": float(max_abs_residual_nl),
        "steady_fit_residual_trend_nl_per_us": (
            None if residual_trend_nl_per_us is None else float(residual_trend_nl_per_us)
        ),
        "steady_rate_ci95_low_nl_per_us": ci_low,
        "steady_rate_ci95_high_nl_per_us": ci_high,
        "steady_rate_ci95_relative_width": ci_relative_width,
        "fit_weight_floor": float(policy["fit_weight_floor"]),
    }


def _steady_fit_confidence_from_points(
    points: list[dict],
    *,
    central_rate: float | None,
    policy: dict,
) -> dict:
    if central_rate is None:
        return {
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_missing_central_rate",
        }
    if len(points) < 2:
        return {
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_insufficient_points",
        }

    x_values = np.asarray(
        [float(point["delay_from_emergence_us"]) for point in points],
        dtype=float,
    )
    y_values = np.asarray(
        [float(point["median_visible_volume_nl"]) for point in points],
        dtype=float,
    )
    if np.any(~np.isfinite(x_values)) or np.any(~np.isfinite(y_values)):
        return {
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_missing_time_or_volume",
        }

    weights = np.asarray(
        [_point_fit_weight(point, weight_floor=float(policy["fit_weight_floor"])) for point in points],
        dtype=float,
    )
    fit = _weighted_linear_fit(x_values, y_values, weights)
    if fit is None or fit.get("slope_se") is None or int(fit.get("dof") or 0) <= 0:
        return {
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_weighted_fit_failed",
        }
    try:
        t_crit = float(stats.t.ppf(0.975, int(fit["dof"])))
        rate_low = float(fit["slope"] - (t_crit * float(fit["slope_se"])))
        rate_high = float(fit["slope"] + (t_crit * float(fit["slope_se"])))
    except Exception:
        return {
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_weighted_fit_failed",
        }

    rate_low, rate_high = sorted((float(rate_low), float(rate_high)))
    rate_relative_width = None
    if float(central_rate) != 0.0:
        rate_relative_width = float((float(rate_high) - float(rate_low)) / abs(float(central_rate)))
    contains_central = bool(
        float(rate_low) - float(_CENTRAL_RATE_TOL)
        <= float(central_rate)
        <= float(rate_high) + float(_CENTRAL_RATE_TOL)
    )
    return {
        "steady_rate_ci95_low_nl_per_us": float(rate_low),
        "steady_rate_ci95_high_nl_per_us": float(rate_high),
        "steady_rate_ci95_relative_width": rate_relative_width,
        "steady_rate_ci95_contains_central": bool(contains_central),
        "steady_rate_confidence_status": (
            "ok" if contains_central else "warning_central_rate_mismatch"
        ),
    }


def _late_coverage_summary(points: list[dict], *, policy: dict) -> dict:
    confidence_min = float(policy["late_coverage_confidence_min"])
    delay_threshold = int(policy["late_coverage_min_delay_us"])
    clearance_threshold = float(policy["late_coverage_min_visible_fluid_clearance_px"])
    for point in points:
        confidence = _to_float_or_none(point.get("flow_point_confidence"))
        if confidence is None or float(confidence) < confidence_min:
            continue
        delay_from_emergence_us = _to_int(point.get("delay_from_emergence_us"), None)
        if delay_from_emergence_us is not None and int(delay_from_emergence_us) >= delay_threshold:
            return {
                "late_coverage_reached": True,
                "late_coverage_delay_from_emergence_us": int(delay_from_emergence_us),
                "late_coverage_metric": "delay_threshold",
            }
        clearance_px = _to_float_or_none(point.get("min_accepted_fluid_distance_from_bottom_px"))
        if clearance_px is None:
            clearance_px = _to_float_or_none(point.get("min_attached_bottom_clearance_px"))
        if clearance_px is not None and float(clearance_px) <= clearance_threshold:
            return {
                "late_coverage_reached": True,
                "late_coverage_delay_from_emergence_us": int(delay_from_emergence_us or 0),
                "late_coverage_metric": "visible_fluid_bottom_clearance",
            }
    return {
        "late_coverage_reached": False,
        "late_coverage_delay_from_emergence_us": None,
        "late_coverage_metric": None,
    }


def _late_slope_summary(
    points: list[dict],
    *,
    global_slope: float | None,
    residual_trend_nl_per_us: float | None,
    policy: dict,
) -> dict:
    if global_slope is None or float(global_slope) <= 0.0:
        return {
            "late_slope_nl_per_us": None,
            "late_slope_relative_gap": None,
            "late_slope_stable": False,
        }
    min_confidence = float(policy["late_coverage_confidence_min"])
    window_points = int(max(3, _to_int(policy.get("late_slope_window_points"), 4)))
    high_conf_points = [
        dict(point)
        for point in list(points or [])
        if _to_float_or_none(point.get("flow_point_confidence")) is not None
        and float(point["flow_point_confidence"]) >= min_confidence
    ]
    if len(high_conf_points) < 3:
        return {
            "late_slope_nl_per_us": None,
            "late_slope_relative_gap": None,
            "late_slope_stable": False,
        }
    keep_count = int(min(window_points, len(high_conf_points)))
    late_points = high_conf_points[-keep_count:]
    if len(late_points) < 3:
        late_points = high_conf_points[-3:]
    late_metrics = _fit_window_metrics(late_points, policy=policy)
    if late_metrics is None:
        return {
            "late_slope_nl_per_us": None,
            "late_slope_relative_gap": None,
            "late_slope_stable": False,
        }
    late_slope = _to_float_or_none(late_metrics.get("flow_rate_nl_per_us"))
    relative_gap = None
    if late_slope is not None and float(global_slope) != 0.0:
        relative_gap = float(abs(float(late_slope) - float(global_slope)) / abs(float(global_slope)))
    stable = bool(
        late_slope is not None
        and relative_gap is not None
        and float(relative_gap) <= float(policy["late_slope_max_relative_gap"])
        and (
            residual_trend_nl_per_us is not None
            and abs(float(residual_trend_nl_per_us))
            <= float(policy["late_slope_residual_trend_max_nl_per_us"])
        )
    )
    return {
        "late_slope_nl_per_us": late_slope,
        "late_slope_relative_gap": relative_gap,
        "late_slope_stable": stable,
    }


def _local_interpolation_deviation_candidates(points: list[dict]) -> list[dict]:
    candidates = []
    if len(points) < 3:
        return candidates
    for offset in range(1, len(points) - 1):
        left = dict(points[offset - 1])
        center = dict(points[offset])
        right = dict(points[offset + 1])
        left_x = _to_float_or_none(left.get("delay_from_emergence_us"))
        center_x = _to_float_or_none(center.get("delay_from_emergence_us"))
        right_x = _to_float_or_none(right.get("delay_from_emergence_us"))
        left_y = _to_float_or_none(left.get("median_visible_volume_nl"))
        center_y = _to_float_or_none(center.get("median_visible_volume_nl"))
        right_y = _to_float_or_none(right.get("median_visible_volume_nl"))
        if (
            left_x is None
            or center_x is None
            or right_x is None
            or left_y is None
            or center_y is None
            or right_y is None
            or float(right_x) == float(left_x)
        ):
            continue
        expected_y = float(left_y) + (
            (float(center_x) - float(left_x)) / (float(right_x) - float(left_x))
        ) * (float(right_y) - float(left_y))
        deviation_nl = float(center_y - expected_y)
        candidates.append(
            {
                "offset": int(offset),
                "delay_us": _to_int(center.get("delay_us")),
                "delay_from_emergence_us": _to_int(center.get("delay_from_emergence_us")),
                "local_deviation_nl": float(deviation_nl),
                "abs_local_deviation_nl": float(abs(deviation_nl)),
            }
        )
    return candidates


def _normalized_trace_mid_dev(points: list[dict]) -> float | None:
    if len(points) < 3:
        return None
    x_values = np.asarray(
        [_to_float_or_none(point.get("delay_from_emergence_us")) for point in points],
        dtype=float,
    )
    y_values = np.asarray(
        [_to_float_or_none(point.get("median_visible_volume_nl")) for point in points],
        dtype=float,
    )
    if (
        np.any(~np.isfinite(x_values))
        or np.any(~np.isfinite(y_values))
        or float(x_values[-1]) <= float(x_values[0])
        or float(y_values[-1]) == float(y_values[0])
    ):
        return None
    normalized_x = (x_values - float(x_values[0])) / float(float(x_values[-1]) - float(x_values[0]))
    normalized_y = (y_values - float(y_values[0])) / float(float(y_values[-1]) - float(y_values[0]))
    return float(np.interp(0.5, normalized_x, normalized_y) - 0.5)


def _maybe_apply_settling_aware_late_window(
    accepted_delay_points: list[dict],
    *,
    global_fit_metrics: dict | None,
    policy: dict,
) -> dict:
    late_window_points = int(
        max(
            int(policy["min_accepted_delays"]),
            int(policy["settling_aware_late_window_points"]),
        )
    )
    early_window_points = int(max(2, _to_int(policy.get("settling_aware_early_window_points"), 6)))
    result = {
        "rule_name": "conservative_frontloaded_late12",
        "enabled": bool(policy.get("settling_aware_fit_enabled")),
        "applied": False,
        "fit_points": [dict(point) for point in list(accepted_delay_points or [])],
        "fit_metrics": dict(global_fit_metrics or {}),
        "early_vs_late_pct": None,
        "mid_dev": _normalized_trace_mid_dev(accepted_delay_points),
        "base_flow_rate_nl_per_us": _to_float_or_none(
            None if global_fit_metrics is None else global_fit_metrics.get("flow_rate_nl_per_us")
        ),
        "rate_delta_pct_vs_base": None,
    }
    if not bool(policy.get("settling_aware_fit_enabled")):
        return result
    if len(accepted_delay_points) < int(late_window_points) or len(accepted_delay_points) < int(early_window_points):
        return result

    early_fit_metrics = _fit_window_metrics(
        [dict(point) for point in accepted_delay_points[:early_window_points]],
        policy=policy,
    )
    late_fit_points = [dict(point) for point in accepted_delay_points[-late_window_points:]]
    late_fit_metrics = _fit_window_metrics(late_fit_points, policy=policy)
    if early_fit_metrics is None or late_fit_metrics is None:
        return result

    early_rate = _to_float_or_none(early_fit_metrics.get("flow_rate_nl_per_us"))
    late_rate = _to_float_or_none(late_fit_metrics.get("flow_rate_nl_per_us"))
    if early_rate in (None, 0.0) or late_rate in (None, 0.0):
        return result

    early_vs_late_pct = float((float(early_rate) / float(late_rate) - 1.0) * 100.0)
    result["early_vs_late_pct"] = early_vs_late_pct
    if (
        result["mid_dev"] is None
        or float(early_vs_late_pct) <= float(policy["settling_aware_early_vs_late_pct_min"])
        or float(result["mid_dev"]) >= float(policy["settling_aware_mid_dev_max"])
    ):
        return result

    result["applied"] = True
    result["fit_points"] = late_fit_points
    result["fit_metrics"] = dict(late_fit_metrics or {})
    if (
        result["base_flow_rate_nl_per_us"] not in (None, 0.0)
        and _to_float_or_none(late_fit_metrics.get("flow_rate_nl_per_us")) is not None
    ):
        result["rate_delta_pct_vs_base"] = float(
            (
                float(late_fit_metrics["flow_rate_nl_per_us"])
                / float(result["base_flow_rate_nl_per_us"])
                - 1.0
            )
            * 100.0
        )
    return result


def _maybe_prune_flow_fit_outlier(
    points: list[dict],
    *,
    policy: dict,
) -> dict:
    min_delays_for_prune = int(policy["min_delays_for_outlier_prune"])
    min_accepted_delays = int(policy["min_accepted_delays"])
    if len(points) < int(min_delays_for_prune):
        return {
            "points": list(points),
            "flow_fit_outlier_prune_status": "not_needed_too_few_points",
            "flow_fit_dropped_outlier_delay_us": None,
            "flow_fit_dropped_outlier_delay_from_emergence_us": None,
            "flow_fit_dropped_outlier_local_deviation_nl": None,
        }

    deviation_candidates = _local_interpolation_deviation_candidates(points)
    if not deviation_candidates:
        return {
            "points": list(points),
            "flow_fit_outlier_prune_status": "kept_no_interior_candidates",
            "flow_fit_dropped_outlier_delay_us": None,
            "flow_fit_dropped_outlier_delay_from_emergence_us": None,
            "flow_fit_dropped_outlier_local_deviation_nl": None,
        }

    abs_deviations = np.asarray(
        [candidate["abs_local_deviation_nl"] for candidate in deviation_candidates],
        dtype=float,
    )
    median_abs_deviation = float(np.median(abs_deviations))
    local_deviation_mad = float(np.median(np.abs(abs_deviations - median_abs_deviation)))
    deviation_threshold_nl = float(
        max(float(policy["outlier_local_deviation_floor_nl"]), 4.0 * float(local_deviation_mad))
    )
    sorted_candidates = sorted(
        deviation_candidates,
        key=lambda candidate: float(candidate["abs_local_deviation_nl"]),
        reverse=True,
    )
    primary_candidate = dict(sorted_candidates[0])
    second_largest_abs_deviation_nl = float(
        sorted_candidates[1]["abs_local_deviation_nl"] if len(sorted_candidates) > 1 else 0.0
    )
    if float(primary_candidate["abs_local_deviation_nl"]) <= float(deviation_threshold_nl):
        return {
            "points": list(points),
            "flow_fit_outlier_prune_status": "kept_below_local_deviation_threshold",
            "flow_fit_dropped_outlier_delay_us": None,
            "flow_fit_dropped_outlier_delay_from_emergence_us": None,
            "flow_fit_dropped_outlier_local_deviation_nl": None,
        }
    if (
        float(second_largest_abs_deviation_nl) > 0.0
        and float(primary_candidate["abs_local_deviation_nl"])
        < (1.5 * float(second_largest_abs_deviation_nl))
    ):
        return {
            "points": list(points),
            "flow_fit_outlier_prune_status": "kept_not_unique_enough",
            "flow_fit_dropped_outlier_delay_us": None,
            "flow_fit_dropped_outlier_delay_from_emergence_us": None,
            "flow_fit_dropped_outlier_local_deviation_nl": None,
        }

    pruned_points = [
        dict(point)
        for index, point in enumerate(points)
        if int(index) != int(primary_candidate["offset"])
    ]
    if len(pruned_points) < int(min_accepted_delays):
        return {
            "points": list(points),
            "flow_fit_outlier_prune_status": "kept_prune_would_break_min_points",
            "flow_fit_dropped_outlier_delay_us": None,
            "flow_fit_dropped_outlier_delay_from_emergence_us": None,
            "flow_fit_dropped_outlier_local_deviation_nl": None,
        }

    base_metrics = _fit_window_metrics(points, policy=policy)
    pruned_metrics = _fit_window_metrics(pruned_points, policy=policy)
    if (
        base_metrics is None
        or pruned_metrics is None
        or _to_float_or_none(base_metrics.get("steady_fit_max_abs_residual_nl")) in (None, 0.0)
    ):
        return {
            "points": list(points),
            "flow_fit_outlier_prune_status": "kept_prune_fit_invalid",
            "flow_fit_dropped_outlier_delay_us": None,
            "flow_fit_dropped_outlier_delay_from_emergence_us": None,
            "flow_fit_dropped_outlier_local_deviation_nl": None,
        }

    improvement_fraction = float(
        (
            float(base_metrics["steady_fit_max_abs_residual_nl"])
            - float(pruned_metrics["steady_fit_max_abs_residual_nl"])
        )
        / float(base_metrics["steady_fit_max_abs_residual_nl"])
    )
    if improvement_fraction < float(policy["outlier_improvement_fraction_min"]):
        return {
            "points": list(points),
            "flow_fit_outlier_prune_status": "kept_prune_gain_below_threshold",
            "flow_fit_dropped_outlier_delay_us": None,
            "flow_fit_dropped_outlier_delay_from_emergence_us": None,
            "flow_fit_dropped_outlier_local_deviation_nl": None,
        }

    return {
        "points": pruned_points,
        "flow_fit_outlier_prune_status": "dropped_isolated_point",
        "flow_fit_dropped_outlier_delay_us": _to_int(primary_candidate.get("delay_us")),
        "flow_fit_dropped_outlier_delay_from_emergence_us": _to_int(
            primary_candidate.get("delay_from_emergence_us")
        ),
        "flow_fit_dropped_outlier_local_deviation_nl": float(
            primary_candidate["local_deviation_nl"]
        ),
    }


def fit_online_stream_flow_phase(
    *,
    measurements: list[dict],
    delay_summaries: list[dict],
    quality_policy: dict | None = None,
) -> dict:
    policy = _resolved_quality_policy(quality_policy)
    accepted_measurements = [
        dict(row or {})
        for row in list(measurements or [])
        if bool((row or {}).get("qc_pass"))
    ]
    accepted_delay_points = _accepted_delay_points_from_delay_summaries(delay_summaries)
    steady_width_baseline_px = _median_or_none(
        row.get("width_px") for row in accepted_measurements
    )

    base_result = {
        "fit_status": "unresolved_fit_failed",
        "accepted_delay_point_count": int(len(accepted_delay_points)),
        "accepted_delay_points": [dict(point) for point in accepted_delay_points],
        "flow_fit_point_count": 0,
        "flow_rate_nl_per_us": None,
        "flow_intercept_nl": None,
        "lag_equivalent_us": None,
        "flow_fit_delay_start_from_emergence_us": None,
        "flow_fit_delay_end_from_emergence_us": None,
        "steady_width_baseline_px": steady_width_baseline_px,
        "steady_r2": None,
        "steady_nrmse": None,
        "steady_rate_ci95_low_nl_per_us": None,
        "steady_rate_ci95_high_nl_per_us": None,
        "steady_rate_ci95_relative_width": None,
        "steady_rate_ci95_contains_central": None,
        "steady_rate_confidence_status": "unresolved_no_fit",
        "steady_fit_first_last_residual_delta_nl": None,
        "steady_fit_max_abs_residual_nl": None,
        "steady_fit_residual_trend_nl_per_us": None,
        "late_slope_nl_per_us": None,
        "late_slope_relative_gap": None,
        "late_slope_stable": False,
        "late_coverage_reached": False,
        "late_coverage_delay_from_emergence_us": None,
        "late_coverage_metric": None,
        "fit_weight_floor": float(policy["fit_weight_floor"]),
        "flow_fit_outlier_prune_status": "not_attempted",
        "flow_fit_dropped_outlier_delay_us": None,
        "flow_fit_dropped_outlier_delay_from_emergence_us": None,
        "flow_fit_dropped_outlier_local_deviation_nl": None,
        "settling_aware_fit_enabled": bool(policy["settling_aware_fit_enabled"]),
        "settling_aware_fit_applied": False,
        "settling_aware_fit_rule_name": "conservative_frontloaded_late12",
        "settling_aware_fit_early_vs_late_pct": None,
        "settling_aware_fit_mid_dev": None,
        "settling_aware_fit_rate_delta_pct_vs_base": None,
        "settling_aware_fit_base_flow_rate_nl_per_us": None,
        "warnings": [],
    }

    if len(accepted_delay_points) < int(policy["min_accepted_delays"]):
        return {
            **base_result,
            "fit_status": "unresolved_insufficient_delays",
            "flow_fit_outlier_prune_status": "not_attempted_insufficient_delays",
            "warnings": ["insufficient_accepted_delays"],
        }

    prune_result = _maybe_prune_flow_fit_outlier(
        accepted_delay_points,
        policy=policy,
    )
    global_fit_points = [dict(point) for point in prune_result["points"]]
    global_fit_metrics = _fit_window_metrics(global_fit_points, policy=policy)
    if global_fit_metrics is None:
        warnings = ["flow_fit_failed"]
        if str(prune_result.get("flow_fit_outlier_prune_status")) == "dropped_isolated_point":
            warnings.append("flow_fit_outlier_pruned")
        return {
            **base_result,
            **{
                "flow_fit_outlier_prune_status": str(
                    prune_result.get("flow_fit_outlier_prune_status") or "not_attempted"
                ),
                "flow_fit_dropped_outlier_delay_us": _to_int(
                    prune_result.get("flow_fit_dropped_outlier_delay_us")
                ),
                "flow_fit_dropped_outlier_delay_from_emergence_us": _to_int(
                    prune_result.get("flow_fit_dropped_outlier_delay_from_emergence_us")
                ),
                "flow_fit_dropped_outlier_local_deviation_nl": _to_float_or_none(
                    prune_result.get("flow_fit_dropped_outlier_local_deviation_nl")
                ),
                "warnings": _unique_strings(warnings),
            },
        }

    settling_fit = _maybe_apply_settling_aware_late_window(
        accepted_delay_points,
        global_fit_metrics=global_fit_metrics,
        policy=policy,
    )
    fit_points = [dict(point) for point in global_fit_points]
    fit_metrics = dict(global_fit_metrics or {})
    flow_fit_outlier_prune_status = str(
        prune_result.get("flow_fit_outlier_prune_status") or "not_attempted"
    )
    flow_fit_dropped_outlier_delay_us = _to_int(prune_result.get("flow_fit_dropped_outlier_delay_us"))
    flow_fit_dropped_outlier_delay_from_emergence_us = _to_int(
        prune_result.get("flow_fit_dropped_outlier_delay_from_emergence_us")
    )
    flow_fit_dropped_outlier_local_deviation_nl = _to_float_or_none(
        prune_result.get("flow_fit_dropped_outlier_local_deviation_nl")
    )
    if bool(settling_fit.get("applied")):
        fit_points = [dict(point) for point in settling_fit["fit_points"]]
        fit_metrics = dict(settling_fit["fit_metrics"] or global_fit_metrics or {})
        flow_fit_outlier_prune_status = "skipped_settling_aware_late_window"
        flow_fit_dropped_outlier_delay_us = None
        flow_fit_dropped_outlier_delay_from_emergence_us = None
        flow_fit_dropped_outlier_local_deviation_nl = None

    confidence = _steady_fit_confidence_from_points(
        fit_points,
        central_rate=_to_float_or_none(fit_metrics.get("flow_rate_nl_per_us")),
        policy=policy,
    )
    late_coverage = _late_coverage_summary(fit_points, policy=policy)
    late_slope = _late_slope_summary(
        fit_points,
        global_slope=_to_float_or_none(fit_metrics.get("flow_rate_nl_per_us")),
        residual_trend_nl_per_us=_to_float_or_none(
            fit_metrics.get("steady_fit_residual_trend_nl_per_us")
        ),
        policy=policy,
    )
    warnings = []
    fit_status = "ok"
    if len(fit_points) == int(policy["min_accepted_delays"]):
        fit_status = "warning_min_points_only"
        warnings.append("flow_fit_min_points_only")
    if (
        _to_float_or_none(fit_metrics.get("steady_r2")) is None
        or float(fit_metrics["steady_r2"]) < float(policy["steady_fit_r2_min"])
        or _to_float_or_none(fit_metrics.get("steady_nrmse")) is None
        or float(fit_metrics["steady_nrmse"]) > float(policy["steady_fit_nrmse_max"])
    ):
        fit_status = "warning_quality_thresholds"
        warnings.append("flow_fit_quality_thresholds")
    if (
        _to_float_or_none(confidence.get("steady_rate_ci95_relative_width")) is not None
        and float(confidence["steady_rate_ci95_relative_width"])
        > float(policy["steady_rate_ci95_relative_width_warn"])
    ):
        warnings.append("flow_fit_ci95_wide")
    if str(prune_result.get("flow_fit_outlier_prune_status")) == "dropped_isolated_point":
        warnings.append("flow_fit_outlier_pruned")
    if str(confidence.get("steady_rate_confidence_status") or "") == "warning_central_rate_mismatch":
        warnings.append("flow_fit_ci95_central_rate_mismatch")
    if not bool(late_coverage.get("late_coverage_reached")):
        warnings.append("flow_fit_late_coverage_not_reached")
    if not bool(late_slope.get("late_slope_stable")):
        warnings.append("flow_fit_late_slope_unstable")
    if bool(settling_fit.get("applied")):
        warnings.append("flow_fit_settling_aware_late12_applied")

    return {
        **base_result,
        **fit_metrics,
        **confidence,
        **late_coverage,
        **late_slope,
        "fit_status": str(fit_status),
        "flow_fit_point_count": int(len(fit_points)),
        "flow_fit_delay_start_from_emergence_us": int(fit_points[0]["delay_from_emergence_us"]),
        "flow_fit_delay_end_from_emergence_us": int(fit_points[-1]["delay_from_emergence_us"]),
        "flow_fit_outlier_prune_status": flow_fit_outlier_prune_status,
        "flow_fit_dropped_outlier_delay_us": flow_fit_dropped_outlier_delay_us,
        "flow_fit_dropped_outlier_delay_from_emergence_us": flow_fit_dropped_outlier_delay_from_emergence_us,
        "flow_fit_dropped_outlier_local_deviation_nl": flow_fit_dropped_outlier_local_deviation_nl,
        "settling_aware_fit_enabled": bool(policy["settling_aware_fit_enabled"]),
        "settling_aware_fit_applied": bool(settling_fit.get("applied")),
        "settling_aware_fit_rule_name": str(settling_fit.get("rule_name") or "conservative_frontloaded_late12"),
        "settling_aware_fit_early_vs_late_pct": _to_float_or_none(settling_fit.get("early_vs_late_pct")),
        "settling_aware_fit_mid_dev": _to_float_or_none(settling_fit.get("mid_dev")),
        "settling_aware_fit_rate_delta_pct_vs_base": _to_float_or_none(
            settling_fit.get("rate_delta_pct_vs_base")
        ),
        "settling_aware_fit_base_flow_rate_nl_per_us": _to_float_or_none(
            settling_fit.get("base_flow_rate_nl_per_us")
        ),
        "warnings": _unique_strings(warnings),
    }
