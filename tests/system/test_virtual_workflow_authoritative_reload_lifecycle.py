from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.virtual_workflows.actions import AUTHORITATIVE_RELOAD_ACTION_IDS
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
    VirtualPrintArrayScenarioConfig,
    fixture_well_ids,
    load_virtual_print_array_fixture,
    run_virtual_print_array_scenario,
)


def test_authoritative_reload_resume_fixture_contract_is_exact():
    fixture = load_virtual_print_array_fixture(
        scenario_id=AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID
    )

    assert fixture["schema_version"] == 3
    assert fixture["fixture_id"] == AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID
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
    assert fixture["simulation"] == {
        "dispense_frequency_hz": 20,
        "lookahead_wells": 2,
        "staging_slot": 0,
    }
    assert fixture["lifecycle"] == {
        "kind": "authoritative_reload_resume",
        "request_after_completion_count": 6,
        "maximum_completion_catchup": 2,
        "quiescence_observation_ms": 250,
        "expected_application_session_count": 2,
    }
    assert fixture_well_ids(fixture) == tuple(
        f"A{column}" for column in range(1, 25)
    )
    assert fixture["stocks"][0]["factor_name"] == "Virtual Reload Stock"
    assert fixture["stocks"][0]["printer_head"]["printer_head_id"] == (
        "virtual-head-reload-24-v1"
    )


@pytest.mark.sil_lifecycle
def test_authoritative_reload_retains_strict_editor_failure_evidence(
    qapp,
    tmp_path,
):
    report = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            scenario_id=AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
            output_root=tmp_path,
            timeout_seconds=60,
            run_id="authoritative-reload-lifecycle",
        )
    )

    validate_report_v1(report)
    assert report["classification"]["status"] == "fail"
    assert report["run"]["scenario_name"] == "authoritative_reload_resume"
    workflow = report["metrics"]["workflow"]["values"]
    actions = workflow["action_results"]
    assert {
        item["action_id"] for item in actions
    }.issubset(AUTHORITATIVE_RELOAD_ACTION_IDS)
    launches = [
        item for item in actions if item["action_id"] == "app.launch_simulated"
    ]
    assert len(launches) == 2
    assert {item["application_session_id"] for item in launches} == {
        "session_1",
        "session_2",
    }
    assert {item["status"] for item in launches} == {"pass"}
    assert next(
        item
        for item in actions
        if item["action_id"] == "app.close_simulated_session"
    )["status"] == "pass"

    failed_load = next(
        item
        for item in actions
        if item["action_id"] == "experiment.load_authoritative_via_ui"
    )
    assert failed_load["status"] == "fail"
    assert failed_load["application_session_id"] == "session_2"
    evidence = failed_load["evidence"]
    assert evidence["eligibility"]["status"] == "blocked"
    assert evidence["checks"]["runtime_inactive"]
    assert evidence["checks"]["name_matches"]
    assert not evidence["checks"]["eligibility_ready_to_resume"]
    identity = evidence["design_identity"]
    assert identity["disk_design_sha256"] == identity["plan_design_sha256"]
    assert identity["model_design_sha256"] != identity["plan_design_sha256"]

    assertions = {
        item["assertion_id"]: item["decision"]
        for item in workflow["assertion_results"]
    }
    assert assertions["ui.real_app_constructed"] == "pass"
    assert assertions["ui.fresh_application_session_constructed"] == "pass"
    assert assertions["execution.first_session_paused"] == "pass"
    assert assertions["execution.first_session_teardown_clean"] == "pass"
    assert assertions["execution.authoritative_reload_valid"] == "fail"
    assert assertions["execution.authoritative_runtime_rehydrated"] == (
        "incomplete"
    )
    assert assertions["execution.reload_resume_exactly_once"] == "incomplete"

    assert [item["name"] for item in workflow["lifecycle_milestones"]] == [
        "session_1_ready",
        "session_1_printing",
        "session_1_stop_requested",
        "session_1_stopped",
        "session_2_load_failed",
    ]
    report_dir = Path(report["safety"]["scenario_root"]).parent
    failure_image = report["artifacts"]["screenshots"][
        "session_2_load_failed"
    ]
    assert (report_dir / failure_image).stat().st_size > 0
    assert report["artifacts"]["failure_traceback"] == "failure_traceback.txt"
    traceback_text = (
        report_dir / report["artifacts"]["failure_traceback"]
    ).read_text(encoding="utf-8")
    assert "loaded authoritative editor state is invalid" in traceback_text
    assert json.loads(
        (report_dir / "report.json").read_text(encoding="utf-8")
    )["classification"]["status"] == "fail"
