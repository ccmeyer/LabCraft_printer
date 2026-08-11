from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from tools.virtual_workflows.exploration_m13 import resolve_plan
from tools.virtual_workflows.exploration_runner_m13 import (
    AGGREGATE_SCHEMA_VERSION,
    M13AggregateError,
    M13ExplorationRunConfig,
    build_semantic_coverage,
    execute_m13_exploration,
    load_m13_aggregate,
    load_m13_plan,
    validate_m13_plan,
    validate_semantic_coverage,
)
from tools.virtual_workflows.suite_runner import file_sha256, relative_artifact_path


class _FakeProcess:
    next_pid = 13100

    def __init__(self, command, behavior):
        self.command = list(command)
        self.behavior = dict(behavior)
        self.pid = self.next_pid
        type(self).next_pid += 1
        self.returncode = None
        self.terminated = False
        self.killed = False

    def communicate(self, timeout=None):
        if self.behavior.get("timeout") and not self.terminated:
            raise subprocess.TimeoutExpired(self.command, timeout)
        if self.behavior.get("timeout") and self.terminated and not self.killed:
            raise subprocess.TimeoutExpired(self.command, timeout)
        if self.behavior.get("report", "present") == "present":
            child_root = Path(self.command[self.command.index("--output-root") + 1])
            report = child_root / "synthetic" / "report.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("{}", encoding="utf-8")
        self.returncode = self.behavior.get("return_code", -9 if self.killed else 0)
        return "synthetic stdout\n", self.behavior.get("stderr", "")

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def _factory(behaviors):
    remaining = list(behaviors)
    processes = []

    def create(command, **_kwargs):
        process = _FakeProcess(command, remaining.pop(0))
        processes.append(process)
        return process

    return create, processes


def _fake_report_loader(path, *, child_root, aggregate_root, row):
    sequence = row["sequence"]
    return {
        "path": relative_artifact_path(path, aggregate_root),
        "sha256": file_sha256(path),
        "run_id": f"run-{sequence['sequence_id']}",
        "classification": "pass",
        "classification_reasons": [],
        "duration_ms": 1.0,
        "source": {"git_commit": "a" * 40, "dirty_worktree": True},
        "child_replay_command": ["python", "runner.py", "--exploration"],
        "reached_transitions": list(sequence["steps"]),
        "action_count": min(65, sequence["projected_action_rows"] + 20),
        "session_count": min(3, sequence["sessions"] + 1),
        "screenshot_count": sequence["screenshots"],
        "screenshot_names": ["prepared", "fresh_loaded", "fresh_activated", "terminal_reloaded"],
        "cleanup_results": [{"status": "pass"}],
    }, None


def _config(tmp_path, plan):
    return M13ExplorationRunConfig(
        plan=plan,
        output_root=tmp_path,
        replay_command=("python", "runner.py", "--exploration", "design_calibration_lifecycle_v1"),
        termination_grace_seconds=0.01,
    )


def test_frozen_aggregate_retains_exact_originals_coverage_and_replay(
    tmp_path, monkeypatch
):
    plan = resolve_plan(execution_authorized=True)
    monkeypatch.setattr(
        "tools.virtual_workflows.exploration_runner_m13._load_report",
        _fake_report_loader,
    )
    factory, processes = _factory([{} for _ in range(6)])
    result = execute_m13_exploration(
        _config(tmp_path, plan), popen_factory=factory
    )

    assert result.exit_code == 0
    assert result.aggregate["schema_version"] == AGGREGATE_SCHEMA_VERSION
    assert result.aggregate["classification"]["status"] == "pass"
    assert result.aggregate["semantic_coverage"]["status"] == "complete"
    assert result.aggregate["original_failures"]["failure_count"] == 0
    assert result.aggregate["release_gate"] == {"affected": True, "status": "pass"}
    assert "--exploration-plan" in result.aggregate["run"]["replay_command"]
    assert all(
        child["normalized_sequence"]["immutable_original"]
        for child in result.aggregate["children"]
    )
    assert all(process.pid != result.aggregate["run"]["parent_pid"] for process in processes)
    assert load_m13_plan(result.aggregate_path.parent / "exploration_plan.json") == plan
    assert load_m13_aggregate(result.aggregate_path) == result.aggregate


