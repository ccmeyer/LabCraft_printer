from __future__ import annotations

import copy
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

import tools.virtual_workflows.matrices as matrices
from tools.virtual_workflows.matrices import (
    MIXED_MODE_MATRIX_ID,
    MatrixDefinition,
    MatrixRegistry,
    resolve_matrix_plan,
)
from tools.virtual_workflows.matrix_runner import (
    MATRIX_AGGREGATE_SCHEMA_NAME,
    MatrixAggregateError,
    MatrixRunConfig,
    execute_matrix,
    load_matrix_aggregate,
    validate_matrix_plan,
)
from tools.virtual_workflows.suite_runner import (
    file_sha256,
    relative_artifact_path,
)


def _plan(*, case_id="mixed_ab_baseline_pass"):
    return resolve_matrix_plan(
        MIXED_MODE_MATRIX_ID,
        case_id=case_id,
        seed=1,
        timeout_seconds=1,
        execution_authorized=True,
    )


def _two_case_plan():
    payload = resolve_matrix_plan(
        MIXED_MODE_MATRIX_ID,
        seed=1,
        timeout_seconds=1,
        execution_authorized=True,
    )
    payload["cases"] = payload["cases"][:2]
    payload["case_count"] = 2
    return payload


class _FakeProcess:
    next_pid = 7000

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
            child_root = Path(
                self.command[self.command.index("--output-root") + 1]
            )
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
        behavior = remaining.pop(0)
        calls.append((list(command), kwargs))
        process = _FakeProcess(command, behavior)
        processes.append(process)
        return process

    return create, calls, processes


def _fake_report_loader(
    path, *, child_root, aggregate_root, config, row
):
    classification = "warning" if "warning" in path.parts else "pass"
    return {
        "path": relative_artifact_path(path, aggregate_root),
        "sha256": file_sha256(path),
        "run_id": f"run-{row['case']['case_id']}",
        "classification": classification,
        "classification_reasons": [],
        "duration_ms": 1.0,
        "source": {"git_commit": "a" * 40, "dirty_worktree": True},
        "replay_command": [
            "python",
            "runner.py",
            "--matrix",
            config.plan["matrix"]["id"],
            "--case",
            row["case"]["case_id"],
        ],
    }, None


def _config(tmp_path, *, plan=None):
    return MatrixRunConfig(
        plan=plan or _plan(),
        output_root=tmp_path,
        speed_multiplier=1000,
        replay_command=("python", "runner.py", "--matrix", MIXED_MODE_MATRIX_ID),
        child_timeout_grace_seconds=0.01,
        termination_grace_seconds=0.01,
    )


@dataclass(frozen=True)
class _SyntheticCase:
    case_id: str
    expected_label: str

    def normalized(self):
        return {
            "case_id": self.case_id,
            "expected_label": self.expected_label,
        }


def _synthetic_definition() -> MatrixDefinition:
    return MatrixDefinition(
        matrix_id="synthetic_runner_matrix_v1",
        base_scenario_id="synthetic_runner_base_v1",
        journey_family="synthetic_runner",
        platform="windows_sil",
        execution="manual_on_demand",
        cases=(_SyntheticCase("control", "runner"),),
        catalog_metadata={},
        fixture_builder=lambda _case: ({}, Path(__file__)),
    )


def test_successful_matrix_retains_fresh_process_identity_and_hashes(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "tools.virtual_workflows.matrix_runner._load_report",
        _fake_report_loader,
    )
    factory, calls, processes = _factory([{}])

    result = execute_matrix(_config(tmp_path), popen_factory=factory)

    assert result.exit_code == 0
    assert result.aggregate["schema_name"] == MATRIX_AGGREGATE_SCHEMA_NAME
    assert result.aggregate["classification"]["status"] == "pass"
    child = result.aggregate["children"][0]
    assert child["expected_terminal"] == "completed"
    assert child["expected_completion_count"] == 48
    assert child["process"]["pid"] == processes[0].pid
    assert child["process"]["pid"] != child["process"]["parent_pid"]
    assert child["report"]["sha256"] == file_sha256(
        result.aggregate_path.parent / child["report"]["path"]
    )
    assert calls[0][0][calls[0][0].index("--case") + 1] == child["case_id"]
    assert calls[0][1]["cwd"] == Path(__file__).resolve().parents[1]
    assert load_matrix_aggregate(result.aggregate_path) == result.aggregate
    assert "Replay: python runner.py --matrix" in result.summary_path.read_text(
        encoding="utf-8"
    )


def test_runner_validates_and_aggregates_test_local_second_definition(
    tmp_path, monkeypatch
):
    definition = _synthetic_definition()
    registry = MatrixRegistry((matrices.MIXED_MODE_DEFINITION, definition))
    monkeypatch.setattr(matrices, "MATRIX_REGISTRY", registry)
    plan = matrices.resolve_matrix_plan(
        definition.matrix_id,
        case_id="control",
        seed=5,
        timeout_seconds=1,
    )
    validate_matrix_plan(plan)
    monkeypatch.setattr(
        "tools.virtual_workflows.matrix_runner._load_report",
        _fake_report_loader,
    )
    factory, calls, _ = _factory([{}])

    result = execute_matrix(
        _config(tmp_path, plan=plan),
        popen_factory=factory,
    )

    assert result.aggregate["catalog"]["id"] == definition.matrix_id
    child = result.aggregate["children"][0]
    assert child["expected_label"] == "runner"
    assert "expected_terminal" not in child
    assert "expected_completion_count" not in child
    command = calls[0][0]
    assert command[command.index("--matrix") + 1] == definition.matrix_id
    assert command[command.index("--case") + 1] == "control"


def test_matrix_continues_after_missing_report_and_fails_closed(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "tools.virtual_workflows.matrix_runner._load_report",
        _fake_report_loader,
    )
    factory, calls, _ = _factory([{"report": "missing"}, {}])

    result = execute_matrix(
        _config(tmp_path, plan=_two_case_plan()), popen_factory=factory
    )

    assert len(calls) == 2
    assert [row["outcome"] for row in result.aggregate["children"]] == [
        "invalid_report",
        "pass",
    ]
    assert result.aggregate["classification"]["status"] == "fail"
    assert result.aggregate["classification"]["fail_count"] == 1
    assert result.exit_code == 2


def test_matrix_watchdog_terminates_then_kills_and_retains_logs(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "tools.virtual_workflows.matrix_runner._load_report",
        _fake_report_loader,
    )
    factory, _, processes = _factory([{"timeout": True}])

    result = execute_matrix(_config(tmp_path), popen_factory=factory)

    child = result.aggregate["children"][0]
    assert child["outcome"] == "timeout"
    assert child["process"]["timed_out"] is True
    assert child["process"]["terminated"] is True
    assert child["process"]["killed"] is True
    assert processes[0].terminated and processes[0].killed
    assert result.exit_code == 2


def test_plan_and_loaded_artifact_hashes_fail_closed(tmp_path, monkeypatch):
    invalid = copy.deepcopy(_plan())
    invalid["cases"][0]["case_sha256"] = "short"
    with pytest.raises(MatrixAggregateError, match="case hash"):
        validate_matrix_plan(invalid)

    monkeypatch.setattr(
        "tools.virtual_workflows.matrix_runner._load_report",
        _fake_report_loader,
    )
    factory, _, _ = _factory([{}])
    result = execute_matrix(_config(tmp_path), popen_factory=factory)
    plan_path = result.aggregate_path.parent / "matrix_plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    with pytest.raises(MatrixAggregateError, match="hash mismatch"):
        load_matrix_aggregate(result.aggregate_path)
