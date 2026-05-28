#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

from LocalConfig import get_calibration_memory_root

RUN_SUMMARY_COLUMNS = [
    "run_id",
    "schema_name",
    "schema_version",
    "summary_path",
    "observations_path",
    "calibration_json_path",
    "run_status",
    "run_completed",
    "started_at_utc",
    "ended_at_utc",
    "last_updated_at_utc",
    "notes",
    "profile_name",
    "experiment_dir",
    "calibration_file_path",
    "stock_id",
    "stock_display_name",
    "stock_concentration",
    "stock_units",
    "reagent_id",
    "reagent_display_name",
    "reagent_family",
    "glycerol_percent",
    "printer_head_id",
    "printer_head_display_name",
    "head_type_id",
    "head_type_display_name",
    "nominal_nozzle_diameter_um",
    "measured_nozzle_diameter_um",
    "nozzle_diameter_um",
    "manufacturer_batch",
    "identity_quality_stock_id",
    "identity_quality_reagent_id",
    "identity_quality_printer_head_id",
    "identity_quality_head_type_id",
    "phase_count_total",
    "phase_counts_json",
    "process_result_keys_json",
    "usable_for_aggregation",
    "qualification_reasons_json",
    "eligible_aggregation_levels_json",
    "pulse_width_us",
    "recommended_pressure_psi",
    "recommended_pressure_source",
    "single_droplet_band_low_psi",
    "single_droplet_band_high_psi",
    "single_droplet_band_source",
    "trajectory_pressure_band_low_psi",
    "trajectory_pressure_band_high_psi",
    "trajectory_pressure_band_source",
    "emergence_time_us",
    "emergence_time_source",
    "expected_mean_volume_nL",
    "expected_cv_pct",
    "volume_source",
    "online_stream_flow_rate_nl_per_us",
    "online_stream_flow_fit_status",
    "online_stream_tail_status",
    "online_stream_tail_start_delay_from_emergence_us",
    "online_stream_predicted_volume_nl",
    "online_stream_print_pressure_psi",
    "online_stream_prior_condition_match",
    "online_stream_prior_source",
    "online_stream_prior_aggregation_level",
    "online_stream_prior_candidate_found",
    "online_stream_prior_fallback_reason",
    "pressure_sweep_row_count",
    "pressure_sweep_valid_row_count",
    "pressure_sweep_valid_band_low_psi",
    "pressure_sweep_valid_band_high_psi",
    "pressure_sweep_preferred_pressure_psi",
    "pressure_sweep_preferred_mean_volume_nL",
    "pressure_sweep_preferred_cv_pct",
    "prior_application_mode",
    "prior_lookup_performed",
    "prior_candidate_found",
    "prior_qualified",
    "prior_applied",
    "prior_application_reason",
    "prior_rejected_reason",
    "prior_fallback_triggered",
    "prior_fallback_reason",
    "prior_candidate_aggregation_level",
    "prior_candidate_match_type",
    "prior_candidate_pulse_match_type",
    "prior_candidate_confidence",
    "prior_candidate_pulse_width_us",
    "prior_candidate_recommended_pressure_psi",
    "prior_candidate_expected_mean_volume_nL",
    "prior_candidate_expected_cv_pct",
    "prior_candidate_contributing_runs",
    "prior_candidate_source_run_ids_json",
    "prior_seed_start_pressure_psi",
    "prior_seed_source",
    "prior_seed_single_band_low_psi",
    "prior_seed_single_band_high_psi",
    "prior_seed_expected_mean_volume_nL",
    "prior_seed_expected_cv_pct",
    "prior_seed_pulse_width_us",
    "prior_usefulness_signal",
    "prior_steps_until_first_single",
    "prior_first_single_pressure_psi",
    "prior_first_single_seed_error_psi",
    "prior_seed_inside_actual_single_band",
    "prior_actual_vs_prior_pressure_error_psi",
    "prior_actual_vs_prior_volume_error_nL",
    "ui_recommendation_shown",
    "ui_recommendation_shown_count",
    "ui_recommendation_applied",
    "ui_recommendation_apply_count",
    "ui_recommendation_ignored",
    "ui_recommendation_ignore_count",
    "ui_recommendation_last_action",
    "ui_recommendation_aggregation_level",
    "ui_recommendation_confidence",
    "ui_recommendation_manual_apply_allowed",
    "ui_recommendation_manual_apply_reason",
    "ui_recommendation_target_pulse_width_us",
    "ui_recommendation_target_volume_nl",
    "context_json",
    "derived_metrics_json",
    "prior_candidate_json",
    "ui_recommendation_json",
]

OBSERVATION_COLUMNS = [
    "run_id",
    "observation_id",
    "schema_name",
    "schema_version",
    "summary_path",
    "observation_path",
    "observation_index",
    "ts_utc",
    "phase",
    "observation_type",
    "run_status",
    "started_at_utc",
    "ended_at_utc",
    "stock_id",
    "stock_display_name",
    "reagent_id",
    "reagent_display_name",
    "reagent_family",
    "printer_head_id",
    "printer_head_display_name",
    "head_type_id",
    "nominal_nozzle_diameter_um",
    "identity_quality_reagent_id",
    "identity_quality_printer_head_id",
    "identity_quality_head_type_id",
    "settings_print_width_us",
    "settings_print_pressure_psi",
    "settings_refuel_pressure_psi",
    "settings_flash_delay_us",
    "settings_flash_duration_us",
    "settings_num_droplets",
    "settings_exposure_time_us",
    "machine_pos_x",
    "machine_pos_y",
    "machine_pos_z",
    "payload_kind",
    "payload_action",
    "payload_reason",
    "payload_verdict",
    "payload_confidence",
    "payload_pressure_psi",
    "payload_print_pulse_width_us",
    "payload_delay_us",
    "payload_mean_volume_nL",
    "payload_cv_pct",
    "payload_valid",
    "payload_aggregation_level",
    "payload_match_type",
    "payload_pulse_match_type",
    "payload_seed_start_pressure_psi",
    "artifact_camera_capture_root",
    "artifact_camera_active_save_dir",
    "artifact_calibration_json_path",
    "artifact_refs_json",
    "settings_json",
    "payload_json",
    "context_json",
]

PLOT_VOLUME_COLUMNS = [
    "run_id",
    "reagent_id",
    "reagent_display_name",
    "head_type_id",
    "printer_head_id",
    "nominal_nozzle_diameter_um",
    "pulse_width_us",
    "recommended_pressure_psi",
    "expected_mean_volume_nL",
    "expected_cv_pct",
    "group_label",
]

