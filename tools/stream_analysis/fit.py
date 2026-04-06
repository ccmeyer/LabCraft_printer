from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from scipy import stats

from tools.stream_analysis.dataset import (
    _clean_text,
    _int_or_none,
    _preferred_columns,
    _write_csv,
    _write_json,
    build_stage0_inventory,
    default_output_root,
)
from tools.stream_analysis import fov as fov_mod
from tools.stream_analysis import volume as volume_mod


FIT_STAGE_DIRNAME = "stage_05_fit"
TAIL_PRELIM_BACKTRACK_PLATEAU_TOL_PX = 0.5
TAIL_DIRECT_FINAL_DROP_PX = 1.5
TAIL_SHOULDER_MIN_FRAMES = 5
TAIL_SHOULDER_MAX_SPAN_PX = 1.0
TAIL_SHOULDER_EXIT_DROP_PX = 1.5
TAIL_SHOULDER_EXIT_LOOKAHEAD_FRAMES = 2
STEADY_RATE_CI_CONTAINS_CENTRAL_TOL = 1e-12
TAIL_START_MODE_LEGACY = "legacy"
TAIL_START_MODE_DESCRIPTOR_SCORE = "descriptor-score"
TAIL_START_MODE_DESCRIPTOR_UNIFIED = "descriptor-unified"
TAIL_START_REFINEMENT_LEGACY = "legacy"
TAIL_START_REFINEMENT_DESCRIPTOR_SCORE = "descriptor_score"
TAIL_START_REFINEMENT_DESCRIPTOR_UNIFIED = "descriptor_unified"
TAIL_DIRECT_TARGET_DROP_TO_THRESHOLD_FRAC = 0.171
TAIL_DIRECT_TARGET_PEAK_LEAD_US = 223.0
TAIL_DIRECT_TARGET_SHRINK_RATE_RATIO = 0.117
TAIL_SHOULDER_TARGET_DROP_TO_THRESHOLD_FRAC = 0.195
TAIL_SHOULDER_TARGET_PEAK_LEAD_US = 244.0
TAIL_SHOULDER_TARGET_SHRINK_RATE_RATIO = 0.107
TAIL_UNIFIED_BAND_DROP_MIN = 0.15
TAIL_UNIFIED_BAND_DROP_MAX = 0.35
TAIL_UNIFIED_BAND_PEAK_LEAD_MIN_US = 180.0
TAIL_UNIFIED_BAND_PEAK_LEAD_MAX_US = 320.0
TAIL_UNIFIED_BAND_SHRINK_RATE_RATIO_MIN = 0.05
TAIL_UNIFIED_BAND_SHRINK_RATE_RATIO_MAX = 0.18
TAIL_UNIFIED_TARGET_DROP_TO_THRESHOLD_FRAC = 0.19
TAIL_UNIFIED_TARGET_PEAK_LEAD_US = 230.0
TAIL_UNIFIED_TARGET_SHRINK_RATE_RATIO = 0.11
TAIL_SCORE_DROP_WEIGHT = 3.0
TAIL_SCORE_PEAK_LEAD_WEIGHT = 1.5
TAIL_SCORE_SHRINK_RATE_WEIGHT = 1.0
TAIL_SCORE_DROP_SCALE = 0.08
TAIL_SCORE_PEAK_LEAD_SCALE_US = 60.0
TAIL_SCORE_SHRINK_RATE_SCALE = 0.04
VOLUME_UNCERTAINTY_SAMPLE_COUNT = 10000
VOLUME_UNCERTAINTY_SEED = 0
TAIL_UNCERTAINTY_SCORE_TOLERANCE = 1.0

PHASE_FEATURE_COLUMNS = list(volume_mod.FRAME_METRIC_COLUMNS) + [
    "attached_near_nozzle_width_median_px",
    "attached_near_nozzle_width_iqr_px",
    "attached_near_nozzle_band_valid_row_count",
    "attached_near_nozzle_band_y0_px",
    "attached_near_nozzle_band_y1_px",
    "attached_near_nozzle_width_smoothed_px",
    "phase_label",
    "steady_candidate",
    "steady_selected",
    "tail_drop_candidate",
    "tail_confirmation_frame",
    "tail_shoulder_end_frame",
    "tail_start_frame",
]
PHASE_DERIVED_COLUMNS = {
    "attached_near_nozzle_width_smoothed_px",
    "phase_label",
    "steady_candidate",
    "steady_selected",
    "tail_drop_candidate",
    "tail_confirmation_frame",
    "tail_shoulder_end_frame",
    "tail_start_frame",
}
PHASE_INPUT_COLUMNS = [
    column for column in PHASE_FEATURE_COLUMNS if column not in PHASE_DERIVED_COLUMNS
]
TAIL_START_CANDIDATE_COLUMNS = [
    "candidate_window_kind",
    "position",
    "capture_index",
    "delay_from_emergence_us",
    "width_px",
    "drop_frac",
    "drop_to_threshold_frac",
    "shrink_rate_norm_per_ms",
    "shrink_rate_ratio",
    "tail_peak_lead_us",
    "within_drop_band",
    "within_peak_lead_band",
    "within_shrink_rate_band",
    "within_unified_band",
    "score_drop_term",
    "score_peak_lead_term",
    "score_shrink_rate_term",
    "score_total",
    "selection_reason",
    "is_selected",
    "is_legacy_anchor",
]


def _capture_key(row: dict):
    return volume_mod._capture_key(row)


def _time_axis_value(row: dict, *, allow_flash_fallback: bool):
    delay_from_emergence_us = _int_or_none(row.get("delay_from_emergence_us"))
    if delay_from_emergence_us is not None:
        return int(delay_from_emergence_us)
    if allow_flash_fallback:
        flash_delay_us = _int_or_none(row.get("flash_delay_us"))
        if flash_delay_us is not None:
            return int(flash_delay_us)
    return None


def _row_by_capture_index(rows: list[dict], capture_index: int | None):
    if capture_index is None:
        return None
    return next(
        (row for row in rows if _int_or_none(row.get("capture_index")) == int(capture_index)),
        None,
    )


def _float_or_none(value):
    try:
        if value in (None, ""):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        return number
    except Exception:
        return None


def _near_nozzle_width_metrics(
    frame_row: dict,
    attached_edge_rows: list[dict],
    *,
    near_nozzle_band_top_px: int,
    near_nozzle_band_height_px: int,
    min_band_valid_rows: int,
):
    tracked_nozzle_y_px = frame_row.get("tracked_nozzle_y_px")
    if tracked_nozzle_y_px is None:
        return {
            "attached_near_nozzle_width_median_px": None,
            "attached_near_nozzle_width_iqr_px": None,
            "attached_near_nozzle_band_valid_row_count": 0,
            "attached_near_nozzle_band_y0_px": None,
            "attached_near_nozzle_band_y1_px": None,
        }

    band_y0_px = int(math.floor(float(tracked_nozzle_y_px) + float(near_nozzle_band_top_px)))
    band_y1_px = int(band_y0_px + int(near_nozzle_band_height_px))
    band_widths = [
        int(row["width_px"])
        for row in attached_edge_rows
        if band_y0_px <= int(row["y_px"]) < band_y1_px
    ]
    band_row_count = int(len(band_widths))
    if band_row_count < int(min_band_valid_rows):
        return {
            "attached_near_nozzle_width_median_px": None,
            "attached_near_nozzle_width_iqr_px": None,
            "attached_near_nozzle_band_valid_row_count": band_row_count,
            "attached_near_nozzle_band_y0_px": band_y0_px,
            "attached_near_nozzle_band_y1_px": band_y1_px,
        }

    q1_px, q3_px = np.percentile(np.asarray(band_widths, dtype=float), [25.0, 75.0])
    return {
        "attached_near_nozzle_width_median_px": float(np.median(np.asarray(band_widths, dtype=float))),
        "attached_near_nozzle_width_iqr_px": float(q3_px - q1_px),
        "attached_near_nozzle_band_valid_row_count": band_row_count,
        "attached_near_nozzle_band_y0_px": band_y0_px,
        "attached_near_nozzle_band_y1_px": band_y1_px,
    }


def _centered_valid_rolling_median(values: list[float | None], window: int):
    if int(window) <= 1:
        return [None if value is None else float(value) for value in values]

    valid_positions = [index for index, value in enumerate(values) if value is not None]
    smoothed = [None for _ in values]
    if not valid_positions:
        return smoothed

    half_window = max(0, int(window) // 2)
    valid_values = [float(values[index]) for index in valid_positions]
    for position_index, frame_index in enumerate(valid_positions):
        left = max(0, position_index - half_window)
        right = min(len(valid_positions), position_index + half_window + 1)
        neighborhood = valid_values[left:right]
        smoothed[frame_index] = float(np.median(np.asarray(neighborhood, dtype=float)))
    return smoothed


def _build_phase_feature_rows(
    stage4_run: dict,
    *,
    near_nozzle_band_top_px: int,
    near_nozzle_band_height_px: int,
    min_band_valid_rows: int,
    width_smooth_window: int,
):
    attached_edge_rows_by_capture = {}
    for edge_row in stage4_run["edge_rows"]:
        if _clean_text(edge_row.get("component_id")) != "attached_primary":
            continue
        attached_edge_rows_by_capture.setdefault(_capture_key(edge_row), []).append(edge_row)

    feature_rows = []
    for frame_row in stage4_run["frame_metric_rows"]:
        attached_edge_rows = attached_edge_rows_by_capture.get(_capture_key(frame_row), [])
        width_metrics = _near_nozzle_width_metrics(
            frame_row,
            attached_edge_rows,
            near_nozzle_band_top_px=int(near_nozzle_band_top_px),
            near_nozzle_band_height_px=int(near_nozzle_band_height_px),
            min_band_valid_rows=int(min_band_valid_rows),
        )
        width_valid = width_metrics["attached_near_nozzle_width_median_px"] is not None
        steady_candidate = bool(
            _clean_text(frame_row.get("volume_trust_label")) == fov_mod.TRUST_LABEL_TRUSTED
            and frame_row.get("total_visible_volume_nl") is not None
            and width_valid
            and _time_axis_value(frame_row, allow_flash_fallback=False) is not None
        )
        feature_rows.append(
            {
                **dict(frame_row),
                **width_metrics,
                "attached_near_nozzle_width_smoothed_px": None,
                "phase_label": "width_unavailable" if not width_valid else "head_or_transition",
                "steady_candidate": bool(steady_candidate),
                "steady_selected": False,
                "tail_drop_candidate": False,
                "tail_confirmation_frame": False,
                "tail_shoulder_end_frame": False,
                "tail_start_frame": False,
            }
        )

    smoothed_widths = _centered_valid_rolling_median(
        [row.get("attached_near_nozzle_width_median_px") for row in feature_rows],
        int(width_smooth_window),
    )
    for row, smoothed_width in zip(feature_rows, smoothed_widths):
        row["attached_near_nozzle_width_smoothed_px"] = smoothed_width
    return feature_rows


def _phase_input_rows_from_feature_rows(feature_rows: list[dict]):
    return [
        {column: row.get(column) for column in PHASE_INPUT_COLUMNS}
        for row in feature_rows
    ]


def _feature_rows_from_phase_input_rows(
    phase_input_rows: list[dict],
    *,
    width_smooth_window: int,
):
    feature_rows = []
    for phase_input_row in phase_input_rows:
        row = {
            key: (None if value == "" else value)
            for key, value in dict(phase_input_row).items()
        }
        width_valid = row.get("attached_near_nozzle_width_median_px") not in (None, "")
        steady_candidate = bool(
            _clean_text(row.get("volume_trust_label")) == fov_mod.TRUST_LABEL_TRUSTED
            and row.get("total_visible_volume_nl") not in (None, "")
            and width_valid
            and _time_axis_value(row, allow_flash_fallback=False) is not None
        )
        row["attached_near_nozzle_width_smoothed_px"] = None
        row["phase_label"] = "width_unavailable" if not width_valid else "head_or_transition"
        row["steady_candidate"] = bool(steady_candidate)
        row["steady_selected"] = False
        row["tail_drop_candidate"] = False
        row["tail_confirmation_frame"] = False
        row["tail_shoulder_end_frame"] = False
        row["tail_start_frame"] = False
        feature_rows.append(row)

    smoothed_widths = _centered_valid_rolling_median(
        [row.get("attached_near_nozzle_width_median_px") for row in feature_rows],
        int(width_smooth_window),
    )
    for row, smoothed_width in zip(feature_rows, smoothed_widths):
        row["attached_near_nozzle_width_smoothed_px"] = smoothed_width
    return feature_rows


def _contiguous_candidate_blocks(feature_rows: list[dict]):
    blocks = []
    current_block = []
    previous_capture_index = None

    for position, row in enumerate(feature_rows):
        capture_index = _int_or_none(row.get("capture_index"))
        if not bool(row.get("steady_candidate")):
            if current_block:
                blocks.append(list(current_block))
                current_block = []
            previous_capture_index = capture_index
            continue

        consecutive = bool(
            current_block
            and capture_index is not None
            and previous_capture_index is not None
            and capture_index == previous_capture_index + 1
        )
        if current_block and not consecutive:
            blocks.append(list(current_block))
            current_block = []
        current_block.append(position)
        previous_capture_index = capture_index

    if current_block:
        blocks.append(list(current_block))
    return blocks


def _plateau_width_metrics(
    window_rows: list[dict],
    *,
    steady_width_tol_frac: float,
    steady_width_tol_px: float,
):
    if len(window_rows) < 1:
        return None
    smoothed_widths = np.asarray(
        [row.get("attached_near_nozzle_width_smoothed_px") for row in window_rows],
        dtype=float,
    )
    if np.any(np.isnan(smoothed_widths)):
        return None

    width_plateau_px = float(np.median(smoothed_widths))
    width_span_px = float(np.max(smoothed_widths) - np.min(smoothed_widths))
    width_tolerance_px = float(
        max(float(steady_width_tol_px), float(steady_width_tol_frac) * float(width_plateau_px))
    )
    return {
        "steady_width_plateau_px": width_plateau_px,
        "steady_width_span_px": width_span_px,
        "steady_width_tolerance_px": width_tolerance_px,
        "steady_fit_ok": bool(width_span_px <= width_tolerance_px),
    }


def _fit_window_metrics(window_rows: list[dict]):
    if len(window_rows) < 2:
        return None

    x_values = np.asarray(
        [_time_axis_value(row, allow_flash_fallback=False) for row in window_rows],
        dtype=float,
    )
    if np.any(np.isnan(x_values)):
        return None

    y_values = np.asarray(
        [float(row["total_visible_volume_nl"]) for row in window_rows],
        dtype=float,
    )
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
        "steady_rate_nl_per_us": float(slope),
        "steady_intercept_nl": float(intercept),
        "steady_r2": r2,
        "steady_nrmse": nrmse,
        "steady_fit_first_last_residual_delta_nl": first_last_residual_delta_nl,
        "steady_fit_max_abs_residual_nl": max_abs_residual_nl,
        "steady_fit_residual_trend_nl_per_us": residual_trend_nl_per_us,
    }


def _steady_window_metrics(
    window_rows: list[dict],
    *,
    steady_width_tol_frac: float,
    steady_width_tol_px: float,
):
    fit_metrics = _fit_window_metrics(window_rows)
    plateau_metrics = _plateau_width_metrics(
        window_rows,
        steady_width_tol_frac=float(steady_width_tol_frac),
        steady_width_tol_px=float(steady_width_tol_px),
    )
    if fit_metrics is None or plateau_metrics is None:
        return None
    return {
        **fit_metrics,
        **plateau_metrics,
    }


def _fit_metrics_within_quality_thresholds(
    metrics: dict | None,
    *,
    steady_fit_r2_min: float,
    steady_fit_nrmse_max: float,
):
    if metrics is None:
        return False
    steady_r2 = _float_or_none(metrics.get("steady_r2"))
    steady_nrmse = _float_or_none(metrics.get("steady_nrmse"))
    if steady_r2 is None or steady_nrmse is None:
        return False
    return bool(
        float(steady_r2) >= float(steady_fit_r2_min)
        and float(steady_nrmse) <= float(steady_fit_nrmse_max)
    )


def _steady_window_is_acceptable(
    metrics: dict | None,
    *,
    steady_fit_r2_min: float,
    steady_fit_nrmse_max: float,
):
    if metrics is None or not bool(metrics.get("steady_fit_ok")):
        return False
    return _fit_metrics_within_quality_thresholds(
        metrics,
        steady_fit_r2_min=float(steady_fit_r2_min),
        steady_fit_nrmse_max=float(steady_fit_nrmse_max),
    )


def _steady_fit_confidence_from_points(steady_points: list[tuple[float, float]], *, central_rate: float | None):
    if central_rate is None:
        return {
            "steady_fit_point_count": 0,
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_missing_central_rate",
        }
    if len(steady_points) < 2:
        return {
            "steady_fit_point_count": len(steady_points),
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_insufficient_points",
        }

    x_values = np.asarray([point[0] for point in steady_points], dtype=float)
    y_values = np.asarray([point[1] for point in steady_points], dtype=float)
    if np.any(~np.isfinite(x_values)) or np.any(~np.isfinite(y_values)):
        return {
            "steady_fit_point_count": len(steady_points),
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
            "steady_fit_point_count": len(steady_points),
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_theilsen_failed",
        }

    rate_low = _float_or_none(lower_slope)
    rate_high = _float_or_none(upper_slope)
    if rate_low is None or rate_high is None:
        return {
            "steady_fit_point_count": len(steady_points),
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
        float(rate_low) - float(STEADY_RATE_CI_CONTAINS_CENTRAL_TOL)
        <= float(central_rate)
        <= float(rate_high) + float(STEADY_RATE_CI_CONTAINS_CENTRAL_TOL)
    )
    return {
        "steady_fit_point_count": len(steady_points),
        "steady_rate_ci95_low_nl_per_us": float(rate_low),
        "steady_rate_ci95_high_nl_per_us": float(rate_high),
        "steady_rate_ci95_relative_width": rate_relative_width,
        "steady_rate_ci95_contains_central": contains_central,
        "steady_rate_confidence_status": (
            "ok" if contains_central else "warning_central_rate_mismatch"
        ),
    }


def _find_steady_window(
    feature_rows: list[dict],
    *,
    min_steady_frames: int,
    steady_width_tol_frac: float,
    steady_width_tol_px: float,
    steady_fit_r2_min: float,
    steady_fit_nrmse_max: float,
):
    for block in _contiguous_candidate_blocks(feature_rows):
        if len(block) < int(min_steady_frames):
            continue
        for start_offset in range(0, len(block) - int(min_steady_frames) + 1):
            initial_positions = block[start_offset : start_offset + int(min_steady_frames)]
            initial_rows = [feature_rows[position] for position in initial_positions]
            metrics = _steady_window_metrics(
                initial_rows,
                steady_width_tol_frac=float(steady_width_tol_frac),
                steady_width_tol_px=float(steady_width_tol_px),
            )
            if not _steady_window_is_acceptable(
                metrics,
                steady_fit_r2_min=float(steady_fit_r2_min),
                steady_fit_nrmse_max=float(steady_fit_nrmse_max),
            ):
                continue

            best_positions = list(initial_positions)
            best_metrics = dict(metrics)
            end_offset = start_offset + int(min_steady_frames)
            while end_offset < len(block):
                trial_positions = block[start_offset : end_offset + 1]
                trial_rows = [feature_rows[position] for position in trial_positions]
                trial_metrics = _steady_window_metrics(
                    trial_rows,
                    steady_width_tol_frac=float(steady_width_tol_frac),
                    steady_width_tol_px=float(steady_width_tol_px),
                )
                if not _steady_window_is_acceptable(
                    trial_metrics,
                    steady_fit_r2_min=float(steady_fit_r2_min),
                    steady_fit_nrmse_max=float(steady_fit_nrmse_max),
                ):
                    break
                best_positions = list(trial_positions)
                best_metrics = dict(trial_metrics)
                end_offset += 1

            start_row = feature_rows[best_positions[0]]
            end_row = feature_rows[best_positions[-1]]
            return {
                **best_metrics,
                "steady_fit_status": "ok",
                "positions": list(best_positions),
                "steady_start_capture_index": _int_or_none(start_row.get("capture_index")),
                "steady_end_capture_index": _int_or_none(end_row.get("capture_index")),
            }

    return {
        "steady_fit_status": "unresolved",
        "positions": [],
        "steady_start_capture_index": None,
        "steady_end_capture_index": None,
        "steady_rate_nl_per_us": None,
        "steady_intercept_nl": None,
        "steady_r2": None,
        "steady_nrmse": None,
        "steady_width_plateau_px": None,
        "steady_width_span_px": None,
        "steady_width_tolerance_px": None,
    }


