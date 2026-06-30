#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPERIMENTS_ROOT = Path("FreeRTOS-interface") / "Experiments"
DEFAULT_OUTPUT = (
    Path("tools")
    / "stream_analysis"
    / "manifests"
    / "online_stream_tail_gravimetric_validation_v1.json"
)
SCHEMA_VERSION = "online_stream_tail_validation_manifest_v1"
MANIFEST_ID = "online_stream_tail_gravimetric_validation_v1"
DENSITY_ASSUMPTION_G_PER_ML = 1.0
DENSITY_MEASUREMENTS_CSV = Path("tools") / "stream_analysis" / "manifests" / "stream_density_measurements.csv"
CODE_DEFAULT_UM_PER_PIXEL = 1.5696
ASSIGNED_UM_PER_PIXEL = 1.5824

EXPERIMENT_DENSITY_ASSIGNMENTS = {
    "EF-Ts_rep1-20260424_223016": "EFTs",
    "Ribo_rep1-20260423_204338": "Ribo",
    "Stream_100um-20260407_111519": "Water",
    "Stream_BSA_large1-20260411_113020": "BSA_50per",
    "Stream_BSA_rep1-20260410_113246": "BSA_50per",
    "Stream_characterization-20260327_225650": "Water",
    "Stream_online_rep11-20260409_093958": "Water",
    "Stream_online_rep13-20260409_120113": "Water",
    "Stream_online_rep14-20260409_134101": "Water",
    "Stream_online_rep5-20260408_103201": "Water",
    "Stream_online_rep6-20260408_105437": "Water",
    "Stream_online_rep7-20260408_171441": "Water",
    "Stream_seg_EFTs_rep1-20260428_195903": "EFTs",
    "Stream_seg_EFTu_rep1-20260428_191455": "EFTu",
    "Stream_seg_Pmix_rep1-20260429_130356": "Pmix",
    "Stream_seg_SolB_rep1-20260429_140537": "SolB",
    "Stream_tail_rep1-20260415_113940": "Water",
    "Stream_water_large1-20260412_141203": "Water",
    "Untitled-20260416_150721": "Water",
    "Untitled-20260427_182241": "Water",
    "stream_120um_rep2-20260612_113906": "Water",
}

ASSIGNMENT_SOURCE = "user_confirmed_manifest_review"
OPTICS_ASSIGNMENT_BASIS = "historical_machine"


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _parse_int(value: Any) -> int | None:
    parsed = _parse_float(value)
    if parsed is None:
        return None
    return int(parsed)


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rel(path: Path, repo_root: Path) -> str:
    return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")


def _has_tail_summaries(tail_fit: dict[str, Any]) -> bool:
    return bool(tail_fit.get("scout_delay_summaries") and tail_fit.get("backtrack_delay_summaries"))


def _has_window_candidates(tail_fit: dict[str, Any]) -> bool:
    summaries = list(tail_fit.get("scout_delay_summaries") or [])
    summaries.extend(tail_fit.get("backtrack_delay_summaries") or [])
    return any(summary.get("tail_width_window_candidates") for summary in summaries)


def _flow_fit_values(flow_fit: dict[str, Any]) -> tuple[float | None, float | None]:
    fit = flow_fit.get("fit")
    if not isinstance(fit, dict):
        return None, None
    return _parse_float(fit.get("flow_rate_nl_per_us")), _parse_float(fit.get("flow_intercept_nl"))


def _load_density_measurements(repo_root: Path) -> dict[str, float]:
    measurements: dict[str, float] = {}
    density_path = repo_root / DENSITY_MEASUREMENTS_CSV
    with density_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            solution_id = str(row.get("Solution") or "").strip()
            density_g_per_ml = _parse_float(row.get("Density"))
            if not solution_id or density_g_per_ml is None:
                continue
            measurements[solution_id] = float(density_g_per_ml)
    return measurements


