from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.virtual_workflows.editor_safeguards import (
    EDITOR_SAFEGUARD_MATRIX_ID,
    EXPECTED_CASE_IDS,
    get_editor_safeguard_case,
)
from tools.virtual_workflows.journeys import EDITOR_SAFEGUARD_REQUIRED_ASSERTIONS
from tools.virtual_workflows.report import validate_report_v1


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "tools" / "run_virtual_workflow.py"


def _run_case(tmp_path: Path, case_id: str) -> dict:
    output_root = tmp_path / case_id
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--matrix",
            EDITOR_SAFEGUARD_MATRIX_ID,
            "--case",
            case_id,
            "--output-root",
            str(output_root),
            "--seed",
            "1",
            "--speed-multiplier",
            "1000",
            "--timeout-seconds",
            "90",
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    assert process.returncode == 0, process.stderr or process.stdout
    reports = tuple(output_root.rglob("report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    validate_report_v1(report)
    return report


@pytest.mark.sil_lifecycle
@pytest.mark.parametrize("case_id", EXPECTED_CASE_IDS)
def test_editor_safeguard_real_operator_action_is_exact_and_quiescent(
    tmp_path, case_id
):
    case = get_editor_safeguard_case(case_id)
    report = _run_case(tmp_path, case_id)

    assert report["classification"]["status"] == "pass"
    assert not any(report["safety"]["hardware_interfaces"].values())
    assert report["workload"]["workload_id"] == EDITOR_SAFEGUARD_MATRIX_ID
    workflow = report["metrics"]["workflow"]["values"]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert tuple(decisions) == EDITOR_SAFEGUARD_REQUIRED_ASSERTIONS
    assert set(decisions.values()) == {"pass"}
    ui_actions = {
        row["action_id"]
        for row in workflow["action_results"]
        if row["interaction_surface"] == "ui"
    }
    assert case.operator_action_id in ui_actions

    values = report["metrics"]["persistence"]["values"]
    matrix_case = values["matrix_case"]
    assert matrix_case["case"] == case.to_dict()
    assert matrix_case["case_sha256"] == case.contract_sha256
    boundary = values["safeguard_boundary"]
    assert boundary["failed_checks"] == []
    assert all(boundary["checks"].values())
    assert boundary["expected"] == case.expected.to_dict()
    assert boundary["observed"] == case.expected.to_dict()
    assert boundary["before_sha256"] == boundary["after_sha256"]
    assert boundary["before"]["dispatch"] == {
        "commands": 0,
        "completions": 0,
        "drops": 0,
        "machine_intents": 0,
    }