def _find_tail_onset(
    feature_rows: list[dict],
    steady_fit: dict,
    *,
    first_untrusted_capture_index: int | None,
    tail_drop_frac: float,
    tail_persist_frames: int,
):
    def _valid_smoothed_width(position: int):
        if int(position) < 0 or int(position) >= len(feature_rows):
            return None, None
        row = feature_rows[int(position)]
        capture_index = _int_or_none(row.get("capture_index"))
        width_smoothed_px = row.get("attached_near_nozzle_width_smoothed_px")
        if capture_index is None or width_smoothed_px is None:
            return None, None
        return int(capture_index), float(width_smoothed_px)

    def _tail_result(
        *,
        threshold_px,
        candidate_positions: set[int],
        tail_start_position: int | None,
        confirmation_position: int | None,
        detection_mode: str,
        tail_start_selection_mode: str | None,
        shoulder_end_position: int | None,
        preliminary_start_position: int | None,
        direct_final_start_position: int | None,
    ):
        if confirmation_position is None:
            tail_onset_status = "not_needed_no_fov_exit" if first_untrusted_capture_index is None else "unresolved"
            tail_detection_mode = (
                "not_needed_no_fov_exit" if first_untrusted_capture_index is None else "unresolved"
            )
            return {
                "tail_start_capture_index": None,
                "tail_start_delay_from_emergence_us": None,
                "tail_confirmation_capture_index": None,
                "tail_confirmation_delay_from_emergence_us": None,
                "tail_onset_status": tail_onset_status,
                "tail_detection_mode": tail_detection_mode,
                "tail_start_selection_mode": None,
                "preliminary_tail_start_capture_index": None,
                "preliminary_tail_start_delay_from_emergence_us": None,
                "direct_final_tail_start_capture_index": None,
                "direct_final_tail_start_delay_from_emergence_us": None,
                "tail_shoulder_end_capture_index": None,
                "tail_shoulder_end_delay_from_emergence_us": None,
                "tail_width_threshold_px": threshold_px,
                "tail_candidate_positions": candidate_positions,
                "tail_confirmation_position": None,
                "tail_shoulder_end_position": None,
                "preliminary_tail_start_position": None,
                "direct_final_tail_start_position": None,
                "tail_start_position": None,
            }

        confirmation_row = feature_rows[int(confirmation_position)]
        tail_start_row = feature_rows[int(tail_start_position)]
        preliminary_start_row = (
            None if preliminary_start_position is None else feature_rows[int(preliminary_start_position)]
        )
        direct_final_start_row = (
            None if direct_final_start_position is None else feature_rows[int(direct_final_start_position)]
        )
        shoulder_end_row = None if shoulder_end_position is None else feature_rows[int(shoulder_end_position)]
        tail_start_capture_index = _int_or_none(tail_start_row.get("capture_index"))
        if (
            first_untrusted_capture_index is not None
            and tail_start_capture_index is not None
            and tail_start_capture_index <= int(first_untrusted_capture_index)
        ):
            tail_onset_status = "before_fov_exit"
        else:
            tail_onset_status = "ok"
        return {
            "tail_start_capture_index": tail_start_capture_index,
            "tail_start_delay_from_emergence_us": _int_or_none(tail_start_row.get("delay_from_emergence_us")),
            "tail_confirmation_capture_index": _int_or_none(confirmation_row.get("capture_index")),
            "tail_confirmation_delay_from_emergence_us": _int_or_none(
                confirmation_row.get("delay_from_emergence_us")
            ),
            "tail_onset_status": tail_onset_status,
            "tail_detection_mode": detection_mode,
            "tail_start_selection_mode": tail_start_selection_mode,
            "preliminary_tail_start_capture_index": None
            if preliminary_start_row is None
            else _int_or_none(preliminary_start_row.get("capture_index")),
            "preliminary_tail_start_delay_from_emergence_us": None
            if preliminary_start_row is None
            else _int_or_none(preliminary_start_row.get("delay_from_emergence_us")),
            "direct_final_tail_start_capture_index": None
            if direct_final_start_row is None
            else _int_or_none(direct_final_start_row.get("capture_index")),
            "direct_final_tail_start_delay_from_emergence_us": None
            if direct_final_start_row is None
            else _int_or_none(direct_final_start_row.get("delay_from_emergence_us")),
            "tail_shoulder_end_capture_index": None
            if shoulder_end_row is None
            else _int_or_none(shoulder_end_row.get("capture_index")),
            "tail_shoulder_end_delay_from_emergence_us": None
            if shoulder_end_row is None
            else _int_or_none(shoulder_end_row.get("delay_from_emergence_us")),
            "tail_width_threshold_px": threshold_px,
            "tail_candidate_positions": candidate_positions,
            "tail_confirmation_position": int(confirmation_position),
            "tail_shoulder_end_position": None
            if shoulder_end_position is None
            else int(shoulder_end_position),
            "preliminary_tail_start_position": None
            if preliminary_start_position is None
            else int(preliminary_start_position),
            "direct_final_tail_start_position": None
            if direct_final_start_position is None
            else int(direct_final_start_position),
            "tail_start_position": int(tail_start_position),
        }

    def _backtrack_tail_start_position(confirmation_position: int, *, plateau_tol_px: float):
        plateau_floor = float(steady_width_plateau_px) - float(plateau_tol_px)
        confirmation_capture_index = _int_or_none(feature_rows[int(confirmation_position)].get("capture_index"))
        previous_capture_index = confirmation_capture_index
        anchor_position = None

        for position in range(int(confirmation_position) - 1, -1, -1):
            row = feature_rows[position]
            capture_index = _int_or_none(row.get("capture_index"))
            if capture_index is None or capture_index <= int(steady_end_capture_index):
                break
            if previous_capture_index is not None and capture_index != int(previous_capture_index) - 1:
                break
            width_smoothed_px = row.get("attached_near_nozzle_width_smoothed_px")
            if width_smoothed_px is None:
                break
            if float(width_smoothed_px) >= float(plateau_floor):
                anchor_position = int(position)
                break
            previous_capture_index = capture_index

        if anchor_position is None:
            return int(confirmation_position)
        return int(anchor_position + 1)

    def _shoulder_adjusted_tail_start(
        preliminary_start_position: int,
        confirmation_position: int,
        threshold_px: float,
    ):
        if int(preliminary_start_position) >= int(confirmation_position):
            return int(preliminary_start_position), "direct_backtrack", None

        contiguous_groups: list[list[int]] = []
        current_group: list[int] = []
        previous_capture_index = None
        for position in range(int(preliminary_start_position), int(confirmation_position)):
            capture_index, width_smoothed_px = _valid_smoothed_width(position)
            if capture_index is None or width_smoothed_px is None:
                if current_group:
                    contiguous_groups.append(list(current_group))
                    current_group = []
                previous_capture_index = None
                continue

            if current_group and previous_capture_index is not None and capture_index != int(previous_capture_index) + 1:
                contiguous_groups.append(list(current_group))
                current_group = []

            current_group.append(int(position))
            previous_capture_index = int(capture_index)

        if current_group:
            contiguous_groups.append(list(current_group))

        qualifying_candidate = None
        for group in contiguous_groups:
            for start_offset in range(len(group)):
                shoulder_widths: list[float] = []
                for end_offset in range(start_offset, len(group)):
                    position = int(group[end_offset])
                    _capture_index, width_smoothed_px = _valid_smoothed_width(position)
                    if width_smoothed_px is None or float(width_smoothed_px) <= float(threshold_px):
                        break

                    shoulder_widths.append(float(width_smoothed_px))
                    width_span = float(max(shoulder_widths) - min(shoulder_widths))
                    if width_span > float(TAIL_SHOULDER_MAX_SPAN_PX):
                        break
                    if len(shoulder_widths) < int(TAIL_SHOULDER_MIN_FRAMES):
                        continue

                    lookahead_positions = group[end_offset + 1 : end_offset + 1 + int(TAIL_SHOULDER_EXIT_LOOKAHEAD_FRAMES)]
                    if not lookahead_positions:
                        continue

                    shoulder_median = float(np.median(np.asarray(shoulder_widths, dtype=float)))
                    exit_threshold = float(shoulder_median - float(TAIL_SHOULDER_EXIT_DROP_PX))
                    lookahead_widths = []
                    for lookahead_position in lookahead_positions:
                        _lookahead_capture_index, lookahead_width = _valid_smoothed_width(int(lookahead_position))
                        if lookahead_width is not None:
                            lookahead_widths.append(float(lookahead_width))

                    if lookahead_widths and any(
                        float(lookahead_width) <= float(exit_threshold) for lookahead_width in lookahead_widths
                    ):
                        qualifying_candidate = {
                            "shoulder_end_position": int(group[end_offset]),
                            "tail_start_position": int(lookahead_positions[0]),
                        }

        if qualifying_candidate is None:
            return int(preliminary_start_position), "direct_backtrack", None
        return (
            int(qualifying_candidate["tail_start_position"]),
            "shoulder_adjusted",
            int(qualifying_candidate["shoulder_end_position"]),
        )

    def _truncated_confirmation_position(candidate_positions: set[int], threshold_px: float):
        min_below_count = max(2, int(tail_persist_frames) - 1)
        valid_positions = [
            position
            for position, row in enumerate(feature_rows)
            if _int_or_none(row.get("capture_index")) is not None
            and _int_or_none(row.get("capture_index")) > int(steady_end_capture_index)
            and row.get("attached_near_nozzle_width_smoothed_px") is not None
        ]
        if not valid_positions:
            return None

        last_valid_position = int(valid_positions[-1])
        if last_valid_position >= len(feature_rows) - 1:
            return None
        if float(feature_rows[last_valid_position]["attached_near_nozzle_width_smoothed_px"]) > float(threshold_px):
            return None

        trailing_positions = [last_valid_position]
        previous_capture_index = _int_or_none(feature_rows[last_valid_position].get("capture_index"))
        for position in range(last_valid_position - 1, -1, -1):
            row = feature_rows[position]
            capture_index = _int_or_none(row.get("capture_index"))
            if capture_index is None or capture_index <= int(steady_end_capture_index):
                break
            if previous_capture_index is not None and capture_index != int(previous_capture_index) - 1:
                break
            width_smoothed_px = row.get("attached_near_nozzle_width_smoothed_px")
            if width_smoothed_px is None or float(width_smoothed_px) > float(threshold_px):
                break
            trailing_positions.insert(0, int(position))
            previous_capture_index = capture_index

        if len(trailing_positions) < int(min_below_count):
            return None

        saw_earlier_above_threshold = any(
            row.get("attached_near_nozzle_width_smoothed_px") is not None
            and float(row["attached_near_nozzle_width_smoothed_px"]) > float(threshold_px)
            for row in feature_rows[: trailing_positions[0]]
            if _int_or_none(row.get("capture_index")) is not None
            and _int_or_none(row.get("capture_index")) > int(steady_end_capture_index)
        )
        if not saw_earlier_above_threshold:
            return None

        candidate_positions.update(int(position) for position in trailing_positions)
        return int(trailing_positions[0])

    if _clean_text(steady_fit.get("steady_fit_status")) != "ok":
        return _tail_result(
            threshold_px=None,
            candidate_positions=set(),
            tail_start_position=None,
            confirmation_position=None,
            detection_mode="unresolved",
            tail_start_selection_mode=None,
            shoulder_end_position=None,
            preliminary_start_position=None,
            direct_final_start_position=None,
        )

    steady_end_capture_index = _int_or_none(steady_fit.get("steady_end_capture_index"))
    steady_width_plateau_px = steady_fit.get("steady_width_plateau_px")
    if steady_end_capture_index is None or steady_width_plateau_px is None:
        return _tail_result(
            threshold_px=None,
            candidate_positions=set(),
            tail_start_position=None,
            confirmation_position=None,
            detection_mode="unresolved",
            tail_start_selection_mode=None,
            shoulder_end_position=None,
            preliminary_start_position=None,
            direct_final_start_position=None,
        )

    threshold_px = float((1.0 - float(tail_drop_frac)) * float(steady_width_plateau_px))
    candidate_positions: set[int] = set()
    streak_positions = []
    previous_capture_index = None
    confirmation_position = None
    detection_mode = "unresolved"

    for position, row in enumerate(feature_rows):
        capture_index = _int_or_none(row.get("capture_index"))
        if capture_index is None or capture_index <= int(steady_end_capture_index):
            continue
        width_smoothed_px = row.get("attached_near_nozzle_width_smoothed_px")
        if width_smoothed_px is None or float(width_smoothed_px) > threshold_px:
            streak_positions = []
            previous_capture_index = capture_index
            continue

        if streak_positions and previous_capture_index is not None and capture_index != previous_capture_index + 1:
            streak_positions = []
        streak_positions.append(position)
        candidate_positions.add(position)
        previous_capture_index = capture_index
        if len(streak_positions) >= int(tail_persist_frames):
            confirmation_position = int(streak_positions[0])
            detection_mode = "confirmed_persistent"
            break

    if confirmation_position is None:
        confirmation_position = _truncated_confirmation_position(candidate_positions, threshold_px)
        if confirmation_position is not None:
            detection_mode = "confirmed_truncated_width_loss"

    tail_start_position = None
    tail_start_selection_mode = None
    shoulder_end_position = None
    preliminary_start_position = None
    direct_final_start_position = None
    if confirmation_position is not None:
        preliminary_start_position = _backtrack_tail_start_position(
            int(confirmation_position),
            plateau_tol_px=float(TAIL_PRELIM_BACKTRACK_PLATEAU_TOL_PX),
        )
        direct_final_start_position = _backtrack_tail_start_position(
            int(confirmation_position),
            plateau_tol_px=float(TAIL_DIRECT_FINAL_DROP_PX),
        )
        (
            tail_start_position,
            tail_start_selection_mode,
            shoulder_end_position,
        ) = _shoulder_adjusted_tail_start(
            int(preliminary_start_position),
            int(confirmation_position),
            float(threshold_px),
        )
        if tail_start_selection_mode == "direct_backtrack":
            tail_start_position = int(direct_final_start_position)

    return _tail_result(
        threshold_px=threshold_px,
        candidate_positions=candidate_positions,
        tail_start_position=tail_start_position,
        confirmation_position=confirmation_position,
        detection_mode=detection_mode,
        tail_start_selection_mode=tail_start_selection_mode,
        shoulder_end_position=shoulder_end_position,
        preliminary_start_position=preliminary_start_position,
        direct_final_start_position=direct_final_start_position,
    )


def _middle_extrapolation(
    feature_rows: list[dict],
    steady_fit: dict,
    tail_onset: dict,
    fov_report: dict,
    *,
    trusted_visible_volume_nl: float | None = None,
    first_untrusted_delay_from_emergence_us: int | None = None,
):
    if trusted_visible_volume_nl is None:
        last_trusted_row = next(
            (
                row
                for row in reversed(feature_rows)
                if _clean_text(row.get("volume_trust_label")) == fov_mod.TRUST_LABEL_TRUSTED
                and row.get("total_visible_volume_nl") is not None
            ),
            None,
        )
        trusted_visible_volume_nl = (
            None if last_trusted_row is None else float(last_trusted_row["total_visible_volume_nl"])
        )
    first_untrusted_capture_index = _int_or_none(fov_report.get("first_untrusted_capture_index"))
    tail_start_capture_index = _int_or_none(tail_onset.get("tail_start_capture_index"))

    if first_untrusted_capture_index is None:
        middle_extrapolated_volume_nl = 0.0
        middle_extrapolation_status = "not_needed_no_fov_exit"
    elif _clean_text(steady_fit.get("steady_fit_status")) != "ok":
        middle_extrapolated_volume_nl = None
        middle_extrapolation_status = "unresolved_no_steady_fit"
    elif tail_start_capture_index is None:
        middle_extrapolated_volume_nl = None
        middle_extrapolation_status = "unresolved_no_tail_onset"
    elif tail_start_capture_index <= int(first_untrusted_capture_index):
        middle_extrapolated_volume_nl = 0.0
        middle_extrapolation_status = "zero_tail_before_fov_exit"
    else:
        end_row = _row_by_capture_index(feature_rows, int(tail_start_capture_index))
        start_time_us = _int_or_none(first_untrusted_delay_from_emergence_us)
        if start_time_us is None:
            start_row = _row_by_capture_index(feature_rows, int(first_untrusted_capture_index))
            start_time_us = None if start_row is None else _time_axis_value(start_row, allow_flash_fallback=True)
        end_time_us = None if end_row is None else _time_axis_value(end_row, allow_flash_fallback=True)
        if start_time_us is None or end_time_us is None or int(end_time_us) < int(start_time_us):
            middle_extrapolated_volume_nl = None
            middle_extrapolation_status = "unresolved_missing_time_axis"
        else:
            middle_extrapolated_volume_nl = float(steady_fit["steady_rate_nl_per_us"]) * float(
                int(end_time_us) - int(start_time_us)
            )
            middle_extrapolation_status = "ok"

    if trusted_visible_volume_nl is None:
        partial_total_without_tail_nl = None
    elif middle_extrapolated_volume_nl is None:
        partial_total_without_tail_nl = float(trusted_visible_volume_nl)
    else:
        partial_total_without_tail_nl = float(trusted_visible_volume_nl + float(middle_extrapolated_volume_nl))

    return {
        "trusted_visible_volume_nl": trusted_visible_volume_nl,
        "middle_extrapolated_volume_nl": middle_extrapolated_volume_nl,
        "partial_total_without_tail_nl": partial_total_without_tail_nl,
        "tail_volume_nl": None,
        "middle_extrapolation_status": middle_extrapolation_status,
        "final_total_status": "tail_pending",
        "first_untrusted_capture_index": first_untrusted_capture_index,
        "tail_start_capture_index": tail_start_capture_index,
    }


def _middle_extrapolation_start_time_us(
    feature_rows: list[dict],
    fov_report: dict,
    *,
    first_untrusted_delay_from_emergence_us: int | None = None,
):
    first_untrusted_capture_index = _int_or_none(fov_report.get("first_untrusted_capture_index"))
    start_time_us = _int_or_none(first_untrusted_delay_from_emergence_us)
    if start_time_us is None and first_untrusted_capture_index is not None:
        start_row = _row_by_capture_index(feature_rows, int(first_untrusted_capture_index))
        start_time_us = None if start_row is None else _time_axis_value(start_row, allow_flash_fallback=True)
    return first_untrusted_capture_index, start_time_us


def _plausible_tail_uncertainty_candidates(
    candidate_rows: list[dict],
    *,
    score_tolerance: float,
):
    usable_rows = [
        dict(candidate_row)
        for candidate_row in candidate_rows
        if _int_or_none(candidate_row.get("capture_index")) is not None
        and _float_or_none(candidate_row.get("delay_from_emergence_us")) is not None
    ]
    if not usable_rows:
        return [], None

    in_band_rows = [
        row for row in usable_rows if bool(row.get("within_unified_band"))
    ]
    if in_band_rows:
        return sorted(
            in_band_rows,
            key=lambda row: (
                int(_int_or_none(row.get("capture_index"))),
                int(_int_or_none(row.get("position")) or -1),
            ),
        ), "unified_band"

    scored_rows = [
        row for row in usable_rows if _float_or_none(row.get("score_total")) is not None
    ]
    if not scored_rows:
        return [], None

    best_score = min(float(row["score_total"]) for row in scored_rows)
    plausible_rows = [
        row
        for row in scored_rows
        if float(row["score_total"]) <= float(best_score) + float(score_tolerance) + 1e-12
    ]
    return sorted(
        plausible_rows,
        key=lambda row: (
            int(_int_or_none(row.get("capture_index"))),
            int(_int_or_none(row.get("position")) or -1),
        ),
    ), "score_tolerance"


def _propagated_volume_uncertainty_from_review(
    feature_rows: list[dict],
    steady_fit: dict,
    middle: dict,
    fov_report: dict,
    *,
    tail_start_candidate_rows: list[dict],
    first_untrusted_delay_from_emergence_us: int | None,
    sample_count: int,
    seed: int,
    tail_uncertainty_score_tolerance: float,
):
    result = {
        "tail_start_uncertainty_p05_us": None,
        "tail_start_uncertainty_p95_us": None,
        "tail_start_uncertainty_candidate_count": 0,
        "tail_start_uncertainty_source": None,
        "predicted_volume_uncertainty_p05_nl": None,
        "predicted_volume_uncertainty_p95_nl": None,
        "predicted_volume_uncertainty_width_nl": None,
        "predicted_volume_uncertainty_relative_width": None,
        "predicted_volume_uncertainty_status": "unresolved_missing_rate_interval",
        "volume_uncertainty_sample_count": 0,
    }

    trusted_visible_volume_nl = _float_or_none(middle.get("trusted_visible_volume_nl"))
    partial_total_without_tail_nl = _float_or_none(middle.get("partial_total_without_tail_nl"))
    first_untrusted_capture_index, start_time_us = _middle_extrapolation_start_time_us(
        feature_rows,
        fov_report,
        first_untrusted_delay_from_emergence_us=first_untrusted_delay_from_emergence_us,
    )

    if first_untrusted_capture_index is None:
        result.update(
            {
                "tail_start_uncertainty_source": "not_needed_no_fov_exit",
                "predicted_volume_uncertainty_p05_nl": partial_total_without_tail_nl,
                "predicted_volume_uncertainty_p95_nl": partial_total_without_tail_nl,
                "predicted_volume_uncertainty_width_nl": 0.0
                if partial_total_without_tail_nl is not None
                else None,
                "predicted_volume_uncertainty_relative_width": 0.0
                if partial_total_without_tail_nl not in (None, 0.0)
                else (0.0 if partial_total_without_tail_nl == 0.0 else None),
                "predicted_volume_uncertainty_status": "not_needed_no_fov_exit",
            }
        )
        return result

    if trusted_visible_volume_nl is None:
        result["predicted_volume_uncertainty_status"] = "unresolved_missing_trusted_visible_volume"
        return result

    rate_low = _float_or_none(steady_fit.get("steady_rate_ci95_low_nl_per_us"))
    rate_high = _float_or_none(steady_fit.get("steady_rate_ci95_high_nl_per_us"))
    if rate_low is None or rate_high is None:
        return result
    ordered_rate_low = float(min(rate_low, rate_high))
    ordered_rate_high = float(max(rate_low, rate_high))
    rate_low = ordered_rate_low
    rate_high = ordered_rate_high

    plausible_rows, uncertainty_source = _plausible_tail_uncertainty_candidates(
        list(tail_start_candidate_rows or []),
        score_tolerance=float(tail_uncertainty_score_tolerance),
    )
    if not plausible_rows:
        result["predicted_volume_uncertainty_status"] = "unresolved_missing_plausible_tail_candidates"
        return result
    if uncertainty_source is None:
        result["predicted_volume_uncertainty_status"] = "unresolved_missing_tail_scores"
        return result
    if start_time_us is None:
        result["predicted_volume_uncertainty_status"] = "unresolved_missing_start_time"
        return result

    resolved_sample_count = max(1, int(sample_count))
    rng = np.random.default_rng(int(seed))
    if float(rate_low) == float(rate_high):
        rate_samples = np.full(resolved_sample_count, float(rate_low), dtype=float)
    else:
        rate_samples = rng.uniform(float(rate_low), float(rate_high), size=resolved_sample_count)

    tail_capture_indices = np.asarray(
        [int(_int_or_none(row.get("capture_index"))) for row in plausible_rows],
        dtype=int,
    )
    tail_delay_samples_available = np.asarray(
        [float(_float_or_none(row.get("delay_from_emergence_us"))) for row in plausible_rows],
        dtype=float,
    )
    sampled_positions = rng.integers(
        0,
        len(plausible_rows),
        size=resolved_sample_count,
        endpoint=False,
    )
    sampled_capture_indices = tail_capture_indices[sampled_positions]
    sampled_tail_delays_us = tail_delay_samples_available[sampled_positions]

    middle_samples_nl = np.where(
        sampled_capture_indices <= int(first_untrusted_capture_index),
        0.0,
        rate_samples * np.maximum(sampled_tail_delays_us - float(start_time_us), 0.0),
    )
    partial_total_samples_nl = float(trusted_visible_volume_nl) + middle_samples_nl

    tail_p05_us, tail_p95_us = np.percentile(sampled_tail_delays_us, [5.0, 95.0])
    predicted_p05_nl, predicted_p95_nl = np.percentile(partial_total_samples_nl, [5.0, 95.0])
    predicted_width_nl = float(predicted_p95_nl - predicted_p05_nl)
    predicted_relative_width = None
    if partial_total_without_tail_nl is not None and float(partial_total_without_tail_nl) != 0.0:
        predicted_relative_width = float(
            predicted_width_nl / abs(float(partial_total_without_tail_nl))
        )

    result.update(
        {
            "tail_start_uncertainty_p05_us": float(tail_p05_us),
            "tail_start_uncertainty_p95_us": float(tail_p95_us),
            "tail_start_uncertainty_candidate_count": int(len(plausible_rows)),
            "tail_start_uncertainty_source": str(uncertainty_source),
            "predicted_volume_uncertainty_p05_nl": float(predicted_p05_nl),
            "predicted_volume_uncertainty_p95_nl": float(predicted_p95_nl),
            "predicted_volume_uncertainty_width_nl": predicted_width_nl,
            "predicted_volume_uncertainty_relative_width": predicted_relative_width,
            "predicted_volume_uncertainty_status": "ok",
            "volume_uncertainty_sample_count": int(resolved_sample_count),
        }
    )
    return result


