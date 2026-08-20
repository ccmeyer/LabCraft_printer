from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.virtual_workflows.journeys import (
    NEW_EXPERIMENT_SESSION_REQUIRED_ASSERTIONS,
    NEW_EXPERIMENT_SESSION_REQUIRED_SCREENSHOTS,
    NEW_EXPERIMENT_SESSION_REQUIRED_UI_ACTIONS,
    NEW_EXPERIMENT_SESSION_WORKLOAD_ID,
    get_journey_definition,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import load_virtual_print_array_fixture


def test_new_experiment_session_fixture_contract_is_exact():
    fixture = load_virtual_print_array_fixture(
        scenario_id=NEW_EXPERIMENT_SESSION_WORKLOAD_ID
    )

    assert fixture["fixture_id"] == NEW_EXPERIMENT_SESSION_WORKLOAD_ID
    assert fixture["schema_version"] == 3
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
        "stock_count": 1,
        "array_passes": 1,
        "completion_count": 24,
    }
    assert fixture["stocks"] == [
        {
            "factor_name": "New Session SIL Stock",
            "concentration": 1.0,
            "target_concentration": 1.0,
            "units": "x",
            "printing_mode": "droplet",
            "prepared_droplet_volume_nL": 5.0,
            "droplet_volume_nL": 10.0,
            "printer_head": {
                "printer_head_id": "virtual-head-new-session-v1",
                "initial_volume_uL": 1000.0,
                "print_pulse_width_us": 1300,
                "print_pressure_psi": 1.2,
            },
        }
    ]
    assert fixture["fill_stock"] == {
        "factor_name": "Water",
        "concentration": 1.0,
        "units": "--",
        "printing_mode": "droplet",
        "droplet_volume_nL": 10.0,
        "target_dispenses_per_well": 0,
    }
    assert fixture["simulation"] == {
        "dispense_frequency_hz": 20,
        "lookahead_wells": 2,
        "staging_slot": 0,
    }
    assert fixture["lifecycle"] == {
        "kind": "new_experiment_session_hardening",
        "request_after_completion_count": 6,
        "maximum_completion_catchup": 2,
        "quiescence_observation_ms": 250,
        "candidate_name": "Untitled-20300102_030405",
        "collision_names": [
            "Untitled-20300102_030405",
            "Untitled-20300102_030405-2",
        ],
        "failed_candidate_name": "Untitled-20300102_030405-3",
        "resume_success_name": "Untitled-20300102_030405-3",
        "idle_success_name": "Untitled-20300102_030405-4",
        "failure_stage": "validation",
    }


