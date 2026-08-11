from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.virtual_workflows.actions import MULTI_STOCK_LIFECYCLE_ACTION_IDS
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    MULTI_STOCK_WORKLOAD_ID,
    VirtualPrintArrayScenarioConfig,
    fixture_well_ids,
    load_virtual_print_array_fixture,
    run_virtual_print_array_scenario,
)


def test_multi_stock_fixture_contract_is_exact():
    fixture = load_virtual_print_array_fixture(
        scenario_id=MULTI_STOCK_WORKLOAD_ID
    )

    assert fixture["schema_version"] == 4
    assert fixture["fixture_id"] == MULTI_STOCK_WORKLOAD_ID
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
        "stock_count": 2,
        "array_passes": 2,
        "completion_count": 48,
    }
    assert fixture["simulation"] == {
        "dispense_frequency_hz": 20,
        "lookahead_wells": 2,
        "staging_slot": 0,
    }
    assert fixture["lifecycle"] == {
        "kind": "multi_stock_head_exchange",
        "expected_stock_pass_count": 2,
        "expected_head_stage_count": 2,
        "expected_between_pass_exchange_count": 1,
    }
    assert fixture_well_ids(fixture) == tuple(
        f"A{column}" for column in range(1, 25)
    )
    assert [stock["factor_name"] for stock in fixture["stocks"]] == [
        "Virtual Multi Stock 01",
        "Virtual Multi Stock 02",
    ]
    assert [
        stock["printer_head"]["printer_head_id"]
        for stock in fixture["stocks"]
    ] == [
        "virtual-head-multi-24x2-01-v1",
        "virtual-head-multi-24x2-02-v1",
    ]
    assert [
        (
            stock["printer_head"]["print_pulse_width_us"],
            stock["printer_head"]["print_pressure_psi"],
        )
        for stock in fixture["stocks"]
    ] == [(1300, 1.2), (1800, 1.5)]
    assert [stock["concentration"] for stock in fixture["stocks"]] == [3.0, 1.5]
    assert [
        stock["prepared_droplet_volume_nL"] for stock in fixture["stocks"]
    ] == [9.0, 18.0]
    assert [stock["droplet_volume_nL"] for stock in fixture["stocks"]] == [
        9.0,
        18.0,
    ]


