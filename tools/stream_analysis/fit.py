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
    "tail_start_frame",
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


def _steady_window_metrics(
    window_rows: list[dict],
    *,
    steady_width_tol_frac: float,
    steady_width_tol_px: float,
):
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
    smoothed_widths = np.asarray(
        [row.get("attached_near_nozzle_width_smoothed_px") for row in window_rows],
        dtype=float,
    )
    if np.any(np.isnan(smoothed_widths)):
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
    width_plateau_px = float(np.median(smoothed_widths))
    width_span_px = float(np.max(smoothed_widths) - np.min(smoothed_widths))
    width_tolerance_px = float(
        max(float(steady_width_tol_px), float(steady_width_tol_frac) * float(width_plateau_px))
    )

    return {
        "steady_rate_nl_per_us": float(slope),
        "steady_intercept_nl": float(intercept),
        "steady_r2": r2,
        "steady_nrmse": nrmse,
        "steady_width_plateau_px": width_plateau_px,
        "steady_width_span_px": width_span_px,
        "steady_width_tolerance_px": width_tolerance_px,
        "steady_fit_ok": bool(width_span_px <= width_tolerance_px),
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
            if metrics is None:
                continue
            if not (
                bool(metrics["steady_fit_ok"])
                and float(metrics["steady_r2"]) >= float(steady_fit_r2_min)
                and float(metrics["steady_nrmse"]) <= float(steady_fit_nrmse_max)
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
                if trial_metrics is None:
                    break
                if not (
                    bool(trial_metrics["steady_fit_ok"])
                    and float(trial_metrics["steady_r2"]) >= float(steady_fit_r2_min)
                    and float(trial_metrics["steady_nrmse"]) <= float(steady_fit_nrmse_max)
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
    if _clean_text(steady_fit.get("steady_fit_status")) != "ok":
        return {
            "tail_start_capture_index": None,
            "tail_start_delay_from_emergence_us": None,
            "tail_onset_status": "unresolved",
            "tail_width_threshold_px": None,
            "tail_candidate_positions": set(),
            "tail_start_position": None,
        }

    steady_end_capture_index = _int_or_none(steady_fit.get("steady_end_capture_index"))
    steady_width_plateau_px = steady_fit.get("steady_width_plateau_px")
    if steady_end_capture_index is None or steady_width_plateau_px is None:
        return {
            "tail_start_capture_index": None,
            "tail_start_delay_from_emergence_us": None,
            "tail_onset_status": "unresolved",
            "tail_width_threshold_px": None,
            "tail_candidate_positions": set(),
            "tail_start_position": None,
        }

    threshold_px = float((1.0 - float(tail_drop_frac)) * float(steady_width_plateau_px))
    candidate_positions = set()
    streak_positions = []
    previous_capture_index = None

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
            tail_start_position = int(streak_positions[0])
            tail_start_row = feature_rows[tail_start_position]
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
                "tail_onset_status": tail_onset_status,
                "tail_width_threshold_px": threshold_px,
                "tail_candidate_positions": candidate_positions,
                "tail_start_position": tail_start_position,
            }

    return {
        "tail_start_capture_index": None,
        "tail_start_delay_from_emergence_us": None,
        "tail_onset_status": "not_needed_no_fov_exit" if first_untrusted_capture_index is None else "unresolved",
        "tail_width_threshold_px": threshold_px,
        "tail_candidate_positions": candidate_positions,
        "tail_start_position": None,
    }


def _middle_extrapolation(
    feature_rows: list[dict],
    steady_fit: dict,
    tail_onset: dict,
    fov_report: dict,
):
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
        start_row = _row_by_capture_index(feature_rows, int(first_untrusted_capture_index))
        end_row = _row_by_capture_index(feature_rows, int(tail_start_capture_index))
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


def _apply_phase_labels(feature_rows: list[dict], steady_fit: dict, tail_onset: dict):
    steady_positions = set(steady_fit.get("positions") or [])
    tail_candidate_positions = set(tail_onset.get("tail_candidate_positions") or set())
    tail_start_position = tail_onset.get("tail_start_position")
    steady_end_capture_index = _int_or_none(steady_fit.get("steady_end_capture_index"))
    tail_start_capture_index = _int_or_none(tail_onset.get("tail_start_capture_index"))

    for position, row in enumerate(feature_rows):
        capture_index = _int_or_none(row.get("capture_index"))
        row["steady_selected"] = bool(position in steady_positions)
        row["tail_drop_candidate"] = bool(position in tail_candidate_positions)
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

    steady_positions = list(steady_fit.get("positions") or [])
    if steady_positions and _clean_text(steady_fit.get("steady_fit_status")) == "ok":
        steady_x = []
        steady_y = []
        for position in steady_positions:
            x_value = _time_axis_value(feature_rows[position], allow_flash_fallback=False)
            if x_value is None:
                continue
            steady_x.append(float(x_value))
            steady_y.append(
                float(steady_fit["steady_intercept_nl"]) + (float(steady_fit["steady_rate_nl_per_us"]) * float(x_value))
            )
        if steady_x:
            ax.plot(steady_x, steady_y, color="#0f766e", linewidth=2.0, label="steady fit")

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
        (steady_fit.get("steady_start_capture_index"), "steady start", "#228b22", "--"),
        (steady_fit.get("steady_end_capture_index"), "steady end", "#228b22", "-."),
        (fov_report.get("first_untrusted_capture_index"), "first untrusted", "#d62728", "--"),
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

    ax.set_title(f"Visible Volume Fit V(t) - {run_id}")
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
        "steady_start_capture_index": steady_fit.get("steady_start_capture_index"),
        "steady_end_capture_index": steady_fit.get("steady_end_capture_index"),
        "steady_rate_nl_per_us": steady_fit.get("steady_rate_nl_per_us"),
        "steady_intercept_nl": steady_fit.get("steady_intercept_nl"),
        "steady_r2": steady_fit.get("steady_r2"),
        "steady_nrmse": steady_fit.get("steady_nrmse"),
        "steady_width_plateau_px": steady_fit.get("steady_width_plateau_px"),
        "tail_start_capture_index": tail_onset.get("tail_start_capture_index"),
        "tail_start_delay_from_emergence_us": tail_onset.get("tail_start_delay_from_emergence_us"),
        "tail_onset_status": tail_onset.get("tail_onset_status"),
        "trusted_visible_volume_nl": middle.get("trusted_visible_volume_nl"),
        "middle_extrapolated_volume_nl": middle.get("middle_extrapolated_volume_nl"),
        "partial_total_without_tail_nl": middle.get("partial_total_without_tail_nl"),
        "tail_volume_nl": middle.get("tail_volume_nl"),
        "middle_extrapolation_status": middle.get("middle_extrapolation_status"),
        "final_total_status": middle.get("final_total_status"),
    }


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
    tail_drop_frac: float = 0.08,
    tail_persist_frames: int = 3,
):
    inventory = build_stage0_inventory(
        experiment_root,
        include_unmatched=include_unmatched,
        run_ids=run_ids,
        limit_runs=limit_runs,
    )

    output_path = Path(output_root).expanduser().resolve() if output_root else default_output_root(experiment_root)
    output_path.mkdir(parents=True, exist_ok=True)

    run_manifests = []
    for run_row in inventory["selected_runs"]:
        run_id = str(run_row["run_id"])
        frame_rows = list(inventory["frames_by_run_id"][run_id])
        if not frame_rows:
            raise ValueError(f"No frame index rows available for run: {run_id}")

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

        feature_rows = _build_phase_feature_rows(
            stage4_run,
            near_nozzle_band_top_px=int(near_nozzle_band_top_px),
            near_nozzle_band_height_px=int(near_nozzle_band_height_px),
            min_band_valid_rows=int(min_band_valid_rows),
            width_smooth_window=int(width_smooth_window),
        )
        steady_fit = _find_steady_window(
            feature_rows,
            min_steady_frames=int(min_steady_frames),
            steady_width_tol_frac=float(steady_width_tol_frac),
            steady_width_tol_px=float(steady_width_tol_px),
            steady_fit_r2_min=float(steady_fit_r2_min),
            steady_fit_nrmse_max=float(steady_fit_nrmse_max),
        )
        tail_onset = _find_tail_onset(
            feature_rows,
            steady_fit,
            first_untrusted_capture_index=_int_or_none(
                stage4_run["fov_report"].get("first_untrusted_capture_index")
            ),
            tail_drop_frac=float(tail_drop_frac),
            tail_persist_frames=int(tail_persist_frames),
        )
        middle = _middle_extrapolation(
            feature_rows,
            steady_fit,
            tail_onset,
            dict(stage4_run["fov_report"]),
        )
        _apply_phase_labels(feature_rows, steady_fit, tail_onset)

        steady_start_row = _row_by_capture_index(
            feature_rows,
            _int_or_none(steady_fit.get("steady_start_capture_index")),
        )
        steady_end_row = _row_by_capture_index(
            feature_rows,
            _int_or_none(steady_fit.get("steady_end_capture_index")),
        )
        first_untrusted_row = _row_by_capture_index(
            feature_rows,
            _int_or_none(stage4_run["fov_report"].get("first_untrusted_capture_index")),
        )
        tail_start_row = _row_by_capture_index(
            feature_rows,
            _int_or_none(tail_onset.get("tail_start_capture_index")),
        )

        phase_boundaries = {
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
            "first_untrusted_capture_index": stage4_run["fov_report"].get("first_untrusted_capture_index"),
            "first_untrusted_delay_from_emergence_us": None
            if first_untrusted_row is None
            else _int_or_none(first_untrusted_row.get("delay_from_emergence_us")),
            "tail_start_capture_index": tail_onset.get("tail_start_capture_index"),
            "tail_start_delay_from_emergence_us": tail_onset.get("tail_start_delay_from_emergence_us"),
            "tail_onset_status": tail_onset.get("tail_onset_status"),
            "middle_extrapolation_status": middle.get("middle_extrapolation_status"),
            "final_total_status": middle.get("final_total_status"),
        }

        steady_fit_payload = {
            "schema_version": 1,
            "stage": "fit",
            "run_id": run_id,
            "steady_fit_status": steady_fit.get("steady_fit_status"),
            "steady_start_capture_index": steady_fit.get("steady_start_capture_index"),
            "steady_end_capture_index": steady_fit.get("steady_end_capture_index"),
            "steady_capture_indices": [
                _int_or_none(feature_rows[position].get("capture_index"))
                for position in (steady_fit.get("positions") or [])
            ],
            "steady_rate_nl_per_us": steady_fit.get("steady_rate_nl_per_us"),
            "steady_intercept_nl": steady_fit.get("steady_intercept_nl"),
            "steady_r2": steady_fit.get("steady_r2"),
            "steady_nrmse": steady_fit.get("steady_nrmse"),
            "steady_width_plateau_px": steady_fit.get("steady_width_plateau_px"),
            "steady_width_span_px": steady_fit.get("steady_width_span_px"),
            "steady_width_tolerance_px": steady_fit.get("steady_width_tolerance_px"),
        }

        middle_payload = {
            "schema_version": 1,
            "stage": "fit",
            "run_id": run_id,
            "first_untrusted_capture_index": middle.get("first_untrusted_capture_index"),
            "first_untrusted_delay_from_emergence_us": stage4_run["fov_report"].get(
                "first_fov_exit_delay_from_emergence_us"
            )
            if middle.get("first_untrusted_capture_index") is not None
            else None,
            "tail_start_capture_index": middle.get("tail_start_capture_index"),
            "tail_start_delay_from_emergence_us": None
            if tail_start_row is None
            else _int_or_none(tail_start_row.get("delay_from_emergence_us")),
            "steady_fit_status": steady_fit.get("steady_fit_status"),
            "tail_onset_status": tail_onset.get("tail_onset_status"),
            "trusted_visible_volume_nl": middle.get("trusted_visible_volume_nl"),
            "middle_extrapolated_volume_nl": middle.get("middle_extrapolated_volume_nl"),
            "partial_total_without_tail_nl": middle.get("partial_total_without_tail_nl"),
            "tail_volume_nl": middle.get("tail_volume_nl"),
            "middle_extrapolation_status": middle.get("middle_extrapolation_status"),
            "final_total_status": middle.get("final_total_status"),
        }

        stage_dir = output_path / "runs" / run_id / FIT_STAGE_DIRNAME
        stage_dir.mkdir(parents=True, exist_ok=True)

        phase_features_csv = stage_dir / "phase_features.csv"
        phase_boundaries_json = stage_dir / "phase_boundaries.json"
        steady_fit_json = stage_dir / "steady_fit.json"
        middle_extrapolation_json = stage_dir / "middle_extrapolation.json"
        vt_fit_png = stage_dir / "Vt_fit.png"
        width_trace_png = stage_dir / "width_trace.png"
        run_manifest_json = stage_dir / "fit_manifest.json"

        _write_csv(
            phase_features_csv,
            _preferred_columns(feature_rows, PHASE_FEATURE_COLUMNS),
            feature_rows,
        )
        _write_json(phase_boundaries_json, phase_boundaries)
        _write_json(steady_fit_json, steady_fit_payload)
        _write_json(middle_extrapolation_json, middle_payload)
        _plot_vt_fit(
            vt_fit_png,
            feature_rows,
            run_id=run_id,
            steady_fit=steady_fit,
            middle=middle,
            fov_report=stage4_run["fov_report"],
            tail_onset=tail_onset,
        )
        _plot_width_trace(
            width_trace_png,
            feature_rows,
            run_id=run_id,
            steady_fit=steady_fit,
            tail_onset=tail_onset,
            fov_report=stage4_run["fov_report"],
        )

        summary = _run_phase_summary(steady_fit, tail_onset, middle)
        summary["phase_feature_row_count"] = int(len(feature_rows))
        summary["width_valid_frame_count"] = int(
            sum(
                1
                for row in feature_rows
                if row.get("attached_near_nozzle_width_median_px") is not None
            )
        )
        summary["steady_selected_frame_count"] = int(
            sum(1 for row in feature_rows if bool(row.get("steady_selected")))
        )
        summary["tail_start_capture_index"] = tail_onset.get("tail_start_capture_index")
        summary["tail_onset_status"] = tail_onset.get("tail_onset_status")

        run_manifest = {
            "schema_version": 1,
            "stage": "fit",
            "run_id": run_id,
            "run_dir": run_row["run_dir"],
            "volume_unit": "nL",
            "sample_count": int(sample_count),
            "extra_frame_indices": list(extra_frame_indices or []),
            "near_nozzle_band_top_px": int(near_nozzle_band_top_px),
            "near_nozzle_band_height_px": int(near_nozzle_band_height_px),
            "min_band_valid_rows": int(min_band_valid_rows),
            "width_smooth_window": int(width_smooth_window),
            "min_steady_frames": int(min_steady_frames),
            "steady_width_tol_frac": float(steady_width_tol_frac),
            "steady_width_tol_px": float(steady_width_tol_px),
            "steady_fit_r2_min": float(steady_fit_r2_min),
            "steady_fit_nrmse_max": float(steady_fit_nrmse_max),
            "tail_drop_frac": float(tail_drop_frac),
            "tail_persist_frames": int(tail_persist_frames),
            "outputs": {
                "phase_features_csv": str(phase_features_csv),
                "phase_boundaries_json": str(phase_boundaries_json),
                "steady_fit_json": str(steady_fit_json),
                "middle_extrapolation_json": str(middle_extrapolation_json),
                "vt_fit_png": str(vt_fit_png),
                "width_trace_png": str(width_trace_png),
            },
            "summary": summary,
            "fov_report": dict(stage4_run["fov_report"]),
            "stage4_summary": dict(stage4_run["summary_counts"]),
            "shift_events": list(stage4_run["shift_events"]),
        }
        _write_json(run_manifest_json, run_manifest)

        run_manifests.append(
            {
                "run_id": run_id,
                "run_dir": run_row["run_dir"],
                "phase_features_csv": str(phase_features_csv),
                "phase_boundaries_json": str(phase_boundaries_json),
                "steady_fit_json": str(steady_fit_json),
                "middle_extrapolation_json": str(middle_extrapolation_json),
                "vt_fit_png": str(vt_fit_png),
                "width_trace_png": str(width_trace_png),
                "phase_feature_row_count": len(feature_rows),
                "steady_fit_status": steady_fit.get("steady_fit_status"),
                "tail_onset_status": tail_onset.get("tail_onset_status"),
                "middle_extrapolation_status": middle.get("middle_extrapolation_status"),
                "partial_total_without_tail_nl": middle.get("partial_total_without_tail_nl"),
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
        "tail_drop_frac": float(tail_drop_frac),
        "tail_persist_frames": int(tail_persist_frames),
        "runs": run_manifests,
    }
    manifest_path = output_path / "fit_manifest.json"
    _write_json(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest
