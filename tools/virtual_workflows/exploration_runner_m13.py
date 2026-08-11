"""Fresh-process aggregation and semantic coverage for Milestone 13."""

from __future__ import annotations

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

from tools.virtual_workflows.exploration_m13 import (
    CAMPAIGN_BUDGET,
    CAMPAIGN_ID,
    EXPECTED_CAMPAIGN_SHA256,
    EXPECTED_CATALOG_SHA256,
    FROZEN_SEQUENCES,
    M13_REJECTION_CASES,
    OPERATIONS,
    PLAN_SCHEMA_NAME,
    PLAN_SCHEMA_VERSION,
    SEMANTIC_COVERAGE_VERSION,
    SEQUENCE_BUDGET,
    STATES,
    campaign_sha256,
    catalog_sha256,
    sequence_from_normalized,
    sequence_sha256,
)
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.suite_runner import (
    TERMINATION_GRACE_SECONDS,
    contained_artifact_path,
    execute_isolated_child_process,
    file_sha256,
    relative_artifact_path,
    write_json_atomic,
    write_text_atomic,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATE_SCHEMA_NAME = "labcraft.virtual_workflow_exploration_aggregate"
AGGREGATE_SCHEMA_VERSION = 2
COVERAGE_SCHEMA_NAME = "labcraft.virtual_workflow_semantic_coverage"
COVERAGE_SCHEMA_VERSION = 1
FAILURE_INDEX_SCHEMA_NAME = "labcraft.virtual_workflow_original_failures"
FAILURE_INDEX_SCHEMA_VERSION = 1
CHILD_OUTCOMES = {
    "pass",
    "warning",
    "fail",
    "timeout",
    "process_error",
    "invalid_report",
    "budget_overrun",
}


class M13AggregateError(ValueError):
    """Raised when M13 aggregate, replay, coverage, or evidence drifts."""


@dataclass(frozen=True)
class M13ExplorationRunConfig:
    plan: Mapping[str, Any]
    output_root: Path = REPO_ROOT / "verification_reports" / "exploration"
    speed_multiplier: float = 1000.0
    visible: bool = False
    qt_platform: str = "offscreen"
    replay_command: tuple[str, ...] = ()
    python_executable: Path = Path(sys.executable)
    runner_path: Path = REPO_ROOT / "tools" / "run_virtual_workflow.py"
    termination_grace_seconds: float = TERMINATION_GRACE_SECONDS

    def __post_init__(self) -> None:
        validate_m13_plan(self.plan)
        object.__setattr__(self, "output_root", Path(self.output_root).resolve())
        object.__setattr__(
            self, "python_executable", Path(self.python_executable).resolve()
        )
        object.__setattr__(self, "runner_path", Path(self.runner_path).resolve())
        if not self.python_executable.is_file() or not self.runner_path.is_file():
            raise M13AggregateError("M13 executable or runner is absent")
        if not math.isfinite(self.speed_multiplier) or self.speed_multiplier <= 0:
            raise M13AggregateError("M13 speed multiplier is invalid")
        if self.qt_platform not in {"offscreen", "minimal"}:
            raise M13AggregateError("M13 Qt platform is unsupported")
        if self.termination_grace_seconds <= 0:
            raise M13AggregateError("M13 termination grace must be positive")
        if any(not isinstance(value, str) or not value for value in self.replay_command):
            raise M13AggregateError("M13 replay command is invalid")


@dataclass(frozen=True)
class M13ExplorationExecutionResult:
    aggregate: Mapping[str, Any]
    aggregate_path: Path
    summary_path: Path
    coverage_path: Path
    failure_index_path: Path

    @property
    def exit_code(self) -> int:
        return 2 if self.aggregate["classification"]["status"] == "fail" else 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _safe_sequence_label(value: str) -> str:
    if not value or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for char in value
    ):
        raise M13AggregateError("M13 sequence ID is unsafe for evidence paths")
    return value


def _tree_stats(root: Path) -> dict[str, int]:
    files = tuple(path for path in root.rglob("*") if path.is_file())
    return {
        "retained_files": len(files),
        "retained_bytes": sum(path.stat().st_size for path in files),
    }


