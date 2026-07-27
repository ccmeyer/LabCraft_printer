from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tools.virtual_workflows.editor_scenarios import (
    ASSERTION_IDS,
    RENAME_ASSERTION_IDS,
    RENAME_WORKLOAD_ID,
    WORKLOAD_ID,
    EditorLifecycleScenarioConfig,
    load_editor_create_finalize_fixture,
    load_editor_prestart_rename_refinalize_fixture,
    run_editor_create_finalize_scenario,
    run_editor_prestart_rename_refinalize_scenario,
)
from tools.virtual_workflows.actions import ScenarioActionError
from tools.virtual_workflows.report import validate_report_v1


def test_editor_create_finalize_fixture_contract_is_exact():
    fixture = load_editor_create_finalize_fixture()

    assert fixture == {
        "fixture_id": WORKLOAD_ID,
        "schema_version": 1,
        "experiment": {
            "name": "sil-editor-create-finalize-v1",
            "plate_name": "shallow-384_well_plate",
            "replicates": 2,
            "expected_well_ids": ["A1", "A2"],
            "printed_volume_nL": 10.0,
            "final_volume_nL": 10.0,
            "printed_volume_tolerance_nL": 0.0,
            "randomize_assignments": False,
            "allow_two_stock_solutions": False,
        },
        "reagent": {
            "stock_label": "Editor Stock",
            "group": "Additive",
            "printing_mode": "droplet",
            "starting_concentration": 0.0,
            "targets": [1.0],
            "units": "x",
            "fixed_stock_concentration": 1.0,
            "droplet_volume_nL": 10.0,
        },
        "workload": {
            "completion_count": 1,
            "expected_editor_finalization_operations": 1,
        },
    }


def test_editor_prestart_rename_refinalize_fixture_contract_is_exact():
    fixture = load_editor_prestart_rename_refinalize_fixture()

    assert fixture == {
        "fixture_id": RENAME_WORKLOAD_ID,
        "schema_version": 2,
        "experiment": {
            "initial_name": "sil-editor-prestart-rename-v1",
            "renamed_name": "sil-editor-prestart-renamed-v1",
            "plate_name": "shallow-384_well_plate",
            "initial_replicates": 2,
            "initial_expected_well_ids": ["A1", "A2"],
            "initial_printed_volume_nL": 10.0,
            "initial_final_volume_nL": 10.0,
            "refinalized_replicates": 3,
            "refinalized_expected_well_ids": [
                "A1", "A2", "A3", "A4", "A5", "A6"
            ],
            "refinalized_printed_volume_nL": 120.0,
            "refinalized_final_volume_nL": 120.0,
            "printed_volume_tolerance_nL": 0.0,
            "randomize_assignments": False,
            "allow_two_stock_solutions": False,
            "initial_fill_printing_mode": "droplet",
            "initial_fill_droplet_volume_nL": 10.0,
            "refinalized_fill_printing_mode": "stream",
            "refinalized_fill_droplet_volume_nL": 60.0,
        },
        "reagent": {
            "stock_label": "Editor Stock",
            "group": "Additive",
            "initial_printing_mode": "droplet",
            "refinalized_printing_mode": "stream",
            "starting_concentration": 0.0,
            "initial_targets": [1.0],
            "refinalized_targets": [0.5, 1.0],
            "units": "x",
            "fixed_stock_concentration": 1.0,
            "initial_droplet_volume_nL": 10.0,
            "refinalized_droplet_volume_nL": 60.0,
        },
        "workload": {
            "completion_count": 2,
            "expected_editor_finalization_operations": 2,
            "expected_rename_operations": 1,
            "expected_prepared_design_edit_operations": 1,
        },
    }


