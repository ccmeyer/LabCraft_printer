from __future__ import annotations

import sys
import json
from types import SimpleNamespace

import pytest

from tools.virtual_workflows.composition import JourneyRuntime
from tools.virtual_workflows.harness import AutomationHarness, AutomationHarnessConfig
from tools.virtual_workflows.journeys import (
    OPTIMIZER_360_CALIBRATION_CHAIN_REQUIRED_ASSERTIONS,
    OPTIMIZER_360_FIRST_CALIBRATION_REQUIRED_ASSERTIONS,
    run_optimizer_360_calibration_chain,
    run_optimizer_360_first_calibration_checkpoint,
)
from tools.virtual_workflows.optimizer_360_cases import (
    OPTIMIZER_360_CASE,
    OPTIMIZER_360_FIXTURE_PATH,
    OPTIMIZER_360_STOCK_IDS,
    RANGE_A_STOCK_ID,
)


pytestmark = [
    pytest.mark.sil_stress,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows host-stress only"),
]


def test_real_optimizer_360_editor_and_first_calibration_are_exact(qapp, tmp_path):
    case = OPTIMIZER_360_CASE
    harness = AutomationHarness(
        AutomationHarnessConfig(
            scenario_id="focused_optimizer_360_first_calibration",
            workload_id="focused_optimizer_360_first_calibration",
            output_root=tmp_path,
            visible=False,
            seed=case.qualification.cli_seed,
            speed_multiplier=1000.0,
            timeout_seconds=case.qualification.offscreen_timeout_seconds,
            run_id="focused-optimizer-360-first-calibration",
        )
    )
    runtime = JourneyRuntime(
        definition=SimpleNamespace(
            registry_id="unregistered_optimizer_360_first_calibration"
        ),
        harness=harness,
        fixture={"case_id": case.case_id},
        fixture_path=OPTIMIZER_360_FIXTURE_PATH,
    )
    teardown = None
    try:
        harness.start()
        run_optimizer_360_first_calibration_checkpoint(runtime)

        assertions = harness.assertion_results
        assert tuple(row["assertion_id"] for row in assertions) == (
            OPTIMIZER_360_FIRST_CALIBRATION_REQUIRED_ASSERTIONS
        )
        assert {row["decision"] for row in assertions} == {"pass"}, json.dumps(
            assertions, indent=2
        )
        lifecycle = runtime.observations["optimizer_360_calibration_lifecycle"]
        prepared = lifecycle["prepared"]
        assert prepared["approximate_targets"] == 7
        assert prepared["unreachable_targets"] == 0
        assert prepared["expected_stocks"] == {
            "Range A_222.22_x": "222.22222222222223",
            "Range B_100.00_x": "100",
            "Range C_555.56_x": "555.5555555555555",
            "Range D_20.00_x": "20",
            "Water_1.00_--": "1",
        }
        calibrated = lifecycle["range_a_calibrated"]
        assert calibrated["calibrated"]["plan_revision"] == 3
        assert calibrated["calibrated"]["total_added_droplets"] == 0
        assert calibrated["history_revisions"] == [1, 2, 3]
        assert calibrated["calibration_record"]["stock_id"] == RANGE_A_STOCK_ID
        assert calibrated["calibration_record"]["printer_head_id"] == (
            "virtual-head-m11a-range-a-v1"
        )
        assert calibrated["calibration_record"]["pw_us"] == 1400
        assert calibrated["calibration_record"]["effective_volume_nL"] == 10.8
        assert all(calibrated["checks"].values())
        assert set(harness.context.screenshots) == {
            "optimizer_stocks_generated",
            "prepared_randomized",
            "range_a_calibrated",
        }
        assert len(harness.context.action_results) <= case.qualification.action_cap
    finally:
        runtime.restore_all()
        teardown = harness.close()

    assert teardown["status"] == "pass"
    assert teardown["evidence"]["close_succeeded"] is True
    assert teardown["evidence"]["session_lock_present"] is False


def test_optimizer_360_fresh_rotation_and_all_calibrations_are_exact(qapp, tmp_path):
    case = OPTIMIZER_360_CASE
    harness = AutomationHarness(
        AutomationHarnessConfig(
            scenario_id="focused_optimizer_360_calibration_chain",
            workload_id="focused_optimizer_360_calibration_chain",
            output_root=tmp_path,
            visible=False,
            seed=case.qualification.cli_seed,
            speed_multiplier=1000.0,
            timeout_seconds=case.qualification.offscreen_timeout_seconds,
            run_id="focused-optimizer-360-calibration-chain",
        )
    )
    runtime = JourneyRuntime(
        definition=SimpleNamespace(
            registry_id="unregistered_optimizer_360_calibration_chain"
        ),
        harness=harness,
        fixture={"case_id": case.case_id},
        fixture_path=OPTIMIZER_360_FIXTURE_PATH,
    )
    teardown = None
    try:
        harness.start()
        run_optimizer_360_calibration_chain(runtime)

        assertions = harness.assertion_results
        assert tuple(row["assertion_id"] for row in assertions) == (
            OPTIMIZER_360_CALIBRATION_CHAIN_REQUIRED_ASSERTIONS
        )
        assert {row["decision"] for row in assertions} == {"pass"}, json.dumps(
            assertions, indent=2
        )
        lifecycle = runtime.observations["optimizer_360_calibration_lifecycle"]
        rotation = lifecycle["clean_session_rotation"]
        assert len(rotation["application_sessions"]) == 2
        assert rotation["loaded"]["resume_present"] is False
        assert rotation["activated"]["resume_present"] is True
        assert rotation["activated"]["total_added_droplets"] == 0
        remaining = lifecycle["remaining_calibrations"]
        assert remaining["history_revisions"] == [1, 2, 3, 4, 5, 6, 7]
        assert set(remaining["records"]) == set(OPTIMIZER_360_STOCK_IDS)
        assert all(remaining["identity_checks"].values())
        assert all(remaining["checks"].values())
        assert set(harness.context.screenshots) == {
            "optimizer_stocks_generated",
            "prepared_randomized",
            "range_a_calibrated",
            "fresh_loaded",
            "fresh_activated",
            "range_b_calibrated",
            "range_c_calibrated",
            "range_d_calibrated",
            "all_stocks_calibrated",
        }
    finally:
        runtime.restore_all()
        teardown = harness.close()

    assert teardown["status"] == "pass"
    assert teardown["evidence"]["close_succeeded"] is True
    assert teardown["evidence"]["session_lock_present"] is False
