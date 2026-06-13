from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets

import PlateReaderAnalysisWindow as plate_reader_window_module
import View
from Controller import Controller
from PlateReaderAnalysisRunner import PlateReaderAnalysisConfig, PlateReaderAnalysisPreviewResult
from PlateReaderAnalysisWindow import PlateReaderAnalysisWindow


class _WindowController(QtCore.QObject):
    plate_reader_analysis_preview_stage = QtCore.Signal(str)
    plate_reader_analysis_preview_finished = QtCore.Signal(bool, str, object)
    plate_reader_analysis_stage = QtCore.Signal(str)
    plate_reader_analysis_output = QtCore.Signal(str)
    plate_reader_analysis_finished = QtCore.Signal(bool, str, object)

    def __init__(self, *, start_result=True, preview_start_result=True):
        super().__init__()
        self.start_result = start_result
        self.preview_start_result = preview_start_result
        self.started_preview_config = None
        self.started_config = None
        self.cancel_calls = 0

    def start_plate_reader_analysis_preview(self, config):
        self.started_preview_config = config
        return self.preview_start_result

    def start_plate_reader_analysis(self, config):
        self.started_config = config
        return self.start_result

    def cancel_plate_reader_analysis(self):
        self.cancel_calls += 1
        return True


class _MachineModel:
    def get_current_position_dict(self):
        return {}

    def get_current_location(self):
        return "unknown"


class _FakeWorker(QtCore.QObject):
    stage = QtCore.Signal(str)
    output = QtCore.Signal(str)
    run_finished = QtCore.Signal(bool, str, object)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.started = False
        self.running = False
        self.cancelled = False

    def start(self):
        self.started = True
        self.running = True

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancelled = True

    def finish(self, ok=True, message="done", payload=None):
        self.running = False
        self.run_finished.emit(bool(ok), str(message), payload or {})


class _FakePreviewWorker(QtCore.QObject):
    stage = QtCore.Signal(str)
    run_finished = QtCore.Signal(bool, str, object)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.started = False
        self.running = False

    def start(self):
        self.started = True
        self.running = True

    def isRunning(self):
        return self.running

    def finish(self, ok=True, message="preview done", payload=None):
        self.running = False
        self.run_finished.emit(bool(ok), str(message), payload or {})


def _make_experiment(tmp_path: Path):
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    key_file = experiment_dir / "concentration_key.csv"
    key_file.write_text("Well ID,DNA_mM\nA1,1\n", encoding="utf-8")
    plate_file = tmp_path / "plate_reader.txt"
    plate_file.write_text("raw plate reader export\n", encoding="utf-8")
    return experiment_dir, key_file, plate_file


def _make_window(tmp_path: Path, qapp, *, controller=None):
    experiment_dir, key_file, plate_file = _make_experiment(tmp_path)
    model = SimpleNamespace(
        experiment_model=SimpleNamespace(
            experiment_dir_path=str(experiment_dir),
            concentration_key_file_path=str(key_file),
        )
    )
    controller = controller or _WindowController()
    window = PlateReaderAnalysisWindow(None, model=model, controller=controller)
    window.plate_reader_file_edit.setText(str(plate_file))
    qapp.processEvents()
    return window, controller, experiment_dir, key_file, plate_file


def _make_controller(tmp_path: Path):
    controller = Controller.__new__(Controller)
    QtCore.QObject.__init__(controller)
    controller._repo_root = Path(tmp_path)
    controller._plate_reader_analysis_preview_worker = None
    controller._plate_reader_analysis_worker = None
    return controller


def _preview_payload(experiment_dir: Path, *, ok: bool = True, errors=None, warnings=None) -> dict[str, object]:
    return {
        "ok": ok,
        "message": "Validation preview passed." if ok else "Validation preview failed.",
        "errors": list(errors or []),
        "warnings": list(warnings or []),
        "summary": {
            "measured_well_count": 2,
            "key_well_count": 2,
            "keyed_measured_well_count": 2,
            "unkeyed_measured_well_count": 0,
            "missing_key_well_count": 0,
            "keyed_measured_wells": ["A1", "A2"],
            "unkeyed_measured_wells": [],
            "missing_key_wells": [],
            "fluorophores": ["488_509"],
            "timepoint_count": 3,
            "time_minutes_min": 0.0,
            "time_minutes_max": 2.0,
            "has_timecourse_data": True,
            "condition_columns": ["DNA_mM"],
            "composition_count": 2,
            "dropped_timepoint_count": 0,
        },
        "paths": {
            "merged_csv": str(experiment_dir / "plate_reader_merged_tidy.csv"),
            "output_dir": str(experiment_dir / "plate_reader_analysis"),
            "report_html": str(experiment_dir / "plate_reader_analysis" / "analysis_report.html"),
        },
    }


