from __future__ import annotations

import importlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


REPORT_SCHEMA_NAME = "labcraft.virtual_workflow_report"
REPORT_SCHEMA_VERSION = 1

REQUIRED_TOP_LEVEL_FIELDS = {
    "schema_name",
    "schema_version",
    "run",
    "source",
    "environment",
    "safety",
    "workload",
    "metrics",
    "artifacts",
    "classification",
    "limitations",
}
METRIC_GROUPS = {
    "responsiveness",
    "workflow",
    "queue",
    "persistence",
    "resources",
}
METRIC_STATUSES = {
    "measured",
    "partial",
    "not_available",
    "not_applicable",
}
CLASSIFICATION_STATUSES = {"pass", "warning", "fail"}
THRESHOLD_MATURITIES = {"informational", "candidate", "acceptance"}
INTERACTION_SURFACES = {"ui", "controller", "model", "simulator", "harness"}


class ReportValidationError(ValueError):
    """Raised when a virtual-workflow report violates its versioned contract."""


def validate_interaction_surface_claims(
    action_results: list[Mapping[str, Any]],
    *,
    required_ui_action_ids: set[str] | frozenset[str] = frozenset(),
) -> None:
    """Fail closed when a composed run overstates normal-UI coverage."""
    observed: dict[str, set[str]] = {}
    for index, row in enumerate(action_results):
        if not isinstance(row, Mapping):
            raise ReportValidationError(f"action_results[{index}] must be an object")
        action_id = row.get("action_id")
        surface = row.get("interaction_surface")
        if not isinstance(action_id, str) or not action_id:
            raise ReportValidationError(
                f"action_results[{index}].action_id must be a non-empty string"
            )
        if surface not in INTERACTION_SURFACES:
            raise ReportValidationError(
                f"action {action_id} has invalid interaction_surface {surface!r}"
            )
        observed.setdefault(action_id, set()).add(str(surface))

    missing = sorted(required_ui_action_ids - set(observed))
    non_ui = sorted(
        action_id
        for action_id in required_ui_action_ids & set(observed)
        if observed[action_id] != {"ui"}
    )
    if missing or non_ui:
        details = []
        if missing:
            details.append("missing actions: " + ", ".join(missing))
        if non_ui:
            details.append("non-UI actions: " + ", ".join(non_ui))
        raise ReportValidationError(
            "normal-UI interaction claim failed; " + "; ".join(details)
        )


