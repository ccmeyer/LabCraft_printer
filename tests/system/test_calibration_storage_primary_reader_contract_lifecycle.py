from __future__ import annotations

import json

import pytest

from tools.virtual_workflows.calibration_storage_journeys import (
    FUNCTIONAL_ASSERTIONS,
    PRIMARY_READER_FUNCTIONAL_ID,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1


@pytest.mark.sil_lifecycle
def test_calibration_storage_primary_reader_contract(qapp, tmp_path):
    report = run_registered_scenario(
        PRIMARY_READER_FUNCTIONAL_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=600.0,
        run_id="calibration-storage-primary-reader-contract-success",
        seed=1,
    )
    validate_report_v1(report)
    assert report["classification"]["status"] == "pass", json.dumps(report["classification"], indent=2)
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in report["metrics"]["workflow"]["values"]["assertion_results"]
    }
    assert decisions == {assertion_id: "pass" for assertion_id in FUNCTIONAL_ASSERTIONS}
    storage = report["metrics"]["persistence"]["values"]["calibration_storage"]
    fresh = storage["fresh_application"]
    assert fresh["selected"]["result_id"]
    assert fresh["selected"]["update_id"]
    assert fresh["applied"]["record"]["result_id"] == fresh["selected"]["result_id"]
    assert fresh["applied"]["record"]["update_id"] == fresh["selected"]["update_id"]
    assert not any(report["safety"]["hardware_interfaces"].values())

