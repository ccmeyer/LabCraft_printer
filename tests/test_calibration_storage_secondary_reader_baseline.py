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
from tools.virtual_workflows.compare import build_report_set
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
    report["workload"]["timeout_seconds"] = 3600.0
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
    result["runs"]["warmup_count"] = 0
    result["runs"]["warmups"] = []
    return result


def test_secondary_baseline_preserves_integrity_and_candidate_limits():
    prior = _prior()
    reports = [_report("measured-1", 0.01, prior)]
    baseline = create_secondary_reader_baseline(
        _report_set(reports), reports, prior,
        report_set_sha256="9" * 64,
        milestone4a_baseline_sha256="8" * 64,
    )
    assert baseline["baseline_id"] == BASELINE_ID
    assert baseline["classification"]["status"] == "pass"
    assert baseline["milestone3_comparison"]["decision"] == "pass"
    assert baseline["secondary_integrity"]["memory_usable_run_count"] == 200
    assert baseline["secondary_metrics"]["export_latency_ms"]["candidate_limit"][
        "upper_limit"
    ] == pytest.approx(1.01)


def test_secondary_baseline_rejects_consumer_integrity_drift():
    prior = _prior()
    reports = [_report("measured-1", 0.01, prior)]
    reports[0]["metrics"]["persistence"]["values"]["calibration_storage"][
        "secondary_consumer_metrics"
    ]["consumer_error_count"] = 1
    with pytest.raises(CalibrationStorageBaselineError, match="integrity"):
        create_secondary_reader_baseline(
            _report_set(reports), reports, prior,
            report_set_sha256="9" * 64,
            milestone4a_baseline_sha256="8" * 64,
        )


def test_secondary_baseline_carries_forward_milestone3_peak_rss_gate():
    prior = _prior()
    reports = [_report("measured-1", 0.01, prior)]
    reports[0]["metrics"]["resources"]["values"]["peak_rss_bytes"] = (
        prior["milestone3_comparison"]["metrics"]["peak_rss_bytes"][
            "milestone3_upper_limit"
        ]
        + 1
    )
    baseline = create_secondary_reader_baseline(
        _report_set(reports), reports, prior,
        report_set_sha256="9" * 64,
        milestone4a_baseline_sha256="8" * 64,
    )
    assert baseline["milestone3_comparison"]["decision"] == "regression"
    assert baseline["classification"]["status"] == "fail"


def test_secondary_baseline_freezes_expanded_scope_rss_growth():
    prior = _prior()
    reports = [_report("measured-1", 0.01, prior)]
    reports[0]["metrics"]["resources"]["values"]["rss_growth_bytes"] = 42_000_000
    baseline = create_secondary_reader_baseline(
        _report_set(reports), reports, prior,
        report_set_sha256="9" * 64,
        milestone4a_baseline_sha256="8" * 64,
    )
    assert baseline["classification"]["status"] == "pass"
    assert baseline["resource_metrics"]["rss_growth_bytes"]["per_run"][0][
        "value"
    ] == 42_000_000


def test_secondary_workload_builds_storage_profile_report_set(tmp_path):
    prior = _prior()
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(_report("measured-1", 0.01, prior)), encoding="utf-8"
    )
    report_set = build_report_set(
        [report_path], host_label="pi5-calibration-storage-secondary-reader-v1"
    )
    assert report_set["metric_profile"] == "calibration_storage_reference_v1"
    assert report_set["runs"]["measured_count"] == 1