PLOT_CV_COLUMNS = [
    "run_id",
    "reagent_id",
    "reagent_display_name",
    "head_type_id",
    "printer_head_id",
    "nominal_nozzle_diameter_um",
    "pulse_width_us",
    "recommended_pressure_psi",
    "expected_cv_pct",
    "expected_mean_volume_nL",
    "group_label",
]

PLOT_EMERGENCE_COLUMNS = [
    "run_id",
    "reagent_id",
    "reagent_display_name",
    "head_type_id",
    "printer_head_id",
    "nominal_nozzle_diameter_um",
    "pulse_width_us",
    "recommended_pressure_psi",
    "emergence_time_us",
    "expected_mean_volume_nL",
    "group_label",
]


def resolve_memory_root(root: str | Path | None = None) -> Path:
    if root:
        return Path(root).expanduser().resolve()
    return get_calibration_memory_root().resolve()


def default_analysis_root(root: str | Path | None = None) -> Path:
    return resolve_memory_root(root) / "analysis"


def default_summary_export_path(root: str | Path | None = None) -> Path:
    return default_analysis_root(root) / "exports" / "calibration_run_summaries.csv"


def default_observation_export_path(root: str | Path | None = None) -> Path:
    return default_analysis_root(root) / "exports" / "calibration_observations.csv"


def default_plot_output_dir(root: str | Path | None = None) -> Path:
    return default_analysis_root(root) / "plots"


def default_audit_json_path(root: str | Path | None = None) -> Path:
    return default_analysis_root(root) / "reports" / "calibration_memory_audit.json"


def default_audit_md_path(root: str | Path | None = None) -> Path:
    return default_analysis_root(root) / "reports" / "calibration_memory_audit.md"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            yield json.loads(text)


def _clean_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value):
    try:
        if value is None or value == "":
            return None
        return int(round(float(value)))
    except Exception:
        return None


def _float_or_none(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _bool_or_none(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _band_bounds(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None, None
    lo = _float_or_none(value[0])
    hi = _float_or_none(value[1])
    if lo is None or hi is None:
        return None, None
    return (min(lo, hi), max(lo, hi))


def _safe_get(data, *path):
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _lookup_paths(data, *paths):
    for path in paths:
        value = _safe_get(data, *path)
        if value is not None and value != "":
            return value
    return None


def _json_cell(value):
    if value is None or value == "" or value == [] or value == {} or value == ():
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _read_run_summary_paths(root: Path):
    runs_dir = root / "runs"
    if not runs_dir.exists():
        return []
    return sorted(path for path in runs_dir.glob("*/run_summary.json") if path.is_file())


def _ensure_derived_snapshots(root: Path):
    indices_dir = root / "indices"
    required = (
        indices_dir / "pair_memory.json",
        indices_dir / "pair_type_memory.json",
        indices_dir / "reagent_memory.json",
        indices_dir / "head_type_memory.json",
        indices_dir / "recommendation_index.json",
    )
    needs_refresh = any(not path.exists() for path in required)
    try:
        from CalibrationMemoryStore import CalibrationMemoryStore

        store = CalibrationMemoryStore(root_dir=str(root))
        needs_refresh = needs_refresh or store.is_derived_memory_dirty()
        if needs_refresh:
            store.refresh_derived_memory()
    except Exception:
        return


def _phase_count_total(phase_counts):
    total = 0
    if not isinstance(phase_counts, dict):
        return 0
    for value in phase_counts.values():
        try:
            total += int(value)
        except Exception:
            continue
    return total


def _normalize_filter_values(values):
    if not values:
        return None
    normalized = set()
    for value in values:
        if value is None:
            continue
        for part in str(value).split(","):
            cleaned = part.strip()
            if cleaned:
                normalized.add(cleaned)
    return normalized or None


def _write_csv(path: Path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_cell(row.get(column)) for column in columns})
    return path


def _group_label(row):
    reagent = _clean_text(row.get("reagent_id")) or _clean_text(row.get("reagent_display_name")) or "unknown_reagent"
    head_type = _clean_text(row.get("head_type_id")) or "unknown_head_type"
    return f"{reagent} | {head_type}"


def _passes_trend_filter(row, reagent_ids=None, head_type_ids=None):
    reagent_filter = _normalize_filter_values(reagent_ids)
    head_filter = _normalize_filter_values(head_type_ids)
    if reagent_filter and (_clean_text(row.get("reagent_id")) not in reagent_filter):
        return False
    if head_filter and (_clean_text(row.get("head_type_id")) not in head_filter):
        return False
    return True


def _count_nonempty(rows, column):
    total = 0
    for row in rows:
        value = row.get(column)
        if value not in (None, "", [], {}, ()):
            total += 1
    return total


def _read_snapshot_entry_count(path: Path):
    if not path.exists():
        return None
    try:
        payload = _load_json(path)
    except Exception:
        return None
    return _int_or_none(payload.get("entry_count"))


def _readiness_block(*, label, run_count, criteria, sufficient):
    return {
        "label": label,
        "run_count": int(run_count),
        "criteria": criteria,
        "sufficient": bool(sufficient),
    }


def _print_json(payload):
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True))
    sys.stdout.write("\n")


def load_run_summaries(root: str | Path | None = None):
    root_path = resolve_memory_root(root)
    records = []
    errors = []
    for path in _read_run_summary_paths(root_path):
        try:
            summary = _load_json(path)
        except Exception as exc:
            errors.append({"path": str(path), "error": str(exc)})
            continue
        run_id = _clean_text(summary.get("run_id")) or path.parent.name
        summary["run_id"] = run_id
        summary["_summary_path"] = str(path)
        records.append(summary)
    records.sort(
        key=lambda item: (
            _clean_text(_safe_get(item, "run_timing", "started_at_utc")) or "",
            _clean_text(item.get("run_id")) or "",
        )
    )
    return records, errors


