from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.virtual_workflows.actions import COMPOSED_SOFT_STOP_ACTION_IDS
from tools.virtual_workflows.journeys import (
    SOFT_STOP_REQUIRED_ASSERTIONS,
    SOFT_STOP_REQUIRED_UI_ACTIONS,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    SOFT_STOP_RESUME_WORKLOAD_ID,
    VirtualPrintArrayScenarioConfig,
    run_virtual_print_array_scenario,
)


@pytest.mark.sil_lifecycle
def test_composed_soft_stop_resume_report(qapp, tmp_path):
    report = run_registered_scenario(
        SOFT_STOP_RESUME_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="composed-soft-stop",
        seed=11,
    )
    validate_report_v1(report)
    workflow = report["metrics"]["workflow"]["values"]
    assert report["classification"]["status"] == "pass", json.dumps(
        {
            "failed_actions": [
                row for row in workflow["action_results"] if row["status"] == "fail"
            ],
            "assertions": workflow["assertion_results"],
        },
        indent=2,
    )
    assert report["run"]["scenario_name"] == "print_array_soft_stop_resume"
    assert report["workload"]["fixture_schema_version"] == 3
    assert report["workload"]["expected_completion_count"] == 24
    assert workflow["completed_stock_well_count"] == 24
    assert workflow["array_complete_count"] == 1
    assert [row["title"] for row in workflow["dialogs"]] == [
        "Start Print Array",
        "Evaporation Plate Dock Check",
        "Resume Print Array",
    ]
    actions = workflow["action_results"]
    assert {row["action_id"] for row in actions} == COMPOSED_SOFT_STOP_ACTION_IDS
    assert {row["status"] for row in actions} == {"pass"}
    assert {
        row["action_id"]: row["interaction_surface"]
        for row in actions
        if row["action_id"] in SOFT_STOP_REQUIRED_UI_ACTIONS
    } == {action_id: "ui" for action_id in SOFT_STOP_REQUIRED_UI_ACTIONS}
    assert {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    } == {assertion_id: "pass" for assertion_id in SOFT_STOP_REQUIRED_ASSERTIONS}
    assert [row["name"] for row in workflow["lifecycle_milestones"]] == [
        "editor_opened",
        "generated",
        "ready",
        "printing",
        "stop_requested",
        "stopped",
        "resumed",
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
        "ready": ("Start Array", True),
        "printing": ("Stop After Well", True),
        "stop_requested": ("Stop Pending", False),
        "stopped": ("Resume Print", True),
        "resumed": ("Stop After Well", True),
        "completed": ("Array Complete", False),
    }
    persistence = report["metrics"]["persistence"]["values"]
    assert persistence["paused_boundary"]["checkpoint_state"] == "paused"
    assert persistence["quiescence"]["starting_completion_count"] == (
        persistence["quiescence"]["ending_completion_count"]
    )
    assert persistence["discard_batch_count"] >= 1
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
def test_composed_soft_stop_can_begin_with_immediate_pause(
    qapp,
    tmp_path,
    monkeypatch,
):
    from tools.virtual_workflows.page_drivers import ArrayDriver

    def request_immediate_pause_safe_stop(driver):
        array_button = driver.control
        before = array_button.text()
        pause_button = driver.view.connection_widget.pause_machine_button
        dialogs = driver.click_with_message_boxes(
            pause_button,
            [
                (
                    "Print Array Paused Immediately",
                    "Finish Current Well and Stop",
                )
            ],
        )
        driver.wait_until(
            lambda: (
                driver.context.controller.get_array_run_state() == "stop_requested"
                and array_button.text() == "Stop Pending"
                and not array_button.isEnabled()
            ),
            "immediate-pause safe stop pending control",
        )
        context = dict(
            getattr(driver.context.controller, "_array_context", {}) or {}
        )
        if (
            context.get("soft_stop_origin") != "immediate_pause"
            or int(context.get("soft_stop_frozen_barrier_seq32") or 0) <= 0
        ):
            raise RuntimeError(
                "immediate pause did not establish a frozen safe-stop boundary"
            )
        return {
            "button_text_before": before,
            "button_text_after": array_button.text(),
            "button_enabled_after": bool(array_button.isEnabled()),
            "pause_dialogs": dialogs,
            "soft_stop_origin": context.get("soft_stop_origin"),
            "frozen_barrier_seq32": int(
                context.get("soft_stop_frozen_barrier_seq32") or 0
            ),
        }

    monkeypatch.setattr(
        ArrayDriver,
        "request_soft_stop",
        request_immediate_pause_safe_stop,
    )
    report = run_registered_scenario(
        SOFT_STOP_RESUME_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1.0,
        timeout_seconds=60.0,
        run_id="composed-immediate-pause-soft-stop",
        seed=19,
    )

    validate_report_v1(report)
    workflow = report["metrics"]["workflow"]["values"]
    assert report["classification"]["status"] == "pass", json.dumps(
        {
            "classification": report["classification"],
            "failed_actions": [
                row for row in workflow["action_results"] if row["status"] == "fail"
            ],
            "assertions": workflow["assertion_results"],
            "errors": workflow.get("errors"),
        },
        indent=2,
    )
    assert "Print Array Paused Immediately" in [
        row["title"] for row in workflow["dialogs"]
    ]
    request_action = next(
        row
        for row in workflow["action_results"]
        if row["action_id"] == "array.request_soft_stop_via_ui"
    )
    assert request_action["evidence"]["soft_stop_origin"] == "immediate_pause"
    assert request_action["evidence"]["frozen_barrier_seq32"] > 0


