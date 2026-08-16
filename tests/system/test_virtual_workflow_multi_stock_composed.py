from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.virtual_workflows.actions import COMPOSED_MULTI_STOCK_ACTION_IDS
from tools.virtual_workflows.journeys import (
    MULTI_STOCK_REQUIRED_ASSERTIONS,
    MULTI_STOCK_REQUIRED_UI_ACTIONS,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    MULTI_STOCK_WORKLOAD_ID,
    VirtualPrintArrayScenarioConfig,
    run_virtual_print_array_scenario,
)


@pytest.mark.sil_lifecycle
def test_composed_multi_stock_lifecycle_report(qapp, tmp_path):
    report = run_registered_scenario(
        MULTI_STOCK_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="composed-multi-stock",
        seed=7,
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
        "print_array_multi_stock_head_exchange"
    )
    assert report["workload"]["fixture_schema_version"] == 4
    assert report["workload"]["expected_completion_count"] == 48
    assert workflow["completed_stock_well_count"] == 48
    assert workflow["array_complete_count"] == 2
    assert workflow["pass_terminal_states"] == ["active", "completed"]
    assert [row["completed_well_updates"] for row in workflow["stock_passes"]] == [
        24,
        24,
    ]
    assert [row["title"] for row in workflow["dialogs"]] == [
        "Start Print Array",
        "Evaporation Plate Dock Check",
        "Start Print Array",
    ]
    actions = workflow["action_results"]
    assert {row["action_id"] for row in actions} == COMPOSED_MULTI_STOCK_ACTION_IDS
    assert {row["status"] for row in actions} == {"pass"}
    assert {
        row["action_id"]: row["interaction_surface"]
        for row in actions
        if row["action_id"] in MULTI_STOCK_REQUIRED_UI_ACTIONS
    } == {action_id: "ui" for action_id in MULTI_STOCK_REQUIRED_UI_ACTIONS}
    assert next(
        row for row in actions if row["action_id"] == "head.bind_identity"
    )["interaction_surface"] == "model"
    assert {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    } == {assertion_id: "pass" for assertion_id in MULTI_STOCK_REQUIRED_ASSERTIONS}
    assert [row["name"] for row in workflow["lifecycle_milestones"]] == [
        "editor_opened",
        "generated",
        "stock_1_ready",
        "stock_1_printing",
        "stock_1_completed",
        "stock_2_staged",
        "stock_2_printing",
        "completed",
    ]
    milestone_controls = {
        row["name"]: (row.get("evidence") or {}).get("array_control")
        for row in workflow["lifecycle_milestones"]
    }
    assert {
        name: (control["text"], control["enabled"])
        for name, control in milestone_controls.items()
        if control is not None
    } == {
        "stock_1_ready": ("Start Array", True),
        "stock_1_printing": ("Stop After Well", True),
        "stock_1_completed": ("Array Complete", False),
        "stock_2_staged": ("Start Array", True),
        "stock_2_printing": ("Stop After Well", True),
        "completed": ("Start Array", False),
    }
    return_controls = [
        row["evidence"]["array_control_before_return"]
        for row in actions
        if row["action_id"] == "head.return_via_ui"
        and "array_control_before_return" in row["evidence"]
    ]
    assert [
        (control["text"], control["enabled"]) for control in return_controls
    ] == [("Array Complete", False), ("Array Complete", False)]

    persistence = report["metrics"]["persistence"]["values"]
    exchange = persistence["multi_stock_head_exchange"]
    assert exchange["head_identities"] == [
        "virtual-head-multi-24x2-01-v1",
        "virtual-head-multi-24x2-02-v1",
    ]
    assert [row["returned_previous"] for row in exchange["head_staging"]] == [
        False,
        True,
    ]
    assert [row["plan_state"] for row in exchange["pass_boundaries"]] == [
        "active",
        "completed",
    ]
    assert persistence["progress_snapshot"]["mode_counts"] == {
        "full_rebuild": 0,
        "cached_update": 48,
    }
    assert persistence["authoritative_io"]["resume_save_fsync_count"] == 48 * 3
    assert persistence["authoritative_io"]["resume_save_replace_count"] == 48 * 3
    assert persistence["authoritative_io"]["observer_restored"] is True
    assert report["metrics"]["queue"]["values"]["unexpected_starvation_count"] == 0
    assert report["metrics"]["queue"]["values"]["simulator_cleanup"] == {
        "command_timer_active": False,
        "connection_timer_active": False,
        "deferred_timer_count": 0,
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
    assert set(report["artifacts"]["screenshots"]) == {
        "editor_opened",
        "generated",
        "stock_1_ready",
        "stock_1_printing",
        "stock_1_completed",
        "stock_2_staged",
        "stock_2_printing",
        "completed",
    }


@pytest.mark.sil_lifecycle
def test_composed_and_legacy_multi_stock_stable_parity(qapp, tmp_path):
    composed = run_registered_scenario(
        MULTI_STOCK_WORKLOAD_ID,
        output_root=tmp_path / "composed",
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        seed=3,
    )
    legacy = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            scenario_id=MULTI_STOCK_WORKLOAD_ID,
            output_root=tmp_path / "legacy",
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
        )
    )
    for report in (composed, legacy):
        assert report["classification"]["status"] == "pass"
        validate_report_v1(report)
    for field in (
        "workload_id",
        "fixture_schema_version",
        "fixture_sha256",
        "well_ids",
        "stock_count",
        "array_passes",
        "expected_completion_count",
    ):
        assert composed["workload"][field] == legacy["workload"][field]
    composed_workflow = composed["metrics"]["workflow"]["values"]
    legacy_workflow = legacy["metrics"]["workflow"]["values"]
    assert composed_workflow["completed_stock_well_count"] == (
        legacy_workflow["completed_stock_well_count"]
    ) == 48
    assert composed_workflow["pass_terminal_states"] == (
        legacy_workflow["pass_terminal_states"]
    ) == ["active", "completed"]
    for report in (composed, legacy):
        decisions = {
            row["assertion_id"]: row["decision"]
            for row in report["metrics"]["workflow"]["values"][
                "assertion_results"
            ]
        }
        assert decisions == {
            assertion_id: "pass"
            for assertion_id in MULTI_STOCK_REQUIRED_ASSERTIONS
        }