def flatten_run_summary(summary):
    context = dict(summary.get("context") or {})
    derived = dict(summary.get("derived_metrics") or {})
    prior = dict(summary.get("prior_candidate") or summary.get("advisory_prior") or {})
    seed = dict(summary.get("prior_seed_values") or {})
    prior_use = dict(summary.get("prior_usefulness_summary") or {})
    ui = dict(summary.get("ui_recommendation") or {})
    run_timing = dict(summary.get("run_timing") or {})
    source_refs = dict(summary.get("source_refs") or {})
    authoritative_refs = dict(summary.get("authoritative_refs") or {})
    phase_counts = dict(summary.get("phase_counts") or {})
    process_results = dict(summary.get("process_results") or {})
    pressure_sweep = dict(derived.get("pressure_sweep") or {})

    single_lo, single_hi = _band_bounds(derived.get("single_droplet_band_psi"))
    traj_lo, traj_hi = _band_bounds(derived.get("trajectory_pressure_band_psi"))
    sweep_lo, sweep_hi = _band_bounds(pressure_sweep.get("valid_pressure_band_psi"))
    seed_lo, seed_hi = _band_bounds(seed.get("seed_single_droplet_band_psi"))

    row = {column: None for column in RUN_SUMMARY_COLUMNS}
    row["run_id"] = _clean_text(summary.get("run_id"))
    row["schema_name"] = _clean_text(summary.get("schema_name"))
    row["schema_version"] = _int_or_none(summary.get("schema_version"))
    row["summary_path"] = _clean_text(summary.get("_summary_path")) or _clean_text(source_refs.get("run_summary_path"))
    row["observations_path"] = _clean_text(source_refs.get("observations_path"))
    row["calibration_json_path"] = _clean_text(authoritative_refs.get("calibration_json_path"))
    row["run_status"] = _clean_text(summary.get("run_status")) or ("completed" if run_timing.get("ended_at_utc") else "in_progress")
    row["run_completed"] = row["run_status"] == "completed"
    row["started_at_utc"] = _clean_text(run_timing.get("started_at_utc"))
    row["ended_at_utc"] = _clean_text(run_timing.get("ended_at_utc"))
    row["last_updated_at_utc"] = _clean_text(summary.get("last_updated_at_utc"))
    row["notes"] = _clean_text(summary.get("notes"))
    row["profile_name"] = _clean_text(context.get("profile_name"))
    row["experiment_dir"] = _clean_text(context.get("experiment_dir"))
    row["calibration_file_path"] = _clean_text(context.get("calibration_file_path"))
    row["stock_id"] = _clean_text(context.get("stock_id"))
    row["stock_display_name"] = _clean_text(context.get("stock_display_name"))
    row["stock_concentration"] = _clean_text(context.get("stock_concentration"))
    row["stock_units"] = _clean_text(context.get("stock_units"))
    row["reagent_id"] = _clean_text(context.get("reagent_id"))
    row["reagent_display_name"] = _clean_text(context.get("reagent_display_name"))
    row["reagent_family"] = _clean_text(context.get("reagent_family"))
    row["glycerol_percent"] = _float_or_none(context.get("glycerol_percent"))
    row["printer_head_id"] = _clean_text(context.get("printer_head_id"))
    row["printer_head_display_name"] = _clean_text(context.get("printer_head_display_name"))
    row["head_type_id"] = _clean_text(context.get("head_type_id"))
    row["head_type_display_name"] = _clean_text(context.get("head_type_display_name"))
    row["nominal_nozzle_diameter_um"] = _float_or_none(context.get("nominal_nozzle_diameter_um"))
    row["measured_nozzle_diameter_um"] = _float_or_none(context.get("measured_nozzle_diameter_um"))
    row["nozzle_diameter_um"] = _float_or_none(context.get("nozzle_diameter_um"))
    row["manufacturer_batch"] = _clean_text(context.get("manufacturer_batch"))
    row["identity_quality_stock_id"] = _clean_text(_safe_get(context, "identity_quality", "stock_id"))
    row["identity_quality_reagent_id"] = _clean_text(_safe_get(context, "identity_quality", "reagent_id"))
    row["identity_quality_printer_head_id"] = _clean_text(_safe_get(context, "identity_quality", "printer_head_id"))
    row["identity_quality_head_type_id"] = _clean_text(_safe_get(context, "identity_quality", "head_type_id"))
    row["phase_count_total"] = _phase_count_total(phase_counts)
    row["phase_counts_json"] = _json_cell(phase_counts)
    row["process_result_keys_json"] = _json_cell(sorted(process_results.keys()))
    row["usable_for_aggregation"] = _bool_or_none(derived.get("usable_for_aggregation"))
    row["qualification_reasons_json"] = _json_cell(derived.get("qualification_reasons"))
    row["eligible_aggregation_levels_json"] = _json_cell(derived.get("eligible_aggregation_levels"))
    row["pulse_width_us"] = _int_or_none(derived.get("pulse_width_us"))
    row["recommended_pressure_psi"] = _float_or_none(derived.get("recommended_pressure_psi"))
    row["recommended_pressure_source"] = _clean_text(derived.get("recommended_pressure_source"))
    row["single_droplet_band_low_psi"] = single_lo
    row["single_droplet_band_high_psi"] = single_hi
    row["single_droplet_band_source"] = _clean_text(derived.get("single_droplet_band_source"))
    row["trajectory_pressure_band_low_psi"] = traj_lo
    row["trajectory_pressure_band_high_psi"] = traj_hi
    row["trajectory_pressure_band_source"] = _clean_text(derived.get("trajectory_pressure_band_source"))
    row["emergence_time_us"] = _int_or_none(derived.get("emergence_time_us"))
    row["emergence_time_source"] = _clean_text(derived.get("emergence_time_source"))
    row["expected_mean_volume_nL"] = _float_or_none(derived.get("expected_mean_volume_nL"))
    row["expected_cv_pct"] = _float_or_none(derived.get("expected_cv_pct"))
    row["volume_source"] = _clean_text(derived.get("volume_source"))
    row["online_stream_flow_rate_nl_per_us"] = _float_or_none(
        derived.get("online_stream_flow_rate_nl_per_us")
    )
    row["online_stream_flow_fit_status"] = _clean_text(
        derived.get("online_stream_flow_fit_status")
    )
    row["online_stream_tail_status"] = _clean_text(
        derived.get("online_stream_tail_status")
    )
    row["online_stream_tail_start_delay_from_emergence_us"] = _int_or_none(
        derived.get("online_stream_tail_start_delay_from_emergence_us")
    )
    row["online_stream_predicted_volume_nl"] = _float_or_none(
        derived.get("online_stream_predicted_volume_nL")
    )
    row["online_stream_print_pressure_psi"] = _float_or_none(
        derived.get("online_stream_print_pressure_psi")
    )
    online_stream_prior = dict(summary.get("online_stream_prior_applied_prior") or {})
    if not online_stream_prior:
        online_stream_prior = dict(summary.get("online_stream_prior_candidate") or {})
    row["online_stream_prior_condition_match"] = _clean_text(
        online_stream_prior.get("condition_match")
    )
    row["online_stream_prior_source"] = _clean_text(
        online_stream_prior.get("source")
    )
    row["online_stream_prior_aggregation_level"] = _clean_text(
        online_stream_prior.get("aggregation_level")
    )
    row["online_stream_prior_candidate_found"] = _bool_or_none(
        summary.get("online_stream_prior_candidate_found")
    )
    row["online_stream_prior_fallback_reason"] = _clean_text(
        summary.get("online_stream_prior_fallback_reason")
    )
    row["pressure_sweep_row_count"] = _int_or_none(pressure_sweep.get("row_count"))
    row["pressure_sweep_valid_row_count"] = _int_or_none(pressure_sweep.get("valid_row_count"))
    row["pressure_sweep_valid_band_low_psi"] = sweep_lo
    row["pressure_sweep_valid_band_high_psi"] = sweep_hi
    row["pressure_sweep_preferred_pressure_psi"] = _float_or_none(pressure_sweep.get("preferred_pressure_psi"))
    row["pressure_sweep_preferred_mean_volume_nL"] = _float_or_none(pressure_sweep.get("preferred_mean_volume_nL"))
    row["pressure_sweep_preferred_cv_pct"] = _float_or_none(pressure_sweep.get("preferred_cv_pct"))
    row["prior_application_mode"] = _clean_text(summary.get("prior_application_mode"))
    row["prior_lookup_performed"] = _bool_or_none(summary.get("prior_lookup_performed"))
    row["prior_candidate_found"] = _bool_or_none(summary.get("prior_candidate_found"))
    row["prior_qualified"] = _bool_or_none(summary.get("prior_qualified"))
    row["prior_applied"] = _bool_or_none(summary.get("prior_applied"))
    row["prior_application_reason"] = _clean_text(summary.get("prior_application_reason"))
    row["prior_rejected_reason"] = _clean_text(summary.get("prior_rejected_reason"))
    row["prior_fallback_triggered"] = _bool_or_none(summary.get("prior_fallback_triggered"))
    row["prior_fallback_reason"] = _clean_text(summary.get("prior_fallback_reason"))
    row["prior_candidate_aggregation_level"] = _clean_text(prior.get("aggregation_level"))
    row["prior_candidate_match_type"] = _clean_text(prior.get("match_type"))
    row["prior_candidate_pulse_match_type"] = _clean_text(prior.get("pulse_match_type"))
    row["prior_candidate_confidence"] = _float_or_none(
        prior.get("recommendation_confidence_adjusted", prior.get("recommendation_confidence"))
    )
    row["prior_candidate_pulse_width_us"] = _int_or_none(prior.get("pulse_width_us"))
    row["prior_candidate_recommended_pressure_psi"] = _float_or_none(prior.get("recommended_pressure_psi"))
    row["prior_candidate_expected_mean_volume_nL"] = _float_or_none(prior.get("expected_mean_volume_nL"))
    row["prior_candidate_expected_cv_pct"] = _float_or_none(prior.get("expected_cv_pct"))
    row["prior_candidate_contributing_runs"] = _int_or_none(prior.get("contributing_runs"))
    row["prior_candidate_source_run_ids_json"] = _json_cell(prior.get("source_run_ids"))
    row["prior_seed_start_pressure_psi"] = _float_or_none(seed.get("start_pressure_psi"))
    row["prior_seed_source"] = _clean_text(seed.get("seed_source"))
    row["prior_seed_single_band_low_psi"] = seed_lo
    row["prior_seed_single_band_high_psi"] = seed_hi
    row["prior_seed_expected_mean_volume_nL"] = _float_or_none(seed.get("seed_expected_mean_volume_nL"))
    row["prior_seed_expected_cv_pct"] = _float_or_none(seed.get("seed_expected_cv_pct"))
    row["prior_seed_pulse_width_us"] = _int_or_none(seed.get("seed_pulse_width_us"))
    row["prior_usefulness_signal"] = _clean_text(prior_use.get("usefulness_signal"))
    row["prior_steps_until_first_single"] = _int_or_none(prior_use.get("steps_until_first_single"))
    row["prior_first_single_pressure_psi"] = _float_or_none(prior_use.get("first_single_pressure_psi"))
    row["prior_first_single_seed_error_psi"] = _float_or_none(prior_use.get("first_single_seed_error_psi"))
    row["prior_seed_inside_actual_single_band"] = _bool_or_none(prior_use.get("seed_inside_actual_single_band"))
    row["prior_actual_vs_prior_pressure_error_psi"] = _float_or_none(prior_use.get("actual_vs_prior_pressure_error_psi"))
    row["prior_actual_vs_prior_volume_error_nL"] = _float_or_none(prior_use.get("actual_vs_prior_volume_error_nL"))
    row["ui_recommendation_shown"] = _bool_or_none(ui.get("shown"))
    row["ui_recommendation_shown_count"] = _int_or_none(ui.get("shown_count"))
    row["ui_recommendation_applied"] = _bool_or_none(ui.get("applied"))
    row["ui_recommendation_apply_count"] = _int_or_none(ui.get("apply_count"))
    row["ui_recommendation_ignored"] = _bool_or_none(ui.get("ignored"))
    row["ui_recommendation_ignore_count"] = _int_or_none(ui.get("ignore_count"))
    row["ui_recommendation_last_action"] = _clean_text(ui.get("last_action"))
    row["ui_recommendation_aggregation_level"] = _clean_text(ui.get("aggregation_level"))
    row["ui_recommendation_confidence"] = _float_or_none(ui.get("confidence"))
    row["ui_recommendation_manual_apply_allowed"] = _bool_or_none(ui.get("manual_apply_allowed"))
    row["ui_recommendation_manual_apply_reason"] = _clean_text(ui.get("manual_apply_reason"))
    row["ui_recommendation_target_pulse_width_us"] = _int_or_none(ui.get("target_pulse_width_us"))
    row["ui_recommendation_target_volume_nl"] = _float_or_none(ui.get("target_volume_nl"))
    row["context_json"] = _json_cell(context)
    row["derived_metrics_json"] = _json_cell(derived)
    row["prior_candidate_json"] = _json_cell(prior)
    row["ui_recommendation_json"] = _json_cell(ui)
    return row


