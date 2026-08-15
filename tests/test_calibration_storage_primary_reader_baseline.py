from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.sil.calibration_storage_baseline import CalibrationStorageBaselineError
from tools.sil.calibration_storage_primary_reader_baseline import (
    BASELINE_ID,
    EXPECTED_COUNTS,
    create_primary_reader_baseline,
)
from tests.test_calibration_storage_authoritative_baseline import (
    _authoritative_report,
    _authoritative_report_set,
    _shadow_baseline,
)


M3_BASELINE_PATH = (
    Path(__file__).resolve().parent
    / "performance"
    / "baselines"
    / "calibration_storage_authoritative_pi5_v1.json"
)


def _prior():
    return json.loads(M3_BASELINE_PATH.read_text(encoding="utf-8"))


def _report(run_id, value, prior):
    report = _authoritative_report(run_id, value, _shadow_baseline())
    report["environment"] = copy.deepcopy(prior["compatibility"]["environment"])
    report["run"]["scenario_name"] = "calibration_storage_primary_reader"
    report["workload"]["workload_id"] = "calibration_storage_primary_reader_8x25_v1"
    storage = report["metrics"]["persistence"]["values"]["calibration_storage"]
    distribution = {"count": 8, "minimum": value, "median": value, "p95": value, "maximum": value, "samples": [value] * 8}
    storage["reader_metrics"] = {
        "summary_materialization_latency_ms": dict(distribution),
        "selected_validation_latency_ms": dict(distribution),
        "recheck_context_latency_ms": dict(distribution),
        "diagnostics": {"routine_result_bundle_reads": 0, "routine_recursive_scans": 0},
    }
    return report


def _report_set(reports):
    value = _authoritative_report_set(reports)
    value["host_label"] = "pi5-calibration-storage-primary-reader-v1"
    value["compatibility"]["workload"] = copy.deepcopy(reports[0]["workload"])
    return value


def test_primary_reader_baseline_preserves_counts_and_reader_limits():
    prior = _prior()
    reports = [_report(f"measured-{index}", 0.01, prior) for index in range(1, 4)]
    baseline = create_primary_reader_baseline(
        _report_set(reports), reports, prior,
        report_set_sha256="9" * 64,
        milestone3_baseline_sha256="8" * 64,
    )
    assert baseline["baseline_id"] == BASELINE_ID
    assert baseline["exact_counts"] == {**EXPECTED_COUNTS, "key_evidence_probe_capture_count": 2}
    assert baseline["classification"]["status"] == "pass"
    assert baseline["reader_metrics"]["summary_materialization_latency_ms"]["candidate_limit"]["upper_limit"] == pytest.approx(1.01)


def test_primary_reader_baseline_rejects_unbounded_history_io():
    prior = _prior()
    reports = [_report(f"measured-{index}", 0.01, prior) for index in range(1, 4)]
    reports[0]["metrics"]["persistence"]["values"]["calibration_storage"]["reader_metrics"]["diagnostics"]["routine_result_bundle_reads"] = 1
    with pytest.raises(CalibrationStorageBaselineError, match="unbounded"):
        create_primary_reader_baseline(
            _report_set(reports), reports, prior,
            report_set_sha256="9" * 64,
            milestone3_baseline_sha256="8" * 64,
        )
