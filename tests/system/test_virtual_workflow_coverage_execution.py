from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.virtual_workflows.coverage import load_coverage_evaluation
from tools.virtual_workflows.suite_runner import load_aggregate


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "tools" / "run_virtual_workflow.py"


def _run(command: list[str], *, expected: int, timeout: float = 150.0) -> str:
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    process = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    assert process.returncode == expected, process.stderr or process.stdout
    return process.stdout


def _printed_path(stdout: str, prefix: str) -> Path:
    line = next(value for value in stdout.splitlines() if value.startswith(prefix))
    return Path(line.removeprefix(prefix)).resolve()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.sil_lifecycle
def test_standard_suite_coverage_is_hashed_current_and_portfolio_incomplete(tmp_path):
    suite_stdout = _run(
        [
            sys.executable,
            str(RUNNER),
            "--suite",
            "standard",
            "--output-root",
            str(tmp_path / "suites"),
            "--seed",
            "1",
            "--speed-multiplier",
            "1000",
        ],
        expected=0,
    )
    aggregate_path = _printed_path(suite_stdout, "Aggregate: ")
    aggregate = load_aggregate(aggregate_path)
    assert aggregate["classification"]["status"] == "pass"

    coverage_stdout = _run(
        [
            sys.executable,
            str(RUNNER),
            "--coverage-from",
            str(aggregate_path),
            "--output-root",
            str(tmp_path / "suites"),
        ],
        expected=2,
    )
    coverage_path = _printed_path(coverage_stdout, "Coverage: ")
    coverage = load_coverage_evaluation(coverage_path)

    assert coverage["inputs"][0]["sha256"] == _sha256(aggregate_path)
    assert coverage["classification"]["status"] == "fail"
    assert coverage["classification"]["counts"]["incomplete"] == 4
    assert coverage["classification"]["counts"]["fail"] == 0
    smoke = next(
        row
        for row in coverage["scenarios"]
        if row["scenario_id"] == "print_array_smoke_24_v1"
    )
    assert smoke["status"] == "pass"
    assert smoke["source_state"] == "current"
    assert all(
        row["status"] == "incomplete" for row in coverage["capabilities"]
    )
    assert "Counts:" in coverage_stdout
    assert f"Coverage SHA-256: {_sha256(coverage_path)}" in coverage_stdout