@pytest.mark.sil_lifecycle
def test_editor_create_finalize_lifecycle_report(qapp, tmp_path):
    started = time.perf_counter()
    report = run_editor_create_finalize_scenario(
        EditorLifecycleScenarioConfig(
            output_root=tmp_path,
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
            run_id="editor-create-finalize",
        )
    )
    elapsed = time.perf_counter() - started
    validate_report_v1(report)

    assert elapsed < 60
    assert report["run"]["duration_ms"] < 60_000
    assert report["run"]["scenario_name"] == "experiment_editor_create_finalize"
    assert report["run"]["scenario_version"] == "1"
    font = report["environment"]["qt"]["font"]
    assert font["status"] == "pass"
    assert font["resolved_family"] == "Segoe UI"
    assert font["point_size"] == 9.0
    assert font["raw_font_valid"] is True
    assert font["sample_glyphs_renderable"] is True
    assert font["matches_native_windows_app"] is True
    assert report["classification"] == {
        "status": "pass",
        "threshold_maturity": "informational",
        "reasons": [],
    }
    assert report["workload"]["well_ids"] == ["A1", "A2"]
    assert report["safety"]["simulation"] is True
    assert report["safety"]["hardware_access_allowed"] is False
    assert not any(report["safety"]["hardware_interfaces"].values())

    workflow = report["metrics"]["workflow"]["values"]
    assert workflow["dialogs"] == []
    assert workflow["unexpected_dialogs"] == []
    assert workflow["errors"] == []
    assert [item["name"] for item in workflow["lifecycle_milestones"]] == [
        "editor_opened",
        "generated",
        "finalized",
        "reloaded",
        "validated",
    ]
    assert [item["action_id"] for item in workflow["action_results"]] == [
        "app.launch_simulated",
        "editor.open_via_ui",
        "artifact.capture_milestone",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        "editor.optimize_generate_via_ui",
        "artifact.capture_milestone",
        "editor.finish_via_ui",
        "artifact.capture_milestone",
        "validation.prepared_bundle",
        "experiment.reload_authoritative",
        "artifact.capture_milestone",
        "artifact.capture_milestone",
        "scenario.teardown",
    ]
    assert {item["status"] for item in workflow["action_results"]} == {"pass"}
    assert {item["status"] for item in workflow["cleanup_results"]} == {"pass"}
    assertions = {
        item["assertion_id"]: item for item in workflow["assertion_results"]
    }
    assert set(assertions) == set(ASSERTION_IDS)
    assert {item["decision"] for item in assertions.values()} == {"pass"}
    assert (
        assertions["ui.real_app_constructed"]["evidence"]["font_rendering"]
        == font
    )

    persistence = report["metrics"]["persistence"]["values"]
    prepared = persistence["prepared_bundle"]
    reloaded = persistence["reload_activation"]
    assert prepared["plan_revision"] == 1
    assert prepared["plan_state"] == "prepared"
    assert prepared["eligibility_status"] == "ready_to_start"
    assert prepared["well_ids"] == ["A1", "A2"]
    assert prepared["total_added_droplets"] == 0
    assert prepared["runtime_assignments"] == reloaded["runtime_assignments"]
    assert reloaded["eligibility_status"] == "ready_to_start"
    assert reloaded["resume_state"] == "clean"
    assert reloaded["resume_intent_count"] == 0

    assert report["metrics"]["responsiveness"] == {
        "status": "not_applicable",
        "values": {},
    }
    assert report["metrics"]["resources"] == {
        "status": "not_applicable",
        "values": {},
    }
    assert report["metrics"]["queue"]["status"] == "not_applicable"
    assert report["metrics"]["queue"]["values"]["print_commands_executed"] == 0

    report_dir = Path(report["safety"]["scenario_root"]).parent
    assert json.loads(
        (report_dir / "report.json").read_text(encoding="utf-8")
    ) == report
    assert set(report["artifacts"]["screenshots"]) == {
        "editor_opened",
        "generated",
        "finalized",
        "validated",
        "reloaded",
    }
    for relative in report["artifacts"]["screenshots"].values():
        path = report_dir / relative
        assert path.is_file()
        assert path.stat().st_size > 0
    for name in (
        "report.json",
        "summary.txt",
        "events.jsonl",
        "stall_stacks.txt",
        "application_stdout.log",
    ):
        assert (report_dir / name).is_file()
    assert not (report_dir / "failure_traceback.txt").exists()