def _analysis_manifest(output_dir: Path) -> dict[str, object]:
    return {
        "schema_version": "plate_reader_analysis_manifest_v1",
        "created_at": "2026-06-13T12:00:00",
        "inputs": {
            "merged_csv": "plate_reader_merged_tidy.csv",
            "output_dir": ".",
            "endpoint_last_n": 3,
        },
        "dataset": {
            "total_rows": 12,
            "endpoint_rows": 4,
            "composition_rows": 2,
            "keyed_well_count": 4,
            "measured_well_count": 5,
            "fluorophores": ["488_509"],
            "condition_columns": ["DNA_mM", "MgCl2_mM"],
            "has_timecourse_data": True,
        },
        "outliers": {
            "final_outlier_count": 1,
            "outlier_summary_path": "outlier_summary.csv",
        },
        "outputs": [
            {
                "category": "endpoint_tables",
                "kind": "csv",
                "path": "endpoint_by_well.csv",
                "title": "Endpoint by well",
            },
            {
                "category": "absolute_rfu_heatmaps",
                "kind": "csv",
                "path": "heatmaps_absolute_rfu/488_509_endpoint_rfu.csv",
                "title": "Absolute RFU matrix",
            },
            {
                "category": "absolute_rfu_heatmaps",
                "kind": "png",
                "path": "heatmaps_absolute_rfu/488_509_endpoint_rfu.png",
                "title": "Absolute RFU heatmap",
            },
            {
                "category": "endpoint_variability",
                "kind": "png",
                "path": "endpoint_variability/including_outliers/488_509_cv_vs_mean_endpoint_rfu.png",
                "title": "CV vs mean",
            },
            {
                "category": "metadata",
                "kind": "json",
                "path": "analysis_manifest.json",
                "title": "Analysis manifest",
            },
        ],
        "warnings": ["Endpoint-only data skipped timecourse plots."],
    }


def _write_manifest(output_dir: Path, manifest: dict[str, object] | None = None) -> Path:
    manifest_path = output_dir / "analysis_manifest.json"
    manifest_path.write_text(json.dumps(manifest or _analysis_manifest(output_dir)), encoding="utf-8")
    return manifest_path


def _table_rows(table: QtWidgets.QTableWidget) -> dict[str, str]:
    rows: dict[str, str] = {}
    for row in range(table.rowCount()):
        label_item = table.item(row, 0)
        value_item = table.item(row, 1)
        if label_item is not None:
            rows[label_item.text()] = value_item.text() if value_item is not None else ""
    return rows


def _output_table_rows(table: QtWidgets.QTableWidget) -> dict[str, tuple[str, str, str, str]]:
    rows: dict[str, tuple[str, str, str, str]] = {}
    for row in range(table.rowCount()):
        category_item = table.item(row, 0)
        if category_item is None:
            continue
        rows[category_item.text()] = tuple(
            table.item(row, column).text() if table.item(row, column) is not None else ""
            for column in range(1, 5)
        )
    return rows


def _validate_window_preview(window, controller, experiment_dir: Path, qapp):
    window._on_validate_preview_clicked()
    controller.plate_reader_analysis_preview_finished.emit(
        True,
        "Validation preview passed.",
        _preview_payload(experiment_dir),
    )
    qapp.processEvents()


def test_window_defaults_experiment_and_key_paths_from_model(tmp_path, qapp):
    window, _controller, experiment_dir, key_file, _plate_file = _make_window(tmp_path, qapp)

    assert window.experiment_dir_edit.text() == str(experiment_dir)
    assert window.key_file_edit.text() == str(key_file)
    assert window.output_dir_edit.text() == ""
    assert window.endpoint_last_n_spin.value() == 3
    assert window.run_button.isEnabled() is False
    assert window.validate_preview_button.isEnabled() is True
    assert window.export_button.isEnabled() is False
    assert window.open_export_folder_button.isEnabled() is False

    window.close()