def _steady_fit_from_payload(feature_rows: list[dict], steady_fit_payload: dict):
    plateau_capture_indices, plateau_positions = _capture_indices_and_positions_from_payload(
        feature_rows,
        capture_indices=list(
            steady_fit_payload.get("plateau_capture_indices")
            or steady_fit_payload.get("steady_capture_indices")
            or []
        ),
        start_capture_index=_int_or_none(steady_fit_payload.get("steady_start_capture_index")),
        end_capture_index=_int_or_none(steady_fit_payload.get("steady_end_capture_index")),
    )
    flow_fit_capture_indices, flow_fit_positions = _capture_indices_and_positions_from_payload(
        feature_rows,
        capture_indices=list(
            steady_fit_payload.get("flow_fit_capture_indices")
            or steady_fit_payload.get("steady_capture_indices")
            or []
        ),
        start_capture_index=(
            _int_or_none(steady_fit_payload.get("flow_fit_start_capture_index"))
            if _int_or_none(steady_fit_payload.get("flow_fit_start_capture_index")) is not None
            else _int_or_none(steady_fit_payload.get("steady_start_capture_index"))
        ),
        end_capture_index=(
            _int_or_none(steady_fit_payload.get("flow_fit_end_capture_index"))
            if _int_or_none(steady_fit_payload.get("flow_fit_end_capture_index")) is not None
            else _int_or_none(steady_fit_payload.get("steady_end_capture_index"))
        ),
    )
    confidence = _steady_fit_confidence_from_payload(
        feature_rows,
        steady_fit_payload,
        flow_fit_capture_indices=flow_fit_capture_indices,
    )
    flow_fit_backfill_point_count = _int_or_none(
        steady_fit_payload.get("flow_fit_backfill_point_count")
    )
    if flow_fit_backfill_point_count is None:
        plateau_capture_index_set = set(int(value) for value in plateau_capture_indices)
        flow_fit_backfill_point_count = int(
            sum(
                1
                for capture_index in flow_fit_capture_indices
                if int(capture_index) not in plateau_capture_index_set
                and int(capture_index) < int(plateau_capture_indices[0])
            )
        ) if plateau_capture_indices else 0
    return {
        "steady_fit_status": steady_fit_payload.get("steady_fit_status"),
        "steady_fit_mode": steady_fit_payload.get("steady_fit_mode") or "frozen",
        "positions": plateau_positions,
        "plateau_positions": plateau_positions,
        "flow_fit_positions": flow_fit_positions,
        "steady_capture_indices": plateau_capture_indices,
        "plateau_capture_indices": plateau_capture_indices,
        "flow_fit_capture_indices": flow_fit_capture_indices,
        "steady_start_capture_index": _int_or_none(steady_fit_payload.get("steady_start_capture_index")),
        "steady_end_capture_index": _int_or_none(steady_fit_payload.get("steady_end_capture_index")),
        "plateau_point_count": _int_or_none(steady_fit_payload.get("plateau_point_count"))
        or int(len(plateau_capture_indices)),
        "flow_fit_start_capture_index": _int_or_none(
            steady_fit_payload.get("flow_fit_start_capture_index")
        )
        if _int_or_none(steady_fit_payload.get("flow_fit_start_capture_index")) is not None
        else (
            None if not flow_fit_capture_indices else int(flow_fit_capture_indices[0])
        ),
        "flow_fit_end_capture_index": _int_or_none(
            steady_fit_payload.get("flow_fit_end_capture_index")
        )
        if _int_or_none(steady_fit_payload.get("flow_fit_end_capture_index")) is not None
        else (
            None if not flow_fit_capture_indices else int(flow_fit_capture_indices[-1])
        ),
        "flow_fit_point_count": _int_or_none(steady_fit_payload.get("flow_fit_point_count"))
        or int(len(flow_fit_capture_indices)),
        "flow_fit_eligible_point_count": _int_or_none(
            steady_fit_payload.get("flow_fit_eligible_point_count")
        )
        or int(len(flow_fit_capture_indices)),
        "flow_fit_backfill_point_count": int(flow_fit_backfill_point_count),
        "flow_fit_outlier_prune_status": steady_fit_payload.get("flow_fit_outlier_prune_status")
        or (
            "legacy_unspecified"
            if flow_fit_capture_indices
            else "unresolved_no_steady_fit"
        ),
        "flow_fit_dropped_outlier_capture_index": _int_or_none(
            steady_fit_payload.get("flow_fit_dropped_outlier_capture_index")
        ),
        "flow_fit_dropped_outlier_delay_from_emergence_us": _int_or_none(
            steady_fit_payload.get("flow_fit_dropped_outlier_delay_from_emergence_us")
        ),
        "flow_fit_dropped_outlier_local_deviation_nl": _float_or_none(
            steady_fit_payload.get("flow_fit_dropped_outlier_local_deviation_nl")
        ),
        "steady_rate_nl_per_us": steady_fit_payload.get("steady_rate_nl_per_us"),
        "steady_intercept_nl": steady_fit_payload.get("steady_intercept_nl"),
        "steady_r2": steady_fit_payload.get("steady_r2"),
        "steady_nrmse": steady_fit_payload.get("steady_nrmse"),
        "steady_width_plateau_px": steady_fit_payload.get("steady_width_plateau_px"),
        "steady_width_span_px": steady_fit_payload.get("steady_width_span_px"),
        "steady_width_tolerance_px": steady_fit_payload.get("steady_width_tolerance_px"),
        "steady_fit_candidate_window_count": _int_or_none(
            steady_fit_payload.get("steady_fit_candidate_window_count")
        ),
        "steady_fit_selection_score": _float_or_none(
            steady_fit_payload.get("steady_fit_selection_score")
        ),
        "steady_fit_exclude_last_trusted_frames": _int_or_none(
            steady_fit_payload.get("steady_fit_exclude_last_trusted_frames")
        ),
        "steady_fit_excluded_tail_trusted_frame_count": _int_or_none(
            steady_fit_payload.get("steady_fit_excluded_tail_trusted_frame_count")
        ),
        "excluded_tail_trusted_capture_indices": [
            capture_index
            for capture_index in [
                _int_or_none(capture_index)
                for capture_index in list(
                    steady_fit_payload.get("excluded_tail_trusted_capture_indices") or []
                )
            ]
            if capture_index is not None
        ],
        "steady_fit_first_last_residual_delta_nl": _float_or_none(
            steady_fit_payload.get("steady_fit_first_last_residual_delta_nl")
        ),
        "steady_fit_max_abs_residual_nl": _float_or_none(
            steady_fit_payload.get("steady_fit_max_abs_residual_nl")
        ),
        "steady_fit_residual_trend_nl_per_us": _float_or_none(
            steady_fit_payload.get("steady_fit_residual_trend_nl_per_us")
        ),
        **confidence,
    }


def _capture_indices_and_positions_from_payload(
    feature_rows: list[dict],
    *,
    capture_indices: list[int] | None,
    start_capture_index: int | None,
    end_capture_index: int | None,
):
    capture_positions = {
        _int_or_none(row.get("capture_index")): position
        for position, row in enumerate(feature_rows)
        if _int_or_none(row.get("capture_index")) is not None
    }
    selected_capture_indices = [
        capture_index
        for capture_index in [
            _int_or_none(capture_index)
            for capture_index in list(capture_indices or [])
        ]
        if capture_index is not None and capture_index in capture_positions
    ]
    if not selected_capture_indices:
        if (
            start_capture_index is not None
            and end_capture_index is not None
            and int(end_capture_index) >= int(start_capture_index)
        ):
            selected_capture_indices = [
                capture_index
                for capture_index in range(
                    int(start_capture_index),
                    int(end_capture_index) + 1,
                )
                if capture_index in capture_positions
            ]
    positions = [capture_positions[capture_index] for capture_index in selected_capture_indices]
    return selected_capture_indices, positions


def _steady_fit_confidence_from_payload(
    feature_rows: list[dict],
    steady_fit_payload: dict,
    *,
    flow_fit_capture_indices: list[int] | None = None,
):
    if _clean_text(steady_fit_payload.get("steady_fit_status")) != "ok":
        return {
            "steady_fit_point_count": 0,
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_no_steady_fit",
        }

    central_rate = _float_or_none(steady_fit_payload.get("steady_rate_nl_per_us"))
    if central_rate is None:
        return {
            "steady_fit_point_count": 0,
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_missing_central_rate",
        }

    if flow_fit_capture_indices is None:
        flow_fit_capture_indices, _positions = _capture_indices_and_positions_from_payload(
            feature_rows,
            capture_indices=list(
                steady_fit_payload.get("flow_fit_capture_indices")
                or steady_fit_payload.get("steady_capture_indices")
                or []
            ),
            start_capture_index=(
                _int_or_none(steady_fit_payload.get("flow_fit_start_capture_index"))
                if _int_or_none(steady_fit_payload.get("flow_fit_start_capture_index")) is not None
                else _int_or_none(steady_fit_payload.get("steady_start_capture_index"))
            ),
            end_capture_index=(
                _int_or_none(steady_fit_payload.get("flow_fit_end_capture_index"))
                if _int_or_none(steady_fit_payload.get("flow_fit_end_capture_index")) is not None
                else _int_or_none(steady_fit_payload.get("steady_end_capture_index"))
            ),
        )

    steady_points = []
    for capture_index in flow_fit_capture_indices:
        row = _row_by_capture_index(feature_rows, int(capture_index))
        if row is None:
            continue
        time_us = _time_axis_value(row, allow_flash_fallback=False)
        volume_nl = _float_or_none(row.get("total_visible_volume_nl"))
        if time_us is None or volume_nl is None:
            continue
        steady_points.append((float(time_us), float(volume_nl)))

    if any(
        not (math.isfinite(point[0]) and math.isfinite(point[1]))
        for point in steady_points
    ):
        return {
            "steady_fit_point_count": len(steady_points),
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_missing_time_or_volume",
        }
    return _steady_fit_confidence_from_points(
        steady_points,
        central_rate=float(central_rate),
    )


def _contiguous_position_blocks(feature_rows: list[dict], positions: list[int]):
    blocks = []
    current_block = []
    previous_capture_index = None
    for position in positions:
        capture_index = _int_or_none(feature_rows[int(position)].get("capture_index"))
        if capture_index is None:
            if current_block:
                blocks.append(list(current_block))
                current_block = []
            previous_capture_index = None
            continue
        consecutive = bool(
            current_block
            and previous_capture_index is not None
            and int(capture_index) == int(previous_capture_index) + 1
        )
        if current_block and not consecutive:
            blocks.append(list(current_block))
            current_block = []
        current_block.append(int(position))
        previous_capture_index = int(capture_index)
    if current_block:
        blocks.append(list(current_block))
    return blocks


def _excluded_tail_trusted_positions(
    feature_rows: list[dict],
    *,
    first_untrusted_capture_index: int | None,
    exclude_last_trusted_frames: int,
):
    if (
        first_untrusted_capture_index is None
        or int(exclude_last_trusted_frames) <= 0
    ):
        return []

    trusted_candidate_positions = [
        position
        for position, row in enumerate(feature_rows)
        if bool(row.get("steady_candidate"))
        and (
            _int_or_none(row.get("capture_index")) is not None
            and _int_or_none(row.get("capture_index")) < int(first_untrusted_capture_index)
        )
    ]
    if not trusted_candidate_positions:
        return []

    tail_positions = [int(trusted_candidate_positions[-1])]
    previous_capture_index = _int_or_none(
        feature_rows[int(trusted_candidate_positions[-1])].get("capture_index")
    )
    for position in reversed(trusted_candidate_positions[:-1]):
        capture_index = _int_or_none(feature_rows[int(position)].get("capture_index"))
        if (
            capture_index is None
            or previous_capture_index is None
            or int(capture_index) != int(previous_capture_index) - 1
        ):
            break
        tail_positions.insert(0, int(position))
        previous_capture_index = int(capture_index)
    return tail_positions[-int(exclude_last_trusted_frames) :]


def _first_plateau_seed_in_block(
    feature_rows: list[dict],
    block: list[int],
    *,
    min_steady_frames: int,
    steady_width_tol_frac: float,
    steady_width_tol_px: float,
):
    candidate_window_count = 0
    if len(block) < int(min_steady_frames):
        return None, candidate_window_count

    for start_offset in range(0, len(block) - int(min_steady_frames) + 1):
        candidate_window_count += 1
        plateau_positions = list(block[start_offset : start_offset + int(min_steady_frames)])
        plateau_rows = [feature_rows[int(position)] for position in plateau_positions]
        plateau_metrics = _plateau_width_metrics(
            plateau_rows,
            steady_width_tol_frac=float(steady_width_tol_frac),
            steady_width_tol_px=float(steady_width_tol_px),
        )
        if plateau_metrics is None or not bool(plateau_metrics.get("steady_fit_ok")):
            continue
        return {
            "plateau_positions": plateau_positions,
            "plateau_metrics": plateau_metrics,
            "start_offset": int(start_offset),
        }, candidate_window_count
    return None, candidate_window_count


def _flow_fit_backfill_positions(
    feature_rows: list[dict],
    selected_block: list[int],
    *,
    plateau_seed: dict,
    flow_fit_backfill_max_frames: int,
    flow_fit_backfill_width_delta_px: float,
    flow_fit_backfill_monotonic_slack_px: float,
):
    max_frames = max(0, int(flow_fit_backfill_max_frames))
    if max_frames <= 0:
        return []

    plateau_metrics = dict(plateau_seed.get("plateau_metrics") or {})
    plateau_width_px = _float_or_none(plateau_metrics.get("steady_width_plateau_px"))
    start_offset = _int_or_none(plateau_seed.get("start_offset"))
    if plateau_width_px is None or start_offset is None or int(start_offset) <= 0:
        return []

    backfilled_positions = []
    next_retained_position = int(selected_block[int(start_offset)])
    for block_offset in range(int(start_offset) - 1, -1, -1):
        if len(backfilled_positions) >= int(max_frames):
            break
        candidate_position = int(selected_block[int(block_offset)])
        candidate_row = feature_rows[int(candidate_position)]
        next_row = feature_rows[int(next_retained_position)]
        candidate_width_px = _float_or_none(candidate_row.get("attached_near_nozzle_width_smoothed_px"))
        next_width_px = _float_or_none(next_row.get("attached_near_nozzle_width_smoothed_px"))
        if candidate_width_px is None or next_width_px is None:
            break
        if float(candidate_width_px) > float(plateau_width_px) + float(flow_fit_backfill_width_delta_px):
            break
        if float(candidate_width_px) < float(next_width_px) - float(flow_fit_backfill_monotonic_slack_px):
            break
        backfilled_positions.insert(0, int(candidate_position))
        next_retained_position = int(candidate_position)
    return backfilled_positions


def _local_interpolation_deviation_candidates(feature_rows: list[dict], positions: list[int]):
    candidates = []
    for offset in range(1, len(positions) - 1):
        left_row = feature_rows[int(positions[offset - 1])]
        center_row = feature_rows[int(positions[offset])]
        right_row = feature_rows[int(positions[offset + 1])]
        left_x = _time_axis_value(left_row, allow_flash_fallback=False)
        center_x = _time_axis_value(center_row, allow_flash_fallback=False)
        right_x = _time_axis_value(right_row, allow_flash_fallback=False)
        left_y = _float_or_none(left_row.get("total_visible_volume_nl"))
        center_y = _float_or_none(center_row.get("total_visible_volume_nl"))
        right_y = _float_or_none(right_row.get("total_visible_volume_nl"))
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
            (float(center_x) - float(left_x))
            / (float(right_x) - float(left_x))
        ) * (float(right_y) - float(left_y))
        deviation_nl = float(center_y - expected_y)
        candidates.append(
            {
                "offset": int(offset),
                "position": int(positions[offset]),
                "capture_index": _int_or_none(center_row.get("capture_index")),
                "delay_from_emergence_us": _int_or_none(center_row.get("delay_from_emergence_us")),
                "local_deviation_nl": deviation_nl,
                "abs_local_deviation_nl": float(abs(deviation_nl)),
            }
        )
    return candidates


def _maybe_prune_flow_fit_outlier(
    feature_rows: list[dict],
    flow_fit_positions: list[int],
    *,
    min_steady_frames: int,
):
    if len(flow_fit_positions) <= int(min_steady_frames):
        return {
            "positions": list(flow_fit_positions),
            "outlier_prune_status": "kept_min_points_only",
            "dropped_outlier_position": None,
            "dropped_outlier_capture_index": None,
            "dropped_outlier_delay_from_emergence_us": None,
            "dropped_outlier_local_deviation_nl": None,
        }

    deviation_candidates = _local_interpolation_deviation_candidates(
        feature_rows,
        flow_fit_positions,
    )
    if not deviation_candidates:
        return {
            "positions": list(flow_fit_positions),
            "outlier_prune_status": "kept_no_interior_candidates",
            "dropped_outlier_position": None,
            "dropped_outlier_capture_index": None,
            "dropped_outlier_delay_from_emergence_us": None,
            "dropped_outlier_local_deviation_nl": None,
        }

    abs_deviations = np.asarray(
        [candidate["abs_local_deviation_nl"] for candidate in deviation_candidates],
        dtype=float,
    )
    median_abs_deviation = float(np.median(abs_deviations))
    local_deviation_mad = float(np.median(np.abs(abs_deviations - median_abs_deviation)))
    deviation_threshold_nl = float(max(0.75, 4.0 * float(local_deviation_mad)))
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
            "positions": list(flow_fit_positions),
            "outlier_prune_status": "kept_below_local_deviation_threshold",
            "dropped_outlier_position": None,
            "dropped_outlier_capture_index": None,
            "dropped_outlier_delay_from_emergence_us": None,
            "dropped_outlier_local_deviation_nl": None,
        }
    if (
        float(second_largest_abs_deviation_nl) > 0.0
        and float(primary_candidate["abs_local_deviation_nl"])
        < (1.5 * float(second_largest_abs_deviation_nl))
    ):
        return {
            "positions": list(flow_fit_positions),
            "outlier_prune_status": "kept_not_unique_enough",
            "dropped_outlier_position": None,
            "dropped_outlier_capture_index": None,
            "dropped_outlier_delay_from_emergence_us": None,
            "dropped_outlier_local_deviation_nl": None,
        }

    pruned_positions = [
        int(position)
        for position in flow_fit_positions
        if int(position) != int(primary_candidate["position"])
    ]
    if len(pruned_positions) < int(min_steady_frames):
        return {
            "positions": list(flow_fit_positions),
            "outlier_prune_status": "kept_prune_would_break_min_points",
            "dropped_outlier_position": None,
            "dropped_outlier_capture_index": None,
            "dropped_outlier_delay_from_emergence_us": None,
            "dropped_outlier_local_deviation_nl": None,
        }

    base_metrics = _fit_window_metrics(
        [feature_rows[int(position)] for position in flow_fit_positions]
    )
    pruned_metrics = _fit_window_metrics(
        [feature_rows[int(position)] for position in pruned_positions]
    )
    if (
        base_metrics is None
        or pruned_metrics is None
        or _float_or_none(base_metrics.get("steady_fit_max_abs_residual_nl")) in (None, 0.0)
    ):
        return {
            "positions": list(flow_fit_positions),
            "outlier_prune_status": "kept_prune_fit_invalid",
            "dropped_outlier_position": None,
            "dropped_outlier_capture_index": None,
            "dropped_outlier_delay_from_emergence_us": None,
            "dropped_outlier_local_deviation_nl": None,
        }

    improvement_fraction = float(
        (
            float(base_metrics["steady_fit_max_abs_residual_nl"])
            - float(pruned_metrics["steady_fit_max_abs_residual_nl"])
        )
        / float(base_metrics["steady_fit_max_abs_residual_nl"])
    )
    if improvement_fraction < 0.20:
        return {
            "positions": list(flow_fit_positions),
            "outlier_prune_status": "kept_prune_gain_below_threshold",
            "dropped_outlier_position": None,
            "dropped_outlier_capture_index": None,
            "dropped_outlier_delay_from_emergence_us": None,
            "dropped_outlier_local_deviation_nl": None,
        }

    return {
        "positions": pruned_positions,
        "outlier_prune_status": "dropped_isolated_point",
        "dropped_outlier_position": int(primary_candidate["position"]),
        "dropped_outlier_capture_index": _int_or_none(
            primary_candidate.get("capture_index")
        ),
        "dropped_outlier_delay_from_emergence_us": _int_or_none(
            primary_candidate.get("delay_from_emergence_us")
        ),
        "dropped_outlier_local_deviation_nl": float(
            primary_candidate["local_deviation_nl"]
        ),
    }