def validate_m13_plan(plan: Mapping[str, Any]) -> None:
    if not isinstance(plan, Mapping):
        raise M13AggregateError("M13 plan must be an object")
    if plan.get("schema_name") != PLAN_SCHEMA_NAME:
        raise M13AggregateError("M13 plan schema is unsupported")
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise M13AggregateError("M13 plan version is unsupported")
    if plan.get("platform") != "windows_sil":
        raise M13AggregateError("M13 aggregate is Windows SIL only")
    if plan.get("execution_authorized") is not True:
        raise M13AggregateError("M13 plan is not authorized")
    tier = plan.get("seed_tier")
    if tier not in {"frozen", "diagnostic"}:
        raise M13AggregateError("M13 seed tier is invalid")
    if plan.get("release_gate_affected") is not (tier == "frozen"):
        raise M13AggregateError("M13 release-gate tier projection drifted")
    campaign = plan.get("campaign")
    rows = plan.get("sequences")
    if not isinstance(campaign, Mapping) or not isinstance(rows, list) or not rows:
        raise M13AggregateError("M13 campaign or sequence list is invalid")
    if (
        campaign.get("id") != CAMPAIGN_ID
        or campaign.get("catalog_sha256") != catalog_sha256()
        or campaign.get("campaign_sha256") != campaign_sha256()
        or campaign.get("catalog_sha256") != EXPECTED_CATALOG_SHA256
        or campaign.get("campaign_sha256") != EXPECTED_CAMPAIGN_SHA256
    ):
        raise M13AggregateError("M13 campaign identity drifted")
    if plan.get("sequence_count") != len(rows):
        raise M13AggregateError("M13 sequence count drifted")
    if tier == "frozen" and len(rows) != len(FROZEN_SEQUENCES):
        raise M13AggregateError("M13 frozen aggregate requires all six sequences")
    if tier == "diagnostic" and len(rows) > 4:
        raise M13AggregateError("M13 diagnostic aggregate exceeds four seeds")
    timeout = plan.get("timeout_seconds")
    if (
        not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
        or timeout > SEQUENCE_BUDGET.scenario_deadline_seconds
    ):
        raise M13AggregateError("M13 sequence deadline is invalid")
    seen: set[str] = set()
    totals = {
        "semantic_operations": 0,
        "action_rows": 0,
        "sessions": 0,
        "session_rotations": 0,
        "screenshots": 0,
        "reactions": 0,
        "executable_stocks": 0,
        "intents": 0,
        "droplets": 0,
    }
    for order, row in enumerate(rows, 1):
        if not isinstance(row, Mapping) or row.get("order") != order:
            raise M13AggregateError("M13 plan order is invalid")
        normalized = row.get("sequence")
        if not isinstance(normalized, Mapping):
            raise M13AggregateError("M13 normalized sequence is absent")
        sequence = sequence_from_normalized(normalized)
        if sequence.seed_tier != tier or sequence.sequence_id in seen:
            raise M13AggregateError("M13 sequence tier or identity drifted")
        seen.add(sequence.sequence_id)
        if row.get("sequence_sha256") != sequence_sha256(sequence):
            raise M13AggregateError("M13 normalized sequence hash drifted")
        values = sequence.normalized()
        totals["semantic_operations"] += values["operation_count"]
        totals["action_rows"] += values["projected_action_rows"]
        totals["sessions"] += values["sessions"]
        totals["session_rotations"] += values["session_rotations"]
        totals["screenshots"] += values["screenshots"]
        for name, value in values["workload_projection"].items():
            totals[name] += int(value)
    limits = CAMPAIGN_BUDGET.normalized()
    exceeded = [name for name, value in totals.items() if value > limits[name]]
    if exceeded:
        raise M13AggregateError(
            "M13 plan exceeds campaign budgets: " + ", ".join(exceeded)
        )