def test_window_validate_preview_builds_config_and_locks_inputs(tmp_path, qapp):
    window, controller, experiment_dir, key_file, plate_file = _make_window(tmp_path, qapp)

    window._on_validate_preview_clicked()

    assert isinstance(controller.started_preview_config, PlateReaderAnalysisConfig)
    assert Path(controller.started_preview_config.experiment_dir) == experiment_dir
    assert Path(controller.started_preview_config.plate_reader_file) == plate_file
    assert Path(controller.started_preview_config.key_file) == key_file
    assert controller.started_preview_config.output_dir is None
    assert controller.started_preview_config.endpoint_last_n == 3
    assert window.experiment_dir_edit.isEnabled() is False
    assert window.validate_preview_button.isEnabled() is False
    assert window.run_button.isEnabled() is False
    assert "Validating preview" in window.preview_messages.toPlainText()

    controller.plate_reader_analysis_preview_finished.emit(
        True,
        "Validation preview passed.",
        _preview_payload(experiment_dir),
    )
    window.close()


def test_window_run_builds_expected_config_and_locks_inputs(tmp_path, qapp):
    window, controller, experiment_dir, key_file, plate_file = _make_window(tmp_path, qapp)
    _validate_window_preview(window, controller, experiment_dir, qapp)

    window._on_run_clicked()

    assert isinstance(controller.started_config, PlateReaderAnalysisConfig)
    assert Path(controller.started_config.experiment_dir) == experiment_dir
    assert Path(controller.started_config.plate_reader_file) == plate_file
    assert Path(controller.started_config.key_file) == key_file
    assert controller.started_config.output_dir is None
    assert controller.started_config.endpoint_last_n == 3
    assert window.run_button.isEnabled() is False
    assert window.cancel_button.isEnabled() is True

    controller.plate_reader_analysis_finished.emit(False, "stopped", {})
    window.close()


def test_window_failed_preview_shows_errors_and_keeps_run_disabled(tmp_path, qapp):
    window, controller, _experiment_dir, _key_file, plate_file = _make_window(tmp_path, qapp)
    plate_file.unlink()

    window._on_validate_preview_clicked()
    controller.plate_reader_analysis_preview_finished.emit(
        False,
        "Validation preview failed.",
        _preview_payload(Path(window.experiment_dir_edit.text()), ok=False, errors=["Plate-reader file does not exist"]),
    )

    assert controller.started_config is None
    assert "Preview failed" in window.status_label.text()
    assert "Plate-reader file does not exist" in window.preview_messages.toPlainText()
    assert window.run_button.isEnabled() is False

    window.close()


def test_window_stage_and_output_signals_update_status_and_log(tmp_path, qapp):
    window, controller, *_ = _make_window(tmp_path, qapp)

    controller.plate_reader_analysis_stage.emit("Running analysis")
    controller.plate_reader_analysis_output.emit("analysis output line")
    qapp.processEvents()

    assert window.status_label.text() == "Running analysis"
    assert "analysis output line" in window.log_output.toPlainText()

    window.close()


def test_window_success_enables_report_and_folder_buttons(tmp_path, qapp):
    window, controller, experiment_dir, *_ = _make_window(tmp_path, qapp)
    output_dir = tmp_path / "analysis"
    output_dir.mkdir()
    report = output_dir / "analysis_report.html"
    report.write_text("<html></html>", encoding="utf-8")

    _validate_window_preview(window, controller, experiment_dir, qapp)
    window._on_run_clicked()
    controller.plate_reader_analysis_finished.emit(
        True,
        "finished",
        {"report_html": str(report), "output_dir": str(output_dir)},
    )
    qapp.processEvents()

    assert window.status_label.text() == "Finished"
    assert window.open_report_button.isEnabled() is True
    assert window.open_folder_button.isEnabled() is True
    assert window.export_button.isEnabled() is True
    assert "finished" in window.log_output.toPlainText()

    window.close()