@pytest.mark.sil_lifecycle
def test_new_experiment_session_hardening_report(qapp, tmp_path):
    definition = get_journey_definition(NEW_EXPERIMENT_SESSION_WORKLOAD_ID)
    report = run_registered_scenario(
        NEW_EXPERIMENT_SESSION_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="new-experiment-session-hardening",
        seed=17,
    )
    validate_report_v1(report)

    workflow = report["metrics"]["workflow"]["values"]
    assert report["classification"]["status"] == "pass", json.dumps(
        {
            "failed_actions": [
                (row["action_id"], row.get("message"))
                for row in workflow["action_results"]
                if row["status"] != "pass"
            ],
            "failed_assertions": [
                (
                    row["assertion_id"],
                    row.get("message"),
                    (row.get("evidence") or {}).get("checks"),
                    {
                        "before_context": ((row.get("evidence") or {}).get("before") or {}).get("array_context_id"),
                        "after_context": ((row.get("evidence") or {}).get("after") or {}).get("array_context_id"),
                    },
                )
                for row in workflow["assertion_results"]
                if row["decision"] != "pass"
            ],
            "errors": workflow["errors"],
        },
        indent=2,
    )
    assert report["run"]["scenario_name"] == "experiment_new_session_hardening"
    assert report["workload"]["workload_id"] == NEW_EXPERIMENT_SESSION_WORKLOAD_ID
    assert report["workload"]["expected_completion_count"] == 24
    assert 6 <= report["workload"]["paused_completion_count"] <= 8

    actions = workflow["action_results"]
    assert {row["action_id"] for row in actions} == set(
        definition.required_action_ids
    )
    assert {row["status"] for row in actions} == {"pass"}
    assert {
        row["action_id"]: row["interaction_surface"]
        for row in actions
        if row["action_id"] in NEW_EXPERIMENT_SESSION_REQUIRED_UI_ACTIONS
    } == {
        action_id: "ui"
        for action_id in NEW_EXPERIMENT_SESSION_REQUIRED_UI_ACTIONS
    }
    assert [row["name"] for row in workflow["lifecycle_milestones"]] == [
        "editor_opened",
        "generated",
        "ready",
        "printing",
        "stop_requested",
        "stopped",
        "resume_ready_editor",
        "new_session_cancelled_prompt",
        "new_session_cancelled",
        "new_session_failure_preserved_prompt",
        "new_session_validation_failure",
        "new_session_failure_preserved",
        "new_session_resume_created_prompt",
        "new_session_resume_created",
        "new_session_idle_created",
    ]
    assert workflow["unexpected_dialogs"] == []
    assert workflow["errors"] == []
    assert {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    } == {
        assertion_id: "pass"
        for assertion_id in NEW_EXPERIMENT_SESSION_REQUIRED_ASSERTIONS
    }

    persistence = report["metrics"]["persistence"]["values"]
    boundary = persistence["new_session"]
    collisions = persistence["collisions"]
    assert boundary["load_signal_count"] == 2
    assert boundary["generation_signal_count"] == 0
    assert boundary["failed"]["failed_candidate_exists"] is False
    assert boundary["resumed"]["after"]["experiment_name"].endswith("-3")
    assert boundary["idle"]["after"]["experiment_name"].endswith("-4")
    assert boundary["resume_hashes_before_idle"] == boundary[
        "resume_hashes_after_idle"
    ]
    assert boundary["opened"]["directory_hashes"] == boundary[
        "source_hashes_final"
    ]
    assert collisions["hashes_before"] == collisions["hashes_after"]

    assert set(report["artifacts"]["screenshots"]) == set(
        NEW_EXPERIMENT_SESSION_REQUIRED_SCREENSHOTS
    )
    assert {row["status"] for row in workflow["cleanup_results"]} == {"pass"}
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
def test_new_experiment_session_driver_failure_retains_evidence(
    qapp, tmp_path, monkeypatch
):
    from tools.virtual_workflows import page_drivers

    def fail_driver(_self, **_kwargs):
        raise RuntimeError("synthetic New Experiment driver failure")

    monkeypatch.setattr(
        page_drivers.ExperimentEditorDriver,
        "exercise_new_session_hardening",
        fail_driver,
    )
    report = run_registered_scenario(
        NEW_EXPERIMENT_SESSION_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="new-experiment-session-driver-failure",
        seed=19,
    )
    validate_report_v1(report)

    assert report["classification"]["status"] == "fail"
    workflow = report["metrics"]["workflow"]["values"]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert decisions["execution.stopped_boundary_quiescent"] == "pass"
    assert decisions["experiment.new_session_cancel_preserves_active"] == "incomplete"
    assert decisions["artifacts.required_present"] == "fail"
    assert {row["status"] for row in workflow["cleanup_results"]} == {"pass"}
    report_dir = Path(report["safety"]["report_dir"])
    assert (report_dir / "failure_traceback.txt").is_file()
    assert (report_dir / "action_ledger.json").is_file()
    assert (report_dir / "assertion_ledger.json").is_file()
    assert (report_dir / "evidence_manifest.json").is_file()
    assert not (Path(report["safety"]["scenario_root"]) / ".sil-session.lock").exists()
