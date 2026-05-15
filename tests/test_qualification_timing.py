import json
from pathlib import Path

from QualificationReports import compact_report_time
from QualificationTiming import build_timing_model


def _report(
    *,
    manifest_id="factory_acceptance_v3",
    started_at="2026-05-15T00:00:00Z",
    result_times=None,
    aborted=False,
):
    result_times = result_times or [
        (2007, "2026-05-15T00:00:05Z"),
        (2201, "2026-05-15T00:00:15Z"),
    ]
    return {
        "schema_version": "qualification_report_v1",
        "manifest": {
            "manifest_id": manifest_id,
            "name": manifest_id,
            "profile": "FULL",
        },
        "started_at": started_at,
        "finished_at": result_times[-1][1] if result_times else started_at,
        "aborted": aborted,
        "results": [
            {
                "test_id": test_id,
                "name": f"test_{test_id}",
                "pass": True,
                "metrics": {},
                "timestamp": timestamp,
            }
            for test_id, timestamp in result_times
        ],
        "host_checks": [],
        "analysis": {"items": [], "metric_evaluations": []},
        "warnings": [],
        "overall_status": "pass",
    }


def _write_report(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_timing_model_uses_median_manifest_specific_durations(tmp_path):
    _write_report(tmp_path / "qualification" / "LC-TEST" / "run1" / "report.json", _report())
    _write_report(
        tmp_path / "qualification" / "LC-TEST" / "run2" / "report.json",
        _report(
            started_at="2026-05-15T01:00:00Z",
            result_times=[
                (2007, "2026-05-15T01:00:07Z"),
                (2201, "2026-05-15T01:00:22Z"),
            ],
        ),
    )

    model = build_timing_model(tmp_path)

    estimate_2007 = model.estimate_for("factory_acceptance_v3", 2007)
    estimate_2201 = model.estimate_for("factory_acceptance_v3", 2201)
    assert estimate_2007 is not None
    assert estimate_2007.typical_seconds == 6.0
    assert estimate_2007.sample_count == 2
    assert estimate_2201 is not None
    assert estimate_2201.typical_seconds == 12.5


def test_build_timing_model_skips_aborted_invalid_and_negative_reports(tmp_path):
    _write_report(
        tmp_path / "qualification" / "LC-TEST" / "good" / "report.json",
        _report(result_times=[(2007, "2026-05-15T00:00:05Z")]),
    )
    _write_report(
        tmp_path / "qualification" / "LC-TEST" / "aborted" / "report.json",
        _report(result_times=[(2007, "2026-05-15T00:10:00Z")], aborted=True),
    )
    _write_report(
        tmp_path / "qualification" / "LC-TEST" / "invalid" / "report.json",
        _report(started_at="not a timestamp", result_times=[(2007, "2026-05-15T00:10:00Z")]),
    )
    _write_report(
        tmp_path / "qualification" / "LC-TEST" / "negative" / "report.json",
        _report(started_at="2026-05-15T00:10:00Z", result_times=[(2007, "2026-05-15T00:00:05Z")]),
    )
    missing_timestamp = _report(result_times=[(2007, "2026-05-15T00:00:05Z")])
    del missing_timestamp["results"][0]["timestamp"]
    _write_report(tmp_path / "qualification" / "LC-TEST" / "missing_timestamp" / "report.json", missing_timestamp)

    model = build_timing_model(tmp_path)

    estimate = model.estimate_for("factory_acceptance_v3", 2007)
    assert estimate is not None
    assert estimate.typical_seconds == 5.0
    assert estimate.sample_count == 1


def test_timing_model_falls_back_to_test_id_when_manifest_has_no_history(tmp_path):
    _write_report(tmp_path / "qualification" / "LC-TEST" / "run1" / "report.json", _report())

    model = build_timing_model(tmp_path)

    estimate = model.estimate_for("new_manifest", 2007)
    assert estimate is not None
    assert estimate.typical_seconds == 5.0
    assert estimate.source == "test"


def test_compact_report_time_formats_iso_and_run_directory_timestamps():
    assert compact_report_time("2026-05-15T04:34:25.123456Z") == "2026-05-15 04:34:25"
    assert compact_report_time("", "20260515T043425Z") == "2026-05-15 04:34:25"
