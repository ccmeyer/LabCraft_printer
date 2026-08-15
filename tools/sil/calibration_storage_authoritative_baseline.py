"""Freeze and compare Milestone 3 authoritative calibration-store Pi evidence."""

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
from tools.sil.calibration_storage_shadow_baseline import (
    COMMON_RESOURCE_METRICS,
    COMMON_TIMING_METRICS,
    NEW_TIMING_METRICS,
    _path,
    _resolve_raw_report,
    _sha256,
    _storage,
)
from tools.virtual_workflows.compare import load_report_set
from tools.virtual_workflows.report import validate_report_v1


SCHEMA_NAME = "labcraft.calibration_storage_authoritative_pi_baseline"
SCHEMA_VERSION = 1
WORKLOAD_ID = "calibration_storage_authoritative_8x25_v1"
BASELINE_ID = "calibration_storage_authoritative_pi5_v1"
EXPECTED_COUNTS = {
    "process_run_count": 200,
    "legacy_run_envelope_count": 201,
    "update_count": 232,
    "recording_count": 200,
    "workload_capture_count": 0,
    "canonical_update_count": 232,
    "canonical_result_count": 200,
    "canonical_index_event_count": 200,
    "integrity_failure_count": 0,
}


def _validate_report(report: Mapping[str, Any]) -> None:
    validate_report_v1(report)
    if report.get("classification", {}).get("status") != "pass":
        raise CalibrationStorageBaselineError("all authoritative reports must pass")
    if report.get("workload", {}).get("workload_id") != WORKLOAD_ID:
        raise CalibrationStorageBaselineError("unexpected authoritative workload")
    storage = _storage(report)
    if storage.get("authoritative_mode") is not True:
        raise CalibrationStorageBaselineError("authoritative mode was not recorded")
    for key, expected in EXPECTED_COUNTS.items():
        if storage.get(key) != expected:
            raise CalibrationStorageBaselineError(f"authoritative {key} drifted")
    if storage.get("key_evidence_probe", {}).get("capture_count") != 2:
        raise CalibrationStorageBaselineError("authoritative capture probe drifted")
    for name in (*COMMON_TIMING_METRICS, *NEW_TIMING_METRICS):
        distribution = storage.get("metrics", {}).get(name)
        if not isinstance(distribution, Mapping) or int(
            distribution.get("count") or 0
        ) < 1:
            raise CalibrationStorageBaselineError(
                f"authoritative {name} is incomplete"
            )


def _shadow_limit(shadow: Mapping[str, Any], name: str) -> float:
    if name in NEW_TIMING_METRICS:
        return float(shadow["new_metrics"][name]["candidate_limit"]["upper_limit"])
    return float(
        shadow["legacy_comparison"]["metrics"][name]["legacy_upper_limit"]
    )


