from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from tools.stream_analysis.dataset import (
    _clean_text,
    _int_or_none,
    _preferred_columns,
    _write_csv,
    _write_json,
    build_stage0_inventory,
    default_output_root,
)
from tools.stream_analysis import fit as fit_mod
from tools.stream_analysis import volume as volume_mod


SUMMARY_STAGE_DIRNAME = "stage_06_summary"
SUMMARY_PROGRESS_FILENAME = "summary_progress.json"
NL_PER_MG_WATER = 1000.0

RUN_SUMMARY_COLUMNS = [
    "run_id",
    "run_dir",
    "metadata_match_status",
    "metadata_row_index",
    "outcome",
    "started_at_utc",
    "ended_at_utc",
    "print_pw_us",
    "print_pressure",
    "refuel_pw_us",
    "refuel_pressure",
    "replicate_index",
    "num_printed",
    "mass_per_print_mg",
    "gravimetric_total_nl",
    "steady_fit_status",
    "steady_start_capture_index",
    "steady_end_capture_index",
    "steady_duration_us",
    "steady_fit_point_count",
    "steady_rate_nl_per_us",
    "steady_rate_ci95_low_nl_per_us",
    "steady_rate_ci95_high_nl_per_us",
    "steady_rate_ci95_relative_width",
    "steady_rate_confidence_status",
    "steady_r2",
    "steady_nrmse",
    "steady_width_plateau_px",
    "first_untrusted_capture_index",
    "fov_exit_delay_from_emergence_us",
    "tail_confirmation_capture_index",
    "tail_confirmation_delay_from_emergence_us",
    "tail_detection_mode",
    "tail_start_selection_mode",
    "preliminary_tail_start_capture_index",
    "preliminary_tail_start_delay_from_emergence_us",
    "direct_final_tail_start_capture_index",
    "direct_final_tail_start_delay_from_emergence_us",
    "tail_shoulder_end_capture_index",
    "tail_shoulder_end_delay_from_emergence_us",
    "tail_start_capture_index",
    "tail_start_delay_from_emergence_us",
    "tail_onset_status",
    "middle_duration_us",
    "trusted_visible_volume_nl",
    "middle_extrapolated_volume_nl",
    "partial_total_without_tail_nl",
    "middle_extrapolation_status",
    "final_total_status",
    "signed_residual_nl",
    "signed_residual_fraction",
    "partial_to_gravimetric_ratio",
    "partial_exceeds_gravimetric",
    "referenced_stage4_fit_output_root",
    "referenced_stage4_manifest_json",
    "referenced_stage5_fit_output_root",
    "referenced_stage5_manifest_json",
    "run_summary_json",
]

CONDITION_SUMMARY_COLUMNS = [
    "condition_key",
    "print_pressure",
    "print_pw_us",
    "run_count",
    "replicate_ids",
    "gravimetric_total_nl_mean",
    "partial_total_without_tail_nl_mean",
    "signed_residual_nl_mean",
    "signed_residual_nl_std",
    "signed_residual_fraction_mean",
    "partial_to_gravimetric_ratio_mean",
    "overprediction_run_count",
]

CONDITION_CONSISTENCY_COLUMNS = [
    "condition_key",
    "print_pressure",
    "print_pw_us",
    "run_count",
    "replicate_ids",
    "consistency_status",
    "vt_band_sample_count",
    "trusted_vt_band_width_nl_median",
    "trusted_vt_band_width_nl_p95",
    "width_band_sample_count",
    "width_band_width_px_median",
    "width_band_width_px_p95",
    "steady_rate_nl_per_us_std_sample",
    "steady_rate_nl_per_us_cv",
    "flow_fit_start_after_first_trusted_us_std",
    "flow_fit_end_to_fov_exit_us_std",
    "tail_confirmation_delay_from_emergence_us_std",
    "tail_start_delay_from_emergence_us_std",
    "partial_total_without_tail_nl_std_sample",
    "predicted_volume_uncertainty_width_nl_median",
    "vt_overlay_png",
    "width_overlay_png",
]

CONDITION_CONSISTENCY_GRID_SPACING_US = 50.0


def _float_or_none(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _utc_now_text():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _progress(message: str):
    print(message, file=sys.stderr, flush=True)


def _mean_or_none(values: list[float]):
    if not values:
        return None
    return float(np.mean(np.asarray(values, dtype=float)))


def _std_or_none(values: list[float]):
    if not values:
        return None
    return float(np.std(np.asarray(values, dtype=float), ddof=0))


def _sample_std_or_none(values: list[float]):
    if len(values) < 2:
        return None
    return float(np.std(np.asarray(values, dtype=float), ddof=1))


def _median_or_none(values: list[float]):
    if not values:
        return None
    return float(np.median(np.asarray(values, dtype=float)))


def _percentile_or_none(values: list[float], percentile: float):
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), float(percentile)))


def _cv_or_none(values: list[float]):
    mean_value = _mean_or_none(values)
    std_value = _sample_std_or_none(values)
    if mean_value is None or std_value is None or float(mean_value) == 0.0:
        return None
    return float(float(std_value) / abs(float(mean_value)))


def _metadata_metrics(run_row: dict):
    return {
        "print_pw_us": _int_or_none(run_row.get("metadata_print_pw")),
        "print_pressure": _float_or_none(run_row.get("metadata_print_pressure")),
        "refuel_pw_us": _int_or_none(run_row.get("metadata_refuel_pw")),
        "refuel_pressure": _float_or_none(run_row.get("metadata_refuel_pressure")),
        "replicate_index": _int_or_none(run_row.get("metadata_rep")),
        "num_printed": _int_or_none(run_row.get("metadata_num_printed")),
        "mass_per_print_mg": _float_or_none(run_row.get("metadata_mass_print")),
    }


def _gravimetric_fields(*, mass_per_print_mg: float | None, partial_total_without_tail_nl: float | None):
    gravimetric_total_nl = None
    if mass_per_print_mg is not None:
        gravimetric_total_nl = float(mass_per_print_mg) * float(NL_PER_MG_WATER)

    if gravimetric_total_nl is None or partial_total_without_tail_nl is None:
        return {
            "gravimetric_total_nl": gravimetric_total_nl,
            "signed_residual_nl": None,
            "signed_residual_fraction": None,
            "partial_to_gravimetric_ratio": None,
            "partial_exceeds_gravimetric": None,
        }

    signed_residual_nl = float(gravimetric_total_nl - float(partial_total_without_tail_nl))
    signed_residual_fraction = None
    partial_to_gravimetric_ratio = None
    if float(gravimetric_total_nl) != 0.0:
        signed_residual_fraction = float(signed_residual_nl / float(gravimetric_total_nl))
        partial_to_gravimetric_ratio = float(
            float(partial_total_without_tail_nl) / float(gravimetric_total_nl)
        )
    return {
        "gravimetric_total_nl": gravimetric_total_nl,
        "signed_residual_nl": signed_residual_nl,
        "signed_residual_fraction": signed_residual_fraction,
        "partial_to_gravimetric_ratio": partial_to_gravimetric_ratio,
        "partial_exceeds_gravimetric": bool(float(partial_total_without_tail_nl) > float(gravimetric_total_nl)),
    }


def _artifact_path_map(root: Path, run_id: str):
    stage4_dir = root / "runs" / run_id / volume_mod.VOLUME_STAGE_DIRNAME
    stage5_dir = root / "runs" / run_id / fit_mod.FIT_STAGE_DIRNAME
    return {
        "stage4_output_root": str(root),
        "stage4_manifest_json": str(stage4_dir / "volume_manifest.json")
        if (stage4_dir / "volume_manifest.json").exists()
        else None,
        "stage5_output_root": str(root),
        "stage5_manifest_json": str(stage5_dir / "fit_manifest.json")
        if (stage5_dir / "fit_manifest.json").exists()
        else None,
    }


def _artifact_references(experiment_root: str | Path, output_root: Path, run_id: str):
    candidate_roots = [Path(output_root).resolve()]
    try:
        default_root = default_output_root(experiment_root)
    except Exception:
        default_root = None
    for candidate in [default_root]:
        if candidate is None:
            continue
        resolved = Path(candidate).resolve()
        if resolved not in candidate_roots:
            candidate_roots.append(resolved)

    for candidate_root in candidate_roots:
        mapping = _artifact_path_map(candidate_root, run_id)
        if mapping["stage4_manifest_json"] or mapping["stage5_manifest_json"]:
            return {
                "referenced_stage4_fit_output_root": mapping["stage4_output_root"],
                "referenced_stage4_manifest_json": mapping["stage4_manifest_json"],
                "referenced_stage5_fit_output_root": mapping["stage5_output_root"],
                "referenced_stage5_manifest_json": mapping["stage5_manifest_json"],
            }

    return {
        "referenced_stage4_fit_output_root": None,
        "referenced_stage4_manifest_json": None,
        "referenced_stage5_fit_output_root": None,
        "referenced_stage5_manifest_json": None,
    }


