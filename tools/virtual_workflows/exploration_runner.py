"""Fresh-process execution and aggregation for bounded seeded exploration."""

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

from tools.virtual_workflows.exploration import (
    CAMPAIGN_ID,
    EXPLORATION_PLAN_SCHEMA_NAME,
    EXPLORATION_SCHEMA_VERSION,
    catalog_sha256,
    get_sequence,
)
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.suite_runner import (
    CHILD_TIMEOUT_GRACE_SECONDS,
    TERMINATION_GRACE_SECONDS,
    contained_artifact_path,
    execute_isolated_child_process,
    file_sha256,
    relative_artifact_path,
    write_json_atomic,
    write_text_atomic,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPLORATION_AGGREGATE_SCHEMA_NAME = "labcraft.virtual_workflow_exploration_aggregate"
EXPLORATION_AGGREGATE_SCHEMA_VERSION = 1
EXPLORATION_STATUSES = {"pass", "warning", "fail"}


class ExplorationAggregateError(ValueError):
    """Raised when exploration execution or evidence violates its contract."""


@dataclass(frozen=True)
class ExplorationRunConfig:
    plan: Mapping[str, Any]
    output_root: Path = REPO_ROOT / "verification_reports" / "exploration"
    speed_multiplier: float = 1.0
    visible: bool = False
    qt_platform: str = "offscreen"
    replay_command: tuple[str, ...] = ()
    python_executable: Path = Path(sys.executable)
    runner_path: Path = REPO_ROOT / "tools" / "run_virtual_workflow.py"
    child_timeout_grace_seconds: float = CHILD_TIMEOUT_GRACE_SECONDS
    termination_grace_seconds: float = TERMINATION_GRACE_SECONDS

    def __post_init__(self) -> None:
        validate_exploration_plan(self.plan)
        object.__setattr__(self, "output_root", Path(self.output_root).resolve())
        object.__setattr__(self, "python_executable", Path(self.python_executable).resolve())
        object.__setattr__(self, "runner_path", Path(self.runner_path).resolve())
        if not self.python_executable.is_file() or not self.runner_path.is_file():
            raise ExplorationAggregateError("exploration executable or runner is absent")
        if not math.isfinite(self.speed_multiplier) or self.speed_multiplier <= 0:
            raise ExplorationAggregateError("exploration speed must be positive")
        if self.qt_platform not in {"offscreen", "minimal"}:
            raise ExplorationAggregateError("exploration Qt platform is unsupported")
        if self.child_timeout_grace_seconds <= 0 or self.termination_grace_seconds <= 0:
            raise ExplorationAggregateError("exploration timeout grace must be positive")
        if any(not isinstance(value, str) or not value for value in self.replay_command):
            raise ExplorationAggregateError("exploration replay command is invalid")


@dataclass(frozen=True)
class ExplorationExecutionResult:
    aggregate: Mapping[str, Any]
    aggregate_path: Path
    summary_path: Path

    @property
    def exit_code(self) -> int:
        return 2 if self.aggregate["classification"]["status"] == "fail" else 0


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def validate_exploration_plan(plan: Mapping[str, Any]) -> None:
    if not isinstance(plan, Mapping):
        raise ExplorationAggregateError("exploration plan must be an object")
    if plan.get("schema_name") != EXPLORATION_PLAN_SCHEMA_NAME:
        raise ExplorationAggregateError("exploration plan schema is unsupported")
    if plan.get("schema_version") != EXPLORATION_SCHEMA_VERSION:
        raise ExplorationAggregateError("exploration plan version is unsupported")
    if plan.get("platform") != "windows_sil" or plan.get("execution_authorized") is not True:
        raise ExplorationAggregateError("exploration plan is not authorized")
    campaign = plan.get("campaign")
    sequences = plan.get("sequences")
    if not isinstance(campaign, Mapping) or not isinstance(sequences, list) or not sequences:
        raise ExplorationAggregateError("exploration campaign or sequences are invalid")
    if campaign.get("id") != CAMPAIGN_ID or campaign.get("catalog_sha256") != catalog_sha256():
        raise ExplorationAggregateError("exploration catalog identity drifted")
    if plan.get("sequence_count") != len(sequences):
        raise ExplorationAggregateError("exploration sequence count drifted")
    timeout = plan.get("timeout_seconds")
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ExplorationAggregateError("exploration timeout is invalid")
    identities: set[str] = set()
    for order, row in enumerate(sequences, 1):
        sequence = row.get("sequence") if isinstance(row, Mapping) else None
        if row.get("order") != order or not isinstance(sequence, Mapping):
            raise ExplorationAggregateError("exploration sequence order is invalid")
        sequence_id = sequence.get("sequence_id")
        if not isinstance(sequence_id, str) or sequence_id in identities:
            raise ExplorationAggregateError("exploration sequence identity is invalid")
        identities.add(sequence_id)
        if sequence != get_sequence(CAMPAIGN_ID, sequence_id).normalized():
            raise ExplorationAggregateError("exploration sequence parameters drifted")
        if row.get("sequence_sha256") != _canonical_sha256(sequence):
            raise ExplorationAggregateError("exploration sequence hash drifted")


def _child_command(
    config: ExplorationRunConfig,
    row: Mapping[str, Any],
    child_root: Path,
) -> list[str]:
    sequence = row["sequence"]
    command = [
        str(config.python_executable),
        str(config.runner_path),
        "--exploration",
        CAMPAIGN_ID,
        "--sequence",
        str(sequence["sequence_id"]),
        "--output-root",
        str(child_root),
        "--seed",
        str(sequence["seed"]),
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
    config: ExplorationRunConfig,
    row: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ExplorationAggregateError("child report must be an object")
        validate_report_v1(payload)
    except Exception as exc:
        return None, f"invalid child report: {exc}"
    sequence = row["sequence"]
    values = payload.get("metrics", {}).get("workflow", {}).get("values", {}).get(
        "sequence_exploration", {}
    )
    mismatches: list[str] = []
    if not path.resolve().is_relative_to(child_root.resolve()):
        mismatches.append("report escaped child root")
    if payload.get("workload", {}).get("workload_id") != CAMPAIGN_ID:
        mismatches.append("campaign workload mismatch")
    if payload.get("run", {}).get("seed") != sequence["seed"]:
        mismatches.append("sequence seed mismatch")
    if values.get("campaign_id") != CAMPAIGN_ID:
        mismatches.append("campaign identity mismatch")
    if values.get("sequence", {}).get("sequence_id") != sequence["sequence_id"]:
        mismatches.append("sequence identity mismatch")
    if values.get("sequence_sha256") != row["sequence_sha256"]:
        mismatches.append("sequence hash mismatch")
    if values.get("catalog_sha256") != config.plan["campaign"]["catalog_sha256"]:
        mismatches.append("catalog hash mismatch")
    replay = payload.get("run", {}).get("replay_command")
    if not isinstance(replay, list) or "--exploration" not in replay or "--sequence" not in replay:
        mismatches.append("sequence replay is invalid")
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
    config: ExplorationRunConfig,
    row: Mapping[str, Any],
    aggregate_root: Path,
    *,
    popen_factory: Callable[..., subprocess.Popen[str]],
) -> dict[str, Any]:
    order = int(row["order"])
    sequence = row["sequence"]
    sequence_id = str(sequence["sequence_id"])
    slot = contained_artifact_path(
        aggregate_root / "children" / f"{order:02d}_{sequence_id}",
        aggregate_root,
        "exploration child root",
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
    process = dict(isolated.process)
    reports = list(isolated.report_paths)
    reference: dict[str, Any] | None = None
    report_error: str | None = None
    if len(reports) == 1:
        reference, report_error = _load_report(
            reports[0], child_root=slot, aggregate_root=aggregate_root,
            config=config, row=row,
        )
    elif not reports:
        report_error = "child produced no report.json"
    else:
        report_error = f"child produced {len(reports)} report.json files"
    reasons: list[str] = []
    if process["timed_out"]:
        outcome = "timeout"
        reasons.append(f"child exceeded {watchdog:g}-second watchdog")
    elif process["launch_error"]:
        outcome = "process_error"
        reasons.append(str(process["launch_error"]))
    elif process["return_code"] not in {0, 2}:
        outcome = "process_error"
        reasons.append(f"unsupported child return code {process['return_code']}")
    elif report_error:
        outcome = "invalid_report"
        reasons.append(report_error)
    else:
        assert reference is not None
        outcome = str(reference["classification"])
        expected_code = 2 if outcome == "fail" else 0
        if process["return_code"] != expected_code:
            outcome = "process_error"
            reasons.append("child return code disagrees with report classification")
        else:
            reasons.extend(reference["classification_reasons"])
    return {
        "order": order,
        "sequence_id": sequence_id,
        "seed": sequence["seed"],
        "sequence_class": sequence["sequence_class"],
        "sequence_sha256": row["sequence_sha256"],
        "normalized_sequence": dict(sequence),
        "command": list(isolated.command),
        "watchdog_seconds": watchdog,
        "outcome": outcome,
        "reasons": reasons,
        "process": process,
        "report": reference,
    }


def _status(children: Sequence[Mapping[str, Any]]) -> str:
    outcomes = {str(row["outcome"]) for row in children}
    if outcomes - {"pass", "warning"}:
        return "fail"
    return "warning" if "warning" in outcomes else "pass"


def exploration_summary(payload: Mapping[str, Any]) -> str:
    classification = payload["classification"]
    lines = [
        "Virtual workflow seeded editor exploration",
        f"Campaign: {payload['run']['campaign_id']}",
        f"Status: {classification['status']}",
        f"Sequences: {classification['completed_count']} / {classification['total_count']}",
        f"Passed: {classification['pass_count']}",
        f"Warnings: {classification['warning_count']}",
        f"Failed: {classification['fail_count']}",
        "",
        "Sequences:",
        *[
            f"{row['order']:02d}. {row['sequence_id']}: {row['outcome']}"
            for row in payload["children"]
        ],
        "",
        "Replay: " + " ".join(payload["run"]["replay_command"]),
    ]
    return "\n".join(lines) + "\n"


def execute_exploration(
    config: ExplorationRunConfig,
    *,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> ExplorationExecutionResult:
    validate_exploration_plan(config.plan)
    run_id = str(uuid.uuid4())
    root = (
        config.output_root / CAMPAIGN_ID / f"{_run_stamp()}_{run_id[:12]}"
    ).resolve()
    if not root.is_relative_to(config.output_root):
        raise ExplorationAggregateError("exploration run escaped output root")
    root.mkdir(parents=True, exist_ok=False)
    started_at = _utc_now()
    started = time.perf_counter()
    plan_path = write_json_atomic(root / "exploration_plan.json", dict(config.plan))
    children = [
        _execute_child(config, row, root, popen_factory=popen_factory)
        for row in config.plan["sequences"]
    ]
    status = _status(children)
    aggregate = {
        "schema_name": EXPLORATION_AGGREGATE_SCHEMA_NAME,
        "schema_version": EXPLORATION_AGGREGATE_SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "campaign_id": CAMPAIGN_ID,
            "platform": "windows_sil",
            "started_at_utc": started_at,
            "ended_at_utc": _utc_now(),
            "duration_ms": (time.perf_counter() - started) * 1000.0,
            "parent_pid": os.getpid(),
            "speed_multiplier": config.speed_multiplier,
            "visible": config.visible,
            "qt_platform": os.environ.get("QT_QPA_PLATFORM") if config.visible else config.qt_platform,
            "replay_command": list(config.replay_command),
        },
        "catalog": dict(config.plan["campaign"]),
        "exploration_plan": {
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
                f"sequence {row['sequence_id']}: {row['outcome']}"
                for row in children if row["outcome"] != "pass"
            ],
        },
        "limitations": [
            "Exploration is bounded host SIL evidence, not exhaustive state-space coverage.",
            "Exploration aggregates cannot satisfy registered capability evidence.",
        ],
    }
    validate_exploration_aggregate(aggregate, aggregate_root=root, verify_hashes=True)
    aggregate_path = write_json_atomic(root / "aggregate.json", aggregate)
    summary_path = write_text_atomic(root / "summary.txt", exploration_summary(aggregate))
    return ExplorationExecutionResult(aggregate, aggregate_path, summary_path)


def _artifact_path(value: Any, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ExplorationAggregateError(f"{label} path is invalid")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise ExplorationAggregateError(f"{label} path escaped exploration root")
    return contained_artifact_path(root / Path(*pure.parts), root, label)


def validate_exploration_aggregate(
    payload: Mapping[str, Any],
    *,
    aggregate_root: str | Path | None = None,
    verify_hashes: bool = True,
) -> None:
    if payload.get("schema_name") != EXPLORATION_AGGREGATE_SCHEMA_NAME:
        raise ExplorationAggregateError("exploration aggregate schema is unsupported")
    if payload.get("schema_version") != EXPLORATION_AGGREGATE_SCHEMA_VERSION:
        raise ExplorationAggregateError("exploration aggregate version is unsupported")
    children = payload.get("children")
    classification = payload.get("classification", {})
    if not isinstance(children, list) or not children:
        raise ExplorationAggregateError("exploration aggregate children are invalid")
    if classification.get("status") not in EXPLORATION_STATUSES:
        raise ExplorationAggregateError("exploration classification is invalid")
    for order, row in enumerate(children, 1):
        if (
            not isinstance(row, Mapping) or row.get("order") != order
            or not isinstance(row.get("sequence_id"), str)
            or row.get("outcome") not in {
                "pass", "warning", "fail", "timeout", "process_error", "invalid_report"
            }
        ):
            raise ExplorationAggregateError("exploration child contract is invalid")
    expected = {
        "status": _status(children),
        "total_count": len(children),
        "completed_count": len(children),
        "pass_count": sum(row["outcome"] == "pass" for row in children),
        "warning_count": sum(row["outcome"] == "warning" for row in children),
        "fail_count": sum(row["outcome"] not in {"pass", "warning"} for row in children),
    }
    if any(classification.get(key) != value for key, value in expected.items()):
        raise ExplorationAggregateError("exploration classification counts drifted")
    replay = payload.get("run", {}).get("replay_command")
    if not isinstance(replay, list) or not replay:
        raise ExplorationAggregateError("exploration aggregate replay is invalid")
    if aggregate_root is None:
        return
    root = Path(aggregate_root).resolve()
    references = [(payload["exploration_plan"], "exploration plan")]
    for row in children:
        references.extend(
            [
                (row["process"]["stdout"], f"{row['sequence_id']} stdout"),
                (row["process"]["stderr"], f"{row['sequence_id']} stderr"),
            ]
        )
        if row.get("report"):
            references.append((row["report"], f"{row['sequence_id']} report"))
    for reference, label in references:
        path = _artifact_path(reference.get("path"), root, label)
        digest = reference.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ExplorationAggregateError(f"{label} hash is invalid")
        if verify_hashes and (not path.is_file() or file_sha256(path) != digest):
            raise ExplorationAggregateError(f"{label} hash mismatch")


def load_exploration_aggregate(
    path: str | Path, *, verify_hashes: bool = True
) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExplorationAggregateError(f"could not load exploration aggregate: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExplorationAggregateError("exploration aggregate must be an object")
    validate_exploration_aggregate(
        payload, aggregate_root=source.parent, verify_hashes=verify_hashes
    )
    return payload


__all__ = [
    "EXPLORATION_AGGREGATE_SCHEMA_NAME",
    "EXPLORATION_AGGREGATE_SCHEMA_VERSION",
    "ExplorationAggregateError",
    "ExplorationExecutionResult",
    "ExplorationRunConfig",
    "execute_exploration",
    "exploration_summary",
    "load_exploration_aggregate",
    "validate_exploration_aggregate",
    "validate_exploration_plan",
]