def test_window_success_with_manifest_populates_result_summary(tmp_path, qapp):
    window, controller, experiment_dir, *_ = _make_window(tmp_path, qapp)
    output_dir = tmp_path / "analysis"
    output_dir.mkdir()
    report = output_dir / "analysis_report.html"
    report.write_text("<html></html>", encoding="utf-8")
    manifest_path = _write_manifest(output_dir)

    _validate_window_preview(window, controller, experiment_dir, qapp)
    window._on_run_clicked()
    controller.plate_reader_analysis_finished.emit(
        True,
        "finished",
        {
            "report_html": str(report),
            "output_dir": str(output_dir),
            "manifest_json": str(manifest_path),
        },
    )
    qapp.processEvents()

    summary = _table_rows(window.result_summary_table)
    assert summary["Merged CSV"] == "plate_reader_merged_tidy.csv"
    assert summary["Output directory"] == "."
    assert summary["Measured wells"] == "5"
    assert summary["Keyed wells"] == "4"
    assert summary["Endpoint rows"] == "4"
    assert summary["Composition rows"] == "2"
    assert summary["Fluorophores"] == "488_509"
    assert summary["Condition columns"] == "DNA_mM, MgCl2_mM"
    assert summary["Data type"] == "Timecourse"
    assert summary["Endpoint outliers"] == "1"
    assert summary["Warnings"] == "1"
    assert "Endpoint-only data skipped timecourse plots" in window.result_messages.toPlainText()
    assert window.open_report_button.isEnabled() is True
    assert window.open_folder_button.isEnabled() is True
    assert window.export_button.isEnabled() is True

    outputs = _output_table_rows(window.result_outputs_table)
    assert outputs["absolute_rfu_heatmaps"] == ("1", "1", "0", "2")
    assert outputs["endpoint_tables"] == ("1", "0", "0", "1")
    assert outputs["endpoint_variability"] == ("0", "1", "0", "1")
    assert outputs["metadata"] == ("0", "0", "1", "1")

    window.close()


def test_window_missing_manifest_shows_result_error_but_keeps_result_buttons(tmp_path, qapp):
    window, controller, experiment_dir, *_ = _make_window(tmp_path, qapp)
    output_dir = tmp_path / "analysis"
    output_dir.mkdir()
    report = output_dir / "analysis_report.html"
    report.write_text("<html></html>", encoding="utf-8")
    missing_manifest = output_dir / "missing_manifest.json"

    _validate_window_preview(window, controller, experiment_dir, qapp)
    window._on_run_clicked()
    controller.plate_reader_analysis_finished.emit(
        True,
        "finished",
        {
            "report_html": str(report),
            "output_dir": str(output_dir),
            "manifest_json": str(missing_manifest),
        },
    )
    qapp.processEvents()

    assert window.result_summary_table.rowCount() == 0
    assert window.result_outputs_table.rowCount() == 0
    assert "manifest does not exist" in window.result_messages.toPlainText()
    assert window.open_report_button.isEnabled() is True
    assert window.open_folder_button.isEnabled() is True
    assert window.export_button.isEnabled() is True

    window.close()


def test_window_invalid_manifest_schema_shows_result_error(tmp_path, qapp):
    window, controller, experiment_dir, *_ = _make_window(tmp_path, qapp)
    output_dir = tmp_path / "analysis"
    output_dir.mkdir()
    report = output_dir / "analysis_report.html"
    report.write_text("<html></html>", encoding="utf-8")
    manifest_path = _write_manifest(output_dir, {"schema_version": "not_the_contract"})

    _validate_window_preview(window, controller, experiment_dir, qapp)
    window._on_run_clicked()
    controller.plate_reader_analysis_finished.emit(
        True,
        "finished",
        {
            "report_html": str(report),
            "output_dir": str(output_dir),
            "manifest_json": str(manifest_path),
        },
    )
    qapp.processEvents()

    assert window.result_summary_table.rowCount() == 0
    assert "unsupported manifest schema" in window.result_messages.toPlainText()
    assert window.open_report_button.isEnabled() is True
    assert window.export_button.isEnabled() is True

    window.close()


def test_window_failure_restores_controls_and_keeps_result_buttons_disabled(tmp_path, qapp):
    window, controller, experiment_dir, *_ = _make_window(tmp_path, qapp)

    _validate_window_preview(window, controller, experiment_dir, qapp)
    window._on_run_clicked()
    controller.plate_reader_analysis_finished.emit(False, "failed", {})
    qapp.processEvents()

    assert window.status_label.text() == "Failed"
    assert window.run_button.isEnabled() is True
    assert window.cancel_button.isEnabled() is False
    assert window.open_report_button.isEnabled() is False
    assert window.open_folder_button.isEnabled() is False
    assert window.export_button.isEnabled() is False
    assert window.open_export_folder_button.isEnabled() is False
    assert window.result_summary_table.rowCount() == 0
    assert "did not finish successfully" in window.result_messages.toPlainText()

    window.close()


