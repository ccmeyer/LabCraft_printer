from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.sil.calibration_storage_baseline import CalibrationStorageBaselineError
from tools.sil.calibration_storage_secondary_reader_baseline import (
    BASELINE_ID,
    SECONDARY_METRICS,
    create_secondary_reader_baseline,
)
from tests.test_calibration_storage_primary_reader_baseline import (
    _report as _primary_report,
    _report_set as _primary_report_set,
)


M4A_PATH = (
    Path(__file__).resolve().parent
    / "performance"
    / "baselines"
    / "calibration_storage_primary_reader_pi5_v1.json"
)


def _prior():
    return json.loads(M4A_PATH.read_text(encoding="utf-8"))


def _report(run_id, value, prior):
    report = _primary_report(run_id, value, prior)
    report["run"]["scenario_name"] = "calibration_storage_secondary_reader"
    report["workload"]["workload_id"] = (
        "calibration_storage_secondary_reader_8x25_v1"
    )
    storage = report["metrics"]["persistence"]["values"]["calibration_storage"]
    dist = {
        "count": 1,
        "minimum": value,
        "median": value,
        "p95": value,
        "maximum": value,
        "samples": [value],
    }
    storage["secondary_consumer_metrics"] = {
        **{name: dict(dist) for name in SECONDARY_METRICS},
        "memory_usable_run_count": 200,
        "summary_row_count": 200,
        "consumer_error_count": 0,
        "legacy_hash_preserved": True,
        "tool_reader_state": "matching_dual",
    }
    return report


def _report_set(reports):
    result = _primary_report_set(reports)
    result["host_label"] = "pi5-calibration-storage-secondary-reader-v1"
    result["compatibility"]["workload"] = copy.deepcopy(reports[0]["workload"])
    return result


def test_secondary_baseline_preserves_integrity_and_candidate_limits():
    prior = _prior()
    reports = [_report(f"measured-{index}", 0.01, prior) for index in range(1, 4)]
    baseline = create_secondary_reader_baseline(
        _report_set(reports), reports, prior,
        report_set_sha256="9" * 64,
        milestone4a_baseline_sha256="8" * 64,
    )
    assert baseline["baseline_id"] == BASELINE_ID
    assert baseline["classification"]["status"] == "pass"
    assert baseline["secondary_integrity"]["memory_usable_run_count"] == 200
    assert baseline["secondary_metrics"]["export_latency_ms"]["candidate_limit"][
        "upper_limit"
    ] == pytest.approx(1.01)


def test_secondary_baseline_rejects_consumer_integrity_drift():
    prior = _prior()
    reports = [_report(f"measured-{index}", 0.01, prior) for index in range(1, 4)]
    reports[0]["metrics"]["persistence"]["values"]["calibration_storage"][
        "secondary_consumer_metrics"
    ]["consumer_error_count"] = 1
    with pytest.raises(CalibrationStorageBaselineError, match="integrity"):
        create_secondary_reader_baseline(
            _report_set(reports), reports, prior,
            report_set_sha256="9" * 64,
            milestone4a_baseline_sha256="8" * 64,
        )