def _duration_us(start_value, end_value):
    start_int = _int_or_none(start_value)
    end_int = _int_or_none(end_value)
    if start_int is None or end_int is None:
        return None
    return int(end_int - start_int)


def _run_summary_row(run_row: dict, stage5_run: dict, *, experiment_root: str | Path, output_root: Path):
    metadata_metrics = _metadata_metrics(run_row)
    summary = dict(stage5_run["summary"])
    phase_boundaries = dict(stage5_run["phase_boundaries"])
    gravimetric = _gravimetric_fields(
        mass_per_print_mg=metadata_metrics["mass_per_print_mg"],
        partial_total_without_tail_nl=_float_or_none(summary.get("partial_total_without_tail_nl")),
    )
    artifact_references = _artifact_references(experiment_root, output_root, str(run_row["run_id"]))

    row = {
        "run_id": run_row.get("run_id"),
        "run_dir": run_row.get("run_dir"),
        "metadata_match_status": run_row.get("metadata_match_status"),
        "metadata_row_index": _int_or_none(run_row.get("metadata_row_index")),
        "outcome": run_row.get("outcome"),
        "started_at_utc": run_row.get("started_at_utc"),
        "ended_at_utc": run_row.get("ended_at_utc"),
        **metadata_metrics,
        **gravimetric,
        "steady_fit_status": summary.get("steady_fit_status"),
        "steady_start_capture_index": _int_or_none(summary.get("steady_start_capture_index")),
        "steady_end_capture_index": _int_or_none(summary.get("steady_end_capture_index")),
        "steady_duration_us": _duration_us(
            phase_boundaries.get("steady_start_delay_from_emergence_us"),
            phase_boundaries.get("steady_end_delay_from_emergence_us"),
        ),
        "steady_fit_point_count": _int_or_none(summary.get("steady_fit_point_count")),
        "steady_rate_nl_per_us": _float_or_none(summary.get("steady_rate_nl_per_us")),
        "steady_rate_ci95_low_nl_per_us": _float_or_none(
            summary.get("steady_rate_ci95_low_nl_per_us")
        ),
        "steady_rate_ci95_high_nl_per_us": _float_or_none(
            summary.get("steady_rate_ci95_high_nl_per_us")
        ),
        "steady_rate_ci95_relative_width": _float_or_none(
            summary.get("steady_rate_ci95_relative_width")
        ),
        "steady_rate_confidence_status": summary.get("steady_rate_confidence_status"),
        "steady_r2": _float_or_none(summary.get("steady_r2")),
        "steady_nrmse": _float_or_none(summary.get("steady_nrmse")),
        "steady_width_plateau_px": _float_or_none(summary.get("steady_width_plateau_px")),
        "first_untrusted_capture_index": _int_or_none(phase_boundaries.get("first_untrusted_capture_index")),
        "fov_exit_delay_from_emergence_us": _int_or_none(
            phase_boundaries.get("first_untrusted_delay_from_emergence_us")
        ),
        "tail_confirmation_capture_index": _int_or_none(summary.get("tail_confirmation_capture_index")),
        "tail_confirmation_delay_from_emergence_us": _int_or_none(
            summary.get("tail_confirmation_delay_from_emergence_us")
        ),
        "tail_detection_mode": summary.get("tail_detection_mode"),
        "tail_start_selection_mode": summary.get("tail_start_selection_mode"),
        "preliminary_tail_start_capture_index": _int_or_none(
            summary.get("preliminary_tail_start_capture_index")
        ),
        "preliminary_tail_start_delay_from_emergence_us": _int_or_none(
            summary.get("preliminary_tail_start_delay_from_emergence_us")
        ),
        "direct_final_tail_start_capture_index": _int_or_none(
            summary.get("direct_final_tail_start_capture_index")
        ),
        "direct_final_tail_start_delay_from_emergence_us": _int_or_none(
            summary.get("direct_final_tail_start_delay_from_emergence_us")
        ),
        "tail_shoulder_end_capture_index": _int_or_none(summary.get("tail_shoulder_end_capture_index")),
        "tail_shoulder_end_delay_from_emergence_us": _int_or_none(
            summary.get("tail_shoulder_end_delay_from_emergence_us")
        ),
        "tail_start_capture_index": _int_or_none(summary.get("tail_start_capture_index")),
        "tail_start_delay_from_emergence_us": _int_or_none(summary.get("tail_start_delay_from_emergence_us")),
        "tail_onset_status": summary.get("tail_onset_status"),
        "middle_duration_us": _duration_us(
            phase_boundaries.get("first_untrusted_delay_from_emergence_us"),
            phase_boundaries.get("tail_start_delay_from_emergence_us"),
        ),
        "trusted_visible_volume_nl": _float_or_none(summary.get("trusted_visible_volume_nl")),
        "middle_extrapolated_volume_nl": _float_or_none(summary.get("middle_extrapolated_volume_nl")),
        "partial_total_without_tail_nl": _float_or_none(summary.get("partial_total_without_tail_nl")),
        "middle_extrapolation_status": summary.get("middle_extrapolation_status"),
        "final_total_status": summary.get("final_total_status"),
        **artifact_references,
        "run_summary_json": None,
    }

    for key, value in run_row.items():
        if not str(key).startswith("metadata_"):
            continue
        if key in {"metadata_raw", "metadata_source_path"}:
            continue
        row[key] = value
    return row


def _condition_key(row: dict):
    print_pressure = _float_or_none(row.get("print_pressure"))
    print_pw_us = _int_or_none(row.get("print_pw_us"))
    if print_pressure is None or print_pw_us is None:
        return None
    return f"{print_pressure:g}bar__{print_pw_us}us"


def _condition_summary_rows(summary_rows: list[dict]):
    grouped = {}
    for row in summary_rows:
        key = _condition_key(row)
        grouped.setdefault(key, []).append(row)

    condition_rows = []
    for key, rows in sorted(grouped.items(), key=lambda item: "" if item[0] is None else item[0]):
        residual_values = [
            float(row["signed_residual_nl"])
            for row in rows
            if row.get("signed_residual_nl") is not None
        ]
        residual_fraction_values = [
            float(row["signed_residual_fraction"])
            for row in rows
            if row.get("signed_residual_fraction") is not None
        ]
        gravimetric_values = [
            float(row["gravimetric_total_nl"])
            for row in rows
            if row.get("gravimetric_total_nl") is not None
        ]
        partial_values = [
            float(row["partial_total_without_tail_nl"])
            for row in rows
            if row.get("partial_total_without_tail_nl") is not None
        ]
        ratio_values = [
            float(row["partial_to_gravimetric_ratio"])
            for row in rows
            if row.get("partial_to_gravimetric_ratio") is not None
        ]
        condition_rows.append(
            {
                "condition_key": key,
                "print_pressure": _float_or_none(rows[0].get("print_pressure")),
                "print_pw_us": _int_or_none(rows[0].get("print_pw_us")),
                "run_count": len(rows),
                "replicate_ids": [
                    row.get("replicate_index") for row in rows if row.get("replicate_index") is not None
                ],
                "gravimetric_total_nl_mean": _mean_or_none(gravimetric_values),
                "partial_total_without_tail_nl_mean": _mean_or_none(partial_values),
                "signed_residual_nl_mean": _mean_or_none(residual_values),
                "signed_residual_nl_std": _std_or_none(residual_values),
                "signed_residual_fraction_mean": _mean_or_none(residual_fraction_values),
                "partial_to_gravimetric_ratio_mean": _mean_or_none(ratio_values),
                "overprediction_run_count": sum(
                    1 for row in rows if bool(row.get("partial_exceeds_gravimetric"))
                ),
            }
        )
    return condition_rows


def _condition_style_maps(summary_rows: list[dict]):
    pressure_values = sorted(
        {
            _float_or_none(row.get("print_pressure"))
            for row in summary_rows
            if _float_or_none(row.get("print_pressure")) is not None
        }
    )
    pw_values = sorted(
        {
            _int_or_none(row.get("print_pw_us"))
            for row in summary_rows
            if _int_or_none(row.get("print_pw_us")) is not None
        }
    )
    palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
    markers = ["o", "s", "^", "D", "P", "X", "v", "<", ">"]
    color_map = {value: palette[index % len(palette)] for index, value in enumerate(pressure_values)}
    marker_map = {value: markers[index % len(markers)] for index, value in enumerate(pw_values)}
    return color_map, marker_map


