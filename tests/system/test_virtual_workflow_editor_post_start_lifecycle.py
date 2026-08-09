from __future__ import annotations

from pathlib import Path

import pytest

from tools.virtual_workflows.editor_scenarios import (
    POST_START_LOCK_ASSERTION_IDS,
    POST_START_LOCK_WORKLOAD_ID,
    EditorLifecycleScenarioConfig,
    load_editor_post_start_lock_fixture,
    run_editor_post_start_lock_scenario,
)
from tools.virtual_workflows.report import validate_report_v1


def test_editor_post_start_lock_fixture_contract_is_exact():
    fixture = load_editor_post_start_lock_fixture()

    assert fixture["fixture_id"] == POST_START_LOCK_WORKLOAD_ID
    assert fixture["experiment"] == {
        "source_name": "sil-editor-post-start-lock-v1",
        "copy_name": "sil-editor-post-start-copy-v1",
        "plate_name": "shallow-384_well_plate",
        "replicates": 2,
        "expected_well_ids": ["A1", "A2"],
        "printed_volume_nL": 10.0,
        "final_volume_nL": 10.0,
        "printed_volume_tolerance_nL": 0.0,
        "copy_printed_volume_tolerance_nL": 1.0,
        "randomize_assignments": False,
        "allow_two_stock_solutions": False,
    }
    assert fixture["workload"] == {
        "completion_count": 2,
        "expected_editor_finalization_operations": 2,
        "expected_authoritative_activations": 1,
        "expected_printing_start_locks": 1,
        "expected_editable_copy_operations": 1,
    }


@pytest.mark.sil_lifecycle
def test_editor_post_start_lock_lifecycle_report(qapp, tmp_path):
    report = run_editor_post_start_lock_scenario(
        EditorLifecycleScenarioConfig(
            output_root=tmp_path,
            scenario_id=POST_START_LOCK_WORKLOAD_ID,
            timeout_seconds=60,
        )
    )

    validate_report_v1(report)
    assert report["classification"]["status"] == "pass", [
        {
            "action_id": item["action_id"],
            "failure_message": item["failure_message"],
            "evidence": item["evidence"],
        }
        for item in report["metrics"]["workflow"]["values"][
            "action_results"
        ]
        if item["status"] != "pass"
    ]
    workflow = report["metrics"]["workflow"]["values"]
    assert {
        item["assertion_id"]: item["decision"]
        for item in workflow["assertion_results"]
    } == {assertion_id: "pass" for assertion_id in POST_START_LOCK_ASSERTION_IDS}
    assert [item["name"] for item in workflow["lifecycle_milestones"]] == [
        "editor_opened",
        "generated",
        "initial_finalized",
        "source_locked",
        "locked_editor_opened",
        "in_place_edit_rejected",
        "editable_copy_created",
        "copy_edited",
        "copy_finalized",
        "validated",
    ]
    boundary = report["metrics"]["persistence"]["values"][
        "post_start_edit_boundary"
    ]
    assert set(boundary) == {
        "source_locked",
        "locked_editor",
        "editable_copy_before_finalize",
        "editable_copy_after_finalize",
        "source_after_copy",
    }
    assert boundary["source_after_copy"]["files_byte_identical"] is True
    locked_editor = boundary["locked_editor"]
    assert locked_editor["banner_visible"] is True
    assert locked_editor["action_label"] == "Experiment Loaded"
    assert "Calibration may still update" in locked_editor["banner_text"]
    copy_evidence = boundary["editable_copy_before_finalize"]
    assert copy_evidence["action_label"] == "Finalize Experiment"
    assert (
        Path(copy_evidence["source_auto_selected"]).resolve()
        == Path(boundary["source_locked"]["experiment_dir"]).resolve()
    )
    assert (
        copy_evidence["copy_name_dialog"]["dialog_minimum_width_px"] >= 640
    )
    assert (
        copy_evidence["copy_name_dialog"]["name_field_minimum_width_px"] >= 480
    )
    assert (
        Path(copy_evidence["destination"]).resolve()
        == Path(copy_evidence["experiment_dir"]).resolve()
    )
    assert (
        boundary["editable_copy_after_finalize"]["plan_id"]
        != boundary["source_locked"]["plan_id"]
    )
    assert boundary["editable_copy_after_finalize"]["plan_state"] == "prepared"
    assert boundary["editable_copy_after_finalize"]["resume_present"] is False

    report_path = Path(report["safety"]["scenario_root"]).parent / "report.json"
    assert report_path.is_file()
    screenshots = report["artifacts"]["screenshots"]
    assert set(screenshots) == {
        "editor_opened",
        "generated",
        "initial_finalized",
        "source_locked",
        "locked_editor_opened",
        "in_place_edit_rejected",
        "editable_copy_created",
        "copy_edited",
        "copy_finalized",
        "validated",
    }
    assert all(
        (report_path.parent / relative).stat().st_size > 0
        for relative in screenshots.values()
    )


@pytest.mark.sil_lifecycle
def test_editor_post_start_lock_failure_retains_boundary_evidence(
    qapp,
    tmp_path,
    monkeypatch,
):
    from tools.virtual_workflows import editor_scenarios
    from tools.virtual_workflows.actions import ScenarioActionError

    def fail_lock_driver(*args, **kwargs):
        raise ScenarioActionError(
            "editor.inspect_active_lock_via_ui",
            "synthetic active lock failure",
            stage="operation",
            evidence={
                "control_matrix": {
                    "all_mutating_controls_locked": False,
                    "status_text": "",
                }
            },
        )

    monkeypatch.setattr(
        editor_scenarios,
        "drive_editor_post_start_lock_and_copy",
        fail_lock_driver,
    )
    report = run_editor_post_start_lock_scenario(
        EditorLifecycleScenarioConfig(
            output_root=tmp_path,
            scenario_id=POST_START_LOCK_WORKLOAD_ID,
            timeout_seconds=60,
        )
    )

    validate_report_v1(report)
    assert report["classification"]["status"] == "fail"
    assertions = {
        item["assertion_id"]: item
        for item in report["metrics"]["workflow"]["values"][
            "assertion_results"
        ]
    }
    assert assertions["experiment.active_edit_lock"]["decision"] == "fail"
    assert (
        assertions["experiment.in_place_edit_rejected"]["decision"]
        == "incomplete"
    )
    assert (
        assertions["experiment.editable_copy_created"]["decision"]
        == "incomplete"
    )
    boundary = report["metrics"]["persistence"]["values"][
        "post_start_edit_boundary"
    ]
    assert boundary["source_locked"]["plan_state"] == "active"
    assert (
        boundary["locked_editor"]["all_mutating_controls_locked"]
        is False
    )
    assert boundary["source_after_copy"]["diagnostic_only"] is True
    assert report["artifacts"]["failure_traceback"] == "failure_traceback.txt"
