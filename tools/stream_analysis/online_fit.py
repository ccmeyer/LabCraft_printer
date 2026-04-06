import math

import numpy as np
from scipy import stats


DEFAULT_ONLINE_FLOW_FIT_POLICY = {
    "min_accepted_delays": 3,
    "steady_fit_r2_min": 0.98,
    "steady_fit_nrmse_max": 0.05,
    "steady_rate_ci95_relative_width_warn": 0.12,
    "min_delays_for_outlier_prune": 4,
    "outlier_local_deviation_floor_nl": 0.75,
    "outlier_improvement_fraction_min": 0.20,
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
                "detached_near_bottom_warning": bool(summary.get("detached_near_bottom_warning")),
            }
        )
    points.sort(key=lambda row: (int(row["delay_from_emergence_us"]), int(row["delay_us"])))
    return points


def _fit_window_metrics(points: list[dict]) -> dict | None:
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
    if np.any(~np.isfinite(x_values)) or np.any(~np.isfinite(y_values)):
        return None

    try:
        slope, intercept, _lower, _upper = stats.theilslopes(y_values, x_values)
    except Exception:
        return None

    if not np.isfinite(slope) or not np.isfinite(intercept) or float(slope) <= 0.0:
        return None

    predicted = (float(slope) * x_values) + float(intercept)
    residuals = y_values - predicted
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y_values - np.mean(y_values)) ** 2))
    if ss_tot <= 0.0:
        return None

    value_span = float(np.max(y_values) - np.min(y_values))
    if value_span <= 0.0:
        return None

    rmse = float(np.sqrt(np.mean(residuals**2)))
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

    return {
        "flow_rate_nl_per_us": float(slope),
        "flow_intercept_nl": float(intercept),
        "steady_r2": float(r2),
        "steady_nrmse": float(nrmse),
        "steady_fit_first_last_residual_delta_nl": float(first_last_residual_delta_nl),
        "steady_fit_max_abs_residual_nl": float(max_abs_residual_nl),
        "steady_fit_residual_trend_nl_per_us": (
            None if residual_trend_nl_per_us is None else float(residual_trend_nl_per_us)
        ),
    }


def _steady_fit_confidence_from_points(points: list[dict], *, central_rate: float | None) -> dict:
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

    try:
        _slope, _intercept, lower_slope, upper_slope = stats.theilslopes(
            y_values,
            x_values,
            alpha=0.95,
        )
    except Exception:
        return {
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_theilsen_failed",
        }

    rate_low = _to_float_or_none(lower_slope)
    rate_high = _to_float_or_none(upper_slope)
    if rate_low is None or rate_high is None:
        return {
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_theilsen_failed",
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

    base_metrics = _fit_window_metrics(points)
    pruned_metrics = _fit_window_metrics(pruned_points)
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
        "flow_fit_outlier_prune_status": "not_attempted",
        "flow_fit_dropped_outlier_delay_us": None,
        "flow_fit_dropped_outlier_delay_from_emergence_us": None,
        "flow_fit_dropped_outlier_local_deviation_nl": None,
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
    fit_points = [dict(point) for point in prune_result["points"]]
    fit_metrics = _fit_window_metrics(fit_points)
    if fit_metrics is None:
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

    confidence = _steady_fit_confidence_from_points(
        fit_points,
        central_rate=_to_float_or_none(fit_metrics.get("flow_rate_nl_per_us")),
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

    return {
        **base_result,
        **fit_metrics,
        **confidence,
        "fit_status": str(fit_status),
        "flow_fit_point_count": int(len(fit_points)),
        "flow_fit_delay_start_from_emergence_us": int(fit_points[0]["delay_from_emergence_us"]),
        "flow_fit_delay_end_from_emergence_us": int(fit_points[-1]["delay_from_emergence_us"]),
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
    }
