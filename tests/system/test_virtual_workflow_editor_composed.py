import json
import hashlib
from pathlib import Path

import pytest

from tools.virtual_workflows.editor_scenarios import (
    ASSERTION_IDS,
    WORKLOAD_ID,
    EditorLifecycleScenarioConfig,
    load_editor_create_finalize_fixture,
    run_editor_create_finalize_scenario,
)
from tools.virtual_workflows.journeys import (
    EDITOR_REQUIRED_ASSERTIONS,
    EDITOR_REQUIRED_SCREENSHOTS,
    EDITOR_REQUIRED_UI_ACTIONS,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1


def test_editor_create_finalize_fixture_contract_is_exact():
    fixture = load_editor_create_finalize_fixture()

    assert fixture["fixture_id"] == WORKLOAD_ID
    assert fixture["schema_version"] == 1
    assert fixture["experiment"]["expected_well_ids"] == ["A1", "A2"]
    assert fixture["experiment"]["replicates"] == 2
    assert fixture["experiment"]["printed_volume_nL"] == 10.0
    assert fixture["reagent"]["printing_mode"] == "droplet"
    assert fixture["reagent"]["droplet_volume_nL"] == 10.0
    assert fixture["workload"] == {
        "completion_count": 1,
        "expected_editor_finalization_operations": 1,
    }


@pytest.mark.sil_lifecycle
def test_composed_editor_create_finalize_report(qapp, tmp_path):
    report = run_registered_scenario(
        WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="composed-editor-success",
        seed=7,
    )
    validate_report_v1(report)

    assert report["classification"]["status"] == "pass", json.dumps(
        report["classification"], indent=2
    )
    assert report["run"]["scenario_name"] == "experiment_editor_create_finalize"
    assert report["run"]["scenario_version"] == "1"
    assert report["run"]["seed"] == 7
    assert report["workload"]["well_ids"] == ["A1", "A2"]
    assert report["safety"]["root_containment_valid"] is True
    assert not any(report["safety"]["hardware_interfaces"].values())

    workflow = report["metrics"]["workflow"]["values"]
    assert workflow["unexpected_dialogs"] == []
    assert workflow["errors"] == []
    assert [row["name"] for row in workflow["lifecycle_milestones"]] == [
        "editor_opened",
        "generated",
        "finalized",
        "reloaded",
        "validated",
    ]
    assert {row["status"] for row in workflow["action_results"]} == {"pass"}
    surfaces = {
        row["action_id"]: row["interaction_surface"]
        for row in workflow["action_results"]
        if row["action_id"] in EDITOR_REQUIRED_UI_ACTIONS
    }
    assert surfaces == {
        action_id: "ui" for action_id in EDITOR_REQUIRED_UI_ACTIONS
    }
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert tuple(decisions) == EDITOR_REQUIRED_ASSERTIONS
    assert decisions == {
        assertion_id: "pass" for assertion_id in EDITOR_REQUIRED_ASSERTIONS
    }

    persistence = report["metrics"]["persistence"]["values"]
    prepared = persistence["prepared_bundle"]
    reloaded = persistence["reload_activation"]
    assert prepared["plan_revision"] == 1
    assert prepared["plan_state"] == "prepared"
    assert prepared["eligibility_status"] == "ready_to_start"
    assert prepared["well_ids"] == ["A1", "A2"]
    assert prepared["total_added_droplets"] == 0
    assert prepared["resume_present"] is False
    assert reloaded["plan_id"] == prepared["plan_id"]
    assert reloaded["plan_revision"] == prepared["plan_revision"]
    assert reloaded["plan_state"] == "prepared"
    assert reloaded["eligibility_status"] == "ready_to_start"
    assert reloaded["activation_performed"] is False
    assert reloaded["runtime_active"] is False
    assert reloaded["resume_present"] is False

    report_dir = Path(report["safety"]["report_dir"])
    scenario_root = Path(report["safety"]["scenario_root"])
    assert scenario_root.is_dir()
    assert not (scenario_root / ".sil-session.lock").exists()
    assert set(report["artifacts"]["screenshots"]) == EDITOR_REQUIRED_SCREENSHOTS
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


@pytest.mark.sil_lifecycle
def test_composed_editor_matches_legacy_stable_prepared_contract(qapp, tmp_path):
    legacy = run_editor_create_finalize_scenario(
        EditorLifecycleScenarioConfig(
            output_root=tmp_path / "legacy",
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
            run_id="legacy-parity",
        )
    )
    composed = run_registered_scenario(
        WORKLOAD_ID,
        output_root=tmp_path / "composed",
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="composed-parity",
        seed=1,
    )

    assert legacy["classification"]["status"] == "pass"
    assert composed["classification"]["status"] == "pass"
    assert legacy["run"]["scenario_name"] == composed["run"]["scenario_name"]
    assert legacy["run"]["scenario_version"] == composed["run"]["scenario_version"]
    assert legacy["workload"]["workload_id"] == composed["workload"]["workload_id"]
    fixture_path = Path(
        "tools/virtual_workflows/fixtures/experiment_editor_create_finalize_v1.json"
    )
    assert composed["workload"]["fixture_sha256"] == hashlib.sha256(
        fixture_path.read_bytes()
    ).hexdigest()
    assert legacy["workload"]["well_ids"] == composed["workload"]["well_ids"]
    assert tuple(ASSERTION_IDS) == EDITOR_REQUIRED_ASSERTIONS
    for report in (legacy, composed):
        decisions = {
            row["assertion_id"]: row["decision"]
            for row in report["metrics"]["workflow"]["values"]["assertion_results"]
        }
        assert decisions == {assertion_id: "pass" for assertion_id in ASSERTION_IDS}
        prepared = report["metrics"]["persistence"]["values"]["prepared_bundle"]
        assert prepared["plan_revision"] == 1
        assert prepared["plan_state"] == "prepared"
        assert prepared["eligibility_status"] == "ready_to_start"
        assert prepared["well_ids"] == ["A1", "A2"]
        assert prepared["total_added_droplets"] == 0

    composed_reload = composed["metrics"]["persistence"]["values"][
        "reload_activation"
    ]
    assert composed_reload["activation_performed"] is False
    assert composed_reload["runtime_active"] is False
    assert composed_reload["resume_present"] is False


@pytest.mark.sil_lifecycle
def test_composed_editor_unexpected_dialog_retains_failure_evidence(
    qapp, tmp_path, monkeypatch
):
    from PySide6 import QtWidgets
    from tools.virtual_workflows.page_drivers import ExperimentLoaderDriver

    def leave_unexpected_dialog(self, *_args, **_kwargs):
        dialog = QtWidgets.QDialog(self.context.view)
        dialog.setWindowTitle("Injected unexpected dialog")
        dialog.show()
        self.context.app.processEvents()
        return {"injected": True}

    monkeypatch.setattr(
        ExperimentLoaderDriver,
        "load_prepared_design",
        leave_unexpected_dialog,
    )
    report = run_registered_scenario(
        WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="composed-editor-failure",
        seed=1,
    )

    assert report["classification"]["status"] == "fail"
    workflow = report["metrics"]["workflow"]["values"]
    failed_action = next(
        row
        for row in workflow["action_results"]
        if row["action_id"] == "experiment.load_authoritative_via_ui"
    )
    assert failed_action["status"] == "fail"
    assert workflow["unexpected_dialogs"] == [
        {"type": "QDialog", "title": "Injected unexpected dialog"}
    ]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert decisions["experiment.prepared_bundle_valid"] == "pass"
    assert decisions["experiment.prepared_reload_ready"] == "incomplete"
    assert decisions["experiment.runtime_assignments_match"] == "incomplete"
    assert decisions["experiment.key_files_consistent"] == "incomplete"
    assert decisions["artifacts.required_present"] == "fail"

    report_dir = Path(report["safety"]["report_dir"])
    scenario_root = Path(report["safety"]["scenario_root"])
    assert (report_dir / "failure_traceback.txt").is_file()
    assert (report_dir / "screenshots" / "failure.png").is_file()
    assert (report_dir / "evidence_manifest.json").is_file()
    assert not (scenario_root / ".sil-session.lock").exists()
