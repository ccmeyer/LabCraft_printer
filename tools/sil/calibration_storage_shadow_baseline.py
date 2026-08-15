"""Freeze and compare Milestone 2 Pi shadow-store evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from tools.sil.calibration_storage_baseline import (
    CalibrationStorageBaselineError,
    candidate_upper_limit,
)
from tools.virtual_workflows.compare import load_report_set
from tools.virtual_workflows.report import validate_report_v1


SCHEMA_NAME = "labcraft.calibration_storage_shadow_pi_baseline"
SCHEMA_VERSION = 1
WORKLOAD_ID = "calibration_storage_shadow_8x25_v1"
BASELINE_ID = "calibration_storage_shadow_pi5_v1"
NEW_TIMING_METRICS = {
    "canonical_update_append_latency_ms": 1.0,
    "result_finalize_latency": 1.0,
    "index_latency": 1.0,
}
COMMON_TIMING_METRICS = (
    "calibration_rewrite_latency_ms",
    "recorder_append_latency_ms",
    "update_latency_ms",
    "process_finalize_latency_ms",
    "first_quartile_update_latency_ms",
    "last_quartile_update_latency_ms",
    "history_load_latency_ms",
    "fresh_reload_latency_ms",
)
COMMON_RESOURCE_METRICS = {
    "peak_rss_bytes": ("metrics", "resources", "values", "peak_rss_bytes"),
    "rss_growth_bytes": ("metrics", "resources", "values", "rss_growth_bytes"),
}
EXPECTED_COUNTS = {
    "process_run_count": 200,
    "legacy_run_envelope_count": 201,
    "update_count": 232,
    "recording_count": 200,
    "workload_capture_count": 0,
    "canonical_update_count": 232,
    "canonical_result_count": 200,
    "canonical_index_event_count": 200,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path(payload: Mapping[str, Any], parts: Sequence[str]) -> Any:
    value: Any = payload
    for part in parts:
        if not isinstance(value, Mapping) or part not in value:
            raise CalibrationStorageBaselineError(
                f"missing shadow baseline field: {'.'.join(parts)}"
            )
        value = value[part]
    return value


def _storage(report: Mapping[str, Any]) -> Mapping[str, Any]:
    value = _path(
        report, ("metrics", "persistence", "values", "calibration_storage")
    )
    if not isinstance(value, Mapping):
        raise CalibrationStorageBaselineError("calibration storage metrics are invalid")
    return value


def _resolve_raw_report(report_set_path: Path, reference: Mapping[str, Any]) -> Path:
    raw = Path(str(reference.get("path") or ""))
    candidates = [raw]
    if not raw.is_absolute():
        candidates.extend((Path.cwd() / raw, report_set_path.parent / raw))
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    raise CalibrationStorageBaselineError(f"referenced raw report is missing: {raw}")


def _validate_shadow_report(report: Mapping[str, Any]) -> None:
    validate_report_v1(report)
    if report.get("classification", {}).get("status") != "pass":
        raise CalibrationStorageBaselineError("all shadow reports must pass")
    if report.get("workload", {}).get("workload_id") != WORKLOAD_ID:
        raise CalibrationStorageBaselineError("unexpected shadow workload")
    storage = _storage(report)
    for key, expected in EXPECTED_COUNTS.items():
        if storage.get(key) != expected:
            raise CalibrationStorageBaselineError(f"shadow {key} drifted")
    if storage.get("key_evidence_probe", {}).get("capture_count") != 2:
        raise CalibrationStorageBaselineError("shadow capture probe drifted")
    for name in (*COMMON_TIMING_METRICS, *NEW_TIMING_METRICS):
        distribution = storage.get("metrics", {}).get(name)
        if not isinstance(distribution, Mapping) or int(
            distribution.get("count") or 0
        ) < 1:
            raise CalibrationStorageBaselineError(f"shadow {name} is incomplete")


def create_shadow_baseline(
    report_set: Mapping[str, Any],
    measured_reports: Sequence[Mapping[str, Any]],
    legacy_baseline: Mapping[str, Any],
    *,
    report_set_sha256: str,
    legacy_baseline_sha256: str,
) -> dict[str, Any]:
    runs = report_set.get("runs") or {}
    measured_refs = list(runs.get("measured") or [])
    if len(runs.get("warmups") or []) != 1 or len(measured_refs) != 3:
        raise CalibrationStorageBaselineError(
            "shadow qualification requires one warmup and three measured runs"
        )
    if len(measured_reports) != 3:
        raise CalibrationStorageBaselineError("three measured shadow reports are required")
    source_summary = report_set.get("source_summary") or {}
    sources = list(source_summary.get("sources") or [])
    if source_summary.get("any_dirty_worktree") is not False or len(sources) != 1:
        raise CalibrationStorageBaselineError("shadow evidence must use one clean commit")
    for report in measured_reports:
        _validate_shadow_report(report)
    compatibility = report_set.get("compatibility") or {}
    workload = compatibility.get("workload") or {}
    legacy_workload = legacy_baseline.get("compatibility", {}).get("workload", {})
    for key in ("fixture_sha256", "workload_hash"):
        if workload.get(key) != legacy_workload.get(key):
            raise CalibrationStorageBaselineError(
                f"shadow workload is incompatible with legacy {key}"
            )
    legacy_target = legacy_baseline.get("compatibility", {}).get("environment", {}).get(
        "target_pi", {}
    )
    shadow_target = compatibility.get("environment", {}).get("target_pi", {})
    if shadow_target.get("pi_model") != legacy_target.get("pi_model") or shadow_target.get(
        "filesystem"
    ) != legacy_target.get("filesystem"):
        raise CalibrationStorageBaselineError("shadow Pi/storage identity drifted")

    common_comparison = {}
    regression = False
    for name in COMMON_TIMING_METRICS:
        observed = [float(_storage(report)["metrics"][name]["p95"]) for report in measured_reports]
        upper = float(
            legacy_baseline["metrics"]["timing"][name]["candidate_limit"]["upper_limit"]
        )
        decision = "pass" if max(observed) <= upper else "regression"
        regression = regression or decision != "pass"
        common_comparison[name] = {
            "observed_p95": observed,
            "legacy_upper_limit": upper,
            "decision": decision,
        }
    for name, path in COMMON_RESOURCE_METRICS.items():
        observed = [float(_path(report, path)) for report in measured_reports]
        upper = float(
            legacy_baseline["metrics"]["resources_and_growth"][name][
                "candidate_limit"
            ]["upper_limit"]
        )
        decision = "pass" if max(observed) <= upper else "regression"
        regression = regression or decision != "pass"
        common_comparison[name] = {
            "observed": observed,
            "legacy_upper_limit": upper,
            "decision": decision,
        }

    new_metrics = {}
    for name, floor in NEW_TIMING_METRICS.items():
        per_run = [
            {
                "run_id": reference.get("run_id"),
                "distribution": dict(_storage(report)["metrics"][name]),
            }
            for reference, report in zip(measured_refs, measured_reports)
        ]
        p95_values = [float(row["distribution"]["p95"]) for row in per_run]
        new_metrics[name] = {
            "unit": "milliseconds",
            "per_run": per_run,
            "candidate_limit": candidate_upper_limit(p95_values, floor=floor),
        }

    raw_reports = []
    for role, references in (
        ("warmup", list(runs.get("warmups") or [])),
        ("measured", measured_refs),
    ):
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
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": dict(sources[0]),
        "host_label": report_set.get("host_label"),
        "compatibility": dict(compatibility),
        "exact_counts": {**EXPECTED_COUNTS, "key_evidence_probe_capture_count": 2},
        "legacy_comparison": {
            "baseline_id": legacy_baseline.get("baseline_id"),
            "baseline_sha256": legacy_baseline_sha256,
            "metrics": common_comparison,
            "decision": "regression" if regression else "pass",
        },
        "new_metrics": new_metrics,
        "artifact_growth": {
            "per_run": [
                {
                    "run_id": reference.get("run_id"),
                    "calibration_json_bytes": _storage(report)["artifact_growth"][
                        "calibration_json_bytes"
                    ],
                    "scenario_total_bytes": _storage(report)["artifact_growth"][
                        "scenario_total_bytes"
                    ],
                    "inventory": _storage(report)["artifact_growth"]["inventory"],
                }
                for reference, report in zip(measured_refs, measured_reports)
            ],
            "comparison_policy": "measured_additive_not_legacy_gated",
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
            "Canonical artifacts remain non-authoritative in Milestone 2.",
            "Artifact growth is additive in dual-write mode and is measured but not gated against the legacy total-byte limit.",
        ],
    }


def freeze_shadow_baseline(
    report_set_path: Path, legacy_baseline_path: Path, output_path: Path
) -> Path:
    source = report_set_path.resolve()
    legacy_path = legacy_baseline_path.resolve()
    output = output_path.resolve()
    if output.exists():
        raise CalibrationStorageBaselineError(f"refusing to overwrite: {output}")
    report_set = load_report_set(source)
    measured_reports = []
    for reference in report_set["runs"]["measured"]:
        raw_path = _resolve_raw_report(source, reference)
        if _sha256(raw_path) != reference.get("sha256"):
            raise CalibrationStorageBaselineError(f"raw report hash mismatch: {raw_path}")
        measured_reports.append(json.loads(raw_path.read_text(encoding="utf-8")))
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    baseline = create_shadow_baseline(
        report_set,
        measured_reports,
        legacy,
        report_set_sha256=_sha256(source),
        legacy_baseline_sha256=_sha256(legacy_path),
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
    parser = argparse.ArgumentParser(description="Freeze a Milestone 2 Pi shadow baseline.")
    parser.add_argument("--report-set", type=Path, required=True)
    parser.add_argument("--legacy-baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        path = freeze_shadow_baseline(
            arguments.report_set, arguments.legacy_baseline, arguments.output
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
    "create_shadow_baseline",
    "freeze_shadow_baseline",
]
