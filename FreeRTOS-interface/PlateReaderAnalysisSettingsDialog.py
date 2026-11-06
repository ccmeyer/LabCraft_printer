"""User-reviewed grouping and exclusion choices for offline analysis."""

from collections import defaultdict
from pathlib import Path

from PySide6 import QtWidgets

from tools.data_analysis.analysis_settings import expand_well_ranges, normalize_settings, settings_from_design


class PlateReaderAnalysisSettingsDialog(QtWidgets.QDialog):
    def __init__(self, settings=None, *, experiment_dir=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Analysis Grouping and Well Exclusions")
        self.resize(780, 650)
        self.experiment_dir = Path(experiment_dir) if experiment_dir else Path.home()
        self.settings = normalize_settings(settings)
        self._target_source = dict(self.settings["target_source"])
        self._source_targets = self.settings["nominal_targets"]
        layout = QtWidgets.QVBoxLayout(self)
        self.group_targets = QtWidgets.QCheckBox("Group by intended concentrations")
        self.group_targets.setObjectName("useNominalConcentrationsCheck")
        self.group_targets.setChecked(bool(self.settings["nominal_targets"]))
        layout.addWidget(self.group_targets)
        self.load_design_button = QtWidgets.QPushButton("Load targets from experiment design...")
        self.load_design_button.clicked.connect(self._load_design)
        layout.addWidget(self.load_design_button)
        self.targets_table = QtWidgets.QTableWidget(0, 2)
        self.targets_table.setObjectName("nominalConcentrationsTable")
        self.targets_table.setHorizontalHeaderLabels(["Reagent (with units)", "Intended levels, separated by commas"])
        self.targets_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        layout.addWidget(self.targets_table)
        self._set_targets(self.settings["nominal_targets"])
        target_buttons = QtWidgets.QHBoxLayout()
        for title, action in (("Add reagent", lambda: self.targets_table.insertRow(self.targets_table.rowCount())),
                              ("Remove selected reagent", lambda: self.targets_table.removeRow(self.targets_table.currentRow()))):
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(action)
            target_buttons.addWidget(button)
        layout.addLayout(target_buttons)
        form = QtWidgets.QFormLayout()
        self.tolerance_spin = QtWidgets.QDoubleSpinBox()
        self.tolerance_spin.setObjectName("nominalToleranceSpin")
        self.tolerance_spin.setRange(0, 100)
        self.tolerance_spin.setDecimals(3)
        self.tolerance_spin.setSuffix(" %")
        self.tolerance_spin.setValue(self.settings["target_tolerance_percent"])
        form.addRow("Maximum deviation from intended level", self.tolerance_spin)
        layout.addLayout(form)
        explanation = QtWidgets.QLabel("Each calculated concentration must match exactly one intended level within the tolerance. Zero targets require zero within numerical precision. Unlisted reagents retain exact calculated values.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        layout.addWidget(QtWidgets.QLabel("Exclude known invalid wells from all calculations (all times and channels):"))
        self.exclusions_table = QtWidgets.QTableWidget(0, 2)
        self.exclusions_table.setObjectName("manualWellExclusionsTable")
        self.exclusions_table.setHorizontalHeaderLabels(["Wells or ranges (e.g. N1:P4)", "Reason (required)"])
        self.exclusions_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        grouped = defaultdict(list)
        for well, reason in self.settings["excluded_wells"].items():
            grouped[reason].append(well)
        for reason, wells in grouped.items():
            self._add_rule(", ".join(wells), reason)
        if not grouped:
            self._add_rule()
        layout.addWidget(self.exclusions_table)
        exclusion_buttons = QtWidgets.QHBoxLayout()
        for title, action in (("Add exclusion rule", lambda: self._add_rule()),
                              ("Remove selected rule", lambda: self.exclusions_table.removeRow(self.exclusions_table.currentRow()))):
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(action)
            exclusion_buttons.addWidget(button)
        layout.addLayout(exclusion_buttons)
        note = QtWidgets.QLabel("Applied choices are saved with the experiment when analysis runs and included in reports and exports. Raw measurements are retained.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error_label = QtWidgets.QLabel()
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Apply settings")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.group_targets.toggled.connect(self._update_enabled)
        self._update_enabled()

    def _update_enabled(self):
        self.targets_table.setEnabled(self.group_targets.isChecked())
        self.tolerance_spin.setEnabled(self.group_targets.isChecked())

    def _set_targets(self, targets):
        self.targets_table.setRowCount(len(targets))
        for row, (column, levels) in enumerate(targets.items()):
            self.targets_table.setItem(row, 0, QtWidgets.QTableWidgetItem(column))
            self.targets_table.setItem(row, 1, QtWidgets.QTableWidgetItem(", ".join(f"{value:g}" for value in levels)))

    def _add_rule(self, wells="", reason=""):
        row = self.exclusions_table.rowCount()
        self.exclusions_table.insertRow(row)
        self.exclusions_table.setItem(row, 0, QtWidgets.QTableWidgetItem(wells))
        self.exclusions_table.setItem(row, 1, QtWidgets.QTableWidgetItem(reason))

    def _load_design(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Experiment Design", str(self.experiment_dir / "experiment_design.json"), "JSON files (*.json)")
        if not path:
            return
        try:
            settings = settings_from_design(path)
            self._target_source = settings["target_source"]
            self._source_targets = settings["nominal_targets"]
            self._set_targets(self._source_targets)
            self.group_targets.setChecked(True)
            self.error_label.clear()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error_label.setText(str(exc))

    @staticmethod
    def _cell(table, row, column):
        item = table.item(row, column)
        return item.text().strip() if item else ""

    def collect_settings(self):
        targets = {}
        if self.group_targets.isChecked():
            for row in range(self.targets_table.rowCount()):
                column = self._cell(self.targets_table, row, 0)
                text = self._cell(self.targets_table, row, 1)
                if not column and not text:
                    continue
                if not column or column in targets:
                    raise ValueError("Each intended-level row needs a unique reagent name.")
                targets[column] = [float(value.strip()) for value in text.split(",")]
            if not targets:
                raise ValueError("Load or enter intended concentrations, or switch to calculated concentrations.")
        exclusions = {}
        for row in range(self.exclusions_table.rowCount()):
            wells = self._cell(self.exclusions_table, row, 0)
            reason = self._cell(self.exclusions_table, row, 1)
            if not wells and not reason:
                continue
            expanded = expand_well_ranges(wells)
            if not expanded or not reason:
                raise ValueError("Each exclusion rule requires wells and a reason.")
            for well in expanded:
                if well in exclusions and exclusions[well] != reason:
                    raise ValueError(f"Conflicting exclusion reasons for {well}.")
                exclusions[well] = reason
        source = self._target_source if targets == self._source_targets else {"label": "User-entered intended levels"}
        return normalize_settings({"nominal_targets": targets, "target_tolerance_percent": self.tolerance_spin.value(),
                                   "excluded_wells": exclusions, "target_source": source if targets else {}})

    def _apply(self):
        try:
            self.settings = self.collect_settings()
        except (ValueError, TypeError) as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()
