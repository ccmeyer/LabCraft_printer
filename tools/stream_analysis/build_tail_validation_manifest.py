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
            "window_selection_reasons": Counter(),
            "subsets": Counter(),
        },
    )
    summary["gravimetric_rows"] += 1
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
        for key in ("conditions", "stock_solutions", "window_selection_reasons", "subsets"):
            item[key] = dict(sorted(item[key].items()))
        finalized.append(item)
    return finalized


def build_manifest(repo_root: Path = REPO_ROOT, experiments_root: Path = DEFAULT_EXPERIMENTS_ROOT) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    experiments_root = (repo_root / experiments_root).resolve()
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

                if reasons:
                    excluded = {
                        **base,
                        "exclusion_reasons": reasons,
                        "gravimetric": {
                            "mass_per_print_mg": _round(mass_per_print_mg, 6),
                            "gravimetric_volume_nl_water_density": _round(mass_per_print_mg * 1000.0, 3),
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
                gravimetric_volume_nl = mass_per_print_mg * 1000.0
                equivalent_tail_start_us = None
                if rate not in (None, 0.0) and intercept is not None:
                    equivalent_tail_start_us = (gravimetric_volume_nl - intercept) / rate
                current_tail_start = tail_values["tail_start_from_emergence_us"]
                current_volume = tail_values["predicted_volume_nl"]
                window_reason = tail_values["segmented"].get("window_selection_reason") or "legacy/no_segmented"
                has_window_candidates = _has_window_candidates(tail_fit)
                subsets = _subsets(
                    experiment_id,
                    has_window_candidates,
                    bool(tail_values["has_segmented_result"]),
                    window_reason,
                )
                run = {
                    **base,
                    "subsets": subsets,
                    "condition": _condition(row, tail_fit),
                    "gravimetric": {
                        "mass_per_print_mg": _round(mass_per_print_mg, 6),
                        "gravimetric_volume_nl_water_density": _round(gravimetric_volume_nl, 3),
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
                            current_volume - gravimetric_volume_nl if current_volume is not None else None,
                            6,
                        ),
                        "gravimetric_equivalent_tail_start_us": _round(equivalent_tail_start_us, 3),
                        "tail_start_error_vs_gravimetric_equivalent_us": _round(
                            current_tail_start - equivalent_tail_start_us
                            if current_tail_start is not None and equivalent_tail_start_us is not None
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
        "selection_criteria": {
            "experiments_root": _rel(experiments_root, repo_root),
            "included": [
                "stream_metadata.csv row has Mass/print",
                "Dataset name maps to calibration_recordings/OnlineStreamCalibrationProcess/run_*",
                "run folder has flow_fit.json, tail_fit.json, frames.jsonl, events.jsonl, and captures",
                "tail_fit.json has scout_delay_summaries and backtrack_delay_summaries",
            ],
            "gravimetric_volume_note": (
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