def test_window_cancel_calls_controller_cancel(tmp_path, qapp):
    window, controller, experiment_dir, *_ = _make_window(tmp_path, qapp)

    _validate_window_preview(window, controller, experiment_dir, qapp)
    window._on_run_clicked()
    window._on_cancel_clicked()

    assert controller.cancel_calls == 1
    assert "Cancel requested" in window.log_output.toPlainText()

    controller.plate_reader_analysis_finished.emit(False, "canceled", {})
    window.close()


def test_window_start_rejected_by_controller_restores_idle_state(tmp_path, qapp):
    controller = _WindowController(start_result=False)
    window, controller, experiment_dir, *_ = _make_window(tmp_path, qapp, controller=controller)

    _validate_window_preview(window, controller, experiment_dir, qapp)
    window._on_run_clicked()

    assert window.status_label.text() == "Failed"
    assert window.run_button.isEnabled() is True
    assert window.cancel_button.isEnabled() is False
    assert "already active" in window.log_output.toPlainText()

    window.close()


def test_window_export_package_uses_latest_payload_and_enables_export_folder(
    tmp_path,
    qapp,
    monkeypatch,
):
    window, controller, experiment_dir, key_file, plate_file = _make_window(tmp_path, qapp)
    output_dir = tmp_path / "analysis"
    output_dir.mkdir()
    report = output_dir / "analysis_report.html"
    report.write_text("<html></html>", encoding="utf-8")
    merged_csv = experiment_dir / "plate_reader_merged_tidy.csv"
    merged_csv.write_text("well,rfu\nA1,100\n", encoding="utf-8")
    raw_copy = experiment_dir / "raw_plate_reader" / plate_file.name
    raw_copy.parent.mkdir()
    raw_copy.write_text("raw\n", encoding="utf-8")
    manifest_path = _write_manifest(output_dir)
    export_path = tmp_path / "export.zip"
    captured = {}

    def fake_get_save_file_name(*_args, **_kwargs):
        return str(export_path), "ZIP files (*.zip)"

    def fake_export(config):
        captured["config"] = config
        export_path.write_bytes(b"zip")
        return {"destination": str(export_path), "missing_files": []}

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", fake_get_save_file_name)
    monkeypatch.setattr(plate_reader_window_module, "export_plate_reader_analysis_package", fake_export)

    _validate_window_preview(window, controller, experiment_dir, qapp)
    window._on_run_clicked()
    payload = {
        "experiment_dir": str(experiment_dir),
        "plate_reader_file": str(plate_file),
        "copied_plate_reader_file": str(raw_copy),
        "key_file": str(key_file),
        "merged_csv": str(merged_csv),
        "output_dir": str(output_dir),
        "manifest_json": str(manifest_path),
        "report_html": str(report),
        "command_returncodes": {"associate": 0, "analyze": 0},
    }
    controller.plate_reader_analysis_finished.emit(True, "finished", payload)
    qapp.processEvents()
    assert window.export_button.isEnabled() is True

    window._on_export_clicked()

    assert captured["config"].analysis_payload == payload
    assert Path(captured["config"].destination) == export_path
    assert captured["config"].created_by == "LabCraft app"
    assert window.open_export_folder_button.isEnabled() is True
    assert "Exported plate-reader analysis package" in window.log_output.toPlainText()

    window.close()


def test_window_export_failure_logs_error_and_keeps_window_usable(tmp_path, qapp, monkeypatch):
    window, controller, experiment_dir, *_ = _make_window(tmp_path, qapp)
    output_dir = tmp_path / "analysis"
    output_dir.mkdir()
    report = output_dir / "analysis_report.html"
    report.write_text("<html></html>", encoding="utf-8")
    manifest_path = _write_manifest(output_dir)

    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(tmp_path / "export.zip"), "ZIP files (*.zip)"),
    )

    def fake_export(_config):
        raise RuntimeError("disk full")

    monkeypatch.setattr(plate_reader_window_module, "export_plate_reader_analysis_package", fake_export)

    _validate_window_preview(window, controller, experiment_dir, qapp)
    window._on_run_clicked()
    controller.plate_reader_analysis_finished.emit(
        True,
        "finished",
        {
            "experiment_dir": str(experiment_dir),
            "output_dir": str(output_dir),
            "manifest_json": str(manifest_path),
            "report_html": str(report),
        },
    )
    qapp.processEvents()

    window._on_export_clicked()

    assert window.status_label.text() == "Export failed"
    assert "disk full" in window.log_output.toPlainText()
    assert window.export_button.isEnabled() is True
    assert window.open_export_folder_button.isEnabled() is False

    window.close()


