from __future__ import annotations

import csv
from pathlib import Path

from tools.stream_analysis.dataset import (
    _clean_text,
    _int_or_none,
    _load_json,
    _preferred_columns,
    _write_csv,
    _write_json,
    build_stage0_inventory,
    default_output_root,
)
from tools.stream_analysis import fit as fit_mod
from tools.stream_analysis import summary as summary_mod


FIT_CACHE_STAGE_DIRNAME = "stage_05_review_cache"
FIT_REVIEW_STAGE_DIRNAME = "stage_05_review"
CACHE_MANIFEST_FILENAME = "cache_manifest.json"
CACHE_RUN_MANIFEST_FILENAME = "cache_run_manifest.json"
REVIEW_MANIFEST_FILENAME = "review_manifest.json"
SUSPECT_GRAVIMETRIC_CONDITIONS = {(0.65, 3000)}

RAW_FALLBACK_STAGE5_KWARGS = {
    "sample_count": 6,
    "extra_frame_indices": [],
    "search_width_frac": 0.22,
    "search_top_frac": 0.08,
    "search_bottom_frac": 0.30,
    "blur_sigma": 12.0,
    "residual_threshold": 18,
    "shift_threshold_px": 6.0,
    "confidence_threshold": 0.55,
    "roi_width_frac": 0.35,
    "roi_top_frac": 0.10,
    "roi_bottom_frac": 1.0,
    "corridor_width_frac": 0.70,
    "nozzle_guard_px": 2,
    "min_component_area_px": 120,
    "near_nozzle_band_top_px": 24,
    "near_nozzle_band_height_px": 40,
    "min_band_valid_rows": 24,
    "width_smooth_window": 5,
    "min_steady_frames": 8,
    "steady_width_tol_frac": 0.08,
    "steady_width_tol_px": 4.0,
    "steady_fit_r2_min": 0.985,
    "steady_fit_nrmse_max": 0.03,
    "tail_drop_frac": 0.08,
    "tail_persist_frames": 3,
}

REVIEW_RUN_SUMMARY_COLUMNS = list(summary_mod.RUN_SUMMARY_COLUMNS) + [
    "analysis_source_mode",
    "steady_fit_mode",
    "plateau_capture_indices",
    "plateau_point_count",
    "flow_fit_capture_indices",
    "flow_fit_start_capture_index",
    "flow_fit_end_capture_index",
    "flow_fit_point_count",
    "flow_fit_eligible_point_count",
    "flow_fit_backfill_point_count",
    "flow_fit_outlier_prune_status",
    "flow_fit_dropped_outlier_capture_index",
    "flow_fit_dropped_outlier_delay_from_emergence_us",
    "flow_fit_dropped_outlier_local_deviation_nl",
    "steady_fit_candidate_window_count",
    "steady_fit_selection_score",
    "steady_fit_exclude_last_trusted_frames",
    "steady_fit_excluded_tail_trusted_frame_count",
    "steady_fit_first_last_residual_delta_nl",
    "steady_fit_max_abs_residual_nl",
    "steady_fit_residual_trend_nl_per_us",
    "steady_rate_ci95_contains_central",
    "tail_start_refinement_mode",
    "tail_start_band_selection_status",
    "tail_in_band_candidate_count",
    "tail_start_score",
    "tail_score_candidate_count",
    "tail_score_window_start_capture_index",
    "tail_score_window_end_capture_index",
    "tail_start_drop_frac",
    "tail_start_drop_to_threshold_frac",
    "tail_start_shrink_rate_norm_per_ms",
    "tail_start_shrink_rate_ratio",
    "tail_peak_shrink_rate_norm_per_ms",
    "tail_peak_shrink_rate_delay_us",
    "tail_start_to_tail_peak_delta_us",
    "tail_start_uncertainty_p05_us",
    "tail_start_uncertainty_p95_us",
    "tail_start_uncertainty_candidate_count",
    "tail_start_uncertainty_source",
    "predicted_volume_uncertainty_p05_nl",
    "predicted_volume_uncertainty_p95_nl",
    "predicted_volume_uncertainty_width_nl",
    "predicted_volume_uncertainty_relative_width",
    "predicted_volume_uncertainty_status",
    "volume_uncertainty_sample_count",
    "gravimetric_reference_status",
    "include_in_gravimetric_plots",
    "gravimetric_equality_delay_us",
    "gravimetric_equality_delay_low_us",
    "gravimetric_equality_delay_high_us",
    "gravimetric_equality_band_width_us",
    "gravimetric_equality_confidence_status",
    "gravimetric_eq_width_px",
    "gravimetric_eq_drop_frac",
    "gravimetric_eq_drop_to_threshold_frac",
    "gravimetric_eq_width_low_px",
    "gravimetric_eq_width_high_px",
    "gravimetric_eq_drop_to_threshold_low_frac",
    "gravimetric_eq_drop_to_threshold_high_frac",
    "gravimetric_eq_shrink_rate_norm_per_ms",
    "max_shrink_rate_norm_per_ms",
    "max_shrink_rate_delay_us",
    "gravimetric_eq_to_max_shrink_rate_delta_us",
    "cache_source_kind",
    "phase_input_csv",
    "run_context_json",
]

REVIEW_CONDITION_SUMMARY_COLUMNS = list(summary_mod.CONDITION_SUMMARY_COLUMNS) + [
    "total_run_count",
    "included_run_count",
    "excluded_run_count",
    "predicted_volume_nl_mean",
    "predicted_volume_nl_std_sample",
    "predicted_volume_cv",
    "gravimetric_total_nl_std_sample",
    "gravimetric_total_nl_cv",
    "absolute_residual_nl_mean",
    "absolute_residual_fraction_mean",
    "predicted_volume_uncertainty_width_nl_median",
    "predicted_volume_uncertainty_relative_width_median",
]

CONDITION_CONFIDENCE_SUMMARY_COLUMNS = [
    "condition_key",
    "print_pressure",
    "print_pw_us",
    "included_run_count",
    "predicted_volume_nl_mean",
    "predicted_volume_nl_std_sample",
    "predicted_volume_cv",
    "gravimetric_total_nl_mean",
    "gravimetric_total_nl_std_sample",
    "gravimetric_total_nl_cv",
    "signed_residual_fraction_mean",
    "absolute_residual_fraction_mean",
    "predicted_volume_uncertainty_relative_width_median",
]