@pytest.mark.sil_lifecycle
def test_multi_stock_head_exchange_lifecycle_report(qapp, tmp_path):
    report = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            scenario_id=MULTI_STOCK_WORKLOAD_ID,
            output_root=tmp_path,
            speed_multiplier=1000.0,
            timeout_seconds=60,
            run_id="multi-stock-head-exchange-lifecycle",
        )
    )

    validate_report_v1(report)
    assert report["classification"]["status"] == "pass", json.dumps(
        report["metrics"]["workflow"]["values"]["action_results"],
        indent=2,
    )
    assert report["run"]["scenario_name"] == (
        "print_array_multi_stock_head_exchange"
    )
    assert report["workload"]["expected_completion_count"] == 48
    workflow = report["metrics"]["workflow"]["values"]
    actions = workflow["action_results"]
    assert {item["action_id"] for item in actions} == (
        MULTI_STOCK_LIFECYCLE_ACTION_IDS
    )
    assert {item["status"] for item in actions} == {"pass"}
    assert sum(item["action_id"] == "head.stage_virtual" for item in actions) == 2
    assert sum(item["action_id"] == "array.start_via_ui" for item in actions) == 2
    assert sum(
        item["action_id"] == "validation.stock_pass_boundary"
        for item in actions
    ) == 2
    assert [item["name"] for item in workflow["lifecycle_milestones"]] == [
        "stock_1_ready",
        "stock_1_printing",
        "stock_1_completed",
        "stock_2_staged",
        "stock_2_printing",
        "completed",
    ]
    assert [item["title"] for item in workflow["dialogs"]] == [
        "Start Print Array",
        "Evaporation Plate Dock Check",
        "Start Print Array",
    ]
    assert workflow["completed_stock_well_count"] == 48
    assert workflow["well_update_count"] == 48
    assert workflow["array_complete_count"] == 2
    assert workflow["pass_terminal_states"] == ["active", "completed"]
    assert [
        item["completed_well_updates"] for item in workflow["stock_passes"]
    ] == [24, 24]
    assert {
        item["assertion_id"]: item["decision"]
        for item in workflow["assertion_results"]
    } == {
        assertion_id: "pass"
        for assertion_id in (
            "sil.host_hardware_disabled",
            "ui.real_app_constructed",
            "execution.multi_stock_head_exchange",
            "execution.stock_pass_boundaries_valid",
            "execution.stock_head_settings_match",
            "execution.expected_completions",
            "execution.no_queue_starvation",
            "execution.intent_durability_exact",
            "execution.event_history_bounded",
            "execution.terminal_bundle_valid",
            "artifacts.required_present",
        )
    }

    persistence = report["metrics"]["persistence"]["values"]
    evidence = persistence["multi_stock_head_exchange"]
    assert evidence["head_identities"] == [
        "virtual-head-multi-24x2-01-v1",
        "virtual-head-multi-24x2-02-v1",
    ]
    assert [
        item["returned_previous"] for item in evidence["head_staging"]
    ] == [False, True]
    assert [
        item["queue_drained_before"] for item in evidence["head_staging"]
    ] == [True, True]
    assert [
        item["plan_state"] for item in evidence["pass_boundaries"]
    ] == ["active", "completed"]
    assert evidence["intent_reconciliation"] == {
        "begin_count": 48,
        "attachment_count": 48,
        "completion_count": 48,
        "discard_batch_count": 0,
    }
    assert evidence["terminal"]["plan_state"] == "completed"
    assert persistence["stock_well_completion_count"] == 48
    assert persistence["progress_snapshot"]["mode_counts"] == {
        "full_rebuild": 0,
        "cached_update": 48,
    }
    assert persistence["authoritative_io"]["resume_save_fsync_count"] == 48 * 3
    assert persistence["authoritative_io"]["resume_save_replace_count"] == 48 * 3
    assert report["metrics"]["queue"]["values"][
        "unexpected_starvation_count"
    ] == 0
    assert report["metrics"]["queue"]["values"]["simulator_cleanup"] == {
        "command_timer_active": False,
        "connection_timer_active": False,
        "deferred_timer_count": 0,
    }
    assert report["metrics"]["responsiveness"]["status"] == "not_applicable"
    assert report["metrics"]["resources"]["status"] == "not_applicable"

    report_dir = Path(report["safety"]["scenario_root"]).parent
    assert set(report["artifacts"]["screenshots"]) == {
        "stock_1_ready",
        "stock_1_printing",
        "stock_1_completed",
        "stock_2_staged",
        "stock_2_printing",
        "completed",
    }
    assert all(
        (report_dir / relative).stat().st_size > 0
        for relative in report["artifacts"]["screenshots"].values()
    )


@pytest.mark.sil_lifecycle
def test_multi_stock_failure_retains_exchange_evidence(
    qapp,
    tmp_path,
    monkeypatch,
):
    from tools.virtual_workflows import scenarios

    monkeypatch.setattr(
        scenarios,
        "_validate_multi_stock_completed_scenario",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("synthetic multi-stock terminal failure")
        ),
    )
    report = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            scenario_id=MULTI_STOCK_WORKLOAD_ID,
            output_root=tmp_path,
            speed_multiplier=1000.0,
            timeout_seconds=60,
        )
    )

    validate_report_v1(report)
    assert report["classification"]["status"] == "fail"
    workflow = report["metrics"]["workflow"]["values"]
    assert sum(
        item["action_id"] == "head.stage_virtual"
        and item["status"] == "pass"
        for item in workflow["action_results"]
    ) == 2
    assert workflow["action_results"][-2]["action_id"] == (
        "validation.terminal_bundle"
    )
    assert workflow["action_results"][-2]["status"] == "fail"
    assert report["artifacts"]["failure_traceback"] == "failure_traceback.txt"