def test_original_failure_is_retained_unchanged_and_does_not_stop_children(
    tmp_path, monkeypatch
):
    plan = resolve_plan(execution_authorized=True)
    monkeypatch.setattr(
        "tools.virtual_workflows.exploration_runner_m13._load_report",
        _fake_report_loader,
    )
    behaviors = [{"report": "missing"}, *({} for _ in range(5))]
    factory, _ = _factory(behaviors)
    result = execute_m13_exploration(
        _config(tmp_path, plan), popen_factory=factory
    )

    assert len(result.aggregate["children"]) == 6
    assert result.aggregate["classification"]["status"] == "fail"
    assert result.aggregate["original_failures"]["failure_count"] == 1
    index = json.loads(result.failure_index_path.read_text(encoding="utf-8"))
    failure = index["failures"][0]
    assert failure["authoritative_original"]["immutable_original"] is True
    assert failure["original_may_not_be_replaced"] is True
    assert failure["reached_prefix"] == []
    original = result.aggregate_path.parent / Path(
        failure["authoritative_original"]["path"]
    )
    original.write_text("{}", encoding="utf-8")
    with pytest.raises(M13AggregateError, match="hash mismatch"):
        load_m13_aggregate(result.aggregate_path)


def test_diagnostic_aggregate_is_retained_but_release_gate_is_not_applicable(
    tmp_path, monkeypatch
):
    frozen_before = resolve_plan(execution_authorized=True)
    plan = resolve_plan(
        execution_authorized=True,
        seed_tier="diagnostic",
        diagnostic_seeds=(1,),
    )
    monkeypatch.setattr(
        "tools.virtual_workflows.exploration_runner_m13._load_report",
        _fake_report_loader,
    )
    factory, _ = _factory([{}])
    result = execute_m13_exploration(
        _config(tmp_path, plan), popen_factory=factory
    )

    assert result.aggregate["classification"]["status"] == "pass"
    assert result.aggregate["release_gate"] == {
        "affected": False,
        "status": "not_applicable",
    }
    assert result.aggregate["semantic_coverage"]["status"] == "complete"
    assert resolve_plan(execution_authorized=True) == frozen_before


def test_timeout_is_killed_retained_and_classified_fail(tmp_path, monkeypatch):
    plan = resolve_plan(execution_authorized=True)
    monkeypatch.setattr(
        "tools.virtual_workflows.exploration_runner_m13._load_report",
        _fake_report_loader,
    )
    factory, processes = _factory([{"timeout": True}, *({} for _ in range(5))])
    result = execute_m13_exploration(
        _config(tmp_path, plan), popen_factory=factory
    )
    first = result.aggregate["children"][0]
    assert first["outcome"] == "timeout"
    assert first["process"]["terminated"] is True
    assert first["process"]["killed"] is True
    assert processes[0].terminated and processes[0].killed


def test_plan_and_semantic_coverage_mutations_fail_closed():
    plan = resolve_plan(execution_authorized=True)
    changed = copy.deepcopy(plan)
    changed["sequences"][0]["sequence_sha256"] = "0" * 64
    with pytest.raises(M13AggregateError, match="hash drifted"):
        validate_m13_plan(changed)

    children = [
        {
            "outcome": "pass",
            "report": {"reached_transitions": row["sequence"]["steps"]},
        }
        for row in plan["sequences"]
    ]
    coverage = build_semantic_coverage(plan, children)
    validate_semantic_coverage(coverage)
    coverage["categories"]["operations"]["missing"] = ["invented"]
    with pytest.raises(M13AggregateError, match="status drifted"):
        validate_semantic_coverage(coverage)
