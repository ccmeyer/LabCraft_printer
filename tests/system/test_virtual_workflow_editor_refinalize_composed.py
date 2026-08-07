import hashlib
import json
from pathlib import Path

import pytest

from tools.virtual_workflows.actions import ScenarioActionError
from tools.virtual_workflows.editor_scenarios import (
    EditorLifecycleScenarioConfig,
    RENAME_ASSERTION_IDS,
    RENAME_WORKLOAD_ID,
    run_editor_prestart_rename_refinalize_scenario,
)
from tools.virtual_workflows.journeys import (
    EDITOR_REVISION_REQUIRED_ASSERTIONS,
    EDITOR_REVISION_REQUIRED_SCREENSHOTS,
    EDITOR_REVISION_REQUIRED_UI_ACTIONS,
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
    "experiment.load_authoritative_via_ui",
    "artifact.capture_milestone",
    "artifact.capture_milestone",
    "scenario.teardown",
]


@pytest.mark.sil_lifecycle
def test_composed_editor_prestart_rename_refinalize_report(qapp, tmp_path):
    report = run_registered_scenario(
        RENAME_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="composed-editor-refinalize-success",
        seed=7,
    )
    validate_report_v1(report)

    assert report["classification"]["status"] == "pass", json.dumps(
        report["classification"], indent=2
    )
    assert report["run"]["scenario_name"] == (
        "experiment_editor_prestart_rename_refinalize"
    )
    assert report["run"]["seed"] == 7
    assert report["workload"]["experiment_name"] == (
        "sil-editor-prestart-rename-v1"
    )
    assert report["workload"]["renamed_experiment_name"] == (
        "sil-editor-prestart-renamed-v1"
    )
    assert report["workload"]["well_ids"] == [
        "A1", "A2", "A3", "A4", "A5", "A6"
    ]
    assert report["safety"]["root_containment_valid"] is True
    assert not any(report["safety"]["hardware_interfaces"].values())

    workflow = report["metrics"]["workflow"]["values"]
    assert workflow["unexpected_dialogs"] == []
    assert workflow["errors"] == []
    assert [row["action_id"] for row in workflow["action_results"]] == (
        EXPECTED_ACTION_IDS
    )
    assert {row["status"] for row in workflow["action_results"]} == {"pass"}
    ui_rows = [
        row
        for row in workflow["action_results"]
        if row["action_id"] in EDITOR_REVISION_REQUIRED_UI_ACTIONS
    ]
    assert ui_rows
    assert {row["interaction_surface"] for row in ui_rows} == {"ui"}
    assert [row["name"] for row in workflow["lifecycle_milestones"]] == [
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
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert tuple(decisions) == EDITOR_REVISION_REQUIRED_ASSERTIONS
    assert decisions == {
        assertion_id: "pass"
        for assertion_id in EDITOR_REVISION_REQUIRED_ASSERTIONS
    }

    persistence = report["metrics"]["persistence"]["values"]
    before = persistence["rename_refinalization"]["before"]
    final = persistence["refinalized_bundle"]
    reloaded = persistence["reload_activation"]
    assert before["metadata_name"] == "sil-editor-prestart-rename-v1"
    assert final["failed_checks"] == []
    assert final["plan_id"] != before["plan_id"]
    assert final["plan_revision"] == 1
    assert final["plan_state"] == "prepared"
    assert final["eligibility_status"] == "ready_to_start"
    assert final["well_ids"] == ["A1", "A2", "A3", "A4", "A5", "A6"]
    assert final["total_added_droplets"] == 0
    assert final["experiment_directories"] == [
        "sil-editor-prestart-renamed-v1"
    ]
    assert final["staging_directories"] == []
    assert reloaded["plan_id"] == final["plan_id"]
    assert reloaded["plan_state"] == "prepared"
    assert reloaded["eligibility_status"] == "ready_to_start"
    assert reloaded["activation_performed"] is False
    assert reloaded["runtime_active"] is False

    report_dir = Path(report["safety"]["report_dir"])
    scenario_root = Path(report["safety"]["scenario_root"])
    assert set(report["artifacts"]["screenshots"]) == (
        EDITOR_REVISION_REQUIRED_SCREENSHOTS
    )
    for relative in report["artifacts"]["screenshots"].values():
        assert (report_dir / relative).stat().st_size > 0
    for name in (
        "report.json",
        "summary.txt",
        "events.jsonl",
        "action_ledger.json",
        "assertion_ledger.json",
        "evidence_manifest.json",
    ):
        assert (report_dir / name).is_file()
    assert not (report_dir / "failure_traceback.txt").exists()
    assert not (scenario_root / ".sil-session.lock").exists()


@pytest.mark.sil_lifecycle
def test_composed_and_legacy_editor_refinalize_stable_parity(qapp, tmp_path):
    legacy = run_editor_prestart_rename_refinalize_scenario(
        EditorLifecycleScenarioConfig(
            scenario_id=RENAME_WORKLOAD_ID,
            output_root=tmp_path / "legacy",
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
            run_id="legacy-editor-refinalize-parity",
        )
    )
    composed = run_registered_scenario(
        RENAME_WORKLOAD_ID,
        output_root=tmp_path / "composed",
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="composed-editor-refinalize-parity",
        seed=1,
    )

    assert legacy["classification"]["status"] == "pass"
    assert composed["classification"]["status"] == "pass"
    for field in ("scenario_name", "scenario_version"):
        assert legacy["run"][field] == composed["run"][field]
    assert legacy["workload"]["workload_id"] == composed["workload"][
        "workload_id"
    ]
    fixture_path = Path(
        "tools/virtual_workflows/fixtures/"
        "experiment_editor_prestart_rename_refinalize_v1.json"
    )
    assert composed["workload"]["fixture_sha256"] == hashlib.sha256(
        fixture_path.read_bytes()
    ).hexdigest()
    assert tuple(RENAME_ASSERTION_IDS) == EDITOR_REVISION_REQUIRED_ASSERTIONS
    for report in (legacy, composed):
        decisions = {
            row["assertion_id"]: row["decision"]
            for row in report["metrics"]["workflow"]["values"][
                "assertion_results"
            ]
        }
        assert decisions == {
            assertion_id: "pass" for assertion_id in RENAME_ASSERTION_IDS
        }
        final = report["metrics"]["persistence"]["values"][
            "refinalized_bundle"
        ]
        assert final["failed_checks"] == []
        assert final["plan_revision"] == 1
        assert final["plan_state"] == "prepared"
        assert final["eligibility_status"] == "ready_to_start"
        assert final["well_ids"] == ["A1", "A2", "A3", "A4", "A5", "A6"]
        assert final["total_added_droplets"] == 0
        assert final["experiment_directories"] == [
            "sil-editor-prestart-renamed-v1"
        ]
        assert final["staging_directories"] == []


@pytest.mark.sil_lifecycle
def test_composed_editor_refinalize_failure_retains_evidence(
    qapp, tmp_path, monkeypatch
):
    from tools.virtual_workflows.page_drivers import ExperimentEditorDriver

    def fail_refinalize(self, **_values):
        for action_id in (
            "editor.open_via_ui",
            "editor.rename_prepared_via_ui",
            "editor.edit_prepared_design_via_ui",
            "editor.regenerate_prepared_design_via_ui",
        ):
            self.action_runner(action_id, lambda: {"synthetic": True})

        def fail():
            raise ScenarioActionError(
                "editor.refinalize_prepared_via_ui",
                "synthetic prepared refinalization failure",
                stage="operation",
            )

        return self.action_runner("editor.refinalize_prepared_via_ui", fail)

    monkeypatch.setattr(
        ExperimentEditorDriver,
        "revise_prepared_design",
        fail_refinalize,
    )
    report = run_registered_scenario(
        RENAME_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="composed-editor-refinalize-failure",
        seed=1,
    )

    assert report["classification"]["status"] == "fail"
    workflow = report["metrics"]["workflow"]["values"]
    failed_action = next(
        row
        for row in workflow["action_results"]
        if row["action_id"] == "editor.refinalize_prepared_via_ui"
    )
    assert failed_action["status"] == "fail"
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert decisions["experiment.prepared_rename_refinalize"] == "fail"
    assert decisions["experiment.prepared_design_refinalize"] == "incomplete"
    assert decisions["experiment.refinalized_bundle_valid"] == "incomplete"
    assert decisions["experiment.prepared_reload_ready"] == "incomplete"
    assert decisions["artifacts.required_present"] == "fail"
    assert {
        row["status"] for row in workflow["cleanup_results"]
    } == {"pass"}
    persistence = report["metrics"]["persistence"]["values"]
    assert persistence["prepared_bundle"]["failed_checks"] == []
    assert persistence["rename_refinalization"]["before"]["metadata_name"] == (
        "sil-editor-prestart-rename-v1"
    )
    report_dir = Path(report["safety"]["report_dir"])
    scenario_root = Path(report["safety"]["scenario_root"])
    assert (report_dir / "failure_traceback.txt").is_file()
    assert (report_dir / "screenshots" / "failure.png").is_file()
    assert (report_dir / "evidence_manifest.json").is_file()
    assert not (scenario_root / ".sil-session.lock").exists()
