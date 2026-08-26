from __future__ import annotations

import json
import sys

import pytest

from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.resolution_stock_cases import (
    IMPORT_CASE_ID,
    PROGRESS_GUARD_CASE_ID,
    SINGLE_CASE,
    SINGLE_CASE_ID,
    TWO_STOCK_CASE,
    TWO_STOCK_CASE_ID,
)


pytestmark = [
    pytest.mark.sil_lifecycle,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows host-SIL only"),
]


@pytest.mark.parametrize(
    ("case_id", "case"),
    ((SINGLE_CASE_ID, SINGLE_CASE), (TWO_STOCK_CASE_ID, TWO_STOCK_CASE)),
)
def test_registered_resolution_stock_terminal_lifecycle(qapp, tmp_path, case_id, case):
    report = run_registered_scenario(
        case_id,
        output_root=tmp_path,
        visible=False,
        seed=case.qualification.cli_seed,
        speed_multiplier=1000.0,
        timeout_seconds=case.qualification.offscreen_timeout_seconds,
        run_id=f"focused-{case_id}",
    )
    validate_report_v1(report)
    workflow = report["metrics"]["workflow"]["values"]
    assert report["classification"]["status"] == "pass", json.dumps(
        {
            "errors": workflow["errors"],
            "assertions": [
                row
                for row in workflow["assertion_results"]
                if row["decision"] != "pass"
            ],
            "failed_actions": [
                row for row in workflow["action_results"] if row["status"] == "fail"
            ],
        },
        indent=2,
    )
    assert report["workload"]["case_sha256"] == case.sha256()
    assert workflow["completed_stock_well_count"] == case.terminal.expected_intents
    terminal = report["metrics"]["persistence"]["values"][
        "resolution_stock_lifecycle"
    ]["terminal"]
    assert terminal["terminal"]["plan_revision"] == 6
    assert terminal["terminal"]["plan_state"] == "completed"
    assert terminal["terminal"]["total_added_droplets"] == case.terminal.expected_droplets
    assert len(terminal["intent_counts"]) == case.terminal.expected_intents
    assert len(terminal["simulator_dispenses"]) == case.terminal.expected_intents
    assert all(terminal["checks"].values())


def test_registered_same_reagent_progress_guard(qapp, tmp_path):
    report = run_registered_scenario(
        PROGRESS_GUARD_CASE_ID,
        output_root=tmp_path,
        visible=False,
        seed=1,
        speed_multiplier=1000.0,
        timeout_seconds=180,
        run_id="focused-same-reagent-progress-guard",
    )
    validate_report_v1(report)
    workflow = report["metrics"]["workflow"]["values"]
    assert report["classification"]["status"] == "pass", json.dumps(
        [
            row
            for row in workflow["assertion_results"]
            if row["decision"] != "pass"
        ],
        indent=2,
    )
    guard = report["metrics"]["persistence"]["values"][
        "resolution_stock_lifecycle"
    ]["progress_guard"]
    assert guard["progressed_drops"] == 5
    assert guard["apply_state"]["enabled"] is False
    assert guard["apply_state"]["eligibility"]["code"] == "affected_stock_progress"
    assert all(guard["checks"].values())
    assert workflow["completed_stock_well_count"] == 2


def test_registered_two_stock_csv_import_preview_reuse(qapp, tmp_path):
    report = run_registered_scenario(
        IMPORT_CASE_ID,
        output_root=tmp_path,
        visible=False,
        seed=1,
        speed_multiplier=1000.0,
        timeout_seconds=180,
        run_id="focused-two-stock-csv-import",
    )
    validate_report_v1(report)
    workflow = report["metrics"]["workflow"]["values"]
    assert report["classification"]["status"] == "pass", json.dumps(
        [
            row
            for row in workflow["assertion_results"]
            if row["decision"] != "pass"
        ],
        indent=2,
    )
    oracle = report["metrics"]["persistence"]["values"][
        "two_stock_import_lifecycle"
    ]["oracle"]
    assert oracle["preview_labels"] == ["Stock 1 of 2", "Stock 2 of 2"]
    assert oracle["outer_optimizer_calls"] == 0
    assert oracle["optimizer"]["stock_allocation_reused_import_plan"] is True
    assert all(oracle["checks"].values())