def load_m13_plan(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M13AggregateError(f"cannot load retained M13 plan: {exc}") from exc
    if not isinstance(payload, dict):
        raise M13AggregateError("retained M13 plan must be an object")
    validate_m13_plan(payload)
    return payload


def _sequence_reference(path: Path, root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": relative_artifact_path(path, root),
        "sha256": file_sha256(path),
        "semantic_sha256": row["sequence_sha256"],
        "immutable_original": True,
    }


def _child_command(
    config: M13ExplorationRunConfig,
    row: Mapping[str, Any],
    child_root: Path,
    normalized_path: Path,
) -> list[str]:
    sequence = row["sequence"]
    command = [
        str(config.python_executable),
        str(config.runner_path),
        "--exploration",
        CAMPAIGN_ID,
        "--sequence",
        str(sequence["sequence_id"]),
        "--normalized-sequence",
        str(normalized_path),
        "--output-root",
        str(child_root),
        "--seed",
        str(sequence["seed"]),
        "--speed-multiplier",
        f"{config.speed_multiplier:g}",
        "--timeout-seconds",
        str(float(config.plan["timeout_seconds"])),
    ]
    if sequence["seed_tier"] == "diagnostic":
        command.extend(
            ["--seed-tier", "diagnostic", "--diagnostic-seed", str(sequence["seed"])]
        )
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
    row: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise M13AggregateError("child report must be an object")
        validate_report_v1(payload)
    except Exception as exc:
        return None, f"invalid child report: {exc}"
    sequence = row["sequence"]
    workflow = payload.get("metrics", {}).get("workflow", {}).get("values", {})
    semantic = workflow.get("sequence_exploration", {})
    mismatches: list[str] = []
    if not path.resolve().is_relative_to(child_root.resolve()):
        mismatches.append("report escaped child root")
    if payload.get("workload", {}).get("workload_id") != CAMPAIGN_ID:
        mismatches.append("campaign workload mismatch")
    if payload.get("run", {}).get("seed") != sequence["seed"]:
        mismatches.append("sequence seed mismatch")
    if semantic.get("campaign_id") != CAMPAIGN_ID:
        mismatches.append("campaign identity mismatch")
    if semantic.get("catalog_sha256") != EXPECTED_CATALOG_SHA256:
        mismatches.append("catalog hash mismatch")
    if semantic.get("campaign_sha256") != EXPECTED_CAMPAIGN_SHA256:
        mismatches.append("campaign hash mismatch")
    if semantic.get("seed_tier") != sequence["seed_tier"]:
        mismatches.append("seed tier mismatch")
    if semantic.get("sequence") != sequence:
        mismatches.append("normalized sequence mismatch")
    if semantic.get("sequence_sha256") != row["sequence_sha256"]:
        mismatches.append("normalized sequence hash mismatch")
    reached = semantic.get("reached_transitions")
    if reached != sequence["steps"]:
        mismatches.append("reached transitions differ from normalized sequence")
    action_count = workflow.get("action_count")
    sessions = workflow.get("application_sessions")
    screenshots = workflow.get("screenshots")
    if not isinstance(action_count, int) or action_count > SEQUENCE_BUDGET.action_rows:
        mismatches.append("action budget exceeded")
    if not isinstance(sessions, list) or len(sessions) > SEQUENCE_BUDGET.sessions:
        mismatches.append("session budget exceeded")
    if not isinstance(screenshots, list) or len(screenshots) > SEQUENCE_BUDGET.screenshots:
        mismatches.append("screenshot budget exceeded")
    workload = payload.get("workload", {})
    if (
        workload.get("reaction_count"),
        workload.get("stock_count"),
        workload.get("expected_intent_count"),
        workload.get("expected_droplets"),
    ) != (4, 2, 8, 44):
        mismatches.append("compact workload projection drifted")
    replay = payload.get("run", {}).get("replay_command")
    if not isinstance(replay, list) or "--exploration" not in replay:
        mismatches.append("child replay command is invalid")
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
        "child_replay_command": list(replay),
        "reached_transitions": list(reached),
        "action_count": action_count,
        "session_count": len(sessions),
        "screenshot_count": len(screenshots),
        "screenshot_names": sorted(str(value) for value in screenshots),
        "cleanup_results": list(workflow.get("cleanup_results") or []),
    }, None