@pytest.mark.sil_lifecycle
def test_editor_lifecycle_failure_reports_failed_and_incomplete_assertions(
    qapp,
    tmp_path,
    monkeypatch,
):
    import tools.virtual_workflows.editor_scenarios as scenarios

    def fail_editor(_context, _fixture):
        raise ScenarioActionError(
            "editor.configure_design_via_ui",
            "synthetic editor failure",
            stage="operation",
            evidence={"step": "control_entry"},
        )

    monkeypatch.setattr(scenarios, "drive_editor_create_finalize", fail_editor)
    report = run_editor_create_finalize_scenario(
        EditorLifecycleScenarioConfig(
            output_root=tmp_path,
            timeout_seconds=60,
            run_id="editor-failure",
        )
    )

    assert report["classification"]["status"] == "fail"
    assertions = {
        item["assertion_id"]: item["decision"]
        for item in report["metrics"]["workflow"]["values"][
            "assertion_results"
        ]
    }
    assert assertions["experiment.editor_create_finalize"] == "fail"
    assert assertions["artifacts.required_present"] == "fail"
    assert assertions["experiment.prepared_bundle_valid"] == "incomplete"
    assert assertions["experiment.prepared_reload_ready"] == "incomplete"
    cleanup = report["metrics"]["workflow"]["values"]["cleanup_results"]
    assert cleanup
    assert {item["status"] for item in cleanup} == {"pass"}
    report_dir = Path(report["safety"]["scenario_root"]).parent
    assert (report_dir / "failure_traceback.txt").is_file()


@pytest.mark.sil_lifecycle
def test_editor_prestart_rename_refinalize_lifecycle_report(qapp, tmp_path):
    started = time.perf_counter()
    report = run_editor_prestart_rename_refinalize_scenario(
        EditorLifecycleScenarioConfig(
            output_root=tmp_path,
            scenario_id=RENAME_WORKLOAD_ID,
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
            run_id="editor-prestart-rename-refinalize",
        )
    )
    elapsed = time.perf_counter() - started
    validate_report_v1(report)

    assert elapsed < 60
    assert report["run"]["duration_ms"] < 60_000
    assert (
        report["run"]["scenario_name"]
        == "experiment_editor_prestart_rename_refinalize"
    )
    assert report["classification"] == {
        "status": "pass",
        "threshold_maturity": "informational",
        "reasons": [],
    }
    assert report["workload"]["operation_count"] == 2
    assert report["workload"]["experiment_name"] == (
        "sil-editor-prestart-rename-v1"
    )
    assert report["workload"]["renamed_experiment_name"] == (
        "sil-editor-prestart-renamed-v1"
    )

    workflow = report["metrics"]["workflow"]["values"]
    assert workflow["dialogs"] == []
    assert workflow["unexpected_dialogs"] == []
    assert workflow["errors"] == []
    assert [item["name"] for item in workflow["lifecycle_milestones"]] == [
        "editor_opened",
        "generated",
        "initial_finalized",
        "rename_editor_opened",
        "renamed",
        "prepared_design_edited",
        "regenerated",
        "refinalized",
        "reloaded",
        "validated",
    ]
    assert [item["action_id"] for item in workflow["action_results"]] == [
        "app.launch_simulated",
        "editor.open_via_ui",
        "artifact.capture_milestone",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        "editor.optimize_generate_via_ui",
        "artifact.capture_milestone",
        "editor.finish_via_ui",
        "artifact.capture_milestone",
        "validation.prepared_bundle",
        "editor.open_via_ui",
        "artifact.capture_milestone",
        "editor.rename_prepared_via_ui",
        "artifact.capture_milestone",
        "editor.edit_prepared_design_via_ui",
        "artifact.capture_milestone",
        "editor.regenerate_prepared_design_via_ui",
        "artifact.capture_milestone",
        "editor.refinalize_prepared_via_ui",
        "artifact.capture_milestone",
        "validation.refinalized_bundle",
        "experiment.reload_authoritative",
        "artifact.capture_milestone",
        "artifact.capture_milestone",
        "scenario.teardown",
    ]
    assert {item["status"] for item in workflow["action_results"]} == {"pass"}
    assert {item["status"] for item in workflow["cleanup_results"]} == {"pass"}
    assertions = {
        item["assertion_id"]: item for item in workflow["assertion_results"]
    }
    assert set(assertions) == set(RENAME_ASSERTION_IDS)
    assert {item["decision"] for item in assertions.values()} == {"pass"}

    persistence = report["metrics"]["persistence"]["values"]
    before = persistence["rename_refinalization"]["before"]
    after = persistence["rename_refinalization"]["after"]
    refinalized = persistence["refinalized_bundle"]
    reloaded = persistence["reload_activation"]
    assert before["metadata_name"] == "sil-editor-prestart-rename-v1"
    assert after["renamed_name"] == "sil-editor-prestart-renamed-v1"
    assert refinalized["failed_checks"] == []
    assert refinalized["plan_state"] == "prepared"
    assert refinalized["eligibility_status"] == "ready_to_start"
    assert refinalized["total_added_droplets"] == 0
    assert refinalized["well_ids"] == ["A1", "A2", "A3", "A4", "A5", "A6"]
    assert before["plan_id"] != after["plan_id"]
    assert refinalized["experiment_directories"] == [
        "sil-editor-prestart-renamed-v1"
    ]
    assert refinalized["staging_directories"] == []
    assert reloaded["eligibility_status"] == "ready_to_start"
    assert reloaded["resume_state"] == "clean"
    assert reloaded["resume_intent_count"] == 0

    report_dir = Path(report["safety"]["scenario_root"]).parent
    assert set(report["artifacts"]["screenshots"]) == {
        "editor_opened",
        "generated",
        "initial_finalized",
        "rename_editor_opened",
        "renamed",
        "prepared_design_edited",
        "regenerated",
        "refinalized",
        "reloaded",
        "validated",
    }
    for relative in report["artifacts"]["screenshots"].values():
        path = report_dir / relative
        assert path.is_file()
        assert path.stat().st_size > 0
    assert not (report_dir / "failure_traceback.txt").exists()


