from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from PlateReaderAnalysisExport import PlateReaderAnalysisExportConfig, export_plate_reader_analysis_package
from PlateReaderAnalysisRunner import PlateReaderAnalysisConfig, PlateReaderAnalysisPreviewResult


class PlateReaderAnalysisWindow(QtWidgets.QDialog):
    """Minimal app window for running offline plate-reader analysis."""

    def __init__(self, parent=None, model=None, controller=None):
        super().__init__(parent)
        self.main_window = parent
        self.model = model if model is not None else getattr(parent, "model", None)
        self.controller = controller if controller is not None else getattr(parent, "controller", None)
        self._running = False
        self._previewing = False
        self._preview_valid = False
        self._preview_signature: tuple[str, str, str, str, int] | None = None
        self._pending_preview_signature: tuple[str, str, str, str, int] | None = None
        self._last_preview_payload: dict[str, object] = {}
        self._last_payload: dict[str, object] = {}
        self._last_manifest: dict[str, object] = {}
        self._manifest_path: Path | None = None
        self._report_path: Path | None = None
        self._analysis_dir: Path | None = None
        self._export_path: Path | None = None

        self.setWindowTitle("Plate Reader Analysis")
        self.resize(920, 760)
        self._build_ui()
        self._connect_controller()
        self._populate_defaults()
        self._mark_preview_stale()
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
        self.experiment_dir_edit.textChanged.connect(self._mark_preview_stale)
        form.addRow("Experiment Directory", self._path_row(self.experiment_dir_edit, self.experiment_dir_button))

        self.plate_reader_file_edit = QtWidgets.QLineEdit()
        self.plate_reader_file_edit.setObjectName("plateReaderFileEdit")
        self.plate_reader_file_button = QtWidgets.QPushButton("Browse...")
        self.plate_reader_file_button.clicked.connect(self._browse_plate_reader_file)
        self.plate_reader_file_edit.textChanged.connect(self._mark_preview_stale)
        form.addRow("Plate Reader Export", self._path_row(self.plate_reader_file_edit, self.plate_reader_file_button))

        self.key_file_edit = QtWidgets.QLineEdit()
        self.key_file_edit.setObjectName("keyFileEdit")
        self.key_file_button = QtWidgets.QPushButton("Browse...")
        self.key_file_button.clicked.connect(self._browse_key_file)
        self.key_file_edit.textChanged.connect(self._mark_preview_stale)
        form.addRow("Concentration Key", self._path_row(self.key_file_edit, self.key_file_button))

        self.output_dir_edit = QtWidgets.QLineEdit()
        self.output_dir_edit.setObjectName("outputDirEdit")
        self.output_dir_edit.setPlaceholderText("Default: <experiment_dir>/plate_reader_analysis")
        self.output_dir_button = QtWidgets.QPushButton("Browse...")
        self.output_dir_button.clicked.connect(self._browse_output_dir)
        self.output_dir_edit.textChanged.connect(self._mark_preview_stale)
        form.addRow("Output Directory", self._path_row(self.output_dir_edit, self.output_dir_button))

        self.endpoint_last_n_spin = QtWidgets.QSpinBox()
        self.endpoint_last_n_spin.setObjectName("endpointLastNSpin")
        self.endpoint_last_n_spin.setRange(1, 100)
        self.endpoint_last_n_spin.setValue(3)
        self.endpoint_last_n_spin.valueChanged.connect(self._mark_preview_stale)
        form.addRow("Endpoint Last N", self.endpoint_last_n_spin)

        root.addWidget(form_group)

        preview_group = QtWidgets.QGroupBox("Validation Preview")
        preview_layout = QtWidgets.QVBoxLayout(preview_group)
        self.preview_table = QtWidgets.QTableWidget(0, 2)
        self.preview_table.setObjectName("plateReaderPreviewTable")
        self.preview_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.preview_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.preview_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.preview_table.setMinimumHeight(150)
        preview_layout.addWidget(self.preview_table)

        self.preview_messages = QtWidgets.QPlainTextEdit()
        self.preview_messages.setObjectName("plateReaderPreviewMessages")
        self.preview_messages.setReadOnly(True)
        self.preview_messages.setMaximumHeight(95)
        preview_layout.addWidget(self.preview_messages)
        root.addWidget(preview_group)

        result_group = QtWidgets.QGroupBox("Result Summary")
        result_group.setObjectName("plateReaderResultSummaryGroup")
        result_layout = QtWidgets.QVBoxLayout(result_group)

        self.result_summary_table = QtWidgets.QTableWidget(0, 2)
        self.result_summary_table.setObjectName("plateReaderResultSummaryTable")
        self.result_summary_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.result_summary_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.result_summary_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.result_summary_table.verticalHeader().setVisible(False)
        self.result_summary_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.result_summary_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.result_summary_table.setMaximumHeight(150)
        result_layout.addWidget(self.result_summary_table)

        self.result_outputs_table = QtWidgets.QTableWidget(0, 5)
        self.result_outputs_table.setObjectName("plateReaderResultOutputsTable")
        self.result_outputs_table.setHorizontalHeaderLabels(["Category", "CSVs", "PNGs", "Other", "Total"])
        self.result_outputs_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.result_outputs_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.result_outputs_table.verticalHeader().setVisible(False)
        self.result_outputs_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in range(1, 5):
            self.result_outputs_table.horizontalHeader().setSectionResizeMode(
                column,
                QtWidgets.QHeaderView.ResizeToContents,
            )
        self.result_outputs_table.setMaximumHeight(115)
        result_layout.addWidget(self.result_outputs_table)

        self.result_messages = QtWidgets.QPlainTextEdit()
        self.result_messages.setObjectName("plateReaderResultMessages")
        self.result_messages.setReadOnly(True)
        self.result_messages.setMaximumHeight(80)
        result_layout.addWidget(self.result_messages)
        root.addWidget(result_group)

        status_row = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("Idle")
        self.status_label.setObjectName("plateReaderAnalysisStatusLabel")
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.status_label, 1)
        root.addLayout(status_row)

        self.log_output = QtWidgets.QPlainTextEdit()
        self.log_output.setObjectName("plateReaderAnalysisLog")
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(150)
        root.addWidget(self.log_output, 1)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        self.validate_preview_button = QtWidgets.QPushButton("Validate Preview")
        self.validate_preview_button.setObjectName("validatePlateReaderPreviewButton")
        self.validate_preview_button.clicked.connect(self._on_validate_preview_clicked)
        self.run_button = QtWidgets.QPushButton("Run Analysis")
        self.run_button.setObjectName("runPlateReaderAnalysisButton")
        self.run_button.clicked.connect(self._on_run_clicked)
        self.run_button.setEnabled(False)
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
        self.export_button = QtWidgets.QPushButton("Export Package...")
        self.export_button.setObjectName("exportPlateReaderAnalysisPackageButton")
        self.export_button.clicked.connect(self._on_export_clicked)
        self.open_export_folder_button = QtWidgets.QPushButton("Open Export Folder")
        self.open_export_folder_button.setObjectName("openPlateReaderAnalysisExportFolderButton")
        self.open_export_folder_button.clicked.connect(self._open_export_folder)
        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_row.addWidget(self.validate_preview_button)
        button_row.addWidget(self.run_button)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.open_report_button)
        button_row.addWidget(self.open_folder_button)
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.open_export_folder_button)
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
            ("plate_reader_analysis_preview_stage", self._on_preview_stage),
            ("plate_reader_analysis_preview_finished", self._on_preview_finished),
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

    def _build_config(self, *, validate_paths: bool = True) -> PlateReaderAnalysisConfig:
        experiment_dir = Path(self.experiment_dir_edit.text().strip())
        plate_reader_file = Path(self.plate_reader_file_edit.text().strip())
        key_file = Path(self.key_file_edit.text().strip())
        output_text = self.output_dir_edit.text().strip()

        if validate_paths:
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

    @staticmethod
    def _config_signature(config: PlateReaderAnalysisConfig) -> tuple[str, str, str, str, int]:
        return (
            str(Path(config.experiment_dir)),
            str(Path(config.plate_reader_file)),
            str(Path(config.key_file)) if config.key_file is not None else "",
            str(Path(config.output_dir)) if config.output_dir is not None else "",
            int(config.endpoint_last_n),
        )

    @QtCore.Slot()
    def _on_validate_preview_clicked(self):
        previewer = getattr(self.controller, "start_plate_reader_analysis_preview", None)
        if not callable(previewer):
            self._set_status("Plate-reader validation preview is not available from this controller.")
            self._set_preview_messages(
                ["Plate-reader validation preview is not available from this controller."],
                [],
            )
            return

        config = self._build_config(validate_paths=False)
        self._pending_preview_signature = self._config_signature(config)
        self._preview_valid = False
        self._preview_signature = None
        self._last_preview_payload = {}
        self._last_payload = {}
        self._report_path = None
        self._analysis_dir = None
        self._export_path = None
        self._clear_result_summary("Validation preview running...")
        self._set_previewing(True)
        self._set_status("Validating preview...")
        self.preview_messages.setPlainText("Validating preview...")
        if not previewer(config):
            self._set_status("Preview failed")
            self._set_previewing(False)
            if not self.preview_messages.toPlainText().strip():
                self._set_preview_messages(["A plate-reader analysis preview is already active."], [])

    @QtCore.Slot(str)
    def _on_preview_stage(self, message: str):
        self._set_status(str(message or ""))

    @QtCore.Slot(bool, str, object)
    def _on_preview_finished(self, ok: bool, message: str, payload: object):
        self._set_previewing(False)
        preview = self._normalize_preview_payload(ok, message, payload)
        self._last_preview_payload = preview
        errors = [str(item) for item in preview.get("errors", []) or []]
        warnings = [str(item) for item in preview.get("warnings", []) or []]
        self._preview_valid = bool(preview.get("ok")) and not errors
        self._preview_signature = self._pending_preview_signature if self._preview_valid else None
        self._pending_preview_signature = None
        self._set_status("Preview valid" if self._preview_valid else "Preview failed")
        self._populate_preview_table(preview)
        self._set_preview_messages(errors, warnings, success_message=str(preview.get("message") or ""))
        self._update_run_enabled()

    def _normalize_preview_payload(self, ok: bool, message: str, payload: object) -> dict[str, object]:
        if isinstance(payload, PlateReaderAnalysisPreviewResult):
            return payload.to_payload()
        if isinstance(payload, dict):
            result = dict(payload)
            result.setdefault("ok", bool(ok))
            result.setdefault("message", str(message or ""))
            result.setdefault("errors", [])
            result.setdefault("warnings", [])
            result.setdefault("summary", {})
            result.setdefault("paths", {})
            return result
        return {
            "ok": bool(ok),
            "message": str(message or ""),
            "errors": [] if ok else [str(message or "Preview failed.")],
            "warnings": [],
            "summary": {},
            "paths": {},
        }

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
        if not self._preview_valid or self._preview_signature != self._config_signature(config):
            self._set_status("Validate preview before running")
            self._append_log("Validate the current inputs before running analysis.")
            self._update_run_enabled()
            return

        self.log_output.clear()
        self._last_payload = {}
        self._report_path = None
        self._analysis_dir = None
        self._export_path = None
        self._clear_result_summary("Analysis running...")
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
            self._load_result_manifest(self._last_payload)
        else:
            self._report_path = None
            self._analysis_dir = None
            self._export_path = None
            self._clear_result_summary("Analysis did not finish successfully.")
        self._update_result_buttons()

    def _set_status(self, text: str):
        self.status_label.setText(str(text or ""))

    def _append_log(self, text: str):
        if text:
            self.log_output.appendPlainText(text)

    def _format_preview_list(self, values: object, *, limit: int = 8) -> str:
        if not isinstance(values, (list, tuple)):
            return str(values) if values is not None else "(none)"
        cleaned = [str(value) for value in values if str(value).strip()]
        if not cleaned:
            return "(none)"
        suffix = f", ... ({len(cleaned) - limit} more)" if len(cleaned) > limit else ""
        return ", ".join(cleaned[:limit]) + suffix

    def _format_preview_count_with_list(self, count: object, values: object) -> str:
        try:
            count_text = str(int(count))
        except (TypeError, ValueError):
            count_text = str(count)
        value_text = self._format_preview_list(values)
        return count_text if value_text == "(none)" else f"{count_text}: {value_text}"

    def _clear_result_summary(self, message: str = "Run analysis to see result summary."):
        self._last_manifest = {}
        self._manifest_path = None
        if hasattr(self, "result_summary_table"):
            self.result_summary_table.setRowCount(0)
        if hasattr(self, "result_outputs_table"):
            self.result_outputs_table.setRowCount(0)
        if hasattr(self, "result_messages"):
            self.result_messages.setPlainText(str(message or ""))

    def _load_result_manifest(self, payload: dict[str, object]):
        manifest_value = payload.get("manifest_json")
        if not manifest_value:
            self._clear_result_summary("Could not load result summary: analysis manifest path was not returned.")
            return

        manifest_path = Path(str(manifest_value))
        if not manifest_path.exists():
            self._clear_result_summary(f"Could not load result summary: manifest does not exist: {manifest_path}")
            return

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._clear_result_summary(f"Could not load result summary: invalid manifest JSON: {exc}")
            return

        if not isinstance(manifest, dict):
            self._clear_result_summary("Could not load result summary: manifest root is not an object.")
            return
        if manifest.get("schema_version") != "plate_reader_analysis_manifest_v1":
            schema = manifest.get("schema_version", "(missing)")
            self._clear_result_summary(f"Could not load result summary: unsupported manifest schema: {schema}")
            return

        self._last_manifest = manifest
        self._manifest_path = manifest_path
        self._populate_result_summary(manifest)

    def _populate_result_summary(self, manifest: dict[str, object]):
        inputs = manifest.get("inputs") if isinstance(manifest.get("inputs"), dict) else {}
        dataset = manifest.get("dataset") if isinstance(manifest.get("dataset"), dict) else {}
        outliers = manifest.get("outliers") if isinstance(manifest.get("outliers"), dict) else {}
        outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), list) else []
        warnings = [str(warning) for warning in manifest.get("warnings", []) or []]
        data_type = "Timecourse" if dataset.get("has_timecourse_data") else "Endpoint only"
        rows = [
            ("Merged CSV", inputs.get("merged_csv", "")),
            ("Output directory", inputs.get("output_dir", "")),
            ("Measured wells", dataset.get("measured_well_count", "")),
            ("Keyed wells", dataset.get("keyed_well_count", "")),
            ("Endpoint rows", dataset.get("endpoint_rows", "")),
            ("Composition rows", dataset.get("composition_rows", "")),
            ("Fluorophores", self._format_preview_list(dataset.get("fluorophores", []))),
            ("Condition columns", self._format_preview_list(dataset.get("condition_columns", []))),
            ("Data type", data_type),
            ("Endpoint outliers", outliers.get("final_outlier_count", "")),
            ("Warnings", len(warnings)),
        ]

        self.result_summary_table.setRowCount(len(rows))
        for row_index, (label, value) in enumerate(rows):
            label_item = QtWidgets.QTableWidgetItem(str(label))
            value_item = QtWidgets.QTableWidgetItem(str(value))
            label_item.setFlags(QtCore.Qt.ItemIsEnabled)
            value_item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.result_summary_table.setItem(row_index, 0, label_item)
            self.result_summary_table.setItem(row_index, 1, value_item)

        self._populate_result_outputs_table(outputs)
        if warnings:
            lines = ["Warnings:"]
            lines.extend(f"- {warning}" for warning in warnings)
            self.result_messages.setPlainText("\n".join(lines))
        else:
            self.result_messages.setPlainText("Result summary loaded from analysis_manifest.json.")

    def _populate_result_outputs_table(self, outputs: list[object]):
        counts: dict[str, dict[str, int]] = defaultdict(lambda: {"csv": 0, "png": 0, "other": 0, "total": 0})
        for output in outputs:
            if not isinstance(output, dict):
                continue
            category = str(output.get("category") or "uncategorized")
            kind = str(output.get("kind") or "").lower()
            path_suffix = Path(str(output.get("path") or "")).suffix.lower()
            if kind == "csv" or path_suffix == ".csv":
                bucket = "csv"
            elif kind == "png" or path_suffix == ".png":
                bucket = "png"
            else:
                bucket = "other"
            counts[category][bucket] += 1
            counts[category]["total"] += 1

        categories = sorted(counts)
        self.result_outputs_table.setRowCount(len(categories))
        for row_index, category in enumerate(categories):
            values = [
                category,
                counts[category]["csv"],
                counts[category]["png"],
                counts[category]["other"],
                counts[category]["total"],
            ]
            for column_index, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                self.result_outputs_table.setItem(row_index, column_index, item)

    def _populate_preview_table(self, preview: dict[str, object]):
        summary = preview.get("summary") if isinstance(preview.get("summary"), dict) else {}
        paths = preview.get("paths") if isinstance(preview.get("paths"), dict) else {}
        if not summary and not paths:
            self.preview_table.setRowCount(0)
            return

        time_min = summary.get("time_minutes_min")
        time_max = summary.get("time_minutes_max")
        if time_min is None or time_max is None:
            time_range = "(unknown)"
        else:
            time_range = f"{float(time_min):.2f} to {float(time_max):.2f} min"
        data_type = "Timecourse" if summary.get("has_timecourse_data") else "Endpoint only"
        rows = [
            ("Measured wells", summary.get("measured_well_count", "")),
            ("Key wells", summary.get("key_well_count", "")),
            (
                "Keyed measured wells",
                self._format_preview_count_with_list(
                    summary.get("keyed_measured_well_count", ""),
                    summary.get("keyed_measured_wells", []),
                ),
            ),
            (
                "Unkeyed measured wells",
                self._format_preview_count_with_list(
                    summary.get("unkeyed_measured_well_count", ""),
                    summary.get("unkeyed_measured_wells", []),
                ),
            ),
            (
                "Missing key wells",
                self._format_preview_count_with_list(
                    summary.get("missing_key_well_count", ""),
                    summary.get("missing_key_wells", []),
                ),
            ),
            ("Fluorophores", self._format_preview_list(summary.get("fluorophores", []))),
            ("Timepoints", summary.get("timepoint_count", "")),
            ("Time range", time_range),
            ("Data type", data_type),
            ("Condition columns", self._format_preview_list(summary.get("condition_columns", []))),
            ("Compositions", summary.get("composition_count", "")),
            ("Dropped timepoints", summary.get("dropped_timepoint_count", "")),
            ("Merged CSV", paths.get("merged_csv", "")),
            ("Analysis output", paths.get("output_dir", "")),
            ("Report", paths.get("report_html", "")),
        ]

        self.preview_table.setRowCount(len(rows))
        for row_index, (label, value) in enumerate(rows):
            label_item = QtWidgets.QTableWidgetItem(str(label))
            value_item = QtWidgets.QTableWidgetItem(str(value))
            label_item.setFlags(QtCore.Qt.ItemIsEnabled)
            value_item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.preview_table.setItem(row_index, 0, label_item)
            self.preview_table.setItem(row_index, 1, value_item)

    def _set_preview_messages(self, errors: list[str], warnings: list[str], *, success_message: str = ""):
        lines: list[str] = []
        if errors:
            lines.append("Errors:")
            lines.extend(f"- {error}" for error in errors)
        if warnings:
            if lines:
                lines.append("")
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in warnings)
        if not lines:
            lines.append(success_message or "Preview passed with no warnings.")
        self.preview_messages.setPlainText("\n".join(lines))

    def _mark_preview_stale(self, *_args):
        if self._previewing or self._running:
            return
        had_preview = self._preview_valid or bool(self._last_preview_payload)
        self._preview_valid = False
        self._preview_signature = None
        self._pending_preview_signature = None
        self._last_preview_payload = {}
        self._last_payload = {}
        self._report_path = None
        self._analysis_dir = None
        self._export_path = None
        self._clear_result_summary()
        if had_preview:
            self._set_status("Preview stale; validate before running.")
            self.preview_messages.setPlainText("Inputs changed. Validate preview before running analysis.")
        self._update_run_enabled()
        self._update_result_buttons()

    def _update_run_enabled(self):
        try:
            current_signature = self._config_signature(self._build_config(validate_paths=False))
        except Exception:
            current_signature = None
        self.run_button.setEnabled(
            (not self._running)
            and (not self._previewing)
            and self._preview_valid
            and self._preview_signature is not None
            and self._preview_signature == current_signature
        )

    def _set_previewing(self, previewing: bool):
        self._previewing = bool(previewing)
        self._update_input_enabled()
        self.validate_preview_button.setEnabled(not self._previewing and not self._running)
        self.cancel_button.setEnabled(self._running)
        self.close_button.setEnabled(not self._running and not self._previewing)
        self._update_run_enabled()
        self._update_result_buttons()

    def _update_input_enabled(self):
        enabled = not self._running and not self._previewing
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
            widget.setEnabled(enabled)

    def _set_running(self, running: bool):
        self._running = bool(running)
        self._update_input_enabled()
        self.validate_preview_button.setEnabled(not self._running and not self._previewing)
        self._update_run_enabled()
        self.cancel_button.setEnabled(self._running)
        self.close_button.setEnabled(not self._running and not self._previewing)
        self._update_result_buttons()

    def _update_result_buttons(self):
        report_ok = self._report_path is not None and self._report_path.exists()
        folder_ok = self._analysis_dir is not None and self._analysis_dir.exists()
        export_ok = folder_ok and bool(self._last_payload)
        export_folder_ok = self._export_path is not None and self._export_path.exists()
        self.open_report_button.setEnabled((not self._running) and (not self._previewing) and report_ok)
        self.open_folder_button.setEnabled((not self._running) and (not self._previewing) and folder_ok)
        self.export_button.setEnabled((not self._running) and (not self._previewing) and export_ok)
        self.open_export_folder_button.setEnabled((not self._running) and (not self._previewing) and export_folder_ok)

    def _default_export_path(self) -> Path:
        experiment_dir = Path(str(self._last_payload.get("experiment_dir") or "")) if self._last_payload else Path()
        if not str(experiment_dir) or experiment_dir.name == "":
            experiment_dir = self._analysis_dir.parent if self._analysis_dir is not None else Path.home()
        downloads = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.DownloadLocation)
        base_dir = Path(downloads) if downloads else experiment_dir
        stem_source = experiment_dir.name or "plate_reader_analysis"
        safe_stem = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in stem_source).strip("_")
        safe_stem = safe_stem or "plate_reader_analysis"
        return base_dir / f"{safe_stem}_plate_reader_analysis_export.zip"

    @QtCore.Slot()
    def _on_export_clicked(self):
        if self._analysis_dir is None or not self._analysis_dir.exists():
            self._set_status("Export failed")
            self._append_log("Analysis folder does not exist yet.")
            return
        path, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Plate Reader Analysis Package",
            str(self._default_export_path()),
            "ZIP files (*.zip);;All files (*)",
        )
        if not path:
            return
        try:
            result = export_plate_reader_analysis_package(
                PlateReaderAnalysisExportConfig(
                    analysis_payload=dict(self._last_payload),
                    destination=Path(path),
                    created_by="LabCraft app",
                )
            )
        except Exception as exc:
            self._set_status("Export failed")
            self._append_log(f"Failed to export plate-reader analysis package: {exc}")
            self._export_path = None
            self._update_result_buttons()
            return

        self._export_path = Path(str(result.get("destination") or path))
        missing = result.get("missing_files") or []
        self._set_status("Exported analysis package")
        self._append_log(f"Exported plate-reader analysis package: {self._export_path}")
        if missing:
            self._append_log("Export completed with missing optional files: " + ", ".join(str(item) for item in missing))
        self._update_result_buttons()

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

    @QtCore.Slot()
    def _open_export_folder(self):
        if self._export_path is None or not self._export_path.exists():
            self._append_log("Export package does not exist yet.")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self._export_path.parent.resolve())))

    def closeEvent(self, event):
        if self._running or self._previewing:
            self._append_log("Wait for the active validation or cancel the active analysis before closing this window.")
            event.ignore()
            return
        super().closeEvent(event)