def test_window_successful_preview_populates_summary_and_enables_run(tmp_path, qapp):
    window, controller, experiment_dir, *_ = _make_window(tmp_path, qapp)

    _validate_window_preview(window, controller, experiment_dir, qapp)

    assert window.status_label.text() == "Preview valid"
    assert window.run_button.isEnabled() is True
    assert "Validation preview passed" in window.preview_messages.toPlainText()
    table_values = [
        window.preview_table.item(row, 1).text()
        for row in range(window.preview_table.rowCount())
        if window.preview_table.item(row, 0) is not None
    ]
    assert any("488_509" in value for value in table_values)
    assert any("DNA_mM" in value for value in table_values)

    window.close()


def test_window_edit_after_preview_marks_preview_stale_and_disables_run(tmp_path, qapp):
    window, controller, experiment_dir, *_ = _make_window(tmp_path, qapp)
    _validate_window_preview(window, controller, experiment_dir, qapp)
    assert window.run_button.isEnabled() is True

    window.endpoint_last_n_spin.setValue(4)
    qapp.processEvents()

    assert window.run_button.isEnabled() is False
    assert "Preview stale" in window.status_label.text()
    assert "Inputs changed" in window.preview_messages.toPlainText()

    window.close()


def test_window_edit_after_success_clears_result_summary_and_buttons(tmp_path, qapp):
    window, controller, experiment_dir, *_ = _make_window(tmp_path, qapp)
    output_dir = tmp_path / "analysis"
    output_dir.mkdir()
    report = output_dir / "analysis_report.html"
    report.write_text("<html></html>", encoding="utf-8")
    manifest_path = _write_manifest(output_dir)

    _validate_window_preview(window, controller, experiment_dir, qapp)
    window._on_run_clicked()
    controller.plate_reader_analysis_finished.emit(
        True,
        "finished",
        {
            "report_html": str(report),
            "output_dir": str(output_dir),
            "manifest_json": str(manifest_path),
        },
    )
    qapp.processEvents()
    assert window.result_summary_table.rowCount() > 0
    assert window.open_report_button.isEnabled() is True

    window.endpoint_last_n_spin.setValue(4)
    qapp.processEvents()

    assert window.result_summary_table.rowCount() == 0
    assert window.result_outputs_table.rowCount() == 0
    assert window.open_report_button.isEnabled() is False
    assert window.open_folder_button.isEnabled() is False
    assert window.export_button.isEnabled() is False
    assert window.open_export_folder_button.isEnabled() is False
    assert "Run analysis" in window.result_messages.toPlainText()

    window.close()


def test_right_panel_exposes_plate_reader_analysis_button(qapp):
    host = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(host)
    main_window = SimpleNamespace(
        show_experiment_audit=lambda: None,
        show_plate_reader_analysis=lambda: None,
        show_keyboard_shortcuts=lambda: None,
    )

    View.MainWindow._add_right_panel_action_buttons(main_window, layout)

    button = host.findChild(QtWidgets.QPushButton, "plateReaderAnalysisButton")
    assert button is not None
    assert button.text() == "Analyze Plate Reader..."

    host.close()


