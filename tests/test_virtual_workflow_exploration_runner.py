from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest

from tools.virtual_workflows.exploration import (
    CAMPAIGN_ID,
    resolve_exploration_plan,
)
from tools.virtual_workflows.exploration_runner import (
    EXPLORATION_AGGREGATE_SCHEMA_NAME,
    ExplorationAggregateError,
    ExplorationRunConfig,
    execute_exploration,
    load_exploration_aggregate,
    validate_exploration_plan,
)
from tools.virtual_workflows.suite_runner import file_sha256, relative_artifact_path


def _plan(*, sequence_id="seed_1_legal"):
    return resolve_exploration_plan(
        CAMPAIGN_ID,
        sequence_id=sequence_id,
        timeout_seconds=1,
    )


def _two_sequence_plan():
    plan = resolve_exploration_plan(CAMPAIGN_ID, timeout_seconds=1)
    plan["sequences"] = plan["sequences"][:2]
    plan["sequence_count"] = 2
    return plan


class _FakeProcess:
    next_pid = 8100

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
    calls = []
    processes = []

    def create(command, **kwargs):
        calls.append((list(command), kwargs))
        process = _FakeProcess(command, remaining.pop(0))
        processes.append(process)
        return process

    return create, calls, processes


def _fake_report_loader(path, *, child_root, aggregate_root, config, row):
    return {
        "path": relative_artifact_path(path, aggregate_root),
        "sha256": file_sha256(path),
        "run_id": f"run-{row['sequence']['sequence_id']}",
        "classification": "pass",
        "classification_reasons": [],
        "duration_ms": 1.0,
        "source": {"git_commit": "a" * 40, "dirty_worktree": True},
        "replay_command": [
            "python", "runner.py", "--exploration", CAMPAIGN_ID,
            "--sequence", row["sequence"]["sequence_id"],
        ],
    }, None


def _config(tmp_path, *, plan=None):
    return ExplorationRunConfig(
        plan=plan or _plan(),
        output_root=tmp_path,
        speed_multiplier=1000,
        replay_command=("python", "runner.py", "--exploration", CAMPAIGN_ID),
        child_timeout_grace_seconds=0.01,
        termination_grace_seconds=0.01,
    )


def test_successful_exploration_retains_process_and_hashes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tools.virtual_workflows.exploration_runner._load_report",
        _fake_report_loader,
    )
    factory, calls, processes = _factory([{}])
    result = execute_exploration(_config(tmp_path), popen_factory=factory)

    assert result.exit_code == 0
    assert result.aggregate["schema_name"] == EXPLORATION_AGGREGATE_SCHEMA_NAME
    child = result.aggregate["children"][0]
    assert child["process"]["pid"] == processes[0].pid
    assert child["process"]["pid"] != child["process"]["parent_pid"]
    assert calls[0][0][calls[0][0].index("--seed") + 1] == "1"
    assert load_exploration_aggregate(result.aggregate_path) == result.aggregate


def test_exploration_continues_after_missing_report(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tools.virtual_workflows.exploration_runner._load_report",
        _fake_report_loader,
    )
    factory, calls, _ = _factory([{"report": "missing"}, {}])
    result = execute_exploration(
        _config(tmp_path, plan=_two_sequence_plan()), popen_factory=factory
    )

    assert len(calls) == 2
    assert [row["outcome"] for row in result.aggregate["children"]] == [
        "invalid_report", "pass"
    ]
    assert result.exit_code == 2


def test_exploration_timeout_terminates_and_kills(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tools.virtual_workflows.exploration_runner._load_report",
        _fake_report_loader,
    )
    factory, _, processes = _factory([{"timeout": True}])
    result = execute_exploration(_config(tmp_path), popen_factory=factory)

    child = result.aggregate["children"][0]
    assert child["outcome"] == "timeout"
    assert child["process"]["terminated"] is True
    assert child["process"]["killed"] is True
    assert processes[0].terminated and processes[0].killed


def test_exploration_hash_and_path_validation_fail_closed(tmp_path, monkeypatch):
    invalid = copy.deepcopy(_plan())
    invalid["sequences"][0]["sequence_sha256"] = "short"
    with pytest.raises(ExplorationAggregateError, match="hash"):
        validate_exploration_plan(invalid)

    monkeypatch.setattr(
        "tools.virtual_workflows.exploration_runner._load_report",
        _fake_report_loader,
    )
    factory, _, _ = _factory([{}])
    result = execute_exploration(_config(tmp_path), popen_factory=factory)
    plan_path = result.aggregate_path.parent / "exploration_plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ExplorationAggregateError, match="hash mismatch"):
        load_exploration_aggregate(result.aggregate_path)
