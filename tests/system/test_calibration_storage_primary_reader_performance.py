from __future__ import annotations

import json

import pytest

from tools.virtual_workflows.calibration_storage_journeys import (
    PERFORMANCE_ASSERTIONS,
    PRIMARY_READER_PERFORMANCE_ID,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1


@pytest.mark.sil_stress
def test_calibration_storage_primary_reader_8x25_workload(qapp, tmp_path):
    report = run_registered_scenario(
        PRIMARY_READER_PERFORMANCE_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=1800.0,
        run_id="calibration-storage-primary-reader-8x25-success",
        seed=1,
    )
    validate_report_v1(report)
    assert report["classification"]["status"] == "pass", json.dumps(report["classification"], indent=2)
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in report["metrics"]["workflow"]["values"]["assertion_results"]
    }
    assert decisions == {assertion_id: "pass" for assertion_id in PERFORMANCE_ASSERTIONS}
    storage = report["metrics"]["persistence"]["values"]["calibration_storage"]
    assert storage["process_run_count"] == 200
    assert storage["update_count"] == 232
    assert storage["canonical_result_count"] == 200
    assert storage["reader_metrics"]["summary_materialization_latency_ms"]["count"] == 8
    assert storage["reader_metrics"]["recheck_context_latency_ms"]["count"] == 8
    assert storage["reader_metrics"]["diagnostics"]["routine_result_bundle_reads"] == 0
    assert storage["reader_metrics"]["diagnostics"]["routine_recursive_scans"] == 0
    assert not any(report["safety"]["hardware_interfaces"].values())
