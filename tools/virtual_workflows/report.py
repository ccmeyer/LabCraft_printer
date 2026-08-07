from __future__ import annotations

import importlib
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
SOURCE_TREE_SCHEMA = "labcraft.source_tree_identity"
SOURCE_TREE_VERSION = 1
SOURCE_TREE_SCOPE = "git_tracked_and_nonignored_execution_inputs_v1"
_SOURCE_TREE_EXCLUDED_PARTS = {
    ".agents_tmp",
    ".git",
    ".pytest_cache",
    "__pycache__",
    "documentation",
    "docs",
    "verification_reports",
}
_SOURCE_TREE_EXCLUDED_NAMES = {"agents.md"}


class ReportValidationError(ValueError):
    """Raised when a virtual-workflow report violates its versioned contract."""


@dataclass(frozen=True)
class ComposedReportPayload:
    """Scenario-specific values inserted into the common report-v1 envelope."""

    workload: Mapping[str, Any]
    workflow_values: Mapping[str, Any] = field(default_factory=dict)
    workflow_status: str = "measured"
    queue: Mapping[str, Any] = field(
        default_factory=lambda: {"status": "not_applicable", "values": {}}
    )
    persistence: Mapping[str, Any] = field(
        default_factory=lambda: {"status": "not_applicable", "values": {}}
    )
    resources: Mapping[str, Any] = field(
        default_factory=lambda: {"status": "not_applicable", "values": {}}
    )
    responsiveness: Mapping[str, Any] = field(
        default_factory=lambda: {"status": "not_applicable", "values": {}}
    )
    classification: Mapping[str, Any] | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.workload, Mapping):
            raise ValueError("composed report workload must be a mapping")
        if self.workflow_status not in METRIC_STATUSES:
            raise ValueError("composed workflow status is invalid")