def _execute_child(
    config: M13ExplorationRunConfig,
    row: Mapping[str, Any],
    root: Path,
    normalized_path: Path,
    *,
    popen_factory: Callable[..., subprocess.Popen[str]],
) -> dict[str, Any]:
    sequence = row["sequence"]
    sequence_id = _safe_sequence_label(str(sequence["sequence_id"]))
    slot = contained_artifact_path(
        root / "children" / f"{int(row['order']):02d}_{sequence_id}",
        root,
        "M13 child root",
    )
    command = _child_command(config, row, slot, normalized_path)
    environment = os.environ.copy()
    if not config.visible:
        environment["QT_QPA_PLATFORM"] = config.qt_platform
    isolated = execute_isolated_child_process(
        command=command,
        child_root=slot,
        aggregate_root=root,
        watchdog_seconds=float(SEQUENCE_BUDGET.child_watchdog_seconds),
        termination_grace_seconds=config.termination_grace_seconds,
        environment=environment,
        popen_factory=popen_factory,
    )
    process = dict(isolated.process)
    reports = list(isolated.report_paths)
    report: dict[str, Any] | None = None
    report_error: str | None = None
    if len(reports) == 1:
        report, report_error = _load_report(
            reports[0], child_root=slot, aggregate_root=root, row=row
        )
    elif not reports:
        report_error = "child produced no report.json"
    else:
        report_error = f"child produced {len(reports)} report.json files"
    reasons: list[str] = []
    if process["timed_out"]:
        outcome = "timeout"
        reasons.append("child exceeded the 300-second watchdog")
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
        assert report is not None
        outcome = str(report["classification"])
        expected_code = 2 if outcome == "fail" else 0
        if process["return_code"] != expected_code:
            outcome = "process_error"
            reasons.append("child return code disagrees with report classification")
        else:
            reasons.extend(report["classification_reasons"])
    stats = _tree_stats(slot)
    if (
        stats["retained_files"] > SEQUENCE_BUDGET.retained_files
        or stats["retained_bytes"] > SEQUENCE_BUDGET.retained_bytes
    ):
        outcome = "budget_overrun"
        reasons.append("child retained-evidence budget exceeded")
    return {
        "order": int(row["order"]),
        "sequence_id": sequence_id,
        "seed": int(sequence["seed"]),
        "seed_tier": sequence["seed_tier"],
        "role": sequence["role"],
        "sequence_sha256": row["sequence_sha256"],
        "normalized_sequence": _sequence_reference(normalized_path, root, row),
        "command": list(isolated.command),
        "exact_rerun_command": list(command),
        "watchdog_seconds": SEQUENCE_BUDGET.child_watchdog_seconds,
        "outcome": outcome,
        "reasons": reasons,
        "process": process,
        "report": report,
        "retained_evidence": stats,
    }


def _transition_identity(row: Mapping[str, Any]) -> str:
    return (
        f"{row['operation_id']}|{row['from_state']}->{row['to_state']}|"
        f"{row['expected_outcome']}"
    )