def create_authoritative_baseline(
    report_set: Mapping[str, Any],
    measured_reports: Sequence[Mapping[str, Any]],
    shadow_baseline: Mapping[str, Any],
    *,
    report_set_sha256: str,
    shadow_baseline_sha256: str,
) -> dict[str, Any]:
    runs = report_set.get("runs") or {}
    warmup_refs = list(runs.get("warmups") or [])
    measured_refs = list(runs.get("measured") or [])
    if len(warmup_refs) != 1 or len(measured_refs) != 3:
        raise CalibrationStorageBaselineError(
            "authoritative qualification requires one warmup and three measured runs"
        )
    if len(measured_reports) != 3:
        raise CalibrationStorageBaselineError(
            "three measured authoritative reports are required"
        )
    source_summary = report_set.get("source_summary") or {}
    sources = list(source_summary.get("sources") or [])
    if source_summary.get("any_dirty_worktree") is not False or len(sources) != 1:
        raise CalibrationStorageBaselineError(
            "authoritative evidence must use one clean commit"
        )
    for report in measured_reports:
        _validate_report(report)

    compatibility = report_set.get("compatibility") or {}
    workload = compatibility.get("workload") or {}
    shadow_workload = shadow_baseline.get("compatibility", {}).get("workload", {})
    for key in ("fixture_sha256", "workload_hash"):
        if workload.get(key) != shadow_workload.get(key):
            raise CalibrationStorageBaselineError(
                f"authoritative workload is incompatible with shadow {key}"
            )
    environment = compatibility.get("environment", {})
    shadow_environment = shadow_baseline.get("compatibility", {}).get(
        "environment", {}
    )
    for key in (
        "architecture",
        "operating_system",
        "os_release",
        "python_implementation",
        "python_version",
        "qt",
    ):
        if environment.get(key) != shadow_environment.get(key):
            raise CalibrationStorageBaselineError(
                f"authoritative runtime environment drifted for {key}"
            )
    target = environment.get("target_pi", {})
    shadow_target = shadow_environment.get("target_pi", {})
    if target.get("pi_model") != shadow_target.get("pi_model"):
        raise CalibrationStorageBaselineError(
            "authoritative Pi model drifted"
        )
    filesystem = target.get("filesystem", {})
    shadow_filesystem = shadow_target.get("filesystem", {})
    for key in ("storage_class", "filesystem_type"):
        if filesystem.get(key) != shadow_filesystem.get(key):
            raise CalibrationStorageBaselineError(
                f"authoritative storage environment drifted for {key}"
            )

    comparison: dict[str, Any] = {}
    regression = False
    for name in (*COMMON_TIMING_METRICS, *NEW_TIMING_METRICS):
        observed = [
            float(_storage(report)["metrics"][name]["p95"])
            for report in measured_reports
        ]
        upper = _shadow_limit(shadow_baseline, name)
        decision = "pass" if max(observed) <= upper else "regression"
        regression = regression or decision != "pass"
        comparison[name] = {
            "observed_p95": observed,
            "shadow_upper_limit": upper,
            "decision": decision,
        }
    for name, path in COMMON_RESOURCE_METRICS.items():
        observed = [float(_path(report, path)) for report in measured_reports]
        upper = float(
            shadow_baseline["legacy_comparison"]["metrics"][name][
                "legacy_upper_limit"
            ]
        )
        decision = "pass" if max(observed) <= upper else "regression"
        regression = regression or decision != "pass"
        comparison[name] = {
            "observed": observed,
            "shadow_upper_limit": upper,
            "decision": decision,
        }

    candidate_metrics = {}
    for name in (*COMMON_TIMING_METRICS, *NEW_TIMING_METRICS):
        per_run = [
            {
                "run_id": reference.get("run_id"),
                "distribution": dict(_storage(report)["metrics"][name]),
            }
            for reference, report in zip(measured_refs, measured_reports)
        ]
        p95_values = [float(row["distribution"]["p95"]) for row in per_run]
        candidate_metrics[name] = {
            "unit": "milliseconds",
            "per_run": per_run,
            "candidate_limit": candidate_upper_limit(
                p95_values,
                floor=float(NEW_TIMING_METRICS.get(name, 1.0)),
            ),
        }

    raw_reports = []
    for role, references in (("warmup", warmup_refs), ("measured", measured_refs)):
        raw_reports.extend(
            {
                "role": role,
                "path": reference.get("path"),
                "sha256": reference.get("sha256"),
                "run_id": reference.get("run_id"),
            }
            for reference in references
        )
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "baseline_id": BASELINE_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "source": dict(sources[0]),
        "host_label": report_set.get("host_label"),
        "compatibility": dict(compatibility),
        "exact_counts": {
            **EXPECTED_COUNTS,
            "key_evidence_probe_capture_count": 2,
        },
        "shadow_comparison": {
            "baseline_id": shadow_baseline.get("baseline_id"),
            "baseline_sha256": shadow_baseline_sha256,
            "metrics": comparison,
            "decision": "regression" if regression else "pass",
        },
        "metrics": candidate_metrics,
        "artifact_growth": {
            "per_run": [
                {
                    "run_id": reference.get("run_id"),
                    **dict(_storage(report)["artifact_growth"]),
                }
                for reference, report in zip(measured_refs, measured_reports)
            ],
            "comparison_policy": "measured_additive_not_shadow_gated",
        },
        "runs": {
            "warmup_count": 1,
            "measured_count": 3,
            "report_set_sha256": report_set_sha256,
            "raw_reports": raw_reports,
        },
        "classification": {
            "status": "fail" if regression else "pass",
            "threshold_maturity": "candidate",
        },
        "limitations": [
            "Image analysis, camera acquisition, firmware, and physical hardware behavior are outside this baseline.",
            "Artifact growth is additive during legacy dual-writing and is measured but not gated against the Milestone 2 total-byte observation.",
        ],
    }


def freeze_authoritative_baseline(
    report_set_path: Path, shadow_baseline_path: Path, output_path: Path
) -> Path:
    source = report_set_path.resolve()
    shadow_path = shadow_baseline_path.resolve()
    output = output_path.resolve()
    if output.exists():
        raise CalibrationStorageBaselineError(f"refusing to overwrite: {output}")
    report_set = load_report_set(source)
    measured_reports = []
    for reference in report_set["runs"]["measured"]:
        raw_path = _resolve_raw_report(source, reference)
        if _sha256(raw_path) != reference.get("sha256"):
            raise CalibrationStorageBaselineError(
                f"raw report hash mismatch: {raw_path}"
            )
        measured_reports.append(json.loads(raw_path.read_text(encoding="utf-8")))
    shadow = json.loads(shadow_path.read_text(encoding="utf-8"))
    baseline = create_authoritative_baseline(
        report_set,
        measured_reports,
        shadow,
        report_set_sha256=_sha256(source),
        shadow_baseline_sha256=_sha256(shadow_path),
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
    parser = argparse.ArgumentParser(
        description="Freeze a Milestone 3 authoritative Pi baseline."
    )
    parser.add_argument("--report-set", type=Path, required=True)
    parser.add_argument("--shadow-baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        path = freeze_authoritative_baseline(
            arguments.report_set,
            arguments.shadow_baseline,
            arguments.output,
        )
    except (CalibrationStorageBaselineError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASELINE_ID",
    "EXPECTED_COUNTS",
    "create_authoritative_baseline",
    "freeze_authoritative_baseline",
]
