import json
from pathlib import Path

import pytest

from tools.virtual_workflows.journeys import (
    LEGACY_READ_ONLY_REQUIRED_ASSERTIONS,
    LEGACY_READ_ONLY_REQUIRED_SCREENSHOTS,
    LEGACY_READ_ONLY_REQUIRED_UI_ACTIONS,
    LEGACY_READ_ONLY_WORKLOAD_ID,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1


def test_legacy_read_only_fixture_contract_is_exact():
    path = (
        Path(__file__).parents[2]
        / "tools"
        / "virtual_workflows"
        / "fixtures"
        / "legacy_experiment_read_only_v1.json"
    )
    fixture = json.loads(path.read_text(encoding="utf-8"))

    assert fixture["fixture_id"] == LEGACY_READ_ONLY_WORKLOAD_ID
    assert fixture["expected_completed_wells"] == ["A1"]
    assert fixture["expected_partial_wells"] == ["A2"]
    assert fixture["progress"]["A1"]["completed"] is True
    assert fixture["progress"]["A2"]["completed"] is False


@pytest.mark.sil_lifecycle
def test_registered_legacy_read_only_report(qapp, tmp_path):
    report = run_registered_scenario(
        LEGACY_READ_ONLY_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="legacy-read-only-success",
        seed=7,
    )
    validate_report_v1(report)

    assert report["classification"]["status"] == "pass", json.dumps(
        report["classification"], indent=2
    )
    assert report["run"]["scenario_name"] == "legacy_experiment_read_only"
    assert not any(report["safety"]["hardware_interfaces"].values())
    workflow = report["metrics"]["workflow"]["values"]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert tuple(decisions) == LEGACY_READ_ONLY_REQUIRED_ASSERTIONS
    assert set(decisions.values()) == {"pass"}
    surfaces = {
        row["action_id"]: row["interaction_surface"]
        for row in workflow["action_results"]
        if row["action_id"] in LEGACY_READ_ONLY_REQUIRED_UI_ACTIONS
    }
    assert surfaces == {
        action_id: "ui" for action_id in LEGACY_READ_ONLY_REQUIRED_UI_ACTIONS
    }
    assert set(report["artifacts"]["screenshots"]) == (
        LEGACY_READ_ONLY_REQUIRED_SCREENSHOTS
    )
    editable_copy = workflow["editable_copy"]
    assert editable_copy["direct_read_only_launch"] is True
    assert editable_copy["saved_progress_prompt_absent"] is True
    assert editable_copy["source_opened_read_only"] is True
    assert editable_copy["copy_button_clicked"] is True
    assert editable_copy["name_dialog_handled"] is True
    assert editable_copy["controls_editable"] is True
    assert editable_copy["progress_empty"] is True
    assert editable_copy["no_execution_plan"] is True
    assert report["metrics"]["persistence"]["values"]["source_unchanged"] is True