def _density_assignment(experiment_id: str, density_measurements: dict[str, float]) -> dict[str, Any]:
    solution_id = EXPERIMENT_DENSITY_ASSIGNMENTS.get(str(experiment_id))
    density_g_per_ml = density_measurements.get(str(solution_id)) if solution_id else None
    if solution_id and density_g_per_ml is None:
        raise ValueError(f"Missing density measurement for solution_id={solution_id!r}")
    return {
        "solution_id": solution_id,
        "density_g_per_ml": density_g_per_ml,
        "assignment_basis": "experiment_id" if solution_id else None,
        "assignment_source": ASSIGNMENT_SOURCE if solution_id else None,
        "assignment_confidence": "confirmed" if solution_id else "unassigned",
    }


def _optics_assignment() -> dict[str, Any]:
    return {
        "um_per_pixel": ASSIGNED_UM_PER_PIXEL,
        "assignment_basis": OPTICS_ASSIGNMENT_BASIS,
        "assignment_source": ASSIGNMENT_SOURCE,
        "assignment_confidence": "confirmed",
        "stored_in_run_artifacts": False,
    }


def _gravimetric_volume_nl(mass_per_print_mg: float | None, density_g_per_ml: float | None) -> float | None:
    if mass_per_print_mg is None or density_g_per_ml in (None, 0.0):
        return None
    return float(mass_per_print_mg) * 1000.0 / float(density_g_per_ml)


def _tail_result_values(tail_fit: dict[str, Any]) -> dict[str, Any]:
    result = tail_fit.get("result") if isinstance(tail_fit.get("result"), dict) else {}
    tail_phase = result.get("tail_phase") if isinstance(result.get("tail_phase"), dict) else {}
    segmented = tail_phase.get("segmented_tail") if isinstance(tail_phase.get("segmented_tail"), dict) else {}
    current_tail_start = _parse_float(result.get("predicted_stream_duration_us"))
    if current_tail_start is None:
        current_tail_start = _parse_float(tail_phase.get("tail_start_delay_from_emergence_us"))
    current_volume = _parse_float(result.get("predicted_volume_nl"))
    return {
        "tail_start_from_emergence_us": _round(current_tail_start, 3),
        "predicted_volume_nl": _round(current_volume, 6),
        "warnings": list(result.get("warnings") or tail_fit.get("warnings") or []),
        "has_segmented_result": bool(segmented),
        "has_segmented_candidate_traces": bool(segmented.get("segmented_tail_candidate_window_traces")),
        "segmented": {
            "tail_start_from_emergence_us": _round(
                _parse_float(segmented.get("tail_start_delay_from_emergence_us")),
                3,
            ),
            "predicted_volume_nl": _round(_parse_float(segmented.get("predicted_volume_nl")), 6),
            "window_selection_reason": segmented.get("segmented_tail_window_selection_reason"),
            "source_trace_kind": segmented.get("segmented_tail_source_trace_kind"),
            "source_window_mode": segmented.get("segmented_tail_source_window_mode"),
            "source_window_step_index": _parse_int(segmented.get("segmented_tail_source_window_step_index")),
            "source_baseline_width_px": _round(
                _parse_float(segmented.get("segmented_tail_source_baseline_width_px")),
                3,
            ),
            "root_window_override_applied": bool(segmented.get("segmented_tail_root_window_override_applied")),
            "root_window_override_reason": segmented.get("segmented_tail_root_window_override_reason"),
            "tail_start_source": segmented.get("tail_start_source"),
            "fit_status": segmented.get("fit_status") or segmented.get("status"),
        },
    }


def _condition(row: dict[str, str], tail_fit: dict[str, Any]) -> dict[str, Any]:
    condition = tail_fit.get("condition") if isinstance(tail_fit.get("condition"), dict) else {}
    return {
        "print_pulse_width_us": _parse_int(condition.get("print_pulse_width_us")) or _parse_int(row.get("Print PW")),
        "print_pressure_psi": _round(
            _parse_float(condition.get("print_pressure_psi")) or _parse_float(row.get("Print Pressure")),
            4,
        ),
        "refuel_pulse_width_us": _parse_int(row.get("Refuel PW")),
        "refuel_pressure_psi": _round(_parse_float(row.get("Refuel Pressure")), 4),
        "stock_solution": condition.get("stock_solution") or None,
        "printer_head_id": condition.get("printer_head_id") or None,
    }


