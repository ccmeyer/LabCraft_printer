from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.virtual_workflows.composition import JourneyRuntime
from tools.virtual_workflows.harness import AutomationHarness, AutomationHarnessConfig
from tools.virtual_workflows.joined_interaction_cases import (
    DESIGN_B_STOCK_ID,
    JOINED_INTERACTION_CASE,
    JOINED_INTERACTION_FIXTURE_PATH,
)
from tools.virtual_workflows.journeys import (
    JOINED_CALIBRATED_CHECKPOINT_REQUIRED_ASSERTIONS,
    JOINED_CALIBRATED_CHECKPOINT_REQUIRED_UI_ACTIONS,
    RANDOMIZED_CALIBRATION_REQUIRED_ASSERTIONS,
    RANDOMIZED_CALIBRATION_REQUIRED_SCREENSHOTS,
    RANDOMIZED_CALIBRATION_REQUIRED_UI_ACTIONS,
    get_journey_definition,
    run_joined_calibrated_checkpoint,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1


@pytest.mark.sil_lifecycle
def test_real_randomized_calibration_reload_lifecycle_reconciles_terminal_counts(
    qapp,
    tmp_path,
):
    harness = AutomationHarness(
        AutomationHarnessConfig(
            scenario_id="focused_randomized_calibration_checkpoint",
            workload_id="focused_randomized_calibration_checkpoint",
            output_root=tmp_path,
            visible=False,
            seed=1,
            speed_multiplier=1000.0,
            timeout_seconds=180.0,
            run_id="focused-randomized-calibration-checkpoint",
        )
    )
    runtime = JourneyRuntime(
        definition=SimpleNamespace(registry_id="unregistered_joined_checkpoint"),
        harness=harness,
        fixture=JOINED_INTERACTION_CASE.normalized(),
        fixture_path=JOINED_INTERACTION_FIXTURE_PATH,
    )
    teardown = None
    try:
        harness.start()
        run_joined_calibrated_checkpoint(runtime)

        assertion_rows = harness.assertion_results
        assert tuple(row["assertion_id"] for row in assertion_rows) == (
            JOINED_CALIBRATED_CHECKPOINT_REQUIRED_ASSERTIONS
        )
        assert {row["decision"] for row in assertion_rows} == {"pass"}
        ui_actions = {
            row["action_id"]
            for row in harness.context.action_results
            if row["interaction_surface"] == "ui"
        }
        assert ui_actions == JOINED_CALIBRATED_CHECKPOINT_REQUIRED_UI_ACTIONS
        assert not any(
            row["action_id"].startswith("manual_refuel.")
            for row in harness.context.action_results
        )
        assert set(harness.context.screenshots) == set(
            JOINED_INTERACTION_CASE.qualification.required_screenshots
        )
        assert assertion_rows[0]["evidence"]["machine_type"] == "SimulatedMachine"
        assert "NO HARDWARE" in assertion_rows[0]["evidence"]["banner_text"]

        lifecycle = runtime.observations["randomized_calibration_lifecycle"]
        prepared = lifecycle["prepared"]
        calibrated = lifecycle["calibrated_zero_progress"]
        assert prepared["prepared"]["plan_revision"] == 1
        assert calibrated["calibrated"]["plan_revision"] == 3
        assert calibrated["history_revisions"] == [1, 2, 3]
        assert calibrated["calibration_record"]["stock_id"] != DESIGN_B_STOCK_ID
        assert calibrated["calibration_record"]["printer_head_id"] == (
            "virtual-head-m11-design-a-v1"
        )
        assert calibrated["calibrated"]["total_added_droplets"] == 0
        assert all(calibrated["checks"].values())
        rotation = lifecycle["clean_session_rotation"]
        assert all(rotation["checks"].values())
        assert len(rotation["application_sessions"]) == 2
        assert len({
            row["application_session_id"]
            for row in rotation["application_sessions"]
        }) == 2
        assert rotation["loaded"]["resume_present"] is False
        assert rotation["activated"]["resume_present"] is True
        assert rotation["activated"]["total_added_droplets"] == 0
        remaining = lifecycle["remaining_calibrations"]
        assert remaining["history_revisions"] == [1, 2, 3, 4, 5]
        assert all(remaining["checks"].values())
        terminal = lifecycle["terminal"]
        assert terminal["terminal"]["plan_revision"] == 6
        assert terminal["terminal"]["plan_state"] == "completed"
        assert terminal["terminal"]["total_added_droplets"] == 80
        assert terminal["pass_starts"] == [
            row.stock_id for row in JOINED_INTERACTION_CASE.execution_passes
        ]
        assert len(terminal["intent_counts"]) == 24
        assert len(terminal["simulator_dispenses"]) == 24
        assert len(terminal["application_sessions"]) == 3
        assert all(terminal["checks"].values())
    finally:
        runtime.restore_all()
        teardown = harness.close()

    assert teardown["status"] == "pass"
    assert teardown["evidence"]["close_succeeded"] is True
    assert teardown["evidence"]["session_lock_present"] is False


@pytest.mark.sil_lifecycle
def test_registered_randomized_calibration_reload_execution_report(qapp, tmp_path):
    report = run_registered_scenario(
        JOINED_INTERACTION_CASE.case_id,
        output_root=tmp_path,
        visible=False,
        seed=JOINED_INTERACTION_CASE.qualification.cli_seed,
        speed_multiplier=1000.0,
        timeout_seconds=180.0,
        run_id="registered-randomized-calibration-reload",
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
    assert report["run"]["scenario_name"] == (
        "randomized_calibration_reload_execution"
    )
    assert report["workload"]["case_sha256"] == JOINED_INTERACTION_CASE.sha256()
    assert report["workload"]["count_oracle_sha256"] == (
        JOINED_INTERACTION_CASE.count_oracle_sha256()
    )
    assert report["workload"]["expected_completion_count"] == 24
    assert report["workload"]["expected_droplets"] == 80
    assert workflow["completed_stock_well_count"] == 24
    assert workflow["array_complete_count"] == 3
    assert workflow["action_count"] <= workflow["action_cap"] == 96
    assert {row["action_id"] for row in workflow["action_results"]} == (
        get_journey_definition(JOINED_INTERACTION_CASE.case_id).required_action_ids
    )
    assert {
        row["action_id"]
        for row in workflow["action_results"]
        if row["interaction_surface"] == "ui"
    } == RANDOMIZED_CALIBRATION_REQUIRED_UI_ACTIONS
    assert {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    } == {
        assertion_id: "pass"
        for assertion_id in RANDOMIZED_CALIBRATION_REQUIRED_ASSERTIONS
    }
    completed_reload = next(
        row
        for row in workflow["assertion_results"]
        if row["assertion_id"] == "execution.completed_terminal_reload_exact"
    )
    loader_evidence = completed_reload["evidence"]["loader"]
    assert loader_evidence["checks"][
        "printer_head_diagnostics_disabled"
    ] is True
    assert loader_evidence["checks"][
        "printer_head_diagnostics_tooltip"
    ] is True
    assert loader_evidence["printer_head_diagnostics_enabled"] is False
    assert "Historical experiments are analysis-only" in loader_evidence[
        "printer_head_diagnostics_tooltip"
    ]
    assert set(report["artifacts"]["screenshots"]) == set(
        RANDOMIZED_CALIBRATION_REQUIRED_SCREENSHOTS
    )

    persistence = report["metrics"]["persistence"]["values"]
    lifecycle = persistence["randomized_calibration_lifecycle"]
    terminal = lifecycle["terminal"]
    assert terminal["terminal"]["plan_revision"] == 6
    assert terminal["terminal"]["plan_state"] == "completed"
    assert terminal["terminal"]["total_added_droplets"] == 80
    assert len(terminal["intent_counts"]) == 24
    assert len(terminal["simulator_dispenses"]) == 24
    assert len(terminal["application_sessions"]) == 3
    assert all(terminal["checks"].values())
    assert report["metrics"]["queue"]["values"] == {
        "unexpected_starvation_count": 0,
        "queue_drained_at_terminal": True,
        "simulator_dispense_overflow_count": 0,
    }

    report_dir = Path(report["safety"]["report_dir"])
    assert not (Path(report["safety"]["scenario_root"]) / ".sil-session.lock").exists()
    for name in (
        "report.json",
        "summary.txt",
        "events.jsonl",
        "action_ledger.json",
        "assertion_ledger.json",
        "evidence_manifest.json",
    ):
        assert (report_dir / name).is_file()