def _condition_bundle_sort_key(bundle: dict):
    replicate_index = _int_or_none(bundle.get("replicate_index"))
    run_id = _clean_text(bundle.get("run_id")) or ""
    return (
        10**9 if replicate_index is None else int(replicate_index),
        run_id,
    )


def _condition_run_label(bundle: dict):
    replicate_index = _int_or_none(bundle.get("replicate_index"))
    run_id = _clean_text(bundle.get("run_id")) or "unknown"
    if replicate_index is None:
        return run_id
    return f"rep {int(replicate_index)} | {run_id}"


def _dedupe_sorted_series(points: list[tuple[float, float]]):
    deduped = {}
    for x_value, y_value in sorted(points, key=lambda point: point[0]):
        deduped[float(x_value)] = float(y_value)
    return [(x_value, deduped[x_value]) for x_value in sorted(deduped.keys())]


def _feature_series(
    feature_rows: list[dict],
    value_key: str,
    *,
    trusted_only: bool = False,
):
    points = []
    for row in feature_rows:
        if trusted_only and _clean_text(row.get("volume_trust_label")) != fit_mod.fov_mod.TRUST_LABEL_TRUSTED:
            continue
        x_value = _float_or_none(row.get("delay_from_emergence_us"))
        y_value = _float_or_none(row.get(value_key))
        if x_value is None or y_value is None:
            continue
        points.append((float(x_value), float(y_value)))
    return _dedupe_sorted_series(points)


def _interpolate_series_value(points: list[tuple[float, float]], x_value: float):
    if not points:
        return None
    if len(points) == 1:
        return float(points[0][1]) if float(points[0][0]) == float(x_value) else None

    xs = [float(point[0]) for point in points]
    insert_index = int(np.searchsorted(np.asarray(xs, dtype=float), float(x_value), side="left"))
    if insert_index < len(points) and float(points[insert_index][0]) == float(x_value):
        return float(points[insert_index][1])
    if insert_index <= 0 or insert_index >= len(points):
        return None

    x0, y0 = points[insert_index - 1]
    x1, y1 = points[insert_index]
    if float(x1) == float(x0):
        return float(y0)
    fraction = float((float(x_value) - float(x0)) / (float(x1) - float(x0)))
    return float(float(y0) + (fraction * (float(y1) - float(y0))))


def _trace_spread_metrics(series_by_run: list[list[tuple[float, float]]], *, grid_spacing_us: float):
    valid_series = [series for series in series_by_run if series]
    if not valid_series:
        return {"sample_count": 0, "median_spread": None, "p95_spread": None}

    min_time = min(float(series[0][0]) for series in valid_series)
    max_time = max(float(series[-1][0]) for series in valid_series)
    if float(max_time) < float(min_time):
        return {"sample_count": 0, "median_spread": None, "p95_spread": None}

    grid = np.arange(
        float(min_time),
        float(max_time) + float(grid_spacing_us),
        float(grid_spacing_us),
        dtype=float,
    )
    spread_values = []
    for x_value in grid:
        sample_values = []
        for series in valid_series:
            interpolated = _interpolate_series_value(series, float(x_value))
            if interpolated is not None:
                sample_values.append(float(interpolated))
        if len(sample_values) < 2:
            continue
        spread_values.append(
            float(
                np.percentile(np.asarray(sample_values, dtype=float), 95)
                - np.percentile(np.asarray(sample_values, dtype=float), 5)
            )
        )

    return {
        "sample_count": len(spread_values),
        "median_spread": _median_or_none(spread_values),
        "p95_spread": _percentile_or_none(spread_values, 95),
    }


def _bundle_delay_value(bundle: dict, *keys: str):
    summary_row = dict(bundle.get("summary_row") or {})
    phase_boundaries = dict(bundle.get("phase_boundaries") or {})
    tail_onset = dict(bundle.get("tail_onset") or {})
    fov_report = dict(bundle.get("fov_report") or {})
    steady_fit_metrics = dict(bundle.get("steady_fit_review_metrics") or {})
    for key in keys:
        for source in (summary_row, phase_boundaries, tail_onset, fov_report, steady_fit_metrics):
            value = _float_or_none(source.get(key))
            if value is not None:
                return float(value)
    return None


