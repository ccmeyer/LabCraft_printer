"""Freeze a qualified Pi baseline for the legacy calibration-storage writers."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import tempfile
from typing import Any, Mapping, Sequence

from tools.virtual_workflows.compare import load_report_set
from tools.virtual_workflows.metrics import percentile
from tools.virtual_workflows.report import validate_report_v1


SCHEMA_NAME = "labcraft.calibration_storage_pi_baseline"
SCHEMA_VERSION = 1
WORKLOAD_ID = "calibration_storage_legacy_baseline_8x25_v1"
BASELINE_ID = "calibration_storage_legacy_pi5_v1"
EXPECTED_COUNTS = {
    "process_run_count": 200,
    "legacy_run_envelope_count": 201,
    "update_count": 232,
    "recording_count": 200,
    "workload_capture_count": 0,
    "key_evidence_probe_capture_count": 2,
}
TIMING_METRICS = (
    "calibration_rewrite_latency_ms",
    "recorder_append_latency_ms",
    "update_latency_ms",
    "process_finalize_latency_ms",
    "first_quartile_update_latency_ms",
    "last_quartile_update_latency_ms",
    "history_load_latency_ms",
    "fresh_reload_latency_ms",
)
CLOCK_RESOLUTION_FLOORS_MS = {
    "calibration_rewrite_latency_ms": 1.0,
    "recorder_append_latency_ms": 1.0,
    "update_latency_ms": 1.0,
    "process_finalize_latency_ms": 1.0,
    "first_quartile_update_latency_ms": 1.0,
    "last_quartile_update_latency_ms": 1.0,
    "history_load_latency_ms": 2.0,
    "fresh_reload_latency_ms": 10.0,
}
SCALAR_METRICS = {
    "peak_rss_bytes": ("metrics", "resources", "values", "peak_rss_bytes"),
    "rss_growth_bytes": ("metrics", "resources", "values", "rss_growth_bytes"),
    "calibration_json_bytes": (
        "metrics",
        "persistence",
        "values",
        "calibration_storage",
        "artifact_growth",
        "calibration_json_bytes",
    ),
    "scenario_total_bytes": (
        "metrics",
        "persistence",
        "values",
        "calibration_storage",
        "artifact_growth",
        "scenario_total_bytes",
    ),
}


class CalibrationStorageBaselineError(ValueError):
    """Raised when Pi evidence is not eligible for a storage baseline."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CalibrationStorageBaselineError(f"{name} must be an object")
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise CalibrationStorageBaselineError(f"{name} must be an array")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalibrationStorageBaselineError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise CalibrationStorageBaselineError(f"{name} must be finite")
    return result


def _path_value(payload: Mapping[str, Any], parts: Sequence[str], name: str) -> Any:
    value: Any = payload
    for part in parts:
        if not isinstance(value, Mapping) or part not in value:
            raise CalibrationStorageBaselineError(f"{name} is missing")
        value = value[part]
    return value


