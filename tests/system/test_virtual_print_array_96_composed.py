from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.virtual_workflows.journeys import (
    REGRESSION_REQUIRED_ASSERTIONS,
    REGRESSION_WORKLOAD_ID,
    JourneyRunConfig,
    get_journey_definition,
    run_composed_journey,
)
from tools.virtual_workflows.registry import get_registered_scenario
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    VirtualPrintArrayScenarioConfig,
    load_virtual_print_array_fixture,
    run_virtual_print_array_scenario,
)


FIXTURE_SHA256 = "25bec67be06a73d4c43766c328ce218731e577c75f8aeae08021b81cd9fe8ff1"
SCREENSHOTS = {
    "editor_opened",
    "generated",
    "ready",
    "printing",
    "mid_array",
    "completed",
}
FORBIDDEN_LEGACY_ACTIONS = {
    "fixture.prepare_authoritative",
    "machine.connect_ready",
    "head.stage_virtual",
    "validation.terminal_bundle",
}


def _report_dir(root: Path) -> Path:
    reports = list(root.rglob("report.json"))
    assert len(reports) == 1
    return reports[0].parent


def _action(report, action_id):
    return next(
        row
        for row in report["metrics"]["workflow"]["values"]["action_results"]
        if row["action_id"] == action_id
    )


def _decisions(report):
    return {
        row["assertion_id"]: row["decision"]
        for row in report["metrics"]["workflow"]["values"]["assertion_results"]
    }


def test_composed_96_contract_uses_shared_one_stock_journey():
    fixture, path = load_virtual_print_array_fixture(
        scenario_id=REGRESSION_WORKLOAD_ID
    ), get_registered_scenario(REGRESSION_WORKLOAD_ID).fixture_path
    definition = get_journey_definition(REGRESSION_WORKLOAD_ID)

    assert get_registered_scenario(REGRESSION_WORKLOAD_ID).runner_family == (
        "composed_journey"
    )
    assert definition.midpoint_completion_count == 48
    assert definition.required_assertion_ids == REGRESSION_REQUIRED_ASSERTIONS
    assert definition.required_screenshots == SCREENSHOTS
    assert hashlib.sha256(path.read_bytes()).hexdigest() == FIXTURE_SHA256
    assert fixture["stock"]["prepared_droplet_volume_nL"] == 5.0
    assert fixture["stock"]["droplet_volume_nL"] == 10.0
    with pytest.raises(ValueError, match="96-well workload"):
        JourneyRunConfig(
            scenario_id=REGRESSION_WORKLOAD_ID,
            inject_after_completion=97,
        )