def _plot_condition_vt_overlay(path: Path, condition_key: str, bundles: list[dict]):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    fig, (ax_trace, ax_events) = plt.subplots(
        2,
        1,
        figsize=(11, 7.5),
        sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1.8]},
    )
    palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    event_specs = [
        ("steady start", "o", ("steady_start_delay_from_emergence_us",)),
        ("steady end", "s", ("steady_end_delay_from_emergence_us",)),
        ("first untrusted", "^", ("fov_exit_delay_from_emergence_us", "first_untrusted_delay_from_emergence_us", "first_fov_exit_delay_from_emergence_us")),
        ("tail confirmation", "D", ("tail_confirmation_delay_from_emergence_us",)),
        ("tail start", "X", ("tail_start_delay_from_emergence_us",)),
    ]

    labels = []
    for run_index, bundle in enumerate(bundles):
        color = palette[run_index % len(palette)]
        feature_rows = list(bundle.get("phase_feature_rows") or [])
        trusted_points = _feature_series(
            feature_rows,
            "total_visible_volume_nl",
            trusted_only=True,
        )
        untrusted_points = [
            (float(_float_or_none(row.get("delay_from_emergence_us"))), float(_float_or_none(row.get("total_visible_volume_nl"))))
            for row in feature_rows
            if _clean_text(row.get("volume_trust_label")) != fit_mod.fov_mod.TRUST_LABEL_TRUSTED
            and _float_or_none(row.get("delay_from_emergence_us")) is not None
            and _float_or_none(row.get("total_visible_volume_nl")) is not None
        ]
        untrusted_points = _dedupe_sorted_series(untrusted_points)
        if trusted_points:
            ax_trace.plot(
                [x for x, _y in trusted_points],
                [y for _x, y in trusted_points],
                color=color,
                linewidth=1.8,
                alpha=0.95,
            )
        if untrusted_points:
            ax_trace.plot(
                [x for x, _y in untrusted_points],
                [y for _x, y in untrusted_points],
                color=color,
                linewidth=1.5,
                linestyle="--",
                alpha=0.45,
            )

        steady_fit = dict(bundle.get("steady_fit") or {})
        flow_fit_points = fit_mod._steady_fit_time_volume_points(feature_rows, steady_fit)
        steady_rate = _float_or_none(steady_fit.get("steady_rate_nl_per_us"))
        steady_intercept = _float_or_none(steady_fit.get("steady_intercept_nl"))
        if flow_fit_points and steady_rate is not None and steady_intercept is not None:
            flow_x = [float(time_us) for time_us, _volume in flow_fit_points]
            ax_trace.plot(
                flow_x,
                [
                    float(steady_intercept) + (float(steady_rate) * float(time_us))
                    for time_us in flow_x
                ],
                color=color,
                linewidth=2.4,
                linestyle=":",
                alpha=0.95,
            )

        labels.append(_condition_run_label(bundle))

    legend_handles = []
    for run_index, bundle in enumerate(bundles):
        color = palette[run_index % len(palette)]
        y_position = float(run_index)
        for label, marker, keys in event_specs:
            x_value = _bundle_delay_value(bundle, *keys)
            if x_value is None:
                continue
            ax_events.scatter(
                [float(x_value)],
                [y_position],
                color=color,
                marker=marker,
                s=58,
                edgecolors="#111827",
                linewidths=0.7,
                zorder=4,
            )
        if not legend_handles:
            legend_handles = [
                Line2D(
                    [0],
                    [0],
                    marker=marker,
                    color="#374151",
                    linestyle="None",
                    markersize=7,
                    label=label,
                )
                for label, marker, _keys in event_specs
            ]

    ax_trace.set_title(
        f"Condition V(t) Overlay - {condition_key}\n"
        "Run colors match the event rows below"
    )
    ax_trace.set_ylabel("Visible volume (nL)")
    ax_trace.grid(True, alpha=0.25)
    ax_events.set_ylabel("Runs")
    ax_events.set_xlabel("Delay from emergence (us)")
    ax_events.set_yticks(range(len(labels)))
    ax_events.set_yticklabels(labels)
    if hasattr(ax_events, "invert_yaxis"):
        ax_events.invert_yaxis()
    elif hasattr(ax_events, "set_ylim"):
        ax_events.set_ylim(len(labels) - 0.5, -0.5)
    ax_events.grid(True, axis="x", alpha=0.25)
    if legend_handles:
        if hasattr(fig, "legend"):
            fig.legend(
                handles=legend_handles,
                loc="upper center",
                ncol=min(len(legend_handles), 5),
                frameon=False,
                bbox_to_anchor=(0.5, 0.98),
            )
        elif hasattr(ax_trace, "legend"):
            ax_trace.legend(legend_handles, [handle.get_label() for handle in legend_handles], loc="best")
    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.94])
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _plot_condition_width_overlay(path: Path, condition_key: str, bundles: list[dict]):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    fig, (ax_trace, ax_events) = plt.subplots(
        2,
        1,
        figsize=(11, 7.5),
        sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1.8]},
    )
    palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    event_specs = [
        ("preliminary tail start", "o", ("preliminary_tail_start_delay_from_emergence_us",)),
        ("direct tail start", "s", ("direct_final_tail_start_delay_from_emergence_us",)),
        ("tail shoulder end", "^", ("tail_shoulder_end_delay_from_emergence_us",)),
        ("tail start", "D", ("tail_start_delay_from_emergence_us",)),
        ("tail peak shrink", "X", ("tail_peak_shrink_rate_delay_us",)),
    ]

    labels = []
    for run_index, bundle in enumerate(bundles):
        color = palette[run_index % len(palette)]
        width_points = _feature_series(
            list(bundle.get("phase_feature_rows") or []),
            "attached_near_nozzle_width_smoothed_px",
        )
        if width_points:
            ax_trace.plot(
                [x for x, _y in width_points],
                [y for _x, y in width_points],
                color=color,
                linewidth=1.8,
                alpha=0.95,
            )
        labels.append(_condition_run_label(bundle))
        y_position = float(run_index)
        for label, marker, keys in event_specs:
            x_value = _bundle_delay_value(bundle, *keys)
            if x_value is None:
                continue
            ax_events.scatter(
                [float(x_value)],
                [y_position],
                color=color,
                marker=marker,
                s=58,
                edgecolors="#111827",
                linewidths=0.7,
                zorder=4,
            )

    legend_handles = [
        Line2D(
            [0],
            [0],
            marker=marker,
            color="#374151",
            linestyle="None",
            markersize=7,
            label=label,
        )
        for label, marker, _keys in event_specs
    ]
    ax_trace.set_title(
        f"Condition Width Overlay - {condition_key}\n"
        "Run colors match the event rows below"
    )
    ax_trace.set_ylabel("Smoothed width (px)")
    ax_trace.grid(True, alpha=0.25)
    ax_events.set_ylabel("Runs")
    ax_events.set_xlabel("Delay from emergence (us)")
    ax_events.set_yticks(range(len(labels)))
    ax_events.set_yticklabels(labels)
    if hasattr(ax_events, "invert_yaxis"):
        ax_events.invert_yaxis()
    elif hasattr(ax_events, "set_ylim"):
        ax_events.set_ylim(len(labels) - 0.5, -0.5)
    ax_events.grid(True, axis="x", alpha=0.25)
    if hasattr(fig, "legend"):
        fig.legend(
            handles=legend_handles,
            loc="upper center",
            ncol=min(len(legend_handles), 5),
            frameon=False,
            bbox_to_anchor=(0.5, 0.98),
        )
    elif hasattr(ax_trace, "legend"):
        ax_trace.legend(legend_handles, [handle.get_label() for handle in legend_handles], loc="best")
    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.94])
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _condition_consistency_rows(condition_bundles: list[dict], *, review_dir: Path | None = None):
    grouped = {}
    for bundle in condition_bundles:
        condition_key = _clean_text(bundle.get("condition_key"))
        if not condition_key:
            continue
        grouped.setdefault(condition_key, []).append(dict(bundle))

    rows = []
    for condition_key, bundles in sorted(grouped.items(), key=lambda item: item[0]):
        ordered_bundles = sorted(bundles, key=_condition_bundle_sort_key)
        summary_rows = [dict(bundle.get("summary_row") or {}) for bundle in ordered_bundles]
        vt_series_by_run = [
            _feature_series(
                list(bundle.get("phase_feature_rows") or []),
                "total_visible_volume_nl",
                trusted_only=True,
            )
            for bundle in ordered_bundles
        ]
        width_series_by_run = [
            _feature_series(
                list(bundle.get("phase_feature_rows") or []),
                "attached_near_nozzle_width_smoothed_px",
            )
            for bundle in ordered_bundles
        ]
        vt_spread = _trace_spread_metrics(
            vt_series_by_run,
            grid_spacing_us=CONDITION_CONSISTENCY_GRID_SPACING_US,
        )
        width_spread = _trace_spread_metrics(
            width_series_by_run,
            grid_spacing_us=CONDITION_CONSISTENCY_GRID_SPACING_US,
        )
        steady_rate_values = [
            float(value)
            for value in (
                _float_or_none(summary_row.get("steady_rate_nl_per_us"))
                for summary_row in summary_rows
            )
            if value is not None
        ]
        flow_fit_start_values = [
            float(value)
            for value in (
                _float_or_none(
                    dict(bundle.get("steady_fit_review_metrics") or {}).get(
                        "flow_fit_start_after_first_trusted_us"
                    )
                )
                for bundle in ordered_bundles
            )
            if value is not None
        ]
        flow_fit_end_values = [
            float(value)
            for value in (
                _float_or_none(
                    dict(bundle.get("steady_fit_review_metrics") or {}).get(
                        "flow_fit_end_to_fov_exit_us"
                    )
                )
                for bundle in ordered_bundles
            )
            if value is not None
        ]
        tail_confirmation_values = [
            float(value)
            for value in (
                _float_or_none(summary_row.get("tail_confirmation_delay_from_emergence_us"))
                for summary_row in summary_rows
            )
            if value is not None
        ]
        tail_start_values = [
            float(value)
            for value in (
                _float_or_none(summary_row.get("tail_start_delay_from_emergence_us"))
                for summary_row in summary_rows
            )
            if value is not None
        ]
        partial_total_values = [
            float(value)
            for value in (
                _float_or_none(summary_row.get("partial_total_without_tail_nl"))
                for summary_row in summary_rows
            )
            if value is not None
        ]
        predicted_uncertainty_width_values = [
            float(value)
            for value in (
                _float_or_none(summary_row.get("predicted_volume_uncertainty_width_nl"))
                for summary_row in summary_rows
            )
            if value is not None
        ]

        vt_overlay_path = None
        width_overlay_path = None
        if len(ordered_bundles) >= 2 and review_dir is not None:
            vt_overlay_path = review_dir / f"{condition_key}__vt_overlay.png"
            width_overlay_path = review_dir / f"{condition_key}__width_overlay.png"
            _plot_condition_vt_overlay(vt_overlay_path, condition_key, ordered_bundles)
            _plot_condition_width_overlay(width_overlay_path, condition_key, ordered_bundles)

        if len(ordered_bundles) < 2:
            consistency_status = "insufficient_runs"
        elif int(vt_spread["sample_count"]) == 0 and int(width_spread["sample_count"]) == 0:
            consistency_status = "no_common_trace_samples"
        elif int(vt_spread["sample_count"]) == 0:
            consistency_status = "no_common_vt_samples"
        elif int(width_spread["sample_count"]) == 0:
            consistency_status = "no_common_width_samples"
        else:
            consistency_status = "ok"

        rows.append(
            {
                "condition_key": condition_key,
                "print_pressure": _float_or_none(summary_rows[0].get("print_pressure")),
                "print_pw_us": _int_or_none(summary_rows[0].get("print_pw_us")),
                "run_count": len(ordered_bundles),
                "replicate_ids": [
                    _int_or_none(bundle.get("replicate_index"))
                    for bundle in ordered_bundles
                    if _int_or_none(bundle.get("replicate_index")) is not None
                ],
                "consistency_status": consistency_status,
                "vt_band_sample_count": int(vt_spread["sample_count"]),
                "trusted_vt_band_width_nl_median": vt_spread["median_spread"],
                "trusted_vt_band_width_nl_p95": vt_spread["p95_spread"],
                "width_band_sample_count": int(width_spread["sample_count"]),
                "width_band_width_px_median": width_spread["median_spread"],
                "width_band_width_px_p95": width_spread["p95_spread"],
                "steady_rate_nl_per_us_std_sample": _sample_std_or_none(steady_rate_values),
                "steady_rate_nl_per_us_cv": _cv_or_none(steady_rate_values),
                "flow_fit_start_after_first_trusted_us_std": _sample_std_or_none(
                    flow_fit_start_values
                ),
                "flow_fit_end_to_fov_exit_us_std": _sample_std_or_none(flow_fit_end_values),
                "tail_confirmation_delay_from_emergence_us_std": _sample_std_or_none(
                    tail_confirmation_values
                ),
                "tail_start_delay_from_emergence_us_std": _sample_std_or_none(
                    tail_start_values
                ),
                "partial_total_without_tail_nl_std_sample": _sample_std_or_none(
                    partial_total_values
                ),
                "predicted_volume_uncertainty_width_nl_median": _median_or_none(
                    predicted_uncertainty_width_values
                ),
                "vt_overlay_png": None if vt_overlay_path is None else str(vt_overlay_path),
                "width_overlay_png": None if width_overlay_path is None else str(width_overlay_path),
            }
        )
    return rows