def _distribution(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        raise CalibrationStorageBaselineError("cannot summarize an empty series")
    samples = [float(value) for value in values]
    median = statistics.median(samples)
    return {
        "count": len(samples),
        "minimum": min(samples),
        "q1": percentile(samples, 0.25),
        "median": median,
        "q3": percentile(samples, 0.75),
        "maximum": max(samples),
        "median_absolute_deviation": statistics.median(
            abs(value - median) for value in samples
        ),
    }


def candidate_upper_limit(values: Sequence[float], *, floor: float) -> dict[str, float]:
    """Return the frozen Milestone 1 upper-limit calculation and components."""

    distribution = _distribution(values)
    relative_margin = 0.25 * float(distribution["median"])
    robust_margin = 6.0 * float(distribution["median_absolute_deviation"])
    selected_margin = max(relative_margin, robust_margin, float(floor))
    return {
        "maximum_observed": float(distribution["maximum"]),
        "relative_margin": relative_margin,
        "robust_margin": robust_margin,
        "measurement_floor": float(floor),
        "selected_margin": selected_margin,
        "upper_limit": float(distribution["maximum"]) + selected_margin,
    }


def _storage(report: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(
        _path_value(
            report,
            ("metrics", "persistence", "values", "calibration_storage"),
            "metrics.persistence.values.calibration_storage",
        ),
        "metrics.persistence.values.calibration_storage",
    )


def _validate_report_contract(report: Mapping[str, Any]) -> None:
    try:
        validate_report_v1(report)
    except ValueError as exc:
        raise CalibrationStorageBaselineError(f"invalid raw report: {exc}") from exc
    if report.get("classification", {}).get("status") != "pass":
        raise CalibrationStorageBaselineError("all baseline reports must pass")
    workload = _mapping(report.get("workload"), "report.workload")
    if workload.get("workload_id") != WORKLOAD_ID:
        raise CalibrationStorageBaselineError("raw report workload is not the frozen workload")
    if workload.get("completion_count") != EXPECTED_COUNTS["process_run_count"]:
        raise CalibrationStorageBaselineError("raw report process workload count drifted")
    if workload.get("expected_update_count") != EXPECTED_COUNTS["update_count"]:
        raise CalibrationStorageBaselineError("raw report update workload count drifted")

    storage = _storage(report)
    for key in (
        "process_run_count",
        "legacy_run_envelope_count",
        "update_count",
        "recording_count",
        "workload_capture_count",
    ):
        if storage.get(key) != EXPECTED_COUNTS[key]:
            raise CalibrationStorageBaselineError(f"raw report {key} drifted")
    probe = _mapping(storage.get("key_evidence_probe"), "key_evidence_probe")
    if probe.get("capture_count") != EXPECTED_COUNTS["key_evidence_probe_capture_count"]:
        raise CalibrationStorageBaselineError("raw report key-evidence probe drifted")
    metrics = _mapping(storage.get("metrics"), "calibration_storage.metrics")
    for metric_name in TIMING_METRICS:
        distribution = _mapping(metrics.get(metric_name), metric_name)
        if int(distribution.get("count") or 0) < 1:
            raise CalibrationStorageBaselineError(f"{metric_name} has no samples")
        for field in ("minimum", "median", "p95", "maximum"):
            _finite(distribution.get(field), f"{metric_name}.{field}")
    for deferred in ("result_finalize_latency", "index_latency"):
        state = _mapping(metrics.get(deferred), deferred)
        if state.get("status") != "not_available_until_m2" or state.get("samples") != []:
            raise CalibrationStorageBaselineError(f"{deferred} status drifted")

    target = _mapping(report.get("environment", {}).get("target_pi"), "target_pi")
    filesystem = _mapping(target.get("filesystem"), "target_pi.filesystem")
    if not target.get("pi_model") or not filesystem.get("storage_class") or not filesystem.get("filesystem_type"):
        raise CalibrationStorageBaselineError("qualified Pi/storage identity is incomplete")
    pi_sil = _mapping(report.get("safety", {}).get("pi_sil"), "safety.pi_sil")
    if not all(
        pi_sil.get(key) is True
        for key in ("private_dev", "root_read_only", "network_unshared")
    ):
        raise CalibrationStorageBaselineError("Pi hardware-isolation evidence is incomplete")


def create_calibration_storage_baseline(
    report_set: Mapping[str, Any],
    measured_reports: Sequence[Mapping[str, Any]],
    *,
    report_set_sha256: str,
) -> dict[str, Any]:
    """Create the compact baseline after report-set hashes have been verified."""

    runs = _mapping(report_set.get("runs"), "report_set.runs")
    warmups = _sequence(runs.get("warmups"), "report_set.runs.warmups")
    measured = _sequence(runs.get("measured"), "report_set.runs.measured")
    if len(warmups) != 1 or runs.get("warmup_count") != 1:
        raise CalibrationStorageBaselineError("baseline requires exactly one warm-up run")
    if len(measured) != 3 or runs.get("measured_count") != 3:
        raise CalibrationStorageBaselineError("baseline requires exactly three measured runs")
    if len(measured_reports) != 3:
        raise CalibrationStorageBaselineError("three measured raw reports are required")
    if report_set.get("functional", {}).get("status") != "pass":
        raise CalibrationStorageBaselineError("a functional failure cannot become a baseline")
    if report_set.get("synthetic", {}).get("warmup_injected_count") or report_set.get(
        "synthetic", {}
    ).get("measured_injected_count"):
        raise CalibrationStorageBaselineError("injected-stall reports cannot become a baseline")

    source_summary = _mapping(report_set.get("source_summary"), "source_summary")
    sources = _sequence(source_summary.get("sources"), "source_summary.sources")
    if source_summary.get("any_dirty_worktree") is not False or len(sources) != 1:
        raise CalibrationStorageBaselineError("baseline reports must use one clean source commit")
    source = _mapping(sources[0], "source_summary.sources[0]")
    if source.get("dirty_worktree") is not False or not source.get("git_commit"):
        raise CalibrationStorageBaselineError("baseline source identity is incomplete")

    compatibility = _mapping(report_set.get("compatibility"), "compatibility")
    workload = _mapping(compatibility.get("workload"), "compatibility.workload")
    if workload.get("workload_id") != WORKLOAD_ID:
        raise CalibrationStorageBaselineError("report-set workload is not the frozen workload")

    for report in measured_reports:
        _validate_report_contract(report)
    fixture_hashes = {str(report["workload"].get("fixture_sha256")) for report in measured_reports}
    workload_hashes = {str(report["workload"].get("workload_hash")) for report in measured_reports}
    if len(fixture_hashes) != 1 or "None" in fixture_hashes:
        raise CalibrationStorageBaselineError("fixture hashes differ or are absent")
    if len(workload_hashes) != 1 or "None" in workload_hashes:
        raise CalibrationStorageBaselineError("workload hashes differ or are absent")

    timing: dict[str, Any] = {}
    for metric_name in TIMING_METRICS:
        per_run = []
        p95_values = []
        median_values = []
        for reference, report in zip(measured, measured_reports):
            distribution = dict(_storage(report)["metrics"][metric_name])
            per_run.append(
                {"run_id": reference.get("run_id"), "distribution": distribution}
            )
            p95_values.append(_finite(distribution["p95"], f"{metric_name}.p95"))
            median_values.append(
                _finite(distribution["median"], f"{metric_name}.median")
            )
        timing[metric_name] = {
            "unit": "milliseconds",
            "per_run": per_run,
            "p95_distribution": _distribution(p95_values),
            "median_distribution": _distribution(median_values),
            "candidate_limit": candidate_upper_limit(
                p95_values, floor=CLOCK_RESOLUTION_FLOORS_MS[metric_name]
            ),
        }

    scalars: dict[str, Any] = {}
    for metric_name, metric_path in SCALAR_METRICS.items():
        values = [
            _finite(_path_value(report, metric_path, metric_name), metric_name)
            for report in measured_reports
        ]
        scalars[metric_name] = {
            "unit": "bytes",
            "per_run": [
                {"run_id": reference.get("run_id"), "value": value}
                for reference, value in zip(measured, values)
            ],
            "distribution": _distribution(values),
            "candidate_limit": candidate_upper_limit(values, floor=4096.0),
        }

    raw_reports = [
        {
            "role": "warmup" if index == 0 else "measured",
            "path": reference.get("path"),
            "sha256": reference.get("sha256"),
            "run_id": reference.get("run_id"),
        }
        for index, reference in enumerate([*warmups, *measured])
    ]
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "baseline_id": BASELINE_ID,
        "threshold_maturity": "candidate",
        "created_at_utc": _utc_now(),
        "source": dict(source),
        "host_label": report_set.get("host_label"),
        "compatibility": {
            "environment": dict(_mapping(compatibility.get("environment"), "environment")),
            "safety": dict(_mapping(compatibility.get("safety"), "safety")),
            "workload": dict(workload),
        },
        "fixture_identity": {
            "fixture_sha256": next(iter(fixture_hashes)),
            "workload_hash": next(iter(workload_hashes)),
        },
        "exact_counts": dict(EXPECTED_COUNTS),
        "runs": {
            "warmup_count": 1,
            "measured_count": 3,
            "report_set_sha256": report_set_sha256,
            "raw_reports": raw_reports,
        },
        "policy": {
            "upper_limit_formula": (
                "maximum observed p95 plus max(25% median p95, "
                "6 median absolute deviations, measurement floor)"
            ),
            "clock_resolution_floors_ms": dict(CLOCK_RESOLUTION_FLOORS_MS),
            "byte_measurement_floor": 4096,
        },
        "metrics": {"timing": timing, "resources_and_growth": scalars},
        "deferred_metrics": {
            "result_finalize_latency": "not_available_until_m2",
            "index_latency": "not_available_until_m2",
        },
        "classification": {
            "status": "pass",
            "threshold_maturity": "candidate",
        },
        "limitations": [
            "Valid only for the exact Pi model, storage class/filesystem, Python/Qt environment, fixture catalog, and workload hash above.",
            "Characterizes the current legacy writer; it is not an acceptance threshold for the Milestone 2 store.",
        ],
    }


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


def freeze_calibration_storage_baseline(report_set_path: Path, output_path: Path) -> Path:
    """Load qualified evidence and atomically write a non-overwriting baseline."""

    source = report_set_path.resolve()
    if not source.is_file():
        raise CalibrationStorageBaselineError(f"report set does not exist: {source}")
    if output_path.exists():
        raise CalibrationStorageBaselineError(f"refusing to overwrite: {output_path}")
    report_set = load_report_set(source)
    measured_references = report_set["runs"]["measured"]
    measured_reports = []
    for reference in measured_references:
        raw_path = _resolve_raw_report(source, reference)
        if _sha256(raw_path) != reference.get("sha256"):
            raise CalibrationStorageBaselineError(f"raw report hash mismatch: {raw_path}")
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise CalibrationStorageBaselineError(f"raw report is not an object: {raw_path}")
        measured_reports.append(payload)
    baseline = create_calibration_storage_baseline(
        report_set,
        measured_reports,
        report_set_sha256=_sha256(source),
    )
    output = output_path.resolve()
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
        if output.exists():
            raise CalibrationStorageBaselineError(f"refusing to overwrite: {output}")
        os.replace(temporary_name, output)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze a candidate Pi baseline for calibration storage."
    )
    parser.add_argument("--report-set", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        output = freeze_calibration_storage_baseline(
            arguments.report_set, arguments.output
        )
    except (CalibrationStorageBaselineError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASELINE_ID",
    "CLOCK_RESOLUTION_FLOORS_MS",
    "CalibrationStorageBaselineError",
    "candidate_upper_limit",
    "create_calibration_storage_baseline",
    "freeze_calibration_storage_baseline",
]
