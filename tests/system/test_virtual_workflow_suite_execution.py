from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.suite_runner import load_aggregate


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "tools" / "run_virtual_workflow.py"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, timeout: float = 120.0):
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(timeout=timeout)
    assert process.returncode == 0, stderr or stdout
    return process, stdout


def _printed_path(stdout: str, prefix: str) -> Path:
    line = next(item for item in stdout.splitlines() if item.startswith(prefix))
    return Path(line.removeprefix(prefix)).resolve()


@pytest.mark.sil_lifecycle
def test_standard_suite_runs_in_fresh_process_and_direct_smoke_still_works(
    tmp_path,
):
    suite_process, suite_stdout = _run(
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
        ]
    )

    aggregate_path = _printed_path(suite_stdout, "Aggregate: ")
    aggregate = load_aggregate(aggregate_path)
    child = aggregate["children"][0]
    child_report_path = (
        aggregate_path.parent / child["report"]["path"]
    ).resolve()
    child_report = json.loads(child_report_path.read_text(encoding="utf-8"))
    validate_report_v1(child_report)

    assert aggregate["classification"]["status"] == "pass"
    assert aggregate["run"]["selector"]["kind"] == "suite"
    assert aggregate["run"]["selector"]["id"] == "standard"
    assert aggregate["run"]["parent_pid"] > 0
    assert child["process"]["pid"] != aggregate["run"]["parent_pid"]
    assert child["report"]["sha256"] == _sha256(child_report_path)
    assert child_report["workload"]["workload_id"] == (
        "virtual_print_array_24_v1"
    )
    assert child_report["run"]["seed"] == 1

    direct_root = tmp_path / "direct"
    _, direct_stdout = _run(
        [
            sys.executable,
            str(RUNNER),
            "--scenario",
            "virtual_print_array_24_v1",
            "--output-root",
            str(direct_root),
            "--seed",
            "1",
            "--speed-multiplier",
            "1000",
            "--timeout-seconds",
            "60",
        ]
    )
    assert "Status: pass" in direct_stdout
    direct_reports = tuple(direct_root.rglob("report.json"))
    assert len(direct_reports) == 1
    direct_report = json.loads(
        direct_reports[0].read_text(encoding="utf-8")
    )
    validate_report_v1(direct_report)
    assert direct_report["classification"]["status"] == "pass"