def _recompute_steady_fit_from_feature_rows(
    feature_rows: list[dict],
    *,
    first_untrusted_capture_index: int | None,
    exclude_last_trusted_frames: int,
    min_steady_frames: int,
    steady_width_tol_frac: float,
    steady_width_tol_px: float,
    flow_fit_backfill_max_frames: int = 3,
    flow_fit_backfill_width_delta_px: float = 8.0,
    flow_fit_backfill_monotonic_slack_px: float = 0.75,
    steady_fit_r2_min: float = 0.985,
    steady_fit_nrmse_max: float = 0.03,
):
    excluded_tail_positions = _excluded_tail_trusted_positions(
        feature_rows,
        first_untrusted_capture_index=first_untrusted_capture_index,
        exclude_last_trusted_frames=int(exclude_last_trusted_frames),
    )
    excluded_tail_position_set = set(int(position) for position in excluded_tail_positions)
    eligible_positions = [
        position
        for position, row in enumerate(feature_rows)
        if bool(row.get("steady_candidate")) and int(position) not in excluded_tail_position_set
    ]

    base_result = {
        "steady_fit_mode": "recompute",
        "steady_fit_status": "unresolved",
        "positions": [],
        "plateau_positions": [],
        "flow_fit_positions": [],
        "steady_capture_indices": [],
        "plateau_capture_indices": [],
        "flow_fit_capture_indices": [],
        "steady_start_capture_index": None,
        "steady_end_capture_index": None,
        "plateau_point_count": 0,
        "flow_fit_start_capture_index": None,
        "flow_fit_end_capture_index": None,
        "flow_fit_point_count": 0,
        "flow_fit_eligible_point_count": 0,
        "flow_fit_backfill_point_count": 0,
        "flow_fit_outlier_prune_status": "unresolved_no_plateau_seed",
        "flow_fit_dropped_outlier_capture_index": None,
        "flow_fit_dropped_outlier_delay_from_emergence_us": None,
        "flow_fit_dropped_outlier_local_deviation_nl": None,
        "steady_rate_nl_per_us": None,
        "steady_intercept_nl": None,
        "steady_r2": None,
        "steady_nrmse": None,
        "steady_width_plateau_px": None,
        "steady_width_span_px": None,
        "steady_width_tolerance_px": None,
        "steady_fit_candidate_window_count": 0,
        "steady_fit_selection_score": None,
        "steady_fit_exclude_last_trusted_frames": int(exclude_last_trusted_frames),
        "steady_fit_excluded_tail_trusted_frame_count": int(len(excluded_tail_positions)),
        "excluded_tail_trusted_capture_indices": [
            _int_or_none(feature_rows[int(position)].get("capture_index"))
            for position in excluded_tail_positions
            if _int_or_none(feature_rows[int(position)].get("capture_index")) is not None
        ],
        "steady_fit_first_last_residual_delta_nl": None,
        "steady_fit_max_abs_residual_nl": None,
        "steady_fit_residual_trend_nl_per_us": None,
    }
    candidate_window_count = 0
    plateau_seed = None
    selected_block = None
    for block in _contiguous_position_blocks(feature_rows, eligible_positions):
        plateau_seed, block_candidate_count = _first_plateau_seed_in_block(
            feature_rows,
            block,
            min_steady_frames=int(min_steady_frames),
            steady_width_tol_frac=float(steady_width_tol_frac),
            steady_width_tol_px=float(steady_width_tol_px),
        )
        candidate_window_count += int(block_candidate_count)
        if plateau_seed is not None:
            selected_block = list(block)
            break

    base_result["steady_fit_candidate_window_count"] = int(candidate_window_count)
    if plateau_seed is None or not selected_block:
        return {
            **base_result,
            "steady_fit_point_count": 0,
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": "unresolved_no_steady_fit",
        }

    plateau_positions = list(plateau_seed["plateau_positions"])
    plateau_metrics = dict(plateau_seed["plateau_metrics"])
    backfilled_positions = _flow_fit_backfill_positions(
        feature_rows,
        selected_block,
        plateau_seed=plateau_seed,
        flow_fit_backfill_max_frames=int(flow_fit_backfill_max_frames),
        flow_fit_backfill_width_delta_px=float(flow_fit_backfill_width_delta_px),
        flow_fit_backfill_monotonic_slack_px=float(flow_fit_backfill_monotonic_slack_px),
    )
    flow_fit_eligible_positions = list(backfilled_positions) + list(
        selected_block[int(plateau_seed["start_offset"]) :]
    )
    pruned_flow_fit = _maybe_prune_flow_fit_outlier(
        feature_rows,
        flow_fit_eligible_positions,
        min_steady_frames=int(min_steady_frames),
    )
    flow_fit_positions = list(pruned_flow_fit["positions"])
    flow_fit_metrics = _fit_window_metrics(
        [feature_rows[int(position)] for position in flow_fit_positions]
    )
    flow_fit_meets_quality = bool(
        flow_fit_metrics is not None
        and _fit_metrics_within_quality_thresholds(
            flow_fit_metrics,
            steady_fit_r2_min=float(steady_fit_r2_min),
            steady_fit_nrmse_max=float(steady_fit_nrmse_max),
        )
    )
    if flow_fit_metrics is None or not flow_fit_meets_quality:
        flow_fit_start_row = None if not flow_fit_positions else feature_rows[int(flow_fit_positions[0])]
        flow_fit_end_row = None if not flow_fit_positions else feature_rows[int(flow_fit_positions[-1])]
        attempted_fit_diagnostics = {}
        steady_fit_status = "unresolved"
        steady_rate_confidence_status = "unresolved_no_steady_fit"
        if flow_fit_metrics is not None:
            attempted_fit_diagnostics = {
                "steady_r2": flow_fit_metrics.get("steady_r2"),
                "steady_nrmse": flow_fit_metrics.get("steady_nrmse"),
                "steady_fit_first_last_residual_delta_nl": flow_fit_metrics.get(
                    "steady_fit_first_last_residual_delta_nl"
                ),
                "steady_fit_max_abs_residual_nl": flow_fit_metrics.get(
                    "steady_fit_max_abs_residual_nl"
                ),
                "steady_fit_residual_trend_nl_per_us": flow_fit_metrics.get(
                    "steady_fit_residual_trend_nl_per_us"
                ),
            }
            steady_fit_status = "unresolved_quality_thresholds"
            steady_rate_confidence_status = "unresolved_quality_thresholds"
        return {
            **base_result,
            **attempted_fit_diagnostics,
            "steady_fit_status": steady_fit_status,
            "plateau_positions": plateau_positions,
            "positions": plateau_positions,
            "plateau_capture_indices": [
                _int_or_none(feature_rows[int(position)].get("capture_index"))
                for position in plateau_positions
                if _int_or_none(feature_rows[int(position)].get("capture_index")) is not None
            ],
            "steady_capture_indices": [
                _int_or_none(feature_rows[int(position)].get("capture_index"))
                for position in plateau_positions
                if _int_or_none(feature_rows[int(position)].get("capture_index")) is not None
            ],
            "plateau_point_count": int(len(plateau_positions)),
            "flow_fit_positions": flow_fit_positions,
            "flow_fit_start_capture_index": None
            if flow_fit_start_row is None
            else _int_or_none(flow_fit_start_row.get("capture_index")),
            "flow_fit_end_capture_index": None
            if flow_fit_end_row is None
            else _int_or_none(flow_fit_end_row.get("capture_index")),
            "flow_fit_capture_indices": [
                _int_or_none(feature_rows[int(position)].get("capture_index"))
                for position in flow_fit_positions
                if _int_or_none(feature_rows[int(position)].get("capture_index")) is not None
            ],
            "flow_fit_eligible_point_count": int(len(flow_fit_eligible_positions)),
            "flow_fit_point_count": int(len(flow_fit_positions)),
            "flow_fit_backfill_point_count": int(len(backfilled_positions)),
            "flow_fit_outlier_prune_status": pruned_flow_fit["outlier_prune_status"],
            "flow_fit_dropped_outlier_capture_index": pruned_flow_fit["dropped_outlier_capture_index"],
            "flow_fit_dropped_outlier_delay_from_emergence_us": pruned_flow_fit[
                "dropped_outlier_delay_from_emergence_us"
            ],
            "flow_fit_dropped_outlier_local_deviation_nl": pruned_flow_fit[
                "dropped_outlier_local_deviation_nl"
            ],
            "steady_fit_point_count": int(len(flow_fit_positions)),
            "steady_width_plateau_px": plateau_metrics.get("steady_width_plateau_px"),
            "steady_width_span_px": plateau_metrics.get("steady_width_span_px"),
            "steady_width_tolerance_px": plateau_metrics.get("steady_width_tolerance_px"),
            "steady_rate_nl_per_us": None,
            "steady_intercept_nl": None,
            "steady_rate_ci95_low_nl_per_us": None,
            "steady_rate_ci95_high_nl_per_us": None,
            "steady_rate_ci95_relative_width": None,
            "steady_rate_ci95_contains_central": None,
            "steady_rate_confidence_status": steady_rate_confidence_status,
        }

    plateau_start_row = feature_rows[int(plateau_positions[0])]
    plateau_end_row = feature_rows[int(plateau_positions[-1])]
    flow_fit_start_row = feature_rows[int(flow_fit_positions[0])]
    flow_fit_end_row = feature_rows[int(flow_fit_positions[-1])]
    recomputed_fit = {
        **dict(flow_fit_metrics),
        "steady_fit_status": "ok",
        "positions": plateau_positions,
        "plateau_positions": plateau_positions,
        "flow_fit_positions": flow_fit_positions,
        "steady_capture_indices": [
            _int_or_none(feature_rows[int(position)].get("capture_index"))
            for position in plateau_positions
            if _int_or_none(feature_rows[int(position)].get("capture_index")) is not None
        ],
        "plateau_capture_indices": [
            _int_or_none(feature_rows[int(position)].get("capture_index"))
            for position in plateau_positions
            if _int_or_none(feature_rows[int(position)].get("capture_index")) is not None
        ],
        "flow_fit_capture_indices": [
            _int_or_none(feature_rows[int(position)].get("capture_index"))
            for position in flow_fit_positions
            if _int_or_none(feature_rows[int(position)].get("capture_index")) is not None
        ],
        "steady_start_capture_index": _int_or_none(plateau_start_row.get("capture_index")),
        "steady_end_capture_index": _int_or_none(plateau_end_row.get("capture_index")),
        "plateau_point_count": int(len(plateau_positions)),
        "flow_fit_start_capture_index": _int_or_none(flow_fit_start_row.get("capture_index")),
        "flow_fit_end_capture_index": _int_or_none(flow_fit_end_row.get("capture_index")),
        "flow_fit_point_count": int(len(flow_fit_positions)),
        "flow_fit_eligible_point_count": int(len(flow_fit_eligible_positions)),
        "flow_fit_backfill_point_count": int(len(backfilled_positions)),
        "flow_fit_outlier_prune_status": pruned_flow_fit["outlier_prune_status"],
        "flow_fit_dropped_outlier_capture_index": pruned_flow_fit["dropped_outlier_capture_index"],
        "flow_fit_dropped_outlier_delay_from_emergence_us": pruned_flow_fit[
            "dropped_outlier_delay_from_emergence_us"
        ],
        "flow_fit_dropped_outlier_local_deviation_nl": pruned_flow_fit[
            "dropped_outlier_local_deviation_nl"
        ],
        "steady_width_plateau_px": plateau_metrics.get("steady_width_plateau_px"),
        "steady_width_span_px": plateau_metrics.get("steady_width_span_px"),
        "steady_width_tolerance_px": plateau_metrics.get("steady_width_tolerance_px"),
        "steady_fit_selection_score": None,
    }
    steady_points = _steady_fit_time_volume_points(feature_rows, recomputed_fit)
    confidence = _steady_fit_confidence_from_points(
        steady_points,
        central_rate=_float_or_none(recomputed_fit.get("steady_rate_nl_per_us")),
    )
    return {
        **base_result,
        **recomputed_fit,
        **confidence,
    }


def _steady_fit_time_volume_points(feature_rows: list[dict], steady_fit: dict):
    if _clean_text(steady_fit.get("steady_fit_status")) != "ok":
        return []
    points = []
    for position in list(steady_fit.get("flow_fit_positions") or steady_fit.get("positions") or []):
        if int(position) < 0 or int(position) >= len(feature_rows):
            continue
        row = feature_rows[int(position)]
        time_us = _time_axis_value(row, allow_flash_fallback=False)
        volume_nl = _float_or_none(row.get("total_visible_volume_nl"))
        if time_us is None or volume_nl is None:
            continue
        points.append((float(time_us), float(volume_nl)))
    return points


def _steady_fit_residual_points(feature_rows: list[dict], steady_fit: dict):
    central_rate = _float_or_none(steady_fit.get("steady_rate_nl_per_us"))
    intercept_nl = _float_or_none(steady_fit.get("steady_intercept_nl"))
    if central_rate is None or intercept_nl is None:
        return []
    points = []
    for time_us, volume_nl in _steady_fit_time_volume_points(feature_rows, steady_fit):
        predicted_nl = float(intercept_nl) + (float(central_rate) * float(time_us))
        points.append((float(time_us), float(volume_nl - predicted_nl)))
    return points


def _steady_fit_ci_band_points(
    feature_rows: list[dict],
    steady_fit: dict,
    *,
    plot_x_values: list[float] | None = None,
):
    central_rate = _float_or_none(steady_fit.get("steady_rate_nl_per_us"))
    intercept_nl = _float_or_none(steady_fit.get("steady_intercept_nl"))
    rate_low = _float_or_none(steady_fit.get("steady_rate_ci95_low_nl_per_us"))
    rate_high = _float_or_none(steady_fit.get("steady_rate_ci95_high_nl_per_us"))
    steady_points = _steady_fit_time_volume_points(feature_rows, steady_fit)
    if (
        central_rate is None
        or intercept_nl is None
        or rate_low is None
        or rate_high is None
        or not steady_points
    ):
        return []

    x_candidates = list(plot_x_values or [])
    if not x_candidates:
        x_candidates = [time_us for time_us, _volume_nl in steady_points]
    x_candidates = sorted(
        {
            float(x_value)
            for x_value in x_candidates
            if x_value is not None and math.isfinite(float(x_value))
        }
    )
    if not x_candidates:
        return []

    steady_x_values = [time_us for time_us, _volume_nl in steady_points]
    x_min = float(min(steady_x_values))
    x_max = float(max(x_candidates))
    if float(x_max) < float(x_min):
        return []

    anchor_x = float(np.median(np.asarray(steady_x_values, dtype=float)))
    anchor_y = float(intercept_nl) + (float(central_rate) * float(anchor_x))

    ci_points = []
    for x_value in x_candidates:
        if float(x_value) < float(x_min) or float(x_value) > float(x_max):
            continue
        y_low = float(anchor_y) + (float(rate_low) * float(x_value - anchor_x))
        y_high = float(anchor_y) + (float(rate_high) * float(x_value - anchor_x))
        ci_points.append((float(x_value), float(min(y_low, y_high)), float(max(y_low, y_high))))
    return ci_points


def _smoothed_width_points_by_delay(feature_rows: list[dict]):
    points = []
    for row in feature_rows:
        delay_us = _int_or_none(row.get("delay_from_emergence_us"))
        width_px = _float_or_none(row.get("attached_near_nozzle_width_smoothed_px"))
        if delay_us is None or width_px is None:
            continue
        if points and float(delay_us) <= float(points[-1][0]):
            if float(delay_us) == float(points[-1][0]):
                points[-1] = (float(delay_us), float(width_px))
            continue
        points.append((float(delay_us), float(width_px)))
    return points


