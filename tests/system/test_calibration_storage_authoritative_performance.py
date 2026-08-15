from __future__ import annotations

import json

import pytest

from tools.virtual_workflows.calibration_storage_journeys import (
    AUTHORITATIVE_PERFORMANCE_ID,
    PERFORMANCE_ASSERTIONS,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1


@pytest.mark.sil_stress
def test_calibration_storage_authoritative_8x25_workload(qapp, tmp_path):
    report = run_registered_scenario(
        AUTHORITATIVE_PERFORMANCE_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=1800.0,
        run_id="calibration-storage-authoritative-8x25-success",
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
        assertion_id: "pass" for assertion_id in PERFORMANCE_ASSERTIONS
    }
    storage = report["metrics"]["persistence"]["values"]["calibration_storage"]
    assert storage["authoritative_mode"] is True
    assert storage["process_run_count"] == 200
    assert storage["update_count"] == 232
    assert storage["canonical_update_count"] == 232
    assert storage["canonical_result_count"] == 200
    assert storage["canonical_index_event_count"] == 200
    assert storage["integrity_failure_count"] == 0
    assert storage["metrics"]["result_finalize_latency"]["count"] == 200
    assert storage["metrics"]["index_latency"]["count"] == 200
    assert storage["key_evidence_probe"]["capture_count"] == 2
    assert not any(report["safety"]["hardware_interfaces"].values())
