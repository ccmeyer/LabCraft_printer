from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets

import View
from Controller import Controller
from PlateReaderAnalysisRunner import PlateReaderAnalysisConfig
from PlateReaderAnalysisWindow import PlateReaderAnalysisWindow


class _WindowController(QtCore.QObject):
    plate_reader_analysis_stage = QtCore.Signal(str)
    plate_reader_analysis_output = QtCore.Signal(str)
    plate_reader_analysis_finished = QtCore.Signal(bool, str, object)

    def __init__(self, *, start_result=True):
        super().__init__()
        self.start_result = start_result
        self.started_config = None
        self.cancel_calls = 0

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
    controller._plate_reader_analysis_worker = None
    return controller


def test_window_defaults_experiment_and_key_paths_from_model(tmp_path, qapp):
    window, _controller, experiment_dir, key_file, _plate_file = _make_window(tmp_path, qapp)

    assert window.experiment_dir_edit.text() == str(experiment_dir)
    assert window.key_file_edit.text() == str(key_file)
    assert window.output_dir_edit.text() == ""
    assert window.endpoint_last_n_spin.value() == 3

    window.close()


def test_window_run_builds_expected_config_and_locks_inputs(tmp_path, qapp):
    window, controller, experiment_dir, key_file, plate_file = _make_window(tmp_path, qapp)

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


def test_window_blocks_run_when_required_paths_are_missing(tmp_path, qapp):
    window, controller, _experiment_dir, _key_file, plate_file = _make_window(tmp_path, qapp)
    plate_file.unlink()

    window._on_run_clicked()

    assert controller.started_config is None
    assert "Invalid input" in window.status_label.text()
    assert "Plate-reader file does not exist" in window.log_output.toPlainText()

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
    window, controller, *_ = _make_window(tmp_path, qapp)
    output_dir = tmp_path / "analysis"
    output_dir.mkdir()
    report = output_dir / "analysis_report.html"
    report.write_text("<html></html>", encoding="utf-8")

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
    assert "finished" in window.log_output.toPlainText()

    window.close()


def test_window_failure_restores_controls_and_keeps_result_buttons_disabled(tmp_path, qapp):
    window, controller, *_ = _make_window(tmp_path, qapp)

    window._on_run_clicked()
    controller.plate_reader_analysis_finished.emit(False, "failed", {})
    qapp.processEvents()

    assert window.status_label.text() == "Failed"
    assert window.run_button.isEnabled() is True
    assert window.cancel_button.isEnabled() is False
    assert window.open_report_button.isEnabled() is False
    assert window.open_folder_button.isEnabled() is False

    window.close()


def test_window_cancel_calls_controller_cancel(tmp_path, qapp):
    window, controller, *_ = _make_window(tmp_path, qapp)

    window._on_run_clicked()
    window._on_cancel_clicked()

    assert controller.cancel_calls == 1
    assert "Cancel requested" in window.log_output.toPlainText()

    controller.plate_reader_analysis_finished.emit(False, "canceled", {})
    window.close()


def test_window_start_rejected_by_controller_restores_idle_state(tmp_path, qapp):
    controller = _WindowController(start_result=False)
    window, controller, *_ = _make_window(tmp_path, qapp, controller=controller)

    window._on_run_clicked()

    assert window.status_label.text() == "Failed"
    assert window.run_button.isEnabled() is True
    assert window.cancel_button.isEnabled() is False
    assert "already active" in window.log_output.toPlainText()

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