def _artifact_paths(run_dir: Path, repo_root: Path) -> dict[str, Any]:
    captures = run_dir / "captures"
    capture_count = 0
    if captures.exists():
        capture_count = sum(1 for item in captures.iterdir() if item.is_file())
    return {
        "run_dir": _rel(run_dir, repo_root),
        "flow_fit_json": _rel(run_dir / "flow_fit.json", repo_root),
        "tail_fit_json": _rel(run_dir / "tail_fit.json", repo_root),
        "frames_jsonl": _rel(run_dir / "frames.jsonl", repo_root),
        "events_jsonl": _rel(run_dir / "events.jsonl", repo_root),
        "captures_dir": _rel(captures, repo_root),
        "capture_count": capture_count,
    }


def _missing_reasons(run_dir: Path, tail_fit_path: Path, flow_fit_path: Path) -> list[str]:
    reasons: list[str] = []
    if not run_dir.exists():
        return ["missing_run_dir"]
    if not tail_fit_path.exists():
        reasons.append("missing_tail_fit")
    if not flow_fit_path.exists():
        reasons.append("missing_flow_fit")
    if not (run_dir / "frames.jsonl").exists():
        reasons.append("missing_frames_jsonl")
    if not (run_dir / "events.jsonl").exists():
        reasons.append("missing_events_jsonl")
    captures = run_dir / "captures"
    if not captures.exists() or not any(item.is_file() for item in captures.iterdir()):
        reasons.append("missing_captures")
    if tail_fit_path.exists():
        try:
            tail_fit = _read_json(tail_fit_path)
        except Exception:
            reasons.append("invalid_tail_fit_json")
        else:
            if not _has_tail_summaries(tail_fit):
                reasons.append("missing_tail_summaries")
    return reasons


def _subsets(
    experiment_id: str,
    has_window_candidates: bool,
    has_segmented_result: bool,
    reason: str | None,
) -> list[str]:
    subsets = ["full_replayable"]
    if experiment_id == "stream_120um_rep2-20260612_113906":
        subsets.append("current_120um_issue")
    if has_window_candidates or has_segmented_result:
        subsets.append("segmented_window_bank")
    if reason == "root_window_override_steep_collapse":
        subsets.append("root_window_override_cases")
    if reason == "selected_lowest_uniform_window":
        subsets.append("selected_lower_window_cases")
    if reason == "no_selected_lower_window":
        subsets.append("segmented_no_lower_window_cases")
    if reason == "legacy/no_segmented":
        subsets.append("legacy_regression")
    return subsets


def _append_experiment_summary(
    summaries: dict[str, dict[str, Any]],
    run: dict[str, Any] | None,
    excluded: dict[str, Any] | None,
) -> None:
    experiment_id = (run or excluded or {})["experiment_id"]
    summary = summaries.setdefault(
        experiment_id,
        {
            "experiment_id": experiment_id,
            "experiment_path": (run or excluded or {})["experiment_path"],
            "gravimetric_rows": 0,
            "full_replayable_rows": 0,
            "excluded_rows": 0,
            "conditions": Counter(),
            "stock_solutions": Counter(),
            "density_solutions": Counter(),
            "window_selection_reasons": Counter(),
            "subsets": Counter(),
        },
    )
    summary["gravimetric_rows"] += 1
    density = dict((run or excluded or {}).get("density") or {})
    if density.get("solution_id"):
        summary["density_solutions"][density["solution_id"]] += 1
    if run is None:
        summary["excluded_rows"] += 1
        return
    summary["full_replayable_rows"] += 1
    condition = run["condition"]
    condition_id = f"{condition.get('print_pulse_width_us')}us/{condition.get('print_pressure_psi')}psi"
    summary["conditions"][condition_id] += 1
    if condition.get("stock_solution"):
        summary["stock_solutions"][condition["stock_solution"]] += 1
    reason = run["current_analysis"].get("segmented", {}).get("window_selection_reason") or "legacy/no_segmented"
    summary["window_selection_reasons"][reason] += 1
    for subset in run["subsets"]:
        summary["subsets"][subset] += 1


