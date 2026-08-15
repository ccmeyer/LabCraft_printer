from __future__ import annotations

import json

import pytest

from tools.virtual_workflows.calibration_storage_journeys import (
    AUTHORITATIVE_FUNCTIONAL_ID,
    FUNCTIONAL_ASSERTIONS,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1


@pytest.mark.sil_lifecycle
def test_calibration_storage_authoritative_contract(qapp, tmp_path):
    report = run_registered_scenario(
        AUTHORITATIVE_FUNCTIONAL_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=600.0,
        run_id="calibration-storage-authoritative-contract-success",
        seed=1,
    )
    validate_report_v1(report)
    assert report["classification"]["status"] == "pass", json.dumps(
        report["classification"], indent=2
    )
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in report["metrics"]["workflow"]["values"]["assertion_results"]
    }
    assert decisions == {
        assertion_id: "pass" for assertion_id in FUNCTIONAL_ASSERTIONS
    }
    storage = report["metrics"]["persistence"]["values"]["calibration_storage"]
    assert storage["authoritative_mode"] is True
    assert storage["canonical_store_enabled"] is True
    assert storage["capture_counts"] == {
        "structured-only-proxy": 0,
        "key-evidence-proxy": 2,
        "full-proxy": 4,
        "recorder-disabled-control": 0,
    }
    assert storage["canonical_result_count"] == 16
    assert storage["canonical_index_event_count"] == 16
    assert all(row["canonical_valid"] for row in storage["processes"])
    assert not any(report["safety"]["hardware_interfaces"].values())
