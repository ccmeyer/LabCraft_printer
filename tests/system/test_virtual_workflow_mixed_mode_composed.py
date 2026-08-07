from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.virtual_workflows.journeys import (
    MIXED_MODE_REQUIRED_ASSERTIONS,
    MIXED_MODE_REQUIRED_UI_ACTIONS,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    MIXED_MODE_WORKLOAD_ID,
    load_virtual_print_array_fixture,
)


def test_mixed_mode_fixture_contract_is_exact():
    fixture = load_virtual_print_array_fixture(scenario_id=MIXED_MODE_WORKLOAD_ID)

    assert fixture["workload"] == {
        "target_dispenses_per_stock_per_well": 1,
        "well_count": 24,
        "stock_count": 2,
        "array_passes": 2,
        "completion_count": 48,
    }
    assert [stock["printing_mode"] for stock in fixture["stocks"]] == [
        "droplet",
        "stream",
    ]
    assert [stock["droplet_volume_nL"] for stock in fixture["stocks"]] == [
        9.0,
        60.0,
    ]
    assert fixture["stocks"][1]["printer_head"] == {
        "printer_head_id": "virtual-head-mixed-24x2-stream-v1",
        "initial_volume_uL": 1000.0,
        "print_pulse_width_us": 2500,
        "print_pressure_psi": 1.2,
        "refuel_pulse_width_us": 6000,
        "refuel_pressure_psi": 0.4,
    }
    assert fixture["lifecycle"]["manual_refuel_check"] == {
        "status": "passed",
        "operator_judgment": "stable",
        "trial_count": 2,
        "trial_droplet_count": 5,
    }


@pytest.mark.sil_lifecycle
def test_composed_mixed_mode_lifecycle_report(qapp, tmp_path):
    report = run_registered_scenario(
        MIXED_MODE_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=90.0,
        run_id="composed-mixed-mode",
        seed=1,
    )
    validate_report_v1(report)
    workflow = report["metrics"]["workflow"]["values"]
    assert report["classification"]["status"] == "pass", json.dumps(
        {
            "errors": workflow["errors"],
            "failed_actions": [
                row for row in workflow["action_results"]
                if row["status"] == "fail"
            ],
            "assertions": workflow["assertion_results"],
        },
        indent=2,
    )
    assert report["run"]["scenario_name"] == "print_array_mixed_droplet_stream"
    assert workflow["completed_stock_well_count"] == 48
    assert workflow["array_complete_count"] == 2
    assert workflow["pass_terminal_states"] == ["active", "completed"]
    actions = workflow["action_results"]
    assert {row["status"] for row in actions} == {"pass"}
    assert {
        row["action_id"]: row["interaction_surface"]
        for row in actions if row["action_id"] in MIXED_MODE_REQUIRED_UI_ACTIONS
    } == {action_id: "ui" for action_id in MIXED_MODE_REQUIRED_UI_ACTIONS}
    action_ids = [row["action_id"] for row in actions]
    applies = [i for i, value in enumerate(action_ids) if value == "calibration.apply_via_ui"]
    starts = [i for i, value in enumerate(action_ids) if value == "array.start_via_ui"]
    manual = action_ids.index("manual_refuel.complete_check_via_ui")
    assert applies[1] < manual < starts[1]
    assert {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    } == {assertion_id: "pass" for assertion_id in MIXED_MODE_REQUIRED_ASSERTIONS}
    assert [row["name"] for row in workflow["lifecycle_milestones"]] == [
        "editor_opened",
        "generated",
        "droplet_ready",
        "droplet_printing",
        "droplet_completed",
        "manual_refuel_passed",
        "stream_ready",
        "stream_printing",
        "completed",
    ]

    persistence = report["metrics"]["persistence"]["values"]
    mixed = persistence["mixed_mode_lifecycle"]
    assert [
        row["printing_mode"]
        for row in mixed["calibrations"]["calibration_records"]
    ] == ["droplet", "stream"]
    record = mixed["manual_refuel"]["persisted_record"]
    assert record["status"] == "passed"
    assert record["source"] == "sil_simulated_manual_refuel_check"
    assert record["trial_count"] == 2
    assert record["trial_droplet_count"] == 5
    assert record["operator_judgment"] == "stable"
    assert record["refuel_pulse_width_us"] == 6000
    assert record["target_refuel_pressure_psi"] == pytest.approx(0.4, abs=0.001)
    assert mixed["manual_refuel"]["action_order"]["valid"] is True
    assert report["metrics"]["queue"]["values"]["unexpected_starvation_count"] == 0
    assert set(report["artifacts"]["screenshots"]) == {
        "editor_opened", "generated", "droplet_ready", "droplet_printing",
        "droplet_completed", "manual_refuel_passed", "stream_ready",
        "stream_printing", "completed",
    }
    report_dir = Path(report["safety"]["report_dir"])
    assert (report_dir / "report.json").is_file()
    assert not (Path(report["safety"]["scenario_root"]) / ".sil-session.lock").exists()
