from __future__ import annotations

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
    run_joined_calibrated_checkpoint,
)


@pytest.mark.sil_lifecycle
def test_real_randomized_editor_and_design_a_calibration_reach_zero_progress_checkpoint(
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
            timeout_seconds=90.0,
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
            row["action_id"].startswith(("array.", "manual_refuel."))
            for row in harness.context.action_results
        )
        assert set(harness.context.screenshots) == {
            "design_generated",
            "prepared_randomized",
            "calibrated_zero_progress",
            "fresh_loaded",
            "fresh_activated",
        }
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
    finally:
        runtime.restore_all()
        teardown = harness.close()

    assert teardown["status"] == "pass"
    assert teardown["evidence"]["close_succeeded"] is True
    assert teardown["evidence"]["session_lock_present"] is False
