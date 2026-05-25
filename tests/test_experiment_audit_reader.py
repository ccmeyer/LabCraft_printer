import json
from pathlib import Path
from types import SimpleNamespace

from ExperimentAuditReader import (
    ExperimentAuditReader,
    build_audit_tooltip,
    derive_audit_stock_solution,
    event_detail_json,
    format_audit_elapsed,
    format_audit_timestamp,
)


def _event(event_id, event_type, *, elapsed_s=0.0, summary=None):
    return {
        "schema_version": 1,
        "event_id": event_id,
        "timestamp_utc": "2026-05-24T12:34:56Z",
        "elapsed_s": elapsed_s,
        "event_type": event_type,
        "level": "info",
        "summary": summary or event_type.replace("_", " ").title(),
        "details": {"stock_id": "stock-a", "count": 2},
        "context": {"experiment_name": "Reader Test"},
    }


def _write_jsonl(path, rows):
    lines = []
    for row in rows:
        if isinstance(row, str):
            lines.append(row)
        else:
            lines.append(json.dumps(row, separators=(",", ":")))
    Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def test_reads_valid_jsonl_events_and_exposes_row_fields(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    event = _event("event-1", "experiment_loaded", elapsed_s=5.25)
    _write_jsonl(audit_path, [event])

    rows = ExperimentAuditReader(audit_path=audit_path).read_rows()

    assert len(rows) == 1
    row = rows[0]
    assert row.line_number == 1
    assert row.event == event
    assert row.is_valid is True
    assert row.level == "info"
    assert row.event_type == "experiment_loaded"
    assert row.summary == "Experiment Loaded"
    assert row.timestamp_utc == "2026-05-24T12:34:56Z"
    assert row.elapsed_s == 5.25
    assert row.time_display == "2026-05-24 12:34:56 UTC"
    assert row.elapsed_display == "00:00:05.250"
    assert row.stock_solution == "stock-a"
    assert len(row.tooltip_text.splitlines()) <= 10


def test_preserves_file_order_and_line_numbers(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    first = _event("event-1", "first_event")
    second = _event("event-2", "second_event")
    third = _event("event-3", "third_event")
    _write_jsonl(audit_path, [first, second, third])

    rows = ExperimentAuditReader(audit_path=audit_path).read_rows()

    assert [row.event_type for row in rows] == ["first_event", "second_event", "third_event"]
    assert [row.line_number for row in rows] == [1, 2, 3]


def test_formats_timestamps_and_elapsed_seconds():
    assert format_audit_timestamp("2026-05-24T12:34:56Z") == "2026-05-24 12:34:56 UTC"
    assert format_audit_timestamp("2026-05-24T05:34:56-07:00") == "2026-05-24 12:34:56 UTC"
    assert format_audit_timestamp("not-a-time") == "not-a-time"
    assert format_audit_timestamp(None) == ""

    assert format_audit_elapsed(0) == "00:00:00.000"
    assert format_audit_elapsed(65.25) == "00:01:05.250"
    assert format_audit_elapsed(3661.9996) == "01:01:02.000"
    assert format_audit_elapsed(None) == ""


def test_missing_audit_file_returns_empty_list(tmp_path):
    audit_path = tmp_path / "missing" / "experiment_audit.jsonl"

    assert ExperimentAuditReader(audit_path=audit_path).read_rows() == []
    assert not audit_path.exists()


def test_empty_audit_file_returns_empty_list(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    audit_path.write_text("", encoding="utf-8")

    assert ExperimentAuditReader(audit_path=audit_path).read_rows() == []


def test_missing_experiment_directory_returns_empty_list():
    model = SimpleNamespace(experiment_model=SimpleNamespace(experiment_dir_path=None))

    reader = ExperimentAuditReader(model=model)

    assert reader.get_audit_path() is None
    assert reader.read_rows() == []


def test_model_derived_path_reads_experiment_audit(tmp_path):
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    audit_path = experiment_dir / "experiment_audit.jsonl"
    _write_jsonl(audit_path, [_event("event-1", "experiment_loaded")])
    model = SimpleNamespace(experiment_model=SimpleNamespace(experiment_dir_path=str(experiment_dir)))

    reader = ExperimentAuditReader(model=model)

    assert reader.get_audit_path() == str(audit_path.resolve())
    assert [row.event_type for row in reader.read_rows()] == ["experiment_loaded"]


def test_malformed_lines_become_warning_rows_without_crashing(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    _write_jsonl(audit_path, ["{not json"])

    rows = ExperimentAuditReader(audit_path=audit_path).read_rows()

    assert len(rows) == 1
    row = rows[0]
    assert row.is_valid is False
    assert row.line_number == 1
    assert row.level == "warning"
    assert row.event_type == "audit_parse_error"
    assert row.summary == "Malformed audit line"
    assert "Expecting property name" in row.parse_error
    assert "raw_line" in row.detail_json
    assert "{not json" in row.detail_json


def test_valid_rows_before_and_after_malformed_lines_are_preserved(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    first = _event("event-1", "first_event")
    second = _event("event-2", "second_event")
    _write_jsonl(audit_path, [first, "{bad json", second])

    rows = ExperimentAuditReader(audit_path=audit_path).read_rows()

    assert [row.event_type for row in rows] == [
        "first_event",
        "audit_parse_error",
        "second_event",
    ]
    assert [row.is_valid for row in rows] == [True, False, True]
    assert [row.line_number for row in rows] == [1, 2, 3]


def test_detail_json_includes_structured_details_and_context(tmp_path):
    event = _event("event-1", "print_array_started")

    detail = event_detail_json(event)

    assert '"details"' in detail
    assert '"context"' in detail
    assert '"stock_id": "stock-a"' in detail
    assert '"experiment_name": "Reader Test"' in detail


def test_read_table_returns_stable_table_dictionaries(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    _write_jsonl(audit_path, [_event("event-1", "experiment_loaded", elapsed_s=2.0)])

    table = ExperimentAuditReader(audit_path=audit_path).read_table()

    assert table == [
        {
            "time": "2026-05-24 12:34:56 UTC",
            "elapsed": "00:00:02.000",
            "level": "info",
            "stock_solution": "stock-a",
            "event_type": "experiment_loaded",
            "summary": "Experiment Loaded",
            "line_number": 1,
            "detail_json": table[0]["detail_json"],
            "is_valid": True,
        }
    ]
    assert set(table[0]) == {
        "time",
        "elapsed",
        "level",
        "stock_solution",
        "event_type",
        "summary",
        "line_number",
        "detail_json",
        "is_valid",
    }


def test_stock_solution_is_derived_from_common_audit_payload_shapes():
    assert derive_audit_stock_solution(
        {
            "details": {
                "stock_identity": {
                    "stock_solution": "Glycerol - 10 mM",
                    "stock_id": "glycerol-10",
                },
                "stock_solution": "Glycerol",
            }
        }
    ) == "Glycerol - 10 mM"
    assert derive_audit_stock_solution(
        {
            "details": {
                "stock_identity": {
                    "reagent_name": "Glycerol",
                    "display_concentration": "20",
                    "units": "mM",
                }
            }
        }
    ) == "Glycerol - 20 mM"
    assert derive_audit_stock_solution(
        {"details": {"stock_solution": "cal-stock"}}
    ) == "cal-stock"
    assert derive_audit_stock_solution(
        {"details": {"loaded_printer_head": {"stock_solution": "loaded-stock"}}}
    ) == "loaded-stock"
    assert derive_audit_stock_solution(
        {"details": {"loaded_printer_head": {"stock_id": "stock-id"}}}
    ) == "stock-id"
    assert derive_audit_stock_solution(
        {"details": {"stock_id": "reset-stock"}}
    ) == "reset-stock"
    assert derive_audit_stock_solution(
        {"details": {}, "context": {"stock_solution": "context-stock"}}
    ) == "context-stock"


def test_tooltip_is_compact_and_prioritizes_calibration_results():
    event = {
        "event_type": "calibration_process_completed",
        "level": "info",
        "summary": "Calibration completed",
        "details": {
            "stock_solution": "stock-a",
            "process_name": "PressureSweepCharacterizationProcess",
            "calibration_phase": "pressure_sweep_characterization",
            "outcome": "completed",
            "settings": {"print_width": 1450, "print_pressure": 1.35},
            "result_summary": {
                "volume_nL": 12.4,
                "cv_pct": 3.1,
                "print_pressure_psi": 1.35,
                "pulse_width_us": 1450,
                "replicate_count": 6,
                "latest_compact": {
                    "huge": "x" * 1000,
                },
            },
        },
    }

    tooltip = build_audit_tooltip(event, stock_solution="stock-a")

    assert len(tooltip.splitlines()) <= 10
    assert "Stock: stock-a" in tooltip
    assert "Ejection volume nL: 12.4" in tooltip
    assert "CV %: 3.1" in tooltip
    assert "Print pressure psi: 1.35" in tooltip
    assert "Pulse width us: 1450" in tooltip
    assert "x" * 100 not in tooltip


def test_reader_does_not_mutate_existing_audit_file(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    _write_jsonl(audit_path, [_event("event-1", "experiment_loaded"), "{bad json"])
    before = audit_path.read_bytes()

    ExperimentAuditReader(audit_path=audit_path).read_rows()

    assert audit_path.read_bytes() == before
