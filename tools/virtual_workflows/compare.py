from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from numbers import Real
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tools.virtual_workflows.metrics import percentile
from tools.virtual_workflows.report import validate_report_v1


REPORT_SET_SCHEMA_NAME = "labcraft.virtual_workflow_report_set"
BASELINE_SCHEMA_NAME = "labcraft.virtual_workflow_baseline"
COMPARISON_SCHEMA_NAME = "labcraft.virtual_workflow_comparison"
COMPARISON_SCHEMA_VERSION = 1
POLICY_VERSION = "virtual_workflow_policy_v1"
DEFAULT_METRIC_PROFILE = "virtual_print_array_v1"
CALIBRATION_STORAGE_METRIC_PROFILE = "calibration_storage_reference_v1"
CALIBRATION_STORAGE_WORKLOAD_ID = "calibration_storage_legacy_baseline_8x25_v1"
CALIBRATION_STORAGE_SHADOW_WORKLOAD_ID = "calibration_storage_shadow_8x25_v1"
CALIBRATION_STORAGE_AUTHORITATIVE_WORKLOAD_ID = (
    "calibration_storage_authoritative_8x25_v1"
)
CALIBRATION_STORAGE_PRIMARY_READER_WORKLOAD_ID = (
    "calibration_storage_primary_reader_8x25_v1"
)
CALIBRATION_STORAGE_SECONDARY_READER_WORKLOAD_ID = (
    "calibration_storage_secondary_reader_8x25_v1"
)
CALIBRATION_STORAGE_HISTORICAL_CONVERSION_WORKLOAD_ID = (
    "calibration_storage_historical_conversion_contract_v1"
)
CALIBRATION_STORAGE_WORKLOAD_IDS = frozenset(
    {
        CALIBRATION_STORAGE_WORKLOAD_ID,
        CALIBRATION_STORAGE_SHADOW_WORKLOAD_ID,
        CALIBRATION_STORAGE_AUTHORITATIVE_WORKLOAD_ID,
        CALIBRATION_STORAGE_PRIMARY_READER_WORKLOAD_ID,
        CALIBRATION_STORAGE_SECONDARY_READER_WORKLOAD_ID,
        CALIBRATION_STORAGE_HISTORICAL_CONVERSION_WORKLOAD_ID,
    }
)

PRIMARY_METRICS = (
    "metrics.responsiveness.values.scheduling_lateness_ms.p95",
    "metrics.responsiveness.values.scheduling_lateness_ms.p99",
)
SECONDARY_METRICS = (
    "metrics.responsiveness.values.phase_timings.duration_by_name_ms."
    "controller.well_completion.p95",
    "metrics.responsiveness.values.phase_timings.duration_by_name_ms."
    "ui.well_plate_update.p95",
    "metrics.responsiveness.values.phase_timings.duration_by_name_ms."
    "persistence.write_progress.p95",
    "metrics.responsiveness.values.phase_timings.duration_by_name_ms."
    "persistence.complete_intent.p95",
    "run.duration_ms",
)
SERVICE_GAP_MAXIMUM = (
    "metrics.responsiveness.values.event_loop_gap_ms.maximum"
)
SCHEDULING_LATENESS_P99 = (
    "metrics.responsiveness.values.scheduling_lateness_ms.p99"
)
ALL_METRICS = PRIMARY_METRICS + SECONDARY_METRICS + (SERVICE_GAP_MAXIMUM,)


class ComparisonError(ValueError):
    """Raised when comparison input or output violates its contract."""


class ComparisonIncompleteError(ComparisonError):
    """Raised when required evidence is absent or not comparison-ready."""


