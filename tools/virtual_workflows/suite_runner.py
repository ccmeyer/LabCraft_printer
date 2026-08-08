"""Fresh-process execution and aggregation for manual SIL selections."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.selection import (
    SELECTION_PLAN_SCHEMA_NAME,
    SELECTION_SCHEMA_VERSION,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATE_SCHEMA_NAME = "labcraft.virtual_workflow_aggregate"
AGGREGATE_SCHEMA_VERSION = 1
DEFAULT_AGGREGATE_ROOT = REPO_ROOT / "verification_reports" / "suites"
CHILD_TIMEOUT_GRACE_SECONDS = 60.0
TERMINATION_GRACE_SECONDS = 5.0
CHILD_OUTCOMES = {
    "pass",
    "warning",
    "fail",
    "timeout",
    "process_error",
    "missing_report",
    "ambiguous_report",
    "invalid_report",
    "identity_mismatch",
}
AGGREGATE_STATUSES = {"pass", "warning", "fail"}
AGGREGATE_PLATFORMS = {"windows_sil", "pi_sil"}
PI_SUITE_IDS = {"pi_primary", "pi_stress"}


class AggregateError(ValueError):
    """Raised when aggregate execution or evidence violates its contract."""


@dataclass(frozen=True)
class AggregateRunConfig:
    """Validated inputs for one explicit selection execution."""

    plan: Mapping[str, Any]
    output_root: Path = DEFAULT_AGGREGATE_ROOT
    speed_multiplier: float = 1.0
    visible: bool = False
    qt_platform: str = "offscreen"
    replay_command: tuple[str, ...] = ()
    python_executable: Path = Path(sys.executable)
    runner_path: Path = REPO_ROOT / "tools" / "run_virtual_workflow.py"
    child_timeout_grace_seconds: float = CHILD_TIMEOUT_GRACE_SECONDS
    termination_grace_seconds: float = TERMINATION_GRACE_SECONDS
    pi_preflight_path: Path | None = None
    pi_hardware_proof_path: Path | None = None

    def __post_init__(self) -> None:
        _validate_selection_plan(self.plan)
        object.__setattr__(self, "output_root", Path(self.output_root).resolve())
        object.__setattr__(
            self, "python_executable", Path(self.python_executable).resolve()
        )
        object.__setattr__(self, "runner_path", Path(self.runner_path).resolve())
        if self.pi_preflight_path is not None:
            object.__setattr__(
                self,
                "pi_preflight_path",
                Path(self.pi_preflight_path).resolve(),
            )
        if self.pi_hardware_proof_path is not None:
            object.__setattr__(
                self,
                "pi_hardware_proof_path",
                Path(self.pi_hardware_proof_path).resolve(),
            )
        if not self.python_executable.is_file():
            raise AggregateError("suite Python executable does not exist")
        if not self.runner_path.is_file():
            raise AggregateError("suite child runner does not exist")
        if not math.isfinite(self.speed_multiplier) or self.speed_multiplier <= 0:
            raise AggregateError("speed multiplier must be positive and finite")
        if self.qt_platform not in {"offscreen", "minimal"}:
            raise AggregateError("aggregate Qt platform is unsupported")
        for label, value in (
            ("child timeout grace", self.child_timeout_grace_seconds),
            ("termination grace", self.termination_grace_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise AggregateError(f"{label} must be positive and finite")
        if any(not isinstance(item, str) or not item for item in self.replay_command):
            raise AggregateError("aggregate replay command is invalid")
        platform_name = str(self.plan["platform"])
        pi_paths = (self.pi_preflight_path, self.pi_hardware_proof_path)
        if platform_name == "pi_sil":
            if self.visible:
                raise AggregateError("Pi aggregate execution is headless")
            if any(path is None for path in pi_paths):
                raise AggregateError("Pi aggregate execution requires preflight and proof")
            _pi_safety_identity(self)
        elif any(path is not None for path in pi_paths):
            raise AggregateError("Pi evidence is invalid for a Windows aggregate")


@dataclass(frozen=True)
class AggregateExecutionResult:
    """Written aggregate and its stable CLI exit classification."""

    aggregate: Mapping[str, Any]
    aggregate_path: Path
    summary_path: Path

    @property
    def exit_code(self) -> int:
        return aggregate_exit_code(self.aggregate)


@dataclass(frozen=True)
class IsolatedChildProcessResult:
    """Process/log/report-discovery facts shared by aggregate runners."""

    command: tuple[str, ...]
    process: Mapping[str, Any]
    report_paths: tuple[Path, ...]


def execute_isolated_child_process(
    *,
    command: Sequence[str],
    child_root: Path,
    aggregate_root: Path,
    watchdog_seconds: float,
    termination_grace_seconds: float,
    environment: Mapping[str, str],
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    cwd: Path = REPO_ROOT,
) -> IsolatedChildProcessResult:
    """Run one fresh child, retain logs, and discover report-v1 candidates."""

    root = contained_artifact_path(child_root, aggregate_root, "child root")
    root.mkdir(parents=True, exist_ok=False)
    process: subprocess.Popen[str] | None = None
    launch_error: str | None = None
    stdout = stderr = ""
    timed_out = terminated = killed = False
    started = time.perf_counter()
    try:
        process = popen_factory(
            list(command),
            cwd=Path(cwd).resolve(),
            env=dict(environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr, timed_out, terminated, killed = communicate_bounded(
            process,
            timeout_seconds=float(watchdog_seconds),
            termination_grace_seconds=float(termination_grace_seconds),
        )
    except OSError as exc:
        launch_error = f"{type(exc).__name__}: {exc}"
        stderr = launch_error + "\n"
    duration_ms = (time.perf_counter() - started) * 1000.0
    stdout_path = write_text_atomic(root / "process_stdout.txt", stdout)
    stderr_path = write_text_atomic(root / "process_stderr.txt", stderr)
    reports = tuple(sorted(root.rglob("report.json"), key=lambda item: item.as_posix()))
    return IsolatedChildProcessResult(
        command=tuple(str(value) for value in command),
        process={
            "parent_pid": os.getpid(),
            "pid": process.pid if process is not None else None,
            "return_code": process.returncode if process is not None else None,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "terminated": terminated,
            "killed": killed,
            "launch_error": launch_error,
            "stdout": log_reference(stdout_path, aggregate_root),
            "stderr": log_reference(stderr_path, aggregate_root),
        },
        report_paths=reports,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_selection_plan(plan: Mapping[str, Any]) -> None:
    if not isinstance(plan, Mapping):
        raise AggregateError("selection plan must be an object")
    if plan.get("schema_name") != SELECTION_PLAN_SCHEMA_NAME:
        raise AggregateError("selection plan schema name is unsupported")
    if plan.get("schema_version") != SELECTION_SCHEMA_VERSION:
        raise AggregateError("selection plan schema version is unsupported")
    platform_name = plan.get("platform")
    if platform_name not in AGGREGATE_PLATFORMS:
        raise AggregateError("selection plan platform is unsupported")
    if plan.get("readiness") != "ready":
        raise AggregateError("selection plan is not ready")
    if plan.get("execution_authorized") is not False:
        raise AggregateError("selection plan execution flag drifted")
    selector = plan.get("selector")
    if not isinstance(selector, Mapping) or selector.get("kind") not in {
        "suite",
        "capability",
    }:
        raise AggregateError("aggregate selection must be a suite or capability")
    if platform_name == "pi_sil" and (
        selector.get("kind") != "suite" or selector.get("id") not in PI_SUITE_IDS
    ):
        raise AggregateError("Pi execution accepts only pi_primary or pi_stress suites")
    scenarios = plan.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise AggregateError("aggregate selection has no scenarios")
    if plan.get("scenario_count") != len(scenarios):
        raise AggregateError("selection plan scenario count drifted")
    for expected_order, scenario in enumerate(scenarios, start=1):
        if not isinstance(scenario, Mapping):
            raise AggregateError("selection plan scenario must be an object")
        if scenario.get("order") != expected_order:
            raise AggregateError("selection plan scenario order drifted")
        for key in ("scenario_id", "registry_id", "runner_family"):
            if not isinstance(scenario.get(key), str) or not scenario[key]:
                raise AggregateError(f"selection scenario {key} is invalid")
        seed = scenario.get("seed")
        timeout = scenario.get("timeout_seconds")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise AggregateError("selection scenario seed is invalid")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or timeout <= 0
        ):
            raise AggregateError("selection scenario timeout is invalid")
        required_pi = scenario.get("required_pi_evidence")
        if not isinstance(required_pi, list):
            raise AggregateError("selection scenario Pi evidence is invalid")
        if platform_name == "pi_sil" and required_pi != [
            "preflight",
            "hardware_proof",
        ]:
            raise AggregateError("Pi selection scenario evidence contract drifted")
        if platform_name == "windows_sil" and required_pi:
            raise AggregateError("Windows selection unexpectedly requires Pi evidence")


def _pi_safety_identity(config: AggregateRunConfig) -> dict[str, Any]:
    """Load the authoritative Pi evidence and return aggregate-safe identity."""

    if config.pi_preflight_path is None or config.pi_hardware_proof_path is None:
        raise AggregateError("Pi aggregate execution requires preflight and proof")
    from tools.virtual_workflows.pi_sil import (
        PiSilError,
        load_and_validate_pi_evidence,
    )

    try:
        preflight, proof = load_and_validate_pi_evidence(
            config.pi_preflight_path,
            config.pi_hardware_proof_path,
            expected_qt_platform=config.qt_platform,
        )
    except PiSilError as exc:
        raise AggregateError(f"Pi aggregate evidence is invalid: {exc}") from exc
    source_tree_sha256 = preflight.get("source_tree_sha256")
    if not isinstance(source_tree_sha256, str) or len(source_tree_sha256) != 64:
        raise AggregateError("Pi aggregate preflight has no source-tree identity")
    return {
        "preflight_sha256": _sha256(config.pi_preflight_path),
        "proof_sha256": _sha256(config.pi_hardware_proof_path),
        "trace_sha256": str(proof["trace_sha256"]),
        "source_commit": str(preflight["source_commit"]),
        "source_tree_sha256": source_tree_sha256,
        "dirty_worktree": bool(preflight["dirty_worktree"]),
        "qt_platform": str(preflight["qt_platform"]),
        "sandbox_method": str(proof["sandbox_method"]),
        "pi_model": str(preflight["pi_model"]),
        "private_dev": bool(proof["private_dev"]),
        "root_read_only": bool(proof["root_read_only"]),
        "network_unshared": bool(proof["network_unshared"]),
    }


def _selector_label(selector: Mapping[str, Any]) -> str:
    selector_id = str(selector["id"])
    if not selector_id or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
        for character in selector_id
    ):
        raise AggregateError("selector ID is unsafe for aggregate paths")
    return (
        selector_id
        if selector["kind"] == "suite"
        else f"capability__{selector_id}"
    )


def _contained(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    if resolved == root.resolve() or not resolved.is_relative_to(root.resolve()):
        raise AggregateError(f"{label} escaped its aggregate root")
    return resolved


def _relative(path: Path, root: Path) -> str:
    return _contained(path, root, "artifact path").relative_to(
        root.resolve()
    ).as_posix()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> Path:
    if path.exists():
        raise AggregateError(f"refusing to overwrite aggregate artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path


def _write_text_atomic(path: Path, value: str) -> Path:
    if path.exists():
        raise AggregateError(f"refusing to overwrite aggregate artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path


def _child_command(
    config: AggregateRunConfig,
    scenario: Mapping[str, Any],
    child_root: Path,
) -> list[str]:
    command = [
        str(config.python_executable),
        str(config.runner_path),
        "--scenario",
        str(scenario["registry_id"]),
        "--output-root",
        str(child_root),
        "--seed",
        str(scenario["seed"]),
        "--speed-multiplier",
        f"{config.speed_multiplier:g}",
        "--timeout-seconds",
        str(float(scenario["timeout_seconds"])),
    ]
    if config.visible:
        command.append("--visible")
    else:
        command.extend(["--qt-platform", config.qt_platform])
    if config.plan["platform"] == "pi_sil":
        assert config.pi_preflight_path is not None
        assert config.pi_hardware_proof_path is not None
        command.extend(
            [
                "--target-pi",
                "--pi-preflight",
                str(config.pi_preflight_path),
                "--pi-hardware-proof",
                str(config.pi_hardware_proof_path),
            ]
        )
    return command


def _decode_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _communicate_bounded(
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float,
    termination_grace_seconds: float,
) -> tuple[str, str, bool, bool, bool]:
    timed_out = terminated = killed = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.terminate()
        terminated = True
        try:
            stdout, stderr = process.communicate(
                timeout=termination_grace_seconds
            )
        except subprocess.TimeoutExpired:
            process.kill()
            killed = True
            stdout, stderr = process.communicate()
    return (
        _decode_output(stdout),
        _decode_output(stderr),
        timed_out,
        terminated,
        killed,
    )


def _log_reference(path: Path, aggregate_root: Path) -> dict[str, Any]:
    return {
        "path": _relative(path, aggregate_root),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _load_child_report(
    report_path: Path,
    *,
    child_root: Path,
    aggregate_root: Path,
    scenario: Mapping[str, Any],
    platform_name: str,
    pi_safety: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise AggregateError("child report must contain an object")
        validate_report_v1(payload)
    except Exception as exc:
        return None, "invalid_report", f"invalid child report: {exc}"

    report_dir = Path(str(payload["safety"].get("report_dir") or "")).resolve()
    expected_report_dir = report_path.resolve().parent
    mismatches: list[str] = []
    if report_dir != expected_report_dir:
        mismatches.append("reported directory does not match report path")
    if not report_path.resolve().is_relative_to(child_root.resolve()):
        mismatches.append("child report escaped its child root")
    if payload["workload"].get("workload_id") != scenario["registry_id"]:
        mismatches.append("workload ID does not match selected registry ID")
    if payload["run"].get("seed") != scenario["seed"]:
        mismatches.append("report seed does not match selection plan")
    if platform_name == "pi_sil":
        assert pi_safety is not None
        if payload["run"].get("run_mode") != (
            f"{pi_safety['qt_platform']}_pi_sil"
        ):
            mismatches.append("report run mode is not the selected Pi SIL mode")
        if payload["source"].get("git_commit") != pi_safety["source_commit"]:
            mismatches.append("report source commit does not match Pi preflight")
        report_source_tree = payload["source"].get("source_tree") or {}
        if report_source_tree.get("sha256") != pi_safety["source_tree_sha256"]:
            mismatches.append("report source tree does not match Pi preflight")
        environment = payload.get("environment") or {}
        target_pi = environment.get("target_pi") or {}
        if target_pi.get("lane") != "raspberry_pi_sil":
            mismatches.append("report is missing Raspberry Pi lane identity")
        if target_pi.get("pi_model") != pi_safety["pi_model"]:
            mismatches.append("report Pi model does not match preflight")
        report_pi = payload["safety"].get("pi_sil") or {}
        expected_pi = {
            "sandbox_method": pi_safety["sandbox_method"],
            "private_dev": True,
            "root_read_only": True,
            "network_unshared": True,
            "forbidden_access_attempt_count": 0,
            "proof_sha256": pi_safety["proof_sha256"],
            "trace_sha256": pi_safety["trace_sha256"],
        }
        for key, expected_value in expected_pi.items():
            if report_pi.get(key) != expected_value:
                mismatches.append(f"report Pi safety field {key} does not match")
    elif str(payload["run"].get("run_mode", "")).endswith("_pi_sil"):
        mismatches.append("Windows aggregate received a Pi SIL report")
    replay = payload["run"].get("replay_command")
    if not isinstance(replay, list) or any(
        not isinstance(item, str) or not item for item in replay
    ):
        mismatches.append("child replay command is invalid")
    if mismatches:
        return None, "identity_mismatch", "; ".join(mismatches)

    reference = {
        "path": _relative(report_path, aggregate_root),
        "sha256": _sha256(report_path),
        "run_id": payload["run"]["run_id"],
        "classification": payload["classification"]["status"],
        "classification_reasons": list(
            payload["classification"].get("reasons") or []
        ),
        "duration_ms": float(payload["run"]["duration_ms"]),
        "source": dict(payload["source"]),
        "replay_command": list(replay),
    }
    return reference, None, None


def _execute_child(
    config: AggregateRunConfig,
    scenario: Mapping[str, Any],
    aggregate_root: Path,
    *,
    popen_factory: Callable[..., subprocess.Popen[str]],
    pi_safety: Mapping[str, Any] | None,
) -> dict[str, Any]:
    order = int(scenario["order"])
    slot = _contained(
        aggregate_root
        / "children"
        / f"{order:02d}_{scenario['registry_id']}",
        aggregate_root,
        "child root",
    )
    slot.mkdir(parents=True, exist_ok=False)
    command = _child_command(config, scenario, slot)
    watchdog_seconds = (
        float(scenario["timeout_seconds"])
        + config.child_timeout_grace_seconds
    )
    environment = os.environ.copy()
    if not config.visible:
        environment["QT_QPA_PLATFORM"] = config.qt_platform

    started = time.perf_counter()
    process: subprocess.Popen[str] | None = None
    launch_error: str | None = None
    stdout = stderr = ""
    timed_out = terminated = killed = False
    try:
        process = popen_factory(
            command,
            cwd=REPO_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr, timed_out, terminated, killed = _communicate_bounded(
            process,
            timeout_seconds=watchdog_seconds,
            termination_grace_seconds=config.termination_grace_seconds,
        )
    except OSError as exc:
        launch_error = f"{type(exc).__name__}: {exc}"
        stderr = launch_error + "\n"
    duration_ms = (time.perf_counter() - started) * 1000.0

    stdout_path = _write_text_atomic(slot / "process_stdout.txt", stdout)
    stderr_path = _write_text_atomic(slot / "process_stderr.txt", stderr)
    reports = sorted(slot.rglob("report.json"), key=lambda value: value.as_posix())
    report_reference: dict[str, Any] | None = None
    report_outcome: str | None = None
    report_reason: str | None = None
    if len(reports) == 1:
        report_reference, report_outcome, report_reason = _load_child_report(
            reports[0],
            child_root=slot,
            aggregate_root=aggregate_root,
            scenario=scenario,
            platform_name=str(config.plan["platform"]),
            pi_safety=pi_safety,
        )
    elif not reports:
        report_outcome = "missing_report"
        report_reason = "child produced no report.json"
    else:
        report_outcome = "ambiguous_report"
        report_reason = f"child produced {len(reports)} report.json files"

    return_code = process.returncode if process is not None else None
    reasons: list[str] = []
    if timed_out:
        outcome = "timeout"
        reasons.append(f"child exceeded {watchdog_seconds:g}-second watchdog")
    elif launch_error is not None:
        outcome = "process_error"
        reasons.append(launch_error)
    elif return_code not in {0, 2}:
        outcome = "process_error"
        reasons.append(f"child exited with unsupported return code {return_code}")
    elif report_outcome is not None:
        outcome = report_outcome
        reasons.append(report_reason or report_outcome)
    else:
        assert report_reference is not None
        classification = str(report_reference["classification"])
        expected_return_code = 2 if classification == "fail" else 0
        if return_code != expected_return_code:
            outcome = "process_error"
            reasons.append(
                "child return code disagrees with report classification: "
                f"return_code={return_code}, classification={classification}"
            )
        else:
            outcome = classification
            reasons.extend(
                f"report: {reason}"
                for reason in report_reference["classification_reasons"]
            )

    if report_reason and report_reason not in reasons:
        reasons.append(report_reason)
    return {
        "order": order,
        "scenario_id": scenario["scenario_id"],
        "registry_id": scenario["registry_id"],
        "command": command,
        "watchdog_seconds": watchdog_seconds,
        "outcome": outcome,
        "reasons": reasons,
        "process": {
            "parent_pid": os.getpid(),
            "pid": process.pid if process is not None else None,
            "return_code": return_code,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "terminated": terminated,
            "killed": killed,
            "launch_error": launch_error,
            "stdout": _log_reference(stdout_path, aggregate_root),
            "stderr": _log_reference(stderr_path, aggregate_root),
        },
        "report": report_reference,
    }


def _aggregate_status(children: Sequence[Mapping[str, Any]]) -> str:
    outcomes = {str(child["outcome"]) for child in children}
    if outcomes - {"pass", "warning"}:
        return "fail"
    return "warning" if "warning" in outcomes else "pass"


def aggregate_summary(payload: Mapping[str, Any]) -> str:
    """Render the stable human-readable aggregate summary."""

    validate_aggregate(payload, verify_hashes=False)
    classification = payload["classification"]
    selector = payload["run"]["selector"]
    lines = [
        "Virtual workflow aggregate",
        f"Selector: {selector['kind']} {selector['id']}",
        f"Status: {classification['status']}",
        f"Children: {classification['completed_count']} / {classification['total_count']}",
        f"Passed: {classification['pass_count']}",
        f"Warnings: {classification['warning_count']}",
        f"Failed: {classification['fail_count']}",
        "",
        "Children:",
    ]
    lines.extend(
        f"{child['order']:02d}. {child['registry_id']}: {child['outcome']}"
        for child in payload["children"]
    )
    lines.extend(
        [
            "",
            "Replay: " + " ".join(payload["run"]["replay_command"]),
        ]
    )
    return "\n".join(lines) + "\n"


def execute_selection(
    config: AggregateRunConfig,
    *,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> AggregateExecutionResult:
    """Run every planned scenario in a fresh child and aggregate it."""

    _validate_selection_plan(config.plan)
    platform_name = str(config.plan["platform"])
    pi_safety = _pi_safety_identity(config) if platform_name == "pi_sil" else None
    selector = dict(config.plan["selector"])
    run_id = str(uuid.uuid4())
    aggregate_root = (
        config.output_root
        / _selector_label(selector)
        / f"{_run_stamp()}_{run_id[:12]}"
    ).resolve()
    if not aggregate_root.is_relative_to(config.output_root):
        raise AggregateError("aggregate directory escaped output root")
    aggregate_root.mkdir(parents=True, exist_ok=False)
    started_at = _utc_now()
    started = time.perf_counter()

    plan_path = _write_json_atomic(
        aggregate_root / "selection_plan.json", dict(config.plan)
    )
    children = [
        _execute_child(
            config,
            scenario,
            aggregate_root,
            popen_factory=popen_factory,
            pi_safety=pi_safety,
        )
        for scenario in config.plan["scenarios"]
    ]
    status = _aggregate_status(children)
    fail_count = sum(
        child["outcome"] not in {"pass", "warning"} for child in children
    )
    warning_count = sum(child["outcome"] == "warning" for child in children)
    pass_count = sum(child["outcome"] == "pass" for child in children)
    reasons = [
        f"child {child['order']} {child['registry_id']}: "
        f"{child['outcome']}"
        + (f" — {'; '.join(child['reasons'])}" if child["reasons"] else "")
        for child in children
        if child["outcome"] not in {"pass"}
    ]
    seeds = {int(row["seed"]) for row in config.plan["scenarios"]}
    aggregate = {
        "schema_name": AGGREGATE_SCHEMA_NAME,
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "selector": selector,
            "platform": platform_name,
            "started_at_utc": started_at,
            "ended_at_utc": _utc_now(),
            "duration_ms": (time.perf_counter() - started) * 1000.0,
            "parent_pid": os.getpid(),
            "seed": next(iter(seeds)) if len(seeds) == 1 else None,
            "speed_multiplier": config.speed_multiplier,
            "visible": config.visible,
            "qt_platform": (
                os.environ.get("QT_QPA_PLATFORM")
                if config.visible
                else config.qt_platform
            ),
            "execution_requested": True,
            "replay_command": list(config.replay_command),
            **({"pi_safety": pi_safety} if pi_safety is not None else {}),
        },
        "manifest": dict(config.plan["manifest"]),
        "selection_plan": {
            "path": _relative(plan_path, aggregate_root),
            "sha256": _sha256(plan_path),
        },
        "children": children,
        "classification": {
            "status": status,
            "total_count": len(children),
            "completed_count": len(children),
            "pass_count": pass_count,
            "warning_count": warning_count,
            "fail_count": fail_count,
            "reasons": reasons,
        },
        "limitations": [
            (
                "Pi SIL children run inside the proved private-device sandbox "
                "but do not prove firmware or physical hardware behavior."
                if platform_name == "pi_sil"
                else "Host SIL children do not prove firmware or physical hardware behavior."
            ),
            "Aggregate status references child report-v1 evidence; capability freshness is evaluated in Milestone 8 Slice 4.",
        ],
    }
    aggregate_path = aggregate_root / "aggregate.json"
    write_aggregate_atomic(aggregate_path, aggregate)
    summary_path = _write_text_atomic(
        aggregate_root / "summary.txt", aggregate_summary(aggregate)
    )
    return AggregateExecutionResult(
        aggregate=aggregate,
        aggregate_path=aggregate_path,
        summary_path=summary_path,
    )


def execute_host_selection(
    config: AggregateRunConfig,
    *,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> AggregateExecutionResult:
    """Backward-compatible alias for the platform-neutral executor."""

    return execute_selection(config, popen_factory=popen_factory)


def _artifact_path(value: Any, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise AggregateError(f"{label} path is invalid")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise AggregateError(f"{label} path escaped aggregate root")
    return _contained(root / Path(*pure.parts), root, label)


def _validate_hash_reference(
    reference: Mapping[str, Any],
    root: Path,
    label: str,
    *,
    verify_hashes: bool,
) -> Path:
    path = _artifact_path(reference.get("path"), root, label)
    digest = reference.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise AggregateError(f"{label} SHA-256 is invalid")
    if verify_hashes:
        if not path.is_file():
            raise AggregateError(f"{label} is missing: {path}")
        if _sha256(path) != digest:
            raise AggregateError(f"{label} SHA-256 mismatch")
    return path


def validate_aggregate(
    payload: Mapping[str, Any],
    *,
    aggregate_root: str | Path | None = None,
    verify_hashes: bool = True,
) -> None:
    """Validate aggregate schema and optionally every referenced hash."""

    if not isinstance(payload, Mapping):
        raise AggregateError("aggregate must be an object")
    expected = {
        "schema_name",
        "schema_version",
        "run",
        "manifest",
        "selection_plan",
        "children",
        "classification",
        "limitations",
    }
    if set(payload) != expected:
        raise AggregateError("aggregate top-level fields are invalid")
    if payload["schema_name"] != AGGREGATE_SCHEMA_NAME:
        raise AggregateError("aggregate schema name is unsupported")
    if payload["schema_version"] != AGGREGATE_SCHEMA_VERSION:
        raise AggregateError("aggregate schema version is unsupported")
    run = payload["run"]
    manifest = payload["manifest"]
    children = payload["children"]
    classification = payload["classification"]
    if not all(isinstance(item, Mapping) for item in (run, manifest, classification)):
        raise AggregateError("aggregate metadata sections must be objects")
    platform_name = run.get("platform")
    if platform_name not in AGGREGATE_PLATFORMS or run.get("execution_requested") is not True:
        raise AggregateError("aggregate execution identity is invalid")
    pi_safety = run.get("pi_safety")
    if platform_name == "pi_sil":
        if not isinstance(pi_safety, Mapping):
            raise AggregateError("Pi aggregate safety identity is missing")
        expected_pi_keys = {
            "preflight_sha256",
            "proof_sha256",
            "trace_sha256",
            "source_commit",
            "source_tree_sha256",
            "dirty_worktree",
            "qt_platform",
            "sandbox_method",
            "pi_model",
            "private_dev",
            "root_read_only",
            "network_unshared",
        }
        if set(pi_safety) != expected_pi_keys:
            raise AggregateError("Pi aggregate safety identity is invalid")
        for hash_key in (
            "preflight_sha256",
            "proof_sha256",
            "trace_sha256",
            "source_tree_sha256",
        ):
            value = pi_safety.get(hash_key)
            if not isinstance(value, str) or len(value) != 64:
                raise AggregateError(f"Pi aggregate {hash_key} is invalid")
        if pi_safety.get("qt_platform") not in {"offscreen", "minimal"}:
            raise AggregateError("Pi aggregate Qt platform is invalid")
        if not all(
            pi_safety.get(key) is True
            for key in ("private_dev", "root_read_only", "network_unshared")
        ):
            raise AggregateError("Pi aggregate sandbox protections are invalid")
    elif pi_safety is not None:
        raise AggregateError("Windows aggregate unexpectedly contains Pi safety")
    if not isinstance(run.get("parent_pid"), int) or run["parent_pid"] <= 0:
        raise AggregateError("aggregate parent PID is invalid")
    if not isinstance(run.get("replay_command"), list) or not run["replay_command"]:
        raise AggregateError("aggregate replay command is invalid")
    if not isinstance(children, list) or not children:
        raise AggregateError("aggregate has no children")
    if classification.get("status") not in AGGREGATE_STATUSES:
        raise AggregateError("aggregate classification is invalid")
    if classification.get("total_count") != len(children):
        raise AggregateError("aggregate child count drifted")
    if classification.get("completed_count") != len(children):
        raise AggregateError("aggregate completion count drifted")
    root = Path(aggregate_root).resolve() if aggregate_root is not None else None
    if verify_hashes and root is None:
        raise AggregateError("aggregate root is required for hash validation")
    if root is not None:
        plan_path = _validate_hash_reference(
            payload["selection_plan"],
            root,
            "selection plan",
            verify_hashes=verify_hashes,
        )
        if verify_hashes:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            _validate_selection_plan(plan)
            if plan.get("manifest") != manifest:
                raise AggregateError("aggregate manifest differs from selection plan")
            if plan.get("platform") != platform_name:
                raise AggregateError("aggregate platform differs from selection plan")

    derived_pass = derived_warning = derived_fail = 0
    for expected_order, child in enumerate(children, start=1):
        if not isinstance(child, Mapping) or child.get("order") != expected_order:
            raise AggregateError("aggregate child order is invalid")
        outcome = child.get("outcome")
        if outcome not in CHILD_OUTCOMES:
            raise AggregateError("aggregate child outcome is invalid")
        process = child.get("process")
        if not isinstance(process, Mapping):
            raise AggregateError("aggregate child process is invalid")
        if process.get("parent_pid") != run["parent_pid"]:
            raise AggregateError("child parent PID differs from aggregate")
        if root is not None:
            for stream in ("stdout", "stderr"):
                reference = process.get(stream)
                if not isinstance(reference, Mapping):
                    raise AggregateError(f"child {stream} reference is invalid")
                _validate_hash_reference(
                    reference,
                    root,
                    f"child {stream}",
                    verify_hashes=verify_hashes,
                )
            report_reference = child.get("report")
            if report_reference is not None:
                if not isinstance(report_reference, Mapping):
                    raise AggregateError("child report reference is invalid")
                report_path = _validate_hash_reference(
                    report_reference,
                    root,
                    "child report",
                    verify_hashes=verify_hashes,
                )
                if verify_hashes:
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    validate_report_v1(report)
                    if report["classification"]["status"] != report_reference.get(
                        "classification"
                    ):
                        raise AggregateError("child report classification drifted")
                    if list(report["classification"].get("reasons") or []) != (
                        report_reference.get("classification_reasons") or []
                    ):
                        raise AggregateError("child report reasons drifted")
                    if platform_name == "pi_sil":
                        assert isinstance(pi_safety, Mapping)
                        if report["run"].get("run_mode") != (
                            f"{pi_safety['qt_platform']}_pi_sil"
                        ):
                            raise AggregateError("child report Pi run mode drifted")
                        if report["source"].get("git_commit") != pi_safety.get(
                            "source_commit"
                        ):
                            raise AggregateError("child report Pi source drifted")
                        if (report["source"].get("source_tree") or {}).get(
                            "sha256"
                        ) != pi_safety.get("source_tree_sha256"):
                            raise AggregateError(
                                "child report Pi source-tree identity drifted"
                            )
                        report_pi = report["safety"].get("pi_sil") or {}
                        for field in (
                            "proof_sha256",
                            "trace_sha256",
                            "sandbox_method",
                            "private_dev",
                            "root_read_only",
                            "network_unshared",
                        ):
                            if report_pi.get(field) != pi_safety.get(field):
                                raise AggregateError(
                                    f"child report Pi safety {field} drifted"
                                )
        derived_pass += outcome == "pass"
        derived_warning += outcome == "warning"
        derived_fail += outcome not in {"pass", "warning"}
    if classification.get("pass_count") != derived_pass:
        raise AggregateError("aggregate pass count drifted")
    if classification.get("warning_count") != derived_warning:
        raise AggregateError("aggregate warning count drifted")
    if classification.get("fail_count") != derived_fail:
        raise AggregateError("aggregate fail count drifted")
    expected_status = _aggregate_status(children)
    if classification["status"] != expected_status:
        raise AggregateError("aggregate status disagrees with children")
    limitations = payload["limitations"]
    if not isinstance(limitations, list) or any(
        not isinstance(item, str) or not item for item in limitations
    ):
        raise AggregateError("aggregate limitations are invalid")


def load_aggregate(path: str | Path, *, verify_hashes: bool = True) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AggregateError(f"could not load aggregate {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AggregateError("aggregate file must contain an object")
    validate_aggregate(
        payload,
        aggregate_root=source.parent,
        verify_hashes=verify_hashes,
    )
    return payload


def write_aggregate_atomic(
    path: str | Path, payload: Mapping[str, Any]
) -> Path:
    """Validate and atomically create one non-overwriting aggregate JSON."""

    destination = Path(path).resolve()
    validate_aggregate(payload, aggregate_root=destination.parent)
    return _write_json_atomic(destination, payload)


def aggregate_exit_code(payload: Mapping[str, Any]) -> int:
    status = payload.get("classification", {}).get("status")
    if status not in AGGREGATE_STATUSES:
        raise AggregateError("aggregate classification is invalid")
    return 2 if status == "fail" else 0


# Reusable process/evidence primitives shared by suite and matrix aggregation.
# Slice 3 continues to call the original private names so its behavior and
# schemas remain frozen.
contained_artifact_path = _contained
relative_artifact_path = _relative
write_json_atomic = _write_json_atomic
write_text_atomic = _write_text_atomic
communicate_bounded = _communicate_bounded
log_reference = _log_reference
file_sha256 = _sha256


__all__ = [
    "AGGREGATE_SCHEMA_NAME",
    "AGGREGATE_SCHEMA_VERSION",
    "AggregateError",
    "AggregateExecutionResult",
    "AggregateRunConfig",
    "IsolatedChildProcessResult",
    "aggregate_exit_code",
    "aggregate_summary",
    "execute_host_selection",
    "execute_selection",
    "execute_isolated_child_process",
    "load_aggregate",
    "validate_aggregate",
    "write_aggregate_atomic",
    "communicate_bounded",
    "contained_artifact_path",
    "file_sha256",
    "log_reference",
    "relative_artifact_path",
    "write_json_atomic",
    "write_text_atomic",
]
