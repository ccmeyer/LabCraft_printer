import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import View
from ExperimentAuditLog import ExperimentAuditLog
from ExperimentAuditReader import ExperimentAuditReader, build_audit_markdown
from View import AuditTimelineWindow


class _Clock:
    def __init__(self):
        self.current = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        value = self.current
        self.current = self.current + timedelta(seconds=1)
        return value


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _make_audit_model(tmp_path):
    model = SimpleNamespace()
    exp = SimpleNamespace(
        experiment_dir_path=str(tmp_path),
        experiment_file_path=str(tmp_path / "experiment_design.json"),
        progress_file_path=str(tmp_path / "progress.json"),
        calibration_file_path=str(tmp_path / "calibration.json"),
        metadata={"name": "Note Test"},
    )
    model.experiment_model = exp
    ids = iter(f"event-{idx}" for idx in range(1, 20))
    log = ExperimentAuditLog(model=model, clock=_Clock(), uuid_factory=lambda: next(ids))
    model.experiment_audit_log = log
    model.record_experiment_audit_event = Mock(side_effect=log.record)
    return model


def _patch_note_dialog(monkeypatch, text, ok=True):
    monkeypatch.setattr(
        View.QtWidgets.QInputDialog,
        "getMultiLineText",
        lambda *args, **kwargs: (text, ok),
    )


def _patch_export_dialog(monkeypatch, path):
    monkeypatch.setattr(
        View.QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(path), "Markdown files (*.md)") if path else ("", ""),
    )


def test_add_operator_note_appends_valid_audit_event(qapp, tmp_path, monkeypatch):
    model = _make_audit_model(tmp_path)
    window = AuditTimelineWindow(model=model)
    note = "Remember to inspect row A1 after incubation.\nSecond line stays in details."
    _patch_note_dialog(monkeypatch, note)

    window.add_operator_note()

    rows = _read_jsonl(tmp_path / "experiment_audit.jsonl")
    assert len(rows) == 1
    event = rows[0]
    assert event["event_type"] == "operator_note_added"
    assert event["level"] == "info"
    assert event["summary"] == "Operator note added: Remember to inspect row A1 after incubation."
    assert event["details"]["note"] == note
    assert event["context"]["source"] == "audit_timeline_window"
    assert event["context"]["experiment_name"] == "Note Test"


def test_operator_note_summary_truncates_first_line(qapp, tmp_path, monkeypatch):
    model = _make_audit_model(tmp_path)
    window = AuditTimelineWindow(model=model)
    first_line = "x" * 100
    _patch_note_dialog(monkeypatch, f"{first_line}\nfull note continues")

    window.add_operator_note()

    event = _read_jsonl(tmp_path / "experiment_audit.jsonl")[0]
    snippet = event["summary"].removeprefix("Operator note added: ")
    assert len(snippet) == 80
    assert snippet == ("x" * 77) + "..."
    assert event["details"]["note"] == f"{first_line}\nfull note continues"


def test_empty_operator_note_is_rejected_without_recording(qapp, tmp_path, monkeypatch):
    model = _make_audit_model(tmp_path)
    window = AuditTimelineWindow(model=model)
    _patch_note_dialog(monkeypatch, "  \n\t  ")

    window.add_operator_note()

    model.record_experiment_audit_event.assert_not_called()
    assert not (tmp_path / "experiment_audit.jsonl").exists()
    assert "empty" in window.status_label.text().lower()


def test_operator_note_record_failures_do_not_crash(qapp, tmp_path, monkeypatch):
    model = SimpleNamespace(
        experiment_model=SimpleNamespace(experiment_dir_path=str(tmp_path)),
        record_experiment_audit_event=Mock(side_effect=RuntimeError("audit offline")),
    )
    window = AuditTimelineWindow(model=model)
    _patch_note_dialog(monkeypatch, "note")

    window.add_operator_note()

    assert "Could not add operator note" in window.status_label.text()

    model.record_experiment_audit_event = Mock(return_value=None)
    window.add_operator_note()

    assert "Could not add operator note" in window.status_label.text()


def test_operator_note_appears_in_reader_and_window_after_refresh(qapp, tmp_path, monkeypatch):
    model = _make_audit_model(tmp_path)
    window = AuditTimelineWindow(model=model)
    _patch_note_dialog(monkeypatch, "Visible note")

    window.add_operator_note()

    reader_rows = ExperimentAuditReader(model=model).read_rows()
    assert [row.event_type for row in reader_rows] == ["operator_note_added"]
    assert window.table_model.rowCount() == 1
    assert window.table_model.row_at(0).event_type == "operator_note_added"
    assert "Visible note" in window.details_text.toPlainText()


def test_operator_note_appends_without_rewriting_existing_rows(qapp, tmp_path, monkeypatch):
    model = _make_audit_model(tmp_path)
    model.record_experiment_audit_event("experiment_loaded", "Loaded")
    audit_path = tmp_path / "experiment_audit.jsonl"
    before = audit_path.read_text(encoding="utf-8")
    window = AuditTimelineWindow(model=model)
    _patch_note_dialog(monkeypatch, "Append-only note")

    window.add_operator_note()

    after = audit_path.read_text(encoding="utf-8")
    rows = _read_jsonl(audit_path)
    assert after.startswith(before)
    assert len(rows) == 2
    assert rows[0]["event_type"] == "experiment_loaded"
    assert rows[1]["event_type"] == "operator_note_added"


def test_build_audit_markdown_renders_rows_malformed_lines_and_details(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    audit_path.write_text(
        json.dumps(
            {
                "timestamp_utc": "2026-05-25T12:00:00Z",
                "elapsed_s": 1.5,
                "event_type": "operator_note_added",
                "level": "info",
                "summary": "A | B\nC",
                "details": {"note": "hello"},
                "context": {"source": "test"},
            }
        )
        + "\n"
        + "{bad json\n",
        encoding="utf-8",
    )
    rows = ExperimentAuditReader(audit_path=audit_path).read_rows()

    markdown = build_audit_markdown(
        rows,
        audit_path=audit_path,
        generated_at="2026-05-25T12:05:00Z",
    )

    assert "# Experiment Audit Timeline" in markdown
    assert f"- Audit file: `{audit_path}`" in markdown
    assert "A \\| B<br>C" in markdown
    assert "audit_parse_error" in markdown
    assert "```json" in markdown
    assert '"note": "hello"' in markdown
    assert '"raw_line": "{bad json"' in markdown


def test_export_markdown_writes_selected_file_without_mutating_audit(qapp, tmp_path, monkeypatch):
    model = _make_audit_model(tmp_path)
    model.record_experiment_audit_event("experiment_loaded", "Loaded")
    audit_path = tmp_path / "experiment_audit.jsonl"
    before = audit_path.read_text(encoding="utf-8")
    export_path = tmp_path / "experiment_audit_timeline.md"
    _patch_export_dialog(monkeypatch, export_path)
    window = AuditTimelineWindow(model=model)

    window.export_markdown()

    assert export_path.exists()
    assert "# Experiment Audit Timeline" in export_path.read_text(encoding="utf-8")
    assert "experiment_loaded" in export_path.read_text(encoding="utf-8")
    assert audit_path.read_text(encoding="utf-8") == before
    assert "Exported audit markdown" in window.status_label.text()


def test_canceled_export_does_not_write_file(qapp, tmp_path, monkeypatch):
    model = _make_audit_model(tmp_path)
    export_path = tmp_path / "experiment_audit_timeline.md"
    _patch_export_dialog(monkeypatch, None)
    window = AuditTimelineWindow(model=model)

    window.export_markdown()

    assert not export_path.exists()


def test_default_markdown_export_path_uses_experiment_directory(qapp, tmp_path):
    model = _make_audit_model(tmp_path)
    window = AuditTimelineWindow(model=model)

    assert window._default_markdown_export_path() == str(tmp_path / "experiment_audit_timeline.md")


def test_export_write_failure_is_handled(qapp, tmp_path, monkeypatch):
    model = _make_audit_model(tmp_path)
    model.record_experiment_audit_event("experiment_loaded", "Loaded")
    _patch_export_dialog(monkeypatch, tmp_path / "blocked.md")

    def _boom(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(View.Path, "write_text", _boom)
    window = AuditTimelineWindow(model=model)

    window.export_markdown()

    assert "Could not export audit" in window.status_label.text()
    assert "disk full" in window.status_label.text()
