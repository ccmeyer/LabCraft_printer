from __future__ import annotations

import csv
import json
from pathlib import Path

from tools import export_calibration_recording_summary as mod


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _make_run(
    exp_dir: Path,
    *,
    process_name: str = "NozzlePositionCalibrationProcess",
    run_id: str = "run_20260424_120000_deadbeef",
    phase_name: str = "nozzle_position",
    started_at_utc: str = "2026-04-24T12:00:00Z",
    meta_outcome: str = "completed",
    meta_error_message: str = "",
    verdict_outcome: str = "success",
    failure_summary: str = "",
    events: list[dict] | None = None,
    analysis_rows: list[dict] | None = None,
    extra_jsonl: dict[str, list[dict]] | None = None,
    omit_verdict: bool = False,
):
    run_dir = exp_dir / "calibration_recordings" / process_name / run_id
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "run_meta.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "process_name": process_name,
            "phase_name": phase_name,
            "started_at_utc": started_at_utc,
            "ended_at_utc": "2026-04-24T12:01:00Z",
            "outcome": meta_outcome,
            "error_message": meta_error_message,
            "recorder_warning_count": 0,
            "recorder_warnings": [],
            "capture_write_failure_count": 0,
            "capture_write_failures": [],
        },
    )
    if not omit_verdict:
        _write_json(
            run_dir / "verdict.json",
            {
                "schema_version": 1,
                "run_id": run_id,
                "process_name": process_name,
                "phase_name": phase_name,
                "outcome": verdict_outcome,
                "failure_summary": failure_summary,
                "suspected_cause": "",
                "notes": "",
            },
        )
    _write_jsonl(run_dir / "events.jsonl", events or [])
    _write_jsonl(run_dir / "analysis.jsonl", analysis_rows or [])
    for filename, rows in (extra_jsonl or {}).items():
        _write_jsonl(run_dir / filename, rows)
    return run_dir


def _read_csv_rows(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def test_success_verdict_completed_metadata_exports_ok(tmp_path):
    exp_dir = tmp_path / "ExperimentA"
    _make_run(exp_dir)

    rows, stats = mod.build_calibration_recording_summary_rows(exp_dir)

    assert stats["row_count"] == 1
    assert stats["needs_review_count"] == 0
    row = rows[0]
    assert row["run_id"] == "run_20260424_120000_deadbeef"
    assert row["meta_outcome"] == "completed"
    assert row["verdict"] == "success"
    assert row["review_status"] == "ok"
    assert row["review_reasons"] == ""
    assert row["tool_error_count"] == 0


def test_unknown_verdict_is_flagged_for_review(tmp_path):
    exp_dir = tmp_path / "ExperimentA"
    _make_run(exp_dir, verdict_outcome="unknown")

    rows, stats = mod.build_calibration_recording_summary_rows(exp_dir)

    assert stats["needs_review_count"] == 1
    assert rows[0]["review_status"] == "needs_review"
    assert rows[0]["verdict"] == "unknown"
    assert "verdict_unknown" in rows[0]["review_reasons"]


def test_failed_verdict_exports_failure_summary(tmp_path):
    exp_dir = tmp_path / "ExperimentA"
    _make_run(
        exp_dir,
        verdict_outcome="failed",
        failure_summary="No droplet detected during emergence scan",
    )

    rows, _stats = mod.build_calibration_recording_summary_rows(exp_dir)

    row = rows[0]
    assert row["review_status"] == "needs_review"
    assert row["verdict"] == "failed"
    assert "verdict_failed" in row["review_reasons"]
    assert "No droplet detected during emergence scan" in row["error_messages"]


def test_event_and_analysis_problems_are_counted(tmp_path):
    exp_dir = tmp_path / "ExperimentA"
    _make_run(
        exp_dir,
        events=[
            {
                "level": "error",
                "event_type": "error",
                "payload": {"error_message": "move timed out", "reason": "timeout"},
            },
            {
                "level": "warning",
                "event_type": "capture_save_failed",
                "payload": {"message": "overlay write failed"},
            },
        ],
        analysis_rows=[
            {
                "kind": "focus_fit",
                "status": "failed",
                "failure_reason": "not enough valid samples",
            }
        ],
        extra_jsonl={
            "frames.jsonl": [
                {
                    "phase": "flow_rate",
                    "status": "accepted",
                    "flow_measurement_usable": False,
                }
            ]
        },
    )

    rows, stats = mod.build_calibration_recording_summary_rows(exp_dir)

    row = rows[0]
    assert stats["needs_review_count"] == 1
    assert row["review_status"] == "needs_review"
    assert row["event_error_count"] == 1
    assert row["event_warning_count"] == 1
    assert row["analysis_problem_count"] == 2
    assert "event_errors" in row["review_reasons"]
    assert "event_warnings" in row["review_reasons"]
    assert "analysis_problems" in row["review_reasons"]
    assert "move timed out" in row["error_messages"]
    assert "overlay write failed" in row["error_messages"]
    assert "not enough valid samples" in row["error_messages"]
    assert "flow_measurement_usable=false" in row["error_messages"]


def test_missing_and_malformed_files_become_tool_errors(tmp_path):
    exp_dir = tmp_path / "ExperimentA"
    run_dir = _make_run(exp_dir, omit_verdict=True)
    (run_dir / "analysis.jsonl").write_text('{"kind": "ok"}\nnot-json\n', encoding="utf-8")

    rows, stats = mod.build_calibration_recording_summary_rows(exp_dir)

    row = rows[0]
    assert row["verdict"] == "unknown"
    assert row["review_status"] == "needs_review"
    assert row["tool_error_count"] == 2
    assert stats["parse_error_count"] == 1
    assert stats["tool_error_count"] == 2
    assert "missing verdict.json" in row["error_messages"]
    assert "malformed analysis.jsonl:2" in row["error_messages"]
    assert "tool_errors" in row["review_reasons"]


def test_cli_writes_custom_output_and_sorts_deterministically(tmp_path, capsys):
    exp_dir = tmp_path / "ExperimentA"
    _make_run(
        exp_dir,
        process_name="OnlineStreamCalibrationProcess",
        run_id="run_b",
        phase_name="online_stream_calibration",
        started_at_utc="2026-04-24T12:02:00Z",
    )
    _make_run(
        exp_dir,
        process_name="HeadPrimeCalibrationProcess",
        run_id="run_a",
        phase_name="head_prime",
        started_at_utc="2026-04-24T12:01:00Z",
    )
    out_path = tmp_path / "exports" / "summary.csv"

    rc = mod.main([str(exp_dir), "--out", str(out_path)])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["output_path"] == str(out_path.resolve())
    assert payload["row_count"] == 2
    fieldnames, rows = _read_csv_rows(out_path)
    assert fieldnames == mod.SUMMARY_COLUMNS
    assert [row["run_id"] for row in rows] == ["run_a", "run_b"]


def test_recordings_root_can_scan_standalone_copy(tmp_path):
    root = tmp_path / "calibration_recordings"
    exp_dir = tmp_path / "ExperimentA"
    run_dir = _make_run(exp_dir)
    standalone_run = root / run_dir.parent.name / run_dir.name
    standalone_run.parent.mkdir(parents=True)
    standalone_run.mkdir()
    for path in run_dir.iterdir():
        if path.is_file():
            (standalone_run / path.name).write_bytes(path.read_bytes())

    result = mod.export_calibration_recording_summary(recordings_root=root)

    output = Path(result["output_path"])
    assert output == tmp_path / "calibration_recordings_summary.csv"
    _fieldnames, rows = _read_csv_rows(output)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run_20260424_120000_deadbeef"