def _git(repo_root: Path, *args: str) -> tuple[str | None, str | None]:
    command = [
        "git",
        "-c",
        f"safe.directory={repo_root.as_posix()}",
        *args,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip() or "git command failed"
    return result.stdout.strip(), None


def _qt_identity() -> dict[str, Any]:
    result: dict[str, Any] = {
        "binding": "missing",
        "pyside_version": None,
        "qt_version": None,
        "module_path": None,
        "platform": os.environ.get("QT_QPA_PLATFORM"),
    }
    try:
        pyside = importlib.import_module("PySide6")
        qtcore = importlib.import_module("PySide6.QtCore")
    except (ImportError, ModuleNotFoundError):
        return result

    module_path = getattr(pyside, "__file__", None)
    pyside_version = getattr(pyside, "__version__", None)
    q_version = getattr(qtcore, "qVersion", None)
    result.update(
        {
            "binding": (
                "real"
                if module_path and pyside_version and callable(q_version)
                else "stub"
            ),
            "pyside_version": (
                str(pyside_version) if pyside_version is not None else None
            ),
            "qt_version": str(q_version()) if callable(q_version) else None,
            "module_path": str(module_path) if module_path else None,
        }
    )
    return result


def collect_environment_identity(repo_root: str | Path) -> dict[str, dict[str, Any]]:
    """Collect source and host identity without initializing a Qt application."""
    root = Path(repo_root).resolve()
    commit, commit_error = _git(root, "rev-parse", "HEAD")
    status, status_error = _git(root, "status", "--porcelain", "--untracked-files=all")
    git_error = commit_error or status_error
    source = {
        "git_commit": commit,
        "git_short_commit": commit[:12] if commit else None,
        "dirty_worktree": bool(status) if status is not None else None,
        "git_error": git_error,
    }
    environment = {
        "operating_system": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "cpu_identifier": (
            platform.processor()
            or os.environ.get("PROCESSOR_IDENTIFIER")
            or "unknown"
        ),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": str(Path(sys.executable).resolve()),
        "qt": _qt_identity(),
    }
    return {"source": source, "environment": environment}


def _require_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ReportValidationError(f"{key} must be an object")
    return value


def _validate_utc_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReportValidationError(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReportValidationError(
            f"{field} must be an ISO-8601 UTC timestamp"
        ) from exc


def validate_report_v1(payload: Mapping[str, Any]) -> None:
    """Validate the stable v1 envelope while allowing scenario metric values."""
    if not isinstance(payload, Mapping):
        raise ReportValidationError("report must be an object")
    fields = set(payload)
    missing = REQUIRED_TOP_LEVEL_FIELDS - fields
    unknown = fields - REQUIRED_TOP_LEVEL_FIELDS
    if missing:
        raise ReportValidationError(
            "missing top-level fields: " + ", ".join(sorted(missing))
        )
    if unknown:
        raise ReportValidationError(
            "unknown top-level fields: " + ", ".join(sorted(unknown))
        )
    if payload["schema_name"] != REPORT_SCHEMA_NAME:
        raise ReportValidationError("unsupported schema_name")
    if payload["schema_version"] != REPORT_SCHEMA_VERSION:
        raise ReportValidationError("unsupported schema_version")

    run = _require_mapping(payload, "run")
    for key in (
        "run_id",
        "scenario_name",
        "scenario_version",
        "run_mode",
        "timing_policy",
    ):
        if not isinstance(run.get(key), str) or not run[key]:
            raise ReportValidationError(f"run.{key} must be a non-empty string")
    for key in ("warmup_runs", "measured_runs"):
        value = run.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ReportValidationError(f"run.{key} must be a non-negative integer")
    duration = run.get("duration_ms")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
        raise ReportValidationError("run.duration_ms must be non-negative")
    _validate_utc_timestamp(run.get("started_at_utc"), "run.started_at_utc")
    _validate_utc_timestamp(run.get("ended_at_utc"), "run.ended_at_utc")

    _require_mapping(payload, "source")
    _require_mapping(payload, "environment")
    safety = _require_mapping(payload, "safety")
    if safety.get("simulation") is not True:
        raise ReportValidationError("safety.simulation must be true")
    if safety.get("hardware_access_allowed") is not False:
        raise ReportValidationError("safety.hardware_access_allowed must be false")
    interfaces = safety.get("hardware_interfaces")
    if not isinstance(interfaces, Mapping) or not interfaces:
        raise ReportValidationError("safety.hardware_interfaces must be a non-empty object")
    if any(value is not False for value in interfaces.values()):
        raise ReportValidationError("every safety hardware interface must be false")

    _require_mapping(payload, "workload")
    metrics = _require_mapping(payload, "metrics")
    missing_metrics = METRIC_GROUPS - set(metrics)
    unknown_metrics = set(metrics) - METRIC_GROUPS
    if missing_metrics or unknown_metrics:
        details = []
        if missing_metrics:
            details.append("missing " + ", ".join(sorted(missing_metrics)))
        if unknown_metrics:
            details.append("unknown " + ", ".join(sorted(unknown_metrics)))
        raise ReportValidationError("invalid metric groups: " + "; ".join(details))
    for name in sorted(METRIC_GROUPS):
        group = metrics[name]
        if not isinstance(group, Mapping):
            raise ReportValidationError(f"metrics.{name} must be an object")
        if group.get("status") not in METRIC_STATUSES:
            raise ReportValidationError(f"metrics.{name}.status is invalid")
        if not isinstance(group.get("values"), Mapping):
            raise ReportValidationError(f"metrics.{name}.values must be an object")

    _require_mapping(payload, "artifacts")
    classification = _require_mapping(payload, "classification")
    if classification.get("status") not in CLASSIFICATION_STATUSES:
        raise ReportValidationError("classification.status is invalid")
    if classification.get("threshold_maturity") not in THRESHOLD_MATURITIES:
        raise ReportValidationError("classification.threshold_maturity is invalid")
    reasons = classification.get("reasons")
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise ReportValidationError("classification.reasons must be a list of strings")
    limitations = payload["limitations"]
    if not isinstance(limitations, list) or any(
        not isinstance(item, str) for item in limitations
    ):
        raise ReportValidationError("limitations must be a list of strings")


def write_report_atomic(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Validate and durably replace a report JSON file."""
    validate_report_v1(payload)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination
