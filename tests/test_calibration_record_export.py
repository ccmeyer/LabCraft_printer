import csv
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from CalibrationRecordExport import (
    CalibrationRecordExportError,
    export_calibration_records,
)
from tests.fakes import FakeSignal


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _make_run(
    experiment_dir: Path,
    process_name: str = "DropletSearchCalibrationProcess",
    run_id: str = "run_20260604_120000_abcdef12",
) -> Path:
    run_dir = experiment_dir / "calibration_recordings" / process_name / run_id
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "run_meta.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "process_name": process_name,
            "phase_name": "droplet_characterization",
            "started_at_utc": "2026-06-04T12:00:00Z",
            "ended_at_utc": "2026-06-04T12:01:00Z",
            "outcome": "completed",
            "error_message": "",
        },
    )
    _write_json(
        run_dir / "verdict.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "process_name": process_name,
            "phase_name": "droplet_characterization",
            "outcome": "success",
            "notes": "usable",
            "submitted_by": "unit-test",
        },
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps(
            {
                "event_type": "process_started",
                "level": "info",
                "payload": {"value": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "analysis.jsonl").write_text(
        json.dumps({"kind": "analysis", "status": "ok"}) + "\n",
        encoding="utf-8",
    )
    captures = run_dir / "captures"
    captures.mkdir()
    (captures / "frame_0001.png").write_bytes(b"fake-image")
    return run_dir


def _make_experiment(tmp_path: Path, name: str = "Test Experiment") -> Path:
    experiment_dir = tmp_path / name
    experiment_dir.mkdir()
    _make_run(experiment_dir)
    _write_json(experiment_dir / "calibration.json", {"runs": []})
    _write_json(experiment_dir / "experiment_design.json", {"name": name})
    _write_json(experiment_dir / "progress.json", {"printed": []})
    (experiment_dir / "experiment_audit.jsonl").write_text(
        json.dumps({"event": "created"}) + "\n",
        encoding="utf-8",
    )
    return experiment_dir


def test_export_calibration_records_writes_zip_with_summary_and_manifest(tmp_path):
    experiment_dir = _make_experiment(tmp_path)
    output_dir = tmp_path / "Downloads"

    result = export_calibration_records(
        experiment_dir,
        output_dir,
        created_at=datetime(2026, 6, 4, 12, 30, 0, tzinfo=timezone.utc),
    )

    archive = Path(result["archive_path"])
    assert archive == output_dir / "LabCraft_calibration_records_Test_Experiment_20260604_123000.zip"
    assert archive.exists()
    assert result["archive_size_bytes"] > 0
    assert result["summary"]["row_count"] == 1

    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        assert "calibration_recordings/DropletSearchCalibrationProcess/run_20260604_120000_abcdef12/run_meta.json" in names
        assert "calibration_recordings/DropletSearchCalibrationProcess/run_20260604_120000_abcdef12/captures/frame_0001.png" in names
        assert "calibration.json" in names
        assert "experiment_design.json" in names
        assert "progress.json" in names
        assert "experiment_audit.jsonl" in names
        assert "calibration_recordings_summary.csv" in names
        assert "manifest.json" in names

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["schema_version"] == 1
        assert manifest["experiment_name"] == "Test Experiment"
        assert manifest["archive_name"] == archive.name
        assert manifest["summary"]["row_count"] == 1
        assert "calibration_recordings" in manifest["included_top_level_items"]

        summary_rows = list(
            csv.DictReader(
                zf.read("calibration_recordings_summary.csv").decode("utf-8").splitlines()
            )
        )
        assert len(summary_rows) == 1
        assert summary_rows[0]["run_id"] == "run_20260604_120000_abcdef12"


def test_export_calibration_records_archive_paths_are_relative(tmp_path):
    experiment_dir = _make_experiment(tmp_path)
    result = export_calibration_records(experiment_dir, tmp_path / "Downloads")

    with zipfile.ZipFile(result["archive_path"]) as zf:
        for name in zf.namelist():
            assert not Path(name).is_absolute()
            assert ".." not in Path(name).parts
            assert str(experiment_dir) not in name


def test_export_calibration_records_missing_recordings_root_raises(tmp_path):
    experiment_dir = tmp_path / "NoRecordings"
    experiment_dir.mkdir()

    with pytest.raises(CalibrationRecordExportError, match="calibration_recordings not found"):
        export_calibration_records(experiment_dir, tmp_path / "Downloads")


def test_export_calibration_records_empty_recordings_root_raises(tmp_path):
    experiment_dir = tmp_path / "EmptyRecordings"
    (experiment_dir / "calibration_recordings").mkdir(parents=True)

    with pytest.raises(CalibrationRecordExportError, match="No calibration recording runs found"):
        export_calibration_records(experiment_dir, tmp_path / "Downloads")


def test_export_calibration_records_uses_unique_filename(tmp_path):
    experiment_dir = _make_experiment(tmp_path)
    output_dir = tmp_path / "Downloads"
    output_dir.mkdir()
    existing = output_dir / "LabCraft_calibration_records_Test_Experiment_20260604_123000.zip"
    existing.write_bytes(b"existing")

    result = export_calibration_records(
        experiment_dir,
        output_dir,
        created_at=datetime(2026, 6, 4, 12, 30, 0, tzinfo=timezone.utc),
    )

    assert Path(result["archive_path"]).name == "LabCraft_calibration_records_Test_Experiment_20260604_123000_2.zip"
    assert existing.read_bytes() == b"existing"


def test_export_calibration_records_skips_missing_optional_files(tmp_path):
    experiment_dir = tmp_path / "Minimal"
    experiment_dir.mkdir()
    _make_run(experiment_dir)

    result = export_calibration_records(experiment_dir, tmp_path / "Downloads")

    with zipfile.ZipFile(result["archive_path"]) as zf:
        names = set(zf.namelist())
        assert "calibration_recordings_summary.csv" in names
        assert "manifest.json" in names
        assert "calibration.json" not in names
        assert "experiment_design.json" not in names
        assert "progress.json" not in names
        assert "experiment_audit.jsonl" not in names


def _raise(exc):
    raise exc


def test_calibration_record_export_worker_emits_succeeded(monkeypatch):
    import CalibrationClasses.View as calibration_view

    expected = {"archive_path": "records.zip", "archive_size_bytes": 123}
    monkeypatch.setattr(
        calibration_view,
        "export_calibration_records",
        lambda experiment_dir, output_dir: expected,
    )
    worker = calibration_view._CalibrationRecordExportWorker("experiment", "downloads")
    seen = []
    worker.succeeded.connect(lambda payload: seen.append(payload))

    worker.run()

    assert seen == [expected]


def test_calibration_record_export_worker_emits_warning_for_export_error(monkeypatch):
    import CalibrationClasses.View as calibration_view

    monkeypatch.setattr(
        calibration_view,
        "export_calibration_records",
        lambda experiment_dir, output_dir: _raise(CalibrationRecordExportError("no records")),
    )
    worker = calibration_view._CalibrationRecordExportWorker("experiment", "downloads")
    seen = []
    worker.failed.connect(lambda message, severity: seen.append((message, severity)))

    worker.run()

    assert seen == [("no records", "warning")]


def test_calibration_record_export_worker_emits_critical_for_unexpected_error(monkeypatch):
    import CalibrationClasses.View as calibration_view

    monkeypatch.setattr(
        calibration_view,
        "export_calibration_records",
        lambda experiment_dir, output_dir: _raise(RuntimeError("disk error")),
    )
    worker = calibration_view._CalibrationRecordExportWorker("experiment", "downloads")
    seen = []
    worker.failed.connect(lambda message, severity: seen.append((message, severity)))

    worker.run()

    assert seen == [("disk error", "critical")]


class _FakeButton:
    def __init__(self):
        self.enabled = True
        self.text = ""
        self.tooltip = ""

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setText(self, text):
        self.text = str(text)

    def setToolTip(self, tooltip):
        self.tooltip = str(tooltip)


class _FakeExportThread:
    instances = []

    def __init__(self, parent=None):
        self.parent = parent
        self.started = FakeSignal()
        self.finished = FakeSignal()
        self.started_called = False
        self.quit_called = False
        self.deleted = False
        self.__class__.instances.append(self)

    def start(self):
        self.started_called = True
        self.started.emit()

    def quit(self, *args, **kwargs):
        self.quit_called = True
        self.finished.emit()

    def deleteLater(self, *args, **kwargs):
        self.deleted = True


class _FakeExportWorker:
    instances = []

    def __init__(self, experiment_dir, output_dir):
        self.experiment_dir = experiment_dir
        self.output_dir = output_dir
        self.succeeded = FakeSignal()
        self.failed = FakeSignal()
        self.run_called = False
        self.deleted = False
        self.thread = None
        self.__class__.instances.append(self)

    def moveToThread(self, thread):
        self.thread = thread

    def run(self):
        self.run_called = True

    def deleteLater(self, *args, **kwargs):
        self.deleted = True


def _make_export_dialog(calibration_view, experiment_dir, downloads_dir):
    dialog = calibration_view.DropletImagingDialog.__new__(calibration_view.DropletImagingDialog)
    dialog.model = SimpleNamespace(
        experiment_model=SimpleNamespace(experiment_dir_path=str(experiment_dir)),
        calibration_manager=SimpleNamespace(calibration_file_path=""),
    )
    dialog.controller = object()
    dialog._capture_request_pending = False
    dialog._calibration_record_export_thread = None
    dialog._calibration_record_export_worker = None
    dialog._calibration_record_export_in_progress = False
    dialog.export_calibration_records_button = _FakeButton()
    dialog._resolve_downloads_dir = lambda: downloads_dir
    dialog.update_stage_and_log = lambda *args, **kwargs: None
    return dialog


def _install_fake_export_threading(monkeypatch, calibration_view):
    _FakeExportThread.instances = []
    _FakeExportWorker.instances = []
    monkeypatch.setattr(calibration_view.QtCore, "QThread", _FakeExportThread)
    monkeypatch.setattr(calibration_view, "_CalibrationRecordExportWorker", _FakeExportWorker)


def test_droplet_dialog_export_handler_starts_worker_and_restores_on_success(monkeypatch, tmp_path):
    import CalibrationClasses.View as calibration_view

    experiment_dir = _make_experiment(tmp_path)
    downloads_dir = tmp_path / "Downloads"
    dialog = _make_export_dialog(calibration_view, experiment_dir, downloads_dir)
    _install_fake_export_threading(monkeypatch, calibration_view)
    info_messages = []
    warning_messages = []
    monkeypatch.setattr(
        calibration_view.DropletImagingDialog,
        "_is_calibration_busy",
        lambda self: False,
    )
    monkeypatch.setattr(
        calibration_view.QtWidgets.QMessageBox,
        "information",
        lambda *args, **kwargs: info_messages.append(args),
    )
    monkeypatch.setattr(
        calibration_view.QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warning_messages.append(args),
    )

    calibration_view.DropletImagingDialog.export_calibration_records_to_downloads(dialog)

    assert len(_FakeExportWorker.instances) == 1
    assert len(_FakeExportThread.instances) == 1
    worker = _FakeExportWorker.instances[0]
    thread = _FakeExportThread.instances[0]
    assert Path(worker.experiment_dir) == experiment_dir
    assert Path(worker.output_dir) == downloads_dir
    assert worker.thread is thread
    assert worker.run_called is True
    assert dialog.export_calibration_records_button.enabled is False
    assert dialog.export_calibration_records_button.text == "Exporting..."

    worker.succeeded.emit(
        {
            "archive_path": str(downloads_dir / "records.zip"),
            "archive_size_bytes": 2048,
        }
    )

    assert thread.quit_called is True
    assert thread.deleted is True
    assert worker.deleted is True
    assert dialog._calibration_record_export_thread is None
    assert dialog._calibration_record_export_worker is None
    assert dialog._calibration_record_export_in_progress is False
    assert dialog.export_calibration_records_button.enabled is True
    assert dialog.export_calibration_records_button.text == "Export Calibration Records"
    assert info_messages
    assert not warning_messages


@pytest.mark.parametrize(
    ("severity", "expected_message_kind"),
    [
        ("warning", "warning"),
        ("critical", "critical"),
    ],
)
def test_droplet_dialog_export_handler_restores_on_failure(
    monkeypatch,
    tmp_path,
    severity,
    expected_message_kind,
):
    import CalibrationClasses.View as calibration_view

    experiment_dir = _make_experiment(tmp_path)
    downloads_dir = tmp_path / "Downloads"
    dialog = _make_export_dialog(calibration_view, experiment_dir, downloads_dir)
    _install_fake_export_threading(monkeypatch, calibration_view)
    messages = {"warning": [], "critical": []}
    monkeypatch.setattr(
        calibration_view.DropletImagingDialog,
        "_is_calibration_busy",
        lambda self: False,
    )
    monkeypatch.setattr(
        calibration_view.QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: messages["warning"].append(args),
    )
    monkeypatch.setattr(
        calibration_view.QtWidgets.QMessageBox,
        "critical",
        lambda *args, **kwargs: messages["critical"].append(args),
    )

    calibration_view.DropletImagingDialog.export_calibration_records_to_downloads(dialog)
    worker = _FakeExportWorker.instances[0]
    worker.failed.emit("export failed", severity)

    assert dialog._calibration_record_export_in_progress is False
    assert dialog.export_calibration_records_button.enabled is True
    assert dialog.export_calibration_records_button.text == "Export Calibration Records"
    assert messages[expected_message_kind]


def test_droplet_dialog_export_handler_blocks_second_click_while_exporting(monkeypatch, tmp_path):
    import CalibrationClasses.View as calibration_view

    experiment_dir = _make_experiment(tmp_path)
    downloads_dir = tmp_path / "Downloads"
    dialog = _make_export_dialog(calibration_view, experiment_dir, downloads_dir)
    _install_fake_export_threading(monkeypatch, calibration_view)
    warning_messages = []
    monkeypatch.setattr(
        calibration_view.DropletImagingDialog,
        "_is_calibration_busy",
        lambda self: False,
    )
    monkeypatch.setattr(
        calibration_view.QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warning_messages.append(args),
    )

    calibration_view.DropletImagingDialog.export_calibration_records_to_downloads(dialog)
    calibration_view.DropletImagingDialog.export_calibration_records_to_downloads(dialog)

    assert len(_FakeExportWorker.instances) == 1
    assert warning_messages
    assert dialog.export_calibration_records_button.enabled is False
    assert dialog.export_calibration_records_button.text == "Exporting..."


def test_droplet_dialog_export_handler_blocks_while_busy(monkeypatch, tmp_path):
    import CalibrationClasses.View as calibration_view

    experiment_dir = _make_experiment(tmp_path)
    downloads_dir = tmp_path / "Downloads"
    dialog = _make_export_dialog(calibration_view, experiment_dir, downloads_dir)
    _install_fake_export_threading(monkeypatch, calibration_view)

    monkeypatch.setattr(
        calibration_view.DropletImagingDialog,
        "_is_calibration_busy",
        lambda self: True,
    )
    warning_messages = []
    monkeypatch.setattr(
        calibration_view.QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warning_messages.append(args),
    )

    calibration_view.DropletImagingDialog.export_calibration_records_to_downloads(dialog)

    assert warning_messages
    assert not _FakeExportWorker.instances