def build_semantic_coverage(
    plan: Mapping[str, Any], children: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    frozen = plan["seed_tier"] == "frozen"
    declared_sequences = [dict(row["sequence"]) for row in plan["sequences"]]
    denominator = {
        "states": (
            sorted(state.state_id for state in STATES)
            if frozen
            else sorted(
                {
                    sequence["initial_state"]
                    for sequence in declared_sequences
                }
                | {
                    step["to_state"]
                    for sequence in declared_sequences
                    for step in sequence["steps"]
                }
            )
        ),
        "transitions": sorted(
            {
                _transition_identity(step)
                for sequence in declared_sequences
                for step in sequence["steps"]
            }
        ),
        "operations": (
            sorted(operation.operation_id for operation in OPERATIONS)
            if frozen
            else sorted(
                {
                    step["operation_id"]
                    for sequence in declared_sequences
                    for step in sequence["steps"]
                }
            )
        ),
        "rejection_classes": (
            sorted(
                {
                    operation.rejection_class
                    for operation in OPERATIONS
                    if operation.rejection_class
                }
            )
            if frozen
            else sorted(
                {
                    step["rejection_class"]
                    for sequence in declared_sequences
                    for step in sequence["steps"]
                    if step["rejection_class"]
                }
            )
        ),
    }
    reached = [
        step
        for child in children
        if child["outcome"] in {"pass", "warning"} and child.get("report")
        for step in child["report"]["reached_transitions"]
    ]
    observed = {
        "states": sorted(
            {
                state
                for step in reached
                for state in (step["from_state"], step["to_state"])
            }
        ),
        "transitions": sorted({_transition_identity(step) for step in reached}),
        "operations": sorted({step["operation_id"] for step in reached}),
        "rejection_classes": sorted(
            {step["rejection_class"] for step in reached if step["rejection_class"]}
        ),
    }
    categories: dict[str, Any] = {}
    complete = True
    for name, expected in denominator.items():
        missing = sorted(set(expected) - set(observed[name]))
        unexpected = sorted(set(observed[name]) - set(expected))
        passed = not missing and not unexpected
        complete = complete and passed
        categories[name] = {
            "status": "complete" if passed else "incomplete",
            "declared_count": len(expected),
            "observed_count": len(observed[name]),
            "declared": expected,
            "observed": observed[name],
            "missing": missing,
            "unexpected": unexpected,
        }
    return {
        "schema_name": COVERAGE_SCHEMA_NAME,
        "schema_version": COVERAGE_SCHEMA_VERSION,
        "coverage_version": SEMANTIC_COVERAGE_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "catalog_sha256": EXPECTED_CATALOG_SHA256,
        "campaign_sha256": EXPECTED_CAMPAIGN_SHA256,
        "seed_tier": plan["seed_tier"],
        "gate_eligible": frozen,
        "coverage_basis": "passing_child_reached_transitions",
        "status": "complete" if complete else "incomplete",
        "categories": categories,
        "sequence_count_is_not_coverage": True,
        "action_count_is_not_coverage": True,
    }


def validate_semantic_coverage(payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema_name") != COVERAGE_SCHEMA_NAME
        or payload.get("schema_version") != COVERAGE_SCHEMA_VERSION
        or payload.get("coverage_version") != SEMANTIC_COVERAGE_VERSION
    ):
        raise M13AggregateError("M13 semantic coverage schema drifted")
    categories = payload.get("categories")
    if not isinstance(categories, Mapping) or set(categories) != {
        "states",
        "transitions",
        "operations",
        "rejection_classes",
    }:
        raise M13AggregateError("M13 semantic coverage categories drifted")
    complete = True
    for row in categories.values():
        if not isinstance(row, Mapping):
            raise M13AggregateError("M13 semantic coverage row is invalid")
        passed = not row.get("missing") and not row.get("unexpected")
        if row.get("status") != ("complete" if passed else "incomplete"):
            raise M13AggregateError("M13 semantic coverage status drifted")
        complete = complete and passed
    if payload.get("status") != ("complete" if complete else "incomplete"):
        raise M13AggregateError("M13 semantic coverage classification drifted")


def _status(children: Sequence[Mapping[str, Any]]) -> str:
    outcomes = {str(row["outcome"]) for row in children}
    if outcomes - {"pass", "warning"}:
        return "fail"
    return "warning" if "warning" in outcomes else "pass"


def _failure_index(plan: Mapping[str, Any], children: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failures = []
    for child in children:
        if child["outcome"] in {"pass", "warning"}:
            continue
        report = child.get("report") or {}
        failures.append(
            {
                "sequence_id": child["sequence_id"],
                "seed": child["seed"],
                "seed_tier": child["seed_tier"],
                "outcome": child["outcome"],
                "reasons": list(child["reasons"]),
                "authoritative_original": dict(child["normalized_sequence"]),
                "reached_prefix": list(report.get("reached_transitions") or []),
                "report": dict(report) if report else None,
                "stdout": dict(child["process"]["stdout"]),
                "stderr": dict(child["process"]["stderr"]),
                "cleanup_results": list(report.get("cleanup_results") or []),
                "exact_rerun_command": list(child["exact_rerun_command"]),
                "original_may_not_be_replaced": True,
            }
        )
    return {
        "schema_name": FAILURE_INDEX_SCHEMA_NAME,
        "schema_version": FAILURE_INDEX_SCHEMA_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "seed_tier": plan["seed_tier"],
        "failure_count": len(failures),
        "failures": failures,
        "reduction": {
            "enabled": False,
            "policy": "optional diagnostic derivatives never replace originals",
        },
    }


def _classification(children: Sequence[Mapping[str, Any]], coverage: Mapping[str, Any]) -> dict[str, Any]:
    status = _status(children)
    if coverage["status"] != "complete":
        status = "fail"
    return {
        "status": status,
        "total_count": len(children),
        "completed_count": len(children),
        "pass_count": sum(row["outcome"] == "pass" for row in children),
        "warning_count": sum(row["outcome"] == "warning" for row in children),
        "fail_count": sum(row["outcome"] not in {"pass", "warning"} for row in children),
        "reasons": [
            f"sequence {row['sequence_id']}: {row['outcome']}"
            for row in children
            if row["outcome"] != "pass"
        ] + (["semantic coverage is incomplete"] if coverage["status"] != "complete" else []),
    }


def m13_exploration_summary(payload: Mapping[str, Any]) -> str:
    classification = payload["classification"]
    lines = [
        "Milestone 13 design/calibration semantic exploration",
        f"Tier: {payload['run']['seed_tier']}",
        f"Status: {classification['status']}",
        f"Sequences: {classification['pass_count']} pass / {classification['total_count']} total",
        f"Semantic coverage: {payload['semantic_coverage']['status']}",
        f"Original failures: {payload['original_failures']['failure_count']}",
        f"Release gate: {payload['release_gate']['status']}",
        "",
        *[
            f"{row['order']:02d}. {row['sequence_id']}: {row['outcome']}"
            for row in payload["children"]
        ],
        "",
        "Exact replay: " + " ".join(payload["run"]["replay_command"]),
    ]
    return "\n".join(lines) + "\n"


def execute_m13_exploration(
    config: M13ExplorationRunConfig,
    *,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> M13ExplorationExecutionResult:
    validate_m13_plan(config.plan)
    run_id = str(uuid.uuid4())
    root = (
        config.output_root / CAMPAIGN_ID / f"{_run_stamp()}_{run_id[:12]}"
    ).resolve()
    if not root.is_relative_to(config.output_root):
        raise M13AggregateError("M13 aggregate escaped its output root")
    root.mkdir(parents=True, exist_ok=False)
    started_at = _utc_now()
    started = time.perf_counter()
    plan_path = write_json_atomic(root / "exploration_plan.json", dict(config.plan))
    originals: list[Path] = []
    for row in config.plan["sequences"]:
        sequence_id = _safe_sequence_label(str(row["sequence"]["sequence_id"]))
        originals.append(
            write_json_atomic(
                root / "original_sequences" / f"{int(row['order']):02d}_{sequence_id}.json",
                dict(row["sequence"]),
            )
        )
    children: list[dict[str, Any]] = []
    for row, normalized_path in zip(config.plan["sequences"], originals):
        if time.perf_counter() - started >= CAMPAIGN_BUDGET.scenario_deadline_seconds:
            raise M13AggregateError("M13 aggregate exceeded 1,800 seconds before child launch")
        children.append(
            _execute_child(
                config,
                row,
                root,
                normalized_path,
                popen_factory=popen_factory,
            )
        )
    coverage = build_semantic_coverage(config.plan, children)
    validate_semantic_coverage(coverage)
    coverage_path = write_json_atomic(root / "semantic_coverage.json", coverage)
    failure_index = _failure_index(config.plan, children)
    failure_index_path = write_json_atomic(
        root / "original_failures.json", failure_index
    )
    duration_seconds = time.perf_counter() - started
    observed = {
        "semantic_operations": sum(
            int(row["sequence"]["operation_count"])
            for row in config.plan["sequences"]
        ),
        "action_rows": sum(
            int((row.get("report") or {}).get("action_count") or 0)
            for row in children
        ),
        "sessions": sum(
            int((row.get("report") or {}).get("session_count") or 0)
            for row in children
        ),
        "session_rotations": sum(
            int(row["sequence"]["session_rotations"])
            for row in config.plan["sequences"]
        ),
        "screenshots": sum(
            int((row.get("report") or {}).get("screenshot_count") or 0)
            for row in children
        ),
        "reactions": 4 * len(children),
        "executable_stocks": 2 * len(children),
        "intents": 8 * len(children),
        "droplets": 44 * len(children),
        "aggregate_runtime_seconds": duration_seconds,
    }
    limits = CAMPAIGN_BUDGET.normalized()
    budget_checks = {
        name: observed[name] <= limits[name]
        for name in (
            "semantic_operations",
            "action_rows",
            "sessions",
            "session_rotations",
            "screenshots",
            "reactions",
            "executable_stocks",
            "intents",
            "droplets",
        )
    }
    budget_checks["aggregate_runtime_seconds"] = (
        duration_seconds <= CAMPAIGN_BUDGET.scenario_deadline_seconds
    )
    replay_command = list(config.replay_command)
    if "--exploration-plan" not in replay_command:
        replay_command.extend(["--exploration-plan", str(plan_path)])
    classification = _classification(children, coverage)
    if not all(budget_checks.values()):
        classification["status"] = "fail"
        classification["reasons"].append("campaign execution budget exceeded")
    aggregate = {
        "schema_name": AGGREGATE_SCHEMA_NAME,
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "campaign_id": CAMPAIGN_ID,
            "seed_tier": config.plan["seed_tier"],
            "platform": "windows_sil",
            "started_at_utc": started_at,
            "ended_at_utc": _utc_now(),
            "duration_ms": duration_seconds * 1000.0,
            "parent_pid": os.getpid(),
            "speed_multiplier": config.speed_multiplier,
            "visible": config.visible,
            "qt_platform": None if config.visible else config.qt_platform,
            "replay_command": replay_command,
        },
        "catalog": dict(config.plan["campaign"]),
        "exploration_plan": {
            "path": relative_artifact_path(plan_path, root),
            "sha256": file_sha256(plan_path),
            "replay_consumes_retained_plan": True,
        },
        "children": children,
        "semantic_coverage": {
            "path": relative_artifact_path(coverage_path, root),
            "sha256": file_sha256(coverage_path),
            "status": coverage["status"],
            "version": coverage["coverage_version"],
        },
        "original_failures": {
            "path": relative_artifact_path(failure_index_path, root),
            "sha256": file_sha256(failure_index_path),
            "failure_count": failure_index["failure_count"],
            "originals_are_immutable": True,
        },
        "classification": classification,
        "release_gate": {
            "affected": config.plan["seed_tier"] == "frozen",
            "status": (
                classification["status"]
                if config.plan["seed_tier"] == "frozen"
                else "not_applicable"
            ),
        },
        "budgets": {
            "limits": limits,
            "observed": observed,
            "checks": budget_checks,
            "overrun_policy": "fail_closed_no_retry_or_budget_growth",
        },
        "reduction": {
            "enabled": False,
            "original_failure_remains_authoritative": True,
        },
        "limitations": [
            "Generated exploration supplements deterministic Milestone 9-12 evidence.",
            "This is application SIL evidence, not firmware, protocol, or physical hardware coverage.",
            "Deterministic reduction is intentionally omitted; originals are never replaced.",
        ],
    }
    summary = m13_exploration_summary(aggregate)
    current_stats = _tree_stats(root)
    for _ in range(4):
        retained_files = current_stats["retained_files"] + 2
        retained_bytes = (
            current_stats["retained_bytes"]
            + len(_json_bytes(aggregate))
            + len(summary.encode("utf-8"))
        )
        observed["retained_files"] = retained_files
        observed["retained_bytes"] = retained_bytes
        budget_checks["retained_files"] = retained_files <= CAMPAIGN_BUDGET.retained_files
        budget_checks["retained_bytes"] = retained_bytes <= CAMPAIGN_BUDGET.retained_bytes
        if not budget_checks["retained_files"] or not budget_checks["retained_bytes"]:
            classification["status"] = "fail"
            if "campaign retained-evidence budget exceeded" not in classification["reasons"]:
                classification["reasons"].append("campaign retained-evidence budget exceeded")
            if config.plan["seed_tier"] == "frozen":
                aggregate["release_gate"]["status"] = "fail"
        summary = m13_exploration_summary(aggregate)
    validate_m13_aggregate(aggregate, aggregate_root=root, verify_hashes=True)
    aggregate_path = write_json_atomic(root / "aggregate.json", aggregate)
    summary_path = write_text_atomic(root / "summary.txt", summary)
    actual_stats = _tree_stats(root)
    if actual_stats != {
        "retained_files": observed["retained_files"],
        "retained_bytes": observed["retained_bytes"],
    }:
        raise M13AggregateError("M13 retained-evidence accounting drifted")
    return M13ExplorationExecutionResult(
        aggregate,
        aggregate_path,
        summary_path,
        coverage_path,
        failure_index_path,
    )


def _artifact_path(value: Any, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise M13AggregateError(f"{label} path is invalid")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise M13AggregateError(f"{label} escaped aggregate root")
    return contained_artifact_path(root / Path(*pure.parts), root, label)


def validate_m13_aggregate(
    payload: Mapping[str, Any],
    *,
    aggregate_root: str | Path | None = None,
    verify_hashes: bool = True,
) -> None:
    if (
        payload.get("schema_name") != AGGREGATE_SCHEMA_NAME
        or payload.get("schema_version") != AGGREGATE_SCHEMA_VERSION
    ):
        raise M13AggregateError("M13 aggregate schema is unsupported")
    children = payload.get("children")
    if not isinstance(children, list) or not children:
        raise M13AggregateError("M13 aggregate children are invalid")
    for order, child in enumerate(children, 1):
        if (
            not isinstance(child, Mapping)
            or child.get("order") != order
            or child.get("outcome") not in CHILD_OUTCOMES
        ):
            raise M13AggregateError("M13 child contract is invalid")
    classification = payload.get("classification", {})
    coverage_ref = payload.get("semantic_coverage", {})
    expected_status = _status(children)
    if coverage_ref.get("status") != "complete":
        expected_status = "fail"
    if not all(payload.get("budgets", {}).get("checks", {}).values()):
        expected_status = "fail"
    if classification.get("status") != expected_status:
        raise M13AggregateError("M13 aggregate classification drifted")
    expected_counts = {
        "total_count": len(children),
        "completed_count": len(children),
        "pass_count": sum(row["outcome"] == "pass" for row in children),
        "warning_count": sum(row["outcome"] == "warning" for row in children),
        "fail_count": sum(row["outcome"] not in {"pass", "warning"} for row in children),
    }
    if any(classification.get(name) != value for name, value in expected_counts.items()):
        raise M13AggregateError("M13 aggregate counts drifted")
    tier = payload.get("run", {}).get("seed_tier")
    gate = payload.get("release_gate", {})
    if gate.get("affected") is not (tier == "frozen"):
        raise M13AggregateError("M13 diagnostic release-gate isolation drifted")
    if gate.get("status") != (expected_status if tier == "frozen" else "not_applicable"):
        raise M13AggregateError("M13 release-gate status drifted")
    replay = payload.get("run", {}).get("replay_command")
    if not isinstance(replay, list) or "--exploration-plan" not in replay:
        raise M13AggregateError("M13 exact aggregate replay is invalid")
    if aggregate_root is None:
        return
    root = Path(aggregate_root).resolve()
    references: list[tuple[Mapping[str, Any], str]] = [
        (payload["exploration_plan"], "M13 exploration plan"),
        (payload["semantic_coverage"], "M13 semantic coverage"),
        (payload["original_failures"], "M13 original failures"),
    ]
    for child in children:
        references.extend(
            [
                (child["normalized_sequence"], f"{child['sequence_id']} original"),
                (child["process"]["stdout"], f"{child['sequence_id']} stdout"),
                (child["process"]["stderr"], f"{child['sequence_id']} stderr"),
            ]
        )
        if child.get("report"):
            references.append((child["report"], f"{child['sequence_id']} report"))
    for reference, label in references:
        path = _artifact_path(reference.get("path"), root, label)
        digest = reference.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise M13AggregateError(f"{label} hash is invalid")
        if verify_hashes and (not path.is_file() or file_sha256(path) != digest):
            raise M13AggregateError(f"{label} hash mismatch")
    coverage = json.loads(
        _artifact_path(payload["semantic_coverage"]["path"], root, "coverage").read_text(
            encoding="utf-8"
        )
    )
    validate_semantic_coverage(coverage)
    failures = json.loads(
        _artifact_path(payload["original_failures"]["path"], root, "failures").read_text(
            encoding="utf-8"
        )
    )
    failed_ids = {
        child["sequence_id"]
        for child in children
        if child["outcome"] not in {"pass", "warning"}
    }
    if failures.get("failure_count") != len(failed_ids) or {
        row["sequence_id"] for row in failures.get("failures", [])
    } != failed_ids:
        raise M13AggregateError("M13 authoritative failure index drifted")
    for child in children:
        original = json.loads(
            _artifact_path(
                child["normalized_sequence"]["path"], root, "normalized sequence"
            ).read_text(encoding="utf-8")
        )
        sequence = sequence_from_normalized(original)
        if sequence.sequence_id != child["sequence_id"]:
            raise M13AggregateError("M13 retained original identity drifted")
        if sequence_sha256(sequence) != child["sequence_sha256"]:
            raise M13AggregateError("M13 retained original semantic hash drifted")


def load_m13_aggregate(
    path: str | Path, *, verify_hashes: bool = True
) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M13AggregateError(f"cannot load M13 aggregate: {exc}") from exc
    if not isinstance(payload, dict):
        raise M13AggregateError("M13 aggregate must be an object")
    validate_m13_aggregate(
        payload, aggregate_root=source.parent, verify_hashes=verify_hashes
    )
    return payload


__all__ = [
    "AGGREGATE_SCHEMA_NAME",
    "AGGREGATE_SCHEMA_VERSION",
    "COVERAGE_SCHEMA_NAME",
    "COVERAGE_SCHEMA_VERSION",
    "FAILURE_INDEX_SCHEMA_NAME",
    "FAILURE_INDEX_SCHEMA_VERSION",
    "M13AggregateError",
    "M13ExplorationExecutionResult",
    "M13ExplorationRunConfig",
    "build_semantic_coverage",
    "execute_m13_exploration",
    "load_m13_aggregate",
    "load_m13_plan",
    "m13_exploration_summary",
    "validate_m13_aggregate",
    "validate_m13_plan",
    "validate_semantic_coverage",
]
