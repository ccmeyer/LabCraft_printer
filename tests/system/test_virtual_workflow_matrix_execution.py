from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.virtual_workflows.matrices import (
    CALIBRATION_REQUANTIZATION_MATRIX_ID,
    MIXED_MODE_MATRIX_ID,
)
from tools.virtual_workflows.report import validate_report_v1


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "tools" / "run_virtual_workflow.py"


def _run_case(
    tmp_path: Path,
    case_id: str,
    matrix_id: str = MIXED_MODE_MATRIX_ID,
) -> dict:
    output_root = tmp_path / case_id
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--matrix",
            matrix_id,
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
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    validate_report_v1(payload)
    return payload


@pytest.mark.sil_lifecycle
def test_matrix_cases_reuse_one_journey_for_positive_and_safe_blocks(tmp_path):
    positive = _run_case(tmp_path, "mixed_ab_baseline_pass")
    late_block = _run_case(tmp_path, "stream_pair_ba_alternate_second_rise")
    blocked = _run_case(tmp_path, "mixed_ba_baseline_unclear")

    assert positive["classification"]["status"] == "pass"
    assert positive["workload"]["workload_id"] == MIXED_MODE_MATRIX_ID
    positive_case = positive["metrics"]["persistence"]["values"]["matrix_case"]
    assert positive_case["case"]["expected_completion_count"] == 48
    assert positive_case["outcome"]["observed_completion_count"] == 48
    assert positive_case["outcome"]["expected_terminal"] == "completed"

    assert late_block["classification"]["status"] == "pass"
    late_case = late_block["metrics"]["persistence"]["values"]["matrix_case"]
    assert late_case["outcome"]["observed_completion_count"] == 24
    assert late_case["outcome"]["block"]["completion_count_before"] == 24
    assert late_case["outcome"]["block"]["completion_count_after"] == 24
    blocked_head = late_case["outcome"]["block"]["printer_head_id"]
    matching = [
        row
        for row in late_case["outcome"]["persisted_manual_refuel_checks"]
        if row["printer_head_id"] == blocked_head
    ]
    assert len(matching) == 1
    assert matching[0]["status"] == "failed"
    assert matching[0]["operator_judgment"] == "level_rose"

    assert blocked["classification"]["status"] == "pass"
    blocked_case = blocked["metrics"]["persistence"]["values"]["matrix_case"]
    assert blocked_case["case"]["expected_completion_count"] == 0
    outcome = blocked_case["outcome"]
    assert outcome["observed_completion_count"] == 0
    assert outcome["expected_terminal"] == "manual_refuel_cancelled"
    assert outcome["block"]["completion_count_before"] == 0
    assert outcome["block"]["completion_count_after"] == 0
    assert outcome["block"]["queue_drained"] is True
    assert [row["title"] for row in outcome["block"]["dialogs"]] == [
        "Start Print Array",
        "Manual Refuel Check Required",
    ]


@pytest.mark.sil_lifecycle
def test_calibration_requantization_matrix_executes_exact_catalog_counts(tmp_path):
    expected = {
        "droplet_idempotent_10_to_10": (10, 10),
        "droplet_volume_increase_10_to_9": (10, 9),
        "droplet_volume_decrease_10_to_11": (10, 11),
    }
    for case_id, (prepared, requantized) in expected.items():
        report = _run_case(
            tmp_path,
            case_id,
            CALIBRATION_REQUANTIZATION_MATRIX_ID,
        )
        assert report["classification"]["status"] == "pass"
        assert report["workload"]["workload_id"] == (
            CALIBRATION_REQUANTIZATION_MATRIX_ID
        )
        values = report["metrics"]["persistence"]["values"]
        evidence = values["dispense_count_evidence"]
        assert evidence["oracle_scope"] == (
            "calibration_requantization_v1_catalog_oracle"
        )
        assert evidence["count_oracle"]["prepared_count"] == prepared
        assert evidence["count_oracle"]["requantized_count"] == requantized
        assert evidence["reconciliation"]["passed"] is True
        assert len(evidence["command_join"]["joined_commands"]) == 24
        assert values["matrix_case"]["outcome"][
            "observed_completion_count"
        ] == 24
