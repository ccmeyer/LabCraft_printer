from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.virtual_workflows.actions import PRINT_ARRAY_LIFECYCLE_ACTION_IDS
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    SOFT_STOP_RESUME_WORKLOAD_ID,
    VirtualPrintArrayScenarioConfig,
    fixture_well_ids,
    load_virtual_print_array_fixture,
    run_virtual_print_array_scenario,
)


def test_soft_stop_resume_fixture_contract_is_exact():
    fixture = load_virtual_print_array_fixture(
        scenario_id=SOFT_STOP_RESUME_WORKLOAD_ID
    )

    assert fixture["schema_version"] == 3
    assert fixture["fixture_id"] == SOFT_STOP_RESUME_WORKLOAD_ID
    assert fixture["plate"] == {
        "name": "shallow-384_well_plate",
        "rows": 16,
        "columns": 24,
        "included_rows": ["A"],
        "serpentine": True,
    }
    assert fixture["workload"] == {
        "target_dispenses_per_stock_per_well": 1,
        "well_count": 24,
        "stock_count": 1,
        "array_passes": 1,
        "completion_count": 24,
    }
    assert fixture["simulation"] == {
        "dispense_frequency_hz": 20,
        "lookahead_wells": 2,
        "staging_slot": 0,
    }
    assert fixture["lifecycle"] == {
        "kind": "soft_stop_resume",
        "request_after_completion_count": 6,
        "maximum_completion_catchup": 2,
        "quiescence_observation_ms": 250,
    }
    assert fixture_well_ids(fixture) == tuple(
        f"A{column}" for column in range(1, 25)
    )
    assert fixture["stocks"][0]["printer_head"]["printer_head_id"] == (
        "virtual-head-soft-stop-24-v1"
    )


@pytest.mark.sil_lifecycle
def test_soft_stop_resume_lifecycle_report(qapp, tmp_path):
    report = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            scenario_id=SOFT_STOP_RESUME_WORKLOAD_ID,
            output_root=tmp_path,
            timeout_seconds=60,
            run_id="soft-stop-resume-lifecycle",
        )
    )

    validate_report_v1(report)
    assert report["classification"]["status"] == "pass", json.dumps(
        report["metrics"]["workflow"]["values"]["action_results"],
        indent=2,
    )
    assert report["run"]["scenario_name"] == "print_array_soft_stop_resume"
    workflow = report["metrics"]["workflow"]["values"]
    assert {
        item["action_id"] for item in workflow["action_results"]
    } == PRINT_ARRAY_LIFECYCLE_ACTION_IDS
    assert {item["status"] for item in workflow["action_results"]} == {"pass"}
    assert [item["name"] for item in workflow["lifecycle_milestones"]] == [
        "ready",
        "printing",
        "stop_requested",
        "stopped",
        "resumed",
        "completed",
    ]
    assert {
        item["assertion_id"]: item["decision"]
        for item in workflow["assertion_results"]
    } == {
        assertion_id: "pass"
        for assertion_id in (
            "sil.host_hardware_disabled",
            "ui.real_app_constructed",
            "execution.soft_stop_requested",
            "execution.soft_stop_boundary_valid",
            "execution.stopped_boundary_quiescent",
            "execution.resume_exactly_once",
            "execution.expected_completions",
            "execution.intent_durability_exact",
            "execution.terminal_bundle_valid",
            "artifacts.required_present",
        )
    }
    assert [item["title"] for item in workflow["dialogs"]] == [
        "Start Print Array",
        "Evaporation Plate Dock Check",
        "Resume Print Array",
    ]

    persistence = report["metrics"]["persistence"]["values"]
    evidence = persistence["soft_stop_resume"]
    assert evidence["request"]["clicked_count"] == 6
    stopped = evidence["stopped_checkpoint"]
    assert 1 <= stopped["completion_catchup"] <= 2
    assert stopped["checkpoint_state"] == "paused"
    assert stopped["checkpoint_intent_count"] == 0
    assert stopped["eligibility_status"] == "ready_to_resume"
    assert evidence["quiescence"]["starting_completion_count"] == (
        evidence["quiescence"]["ending_completion_count"]
    )
    assert evidence["quiescence"]["starting_progress_count"] == (
        evidence["quiescence"]["ending_progress_count"]
    )
    intents = evidence["intent_reconciliation"]
    assert intents["completed_count"] == 24
    assert intents["discarded_count"] >= 1
    assert intents["begin_count"] == 24 + intents["discarded_count"]
    assert persistence["terminal_plan_state"] == "completed"
    assert persistence["stock_well_completion_count"] == 24
    assert persistence["progress_snapshot"]["mode_counts"] == {
        "full_rebuild": 0,
        "cached_update": 24,
    }
    expected_resume_writes = (
        intents["begin_count"] * 2
        + intents["completed_count"]
        + intents["discard_batch_count"]
    )
    assert persistence["authoritative_io"]["resume_save_fsync_count"] == (
        expected_resume_writes
    )
    assert persistence["authoritative_io"]["resume_save_replace_count"] == (
        expected_resume_writes
    )
    assert report["metrics"]["responsiveness"]["status"] == "not_applicable"
    assert report["metrics"]["resources"]["status"] == "not_applicable"

    report_dir = Path(report["safety"]["scenario_root"]).parent
    assert set(report["artifacts"]["screenshots"]) == {
        "ready",
        "printing",
        "stop_requested",
        "stopped",
        "resumed",
        "completed",
    }
    assert all(
        (report_dir / relative).stat().st_size > 0
        for relative in report["artifacts"]["screenshots"].values()
    )


@pytest.mark.sil_lifecycle
def test_soft_stop_failure_retains_paused_action_evidence(
    qapp,
    tmp_path,
    monkeypatch,
):
    from tools.virtual_workflows import scenarios

    monkeypatch.setattr(
        scenarios,
        "_validate_soft_stop_paused_scenario",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("synthetic paused-boundary failure")
        ),
    )
    report = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            scenario_id=SOFT_STOP_RESUME_WORKLOAD_ID,
            output_root=tmp_path,
            timeout_seconds=60,
        )
    )

    validate_report_v1(report)
    assert report["classification"]["status"] == "fail"
    workflow = report["metrics"]["workflow"]["values"]
    failed = [
        item for item in workflow["action_results"] if item["status"] == "fail"
    ]
    assert failed[-1]["action_id"] == "validation.paused_bundle"
    assertions = {
        item["assertion_id"]: item["decision"]
        for item in workflow["assertion_results"]
    }
    assert assertions["execution.soft_stop_requested"] == "pass"
    assert assertions["execution.soft_stop_boundary_valid"] == "fail"
    assert assertions["execution.stopped_boundary_quiescent"] == "incomplete"
    assert report["artifacts"]["failure_traceback"] == "failure_traceback.txt"