@pytest.mark.sil_lifecycle
def test_editor_rename_failure_retains_evidence_and_incomplete_assertions(
    qapp,
    tmp_path,
    monkeypatch,
):
    import tools.virtual_workflows.editor_scenarios as scenarios

    def fail_refinalize(
        _context,
        *,
        initial_name,
        renamed_name,
        experiment,
        reagent,
    ):
        raise ScenarioActionError(
            "editor.refinalize_prepared_via_ui",
            "synthetic prepared refinalization failure",
            stage="operation",
            evidence={
                "initial_name": initial_name,
                "renamed_name": renamed_name,
            },
        )

    monkeypatch.setattr(
        scenarios,
        "drive_editor_prestart_rename_refinalize",
        fail_refinalize,
    )
    report = run_editor_prestart_rename_refinalize_scenario(
        EditorLifecycleScenarioConfig(
            output_root=tmp_path,
            scenario_id=RENAME_WORKLOAD_ID,
            timeout_seconds=60,
            run_id="editor-rename-failure",
        )
    )

    assert report["classification"]["status"] == "fail"
    assertions = {
        item["assertion_id"]: item["decision"]
        for item in report["metrics"]["workflow"]["values"][
            "assertion_results"
        ]
    }
    assert assertions["experiment.prepared_rename_refinalize"] == "fail"
    assert assertions["artifacts.required_present"] == "fail"
    assert assertions["experiment.refinalized_bundle_valid"] == "incomplete"
    assert assertions["experiment.prepared_reload_ready"] == "incomplete"
    assert {
        item["status"]
        for item in report["metrics"]["workflow"]["values"]["cleanup_results"]
    } == {"pass"}
    persistence = report["metrics"]["persistence"]["values"]
    assert persistence["prepared_bundle"]["failed_checks"] == []
    assert persistence["rename_refinalization"]["before"]["metadata_name"] == (
        "sil-editor-prestart-rename-v1"
    )
    report_dir = Path(report["safety"]["scenario_root"]).parent
    assert (report_dir / "failure_traceback.txt").is_file()
