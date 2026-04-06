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


def export_stage6_summary(
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

    selected_run_ids = [str(row["run_id"]) for row in inventory["selected_runs"]]
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
    for run_index, run_row in enumerate(inventory["selected_runs"], start=1):
        run_id = str(run_row["run_id"])
        frame_rows = list(inventory["frames_by_run_id"][run_id])
        if not frame_rows:
            raise ValueError(f"No frame index rows available for run: {run_id}")

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
        stage5_run = fit_mod._build_stage5_run(
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
            near_nozzle_band_top_px=near_nozzle_band_top_px,
            near_nozzle_band_height_px=near_nozzle_band_height_px,
            min_band_valid_rows=min_band_valid_rows,
            width_smooth_window=width_smooth_window,
            min_steady_frames=min_steady_frames,
            steady_width_tol_frac=steady_width_tol_frac,
            steady_width_tol_px=steady_width_tol_px,
            steady_fit_r2_min=steady_fit_r2_min,
            steady_fit_nrmse_max=steady_fit_nrmse_max,
            tail_drop_frac=tail_drop_frac,
            tail_persist_frames=tail_persist_frames,
        )

        summary_row = _run_summary_row(
            dict(run_row),
            stage5_run,
            experiment_root=experiment_root,
            output_root=output_path,
        )
        stage_dir = output_path / "runs" / run_id / SUMMARY_STAGE_DIRNAME
        stage_dir.mkdir(parents=True, exist_ok=True)
        run_summary_json = stage_dir / "run_summary.json"
        summary_row["run_summary_json"] = str(run_summary_json)
        run_summary_payload = {
            "schema_version": 1,
            "stage": "summary",
            "run_id": run_id,
            "run_dir": run_row.get("run_dir"),
            "volume_unit": "nL",
            "summary_row": summary_row,
            "stage5_summary": dict(stage5_run["summary"]),
            "phase_boundaries": dict(stage5_run["phase_boundaries"]),
            "steady_fit": dict(stage5_run["steady_fit_payload"]),
            "middle_extrapolation": dict(stage5_run["middle_payload"]),
            "fov_report": dict(stage5_run["stage4_run"]["fov_report"]),
        }
        _write_json(run_summary_json, run_summary_payload)
        run_summaries_written.append(str(run_summary_json))
        summary_rows.append(summary_row)

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
                "run_dir": run_row.get("run_dir"),
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
            }
        )

    condition_rows = _condition_summary_rows(summary_rows)

    experiment_summary_csv = output_path / "experiment_summary.csv"
    experiment_summary_json = output_path / "experiment_summary.json"
    condition_summary_csv = output_path / "condition_summary.csv"
    condition_summary_json = output_path / "condition_summary.json"
    scatter_png = output_path / "partial_vs_gravimetric_scatter.png"
    residual_condition_png = output_path / "signed_residual_by_condition.png"
    residual_fraction_condition_png = output_path / "signed_residual_fraction_by_condition.png"
    residual_middle_png = output_path / "signed_residual_vs_middle_duration.png"
    manifest_json = output_path / "summary_manifest.json"

    metadata_columns = sorted(
        {
            key
            for row in summary_rows
            for key in row.keys()
            if str(key).startswith("metadata_")
            and key not in {"metadata_raw", "metadata_source_path"}
        }
    )
    run_summary_columns = RUN_SUMMARY_COLUMNS + [
        key for key in metadata_columns if key not in RUN_SUMMARY_COLUMNS
    ]
    _write_csv(experiment_summary_csv, _preferred_columns(summary_rows, run_summary_columns), summary_rows)
    _write_json(
        experiment_summary_json,
        {
            "schema_version": 1,
            "stage": "summary",
            "experiment_root": inventory["experiment_root"],
            "row_count": len(summary_rows),
            "rows": summary_rows,
        },
    )
    _write_csv(condition_summary_csv, _preferred_columns(condition_rows, CONDITION_SUMMARY_COLUMNS), condition_rows)
    _write_json(
        condition_summary_json,
        {
            "schema_version": 1,
            "stage": "summary",
            "experiment_root": inventory["experiment_root"],
            "row_count": len(condition_rows),
            "rows": condition_rows,
        },
    )
    _plot_partial_vs_gravimetric(scatter_png, summary_rows)
    _plot_residual_by_condition(residual_condition_png, condition_rows, summary_rows, fraction=False)
    _plot_residual_by_condition(
        residual_fraction_condition_png,
        condition_rows,
        summary_rows,
        fraction=True,
    )
    _plot_residual_vs_middle_duration(residual_middle_png, summary_rows)

    usable_gravimetric_rows = sum(1 for row in summary_rows if row.get("gravimetric_total_nl") is not None)
    overprediction_run_count = sum(1 for row in summary_rows if bool(row.get("partial_exceeds_gravimetric")))
    manifest = {
        "schema_version": 1,
        "stage": "summary",
        "experiment_root": inventory["experiment_root"],
        "output_root": str(output_path),
        "selected_run_count": len(selected_run_ids),
        "analyzed_run_count": len(summary_rows),
        "condition_group_count": len(condition_rows),
        "usable_gravimetric_row_count": usable_gravimetric_rows,
        "overprediction_run_count": overprediction_run_count,
        "volume_unit": "nL",
        "water_assumption_nl_per_mg": float(NL_PER_MG_WATER),
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
        "outputs": {
            "summary_progress_json": str(progress_path),
            "experiment_summary_csv": str(experiment_summary_csv),
            "experiment_summary_json": str(experiment_summary_json),
            "condition_summary_csv": str(condition_summary_csv),
            "condition_summary_json": str(condition_summary_json),
            "partial_vs_gravimetric_scatter_png": str(scatter_png),
            "signed_residual_by_condition_png": str(residual_condition_png),
            "signed_residual_fraction_by_condition_png": str(residual_fraction_condition_png),
            "signed_residual_vs_middle_duration_png": str(residual_middle_png),
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