class ComposedReportAdapter:
    """Build the common envelope retained by every composed journey."""

    def __init__(self, harness: Any, *, repo_root: str | Path) -> None:
        self.harness = harness
        self.repo_root = Path(repo_root).resolve()

    def sections(
        self,
        *,
        workload_id: str,
        scenario_name: str,
        scenario_version: str,
        replay_command: list[str],
        passed: bool,
    ) -> dict[str, Any]:
        harness = self.harness
        identity = collect_environment_identity(self.repo_root)
        report_identity = dict(getattr(harness, "report_identity", {}) or {})
        if report_identity.get("target_pi") is not None:
            identity["environment"]["target_pi"] = report_identity["target_pi"]
        failure_text = str(harness.failure) if harness.failure is not None else None
        classification = "pass" if passed and failure_text is None else "fail"
        roots = getattr(harness.session, "application_roots", None)
        contained = bool(
            roots is not None
            and all(
                Path(value).resolve().is_relative_to(harness.scenario_root)
                for value in (
                    roots.config_root,
                    roots.experiments_root,
                    roots.calibration_memory_root,
                )
            )
        )
        return {
            "schema_name": REPORT_SCHEMA_NAME,
            "schema_version": REPORT_SCHEMA_VERSION,
            "run": {
                "run_id": harness.run_id,
                "scenario_name": str(scenario_name),
                "scenario_version": str(scenario_version),
                "run_mode": report_identity.get("run_mode") or (
                    "visible_windows_sil" if harness.config.visible else "offscreen_windows_sil"
                ),
                "timing_policy": (
                    "simulated_command_durations_x"
                    f"{harness.config.speed_multiplier:g}"
                ),
                "warmup_runs": 0,
                "measured_runs": 1,
                "started_at_utc": harness.started_at_utc,
                "ended_at_utc": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "duration_ms": harness.duration_ms,
                "seed": harness.config.seed,
                "replay_command": list(replay_command),
            },
            "source": identity["source"],
            "environment": identity["environment"],
            "safety": {
                "simulation": True,
                "hardware_access_allowed": False,
                "hardware_interfaces": {
                    "serial": False,
                    "GPIO": False,
                    "camera": False,
                    "balance": False,
                    "MCU": False,
                    "firmware_update": False,
                },
                "simulated_port": "SIMULATED",
                "scenario_root": str(harness.scenario_root),
                "report_dir": str(harness.report_dir),
                "root_containment_valid": contained,
                **(
                    {"pi_sil": report_identity["pi_sil"]}
                    if report_identity.get("pi_sil") is not None
                    else {}
                ),
            },
            "artifacts": {
                "report_json": "report.json",
                "summary_text": "summary.txt",
                "event_trace": "events.jsonl",
                "action_ledger": "action_ledger.json",
                "assertion_ledger": "assertion_ledger.json",
                "evidence_manifest": "evidence_manifest.json",
                "stall_stacks": (
                    "stall_stacks.txt"
                    if (harness.report_dir / "stall_stacks.txt").is_file()
                    else None
                ),
                "failure_traceback": (
                    "failure_traceback.txt" if harness.failure is not None else None
                ),
                "scenario_root": str(harness.scenario_root),
                "screenshots": {
                    name: path.resolve()
                    .relative_to(harness.report_dir.resolve())
                    .as_posix()
                    for name, path in sorted(harness.context.screenshots.items())
                },
            },
            "classification": {
                "status": classification,
                "threshold_maturity": "informational",
                "reasons": (
                    []
                    if classification == "pass"
                    else [failure_text or "required assertion failed"]
                ),
            },
        }

    def build(
        self,
        *,
        workload_id: str,
        scenario_name: str,
        scenario_version: str,
        replay_command: list[str],
        required_assertion_ids: tuple[str, ...],
        required_ui_action_ids: frozenset[str],
        payload: ComposedReportPayload,
    ) -> dict[str, Any]:
        """Build and validate one complete composed report-v1 document."""

        harness = self.harness
        decisions = {
            str(row.get("assertion_id")): str(row.get("decision"))
            for row in harness.assertion_results
        }
        passed = all(
            decisions.get(assertion_id) == "pass"
            for assertion_id in required_assertion_ids
        )
        report = self.sections(
            workload_id=workload_id,
            scenario_name=scenario_name,
            scenario_version=scenario_version,
            replay_command=replay_command,
            passed=passed,
        )
        common_workflow_values = {
            "action_results": list(harness.context.action_results),
            "assertion_results": list(harness.assertion_results),
            "lifecycle_milestones": list(harness.context.milestones),
            "dialogs": list(harness.context.dialogs),
            "unexpected_dialogs": list(harness.context.unexpected_dialogs),
            "errors": list(harness.context.errors),
            "interaction_surface_policy": "state-changing UI actions require QTest",
        }
        common_workflow_values.update(dict(payload.workflow_values))
        report.update(
            {
                "workload": dict(payload.workload),
                "metrics": {
                    "responsiveness": dict(payload.responsiveness),
                    "workflow": {
                        "status": payload.workflow_status,
                        "values": common_workflow_values,
                    },
                    "queue": dict(payload.queue),
                    "persistence": dict(payload.persistence),
                    "resources": dict(payload.resources),
                },
                "limitations": list(payload.limitations),
            }
        )
        if report["classification"]["status"] == "pass" and payload.classification:
            requested = dict(payload.classification)
            status = requested.get("status")
            reasons = requested.get("reasons", [])
            if status not in {"pass", "warning"}:
                raise ValueError("successful composed classification must be pass or warning")
            if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
                raise ValueError("composed classification reasons must be a list of strings")
            report["classification"].update(
                {"status": status, "reasons": reasons,
                 "threshold_maturity": "informational"}
            )
        actions = report["metrics"]["workflow"]["values"]["action_results"]
        observed = {str(row.get("action_id")) for row in actions}
        validate_interaction_surface_claims(
            actions,
            required_ui_action_ids=(
                required_ui_action_ids
                if report["classification"]["status"] == "pass"
                else required_ui_action_ids & observed
            ),
        )
        validate_report_v1(report)
        return report