def build_run_summary_export_rows(root: str | Path | None = None):
    summaries, errors = load_run_summaries(root)
    rows = [flatten_run_summary(summary) for summary in summaries]
    rows.sort(
        key=lambda item: (
            _clean_text(item.get("started_at_utc")) or "",
            _clean_text(item.get("run_id")) or "",
        )
    )
    return rows, errors


def export_run_summaries_csv(root: str | Path | None = None, out_path: str | Path | None = None):
    rows, errors = build_run_summary_export_rows(root)
    output_path = Path(out_path or default_summary_export_path(root)).resolve()
    _write_csv(output_path, RUN_SUMMARY_COLUMNS, rows)
    return {
        "root_dir": str(resolve_memory_root(root)),
        "output_path": str(output_path),
        "row_count": len(rows),
        "columns": list(RUN_SUMMARY_COLUMNS),
        "error_count": len(errors),
        "errors": errors,
    }


def _build_summary_lookup(root: str | Path | None = None):
    summaries, errors = load_run_summaries(root)
    lookup = {}
    for summary in summaries:
        run_id = _clean_text(summary.get("run_id"))
        if run_id:
            lookup[run_id] = summary
    return lookup, errors


def _extract_observation_metrics(payload):
    payload = dict(payload or {})
    return {
        "payload_kind": _clean_text(_lookup_paths(payload, ("kind",), ("probe", "phase_name"))),
        "payload_action": _clean_text(_lookup_paths(payload, ("action",))),
        "payload_reason": _clean_text(
            _lookup_paths(payload, ("reason",), ("fallback_reason",), ("extra", "reason"), ("decision_reason",))
        ),
        "payload_verdict": _clean_text(_lookup_paths(payload, ("verdict",), ("probe", "verdict"))),
        "payload_confidence": _float_or_none(
            _lookup_paths(
                payload,
                ("confidence",),
                ("probe", "confidence"),
                ("prior", "recommendation_confidence_adjusted"),
                ("prior", "recommendation_confidence"),
            )
        ),
        "payload_pressure_psi": _float_or_none(
            _lookup_paths(
                payload,
                ("pressure_psi",),
                ("pressure",),
                ("probe", "pressure_psi"),
                ("seed_values", "start_pressure_psi"),
                ("extra", "seeded_start_pressure_psi"),
                ("prior", "recommended_pressure_psi"),
            )
        ),
        "payload_print_pulse_width_us": _int_or_none(
            _lookup_paths(
                payload,
                ("print_pulse_width_us",),
                ("pulse_width_us",),
                ("seed_values", "seed_pulse_width_us"),
                ("extra", "seeded_pulse_width_us"),
                ("prior", "pulse_width_us"),
            )
        ),
        "payload_delay_us": _int_or_none(
            _lookup_paths(
                payload,
                ("delay_us",),
                ("flash_delay_us",),
                ("emergence_time_us",),
                ("prior", "emergence_time_us"),
            )
        ),
        "payload_mean_volume_nL": _float_or_none(
            _lookup_paths(
                payload,
                ("mean_volume_nL",),
                ("mean_volume",),
                ("volume_nL",),
                ("prior", "expected_mean_volume_nL"),
            )
        ),
        "payload_cv_pct": _float_or_none(
            _lookup_paths(
                payload,
                ("cv_pct",),
                ("cv_volume_percent",),
                ("prior", "expected_cv_pct"),
            )
        ),
        "payload_valid": _bool_or_none(_lookup_paths(payload, ("valid",), ("probe", "valid"))),
        "payload_aggregation_level": _clean_text(_lookup_paths(payload, ("aggregation_level",), ("prior", "aggregation_level"))),
        "payload_match_type": _clean_text(_lookup_paths(payload, ("match_type",), ("prior", "match_type"))),
        "payload_pulse_match_type": _clean_text(
            _lookup_paths(payload, ("pulse_match_type",), ("prior", "pulse_match_type"))
        ),
        "payload_seed_start_pressure_psi": _float_or_none(
            _lookup_paths(payload, ("seed_values", "start_pressure_psi"), ("extra", "seeded_start_pressure_psi"))
        ),
    }


