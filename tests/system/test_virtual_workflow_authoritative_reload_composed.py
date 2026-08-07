from __future__ import annotations

from pathlib import Path

import pytest

from tools.virtual_workflows.harness import AutomationHarness
from tools.virtual_workflows.journeys import (
    AUTHORITATIVE_RELOAD_REQUIRED_ASSERTIONS,
    AUTHORITATIVE_RELOAD_WORKLOAD_ID,
    JourneyRunConfig,
    run_composed_journey,
)
from tools.virtual_workflows.page_drivers import ExperimentLoaderDriver
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    VirtualPrintArrayScenarioConfig,
    run_virtual_print_array_scenario,
)


EXPECTED_MILESTONES = [
    "session_1_ready",
    "session_1_printing",
    "session_1_stop_requested",
    "session_1_stopped",
    "session_2_loaded",
    "session_2_activated",
    "session_2_resumed",
    "completed",
]

EXPECTED_ACTIONS = [
    "app.launch_simulated",
    "machine.connect_via_ui",
    "machine.enable_motors_via_ui",
    "machine.home_via_ui",
    "editor.open_via_ui",
    "editor.new_experiment_via_ui",
    "editor.configure_design_via_ui",
    "editor.optimize_generate_via_ui",
    "editor.finish_via_ui",
    "machine.configure_print_settings_via_ui",
    "head.set_volume_via_ui",
    "head.stage_via_ui",
    "pressure.enable_regulation_via_ui",
    "calibration.open_via_ui",
    "calibration.generate_via_ui",
    "calibration.select_via_ui",
    "calibration.apply_via_ui",
    "artifact.capture_milestone",
    "array.start_via_ui",
    "artifact.capture_milestone",
    "array.request_soft_stop_via_ui",
    "artifact.capture_milestone",
    "array.wait_for_state",
    "artifact.capture_milestone",
    "array.observe_stopped_quiescence",
    "app.close_simulated_session",
    "app.launch_simulated",
    "experiment.load_authoritative_via_ui",
    "artifact.capture_milestone",
    "experiment.activate_authoritative_via_ui",
    "artifact.capture_milestone",
    "machine.connect_via_ui",
    "machine.enable_motors_via_ui",
    "machine.home_via_ui",
    "machine.configure_print_settings_via_ui",
    "head.set_volume_via_ui",
    "head.stage_via_ui",
    "pressure.enable_regulation_via_ui",
    "array.resume_via_ui",
    "artifact.capture_milestone",
    "array.wait_for_completions",
    "artifact.capture_milestone",
    "scenario.teardown",
]


def _run_composed(tmp_path: Path, run_id: str):
    return run_composed_journey(
        JourneyRunConfig(
            scenario_id=AUTHORITATIVE_RELOAD_WORKLOAD_ID,
            output_root=tmp_path,
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
            run_id=run_id,
        )
    )


def _decisions(report):
    return {
        row["assertion_id"]: row["decision"]
        for row in report["metrics"]["workflow"]["values"]["assertion_results"]
    }


@pytest.mark.sil_lifecycle
def test_authoritative_reload_composed_report_passes(qapp, tmp_path):
    report = _run_composed(tmp_path, "composed-success")
    validate_report_v1(report)
    assert report["classification"]["status"] == "pass"
    assert list(_decisions(report)) == list(AUTHORITATIVE_RELOAD_REQUIRED_ASSERTIONS)
    assert set(_decisions(report).values()) == {"pass"}

    workflow = report["metrics"]["workflow"]["values"]
    assert [row["action_id"] for row in workflow["action_results"]] == EXPECTED_ACTIONS
    assert [row["name"] for row in workflow["lifecycle_milestones"]] == (
        EXPECTED_MILESTONES
    )
    assert set(report["artifacts"]["screenshots"]) == set(EXPECTED_MILESTONES)
    sessions = workflow["application_sessions"]
    assert len(sessions) == 2
    assert len({row["application_session_id"] for row in sessions}) == 2
    assert {row["status"] for row in sessions} == {"completed"}
    assert {row["recorder"]["status"] for row in sessions} == {"closed"}

    persistence = report["metrics"]["persistence"]["values"][
        "authoritative_reload_resume"
    ]
    assert persistence["between_sessions"]["byte_identical"]
    assert persistence["session_2_loaded"]["checks"][
        "authoritative_files_byte_identical"
    ]
    assert persistence["session_2_activation"]["checks"][
        "partial_progress_rehydrated"
    ]
    assert persistence["resume_reconciliation"][
        "session_1_completed_pairs_not_replayed"
    ]
    assert persistence["terminal"]["completion_count"] == 24
    assert persistence["terminal"]["plan_state"] == "completed"
    assert set(persistence["terminal"]["checks"].values()) == {True}