def composed_report_contract_projection(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Select replay-stable composed fields for before/after parity checks."""

    validate_report_v1(report)
    workflow = report["metrics"]["workflow"]["values"]
    return {
        "schema_name": report["schema_name"],
        "schema_version": report["schema_version"],
        "scenario_name": report["run"]["scenario_name"],
        "scenario_version": report["run"]["scenario_version"],
        "seed": report["run"].get("seed"),
        "workload": dict(report["workload"]),
        "actions": [
            {
                "action_id": row.get("action_id"),
                "interaction_surface": row.get("interaction_surface"),
                "status": row.get("status"),
            }
            for row in workflow.get("action_results", [])
        ],
        "assertions": [
            {
                "assertion_id": row.get("assertion_id"),
                "decision": row.get("decision"),
            }
            for row in workflow.get("assertion_results", [])
        ],
        "milestones": [
            row.get("name") for row in workflow.get("lifecycle_milestones", [])
        ],
        "screenshot_names": sorted(report["artifacts"].get("screenshots", {})),
        "dialogs": list(workflow.get("dialogs", [])),
        "unexpected_dialogs": list(workflow.get("unexpected_dialogs", [])),
        "errors": list(workflow.get("errors", [])),
        "classification": report["classification"]["status"],
        "assertion_decisions": dict(
            report["metrics"]["persistence"]["values"].get(
                "assertion_decisions", {}
            )
        ),
    }


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


def _git_bytes(repo_root: Path, *args: str) -> tuple[bytes | None, str | None]:
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
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).decode(
            "utf-8", errors="replace"
        ).strip()
        return None, detail or "git command failed"
    return result.stdout, None


def _source_path_in_scope(relative_path: str) -> bool:
    path = Path(relative_path)
    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts & _SOURCE_TREE_EXCLUDED_PARTS:
        return False
    if path.name.lower() in _SOURCE_TREE_EXCLUDED_NAMES:
        return False
    if path.suffix.lower() == ".md" or path.name.lower().startswith("readme"):
        return False
    return True


def collect_source_tree_identity(repo_root: str | Path) -> dict[str, Any]:
    """Hash executable/verification inputs without retaining their contents."""

    root = Path(repo_root).resolve()
    tracked, tracked_error = _git_bytes(root, "ls-files", "--stage", "-z")
    untracked, untracked_error = _git_bytes(
        root, "ls-files", "--others", "--exclude-standard", "-z"
    )
    error = tracked_error or untracked_error
    if error is not None or tracked is None or untracked is None:
        return {
            "schema_name": SOURCE_TREE_SCHEMA,
            "schema_version": SOURCE_TREE_VERSION,
            "scope": SOURCE_TREE_SCOPE,
            "sha256": None,
            "file_count": None,
            "error": error or "source-tree discovery failed",
        }

    entries: dict[str, bytes] = {}
    for raw_entry in tracked.split(b"\0"):
        if not raw_entry:
            continue
        try:
            metadata, raw_path = raw_entry.split(b"\t", 1)
            relative = raw_path.decode("utf-8", errors="surrogateescape")
        except (ValueError, UnicodeDecodeError) as exc:
            error = f"invalid tracked source entry: {exc}"
            break
        if _source_path_in_scope(relative):
            entries[relative] = metadata

    if error is None:
        for raw_path in untracked.split(b"\0"):
            if not raw_path:
                continue
            try:
                relative = raw_path.decode("utf-8", errors="surrogateescape")
            except UnicodeDecodeError as exc:
                error = f"invalid untracked source path: {exc}"
                break
            if _source_path_in_scope(relative):
                entries.setdefault(relative, b"untracked")

    digest = hashlib.sha256()
    file_count = 0
    if error is None:
        for relative in sorted(entries):
            path = root / Path(relative)
            try:
                if path.is_symlink():
                    kind = b"symlink"
                    content = os.readlink(path).encode(
                        "utf-8", errors="surrogateescape"
                    )
                elif path.is_file():
                    kind = b"file"
                    content = path.read_bytes()
                elif path.is_dir():
                    # Gitlinks are separately versioned repositories. Retain
                    # their root index identity and, when initialized, their
                    # current commit and dirty state without recursively
                    # retaining submodule contents.
                    if not (path / ".git").exists():
                        kind = b"gitlink-uninitialized"
                        content = entries[relative]
                    else:
                        commit, commit_error = _git(path, "rev-parse", "HEAD")
                        status, status_error = _git(
                            path,
                            "status",
                            "--porcelain",
                            "--untracked-files=all",
                        )
                        if commit_error or status_error:
                            kind = b"gitlink-error"
                            content = entries[relative]
                        else:
                            kind = b"gitlink"
                            content = b"\0".join(
                                (
                                    entries[relative],
                                    str(commit).encode("ascii"),
                                    str(status).encode("utf-8"),
                                )
                            )
                else:
                    kind = b"missing"
                    content = b""
            except OSError as exc:
                error = f"could not hash {relative}: {exc}"
                break
            relative_bytes = relative.encode("utf-8", errors="surrogateescape")
            digest.update(len(relative_bytes).to_bytes(8, "big"))
            digest.update(relative_bytes)
            digest.update(len(kind).to_bytes(2, "big"))
            digest.update(kind)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
            file_count += 1

    return {
        "schema_name": SOURCE_TREE_SCHEMA,
        "schema_version": SOURCE_TREE_VERSION,
        "scope": SOURCE_TREE_SCOPE,
        "sha256": digest.hexdigest() if error is None else None,
        "file_count": file_count if error is None else None,
        "error": error,
    }


def collect_source_identity(repo_root: str | Path) -> dict[str, Any]:
    """Collect Git provenance plus a Qt-free source-tree fingerprint."""

    root = Path(repo_root).resolve()
    commit, commit_error = _git(root, "rev-parse", "HEAD")
    status, status_error = _git(root, "status", "--porcelain", "--untracked-files=all")
    return {
        "git_commit": commit,
        "git_short_commit": commit[:12] if commit else None,
        "dirty_worktree": bool(status) if status is not None else None,
        "git_error": commit_error or status_error,
        "source_tree": collect_source_tree_identity(root),
    }


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
    source = collect_source_identity(root)
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
