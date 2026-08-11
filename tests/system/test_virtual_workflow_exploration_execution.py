from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.virtual_workflows.exploration import CAMPAIGN_ID, MAX_ACTIONS
from tools.virtual_workflows.report import validate_report_v1


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "tools" / "run_virtual_workflow.py"


def _run_sequence(tmp_path: Path, sequence_id: str) -> dict:
    output_root = tmp_path / sequence_id
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--exploration",
            CAMPAIGN_ID,
            "--sequence",
            sequence_id,
            "--output-root",
            str(output_root),
            "--speed-multiplier",
            "1000",
            "--timeout-seconds",
            "60",
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=90,
        check=False,
    )
    assert process.returncode == 0, process.stderr or process.stdout
    reports = tuple(output_root.rglob("report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    validate_report_v1(report)
    return report


@pytest.mark.sil_lifecycle
def test_legal_exploration_sequence_reuses_editor_and_recovers(tmp_path):
    report = _run_sequence(tmp_path, "seed_7_legal")

    assert report["classification"]["status"] == "pass"
    assert report["run"]["seed"] == 7
    workflow = report["metrics"]["workflow"]["values"]
    sequence = workflow["sequence_exploration"]
    assert sequence["sequence"]["sequence_id"] == "seed_7_legal"
    assert sequence["sequence"]["rename_first"] is True
    assert sequence["rejection_evidence"] == []
    assert len(workflow["action_results"]) <= MAX_ACTIONS
    assert workflow["unexpected_dialogs"] == []
    assert workflow["errors"] == []
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert decisions["exploration.sequence_plan_applied"] == "pass"
    assert decisions["exploration.expected_rejection_safe"] == "pass"
    assert decisions["exploration.recovery_terminal_valid"] == "pass"
    assert sequence["terminal_recovery"]["checks"]["prepared"] is True
    assert sequence["terminal_recovery"]["checks"]["runtime_inactive"] is True


@pytest.mark.sil_lifecycle
def test_illegal_exploration_sequence_rejects_invalid_finalize_and_recovers(
    tmp_path,
):
    report = _run_sequence(tmp_path, "seed_101_illegal")

    assert report["classification"]["status"] == "pass"
    assert report["run"]["seed"] == 101
    workflow = report["metrics"]["workflow"]["values"]
    sequence = workflow["sequence_exploration"]
    assert sequence["sequence"]["edit_cycles"] == 2
    assert len(sequence["rejection_evidence"]) == 1
    rejection = sequence["rejection_evidence"][0]
    assert rejection["safe"] is True
    assert rejection["activation_count"] == 1
    assert rejection["warning"] == {
        "entered": True,
        "title": "Invalid volumes",
        "type": "QMessageBox",
        "dismissed": True,
    }
    assert rejection["invalid_volumes"]["printed_volume_nL"] > (
        rejection["invalid_volumes"]["final_volume_nL"]
    )
    assert rejection["before"] == rejection["after"]
    assert len(workflow["action_results"]) <= MAX_ACTIONS
    assert workflow["unexpected_dialogs"] == []
    assert workflow["errors"] == []
    assert sequence["terminal_recovery"]["checks"]["prepared"] is True
    assert sequence["terminal_recovery"]["checks"]["runtime_inactive"] is True