def flatten_observation(record, *, summary=None, observation_path=None, observation_index=None):
    summary = dict(summary or {})
    context = dict(record.get("context") or {})
    summary_context = dict(summary.get("context") or {})
    if summary_context:
        merged_context = dict(summary_context)
        merged_context.update(context)
        context = merged_context

    run_timing = dict(summary.get("run_timing") or {})
    settings = dict(record.get("settings") or {})
    machine = dict(record.get("machine") or {})
    machine_pos = machine.get("position") or settings.get("current_position") or {}
    payload = dict(record.get("payload") or {})
    artifact_refs = {}
    artifact_refs.update(dict(summary.get("artifact_refs") or {}))
    artifact_refs.update(dict(record.get("artifact_refs") or {}))
    metrics = _extract_observation_metrics(payload)

    row = {column: None for column in OBSERVATION_COLUMNS}
    row["run_id"] = _clean_text(record.get("run_id")) or _clean_text(summary.get("run_id"))
    row["observation_id"] = _clean_text(record.get("observation_id"))
    row["schema_name"] = _clean_text(record.get("schema_name"))
    row["schema_version"] = _int_or_none(record.get("schema_version"))
    row["summary_path"] = _clean_text(summary.get("_summary_path")) or _clean_text(_safe_get(summary, "source_refs", "run_summary_path"))
    row["observation_path"] = _clean_text(observation_path)
    row["observation_index"] = _int_or_none(observation_index)
    row["ts_utc"] = _clean_text(record.get("ts_utc"))
    row["phase"] = _clean_text(record.get("phase"))
    row["observation_type"] = _clean_text(record.get("observation_type"))
    row["run_status"] = _clean_text(summary.get("run_status")) or ("completed" if run_timing.get("ended_at_utc") else None)
    row["started_at_utc"] = _clean_text(run_timing.get("started_at_utc"))
    row["ended_at_utc"] = _clean_text(run_timing.get("ended_at_utc"))
    row["stock_id"] = _clean_text(context.get("stock_id"))
    row["stock_display_name"] = _clean_text(context.get("stock_display_name"))
    row["reagent_id"] = _clean_text(context.get("reagent_id"))
    row["reagent_display_name"] = _clean_text(context.get("reagent_display_name"))
    row["reagent_family"] = _clean_text(context.get("reagent_family"))
    row["printer_head_id"] = _clean_text(context.get("printer_head_id"))
    row["printer_head_display_name"] = _clean_text(context.get("printer_head_display_name"))
    row["head_type_id"] = _clean_text(context.get("head_type_id"))
    row["nominal_nozzle_diameter_um"] = _float_or_none(context.get("nominal_nozzle_diameter_um"))
    row["identity_quality_reagent_id"] = _clean_text(_safe_get(context, "identity_quality", "reagent_id"))
    row["identity_quality_printer_head_id"] = _clean_text(_safe_get(context, "identity_quality", "printer_head_id"))
    row["identity_quality_head_type_id"] = _clean_text(_safe_get(context, "identity_quality", "head_type_id"))
    row["settings_print_width_us"] = _int_or_none(settings.get("print_width"))
    row["settings_print_pressure_psi"] = _float_or_none(settings.get("print_pressure"))
    row["settings_refuel_pressure_psi"] = _float_or_none(settings.get("refuel_pressure"))
    row["settings_flash_delay_us"] = _int_or_none(settings.get("flash_delay"))
    row["settings_flash_duration_us"] = _int_or_none(settings.get("flash_duration"))
    row["settings_num_droplets"] = _int_or_none(settings.get("num_droplets"))
    row["settings_exposure_time_us"] = _int_or_none(settings.get("exposure_time"))
    row["machine_pos_x"] = _float_or_none((machine_pos or {}).get("X"))
    row["machine_pos_y"] = _float_or_none((machine_pos or {}).get("Y"))
    row["machine_pos_z"] = _float_or_none((machine_pos or {}).get("Z"))
    for key, value in metrics.items():
        row[key] = value
    row["artifact_camera_capture_root"] = _clean_text(artifact_refs.get("camera_capture_root"))
    row["artifact_camera_active_save_dir"] = _clean_text(artifact_refs.get("camera_active_save_dir"))
    row["artifact_calibration_json_path"] = _clean_text(artifact_refs.get("calibration_json_path"))
    row["artifact_refs_json"] = _json_cell(artifact_refs)
    row["settings_json"] = _json_cell(settings)
    row["payload_json"] = _json_cell(payload)
    row["context_json"] = _json_cell(context)
    return row