def test_controller_start_plate_reader_analysis_bridges_worker_signals(tmp_path):
    controller = _make_controller(tmp_path)
    created_workers = []
    stages = []
    outputs = []
    finished = []
    controller.plate_reader_analysis_stage.connect(stages.append)
    controller.plate_reader_analysis_output.connect(outputs.append)
    controller.plate_reader_analysis_finished.connect(lambda ok, msg, payload: finished.append((ok, msg, payload)))

    def worker_factory(config):
        worker = _FakeWorker(config)
        created_workers.append(worker)
        return worker

    config = PlateReaderAnalysisConfig(
        experiment_dir=tmp_path,
        plate_reader_file=tmp_path / "plate.txt",
        key_file=tmp_path / "concentration_key.csv",
    )
    assert controller.start_plate_reader_analysis(config, worker_factory=worker_factory) is True
    worker = created_workers[0]
    assert worker.started is True
    assert controller.is_plate_reader_analysis_running() is True

    assert controller.start_plate_reader_analysis(config, worker_factory=worker_factory) is False
    assert any("already active" in line for line in outputs)

    worker.stage.emit("stage one")
    worker.output.emit("output one")
    worker.finish(True, "done", {"report_html": "report.html"})

    assert "stage one" in stages
    assert "output one" in outputs
    assert finished == [(True, "done", {"report_html": "report.html"})]
    assert controller.is_plate_reader_analysis_running() is False


def test_controller_start_plate_reader_analysis_preview_bridges_worker_signals(tmp_path):
    controller = _make_controller(tmp_path)
    created_workers = []
    stages = []
    finished = []
    controller.plate_reader_analysis_preview_stage.connect(stages.append)
    controller.plate_reader_analysis_preview_finished.connect(
        lambda ok, msg, payload: finished.append((ok, msg, payload))
    )

    def worker_factory(config):
        worker = _FakePreviewWorker(config)
        created_workers.append(worker)
        return worker

    config = PlateReaderAnalysisConfig(
        experiment_dir=tmp_path,
        plate_reader_file=tmp_path / "plate.txt",
        key_file=tmp_path / "concentration_key.csv",
    )

    assert controller.start_plate_reader_analysis_preview(config, worker_factory=worker_factory) is True
    worker = created_workers[0]
    assert worker.started is True
    assert controller.is_plate_reader_analysis_preview_running() is True

    worker.stage.emit("validating")
    payload = PlateReaderAnalysisPreviewResult(True, "ok", [], [], {"measured_well_count": 1}, {})
    worker.finish(True, "ok", payload)

    assert stages == ["validating"]
    assert finished == [(True, "ok", payload)]
    assert controller.is_plate_reader_analysis_preview_running() is False


def test_controller_preview_rejects_concurrent_preview_or_analysis(tmp_path):
    controller = _make_controller(tmp_path)
    created_previews = []
    preview_finished = []
    analysis_outputs = []
    controller.plate_reader_analysis_preview_finished.connect(
        lambda ok, msg, payload: preview_finished.append((ok, msg, payload))
    )
    controller.plate_reader_analysis_output.connect(analysis_outputs.append)

    def preview_factory(config):
        worker = _FakePreviewWorker(config)
        created_previews.append(worker)
        return worker

    config = PlateReaderAnalysisConfig(
        experiment_dir=tmp_path,
        plate_reader_file=tmp_path / "plate.txt",
        key_file=tmp_path / "concentration_key.csv",
    )

    assert controller.start_plate_reader_analysis_preview(config, worker_factory=preview_factory) is True
    assert controller.start_plate_reader_analysis_preview(config, worker_factory=preview_factory) is False
    assert "preview is already active" in preview_finished[-1][1]
    assert controller.start_plate_reader_analysis(config, worker_factory=lambda _config: _FakeWorker(_config)) is False
    assert any("preview is already active" in line for line in analysis_outputs)

    created_previews[0].finish(True, "preview done", {})
    assert controller.start_plate_reader_analysis(config, worker_factory=lambda _config: _FakeWorker(_config)) is True
    assert controller.start_plate_reader_analysis_preview(config, worker_factory=preview_factory) is False
    assert "run is already active" in preview_finished[-1][1]


def test_controller_cancel_plate_reader_analysis_calls_worker_cancel(tmp_path):
    controller = _make_controller(tmp_path)
    created_workers = []

    def worker_factory(config):
        worker = _FakeWorker(config)
        created_workers.append(worker)
        return worker

    config = PlateReaderAnalysisConfig(
        experiment_dir=tmp_path,
        plate_reader_file=tmp_path / "plate.txt",
        key_file=tmp_path / "concentration_key.csv",
    )

    assert controller.cancel_plate_reader_analysis() is False
    assert controller.start_plate_reader_analysis(config, worker_factory=worker_factory) is True
    assert controller.cancel_plate_reader_analysis() is True
    assert created_workers[0].cancelled is True
