"""Fresh-process execution and aggregation for typed host SIL matrices."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from tools.virtual_workflows.matrices import (
    MATRIX_PLAN_SCHEMA_NAME,
    MATRIX_SCHEMA_VERSION,
    MatrixValidationError,
    get_matrix_definition,
)
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.suite_runner import (
    CHILD_TIMEOUT_GRACE_SECONDS,
    TERMINATION_GRACE_SECONDS,
    communicate_bounded,
    contained_artifact_path,
    execute_isolated_child_process,
    file_sha256,
    log_reference,
    relative_artifact_path,
    write_json_atomic,
    write_text_atomic,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_AGGREGATE_SCHEMA_NAME = "labcraft.virtual_workflow_matrix_aggregate"
MATRIX_AGGREGATE_SCHEMA_VERSION = 1
MATRIX_STATUSES = {"pass", "warning", "fail"}


class MatrixAggregateError(ValueError):
    """Raised when matrix execution or retained evidence violates its contract."""


@dataclass(frozen=True)
class MatrixRunConfig:
    plan: Mapping[str, Any]
    output_root: Path = REPO_ROOT / "verification_reports" / "matrices"
    speed_multiplier: float = 1.0
    visible: bool = False
    qt_platform: str = "offscreen"
    replay_command: tuple[str, ...] = ()
    python_executable: Path = Path(sys.executable)
    runner_path: Path = REPO_ROOT / "tools" / "run_virtual_workflow.py"
    child_timeout_grace_seconds: float = CHILD_TIMEOUT_GRACE_SECONDS
    termination_grace_seconds: float = TERMINATION_GRACE_SECONDS

    def __post_init__(self) -> None:
        validate_matrix_plan(self.plan)
        object.__setattr__(self, "output_root", Path(self.output_root).resolve())
        object.__setattr__(
            self, "python_executable", Path(self.python_executable).resolve()
        )
        object.__setattr__(self, "runner_path", Path(self.runner_path).resolve())
        if not self.python_executable.is_file() or not self.runner_path.is_file():
            raise MatrixAggregateError("matrix executable or runner does not exist")
        if not math.isfinite(self.speed_multiplier) or self.speed_multiplier <= 0:
            raise MatrixAggregateError("matrix speed multiplier must be positive")
        if self.qt_platform not in {"offscreen", "minimal"}:
            raise MatrixAggregateError("matrix Qt platform is unsupported")
        if self.child_timeout_grace_seconds <= 0 or self.termination_grace_seconds <= 0:
            raise MatrixAggregateError("matrix timeout grace must be positive")
        if any(not isinstance(item, str) or not item for item in self.replay_command):
            raise MatrixAggregateError("matrix replay command is invalid")


@dataclass(frozen=True)
class MatrixExecutionResult:
    aggregate: Mapping[str, Any]
    aggregate_path: Path
    summary_path: Path

    @property
    def exit_code(self) -> int:
        return 2 if self.aggregate["classification"]["status"] == "fail" else 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def validate_matrix_plan(plan: Mapping[str, Any]) -> None:
    if not isinstance(plan, Mapping):
        raise MatrixAggregateError("matrix plan must be an object")
    if plan.get("schema_name") != MATRIX_PLAN_SCHEMA_NAME:
        raise MatrixAggregateError("matrix plan schema name is unsupported")
    if plan.get("schema_version") != MATRIX_SCHEMA_VERSION:
        raise MatrixAggregateError("matrix plan schema version is unsupported")
    matrix = plan.get("matrix")
    cases = plan.get("cases")
    if not isinstance(matrix, Mapping) or not isinstance(cases, list) or not cases:
        raise MatrixAggregateError("matrix plan identity or cases are invalid")
    try:
        definition = get_matrix_definition(str(matrix.get("id") or ""))
    except MatrixValidationError as exc:
        raise MatrixAggregateError(str(exc)) from exc
    if (
        definition.platform != "windows_sil"
        or plan.get("platform") != definition.platform
        or plan.get("execution_authorized") is not True
    ):
        raise MatrixAggregateError("matrix plan is not authorized for Windows SIL")
    if plan.get("case_count") != len(cases):
        raise MatrixAggregateError("matrix plan case count drifted")
    if (
        matrix.get("id") != definition.matrix_id
        or matrix.get("catalog_sha256") != definition.catalog_sha256()
        or matrix.get("base_scenario_id") != definition.base_scenario_id
    ):
        raise MatrixAggregateError("matrix catalog identity drifted")
    if not isinstance(plan.get("seed"), int) or isinstance(plan.get("seed"), bool):
        raise MatrixAggregateError("matrix seed is invalid")
    timeout = plan.get("timeout_seconds")
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise MatrixAggregateError("matrix timeout is invalid")
    ids: set[str] = set()
    for index, row in enumerate(cases, 1):
        case = row.get("case") if isinstance(row, Mapping) else None
        if row.get("order") != index or not isinstance(case, Mapping):
            raise MatrixAggregateError("matrix case order or payload is invalid")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise MatrixAggregateError("matrix case identity is invalid")
        ids.add(case_id)
        digest = row.get("case_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise MatrixAggregateError("matrix case hash is invalid")
        try:
            expected_case = definition.get_case(case_id)
        except MatrixValidationError as exc:
            raise MatrixAggregateError(str(exc)) from exc
        if case != expected_case.normalized():
            raise MatrixAggregateError("matrix case parameters drifted")
        expected_digest = hashlib.sha256(
            json.dumps(
                case, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        if digest != expected_digest:
            raise MatrixAggregateError("matrix case hash disagrees with parameters")


def _child_command(
    config: MatrixRunConfig,
    row: Mapping[str, Any],
    child_root: Path,
) -> list[str]:
    case_id = str(row["case"]["case_id"])
    command = [
        str(config.python_executable),
        str(config.runner_path),
        "--matrix",
        str(config.plan["matrix"]["id"]),
        "--case",
        case_id,
        "--output-root",
        str(child_root),
        "--seed",
        str(config.plan["seed"]),
        "--speed-multiplier",
        f"{config.speed_multiplier:g}",
        "--timeout-seconds",
        str(float(config.plan["timeout_seconds"])),
    ]
    if config.visible:
        command.append("--visible")
    else:
        command.extend(["--qt-platform", config.qt_platform])
    return command


def _load_report(
    path: Path,
    *,
    child_root: Path,
    aggregate_root: Path,
    config: MatrixRunConfig,
    row: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise MatrixAggregateError("matrix child report must be an object")
        validate_report_v1(payload)
    except Exception as exc:
        return None, f"invalid child report: {exc}"
    case_values = (
        payload.get("metrics", {})
        .get("persistence", {})
        .get("values", {})
        .get("matrix_case", {})
    )
    mismatches: list[str] = []
    if not path.resolve().is_relative_to(child_root.resolve()):
        mismatches.append("report escaped child root")
    if payload.get("workload", {}).get("workload_id") != config.plan["matrix"]["id"]:
        mismatches.append("matrix workload ID mismatch")
    if payload.get("run", {}).get("seed") != config.plan["seed"]:
        mismatches.append("matrix seed mismatch")
    if case_values.get("case", {}).get("case_id") != row["case"]["case_id"]:
        mismatches.append("matrix case ID mismatch")
    if case_values.get("case_sha256") != row["case_sha256"]:
        mismatches.append("matrix case hash mismatch")
    if case_values.get("catalog_sha256") != config.plan["matrix"]["catalog_sha256"]:
        mismatches.append("matrix catalog hash mismatch")
    replay = payload.get("run", {}).get("replay_command")
    if not isinstance(replay, list) or "--matrix" not in replay or "--case" not in replay:
        mismatches.append("matrix case replay command is invalid")
    if mismatches:
        return None, "; ".join(mismatches)
    return {
        "path": relative_artifact_path(path, aggregate_root),
        "sha256": file_sha256(path),
        "run_id": payload["run"]["run_id"],
        "classification": payload["classification"]["status"],
        "classification_reasons": list(payload["classification"].get("reasons") or []),
        "duration_ms": float(payload["run"]["duration_ms"]),
        "source": dict(payload["source"]),
        "replay_command": list(replay),
    }, None


def _execute_child(
    config: MatrixRunConfig,
    row: Mapping[str, Any],
    aggregate_root: Path,
    *,
    popen_factory: Callable[..., subprocess.Popen[str]],
) -> dict[str, Any]:
    order = int(row["order"])
    case_id = str(row["case"]["case_id"])
    slot = contained_artifact_path(
        aggregate_root / "children" / f"{order:02d}_{case_id}",
        aggregate_root,
        "matrix child root",
    )
    command = _child_command(config, row, slot)
    watchdog = float(config.plan["timeout_seconds"]) + config.child_timeout_grace_seconds
    environment = os.environ.copy()
    if not config.visible:
        environment["QT_QPA_PLATFORM"] = config.qt_platform
    isolated = execute_isolated_child_process(
        command=command,
        child_root=slot,
        aggregate_root=aggregate_root,
        watchdog_seconds=watchdog,
        termination_grace_seconds=config.termination_grace_seconds,
        environment=environment,
        popen_factory=popen_factory,
    )
    process_evidence = dict(isolated.process)
    reports = list(isolated.report_paths)
    reference: dict[str, Any] | None = None
    report_error: str | None = None
    if len(reports) == 1:
        reference, report_error = _load_report(
            reports[0],
            child_root=slot,
            aggregate_root=aggregate_root,
            config=config,
            row=row,
        )
    elif not reports:
        report_error = "child produced no report.json"
    else:
        report_error = f"child produced {len(reports)} report.json files"
    return_code = process_evidence["return_code"]
    timed_out = bool(process_evidence["timed_out"])
    launch_error = process_evidence["launch_error"]
    reasons: list[str] = []
    if timed_out:
        outcome = "timeout"
        reasons.append(f"child exceeded {watchdog:g}-second watchdog")
    elif launch_error:
        outcome = "process_error"
        reasons.append(launch_error)
    elif return_code not in {0, 2}:
        outcome = "process_error"
        reasons.append(f"unsupported child return code {return_code}")
    elif report_error:
        outcome = "invalid_report"
        reasons.append(report_error)
    else:
        assert reference is not None
        classification = str(reference["classification"])
        expected_code = 2 if classification == "fail" else 0
        if return_code != expected_code:
            outcome = "process_error"
            reasons.append("child return code disagrees with report classification")
        else:
            outcome = classification
            reasons.extend(reference["classification_reasons"])
    evidence = {
        "order": order,
        "case_id": case_id,
        "case_sha256": row["case_sha256"],
        "normalized_parameters": dict(row["case"]),
        "command": command,
        "watchdog_seconds": watchdog,
        "outcome": outcome,
        "reasons": reasons,
        "process": {
            **process_evidence,
        },
        "report": reference,
    }
    evidence.update(
        {
            key: value
            for key, value in row["case"].items()
            if str(key).startswith("expected_")
        }
    )
    return evidence


def _status(children: Sequence[Mapping[str, Any]]) -> str:
    outcomes = {str(row["outcome"]) for row in children}
    if outcomes - {"pass", "warning"}:
        return "fail"
    return "warning" if "warning" in outcomes else "pass"


def matrix_summary(payload: Mapping[str, Any]) -> str:
    classification = payload["classification"]
    lines = [
        "Virtual workflow parameter matrix",
        f"Matrix: {payload['run']['matrix_id']}",
        f"Status: {classification['status']}",
        f"Cases: {classification['completed_count']} / {classification['total_count']}",
        f"Passed: {classification['pass_count']}",
        f"Warnings: {classification['warning_count']}",
        f"Failed: {classification['fail_count']}",
        "",
        "Cases:",
    ]
    lines.extend(
        f"{row['order']:02d}. {row['case_id']}: {row['outcome']}"
        for row in payload["children"]
    )
    lines.extend(["", "Replay: " + " ".join(payload["run"]["replay_command"])])
    return "\n".join(lines) + "\n"


def execute_matrix(
    config: MatrixRunConfig,
    *,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> MatrixExecutionResult:
    validate_matrix_plan(config.plan)
    matrix_id = str(config.plan["matrix"]["id"])
    run_id = str(uuid.uuid4())
    root = (
        config.output_root / matrix_id / f"{_run_stamp()}_{run_id[:12]}"
    ).resolve()
    if not root.is_relative_to(config.output_root):
        raise MatrixAggregateError("matrix run escaped output root")
    root.mkdir(parents=True, exist_ok=False)
    started_at = _utc_now()
    started = time.perf_counter()
    plan_path = write_json_atomic(root / "matrix_plan.json", dict(config.plan))
    children = [
        _execute_child(config, row, root, popen_factory=popen_factory)
        for row in config.plan["cases"]
    ]
    status = _status(children)
    aggregate = {
        "schema_name": MATRIX_AGGREGATE_SCHEMA_NAME,
        "schema_version": MATRIX_AGGREGATE_SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "matrix_id": matrix_id,
            "platform": "windows_sil",
            "started_at_utc": started_at,
            "ended_at_utc": _utc_now(),
            "duration_ms": (time.perf_counter() - started) * 1000.0,
            "parent_pid": os.getpid(),
            "seed": config.plan["seed"],
            "speed_multiplier": config.speed_multiplier,
            "visible": config.visible,
            "qt_platform": os.environ.get("QT_QPA_PLATFORM") if config.visible else config.qt_platform,
            "replay_command": list(config.replay_command),
        },
        "catalog": dict(config.plan["matrix"]),
        "matrix_plan": {
            "path": relative_artifact_path(plan_path, root),
            "sha256": file_sha256(plan_path),
        },
        "children": children,
        "classification": {
            "status": status,
            "total_count": len(children),
            "completed_count": len(children),
            "pass_count": sum(row["outcome"] == "pass" for row in children),
            "warning_count": sum(row["outcome"] == "warning" for row in children),
            "fail_count": sum(row["outcome"] not in {"pass", "warning"} for row in children),
            "reasons": [
                f"case {row['case_id']}: {row['outcome']}"
                for row in children if row["outcome"] != "pass"
            ],
        },
        "limitations": [
            "Matrix evidence is host SIL evidence and does not validate firmware or physical output.",
            "Matrix aggregates remain separate from registered capability coverage.",
        ],
    }
    validate_matrix_aggregate(aggregate, aggregate_root=root, verify_hashes=True)
    aggregate_path = write_json_atomic(root / "aggregate.json", aggregate)
    summary_path = write_text_atomic(root / "summary.txt", matrix_summary(aggregate))
    return MatrixExecutionResult(aggregate, aggregate_path, summary_path)


def _artifact_path(value: Any, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise MatrixAggregateError(f"{label} path is invalid")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise MatrixAggregateError(f"{label} path escaped matrix root")
    return contained_artifact_path(root / Path(*pure.parts), root, label)


def validate_matrix_aggregate(
    payload: Mapping[str, Any],
    *,
    aggregate_root: str | Path | None = None,
    verify_hashes: bool = True,
) -> None:
    if payload.get("schema_name") != MATRIX_AGGREGATE_SCHEMA_NAME:
        raise MatrixAggregateError("matrix aggregate schema name is unsupported")
    if payload.get("schema_version") != MATRIX_AGGREGATE_SCHEMA_VERSION:
        raise MatrixAggregateError("matrix aggregate schema version is unsupported")
    if payload.get("classification", {}).get("status") not in MATRIX_STATUSES:
        raise MatrixAggregateError("matrix aggregate classification is invalid")
    children = payload.get("children")
    if not isinstance(children, list) or not children:
        raise MatrixAggregateError("matrix aggregate children are invalid")
    classification = payload["classification"]
    if classification.get("total_count") != len(children) or classification.get("completed_count") != len(children):
        raise MatrixAggregateError("matrix aggregate counts drifted")
    replay = payload.get("run", {}).get("replay_command")
    if not isinstance(replay, list) or not replay:
        raise MatrixAggregateError("matrix aggregate replay is invalid")
    for index, row in enumerate(children, 1):
        if (
            not isinstance(row, Mapping)
            or row.get("order") != index
            or not isinstance(row.get("case_id"), str)
            or row.get("outcome") not in {
                "pass", "warning", "fail", "timeout", "process_error", "invalid_report"
            }
        ):
            raise MatrixAggregateError("matrix aggregate child contract is invalid")
    expected_status = _status(children)
    expected_counts = {
        "status": expected_status,
        "total_count": len(children),
        "completed_count": len(children),
        "pass_count": sum(row["outcome"] == "pass" for row in children),
        "warning_count": sum(row["outcome"] == "warning" for row in children),
        "fail_count": sum(row["outcome"] not in {"pass", "warning"} for row in children),
    }
    if any(classification.get(key) != value for key, value in expected_counts.items()):
        raise MatrixAggregateError("matrix aggregate classification counts drifted")
    if aggregate_root is None:
        return
    root = Path(aggregate_root).resolve()
    refs = [(payload["matrix_plan"], "matrix plan")]
    for row in children:
        refs.extend(
            [
                (row["process"]["stdout"], f"{row['case_id']} stdout"),
                (row["process"]["stderr"], f"{row['case_id']} stderr"),
            ]
        )
        if row.get("report"):
            refs.append((row["report"], f"{row['case_id']} report"))
    for reference, label in refs:
        path = _artifact_path(reference.get("path"), root, label)
        digest = reference.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise MatrixAggregateError(f"{label} hash is invalid")
        if verify_hashes and (not path.is_file() or file_sha256(path) != digest):
            raise MatrixAggregateError(f"{label} hash mismatch")


def load_matrix_aggregate(
    path: str | Path,
    *,
    verify_hashes: bool = True,
) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixAggregateError(f"could not load matrix aggregate: {exc}") from exc
    if not isinstance(payload, dict):
        raise MatrixAggregateError("matrix aggregate must contain an object")
    validate_matrix_aggregate(
        payload, aggregate_root=source.parent, verify_hashes=verify_hashes
    )
    return payload


__all__ = [
    "MATRIX_AGGREGATE_SCHEMA_NAME",
    "MATRIX_AGGREGATE_SCHEMA_VERSION",
    "MatrixAggregateError",
    "MatrixExecutionResult",
    "MatrixRunConfig",
    "execute_matrix",
    "load_matrix_aggregate",
    "matrix_summary",
    "validate_matrix_aggregate",
    "validate_matrix_plan",
]
