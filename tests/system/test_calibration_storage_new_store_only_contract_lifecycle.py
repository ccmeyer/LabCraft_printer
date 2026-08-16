from __future__ import annotations

import json

import pytest

from tools.virtual_workflows.calibration_storage_journeys import (
    NEW_STORE_ONLY_ASSERTIONS,
    NEW_STORE_ONLY_FUNCTIONAL_ID,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1


@pytest.mark.sil_lifecycle
def test_calibration_storage_new_store_only_contract(qapp, tmp_path):
    report = run_registered_scenario(
        NEW_STORE_ONLY_FUNCTIONAL_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=180.0,
        run_id="calibration-storage-new-store-only-contract-success",
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
        assertion_id: "pass" for assertion_id in NEW_STORE_ONLY_ASSERTIONS
    }
    storage = report["metrics"]["persistence"]["values"]["calibration_storage"]
    writer = storage["legacy_writer"]
    assert writer["declared_mode"] == "canonical_only"
    assert writer["effective_enabled"] is False
    assert writer["write_count"] == 0
    assert writer["suppressed_write_count"] == 0
    assert writer["legacy_writer_available"] is False
    assert writer["effective_reason"] == "writer_retired"
    assert storage["calibration_sha256"] is None
    assert storage["legacy_writer_canaries"]["exact"] is True
    assert not any(report["safety"]["hardware_interfaces"].values())
