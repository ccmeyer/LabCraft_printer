from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from PlateReaderAnalysisRunner import PlateReaderAnalysisConfig


class PlateReaderAnalysisWindow(QtWidgets.QDialog):
    """Minimal app window for running offline plate-reader analysis."""

    def __init__(self, parent=None, model=None, controller=None):
        super().__init__(parent)
        self.main_window = parent
        self.model = model if model is not None else getattr(parent, "model", None)
        self.controller = controller if controller is not None else getattr(parent, "controller", None)
        self._running = False
        self._last_payload: dict[str, object] = {}
        self._report_path: Path | None = None
        self._analysis_dir: Path | None = None

        self.setWindowTitle("Plate Reader Analysis")
        self.resize(860, 560)
        self._build_ui()
        self._connect_controller()
        self._populate_defaults()
        self._update_result_buttons()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        form_group = QtWidgets.QGroupBox("Analysis Input")
        form = QtWidgets.QFormLayout(form_group)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        self.experiment_dir_edit = QtWidgets.QLineEdit()
        self.experiment_dir_edit.setObjectName("experimentDirEdit")
        self.experiment_dir_button = QtWidgets.QPushButton("Browse...")
        self.experiment_dir_button.clicked.connect(self._browse_experiment_dir)
        self.experiment_dir_edit.textChanged.connect(self._on_experiment_dir_changed)
        form.addRow("Experiment Directory", self._path_row(self.experiment_dir_edit, self.experiment_dir_button))

        self.plate_reader_file_edit = QtWidgets.QLineEdit()
        self.plate_reader_file_edit.setObjectName("plateReaderFileEdit")
        self.plate_reader_file_button = QtWidgets.QPushButton("Browse...")
        self.plate_reader_file_button.clicked.connect(self._browse_plate_reader_file)
        form.addRow("Plate Reader Export", self._path_row(self.plate_reader_file_edit, self.plate_reader_file_button))

        self.key_file_edit = QtWidgets.QLineEdit()
        self.key_file_edit.setObjectName("keyFileEdit")
        self.key_file_button = QtWidgets.QPushButton("Browse...")
        self.key_file_button.clicked.connect(self._browse_key_file)
        form.addRow("Concentration Key", self._path_row(self.key_file_edit, self.key_file_button))

        self.output_dir_edit = QtWidgets.QLineEdit()
        self.output_dir_edit.setObjectName("outputDirEdit")
        self.output_dir_edit.setPlaceholderText("Default: <experiment_dir>/plate_reader_analysis")
        self.output_dir_button = QtWidgets.QPushButton("Browse...")
        self.output_dir_button.clicked.connect(self._browse_output_dir)
        form.addRow("Output Directory", self._path_row(self.output_dir_edit, self.output_dir_button))

        self.endpoint_last_n_spin = QtWidgets.QSpinBox()
        self.endpoint_last_n_spin.setObjectName("endpointLastNSpin")
        self.endpoint_last_n_spin.setRange(1, 100)
        self.endpoint_last_n_spin.setValue(3)
        form.addRow("Endpoint Last N", self.endpoint_last_n_spin)

        root.addWidget(form_group)

        status_row = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("Idle")
        self.status_label.setObjectName("plateReaderAnalysisStatusLabel")
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.status_label, 1)
        root.addLayout(status_row)

        self.log_output = QtWidgets.QPlainTextEdit()
        self.log_output.setObjectName("plateReaderAnalysisLog")
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(220)
        root.addWidget(self.log_output, 1)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        self.run_button = QtWidgets.QPushButton("Run Analysis")
        self.run_button.setObjectName("runPlateReaderAnalysisButton")
        self.run_button.clicked.connect(self._on_run_clicked)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setObjectName("cancelPlateReaderAnalysisButton")
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        self.cancel_button.setEnabled(False)
        self.open_report_button = QtWidgets.QPushButton("Open Report")
        self.open_report_button.setObjectName("openPlateReaderReportButton")
        self.open_report_button.clicked.connect(self._open_report)
        self.open_folder_button = QtWidgets.QPushButton("Open Analysis Folder")
        self.open_folder_button.setObjectName("openPlateReaderAnalysisFolderButton")
        self.open_folder_button.clicked.connect(self._open_analysis_folder)
        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_row.addWidget(self.run_button)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.open_report_button)
        button_row.addWidget(self.open_folder_button)
        button_row.addWidget(self.close_button)
        root.addLayout(button_row)

    @staticmethod
    def _path_row(edit: QtWidgets.QLineEdit, button: QtWidgets.QPushButton) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        return row

    def _connect_controller(self):
        if self.controller is None:
            return
        for signal_name, slot in (
            ("plate_reader_analysis_stage", self._on_stage),
            ("plate_reader_analysis_output", self._on_output),
            ("plate_reader_analysis_finished", self._on_finished),
        ):
            signal = getattr(self.controller, signal_name, None)
            connect = getattr(signal, "connect", None)
            if callable(connect):
                connect(slot)

    def _populate_defaults(self):
        experiment_model = getattr(self.model, "experiment_model", self.model)
        experiment_dir = getattr(experiment_model, "experiment_dir_path", None)
        key_file = getattr(experiment_model, "concentration_key_file_path", None)
        if experiment_dir:
            self.experiment_dir_edit.setText(str(experiment_dir))
        if key_file:
            self.key_file_edit.setText(str(key_file))
        elif experiment_dir:
            self.key_file_edit.setText(str(Path(str(experiment_dir)) / "concentration_key.csv"))

    def _on_experiment_dir_changed(self, text: str):
        if self.key_file_edit.text().strip():
            return
        if str(text).strip():
            self.key_file_edit.setText(str(Path(str(text).strip()) / "concentration_key.csv"))

    def _browse_experiment_dir(self):
        start_dir = self.experiment_dir_edit.text().strip() or str(Path.home())
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Experiment Directory", start_dir)
        if path:
            self.experiment_dir_edit.setText(path)

    def _browse_plate_reader_file(self):
        start_dir = self.experiment_dir_edit.text().strip() or str(Path.home())
        path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Plate Reader Export",
            start_dir,
            "Plate reader exports (*.txt *.csv *.tsv);;All files (*)",
        )
        if path:
            self.plate_reader_file_edit.setText(path)

    def _browse_key_file(self):
        start_dir = self.experiment_dir_edit.text().strip() or str(Path.home())
        path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Concentration Key",
            start_dir,
            "CSV files (*.csv);;All files (*)",
        )
        if path:
            self.key_file_edit.setText(path)

    def _browse_output_dir(self):
        start_dir = self.output_dir_edit.text().strip() or self.experiment_dir_edit.text().strip() or str(Path.home())
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Analysis Output Directory", start_dir)
        if path:
            self.output_dir_edit.setText(path)

    def _build_config(self) -> PlateReaderAnalysisConfig:
        experiment_dir = Path(self.experiment_dir_edit.text().strip())
        plate_reader_file = Path(self.plate_reader_file_edit.text().strip())
        key_file = Path(self.key_file_edit.text().strip())
        output_text = self.output_dir_edit.text().strip()

        if not experiment_dir.exists() or not experiment_dir.is_dir():
            raise ValueError(f"Experiment directory does not exist or is not a directory: {experiment_dir}")
        if not plate_reader_file.exists() or not plate_reader_file.is_file():
            raise ValueError(f"Plate-reader file does not exist or is not a file: {plate_reader_file}")
        if not key_file.exists() or not key_file.is_file():
            raise ValueError(f"Concentration key does not exist or is not a file: {key_file}")

        return PlateReaderAnalysisConfig(
            experiment_dir=experiment_dir,
            plate_reader_file=plate_reader_file,
            key_file=key_file,
            output_dir=Path(output_text) if output_text else None,
            endpoint_last_n=int(self.endpoint_last_n_spin.value()),
        )

    @QtCore.Slot()
    def _on_run_clicked(self):
        starter = getattr(self.controller, "start_plate_reader_analysis", None)
        if not callable(starter):
            self._set_status("Plate-reader analysis is not available from this controller.")
            self._append_log("Plate-reader analysis is not available from this controller.")
            return
        try:
            config = self._build_config()
        except ValueError as exc:
            self._set_status("Invalid input")
            self._append_log(str(exc))
            return

        self.log_output.clear()
        self._last_payload = {}
        self._report_path = None
        self._analysis_dir = None
        self._update_result_buttons()
        self._set_running(True)
        self._set_status("Starting plate-reader analysis")
        if not starter(config):
            self._append_log("A plate-reader analysis run is already active.")
            self._set_status("Failed")
            self._set_running(False)

    @QtCore.Slot()
    def _on_cancel_clicked(self):
        cancel = getattr(self.controller, "cancel_plate_reader_analysis", None)
        if callable(cancel):
            cancel()
            self._append_log("Cancel requested.")

    @QtCore.Slot(str)
    def _on_stage(self, message: str):
        self._set_status(str(message or ""))

    @QtCore.Slot(str)
    def _on_output(self, message: str):
        self._append_log(str(message or ""))

    @QtCore.Slot(bool, str, object)
    def _on_finished(self, ok: bool, message: str, payload: object):
        self._set_running(False)
        self._set_status("Finished" if ok else "Failed")
        self._append_log(str(message or ""))
        self._last_payload = dict(payload) if isinstance(payload, dict) else {}
        if ok:
            report = self._last_payload.get("report_html")
            output_dir = self._last_payload.get("output_dir")
            self._report_path = Path(str(report)) if report else None
            self._analysis_dir = Path(str(output_dir)) if output_dir else None
        else:
            self._report_path = None
            self._analysis_dir = None
        self._update_result_buttons()

    def _set_status(self, text: str):
        self.status_label.setText(str(text or ""))

    def _append_log(self, text: str):
        if text:
            self.log_output.appendPlainText(text)

    def _set_running(self, running: bool):
        self._running = bool(running)
        for widget in (
            self.experiment_dir_edit,
            self.experiment_dir_button,
            self.plate_reader_file_edit,
            self.plate_reader_file_button,
            self.key_file_edit,
            self.key_file_button,
            self.output_dir_edit,
            self.output_dir_button,
            self.endpoint_last_n_spin,
        ):
            widget.setEnabled(not self._running)
        self.run_button.setEnabled(not self._running)
        self.cancel_button.setEnabled(self._running)
        self.close_button.setEnabled(not self._running)
        self._update_result_buttons()

    def _update_result_buttons(self):
        report_ok = self._report_path is not None and self._report_path.exists()
        folder_ok = self._analysis_dir is not None and self._analysis_dir.exists()
        self.open_report_button.setEnabled((not self._running) and report_ok)
        self.open_folder_button.setEnabled((not self._running) and folder_ok)

    @QtCore.Slot()
    def _open_report(self):
        if self._report_path is None or not self._report_path.exists():
            self._append_log("Analysis report does not exist yet.")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self._report_path.resolve())))

    @QtCore.Slot()
    def _open_analysis_folder(self):
        if self._analysis_dir is None or not self._analysis_dir.exists():
            self._append_log("Analysis folder does not exist yet.")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self._analysis_dir.resolve())))

    def closeEvent(self, event):
        if self._running:
            self._append_log("Cancel the active analysis before closing this window.")
            event.ignore()
            return
        super().closeEvent(event)
