from __future__ import annotations

# Import your model & dataclasses
from Model import (
    FactorSpec,
    OptionSpec,
    ExperimentModel,
    Well,
    PRINTING_MODE_DROPLET,
    PRINTING_MODE_STREAM,
    normalize_printing_mode,
    infer_printing_mode_from_volume,
    printing_mode_default_ejection_volume_nl,
    printing_mode_allowed_range_nl,
)

from PySide6 import QtCore, QtWidgets, QtGui, QtCharts
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QGridLayout, QGroupBox, QPushButton, QComboBox, QSpinBox, QSizePolicy,
    QSpacerItem, QFileDialog, QInputDialog, QMessageBox, QAbstractItemView, QDialog,QLineEdit,QDoubleSpinBox,
    QTabWidget, QCheckBox, QScrollArea, QFormLayout, QFrame
)
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QWidget, QGraphicsEllipseItem, QGraphicsScene, QGraphicsView, QGraphicsRectItem
from PySide6.QtGui import QShortcut, QKeySequence, QPixmap, QColor, QPen, QBrush, QImage, QPainter, QIcon
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QSignalBlocker
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import json
import os
import sys
import random
import time
import shutil
import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime
from pathlib import Path
import cv2
from utilities import ShortcutManager
from ExperimentAuditReader import ExperimentAuditReader, build_audit_markdown
import CalibrationClasses
import importlib
from typing import Mapping, Sequence, Optional, Any, List, Dict, Tuple, Set
from hardware.profile import CURRENT_PROFILE, HardwareProfile

MassCalibrationDialog = None


def _get_mass_calibration_dialog_class():
    global MassCalibrationDialog
    if MassCalibrationDialog is None:
        from legacy.mass_calibration import MassCalibrationDialog as _MassCalibrationDialog

        MassCalibrationDialog = _MassCalibrationDialog
    return MassCalibrationDialog


class OptionsDialog(QtWidgets.QDialog):
    def __init__(self, title, message, options):
        super().__init__()

        self.setWindowTitle(title)
        self.layout = QtWidgets.QVBoxLayout(self)

        self.message_label = QtWidgets.QLabel(message)
        self.layout.addWidget(self.message_label)

        self.buttons_layout = QtWidgets.QGridLayout()
        self.layout.addLayout(self.buttons_layout)

        self.buttons = []
        for i, option in enumerate(options):
            button = QtWidgets.QPushButton(option)
            button.clicked.connect(lambda _, option=option: self.button_clicked(option))
            self.buttons_layout.addWidget(button, i // 5, i % 5)  # Change 5 to the number of buttons per row
            self.buttons.append(button)

        self.quit_button = QtWidgets.QPushButton("Quit")
        self.quit_button.clicked.connect(self.reject)
        self.layout.addWidget(self.quit_button)

        self.clicked_option = None

    def button_clicked(self, option):
        self.clicked_option = option
        self.accept()

    def exec(self):
        super().exec()
        return self.clicked_option

class RefreshingComboBox(QComboBox):
    aboutToShowPopup = Signal()

    def showPopup(self):
        self.aboutToShowPopup.emit()
        super().showPopup()


AUDIT_TIMELINE_ROW_ROLE = int(Qt.UserRole) + 100


class AuditTimelineTableModel(QtCore.QAbstractTableModel):
    COLUMNS = (
        ("time_display", "Time", Qt.AlignLeft | Qt.AlignVCenter),
        ("elapsed_display", "Elapsed", Qt.AlignRight | Qt.AlignVCenter),
        ("level", "Level", Qt.AlignCenter),
        ("stock_solution", "Stock Solution", Qt.AlignLeft | Qt.AlignVCenter),
        ("event_type", "Type", Qt.AlignLeft | Qt.AlignVCenter),
        ("summary", "Summary", Qt.AlignLeft | Qt.AlignVCenter),
        ("line_number", "Line", Qt.AlignRight | Qt.AlignVCenter),
    )

    def __init__(self, parent=None, rows=None):
        super().__init__(parent)
        self._rows = list(rows or [])

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()

    def row_at(self, row_index):
        if 0 <= row_index < len(self._rows):
            return self._rows[row_index]
        return None

    def column_index(self, key):
        for idx, (column_key, _label, _alignment) in enumerate(self.COLUMNS):
            if column_key == key:
                return idx
        raise KeyError(key)

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self.COLUMNS):
            return self.COLUMNS[section][1]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.row_at(index.row())
        if row is None:
            return None
        column_key, _label, alignment = self.COLUMNS[index.column()]

        if role in (Qt.DisplayRole, Qt.EditRole):
            value = getattr(row, column_key, "")
            return "" if value is None else str(value)
        if role == Qt.TextAlignmentRole:
            return int(alignment)
        if role == AUDIT_TIMELINE_ROW_ROLE:
            return row
        if role == Qt.ToolTipRole:
            if column_key == "summary":
                return getattr(row, "tooltip_text", "")
            return None
        if role == Qt.ForegroundRole:
            level = str(getattr(row, "level", "") or "").lower()
            if level == "error":
                return QBrush(QColor("#b91c1c"))
            if level == "warning":
                return QBrush(QColor("#b45309"))
            if getattr(row, "is_valid", True) is False:
                return QBrush(QColor("#6b7280"))
        return None


class AuditTimelineWindow(QtWidgets.QDialog):
    def __init__(self, parent=None, model=None, reader_factory=None):
        super().__init__(parent)
        self.model = model if model is not None else getattr(parent, "model", None)
        self.reader_factory = reader_factory

        self.setWindowTitle("Experiment Audit Timeline")
        self.resize(1000, 650)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.add_note_button = QtWidgets.QPushButton("Add Note")
        self.add_note_button.clicked.connect(self.add_operator_note)
        self.export_markdown_button = QtWidgets.QPushButton("Export Markdown")
        self.export_markdown_button.clicked.connect(self.export_markdown)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.add_note_button)
        toolbar.addWidget(self.export_markdown_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.status_label)
        layout.addLayout(toolbar)

        splitter = QtWidgets.QSplitter(Qt.Vertical)

        self.table = QtWidgets.QTableView()
        self.table_model = AuditTimelineTableModel(self)
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            self.table_model.column_index("summary"),
            QHeaderView.Stretch,
        )

        self.details_text = QtWidgets.QPlainTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        details_font = QtGui.QFont("Consolas")
        details_font.setStyleHint(QtGui.QFont.Monospace)
        self.details_text.setFont(details_font)

        splitter.addWidget(self.table)
        splitter.addWidget(self.details_text)
        splitter.setSizes([430, 220])
        layout.addWidget(splitter, 1)

        selection_model = self.table.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(self._on_selection_changed)

        self.refresh()

    def _make_reader(self):
        if self.reader_factory is not None:
            return self.reader_factory()
        return ExperimentAuditReader(model=self.model)

    def refresh(self, select_row=0):
        try:
            rows = self._make_reader().read_rows()
        except Exception as exc:
            rows = []
            self.status_label.setText(f"Could not read audit: {exc}")
        else:
            self.status_label.setText(self._format_status(rows))

        self.table_model.set_rows(rows)
        if rows:
            row_index = len(rows) - 1 if select_row == "last" else int(select_row or 0)
            row_index = max(0, min(row_index, len(rows) - 1))
            self.table.selectRow(row_index)
            self._set_details(rows[row_index])
        else:
            self.details_text.setPlainText("")

    def _format_status(self, rows):
        count = len(rows or [])
        if count == 0:
            return "No audit events found"
        warnings = sum(1 for row in rows if str(getattr(row, "level", "")).lower() == "warning")
        errors = sum(1 for row in rows if str(getattr(row, "level", "")).lower() == "error")
        parts = [f"{count} event" if count == 1 else f"{count} events"]
        if warnings:
            parts.append(f"{warnings} warning" if warnings == 1 else f"{warnings} warnings")
        if errors:
            parts.append(f"{errors} error" if errors == 1 else f"{errors} errors")
        return " | ".join(parts)

    def _selected_row(self):
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return None
        selected = selection_model.selectedRows()
        if not selected:
            return None
        return self.table_model.row_at(selected[0].row())

    def _set_details(self, row):
        self.details_text.setPlainText(str(getattr(row, "detail_json", "") or ""))

    def _on_selection_changed(self, *_args):
        row = self._selected_row()
        if row is None:
            self.details_text.setPlainText("")
            return
        self._set_details(row)

    @staticmethod
    def _operator_note_summary(note_text):
        lines = str(note_text or "").splitlines()
        first_line = lines[0].strip() if lines else ""
        if len(first_line) > 80:
            first_line = first_line[:77] + "..."
        return f"Operator note added: {first_line}"

    def add_operator_note(self):
        note_text, ok = QtWidgets.QInputDialog.getMultiLineText(
            self,
            "Add Operator Note",
            "Note:",
        )
        if not ok:
            return

        note_text = str(note_text or "").strip()
        if not note_text:
            self.status_label.setText("Operator note was empty")
            return

        try:
            recorder = getattr(self.model, "record_experiment_audit_event", None)
            if not callable(recorder):
                self.status_label.setText("Could not add operator note")
                return
            event = recorder(
                "operator_note_added",
                self._operator_note_summary(note_text),
                details={"note": note_text},
                level="info",
                context={"source": "audit_timeline_window"},
            )
        except Exception as exc:
            self.status_label.setText(f"Could not add operator note: {exc}")
            return

        if event is None:
            self.status_label.setText("Could not add operator note")
            return

        self.refresh(select_row="last")

    def _default_markdown_export_path(self):
        exp = getattr(self.model, "experiment_model", None)
        exp_dir = getattr(exp, "experiment_dir_path", None)
        if exp_dir:
            return os.path.join(os.fspath(exp_dir), "experiment_audit_timeline.md")
        return "experiment_audit_timeline.md"

    def export_markdown(self):
        default_path = self._default_markdown_export_path()
        selected = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Audit Markdown",
            default_path,
            "Markdown files (*.md);;Text files (*.txt);;All files (*)",
        )
        file_path = selected[0] if isinstance(selected, tuple) else selected
        if not file_path:
            return

        try:
            reader = self._make_reader()
            rows = reader.read_rows()
            markdown = build_audit_markdown(rows, audit_path=reader.get_audit_path())
            Path(file_path).write_text(markdown, encoding="utf-8")
        except Exception as exc:
            self.status_label.setText(f"Could not export audit: {exc}")
            return

        self.status_label.setText(f"Exported audit markdown to {file_path}")

# class ShortcutManager:
#     """Manage application shortcuts and their descriptions."""
#     def __init__(self, parent):
#         self.parent = parent
#         self.shortcuts = []

#     def add_shortcut(self, key_sequence, description, callback):
#         """Add a shortcut to the application and store its description."""
#         shortcut = QShortcut(QKeySequence(key_sequence), self.parent, activated=callback)
#         self.shortcuts.append((key_sequence, description))
#         return shortcut

#     def get_shortcuts(self):
#         """Return a list of shortcuts and their descriptions."""
#         return self.shortcuts

class MainWindow(QMainWindow):
    CLOSE_DISCONNECT_TIMEOUT_MS = 5000

    def __init__(self, model, controller, profile: HardwareProfile = CURRENT_PROFILE):
        super().__init__()
        self.model = model
        self.controller = controller
        self.profile = profile
        self.shortcut_manager = ShortcutManager(self)
        self.setup_shortcuts()
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.color_dict_path = os.path.join(self.script_dir, 'Presets','Colors.json')
        self.color_dict = self.load_colors(self.color_dict_path)
        self._startup_focus_initialized = False
        self.audit_timeline_window = None
        self._app_update_close_requested = False

        self.setWindowTitle("Droplet Printer Interface v1.0.1")
        self.init_ui()
        self.disconnected = False
        self._close_disconnect_pending = False
        self._close_after_disconnect = False
        self._close_disconnect_dialog = None
        self._close_disconnect_timer = None
        self._close_disconnect_timeout_prompt = False
        self._close_disconnect_signal_hooked = False

        self.controller.error_occurred_signal.connect(self.popup_message)
        self.controller.machine.disconnect_complete_signal.connect(self.disconnect_successful)
        self._ensure_close_disconnect_signal_hook()
        self.controller.update_volumes_in_view_signal.connect(self.rack_box.update_all_slots)
        self.controller.machine.require_gripper_confirmation.connect(self.on_require_gripper_confirmation)

    def load_colors(self, file_path):
        with open(file_path, 'r') as file:
            return json.load(file)

    def init_ui(self):
        """Initialize the main user interface."""
        self.central_widget = QWidget()
        self.central_widget.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setCentralWidget(self.central_widget)
        self.setWindowIcon(self.make_window_icon())

        self.layout = QHBoxLayout(self.central_widget)

        # Create the left panel with the motor positions
        left_panel = QtWidgets.QWidget()
        left_panel.setFixedWidth(450)
        left_panel.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        
        # Add ConnectionWidget
        self.connection_widget = ConnectionWidget(self,self.model, self.controller)
        left_layout.addWidget(self.connection_widget)

        self.coordinates_box = MotorPositionWidget(self,self.model, self.controller)
        self.coordinates_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        left_layout.addWidget(self.coordinates_box)

        self.pressure_box = PressurePlotBox(self, self.model, self.controller)
        self.pressure_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        left_layout.addWidget(self.pressure_box)

        self.layout.addWidget(left_panel)

        mid_panel = QtWidgets.QWidget()
        mid_panel.setFixedWidth(1000)
        mid_panel.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        mid_layout = QtWidgets.QVBoxLayout(mid_panel)

        self.tab_widget = QtWidgets.QTabWidget()
        self.tab_widget.setFocusPolicy(QtCore.Qt.NoFocus)

        self.well_plate_widget = WellPlateWidget(self,self.model, self.controller)
        self.well_plate_widget.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        self.tab_widget.addTab(self.well_plate_widget, "Well Plate")

        self.movement_box = MovementBox(self, self.model, self.controller)
        self.movement_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        self.tab_widget.addTab(self.movement_box, "Movement")

        self.speed_profiles_tab = SpeedProfilesTab(self, self.model, self.controller, self.color_dict)
        self.speed_profiles_tab.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        self.tab_widget.addTab(self.speed_profiles_tab, "Firmware")

        self.sequences_tab = PreprogrammedSequencesTab(self, self.model, self.controller, self.color_dict)
        self.sequences_tab.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        self.tab_widget.addTab(self.sequences_tab, "Sequences")

        self.calibrations_tab = self._create_calibrations_tab()
        self.calibrations_tab.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        self.tab_widget.addTab(self.calibrations_tab, "Calibrations")

        mid_layout.addWidget(self.tab_widget)

        self.rack_box = RackBox(self,self.model,self.controller)
        self.rack_box.setFixedHeight(250)
        self.rack_box.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        mid_layout.addWidget(self.rack_box)

        self.layout.addWidget(mid_panel)

        # Add other widgets to the right panel as needed
        right_panel = QtWidgets.QWidget()
        right_panel.setFixedWidth(450)
        right_panel.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        right_layout = QtWidgets.QVBoxLayout(right_panel)

        self.board_status_box = BoardStatusBox(self, self.model, self.controller)
        self.board_status_box.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        self.board_status_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

        right_layout.addWidget(self.board_status_box)

        self.audit_timeline_button = QtWidgets.QPushButton("Audit Timeline")
        self.audit_timeline_button.clicked.connect(self.show_experiment_audit)
        right_layout.addWidget(self.audit_timeline_button)

        self.experiment_task_list = ExperimentTaskListWidget(self, self.model, self.controller)
        self.experiment_task_list.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        self.experiment_task_list.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        right_layout.addWidget(self.experiment_task_list)

        # Add the command queue table to the right panel
        self.command_queue_widget = CommandQueueWidget(self,self.controller.machine)
        right_layout.addWidget(self.command_queue_widget)

        self.layout.addWidget(right_panel)

        # Set the size of the main window to be 90% of the screen size
        screen_geometry = QApplication.primaryScreen().geometry()
        width = int(screen_geometry.width() * 0.9)
        height = int(screen_geometry.height() * 0.9)
        self.resize(width, height)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._startup_focus_initialized:
            self._startup_focus_initialized = True
            QTimer.singleShot(0, lambda: self.central_widget.setFocus(QtCore.Qt.OtherFocusReason))
        

    def setup_shortcuts(self):
        """Set up keyboard shortcuts using the shortcut manager."""
        self.shortcut_manager.add_shortcut('Left', 'Move left', lambda: self.controller.set_relative_Y(-self.model.machine_model.step_size,manual=True))
        self.shortcut_manager.add_shortcut('Right', 'Move right', lambda: self.controller.set_relative_Y(self.model.machine_model.step_size,manual=True))
        self.shortcut_manager.add_shortcut('Up', 'Move forward', lambda: self.controller.set_relative_X(self.model.machine_model.step_size, manual=True))
        self.shortcut_manager.add_shortcut('Down', 'Move backward', lambda: self.controller.set_relative_X(-self.model.machine_model.step_size, manual=True))
        self.shortcut_manager.add_shortcut('k', 'Move up', lambda: self.controller.set_relative_Z(-self.model.machine_model.step_size,manual=True))
        self.shortcut_manager.add_shortcut('m', 'Move down', lambda: self.controller.set_relative_Z(self.model.machine_model.step_size,manual=True))
        self.shortcut_manager.add_shortcut('Ctrl+Up', 'Increase step size', self.model.machine_model.increase_step_size)
        self.shortcut_manager.add_shortcut('Ctrl+Down', 'Decrease step size', self.model.machine_model.decrease_step_size)

        self.shortcut_manager.add_shortcut('1','Large refuel pressure decrease', lambda: self.controller.set_relative_refuel_pressure(-1,manual=True))
        self.shortcut_manager.add_shortcut('2','Small refuel pressure decrease', lambda: self.controller.set_relative_refuel_pressure(-0.1,manual=True))
        self.shortcut_manager.add_shortcut('3','Small refuel pressure increase', lambda: self.controller.set_relative_refuel_pressure(0.1,manual=True))
        self.shortcut_manager.add_shortcut('4','Large refuel pressure increase', lambda: self.controller.set_relative_refuel_pressure(1,manual=True))
        
        self.shortcut_manager.add_shortcut('5','Set refuel pressure to 0.', lambda: self.controller.set_absolute_refuel_pressure(0.3,manual=True))
        self.shortcut_manager.add_shortcut('6','Large print pressure decrease', lambda: self.controller.set_relative_print_pressure(-1,manual=True))
        self.shortcut_manager.add_shortcut('7','Small print pressure decrease', lambda: self.controller.set_relative_print_pressure(-0.1,manual=True))
        self.shortcut_manager.add_shortcut('8','Small print pressure increase', lambda: self.controller.set_relative_print_pressure(0.1,manual=True))
        self.shortcut_manager.add_shortcut('9','Large print pressure increase', lambda: self.controller.set_relative_print_pressure(1,manual=True))
        self.shortcut_manager.add_shortcut('0','Set print pressure to 0.6', lambda: self.controller.set_absolute_print_pressure(0.6,manual=True))

        self.shortcut_manager.add_shortcut('Shift+s','Save new location', lambda: self.add_new_location())
        self.shortcut_manager.add_shortcut('Shift+d','Modify location', lambda: self.modify_location())
        self.shortcut_manager.add_shortcut('l','Move to location', lambda: self.move_to_location(manual=True))
    
        self.shortcut_manager.add_shortcut('g','Close gripper', lambda: self.controller.close_gripper())
        self.shortcut_manager.add_shortcut('Shift+g','Open gripper', lambda: self.controller.open_gripper())

        self.shortcut_manager.add_shortcut('Shift+p','Print Array', lambda: self.well_plate_widget.start_print_array())
        self.shortcut_manager.add_shortcut('Shift+r','Reset Single Array', lambda: self.reset_single_array())
        self.shortcut_manager.add_shortcut('Shift+e','Reset All Arrays', lambda: self.reset_all_arrays())

        self.shortcut_manager.add_shortcut('z','Refuel only 20', lambda: self.controller.refuel_only(20))  
        self.shortcut_manager.add_shortcut('x','Refuel only 5', lambda: self.controller.refuel_only(5))  
        self.shortcut_manager.add_shortcut('c','Print only 5', lambda: self.controller.print_only(5))
        self.shortcut_manager.add_shortcut('v','Print only 20', lambda: self.controller.print_only(20))
        
        self.shortcut_manager.add_shortcut('w','Print 1 droplet', lambda: self.controller.print_droplets(1))
        self.shortcut_manager.add_shortcut('e','Print 5 droplets', lambda: self.controller.print_droplets(5))
        self.shortcut_manager.add_shortcut('r','Print 10 droplets', lambda: self.controller.print_droplets(10))
        self.shortcut_manager.add_shortcut('t','Print 20 droplets', lambda: self.controller.print_droplets(20))
        # self.shortcut_manager.add_shortcut('Shift+s','Reset Print Syringe', lambda: self.controller.reset_print_syringe())
        self.shortcut_manager.add_shortcut('Shift+i','See calibrations', lambda: self.show_calibrations())
        self.shortcut_manager.add_shortcut('Ctrl+Shift+A','Audit Timeline', lambda: self.show_experiment_audit())
        self.shortcut_manager.add_shortcut('Esc', 'Pause Action', lambda: self.pause_machine())
        self.shortcut_manager.add_shortcut('Shift+1','LED On', lambda: self.controller.LED_on())
        self.shortcut_manager.add_shortcut('Shift+2','LED Off', lambda: self.controller.LED_off())
        self.shortcut_manager.add_shortcut('Shift+3','Start Refuel Camera', lambda: self.controller.start_refuel_camera())
        self.shortcut_manager.add_shortcut('Shift+4','Stop Refuel Camera', lambda: self.controller.stop_refuel_camera())
        self.shortcut_manager.add_shortcut('Shift+5','Reset Print Syringe', lambda: self.controller.reset_print_syringe())
        self.shortcut_manager.add_shortcut('Shift+6','Reset Refuel Syringe', lambda: self.controller.reset_refuel_syringe())
        self.shortcut_manager.add_shortcut('Shift+7','Home Regulators', lambda: self.controller.home_regulators())

    def make_transparent_icon(self):
        transparent_image = QtGui.QImage(1, 1, QtGui.QImage.Format_ARGB32)
        transparent_image.fill(QtCore.Qt.transparent)
        transparent_pixmap = QtGui.QPixmap.fromImage(transparent_image)
        transparent_icon = QtGui.QIcon(transparent_pixmap)
        return transparent_icon

    def make_window_icon(self):
        icon_path = os.path.join(self.script_dir, 'Presets', 'LabCraft_icon.png')
        if os.path.exists(icon_path):
            return QtGui.QIcon(icon_path)
        return self.make_transparent_icon()

    def show_well_plate_tab(self):
        """Switch the center tab widget to the Well Plate tab."""
        if not hasattr(self, "tab_widget") or not hasattr(self, "well_plate_widget"):
            return
        idx = self.tab_widget.indexOf(self.well_plate_widget)
        if idx != -1:
            self.tab_widget.setCurrentIndex(idx)

    def _create_calibrations_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        optics_group = QtWidgets.QGroupBox("Droplet Imager Optics Calibration")
        optics_layout = QtWidgets.QVBoxLayout(optics_group)
        optics_layout.setContentsMargins(12, 12, 12, 12)
        optics_layout.setSpacing(8)

        self.optics_calibration_factor_label = QtWidgets.QLabel()
        self.optics_calibration_factor_label.setWordWrap(True)
        self.optics_calibration_config_label = QtWidgets.QLabel()
        self.optics_calibration_config_label.setWordWrap(True)
        self.optics_calibration_config_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        button_row = QtWidgets.QHBoxLayout()
        self.start_guided_optics_calibration_button = QtWidgets.QPushButton("Start Guided Optics Calibration")
        self.start_guided_optics_calibration_button.clicked.connect(self._start_guided_optics_calibration)
        self.open_manual_optics_calibration_button = QtWidgets.QPushButton("Open Manual Optics Calibration")
        self.open_manual_optics_calibration_button.clicked.connect(self._open_manual_optics_calibration)
        self.refresh_optics_calibration_button = QtWidgets.QPushButton("Refresh")
        self.refresh_optics_calibration_button.clicked.connect(self._refresh_optics_calibration_display)
        button_row.addWidget(self.start_guided_optics_calibration_button)
        button_row.addWidget(self.open_manual_optics_calibration_button)
        button_row.addWidget(self.refresh_optics_calibration_button)
        button_row.addStretch(1)

        optics_layout.addWidget(self.optics_calibration_factor_label)
        optics_layout.addWidget(self.optics_calibration_config_label)
        optics_layout.addLayout(button_row)
        layout.addWidget(optics_group)
        layout.addStretch(1)
        self._refresh_optics_calibration_display()
        return tab

    def _refresh_optics_calibration_display(self):
        cam = getattr(self.model, "droplet_camera_model", None)
        value = 1.5696
        source = "default"
        step_source = "preset"
        config_path = "local/droplet_imager_optics.json"
        if cam is not None:
            getter = getattr(cam, "get_um_per_pixel", None)
            source_getter = getattr(cam, "get_um_per_pixel_source", None)
            step_source_getter = getattr(cam, "get_step_conversion_source", None)
            path_getter = getattr(cam, "optics_config_path", None)
            try:
                if callable(getter):
                    value = float(getter())
            except Exception:
                value = 1.5696
            try:
                if callable(source_getter):
                    source = str(source_getter())
            except Exception:
                source = "default"
            try:
                if callable(step_source_getter):
                    step_source = str(step_source_getter())
            except Exception:
                step_source = "preset"
            try:
                if callable(path_getter):
                    config_path = str(path_getter())
            except Exception:
                pass

        if hasattr(self, "optics_calibration_factor_label"):
            self.optics_calibration_factor_label.setText(
                f"Current micrometer/pixel factor: {value:.6f} um/pixel ({source}).\n"
                f"Current motion conversion: {step_source}."
            )
        if hasattr(self, "optics_calibration_config_label"):
            self.optics_calibration_config_label.setText(f"Config: {config_path}")

    def _open_manual_optics_calibration(self):
        launcher = getattr(getattr(self, "pressure_box", None), "open_manual_optics_calibration", None)
        if callable(launcher):
            launcher()
        else:
            self.popup_message(
                "Optics Calibration Unavailable",
                "The droplet imager launcher is not available yet.",
            )
        self._refresh_optics_calibration_display()

    def _start_guided_optics_calibration(self):
        launcher = getattr(getattr(self, "pressure_box", None), "start_guided_optics_calibration", None)
        if callable(launcher):
            launcher()
        else:
            self.popup_message(
                "Optics Calibration Unavailable",
                "The guided droplet imager optics calibration wizard is not available yet.",
            )
        self._refresh_optics_calibration_display()

    def popup_message(self, title, message):
        """Display a popup message with a title and message."""
        #print(f"Popup message: {title} - {message}")
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(message)
        transparent_icon = self.make_transparent_icon()
        msg.setWindowIcon(transparent_icon)
        msg.exec()

    def popup_options(self, title, message, options):
        dialog = OptionsDialog(title, message, options)
        clicked_option = dialog.exec()
        return clicked_option

    def popup_choice(self, title, message, options, *, default=None):
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(message)
        transparent_icon = self.make_transparent_icon()
        msg.setWindowIcon(transparent_icon)
        buttons = {}
        for option in options:
            role = QtWidgets.QMessageBox.RejectRole if option == "Cancel" else QtWidgets.QMessageBox.ActionRole
            buttons[option] = msg.addButton(option, role)
        default_option = default if default in buttons else (options[0] if options else None)
        if default_option is not None:
            msg.setDefaultButton(buttons[default_option])
        msg.exec()
        clicked = msg.clickedButton()
        for option, button in buttons.items():
            if clicked == button:
                return option
        return default_option
    
    def popup_yes_no(self,title, message):
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        transparent_icon = self.make_transparent_icon()
        msg.setWindowIcon(transparent_icon)
        result = msg.exec()
        return QtWidgets.QMessageBox.StandardButton(result)

    @staticmethod
    def _is_yes_response(response) -> bool:
        if isinstance(response, QtWidgets.QMessageBox.StandardButton):
            return response == QtWidgets.QMessageBox.Yes
        if isinstance(response, int):
            return response == int(QtWidgets.QMessageBox.Yes)
        if isinstance(response, str):
            normalized = response.replace("&", "").strip().lower()
            return normalized in {"yes", "y"}
        return False

    @staticmethod
    def _is_no_response(response) -> bool:
        if isinstance(response, QtWidgets.QMessageBox.StandardButton):
            return response == QtWidgets.QMessageBox.No
        if isinstance(response, int):
            return response == int(QtWidgets.QMessageBox.No)
        if isinstance(response, str):
            normalized = response.replace("&", "").strip().lower()
            return normalized in {"no", "n"}
        return False

    def _get_close_disconnect_timeout_ms(self):
        return getattr(self, "close_disconnect_timeout_ms", self.CLOSE_DISCONNECT_TIMEOUT_MS)

    def _ensure_close_disconnect_signal_hook(self):
        if getattr(self, "_close_disconnect_signal_hooked", False):
            return
        signal = getattr(getattr(self.controller, "machine", None), "disconnect_complete_signal", None)
        if signal is None:
            return
        signal.connect(self._handle_close_disconnect_complete)
        self._close_disconnect_signal_hooked = True

    def _get_close_disconnect_timer(self):
        timer = getattr(self, "_close_disconnect_timer", None)
        if timer is None:
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(self._handle_close_disconnect_timeout)
            self._close_disconnect_timer = timer
        return timer

    def _show_close_disconnect_dialog(self, timed_out: bool = False):
        dialog = getattr(self, "_close_disconnect_dialog", None)
        if dialog is None:
            dialog = QtWidgets.QMessageBox(self)
            dialog.setWindowIcon(self.make_transparent_icon())
            dialog.buttonClicked.connect(self._handle_close_disconnect_dialog_clicked)
            self._close_disconnect_dialog = dialog

        dialog.setWindowTitle("Closing Application")
        dialog.setIcon(QtWidgets.QMessageBox.Information)
        dialog.setWindowModality(QtCore.Qt.ApplicationModal)

        if timed_out:
            dialog.setText("Still disconnecting from the MCU.")
            dialog.setInformativeText(
                "The application is still waiting for the MCU to finish disconnecting. "
                "You can keep waiting or cancel closing and return to the application."
            )
            dialog.setStandardButtons(QtWidgets.QMessageBox.Retry | QtWidgets.QMessageBox.Cancel)

            keep_waiting_button = dialog.button(QtWidgets.QMessageBox.Retry)
            if keep_waiting_button is not None:
                keep_waiting_button.setText("Keep Waiting")

            cancel_button = dialog.button(QtWidgets.QMessageBox.Cancel)
            if cancel_button is not None:
                cancel_button.setText("Cancel Close")
        else:
            dialog.setText("Disconnecting from the MCU and closing the application...")
            dialog.setInformativeText(
                "The application will close automatically when the MCU confirms that "
                "disconnect is complete."
            )
            dialog.setStandardButtons(QtWidgets.QMessageBox.NoButton)

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _dismiss_close_disconnect_dialog(self):
        dialog = getattr(self, "_close_disconnect_dialog", None)
        if dialog is None:
            return

        try:
            dialog.hide()
            dialog.close()
        except Exception:
            pass

        try:
            dialog.deleteLater()
        except Exception:
            pass

        self._close_disconnect_dialog = None

    def _cancel_pending_close_disconnect(self):
        self._close_disconnect_pending = False
        self._close_disconnect_timeout_prompt = False
        self._close_after_disconnect = False

        timer = getattr(self, "_close_disconnect_timer", None)
        if timer is not None:
            timer.stop()

        self._dismiss_close_disconnect_dialog()

    def _cancel_app_update_request(self):
        self._app_update_close_requested = False
        cancel_update = getattr(self.controller, "cancel_app_update_process", None)
        if callable(cancel_update):
            cancel_update()

    def _begin_close_disconnect(self):
        self._ensure_close_disconnect_signal_hook()
        self.disconnected = False
        self._close_disconnect_pending = True
        self._close_after_disconnect = False
        self._close_disconnect_timeout_prompt = False
        self._show_close_disconnect_dialog(timed_out=False)
        self._get_close_disconnect_timer().start(self._get_close_disconnect_timeout_ms())
        self.controller.disconnect_machine()

    @Slot()
    def _handle_close_disconnect_timeout(self):
        if not getattr(self, "_close_disconnect_pending", False):
            return

        self._close_disconnect_timeout_prompt = True
        self._show_close_disconnect_dialog(timed_out=True)

    @Slot(QtWidgets.QAbstractButton)
    def _handle_close_disconnect_dialog_clicked(self, button):
        if not getattr(self, "_close_disconnect_pending", False):
            return

        dialog = getattr(self, "_close_disconnect_dialog", None)
        if dialog is None:
            return

        standard_button = dialog.standardButton(button)
        if standard_button == QtWidgets.QMessageBox.Retry:
            self._close_disconnect_timeout_prompt = False
            self._show_close_disconnect_dialog(timed_out=False)
            self._get_close_disconnect_timer().start(self._get_close_disconnect_timeout_ms())
            return

        if standard_button == QtWidgets.QMessageBox.Cancel:
            self._cancel_pending_close_disconnect()
            if getattr(self, "_app_update_close_requested", False):
                self._cancel_app_update_request()
                self.popup_message(
                    "Update Cancelled",
                    "Application update was cancelled. The app will remain open.",
                )

    @Slot()
    def _handle_close_disconnect_complete(self):
        if not getattr(self, "_close_disconnect_pending", False):
            return

        self._close_disconnect_pending = False
        self._close_disconnect_timeout_prompt = False
        self._close_after_disconnect = True

        timer = getattr(self, "_close_disconnect_timer", None)
        if timer is not None:
            timer.stop()

        self._dismiss_close_disconnect_dialog()
        self.close()
    
    def popup_input(self,title, message):
        text, ok = QtWidgets.QInputDialog.getText(self, title, message)
        if ok:
            return text
        else:
            return None

    def request_app_update(self):
        """Launch the standalone updater, then close through the normal path."""
        check_getter = getattr(self.controller, "get_last_app_update_check_result", None)
        if callable(check_getter):
            check_result = check_getter()
            if check_result is None:
                self.popup_message("Check for Updates", "Check for updates before starting an app update.")
                return False
            if getattr(check_result, "status", "") != "update_available":
                self.popup_message("No Update Available", getattr(check_result, "message", "No app update is available."))
                return False

        response = self.popup_yes_no(
            "Update App",
            "The app will close, update the application code, and reopen. "
            "A LabCraft updater window will show progress. Firmware will not be updated. Continue?",
        )
        if not self._is_yes_response(response):
            return False

        blockers_getter = getattr(self.controller, "get_app_update_blockers", None)
        blockers = blockers_getter() if callable(blockers_getter) else []
        if blockers:
            message = "Application update cannot start right now:\n\n" + "\n".join(
                f"- {blocker}" for blocker in blockers
            )
            self.popup_message("Cannot Update App", message)
            return False

        launcher = getattr(self.controller, "launch_app_updater", None)
        if not callable(launcher):
            self.popup_message(
                "Cannot Update App",
                "The controller does not support application updates.",
            )
            return False

        ok, message = launcher(wait_pid=os.getpid())
        if not ok:
            self.popup_message("Cannot Update App", str(message or "Updater could not be started."))
            return False

        self._app_update_close_requested = True
        self.close()
        return True

    def request_app_update_check(self):
        blockers_getter = getattr(self.controller, "get_app_update_blockers", None)
        blockers = blockers_getter() if callable(blockers_getter) else []
        if blockers:
            message = "Cannot check for updates right now:\n\n" + "\n".join(
                f"- {blocker}" for blocker in blockers
            )
            self.popup_message("Cannot Check for Updates", message)
            return False

        starter = getattr(self.controller, "start_app_update_check", None)
        if not callable(starter):
            self.popup_message(
                "Cannot Check for Updates",
                "The controller does not support application update checks.",
            )
            return False

        ok, message = starter()
        if not ok:
            self.popup_message("Cannot Check for Updates", str(message or "Update check could not be started."))
            return False
        return True

    def _latest_app_update_result_path(self):
        repo_root = getattr(self.controller, "_repo_root", None)
        if repo_root is None:
            repo_root = Path(self.script_dir).parent
        return Path(repo_root) / "local" / "update_logs" / "latest_update_result.json"

    def show_pending_app_update_result_after_startup(self, delay_ms=500):
        QTimer.singleShot(delay_ms, self.show_pending_app_update_result)

    def show_pending_app_update_result(self):
        path = self._latest_app_update_result_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False
        except Exception:
            try:
                path.unlink()
            except OSError:
                pass
            return False

        message = self._format_app_update_result_message(payload)
        self.popup_message("Application Update Result", message)

        try:
            path.unlink()
        except OSError:
            pass

        return True

    @staticmethod
    def _format_app_update_result_message(payload):
        status = str(payload.get("status") or "")
        message = str(payload.get("message") or "Application update finished.")
        before_sha = str(payload.get("before_sha") or "")
        after_sha = str(payload.get("after_sha") or "")
        log_path = str(payload.get("log_path") or "")
        commits = [str(commit) for commit in (payload.get("commits") or []) if str(commit).strip()]

        lines = [message]
        if status:
            lines.append(f"Status: {status}")
        if before_sha or after_sha:
            lines.append(f"Before: {before_sha or 'unknown'}")
            lines.append(f"After: {after_sha or 'unknown'}")
        if log_path:
            lines.append(f"Log: {log_path}")
        if commits:
            lines.append("")
            lines.append("Updates installed:")
            lines.extend(f"- {commit}" for commit in commits[:10])
            if len(commits) > 10:
                lines.append(f"- ...and {len(commits) - 10} more")
        return "\n".join(lines)

    def show_calibrations(self):
        """Print all printer head calibrations to terminal."""
        for printer_head in self.model.printer_head_manager.get_all_printer_heads():
            #print(f'Printer Head {printer_head.get_stock_id()}')
            print(printer_head.get_prediction_data())

    def show_experiment_audit(self):
        """Open the read-only experiment audit timeline window."""
        window = getattr(self, "audit_timeline_window", None)
        if window is None:
            window = AuditTimelineWindow(self, model=self.model)
            self.audit_timeline_window = window
        else:
            window.model = self.model
            window.refresh()

        window.show()
        window.raise_()
        window.activateWindow()
        
    def reset_single_array(self):
        """Reset a single array."""
        active_printer_head = self.model.rack_model.get_gripper_printer_head()
        if active_printer_head == None:
            self.popup_message('Cannot reset:','Only resets the array for the loaded printer head')
            return
        else:
            response = self.popup_yes_no('Reset Array','Are you sure you want to reset the current array?')
            if self._is_yes_response(response):
                self.controller.reset_single_array()

    def reset_all_arrays(self):
        """Reset all arrays."""
        response = self.popup_yes_no('Reset All Arrays','Are you sure you want to reset all arrays?')
        if self._is_yes_response(response):
            self.controller.reset_all_arrays()
    
    def pause_machine(self):
        """Pause the machine."""
        self.controller.pause_commands()
        response = self.popup_yes_no('Pause','Execution paused. Do you want to resume?')
        if self._is_yes_response(response):
            print('Resuming execution')
            self.controller.resume_commands()
            return
        else:
            print('Clearing Queue')
            self.controller.clear_command_queue()
            # self.controller.reset_acceleration()

    def add_new_location(self):
        """Save the current location information."""
        name = self.popup_input("Save Location","Enter the name of the location")
        if name is not None:
            self.controller.add_new_location(name)
        ansewer = self.popup_yes_no("Write to file","Would you like to write the location to a file?")
        if self._is_yes_response(ansewer):
            self.controller.save_locations()

    def modify_location(self):
        """Modify a saved location."""
        name = self.popup_options("Modify Location","Select a location to modify",self.model.location_model.get_location_names())
        if name is not None:
            self.controller.modify_location(name)
        ansewer = self.popup_yes_no("Write to file","Would you like to write the location to a file?")
        if self._is_yes_response(ansewer):
            self.controller.save_locations()

    def move_to_location(self,location=False,direct=True,safe_y=False,manual=False):
        """Move the machine to a saved location."""
        if len(self.model.location_model.get_location_names()) == 0:
            self.popup_message("No Locations","There are no saved locations")
            return
        if self.model.machine_model.motors_enabled == False or self.model.machine_model.motors_homed == False:
            self.popup_message("Motors Not Enabled","Please enable and home the motors before moving to a location")
            return
        if not location:
            name = self.popup_options("Move to Location","Select a location to move to",self.model.location_model.get_location_names())
        else:
            name = location
        if name is not None:
            self.controller.move_to_location(name,direct=direct,safe_y=safe_y,manual=manual)

    def disconnect_successful(self):
        self.disconnected = True

    def complete_experiment_design(self, *, load_progress: bool = False):
        """Handle completion of experiment design."""
        print("[MainWindow] Experiment design completed.")
        plate_name = self.model.experiment_model.metadata.get("plate_name")
        self.model.load_experiment_from_model(plate_name=plate_name, load_progress=load_progress)
    
    def closeEvent(self, event):
        """Handle the window close event."""
        if getattr(self, "_close_after_disconnect", False):
            self._close_after_disconnect = False
            event.accept()
            return

        if getattr(self, "_close_disconnect_pending", False):
            event.ignore()
            self._show_close_disconnect_dialog(
                timed_out=getattr(self, "_close_disconnect_timeout_prompt", False)
            )
            return

        update_close_requested = getattr(self, "_app_update_close_requested", False)
        if self.model.machine_model.is_connected():
            if update_close_requested:
                self._begin_close_disconnect()
                event.ignore()
                return

            response = self.popup_yes_no('Close Application','Disconnect from the machine and close the application?')
            if not self._is_yes_response(response):
                event.ignore()
                return

            self._begin_close_disconnect()
            event.ignore()
            return
        # if self.model.machine_model.is_balance_connected():
        #     self.controller.disconnect_balance()
        #     print('Disconnected balance')

        event.accept()
    @Slot(str)
    def on_require_gripper_confirmation(self, action: str):
        # action is "OPEN" or "CLOSE"
        verb = "open" if action.upper() == "OPEN" else "close"

        m = QMessageBox(self)
        m.setWindowTitle("Gripper confirmation required")
        m.setIcon(QMessageBox.Warning)
        m.setText(
            f"The gripper may stick after being idle.\n\n"
            f"Please manually {verb} the gripper now.\n\n"
            f"When done, click Continue to proceed."
        )
        m.setStandardButtons(QMessageBox.Ok)
        m.setDefaultButton(QMessageBox.Ok)
        m.setModal(True)
        m.exec()  # blocks until user clicks OK

        # Tell the Machine it can proceed
        self.controller.machine.confirm_gripper_ready()

class ConnectionWidget(QGroupBox):
    connect_machine_requested = QtCore.Signal(str)
    connect_balance_requested = QtCore.Signal(str)

    def __init__(self, main_window, model, controller):
        super().__init__("CONNECTION")
        self.main_window = main_window
        self.color_dict = getattr(
            self.main_window, "color_dict",
            {"dark_blue": "#1b3a57", "light_blue": "#3b82f6", "mid_gray": "#6e6e6e"}
        )
        self.model = model
        self.controller = controller

        # Decide mode from profile (adjust attribute name to your actual profile)
        prof = getattr(self.main_window, "profile", None)
        self.legacy_mode = prof.name == "legacy" if prof else True

        # Defaults
        self.machine_default = self.model.get_default_machine_port()
        self.balance_default = self.model.get_default_balance_port()
        self._machine_disconnect_pending = False

        # # Fixed on-board port (e.g., "/dev/ttyACM0" on the Pi)
        # self.fixed_port = self.model.get_default_machine_port()  # must return a string

        self.init_ui()

        # Model → View
        self.model.machine_model.machine_state_updated.connect(
            self.update_machine_connect_button
        )
        self.controller.machine.disconnect_complete_signal.connect(
            self._handle_machine_disconnect_complete
        )

        if self.legacy_mode:
            self.model.machine_model.ports_updated.connect(self.on_ports_updated)
            self.model.machine_model.balance_state_updated.connect(self.update_balance_connect_button)

            # Periodic refresh only in legacy mode
            self._port_timer = QtCore.QTimer(self)
            self._port_timer.timeout.connect(self.controller.update_available_ports)
            self._port_timer.start(1500)

            # Initial populate
            self.controller.update_available_ports()

        # Optional: if your model can change the default port at runtime,
        # hook a signal for that (only if it exists).
        if hasattr(self.model.machine_model, "default_port_changed"):
            self.model.machine_model.default_port_changed.connect(self.set_port)

        # Signals: View → Controller
        self.connect_machine_requested.connect(self.controller.connect_machine)
        if self.legacy_mode:
            self.connect_balance_requested.connect(self.controller.connect_balance)
        # Initialize current state
        self.update_machine_connect_button(self.model.machine_model.machine_connected)
        if self.legacy_mode:
            self.update_balance_connect_button(self.model.machine_model.balance_connected)

    # def init_ui(self):
    #     layout = QGridLayout()
    #     self.setLayout(layout)

    #     # Header row
    #     layout.addWidget(QLabel("Device"), 0, 0)
    #     layout.addWidget(QLabel("Port"),   0, 1)
    #     layout.addWidget(QLabel("Connect"),0, 2)

    #     # Machine row
    #     self.machine_label = QLabel("Machine")
    #     self.port_label = QLabel(self.fixed_port or "Auto")
    #     self.port_label.setToolTip("Fixed on-board serial port")
    #     self.port_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

    #     self.machine_connect_button = QPushButton()
    #     self.machine_connect_button.setCheckable(True)
    #     self.machine_connect_button.setFocusPolicy(QtCore.Qt.NoFocus)
    #     self.machine_connect_button.clicked.connect(self.request_machine_connect_change)

    #     layout.addWidget(self.machine_label,          1, 0)
    #     layout.addWidget(self.port_label,             1, 1)
    #     layout.addWidget(self.machine_connect_button, 1, 2)

    def init_ui(self):
        layout = QGridLayout()
        self.setLayout(layout)

        layout.addWidget(QLabel("Device"), 0, 0)
        layout.addWidget(QLabel("Port"),   0, 1)
        layout.addWidget(QLabel("Connect"),0, 2)

        if not self.legacy_mode:
            # ----- CURRENT MODE (unchanged behavior) -----
            fixed_port = self.machine_default
            self.machine_label = QLabel("Machine")
            self.port_label = QLabel(fixed_port or "Auto")
            self.port_label.setToolTip("Fixed on-board serial port")
            self.port_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

            self.machine_connect_button = QPushButton()
            self.machine_connect_button.setCheckable(True)
            self.machine_connect_button.setFocusPolicy(QtCore.Qt.NoFocus)
            self.machine_connect_button.clicked.connect(self.request_machine_connect_change)

            layout.addWidget(self.machine_label,          1, 0)
            layout.addWidget(self.port_label,             1, 1)
            layout.addWidget(self.machine_connect_button, 1, 2)
            return
        
        # ----- LEGACY MODE (dropdowns) -----
        self.machine_label = QLabel("Machine")
        self.machine_port_combo = RefreshingComboBox()
        self.machine_port_combo.aboutToShowPopup.connect(self.controller.update_available_ports)

        self.machine_connect_button = QPushButton()
        self.machine_connect_button.setCheckable(True)
        self.machine_connect_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.machine_connect_button.clicked.connect(self.request_machine_connect_change)

        layout.addWidget(self.machine_label,          1, 0)
        layout.addWidget(self.machine_port_combo,     1, 1)
        layout.addWidget(self.machine_connect_button, 1, 2)

        self.balance_label = QLabel("Balance")
        self.balance_port_combo = RefreshingComboBox()
        self.balance_port_combo.aboutToShowPopup.connect(self.controller.update_available_ports)

        self.balance_connect_button = QPushButton()
        self.balance_connect_button.setCheckable(True)
        self.balance_connect_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.balance_connect_button.clicked.connect(self.request_balance_connect_change)

        layout.addWidget(self.balance_label,          2, 0)
        layout.addWidget(self.balance_port_combo,     2, 1)
        layout.addWidget(self.balance_connect_button, 2, 2)

        # Pre-populate with defaults even before scan results
        self._set_combo_items(self.machine_port_combo, [], self.machine_default)
        self._set_combo_items(self.balance_port_combo, [], self.balance_default)

    def _set_combo_items(self, combo, ports: list[str], preferred: str):
        combo.blockSignals(True)
        current = combo.currentText().strip()

        combo.clear()
        # if preferred and preferred not in ports:
        #     combo.addItem(preferred)  # keep default visible even if not currently present
        # for p in ports:
        #     if p != preferred:
        #         combo.addItem(p)
        for p in ports:
            combo.addItem(p)

        # choose selection: current -> preferred -> first
        target = current or preferred
        if target:
            idx = combo.findText(target)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    @QtCore.Slot(list)
    def on_ports_updated(self, ports: list[str]):
        self._set_combo_items(self.machine_port_combo, ports, self.machine_default)
        if self.legacy_mode:
            self._set_combo_items(self.balance_port_combo, ports, self.balance_default)


    def set_port(self, port: str):
        """Update the displayed fixed port (and internal copy)."""
        self.fixed_port = port or "Auto"
        self.port_label.setText(self.fixed_port)

    def request_machine_connect_change(self):
        """Toggle connect/disconnect."""
        if self._machine_disconnect_pending:
            return
        if self.model.machine_model.machine_connected:
            self._set_machine_disconnect_pending(True)
            self.controller.disconnect_machine()
        else:
            self.connect_machine()

    @QtCore.Slot()
    def _handle_machine_disconnect_complete(self):
        self._set_machine_disconnect_pending(False)

    def _set_machine_disconnect_pending(self, pending: bool):
        self._machine_disconnect_pending = pending
        self.update_machine_connect_button(self.model.machine_model.machine_connected)

    # def connect_machine(self):
    #     """Emit the fixed port to controller; no dropdown involved."""
    #     port = self.fixed_port or self.model.get_default_machine_port()
    #     self.connect_machine_requested.emit(port)

    def connect_machine(self):
        if not self.legacy_mode:
            port = self.machine_default or self.model.get_default_machine_port()
        else:
            port = self.machine_port_combo.currentText().strip()

        if not port:
            self.controller.error_occurred_signal.emit("Please select a machine (MCU) port.")
            return

        # Optional: persist selection if your model supports it
        if hasattr(self.model, "set_default_machine_port"):
            self.model.set_default_machine_port(port)

        self.connect_machine_requested.emit(port)

    # def update_machine_connect_button(self, machine_connected: bool):
    #     """Set button text/color based on connection state."""
    #     if machine_connected:
    #         self.machine_connect_button.setText("Disconnect")
    #         self.machine_connect_button.setChecked(True)
    #         self.machine_connect_button.setStyleSheet(
    #             f"background-color: {self.color_dict['dark_blue']}; color: white;"
    #         )
    #     else:
    #         self.machine_connect_button.setText("Connect")
    #         self.machine_connect_button.setChecked(False)
    #         self.machine_connect_button.setStyleSheet(
    #             f"background-color: {self.color_dict['light_blue']}; color: white;"
    #         )
    def update_machine_connect_button(self, machine_connected: bool):
        if not machine_connected and self._machine_disconnect_pending:
            self._machine_disconnect_pending = False

        if self._machine_disconnect_pending:
            disconnecting_color = self.color_dict.get(
                "mid_gray",
                self.color_dict.get("dark_gray", "#6e6e6e"),
            )
            self.machine_connect_button.setText("Disconnecting...")
            self.machine_connect_button.setChecked(True)
            self.machine_connect_button.setEnabled(False)
            self.machine_connect_button.setStyleSheet(
                f"background-color: {disconnecting_color}; color: white;"
            )
            if self.legacy_mode:
                self.machine_port_combo.setEnabled(False)
            return

        self.machine_connect_button.setEnabled(True)
        if machine_connected:
            self.machine_connect_button.setText("Disconnect")
            self.machine_connect_button.setChecked(True)
            self.machine_connect_button.setStyleSheet(
                f"background-color: {self.color_dict['dark_blue']}; color: white;"
            )
            if self.legacy_mode:
                self.machine_port_combo.setEnabled(False)
        else:
            self.machine_connect_button.setText("Connect")
            self.machine_connect_button.setChecked(False)
            self.machine_connect_button.setStyleSheet(
                f"background-color: {self.color_dict['light_blue']}; color: white;"
            )
            if self.legacy_mode:
                self.machine_port_combo.setEnabled(True)

    # --------- Balance connect/disconnect ----------
    def request_balance_connect_change(self):
        if self.model.machine_model.balance_connected:
            self.controller.disconnect_balance()
        else:
            self.connect_balance()

    def connect_balance(self):
        port = self.balance_port_combo.currentText().strip()
        if not port:
            self.controller.error_occurred_signal.emit("Please select a balance port.")
            return

        if hasattr(self.model, "set_default_balance_port"):
            self.model.set_default_balance_port(port)

        self.connect_balance_requested.emit(port)

    def update_balance_connect_button(self, balance_connected: bool):
        if not self.legacy_mode:
            return

        if balance_connected:
            self.balance_connect_button.setText("Disconnect")
            self.balance_connect_button.setChecked(True)
            self.balance_connect_button.setStyleSheet(
                f"background-color: {self.color_dict['dark_blue']}; color: white;"
            )
            self.balance_port_combo.setEnabled(False)
        else:
            self.balance_connect_button.setText("Connect")
            self.balance_connect_button.setChecked(False)
            self.balance_connect_button.setStyleSheet(
                f"background-color: {self.color_dict['light_blue']}; color: white;"
            )
            self.balance_port_combo.setEnabled(True)

class CustomSpinBox(QtWidgets.QDoubleSpinBox):
    valueChangedByStep = QtCore.Signal(int)
    def __init__(self,possible_steps, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.values = possible_steps
        self.setDecimals(0)

    def stepBy(self, steps):
        current_index = self.values.index(self.value())
        new_index = max(0, min(current_index + steps, len(self.values) - 1))
        self.setValue(self.values[new_index])
        self.valueChangedByStep.emit(steps)

class MotorPositionWidget(QGroupBox):
    home_requested = QtCore.Signal()  # Signal to request homing
    toggle_motor_requested = QtCore.Signal()  # Signal to toggle motor state

    def __init__(self, main_window, model, controller):
        super().__init__('POSITIONS')
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.controller = controller
        prof = getattr(self.main_window, "profile", None)
        self.legacy_mode = prof.name == "legacy" if prof else True

        self.init_ui()

        # Connect the model's state_updated signal to the update_labels method
        self.model.machine_state_updated.connect(self.update_labels)
        self.model.machine_model.step_size_changed.connect(self.update_step_size)
        self.model.machine_model.motor_state_changed.connect(self.update_motor_button)
        self.model.machine_model.machine_state_updated.connect(self.update_motor_button_state)

        # Connect the signals to the controller's slots
        self.home_requested.connect(self.controller.home_machine)  # Connect the signal to the controller's slot
        self.toggle_motor_requested.connect(self.controller.toggle_motors)


    def init_ui(self):
        """Initialize the user interface."""
        main_layout = QHBoxLayout()  # Main horizontal layout

        # Create a grid layout for motor positions
        grid_layout = QGridLayout()

        # Add column headers
        motor_label = QLabel('Motor')
        current_label = QLabel('Current')
        target_label = QLabel('Target')
        motor_label.setAlignment(Qt.AlignCenter)
        current_label.setAlignment(Qt.AlignCenter)
        target_label.setAlignment(Qt.AlignCenter)

        grid_layout.addWidget(motor_label, 0, 0)
        grid_layout.addWidget(current_label, 0, 1)
        grid_layout.addWidget(target_label, 0, 2)

        # Labels to display motor positions
        self.labels = {
            'X': {'current': QLabel('0'), 'target': QLabel('0')},
            'Y': {'current': QLabel('0'), 'target': QLabel('0')},
            'Z': {'current': QLabel('0'), 'target': QLabel('0')},
            'P': {'current': QLabel('0'), 'target': QLabel('0')},
        }
        if not self.legacy_mode:
            self.labels['R'] = {'current': QLabel('0'), 'target': QLabel('0')}

        row = 1
        for motor, positions in self.labels.items():
            motor_label = QLabel(motor)
            motor_label.setAlignment(Qt.AlignCenter)
            motor_label.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
            grid_layout.addWidget(motor_label, row, 0)
            grid_layout.addWidget(positions['current'], row, 1)
            grid_layout.addWidget(positions['target'], row, 2)
            positions['current'].setAlignment(Qt.AlignCenter)
            positions['current'].setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
            positions['target'].setAlignment(Qt.AlignCenter)
            positions['target'].setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
            row += 1

        # Create a vertical layout for buttons and spin box
        button_layout = QVBoxLayout()

        fixed_width = 100  # Desired fixed width for the buttons
        fixed_height = 30  # Desired fixed height for the buttons

        # Add Toggle Motors button
        self.toggle_motor_button = QtWidgets.QPushButton("Enable Motors")
        self.toggle_motor_button.setFocusPolicy(QtCore.Qt.NoFocus)
        # self.toggle_motor_button.setCheckable(True)
        self.toggle_motor_button.clicked.connect(self.request_toggle_motors)
        self.toggle_motor_button.setFixedWidth(fixed_width)  # Set fixed width
        self.toggle_motor_button.setFixedHeight(fixed_height)  # Set a fixed height
        button_layout.addWidget(self.toggle_motor_button, alignment=Qt.AlignRight)

        # Add Home button
        self.home_button = QtWidgets.QPushButton("Home")
        self.home_button.clicked.connect(self.request_homing)
        self.home_button.setStyleSheet(f"background-color: {self.color_dict['green']}; color: white;")
        self.home_button.setFixedWidth(fixed_width)  # Set fixed width
        self.home_button.setFixedHeight(fixed_height)  # Set a fixed height
        button_layout.addWidget(self.home_button, alignment=Qt.AlignRight)

        # Add Step Size label and spin box
        self.step_size_label = QtWidgets.QLabel("Step Size:")
        self.step_size_label.setFixedHeight(fixed_height)  # Set a fixed height
        self.step_size_label.setFixedWidth(fixed_width)  # Set fixed width
        button_layout.addWidget(self.step_size_label, alignment=Qt.AlignRight)
        self.step_size_input = CustomSpinBox(self.model.machine_model.possible_steps)
        self.step_size_input.setRange(min(self.model.machine_model.possible_steps), max(self.model.machine_model.possible_steps))
        self.step_size_input.setValue(self.model.machine_model.step_size)
        self.step_size_input.setFocusPolicy(QtCore.Qt.NoFocus)
        self.step_size_input.setFixedWidth(fixed_width)  # Set fixed width
        self.step_size_input.setFixedHeight(fixed_height)  # Set a fixed height
        self.step_size_input.valueChangedByStep.connect(self.change_step_size)
        button_layout.addWidget(self.step_size_input, alignment=Qt.AlignRight)

        # Add grid layout and button layout to the main horizontal layout
        main_layout.addLayout(grid_layout)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)
        
        self.update_motor_button(self.model.machine_model.motors_enabled)
        self.update_motor_button_state(self.model.machine_model.is_connected())


    def update_labels(self):
        """Update the labels with the current motor positions."""
        self.labels['X']['current'].setText(str(self.model.machine_model.current_x))
        self.labels['X']['target'].setText(str(self.model.machine_model.target_x))
        self.labels['Y']['current'].setText(str(self.model.machine_model.current_y))
        self.labels['Y']['target'].setText(str(self.model.machine_model.target_y))
        self.labels['Z']['current'].setText(str(self.model.machine_model.current_z))
        self.labels['Z']['target'].setText(str(self.model.machine_model.target_z))
        self.labels['P']['current'].setText(str(self.model.machine_model.current_p))
        self.labels['P']['target'].setText(str(self.model.machine_model.target_p))
        if not self.legacy_mode:
            self.labels['R']['current'].setText(str(self.model.machine_model.current_r))
            self.labels['R']['target'].setText(str(self.model.machine_model.target_r))

    def update_step_size(self, new_step_size):
        """Update the spin box with the new step size."""
        self.step_size_input.setValue(new_step_size)

    def change_step_size(self, steps):
        """Update the model's step size when the spin box value changes."""
        new_step_size = int(self.step_size_input.value())
        self.model.machine_model.set_step_size(new_step_size)

    def request_homing(self):
        """Emit a signal to request the machine to home."""
        self.home_requested.emit()

    def request_toggle_motors(self):
        """Emit a signal to request toggling the motors."""
        self.toggle_motor_requested.emit()

    def update_motor_button_state(self,machine_connected):
        self.toggle_motor_button.setEnabled(machine_connected)
        if not machine_connected:
            self.home_button.setEnabled(False)

    def update_motor_button(self, motors_enabled):
        """Update the motor button text and color based on the motor state."""
        if motors_enabled:
            self.toggle_motor_button.setText("Disable Motors")
            self.toggle_motor_button.setStyleSheet(f"background-color: {self.color_dict['dark_blue']}; color: white;")
            self.home_button.setEnabled(True)
        else:
            self.toggle_motor_button.setText("Enable Motors")
            self.toggle_motor_button.setStyleSheet(f"background-color: {self.color_dict['light_blue']}; color: white;")
            self.home_button.setEnabled(False)


class OpticsCalibrationApproachWizardDialog(QtWidgets.QDialog):
    """Guided, guarded setup for loading a micrometer into the droplet imager."""

    APPROACH_CLEARANCE_STEPS = 1000

    def __init__(self, main_window, model, controller):
        super().__init__(main_window if isinstance(main_window, QtWidgets.QWidget) else None)
        self.main_window = main_window
        self.model = model
        self.controller = controller
        self.machine_model = getattr(model, "machine_model", None)
        self.location_model = getattr(model, "location_model", None)
        self.home_location = self._read_location("home")
        self.camera_location = self._read_location("camera")
        self.approach_z = self._clamp_z(int(self.camera_location["Z"]) - self.APPROACH_CLEARANCE_STEPS)
        self._motion_active = False
        self._cleanup_recommended = False
        self._home_signal_connected = False
        self._step_size_signal_connected = False
        self.step_name = "ready"

        self.setWindowTitle("Guided Optics Calibration Setup")
        self.resize(560, 420)
        self._build_ui()
        self._connect_step_size_signal()
        self._setup_shortcuts()
        self._refresh_step_size_label()
        self._refresh_buttons()

    @staticmethod
    def coerce_location(raw, name):
        if not isinstance(raw, dict):
            raise ValueError(f"Location '{name}' is missing.")
        out = {}
        for axis in ("X", "Y", "Z"):
            if axis not in raw:
                raise ValueError(f"Location '{name}' is missing {axis}.")
            try:
                out[axis] = int(raw[axis])
            except (TypeError, ValueError):
                raise ValueError(f"Location '{name}' has non-numeric {axis}.")
        return out

    @classmethod
    def validate_locations(cls, model):
        location_model = getattr(model, "location_model", None)
        getter = getattr(location_model, "get_location_dict", None)
        if not callable(getter):
            raise ValueError("Location model is not available.")
        home = cls.coerce_location(getter("home"), "home")
        camera = cls.coerce_location(getter("camera"), "camera")
        return home, camera

    def _read_location(self, name):
        getter = getattr(self.location_model, "get_location_dict", None)
        raw = getter(name) if callable(getter) else None
        return self.coerce_location(raw, name)

    def _clamp_z(self, z):
        return int(max(0, min(130000, int(z))))

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.step_label = QtWidgets.QLabel("Ready to begin guided optics calibration.")
        self.step_label.setWordWrap(True)
        self.status_label = QtWidgets.QLabel(
            "This wizard will home the machine, open the gripper, guide micrometer loading, move to camera X/Y at home Z, then stop at the guarded approach height."
        )
        self.status_label.setWordWrap(True)
        self.approach_label = QtWidgets.QLabel(
            f"Guarded approach height: Z={self.approach_z} (camera Z {int(self.camera_location['Z'])} - {self.APPROACH_CLEARANCE_STEPS})."
        )
        self.approach_label.setWordWrap(True)
        layout.addWidget(self.step_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.approach_label)

        self.manual_group = QtWidgets.QGroupBox("Manual Alignment")
        manual_layout = QtWidgets.QGridLayout(self.manual_group)
        manual_layout.setHorizontalSpacing(6)
        manual_layout.setVerticalSpacing(6)
        self.step_size_label = QtWidgets.QLabel("Step: -")
        manual_layout.addWidget(self.step_size_label, 0, 0, 1, 3)
        self.x_minus_btn = QtWidgets.QPushButton("X-")
        self.x_plus_btn = QtWidgets.QPushButton("X+")
        self.y_minus_btn = QtWidgets.QPushButton("Y-")
        self.y_plus_btn = QtWidgets.QPushButton("Y+")
        self.z_up_btn = QtWidgets.QPushButton("Z Up")
        self.z_down_btn = QtWidgets.QPushButton("Z Down")
        self.step_down_btn = QtWidgets.QPushButton("Step -")
        self.step_up_btn = QtWidgets.QPushButton("Step +")
        self.x_minus_btn.clicked.connect(lambda: self.manual_jog("X", -1))
        self.x_plus_btn.clicked.connect(lambda: self.manual_jog("X", 1))
        self.y_minus_btn.clicked.connect(lambda: self.manual_jog("Y", -1))
        self.y_plus_btn.clicked.connect(lambda: self.manual_jog("Y", 1))
        self.z_up_btn.clicked.connect(lambda: self.manual_jog("Z", -1))
        self.z_down_btn.clicked.connect(lambda: self.manual_jog("Z", 1))
        self.step_down_btn.clicked.connect(self.decrease_step_size)
        self.step_up_btn.clicked.connect(self.increase_step_size)
        manual_layout.addWidget(self.x_minus_btn, 1, 0)
        manual_layout.addWidget(self.x_plus_btn, 1, 1)
        manual_layout.addWidget(self.y_minus_btn, 2, 0)
        manual_layout.addWidget(self.y_plus_btn, 2, 1)
        manual_layout.addWidget(self.z_up_btn, 3, 0)
        manual_layout.addWidget(self.z_down_btn, 3, 1)
        manual_layout.addWidget(self.step_down_btn, 4, 0)
        manual_layout.addWidget(self.step_up_btn, 4, 1)
        self.manual_group.hide()
        layout.addWidget(self.manual_group)

        button_row = QtWidgets.QHBoxLayout()
        self.primary_button = QtWidgets.QPushButton("Begin")
        self.primary_button.clicked.connect(self.advance_step)
        self.pause_button = QtWidgets.QPushButton("Pause Machine")
        self.pause_button.clicked.connect(self.pause_machine)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.primary_button)
        button_row.addWidget(self.pause_button)
        button_row.addStretch(1)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

    def _setup_shortcuts(self):
        self._wizard_shortcuts = [
            QShortcut(QKeySequence("Left"), self, activated=lambda: self.manual_jog("X", -1)),
            QShortcut(QKeySequence("Right"), self, activated=lambda: self.manual_jog("X", 1)),
            QShortcut(QKeySequence("Up"), self, activated=lambda: self.manual_jog("Y", 1)),
            QShortcut(QKeySequence("Down"), self, activated=lambda: self.manual_jog("Y", -1)),
            QShortcut(QKeySequence("K"), self, activated=lambda: self.manual_jog("Z", -1)),
            QShortcut(QKeySequence("M"), self, activated=lambda: self.manual_jog("Z", 1)),
            QShortcut(QKeySequence("Ctrl+Up"), self, activated=self.increase_step_size),
            QShortcut(QKeySequence("Ctrl+Down"), self, activated=self.decrease_step_size),
        ]

    def _connect_step_size_signal(self):
        signal = getattr(self.machine_model, "step_size_changed", None)
        if signal is None:
            return
        try:
            signal.connect(self._refresh_step_size_label)
            self._step_size_signal_connected = True
        except Exception:
            self._step_size_signal_connected = False

    def _disconnect_step_size_signal(self):
        if not self._step_size_signal_connected:
            return
        signal = getattr(self.machine_model, "step_size_changed", None)
        try:
            signal.disconnect(self._refresh_step_size_label)
        except Exception:
            pass
        self._step_size_signal_connected = False

    def _connect_home_signal(self):
        signal = getattr(self.machine_model, "home_status_signal", None)
        if signal is None:
            return False
        try:
            signal.connect(self._on_home_complete)
            self._home_signal_connected = True
            return True
        except Exception:
            self._home_signal_connected = False
            return False

    def _disconnect_home_signal(self):
        if not self._home_signal_connected:
            return
        signal = getattr(self.machine_model, "home_status_signal", None)
        try:
            signal.disconnect(self._on_home_complete)
        except Exception:
            pass
        self._home_signal_connected = False

    def _is_yes_response(self, response):
        checker = getattr(self.main_window, "_is_yes_response", None)
        if callable(checker):
            return bool(checker(response))
        return MainWindow._is_yes_response(response)

    def _popup_yes_no(self, title, message):
        popup = getattr(self.main_window, "popup_yes_no", None)
        if callable(popup):
            return popup(title, message)
        return QtWidgets.QMessageBox.question(self, title, message)

    def _popup_message(self, title, message):
        popup = getattr(self.main_window, "popup_message", None)
        if callable(popup):
            popup(title, message)
        else:
            QtWidgets.QMessageBox.information(self, title, message)

    def _commands_idle(self):
        checker = getattr(self.controller, "check_if_all_completed", None)
        try:
            return bool(checker()) if callable(checker) else True
        except Exception:
            return False

    def _current_z(self):
        expected = getattr(self.controller, "expected_position", None)
        if isinstance(expected, dict) and "Z" in expected:
            try:
                return int(expected["Z"])
            except Exception:
                pass
        getter = getattr(self.machine_model, "get_current_position_dict", None)
        try:
            pos = getter() if callable(getter) else {}
            return int(pos.get("Z"))
        except Exception:
            pass
        return int(getattr(self.machine_model, "current_z", self.home_location["Z"]))

    def _step_size(self):
        try:
            return int(getattr(self.machine_model, "step_size"))
        except Exception:
            return 500

    def _refresh_step_size_label(self, *_args):
        if hasattr(self, "step_size_label"):
            self.step_size_label.setText(f"Step: {self._step_size()} steps")

    def _set_status(self, step_text, status_text=None, color=None):
        self.step_label.setText(str(step_text))
        if status_text is not None:
            self.status_label.setText(str(status_text))
        self.status_label.setStyleSheet("" if not color else f"color:{color};")

    def _set_motion_active(self, active):
        self._motion_active = bool(active)
        self._refresh_buttons()

    def _refresh_buttons(self):
        active = bool(self._motion_active)
        manual = self.step_name == "manual_alignment"
        self.primary_button.setEnabled((not active) and self.step_name not in {"failed"})
        self.cancel_button.setEnabled(not active)
        self.pause_button.setEnabled(active)
        self.manual_group.setVisible(manual)
        for widget in (
            self.x_minus_btn,
            self.x_plus_btn,
            self.y_minus_btn,
            self.y_plus_btn,
            self.z_up_btn,
            self.z_down_btn,
            self.step_down_btn,
            self.step_up_btn,
        ):
            widget.setEnabled((not active) and manual)

    def advance_step(self):
        if self._motion_active:
            return
        if self.step_name == "ready":
            self.begin()
        elif self.step_name == "waiting_micrometer":
            self.confirm_micrometer_inserted()
        elif self.step_name == "waiting_waste_holder":
            self.confirm_waste_holder_removed()
        elif self.step_name == "waiting_entry_alignment":
            self.confirm_entry_alignment()
        elif self.step_name == "manual_alignment":
            self.continue_manual_alignment()

    def begin(self):
        if not self._commands_idle():
            self._set_status("Commands still running.", "Wait for the current commands to finish before starting.", "red")
            return
        response = self._popup_yes_no(
            "Begin Guided Optics Calibration",
            "This wizard will home the machine, open the gripper, and move near the imager. Confirm that the area is clear and the micrometer slide is ready.",
        )
        if not self._is_yes_response(response):
            self.reject()
            return
        self.step_name = "homing"
        self.primary_button.setText("Homing...")
        self._set_status("Homing machine.", "Waiting for the home-complete signal.")
        self._set_motion_active(True)
        if not self._connect_home_signal():
            self.fail_step("Home status signal is unavailable.")
            return
        result = self.controller.home_machine()
        if result is False:
            self._disconnect_home_signal()
            self.fail_step("Failed to queue homing.")

    def _on_home_complete(self, *_args):
        self._disconnect_home_signal()
        self._set_motion_active(False)
        self.queue_open_gripper()

    def queue_open_gripper(self):
        self.step_name = "opening_gripper"
        self.primary_button.setText("Opening Gripper...")
        self._set_status("Opening gripper.", "Waiting for the gripper to open.")
        self._set_motion_active(True)
        opener = getattr(self.controller, "open_gripper", None)
        result = opener(handler=self._after_gripper_opened) if callable(opener) else False
        if result is False:
            self.fail_step("Failed to queue gripper open.")

    def _after_gripper_opened(self):
        self._cleanup_recommended = True
        self.step_name = "waiting_micrometer"
        self.primary_button.setText("Micrometer Inserted - Close Gripper")
        self._set_motion_active(False)
        self._set_status(
            "Insert micrometer slide.",
            "Insert the micrometer adapter into the gripper, then continue to close the gripper.",
        )

    def confirm_micrometer_inserted(self):
        if not self._commands_idle():
            self._set_status("Commands still running.", "Wait for the gripper-open command to finish before closing.", "red")
            return
        self.step_name = "closing_gripper"
        self.primary_button.setText("Closing Gripper...")
        self._set_status("Closing gripper.", "Waiting for the micrometer slide to be held.")
        self._set_motion_active(True)
        closer = getattr(self.controller, "close_gripper", None)
        result = closer(handler=self._after_gripper_closed) if callable(closer) else False
        if result is False:
            self.fail_step("Failed to queue gripper close.")

    def _after_gripper_closed(self):
        self.step_name = "waiting_waste_holder"
        self.primary_button.setText("Waste Holder Removed")
        self._set_motion_active(False)
        self._set_status(
            "Remove waste tube holder.",
            "Remove the waste tube holder from the imager area, then continue.",
        )

    def confirm_waste_holder_removed(self):
        response = self._popup_yes_no(
            "Waste Tube Holder Removed",
            "Confirm the waste tube holder has been removed from the droplet imager area.",
        )
        if not self._is_yes_response(response):
            self._set_status(
                "Remove waste tube holder.",
                "The wizard will not move to the imager until this is confirmed.",
                "red",
            )
            return
        self.queue_camera_xy()

    def queue_camera_xy(self):
        if not self._commands_idle():
            self._set_status("Commands still running.", "Wait for the current command to finish before moving to camera X/Y.", "red")
            return
        self.step_name = "moving_camera_xy"
        self.primary_button.setText("Moving To Camera X/Y...")
        self._set_status(
            "Moving to camera X/Y at home Z.",
            f"Target X={self.camera_location['X']}, Y={self.camera_location['Y']}; Z stays at home height.",
        )
        self._set_motion_active(True)
        mover = getattr(self.controller, "set_absolute_XY", None)
        result = (
            mover(
                int(self.camera_location["X"]),
                int(self.camera_location["Y"]),
                manual=True,
                handler=self._after_camera_xy,
            )
            if callable(mover)
            else False
        )
        if result is False:
            self.fail_step("Failed to queue camera X/Y move.")

    def _after_camera_xy(self):
        self.step_name = "waiting_entry_alignment"
        self.primary_button.setText("Confirm Entry Alignment")
        self._set_motion_active(False)
        self._set_status(
            "Confirm micrometer entry alignment.",
            "If the micrometer is lined up with the imager entry, continue. Otherwise choose No in the next prompt to jog manually.",
        )

    def confirm_entry_alignment(self):
        response = self._popup_yes_no(
            "Micrometer Entry Alignment",
            "Is the micrometer lined up with the imager entry position?",
        )
        if self._is_yes_response(response):
            self.queue_guarded_approach()
        else:
            self.enter_manual_alignment()

    def enter_manual_alignment(self):
        self.step_name = "manual_alignment"
        self.primary_button.setText("Continue To Guarded Height")
        self._set_status(
            "Manual alignment.",
            "Jog the machine until the micrometer is lined up. Z jogging is blocked below the guarded approach height.",
        )
        self._refresh_buttons()

    def manual_jog(self, axis, direction):
        if self.step_name != "manual_alignment" or self._motion_active:
            return False
        if not self._commands_idle():
            self._set_status("Commands still running.", "Wait for the current jog to complete before sending another.", "red")
            return False
        axis = str(axis).upper()
        delta = int(direction) * self._step_size()
        if axis == "Z":
            target_z = self._current_z() + delta
            if target_z > self.approach_z:
                self._set_status(
                    "Z jog blocked.",
                    f"Guardrail blocked Z={target_z}; guarded approach limit is Z={self.approach_z}.",
                    "red",
                )
                return False
        method = getattr(self.controller, f"set_relative_{axis}", None)
        if not callable(method):
            self._set_status("Jog unavailable.", f"Controller does not support relative {axis} jogs.", "red")
            return False
        result = method(delta, manual=True)
        if result is False:
            self._set_status("Jog blocked.", f"The controller rejected the {axis} jog.", "red")
            return False
        self._set_status("Manual alignment.", f"Queued {axis} jog of {delta} steps.")
        return True

    def increase_step_size(self):
        method = getattr(self.machine_model, "increase_step_size", None)
        if callable(method):
            method()
        self._refresh_step_size_label()

    def decrease_step_size(self):
        method = getattr(self.machine_model, "decrease_step_size", None)
        if callable(method):
            method()
        self._refresh_step_size_label()

    def continue_manual_alignment(self):
        if not self._commands_idle():
            self._set_status("Commands still running.", "Wait for the current jog to complete before continuing.", "red")
            return
        self.queue_guarded_approach()

    def queue_guarded_approach(self):
        if not self._commands_idle():
            self._set_status("Commands still running.", "Wait for the current command to finish before descending.", "red")
            return
        self.step_name = "guarded_approach"
        self.primary_button.setText("Moving To Guarded Height...")
        self._set_status(
            "Moving to guarded approach height.",
            f"Descending only to Z={self.approach_z}, never to final camera Z={int(self.camera_location['Z'])}.",
        )
        self._set_motion_active(True)
        if self._current_z() == self.approach_z:
            self._after_guarded_approach()
            return
        mover = getattr(self.controller, "set_absolute_Z", None)
        result = mover(self.approach_z, manual=True, handler=self._after_guarded_approach) if callable(mover) else False
        if result is False:
            self.fail_step("Failed to queue guarded Z approach.")

    def _after_guarded_approach(self):
        self.step_name = "approach_complete"
        self._cleanup_recommended = True
        self._set_motion_active(False)
        self.accept()

    def pause_machine(self):
        method = getattr(self.controller, "pause_machine", None)
        if callable(method):
            method()

    def fail_step(self, message):
        self.step_name = "failed"
        self.primary_button.setText("Failed")
        self._set_motion_active(False)
        self._set_status("Guided optics setup failed.", str(message), "red")

    def should_prompt_cleanup(self):
        return bool(self._cleanup_recommended)

    def _cleanup_signal_connections(self):
        self._disconnect_home_signal()
        self._disconnect_step_size_signal()

    def done(self, result):
        self._cleanup_signal_connections()
        super().done(result)

    def reject(self):
        if self._motion_active:
            self._set_status("Motion in progress.", "Pause the machine if needed. Cancel is available between steps.", "red")
            return
        super().reject()

    def closeEvent(self, event):
        self._cleanup_signal_connections()
        super().closeEvent(event)


class PressurePlotBox(QtWidgets.QGroupBox):
    """
    A widget to display the pressure readings and target
    """
    toggle_regulation_requested = QtCore.Signal()
    # update_target_pressure_input = QtCore.Signal(float)
    # update_pulse_width_input = QtCore.Signal(int)
    popup_message_signal = QtCore.Signal(str,str)
    PRINT_PROFILE_PRESSURE_TOLERANCE = 0.005

    def __init__(self, main_window, model,controller):
        super().__init__('PRESSURE')
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.controller = controller
        self._pressure_spinbox_focus_targets = {}
        self._pressure_spinboxes = []
        self._active_spinbox_highlight = None
        self._print_profile_apply_pending = False

        prof = getattr(self.main_window, "profile", None)
        self.legacy_mode = prof.name == "legacy" if prof else True


        self.init_ui()
        self.model.machine_model.machine_state_updated.connect(self.update_regulation_button_state)
        self.model.machine_model.regulation_state_changed.connect(self.update_regulation_button)
        self.model.machine_model.printing_parameters_updated.connect(self.update_printing_controls)
        self.toggle_regulation_requested.connect(self.controller.toggle_regulation)
        # self.update_target_pressure_input.connect(self.controller.set_absolute_pressure)
        # self.update_pulse_width_input.connect(self.controller.set_pulse_width)

        self.update_regulation_button_state(self.model.machine_model.is_connected())
        self.popup_message_signal.connect(self.main_window.popup_message)
        self.update_printing_controls()

    @staticmethod
    def _spinbox_is_being_edited(spinbox):
        """Return True while a spinbox has keyboard focus for an in-progress edit."""
        line_edit = spinbox.lineEdit() if hasattr(spinbox, "lineEdit") else None
        return spinbox.hasFocus() or (line_edit is not None and line_edit.hasFocus())

    @staticmethod
    def _finish_spinbox_edit(spinbox):
        """End active editing so global keyboard shortcuts become active again."""
        spinbox.clearFocus()

    def _configure_editable_spinbox(self, spinbox, handler):
        """Configure a pressure control spinbox for guarded edits."""
        spinbox.setKeyboardTracking(False)
        spinbox.setFocusPolicy(QtCore.Qt.StrongFocus)
        spinbox.editingFinished.connect(handler)
        spinbox.installEventFilter(self)
        self._pressure_spinbox_focus_targets[spinbox] = spinbox
        self._pressure_spinboxes.append(spinbox)

        line_edit = spinbox.lineEdit() if hasattr(spinbox, "lineEdit") else None
        if line_edit is not None:
            line_edit.installEventFilter(self)
            self._pressure_spinbox_focus_targets[line_edit] = spinbox

    def _refresh_spinbox_edit_highlight(self):
        """Show a thin focus frame only around the actively edited spinbox."""
        active_spinbox = next(
            (spinbox for spinbox in self._pressure_spinboxes if self._spinbox_is_being_edited(spinbox)),
            None,
        )

        if active_spinbox is None:
            self._active_spinbox_highlight = None
            self.edit_focus_frame.hide()
            return

        self._active_spinbox_highlight = active_spinbox
        self.edit_focus_frame.setWidget(active_spinbox)
        self.edit_focus_frame.show()
        self.edit_focus_frame.raise_()

    def eventFilter(self, watched, event):
        spinbox = self._pressure_spinbox_focus_targets.get(watched)
        if spinbox is not None and event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.FocusOut):
            QTimer.singleShot(0, self._refresh_spinbox_edit_highlight)
        return super().eventFilter(watched, event)

    @staticmethod
    def _format_print_profile_tooltip(profile):
        try:
            print_pressure = float(profile["print_pressure"])
            refuel_pressure = float(profile["refuel_pressure"])
            print_pw = int(profile["print_pulse_width"])
            refuel_pw = int(profile["refuel_pulse_width"])
        except (KeyError, TypeError, ValueError):
            return "Invalid print profile"
        return (
            f"Print pressure: {print_pressure:.2f} psi\n"
            f"Refuel pressure: {refuel_pressure:.2f} psi\n"
            f"Print PW: {print_pw} us\n"
            f"Refuel PW: {refuel_pw} us"
        )

    def _init_print_profile_row(self, row):
        self.print_profile_label = QtWidgets.QLabel("Print Profile")
        self.print_profile_combo = QtWidgets.QComboBox()
        self.print_profile_combo.setFocusPolicy(QtCore.Qt.NoFocus)
        self.print_profile_apply_button = QtWidgets.QPushButton("Loaded")
        self.print_profile_apply_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.print_profile_apply_button.clicked.connect(self.handle_print_profile_apply)

        profiles = list(getattr(self.model, "print_profiles", []) or [])
        for profile in profiles:
            profile_data = dict(profile)
            self.print_profile_combo.addItem(str(profile_data.get("name", profile_data.get("id", "Profile"))), profile_data)
            index = self.print_profile_combo.count() - 1
            self.print_profile_combo.setItemData(
                index,
                self._format_print_profile_tooltip(profile_data),
                QtCore.Qt.ToolTipRole,
            )
        try:
            self.print_profile_combo.view().setMouseTracking(True)
        except Exception:
            pass
        self.print_profile_combo.currentIndexChanged.connect(self.handle_print_profile_selection_change)

        self.layout.addWidget(self.print_profile_label, row, 0)
        self.layout.addWidget(self.print_profile_combo, row, 1, 1, 2)
        self.layout.addWidget(self.print_profile_apply_button, row, 3)

        if not profiles:
            self.print_profile_combo.setEnabled(False)
            self._set_print_profile_button("No Profiles", enabled=False, color="#777777")
        else:
            self._refresh_print_profile_combo_tooltip()
            self.update_print_profile_button_state()

    def _get_selected_print_profile(self):
        combo = getattr(self, "print_profile_combo", None)
        if combo is None or combo.count() == 0:
            return None
        profile = combo.currentData()
        return dict(profile) if isinstance(profile, dict) else None

    def _refresh_print_profile_combo_tooltip(self):
        combo = getattr(self, "print_profile_combo", None)
        if combo is None:
            return
        tooltip = combo.itemData(combo.currentIndex(), QtCore.Qt.ToolTipRole)
        combo.setToolTip(str(tooltip or ""))

    def _current_print_profile_values(self):
        machine_model = self.model.machine_model
        print_pressure = (
            self.target_print_pressure_spinbox.value()
            if hasattr(self, "target_print_pressure_spinbox")
            else machine_model.get_target_print_pressure()
        )
        refuel_pressure = (
            self.target_refuel_pressure_spinbox.value()
            if hasattr(self, "target_refuel_pressure_spinbox")
            else machine_model.get_target_refuel_pressure()
        )
        print_pulse_width = (
            self.print_pulse_width_spinbox.value()
            if hasattr(self, "print_pulse_width_spinbox")
            else getattr(
                machine_model,
                "get_print_pulse_width",
                lambda: getattr(machine_model, "print_pulse_width", 0),
            )()
        )
        refuel_pulse_width = (
            self.refuel_pulse_width_spinbox.value()
            if hasattr(self, "refuel_pulse_width_spinbox")
            else getattr(
                machine_model,
                "get_refuel_pulse_width",
                lambda: getattr(machine_model, "refuel_pulse_width", 0),
            )()
        )
        return {
            "print_pressure": float(print_pressure),
            "refuel_pressure": float(refuel_pressure),
            "print_pulse_width": int(print_pulse_width),
            "refuel_pulse_width": int(refuel_pulse_width),
        }

    def _selected_print_profile_is_loaded(self, profile):
        if profile is None:
            return False
        try:
            current = self._current_print_profile_values()
            return (
                abs(current["print_pressure"] - float(profile["print_pressure"]))
                <= self.PRINT_PROFILE_PRESSURE_TOLERANCE
                and abs(current["refuel_pressure"] - float(profile["refuel_pressure"]))
                <= self.PRINT_PROFILE_PRESSURE_TOLERANCE
                and current["print_pulse_width"] == int(profile["print_pulse_width"])
                and current["refuel_pulse_width"] == int(profile["refuel_pulse_width"])
            )
        except (KeyError, TypeError, ValueError):
            return False

    def _set_print_profile_button(self, text, *, enabled, color):
        button = getattr(self, "print_profile_apply_button", None)
        if button is None:
            return
        button.setText(text)
        button.setEnabled(enabled)
        button.setProperty("profile_state", text.lower())
        button.setStyleSheet(f"background-color: {color}; color: white;")

    def update_print_profile_button_state(self):
        if self.legacy_mode or not hasattr(self, "print_profile_apply_button"):
            return
        profile = self._get_selected_print_profile()
        if profile is None:
            self._set_print_profile_button("No Profiles", enabled=False, color="#777777")
            return

        if self._selected_print_profile_is_loaded(profile):
            self._print_profile_apply_pending = False
            self._set_print_profile_button("Loaded", enabled=False, color="#777777")
        elif self._print_profile_apply_pending:
            self._set_print_profile_button("Applying...", enabled=False, color=self.color_dict["light_blue"])
        else:
            self._set_print_profile_button("Apply", enabled=True, color=self.color_dict["light_blue"])

    def handle_print_profile_selection_change(self, _index=None):
        self._print_profile_apply_pending = False
        self._refresh_print_profile_combo_tooltip()
        self.update_print_profile_button_state()

    def handle_print_profile_apply(self):
        profile = self._get_selected_print_profile()
        if profile is None:
            return
        self._print_profile_apply_pending = True
        self.update_print_profile_button_state()
        result = self.controller.apply_print_profile(
            profile,
            callback=self._handle_print_profile_apply_complete,
        )
        if result is False:
            self._print_profile_apply_pending = False
            self.update_print_profile_button_state()

    def _handle_print_profile_apply_complete(self, *args, **kwargs):
        QTimer.singleShot(0, self._finish_print_profile_apply)

    def _finish_print_profile_apply(self):
        self._print_profile_apply_pending = False
        self.update_print_profile_button_state()

    def _mark_print_profile_settings_changed(self):
        if self.legacy_mode or not hasattr(self, "print_profile_apply_button"):
            return
        self._print_profile_apply_pending = False
        self.update_print_profile_button_state()

    def init_ui(self):
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout = QtWidgets.QGridLayout(self)
        self.edit_focus_frame = QtWidgets.QFocusFrame(self)
        self.edit_focus_frame.setFocusPolicy(QtCore.Qt.NoFocus)
        self.edit_focus_frame.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.edit_focus_frame.setStyleSheet(
            "QFocusFrame {"
            f" border: 1px solid {self.color_dict.get('light_blue', '#3b82f6')};"
            " border-radius: 2px;"
            " background: transparent;"
            "}"
        )
        self.edit_focus_frame.hide()

        row_offset = 0
        if not self.legacy_mode:
            self._init_print_profile_row(0)
            row_offset = 1

        self.current_print_pressure_label = QtWidgets.QLabel("Print Pressure:")  # Create a new QLabel for the current pressure label
        self.current_print_pressure_value = QtWidgets.QLabel()  # Create a new QLabel for the current pressure value
        self.target_print_pressure_label = QtWidgets.QLabel("Target Print:")  # Create a new QLabel for the target pressure label
        self.target_print_pressure_spinbox = QtWidgets.QDoubleSpinBox()  # Create a new QDoubleSpinBox for the target pressure value
        self.target_print_pressure_spinbox.setDecimals(2)  # Set the number of decimal places to 3
        self.target_print_pressure_spinbox.setSingleStep(0.1)  # Set the step size to 0.001
        self.target_print_pressure_spinbox.setRange(0, 5)  # Set the range of the spinbox to 0-10
        self._configure_editable_spinbox(
            self.target_print_pressure_spinbox,
            self.handle_target_print_pressure_change,
        )

        self.layout.addWidget(self.current_print_pressure_label, row_offset + 0, 0)  # Add the QLabel to the layout at position (0, 0)
        self.layout.addWidget(self.current_print_pressure_value, row_offset + 0, 1)  # Add the QLabel to the layout at position (0, 1)
        self.layout.addWidget(self.target_print_pressure_label, row_offset + 0, 2)  # Add the QLabel to the layout at position (1, 0)
        self.layout.addWidget(self.target_print_pressure_spinbox, row_offset + 0, 3)  # Add the QDoubleSpinBox to the layout at position (1, 1)
        self.print_frequency_label = QtWidgets.QLabel("Print Frequency (Hz):")
        self.print_frequency_spinbox = QtWidgets.QSpinBox()
        self.print_frequency_spinbox.setRange(1, 100)
        self.print_frequency_spinbox.setSingleStep(1)
        self._configure_editable_spinbox(
            self.print_frequency_spinbox,
            self.handle_print_frequency_change,
        )

        if not self.legacy_mode:
            self.current_refuel_pressure_label = QtWidgets.QLabel("Refuel Pressure:")  # Create a new QLabel for the current pressure label
            self.current_refuel_pressure_value = QtWidgets.QLabel()  # Create a new QLabel for the current pressure value
            self.target_refuel_pressure_label = QtWidgets.QLabel("Target Refuel:")  # Create a new QLabel for the target pressure label
            self.target_refuel_pressure_spinbox = QtWidgets.QDoubleSpinBox()  # Create a new QDoubleSpinBox for the target pressure value
            self.target_refuel_pressure_spinbox.setDecimals(2)  # Set the number of decimal places to 3
            self.target_refuel_pressure_spinbox.setSingleStep(0.1)  # Set the step size to 0.001
            self.target_refuel_pressure_spinbox.setRange(0, 5)  # Set the range of the spinbox to 0-10
            self._configure_editable_spinbox(
                self.target_refuel_pressure_spinbox,
                self.handle_target_refuel_pressure_change,
            )

            self.layout.addWidget(self.current_refuel_pressure_label, row_offset + 1, 0)  # Add the QLabel to the layout at position (0, 0)
            self.layout.addWidget(self.current_refuel_pressure_value, row_offset + 1, 1)  # Add the QLabel to the layout at position (0, 1)
            self.layout.addWidget(self.target_refuel_pressure_label, row_offset + 1, 2)  # Add the QLabel to the layout at position (1, 0)
            self.layout.addWidget(self.target_refuel_pressure_spinbox, row_offset + 1, 3)  # Add the QDoubleSpinBox to the layout at position (1, 1)


        self.pressure_regulation_button = QtWidgets.QPushButton("Regulate Pressure")
        self.pressure_regulation_button.setFocusPolicy(QtCore.Qt.NoFocus)
        # self.pressure_regulation_button.setCheckable(True)
        self.pressure_regulation_button.clicked.connect(self.request_toggle_regulation)
        self.layout.addWidget(self.pressure_regulation_button, row_offset + 2, 0, 1, 4)  # Add the button to the layout at position (2, 0) and make it span 2 columns
        self.update_regulation_button(self.model.machine_model.regulating_print_pressure)

        self.chart = QtCharts.QChart()
        self.chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.chart.setBackgroundBrush(QtGui.QBrush(self.color_dict['darker_gray']))  # Set the background color to grey
        self.chart_view = QtCharts.QChartView(self.chart)
        
        self.print_series = QtCharts.QLineSeries()
        self.print_series.setColor(QtCore.Qt.white)
        self.chart.addSeries(self.print_series)

        if not self.legacy_mode:
            self.refuel_series = QtCharts.QLineSeries()
            self.refuel_series.setColor(QtCore.Qt.white)
            self.chart.addSeries(self.refuel_series)

        self.target_print_pressure_series = QtCharts.QLineSeries()  # Create a new line series for the target pressure
        self.target_print_pressure_series.setColor(QtCore.Qt.red)  # Set the line color to red
        self.chart.addSeries(self.target_print_pressure_series)

        if not self.legacy_mode:
                self.target_refuel_pressure_series = QtCharts.QLineSeries()  # Create a new line series for the target pressure
                self.target_refuel_pressure_series.setColor(QtCore.Qt.red)
                self.chart.addSeries(self.target_refuel_pressure_series)

        self.axisX = QtCharts.QValueAxis()
        self.axisX.setTickCount(3)
        self.axisX.setRange(0, len(self.model.machine_model.get_print_pressure_readings()))
        self.axisY = QtCharts.QValueAxis()
        self.axisY.setTitleText("Pressure (psi)")

        self.chart.addAxis(self.axisX, QtCore.Qt.AlignBottom)
        self.chart.addAxis(self.axisY, QtCore.Qt.AlignLeft)

        self.print_series.attachAxis(self.axisX)
        self.print_series.attachAxis(self.axisY)

        if not self.legacy_mode:
            self.refuel_series.attachAxis(self.axisX)
            self.refuel_series.attachAxis(self.axisY)

        self.target_print_pressure_series.attachAxis(self.axisX)
        self.target_print_pressure_series.attachAxis(self.axisY)

        if not self.legacy_mode:
            self.target_refuel_pressure_series.attachAxis(self.axisX)
            self.target_refuel_pressure_series.attachAxis(self.axisY)

        self.chart.legend().hide()  # Hide the legend
        self.chart_view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.chart_view.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout.addWidget(self.chart_view, row_offset + 3, 0,1,4)

        self.calibrate_pressure_button = QtWidgets.QPushButton("Calibrate Printer head")
        self.calibrate_pressure_button.clicked.connect(self.calibrate_pressure)
        self.layout.addWidget(self.calibrate_pressure_button, row_offset + 4, 0, 1, 2)

        if not self.legacy_mode:
            self.refuel_camera_button = QtWidgets.QPushButton("Refuel Camera")
            self.refuel_camera_button.clicked.connect(self.refuel_camera)
            self.layout.addWidget(self.refuel_camera_button, row_offset + 5, 0, 1, 2)

        self.print_pulse_width_label = QtWidgets.QLabel("Print Pulse Width:")
        self.print_pulse_width_spinbox = QtWidgets.QSpinBox()
        self.print_pulse_width_spinbox.setRange(0, 10000)
        self.print_pulse_width_spinbox.setSingleStep(50)
        self.print_pulse_width_spinbox.setValue(3000)
        self._configure_editable_spinbox(
            self.print_pulse_width_spinbox,
            self.handle_print_pulse_width_change,
        )
        self.layout.addWidget(self.print_pulse_width_label,row_offset + 4,2,1,1)
        self.layout.addWidget(self.print_pulse_width_spinbox,row_offset + 4,3,1,1)


        if not self.legacy_mode:
            self.refuel_pulse_width_label = QtWidgets.QLabel("Refuel Pulse Width:")
            self.refuel_pulse_width_spinbox = QtWidgets.QSpinBox()
            self.refuel_pulse_width_spinbox.setRange(0, 10000)
            self.refuel_pulse_width_spinbox.setSingleStep(50)
            self.refuel_pulse_width_spinbox.setValue(3000)
            self._configure_editable_spinbox(
                self.refuel_pulse_width_spinbox,
                self.handle_refuel_pulse_width_change,
            )
            self.layout.addWidget(self.refuel_pulse_width_label,row_offset + 5,2,1,1)
            self.layout.addWidget(self.refuel_pulse_width_spinbox,row_offset + 5,3,1,1)

        frequency_row = row_offset + (5 if self.legacy_mode else 6)
        self.layout.addWidget(self.print_frequency_label, frequency_row, 2, 1, 1)
        self.layout.addWidget(self.print_frequency_spinbox, frequency_row, 3, 1, 1)


        self.model.machine_model.pressure_updated.connect(self.update_pressure)

    def handle_target_print_pressure_change(self):
        """Handle changes to the target pressure value."""
        value = self.target_print_pressure_spinbox.value()
        self.controller.set_absolute_print_pressure(value,manual=True)
        self._finish_spinbox_edit(self.target_print_pressure_spinbox)
        self._mark_print_profile_settings_changed()

    def handle_target_refuel_pressure_change(self):
        """Handle changes to the target pressure value."""
        value = self.target_refuel_pressure_spinbox.value()
        self.controller.set_absolute_refuel_pressure(value,manual=True)
        self._finish_spinbox_edit(self.target_refuel_pressure_spinbox)
        self._mark_print_profile_settings_changed()

    def handle_print_pulse_width_change(self):
        """Handle changes to the pulse width value."""
        value = self.print_pulse_width_spinbox.value()
        self.controller.set_print_pulse_width(value,manual=True)
        self._finish_spinbox_edit(self.print_pulse_width_spinbox)
        self._mark_print_profile_settings_changed()

    def handle_print_frequency_change(self):
        """Handle changes to the print pacing value."""
        value = self.print_frequency_spinbox.value()
        self.controller.set_dispense_frequency_hz(value, manual=True)
        self._finish_spinbox_edit(self.print_frequency_spinbox)
    
    def handle_refuel_pulse_width_change(self):
        """Handle changes to the pulse width value."""
        value = self.refuel_pulse_width_spinbox.value()
        self.controller.set_refuel_pulse_width(value,manual=True)
        self._finish_spinbox_edit(self.refuel_pulse_width_spinbox)
        self._mark_print_profile_settings_changed()

    def update_printing_controls(self):
        """Refresh editable print settings from the machine model."""
        machine_model = self.model.machine_model

        if not self._spinbox_is_being_edited(self.target_print_pressure_spinbox):
            self.target_print_pressure_spinbox.blockSignals(True)
            self.target_print_pressure_spinbox.setValue(machine_model.get_target_print_pressure())
            self.target_print_pressure_spinbox.blockSignals(False)

        if not self._spinbox_is_being_edited(self.print_pulse_width_spinbox):
            self.print_pulse_width_spinbox.blockSignals(True)
            self.print_pulse_width_spinbox.setValue(machine_model.print_pulse_width)
            self.print_pulse_width_spinbox.blockSignals(False)

        if not self._spinbox_is_being_edited(self.print_frequency_spinbox):
            self.print_frequency_spinbox.blockSignals(True)
            self.print_frequency_spinbox.setValue(machine_model.get_dispense_frequency_hz())
            self.print_frequency_spinbox.blockSignals(False)

        if not self.legacy_mode:
            if not self._spinbox_is_being_edited(self.target_refuel_pressure_spinbox):
                self.target_refuel_pressure_spinbox.blockSignals(True)
                self.target_refuel_pressure_spinbox.setValue(machine_model.get_target_refuel_pressure())
                self.target_refuel_pressure_spinbox.blockSignals(False)

            if not self._spinbox_is_being_edited(self.refuel_pulse_width_spinbox):
                self.refuel_pulse_width_spinbox.blockSignals(True)
                self.refuel_pulse_width_spinbox.setValue(machine_model.refuel_pulse_width)
                self.refuel_pulse_width_spinbox.blockSignals(False)

        self.update_print_profile_button_state()

    def update_pressure(self):
        """Update the current pressure label and plot with the new pressure values."""
        # Clear previous data
        self.print_series.clear()
        if not self.legacy_mode:
            self.refuel_series.clear()
        self.target_print_pressure_series.clear()

        print_log = self.model.machine_model.get_print_pressure_readings()
        if not self.legacy_mode:
            refuel_log = self.model.machine_model.get_refuel_pressure_readings()
        
        comp_log = list(print_log).copy()
        if not self.legacy_mode:
            comp_log.extend(refuel_log)

        # Append new pressure data
        for i, pressure in enumerate(print_log):
            self.print_series.append(i, pressure)

        if not self.legacy_mode:
            for i, pressure in enumerate(refuel_log):
                self.refuel_series.append(i, pressure)

        # Get the target pressure and append target line points
        target_print_pressure = self.model.machine_model.get_target_print_pressure()
        self.target_print_pressure_series.append(0, target_print_pressure)  # Add lower point of target pressure line
        self.target_print_pressure_series.append(len(print_log) - 1, target_print_pressure)  # Add upper point of target pressure line

        # Calculate min and max pressure for y-axis range
        min_pressure = min([*comp_log,target_print_pressure]) - 0.5
        max_pressure = max([*comp_log,target_print_pressure]) + 0.5

        # Update y-axis range with calculated min and max
        self.axisY.setRange(min_pressure, max_pressure)

        # Update the pressure display labels
        self.current_print_pressure_value.setText(f"{print_log[-1]:.3f}")
        if not self.legacy_mode:
            self.current_refuel_pressure_value.setText(f"{refuel_log[-1]:.3f}")

    def request_toggle_regulation(self):
        """Emit a signal to request toggling the motors."""
        if self.model.machine_model.motors_are_enabled():
            self.toggle_regulation_requested.emit()
        else:
            self.popup_message_signal.emit("Motors Not Enabled","Please enable and home the motors before regulating pressure")

    def update_regulation_button_state(self,machine_connected):
        self.pressure_regulation_button.setEnabled(machine_connected)

    def update_regulation_button(self, regulating_pressure):
        """Update the motor button text and color based on the motor state."""
        if regulating_pressure:
            self.pressure_regulation_button.setText("Deregulate Pressure")
            self.pressure_regulation_button.setStyleSheet(f"background-color: {self.color_dict['dark_blue']}; color: white;")
        else:
            self.pressure_regulation_button.setText("Regulate Pressure")
            self.pressure_regulation_button.setStyleSheet(f"background-color: {self.color_dict['light_blue']}; color: white;")

    def calibrate_pressure(self):
        """Calibrate the pressure for a specific printer head."""
        # if not self.controller.check_if_all_completed():
        #     self.popup_message_signal.emit("Cannot calibrate pressure","Please wait for the current actions to complete")
        #     return

        # if self.model.rack_model.get_gripper_printer_head() == None:
        #     self.popup_message_signal.emit("No Printer Head","Please load a printer head before calibrating pressure")
        #     return
        # if self.model.machine_model.get_current_location() != 'balance':
        #     response = self.main_window.popup_yes_no("Must be positioned at the balance","Would you like to move to the balance?")
        #     if response == '&No':
        #         self.popup_message_signal.emit("Must be positioned at the balance","Please move to the balance before calibrating pressure")
        #         return
        #     elif response == '&Yes':
        #         self.controller.move_to_location('balance', manual=True, safe_y=True)
        # mass_calibration_dialog = MassCalibrationDialog(self.main_window,self.model,self.controller)
        # mass_calibration_dialog.exec()
        if not self.legacy_mode:
            self.droplet_imager()
        else:
            mass_calibration_dialog_cls = _get_mass_calibration_dialog_class()
            mass_calibration_dialog = mass_calibration_dialog_cls(self.main_window,self.model,self.controller)
            mass_calibration_dialog.exec()
        # droplet_imaging_dialog = DropletImagingDialog(self.main_window,self.model,self.controller)
        # droplet_imaging_dialog.exec()

    def _launch_droplet_imager_dialog(self):
        """Open the droplet imager dialog after preflight checks have passed."""
        self.controller.disconnect_droplet_camera_signals()
        importlib.reload(CalibrationClasses.View)
        importlib.reload(CalibrationClasses)
        self.model.reload_droplet_model()
        self.controller.connect_droplet_camera_signals()
        self.controller.enable_print_profile()
        droplet_imaging_dialog = CalibrationClasses.DropletImagingDialog(
            self.main_window,
            self.model,
            self.controller,
            open_refuel_camera_callback=self.refuel_camera,
        )
        droplet_imaging_dialog.exec()

    def _launch_manual_optics_calibration_dialog(self):
        """Open the droplet imager directly to the manual optics-calibration tab."""
        try:
            self.controller.disconnect_droplet_camera_signals()
        except Exception:
            pass
        importlib.reload(CalibrationClasses.View)
        importlib.reload(CalibrationClasses)
        try:
            self.model.reload_droplet_model()
        except Exception:
            pass
        try:
            self.controller.connect_droplet_camera_signals()
        except Exception:
            pass
        droplet_imaging_dialog = CalibrationClasses.DropletImagingDialog(
            self.main_window,
            self.model,
            self.controller,
            service_mode=True,
            initial_tab="optics",
            open_refuel_camera_callback=self.refuel_camera,
        )
        droplet_imaging_dialog.exec()

    def _guided_optics_location_pair(self):
        try:
            return OpticsCalibrationApproachWizardDialog.validate_locations(self.model)
        except ValueError as exc:
            self.popup_message_signal.emit("Invalid Optics Locations", str(exc))
            return None

    def _machine_is_connected_for_guided_optics(self):
        getter = getattr(self.model.machine_model, "is_connected", None)
        try:
            return bool(getter()) if callable(getter) else bool(getattr(self.model.machine_model, "machine_connected", False))
        except Exception:
            return False

    def _motors_enabled_for_guided_optics(self):
        getter = getattr(self.model.machine_model, "motors_are_enabled", None)
        try:
            return bool(getter()) if callable(getter) else bool(getattr(self.model.machine_model, "motors_enabled", False))
        except Exception:
            return False

    def start_guided_optics_calibration(self):
        """Start the guided micrometer load/approach wizard for optics calibration."""
        if not self.controller.check_if_all_completed():
            self.popup_message_signal.emit(
                "Commands Still Running",
                "Please wait for the current commands to finish before starting guided optics calibration.",
            )
            return

        if not self._machine_is_connected_for_guided_optics():
            self.popup_message_signal.emit(
                "Machine Not Connected",
                "Please connect to the machine before starting guided optics calibration.",
            )
            return

        if not self._motors_enabled_for_guided_optics():
            self.popup_message_signal.emit(
                "Motors Not Enabled",
                "Please enable the motors before starting guided optics calibration.",
            )
            return

        if self._guided_optics_location_pair() is None:
            return

        self._launch_guided_optics_calibration_dialog()

    def _launch_guided_optics_calibration_dialog(self):
        wizard = OpticsCalibrationApproachWizardDialog(self.main_window, self.model, self.controller)
        result = wizard.exec()
        accepted = int(result) == int(QtWidgets.QDialog.Accepted)
        try:
            prompt_cleanup = bool(wizard.should_prompt_cleanup())
        except Exception:
            prompt_cleanup = False
        if accepted:
            self._launch_manual_optics_calibration_dialog()
            self._prompt_guided_optics_cleanup()
        elif prompt_cleanup:
            self._prompt_guided_optics_cleanup()

    def _prompt_guided_optics_cleanup(self):
        if self._guided_optics_location_pair() is None:
            return
        response = self.main_window.popup_yes_no(
            "Clean Up Optics Calibration Setup",
            "Would you like to raise to home Z, move to home X/Y, open the gripper, and remove the micrometer now?",
        )
        if not self.main_window._is_yes_response(response):
            self.popup_message_signal.emit(
                "Optics Cleanup Reminder",
                "Leave the machine safe and remove the micrometer and adapter before returning to normal operation.",
            )
            return

        if not self.controller.check_if_all_completed():
            self.popup_message_signal.emit(
                "Cleanup Deferred",
                "Commands are still running. Please clean up manually once the command queue is clear.",
            )
            return

        home, _camera = self._guided_optics_location_pair()
        if home is None:
            return

        def _after_open():
            self.popup_message_signal.emit(
                "Remove Micrometer",
                "The gripper is open. Remove the micrometer adapter before normal operation.",
            )

        def _after_xy():
            opener = getattr(self.controller, "open_gripper", None)
            if not callable(opener) or opener(handler=_after_open) is False:
                self.popup_message_signal.emit(
                    "Cleanup Incomplete",
                    "Failed to queue gripper open. Remove the micrometer manually when safe.",
                )

        def _after_z():
            mover = getattr(self.controller, "set_absolute_XY", None)
            if (
                not callable(mover)
                or mover(int(home["X"]), int(home["Y"]), manual=True, handler=_after_xy) is False
            ):
                self.popup_message_signal.emit(
                    "Cleanup Incomplete",
                    "Failed to queue the home X/Y move. Remove the micrometer manually when safe.",
                )

        mover_z = getattr(self.controller, "set_absolute_Z", None)
        if not callable(mover_z) or mover_z(int(home["Z"]), manual=True, handler=_after_z) is False:
            self.popup_message_signal.emit(
                "Cleanup Incomplete",
                "Failed to queue the home Z move. Remove the micrometer manually when safe.",
            )

    def _launch_refuel_camera_dialog(self):
        """Open the refuel camera dialog after preflight checks have passed."""
        importlib.reload(CalibrationClasses.View)
        importlib.reload(CalibrationClasses)
        self.controller.enable_print_profile()
        refuel_camera_dialog = CalibrationClasses.RefuelCameraWindow(
            self.main_window,
            self.model,
            self.controller,
        )
        refuel_camera_dialog.exec()

    def droplet_imager(self):
        """Open the droplet imager dialog after verifying prerequisites."""
        if not self.controller.check_if_all_completed():
            self.popup_message_signal.emit(
                "Commands Still Running",
                "Please wait for the current commands to finish before starting the droplet imager.",
            )
            return

        if self.model.rack_model.get_gripper_printer_head() is None:
            self.popup_message_signal.emit(
                "No Printer Head",
                "Please load a printer head into the gripper before starting calibration.",
            )
            return

        if not self.model.machine_model.regulating_print_pressure:
            self.popup_message_signal.emit(
                "Pressure Not Regulated",
                "Please regulate pressure before starting calibration.",
            )
            return

        current_location = str(self.model.machine_model.get_current_location() or "").strip().lower()
        if current_location == "camera":
            self._launch_droplet_imager_dialog()
            return

        response = self.main_window.popup_yes_no(
            "Move To Camera",
            "Droplet calibration must start at the camera position. Would you like to move to the camera position now?",
        )
        if not self.main_window._is_yes_response(response):
            self.popup_message_signal.emit(
                "Must Be At Camera",
                "Please move the machine to the camera position before starting calibration.",
            )
            return

        self.controller.move_to_location(
            "camera",
            manual=True,
            on_complete=self._launch_droplet_imager_dialog,
        )

    def open_manual_optics_calibration(self):
        """Start the manual optics calibration slice without motion or pressure preflight."""
        if not self.controller.check_if_all_completed():
            self.popup_message_signal.emit(
                "Commands Still Running",
                "Please wait for the current commands to finish before starting optics calibration.",
            )
            return

        response = self.main_window.popup_yes_no(
            "Begin Optics Calibration",
            "This opens the droplet imager for manual micrometer positioning and capture. No automatic homing, gripper, or camera-approach motion will run. Continue?",
        )
        if not self.main_window._is_yes_response(response):
            return

        self._launch_manual_optics_calibration_dialog()

    def refuel_camera(self):
        """Open the refuel camera dialog after verifying prerequisites."""
        if not self.controller.check_if_all_completed():
            self.popup_message_signal.emit(
                "Commands Still Running",
                "Please wait for the current commands to finish before starting the refuel camera.",
            )
            return

        if self.model.rack_model.get_gripper_printer_head() is None:
            self.popup_message_signal.emit(
                "No Printer Head",
                "Please load a printer head into the gripper before starting refuel imaging.",
            )
            return

        if (
            not self.model.machine_model.regulating_print_pressure
            or not self.model.machine_model.regulating_refuel_pressure
        ):
            self.popup_message_signal.emit(
                "Pressure Not Regulated",
                "Please regulate both print and refuel pressure before starting the refuel camera.",
            )
            return

        current_location = str(self.model.machine_model.get_current_location() or "").strip().lower()
        if current_location == "camera":
            self._launch_refuel_camera_dialog()
            return

        response = self.main_window.popup_yes_no(
            "Move To Camera",
            "Refuel imaging must start at the camera position. Would you like to move to the camera position now?",
        )
        if not self.main_window._is_yes_response(response):
            self.popup_message_signal.emit(
                "Must Be At Camera",
                "Please move the machine to the camera position before starting refuel imaging.",
            )
            return

        self.controller.move_to_location(
            "camera",
            manual=True,
            on_complete=self._launch_refuel_camera_dialog,
        )

    def nozzle_position_dataset_capture(self):
        """Open the NozzlePosition checklist-driven dataset capture dialog."""
        self.controller.disconnect_droplet_camera_signals()
        importlib.reload(CalibrationClasses.View)
        importlib.reload(CalibrationClasses)
        self.model.reload_droplet_model()
        self.controller.connect_droplet_camera_signals()
        self.controller.enable_print_profile()
        dlg = CalibrationClasses.NozzlePositionDatasetCaptureWindow(self.main_window, self.model, self.controller)
        dlg.exec()

    def print_calibration_droplets(self,num_droplets):
        print('Printing calibration droplets:',num_droplets,self.target_pressure)
        self.controller.print_calibration_droplets(num_droplets,self.target_pressure)

    def calibration_pressure_change(self,pressure):
        print('Pressure changed to:',pressure)
        self.target_pressure = pressure
        self.controller.set_absolute_print_pressure(pressure)

class StockPrepDialog(QDialog):
    COL_REAGENT = 0
    COL_TARGET_CONC = 1
    COL_UNITS = 2
    COL_REQUIRED_VOL = 3
    COL_PREP_VOL = 4
    COL_SOURCE_CONC = 5
    COL_STOCK_TO_ADD = 6
    COL_DILUENT_TO_ADD = 7
    COL_STATUS = 8

    DEFAULT_DEAD_VOLUME_UL = 20.0
    DEFAULT_CALIBRATION_EXTRA_UL = 10.0
    INFO_TEXT = (
        "One row per experiment stock. Fill reagent is excluded. Two-stock plans appear "
        "as separate rows. Calculations assume a compatible diluent, typically water."
    )
    EMPTY_TEXT = (
        "No calculated stock plan is available. Generate an experiment in Experiment Editor first."
    )

    def __init__(self, experiment_model: ExperimentModel, main_window):
        parent = main_window if isinstance(main_window, QWidget) else None
        super().__init__(parent)
        self.experiment_model = experiment_model
        self.main_window = main_window
        self._stock_rows = self._load_stock_rows()
        self._close_persist_complete = False

        self.setWindowTitle("Stock Prep Calculator")
        self.setModal(True)
        self.resize(1100, 520)

        icon_factory = getattr(self.main_window, "make_transparent_icon", None)
        if callable(icon_factory):
            try:
                icon = icon_factory()
            except Exception:
                icon = None
            if icon is not None:
                self.setWindowIcon(icon)

        self._build_ui()
        self._hydrate_defaults_from_model()
        self._populate_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        info_label = QLabel(self.INFO_TEXT, self)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Dead Volume Extra (uL)", self))
        self.dead_volume_spin = QDoubleSpinBox(self)
        self.dead_volume_spin.setDecimals(2)
        self.dead_volume_spin.setRange(0.0, 1_000_000.0)
        self.dead_volume_spin.setValue(self.DEFAULT_DEAD_VOLUME_UL)
        controls_layout.addWidget(self.dead_volume_spin)

        controls_layout.addWidget(QLabel("Calibration Extra (uL)", self))
        self.calibration_extra_spin = QDoubleSpinBox(self)
        self.calibration_extra_spin.setDecimals(2)
        self.calibration_extra_spin.setRange(0.0, 1_000_000.0)
        self.calibration_extra_spin.setValue(self.DEFAULT_CALIBRATION_EXTRA_UL)
        controls_layout.addWidget(self.calibration_extra_spin)

        self.apply_suggested_button = QPushButton("Apply Suggested Volumes", self)
        self.apply_suggested_button.clicked.connect(self._apply_suggested_prep_volumes)
        controls_layout.addWidget(self.apply_suggested_button)
        controls_layout.addStretch(1)
        layout.addLayout(controls_layout)

        self.table = QTableWidget(0, 9, self)
        self.table.setHorizontalHeaderLabels([
            "Reagent",
            "Target Conc",
            "Units",
            "Required Vol (uL)",
            "Prep Vol (uL)",
            "Source Conc",
            "Stock To Add (uL)",
            "Diluent To Add (uL)",
            "Status",
        ])
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.empty_state_label = QLabel("", self)
        self.empty_state_label.setWordWrap(True)
        self.empty_state_label.setStyleSheet("color:#666; font-style: italic;")
        self.empty_state_label.hide()
        layout.addWidget(self.empty_state_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.accept)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

    def _load_stock_rows(self) -> List[Dict[str, Any]]:
        getter = getattr(self.experiment_model, "get_stock_table_rows", None)
        if not callable(getter):
            return []

        rows: List[Dict[str, Any]] = []
        for row in getter(include_fill=False):
            units = str(row.get("units", "") or "")
            if units == "--":
                continue

            total_volume = row.get("total_volume_uL", None)
            try:
                total_volume_uL = float(total_volume)
            except Exception:
                continue
            if not math.isfinite(total_volume_uL) or total_volume_uL <= 0:
                continue

            normalized = dict(row)
            normalized["total_volume_uL"] = total_volume_uL
            rows.append(normalized)
        return rows

    def _populate_table(self):
        self.table.setRowCount(0)
        if not self._stock_rows:
            self.empty_state_label.setText(self.EMPTY_TEXT)
            self.empty_state_label.show()
            return

        self.empty_state_label.clear()
        self.empty_state_label.hide()

        for row_index, row in enumerate(self._stock_rows):
            self.table.insertRow(row_index)
            label = str(row.get("option_name") or row.get("factor_name") or "")
            self._set_readonly_item(row_index, self.COL_REAGENT, label)
            self._set_readonly_item(
                row_index,
                self.COL_TARGET_CONC,
                self._fmt_num(row.get("stock_concentration", "")),
            )
            self._set_readonly_item(row_index, self.COL_UNITS, str(row.get("units", "")))
            self._set_readonly_item(
                row_index,
                self.COL_REQUIRED_VOL,
                self._fmt_num(row.get("total_volume_uL", "")),
            )
            persisted_entry = self._get_saved_row_state(row)

            prep_spin = QDoubleSpinBox(self.table)
            prep_spin.setDecimals(2)
            prep_spin.setRange(0.0, 1_000_000.0)
            prep_spin.setValue(self._resolve_prep_volume(row, persisted_entry))
            prep_spin.valueChanged.connect(lambda _value, rr=row_index: self._recompute_row(rr))
            self.table.setCellWidget(row_index, self.COL_PREP_VOL, prep_spin)

            source_spin = QDoubleSpinBox(self.table)
            source_spin.setDecimals(2)
            source_spin.setRange(0.0, 1_000_000.0)
            source_spin.setSpecialValueText("--")
            source_spin.setValue(self._resolve_source_concentration(persisted_entry))
            source_spin.valueChanged.connect(lambda _value, rr=row_index: self._recompute_row(rr))
            self.table.setCellWidget(row_index, self.COL_SOURCE_CONC, source_spin)

            self._set_readonly_item(row_index, self.COL_STOCK_TO_ADD, "")
            self._set_readonly_item(row_index, self.COL_DILUENT_TO_ADD, "")
            self._set_readonly_item(row_index, self.COL_STATUS, "", alignment=Qt.AlignLeft | Qt.AlignVCenter)

        self._recompute_all_rows()

    def _set_readonly_item(self, row: int, col: int, text: str, alignment=Qt.AlignCenter):
        item = QTableWidgetItem(str(text))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setTextAlignment(alignment)
        self.table.setItem(row, col, item)

    def _hydrate_defaults_from_model(self):
        getter = getattr(self.experiment_model, "get_stock_prep_defaults", None)
        if not callable(getter):
            return
        try:
            defaults = getter() or {}
        except Exception:
            return
        dead_volume = self._coerce_nonnegative_float(
            defaults.get("dead_volume_extra_uL", self.DEFAULT_DEAD_VOLUME_UL),
            self.DEFAULT_DEAD_VOLUME_UL,
        )
        calibration_extra = self._coerce_nonnegative_float(
            defaults.get("calibration_extra_uL", self.DEFAULT_CALIBRATION_EXTRA_UL),
            self.DEFAULT_CALIBRATION_EXTRA_UL,
        )
        self.dead_volume_spin.setValue(dead_volume)
        self.calibration_extra_spin.setValue(calibration_extra)

    def _get_saved_row_state(self, row: Mapping[str, Any]) -> Dict[str, Any] | None:
        getter = getattr(self.experiment_model, "get_stock_prep_entry", None)
        if not callable(getter):
            return None
        try:
            entry = getter(row)
        except Exception:
            return None
        return entry if isinstance(entry, dict) else None

    def _resolve_prep_volume(self, row: Mapping[str, Any], persisted_entry: Dict[str, Any] | None) -> float:
        suggested = self._suggested_prep_volume(row)
        if not persisted_entry:
            return suggested
        return self._coerce_nonnegative_float(persisted_entry.get("prep_volume_uL"), suggested)

    def _resolve_source_concentration(self, persisted_entry: Dict[str, Any] | None) -> float:
        if not persisted_entry:
            return 0.0
        return self._coerce_nonnegative_float(persisted_entry.get("source_concentration"), 0.0)

    @staticmethod
    def _coerce_nonnegative_float(value, fallback: float) -> float:
        try:
            coerced = float(value)
        except Exception:
            return float(fallback)
        if not math.isfinite(coerced) or coerced < 0.0:
            return float(fallback)
        return coerced

    def _suggested_prep_volume(self, row: Mapping[str, Any]) -> float:
        required = float(row.get("total_volume_uL", 0.0) or 0.0)
        return required + float(self.dead_volume_spin.value()) + float(self.calibration_extra_spin.value())

    def _apply_suggested_prep_volumes(self):
        for row_index, row in enumerate(self._stock_rows):
            prep_spin = self.table.cellWidget(row_index, self.COL_PREP_VOL)
            if isinstance(prep_spin, QDoubleSpinBox):
                prep_spin.setValue(self._suggested_prep_volume(row))
        self._recompute_all_rows()

    def _recompute_all_rows(self):
        for row_index in range(self.table.rowCount()):
            self._recompute_row(row_index)

    def _recompute_row(self, row_index: int):
        if row_index < 0 or row_index >= len(self._stock_rows):
            return

        row = self._stock_rows[row_index]
        target_conc = float(row.get("stock_concentration", 0.0) or 0.0)
        prep_spin = self.table.cellWidget(row_index, self.COL_PREP_VOL)
        source_spin = self.table.cellWidget(row_index, self.COL_SOURCE_CONC)
        if not isinstance(prep_spin, QDoubleSpinBox) or not isinstance(source_spin, QDoubleSpinBox):
            return

        prep_volume_uL = float(prep_spin.value())
        source_conc = float(source_spin.value())

        stock_item = self.table.item(row_index, self.COL_STOCK_TO_ADD)
        diluent_item = self.table.item(row_index, self.COL_DILUENT_TO_ADD)
        status_item = self.table.item(row_index, self.COL_STATUS)
        if stock_item is None or diluent_item is None or status_item is None:
            return

        def _set_blank(message: str):
            stock_item.setText("")
            diluent_item.setText("")
            status_item.setText(message)

        if source_conc <= 0:
            _set_blank("Enter source concentration")
            return
        if prep_volume_uL <= 0:
            _set_blank("Enter prep volume")
            return
        if source_conc + 1e-12 < target_conc:
            _set_blank("Source concentration must be >= target concentration")
            return

        if abs(source_conc - target_conc) <= 1e-12:
            stock_uL = prep_volume_uL
            diluent_uL = 0.0
        else:
            stock_uL, diluent_uL = self._calculate_dilution(target_conc, source_conc, prep_volume_uL)

        stock_item.setText(self._fmt_num(stock_uL))
        diluent_item.setText(self._fmt_num(diluent_uL))
        status_item.setText("Ready")

    def _calculate_dilution(
        self,
        target_conc: float,
        source_conc: float,
        prep_volume_uL: float,
    ) -> Tuple[float, float]:
        stock_uL = (float(target_conc) / float(source_conc)) * float(prep_volume_uL)
        diluent_uL = float(prep_volume_uL) - stock_uL
        if -1e-9 < diluent_uL < 0:
            diluent_uL = 0.0
        return stock_uL, diluent_uL

    def _collect_stock_prep_snapshot(self) -> List[Dict[str, Any]]:
        snapshot_rows: List[Dict[str, Any]] = []
        for row_index, row in enumerate(self._stock_rows):
            prep_spin = self.table.cellWidget(row_index, self.COL_PREP_VOL)
            source_spin = self.table.cellWidget(row_index, self.COL_SOURCE_CONC)
            if not isinstance(prep_spin, QDoubleSpinBox) or not isinstance(source_spin, QDoubleSpinBox):
                continue
            snapshot_rows.append({
                "factor_name": str(row.get("factor_name", "") or ""),
                "option_name": str(row.get("option_name", "") or ""),
                "stock_concentration": float(row.get("stock_concentration", 0.0) or 0.0),
                "units": str(row.get("units", "") or ""),
                "prep_volume_uL": float(prep_spin.value()),
                "source_concentration": float(source_spin.value()),
            })
        return snapshot_rows

    def _persist_stock_prep_state(self) -> bool:
        rows = self._collect_stock_prep_snapshot()
        setter = getattr(self.experiment_model, "set_stock_prep_snapshot", None)
        if callable(setter):
            setter(
                rows,
                dead_volume_extra_uL=float(self.dead_volume_spin.value()),
                calibration_extra_uL=float(self.calibration_extra_spin.value()),
            )

        experiment_path = getattr(self.experiment_model, "experiment_file_path", None)
        saver = getattr(self.experiment_model, "save_experiment", None)
        if not experiment_path or not callable(saver):
            return True

        try:
            saver()
        except Exception as exc:
            popup = getattr(self.main_window, "popup_message", None)
            if callable(popup):
                popup("Save Stock Prep Failed", f"Could not save stock prep values: {exc}")
            return False
        return True

    def _persist_before_close(self) -> bool:
        if self._close_persist_complete:
            return True
        if not self._persist_stock_prep_state():
            return False
        self._close_persist_complete = True
        return True

    def accept(self):
        if not self._persist_before_close():
            return
        super().accept()

    def reject(self):
        if not self._persist_before_close():
            return
        super().reject()

    def closeEvent(self, event):
        if self._close_persist_complete:
            super().closeEvent(event)
            return
        if not self._persist_before_close():
            event.ignore()
            return
        super().closeEvent(event)

    @staticmethod
    def _fmt_num(x) -> str:
        try:
            xv = float(x)
            if abs(xv - round(xv)) < 1e-9:
                return str(int(round(xv)))
            return f"{xv:.2f}".rstrip("0").rstrip(".")
        except Exception:
            return str(x)

class WellPlateWidget(QtWidgets.QGroupBox):
    def __init__(self, main_window, model, controller):
        super().__init__('PLATE')
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.controller = controller
        self.grid_layout = QGridLayout()
        self.well_labels = []
        # Set the max height of the widget
        self.setMaximumHeight(800)

        self.model.experiment_loaded.connect(self.on_experiment_loaded)
        self.model.rack_model.gripper_updated.connect(self.gripper_update_handler)
        self.model.well_plate.well_state_changed_signal.connect(self.update_well_colors)
        self.model.well_plate.clear_all_wells_signal.connect(self.update_well_colors)
        self.model.well_plate.plate_format_changed_signal.connect(self.update_grid)
        self.model.well_plate.plate_summary_changed_signal.connect(self._update_plate_summary)
        self.model.rack_model.gripper_updated.connect(self.update_start_print_array_button)
        self.controller.array_state_changed.connect(self.update_start_print_array_button)
        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout()
        self.top_layout = QHBoxLayout()
        self.plate_selection_label = QLabel("Plate Format:")
        self.plate_selection_label.setStyleSheet("color: white;")
        self.plate_selection_label.setAlignment(Qt.AlignRight)
        self.top_layout.addWidget(self.plate_selection_label)
        self.plate_format_value_label = QLabel("")
        self.plate_format_value_label.setStyleSheet("color: white;")
        self.top_layout.addWidget(self.plate_format_value_label)
        self._update_plate_summary(
            self.model.well_plate.get_current_plate_name(),
            self.model.well_plate.get_num_rows(),
            self.model.well_plate.get_num_cols(),
        )
        
        # Create a calibration button
        self.calibration_button = QPushButton("Calibrate Plate", self)
        self.calibration_button.clicked.connect(self.open_calibration_dialog)
        self.top_layout.addWidget(self.calibration_button)
        
        self.bottom_layout = QHBoxLayout()

        self.design_experiment_button = QPushButton("Experiment Editor")
        self.design_experiment_button.clicked.connect(self.open_experiment_designer)
        self.bottom_layout.addWidget(self.design_experiment_button)

        self.stock_prep_button = QPushButton("Prep Stocks")
        self.stock_prep_button.clicked.connect(self.open_stock_prep_dialog)
        self.bottom_layout.addWidget(self.stock_prep_button)

        self.start_print_array_button = QPushButton("Start Print")
        self.start_print_array_button.setStyleSheet(f"background-color: {self.color_dict['darker_gray']}; color: white;")
        self.start_print_array_button.setEnabled(False)
        self.start_print_array_button.clicked.connect(self.start_print_array)
        self.bottom_layout.addWidget(self.start_print_array_button)

        self.pause_machine_button = QPushButton("Pause")
        self.pause_machine_button.setStyleSheet(f"background-color: {self.color_dict['dark_red']}; color: white;")
        self.pause_machine_button.clicked.connect(self.main_window.pause_machine)
        self.bottom_layout.addWidget(self.pause_machine_button)

        self.reagent_selection = QComboBox()
        self._populate_reagent_selection()
        self.reagent_selection.currentIndexChanged.connect(self.update_well_colors)
        self.bottom_layout.addWidget(self.reagent_selection)

        self.layout.addLayout(self.top_layout)
        self.layout.addLayout(self.grid_layout)
        self.layout.addLayout(self.bottom_layout)

        self.setLayout(self.layout)
        self.update_grid()
        self.update_start_print_array_button()

    def _set_array_button_state(self, button, enabled, active_color):
        button.setEnabled(bool(enabled))
        color = self.color_dict[active_color] if enabled else self.color_dict['darker_gray']
        button.setStyleSheet(f"background-color: {color}; color: white;")

    def update_start_print_array_button(self, *_args):
        has_head = self.model.rack_model.gripper_printer_head is not None
        state_getter = getattr(self.controller, "get_array_run_state", None)
        array_state = state_getter() if callable(state_getter) else "idle"

        if array_state == "running":
            self.start_print_array_button.setText("Stop After Well")
            self._set_array_button_state(self.start_print_array_button, True, 'dark_red')
            return

        if array_state == "stop_requested":
            self.start_print_array_button.setText("Stop Pending")
            self._set_array_button_state(self.start_print_array_button, False, 'dark_red')
            return

        if array_state == "resume_ready":
            self.start_print_array_button.setText("Resume Print")
            self._set_array_button_state(self.start_print_array_button, has_head, 'dark_blue')
            return

        self.start_print_array_button.setText("Start Print")
        self._set_array_button_state(self.start_print_array_button, has_head, 'dark_blue')

    def start_print_array(self):
        state_getter = getattr(self.controller, "get_array_run_state", None)
        array_state = state_getter() if callable(state_getter) else "idle"

        if array_state == "running":
            self.request_array_soft_stop()
            return

        if array_state == "stop_requested":
            return

        if not self.controller.check_if_all_completed():
            return
        is_resume = array_state == "resume_ready"
        title = "Resume Print Array" if is_resume else "Start Print Array"
        message = "Are you sure you want to resume the print array?" if is_resume else "Are you sure you want to start the print array?"
        response = self.main_window.popup_yes_no(title, message)
        if not self.main_window._is_yes_response(response):
            return

        print_kwargs = {}
        preflight_getter = getattr(self.controller, "get_print_array_imaging_calibration_preflight", None)
        preflight = preflight_getter() if callable(preflight_getter) else {"ok": True, "code": "ok"}
        if not bool((preflight or {}).get("ok")):
            code = str((preflight or {}).get("code") or "")
            message = str((preflight or {}).get("message") or "Applied imaging calibration could not be confirmed.")
            choice_getter = getattr(self.main_window, "popup_choice", None)
            if code in {"missing_record", "stale_design_volume"}:
                if callable(choice_getter):
                    choice = choice_getter(
                        "Applied Calibration Missing",
                        (
                            f"{message}\n\n"
                            "Proceeding may print with droplet counts or concentrations that do not match "
                            "a currently applied imaging calibration."
                        ),
                        ["Proceed without applied calibration", "Cancel"],
                        default="Cancel",
                    )
                    proceed = choice == "Proceed without applied calibration"
                else:
                    proceed = self.main_window._is_yes_response(
                        self.main_window.popup_yes_no(
                            "Applied Calibration Missing",
                            f"{message}\n\nProceed without applied imaging calibration?",
                        )
                    )
                if not proceed:
                    return
                print_kwargs["imaging_calibration_override"] = True
            elif code in {"pulse_width_mismatch", "pressure_mismatch"}:
                if callable(choice_getter):
                    choice = choice_getter(
                        "Print Settings Differ",
                        (
                            f"{message}\n\n"
                            "Choose whether to switch to the applied calibration settings, "
                            "print with the current settings, or cancel."
                        ),
                        [
                            "Switch to applied calibration settings",
                            "Proceed with current settings",
                            "Cancel",
                        ],
                        default="Cancel",
                    )
                else:
                    choice = "Cancel"

                if choice == "Switch to applied calibration settings":
                    applier = getattr(self.controller, "apply_applied_imaging_calibration_print_settings", None)
                    result = (
                        applier((preflight or {}).get("record"))
                        if callable(applier)
                        else {"ok": False, "message": "Controller cannot apply calibration settings."}
                    )
                    if bool((result or {}).get("ok")):
                        self.main_window.popup_message(
                            "Print Settings Changed",
                            (
                                f"{result.get('message', 'Applied calibration print settings.')}\n\n"
                                "Wait for the pressure to settle, then start the print array again."
                            ),
                        )
                    else:
                        self.main_window.popup_message(
                            "Print Settings Not Changed",
                            str((result or {}).get("message") or "Could not apply calibration settings."),
                        )
                    return
                if choice == "Proceed with current settings":
                    print_kwargs["settings_mismatch_override"] = True
                else:
                    return
            else:
                self.main_window.popup_message("Cannot Start Print Array", message)
                return

        self.controller.print_array(**print_kwargs)

    def request_array_soft_stop(self):
        request_stop = getattr(self.controller, "request_array_soft_stop", None)
        if callable(request_stop):
            request_stop()

    def update_grid(self):
        """Update the grid layout to match the selected plate format."""
        self.grid_layout.setSpacing(1)
        self.clear_grid()

        rows, cols = self.model.well_plate.get_plate_dimensions()
        self.well_labels = [[QLabel() for _ in range(cols)] for _ in range(rows)]

        # Column headers
        for col in range(cols):
            hdr = QLabel(str(col + 1))
            hdr.setStyleSheet("color: white;")
            hdr.setAlignment(Qt.AlignCenter)
            self.grid_layout.addWidget(hdr, 0, col + 1)

        # Row headers + wells
        row_labels = list(self.model.well_plate.iter_rows())
        for row in range(rows):
            row_hdr = QLabel(row_labels[row])
            row_hdr.setStyleSheet("color: white;")
            row_hdr.setAlignment(Qt.AlignCenter)
            self.grid_layout.addWidget(row_hdr, row + 1, 0)

        for row in range(rows):
            for col in range(cols):
                label = QLabel()
                label.setStyleSheet("border: 0.5px solid black; border-radius: 4px;")
                label.setAlignment(Qt.AlignCenter)
                self.grid_layout.addWidget(label, row + 1, col + 1)
                self.well_labels[row][col] = label

    def _update_plate_summary(self, name: str, rows: int, cols: int):
        if hasattr(self, "plate_format_value_label"):
            self.plate_format_value_label.setText(f"{name} ({rows}x{cols})")

    def _populate_reagent_selection(self):
        self.reagent_selection.clear()
        for stock_id in self.model.stock_solutions.get_stock_solution_names():
            stock_formatted = self.model.stock_solutions.get_formatted_from_stock_id(stock_id)
            self.reagent_selection.addItem(stock_formatted, userData=stock_id)

    def gripper_update_handler(self):
        """Handle when the gripper picks up a new printer head."""
        if self.model.rack_model.gripper_printer_head is not None:
            printer_head = self.model.rack_model.gripper_printer_head
            stock_id = printer_head.get_stock_id()
            find_data = getattr(self.reagent_selection, "findData", None)
            if callable(find_data):
                idx = find_data(stock_id)
            else:
                stock_name = printer_head.get_display_stock_name(new_line=False)
                idx = self.reagent_selection.findText(stock_name)
            self.reagent_selection.setCurrentIndex(idx)
            self.update_well_colors()            
    
    def update_well_colors(self, *_args):
        """Update the colors of the wells based on the selected reagent's concentration."""
        rows, cols = self.model.well_plate.get_plate_dimensions()
        enable_tooltips = (rows * cols) <= 384
        stock_id = None
        if not self.model.reaction_collection.is_empty():
            # Get the current reagent selection
            stock_index = self.reagent_selection.currentIndex()
            item_data = getattr(self.reagent_selection, "itemData", None)
            if callable(item_data):
                stock_id = item_data(stock_index)
            else:
                stock_formatted = self.reagent_selection.itemText(stock_index)
                stock_id = self.model.stock_solutions.get_stock_id_from_formatted(stock_formatted)
            #print(f"Stock ID: {stock_id}, Stock Index: {stock_index}, Stock Formatted: {stock_formatted}")
            if stock_id == None:
                print('No reagent selected')
                stock_id = self.model.stock_solutions.get_stock_solution_names()[0]
                find_data = getattr(self.reagent_selection, "findData", None)
                if callable(find_data):
                    idx = find_data(stock_id)
                else:
                    stock_formatted = self.model.stock_solutions.get_formatted_from_stock_id(stock_id)
                    idx = self.reagent_selection.findText(stock_formatted)
                self.reagent_selection.setCurrentIndex(idx)
                #print(f'---Using default reagent: {stock_id}---')
            max_concentration = self.model.reaction_collection.get_max_droplets(stock_id)
            printer_head = self.model.printer_head_manager.get_printer_head_by_id(stock_id)
            color = printer_head.get_color()
        else:
            max_concentration = 0
            color = 'grey'
        
        for well in self.model.well_plate.get_all_wells():
            if well.assigned_reaction:
                concentration = well.assigned_reaction.get_target_droplets_for_stock(stock_id)
                final_conc = self.model.get_well_stock_final_concentration(well.well_id, stock_id)
                state = well.assigned_reaction.check_stock_complete(stock_id)
                if state:
                    outline = 'white'
                else:
                    outline = 'black'
                if concentration is not None:
                    if max_concentration == 0:
                        opacity = 0
                    else:
                        opacity = concentration / max_concentration
                    color = QtGui.QColor(color)
                    color.setAlphaF(opacity)
                    rgba_color = f"rgba({color.red()},{color.green()},{color.blue()},{color.alpha()})"
                    self.well_labels[well.row_num][well.col-1].setStyleSheet(f"background-color: {rgba_color}; border: 1px solid {outline};")
                else:
                    self.well_labels[well.row_num][well.col-1].setStyleSheet(f"background-color: grey; border: 1px solid {outline};")
                if final_conc is None:
                    conc_text = "n/a"
                else:
                    try:
                        units = self.model.stock_solutions.get_stock_by_id(stock_id).units
                    except Exception:
                        units = ""
                    conc_text = f"{final_conc:.4f} {units}".strip()
                if enable_tooltips:
                    self.well_labels[well.row_num][well.col-1].setToolTip(
                        f"Well {well.well_id}\nTarget droplets: {int(concentration or 0)}\nFinal concentration: {conc_text}"
                    )
                else:
                    self.well_labels[well.row_num][well.col-1].setToolTip("")
            else:
                self.well_labels[well.row_num][well.col-1].setStyleSheet(f"background-color: none; border: 1px solid black;")
                if enable_tooltips:
                    self.well_labels[well.row_num][well.col-1].setToolTip(f"Well {well.well_id}\nNo reaction assigned")
                else:
                    self.well_labels[well.row_num][well.col-1].setToolTip("")


    def clear_grid(self):
        """Clear the existing grid."""
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def on_plate_selection_changed(self):
        """Deprecated: plate format is configured in Experiment Design dialog."""
        return
    
    def on_experiment_loaded(self):
        """Handle the experiment loaded signal."""
        # Update the options in the reagent selection combobox
        self._populate_reagent_selection()
        self.reagent_selection.setCurrentIndex(0)

        self.update_well_colors()  # Update with a default reagent on load
        print('Completed experiment load')

    def open_calibration_dialog(self):
        """
        Function to open the well plate calibration dialog.
        This function will be triggered when the calibration button is pressed.
        """
        # Create an instance of the CalibrationDialog
        if not self.model.machine_model.motors_are_enabled() or not self.model.machine_model.motors_are_homed():
            self.main_window.popup_message("Motors Not Enabled or Homed","Please enable and home the motors before calibrating the well plate.")
            return
        if self.model.rack_model.get_gripper_printer_head() != None:
            print("Gripper is loaded")
            if not self.model.rack_model.get_gripper_printer_head().is_calibration_chip():
                self.main_window.popup_message("Calibration Chip Required","Please load the calibration chip into the gripper before calibrating the rack.")
                return
            else:
                print("Calibration chip is loaded")
        else:
            print("Gripper is empty")
            response = self.main_window.popup_yes_no("Gripper Empty","Please load the calibration chip into the gripper before calibrating the rack. Proceed anyway?")
            if self.main_window._is_no_response(response):
                return
        self.controller.move_to_location('plate',z_offset=500)
        plate_calibration_dialog = PlateCalibrationDialog(self.main_window,self.model,self.controller)
        
        # Execute the dialog and check if the user completes the calibration
        if plate_calibration_dialog.exec() == QDialog.Accepted:
            print("Calibration completed successfully.")
            self.model.well_plate.update_calibration_data()

        else:
            print("Calibration was canceled or failed.")
            self.model.well_plate.discard_temp_calibrations()

    def open_experiment_designer(self):
        # dialog = ExperimentDesignDialog(self.main_window, self.model)
        dialog = ExperimentDesignDialog(self.model.experiment_model,self.main_window)
        if hasattr(dialog, "prepare_progress_policy_for_current_design"):
            if not dialog.prepare_progress_policy_for_current_design():
                return
        if dialog.exec():
            print("Experiment file generated and loaded.")

    def open_stock_prep_dialog(self):
        dialog = StockPrepDialog(self.model.experiment_model, self.main_window)
        dialog.exec()

class SimplePositionWidget(QGroupBox):
    home_requested = QtCore.Signal()  # Signal to request homing
    toggle_motor_requested = QtCore.Signal()  # Signal to toggle motor state

    def __init__(self, main_window, model, controller):
        super().__init__('POSITIONS')
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.controller = controller

        self.init_ui()

        # Connect the model's state_updated signal to the update_labels method
        self.model.machine_state_updated.connect(self.update_labels)
        self.model.machine_model.step_size_changed.connect(self.update_step_size)


    def init_ui(self):
        """Initialize the user interface."""
        main_layout = QHBoxLayout()  # Main horizontal layout

        # Create a grid layout for motor positions
        grid_layout = QGridLayout()

        # Add column headers
        motor_label = QLabel('Motor')
        current_label = QLabel('Current')
        target_label = QLabel('Target')
        motor_label.setAlignment(Qt.AlignCenter)
        current_label.setAlignment(Qt.AlignCenter)
        target_label.setAlignment(Qt.AlignCenter)

        grid_layout.addWidget(motor_label, 0, 0)
        grid_layout.addWidget(current_label, 0, 1)
        grid_layout.addWidget(target_label, 0, 2)

        # Labels to display motor positions
        self.labels = {
            'X': {'current': QLabel('0'), 'target': QLabel('0')},
            'Y': {'current': QLabel('0'), 'target': QLabel('0')},
            'Z': {'current': QLabel('0'), 'target': QLabel('0')},
            'P': {'current': QLabel('0'), 'target': QLabel('0')}
        }

        row = 1
        for motor, positions in self.labels.items():
            motor_label = QLabel(motor)
            motor_label.setAlignment(Qt.AlignCenter)
            motor_label.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
            grid_layout.addWidget(motor_label, row, 0)
            grid_layout.addWidget(positions['current'], row, 1)
            grid_layout.addWidget(positions['target'], row, 2)
            positions['current'].setAlignment(Qt.AlignCenter)
            positions['current'].setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
            positions['target'].setAlignment(Qt.AlignCenter)
            positions['target'].setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
            row += 1

        # Create a vertical layout for buttons and spin box
        button_layout = QVBoxLayout()

        fixed_width = 100  # Desired fixed width for the buttons
        fixed_height = 30  # Desired fixed height for the buttons

        # Add Step Size label and spin box
        self.step_size_label = QtWidgets.QLabel("Step Size:")
        self.step_size_label.setFixedHeight(fixed_height)  # Set a fixed height
        self.step_size_label.setFixedWidth(fixed_width)  # Set fixed width
        button_layout.addWidget(self.step_size_label, alignment=Qt.AlignRight)
        self.step_size_input = CustomSpinBox(self.model.machine_model.possible_steps)
        self.step_size_input.setRange(min(self.model.machine_model.possible_steps), max(self.model.machine_model.possible_steps))
        self.step_size_input.setValue(self.model.machine_model.step_size)
        self.step_size_input.setFocusPolicy(QtCore.Qt.NoFocus)
        self.step_size_input.setFixedWidth(fixed_width)  # Set fixed width
        self.step_size_input.setFixedHeight(fixed_height)  # Set a fixed height
        self.step_size_input.valueChangedByStep.connect(self.change_step_size)
        button_layout.addWidget(self.step_size_input, alignment=Qt.AlignRight)

        # Add grid layout and button layout to the main horizontal layout
        main_layout.addLayout(grid_layout)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

    def update_labels(self):
        """Update the labels with the current motor positions."""
        self.labels['X']['current'].setText(str(self.model.machine_model.current_x))
        self.labels['X']['target'].setText(str(self.model.machine_model.target_x))
        self.labels['Y']['current'].setText(str(self.model.machine_model.current_y))
        self.labels['Y']['target'].setText(str(self.model.machine_model.target_y))
        self.labels['Z']['current'].setText(str(self.model.machine_model.current_z))
        self.labels['Z']['target'].setText(str(self.model.machine_model.target_z))
        self.labels['P']['current'].setText(str(self.model.machine_model.current_p))
        self.labels['P']['target'].setText(str(self.model.machine_model.target_p))

    def update_step_size(self, new_step_size):
        """Update the spin box with the new step size."""
        self.step_size_input.setValue(new_step_size)

    def change_step_size(self, steps):
        """Update the model's step size when the spin box value changes."""
        new_step_size = int(self.step_size_input.value())
        self.model.machine_model.set_step_size(new_step_size)

class SpeedProfilesTab(QtWidgets.QWidget):
    """
    A mid-panel tab showing per-axis max speed and acceleration.
    - Rows: X, Y, Z
    - Columns: Axis | Max Speed (Hz) | Acceleration (steps/s^2)

    Signals:
        set_axis_maxspeed(axis_index:int, max_hz:int)
        set_axis_accel(axis_index:int, accel_sps2:int)
    """
    set_axis_maxspeed = QtCore.Signal(int, int)
    set_axis_accel    = QtCore.Signal(int, int)

    def __init__(self, parent, model, controller, color_dict):
        super().__init__(parent)
        self.main_window = parent
        self.model = model
        self.controller = controller
        self.color_dict = color_dict
        self.setObjectName("SpeedProfilesTab")
        self._dfu_manual_session = False 
        self._qualification_window = None
        self._regulator_calibration_window = None

        # Prevent feedback loops when we update widgets from model signals
        self._updating = False

        # Reasonable UI limits
        self._speed_min  = 1000       # Hz
        self._speed_max  = 100000     # Hz
        self._speed_step = 1000       # Hz

        self._acc_min    = 1000      # steps/s^2
        self._acc_max    = 200000    # steps/s^2
        self._acc_step   = 10000      # steps/s^2

        self._axis_rows = [
            ("X", 0),
            ("Y", 1),
            ("Z", 2),
        ]

        self._build_ui()
        self._connect_model_signals()

        # Background to match the rest of the mid-panel
        self.setStyleSheet(f"QWidget#SpeedProfilesTab {{ background-color: {self.color_dict['darker_gray']}; }}")

        # If the model already has values, try to show them once at startup
        self._pull_initial_values_if_available()

    # ---------------- UI ----------------

    def _build_ui(self):
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(10)

        # Header row
        hdr_axis = QtWidgets.QLabel("Axis")
        hdr_spd  = QtWidgets.QLabel("Max Speed (Hz)")
        hdr_acc  = QtWidgets.QLabel("Acceleration (steps/s²)")
        font = hdr_axis.font()
        font.setBold(True)
        hdr_axis.setFont(font); hdr_spd.setFont(font); hdr_acc.setFont(font)

        layout.addWidget(hdr_axis, 0, 0)
        layout.addWidget(hdr_spd,  0, 1)
        layout.addWidget(hdr_acc,  0, 2)

        self._speed_boxes = []
        self._accel_boxes = []

        for row_idx, (axis_name, axis_idx) in enumerate(self._axis_rows, start=1):
            # Axis label
            lbl = QtWidgets.QLabel(axis_name)
            layout.addWidget(lbl, row_idx, 0)

            # Speed spinbox
            spd = QtWidgets.QSpinBox()
            spd.setRange(self._speed_min, self._speed_max)
            spd.setSingleStep(self._speed_step)
            spd.setAccelerated(True)
            spd.setKeyboardTracking(False)
            spd.setToolTip("Per-axis max step rate (Hz)")

            # Make it not grab keyboard focus so shortcuts keep working
            spd.setFocusPolicy(QtCore.Qt.NoFocus)
            spd.setContextMenuPolicy(QtCore.Qt.NoContextMenu)

            spd.valueChanged.connect(self._mk_speed_handler(axis_idx))
            self._speed_boxes.append(spd)
            layout.addWidget(spd, row_idx, 1)

            # Accel spinbox
            acc = QtWidgets.QSpinBox()
            acc.setRange(self._acc_min, self._acc_max)
            acc.setSingleStep(self._acc_step)
            acc.setAccelerated(True)
            acc.setKeyboardTracking(False)
            acc.setToolTip("Per-axis acceleration (steps/s²)")

            # Same focus behavior
            acc.setFocusPolicy(QtCore.Qt.NoFocus)
            acc.setContextMenuPolicy(QtCore.Qt.NoContextMenu)

            acc.valueChanged.connect(self._mk_accel_handler(axis_idx))
            self._accel_boxes.append(acc)
            layout.addWidget(acc, row_idx, 2)

        # --- Firmware Update group ---
        row_after_table = len(self._axis_rows) + 1

        fw_group = QtWidgets.QGroupBox("Firmware Update")
        fw_v = QtWidgets.QVBoxLayout(fw_group)

        self.fw_status = QtWidgets.QLabel("Idle")
        self.fw_bar    = QtWidgets.QProgressBar()
        self.fw_bar.setRange(0, 100)
        self.fw_bar.setValue(0)

        self.firmware_update_button = QtWidgets.QPushButton("Update Firmware")
        self.firmware_update_button.setStyleSheet("""
                QPushButton:disabled {
                    background-color: #555555;
                    color: #AAAAAA;
                    border: 1px solid #444444;
                }
                """)
        self.firmware_update_button.clicked.connect(self._on_firmware_update_requested)

        fw_v.addWidget(self.fw_status)
        fw_v.addWidget(self.fw_bar)
        fw_v.addWidget(self.firmware_update_button)

        self.machine_qualification_button = QtWidgets.QPushButton("Machine Qualification...")
        self.machine_qualification_button.setObjectName("machineQualificationButton")
        self.machine_qualification_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.machine_qualification_button.clicked.connect(self._on_machine_qualification_requested)
        fw_v.addWidget(self.machine_qualification_button)

        self.regulator_calibration_button = QtWidgets.QPushButton("Regulator Calibration...")
        self.regulator_calibration_button.setObjectName("regulatorCalibrationButton")
        self.regulator_calibration_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.regulator_calibration_button.clicked.connect(self._on_regulator_calibration_requested)
        fw_v.addWidget(self.regulator_calibration_button)

        layout.addWidget(fw_group, row_after_table + 1, 0, 1, 3)

        app_update_group = QtWidgets.QGroupBox("Application Update")
        app_update_v = QtWidgets.QVBoxLayout(app_update_group)

        self.app_update_status_label = QtWidgets.QLabel("Check for updates before updating.")
        self.app_update_status_label.setWordWrap(True)
        app_update_v.addWidget(self.app_update_status_label)

        self.app_update_check_button = QtWidgets.QPushButton("Check for Updates")
        self.app_update_check_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.app_update_check_button.clicked.connect(self._on_app_update_check_requested)
        app_update_v.addWidget(self.app_update_check_button)

        self.app_update_button = QtWidgets.QPushButton("Update App")
        self.app_update_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.app_update_button.setEnabled(False)
        self.app_update_button.clicked.connect(self._on_app_update_requested)
        app_update_v.addWidget(self.app_update_button)

        layout.addWidget(app_update_group, row_after_table + 2, 0, 1, 3)

        # Add a new button for resetting the mcu board
        self.reset_mcu_button = QtWidgets.QPushButton("Reset MCU")
        self.reset_mcu_button.setStyleSheet("""
            QPushButton {
                background-color: #FF5555;
                color: #FFFFFF;
                border: 1px solid #FF4444;
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #AAAAAA;
                border: 1px solid #444444;
            }
        """)
        self.reset_mcu_button.clicked.connect(self._on_reset_mcu_requested)
        layout.addWidget(self.reset_mcu_button, row_after_table + 3, 0, 1, 3)

        # === MCU Task Usage table (scrollable) ===
        self.tasks_group = QtWidgets.QGroupBox("MCU Task Usage")
        tasks_v = QtWidgets.QVBoxLayout(self.tasks_group)

        self.tasks_table = QtWidgets.QTableWidget(0, 2, self)
        self.tasks_table.setHorizontalHeaderLabels(["Task", "CPU %"])
        self.tasks_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tasks_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.tasks_table.setAlternatingRowColors(True)
        self.tasks_table.verticalHeader().setVisible(False)
        self.tasks_table.horizontalHeader().setStretchLastSection(True)
        self.tasks_table.setSortingEnabled(True)
        self.tasks_table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.tasks_table.setContextMenuPolicy(QtCore.Qt.NoContextMenu)

        # Optional: make numbers right-aligned
        self.tasks_table.horizontalHeader().setDefaultAlignment(
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
        )

        tasks_v.addWidget(self.tasks_table)
        layout.addWidget(self.tasks_group, row_after_table + 4, 0, 1, 3)

        # Background style to match mid-panel (optional)
        self.tasks_group.setStyleSheet(
            f"QGroupBox {{ color: #DDD; border: 1px solid #444; margin-top: 6px; }}"
            f"QTableWidget {{ background-color: {self.color_dict['darker_gray']}; }}"
        )        

        # === Log Messages group (scrollable table) ===
        self.logs_group = QtWidgets.QGroupBox("Log Messages")                    # NEW
        logs_v = QtWidgets.QVBoxLayout(self.logs_group)                          # NEW

        self.logs_table = QtWidgets.QTableWidget(0, 1, self)                     # NEW
        self.logs_table.setHorizontalHeaderLabels(["Message"])                   # NEW
        self.logs_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.logs_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.logs_table.setAlternatingRowColors(True)
        self.logs_table.verticalHeader().setVisible(False)
        self.logs_table.horizontalHeader().setStretchLastSection(True)
        self.logs_table.setWordWrap(False)
        self.logs_table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.logs_table.setContextMenuPolicy(QtCore.Qt.NoContextMenu)
        self._log_max_rows = 2000                                                # NEW

        logs_v.addWidget(self.logs_table)                                        # NEW
        layout.addWidget(self.logs_group, row_after_table + 5, 0, 1, 3)          # NEW

        # Optional style
        self.logs_group.setStyleSheet(                                           # NEW
            f"QGroupBox {{ color: #DDD; border: 1px solid #444; margin-top: 6px; }}"
            f"QTableWidget {{ background-color: {self.color_dict['darker_gray']}; }}"
        )

        # Stretch/spacer row so everything stays at the top
        last_row = row_after_table + 6   # after logs_group                      # CHANGED
        spacer = QtWidgets.QSpacerItem(
            0, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding
        )
        layout.addItem(spacer, last_row, 0, 1, 4)
        layout.setRowStretch(last_row, 1)

        # Columns sizing
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
    # ------------- Model <-> View wiring -------------

    def _connect_model_signals(self):
        # These signals should carry speeds or accels for all three axes
        # Accept tuple/list order [X,Y,Z] or dicts like {"x":..,"y":..,"z":..}
        if hasattr(self.model.machine_model, "speeds_changed"):
            self.model.machine_model.speeds_changed.connect(self.on_speeds_changed)
        if hasattr(self.model.machine_model, "accelerations_changed"):
            self.model.machine_model.accelerations_changed.connect(self.on_accels_changed)
                # Connect DFU signals if the controller exposes them
        if hasattr(self.controller, "dfu_progress"):
            self.controller.dfu_progress.connect(self._on_dfu_progress)
        if hasattr(self.controller, "dfu_stage"):
            self.controller.dfu_stage.connect(self._on_dfu_stage)
        if hasattr(self.controller, "dfu_finished"):
            self.controller.dfu_finished.connect(self._on_dfu_finished)
        # Optional: live log lines
        if hasattr(self.controller, "dfu_output"):
            self.controller.dfu_output.connect(self._on_dfu_output)
        if hasattr(self.controller, "app_update_check_started"):
            self.controller.app_update_check_started.connect(self._on_app_update_check_started)
        if hasattr(self.controller, "app_update_check_finished"):
            self.controller.app_update_check_finished.connect(self._on_app_update_check_finished)

        self.controller.machine.log_stats_updated.connect(self._on_stats_updated)
        self.controller.machine.log_message_received.connect(self._on_log_message_received)

        self.set_axis_maxspeed.connect(self.controller.set_axis_maxspeed)
        self.set_axis_accel.connect(self.controller.set_axis_accel)

    def _pull_initial_values_if_available(self):
        """If the model already exposes current values, reflect them at startup."""
        # We intentionally don't fail if these attributes/methods don't exist.
        speeds = getattr(self.model.machine_model, "current_speeds", None)
        if speeds is None:
            get_speeds = getattr(self.model.machine_model, "get_current_speeds", None)
            if callable(get_speeds):
                speeds = get_speeds()
        if speeds is not None:
            self.on_speeds_changed(speeds)

        accels = getattr(self.model, "current_accelerations", None)
        if accels is None:
            get_accels = getattr(self.model, "get_current_accelerations", None)
            if callable(get_accels):
                accels = get_accels()
        if accels is not None:
            self.on_accels_changed(accels)

    # ---------------- Slots ----------------

    @QtCore.Slot(object)
    def on_speeds_changed(self, speeds: Any):
        """Update spin boxes from a model signal carrying X/Y/Z speeds."""
        # vals = self._extract_xyz(speeds)
        vals = self.model.machine_model.get_current_speeds()
        if vals is None:
            return
        x, y, z = vals
        self._updating = True
        try:
            for idx, val in enumerate((x, y, z)):
                box = self._speed_boxes[idx]
                # Clamp to UI limits so the control always accepts it
                box.setValue(int(max(self._speed_min, min(self._speed_max, int(val)))))
        finally:
            self._updating = False

    @QtCore.Slot(object)
    def on_accels_changed(self, accels: Any):
        """Update spin boxes from a model signal carrying X/Y/Z accelerations."""
        # vals = self._extract_xyz(accels)
        vals = self.model.machine_model.get_current_accelerations()
        if vals is None:
            return
        x, y, z = vals
        self._updating = True
        try:
            for idx, val in enumerate((x, y, z)):
                box = self._accel_boxes[idx]
                box.setValue(int(max(self._acc_min, min(self._acc_max, int(val)))))
        finally:
            self._updating = False

    # === Slot to update the table ===
    @QtCore.Slot(object)
    def _on_stats_updated(self, stats: dict):
        rows = stats.get("rows", []) or []
        # Keep current sort settings stable while updating to avoid flicker
        sorting_enabled = self.tasks_table.isSortingEnabled()
        if sorting_enabled:
            self.tasks_table.setSortingEnabled(False)

        self.tasks_table.setRowCount(len(rows))
        for r_idx, r in enumerate(rows):
            task_name = r.get("task", "")
            pct = r.get("percent", None)

            # Name column
            name_item = QtWidgets.QTableWidgetItem(task_name)
            name_item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.tasks_table.setItem(r_idx, 0, name_item)

            # Percent column (numeric sortable)
            if pct is None:
                pct_text = "—"
                pct_value = 0.0
            else:
                pct_text = f"{pct:.1f}"
                pct_value = float(pct)

            pct_item = QtWidgets.QTableWidgetItem(pct_text)
            pct_item.setFlags(QtCore.Qt.ItemIsEnabled)
            pct_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            # Use EditRole for numeric sorting
            pct_item.setData(QtCore.Qt.EditRole, pct_value)
            self.tasks_table.setItem(r_idx, 1, pct_item)

            # Optional: visually deemphasize IDLE a bit
            if task_name.strip().upper() == "IDLE":
                pct_item.setForeground(QtGui.QBrush(QtGui.QColor("#A0E3A0")))
                name_item.setForeground(QtGui.QBrush(QtGui.QColor("#A0E3A0")))

        # Resize columns to contents once (or occasionally)
        self.tasks_table.resizeColumnToContents(0)

        if sorting_enabled:
            self.tasks_table.setSortingEnabled(True)

    @QtCore.Slot(str)
    def _on_log_message_received(self, text: str):
        self._append_log_line(text)

    # === Table appender with cap & autoscroll ===
    def _append_log_line(self, text: str):
        if not text:
            return
        # Cap the rows (remove oldest if needed)
        rowcount = self.logs_table.rowCount()
        if rowcount >= self._log_max_rows:
            # remove top chunk to avoid O(n) per message; drop 50 at once
            for _ in range(50):
                if self.logs_table.rowCount() == 0:
                    break
                self.logs_table.removeRow(0)

        row = self.logs_table.rowCount()
        self.logs_table.insertRow(row)
        item = QtWidgets.QTableWidgetItem(text)
        item.setFlags(QtCore.Qt.ItemIsEnabled)
        self.logs_table.setItem(row, 0, item)
        # Ensure view stays scrolled to latest
        self.logs_table.scrollToBottom()

    # ---------- DFU UI handlers ----------
    @QtCore.Slot()
    def _on_firmware_update_requested(self):
        # Lock the button and change its text
        self.firmware_update_button.setEnabled(False)
        self.firmware_update_button.setText("Updating…")
        # Indeterminate bar while the worker spins up
        self.fw_bar.setRange(0, 0)
        self.fw_status.setText("Starting…")

        manual = sys.platform.startswith("win")
        self._dfu_manual_session = manual

        if manual:
            msg = (
                "The legacy machine requires MANUAL DFU mode.\n\n"
                "Before clicking Yes:\n"
                "  1) Connect the MCU board to this computer via USB.\n"
                "  2) Place the jumper on the BOOT0/BOOT pins (BOOT0 = 1).\n"
                "  3) Press and release the RESET button on the MCU board.\n\n"
                "Then click Yes to start flashing."
            )
            response = self.main_window.popup_yes_no("Enter DFU Mode (Manual)", msg)
            if not self.main_window._is_yes_response(response):
                # user cancelled -> restore UI
                self.fw_bar.setRange(0, 100)
                self.fw_bar.setValue(0)
                self.fw_status.setText("Cancelled.")
                self.firmware_update_button.setEnabled(True)
                self.firmware_update_button.setText("Update Firmware")
                self._dfu_manual_session = False
                return
            
        # Kick the controller
        if hasattr(self.controller, "start_firmware_update"):
            print("[View] Starting firmware update...")
            self.controller.start_firmware_update(manual = self._dfu_manual_session)
        else:
            self.fw_status.setText("Controller does not support firmware update.")
            self.fw_bar.setRange(0, 100)
            self.fw_bar.setValue(0)
            self.firmware_update_button.setEnabled(True)
            self.firmware_update_button.setText("Update Firmware")
            self._dfu_manual_session = False
        # elif hasattr(self.controller, "update_firmware"):
        #     self.fw_status.setText("Running (UI will freeze)…")
        #     self.controller.update_firmware()

    @QtCore.Slot()
    def _on_app_update_requested(self):
        self.main_window.request_app_update()

    @QtCore.Slot()
    def _on_app_update_check_requested(self):
        self.main_window.request_app_update_check()

    @QtCore.Slot()
    def _on_app_update_check_started(self):
        self.app_update_status_label.setText("Checking for updates...")
        self.app_update_check_button.setEnabled(False)
        self.app_update_button.setEnabled(False)

    @QtCore.Slot(object)
    def _on_app_update_check_finished(self, result):
        self.app_update_check_button.setEnabled(True)
        status = str(getattr(result, "status", "") or "")
        message = str(getattr(result, "message", "") or "Update check finished.")

        if status == "update_available":
            behind_count = int(getattr(result, "behind_count", 0) or 0)
            self.app_update_status_label.setText(message)
            blockers_getter = getattr(self.controller, "get_app_update_blockers", None)
            blockers = blockers_getter() if callable(blockers_getter) else []
            self.app_update_button.setEnabled(not blockers)
            commits = [str(commit) for commit in getattr(result, "commits", ()) if str(commit).strip()]
            details = [message]
            if behind_count:
                details.append(f"Pending commits: {behind_count}")
            if commits:
                details.append("")
                details.extend(f"- {commit}" for commit in commits[:10])
                if len(commits) > 10:
                    details.append(f"- ...and {len(commits) - 10} more")
            self.main_window.popup_message("Updates Available", "\n".join(details))
            return

        self.app_update_button.setEnabled(False)
        self.app_update_status_label.setText(message)

    @QtCore.Slot()
    def _on_machine_qualification_requested(self):
        window = getattr(self, "_qualification_window", None)
        if window is not None:
            try:
                window.show()
                window.raise_()
                window.activateWindow()
                return
            except RuntimeError:
                self._qualification_window = None

        from QualificationView import MachineQualificationWindow

        self._qualification_window = MachineQualificationWindow(self.main_window, self.controller)
        self._qualification_window.destroyed.connect(
            lambda *_args: setattr(self, "_qualification_window", None)
        )
        self._qualification_window.show()
        self._qualification_window.raise_()
        self._qualification_window.activateWindow()

    @QtCore.Slot()
    def _on_regulator_calibration_requested(self):
        window = getattr(self, "_regulator_calibration_window", None)
        if window is not None:
            try:
                window.show()
                window.raise_()
                window.activateWindow()
                return
            except RuntimeError:
                self._regulator_calibration_window = None

        from RegulatorCalibrationWindow import RegulatorCalibrationWindow

        self._regulator_calibration_window = RegulatorCalibrationWindow(
            self.main_window,
            self.model,
            self.controller,
        )
        self._regulator_calibration_window.destroyed.connect(
            lambda *_args: setattr(self, "_regulator_calibration_window", None)
        )
        self._regulator_calibration_window.show()
        self._regulator_calibration_window.raise_()
        self._regulator_calibration_window.activateWindow()

    @QtCore.Slot()
    def _on_reset_mcu_requested(self):
        # Confirm with the user
        response = self.main_window.popup_yes_no("Reset MCU","Are you sure you want to reset the microcontroller unit (MCU)? This will interrupt any ongoing operations.")
        if self.main_window._is_yes_response(response):
            if hasattr(self.controller, "reset_mcu_board"):
                self.controller.reset_mcu_board()
            else:
                self.main_window.popup_message("Reset MCU","The controller does not support MCU reset.")

    @QtCore.Slot(int)
    def _on_dfu_progress(self, p):
        if self.fw_bar.maximum() == 0:
            self.fw_bar.setRange(0, 100)  # switch from indeterminate
        self.fw_bar.setValue(max(0, min(100, p)))

    @QtCore.Slot(str)
    def _on_dfu_stage(self, msg):
        self.fw_status.setText(msg)

    @QtCore.Slot(bool, str)
    def _on_dfu_finished(self, ok, msg):
        # Restore button & show result
        self.fw_status.setText(("✅ " if ok else "❌ ") + msg)
        self.fw_bar.setRange(0, 100)
        self.fw_bar.setValue(100 if ok else 0)
        self.firmware_update_button.setEnabled(True)
        self.firmware_update_button.setText("Update Firmware")

        # --- manual DFU exit prompt ---
        if ok and getattr(self, "_dfu_manual_session", False):
            self.main_window.popup_message(
                "Exit DFU Mode (Manual)",
                "Firmware upload complete.\n\n"
                "Now:\n"
                "  1) REMOVE the BOOT0/BOOT jumper (BOOT0 = 0)\n"
                "  2) Press and release RESET to boot the new firmware."
            )
        self._dfu_manual_session = False

    @QtCore.Slot(str)
    def _on_dfu_output(self, line):
        # Optional: surface raw dfu-util output somewhere if you want
        # print('DFU:', line)
        self._append_log_line(line)
        # pass
    # ---------------- Emitters ----------------

    def _mk_speed_handler(self, axis_idx: int):
        def _handler(value: int):
            if self._updating:
                return
            self.set_axis_maxspeed.emit(axis_idx, int(value))
        return _handler

    def _mk_accel_handler(self, axis_idx: int):
        def _handler(value: int):
            if self._updating:
                return
            self.set_axis_accel.emit(axis_idx, int(value))
        return _handler

    # ---------------- Helpers ----------------

    @staticmethod
    def _extract_xyz(payload: Any) -> Optional[tuple[int, int, int]]:
        """
        Accepts:
          - Sequence/tuple/list like [x, y, z]
          - Mapping/dict with keys 'x','y','z' (case-insensitive)
          - Mapping/dict with 0,1,2
        Returns (x,y,z) or None.
        """
        if payload is None:
            return None

        # Sequence
        if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
            if len(payload) >= 3:
                try:
                    return int(payload[0]), int(payload[1]), int(payload[2])
                except Exception:
                    return None

        # Mapping
        if isinstance(payload, Mapping):
            # common lowercase keys
            keys = {k.lower(): k for k in payload.keys()}
            def _get(k, fallback=None):
                if k in keys:
                    return payload[keys[k]]
                return fallback
            try:
                x = _get('x', payload.get(0))
                y = _get('y', payload.get(1))
                z = _get('z', payload.get(2))
                if x is None or y is None or z is None:
                    return None
                return int(x), int(y), int(z)
            except Exception:
                return None

        return None

class PreprogrammedSequencesTab(QtWidgets.QWidget):
    def __init__(self, main_window, model, controller, color_dict):
        super().__init__()
        self.main_window = main_window
        self.model = model
        self.controller = controller
        self.color_dict = color_dict

        self._auto_switch_threshold_s = 2.0
        self._switched_to_well_plate = False

        self._build_ui()
        self._wire_signals()
        self._set_state("idle")

    def _build_ui(self):
        self.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        # --- Delay / Countdown row ---
        top = QtWidgets.QGroupBox("Start Delay")
        top_layout = QtWidgets.QGridLayout(top)

        top_layout.addWidget(QtWidgets.QLabel("Delay before start (s):"), 0, 0)
        self.delay_spin = QtWidgets.QDoubleSpinBox()
        self.delay_spin.setRange(0, 120)
        self.delay_spin.setDecimals(1)
        self.delay_spin.setSingleStep(0.5)
        self.delay_spin.setValue(5.0)
        self.delay_spin.setFocusPolicy(QtCore.Qt.NoFocus)
        top_layout.addWidget(self.delay_spin, 0, 1)

        self.countdown_label = QtWidgets.QLabel("Ready")
        f = self.countdown_label.font()
        f.setPointSize(14)
        f.setBold(True)
        self.countdown_label.setFont(f)
        self.countdown_label.setAlignment(Qt.AlignCenter)
        top_layout.addWidget(self.countdown_label, 1, 0, 1, 2)

        self.cancel_btn = QtWidgets.QPushButton("Cancel Countdown")
        self.cancel_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        self.cancel_btn.clicked.connect(self.controller.cancel_preprogrammed_sequence)
        top_layout.addWidget(self.cancel_btn, 2, 0, 1, 2)

        outer.addWidget(top)

        # --- Sequences list ---
        seq_box = QtWidgets.QGroupBox("Preprogrammed Sequences")
        seq_layout = QtWidgets.QGridLayout(seq_box)
        seq_layout.setColumnStretch(0, 1)
        seq_layout.setColumnStretch(1, 0)

        # 1) Pickup slot -> imager -> return
        self.pickup_btn = QtWidgets.QPushButton("Pickup Slot → Imager → Return")
        self.pickup_btn.setFocusPolicy(QtCore.Qt.NoFocus)

        self.pickup_slot_spin = QtWidgets.QSpinBox()
        self.pickup_slot_spin.setRange(1, 4)
        self.pickup_slot_spin.setValue(1)
        self.pickup_slot_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        seq_layout.addWidget(self.pickup_btn,        0, 0)
        seq_layout.addWidget(QtWidgets.QLabel("Slot:"), 0, 1)
        seq_layout.addWidget(self.pickup_slot_spin,  0, 2)

        # 2) LED on -> wait -> off
        self.led_btn = QtWidgets.QPushButton("LED On → Wait → LED Off")
        self.led_btn.setFocusPolicy(QtCore.Qt.NoFocus)

        self.led_wait_spin = QtWidgets.QDoubleSpinBox()
        self.led_wait_spin.setRange(0.1, 120.0)
        self.led_wait_spin.setDecimals(1)
        self.led_wait_spin.setSingleStep(0.5)
        self.led_wait_spin.setValue(5.0)
        self.led_wait_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        seq_layout.addWidget(self.led_btn,           1, 0)
        seq_layout.addWidget(QtWidgets.QLabel("On-time (s):"), 1, 1)
        seq_layout.addWidget(self.led_wait_spin,     1, 2)

        # 3) Imager -> plate -> imager
        self.move_btn = QtWidgets.QPushButton("Imager → Plate → Imager")
        self.move_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        seq_layout.addWidget(self.move_btn,          2, 0, 1, 3)

        # 4) Snake grid droplet print
        self.grid_btn = QtWidgets.QPushButton("Snake Grid: Print Droplets")
        self.grid_btn.setFocusPolicy(QtCore.Qt.NoFocus)

        # params widget so we don't fight the grid columns
        grid_params = QtWidgets.QWidget()
        grid_params_layout = QtWidgets.QHBoxLayout(grid_params)
        grid_params_layout.setContentsMargins(0, 0, 0, 0)
        grid_params_layout.setSpacing(8)

        self.grid_rows_spin = QtWidgets.QSpinBox()
        self.grid_rows_spin.setRange(1, 200)
        self.grid_rows_spin.setValue(5)
        self.grid_rows_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        self.grid_cols_spin = QtWidgets.QSpinBox()
        self.grid_cols_spin.setRange(1, 200)
        self.grid_cols_spin.setValue(5)
        self.grid_cols_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        self.grid_step_spin = QtWidgets.QSpinBox()
        self.grid_step_spin.setRange(0, 500000)
        self.grid_step_spin.setValue(50)
        self.grid_step_spin.setSingleStep(10)
        self.grid_step_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        self.grid_droplets_spin = QtWidgets.QSpinBox()
        self.grid_droplets_spin.setRange(1, 10000)
        self.grid_droplets_spin.setValue(1)
        self.grid_droplets_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        grid_params_layout.addWidget(QtWidgets.QLabel("Rows:"))
        grid_params_layout.addWidget(self.grid_rows_spin)
        grid_params_layout.addWidget(QtWidgets.QLabel("Cols:"))
        grid_params_layout.addWidget(self.grid_cols_spin)
        grid_params_layout.addWidget(QtWidgets.QLabel("Step (steps):"))
        grid_params_layout.addWidget(self.grid_step_spin)
        grid_params_layout.addWidget(QtWidgets.QLabel("Droplets/spot:"))
        grid_params_layout.addWidget(self.grid_droplets_spin)
        grid_params_layout.addStretch(1)

        # Add to the sequences grid layout
        seq_layout.addWidget(self.grid_btn,    3, 0)
        seq_layout.addWidget(grid_params,      3, 1, 1, 2)

        # 5) Droplet walk +Y (1,2,3,...)
        self.walk_btn = QtWidgets.QPushButton("Droplet Walk +Y (1,2,3,...)")
        self.walk_btn.setFocusPolicy(QtCore.Qt.NoFocus)

        walk_params = QtWidgets.QWidget()
        walk_layout = QtWidgets.QHBoxLayout(walk_params)
        walk_layout.setContentsMargins(0, 0, 0, 0)
        walk_layout.setSpacing(8)

        self.walk_nspots_spin = QtWidgets.QSpinBox()
        self.walk_nspots_spin.setRange(1, 500)
        self.walk_nspots_spin.setValue(8)
        self.walk_nspots_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        self.walk_stepy_spin = QtWidgets.QSpinBox()
        self.walk_stepy_spin.setRange(0, 500000)
        self.walk_stepy_spin.setValue(50)
        self.walk_stepy_spin.setSingleStep(5)
        self.walk_stepy_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        self.walk_start_spin = QtWidgets.QSpinBox()
        self.walk_start_spin.setRange(1, 10000)
        self.walk_start_spin.setValue(1)
        self.walk_start_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        self.walk_inc_spin = QtWidgets.QSpinBox()
        self.walk_inc_spin.setRange(0, 10000)
        self.walk_inc_spin.setValue(1)
        self.walk_inc_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        walk_layout.addWidget(QtWidgets.QLabel("Spots:"))
        walk_layout.addWidget(self.walk_nspots_spin)
        walk_layout.addWidget(QtWidgets.QLabel("ΔY (steps):"))
        walk_layout.addWidget(self.walk_stepy_spin)
        walk_layout.addWidget(QtWidgets.QLabel("Start droplets:"))
        walk_layout.addWidget(self.walk_start_spin)
        walk_layout.addWidget(QtWidgets.QLabel("+ per spot:"))
        walk_layout.addWidget(self.walk_inc_spin)
        walk_layout.addStretch(1)

        seq_layout.addWidget(self.walk_btn, 4, 0)
        seq_layout.addWidget(walk_params, 4, 1, 1, 2)

        # --- Bridge & Pull sequence ---
        self.bridge_pull_btn = QtWidgets.QPushButton("Bridge & Pull +Y (Target → Payload)")
        self.bridge_pull_btn.setFocusPolicy(QtCore.Qt.NoFocus)

        bridge_params = QtWidgets.QWidget()
        bridge_layout = QtWidgets.QHBoxLayout(bridge_params)
        bridge_layout.setContentsMargins(0, 0, 0, 0)
        bridge_layout.setSpacing(8)

        self.payload_droplets_spin = QtWidgets.QSpinBox()
        self.payload_droplets_spin.setRange(1, 10000)
        self.payload_droplets_spin.setValue(5)
        self.payload_droplets_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        self.target_droplets_spin = QtWidgets.QSpinBox()
        self.target_droplets_spin.setRange(1, 10000)
        self.target_droplets_spin.setValue(10)
        self.target_droplets_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        self.separation_steps_spin = QtWidgets.QSpinBox()
        self.separation_steps_spin.setRange(0, 500000)
        self.separation_steps_spin.setValue(100)
        self.separation_steps_spin.setSingleStep(10)
        self.separation_steps_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        self.bridge_spacing_steps_spin = QtWidgets.QSpinBox()
        self.bridge_spacing_steps_spin.setRange(1, 500000)
        self.bridge_spacing_steps_spin.setValue(10)
        self.bridge_spacing_steps_spin.setSingleStep(5)
        self.bridge_spacing_steps_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        bridge_layout.addWidget(QtWidgets.QLabel("Payload droplets:"))
        bridge_layout.addWidget(self.payload_droplets_spin)
        bridge_layout.addWidget(QtWidgets.QLabel("Target droplets:"))
        bridge_layout.addWidget(self.target_droplets_spin)
        bridge_layout.addWidget(QtWidgets.QLabel("Separation +Y (steps):"))
        bridge_layout.addWidget(self.separation_steps_spin)
        bridge_layout.addWidget(QtWidgets.QLabel("Bridge spacing (steps):"))
        bridge_layout.addWidget(self.bridge_spacing_steps_spin)
        bridge_layout.addStretch(1)

        # pick a row index that doesn't collide with your existing ones
        row = 5
        seq_layout.addWidget(self.bridge_pull_btn, row, 0)
        seq_layout.addWidget(bridge_params,       row, 1, 1, 2)

        # --- Bridge & Pull x3 (single payload, 3 steps) ---
        self.bridge3_btn = QtWidgets.QPushButton("Bridge & Pull x3 +Y (Target → Payload)")
        self.bridge3_btn.setFocusPolicy(QtCore.Qt.NoFocus)

        bridge3_params = QtWidgets.QWidget()
        bridge3_grid = QtWidgets.QGridLayout(bridge3_params)
        bridge3_grid.setContentsMargins(0, 0, 0, 0)
        bridge3_grid.setHorizontalSpacing(10)
        bridge3_grid.setVerticalSpacing(6)

        # Payload (only once)
        self.bridge3_payload_spin = QtWidgets.QSpinBox()
        self.bridge3_payload_spin.setRange(1, 10000)
        self.bridge3_payload_spin.setValue(5)
        self.bridge3_payload_spin.setFocusPolicy(QtCore.Qt.NoFocus)

        bridge3_grid.addWidget(QtWidgets.QLabel("Payload droplets (start):"), 0, 0)
        bridge3_grid.addWidget(self.bridge3_payload_spin,                     0, 1)

        # Helper to make step rows
        def _make_step_controls(default_target=10, default_sep=200, default_spacing=50):
            t = QtWidgets.QSpinBox()
            t.setRange(1, 10000)
            t.setValue(default_target)
            t.setFocusPolicy(QtCore.Qt.NoFocus)

            sep = QtWidgets.QSpinBox()
            sep.setRange(0, 500000)
            sep.setValue(default_sep)
            sep.setSingleStep(10)
            sep.setFocusPolicy(QtCore.Qt.NoFocus)

            sp = QtWidgets.QSpinBox()
            sp.setRange(1, 500000)
            sp.setValue(default_spacing)
            sp.setSingleStep(5)
            sp.setFocusPolicy(QtCore.Qt.NoFocus)
            return t, sep, sp

        # Headers
        bridge3_grid.addWidget(QtWidgets.QLabel(""),                  1, 0)
        bridge3_grid.addWidget(QtWidgets.QLabel("Target droplets"),   1, 1)
        bridge3_grid.addWidget(QtWidgets.QLabel("Separation +Y"),     1, 2)
        bridge3_grid.addWidget(QtWidgets.QLabel("Bridge spacing"),    1, 3)

        # Step 1
        self.bridge3_t1_spin, self.bridge3_sep1_spin, self.bridge3_sp1_spin = _make_step_controls()
        bridge3_grid.addWidget(QtWidgets.QLabel("Step 1:"), 2, 0)
        bridge3_grid.addWidget(self.bridge3_t1_spin,       2, 1)
        bridge3_grid.addWidget(self.bridge3_sep1_spin,     2, 2)
        bridge3_grid.addWidget(self.bridge3_sp1_spin,      2, 3)

        # Step 2
        self.bridge3_t2_spin, self.bridge3_sep2_spin, self.bridge3_sp2_spin = _make_step_controls()
        bridge3_grid.addWidget(QtWidgets.QLabel("Step 2:"), 3, 0)
        bridge3_grid.addWidget(self.bridge3_t2_spin,       3, 1)
        bridge3_grid.addWidget(self.bridge3_sep2_spin,     3, 2)
        bridge3_grid.addWidget(self.bridge3_sp2_spin,      3, 3)

        # Step 3
        self.bridge3_t3_spin, self.bridge3_sep3_spin, self.bridge3_sp3_spin = _make_step_controls()
        bridge3_grid.addWidget(QtWidgets.QLabel("Step 3:"), 4, 0)
        bridge3_grid.addWidget(self.bridge3_t3_spin,       4, 1)
        bridge3_grid.addWidget(self.bridge3_sep3_spin,     4, 2)
        bridge3_grid.addWidget(self.bridge3_sp3_spin,      4, 3)

        # Add into the sequences grid layout on the next available row
        row = seq_layout.rowCount()
        seq_layout.addWidget(self.bridge3_btn,    row, 0)
        seq_layout.addWidget(bridge3_params,      row, 1, 1, 2)


        outer.addWidget(seq_box)
        outer.addStretch(1)

        # Bind button actions
        self.pickup_btn.clicked.connect(self._run_pickup_sequence)
        self.led_btn.clicked.connect(self._run_led_sequence)
        self.move_btn.clicked.connect(self._run_move_sequence)
        self.grid_btn.clicked.connect(self._run_snake_grid_sequence)
        self.walk_btn.clicked.connect(self._run_walk_sequence)
        self.bridge_pull_btn.clicked.connect(self._run_bridge_pull_sequence)
        self.bridge3_btn.clicked.connect(self._run_bridge_pull3_sequence)


    def _wire_signals(self):
        self.controller.sequence_state_changed.connect(self._set_state)
        self.controller.sequence_countdown_s.connect(self._on_countdown)
        self.controller.sequence_error.connect(self._on_error)
        self.controller.sequence_completed.connect(self._on_completed)

        # If your model has a machine_state_updated signal, keep enable/disable fresh
        if hasattr(self.model, "machine_state_updated"):
            self.model.machine_state_updated.connect(self._refresh_enabled)

        # Also refresh once at startup
        self._refresh_enabled()

    def _refresh_enabled(self):
        connected = True
        try:
            connected = bool(self.model.machine_model.is_connected())
        except Exception:
            pass

        idle = (getattr(self.controller, "_seq_state", "idle") == "idle")
        enable = connected and idle

        # enable main controls only when idle
        self.pickup_btn.setEnabled(enable)
        self.pickup_slot_spin.setEnabled(enable)
        self.led_btn.setEnabled(enable)
        self.led_wait_spin.setEnabled(enable)
        self.move_btn.setEnabled(enable)
        self.delay_spin.setEnabled(enable)

        self.grid_btn.setEnabled(enable)
        self.grid_rows_spin.setEnabled(enable)
        self.grid_cols_spin.setEnabled(enable)
        self.grid_step_spin.setEnabled(enable)
        self.grid_droplets_spin.setEnabled(enable)

        self.walk_btn.setEnabled(enable)
        self.walk_nspots_spin.setEnabled(enable)
        self.walk_stepy_spin.setEnabled(enable)
        self.walk_start_spin.setEnabled(enable)
        self.walk_inc_spin.setEnabled(enable)

        self.bridge_pull_btn.setEnabled(enable)
        self.payload_droplets_spin.setEnabled(enable)
        self.target_droplets_spin.setEnabled(enable)
        self.separation_steps_spin.setEnabled(enable)
        self.bridge_spacing_steps_spin.setEnabled(enable)

        self.bridge3_btn.setEnabled(enable)
        self.bridge3_payload_spin.setEnabled(enable)

        self.bridge3_t1_spin.setEnabled(enable)
        self.bridge3_sep1_spin.setEnabled(enable)
        self.bridge3_sp1_spin.setEnabled(enable)

        self.bridge3_t2_spin.setEnabled(enable)
        self.bridge3_sep2_spin.setEnabled(enable)
        self.bridge3_sp2_spin.setEnabled(enable)

        self.bridge3_t3_spin.setEnabled(enable)
        self.bridge3_sep3_spin.setEnabled(enable)
        self.bridge3_sp3_spin.setEnabled(enable)

        # cancel only during countdown
        self.cancel_btn.setEnabled(getattr(self.controller, "_seq_state", "idle") == "countdown")

    def _format_seconds(self, s: float) -> str:
        s = max(0.0, float(s))
        return f"{s:.1f}s"

    def _set_state(self, state: str):
        if state == "idle":
            self._switched_to_well_plate = False
            self.countdown_label.setText("Ready")
        elif state == "countdown":
            self._switched_to_well_plate = False
            # countdown label gets updated by _on_countdown
            pass
        elif state == "running":
            self.countdown_label.setText("Running…")
        else:
            self.countdown_label.setText(state)
        self._refresh_enabled()

    def _on_countdown(self, remaining_s: float):
        if getattr(self.controller, "_seq_state", "") != "countdown":
            return

        self.countdown_label.setText(f"Starting in {self._format_seconds(remaining_s)}")

        if (remaining_s <= self._auto_switch_threshold_s) and (not self._switched_to_well_plate):
            # Switch UI to Well Plate tab for recordings
            if hasattr(self.main_window, "show_well_plate_tab"):
                self.main_window.show_well_plate_tab()
            self._switched_to_well_plate = True
            
    def _on_error(self, msg: str):
        self.main_window.popup_message("Sequence Error", msg)
        self._refresh_enabled()

    def _on_completed(self, seq_id: str):
        self.countdown_label.setText("Done")
        self._refresh_enabled()

    # -----------------
    # Run button actions
    # -----------------

    def _run_pickup_sequence(self):
        delay = float(self.delay_spin.value())
        slot  = int(self.pickup_slot_spin.value())
        self.controller.start_preprogrammed_sequence(
            "pickup_slot_imager_return",
            delay_s=delay,
            slot=slot
        )

    def _run_led_sequence(self):
        delay = float(self.delay_spin.value())
        on_s  = float(self.led_wait_spin.value())
        self.controller.start_preprogrammed_sequence(
            "led_on_wait_off",
            delay_s=delay,
            on_s=on_s
        )

    def _run_move_sequence(self):
        delay = float(self.delay_spin.value())
        self.controller.start_preprogrammed_sequence(
            "imager_plate_imager",
            delay_s=delay
        )

    def _run_snake_grid_sequence(self):
        delay = float(self.delay_spin.value())
        rows = int(self.grid_rows_spin.value())
        cols = int(self.grid_cols_spin.value())
        step = int(self.grid_step_spin.value())
        droplets = int(self.grid_droplets_spin.value())

        self.controller.start_preprogrammed_sequence(
            "snake_grid_droplet_print",
            delay_s=delay,
            rows=rows,
            cols=cols,
            step=step,
            droplets=droplets
        )
        
    def _run_walk_sequence(self):
        delay = float(self.delay_spin.value())
        n_spots = int(self.walk_nspots_spin.value())
        step_y = int(self.walk_stepy_spin.value())
        start = int(self.walk_start_spin.value())
        inc = int(self.walk_inc_spin.value())

        self.controller.start_preprogrammed_sequence(
            "droplet_walk_y",
            delay_s=delay,
            n_spots=n_spots,
            step_y=step_y,
            start_droplets=start,
            inc_droplets=inc,
        )
        
    def _run_bridge_pull_sequence(self):
        delay = float(self.delay_spin.value())

        payload = int(self.payload_droplets_spin.value())
        target = int(self.target_droplets_spin.value())
        separation = int(self.separation_steps_spin.value())
        bridge_spacing = int(self.bridge_spacing_steps_spin.value())

        self.controller.start_preprogrammed_sequence(
            "bridge_and_pull_y",
            delay_s=delay,
            payload_droplets=payload,
            target_droplets=target,
            separation_steps=separation,
            bridge_spacing_steps=bridge_spacing,
        )

    def _run_bridge_pull3_sequence(self):
        delay = float(self.delay_spin.value())

        payload = int(self.bridge3_payload_spin.value())

        t1 = int(self.bridge3_t1_spin.value())
        sep1 = int(self.bridge3_sep1_spin.value())
        sp1 = int(self.bridge3_sp1_spin.value())

        t2 = int(self.bridge3_t2_spin.value())
        sep2 = int(self.bridge3_sep2_spin.value())
        sp2 = int(self.bridge3_sp2_spin.value())

        t3 = int(self.bridge3_t3_spin.value())
        sep3 = int(self.bridge3_sep3_spin.value())
        sp3 = int(self.bridge3_sp3_spin.value())

        self.controller.start_preprogrammed_sequence(
            "bridge_pull_y_3step",
            delay_s=delay,

            payload_droplets=payload,

            step1_target_droplets=t1,
            step1_separation_steps=sep1,
            step1_bridge_spacing_steps=sp1,

            step2_target_droplets=t2,
            step2_separation_steps=sep2,
            step2_bridge_spacing_steps=sp2,

            step3_target_droplets=t3,
            step3_separation_steps=sep3,
            step3_bridge_spacing_steps=sp3,
        )

class BaseCalibrationDialog(QDialog):
    def __init__(self, main_window, model, controller, title, steps, name_dict,offsets):
        super().__init__()
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.controller = controller
        self.shortcut_manager = ShortcutManager(self)
        self.setup_shortcuts()
        self.steps = steps
        self.name_dict = name_dict
        self.current_step = 0
        self.initial_calibrations = self.get_initial_calibrations()

        self.offsets = offsets

        self.setWindowTitle(title)
        self.setFixedSize(1200, 600)
        
        # Layouts
        self.main_layout = QHBoxLayout(self)
        self.left_layout = QVBoxLayout()
        
        self.coordinates_box = SimplePositionWidget(self.main_window, self.model, self.controller)
        self.coordinates_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.left_layout.addWidget(self.coordinates_box)

        self.mid_layout = QVBoxLayout()
        self.right_layout = QVBoxLayout()
        self.shortcut_box = ShortcutTableWidget(self, self.shortcut_manager)
        self.shortcut_box.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        self.shortcut_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        self.right_layout.addWidget(self.shortcut_box)

        self.bottom_layout = QHBoxLayout()
        self.steps_layout = QVBoxLayout()
        self.instructions_label = QLabel(f"Move to the {self.steps[0]} position and confirm the location.", self)
        self.next_button = QPushButton("Confirm Position", self)
        self.next_button.clicked.connect(self.next_step)
        self.back_button = QPushButton("Back", self)
        self.back_button.clicked.connect(self.previous_step)
        self.back_button.setEnabled(False)  # Initially disable the back button
        self.submit_button = QPushButton("Submit", self)
        self.submit_button.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        self.submit_button.clicked.connect(self.submit_calibration)
        self.submit_button.setEnabled(False)

        # Create step indicators
        self.step_labels = []
        for step in self.steps:
            label = QLabel(step, self)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("padding: 5px; border: 1px solid black;")
            self.steps_layout.addWidget(label)
            self.step_labels.append(label)
        
        self.bottom_layout.addLayout(self.steps_layout)

        # Vertical layout for buttons
        self.button_layout = QVBoxLayout()
        self.button_layout.addWidget(self.next_button)
        self.button_layout.addWidget(self.back_button)
        self.button_layout.addWidget(self.submit_button)
        self.bottom_layout.addLayout(self.button_layout)

        # Visual Aid (Graphics View for the illustration)
        self.visual_aid_view = QGraphicsView(self)
        self.visual_aid_scene = QGraphicsScene(self)
        self.visual_aid_view.setScene(self.visual_aid_scene)
        self.update_visual_aid()  # Update the visual aid for the initial step

        # Add widgets to the main layout
        self.mid_layout.addWidget(self.instructions_label)
        self.mid_layout.addWidget(self.visual_aid_view)  # Add the visual aid to the main layout
        self.mid_layout.addLayout(self.bottom_layout)

        self.main_layout.addLayout(self.left_layout)
        self.main_layout.addLayout(self.mid_layout)
        self.main_layout.addLayout(self.right_layout)
        
        # Update the UI to reflect the initial state
        self.update_step_labels()

        self.move_to_initial_position()

    def setup_shortcuts(self):
        """Set up keyboard shortcuts using the shortcut manager."""
        self.shortcut_manager.add_shortcut('Left', 'Move left', lambda: self.controller.set_relative_coordinates(0, -self.model.machine_model.step_size, 0, manual=True,override=True))
        self.shortcut_manager.add_shortcut('Right', 'Move right', lambda: self.controller.set_relative_coordinates(0, self.model.machine_model.step_size, 0, manual=True,override=True))
        self.shortcut_manager.add_shortcut('Up', 'Move forward', lambda: self.controller.set_relative_coordinates(self.model.machine_model.step_size, 0, 0, manual=True,override=True))
        self.shortcut_manager.add_shortcut('Down', 'Move backward', lambda: self.controller.set_relative_coordinates(-self.model.machine_model.step_size, 0, 0, manual=True,override=True))
        self.shortcut_manager.add_shortcut('k', 'Move up', lambda: self.controller.set_relative_coordinates(0, 0, -self.model.machine_model.step_size, manual=True,override=True))
        self.shortcut_manager.add_shortcut('m', 'Move down', lambda: self.controller.set_relative_coordinates(0, 0, self.model.machine_model.step_size, manual=True,override=True))
        self.shortcut_manager.add_shortcut('Ctrl+Up', 'Increase step size', self.model.machine_model.increase_step_size)
        self.shortcut_manager.add_shortcut('Ctrl+Down', 'Decrease step size', self.model.machine_model.decrease_step_size)

    def update_step_labels(self):
        for i, label in enumerate(self.step_labels):
            if i < self.current_step:
                label.setStyleSheet(f"background-color: {self.color_dict['dark_blue']}; color: white; padding: 5px; border: 1px solid black;")
            elif i == self.current_step:
                label.setStyleSheet(f"background-color: {self.color_dict['dark_red']}; color: white; padding: 5px; border: 1px solid black;")
            else:
                label.setStyleSheet(f"background-color: {self.color_dict['dark_gray']}; color: white; padding: 5px; border: 1px solid black;")

    def apply_offset(self, coords):
        """Apply the calculated offset to the given coordinates."""
        return {
            axis: coords[axis] + self.offsets[axis] for axis in ['X', 'Y', 'Z'] 
        }
    
    def move_to_initial_position(self):
        """Move the machine to the initial calibration position for the current step, if available."""
        step_name = self.steps[self.current_step]
        converted_step_name = self.name_dict[step_name]
        starting_coordinates = self.get_calibration_by_name(converted_step_name)
        temp_coordinates = self.get_temp_calibration_by_name(converted_step_name)

        if temp_coordinates:
            target_coordinates = temp_coordinates.copy()
            #print(f"Moved to temporary position for {step_name}: {temp_coordinates}")
        elif starting_coordinates:
            #print(f'Starting coords: {starting_coordinates}')
            avg_offset = self.calculate_average_offset()
            adjusted_coordinates = {
                axis: int(starting_coordinates[axis]) + int(avg_offset[axis]) for axis in ['X', 'Y', 'Z']
            }
            target_coordinates = adjusted_coordinates.copy()
            #print(f"Offset: {avg_offset}")
            #print(f"Moved to initial position for {step_name}: {adjusted_coordinates}")
        else:
            target_coordinates = None

        if target_coordinates is None:
            #print(f"No initial calibration data for {step_name}.")
            return
        else:
            intermediate_coords = self.apply_offset(target_coordinates)
            self.controller.set_absolute_coordinates(*self.convert_dict_coords(intermediate_coords),override=True)
            self.controller.set_absolute_coordinates(*self.convert_dict_coords(target_coordinates),override=True)

    def move_to_offset_position(self):
        """Move the machine to the offset position from the current position."""
        current_position = self.model.machine_model.get_current_position_dict_capital().copy()
        offset_position = self.apply_offset(current_position)
        self.controller.set_absolute_coordinates(*self.convert_dict_coords(offset_position),override=True)

    def next_step(self):
        # Check if the machine has completed all commands in the queue
        if self.model.machine_model.is_busy():
            self.main_window.popup_message("Machine Busy", "The machine is currently executing a command. Please wait for it to complete.")
            return

        if self.current_step < len(self.steps):
            # Save the current position as the calibration for this step
            current_position = self.model.machine_model.get_current_position_dict_capital()
            step_name = self.steps[self.current_step]
            converted_step_name = self.name_dict[step_name]
            self.set_calibration_position(converted_step_name, current_position)

            #print(f"Calibrating {self.steps[self.current_step]} position...")
            #print(f'Applying offset: {self.offsets}')
            self.move_to_offset_position()
            # Move to the next step
            self.current_step += 1

            # Update instructions and step labels
            if self.current_step < len(self.steps):
                self.instructions_label.setText(f"Move to the {self.steps[self.current_step]} position and confirm the location.")
                self.move_to_initial_position()
            else:
                self.instructions_label.setText("Calibration complete.")
                self.next_button.setEnabled(False)  # Disable the button when done
                self.submit_button.setEnabled(True)
                self.submit_button.setStyleSheet(f"background-color: {self.color_dict['dark_blue']}; color: white;")
            self.back_button.setEnabled(True)  # Enable the back button when not at the first step
            
            self.update_step_labels()
            self.update_visual_aid()  # Update the visual aid

    def previous_step(self):
        if self.current_step > 0:
            self.current_step -= 1

            # Update instructions and step labels
            self.instructions_label.setText(f"Move to the {self.steps[self.current_step]} position and confirm the location.")
            self.move_to_initial_position()
            self.next_button.setEnabled(True)  # Enable the next button if we're going back
            if self.current_step == 0:
                self.back_button.setEnabled(False)  # Disable the back button when at the first step
            
            self.update_step_labels()
            self.update_visual_aid()  # Update the visual aid

    def submit_calibration(self):
        """Submit the calibration data and close the dialog."""
        print("Submitting calibration data...")
        self.accept()

    def closeEvent(self, event):
        """Handle the window close event."""
        reply = QMessageBox.question(
            self,
            "Incomplete Calibration",
            "The calibration process is not complete. Are you sure you want to exit? All unsaved calibration data will be lost.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.discard_temp_calibrations()  # Discard temporary data
            event.accept()  # Close the dialog
        else:
            event.ignore()  # Keep the dialog open

    def calculate_average_offset(self):
        """Calculate the average offset based on saved temporary calibration positions."""
        offsets = {'X': 0, 'Y': 0, 'Z': 0}
        count = 0

        for step in self.steps:
            converted_step_name = self.name_dict[step]
            initial_coords = self.get_calibration_by_name(converted_step_name)
            temp_coords = self.get_temp_calibration_by_name(converted_step_name)

            if temp_coords and initial_coords:
                for axis in offsets.keys():
                    offsets[axis] += temp_coords[axis] - initial_coords[axis]
                count += 1

        if count > 0:
            for axis in offsets.keys():
                offsets[axis] /= count

        return offsets

    def convert_dict_coords(self, coords):
        return coords['X'], coords['Y'], coords['Z']

    # Methods that should be implemented in the subclass
    def get_initial_calibrations(self):
        raise NotImplementedError

    def get_calibration_by_name(self, name):
        raise NotImplementedError

    def get_temp_calibration_by_name(self, name):
        raise NotImplementedError

    def set_calibration_position(self, name, position):
        raise NotImplementedError

    def discard_temp_calibrations(self):
        raise NotImplementedError

    def update_visual_aid(self):
        raise NotImplementedError

class PlateCalibrationDialog(BaseCalibrationDialog):
    def __init__(self, main_window, model, controller):
        steps = ["Top-Left", "Top-Right", "Bottom-Right", "Bottom-Left"]
        name_dict = {
            "Top-Left": "top_left",
            "Top-Right": "top_right",
            "Bottom-Right": "bottom_right",
            "Bottom-Left": "bottom_left"
        }
        offsets = {
            'X': 0,
            'Y': 0,
            'Z': -500
        }
        super().__init__(main_window, model, controller, "Well Plate Calibration", steps, name_dict,offsets)

    def get_initial_calibrations(self):
        return self.model.well_plate.get_all_current_plate_calibrations()

    def get_calibration_by_name(self, name):
        return self.model.well_plate.get_calibration_by_name(name)

    def get_temp_calibration_by_name(self, name):
        return self.model.well_plate.get_temp_calibration_by_name(name)

    def set_calibration_position(self, name, position):
        self.model.well_plate.set_calibration_position(name, position)

    def discard_temp_calibrations(self):
        self.model.well_plate.discard_temp_calibrations()

    def update_visual_aid(self):
        """Update the visual aid based on the current step."""
        # Clear the scene
        self.visual_aid_scene.clear()

        # Draw the outline of the well plate
        height = 250
        width = 400
        padding = 50
        offset_x = 100
        offset_y = 50
        well_plate_outline = QGraphicsRectItem(offset_x, offset_y, width, height)
        well_plate_outline.setPen(QPen(Qt.darkGray, 2))
        self.visual_aid_scene.addItem(well_plate_outline)

        # Define the positions of the wells on the well plate
        # Adjusted to center the wells based on their radius
        well_radius = 15  # Radius of the well (half of the diameter)
        well_position = {
            "Top-Left": (offset_x + padding - well_radius, offset_y + padding - well_radius),
            "Top-Right": (offset_x + width - padding - well_radius, offset_y + padding - well_radius),
            "Bottom-Right": (offset_x + width - padding - well_radius, offset_y + height - padding - well_radius),
            "Bottom-Left": (offset_x + padding - well_radius, offset_y + height - padding - well_radius)
        }

        # Draw all four wells as circles
        for i, step in enumerate(self.steps):
            pos = well_position[step]
            if i < self.current_step:
                pen = QPen(QColor(self.color_dict['dark_blue']), 2)
                brush = QBrush(Qt.NoBrush)
            elif i == self.current_step:
                pen = QPen(QColor(self.color_dict['dark_red']), 4)
                brush = QBrush(Qt.NoBrush)
            else:
                pen = QPen(QColor(self.color_dict['dark_gray']), 2)
                brush = QBrush(Qt.NoBrush)

            self.visual_aid_scene.addEllipse(pos[0], pos[1], well_radius * 2, well_radius * 2, pen=pen, brush=brush)

class RackCalibrationDialog(BaseCalibrationDialog):
    def __init__(self, main_window, model, controller):
        steps = ["Left","Right"]
        name_dict = {
            "Left": "rack_position_Left",
            "Right": "rack_position_Right"
        }
        offsets = {
            'X': 2500,
            'Y': 0,
            'Z': 0
        }
        super().__init__(main_window, model, controller, "Rack Calibration", steps, name_dict,offsets)

    def get_initial_calibrations(self):
        return self.model.rack_model.get_all_current_rack_calibrations()

    def get_calibration_by_name(self, name):
        return self.model.rack_model.get_calibration_by_name(name)

    def get_temp_calibration_by_name(self, name):
        return self.model.rack_model.get_temp_calibration_by_name(name)

    def set_calibration_position(self, name, position):
        self.model.rack_model.set_calibration_position(name, position)

    def discard_temp_calibrations(self):
        self.model.rack_model.discard_temp_calibrations()

    def update_visual_aid(self):
        """Update the visual aid for the rack position calibration."""
        # Clear the scene
        self.visual_aid_scene.clear()

        # Draw the outline of the rack
        height = 150  # Adjusted for rack dimensions
        width = 400
        padding = 50
        offset_x = 100
        offset_y = 100  # Adjusted vertical positioning
        rack_outline = QGraphicsRectItem(offset_x, offset_y, width, height)
        rack_outline.setPen(QPen(Qt.darkGray, 2))
        self.visual_aid_scene.addItem(rack_outline)

        # Define the positions of the left and right points on the rack
        well_radius = 20  # Radius of the position marker
        position_coordinates = {
            "Left": (offset_x + padding - well_radius, offset_y + height / 2 - well_radius),
            "Right": (offset_x + width - padding - well_radius, offset_y + height / 2 - well_radius)
        }

        # Draw the left and right positions as circles
        for i, step in enumerate(self.steps):
            pos = position_coordinates[step]
            if i < self.current_step:
                pen = QPen(QColor(self.color_dict['dark_blue']), 2)
                brush = QBrush(Qt.NoBrush)
            elif i == self.current_step:
                pen = QPen(QColor(self.color_dict['dark_red']), 4)
                brush = QBrush(Qt.NoBrush)
            else:
                pen = QPen(QColor(self.color_dict['dark_gray']), 2)
                brush = QBrush(Qt.NoBrush)

            self.visual_aid_scene.addEllipse(pos[0], pos[1], well_radius * 2, well_radius * 2, pen=pen, brush=brush)


class MovementBox(QtWidgets.QGroupBox):
    """
    A widget to display the movement of the machine in 2D (XY) and 1D (Z).

    The 2D plot shows the XY movement, and the 1D plot shows the Z movement over time.
    """

    def __init__(self, main_window,model, controller):
        super().__init__("Movement")
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.controller = controller

        self.init_ui()

        self.x_min = -15000
        self.x_max = 0
        self.y_min = 0
        self.y_max = 10000
        self.z_min = -35000
        self.z_max = 0

        # Connect the model's state_updated signal to the update_plots method
        self.model.machine_state_updated.connect(self.update_machine_position)

    def init_ui(self):
        """Initialize the user interface."""
        self.layout = QtWidgets.QHBoxLayout(self)

        self.x_min = 0
        self.x_max = 15000
        self.y_min = 0
        self.y_max = 10000
        self.z_min = 0
        self.z_max = 35000

        # Create a chart, a chart view and a line series for X and Y coordinates
        self.xy_chart = QtCharts.QChart()
        self.xy_chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.xy_chart.setBackgroundBrush(QtGui.QBrush(self.color_dict['dark_gray']))  # Set the background color to grey
        self.xy_chart_view = QtCharts.QChartView(self.xy_chart)
        self.xy_series = QtCharts.QLineSeries()
        self.xy_position_series = QtCharts.QScatterSeries()

        # Add the series to the XY chart
        self.xy_chart.addSeries(self.xy_series)
        self.xy_chart.addSeries(self.xy_position_series)

        # Create a chart, a chart view and a line series for Z coordinate
        self.z_chart = QtCharts.QChart()
        self.z_chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.z_chart.setBackgroundBrush(QtGui.QBrush(self.color_dict['dark_gray']))  # Set the background color to grey
        self.z_chart_view = QtCharts.QChartView(self.z_chart)
        self.z_series = QtCharts.QLineSeries()
        self.z_position_series = QtCharts.QScatterSeries()

        # Add the series to the Z chart
        self.z_chart.addSeries(self.z_series)
        self.z_chart.addSeries(self.z_position_series)

        # Set the chart views to render using OpenGL (for better performance)
        self.xy_chart_view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.z_chart_view.setRenderHint(QtGui.QPainter.Antialiasing)

        # Prevent the chart views from taking focus
        self.xy_chart_view.setFocusPolicy(QtCore.Qt.NoFocus)
        self.z_chart_view.setFocusPolicy(QtCore.Qt.NoFocus)

        self.xy_chart.legend().hide()  # Hide the legend
        self.z_chart.legend().hide()  # Hide the legend


        # Add the chart views to the layout
        self.layout.addWidget(self.xy_chart_view,3)
        self.layout.addWidget(self.z_chart_view,1)

        # Set the layout for the widget
        self.setLayout(self.layout)

        # Create axes, add them to the charts and attach them to the series
        self.xy_chart.createDefaultAxes()
        self.xy_chart.axisY().setRange(self.x_min, self.x_max)
        self.xy_chart.axisY().setLabelFormat("%d")  # Set label format to integer
        self.xy_chart.axisX().setRange(self.y_min, self.y_max)
        self.xy_chart.axisX().setLabelFormat("%d")  # Set label format to integer

        self.z_chart.createDefaultAxes()
        self.z_chart.axisX().setRange(-1, 1)
        self.z_chart.axisX().setLabelsVisible(False)
        self.z_chart.axisX().setTickCount(3)
        self.z_chart.axisY().setRange(-self.z_max, -self.z_min)
        self.z_chart.axisY().setLabelFormat("%d")  # Set label format to integer
        self.z_chart.axisY().setTickCount(1)

    def plot_movements(self):
        # Clear the series
        self.xy_series.clear()
        self.z_series.clear()

        # Get the target coordinates from the machine
        target_coordinates = self.model.machine_model.get_target_coordinates()

        # Add the coordinates to the series
        for coord in target_coordinates:
            self.xy_series.append(coord[0], coord[1])
            self.z_series.append(-coord[2], 0)

    def update_machine_position(self):
        # Clear the position series
        self.xy_position_series.clear()
        self.z_position_series.clear()

        # Get the current position from the machine
        x_pos = self.model.machine_model.current_x
        y_pos = self.model.machine_model.current_y
        z_pos = self.model.machine_model.current_z

        # Add the current position to the position series
        self.xy_position_series.append(y_pos, x_pos)
        self.z_position_series.append(0,-z_pos)

class ClickableLabel(QLabel):
    doubleClicked = QtCore.Signal()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

class VolumeDialog(QDialog):
    def __init__(self, initial_volume, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Volume")
        self.setModal(True)
        self.color_dict = parent.color_dict
        # Define the size of the window
        self.setFixedSize(200, 100)

        # Layout and SpinBox for volume input
        layout = QVBoxLayout(self)
        self.volume_spinbox = QDoubleSpinBox()
        self.volume_spinbox.setDecimals(2)
        self.volume_spinbox.setRange(0.0, 1000.0)  # Set range according to your requirements
        if initial_volume:
            self.volume_spinbox.setValue(initial_volume)
        else:
            self.volume_spinbox.setValue(0.0)

        # Set spinbox color to dark gray
        self.volume_spinbox.setStyleSheet(f"background-color: {self.color_dict['black']};")
        layout.addWidget(self.volume_spinbox)

        # Save button
        save_button = QPushButton("Update volume")
        save_button.clicked.connect(self.accept)  # Close dialog with accept state
        layout.addWidget(save_button)

    def get_volume(self):
        return self.volume_spinbox.value()

class RackBox(QGroupBox):
    """
    A widget to display the reagent rack and the gripper.

    Each slot can contain 0 or 1 printer head. The reagent loaded in the printer head is displayed as a label, and the color of the slot changes to match the printer head color.
    - There is a button below the label to confirm the correct printer head is loaded.
    - There is a button to load the printer head into the gripper of the machine.
    - If the gripper is loaded, the button will unload the gripper to the empty slot.
    - The gripper section shows the printer head currently held by the gripper.
    """
    popup_message_signal = QtCore.Signal(str,str)
    def __init__(self,main_window, model, controller):
        super().__init__("RACK")
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.rack_model = model.rack_model
        self.controller = controller
        self.init_ui()
        self.current_volume = 0

        # Connect model signals to the update methods
        self.rack_model.slot_updated.connect(self.update_all_slots)
        self.rack_model.gripper_updated.connect(self.update_gripper)
        self.model.machine_model.machine_state_updated.connect(self.update_button_states)
        self.model.machine_model.gripper_state_changed.connect(self.update_gripper_state)
        self.model.experiment_loaded.connect(self.update_all_slots)
        self.controller.array_complete.connect(self.update_all_slots)
        self.controller.update_slots_signal.connect(self.update_all_slots)
        self.popup_message_signal.connect(self.main_window.popup_message)

        self.update_button_states(self.model.machine_model.is_connected())

    def init_ui(self):
        """Initialize the user interface."""
        main_layout = QHBoxLayout(self)
        self.setLayout(main_layout)

        # Gripper section
        gripper_widget = QWidget()
        gripper_layout = QVBoxLayout(gripper_widget)
        self.gripper_label = QLabel("Gripper Empty")
        self.gripper_label.setAlignment(Qt.AlignCenter)
        self.gripper_label.setMinimumWidth(100)

        gripper_layout.addWidget(self.gripper_label)

        # Add a clickable label to show the volume of the printer head in the gripper
        self.gripper_volume_label = ClickableLabel("---")
        self.gripper_volume_label.setToolTip("Double click to change the volume")
        self.gripper_volume_label.doubleClicked.connect(self.create_volume_dialog_callback(-1))
        self.gripper_volume_label.setAlignment(Qt.AlignCenter)
        self.gripper_volume_label.setStyleSheet(f"background-color: {self.color_dict['darker_gray']}; color: white;")
        self.gripper_volume_label.setMaximumHeight(20)
        gripper_layout.addWidget(self.gripper_volume_label)

        self.gripper_state = QLabel("Closed")
        self.gripper_state.setAlignment(Qt.AlignCenter)
        self.gripper_state.setStyleSheet(f"background-color: {self.color_dict['darker_gray']}; color: white;")
        self.gripper_state.setMaximumHeight(20)
        gripper_layout.addWidget(self.gripper_state)

        # Add a button to trigger the rack calibration
        calibrate_button = QPushButton("Calibrate Rack")
        calibrate_button.clicked.connect(self.open_rack_calibration_dialog)
        gripper_layout.addWidget(calibrate_button)

         # Add a spacer to separate slots and gripper visually
        spacer = QSpacerItem(20, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)

        self.slot_widgets = []

        # Create UI for each slot in the rack
        slots_layout = QHBoxLayout()
        for slot in self.rack_model.slots:
            slot_widget = QGroupBox(f'Slot {slot.number+1}')
            slot_layout = QVBoxLayout(slot_widget)
            slot_label = QLabel("Empty")
            slot_label.setAlignment(Qt.AlignCenter)

            volume_label = ClickableLabel(f"---")
            volume_label.setToolTip(f"Double click to change the volume")
            volume_label.doubleClicked.connect(self.create_volume_dialog_callback(slot.number))
            volume_label.setAlignment(Qt.AlignCenter)
            volume_label.setStyleSheet(f"background-color: {self.color_dict['darker_gray']}; color: white;")
            volume_label.setMaximumHeight(20)
            
            combined_button = QPushButton("Confirm")
            combined_button.clicked.connect(self.create_combined_button_callback(slot.number))

            swap_combobox = QComboBox()
            swap_combobox.addItem("Swap")
            swap_combobox.currentIndexChanged.connect(self.create_swap_callback(slot.number, swap_combobox))

            slot_layout.addWidget(slot_label)
            slot_layout.addWidget(volume_label)
            slot_layout.addWidget(combined_button)
            slot_layout.addWidget(swap_combobox)

            slots_layout.addWidget(slot_widget)
            # self.slot_widgets.append((slot_label, confirm_button, load_button, swap_combobox))
            self.slot_widgets.append((slot_label, volume_label, combined_button, swap_combobox))

         # Add a spacer to separate slots and table visually
        spacer_right = QSpacerItem(20, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)

        # Table for unassigned printer heads
        self.unassigned_table = QTableWidget()
        self.unassigned_table.setColumnCount(1)
        self.unassigned_table.setHorizontalHeaderLabels(["Stock"])
        self.unassigned_table.verticalHeader().setVisible(False)  # Hide the index column
        self.unassigned_table.setMinimumWidth(100)
        self.unassigned_table.setFocusPolicy(Qt.NoFocus)  # Remove focus from the table
        self.unassigned_table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # Disable editing
        self.unassigned_table.setSelectionMode(QAbstractItemView.NoSelection)  # Disable selection
        
        # Add slots, spacer, and gripper to the main layout
        main_layout.addWidget(gripper_widget)
        main_layout.addItem(spacer)
        main_layout.addLayout(slots_layout)
        main_layout.addItem(spacer_right)
        main_layout.addWidget(self.unassigned_table)

        # Initial population of unassigned printer heads
        self.update_unassigned_printer_heads()
        self.update_all_slots()
    
    def open_rack_calibration_dialog(self):
        """Open the rack calibration dialog."""
        importlib.reload(CalibrationClasses.View)
        importlib.reload(CalibrationClasses)

        rack_fix_dialog = CalibrationClasses.RackCalibrationFixDialog(self.main_window,self.model,self.controller)
        rack_fix_dialog.exec()


        # if not self.model.machine_model.motors_are_enabled() or not self.model.machine_model.motors_are_homed():
        #     self.main_window.popup_message("Motors Not Enabled or Homed","Please enable and home the motors before calibrating the well plate.")
        #     return
        # if self.model.rack_model.get_gripper_printer_head() != None:
        #     print("Gripper is loaded")
        #     if not self.model.rack_model.get_gripper_printer_head().is_calibration_chip():
        #         self.main_window.popup_message("Calibration Chip Required","Please load the calibration chip into the gripper before calibrating the rack.")
        #         return
        #     else:
        #         print("Calibration chip is loaded")
        # else:
        #     print("Gripper is empty")
        #     self.main_window.popup_message("Gripper Empty","Please load the calibration chip into the gripper before calibrating the rack.")
        #     return
        # rack_calibration_dialog = RackCalibrationDialog(self.main_window,self.model,self.controller)
        
        # # Execute the dialog and check if the user completes the calibration
        # if rack_calibration_dialog.exec() == QDialog.Accepted:
        #     print("Calibration completed successfully.")
        #     self.model.rack_model.update_calibration_data()
        # else:
        #     print("Calibration was canceled or failed.")
        #     self.model.rack_model.discard_temp_calibrations()
        #     # self.model.well_plate.discard_temp_calibrations()

    def update_button_states(self, machine_connected):
        """Update the button states based on the machine connection state."""
        for _, _, combined_button, _ in self.slot_widgets:
            combined_button.setEnabled(machine_connected)

    def open_volume_dialog(self,volume):
        # Open the VolumeDialog with the current volume
        dialog = VolumeDialog(volume, self)
        if dialog.exec_():  # Check if the dialog was accepted
            # Update volume and label text after user saves
            new_volume = dialog.get_volume()
            return new_volume
    

    def create_volume_dialog_callback(self, slot_number):
        """Create a callback function that access the printer head loaded at the specified slot and passes the current volume of the 
        of the printer head to the volume dialogue."""
        def volume_dialog_callback():
            if slot_number == -1:
                if self.rack_model.gripper_printer_head:
                    current_printer_head = self.rack_model.gripper_printer_head
            else:
                slot = self.rack_model.slots[slot_number]
                current_printer_head = slot.printer_head
            if current_printer_head:
                current_volume = current_printer_head.get_current_volume()
                new_volume = self.open_volume_dialog(current_volume)
                if new_volume is not None:
                    current_printer_head.set_absolute_volume(new_volume)
                    self.update_all_slots()
        return volume_dialog_callback
        

    def create_combined_button_callback(self, slot_number):
        """Create a callback function for the combined Confirm/Load/Unload button."""
        def combined_button_action():
            if not self.model.machine_model.motors_are_enabled():
                self.popup_message_signal.emit("Motors Not Enabled","Please enable and home the motors before picking up printer heads")
                return
            elif not self.model.machine_model.motors_are_homed():
                self.popup_message_signal.emit("Motors Not Homed","Please home the motors before picking up printer heads")
                return
            slot = self.rack_model.slots[slot_number]
            if not slot.confirmed:
                # Confirm the slot
                self.controller.confirm_slot(slot_number)
            elif slot.locked:
                # Unload the printer head
                self.controller.drop_off_printer_head(slot_number,manual=True)
            else:
                # Load the printer head
                self.controller.pick_up_printer_head(slot_number,manual=True)
            self.update_all_slots()
        return combined_button_action
    
    def create_dropdown_change_callback(self, slot_number):
        """Create a callback function for handling dropdown changes."""
        return lambda: self.on_dropdown_change(slot_number)
    
    def on_dropdown_change(self, slot_number):
        """Handle changes in the dropdown menu."""
        dropdown = self.slot_widgets[slot_number][2]
        selected_text = dropdown.currentText()
        if selected_text:
            other_slot_number = self.find_slot_by_printer_head_text(selected_text)
            if other_slot_number is not None:
                self.controller.swap_printer_heads_between_slots(slot_number, other_slot_number)

    
    def create_swap_callback(self, slot_number, combobox):
        """Create a callback function for swapping a slot."""
        def swap_printer_head():
            selected_text = combobox.currentText()
            if selected_text != "Swap":
                printer_head_manager = self.model.printer_head_manager
                # Check if the selected printer head is unassigned
                for printer_head in printer_head_manager.get_unassigned_printer_heads():
                    if selected_text == printer_head.get_display_stock_name():
                        self.controller.swap_printer_head(slot_number, printer_head)
                        self.update_all_slots()  # Update all dropdowns after swapping
                        self.update_unassigned_printer_heads()  # Update the table to reflect the change
                        return

                # Check if the selected printer head is in another slot
                for i, slot in enumerate(self.rack_model.slots):
                    if i != slot_number and slot.printer_head:
                        slot_text = f"Slot {i+1}: {slot.printer_head.get_display_stock_name()}"
                        if selected_text == slot_text:
                            self.controller.swap_printer_heads_between_slots(slot_number, i)
                            self.update_all_slots()  # Update all dropdowns after swapping
                            self.update_unassigned_printer_heads()  # Update the table to reflect the change
                            return
        return swap_printer_head
    
    def update_all_slots(self, *_args):
        """Update all slots in the rack."""
        for slot_number in range(len(self.rack_model.slots)):
            self.update_slot(slot_number)

        self.update_gripper()
        self.update_unassigned_printer_heads()

    def update_slot(self, slot_number):
        """Update the UI for a specific slot."""
        slot = self.rack_model.slots[slot_number]
        label, volume_label, combined_button, swap_combobox = self.slot_widgets[slot_number]

        if slot.printer_head:
            printer_head = slot.printer_head
            if not printer_head.is_calibration_chip():
                complete = printer_head.check_complete(self.model.well_plate)
            else:
                complete = False
            label.setText(printer_head.get_display_stock_name(new_line=True))
            color = QtGui.QColor(printer_head.color)
            color.setAlphaF(0.7)
            rgba_color = f"rgba({color.red()},{color.green()},{color.blue()},{color.alpha()})"
            if complete:
                border_color = 'white'
                label.setStyleSheet(f"background-color: {rgba_color}; border: 2px solid {border_color}; color: white;")
            else:
                label.setStyleSheet(f"background-color: {rgba_color}; color: white;")

            # print(f'slot: {slot_number} locked: {slot.locked} confirmed: {slot.confirmed}')
            if slot.confirmed and not slot.locked:
                combined_button.setText("Load")
                combined_button.setStyleSheet(f"background-color: {self.color_dict['dark_blue']}; color: white;")
            elif slot.locked:
                combined_button.setText("Unload")
                combined_button.setStyleSheet(f"background-color: {self.color_dict['dark_red']}; color: white;")
            else:
                combined_button.setText("Confirm")
                combined_button.setStyleSheet(f"background-color: {self.color_dict['dark_gray']}; color: white;")
        else:
            label.setText("Empty")
            label.setStyleSheet(f"background-color: {self.color_dict['dark_gray']}; color: white;")
            if slot.locked:
                combined_button.setText("Unload")
                combined_button.setStyleSheet(f"background-color: {self.color_dict['dark_red']}; color: white;")
            else:
                combined_button.setText("Confirm")
                combined_button.setStyleSheet(f"background-color: {self.color_dict['dark_gray']}; color: white;")

        # Update dropdown options
        self.update_dropdown(slot_number, swap_combobox)
        swap_combobox.setEnabled(not slot.is_locked())

        # Update the volume label
        if slot.printer_head:
            volume = slot.printer_head.get_current_volume()
            if volume is None:
                volume_label.setText("---")
            else:
                volume_label.setText(f"{round(volume,2)} uL")
        else:
            volume_label.setText("---")
        
        # Update the button's functionality
        combined_button.clicked.disconnect()
        combined_button.clicked.connect(self.create_combined_button_callback(slot_number))

    def update_dropdown(self, slot_number, dropdown):
        """
        Update the dropdown for a specific slot with all available printer heads.
        """
        dropdown.blockSignals(True)
        dropdown.clear()
        dropdown.addItem("Swap")

        # Add all unassigned printer heads
        for printer_head in self.model.printer_head_manager.get_unassigned_printer_heads():
            dropdown.addItem(printer_head.get_display_stock_name())

        # Add all printer heads in other slots
        for i, slot in enumerate(self.rack_model.get_all_slots()):
            if i != slot_number and slot.printer_head:
                dropdown.addItem(f"Slot {i+1}: {slot.printer_head.get_display_stock_name()}")
        
        dropdown.blockSignals(False)

    def update_gripper(self):
        """Update the UI when the gripper state changes."""
        if self.rack_model.gripper_printer_head:
            printer_head = self.rack_model.gripper_printer_head
            self.gripper_label.setText(printer_head.get_display_stock_name(new_line=True))
            self.gripper_label.setStyleSheet(f"background-color: {printer_head.color}; color: white;")
            volume = printer_head.get_current_volume()
            if volume is None:
                self.gripper_volume_label.setText("---")
            else:
                self.gripper_volume_label.setText(f"{round(volume,2)} uL")
        else:
            self.gripper_volume_label.setText("---")
            self.gripper_label.setText("Gripper Empty")
            self.gripper_label.setStyleSheet("background-color: none; color: white;")

    def update_unassigned_printer_heads(self):
        """Update the table with unassigned printer heads."""
        unassigned_printer_heads = self.model.printer_head_manager.get_unassigned_printer_heads()
        self.unassigned_table.setRowCount(len(unassigned_printer_heads))

        for row, printer_head in enumerate(unassigned_printer_heads):
            if not printer_head.is_calibration_chip():
                complete = printer_head.check_complete(self.model.well_plate)
            else:
                complete = True
            color = printer_head.get_color()
            color = QtGui.QColor(color)
            color.setAlphaF(0.5)

            text_name = printer_head.get_display_stock_name()
            if printer_head.is_calibration_chip():
                text_name = f"Calibration"
            reagent_item = QTableWidgetItem(text_name)
            reagent_item.setTextAlignment(Qt.AlignCenter)
            if complete:
                font_color = self.color_dict['light_gray']
                font = reagent_item.font()
                font.setBold(False)  # Make the text bold
                reagent_item.setFont(font)  # Set the font
            else:
                font_color = self.color_dict['white']
                font = reagent_item.font()
                font.setBold(True)  # Make the text bold
                reagent_item.setFont(font)  # Set the font
            reagent_item.setForeground(QtGui.QBrush(QtGui.QColor(font_color)))  # Set the text color
            reagent_item.setBackground(QtGui.QBrush(QtGui.QColor(color)))

            self.unassigned_table.setItem(row, 0, reagent_item)
    
    def toggle_load(self, slot_number):
        """Toggle loading/unloading between the slot and gripper."""
        slot = self.rack_model.slots[slot_number]
        if slot.printer_head is None and self.rack_model.gripper_printer_head:
            self.controller.drop_off_printer_head(slot_number)
        elif slot.printer_head and self.rack_model.gripper_printer_head is None:
            self.controller.pick_up_printer_head(slot_number)

    def update_gripper_state(self, gripper_state):
        """Update the gripper state label."""
        if gripper_state == True:
            self.gripper_state.setText("Open")
            self.gripper_state.setStyleSheet(f"background-color: {self.color_dict['dark_red']}; color: white;")
        else:
            self.gripper_state.setText("Closed")
            self.gripper_state.setStyleSheet(f"background-color: {self.color_dict['darker_gray']}; color: white;")


class BoardStatusBox(QGroupBox):
    '''
    A widget to display the status of the machine board.
    Displays a grid with the label of the variable from the board and the value of the variable.
    Includes the cycle count and max cycle time for the board.
    '''
    def __init__(self, main_window, model, controller):
        super().__init__('STATUS')
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.controller = controller
        
        prof = getattr(self.main_window, "profile", None)
        self.legacy_mode = prof.name == "legacy" if prof else True

        self.init_ui()

        # Connect model signals to the update methods
        self.model.machine_state_updated.connect(self.update_status)
        self.model.location_model.locations_updated.connect(self.update_status)
        self.model.machine_model.machine_paused.connect(self.update_status)
        self.model.machine_model.home_status_signal.connect(self.update_status)
        if self.legacy_mode:
            self.model.calibration_model.mass_updated_signal.connect(self.update_status)
    
    def init_ui(self):
        """Initialize the user interface."""
        self.layout = QtWidgets.QGridLayout(self)

        self.labels = {
            'Homed': QLabel('False'),
            'Paused': QLabel('False'),
            'Location': QLabel('Unknown'),
            'Cycle Count': QLabel('0'),
            'Current Micros': QLabel('0'),
            # 'Mass': QLabel('0'),
            # 'Stable': QLabel('False')
        }
        if hasattr(self.model, "droplet_camera_model"):
            self.labels['Flash Session'] = QLabel('Disarmed')
            self.labels['Flash Fault'] = QLabel('None')
        if self.legacy_mode:
            self.labels['Mass'] = QLabel('0')
            self.labels['Stable'] = QLabel('False')

        row = 0
        for label, value in self.labels.items():
            label_label = QLabel(label)
            label_label.setAlignment(Qt.AlignCenter)
            value.setAlignment(Qt.AlignCenter)
            self.layout.addWidget(label_label, row, 0)
            self.layout.addWidget(value, row, 1)
            row += 1
        
        self.setLayout(self.layout)

    def update_status(self):
        """Update the labels with the current board status."""
        self.labels['Location'].setText(self.model.machine_model.current_location)
        self.labels['Homed'].setText(str(self.model.machine_model.motors_homed))
        self.labels['Paused'].setText(str(self.model.machine_model.paused))
        self.labels['Cycle Count'].setText(str(self.model.machine_model.cycle_count))
        self.labels['Current Micros'].setText(str(self.model.machine_model.current_micros))
        cam = getattr(self.model, "droplet_camera_model", None)
        if cam is not None and 'Flash Session' in self.labels:
            armed_getter = getattr(cam, "get_flash_session_armed", None)
            fault_getter = getattr(cam, "get_flash_fault_latched", None)
            reason_getter = getattr(cam, "get_flash_fault_reason_display", None)
            armed = bool(armed_getter()) if callable(armed_getter) else bool(getattr(cam, "flash_session_armed", False))
            fault_latched = bool(fault_getter()) if callable(fault_getter) else bool(getattr(cam, "flash_fault_latched", False))
            if callable(reason_getter):
                reason_text = str(reason_getter())
            else:
                reason_text = str(getattr(cam, "flash_fault_reason", "") or "None")
            self.labels['Flash Session'].setText('Armed' if armed else 'Disarmed')
            self.labels['Flash Fault'].setText(reason_text if fault_latched else 'None')

        if self.legacy_mode:
            self.labels['Mass'].setText(str(self.model.calibration_model.get_current_mass()))
            self.labels['Stable'].setText(str(self.model.calibration_model.is_mass_stable()))

class ExperimentTaskListWidget(QGroupBox):
    """Read-only experiment workflow guide for global readiness and per-head tasks."""

    REFRESH_DEBOUNCE_MS = 500
    STATE_LABELS = {
        "done": "Done",
        "current": "Current",
        "waiting": "Waiting",
        "blocked": "Blocked",
        "optional": "Optional",
        "in_progress": "In progress",
        "stopping": "Stopping",
    }
    STATE_COLORS = {
        "done": "#2f855a",
        "current": "#2b6cb0",
        "waiting": "#666666",
        "blocked": "#9b2c2c",
        "optional": "#805ad5",
        "in_progress": "#2b6cb0",
        "stopping": "#996515",
    }

    def __init__(self, main_window, model, controller):
        super().__init__("EXPERIMENT GUIDE")
        self.main_window = main_window
        self.model = model
        self.controller = controller
        self.color_dict = getattr(main_window, "color_dict", {}) or {}
        self._sections = {}
        self._manual_section_states = {}
        self._connected_signals = []
        self._last_experiment_identity = None
        self._last_render_signature = None
        self._last_calibration_summary_signature = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(self.REFRESH_DEBOUNCE_MS)
        self._refresh_timer.timeout.connect(self.refresh)
        self._init_ui()
        self._connect_refresh_signals()
        self.refresh()
        self._last_calibration_summary_signature = self._calibration_summary_signature()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.next_label = QLabel("Next: Load or create an experiment")
        self.next_label.setWordWrap(True)
        self.next_label.setStyleSheet("color: white; font-weight: bold;")
        layout.addWidget(self.next_label)

        self.blocking_label = QLabel("")
        self.blocking_label.setWordWrap(True)
        self.blocking_label.setStyleSheet(f"color: {self.color_dict.get('light_gray', '#cccccc')};")
        layout.addWidget(self.blocking_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setFocusPolicy(Qt.NoFocus)
        self.scroll_widget = QWidget()
        self.sections_layout = QVBoxLayout(self.scroll_widget)
        self.sections_layout.setContentsMargins(0, 0, 0, 0)
        self.sections_layout.setSpacing(6)
        self.sections_layout.addStretch(1)
        self.scroll_area.setWidget(self.scroll_widget)
        layout.addWidget(self.scroll_area, stretch=1)

    def _safe_connect(self, signal, callback):
        connector = getattr(signal, "connect", None)
        if not callable(connector):
            return
        try:
            connector(callback)
            self._connected_signals.append(signal)
        except Exception:
            pass

    def _connect_refresh_signals(self):
        self._safe_connect(getattr(self.model, "experiment_loaded", None), self._on_experiment_loaded)
        rack = getattr(self.model, "rack_model", None)
        well_plate = getattr(self.model, "well_plate", None)
        machine_model = getattr(self.model, "machine_model", None)
        calibration_manager = getattr(self.model, "calibration_manager", None)
        experiment_model = getattr(self.model, "experiment_model", None)

        self._safe_connect(getattr(rack, "gripper_updated", None), self.request_refresh)
        self._safe_connect(getattr(rack, "slot_updated", None), self.request_refresh)
        self._safe_connect(getattr(well_plate, "well_state_changed_signal", None), self.request_refresh)
        self._safe_connect(getattr(well_plate, "clear_all_wells_signal", None), self.request_refresh)
        self._safe_connect(getattr(well_plate, "plate_format_changed_signal", None), self.request_refresh)
        self._safe_connect(getattr(machine_model, "machine_state_updated", None), self.request_refresh)
        self._safe_connect(getattr(machine_model, "home_status_signal", None), self.request_refresh)
        self._safe_connect(getattr(machine_model, "regulation_state_changed", None), self.request_refresh)
        self._safe_connect(getattr(self.controller, "array_state_changed", None), self.request_refresh)
        self._safe_connect(getattr(self.controller, "array_complete", None), self.request_refresh)
        self._safe_connect(
            getattr(calibration_manager, "characterizationSummaryUpdated", None),
            self._on_calibration_summary_updated,
        )
        self._safe_connect(getattr(experiment_model, "applied_imaging_calibration_changed", None), self.request_refresh)

    def _on_experiment_loaded(self, *_args):
        self._manual_section_states.clear()
        self._last_render_signature = None
        self._last_calibration_summary_signature = None
        self.refresh()
        self._last_calibration_summary_signature = self._calibration_summary_signature()

    def request_refresh(self, *_args):
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _on_calibration_summary_updated(self, *_args):
        signature = self._calibration_summary_signature()
        if signature == self._last_calibration_summary_signature:
            return
        self._last_calibration_summary_signature = signature
        self.request_refresh()

    @staticmethod
    def _call_bool(obj, name, default=False):
        fn = getattr(obj, name, None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:
                return bool(default)
        return bool(getattr(obj, name, default))

    @staticmethod
    def _call_value(obj, name, default=None, *args, **kwargs):
        fn = getattr(obj, name, None)
        if callable(fn):
            try:
                return fn(*args, **kwargs)
            except Exception:
                return default
        return getattr(obj, name, default)

    def _experiment_identity(self):
        em = getattr(self.model, "experiment_model", None)
        for attr in ("experiment_file_path", "experiment_dir_path"):
            value = getattr(em, attr, None)
            if value:
                return str(value)
        return id(em)

    def _all_wells(self):
        well_plate = getattr(self.model, "well_plate", None)
        getter = getattr(well_plate, "get_all_wells", None)
        if callable(getter):
            try:
                return list(getter() or [])
            except Exception:
                return []
        return list(getattr(well_plate, "wells", []) or [])

    def _well_assigned_reaction(self, well):
        return getattr(well, "assigned_reaction", getattr(well, "assigned_reaction", None))

    def _experiment_ready(self):
        reaction_collection = getattr(self.model, "reaction_collection", None)
        is_empty = getattr(reaction_collection, "is_empty", None)
        if callable(is_empty):
            try:
                if bool(is_empty()):
                    return False
            except Exception:
                pass

        return any(self._well_assigned_reaction(well) is not None for well in self._all_wells())

    def _queue_idle(self):
        checker = getattr(self.controller, "check_if_all_completed", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return True

    def _global_tasks(self):
        machine_model = getattr(self.model, "machine_model", None)
        well_plate = getattr(self.model, "well_plate", None)
        return [
            {
                "key": "experiment",
                "label": "Experiment loaded",
                "done": self._experiment_ready(),
                "next": "Load or create an experiment",
                "blocking": "Open Experiment Editor and generate a print array.",
            },
            {
                "key": "connected",
                "label": "Machine connected",
                "done": self._call_bool(machine_model, "is_connected", False),
                "next": "Connect to the machine",
                "blocking": "Use the connection controls before preparing the run.",
            },
            {
                "key": "motors_enabled",
                "label": "Motors enabled",
                "done": self._call_bool(machine_model, "motors_are_enabled", False),
                "next": "Enable motors",
                "blocking": "Motors must be enabled before head handling or printing.",
            },
            {
                "key": "motors_homed",
                "label": "Motors homed",
                "done": self._call_bool(machine_model, "motors_are_homed", False),
                "next": "Home motors",
                "blocking": "Home the motors before moving to rack, camera, or plate positions.",
            },
            {
                "key": "pressure",
                "label": "Pressure regulation running",
                "done": bool(getattr(machine_model, "regulating_print_pressure", False)),
                "next": "Start pressure regulation",
                "blocking": "Pressure regulation is required before calibration or array printing.",
            },
            {
                "key": "plate_calibration",
                "label": "Plate calibration applied",
                "done": self._call_bool(well_plate, "check_calibration_applied", False),
                "next": "Apply plate calibration",
                "blocking": "Calibrate the plate before starting a print array.",
            },
        ]

    def _first_incomplete_global_task(self):
        for task in self._global_tasks():
            if not task["done"]:
                return task
        return None

    def _active_head(self):
        rack = getattr(self.model, "rack_model", None)
        getter = getattr(rack, "get_gripper_printer_head", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
        return getattr(rack, "gripper_printer_head", None)

    def _head_stock_id(self, head):
        value = self._call_value(head, "get_stock_id", None)
        if value is not None:
            return str(value)
        stock = getattr(head, "stock_solution", None)
        value = self._call_value(stock, "get_stock_id", None)
        return None if value is None else str(value)

    def _head_key(self, head):
        stock_id = self._head_stock_id(head)
        if stock_id:
            return stock_id
        return str(id(head))

    def _is_calibration_chip(self, head):
        return self._call_bool(head, "is_calibration_chip", False)

    def _discover_heads(self):
        heads = []
        manager = getattr(self.model, "printer_head_manager", None)
        heads.extend(list(getattr(manager, "printer_heads", []) or []))

        active = self._active_head()
        if active is not None:
            heads.append(active)

        rack = getattr(self.model, "rack_model", None)
        for slot in list(getattr(rack, "slots", []) or []):
            head = getattr(slot, "printer_head", None)
            if head is not None:
                heads.append(head)

        getter = getattr(manager, "get_unassigned_printer_heads", None)
        if callable(getter):
            try:
                heads.extend(list(getter() or []))
            except Exception:
                pass

        deduped = []
        seen = set()
        for head in heads:
            if head is None or self._is_calibration_chip(head):
                continue
            key = self._head_key(head)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(head)
        return deduped

    def _display_head_name(self, head):
        for args in ((False,), tuple()):
            fn = getattr(head, "get_display_stock_name", None)
            if callable(fn):
                try:
                    value = fn(*args)
                    if value:
                        return str(value).replace("\n", " ")
                except Exception:
                    pass
        stock_id = self._head_stock_id(head)
        if stock_id:
            stock_manager = getattr(self.model, "stock_solutions", None)
            formatter = getattr(stock_manager, "get_formatted_from_stock_id", None)
            if callable(formatter):
                try:
                    return str(formatter(stock_id))
                except Exception:
                    pass
            return stock_id
        return "Printer head"

    def _applied_calibration_record(self, head):
        em = getattr(self.model, "experiment_model", None)
        getter = getattr(em, "get_applied_imaging_calibration", None)
        if callable(getter):
            try:
                record = getter(printer_head=head)
                return record if isinstance(record, dict) else None
            except Exception:
                return None
        return None

    def _head_calibrated(self, head):
        return (
            self._call_bool(head, "check_calibration_complete", False)
            or self._applied_calibration_record(head) is not None
            or self._head_has_calibration_summary_row(head)
        )

    def _calibration_summary_rows(self):
        calibration_manager = getattr(self.model, "calibration_manager", None)
        getter = getattr(calibration_manager, "get_characterization_summary_rows", None)
        if not callable(getter):
            return []
        try:
            return list(getter() or [])
        except Exception:
            return []

    @staticmethod
    def _summary_value(row, key):
        if isinstance(row, dict):
            return row.get(key)
        return getattr(row, key, None)

    def _calibration_summary_row_signature(self, row):
        keys = (
            "run_id",
            "source_run_id",
            "source_phase_key",
            "source_step_index",
            "source_pressure_index",
            "phase",
            "pw_us",
            "pressure_psi",
            "delay_us",
            "printing_mode",
            "valid",
        )
        return tuple(str(self._summary_value(row, key)) for key in keys)

    def _calibration_summary_signature(self):
        return tuple(
            self._calibration_summary_row_signature(row)
            for row in self._calibration_summary_rows()
        )

    def _head_has_calibration_summary_row(self, head):
        rows = self._calibration_summary_rows()
        if not rows:
            return False

        head_stock_id = self._head_stock_id(head)
        head_name = self._display_head_name(head)
        active = self._active_head()
        is_active = active is head or (
            active is not None and self._head_key(active) == self._head_key(head)
        )

        for row in rows:
            valid = self._summary_value(row, "valid")
            if valid is False:
                continue

            row_tokens = [
                self._summary_value(row, key)
                for key in (
                    "stock_id",
                    "stock_solution",
                    "reagent_id",
                    "reagent_name",
                    "stock_name",
                    "stock_label",
                )
            ]
            normalized_tokens = {str(token) for token in row_tokens if token is not None}
            if head_stock_id and head_stock_id in normalized_tokens:
                return True
            if head_name and head_name in normalized_tokens:
                return True
            if not normalized_tokens and is_active:
                return True
        return False

    def _reaction_target_for_stock(self, reaction, stock_id):
        getter = getattr(reaction, "get_target_droplets_for_stock", None)
        if callable(getter):
            try:
                value = getter(stock_id)
                return int(value or 0)
            except Exception:
                return 0
        reagents = getattr(reaction, "reagents", None)
        reagent = reagents.get(stock_id) if isinstance(reagents, dict) else None
        return int(getattr(reagent, "target_droplets", 0) or 0)

    def _well_remaining_for_stock(self, well, stock_id):
        getter = getattr(well, "get_remaining_droplets", None)
        if callable(getter):
            try:
                return int(getter(stock_id) or 0)
            except Exception:
                pass
        reaction = self._well_assigned_reaction(well)
        getter = getattr(reaction, "get_remaining_droplets_for_stock", None)
        if callable(getter):
            try:
                return int(getter(stock_id) or 0)
            except Exception:
                return 0
        target = self._reaction_target_for_stock(reaction, stock_id)
        added = 0
        reagents = getattr(reaction, "reagents", None)
        reagent = reagents.get(stock_id) if isinstance(reagents, dict) else None
        if reagent is not None:
            added = int(getattr(reagent, "added_droplets", 0) or 0)
        return max(0, target - added)

    def _head_print_progress(self, head):
        stock_id = self._head_stock_id(head)
        total = 0
        printed = 0
        remaining_droplets = 0
        if not stock_id:
            return {"stock_id": stock_id, "total_wells": 0, "printed_wells": 0, "remaining_droplets": 0}

        for well in self._all_wells():
            reaction = self._well_assigned_reaction(well)
            if reaction is None:
                continue
            target = self._reaction_target_for_stock(reaction, stock_id)
            if target <= 0:
                continue
            total += 1
            remaining = self._well_remaining_for_stock(well, stock_id)
            remaining_droplets += remaining
            if remaining <= 0:
                printed += 1

        return {
            "stock_id": stock_id,
            "total_wells": total,
            "printed_wells": printed,
            "remaining_droplets": remaining_droplets,
        }

    def _preflight_blocking_message(self):
        getter = getattr(self.controller, "get_print_array_imaging_calibration_preflight", None)
        if not callable(getter):
            return ""
        try:
            result = getter() or {}
        except Exception:
            return ""
        if bool(result.get("ok", True)):
            return ""
        return str(result.get("message") or "")

    def _head_context(self, head):
        active = self._active_head()
        is_active = active is head or (
            active is not None and self._head_key(active) == self._head_key(head)
        )
        applied = self._applied_calibration_record(head) is not None
        calibrated = self._head_calibrated(head)
        progress = self._head_print_progress(head)
        has_work = progress["total_wells"] > 0
        printed = has_work and progress["remaining_droplets"] <= 0
        dropped_off = printed and not is_active
        load_done = is_active or dropped_off
        queue_idle = self._queue_idle()
        array_state_getter = getattr(self.controller, "get_array_run_state", None)
        array_state = array_state_getter() if callable(array_state_getter) else "idle"

        tasks = []
        tasks.append({"key": "load", "label": "Load printer head", "done": load_done, "blocking": ""})
        tasks.append({
            "key": "calibrate",
            "label": "Calibrate printer head",
            "done": calibrated,
            "blocking": "" if is_active else "Load this printer head before calibrating.",
        })
        tasks.append({
            "key": "apply",
            "label": "Apply calibration to experiment",
            "done": applied,
            "blocking": "" if calibrated else "Complete or select a calibration result first.",
        })
        tasks.append({
            "key": "print",
            "label": "Print array",
            "done": printed,
            "blocking": "",
        })
        tasks.append({
            "key": "recheck",
            "label": "Bookend recheck",
            "done": False,
            "optional": True,
            "blocking": "Optional until this workflow has persisted recheck tracking.",
        })
        tasks.append({
            "key": "dropoff",
            "label": "Drop off printer head",
            "done": dropped_off,
            "blocking": "" if printed else "Print this head's assigned wells first.",
        })

        if is_active and applied:
            preflight_message = self._preflight_blocking_message()
        else:
            preflight_message = ""

        for task in tasks:
            task["state"] = "done" if task.get("done") else "waiting"

        current = None
        if dropped_off:
            current = None
        elif not is_active:
            current = tasks[0]
        elif not calibrated:
            current = tasks[1]
        elif not applied:
            current = tasks[2]
        elif has_work and not printed:
            current = tasks[3]
        elif printed and is_active:
            current = tasks[5]

        if current is not None:
            current["state"] = "current"

        if current is tasks[0] and not queue_idle:
            current["state"] = "blocked"
            current["blocking"] = "The command queue must finish before loading this printer head."
        elif current is tasks[5] and not queue_idle:
            current["state"] = "blocked"
            current["blocking"] = "The command queue must finish before dropping off this printer head."

        if current is tasks[3]:
            if array_state == "running":
                current["state"] = "in_progress"
                current["blocking"] = "Array printing is in progress."
            elif array_state == "stop_requested":
                current["state"] = "stopping"
                current["blocking"] = "The array will stop after the current well."
            elif not queue_idle:
                current["state"] = "blocked"
                current["blocking"] = "The command queue must finish before printing."
            elif preflight_message:
                current["state"] = "blocked"
                current["blocking"] = preflight_message
        elif current is tasks[1] and not is_active:
            current["state"] = "blocked"
        elif current is tasks[2] and not calibrated:
            current["state"] = "blocked"
        elif current is tasks[5] and not printed:
            current["state"] = "blocked"

        tasks[4]["state"] = "optional"

        done_count = sum(1 for task in tasks if task.get("done") and not task.get("optional"))
        total_count = sum(1 for task in tasks if not task.get("optional"))
        return {
            "head": head,
            "key": self._head_key(head),
            "name": self._display_head_name(head),
            "is_active": is_active,
            "applied": applied,
            "calibrated": calibrated,
            "printed": printed,
            "progress": progress,
            "tasks": tasks,
            "current_task": current,
            "done_count": done_count,
            "total_count": total_count,
        }

    def _choose_next(self, head_contexts):
        global_task = self._first_incomplete_global_task()
        if global_task is not None:
            return f"Next: {global_task['next']}", global_task.get("blocking", "")

        for context in head_contexts:
            if context["is_active"] and context["current_task"] is not None:
                task = context["current_task"]
                if task.get("key") == "print" and task.get("state") == "in_progress":
                    return f"Next: Printing array for {context['name']}", task.get("blocking", "")
                if task.get("key") == "print" and task.get("state") == "stopping":
                    return f"Next: Stopping after current well for {context['name']}", task.get("blocking", "")
                return f"Next: {task['label']} for {context['name']}", task.get("blocking", "")

        for context in head_contexts:
            if context["current_task"] is not None:
                task = context["current_task"]
                return f"Next: {task['label']} for {context['name']}", task.get("blocking", "")

        if head_contexts:
            return "Next: Experiment complete", ""
        return "Next: Add printer heads to the experiment", "Create or load an experiment with reagent assignments."

    def _row_style(self, state):
        color = self.STATE_COLORS.get(state, "#666666")
        if state in {"current", "in_progress", "stopping"}:
            return f"color: white; background-color: {color}; padding: 2px 4px; border-radius: 2px;"
        if state == "blocked":
            return f"color: white; background-color: {color}; padding: 2px 4px; border-radius: 2px;"
        return f"color: {color};"

    def _style_color(self, name, fallback):
        value = str(self.color_dict.get(name) or fallback)
        return value if QtGui.QColor(value).isValid() else fallback

    def _make_task_row(self, task):
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        line = QWidget()
        line_layout = QHBoxLayout(line)
        line_layout.setContentsMargins(0, 0, 0, 0)
        line_layout.setSpacing(6)
        label = QLabel(str(task.get("label", "")))
        label.setWordWrap(True)
        label.setStyleSheet("color: white;")
        state = str(task.get("state") or ("done" if task.get("done") else "waiting"))
        state_label = QLabel(self.STATE_LABELS.get(state, state.title()))
        state_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        state_label.setStyleSheet(self._row_style(state))
        line_layout.addWidget(label, stretch=1)
        line_layout.addWidget(state_label)
        layout.addWidget(line)

        blocking = str(task.get("blocking") or "")
        if blocking and state in {"blocked", "current", "optional"}:
            detail = QLabel(blocking)
            detail.setWordWrap(True)
            detail.setStyleSheet(f"color: {self.color_dict.get('light_gray', '#cccccc')}; font-size: 10px;")
            layout.addWidget(detail)
        return row

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _make_section(self, key, title, expanded=False):
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        button = QtWidgets.QToolButton()
        button.setText(title)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        button.setCheckable(True)
        button.setChecked(bool(expanded))
        header_bg = self._style_color("dark_gray", "#444444")
        button.setStyleSheet(
            f"color: #ffffff; background-color: {header_bg}; "
            "border: none; padding: 5px; font-weight: bold;"
        )
        outer.addWidget(button)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 4, 4, 6)
        body_layout.setSpacing(4)
        body.setVisible(bool(expanded))
        outer.addWidget(body)

        def _toggle(checked):
            body.setVisible(bool(checked))
            button.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
            self._manual_section_states[key] = bool(checked)

        button.toggled.connect(_toggle)
        return {"container": container, "button": button, "body": body, "layout": body_layout}

    def _section_expanded(self, key, default=False):
        if key in self._manual_section_states:
            return bool(self._manual_section_states[key])
        return bool(default)

    def _add_section(self, key, title, rows, expanded=False):
        section = self._make_section(key, title, expanded=expanded)
        for row in rows:
            section["layout"].addWidget(row)
        insert_index = max(0, self.sections_layout.count() - 1)
        self.sections_layout.insertWidget(insert_index, section["container"])
        self._sections[key] = section
        return section

    def _render_global_section(self):
        rows = []
        first_incomplete = self._first_incomplete_global_task()
        current_key = None if first_incomplete is None else first_incomplete.get("key")
        for task in self._global_tasks():
            state = "done" if task["done"] else ("current" if task.get("key") == current_key else "waiting")
            rows.append(self._make_task_row({"label": task["label"], "state": state, "blocking": task.get("blocking", "")}))
        expanded = self._section_expanded("global", default=first_incomplete is not None)
        self._add_section("global", "Run Readiness", rows, expanded=expanded)

    def _render_head_section(self, context):
        progress = context["progress"]
        printed = progress["printed_wells"]
        total = progress["total_wells"]
        title = (
            f"{context['name']} | {context['done_count']}/{context['total_count']} | "
            f"{printed}/{total} wells"
        )
        if context["is_active"]:
            title += " | Loaded"
        elif context["current_task"] is None:
            title += " | Complete"
        section_key = f"head:{context['key']}"
        rows = [self._make_task_row(task) for task in context["tasks"]]
        expanded = True if context["is_active"] else self._section_expanded(section_key, default=False)
        self._add_section(section_key, title, rows, expanded=expanded)

    def _render_signature(self, head_contexts, next_text, blocking_text):
        global_signature = tuple(
            (str(task.get("key")), bool(task.get("done")))
            for task in self._global_tasks()
        )
        head_signature = []
        for context in head_contexts:
            progress = context["progress"]
            task_signature = tuple(
                (
                    str(task.get("key")),
                    str(task.get("state")),
                    bool(task.get("done")),
                    str(task.get("blocking") or ""),
                )
                for task in context["tasks"]
            )
            head_signature.append(
                (
                    str(context["key"]),
                    str(context["name"]),
                    bool(context["is_active"]),
                    int(context["done_count"]),
                    int(context["total_count"]),
                    str(progress.get("stock_id")),
                    int(progress.get("total_wells", 0)),
                    int(progress.get("printed_wells", 0)),
                    int(progress.get("remaining_droplets", 0)),
                    task_signature,
                )
            )
        return (
            str(next_text),
            str(blocking_text),
            global_signature,
            tuple(head_signature),
            bool(head_contexts),
        )

    def _active_section_needs_expand(self, head_contexts):
        for context in head_contexts:
            if not context["is_active"]:
                continue
            section = self._sections.get(f"head:{context['key']}")
            button = section.get("button") if isinstance(section, dict) else None
            if button is not None and not button.isChecked():
                return True
        return False

    def refresh(self, *_args):
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()

        current_identity = self._experiment_identity()
        if self._last_experiment_identity is None:
            self._last_experiment_identity = current_identity
        elif current_identity != self._last_experiment_identity:
            self._last_experiment_identity = current_identity
            self._manual_section_states.clear()
            self._last_render_signature = None

        head_contexts = [self._head_context(head) for head in self._discover_heads()]
        next_text, blocking_text = self._choose_next(head_contexts)
        render_signature = self._render_signature(head_contexts, next_text, blocking_text)
        if (
            render_signature == self._last_render_signature
            and not self._active_section_needs_expand(head_contexts)
        ):
            return
        self._last_render_signature = render_signature

        self._clear_layout(self.sections_layout)
        self._sections.clear()
        self.sections_layout.addStretch(1)

        self.next_label.setText(next_text)
        self.blocking_label.setText(blocking_text)
        self.blocking_label.setVisible(bool(blocking_text))

        self._render_global_section()
        if head_contexts:
            for context in head_contexts:
                self._render_head_section(context)
        else:
            empty = QLabel("No printer heads found for the current experiment.")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {self.color_dict.get('light_gray', '#cccccc')};")
            self.sections_layout.insertWidget(max(0, self.sections_layout.count() - 1), empty)
        self._last_calibration_summary_signature = self._calibration_summary_signature()

class ShortcutTableWidget(QGroupBox):
    """
    A widget to display all keyboard shortcuts in a table format.

    The table has two columns: one for the key sequence and one for the description.
    """
    def __init__(self, main_window, shortcut_manager):
        super().__init__("SHORTCUTS")
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.shortcut_manager = shortcut_manager

        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)

        # Create the table widget
        self.table = QTableWidget()
        self.table.setColumnCount(2)  # Two columns: Key Sequence, Description
        self.table.setHorizontalHeaderLabels(["Key Sequence", "Description"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)  # Stretch columns to fill the width
        self.table.verticalHeader().setVisible(False)  # Hide row numbers
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # Make cells read-only

        # Add shortcuts to the table
        self.load_shortcuts()

        # Add the table to the layout
        layout.addWidget(self.table)

    def load_shortcuts(self):
        """Load shortcuts from the manager into the table."""
        shortcuts = self.shortcut_manager.get_shortcuts()
        self.table.setRowCount(len(shortcuts))

        for row, (key_sequence, description) in enumerate(shortcuts):
            key_item = QTableWidgetItem(key_sequence)
            description_item = QTableWidgetItem(description)
            key_item.setTextAlignment(Qt.AlignCenter)
            description_item.setTextAlignment(Qt.AlignLeft)

            self.table.setItem(row, 0, key_item)
            self.table.setItem(row, 1, description_item)
        
class CommandQueueWidget(QGroupBox):
    """
    A widget to display the command queue with a scrollable table.

    The table has two columns: one for the command number and one for the command signal.
    The row color changes based on the status of the command:
    - Added: Dark grey
    - Sent: Lighter grey
    - Executing: Red
    - Completed: Black
    """

    def __init__(self,main_window, machine):
        super().__init__("QUEUE")
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.machine = machine
        self.init_ui()

        # Connect the queue_updated signal to the update_commands method
        self.machine.command_queue.queue_updated.connect(self.update_commands)

    def init_ui(self):
        """Initialize the user interface."""
        self.setLayout(QVBoxLayout())

        # Create a table to display the commands
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Command ID", "Command Signal"])
        self.table.horizontalHeader().setStretchLastSection(True)
        # Hide the vertical index column
        self.table.verticalHeader().setVisible(False)

        # Set the table to be read-only
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setSelectionMode(QTableWidget.NoSelection)

        # Add the table to the layout
        self.layout().addWidget(self.table)

        # Initial update to populate the table
        self.update_commands()

    def update_commands(self):
        """Update the table with the current commands in the queue."""
        self.table.setRowCount(0)  # Clear the table

        # Get the commands from both the active queue and the completed queue
        completed = list(self.machine.command_queue.completed)
        if len(completed) > 10:
            completed = completed[-10:]
        in_queue = list(self.machine.command_queue.queue)
        if len(in_queue) > 50:
            in_queue = in_queue[:50]
        all_commands = in_queue + completed
        
        # Sort commands by command number in descending order
        all_commands.sort(key=lambda cmd: cmd.get_number(), reverse=True)

        for command in all_commands:
            row_position = self.table.rowCount()
            self.table.insertRow(row_position)

            # Add the command number and signal to the table
            command_num_label = QTableWidgetItem(str(command.get_number()))
            command_num_label.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_position, 0, command_num_label)
            self.table.setItem(row_position, 1, QTableWidgetItem(command.get_command()))

            # Set the row color based on the command status
            if command.status == "Added":
                self.set_row_color(row_position, self._queue_color("darker_gray", "dark_gray", default="#2c2c2c"))
            elif command.status == "Sent":
                self.set_row_color(row_position, self._queue_color("mid_gray", "light_gray", default="#6e6e6e"))
            elif command.status == "Accepted":
                self.set_row_color(row_position, self._queue_color("dark_gray", "mid_gray", default="#4d4d4d"))
            elif command.status == "Executing":
                self.set_row_color(row_position, self._queue_color("dark_red", default="#8a0303"))
            elif command.status == "Completed":
                self.set_row_color(row_position, self._queue_color("darker_gray", "dark_gray", default="#2c2c2c"))
            elif command.status == "Canceled":
                self.set_row_color(row_position, self._queue_color("mid_red", "dark_red", default="#8a0303"))

    def _queue_color(self, *names, default):
        for name in names:
            color = self.color_dict.get(name)
            if color:
                return color
        return default

    def set_row_color(self, row, color):
        """Set the background color for a row."""
        for column in range(self.table.columnCount()):
            self.table.item(row, column).setBackground(QtGui.QColor(color))
        

class _NoElideTableItemDelegate(QtWidgets.QStyledItemDelegate):
    """Render table cells without replacing visible text with ellipses."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideNone


class _BusyUiContext:
    """Show an indeterminate busy dialog while synchronous UI work runs."""

    def __init__(
        self,
        parent,
        message: str,
        *,
        widgets: Sequence[Any] | None = None,
        status_setter=None,
        failure_message: str | None = None,
    ):
        self.parent = parent
        self.message = str(message or "Working...")
        self.widgets = [widget for widget in (widgets or []) if widget is not None]
        self.status_setter = status_setter
        self.failure_message = failure_message
        self._enabled_states: list[tuple[Any, bool]] = []
        self._dialog = None

    def __enter__(self):
        for widget in self.widgets:
            try:
                self._enabled_states.append((widget, bool(widget.isEnabled())))
                widget.setEnabled(False)
            except Exception:
                pass

        if callable(self.status_setter):
            self.status_setter(self.message)

        app = QApplication.instance()
        if app is not None:
            try:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            except Exception:
                pass

        try:
            self._dialog = QtWidgets.QProgressDialog(self.message, "", 0, 0, self.parent)
            self._dialog.setWindowTitle("Please wait")
            self._dialog.setCancelButton(None)
            self._dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self._dialog.setMinimumDuration(0)
            self._dialog.setAutoClose(False)
            self._dialog.setAutoReset(False)
            self._dialog.setRange(0, 0)
            self._dialog.show()
            self._dialog.raise_()
            self._dialog.activateWindow()
            self._dialog.repaint()
        except Exception:
            self._dialog = None

        if app is not None:
            try:
                QApplication.sendPostedEvents(None, QtCore.QEvent.Type.Paint)
                app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
                app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
            except Exception:
                pass
        return self

    def __exit__(self, exc_type, _exc, _tb):
        if self._dialog is not None:
            try:
                self._dialog.close()
                self._dialog.deleteLater()
            except Exception:
                pass
            self._dialog = None

        try:
            QApplication.restoreOverrideCursor()
        except Exception:
            pass

        for widget, enabled in self._enabled_states:
            try:
                widget.setEnabled(enabled)
            except Exception:
                pass
        self._enabled_states.clear()

        if exc_type is not None and callable(self.status_setter) and self.failure_message:
            self.status_setter(self.failure_message)

        app = QApplication.instance()
        if app is not None:
            try:
                app.processEvents()
            except Exception:
                pass
        return False


class ExperimentImportWizard(QDialog):
    """Preflight uploaded reaction designs before applying them to the editor."""

    COMPOSITION_FIRST_REAGENT_COL = 3
    COMPOSITION_TRAILING_COLS = 3
    COMPOSITION_REAGENT_COL_WIDTH = 118
    COMPOSITION_HEADER_HEIGHT = 58
    COMPOSITION_ROW_HEIGHT = 46

    STOCK_COL_REAGENT = 0
    STOCK_COL_UNITS = 1
    STOCK_COL_MODE = 2
    STOCK_COL_DROPLET = 3
    STOCK_COL_MAX = 4
    STOCK_COL_IDEAL = 5
    STOCK_COL_DELTA = 6
    STOCK_COL_MIN = 7
    STOCK_COL_MAX_TARGET = 8
    STOCK_COL_SPAN = 9
    STOCK_COL_SMALLEST = 10
    STOCK_COL_WORST_VOL = 11
    STOCK_COL_STEP = 12
    STOCK_COL_STATUS = 13

    def __init__(
        self,
        model: ExperimentModel,
        parent=None,
        *,
        printed_volume_nL: float = 500.0,
        printed_volume_tolerance_nL: float = 50.0,
        final_volume_nL: float = 500.0,
        allow_two: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("Import Experiment Design")
        self.setMinimumSize(1280, 760)

        self.model = model
        self.design_df: pd.DataFrame | None = None
        self.max_stock_df: pd.DataFrame | None = None
        self.design_path: str | None = None
        self.max_stock_path: str | None = None
        self.report: Dict[str, Any] | None = None
        self._manual_max_stock_by_reagent: Dict[str, float] = {}
        self._populating_tables = False
        self._report_dirty = False
        self._has_calculated_report = False
        self._pending_change_message = ""

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        right = QVBoxLayout()
        root.addLayout(left, stretch=1)
        root.addLayout(right, stretch=3)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.design_path_lbl = QLabel("No design CSV loaded")
        self.design_path_lbl.setWordWrap(True)
        self.max_stock_path_lbl = QLabel("No max stock CSV loaded")
        self.max_stock_path_lbl.setWordWrap(True)

        self.load_design_btn = QPushButton("Upload Target Concentrations CSV...")
        self.load_design_btn.clicked.connect(self._on_load_design_clicked)
        left.addWidget(self.load_design_btn)
        left.addWidget(self.design_path_lbl)

        self.load_stock_btn = QPushButton("Upload Max Stock Concentrations CSV...")
        self.load_stock_btn.clicked.connect(self._on_load_max_stock_clicked)
        left.addWidget(self.load_stock_btn)
        left.addWidget(self.max_stock_path_lbl)

        self.printed_volume_spin = QDoubleSpinBox()
        self.printed_volume_spin.setDecimals(1)
        self.printed_volume_spin.setRange(1.0, 1_000_000.0)
        self.printed_volume_spin.setSingleStep(50.0)
        self.printed_volume_spin.setValue(float(printed_volume_nL))
        self.printed_volume_spin.editingFinished.connect(
            lambda: self._mark_report_dirty("Printed volume changed.")
        )
        form.addRow(QLabel("Printed Volume (nL)"), self.printed_volume_spin)

        self.final_volume_spin = QDoubleSpinBox()
        self.final_volume_spin.setDecimals(1)
        self.final_volume_spin.setRange(1.0, 1_000_000.0)
        self.final_volume_spin.setSingleStep(50.0)
        self.final_volume_spin.setValue(float(final_volume_nL))
        self.final_volume_spin.editingFinished.connect(
            lambda: self._mark_report_dirty("Final reaction volume changed.")
        )
        form.addRow(QLabel("Final Reaction Volume (nL)"), self.final_volume_spin)

        self.printed_volume_tolerance_spin = QDoubleSpinBox()
        self.printed_volume_tolerance_spin.setDecimals(1)
        self.printed_volume_tolerance_spin.setRange(0.0, 1_000_000.0)
        self.printed_volume_tolerance_spin.setSingleStep(10.0)
        self.printed_volume_tolerance_spin.setValue(max(0.0, float(printed_volume_tolerance_nL)))
        self.printed_volume_tolerance_spin.editingFinished.connect(
            lambda: self._mark_report_dirty("Printed volume tolerance changed.")
        )
        form.addRow(QLabel("Printed Volume Tolerance (nL)"), self.printed_volume_tolerance_spin)

        self.allow_two_chk = QCheckBox()
        self.allow_two_chk.setChecked(bool(allow_two))
        self.allow_two_chk.stateChanged.connect(
            lambda _state: self._mark_report_dirty("Two-stock setting changed.")
        )
        form.addRow(QLabel("Allow Two Stock Solutions"), self.allow_two_chk)

        left.addLayout(form)

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status_lbl.setStyleSheet("color:#666; font-style: italic;")
        left.addWidget(self.status_lbl)
        left.addStretch(1)

        self.calculate_btn = QPushButton("Calculate Feasibility")
        self.calculate_btn.clicked.connect(self._recompute_report)
        left.addWidget(self.calculate_btn)

        buttons = QHBoxLayout()
        self.apply_btn = QPushButton("Apply to Experiment Editor")
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.apply_btn)
        left.addLayout(buttons)

        right.addWidget(QLabel("Unique Compositions"))
        self.composition_table = QTableWidget(0, 0, self)
        self.composition_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.composition_table.setWordWrap(True)
        self.composition_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.composition_table.setItemDelegate(_NoElideTableItemDelegate(self.composition_table))
        self.composition_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.composition_table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self.composition_table.horizontalHeader().setFixedHeight(self.COMPOSITION_HEADER_HEIGHT)
        self.composition_table.verticalHeader().setDefaultSectionSize(self.COMPOSITION_ROW_HEIGHT)
        right.addWidget(self.composition_table, stretch=3)

        right.addWidget(QLabel("Stock Concentration Constraints"))
        self.stock_table = QTableWidget(0, 14, self)
        self.stock_table.setHorizontalHeaderLabels([
            "Reagent", "Units", "Print Mode", "Ejection Vol (nL)",
            "Max Stock", "Ideal Stock", "Delta/drop", "Target Min",
            "Target Max", "Span", "Smallest Nonzero", "Worst Vol @ Max",
            "Smallest Step", "Status / Recommendation"
        ])
        self.stock_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.stock_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.stock_table.cellChanged.connect(self._on_stock_cell_changed)
        right.addWidget(self.stock_table, stretch=2)

        self._populate_composition_table(None)
        self._populate_stock_table(None)
        self.status_lbl.setText("Upload a target concentrations CSV to begin.")
        self._update_calculate_button_state()
        self._update_apply_enabled()

    @staticmethod
    def _fmt_value(value, digits: int = 4) -> str:
        if value is None:
            return ""
        try:
            number = float(value)
        except Exception:
            return str(value)
        if not math.isfinite(number):
            return ""
        if abs(number - round(number)) < 1e-9:
            return str(int(round(number)))
        return f"{number:.{digits}f}".rstrip("0").rstrip(".")

    @staticmethod
    def _fmt_whole_nl(value) -> str:
        if value is None:
            return ""
        try:
            number = float(value)
        except Exception:
            return str(value)
        if not math.isfinite(number):
            return ""
        return f"{number:.0f}"

    @staticmethod
    def _fmt_printing_mode(value) -> str:
        mode = normalize_printing_mode(value, fallback=PRINTING_MODE_DROPLET)
        return "Stream" if mode == PRINTING_MODE_STREAM else "Droplet"

    @staticmethod
    def _wrap_header_label(value, max_line_chars: int = 14) -> str:
        text = str(value or "").strip()
        if len(text) <= max_line_chars:
            return text

        prefix = ""
        suffix = ""
        inner = text
        if inner.startswith("[") and inner.endswith("]") and len(inner) > 2:
            prefix = "["
            suffix = "]"
            inner = inner[1:-1].strip()

        normalized = inner.replace("_", " ").replace("-", " ").replace("/", " / ")
        words = [word for word in normalized.split() if word]
        if not words:
            words = [inner]

        lines = []
        current = ""
        for word in words:
            candidate = f"{current} {word}" if current else word
            if len(candidate) <= max_line_chars or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)

        split_lines = []
        for line in lines:
            if len(line) <= max_line_chars:
                split_lines.append(line)
            else:
                split_lines.extend(
                    line[idx:idx + max_line_chars]
                    for idx in range(0, len(line), max_line_chars)
                )

        if prefix and split_lines:
            split_lines[0] = f"{prefix}{split_lines[0]}"
            split_lines[-1] = f"{split_lines[-1]}{suffix}"
        return "\n".join(split_lines)

    @staticmethod
    def _short_path(path: str | None) -> str:
        if not path:
            return ""
        return os.path.basename(str(path)) or str(path)

    def _dirty_calculate_stylesheet(self) -> str:
        color = "#1b3a57"
        parent = self.parent()
        parent_colors = getattr(parent, "color_dict", {}) if parent is not None else {}
        if isinstance(parent_colors, Mapping):
            color = str(parent_colors.get("dark_blue") or color)
        return f"background-color: {color}; color: white;"

    def _report_has_errors(self) -> bool:
        return any(
            issue.get("severity") == "error"
            for issue in (self.report or {}).get("issues", [])
        )

    def _update_calculate_button_state(self):
        has_design = self.design_df is not None
        self.calculate_btn.setEnabled(has_design)
        if has_design and self._report_dirty:
            self.calculate_btn.setStyleSheet(self._dirty_calculate_stylesheet())
        else:
            self.calculate_btn.setStyleSheet("")

    def _update_apply_enabled(self):
        self.apply_btn.setEnabled(
            self.design_df is not None
            and self.report is not None
            and not self._report_dirty
            and not self._report_has_errors()
        )

    def _mark_report_dirty(self, reason: str = "Inputs changed."):
        if self.design_df is None:
            self._report_dirty = False
            self._pending_change_message = ""
            self.status_lbl.setText("Upload a target concentrations CSV to begin.")
            self._update_calculate_button_state()
            self._update_apply_enabled()
            return

        self._report_dirty = True
        self._pending_change_message = str(reason or "Inputs changed.")
        if self._has_calculated_report and self.report is not None:
            self.status_lbl.setText(
                f"Results are stale: {self._pending_change_message} "
                "Press Calculate Feasibility to update."
            )
        else:
            self.status_lbl.setText(
                f"{self._pending_change_message} Press Calculate Feasibility to analyze."
            )
        self._update_calculate_button_state()
        self._update_apply_enabled()

    def _mark_report_clean(self):
        self._report_dirty = False
        self._has_calculated_report = True
        self._pending_change_message = ""
        self._update_calculate_button_state()
        self._update_apply_enabled()

    def _busy_widgets(self) -> list[Any]:
        return [
            self.load_design_btn,
            self.load_stock_btn,
            self.printed_volume_spin,
            self.final_volume_spin,
            self.printed_volume_tolerance_spin,
            self.allow_two_chk,
            self.calculate_btn,
            self.apply_btn,
            self.cancel_btn,
            self.composition_table,
            self.stock_table,
        ]

    def load_design_dataframe(self, df: "pd.DataFrame", *, source_path: str | None = None):
        self.design_df = df.copy()
        self.design_path = source_path
        self.design_path_lbl.setText(self._short_path(source_path) if source_path else "Design CSV loaded")
        self._manual_max_stock_by_reagent.clear()
        self._mark_report_dirty("Target concentrations CSV loaded.")

    def load_max_stock_dataframe(self, df: "pd.DataFrame", *, source_path: str | None = None):
        self.max_stock_df = df.copy()
        self.max_stock_path = source_path
        self.max_stock_path_lbl.setText(self._short_path(source_path) if source_path else "Max stock CSV loaded")
        self._mark_report_dirty("Max stock concentrations CSV loaded.")

    def _on_load_design_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select reaction design CSV",
            "",
            "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            df = pd.read_csv(path)
        except Exception as e:
            QMessageBox.critical(self, "Error loading CSV", f"Could not read file:\n{e}")
            return
        if df.empty:
            QMessageBox.warning(self, "Empty file", "The selected CSV has no data.")
            return
        self.load_design_dataframe(df, source_path=path)

    def _on_load_max_stock_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select max stock concentrations CSV",
            "",
            "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            df = pd.read_csv(path)
        except Exception as e:
            QMessageBox.critical(self, "Error loading CSV", f"Could not read file:\n{e}")
            return
        if df.empty:
            QMessageBox.warning(self, "Empty file", "The selected CSV has no data.")
            return
        self.load_max_stock_dataframe(df, source_path=path)

    def _recompute_report(self):
        if self.design_df is None:
            self.report = None
            self._populate_composition_table(None)
            self._populate_stock_table(None)
            self.status_lbl.setText("Upload a target concentrations CSV to begin.")
            self._report_dirty = False
            self._has_calculated_report = False
            self._update_calculate_button_state()
            self._update_apply_enabled()
            return

        with _BusyUiContext(
            self,
            "Calculating feasibility... this may take a moment on Raspberry Pi.",
            widgets=self._busy_widgets(),
            status_setter=self.status_lbl.setText,
            failure_message="Feasibility calculation failed.",
        ):
            self.report = self.model.build_import_feasibility_report(
                self.design_df,
                max_stock_df=self.max_stock_df,
                max_stock_map=self._manual_max_stock_by_reagent,
                units_default="",
                droplet_nL_default=10.0,
                starting_conc_default=0.0,
                printed_volume_nL=float(self.printed_volume_spin.value()),
                printed_volume_tolerance_nL=float(self.printed_volume_tolerance_spin.value()),
                final_volume_nL=float(self.final_volume_spin.value()),
                allow_two=bool(self.allow_two_chk.isChecked()),
            )
            self._populate_composition_table(self.report)
            self._populate_stock_table(self.report)
        self._update_status()
        self._mark_report_clean()

    def _status_brush(self, status: str) -> QtGui.QBrush | None:
        status = str(status or "")
        if status in {"Volume impossible", "Invalid value", "Stock plan impossible"}:
            return QtGui.QBrush(QtGui.QColor("#8b1e1e"))
        if status in {"Missing max stock", "Unit mismatch", "Resolution warning", "Near budget", "Invalid print mode"}:
            return QtGui.QBrush(QtGui.QColor("#7a5a00"))
        return None

    def _set_row_status_background(self, table: QTableWidget, row: int, status: str):
        brush = self._status_brush(status)
        if brush is None:
            return
        foreground = QtGui.QBrush(QtGui.QColor("#ffffff"))
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item is not None:
                item.setBackground(brush)
                item.setForeground(foreground)

    def _populate_composition_table(self, report: Dict[str, Any] | None):
        self._populating_tables = True
        try:
            self.composition_table.clear()
            if not report:
                self.composition_table.setRowCount(0)
                self.composition_table.setColumnCount(0)
                return

            specs = report.get("reagent_specs", [])
            headers = ["Composition", "Wells", "Count"]
            headers.extend(self._wrap_header_label(spec.get("name", "")) for spec in specs)
            headers.extend(["Total @ Max (nL)", "Remaining (nL)", "Status"])

            rows = report.get("composition_rows", [])
            self.composition_table.setColumnCount(len(headers))
            self.composition_table.setHorizontalHeaderLabels(headers)
            self.composition_table.setRowCount(len(rows))

            for row_idx, row in enumerate(rows):
                values = [
                    row.get("label", ""),
                    ", ".join(row.get("wells", [])[:8]) + ("..." if len(row.get("wells", [])) > 8 else ""),
                    str(row.get("count", "")),
                ]
                for spec in specs:
                    name = spec.get("name")
                    target = row.get("targets", {}).get(name)
                    volume = row.get("reagent_volumes_nL", {}).get(name)
                    text = self._fmt_value(target)
                    if volume is None and target not in (None, 0, 0.0):
                        text = f"{text}\nmissing"
                    elif volume is not None:
                        text = f"{text}\n{self._fmt_value(volume)} nL"
                    values.append(text)
                values.extend([
                    self._fmt_whole_nl(row.get("total_required_volume_nL")),
                    self._fmt_whole_nl(row.get("remaining_printed_volume_nL")),
                    row.get("status", ""),
                ])

                for col_idx, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.composition_table.setItem(row_idx, col_idx, item)
                self._set_row_status_background(self.composition_table, row_idx, row.get("status", ""))

            self._apply_composition_table_layout(len(specs))
        finally:
            self._populating_tables = False

    def _apply_composition_table_layout(self, reagent_count: int):
        self.composition_table.resizeColumnsToContents()
        header = self.composition_table.horizontalHeader()
        header.setFixedHeight(self.COMPOSITION_HEADER_HEIGHT)

        first_reagent = self.COMPOSITION_FIRST_REAGENT_COL
        last_reagent = first_reagent + int(reagent_count)
        for col in range(first_reagent, last_reagent):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.composition_table.setColumnWidth(col, self.COMPOSITION_REAGENT_COL_WIDTH)

        trailing = [
            (0, 110),
            (1, 130),
            (2, 58),
            (last_reagent, 112),
            (last_reagent + 1, 112),
            (last_reagent + 2, 140),
        ]
        for col, width in trailing:
            if col < self.composition_table.columnCount():
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
                self.composition_table.setColumnWidth(col, max(width, self.composition_table.columnWidth(col)))

        for row in range(self.composition_table.rowCount()):
            self.composition_table.setRowHeight(row, self.COMPOSITION_ROW_HEIGHT)

    def _populate_stock_table(self, report: Dict[str, Any] | None):
        self._populating_tables = True
        try:
            rows = list((report or {}).get("stock_rows", []))
            self.stock_table.setRowCount(len(rows))
            for row_idx, row in enumerate(rows):
                values = [
                    row.get("reagent", ""),
                    row.get("units", ""),
                    self._fmt_printing_mode(row.get("printing_mode")),
                    self._fmt_value(row.get("droplet_nL")),
                    self._fmt_value(row.get("max_stock_conc")),
                    self._fmt_value(row.get("ideal_stock_conc")),
                    self._fmt_value(row.get("delta_per_drop")),
                    self._fmt_value(row.get("target_min")),
                    self._fmt_value(row.get("target_max")),
                    self._fmt_value(row.get("target_span")),
                    self._fmt_value(row.get("smallest_nonzero_target")),
                    self._fmt_value(row.get("worst_max_stock_volume_nL")),
                    self._fmt_value(row.get("smallest_useful_target_step")),
                    f"{row.get('status', '')}: {row.get('recommendation', '')}",
                ]
                for col_idx, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if col_idx == self.STOCK_COL_MAX:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        item.setData(Qt.ItemDataRole.UserRole, row.get("reagent", ""))
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.stock_table.setItem(row_idx, col_idx, item)
                self._set_row_status_background(self.stock_table, row_idx, row.get("status", ""))
            self.stock_table.resizeColumnsToContents()
        finally:
            self._populating_tables = False

    def _on_stock_cell_changed(self, row: int, col: int):
        if self._populating_tables or col != self.STOCK_COL_MAX:
            return
        item = self.stock_table.item(row, col)
        if item is None:
            return
        reagent = item.data(Qt.ItemDataRole.UserRole)
        if not reagent and self.stock_table.item(row, self.STOCK_COL_REAGENT) is not None:
            reagent = self.stock_table.item(row, self.STOCK_COL_REAGENT).text()
        if not reagent:
            return
        text = (item.text() or "").strip()
        if not text:
            self._manual_max_stock_by_reagent.pop(str(reagent), None)
            self._mark_report_dirty("Max stock override cleared.")
            return
        try:
            value = float(text)
        except Exception:
            self._mark_report_dirty("Max stock override changed.")
            return
        if value > 0 and math.isfinite(value):
            self._manual_max_stock_by_reagent[str(reagent)] = value
            self._mark_report_dirty("Max stock override changed.")

    def _update_status(self):
        report = self.report or {}
        rows = report.get("composition_rows", [])
        stock_rows = report.get("stock_rows", [])
        status_counts = report.get("status_counts", {})
        parts = [
            f"{len(rows)} unique composition(s)",
            f"{len(stock_rows)} reagent(s)",
        ]
        if status_counts:
            parts.append(", ".join(f"{key}: {value}" for key, value in status_counts.items()))
        if report.get("unmatched_stock_rows"):
            parts.append(f"{len(report['unmatched_stock_rows'])} unmatched stock row(s)")
        issues = report.get("issues", [])
        if issues:
            parts.append(str(issues[0].get("message", "")))
        self.status_lbl.setText(". ".join(part for part in parts if part))

    def _on_apply_clicked(self):
        if self.design_df is None:
            return
        if self._report_dirty or self.report is None:
            self._mark_report_dirty("Calculate feasibility before applying.")
            return
        if self.apply_btn.isEnabled():
            self.accept()

    def get_apply_payload(self) -> Dict[str, Any]:
        report = self.report or {}
        return {
            "design_df": self.design_df.copy() if self.design_df is not None else None,
            "source_path": self.design_path,
            "max_stock_by_reagent": dict(report.get("max_stock_by_reagent", {})),
            "stock_settings_by_reagent": dict(report.get("stock_settings_by_reagent", {})),
            "printed_volume_nL": float(self.printed_volume_spin.value()),
            "printed_volume_tolerance_nL": float(self.printed_volume_tolerance_spin.value()),
            "final_volume_nL": float(self.final_volume_spin.value()),
            "allow_two": bool(self.allow_two_chk.isChecked()),
        }


class ExperimentDesignDialog(QDialog):
    """
    UI for composing reagents (additives and choice groups), optimizing stock solutions,
    and generating the design using ExperimentModelV2.
    """

    GROUP_ADDITIVE = "Additive"
    GROUP_NEW = "New choice group…"

    COL_STOCK_LABEL  = 0
    COL_REAGENT      = 1
    COL_GROUP        = 2
    COL_HEAD_TYPE    = 3
    COL_MODE         = 4
    COL_STARTING     = 5
    COL_TARGETS      = 6
    COL_UNITS        = 7
    COL_SET_STOCK    = 8
    COL_MAX_STOCK    = 9
    COL_DROPLET      = 10
    COL_PRIOR        = 11
    COL_DELETE       = 12

    PROGRESS_POLICY_RESUME = "resume"
    PROGRESS_POLICY_RESET = "reset"
    PROGRESS_POLICY_CANCEL = "cancel"

    def __init__(self, model: ExperimentModel, main_window):
        super().__init__()
        self.main_window = main_window
        self.color_dict = getattr(
            self.main_window, "color_dict",
            {"dark_red": "#8a0303","blue": "#1e64b4","dark_blue": "#1b3a57", "light_blue": "#3b82f6"}
        )
                
        prof = getattr(self.main_window, "profile", None)
        self.legacy_mode = prof.name == "legacy" if prof else True

        self.default_droplet_volume_nL = printing_mode_default_ejection_volume_nl(PRINTING_MODE_DROPLET)

        self.setWindowTitle("Experiment Design (v2)")
        self.setMinimumSize(1440, 820)

        self.model: ExperimentModel = model
        self.runtime_model = getattr(self.main_window, "model", None)
        self.choice_groups: Set[str] = set(
            f.name for f in getattr(self.model, "factors", []) if getattr(f, "kind", "") == "choice"
        )

        # Uploaded design UI state
        self._uploaded_design_active: bool = bool(self.model.has_uploaded_design())
        self._uploaded_design_path: str | None = getattr(self.model, "_uploaded_design_source", None)
        self._apply_requested: bool = False
        self._editing_locked_by_gripper: bool = False
        self._progress_protected: bool = False
        self._preserve_progress_on_finish: bool = False
        self._progress_reset_confirmed: bool = False
        self._progress_lock_status_message: str = ""
        self._gripper_lock_connection = None
        self._auto_update_suspended: bool = False
        self._design_optimization_dirty: bool = True
        self._last_optimization_result: dict | None = None


        # Debounced auto-update timer (4)
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(350)  # ms
        self._auto_timer.timeout.connect(self._recompute_silent)

        # -------------------------
        # Root layout: LEFT (narrow) | RIGHT (wide)
        # -------------------------
        self.root = QHBoxLayout(self)

        left = QVBoxLayout()                # single column for all controls/buttons
        self.root.addLayout(left, stretch=1)  # make left narrower

        right = QVBoxLayout()                 # tables column (wide)
        self.root.addLayout(right, stretch=3) # make right wider

        # ---------- Reagents table (top-right) ----------
        reagent_table_box = QtWidgets.QWidget(self)
        reagent_table_layout = QHBoxLayout(reagent_table_box)
        reagent_table_layout.setContentsMargins(0, 0, 0, 0)
        reagent_table_layout.setSpacing(0)

        self.reagent_name_table = QTableWidget(0, 1, self)
        self.reagent_name_table.setHorizontalHeaderLabels(["Stock / Label"])
        self.reagent_name_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.reagent_name_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.reagent_name_table.setColumnWidth(0, 180)
        self.reagent_name_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.reagent_name_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.reagent_name_table.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.reagent_name_table.verticalHeader().setVisible(False)
        reagent_table_layout.addWidget(self.reagent_name_table, stretch=0)

        self.reagent_table = QTableWidget(0, 12, self)
        self.reagent_table.setHorizontalHeaderLabels([
            "Reagent", "Group", "Head Type", "Mode", "Starting", "Targets", "Units",
            "Fixed Stock Conc", "Max Stock Conc", "Ejection Vol (nL)", "Prior", "Delete"
        ])
        self.reagent_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.reagent_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.reagent_table.setColumnWidth(0, 170)   # Reagent
        self.reagent_table.setColumnWidth(1, 70)    # Group
        self.reagent_table.setColumnWidth(2, 75)    # Head type
        self.reagent_table.setColumnWidth(3, 85)    # Mode
        self.reagent_table.setColumnWidth(4, 90)    # Starting
        self.reagent_table.setColumnWidth(5, 220)   # Targets
        self.reagent_table.setColumnWidth(6, 90)    # Units
        self.reagent_table.setColumnWidth(7, 120)   # Fixed stock conc
        self.reagent_table.setColumnWidth(8, 120)   # Max stock conc
        self.reagent_table.setColumnWidth(9, 105)   # Ejection vol
        self.reagent_table.setColumnWidth(10, 130)  # Prior
        self.reagent_table.setColumnWidth(11, 90)   # Delete
        reagent_table_layout.addWidget(self.reagent_table, stretch=1)
        right.addWidget(reagent_table_box)
        self.reagent_table.verticalScrollBar().valueChanged.connect(self._sync_frozen_reagent_scroll)
        self.reagent_name_table.verticalScrollBar().valueChanged.connect(self._sync_main_reagent_scroll)
        self.reagent_table.verticalHeader().sectionResized.connect(self._sync_frozen_reagent_row_height)
        self.reagent_name_table.verticalHeader().sectionResized.connect(self._sync_main_reagent_row_height)
        self.reagent_name_table.horizontalHeader().sectionResized.connect(lambda *_: self._sync_reagent_tables_geometry())

        # ---------- Stock table (bottom-right) ----------
        # Add "Max / Rxn (nL)" column
        self.stock_table_status_lbl = QLabel("")
        self.stock_table_status_lbl.setWordWrap(True)
        self.stock_table_status_lbl.setStyleSheet("color:#666; font-style: italic;")
        self.stock_table_status_lbl.setVisible(False)
        right.addWidget(self.stock_table_status_lbl)

        self.stock_table = QTableWidget(0, 9, self)
        self.stock_table.setHorizontalHeaderLabels([
            "Factor/Group", "Option", "Stock Conc", "Δ per drop",
            "Units", "Ejection Vol (nL)", "Max / Rxn (nL)", "Total Drops", "Total Vol (µL)"
        ])
        self.stock_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.stock_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        right.addWidget(self.stock_table)

        # =========================
        # right COLUMN (single stack)
        # =========================
        controls_col = QVBoxLayout()
        left.addLayout(controls_col)

        # --- Form-like controls stacked at top of right column ---
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Experiment name
        self.exp_name_edit = QLineEdit(self.model.metadata.get("name", "Untitled"))
        form.addRow(QLabel("Experiment Name"), self.exp_name_edit)

        # Replicates
        self.rep_spin = QSpinBox()
        self.rep_spin.setMinimum(1); self.rep_spin.setMaximum(9999)
        self.rep_spin.setValue(int(self.model.metadata.get("replicates", 1)))
        form.addRow(QLabel("Replicates"), self.rep_spin)

        # Target reaction volume (nL)
        self.v_spin = QDoubleSpinBox()
        self.v_spin.setDecimals(1)
        self.v_spin.setRange(1.0, 1_000_000.0)
        self.v_spin.setValue(float(self.model.metadata.get("target_reaction_volume_nL", 500.0)))
        self.v_spin.setSingleStep(50.0)
        form.addRow(QLabel("Target Reaction Volume (nL)"), self.v_spin)
        
        self.final_v_spin = QDoubleSpinBox()
        self.final_v_spin.setDecimals(1)
        self.final_v_spin.setRange(1.0, 1_000_000.0)
        # default to metadata value or fall back to target if absent
        self.final_v_spin.setValue(float(self.model.metadata.get(
            "final_reaction_volume_nL",
            self.model.metadata.get("target_reaction_volume_nL", 500.0)
        )))
        self.final_v_spin.setSingleStep(50.0)
        form.addRow(QLabel("Final Reaction Volume (nL)"), self.final_v_spin)

        self.volume_tolerance_spin = QDoubleSpinBox()
        self.volume_tolerance_spin.setDecimals(1)
        self.volume_tolerance_spin.setRange(0.0, 1_000_000.0)
        self.volume_tolerance_spin.setSingleStep(10.0)
        self.volume_tolerance_spin.setValue(float(self.model.metadata.get("printed_volume_tolerance_nL", 50.0)))
        form.addRow(QLabel("Printed Volume Tolerance (nL)"), self.volume_tolerance_spin)

        self.allow_two_chk = QCheckBox()
        self.allow_two_chk.setChecked(bool(self.model.metadata.get("allow_two_stock_solutions", False)))
        self.allow_two_chk.setToolTip("Enable two-stock fallback when a single stock cannot satisfy the targets under the current bounds.")
        form.addRow(QLabel("Allow Two Stock Solutions"), self.allow_two_chk)

        # Fill reagent name
        self.fill_name_edit = QLineEdit(self.model.metadata.get("fill_reagent_name", "Water"))
        form.addRow(QLabel("Fill Reagent Name"), self.fill_name_edit)

        fill_dv_value = float(self.model.metadata.get("fill_droplet_volume_nL", self.default_droplet_volume_nL))
        fill_mode_value = normalize_printing_mode(
            self.model.metadata.get("fill_printing_mode"),
            fallback=infer_printing_mode_from_volume(fill_dv_value, fallback=PRINTING_MODE_DROPLET),
        )

        self.fill_mode_combo = self._build_printing_mode_selector(fill_mode_value)
        form.addRow(QLabel("Fill Mode"), self.fill_mode_combo)

        # Fill ejection volume
        self.fill_dv_spin = QDoubleSpinBox()
        self.fill_dv_spin.setDecimals(1)
        self.fill_dv_spin.setSingleStep(1.0)
        self._configure_ejection_volume_spinbox(
            self.fill_dv_spin,
            fill_mode_value,
            preferred_value=fill_dv_value,
        )
        form.addRow(QLabel("Fill Ejection Vol (nL)"), self.fill_dv_spin)

        # Randomize well assignments + seed
        self.randomize_chk = QCheckBox()
        self.randomize_chk.setChecked(bool(self.model.metadata.get("randomize_assignments", False)))
        form.addRow(QLabel("Randomize well assignments"), self.randomize_chk)

        self.random_seed_spin = QSpinBox()
        self.random_seed_spin.setMinimum(0); self.random_seed_spin.setMaximum(9999999)
        current_seed = self.model.metadata.get("random_seed", 0) or 0
        self.random_seed_spin.setValue(int(current_seed))
        self.randomize_chk.toggled.connect(self.random_seed_spin.setEnabled)
        self.random_seed_spin.setEnabled(self.randomize_chk.isChecked())
        form.addRow(QLabel("Random seed"), self.random_seed_spin)

        # Use subset design + reduction factor
        self.subset_chk = QCheckBox()
        self.subset_chk.setChecked(bool(self.model.metadata.get("use_subset_design", False)))
        form.addRow(QLabel("Use subset design"), self.subset_chk)

        self.reduction_spin = QSpinBox()
        self.reduction_spin.setMinimum(1); self.reduction_spin.setMaximum(999)
        self.reduction_spin.setValue(int(self.model.metadata.get("reduction_factor", 1)))
        self.subset_chk.toggled.connect(self.reduction_spin.setEnabled)
        self.reduction_spin.setEnabled(self.subset_chk.isChecked())
        form.addRow(QLabel("Reduction factor"), self.reduction_spin)

        # Start column/row
        self.start_col_spin = QSpinBox()
        self.start_col_spin.setMinimum(0); self.start_col_spin.setMaximum(999)
        self.start_col_spin.setValue(int(self.model.metadata.get("start_col", 0)))
        form.addRow(QLabel("Start column (0-based)"), self.start_col_spin)

        self.start_row_spin = QSpinBox()
        self.start_row_spin.setMinimum(0); self.start_row_spin.setMaximum(999)
        self.start_row_spin.setValue(int(self.model.metadata.get("start_row", 0)))
        form.addRow(QLabel("Start row (0-based)"), self.start_row_spin)

        # Plate format (designer-owned source of truth)
        self.plate_format_combo = QComboBox()
        try:
            plate_names = list(self.main_window.model.well_plate.get_all_plate_names())
        except Exception:
            plate_names = []
        self.plate_format_combo.addItems(plate_names)
        selected_plate = self.model.metadata.get("plate_name")
        if not selected_plate and hasattr(self.main_window.model, "well_plate"):
            selected_plate = self.main_window.model.well_plate.get_current_plate_name()
        if selected_plate:
            idx = self.plate_format_combo.findText(str(selected_plate))
            if idx >= 0:
                self.plate_format_combo.setCurrentIndex(idx)
        form.addRow(QLabel("Plate format"), self.plate_format_combo)

        # Add the form to the left-hand column
        controls_col.addLayout(form)

        # --- Buttons stacked below the form ---
        self.add_reagent_btn = QPushButton("Add Reagent")
        self.add_reagent_btn.clicked.connect(self._on_add_reagent)
        controls_col.addWidget(self.add_reagent_btn)

        # --- Manual design vs uploaded design controls ---
        self.upload_design_btn = QPushButton("Upload reaction design (CSV)…")
        self.upload_design_btn.clicked.connect(self._on_upload_design)
        controls_col.addWidget(self.upload_design_btn)

        self.reset_upload_btn = QPushButton("Reset uploaded design")
        self.reset_upload_btn.clicked.connect(self._on_reset_uploaded_design)
        controls_col.addWidget(self.reset_upload_btn)

        self.auto_update_chk = QCheckBox("Auto update design")
        self.auto_update_chk.setChecked(True)
        self.auto_update_chk.setToolTip(
            "When enabled, design edits automatically re-optimize after a short delay. "
            "Turn this off to make several edits before pressing Optimize and Generate."
        )
        self.auto_update_chk.toggled.connect(self._on_auto_update_toggled)
        controls_col.addWidget(self.auto_update_chk)

        self.run_btn = new_btn = QPushButton("Optimize and Generate")
        self._run_btn_default_stylesheet = self.run_btn.styleSheet()
        self.run_btn.clicked.connect(self._on_optimize_and_generate)
        controls_col.addWidget(self.run_btn)

        self.new_btn = QPushButton("New Experiment")
        # self.new_btn.setStyleSheet(f"background-color: {self.color_dict['blue']}; color: white;")
        self.new_btn.clicked.connect(self._on_new_experiment)
        controls_col.addWidget(self.new_btn)

        self.save_btn = QPushButton("Save Design…")
        self.save_btn.clicked.connect(self._on_save_design)
        controls_col.addWidget(self.save_btn)

        self.load_btn = QPushButton("Load Design…")
        self.load_btn.clicked.connect(self._on_load_design)
        controls_col.addWidget(self.load_btn)

        self.finish_btn = QPushButton("Finish")
        self.finish_btn.setStyleSheet(f"background-color: {self.color_dict['dark_blue']}; color: white;")
        self.finish_btn.clicked.connect(self._on_finish)
        controls_col.addWidget(self.finish_btn)

        # Summary & status
        self.summary_lbl = QLabel("Summary: —")
        controls_col.addWidget(self.summary_lbl)

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status_lbl.setStyleSheet("color:#666; font-style: italic;")
        self.status_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        line_h = self.status_lbl.fontMetrics().height()
        self.status_lbl.setMaximumHeight(int(line_h * 3.6))
        controls_col.addWidget(self.status_lbl)

        controls_col.addStretch(1)

        # ---- Auto-update bindings ----
        def _auto_update():
            self._schedule_auto_update()
        self.randomize_chk.stateChanged.connect(_auto_update)
        self.random_seed_spin.valueChanged.connect(_auto_update)
        self.subset_chk.stateChanged.connect(_auto_update)
        self.reduction_spin.valueChanged.connect(_auto_update)
        self.start_col_spin.valueChanged.connect(_auto_update)
        self.start_row_spin.valueChanged.connect(_auto_update)
        self.allow_two_chk.stateChanged.connect(_auto_update)

        self.exp_name_edit.textChanged.connect(self._schedule_auto_update)
        self.rep_spin.valueChanged.connect(self._schedule_auto_update)
        self.v_spin.valueChanged.connect(self._schedule_auto_update)
        self.final_v_spin.valueChanged.connect(self._schedule_auto_update)
        self.volume_tolerance_spin.valueChanged.connect(self._schedule_auto_update)
        self.fill_name_edit.textChanged.connect(self._schedule_auto_update)
        self.fill_dv_spin.valueChanged.connect(self._schedule_auto_update)
        self.fill_mode_combo.currentIndexChanged.connect(self._on_fill_printing_mode_changed)
        self.plate_format_combo.currentIndexChanged.connect(self._schedule_auto_update)

        # ---- Model hooks & initial render ----
        self.model.stock_updated.connect(self._refresh_stock_table)
        self.model.experiment_generated.connect(self._on_experiment_generated)

        self._load_factors_into_table()
        self._refresh_stock_table()
        self._update_summary_labels(initial=True)
        self._refresh_all_lock_states()
        self._sync_reagent_tables_geometry()
        self._gripper_lock_connection = self.main_window.model.rack_model.gripper_updated.connect(
            self._refresh_all_lock_states
        )


    # -----------------------------
    # Table row utilities
    # -----------------------------

    def _has_frozen_reagent_column(self) -> bool:
        return getattr(self, "reagent_name_table", None) is not None

    def _reagent_table_and_column(self, logical_col: int):
        if self._has_frozen_reagent_column():
            if logical_col == self.COL_STOCK_LABEL:
                return self.reagent_name_table, 0
            return self.reagent_table, logical_col - 1
        return self.reagent_table, logical_col

    def _reagent_cell_widget(self, row: int, logical_col: int):
        table, col = self._reagent_table_and_column(logical_col)
        if table is None or row < 0 or row >= table.rowCount():
            return None
        return table.cellWidget(row, col)

    def _set_reagent_cell_widget(self, row: int, logical_col: int, widget):
        table, col = self._reagent_table_and_column(logical_col)
        if table is not None:
            table.setCellWidget(row, col, widget)

    def _reagent_column_width(self, logical_col: int) -> int:
        table, col = self._reagent_table_and_column(logical_col)
        return 0 if table is None else int(table.columnWidth(col))

    def _reagent_row_count(self) -> int:
        table = self.reagent_name_table if self._has_frozen_reagent_column() else getattr(self, "reagent_table", None)
        return 0 if table is None else table.rowCount()

    def _reagent_insert_row(self, row: int):
        if self._has_frozen_reagent_column():
            self.reagent_name_table.insertRow(row)
        if getattr(self, "reagent_table", None) is not None:
            self.reagent_table.insertRow(row)

    def _reagent_remove_row(self, row: int):
        if self._has_frozen_reagent_column():
            self.reagent_name_table.removeRow(row)
        if getattr(self, "reagent_table", None) is not None:
            self.reagent_table.removeRow(row)

    def _clear_reagent_rows(self):
        if self._has_frozen_reagent_column():
            self.reagent_name_table.setRowCount(0)
        if getattr(self, "reagent_table", None) is not None:
            self.reagent_table.setRowCount(0)

    def _iter_reagent_widgets(self):
        for row in range(self._reagent_row_count()):
            for logical_col in range(self.COL_DELETE + 1):
                widget = self._reagent_cell_widget(row, logical_col)
                if widget is not None:
                    yield row, logical_col, widget

    def _sync_reagent_tables_geometry(self):
        if not self._has_frozen_reagent_column():
            return
        header_height = self.reagent_table.horizontalHeader().height()
        self.reagent_name_table.horizontalHeader().setFixedHeight(header_height)
        frozen_width = self.reagent_name_table.columnWidth(0) + (self.reagent_name_table.frameWidth() * 2)
        self.reagent_name_table.setFixedWidth(frozen_width)
        self._sync_all_reagent_row_heights()

    def _sync_reagent_row_height(self, row: int):
        if not self._has_frozen_reagent_column():
            return
        if row < 0 or row >= self._reagent_row_count():
            return
        height = max(self.reagent_table.rowHeight(row), self.reagent_name_table.rowHeight(row))
        self.reagent_table.setRowHeight(row, height)
        self.reagent_name_table.setRowHeight(row, height)

    def _sync_all_reagent_row_heights(self):
        for row in range(self._reagent_row_count()):
            self._sync_reagent_row_height(row)

    def _sync_frozen_reagent_scroll(self, value: int):
        if not self._has_frozen_reagent_column():
            return
        if self.reagent_name_table.verticalScrollBar().value() != value:
            self.reagent_name_table.verticalScrollBar().setValue(value)

    def _sync_main_reagent_scroll(self, value: int):
        if not self._has_frozen_reagent_column():
            return
        if self.reagent_table.verticalScrollBar().value() != value:
            self.reagent_table.verticalScrollBar().setValue(value)

    def _sync_frozen_reagent_row_height(self, row: int, _old_size: int, new_size: int):
        if not self._has_frozen_reagent_column():
            return
        if self.reagent_name_table.rowHeight(row) != new_size:
            self.reagent_name_table.setRowHeight(row, new_size)

    def _sync_main_reagent_row_height(self, row: int, _old_size: int, new_size: int):
        if not self._has_frozen_reagent_column():
            return
        if self.reagent_table.rowHeight(row) != new_size:
            self.reagent_table.setRowHeight(row, new_size)

    def _bridge_get_runtime_model(self):
        return getattr(self, "runtime_model", None) or getattr(getattr(self, "main_window", None), "model", None)

    def _list_known_reagent_identities(self):
        runtime_model = self._bridge_get_runtime_model()
        getter = getattr(runtime_model, "list_known_reagent_identities", None)
        if callable(getter):
            try:
                return list(getter() or [])
            except Exception:
                return []
        return []

    def _list_known_printer_head_types(self):
        runtime_model = self._bridge_get_runtime_model()
        getter = getattr(runtime_model, "list_known_printer_head_types", None)
        if callable(getter):
            try:
                return list(getter() or [])
            except Exception:
                return []
        return []

    def _resolve_design_reagent_identity(self, *, reagent_name=None, reagent_id=None, stock_label=None):
        runtime_model = self._bridge_get_runtime_model()
        getter = getattr(runtime_model, "resolve_design_reagent_identity", None)
        if callable(getter):
            try:
                return dict(
                    getter(
                        reagent_name=reagent_name,
                        reagent_id=reagent_id,
                        stock_label=stock_label,
                    )
                    or {}
                )
            except Exception:
                return {}
        raw_name = (reagent_name or stock_label or "").strip()
        reagent_id = getattr(runtime_model, "_slugify_identity_token", lambda value: value)(reagent_id or raw_name) if runtime_model else raw_name
        return {
            "reagent_id": reagent_id,
            "display_name": raw_name or reagent_id,
            "reagent_family": None,
            "known": False,
            "quality": {"reagent_id": "inferred" if raw_name else "unknown"},
            "match_source": "unavailable",
        }

    def _find_row_for_widget(self, widget):
        if widget is None or getattr(self, "reagent_table", None) is None:
            return -1
        for row in range(self._reagent_row_count()):
            for logical_col in range(self.COL_DELETE + 1):
                if self._reagent_cell_widget(row, logical_col) is widget:
                    return row
        return -1

    @staticmethod
    def _combo_current_text(combo: QComboBox) -> str:
        if combo is None:
            return ""
        try:
            return (combo.currentText() or "").strip()
        except Exception:
            return ""

    def _combo_current_payload(self, combo: QComboBox):
        if combo is None:
            return None
        data = combo.currentData()
        if isinstance(data, dict):
            return dict(data)
        text = self._combo_current_text(combo)
        if text:
            idx = combo.findText(text)
            if idx >= 0:
                data = combo.itemData(idx)
                if isinstance(data, dict):
                    return dict(data)
        return None

    def _current_printing_mode_from_combo(self, combo: QComboBox | None, *, fallback=PRINTING_MODE_DROPLET) -> str:
        if combo is None:
            return normalize_printing_mode(fallback)
        return normalize_printing_mode(combo.currentData(), fallback=fallback)

    def _build_printing_mode_selector(self, printing_mode: str | None = None) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Droplet", PRINTING_MODE_DROPLET)
        combo.addItem("Stream", PRINTING_MODE_STREAM)
        normalized = normalize_printing_mode(printing_mode, fallback=PRINTING_MODE_DROPLET)
        for idx in range(combo.count()):
            if combo.itemData(idx) == normalized:
                combo.setCurrentIndex(idx)
                break
        return combo

    def _configure_ejection_volume_spinbox(
        self,
        spinbox: QDoubleSpinBox | None,
        printing_mode: str | None,
        *,
        preferred_value: float | None = None,
    ) -> None:
        if spinbox is None:
            return

        mode = normalize_printing_mode(printing_mode, fallback=PRINTING_MODE_DROPLET)
        min_value, max_value = printing_mode_allowed_range_nl(mode)
        candidate = float(spinbox.value()) if preferred_value is None else float(preferred_value)
        if not (min_value <= candidate <= max_value):
            candidate = printing_mode_default_ejection_volume_nl(mode)

        blocker = QSignalBlocker(spinbox)
        spinbox.setRange(min_value, max_value)
        spinbox.setValue(candidate)
        del blocker

    @staticmethod
    def _is_placeholder_stock_label(text: str) -> bool:
        lowered = (text or "").strip().lower()
        return (not lowered) or lowered.startswith("reagent-")

    def _build_known_reagent_selector(self, *, stock_label: str = "", reagent_display_name: str | None = None, reagent_id: str | None = None):
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.addItem("", None)
        for item in self._list_known_reagent_identities():
            combo.addItem(item.get("display_name") or item.get("reagent_id") or "", item)

        resolved = self._resolve_design_reagent_identity(
            reagent_name=reagent_display_name,
            reagent_id=reagent_id,
            stock_label=stock_label,
        )
        current_text = (
            reagent_display_name
            or resolved.get("display_name")
            or stock_label
            or ""
        )
        if current_text:
            idx = combo.findText(str(current_text))
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setEditText(str(current_text))
        combo.currentTextChanged.connect(self._on_reagent_identity_changed)
        return combo

    def _build_head_type_selector(self, *, head_type_id: str | None = None):
        combo = QComboBox()
        combo.addItem("Unspecified", None)
        for item in self._list_known_printer_head_types():
            combo.addItem(item.get("display_name") or item.get("head_type_id") or "", item)

        if head_type_id:
            normalized = str(head_type_id).strip()
            for idx in range(combo.count()):
                data = combo.itemData(idx)
                if isinstance(data, dict) and data.get("head_type_id") == normalized:
                    combo.setCurrentIndex(idx)
                    break
        combo.currentIndexChanged.connect(self._on_reagent_identity_changed)
        return combo

    def _format_prior_availability(self, preview: dict | None) -> tuple[str, str, str]:
        preview = dict(preview or {})
        status = str(preview.get("status") or "")
        prior = dict(preview.get("prior") or {})
        if status == "head_type_missing":
            return "Head type not set", "color:#996515;", "Choose an intended head type to check calibration memory."
        if status == "memory_disabled":
            return "Memory disabled", "color:#666;", "Calibration memory is disabled, so no prior lookup is performed."
        if status == "memory_unavailable":
            return "Memory unavailable", "color:#666;", "Calibration memory could not be queried."
        if status == "none":
            return "No prior", "color:#666;", "No calibration-memory prior found for this reagent/head-type combination."

        confidence = prior.get("recommendation_confidence_adjusted", prior.get("recommendation_confidence"))
        try:
            confidence_text = f"{float(confidence):.2f}"
        except Exception:
            confidence_text = None

        level = str(prior.get("aggregation_level") or "")
        source_labels = {
            "exact_pair": "Exact pair",
            "exact_reagent_head_type": "Exact reagent + head type",
            "reagent_family_head_type": "Reagent family + head type",
            "reagent_only": "Reagent fallback",
            "head_type_only": "Head-type fallback",
        }
        source_label = source_labels.get(level, level or "Unknown prior")
        label = "Strong prior" if status == "strong" else "Some prior"
        color = "color:#1f6f43;" if status == "strong" else "color:#1b3a57;"

        details = [source_label]
        if confidence_text is not None:
            details.append(f"confidence {confidence_text}")
        if prior.get("recommended_pressure_psi") is not None:
            try:
                details.append(f"start {float(prior.get('recommended_pressure_psi')):.3f} psi")
            except Exception:
                pass
        band = prior.get("recommended_pressure_band_psi") or prior.get("trajectory_pressure_band_psi")
        if isinstance(band, (list, tuple)) and len(band) == 2:
            try:
                details.append(f"band {float(band[0]):.3f}-{float(band[1]):.3f} psi")
            except Exception:
                pass
        if prior.get("expected_mean_volume_nL") is not None:
            try:
                details.append(f"volume {float(prior.get('expected_mean_volume_nL')):.3f} nL")
            except Exception:
                pass
        if prior.get("expected_cv_pct") is not None:
            try:
                details.append(f"CV {float(prior.get('expected_cv_pct')):.2f}%")
            except Exception:
                pass
        if prior.get("contributing_runs") is not None:
            details.append(f"{int(prior.get('contributing_runs'))} runs")
        return label, color, " | ".join(details)

    def _resolve_reagent_selection_from_row(self, row: int):
        name_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_STOCK_LABEL)
        reagent_combo: QComboBox = self._reagent_cell_widget(row, self.COL_REAGENT)
        stock_label = (name_edit.text() or "").strip() if name_edit is not None else ""
        reagent_payload = self._combo_current_payload(reagent_combo)
        reagent_text = self._combo_current_text(reagent_combo)
        resolved = self._resolve_design_reagent_identity(
            reagent_name=reagent_text,
            reagent_id=(reagent_payload or {}).get("reagent_id") if reagent_payload else None,
            stock_label=stock_label,
        )
        return {
            "stock_label": stock_label,
            "selection_text": reagent_text,
            "selection_payload": reagent_payload,
            "resolved": resolved,
        }

    def _refresh_prior_availability_for_row(self, row: int):
        if row < 0 or row >= self._reagent_row_count():
            return None
        runtime_model = self._bridge_get_runtime_model()
        prior_label: QLabel = self._reagent_cell_widget(row, self.COL_PRIOR)
        head_type_combo: QComboBox = self._reagent_cell_widget(row, self.COL_HEAD_TYPE)
        dv_spin: QDoubleSpinBox = self._reagent_cell_widget(row, self.COL_DROPLET)
        if prior_label is None:
            return None

        resolved = self._resolve_reagent_selection_from_row(row)
        head_type_payload = self._combo_current_payload(head_type_combo)
        head_type_id = (head_type_payload or {}).get("head_type_id") if head_type_payload else None
        target_volume = float(dv_spin.value()) if dv_spin is not None else None

        preview = None
        getter = getattr(runtime_model, "preview_experiment_design_prior", None)
        if callable(getter):
            try:
                preview = dict(
                    getter(
                        reagent_name=resolved["selection_text"] or resolved["stock_label"],
                        reagent_id=(resolved.get("resolved") or {}).get("reagent_id"),
                        head_type_id=head_type_id,
                        target_volume_nl=target_volume,
                        stock_label=resolved["stock_label"],
                    )
                    or {}
                )
            except Exception:
                preview = {"status": "memory_unavailable"}
        if preview is None:
            preview = {"status": "memory_unavailable"}

        label_text, style, tooltip = self._format_prior_availability(preview)
        prior_label.setText(label_text)
        prior_label.setStyleSheet(style)
        prior_label.setToolTip(tooltip)
        prior_label.setProperty("prior_preview", preview)
        return preview

    def _refresh_all_prior_availability(self):
        for row in range(self._reagent_row_count()):
            self._refresh_prior_availability_for_row(row)

    def _on_reagent_identity_changed(self, *_args):
        row = self._find_row_for_widget(self.sender())
        if row >= 0:
            name_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_STOCK_LABEL)
            resolved = self._resolve_reagent_selection_from_row(row)
            suggested_label = (resolved.get("resolved") or {}).get("display_name")
            if name_edit is not None and self._is_placeholder_stock_label(name_edit.text()) and suggested_label:
                blocker = QSignalBlocker(name_edit)
                name_edit.setText(str(suggested_label))
            self._refresh_prior_availability_for_row(row)
        self._schedule_auto_update()

    def _on_reagent_printing_mode_changed(self, *_args):
        row = self._find_row_for_widget(self.sender())
        if row < 0:
            self._schedule_auto_update()
            return
        mode_combo: QComboBox = self._reagent_cell_widget(row, self.COL_MODE)
        dv_spin: QDoubleSpinBox = self._reagent_cell_widget(row, self.COL_DROPLET)
        self._configure_ejection_volume_spinbox(
            dv_spin,
            self._current_printing_mode_from_combo(mode_combo),
        )
        self._refresh_prior_availability_for_row(row)
        self._schedule_auto_update()

    def _on_fill_printing_mode_changed(self, *_args):
        self._configure_ejection_volume_spinbox(
            self.fill_dv_spin,
            self._current_printing_mode_from_combo(getattr(self, "fill_mode_combo", None)),
        )
        self._schedule_auto_update()

    def _make_group_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.addItem(self.GROUP_ADDITIVE)
        for g in sorted(self.choice_groups):
            combo.addItem(g)
        combo.addItem(self.GROUP_NEW)

        # 5) Use 'activated' so programmatic setCurrentIndex won't re-trigger the dialog
        combo.activated.connect(lambda _: self._maybe_create_group(combo))
        return combo

    def _maybe_create_group(self, combo: QComboBox):
        if combo.currentText() != self.GROUP_NEW:
            return

        name, ok = QInputDialog.getText(self, "Create choice group", "Group name:")
        if not ok or not name.strip():
            # revert to Additive if canceled or empty
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findText(self.GROUP_ADDITIVE)))
            combo.blockSignals(False)
            return

        name = name.strip()
        if name == self.GROUP_ADDITIVE:
            QMessageBox.warning(self, "Invalid name", "“Additive” is reserved.")
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findText(self.GROUP_ADDITIVE))
            combo.blockSignals(False)
            return

        if name in self.choice_groups:
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findText(name))
            combo.blockSignals(False)
            return

        # add to set and to all combos
        self.choice_groups.add(name)
        for row in range(self._reagent_row_count()):
            c: QComboBox = self._reagent_cell_widget(row, self.COL_GROUP)
            if c.findText(name) < 0:
                c.blockSignals(True)
                c.insertItem(c.count() - 1, name)
                c.blockSignals(False)

        combo.blockSignals(True)
        combo.setCurrentIndex(combo.findText(name))
        combo.blockSignals(False)

        # No auto-recompute here; user still needs to assign reagents to that group

    def _parse_targets(self, text: str) -> List[float]:
        # Accept comma or whitespace separated floats
        text = (text or "").replace(",", " ")
        parts = [p for p in text.split() if p.strip()]
        vals: List[float] = []
        for p in parts:
            try:
                vals.append(float(p))
            except ValueError:
                pass
        # unique + sorted
        return sorted(set(vals))

    def _add_reagent_row(self, name: str = "", group: str = GROUP_ADDITIVE,
                        targets: str = "0, 1, 2", units: str = "mM",
                        droplet_nL: float = 10.0, starting_conc: float = 0.0,
                        forced_stock_conc: float | None = None,
                        max_stock_conc: float | None = None,
                        reagent_id: str | None = None,
                        reagent_display_name: str | None = None,
                        intended_head_type_id: str | None = None,
                        intended_head_type_display_name: str | None = None,
                        printing_mode: str | None = None):
        row = self._reagent_row_count()
        self._reagent_insert_row(row)

        # 0 Stock / Label
        name_edit = QLineEdit(name or f"reagent-{row+1}")
        name_edit.textEdited.connect(self._schedule_auto_update)
        self._set_reagent_cell_widget(row, self.COL_STOCK_LABEL, name_edit)

        # 1 Reagent identity
        reagent_combo = self._build_known_reagent_selector(
            stock_label=name or f"reagent-{row+1}",
            reagent_display_name=reagent_display_name,
            reagent_id=reagent_id,
        )
        self._set_reagent_cell_widget(row, self.COL_REAGENT, reagent_combo)

        # 2 Group
        group_combo = self._make_group_combo()
        group_combo.setCurrentIndex(
            group_combo.findText(group if group in self.choice_groups or group == self.GROUP_ADDITIVE
                                else self.GROUP_ADDITIVE)
        )
        group_combo.activated.connect(self._schedule_auto_update)
        self._set_reagent_cell_widget(row, self.COL_GROUP, group_combo)

        # 3 Intended head type
        head_type_combo = self._build_head_type_selector(head_type_id=intended_head_type_id)
        if intended_head_type_display_name and head_type_combo.currentIndex() <= 0:
            head_type_combo.setToolTip(str(intended_head_type_display_name))
        self._set_reagent_cell_widget(row, self.COL_HEAD_TYPE, head_type_combo)

        # 4 Printing mode
        initial_mode = normalize_printing_mode(
            printing_mode,
            fallback=infer_printing_mode_from_volume(droplet_nL, fallback=PRINTING_MODE_DROPLET),
        )
        mode_combo = self._build_printing_mode_selector(initial_mode)
        mode_combo.currentIndexChanged.connect(self._on_reagent_printing_mode_changed)
        self._set_reagent_cell_widget(row, self.COL_MODE, mode_combo)

        # 5 Starting concentration
        start_spin = QDoubleSpinBox()
        start_spin.setDecimals(4)
        start_spin.setRange(0.0, 1e12)
        start_spin.setSingleStep(0.1)
        start_spin.setValue(float(starting_conc or 0.0))
        start_spin.valueChanged.connect(self._schedule_auto_update)
        self._set_reagent_cell_widget(row, self.COL_STARTING, start_spin)

        # 6 Targets
        tgt_edit = QLineEdit(targets)
        tgt_edit.textEdited.connect(self._schedule_auto_update)
        self._set_reagent_cell_widget(row, self.COL_TARGETS, tgt_edit)

        # 7 Units
        units_edit = QLineEdit(units)
        units_edit.textEdited.connect(self._schedule_auto_update)
        self._set_reagent_cell_widget(row, self.COL_UNITS, units_edit)

        # 8 Fixed Stock Conc (blank => optimize)
        stock_edit = QLineEdit("" if forced_stock_conc in (None, 0.0) else str(forced_stock_conc))
        stock_edit.setPlaceholderText("auto")
        stock_edit.setToolTip(self._default_fixed_stock_tooltip())
        stock_edit.textEdited.connect(self._schedule_auto_update)
        self._set_reagent_cell_widget(row, self.COL_SET_STOCK, stock_edit)

        # 9 Max Stock Conc (blank => unbounded)
        max_stock_edit = QLineEdit("" if max_stock_conc in (None, 0.0) else str(max_stock_conc))
        max_stock_edit.setPlaceholderText("unbounded")
        max_stock_edit.setToolTip(self._default_max_stock_tooltip())
        max_stock_edit.textEdited.connect(self._schedule_auto_update)
        self._set_reagent_cell_widget(row, self.COL_MAX_STOCK, max_stock_edit)

        # 10 Ejection volume
        dv_spin = QDoubleSpinBox()
        dv_spin.setDecimals(1)
        dv_spin.setSingleStep(1.0)
        self._configure_ejection_volume_spinbox(
            dv_spin,
            initial_mode,
            preferred_value=float(droplet_nL),
        )
        dv_spin.valueChanged.connect(self._schedule_auto_update)
        self._set_reagent_cell_widget(row, self.COL_DROPLET, dv_spin)

        # 11 Prior availability
        prior_label = QLabel("Head type not set")
        prior_label.setWordWrap(True)
        prior_label.setStyleSheet("color:#996515;")
        self._set_reagent_cell_widget(row, self.COL_PRIOR, prior_label)

        # 12 Delete
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(lambda _, r=row: self._delete_row(r))
        self._set_reagent_cell_widget(row, self.COL_DELETE, del_btn)

        self._sync_reagent_row_height(row)
        self._refresh_prior_availability_for_row(row)
        self._sync_reagent_tables_geometry()
        self._schedule_auto_update()

    def _delete_row(self, r: int):
        self._reagent_remove_row(r)
        for i in range(self._reagent_row_count()):
            btn: QPushButton = self._reagent_cell_widget(i, self.COL_DELETE)
            try:
                btn.clicked.disconnect()
            except Exception:
                pass
            btn.clicked.connect(lambda _, rr=i: self._delete_row(rr))
        self._sync_reagent_tables_geometry()
        self._refresh_all_prior_availability()
        self._schedule_auto_update()

    def _auto_update_enabled(self) -> bool:
        chk = getattr(self, "auto_update_chk", None)
        if chk is None:
            return True
        try:
            return bool(chk.isChecked())
        except Exception:
            return True

    def _run_button_dirty_stylesheet(self) -> str:
        color = str(self.color_dict.get("dark_blue") or "#1b3a57")
        return f"background-color: {color}; color: white;"

    def _update_run_button_dirty_state(self):
        run_btn = getattr(self, "run_btn", None)
        if run_btn is None:
            return
        dirty = bool(getattr(self, "_design_optimization_dirty", True))
        if dirty and not self._auto_update_enabled():
            run_btn.setStyleSheet(self._run_button_dirty_stylesheet())
        else:
            run_btn.setStyleSheet(getattr(self, "_run_btn_default_stylesheet", ""))

    def _on_auto_update_toggled(self, checked: bool):
        timer = getattr(self, "_auto_timer", None)
        if not checked:
            if timer is not None:
                timer.stop()
            if getattr(self, "_design_optimization_dirty", False):
                self._set_status("Design edits pending. Press Optimize and Generate to update.")
            self._update_run_button_dirty_state()
            return

        self._update_run_button_dirty_state()
        if getattr(self, "_design_optimization_dirty", False):
            if timer is not None:
                timer.start()

    def _mark_design_optimization_dirty(self):
        self._design_optimization_dirty = True
        self._update_run_button_dirty_state()

    def _mark_design_optimization_clean(self, result: dict | None = None):
        self._design_optimization_dirty = False
        self._last_optimization_result = result
        timer = getattr(self, "_auto_timer", None)
        if timer is not None:
            timer.stop()
        self._update_run_button_dirty_state()

    def _has_current_generated_design(self) -> bool:
        plans = getattr(self.model, "plans_per_option", None)
        if not plans:
            return False

        reactions_df = getattr(self.model, "_reactions_df", None)
        if reactions_df is not None:
            try:
                if not bool(getattr(reactions_df, "empty", True)):
                    return True
            except Exception:
                pass

        get_count = getattr(self.model, "get_number_of_reactions", None)
        if callable(get_count):
            try:
                return int(get_count() or 0) > 0
            except Exception:
                return False
        return False

    def _can_reuse_current_generated_design(self) -> bool:
        return (
            not bool(getattr(self, "_design_optimization_dirty", True))
            and self._has_current_generated_design()
        )

    def _schedule_auto_update(self, *_args, mark_dirty: bool = True):
        if getattr(self, "_auto_update_suspended", False):
            return

        if mark_dirty:
            self._mark_design_optimization_dirty()

        if (
            getattr(self, "_uploaded_design_active", False)
            and not getattr(self, "_design_optimization_dirty", True)
            and self._has_current_generated_design()
        ):
            return

        if not self._auto_update_enabled():
            timer = getattr(self, "_auto_timer", None)
            if timer is not None:
                timer.stop()
            if getattr(self, "_design_optimization_dirty", False):
                self._set_status("Design edits pending. Press Optimize and Generate to update.")
            self._update_run_button_dirty_state()
            return

        # Debounce rapid edits
        timer = getattr(self, "_auto_timer", None)
        if timer is not None:
            timer.start()

    def _recompute_silent(self):
        if (
            getattr(self, "_uploaded_design_active", False)
            and self._can_reuse_current_generated_design()
        ):
            return
        self._run_design_optimization_flow(
            show_failure_dialog=False,
            show_capacity_dialog=False,
            busy_message="Updating experiment design... this may take a moment on Raspberry Pi.",
        )

    def _load_factors_into_table(self):
        """Populate the reagent table from the model's current factors (if any)."""
        previous_suspended = getattr(self, "_auto_update_suspended", False)
        self._auto_update_suspended = True
        try:
            self._clear_reagent_rows()
            # Additives
            for f in getattr(self.model, "factors", []):
                if f.kind == "additive":
                    o = f.options[0]
                    self._add_reagent_row(
                        name=o.name,
                        group=self.GROUP_ADDITIVE,
                        targets=", ".join(str(x) for x in o.targets),
                        units=o.units,
                        droplet_nL=o.droplet_nL,
                        starting_conc=getattr(o, "starting_conc", 0.0),
                        forced_stock_conc=getattr(o, "forced_stock_conc", None),
                        max_stock_conc=getattr(o, "max_stock_conc", None),
                        reagent_id=getattr(o, "reagent_id", None),
                        reagent_display_name=getattr(o, "reagent_display_name", None),
                        intended_head_type_id=getattr(o, "intended_head_type_id", None),
                        intended_head_type_display_name=getattr(o, "intended_head_type_display_name", None),
                        printing_mode=getattr(o, "printing_mode", None),
                    )
            # Choice groups
            for f in getattr(self.model, "factors", []):
                if f.kind == "choice":
                    self.choice_groups.add(f.name)
                    for o in f.options:
                        self._add_reagent_row(
                            name=o.name,
                            group=f.name,
                            targets=", ".join(str(x) for x in o.targets),
                            units=o.units,
                            droplet_nL=o.droplet_nL,
                            starting_conc=getattr(o, "starting_conc", 0.0),
                            forced_stock_conc=getattr(o, "forced_stock_conc", None),
                            max_stock_conc=getattr(o, "max_stock_conc", None),
                            reagent_id=getattr(o, "reagent_id", None),
                            reagent_display_name=getattr(o, "reagent_display_name", None),
                            intended_head_type_id=getattr(o, "intended_head_type_id", None),
                            intended_head_type_display_name=getattr(o, "intended_head_type_display_name", None),
                            printing_mode=getattr(o, "printing_mode", None),
                        )
            self._sync_reagent_tables_geometry()
            self._refresh_all_prior_availability()
        finally:
            self._auto_update_suspended = previous_suspended

    def _design_busy_widgets(self) -> list[Any]:
        return [
            getattr(self, "run_btn", None),
            getattr(self, "finish_btn", None),
            getattr(self, "save_btn", None),
            getattr(self, "upload_design_btn", None),
            getattr(self, "reset_upload_btn", None),
            getattr(self, "add_reagent_btn", None),
            getattr(self, "auto_update_chk", None),
            getattr(self, "new_btn", None),
            getattr(self, "load_btn", None),
        ]
    # -----------------------------
    # Uploaded design mode toggling
    # -----------------------------
    def _apply_uploaded_design_mode_to_ui(self, active: bool):
        """
        Turn CSV-upload mode on/off.

        When active:
          - Disable manual *structure* editing (adding/removing reagents, changing groups/targets/units).
          - Keep 'Starting', 'Set Stock Conc', and 'Droplet Vol' fully editable.
        """
        self._uploaded_design_active = bool(active)

        #
        # Top-level controls:
        #
        # These should be disabled when a custom design CSV is in control of the reactions.
        #
        self.add_reagent_btn.setEnabled(not active)
        # If you have any "Remove reagent", "Clone reagent", etc. buttons, disable them here too.

        # You may or may not want to disable subset-design controls;
        # with an uploaded design they're usually meaningless, so I disable them:
        self.subset_chk.setEnabled(not active)
        self.reduction_spin.setEnabled(not active and self.subset_chk.isChecked())

        # "New experiment" and "Load Design…" usually remain allowed so user can leave upload-mode.
        # If in your previous version you disabled them, you can keep that behavior if you prefer.
        # self.new_btn.setEnabled(not active)
        # self.load_btn.setEnabled(not active)

        #
        # Per-row reagent table behavior:
        #
        #  Lock these columns:
        #    - Stock / Label
        #    - Group
        #    - Targets
        #    - Units
        #    - Delete
        #
        #  Keep editable:
        #    - Reagent
        #    - Head Type
        #    - Prior indicator (read-only)
        #    - Starting
        #    - Set Stock Conc
        #    - Droplet Vol
        #
        lock_cols = {
            self.COL_STOCK_LABEL,
            self.COL_GROUP,
            self.COL_TARGETS,
            self.COL_UNITS,
            self.COL_DELETE,
        }

        for row in range(self.reagent_table.rowCount()):
            for col in range(self.reagent_table.columnCount()):
                w = self.reagent_table.cellWidget(row, col)
                if w is None:
                    continue

                if col in lock_cols:
                    # Structural / identity columns – freeze when active
                    if isinstance(w, QLineEdit):
                        w.setReadOnly(active)
                    elif isinstance(w, QComboBox):
                        w.setEnabled(not active)
                    elif isinstance(w, QPushButton):
                        w.setEnabled(not active)
                    else:
                        w.setEnabled(not active)
                else:
                    # Starting conc, Set Stock, Droplet Vol – always editable
                    if isinstance(w, QLineEdit):
                        w.setReadOnly(False)
                    else:
                        w.setEnabled(True)
        

    def _on_upload_design(self):
        """Launch a feasibility wizard for explicit reaction designs."""
        printed_volume = (
            float(self.v_spin.value())
            if hasattr(self, "v_spin") and self.v_spin is not None
            else float(getattr(self.model, "metadata", {}).get("target_reaction_volume_nL", 500.0))
        )
        final_volume = (
            float(self.final_v_spin.value())
            if hasattr(self, "final_v_spin") and self.final_v_spin is not None
            else float(getattr(self.model, "metadata", {}).get("final_reaction_volume_nL", printed_volume))
        )
        printed_volume_tolerance = (
            float(self.volume_tolerance_spin.value())
            if hasattr(self, "volume_tolerance_spin") and self.volume_tolerance_spin is not None
            else float(getattr(self.model, "metadata", {}).get("printed_volume_tolerance_nL", 50.0))
        )
        allow_two = (
            bool(self.allow_two_chk.isChecked())
            if hasattr(self, "allow_two_chk") and self.allow_two_chk is not None
            else bool(getattr(self.model, "metadata", {}).get("allow_two_stock_solutions", False))
        )
        wizard = ExperimentImportWizard(
            self.model,
            self,
            printed_volume_nL=printed_volume,
            printed_volume_tolerance_nL=printed_volume_tolerance,
            final_volume_nL=final_volume,
            allow_two=allow_two,
        )
        if wizard.exec() != QDialog.Accepted:
            return

        payload = wizard.get_apply_payload()
        df = payload.get("design_df")
        if df is None or df.empty:
            return

        # Push into the model – this will rebuild factors and uploaded reactions.
        # We default to same droplet volume and units assumptions used elsewhere.
        if not self._validate_uploaded_design_well_assignments(df):
            return

        QTimer.singleShot(0, lambda payload=payload: self._apply_uploaded_design_payload(payload))

    def _apply_uploaded_design_payload(self, payload: Mapping[str, Any]):
        df = payload.get("design_df")
        if df is None or df.empty:
            return

        with (
            QSignalBlocker(self.v_spin),
            QSignalBlocker(self.final_v_spin),
            QSignalBlocker(self.volume_tolerance_spin),
            QSignalBlocker(self.allow_two_chk),
        ):
            self.v_spin.setValue(float(payload.get("printed_volume_nL", self.v_spin.value())))
            self.final_v_spin.setValue(float(payload.get("final_volume_nL", self.final_v_spin.value())))
            self.volume_tolerance_spin.setValue(float(
                payload.get("printed_volume_tolerance_nL", self.volume_tolerance_spin.value())
            ))
            self.allow_two_chk.setChecked(bool(payload.get("allow_two", self.allow_two_chk.isChecked())))

        self.model.set_metadata(
            target_reaction_volume_nL=float(self.v_spin.value()),
            printed_volume_tolerance_nL=float(self.volume_tolerance_spin.value()),
            final_reaction_volume_nL=float(self.final_v_spin.value()),
            allow_two_stock_solutions=bool(self.allow_two_chk.isChecked()),
        )

        self.model.set_uploaded_design_from_dataframe(
            df,
            units_default="",                    # user units come from header; blank defaults to "arb"
            droplet_nL_default=10.0,
            starting_conc_default=0.0,
            source_path=payload.get("source_path"),
        )

        max_stock_by_reagent = dict(payload.get("max_stock_by_reagent") or {})
        stock_settings_by_reagent = dict(payload.get("stock_settings_by_reagent") or {})
        for factor in getattr(self.model, "factors", []) or []:
            if not getattr(factor, "options", None):
                continue
            factor_name = getattr(factor, "name", "")
            option = factor.options[0]
            settings = stock_settings_by_reagent.get(factor_name) or {}
            value = settings.get("max_stock_conc", max_stock_by_reagent.get(factor_name))
            if value is not None:
                option.max_stock_conc = float(value)
            if settings:
                mode = normalize_printing_mode(
                    settings.get("printing_mode"),
                    fallback=getattr(option, "printing_mode", PRINTING_MODE_DROPLET),
                )
                option.printing_mode = mode
                try:
                    droplet_nL = float(settings.get("droplet_nL"))
                except Exception:
                    droplet_nL = printing_mode_default_ejection_volume_nl(mode)
                if not math.isfinite(droplet_nL) or droplet_nL <= 0:
                    droplet_nL = printing_mode_default_ejection_volume_nl(mode)
                option.droplet_nL = float(droplet_nL)

        # Update local flags
        self._uploaded_design_active = True
        self._uploaded_design_path = payload.get("source_path")

        # Rebuild UI from the model's new factors
        self.choice_groups = set(
            f.name for f in getattr(self.model, "factors", []) if getattr(f, "kind", "") == "choice"
        )
        self._load_factors_into_table()
        self._update_metadata_from_controls()

        # Immediately optimize & generate using the uploaded design
        self._run_design_optimization_flow(
            show_failure_dialog=True,
            failure_title="Optimization failed",
            failure_prefix="Could not find feasible stock solutions for the uploaded design:\n",
            show_capacity_dialog=False,
            refresh_lock_states=True,
            busy_message="Applying uploaded design and optimizing stock solutions... this may take a moment on Raspberry Pi.",
        )

    def _validate_uploaded_design_well_assignments(self, df) -> bool:
        extract_well_ids = getattr(self.model, "extract_uploaded_design_well_ids_from_dataframe", None)
        if not callable(extract_well_ids):
            return True

        uploaded_well_ids = extract_well_ids(df)
        if not uploaded_well_ids:
            return True

        well_plate = getattr(getattr(self.main_window, "model", None), "well_plate", None)
        if well_plate is None:
            return True

        selected_plate_name = None
        if hasattr(self, "plate_format_combo") and self.plate_format_combo is not None:
            selected_plate_name = self.plate_format_combo.currentText().strip() or None

        try:
            well_plate.validate_explicit_well_ids(
                uploaded_well_ids,
                plate_name=selected_plate_name or None,
            )
        except ValueError as e:
            message = str(e)
            self._set_status(message)
            QMessageBox.warning(self, "Invalid well assignments", message)
            return False

        return True

    def _on_reset_uploaded_design(self):
        if not self._uploaded_design_active and not self.model.has_uploaded_design():
            return

        resp = QMessageBox.question(
            self,
            "Reset uploaded design",
            "This will discard the imported reaction design and return to manual design mode.\n\n"
            "Existing reagents will remain in the table, but you can edit them again.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if resp != QMessageBox.Yes:
            return

        # Clear model's uploaded design
        self.model.clear_uploaded_design()
        self._uploaded_design_active = False
        self._uploaded_design_path = None

        # We keep the current factors (the uploaded design already set them).
        # Just rebuild table UI from whatever is now in model.factors.
        self.choice_groups = set(
            f.name for f in getattr(self.model, "factors", []) if getattr(f, "kind", "") == "choice"
        )
        self._load_factors_into_table()
        self._run_design_optimization_flow(
            show_failure_dialog=False,
            show_capacity_dialog=False,
            refresh_lock_states=True,
        )

    def _manual_assignments_active(self) -> bool:
        """
        Return True if the ExperimentModel currently has explicit
        well assignments (manual layout) configured.
        """
        em = self.model
        try:
            if hasattr(em, "has_explicit_well_assignments") and callable(em.has_explicit_well_assignments):
                return bool(em.has_explicit_well_assignments())
            wells = getattr(em, "_uploaded_well_ids", None)
            return bool(wells)
        except Exception:
            return False

    def _apply_manual_assignment_lock_state(self):
        """
        When explicit well assignments are present:
          - Force replicates to 0 in the UI and disable the spinbox.
          - Disable randomize checkbox.
          - Disable random seed spinbox (regardless of randomize state).
        """
        active = self._manual_assignments_active()

        # Replicates spin: when manual layout is active, force 1 and lock.
        if hasattr(self, "rep_spin") and self.rep_spin is not None:
            blocker = QSignalBlocker(self.rep_spin)
            if active:
                # Allow 1 in the spinbox so it matches metadata
                if self.rep_spin.minimum() != 1:
                    self.rep_spin.setMinimum(1)
                if self.rep_spin.value() != 1:
                    self.rep_spin.setValue(1)
                self.rep_spin.setEnabled(False)
            else:
                # Restore normal behavior
                if self.rep_spin.minimum() != 1:
                    self.rep_spin.setMinimum(1)
                self.rep_spin.setEnabled(True)

        # Randomize checkbox
        if hasattr(self, "randomize_chk") and self.randomize_chk is not None:
            self.randomize_chk.setEnabled(not active)

        # Random seed spinbox: only enabled if not manual & randomize is checked
        if hasattr(self, "random_seed_spin") and self.random_seed_spin is not None:
            self.random_seed_spin.setEnabled(
                (not active) and self.randomize_chk.isChecked()
            )

        if hasattr(self, "start_col_spin") and self.start_col_spin is not None:
            self.start_col_spin.setEnabled(not active)
        if hasattr(self, "start_row_spin") and self.start_row_spin is not None:
            self.start_row_spin.setEnabled(not active)
        if hasattr(self, "plate_format_combo") and self.plate_format_combo is not None:
            self.plate_format_combo.setEnabled(not active)

    def _is_gripper_loaded(self) -> bool:
        try:
            return self.main_window.model.rack_model.get_gripper_printer_head() is not None
        except Exception:
            return False

    def _apply_gripper_edit_lock_state(self):
        self._editing_locked_by_gripper = self._is_gripper_loaded()
        locked = self._editing_locked_by_gripper

        mutating_controls = [
            "add_reagent_btn",
            "upload_design_btn",
            "reset_upload_btn",
            "run_btn",
            "new_btn",
            "save_btn",
            "load_btn",
            "finish_btn",
            "rep_spin",
            "v_spin",
            "final_v_spin",
            "volume_tolerance_spin",
            "fill_name_edit",
            "fill_mode_combo",
            "fill_dv_spin",
            "allow_two_chk",
            "randomize_chk",
            "random_seed_spin",
            "subset_chk",
            "reduction_spin",
            "start_col_spin",
            "start_row_spin",
            "plate_format_combo",
        ]
        for attr_name in mutating_controls:
            widget = getattr(self, attr_name, None)
            if widget is not None and locked:
                widget.setEnabled(False)

        if hasattr(self, "reagent_table") and self.reagent_table is not None:
            for row in range(self.reagent_table.rowCount()):
                for col in range(self.reagent_table.columnCount()):
                    w = self.reagent_table.cellWidget(row, col)
                    if w is None:
                        continue
                    if isinstance(w, QLineEdit):
                        if locked:
                            w.setReadOnly(True)
                    elif locked:
                        w.setEnabled(False)

        if locked:
            self._set_status("Design is view-only while a printer head is loaded in the gripper.")
        elif hasattr(self, "status_lbl") and self.status_lbl is not None:
            if self.status_lbl.text() == "Design is view-only while a printer head is loaded in the gripper.":
                self._set_status("")

    def _apply_default_edit_state(self):
        baseline_controls = [
            "add_reagent_btn",
            "upload_design_btn",
            "reset_upload_btn",
            "run_btn",
            "new_btn",
            "save_btn",
            "load_btn",
            "finish_btn",
            "rep_spin",
            "v_spin",
            "final_v_spin",
            "volume_tolerance_spin",
            "fill_name_edit",
            "fill_mode_combo",
            "fill_dv_spin",
            "allow_two_chk",
            "randomize_chk",
            "random_seed_spin",
            "subset_chk",
            "reduction_spin",
            "start_col_spin",
            "start_row_spin",
        ]
        for attr_name in baseline_controls:
            widget = getattr(self, attr_name, None)
            if widget is not None:
                widget.setEnabled(True)

        if hasattr(self, "random_seed_spin") and hasattr(self, "randomize_chk"):
            self.random_seed_spin.setEnabled(self.randomize_chk.isChecked())
        if hasattr(self, "reduction_spin") and hasattr(self, "subset_chk"):
            self.reduction_spin.setEnabled(self.subset_chk.isChecked())

        if hasattr(self, "reagent_table") and self.reagent_table is not None:
            for row in range(self.reagent_table.rowCount()):
                for col in range(self.reagent_table.columnCount()):
                    w = self.reagent_table.cellWidget(row, col)
                    if w is None:
                        continue
                    if isinstance(w, QLineEdit):
                        w.setReadOnly(False)
                    else:
                        w.setEnabled(True)

    def _refresh_all_lock_states(self):
        self._apply_default_edit_state()
        self._apply_uploaded_design_mode_to_ui(active=self._uploaded_design_active)
        self._apply_manual_assignment_lock_state()
        self._apply_progress_edit_lock_state()
        self._apply_gripper_edit_lock_state()

    def _apply_uploaded_design_mode_to_ui(self, active: bool):
        self._uploaded_design_active = bool(active)

        self.add_reagent_btn.setEnabled(not active)
        self.subset_chk.setEnabled(not active)
        self.reduction_spin.setEnabled(not active and self.subset_chk.isChecked())

        lock_cols = {
            self.COL_STOCK_LABEL,
            self.COL_GROUP,
            self.COL_TARGETS,
            self.COL_UNITS,
            self.COL_DELETE,
        }

        for _row, col, w in self._iter_reagent_widgets():
            if col in lock_cols:
                if isinstance(w, QLineEdit):
                    w.setReadOnly(active)
                elif isinstance(w, QComboBox):
                    w.setEnabled(not active)
                elif isinstance(w, QPushButton):
                    w.setEnabled(not active)
                else:
                    w.setEnabled(not active)
            else:
                if isinstance(w, QLineEdit):
                    w.setReadOnly(False)
                else:
                    w.setEnabled(True)

    def _apply_gripper_edit_lock_state(self):
        self._editing_locked_by_gripper = self._is_gripper_loaded()
        locked = self._editing_locked_by_gripper

        mutating_controls = [
            "add_reagent_btn",
            "upload_design_btn",
            "reset_upload_btn",
            "run_btn",
            "new_btn",
            "save_btn",
            "load_btn",
            "finish_btn",
            "rep_spin",
            "v_spin",
            "final_v_spin",
            "volume_tolerance_spin",
            "fill_name_edit",
            "fill_mode_combo",
            "fill_dv_spin",
            "allow_two_chk",
            "randomize_chk",
            "random_seed_spin",
            "subset_chk",
            "reduction_spin",
            "start_col_spin",
            "start_row_spin",
            "plate_format_combo",
        ]
        for attr_name in mutating_controls:
            widget = getattr(self, attr_name, None)
            if widget is not None and locked:
                widget.setEnabled(False)

        if hasattr(self, "reagent_table") and self.reagent_table is not None:
            for _row, _col, w in self._iter_reagent_widgets():
                if isinstance(w, QLineEdit):
                    if locked:
                        w.setReadOnly(True)
                elif locked:
                    w.setEnabled(False)

        if locked:
            self._set_status("Design is view-only while a printer head is loaded in the gripper.")
        elif hasattr(self, "status_lbl") and self.status_lbl is not None:
            if self.status_lbl.text() == "Design is view-only while a printer head is loaded in the gripper.":
                self._set_status("")

    def _apply_default_edit_state(self):
        baseline_controls = [
            "add_reagent_btn",
            "upload_design_btn",
            "reset_upload_btn",
            "run_btn",
            "new_btn",
            "save_btn",
            "load_btn",
            "finish_btn",
            "rep_spin",
            "v_spin",
            "final_v_spin",
            "volume_tolerance_spin",
            "fill_name_edit",
            "fill_mode_combo",
            "fill_dv_spin",
            "allow_two_chk",
            "randomize_chk",
            "random_seed_spin",
            "subset_chk",
            "reduction_spin",
            "start_col_spin",
            "start_row_spin",
        ]
        for attr_name in baseline_controls:
            widget = getattr(self, attr_name, None)
            if widget is not None:
                widget.setEnabled(True)

        if hasattr(self, "random_seed_spin") and hasattr(self, "randomize_chk"):
            self.random_seed_spin.setEnabled(self.randomize_chk.isChecked())
        if hasattr(self, "reduction_spin") and hasattr(self, "subset_chk"):
            self.reduction_spin.setEnabled(self.subset_chk.isChecked())

        if hasattr(self, "reagent_table") and self.reagent_table is not None:
            for _row, _col, w in self._iter_reagent_widgets():
                if isinstance(w, QLineEdit):
                    w.setReadOnly(False)
                else:
                    w.setEnabled(True)

    def _progress_status_message(self, status: Mapping[str, Any]) -> str:
        wells = int(status.get("wells_with_progress", 0) or 0)
        droplets = int(status.get("total_added_droplets", 0) or 0)
        return (
            "This experiment has saved print progress "
            f"({droplets} droplet(s) recorded across {wells} well(s)). "
            "The design is view-only unless progress is deleted."
        )

    def _set_progress_protection(self, protected: bool, status: Mapping[str, Any] | None = None):
        self._progress_protected = bool(protected)
        self._preserve_progress_on_finish = bool(protected)
        self._progress_lock_status_message = (
            self._progress_status_message(status or {})
            if protected
            else ""
        )

    def _prompt_progress_policy(self, status: Mapping[str, Any], *, title: str) -> str:
        message = self._progress_status_message(status)
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setIcon(QMessageBox.Warning)
        msg.setText(message)
        msg.setInformativeText(
            "Keep Progress / Resume will preserve the saved run state and keep the design read-only. "
            "Delete Progress and Edit will discard saved progress so the design can be changed."
        )
        keep_btn = msg.addButton("Keep Progress / Resume", QMessageBox.AcceptRole)
        reset_btn = msg.addButton("Delete Progress and Edit", QMessageBox.DestructiveRole)
        cancel_btn = msg.addButton(QMessageBox.Cancel)
        msg.setDefaultButton(keep_btn)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked is reset_btn:
            return self.PROGRESS_POLICY_RESET
        if clicked is cancel_btn:
            return self.PROGRESS_POLICY_CANCEL
        return self.PROGRESS_POLICY_RESUME

    def prepare_progress_policy_for_current_design(self) -> bool:
        get_status = getattr(self.model, "get_progress_status", None)
        status = get_status() if callable(get_status) else {}
        if not status.get("has_printed_progress"):
            self._set_progress_protection(False)
            self._progress_reset_confirmed = False
            self._refresh_all_lock_states()
            return True

        policy = self._prompt_progress_policy(
            status,
            title="Experiment progress exists",
        )
        if policy == self.PROGRESS_POLICY_CANCEL:
            return False
        if policy == self.PROGRESS_POLICY_RESET:
            clearer = getattr(self.model, "clear_progress_for_design_edit", None)
            if callable(clearer):
                clearer()
            self._progress_reset_confirmed = True
            self._set_progress_protection(False)
            self._set_status("Saved progress deleted. The design can be edited.")
        else:
            self._progress_reset_confirmed = False
            self._set_progress_protection(True, status)
            self._set_status(self._progress_lock_status_message)
        self._refresh_all_lock_states()
        return True

    def _apply_progress_edit_lock_state(self):
        if not getattr(self, "_progress_protected", False):
            if hasattr(self, "status_lbl") and self.status_lbl is not None:
                if self.status_lbl.text() == getattr(self, "_progress_lock_status_message", ""):
                    self._set_status("")
            return

        mutating_controls = [
            "add_reagent_btn",
            "upload_design_btn",
            "reset_upload_btn",
            "run_btn",
            "save_btn",
            "rep_spin",
            "v_spin",
            "final_v_spin",
            "volume_tolerance_spin",
            "fill_name_edit",
            "fill_mode_combo",
            "fill_dv_spin",
            "allow_two_chk",
            "randomize_chk",
            "random_seed_spin",
            "subset_chk",
            "reduction_spin",
            "start_col_spin",
            "start_row_spin",
            "plate_format_combo",
        ]
        for attr_name in mutating_controls:
            widget = getattr(self, attr_name, None)
            if widget is not None:
                widget.setEnabled(False)

        if hasattr(self, "reagent_table") and self.reagent_table is not None:
            for _row, _col, w in self._iter_reagent_widgets():
                if isinstance(w, QLineEdit):
                    w.setReadOnly(True)
                else:
                    w.setEnabled(False)

        message = getattr(self, "_progress_lock_status_message", "")
        if message:
            self._set_status(message)

    # -----------------------------
    # Model rebuild & metadata
    # -----------------------------
    def _parse_float_or_none(self, s: str) -> float | None:
        s = (s or "").strip()
        if not s:
            return None
        try:
            v = float(s)
            return v if v > 0 else None
        except ValueError:
            return None

    def _validation_key_for_row(self, row: int) -> tuple[str, Optional[str]]:
        name_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_STOCK_LABEL)
        group_combo: QComboBox = self._reagent_cell_widget(row, self.COL_GROUP)
        reagent_name = (name_edit.text() or "").strip() if name_edit is not None else ""
        group_name = group_combo.currentText() if group_combo is not None else self.GROUP_ADDITIVE
        if not reagent_name:
            return (f"__row_{row}__", None)
        if group_name == self.GROUP_ADDITIVE:
            return (reagent_name, None)
        return (group_name, reagent_name)

    @staticmethod
    def _default_fixed_stock_tooltip() -> str:
        return "Leave blank to auto-optimize. Enter a positive number to force the stock concentration."

    @staticmethod
    def _default_max_stock_tooltip() -> str:
        return "Optional upper bound for auto-selected stock concentrations. Leave blank for no limit."

    def _parse_positive_float_issue(
        self,
        raw_text: str,
        *,
        key: tuple[str, Optional[str]],
        field: str,
        row_label: str,
    ) -> dict | None:
        text = (raw_text or "").strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return {
                "field": field,
                "severity": "error",
                "code": "invalid_number",
                "message": f"{row_label}: {field.replace('_', ' ')} must be a positive number.",
                "raw_text": text,
            }
        if value <= 0:
            return {
                "field": field,
                "severity": "error",
                "code": "nonpositive_value",
                "message": f"{row_label}: {field.replace('_', ' ')} must be greater than zero.",
                "raw_text": text,
                "value": value,
            }
        return None

    def _collect_raw_stock_input_issues(self) -> Dict[tuple[str, Optional[str]], List[Dict[str, Any]]]:
        issues: Dict[tuple[str, Optional[str]], List[Dict[str, Any]]] = {}
        for row in range(self._reagent_row_count()):
            key = self._validation_key_for_row(row)
            stock_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_SET_STOCK)
            max_stock_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_MAX_STOCK)
            label = self._key_label(key) if not key[0].startswith("__row_") else f"Row {row + 1}"

            for field_name, widget in (("fixed_stock", stock_edit), ("max_stock", max_stock_edit)):
                if widget is None:
                    continue
                issue = self._parse_positive_float_issue(
                    widget.text(),
                    key=key,
                    field=field_name,
                    row_label=label,
                )
                if issue is not None:
                    issues.setdefault(key, []).append(issue)
        return issues

    @staticmethod
    def _merge_issue_maps(*issue_maps: Mapping[tuple[str, Optional[str]], Sequence[Mapping[str, Any]]]) -> Dict[tuple[str, Optional[str]], List[Dict[str, Any]]]:
        merged: Dict[tuple[str, Optional[str]], List[Dict[str, Any]]] = {}
        for issue_map in issue_maps:
            for key, rows in (issue_map or {}).items():
                merged.setdefault(key, [])
                merged[key].extend(dict(row) for row in rows)
        return merged

    def _summarize_issue_map(
        self,
        issue_map: Mapping[tuple[str, Optional[str]], Sequence[Mapping[str, Any]]],
        *,
        fallback_reason: str | None = None,
        stale: bool = False,
        stale_message: str | None = None,
    ) -> str:
        messages: list[str] = []
        seen: set[str] = set()
        for rows in (issue_map or {}).values():
            for issue in rows:
                msg = str(issue.get("message") or "").strip()
                if msg and msg not in seen:
                    messages.append(msg)
                    seen.add(msg)
        if not messages and fallback_reason:
            messages.append(str(fallback_reason))
        if not messages and stale:
            messages.append(stale_message or "Showing last valid stock plan; current stock inputs are invalid.")
        if not messages:
            return ""
        summary = messages[0]
        if len(messages) > 1:
            summary += f" (+{len(messages) - 1} more issue(s))"
        if stale and "Showing last valid stock plan" not in summary:
            prefix = stale_message or "Showing last valid stock plan; current stock inputs are invalid."
            summary = f"{prefix} {summary}"
        return summary

    def _style_stock_input_widget(
        self,
        widget: QLineEdit,
        *,
        issues: Sequence[Mapping[str, Any]],
        default_tooltip: str,
    ):
        if widget is None:
            return
        if not issues:
            widget.setStyleSheet("")
            widget.setToolTip(default_tooltip)
            return
        severity_rank = {"error": 2, "warning": 1}
        top_severity = max((severity_rank.get(str(issue.get("severity")), 0) for issue in issues), default=0)
        if top_severity >= 2:
            widget.setStyleSheet("border:1px solid #8a0303;")
        else:
            widget.setStyleSheet("border:1px solid #996515;")
        tooltip_lines = [str(issue.get("message") or "").strip() for issue in issues if str(issue.get("message") or "").strip()]
        widget.setToolTip("\n".join(tooltip_lines) if tooltip_lines else default_tooltip)

    def _apply_stock_input_issue_state(self, issue_map: Mapping[tuple[str, Optional[str]], Sequence[Mapping[str, Any]]]):
        for row in range(self._reagent_row_count()):
            key = self._validation_key_for_row(row)
            key_issues = list((issue_map or {}).get(key, []))
            stock_issues = [issue for issue in key_issues if str(issue.get("field")) == "fixed_stock"]
            max_issues = [issue for issue in key_issues if str(issue.get("field")) == "max_stock"]

            stock_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_SET_STOCK)
            max_stock_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_MAX_STOCK)
            self._style_stock_input_widget(
                stock_edit,
                issues=stock_issues,
                default_tooltip=self._default_fixed_stock_tooltip(),
            )
            self._style_stock_input_widget(
                max_stock_edit,
                issues=max_issues,
                default_tooltip=self._default_max_stock_tooltip(),
            )

    def _clear_target_color_state(self):
        for row in range(self._reagent_row_count()):
            tgt_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_TARGETS)
            if tgt_edit is not None:
                tgt_edit.setStyleSheet("")
                tgt_edit.setToolTip("")

    def _set_stock_table_stale(self, stale: bool, message: str = ""):
        if hasattr(self, "stock_table_status_lbl") and self.stock_table_status_lbl is not None:
            self.stock_table_status_lbl.setText(message if stale else "")
            self.stock_table_status_lbl.setVisible(bool(stale and message))
        if hasattr(self, "stock_table") and self.stock_table is not None:
            self.stock_table.setStyleSheet(
                "QTableWidget { border:1px solid #8a0303; }"
                if stale else ""
            )
        
    def _rebuild_model_from_table(self):
        """Clear and rebuild factors in the model based on the table."""
        self.model.factors.clear()
        created_choice_groups: Set[str] = set()

        for row in range(self._reagent_row_count()):
            name_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_STOCK_LABEL)
            reagent_combo: QComboBox = self._reagent_cell_widget(row, self.COL_REAGENT)
            group_combo: QComboBox = self._reagent_cell_widget(row, self.COL_GROUP)
            head_type_combo: QComboBox = self._reagent_cell_widget(row, self.COL_HEAD_TYPE)
            mode_combo: QComboBox = self._reagent_cell_widget(row, self.COL_MODE)
            start_spin: QDoubleSpinBox = self._reagent_cell_widget(row, self.COL_STARTING)
            tgt_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_TARGETS)
            units_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_UNITS)
            stock_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_SET_STOCK)
            max_stock_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_MAX_STOCK)
            dv_spin: QDoubleSpinBox = self._reagent_cell_widget(row, self.COL_DROPLET)

            r_name = (name_edit.text() or "").strip()
            reagent_payload = self._combo_current_payload(reagent_combo)
            resolved_reagent = self._resolve_design_reagent_identity(
                reagent_name=self._combo_current_text(reagent_combo),
                reagent_id=(reagent_payload or {}).get("reagent_id") if reagent_payload else None,
                stock_label=r_name,
            )
            r_group = group_combo.currentText()
            head_type_payload = self._combo_current_payload(head_type_combo)
            r_start = float(start_spin.value() if start_spin is not None else 0.0)
            r_targets = self._parse_targets(tgt_edit.text())
            r_units = (units_edit.text() or "mM").strip()
            r_forced = self._parse_float_or_none(stock_edit.text())
            r_max_stock = self._parse_float_or_none(max_stock_edit.text()) if max_stock_edit is not None else None
            r_dv = float(dv_spin.value())
            r_reagent_id = resolved_reagent.get("reagent_id")
            r_reagent_display = resolved_reagent.get("display_name") or self._combo_current_text(reagent_combo) or r_name
            r_head_type_id = (head_type_payload or {}).get("head_type_id") if head_type_payload else None
            r_head_type_display = (head_type_payload or {}).get("display_name") if head_type_payload else None
            r_printing_mode = self._current_printing_mode_from_combo(
                mode_combo,
                fallback=infer_printing_mode_from_volume(r_dv, fallback=PRINTING_MODE_DROPLET),
            )

            if not r_name or not r_targets:
                continue

            if r_group == self.GROUP_ADDITIVE:
                self.model.add_additive(name=r_name, targets=r_targets,
                                        units=r_units, droplet_nL=r_dv,
                                        printing_mode=r_printing_mode,
                                        starting_conc=r_start,
                                        forced_stock_conc=r_forced,
                                        max_stock_conc=r_max_stock,
                                        reagent_id=r_reagent_id,
                                        reagent_display_name=r_reagent_display,
                                        intended_head_type_id=r_head_type_id,
                                        intended_head_type_display_name=r_head_type_display)
            else:
                if r_group not in created_choice_groups:
                    self.model.add_choice_group(r_group)
                    created_choice_groups.add(r_group)
                self.model.add_choice_option(group_name=r_group, option_name=r_name,
                                            targets=r_targets, units=r_units, droplet_nL=r_dv,
                                            printing_mode=r_printing_mode,
                                            starting_conc=r_start,
                                            forced_stock_conc=r_forced,
                                            max_stock_conc=r_max_stock,
                                            reagent_id=r_reagent_id,
                                            reagent_display_name=r_reagent_display,
                                            intended_head_type_id=r_head_type_id,
                                            intended_head_type_display_name=r_head_type_display)
        
    def _update_metadata_from_controls(self):
        # If randomize is checked and no seed yet, create a fresh one
        randomize = self.randomize_chk.isChecked()
        seed = int(self.random_seed_spin.value())
        selected_plate_name = self.plate_format_combo.currentText().strip() or None
        plate_rows = None
        plate_columns = None
        printed_volume_tolerance = (
            float(self.volume_tolerance_spin.value())
            if hasattr(self, "volume_tolerance_spin") and self.volume_tolerance_spin is not None
            else float(getattr(self.model, "metadata", {}).get("printed_volume_tolerance_nL", 50.0))
        )

        # Keep plate metadata coherent at save-time, before finish handoff mutates runtime state.
        try:
            wp = getattr(getattr(self.main_window, "model", None), "well_plate", None)
            if wp is not None and selected_plate_name:
                plate_data = wp.get_plate_data_by_name(selected_plate_name)
                plate_rows = int(plate_data.get("rows"))
                plate_columns = int(plate_data.get("columns"))
        except Exception:
            plate_rows = None
            plate_columns = None

        self.model.set_metadata(
            name=self.exp_name_edit.text().strip() or "Untitled",
            replicates=int(self.rep_spin.value()),
            target_reaction_volume_nL=float(self.v_spin.value()),
            printed_volume_tolerance_nL=printed_volume_tolerance,
            fill_reagent_name=self.fill_name_edit.text().strip() or "Water",
            fill_droplet_volume_nL=float(self.fill_dv_spin.value()),
            fill_printing_mode=self._current_printing_mode_from_combo(
                getattr(self, "fill_mode_combo", None),
                fallback=infer_printing_mode_from_volume(self.fill_dv_spin.value(), fallback=PRINTING_MODE_DROPLET),
            ),
            final_reaction_volume_nL=float(self.final_v_spin.value()),
            allow_two_stock_solutions=bool(self.allow_two_chk.isChecked()),
            randomize_assignments=randomize,
            random_seed=(seed if randomize else None),
            use_subset_design=bool(self.subset_chk.isChecked()),
            reduction_factor=int(self.reduction_spin.value()) if self.subset_chk.isChecked() else 1,
            start_col=int(self.start_col_spin.value()),
            start_row=int(self.start_row_spin.value()),
            plate_name=selected_plate_name,
            plate_rows=plate_rows,
            plate_columns=plate_columns,
        )
        print(f"[ExperimentDesignDialog] metadata updated: {self.model.metadata}")

    def _persist_design_identity_registry_entries(self):
        runtime_model = self._bridge_get_runtime_model()
        writer = getattr(runtime_model, "register_experiment_design_reagents", None)
        if callable(writer):
            try:
                writer(self.model)
            except Exception as e:
                print(f"[ExperimentDesignDialog] WARNING: could not persist reagent identities: {e}")

    def _allow_two_setting(self) -> bool:
        if hasattr(self, "allow_two_chk") and self.allow_two_chk is not None:
            return bool(self.allow_two_chk.isChecked())
        return bool(self.model.metadata.get("allow_two_stock_solutions", False))

    def _key_label(self, key: tuple[str, Optional[str]]) -> str:
        factor_name, option_name = key
        return factor_name if option_name in (None, "") else f"{factor_name}/{option_name}"

    def _update_optimization_status(self, res: dict | None):
        if not res:
            return
        if not res.get("best"):
            self._set_status(str(res.get("reason", "Optimization failed")))
            return

        preview = {}
        try:
            preview = self.model.get_target_preview_map() or {}
        except Exception:
            preview = {}

        two_stock = [
            self._key_label(key)
            for key, plan in getattr(self.model, "plans_per_option", {}).items()
            if plan.get("n_stocks", 1) == 2
        ]
        bounded_search = [
            self._key_label(key)
            for key in (res.get("two_stock_search_limited_keys") or [])
        ]
        unreachable = []
        approximate = []
        for key, rows in preview.items():
            if any(not bool(row.get("reachable")) for row in rows):
                unreachable.append(self._key_label(key))
            elif any(abs(float(row.get("abs_error", 0.0))) > 1e-12 for row in rows):
                approximate.append(self._key_label(key))

        parts = []
        if unreachable:
            parts.append(
                "Some targets remain unreachable under the selected stock settings: "
                + ", ".join(unreachable[:4])
                + ("..." if len(unreachable) > 4 else "")
                + "."
            )
        if two_stock:
            parts.append(
                "Two-stock plans are required for: "
                + ", ".join(two_stock[:4])
                + ("..." if len(two_stock) > 4 else "")
                + "."
            )
        if bounded_search:
            parts.append(
                "Two-stock search was capped for: "
                + ", ".join(bounded_search[:4])
                + ("..." if len(bounded_search) > 4 else "")
                + "."
            )
        if approximate or preview:
            parts.append("Hover a Targets field to inspect the actual achieved concentrations.")
        if not parts:
            parts.append("Optimization complete.")
        self._set_status(" ".join(parts))

    def _run_design_optimization_flow(
        self,
        *,
        show_failure_dialog: bool = False,
        failure_title: str = "Optimization failed",
        failure_prefix: str = "",
        show_capacity_dialog: bool = False,
        refresh_lock_states: bool = False,
        busy_message: str | None = None,
    ) -> tuple[bool, dict | None]:
        self._rebuild_model_from_table()
        self._refresh_all_prior_availability()
        self._update_metadata_from_controls()

        raw_issues = self._collect_raw_stock_input_issues()
        if raw_issues:
            self._mark_design_optimization_dirty()
            self._apply_stock_input_issue_state(raw_issues)
            self._clear_target_color_state()
            stale_msg = "Showing last valid stock plan; current stock inputs are invalid."
            self._set_stock_table_stale(True, stale_msg)
            summary = self._summarize_issue_map(raw_issues, stale=True, stale_message=stale_msg)
            self._set_status(summary)
            if refresh_lock_states:
                self._refresh_all_lock_states()
            if show_failure_dialog:
                QMessageBox.warning(self, failure_title, f"{failure_prefix}{summary}")
            return False, {
                "best": None,
                "reason": summary,
                "issues_by_key": raw_issues,
            }

        with _BusyUiContext(
            self,
            busy_message or "Optimizing stock solutions and generating experiment... this may take a moment on Raspberry Pi.",
            widgets=self._design_busy_widgets(),
            status_setter=self._set_status,
            failure_message="Optimization failed.",
        ):
            res = self.model.optimize_stock_solutions(
                quantum=0.1,
                max_refine=60,
                two_max_refine=40,
                allow_two=self._allow_two_setting(),
            )
            if res.get("best"):
                self.model.generate_experiment()
        merged_issues = self._merge_issue_maps(res.get("issues_by_key") or {})
        self._apply_stock_input_issue_state(merged_issues)

        if not res.get("best"):
            self._mark_design_optimization_dirty()
            self._clear_target_color_state()
            stale_msg = "Showing last valid stock plan; current stock inputs are not feasible."
            self._set_stock_table_stale(True, stale_msg)
            summary = self._summarize_issue_map(
                merged_issues,
                fallback_reason=res.get("reason"),
                stale=True,
                stale_message=stale_msg,
            )
            self._set_status(summary)
            if refresh_lock_states:
                self._refresh_all_lock_states()
            if show_failure_dialog:
                QMessageBox.warning(
                    self,
                    failure_title,
                    f"{failure_prefix}{summary or res.get('reason', 'Unknown error')}",
                )
            return False, res

        capacity_ok = self._validate_plate_capacity(show_dialog=show_capacity_dialog)
        self._refresh_stock_table()
        self._update_summary_labels()
        self._apply_target_color_state()
        self._refresh_all_prior_availability()
        self._set_stock_table_stale(False, "")
        self._update_optimization_status(res)
        self._mark_design_optimization_clean(res)
        if refresh_lock_states:
            self._refresh_all_lock_states()
        return bool(capacity_ok), res

    # -----------------------------
    # Actions
    # -----------------------------

    def _on_add_reagent(self):
        # Default to Additive (per your request)
        self._add_reagent_row(
            group=self.GROUP_ADDITIVE,
            droplet_nL=printing_mode_default_ejection_volume_nl(PRINTING_MODE_DROPLET),
            printing_mode=PRINTING_MODE_DROPLET,
        )

    def _on_optimize_and_generate(
        self,
        show_capacity_dialog: bool = False,
        *,
        busy_message: str | None = None,
    ):
        ok, _res = self._run_design_optimization_flow(
            show_failure_dialog=True,
            failure_title="Optimization failed",
            show_capacity_dialog=show_capacity_dialog,
            busy_message=busy_message or "Optimizing stock solutions and generating experiment... this may take a moment on Raspberry Pi.",
        )
        return ok

    def _available_wells_for_selected_plate(self) -> tuple[int, str]:
        """
        Compute assignable wells for the selected plate using the same gating inputs
        as runtime assignment (plate dims, start row/col, exclusions).
        """
        selected_plate = self.plate_format_combo.currentText().strip()
        wp = getattr(getattr(self.main_window, "model", None), "well_plate", None)
        if wp is None:
            return 0, selected_plate or "unknown"

        plate_name = selected_plate or wp.get_current_plate_name()
        plate = wp.get_plate_data_by_name(plate_name)
        rows = int(plate.get("rows", 0))
        cols = int(plate.get("columns", 0))
        start_row = int(self.start_row_spin.value())
        start_col = int(self.start_col_spin.value())

        if start_row < 0 or start_col < 0:
            return 0, plate_name
        if start_row >= rows or start_col >= cols:
            return 0, plate_name

        region_capacity = (rows - start_row) * (cols - start_col)
        excluded_count = 0
        for item in set(getattr(wp, "excluded_wells", set()) or set()):
            if isinstance(item, Well):
                well_id = item.well_id
            else:
                well_id = str(item).strip().upper()
            try:
                row_label, col_1 = Well.parse_well_id(well_id)
                row_idx = Well.row_label_to_index(row_label)
                col_idx = int(col_1) - 1
            except Exception:
                continue
            if 0 <= row_idx < rows and 0 <= col_idx < cols and row_idx >= start_row and col_idx >= start_col:
                excluded_count += 1
        return max(0, region_capacity - excluded_count), plate_name

    def _validate_plate_capacity(self, show_dialog: bool = True) -> bool:
        required = int(self.model.get_number_of_reactions() or 0)
        available, plate_name = self._available_wells_for_selected_plate()
        if required <= available:
            return True

        message = (
            "Not enough available wells for this experiment design.\n\n"
            f"Required reactions: {required}\n"
            f"Available wells on '{plate_name}': {available}\n\n"
            "Choose a larger plate, reduce the design size, adjust start row/column, "
            "or include more wells."
        )
        if show_dialog:
            QMessageBox.warning(self, "Insufficient Well Capacity", message)
        return False

    def _apply_target_color_state(self):
        """
        Colors each Targets cell red if a forced stock exists and at least one target is unreachable
        for that reagent (based on the model's preview map). Also sets a helpful tooltip.
        """
        preview = {}
        try:
            preview = self.model.get_target_preview_map() or {}
        except Exception:
            preview = {}

        for row in range(self._reagent_row_count()):
            name_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_STOCK_LABEL)
            group_combo: QComboBox = self._reagent_cell_widget(row, self.COL_GROUP)
            tgt_edit: QLineEdit = self._reagent_cell_widget(row, self.COL_TARGETS)

            reagent_name = (name_edit.text() or "").strip()
            group_name = group_combo.currentText()

            # Map to key used by the model
            key = (reagent_name, None) if group_name == self.GROUP_ADDITIVE else (group_name, reagent_name)
            rows = preview.get(key, [])

            if not rows:
                tgt_edit.setStyleSheet("")
                tgt_edit.setToolTip("")
                continue

            tooltip = self._build_target_preview_tooltip(rows)
            has_unreachable = any(not bool(r.get("reachable")) for r in rows)

            if has_unreachable:
                tgt_edit.setStyleSheet("color: %s;" % self.color_dict.get("dark_red", "#8a0303"))
                tgt_edit.setToolTip(tooltip)
            else:
                tgt_edit.setStyleSheet("")
                tgt_edit.setToolTip(tooltip)

    @staticmethod
    def _fmt_target_preview_num(x) -> str:
        try:
            xv = float(x)
        except Exception:
            return str(x)
        if abs(xv) <= 1e-12:
            return "0"
        ax = abs(xv)
        if 1e-3 <= ax < 1000:
            return f"{xv:.3f}".rstrip("0").rstrip(".")
        return f"{xv:.6g}"

    @staticmethod
    def _fmt_target_preview_signed(x) -> str:
        try:
            xv = float(x)
        except Exception:
            return str(x)
        sign = "+" if xv >= -1e-12 else "-"
        return f"{sign}{ExperimentDesignDialog._fmt_target_preview_num(abs(xv))}"

    @staticmethod
    def _target_preview_reason_text(reason: str) -> str:
        return {
            "rounds_to_zero_drops": "0 drops; positive targets may not round to zero",
            "outside_half_step": "outside half-step tolerance",
            "nonpositive_delta": "no positive per-drop increase",
        }.get(str(reason or ""), "")

    @classmethod
    def _build_target_preview_tooltip(cls, rows: Sequence[Mapping[str, Any]]) -> str:
        if not rows:
            return ""

        first = rows[0]
        units = str(first.get("units", "") or "").strip()
        plan_mode = str(first.get("plan_mode", "auto") or "auto")
        stock_info = first.get("stock_concentration", "")
        if isinstance(stock_info, tuple):
            stock_bits = [
                f"{cls._fmt_target_preview_num(val)} {units}".strip()
                for val in stock_info
            ]
            header = f"Achievable with 2 stocks {' + '.join(stock_bits)}:"
        else:
            stock_text = cls._fmt_target_preview_num(stock_info)
            stock_label = f"{stock_text} {units}".strip()
            header = "Achievable with stock:"
            if plan_mode == "fixed":
                header = "Achievable with fixed stock:"
            if stock_label:
                header = f"{header[:-1]} {stock_label}:"

        lines = [header]
        for row in rows:
            requested = cls._fmt_target_preview_num(row.get("requested_final", 0.0))
            achieved = cls._fmt_target_preview_num(row.get("achieved_final", 0.0))
            drops_value = row.get("droplets", 0)
            if isinstance(drops_value, tuple):
                drops = " + ".join(str(int(v)) for v in drops_value)
                total = sum(int(v) for v in drops_value)
                drop_word = "drop" if total == 1 else "drops"
            else:
                total = int(drops_value or 0)
                drops = str(total)
                drop_word = "drop" if total == 1 else "drops"
            err = cls._fmt_target_preview_signed(row.get("signed_error", 0.0))
            line = f"{requested} -> {achieved} ({drops} {drop_word}, {err})"
            if not bool(row.get("reachable")):
                reason = cls._target_preview_reason_text(str(row.get("reason", "")))
                if reason:
                    line = f"{line}; {reason}"
            lines.append(line)
        return "\n".join(lines)

    # -----------------------------
    # Stock table & summary updates
    # -----------------------------

    def _refresh_stock_table(self):
        rows = self.model.get_stock_table_rows(include_fill=True)
        self.stock_table.setRowCount(0)
        for r in rows:
            rr = self.stock_table.rowCount()
            self.stock_table.insertRow(rr)
            self.stock_table.setItem(rr, 0, QTableWidgetItem(str(r.get("factor_name", ""))))
            self.stock_table.setItem(rr, 1, QTableWidgetItem(str(r.get("option_name", ""))))
            self.stock_table.setItem(rr, 2, QTableWidgetItem(self._fmt_stock_conc_display(r.get("stock_concentration", ""))))
            self.stock_table.setItem(rr, 3, QTableWidgetItem(self._fmt_num(r.get("delta_per_drop", ""))))
            self.stock_table.setItem(rr, 4, QTableWidgetItem(str(r.get("units", ""))))
            self.stock_table.setItem(rr, 5, QTableWidgetItem(self._fmt_num(r.get("droplet_volume_nL", ""))))
            # 3) New column: per-reaction max volume (nL)
            max_nL = r.get("max_per_rxn_nL", "")
            self.stock_table.setItem(rr, 6, QTableWidgetItem(self._fmt_num(max_nL) if max_nL != "" else ""))
            self.stock_table.setItem(rr, 7, QTableWidgetItem(str(r.get("total_droplets", ""))))
            self.stock_table.setItem(rr, 8, QTableWidgetItem(self._fmt_num(r.get("total_volume_uL", ""))))
    
    def _on_experiment_generated(self, total_reactions: int, worst_nonfill_nL: float):
        # Update summary when model emits
        self._update_summary_labels(total_reactions=total_reactions, worst_nonfill_nL=worst_nonfill_nL)
        self._validate_plate_capacity(show_dialog=False)

    def _update_summary_labels(self, initial: bool = False, total_reactions: int | None = None, worst_nonfill_nL: float | None = None):
        if total_reactions is None:
            df = self.model.get_reactions_dataframe()
            total_reactions = len(df)
        if worst_nonfill_nL is None:
            worst_nonfill_nL = self.model.get_worst_nonfill_volume_nL() or 0.0
        available_wells = None
        try:
            available_wells, _ = self._available_wells_for_selected_plate()
        except Exception:
            available_wells = None

        required_html = str(total_reactions)
        if available_wells is not None and int(total_reactions) > int(available_wells):
            required_html = f"<span style='color:#8a0303; font-weight:600;'>{int(total_reactions)}</span>"

        available_text = str(available_wells) if available_wells is not None else "n/a"
        self.summary_lbl.setText(
            "Summary: "
            f"Total reactions = {required_html}  |  "
            f"Available wells = {available_text}  |  "
            f"Worst non-fill volume = {self._fmt_num(worst_nonfill_nL)} nL"
        )
    
    def _sync_controls_from_model(self):
        md = self.model.metadata

        blockers = []
        def blk(widget):
            if widget is not None:
                blockers.append(QSignalBlocker(widget))

        # Block signals while restoring to avoid re-entrancy/races
        blk(self.exp_name_edit); blk(self.rep_spin); blk(self.v_spin)
        blk(self.final_v_spin)
        blk(self.volume_tolerance_spin)
        blk(self.fill_name_edit); blk(getattr(self, "fill_mode_combo", None)); blk(self.fill_dv_spin)
        blk(self.allow_two_chk)
        blk(self.randomize_chk); blk(self.random_seed_spin)
        blk(self.subset_chk); blk(self.reduction_spin)
        blk(self.start_col_spin); blk(self.start_row_spin)
        blk(getattr(self, "plate_format_combo", None))

        self.exp_name_edit.setText(md.get("name", "Untitled"))
        self.rep_spin.setValue(int(md.get("replicates", 1)))
        self.v_spin.setValue(float(md.get("target_reaction_volume_nL", 500.0)))
        self.fill_name_edit.setText(md.get("fill_reagent_name", "Water"))
        fill_dv_value = float(md.get("fill_droplet_volume_nL", 10.0))
        fill_mode_value = normalize_printing_mode(
            md.get("fill_printing_mode"),
            fallback=infer_printing_mode_from_volume(fill_dv_value, fallback=PRINTING_MODE_DROPLET),
        )
        if hasattr(self, "fill_mode_combo") and self.fill_mode_combo is not None:
            for idx in range(self.fill_mode_combo.count()):
                if self.fill_mode_combo.itemData(idx) == fill_mode_value:
                    self.fill_mode_combo.setCurrentIndex(idx)
                    break
        self._configure_ejection_volume_spinbox(
            self.fill_dv_spin,
            fill_mode_value,
            preferred_value=fill_dv_value,
        )
        self.final_v_spin.setValue(float(md.get(
            "final_reaction_volume_nL",
            md.get("target_reaction_volume_nL", 500.0)
        )))
        self.volume_tolerance_spin.setValue(float(md.get("printed_volume_tolerance_nL", 50.0)))
        self.allow_two_chk.setChecked(bool(md.get("allow_two_stock_solutions", False)))

        if hasattr(self, "randomize_chk"):
            self.randomize_chk.setChecked(bool(md.get("randomize_assignments", False)))
        if hasattr(self, "random_seed_spin"):
            seed = md.get("random_seed", 0) or 0
            self.random_seed_spin.setValue(int(seed))
            self.random_seed_spin.setEnabled(self.randomize_chk.isChecked())

        if hasattr(self, "subset_chk"):
            self.subset_chk.setChecked(bool(md.get("use_subset_design", False)))
        if hasattr(self, "reduction_spin"):
            self.reduction_spin.setValue(int(md.get("reduction_factor", 1)))
            self.reduction_spin.setEnabled(self.subset_chk.isChecked())

        if hasattr(self, "start_col_spin"):
            self.start_col_spin.setValue(int(md.get("start_col", 0)))
        if hasattr(self, "start_row_spin"):
            self.start_row_spin.setValue(int(md.get("start_row", 0)))

        if hasattr(self, "plate_format_combo"):
            selected_plate = md.get("plate_name")
            if not selected_plate and hasattr(self.main_window.model, "well_plate"):
                selected_plate = self.main_window.model.well_plate.get_current_plate_name()
            if selected_plate:
                idx = self.plate_format_combo.findText(str(selected_plate))
                if idx >= 0:
                    self.plate_format_combo.setCurrentIndex(idx)

        self._recompute_silent()
        self._apply_manual_assignment_lock_state()

    def _ensure_experiment_dir(self):
        """
        Make sure the experiment folder exists and matches the current name.
        Will create the folder on first save, or rename it if the name changed.
        """
        name = self.exp_name_edit.text().strip() or "Untitled"
        # initialize paths if missing
        if not self.model.experiment_dir_path:
            self.model.initialize_experiment()
            return

        cur_dirname = os.path.basename(self.model.experiment_dir_path)
        if cur_dirname != name:
            # Try to rename; if the target exists, just keep the old folder and warn
            ok = self.model.rename_experiment(name)
            if not ok:
                QMessageBox.warning(self, "Rename failed",
                                    f"A folder named '{name}' already exists. Keeping the current folder.")

    def _on_new_experiment(self):
        """
        Reset the experiment to a fresh state (like app launch):
        - New Untitled-YYYYMMDD_HHMMSS name
        - Clear factors, cached tables
        - Create Experiments/<name>/ with initial files
        - Refresh UI
        """
        # Prefer the model's own reset if available (keeps your existing behavior)
        if hasattr(self.model, "reset_experiment_model"):
            try:
                self.model.reset_experiment_model()
            except Exception as e:
                self._set_status(f"New experiment failed (reset_experiment_model): {e}")
                return
        else:
            # Fallback: do a safe manual reset for the new ExperimentModel
            try:
                # fresh name
                temp_name = "Untitled-" + time.strftime("%Y%m%d_%H%M%S")
                # metadata defaults
                self.model.metadata = {
                    "name": temp_name,
                    "replicates": 1,
                    "target_reaction_volume_nL": 500.0,
                    "printed_volume_tolerance_nL": 50.0,
                    "final_reaction_volume_nL": 500.0,
                    "fill_reagent_name": "Water",
                    "fill_printing_mode": PRINTING_MODE_DROPLET,
                    "fill_droplet_volume_nL": 10.0,
                    "allow_two_stock_solutions": False,
                    "randomize_assignments": False,
                    "random_seed": None,
                    "use_subset_design": False,
                    "reduction_factor": 1,
                    "start_row": 0,
                    "start_col": 0,
                }
                # factors + caches
                self.model.factors = []
                self.model.plans_per_option.clear()
                self.model._stock_rows_cache = []
                self.model._fill_row_cache = None
                import pandas as pd
                self.model._reactions_df = pd.DataFrame()
                self.model._last_worst_nonfill_volume_nL = None

                # create folder + initial files
                if hasattr(self.model, "initialize_experiment"):
                    self.model.initialize_experiment()
            except Exception as e:
                self._set_status(f"New experiment failed (fallback): {e}")
                return

        self._progress_reset_confirmed = False
        self._set_progress_protection(False)

        # Repaint UI from the fresh model (avoid auto-update churn while setting)
        blockers = [
            QSignalBlocker(self.exp_name_edit), QSignalBlocker(self.rep_spin),
            QSignalBlocker(self.v_spin), QSignalBlocker(self.volume_tolerance_spin), QSignalBlocker(self.fill_name_edit),
            QSignalBlocker(getattr(self, "fill_mode_combo", None)), QSignalBlocker(self.fill_dv_spin), QSignalBlocker(self.allow_two_chk),
            QSignalBlocker(self.randomize_chk),
            QSignalBlocker(self.random_seed_spin), QSignalBlocker(self.subset_chk),
            QSignalBlocker(self.reduction_spin), QSignalBlocker(self.start_col_spin),
            QSignalBlocker(self.start_row_spin)
        ]

        self.choice_groups = set()
        self._load_factors_into_table()
        self._sync_controls_from_model()
        self._refresh_stock_table()
        self._update_summary_labels()
        self._refresh_all_prior_availability()

        self._set_status(f"New experiment created: {getattr(self.model, 'experiment_dir_path', '(unsaved yet)')}")

    def _on_save_design(self):
        """
        Save the current design (factors + metadata) to Experiments/<name>/experiment_design.json.
        If needed, optimize/generate so stock table is fresh in the preview.
        """
        ok, res = self._run_design_optimization_flow(
            show_failure_dialog=True,
            failure_title="Optimization failed",
            show_capacity_dialog=False,
            busy_message="Optimizing before saving design... this may take a moment on Raspberry Pi.",
        )
        if not ok:
            return
        self._persist_design_identity_registry_entries()

        # Ensure folder exists / name is current, then save
        self._ensure_experiment_dir()
        self.model.save_experiment()
        self._set_status(f"Design saved to: {self.model.experiment_file_path}")

    def _on_load_design(self):
        # Default directory = Experiments
        default_dir = None
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            maybe = os.path.join(script_dir, "Experiments")
            default_dir = maybe if os.path.isdir(maybe) else None
        except Exception:
            pass

        exp_dir = QFileDialog.getExistingDirectory(
            self, "Select Experiment Folder", default_dir or os.getcwd()
        )
        if not exp_dir:
            return

        path = os.path.join(exp_dir, "experiment_design.json")
        if not os.path.exists(path):
            self._set_status(f"No 'experiment_design.json' found in: {exp_dir}")
            return

        progress_path = os.path.join(exp_dir, "progress.json")
        progress_status = {}
        get_status = getattr(self.model, "get_progress_status", None)
        if callable(get_status):
            progress_status = get_status(progress_file_path=progress_path)

        progress_policy = None
        if progress_status.get("has_printed_progress"):
            progress_policy = self._prompt_progress_policy(
                progress_status,
                title="Loaded experiment has saved progress",
            )
            if progress_policy == self.PROGRESS_POLICY_CANCEL:
                self._set_status("Load canceled; current design was left unchanged.")
                return
            if progress_policy == self.PROGRESS_POLICY_RESET:
                clearer = getattr(self.model, "clear_progress_for_design_edit", None)
                if callable(clearer):
                    clearer(progress_file_path=progress_path)

        # Load into the model (recomputes optimization + grid)
        self.model.load_experiment(path, exp_dir)
        if progress_policy == self.PROGRESS_POLICY_RESUME:
            self._progress_reset_confirmed = False
            self._set_progress_protection(True, progress_status)
        else:
            self._progress_reset_confirmed = progress_policy == self.PROGRESS_POLICY_RESET
            self._set_progress_protection(False)

        # After loading, refresh uploaded-design UI state
        self._uploaded_design_active = self.model.has_uploaded_design()
        self._uploaded_design_path = getattr(self.model, "_uploaded_design_source", None)
        self._refresh_all_lock_states()

        # Repaint UI from model
        self.choice_groups = set(
            f.name for f in getattr(self.model, "factors", []) if getattr(f, "kind", "") == "choice"
        )
        self._load_factors_into_table()
        self._sync_controls_from_model()
        self._refresh_stock_table()
        self._update_summary_labels()
        self._refresh_all_prior_availability()
        self._refresh_all_lock_states()

        if progress_policy == self.PROGRESS_POLICY_RESUME:
            self._set_status(self._progress_lock_status_message)
        elif progress_policy == self.PROGRESS_POLICY_RESET:
            self._set_status(f"Design loaded from: {exp_dir}. Saved progress deleted; edits are enabled.")
        else:
            self._set_status(f"Design loaded from: {exp_dir}")

    def _on_finish(self):
        """
        Optimize & generate, save the design (creating/renaming the folder if needed),
        then close the dialog. Applying to the main app is explicit in this path only.
        """
        if self._editing_locked_by_gripper:
            self._set_status("Design is view-only while a printer head is loaded in the gripper.")
            return

        if (
            not getattr(self, "_progress_protected", False)
            and not getattr(self, "_progress_reset_confirmed", False)
        ):
            get_status = getattr(self.model, "get_progress_status", None)
            status = get_status() if callable(get_status) else {}
            if status.get("has_printed_progress"):
                if not self.prepare_progress_policy_for_current_design():
                    return

        if self._can_reuse_current_generated_design():
            timer = getattr(self, "_auto_timer", None)
            if timer is not None:
                timer.stop()
            if not self._validate_plate_capacity(show_dialog=True):
                return
            self._refresh_stock_table()
            self._update_summary_labels()
            self._apply_target_color_state()
        else:
            # Reuse the same logic as Optimize & Generate
            if not self._on_optimize_and_generate(
                show_capacity_dialog=True,
                busy_message="Optimizing stock solutions and generating experiment... this may take a moment on Raspberry Pi.",
            ):
                return

        # Ensure the folder exists and save the design itself
        self._ensure_experiment_dir()
        self._persist_design_identity_registry_entries()
        self.model.save_experiment()

        self._set_status("Design finalized and saved. Closing...")

        # Propagate the experiment to the main window
        try:
            if self.main_window is not None and hasattr(self.main_window, "complete_experiment_design"):
                self.main_window.complete_experiment_design(
                    load_progress=getattr(self, "_preserve_progress_on_finish", False)
                )
                self._apply_requested = True
        except Exception as e:
            message = str(e) or "Unknown error applying the experiment design."
            self._set_status(message)
            QMessageBox.warning(self, "Could not apply experiment design", message)
            print(f"[ExperimentDesignDialog] finish handoff error: {e}")
            return

        # Close dialog after explicit apply.
        self.accept()

    def _set_status(self, msg: str):
        self.status_lbl.setToolTip(msg)
        self.status_lbl.setText(msg)

    @staticmethod
    def _fmt_stock_conc_display(x, sig_figs: int = 3) -> str:
        try:
            value = Decimal(str(x))
        except (InvalidOperation, TypeError, ValueError):
            return str(x)

        if not value.is_finite():
            return str(x)
        if value == 0:
            return "0"

        exponent = value.adjusted() - (int(sig_figs) - 1)
        quantum = Decimal(f"1e{exponent}")
        rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
        text = format(rounded, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return "0" if text in ("-0", "+0") else text

    @staticmethod
    def _fmt_num(x) -> str:
        try:
            xv = float(x)
            # show as int if very close
            if abs(xv - round(xv)) < 1e-9:
                return str(int(round(xv)))
            return f"{xv:.3f}".rstrip("0").rstrip(".")
        except Exception:
            return str(x)
        
    def closeEvent(self, event):
        """
        Close-time cleanup only. Applying the design is explicit via Finish.
        """
        try:
            self._auto_timer.stop()
        except Exception:
            pass

        try:
            if self._gripper_lock_connection is not None:
                self.main_window.model.rack_model.gripper_updated.disconnect(self._refresh_all_lock_states)
                self._gripper_lock_connection = None
        except Exception:
            pass

        super().closeEvent(event)
