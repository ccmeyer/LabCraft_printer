from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from QualificationReports import (
    SUBSYSTEMS,
    QualificationReportIndexEntry,
    QualificationResultRow,
    artifact_paths,
    compact_report_time,
    discover_report_entries,
    load_report,
    normalize_result_rows,
)
from QualificationSuites import (
    QualificationSuiteEntry,
    QualificationTestPlanRow,
    build_test_plan_rows,
    discover_suite_entries,
    fixture_notes,
    required_fixture_ids,
)
from QualificationTiming import QualificationTimingModel, build_timing_model


PLAN_STATUS_COL = 0
PLAN_ID_COL = 1
PLAN_SUBSYSTEM_COL = 2
PLAN_TEST_COL = 3
PLAN_TYPICAL_COL = 4
PLAN_ELAPSED_COL = 5
PLAN_EVALUATES_COL = 6
PLAN_METRICS_COL = 7
PLAN_FIXTURE_COL = 8


class MachineQualificationWindow(QtWidgets.QDialog):
    """Run qualification suites and browse qualification_report_v1 artifacts."""

    def __init__(self, parent, controller, *, report_root: str | Path | None = None, monotonic_fn=None):
        super().__init__(parent)
        self.main_window = parent
        self.controller = controller
        self.report_root = Path(report_root) if report_root is not None else None
        self._monotonic_fn = monotonic_fn or time.monotonic

        self._suite_entries: list[QualificationSuiteEntry] = []
        self._current_suite: QualificationSuiteEntry | None = None
        self._test_plan_rows: list[QualificationTestPlanRow] = []
        self._plan_row_by_test_id: dict[int, int] = {}
        self._run_busy = False
        self._timing_estimates = QualificationTimingModel()
        self._plan_typical_seconds: dict[int, float | None] = {}
        self._plan_elapsed_seconds: dict[int, float] = {}
        self._run_started_monotonic: float | None = None
        self._run_finished_monotonic: float | None = None
        self._current_run_row: int | None = None
        self._current_test_started_monotonic: float | None = None

        self._entries: list[QualificationReportIndexEntry] = []
        self._current_entry: QualificationReportIndexEntry | None = None
        self._current_report: dict[str, Any] | None = None
        self._rows: list[QualificationResultRow] = []
        self.result_tables: dict[str, QtWidgets.QTableWidget] = {}

        self.setWindowTitle("Machine Qualification")
        self.setMinimumSize(1280, 820)
        self._timing_timer = QtCore.QTimer(self)
        self._timing_timer.setInterval(1000)
        self._timing_timer.timeout.connect(self._update_timing_display)
        self._build_ui()
        self._resize_near_parent_or_screen()
        self._connect_controller_signals()
        self._refresh_timing_estimates()
        self.refresh_suites()
        self.refresh_reports()

    def _resize_near_parent_or_screen(self):
        target_width = self.minimumWidth()
        target_height = self.minimumHeight()
        parent = self.parentWidget()
        if parent is not None and parent.width() > 200 and parent.height() > 200:
            target_width = max(target_width, int(parent.width() * 0.94))
            target_height = max(target_height, int(parent.height() * 0.94))
        else:
            screen = self.screen() or QtWidgets.QApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                target_width = max(target_width, int(available.width() * 0.92))
                target_height = max(target_height, int(available.height() * 0.92))
        self.resize(target_width, target_height)

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        self.main_tabs = QtWidgets.QTabWidget(self)
        root.addWidget(self.main_tabs)

        self.run_tab = QtWidgets.QWidget(self)
        self.review_tab = QtWidgets.QWidget(self)
        self.main_tabs.addTab(self.run_tab, "Run Qualification")
        self.main_tabs.addTab(self.review_tab, "Review Results")

        self._build_run_tab()
        self._build_review_tab()

    def _build_run_tab(self):
        layout = QtWidgets.QVBoxLayout(self.run_tab)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self.run_tab)
        layout.addWidget(splitter)

        left = QtWidgets.QWidget(self.run_tab)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Qualification Suites")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        self.refresh_suites_button = QtWidgets.QPushButton("Refresh")
        self.refresh_suites_button.clicked.connect(self.refresh_suites)
        header.addWidget(title, stretch=1)
        header.addWidget(self.refresh_suites_button)
        left_layout.addLayout(header)

        self.suite_list = QtWidgets.QListWidget(self.run_tab)
        self.suite_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.suite_list.currentRowChanged.connect(self._load_suite_at_row)
        left_layout.addWidget(self.suite_list, stretch=1)

        self.suite_count_label = QtWidgets.QLabel("")
        self.suite_count_label.setWordWrap(True)
        left_layout.addWidget(self.suite_count_label)
        splitter.addWidget(left)

        right = QtWidgets.QWidget(self.run_tab)
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)

        self.suite_group = QtWidgets.QGroupBox("Suite Details")
        suite_grid = QtWidgets.QGridLayout(self.suite_group)
        self.suite_labels: dict[str, QtWidgets.QLabel] = {}
        fields = [
            ("Manifest", "manifest"),
            ("Profile", "profile"),
            ("Operator gated", "operator_gated"),
            ("Fixtures", "fixtures"),
            ("Description", "description"),
        ]
        for idx, (label, key) in enumerate(fields):
            name = QtWidgets.QLabel(f"{label}:")
            name.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            value = QtWidgets.QLabel("")
            value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            self.suite_labels[key] = value
            suite_grid.addWidget(name, idx, 0)
            suite_grid.addWidget(value, idx, 1)
        right_layout.addWidget(self.suite_group)

        config_group = QtWidgets.QGroupBox("Run Configuration")
        config_grid = QtWidgets.QGridLayout(config_group)
        self.machine_id_edit = QtWidgets.QLineEdit()
        self.machine_id_edit.setPlaceholderText("Use existing local identity")
        self.port_edit = QtWidgets.QLineEdit()
        self.baud_spin = QtWidgets.QSpinBox()
        self.baud_spin.setRange(1200, 3000000)
        self.baud_spin.setValue(115200)
        self.timeout_edit = QtWidgets.QLineEdit()
        self.timeout_edit.setPlaceholderText("Default")
        self.fixture_combo = QtWidgets.QComboBox()
        self.fixture_combo.currentTextChanged.connect(self._update_start_enabled)
        self.operator_prompts_check = QtWidgets.QCheckBox("Operator prompts required")
        self.operator_prompts_check.setEnabled(False)

        defaults = [
            ("Machine ID", self.machine_id_edit),
            ("Port", self.port_edit),
            ("Baud", self.baud_spin),
            ("Timeout ms", self.timeout_edit),
            ("Fixture", self.fixture_combo),
            ("", self.operator_prompts_check),
        ]
        for idx, (label, widget) in enumerate(defaults):
            if label:
                config_grid.addWidget(QtWidgets.QLabel(f"{label}:"), idx // 2, (idx % 2) * 2)
            config_grid.addWidget(widget, idx // 2, (idx % 2) * 2 + 1)
        self.port_edit.textChanged.connect(self._update_start_enabled)
        self.timeout_edit.textChanged.connect(self._update_start_enabled)

        self.start_button = QtWidgets.QPushButton("Start Qualification")
        self.start_button.clicked.connect(self._on_start_clicked)
        self.run_status_label = QtWidgets.QLabel("Idle")
        self.run_status_label.setWordWrap(True)
        self.run_progress = QtWidgets.QProgressBar()
        self.run_progress.setRange(0, 1)
        self.run_progress.setValue(0)
        self.elapsed_time_label = QtWidgets.QLabel("Elapsed: 00:00")
        self.remaining_time_label = QtWidgets.QLabel("Expected remaining: unknown")
        self.typical_total_time_label = QtWidgets.QLabel("Typical total: unknown")
        config_grid.addWidget(self.run_status_label, 3, 0, 1, 2)
        config_grid.addWidget(self.run_progress, 3, 2)
        config_grid.addWidget(self.start_button, 3, 3)
        config_grid.addWidget(self.elapsed_time_label, 4, 0)
        config_grid.addWidget(self.remaining_time_label, 4, 1, 1, 2)
        config_grid.addWidget(self.typical_total_time_label, 4, 3)
        right_layout.addWidget(config_group)

        self.test_plan_table = QtWidgets.QTableWidget(0, 9, self.run_tab)
        self.test_plan_table.setHorizontalHeaderLabels(
            [
                "Status",
                "ID",
                "Subsystem",
                "Test",
                "Typical",
                "Elapsed",
                "Evaluates",
                "Key Metrics",
                "Fixture/Safety",
            ]
        )
        self.test_plan_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.test_plan_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.test_plan_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.test_plan_table.setAlternatingRowColors(True)
        self.test_plan_table.setWordWrap(True)
        self.test_plan_table.verticalHeader().setVisible(False)
        for idx in (PLAN_STATUS_COL, PLAN_ID_COL, PLAN_SUBSYSTEM_COL, PLAN_TYPICAL_COL, PLAN_ELAPSED_COL):
            self.test_plan_table.horizontalHeader().setSectionResizeMode(idx, QtWidgets.QHeaderView.ResizeToContents)
        self.test_plan_table.horizontalHeader().setSectionResizeMode(PLAN_TEST_COL, QtWidgets.QHeaderView.ResizeToContents)
        self.test_plan_table.horizontalHeader().setSectionResizeMode(PLAN_EVALUATES_COL, QtWidgets.QHeaderView.Stretch)
        self.test_plan_table.horizontalHeader().setSectionResizeMode(PLAN_METRICS_COL, QtWidgets.QHeaderView.Stretch)
        self.test_plan_table.horizontalHeader().setSectionResizeMode(PLAN_FIXTURE_COL, QtWidgets.QHeaderView.Stretch)
        right_layout.addWidget(self.test_plan_table, stretch=1)

        self.run_log = QtWidgets.QPlainTextEdit(self.run_tab)
        self.run_log.setReadOnly(True)
        self.run_log.setMaximumBlockCount(1000)
        self.run_log.setMaximumHeight(140)
        right_layout.addWidget(self.run_log)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 830])

    def _build_review_tab(self):
        root = QtWidgets.QVBoxLayout(self.review_tab)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self.review_tab)
        root.addWidget(splitter)

        left = QtWidgets.QWidget(self.review_tab)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Qualification Reports")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_reports)
        header.addWidget(title, stretch=1)
        header.addWidget(self.refresh_button)
        left_layout.addLayout(header)

        self.report_list = QtWidgets.QListWidget(self.review_tab)
        self.report_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.report_list.currentRowChanged.connect(self._load_report_at_row)
        left_layout.addWidget(self.report_list, stretch=1)

        self.report_count_label = QtWidgets.QLabel("")
        self.report_count_label.setWordWrap(True)
        left_layout.addWidget(self.report_count_label)
        splitter.addWidget(left)

        right = QtWidgets.QWidget(self.review_tab)
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)

        self.summary_group = QtWidgets.QGroupBox("Run Summary")
        summary_grid = QtWidgets.QGridLayout(self.summary_group)
        self.summary_labels: dict[str, QtWidgets.QLabel] = {}
        summary_fields = [
            ("Status", "status"),
            ("Machine", "machine"),
            ("Manifest", "manifest"),
            ("Profile", "profile"),
            ("Fixture", "fixture"),
            ("Started", "started"),
            ("Finished", "finished"),
            ("Counts", "counts"),
        ]
        for idx, (label, key) in enumerate(summary_fields):
            row = idx // 2
            col = (idx % 2) * 2
            name = QtWidgets.QLabel(f"{label}:")
            name.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            value = QtWidgets.QLabel("")
            value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            self.summary_labels[key] = value
            summary_grid.addWidget(name, row, col)
            summary_grid.addWidget(value, row, col + 1)
        right_layout.addWidget(self.summary_group)

        self.warnings_group = QtWidgets.QGroupBox("Warnings and Failures")
        warnings_layout = QtWidgets.QVBoxLayout(self.warnings_group)
        self.warnings_list = QtWidgets.QListWidget(self.review_tab)
        self.warnings_list.setMaximumHeight(110)
        warnings_layout.addWidget(self.warnings_list)
        right_layout.addWidget(self.warnings_group)

        self.review_tabs = QtWidgets.QTabWidget(self.review_tab)
        for subsystem in SUBSYSTEMS:
            table = self._make_result_table()
            self.result_tables[subsystem] = table
            self.review_tabs.addTab(table, subsystem)

        self.artifacts_tab = QtWidgets.QWidget(self.review_tab)
        artifacts_layout = QtWidgets.QVBoxLayout(self.artifacts_tab)
        self.artifacts_table = QtWidgets.QTableWidget(0, 3, self.review_tab)
        self.artifacts_table.setHorizontalHeaderLabels(["Artifact", "Path", "Exists"])
        self.artifacts_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.artifacts_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.artifacts_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.artifacts_table.verticalHeader().setVisible(False)
        self.artifacts_table.horizontalHeader().setStretchLastSection(False)
        self.artifacts_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.artifacts_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.artifacts_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        artifacts_layout.addWidget(self.artifacts_table)

        artifact_buttons = QtWidgets.QHBoxLayout()
        self.copy_artifact_button = QtWidgets.QPushButton("Copy Path")
        self.copy_artifact_button.clicked.connect(self._copy_selected_artifact_path)
        self.open_run_folder_button = QtWidgets.QPushButton("Open Run Folder")
        self.open_run_folder_button.clicked.connect(self._open_run_folder)
        artifact_buttons.addStretch(1)
        artifact_buttons.addWidget(self.copy_artifact_button)
        artifact_buttons.addWidget(self.open_run_folder_button)
        artifacts_layout.addLayout(artifact_buttons)
        self.review_tabs.addTab(self.artifacts_tab, "Artifacts")

        right_layout.addWidget(self.review_tabs, stretch=1)

        details_group = QtWidgets.QGroupBox("Details")
        details_layout = QtWidgets.QVBoxLayout(details_group)
        self.details_text = QtWidgets.QPlainTextEdit(self.review_tab)
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumBlockCount(2000)
        details_layout.addWidget(self.details_text)
        right_layout.addWidget(details_group, stretch=0)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 790])

    def _connect_controller_signals(self):
        connections = [
            ("qualification_stage", self._on_qualification_stage),
            ("qualification_output", self._on_qualification_output),
            ("qualification_prompt", self._on_qualification_prompt),
            ("qualification_selftest_event", self._on_selftest_event),
            ("qualification_finished", self._on_qualification_finished),
        ]
        for signal_name, slot in connections:
            signal = getattr(self.controller, signal_name, None)
            if signal is not None and hasattr(signal, "connect"):
                signal.connect(slot)

    def _make_result_table(self) -> QtWidgets.QTableWidget:
        table = QtWidgets.QTableWidget(0, 8, self.review_tab)
        table.setHorizontalHeaderLabels(
            ["ID", "Name", "Raw", "Analysis", "Category", "Domain", "Key Metrics", "Message"]
        )
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(6, QtWidgets.QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(7, QtWidgets.QHeaderView.Stretch)
        table.itemSelectionChanged.connect(lambda table=table: self._update_details_from_table(table))
        return table

    def _suite_entries_from_controller(self) -> list[QualificationSuiteEntry]:
        if hasattr(self.controller, "list_qualification_suites"):
            return list(self.controller.list_qualification_suites())
        repo_root = Path(__file__).resolve().parents[1]
        return discover_suite_entries(repo_root / "tools" / "qualification" / "manifests")

    def _refresh_timing_estimates(self):
        getter = getattr(self.controller, "qualification_timing_estimates", None)
        if callable(getter):
            try:
                self._timing_estimates = getter()
                return
            except Exception:
                pass
        root = self.report_root or Path("hil_reports")
        self._timing_estimates = build_timing_model(root)

    @QtCore.Slot()
    def refresh_suites(self):
        previous = self._current_suite.manifest_id if self._current_suite is not None else ""
        self.suite_list.blockSignals(True)
        self.suite_list.clear()
        try:
            self._suite_entries = self._suite_entries_from_controller()
            self.suite_count_label.setText(f"{len(self._suite_entries)} suite(s) found.")
        except Exception as exc:
            self._suite_entries = []
            self.suite_count_label.setText(f"Could not scan qualification suites: {exc}")

        select_row = 0
        for idx, entry in enumerate(self._suite_entries):
            item = QtWidgets.QListWidgetItem(entry.display_name)
            item.setToolTip(str(entry.manifest_path))
            self.suite_list.addItem(item)
            if entry.manifest_id == previous:
                select_row = idx
        self.suite_list.blockSignals(False)

        if self._suite_entries:
            self.suite_list.setCurrentRow(select_row)
            self._load_suite_at_row(select_row)
        else:
            self._clear_suite_display("No qualification suites found.")

    @QtCore.Slot(int)
    def _load_suite_at_row(self, row: int):
        if row < 0 or row >= len(self._suite_entries):
            return
        self._current_suite = self._suite_entries[row]
        manifest = self._current_suite.manifest
        self.suite_labels["manifest"].setText(f"{manifest.name} ({manifest.manifest_id})")
        self.suite_labels["profile"].setText(manifest.profile)
        self.suite_labels["operator_gated"].setText("yes" if manifest.requires_operator_prompts else "no")
        fixture_ids = required_fixture_ids(manifest)
        self.suite_labels["fixtures"].setText(", ".join(fixture_ids) if fixture_ids else "none")
        self.suite_labels["description"].setText(str(manifest.raw.get("description") or ""))

        self._test_plan_rows = build_test_plan_rows(manifest)
        self._populate_test_plan_table(self._test_plan_rows)
        self._populate_run_defaults(manifest, fixture_ids)
        self._reset_run_timing_state()
        self._update_timing_display()
        self._update_start_enabled()

    def _clear_suite_display(self, message: str):
        self._current_suite = None
        self._test_plan_rows = []
        for label in self.suite_labels.values():
            label.setText("")
        self.test_plan_table.setRowCount(0)
        self.run_status_label.setText(message)
        self._reset_run_timing_state()
        self._update_timing_display()
        self.start_button.setEnabled(False)

    def _populate_run_defaults(self, manifest, fixture_ids: tuple[str, ...]):
        if not self.machine_id_edit.text().strip():
            self.machine_id_edit.setText(self._default_machine_id())
        if not self.port_edit.text().strip():
            self.port_edit.setText(self._default_port())

        self.timeout_edit.setText("420000" if manifest.manifest_id == "gripper_seal_v1" else "")
        self.fixture_combo.blockSignals(True)
        self.fixture_combo.clear()
        self.fixture_combo.addItem("")
        for fixture_id in fixture_ids:
            self.fixture_combo.addItem(fixture_id)
        self.fixture_combo.blockSignals(False)
        self.operator_prompts_check.setChecked(bool(manifest.requires_operator_prompts))

    def _default_machine_id(self) -> str:
        getter = getattr(self.controller, "qualification_default_machine_id", None)
        if callable(getter):
            try:
                return str(getter() or "")
            except Exception:
                return ""
        return ""

    def _default_port(self) -> str:
        getter = getattr(self.controller, "get_machine_port", None)
        if callable(getter):
            try:
                port = str(getter() or "").strip()
                if port:
                    return port
            except Exception:
                pass
        return "/dev/ttyAMA0"

    def _populate_test_plan_table(self, rows: list[QualificationTestPlanRow]):
        self._plan_row_by_test_id = {}
        self._plan_typical_seconds = {}
        self._plan_elapsed_seconds = {}
        self.test_plan_table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            self._plan_row_by_test_id[row.test_id] = row_idx
            typical_s = self._typical_seconds_for(row.test_id)
            self._plan_typical_seconds[row.test_id] = typical_s
            values = [
                row.status,
                str(row.test_id),
                row.subsystem,
                row.name,
                self._format_duration(typical_s, unknown="unknown"),
                "",
                row.evaluates,
                row.metrics,
                row.fixture_summary,
            ]
            for col_idx, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                if col_idx == PLAN_STATUS_COL:
                    item.setData(QtCore.Qt.UserRole, row)
                self._apply_plan_status_brush(item, row.status)
                self.test_plan_table.setItem(row_idx, col_idx, item)
        self.test_plan_table.resizeRowsToContents()
        self._update_timing_display()

    def _typical_seconds_for(self, test_id: int) -> float | None:
        manifest_id = self._current_suite.manifest_id if self._current_suite is not None else ""
        estimate = self._timing_estimates.estimate_for(manifest_id, int(test_id))
        return estimate.typical_seconds if estimate is not None else None

    def _refresh_plan_timing_columns(self):
        for row_idx in range(self.test_plan_table.rowCount()):
            test_id = self._test_id_for_row(row_idx)
            if test_id is None:
                continue
            typical_s = self._typical_seconds_for(test_id)
            self._plan_typical_seconds[test_id] = typical_s
            item = self.test_plan_table.item(row_idx, PLAN_TYPICAL_COL)
            if item is None:
                item = QtWidgets.QTableWidgetItem()
                item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                self.test_plan_table.setItem(row_idx, PLAN_TYPICAL_COL, item)
            item.setText(self._format_duration(typical_s, unknown="unknown"))
            self._apply_plan_status_brush(item, self._plan_status(row_idx))
        self._update_timing_display()

    def _set_all_plan_status(self, status: str):
        for row_idx in range(self.test_plan_table.rowCount()):
            self._set_plan_status(row_idx, status)

    def _set_plan_status(self, row_idx: int, status: str):
        item = self.test_plan_table.item(row_idx, PLAN_STATUS_COL)
        if item is None:
            item = QtWidgets.QTableWidgetItem()
            self.test_plan_table.setItem(row_idx, PLAN_STATUS_COL, item)
        item.setText(status)
        for col_idx in range(self.test_plan_table.columnCount()):
            col_item = self.test_plan_table.item(row_idx, col_idx)
            if col_item is not None:
                self._apply_plan_status_brush(col_item, status)

    def _plan_status(self, row_idx: int) -> str:
        item = self.test_plan_table.item(row_idx, PLAN_STATUS_COL)
        return item.text() if item is not None else ""

    def _mark_next_queued_in_progress(self, *, after_row: int = -1):
        for row_idx in range(max(0, after_row + 1), self.test_plan_table.rowCount()):
            if self._plan_status(row_idx) == "Queued":
                self._mark_plan_row_in_progress(row_idx)
                return

    def _mark_plan_row_in_progress(self, row_idx: int):
        self._set_plan_status(row_idx, "In progress")
        if self._run_started_monotonic is None:
            return
        if self._current_run_row != row_idx:
            self._current_run_row = row_idx
            self._current_test_started_monotonic = self._monotonic_fn()
        self._set_elapsed_for_row(row_idx, 0.0)
        self._update_timing_display()

    def _begin_run_timing(self):
        now = self._monotonic_fn()
        self._run_started_monotonic = now
        self._run_finished_monotonic = None
        self._current_run_row = None
        self._current_test_started_monotonic = None
        self._plan_elapsed_seconds = {}
        for row_idx in range(self.test_plan_table.rowCount()):
            self._set_elapsed_for_row(row_idx, None)
        self._timing_timer.start()
        self._update_timing_display()

    def _stop_run_timing(self):
        self._timing_timer.stop()
        if self._run_started_monotonic is not None and self._run_finished_monotonic is None:
            self._run_finished_monotonic = self._monotonic_fn()
        self._update_timing_display()

    def _reset_run_timing_state(self):
        self._timing_timer.stop()
        self._plan_elapsed_seconds = {}
        self._run_started_monotonic = None
        self._run_finished_monotonic = None
        self._current_run_row = None
        self._current_test_started_monotonic = None
        for row_idx in range(self.test_plan_table.rowCount()):
            self._set_elapsed_for_row(row_idx, None)

    def _finish_timing_for_row(self, row_idx: int):
        if self._run_started_monotonic is None:
            return
        now = self._monotonic_fn()
        if self._current_run_row == row_idx and self._current_test_started_monotonic is not None:
            elapsed_s = max(0.0, now - self._current_test_started_monotonic)
        else:
            elapsed_s = 0.0
        self._set_elapsed_for_row(row_idx, elapsed_s)
        self._current_run_row = None
        self._current_test_started_monotonic = None
        self._update_timing_display()

    def _set_elapsed_for_row(self, row_idx: int, elapsed_s: float | None):
        test_id = self._test_id_for_row(row_idx)
        if test_id is not None:
            if elapsed_s is None:
                self._plan_elapsed_seconds.pop(test_id, None)
            else:
                self._plan_elapsed_seconds[test_id] = elapsed_s
        item = self.test_plan_table.item(row_idx, PLAN_ELAPSED_COL)
        if item is None:
            item = QtWidgets.QTableWidgetItem()
            item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self.test_plan_table.setItem(row_idx, PLAN_ELAPSED_COL, item)
        item.setText("" if elapsed_s is None else self._format_duration(elapsed_s))

    def _test_id_for_row(self, row_idx: int) -> int | None:
        item = self.test_plan_table.item(row_idx, PLAN_ID_COL)
        if item is None:
            return None
        try:
            return int(item.text())
        except (TypeError, ValueError):
            return None

    def _update_timing_display(self):
        now = self._monotonic_fn()
        if self._run_started_monotonic is None:
            elapsed_s = 0.0
        elif self._run_finished_monotonic is not None:
            elapsed_s = max(0.0, self._run_finished_monotonic - self._run_started_monotonic)
        else:
            elapsed_s = max(0.0, now - self._run_started_monotonic)

        if self._current_run_row is not None and self._current_test_started_monotonic is not None:
            self._set_elapsed_for_row(self._current_run_row, max(0.0, now - self._current_test_started_monotonic))

        remaining_s, remaining_unknown = self._remaining_seconds(now)
        total_s, total_unknown = self._typical_total_seconds()
        self.elapsed_time_label.setText(f"Elapsed: {self._format_duration(elapsed_s)}")
        self.remaining_time_label.setText(f"Expected remaining: {self._format_estimate(remaining_s, remaining_unknown)}")
        self.typical_total_time_label.setText(f"Typical total: {self._format_estimate(total_s, total_unknown)}")

    def _remaining_seconds(self, now: float) -> tuple[float, bool]:
        total = 0.0
        unknown = False
        terminal = {"passed", "failed", "warning", "missing", "blocked", "skipped"}
        for row_idx in range(self.test_plan_table.rowCount()):
            status = self._plan_status(row_idx).strip().lower()
            if status in terminal:
                continue
            test_id = self._test_id_for_row(row_idx)
            if test_id is None:
                continue
            typical_s = self._plan_typical_seconds.get(test_id)
            if typical_s is None:
                unknown = True
                continue
            if row_idx == self._current_run_row and self._current_test_started_monotonic is not None:
                elapsed_s = max(0.0, now - self._current_test_started_monotonic)
                total += max(0.0, typical_s - elapsed_s)
            else:
                total += typical_s
        return total, unknown

    def _typical_total_seconds(self) -> tuple[float, bool]:
        total = 0.0
        unknown = False
        for row in self._test_plan_rows:
            typical_s = self._plan_typical_seconds.get(row.test_id)
            if typical_s is None:
                unknown = True
            else:
                total += typical_s
        return total, unknown

    @staticmethod
    def _format_duration(seconds: float | None, *, unknown: str = "") -> str:
        if seconds is None:
            return unknown
        whole = int(round(max(0.0, float(seconds))))
        minutes, sec = divmod(whole, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{sec:02d}"
        return f"{minutes:02d}:{sec:02d}"

    def _format_estimate(self, seconds: float, unknown: bool) -> str:
        if unknown and seconds <= 0:
            return "unknown"
        prefix = "~" if seconds > 0 else ""
        suffix = " + unknown" if unknown else ""
        return f"{prefix}{self._format_duration(seconds)}{suffix}"

    def _apply_plan_status_brush(self, item: QtWidgets.QTableWidgetItem, status: str):
        value = str(status or "").lower()
        colors = {
            "queued": ("#26384f", "#ffffff"),
            "in progress": ("#31435f", "#ffffff"),
            "passed": ("#1f4f32", "#ffffff"),
            "warning": ("#5a461f", "#ffffff"),
            "failed": ("#5a1f1f", "#ffffff"),
            "missing": ("#4c2a2a", "#ffffff"),
            "blocked": ("#5a1f1f", "#ffffff"),
            "skipped": ("#3a3a3a", "#ffffff"),
        }
        if value in colors:
            bg, fg = colors[value]
            item.setBackground(QtGui.QBrush(QtGui.QColor(bg)))
            item.setForeground(QtGui.QBrush(QtGui.QColor(fg)))
        else:
            item.setBackground(QtGui.QBrush())
            item.setForeground(QtGui.QBrush())

    def _update_start_enabled(self):
        if self._run_busy or self._current_suite is None:
            self.start_button.setEnabled(False)
            return
        manifest = self._current_suite.manifest
        port_ok = bool(self.port_edit.text().strip())
        fixture_ok = True
        if manifest.requires_operator_prompts:
            fixture_ok = self.fixture_combo.currentText().strip() in set(required_fixture_ids(manifest))
        self.start_button.setEnabled(port_ok and fixture_ok)

    def _run_config(self) -> dict[str, Any] | None:
        if self._current_suite is None:
            return None
        timeout_text = self.timeout_edit.text().strip()
        timeout_ms = None
        if timeout_text:
            try:
                timeout_ms = int(timeout_text)
            except ValueError:
                self._popup_message("Machine Qualification", "Timeout must be blank or an integer number of milliseconds.")
                return None
            if timeout_ms <= 0:
                self._popup_message("Machine Qualification", "Timeout must be greater than zero.")
                return None

        manifest = self._current_suite.manifest
        fixture_id = self.fixture_combo.currentText().strip()
        if manifest.requires_operator_prompts and fixture_id not in set(required_fixture_ids(manifest)):
            self._popup_message("Machine Qualification", "Select the required fixture before starting this operator-gated suite.")
            return None

        return {
            "manifest_ref": str(self._current_suite.manifest_path),
            "manifest_id": manifest.manifest_id,
            "port": self.port_edit.text().strip(),
            "baud": int(self.baud_spin.value()),
            "machine_id": self.machine_id_edit.text().strip(),
            "timeout_ms": timeout_ms,
            "fixture_id": fixture_id,
            "operator_prompts": bool(manifest.requires_operator_prompts),
        }

    @QtCore.Slot()
    def _on_start_clicked(self):
        config = self._run_config()
        if config is None:
            return
        if not self._confirm_qualification_start(config):
            return

        self.run_log.clear()
        self._set_run_busy(True)
        self._set_all_plan_status("Queued")
        self._begin_run_timing()
        self._mark_next_queued_in_progress()
        self._on_qualification_stage("Preparing qualification run")
        starter = getattr(self.controller, "start_qualification_run", None)
        if not callable(starter) or not starter(config):
            self._stop_run_timing()
            self._set_run_busy(False)
            self._on_qualification_stage("Failed")
            self._popup_message("Machine Qualification", "Could not start qualification run.")

    def _confirm_qualification_start(self, config: dict[str, Any]) -> bool:
        if self._current_suite is None:
            return False
        manifest = self._current_suite.manifest
        notes = "\n".join(fixture_notes(manifest)) or "No fixture notes."
        message = (
            f"Suite: {manifest.name}\n"
            f"Profile: {manifest.profile}\n"
            f"Port: {config['port']}\n"
            f"Fixture: {config.get('fixture_id') or 'none'}\n\n"
            f"{notes}\n\n"
            "This may move axes, actuate pressure regulators, valves, or the gripper depending on the suite."
        )
        response = QtWidgets.QMessageBox.question(
            self,
            "Start Machine Qualification",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return response == QtWidgets.QMessageBox.Yes

    def _set_run_busy(self, busy: bool):
        self._run_busy = bool(busy)
        self.run_progress.setRange(0, 0 if busy else 1)
        self.run_progress.setValue(0)
        self.suite_list.setEnabled(not busy)
        self.refresh_suites_button.setEnabled(not busy)
        self.machine_id_edit.setEnabled(not busy)
        self.port_edit.setEnabled(not busy)
        self.baud_spin.setEnabled(not busy)
        self.timeout_edit.setEnabled(not busy)
        self.fixture_combo.setEnabled(not busy)
        if not busy:
            self._timing_timer.stop()
        self._update_start_enabled()

    @QtCore.Slot(str)
    def _on_qualification_stage(self, message: str):
        self.run_status_label.setText(str(message))
        self._append_run_log(str(message))

    @QtCore.Slot(str)
    def _on_qualification_output(self, message: str):
        self._append_run_log(str(message))

    @QtCore.Slot(str)
    def _on_qualification_prompt(self, message: str):
        response = QtWidgets.QMessageBox.question(
            self,
            "Qualification Operator Prompt",
            str(message),
            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Ok,
        )
        responder = getattr(self.controller, "respond_qualification_prompt", None)
        if callable(responder):
            responder(response == QtWidgets.QMessageBox.Ok)

    @QtCore.Slot(object)
    def _on_selftest_event(self, event: object):
        if not isinstance(event, dict):
            return
        event_type = str(event.get("event") or "")
        if event_type == "selftest_progress":
            stage = str(event.get("stage") or "").strip()
            if stage:
                self.run_status_label.setText(stage)
                self._append_run_log(f"Progress: {stage}")
            test_id = self._event_test_id(event)
            if test_id is not None and test_id in self._plan_row_by_test_id:
                self._mark_plan_row_in_progress(self._plan_row_by_test_id[test_id])
            return

        if event_type == "selftest_result":
            test_id = self._event_test_id(event)
            if test_id is None:
                return
            row_idx = self._plan_row_by_test_id.get(test_id)
            if row_idx is None:
                return
            status = "Passed" if bool(event.get("pass")) else "Failed"
            self._finish_timing_for_row(row_idx)
            self._set_plan_status(row_idx, status)
            name = str(event.get("name") or test_id)
            self._append_run_log(f"Result {test_id} {name}: {status}")
            self._mark_next_queued_in_progress(after_row=row_idx)
            return

        if event_type == "selftest_done":
            summary = event.get("summary") if isinstance(event.get("summary"), dict) else {}
            text = (
                f"Self-test done: total={summary.get('total', '?')}, "
                f"passed={summary.get('passed', '?')}, failed={summary.get('failed', '?')}"
            )
            self.run_status_label.setText(text)
            self._append_run_log(text)
            return

        if event_type == "selftest_timeout":
            reason = str(event.get("reason") or "timeout")
            text = f"Self-test timeout: {reason}"
            self.run_status_label.setText(text)
            self._append_run_log(text)
            return

        if event_type == "selftest_reset_report":
            text = "MCU reset report seen during self-test"
            self.run_status_label.setText(text)
            self._append_run_log(text)

    @staticmethod
    def _event_test_id(event: dict[str, Any]) -> int | None:
        try:
            test_id = int(event.get("test_id"))
        except (TypeError, ValueError):
            return None
        return test_id if test_id > 0 else None

    @QtCore.Slot(bool, str, object)
    def _on_qualification_finished(self, ok: bool, message: str, payload: object):
        self._stop_run_timing()
        self._set_run_busy(False)
        self._on_qualification_stage("Finished" if ok else "Failed")
        self._append_run_log(str(message))
        data = payload if isinstance(payload, dict) else {}
        report = data.get("report") if isinstance(data.get("report"), dict) else None
        if report is not None:
            self._apply_final_report_to_plan(report)
        self.refresh_reports(select_report_path=data.get("report_path"))
        self._refresh_timing_estimates()
        self._refresh_plan_timing_columns()

    def _append_run_log(self, message: str):
        if message:
            self.run_log.appendPlainText(message)

    def _apply_final_report_to_plan(self, report: dict[str, Any]):
        rows = normalize_result_rows(report)
        rows_by_id = {int(row.item_id): row for row in rows if row.item_id and str(row.item_id).isdigit()}
        for test_id, row_idx in self._plan_row_by_test_id.items():
            result_row = rows_by_id.get(int(test_id))
            if result_row is None:
                status = "Missing"
            else:
                status = self._status_for_result_row(result_row)
            self._set_plan_status(row_idx, status)

    @staticmethod
    def _status_for_result_row(row: QualificationResultRow) -> str:
        analysis = str(row.analysis_status or "").lower()
        raw = str(row.raw_pass or "").lower()
        if analysis == "fail" or raw == "fail":
            return "Failed"
        if analysis == "warning":
            return "Warning"
        if analysis == "pass" or raw == "pass":
            return "Passed"
        return "Missing"

    def _report_entries_from_controller(self) -> list[QualificationReportIndexEntry]:
        if hasattr(self.controller, "list_qualification_reports"):
            return list(self.controller.list_qualification_reports())
        root = self.report_root or Path("hil_reports")
        return discover_report_entries(root)

    def _load_report_from_controller(self, report_path: Path) -> dict[str, Any]:
        if hasattr(self.controller, "load_qualification_report"):
            return self.controller.load_qualification_report(report_path)
        return load_report(report_path)

    @QtCore.Slot()
    def refresh_reports(self, select_report_path: str | Path | None = None):
        selected_target = str(select_report_path or "")
        previous = str(self._current_entry.report_path) if self._current_entry is not None else ""
        wanted = selected_target or previous
        self.report_list.blockSignals(True)
        self.report_list.clear()
        try:
            self._entries = self._report_entries_from_controller()
            self.report_count_label.setText(f"{len(self._entries)} report(s) found.")
        except Exception as exc:
            self._entries = []
            self.report_count_label.setText(f"Could not scan qualification reports: {exc}")

        select_row = 0
        for idx, entry in enumerate(self._entries):
            item = QtWidgets.QListWidgetItem(entry.compact_display_time)
            item.setToolTip(self._report_list_tooltip(entry))
            self.report_list.addItem(item)
            if str(entry.report_path) == wanted:
                select_row = idx
        self.report_list.blockSignals(False)

        if self._entries:
            self.report_list.setCurrentRow(select_row)
            self._load_report_at_row(select_row)
        else:
            self._clear_report_display("No qualification reports found.")
        self._refresh_timing_estimates()
        self._refresh_plan_timing_columns()

    @staticmethod
    def _report_list_tooltip(entry: QualificationReportIndexEntry) -> str:
        manifest = entry.manifest_name or entry.manifest_id or "unknown"
        if entry.manifest_name and entry.manifest_id and entry.manifest_name != entry.manifest_id:
            manifest = f"{entry.manifest_name} ({entry.manifest_id})"
        return (
            f"Machine: {entry.machine_id or 'unknown'}\n"
            f"Manifest: {manifest}\n"
            f"Profile: {entry.profile or 'unknown'}\n"
            f"Status: {entry.overall_status or 'unknown'}\n"
            f"Started: {compact_report_time(entry.started_at, entry.run_dir.name)}\n"
            f"Path: {entry.report_path}"
        )

    @QtCore.Slot(int)
    def _load_report_at_row(self, row: int):
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]
        try:
            report = self._load_report_from_controller(entry.report_path)
        except Exception as exc:
            self._clear_report_display(f"Could not load report: {exc}")
            return

        self._current_entry = entry
        self._current_report = report
        self._rows = normalize_result_rows(report)
        self._populate_summary(entry, report)
        self._populate_warnings(report)
        self._populate_result_tables()
        self._populate_artifacts(report, entry.report_path)
        self.details_text.setPlainText("")

    def _clear_report_display(self, message: str):
        self._current_entry = None
        self._current_report = None
        self._rows = []
        for label in self.summary_labels.values():
            label.setText("")
        self.warnings_list.clear()
        self.warnings_list.addItem(message)
        for table in self.result_tables.values():
            table.setRowCount(0)
        self.artifacts_table.setRowCount(0)
        self.details_text.setPlainText(message)

    def _populate_summary(self, entry: QualificationReportIndexEntry, report: dict[str, Any]):
        manifest = report.get("manifest") if isinstance(report.get("manifest"), dict) else {}
        counts = (
            f"{entry.result_count} result(s), "
            f"{entry.host_check_count} host check(s), "
            f"{entry.warning_count} warning(s)"
        )
        manifest_text = entry.manifest_id
        if entry.manifest_name and entry.manifest_name != entry.manifest_id:
            manifest_text = f"{entry.manifest_name} ({entry.manifest_id})"

        self.summary_labels["status"].setText(entry.overall_status or "unknown")
        self.summary_labels["machine"].setText(entry.machine_id or "unknown")
        self.summary_labels["manifest"].setText(manifest_text or str(manifest.get("name") or "unknown"))
        self.summary_labels["profile"].setText(entry.profile or "unknown")
        self.summary_labels["fixture"].setText(entry.fixture_id or "none")
        self.summary_labels["started"].setText(entry.started_at or "unknown")
        self.summary_labels["finished"].setText(entry.finished_at or "unknown")
        self.summary_labels["counts"].setText(counts)

    def _populate_warnings(self, report: dict[str, Any]):
        self.warnings_list.clear()
        warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
        blocking = []
        analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
        seen_messages = set()

        def add_unique(text: str):
            if text in seen_messages:
                return
            seen_messages.add(text)
            self.warnings_list.addItem(text)

        for item in analysis.get("items") or []:
            if isinstance(item, dict) and str(item.get("status") or "").lower() == "fail":
                blocking.append(item)

        for item in blocking:
            text = str(item.get("message") or "Blocking issue")
            add_unique(f"FAIL: {text}")
        for item in analysis.get("metric_evaluations") or []:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").lower()
            if status not in {"warning", "fail"}:
                continue
            label = "FAIL" if status == "fail" else "WARN"
            message = str(item.get("message") or "Metric outside threshold")
            name = str(item.get("name") or item.get("test_id") or "").strip()
            prefix = f"{name}: " if name else ""
            add_unique(f"{label}: {prefix}{message}")
        for item in warnings:
            if isinstance(item, dict):
                text = str(item.get("message") or "Warning")
                name = str(item.get("name") or item.get("test_id") or "").strip()
                prefix = f"{name}: " if name else ""
                add_unique(f"WARN: {prefix}{text}")
        if self.warnings_list.count() == 0:
            self.warnings_list.addItem("No warnings or blocking failures.")

    def _populate_result_tables(self):
        for subsystem, table in self.result_tables.items():
            rows = self._rows if subsystem == "All" else [row for row in self._rows if row.subsystem == subsystem]
            self._populate_table(table, rows)

    def _populate_table(self, table: QtWidgets.QTableWidget, rows: list[QualificationResultRow]):
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            values = [
                row.item_id,
                row.name,
                row.raw_pass,
                row.analysis_status,
                row.category,
                row.failure_domain,
                row.metric_summary,
                row.message,
            ]
            for col_idx, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value or ""))
                item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                if col_idx == 0:
                    item.setData(QtCore.Qt.UserRole, row)
                self._apply_row_brush(item, row)
                table.setItem(row_idx, col_idx, item)
        table.resizeRowsToContents()
        table.setSortingEnabled(True)

    def _apply_row_brush(self, item: QtWidgets.QTableWidgetItem, row: QualificationResultRow):
        status = str(row.analysis_status or row.raw_pass or "").lower()
        raw = str(row.raw_pass or "").lower()
        if status == "fail" or raw == "fail":
            item.setBackground(QtGui.QBrush(QtGui.QColor("#5a1f1f")))
            item.setForeground(QtGui.QBrush(QtGui.QColor("#ffffff")))
        elif status == "warning":
            item.setBackground(QtGui.QBrush(QtGui.QColor("#5a461f")))
            item.setForeground(QtGui.QBrush(QtGui.QColor("#ffffff")))

    def _populate_artifacts(self, report: dict[str, Any], report_path: Path):
        paths = artifact_paths(report, report_path=report_path)
        self.artifacts_table.setRowCount(len(paths))
        for row_idx, (label, path_text) in enumerate(paths):
            exists = bool(path_text and Path(path_text).exists())
            values = [label, path_text, "yes" if exists else "no"]
            for col_idx, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                self.artifacts_table.setItem(row_idx, col_idx, item)
        self.artifacts_table.resizeRowsToContents()

    def _selected_row_from_table(self, table: QtWidgets.QTableWidget) -> QualificationResultRow | None:
        selected = table.selectionModel().selectedRows() if table.selectionModel() else []
        if not selected:
            return None
        row_index = selected[0].row()
        item = table.item(row_index, 0)
        if item is None:
            return None
        row = item.data(QtCore.Qt.UserRole)
        return row if isinstance(row, QualificationResultRow) else None

    def _update_details_from_table(self, table: QtWidgets.QTableWidget):
        row = self._selected_row_from_table(table)
        if row is None:
            return
        payload = {
            "item_kind": row.item_kind,
            "item_id": row.item_id,
            "name": row.name,
            "subsystem": row.subsystem,
            "raw_pass": row.raw_pass,
            "analysis_status": row.analysis_status,
            "category": row.category,
            "failure_domain": row.failure_domain,
            "message": row.message,
            "details": row.details,
        }
        self.details_text.setPlainText(json.dumps(payload, indent=2, sort_keys=True))

    def _selected_artifact_path(self) -> str:
        selected = self.artifacts_table.selectionModel().selectedRows() if self.artifacts_table.selectionModel() else []
        if selected:
            item = self.artifacts_table.item(selected[0].row(), 1)
            if item is not None:
                return item.text()
        if self._current_entry is not None:
            return str(self._current_entry.report_path)
        return ""

    def _copy_selected_artifact_path(self):
        path_text = self._selected_artifact_path()
        if not path_text:
            return
        QtWidgets.QApplication.clipboard().setText(path_text)

    def _open_run_folder(self):
        if self._current_entry is None:
            return
        run_dir = self._current_entry.run_dir
        if not run_dir.exists():
            report_parent = self._current_entry.report_path.parent
            run_dir = report_parent if report_parent.exists() else run_dir
        if not run_dir.exists():
            self._popup_message("Machine Qualification", f"Run folder does not exist:\n{run_dir}")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(run_dir.resolve())))

    def _popup_message(self, title: str, message: str):
        popup = getattr(self.main_window, "popup_message", None)
        if callable(popup):
            popup(title, message)
            return
        QtWidgets.QMessageBox.warning(self, title, message)

    def closeEvent(self, event):
        if self._run_busy:
            QtWidgets.QMessageBox.warning(
                self,
                "Machine Qualification",
                "A qualification run is still active. Wait for it to finish before closing this window.",
            )
            event.ignore()
            return
        super().closeEvent(event)