def build_observation_export_rows(
    root: str | Path | None = None,
    *,
    run_ids=None,
    observation_types=None,
    phases=None,
    completed_only: bool = False,
):
    root_path = resolve_memory_root(root)
    summary_lookup, errors = _build_summary_lookup(root_path)
    run_filter = _normalize_filter_values(run_ids)
    type_filter = _normalize_filter_values(observation_types)
    phase_filter = _normalize_filter_values(phases)

    rows = []
    runs_dir = root_path / "runs"
    if not runs_dir.exists():
        return rows, errors

    for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        run_id = run_dir.name
        if run_filter and run_id not in run_filter:
            continue

        summary = summary_lookup.get(run_id, {})
        if completed_only:
            run_status = _clean_text(summary.get("run_status")) or (
                "completed" if _safe_get(summary, "run_timing", "ended_at_utc") else "in_progress"
            )
            if run_status != "completed":
                continue

        observation_path = run_dir / "observations.jsonl"
        if not observation_path.exists():
            continue

        try:
            records = list(_iter_jsonl(observation_path))
        except Exception as exc:
            errors.append({"path": str(observation_path), "error": str(exc)})
            continue

        for index, record in enumerate(records, start=1):
            obs_type = _clean_text(record.get("observation_type"))
            phase = _clean_text(record.get("phase"))
            if type_filter and obs_type not in type_filter:
                continue
            if phase_filter and phase not in phase_filter:
                continue
            rows.append(
                flatten_observation(
                    record,
                    summary=summary,
                    observation_path=str(observation_path),
                    observation_index=index,
                )
            )

    rows.sort(
        key=lambda item: (
            _clean_text(item.get("run_id")) or "",
            _clean_text(item.get("ts_utc")) or "",
            _int_or_none(item.get("observation_index")) or 0,
        )
    )
    return rows, errors


def export_observations_csv(
    root: str | Path | None = None,
    out_path: str | Path | None = None,
    *,
    run_ids=None,
    observation_types=None,
    phases=None,
    completed_only: bool = False,
):
    rows, errors = build_observation_export_rows(
        root,
        run_ids=run_ids,
        observation_types=observation_types,
        phases=phases,
        completed_only=completed_only,
    )
    output_path = Path(out_path or default_observation_export_path(root)).resolve()
    _write_csv(output_path, OBSERVATION_COLUMNS, rows)
    return {
        "root_dir": str(resolve_memory_root(root)),
        "output_path": str(output_path),
        "row_count": len(rows),
        "columns": list(OBSERVATION_COLUMNS),
        "error_count": len(errors),
        "errors": errors,
    }


def build_trend_tables(summary_rows, *, reagent_ids=None, head_type_ids=None):
    volume_rows = []
    cv_rows = []
    emergence_rows = []
    for row in summary_rows:
        if row.get("run_status") != "completed":
            continue
        if not _passes_trend_filter(row, reagent_ids=reagent_ids, head_type_ids=head_type_ids):
            continue
        group_label = _group_label(row)
        volume_row = {
            "run_id": row.get("run_id"),
            "reagent_id": row.get("reagent_id"),
            "reagent_display_name": row.get("reagent_display_name"),
            "head_type_id": row.get("head_type_id"),
            "printer_head_id": row.get("printer_head_id"),
            "nominal_nozzle_diameter_um": row.get("nominal_nozzle_diameter_um"),
            "pulse_width_us": row.get("pulse_width_us"),
            "recommended_pressure_psi": row.get("recommended_pressure_psi"),
            "expected_mean_volume_nL": row.get("expected_mean_volume_nL"),
            "expected_cv_pct": row.get("expected_cv_pct"),
            "group_label": group_label,
        }
        if volume_row["recommended_pressure_psi"] is not None and volume_row["expected_mean_volume_nL"] is not None:
            volume_rows.append(volume_row)

        cv_row = {
            "run_id": row.get("run_id"),
            "reagent_id": row.get("reagent_id"),
            "reagent_display_name": row.get("reagent_display_name"),
            "head_type_id": row.get("head_type_id"),
            "printer_head_id": row.get("printer_head_id"),
            "nominal_nozzle_diameter_um": row.get("nominal_nozzle_diameter_um"),
            "pulse_width_us": row.get("pulse_width_us"),
            "recommended_pressure_psi": row.get("recommended_pressure_psi"),
            "expected_cv_pct": row.get("expected_cv_pct"),
            "expected_mean_volume_nL": row.get("expected_mean_volume_nL"),
            "group_label": group_label,
        }
        if cv_row["recommended_pressure_psi"] is not None and cv_row["expected_cv_pct"] is not None:
            cv_rows.append(cv_row)

        emergence_row = {
            "run_id": row.get("run_id"),
            "reagent_id": row.get("reagent_id"),
            "reagent_display_name": row.get("reagent_display_name"),
            "head_type_id": row.get("head_type_id"),
            "printer_head_id": row.get("printer_head_id"),
            "nominal_nozzle_diameter_um": row.get("nominal_nozzle_diameter_um"),
            "pulse_width_us": row.get("pulse_width_us"),
            "recommended_pressure_psi": row.get("recommended_pressure_psi"),
            "emergence_time_us": row.get("emergence_time_us"),
            "expected_mean_volume_nL": row.get("expected_mean_volume_nL"),
            "group_label": group_label,
        }
        if emergence_row["pulse_width_us"] is not None and emergence_row["emergence_time_us"] is not None:
            emergence_rows.append(emergence_row)

    def _sort_key(item):
        return (
            _clean_text(item.get("group_label")) or "",
            _int_or_none(item.get("pulse_width_us")) or 0,
            _float_or_none(item.get("recommended_pressure_psi")) or 0.0,
            _clean_text(item.get("run_id")) or "",
        )

    volume_rows.sort(key=_sort_key)
    cv_rows.sort(key=_sort_key)
    emergence_rows.sort(key=_sort_key)
    return {
        "volume_vs_pressure": volume_rows,
        "cv_vs_pressure": cv_rows,
        "emergence_vs_pulse_width": emergence_rows,
    }


