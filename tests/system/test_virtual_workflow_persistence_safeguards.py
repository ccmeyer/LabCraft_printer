from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.virtual_workflows.journeys import PERSISTENCE_SAFEGUARD_REQUIRED_ASSERTIONS
from tools.virtual_workflows.persistence_safeguards import (
    EXPECTED_CASE_IDS,
    PERSISTENCE_SAFEGUARD_MATRIX_ID,
    get_persistence_safeguard_case,
)
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
            PERSISTENCE_SAFEGUARD_MATRIX_ID,
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
def test_persistence_fault_real_load_is_exact_inactive_and_nonmutating(
    tmp_path, case_id
):
    case = get_persistence_safeguard_case(case_id)
    report = _run_case(tmp_path, case_id)
    assert report["classification"]["status"] == "pass"
    assert not any(report["safety"]["hardware_interfaces"].values())
    workflow = report["metrics"]["workflow"]["values"]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert tuple(decisions) == PERSISTENCE_SAFEGUARD_REQUIRED_ASSERTIONS
    assert set(decisions.values()) == {"pass"}
    ui_actions = {
        row["action_id"]
        for row in workflow["action_results"]
        if row["interaction_surface"] == "ui"
    }
    assert case.operator_action_id in ui_actions
    assert "experiment.attempt_locked_activation_via_ui" in ui_actions
    values = report["metrics"]["persistence"]["values"]
    assert values["matrix_case"]["case"] == case.to_dict()
    fault = values["prelaunch_fault"]
    assert fault["fault_manifest"]["application_launched"] is False
    assert fault["fault_manifest"]["mutation_count"] == 1
    boundary = values["safeguard_boundary"]
    assert boundary["failed_checks"] == []
    assert all(boundary["checks"].values())
    assert boundary["before_sha256"] == boundary["after_sha256"]