def _finalize_experiment_summaries(summaries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    finalized: list[dict[str, Any]] = []
    for summary in sorted(summaries.values(), key=lambda item: item["experiment_id"]):
        item = dict(summary)
        for key in ("conditions", "stock_solutions", "density_solutions", "window_selection_reasons", "subsets"):
            item[key] = dict(sorted(item[key].items()))
        finalized.append(item)
    return finalized


def build_manifest(repo_root: Path = REPO_ROOT, experiments_root: Path = DEFAULT_EXPERIMENTS_ROOT) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    experiments_root = (repo_root / experiments_root).resolve()
    density_measurements = _load_density_measurements(repo_root)
    runs: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    experiment_summaries: dict[str, dict[str, Any]] = {}

    for metadata_path in sorted(experiments_root.rglob("stream_metadata.csv")):
        experiment_dir = metadata_path.parent
        experiment_id = experiment_dir.name
        with metadata_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row_index, row in enumerate(reader, start=1):
                mass_per_print_mg = _parse_float(row.get("Mass/print"))
                if mass_per_print_mg is None:
                    continue

                dataset_name = (row.get("Dataset name") or "").strip()
                run_dir = (
                    experiment_dir
                    / "calibration_recordings"
                    / "OnlineStreamCalibrationProcess"
                    / dataset_name
                )
                tail_fit_path = run_dir / "tail_fit.json"
                flow_fit_path = run_dir / "flow_fit.json"
                reasons = _missing_reasons(run_dir, tail_fit_path, flow_fit_path)
                base = {
                    "experiment_id": experiment_id,
                    "experiment_path": _rel(experiment_dir, repo_root),
                    "metadata_csv": _rel(metadata_path, repo_root),
                    "metadata_row_index": row_index,
                    "run_id": dataset_name,
                    "dataset_name": dataset_name,
                }
                density = _density_assignment(experiment_id, density_measurements)
                optics = _optics_assignment()
                water_density_volume_nl = mass_per_print_mg * 1000.0
                density_corrected_volume_nl = _gravimetric_volume_nl(
                    mass_per_print_mg,
                    _parse_float(density.get("density_g_per_ml")),
                )

                if reasons:
                    excluded = {
                        **base,
                        "exclusion_reasons": reasons,
                        "density": density,
                        "optics": optics,
                        "gravimetric": {
                            "mass_per_print_mg": _round(mass_per_print_mg, 6),
                            "gravimetric_volume_nl": _round(density_corrected_volume_nl, 3),
                            "gravimetric_volume_nl_water_density": _round(water_density_volume_nl, 3),
                            "density_g_per_ml": _round(_parse_float(density.get("density_g_per_ml")), 6),
                            "density_assumption_g_per_ml": DENSITY_ASSUMPTION_G_PER_ML,
                            "num_printed": _parse_int(row.get("Num printed")),
                        },
                    }
                    excluded_rows.append(excluded)
                    _append_experiment_summary(experiment_summaries, None, excluded)
                    continue

                tail_fit = _read_json(tail_fit_path)
                flow_fit = _read_json(flow_fit_path)
                rate, intercept = _flow_fit_values(flow_fit)
                tail_values = _tail_result_values(tail_fit)
                water_density_equivalent_tail_start_us = None
                density_corrected_equivalent_tail_start_us = None
                if rate not in (None, 0.0) and intercept is not None:
                    water_density_equivalent_tail_start_us = (water_density_volume_nl - intercept) / rate
                    if density_corrected_volume_nl is not None:
                        density_corrected_equivalent_tail_start_us = (density_corrected_volume_nl - intercept) / rate
                current_tail_start = tail_values["tail_start_from_emergence_us"]
                current_volume = tail_values["predicted_volume_nl"]
                window_reason = tail_values["segmented"].get("window_selection_reason") or "legacy/no_segmented"
                has_window_candidates = _has_window_candidates(tail_fit)
                condition = _condition(row, tail_fit)
                subsets = _subsets(
                    experiment_id,
                    has_window_candidates,
                    bool(tail_values["has_segmented_result"]),
                    window_reason,
                )
                run = {
                    **base,
                    "subsets": subsets,
                    "condition": condition,
                    "density": density,
                    "optics": optics,
                    "gravimetric": {
                        "mass_per_print_mg": _round(mass_per_print_mg, 6),
                        "gravimetric_volume_nl": _round(density_corrected_volume_nl, 3),
                        "gravimetric_volume_nl_water_density": _round(water_density_volume_nl, 3),
                        "density_g_per_ml": _round(_parse_float(density.get("density_g_per_ml")), 6),
                        "density_assumption_g_per_ml": DENSITY_ASSUMPTION_G_PER_ML,
                        "num_printed": _parse_int(row.get("Num printed")),
                        "mass_change_mg": _round(_parse_float(row.get("Mass Change")), 6),
                        "starting_flash": _parse_int(row.get("Starting flash")),
                        "ending_flash": _parse_int(row.get("Ending flash")),
                        "replicate": _parse_int(row.get("Rep")),
                    },
                    "artifacts": {
                        **_artifact_paths(run_dir, repo_root),
                        "has_tail_summaries": True,
                        "has_tail_width_window_candidates": has_window_candidates,
                        "has_segmented_result": bool(tail_values["has_segmented_result"]),
                        "has_segmented_candidate_traces": bool(tail_values["has_segmented_candidate_traces"]),
                    },
                    "current_analysis": {
                        "flow_rate_nl_per_us": _round(rate, 9),
                        "flow_intercept_nl": _round(intercept, 6),
                        "tail_start_from_emergence_us": current_tail_start,
                        "predicted_volume_nl": current_volume,
                        "volume_error_vs_gravimetric_nl": _round(
                            current_volume - water_density_volume_nl if current_volume is not None else None,
                            6,
                        ),
                        "volume_error_vs_gravimetric_density_corrected_nl": _round(
                            current_volume - density_corrected_volume_nl
                            if current_volume is not None and density_corrected_volume_nl is not None
                            else None,
                            6,
                        ),
                        "gravimetric_equivalent_tail_start_us": _round(water_density_equivalent_tail_start_us, 3),
                        "gravimetric_density_corrected_equivalent_tail_start_us": _round(
                            density_corrected_equivalent_tail_start_us,
                            3,
                        ),
                        "tail_start_error_vs_gravimetric_equivalent_us": _round(
                            current_tail_start - water_density_equivalent_tail_start_us
                            if current_tail_start is not None and water_density_equivalent_tail_start_us is not None
                            else None,
                            3,
                        ),
                        "tail_start_error_vs_density_corrected_gravimetric_equivalent_us": _round(
                            current_tail_start - density_corrected_equivalent_tail_start_us
                            if current_tail_start is not None
                            and density_corrected_equivalent_tail_start_us is not None
                            else None,
                            3,
                        ),
                        "warnings": tail_values["warnings"],
                        "segmented": tail_values["segmented"],
                    },
                }
                runs.append(run)
                _append_experiment_summary(experiment_summaries, run, None)

    subset_counts = Counter()
    for run in runs:
        subset_counts.update(run["subsets"])
    density_solution_counts = Counter(
        str(run.get("density", {}).get("solution_id") or "unassigned")
        for run in runs
    )
    total_density_solution_counts = Counter(density_solution_counts)
    total_density_solution_counts.update(
        str(row.get("density", {}).get("solution_id") or "unassigned")
        for row in excluded_rows
    )
    optics_assignment_counts = Counter(
        str(run.get("optics", {}).get("um_per_pixel") or "unassigned")
        for run in runs
    )
    total_optics_assignment_counts = Counter(optics_assignment_counts)
    total_optics_assignment_counts.update(
        str(row.get("optics", {}).get("um_per_pixel") or "unassigned")
        for row in excluded_rows
    )
    exclusion_counts = Counter(
        reason
        for row in excluded_rows
        for reason in row["exclusion_reasons"]
    )
    summary = {
        "total_gravimetric_rows": len(runs) + len(excluded_rows),
        "full_replayable_rows": len(runs),
        "excluded_rows": len(excluded_rows),
        "subset_counts": dict(sorted(subset_counts.items())),
        "exclusion_reason_counts": dict(sorted(exclusion_counts.items())),
        "density_solution_counts": dict(sorted(density_solution_counts.items())),
        "density_unassigned_rows": density_solution_counts.get("unassigned", 0),
        "total_density_solution_counts": dict(sorted(total_density_solution_counts.items())),
        "total_density_unassigned_rows": total_density_solution_counts.get("unassigned", 0),
        "optics_assignment_counts": dict(sorted(optics_assignment_counts.items())),
        "optics_unassigned_rows": optics_assignment_counts.get("unassigned", 0),
        "total_optics_assignment_counts": dict(sorted(total_optics_assignment_counts.items())),
        "total_optics_unassigned_rows": total_optics_assignment_counts.get("unassigned", 0),
        "experiment_count": len(experiment_summaries),
        "full_replayable_experiment_count": sum(
            1 for item in experiment_summaries.values() if item["full_replayable_rows"]
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_id": MANIFEST_ID,
        "name": "Online Stream Tail Gravimetric Validation v1",
        "description": (
            "Local gravimetric online-stream calibration runs with enough saved artifacts "
            "to replay or reconstruct flow and tail selection decisions."
        ),
        "density_layer": {
            "schema_version": "density_assignment_v1",
            "density_source_csv": _rel(repo_root / DENSITY_MEASUREMENTS_CSV, repo_root),
            "measurements_g_per_ml": dict(sorted(density_measurements.items())),
            "experiment_assignments": dict(sorted(EXPERIMENT_DENSITY_ASSIGNMENTS.items())),
            "assignment_source": ASSIGNMENT_SOURCE,
            "assignment_basis": "experiment_id",
            "gravimetric_volume_formula": "mass_per_print_mg * 1000 / density_g_per_ml",
            "compatibility_note": (
                "gravimetric_volume_nl is density-corrected. "
                "gravimetric_volume_nl_water_density and volume_error_vs_gravimetric_nl "
                "preserve the original 1.0 g/mL water-density calculation."
            ),
        },
        "optics_layer": {
            "schema_version": "optics_assignment_v1",
            "um_per_pixel": ASSIGNED_UM_PER_PIXEL,
            "assignment_basis": OPTICS_ASSIGNMENT_BASIS,
            "assignment_source": ASSIGNMENT_SOURCE,
            "assignment_confidence": "confirmed",
            "stored_in_run_artifacts": False,
            "code_default_um_per_pixel": CODE_DEFAULT_UM_PER_PIXEL,
            "volume_scale_vs_code_default": (ASSIGNED_UM_PER_PIXEL / CODE_DEFAULT_UM_PER_PIXEL) ** 3,
            "volume_scale_note": "Visible volume scales with um_per_pixel ** 3.",
        },
        "selection_criteria": {
            "experiments_root": _rel(experiments_root, repo_root),
            "included": [
                "stream_metadata.csv row has Mass/print",
                "Dataset name maps to calibration_recordings/OnlineStreamCalibrationProcess/run_*",
                "run folder has flow_fit.json, tail_fit.json, frames.jsonl, events.jsonl, and captures",
                "tail_fit.json has scout_delay_summaries and backtrack_delay_summaries",
            ],
            "gravimetric_volume_note": (
                "gravimetric_volume_nl is density-corrected. "
                "gravimetric_volume_nl_water_density uses Mass/print with a 1.0 g/mL density assumption."
            ),
        },
        "summary": summary,
        "experiments": _finalize_experiment_summaries(experiment_summaries),
        "runs": runs,
        "excluded_rows": excluded_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the online stream tail validation manifest.")
    parser.add_argument("--experiments-root", type=Path, default=DEFAULT_EXPERIMENTS_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Fail if the output file differs from regenerated JSON.")
    args = parser.parse_args(argv)

    manifest = build_manifest(REPO_ROOT, args.experiments_root)
    text = json.dumps(manifest, indent=2, sort_keys=False) + "\n"
    output_path = (REPO_ROOT / args.output).resolve()

    if args.check:
        existing = output_path.read_text(encoding="utf-8")
        if existing != text:
            raise SystemExit(f"Manifest is out of date: {_rel(output_path, REPO_ROOT)}")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    print(f"Wrote {_rel(output_path, REPO_ROOT)}")
    print(json.dumps(manifest["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