@dataclass(frozen=True)
class ComparisonPolicy:
    policy_version: str = POLICY_VERSION
    minimum_warmup_runs: int = 1
    minimum_measured_runs: int = 5
    relative_regression_ratio: float = 1.25
    primary_absolute_noise_floor_ms: float = 10.0
    secondary_absolute_noise_floor_ms: float = 5.0
    duration_absolute_noise_floor_ms: float = 1000.0
    robust_noise_multiplier: float = 3.0
    maximum_primary_cv: float = 0.30
    absolute_warning_service_gap_ms: float = 250.0
    absolute_failure_service_gap_ms: float = 1000.0
    absolute_failure_lateness_p99_ms: float = 250.0

    def __post_init__(self) -> None:
        if not self.policy_version:
            raise ValueError("policy_version must be non-empty")
        if self.minimum_warmup_runs < 0 or self.minimum_measured_runs < 1:
            raise ValueError("run-count requirements are invalid")
        if self.relative_regression_ratio <= 1.0:
            raise ValueError("relative_regression_ratio must exceed 1")
        for value in (
            self.primary_absolute_noise_floor_ms,
            self.secondary_absolute_noise_floor_ms,
            self.duration_absolute_noise_floor_ms,
            self.robust_noise_multiplier,
            self.maximum_primary_cv,
            self.absolute_warning_service_gap_ms,
            self.absolute_failure_service_gap_ms,
            self.absolute_failure_lateness_p99_ms,
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError("comparison policy values must be finite and non-negative")
        if (
            self.absolute_failure_service_gap_ms
            <= self.absolute_warning_service_gap_ms
        ):
            raise ValueError("failure service-gap budget must exceed warning budget")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ComparisonError(f"{name} must be an object")
    return value


def _require_sequence(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ComparisonError(f"{name} must be an array")
    return value


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ComparisonIncompleteError(f"required metric {name} is not numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise ComparisonIncompleteError(f"required metric {name} is not finite")
    return converted


def _path_value(payload: Mapping[str, Any], dotted_path: str) -> Any:
    value: Any = payload
    parts = dotted_path.split(".")
    traversed: list[str] = []
    index = 0
    while index < len(parts):
        if not isinstance(value, Mapping):
            raise ComparisonIncompleteError(
                f"required metric {'.'.join(traversed + [parts[index]])} is missing"
            )
        matched_key: str | None = None
        matched_end = index
        for end in range(len(parts), index, -1):
            candidate = ".".join(parts[index:end])
            if candidate in value:
                matched_key = candidate
                matched_end = end
                break
        if matched_key is None:
            raise ComparisonIncompleteError(
                f"required metric {'.'.join(traversed + [parts[index]])} is missing"
            )
        traversed.append(matched_key)
        value = value[matched_key]
        index = matched_end
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _load_json(path: str | Path) -> tuple[Path, dict[str, Any]]:
    source = Path(path).resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonError(f"could not load {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ComparisonError(f"{source} must contain a JSON object")
    return source, payload


def _report_reference(
    path: Path,
    report: Mapping[str, Any],
    *,
    require_injected_stall: bool,
) -> dict[str, Any]:
    source = _require_mapping(report.get("source"), "report.source")
    run = _require_mapping(report.get("run"), "report.run")
    classification = _require_mapping(
        report.get("classification"), "report.classification"
    )
    injected = False
    if require_injected_stall:
        injected = _path_value(
            report,
            "metrics.responsiveness.values.injected_stall_assessment.requested",
        )
        if not isinstance(injected, bool):
            raise ComparisonIncompleteError(
                "injected_stall_assessment.requested must be boolean"
            )
    return {
        "path": _portable_path(path),
        "sha256": _sha256(path),
        "run_id": run["run_id"],
        "classification_status": classification["status"],
        "git_commit": source.get("git_commit"),
        "dirty_worktree": source.get("dirty_worktree"),
        "injected_stall": injected,
    }


def _compatibility_identity(
    report: Mapping[str, Any], host_label: str
) -> dict[str, Any]:
    run = _require_mapping(report.get("run"), "report.run")
    environment = _require_mapping(report.get("environment"), "report.environment")
    qt = _require_mapping(environment.get("qt"), "report.environment.qt")
    workload = _require_mapping(report.get("workload"), "report.workload")
    safety = _require_mapping(report.get("safety"), "report.safety")
    python_executable = environment.get("python_executable")
    if isinstance(python_executable, str) and python_executable:
        python_executable = _portable_path(Path(python_executable))
    identity = {
        "host_label": host_label,
        "report_schema_name": report["schema_name"],
        "report_schema_version": report["schema_version"],
        "scenario_name": run["scenario_name"],
        "scenario_version": run["scenario_version"],
        "run_mode": run["run_mode"],
        "timing_policy": run["timing_policy"],
        "environment": {
            "operating_system": environment.get("operating_system"),
            "os_release": environment.get("os_release"),
            "architecture": environment.get("architecture"),
            "cpu_identifier": environment.get("cpu_identifier"),
            "python_version": environment.get("python_version"),
            "python_implementation": environment.get("python_implementation"),
            "python_executable": python_executable,
            "qt": {
                "binding": qt.get("binding"),
                "pyside_version": qt.get("pyside_version"),
                "qt_version": qt.get("qt_version"),
                "platform": qt.get("platform"),
            },
        },
        "safety": {
            "simulation": safety.get("simulation"),
            "hardware_access_allowed": safety.get("hardware_access_allowed"),
            "hardware_interfaces": safety.get("hardware_interfaces"),
            "simulated_port": safety.get("simulated_port"),
        },
        "workload": dict(workload),
    }
    target_pi = environment.get("target_pi")
    if isinstance(target_pi, Mapping) and target_pi:
        identity["environment"]["target_pi"] = dict(target_pi)
    pi_sil = safety.get("pi_sil")
    if isinstance(pi_sil, Mapping) and pi_sil:
        identity["safety"]["pi_sil"] = {
            "sandbox_method": pi_sil.get("sandbox_method"),
            "private_dev": pi_sil.get("private_dev"),
            "root_read_only": pi_sil.get("root_read_only"),
            "network_unshared": pi_sil.get("network_unshared"),
        }
    return identity


def _metric_profile(identity: Mapping[str, Any]) -> str:
    workload = _require_mapping(identity.get("workload"), "compatibility.workload")
    if workload.get("workload_id") in CALIBRATION_STORAGE_WORKLOAD_IDS:
        return CALIBRATION_STORAGE_METRIC_PROFILE
    return DEFAULT_METRIC_PROFILE


def _distribution(values: Iterable[float]) -> dict[str, Any]:
    samples = [float(value) for value in values]
    if not samples:
        raise ComparisonIncompleteError("cannot summarize an empty metric series")
    mean = statistics.fmean(samples)
    median = statistics.median(samples)
    deviation = statistics.median(abs(value - median) for value in samples)
    standard_deviation = statistics.stdev(samples) if len(samples) > 1 else 0.0
    coefficient = (
        standard_deviation / abs(mean)
        if not math.isclose(mean, 0.0, abs_tol=1e-15)
        else (0.0 if math.isclose(standard_deviation, 0.0, abs_tol=1e-15) else None)
    )
    q1 = percentile(samples, 0.25)
    q3 = percentile(samples, 0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    outliers = [
        {"run_index": index, "value": value}
        for index, value in enumerate(samples)
        if value < lower or value > upper
    ]
    return {
        "count": len(samples),
        "mean": mean,
        "median": median,
        "minimum": min(samples),
        "maximum": max(samples),
        "standard_deviation": standard_deviation,
        "coefficient_of_variation": coefficient,
        "median_absolute_deviation": deviation,
        "q1": q1,
        "q3": q3,
        "tukey_outliers": outliers,
    }


def _extract_metrics(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for metric_path in ALL_METRICS:
        values = [
            _finite_number(_path_value(report, metric_path), metric_path)
            for report in reports
        ]
        result[metric_path] = {
            "per_run": values,
            "distribution": _distribution(values),
        }
    return result


def _load_reports(paths: Sequence[str | Path]) -> tuple[list[Path], list[dict[str, Any]]]:
    resolved: list[Path] = []
    reports: list[dict[str, Any]] = []
    for path in paths:
        report_path, report = _load_json(path)
        try:
            validate_report_v1(report)
        except ValueError as exc:
            raise ComparisonError(f"invalid report {report_path}: {exc}") from exc
        resolved.append(report_path)
        reports.append(report)
    return resolved, reports


def _validate_host_label(host_label: str) -> str:
    value = host_label.strip()
    if not value:
        raise ComparisonError("host_label must be non-empty")
    if len(value) > 100:
        raise ComparisonError("host_label must be at most 100 characters")
    return value


def build_report_set(
    report_paths: Sequence[str | Path],
    *,
    warmup_paths: Sequence[str | Path] = (),
    host_label: str,
) -> dict[str, Any]:
    """Build a versioned aggregate without blending individual run samples."""

    label = _validate_host_label(host_label)
    if not report_paths:
        raise ComparisonIncompleteError("at least one measured report is required")
    measured_paths, measured_reports = _load_reports(report_paths)
    resolved_warmups, warmup_reports = _load_reports(warmup_paths)
    all_paths = resolved_warmups + measured_paths
    all_reports = warmup_reports + measured_reports

    identity = _compatibility_identity(all_reports[0], label)
    for path, report in zip(all_paths[1:], all_reports[1:]):
        candidate_identity = _compatibility_identity(report, label)
        if candidate_identity != identity:
            raise ComparisonError(
                f"report {path} is incompatible with the first report in the set"
            )

    metric_profile = _metric_profile(identity)
    require_injected_stall = metric_profile == DEFAULT_METRIC_PROFILE

    warmup_references = [
        _report_reference(
            path, report, require_injected_stall=require_injected_stall
        )
        for path, report in zip(resolved_warmups, warmup_reports)
    ]
    measured_references = [
        _report_reference(
            path, report, require_injected_stall=require_injected_stall
        )
        for path, report in zip(measured_paths, measured_reports)
    ]
    all_references = warmup_references + measured_references
    failed = [
        reference
        for reference in all_references
        if reference["classification_status"] == "fail"
    ]
    sources = {
        (
            reference["git_commit"],
            reference["dirty_worktree"],
        )
        for reference in all_references
    }
    if metric_profile == DEFAULT_METRIC_PROFILE:
        metrics = _extract_metrics(measured_reports)
        noisy_metrics = [
            metric_path
            for metric_path in PRIMARY_METRICS
            if (
                metrics[metric_path]["distribution"]["coefficient_of_variation"]
                is None
                or metrics[metric_path]["distribution"]["coefficient_of_variation"]
                > ComparisonPolicy().maximum_primary_cv
            )
        ]
        noise = {
            "maximum_primary_cv": ComparisonPolicy().maximum_primary_cv,
            "noisy_primary_metrics": noisy_metrics,
            "status": "noisy" if noisy_metrics else "acceptable",
        }
    else:
        metrics = {}
        noise = {
            "maximum_primary_cv": None,
            "noisy_primary_metrics": [],
            "status": "not_applicable",
        }
    return {
        "schema_name": REPORT_SET_SCHEMA_NAME,
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "host_label": label,
        "metric_profile": metric_profile,
        "compatibility": identity,
        "source_summary": {
            "sources": [
                {"git_commit": commit, "dirty_worktree": dirty}
                for commit, dirty in sorted(
                    sources, key=lambda item: (str(item[0]), str(item[1]))
                )
            ],
            "any_dirty_worktree": any(
                reference["dirty_worktree"] is not False
                for reference in all_references
            ),
        },
        "runs": {
            "warmup_count": len(warmup_references),
            "measured_count": len(measured_references),
            "warmups": warmup_references,
            "measured": measured_references,
        },
        "functional": {
            "status": "fail" if failed else "pass",
            "failed_run_ids": [reference["run_id"] for reference in failed],
        },
        "synthetic": {
            "warmup_injected_count": sum(
                bool(reference["injected_stall"])
                for reference in warmup_references
            ),
            "measured_injected_count": sum(
                bool(reference["injected_stall"])
                for reference in measured_references
            ),
        },
        "metrics": metrics,
        "noise": noise,
    }


def _validate_report_reference_metadata(reference: Mapping[str, Any]) -> None:
    path_value = reference.get("path")
    expected_hash = reference.get("sha256")
    if not isinstance(path_value, str) or not path_value:
        raise ComparisonError("raw report reference path is invalid")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ComparisonError("raw report reference hash is invalid")


def _validate_report_reference(reference: Mapping[str, Any]) -> None:
    _validate_report_reference_metadata(reference)
    path_value = reference["path"]
    expected_hash = reference["sha256"]
    path = Path(path_value)
    if not path.is_file():
        raise ComparisonIncompleteError(f"referenced raw report is missing: {path}")
    actual_hash = _sha256(path)
    if actual_hash != expected_hash:
        raise ComparisonError(f"raw report hash mismatch: {path}")


def validate_report_set(payload: Mapping[str, Any], *, verify_hashes: bool = True) -> None:
    if payload.get("schema_name") != REPORT_SET_SCHEMA_NAME:
        raise ComparisonError("unsupported report-set schema_name")
    if payload.get("schema_version") != COMPARISON_SCHEMA_VERSION:
        raise ComparisonError("unsupported report-set schema_version")
    _validate_host_label(str(payload.get("host_label") or ""))
    compatibility = _require_mapping(
        payload.get("compatibility"), "report_set.compatibility"
    )
    metric_profile = payload.get("metric_profile", DEFAULT_METRIC_PROFILE)
    if metric_profile not in {
        DEFAULT_METRIC_PROFILE,
        CALIBRATION_STORAGE_METRIC_PROFILE,
    }:
        raise ComparisonError("report-set metric profile is invalid")
    if metric_profile == CALIBRATION_STORAGE_METRIC_PROFILE:
        workload = _require_mapping(
            compatibility.get("workload"), "report_set.compatibility.workload"
        )
        if workload.get("workload_id") not in CALIBRATION_STORAGE_WORKLOAD_IDS:
            raise ComparisonError("storage metric profile has the wrong workload")
    runs = _require_mapping(payload.get("runs"), "report_set.runs")
    warmups = _require_sequence(runs.get("warmups"), "report_set.runs.warmups")
    measured = _require_sequence(runs.get("measured"), "report_set.runs.measured")
    if runs.get("warmup_count") != len(warmups):
        raise ComparisonError("report-set warmup_count does not match references")
    if runs.get("measured_count") != len(measured) or not measured:
        raise ComparisonError("report-set measured_count does not match references")
    functional = _require_mapping(payload.get("functional"), "report_set.functional")
    if functional.get("status") not in {"pass", "fail"}:
        raise ComparisonError("report-set functional status is invalid")
    metrics = _require_mapping(payload.get("metrics"), "report_set.metrics")
    if metric_profile == DEFAULT_METRIC_PROFILE:
        for metric_path in ALL_METRICS:
            metric = _require_mapping(metrics.get(metric_path), f"metrics.{metric_path}")
            values = _require_sequence(metric.get("per_run"), f"{metric_path}.per_run")
            if len(values) != len(measured):
                raise ComparisonError(f"{metric_path} does not preserve measured runs")
            for index, value in enumerate(values):
                _finite_number(value, f"{metric_path}[{index}]")
            _require_mapping(metric.get("distribution"), f"{metric_path}.distribution")
    elif metrics:
        raise ComparisonError("storage reference report sets must not contain generic metrics")
    if verify_hashes:
        for raw_reference in list(warmups) + list(measured):
            _validate_report_reference(
                _require_mapping(raw_reference, "raw report reference")
            )


def _compact_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for metric_path in ALL_METRICS:
        metric = _require_mapping(metrics.get(metric_path), metric_path)
        compact[metric_path] = {
            "distribution": dict(
                _require_mapping(metric.get("distribution"), metric_path)
            )
        }
    return compact


def create_baseline_summary(
    report_set: Mapping[str, Any],
    *,
    maturity: str,
    policy: ComparisonPolicy | None = None,
) -> dict[str, Any]:
    """Create compact, tracked evidence from a clean compatible report set."""

    selected_policy = policy or ComparisonPolicy()
    validate_report_set(report_set)
    if report_set.get("metric_profile", DEFAULT_METRIC_PROFILE) != DEFAULT_METRIC_PROFILE:
        raise ComparisonIncompleteError(
            "the generic baseline builder does not support this metric profile"
        )
    if maturity not in {"candidate", "acceptance"}:
        raise ComparisonError("baseline maturity must be candidate or acceptance")
    runs = _require_mapping(report_set["runs"], "report_set.runs")
    if runs["warmup_count"] < selected_policy.minimum_warmup_runs:
        raise ComparisonIncompleteError(
            f"baseline requires at least {selected_policy.minimum_warmup_runs} warm-up run"
        )
    if runs["measured_count"] < selected_policy.minimum_measured_runs:
        raise ComparisonIncompleteError(
            "baseline requires at least "
            f"{selected_policy.minimum_measured_runs} measured runs"
        )
    functional = _require_mapping(report_set["functional"], "report_set.functional")
    if functional["status"] != "pass":
        raise ComparisonError("a functional failure cannot become a baseline")
    source_summary = _require_mapping(
        report_set["source_summary"], "report_set.source_summary"
    )
    sources = _require_sequence(source_summary.get("sources"), "source_summary.sources")
    if source_summary.get("any_dirty_worktree") is not False:
        raise ComparisonError("accepted baseline reports must have clean worktrees")
    if len(sources) != 1:
        raise ComparisonError("accepted baseline reports must use one source commit")
    source = _require_mapping(sources[0], "source_summary.sources[0]")
    if source.get("dirty_worktree") is not False or not source.get("git_commit"):
        raise ComparisonError("accepted baseline source identity is invalid")
    synthetic = _require_mapping(report_set["synthetic"], "report_set.synthetic")
    if synthetic.get("warmup_injected_count") or synthetic.get(
        "measured_injected_count"
    ):
        raise ComparisonError("accepted baselines cannot contain injected stalls")
    noise = _require_mapping(report_set["noise"], "report_set.noise")
    if noise.get("status") != "acceptable":
        raise ComparisonIncompleteError("noisy report sets cannot become baselines")

    references = [
        {
            "path": reference["path"],
            "sha256": reference["sha256"],
            "run_id": reference["run_id"],
        }
        for reference in list(runs["warmups"]) + list(runs["measured"])
    ]
    baseline = {
        "schema_name": BASELINE_SCHEMA_NAME,
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "baseline_id": (
            f"{report_set['compatibility']['workload']['workload_id']}"
            f"_{report_set['host_label']}"
        ),
        "threshold_maturity": maturity,
        "policy": asdict(selected_policy),
        "host_label": report_set["host_label"],
        "compatibility": report_set["compatibility"],
        "source": dict(source),
        "runs": {
            "warmup_count": runs["warmup_count"],
            "measured_count": runs["measured_count"],
            "raw_reports": references,
        },
        "metrics": _compact_metrics(
            _require_mapping(report_set["metrics"], "report_set.metrics")
        ),
        "noise": report_set["noise"],
        "classification": {
            "status": "pass",
            "threshold_maturity": maturity,
            "reasons": [
                "All baseline functional invariants passed.",
                "Primary cross-run variation satisfied the candidate noise policy.",
            ],
        },
    }
    validate_baseline_summary(baseline, verify_hashes=True)
    return baseline


def validate_baseline_summary(
    payload: Mapping[str, Any], *, verify_hashes: bool = False
) -> None:
    if payload.get("schema_name") != BASELINE_SCHEMA_NAME:
        raise ComparisonError("unsupported baseline schema_name")
    if payload.get("schema_version") != COMPARISON_SCHEMA_VERSION:
        raise ComparisonError("unsupported baseline schema_version")
    if payload.get("threshold_maturity") not in {"candidate", "acceptance"}:
        raise ComparisonError("baseline threshold_maturity is invalid")
    policy = _require_mapping(payload.get("policy"), "baseline.policy")
    if policy.get("policy_version") != POLICY_VERSION:
        raise ComparisonError("baseline policy version is incompatible")
    _require_mapping(payload.get("compatibility"), "baseline.compatibility")
    source = _require_mapping(payload.get("source"), "baseline.source")
    if source.get("dirty_worktree") is not False or not source.get("git_commit"):
        raise ComparisonError("baseline must identify one clean source commit")
    runs = _require_mapping(payload.get("runs"), "baseline.runs")
    references = _require_sequence(
        runs.get("raw_reports"), "baseline.runs.raw_reports"
    )
    expected_count = runs.get("warmup_count", 0) + runs.get("measured_count", 0)
    if expected_count != len(references):
        raise ComparisonError("baseline raw report count is inconsistent")
    metrics = _require_mapping(payload.get("metrics"), "baseline.metrics")
    for metric_path in ALL_METRICS:
        metric = _require_mapping(metrics.get(metric_path), metric_path)
        _require_mapping(metric.get("distribution"), f"{metric_path}.distribution")
    for reference in references:
        validated = _require_mapping(reference, "raw report reference")
        _validate_report_reference_metadata(validated)
        if verify_hashes:
            _validate_report_reference(validated)


def _distribution_for(
    payload: Mapping[str, Any], metric_path: str
) -> Mapping[str, Any]:
    metrics = _require_mapping(payload.get("metrics"), "metrics")
    metric = _require_mapping(metrics.get(metric_path), metric_path)
    return _require_mapping(metric.get("distribution"), f"{metric_path}.distribution")


def _candidate_noisy_metrics(
    candidate: Mapping[str, Any], policy: ComparisonPolicy
) -> list[str]:
    noisy: list[str] = []
    for metric_path in PRIMARY_METRICS:
        distribution = _distribution_for(candidate, metric_path)
        cv = distribution.get("coefficient_of_variation")
        if (
            isinstance(cv, bool)
            or not isinstance(cv, Real)
            or not math.isfinite(float(cv))
            or float(cv) > policy.maximum_primary_cv
        ):
            noisy.append(metric_path)
    return noisy


def _relative_rule(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    metric_path: str,
    category: str,
    fixed_floor_ms: float,
    policy: ComparisonPolicy,
) -> dict[str, Any]:
    baseline_distribution = _distribution_for(baseline, metric_path)
    candidate_distribution = _distribution_for(candidate, metric_path)
    baseline_value = _finite_number(
        baseline_distribution.get("median"), f"baseline {metric_path}.median"
    )
    candidate_value = _finite_number(
        candidate_distribution.get("median"), f"candidate {metric_path}.median"
    )
    baseline_mad = _finite_number(
        baseline_distribution.get("median_absolute_deviation"),
        f"baseline {metric_path}.median_absolute_deviation",
    )
    candidate_mad = _finite_number(
        candidate_distribution.get("median_absolute_deviation"),
        f"candidate {metric_path}.median_absolute_deviation",
    )
    delta = candidate_value - baseline_value
    ratio = (
        candidate_value / baseline_value
        if not math.isclose(baseline_value, 0.0, abs_tol=1e-15)
        else (1.0 if math.isclose(candidate_value, 0.0, abs_tol=1e-15) else None)
    )
    effective_floor = max(
        fixed_floor_ms,
        policy.robust_noise_multiplier * baseline_mad,
        policy.robust_noise_multiplier * candidate_mad,
    )
    regression = (
        (
            ratio is None
            or ratio > policy.relative_regression_ratio
        )
        and delta > effective_floor
    )
    return {
        "rule_type": "relative",
        "category": category,
        "metric_path": metric_path,
        "baseline_median": baseline_value,
        "candidate_median": candidate_value,
        "ratio": ratio,
        "absolute_delta_ms": delta,
        "fixed_noise_floor_ms": fixed_floor_ms,
        "effective_noise_floor_ms": effective_floor,
        "relative_regression_ratio": policy.relative_regression_ratio,
        "regression": regression,
        "decision": "regression" if regression else "pass",
    }


def _comparison_shell(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    policy: ComparisonPolicy,
) -> dict[str, Any]:
    runs = _require_mapping(candidate.get("runs"), "candidate.runs")
    synthetic = _require_mapping(candidate.get("synthetic"), "candidate.synthetic")
    return {
        "schema_name": COMPARISON_SCHEMA_NAME,
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "policy": asdict(policy),
        "baseline": {
            "baseline_id": baseline.get("baseline_id"),
            "source": baseline.get("source"),
            "host_label": baseline.get("host_label"),
            "threshold_maturity": baseline.get("threshold_maturity"),
        },
        "candidate": {
            "source_summary": candidate.get("source_summary"),
            "host_label": candidate.get("host_label"),
            "warmup_count": runs.get("warmup_count"),
            "measured_count": runs.get("measured_count"),
            "synthetic": dict(synthetic),
        },
        "compatibility": {"status": "compatible", "differences": []},
        "noise": {"status": "acceptable", "noisy_primary_metrics": []},
        "functional": {"status": "pass", "failed_run_ids": []},
        "rules": [],
        "classification": {
            "functional_status": "pass",
            "performance_status": "pass",
            "overall_status": "pass",
            "threshold_maturity": baseline.get("threshold_maturity"),
            "reasons": [],
        },
    }


def _identity_differences(
    baseline_identity: Mapping[str, Any],
    candidate_identity: Mapping[str, Any],
) -> list[str]:
    if baseline_identity == candidate_identity:
        return []
    baseline_text = json.dumps(baseline_identity, sort_keys=True, separators=(",", ":"))
    candidate_text = json.dumps(candidate_identity, sort_keys=True, separators=(",", ":"))
    if baseline_text == candidate_text:
        return []

    differences: list[str] = []

    def walk(left: Any, right: Any, prefix: str) -> None:
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            for key in sorted(set(left) | set(right)):
                child = f"{prefix}.{key}" if prefix else str(key)
                if key not in left or key not in right:
                    differences.append(child)
                else:
                    walk(left[key], right[key], child)
            return
        if left != right:
            differences.append(prefix)

    walk(baseline_identity, candidate_identity, "")
    return differences


def compare_report_sets(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    policy: ComparisonPolicy | None = None,
) -> dict[str, Any]:
    """Compare a compact baseline with a compatible candidate report set."""

    validate_baseline_summary(baseline)
    validate_report_set(candidate)
    if candidate.get("metric_profile", DEFAULT_METRIC_PROFILE) != DEFAULT_METRIC_PROFILE:
        raise ComparisonIncompleteError(
            "the generic comparison engine does not support this metric profile"
        )
    try:
        baseline_policy = ComparisonPolicy(**dict(baseline["policy"]))
    except (TypeError, ValueError) as exc:
        raise ComparisonError(f"baseline policy is invalid: {exc}") from exc
    selected_policy = policy or baseline_policy
    if asdict(baseline_policy) != asdict(selected_policy):
        raise ComparisonError("selected policy does not exactly match the baseline")

    result = _comparison_shell(baseline, candidate, selected_policy)
    classification = result["classification"]
    maturity = baseline["threshold_maturity"]
    baseline_identity = _require_mapping(
        baseline["compatibility"], "baseline.compatibility"
    )
    candidate_identity = _require_mapping(
        candidate["compatibility"], "candidate.compatibility"
    )
    differences = _identity_differences(baseline_identity, candidate_identity)
    if differences:
        result["compatibility"] = {
            "status": "incompatible",
            "differences": differences,
        }
        classification.update(
            {
                "performance_status": "not_evaluated",
                "overall_status": "incomplete",
                "reasons": [
                    "Baseline and candidate compatibility identities differ: "
                    + ", ".join(differences)
                ],
            }
        )
        validate_comparison(result)
        return result

    candidate_runs = _require_mapping(candidate["runs"], "candidate.runs")
    if (
        candidate_runs["warmup_count"] < selected_policy.minimum_warmup_runs
        or candidate_runs["measured_count"] < selected_policy.minimum_measured_runs
    ):
        classification.update(
            {
                "performance_status": "not_evaluated",
                "overall_status": "incomplete",
                "reasons": [
                    "Candidate lacks the required warm-up and measured run counts."
                ],
            }
        )
        validate_comparison(result)
        return result

    functional = _require_mapping(candidate["functional"], "candidate.functional")
    if functional["status"] == "fail":
        failed_ids = list(functional.get("failed_run_ids") or [])
        result["functional"] = {
            "status": "fail",
            "failed_run_ids": failed_ids,
        }
        classification.update(
            {
                "functional_status": "fail",
                "performance_status": "not_evaluated",
                "overall_status": "fail",
                "reasons": [
                    "Candidate contains functional workflow failures; "
                    "performance was not evaluated."
                ],
            }
        )
        validate_comparison(result)
        return result

    noisy_metrics = _candidate_noisy_metrics(candidate, selected_policy)
    if noisy_metrics:
        result["noise"] = {
            "status": "noisy",
            "noisy_primary_metrics": noisy_metrics,
        }
        classification.update(
            {
                "performance_status": "not_evaluated",
                "overall_status": "incomplete",
                "reasons": [
                    "Candidate primary-metric variation exceeds the "
                    f"{selected_policy.maximum_primary_cv:.0%} CV limit: "
                    + ", ".join(noisy_metrics)
                ],
            }
        )
        validate_comparison(result)
        return result

    rules: list[dict[str, Any]] = []
    for metric_path in PRIMARY_METRICS:
        rules.append(
            _relative_rule(
                baseline,
                candidate,
                metric_path=metric_path,
                category="primary",
                fixed_floor_ms=selected_policy.primary_absolute_noise_floor_ms,
                policy=selected_policy,
            )
        )
    for metric_path in SECONDARY_METRICS:
        floor = (
            selected_policy.duration_absolute_noise_floor_ms
            if metric_path == "run.duration_ms"
            else selected_policy.secondary_absolute_noise_floor_ms
        )
        rules.append(
            _relative_rule(
                baseline,
                candidate,
                metric_path=metric_path,
                category="secondary",
                fixed_floor_ms=floor,
                policy=selected_policy,
            )
        )

    service_gap = _distribution_for(candidate, SERVICE_GAP_MAXIMUM)
    service_gap_value = _finite_number(
        service_gap.get("maximum"), "candidate service-gap maximum"
    )
    gap_level = (
        "severe"
        if service_gap_value > selected_policy.absolute_failure_service_gap_ms
        else "warning"
        if service_gap_value > selected_policy.absolute_warning_service_gap_ms
        else "pass"
    )
    rules.append(
        {
            "rule_type": "absolute",
            "category": "primary",
            "metric_path": SERVICE_GAP_MAXIMUM,
            "candidate_maximum": service_gap_value,
            "warning_budget_ms": selected_policy.absolute_warning_service_gap_ms,
            "failure_budget_ms": selected_policy.absolute_failure_service_gap_ms,
            "regression": gap_level != "pass",
            "decision": gap_level,
        }
    )
    lateness = _distribution_for(candidate, SCHEDULING_LATENESS_P99)
    lateness_value = _finite_number(
        lateness.get("maximum"), "candidate scheduling-lateness p99 maximum"
    )
    lateness_severe = (
        lateness_value > selected_policy.absolute_failure_lateness_p99_ms
    )
    rules.append(
        {
            "rule_type": "absolute",
            "category": "primary",
            "metric_path": SCHEDULING_LATENESS_P99,
            "candidate_maximum": lateness_value,
            "failure_budget_ms": selected_policy.absolute_failure_lateness_p99_ms,
            "regression": lateness_severe,
            "decision": "severe" if lateness_severe else "pass",
        }
    )
    for rule in rules:
        rule["threshold_maturity"] = maturity
    result["rules"] = rules

    primary_relative = [
        rule
        for rule in rules
        if rule["rule_type"] == "relative"
        and rule["category"] == "primary"
        and rule["regression"]
    ]
    secondary = [
        rule
        for rule in rules
        if rule["category"] == "secondary" and rule["regression"]
    ]
    absolute_warning = gap_level == "warning"
    severe = gap_level == "severe" or lateness_severe
    warnings = bool(primary_relative or secondary or absolute_warning or severe)
    acceptance_failure = maturity == "acceptance" and bool(primary_relative or severe)

    reasons: list[str] = []
    if acceptance_failure:
        reasons.append(
            "Accepted primary responsiveness budget or relative regression gate failed."
        )
    elif warnings:
        reasons.append(
            "Candidate performance evidence crossed one or more warning rules."
        )
    else:
        reasons.append("Candidate remained within every comparison rule.")
    if secondary:
        reasons.append(
            "Secondary diagnostic regressions: "
            + ", ".join(rule["metric_path"] for rule in secondary)
        )
    if candidate["source_summary"].get("any_dirty_worktree"):
        reasons.append(
            "Candidate was collected from a dirty worktree; it is review evidence, "
            "not a release baseline."
        )
    if candidate["synthetic"].get("measured_injected_count"):
        reasons.append("Candidate contains explicitly injected synthetic UI stalls.")

    classification.update(
        {
            "performance_status": (
                "fail"
                if acceptance_failure
                else "warning"
                if warnings
                else "pass"
            ),
            "overall_status": (
                "fail"
                if acceptance_failure
                else "warning"
                if warnings
                else "pass"
            ),
            "reasons": reasons,
        }
    )
    validate_comparison(result)
    return result


def validate_comparison(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_name") != COMPARISON_SCHEMA_NAME:
        raise ComparisonError("unsupported comparison schema_name")
    if payload.get("schema_version") != COMPARISON_SCHEMA_VERSION:
        raise ComparisonError("unsupported comparison schema_version")
    _require_mapping(payload.get("policy"), "comparison.policy")
    _require_mapping(payload.get("baseline"), "comparison.baseline")
    _require_mapping(payload.get("candidate"), "comparison.candidate")
    compatibility = _require_mapping(
        payload.get("compatibility"), "comparison.compatibility"
    )
    if compatibility.get("status") not in {"compatible", "incompatible"}:
        raise ComparisonError("comparison compatibility status is invalid")
    _require_sequence(payload.get("rules"), "comparison.rules")
    classification = _require_mapping(
        payload.get("classification"), "comparison.classification"
    )
    if classification.get("overall_status") not in {
        "pass",
        "warning",
        "fail",
        "incomplete",
    }:
        raise ComparisonError("comparison overall status is invalid")
    if classification.get("threshold_maturity") not in {"candidate", "acceptance"}:
        raise ComparisonError("comparison threshold maturity is invalid")
    reasons = classification.get("reasons")
    if not isinstance(reasons, list) or any(
        not isinstance(reason, str) for reason in reasons
    ):
        raise ComparisonError("comparison reasons must be an array of strings")


def _write_json_atomic(
    path: str | Path,
    payload: Mapping[str, Any],
    *,
    replace: bool,
) -> Path:
    destination = Path(path)
    if destination.exists() and not replace:
        raise ComparisonError(
            f"refusing to overwrite existing comparison artifact: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def write_report_set(
    path: str | Path, payload: Mapping[str, Any], *, replace: bool = False
) -> Path:
    validate_report_set(payload)
    return _write_json_atomic(path, payload, replace=replace)


def write_baseline_summary(
    path: str | Path, payload: Mapping[str, Any], *, replace: bool = False
) -> Path:
    validate_baseline_summary(payload)
    return _write_json_atomic(path, payload, replace=replace)


def write_comparison(
    path: str | Path, payload: Mapping[str, Any], *, replace: bool = False
) -> Path:
    validate_comparison(payload)
    return _write_json_atomic(path, payload, replace=replace)


def comparison_markdown(payload: Mapping[str, Any]) -> str:
    validate_comparison(payload)
    classification = payload["classification"]
    lines = [
        "# Virtual Workflow Comparison",
        "",
        f"- Overall: `{classification['overall_status']}`",
        f"- Functional: `{classification['functional_status']}`",
        f"- Performance: `{classification['performance_status']}`",
        f"- Threshold maturity: `{classification['threshold_maturity']}`",
        f"- Compatibility: `{payload['compatibility']['status']}`",
        f"- Noise: `{payload['noise']['status']}`",
        "",
        "## Reasons",
        "",
    ]
    lines.extend(
        f"- {reason}" for reason in classification["reasons"]
    )
    if not classification["reasons"]:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Rules",
            "",
            "| Metric | Type | Baseline | Candidate | Delta | Ratio | Floor/Budget | Decision |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for rule in payload["rules"]:
        if rule["rule_type"] == "relative":
            lines.append(
                "| {metric} | {category} relative | {baseline:.3f} | "
                "{candidate:.3f} | {delta:.3f} | {ratio} | {floor:.3f} | "
                "{decision} |".format(
                    metric=rule["metric_path"],
                    category=rule["category"],
                    baseline=rule["baseline_median"],
                    candidate=rule["candidate_median"],
                    delta=rule["absolute_delta_ms"],
                    ratio=(
                        f"{rule['ratio']:.3f}"
                        if rule["ratio"] is not None
                        else "n/a"
                    ),
                    floor=rule["effective_noise_floor_ms"],
                    decision=rule["decision"],
                )
            )
        else:
            budget = (
                rule.get("warning_budget_ms")
                if rule.get("warning_budget_ms") is not None
                and rule["decision"] != "severe"
                else rule.get("failure_budget_ms")
                or rule.get("warning_budget_ms")
            )
            lines.append(
                f"| {rule['metric_path']} | absolute | n/a | "
                f"{rule['candidate_maximum']:.3f} | n/a | n/a | "
                f"{float(budget):.3f} | {rule['decision']} |"
            )
    return "\n".join(lines) + "\n"


def write_comparison_markdown(
    path: str | Path, payload: Mapping[str, Any], *, replace: bool = False
) -> Path:
    destination = Path(path)
    if destination.exists() and not replace:
        raise ComparisonError(f"refusing to overwrite {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(comparison_markdown(payload), encoding="utf-8")
    return destination


def load_report_set(path: str | Path) -> dict[str, Any]:
    _, payload = _load_json(path)
    validate_report_set(payload)
    return payload


def load_baseline_summary(path: str | Path) -> dict[str, Any]:
    _, payload = _load_json(path)
    validate_baseline_summary(payload)
    return payload


__all__ = [
    "BASELINE_SCHEMA_NAME",
    "COMPARISON_SCHEMA_NAME",
    "POLICY_VERSION",
    "REPORT_SET_SCHEMA_NAME",
    "ComparisonError",
    "ComparisonIncompleteError",
    "ComparisonPolicy",
    "build_report_set",
    "compare_report_sets",
    "comparison_markdown",
    "create_baseline_summary",
    "load_baseline_summary",
    "load_report_set",
    "validate_baseline_summary",
    "validate_comparison",
    "validate_report_set",
    "write_baseline_summary",
    "write_comparison",
    "write_comparison_markdown",
    "write_report_set",
]
