from __future__ import annotations

import json

import pytest

from tools.virtual_workflows.calibration_storage_journeys import (
    PERFORMANCE_ASSERTIONS,
    PERFORMANCE_ID,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1


@pytest.mark.sil_stress
def test_calibration_storage_legacy_8x25_workload(qapp, tmp_path):
    report = run_registered_scenario(
        PERFORMANCE_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=1800.0,
        run_id="calibration-storage-legacy-8x25-success",
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
    assert decisions == {assertion_id: "pass" for assertion_id in PERFORMANCE_ASSERTIONS}

    storage = report["metrics"]["persistence"]["values"]["calibration_storage"]
    assert {
        key: storage[key]
        for key in (
            "process_run_count",
            "legacy_run_envelope_count",
            "update_count",
            "recording_count",
            "workload_capture_count",
        )
    } == {
        "process_run_count": 200,
        "legacy_run_envelope_count": 201,
        "update_count": 232,
        "recording_count": 200,
        "workload_capture_count": 0,
    }
    assert storage["key_evidence_probe"]["capture_count"] == 2
    assert storage["metrics"]["result_finalize_latency"] == {
        "samples": [],
        "status": "not_available_until_m2",
    }
    assert storage["metrics"]["index_latency"] == {
        "samples": [],
        "status": "not_available_until_m2",
    }