def _plot_partial_vs_gravimetric(path: Path, summary_rows: list[dict]):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    rows = [
        row
        for row in summary_rows
        if row.get("gravimetric_total_nl") is not None and row.get("partial_total_without_tail_nl") is not None
    ]
    fig, ax = plt.subplots(figsize=(8, 6))
    color_map, marker_map = _condition_style_maps(rows)
    for row in rows:
        pressure = _float_or_none(row.get("print_pressure"))
        pw = _int_or_none(row.get("print_pw_us"))
        ax.scatter(
            float(row["gravimetric_total_nl"]),
            float(row["partial_total_without_tail_nl"]),
            color=color_map.get(pressure, "#1f77b4"),
            marker=marker_map.get(pw, "o"),
            s=44,
            alpha=0.9,
        )

    if rows:
        all_values = [
            float(value)
            for row in rows
            for value in [row["gravimetric_total_nl"], row["partial_total_without_tail_nl"]]
        ]
        min_value = min(all_values)
        max_value = max(all_values)
        ax.plot([min_value, max_value], [min_value, max_value], color="#777777", linestyle="--", linewidth=1.2)
    ax.set_title("Stage 5 Partial Total vs Gravimetric Total")
    ax.set_xlabel("Gravimetric total (nL)")
    ax.set_ylabel("Partial total without tail (nL)")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _plot_residual_by_condition(path: Path, condition_rows: list[dict], summary_rows: list[dict], *, fraction: bool):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    value_key = "signed_residual_fraction" if fraction else "signed_residual_nl"
    mean_key = "signed_residual_fraction_mean" if fraction else "signed_residual_nl_mean"
    valid_condition_rows = [row for row in condition_rows if row.get("condition_key") is not None]
    x_positions = {row["condition_key"]: index for index, row in enumerate(valid_condition_rows)}

    fig, ax = plt.subplots(figsize=(10, 5))
    for row in summary_rows:
        condition_key = _condition_key(row)
        value = _float_or_none(row.get(value_key))
        if condition_key is None or value is None:
            continue
        x_center = x_positions[condition_key]
        jitter = ((int(row.get("replicate_index") or 0) % 5) - 2) * 0.04
        ax.scatter(x_center + jitter, value, color="#8aa5c8", s=30, alpha=0.85)

    for row in valid_condition_rows:
        mean_value = _float_or_none(row.get(mean_key))
        if mean_value is None:
            continue
        ax.scatter(x_positions[row["condition_key"]], mean_value, color="#d62728", marker="_", s=400, linewidths=2.0)

    ax.axhline(0.0, color="#777777", linestyle="--", linewidth=1.0)
    ax.set_xticks(list(x_positions.values()))
    ax.set_xticklabels(list(x_positions.keys()), rotation=45, ha="right")
    ax.set_title(
        "Signed Relative Error by Condition" if fraction else "Signed Residual by Condition"
    )
    ax.set_ylabel(
        "Signed relative error (fraction of gravimetric total)"
        if fraction
        else "Signed residual (nL)"
    )
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _plot_residual_vs_middle_duration(path: Path, summary_rows: list[dict]):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    rows = [
        row
        for row in summary_rows
        if row.get("middle_duration_us") is not None and row.get("signed_residual_nl") is not None
    ]
    color_map, marker_map = _condition_style_maps(rows)
    fig, ax = plt.subplots(figsize=(8, 6))
    for row in rows:
        pressure = _float_or_none(row.get("print_pressure"))
        pw = _int_or_none(row.get("print_pw_us"))
        ax.scatter(
            float(row["middle_duration_us"]),
            float(row["signed_residual_nl"]),
            color=color_map.get(pressure, "#1f77b4"),
            marker=marker_map.get(pw, "o"),
            s=44,
            alpha=0.9,
        )
    ax.axhline(0.0, color="#777777", linestyle="--", linewidth=1.0)
    ax.set_title("Signed Residual vs Middle Duration")
    ax.set_xlabel("Middle duration (us)")
    ax.set_ylabel("Signed residual (nL)")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _progress_payload(
    selected_run_ids: list[str],
    *,
    completed_run_ids: list[str],
    current_run_id: str | None,
    last_completed_run_id: str | None,
    run_summaries_written: list[str],
):
    return {
        "schema_version": 1,
        "stage": "summary",
        "selected_run_count": int(len(selected_run_ids)),
        "completed_run_count": int(len(completed_run_ids)),
        "pending_run_count": int(max(0, len(selected_run_ids) - len(completed_run_ids))),
        "completed_run_ids": list(completed_run_ids),
        "current_run_id": current_run_id,
        "last_completed_run_id": last_completed_run_id,
        "last_update_utc": _utc_now_text(),
        "run_summaries_written": list(run_summaries_written),
    }


def _write_progress(path: Path, payload: dict):
    _write_json(path, payload)


def _build_raw_run_context(review_cache_mod, run_row: dict, stage5_run: dict, *, source: dict):
    middle_payload = dict(stage5_run.get("middle_payload") or {})
    return review_cache_mod._cache_context_payload(
        run_row,
        steady_fit_payload=dict(stage5_run.get("steady_fit_payload") or {}),
        trusted_visible_volume_nl=_float_or_none(middle_payload.get("trusted_visible_volume_nl")),
        first_untrusted_capture_index=_int_or_none(
            middle_payload.get("first_untrusted_capture_index")
        ),
        first_untrusted_delay_from_emergence_us=_int_or_none(
            middle_payload.get("first_untrusted_delay_from_emergence_us")
        ),
        fov_report=dict(stage5_run.get("stage4_run", {}).get("fov_report") or {}),
        source=source,
    )


def _validate_cache_mode_raw_overrides(
    review_cache_mod,
    *,
    include_unmatched: bool,
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
):
    defaults = dict(review_cache_mod.RAW_FALLBACK_STAGE5_KWARGS)
    current_values = {
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
    }
    mismatches = [key for key, value in current_values.items() if value != defaults.get(key)]
    if bool(include_unmatched):
        mismatches.append("include_unmatched")
    if mismatches:
        mismatch_text = ", ".join(sorted(set(mismatches)))
        raise ValueError(
            "Cache-backed summary only supports default raw image-analysis knobs. "
            f"Reset these options or rerun from the experiment root instead: {mismatch_text}"
        )