@pytest.mark.sil_lifecycle
def test_unexpected_between_pass_dialog_fails_closed(qapp, tmp_path, monkeypatch):
    from tools.virtual_workflows.page_drivers import ArrayDriver

    original = ArrayDriver.start
    calls = {"count": 0}

    def fail_second_start(self, expected_dialogs=None):
        calls["count"] += 1
        if calls["count"] == 2:
            entry = {"type": "QMessageBox", "title": "Unexpected Between Pass"}
            self.context.unexpected_dialogs.append(entry)
            raise RuntimeError("unexpected dialog title 'Unexpected Between Pass'")
        return original(self, expected_dialogs)

    monkeypatch.setattr(ArrayDriver, "start", fail_second_start)
    report = run_registered_scenario(
        MULTI_STOCK_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        seed=5,
    )
    validate_report_v1(report)
    assert report["classification"]["status"] == "fail"
    workflow = report["metrics"]["workflow"]["values"]
    failed = [row for row in workflow["action_results"] if row["status"] == "fail"]
    assert failed[-1]["action_id"] == "array.start_via_ui"
    assert workflow["unexpected_dialogs"] == [
        {"type": "QMessageBox", "title": "Unexpected Between Pass"}
    ]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert decisions["execution.multi_stock_head_exchange"] == "incomplete"
    assert decisions["execution.terminal_bundle_valid"] == "incomplete"
    assert decisions["artifacts.required_present"] == "fail"
    assert report["metrics"]["persistence"]["values"]["authoritative_io"][
        "observer_restored"
    ] is True
    assert report["artifacts"]["failure_traceback"] == "failure_traceback.txt"
    report_dir = Path(report["safety"]["report_dir"])
    assert (report_dir / "failure_traceback.txt").is_file()
    assert (report_dir / "action_ledger.json").is_file()
    assert (report_dir / "assertion_ledger.json").is_file()
    assert (report_dir / "evidence_manifest.json").is_file()
    assert not (Path(report["safety"]["scenario_root"]) / ".sil-session.lock").exists()