def _interpolate_series_value(points: list[tuple[float, float]], x_value: float | None):
    x_value_float = _float_or_none(x_value)
    if x_value_float is None or not points:
        return None
    if float(x_value_float) < float(points[0][0]) or float(x_value_float) > float(points[-1][0]):
        return None
    if float(x_value_float) == float(points[0][0]):
        return float(points[0][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if float(x0) <= float(x_value_float) <= float(x1):
            if float(x1) == float(x0):
                return float(y1)
            fraction = float((float(x_value_float) - float(x0)) / (float(x1) - float(x0)))
            return float(float(y0) + (fraction * (float(y1) - float(y0))))
    return None


def _normalized_width_shrink_rate_points(feature_rows: list[dict], steady_fit: dict):
    plateau_px = _float_or_none(steady_fit.get("steady_width_plateau_px"))
    if plateau_px is None or float(plateau_px) <= 0.0:
        return []
    width_points = _smoothed_width_points_by_delay(feature_rows)
    if len(width_points) < 2:
        return []
    x_values = np.asarray([point[0] for point in width_points], dtype=float)
    y_values = np.asarray([point[1] for point in width_points], dtype=float)
    if len(x_values) < 2 or np.any(np.diff(x_values) <= 0.0):
        return []
    gradients = np.gradient(y_values, x_values)
    shrink_rates = -(gradients / float(plateau_px)) * 1000.0
    return [
        (float(delay_us), float(shrink_rate))
        for delay_us, shrink_rate in zip(x_values.tolist(), shrink_rates.tolist())
        if math.isfinite(delay_us) and math.isfinite(shrink_rate)
    ]


def _width_drop_to_threshold_fraction(
    width_px: float | None,
    steady_width_plateau_px: float | None,
    tail_width_threshold_px: float | None,
):
    width_px_float = _float_or_none(width_px)
    steady_width_plateau_px_float = _float_or_none(steady_width_plateau_px)
    tail_width_threshold_px_float = _float_or_none(tail_width_threshold_px)
    if (
        width_px_float is None
        or steady_width_plateau_px_float is None
        or tail_width_threshold_px_float is None
        or float(steady_width_plateau_px_float) == float(tail_width_threshold_px_float)
    ):
        return None
    return float(
        (float(steady_width_plateau_px_float) - float(width_px_float))
        / (float(steady_width_plateau_px_float) - float(tail_width_threshold_px_float))
    )


def _width_drop_fraction(width_px: float | None, steady_width_plateau_px: float | None):
    width_px_float = _float_or_none(width_px)
    steady_width_plateau_px_float = _float_or_none(steady_width_plateau_px)
    if (
        width_px_float is None
        or steady_width_plateau_px_float is None
        or float(steady_width_plateau_px_float) == 0.0
    ):
        return None
    return float(
        (float(steady_width_plateau_px_float) - float(width_px_float))
        / float(steady_width_plateau_px_float)
    )


def _legacy_tail_anchor_from_tail_onset(tail_onset: dict):
    tail_start_capture_index = _int_or_none(tail_onset.get("tail_start_capture_index"))
    tail_start_position = _int_or_none(tail_onset.get("tail_start_position"))
    if tail_start_capture_index is not None or tail_start_position is not None:
        return {
            "capture_index": tail_start_capture_index,
            "delay_from_emergence_us": _int_or_none(
                tail_onset.get("tail_start_delay_from_emergence_us")
            ),
            "position": tail_start_position,
        }
    selection_mode = _clean_text(tail_onset.get("tail_start_selection_mode"))
    if selection_mode == "shoulder_adjusted":
        return {
            "capture_index": _int_or_none(tail_onset.get("tail_shoulder_end_capture_index")),
            "delay_from_emergence_us": _int_or_none(
                tail_onset.get("tail_shoulder_end_delay_from_emergence_us")
            ),
            "position": _int_or_none(tail_onset.get("tail_shoulder_end_position")),
        }
    direct_capture_index = _int_or_none(tail_onset.get("direct_final_tail_start_capture_index"))
    direct_position = _int_or_none(tail_onset.get("direct_final_tail_start_position"))
    if direct_capture_index is not None or direct_position is not None:
        return {
            "capture_index": direct_capture_index,
            "delay_from_emergence_us": _int_or_none(
                tail_onset.get("direct_final_tail_start_delay_from_emergence_us")
            ),
            "position": direct_position,
        }
    return {
        "capture_index": _int_or_none(tail_onset.get("tail_start_capture_index")),
        "delay_from_emergence_us": _int_or_none(
            tail_onset.get("tail_start_delay_from_emergence_us")
        ),
        "position": _int_or_none(tail_onset.get("tail_start_position")),
    }


def _contiguous_valid_positions_between(
    feature_rows: list[dict],
    start_position: int | None,
    end_position: int | None,
):
    start_position = _int_or_none(start_position)
    end_position = _int_or_none(end_position)
    if (
        start_position is None
        or end_position is None
        or int(start_position) < 0
        or int(end_position) >= len(feature_rows)
        or int(start_position) > int(end_position)
    ):
        return []

    candidate_positions = []
    previous_capture_index = None
    for position in range(int(start_position), int(end_position) + 1):
        row = feature_rows[int(position)]
        capture_index = _int_or_none(row.get("capture_index"))
        delay_us = _time_axis_value(row, allow_flash_fallback=False)
        width_px = _float_or_none(row.get("attached_near_nozzle_width_smoothed_px"))
        if capture_index is None or delay_us is None or width_px is None:
            return []
        if previous_capture_index is not None and int(capture_index) != int(previous_capture_index) + 1:
            return []
        candidate_positions.append(int(position))
        previous_capture_index = int(capture_index)
    return candidate_positions


def _tail_descriptor_context(feature_rows: list[dict], steady_fit: dict, tail_onset: dict):
    plateau_px = _float_or_none(steady_fit.get("steady_width_plateau_px"))
    threshold_px = _float_or_none(tail_onset.get("tail_width_threshold_px"))
    width_points = _smoothed_width_points_by_delay(feature_rows)
    shrink_rate_points = _normalized_width_shrink_rate_points(feature_rows, steady_fit)
    steady_end_row = _row_by_capture_index(
        feature_rows,
        _int_or_none(steady_fit.get("steady_end_capture_index")),
    )
    steady_end_delay_us = None if steady_end_row is None else _time_axis_value(
        steady_end_row,
        allow_flash_fallback=False,
    )
    tail_shrink_rate_points = (
        [
            (float(delay_us), float(shrink_rate))
            for delay_us, shrink_rate in shrink_rate_points
            if steady_end_delay_us is not None and float(delay_us) > float(steady_end_delay_us)
        ]
        if steady_end_delay_us is not None
        else []
    )
    tail_peak_delay_us = None
    tail_peak_shrink_rate_norm_per_ms = None
    if tail_shrink_rate_points:
        tail_peak_delay_us, tail_peak_shrink_rate_norm_per_ms = max(
            tail_shrink_rate_points,
            key=lambda point: float(point[1]),
        )
    return {
        "steady_width_plateau_px": plateau_px,
        "tail_width_threshold_px": threshold_px,
        "width_points": width_points,
        "shrink_rate_points": shrink_rate_points,
        "steady_end_delay_us": None if steady_end_delay_us is None else float(steady_end_delay_us),
        "tail_peak_shrink_rate_delay_us": None
        if tail_peak_delay_us is None
        else float(tail_peak_delay_us),
        "tail_peak_shrink_rate_norm_per_ms": None
        if tail_peak_shrink_rate_norm_per_ms is None
        else float(tail_peak_shrink_rate_norm_per_ms),
    }


def _tail_candidate_descriptor_row(
    feature_rows: list[dict],
    position: int,
    *,
    candidate_window_kind: str,
    context: dict,
    legacy_capture_index: int | None,
):
    row = feature_rows[int(position)]
    capture_index = _int_or_none(row.get("capture_index"))
    delay_from_emergence_us = _time_axis_value(row, allow_flash_fallback=False)
    width_px = _float_or_none(row.get("attached_near_nozzle_width_smoothed_px"))
    drop_frac = _width_drop_fraction(
        width_px,
        context.get("steady_width_plateau_px"),
    )
    drop_to_threshold_frac = _width_drop_to_threshold_fraction(
        width_px,
        context.get("steady_width_plateau_px"),
        context.get("tail_width_threshold_px"),
    )
    shrink_rate_norm_per_ms = None
    if delay_from_emergence_us is not None:
        shrink_rate_norm_per_ms = _interpolate_series_value(
            context.get("shrink_rate_points") or [],
            float(delay_from_emergence_us),
        )
    tail_peak_shrink_rate_norm_per_ms = _float_or_none(
        context.get("tail_peak_shrink_rate_norm_per_ms")
    )
    shrink_rate_ratio = None
    if (
        shrink_rate_norm_per_ms is not None
        and tail_peak_shrink_rate_norm_per_ms is not None
        and float(tail_peak_shrink_rate_norm_per_ms) > 0.0
    ):
        shrink_rate_ratio = float(
            float(shrink_rate_norm_per_ms) / float(tail_peak_shrink_rate_norm_per_ms)
        )
    tail_peak_lead_us = None
    tail_peak_delay_us = _float_or_none(context.get("tail_peak_shrink_rate_delay_us"))
    if delay_from_emergence_us is not None and tail_peak_delay_us is not None:
        tail_peak_lead_us = float(float(tail_peak_delay_us) - float(delay_from_emergence_us))
    return {
        "candidate_window_kind": candidate_window_kind,
        "position": int(position),
        "capture_index": capture_index,
        "delay_from_emergence_us": None
        if delay_from_emergence_us is None
        else float(delay_from_emergence_us),
        "width_px": width_px,
        "drop_frac": drop_frac,
        "drop_to_threshold_frac": drop_to_threshold_frac,
        "shrink_rate_norm_per_ms": shrink_rate_norm_per_ms,
        "shrink_rate_ratio": shrink_rate_ratio,
        "tail_peak_lead_us": tail_peak_lead_us,
        "score_drop_term": None,
        "score_peak_lead_term": None,
        "score_shrink_rate_term": None,
        "score_total": None,
        "within_drop_band": None,
        "within_peak_lead_band": None,
        "within_shrink_rate_band": None,
        "within_unified_band": None,
        "selection_reason": None,
        "is_selected": False,
        "is_legacy_anchor": bool(
            capture_index is not None
            and legacy_capture_index is not None
            and int(capture_index) == int(legacy_capture_index)
        ),
    }


def _tail_scoring_targets(
    tail_start_selection_mode: str,
    *,
    tail_direct_target_drop_to_threshold_frac: float,
    tail_direct_target_peak_lead_us: float,
    tail_direct_target_shrink_rate_ratio: float,
    tail_shoulder_target_drop_to_threshold_frac: float,
    tail_shoulder_target_peak_lead_us: float,
    tail_shoulder_target_shrink_rate_ratio: float,
):
    if _clean_text(tail_start_selection_mode) == "shoulder_adjusted":
        return {
            "target_drop_to_threshold_frac": float(tail_shoulder_target_drop_to_threshold_frac),
            "target_peak_lead_us": float(tail_shoulder_target_peak_lead_us),
            "target_shrink_rate_ratio": float(tail_shoulder_target_shrink_rate_ratio),
        }
    return {
        "target_drop_to_threshold_frac": float(tail_direct_target_drop_to_threshold_frac),
        "target_peak_lead_us": float(tail_direct_target_peak_lead_us),
        "target_shrink_rate_ratio": float(tail_direct_target_shrink_rate_ratio),
    }


def _apply_tail_descriptor_score(
    candidate_rows: list[dict],
    *,
    target_drop_to_threshold_frac: float,
    target_peak_lead_us: float,
    target_shrink_rate_ratio: float,
    drop_weight: float,
    peak_weight: float,
    shrink_weight: float,
    drop_scale: float,
    peak_lead_scale_us: float,
    shrink_rate_scale: float,
):
    scored_rows = []
    for candidate_row in candidate_rows:
        drop_to_threshold_frac = _float_or_none(candidate_row.get("drop_to_threshold_frac"))
        tail_peak_lead_us = _float_or_none(candidate_row.get("tail_peak_lead_us"))
        shrink_rate_ratio = _float_or_none(candidate_row.get("shrink_rate_ratio"))
        if (
            drop_to_threshold_frac is None
            or tail_peak_lead_us is None
            or shrink_rate_ratio is None
            or float(drop_scale) <= 0.0
            or float(peak_lead_scale_us) <= 0.0
            or float(shrink_rate_scale) <= 0.0
        ):
            continue
        score_drop_term = float(
            float(drop_weight)
            * abs(float(drop_to_threshold_frac) - float(target_drop_to_threshold_frac))
            / float(drop_scale)
        )
        score_peak_lead_term = float(
            float(peak_weight)
            * abs(float(tail_peak_lead_us) - float(target_peak_lead_us))
            / float(peak_lead_scale_us)
        )
        score_shrink_rate_term = float(
            float(shrink_weight)
            * abs(float(shrink_rate_ratio) - float(target_shrink_rate_ratio))
            / float(shrink_rate_scale)
        )
        candidate_row["score_drop_term"] = score_drop_term
        candidate_row["score_peak_lead_term"] = score_peak_lead_term
        candidate_row["score_shrink_rate_term"] = score_shrink_rate_term
        candidate_row["score_total"] = float(
            float(score_drop_term)
            + float(score_peak_lead_term)
            + float(score_shrink_rate_term)
        )
        scored_rows.append(candidate_row)
    return scored_rows


def _select_best_tail_score_candidate(candidate_rows: list[dict]):
    scored_rows = [
        dict(candidate_row)
        for candidate_row in candidate_rows
        if _float_or_none(candidate_row.get("score_total")) is not None
        and _int_or_none(candidate_row.get("capture_index")) is not None
        and _int_or_none(candidate_row.get("position")) is not None
    ]
    if not scored_rows:
        return None
    return min(
        scored_rows,
        key=lambda candidate_row: (
            float(candidate_row["score_total"]),
            int(candidate_row["capture_index"]),
            int(candidate_row["position"]),
        ),
    )


def _apply_tail_descriptor_band(
    candidate_rows: list[dict],
    *,
    drop_min: float,
    drop_max: float,
    peak_lead_min_us: float,
    peak_lead_max_us: float,
    shrink_rate_ratio_min: float,
    shrink_rate_ratio_max: float,
):
    band_rows = []
    for candidate_row in candidate_rows:
        drop_to_threshold_frac = _float_or_none(candidate_row.get("drop_to_threshold_frac"))
        tail_peak_lead_us = _float_or_none(candidate_row.get("tail_peak_lead_us"))
        shrink_rate_ratio = _float_or_none(candidate_row.get("shrink_rate_ratio"))
        within_drop_band = bool(
            drop_to_threshold_frac is not None
            and float(drop_min) <= float(drop_to_threshold_frac) <= float(drop_max)
        )
        within_peak_lead_band = bool(
            tail_peak_lead_us is not None
            and float(peak_lead_min_us) <= float(tail_peak_lead_us) <= float(peak_lead_max_us)
        )
        within_shrink_rate_band = bool(
            shrink_rate_ratio is not None
            and float(shrink_rate_ratio_min)
            <= float(shrink_rate_ratio)
            <= float(shrink_rate_ratio_max)
        )
        candidate_row["within_drop_band"] = within_drop_band
        candidate_row["within_peak_lead_band"] = within_peak_lead_band
        candidate_row["within_shrink_rate_band"] = within_shrink_rate_band
        candidate_row["within_unified_band"] = bool(
            within_drop_band and within_peak_lead_band and within_shrink_rate_band
        )
        band_rows.append(candidate_row)
    return band_rows


def _select_earliest_in_band_tail_candidate(candidate_rows: list[dict]):
    in_band_rows = [
        dict(candidate_row)
        for candidate_row in candidate_rows
        if bool(candidate_row.get("within_unified_band"))
        and _int_or_none(candidate_row.get("capture_index")) is not None
        and _int_or_none(candidate_row.get("position")) is not None
    ]
    if not in_band_rows:
        return None
    return min(
        in_band_rows,
        key=lambda candidate_row: (
            int(candidate_row["capture_index"]),
            int(candidate_row["position"]),
        ),
    )


def _refine_tail_onset_for_review(
    feature_rows: list[dict],
    steady_fit: dict,
    tail_onset: dict,
    *,
    first_untrusted_capture_index: int | None,
    tail_start_mode: str,
    tail_direct_target_drop_to_threshold_frac: float,
    tail_direct_target_peak_lead_us: float,
    tail_direct_target_shrink_rate_ratio: float,
    tail_shoulder_target_drop_to_threshold_frac: float,
    tail_shoulder_target_peak_lead_us: float,
    tail_shoulder_target_shrink_rate_ratio: float,
    tail_score_drop_weight: float,
    tail_score_peak_lead_weight: float,
    tail_score_shrink_rate_weight: float,
    tail_score_drop_scale: float,
    tail_score_peak_lead_scale_us: float,
    tail_score_shrink_rate_scale: float,
    tail_unified_band_drop_min: float,
    tail_unified_band_drop_max: float,
    tail_unified_band_peak_lead_min_us: float,
    tail_unified_band_peak_lead_max_us: float,
    tail_unified_band_shrink_rate_ratio_min: float,
    tail_unified_band_shrink_rate_ratio_max: float,
    tail_unified_target_drop_to_threshold_frac: float,
    tail_unified_target_peak_lead_us: float,
    tail_unified_target_shrink_rate_ratio: float,
):
    refined_tail_onset = dict(tail_onset)
    refined_tail_onset["tail_start_refinement_mode"] = TAIL_START_REFINEMENT_LEGACY
    refined_tail_onset["tail_start_band_selection_status"] = None
    refined_tail_onset["tail_in_band_candidate_count"] = 0
    refined_tail_onset["tail_start_score"] = None
    refined_tail_onset["tail_score_candidate_count"] = 0
    refined_tail_onset["tail_score_window_start_capture_index"] = None
    refined_tail_onset["tail_score_window_end_capture_index"] = None
    refined_tail_onset["tail_start_drop_frac"] = None
    refined_tail_onset["tail_start_drop_to_threshold_frac"] = None
    refined_tail_onset["tail_start_shrink_rate_norm_per_ms"] = None
    refined_tail_onset["tail_start_shrink_rate_ratio"] = None
    refined_tail_onset["tail_peak_shrink_rate_norm_per_ms"] = None
    refined_tail_onset["tail_peak_shrink_rate_delay_us"] = None
    refined_tail_onset["tail_start_to_tail_peak_delta_us"] = None

    legacy_anchor = _legacy_tail_anchor_from_tail_onset(refined_tail_onset)
    context = _tail_descriptor_context(feature_rows, steady_fit, refined_tail_onset)
    refined_tail_onset["tail_peak_shrink_rate_norm_per_ms"] = context.get(
        "tail_peak_shrink_rate_norm_per_ms"
    )
    refined_tail_onset["tail_peak_shrink_rate_delay_us"] = context.get(
        "tail_peak_shrink_rate_delay_us"
    )

    selection_mode = _clean_text(refined_tail_onset.get("tail_start_selection_mode"))
    tail_start_mode = _clean_text(tail_start_mode)
    candidate_window_kind = None
    candidate_start_position = None
    candidate_end_position = None
    if tail_start_mode == TAIL_START_MODE_DESCRIPTOR_UNIFIED:
        candidate_window_kind = "descriptor_unified"
        candidate_start_position = _int_or_none(
            refined_tail_onset.get("preliminary_tail_start_position")
        )
        if candidate_start_position is None:
            candidate_start_position = _int_or_none(
                refined_tail_onset.get("direct_final_tail_start_position")
            )
        candidate_end_position = _int_or_none(
            refined_tail_onset.get("tail_confirmation_position")
        )
    elif selection_mode == "shoulder_adjusted":
        candidate_window_kind = "shoulder_adjusted"
        candidate_start_position = _int_or_none(
            refined_tail_onset.get("preliminary_tail_start_position")
        )
        candidate_end_position = _int_or_none(refined_tail_onset.get("tail_start_position"))
        if candidate_end_position is None:
            candidate_end_position = _int_or_none(
                refined_tail_onset.get("tail_shoulder_end_position")
            )
    elif selection_mode == "direct_backtrack":
        candidate_window_kind = "direct_backtrack"
        candidate_start_position = _int_or_none(
            refined_tail_onset.get("direct_final_tail_start_position")
        )
        candidate_end_position = _int_or_none(refined_tail_onset.get("tail_confirmation_position"))

    candidate_positions = _contiguous_valid_positions_between(
        feature_rows,
        candidate_start_position,
        candidate_end_position,
    )
    candidate_rows = [
        _tail_candidate_descriptor_row(
            feature_rows,
            int(position),
            candidate_window_kind=str(candidate_window_kind or ""),
            context=context,
            legacy_capture_index=_int_or_none(legacy_anchor.get("capture_index")),
        )
        for position in candidate_positions
    ]
    refined_tail_onset["tail_score_candidate_count"] = int(len(candidate_rows))
    if candidate_rows:
        refined_tail_onset["tail_score_window_start_capture_index"] = _int_or_none(
            candidate_rows[0].get("capture_index")
        )
        refined_tail_onset["tail_score_window_end_capture_index"] = _int_or_none(
            candidate_rows[-1].get("capture_index")
        )

    selected_candidate = None
    if tail_start_mode == TAIL_START_MODE_DESCRIPTOR_SCORE and candidate_rows:
        targets = _tail_scoring_targets(
            selection_mode,
            tail_direct_target_drop_to_threshold_frac=float(
                tail_direct_target_drop_to_threshold_frac
            ),
            tail_direct_target_peak_lead_us=float(tail_direct_target_peak_lead_us),
            tail_direct_target_shrink_rate_ratio=float(tail_direct_target_shrink_rate_ratio),
            tail_shoulder_target_drop_to_threshold_frac=float(
                tail_shoulder_target_drop_to_threshold_frac
            ),
            tail_shoulder_target_peak_lead_us=float(tail_shoulder_target_peak_lead_us),
            tail_shoulder_target_shrink_rate_ratio=float(tail_shoulder_target_shrink_rate_ratio),
        )
        scored_rows = _apply_tail_descriptor_score(
            candidate_rows,
            target_drop_to_threshold_frac=float(targets["target_drop_to_threshold_frac"]),
            target_peak_lead_us=float(targets["target_peak_lead_us"]),
            target_shrink_rate_ratio=float(targets["target_shrink_rate_ratio"]),
            drop_weight=float(tail_score_drop_weight),
            peak_weight=float(tail_score_peak_lead_weight),
            shrink_weight=float(tail_score_shrink_rate_weight),
            drop_scale=float(tail_score_drop_scale),
            peak_lead_scale_us=float(tail_score_peak_lead_scale_us),
            shrink_rate_scale=float(tail_score_shrink_rate_scale),
        )
        selected_candidate = _select_best_tail_score_candidate(scored_rows)
    elif tail_start_mode == TAIL_START_MODE_DESCRIPTOR_UNIFIED:
        if not candidate_rows:
            refined_tail_onset["tail_start_band_selection_status"] = (
                "legacy_fallback_missing_window"
            )
        else:
            candidate_rows = _apply_tail_descriptor_band(
                candidate_rows,
                drop_min=float(tail_unified_band_drop_min),
                drop_max=float(tail_unified_band_drop_max),
                peak_lead_min_us=float(tail_unified_band_peak_lead_min_us),
                peak_lead_max_us=float(tail_unified_band_peak_lead_max_us),
                shrink_rate_ratio_min=float(tail_unified_band_shrink_rate_ratio_min),
                shrink_rate_ratio_max=float(tail_unified_band_shrink_rate_ratio_max),
            )
            refined_tail_onset["tail_in_band_candidate_count"] = int(
                sum(1 for candidate_row in candidate_rows if bool(candidate_row.get("within_unified_band")))
            )
            scored_rows = _apply_tail_descriptor_score(
                candidate_rows,
                target_drop_to_threshold_frac=float(
                    tail_unified_target_drop_to_threshold_frac
                ),
                target_peak_lead_us=float(tail_unified_target_peak_lead_us),
                target_shrink_rate_ratio=float(tail_unified_target_shrink_rate_ratio),
                drop_weight=float(tail_score_drop_weight),
                peak_weight=float(tail_score_peak_lead_weight),
                shrink_weight=float(tail_score_shrink_rate_weight),
                drop_scale=float(tail_score_drop_scale),
                peak_lead_scale_us=float(tail_score_peak_lead_scale_us),
                shrink_rate_scale=float(tail_score_shrink_rate_scale),
            )
            earliest_in_band = _select_earliest_in_band_tail_candidate(candidate_rows)
            if earliest_in_band is not None:
                selected_candidate = earliest_in_band
                refined_tail_onset["tail_start_band_selection_status"] = "earliest_in_band"
            else:
                selected_candidate = _select_best_tail_score_candidate(scored_rows)
                if selected_candidate is not None:
                    refined_tail_onset["tail_start_band_selection_status"] = (
                        "best_score_fallback"
                    )
                else:
                    refined_tail_onset["tail_start_band_selection_status"] = (
                        "legacy_fallback_missing_descriptors"
                    )

    if selected_candidate is not None:
        selected_capture_index = _int_or_none(selected_candidate.get("capture_index"))
        legacy_capture_index = _int_or_none(legacy_anchor.get("capture_index"))
        would_regress_before_fov_exit = (
            selected_capture_index is not None
            and first_untrusted_capture_index is not None
            and int(selected_capture_index) <= int(first_untrusted_capture_index)
            and legacy_capture_index is not None
            and int(legacy_capture_index) > int(first_untrusted_capture_index)
        )
        if not would_regress_before_fov_exit:
            selected_position = _int_or_none(selected_candidate.get("position"))
            selected_row = None if selected_position is None else feature_rows[int(selected_position)]
            if selected_row is not None:
                refined_tail_onset["tail_start_refinement_mode"] = (
                    TAIL_START_REFINEMENT_DESCRIPTOR_UNIFIED
                    if tail_start_mode == TAIL_START_MODE_DESCRIPTOR_UNIFIED
                    else TAIL_START_REFINEMENT_DESCRIPTOR_SCORE
                )
                refined_tail_onset["tail_start_position"] = int(selected_position)
                refined_tail_onset["tail_start_capture_index"] = _int_or_none(
                    selected_row.get("capture_index")
                )
                refined_tail_onset["tail_start_delay_from_emergence_us"] = _int_or_none(
                    selected_row.get("delay_from_emergence_us")
                )
                refined_tail_onset["tail_onset_status"] = (
                    "before_fov_exit"
                    if (
                        first_untrusted_capture_index is not None
                        and refined_tail_onset.get("tail_start_capture_index") is not None
                        and int(refined_tail_onset["tail_start_capture_index"])
                        <= int(first_untrusted_capture_index)
                    )
                    else "ok"
                )
                refined_tail_onset["tail_start_score"] = _float_or_none(
                    selected_candidate.get("score_total")
                )
        elif tail_start_mode == TAIL_START_MODE_DESCRIPTOR_UNIFIED:
            refined_tail_onset["tail_start_band_selection_status"] = (
                "legacy_fallback_missing_descriptors"
            )

    selected_position = _int_or_none(refined_tail_onset.get("tail_start_position"))
    selected_descriptor = None
    if selected_position is not None and 0 <= int(selected_position) < len(feature_rows):
        selected_descriptor = _tail_candidate_descriptor_row(
            feature_rows,
            int(selected_position),
            candidate_window_kind=str(candidate_window_kind or ""),
            context=context,
            legacy_capture_index=_int_or_none(legacy_anchor.get("capture_index")),
        )
        refined_tail_onset["tail_start_drop_frac"] = selected_descriptor.get("drop_frac")
        refined_tail_onset["tail_start_drop_to_threshold_frac"] = selected_descriptor.get(
            "drop_to_threshold_frac"
        )
        refined_tail_onset["tail_start_shrink_rate_norm_per_ms"] = selected_descriptor.get(
            "shrink_rate_norm_per_ms"
        )
        refined_tail_onset["tail_start_shrink_rate_ratio"] = selected_descriptor.get(
            "shrink_rate_ratio"
        )
        refined_tail_onset["tail_start_to_tail_peak_delta_us"] = selected_descriptor.get(
            "tail_peak_lead_us"
        )

    selected_capture_index = _int_or_none(refined_tail_onset.get("tail_start_capture_index"))
    for candidate_row in candidate_rows:
        candidate_row["is_selected"] = bool(
            selected_capture_index is not None
            and _int_or_none(candidate_row.get("capture_index")) is not None
            and int(candidate_row["capture_index"]) == int(selected_capture_index)
        )
        if bool(candidate_row.get("is_selected")):
            if tail_start_mode == TAIL_START_MODE_DESCRIPTOR_UNIFIED:
                candidate_row["selection_reason"] = (
                    refined_tail_onset.get("tail_start_band_selection_status")
                    if refined_tail_onset.get("tail_start_refinement_mode")
                    == TAIL_START_REFINEMENT_DESCRIPTOR_UNIFIED
                    else "legacy_anchor"
                )
            elif tail_start_mode == TAIL_START_MODE_DESCRIPTOR_SCORE:
                candidate_row["selection_reason"] = (
                    "best_score_fallback"
                    if refined_tail_onset.get("tail_start_refinement_mode")
                    == TAIL_START_REFINEMENT_DESCRIPTOR_SCORE
                    else "legacy_anchor"
                )
            elif bool(candidate_row.get("is_legacy_anchor")):
                candidate_row["selection_reason"] = "legacy_anchor"

    return refined_tail_onset, candidate_rows


def _build_stage5_from_phase_inputs(
    run_id: str,
    phase_input_rows: list[dict],
    *,
    steady_fit_payload: dict,
    fov_report: dict,
    trusted_visible_volume_nl: float | None,
    first_untrusted_delay_from_emergence_us: int | None,
    width_smooth_window: int,
    tail_drop_frac: float = 0.08,
    tail_persist_frames: int = 3,
    steady_fit_mode: str = "frozen",
    steady_fit_exclude_last_trusted_frames: int = 2,
    min_steady_frames: int = 8,
    steady_width_tol_frac: float = 0.08,
    steady_width_tol_px: float = 4.0,
    flow_fit_backfill_max_frames: int = 3,
    flow_fit_backfill_width_delta_px: float = 8.0,
    flow_fit_backfill_monotonic_slack_px: float = 0.75,
    tail_start_mode: str = TAIL_START_MODE_DESCRIPTOR_UNIFIED,
    tail_direct_target_drop_to_threshold_frac: float = TAIL_DIRECT_TARGET_DROP_TO_THRESHOLD_FRAC,
    tail_direct_target_peak_lead_us: float = TAIL_DIRECT_TARGET_PEAK_LEAD_US,
    tail_direct_target_shrink_rate_ratio: float = TAIL_DIRECT_TARGET_SHRINK_RATE_RATIO,
    tail_shoulder_target_drop_to_threshold_frac: float = TAIL_SHOULDER_TARGET_DROP_TO_THRESHOLD_FRAC,
    tail_shoulder_target_peak_lead_us: float = TAIL_SHOULDER_TARGET_PEAK_LEAD_US,
    tail_shoulder_target_shrink_rate_ratio: float = TAIL_SHOULDER_TARGET_SHRINK_RATE_RATIO,
    tail_score_drop_weight: float = TAIL_SCORE_DROP_WEIGHT,
    tail_score_peak_lead_weight: float = TAIL_SCORE_PEAK_LEAD_WEIGHT,
    tail_score_shrink_rate_weight: float = TAIL_SCORE_SHRINK_RATE_WEIGHT,
    tail_score_drop_scale: float = TAIL_SCORE_DROP_SCALE,
    tail_score_peak_lead_scale_us: float = TAIL_SCORE_PEAK_LEAD_SCALE_US,
    tail_score_shrink_rate_scale: float = TAIL_SCORE_SHRINK_RATE_SCALE,
    tail_unified_band_drop_min: float = TAIL_UNIFIED_BAND_DROP_MIN,
    tail_unified_band_drop_max: float = TAIL_UNIFIED_BAND_DROP_MAX,
    tail_unified_band_peak_lead_min_us: float = TAIL_UNIFIED_BAND_PEAK_LEAD_MIN_US,
    tail_unified_band_peak_lead_max_us: float = TAIL_UNIFIED_BAND_PEAK_LEAD_MAX_US,
    tail_unified_band_shrink_rate_ratio_min: float = TAIL_UNIFIED_BAND_SHRINK_RATE_RATIO_MIN,
    tail_unified_band_shrink_rate_ratio_max: float = TAIL_UNIFIED_BAND_SHRINK_RATE_RATIO_MAX,
    tail_unified_target_drop_to_threshold_frac: float = TAIL_UNIFIED_TARGET_DROP_TO_THRESHOLD_FRAC,
    tail_unified_target_peak_lead_us: float = TAIL_UNIFIED_TARGET_PEAK_LEAD_US,
    tail_unified_target_shrink_rate_ratio: float = TAIL_UNIFIED_TARGET_SHRINK_RATE_RATIO,
    volume_uncertainty_sample_count: int = VOLUME_UNCERTAINTY_SAMPLE_COUNT,
    volume_uncertainty_seed: int = VOLUME_UNCERTAINTY_SEED,
    tail_uncertainty_score_tolerance: float = TAIL_UNCERTAINTY_SCORE_TOLERANCE,
    steady_fit_r2_min: float = 0.985,
    steady_fit_nrmse_max: float = 0.03,
):
    feature_rows = _feature_rows_from_phase_input_rows(
        phase_input_rows,
        width_smooth_window=int(width_smooth_window),
    )
    if _clean_text(steady_fit_mode) == "recompute":
        steady_fit = _recompute_steady_fit_from_feature_rows(
            feature_rows,
            first_untrusted_capture_index=_int_or_none(fov_report.get("first_untrusted_capture_index")),
            exclude_last_trusted_frames=int(steady_fit_exclude_last_trusted_frames),
            min_steady_frames=int(min_steady_frames),
            steady_width_tol_frac=float(steady_width_tol_frac),
            steady_width_tol_px=float(steady_width_tol_px),
            flow_fit_backfill_max_frames=int(flow_fit_backfill_max_frames),
            flow_fit_backfill_width_delta_px=float(flow_fit_backfill_width_delta_px),
            flow_fit_backfill_monotonic_slack_px=float(flow_fit_backfill_monotonic_slack_px),
            steady_fit_r2_min=float(steady_fit_r2_min),
            steady_fit_nrmse_max=float(steady_fit_nrmse_max),
        )
    else:
        steady_fit = _steady_fit_from_payload(feature_rows, dict(steady_fit_payload))
    tail_onset = _find_tail_onset(
        feature_rows,
        steady_fit,
        first_untrusted_capture_index=_int_or_none(fov_report.get("first_untrusted_capture_index")),
        tail_drop_frac=float(tail_drop_frac),
        tail_persist_frames=int(tail_persist_frames),
    )
    tail_onset, tail_start_candidate_rows = _refine_tail_onset_for_review(
        feature_rows,
        steady_fit,
        tail_onset,
        first_untrusted_capture_index=_int_or_none(fov_report.get("first_untrusted_capture_index")),
        tail_start_mode=str(tail_start_mode),
        tail_direct_target_drop_to_threshold_frac=float(
            tail_direct_target_drop_to_threshold_frac
        ),
        tail_direct_target_peak_lead_us=float(tail_direct_target_peak_lead_us),
        tail_direct_target_shrink_rate_ratio=float(tail_direct_target_shrink_rate_ratio),
        tail_shoulder_target_drop_to_threshold_frac=float(
            tail_shoulder_target_drop_to_threshold_frac
        ),
        tail_shoulder_target_peak_lead_us=float(tail_shoulder_target_peak_lead_us),
        tail_shoulder_target_shrink_rate_ratio=float(tail_shoulder_target_shrink_rate_ratio),
        tail_score_drop_weight=float(tail_score_drop_weight),
        tail_score_peak_lead_weight=float(tail_score_peak_lead_weight),
        tail_score_shrink_rate_weight=float(tail_score_shrink_rate_weight),
        tail_score_drop_scale=float(tail_score_drop_scale),
        tail_score_peak_lead_scale_us=float(tail_score_peak_lead_scale_us),
        tail_score_shrink_rate_scale=float(tail_score_shrink_rate_scale),
        tail_unified_band_drop_min=float(tail_unified_band_drop_min),
        tail_unified_band_drop_max=float(tail_unified_band_drop_max),
        tail_unified_band_peak_lead_min_us=float(tail_unified_band_peak_lead_min_us),
        tail_unified_band_peak_lead_max_us=float(tail_unified_band_peak_lead_max_us),
        tail_unified_band_shrink_rate_ratio_min=float(
            tail_unified_band_shrink_rate_ratio_min
        ),
        tail_unified_band_shrink_rate_ratio_max=float(
            tail_unified_band_shrink_rate_ratio_max
        ),
        tail_unified_target_drop_to_threshold_frac=float(
            tail_unified_target_drop_to_threshold_frac
        ),
        tail_unified_target_peak_lead_us=float(tail_unified_target_peak_lead_us),
        tail_unified_target_shrink_rate_ratio=float(
            tail_unified_target_shrink_rate_ratio
        ),
    )
    middle = _middle_extrapolation(
        feature_rows,
        steady_fit,
        tail_onset,
        dict(fov_report),
        trusted_visible_volume_nl=trusted_visible_volume_nl,
        first_untrusted_delay_from_emergence_us=first_untrusted_delay_from_emergence_us,
    )
    middle.update(
        _propagated_volume_uncertainty_from_review(
            feature_rows,
            steady_fit,
            middle,
            dict(fov_report),
            tail_start_candidate_rows=tail_start_candidate_rows,
            first_untrusted_delay_from_emergence_us=first_untrusted_delay_from_emergence_us,
            sample_count=int(volume_uncertainty_sample_count),
            seed=int(volume_uncertainty_seed),
            tail_uncertainty_score_tolerance=float(tail_uncertainty_score_tolerance),
        )
    )
    _apply_phase_labels(feature_rows, steady_fit, tail_onset)

    stage4_run = {
        "run_id": run_id,
        "fov_report": dict(fov_report),
    }
    summary = _run_phase_summary(steady_fit, tail_onset, middle)
    summary["phase_feature_row_count"] = int(len(feature_rows))
    summary["width_valid_frame_count"] = int(
        sum(
            1
            for row in feature_rows
            if row.get("attached_near_nozzle_width_median_px") not in (None, "")
        )
    )
    summary["steady_selected_frame_count"] = int(
        sum(1 for row in feature_rows if bool(row.get("steady_selected")))
    )
    summary["tail_start_capture_index"] = tail_onset.get("tail_start_capture_index")
    summary["tail_onset_status"] = tail_onset.get("tail_onset_status")
    summary["tail_start_refinement_mode"] = tail_onset.get("tail_start_refinement_mode")
    summary["tail_start_band_selection_status"] = tail_onset.get(
        "tail_start_band_selection_status"
    )
    summary["tail_in_band_candidate_count"] = tail_onset.get("tail_in_band_candidate_count")
    summary["tail_start_score"] = tail_onset.get("tail_start_score")
    summary["tail_score_candidate_count"] = tail_onset.get("tail_score_candidate_count")
    summary["tail_score_window_start_capture_index"] = tail_onset.get(
        "tail_score_window_start_capture_index"
    )
    summary["tail_score_window_end_capture_index"] = tail_onset.get(
        "tail_score_window_end_capture_index"
    )
    summary["tail_start_drop_frac"] = tail_onset.get("tail_start_drop_frac")
    summary["tail_start_drop_to_threshold_frac"] = tail_onset.get(
        "tail_start_drop_to_threshold_frac"
    )
    summary["tail_start_shrink_rate_norm_per_ms"] = tail_onset.get(
        "tail_start_shrink_rate_norm_per_ms"
    )
    summary["tail_start_shrink_rate_ratio"] = tail_onset.get("tail_start_shrink_rate_ratio")
    summary["tail_peak_shrink_rate_norm_per_ms"] = tail_onset.get(
        "tail_peak_shrink_rate_norm_per_ms"
    )
    summary["tail_peak_shrink_rate_delay_us"] = tail_onset.get("tail_peak_shrink_rate_delay_us")
    summary["tail_start_to_tail_peak_delta_us"] = tail_onset.get(
        "tail_start_to_tail_peak_delta_us"
    )

    return {
        "run_id": run_id,
        "stage4_run": stage4_run,
        "phase_input_rows": [dict(row) for row in phase_input_rows],
        "phase_feature_rows": feature_rows,
        "steady_fit": steady_fit,
        "tail_onset": tail_onset,
        "middle_extrapolation": middle,
        "phase_boundaries": _phase_boundaries_payload(feature_rows, stage4_run, steady_fit, tail_onset, middle),
        "steady_fit_payload": _steady_fit_payload(feature_rows, stage4_run, steady_fit),
        "middle_payload": _middle_payload(feature_rows, stage4_run, steady_fit, tail_onset, middle),
        "summary": summary,
        "tail_start_candidate_rows": [dict(row) for row in tail_start_candidate_rows],
    }


def _build_stage5_review_run(
    run_id: str,
    phase_input_rows: list[dict],
    **kwargs,
):
    return _build_stage5_from_phase_inputs(run_id, phase_input_rows, **kwargs)


def _apply_phase_labels(feature_rows: list[dict], steady_fit: dict, tail_onset: dict):
    steady_positions = set(steady_fit.get("positions") or [])
    tail_candidate_positions = set(tail_onset.get("tail_candidate_positions") or set())
    tail_confirmation_position = tail_onset.get("tail_confirmation_position")
    tail_shoulder_end_position = tail_onset.get("tail_shoulder_end_position")
    tail_start_position = tail_onset.get("tail_start_position")
    steady_end_capture_index = _int_or_none(steady_fit.get("steady_end_capture_index"))
    tail_start_capture_index = _int_or_none(tail_onset.get("tail_start_capture_index"))

    for position, row in enumerate(feature_rows):
        capture_index = _int_or_none(row.get("capture_index"))
        row["steady_selected"] = bool(position in steady_positions)
        row["tail_drop_candidate"] = bool(position in tail_candidate_positions)
        row["tail_confirmation_frame"] = bool(
            tail_confirmation_position is not None and int(position) == int(tail_confirmation_position)
        )
        row["tail_shoulder_end_frame"] = bool(
            tail_shoulder_end_position is not None and int(position) == int(tail_shoulder_end_position)
        )
        row["tail_start_frame"] = bool(
            tail_start_position is not None and int(position) == int(tail_start_position)
        )

        if row.get("attached_near_nozzle_width_median_px") is None:
            row["phase_label"] = "width_unavailable"
        elif bool(row["steady_selected"]):
            row["phase_label"] = "steady"
        elif (
            tail_start_capture_index is not None
            and capture_index is not None
            and capture_index >= int(tail_start_capture_index)
        ):
            row["phase_label"] = "tail"
        elif (
            steady_end_capture_index is not None
            and capture_index is not None
            and capture_index > int(steady_end_capture_index)
        ):
            row["phase_label"] = "post_steady_pre_tail"
        else:
            row["phase_label"] = "head_or_transition"
    return feature_rows


def _plot_width_trace(path: Path, feature_rows: list[dict], *, run_id: str, steady_fit: dict, tail_onset: dict, fov_report: dict):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    x_label, x_values = volume_mod._plot_x_values(feature_rows)
    raw_points = [
        (x_value, float(row["attached_near_nozzle_width_median_px"]))
        for x_value, row in zip(x_values, feature_rows)
        if x_value is not None and row.get("attached_near_nozzle_width_median_px") is not None
    ]
    smoothed_points = [
        (x_value, float(row["attached_near_nozzle_width_smoothed_px"]))
        for x_value, row in zip(x_values, feature_rows)
        if x_value is not None and row.get("attached_near_nozzle_width_smoothed_px") is not None
    ]

    fig, ax = plt.subplots(figsize=(10, 5))
    if raw_points:
        ax.plot(
            [x for x, _y in raw_points],
            [y for _x, y in raw_points],
            color="#9db7d5",
            linewidth=1.0,
            alpha=0.8,
            label="raw width",
        )
    if smoothed_points:
        ax.plot(
            [x for x, _y in smoothed_points],
            [y for _x, y in smoothed_points],
            color="#d97706",
            linewidth=1.6,
            label="smoothed width",
        )

    steady_positions = list(steady_fit.get("positions") or [])
    if steady_positions:
        steady_x = [x_values[position] for position in steady_positions if x_values[position] is not None]
        plateau = steady_fit.get("steady_width_plateau_px")
        tolerance = steady_fit.get("steady_width_tolerance_px")
        if steady_x and plateau is not None:
            x0 = min(steady_x)
            x1 = max(steady_x)
            ax.plot([x0, x1], [float(plateau), float(plateau)], color="#228b22", linewidth=1.4, linestyle="--", label="steady plateau")
            if tolerance is not None:
                ax.plot([x0, x1], [float(plateau) + float(tolerance), float(plateau) + float(tolerance)], color="#228b22", linewidth=1.0, linestyle=":", label="steady band")
                ax.plot([x0, x1], [float(plateau) - float(tolerance), float(plateau) - float(tolerance)], color="#228b22", linewidth=1.0, linestyle=":")

    threshold = tail_onset.get("tail_width_threshold_px")
    if threshold is not None and smoothed_points and steady_positions:
        x0 = x_values[steady_positions[-1]]
        x1 = smoothed_points[-1][0]
        if x0 is not None and x1 is not None:
            ax.plot([x0, x1], [float(threshold), float(threshold)], color="#b91c1c", linewidth=1.0, linestyle="--", label="tail threshold")

    for capture_index, label, color, linestyle in [
        (steady_fit.get("steady_start_capture_index"), "steady start", "#228b22", "--"),
        (steady_fit.get("steady_end_capture_index"), "steady end", "#228b22", "-."),
        (fov_report.get("first_untrusted_capture_index"), "first untrusted", "#d62728", "--"),
        (tail_onset.get("tail_confirmation_capture_index"), "tail confirmation", "#c2410c", "-."),
        (tail_onset.get("tail_shoulder_end_capture_index"), "tail shoulder end", "#0f766e", ":"),
        (tail_onset.get("tail_start_capture_index"), "tail start", "#7c3aed", "--"),
    ]:
        capture_index = _int_or_none(capture_index)
        if capture_index is None:
            continue
        x_value = next(
            (
                x_val
                for x_val, row in zip(x_values, feature_rows)
                if _int_or_none(row.get("capture_index")) == capture_index
            ),
            None,
        )
        if x_value is not None:
            ax.axvline(x_value, color=color, linestyle=linestyle, linewidth=1.2, label=label)

    ax.set_title(f"Near-Nozzle Width Trace - {run_id}")
    ax.set_xlabel(x_label)
    ax.set_ylabel("Attached width (px)")
    ax.grid(True, alpha=0.25)
    if hasattr(ax, "get_legend_handles_labels"):
        handles, labels = ax.get_legend_handles_labels()
        if labels:
            by_label = dict(zip(labels, handles))
            ax.legend(by_label.values(), by_label.keys(), loc="best")
    elif hasattr(ax, "legend"):
        ax.legend(loc="best")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _plot_vt_fit(path: Path, feature_rows: list[dict], *, run_id: str, steady_fit: dict, middle: dict, fov_report: dict, tail_onset: dict):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    x_label, x_values = volume_mod._plot_x_values(feature_rows)
    available_rows = [
        (x_value, row)
        for x_value, row in zip(x_values, feature_rows)
        if x_value is not None and row.get("total_visible_volume_nl") is not None
    ]
    trusted_rows = [
        (x_value, row)
        for x_value, row in zip(x_values, feature_rows)
        if x_value is not None
        and row.get("total_visible_volume_nl") is not None
        and _clean_text(row.get("volume_trust_label")) == fov_mod.TRUST_LABEL_TRUSTED
    ]
    untrusted_rows = [
        (x_value, row)
        for x_value, row in zip(x_values, feature_rows)
        if x_value is not None
        and row.get("total_visible_volume_nl") is not None
        and _clean_text(row.get("volume_trust_label")) == fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT
    ]
    excluded_tail_capture_indices = {
        int(capture_index)
        for capture_index in list(steady_fit.get("excluded_tail_trusted_capture_indices") or [])
        if _int_or_none(capture_index) is not None
    }
    excluded_tail_rows = [
        (x_value, row)
        for x_value, row in zip(x_values, feature_rows)
        if x_value is not None
        and row.get("total_visible_volume_nl") is not None
        and _int_or_none(row.get("capture_index")) in excluded_tail_capture_indices
    ]
    dropped_outlier_capture_index = _int_or_none(
        steady_fit.get("flow_fit_dropped_outlier_capture_index")
    )
    dropped_outlier_rows = [
        (x_value, row)
        for x_value, row in zip(x_values, feature_rows)
        if x_value is not None
        and row.get("total_visible_volume_nl") is not None
        and dropped_outlier_capture_index is not None
        and _int_or_none(row.get("capture_index")) == dropped_outlier_capture_index
    ]
    plateau_positions = list(steady_fit.get("plateau_positions") or steady_fit.get("positions") or [])
    plateau_rows = [
        (x_values[position], feature_rows[position])
        for position in plateau_positions
        if position >= 0
        and position < len(feature_rows)
        and x_values[position] is not None
        and feature_rows[position].get("total_visible_volume_nl") is not None
    ]
    flow_fit_positions = list(steady_fit.get("flow_fit_positions") or steady_fit.get("positions") or [])
    flow_fit_rows = [
        (x_values[position], feature_rows[position])
        for position in flow_fit_positions
        if position >= 0
        and position < len(feature_rows)
        and x_values[position] is not None
        and feature_rows[position].get("total_visible_volume_nl") is not None
    ]
    plateau_position_set = set(int(position) for position in plateau_positions)
    backfilled_flow_fit_rows = [
        (x_values[position], feature_rows[position])
        for position in flow_fit_positions
        if position >= 0
        and position < len(feature_rows)
        and int(position) not in plateau_position_set
        and plateau_positions
        and int(position) < int(plateau_positions[0])
        and x_values[position] is not None
        and feature_rows[position].get("total_visible_volume_nl") is not None
    ]
    post_plateau_flow_fit_rows = [
        (x_values[position], feature_rows[position])
        for position in flow_fit_positions
        if position >= 0
        and position < len(feature_rows)
        and int(position) not in plateau_position_set
        and (
            not plateau_positions
            or int(position) > int(plateau_positions[-1])
        )
        and x_values[position] is not None
        and feature_rows[position].get("total_visible_volume_nl") is not None
    ]
    steady_points = _steady_fit_time_volume_points(feature_rows, steady_fit)
    ci_band_points = _steady_fit_ci_band_points(
        feature_rows,
        steady_fit,
        plot_x_values=[float(x) for x, _row in available_rows],
    )

    fig, ax = plt.subplots(figsize=(10, 5))
    if available_rows:
        ax.plot(
            [x for x, _row in available_rows],
            [float(row["total_visible_volume_nl"]) for _x, row in available_rows],
            color="#8aa5c8",
            linewidth=1.2,
            alpha=0.8,
            label="all visible volume",
        )
    if trusted_rows:
        ax.scatter(
            [x for x, _row in trusted_rows],
            [float(row["total_visible_volume_nl"]) for _x, row in trusted_rows],
            color="#228b22",
            s=22,
            label="trusted",
            zorder=3,
        )
    if untrusted_rows:
        ax.scatter(
            [x for x, _row in untrusted_rows],
            [float(row["total_visible_volume_nl"]) for _x, row in untrusted_rows],
            color="#d62728",
            s=22,
            label="untrusted",
            zorder=3,
        )
    if excluded_tail_rows:
        ax.scatter(
            [x for x, _row in excluded_tail_rows],
            [float(row["total_visible_volume_nl"]) for _x, row in excluded_tail_rows],
            facecolors="none",
            edgecolors="#b91c1c",
            marker="v",
            linewidths=1.2,
            s=58,
            label="trusted excluded near exit",
            zorder=4,
        )
    if plateau_rows:
        ax.scatter(
            [x for x, _row in plateau_rows],
            [float(row["total_visible_volume_nl"]) for _x, row in plateau_rows],
            facecolors="none",
            edgecolors="#1d4ed8",
            marker="s",
            linewidths=1.2,
            s=48,
            label="plateau seed / tail anchor",
            zorder=4,
        )
    if backfilled_flow_fit_rows:
        ax.scatter(
            [x for x, _row in backfilled_flow_fit_rows],
            [float(row["total_visible_volume_nl"]) for _x, row in backfilled_flow_fit_rows],
            facecolors="#fef3c7",
            edgecolors="#92400e",
            marker="D",
            linewidths=0.9,
            s=42,
            label="backfilled pre-plateau fit",
            zorder=4,
        )
    if post_plateau_flow_fit_rows:
        ax.scatter(
            [x for x, _row in post_plateau_flow_fit_rows],
            [float(row["total_visible_volume_nl"]) for _x, row in post_plateau_flow_fit_rows],
            facecolors="#f59e0b",
            edgecolors="#111827",
            linewidths=0.8,
            s=44,
            label="flow fit extension",
            zorder=4,
        )
    if dropped_outlier_rows:
        ax.scatter(
            [x for x, _row in dropped_outlier_rows],
            [float(row["total_visible_volume_nl"]) for _x, row in dropped_outlier_rows],
            color="#dc2626",
            marker="x",
            linewidths=1.6,
            s=64,
            label="dropped outlier",
            zorder=5,
        )

    if ci_band_points and hasattr(ax, "fill_between"):
        ax.fill_between(
            [x for x, _y0, _y1 in ci_band_points],
            [y0 for _x, y0, _y1 in ci_band_points],
            [y1 for _x, _y0, y1 in ci_band_points],
            color="#0f766e",
            alpha=0.14,
            label="flow-fit slope CI95",
        )

    if flow_fit_positions and _clean_text(steady_fit.get("steady_fit_status")) == "ok":
        steady_x = []
        steady_y = []
        for position in flow_fit_positions:
            x_value = _time_axis_value(feature_rows[position], allow_flash_fallback=False)
            if x_value is None:
                continue
            steady_x.append(float(x_value))
            steady_y.append(
                float(steady_fit["steady_intercept_nl"]) + (float(steady_fit["steady_rate_nl_per_us"]) * float(x_value))
            )
        if steady_x:
            ax.plot(steady_x, steady_y, color="#0f766e", linewidth=2.0, label="flow fit")

    if _clean_text(middle.get("middle_extrapolation_status")) == "ok":
        start_capture_index = _int_or_none(middle.get("first_untrusted_capture_index"))
        tail_start_capture_index = _int_or_none(middle.get("tail_start_capture_index"))
        start_row = _row_by_capture_index(feature_rows, start_capture_index)
        end_row = _row_by_capture_index(feature_rows, tail_start_capture_index)
        start_time = None if start_row is None else _time_axis_value(start_row, allow_flash_fallback=True)
        end_time = None if end_row is None else _time_axis_value(end_row, allow_flash_fallback=True)
        if start_time is not None and end_time is not None:
            extrap_x = [float(start_time), float(end_time)]
            extrap_y = [
                float(steady_fit["steady_intercept_nl"]) + (float(steady_fit["steady_rate_nl_per_us"]) * float(start_time)),
                float(steady_fit["steady_intercept_nl"]) + (float(steady_fit["steady_rate_nl_per_us"]) * float(end_time)),
            ]
            ax.plot(
                extrap_x,
                extrap_y,
                color="#7c3aed",
                linewidth=1.8,
                linestyle="--",
                label="middle extrapolation",
            )

    for capture_index, label, color, linestyle in [
        (steady_fit.get("flow_fit_start_capture_index"), "flow fit start", "#0f766e", ":"),
        (steady_fit.get("flow_fit_end_capture_index"), "flow fit end", "#0f766e", "-."),
        (steady_fit.get("steady_start_capture_index"), "steady start", "#228b22", "--"),
        (steady_fit.get("steady_end_capture_index"), "steady end", "#228b22", "-."),
        (fov_report.get("first_untrusted_capture_index"), "first untrusted", "#d62728", "--"),
        (tail_onset.get("tail_confirmation_capture_index"), "tail confirmation", "#c2410c", "-."),
        (tail_onset.get("tail_shoulder_end_capture_index"), "tail shoulder end", "#0f766e", ":"),
        (tail_onset.get("tail_start_capture_index"), "tail start", "#7c3aed", "--"),
    ]:
        capture_index = _int_or_none(capture_index)
        if capture_index is None:
            continue
        x_value = next(
            (
                x_val
                for x_val, row in zip(x_values, feature_rows)
                if _int_or_none(row.get("capture_index")) == capture_index
            ),
            None,
        )
        if x_value is not None:
            ax.axvline(x_value, color=color, linestyle=linestyle, linewidth=1.2, label=label)

    ci_status = _clean_text(steady_fit.get("steady_rate_confidence_status")) or "n/a"
    ax.set_title(
        f"Visible Volume Flow-Fit Review - {run_id}\n"
        f"Plateau seed anchors tail search; flow-fit window drives rate/CI ({ci_status})"
    )
    ax.set_xlabel(x_label)
    ax.set_ylabel("Visible volume (nL)")
    ax.grid(True, alpha=0.25)
    if hasattr(ax, "get_legend_handles_labels"):
        handles, labels = ax.get_legend_handles_labels()
        if labels:
            by_label = dict(zip(labels, handles))
            ax.legend(by_label.values(), by_label.keys(), loc="best")
    elif hasattr(ax, "legend"):
        ax.legend(loc="best")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _run_phase_summary(steady_fit: dict, tail_onset: dict, middle: dict):
    return {
        "steady_fit_status": steady_fit.get("steady_fit_status"),
        "steady_fit_mode": steady_fit.get("steady_fit_mode"),
        "steady_start_capture_index": steady_fit.get("steady_start_capture_index"),
        "steady_end_capture_index": steady_fit.get("steady_end_capture_index"),
        "plateau_capture_indices": list(steady_fit.get("plateau_capture_indices") or []),
        "plateau_point_count": steady_fit.get("plateau_point_count"),
        "flow_fit_capture_indices": list(steady_fit.get("flow_fit_capture_indices") or []),
        "flow_fit_start_capture_index": steady_fit.get("flow_fit_start_capture_index"),
        "flow_fit_end_capture_index": steady_fit.get("flow_fit_end_capture_index"),
        "flow_fit_point_count": steady_fit.get("flow_fit_point_count"),
        "flow_fit_eligible_point_count": steady_fit.get("flow_fit_eligible_point_count"),
        "flow_fit_backfill_point_count": steady_fit.get("flow_fit_backfill_point_count"),
        "flow_fit_outlier_prune_status": steady_fit.get("flow_fit_outlier_prune_status"),
        "flow_fit_dropped_outlier_capture_index": steady_fit.get(
            "flow_fit_dropped_outlier_capture_index"
        ),
        "flow_fit_dropped_outlier_delay_from_emergence_us": steady_fit.get(
            "flow_fit_dropped_outlier_delay_from_emergence_us"
        ),
        "flow_fit_dropped_outlier_local_deviation_nl": steady_fit.get(
            "flow_fit_dropped_outlier_local_deviation_nl"
        ),
        "steady_fit_point_count": steady_fit.get("steady_fit_point_count"),
        "steady_fit_candidate_window_count": steady_fit.get("steady_fit_candidate_window_count"),
        "steady_fit_selection_score": steady_fit.get("steady_fit_selection_score"),
        "steady_fit_exclude_last_trusted_frames": steady_fit.get(
            "steady_fit_exclude_last_trusted_frames"
        ),
        "steady_fit_excluded_tail_trusted_frame_count": steady_fit.get(
            "steady_fit_excluded_tail_trusted_frame_count"
        ),
        "steady_rate_nl_per_us": steady_fit.get("steady_rate_nl_per_us"),
        "steady_rate_ci95_low_nl_per_us": steady_fit.get("steady_rate_ci95_low_nl_per_us"),
        "steady_rate_ci95_high_nl_per_us": steady_fit.get("steady_rate_ci95_high_nl_per_us"),
        "steady_rate_ci95_relative_width": steady_fit.get("steady_rate_ci95_relative_width"),
        "steady_rate_ci95_contains_central": steady_fit.get("steady_rate_ci95_contains_central"),
        "steady_rate_confidence_status": steady_fit.get("steady_rate_confidence_status"),
        "steady_intercept_nl": steady_fit.get("steady_intercept_nl"),
        "steady_r2": steady_fit.get("steady_r2"),
        "steady_nrmse": steady_fit.get("steady_nrmse"),
        "steady_width_plateau_px": steady_fit.get("steady_width_plateau_px"),
        "steady_fit_first_last_residual_delta_nl": steady_fit.get(
            "steady_fit_first_last_residual_delta_nl"
        ),
        "steady_fit_max_abs_residual_nl": steady_fit.get("steady_fit_max_abs_residual_nl"),
        "steady_fit_residual_trend_nl_per_us": steady_fit.get(
            "steady_fit_residual_trend_nl_per_us"
        ),
        "tail_confirmation_capture_index": tail_onset.get("tail_confirmation_capture_index"),
        "tail_confirmation_delay_from_emergence_us": tail_onset.get("tail_confirmation_delay_from_emergence_us"),
        "tail_detection_mode": tail_onset.get("tail_detection_mode"),
        "tail_start_selection_mode": tail_onset.get("tail_start_selection_mode"),
        "preliminary_tail_start_capture_index": tail_onset.get("preliminary_tail_start_capture_index"),
        "preliminary_tail_start_delay_from_emergence_us": tail_onset.get(
            "preliminary_tail_start_delay_from_emergence_us"
        ),
        "direct_final_tail_start_capture_index": tail_onset.get("direct_final_tail_start_capture_index"),
        "direct_final_tail_start_delay_from_emergence_us": tail_onset.get(
            "direct_final_tail_start_delay_from_emergence_us"
        ),
        "tail_shoulder_end_capture_index": tail_onset.get("tail_shoulder_end_capture_index"),
        "tail_shoulder_end_delay_from_emergence_us": tail_onset.get(
            "tail_shoulder_end_delay_from_emergence_us"
        ),
        "tail_start_capture_index": tail_onset.get("tail_start_capture_index"),
        "tail_start_delay_from_emergence_us": tail_onset.get("tail_start_delay_from_emergence_us"),
        "tail_onset_status": tail_onset.get("tail_onset_status"),
        "trusted_visible_volume_nl": middle.get("trusted_visible_volume_nl"),
        "middle_extrapolated_volume_nl": middle.get("middle_extrapolated_volume_nl"),
        "partial_total_without_tail_nl": middle.get("partial_total_without_tail_nl"),
        "tail_start_uncertainty_p05_us": middle.get("tail_start_uncertainty_p05_us"),
        "tail_start_uncertainty_p95_us": middle.get("tail_start_uncertainty_p95_us"),
        "tail_start_uncertainty_candidate_count": middle.get(
            "tail_start_uncertainty_candidate_count"
        ),
        "tail_start_uncertainty_source": middle.get("tail_start_uncertainty_source"),
        "predicted_volume_uncertainty_p05_nl": middle.get(
            "predicted_volume_uncertainty_p05_nl"
        ),
        "predicted_volume_uncertainty_p95_nl": middle.get(
            "predicted_volume_uncertainty_p95_nl"
        ),
        "predicted_volume_uncertainty_width_nl": middle.get(
            "predicted_volume_uncertainty_width_nl"
        ),
        "predicted_volume_uncertainty_relative_width": middle.get(
            "predicted_volume_uncertainty_relative_width"
        ),
        "predicted_volume_uncertainty_status": middle.get(
            "predicted_volume_uncertainty_status"
        ),
        "volume_uncertainty_sample_count": middle.get("volume_uncertainty_sample_count"),
        "tail_volume_nl": middle.get("tail_volume_nl"),
        "middle_extrapolation_status": middle.get("middle_extrapolation_status"),
        "final_total_status": middle.get("final_total_status"),
    }


def _phase_boundaries_payload(feature_rows: list[dict], stage4_run: dict, steady_fit: dict, tail_onset: dict, middle: dict):
    run_id = stage4_run.get("run_id")
    if run_id is None:
        run_id = None if not feature_rows else feature_rows[0].get("run_id")
    steady_start_row = _row_by_capture_index(
        feature_rows,
        _int_or_none(steady_fit.get("steady_start_capture_index")),
    )
    steady_end_row = _row_by_capture_index(
        feature_rows,
        _int_or_none(steady_fit.get("steady_end_capture_index")),
    )
    flow_fit_start_row = _row_by_capture_index(
        feature_rows,
        _int_or_none(steady_fit.get("flow_fit_start_capture_index")),
    )
    flow_fit_end_row = _row_by_capture_index(
        feature_rows,
        _int_or_none(steady_fit.get("flow_fit_end_capture_index")),
    )
    first_untrusted_row = _row_by_capture_index(
        feature_rows,
        _int_or_none(stage4_run["fov_report"].get("first_untrusted_capture_index")),
    )
    return {
        "schema_version": 1,
        "stage": "fit",
        "run_id": run_id,
        "steady_fit_status": steady_fit.get("steady_fit_status"),
        "steady_start_capture_index": steady_fit.get("steady_start_capture_index"),
        "steady_start_delay_from_emergence_us": None
        if steady_start_row is None
        else _int_or_none(steady_start_row.get("delay_from_emergence_us")),
        "steady_end_capture_index": steady_fit.get("steady_end_capture_index"),
        "steady_end_delay_from_emergence_us": None
        if steady_end_row is None
        else _int_or_none(steady_end_row.get("delay_from_emergence_us")),
        "flow_fit_start_capture_index": steady_fit.get("flow_fit_start_capture_index"),
        "flow_fit_start_delay_from_emergence_us": None
        if flow_fit_start_row is None
        else _int_or_none(flow_fit_start_row.get("delay_from_emergence_us")),
        "flow_fit_end_capture_index": steady_fit.get("flow_fit_end_capture_index"),
        "flow_fit_end_delay_from_emergence_us": None
        if flow_fit_end_row is None
        else _int_or_none(flow_fit_end_row.get("delay_from_emergence_us")),
        "first_untrusted_capture_index": stage4_run["fov_report"].get("first_untrusted_capture_index"),
        "first_untrusted_delay_from_emergence_us": None
        if first_untrusted_row is None
        else _int_or_none(first_untrusted_row.get("delay_from_emergence_us")),
        "tail_confirmation_capture_index": tail_onset.get("tail_confirmation_capture_index"),
        "tail_confirmation_delay_from_emergence_us": tail_onset.get("tail_confirmation_delay_from_emergence_us"),
        "tail_detection_mode": tail_onset.get("tail_detection_mode"),
        "tail_start_selection_mode": tail_onset.get("tail_start_selection_mode"),
        "preliminary_tail_start_capture_index": tail_onset.get("preliminary_tail_start_capture_index"),
        "preliminary_tail_start_delay_from_emergence_us": tail_onset.get(
            "preliminary_tail_start_delay_from_emergence_us"
        ),
        "direct_final_tail_start_capture_index": tail_onset.get("direct_final_tail_start_capture_index"),
        "direct_final_tail_start_delay_from_emergence_us": tail_onset.get(
            "direct_final_tail_start_delay_from_emergence_us"
        ),
        "tail_shoulder_end_capture_index": tail_onset.get("tail_shoulder_end_capture_index"),
        "tail_shoulder_end_delay_from_emergence_us": tail_onset.get(
            "tail_shoulder_end_delay_from_emergence_us"
        ),
        "tail_start_capture_index": tail_onset.get("tail_start_capture_index"),
        "tail_start_delay_from_emergence_us": tail_onset.get("tail_start_delay_from_emergence_us"),
        "tail_onset_status": tail_onset.get("tail_onset_status"),
        "middle_extrapolation_status": middle.get("middle_extrapolation_status"),
        "final_total_status": middle.get("final_total_status"),
    }


def _steady_fit_payload(feature_rows: list[dict], stage4_run: dict, steady_fit: dict):
    run_id = stage4_run.get("run_id")
    if run_id is None:
        run_id = None if not feature_rows else feature_rows[0].get("run_id")
    return {
        "schema_version": 1,
        "stage": "fit",
        "run_id": run_id,
        "steady_fit_status": steady_fit.get("steady_fit_status"),
        "steady_fit_mode": steady_fit.get("steady_fit_mode"),
        "steady_start_capture_index": steady_fit.get("steady_start_capture_index"),
        "steady_end_capture_index": steady_fit.get("steady_end_capture_index"),
        "plateau_capture_indices": list(
            steady_fit.get("plateau_capture_indices")
            or steady_fit.get("steady_capture_indices")
            or []
        ),
        "plateau_point_count": steady_fit.get("plateau_point_count"),
        "steady_capture_indices": list(steady_fit.get("steady_capture_indices") or [
            _int_or_none(feature_rows[position].get("capture_index"))
            for position in (steady_fit.get("positions") or [])
        ]),
        "flow_fit_start_capture_index": steady_fit.get("flow_fit_start_capture_index"),
        "flow_fit_end_capture_index": steady_fit.get("flow_fit_end_capture_index"),
        "flow_fit_capture_indices": list(
            steady_fit.get("flow_fit_capture_indices")
            or steady_fit.get("steady_capture_indices")
            or []
        ),
        "flow_fit_point_count": steady_fit.get("flow_fit_point_count"),
        "flow_fit_eligible_point_count": steady_fit.get("flow_fit_eligible_point_count"),
        "flow_fit_backfill_point_count": steady_fit.get("flow_fit_backfill_point_count"),
        "flow_fit_outlier_prune_status": steady_fit.get("flow_fit_outlier_prune_status"),
        "flow_fit_dropped_outlier_capture_index": steady_fit.get(
            "flow_fit_dropped_outlier_capture_index"
        ),
        "flow_fit_dropped_outlier_delay_from_emergence_us": steady_fit.get(
            "flow_fit_dropped_outlier_delay_from_emergence_us"
        ),
        "flow_fit_dropped_outlier_local_deviation_nl": steady_fit.get(
            "flow_fit_dropped_outlier_local_deviation_nl"
        ),
        "steady_fit_candidate_window_count": steady_fit.get("steady_fit_candidate_window_count"),
        "steady_fit_selection_score": steady_fit.get("steady_fit_selection_score"),
        "steady_fit_exclude_last_trusted_frames": steady_fit.get(
            "steady_fit_exclude_last_trusted_frames"
        ),
        "steady_fit_excluded_tail_trusted_frame_count": steady_fit.get(
            "steady_fit_excluded_tail_trusted_frame_count"
        ),
        "excluded_tail_trusted_capture_indices": list(
            steady_fit.get("excluded_tail_trusted_capture_indices") or []
        ),
        "steady_rate_nl_per_us": steady_fit.get("steady_rate_nl_per_us"),
        "steady_rate_ci95_low_nl_per_us": steady_fit.get("steady_rate_ci95_low_nl_per_us"),
        "steady_rate_ci95_high_nl_per_us": steady_fit.get("steady_rate_ci95_high_nl_per_us"),
        "steady_rate_ci95_relative_width": steady_fit.get("steady_rate_ci95_relative_width"),
        "steady_rate_ci95_contains_central": steady_fit.get("steady_rate_ci95_contains_central"),
        "steady_rate_confidence_status": steady_fit.get("steady_rate_confidence_status"),
        "steady_fit_point_count": steady_fit.get("steady_fit_point_count"),
        "steady_intercept_nl": steady_fit.get("steady_intercept_nl"),
        "steady_r2": steady_fit.get("steady_r2"),
        "steady_nrmse": steady_fit.get("steady_nrmse"),
        "steady_width_plateau_px": steady_fit.get("steady_width_plateau_px"),
        "steady_width_span_px": steady_fit.get("steady_width_span_px"),
        "steady_width_tolerance_px": steady_fit.get("steady_width_tolerance_px"),
        "steady_fit_first_last_residual_delta_nl": steady_fit.get(
            "steady_fit_first_last_residual_delta_nl"
        ),
        "steady_fit_max_abs_residual_nl": steady_fit.get("steady_fit_max_abs_residual_nl"),
        "steady_fit_residual_trend_nl_per_us": steady_fit.get(
            "steady_fit_residual_trend_nl_per_us"
        ),
    }


def _middle_payload(feature_rows: list[dict], stage4_run: dict, steady_fit: dict, tail_onset: dict, middle: dict):
    run_id = stage4_run.get("run_id")
    if run_id is None:
        run_id = None if not feature_rows else feature_rows[0].get("run_id")
    tail_start_row = _row_by_capture_index(
        feature_rows,
        _int_or_none(tail_onset.get("tail_start_capture_index")),
    )
    return {
        "schema_version": 1,
        "stage": "fit",
        "run_id": run_id,
        "first_untrusted_capture_index": middle.get("first_untrusted_capture_index"),
        "first_untrusted_delay_from_emergence_us": stage4_run["fov_report"].get(
            "first_fov_exit_delay_from_emergence_us"
        )
        if middle.get("first_untrusted_capture_index") is not None
        else None,
        "tail_confirmation_capture_index": tail_onset.get("tail_confirmation_capture_index"),
        "tail_confirmation_delay_from_emergence_us": tail_onset.get("tail_confirmation_delay_from_emergence_us"),
        "tail_detection_mode": tail_onset.get("tail_detection_mode"),
        "tail_start_selection_mode": tail_onset.get("tail_start_selection_mode"),
        "preliminary_tail_start_capture_index": tail_onset.get("preliminary_tail_start_capture_index"),
        "preliminary_tail_start_delay_from_emergence_us": tail_onset.get(
            "preliminary_tail_start_delay_from_emergence_us"
        ),
        "direct_final_tail_start_capture_index": tail_onset.get("direct_final_tail_start_capture_index"),
        "direct_final_tail_start_delay_from_emergence_us": tail_onset.get(
            "direct_final_tail_start_delay_from_emergence_us"
        ),
        "tail_shoulder_end_capture_index": tail_onset.get("tail_shoulder_end_capture_index"),
        "tail_shoulder_end_delay_from_emergence_us": tail_onset.get(
            "tail_shoulder_end_delay_from_emergence_us"
        ),
        "tail_start_capture_index": middle.get("tail_start_capture_index"),
        "tail_start_delay_from_emergence_us": None
        if tail_start_row is None
        else _int_or_none(tail_start_row.get("delay_from_emergence_us")),
        "steady_fit_status": steady_fit.get("steady_fit_status"),
        "tail_onset_status": tail_onset.get("tail_onset_status"),
        "trusted_visible_volume_nl": middle.get("trusted_visible_volume_nl"),
        "middle_extrapolated_volume_nl": middle.get("middle_extrapolated_volume_nl"),
        "partial_total_without_tail_nl": middle.get("partial_total_without_tail_nl"),
        "tail_start_uncertainty_p05_us": middle.get("tail_start_uncertainty_p05_us"),
        "tail_start_uncertainty_p95_us": middle.get("tail_start_uncertainty_p95_us"),
        "tail_start_uncertainty_candidate_count": middle.get(
            "tail_start_uncertainty_candidate_count"
        ),
        "tail_start_uncertainty_source": middle.get("tail_start_uncertainty_source"),
        "predicted_volume_uncertainty_p05_nl": middle.get(
            "predicted_volume_uncertainty_p05_nl"
        ),
        "predicted_volume_uncertainty_p95_nl": middle.get(
            "predicted_volume_uncertainty_p95_nl"
        ),
        "predicted_volume_uncertainty_width_nl": middle.get(
            "predicted_volume_uncertainty_width_nl"
        ),
        "predicted_volume_uncertainty_relative_width": middle.get(
            "predicted_volume_uncertainty_relative_width"
        ),
        "predicted_volume_uncertainty_status": middle.get(
            "predicted_volume_uncertainty_status"
        ),
        "volume_uncertainty_sample_count": middle.get("volume_uncertainty_sample_count"),
        "tail_volume_nl": middle.get("tail_volume_nl"),
        "middle_extrapolation_status": middle.get("middle_extrapolation_status"),
        "final_total_status": middle.get("final_total_status"),
    }


def _build_stage5_run(
    run_id: str,
    frame_rows: list[dict],
    *,
    sample_count: int,
    extra_frame_indices: list[int] | None,
    search_width_frac: float,
    search_top_frac: float,
    search_bottom_frac: float,
    blur_sigma: float,
    residual_threshold: int,
    shift_threshold_px: float,
    confidence_threshold: float,
    roi_width_frac: float,
    roi_top_frac: float,
    roi_bottom_frac: float,
    corridor_width_frac: float,
    nozzle_guard_px: int,
    min_component_area_px: int,
    near_nozzle_band_top_px: int,
    near_nozzle_band_height_px: int,
    min_band_valid_rows: int,
    width_smooth_window: int,
    min_steady_frames: int,
    steady_width_tol_frac: float,
    steady_width_tol_px: float,
    steady_fit_r2_min: float,
    steady_fit_nrmse_max: float,
    tail_drop_frac: float,
    tail_persist_frames: int,
    steady_fit_mode: str = "recompute",
    steady_fit_exclude_last_trusted_frames: int = 2,
    flow_fit_backfill_max_frames: int = 3,
    flow_fit_backfill_width_delta_px: float = 8.0,
    flow_fit_backfill_monotonic_slack_px: float = 0.75,
    tail_start_mode: str = TAIL_START_MODE_DESCRIPTOR_UNIFIED,
    tail_direct_target_drop_to_threshold_frac: float = TAIL_DIRECT_TARGET_DROP_TO_THRESHOLD_FRAC,
    tail_direct_target_peak_lead_us: float = TAIL_DIRECT_TARGET_PEAK_LEAD_US,
    tail_direct_target_shrink_rate_ratio: float = TAIL_DIRECT_TARGET_SHRINK_RATE_RATIO,
    tail_shoulder_target_drop_to_threshold_frac: float = TAIL_SHOULDER_TARGET_DROP_TO_THRESHOLD_FRAC,
    tail_shoulder_target_peak_lead_us: float = TAIL_SHOULDER_TARGET_PEAK_LEAD_US,
    tail_shoulder_target_shrink_rate_ratio: float = TAIL_SHOULDER_TARGET_SHRINK_RATE_RATIO,
    tail_score_drop_weight: float = TAIL_SCORE_DROP_WEIGHT,
    tail_score_peak_lead_weight: float = TAIL_SCORE_PEAK_LEAD_WEIGHT,
    tail_score_shrink_rate_weight: float = TAIL_SCORE_SHRINK_RATE_WEIGHT,
    tail_score_drop_scale: float = TAIL_SCORE_DROP_SCALE,
    tail_score_peak_lead_scale_us: float = TAIL_SCORE_PEAK_LEAD_SCALE_US,
    tail_score_shrink_rate_scale: float = TAIL_SCORE_SHRINK_RATE_SCALE,
    tail_unified_band_drop_min: float = TAIL_UNIFIED_BAND_DROP_MIN,
    tail_unified_band_drop_max: float = TAIL_UNIFIED_BAND_DROP_MAX,
    tail_unified_band_peak_lead_min_us: float = TAIL_UNIFIED_BAND_PEAK_LEAD_MIN_US,
    tail_unified_band_peak_lead_max_us: float = TAIL_UNIFIED_BAND_PEAK_LEAD_MAX_US,
    tail_unified_band_shrink_rate_ratio_min: float = TAIL_UNIFIED_BAND_SHRINK_RATE_RATIO_MIN,
    tail_unified_band_shrink_rate_ratio_max: float = TAIL_UNIFIED_BAND_SHRINK_RATE_RATIO_MAX,
    tail_unified_target_drop_to_threshold_frac: float = TAIL_UNIFIED_TARGET_DROP_TO_THRESHOLD_FRAC,
    tail_unified_target_peak_lead_us: float = TAIL_UNIFIED_TARGET_PEAK_LEAD_US,
    tail_unified_target_shrink_rate_ratio: float = TAIL_UNIFIED_TARGET_SHRINK_RATE_RATIO,
    volume_uncertainty_sample_count: int = VOLUME_UNCERTAINTY_SAMPLE_COUNT,
    volume_uncertainty_seed: int = VOLUME_UNCERTAINTY_SEED,
    tail_uncertainty_score_tolerance: float = TAIL_UNCERTAINTY_SCORE_TOLERANCE,
):
    stage4_run = volume_mod._build_stage4_run(
        run_id,
        frame_rows,
        sample_count=sample_count,
        extra_frame_indices=extra_frame_indices,
        search_width_frac=search_width_frac,
        search_top_frac=search_top_frac,
        search_bottom_frac=search_bottom_frac,
        blur_sigma=blur_sigma,
        residual_threshold=residual_threshold,
        shift_threshold_px=shift_threshold_px,
        confidence_threshold=confidence_threshold,
        roi_width_frac=roi_width_frac,
        roi_top_frac=roi_top_frac,
        roi_bottom_frac=roi_bottom_frac,
        corridor_width_frac=corridor_width_frac,
        nozzle_guard_px=nozzle_guard_px,
        min_component_area_px=min_component_area_px,
    )
    phase_feature_rows = _build_phase_feature_rows(
        stage4_run,
        near_nozzle_band_top_px=int(near_nozzle_band_top_px),
        near_nozzle_band_height_px=int(near_nozzle_band_height_px),
        min_band_valid_rows=int(min_band_valid_rows),
        width_smooth_window=int(width_smooth_window),
    )
    stage5_run = _build_stage5_from_phase_inputs(
        run_id,
        _phase_input_rows_from_feature_rows(phase_feature_rows),
        steady_fit_payload={},
        fov_report=dict(stage4_run["fov_report"]),
        trusted_visible_volume_nl=None,
        first_untrusted_delay_from_emergence_us=_int_or_none(
            stage4_run["fov_report"].get("first_fov_exit_delay_from_emergence_us")
        ),
        width_smooth_window=int(width_smooth_window),
        tail_drop_frac=float(tail_drop_frac),
        tail_persist_frames=int(tail_persist_frames),
        steady_fit_mode=str(steady_fit_mode),
        steady_fit_exclude_last_trusted_frames=int(steady_fit_exclude_last_trusted_frames),
        min_steady_frames=int(min_steady_frames),
        steady_width_tol_frac=float(steady_width_tol_frac),
        steady_width_tol_px=float(steady_width_tol_px),
        flow_fit_backfill_max_frames=int(flow_fit_backfill_max_frames),
        flow_fit_backfill_width_delta_px=float(flow_fit_backfill_width_delta_px),
        flow_fit_backfill_monotonic_slack_px=float(flow_fit_backfill_monotonic_slack_px),
        tail_start_mode=str(tail_start_mode),
        tail_direct_target_drop_to_threshold_frac=float(
            tail_direct_target_drop_to_threshold_frac
        ),
        tail_direct_target_peak_lead_us=float(tail_direct_target_peak_lead_us),
        tail_direct_target_shrink_rate_ratio=float(tail_direct_target_shrink_rate_ratio),
        tail_shoulder_target_drop_to_threshold_frac=float(
            tail_shoulder_target_drop_to_threshold_frac
        ),
        tail_shoulder_target_peak_lead_us=float(tail_shoulder_target_peak_lead_us),
        tail_shoulder_target_shrink_rate_ratio=float(tail_shoulder_target_shrink_rate_ratio),
        tail_score_drop_weight=float(tail_score_drop_weight),
        tail_score_peak_lead_weight=float(tail_score_peak_lead_weight),
        tail_score_shrink_rate_weight=float(tail_score_shrink_rate_weight),
        tail_score_drop_scale=float(tail_score_drop_scale),
        tail_score_peak_lead_scale_us=float(tail_score_peak_lead_scale_us),
        tail_score_shrink_rate_scale=float(tail_score_shrink_rate_scale),
        tail_unified_band_drop_min=float(tail_unified_band_drop_min),
        tail_unified_band_drop_max=float(tail_unified_band_drop_max),
        tail_unified_band_peak_lead_min_us=float(tail_unified_band_peak_lead_min_us),
        tail_unified_band_peak_lead_max_us=float(tail_unified_band_peak_lead_max_us),
        tail_unified_band_shrink_rate_ratio_min=float(
            tail_unified_band_shrink_rate_ratio_min
        ),
        tail_unified_band_shrink_rate_ratio_max=float(
            tail_unified_band_shrink_rate_ratio_max
        ),
        tail_unified_target_drop_to_threshold_frac=float(
            tail_unified_target_drop_to_threshold_frac
        ),
        tail_unified_target_peak_lead_us=float(tail_unified_target_peak_lead_us),
        tail_unified_target_shrink_rate_ratio=float(tail_unified_target_shrink_rate_ratio),
        volume_uncertainty_sample_count=int(volume_uncertainty_sample_count),
        volume_uncertainty_seed=int(volume_uncertainty_seed),
        tail_uncertainty_score_tolerance=float(tail_uncertainty_score_tolerance),
        steady_fit_r2_min=float(steady_fit_r2_min),
        steady_fit_nrmse_max=float(steady_fit_nrmse_max),
    )
    stage5_run["stage4_run"] = stage4_run
    return stage5_run


def _stage5_parameter_payload(
    *,
    sample_count: int,
    extra_frame_indices: list[int] | None,
    search_width_frac: float,
    search_top_frac: float,
    search_bottom_frac: float,
    blur_sigma: float,
    residual_threshold: int,
    shift_threshold_px: float,
    confidence_threshold: float,
    roi_width_frac: float,
    roi_top_frac: float,
    roi_bottom_frac: float,
    corridor_width_frac: float,
    nozzle_guard_px: int,
    min_component_area_px: int,
    near_nozzle_band_top_px: int,
    near_nozzle_band_height_px: int,
    min_band_valid_rows: int,
    width_smooth_window: int,
    min_steady_frames: int,
    steady_width_tol_frac: float,
    steady_width_tol_px: float,
    steady_fit_r2_min: float,
    steady_fit_nrmse_max: float,
    steady_fit_mode: str,
    steady_fit_exclude_last_trusted_frames: int,
    flow_fit_backfill_max_frames: int,
    flow_fit_backfill_width_delta_px: float,
    flow_fit_backfill_monotonic_slack_px: float,
    tail_drop_frac: float,
    tail_persist_frames: int,
    tail_start_mode: str,
    tail_direct_target_drop_to_threshold_frac: float,
    tail_direct_target_peak_lead_us: float,
    tail_direct_target_shrink_rate_ratio: float,
    tail_shoulder_target_drop_to_threshold_frac: float,
    tail_shoulder_target_peak_lead_us: float,
    tail_shoulder_target_shrink_rate_ratio: float,
    tail_score_drop_weight: float,
    tail_score_peak_lead_weight: float,
    tail_score_shrink_rate_weight: float,
    tail_score_drop_scale: float,
    tail_score_peak_lead_scale_us: float,
    tail_score_shrink_rate_scale: float,
    tail_unified_band_drop_min: float,
    tail_unified_band_drop_max: float,
    tail_unified_band_peak_lead_min_us: float,
    tail_unified_band_peak_lead_max_us: float,
    tail_unified_band_shrink_rate_ratio_min: float,
    tail_unified_band_shrink_rate_ratio_max: float,
    tail_unified_target_drop_to_threshold_frac: float,
    tail_unified_target_peak_lead_us: float,
    tail_unified_target_shrink_rate_ratio: float,
    volume_uncertainty_sample_count: int,
    volume_uncertainty_seed: int,
    tail_uncertainty_score_tolerance: float,
):
    return {
        "sample_count": int(sample_count),
        "extra_frame_indices": list(extra_frame_indices or []),
        "search_width_frac": float(search_width_frac),
        "search_top_frac": float(search_top_frac),
        "search_bottom_frac": float(search_bottom_frac),
        "blur_sigma": float(blur_sigma),
        "residual_threshold": int(residual_threshold),
        "shift_threshold_px": float(shift_threshold_px),
        "confidence_threshold": float(confidence_threshold),
        "roi_width_frac": float(roi_width_frac),
        "roi_top_frac": float(roi_top_frac),
        "roi_bottom_frac": float(roi_bottom_frac),
        "corridor_width_frac": float(corridor_width_frac),
        "nozzle_guard_px": int(nozzle_guard_px),
        "min_component_area_px": int(min_component_area_px),
        "near_nozzle_band_top_px": int(near_nozzle_band_top_px),
        "near_nozzle_band_height_px": int(near_nozzle_band_height_px),
        "min_band_valid_rows": int(min_band_valid_rows),
        "width_smooth_window": int(width_smooth_window),
        "min_steady_frames": int(min_steady_frames),
        "steady_width_tol_frac": float(steady_width_tol_frac),
        "steady_width_tol_px": float(steady_width_tol_px),
        "steady_fit_r2_min": float(steady_fit_r2_min),
        "steady_fit_nrmse_max": float(steady_fit_nrmse_max),
        "steady_fit_mode": str(steady_fit_mode),
        "steady_fit_exclude_last_trusted_frames": int(steady_fit_exclude_last_trusted_frames),
        "flow_fit_backfill_max_frames": int(flow_fit_backfill_max_frames),
        "flow_fit_backfill_width_delta_px": float(flow_fit_backfill_width_delta_px),
        "flow_fit_backfill_monotonic_slack_px": float(flow_fit_backfill_monotonic_slack_px),
        "tail_drop_frac": float(tail_drop_frac),
        "tail_persist_frames": int(tail_persist_frames),
        "tail_start_mode": str(tail_start_mode),
        "tail_direct_target_drop_to_threshold_frac": float(
            tail_direct_target_drop_to_threshold_frac
        ),
        "tail_direct_target_peak_lead_us": float(tail_direct_target_peak_lead_us),
        "tail_direct_target_shrink_rate_ratio": float(tail_direct_target_shrink_rate_ratio),
        "tail_shoulder_target_drop_to_threshold_frac": float(
            tail_shoulder_target_drop_to_threshold_frac
        ),
        "tail_shoulder_target_peak_lead_us": float(tail_shoulder_target_peak_lead_us),
        "tail_shoulder_target_shrink_rate_ratio": float(tail_shoulder_target_shrink_rate_ratio),
        "tail_score_drop_weight": float(tail_score_drop_weight),
        "tail_score_peak_lead_weight": float(tail_score_peak_lead_weight),
        "tail_score_shrink_rate_weight": float(tail_score_shrink_rate_weight),
        "tail_score_drop_scale": float(tail_score_drop_scale),
        "tail_score_peak_lead_scale_us": float(tail_score_peak_lead_scale_us),
        "tail_score_shrink_rate_scale": float(tail_score_shrink_rate_scale),
        "tail_unified_band_drop_min": float(tail_unified_band_drop_min),
        "tail_unified_band_drop_max": float(tail_unified_band_drop_max),
        "tail_unified_band_peak_lead_min_us": float(tail_unified_band_peak_lead_min_us),
        "tail_unified_band_peak_lead_max_us": float(tail_unified_band_peak_lead_max_us),
        "tail_unified_band_shrink_rate_ratio_min": float(
            tail_unified_band_shrink_rate_ratio_min
        ),
        "tail_unified_band_shrink_rate_ratio_max": float(
            tail_unified_band_shrink_rate_ratio_max
        ),
        "tail_unified_target_drop_to_threshold_frac": float(
            tail_unified_target_drop_to_threshold_frac
        ),
        "tail_unified_target_peak_lead_us": float(tail_unified_target_peak_lead_us),
        "tail_unified_target_shrink_rate_ratio": float(tail_unified_target_shrink_rate_ratio),
        "volume_uncertainty_sample_count": int(volume_uncertainty_sample_count),
        "volume_uncertainty_seed": int(volume_uncertainty_seed),
        "tail_uncertainty_score_tolerance": float(tail_uncertainty_score_tolerance),
    }


def _stage5_output_paths(output_root: str | Path, run_id: str):
    stage_dir = Path(output_root).expanduser().resolve() / "runs" / str(run_id) / FIT_STAGE_DIRNAME
    return {
        "stage_dir": stage_dir,
        "phase_features_csv": stage_dir / "phase_features.csv",
        "tail_start_candidates_csv": stage_dir / "tail_start_candidates.csv",
        "phase_boundaries_json": stage_dir / "phase_boundaries.json",
        "steady_fit_json": stage_dir / "steady_fit.json",
        "middle_extrapolation_json": stage_dir / "middle_extrapolation.json",
        "vt_fit_png": stage_dir / "Vt_fit.png",
        "width_trace_png": stage_dir / "width_trace.png",
        "fit_manifest_json": stage_dir / "fit_manifest.json",
    }


def _write_stage5_outputs(
    output_root: str | Path,
    run_id: str,
    stage5_run: dict,
    *,
    run_dir: str | None = None,
    parameters: dict | None = None,
    analysis_source_mode: str,
    cache_source_kind: str | None = None,
    phase_input_csv: str | Path | None = None,
    run_context_json: str | Path | None = None,
    referenced_stage4_fit_output_root: str | None = None,
    referenced_stage4_manifest_json: str | None = None,
    referenced_stage5_fit_output_root: str | None = None,
    referenced_stage5_manifest_json: str | None = None,
    stage4_summary: dict | None = None,
    shift_events: list[dict] | None = None,
):
    stage4_run = dict(stage5_run.get("stage4_run") or {})
    feature_rows = list(stage5_run.get("phase_feature_rows") or [])
    tail_start_candidate_rows = list(stage5_run.get("tail_start_candidate_rows") or [])
    resolved_steady_fit = dict(stage5_run.get("steady_fit") or {})
    if not resolved_steady_fit:
        resolved_steady_fit = _steady_fit_from_payload(
            feature_rows,
            dict(stage5_run.get("steady_fit_payload") or {}),
        )
    resolved_tail_onset = dict(stage5_run.get("tail_onset") or {})
    if not resolved_tail_onset:
        summary = dict(stage5_run.get("summary") or {})
        phase_boundaries = dict(stage5_run.get("phase_boundaries") or {})
        resolved_tail_onset = {
            "tail_confirmation_capture_index": summary.get("tail_confirmation_capture_index")
            or phase_boundaries.get("tail_confirmation_capture_index"),
            "tail_confirmation_delay_from_emergence_us": summary.get(
                "tail_confirmation_delay_from_emergence_us"
            )
            or phase_boundaries.get("tail_confirmation_delay_from_emergence_us"),
            "tail_detection_mode": summary.get("tail_detection_mode")
            or phase_boundaries.get("tail_detection_mode"),
            "tail_start_selection_mode": summary.get("tail_start_selection_mode")
            or phase_boundaries.get("tail_start_selection_mode"),
            "preliminary_tail_start_capture_index": summary.get(
                "preliminary_tail_start_capture_index"
            )
            or phase_boundaries.get("preliminary_tail_start_capture_index"),
            "preliminary_tail_start_delay_from_emergence_us": summary.get(
                "preliminary_tail_start_delay_from_emergence_us"
            )
            or phase_boundaries.get("preliminary_tail_start_delay_from_emergence_us"),
            "direct_final_tail_start_capture_index": summary.get(
                "direct_final_tail_start_capture_index"
            )
            or phase_boundaries.get("direct_final_tail_start_capture_index"),
            "direct_final_tail_start_delay_from_emergence_us": summary.get(
                "direct_final_tail_start_delay_from_emergence_us"
            )
            or phase_boundaries.get("direct_final_tail_start_delay_from_emergence_us"),
            "tail_shoulder_end_capture_index": summary.get("tail_shoulder_end_capture_index")
            or phase_boundaries.get("tail_shoulder_end_capture_index"),
            "tail_shoulder_end_delay_from_emergence_us": summary.get(
                "tail_shoulder_end_delay_from_emergence_us"
            )
            or phase_boundaries.get("tail_shoulder_end_delay_from_emergence_us"),
            "tail_start_capture_index": summary.get("tail_start_capture_index")
            or phase_boundaries.get("tail_start_capture_index"),
            "tail_start_delay_from_emergence_us": summary.get("tail_start_delay_from_emergence_us")
            or phase_boundaries.get("tail_start_delay_from_emergence_us"),
            "tail_onset_status": summary.get("tail_onset_status"),
        }
    resolved_middle = dict(stage5_run.get("middle_extrapolation") or {})
    if not resolved_middle:
        resolved_middle = dict(stage5_run.get("middle_payload") or {})
    paths = _stage5_output_paths(output_root, run_id)
    paths["stage_dir"].mkdir(parents=True, exist_ok=True)

    _write_csv(
        paths["phase_features_csv"],
        _preferred_columns(feature_rows, PHASE_FEATURE_COLUMNS),
        feature_rows,
    )
    _write_csv(
        paths["tail_start_candidates_csv"],
        _preferred_columns(tail_start_candidate_rows, TAIL_START_CANDIDATE_COLUMNS),
        tail_start_candidate_rows,
    )
    _write_json(paths["phase_boundaries_json"], stage5_run["phase_boundaries"])
    _write_json(paths["steady_fit_json"], stage5_run["steady_fit_payload"])
    _write_json(paths["middle_extrapolation_json"], stage5_run["middle_payload"])
    _plot_vt_fit(
        paths["vt_fit_png"],
        feature_rows,
        run_id=run_id,
        steady_fit=resolved_steady_fit,
        middle=resolved_middle,
        fov_report=stage4_run.get("fov_report") or {},
        tail_onset=resolved_tail_onset,
    )
    _plot_width_trace(
        paths["width_trace_png"],
        feature_rows,
        run_id=run_id,
        steady_fit=resolved_steady_fit,
        tail_onset=resolved_tail_onset,
        fov_report=stage4_run.get("fov_report") or {},
    )

    resolved_parameters = dict(parameters or {})
    run_manifest = {
        "schema_version": 1,
        "stage": "fit",
        "run_id": run_id,
        "run_dir": run_dir,
        "volume_unit": "nL",
        "analysis_source_mode": str(analysis_source_mode),
        "cache_source_kind": cache_source_kind,
        "phase_input_csv": None if phase_input_csv is None else str(phase_input_csv),
        "run_context_json": None if run_context_json is None else str(run_context_json),
        "referenced_stage4_fit_output_root": referenced_stage4_fit_output_root,
        "referenced_stage4_manifest_json": referenced_stage4_manifest_json,
        "referenced_stage5_fit_output_root": referenced_stage5_fit_output_root,
        "referenced_stage5_manifest_json": referenced_stage5_manifest_json,
        "parameters": resolved_parameters,
        **resolved_parameters,
        "outputs": {
            "phase_features_csv": str(paths["phase_features_csv"]),
            "tail_start_candidates_csv": str(paths["tail_start_candidates_csv"]),
            "phase_boundaries_json": str(paths["phase_boundaries_json"]),
            "steady_fit_json": str(paths["steady_fit_json"]),
            "middle_extrapolation_json": str(paths["middle_extrapolation_json"]),
            "vt_fit_png": str(paths["vt_fit_png"]),
            "width_trace_png": str(paths["width_trace_png"]),
        },
        "summary": dict(stage5_run["summary"]),
        "fov_report": dict(stage4_run.get("fov_report") or {}),
        "stage4_summary": dict(stage4_summary or stage4_run.get("summary_counts") or {}),
        "shift_events": list(shift_events or stage4_run.get("shift_events") or []),
    }
    _write_json(paths["fit_manifest_json"], run_manifest)
    paths["fit_manifest"] = run_manifest
    return paths


def export_stage5_fit(
    experiment_root: str | Path,
    *,
    output_root: str | Path | None = None,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
    include_unmatched: bool = False,
    sample_count: int = 6,
    extra_frame_indices: list[int] | None = None,
    search_width_frac: float = 0.22,
    search_top_frac: float = 0.08,
    search_bottom_frac: float = 0.30,
    blur_sigma: float = 12.0,
    residual_threshold: int = 18,
    shift_threshold_px: float = 6.0,
    confidence_threshold: float = 0.55,
    roi_width_frac: float = 0.35,
    roi_top_frac: float = 0.10,
    roi_bottom_frac: float = 1.0,
    corridor_width_frac: float = 0.70,
    nozzle_guard_px: int = 2,
    min_component_area_px: int = 120,
    near_nozzle_band_top_px: int = 24,
    near_nozzle_band_height_px: int = 40,
    min_band_valid_rows: int = 24,
    width_smooth_window: int = 5,
    min_steady_frames: int = 8,
    steady_width_tol_frac: float = 0.08,
    steady_width_tol_px: float = 4.0,
    steady_fit_r2_min: float = 0.985,
    steady_fit_nrmse_max: float = 0.03,
    steady_fit_mode: str = "recompute",
    steady_fit_exclude_last_trusted_frames: int = 2,
    flow_fit_backfill_max_frames: int = 3,
    flow_fit_backfill_width_delta_px: float = 8.0,
    flow_fit_backfill_monotonic_slack_px: float = 0.75,
    tail_drop_frac: float = 0.08,
    tail_persist_frames: int = 3,
    tail_start_mode: str = TAIL_START_MODE_DESCRIPTOR_UNIFIED,
    tail_direct_target_drop_to_threshold_frac: float = TAIL_DIRECT_TARGET_DROP_TO_THRESHOLD_FRAC,
    tail_direct_target_peak_lead_us: float = TAIL_DIRECT_TARGET_PEAK_LEAD_US,
    tail_direct_target_shrink_rate_ratio: float = TAIL_DIRECT_TARGET_SHRINK_RATE_RATIO,
    tail_shoulder_target_drop_to_threshold_frac: float = TAIL_SHOULDER_TARGET_DROP_TO_THRESHOLD_FRAC,
    tail_shoulder_target_peak_lead_us: float = TAIL_SHOULDER_TARGET_PEAK_LEAD_US,
    tail_shoulder_target_shrink_rate_ratio: float = TAIL_SHOULDER_TARGET_SHRINK_RATE_RATIO,
    tail_score_drop_weight: float = TAIL_SCORE_DROP_WEIGHT,
    tail_score_peak_lead_weight: float = TAIL_SCORE_PEAK_LEAD_WEIGHT,
    tail_score_shrink_rate_weight: float = TAIL_SCORE_SHRINK_RATE_WEIGHT,
    tail_score_drop_scale: float = TAIL_SCORE_DROP_SCALE,
    tail_score_peak_lead_scale_us: float = TAIL_SCORE_PEAK_LEAD_SCALE_US,
    tail_score_shrink_rate_scale: float = TAIL_SCORE_SHRINK_RATE_SCALE,
    tail_unified_band_drop_min: float = TAIL_UNIFIED_BAND_DROP_MIN,
    tail_unified_band_drop_max: float = TAIL_UNIFIED_BAND_DROP_MAX,
    tail_unified_band_peak_lead_min_us: float = TAIL_UNIFIED_BAND_PEAK_LEAD_MIN_US,
    tail_unified_band_peak_lead_max_us: float = TAIL_UNIFIED_BAND_PEAK_LEAD_MAX_US,
    tail_unified_band_shrink_rate_ratio_min: float = TAIL_UNIFIED_BAND_SHRINK_RATE_RATIO_MIN,
    tail_unified_band_shrink_rate_ratio_max: float = TAIL_UNIFIED_BAND_SHRINK_RATE_RATIO_MAX,
    tail_unified_target_drop_to_threshold_frac: float = TAIL_UNIFIED_TARGET_DROP_TO_THRESHOLD_FRAC,
    tail_unified_target_peak_lead_us: float = TAIL_UNIFIED_TARGET_PEAK_LEAD_US,
    tail_unified_target_shrink_rate_ratio: float = TAIL_UNIFIED_TARGET_SHRINK_RATE_RATIO,
    volume_uncertainty_sample_count: int = VOLUME_UNCERTAINTY_SAMPLE_COUNT,
    volume_uncertainty_seed: int = VOLUME_UNCERTAINTY_SEED,
    tail_uncertainty_score_tolerance: float = TAIL_UNCERTAINTY_SCORE_TOLERANCE,
):
    inventory = build_stage0_inventory(
        experiment_root,
        include_unmatched=include_unmatched,
        run_ids=run_ids,
        limit_runs=limit_runs,
    )

    output_path = (
        Path(output_root).expanduser().resolve()
        if output_root
        else default_output_root(experiment_root)
    )
    output_path.mkdir(parents=True, exist_ok=True)
    parameter_payload = _stage5_parameter_payload(
        sample_count=sample_count,
        extra_frame_indices=extra_frame_indices,
        search_width_frac=search_width_frac,
        search_top_frac=search_top_frac,
        search_bottom_frac=search_bottom_frac,
        blur_sigma=blur_sigma,
        residual_threshold=residual_threshold,
        shift_threshold_px=shift_threshold_px,
        confidence_threshold=confidence_threshold,
        roi_width_frac=roi_width_frac,
        roi_top_frac=roi_top_frac,
        roi_bottom_frac=roi_bottom_frac,
        corridor_width_frac=corridor_width_frac,
        nozzle_guard_px=nozzle_guard_px,
        min_component_area_px=min_component_area_px,
        near_nozzle_band_top_px=near_nozzle_band_top_px,
        near_nozzle_band_height_px=near_nozzle_band_height_px,
        min_band_valid_rows=min_band_valid_rows,
        width_smooth_window=width_smooth_window,
        min_steady_frames=min_steady_frames,
        steady_width_tol_frac=steady_width_tol_frac,
        steady_width_tol_px=steady_width_tol_px,
        steady_fit_r2_min=steady_fit_r2_min,
        steady_fit_nrmse_max=steady_fit_nrmse_max,
        steady_fit_mode=steady_fit_mode,
        steady_fit_exclude_last_trusted_frames=steady_fit_exclude_last_trusted_frames,
        flow_fit_backfill_max_frames=flow_fit_backfill_max_frames,
        flow_fit_backfill_width_delta_px=flow_fit_backfill_width_delta_px,
        flow_fit_backfill_monotonic_slack_px=flow_fit_backfill_monotonic_slack_px,
        tail_drop_frac=tail_drop_frac,
        tail_persist_frames=tail_persist_frames,
        tail_start_mode=tail_start_mode,
        tail_direct_target_drop_to_threshold_frac=tail_direct_target_drop_to_threshold_frac,
        tail_direct_target_peak_lead_us=tail_direct_target_peak_lead_us,
        tail_direct_target_shrink_rate_ratio=tail_direct_target_shrink_rate_ratio,
        tail_shoulder_target_drop_to_threshold_frac=tail_shoulder_target_drop_to_threshold_frac,
        tail_shoulder_target_peak_lead_us=tail_shoulder_target_peak_lead_us,
        tail_shoulder_target_shrink_rate_ratio=tail_shoulder_target_shrink_rate_ratio,
        tail_score_drop_weight=tail_score_drop_weight,
        tail_score_peak_lead_weight=tail_score_peak_lead_weight,
        tail_score_shrink_rate_weight=tail_score_shrink_rate_weight,
        tail_score_drop_scale=tail_score_drop_scale,
        tail_score_peak_lead_scale_us=tail_score_peak_lead_scale_us,
        tail_score_shrink_rate_scale=tail_score_shrink_rate_scale,
        tail_unified_band_drop_min=tail_unified_band_drop_min,
        tail_unified_band_drop_max=tail_unified_band_drop_max,
        tail_unified_band_peak_lead_min_us=tail_unified_band_peak_lead_min_us,
        tail_unified_band_peak_lead_max_us=tail_unified_band_peak_lead_max_us,
        tail_unified_band_shrink_rate_ratio_min=tail_unified_band_shrink_rate_ratio_min,
        tail_unified_band_shrink_rate_ratio_max=tail_unified_band_shrink_rate_ratio_max,
        tail_unified_target_drop_to_threshold_frac=tail_unified_target_drop_to_threshold_frac,
        tail_unified_target_peak_lead_us=tail_unified_target_peak_lead_us,
        tail_unified_target_shrink_rate_ratio=tail_unified_target_shrink_rate_ratio,
        volume_uncertainty_sample_count=volume_uncertainty_sample_count,
        volume_uncertainty_seed=volume_uncertainty_seed,
        tail_uncertainty_score_tolerance=tail_uncertainty_score_tolerance,
    )

    run_manifests = []
    for run_row in inventory["selected_runs"]:
        run_id = str(run_row["run_id"])
        frame_rows = list(inventory["frames_by_run_id"][run_id])
        if not frame_rows:
            raise ValueError(f"No frame index rows available for run: {run_id}")

        stage5_run = _build_stage5_run(
            run_id,
            frame_rows,
            **parameter_payload,
        )
        output_paths = _write_stage5_outputs(
            output_path,
            run_id,
            stage5_run,
            run_dir=run_row.get("run_dir"),
            parameters=parameter_payload,
            analysis_source_mode="raw",
        )

        run_manifests.append(
            {
                "run_id": run_id,
                "run_dir": run_row["run_dir"],
                "phase_features_csv": str(output_paths["phase_features_csv"]),
                "tail_start_candidates_csv": str(output_paths["tail_start_candidates_csv"]),
                "phase_boundaries_json": str(output_paths["phase_boundaries_json"]),
                "steady_fit_json": str(output_paths["steady_fit_json"]),
                "middle_extrapolation_json": str(output_paths["middle_extrapolation_json"]),
                "vt_fit_png": str(output_paths["vt_fit_png"]),
                "width_trace_png": str(output_paths["width_trace_png"]),
                "fit_manifest_json": str(output_paths["fit_manifest_json"]),
                "phase_feature_row_count": len(stage5_run["phase_feature_rows"]),
                "steady_fit_status": stage5_run["steady_fit"].get("steady_fit_status"),
                "tail_onset_status": stage5_run["tail_onset"].get("tail_onset_status"),
                "tail_detection_mode": stage5_run["tail_onset"].get("tail_detection_mode"),
                "tail_start_selection_mode": stage5_run["tail_onset"].get(
                    "tail_start_selection_mode"
                ),
                "tail_confirmation_capture_index": stage5_run["tail_onset"].get(
                    "tail_confirmation_capture_index"
                ),
                "tail_shoulder_end_capture_index": stage5_run["tail_onset"].get(
                    "tail_shoulder_end_capture_index"
                ),
                "tail_start_capture_index": stage5_run["tail_onset"].get(
                    "tail_start_capture_index"
                ),
                "middle_extrapolation_status": stage5_run["middle_extrapolation"].get(
                    "middle_extrapolation_status"
                ),
                "partial_total_without_tail_nl": stage5_run["middle_extrapolation"].get(
                    "partial_total_without_tail_nl"
                ),
            }
        )

    manifest = {
        "schema_version": 1,
        "stage": "fit",
        "experiment_root": inventory["experiment_root"],
        "output_root": str(output_path),
        "selected_run_count": len(run_manifests),
        "run_ids": [row["run_id"] for row in run_manifests],
        "volume_unit": "nL",
        **parameter_payload,
        "runs": run_manifests,
    }
    manifest_path = output_path / "fit_manifest.json"
    _write_json(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest


