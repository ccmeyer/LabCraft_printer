from __future__ import annotations

import json

import pytest

from tools.virtual_workflows.calibration_storage_journeys import (
    FUNCTIONAL_ASSERTIONS,
    FUNCTIONAL_ID,
    FUNCTIONAL_UI_ACTIONS,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1


@pytest.mark.sil_lifecycle
def test_calibration_storage_contract_full_lifecycle(qapp, tmp_path):
    report = run_registered_scenario(
        FUNCTIONAL_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=300.0,
        run_id="calibration-storage-contract-success",
        seed=1,
    )
    validate_report_v1(report)

    assert report["classification"]["status"] == "pass", json.dumps(
        report["classification"], indent=2
    )
    assert not any(report["safety"]["hardware_interfaces"].values())
    workflow = report["metrics"]["workflow"]["values"]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert decisions == {assertion_id: "pass" for assertion_id in FUNCTIONAL_ASSERTIONS}
    surfaces = {
        row["action_id"]: row["interaction_surface"]
        for row in workflow["action_results"]
        if row["action_id"] in FUNCTIONAL_UI_ACTIONS
    }
    assert surfaces == {action_id: "ui" for action_id in FUNCTIONAL_UI_ACTIONS}

    storage = report["metrics"]["persistence"]["values"]["calibration_storage"]
    assert storage["process_count"] == 16
    assert storage["successful_processes"] == 14
    assert storage["error_processes"] == 1
    assert storage["stopped_processes"] == 1
    assert storage["capture_counts"] == {
        "full-proxy": 4,
        "key-evidence-proxy": 2,
        "recorder-disabled-control": 0,
        "structured-only-proxy": 0,
    }
    fresh = storage["fresh_application"]
    assert fresh["applied"]["matches_source"] is True
    assert fresh["applied"]["settings_only_commands"] is True
    assert fresh["applied"]["no_dispense_or_motion"] is True
