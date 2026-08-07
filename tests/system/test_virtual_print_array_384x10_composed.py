from __future__ import annotations

import hashlib

import pytest

from tools.virtual_workflows.journeys import (
    STRESS_REQUIRED_ASSERTIONS,
    STRESS_REQUIRED_SCREENSHOTS,
    JourneyRunConfig,
    get_journey_definition,
    run_composed_journey,
)
from tools.virtual_workflows.registry import get_registered_scenario
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    STRESS_WORKLOAD_ID,
    VirtualPrintArrayScenarioConfig,
    fixture_well_ids,
    load_virtual_print_array_fixture,
    run_virtual_print_array_scenario,
)


FIXTURE_SHA256 = "9584d481ca3423bd32cbc56327e0b619fd0b56387097485f4fbea50423c0458d"


def _assert_frozen_parity_projection(report):
    fixture = load_virtual_print_array_fixture(scenario_id=STRESS_WORKLOAD_ID)
    workload = report["workload"]
    workflow = report["metrics"]["workflow"]["values"]
    assert workload["workload_id"] == STRESS_WORKLOAD_ID
    assert workload["fixture_schema_version"] == fixture["schema_version"]
    assert workload["fixture_sha256"] == FIXTURE_SHA256
    assert workload["well_ids"] == list(fixture_well_ids(fixture))
    assert workload["stock_count"] == fixture["workload"]["stock_count"]
    assert workload["array_passes"] == fixture["workload"]["array_passes"]
    assert workload["expected_completion_count"] == fixture["workload"]["completion_count"]
    assert workflow["completed_stock_well_count"] == 3840
    assert workflow["pass_terminal_states"] == ["active"] * 9 + ["completed"]


def test_composed_384x10_contract_uses_shared_multi_stock_journey():
    from tools.virtual_workflows import journeys

    definition = get_journey_definition(STRESS_WORKLOAD_ID)
    multi = get_journey_definition(journeys.MULTI_STOCK_WORKLOAD_ID)
    path = get_registered_scenario(STRESS_WORKLOAD_ID).fixture_path

    assert get_registered_scenario(STRESS_WORKLOAD_ID).runner_family == "composed_journey"
    assert definition.body is multi.body
    assert definition.payload_builder is multi.payload_builder
    assert definition.required_assertion_ids == STRESS_REQUIRED_ASSERTIONS
    assert definition.required_screenshots == STRESS_REQUIRED_SCREENSHOTS
    assert definition.midpoint_completion_count == 1920
    assert hashlib.sha256(path.read_bytes()).hexdigest() == FIXTURE_SHA256
    with pytest.raises(ValueError, match="completion count"):
        JourneyRunConfig(scenario_id=STRESS_WORKLOAD_ID, inject_after_completion=3841)


@pytest.mark.sil_stress
def test_composed_384x10_success_and_direct_parity(qapp, tmp_path):
    """Preserve the frozen node ID; direct execution now has its own node."""
    report = run_composed_journey(JourneyRunConfig(
        scenario_id=STRESS_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=600.0,
        run_id="m7-slice8-composed-stress",
    ))
    validate_report_v1(report)
    _assert_frozen_parity_projection(report)
    workflow = report["metrics"]["workflow"]["values"]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }

    assert report["classification"]["status"] in {"pass", "warning"}
    assert report["workload"]["fixture_sha256"] == FIXTURE_SHA256
    assert report["workload"]["stock_count"] == 10
    assert report["workload"]["expected_completion_count"] == 3840
    assert workflow["completed_stock_well_count"] == 3840
    assert workflow["pass_terminal_states"] == ["active"] * 9 + ["completed"]
    assert decisions == {item: "pass" for item in STRESS_REQUIRED_ASSERTIONS}
    assert set(report["artifacts"]["screenshots"]) == STRESS_REQUIRED_SCREENSHOTS
    assert [row["name"] for row in workflow["lifecycle_milestones"]] == [
        "editor_opened", "generated", "ready", "printing", "mid_array", "completed"
    ]
    actions = workflow["action_results"]
    assert sum(row["action_id"] == "array.start_via_ui" for row in actions) == 10
    assert sum(row["action_id"] == "head.return_via_ui" for row in actions) == 10
    assert sum(row["action_id"] == "validation.stock_pass_boundary" for row in actions) == 10
    volume_actions = [
        row for row in actions if row["action_id"] == "head.set_volume_via_ui"
    ]
    assert len(volume_actions) == 10
    assert [row["evidence"].get("swap") for row in volume_actions[:4]] == [None] * 4
    swaps = [row["evidence"]["swap"] for row in volume_actions[4:]]
    assert [row["printer_head_id"] for row in swaps] == [
        f"virtual-head-384x10-{index:02d}-v1" for index in range(5, 11)
    ]
    assert [row["replaced_printer_head_id"] for row in swaps] == [
        "virtual-head-384x10-01-v1",
        *[
            f"virtual-head-384x10-{index:02d}-v1"
            for index in range(5, 10)
        ],
    ]
    assert report["metrics"]["queue"]["values"]["unexpected_starvation_count"] == 0
    assert report["metrics"]["persistence"]["values"]["progress_snapshot"]["mode_counts"] == {
        "full_rebuild": 0, "cached_update": 3840
    }
    assert report["metrics"]["resources"]["status"] in {"measured", "partial"}
    phase_records = report["metrics"]["responsiveness"]["values"][
        "phase_timings"
    ]["records"]
    assert sum(
        row["name"] == "pass_start.plan_recovery" for row in phase_records
    ) == 1
    expected_cached_calibration_phases = {
        "pass_start.calibration_cached_commit",
        "pass_start.calibration_successor_validation",
        "pass_start.calibration_prewrite_guard",
        "pass_start.calibration_document_write",
        "pass_start.calibration_immutable_revision_write",
        "pass_start.calibration_current_plan_write",
        "pass_start.calibration_progress_write",
        "pass_start.calibration_resume_write",
        "pass_start.calibration_post_write_acceptance",
        "pass_start.calibration_cache_install",
    }
    assert {
        phase: sum(row["name"] == phase for row in phase_records)
        for phase in expected_cached_calibration_phases
    } == {phase: 9 for phase in expected_cached_calibration_phases}
    assert sum(
        row["name"] == "pass_start.commit_revision" for row in phase_records
    ) == 2



@pytest.mark.sil_stress
def test_direct_384x10_frozen_parity(qapp, tmp_path):
    direct = run_virtual_print_array_scenario(VirtualPrintArrayScenarioConfig(
        scenario_id=STRESS_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=600.0,
        run_id="m7-slice8-direct-stress",
    ))
    validate_report_v1(direct)
    assert direct["classification"]["status"] in {"pass", "warning"}
    _assert_frozen_parity_projection(direct)
