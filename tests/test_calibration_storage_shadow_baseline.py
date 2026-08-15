from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.sil.calibration_storage_baseline import CalibrationStorageBaselineError
from tools.sil.calibration_storage_shadow_baseline import (
    BASELINE_ID,
    EXPECTED_COUNTS,
    create_shadow_baseline,
)
from tests.test_calibration_storage_baseline import _report, _report_set


LEGACY_BASELINE_PATH = (
    Path(__file__).resolve().parent
    / "performance"
    / "baselines"
    / "calibration_storage_legacy_pi5_v1.json"
)


def _legacy_baseline() -> dict:
    return json.loads(LEGACY_BASELINE_PATH.read_text(encoding="utf-8"))


def _shadow_report(run_id: str, value: float, legacy: dict) -> dict:
    report = _report(run_id, value)
    report["run"]["scenario_name"] = "calibration_storage_shadow"
    report["environment"]["target_pi"] = copy.deepcopy(
        legacy["compatibility"]["environment"]["target_pi"]
    )
    report["workload"]["workload_id"] = "calibration_storage_shadow_8x25_v1"
    report["workload"]["fixture_sha256"] = legacy["compatibility"]["workload"][
        "fixture_sha256"
    ]
    report["workload"]["workload_hash"] = legacy["compatibility"]["workload"][
        "workload_hash"
    ]
    storage = report["metrics"]["persistence"]["values"]["calibration_storage"]
    storage.update(
        {
            "canonical_update_count": 232,
            "canonical_result_count": 200,
            "canonical_index_event_count": 200,
        }
    )
    for name in (
        "canonical_update_append_latency_ms",
        "result_finalize_latency",
        "index_latency",
    ):
        storage["metrics"][name] = {
            "count": 3,
            "minimum": value * 0.8,
            "median": value * 0.9,
            "p95": value,
            "maximum": value * 1.1,
        }
    storage["artifact_growth"]["inventory"] = {}
    return report


def _shadow_report_set(reports: list[dict]) -> dict:
    report_set = _report_set(reports)
    report_set["host_label"] = "pi5-calibration-storage-shadow-v1"
    report_set["compatibility"]["environment"] = copy.deepcopy(
        reports[0]["environment"]
    )
    report_set["compatibility"]["workload"] = copy.deepcopy(reports[0]["workload"])
    return report_set


def test_shadow_baseline_preserves_counts_and_freezes_new_timing_limits():
    legacy = _legacy_baseline()
    reports = [
        _shadow_report(f"measured-{index}", value, legacy)
        for index, value in enumerate((1.0, 1.2, 2.0), start=1)
    ]

    baseline = create_shadow_baseline(
        _shadow_report_set(reports),
        reports,
        legacy,
        report_set_sha256="9" * 64,
        legacy_baseline_sha256="8" * 64,
    )

    assert baseline["baseline_id"] == BASELINE_ID
    assert baseline["classification"] == {
        "status": "pass",
        "threshold_maturity": "candidate",
    }
    assert baseline["exact_counts"] == {
        **EXPECTED_COUNTS,
        "key_evidence_probe_capture_count": 2,
    }
    assert baseline["legacy_comparison"]["decision"] == "pass"
    assert baseline["new_metrics"]["index_latency"]["candidate_limit"][
        "upper_limit"
    ] == pytest.approx(3.2)


def test_shadow_baseline_rejects_count_drift():
    legacy = _legacy_baseline()
    reports = [
        _shadow_report(f"measured-{index}", 1.0, legacy)
        for index in range(1, 4)
    ]
    reports[1]["metrics"]["persistence"]["values"]["calibration_storage"][
        "canonical_result_count"
    ] = 199

    with pytest.raises(CalibrationStorageBaselineError, match="canonical_result_count"):
        create_shadow_baseline(
            _shadow_report_set(reports),
            reports,
            legacy,
            report_set_sha256="9" * 64,
            legacy_baseline_sha256="8" * 64,
        )


def test_shadow_baseline_classifies_legacy_metric_regression():
    legacy = _legacy_baseline()
    reports = [
        _shadow_report(f"measured-{index}", 1.0, legacy)
        for index in range(1, 4)
    ]
    for report in reports:
        report["metrics"]["persistence"]["values"]["calibration_storage"][
            "metrics"
        ]["history_load_latency_ms"]["p95"] = 10_000.0

    baseline = create_shadow_baseline(
        _shadow_report_set(reports),
        reports,
        legacy,
        report_set_sha256="9" * 64,
        legacy_baseline_sha256="8" * 64,
    )

    assert baseline["classification"]["status"] == "fail"
    assert baseline["legacy_comparison"]["metrics"]["history_load_latency_ms"][
        "decision"
    ] == "regression"