def write_trend_tables(
    root: str | Path | None = None,
    *,
    out_dir: str | Path | None = None,
    reagent_ids=None,
    head_type_ids=None,
):
    summary_rows, errors = build_run_summary_export_rows(root)
    tables = build_trend_tables(summary_rows, reagent_ids=reagent_ids, head_type_ids=head_type_ids)
    output_dir = Path(out_dir or default_plot_output_dir(root)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    table_specs = (
        ("volume_vs_pressure", PLOT_VOLUME_COLUMNS, output_dir / "volume_vs_pressure_points.csv"),
        ("cv_vs_pressure", PLOT_CV_COLUMNS, output_dir / "cv_vs_pressure_points.csv"),
        ("emergence_vs_pulse_width", PLOT_EMERGENCE_COLUMNS, output_dir / "emergence_vs_pulse_width_points.csv"),
    )
    outputs = {}
    for table_name, columns, path in table_specs:
        _write_csv(path, columns, tables[table_name])
        outputs[table_name] = str(path)

    return {
        "root_dir": str(resolve_memory_root(root)),
        "output_dir": str(output_dir),
        "table_paths": outputs,
        "table_row_counts": {name: len(tables[name]) for name in tables},
        "error_count": len(errors),
        "errors": errors,
        "tables": tables,
    }


def plot_trend_tables(
    root: str | Path | None = None,
    *,
    out_dir: str | Path | None = None,
    reagent_ids=None,
    head_type_ids=None,
):
    table_result = write_trend_tables(
        root,
        out_dir=out_dir,
        reagent_ids=reagent_ids,
        head_type_ids=head_type_ids,
    )
    output_dir = Path(table_result["output_dir"])
    manifest = {
        "root_dir": table_result["root_dir"],
        "output_dir": str(output_dir),
        "table_paths": dict(table_result["table_paths"]),
        "table_row_counts": dict(table_result["table_row_counts"]),
        "plot_paths": {},
        "plots_generated": False,
        "plots_skipped_reason": None,
        "error_count": table_result["error_count"],
        "errors": list(table_result["errors"]),
    }

    try:
        import matplotlib.pyplot as plt
    except Exception as exc:
        manifest["plots_skipped_reason"] = f"matplotlib_unavailable: {exc}"
        return manifest

    plot_specs = (
        (
            "volume_vs_pressure",
            "recommended_pressure_psi",
            "expected_mean_volume_nL",
            "Recommended Pressure (psi)",
            "Expected Mean Volume (nL)",
            "Droplet Volume vs Pressure",
            output_dir / "volume_vs_pressure.png",
        ),
        (
            "cv_vs_pressure",
            "recommended_pressure_psi",
            "expected_cv_pct",
            "Recommended Pressure (psi)",
            "Expected CV (%)",
            "CV vs Pressure",
            output_dir / "cv_vs_pressure.png",
        ),
        (
            "emergence_vs_pulse_width",
            "pulse_width_us",
            "emergence_time_us",
            "Pulse Width (us)",
            "Emergence Time (us)",
            "Emergence Time vs Pulse Width",
            output_dir / "emergence_vs_pulse_width.png",
        ),
    )

    any_plot = False
    for table_name, x_key, y_key, xlabel, ylabel, title, plot_path in plot_specs:
        rows = list(table_result["tables"].get(table_name) or [])
        if not rows:
            continue

        grouped = {}
        for row in rows:
            grouped.setdefault(row["group_label"], []).append(row)

        fig, ax = plt.subplots(figsize=(9, 5))
        for group_label in sorted(grouped.keys()):
            group_rows = sorted(
                grouped[group_label],
                key=lambda item: (
                    _int_or_none(item.get("pulse_width_us")) or 0,
                    _float_or_none(item.get("recommended_pressure_psi")) or 0.0,
                    _clean_text(item.get("run_id")) or "",
                ),
            )
            xs = [_float_or_none(item.get(x_key)) for item in group_rows]
            ys = [_float_or_none(item.get(y_key)) for item in group_rows]
            points = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
            if not points:
                continue
            xvals = [point[0] for point in points]
            yvals = [point[1] for point in points]
            ax.plot(xvals, yvals, marker="o", linewidth=1.2, label=group_label)

        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(True, alpha=0.25)
        handles, labels = ax.get_legend_handles_labels()
        if labels:
            ax.legend(fontsize=8)
        fig.tight_layout()
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(plot_path, dpi=150)
        plt.close(fig)
        manifest["plot_paths"][table_name] = str(plot_path)
        any_plot = True

    manifest["plots_generated"] = any_plot
    if not any_plot and manifest["plots_skipped_reason"] is None:
        manifest["plots_skipped_reason"] = "no_rows_for_requested_plots"

    manifest_path = output_dir / "trend_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def build_dataset_audit(root: str | Path | None = None):
    root_path = resolve_memory_root(root)
    _ensure_derived_snapshots(root_path)
    summary_rows, summary_errors = build_run_summary_export_rows(root_path)
    observation_rows, observation_errors = build_observation_export_rows(root_path)

    coverage = {}
    for column in RUN_SUMMARY_COLUMNS:
        nonempty = _count_nonempty(summary_rows, column)
        coverage[column] = {
            "nonempty_count": int(nonempty),
            "total_runs": int(len(summary_rows)),
            "coverage_ratio": round((float(nonempty) / float(len(summary_rows))) if summary_rows else 0.0, 4),
        }

    observation_type_counts = Counter()
    observation_phase_counts = Counter()
    for row in observation_rows:
        if row.get("observation_type"):
            observation_type_counts[str(row["observation_type"])] += 1
        if row.get("phase"):
            observation_phase_counts[str(row["phase"])] += 1

    exact_pair_runs = [
        row for row in summary_rows
        if row.get("run_status") == "completed"
        and row.get("usable_for_aggregation") is True
        and row.get("identity_quality_reagent_id") == "explicit"
        and row.get("identity_quality_printer_head_id") == "explicit"
    ]
    unique_exact_pairs = {
        (row.get("reagent_id"), row.get("printer_head_id"))
        for row in exact_pair_runs
        if row.get("reagent_id") and row.get("printer_head_id")
    }

    reagent_head_type_runs = [
        row for row in summary_rows
        if row.get("run_status") == "completed"
        and row.get("usable_for_aggregation") is True
        and row.get("reagent_id")
        and row.get("head_type_id")
    ]
    unique_reagent_head_types = {
        (row.get("reagent_id"), row.get("head_type_id"))
        for row in reagent_head_type_runs
        if row.get("reagent_id") and row.get("head_type_id")
    }

    emergence_runs = [
        row for row in summary_rows
        if row.get("run_status") == "completed" and row.get("emergence_time_us") is not None
    ]
    cv_runs = [
        row for row in summary_rows
        if row.get("run_status") == "completed" and row.get("expected_cv_pct") is not None
    ]

    indices_dir = root_path / "indices"
    derived_snapshot_counts = {
        "pair_memory": _read_snapshot_entry_count(indices_dir / "pair_memory.json"),
        "pair_type_memory": _read_snapshot_entry_count(indices_dir / "pair_type_memory.json"),
        "reagent_memory": _read_snapshot_entry_count(indices_dir / "reagent_memory.json"),
        "head_type_memory": _read_snapshot_entry_count(indices_dir / "head_type_memory.json"),
        "recommendation_index": _read_snapshot_entry_count(indices_dir / "recommendation_index.json"),
    }

    return {
        "schema_version": 1,
        "root_dir": str(root_path),
        "source_of_truth": {
            "run_summaries": str(root_path / "runs"),
            "run_catalog": str(root_path / "indices" / "run_catalog.jsonl"),
            "derived_indices_dir": str(indices_dir),
        },
        "counts": {
            "run_summaries": int(len(summary_rows)),
            "observations": int(len(observation_rows)),
            "summary_load_errors": int(len(summary_errors)),
            "observation_load_errors": int(len(observation_errors)),
        },
        "derived_snapshot_counts": derived_snapshot_counts,
        "run_summary_field_coverage": coverage,
        "observation_type_counts": dict(sorted(observation_type_counts.items())),
        "observation_phase_counts": dict(sorted(observation_phase_counts.items())),
        "key_metric_availability": {
            "pulse_width_us": coverage["pulse_width_us"],
            "recommended_pressure_psi": coverage["recommended_pressure_psi"],
            "emergence_time_us": coverage["emergence_time_us"],
            "expected_mean_volume_nL": coverage["expected_mean_volume_nL"],
            "expected_cv_pct": coverage["expected_cv_pct"],
            "prior_candidate_confidence": coverage["prior_candidate_confidence"],
            "ui_recommendation_confidence": coverage["ui_recommendation_confidence"],
        },
        "dataset_readiness": {
            "exact_pair_analysis": {
                **_readiness_block(
                    label="Exact-pair analysis",
                    run_count=len(exact_pair_runs),
                    criteria=">= 3 completed usable runs with explicit reagent_id and explicit printer_head_id",
                    sufficient=(len(exact_pair_runs) >= 3 and len(unique_exact_pairs) >= 1),
                ),
                "unique_pair_count": int(len(unique_exact_pairs)),
            },
            "reagent_head_type_analysis": {
                **_readiness_block(
                    label="Reagent + head-type analysis",
                    run_count=len(reagent_head_type_runs),
                    criteria=">= 3 completed usable runs with reagent_id and head_type_id",
                    sufficient=(len(reagent_head_type_runs) >= 3 and len(unique_reagent_head_types) >= 1),
                ),
                "unique_reagent_head_type_count": int(len(unique_reagent_head_types)),
            },
            "emergence_time_analysis": _readiness_block(
                label="Emergence-time analysis",
                run_count=len(emergence_runs),
                criteria=">= 3 completed runs with emergence_time_us populated",
                sufficient=(len(emergence_runs) >= 3),
            ),
            "cv_trend_analysis": _readiness_block(
                label="CV trend analysis",
                run_count=len(cv_runs),
                criteria=">= 3 completed runs with expected_cv_pct populated",
                sufficient=(len(cv_runs) >= 3),
            ),
        },
        "errors": {
            "run_summaries": summary_errors,
            "observations": observation_errors,
        },
    }


def render_dataset_audit_markdown(audit):
    counts = audit["counts"]
    readiness = audit["dataset_readiness"]
    lines = [
        "# Calibration Memory Dataset Audit",
        "",
        f"- Root: `{audit['root_dir']}`",
        f"- Run summaries: {counts['run_summaries']}",
        f"- Observations: {counts['observations']}",
        f"- Run-summary load errors: {counts['summary_load_errors']}",
        f"- Observation load errors: {counts['observation_load_errors']}",
        "",
        "## Derived Snapshot Counts",
        "",
    ]
    for key, value in sorted((audit.get("derived_snapshot_counts") or {}).items()):
        lines.append(f"- {key}: {value if value is not None else 'missing'}")

    lines.extend(["", "## Dataset Readiness", ""])
    for key in sorted(readiness.keys()):
        block = readiness[key]
        verdict = "yes" if block.get("sufficient") else "no"
        lines.append(f"- {block['label']}: {verdict} ({block['run_count']} runs)")
        lines.append(f"  - criteria: {block['criteria']}")
        if "unique_pair_count" in block:
            lines.append(f"  - unique pairs: {block['unique_pair_count']}")
        if "unique_reagent_head_type_count" in block:
            lines.append(f"  - unique reagent/head-type combinations: {block['unique_reagent_head_type_count']}")

    lines.extend(["", "## Key Metric Coverage", ""])
    for key, block in sorted((audit.get("key_metric_availability") or {}).items()):
        lines.append(
            f"- {key}: {block['nonempty_count']}/{block['total_runs']} "
            f"({block['coverage_ratio']:.0%})"
        )

    lines.extend(["", "## Observation Types", ""])
    for key, value in sorted((audit.get("observation_type_counts") or {}).items()):
        lines.append(f"- {key}: {value}")

    return "\n".join(lines).rstrip() + "\n"


def write_dataset_audit(
    root: str | Path | None = None,
    *,
    json_path: str | Path | None = None,
    md_path: str | Path | None = None,
):
    audit = build_dataset_audit(root)
    json_out = Path(json_path or default_audit_json_path(root)).resolve()
    md_out = Path(md_path or default_audit_md_path(root)).resolve()
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    md_out.write_text(render_dataset_audit_markdown(audit), encoding="utf-8")
    return {
        "root_dir": audit["root_dir"],
        "json_path": str(json_out),
        "md_path": str(md_out),
        "run_count": audit["counts"]["run_summaries"],
        "observation_count": audit["counts"]["observations"],
    }


def read_summary_csv(path: str | Path):
    rows = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            rows.append(dict(raw))
    return rows
