from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tools.virtual_workflows.actions import COMPOSED_DISCONNECT_ACTION_IDS
from tools.virtual_workflows.journeys import (
    DISCONNECT_REQUIRED_ASSERTIONS,
    DISCONNECT_REQUIRED_UI_ACTIONS,
    DISCONNECT_WORKLOAD_ID,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    fixture_well_ids,
    load_virtual_print_array_fixture,
)


def test_disconnect_fixture_contract_is_exact():
    fixture = load_virtual_print_array_fixture(scenario_id=DISCONNECT_WORKLOAD_ID)

    assert fixture["fixture_id"] == DISCONNECT_WORKLOAD_ID
    assert fixture["schema_version"] == 3
    assert fixture_well_ids(fixture) == tuple(f"A{column}" for column in range(1, 25))
    assert fixture["workload"]["completion_count"] == 24
    assert fixture["lifecycle"] == {
        "kind": "disconnect_fail_closed",
        "disconnect_after_completion_count": 6,
        "expected_canceled_intent_count": 2,
        "quiescence_observation_ms": 250,
    }


@pytest.mark.sil_lifecycle
def test_composed_disconnect_fail_closed_report(qapp, tmp_path):
    report = run_registered_scenario(
        DISCONNECT_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="composed-disconnect",
        seed=19,
    )
    validate_report_v1(report)
    workflow = report["metrics"]["workflow"]["values"]
    assert report["classification"]["status"] == "pass", json.dumps(
        {
            "errors": workflow["errors"],
            "failed_actions": [
                row for row in workflow["action_results"] if row["status"] == "fail"
            ],
            "assertions": workflow["assertion_results"],
        },
        indent=2,
    )
    assert report["run"]["scenario_name"] == "print_array_disconnect_fail_closed"
    assert report["workload"]["expected_completion_count"] == 24
    assert workflow["completed_stock_well_count"] == 6
    assert workflow["array_complete_count"] == 0
    assert workflow["errors"] == []
    assert workflow["unexpected_dialogs"] == []
    actions = workflow["action_results"]
    assert {row["action_id"] for row in actions} == COMPOSED_DISCONNECT_ACTION_IDS
    assert {row["status"] for row in actions} == {"pass"}
    assert {
        row["action_id"]: row["interaction_surface"]
        for row in actions
        if row["action_id"] in DISCONNECT_REQUIRED_UI_ACTIONS
    } == {action_id: "ui" for action_id in DISCONNECT_REQUIRED_UI_ACTIONS}
    assert {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    } == {assertion_id: "pass" for assertion_id in DISCONNECT_REQUIRED_ASSERTIONS}
    assert [row["name"] for row in workflow["lifecycle_milestones"]] == [
        "editor_opened",
        "generated",
        "ready",
        "printing",
        "disconnected",
        "recovery_ready",
    ]
    evidence = report["metrics"]["persistence"]["values"]["disconnect_fail_closed"]
    assert evidence["request"]["clicked_count"] == 6
    assert evidence["quiescence"]["starting_completion_count"] == 6
    assert evidence["quiescence"]["ending_completion_count"] == 6
    assert evidence["recovery"]["eligibility"]["status"] == "ready_to_resume"
    assert len(evidence["intent_reconciliation"]["discard_batches"]) == 1
    assert len(evidence["intent_reconciliation"]["discard_batches"][0]["intent_ids"]) == 2
    report_dir = Path(report["safety"]["report_dir"])
    for name in (
        "report.json",
        "summary.txt",
        "events.jsonl",
        "action_ledger.json",
        "assertion_ledger.json",
        "evidence_manifest.json",
    ):
        assert (report_dir / name).is_file()


@pytest.mark.sil_lifecycle
def test_disconnect_controlled_assertion_failure_retains_evidence(
    qapp, tmp_path, monkeypatch
):
    from tools.virtual_workflows import journeys

    original = journeys.disconnect_fail_closed_assertions

    def fail_boundary(*args, **kwargs):
        results = list(original(*args, **kwargs))
        results[1] = replace(
            results[1],
            decision="fail",
            message="synthetic disconnect-boundary evidence failure",
        )
        return tuple(results)

    monkeypatch.setattr(journeys, "disconnect_fail_closed_assertions", fail_boundary)
    report = run_registered_scenario(
        DISCONNECT_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        seed=23,
    )
    validate_report_v1(report)
    assert report["classification"]["status"] == "fail"
    workflow = report["metrics"]["workflow"]["values"]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert decisions["execution.disconnect_requested"] == "pass"
    assert decisions["execution.disconnect_fail_closed"] == "fail"
    assert decisions["execution.disconnect_recovery_ready"] == "incomplete"
    report_dir = Path(report["safety"]["report_dir"])
    assert (report_dir / "failure_traceback.txt").is_file()
    assert (report_dir / "action_ledger.json").is_file()
    assert (report_dir / "assertion_ledger.json").is_file()
    assert (report_dir / "evidence_manifest.json").is_file()
    assert not (Path(report["safety"]["scenario_root"]) / ".sil-session.lock").exists()