@pytest.mark.sil_lifecycle
def test_soft_stop_composed_matches_legacy_oracle(qapp, tmp_path):
    composed = run_registered_scenario(
        SOFT_STOP_RESUME_WORKLOAD_ID,
        output_root=tmp_path / "composed",
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        seed=3,
    )
    legacy = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            scenario_id=SOFT_STOP_RESUME_WORKLOAD_ID,
            output_root=tmp_path / "legacy",
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
        )
    )
    for report in (composed, legacy):
        validate_report_v1(report)
        assert report["classification"]["status"] == "pass"
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
    for report in (composed, legacy):
        workflow = report["metrics"]["workflow"]["values"]
        assert workflow["completed_stock_well_count"] == 24
        assert workflow["array_states"].count("running") == 2
        assert {
            row["assertion_id"]: row["decision"]
            for row in workflow["assertion_results"]
        } == {
            assertion_id: "pass"
            for assertion_id in SOFT_STOP_REQUIRED_ASSERTIONS
        }


@pytest.mark.sil_lifecycle
def test_soft_stop_composed_controlled_failure_retains_evidence(
    qapp, tmp_path, monkeypatch
):
    from dataclasses import replace
    from tools.virtual_workflows import journeys

    original = journeys.soft_stop_paused_assertions

    def fail_boundary(*args, **kwargs):
        request, boundary, quiescence = original(*args, **kwargs)
        return (
            request,
            replace(
                boundary,
                decision="fail",
                message="synthetic paused-boundary evidence failure",
            ),
            quiescence,
        )

    monkeypatch.setattr(journeys, "soft_stop_paused_assertions", fail_boundary)
    report = run_registered_scenario(
        SOFT_STOP_RESUME_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        seed=5,
    )
    validate_report_v1(report)
    assert report["classification"]["status"] == "fail"
    workflow = report["metrics"]["workflow"]["values"]
    assert "array.resume_via_ui" not in {
        row["action_id"] for row in workflow["action_results"]
    }
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert decisions["execution.soft_stop_requested"] == "pass"
    assert decisions["execution.soft_stop_boundary_valid"] == "fail"
    assert decisions["execution.resume_exactly_once"] == "incomplete"
    assert decisions["artifacts.required_present"] == "fail"
    assert report["artifacts"]["failure_traceback"] == "failure_traceback.txt"
    report_dir = Path(report["safety"]["report_dir"])
    assert (report_dir / "failure_traceback.txt").is_file()
    assert (report_dir / "action_ledger.json").is_file()
    assert (report_dir / "assertion_ledger.json").is_file()
    assert (report_dir / "evidence_manifest.json").is_file()
    assert not (Path(report["safety"]["scenario_root"]) / ".sil-session.lock").exists()