@pytest.mark.sil_lifecycle
def test_authoritative_reload_composed_matches_direct_stable_oracle(qapp, tmp_path):
    direct = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            scenario_id=AUTHORITATIVE_RELOAD_WORKLOAD_ID,
            output_root=tmp_path / "direct",
            timeout_seconds=60,
            run_id="direct-parity",
        )
    )
    composed = _run_composed(tmp_path / "composed", "composed-parity")
    assert direct["classification"]["status"] == "pass"
    assert composed["classification"]["status"] == "pass"
    assert direct["workload"]["fixture_sha256"] == composed["workload"][
        "fixture_sha256"
    ]
    assert _decisions(direct) == _decisions(composed)
    direct_state = direct["metrics"]["persistence"]["values"][
        "authoritative_reload_resume"
    ]
    composed_state = composed["metrics"]["persistence"]["values"][
        "authoritative_reload_resume"
    ]
    for name in ("completion_count", "plan_state"):
        assert direct_state["terminal"][name] == composed_state["terminal"][name]
    assert direct_state["between_sessions"]["byte_identical"]
    assert composed_state["between_sessions"]["byte_identical"]
    assert direct_state["resume_reconciliation"][
        "session_1_completed_pairs_not_replayed"
    ]
    assert composed_state["resume_reconciliation"][
        "session_1_completed_pairs_not_replayed"
    ]


@pytest.mark.sil_lifecycle
def test_authoritative_reload_fails_closed_on_first_teardown_mutation(
    qapp, tmp_path, monkeypatch
):
    original = AutomationHarness.close_application_session

    def mutate_after_close(self):
        result = original(self)
        plan = next((self.scenario_root / "experiments").glob("*/execution_plan.json"))
        plan.write_bytes(plan.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(
        AutomationHarness, "close_application_session", mutate_after_close
    )
    report = _run_composed(tmp_path, "teardown-mutation")
    assert report["classification"]["status"] == "fail"
    decisions = _decisions(report)
    assert decisions["execution.first_session_paused"] == "pass"
    assert decisions["execution.first_session_teardown_clean"] == "fail"
    assert decisions["execution.authoritative_reload_valid"] == "incomplete"
    _assert_failure_artifacts(report)


@pytest.mark.sil_lifecycle
def test_authoritative_reload_fails_closed_on_disallowed_activation_write(
    qapp, tmp_path, monkeypatch
):
    original = ExperimentLoaderDriver.load_authoritative_execution

    def mutate_before_activation_check(
        self, experiment_dir, *, expected_name, before_activation, after_activation
    ):
        def mutate_then_validate():
            design = Path(experiment_dir) / "experiment_design.json"
            design.write_bytes(design.read_bytes() + b"\n")
            return after_activation()

        return original(
            self,
            experiment_dir,
            expected_name=expected_name,
            before_activation=before_activation,
            after_activation=mutate_then_validate,
        )

    monkeypatch.setattr(
        ExperimentLoaderDriver,
        "load_authoritative_execution",
        mutate_before_activation_check,
    )
    report = _run_composed(tmp_path, "activation-mutation")
    assert report["classification"]["status"] == "fail"
    decisions = _decisions(report)
    assert decisions["execution.first_session_teardown_clean"] == "pass"
    assert decisions["execution.authoritative_reload_valid"] == "incomplete"
    assert decisions["execution.authoritative_runtime_rehydrated"] == "incomplete"
    activation = next(
        row
        for row in report["metrics"]["workflow"]["values"]["action_results"]
        if row["action_id"] == "experiment.activate_authoritative_via_ui"
    )
    assert activation["status"] == "fail"
    _assert_failure_artifacts(report)


def _assert_failure_artifacts(report):
    report_dir = Path(report["safety"]["report_dir"])
    scenario_root = Path(report["safety"]["scenario_root"])
    for relative in (
        "failure_traceback.txt",
        "action_ledger.json",
        "assertion_ledger.json",
        "evidence_manifest.json",
        "screenshots/failure.png",
    ):
        assert (report_dir / relative).is_file()
    assert not (scenario_root / ".sil-session.lock").exists()