WIDTH_REVIEW_INDEX_COLUMNS = [
    "run_id",
    "print_pressure",
    "print_pw_us",
    "signed_residual_nl",
    "partial_total_without_tail_nl",
    "gravimetric_total_nl",
    "tail_detection_mode",
    "tail_start_selection_mode",
    "tail_start_refinement_mode",
    "tail_start_band_selection_status",
    "tail_in_band_candidate_count",
    "fov_exit_delay_from_emergence_us",
    "tail_confirmation_delay_from_emergence_us",
    "preliminary_tail_start_delay_from_emergence_us",
    "direct_final_tail_start_delay_from_emergence_us",
    "tail_shoulder_end_delay_from_emergence_us",
    "tail_start_delay_from_emergence_us",
    "tail_start_score",
    "tail_score_candidate_count",
    "tail_score_window_start_capture_index",
    "tail_score_window_end_capture_index",
    "tail_start_drop_frac",
    "tail_start_drop_to_threshold_frac",
    "tail_start_shrink_rate_norm_per_ms",
    "tail_start_shrink_rate_ratio",
    "tail_peak_shrink_rate_norm_per_ms",
    "tail_peak_shrink_rate_delay_us",
    "tail_start_to_tail_peak_delta_us",
    "gravimetric_equality_delay_us",
    "gravimetric_equality_delay_low_us",
    "gravimetric_equality_delay_high_us",
    "gravimetric_equality_band_width_us",
    "steady_rate_ci95_relative_width",
    "gravimetric_eq_width_px",
    "gravimetric_eq_drop_frac",
    "gravimetric_eq_drop_to_threshold_frac",
    "gravimetric_eq_width_low_px",
    "gravimetric_eq_width_high_px",
    "gravimetric_eq_drop_to_threshold_low_frac",
    "gravimetric_eq_drop_to_threshold_high_frac",
    "gravimetric_eq_shrink_rate_norm_per_ms",
    "max_shrink_rate_norm_per_ms",
    "max_shrink_rate_delay_us",
    "gravimetric_eq_to_max_shrink_rate_delta_us",
    "plot_path",
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

VT_REVIEW_INDEX_COLUMNS = [
    "run_id",
    "print_pressure",
    "print_pw_us",
    "steady_fit_status",
    "steady_fit_mode",
    "plateau_point_count",
    "flow_fit_start_capture_index",
    "flow_fit_end_capture_index",
    "flow_fit_point_count",
    "flow_fit_eligible_point_count",
    "flow_fit_backfill_point_count",
    "flow_fit_outlier_prune_status",
    "flow_fit_dropped_outlier_capture_index",
    "flow_fit_dropped_outlier_delay_from_emergence_us",
    "flow_fit_dropped_outlier_local_deviation_nl",
    "steady_fit_point_count",
    "steady_fit_candidate_window_count",
    "steady_fit_selection_score",
    "steady_fit_exclude_last_trusted_frames",
    "steady_fit_excluded_tail_trusted_frame_count",
    "steady_duration_us",
    "flow_fit_duration_us",
    "steady_rate_nl_per_us",
    "steady_rate_ci95_low_nl_per_us",
    "steady_rate_ci95_high_nl_per_us",
    "steady_rate_ci95_relative_width",
    "steady_rate_ci95_contains_central",
    "steady_r2",
    "steady_nrmse",
    "fov_exit_delay_from_emergence_us",
    "first_trusted_delay_from_emergence_us",
    "plateau_start_after_first_trusted_us",
    "plateau_end_to_fov_exit_us",
    "steady_start_after_first_trusted_us",
    "steady_end_to_fov_exit_us",
    "flow_fit_start_after_first_trusted_us",
    "flow_fit_end_to_fov_exit_us",
    "steady_fit_first_last_residual_delta_nl",
    "steady_fit_max_abs_residual_nl",
    "steady_fit_residual_trend_nl_per_us",
    "plot_path",
]


def default_cache_root(experiment_root: str | Path) -> Path:
    return default_output_root(experiment_root) / FIT_CACHE_STAGE_DIRNAME


def default_review_output_root(cache_root: str | Path) -> Path:
    return Path(cache_root).expanduser().resolve().parent / FIT_REVIEW_STAGE_DIRNAME


def _load_csv_rows(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sample_std_or_none(values: list[float]):
    if len(values) < 2:
        return None
    return float(summary_mod.np.std(summary_mod.np.asarray(values, dtype=float), ddof=1))


def _cv_or_none(values: list[float]):
    mean_value = summary_mod._mean_or_none(values)
    std_value = _sample_std_or_none(values)
    if mean_value is None or std_value is None or float(mean_value) == 0.0:
        return None
    return float(std_value / abs(float(mean_value)))


def _median_or_none(values: list[float]):
    if not values:
        return None
    return float(summary_mod.np.median(summary_mod.np.asarray(values, dtype=float)))


def _metadata_snapshot(run_row: dict):
    return {str(key): value for key, value in dict(run_row).items()}


def _gravimetric_reference_status(
    print_pressure: float | None,
    print_pw_us: int | None,
    gravimetric_total_nl: float | None,
):
    if gravimetric_total_nl is None:
        return "missing"
    condition_key = (
        None if print_pressure is None else float(print_pressure),
        None if print_pw_us is None else int(print_pw_us),
    )
    if condition_key in SUSPECT_GRAVIMETRIC_CONDITIONS:
        return "suspect_pre_microbalance"
    return "ok"


def _default_include_in_gravimetric_plots(gravimetric_reference_status: str):
    return _clean_text(gravimetric_reference_status) == "ok"


def _minimal_fov_report(phase_boundaries: dict):
    first_untrusted_capture_index = _int_or_none(phase_boundaries.get("first_untrusted_capture_index"))
    return {
        "schema_version": 1,
        "first_untrusted_capture_index": first_untrusted_capture_index,
        "first_fov_exit_capture_index": first_untrusted_capture_index,
        "first_untrusted_capture_id": None
        if first_untrusted_capture_index is None
        else f"cap_{int(first_untrusted_capture_index):06d}",
        "first_fov_exit_capture_id": None
        if first_untrusted_capture_index is None
        else f"cap_{int(first_untrusted_capture_index):06d}",
        "first_fov_exit_delay_from_emergence_us": _int_or_none(
            phase_boundaries.get("first_untrusted_delay_from_emergence_us")
        ),
        "first_fov_exit_reason": None,
        "first_fov_exit_flash_delay_us": None,
        "fov_exit_detected": bool(first_untrusted_capture_index is not None),
        "trigger_components": [],
    }


def _cache_context_payload(
    run_row: dict,
    *,
    steady_fit_payload: dict,
    trusted_visible_volume_nl: float | None,
    first_untrusted_capture_index: int | None,
    first_untrusted_delay_from_emergence_us: int | None,
    fov_report: dict,
    source: dict,
):
    metadata_snapshot = _metadata_snapshot(run_row)
    metadata_metrics = summary_mod._metadata_metrics(metadata_snapshot)
    gravimetric_total_nl = summary_mod._gravimetric_fields(
        mass_per_print_mg=metadata_metrics["mass_per_print_mg"],
        partial_total_without_tail_nl=None,
    )["gravimetric_total_nl"]
    gravimetric_reference_status = _gravimetric_reference_status(
        metadata_metrics["print_pressure"],
        metadata_metrics["print_pw_us"],
        gravimetric_total_nl,
    )
    return {
        "schema_version": 1,
        "stage": "review_cache",
        "run_id": run_row.get("run_id"),
        "run_dir": run_row.get("run_dir"),
        "metadata_snapshot": metadata_snapshot,
        "metadata_metrics": metadata_metrics,
        "gravimetric_total_nl": gravimetric_total_nl,
        "gravimetric_reference_status": gravimetric_reference_status,
        "default_include_in_gravimetric_plots": _default_include_in_gravimetric_plots(
            gravimetric_reference_status
        ),
        "frozen_anchors": {
            "trusted_visible_volume_nl": trusted_visible_volume_nl,
            "first_untrusted_capture_index": first_untrusted_capture_index,
            "first_untrusted_delay_from_emergence_us": first_untrusted_delay_from_emergence_us,
        },
        "frozen_steady_fit": dict(steady_fit_payload),
        "fov_report": dict(fov_report),
        "source": dict(source),
    }


def _cache_entry_paths(cache_root: str | Path, run_id: str):
    cache_root_path = Path(cache_root).expanduser().resolve()
    stage_dir = cache_root_path / "runs" / str(run_id) / FIT_CACHE_STAGE_DIRNAME
    return {
        "stage_dir": stage_dir,
        "phase_input_csv": stage_dir / "phase_input.csv",
        "run_context_json": stage_dir / "run_context.json",
        "cache_run_manifest_json": stage_dir / CACHE_RUN_MANIFEST_FILENAME,
    }


def _review_entry_paths(output_root: str | Path, run_id: str):
    output_root_path = Path(output_root).expanduser().resolve()
    stage_dir = output_root_path / "runs" / str(run_id) / FIT_REVIEW_STAGE_DIRNAME
    return {
        "stage_dir": stage_dir,
        "phase_features_csv": stage_dir / "phase_features.csv",
        "tail_start_candidates_csv": stage_dir / "tail_start_candidates.csv",
        "phase_boundaries_json": stage_dir / "phase_boundaries.json",
        "steady_fit_json": stage_dir / "steady_fit.json",
        "middle_extrapolation_json": stage_dir / "middle_extrapolation.json",
        "run_summary_json": stage_dir / "run_summary.json",
        "run_summary_csv": stage_dir / "run_summary.csv",
        "width_trace_png": stage_dir / "width_trace.png",
        "vt_fit_png": stage_dir / "Vt_fit.png",
        "review_manifest_json": stage_dir / REVIEW_MANIFEST_FILENAME,
    }


def _cache_entry_valid(paths: dict):
    return paths["phase_input_csv"].exists() and paths["run_context_json"].exists()


def _candidate_source_roots(experiment_root: str | Path, source_output_root: str | Path | None):
    roots = []
    if source_output_root:
        roots.append(Path(source_output_root).expanduser().resolve())
    default_root = default_output_root(experiment_root)
    if default_root not in roots:
        roots.append(default_root)
    return roots


def _source_stage5_paths(source_root: str | Path, run_id: str):
    source_root_path = Path(source_root).expanduser().resolve()
    stage_dir = source_root_path / "runs" / str(run_id) / fit_mod.FIT_STAGE_DIRNAME
    return {
        "stage_dir": stage_dir,
        "phase_features_csv": stage_dir / "phase_features.csv",
        "steady_fit_json": stage_dir / "steady_fit.json",
        "middle_extrapolation_json": stage_dir / "middle_extrapolation.json",
        "phase_boundaries_json": stage_dir / "phase_boundaries.json",
        "fit_manifest_json": stage_dir / "fit_manifest.json",
    }


def _source_stage4_paths(source_root: str | Path, run_id: str):
    source_root_path = Path(source_root).expanduser().resolve()
    stage_dir = source_root_path / "runs" / str(run_id) / "stage_04_volume"
    return {
        "stage_dir": stage_dir,
        "volume_manifest_json": stage_dir / "volume_manifest.json",
    }


def _import_stage5_artifacts(run_row: dict, source_root: str | Path):
    run_id = str(run_row["run_id"])
    source_paths = _source_stage5_paths(source_root, run_id)
    stage4_paths = _source_stage4_paths(source_root, run_id)
    required_paths = [
        source_paths["phase_features_csv"],
        source_paths["steady_fit_json"],
        source_paths["middle_extrapolation_json"],
        source_paths["phase_boundaries_json"],
    ]
    missing_paths = [path for path in required_paths if not path.exists()]
    if missing_paths:
        missing_text = ", ".join(str(path) for path in missing_paths)
        raise FileNotFoundError(f"Missing Stage 5 artifacts for {run_id}: {missing_text}")

    feature_rows = _load_csv_rows(source_paths["phase_features_csv"])
    phase_input_rows = fit_mod._phase_input_rows_from_feature_rows(feature_rows)
    steady_fit_payload = _load_json(source_paths["steady_fit_json"])
    middle_payload = _load_json(source_paths["middle_extrapolation_json"])
    phase_boundaries = _load_json(source_paths["phase_boundaries_json"])
    fit_manifest = (
        _load_json(source_paths["fit_manifest_json"])
        if source_paths["fit_manifest_json"].exists()
        else {}
    )
    fov_report = dict(fit_manifest.get("fov_report") or _minimal_fov_report(phase_boundaries))
    first_untrusted_capture_index = _int_or_none(
        middle_payload.get("first_untrusted_capture_index")
        if middle_payload.get("first_untrusted_capture_index") not in (None, "")
        else phase_boundaries.get("first_untrusted_capture_index")
    )
    first_untrusted_delay_from_emergence_us = _int_or_none(
        middle_payload.get("first_untrusted_delay_from_emergence_us")
        if middle_payload.get("first_untrusted_delay_from_emergence_us") not in (None, "")
        else phase_boundaries.get("first_untrusted_delay_from_emergence_us")
    )

    run_context = _cache_context_payload(
        run_row,
        steady_fit_payload=steady_fit_payload,
        trusted_visible_volume_nl=summary_mod._float_or_none(
            middle_payload.get("trusted_visible_volume_nl")
        ),
        first_untrusted_capture_index=first_untrusted_capture_index,
        first_untrusted_delay_from_emergence_us=first_untrusted_delay_from_emergence_us,
        fov_report=fov_report,
        source={
            "kind": "stage5_output_import",
            "source_output_root": str(Path(source_root).expanduser().resolve()),
            "stage4_output_root": str(Path(source_root).expanduser().resolve()),
            "stage4_manifest_json": str(stage4_paths["volume_manifest_json"])
            if stage4_paths["volume_manifest_json"].exists()
            else None,
            "stage5_output_root": str(Path(source_root).expanduser().resolve()),
            "stage5_manifest_json": str(source_paths["fit_manifest_json"])
            if source_paths["fit_manifest_json"].exists()
            else None,
            "phase_features_csv": str(source_paths["phase_features_csv"]),
            "steady_fit_json": str(source_paths["steady_fit_json"]),
            "middle_extrapolation_json": str(source_paths["middle_extrapolation_json"]),
            "phase_boundaries_json": str(source_paths["phase_boundaries_json"]),
            "fit_manifest_json": str(source_paths["fit_manifest_json"])
            if source_paths["fit_manifest_json"].exists()
            else None,
            "fit_manifest_summary": {
                key: fit_manifest.get(key)
                for key in [
                    "near_nozzle_band_top_px",
                    "near_nozzle_band_height_px",
                    "min_band_valid_rows",
                    "width_smooth_window",
                    "tail_drop_frac",
                    "tail_persist_frames",
                ]
                if key in fit_manifest
            },
        },
    )
    return {
        "run_id": run_id,
        "phase_input_rows": phase_input_rows,
        "run_context": run_context,
    }


def _build_raw_stage5_cache_entry(run_row: dict, frame_rows: list[dict]):
    run_id = str(run_row["run_id"])
    stage5_run = fit_mod._build_stage5_run(
        run_id,
        frame_rows,
        **dict(RAW_FALLBACK_STAGE5_KWARGS),
    )
    middle_payload = dict(stage5_run["middle_payload"])
    run_context = _cache_context_payload(
        run_row,
        steady_fit_payload=dict(stage5_run["steady_fit_payload"]),
        trusted_visible_volume_nl=summary_mod._float_or_none(
            middle_payload.get("trusted_visible_volume_nl")
        ),
        first_untrusted_capture_index=_int_or_none(
            middle_payload.get("first_untrusted_capture_index")
        ),
        first_untrusted_delay_from_emergence_us=_int_or_none(
            middle_payload.get("first_untrusted_delay_from_emergence_us")
        ),
        fov_report=dict(stage5_run["stage4_run"]["fov_report"]),
        source={
            "kind": "raw_stage5_fallback",
            "stage4_output_root": None,
            "stage4_manifest_json": None,
            "stage5_output_root": None,
            "stage5_manifest_json": None,
            "stage5_kwargs": dict(RAW_FALLBACK_STAGE5_KWARGS),
        },
    )
    return {
        "run_id": run_id,
        "phase_input_rows": fit_mod._phase_input_rows_from_feature_rows(
            stage5_run["phase_feature_rows"]
        ),
        "run_context": run_context,
    }


def _write_cache_entry(cache_root: str | Path, run_id: str, cache_entry: dict):
    paths = _cache_entry_paths(cache_root, run_id)
    phase_input_rows = list(cache_entry["phase_input_rows"])
    run_context = dict(cache_entry["run_context"])
    _write_csv(
        paths["phase_input_csv"],
        _preferred_columns(phase_input_rows, fit_mod.PHASE_INPUT_COLUMNS),
        phase_input_rows,
    )
    _write_json(paths["run_context_json"], run_context)
    _write_json(
        paths["cache_run_manifest_json"],
        {
            "schema_version": 1,
            "stage": "review_cache",
            "run_id": run_id,
            "cache_source_kind": run_context["source"].get("kind"),
            "outputs": {
                "phase_input_csv": str(paths["phase_input_csv"]),
                "run_context_json": str(paths["run_context_json"]),
            },
            "source": dict(run_context["source"]),
        },
    )
    return paths


def _scan_cache_entries(cache_root: str | Path):
    cache_root_path = Path(cache_root).expanduser().resolve()
    runs_root = cache_root_path / "runs"
    if not runs_root.exists():
        return []

    entries = []
    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        paths = _cache_entry_paths(cache_root_path, run_dir.name)
        if not _cache_entry_valid(paths):
            continue
        entries.append(
            {
                "run_id": run_dir.name,
                "paths": paths,
                "run_context": _load_json(paths["run_context_json"]),
            }
        )
    return entries


def _selected_cache_entries(
    cache_root: str | Path,
    *,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
):
    entries = _scan_cache_entries(cache_root)
    entries_by_run_id = {entry["run_id"]: entry for entry in entries}
    if run_ids:
        selected_ids = [str(run_id) for run_id in run_ids]
        missing_ids = [run_id for run_id in selected_ids if run_id not in entries_by_run_id]
        if missing_ids:
            raise FileNotFoundError(
                f"Review cache does not contain selected runs: {', '.join(sorted(missing_ids))}"
            )
        entries = [entries_by_run_id[run_id] for run_id in selected_ids]
    if limit_runs:
        entries = list(entries[: int(limit_runs)])
    return entries


def export_stage5_review_cache(
    experiment_root: str | Path,
    *,
    cache_root: str | Path | None = None,
    source_output_root: str | Path | None = None,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
    include_unmatched: bool = False,
    refresh_missing: bool = False,
    rebuild: bool = False,
):
    del refresh_missing
    inventory = build_stage0_inventory(
        experiment_root,
        include_unmatched=include_unmatched,
        run_ids=run_ids,
        limit_runs=limit_runs,
    )
    cache_root_path = (
        Path(cache_root).expanduser().resolve()
        if cache_root
        else default_cache_root(experiment_root).resolve()
    )
    cache_root_path.mkdir(parents=True, exist_ok=True)

    source_roots = _candidate_source_roots(experiment_root, source_output_root)
    reused_count = 0
    stage5_import_count = 0
    raw_fallback_count = 0
    run_manifests = []

    for run_row in inventory["selected_runs"]:
        run_id = str(run_row["run_id"])
        cache_paths = _cache_entry_paths(cache_root_path, run_id)
        if not rebuild and _cache_entry_valid(cache_paths):
            run_context = _load_json(cache_paths["run_context_json"])
            reused_count += 1
            run_manifests.append(
                {
                    "run_id": run_id,
                    "cache_source_kind": run_context.get("source", {}).get("kind"),
                    "phase_input_csv": str(cache_paths["phase_input_csv"]),
                    "run_context_json": str(cache_paths["run_context_json"]),
                    "cache_run_manifest_json": str(cache_paths["cache_run_manifest_json"])
                    if cache_paths["cache_run_manifest_json"].exists()
                    else None,
                }
            )
            continue

        cache_entry = None
        for candidate_source_root in source_roots:
            try:
                cache_entry = _import_stage5_artifacts(run_row, candidate_source_root)
                stage5_import_count += 1
                break
            except FileNotFoundError:
                continue

        if cache_entry is None:
            frame_rows = list(inventory["frames_by_run_id"].get(run_id) or [])
            if not frame_rows:
                raise ValueError(f"No frame index rows available for run: {run_id}")
            cache_entry = _build_raw_stage5_cache_entry(run_row, frame_rows)
            raw_fallback_count += 1

        cache_paths = _write_cache_entry(cache_root_path, run_id, cache_entry)
        run_manifests.append(
            {
                "run_id": run_id,
                "cache_source_kind": cache_entry["run_context"]["source"].get("kind"),
                "phase_input_csv": str(cache_paths["phase_input_csv"]),
                "run_context_json": str(cache_paths["run_context_json"]),
                "cache_run_manifest_json": str(cache_paths["cache_run_manifest_json"]),
            }
        )

    manifest = {
        "schema_version": 1,
        "stage": "review_cache",
        "experiment_root": inventory["experiment_root"],
        "cache_root": str(cache_root_path),
        "selected_run_count": len(inventory["selected_runs"]),
        "cached_run_count": len(run_manifests),
        "reused_run_count": reused_count,
        "stage5_import_count": stage5_import_count,
        "raw_fallback_count": raw_fallback_count,
        "source_output_roots": [str(path) for path in source_roots],
        "raw_fallback_stage5_kwargs": dict(RAW_FALLBACK_STAGE5_KWARGS),
        "runs": run_manifests,
    }
    manifest_path = cache_root_path / CACHE_MANIFEST_FILENAME
    _write_json(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def _gravimetric_equality_delay_us(summary_row: dict):
    gravimetric_total_nl = summary_mod._float_or_none(summary_row.get("gravimetric_total_nl"))
    trusted_visible_volume_nl = summary_mod._float_or_none(
        summary_row.get("trusted_visible_volume_nl")
    )
    steady_rate_nl_per_us = summary_mod._float_or_none(summary_row.get("steady_rate_nl_per_us"))
    first_untrusted_delay_from_emergence_us = _int_or_none(
        summary_row.get("fov_exit_delay_from_emergence_us")
    )
    if (
        gravimetric_total_nl is None
        or trusted_visible_volume_nl is None
        or steady_rate_nl_per_us is None
        or first_untrusted_delay_from_emergence_us is None
        or float(steady_rate_nl_per_us) == 0.0
    ):
        return None
    return float(first_untrusted_delay_from_emergence_us) + (
        float(gravimetric_total_nl) - float(trusted_visible_volume_nl)
    ) / float(steady_rate_nl_per_us)


def _gravimetric_equality_delay_metrics(summary_row: dict):
    central_delay_us = _gravimetric_equality_delay_us(summary_row)
    metrics = {
        "gravimetric_equality_delay_us": central_delay_us,
        "gravimetric_equality_delay_low_us": None,
        "gravimetric_equality_delay_high_us": None,
        "gravimetric_equality_band_width_us": None,
        "gravimetric_equality_confidence_status": "unresolved_missing_inputs",
    }
    if central_delay_us is None:
        return metrics

    gravimetric_total_nl = summary_mod._float_or_none(summary_row.get("gravimetric_total_nl"))
    trusted_visible_volume_nl = summary_mod._float_or_none(
        summary_row.get("trusted_visible_volume_nl")
    )
    first_untrusted_delay_from_emergence_us = _int_or_none(
        summary_row.get("fov_exit_delay_from_emergence_us")
    )
    rate_low_nl_per_us = summary_mod._float_or_none(
        summary_row.get("steady_rate_ci95_low_nl_per_us")
    )
    rate_high_nl_per_us = summary_mod._float_or_none(
        summary_row.get("steady_rate_ci95_high_nl_per_us")
    )
    if (
        gravimetric_total_nl is None
        or trusted_visible_volume_nl is None
        or first_untrusted_delay_from_emergence_us is None
    ):
        return metrics
    if rate_low_nl_per_us is None or rate_high_nl_per_us is None:
        metrics["gravimetric_equality_confidence_status"] = "unresolved_missing_rate_ci"
        return metrics
    if float(rate_low_nl_per_us) <= 0.0 or float(rate_high_nl_per_us) <= 0.0:
        metrics["gravimetric_equality_confidence_status"] = "unresolved_nonpositive_rate_ci"
        return metrics

    volume_delta_nl = float(gravimetric_total_nl) - float(trusted_visible_volume_nl)
    delay_candidates = [
        float(first_untrusted_delay_from_emergence_us) + (float(volume_delta_nl) / float(rate_low_nl_per_us)),
        float(first_untrusted_delay_from_emergence_us) + (float(volume_delta_nl) / float(rate_high_nl_per_us)),
    ]
    delay_low_us = float(min(delay_candidates))
    delay_high_us = float(max(delay_candidates))
    metrics.update(
        {
            "gravimetric_equality_delay_low_us": delay_low_us,
            "gravimetric_equality_delay_high_us": delay_high_us,
            "gravimetric_equality_band_width_us": float(delay_high_us - delay_low_us),
            "gravimetric_equality_confidence_status": "ok",
        }
    )
    return metrics


def _gravimetric_trace_metrics(stage5_run: dict, summary_row: dict):
    feature_rows = list(stage5_run.get("phase_feature_rows") or [])
    steady_fit = dict(stage5_run.get("steady_fit") or {})
    tail_onset = dict(stage5_run.get("tail_onset") or {})
    width_points = fit_mod._smoothed_width_points_by_delay(feature_rows)
    shrink_rate_points = fit_mod._normalized_width_shrink_rate_points(feature_rows, steady_fit)
    plateau_px = summary_mod._float_or_none(summary_row.get("steady_width_plateau_px"))
    threshold_px = summary_mod._float_or_none(tail_onset.get("tail_width_threshold_px"))

    gravimetric_eq_delay_us = summary_mod._float_or_none(summary_row.get("gravimetric_equality_delay_us"))
    gravimetric_eq_delay_low_us = summary_mod._float_or_none(
        summary_row.get("gravimetric_equality_delay_low_us")
    )
    gravimetric_eq_delay_high_us = summary_mod._float_or_none(
        summary_row.get("gravimetric_equality_delay_high_us")
    )

    gravimetric_eq_width_px = fit_mod._interpolate_series_value(width_points, gravimetric_eq_delay_us)
    gravimetric_eq_width_low_px = fit_mod._interpolate_series_value(
        width_points,
        gravimetric_eq_delay_low_us,
    )
    gravimetric_eq_width_high_px = fit_mod._interpolate_series_value(
        width_points,
        gravimetric_eq_delay_high_us,
    )

    gravimetric_eq_drop_frac = None
    if gravimetric_eq_width_px is not None and plateau_px not in (None, 0.0):
        gravimetric_eq_drop_frac = float(
            (float(plateau_px) - float(gravimetric_eq_width_px)) / float(plateau_px)
        )

    max_shrink_rate_norm_per_ms = None
    max_shrink_rate_delay_us = None
    if shrink_rate_points:
        max_shrink_rate_delay_us, max_shrink_rate_norm_per_ms = max(
            shrink_rate_points,
            key=lambda point: float(point[1]),
        )

    gravimetric_eq_shrink_rate_norm_per_ms = fit_mod._interpolate_series_value(
        shrink_rate_points,
        gravimetric_eq_delay_us,
    )
    gravimetric_eq_to_max_shrink_rate_delta_us = None
    if gravimetric_eq_delay_us is not None and max_shrink_rate_delay_us is not None:
        gravimetric_eq_to_max_shrink_rate_delta_us = float(
            float(gravimetric_eq_delay_us) - float(max_shrink_rate_delay_us)
        )

    return {
        "gravimetric_eq_width_px": gravimetric_eq_width_px,
        "gravimetric_eq_drop_frac": gravimetric_eq_drop_frac,
        "gravimetric_eq_drop_to_threshold_frac": fit_mod._width_drop_to_threshold_fraction(
            gravimetric_eq_width_px,
            plateau_px,
            threshold_px,
        ),
        "gravimetric_eq_width_low_px": gravimetric_eq_width_low_px,
        "gravimetric_eq_width_high_px": gravimetric_eq_width_high_px,
        "gravimetric_eq_drop_to_threshold_low_frac": fit_mod._width_drop_to_threshold_fraction(
            gravimetric_eq_width_low_px,
            plateau_px,
            threshold_px,
        ),
        "gravimetric_eq_drop_to_threshold_high_frac": fit_mod._width_drop_to_threshold_fraction(
            gravimetric_eq_width_high_px,
            plateau_px,
            threshold_px,
        ),
        "gravimetric_eq_shrink_rate_norm_per_ms": gravimetric_eq_shrink_rate_norm_per_ms,
        "max_shrink_rate_norm_per_ms": max_shrink_rate_norm_per_ms,
        "max_shrink_rate_delay_us": max_shrink_rate_delay_us,
        "gravimetric_eq_to_max_shrink_rate_delta_us": gravimetric_eq_to_max_shrink_rate_delta_us,
    }


def _review_summary_row(
    run_context: dict,
    stage5_run: dict,
    *,
    phase_input_csv: Path | None,
    run_context_json: Path | None,
    include_suspect_gravimetric: bool,
    analysis_source_mode: str,
):
    metadata_snapshot = dict(run_context.get("metadata_snapshot") or {})
    metadata_metrics = dict(run_context.get("metadata_metrics") or {})
    summary = dict(stage5_run["summary"])
    phase_boundaries = dict(stage5_run["phase_boundaries"])
    gravimetric = summary_mod._gravimetric_fields(
        mass_per_print_mg=metadata_metrics.get("mass_per_print_mg"),
        partial_total_without_tail_nl=summary_mod._float_or_none(
            summary.get("partial_total_without_tail_nl")
        ),
    )
    gravimetric_reference_status = _clean_text(
        run_context.get("gravimetric_reference_status")
    ) or "missing"
    include_in_gravimetric_plots = bool(
        run_context.get("default_include_in_gravimetric_plots")
    )
    if (
        include_suspect_gravimetric
        and gravimetric.get("gravimetric_total_nl") is not None
        and gravimetric_reference_status != "missing"
    ):
        include_in_gravimetric_plots = True

    source = dict(run_context.get("source") or {})
    row = {
        "run_id": metadata_snapshot.get("run_id"),
        "run_dir": metadata_snapshot.get("run_dir"),
        "metadata_match_status": metadata_snapshot.get("metadata_match_status"),
        "metadata_row_index": _int_or_none(metadata_snapshot.get("metadata_row_index")),
        "outcome": metadata_snapshot.get("outcome"),
        "started_at_utc": metadata_snapshot.get("started_at_utc"),
        "ended_at_utc": metadata_snapshot.get("ended_at_utc"),
        **metadata_metrics,
        **gravimetric,
        "steady_fit_status": summary.get("steady_fit_status"),
        "steady_fit_mode": summary.get("steady_fit_mode"),
        "steady_start_capture_index": _int_or_none(summary.get("steady_start_capture_index")),
        "steady_end_capture_index": _int_or_none(summary.get("steady_end_capture_index")),
        "steady_duration_us": summary_mod._duration_us(
            phase_boundaries.get("steady_start_delay_from_emergence_us"),
            phase_boundaries.get("steady_end_delay_from_emergence_us"),
        ),
        "plateau_capture_indices": list(summary.get("plateau_capture_indices") or []),
        "plateau_point_count": _int_or_none(summary.get("plateau_point_count")),
        "flow_fit_capture_indices": list(summary.get("flow_fit_capture_indices") or []),
        "flow_fit_start_capture_index": _int_or_none(
            summary.get("flow_fit_start_capture_index")
        ),
        "flow_fit_end_capture_index": _int_or_none(summary.get("flow_fit_end_capture_index")),
        "flow_fit_point_count": _int_or_none(summary.get("flow_fit_point_count")),
        "flow_fit_eligible_point_count": _int_or_none(
            summary.get("flow_fit_eligible_point_count")
        ),
        "flow_fit_backfill_point_count": _int_or_none(
            summary.get("flow_fit_backfill_point_count")
        ),
        "flow_fit_outlier_prune_status": summary.get("flow_fit_outlier_prune_status"),
        "flow_fit_dropped_outlier_capture_index": _int_or_none(
            summary.get("flow_fit_dropped_outlier_capture_index")
        ),
        "flow_fit_dropped_outlier_delay_from_emergence_us": _int_or_none(
            summary.get("flow_fit_dropped_outlier_delay_from_emergence_us")
        ),
        "flow_fit_dropped_outlier_local_deviation_nl": summary_mod._float_or_none(
            summary.get("flow_fit_dropped_outlier_local_deviation_nl")
        ),
        "flow_fit_duration_us": summary_mod._duration_us(
            phase_boundaries.get("flow_fit_start_delay_from_emergence_us"),
            phase_boundaries.get("flow_fit_end_delay_from_emergence_us"),
        ),
        "steady_fit_point_count": _int_or_none(summary.get("steady_fit_point_count")),
        "steady_fit_candidate_window_count": _int_or_none(
            summary.get("steady_fit_candidate_window_count")
        ),
        "steady_fit_selection_score": summary_mod._float_or_none(
            summary.get("steady_fit_selection_score")
        ),
        "steady_fit_exclude_last_trusted_frames": _int_or_none(
            summary.get("steady_fit_exclude_last_trusted_frames")
        ),
        "steady_fit_excluded_tail_trusted_frame_count": _int_or_none(
            summary.get("steady_fit_excluded_tail_trusted_frame_count")
        ),
        "steady_rate_nl_per_us": summary_mod._float_or_none(summary.get("steady_rate_nl_per_us")),
        "steady_rate_ci95_low_nl_per_us": summary_mod._float_or_none(
            summary.get("steady_rate_ci95_low_nl_per_us")
        ),
        "steady_rate_ci95_high_nl_per_us": summary_mod._float_or_none(
            summary.get("steady_rate_ci95_high_nl_per_us")
        ),
        "steady_rate_ci95_relative_width": summary_mod._float_or_none(
            summary.get("steady_rate_ci95_relative_width")
        ),
        "steady_rate_ci95_contains_central": (
            None
            if summary.get("steady_rate_ci95_contains_central") in (None, "")
            else bool(summary.get("steady_rate_ci95_contains_central"))
        ),
        "steady_rate_confidence_status": summary.get("steady_rate_confidence_status"),
        "steady_r2": summary_mod._float_or_none(summary.get("steady_r2")),
        "steady_nrmse": summary_mod._float_or_none(summary.get("steady_nrmse")),
        "steady_width_plateau_px": summary_mod._float_or_none(
            summary.get("steady_width_plateau_px")
        ),
        "steady_fit_first_last_residual_delta_nl": summary_mod._float_or_none(
            summary.get("steady_fit_first_last_residual_delta_nl")
        ),
        "steady_fit_max_abs_residual_nl": summary_mod._float_or_none(
            summary.get("steady_fit_max_abs_residual_nl")
        ),
        "steady_fit_residual_trend_nl_per_us": summary_mod._float_or_none(
            summary.get("steady_fit_residual_trend_nl_per_us")
        ),
        "first_untrusted_capture_index": _int_or_none(
            phase_boundaries.get("first_untrusted_capture_index")
        ),
        "fov_exit_delay_from_emergence_us": _int_or_none(
            phase_boundaries.get("first_untrusted_delay_from_emergence_us")
        ),
        "tail_confirmation_capture_index": _int_or_none(
            summary.get("tail_confirmation_capture_index")
        ),
        "tail_confirmation_delay_from_emergence_us": _int_or_none(
            summary.get("tail_confirmation_delay_from_emergence_us")
        ),
        "tail_detection_mode": summary.get("tail_detection_mode"),
        "tail_start_selection_mode": summary.get("tail_start_selection_mode"),
        "tail_start_refinement_mode": summary.get("tail_start_refinement_mode"),
        "tail_start_band_selection_status": summary.get("tail_start_band_selection_status"),
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
        "tail_shoulder_end_capture_index": _int_or_none(
            summary.get("tail_shoulder_end_capture_index")
        ),
        "tail_shoulder_end_delay_from_emergence_us": _int_or_none(
            summary.get("tail_shoulder_end_delay_from_emergence_us")
        ),
        "tail_start_capture_index": _int_or_none(summary.get("tail_start_capture_index")),
        "tail_start_delay_from_emergence_us": _int_or_none(
            summary.get("tail_start_delay_from_emergence_us")
        ),
        "tail_onset_status": summary.get("tail_onset_status"),
        "tail_start_score": summary_mod._float_or_none(summary.get("tail_start_score")),
        "tail_in_band_candidate_count": _int_or_none(
            summary.get("tail_in_band_candidate_count")
        ),
        "tail_score_candidate_count": _int_or_none(
            summary.get("tail_score_candidate_count")
        ),
        "tail_score_window_start_capture_index": _int_or_none(
            summary.get("tail_score_window_start_capture_index")
        ),
        "tail_score_window_end_capture_index": _int_or_none(
            summary.get("tail_score_window_end_capture_index")
        ),
        "tail_start_drop_frac": summary_mod._float_or_none(
            summary.get("tail_start_drop_frac")
        ),
        "tail_start_drop_to_threshold_frac": summary_mod._float_or_none(
            summary.get("tail_start_drop_to_threshold_frac")
        ),
        "tail_start_shrink_rate_norm_per_ms": summary_mod._float_or_none(
            summary.get("tail_start_shrink_rate_norm_per_ms")
        ),
        "tail_start_shrink_rate_ratio": summary_mod._float_or_none(
            summary.get("tail_start_shrink_rate_ratio")
        ),
        "tail_peak_shrink_rate_norm_per_ms": summary_mod._float_or_none(
            summary.get("tail_peak_shrink_rate_norm_per_ms")
        ),
        "tail_peak_shrink_rate_delay_us": summary_mod._float_or_none(
            summary.get("tail_peak_shrink_rate_delay_us")
        ),
        "tail_start_to_tail_peak_delta_us": summary_mod._float_or_none(
            summary.get("tail_start_to_tail_peak_delta_us")
        ),
        "middle_duration_us": summary_mod._duration_us(
            phase_boundaries.get("first_untrusted_delay_from_emergence_us"),
            phase_boundaries.get("tail_start_delay_from_emergence_us"),
        ),
        "trusted_visible_volume_nl": summary_mod._float_or_none(
            summary.get("trusted_visible_volume_nl")
        ),
        "middle_extrapolated_volume_nl": summary_mod._float_or_none(
            summary.get("middle_extrapolated_volume_nl")
        ),
        "partial_total_without_tail_nl": summary_mod._float_or_none(
            summary.get("partial_total_without_tail_nl")
        ),
        "tail_start_uncertainty_p05_us": summary_mod._float_or_none(
            summary.get("tail_start_uncertainty_p05_us")
        ),
        "tail_start_uncertainty_p95_us": summary_mod._float_or_none(
            summary.get("tail_start_uncertainty_p95_us")
        ),
        "tail_start_uncertainty_candidate_count": _int_or_none(
            summary.get("tail_start_uncertainty_candidate_count")
        ),
        "tail_start_uncertainty_source": summary.get("tail_start_uncertainty_source"),
        "predicted_volume_uncertainty_p05_nl": summary_mod._float_or_none(
            summary.get("predicted_volume_uncertainty_p05_nl")
        ),
        "predicted_volume_uncertainty_p95_nl": summary_mod._float_or_none(
            summary.get("predicted_volume_uncertainty_p95_nl")
        ),
        "predicted_volume_uncertainty_width_nl": summary_mod._float_or_none(
            summary.get("predicted_volume_uncertainty_width_nl")
        ),
        "predicted_volume_uncertainty_relative_width": summary_mod._float_or_none(
            summary.get("predicted_volume_uncertainty_relative_width")
        ),
        "predicted_volume_uncertainty_status": summary.get(
            "predicted_volume_uncertainty_status"
        ),
        "volume_uncertainty_sample_count": _int_or_none(
            summary.get("volume_uncertainty_sample_count")
        ),
        "middle_extrapolation_status": summary.get("middle_extrapolation_status"),
        "final_total_status": summary.get("final_total_status"),
        "analysis_source_mode": str(analysis_source_mode),
        "referenced_stage4_fit_output_root": source.get("stage4_output_root")
        or source.get("source_output_root"),
        "referenced_stage4_manifest_json": source.get("stage4_manifest_json"),
        "referenced_stage5_fit_output_root": source.get("stage5_output_root")
        or source.get("source_output_root"),
        "referenced_stage5_manifest_json": source.get("stage5_manifest_json")
        or source.get("fit_manifest_json"),
        "run_summary_json": None,
        "gravimetric_reference_status": gravimetric_reference_status,
        "include_in_gravimetric_plots": include_in_gravimetric_plots,
        "cache_source_kind": source.get("kind"),
        "phase_input_csv": None if phase_input_csv is None else str(phase_input_csv),
        "run_context_json": None if run_context_json is None else str(run_context_json),
    }
    row.update(_gravimetric_equality_delay_metrics(row))
    row.update(_gravimetric_trace_metrics(stage5_run, row))
    for key, value in metadata_snapshot.items():
        if not str(key).startswith("metadata_"):
            continue
        if key in {"metadata_raw", "metadata_source_path"}:
            continue
        row[key] = value
    return row


def _condition_summary_rows(summary_rows: list[dict]):
    grouped = {}
    for row in summary_rows:
        key = summary_mod._condition_key(row)
        grouped.setdefault(key, []).append(row)

    condition_rows = []
    for key, rows in sorted(grouped.items(), key=lambda item: "" if item[0] is None else item[0]):
        included_rows = [row for row in rows if bool(row.get("include_in_gravimetric_plots"))]
        residual_values = [
            float(row["signed_residual_nl"])
            for row in included_rows
            if row.get("signed_residual_nl") is not None
        ]
        absolute_residual_values = [
            abs(float(row["signed_residual_nl"]))
            for row in included_rows
            if row.get("signed_residual_nl") is not None
        ]
        residual_fraction_values = [
            float(row["signed_residual_fraction"])
            for row in included_rows
            if row.get("signed_residual_fraction") is not None
        ]
        absolute_residual_fraction_values = [
            abs(float(row["signed_residual_fraction"]))
            for row in included_rows
            if row.get("signed_residual_fraction") is not None
        ]
        gravimetric_values = [
            float(row["gravimetric_total_nl"])
            for row in included_rows
            if row.get("gravimetric_total_nl") is not None
        ]
        partial_values = [
            float(row["partial_total_without_tail_nl"])
            for row in included_rows
            if row.get("partial_total_without_tail_nl") is not None
        ]
        ratio_values = [
            float(row["partial_to_gravimetric_ratio"])
            for row in included_rows
            if row.get("partial_to_gravimetric_ratio") is not None
        ]
        uncertainty_width_values = [
            float(row["predicted_volume_uncertainty_width_nl"])
            for row in included_rows
            if row.get("predicted_volume_uncertainty_width_nl") is not None
        ]
        uncertainty_relative_width_values = [
            float(row["predicted_volume_uncertainty_relative_width"])
            for row in included_rows
            if row.get("predicted_volume_uncertainty_relative_width") is not None
        ]
        predicted_volume_mean = summary_mod._mean_or_none(partial_values)
        predicted_volume_std_sample = _sample_std_or_none(partial_values)
        gravimetric_mean = summary_mod._mean_or_none(gravimetric_values)
        gravimetric_std_sample = _sample_std_or_none(gravimetric_values)
        condition_rows.append(
            {
                "condition_key": key,
                "print_pressure": summary_mod._float_or_none(rows[0].get("print_pressure")),
                "print_pw_us": _int_or_none(rows[0].get("print_pw_us")),
                "run_count": len(rows),
                "total_run_count": len(rows),
                "included_run_count": len(included_rows),
                "excluded_run_count": len(rows) - len(included_rows),
                "replicate_ids": [
                    row.get("replicate_index") for row in rows if row.get("replicate_index") is not None
                ],
                "gravimetric_total_nl_mean": gravimetric_mean,
                "gravimetric_total_nl_std_sample": gravimetric_std_sample,
                "gravimetric_total_nl_cv": _cv_or_none(gravimetric_values),
                "partial_total_without_tail_nl_mean": predicted_volume_mean,
                "predicted_volume_nl_mean": predicted_volume_mean,
                "predicted_volume_nl_std_sample": predicted_volume_std_sample,
                "predicted_volume_cv": _cv_or_none(partial_values),
                "signed_residual_nl_mean": summary_mod._mean_or_none(residual_values),
                "signed_residual_nl_std": summary_mod._std_or_none(residual_values),
                "signed_residual_fraction_mean": summary_mod._mean_or_none(
                    residual_fraction_values
                ),
                "absolute_residual_nl_mean": summary_mod._mean_or_none(absolute_residual_values),
                "absolute_residual_fraction_mean": summary_mod._mean_or_none(
                    absolute_residual_fraction_values
                ),
                "partial_to_gravimetric_ratio_mean": summary_mod._mean_or_none(ratio_values),
                "predicted_volume_uncertainty_width_nl_median": _median_or_none(
                    uncertainty_width_values
                ),
                "predicted_volume_uncertainty_relative_width_median": _median_or_none(
                    uncertainty_relative_width_values
                ),
                "overprediction_run_count": sum(
                    1 for row in included_rows if bool(row.get("partial_exceeds_gravimetric"))
                ),
            }
        )
    return condition_rows


def _condition_confidence_rows(condition_rows: list[dict]):
    return [
        {
            key: row.get(key)
            for key in CONDITION_CONFIDENCE_SUMMARY_COLUMNS
        }
        for row in condition_rows
    ]


def _plot_predicted_vs_gravimetric_cv_by_condition(path: Path, condition_rows: list[dict]):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    rows = [
        row
        for row in condition_rows
        if row.get("condition_key") is not None
        and row.get("predicted_volume_cv") is not None
        and row.get("gravimetric_total_nl_cv") is not None
    ]

    fig, ax = plt.subplots(figsize=(10, 5))
    if rows:
        x_positions = summary_mod.np.arange(len(rows), dtype=float)
        bar_width = 0.36
        ax.bar(
            x_positions - (bar_width / 2.0),
            [float(row["predicted_volume_cv"]) for row in rows],
            width=bar_width,
            color="#d97706",
            alpha=0.9,
            label="predicted CV",
        )
        ax.bar(
            x_positions + (bar_width / 2.0),
            [float(row["gravimetric_total_nl_cv"]) for row in rows],
            width=bar_width,
            color="#2563eb",
            alpha=0.85,
            label="gravimetric CV",
        )
        ax.set_xticks(list(x_positions))
        ax.set_xticklabels(
            [str(row["condition_key"]) for row in rows],
            rotation=45,
            ha="right",
        )
        ax.legend(loc="best")
    else:
        if hasattr(ax, "text"):
            ax.text(
                0.5,
                0.5,
                "No included conditions with at least two gravimetric runs.",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
        ax.set_xticks([])
    ax.set_title("Predicted vs Gravimetric CV by Condition")
    ax.set_ylabel("Sample coefficient of variation")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _plot_predicted_volume_with_uncertainty_by_condition(path: Path, summary_rows: list[dict]):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    rows = [
        row
        for row in summary_rows
        if bool(row.get("include_in_gravimetric_plots"))
        and row.get("partial_total_without_tail_nl") is not None
        and row.get("gravimetric_total_nl") is not None
        and summary_mod._condition_key(row) is not None
    ]
    grouped = {}
    for row in rows:
        grouped.setdefault(summary_mod._condition_key(row), []).append(row)

    fig, ax = plt.subplots(figsize=(11, 6))
    color_map, marker_map = summary_mod._condition_style_maps(rows)
    x_positions = {key: index for index, key in enumerate(sorted(grouped))}
    for condition_key in sorted(grouped):
        group_rows = sorted(
            grouped[condition_key],
            key=lambda row: (
                _int_or_none(row.get("replicate_index")) or 0,
                _clean_text(row.get("run_id")) or "",
            ),
        )
        if not group_rows:
            continue
        count = len(group_rows)
        if count == 1:
            offsets = [0.0]
        else:
            offsets = summary_mod.np.linspace(-0.18, 0.18, count).tolist()
        x_center = float(x_positions[condition_key])
        for offset, row in zip(offsets, group_rows):
            x_value = float(x_center + float(offset))
            predicted_value = float(row["partial_total_without_tail_nl"])
            gravimetric_value = float(row["gravimetric_total_nl"])
            uncertainty_low = summary_mod._float_or_none(
                row.get("predicted_volume_uncertainty_p05_nl")
            )
            uncertainty_high = summary_mod._float_or_none(
                row.get("predicted_volume_uncertainty_p95_nl")
            )
            error_y = None
            if uncertainty_low is not None and uncertainty_high is not None:
                error_y = [
                    [max(0.0, predicted_value - float(uncertainty_low))],
                    [max(0.0, float(uncertainty_high) - predicted_value)],
                ]
            pressure = summary_mod._float_or_none(row.get("print_pressure"))
            pw = _int_or_none(row.get("print_pw_us"))
            if hasattr(ax, "errorbar"):
                ax.errorbar(
                    [x_value],
                    [predicted_value],
                    yerr=error_y,
                    fmt=marker_map.get(pw, "o"),
                    color=color_map.get(pressure, "#d97706"),
                    mec=color_map.get(pressure, "#d97706"),
                    mfc="white",
                    markersize=6,
                    linewidth=1.1,
                    capsize=3,
                    alpha=0.95,
                )
            elif hasattr(ax, "scatter"):
                ax.scatter(
                    [x_value],
                    [predicted_value],
                    color=color_map.get(pressure, "#d97706"),
                    marker=marker_map.get(pw, "o"),
                    s=36,
                    alpha=0.95,
                )
            if hasattr(ax, "scatter"):
                ax.scatter(
                    [x_value],
                    [gravimetric_value],
                    color="#1f2937",
                    marker="_",
                    s=220,
                    linewidths=1.8,
                    alpha=0.95,
                )

    if x_positions:
        ax.set_xticks(list(x_positions.values()))
        ax.set_xticklabels(list(x_positions.keys()), rotation=45, ha="right")
    else:
        ax.set_xticks([])
    ax.set_title("Predicted Volume with Propagated Uncertainty by Condition")
    ax.set_ylabel("Volume (nL)")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _plot_width_trace_with_gravimetric(
    path: Path,
    feature_rows: list[dict],
    *,
    run_id: str,
    steady_fit: dict,
    tail_onset: dict,
    fov_report: dict,
    gravimetric_equality_delay_us: float | None,
    gravimetric_equality_delay_low_us: float | None = None,
    gravimetric_equality_delay_high_us: float | None = None,
    max_shrink_rate_delay_us: float | None = None,
    max_shrink_rate_norm_per_ms: float | None = None,
):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    x_label, x_values = fit_mod.volume_mod._plot_x_values(feature_rows)
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
    shrink_rate_points = fit_mod._normalized_width_shrink_rate_points(feature_rows, steady_fit)
    if shrink_rate_points and (
        summary_mod._float_or_none(max_shrink_rate_delay_us) is None
        or summary_mod._float_or_none(max_shrink_rate_norm_per_ms) is None
    ):
        max_shrink_rate_delay_us, max_shrink_rate_norm_per_ms = max(
            shrink_rate_points,
            key=lambda point: float(point[1]),
        )

    fig, (ax_top, ax_bottom) = plt.subplots(
        2,
        1,
        figsize=(10, 7.2),
        sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1.2]},
    )
    if raw_points:
        ax_top.plot(
            [x for x, _y in raw_points],
            [y for _x, y in raw_points],
            color="#9db7d5",
            linewidth=1.0,
            alpha=0.8,
            label="raw width",
        )
    if smoothed_points:
        ax_top.plot(
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
            ax_top.plot(
                [x0, x1],
                [float(plateau), float(plateau)],
                color="#228b22",
                linewidth=1.4,
                linestyle="--",
                label="steady plateau",
            )
            if tolerance is not None:
                ax_top.plot(
                    [x0, x1],
                    [float(plateau) + float(tolerance), float(plateau) + float(tolerance)],
                    color="#228b22",
                    linewidth=1.0,
                    linestyle=":",
                    label="steady band",
                )
                ax_top.plot(
                    [x0, x1],
                    [float(plateau) - float(tolerance), float(plateau) - float(tolerance)],
                    color="#228b22",
                    linewidth=1.0,
                    linestyle=":",
                )

    threshold = tail_onset.get("tail_width_threshold_px")
    if threshold is not None and smoothed_points and steady_positions:
        x0 = x_values[steady_positions[-1]]
        x1 = smoothed_points[-1][0]
        if x0 is not None and x1 is not None:
            ax_top.plot(
                [x0, x1],
                [float(threshold), float(threshold)],
                color="#b91c1c",
                linewidth=1.0,
                linestyle="--",
                label="tail threshold",
            )

    gravimetric_equality_delay_low_us = summary_mod._float_or_none(gravimetric_equality_delay_low_us)
    gravimetric_equality_delay_high_us = summary_mod._float_or_none(gravimetric_equality_delay_high_us)
    gravimetric_equality_delay_us = summary_mod._float_or_none(gravimetric_equality_delay_us)
    if (
        gravimetric_equality_delay_low_us is not None
        and gravimetric_equality_delay_high_us is not None
        and float(gravimetric_equality_delay_high_us) > float(gravimetric_equality_delay_low_us)
        and hasattr(ax_top, "axvspan")
    ):
        ax_top.axvspan(
            float(gravimetric_equality_delay_low_us),
            float(gravimetric_equality_delay_high_us),
            color="#6b7280",
            alpha=0.18,
            label="grav eq 95% band",
        )

    for capture_index, label, color, linestyle in [
        (steady_fit.get("steady_start_capture_index"), "steady start", "#228b22", "--"),
        (steady_fit.get("steady_end_capture_index"), "steady end", "#228b22", "-."),
        (fov_report.get("first_untrusted_capture_index"), "first untrusted", "#d62728", "--"),
        (tail_onset.get("tail_confirmation_capture_index"), "tail confirmation", "#c2410c", "-."),
        (tail_onset.get("tail_shoulder_end_capture_index"), "tail shoulder end", "#0f766e", ":"),
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
            ax_top.axvline(x_value, color=color, linestyle=linestyle, linewidth=1.2, label=label)

    if gravimetric_equality_delay_us is not None:
        ax_top.axvline(
            float(gravimetric_equality_delay_us),
            color="#111827",
            linestyle=":",
            linewidth=1.4,
            label="gravimetric equality",
        )

    legacy_tail_anchor = fit_mod._legacy_tail_anchor_from_tail_onset(tail_onset)
    legacy_tail_capture_index = _int_or_none(legacy_tail_anchor.get("capture_index"))
    selected_tail_capture_index = _int_or_none(tail_onset.get("tail_start_capture_index"))
    tail_start_refinement_mode = _clean_text(tail_onset.get("tail_start_refinement_mode"))
    tail_peak_shrink_rate_delay_us = summary_mod._float_or_none(
        tail_onset.get("tail_peak_shrink_rate_delay_us")
    )
    tail_peak_shrink_rate_norm_per_ms = summary_mod._float_or_none(
        tail_onset.get("tail_peak_shrink_rate_norm_per_ms")
    )
    tail_start_band_selection_status = _clean_text(
        tail_onset.get("tail_start_band_selection_status")
    )

    def _capture_index_x_value(capture_index: int | None):
        capture_index = _int_or_none(capture_index)
        if capture_index is None:
            return None
        return next(
            (
                x_val
                for x_val, row in zip(x_values, feature_rows)
                if _int_or_none(row.get("capture_index")) == capture_index
            ),
            None,
        )

    selected_tail_x_value = _capture_index_x_value(selected_tail_capture_index)
    legacy_tail_x_value = _capture_index_x_value(legacy_tail_capture_index)
    if selected_tail_x_value is not None:
        ax_top.axvline(
            float(selected_tail_x_value),
            color="#7c3aed",
            linestyle="--",
            linewidth=1.4,
            label="tail start",
        )
    if (
        tail_start_refinement_mode
        in {
            fit_mod.TAIL_START_REFINEMENT_DESCRIPTOR_SCORE,
            fit_mod.TAIL_START_REFINEMENT_DESCRIPTOR_UNIFIED,
        }
        and legacy_tail_x_value is not None
        and selected_tail_capture_index is not None
        and legacy_tail_capture_index is not None
        and int(legacy_tail_capture_index) != int(selected_tail_capture_index)
    ):
        ax_top.axvline(
            float(legacy_tail_x_value),
            color="#c4b5fd",
            linestyle=":",
            linewidth=1.4,
            label="tail start (legacy)",
        )
    if tail_peak_shrink_rate_delay_us is not None:
        ax_top.axvline(
            float(tail_peak_shrink_rate_delay_us),
            color="#2563eb",
            linestyle="--",
            linewidth=1.1,
            label="tail peak shrink",
        )

    if shrink_rate_points:
        ax_bottom.plot(
            [x for x, _y in shrink_rate_points],
            [y for _x, y in shrink_rate_points],
            color="#0369a1",
            linewidth=1.5,
            label="norm shrink rate",
        )
    ax_bottom.axhline(0.0, color="#94a3b8", linestyle=":", linewidth=1.0)
    if (
        gravimetric_equality_delay_low_us is not None
        and gravimetric_equality_delay_high_us is not None
        and float(gravimetric_equality_delay_high_us) > float(gravimetric_equality_delay_low_us)
        and hasattr(ax_bottom, "axvspan")
    ):
        ax_bottom.axvspan(
            float(gravimetric_equality_delay_low_us),
            float(gravimetric_equality_delay_high_us),
            color="#6b7280",
            alpha=0.18,
            label="grav eq 95% band",
        )
    if gravimetric_equality_delay_us is not None:
        ax_bottom.axvline(
            float(gravimetric_equality_delay_us),
            color="#111827",
            linestyle=":",
            linewidth=1.4,
            label="gravimetric equality",
        )
    if selected_tail_x_value is not None:
        ax_bottom.axvline(
            float(selected_tail_x_value),
            color="#7c3aed",
            linestyle="--",
            linewidth=1.4,
            label="tail start",
        )
    if (
        tail_start_refinement_mode
        in {
            fit_mod.TAIL_START_REFINEMENT_DESCRIPTOR_SCORE,
            fit_mod.TAIL_START_REFINEMENT_DESCRIPTOR_UNIFIED,
        }
        and legacy_tail_x_value is not None
        and selected_tail_capture_index is not None
        and legacy_tail_capture_index is not None
        and int(legacy_tail_capture_index) != int(selected_tail_capture_index)
    ):
        ax_bottom.axvline(
            float(legacy_tail_x_value),
            color="#c4b5fd",
            linestyle=":",
            linewidth=1.4,
            label="tail start (legacy)",
        )
    max_shrink_rate_delay_us = summary_mod._float_or_none(max_shrink_rate_delay_us)
    max_shrink_rate_norm_per_ms = summary_mod._float_or_none(max_shrink_rate_norm_per_ms)
    if max_shrink_rate_delay_us is not None:
        ax_bottom.axvline(
            float(max_shrink_rate_delay_us),
            color="#1d4ed8",
            linestyle="--",
            linewidth=1.1,
            label="max shrink",
        )
    if max_shrink_rate_delay_us is not None and max_shrink_rate_norm_per_ms is not None:
        ax_bottom.scatter(
            [float(max_shrink_rate_delay_us)],
            [float(max_shrink_rate_norm_per_ms)],
            color="#1d4ed8",
            s=28,
            zorder=4,
        )
    if tail_peak_shrink_rate_delay_us is not None:
        ax_bottom.axvline(
            float(tail_peak_shrink_rate_delay_us),
            color="#2563eb",
            linestyle="--",
            linewidth=1.1,
            label="tail peak shrink",
        )
    if tail_peak_shrink_rate_delay_us is not None and tail_peak_shrink_rate_norm_per_ms is not None:
        ax_bottom.scatter(
            [float(tail_peak_shrink_rate_delay_us)],
            [float(tail_peak_shrink_rate_norm_per_ms)],
            color="#2563eb",
            s=26,
            zorder=4,
        )

    descriptor_summary = (
        f"selected drop frac {_format_float(tail_onset.get('tail_start_drop_to_threshold_frac'), digits=3)}"
        f" | shrink ratio {_format_float(tail_onset.get('tail_start_shrink_rate_ratio'), digits=3)}"
        f" | peak lead {_format_delay_us(tail_onset.get('tail_start_to_tail_peak_delta_us'))}"
        f" | score {_format_float(tail_onset.get('tail_start_score'), digits=3)}"
        f" | status {tail_start_band_selection_status or 'n/a'}"
    )
    fig.suptitle(f"Near-Nozzle Width Trace With Gravimetric Confidence - {run_id}")
    ax_top.set_title(descriptor_summary, fontsize=10)
    ax_top.set_ylabel("Attached width (px)")
    ax_top.grid(True, alpha=0.25)
    ax_bottom.set_xlabel(x_label)
    ax_bottom.set_ylabel("Norm shrink\nrate (1/ms)")
    ax_bottom.grid(True, alpha=0.25)

    if hasattr(ax_top, "get_legend_handles_labels"):
        handles, labels = ax_top.get_legend_handles_labels()
        if labels:
            by_label = dict(zip(labels, handles))
            ax_top.legend(by_label.values(), by_label.keys(), loc="best")
    elif hasattr(ax_top, "legend"):
        ax_top.legend(loc="best")
    if hasattr(ax_bottom, "get_legend_handles_labels"):
        handles, labels = ax_bottom.get_legend_handles_labels()
        if labels:
            by_label = dict(zip(labels, handles))
            ax_bottom.legend(by_label.values(), by_label.keys(), loc="best")
    elif hasattr(ax_bottom, "legend"):
        ax_bottom.legend(loc="best")
    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.965])
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _width_review_sort_key(row: dict):
    print_pressure = summary_mod._float_or_none(row.get("print_pressure"))
    print_pw_us = _int_or_none(row.get("print_pw_us"))
    replicate_index = _int_or_none(row.get("replicate_index"))
    run_id = _clean_text(row.get("run_id")) or ""
    return (
        float("inf") if print_pressure is None else float(print_pressure),
        10**9 if print_pw_us is None else int(print_pw_us),
        10**9 if replicate_index is None else int(replicate_index),
        run_id,
    )


def _format_delay_us(value):
    delay_us = summary_mod._float_or_none(value)
    if delay_us is None:
        return "n/a"
    return f"{delay_us:.0f} us"


def _format_float(value, *, digits: int = 2, suffix: str = ""):
    number = summary_mod._float_or_none(value)
    if number is None:
        return "n/a"
    return f"{number:.{int(digits)}f}{suffix}"


def _steady_fit_review_metrics(stage5_run: dict, summary_row: dict):
    feature_rows = list(stage5_run.get("phase_feature_rows") or [])
    steady_fit = dict(stage5_run.get("steady_fit") or {})
    first_trusted_delay_us = None
    trusted_delays = [
        fit_mod._time_axis_value(row, allow_flash_fallback=False)
        for row in feature_rows
        if _clean_text(row.get("volume_trust_label")) == fit_mod.fov_mod.TRUST_LABEL_TRUSTED
        and row.get("total_visible_volume_nl") not in (None, "")
    ]
    trusted_delays = [delay_us for delay_us in trusted_delays if delay_us is not None]
    if trusted_delays:
        first_trusted_delay_us = int(min(trusted_delays))

    plateau_start_delay_us = None
    plateau_end_delay_us = None
    plateau_capture_indices = list(
        steady_fit.get("plateau_capture_indices")
        or steady_fit.get("steady_capture_indices")
        or []
    )
    if plateau_capture_indices:
        plateau_start_row = fit_mod._row_by_capture_index(
            feature_rows,
            _int_or_none(plateau_capture_indices[0]),
        )
        plateau_end_row = fit_mod._row_by_capture_index(
            feature_rows,
            _int_or_none(plateau_capture_indices[-1]),
        )
        plateau_start_delay_us = None if plateau_start_row is None else float(
            _int_or_none(plateau_start_row.get("delay_from_emergence_us"))
        )
        plateau_end_delay_us = None if plateau_end_row is None else float(
            _int_or_none(plateau_end_row.get("delay_from_emergence_us"))
        )

    flow_fit_points = fit_mod._steady_fit_time_volume_points(feature_rows, steady_fit)
    flow_fit_start_delay_us = None
    flow_fit_end_delay_us = None
    if flow_fit_points:
        flow_fit_start_delay_us = float(flow_fit_points[0][0])
        flow_fit_end_delay_us = float(flow_fit_points[-1][0])

    fov_exit_delay_us = summary_mod._float_or_none(
        summary_row.get("fov_exit_delay_from_emergence_us")
    )

    residual_points = fit_mod._steady_fit_residual_points(feature_rows, steady_fit)
    first_last_delta_nl = None
    max_abs_residual_nl = None
    residual_trend_nl_per_us = None
    if residual_points:
        residual_values = [float(residual_nl) for _time_us, residual_nl in residual_points]
        max_abs_residual_nl = float(max(abs(value) for value in residual_values))
        third_count = max(1, int(len(residual_values)) // 3)
        first_last_delta_nl = float(
            (
                sum(residual_values[-third_count:]) / float(third_count)
            )
            - (
                sum(residual_values[:third_count]) / float(third_count)
            )
        )
        if len(residual_points) >= 2:
            times = [float(time_us) for time_us, _residual_nl in residual_points]
            time_mean = float(sum(times) / float(len(times)))
            residual_mean = float(sum(residual_values) / float(len(residual_values)))
            denominator = float(sum((time_us - time_mean) ** 2 for time_us in times))
            if denominator > 0.0:
                residual_trend_nl_per_us = float(
                    sum(
                        (time_us - time_mean) * (residual_nl - residual_mean)
                        for time_us, residual_nl in zip(times, residual_values)
                    )
                    / denominator
                )

    return {
        "first_trusted_delay_from_emergence_us": first_trusted_delay_us,
        "plateau_start_after_first_trusted_us": None
        if first_trusted_delay_us is None or plateau_start_delay_us is None
        else float(plateau_start_delay_us - float(first_trusted_delay_us)),
        "plateau_end_to_fov_exit_us": None
        if fov_exit_delay_us is None or plateau_end_delay_us is None
        else float(float(fov_exit_delay_us) - float(plateau_end_delay_us)),
        "steady_start_after_first_trusted_us": None
        if first_trusted_delay_us is None or flow_fit_start_delay_us is None
        else float(flow_fit_start_delay_us - float(first_trusted_delay_us)),
        "steady_end_to_fov_exit_us": None
        if fov_exit_delay_us is None or flow_fit_end_delay_us is None
        else float(float(fov_exit_delay_us) - float(flow_fit_end_delay_us)),
        "flow_fit_start_after_first_trusted_us": None
        if first_trusted_delay_us is None or flow_fit_start_delay_us is None
        else float(flow_fit_start_delay_us - float(first_trusted_delay_us)),
        "flow_fit_end_to_fov_exit_us": None
        if fov_exit_delay_us is None or flow_fit_end_delay_us is None
        else float(float(fov_exit_delay_us) - float(flow_fit_end_delay_us)),
        "steady_fit_first_last_residual_delta_nl": first_last_delta_nl,
        "steady_fit_max_abs_residual_nl": max_abs_residual_nl,
        "steady_fit_residual_trend_nl_per_us": residual_trend_nl_per_us,
    }


def _vt_review_index_row(summary_row: dict, stage5_run: dict, plot_path: Path):
    return {
        key: summary_row.get(key)
        for key in VT_REVIEW_INDEX_COLUMNS
        if key not in {
            "plot_path",
            "first_trusted_delay_from_emergence_us",
            "plateau_start_after_first_trusted_us",
            "plateau_end_to_fov_exit_us",
            "steady_start_after_first_trusted_us",
            "steady_end_to_fov_exit_us",
            "flow_fit_start_after_first_trusted_us",
            "flow_fit_end_to_fov_exit_us",
            "steady_fit_first_last_residual_delta_nl",
            "steady_fit_max_abs_residual_nl",
            "steady_fit_residual_trend_nl_per_us",
        }
    } | _steady_fit_review_metrics(stage5_run, summary_row) | {"plot_path": str(plot_path)}


def _plot_width_review_contact_sheet(path: Path, width_review_rows: list[dict]):
    import cv2
    import numpy as np

    rows = [
        dict(row)
        for row in sorted(width_review_rows, key=_width_review_sort_key)
        if _clean_text(row.get("plot_path"))
    ]
    if not rows:
        return None

    target_plot_width = 900 if len(rows) <= 12 else 760
    caption_height = 130
    inner_padding = 12
    outer_padding = 18
    gutter = 18
    columns = 1 if len(rows) <= 4 else 2
    font = cv2.FONT_HERSHEY_SIMPLEX

    panels = []
    for row in rows:
        image = cv2.imread(str(row["plot_path"]), cv2.IMREAD_COLOR)
        if image is None:
            continue
        height, width = image.shape[:2]
        if height <= 0 or width <= 0:
            continue
        scale = float(target_plot_width) / float(width)
        resized = cv2.resize(
            image,
            (int(round(width * scale)), int(round(height * scale))),
            interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR,
        )
        panel_height = int(resized.shape[0]) + int(caption_height)
        panel = np.full((panel_height, int(target_plot_width), 3), 255, dtype=np.uint8)
        panel[: resized.shape[0], : resized.shape[1]] = resized

        print_pressure = summary_mod._float_or_none(row.get("print_pressure"))
        print_pw_us = _int_or_none(row.get("print_pw_us"))
        pressure_text = "n/a" if print_pressure is None else f"{print_pressure:g}"
        pw_text = "n/a" if print_pw_us is None else f"{int(print_pw_us)}"
        line_1 = f"{row.get('run_id')} | {pressure_text} bar | {pw_text} us"
        tail_delay = summary_mod._float_or_none(row.get("tail_start_delay_from_emergence_us"))
        grav_delay = summary_mod._float_or_none(row.get("gravimetric_equality_delay_us"))
        grav_band_width_us = summary_mod._float_or_none(row.get("gravimetric_equality_band_width_us"))
        grav_eq_drop_to_threshold_frac = summary_mod._float_or_none(
            row.get("gravimetric_eq_drop_to_threshold_frac")
        )
        gravimetric_eq_shrink_rate_norm_per_ms = summary_mod._float_or_none(
            row.get("gravimetric_eq_shrink_rate_norm_per_ms")
        )
        gravimetric_eq_to_max_shrink_rate_delta_us = summary_mod._float_or_none(
            row.get("gravimetric_eq_to_max_shrink_rate_delta_us")
        )
        tail_start_drop_to_threshold_frac = summary_mod._float_or_none(
            row.get("tail_start_drop_to_threshold_frac")
        )
        tail_start_shrink_rate_ratio = summary_mod._float_or_none(
            row.get("tail_start_shrink_rate_ratio")
        )
        tail_start_to_tail_peak_delta_us = summary_mod._float_or_none(
            row.get("tail_start_to_tail_peak_delta_us")
        )
        tail_start_score = summary_mod._float_or_none(row.get("tail_start_score"))
        tail_start_refinement_mode = _clean_text(row.get("tail_start_refinement_mode")) or "legacy"
        tail_start_band_selection_status = (
            _clean_text(row.get("tail_start_band_selection_status")) or "n/a"
        )
        delta_text = "n/a"
        if tail_delay is not None and grav_delay is not None:
            delta_text = f"{tail_delay - grav_delay:+.0f} us"
        line_2 = (
            f"tail {_format_delay_us(row.get('tail_start_delay_from_emergence_us'))}"
            f" | grav eq {_format_delay_us(row.get('gravimetric_equality_delay_us'))}"
            f" | band {'n/a' if grav_band_width_us is None else f'{grav_band_width_us:.0f} us'}"
        )
        line_3 = (
            f"delta {delta_text}"
            f" | eq frac {'n/a' if grav_eq_drop_to_threshold_frac is None else f'{grav_eq_drop_to_threshold_frac:.2f}'}"
            f" | shrink {'n/a' if gravimetric_eq_shrink_rate_norm_per_ms is None else f'{gravimetric_eq_shrink_rate_norm_per_ms:.2f}/ms'}"
            f" | peak dt {'n/a' if gravimetric_eq_to_max_shrink_rate_delta_us is None else f'{gravimetric_eq_to_max_shrink_rate_delta_us:+.0f} us'}"
        )
        line_4 = (
            f"sel frac {'n/a' if tail_start_drop_to_threshold_frac is None else f'{tail_start_drop_to_threshold_frac:.2f}'}"
            f" | sel ratio {'n/a' if tail_start_shrink_rate_ratio is None else f'{tail_start_shrink_rate_ratio:.2f}'}"
            f" | sel peak {'n/a' if tail_start_to_tail_peak_delta_us is None else f'{tail_start_to_tail_peak_delta_us:.0f} us'}"
            f" | score {'n/a' if tail_start_score is None else f'{tail_start_score:.2f}'}"
            f" | {tail_start_refinement_mode}"
            f" | {tail_start_band_selection_status}"
        )
        cv2.putText(
            panel,
            line_1,
            (inner_padding, int(resized.shape[0]) + 26),
            font,
            0.56,
            (24, 24, 24),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            line_2,
            (inner_padding, int(resized.shape[0]) + 56),
            font,
            0.54,
            (48, 48, 48),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            line_3,
            (inner_padding, int(resized.shape[0]) + 86),
            font,
            0.48,
            (68, 68, 68),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            line_4,
            (inner_padding, int(resized.shape[0]) + 112),
            font,
            0.46,
            (88, 88, 88),
            1,
            cv2.LINE_AA,
        )
        cv2.rectangle(
            panel,
            (0, 0),
            (panel.shape[1] - 1, panel.shape[0] - 1),
            (210, 210, 210),
            1,
        )
        panels.append(panel)

    if not panels:
        return None

    tile_width = max(panel.shape[1] for panel in panels)
    tile_height = max(panel.shape[0] for panel in panels)
    padded_panels = []
    for panel in panels:
        padded = np.full((tile_height, tile_width, 3), 255, dtype=np.uint8)
        padded[: panel.shape[0], : panel.shape[1]] = panel
        padded_panels.append(padded)

    row_count = int((len(padded_panels) + int(columns) - 1) // int(columns))
    canvas_width = (2 * outer_padding) + (int(columns) * tile_width) + ((int(columns) - 1) * gutter)
    canvas_height = (2 * outer_padding) + (row_count * tile_height) + ((row_count - 1) * gutter)
    canvas = np.full((canvas_height, canvas_width, 3), 255, dtype=np.uint8)

    for index, panel in enumerate(padded_panels):
        row_index = int(index // int(columns))
        col_index = int(index % int(columns))
        y0 = int(outer_padding + (row_index * (tile_height + gutter)))
        x0 = int(outer_padding + (col_index * (tile_width + gutter)))
        canvas[y0 : y0 + tile_height, x0 : x0 + tile_width] = panel

    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), canvas)
    return path


def _plot_vt_review_contact_sheet(path: Path, vt_review_rows: list[dict]):
    import cv2
    import numpy as np

    rows = [
        dict(row)
        for row in sorted(vt_review_rows, key=_width_review_sort_key)
        if _clean_text(row.get("plot_path"))
    ]
    if not rows:
        return None

    target_plot_width = 900 if len(rows) <= 12 else 760
    caption_height = 168
    inner_padding = 12
    outer_padding = 18
    gutter = 18
    columns = 1 if len(rows) <= 4 else 2
    font = cv2.FONT_HERSHEY_SIMPLEX

    panels = []
    for row in rows:
        image = cv2.imread(str(row["plot_path"]), cv2.IMREAD_COLOR)
        if image is None:
            continue
        height, width = image.shape[:2]
        if height <= 0 or width <= 0:
            continue
        scale = float(target_plot_width) / float(width)
        resized = cv2.resize(
            image,
            (int(round(width * scale)), int(round(height * scale))),
            interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR,
        )
        panel_height = int(resized.shape[0]) + int(caption_height)
        panel = np.full((panel_height, int(target_plot_width), 3), 255, dtype=np.uint8)
        panel[: resized.shape[0], : resized.shape[1]] = resized

        print_pressure = summary_mod._float_or_none(row.get("print_pressure"))
        print_pw_us = _int_or_none(row.get("print_pw_us"))
        pressure_text = "n/a" if print_pressure is None else f"{print_pressure:g}"
        pw_text = "n/a" if print_pw_us is None else f"{int(print_pw_us)}"
        line_1 = f"{row.get('run_id')} | {pressure_text} bar | {pw_text} us"
        line_2 = (
            f"rate {_format_float(row.get('steady_rate_nl_per_us'), digits=4, suffix=' nL/us')}"
            f" | CI {_format_float(row.get('steady_rate_ci95_low_nl_per_us'), digits=4)}"
            f" to {_format_float(row.get('steady_rate_ci95_high_nl_per_us'), digits=4)}"
            f" | rel width {_format_float(summary_mod._float_or_none(row.get('steady_rate_ci95_relative_width')) * 100.0 if summary_mod._float_or_none(row.get('steady_rate_ci95_relative_width')) is not None else None, digits=1, suffix='%')}"
        )
        line_3 = (
            f"plateau pts {_int_or_none(row.get('plateau_point_count')) if _int_or_none(row.get('plateau_point_count')) is not None else 'n/a'}"
            f" | flow pts {_int_or_none(row.get('flow_fit_point_count')) if _int_or_none(row.get('flow_fit_point_count')) is not None else 'n/a'}"
            f" / {_int_or_none(row.get('flow_fit_eligible_point_count')) if _int_or_none(row.get('flow_fit_eligible_point_count')) is not None else 'n/a'}"
            f" | backfill {_int_or_none(row.get('flow_fit_backfill_point_count')) if _int_or_none(row.get('flow_fit_backfill_point_count')) is not None else 'n/a'}"
            f" | mode {_clean_text(row.get('steady_fit_mode')) or 'n/a'}"
            f" | excl {_int_or_none(row.get('steady_fit_excluded_tail_trusted_frame_count')) if _int_or_none(row.get('steady_fit_excluded_tail_trusted_frame_count')) is not None else 'n/a'}"
        )
        line_4 = (
            f"plateau start {_format_delay_us(row.get('plateau_start_after_first_trusted_us'))}"
            f" | flow start {_format_delay_us(row.get('flow_fit_start_after_first_trusted_us'))}"
            f" | flow exit margin {_format_delay_us(row.get('flow_fit_end_to_fov_exit_us'))}"
        )
        line_5 = (
            f"prune {_clean_text(row.get('flow_fit_outlier_prune_status')) or 'n/a'}"
            f" | dropped {_int_or_none(row.get('flow_fit_dropped_outlier_capture_index')) if _int_or_none(row.get('flow_fit_dropped_outlier_capture_index')) is not None else 'n/a'}"
            f" | dev {_format_float(row.get('flow_fit_dropped_outlier_local_deviation_nl'), digits=3, suffix=' nL')}"
        )
        line_6 = (
            f"fit quality R2 {_format_float(row.get('steady_r2'), digits=4)}"
            f" | NRMSE {_format_float(row.get('steady_nrmse'), digits=4)}"
        )
        line_7 = (
            f"resid delta {_format_float(row.get('steady_fit_first_last_residual_delta_nl'), digits=3, suffix=' nL')}"
            f" | max |r| {_format_float(row.get('steady_fit_max_abs_residual_nl'), digits=3, suffix=' nL')}"
            f" | CI has central {row.get('steady_rate_ci95_contains_central') if row.get('steady_rate_ci95_contains_central') not in (None, '') else 'n/a'}"
        )
        cv2.putText(
            panel,
            line_1,
            (inner_padding, int(resized.shape[0]) + 24),
            font,
            0.56,
            (24, 24, 24),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            line_2,
            (inner_padding, int(resized.shape[0]) + 52),
            font,
            0.50,
            (48, 48, 48),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            line_3,
            (inner_padding, int(resized.shape[0]) + 80),
            font,
            0.48,
            (68, 68, 68),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            line_4,
            (inner_padding, int(resized.shape[0]) + 108),
            font,
            0.46,
            (88, 88, 88),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            line_5,
            (inner_padding, int(resized.shape[0]) + 126),
            font,
            0.44,
            (96, 96, 96),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            line_6,
            (inner_padding, int(resized.shape[0]) + 144),
            font,
            0.44,
            (108, 108, 108),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            line_7,
            (inner_padding, int(resized.shape[0]) + 162),
            font,
            0.42,
            (116, 116, 116),
            1,
            cv2.LINE_AA,
        )
        cv2.rectangle(
            panel,
            (0, 0),
            (panel.shape[1] - 1, panel.shape[0] - 1),
            (210, 210, 210),
            1,
        )
        panels.append(panel)

    if not panels:
        return None

    tile_width = max(panel.shape[1] for panel in panels)
    tile_height = max(panel.shape[0] for panel in panels)
    padded_panels = []
    for panel in panels:
        padded = np.full((tile_height, tile_width, 3), 255, dtype=np.uint8)
        padded[: panel.shape[0], : panel.shape[1]] = panel
        padded_panels.append(padded)

    row_count = int((len(padded_panels) + int(columns) - 1) // int(columns))
    canvas_width = (2 * outer_padding) + (int(columns) * tile_width) + ((int(columns) - 1) * gutter)
    canvas_height = (2 * outer_padding) + (row_count * tile_height) + ((row_count - 1) * gutter)
    canvas = np.full((canvas_height, canvas_width, 3), 255, dtype=np.uint8)

    for index, panel in enumerate(padded_panels):
        row_index = int(index // int(columns))
        col_index = int(index % int(columns))
        y0 = int(outer_padding + (row_index * (tile_height + gutter)))
        x0 = int(outer_padding + (col_index * (tile_width + gutter)))
        canvas[y0 : y0 + tile_height, x0 : x0 + tile_width] = panel

    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), canvas)
    return path


def export_stage5_cached_review(
    cache_root: str | Path,
    *,
    output_root: str | Path | None = None,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
    include_suspect_gravimetric: bool = False,
    width_smooth_window: int = 5,
    steady_fit_mode: str = "frozen",
    steady_fit_exclude_last_trusted_frames: int = 2,
    flow_fit_backfill_max_frames: int = 3,
    flow_fit_backfill_width_delta_px: float = 8.0,
    flow_fit_backfill_monotonic_slack_px: float = 0.75,
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
    tail_drop_frac: float = 0.08,
    tail_persist_frames: int = 3,
):
    cache_root_path = Path(cache_root).expanduser().resolve()
    if not cache_root_path.exists():
        raise FileNotFoundError(f"Review cache root does not exist: {cache_root_path}")

    return summary_mod.export_stage6_summary(
        cache_root=cache_root_path,
        output_root=output_root,
        run_ids=run_ids,
        limit_runs=limit_runs,
        include_suspect_gravimetric=include_suspect_gravimetric,
        width_smooth_window=width_smooth_window,
        steady_fit_mode=steady_fit_mode,
        steady_fit_exclude_last_trusted_frames=steady_fit_exclude_last_trusted_frames,
        flow_fit_backfill_max_frames=flow_fit_backfill_max_frames,
        flow_fit_backfill_width_delta_px=flow_fit_backfill_width_delta_px,
        flow_fit_backfill_monotonic_slack_px=flow_fit_backfill_monotonic_slack_px,
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
        tail_drop_frac=tail_drop_frac,
        tail_persist_frames=tail_persist_frames,
    )

    selected_entries = _selected_cache_entries(
        cache_root_path,
        run_ids=run_ids,
        limit_runs=limit_runs,
    )
    output_path = (
        Path(output_root).expanduser().resolve()
        if output_root
        else default_review_output_root(cache_root_path)
    )
    output_path.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    run_manifests = []
    width_review_rows = []
    vt_review_rows = []
    width_review_dir = output_path / "gravimetric_width_review"
    vt_review_dir = output_path / "vt_fit_review"

    for entry in selected_entries:
        run_id = str(entry["run_id"])
        cache_paths = entry["paths"]
        run_context = dict(entry["run_context"])
        phase_input_rows = _load_csv_rows(cache_paths["phase_input_csv"])
        frozen_anchors = dict(run_context.get("frozen_anchors") or {})
        stage5_run = fit_mod._build_stage5_review_run(
            run_id,
            phase_input_rows,
            steady_fit_payload=dict(run_context.get("frozen_steady_fit") or {}),
            fov_report=dict(run_context.get("fov_report") or {}),
            trusted_visible_volume_nl=summary_mod._float_or_none(
                frozen_anchors.get("trusted_visible_volume_nl")
            ),
            first_untrusted_delay_from_emergence_us=_int_or_none(
                frozen_anchors.get("first_untrusted_delay_from_emergence_us")
            ),
            width_smooth_window=int(width_smooth_window),
            steady_fit_mode=str(steady_fit_mode),
            steady_fit_exclude_last_trusted_frames=max(
                0,
                int(steady_fit_exclude_last_trusted_frames),
            ),
            flow_fit_backfill_max_frames=max(0, int(flow_fit_backfill_max_frames)),
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
            tail_uncertainty_score_tolerance=float(tail_uncertainty_score_tolerance),
            min_steady_frames=int(RAW_FALLBACK_STAGE5_KWARGS["min_steady_frames"]),
            steady_width_tol_frac=float(RAW_FALLBACK_STAGE5_KWARGS["steady_width_tol_frac"]),
            steady_width_tol_px=float(RAW_FALLBACK_STAGE5_KWARGS["steady_width_tol_px"]),
            steady_fit_r2_min=float(RAW_FALLBACK_STAGE5_KWARGS["steady_fit_r2_min"]),
            steady_fit_nrmse_max=float(RAW_FALLBACK_STAGE5_KWARGS["steady_fit_nrmse_max"]),
            tail_drop_frac=float(tail_drop_frac),
            tail_persist_frames=int(tail_persist_frames),
        )

        review_paths = _review_entry_paths(output_path, run_id)
        fit_mod._plot_width_trace(
            review_paths["width_trace_png"],
            stage5_run["phase_feature_rows"],
            run_id=run_id,
            steady_fit=stage5_run["steady_fit"],
            tail_onset=stage5_run["tail_onset"],
            fov_report=stage5_run["stage4_run"]["fov_report"],
        )
        fit_mod._plot_vt_fit(
            review_paths["vt_fit_png"],
            stage5_run["phase_feature_rows"],
            run_id=run_id,
            steady_fit=stage5_run["steady_fit"],
            middle=stage5_run["middle_extrapolation"],
            fov_report=stage5_run["stage4_run"]["fov_report"],
            tail_onset=stage5_run["tail_onset"],
        )
        _write_csv(
            review_paths["phase_features_csv"],
            _preferred_columns(stage5_run["phase_feature_rows"], fit_mod.PHASE_FEATURE_COLUMNS),
            stage5_run["phase_feature_rows"],
        )
        _write_csv(
            review_paths["tail_start_candidates_csv"],
            TAIL_START_CANDIDATE_COLUMNS,
            list(stage5_run.get("tail_start_candidate_rows") or []),
        )
        _write_json(review_paths["phase_boundaries_json"], stage5_run["phase_boundaries"])
        _write_json(review_paths["steady_fit_json"], stage5_run["steady_fit_payload"])
        _write_json(review_paths["middle_extrapolation_json"], stage5_run["middle_payload"])

        summary_row = _review_summary_row(
            run_context,
            stage5_run,
            phase_input_csv=cache_paths["phase_input_csv"],
            run_context_json=cache_paths["run_context_json"],
            include_suspect_gravimetric=include_suspect_gravimetric,
        )
        summary_row["run_summary_json"] = str(review_paths["run_summary_json"])
        vt_review_rows.append(_vt_review_index_row(summary_row, stage5_run, review_paths["vt_fit_png"]))
        _write_csv(
            review_paths["run_summary_csv"],
            _preferred_columns([summary_row], REVIEW_RUN_SUMMARY_COLUMNS),
            [summary_row],
        )
        _write_json(
            review_paths["run_summary_json"],
            {
                "schema_version": 1,
                "stage": "fit_review",
                "run_id": run_id,
                "volume_unit": "nL",
                "summary_row": summary_row,
                "stage5_summary": dict(stage5_run["summary"]),
                "phase_boundaries": dict(stage5_run["phase_boundaries"]),
                "steady_fit": dict(stage5_run["steady_fit_payload"]),
                "middle_extrapolation": dict(stage5_run["middle_payload"]),
                "fov_report": dict(stage5_run["stage4_run"]["fov_report"]),
                "run_context": run_context,
                "review_parameters": {
                    "width_smooth_window": int(width_smooth_window),
                    "steady_fit_mode": str(steady_fit_mode),
                    "steady_fit_exclude_last_trusted_frames": max(
                        0,
                        int(steady_fit_exclude_last_trusted_frames),
                    ),
                    "flow_fit_backfill_max_frames": max(0, int(flow_fit_backfill_max_frames)),
                    "flow_fit_backfill_width_delta_px": float(flow_fit_backfill_width_delta_px),
                    "flow_fit_backfill_monotonic_slack_px": float(flow_fit_backfill_monotonic_slack_px),
                    "tail_start_mode": str(tail_start_mode),
                    "tail_direct_target_drop_to_threshold_frac": float(
                        tail_direct_target_drop_to_threshold_frac
                    ),
                    "tail_direct_target_peak_lead_us": float(tail_direct_target_peak_lead_us),
                    "tail_direct_target_shrink_rate_ratio": float(
                        tail_direct_target_shrink_rate_ratio
                    ),
                    "tail_shoulder_target_drop_to_threshold_frac": float(
                        tail_shoulder_target_drop_to_threshold_frac
                    ),
                    "tail_shoulder_target_peak_lead_us": float(
                        tail_shoulder_target_peak_lead_us
                    ),
                    "tail_shoulder_target_shrink_rate_ratio": float(
                        tail_shoulder_target_shrink_rate_ratio
                    ),
                    "tail_score_drop_weight": float(tail_score_drop_weight),
                    "tail_score_peak_lead_weight": float(tail_score_peak_lead_weight),
                    "tail_score_shrink_rate_weight": float(tail_score_shrink_rate_weight),
                    "tail_score_drop_scale": float(tail_score_drop_scale),
                    "tail_score_peak_lead_scale_us": float(tail_score_peak_lead_scale_us),
                    "tail_score_shrink_rate_scale": float(tail_score_shrink_rate_scale),
                    "tail_unified_band_drop_min": float(tail_unified_band_drop_min),
                    "tail_unified_band_drop_max": float(tail_unified_band_drop_max),
                    "tail_unified_band_peak_lead_min_us": float(
                        tail_unified_band_peak_lead_min_us
                    ),
                    "tail_unified_band_peak_lead_max_us": float(
                        tail_unified_band_peak_lead_max_us
                    ),
                    "tail_unified_band_shrink_rate_ratio_min": float(
                        tail_unified_band_shrink_rate_ratio_min
                    ),
                    "tail_unified_band_shrink_rate_ratio_max": float(
                        tail_unified_band_shrink_rate_ratio_max
                    ),
                    "tail_unified_target_drop_to_threshold_frac": float(
                        tail_unified_target_drop_to_threshold_frac
                    ),
                    "tail_unified_target_peak_lead_us": float(
                        tail_unified_target_peak_lead_us
                    ),
                    "tail_unified_target_shrink_rate_ratio": float(
                        tail_unified_target_shrink_rate_ratio
                    ),
                    "volume_uncertainty_sample_count": max(
                        1,
                        int(volume_uncertainty_sample_count),
                    ),
                    "volume_uncertainty_seed": int(volume_uncertainty_seed),
                    "tail_uncertainty_score_tolerance": float(
                        tail_uncertainty_score_tolerance
                    ),
                    "tail_drop_frac": float(tail_drop_frac),
                    "tail_persist_frames": int(tail_persist_frames),
                },
            },
        )

        _write_json(
            review_paths["review_manifest_json"],
            {
                "schema_version": 1,
                "stage": "fit_review",
                "run_id": run_id,
                "cache_root": str(cache_root_path),
                "cache_source_kind": run_context.get("source", {}).get("kind"),
                "review_parameters": {
                    "width_smooth_window": int(width_smooth_window),
                    "steady_fit_mode": str(steady_fit_mode),
                    "steady_fit_exclude_last_trusted_frames": max(
                        0,
                        int(steady_fit_exclude_last_trusted_frames),
                    ),
                    "flow_fit_backfill_max_frames": max(0, int(flow_fit_backfill_max_frames)),
                    "flow_fit_backfill_width_delta_px": float(flow_fit_backfill_width_delta_px),
                    "flow_fit_backfill_monotonic_slack_px": float(flow_fit_backfill_monotonic_slack_px),
                    "tail_start_mode": str(tail_start_mode),
                    "tail_direct_target_drop_to_threshold_frac": float(
                        tail_direct_target_drop_to_threshold_frac
                    ),
                    "tail_direct_target_peak_lead_us": float(tail_direct_target_peak_lead_us),
                    "tail_direct_target_shrink_rate_ratio": float(
                        tail_direct_target_shrink_rate_ratio
                    ),
                    "tail_shoulder_target_drop_to_threshold_frac": float(
                        tail_shoulder_target_drop_to_threshold_frac
                    ),
                    "tail_shoulder_target_peak_lead_us": float(
                        tail_shoulder_target_peak_lead_us
                    ),
                    "tail_shoulder_target_shrink_rate_ratio": float(
                        tail_shoulder_target_shrink_rate_ratio
                    ),
                    "tail_score_drop_weight": float(tail_score_drop_weight),
                    "tail_score_peak_lead_weight": float(tail_score_peak_lead_weight),
                    "tail_score_shrink_rate_weight": float(tail_score_shrink_rate_weight),
                    "tail_score_drop_scale": float(tail_score_drop_scale),
                    "tail_score_peak_lead_scale_us": float(tail_score_peak_lead_scale_us),
                    "tail_score_shrink_rate_scale": float(tail_score_shrink_rate_scale),
                    "tail_unified_band_drop_min": float(tail_unified_band_drop_min),
                    "tail_unified_band_drop_max": float(tail_unified_band_drop_max),
                    "tail_unified_band_peak_lead_min_us": float(
                        tail_unified_band_peak_lead_min_us
                    ),
                    "tail_unified_band_peak_lead_max_us": float(
                        tail_unified_band_peak_lead_max_us
                    ),
                    "tail_unified_band_shrink_rate_ratio_min": float(
                        tail_unified_band_shrink_rate_ratio_min
                    ),
                    "tail_unified_band_shrink_rate_ratio_max": float(
                        tail_unified_band_shrink_rate_ratio_max
                    ),
                    "tail_unified_target_drop_to_threshold_frac": float(
                        tail_unified_target_drop_to_threshold_frac
                    ),
                    "tail_unified_target_peak_lead_us": float(
                        tail_unified_target_peak_lead_us
                    ),
                    "tail_unified_target_shrink_rate_ratio": float(
                        tail_unified_target_shrink_rate_ratio
                    ),
                    "volume_uncertainty_sample_count": max(
                        1,
                        int(volume_uncertainty_sample_count),
                    ),
                    "volume_uncertainty_seed": int(volume_uncertainty_seed),
                    "tail_uncertainty_score_tolerance": float(
                        tail_uncertainty_score_tolerance
                    ),
                    "tail_drop_frac": float(tail_drop_frac),
                    "tail_persist_frames": int(tail_persist_frames),
                },
                "outputs": {key: str(value) for key, value in review_paths.items() if key != "stage_dir"},
            },
        )

        gravimetric_plot_path = width_review_dir / f"{run_id}_width_trace_with_gravimetric.png"
        _plot_width_trace_with_gravimetric(
            gravimetric_plot_path,
            stage5_run["phase_feature_rows"],
            run_id=run_id,
            steady_fit=stage5_run["steady_fit"],
            tail_onset=stage5_run["tail_onset"],
            fov_report=stage5_run["stage4_run"]["fov_report"],
            gravimetric_equality_delay_us=summary_row.get("gravimetric_equality_delay_us"),
            gravimetric_equality_delay_low_us=summary_row.get("gravimetric_equality_delay_low_us"),
            gravimetric_equality_delay_high_us=summary_row.get("gravimetric_equality_delay_high_us"),
            max_shrink_rate_delay_us=summary_row.get("max_shrink_rate_delay_us"),
            max_shrink_rate_norm_per_ms=summary_row.get("max_shrink_rate_norm_per_ms"),
        )
        if bool(summary_row.get("include_in_gravimetric_plots")):
            width_review_rows.append(
                {
                    key: summary_row.get(key)
                    for key in WIDTH_REVIEW_INDEX_COLUMNS
                    if key != "plot_path"
                }
                | {"plot_path": str(gravimetric_plot_path)}
            )

        summary_rows.append(summary_row)
        run_manifests.append(
            {
                "run_id": run_id,
                "run_summary_json": str(review_paths["run_summary_json"]),
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

    condition_rows = _condition_summary_rows(summary_rows)
    confidence_rows = _condition_confidence_rows(condition_rows)
    plot_rows = [row for row in summary_rows if bool(row.get("include_in_gravimetric_plots"))]

    experiment_summary_csv = output_path / "experiment_summary.csv"
    experiment_summary_json = output_path / "experiment_summary.json"
    condition_summary_csv = output_path / "condition_summary.csv"
    condition_summary_json = output_path / "condition_summary.json"
    condition_confidence_summary_csv = output_path / "condition_confidence_summary.csv"
    condition_confidence_summary_json = output_path / "condition_confidence_summary.json"
    scatter_png = output_path / "partial_vs_gravimetric_scatter.png"
    residual_condition_png = output_path / "signed_residual_by_condition.png"
    residual_fraction_condition_png = output_path / "signed_residual_fraction_by_condition.png"
    residual_middle_png = output_path / "signed_residual_vs_middle_duration.png"
    cv_condition_png = output_path / "predicted_vs_gravimetric_cv_by_condition.png"
    uncertainty_condition_png = output_path / "predicted_volume_with_uncertainty_by_condition.png"
    width_review_index_csv = width_review_dir / "width_trace_review_index.csv"
    width_review_contact_sheet_png = width_review_dir / "width_trace_review_contact_sheet.png"
    vt_review_index_csv = vt_review_dir / "vt_fit_review_index.csv"
    vt_review_contact_sheet_png = vt_review_dir / "vt_fit_review_contact_sheet.png"
    manifest_json = output_path / REVIEW_MANIFEST_FILENAME

    metadata_columns = sorted(
        {
            key
            for row in summary_rows
            for key in row.keys()
            if str(key).startswith("metadata_")
            and key not in {"metadata_raw", "metadata_source_path"}
        }
    )
    run_summary_columns = REVIEW_RUN_SUMMARY_COLUMNS + [
        key for key in metadata_columns if key not in REVIEW_RUN_SUMMARY_COLUMNS
    ]
    _write_csv(experiment_summary_csv, _preferred_columns(summary_rows, run_summary_columns), summary_rows)
    _write_json(
        experiment_summary_json,
        {
            "schema_version": 1,
            "stage": "fit_review",
            "cache_root": str(cache_root_path),
            "row_count": len(summary_rows),
            "rows": summary_rows,
        },
    )
    _write_csv(
        condition_summary_csv,
        _preferred_columns(condition_rows, REVIEW_CONDITION_SUMMARY_COLUMNS),
        condition_rows,
    )
    _write_json(
        condition_summary_json,
        {
            "schema_version": 1,
            "stage": "fit_review",
            "cache_root": str(cache_root_path),
            "row_count": len(condition_rows),
            "rows": condition_rows,
        },
    )
    _write_csv(
        condition_confidence_summary_csv,
        _preferred_columns(confidence_rows, CONDITION_CONFIDENCE_SUMMARY_COLUMNS),
        confidence_rows,
    )
    _write_json(
        condition_confidence_summary_json,
        {
            "schema_version": 1,
            "stage": "fit_review",
            "cache_root": str(cache_root_path),
            "row_count": len(confidence_rows),
            "rows": confidence_rows,
        },
    )
    _write_csv(
        width_review_index_csv,
        _preferred_columns(width_review_rows, WIDTH_REVIEW_INDEX_COLUMNS),
        width_review_rows,
    )
    _plot_width_review_contact_sheet(width_review_contact_sheet_png, width_review_rows)
    _write_csv(
        vt_review_index_csv,
        _preferred_columns(vt_review_rows, VT_REVIEW_INDEX_COLUMNS),
        vt_review_rows,
    )
    _plot_vt_review_contact_sheet(vt_review_contact_sheet_png, vt_review_rows)
    summary_mod._plot_partial_vs_gravimetric(scatter_png, plot_rows)
    summary_mod._plot_residual_by_condition(
        residual_condition_png,
        condition_rows,
        plot_rows,
        fraction=False,
    )
    summary_mod._plot_residual_by_condition(
        residual_fraction_condition_png,
        condition_rows,
        plot_rows,
        fraction=True,
    )
    summary_mod._plot_residual_vs_middle_duration(residual_middle_png, plot_rows)
    _plot_predicted_vs_gravimetric_cv_by_condition(cv_condition_png, condition_rows)
    _plot_predicted_volume_with_uncertainty_by_condition(
        uncertainty_condition_png,
        plot_rows,
    )

    manifest = {
        "schema_version": 1,
        "stage": "fit_review",
        "cache_root": str(cache_root_path),
        "output_root": str(output_path),
        "selected_run_count": len(selected_entries),
        "analyzed_run_count": len(summary_rows),
        "condition_group_count": len(condition_rows),
        "usable_gravimetric_row_count": sum(
            1 for row in summary_rows if bool(row.get("include_in_gravimetric_plots"))
        ),
        "excluded_gravimetric_row_count": sum(
            1
            for row in summary_rows
            if row.get("gravimetric_total_nl") is not None
            and not bool(row.get("include_in_gravimetric_plots"))
        ),
        "volume_unit": "nL",
        "include_suspect_gravimetric": bool(include_suspect_gravimetric),
        "width_smooth_window": int(width_smooth_window),
        "steady_fit_mode": str(steady_fit_mode),
        "steady_fit_exclude_last_trusted_frames": max(
            0,
            int(steady_fit_exclude_last_trusted_frames),
        ),
        "flow_fit_backfill_max_frames": max(0, int(flow_fit_backfill_max_frames)),
        "flow_fit_backfill_width_delta_px": float(flow_fit_backfill_width_delta_px),
        "flow_fit_backfill_monotonic_slack_px": float(flow_fit_backfill_monotonic_slack_px),
        "tail_start_mode": str(tail_start_mode),
        "tail_direct_target_drop_to_threshold_frac": float(
            tail_direct_target_drop_to_threshold_frac
        ),
        "tail_direct_target_peak_lead_us": float(tail_direct_target_peak_lead_us),
        "tail_direct_target_shrink_rate_ratio": float(
            tail_direct_target_shrink_rate_ratio
        ),
        "tail_shoulder_target_drop_to_threshold_frac": float(
            tail_shoulder_target_drop_to_threshold_frac
        ),
        "tail_shoulder_target_peak_lead_us": float(tail_shoulder_target_peak_lead_us),
        "tail_shoulder_target_shrink_rate_ratio": float(
            tail_shoulder_target_shrink_rate_ratio
        ),
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
        "tail_unified_target_shrink_rate_ratio": float(
            tail_unified_target_shrink_rate_ratio
        ),
        "volume_uncertainty_sample_count": max(
            1,
            int(volume_uncertainty_sample_count),
        ),
        "volume_uncertainty_seed": int(volume_uncertainty_seed),
        "tail_uncertainty_score_tolerance": float(tail_uncertainty_score_tolerance),
        "tail_drop_frac": float(tail_drop_frac),
        "tail_persist_frames": int(tail_persist_frames),
        "outputs": {
            "experiment_summary_csv": str(experiment_summary_csv),
            "experiment_summary_json": str(experiment_summary_json),
            "condition_summary_csv": str(condition_summary_csv),
            "condition_summary_json": str(condition_summary_json),
            "condition_confidence_summary_csv": str(condition_confidence_summary_csv),
            "condition_confidence_summary_json": str(condition_confidence_summary_json),
            "partial_vs_gravimetric_scatter_png": str(scatter_png),
            "signed_residual_by_condition_png": str(residual_condition_png),
            "signed_residual_fraction_by_condition_png": str(
                residual_fraction_condition_png
            ),
            "signed_residual_vs_middle_duration_png": str(residual_middle_png),
            "predicted_vs_gravimetric_cv_by_condition_png": str(cv_condition_png),
            "predicted_volume_with_uncertainty_by_condition_png": str(
                uncertainty_condition_png
            ),
            "width_trace_review_index_csv": str(width_review_index_csv),
            "width_trace_review_contact_sheet_png": str(width_review_contact_sheet_png),
            "vt_fit_review_index_csv": str(vt_review_index_csv),
            "vt_fit_review_contact_sheet_png": str(vt_review_contact_sheet_png),
        },
        "runs": run_manifests,
    }
    _write_json(manifest_json, manifest)
    manifest["manifest_path"] = str(manifest_json)
    return manifest
