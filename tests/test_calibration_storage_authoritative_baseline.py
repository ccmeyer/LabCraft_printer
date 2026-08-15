from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.sil.calibration_storage_authoritative_baseline import (
    BASELINE_ID,
    EXPECTED_COUNTS,
    create_authoritative_baseline,
)
from tools.sil.calibration_storage_baseline import CalibrationStorageBaselineError
from tests.test_calibration_storage_shadow_baseline import (
    _shadow_report,
    _shadow_report_set,
)


SHADOW_BASELINE_PATH = (
    Path(__file__).resolve().parent
    / "performance"
    / "baselines"
    / "calibration_storage_shadow_pi5_v1.json"
)


def _shadow_baseline():
    return json.loads(SHADOW_BASELINE_PATH.read_text(encoding="utf-8"))


def _authoritative_report(run_id, value, shadow):
    report = _shadow_report(run_id, value, shadow)
    report["environment"] = copy.deepcopy(
        shadow["compatibility"]["environment"]
    )
    report["run"]["scenario_name"] = "calibration_storage_authoritative"
    report["workload"]["workload_id"] = (
        "calibration_storage_authoritative_8x25_v1"
    )
    storage = report["metrics"]["persistence"]["values"]["calibration_storage"]
    storage["authoritative_mode"] = True
    storage["integrity_failure_count"] = 0
    return report


def _authoritative_report_set(reports):
    report_set = _shadow_report_set(reports)
    report_set["host_label"] = "pi5-calibration-storage-authoritative-v1"
    report_set["compatibility"]["environment"] = copy.deepcopy(
        reports[0]["environment"]
    )
    report_set["compatibility"]["workload"] = copy.deepcopy(
        reports[0]["workload"]
    )
    return report_set


def test_authoritative_baseline_preserves_counts_and_compares_shadow():
    shadow = _shadow_baseline()
    reports = [
        _authoritative_report(f"measured-{index}", 0.01, shadow)
        for index in range(1, 4)
    ]
    baseline = create_authoritative_baseline(
        _authoritative_report_set(reports),
        reports,
        shadow,
        report_set_sha256="9" * 64,
        shadow_baseline_sha256="8" * 64,
    )
    assert baseline["baseline_id"] == BASELINE_ID
    assert baseline["classification"]["status"] == "pass"
    assert baseline["shadow_comparison"]["decision"] == "pass"
    assert baseline["exact_counts"] == {
        **EXPECTED_COUNTS,
        "key_evidence_probe_capture_count": 2,
    }
    assert baseline["metrics"]["index_latency"]["candidate_limit"][
        "upper_limit"
    ] == pytest.approx(1.01)


def test_authoritative_baseline_rejects_count_drift():
    shadow = _shadow_baseline()
    reports = [
        _authoritative_report(f"measured-{index}", 0.01, shadow)
        for index in range(1, 4)
    ]
    reports[0]["metrics"]["persistence"]["values"]["calibration_storage"][
        "canonical_index_event_count"
    ] = 199
    with pytest.raises(CalibrationStorageBaselineError, match="canonical_index"):
        create_authoritative_baseline(
            _authoritative_report_set(reports),
            reports,
            shadow,
            report_set_sha256="9" * 64,
            shadow_baseline_sha256="8" * 64,
        )
