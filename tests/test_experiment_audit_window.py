import json
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import Qt

import View
from ExperimentAuditReader import ExperimentAuditReader
from View import AuditTimelineTableModel, AuditTimelineWindow, MainWindow


def _event(event_type, summary, *, level="info", elapsed_s=0.0, details=None, context=None):
    return {
        "schema_version": 1,
        "event_id": f"id-{event_type}",
        "timestamp_utc": "2026-05-25T12:34:56Z",
        "elapsed_s": elapsed_s,
        "event_type": event_type,
        "level": level,
        "summary": summary,
        "details": details or {},
        "context": context or {},
    }


def _write_jsonl(path, events):
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


def _model_for_experiment_dir(path):
    return SimpleNamespace(experiment_model=SimpleNamespace(experiment_dir_path=str(path)))


def test_audit_timeline_table_model_exposes_stable_headers_and_data(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    _write_jsonl(
        audit_path,
        [
            _event(
                "experiment_loaded",
                "Loaded experiment",
                elapsed_s=1.25,
                details={"reaction_count": 3},
                context={"experiment_dir_path": str(tmp_path)},
            )
        ],
    )
    rows = ExperimentAuditReader(audit_path=audit_path).read_rows()

    model = AuditTimelineTableModel(rows=rows)

    assert model.rowCount() == 1
    assert model.columnCount() == 6
    assert [
        model.headerData(col, Qt.Horizontal, Qt.DisplayRole)
        for col in range(model.columnCount())
    ] == ["Time", "Elapsed", "Level", "Type", "Summary", "Line"]
    assert model.data(model.index(0, model.column_index("time_display")), Qt.DisplayRole) == "2026-05-25 12:34:56 UTC"
    assert model.data(model.index(0, model.column_index("elapsed_display")), Qt.DisplayRole) == "00:00:01.250"
    assert model.data(model.index(0, model.column_index("level")), Qt.DisplayRole) == "info"
    assert model.data(model.index(0, model.column_index("event_type")), Qt.DisplayRole) == "experiment_loaded"
    assert model.data(model.index(0, model.column_index("summary")), Qt.DisplayRole) == "Loaded experiment"
    assert model.data(model.index(0, model.column_index("line_number")), Qt.DisplayRole) == "1"


def test_audit_timeline_window_renders_valid_rows_and_details(qapp, tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    _write_jsonl(
        audit_path,
        [
            _event(
                "print_array_started",
                "Started stock 1 print array",
                elapsed_s=2.0,
                details={"stock_id": "stock-1"},
                context={"operator": "tester"},
            )
        ],
    )

    window = AuditTimelineWindow(model=_model_for_experiment_dir(tmp_path))

    assert window.table_model.rowCount() == 1
    assert "1 event" in window.status_label.text()
    assert "stock-1" in window.details_text.toPlainText()
    assert "tester" in window.details_text.toPlainText()


def test_audit_timeline_window_handles_missing_and_empty_audit_files(qapp, tmp_path):
    window = AuditTimelineWindow(model=_model_for_experiment_dir(tmp_path))

    assert window.table_model.rowCount() == 0
    assert window.details_text.toPlainText() == ""
    assert "No audit events found" in window.status_label.text()

    (tmp_path / "experiment_audit.jsonl").write_text("", encoding="utf-8")
    window.refresh()

    assert window.table_model.rowCount() == 0
    assert "No audit events found" in window.status_label.text()


def test_audit_timeline_window_shows_malformed_line_diagnostics(qapp, tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    audit_path.write_text(
        json.dumps(_event("experiment_loaded", "Loaded")) + "\n"
        "{bad json\n",
        encoding="utf-8",
    )

    window = AuditTimelineWindow(model=_model_for_experiment_dir(tmp_path))

    assert window.table_model.rowCount() == 2
    malformed_row = window.table_model.row_at(1)
    assert malformed_row.event_type == "audit_parse_error"
    assert malformed_row.level == "warning"
    assert malformed_row.is_valid is False
    assert "bad json" in malformed_row.detail_json


def test_audit_timeline_window_selection_updates_details(qapp, tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    _write_jsonl(
        audit_path,
        [
            _event("experiment_loaded", "Loaded", details={"marker": "first"}),
            _event("print_array_completed", "Completed", elapsed_s=5.0, details={"marker": "second"}),
        ],
    )
    window = AuditTimelineWindow(model=_model_for_experiment_dir(tmp_path))

    window.table.selectRow(1)
    window._on_selection_changed()

    details = window.details_text.toPlainText()
    assert "second" in details
    assert "first" not in details


def test_audit_timeline_window_refresh_reloads_appended_events_without_mutating_file(qapp, tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    first = _event("experiment_loaded", "Loaded")
    second = _event("calibration_session_started", "Calibration started", elapsed_s=3.0)
    _write_jsonl(audit_path, [first])
    window = AuditTimelineWindow(model=_model_for_experiment_dir(tmp_path))
    assert window.table_model.rowCount() == 1

    before = audit_path.read_text(encoding="utf-8")
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(second) + "\n")
    expected_after_append = audit_path.read_text(encoding="utf-8")

    window.refresh()

    assert window.table_model.rowCount() == 2
    assert audit_path.read_text(encoding="utf-8") == expected_after_append
    assert expected_after_append.startswith(before)


def test_main_window_show_experiment_audit_creates_reuses_and_shows_window(monkeypatch):
    instances = []

    class FakeAuditTimelineWindow:
        def __init__(self, parent, model=None):
            self.parent = parent
            self.model = model
            self.refresh = Mock()
            self.show = Mock()
            self.raise_ = Mock()
            self.activateWindow = Mock()
            instances.append(self)

    monkeypatch.setattr(View, "AuditTimelineWindow", FakeAuditTimelineWindow)

    main_window = MainWindow.__new__(MainWindow)
    main_window.model = object()

    MainWindow.show_experiment_audit(main_window)
    MainWindow.show_experiment_audit(main_window)

    assert len(instances) == 1
    assert instances[0].parent is main_window
    assert instances[0].show.call_count == 2
    assert instances[0].raise_.call_count == 2
    assert instances[0].activateWindow.call_count == 2
    instances[0].refresh.assert_called_once_with()


def test_ctrl_shift_a_shortcut_opens_audit_timeline():
    shortcuts = {}

    class RecorderShortcutManager:
        def add_shortcut(self, key, _name, callback):
            shortcuts[key] = callback

    main_window = MainWindow.__new__(MainWindow)
    main_window.shortcut_manager = RecorderShortcutManager()
    main_window.controller = SimpleNamespace()
    main_window.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            step_size=1,
            increase_step_size=Mock(),
            decrease_step_size=Mock(),
        )
    )
    main_window.well_plate_widget = SimpleNamespace(start_print_array=Mock())
    main_window.show_experiment_audit = Mock()

    MainWindow.setup_shortcuts(main_window)
    shortcuts["Ctrl+Shift+A"]()

    main_window.show_experiment_audit.assert_called_once_with()