@pytest.mark.sil_regression
def test_composed_96_success_and_legacy_parity(qapp, tmp_path):
    legacy_root = tmp_path / "legacy"
    composed_root = tmp_path / "composed"
    legacy = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            output_root=legacy_root,
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
            run_id="slice7-legacy-parity",
        )
    )
    composed = run_composed_journey(
        JourneyRunConfig(
            scenario_id=REGRESSION_WORKLOAD_ID,
            output_root=composed_root,
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
            run_id="slice7-composed-success",
        )
    )
    validate_report_v1(composed)

    assert legacy["classification"]["status"] == "pass"
    assert composed["classification"]["status"] == "pass"
    assert composed["workload"]["workload_id"] == REGRESSION_WORKLOAD_ID
    assert composed["workload"]["fixture_sha256"] == FIXTURE_SHA256
    assert composed["workload"]["well_ids"] == legacy["workload"]["well_ids"]
    workflow = composed["metrics"]["workflow"]["values"]
    legacy_workflow = legacy["metrics"]["workflow"]["values"]
    assert workflow["completed_well_ids"] == composed["workload"]["well_ids"]
    assert workflow["completed_well_count"] == 96
    assert workflow["array_complete_count"] == 1
    assert legacy_workflow["completed_well_count"] == 96
    assert legacy_workflow["array_complete_count"] == 1
    assert [row["name"] for row in workflow["lifecycle_milestones"]] == [
        "editor_opened",
        "generated",
        "ready",
        "printing",
        "mid_array",
        "completed",
    ]

    actions = workflow["action_results"]
    action_ids = {row["action_id"] for row in actions}
    assert not action_ids & FORBIDDEN_LEGACY_ACTIONS
    assert {row["status"] for row in actions} == {"pass"}
    assert all(
        row["interaction_surface"] == "ui"
        for row in actions
        if row["action_id"].endswith("_via_ui")
    )
    selected = _action(composed, "calibration.select_via_ui")["evidence"]
    preview = _action(composed, "calibration.apply_via_ui")["evidence"][
        "preview"
    ]["payload"]
    assert selected["source_volume_nL"] == 5.0
    assert selected["pw_us"] == 1300
    assert selected["pressure_psi"] == pytest.approx(1.2, abs=0.001)
    assert selected["mean_nL"] == preview["new_droplet_nL"] == 9.0

    assert _decisions(composed) == {
        assertion_id: "pass" for assertion_id in REGRESSION_REQUIRED_ASSERTIONS
    }
    queue = composed["metrics"]["queue"]["values"]
    persistence = composed["metrics"]["persistence"]["values"]
    responsiveness = composed["metrics"]["responsiveness"]["values"]
    assert queue["unexpected_starvation_count"] == 0
    assert legacy["metrics"]["queue"]["values"][
        "unexpected_starvation_count"
    ] == 0
    assert persistence["intent_count"] == 96
    assert persistence["observed_completed_intent_count"] == 96
    assert persistence["checkpoint_retained_intent_count"] == 0
    assert persistence["terminal_plan_state"] == "completed"
    assert persistence["authoritative_io"]["resume_save_fsync_count"] == 288
    assert persistence["authoritative_io"]["progress_write_fsync_count"] == 96
    assert persistence["authoritative_io"]["observer_restored"] is True
    assert responsiveness["shutdown"] == {
        "timer_active": False,
        "observer_thread_alive": False,
    }
    for phase in (
        "persistence.write_progress",
        "persistence.complete_intent",
        "controller.well_completion",
    ):
        assert responsiveness["phase_timings"]["duration_by_name_ms"][phase][
            "count"
        ] == 96

    report_dir = _report_dir(composed_root)
    assert set(composed["artifacts"]["screenshots"]) == SCREENSHOTS
    for name in (
        "report.json",
        "summary.txt",
        "events.jsonl",
        "stall_stacks.txt",
        "action_ledger.json",
        "assertion_ledger.json",
        "evidence_manifest.json",
    ):
        assert (report_dir / name).is_file()
    assert json.loads((report_dir / "report.json").read_text(encoding="utf-8")) == (
        composed
    )


@pytest.mark.sil_regression
def test_composed_96_injected_stall_is_attributed(qapp, tmp_path):
    report = run_composed_journey(
        JourneyRunConfig(
            scenario_id=REGRESSION_WORKLOAD_ID,
            output_root=tmp_path,
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
            run_id="slice7-composed-injected",
            inject_ui_stall_ms=300,
            inject_after_completion=48,
        )
    )

    assert report["classification"]["status"] == "pass"
    assessment = report["metrics"]["responsiveness"]["values"][
        "injected_stall_assessment"
    ]
    assert assessment["decision"] == "detected"
    assert assessment["stack_captured"] is True
    assert "injected_ui_stall" in (
        _report_dir(tmp_path) / "stall_stacks.txt"
    ).read_text(encoding="utf-8")
    assert report["run"]["replay_command"][-4:] == [
        "--inject-ui-stall-ms",
        "300",
        "--inject-after-completion",
        "48",
    ]


@pytest.mark.sil_regression
def test_composed_96_timeout_fails_closed_with_evidence(qapp, tmp_path):
    report = run_composed_journey(
        JourneyRunConfig(
            scenario_id=REGRESSION_WORKLOAD_ID,
            output_root=tmp_path,
            speed_multiplier=1.0,
            timeout_seconds=0.1,
            run_id="slice7-composed-timeout",
        )
    )

    assert report["classification"]["status"] == "fail"
    assert any(decision != "pass" for decision in _decisions(report).values())
    report_dir = _report_dir(tmp_path)
    assert (report_dir / "failure_traceback.txt").is_file()
    assert (report_dir / "screenshots" / "failure.png").is_file()
    assert (report_dir / "events.jsonl").is_file()
    assert (report_dir / "action_ledger.json").is_file()
    assert (report_dir / "assertion_ledger.json").is_file()
    assert report["metrics"]["workflow"]["values"]["action_results"][-1][
        "action_id"
    ] == "scenario.teardown"
    validate_report_v1(report)
