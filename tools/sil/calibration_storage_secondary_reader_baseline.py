"""Freeze Milestone 4B secondary-consumer Pi evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from tools.sil.calibration_storage_baseline import (
    CalibrationStorageBaselineError,
    candidate_upper_limit,
)
from tools.sil.calibration_storage_primary_reader_baseline import EXPECTED_COUNTS
from tools.sil.calibration_storage_shadow_baseline import (
    _resolve_raw_report,
    _sha256,
    _storage,
)
from tools.virtual_workflows.compare import load_report_set
from tools.virtual_workflows.report import validate_report_v1


SCHEMA_NAME = "labcraft.calibration_storage_secondary_reader_pi_baseline"
SCHEMA_VERSION = 1
WORKLOAD_ID = "calibration_storage_secondary_reader_8x25_v1"
BASELINE_ID = "calibration_storage_secondary_reader_pi5_v1"
SECONDARY_METRICS = (
    "memory_rebuild_latency_ms",
    "summary_latency_ms",
    "tool_update_load_latency_ms",
    "export_latency_ms",
)
MATCHING_WORKLOAD_FIELDS = (
    "capture_mode", "completion_count", "expected_update_count", "fixture_path",
    "fixture_schema_version", "fixture_sha256", "head_count",
    "key_evidence_probe_capture_count", "large_process_ordinal_per_head",
    "large_update_count_per_process", "process_runs_per_head", "speed_multiplier",
    "structured_process_runs", "timeout_seconds", "workload_hash",
)


def _validate_report(report: Mapping[str, Any]) -> None:
    validate_report_v1(report)
    if report.get("classification", {}).get("status") != "pass":
        raise CalibrationStorageBaselineError("all secondary-reader reports must pass")
    if report.get("workload", {}).get("workload_id") != WORKLOAD_ID:
        raise CalibrationStorageBaselineError("unexpected secondary-reader workload")
    storage = _storage(report)
    for key, expected in EXPECTED_COUNTS.items():
        if storage.get(key) != expected:
            raise CalibrationStorageBaselineError(f"secondary-reader {key} drifted")
    secondary = storage.get("secondary_consumer_metrics") or {}
    if (
        int(secondary.get("memory_usable_run_count") or 0) != 200
        or int(secondary.get("summary_row_count") or 0) != 200
        or int(secondary.get("consumer_error_count") or 0) != 0
        or secondary.get("legacy_hash_preserved") is not True
        or secondary.get("tool_reader_state") not in {"canonical_only", "matching_dual"}
    ):
        raise CalibrationStorageBaselineError("secondary-consumer integrity drifted")
    for name in SECONDARY_METRICS:
        metric = secondary.get(name)
        if not isinstance(metric, Mapping) or int(metric.get("count") or 0) < 1:
            raise CalibrationStorageBaselineError(f"secondary metric {name} is incomplete")


def create_secondary_reader_baseline(
    report_set: Mapping[str, Any],
    measured_reports: Sequence[Mapping[str, Any]],
    milestone4a_baseline: Mapping[str, Any],
    *,
    report_set_sha256: str,
    milestone4a_baseline_sha256: str,
) -> dict[str, Any]:
    runs = report_set.get("runs") or {}
    warmups = list(runs.get("warmups") or [])
    measured = list(runs.get("measured") or [])
    if len(warmups) != 1 or len(measured) != 3 or len(measured_reports) != 3:
        raise CalibrationStorageBaselineError(
            "secondary-reader qualification requires one warmup and three measured runs"
        )
    sources = list((report_set.get("source_summary") or {}).get("sources") or [])
    if (report_set.get("source_summary") or {}).get("any_dirty_worktree") is not False or len(sources) != 1:
        raise CalibrationStorageBaselineError("secondary-reader evidence must use one clean commit")
    for report in measured_reports:
        _validate_report(report)

    compatibility = dict(report_set.get("compatibility") or {})
    environment = dict(compatibility.get("environment") or {})
    prior_environment = dict((milestone4a_baseline.get("compatibility") or {}).get("environment") or {})
    for key in ("architecture", "operating_system", "os_release", "python_implementation", "python_version", "qt"):
        if environment.get(key) != prior_environment.get(key):
            raise CalibrationStorageBaselineError(f"Milestone 4A environment drifted for {key}")
    target = environment.get("target_pi") or {}
    prior_target = prior_environment.get("target_pi") or {}
    if target.get("pi_model") != prior_target.get("pi_model"):
        raise CalibrationStorageBaselineError("Milestone 4A Pi model drifted")
    for key in ("storage_class", "filesystem_type"):
        if (target.get("filesystem") or {}).get(key) != (prior_target.get("filesystem") or {}).get(key):
            raise CalibrationStorageBaselineError(f"Milestone 4A storage environment drifted for {key}")
    workload = dict(compatibility.get("workload") or {})
    prior_workload = dict((milestone4a_baseline.get("compatibility") or {}).get("workload") or {})
    for key in MATCHING_WORKLOAD_FIELDS:
        if workload.get(key) != prior_workload.get(key):
            raise CalibrationStorageBaselineError(f"Milestone 4A workload drifted for {key}")

    regression = False
    reader_comparison = {}
    for name, prior in (milestone4a_baseline.get("reader_metrics") or {}).items():
        observed = [float(_storage(report)["reader_metrics"][name]["p95"]) for report in measured_reports]
        upper = float(prior["candidate_limit"]["upper_limit"])
        decision = "pass" if max(observed) <= upper else "regression"
        regression = regression or decision != "pass"
        reader_comparison[name] = {
            "observed_p95": observed,
            "milestone4a_upper_limit": upper,
            "decision": decision,
        }

    secondary_candidates = {}
    for name in SECONDARY_METRICS:
        per_run = [
            {
                "run_id": reference.get("run_id"),
                "distribution": dict(
                    _storage(report)["secondary_consumer_metrics"][name]
                ),
            }
            for reference, report in zip(measured, measured_reports)
        ]
        secondary_candidates[name] = {
            "unit": "milliseconds",
            "per_run": per_run,
            "candidate_limit": candidate_upper_limit(
                [float(item["distribution"]["p95"]) for item in per_run], floor=1.0
            ),
        }

    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "baseline_id": BASELINE_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": dict(sources[0]),
        "host_label": report_set.get("host_label"),
        "compatibility": compatibility,
        "exact_counts": {**EXPECTED_COUNTS, "key_evidence_probe_capture_count": 2},
        "secondary_metrics": secondary_candidates,
        "secondary_integrity": {
            "memory_usable_run_count": 200,
            "summary_row_count": 200,
            "consumer_error_count": 0,
            "legacy_hash_preserved": True,
        },
        "milestone4a_comparison": {
            "baseline_id": milestone4a_baseline.get("baseline_id"),
            "baseline_sha256": milestone4a_baseline_sha256,
            "reader_metrics": reader_comparison,
            "decision": "regression" if regression else "pass",
        },
        "artifact_growth": {
            "per_run": [
                {"run_id": reference.get("run_id"), **dict(_storage(report)["artifact_growth"])}
                for reference, report in zip(measured, measured_reports)
            ]
        },
        "runs": {
            "warmup_count": 1,
            "measured_count": 3,
            "report_set_sha256": report_set_sha256,
            "raw_reports": [
                {"role": role, "path": ref.get("path"), "sha256": ref.get("sha256"), "run_id": ref.get("run_id")}
                for role, refs in (("warmup", warmups), ("measured", measured))
                for ref in refs
            ],
        },
        "classification": {
            "status": "fail" if regression else "pass",
            "threshold_maturity": "candidate",
        },
        "limitations": [
            "Image analysis, camera acquisition, firmware, and physical hardware behavior are outside this baseline."
        ],
    }


def freeze_secondary_reader_baseline(
    report_set_path: Path, milestone4a_baseline_path: Path, output_path: Path
) -> Path:
    source = report_set_path.resolve()
    prior_path = milestone4a_baseline_path.resolve()
    output = output_path.resolve()
    if output.exists():
        raise CalibrationStorageBaselineError(f"refusing to overwrite: {output}")
    report_set = load_report_set(source)
    reports = []
    for reference in report_set["runs"]["measured"]:
        raw_path = _resolve_raw_report(source, reference)
        if _sha256(raw_path) != reference.get("sha256"):
            raise CalibrationStorageBaselineError(f"raw report hash mismatch: {raw_path}")
        reports.append(json.loads(raw_path.read_text(encoding="utf-8")))
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    baseline = create_secondary_reader_baseline(
        report_set, reports, prior,
        report_set_sha256=_sha256(source),
        milestone4a_baseline_sha256=_sha256(prior_path),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(baseline, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, output)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze a Milestone 4B secondary-reader Pi baseline.")
    parser.add_argument("--report-set", type=Path, required=True)
    parser.add_argument("--milestone4a-baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        path = freeze_secondary_reader_baseline(
            args.report_set, args.milestone4a_baseline, args.output
        )
    except (CalibrationStorageBaselineError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASELINE_ID", "SECONDARY_METRICS", "create_secondary_reader_baseline",
    "freeze_secondary_reader_baseline",
]