def export_stage6_summary(
    experiment_root: str | Path | None = None,
    *,
    cache_root: str | Path | None = None,
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
    include_suspect_gravimetric: bool = False,
    tail_start_mode: str = fit_mod.TAIL_START_MODE_DESCRIPTOR_UNIFIED,
    tail_direct_target_drop_to_threshold_frac: float = fit_mod.TAIL_DIRECT_TARGET_DROP_TO_THRESHOLD_FRAC,
    tail_direct_target_peak_lead_us: float = fit_mod.TAIL_DIRECT_TARGET_PEAK_LEAD_US,
    tail_direct_target_shrink_rate_ratio: float = fit_mod.TAIL_DIRECT_TARGET_SHRINK_RATE_RATIO,
    tail_shoulder_target_drop_to_threshold_frac: float = fit_mod.TAIL_SHOULDER_TARGET_DROP_TO_THRESHOLD_FRAC,
    tail_shoulder_target_peak_lead_us: float = fit_mod.TAIL_SHOULDER_TARGET_PEAK_LEAD_US,
    tail_shoulder_target_shrink_rate_ratio: float = fit_mod.TAIL_SHOULDER_TARGET_SHRINK_RATE_RATIO,
    tail_score_drop_weight: float = fit_mod.TAIL_SCORE_DROP_WEIGHT,
    tail_score_peak_lead_weight: float = fit_mod.TAIL_SCORE_PEAK_LEAD_WEIGHT,
    tail_score_shrink_rate_weight: float = fit_mod.TAIL_SCORE_SHRINK_RATE_WEIGHT,
    tail_score_drop_scale: float = fit_mod.TAIL_SCORE_DROP_SCALE,
    tail_score_peak_lead_scale_us: float = fit_mod.TAIL_SCORE_PEAK_LEAD_SCALE_US,
    tail_score_shrink_rate_scale: float = fit_mod.TAIL_SCORE_SHRINK_RATE_SCALE,
    tail_unified_band_drop_min: float = fit_mod.TAIL_UNIFIED_BAND_DROP_MIN,
    tail_unified_band_drop_max: float = fit_mod.TAIL_UNIFIED_BAND_DROP_MAX,
    tail_unified_band_peak_lead_min_us: float = fit_mod.TAIL_UNIFIED_BAND_PEAK_LEAD_MIN_US,
    tail_unified_band_peak_lead_max_us: float = fit_mod.TAIL_UNIFIED_BAND_PEAK_LEAD_MAX_US,
    tail_unified_band_shrink_rate_ratio_min: float = fit_mod.TAIL_UNIFIED_BAND_SHRINK_RATE_RATIO_MIN,
    tail_unified_band_shrink_rate_ratio_max: float = fit_mod.TAIL_UNIFIED_BAND_SHRINK_RATE_RATIO_MAX,
    tail_unified_target_drop_to_threshold_frac: float = fit_mod.TAIL_UNIFIED_TARGET_DROP_TO_THRESHOLD_FRAC,
    tail_unified_target_peak_lead_us: float = fit_mod.TAIL_UNIFIED_TARGET_PEAK_LEAD_US,
    tail_unified_target_shrink_rate_ratio: float = fit_mod.TAIL_UNIFIED_TARGET_SHRINK_RATE_RATIO,
    volume_uncertainty_sample_count: int = fit_mod.VOLUME_UNCERTAINTY_SAMPLE_COUNT,
    volume_uncertainty_seed: int = fit_mod.VOLUME_UNCERTAINTY_SEED,
    tail_uncertainty_score_tolerance: float = fit_mod.TAIL_UNCERTAINTY_SCORE_TOLERANCE,
):
    from tools.stream_analysis import review_cache as review_cache_mod

    if bool(experiment_root) == bool(cache_root):
        raise ValueError("Provide exactly one source: --experiment-root or --cache-root.")

    analysis_source_mode = "cache" if cache_root else "raw"
    parameter_payload = fit_mod._stage5_parameter_payload(
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

    cache_manifest = {}
    experiment_root_text = None
    inventory = None
    selected_runs = []
    selected_entries = []
    if analysis_source_mode == "raw":
        inventory = build_stage0_inventory(
            experiment_root,
            include_unmatched=include_unmatched,
            run_ids=run_ids,
            limit_runs=limit_runs,
        )
        experiment_root_text = inventory["experiment_root"]
        selected_runs = list(inventory["selected_runs"])
    else:
        _validate_cache_mode_raw_overrides(
            review_cache_mod,
            include_unmatched=include_unmatched,
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
        cache_root_path = Path(cache_root).expanduser().resolve()
        cache_manifest_path = cache_root_path / review_cache_mod.CACHE_MANIFEST_FILENAME
        if cache_manifest_path.exists():
            cache_manifest = review_cache_mod._load_json(cache_manifest_path)
            experiment_root_text = cache_manifest.get("experiment_root")
        selected_entries = review_cache_mod._selected_cache_entries(
            cache_root_path,
            run_ids=run_ids,
            limit_runs=limit_runs,
        )

    output_path = (
        Path(output_root).expanduser().resolve()
        if output_root
        else (
            Path(cache_root).expanduser().resolve().parent
            if cache_root
            else default_output_root(experiment_root)
        )
    )
    output_path.mkdir(parents=True, exist_ok=True)

    selected_run_ids = (
        [str(row["run_id"]) for row in selected_runs]
        if analysis_source_mode == "raw"
        else [str(entry["run_id"]) for entry in selected_entries]
    )
    progress_path = output_path / SUMMARY_PROGRESS_FILENAME
    run_summaries_written = []
    completed_run_ids = []
    _progress(
        f"[summary] starting Stage 6 for {len(selected_run_ids)} runs -> {output_path}"
    )
    _write_progress(
        progress_path,
        _progress_payload(
            selected_run_ids,
            completed_run_ids=completed_run_ids,
            current_run_id=None,
            last_completed_run_id=None,
            run_summaries_written=run_summaries_written,
        ),
    )

    summary_rows = []
    run_manifests = []
    width_review_rows = []
    vt_review_rows = []
    condition_consistency_bundles = []
    width_review_dir = output_path / "gravimetric_width_review"
    vt_review_dir = output_path / "vt_fit_review"
    for run_index, run_id in enumerate(selected_run_ids, start=1):
        run_row = None
        run_context = None
        cache_paths = None

        _progress(f"[{run_index}/{len(selected_run_ids)}] starting {run_id}")
        _write_progress(
            progress_path,
            _progress_payload(
                selected_run_ids,
                completed_run_ids=completed_run_ids,
                current_run_id=run_id,
                last_completed_run_id=(completed_run_ids[-1] if completed_run_ids else None),
                run_summaries_written=run_summaries_written,
            ),
        )

        started = time.perf_counter()
        if analysis_source_mode == "raw":
            run_row = next(row for row in selected_runs if str(row["run_id"]) == run_id)
            frame_rows = list(inventory["frames_by_run_id"][run_id])
            if not frame_rows:
                raise ValueError(f"No frame index rows available for run: {run_id}")
            stage5_run = fit_mod._build_stage5_run(
                run_id,
                frame_rows,
                tracking_mode=str(run_row.get("tracking_mode") or "dynamic"),
                **parameter_payload,
            )
            artifact_refs = _artifact_references(experiment_root, output_path, run_id)
            stage5_paths = fit_mod._write_stage5_outputs(
                output_path,
                run_id,
                stage5_run,
                run_dir=run_row.get("run_dir"),
                parameters=parameter_payload,
                analysis_source_mode=analysis_source_mode,
                referenced_stage4_fit_output_root=artifact_refs["referenced_stage4_fit_output_root"],
                referenced_stage4_manifest_json=artifact_refs["referenced_stage4_manifest_json"],
                referenced_stage5_fit_output_root=str(output_path),
                referenced_stage5_manifest_json=None,
                stage4_summary=stage5_run["stage4_run"].get("summary_counts"),
                shift_events=stage5_run["stage4_run"].get("shift_events"),
            )
            run_context = _build_raw_run_context(
                review_cache_mod,
                dict(run_row),
                stage5_run,
                source={
                    "stage4_output_root": artifact_refs["referenced_stage4_fit_output_root"],
                    "stage4_manifest_json": artifact_refs["referenced_stage4_manifest_json"],
                    "stage5_output_root": str(output_path),
                    "stage5_manifest_json": str(stage5_paths["fit_manifest_json"]),
                },
            )
        else:
            entry = next(entry for entry in selected_entries if str(entry["run_id"]) == run_id)
            cache_paths = dict(entry["paths"])
            run_context = dict(entry["run_context"])
            phase_input_rows = review_cache_mod._load_csv_rows(cache_paths["phase_input_csv"])
            frozen_anchors = dict(run_context.get("frozen_anchors") or {})
            stage5_run = fit_mod._build_stage5_review_run(
                run_id,
                phase_input_rows,
                steady_fit_payload=dict(run_context.get("frozen_steady_fit") or {}),
                fov_report=dict(run_context.get("fov_report") or {}),
                trusted_visible_volume_nl=_float_or_none(
                    frozen_anchors.get("trusted_visible_volume_nl")
                ),
                first_untrusted_delay_from_emergence_us=_int_or_none(
                    frozen_anchors.get("first_untrusted_delay_from_emergence_us")
                ),
                width_smooth_window=int(width_smooth_window),
                tail_drop_frac=float(tail_drop_frac),
                tail_persist_frames=int(tail_persist_frames),
                steady_fit_mode=str(steady_fit_mode),
                steady_fit_exclude_last_trusted_frames=int(
                    steady_fit_exclude_last_trusted_frames
                ),
                min_steady_frames=int(min_steady_frames),
                steady_width_tol_frac=float(steady_width_tol_frac),
                steady_width_tol_px=float(steady_width_tol_px),
                flow_fit_backfill_max_frames=int(flow_fit_backfill_max_frames),
                flow_fit_backfill_width_delta_px=float(flow_fit_backfill_width_delta_px),
                flow_fit_backfill_monotonic_slack_px=float(
                    flow_fit_backfill_monotonic_slack_px
                ),
                tail_start_mode=str(tail_start_mode),
                tail_direct_target_drop_to_threshold_frac=float(
                    tail_direct_target_drop_to_threshold_frac
                ),
                tail_direct_target_peak_lead_us=float(tail_direct_target_peak_lead_us),
                tail_direct_target_shrink_rate_ratio=float(
                    tail_direct_target_shrink_rate_ratio
                ),
                tail_shoulder_target_drop_to_threshold_frac=float(
                    tail_shoulder_target_drop_to_threshold_frac
                ),
                tail_shoulder_target_peak_lead_us=float(tail_shoulder_target_peak_lead_us),
                tail_shoulder_target_shrink_rate_ratio=float(
                    tail_shoulder_target_shrink_rate_ratio
                ),
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
                volume_uncertainty_sample_count=max(1, int(volume_uncertainty_sample_count)),
                volume_uncertainty_seed=int(volume_uncertainty_seed),
                tail_uncertainty_score_tolerance=float(
                    tail_uncertainty_score_tolerance
                ),
                steady_fit_r2_min=float(steady_fit_r2_min),
                steady_fit_nrmse_max=float(steady_fit_nrmse_max),
            )
            source = dict(run_context.get("source") or {})
            stage5_paths = fit_mod._write_stage5_outputs(
                output_path,
                run_id,
                stage5_run,
                run_dir=(run_context.get("metadata_snapshot") or {}).get("run_dir"),
                parameters=parameter_payload,
                analysis_source_mode=analysis_source_mode,
                cache_source_kind=source.get("kind"),
                phase_input_csv=cache_paths["phase_input_csv"],
                run_context_json=cache_paths["run_context_json"],
                referenced_stage4_fit_output_root=source.get("stage4_output_root")
                or source.get("source_output_root"),
                referenced_stage4_manifest_json=source.get("stage4_manifest_json"),
                referenced_stage5_fit_output_root=source.get("stage5_output_root")
                or source.get("source_output_root"),
                referenced_stage5_manifest_json=source.get("stage5_manifest_json")
                or source.get("fit_manifest_json"),
            )

        summary_row = review_cache_mod._review_summary_row(
            run_context,
            stage5_run,
            phase_input_csv=None if cache_paths is None else cache_paths["phase_input_csv"],
            run_context_json=None if cache_paths is None else cache_paths["run_context_json"],
            include_suspect_gravimetric=include_suspect_gravimetric,
            analysis_source_mode=analysis_source_mode,
        )
        stage_dir = output_path / "runs" / run_id / SUMMARY_STAGE_DIRNAME
        stage_dir.mkdir(parents=True, exist_ok=True)
        run_summary_json = stage_dir / "run_summary.json"
        run_summary_csv = stage_dir / "run_summary.csv"
        summary_row["run_summary_json"] = str(run_summary_json)
        _write_csv(
            run_summary_csv,
            _preferred_columns([summary_row], review_cache_mod.REVIEW_RUN_SUMMARY_COLUMNS),
            [summary_row],
        )
        run_summary_payload = {
            "schema_version": 1,
            "stage": "summary",
            "run_id": run_id,
            "run_dir": summary_row.get("run_dir"),
            "volume_unit": "nL",
            "summary_row": summary_row,
            "stage5_summary": dict(stage5_run["summary"]),
            "phase_boundaries": dict(stage5_run["phase_boundaries"]),
            "steady_fit": dict(stage5_run["steady_fit_payload"]),
            "middle_extrapolation": dict(stage5_run["middle_payload"]),
            "fov_report": dict(stage5_run["stage4_run"]["fov_report"]),
            "run_context": run_context,
            "analysis_parameters": dict(parameter_payload),
        }
        _write_json(run_summary_json, run_summary_payload)
        run_summaries_written.append(str(run_summary_json))
        summary_rows.append(summary_row)
        review_feature_rows = list(stage5_run.get("phase_feature_rows") or [])
        review_steady_fit = dict(stage5_run.get("steady_fit") or {})
        if not review_steady_fit:
            review_steady_fit = fit_mod._steady_fit_from_payload(
                review_feature_rows,
                dict(stage5_run.get("steady_fit_payload") or {}),
            )
        review_tail_onset = dict(stage5_run.get("tail_onset") or {})
        review_fov_report = dict(stage5_run.get("stage4_run", {}).get("fov_report") or {})
        review_phase_boundaries = dict(stage5_run.get("phase_boundaries") or {})
        condition_key = _condition_key(summary_row)
        if condition_key is not None:
            condition_consistency_bundles.append(
                {
                    "condition_key": condition_key,
                    "run_id": run_id,
                    "replicate_index": summary_row.get("replicate_index"),
                    "print_pressure": summary_row.get("print_pressure"),
                    "print_pw_us": summary_row.get("print_pw_us"),
                    "summary_row": dict(summary_row),
                    "phase_feature_rows": review_feature_rows,
                    "steady_fit": review_steady_fit,
                    "tail_onset": review_tail_onset,
                    "phase_boundaries": review_phase_boundaries,
                    "fov_report": review_fov_report,
                    "steady_fit_review_metrics": review_cache_mod._steady_fit_review_metrics(
                        stage5_run,
                        summary_row,
                    ),
                }
            )
        vt_review_rows.append(
            review_cache_mod._vt_review_index_row(
                summary_row,
                stage5_run,
                stage5_paths["vt_fit_png"],
            )
        )

        gravimetric_plot_path = width_review_dir / f"{run_id}_width_trace_with_gravimetric.png"
        review_cache_mod._plot_width_trace_with_gravimetric(
            gravimetric_plot_path,
            review_feature_rows,
            run_id=run_id,
            steady_fit=review_steady_fit,
            tail_onset=review_tail_onset,
            fov_report=review_fov_report,
            gravimetric_equality_delay_us=summary_row.get("gravimetric_equality_delay_us"),
            gravimetric_equality_delay_low_us=summary_row.get(
                "gravimetric_equality_delay_low_us"
            ),
            gravimetric_equality_delay_high_us=summary_row.get(
                "gravimetric_equality_delay_high_us"
            ),
            max_shrink_rate_delay_us=summary_row.get("max_shrink_rate_delay_us"),
            max_shrink_rate_norm_per_ms=summary_row.get("max_shrink_rate_norm_per_ms"),
        )
        if bool(summary_row.get("include_in_gravimetric_plots")):
            width_review_rows.append(
                {
                    key: summary_row.get(key)
                    for key in review_cache_mod.WIDTH_REVIEW_INDEX_COLUMNS
                    if key != "plot_path"
                }
                | {"plot_path": str(gravimetric_plot_path)}
            )

        elapsed_seconds = float(time.perf_counter() - started)
        completed_run_ids.append(run_id)
        _write_progress(
            progress_path,
            _progress_payload(
                selected_run_ids,
                completed_run_ids=completed_run_ids,
                current_run_id=None,
                last_completed_run_id=run_id,
                run_summaries_written=run_summaries_written,
            ),
        )
        partial_total = summary_row.get("partial_total_without_tail_nl")
        gravimetric_total = summary_row.get("gravimetric_total_nl")
        signed_residual = summary_row.get("signed_residual_nl")
        _progress(
            f"[{run_index}/{len(selected_run_ids)}] completed {run_id} in {elapsed_seconds:.1f}s "
            f"steady={summary_row.get('steady_fit_status')} "
            f"tail={summary_row.get('tail_onset_status')} "
            f"middle={summary_row.get('middle_extrapolation_status')} "
            f"partial={('n/a' if partial_total is None else f'{float(partial_total):.3f}')} "
            f"grav={('n/a' if gravimetric_total is None else f'{float(gravimetric_total):.3f}')} "
            f"residual={('n/a' if signed_residual is None else f'{float(signed_residual):.3f}')}"
        )

        run_manifests.append(
            {
                "run_id": run_id,
                "run_dir": summary_row.get("run_dir"),
                "stage5_fit_manifest_json": str(stage5_paths["fit_manifest_json"]),
                "run_summary_json": str(run_summary_json),
                "steady_fit_status": summary_row.get("steady_fit_status"),
                "tail_onset_status": summary_row.get("tail_onset_status"),
                "tail_detection_mode": summary_row.get("tail_detection_mode"),
                "tail_confirmation_capture_index": summary_row.get("tail_confirmation_capture_index"),
                "tail_start_capture_index": summary_row.get("tail_start_capture_index"),
                "middle_extrapolation_status": summary_row.get("middle_extrapolation_status"),
                "partial_total_without_tail_nl": summary_row.get("partial_total_without_tail_nl"),
                "gravimetric_total_nl": summary_row.get("gravimetric_total_nl"),
                "signed_residual_nl": summary_row.get("signed_residual_nl"),
                "include_in_gravimetric_plots": summary_row.get("include_in_gravimetric_plots"),
                "gravimetric_reference_status": summary_row.get("gravimetric_reference_status"),
            }
        )

    condition_rows = review_cache_mod._condition_summary_rows(summary_rows)
    confidence_rows = review_cache_mod._condition_confidence_rows(condition_rows)
    plot_rows = [row for row in summary_rows if bool(row.get("include_in_gravimetric_plots"))]

    experiment_summary_csv = output_path / "experiment_summary.csv"
    experiment_summary_json = output_path / "experiment_summary.json"
    condition_summary_csv = output_path / "condition_summary.csv"
    condition_summary_json = output_path / "condition_summary.json"
    condition_confidence_summary_csv = output_path / "condition_confidence_summary.csv"
    condition_confidence_summary_json = output_path / "condition_confidence_summary.json"
    condition_consistency_summary_csv = output_path / "condition_consistency_summary.csv"
    condition_consistency_summary_json = output_path / "condition_consistency_summary.json"
    scatter_png = output_path / "partial_vs_gravimetric_scatter.png"
    residual_condition_png = output_path / "signed_residual_by_condition.png"
    residual_fraction_condition_png = output_path / "signed_residual_fraction_by_condition.png"
    residual_middle_png = output_path / "signed_residual_vs_middle_duration.png"
    cv_condition_png = output_path / "predicted_vs_gravimetric_cv_by_condition.png"
    uncertainty_condition_png = output_path / "predicted_volume_with_uncertainty_by_condition.png"
    condition_consistency_review_dir = output_path / "condition_consistency_review"
    width_review_index_csv = width_review_dir / "width_trace_review_index.csv"
    width_review_contact_sheet_png = width_review_dir / "width_trace_review_contact_sheet.png"
    vt_review_index_csv = vt_review_dir / "vt_fit_review_index.csv"
    vt_review_contact_sheet_png = vt_review_dir / "vt_fit_review_contact_sheet.png"
    manifest_json = output_path / "summary_manifest.json"
    condition_consistency_rows = _condition_consistency_rows(
        condition_consistency_bundles,
        review_dir=condition_consistency_review_dir,
    )

    metadata_columns = sorted(
        {
            key
            for row in summary_rows
            for key in row.keys()
            if str(key).startswith("metadata_")
            and key not in {"metadata_raw", "metadata_source_path"}
        }
    )
    run_summary_columns = review_cache_mod.REVIEW_RUN_SUMMARY_COLUMNS + [
        key for key in metadata_columns if key not in review_cache_mod.REVIEW_RUN_SUMMARY_COLUMNS
    ]
    _write_csv(experiment_summary_csv, _preferred_columns(summary_rows, run_summary_columns), summary_rows)
    _write_json(
        experiment_summary_json,
        {
            "schema_version": 1,
            "stage": "summary",
            "analysis_source_mode": analysis_source_mode,
            "experiment_root": experiment_root_text,
            "cache_root": None if cache_root is None else str(Path(cache_root).expanduser().resolve()),
            "row_count": len(summary_rows),
            "rows": summary_rows,
        },
    )
    _write_csv(
        condition_summary_csv,
        _preferred_columns(condition_rows, review_cache_mod.REVIEW_CONDITION_SUMMARY_COLUMNS),
        condition_rows,
    )
    _write_json(
        condition_summary_json,
        {
            "schema_version": 1,
            "stage": "summary",
            "analysis_source_mode": analysis_source_mode,
            "experiment_root": experiment_root_text,
            "cache_root": None if cache_root is None else str(Path(cache_root).expanduser().resolve()),
            "row_count": len(condition_rows),
            "rows": condition_rows,
        },
    )
    _write_csv(
        condition_confidence_summary_csv,
        _preferred_columns(confidence_rows, review_cache_mod.CONDITION_CONFIDENCE_SUMMARY_COLUMNS),
        confidence_rows,
    )
    _write_json(
        condition_confidence_summary_json,
        {
            "schema_version": 1,
            "stage": "summary",
            "analysis_source_mode": analysis_source_mode,
            "experiment_root": experiment_root_text,
            "cache_root": None if cache_root is None else str(Path(cache_root).expanduser().resolve()),
            "row_count": len(confidence_rows),
            "rows": confidence_rows,
        },
    )
    _write_csv(
        condition_consistency_summary_csv,
        _preferred_columns(condition_consistency_rows, CONDITION_CONSISTENCY_COLUMNS),
        condition_consistency_rows,
    )
    _write_json(
        condition_consistency_summary_json,
        {
            "schema_version": 1,
            "stage": "summary",
            "analysis_source_mode": analysis_source_mode,
            "experiment_root": experiment_root_text,
            "cache_root": None if cache_root is None else str(Path(cache_root).expanduser().resolve()),
            "grid_spacing_us": float(CONDITION_CONSISTENCY_GRID_SPACING_US),
            "row_count": len(condition_consistency_rows),
            "rows": condition_consistency_rows,
        },
    )
    _write_csv(
        width_review_index_csv,
        _preferred_columns(width_review_rows, review_cache_mod.WIDTH_REVIEW_INDEX_COLUMNS),
        width_review_rows,
    )
    review_cache_mod._plot_width_review_contact_sheet(width_review_contact_sheet_png, width_review_rows)
    _write_csv(
        vt_review_index_csv,
        _preferred_columns(vt_review_rows, review_cache_mod.VT_REVIEW_INDEX_COLUMNS),
        vt_review_rows,
    )
    review_cache_mod._plot_vt_review_contact_sheet(vt_review_contact_sheet_png, vt_review_rows)
    _plot_partial_vs_gravimetric(scatter_png, plot_rows)
    _plot_residual_by_condition(residual_condition_png, condition_rows, plot_rows, fraction=False)
    _plot_residual_by_condition(
        residual_fraction_condition_png,
        condition_rows,
        plot_rows,
        fraction=True,
    )
    _plot_residual_vs_middle_duration(residual_middle_png, plot_rows)
    review_cache_mod._plot_predicted_vs_gravimetric_cv_by_condition(cv_condition_png, condition_rows)
    review_cache_mod._plot_predicted_volume_with_uncertainty_by_condition(
        uncertainty_condition_png,
        summary_rows,
    )

    usable_gravimetric_rows = sum(
        1 for row in summary_rows if bool(row.get("include_in_gravimetric_plots"))
    )
    overprediction_run_count = sum(1 for row in summary_rows if bool(row.get("partial_exceeds_gravimetric")))
    eligible_condition_count = len(condition_consistency_rows)
    plotted_condition_count = sum(
        1 for row in condition_consistency_rows if row.get("vt_overlay_png") or row.get("width_overlay_png")
    )
    manifest = {
        "schema_version": 1,
        "stage": "summary",
        "analysis_source_mode": analysis_source_mode,
        "experiment_root": experiment_root_text,
        "cache_root": None if cache_root is None else str(Path(cache_root).expanduser().resolve()),
        "output_root": str(output_path),
        "selected_run_count": len(selected_run_ids),
        "analyzed_run_count": len(summary_rows),
        "condition_group_count": len(condition_rows),
        "eligible_condition_count": eligible_condition_count,
        "plotted_condition_count": plotted_condition_count,
        "usable_gravimetric_row_count": usable_gravimetric_rows,
        "overprediction_run_count": overprediction_run_count,
        "volume_unit": "nL",
        "water_assumption_nl_per_mg": float(NL_PER_MG_WATER),
        "include_suspect_gravimetric": bool(include_suspect_gravimetric),
        **parameter_payload,
        "outputs": {
            "summary_progress_json": str(progress_path),
            "experiment_summary_csv": str(experiment_summary_csv),
            "experiment_summary_json": str(experiment_summary_json),
            "condition_summary_csv": str(condition_summary_csv),
            "condition_summary_json": str(condition_summary_json),
            "condition_confidence_summary_csv": str(condition_confidence_summary_csv),
            "condition_confidence_summary_json": str(condition_confidence_summary_json),
            "condition_consistency_summary_csv": str(condition_consistency_summary_csv),
            "condition_consistency_summary_json": str(condition_consistency_summary_json),
            "condition_consistency_review_dir": str(condition_consistency_review_dir),
            "partial_vs_gravimetric_scatter_png": str(scatter_png),
            "signed_residual_by_condition_png": str(residual_condition_png),
            "signed_residual_fraction_by_condition_png": str(residual_fraction_condition_png),
            "signed_residual_vs_middle_duration_png": str(residual_middle_png),
            "predicted_vs_gravimetric_cv_by_condition_png": str(cv_condition_png),
            "predicted_volume_with_uncertainty_by_condition_png": str(uncertainty_condition_png),
            "width_review_index_csv": str(width_review_index_csv),
            "width_review_contact_sheet_png": str(width_review_contact_sheet_png),
            "vt_review_index_csv": str(vt_review_index_csv),
            "vt_review_contact_sheet_png": str(vt_review_contact_sheet_png),
        },
        "runs": run_manifests,
    }
    _write_json(manifest_json, manifest)
    manifest["manifest_path"] = str(manifest_json)

    _write_progress(
        progress_path,
        _progress_payload(
            selected_run_ids,
            completed_run_ids=completed_run_ids,
            current_run_id=None,
            last_completed_run_id=(completed_run_ids[-1] if completed_run_ids else None),
            run_summaries_written=run_summaries_written,
        ),
    )
    _progress(f"[summary] completed Stage 6 -> {manifest_json}")
    return manifest
