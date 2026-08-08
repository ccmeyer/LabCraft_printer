from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.virtual_workflows.journeys import (
    EXPERIMENT_DESIGN_REQUIRED_ASSERTIONS,
    EXPERIMENT_DESIGN_REQUIRED_SCREENSHOTS,
    EXPERIMENT_DESIGN_REQUIRED_UI_ACTIONS,
)
from tools.virtual_workflows.matrices import EXPERIMENT_DESIGN_MATRIX_ID
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
            EXPERIMENT_DESIGN_MATRIX_ID,
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
@pytest.mark.parametrize(
    ("case_id", "expected_assignments"),
    (
        pytest.param(
            "single_reagent_control",
            {"A1": "R1"},
            id="single_reagent_control",
        ),
        pytest.param(
            "multi_reagent_seed_4321",
            {
                "A1": "R8",
                "A2": "R6",
                "A3": "R3",
                "A4": "R2",
                "A5": "R7",
                "A6": "R4",
                "A7": "R1",
                "A8": "R5",
            },
            id="multi_reagent_seed_4321",
        ),
    ),
)
def test_experiment_design_positive_case_is_exact(
    tmp_path,
    case_id,
    expected_assignments,
):
    report = _run_case(tmp_path, case_id)

    assert report["classification"]["status"] == "pass"
    assert report["workload"]["workload_id"] == EXPERIMENT_DESIGN_MATRIX_ID
    assert not any(report["safety"]["hardware_interfaces"].values())
    workflow = report["metrics"]["workflow"]["values"]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert tuple(decisions) == EXPERIMENT_DESIGN_REQUIRED_ASSERTIONS
    assert decisions == {
        assertion_id: "pass"
        for assertion_id in EXPERIMENT_DESIGN_REQUIRED_ASSERTIONS
    }
    ui_actions = {
        row["action_id"]
        for row in workflow["action_results"]
        if row["interaction_surface"] == "ui"
    }
    assert ui_actions == set(EXPERIMENT_DESIGN_REQUIRED_UI_ACTIONS)

    values = report["metrics"]["persistence"]["values"]
    case_evidence = values["matrix_case"]
    assert case_evidence["case"]["case_id"] == case_id
    assert all(case_evidence["outcome"]["oracle_checks"].values())
    assert all(case_evidence["outcome"]["runtime_checks"].values())
    prepared = values["experiment_design_evidence"]["prepared_oracle"]
    reconstructed = values["experiment_design_evidence"]["reload_activation"]
    assert prepared["observed"]["runtime_assignments"] == expected_assignments
    assert reconstructed["reconstructed"]["runtime_assignments"] == (
        expected_assignments
    )
    assert reconstructed["checks"]["runtime_inactive"] is True
    assert reconstructed["changed_paths"] == []
    assert set(report["artifacts"]["screenshots"]) == set(
        EXPERIMENT_DESIGN_REQUIRED_SCREENSHOTS
    )
