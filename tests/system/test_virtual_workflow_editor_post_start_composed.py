from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.virtual_workflows.editor_scenarios import (
    EditorLifecycleScenarioConfig,
    POST_START_LOCK_ASSERTION_IDS,
    POST_START_LOCK_WORKLOAD_ID,
    run_editor_post_start_lock_scenario,
)
from tools.virtual_workflows.journeys import (
    POST_START_LOCK_REQUIRED_ASSERTIONS,
    POST_START_LOCK_REQUIRED_SCREENSHOTS,
    POST_START_LOCK_REQUIRED_UI_ACTIONS,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1


EXPECTED_ACTION_IDS = [
    "app.launch_simulated",
    "editor.open_via_ui",
    "artifact.capture_milestone",
    "editor.new_experiment_via_ui",
    "editor.configure_design_via_ui",
    "editor.optimize_generate_via_ui",
    "artifact.capture_milestone",
    "editor.finish_via_ui",
    "artifact.capture_milestone",
    "experiment.activate_authoritative",
    "execution.lock_for_printing",
    "artifact.capture_milestone",
    "editor.inspect_active_lock_via_ui",
    "artifact.capture_milestone",
    "editor.reject_in_place_edit_via_ui",
    "artifact.capture_milestone",
    "editor.create_editable_copy_via_ui",
    "artifact.capture_milestone",
    "editor.edit_copy_via_ui",
    "artifact.capture_milestone",
    "editor.finalize_copy_via_ui",
    "artifact.capture_milestone",
    "experiment.load_authoritative_via_ui",
    "artifact.capture_milestone",
    "scenario.teardown",
]


def _run(tmp_path: Path, run_id: str) -> dict:
    return run_registered_scenario(
        POST_START_LOCK_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id=run_id,
        seed=7,
    )


@pytest.mark.sil_lifecycle
def test_composed_editor_post_start_lock_report(qapp, tmp_path):
    report = _run(tmp_path, "composed-editor-post-start-success")
    validate_report_v1(report)

    assert report["classification"]["status"] == "pass", json.dumps(
        report["classification"], indent=2
    )
    assert report["run"]["scenario_name"] == "experiment_editor_post_start_lock"
    assert report["run"]["seed"] == 7
    assert report["workload"]["experiment_name"] == (
        "sil-editor-post-start-lock-v1"
    )
    assert report["workload"]["copy_experiment_name"] == (
        "sil-editor-post-start-copy-v1"
    )
    assert report["workload"]["well_ids"] == ["A1", "A2"]
    assert not any(report["safety"]["hardware_interfaces"].values())

    workflow = report["metrics"]["workflow"]["values"]
    rows = workflow["action_results"]
    assert [row["action_id"] for row in rows] == EXPECTED_ACTION_IDS
    assert {row["status"] for row in rows} == {"pass"}
    surfaces = {row["action_id"]: row["interaction_surface"] for row in rows}
    assert surfaces["experiment.activate_authoritative"] == "model"
    assert surfaces["execution.lock_for_printing"] == "model"
    assert {
        row["interaction_surface"]
        for row in rows
        if row["action_id"] in POST_START_LOCK_REQUIRED_UI_ACTIONS
    } == {"ui"}
    assert [row["name"] for row in workflow["lifecycle_milestones"]] == [
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
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert tuple(decisions) == POST_START_LOCK_REQUIRED_ASSERTIONS
    assert decisions == {
        assertion_id: "pass"
        for assertion_id in POST_START_LOCK_REQUIRED_ASSERTIONS
    }

    persistence = report["metrics"]["persistence"]["values"]
    boundary = persistence["post_start_edit_boundary"]
    assert set(boundary) == {
        "source_locked",
        "locked_editor",
        "editable_copy_before_finalize",
        "editable_copy_after_finalize",
        "source_after_copy",
    }
    assert boundary["source_locked"]["plan_state"] == "active"
    assert boundary["source_locked"]["plan_revision"] == 2
    assert boundary["source_locked"]["lock_reason"] == "printing_started"
    assert boundary["locked_editor"]["all_mutating_controls_locked"] is True
    assert boundary["locked_editor"]["action_label"] == "Execution Loaded"
    assert "Calibration may still update" in boundary["locked_editor"][
        "banner_text"
    ]
    before = boundary["editable_copy_before_finalize"]
    assert before["copy_name_dialog"]["dialog_minimum_width_px"] >= 640
    assert before["copy_name_dialog"]["name_field_minimum_width_px"] >= 480
    copy = boundary["editable_copy_after_finalize"]
    assert copy["failed_checks"] == []
    assert copy["plan_state"] == "prepared"
    assert copy["plan_revision"] == 1
    assert copy["resume_present"] is False
    assert copy["plan_id"] != boundary["source_locked"]["plan_id"]
    assert boundary["source_after_copy"]["files_byte_identical"] is True
    reload_evidence = persistence["reload_activation"]
    assert reload_evidence["activation_performed"] is False
    assert reload_evidence["runtime_active"] is False
    assert reload_evidence["eligibility_status"] == "ready_to_start"

    report_dir = Path(report["safety"]["report_dir"])
    scenario_root = Path(report["safety"]["scenario_root"])
    assert set(report["artifacts"]["screenshots"]) == (
        POST_START_LOCK_REQUIRED_SCREENSHOTS
    )
    for name in (
        "report.json",
        "summary.txt",
        "events.jsonl",
        "action_ledger.json",
        "assertion_ledger.json",
        "evidence_manifest.json",
    ):
        assert (report_dir / name).is_file()
    assert not (scenario_root / ".sil-session.lock").exists()


@pytest.mark.sil_lifecycle
def test_composed_and_legacy_editor_post_start_stable_parity(qapp, tmp_path):
    legacy = run_editor_post_start_lock_scenario(
        EditorLifecycleScenarioConfig(
            scenario_id=POST_START_LOCK_WORKLOAD_ID,
            output_root=tmp_path / "legacy",
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
            run_id="legacy-editor-post-start-parity",
        )
    )
    composed = _run(tmp_path / "composed", "composed-editor-post-start-parity")

    assert legacy["classification"]["status"] == "pass"
    assert composed["classification"]["status"] == "pass"
    assert tuple(POST_START_LOCK_ASSERTION_IDS) == POST_START_LOCK_REQUIRED_ASSERTIONS
    fixture_path = Path(
        "tools/virtual_workflows/fixtures/experiment_editor_post_start_lock_v1.json"
    )
    assert composed["workload"]["fixture_sha256"] == hashlib.sha256(
        fixture_path.read_bytes()
    ).hexdigest()
    for report in (legacy, composed):
        decisions = {
            row["assertion_id"]: row["decision"]
            for row in report["metrics"]["workflow"]["values"][
                "assertion_results"
            ]
        }
        assert decisions == {
            assertion_id: "pass" for assertion_id in POST_START_LOCK_ASSERTION_IDS
        }
        boundary = report["metrics"]["persistence"]["values"][
            "post_start_edit_boundary"
        ]
        assert boundary["source_locked"]["plan_state"] == "active"
        assert boundary["source_locked"]["plan_revision"] == 2
        assert boundary["source_locked"]["total_added_droplets"] == 0
        assert boundary["locked_editor"]["all_mutating_controls_locked"] is True
        assert boundary["source_after_copy"]["files_byte_identical"] is True
        copy = boundary["editable_copy_after_finalize"]
        assert copy["plan_state"] == "prepared"
        assert copy["plan_revision"] == 1
        assert copy["resume_present"] is False


@pytest.mark.sil_lifecycle
def test_composed_editor_post_start_lock_violation_retains_evidence(
    qapp, tmp_path, monkeypatch
):
    from tools.virtual_workflows import journeys

    original = journeys.run_post_start_lock_copy

    def inject_violation(*args, **kwargs):
        boundary = original(*args, **kwargs)
        boundary["editor"]["lock_matrix"][
            "all_mutating_controls_locked"
        ] = False
        return boundary

    monkeypatch.setattr(journeys, "run_post_start_lock_copy", inject_violation)
    report = _run(tmp_path, "composed-editor-post-start-lock-failure")

    assert report["classification"]["status"] == "fail"
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in report["metrics"]["workflow"]["values"]["assertion_results"]
    }
    assert decisions["experiment.active_edit_lock"] == "fail"
    assert decisions["experiment.in_place_edit_rejected"] == "incomplete"
    assert decisions["experiment.editable_copy_created"] == "incomplete"
    boundary = report["metrics"]["persistence"]["values"][
        "post_start_edit_boundary"
    ]
    assert boundary["source_locked"]["plan_state"] == "active"
    assert boundary["locked_editor"]["all_mutating_controls_locked"] is False
    assert boundary["source_after_copy"]["files_byte_identical"] is True
    report_dir = Path(report["safety"]["report_dir"])
    scenario_root = Path(report["safety"]["scenario_root"])
    assert (report_dir / "failure_traceback.txt").is_file()
    assert (report_dir / "evidence_manifest.json").is_file()
    assert not (scenario_root / ".sil-session.lock").exists()


@pytest.mark.sil_lifecycle
def test_composed_editor_copy_inherited_runtime_fails_closed(
    qapp, tmp_path, monkeypatch
):
    from tools.virtual_workflows import authoritative_evidence

    original = authoritative_evidence.post_start_copy_boundary_evidence

    def inject_inherited_runtime(*args, **kwargs):
        copy, source = original(*args, **kwargs)
        copy["checks"]["copy_resume_absent"] = False
        copy["failed_checks"] = ["copy_resume_absent"]
        copy["resume_present"] = True
        return copy, source

    monkeypatch.setattr(
        authoritative_evidence,
        "post_start_copy_boundary_evidence",
        inject_inherited_runtime,
    )
    report = _run(tmp_path, "composed-editor-copy-runtime-failure")

    assert report["classification"]["status"] == "fail"
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in report["metrics"]["workflow"]["values"]["assertion_results"]
    }
    assert decisions["experiment.source_bundle_immutable"] == "pass"
    assert decisions["experiment.editable_copy_created"] == "pass"
    assert decisions["experiment.editable_copy_fresh_execution"] == "fail"
    assert decisions["experiment.editable_copy_editable"] == "incomplete"
    boundary = report["metrics"]["persistence"]["values"][
        "post_start_edit_boundary"
    ]
    assert boundary["editable_copy_after_finalize"]["resume_present"] is True
    assert boundary["source_after_copy"]["files_byte_identical"] is True
