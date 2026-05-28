from PySide6 import QtCore, QtWidgets, QtGui, QtCharts
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QGridLayout, QGroupBox, QPushButton, QComboBox, QSpinBox, QSizePolicy,
    QSpacerItem, QInputDialog, QMessageBox, QAbstractItemView, QDialog,QLineEdit,QDoubleSpinBox,QGraphicsOpacityEffect
)
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QWidget, QGraphicsEllipseItem, QGraphicsScene, QGraphicsView, QGraphicsRectItem
from PySide6.QtGui import QShortcut, QKeySequence, QPixmap, QColor, QPen, QBrush, QImage, QPainter, QIcon
from PySide6.QtCore import Qt, QTimer, QEventLoop, Signal, Slot
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import numpy as np
import json
import os
import random
import time
import shutil
import uuid
from datetime import datetime
from pathlib import Path
import cv2
from utilities import ShortcutManager
from .Model import NozzlePositionChecklistStore
from hardware.null_devices import NullCamera

class RackCalibrationFixDialog(QtWidgets.QDialog):
    def __init__(self, main_window, model, controller):
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        super().__init__()
        print('\n---Created new rack calibration fix dialog---\n')
        self.model = model
        self.rack_model = model.rack_model
        self.controller = controller
        self.setWindowTitle("Rack Calibration Fix")
        
        self.init_ui()
    
    def init_ui(self):
        # Create layouts
        main_layout = QtWidgets.QVBoxLayout(self)
        
        # Group box for left calibration
        left_group = QtWidgets.QGroupBox("Rack Position Left")
        left_layout = QtWidgets.QFormLayout()
        self.left_x_spin = QtWidgets.QSpinBox()
        self.left_y_spin = QtWidgets.QSpinBox()
        self.left_z_spin = QtWidgets.QSpinBox()
        for spin in (self.left_x_spin, self.left_y_spin, self.left_z_spin):
            spin.setRange(-100000, 100000)
        left_layout.addRow("X:", self.left_x_spin)
        left_layout.addRow("Y:", self.left_y_spin)
        left_layout.addRow("Z:", self.left_z_spin)
        left_group.setLayout(left_layout)
        
        # Group box for right calibration
        right_group = QtWidgets.QGroupBox("Rack Position Right")
        right_layout = QtWidgets.QFormLayout()
        self.right_x_spin = QtWidgets.QSpinBox()
        self.right_y_spin = QtWidgets.QSpinBox()
        self.right_z_spin = QtWidgets.QSpinBox()
        for spin in (self.right_x_spin, self.right_y_spin, self.right_z_spin):
            spin.setRange(-100000, 100000)
        right_layout.addRow("X:", self.right_x_spin)
        right_layout.addRow("Y:", self.right_y_spin)
        right_layout.addRow("Z:", self.right_z_spin)
        right_group.setLayout(right_layout)
        
        # Populate with current calibration values if available.
        left_calib = self.rack_model.get_calibration_by_name("rack_position_Left")
        right_calib = self.rack_model.get_calibration_by_name("rack_position_Right")
        if left_calib is not None:
            self.left_x_spin.setValue(left_calib.get("X", 0))
            self.left_y_spin.setValue(left_calib.get("Y", 0))
            self.left_z_spin.setValue(left_calib.get("Z", 0))
        if right_calib is not None:
            self.right_x_spin.setValue(right_calib.get("X", 0))
            self.right_y_spin.setValue(right_calib.get("Y", 0))
            self.right_z_spin.setValue(right_calib.get("Z", 0))
        
        # Save button at the bottom
        btn_save = QtWidgets.QPushButton("Save")
        btn_save.clicked.connect(self.save_calibrations)
        
        # Add widgets to the main layout
        main_layout.addWidget(left_group)
        main_layout.addWidget(right_group)
        main_layout.addStretch()
        main_layout.addWidget(btn_save)
    
    def save_calibrations(self):
        # Retrieve values from spinboxes
        left_coords = {
            'X': self.left_x_spin.value(),
            'Y': self.left_y_spin.value(),
            'Z': self.left_z_spin.value()
        }
        right_coords = {
            'X': self.right_x_spin.value(),
            'Y': self.right_y_spin.value(),
            'Z': self.right_z_spin.value()
        }
        # Set temporary calibration data in the rack_model
        self.rack_model.set_calibration_position("rack_position_Left", left_coords)
        self.rack_model.set_calibration_position("rack_position_Right", right_coords)
        # Update calibration data (store temp calibrations, save to file, apply calibrations)
        self.rack_model.update_calibration_data()
        # Close dialog
        self.accept()


class CalibrationVerdictDialog(QtWidgets.QDialog):
    """
    Operator verdict dialog shown after each calibration process run.
    """

    def __init__(self, parent=None, *, process_name: str = "", default_outcome: str = "success", error_message: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Calibration Verdict")
        self.resize(560, 360)

        layout = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel(f"Process: {process_name or 'unknown'}")
        header.setWordWrap(True)
        layout.addWidget(header)

        form = QtWidgets.QFormLayout()
        self.outcome_combo = QtWidgets.QComboBox()
        self.outcome_combo.addItem("success")
        self.outcome_combo.addItem("failed")
        self.outcome_combo.addItem("unknown")
        idx = self.outcome_combo.findText(str(default_outcome or "unknown"))
        self.outcome_combo.setCurrentIndex(max(0, idx))

        self.failure_summary_edit = QtWidgets.QLineEdit()
        self.suspected_cause_edit = QtWidgets.QLineEdit()
        self.notes_edit = QtWidgets.QTextEdit()
        self.notes_edit.setPlaceholderText("Optional notes about behavior, observations, and next steps.")

        if error_message:
            self.failure_summary_edit.setText(str(error_message))

        form.addRow("Outcome:", self.outcome_combo)
        form.addRow("Failure Summary:", self.failure_summary_edit)
        form.addRow("Suspected Cause:", self.suspected_cause_edit)
        form.addRow("Notes:", self.notes_edit)
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        ok_btn = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        if ok_btn is not None:
            ok_btn.setText("Save Verdict")
        cancel_btn = buttons.button(QtWidgets.QDialogButtonBox.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("Skip")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_verdict_payload(self):
        return {
            "outcome": self.outcome_combo.currentText().strip().lower(),
            "failure_summary": self.failure_summary_edit.text().strip(),
            "suspected_cause": self.suspected_cause_edit.text().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
        }


class StreamCaptureMassEntryDialog(QtWidgets.QDialog):
    def __init__(self, parent, *, controller, model):
        super().__init__(parent)
        self.controller = controller
        self.model = model
        self._shortcut_handles = []
        self._app_event_filter_installed = False

        self.setWindowTitle("Stream Capture Mass Entry")
        self.setModal(True)
        self.resize(460, 320)
        self.setFocusPolicy(Qt.StrongFocus)

        layout = QtWidgets.QVBoxLayout(self)

        self.status_label = QtWidgets.QLabel(
            "Measure the waste tube mass, inspect the printer head state, and complete the session."
        )
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.summary_label = QtWidgets.QLabel("Session: -")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.shortcut_hint_label = QtWidgets.QLabel(
            "Available shortcuts: 1/2/3/4, z/x/c/v/t, =, -"
        )
        self.shortcut_hint_label.setWordWrap(True)
        layout.addWidget(self.shortcut_hint_label)

        form = QtWidgets.QFormLayout()
        self.ending_mass_spin = QtWidgets.QDoubleSpinBox()
        self.ending_mass_spin.setDecimals(4)
        self.ending_mass_spin.setRange(-100000.0, 100000.0)
        self.ending_mass_spin.setSingleStep(0.01)
        self.ending_mass_spin.setValue(0.0)
        self.ending_mass_spin.setKeyboardTracking(False)
        form.addRow("Ending Mass (mg):", self.ending_mass_spin)
        layout.addLayout(form)

        button_row = QtWidgets.QHBoxLayout()
        self.discard_button = QtWidgets.QPushButton("Discard Run")
        self.discard_button.setMinimumHeight(32)
        self.discard_button.clicked.connect(self._discard)
        button_row.addWidget(self.discard_button)

        self.complete_button = QtWidgets.QPushButton("Save Row And Return To Camera")
        self.complete_button.setMinimumHeight(32)
        self.complete_button.clicked.connect(self._complete)
        button_row.addWidget(self.complete_button)
        layout.addLayout(button_row)

        self._install_shortcuts()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._app_event_filter_installed = True

    def _install_shortcuts(self):
        for key_sequence, callback in (
            ("1", lambda: self.controller.set_relative_refuel_pressure(-1, manual=True)),
            ("2", lambda: self.controller.set_relative_refuel_pressure(-0.1, manual=True)),
            ("3", lambda: self.controller.set_relative_refuel_pressure(0.1, manual=True)),
            ("4", lambda: self.controller.set_relative_refuel_pressure(1, manual=True)),
            ("z", lambda: self.controller.refuel_only(20)),
            ("x", lambda: self.controller.refuel_only(5)),
            ("c", lambda: self.controller.print_only(5)),
            ("v", lambda: self.controller.print_only(20)),
            ("t", lambda: self.controller.print_droplets(20)),
            ("=", lambda: self._adjust_refuel_pulse_width(500)),
            ("-", lambda: self._adjust_refuel_pulse_width(-500)),
        ):
            shortcut = QShortcut(QKeySequence(key_sequence), self, activated=callback)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            self._shortcut_handles.append(shortcut)

    def _adjust_refuel_pulse_width(self, delta: int):
        getter = getattr(getattr(self.model, "machine_model", None), "get_refuel_pulse_width", None)
        try:
            current = int(getter()) if callable(getter) else int(getattr(self.model.machine_model, "refuel_pulse_width", 0))
        except Exception:
            current = 0
        target = max(0, int(current) + int(delta))
        self.controller.set_refuel_pulse_width(target, manual=True)

    def update_state(self, state: dict, *, rep_value: int, notes: str):
        status_message = str(state.get("status_message") or "")
        dataset_run_id = str(state.get("dataset_run_id") or state.get("timecourse_run_id") or "-")
        capture_mode = str(state.get("capture_mode") or "timecourse")
        capture_process = str(state.get("dataset_process_name") or state.get("capture_process_name") or "-")
        printed_count = state.get("printed_capture_count")
        background_count = state.get("background_capture_count")
        flow_rate = state.get("flow_rate_nl_per_us")
        tail_start = state.get("tail_start_delay_from_emergence_us")
        predicted_duration = state.get("predicted_stream_duration_us")
        predicted_volume = state.get("predicted_volume_nl")
        segmented_tail_start = state.get("segmented_tail_start_delay_from_emergence_us")
        segmented_predicted_duration = state.get("segmented_predicted_stream_duration_us")
        segmented_predicted_volume = state.get("segmented_predicted_volume_nl")
        segmented_volume_delta = state.get("segmented_predicted_volume_delta_from_runtime_nl")
        self.status_label.setText(status_message or "Enter ending mass and inspect the printer head.")
        summary_text = (
            f"Session: {state.get('session_id') or '-'}\n"
            f"Capture Run: {dataset_run_id}\n"
            f"Mode: {capture_mode} | Process: {capture_process}\n"
            f"Num printed: {printed_count if printed_count is not None else '-'} | "
            f"Background captures: {background_count if background_count is not None else '-'}\n"
            f"Rep: {int(rep_value)} | Notes: {notes or '-'}"
        )
        if capture_mode == "online_stream":
            summary_text += (
                "\n"
                f"Flow rate: {flow_rate if flow_rate is not None else '-'} nL/us | "
                f"Tail start: {tail_start if tail_start is not None else '-'} us | "
                f"Duration: {predicted_duration if predicted_duration is not None else '-'} us | "
                f"Volume: {predicted_volume if predicted_volume is not None else '-'} nL"
            )
            if any(
                value is not None
                for value in (
                    segmented_tail_start,
                    segmented_predicted_duration,
                    segmented_predicted_volume,
                )
            ):
                summary_text += (
                    "\n"
                    f"Segmented tail: {segmented_tail_start if segmented_tail_start is not None else '-'} us | "
                    f"Segmented duration: {segmented_predicted_duration if segmented_predicted_duration is not None else '-'} us | "
                    f"Segmented volume: {segmented_predicted_volume if segmented_predicted_volume is not None else '-'} nL"
                )
                if segmented_volume_delta is not None:
                    summary_text += f" | Delta: {segmented_volume_delta} nL"
        self.summary_label.setText(summary_text)
        ending_mass = state.get("ending_mass_mg")
        if ending_mass is not None and not self._mass_editor_has_focus():
            self.ending_mass_spin.setValue(float(ending_mass))

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self.complete_button.setFocus(Qt.OtherFocusReason))

    def closeEvent(self, event):
        self._remove_app_event_filter()
        super().closeEvent(event)

    def _remove_app_event_filter(self):
        if not self._app_event_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._app_event_filter_installed = False

    def _mass_editor_widgets(self):
        widgets = [self.ending_mass_spin]
        try:
            line_edit = self.ending_mass_spin.lineEdit()
        except Exception:
            line_edit = None
        if line_edit is not None:
            widgets.append(line_edit)
        return tuple(widget for widget in widgets if widget is not None)

    def _mass_editor_has_focus(self):
        focus_widget = QApplication.focusWidget()
        return any(focus_widget is widget for widget in self._mass_editor_widgets())

    def _widget_is_inside_mass_editor(self, obj):
        current = obj
        while current is not None:
            if any(current is widget for widget in self._mass_editor_widgets()):
                return True
            current = getattr(current, "parentWidget", lambda: None)()
        return False

    def _commit_and_clear_mass_editor_focus(self):
        try:
            self.ending_mass_spin.interpretText()
        except Exception:
            pass
        try:
            line_edit = self.ending_mass_spin.lineEdit()
        except Exception:
            line_edit = None
        if line_edit is not None:
            line_edit.clearFocus()
        self.ending_mass_spin.clearFocus()

    def eventFilter(self, obj, event):
        if (
            self.isVisible()
            and event is not None
            and event.type() == QtCore.QEvent.MouseButtonPress
            and self._mass_editor_has_focus()
            and not self._widget_is_inside_mass_editor(obj)
        ):
            self._commit_and_clear_mass_editor_focus()
        return super().eventFilter(obj, event)

    def _complete(self):
        parent = self.parent()
        if parent is None:
            return
        handler = getattr(parent, "_complete_stream_gravimetric_capture_from_popup", None)
        if callable(handler) and handler(float(self.ending_mass_spin.value())):
            self.accept()

    def _discard(self):
        parent = self.parent()
        if parent is None:
            return
        handler = getattr(parent, "_discard_stream_gravimetric_capture_from_popup", None)
        if callable(handler) and handler():
            self.accept()

SUMMARY_RAW_ROW_ROLE = Qt.UserRole + 100
SUMMARY_SORT_ROLE = Qt.UserRole + 101


def _build_summary_muted_brush(color_dict):
    muted_hex = (
        (color_dict or {}).get("muted_text")
        or (color_dict or {}).get("light_gray")
        or (color_dict or {}).get("gray")
        or None
    )
    if muted_hex:
        return QBrush(QColor(muted_hex))
    return QBrush(QColor(255, 255, 255, 150))


def _summary_row_fingerprint(row):
    row = dict(row or {})

    def _normalize(value):
        if value is None:
            return None
        if isinstance(value, bool):
            return bool(value)
        if isinstance(value, (int, float)):
            try:
                return round(float(value), 9)
            except Exception:
                return value
        return str(value)

    return (
        _normalize(row.get("run_id")),
        _normalize(row.get("phase")),
        _normalize(row.get("timestamp")),
        _normalize(row.get("pw_us")),
        _normalize(row.get("pressure_psi")),
        _normalize(row.get("mean_nL")),
    )


def _format_bridge_number(value, decimals=2, *, signed=False, trim=False, suffix=""):
    try:
        number = float(value)
    except Exception:
        return "—"
    fmt = f"{number:+.{decimals}f}" if signed else f"{number:.{decimals}f}"
    if trim:
        sign = ""
        body = fmt
        if signed and fmt[:1] in "+-":
            sign = fmt[0]
            body = fmt[1:]
        body = body.rstrip("0").rstrip(".")
        if not body:
            body = "0"
        fmt = f"{sign}{body}"
    return f"{fmt}{suffix}"


def _format_bridge_error_percent(error_value, target_value):
    try:
        error = float(error_value)
        target = float(target_value)
    except Exception:
        return "—"
    if abs(target) < 1e-12:
        return "+0.00%" if abs(error) < 1e-12 else "—"
    return f"{(error / target) * 100.0:+.2f}%"


def _characterization_table_stylesheet():
    return (
        "QTableView {"
        " border: 1px solid rgba(255, 255, 255, 40);"
        " alternate-background-color: transparent;"
        "}"
        "QTableView::item {"
        " padding: 4px 6px;"
        " border-bottom: 1px solid rgba(255, 255, 255, 22);"
        "}"
        "QHeaderView::section {"
        " padding: 4px 6px;"
        "}"
    )


def _configure_characterization_table_view(table, model):
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(False)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
    table.setMinimumHeight(220)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
    table.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
    table.setStyleSheet(_characterization_table_stylesheet())
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setSectionsClickable(True)
    header.setSortIndicatorShown(False)
    for idx, column in enumerate(model.columns()):
        if column["key"] == "status_label":
            header.setSectionResizeMode(idx, QtWidgets.QHeaderView.Stretch)
        else:
            header.setSectionResizeMode(idx, QtWidgets.QHeaderView.ResizeToContents)


class CharacterizationSummaryTableModel(QtCore.QAbstractTableModel):
    def __init__(self, parent=None, *, include_recorded=False, muted_brush=None, applied_brush=None):
        super().__init__(parent)
        self._include_recorded = bool(include_recorded)
        self._muted_brush = muted_brush or QBrush(QColor(255, 255, 255, 150))
        self._applied_brush = applied_brush or QBrush(QColor(59, 130, 246, 64))
        self._applied_row_fingerprint = None
        self._rows = []
        self._columns = self._build_columns()

    @staticmethod
    def _format_float(value, ndigits):
        if value is None:
            return ""
        try:
            return f"{float(value):.{ndigits}f}"
        except Exception:
            return str(value)

    @staticmethod
    def _display_status(row):
        valid = row.get("valid")
        if valid is True:
            return "Valid"
        if valid is False:
            return "Flagged"
        return ""

    @staticmethod
    def _status_sort_value(row):
        valid = row.get("valid")
        if valid is True:
            return 0
        if valid is False:
            return 1
        return 2

    def _is_applied_row(self, row):
        return (
            self._applied_row_fingerprint is not None
            and _summary_row_fingerprint(row) == self._applied_row_fingerprint
        )

    def _build_columns(self):
        right = int(Qt.AlignRight | Qt.AlignVCenter)
        left = int(Qt.AlignLeft | Qt.AlignVCenter)
        center = int(Qt.AlignCenter)
        columns = [
            {
                "key": "applied_marker",
                "label": "",
                "alignment": center,
                "display": lambda row: "✓" if self._is_applied_row(row) else "",
                "sort": lambda row: 0 if self._is_applied_row(row) else 1,
            },
            {
                "key": "run_no",
                "label": "Run",
                "alignment": right,
                "display": lambda row: "" if row.get("run_no") is None else str(row.get("run_no")),
                "sort": lambda row: row.get("run_no"),
            },
            {
                "key": "phase_label",
                "label": "Source",
                "alignment": left,
                "display": lambda row: str(row.get("phase_label") or ""),
                "sort": lambda row: str(row.get("phase_label") or "").lower(),
            },
        ]
        if self._include_recorded:
            columns.append(
                {
                    "key": "timestamp_display",
                    "label": "Recorded",
                    "alignment": left,
                    "display": lambda row: str(row.get("timestamp_display") or ""),
                    "sort": lambda row: row.get("timestamp") or "",
                }
            )
        columns.extend(
            [
                {
                    "key": "pw_us",
                    "label": "PW (us)",
                    "alignment": right,
                    "display": lambda row: self._format_float(row.get("pw_us"), 0),
                    "sort": lambda row: row.get("pw_us"),
                },
                {
                    "key": "pressure_psi",
                    "label": "Pressure (psi)",
                    "alignment": right,
                    "display": lambda row: self._format_float(row.get("pressure_psi"), 3),
                    "sort": lambda row: row.get("pressure_psi"),
                },
                {
                    "key": "mean_nL",
                    "label": "Volume (nL)",
                    "alignment": right,
                    "display": lambda row: self._format_float(row.get("mean_nL"), 3),
                    "sort": lambda row: row.get("mean_nL"),
                },
                {
                    "key": "cv_pct",
                    "label": "CV (%)",
                    "alignment": right,
                    "display": lambda row: self._format_float(row.get("cv_pct"), 2),
                    "sort": lambda row: row.get("cv_pct"),
                },
                {
                    "key": "status_label",
                    "label": "Status",
                    "alignment": left,
                    "display": self._display_status,
                    "sort": self._status_sort_value,
                },
            ]
        )
        return columns

    def columns(self):
        return self._columns

    def column_index(self, key):
        for idx, column in enumerate(self._columns):
            if column["key"] == key:
                return idx
        raise KeyError(key)

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = [dict(row) for row in (rows or [])]
        self.endResetModel()

    def set_applied_row_fingerprint(self, fingerprint):
        fingerprint = None if fingerprint is None else tuple(fingerprint)
        if fingerprint == self._applied_row_fingerprint:
            return
        self._applied_row_fingerprint = fingerprint
        if self.rowCount() <= 0 or self.columnCount() <= 0:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(self.rowCount() - 1, self.columnCount() - 1)
        self.dataChanged.emit(
            top_left,
            bottom_right,
            [Qt.DisplayRole, Qt.ToolTipRole, Qt.BackgroundRole],
        )

    def raw_row_at(self, row):
        if row < 0 or row >= len(self._rows):
            return None
        return dict(self._rows[row])

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self._columns):
            return self._columns[section]["label"]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = self._columns[index.column()]
        key = column["key"]

        if role in (Qt.DisplayRole, Qt.EditRole):
            return column["display"](row)
        if role == Qt.TextAlignmentRole:
            return column["alignment"]
        if role == SUMMARY_RAW_ROW_ROLE:
            return dict(row)
        if role == SUMMARY_SORT_ROLE:
            return column["sort"](row)
        if role == Qt.ToolTipRole:
            if key == "applied_marker" and self._is_applied_row(row):
                return "Applied to design"
            invalid_reason = row.get("invalid_reason")
            if row.get("valid") is False and invalid_reason:
                return f"Invalid: {invalid_reason}"
            if key == "timestamp_display":
                return str(row.get("timestamp_display") or "")
            return None
        if role == Qt.BackgroundRole and self._applied_row_fingerprint is not None:
            if _summary_row_fingerprint(row) == self._applied_row_fingerprint:
                return self._applied_brush
        if role == Qt.ForegroundRole and row.get("valid") is False:
            return self._muted_brush
        if role == Qt.FontRole and row.get("valid") is False:
            font = QtGui.QFont()
            font.setItalic(True)
            return font
        return None


class CharacterizationSummaryProxyModel(QtCore.QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_run_only = False
        self._valid_only = False
        self._source_filter = "all"

    @staticmethod
    def _normalize_sort_value(value):
        if value is None:
            return (1, "")
        if isinstance(value, bool):
            return (0, int(value))
        if isinstance(value, (int, float)):
            return (0, float(value))
        return (0, str(value).lower())

    def _raw_row(self, source_row):
        model = self.sourceModel()
        if model is None or not hasattr(model, "raw_row_at"):
            return {}
        return model.raw_row_at(source_row) or {}

    def setCurrentRunOnly(self, enabled):
        enabled = bool(enabled)
        if self._current_run_only == enabled:
            return
        self._current_run_only = enabled
        self.invalidateFilter()

    def setValidOnly(self, enabled):
        enabled = bool(enabled)
        if self._valid_only == enabled:
            return
        self._valid_only = enabled
        self.invalidateFilter()

    def setSourceFilter(self, source_key):
        normalized = str(source_key or "all").strip().lower()
        if normalized not in ("all", "sweep", "search", "recheck", "stream"):
            normalized = "all"
        if self._source_filter == normalized:
            return
        self._source_filter = normalized
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        row = self._raw_row(source_row)
        if not row:
            return False
        if self._current_run_only and not row.get("is_focus_run"):
            return False
        if self._valid_only and row.get("valid") is not True:
            return False
        if self._source_filter != "all":
            if str(row.get("phase") or "").strip().lower() != self._source_filter:
                return False
        return True

    def lessThan(self, left, right):
        left_value = left.data(SUMMARY_SORT_ROLE)
        right_value = right.data(SUMMARY_SORT_ROLE)
        return self._normalize_sort_value(left_value) < self._normalize_sort_value(right_value)


class CharacterizationHistoryDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, *, rows=None, muted_brush=None):
        super().__init__(parent)
        self.setWindowTitle("Characterization History")
        self.resize(980, 560)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)
        self.history_current_run_only_checkbox = QtWidgets.QCheckBox("Current run only")
        self.history_current_run_only_checkbox.setChecked(False)
        self.history_valid_only_checkbox = QtWidgets.QCheckBox("Valid only")
        self.history_source_combo = QtWidgets.QComboBox()
        self.history_source_combo.addItem("All", "all")
        self.history_source_combo.addItem("Sweep", "sweep")
        self.history_source_combo.addItem("Search", "search")
        self.history_source_combo.addItem("Recheck", "recheck")
        self.history_source_combo.addItem("Stream", "stream")
        self.history_showing_label = QtWidgets.QLabel("")

        toolbar.addWidget(self.history_current_run_only_checkbox)
        toolbar.addWidget(self.history_valid_only_checkbox)
        toolbar.addWidget(QtWidgets.QLabel("Source:"))
        toolbar.addWidget(self.history_source_combo)
        toolbar.addStretch(1)
        toolbar.addWidget(self.history_showing_label)
        layout.addLayout(toolbar)

        self.history_table = QtWidgets.QTableView()
        self.history_table_model = CharacterizationSummaryTableModel(
            self,
            include_recorded=True,
            muted_brush=muted_brush,
        )
        self.history_table_proxy_model = CharacterizationSummaryProxyModel(self)
        self.history_table_proxy_model.setSourceModel(self.history_table_model)
        self.history_table.setModel(self.history_table_proxy_model)
        _configure_characterization_table_view(self.history_table, self.history_table_model)
        layout.addWidget(self.history_table, 1)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QtWidgets.QDialogButtonBox.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.close)
        layout.addWidget(buttons)

        self.history_current_run_only_checkbox.toggled.connect(self._refresh_filters)
        self.history_valid_only_checkbox.toggled.connect(self._refresh_filters)
        self.history_source_combo.currentIndexChanged.connect(self._refresh_filters)
        self.history_table.horizontalHeader().sectionClicked.connect(self._handle_header_click)

        self._sort_column = self.history_table_model.column_index("timestamp_display")
        self._sort_order = Qt.DescendingOrder
        self.history_table_model.set_rows(rows or [])
        self._refresh_filters()
        self._apply_sort(self._sort_column, self._sort_order)

    def _update_count_label(self):
        visible = self.history_table_proxy_model.rowCount()
        total = self.history_table_model.rowCount()
        noun = "result" if total == 1 else "results"
        self.history_showing_label.setText(f"Showing {visible} of {total} {noun}")

    def _refresh_filters(self):
        self.history_table_proxy_model.setCurrentRunOnly(self.history_current_run_only_checkbox.isChecked())
        self.history_table_proxy_model.setValidOnly(self.history_valid_only_checkbox.isChecked())
        self.history_table_proxy_model.setSourceFilter(self.history_source_combo.currentData())
        self._update_count_label()

    def _apply_sort(self, column, order):
        self._sort_column = column
        self._sort_order = order
        header = self.history_table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(column, order)
        self.history_table_proxy_model.sort(column, order)

    def _handle_header_click(self, section):
        if self._sort_column == section:
            order = Qt.DescendingOrder if self._sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            order = Qt.AscendingOrder
        self._apply_sort(section, order)


class PrinterHeadRecoveryDialog(QtWidgets.QDialog):
    MODE_PULL_BACK = "pull_back"
    MODE_REFILL = "refill"
    PULL_BACK_MIN_PRESSURE_PSI = -1.0
    PULL_BACK_MAX_PRESSURE_PSI = 0.0
    REFILL_MIN_PRESSURE_PSI = 0.0
    REFILL_MAX_PRESSURE_PSI = 5.0
    DEFAULT_PULL_BACK_PRESSURE_PSI = -1.0
    DEFAULT_REFILL_PRESSURE_PSI = 2.0
    DEFAULT_REFILL_PULSE_WIDTH_US = 5000
    DEFAULT_PREP_POSITION_STEPS = 20000
    DEFAULT_PREP_MOVE_HZ = 5000

    def __init__(self, parent, model, controller):
        super().__init__(parent)
        self.model = model
        self.controller = controller
        self._mode = self.MODE_PULL_BACK
        self._entered = False
        self._transitioning = False
        self._restore_queued = False
        self._last_committed_pressure = None
        self._last_committed_pulse_width = None
        self._saved_refuel_pressure = self._read_float_setting(
            ("get_target_refuel_pressure", "get_current_refuel_pressure"),
            default=0.0,
        )
        if self._saved_refuel_pressure is None or self._saved_refuel_pressure < 0:
            self._saved_refuel_pressure = 0.0
        self._saved_refuel_pulse_width = self._read_int_setting(
            ("get_refuel_pulse_width",),
            default=None,
        )

        self.setWindowTitle("Printer Head Recovery")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._build_ui()
        self._setup_shortcuts()
        self._apply_mode_ui(self.MODE_PULL_BACK, enabled=False, set_pressure_default=True)
        QTimer.singleShot(0, self._enter_pull_back_mode)

    def _machine_model(self):
        return getattr(self.model, "machine_model", None)

    def _read_float_setting(self, getter_names, default=None):
        machine_model = self._machine_model()
        for name in getter_names:
            getter = getattr(machine_model, name, None)
            if callable(getter):
                try:
                    return float(getter())
                except Exception:
                    pass
        return default

    def _read_int_setting(self, getter_names, default=None):
        value = self._read_float_setting(getter_names, default=default)
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.mode_label = QtWidgets.QLabel()
        font = self.mode_label.font()
        font.setBold(True)
        self.mode_label.setFont(font)
        layout.addWidget(self.mode_label)

        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        self.pressure_spin = QtWidgets.QDoubleSpinBox()
        self.pressure_spin.setDecimals(2)
        self.pressure_spin.setSingleStep(0.05)
        self._configure_recovery_spinbox(self.pressure_spin, self._commit_pressure_spin)
        form.addRow("Refuel pressure (psi):", self.pressure_spin)

        self.pulse_width_spin = QtWidgets.QSpinBox()
        self.pulse_width_spin.setRange(100, 10000)
        self.pulse_width_spin.setSingleStep(50)
        self.pulse_width_spin.setValue(
            int(self._saved_refuel_pulse_width)
            if self._saved_refuel_pulse_width and self._saved_refuel_pulse_width >= 100
            else 3000
        )
        self._configure_recovery_spinbox(self.pulse_width_spin, self._commit_pulse_width_spin)
        form.addRow("Refuel pulse width (us):", self.pulse_width_spin)

        self.pulse_count_spin = QtWidgets.QSpinBox()
        self.pulse_count_spin.setRange(1, 1000)
        self.pulse_count_spin.setValue(5)
        self.pulse_count_spin.setKeyboardTracking(False)
        form.addRow("Pulse count:", self.pulse_count_spin)
        layout.addLayout(form)

        button_row = QtWidgets.QHBoxLayout()
        self.pulse_button = QtWidgets.QPushButton("Pulse Refuel")
        self.pulse_button.clicked.connect(self._pulse_refuel)
        self.loading_button = QtWidgets.QPushButton("Move to Loading")
        self.loading_button.clicked.connect(self._move_to_loading)
        self.camera_button = QtWidgets.QPushButton("Move to Camera")
        self.camera_button.clicked.connect(self._move_to_camera)
        button_row.addWidget(self.pulse_button)
        button_row.addWidget(self.loading_button)
        button_row.addWidget(self.camera_button)
        layout.addLayout(button_row)

        mode_row = QtWidgets.QHBoxLayout()
        self.switch_to_refill_button = QtWidgets.QPushButton("Switch to Refill")
        self.switch_to_refill_button.clicked.connect(self._switch_to_refill_mode)
        self.switch_to_pull_back_button = QtWidgets.QPushButton("Switch to Pull Back")
        self.switch_to_pull_back_button.clicked.connect(self._switch_to_pull_back_mode)
        mode_row.addWidget(self.switch_to_refill_button)
        mode_row.addWidget(self.switch_to_pull_back_button)
        layout.addLayout(mode_row)

        self.status_label = QtWidgets.QLabel("Preparing Pull Back Mode...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        close_row = QtWidgets.QHBoxLayout()
        close_row.addStretch(1)
        self.restore_close_button = QtWidgets.QPushButton("Restore/Close")
        self.restore_close_button.clicked.connect(self.accept)
        close_row.addWidget(self.restore_close_button)
        layout.addLayout(close_row)

    def _setup_shortcuts(self):
        self.shortcut_refuel_many = QShortcut(QKeySequence("z"), self)
        self.shortcut_refuel_many.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut_refuel_many.activated.connect(lambda: self._pulse_refuel_count(5))

        self.shortcut_refuel_few = QShortcut(QKeySequence("x"), self)
        self.shortcut_refuel_few.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut_refuel_few.activated.connect(lambda: self._pulse_refuel_count(1))

        self.shortcut_pause = QShortcut(QKeySequence("Esc"), self)
        self.shortcut_pause.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut_pause.activated.connect(self._pause_from_escape)

    def _configure_recovery_spinbox(self, spinbox, commit_handler):
        spinbox.setKeyboardTracking(False)
        spinbox.setFocusPolicy(QtCore.Qt.StrongFocus)
        spinbox.editingFinished.connect(commit_handler)

    @staticmethod
    def _set_spinbox_value(spinbox, value):
        blocked = spinbox.blockSignals(True)
        spinbox.setValue(value)
        spinbox.blockSignals(blocked)

    @staticmethod
    def _spinbox_is_being_edited(spinbox):
        line_edit = spinbox.lineEdit() if hasattr(spinbox, "lineEdit") else None
        return spinbox.hasFocus() or (line_edit is not None and line_edit.hasFocus())

    def _clear_spinbox_focus(self):
        for spinbox in (self.pressure_spin, self.pulse_width_spin, self.pulse_count_spin):
            if self._spinbox_is_being_edited(spinbox):
                spinbox.clearFocus()

    def _apply_mode_ui(self, mode, enabled, set_pressure_default=False, set_pulse_default=False):
        self._mode = mode
        if mode == self.MODE_PULL_BACK:
            self.mode_label.setText("Pull Back Mode")
            self.pressure_spin.setRange(self.PULL_BACK_MIN_PRESSURE_PSI, self.PULL_BACK_MAX_PRESSURE_PSI)
            if set_pressure_default:
                self._set_spinbox_value(self.pressure_spin, self.DEFAULT_PULL_BACK_PRESSURE_PSI)
        else:
            self.mode_label.setText("Refill Mode")
            self.pressure_spin.setRange(self.REFILL_MIN_PRESSURE_PSI, self.REFILL_MAX_PRESSURE_PSI)
            if set_pressure_default:
                self._set_spinbox_value(self.pressure_spin, self.DEFAULT_REFILL_PRESSURE_PSI)
            if set_pulse_default:
                self._set_spinbox_value(self.pulse_width_spin, self.DEFAULT_REFILL_PULSE_WIDTH_US)
        self._set_controls_enabled(enabled)

    def _set_controls_enabled(self, enabled):
        enabled = bool(enabled) and not self._restore_queued and not self._transitioning
        for widget in (
            self.pressure_spin,
            self.pulse_width_spin,
            self.pulse_count_spin,
            self.pulse_button,
            self.loading_button,
        ):
            widget.setEnabled(enabled)
        self.camera_button.setEnabled(enabled and self._mode == self.MODE_REFILL)
        self.switch_to_refill_button.setEnabled(enabled and self._mode == self.MODE_PULL_BACK)
        self.switch_to_pull_back_button.setEnabled(enabled and self._mode == self.MODE_REFILL)

    def _enter_pull_back_mode(self):
        if self._restore_queued:
            return
        self._transitioning = True
        self._entered = False
        self._apply_mode_ui(self.MODE_PULL_BACK, enabled=False, set_pressure_default=True)
        self.status_label.setText("Preparing Pull Back Mode...")
        enter = getattr(self.controller, "enter_refuel_vacuum_mode", None)
        if not callable(enter):
            self.status_label.setText("Pull Back Mode is unavailable.")
            return
        result = enter(
            target_psi=float(self.pressure_spin.value()),
            prep_position_steps=self.DEFAULT_PREP_POSITION_STEPS,
            move_hz=self.DEFAULT_PREP_MOVE_HZ,
            handler=self._on_pull_back_entered,
            manual=True,
        )
        if result is False:
            self.status_label.setText("Failed to queue Pull Back Mode.")

    def _on_pull_back_entered(self):
        if self._restore_queued:
            return
        self._transitioning = False
        self._entered = True
        self._last_committed_pressure = float(self.pressure_spin.value())
        self._last_committed_pulse_width = int(self.pulse_width_spin.value())
        self._set_controls_enabled(True)
        self.status_label.setText("Pull Back Mode active.")

    def _switch_to_refill_mode(self):
        if self._restore_queued or self._mode == self.MODE_REFILL:
            return
        self._transitioning = True
        self._entered = False
        self._apply_mode_ui(
            self.MODE_REFILL,
            enabled=False,
            set_pressure_default=True,
            set_pulse_default=True,
        )
        self.status_label.setText("Preparing Refill Mode...")
        exit_mode = getattr(self.controller, "exit_refuel_vacuum_mode", None)
        pulse_width = getattr(self.controller, "set_refuel_pulse_width", None)
        if not callable(exit_mode) or not callable(pulse_width):
            self.status_label.setText("Refill Mode is unavailable.")
            return
        exit_result = exit_mode(self.DEFAULT_REFILL_PRESSURE_PSI, manual=True)
        pulse_result = pulse_width(
            self.DEFAULT_REFILL_PULSE_WIDTH_US,
            handler=self._on_refill_entered,
            manual=True,
        )
        if exit_result is False or pulse_result is False:
            self.status_label.setText("Failed to queue Refill Mode.")

    def _on_refill_entered(self):
        if self._restore_queued:
            return
        self._transitioning = False
        self._entered = True
        self._last_committed_pressure = float(self.pressure_spin.value())
        self._last_committed_pulse_width = int(self.pulse_width_spin.value())
        self._set_controls_enabled(True)
        self.status_label.setText("Refill Mode active.")

    def _switch_to_pull_back_mode(self):
        if self._restore_queued or self._mode == self.MODE_PULL_BACK:
            return
        self._enter_pull_back_mode()

    def _commit_pressure_spin(self):
        if not self._entered or self._transitioning or self._restore_queued:
            return
        self.pressure_spin.interpretText()
        value = float(self.pressure_spin.value())
        if self._last_committed_pressure is not None and abs(value - self._last_committed_pressure) < 0.0005:
            return
        if self._mode == self.MODE_PULL_BACK:
            setter = getattr(self.controller, "set_refuel_vacuum_pressure", None)
        else:
            setter = getattr(self.controller, "set_absolute_refuel_pressure", None)
        if callable(setter) and setter(value, manual=True) is not False:
            self._last_committed_pressure = value
            self.status_label.setText(f"Queued {self.mode_label.text()} pressure {value:.2f} psi.")
        else:
            self.status_label.setText(f"Failed to queue {self.mode_label.text()} pressure.")
        self._clear_spinbox_focus()

    def _commit_pulse_width_spin(self):
        if not self._entered or self._transitioning or self._restore_queued:
            return
        self.pulse_width_spin.interpretText()
        value = int(self.pulse_width_spin.value())
        if self._last_committed_pulse_width is not None and value == self._last_committed_pulse_width:
            return
        setter = getattr(self.controller, "set_refuel_pulse_width", None)
        if callable(setter) and setter(value, manual=True) is not False:
            self._last_committed_pulse_width = value
            self.status_label.setText(f"Queued {self.mode_label.text()} pulse width {value} us.")
        else:
            self.status_label.setText("Failed to queue refuel pulse width.")
        self._clear_spinbox_focus()

    def _commit_setting_edits(self):
        for spinbox in (self.pressure_spin, self.pulse_width_spin, self.pulse_count_spin):
            spinbox.interpretText()
        self._commit_pressure_spin()
        self._commit_pulse_width_spin()

    def _pulse_refuel(self):
        self._pulse_refuel_count(int(self.pulse_count_spin.value()))

    def _pulse_refuel_count(self, count):
        if not self._entered or self._transitioning or self._restore_queued:
            return
        self._commit_setting_edits()
        pulse = getattr(self.controller, "refuel_only", None)
        if callable(pulse):
            pulse(int(count), manual=True)
            self.status_label.setText(f"Queued {int(count)} refuel pulses in {self.mode_label.text()}.")

    def _move_to_loading(self):
        mover = getattr(self.controller, "move_to_location", None)
        if callable(mover) and mover("loading", manual=True) is not False:
            self.status_label.setText("Queued move to loading.")
        else:
            self.status_label.setText("Failed to queue move to loading.")

    def _move_to_camera(self):
        if self._mode != self.MODE_REFILL:
            return
        mover = getattr(self.controller, "move_to_location", None)
        if callable(mover) and mover("camera", manual=True) is not False:
            self.status_label.setText("Queued move to camera.")
        else:
            self.status_label.setText("Failed to queue move to camera.")

    def _queue_restore(self):
        if self._restore_queued:
            return
        self._restore_queued = True
        self._transitioning = True
        self._entered = False
        self._set_controls_enabled(False)
        if self._saved_refuel_pulse_width is not None:
            setter = getattr(self.controller, "set_refuel_pulse_width", None)
            if callable(setter):
                setter(int(self._saved_refuel_pulse_width), manual=True)
        exit_mode = getattr(self.controller, "exit_refuel_vacuum_mode", None)
        if callable(exit_mode):
            exit_mode(float(self._saved_refuel_pressure), manual=True)
        self.status_label.setText("Queued Printer Head Recovery restore.")

    def _pause_from_escape(self):
        parent = self.parent()
        main_window = getattr(parent, "main_window", None)
        pause = getattr(main_window, "pause_machine", None)
        if callable(pause):
            pause()
            self.status_label.setText(
                "Pause requested. Printer Head Recovery remains open until Restore/Close."
            )
            return
        pause_commands = getattr(self.controller, "pause_commands", None)
        if callable(pause_commands):
            pause_commands()
            self.status_label.setText(
                "Pause requested. Printer Head Recovery remains open until Restore/Close."
            )
        else:
            self.status_label.setText("Pause shortcut is unavailable in Printer Head Recovery.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._pause_from_escape()
            event.accept()
            return
        super().keyPressEvent(event)

    def accept(self):
        self._queue_restore()
        super().accept()

    def reject(self):
        self._queue_restore()
        super().reject()

    def closeEvent(self, event):
        self._queue_restore()
        super().closeEvent(event)


class DropletImagingDialog(QtWidgets.QDialog):
    REFUEL_LEVEL_CHART_WINDOW_SAMPLES = 100
    REFUEL_LEVEL_CHART_FALLBACK_HEIGHT_PX = 100.0

    _quick_controls_expanded_default = False
    _info_panel_section_default_states = {
        "summary": True,
        "bridge": True,
        "recommendation": False,
        "machine_position": False,
        "status": True,
    }
    _STREAM_CAPTURE_READ_CAMERA_DISARM_STATUSES = {
        "awaiting_mass",
        "awaiting_mass_entry",
        "pending_gripper_restore",
        "restoring_gripper_refresh",
    }

    def __init__(self, main_window, model, controller, service_mode=False, initial_tab=None):
        super().__init__()
        print('\n---Created new droplet imaging dialog---\n')
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.droplet_camera_model = model.droplet_camera_model
        self.refuel_camera_model = getattr(model, "refuel_camera_model", None)
        self.controller = controller
        self.service_mode = bool(service_mode)
        self.initial_tab = str(initial_tab or "").strip().lower()

        # Hardware bounds for pressures (used globally)
        try:
            self.hw_lo, self.hw_hi = self.model.machine_model.get_print_pressure_bounds()
        except Exception:
            self.hw_lo, self.hw_hi = 0.10, 5.00

        self.shortcut_manager = ShortcutManager(self)
        self.manual_flash_shortcut = None
        self.setup_shortcuts()

        self.flash_active = False
        self.saving_active = False
        self.analysis_active = False
        self.start_droplet_camera()
        self._read_camera_stream_armed = False
        self._read_camera_stream_reconciled = False

        # Timer for periodic image capture
        self.camera_timer = QTimer(self)
        self.camera_timer.timeout.connect(self.capture_image)
        self.capturing = False
        self.refuel_monitor_interval_ms = 1000
        self.refuel_monitor_timer = QTimer(self)
        self.refuel_monitor_timer.setInterval(self.refuel_monitor_interval_ms)
        self.refuel_monitor_timer.timeout.connect(self._capture_refuel_monitor_sample)
        self.refuel_panel_refresh_timer = QTimer(self)
        self.refuel_panel_refresh_timer.setSingleShot(True)
        self.refuel_panel_refresh_timer.timeout.connect(self._run_refuel_level_panel_refresh)
        self._refuel_monitor_camera_started = False
        self._refuel_first_sample_pending = False
        self._last_refuel_panel_auto_refresh_monotonic = None
        self._refuel_panel_rendered_version = None
        self._refuel_panel_pending_version = None
        self._refuel_level_chart_full_scale_px = None
        self._last_refuel_named_calibration_payload = {}

        self._bridge_preview_payload = None
        self._memory_recommendation_preview = None
        self._memory_recommendation_logged_fingerprint = None
        self._memory_recommendation_refresh_active = False
        self._manual_focus_frame_active_spinbox = None
        self._manual_spinbox_committers = {}
        self._manual_spinbox_focus_targets = {}
        self._manual_spinbox_syncing = set()
        self._manual_spinbox_typed_drafts = {}
        self._managed_manual_spinboxes = []
        self._manual_controls_locked = False
        self._calibration_action_buttons = {}
        self._calibration_action_defaults = {}
        self._startup_focus_initialized = False
        self._stream_capture_last_status = None
        self._stream_capture_mass_dialog = None
        self._stream_capture_dialog_closing = False
        self._stream_capture_gripper_preamble_attempted = False
        self._stream_capture_gripper_restore_attempted = False
        self._stream_capture_loading_move_attempted = False
        self._stream_capture_camera_return_attempted = False
        self._stream_calibration_sequence_gripper_preamble_attempted = False
        self._stream_calibration_sequence_gripper_restore_attempted = False
        self._droplet_calibration_sequence_gripper_preamble_attempted = False
        self._droplet_calibration_sequence_gripper_restore_attempted = False
        self._printer_head_recovery_dialog = None
        self._optics_session_active = False
        self._optics_session_dir = None
        self._optics_rejected_filenames = []
        self._optics_last_analysis = None
        self._capture_request_pending = False
        try:
            self.model.calibration_manager.clear_calibration_memory_ui_recommendation_state()
        except Exception:
            pass

        self.setWindowTitle("Droplet Imaging")
        self.resize(1600, 1000)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        # =========================
        # Main three-column layout
        # =========================
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(10)
        self.manual_edit_focus_frame = QtWidgets.QFocusFrame(self)
        self.manual_edit_focus_frame.setFocusPolicy(QtCore.Qt.NoFocus)
        self.manual_edit_focus_frame.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.manual_edit_focus_frame.setStyleSheet(
            "QFocusFrame {"
            f" border: 1px solid {self.color_dict.get('light_blue', '#3b82f6')};"
            " border-radius: 2px;"
            " background: transparent;"
            "}"
        )
        self.manual_edit_focus_frame.hide()

        # ---------- RIGHT RESULTS PANEL (fixed width): memory + summary ----------
        self.info_panel = QtWidgets.QWidget()
        info_panel_v = QtWidgets.QVBoxLayout(self.info_panel)
        info_panel_v.setContentsMargins(6, 6, 6, 6)
        info_panel_v.setSpacing(8)
        self.info_panel_scroll = QtWidgets.QScrollArea()
        self.info_panel_scroll.setWidgetResizable(True)
        self.info_panel_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.info_panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.info_panel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.info_panel_scroll.setWidget(self.info_panel)

        # ---------- LEFT CONTROL PANEL (fixed width): workflow tabs + run options ----------
        self.control_panel_scroll = QtWidgets.QScrollArea()
        self.control_panel_scroll.setWidgetResizable(True)
        self.control_panel_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.control_panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.control_panel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.control_panel = QtWidgets.QWidget()
        control_panel_v = QtWidgets.QVBoxLayout(self.control_panel)
        control_panel_v.setContentsMargins(6, 6, 6, 6)
        control_panel_v.setSpacing(8)
        self.control_panel_scroll.setWidget(self.control_panel)

        self.reagent_title_widget = QtWidgets.QWidget()
        reagent_title_v = QtWidgets.QVBoxLayout(self.reagent_title_widget)
        reagent_title_v.setContentsMargins(0, 0, 0, 0)
        reagent_title_v.setSpacing(2)
        self.reagent_title_label = QtWidgets.QLabel("No reagent selected")
        self.reagent_title_label.setWordWrap(True)
        self.reagent_title_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.reagent_stock_label = QtWidgets.QLabel("Stock concentration(s): —")
        self.reagent_stock_label.setWordWrap(True)
        self.reagent_stock_label.setStyleSheet(
            f"color: {self.color_dict.get('muted_text', self.color_dict.get('light_gray', '#9ca3af'))};"
            " font-size: 12px;"
            " font-weight: 500;"
        )
        reagent_title_v.addWidget(self.reagent_title_label)
        reagent_title_v.addWidget(self.reagent_stock_label)

        quick_controls_expanded = self._get_saved_acquisition_controls_expanded()
        (
            self.acquisition_controls_section,
            self.acquisition_controls_toggle,
            self.acquisition_controls_content,
            acquisition_grid,
        ) = self._create_collapsible_section(
            "Acquisition Controls",
            expanded=quick_controls_expanded,
        )
        self.acquisition_controls_toggle.toggled.connect(self._set_acquisition_controls_expanded)
        self._set_acquisition_controls_expanded(quick_controls_expanded)

        self.calibration_tabs = QtWidgets.QTabWidget()
        self.droplet_tab = QtWidgets.QWidget()
        self.stream_tab = QtWidgets.QWidget()
        self.debug_tab = QtWidgets.QWidget()
        self.optics_tab = QtWidgets.QWidget()
        for tab_page in (self.droplet_tab, self.stream_tab, self.optics_tab):
            tab_layout = QtWidgets.QVBoxLayout(tab_page)
            tab_layout.setContentsMargins(10, 10, 10, 0)
            tab_layout.setSpacing(8)
        debug_tab_layout = QtWidgets.QVBoxLayout(self.debug_tab)
        debug_tab_layout.setContentsMargins(0, 0, 0, 0)
        debug_tab_layout.setSpacing(0)
        self.calibration_tabs.addTab(self.droplet_tab, "Droplet")
        self.calibration_tabs.addTab(self.stream_tab, "Stream")
        self.calibration_tabs.addTab(self.debug_tab, "Debug / Specialty")
        self.calibration_tabs.addTab(self.optics_tab, "Optics")
        self.calibration_tabs.currentChanged.connect(self._refresh_calibration_tab_lock_state)
        self.calibration_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        # --- Debug tab: Manual Controls ---
        self.manual_group = QtWidgets.QGroupBox("Manual Controls")
        manual_grid = QtWidgets.QGridLayout(self.manual_group)
        manual_grid.setHorizontalSpacing(8)
        manual_grid.setVerticalSpacing(6)
        row = 0

        # Counters
        self.flash_count_label = QtWidgets.QLabel("Flashes: 0")
        self.trigger_count_label = QtWidgets.QLabel("Triggers: 0")
        self.flash_safety_label = QtWidgets.QLabel("Flash session disarmed.")
        self.flash_safety_label.setWordWrap(True)
        manual_grid.addWidget(self.flash_count_label,   row, 0, 1, 2); row += 1
        manual_grid.addWidget(self.trigger_count_label, row, 0, 1, 2); row += 1
        manual_grid.addWidget(self.flash_safety_label, row, 0, 1, 2); row += 1

        # Flash duration
        self.flash_duration_label = QtWidgets.QLabel("Flash Duration (µs):")
        self.flash_duration_spinbox = QtWidgets.QSpinBox()
        self.flash_duration_spinbox.setRange(0, 10000)
        self.flash_duration_spinbox.setSingleStep(1000)
        self.flash_duration_spinbox.setValue(self.droplet_camera_model.flash_duration)
        manual_grid.addWidget(self.flash_duration_label,  row, 0)
        manual_grid.addWidget(self.flash_duration_spinbox,row, 1); row += 1

        # Flash delay
        self.flash_delay_label = QtWidgets.QLabel("Flash Delay (µs):")
        self.flash_delay_spinbox = QtWidgets.QSpinBox()
        self.flash_delay_spinbox.setRange(0, 50000)
        self.flash_delay_spinbox.setSingleStep(100)
        self.flash_delay_spinbox.setValue(self.droplet_camera_model.flash_delay)
        manual_grid.addWidget(self.flash_delay_label,  row, 0)
        manual_grid.addWidget(self.flash_delay_spinbox,row, 1); row += 1

        # Number of droplets (pre-imaging)
        self.num_droplets_label = QtWidgets.QLabel("Number of droplets:")
        self.num_droplets_spinbox = QtWidgets.QSpinBox()
        self.num_droplets_spinbox.setRange(0, 20)
        self.num_droplets_spinbox.setSingleStep(1)
        self.num_droplets_spinbox.setValue(self.droplet_camera_model.num_droplets)
        manual_grid.addWidget(self.num_droplets_label,  row, 0)
        manual_grid.addWidget(self.num_droplets_spinbox,row, 1); row += 1

        # Print pulse width
        self.print_pulse_width_label = QtWidgets.QLabel("Print Pulse Width (µs):")
        self.print_pulse_width_spinbox = QtWidgets.QSpinBox()
        self.print_pulse_width_spinbox.setRange(0, 10000)
        self.print_pulse_width_spinbox.setSingleStep(50)
        self.print_pulse_width_spinbox.setValue(self.model.machine_model.get_print_pulse_width())
        manual_grid.addWidget(self.print_pulse_width_label,  row, 0)
        manual_grid.addWidget(self.print_pulse_width_spinbox,row, 1); row += 1

        # Exposure time
        self.exposure_time_label = QtWidgets.QLabel("Exposure Time (µs):")
        self.exposure_time_spinbox = QtWidgets.QSpinBox()
        self.exposure_time_spinbox.setRange(0, 1_000_000)
        self.exposure_time_spinbox.setSingleStep(2000)
        self.exposure_time_spinbox.setValue(self.droplet_camera_model.exposure_time)
        manual_grid.addWidget(self.exposure_time_label,  row, 0)
        manual_grid.addWidget(self.exposure_time_spinbox,row, 1); row += 1
        self._register_manual_spinbox(self.flash_duration_spinbox, self.set_flash_duration)
        self._register_manual_spinbox(self.flash_delay_spinbox, self.set_flash_delay)
        self._register_manual_spinbox(self.num_droplets_spinbox, self.set_imaging_droplets)
        self._register_manual_spinbox(self.print_pulse_width_spinbox, self.handle_print_pulse_width_change)
        self._register_manual_spinbox(self.exposure_time_spinbox, self.set_exposure_time)

        # Trigger flash
        self.flash_button = QtWidgets.QPushButton("Trigger Flash")
        self.flash_button.clicked.connect(self.toggle_flash)
        manual_grid.addWidget(self.flash_button, row, 0, 1, 2); row += 1

        self.benchmark_profile_button = QtWidgets.QPushButton("Apply Benchmark Capture Profile")
        self.benchmark_profile_button.clicked.connect(self.apply_benchmark_capture_profile)
        manual_grid.addWidget(self.benchmark_profile_button, row, 0, 1, 2); row += 1

        manual_grid.removeWidget(self.flash_delay_label)
        manual_grid.removeWidget(self.flash_delay_spinbox)
        manual_grid.removeWidget(self.print_pulse_width_label)
        manual_grid.removeWidget(self.print_pulse_width_spinbox)
        manual_grid.removeWidget(self.flash_button)

        acquisition_grid.addWidget(self.flash_delay_label, 0, 0)
        acquisition_grid.addWidget(self.flash_delay_spinbox, 0, 1)
        acquisition_grid.addWidget(self.print_pulse_width_label, 1, 0)
        acquisition_grid.addWidget(self.print_pulse_width_spinbox, 1, 1)
        acquisition_grid.addWidget(self.flash_button, 2, 0, 1, 2)

        self._quick_manual_lock_widgets = (
            self.flash_delay_spinbox,
            self.print_pulse_width_spinbox,
            self.flash_button,
        )
        self._debug_manual_lock_widgets = (
            self.flash_duration_spinbox,
            self.num_droplets_spinbox,
            self.exposure_time_spinbox,
            self.benchmark_profile_button,
        )
        self._manual_lock_widgets = self._quick_manual_lock_widgets + self._debug_manual_lock_widgets

        # --- Droplet tab: standard droplet workflow ---
        self.calib_group = QtWidgets.QGroupBox("Droplet Calibration")
        calib_grid = QtWidgets.QGridLayout(self.calib_group)
        calib_grid.setHorizontalSpacing(8)
        calib_grid.setVerticalSpacing(6)
        crow = 0

        self.prime_head_button = QtWidgets.QPushButton("Prime Printer Head")
        self.prime_head_button.clicked.connect(self.toggle_start_head_prime_calibration)
        self._register_calibration_action_button("head_prime", self.prime_head_button)
        calib_grid.addWidget(self.prime_head_button, crow, 0, 1, 2); crow += 1

        self.calibrate_nozzle_button = QtWidgets.QPushButton("Calibrate Nozzle Position")
        self.calibrate_nozzle_button.clicked.connect(self.toggle_start_nozzle_calibration)
        self._register_calibration_action_button("nozzle_position", self.calibrate_nozzle_button)
        calib_grid.addWidget(self.calibrate_nozzle_button, crow, 0, 1, 2); crow += 1

        self.calibrate_focus_button = QtWidgets.QPushButton("Calibrate Nozzle Focus")
        self.calibrate_focus_button.clicked.connect(self.toggle_start_focus_calibration)
        self._register_calibration_action_button("nozzle_focus", self.calibrate_focus_button)
        calib_grid.addWidget(self.calibrate_focus_button, crow, 0, 1, 2); crow += 1

        self.calibrate_emergence_button = QtWidgets.QPushButton("Calibrate Droplet Emergence")
        self.calibrate_emergence_button.clicked.connect(self.toggle_start_emergence_calibration)
        self._register_calibration_action_button("droplet_emergence", self.calibrate_emergence_button)
        calib_grid.addWidget(self.calibrate_emergence_button, crow, 0, 1, 2); crow += 1

        # Starting Pressure (psi)
        self.start_pressure_label = QtWidgets.QLabel("Starting Pressure (psi):")
        self.start_pressure_spin = QtWidgets.QDoubleSpinBox()
        self.start_pressure_spin.setDecimals(2)
        self.start_pressure_spin.setRange(self.hw_lo, self.hw_hi)
        self.start_pressure_spin.setSingleStep(0.01)
        try:
            cur_p = float(self.model.machine_model.get_current_print_pressure())
            cur_p = min(max(cur_p, self.hw_lo), self.hw_hi)
        except Exception:
            cur_p = (self.hw_lo + self.hw_hi) / 2.0
        self.start_pressure_spin.setValue(round(cur_p, 2))
        calib_grid.addWidget(self.start_pressure_label, crow, 0)
        calib_grid.addWidget(self.start_pressure_spin,  crow, 1); crow += 1

        # Number of pressures to test in characterization process
        self.num_pressure_tests_label = QtWidgets.QLabel("Number of pressures to sample")
        self.num_pressure_tests_spin = QtWidgets.QSpinBox()
        self.num_pressure_tests_spin.setRange(2, 20)
        self.num_pressure_tests_spin.setSingleStep(1)
        self.num_pressure_tests_spin.setValue(4)
        calib_grid.addWidget(self.num_pressure_tests_label, crow, 0)
        calib_grid.addWidget(self.num_pressure_tests_spin,  crow, 1); crow += 1

        self.calibrate_pressure_scan_button = QtWidgets.QPushButton("Scan Pressures")
        self.calibrate_pressure_scan_button.clicked.connect(self.toggle_start_pressure_scan_calibration)
        self._register_calibration_action_button("pressure_scan", self.calibrate_pressure_scan_button)
        calib_grid.addWidget(self.calibrate_pressure_scan_button, crow, 0, 1, 2); crow += 1

        # self.calibrate_trajectory_button = QtWidgets.QPushButton("Calibrate Droplet Trajectory")
        # self.calibrate_trajectory_button.clicked.connect(self.toggle_start_trajectory_calibration)
        # calib_grid.addWidget(self.calibrate_trajectory_button, crow, 0, 1, 2); crow += 1

        self.scan_trajectory_button = QtWidgets.QPushButton("Scan Trajectory Pressures")
        self.scan_trajectory_button.clicked.connect(self.toggle_start_pressure_trajectory_calibration)
        self._register_calibration_action_button("pressure_trajectory", self.scan_trajectory_button)
        calib_grid.addWidget(self.scan_trajectory_button, crow, 0, 1, 2); crow += 1

        # self.calibrate_droplet_search_button = QtWidgets.QPushButton("Search for Droplets")
        # self.calibrate_droplet_search_button.clicked.connect(self.toggle_start_droplet_search_calibration)
        # calib_grid.addWidget(self.calibrate_droplet_search_button, crow, 0, 1, 2); crow += 1

        self.calibrate_pressure_sweep_button = QtWidgets.QPushButton("Pressure Sweep Characterization")
        self.calibrate_pressure_sweep_button.clicked.connect(self.toggle_start_pressure_sweep_calibration)
        self._register_calibration_action_button(
            "pressure_sweep_characterization",
            self.calibrate_pressure_sweep_button,
        )
        calib_grid.addWidget(self.calibrate_pressure_sweep_button, crow, 0, 1, 2); crow += 1

        self.calibrate_all_button = QtWidgets.QPushButton("Calibrate All")
        self.calibrate_all_button.clicked.connect(self.toggle_start_all_calibration)
        self._register_calibration_action_button("calibrate_all", self.calibrate_all_button)
        calib_grid.addWidget(self.calibrate_all_button, crow, 0, 1, 2); crow += 1

        self.calibrate_characterization_button = QtWidgets.QPushButton("Manually Characterize Droplets")
        self.calibrate_characterization_button.clicked.connect(self.toggle_start_characterization_calibration)
        self._register_calibration_action_button(
            "droplet_characterization",
            self.calibrate_characterization_button,
        )
        calib_grid.addWidget(self.calibrate_characterization_button, crow, 0, 1, 2); crow += 1

        # --- Stream tab: standard stream workflow ---
        self.stream_calib_group = QtWidgets.QGroupBox("Stream Calibration")
        stream_calib_grid = QtWidgets.QGridLayout(self.stream_calib_group)
        stream_calib_grid.setHorizontalSpacing(8)
        stream_calib_grid.setVerticalSpacing(6)
        stream_crow = 0

        self.prime_head_stream_button = QtWidgets.QPushButton("Prime Printer Head")
        self.prime_head_stream_button.clicked.connect(self.toggle_start_head_prime_calibration)
        self._register_calibration_action_button("head_prime", self.prime_head_stream_button)
        stream_calib_grid.addWidget(self.prime_head_stream_button, stream_crow, 0, 1, 2); stream_crow += 1

        self.calibrate_nozzle_stream_button = QtWidgets.QPushButton("Calibrate Nozzle Position")
        self.calibrate_nozzle_stream_button.clicked.connect(self.toggle_start_nozzle_calibration)
        self._register_calibration_action_button("nozzle_position", self.calibrate_nozzle_stream_button)
        stream_calib_grid.addWidget(self.calibrate_nozzle_stream_button, stream_crow, 0, 1, 2); stream_crow += 1

        self.calibrate_focus_stream_button = QtWidgets.QPushButton("Calibrate Nozzle Focus")
        self.calibrate_focus_stream_button.clicked.connect(self.toggle_start_focus_calibration)
        self._register_calibration_action_button("nozzle_focus", self.calibrate_focus_stream_button)
        stream_calib_grid.addWidget(self.calibrate_focus_stream_button, stream_crow, 0, 1, 2); stream_crow += 1

        self.calibrate_emergence_stream_button = QtWidgets.QPushButton("Calibrate Droplet Emergence")
        self.calibrate_emergence_stream_button.clicked.connect(self.toggle_start_emergence_calibration)
        self._register_calibration_action_button("droplet_emergence", self.calibrate_emergence_stream_button)
        stream_calib_grid.addWidget(self.calibrate_emergence_stream_button, stream_crow, 0, 1, 2); stream_crow += 1

        self.calibrate_online_stream_button = QtWidgets.QPushButton("Calibrate Stream Volume")
        self.calibrate_online_stream_button.clicked.connect(self.toggle_start_online_stream_calibration)
        self._register_calibration_action_button(
            "online_stream_calibration",
            self.calibrate_online_stream_button,
        )
        stream_calib_grid.addWidget(self.calibrate_online_stream_button, stream_crow, 0, 1, 2); stream_crow += 1

        self.calibrate_all_stream_button = QtWidgets.QPushButton("Calibrate All")
        self.calibrate_all_stream_button.clicked.connect(self.toggle_start_all_stream_calibration)
        self._register_calibration_action_button(
            "stream_calibrate_all",
            self.calibrate_all_stream_button,
        )
        stream_calib_grid.addWidget(self.calibrate_all_stream_button, stream_crow, 0, 1, 2); stream_crow += 1

        # --- Debug tab: Pulse Width Sweep ---
        self.pw_sweep_group = QtWidgets.QGroupBox("Pulse Width Sweep")
        pw_grid = QtWidgets.QGridLayout(self.pw_sweep_group)
        pw_grid.setHorizontalSpacing(8)
        pw_grid.setVerticalSpacing(6)
        pw_row = 0
        self.pw_start_label = QtWidgets.QLabel("PW Start (µs):")
        self.pw_start_spin  = QtWidgets.QSpinBox()
        self.pw_start_spin.setRange(0, 10000)
        self.pw_start_spin.setSingleStep(50)

        self.pw_end_label = QtWidgets.QLabel("PW End (µs):")
        self.pw_end_spin  = QtWidgets.QSpinBox()
        self.pw_end_spin.setRange(0, 10000)
        self.pw_end_spin.setSingleStep(50)

        self.pw_step_label = QtWidgets.QLabel("PW Step (µs):")
        self.pw_step_spin  = QtWidgets.QSpinBox()
        self.pw_step_spin.setRange(1, 10000)
        self.pw_step_spin.setSingleStep(50)

        self.pw_start_spin.setValue(1300)
        self.pw_end_spin.setValue(1800)
        self.pw_step_spin.setValue(50)

        pw_grid.addWidget(self.pw_start_label, pw_row, 0)
        pw_grid.addWidget(self.pw_start_spin,  pw_row, 1); pw_row += 1
        pw_grid.addWidget(self.pw_end_label,   pw_row, 0)
        pw_grid.addWidget(self.pw_end_spin,    pw_row, 1); pw_row += 1
        pw_grid.addWidget(self.pw_step_label,  pw_row, 0)
        pw_grid.addWidget(self.pw_step_spin,   pw_row, 1); pw_row += 1

        self.calibrate_all_pw_button = QtWidgets.QPushButton("Calibrate All (PW Range)")
        self.calibrate_all_pw_button.clicked.connect(self.toggle_start_pw_sweep)
        self._register_calibration_action_button("pulsewidth_sweep", self.calibrate_all_pw_button)
        pw_grid.addWidget(self.calibrate_all_pw_button, pw_row, 0, 1, 2); pw_row += 1

        self.timecourse_group = QtWidgets.QGroupBox("Droplet Timecourse")
        timecourse_v = QtWidgets.QVBoxLayout(self.timecourse_group)
        timecourse_v.setContentsMargins(8, 8, 8, 8)
        timecourse_v.setSpacing(6)
        self.calibrate_timecourse_button = QtWidgets.QPushButton("Droplet Timecourse Imaging")
        self.calibrate_timecourse_button.clicked.connect(self.toggle_start_timecourse_calibration)
        self._register_calibration_action_button("droplet_timecourse", self.calibrate_timecourse_button)
        timecourse_v.addWidget(self.calibrate_timecourse_button)

        self._calibration_readiness_button_specs = (
            ("pressure_scan", "pressure_scan"),
            ("trajectory_pressure_scan", "pressure_trajectory"),
            ("droplet_characterization", "droplet_characterization"),
            ("pressure_sweep_characterization", "pressure_sweep_characterization"),
            ("online_stream_calibration", "online_stream_calibration"),
        )
        self._last_calibration_readiness = {}

        self.stream_capture_group = QtWidgets.QGroupBox("Stream Gravimetric Capture")
        stream_grid = QtWidgets.QGridLayout(self.stream_capture_group)
        stream_grid.setHorizontalSpacing(8)
        stream_grid.setVerticalSpacing(6)
        srow = 0

        self.stream_capture_status_label = QtWidgets.QLabel("Ready to begin stream gravimetric capture.")
        self.stream_capture_status_label.setWordWrap(True)
        stream_grid.addWidget(self.stream_capture_status_label, srow, 0, 1, 2); srow += 1

        self.stream_capture_summary_label = QtWidgets.QLabel("Run: - | Counts: -")
        self.stream_capture_summary_label.setWordWrap(True)
        stream_grid.addWidget(self.stream_capture_summary_label, srow, 0, 1, 2); srow += 1

        self.stream_capture_starting_mass_label = QtWidgets.QLabel("Starting Mass (mg):")
        self.stream_capture_starting_mass_spin = QtWidgets.QDoubleSpinBox()
        self.stream_capture_starting_mass_spin.setDecimals(4)
        self.stream_capture_starting_mass_spin.setRange(-100000.0, 100000.0)
        self.stream_capture_starting_mass_spin.setSingleStep(0.01)
        self.stream_capture_starting_mass_spin.setValue(0.0)
        stream_grid.addWidget(self.stream_capture_starting_mass_label, srow, 0)
        stream_grid.addWidget(self.stream_capture_starting_mass_spin, srow, 1); srow += 1

        self.stream_capture_rep_label = QtWidgets.QLabel("Rep:")
        self.stream_capture_rep_spin = QtWidgets.QSpinBox()
        self.stream_capture_rep_spin.setRange(1, 999)
        self.stream_capture_rep_spin.setValue(1)
        stream_grid.addWidget(self.stream_capture_rep_label, srow, 0)
        stream_grid.addWidget(self.stream_capture_rep_spin, srow, 1); srow += 1

        self.stream_capture_notes_label = QtWidgets.QLabel("Notes:")
        self.stream_capture_notes_edit = QtWidgets.QPlainTextEdit()
        self.stream_capture_notes_edit.setPlaceholderText("Optional notes for stream_metadata.csv and session provenance.")
        self.stream_capture_notes_edit.setMaximumBlockCount(20)
        self.stream_capture_notes_edit.setMinimumHeight(72)
        stream_grid.addWidget(self.stream_capture_notes_label, srow, 0, QtCore.Qt.AlignTop)
        stream_grid.addWidget(self.stream_capture_notes_edit, srow, 1); srow += 1

        self.stream_capture_online_mode_checkbox = QtWidgets.QCheckBox("Use Online Stream Analysis")
        self.stream_capture_online_mode_checkbox.setChecked(False)
        stream_grid.addWidget(self.stream_capture_online_mode_checkbox, srow, 0, 1, 2); srow += 1

        self.stream_capture_begin_button = QtWidgets.QPushButton("Begin Session")
        self.stream_capture_begin_button.clicked.connect(self.begin_stream_gravimetric_capture)
        self.stream_capture_discard_button = QtWidgets.QPushButton("Discard")
        self.stream_capture_discard_button.clicked.connect(self.discard_stream_gravimetric_capture)
        self.stream_capture_begin_button.setMinimumHeight(32)
        self.stream_capture_discard_button.setMinimumHeight(32)
        stream_grid.addWidget(self.stream_capture_begin_button, srow, 0, 1, 2); srow += 1
        stream_grid.addWidget(self.stream_capture_discard_button, srow, 0, 1, 2); srow += 1

        self.run_options_group = QtWidgets.QGroupBox("Run Options")
        run_options_v = QtWidgets.QVBoxLayout(self.run_options_group)
        run_options_v.setContentsMargins(8, 8, 8, 8)
        run_options_v.setSpacing(6)

        self.record_calibration_checkbox = QtWidgets.QCheckBox("Record Calibration Runs")
        self.record_calibration_checkbox.setToolTip(
            "When enabled, calibration runs save captures/events/analysis to calibration_recordings."
        )
        try:
            rec_enabled = bool(self.model.calibration_manager.get_record_mode_enabled())
        except Exception:
            rec_enabled = bool(getattr(self.model.calibration_manager, "record_mode_enabled", True))
        self.record_calibration_checkbox.setChecked(rec_enabled)
        run_options_v.addWidget(self.record_calibration_checkbox)

        self.enable_calibration_memory_checkbox = QtWidgets.QCheckBox("Enable Calibration Memory")
        self.enable_calibration_memory_checkbox.setToolTip(
            "When disabled, prior lookup and calibration-memory sidecar writes are skipped."
        )
        try:
            memory_enabled = bool(self.model.calibration_manager.get_calibration_memory_enabled())
        except Exception:
            memory_enabled = True
        self.enable_calibration_memory_checkbox.setChecked(memory_enabled)
        run_options_v.addWidget(self.enable_calibration_memory_checkbox)

        self.enable_refuel_level_tracking_checkbox = QtWidgets.QCheckBox("Enable Refuel Level Tracking")
        self.enable_refuel_level_tracking_checkbox.setToolTip(
            "Show and sample refuel level while the droplet imager is open."
        )
        refuel_tracking_enabled = False
        refuel_process_monitoring_enabled = False
        if self.refuel_camera_model is not None:
            try:
                refuel_tracking_enabled = bool(self.refuel_camera_model.is_refuel_tracking_enabled())
            except Exception:
                refuel_tracking_enabled = False
            process_getter = getattr(self.refuel_camera_model, "is_refuel_process_monitoring_enabled", None)
            if callable(process_getter):
                try:
                    refuel_process_monitoring_enabled = bool(process_getter())
                except Exception:
                    refuel_process_monitoring_enabled = False
        else:
            self.enable_refuel_level_tracking_checkbox.setEnabled(False)
        self.enable_refuel_level_tracking_checkbox.setChecked(refuel_tracking_enabled)
        run_options_v.addWidget(self.enable_refuel_level_tracking_checkbox)

        self.enable_refuel_process_monitoring_checkbox = QtWidgets.QCheckBox("Monitor Calibration Processes")
        self.enable_refuel_process_monitoring_checkbox.setToolTip(
            "Record refuel-level markers around calibration lifecycle events. "
            "Requires refuel level tracking."
        )
        self.enable_refuel_process_monitoring_checkbox.setChecked(
            bool(refuel_tracking_enabled and refuel_process_monitoring_enabled)
        )
        self.enable_refuel_process_monitoring_checkbox.setEnabled(
            bool(self.refuel_camera_model is not None and refuel_tracking_enabled)
        )
        run_options_v.addWidget(self.enable_refuel_process_monitoring_checkbox)

        self.printer_head_recovery_button = QtWidgets.QPushButton("Printer Head Recovery")
        self.printer_head_recovery_button.setToolTip("Open pull-back and refill recovery controls.")
        run_options_v.addWidget(self.printer_head_recovery_button)

        self.droplet_setup_widget = QtWidgets.QWidget()
        droplet_setup_grid = QtWidgets.QGridLayout(self.droplet_setup_widget)
        droplet_setup_grid.setContentsMargins(0, 0, 0, 0)
        droplet_setup_grid.setHorizontalSpacing(8)
        droplet_setup_grid.setVerticalSpacing(6)
        droplet_setup_grid.addWidget(self.prime_head_button, 0, 0, 1, 2)
        droplet_setup_grid.addWidget(self.calibrate_nozzle_button, 1, 0, 1, 2)
        droplet_setup_grid.addWidget(self.calibrate_focus_button, 2, 0, 1, 2)
        droplet_setup_grid.addWidget(self.calibrate_emergence_button, 3, 0, 1, 2)

        self.droplet_workflow_widget = QtWidgets.QWidget()
        droplet_workflow_grid = QtWidgets.QGridLayout(self.droplet_workflow_widget)
        droplet_workflow_grid.setContentsMargins(0, 0, 0, 0)
        droplet_workflow_grid.setHorizontalSpacing(8)
        droplet_workflow_grid.setVerticalSpacing(6)
        droplet_workflow_grid.addWidget(self.start_pressure_label, 0, 0)
        droplet_workflow_grid.addWidget(self.start_pressure_spin, 0, 1)
        droplet_workflow_grid.addWidget(self.num_pressure_tests_label, 1, 0)
        droplet_workflow_grid.addWidget(self.num_pressure_tests_spin, 1, 1)
        droplet_workflow_grid.addWidget(self.calibrate_pressure_scan_button, 2, 0, 1, 2)
        droplet_workflow_grid.addWidget(self.scan_trajectory_button, 3, 0, 1, 2)
        droplet_workflow_grid.addWidget(self.calibrate_pressure_sweep_button, 4, 0, 1, 2)
        droplet_workflow_grid.addWidget(self.calibrate_all_button, 5, 0, 1, 2)
        droplet_workflow_grid.addWidget(self.calibrate_characterization_button, 6, 0, 1, 2)

        self.stream_setup_widget = QtWidgets.QWidget()
        stream_setup_grid = QtWidgets.QGridLayout(self.stream_setup_widget)
        stream_setup_grid.setContentsMargins(0, 0, 0, 0)
        stream_setup_grid.setHorizontalSpacing(8)
        stream_setup_grid.setVerticalSpacing(6)
        stream_setup_grid.addWidget(self.prime_head_stream_button, 0, 0, 1, 2)
        stream_setup_grid.addWidget(self.calibrate_nozzle_stream_button, 1, 0, 1, 2)
        stream_setup_grid.addWidget(self.calibrate_focus_stream_button, 2, 0, 1, 2)
        stream_setup_grid.addWidget(self.calibrate_emergence_stream_button, 3, 0, 1, 2)

        self.stream_workflow_widget = QtWidgets.QWidget()
        stream_workflow_grid = QtWidgets.QGridLayout(self.stream_workflow_widget)
        stream_workflow_grid.setContentsMargins(0, 0, 0, 0)
        stream_workflow_grid.setHorizontalSpacing(8)
        stream_workflow_grid.setVerticalSpacing(6)
        stream_workflow_grid.addWidget(self.calibrate_online_stream_button, 0, 0, 1, 2)
        stream_workflow_grid.addWidget(self.calibrate_all_stream_button, 1, 0, 1, 2)

        self.debug_scroll = QtWidgets.QScrollArea()
        self.debug_scroll.setWidgetResizable(True)
        self.debug_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.debug_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.debug_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.debug_tab_content = QtWidgets.QWidget()
        debug_content_v = QtWidgets.QVBoxLayout(self.debug_tab_content)
        debug_content_v.setContentsMargins(10, 10, 10, 0)
        debug_content_v.setSpacing(8)
        debug_content_v.addWidget(self.manual_group)
        debug_content_v.addWidget(self.pw_sweep_group)
        debug_content_v.addWidget(self.timecourse_group)
        debug_content_v.addWidget(self.stream_capture_group)
        self.refuel_performance_debug_group = self._build_refuel_performance_debug_group()
        debug_content_v.addWidget(self.refuel_performance_debug_group)
        debug_content_v.addStretch(1)
        self.debug_scroll.setWidget(self.debug_tab_content)

        for button in (self.flash_button, self.benchmark_profile_button):
            button.setMinimumHeight(32)
        for buttons in self._calibration_action_buttons.values():
            for button in buttons:
                button.setMinimumHeight(32)

        self.droplet_tab.layout().addWidget(self._create_lightweight_tab_section_header("Setup"))
        self.droplet_tab.layout().addWidget(self.droplet_setup_widget)
        self.droplet_tab.layout().addWidget(self._create_lightweight_tab_section_header("Workflow"))
        self.droplet_tab.layout().addWidget(self.droplet_workflow_widget)
        self.droplet_tab.layout().addStretch(1)
        self.stream_tab.layout().addWidget(self._create_lightweight_tab_section_header("Setup"))
        self.stream_tab.layout().addWidget(self.stream_setup_widget)
        self.stream_tab.layout().addWidget(self._create_lightweight_tab_section_header("Workflow"))
        self.stream_tab.layout().addWidget(self.stream_workflow_widget)
        self.stream_tab.layout().addStretch(1)
        self.debug_tab.layout().addWidget(self.debug_scroll)
        self._build_optics_tab()

        self.refuel_level_group = self._build_refuel_level_panel()
        control_panel_v.addWidget(self.reagent_title_widget)
        control_panel_v.addWidget(self.acquisition_controls_section)
        control_panel_v.addWidget(self.calibration_tabs, 1)
        control_panel_v.addWidget(self.run_options_group)
        control_panel_v.addWidget(self.refuel_level_group)

        self.recommendation_group = QtWidgets.QWidget()
        recommendation_v = QtWidgets.QVBoxLayout(self.recommendation_group)
        recommendation_v.setContentsMargins(8, 8, 8, 8)
        recommendation_v.setSpacing(6)

        self.memory_recommendation_status_label = QtWidgets.QLabel("No calibration-memory recommendation loaded yet.")
        self.memory_recommendation_status_label.setWordWrap(True)
        self.memory_recommendation_seed_label = QtWidgets.QLabel("Seed: -")
        self.memory_recommendation_seed_label.setWordWrap(True)
        self.memory_recommendation_expected_label = QtWidgets.QLabel("Expected: -")
        self.memory_recommendation_expected_label.setWordWrap(True)
        self.memory_recommendation_mode_label = QtWidgets.QLabel("Mode: -")
        self.memory_recommendation_mode_label.setWordWrap(True)

        recommendation_btn_h = QtWidgets.QHBoxLayout()
        self.memory_recommendation_refresh_btn = QtWidgets.QPushButton("Refresh Recommendation")
        self.memory_recommendation_refresh_btn.clicked.connect(self.refresh_calibration_memory_recommendation)
        self.memory_recommendation_apply_btn = QtWidgets.QPushButton("Use Recommended Seed")
        self.memory_recommendation_apply_btn.setEnabled(False)
        self.memory_recommendation_apply_btn.clicked.connect(self.apply_calibration_memory_recommendation)
        self.memory_recommendation_ignore_btn = QtWidgets.QPushButton("Keep Manual Start")
        self.memory_recommendation_ignore_btn.setEnabled(False)
        self.memory_recommendation_ignore_btn.clicked.connect(self.ignore_calibration_memory_recommendation)
        self.memory_recommendation_refresh_btn.setMinimumHeight(32)
        self.memory_recommendation_apply_btn.setMinimumHeight(32)
        self.memory_recommendation_ignore_btn.setMinimumHeight(32)
        recommendation_btn_h.addWidget(self.memory_recommendation_refresh_btn)
        recommendation_btn_h.addWidget(self.memory_recommendation_apply_btn)
        recommendation_btn_h.addWidget(self.memory_recommendation_ignore_btn)

        recommendation_v.addWidget(self.memory_recommendation_status_label)
        recommendation_v.addWidget(self.memory_recommendation_seed_label)
        recommendation_v.addWidget(self.memory_recommendation_expected_label)
        recommendation_v.addWidget(self.memory_recommendation_mode_label)
        recommendation_v.addLayout(recommendation_btn_h)

        # --- Group 3: Characterization Results ---
        self.summary_group = QtWidgets.QWidget()
        self.summary_group.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        summary_v = QtWidgets.QVBoxLayout(self.summary_group)
        summary_v.setContentsMargins(8, 8, 8, 8)
        summary_v.setSpacing(6)

        self._summary_muted_brush = _build_summary_muted_brush(self.color_dict)
        applied_color = QColor(self.color_dict.get("light_blue", "#3b82f6"))
        applied_color.setAlpha(64)
        self._summary_applied_brush = QBrush(applied_color)
        self.summary_toolbar = QtWidgets.QHBoxLayout()
        self.summary_toolbar.setSpacing(8)
        self.summary_current_run_checkbox = QtWidgets.QCheckBox("Current run only")
        self.summary_current_run_checkbox.setChecked(True)
        self.summary_valid_only_checkbox = QtWidgets.QCheckBox("Valid only")
        self.summary_source_combo = QtWidgets.QComboBox()
        self.summary_source_combo.addItem("All", "all")
        self.summary_source_combo.addItem("Sweep", "sweep")
        self.summary_source_combo.addItem("Search", "search")
        self.summary_source_combo.addItem("Recheck", "recheck")
        self.summary_source_combo.addItem("Stream", "stream")
        self.summary_history_button = QtWidgets.QPushButton("History...")
        self.summary_history_button.setMinimumHeight(28)
        self.summary_count_label = QtWidgets.QLabel("Showing 0 of 0 results")
        self.summary_count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.summary_toolbar.addWidget(self.summary_current_run_checkbox)
        self.summary_toolbar.addWidget(self.summary_valid_only_checkbox)
        self.summary_toolbar.addWidget(QtWidgets.QLabel("Source:"))
        self.summary_toolbar.addWidget(self.summary_source_combo)
        self.summary_toolbar.addWidget(self.summary_history_button)
        self.summary_toolbar.addStretch(1)

        self.summary_applied_calibration_banner = QtWidgets.QLabel()
        self.summary_applied_calibration_banner.setWordWrap(True)
        self.summary_applied_calibration_banner.setMinimumHeight(28)
        self.summary_applied_calibration_banner.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        summary_v.addWidget(self.summary_applied_calibration_banner)
        # Backward-compatible alias for older tests/helpers; the banner above the
        # table is now the only visible applied-calibration status surface.
        self.bridge_applied_calibration_label = self.summary_applied_calibration_banner

        summary_v.addLayout(self.summary_toolbar)

        self.summary_table_model = CharacterizationSummaryTableModel(
            self,
            include_recorded=False,
            muted_brush=self._summary_muted_brush,
            applied_brush=self._summary_applied_brush,
        )
        self.summary_table_proxy_model = CharacterizationSummaryProxyModel(self)
        self.summary_table_proxy_model.setSourceModel(self.summary_table_model)
        self.summary_table = QtWidgets.QTableView()
        self.summary_table.setModel(self.summary_table_proxy_model)
        _configure_characterization_table_view(self.summary_table, self.summary_table_model)
        self._unused_summary_columns = []
        _ = (
            ["Run #", "PW (µs)", "Pressure (psi)", "Mean (nL)", "CV (%)", "Valid"]
        )
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.summary_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        self.summary_table.setColumnWidth(0, 26)
        self.summary_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.summary_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.summary_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        self.summary_table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        
        # Allow selecting entire rows (single selection)
        self.summary_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.summary_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

        self.summary_table.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.summary_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.summary_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.summary_table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.summary_table.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)

        _configure_characterization_table_view(self.summary_table, self.summary_table_model)
        self.summary_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        self.summary_table.setColumnWidth(0, 26)
        self.summary_table.setMinimumHeight(280)
        summary_v.addWidget(self.summary_table, 1)
        summary_v.addWidget(self.summary_count_label)

        self.summary_detail_widget = QtWidgets.QWidget()
        detail_v = QtWidgets.QVBoxLayout(self.summary_detail_widget)
        detail_v.setContentsMargins(0, 0, 0, 0)
        detail_v.setSpacing(2)
        self.summary_detail_meta_label = QtWidgets.QLabel("Select a result to see run details.")
        self.summary_detail_meta_label.setWordWrap(True)
        self.summary_detail_status_label = QtWidgets.QLabel("No result selected.")
        self.summary_detail_status_label.setWordWrap(True)
        detail_v.addWidget(self.summary_detail_meta_label)
        detail_v.addWidget(self.summary_detail_status_label)
        summary_v.addWidget(self.summary_detail_widget)
        self._summary_sort_column = None
        self._summary_sort_order = Qt.AscendingOrder

        # Load Selected button
        self.load_selected_button = QtWidgets.QPushButton("Load selected")
        self.load_selected_button.setMinimumHeight(32)
        self.load_selected_button.setEnabled(False)
        self.load_selected_button.setToolTip("Select a row above, then click to apply its PW and pressure.")
        self.load_selected_button.clicked.connect(self.load_selected_summary_row)
        self.load_selected_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.recheck_selected_button = QtWidgets.QPushButton("Recheck selected")
        self.recheck_selected_button.setMinimumHeight(32)
        self.recheck_selected_button.setEnabled(False)
        self.recheck_selected_button.setToolTip(
            "Select a valid trajectory-aware droplet result, then click to image it again."
        )
        self.recheck_selected_button.clicked.connect(self.recheck_selected_summary_row)
        self.recheck_selected_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        summary_action_row = QtWidgets.QHBoxLayout()
        summary_action_row.setContentsMargins(0, 0, 0, 0)
        summary_action_row.setSpacing(8)
        summary_action_row.addWidget(self.load_selected_button)
        summary_action_row.addWidget(self.recheck_selected_button)
        summary_v.addLayout(summary_action_row)

        # --- Group 4: Design ↔ Calibration Bridge ---
        self.bridge_group = QtWidgets.QWidget()
        self.bridge_group.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        bridge_v = QtWidgets.QVBoxLayout(self.bridge_group)
        bridge_v.setContentsMargins(8, 8, 8, 8)
        bridge_v.setSpacing(6)

        self.bridge_reagent_label = QtWidgets.QLabel("Reagent: —")
        self.bridge_design_dv_label = QtWidgets.QLabel("Design ejection volume (nL): —")
        self.bridge_design_targets_label = QtWidgets.QLabel("Design targets: —")
        self.bridge_design_stock_label = QtWidgets.QLabel("Stock concentration(s): —")

        preview_h = QtWidgets.QHBoxLayout()
        self.bridge_preview_btn = QtWidgets.QPushButton("Preview from selected result")
        self.bridge_preview_btn.setMinimumHeight(32)
        self.bridge_preview_btn.clicked.connect(self._bridge_preview_from_last_char)
        preview_h.addWidget(self.bridge_preview_btn)

        self.bridge_table = QtWidgets.QTableWidget(0, 7, self.bridge_group)
        self.bridge_table.setHorizontalHeaderLabels([
            "Target", "Achievable", "Error (%)", "Drops", "Δ/drop", "Printed nL (new)", "Δ printed nL"
        ])
        self.bridge_table.horizontalHeader().setStretchLastSection(True)
        self.bridge_table.verticalHeader().setVisible(False)
        self.bridge_table.setWordWrap(False)
        self.bridge_table.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.bridge_table.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustIgnored)
        self.bridge_table.setFixedHeight(280)
        self.bridge_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.bridge_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.bridge_table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.bridge_table.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)

        self.bridge_apply_btn = QtWidgets.QPushButton("Apply new ejection volume to design")
        self.bridge_apply_btn.setMinimumHeight(32)
        self.bridge_apply_btn.setEnabled(False)
        self.bridge_apply_btn.clicked.connect(self._apply_previewed_droplet_volume)
        self.bridge_apply_btn.setToolTip("Update ejection counts and the concentration key using this volume")

        bridge_v.addWidget(self.bridge_design_dv_label)
        bridge_v.addWidget(self.bridge_table, 1)
        self.bridge_status_label = QtWidgets.QLabel("Select a characterization result to preview design impact.")
        self.bridge_status_label.setWordWrap(True)
        self.bridge_status_label.setStyleSheet(
            f"color: {self.color_dict.get('muted_text', self.color_dict.get('light_gray', '#9ca3af'))};"
        )
        bridge_v.addWidget(self.bridge_status_label)
        bridge_v.addWidget(self.bridge_apply_btn)

        self.diff_widget = QWidget()
        self.diff_layout = QGridLayout(self.diff_widget)
        self.diff_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        motor_label = QLabel('Motor')
        current_label = QLabel('Current')
        target_label = QLabel('Diff')
        motor_label.setAlignment(Qt.AlignCenter)
        current_label.setAlignment(Qt.AlignCenter)
        target_label.setAlignment(Qt.AlignCenter)
        self.diff_layout.addWidget(motor_label, 0, 0)
        self.diff_layout.addWidget(current_label, 0, 1)
        self.diff_layout.addWidget(target_label, 0, 2)

        self.diff_labels = {
            'X': {'current': QLabel('0'), 'diff': QLabel('0')},
            'Y': {'current': QLabel('0'), 'diff': QLabel('0')},
            'Z': {'current': QLabel('0'), 'diff': QLabel('0')},
        }
        r = 1
        for motor, positions in self.diff_labels.items():
            ml = QLabel(motor); ml.setAlignment(Qt.AlignCenter)
            positions['current'].setAlignment(Qt.AlignCenter)
            positions['diff'].setAlignment(Qt.AlignCenter)
            self.diff_layout.addWidget(ml,                 r, 0)
            self.diff_layout.addWidget(positions['current'], r, 1)
            self.diff_layout.addWidget(positions['diff'],   r, 2)
            r += 1

        self.machine_position_group = QtWidgets.QWidget()
        self.machine_position_group.setObjectName("machine_position_group")
        machine_position_v = QtWidgets.QVBoxLayout(self.machine_position_group)
        machine_position_v.setContentsMargins(8, 8, 8, 8)
        machine_position_v.setSpacing(6)
        machine_position_v.addWidget(self.diff_widget)

        # --- Group 5: Calibration Status ---
        self.status_group = QtWidgets.QWidget()
        self.status_group.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        status_v = QtWidgets.QVBoxLayout(self.status_group)
        status_v.setContentsMargins(8, 8, 8, 8)
        status_v.setSpacing(6)

        self.stageLabel = QtWidgets.QLabel("Status: Idle")
        status_v.addWidget(self.stageLabel)

        self.stage_table = QtWidgets.QTableWidget()
        self.stage_table.setColumnCount(2)
        self.stage_table.setHorizontalHeaderLabels(["Time", "Stage"])
        self.stage_table.verticalHeader().setVisible(False)
        self.stage_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.stage_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.stage_table.setWordWrap(True)
        self.stage_table.setAlternatingRowColors(True)
        self.stage_table.horizontalHeader().setStretchLastSection(True)
        self.stage_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.stage_table.setMinimumHeight(140)
        status_v.addWidget(self.stage_table, 1)

        (
            self.summary_section,
            self.summary_section_toggle,
            self.summary_section_content,
        ) = self._create_info_panel_section("summary", "Characterization Results", self.summary_group)
        (
            self.bridge_section,
            self.bridge_section_toggle,
            self.bridge_section_content,
        ) = self._create_info_panel_section("bridge", "Design ↔ Calibration Bridge", self.bridge_group)
        (
            self.recommendation_section,
            self.recommendation_section_toggle,
            self.recommendation_section_content,
        ) = self._create_info_panel_section(
            "recommendation",
            "Calibration Memory Recommendation",
            self.recommendation_group,
        )
        (
            self.machine_position_section,
            self.machine_position_section_toggle,
            self.machine_position_section_content,
        ) = self._create_info_panel_section(
            "machine_position",
            "Machine Position",
            self.machine_position_group,
        )
        (
            self.status_section,
            self.status_section_toggle,
            self.status_section_content,
        ) = self._create_info_panel_section("status", "Calibration Status", self.status_group)

        self.info_panel_sections = (
            self.summary_section,
            self.bridge_section,
            self.recommendation_section,
            self.machine_position_section,
            self.status_section,
        )
        for section in self.info_panel_sections:
            info_panel_v.addWidget(section)
        info_panel_v.addStretch(1)

        # Keep the side panels stable so buttons and labels remain readable.
        self.info_panel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
        self.info_panel_scroll.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        self.control_panel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
        self.control_panel_scroll.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        self.info_panel.adjustSize()
        self.control_panel.adjustSize()

        # ---------- MIDDLE PANEL (image + online debug plots): expands ----------
        self.analysis_layout = QtWidgets.QVBoxLayout()
        self.analysis_layout.setContentsMargins(0, 0, 0, 0)
        self.analysis_layout.setSpacing(10)

        self.image_label = QLabel("No image captured yet.")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(480, 360)
        self.image_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.image_label.setStyleSheet("background-color: black; border: 1px solid #444; padding: 8px;")
        self.analysis_layout.addWidget(self.image_label, 1)

        self.online_stream_plot_container = QtWidgets.QWidget()
        self.online_stream_plot_container.setObjectName("online_stream_plot_container")
        self.online_stream_plot_container.setMinimumHeight(220)
        self.online_stream_plot_container.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.MinimumExpanding,
        )
        plot_row = QtWidgets.QHBoxLayout(self.online_stream_plot_container)
        plot_row.setContentsMargins(0, 0, 0, 0)
        plot_row.setSpacing(10)

        self._online_stream_flow_chart_bundle = self._create_online_stream_chart_bundle(
            title="Visible Volume vs Time",
            y_title="Visible Volume (nL)",
            use_scatter_data=True,
            reference_color_key="blue",
            reference_fallback="#2d7ff9",
        )
        self.online_stream_flow_chart_view = self._online_stream_flow_chart_bundle["view"]
        self.online_stream_flow_chart_view.setObjectName("online_stream_flow_chart_view")
        plot_row.addWidget(self.online_stream_flow_chart_view, 1)

        self._online_stream_tail_chart_bundle = self._create_online_stream_chart_bundle(
            title="Attached Width vs Time",
            y_title="Attached Width (px)",
        )
        self._online_stream_tail_chart_bundle["reference_series"].setPen(
            self._make_chart_pen("light_gray", "#cfd8dc", width=2, style=Qt.DashLine)
        )
        self.online_stream_tail_chart_view = self._online_stream_tail_chart_bundle["view"]
        self.online_stream_tail_chart_view.setObjectName("online_stream_tail_chart_view")
        plot_row.addWidget(self.online_stream_tail_chart_view, 1)

        self.online_stream_plot_container.hide()
        self._online_stream_debug_active = False
        self.analysis_layout.addWidget(self.online_stream_plot_container, 0)

        self.analysis_layout.addStretch(1)

        # Add panels to the main layout: left controls, middle image, right results.
        self.analysis_panel = QtWidgets.QWidget()
        self.analysis_panel.setLayout(self.analysis_layout)
        self.analysis_panel.setMinimumWidth(560)
        self.analysis_panel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.layout.addWidget(self.control_panel_scroll, 0)
        self.layout.setStretchFactor(self.control_panel_scroll, 0)
        self.layout.addWidget(self.analysis_panel, 1)
        self.layout.setStretchFactor(self.analysis_panel, 1)
        self.layout.addWidget(self.info_panel_scroll, 0)
        self.layout.setStretchFactor(self.info_panel_scroll, 0)
        self._set_equal_panel_widths()

        # ---------------- Connections ----------------
        self.model.droplet_camera_model.droplet_image_updated.connect(self.update_image)
        self.model.droplet_camera_model.droplet_image_updated.connect(self._on_droplet_capture_finished)
        self.model.droplet_camera_model.flash_signal.connect(self.update_flash_info)
        self.model.calibration_manager.analyzedImageUpdated.connect(self.display_analyzed_image)
        online_stream_debug_signal = getattr(self.model.calibration_manager, "onlineStreamDebugUpdated", None)
        if online_stream_debug_signal is not None:
            online_stream_debug_signal.connect(self.on_online_stream_debug_updated)
        if self.refuel_camera_model is not None:
            try:
                self.refuel_camera_model.update_level_ui_signal.connect(self._schedule_refuel_level_panel_refresh)
            except Exception:
                pass

        self.start_pressure_spin.valueChanged.connect(self.set_start_pressure)
        self.num_pressure_tests_spin.valueChanged.connect(self.set_num_pressure_tests)
        self.record_calibration_checkbox.toggled.connect(self.set_record_mode_enabled)
        self.enable_calibration_memory_checkbox.toggled.connect(self.set_calibration_memory_enabled)
        self.enable_refuel_level_tracking_checkbox.toggled.connect(self._set_refuel_tracking_enabled)
        self.enable_refuel_process_monitoring_checkbox.toggled.connect(self._set_refuel_process_monitoring_enabled)
        self.printer_head_recovery_button.clicked.connect(self.open_printer_head_recovery_dialog)
        self.summary_current_run_checkbox.toggled.connect(self._refresh_summary_filters)
        self.summary_valid_only_checkbox.toggled.connect(self._refresh_summary_filters)
        self.summary_source_combo.currentIndexChanged.connect(self._refresh_summary_filters)
        self.summary_history_button.clicked.connect(self.open_characterization_history_dialog)
        self.summary_table.doubleClicked.connect(self._handle_summary_double_click)
        self.summary_table.horizontalHeader().sectionClicked.connect(self._handle_summary_header_click)
        self.summary_table.selectionModel().selectionChanged.connect(self._on_summary_selection_changed)

        self.model.calibration_manager.calibrationStageChanged.connect(self.update_stage_and_log)
        self.model.calibration_manager.calibrationCompleted.connect(self.on_calibration_completed)
        self.model.calibration_manager.calibrationQueueCompleted.connect(self.on_calibration_queue_completed)
        self.model.calibration_manager.calibrationError.connect(self.on_calibration_error)
        self.model.calibration_manager.calibrationStageChanged.connect(self._on_refuel_calibration_stage_changed)
        self.model.calibration_manager.calibrationCompleted.connect(self._on_refuel_calibration_completed)
        self.model.calibration_manager.calibrationQueueCompleted.connect(self._on_refuel_calibration_queue_completed)
        self.model.calibration_manager.calibrationError.connect(self._on_refuel_calibration_error)
        capture_failed_signal = getattr(self.model.calibration_manager, "captureFailed", None)
        if capture_failed_signal is not None:
            capture_failed_signal.connect(self._on_droplet_capture_failed)
        self.model.calibration_manager.position_diff_dict_signal.connect(self.update_position_diffs)
        self.model.calibration_manager.characterizationSummaryUpdated.connect(self.populate_summary_table)
        self.model.calibration_manager.calibrationStageChanged.connect(self._refresh_manual_control_lock_state)
        self.model.calibration_manager.calibrationCompleted.connect(self._refresh_manual_control_lock_state)
        self.model.calibration_manager.calibrationQueueCompleted.connect(self._refresh_manual_control_lock_state)
        self.model.calibration_manager.calibrationError.connect(self._refresh_manual_control_lock_state)
        stream_capture_signal = getattr(self.model.calibration_manager, "streamCaptureStateChanged", None)
        if stream_capture_signal is not None:
            stream_capture_signal.connect(self._sync_stream_capture_panel_state)
            stream_capture_signal.connect(self._refresh_manual_control_lock_state)
            stream_capture_signal.connect(self._ensure_stream_capture_followup_state)
            stream_capture_signal.connect(self._on_refuel_stream_capture_state_changed)
        stream_sequence_signal = getattr(
            self.model.calibration_manager,
            "streamCalibrationSequenceStateChanged",
            None,
        )
        if stream_sequence_signal is not None:
            stream_sequence_signal.connect(self._refresh_manual_control_lock_state)
            stream_sequence_signal.connect(self._ensure_stream_calibration_sequence_followup_state)
            stream_sequence_signal.connect(self._on_refuel_stream_sequence_state_changed)
        droplet_sequence_signal = getattr(
            self.model.calibration_manager,
            "dropletCalibrationSequenceStateChanged",
            None,
        )
        if droplet_sequence_signal is not None:
            droplet_sequence_signal.connect(self._refresh_manual_control_lock_state)
            droplet_sequence_signal.connect(self._ensure_droplet_calibration_sequence_followup_state)
            droplet_sequence_signal.connect(self._on_refuel_droplet_sequence_state_changed)

        self.model.calibration_manager.readinessChanged.connect(self.on_readiness_changed)
        self.model.calibration_manager._emit_readiness()

        self.set_exposure_time(self.droplet_camera_model.exposure_time)
        self.set_flash_delay(self.droplet_camera_model.flash_delay)
        self.set_flash_duration(self.droplet_camera_model.flash_duration)
        self.set_imaging_droplets(self.droplet_camera_model.num_droplets)
        self.set_start_pressure(self.start_pressure_spin.value())
        self.set_num_pressure_tests(self.num_pressure_tests_spin.value())
        if self.initial_tab == "optics":
            self.calibration_tabs.setCurrentWidget(self.optics_tab)
        else:
            self._apply_default_calibration_tab_from_printing_mode()
        self.populate_summary_table()
        self._refresh_manual_control_lock_state()
        self._refresh_optics_controls()
        self._apply_flash_safety_ui_state()
        self._sync_stream_capture_panel_state()
        self._schedule_refuel_level_panel_refresh(force=True)
        if self._is_refuel_tracking_enabled():
            self._start_refuel_monitor()
        QTimer.singleShot(0, self._ensure_stream_capture_followup_state)
        QTimer.singleShot(0, self._ensure_stream_calibration_sequence_followup_state)
        QTimer.singleShot(0, self._ensure_droplet_calibration_sequence_followup_state)

    def _build_refuel_performance_debug_group(self):
        group = QtWidgets.QGroupBox("Refuel Performance Debug")
        group_v = QtWidgets.QVBoxLayout(group)
        group_v.setContentsMargins(8, 8, 8, 8)
        group_v.setSpacing(6)

        self.enable_refuel_performance_diagnostics_checkbox = QtWidgets.QCheckBox(
            "Enable Refuel Performance Diagnostics"
        )
        self.enable_refuel_performance_diagnostics_checkbox.setToolTip(
            "Record calibration stopwatch events and enable refuel performance snapshot export."
        )
        diagnostics_enabled = self._is_refuel_performance_diagnostics_enabled()
        self.enable_refuel_performance_diagnostics_checkbox.setChecked(diagnostics_enabled)
        self.enable_refuel_performance_diagnostics_checkbox.toggled.connect(
            self._set_refuel_performance_diagnostics_enabled
        )
        group_v.addWidget(self.enable_refuel_performance_diagnostics_checkbox)

        self.export_refuel_performance_button = QtWidgets.QPushButton("Export Perf Snapshot")
        self.export_refuel_performance_button.setToolTip(
            "Write refuel monitor timing and process telemetry to a JSON file."
        )
        self.export_refuel_performance_button.clicked.connect(self._export_refuel_performance_snapshot)
        self.export_refuel_performance_button.setEnabled(bool(self.refuel_camera_model is not None and diagnostics_enabled))
        group_v.addWidget(self.export_refuel_performance_button)

        self.refuel_performance_debug_status_label = QtWidgets.QLabel(
            "Performance diagnostics disabled"
            if not diagnostics_enabled
            else "Performance diagnostics enabled"
        )
        self.refuel_performance_debug_status_label.setWordWrap(True)
        group_v.addWidget(self.refuel_performance_debug_status_label)
        return group

    def _build_refuel_level_panel(self):
        group = QtWidgets.QGroupBox("Refuel Level")
        group_v = QtWidgets.QVBoxLayout(group)
        group_v.setContentsMargins(8, 8, 8, 8)
        group_v.setSpacing(6)

        self.refuel_level_value_label = QtWidgets.QLabel("Level: -")
        self.refuel_level_value_label.setStyleSheet("font-weight: 600;")
        self.refuel_level_status_label = QtWidgets.QLabel("Off")
        self.refuel_level_last_update_label = QtWidgets.QLabel("-")
        self.refuel_level_timing_label = QtWidgets.QLabel("-")
        self.refuel_level_timing_label.setWordWrap(True)
        self.refuel_level_process_label = QtWidgets.QLabel("Process monitoring off")
        self.refuel_level_process_label.setWordWrap(True)
        self.refuel_level_ejection_label = QtWidgets.QLabel("-")
        self.refuel_level_ejection_label.setWordWrap(True)
        self.refuel_level_advisory_label = QtWidgets.QLabel("Monitoring disabled")
        self.refuel_level_advisory_label.setWordWrap(True)
        self.refuel_level_process_result_label = QtWidgets.QLabel("")
        self.refuel_level_process_result_label.setWordWrap(True)
        self.refuel_level_process_result_label.hide()
        group_v.addWidget(self.refuel_level_value_label)

        self._refuel_level_chart_bundle = self._create_refuel_level_chart_bundle()
        chart_view = self._refuel_level_chart_bundle["view"]
        chart_view.setObjectName("refuel_level_chart_view")
        chart_view.setMinimumHeight(190)
        chart_view.setMaximumHeight(240)
        group_v.addWidget(chart_view)

        group_v.addWidget(self.refuel_level_advisory_label)
        group_v.addWidget(self.refuel_level_process_result_label)

        self.open_refuel_camera_button = QtWidgets.QPushButton("Open Refuel Camera")
        opener = None
        for attr_name in (
            "open_refuel_camera_window",
            "open_refuel_camera",
            "_launch_refuel_camera_dialog",
        ):
            candidate = getattr(self.main_window, attr_name, None)
            if callable(candidate):
                opener = candidate
                break
        if opener is not None:
            self.open_refuel_camera_button.clicked.connect(opener)
        else:
            self.open_refuel_camera_button.setEnabled(False)
            self.open_refuel_camera_button.setToolTip("Open the main refuel camera window from the app launcher.")
        group_v.addWidget(self.open_refuel_camera_button)

        group.hide()
        return group

    def _is_refuel_performance_diagnostics_enabled(self):
        if self.refuel_camera_model is None:
            return False
        checkbox = getattr(self, "enable_refuel_performance_diagnostics_checkbox", None)
        if checkbox is not None and not checkbox.isChecked():
            return False
        getter = getattr(self.refuel_camera_model, "is_refuel_calibration_performance_enabled", None)
        if callable(getter):
            try:
                return bool(getter())
            except Exception:
                return False
        return bool(checkbox is not None and checkbox.isChecked())

    def _set_refuel_performance_debug_status(self, message):
        label = getattr(self, "refuel_performance_debug_status_label", None)
        if label is not None:
            label.setText(str(message or ""))

    def _set_refuel_performance_diagnostics_enabled(self, checked):
        checked = bool(checked and self.refuel_camera_model is not None)
        checkbox = getattr(self, "enable_refuel_performance_diagnostics_checkbox", None)
        if checkbox is not None and checkbox.isChecked() != checked:
            was_blocked = checkbox.blockSignals(True)
            try:
                checkbox.setChecked(checked)
            finally:
                checkbox.blockSignals(was_blocked)
        if self.refuel_camera_model is not None:
            setter = getattr(self.refuel_camera_model, "set_refuel_calibration_performance_enabled", None)
            if callable(setter):
                try:
                    setter(checked)
                except Exception:
                    checked = False
        button = getattr(self, "export_refuel_performance_button", None)
        if button is not None:
            button.setEnabled(bool(checked and self.refuel_camera_model is not None))
        self._set_refuel_performance_debug_status(
            "Performance diagnostics enabled" if checked else "Performance diagnostics disabled"
        )

    def _export_refuel_performance_snapshot(self, *, reason="manual_export", show_status=True):
        model = self.refuel_camera_model
        if model is None:
            return None
        if not self._is_refuel_performance_diagnostics_enabled():
            if show_status:
                self._set_refuel_performance_debug_status("Enable refuel performance diagnostics before exporting.")
            return None
        writer = getattr(model, "write_refuel_performance_snapshot", None)
        if not callable(writer):
            return None
        try:
            path = writer(reason=reason)
        except Exception as exc:
            print(f"[RefuelMonitor] performance snapshot export failed: {exc}")
            if show_status:
                self._set_refuel_performance_debug_status(f"Performance snapshot export failed: {exc}")
            return None
        if show_status:
            message = f"Performance snapshot saved: {path}"
            self._set_refuel_performance_debug_status(message)
            button = getattr(self, "export_refuel_performance_button", None)
            if button is not None:
                button.setToolTip(message)
        return path

    def _auto_export_refuel_performance_snapshot_on_close(self):
        if self.refuel_camera_model is None:
            return None
        if not self._is_refuel_performance_diagnostics_enabled():
            return None
        try:
            getter = getattr(self.refuel_camera_model, "get_refuel_monitor_timing_log", None)
            timing_log = list(getter() or []) if callable(getter) else []
        except Exception:
            timing_log = []
        has_calibration_performance = False
        try:
            perf_getter = getattr(self.refuel_camera_model, "get_refuel_calibration_performance_summary", None)
            performance = dict(perf_getter() or {}) if callable(perf_getter) else {}
            has_calibration_performance = bool(
                performance.get("active")
                or performance.get("last")
                or int(performance.get("event_count") or 0) > 0
            )
        except Exception:
            has_calibration_performance = False
        if not timing_log and not has_calibration_performance:
            return None
        return self._export_refuel_performance_snapshot(reason="dialog_close", show_status=False)

    def _create_refuel_level_chart_bundle(self):
        chart = QtCharts.QChart()
        chart.setTheme(QtCharts.QChart.ChartThemeDark)
        chart.setBackgroundBrush(QBrush(self._chart_color("darker_gray", "#242424")))
        chart.legend().hide()
        chart.setMargins(QtCore.QMargins(2, 2, 2, 2))

        axis_x = QtCharts.QValueAxis()
        axis_x.setTitleText("Recent Sample")
        axis_x.setLabelFormat("%.0f")
        axis_x.setRange(0.0, float(self.REFUEL_LEVEL_CHART_WINDOW_SAMPLES - 1))
        axis_y = QtCharts.QValueAxis()
        axis_y.setTitleText("Level (px)")
        axis_y.setLabelFormat("%.1f")
        axis_y.setRange(0.0, float(self.REFUEL_LEVEL_CHART_FALLBACK_HEIGHT_PX))
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)

        primary_series = QtCharts.QLineSeries()
        primary_series.setPen(self._make_chart_pen("light_blue", "#6fb6ff", width=2))
        current_series = QtCharts.QScatterSeries()
        current_series.setMarkerSize(9.0)
        current_series.setBorderColor(self._chart_color("light_gray", "#cfd8dc"))
        current_series.setColor(QColor("#ffffff"))
        process_start_line_series = QtCharts.QLineSeries()
        process_start_line_series.setPen(self._make_chart_pen("yellow", "#f1c40f", width=2, style=Qt.DashLine))
        process_end_line_series = QtCharts.QLineSeries()
        process_end_line_series.setPen(self._make_chart_pen("magenta", "#ff4fd8", width=2, style=Qt.DashLine))
        process_start_marker_series = QtCharts.QScatterSeries()
        process_start_marker_series.setMarkerSize(10.0)
        process_start_marker_series.setBorderColor(self._chart_color("yellow", "#f1c40f"))
        process_start_marker_series.setColor(self._chart_color("yellow", "#f1c40f"))
        process_end_marker_series = QtCharts.QScatterSeries()
        process_end_marker_series.setMarkerSize(10.0)
        process_end_marker_series.setBorderColor(self._chart_color("magenta", "#ff4fd8"))
        process_end_marker_series.setColor(self._chart_color("magenta", "#ff4fd8"))

        for series in (
            primary_series,
            process_start_line_series,
            process_end_line_series,
            current_series,
            process_start_marker_series,
            process_end_marker_series,
        ):
            chart.addSeries(series)
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)

        view = QtCharts.QChartView(chart)
        view.setRenderHint(QPainter.Antialiasing)
        view.setFocusPolicy(QtCore.Qt.NoFocus)
        view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        return {
            "chart": chart,
            "view": view,
            "axis_x": axis_x,
            "axis_y": axis_y,
            "primary_series": primary_series,
            "current_series": current_series,
            "process_start_line_series": process_start_line_series,
            "process_end_line_series": process_end_line_series,
            "process_start_marker_series": process_start_marker_series,
            "process_end_marker_series": process_end_marker_series,
        }

    def _set_refuel_tracking_enabled(self, checked):
        checked = bool(checked)
        if self.refuel_camera_model is not None:
            try:
                self.refuel_camera_model.set_refuel_tracking_enabled(checked)
            except Exception:
                pass
        process_checkbox = getattr(self, "enable_refuel_process_monitoring_checkbox", None)
        if process_checkbox is not None:
            process_checkbox.setEnabled(bool(checked and self.refuel_camera_model is not None))
            if not checked:
                was_blocked = process_checkbox.blockSignals(True)
                try:
                    process_checkbox.setChecked(False)
                finally:
                    process_checkbox.blockSignals(was_blocked)
                if self.refuel_camera_model is not None:
                    setter = getattr(self.refuel_camera_model, "set_refuel_process_monitoring_enabled", None)
                    if callable(setter):
                        try:
                            setter(False)
                        except Exception:
                            pass
        if checked:
            self._start_refuel_monitor()
        else:
            self._stop_refuel_monitor("Monitoring disabled")
        self._schedule_refuel_level_panel_refresh(force=True)

    def _set_refuel_process_monitoring_enabled(self, checked):
        checked = bool(checked and self._is_refuel_tracking_enabled())
        checkbox = getattr(self, "enable_refuel_process_monitoring_checkbox", None)
        if checkbox is not None:
            checkbox.setEnabled(bool(self.refuel_camera_model is not None and self._is_refuel_tracking_enabled()))
            if checkbox.isChecked() != checked:
                was_blocked = checkbox.blockSignals(True)
                try:
                    checkbox.setChecked(checked)
                finally:
                    checkbox.blockSignals(was_blocked)
        if self.refuel_camera_model is not None:
            setter = getattr(self.refuel_camera_model, "set_refuel_process_monitoring_enabled", None)
            if callable(setter):
                try:
                    setter(checked)
                except Exception:
                    pass
        self._schedule_refuel_level_panel_refresh(force=True)

    def open_printer_head_recovery_dialog(self):
        if DropletImagingDialog._is_calibration_busy(self):
            QtWidgets.QMessageBox.warning(
                self,
                "Printer Head Recovery",
                "Finish the active calibration before opening Printer Head Recovery.",
            )
            return
        existing = getattr(self, "_printer_head_recovery_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dialog = PrinterHeadRecoveryDialog(self, self.model, self.controller)
        self._printer_head_recovery_dialog = dialog
        dialog.finished.connect(lambda _result: setattr(self, "_printer_head_recovery_dialog", None))
        dialog.open()

    def open_refuel_vacuum_dialog(self):
        self.open_printer_head_recovery_dialog()

    def _start_refuel_monitor(self):
        if self.refuel_camera_model is None:
            return False
        if self.refuel_monitor_timer.isActive():
            return True

        self.refuel_camera_model.set_refuel_monitor_state("starting", "Starting refuel camera")
        try:
            self.controller.start_refuel_camera()
        except Exception as exc:
            self._refuel_monitor_camera_started = False
            self.refuel_monitor_timer.stop()
            self.refuel_camera_model.record_refuel_monitor_failure(f"Refuel camera unavailable: {exc}")
            return False

        self._refuel_monitor_camera_started = True
        self.refuel_camera_model.set_refuel_monitor_state("monitoring", "Waiting for first refuel sample")
        self.refuel_monitor_timer.start(self.refuel_monitor_interval_ms)
        self._refuel_first_sample_pending = True
        QTimer.singleShot(0, self._capture_initial_refuel_monitor_sample)
        return True

    def _stop_refuel_monitor(self, message="Monitoring disabled"):
        self.refuel_monitor_timer.stop()
        self._refuel_first_sample_pending = False
        if self._refuel_monitor_camera_started:
            try:
                self.controller.stop_refuel_camera()
            except Exception as exc:
                print(f"[RefuelMonitor] stop_refuel_camera failed: {exc}")
        self._refuel_monitor_camera_started = False
        if self.refuel_camera_model is not None:
            try:
                self.refuel_camera_model.set_refuel_monitor_state("off", message)
            except Exception:
                pass

    def _capture_initial_refuel_monitor_sample(self):
        if not getattr(self, "_refuel_first_sample_pending", False):
            return
        self._capture_refuel_monitor_sample()

    def _handle_refuel_monitor_failure(self, message):
        if self.refuel_camera_model is None:
            return
        self.refuel_camera_model.record_refuel_monitor_failure(str(message or "Refuel camera unavailable"))
        status = self.refuel_camera_model.get_refuel_monitor_status()
        if int(status.get("consecutive_failures", 0)) >= 3:
            self.refuel_monitor_timer.stop()
            if self._refuel_monitor_camera_started:
                try:
                    self.controller.stop_refuel_camera()
                except Exception as exc:
                    print(f"[RefuelMonitor] stop_refuel_camera failed after failures: {exc}")
            self._refuel_monitor_camera_started = False

    def _new_refuel_monitor_timing_context(self):
        model = self.refuel_camera_model
        tick_index = model.next_refuel_monitor_tick_index() if model is not None else None
        return {
            "refuel_monitor_tick_index": tick_index,
            "refuel_monitor_tick_started_perf_s": time.perf_counter(),
            "refuel_monitor_tick_started_monotonic_s": time.monotonic(),
            "refuel_monitor_interval_ms": int(self.refuel_monitor_interval_ms),
        }

    @staticmethod
    def _elapsed_refuel_monitor_ms(timing_context):
        try:
            return float((time.perf_counter() - float(timing_context["refuel_monitor_tick_started_perf_s"])) * 1000.0)
        except Exception:
            return None

    def _record_refuel_monitor_tick_timing(
        self,
        timing_context,
        *,
        event_kind,
        skip_reason=None,
        failure_message=None,
        analysis_started=None,
        capture_duration_ms=None,
    ):
        model = self.refuel_camera_model
        if model is None:
            return None
        return model.record_refuel_monitor_timing(
            {
                "tick_index": timing_context.get("refuel_monitor_tick_index"),
                "event_kind": event_kind,
                "monitor_state": model.get_refuel_monitor_status().get("state"),
                "capture_duration_ms": capture_duration_ms,
                "total_latency_ms": self._elapsed_refuel_monitor_ms(timing_context),
                "skip_reason": skip_reason,
                "failure_message": failure_message,
                "analysis_started": analysis_started,
                "time_since_last_valid_sample_s": model._time_since_last_valid_sample_s(
                    timing_context.get("refuel_monitor_tick_started_monotonic_s")
                ),
            }
        )

    def _capture_refuel_monitor_sample(self):
        self._refuel_first_sample_pending = False
        model = self.refuel_camera_model
        if model is None or not self._is_refuel_tracking_enabled():
            return
        timing_context = self._new_refuel_monitor_timing_context()

        try:
            if model.is_refuel_diagnostic_capture_active():
                model.record_refuel_monitor_skip(
                    "diagnostic_capture_active",
                    state="paused",
                    message="Paused by refuel camera window",
                )
                self._record_refuel_monitor_tick_timing(
                    timing_context,
                    event_kind="skip",
                    skip_reason="diagnostic_capture_active",
                )
                return
        except Exception:
            pass

        try:
            if model.is_analysis_in_progress():
                model.record_refuel_monitor_skip(
                    "analysis_in_progress",
                    state="monitoring",
                    message="Waiting for refuel analysis",
                )
                self._record_refuel_monitor_tick_timing(
                    timing_context,
                    event_kind="skip",
                    skip_reason="analysis_in_progress",
                )
                return
        except Exception:
            pass

        model.record_refuel_monitor_attempt("Monitoring")
        try:
            result = self.controller.capture_refuel_image_with_context(
                analyze=True,
                context_overrides=timing_context,
            )
        except Exception as exc:
            self._handle_refuel_monitor_failure(f"Refuel capture failed: {exc}")
            self._record_refuel_monitor_tick_timing(
                timing_context,
                event_kind="failure",
                failure_message=f"Refuel capture failed: {exc}",
            )
            return

        frame = result[0] if isinstance(result, tuple) else result
        context = result[1] if isinstance(result, tuple) and len(result) > 1 else {}
        capture_duration_ms = None
        if isinstance(context, dict):
            capture_duration_ms = context.get("refuel_monitor_capture_duration_ms")
        if frame is None:
            self._handle_refuel_monitor_failure("Camera did not return a frame.")
            self._record_refuel_monitor_tick_timing(
                timing_context,
                event_kind="failure",
                failure_message="Camera did not return a frame.",
                analysis_started=False,
                capture_duration_ms=capture_duration_ms,
            )
            return

        model.record_refuel_monitor_success("Monitoring")
        if isinstance(context, dict) and context.get("analysis_started") is False:
            self._record_refuel_monitor_tick_timing(
                timing_context,
                event_kind="analysis_not_started",
                analysis_started=False,
                capture_duration_ms=capture_duration_ms,
            )

    def _is_refuel_tracking_enabled(self):
        checkbox = getattr(self, "enable_refuel_level_tracking_checkbox", None)
        if checkbox is None or not checkbox.isChecked():
            return False
        if self.refuel_camera_model is None:
            return False
        try:
            return bool(self.refuel_camera_model.is_refuel_tracking_enabled())
        except Exception:
            return bool(checkbox.isChecked())

    def _is_refuel_process_monitoring_enabled(self):
        checkbox = getattr(self, "enable_refuel_process_monitoring_checkbox", None)
        if checkbox is None or not checkbox.isChecked():
            return False
        if not self._is_refuel_tracking_enabled() or self.refuel_camera_model is None:
            return False
        getter = getattr(self.refuel_camera_model, "is_refuel_process_monitoring_enabled", None)
        if callable(getter):
            try:
                return bool(getter())
            except Exception:
                return False
        return True

    def _refuel_process_summary(self):
        if self.refuel_camera_model is None:
            return {}
        getter = getattr(self.refuel_camera_model, "get_refuel_process_summary", None)
        if callable(getter):
            try:
                return dict(getter() or {})
            except Exception:
                return {}
        return {}

    def _record_refuel_calibration_performance_marker(self, event_kind, source, extra=None):
        if self.refuel_camera_model is None or not self._is_refuel_performance_diagnostics_enabled():
            return None
        recorder = getattr(self.refuel_camera_model, "record_refuel_calibration_performance_marker", None)
        if not callable(recorder):
            return None
        try:
            return recorder(str(event_kind), self._active_calibration_refuel_payload(source, extra))
        except Exception as exc:
            print(f"[RefuelMonitor] calibration performance marker failed: {exc}")
            return None

    def _complete_refuel_calibration_performance_observation(self, outcome, source, extra=None):
        if self.refuel_camera_model is None or not self._is_refuel_performance_diagnostics_enabled():
            return None
        completer = getattr(self.refuel_camera_model, "complete_refuel_calibration_performance_observation", None)
        if not callable(completer):
            return None
        try:
            return completer(str(outcome), self._active_calibration_refuel_payload(source, extra))
        except Exception as exc:
            print(f"[RefuelMonitor] calibration performance completion failed: {exc}")
            return None

    def _remember_refuel_named_calibration_payload(self, payload):
        if not isinstance(payload, dict):
            return
        if not (payload.get("process_name") or payload.get("phase_name")):
            return
        remembered = dict(getattr(self, "_last_refuel_named_calibration_payload", {}) or {})
        for key in ("process_name", "phase_name", "session_id"):
            if payload.get(key) is not None:
                remembered[key] = payload.get(key)
        self._last_refuel_named_calibration_payload = remembered

    def _active_calibration_refuel_payload(self, source, extra=None):
        payload = {"source": str(source or "droplet_imager")}
        manager = getattr(getattr(self, "model", None), "calibration_manager", None)
        active = getattr(manager, "activeCalibration", None)
        if active is not None:
            payload["process_name"] = (
                getattr(active, "PROCESS_NAME", None)
                or getattr(active, "process_name", None)
                or active.__class__.__name__
            )
            payload["phase_name"] = getattr(active, "phase_name", None) or getattr(active, "PHASE_NAME", None)
            session_id = getattr(active, "session_id", None) or getattr(active, "_session_id", None)
            if session_id is not None:
                payload["session_id"] = session_id
        elif manager is not None:
            phase_name = getattr(manager, "phase_name", None)
            if phase_name:
                payload["phase_name"] = phase_name
        if isinstance(extra, dict):
            for key, value in extra.items():
                payload[str(key)] = value
        fallback = dict(getattr(self, "_last_refuel_named_calibration_payload", {}) or {})
        for key in ("process_name", "phase_name", "session_id"):
            if payload.get(key) is None and fallback.get(key) is not None:
                payload[key] = fallback[key]
        self._remember_refuel_named_calibration_payload(payload)
        return payload

    def _ensure_refuel_process_observation(self, source, extra=None):
        if not self._is_refuel_process_monitoring_enabled() or self.refuel_camera_model is None:
            return None
        payload = self._active_calibration_refuel_payload(source, extra)
        summary = self._refuel_process_summary()
        if not summary.get("active"):
            begin = getattr(self.refuel_camera_model, "begin_refuel_process_observation", None)
            if callable(begin):
                try:
                    return begin(payload)
                except Exception as exc:
                    print(f"[RefuelMonitor] process observation start failed: {exc}")
                    return None
        return summary.get("active")

    def _record_refuel_process_marker(self, event_kind, source, extra=None):
        if not self._is_refuel_process_monitoring_enabled() or self.refuel_camera_model is None:
            return None
        self._ensure_refuel_process_observation(source, extra)
        recorder = getattr(self.refuel_camera_model, "record_refuel_process_marker", None)
        if not callable(recorder):
            return None
        try:
            return recorder(str(event_kind), self._active_calibration_refuel_payload(source, extra))
        except Exception as exc:
            print(f"[RefuelMonitor] process marker failed: {exc}")
            return None

    def _complete_refuel_process_observation(self, outcome, source, extra=None, *, require_active=False):
        if not self._is_refuel_process_monitoring_enabled() or self.refuel_camera_model is None:
            return None
        summary = self._refuel_process_summary()
        if require_active and not summary.get("active"):
            recorder = getattr(self.refuel_camera_model, "record_refuel_process_marker", None)
            if callable(recorder):
                try:
                    return recorder(
                        str(extra.get("event_kind") if isinstance(extra, dict) and extra.get("event_kind") else source),
                        self._active_calibration_refuel_payload(source, extra),
                    )
                except Exception as exc:
                    print(f"[RefuelMonitor] terminal process marker failed: {exc}")
                    return None
            return None
        completer = getattr(self.refuel_camera_model, "complete_refuel_process_observation", None)
        if not callable(completer):
            return None
        try:
            return completer(str(outcome), self._active_calibration_refuel_payload(source, extra))
        except Exception as exc:
            print(f"[RefuelMonitor] process observation completion failed: {exc}")
            return None

    def _on_refuel_calibration_stage_changed(self, message, color=None):
        self._record_refuel_calibration_performance_marker(
            "stage_changed",
            "calibrationStageChanged",
            {
                "stage_message": str(message or ""),
                "color_name": str(color or ""),
            },
        )
        self._record_refuel_process_marker(
            "stage_changed",
            "calibrationStageChanged",
            {
                "stage_message": str(message or ""),
                "color_name": str(color or ""),
            },
        )

    def _on_refuel_calibration_completed(self):
        self._complete_refuel_calibration_performance_observation(
            "completed",
            "calibrationCompleted",
            {"event_kind": "calibration_completed"},
        )
        self._complete_refuel_process_observation(
            "completed",
            "calibrationCompleted",
            {"event_kind": "calibration_completed"},
        )

    def _on_refuel_calibration_queue_completed(self):
        self._complete_refuel_calibration_performance_observation(
            "queue_completed",
            "calibrationQueueCompleted",
            {"event_kind": "queue_completed"},
        )
        self._complete_refuel_process_observation(
            "queue_completed",
            "calibrationQueueCompleted",
            {"event_kind": "queue_completed"},
            require_active=True,
        )

    def _on_refuel_calibration_error(self, message):
        self._complete_refuel_calibration_performance_observation(
            "error",
            "calibrationError",
            {
                "event_kind": "calibration_error",
                "error_message": str(message or ""),
            },
        )
        self._complete_refuel_process_observation(
            "error",
            "calibrationError",
            {
                "event_kind": "calibration_error",
                "error_message": str(message or ""),
            },
        )

    def _on_refuel_sequence_state_changed(self, state, source, event_kind):
        if not isinstance(state, dict):
            state = {}
        status = str(state.get("status") or state.get("sequence_status") or "").strip().lower()
        payload = dict(state)
        payload["sequence_status"] = status
        terminal_statuses = {
            "completed",
            "complete",
            "success",
            "finished",
            "done",
            "error",
            "failed",
            "failure",
            "stopped",
            "cancelled",
            "canceled",
        }
        if status in terminal_statuses:
            outcome = "completed" if status in {"completed", "complete", "success", "finished", "done"} else status
            payload["event_kind"] = event_kind
            self._complete_refuel_calibration_performance_observation(outcome, source, payload)
            self._complete_refuel_process_observation(outcome, source, payload, require_active=True)
            return
        if status and status != "idle":
            self._record_refuel_calibration_performance_marker(event_kind, source, payload)
            self._record_refuel_process_marker(event_kind, source, payload)

    def _on_refuel_stream_capture_state_changed(self, state):
        self._on_refuel_sequence_state_changed(
            state,
            "streamCaptureStateChanged",
            "stream_capture_state_changed",
        )

    def _on_refuel_stream_sequence_state_changed(self, state):
        self._on_refuel_sequence_state_changed(
            state,
            "streamCalibrationSequenceStateChanged",
            "stream_sequence_state_changed",
        )

    def _on_refuel_droplet_sequence_state_changed(self, state):
        self._on_refuel_sequence_state_changed(
            state,
            "dropletCalibrationSequenceStateChanged",
            "droplet_sequence_state_changed",
        )

    @staticmethod
    def _format_refuel_status(status):
        if status is None or status == "":
            return None
        normalized = str(status).replace("_", " ").strip()
        if not normalized:
            return None
        return normalized[:1].upper() + normalized[1:]

    @staticmethod
    def _format_refuel_timing_label(timing):
        if not isinstance(timing, dict) or not timing:
            return "-"
        event_kind = str(timing.get("event_kind") or "")
        if event_kind == "skip":
            return f"Skipped: {timing.get('skip_reason') or 'monitor busy'}"
        if event_kind == "failure":
            return f"Failure: {timing.get('failure_message') or 'capture failed'}"
        if event_kind == "analysis_not_started":
            return "Analysis not started"

        def _fmt_ms(value):
            if value is None:
                return "-"
            try:
                return f"{float(value):.0f} ms"
            except Exception:
                return "-"

        capture = _fmt_ms(timing.get("capture_duration_ms"))
        detector = _fmt_ms(timing.get("detector_runtime_ms"))
        total = _fmt_ms(timing.get("total_latency_ms"))
        return f"Capture {capture} | Detector {detector} | Total {total}"

    @staticmethod
    def _format_refuel_process_label(process_enabled, summary):
        if not process_enabled:
            return "Process monitoring off"
        if not isinstance(summary, dict):
            return "Waiting for calibration"
        active = summary.get("active")
        if isinstance(active, dict) and active:
            name = active.get("phase_name") or active.get("process_name") or "calibration"
            return f"Monitoring {name}"
        last = summary.get("last")
        if isinstance(last, dict) and last:
            drift = last.get("drift_px")
            if drift is None:
                return "Drift unavailable"
            drift_per_ejection = last.get("drift_px_per_ejection")
            ejection_count = last.get("ejection_count_delta")
            try:
                if drift_per_ejection is not None and ejection_count is not None and int(ejection_count) > 0:
                    return (
                        f"Drift {float(drift):+.1f} px | "
                        f"{float(drift_per_ejection):+.3f} px/ejection"
                    )
                return f"Drift {float(drift):+.1f} px"
            except Exception:
                return f"Drift {drift} px"
        return "Waiting for calibration"

    @staticmethod
    def _format_refuel_process_result_label(summary):
        last = summary.get("last") if isinstance(summary, dict) else None
        if not isinstance(last, dict) or not last:
            return ""
        drift = last.get("drift_px")
        if drift is None:
            return "Last process: drift unavailable"
        try:
            drift_value = float(drift)
            if drift_value < 0:
                drift_text = f"level fell {abs(drift_value):.1f} px"
            elif drift_value > 0:
                drift_text = f"level rose {abs(drift_value):.1f} px"
            else:
                drift_text = "level stable"
        except Exception:
            drift_text = f"level changed by {drift} px"

        ejection_count = last.get("ejection_count_delta")
        drift_per_ejection = last.get("drift_px_per_ejection")
        if ejection_count is not None:
            try:
                ejection_count_value = int(ejection_count)
            except Exception:
                ejection_count_value = None
            if ejection_count_value is not None and ejection_count_value > 0:
                if drift_per_ejection is not None:
                    try:
                        return (
                            f"Last process: {drift_text} over {ejection_count_value} ejections "
                            f"({float(drift_per_ejection):+.3f} px/ejection)"
                        )
                    except Exception:
                        return (
                            f"Last process: {drift_text} over {ejection_count_value} ejections "
                            f"({drift_per_ejection} px/ejection)"
                        )
                return f"Last process: {drift_text} over {ejection_count_value} ejections"
        return f"Last process: {drift_text}"

    @staticmethod
    def _format_refuel_ejection_label(counter, summary):
        last = summary.get("last") if isinstance(summary, dict) else None
        if isinstance(last, dict) and last:
            ejection_count = last.get("ejection_count_delta")
            drift_per_ejection = last.get("drift_px_per_ejection")
            if ejection_count is not None:
                try:
                    count_text = f"{int(ejection_count)}"
                except Exception:
                    count_text = str(ejection_count)
                if drift_per_ejection is not None:
                    try:
                        return f"{count_text} | {float(drift_per_ejection):+.3f} px/ejection"
                    except Exception:
                        return f"{count_text} | {drift_per_ejection} px/ejection"
                source = last.get("ejection_count_source")
                return f"{count_text} ({source})" if source else count_text
        active = summary.get("active") if isinstance(summary, dict) else None
        if isinstance(active, dict) and active:
            try:
                observed = int((counter or {}).get("active_observed_ejection_delta") or 0)
                commanded = int((counter or {}).get("active_commanded_ejection_delta") or 0)
                return f"Process observed {observed} | commanded {commanded}"
            except Exception:
                return "Process counting"
        try:
            observed = int((counter or {}).get("observed_ejection_count") or 0)
            commanded = int((counter or {}).get("commanded_ejection_count") or 0)
            return f"Observed {observed} | commanded {commanded}"
        except Exception:
            return "-"

    def _refuel_advisory_message(self, process_enabled):
        if not process_enabled or self.refuel_camera_model is None:
            return None
        getter = getattr(self.refuel_camera_model, "get_refuel_advisory", None)
        if not callable(getter):
            return None
        try:
            advisory = getter() or {}
        except Exception:
            return None
        if not isinstance(advisory, dict) or not advisory.get("enabled"):
            return None
        message = str(advisory.get("message") or "").strip()
        return message or None

    def _latest_refuel_sample(self):
        model = self.refuel_camera_model
        if model is None:
            return None
        getter = getattr(model, "get_sample_trace", None)
        if callable(getter):
            try:
                trace = list(getter() or [])
                if trace:
                    return trace[-1]
            except Exception:
                pass
        level_getter = getattr(model, "get_current_level", None)
        if callable(level_getter):
            try:
                level = level_getter()
                if level is not None:
                    return {"level_px": level}
            except Exception:
                pass
        return None

    def _refuel_panel_refresh_version(self):
        model = self.refuel_camera_model
        if model is None:
            return None
        try:
            sample_count = len(getattr(model, "sample_trace", []) or [])
        except Exception:
            sample_count = 0

        timing_key = None
        try:
            timing_log = getattr(model, "refuel_monitor_timing_log", []) or []
            latest = getattr(model, "last_refuel_monitor_timing", None)
            if not isinstance(latest, dict) and timing_log:
                latest = timing_log[-1]
            latest = latest if isinstance(latest, dict) else {}
            timing_key = (
                len(timing_log),
                latest.get("tick_index"),
                latest.get("event_kind"),
                latest.get("detector_status"),
                latest.get("level_px"),
            )
        except Exception:
            timing_key = None

        marker_count = 0
        try:
            marker_count = len(getattr(model, "refuel_process_marker_log", []) or [])
        except Exception:
            marker_count = 0

        advisory_count = 0
        try:
            advisory_count = len(getattr(model, "refuel_advisory_log", []) or [])
        except Exception:
            advisory_count = 0

        ejection_event_count = 0
        try:
            ejection_event_count = int(getattr(model, "_refuel_ejection_next_event_index", 1) or 1) - 1
        except Exception:
            ejection_event_count = 0

        return (sample_count, timing_key, marker_count, advisory_count, ejection_event_count)

    def _schedule_refuel_level_panel_refresh(self, *args, force=False):
        timer = getattr(self, "refuel_panel_refresh_timer", None)
        if timer is None:
            self._refresh_refuel_level_panel()
            return

        version = self._refuel_panel_refresh_version()
        if force:
            if timer.isActive():
                timer.stop()
            self._refuel_panel_pending_version = None
            self._refuel_panel_rendered_version = version
            self._refresh_refuel_level_panel()
            return

        if version == self._refuel_panel_rendered_version or version == self._refuel_panel_pending_version:
            return
        self._refuel_panel_pending_version = version
        if timer.isActive():
            return

        min_interval_s = max(0.0, float(getattr(self, "refuel_monitor_interval_ms", 1000)) / 1000.0)
        last_refresh = getattr(self, "_last_refuel_panel_auto_refresh_monotonic", None)
        now = time.monotonic()
        if last_refresh is None or now - float(last_refresh) >= min_interval_s:
            delay_ms = 0
        else:
            delay_ms = max(1, int(round((min_interval_s - (now - float(last_refresh))) * 1000.0)))
        timer.start(delay_ms)

    def _run_refuel_level_panel_refresh(self):
        self._last_refuel_panel_auto_refresh_monotonic = time.monotonic()
        self._refuel_panel_rendered_version = (
            self._refuel_panel_pending_version
            if self._refuel_panel_pending_version is not None
            else self._refuel_panel_refresh_version()
        )
        self._refuel_panel_pending_version = None
        self._refresh_refuel_level_panel()

    def _refresh_refuel_level_panel(self, *_args):
        enabled = self._is_refuel_tracking_enabled()
        monitor_status = {}
        if self.refuel_camera_model is not None:
            getter = getattr(self.refuel_camera_model, "get_refuel_monitor_status", None)
            if callable(getter):
                try:
                    monitor_status = dict(getter() or {})
                except Exception:
                    monitor_status = {}
        monitor_state = str(monitor_status.get("state") or "off")
        monitor_message = str(
            monitor_status.get("message")
            or {
                "off": "Monitoring disabled",
                "starting": "Starting refuel camera",
                "monitoring": "Monitoring",
                "paused": "Paused by refuel camera window",
                "unavailable": "Refuel camera unavailable",
            }.get(monitor_state, "Monitoring disabled")
        )
        if not enabled:
            self.refuel_level_group.hide()
            self.refuel_level_value_label.setText("Level: -")
            self.refuel_level_status_label.setText("Off")
            self.refuel_level_last_update_label.setText("-")
            self.refuel_level_timing_label.setText("-")
            self.refuel_level_process_label.setText("Process monitoring off")
            self.refuel_level_ejection_label.setText("-")
            self.refuel_level_advisory_label.setText("Monitoring disabled")
            self.refuel_level_process_result_label.setText("")
            self.refuel_level_process_result_label.hide()
            self._refresh_refuel_level_chart()
            return

        self.refuel_level_group.show()
        timing = None
        if self.refuel_camera_model is not None:
            summary_getter = getattr(self.refuel_camera_model, "get_refuel_monitor_timing_summary", None)
            if callable(summary_getter):
                try:
                    timing = (summary_getter() or {}).get("latest")
                except Exception:
                    timing = None
        self.refuel_level_timing_label.setText(self._format_refuel_timing_label(timing))
        process_enabled = self._is_refuel_process_monitoring_enabled()
        process_summary = self._refuel_process_summary()
        self.refuel_level_process_label.setText(
            self._format_refuel_process_label(process_enabled, process_summary)
        )
        process_result_text = self._format_refuel_process_result_label(process_summary)
        self.refuel_level_process_result_label.setText(process_result_text)
        self.refuel_level_process_result_label.setVisible(bool(process_result_text))
        ejection_counter = {}
        if self.refuel_camera_model is not None:
            counter_getter = getattr(self.refuel_camera_model, "get_refuel_ejection_counter", None)
            if callable(counter_getter):
                try:
                    ejection_counter = dict(counter_getter() or {})
                except Exception:
                    ejection_counter = {}
        self.refuel_level_ejection_label.setText(
            self._format_refuel_ejection_label(ejection_counter, process_summary)
        )
        sample = self._latest_refuel_sample()
        if not sample:
            self.refuel_level_value_label.setText("Level: -")
            if monitor_state in ("starting", "paused", "unavailable"):
                self.refuel_level_status_label.setText(self._format_refuel_status(monitor_state) or "No sample")
            else:
                self.refuel_level_status_label.setText("No sample")
            self.refuel_level_last_update_label.setText("-")
            if monitor_state != "monitoring":
                advisory = monitor_message
            elif int(monitor_status.get("successful_captures") or 0) <= 0:
                advisory = "Waiting for first refuel sample"
            else:
                advisory = "No valid refuel level detected"
            advisory = self._refuel_advisory_message(process_enabled) or advisory
            self.refuel_level_advisory_label.setText(advisory)
            self._refresh_refuel_level_chart()
            return

        level = sample.get("level_px", sample.get("level"))
        if level is None:
            self.refuel_level_value_label.setText("Level: -")
        else:
            try:
                self.refuel_level_value_label.setText(f"Level: {float(level):.1f} px")
            except Exception:
                self.refuel_level_value_label.setText(f"Level: {level}")

        status = sample.get("status") or sample.get("detected_status") or sample.get("predicted_status")
        if status is None and self.refuel_camera_model is not None:
            live_getter = getattr(self.refuel_camera_model, "get_live_status", None)
            if callable(live_getter):
                try:
                    status = live_getter()
                except Exception:
                    status = None
        if status is None and level is not None:
            status = "Visible"
        self.refuel_level_status_label.setText(self._format_refuel_status(status) or "No sample")

        elapsed_s = sample.get("elapsed_s")
        timestamp_utc = sample.get("timestamp_utc")
        if elapsed_s is not None:
            try:
                self.refuel_level_last_update_label.setText(f"{float(elapsed_s):.1f} s")
            except Exception:
                self.refuel_level_last_update_label.setText(str(elapsed_s))
        elif timestamp_utc:
            self.refuel_level_last_update_label.setText(str(timestamp_utc))
        else:
            self.refuel_level_last_update_label.setText("-")

        advisory = "Level stable" if monitor_state == "monitoring" else monitor_message
        advisory_message = self._refuel_advisory_message(process_enabled)
        live_status = None
        if process_enabled and advisory_message:
            advisory = advisory_message
        elif process_enabled and self.refuel_camera_model is not None:
            live_getter = getattr(self.refuel_camera_model, "get_live_status", None)
            if callable(live_getter):
                try:
                    live_status = live_getter()
                except Exception:
                    live_status = None
            burst_getter = getattr(self.refuel_camera_model, "get_last_burst_result", None)
            if callable(burst_getter):
                try:
                    burst_result = burst_getter()
                    if isinstance(burst_result, dict) and burst_result.get("recommendation"):
                        advisory = str(burst_result["recommendation"])
                except Exception:
                    pass
        if monitor_state in ("starting", "paused", "unavailable"):
            advisory = advisory_message or monitor_message
        elif process_enabled and live_status == "In Band":
            advisory = "Level stable"
        elif process_enabled and live_status == "Low":
            advisory = "Level below target"
        elif process_enabled and live_status == "High":
            advisory = "Level above target"
        self.refuel_level_advisory_label.setText(advisory)
        self._refresh_refuel_level_chart()

    def _refresh_refuel_level_chart(self):
        bundle = getattr(self, "_refuel_level_chart_bundle", None)
        if not bundle:
            return
        valid_samples = []
        model = self.refuel_camera_model
        if model is not None and self._is_refuel_tracking_enabled():
            getter = getattr(model, "get_sample_trace", None)
            if callable(getter):
                try:
                    trace = list(getter() or [])
                    for sample in trace:
                        level = sample.get("level_px", sample.get("level")) if isinstance(sample, dict) else None
                        if level is None:
                            continue
                        if self._refuel_level_chart_full_scale_px is None and isinstance(sample, dict):
                            channel_height = sample.get("channel_height_px")
                            if channel_height is not None:
                                try:
                                    channel_height = float(channel_height)
                                    if channel_height > 0:
                                        self._refuel_level_chart_full_scale_px = channel_height
                                except Exception:
                                    pass
                        try:
                            level = float(level)
                        except Exception:
                            continue
                        sample_index = sample.get("sample_index") if isinstance(sample, dict) else None
                        try:
                            sample_index = int(sample_index)
                        except Exception:
                            sample_index = len(valid_samples) + 1
                        valid_samples.append({"sample_index": sample_index, "level_px": level})
                except Exception:
                    valid_samples = []
            if not valid_samples:
                log_getter = getattr(model, "get_level_log", None)
                if callable(log_getter):
                    try:
                        for index, level in enumerate(list(log_getter() or []), start=1):
                            if level is None:
                                continue
                            valid_samples.append({"sample_index": int(index), "level_px": float(level)})
                    except Exception:
                        valid_samples = []

        window_size = int(self.REFUEL_LEVEL_CHART_WINDOW_SAMPLES)
        visible_samples = valid_samples[-window_size:]
        points = [
            (float(index), float(sample["level_px"]))
            for index, sample in enumerate(visible_samples)
        ]
        visible_x_by_sample_index = {
            int(sample["sample_index"]): float(index)
            for index, sample in enumerate(visible_samples)
            if sample.get("sample_index") is not None
        }
        self._replace_xy_series(bundle["primary_series"], points)
        self._replace_xy_series(bundle["current_series"], points[-1:] if points else [])

        annotation_summary = {}
        if model is not None and self._is_refuel_tracking_enabled():
            annotation_summary = self._refuel_process_summary()
        active_process = annotation_summary.get("active") if isinstance(annotation_summary, dict) else None
        last_process = annotation_summary.get("last") if isinstance(annotation_summary, dict) else None
        process_for_annotations = active_process if isinstance(active_process, dict) and active_process else last_process

        def _float_or_none(value):
            if value is None:
                return None
            try:
                return float(value)
            except Exception:
                return None

        def _sample_x_or_none(value):
            if value is None:
                return None
            try:
                return visible_x_by_sample_index.get(int(value))
            except Exception:
                return None

        start_line_points = []
        end_line_points = []
        start_marker_points = []
        end_marker_points = []
        if isinstance(process_for_annotations, dict) and process_for_annotations:
            baseline_level = _float_or_none(process_for_annotations.get("baseline_level_px"))
            if baseline_level is not None:
                start_line_points = [(0.0, baseline_level), (float(window_size - 1), baseline_level)]
                start_x = _sample_x_or_none(process_for_annotations.get("baseline_sample_index"))
                if start_x is not None:
                    start_marker_points = [(start_x, baseline_level)]
            if not (isinstance(active_process, dict) and active_process):
                end_level = _float_or_none(process_for_annotations.get("end_level_px"))
                if end_level is not None:
                    end_line_points = [(0.0, end_level), (float(window_size - 1), end_level)]
                    end_x = _sample_x_or_none(process_for_annotations.get("end_sample_index"))
                    if end_x is not None:
                        end_marker_points = [(end_x, end_level)]

        self._replace_xy_series(bundle["process_start_line_series"], start_line_points)
        self._replace_xy_series(bundle["process_end_line_series"], end_line_points)
        self._replace_xy_series(bundle["process_start_marker_series"], start_marker_points)
        self._replace_xy_series(bundle["process_end_marker_series"], end_marker_points)
        bundle["axis_x"].setRange(0.0, float(window_size - 1))
        y_max = self._refuel_level_chart_full_scale_px
        if y_max is None or y_max <= 0:
            y_max = float(self.REFUEL_LEVEL_CHART_FALLBACK_HEIGHT_PX)
        bundle["axis_y"].setRange(0.0, float(y_max))

    def setup_shortcuts(self):
        """Set up keyboard shortcuts using the shortcut manager."""
        self.shortcut_manager.add_shortcut('Left', 'Move left', lambda: self.move_fraction_of_frame(-0.1,0))
        self.shortcut_manager.add_shortcut('Right', 'Move right', lambda: self.move_fraction_of_frame(0.1,0))
        self.shortcut_manager.add_shortcut('Up', 'Move up', lambda: self.move_fraction_of_frame(0,-0.1))
        self.shortcut_manager.add_shortcut('Down', 'Move down', lambda: self.move_fraction_of_frame(0,0.1))
        self.shortcut_manager.add_shortcut('Ctrl+Left', 'Move left', lambda: self.move_fraction_of_frame(-1,0))
        self.shortcut_manager.add_shortcut('Ctrl+Right', 'Move right', lambda: self.move_fraction_of_frame(1,0))
        self.shortcut_manager.add_shortcut('Ctrl+Up', 'Move up', lambda: self.move_fraction_of_frame(0,-1))
        self.shortcut_manager.add_shortcut('Ctrl+Down', 'Move down', lambda: self.move_fraction_of_frame(0,1))
        
        self.shortcut_manager.add_shortcut('k', 'Move forward', lambda: self.controller.set_relative_Y(5,manual=True))
        self.shortcut_manager.add_shortcut('j', 'Move backward', lambda: self.controller.set_relative_Y(-5,manual=True))
        self.shortcut_manager.add_shortcut('Ctrl+k', 'Move forward', lambda: self.controller.set_relative_Y(25,manual=True))
        self.shortcut_manager.add_shortcut('Ctrl+j', 'Move backward', lambda: self.controller.set_relative_Y(-25,manual=True))
        
        self.manual_flash_shortcut = self.shortcut_manager.add_shortcut('Space', "Toggle flash", self.toggle_flash)

        self.shortcut_manager.add_shortcut('1','Large refuel pressure decrease', lambda: self.controller.set_relative_refuel_pressure(-0.1,manual=True))
        self.shortcut_manager.add_shortcut('2','Small refuel pressure decrease', lambda: self.controller.set_relative_refuel_pressure(-0.01,manual=True))
        self.shortcut_manager.add_shortcut('3','Small refuel pressure increase', lambda: self.controller.set_relative_refuel_pressure(0.01,manual=True))
        self.shortcut_manager.add_shortcut('4','Large refuel pressure increase', lambda: self.controller.set_relative_refuel_pressure(0.1,manual=True))
        
        self.shortcut_manager.add_shortcut('6','Large print pressure decrease', lambda: self.controller.set_relative_print_pressure(-0.1,manual=True))
        self.shortcut_manager.add_shortcut('7','Small print pressure decrease', lambda: self.controller.set_relative_print_pressure(-0.01,manual=True))
        self.shortcut_manager.add_shortcut('8','Small print pressure increase', lambda: self.controller.set_relative_print_pressure(0.01,manual=True))
        self.shortcut_manager.add_shortcut('9','Large print pressure increase', lambda: self.controller.set_relative_print_pressure(0.1,manual=True))
  
        self.shortcut_manager.add_shortcut('z','Refuel only 20', lambda: self.controller.refuel_only(20))  
        self.shortcut_manager.add_shortcut('x','Refuel only 5', lambda: self.controller.refuel_only(5))  
        self.shortcut_manager.add_shortcut('c','Print only 5', lambda: self.controller.print_only(5))
        self.shortcut_manager.add_shortcut('v','Print only 20', lambda: self.controller.print_only(20))
        self.shortcut_manager.add_shortcut('t','Print 20 droplets', lambda: self.controller.print_droplets(20))

        self.shortcut_manager.add_shortcut('Shift+7','Home Regulators', lambda: self.controller.home_regulators())

        self.shortcut_manager.add_shortcut('Esc', 'Pause Action', lambda: self.main_window.pause_machine())

    @staticmethod
    def _manual_spinbox_line_edit(spinbox):
        return spinbox.lineEdit() if hasattr(spinbox, "lineEdit") else None

    def _manual_spinbox_is_being_edited(self, spinbox):
        line_edit = self._manual_spinbox_line_edit(spinbox)
        return spinbox.hasFocus() or (line_edit is not None and line_edit.hasFocus())

    @staticmethod
    def _manual_spinbox_step_subcontrol_hit(spinbox, event):
        option = QtWidgets.QStyleOptionSpinBox()
        spinbox.initStyleOption(option)
        if hasattr(event, "position"):
            point = event.position().toPoint()
        else:
            point = event.pos()
        subcontrol = spinbox.style().hitTestComplexControl(
            QtWidgets.QStyle.CC_SpinBox,
            option,
            point,
            spinbox,
        )
        return subcontrol in (QtWidgets.QStyle.SC_SpinBoxUp, QtWidgets.QStyle.SC_SpinBoxDown)

    def _register_manual_spinbox(self, spinbox, commit_handler):
        spinbox.setKeyboardTracking(False)
        spinbox.setFocusPolicy(QtCore.Qt.StrongFocus)
        spinbox.installEventFilter(self)
        spinbox.valueChanged.connect(
            lambda value, sb=spinbox: self._handle_manual_spinbox_value_changed(sb, value)
        )
        spinbox.editingFinished.connect(
            lambda sb=spinbox: self._handle_manual_spinbox_editing_finished(sb)
        )

        self._managed_manual_spinboxes.append(spinbox)
        self._manual_spinbox_committers[spinbox] = commit_handler
        self._manual_spinbox_focus_targets[spinbox] = spinbox
        self._manual_spinbox_typed_drafts[spinbox] = False

        line_edit = self._manual_spinbox_line_edit(spinbox)
        if line_edit is not None:
            line_edit.installEventFilter(self)
            line_edit.textEdited.connect(
                lambda _text, sb=spinbox: self._mark_manual_spinbox_typed_edit(sb)
            )
            self._manual_spinbox_focus_targets[line_edit] = spinbox

    def _mark_manual_spinbox_typed_edit(self, spinbox):
        self._manual_spinbox_typed_drafts[spinbox] = True
        self._refresh_manual_spinbox_focus_frame()

    def _dispatch_manual_spinbox_value(self, spinbox):
        if DropletImagingDialog._is_calibration_busy(self):
            return
        handler = self._manual_spinbox_committers.get(spinbox)
        if handler is not None:
            handler(spinbox.value())

    def _finish_manual_spinbox_edit(self, spinbox):
        self._manual_spinbox_typed_drafts[spinbox] = False
        spinbox.clearFocus()
        QTimer.singleShot(0, self._refresh_manual_spinbox_focus_frame)

    def _handle_manual_spinbox_value_changed(self, spinbox, _value):
        if spinbox in self._manual_spinbox_syncing:
            return
        if self._manual_spinbox_typed_drafts.get(spinbox, False):
            return
        self._dispatch_manual_spinbox_value(spinbox)
        self._finish_manual_spinbox_edit(spinbox)

    def _handle_manual_spinbox_editing_finished(self, spinbox):
        if spinbox in self._manual_spinbox_syncing:
            return
        if not self._manual_spinbox_typed_drafts.get(spinbox, False):
            QTimer.singleShot(0, self._refresh_manual_spinbox_focus_frame)
            return
        spinbox.interpretText()
        self._manual_spinbox_typed_drafts[spinbox] = False
        self._dispatch_manual_spinbox_value(spinbox)
        self._finish_manual_spinbox_edit(spinbox)

    def _refresh_manual_spinbox_focus_frame(self):
        active_spinbox = next(
            (
                spinbox
                for spinbox in self._managed_manual_spinboxes
                if self._manual_spinbox_is_being_edited(spinbox)
            ),
            None,
        )
        if active_spinbox is None:
            self._manual_focus_frame_active_spinbox = None
            self.manual_edit_focus_frame.hide()
            return
        self._manual_focus_frame_active_spinbox = active_spinbox
        self.manual_edit_focus_frame.setWidget(active_spinbox)
        self.manual_edit_focus_frame.show()
        self.manual_edit_focus_frame.raise_()

    def _sync_manual_spinbox_value(self, spinbox, value, force=False):
        typed_drafts = getattr(self, "_manual_spinbox_typed_drafts", None)
        syncing = getattr(self, "_manual_spinbox_syncing", None)
        if typed_drafts is None or syncing is None:
            spinbox.blockSignals(True)
            try:
                spinbox.setValue(value)
            finally:
                spinbox.blockSignals(False)
            return

        if not force and (
            typed_drafts.get(spinbox, False)
            or DropletImagingDialog._manual_spinbox_is_being_edited(self, spinbox)
        ):
            return
        typed_drafts[spinbox] = False
        syncing.add(spinbox)
        spinbox.blockSignals(True)
        try:
            spinbox.setValue(value)
        finally:
            spinbox.blockSignals(False)
            syncing.discard(spinbox)
        if hasattr(self, "manual_edit_focus_frame"):
            QTimer.singleShot(0, lambda: DropletImagingDialog._refresh_manual_spinbox_focus_frame(self))

    def _register_calibration_action_button(self, action_key: str, button: QtWidgets.QPushButton, *, default_text: str | None = None):
        key = str(action_key)
        self._calibration_action_buttons.setdefault(key, []).append(button)
        self._calibration_action_defaults.setdefault(key, str(default_text or button.text()))
        button.setProperty("calibration_action_key", key)
        return button

    def _get_calibration_action_buttons(self, action_key: str):
        return list(getattr(self, "_calibration_action_buttons", {}).get(str(action_key), []))

    def _set_calibration_action_text(self, action_key: str, text: str | None = None, *, use_default: bool = False):
        key = str(action_key)
        if use_default:
            text = getattr(self, "_calibration_action_defaults", {}).get(key, "")
        if text is None:
            return
        for button in self._get_calibration_action_buttons(key):
            button.setText(str(text))

    def _set_calibration_action_enabled(self, action_key: str, enabled: bool):
        for button in self._get_calibration_action_buttons(action_key):
            button.setEnabled(bool(enabled))

    def _set_calibration_action_state(
        self,
        action_key: str,
        ready: bool,
        missing: list[str] | None = None,
        *,
        tooltip_override: str | None = None,
    ):
        for button in self._get_calibration_action_buttons(action_key):
            self._set_btn_state(
                button,
                ready,
                missing,
                tooltip_override=tooltip_override,
            )

    @staticmethod
    def _normalize_printing_mode(value, *, fallback: str = "droplet") -> str:
        mode = str(value or "").strip().lower()
        if mode in {"droplet", "stream"}:
            return mode
        return str(fallback or "droplet")

    def _resolve_active_printer_head_printing_mode(self) -> str:
        rack_model = getattr(getattr(self, "model", None), "rack_model", None)
        if rack_model is None:
            rack_model = getattr(getattr(self.main_window, "model", None), "rack_model", None)
        if rack_model is None:
            return "droplet"

        getter = getattr(rack_model, "get_gripper_printer_head", None)
        if not callable(getter):
            return "droplet"

        try:
            printer_head = getter()
        except Exception:
            printer_head = None
        if printer_head is None:
            return "droplet"

        mode_getter = getattr(printer_head, "get_printing_mode", None)
        try:
            if callable(mode_getter):
                return self._normalize_printing_mode(mode_getter())
        except Exception:
            pass
        return self._normalize_printing_mode(getattr(printer_head, "printing_mode", None))

    def _apply_default_calibration_tab_from_printing_mode(self):
        tabs = getattr(self, "calibration_tabs", None)
        if tabs is None:
            return
        mode = self._resolve_active_printer_head_printing_mode()
        tabs.setCurrentWidget(self.stream_tab if mode == "stream" else self.droplet_tab)

    def _refresh_calibration_tab_lock_state(self, *_args):
        tabs = getattr(self, "calibration_tabs", None)
        if tabs is None:
            return
        tab_bar = tabs.tabBar()
        lock_tabs = (
            DropletImagingDialog._is_calibration_busy(self)
            or self._stream_capture_blocks_new_starts(self._get_stream_capture_state())
        )
        current_index = tabs.currentIndex()
        for idx in range(tabs.count()):
            tab_bar.setTabEnabled(idx, (not lock_tabs) or idx == current_index)

    def _build_optics_tab(self):
        layout = self.optics_tab.layout()
        layout.addWidget(self._create_lightweight_tab_section_header("Scale Bar Capture"))

        current_group = QtWidgets.QGroupBox("Current Factor")
        current_layout = QtWidgets.QVBoxLayout(current_group)
        current_layout.setContentsMargins(8, 8, 8, 8)
        current_layout.setSpacing(6)
        self.optics_current_factor_label = QtWidgets.QLabel()
        self.optics_current_factor_label.setWordWrap(True)
        self.optics_session_dir_label = QtWidgets.QLabel("Session: none")
        self.optics_session_dir_label.setWordWrap(True)
        self.optics_session_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        current_layout.addWidget(self.optics_current_factor_label)
        current_layout.addWidget(self.optics_session_dir_label)
        layout.addWidget(current_group)

        setup_group = QtWidgets.QGroupBox("Session")
        setup_grid = QtWidgets.QGridLayout(setup_group)
        setup_grid.setHorizontalSpacing(8)
        setup_grid.setVerticalSpacing(6)
        self.optics_division_um_spin = QtWidgets.QDoubleSpinBox()
        self.optics_division_um_spin.setRange(0.001, 1000.0)
        self.optics_division_um_spin.setDecimals(3)
        self.optics_division_um_spin.setSingleStep(1.0)
        self.optics_division_um_spin.setSuffix(" um")
        self.optics_division_um_spin.setValue(10.0)
        self.optics_division_um_spin.valueChanged.connect(lambda *_args: self._refresh_optics_controls())
        setup_grid.addWidget(QtWidgets.QLabel("Division size:"), 0, 0)
        setup_grid.addWidget(self.optics_division_um_spin, 0, 1)

        self.optics_start_session_button = QtWidgets.QPushButton("Start Session")
        self.optics_start_session_button.clicked.connect(self.start_optics_capture_session)
        self.optics_capture_frame_button = QtWidgets.QPushButton("Capture Frame")
        self.optics_capture_frame_button.clicked.connect(self.capture_optics_frame)
        self.optics_reject_last_button = QtWidgets.QPushButton("Reject Last Frame")
        self.optics_reject_last_button.clicked.connect(self.reject_last_optics_frame)
        self.optics_analyze_button = QtWidgets.QPushButton("End Session and Analyze")
        self.optics_analyze_button.clicked.connect(self.end_and_analyze_optics_session)
        self.optics_apply_button = QtWidgets.QPushButton("Apply Result")
        self.optics_apply_button.clicked.connect(self.apply_optics_result)
        self.optics_manual_override_button = QtWidgets.QPushButton("Manual Override")
        self.optics_manual_override_button.clicked.connect(self.manual_override_optics_factor)

        setup_grid.addWidget(self.optics_start_session_button, 1, 0, 1, 2)
        setup_grid.addWidget(self.optics_capture_frame_button, 2, 0, 1, 2)
        setup_grid.addWidget(self.optics_reject_last_button, 3, 0, 1, 2)
        setup_grid.addWidget(self.optics_analyze_button, 4, 0, 1, 2)
        setup_grid.addWidget(self.optics_apply_button, 5, 0, 1, 2)
        setup_grid.addWidget(self.optics_manual_override_button, 6, 0, 1, 2)
        layout.addWidget(setup_group)

        self.optics_status_label = QtWidgets.QLabel("Ready.")
        self.optics_status_label.setWordWrap(True)
        layout.addWidget(self.optics_status_label)

        self.optics_results_text = QtWidgets.QPlainTextEdit()
        self.optics_results_text.setReadOnly(True)
        self.optics_results_text.setMaximumHeight(180)
        self.optics_results_text.setPlainText("No optics analysis has been run yet.")
        layout.addWidget(self.optics_results_text)
        layout.addStretch(1)
        self._refresh_optics_controls()

    def _optics_camera_model(self):
        return getattr(self.model, "droplet_camera_model", None)

    def _optics_current_factor(self):
        cam = self._optics_camera_model()
        getter = getattr(cam, "get_um_per_pixel", None)
        try:
            if callable(getter):
                return float(getter())
        except Exception:
            pass
        return 1.5696

    def _optics_current_source(self):
        cam = self._optics_camera_model()
        getter = getattr(cam, "get_um_per_pixel_source", None)
        try:
            if callable(getter):
                return str(getter())
        except Exception:
            pass
        return "default"

    def _optics_step_conversion_source(self):
        cam = self._optics_camera_model()
        getter = getattr(cam, "get_step_conversion_source", None)
        try:
            if callable(getter):
                return str(getter())
        except Exception:
            pass
        return "preset"

    def _set_optics_status(self, text, color=None):
        if not hasattr(self, "optics_status_label"):
            return
        self.optics_status_label.setText(str(text))
        self.optics_status_label.setStyleSheet("" if not color else f"color:{color};")

    def _set_capture_request_pending(self, pending):
        self._capture_request_pending = bool(pending)
        self._refresh_manual_control_lock_state()
        self._refresh_optics_controls()

    def _on_droplet_capture_finished(self, *_args):
        if getattr(self, "_capture_request_pending", False):
            self._set_capture_request_pending(False)

    def _on_droplet_capture_failed(self, message=""):
        if getattr(self, "_capture_request_pending", False):
            self._set_capture_request_pending(False)
        tabs = getattr(self, "calibration_tabs", None)
        if tabs is not None and tabs.currentWidget() is getattr(self, "optics_tab", None):
            detail = str(message or "Camera did not return a frame.")
            self._set_optics_status(f"Capture failed: {detail}", "red")

    def _refresh_optics_controls(self):
        if not hasattr(self, "optics_start_session_button"):
            return
        active = bool(getattr(self, "_optics_session_active", False))
        capture_pending = bool(getattr(self, "_capture_request_pending", False))
        flash_fault_latched = self._is_flash_fault_latched()
        analysis = getattr(self, "_optics_last_analysis", None) or {}
        summary = dict(analysis.get("summary") or {})
        if "apply_ready" in summary:
            result_ready = summary.get("status") == "ok"
            auto_apply_ok = bool(summary.get("apply_ready"))
            failed_criteria = list(summary.get("failed_criteria") or [])
        else:
            scale_summary = dict(summary)
            accepted_count = int(scale_summary.get("accepted_count") or 0)
            cv_pct = scale_summary.get("cv_pct")
            try:
                cv_pct = float(cv_pct)
            except Exception:
                cv_pct = None
            result_ready = scale_summary.get("status") == "ok"
            auto_apply_ok = bool(result_ready and accepted_count >= 5 and cv_pct is not None and cv_pct <= 2.0)
            failed_criteria = [] if auto_apply_ok else ["scale gate failed"]

        self.optics_current_factor_label.setText(
            f"Current: {self._optics_current_factor():.6f} um/pixel ({self._optics_current_source()}); "
            f"motion conversion: {self._optics_step_conversion_source()}"
        )
        session_dir = getattr(self, "_optics_session_dir", None)
        self.optics_session_dir_label.setText(f"Session: {session_dir or 'none'}")
        self.optics_start_session_button.setEnabled(not active)
        self.optics_capture_frame_button.setEnabled((not capture_pending) and (not flash_fault_latched))
        self.optics_reject_last_button.setEnabled(active and not capture_pending)
        self.optics_analyze_button.setEnabled(active and not capture_pending)
        self.optics_apply_button.setEnabled(auto_apply_ok)
        if result_ready and not auto_apply_ok:
            detail = ", ".join(failed_criteria) if failed_criteria else "quality gates failed"
            self.optics_apply_button.setToolTip(f"Cannot apply until optics quality gates pass: {detail}.")
        else:
            self.optics_apply_button.setToolTip("")
        self.optics_manual_override_button.setEnabled(True)

    def _write_optics_session_json(self, filename, payload):
        session_dir = getattr(self, "_optics_session_dir", None)
        if not session_dir:
            return None
        path = Path(session_dir) / filename
        try:
            path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
            return path
        except Exception as exc:
            self._set_optics_status(f"Could not write {filename}: {exc}", "red")
            return None

    def start_optics_capture_session(self):
        cam = self._optics_camera_model()
        starter = getattr(cam, "start_saving", None)
        if not callable(starter):
            self._set_optics_status("Camera saving is not available in this model.", "red")
            return
        try:
            self.set_imaging_droplets(0)
        except Exception:
            pass
        try:
            session_dir = starter(prefix="scale_bar", image_ext="png")
        except TypeError:
            session_dir = starter()
        except Exception as exc:
            self._set_optics_status(f"Could not start optics capture session: {exc}", "red")
            return

        self._optics_session_active = True
        self._optics_session_dir = session_dir
        self._optics_rejected_filenames = []
        self._optics_last_analysis = None
        self.optics_results_text.setPlainText("Capture multiple micrometer frames, reject any bad frame, then end and analyze.")
        self._set_optics_status("Optics capture session started.", "green")
        self._write_optics_session_json(
            "scale_bar_rejections.json",
            {
                "schema_version": 1,
                "rejected_filenames": [],
                "updated_at": datetime.now().isoformat(),
            },
        )
        self._refresh_optics_controls()

    def capture_optics_frame(self):
        if getattr(self, "_capture_request_pending", False):
            self._set_optics_status("Capture already pending; wait for it to finish before requesting another.", "red")
            return
        active = bool(getattr(self, "_optics_session_active", False))
        checker = getattr(self.controller, "check_if_all_completed", None)
        try:
            commands_idle = bool(checker()) if callable(checker) else True
        except Exception:
            commands_idle = False
        if not commands_idle:
            self._set_optics_status(
                "Wait for all machine commands to finish before capturing an optics frame.",
                "red",
            )
            return
        try:
            if active:
                ok = self.controller.capture_droplet_image(capture_context="optics_scale_bar")
            else:
                ok = self.controller.capture_droplet_image()
        except Exception as exc:
            self._set_optics_status(f"Capture request failed: {exc}", "red")
            return
        if ok is False:
            self._set_optics_status("Capture was not queued; another capture may already be pending.", "red")
            return
        self._set_capture_request_pending(True)
        if active:
            self._set_optics_status("Capture requested.", "green")
        else:
            self._set_optics_status("Preview capture requested. Start a session when ready to save frames.", "green")

    def reject_last_optics_frame(self):
        if not getattr(self, "_optics_session_active", False):
            self._set_optics_status("Start a session before rejecting frames.", "red")
            return
        cam = self._optics_camera_model()
        getter = getattr(cam, "get_last_saved_capture", None)
        last_saved = None
        try:
            if callable(getter):
                last_saved = getter()
            else:
                last_saved = getattr(cam, "_last_saved", None)
        except Exception:
            last_saved = None
        filename = (last_saved or {}).get("filename") if isinstance(last_saved, dict) else None
        if not filename:
            self._set_optics_status("No saved frame is available to reject yet.", "red")
            return
        if filename not in self._optics_rejected_filenames:
            self._optics_rejected_filenames.append(filename)
        self._write_optics_session_json(
            "scale_bar_rejections.json",
            {
                "schema_version": 1,
                "rejected_filenames": list(self._optics_rejected_filenames),
                "updated_at": datetime.now().isoformat(),
            },
        )
        self._set_optics_status(f"Rejected {filename}.", "green")
        self._refresh_optics_controls()

    def end_and_analyze_optics_session(self):
        if not getattr(self, "_optics_session_active", False):
            self._set_optics_status("No optics session is active.", "red")
            return
        session_dir = getattr(self, "_optics_session_dir", None)
        cam = self._optics_camera_model()
        stopper = getattr(cam, "stop_saving", None)
        try:
            if callable(stopper):
                stopper()
        except Exception:
            pass
        self._optics_session_active = False

        if not session_dir:
            self._set_optics_status("No session directory is available for analysis.", "red")
            self._refresh_optics_controls()
            return

        try:
            from tools.scale_bar_conversion import analyze_scale_bar_directory

            scale_analysis = analyze_scale_bar_directory(
                session_dir,
                division_um=float(self.optics_division_um_spin.value()),
                rejected_filenames=set(self._optics_rejected_filenames),
            )
        except Exception as exc:
            self._set_optics_status(f"Scale-bar analysis failed: {exc}", "red")
            self._refresh_optics_controls()
            return

        self._write_optics_session_json("scale_bar_analysis.json", scale_analysis)
        scale_summary = dict((scale_analysis or {}).get("summary") or {})
        if scale_summary.get("status") != "ok":
            self._optics_last_analysis = scale_analysis
            self._render_optics_analysis(scale_analysis)
            self._refresh_optics_controls()
            return

        try:
            from tools.scale_bar_motion_conversion import (
                analyze_scale_bar_motion_directory,
                summarize_motion_fit_quality,
                write_debug_outputs,
            )

            motion_analysis = analyze_scale_bar_motion_directory(
                session_dir,
                rejected_filenames=set(self._optics_rejected_filenames),
            )
            motion_quality = summarize_motion_fit_quality(motion_analysis)
            motion_analysis["motion_quality"] = motion_quality
            debug_dir = Path(session_dir) / "motion_fit_summary"
            debug_summary = write_debug_outputs(
                motion_analysis,
                debug_dir,
                debug_limit=0,
                contact_limit=0,
                summary_only=True,
            )
            debug_index = str(debug_dir / "index.html")
            motion_analysis.setdefault("summary", {})["debug_index_path"] = debug_index
            motion_analysis["debug_summary"] = debug_summary
        except Exception as exc:
            self._set_optics_status(f"Motion conversion analysis failed: {exc}", "red")
            motion_analysis = {
                "schema_version": 1,
                "status": "error",
                "summary": {"status": "error", "run_directory": str(session_dir)},
                "motion_fit": {"status": "error", "error": str(exc), "fit_count": 0},
                "motion_quality": {
                    "schema_version": 1,
                    "status": "failed",
                    "apply_ready": False,
                    "failed_criteria": ["motion_analysis_failed"],
                },
            }
            motion_quality = dict(motion_analysis["motion_quality"])
            debug_index = None

        self._write_optics_session_json("scale_bar_motion_analysis.json", motion_analysis)
        analysis = self._build_combined_optics_analysis(scale_analysis, motion_analysis, motion_quality, debug_index)
        self._optics_last_analysis = analysis
        self._write_optics_session_json("optics_calibration_analysis.json", analysis)
        self._render_optics_analysis(analysis)
        self._refresh_optics_controls()

    def _scale_apply_ready(self, scale_summary):
        try:
            accepted_count = int(scale_summary.get("accepted_count") or 0)
            cv_pct = float(scale_summary.get("cv_pct"))
        except Exception:
            return False
        return bool(scale_summary.get("status") == "ok" and accepted_count >= 5 and cv_pct <= 2.0)

    def _build_combined_optics_analysis(self, scale_analysis, motion_analysis, motion_quality, debug_index):
        scale_summary = dict((scale_analysis or {}).get("summary") or {})
        motion_summary = dict((motion_analysis or {}).get("summary") or {})
        motion_fit = dict((motion_analysis or {}).get("motion_fit") or {})
        motion_quality = dict(motion_quality or {})
        scale_ready = self._scale_apply_ready(scale_summary)
        motion_ready = bool(motion_quality.get("apply_ready"))
        failed = []
        if not scale_ready:
            failed.append("scale_gate_failed")
        failed.extend(str(item) for item in (motion_quality.get("failed_criteria") or []))
        summary = {
            "schema_version": 1,
            "status": "ok" if scale_summary.get("status") == "ok" and motion_summary.get("status") == "ok" else "error",
            "apply_ready": bool(scale_ready and motion_ready),
            "failed_criteria": failed,
            "scale_apply_ready": bool(scale_ready),
            "motion_apply_ready": bool(motion_ready),
            "median_um_per_pixel": scale_summary.get("median_um_per_pixel"),
            "mean_um_per_pixel": scale_summary.get("mean_um_per_pixel"),
            "std_um_per_pixel": scale_summary.get("std_um_per_pixel"),
            "cv_pct": scale_summary.get("cv_pct"),
            "division_um": scale_summary.get("division_um"),
            "accepted_count": scale_summary.get("accepted_count"),
            "rejected_count": scale_summary.get("rejected_count"),
            "failed_count": scale_summary.get("failed_count"),
            "run_directory": scale_summary.get("run_directory"),
            "motion_fit_count": motion_fit.get("fit_count"),
            "motion_repeat_position_group_count": motion_summary.get("repeat_position_group_count"),
            "motion_rmse_2d_px": motion_fit.get("rmse_2d_px"),
            "motion_p95_2d_residual_px": motion_fit.get("p95_2d_residual_px"),
            "motion_max_2d_residual_px": motion_fit.get("max_2d_residual_px"),
            "motion_debug_index_path": debug_index or motion_summary.get("debug_index_path"),
        }
        return {
            "schema_version": 1,
            "status": "ok" if summary["apply_ready"] else "warning",
            "summary": summary,
            "scale_bar_analysis": scale_analysis,
            "motion_analysis": motion_analysis,
            "motion_quality": motion_quality,
        }

    def _render_optics_analysis(self, analysis):
        analysis = analysis or {}
        if "scale_bar_analysis" in analysis:
            summary = dict(analysis.get("summary") or {})
            scale_summary = dict((analysis.get("scale_bar_analysis") or {}).get("summary") or {})
            motion_fit = dict((analysis.get("motion_analysis") or {}).get("motion_fit") or {})
            motion_summary = dict((analysis.get("motion_analysis") or {}).get("summary") or {})
            motion_quality = dict(analysis.get("motion_quality") or {})
            lines = [
                "Measurement conversion",
                f"Median: {float(scale_summary.get('median_um_per_pixel')):.6f} um/pixel",
                f"Mean: {float(scale_summary.get('mean_um_per_pixel')):.6f} um/pixel",
                f"Std: {float(scale_summary.get('std_um_per_pixel')):.6f} um/pixel",
                f"CV: {float(scale_summary.get('cv_pct')):.3f}%",
                f"Accepted images: {int(scale_summary.get('accepted_count') or 0)}",
                f"Rejected images: {int(scale_summary.get('rejected_count') or 0)}",
                f"Failed images: {int(scale_summary.get('failed_count') or 0)}",
                "",
                "Motion conversion",
                f"Fit frames: {int(motion_fit.get('fit_count') or 0)}",
                f"Repeat groups: {int(motion_summary.get('repeat_position_group_count') or 0)}",
                f"2D RMSE: {float(motion_fit.get('rmse_2d_px') or 0.0):.3f} px",
                f"2D residual P95: {float(motion_fit.get('p95_2d_residual_px') or 0.0):.3f} px",
                f"2D residual max: {float(motion_fit.get('max_2d_residual_px') or 0.0):.3f} px",
                f"Debug report: {summary.get('motion_debug_index_path') or 'not available'}",
                f"Run directory: {scale_summary.get('run_directory')}",
            ]
            failed = list(summary.get("failed_criteria") or motion_quality.get("failed_criteria") or [])
            if bool(summary.get("apply_ready")):
                lines.append("Apply status: ready")
                self.optics_results_text.setPlainText("\n".join(lines))
                self._set_optics_status("Analysis complete. Measurement and motion calibration are ready to apply.", "green")
            else:
                lines.append(f"Apply status: blocked ({', '.join(failed) if failed else 'quality gates failed'})")
                self.optics_results_text.setPlainText("\n".join(lines))
                self._set_optics_status("Analysis complete, but apply requires measurement and motion quality gates to pass.", "red")
            return

        summary = dict(analysis.get("summary") or {})
        if summary.get("status") != "ok":
            self.optics_results_text.setPlainText(json.dumps(analysis, indent=2, default=str))
            self._set_optics_status("No valid scale-bar images were found.", "red")
            return
        lines = [
            f"Median: {float(summary.get('median_um_per_pixel')):.6f} um/pixel",
            f"Mean: {float(summary.get('mean_um_per_pixel')):.6f} um/pixel",
            f"Std: {float(summary.get('std_um_per_pixel')):.6f} um/pixel",
            f"CV: {float(summary.get('cv_pct')):.3f}%",
            f"Accepted images: {int(summary.get('accepted_count') or 0)}",
            f"Rejected images: {int(summary.get('rejected_count') or 0)}",
            f"Failed images: {int(summary.get('failed_count') or 0)}",
            f"Run directory: {summary.get('run_directory')}",
        ]
        self.optics_results_text.setPlainText("\n".join(lines))
        if int(summary.get("accepted_count") or 0) >= 5 and float(summary.get("cv_pct") or 999.0) <= 2.0:
            self._set_optics_status("Analysis complete. Result is ready to apply.", "green")
        else:
            self._set_optics_status("Analysis complete, but apply requires at least 5 valid images and CV <= 2%.", "red")

    def apply_optics_result(self):
        analysis = getattr(self, "_optics_last_analysis", None)
        if not analysis:
            self._set_optics_status("Run analysis before applying an optics result.", "red")
            return
        cam = self._optics_camera_model()
        applier = getattr(cam, "apply_optics_calibration", None)
        try:
            if callable(applier):
                applier(analysis)
            else:
                summary = dict(analysis.get("summary") or {})
                setter = getattr(cam, "set_um_per_pixel", None)
                if not callable(setter):
                    raise RuntimeError("Camera model cannot persist optics calibration.")
                setter(float(summary["median_um_per_pixel"]), source="scale_bar_calibration", summary=summary)
        except Exception as exc:
            self._set_optics_status(f"Could not apply optics calibration: {exc}", "red")
            return
        self._set_optics_status("Optics calibration applied.", "green")
        self._refresh_optics_controls()

    def manual_override_optics_factor(self):
        current = self._optics_current_factor()
        value, ok = QtWidgets.QInputDialog.getDouble(
            self,
            "Manual Optics Override",
            "Micrometers per pixel:",
            current,
            0.000001,
            10000.0,
            6,
        )
        if not ok:
            return
        response = self.main_window.popup_yes_no(
            "Apply Manual Override",
            f"Apply {float(value):.6f} um/pixel as the droplet imager optics calibration?",
        )
        if not self.main_window._is_yes_response(response):
            return
        cam = self._optics_camera_model()
        setter = getattr(cam, "set_um_per_pixel", None)
        if not callable(setter):
            self._set_optics_status("Camera model cannot persist optics calibration.", "red")
            return
        try:
            setter(
                float(value),
                source="manual_override",
                division_um=float(self.optics_division_um_spin.value()),
                run_directory=getattr(self, "_optics_session_dir", None),
            )
        except Exception as exc:
            self._set_optics_status(f"Could not apply manual override: {exc}", "red")
            return
        self._set_optics_status("Manual optics override applied.", "green")
        self._refresh_optics_controls()

    def _is_calibration_busy(self):
        manager = getattr(getattr(self, "model", None), "calibration_manager", None)
        if manager is None:
            return False

        active = getattr(manager, "activeCalibration", None)
        queue = getattr(manager, "calibration_queue", None) or []
        sweep_active = False
        if hasattr(manager, "is_pulsewidth_sweep_active"):
            try:
                sweep_active = bool(manager.is_pulsewidth_sweep_active())
            except Exception:
                sweep_active = False
        stream_busy = False
        stream_busy_getter = getattr(manager, "is_stream_gravimetric_capture_busy", None)
        if callable(stream_busy_getter):
            try:
                stream_busy = bool(stream_busy_getter())
            except Exception:
                stream_busy = False
        stream_sequence_busy = False
        stream_sequence_busy_getter = getattr(
            manager,
            "is_stream_calibration_sequence_busy",
            None,
        )
        if callable(stream_sequence_busy_getter):
            try:
                stream_sequence_busy = bool(stream_sequence_busy_getter())
            except Exception:
                stream_sequence_busy = False
        droplet_sequence_busy = False
        droplet_sequence_busy_getter = getattr(
            manager,
            "is_droplet_calibration_sequence_busy",
            None,
        )
        if callable(droplet_sequence_busy_getter):
            try:
                droplet_sequence_busy = bool(droplet_sequence_busy_getter())
            except Exception:
                droplet_sequence_busy = False
        return (
            active is not None
            or bool(queue)
            or sweep_active
            or stream_busy
            or stream_sequence_busy
            or droplet_sequence_busy
        )

    def _sync_manual_controls_from_model(self, force=False):
        DropletImagingDialog._sync_manual_spinbox_value(
            self,
            self.flash_duration_spinbox,
            self.model.droplet_camera_model.get_flash_duration(),
            force=force,
        )
        DropletImagingDialog._sync_manual_spinbox_value(
            self,
            self.flash_delay_spinbox,
            self.model.droplet_camera_model.get_flash_delay(),
            force=force,
        )
        DropletImagingDialog._sync_manual_spinbox_value(
            self,
            self.num_droplets_spinbox,
            self.model.droplet_camera_model.get_num_droplets(),
            force=force,
        )
        DropletImagingDialog._sync_manual_spinbox_value(
            self,
            self.print_pulse_width_spinbox,
            self.model.machine_model.get_print_pulse_width(),
            force=force,
        )
        DropletImagingDialog._sync_manual_spinbox_value(
            self,
            self.exposure_time_spinbox,
            self.model.droplet_camera_model.get_exposure_time(),
            force=force,
        )

    def _clear_manual_control_edit_state(self):
        typed_drafts = getattr(self, "_manual_spinbox_typed_drafts", {})
        for spinbox in getattr(self, "_managed_manual_spinboxes", []):
            typed_drafts[spinbox] = False
            spinbox.clearFocus()
        self._manual_focus_frame_active_spinbox = None
        if hasattr(self, "manual_edit_focus_frame"):
            self.manual_edit_focus_frame.hide()

    def _is_flash_fault_latched(self):
        getter = getattr(self.model.droplet_camera_model, "get_flash_fault_latched", None)
        if callable(getter):
            try:
                return bool(getter())
            except Exception:
                return False
        return bool(getattr(self.model.droplet_camera_model, "flash_fault_latched", False))

    def _flash_fault_reason_text(self):
        getter = getattr(self.model.droplet_camera_model, "get_flash_fault_reason_display", None)
        if callable(getter):
            try:
                return str(getter())
            except Exception:
                pass
        raw = str(getattr(self.model.droplet_camera_model, "flash_fault_reason", "") or "").strip()
        return raw.replace("_", " ") if raw else "None"

    def _is_online_stream_calibration_active(self):
        manager = getattr(getattr(self, "model", None), "calibration_manager", None)
        active = getattr(manager, "activeCalibration", None)
        return str(getattr(active, "phase_name", "") or "") == "online_stream_calibration"

    def _get_stream_calibration_sequence_state(self):
        mgr = getattr(self.model, "calibration_manager", None)
        getter = getattr(mgr, "get_stream_calibration_sequence_state", None)
        if callable(getter):
            try:
                state = getter()
            except Exception:
                state = None
            if isinstance(state, dict):
                return state
        return {
            "status": "idle",
            "status_message": "Ready to begin stream calibration sequence.",
            "error_message": "",
            "session_id": None,
            "session_outcome": None,
            "gripper_refresh_period_snapshot_ms": None,
            "gripper_pulse_duration_snapshot_ms": None,
            "gripper_was_open": None,
            "gripper_refresh_suspended": False,
        }

    def _get_droplet_calibration_sequence_state(self):
        mgr = getattr(self.model, "calibration_manager", None)
        getter = getattr(mgr, "get_droplet_calibration_sequence_state", None)
        if callable(getter):
            try:
                state = getter()
            except Exception:
                state = None
            if isinstance(state, dict):
                return state
        return {
            "status": "idle",
            "status_message": "Ready to begin droplet calibration sequence.",
            "error_message": "",
            "session_id": None,
            "session_outcome": None,
            "gripper_refresh_period_snapshot_ms": None,
            "gripper_pulse_duration_snapshot_ms": None,
            "gripper_was_open": None,
            "gripper_refresh_suspended": False,
        }

    @staticmethod
    def _filter_stream_calibration_sequence_missing(missing):
        ignored = {
            "Emergence time",
            "Emergence-derived nozzle center (image coords)",
        }
        return [
            str(item)
            for item in list(missing or [])
            if str(item) not in ignored
        ]

    def _recompute_online_stream_button_state(self):
        if not self._get_calibration_action_buttons("online_stream_calibration"):
            return

        if self._is_online_stream_calibration_active():
            self._set_calibration_action_state(
                "online_stream_calibration",
                True,
                tooltip_override="Stop the active online stream calibration.",
            )
            return

        readiness = dict(getattr(self, "_last_calibration_readiness", {}) or {})
        info = dict(readiness.get("online_stream_calibration", {}) or {})
        ready = bool(info.get("ready", True))
        missing = list(info.get("missing") or [])
        flash_fault_latched = self._is_flash_fault_latched()
        stream_capture_blocked = self._stream_capture_blocks_new_starts(self._get_stream_capture_state())

        if flash_fault_latched:
            self._set_calibration_action_state(
                "online_stream_calibration",
                False,
                tooltip_override="Unavailable while flash safety fault is latched.",
            )
            return
        if stream_capture_blocked:
            self._set_calibration_action_state(
                "online_stream_calibration",
                False,
                tooltip_override="Unavailable while a stream gravimetric capture session is open.",
            )
            return

        self._set_calibration_action_state("online_stream_calibration", ready, missing)

    def _recompute_stream_calibration_sequence_button_state(self):
        if not self._get_calibration_action_buttons("stream_calibrate_all"):
            return

        state = self._get_stream_calibration_sequence_state()
        status = str(state.get("status") or "idle")
        if status != "idle":
            self._set_calibration_action_text(
                "stream_calibrate_all",
                "Stop Calibration",
            )
            self._set_calibration_action_state(
                "stream_calibrate_all",
                True,
                tooltip_override="Stop the active stream calibration sequence.",
            )
            return
        self._set_calibration_action_text("stream_calibrate_all", use_default=True)

        readiness = dict(getattr(self, "_last_calibration_readiness", {}) or {})
        info = dict(readiness.get("online_stream_calibration", {}) or {})
        missing = self._filter_stream_calibration_sequence_missing(
            info.get("missing") or []
        )
        ready = len(missing) == 0
        flash_fault_latched = self._is_flash_fault_latched()
        stream_capture_blocked = self._stream_capture_blocks_new_starts(self._get_stream_capture_state())

        if flash_fault_latched:
            self._set_calibration_action_state(
                "stream_calibrate_all",
                False,
                tooltip_override="Unavailable while flash safety fault is latched.",
            )
            return
        if stream_capture_blocked:
            self._set_calibration_action_state(
                "stream_calibrate_all",
                False,
                tooltip_override="Unavailable while a stream gravimetric capture session is open.",
            )
            return

        self._set_calibration_action_state(
            "stream_calibrate_all",
            ready,
            missing,
        )

    def _recompute_droplet_calibration_sequence_button_state(self):
        if not self._get_calibration_action_buttons("calibrate_all"):
            return

        state = self._get_droplet_calibration_sequence_state()
        status = str(state.get("status") or "idle")
        if status != "idle":
            self._set_calibration_action_text(
                "calibrate_all",
                "Stop Calibration",
            )
            self._set_calibration_action_state(
                "calibrate_all",
                True,
                tooltip_override="Stop the active droplet calibration sequence.",
            )
            return
        self._set_calibration_action_text("calibrate_all", use_default=True)

        flash_fault_latched = self._is_flash_fault_latched()
        stream_capture_blocked = self._stream_capture_blocks_new_starts(self._get_stream_capture_state())

        if flash_fault_latched:
            self._set_calibration_action_state(
                "calibrate_all",
                False,
                tooltip_override="Unavailable while flash safety fault is latched.",
            )
            return
        if stream_capture_blocked:
            self._set_calibration_action_state(
                "calibrate_all",
                False,
                tooltip_override="Unavailable while a stream gravimetric capture session is open.",
            )
            return

        self._set_calibration_action_state("calibrate_all", True)

    def _apply_flash_safety_ui_state(self):
        fault_latched = self._is_flash_fault_latched()
        armed_getter = getattr(self.model.droplet_camera_model, "get_flash_session_armed", None)
        session_armed = bool(armed_getter()) if callable(armed_getter) else bool(
            getattr(self.model.droplet_camera_model, "flash_session_armed", False)
        )

        if fault_latched:
            self.camera_timer.stop()
            self.capturing = False
            repeat_button = getattr(self, "repeat_capture_button", None)
            if repeat_button is not None:
                repeat_button.setText("Start Repeated Capture")
            self.flash_safety_label.setText(
                "Flash safety fault latched: "
                f"{self._flash_fault_reason_text()}. Close and reopen the imager after PE8 is low."
            )
            self.flash_safety_label.setStyleSheet("color: darkred; font-weight: 600;")
        elif session_armed:
            self.flash_safety_label.setText("Flash session armed.")
            self.flash_safety_label.setStyleSheet("color: darkgreen;")
        else:
            self.flash_safety_label.setText("Flash session disarmed.")
            self.flash_safety_label.setStyleSheet("color: #555555;")

        if fault_latched:
            flash_widgets = ("flash_button", "benchmark_profile_button", "repeat_capture_button")
            for widget_name in flash_widgets:
                widget = getattr(self, widget_name, None)
                if widget is not None:
                    widget.setEnabled(False)
            for action_key in (
                "head_prime",
                "nozzle_position",
                "nozzle_focus",
                "droplet_emergence",
                "pressure_scan",
                "pressure_trajectory",
                "pressure_sweep_characterization",
                "droplet_characterization",
                "droplet_timecourse",
                "online_stream_calibration",
                "stream_calibrate_all",
                "calibrate_all",
                "pulsewidth_sweep",
            ):
                self._set_calibration_action_enabled(action_key, False)

        self._refresh_manual_control_lock_state()

    def _refresh_manual_control_lock_state(self, *_args):
        busy = DropletImagingDialog._is_calibration_busy(self)
        was_locked = getattr(self, "_manual_controls_locked", False)
        flash_fault_latched = self._is_flash_fault_latched()
        capture_pending = bool(getattr(self, "_capture_request_pending", False))

        if busy and not was_locked:
            DropletImagingDialog._clear_manual_control_edit_state(self)
            DropletImagingDialog._sync_manual_controls_from_model(self, force=True)

        self._manual_controls_locked = busy
        enabled = (not busy) and (not flash_fault_latched) and (not capture_pending)

        for widget in getattr(self, "_manual_lock_widgets", ()):
            if widget is not None:
                widget.setEnabled(enabled)

        if getattr(self, "manual_flash_shortcut", None) is not None:
            self.manual_flash_shortcut.setEnabled(enabled)

        if hasattr(self, "memory_recommendation_apply_btn"):
            if busy:
                self.memory_recommendation_apply_btn.setEnabled(False)
                self.memory_recommendation_apply_btn.setToolTip("Unavailable while calibration is running.")
            elif flash_fault_latched:
                self.memory_recommendation_apply_btn.setEnabled(False)
                self.memory_recommendation_apply_btn.setToolTip("Unavailable while flash safety fault is latched.")
            elif getattr(self, "_memory_recommendation_preview", None) is not None:
                self._render_calibration_memory_recommendation(self._memory_recommendation_preview)

        if hasattr(self, "load_selected_button"):
            self._update_load_button_state()

        if hasattr(self, "stream_capture_group"):
            self._sync_stream_capture_panel_state()

        if hasattr(self, "record_calibration_checkbox"):
            droplet_sequence_busy_getter = getattr(
                getattr(self.model, "calibration_manager", None),
                "is_droplet_calibration_sequence_busy",
                None,
            )
            droplet_sequence_busy = False
            if callable(droplet_sequence_busy_getter):
                try:
                    droplet_sequence_busy = bool(droplet_sequence_busy_getter())
                except Exception:
                    droplet_sequence_busy = False
            sequence_busy_getter = getattr(
                getattr(self.model, "calibration_manager", None),
                "is_stream_calibration_sequence_busy",
                None,
            )
            sequence_busy = False
            if callable(sequence_busy_getter):
                try:
                    sequence_busy = bool(sequence_busy_getter())
                except Exception:
                    sequence_busy = False
            if sequence_busy or droplet_sequence_busy:
                self.record_calibration_checkbox.setEnabled(False)

        self._recompute_online_stream_button_state()
        self._recompute_stream_calibration_sequence_button_state()
        self._recompute_droplet_calibration_sequence_button_state()
        self._refresh_calibration_tab_lock_state()

    def eventFilter(self, watched, event):
        spinbox = self._manual_spinbox_focus_targets.get(watched)
        if spinbox is not None:
            if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.FocusOut):
                QTimer.singleShot(0, self._refresh_manual_spinbox_focus_frame)
            elif watched is spinbox and event.type() == QtCore.QEvent.MouseButtonPress:
                if self._manual_spinbox_step_subcontrol_hit(spinbox, event):
                    self._manual_spinbox_typed_drafts[spinbox] = False
            elif event.type() == QtCore.QEvent.Wheel:
                self._manual_spinbox_typed_drafts[spinbox] = False
            elif event.type() == QtCore.QEvent.KeyPress and event.key() in (
                QtCore.Qt.Key_Up,
                QtCore.Qt.Key_Down,
                QtCore.Qt.Key_PageUp,
                QtCore.Qt.Key_PageDown,
            ):
                self._manual_spinbox_typed_drafts[spinbox] = False
        return super().eventFilter(watched, event)

    def move_fraction_of_frame(self, x_fraction, y_fraction):
        """
        Moves the camera frame by a fraction of the frame size.
        """
        dX, dY, dZ = self.model.droplet_camera_model.compute_move_by_fraction(x_fraction, y_fraction)
        self.controller.set_relative_coordinates(dX, dY, dZ, manual=False)

    def _set_equal_panel_widths(self):
        if not all(hasattr(self, name) for name in ("control_panel", "control_panel_scroll", "analysis_panel", "info_panel", "info_panel_scroll")):
            return

        margins = self.layout.contentsMargins()
        spacing = max(0, self.layout.spacing())
        available_width = max(
            0,
            self.width() - margins.left() - margins.right() - (2 * spacing),
        )
        control_width = max(380, min(460, available_width // 4 if available_width > 0 else 380))
        info_width = max(460, min(640, available_width // 3 if available_width > 0 else 460))

        self.control_panel.setMinimumWidth(control_width)
        self.control_panel.setMaximumWidth(control_width)
        self.control_panel_scroll.setMinimumWidth(control_width)
        self.control_panel_scroll.setMaximumWidth(control_width)
        self.info_panel.setMinimumWidth(info_width)
        self.info_panel.setMaximumWidth(info_width)
        self.info_panel_scroll.setMinimumWidth(info_width)
        self.info_panel_scroll.setMaximumWidth(info_width)
        self.analysis_panel.setMinimumWidth(560)
        self.analysis_panel.setMaximumWidth(16777215)
        self.analysis_panel.updateGeometry()

    def _create_lightweight_tab_section_header(self, title):
        header = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        left_divider = QtWidgets.QFrame()
        left_divider.setFrameShape(QtWidgets.QFrame.HLine)
        left_divider.setFrameShadow(QtWidgets.QFrame.Plain)
        left_divider.setStyleSheet("color: #666666;")

        label = QtWidgets.QLabel(str(title))
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setStyleSheet("color: #666666; font-weight: 600;")

        right_divider = QtWidgets.QFrame()
        right_divider.setFrameShape(QtWidgets.QFrame.HLine)
        right_divider.setFrameShadow(QtWidgets.QFrame.Plain)
        right_divider.setStyleSheet("color: #666666;")

        header_layout.addWidget(left_divider, 1)
        header_layout.addWidget(label, 0)
        header_layout.addWidget(right_divider, 1)
        return header

    def _create_collapsible_section(self, title, *, expanded=False):
        container = QtWidgets.QWidget()
        outer_layout = QtWidgets.QVBoxLayout(container)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(4)

        toggle = QtWidgets.QToolButton()
        toggle.setText(str(title))
        toggle.setCheckable(True)
        toggle.setChecked(bool(expanded))
        toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
        toggle.setStyleSheet(
            "QToolButton {"
            " font-weight: 600;"
            " border: none;"
            " padding: 4px 0px;"
            " text-align: left;"
            "}"
        )

        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QGridLayout(content)
        content_layout.setContentsMargins(8, 0, 0, 0)
        content_layout.setHorizontalSpacing(8)
        content_layout.setVerticalSpacing(6)
        content.setVisible(bool(expanded))

        outer_layout.addWidget(toggle)
        outer_layout.addWidget(content)
        return container, toggle, content, content_layout

    def _get_saved_acquisition_controls_expanded(self):
        try:
            if hasattr(self, "main_window"):
                return bool(
                    getattr(
                        self.main_window,
                        "_droplet_imaging_quick_controls_expanded",
                        type(self)._quick_controls_expanded_default,
                    )
                )
        except Exception:
            pass
        return bool(type(self)._quick_controls_expanded_default)

    def _set_acquisition_controls_expanded(self, expanded):
        expanded = bool(expanded)
        if hasattr(self, "acquisition_controls_content"):
            self.acquisition_controls_content.setVisible(expanded)
        if hasattr(self, "acquisition_controls_toggle"):
            self.acquisition_controls_toggle.setArrowType(
                QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow
            )
        type(self)._quick_controls_expanded_default = expanded
        try:
            if hasattr(self, "main_window"):
                setattr(self.main_window, "_droplet_imaging_quick_controls_expanded", expanded)
        except Exception:
            pass

    def _get_saved_info_panel_section_states(self):
        states = dict(type(self)._info_panel_section_default_states)
        try:
            if hasattr(self, "main_window"):
                raw = dict(
                    getattr(
                        self.main_window,
                        "_droplet_imaging_info_panel_sections_expanded",
                        {},
                    )
                    or {}
                )
                for key in states:
                    if key in raw:
                        states[key] = bool(raw[key])
        except Exception:
            pass
        return states

    def _get_saved_info_panel_section_expanded(self, key):
        return bool(self._get_saved_info_panel_section_states().get(str(key), False))

    def _set_info_panel_section_expanded(self, key, expanded, *, content_widget=None, toggle_button=None):
        expanded = bool(expanded)
        if content_widget is not None:
            content_widget.setVisible(expanded)
        if toggle_button is not None:
            toggle_button.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
        try:
            if hasattr(self, "main_window"):
                states = self._get_saved_info_panel_section_states()
                states[str(key)] = expanded
                setattr(self.main_window, "_droplet_imaging_info_panel_sections_expanded", states)
        except Exception:
            pass

    def _create_info_panel_section(self, key, title, body_widget):
        expanded = self._get_saved_info_panel_section_expanded(key)
        container = QtWidgets.QWidget()
        outer_layout = QtWidgets.QVBoxLayout(container)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(4)

        toggle = QtWidgets.QToolButton()
        toggle.setText(str(title))
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
        toggle.setStyleSheet(
            "QToolButton {"
            " font-weight: 600;"
            " border: none;"
            " padding: 4px 0px;"
            " text-align: left;"
            "}"
        )

        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(body_widget)
        content.setVisible(expanded)

        toggle.toggled.connect(
            lambda checked, section_key=str(key), section_content=content, section_toggle=toggle:
            self._set_info_panel_section_expanded(
                section_key,
                checked,
                content_widget=section_content,
                toggle_button=section_toggle,
            )
        )

        outer_layout.addWidget(toggle)
        outer_layout.addWidget(content)
        return container, toggle, content

    def _get_current_reagent_context_key(self):
        try:
            reagent = str(self._bridge_get_current_reagent_name() or "").strip()
        except Exception:
            reagent = ""
        return reagent or "__none__"

    def _get_saved_applied_summary_row_fingerprints(self):
        try:
            if hasattr(self, "main_window"):
                return dict(
                    getattr(
                        self.main_window,
                        "_droplet_imaging_applied_summary_rows",
                        {},
                    )
                    or {}
                )
        except Exception:
            pass
        return {}

    def _get_saved_applied_summary_row_fingerprint(self):
        record = self._get_applied_imaging_calibration_record()
        if isinstance(record, dict):
            fingerprint = record.get("source_row_fingerprint")
            if fingerprint is not None:
                return tuple(fingerprint)
        key = self._get_current_reagent_context_key()
        raw = self._get_saved_applied_summary_row_fingerprints().get(key)
        if raw is None:
            return None
        return tuple(raw)

    def _set_saved_applied_summary_row_fingerprint(self, fingerprint):
        key = self._get_current_reagent_context_key()
        try:
            if hasattr(self, "main_window"):
                mapping = self._get_saved_applied_summary_row_fingerprints()
                if fingerprint is None:
                    mapping.pop(key, None)
                else:
                    mapping[key] = tuple(fingerprint)
                setattr(self.main_window, "_droplet_imaging_applied_summary_rows", mapping)
        except Exception:
            pass

    def _sync_applied_summary_row_highlight(self):
        fingerprint = self._get_saved_applied_summary_row_fingerprint()
        if hasattr(self, "summary_table_model"):
            self.summary_table_model.set_applied_row_fingerprint(fingerprint)
        self._refresh_applied_calibration_banner()

    def _get_loaded_printer_head(self):
        try:
            rack_model = getattr(self.model, "rack_model", None)
            getter = getattr(rack_model, "get_gripper_printer_head", None)
            if callable(getter):
                return getter()
            return getattr(rack_model, "gripper_printer_head", None)
        except Exception:
            return None

    def _get_applied_imaging_calibration_record(self):
        em = getattr(self.model, "experiment_model", None)
        getter = getattr(em, "get_applied_imaging_calibration", None)
        if not callable(getter):
            return None
        try:
            return getter(printer_head=self._get_loaded_printer_head())
        except Exception:
            return None

    @staticmethod
    def _format_applied_record_value(record, key, decimals=None, suffix=""):
        value = (record or {}).get(key)
        if value in (None, ""):
            return "-"
        if decimals is None:
            return f"{value}{suffix}"
        try:
            return f"{float(value):.{decimals}f}{suffix}"
        except Exception:
            return f"{value}{suffix}"

    def _refresh_applied_calibration_status_label(self):
        self._refresh_applied_calibration_banner()

    def _refresh_applied_calibration_banner(self):
        label = getattr(self, "summary_applied_calibration_banner", None)
        if label is None:
            return
        record = self._get_applied_imaging_calibration_record()
        if not isinstance(record, dict):
            label.setText("No calibration applied to this design for the loaded stock/head.")
            color = self.color_dict.get("dark_red", "#8a0303")
            label.setStyleSheet(
                f"QLabel {{ background-color: {color}; color: white; padding: 5px; }}"
            )
            return
        run_id = record.get("run_id") or "-"
        measured = self._format_applied_record_value(record, "measured_volume_nL", 3, " nL")
        pw = self._format_applied_record_value(record, "pw_us", None, " us")
        pressure = self._format_applied_record_value(record, "pressure_psi", 3, " psi")
        label.setText(f"Applied: Run {run_id}, {measured}, PW {pw}, {pressure}")
        color = self.color_dict.get("dark_blue", "#063f99")
        label.setStyleSheet(
            f"QLabel {{ background-color: {color}; color: white; padding: 5px; }}"
        )

    def _selected_summary_row_matches_applied(self, raw=None):
        if raw is None:
            _, raw = self._selected_summary_row()
        if not raw:
            return False
        applied = self._get_saved_applied_summary_row_fingerprint()
        if applied is None:
            return False
        return tuple(self._summary_row_fingerprint(raw)) == tuple(applied)

    def _set_bridge_apply_button_state(self, state, reason=None):
        button = getattr(self, "bridge_apply_btn", None)
        if button is None:
            return
        state = str(state or "unavailable").strip().lower()
        self._bridge_apply_button_state = state

        neutral_style = ""
        primary_color = self.color_dict.get("dark_blue", "#063f99")
        primary_style = f"background-color: {primary_color}; color: white;"

        if state == "ready":
            button.setEnabled(True)
            button.setText("Apply selected calibration to design")
            button.setToolTip(str(reason or "Apply this calibration result to the experiment design."))
            button.setStyleSheet(primary_style)
        elif state == "applied":
            button.setEnabled(False)
            button.setText("Selected calibration is applied")
            button.setToolTip(str(reason or "This calibration result is already applied to the design."))
            button.setStyleSheet(neutral_style)
        else:
            button.setEnabled(False)
            button.setText("Apply selected calibration to design")
            button.setToolTip(str(reason or "Select a usable characterization result to preview a new ejection volume."))
            button.setStyleSheet(neutral_style)

    def _has_applied_calibration_design_context(self):
        if bool(getattr(self, "service_mode", False)):
            return False
        em = getattr(self.model, "experiment_model", None)
        printer_head = self._get_loaded_printer_head()
        if em is None or printer_head is None:
            return False
        resolver = getattr(em, "_resolve_applied_imaging_context", None)
        if callable(resolver):
            try:
                return resolver(printer_head=printer_head) is not None
            except Exception:
                return False
        try:
            return bool(self._bridge_get_current_reagent_name())
        except Exception:
            return False

    def _should_confirm_close_without_applied_calibration(self):
        if not self._has_applied_calibration_design_context():
            return False
        if self._get_applied_imaging_calibration_record() is None:
            return True
        return (
            str(getattr(self, "_bridge_apply_button_state", "")).lower() == "ready"
            and getattr(self, "bridge_apply_btn", None) is not None
            and self.bridge_apply_btn.isEnabled()
        )

    def _close_without_applied_calibration_message(self):
        if self._get_applied_imaging_calibration_record() is None:
            return (
                "No calibration result has been applied to this design for the loaded stock/head. "
                "Exit the droplet imager anyway?"
            )
        return (
            "A different calibration result is selected and ready to apply, but it has not been applied "
            "to the design. Exit the droplet imager anyway?"
        )

    def _build_applied_imaging_calibration_payload(self, raw, measured_volume_nL, *, source_row_fingerprint=None):
        raw = dict(raw or {})
        if source_row_fingerprint is None and raw:
            source_row_fingerprint = self._summary_row_fingerprint(raw)
        machine_model = getattr(self.model, "machine_model", None)

        def _machine_value(getter_name):
            getter = getattr(machine_model, getter_name, None)
            if callable(getter):
                try:
                    return getter()
                except Exception:
                    return None
            return None

        return {
            "printer_head": self._get_loaded_printer_head(),
            "measured_volume_nL": measured_volume_nL,
            "pw_us": raw.get("pw_us", _machine_value("get_print_pulse_width")),
            "pressure_psi": raw.get("pressure_psi", _machine_value("get_current_print_pressure")),
            "run_id": raw.get("run_id") or raw.get("run_no"),
            "phase": raw.get("phase"),
            "timestamp": raw.get("timestamp"),
            "source_row_fingerprint": source_row_fingerprint,
        }

    def _apply_print_settings_for_applied_calibration(self, applied_calibration, *, run_label="-"):
        applied_calibration = dict(applied_calibration or {})
        try:
            pw = int(round(float(applied_calibration.get("pw_us"))))
            pressure = float(applied_calibration.get("pressure_psi"))
        except Exception:
            return {
                "ok": False,
                "message": "Selected calibration is missing usable PW or pressure settings.",
            }

        def _after_apply(*_):
            try:
                DropletImagingDialog._sync_manual_spinbox_value(
                    self,
                    self.print_pulse_width_spinbox,
                    pw,
                    force=True,
                )
            except Exception:
                pass
            try:
                self.update_stage_and_log(
                    f"Loaded PW {pw} us and {pressure:.3f} psi from applied calibration Run {run_label or '-'}",
                    "blue",
                )
            except Exception:
                pass

        mgr = getattr(self.model, "calibration_manager", None)
        signal = getattr(mgr, "changeSettingsRequested", None)
        if signal is not None:
            try:
                signal.emit({"print_pulse_width": pw, "print_pressure": pressure}, _after_apply)
                return {
                    "ok": True,
                    "message": f"Loaded PW {pw} us and {pressure:.3f} psi.",
                }
            except Exception:
                pass

        applied_ok = False
        try:
            if hasattr(self.controller, "set_print_pulse_width"):
                self.controller.set_print_pulse_width(pw, manual=True)
                applied_ok = True
        except Exception:
            pass
        try:
            if hasattr(self.controller, "set_absolute_print_pressure"):
                self.controller.set_absolute_print_pressure(pressure, manual=True)
                applied_ok = True
            elif hasattr(self.controller, "set_print_pressure"):
                self.controller.set_print_pressure(pressure, manual=True)
                applied_ok = True
        except Exception:
            pass

        if applied_ok:
            _after_apply()
            return {
                "ok": True,
                "message": f"Loaded PW {pw} us and {pressure:.3f} psi.",
            }
        return {
            "ok": False,
            "message": "Could not apply settings via calibration manager or controller.",
        }

    @staticmethod
    def _summary_row_fingerprint(row):
        return _summary_row_fingerprint(row)

    def _chart_color(self, key, fallback):
        return QColor(self.color_dict.get(key, fallback))

    def _make_chart_pen(self, color_key, fallback, *, width=2, style=Qt.SolidLine):
        pen = QPen(self._chart_color(color_key, fallback))
        pen.setWidth(width)
        pen.setStyle(style)
        return pen

    @staticmethod
    def _make_hollow_scatter_series(*, marker_size=9.0):
        series = QtCharts.QScatterSeries()
        series.setMarkerShape(QtCharts.QScatterSeries.MarkerShapeCircle)
        series.setMarkerSize(marker_size)
        series.setBorderColor(QColor("#ffffff"))
        series.setColor(QColor(255, 255, 255, 0))
        return series

    def _create_online_stream_chart_bundle(
        self,
        *,
        title: str,
        y_title: str,
        use_scatter_data: bool = False,
        reference_color_key: str = "orange",
        reference_fallback: str = "#f39c12",
    ):
        chart = QtCharts.QChart()
        chart.setTheme(QtCharts.QChart.ChartThemeDark)
        chart.setTitle(title)
        chart.setBackgroundBrush(QBrush(self._chart_color("darker_gray", "#242424")))
        chart.legend().hide()

        axis_x = QtCharts.QValueAxis()
        axis_x.setTitleText("Delay From Emergence (us)")
        axis_x.setLabelFormat("%.0f")
        axis_y = QtCharts.QValueAxis()
        axis_y.setTitleText(y_title)
        axis_y.setLabelFormat("%.2f")
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)

        if use_scatter_data:
            primary_series = self._make_hollow_scatter_series()
            secondary_series = self._make_hollow_scatter_series()
        else:
            primary_series = QtCharts.QLineSeries()
            primary_series.setPen(self._make_chart_pen("light_blue", "#6fb6ff", width=2))
            secondary_series = QtCharts.QLineSeries()
            secondary_series.setPen(self._make_chart_pen("teal", "#2aa198", width=2, style=Qt.DashLine))
        current_series = QtCharts.QScatterSeries()
        current_series.setMarkerSize(11.0)
        current_series.setBorderColor(self._chart_color("light_gray", "#cfd8dc"))
        current_series.setColor(self._chart_color("green", "#2ecc71"))
        reference_series = QtCharts.QLineSeries()
        reference_series.setPen(self._make_chart_pen(reference_color_key, reference_fallback, width=2))
        marker_series = QtCharts.QLineSeries()
        marker_series.setPen(self._make_chart_pen("yellow", "#f1c40f", width=2, style=Qt.DashLine))
        segmented_fit_series = QtCharts.QLineSeries()
        segmented_fit_series.setPen(self._make_chart_pen("purple", "#d946ef", width=2))
        segmented_marker_series = QtCharts.QLineSeries()
        segmented_marker_series.setPen(self._make_chart_pen("green", "#2ecc71", width=2, style=Qt.DashLine))
        segmented_knee_series = QtCharts.QLineSeries()
        segmented_knee_series.setPen(self._make_chart_pen("gray", "#9ca3af", width=1, style=Qt.DotLine))
        segmented_second_knee_series = QtCharts.QLineSeries()
        segmented_second_knee_series.setPen(self._make_chart_pen("gray", "#9ca3af", width=1, style=Qt.DotLine))
        segmented_bracket_left_series = QtCharts.QLineSeries()
        segmented_bracket_left_series.setPen(self._make_chart_pen("gray", "#9ca3af", width=1, style=Qt.DashDotLine))
        segmented_bracket_right_series = QtCharts.QLineSeries()
        segmented_bracket_right_series.setPen(self._make_chart_pen("gray", "#9ca3af", width=1, style=Qt.DashDotLine))

        for series in (
            primary_series,
            secondary_series,
            current_series,
            reference_series,
            marker_series,
            segmented_fit_series,
            segmented_marker_series,
            segmented_knee_series,
            segmented_second_knee_series,
            segmented_bracket_left_series,
            segmented_bracket_right_series,
        ):
            chart.addSeries(series)
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)

        view = QtCharts.QChartView(chart)
        view.setRenderHint(QPainter.Antialiasing)
        view.setFocusPolicy(QtCore.Qt.NoFocus)
        view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        return {
            "chart": chart,
            "view": view,
            "axis_x": axis_x,
            "axis_y": axis_y,
            "primary_series": primary_series,
            "secondary_series": secondary_series,
            "current_series": current_series,
            "reference_series": reference_series,
            "marker_series": marker_series,
            "segmented_fit_series": segmented_fit_series,
            "segmented_marker_series": segmented_marker_series,
            "segmented_knee_series": segmented_knee_series,
            "segmented_second_knee_series": segmented_second_knee_series,
            "segmented_bracket_left_series": segmented_bracket_left_series,
            "segmented_bracket_right_series": segmented_bracket_right_series,
        }

    @staticmethod
    def _replace_xy_series(series, points):
        series.clear()
        for x_value, y_value in list(points or []):
            series.append(float(x_value), float(y_value))

    def _set_online_stream_axis_range(self, axis_x, axis_y, *, xs, ys):
        x_values = [float(value) for value in list(xs or [])]
        y_values = [float(value) for value in list(ys or [])]

        if x_values:
            x_min = min(x_values)
            x_max = max(x_values)
            if x_min == x_max:
                x_pad = max(1.0, abs(x_min) * 0.10)
            else:
                x_pad = max(1.0, (x_max - x_min) * 0.08)
            axis_x.setRange(float(x_min - x_pad), float(x_max + x_pad))
        else:
            axis_x.setRange(0.0, 1.0)

        if y_values:
            y_min = min(y_values)
            y_max = max(y_values)
            if y_min == y_max:
                y_pad = max(0.5, abs(y_min) * 0.10 if y_min else 0.5)
            else:
                y_pad = max(0.5, (y_max - y_min) * 0.12)
            axis_y.setRange(float(min(0.0, y_min - y_pad)), float(y_max + y_pad))
        else:
            axis_y.setRange(0.0, 1.0)

    def _clear_online_stream_chart_bundle(self, bundle):
        for key in (
            "primary_series",
            "secondary_series",
            "current_series",
            "reference_series",
            "marker_series",
            "segmented_fit_series",
            "segmented_marker_series",
            "segmented_knee_series",
            "segmented_second_knee_series",
            "segmented_bracket_left_series",
            "segmented_bracket_right_series",
        ):
            bundle[key].clear()
        bundle["axis_x"].setRange(0.0, 1.0)
        bundle["axis_y"].setRange(0.0, 1.0)

    def _reset_online_stream_debug_view(self, *, hide=True):
        if hasattr(self, "_online_stream_flow_chart_bundle"):
            self._clear_online_stream_chart_bundle(self._online_stream_flow_chart_bundle)
        if hasattr(self, "_online_stream_tail_chart_bundle"):
            self._clear_online_stream_chart_bundle(self._online_stream_tail_chart_bundle)
        self._online_stream_debug_active = False
        if hide and hasattr(self, "online_stream_plot_container"):
            self.online_stream_plot_container.hide()

    def _update_online_stream_flow_chart(self, flow_plot: dict | None):
        plot = dict(flow_plot or {})
        bundle = self._online_stream_flow_chart_bundle
        point_rows = [dict(row or {}) for row in list(plot.get("points") or [])]
        committed_points = [
            (float(row["x_us"]), float(row["y_nl"]))
            for row in point_rows
            if row.get("x_us") is not None and row.get("y_nl") is not None and not bool(row.get("provisional"))
        ]
        provisional_points = [
            (float(row["x_us"]), float(row["y_nl"]))
            for row in point_rows
            if row.get("x_us") is not None and row.get("y_nl") is not None and bool(row.get("provisional"))
        ]
        current_point = dict(plot.get("current_frame_point") or {})
        current_points = []
        if current_point.get("x_us") is not None and current_point.get("y_nl") is not None:
            current_points = [(float(current_point["x_us"]), float(current_point["y_nl"]))]
            current_color = self._chart_color(
                "green" if bool(current_point.get("accepted")) else "dark_red",
                "#2ecc71" if bool(current_point.get("accepted")) else "#c0392b",
            )
            bundle["current_series"].setColor(current_color)
            bundle["current_series"].setBorderColor(current_color)

        fit = dict(plot.get("fit") or {})
        fit_points = []
        if (
            fit.get("x_start_us") is not None
            and fit.get("x_end_us") is not None
            and fit.get("slope_nl_per_us") is not None
            and fit.get("intercept_nl") is not None
        ):
            x_start = float(fit["x_start_us"])
            x_end = float(fit["x_end_us"])
            slope = float(fit["slope_nl_per_us"])
            intercept = float(fit["intercept_nl"])
            fit_points = [
                (x_start, intercept + (slope * x_start)),
                (x_end, intercept + (slope * x_end)),
            ]

        self._replace_xy_series(bundle["primary_series"], committed_points)
        self._replace_xy_series(bundle["secondary_series"], provisional_points)
        self._replace_xy_series(bundle["current_series"], current_points)
        self._replace_xy_series(bundle["reference_series"], fit_points)
        self._replace_xy_series(bundle["marker_series"], [])

        all_xs = [x for x, _ in committed_points + provisional_points + current_points + fit_points]
        all_ys = [y for _, y in committed_points + provisional_points + current_points + fit_points]
        self._set_online_stream_axis_range(bundle["axis_x"], bundle["axis_y"], xs=all_xs, ys=all_ys)

    def _update_online_stream_tail_chart(self, tail_plot: dict | None):
        plot = dict(tail_plot or {})
        bundle = self._online_stream_tail_chart_bundle
        scout_points = [
            (float(row["x_us"]), float(row["y_px"]))
            for row in list(plot.get("scout_points") or [])
            if dict(row or {}).get("x_us") is not None and dict(row or {}).get("y_px") is not None
        ]
        backtrack_points = [
            (float(row["x_us"]), float(row["y_px"]))
            for row in list(plot.get("backtrack_points") or [])
            if dict(row or {}).get("x_us") is not None and dict(row or {}).get("y_px") is not None
        ]
        current_point = dict(plot.get("current_frame_point") or {})
        current_points = []
        if current_point.get("x_us") is not None and current_point.get("y_px") is not None:
            current_points = [(float(current_point["x_us"]), float(current_point["y_px"]))]
            current_color = self._chart_color(
                "green" if bool(current_point.get("accepted")) else "dark_red",
                "#2ecc71" if bool(current_point.get("accepted")) else "#c0392b",
            )
            bundle["current_series"].setColor(current_color)
            bundle["current_series"].setBorderColor(current_color)

        baseline_width_px = plot.get("baseline_width_px")
        tail_start_x_us = plot.get("tail_start_x_us")
        segmented_tail = dict(plot.get("segmented_tail") or {})
        segmented_status = str(segmented_tail.get("status") or "")
        segmented_fit_points = [
            (float(row["delay_from_emergence_us"]), float(row["fitted_width_px"]))
            for row in list(segmented_tail.get("fit_points") or [])
            if dict(row or {}).get("delay_from_emergence_us") is not None
            and dict(row or {}).get("fitted_width_px") is not None
        ]
        segmented_start_x_us = segmented_tail.get("tail_start_delay_from_emergence_us")
        segmented_knee_x_us = segmented_tail.get("knee_delay_from_emergence_us")
        segmented_second_knee_x_us = segmented_tail.get("second_knee_delay_from_emergence_us")
        segmented_bracket_left_x_us = None
        segmented_bracket_right_x_us = None
        if str(segmented_tail.get("tail_start_source") or "") == "three_two_midpoint":
            segmented_bracket_left_x_us = segmented_tail.get("three_break_tail_start_delay_from_emergence_us")
            segmented_bracket_right_x_us = segmented_tail.get("two_break_tail_start_delay_from_emergence_us")

        all_xs = [x for x, _ in scout_points + backtrack_points + current_points + segmented_fit_points]
        if tail_start_x_us is not None:
            all_xs.append(float(tail_start_x_us))
        for guide_x in (
            segmented_start_x_us,
            segmented_knee_x_us,
            segmented_second_knee_x_us,
            segmented_bracket_left_x_us,
            segmented_bracket_right_x_us,
        ):
            if guide_x is not None:
                all_xs.append(float(guide_x))
        all_ys = [y for _, y in scout_points + backtrack_points + current_points + segmented_fit_points]
        if baseline_width_px is not None:
            all_ys.append(float(baseline_width_px))

        self._set_online_stream_axis_range(bundle["axis_x"], bundle["axis_y"], xs=all_xs, ys=all_ys)

        x_min = bundle["axis_x"].min()
        x_max = bundle["axis_x"].max()
        y_min = bundle["axis_y"].min()
        y_max = bundle["axis_y"].max()

        baseline_points = []
        if baseline_width_px is not None:
            baseline_points = [(x_min, float(baseline_width_px)), (x_max, float(baseline_width_px))]
        tail_start_points = []
        if tail_start_x_us is not None:
            tail_start_points = [(float(tail_start_x_us), y_min), (float(tail_start_x_us), y_max)]
        def _vertical_guide(x_value):
            if x_value is None:
                return []
            return [(float(x_value), y_min), (float(x_value), y_max)]

        self._replace_xy_series(bundle["primary_series"], scout_points)
        self._replace_xy_series(bundle["secondary_series"], backtrack_points)
        self._replace_xy_series(bundle["current_series"], current_points)
        self._replace_xy_series(bundle["reference_series"], baseline_points)
        self._replace_xy_series(bundle["marker_series"], tail_start_points)
        self._replace_xy_series(bundle["segmented_fit_series"], segmented_fit_points)
        self._replace_xy_series(bundle["segmented_marker_series"], _vertical_guide(segmented_start_x_us))
        self._replace_xy_series(bundle["segmented_knee_series"], _vertical_guide(segmented_knee_x_us))
        self._replace_xy_series(bundle["segmented_second_knee_series"], _vertical_guide(segmented_second_knee_x_us))
        self._replace_xy_series(bundle["segmented_bracket_left_series"], _vertical_guide(segmented_bracket_left_x_us))
        self._replace_xy_series(bundle["segmented_bracket_right_series"], _vertical_guide(segmented_bracket_right_x_us))

        title = "Attached Width vs Time"
        if segmented_status == "running":
            title = f"{title} | segmented fit running..."
        elif segmented_start_x_us is not None:
            runtime_label = "-" if tail_start_x_us is None else f"{float(tail_start_x_us):.0f}"
            segmented_label = f"{float(segmented_start_x_us):.0f}"
            title = f"{title} | runtime {runtime_label} us | segmented {segmented_label} us"
            segmented_window_step = segmented_tail.get("segmented_tail_source_window_step_index")
            if segmented_window_step is not None:
                title = f"{title} | segmented window step={int(segmented_window_step)}"
            runtime_volume = segmented_tail.get("runtime_predicted_volume_nl")
            segmented_volume = segmented_tail.get("predicted_volume_nl")
            volume_parts = []
            if runtime_volume is not None:
                volume_parts.append(f"runtime vol {float(runtime_volume):.4g} nL")
            if segmented_volume is not None:
                volume_parts.append(f"segmented vol {float(segmented_volume):.4g} nL")
            if volume_parts:
                title = f"{title} | " + " | ".join(volume_parts)
        trace_window_step = plot.get("width_trace_source_window_step_index")
        if trace_window_step is not None:
            title = f"{title} | trace window step={int(trace_window_step)}"
        bundle["chart"].setTitle(title)

    def on_online_stream_debug_updated(self, payload):
        data = dict(payload or {})
        if str(data.get("phase_name") or "") != "online_stream_calibration":
            return
        self._online_stream_debug_active = True
        self.online_stream_plot_container.show()
        if str(data.get("subphase") or "") == "prepare":
            self._clear_online_stream_chart_bundle(self._online_stream_flow_chart_bundle)
            self._clear_online_stream_chart_bundle(self._online_stream_tail_chart_bundle)
        self._update_online_stream_flow_chart(data.get("flow_plot"))
        self._update_online_stream_tail_chart(data.get("tail_plot"))

    def _maybe_hide_online_stream_debug_for_nonstream_preview(self):
        if getattr(self, "_online_stream_debug_active", False) and not self._is_online_stream_calibration_active():
            self._reset_online_stream_debug_view(hide=True)
    
    def numpy_to_qimage(self,image):
        """
        Converts a numpy array (captured image) to a QImage.
        """
        if image is None:
            return QImage()  # return a null QImage if no frame

        arr = np.asarray(image)
        if arr.ndim == 2:
            height, width = arr.shape
            return QImage(arr.data, width, height, width, QImage.Format_Grayscale8).copy()
        if arr.ndim != 3:
            print("Warning: expected image with 2 or 3 dimensions, but got", getattr(arr, "shape", None))
            return QImage()

        height, width, channels = arr.shape
        if channels == 4:
            bytes_per_line = channels * width
            return QImage(arr.data, width, height, bytes_per_line, QImage.Format_RGBA8888).copy()
        if channels != 3:
            print("Warning: expected 3 or 4 channels, but got", channels)
            return QImage()

        bytes_per_line = channels * width
        qimage = QImage(
            arr.data,              # the actual data (byte array)
            width,
            height,
            bytes_per_line,
            QImage.Format_RGB888  # We assume the data is truly RGB
        )
        return qimage.copy()

    def toggle_repeat_capture(self):
        """
        Starts or stops capturing images based on the button toggle.
        """
        if self.capturing:
            self.camera_timer.stop()
            self.repeat_capture_button.setText("Start Repeated Capture")
        else:
            self.enter_repeat_capture_mode()
            self.camera_timer.start(100)  # Capture every 100 milliseconds
            self.repeat_capture_button.setText("Stop Repeated Capture")
        self.capturing = not self.capturing

    def enter_repeat_capture_mode(self):
        """
        Enters the repeat capture mode.
        """
        DropletImagingDialog._sync_manual_spinbox_value(self, self.exposure_time_spinbox, 20000, force=True)
        self.set_exposure_time(20000)
        DropletImagingDialog._sync_manual_spinbox_value(self, self.num_droplets_spinbox, 0, force=True)
        self.set_imaging_droplets(0)

    def apply_benchmark_capture_profile(self):
        """
        Apply a fixed, fast capture profile for throughput benchmarking.
        """
        if DropletImagingDialog._is_calibration_busy(self):
            return
        self.controller.set_droplet_capture_profile("throughput")
        self.controller.set_command_dispatch_interval(20)
        DropletImagingDialog._sync_manual_spinbox_value(self, self.flash_delay_spinbox, 5000, force=True)
        self.set_flash_delay(5000)
        DropletImagingDialog._sync_manual_spinbox_value(self, self.flash_duration_spinbox, 1000, force=True)
        self.set_flash_duration(1000)
        DropletImagingDialog._sync_manual_spinbox_value(self, self.exposure_time_spinbox, 20000, force=True)
        self.set_exposure_time(20000)
        DropletImagingDialog._sync_manual_spinbox_value(self, self.num_droplets_spinbox, 1, force=True)
        self.set_imaging_droplets(1)

    def toggle_flash(self):
        """
        Triggers a flash for the droplet imaging.
        """
        if DropletImagingDialog._is_calibration_busy(self):
            return
        if getattr(self, "_capture_request_pending", False):
            return
        if self._is_flash_fault_latched():
            return
        ok = self.controller.capture_droplet_image()
        if ok is not False:
            self._set_capture_request_pending(True)

    def toggle_saving(self):
        if self.saving_active:
            self.model.droplet_camera_model.stop_saving()
            self.saving_active = False
            self.save_button.setText('Save Images')
        else:
            self.model.droplet_camera_model.start_saving()
            self.saving_active = True
            self.save_button.setText('Saving')

    def toggle_analyzing(self):
        """
        Toggles whether the model should analyze the captured images.
        """
        if self.analysis_active:
            self.model.droplet_camera_model.stop_analyzing()
            self.analysis_active = False
            self.analyze_button.setText('Analyze Images')
        else:
            self.model.droplet_camera_model.start_analyzing()
            self.analysis_active = True
            self.analyze_button.setText('Analyzing')

    def update_analysis_parameters(self):
        """
        Updates the analysis parameters.
        """
        intensity_threshold = self.intensity_threshold_spinbox.value()
        circularity_threshold = self.circularity_threshold_spinbox.value()
        min_area = self.min_area_spinbox.value()
        edge_margin = self.edge_margin_spinbox.value()
        self.model.droplet_camera_model.set_analysis_parameters(intensity_threshold, circularity_threshold, min_area, edge_margin)


    def set_flash_duration(self, duration):
        """
        Sets the duration of the flash.
        """
        self.controller.set_flash_duration(duration)

    def set_flash_delay(self, delay):
        """
        Sets the delay before the flash.
        """
        self.controller.set_flash_delay(delay)
    
    def set_imaging_droplets(self, num_droplets):
        """
        Sets the number of droplets to print before imaging.
        """
        self.controller.set_imaging_droplets(num_droplets)

    def handle_print_pulse_width_change(self, value):
        """
        Handles changes to the print pulse width.
        """
        self.controller.set_print_pulse_width(value, manual=True)
        self.refresh_calibration_memory_recommendation()

    def set_exposure_time(self, exposure_time):
        """
        Sets the exposure time for the camera.
        """
        self.controller.set_exposure_time(exposure_time)

    def set_start_pressure(self, pressure):
        """
        Sets the starting pressure for calibration.
        """
        self.controller.set_start_pressure(pressure)

    def set_num_pressure_tests(self, num_tests):
        """
        Sets the number of pressure tests for characterization.
        """
        self.controller.set_num_pressure_tests(num_tests)

    def set_record_mode_enabled(self, enabled: bool):
        mgr = self.model.calibration_manager
        try:
            mgr.set_record_mode_enabled(bool(enabled))
        except Exception:
            mgr.record_mode_enabled = bool(enabled)
        self._sync_stream_capture_panel_state()

    def _get_stream_capture_state(self):
        mgr = getattr(self.model, "calibration_manager", None)
        getter = getattr(mgr, "get_stream_gravimetric_capture_state", None)
        if callable(getter):
            try:
                state = getter()
            except Exception:
                state = None
            if isinstance(state, dict):
                return state
        return {
            "status": "idle",
            "status_message": "Ready to begin stream gravimetric capture.",
            "error_message": "",
            "session_id": None,
            "starting_mass_mg": 0.0,
            "starting_flash": None,
            "ending_flash": None,
            "raw_flash_delta": None,
            "background_capture_count": None,
            "printed_capture_count": None,
            "capture_mode": "timecourse",
            "capture_process_name": "DropletTimecourseProcess",
            "timecourse_run_id": None,
            "dataset_run_id": None,
            "dataset_process_name": None,
            "flow_fit_status": "",
            "tail_phase_status": "",
            "flow_rate_nl_per_us": None,
            "tail_start_delay_from_emergence_us": None,
            "predicted_stream_duration_us": None,
            "predicted_volume_nl": None,
            "segmented_tail_start_delay_from_emergence_us": None,
            "segmented_predicted_stream_duration_us": None,
            "segmented_predicted_volume_nl": None,
            "segmented_predicted_volume_delta_from_runtime_nl": None,
            "analysis_warnings": [],
            "rep": int(self.stream_capture_rep_spin.value()) if hasattr(self, "stream_capture_rep_spin") else 1,
            "suggested_rep": int(self.stream_capture_rep_spin.value()) if hasattr(self, "stream_capture_rep_spin") else 1,
            "notes": "",
        }

    @staticmethod
    def _stream_capture_blocks_new_starts(state: dict | None):
        status = str((state or {}).get("status") or "idle")
        return status != "idle"

    def _begin_stream_calibration_sequence_gripper_preamble(self):
        result = self.controller.begin_stream_calibration_sequence_gripper_preamble()
        if isinstance(result, tuple) and result and (result[0] is False):
            return False
        return True

    def _begin_stream_calibration_sequence_gripper_restore(self):
        result = self.controller.begin_stream_calibration_sequence_gripper_restore()
        if isinstance(result, tuple) and result and (result[0] is False):
            return False
        return True

    def _begin_droplet_calibration_sequence_gripper_preamble(self):
        result = self.controller.begin_droplet_calibration_sequence_gripper_preamble()
        if isinstance(result, tuple) and result and (result[0] is False):
            return False
        return True

    def _begin_droplet_calibration_sequence_gripper_restore(self):
        result = self.controller.begin_droplet_calibration_sequence_gripper_restore()
        if isinstance(result, tuple) and result and (result[0] is False):
            return False
        return True

    def _close_stream_capture_mass_dialog(self):
        dialog = getattr(self, "_stream_capture_mass_dialog", None)
        if dialog is None:
            return
        dialog.blockSignals(True)
        try:
            dialog.close()
        finally:
            dialog.blockSignals(False)
        dialog.deleteLater()
        self._stream_capture_mass_dialog = None

    def _handle_stream_capture_mass_dialog_finished(self, _result):
        self._stream_capture_mass_dialog = None
        if self._stream_capture_dialog_closing:
            return
        state = self._get_stream_capture_state()
        if str(state.get("status") or "") == "awaiting_mass_entry":
            QTimer.singleShot(0, self._ensure_stream_capture_followup_state)

    def _show_stream_capture_mass_dialog(self, state: dict):
        dialog = getattr(self, "_stream_capture_mass_dialog", None)
        if dialog is None:
            dialog = StreamCaptureMassEntryDialog(self, controller=self.controller, model=self.model)
            dialog.finished.connect(self._handle_stream_capture_mass_dialog_finished)
            self._stream_capture_mass_dialog = dialog
        dialog.update_state(
            state,
            rep_value=int(self.stream_capture_rep_spin.value()),
            notes=self.stream_capture_notes_edit.toPlainText().strip(),
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _set_stream_capture_read_camera_enabled(self, enabled: bool):
        desired_enabled = bool(enabled)
        if desired_enabled and getattr(self, "_stream_capture_dialog_closing", False):
            return
        if (
            self._read_camera_stream_reconciled
            and self._read_camera_stream_armed == desired_enabled
        ):
            return
        if desired_enabled:
            self.controller.start_read_camera()
        else:
            self.controller.stop_read_camera()
        self._read_camera_stream_armed = desired_enabled
        self._read_camera_stream_reconciled = True

    def _sync_stream_capture_read_camera_state(self, status: str):
        self._set_stream_capture_read_camera_enabled(
            str(status or "idle") not in self._STREAM_CAPTURE_READ_CAMERA_DISARM_STATUSES
        )

    def _begin_stream_capture_loading_move(self):
        result = self.controller.begin_stream_gravimetric_capture_loading_move()
        if isinstance(result, tuple) and result and (result[0] is False):
            return False
        move_ok = self.controller.move_to_location(
            "loading",
            on_complete=self.controller.on_stream_gravimetric_capture_loading_reached,
        )
        if move_ok is False:
            self.controller.report_stream_gravimetric_capture_move_failure(
                "loading",
                "Failed to move printer head to loading position.",
            )
            return False
        return True

    def _begin_stream_capture_camera_return(self):
        result = self.controller.begin_stream_gravimetric_capture_camera_return()
        if isinstance(result, tuple) and result and (result[0] is False):
            return False
        self._set_stream_capture_read_camera_enabled(True)
        move_ok = self.controller.move_to_location(
            "camera",
            on_complete=self.controller.on_stream_gravimetric_capture_camera_reached,
        )
        if move_ok is False:
            self.controller.report_stream_gravimetric_capture_move_failure(
                "camera",
                "Failed to move printer head back to camera position.",
            )
            return False
        return True

    def _begin_stream_capture_gripper_preamble(self):
        result = self.controller.begin_stream_gravimetric_capture_gripper_preamble()
        if isinstance(result, tuple) and result and (result[0] is False):
            return False
        return True

    def _begin_stream_capture_gripper_restore(self):
        result = self.controller.begin_stream_gravimetric_capture_gripper_restore()
        if isinstance(result, tuple) and result and (result[0] is False):
            return False
        return True

    def _ensure_stream_capture_followup_state(self, *_args):
        if getattr(self, "_stream_capture_dialog_closing", False):
            return

        state = self._get_stream_capture_state()
        status = str(state.get("status") or "idle")
        self._sync_stream_capture_read_camera_state(status)

        if status == "pending_gripper_refresh":
            if not self._stream_capture_gripper_preamble_attempted:
                self._stream_capture_gripper_preamble_attempted = True
                self._begin_stream_capture_gripper_preamble()
            self._close_stream_capture_mass_dialog()
            return

        if status == "pending_loading_move":
            if not self._stream_capture_loading_move_attempted:
                self._stream_capture_loading_move_attempted = True
                self._begin_stream_capture_loading_move()
            self._close_stream_capture_mass_dialog()
            return

        if status == "pending_gripper_restore":
            if not self._stream_capture_gripper_restore_attempted:
                self._stream_capture_gripper_restore_attempted = True
                self._begin_stream_capture_gripper_restore()
            self._close_stream_capture_mass_dialog()
            return

        if status == "pending_camera_return":
            if not self._stream_capture_camera_return_attempted:
                self._stream_capture_camera_return_attempted = True
                self._begin_stream_capture_camera_return()
            self._close_stream_capture_mass_dialog()
            return

        if status == "awaiting_mass_entry":
            self._show_stream_capture_mass_dialog(state)
        else:
            self._close_stream_capture_mass_dialog()

        if status not in {"pending_gripper_refresh", "refreshing_gripper", "suspending_gripper_refresh"}:
            self._stream_capture_gripper_preamble_attempted = False
        if status not in {"pending_loading_move", "moving_to_loading"}:
            self._stream_capture_loading_move_attempted = False
        if status not in {"pending_gripper_restore", "restoring_gripper_refresh"}:
            self._stream_capture_gripper_restore_attempted = False
        if status not in {"pending_camera_return", "returning_to_camera"}:
            self._stream_capture_camera_return_attempted = False

    def _ensure_stream_calibration_sequence_followup_state(self, *_args):
        state = self._get_stream_calibration_sequence_state()
        status = str(state.get("status") or "idle")

        if status == "pending_gripper_refresh":
            if not self._stream_calibration_sequence_gripper_preamble_attempted:
                self._stream_calibration_sequence_gripper_preamble_attempted = True
                self._begin_stream_calibration_sequence_gripper_preamble()
            return

        if status == "pending_gripper_restore":
            if not self._stream_calibration_sequence_gripper_restore_attempted:
                self._stream_calibration_sequence_gripper_restore_attempted = True
                self._begin_stream_calibration_sequence_gripper_restore()
            return

        if status not in {"pending_gripper_refresh", "refreshing_gripper", "suspending_gripper_refresh"}:
            self._stream_calibration_sequence_gripper_preamble_attempted = False
        if status not in {"pending_gripper_restore", "restoring_gripper_refresh"}:
            self._stream_calibration_sequence_gripper_restore_attempted = False

    def _ensure_droplet_calibration_sequence_followup_state(self, *_args):
        state = self._get_droplet_calibration_sequence_state()
        status = str(state.get("status") or "idle")

        if status == "pending_gripper_refresh":
            if not self._droplet_calibration_sequence_gripper_preamble_attempted:
                self._droplet_calibration_sequence_gripper_preamble_attempted = True
                self._begin_droplet_calibration_sequence_gripper_preamble()
            return

        if status == "pending_gripper_restore":
            if not self._droplet_calibration_sequence_gripper_restore_attempted:
                self._droplet_calibration_sequence_gripper_restore_attempted = True
                self._begin_droplet_calibration_sequence_gripper_restore()
            return

        if status not in {"pending_gripper_refresh", "refreshing_gripper", "suspending_gripper_refresh"}:
            self._droplet_calibration_sequence_gripper_preamble_attempted = False
        if status not in {"pending_gripper_restore", "restoring_gripper_refresh"}:
            self._droplet_calibration_sequence_gripper_restore_attempted = False

    def _complete_stream_gravimetric_capture_from_popup(self, ending_mass_mg: float):
        result = self.controller.finalize_stream_gravimetric_capture(
            float(ending_mass_mg),
            rep_override=int(self.stream_capture_rep_spin.value()),
            notes=self.stream_capture_notes_edit.toPlainText().strip(),
        )
        if isinstance(result, tuple) and result and (result[0] is False):
            QtWidgets.QMessageBox.warning(
                self,
                "Stream Capture",
                str(result[1] or "Failed to save stream gravimetric capture row."),
            )
            return False
        self._close_stream_capture_mass_dialog()
        return True

    def _discard_stream_gravimetric_capture_from_popup(self):
        result = self.controller.discard_stream_gravimetric_capture(
            reason="operator_discarded",
        )
        if isinstance(result, tuple) and result and (result[0] is False):
            QtWidgets.QMessageBox.warning(
                self,
                "Stream Capture",
                str(result[1] or "Failed to discard stream gravimetric capture."),
            )
            return False
        self._close_stream_capture_mass_dialog()
        return True

    def _sync_stream_capture_panel_state(self, state: dict | None = None):
        if not hasattr(self, "stream_capture_group"):
            return
        state = dict(state or self._get_stream_capture_state())
        status = str(state.get("status") or "idle")
        status_message = str(state.get("status_message") or "Ready to begin stream gravimetric capture.")
        error_message = str(state.get("error_message") or "")
        session_id = str(state.get("session_id") or "-")
        dataset_run_id = str(state.get("dataset_run_id") or state.get("timecourse_run_id") or "-")
        capture_mode = str(state.get("capture_mode") or "timecourse")
        capture_process = str(state.get("dataset_process_name") or state.get("capture_process_name") or "-")
        background_count = state.get("background_capture_count")
        printed_count = state.get("printed_capture_count")
        starting_flash = state.get("starting_flash")
        ending_flash = state.get("ending_flash")
        raw_flash_delta = state.get("raw_flash_delta")
        flow_fit_status = str(state.get("flow_fit_status") or "-")
        tail_phase_status = str(state.get("tail_phase_status") or "-")
        flow_rate = state.get("flow_rate_nl_per_us")
        tail_start = state.get("tail_start_delay_from_emergence_us")
        predicted_duration = state.get("predicted_stream_duration_us")
        predicted_volume = state.get("predicted_volume_nl")
        segmented_tail_start = state.get("segmented_tail_start_delay_from_emergence_us")
        segmented_predicted_duration = state.get("segmented_predicted_stream_duration_us")
        segmented_predicted_volume = state.get("segmented_predicted_volume_nl")
        segmented_volume_delta = state.get("segmented_predicted_volume_delta_from_runtime_nl")
        analysis_warnings = state.get("analysis_warnings") or []
        if isinstance(analysis_warnings, (list, tuple)):
            warning_text = "; ".join(str(item) for item in analysis_warnings if str(item).strip())
        else:
            warning_text = str(analysis_warnings or "")

        self.stream_capture_status_label.setText(status_message)
        if error_message and status in {"error", "stopped", "pending_loading_move", "pending_camera_return", "pending_gripper_restore"}:
            self.stream_capture_status_label.setStyleSheet("color: darkred; font-weight: 600;")
        elif status in {"awaiting_mass", "awaiting_mass_entry", "pending_camera_return", "returning_to_camera"}:
            self.stream_capture_status_label.setStyleSheet("color: darkgreen; font-weight: 600;")
        elif status in {
            "pending_gripper_refresh",
            "refreshing_gripper",
            "suspending_gripper_refresh",
            "pending_loading_move",
            "moving_to_loading",
            "pending_gripper_restore",
            "restoring_gripper_refresh",
        }:
            self.stream_capture_status_label.setStyleSheet("color: darkblue; font-weight: 600;")
        else:
            self.stream_capture_status_label.setStyleSheet("")

        summary_text = (
            "Session: "
            f"{session_id}\n"
            f"Capture Run: {dataset_run_id} | Mode: {capture_mode} | Process: {capture_process}\n"
            f"Start flash: {starting_flash if starting_flash is not None else '-'} | "
            f"End flash: {ending_flash if ending_flash is not None else '-'} | Delta: {raw_flash_delta if raw_flash_delta is not None else '-'}\n"
            f"Background captures: {background_count if background_count is not None else '-'} | "
            f"Num printed: {printed_count if printed_count is not None else '-'}"
        )
        if capture_mode == "online_stream":
            summary_text += (
                "\n"
                f"Flow fit: {flow_fit_status} | Tail: {tail_phase_status} | "
                f"Flow rate: {flow_rate if flow_rate is not None else '-'} nL/us | "
                f"Tail start: {tail_start if tail_start is not None else '-'} us | "
                f"Duration: {predicted_duration if predicted_duration is not None else '-'} us | "
                f"Volume: {predicted_volume if predicted_volume is not None else '-'} nL"
            )
            if any(
                value is not None
                for value in (
                    segmented_tail_start,
                    segmented_predicted_duration,
                    segmented_predicted_volume,
                )
            ):
                summary_text += (
                    "\n"
                    f"Segmented tail: {segmented_tail_start if segmented_tail_start is not None else '-'} us | "
                    f"Segmented duration: {segmented_predicted_duration if segmented_predicted_duration is not None else '-'} us | "
                    f"Segmented volume: {segmented_predicted_volume if segmented_predicted_volume is not None else '-'} nL"
                )
                if segmented_volume_delta is not None:
                    summary_text += f" | Delta: {segmented_volume_delta} nL"
            if warning_text:
                summary_text += f"\nWarnings: {warning_text}"
        self.stream_capture_summary_label.setText(summary_text)

        record_mode_enabled = True
        try:
            record_mode_enabled = bool(self.model.calibration_manager.get_record_mode_enabled())
        except Exception:
            record_mode_enabled = bool(getattr(self.model.calibration_manager, "record_mode_enabled", True))
        experiment_ready = False
        try:
            experiment_ready = bool(getattr(self.model.experiment_model, "experiment_dir_path", None))
        except Exception:
            experiment_ready = False
        flash_fault_latched = self._is_flash_fault_latched()
        stream_busy = False
        busy_getter = getattr(self.model.calibration_manager, "is_stream_gravimetric_capture_busy", None)
        if callable(busy_getter):
            try:
                stream_busy = bool(busy_getter())
            except Exception:
                stream_busy = status in {
                    "pending_gripper_refresh",
                    "refreshing_gripper",
                    "suspending_gripper_refresh",
                    "running",
                    "pending_loading_move",
                    "moving_to_loading",
                    "awaiting_mass_entry",
                    "pending_gripper_restore",
                    "restoring_gripper_refresh",
                    "pending_camera_return",
                    "returning_to_camera",
                }
        else:
            stream_busy = status in {
                "pending_gripper_refresh",
                "refreshing_gripper",
                "suspending_gripper_refresh",
                "running",
                "pending_loading_move",
                "moving_to_loading",
                "awaiting_mass_entry",
                "pending_gripper_restore",
                "restoring_gripper_refresh",
                "pending_camera_return",
                "returning_to_camera",
            }

        if status == "idle":
            suggested_rep = int(state.get("suggested_rep") or state.get("rep") or 1)
            if not self.stream_capture_rep_spin.hasFocus():
                self.stream_capture_rep_spin.setValue(max(1, suggested_rep))
            if self._stream_capture_last_status not in (None, "idle"):
                self.stream_capture_starting_mass_spin.setValue(0.0)
                self.stream_capture_notes_edit.clear()
        elif status in {
            "pending_gripper_refresh",
            "refreshing_gripper",
            "suspending_gripper_refresh",
            "running",
            "pending_loading_move",
            "moving_to_loading",
            "awaiting_mass_entry",
            "pending_gripper_restore",
            "restoring_gripper_refresh",
            "pending_camera_return",
            "returning_to_camera",
            "error",
            "stopped",
        }:
            rep_value = int(state.get("rep") or state.get("suggested_rep") or 1)
            if not self.stream_capture_rep_spin.hasFocus():
                self.stream_capture_rep_spin.setValue(max(1, rep_value))
            if (
                state.get("starting_mass_mg") is not None
                and self._stream_capture_last_status in (None, "idle")
            ):
                self.stream_capture_starting_mass_spin.setValue(float(state.get("starting_mass_mg") or 0.0))

        begin_enabled = (
            status == "idle"
            and record_mode_enabled
            and experiment_ready
            and (not flash_fault_latched)
            and (not DropletImagingDialog._is_calibration_busy(self))
        )
        discard_enabled = status in {"pending_loading_move", "awaiting_mass_entry", "error", "stopped"}

        self.stream_capture_begin_button.setEnabled(begin_enabled)
        self.stream_capture_discard_button.setEnabled(discard_enabled)
        self.stream_capture_starting_mass_spin.setEnabled(status == "idle")
        self.stream_capture_rep_spin.setEnabled(status in {"idle", "awaiting_mass_entry"})
        self.stream_capture_notes_edit.setEnabled(status in {"idle", "awaiting_mass_entry"})
        if hasattr(self, "stream_capture_online_mode_checkbox"):
            self.stream_capture_online_mode_checkbox.setEnabled(status == "idle")

        block_new_starts = self._stream_capture_blocks_new_starts(state)
        for action_key in (
            "head_prime",
            "nozzle_position",
            "nozzle_focus",
            "droplet_emergence",
            "pressure_scan",
            "pressure_trajectory",
            "pressure_sweep_characterization",
            "droplet_characterization",
            "droplet_timecourse",
            "online_stream_calibration",
            "stream_calibrate_all",
            "calibrate_all",
            "pulsewidth_sweep",
        ):
            if block_new_starts:
                self._set_calibration_action_enabled(action_key, False)
        if (not block_new_starts) and (not flash_fault_latched):
            self._enable_non_readiness_calibration_buttons()
            self._apply_cached_calibration_readiness()
        else:
            self._recompute_online_stream_button_state()
            self._recompute_stream_calibration_sequence_button_state()
            self._recompute_droplet_calibration_sequence_button_state()

        if hasattr(self, "record_calibration_checkbox"):
            self.record_calibration_checkbox.setEnabled(not stream_busy and not block_new_starts)

        self._stream_capture_last_status = status
        self._refresh_calibration_tab_lock_state()

    def begin_stream_gravimetric_capture(self):
        capture_mode = (
            "online_stream"
            if bool(getattr(self, "stream_capture_online_mode_checkbox", None) and self.stream_capture_online_mode_checkbox.isChecked())
            else "timecourse"
        )
        result = self.controller.start_stream_gravimetric_capture(
            float(self.stream_capture_starting_mass_spin.value()),
            rep_override=int(self.stream_capture_rep_spin.value()),
            notes=self.stream_capture_notes_edit.toPlainText().strip(),
            capture_mode=capture_mode,
        )
        if isinstance(result, tuple) and result and (result[0] is False):
            QtWidgets.QMessageBox.warning(self, "Stream Capture", str(result[1] or "Failed to start stream gravimetric capture."))

    def save_stream_gravimetric_capture(self):
        dialog = getattr(self, "_stream_capture_mass_dialog", None)
        ending_mass = 0.0 if dialog is None else float(dialog.ending_mass_spin.value())
        self._complete_stream_gravimetric_capture_from_popup(ending_mass)

    def discard_stream_gravimetric_capture(self):
        result = self.controller.discard_stream_gravimetric_capture(
            reason="operator_discarded",
        )
        if isinstance(result, tuple) and result and (result[0] is False):
            QtWidgets.QMessageBox.warning(self, "Stream Capture", str(result[1] or "Failed to discard stream gravimetric capture."))

    def set_calibration_memory_enabled(self, enabled: bool):
        mgr = self.model.calibration_manager
        try:
            applied = mgr.set_calibration_memory_enabled(bool(enabled))
        except Exception:
            applied = False
        if not applied:
            self.enable_calibration_memory_checkbox.blockSignals(True)
            try:
                self.enable_calibration_memory_checkbox.setChecked(
                    bool(getattr(mgr, "get_calibration_memory_enabled", lambda: False)())
                )
            finally:
                self.enable_calibration_memory_checkbox.blockSignals(False)
            return
        self.refresh_calibration_memory_recommendation(force_log=False)

    def update_flash_info(self):
        """
        Updates the flash info.
        """
        count = self.model.droplet_camera_model.get_num_flashes()
        self.flash_count_label.setText(f"Flashes: {count}")
        trigger_count = self.model.droplet_camera_model.get_trigger_counter()
        self.trigger_count_label.setText(f"Triggers: {trigger_count}")
        DropletImagingDialog._sync_manual_spinbox_value(
            self,
            self.flash_duration_spinbox,
            self.model.droplet_camera_model.get_flash_duration(),
        )
        DropletImagingDialog._sync_manual_spinbox_value(
            self,
            self.flash_delay_spinbox,
            self.model.droplet_camera_model.get_flash_delay(),
        )
        DropletImagingDialog._sync_manual_spinbox_value(
            self,
            self.num_droplets_spinbox,
            self.model.droplet_camera_model.get_num_droplets(),
        )
        DropletImagingDialog._sync_manual_spinbox_value(
            self,
            self.exposure_time_spinbox,
            self.model.droplet_camera_model.get_exposure_time(),
        )
        self._apply_flash_safety_ui_state()

    def start_droplet_camera(self):
        print('Starting droplet imaging')
        self.controller.start_droplet_camera()

    def capture_image(self):
        if getattr(self, "_capture_request_pending", False):
            return
        ok = self.controller.capture_droplet_image(throughput_mode=bool(self.capturing))
        if ok is not False:
            self._set_capture_request_pending(True)

    def stop_droplet_camera(self):
        self.controller.stop_droplet_camera()

    def on_calibration_completed(self):
        """
        Called when the calibration process is completed.
        """
        self.update_stage_and_log("Calibration Completed", "green")
        self.reset_calibration_buttons()
        self._refresh_manual_control_lock_state()
        try:
            if bool(getattr(self.model.calibration_manager, "should_suppress_process_verdict", lambda: False)()):
                self.model.calibration_manager.clear_pending_process_verdict(
                    reason="stream_capture_verdict_suppressed"
                )
                return
        except Exception:
            pass
        QTimer.singleShot(0, lambda: self._prompt_calibration_verdict(default_outcome="success"))

    def on_calibration_queue_completed(self):
        """
        Called when the calibration queue is completed.
        """
        self.update_stage_and_log("Calibration Queue Completed","green")
        self.reset_calibration_buttons()
        self._refresh_manual_control_lock_state()

    def on_calibration_error(self, error_message):
        """
        Called when the calibration process encounters an error.
        """
        self.update_stage_and_log("Calibration Error", "red")
        self.reset_calibration_buttons()
        self._refresh_manual_control_lock_state()
        QtWidgets.QMessageBox.warning(self, "Calibration Error", error_message)
        try:
            if bool(getattr(self.model.calibration_manager, "should_suppress_process_verdict", lambda: False)()):
                self.model.calibration_manager.clear_pending_process_verdict(
                    reason="stream_capture_verdict_suppressed"
                )
                return
        except Exception:
            pass
        QTimer.singleShot(
            0,
            lambda err=str(error_message): self._prompt_calibration_verdict(
                default_outcome="failed",
                error_message=err,
            ),
        )

    def _prompt_calibration_verdict(self, *, default_outcome: str, error_message: str = ""):
        mgr = self.model.calibration_manager
        pending = None
        try:
            pending = mgr.get_pending_process_verdict()
        except Exception:
            pending = None
        if not pending:
            return

        dlg = CalibrationVerdictDialog(
            self,
            process_name=str(pending.get("process_name") or pending.get("phase_name") or "unknown"),
            default_outcome=str(pending.get("default_outcome") or default_outcome or "unknown"),
            error_message=str(pending.get("error_message") or error_message or ""),
        )
        if dlg.exec():
            verdict = dlg.get_verdict_payload()
            try:
                mgr.submit_pending_process_verdict(
                    outcome=verdict.get("outcome", "unknown"),
                    failure_summary=verdict.get("failure_summary", ""),
                    suspected_cause=verdict.get("suspected_cause", ""),
                    notes=verdict.get("notes", ""),
                    submitted_by="ui",
                )
            except Exception as e:
                print(f"Failed to submit calibration verdict: {e}")
        else:
            try:
                mgr.clear_pending_process_verdict(reason="ui_skipped")
            except Exception:
                pass

    def reset_calibration_buttons(self):
        """
        Resets the calibration buttons to their default state.
        """
        for action_key in (
            "head_prime",
            "nozzle_position",
            "nozzle_focus",
            "droplet_emergence",
            "pressure_scan",
            "pressure_trajectory",
            "pressure_sweep_characterization",
            "droplet_characterization",
            "droplet_timecourse",
            "online_stream_calibration",
            "stream_calibrate_all",
            "calibrate_all",
            "pulsewidth_sweep",
        ):
            self._set_calibration_action_text(action_key, use_default=True)

    def toggle_start_head_prime_calibration(self):
        """
        Toggles whether the printer head priming should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self._set_calibration_action_text("head_prime", use_default=True)
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self._set_calibration_action_text("head_prime", "Stop Calibration")
            self.controller.start_head_prime_calibration()
        self._refresh_manual_control_lock_state()

    def toggle_start_nozzle_calibration(self):
        """
        Toggles whether the nozzle calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self._set_calibration_action_text("nozzle_position", use_default=True)
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self._set_calibration_action_text("nozzle_position", "Stop Calibration")
            self.controller.start_nozzle_calibration()
        self._refresh_manual_control_lock_state()

    def toggle_start_focus_calibration(self):
        """
        Toggles whether the focus calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self._set_calibration_action_text("nozzle_focus", use_default=True)
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self._set_calibration_action_text("nozzle_focus", "Stop Calibration")
            self.controller.start_nozzle_focus_calibration()
        self._refresh_manual_control_lock_state()

    def toggle_start_emergence_calibration(self):
        """
        Toggles whether the droplet emergence calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self._set_calibration_action_text("droplet_emergence", use_default=True)
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self._set_calibration_action_text("droplet_emergence", "Stop Calibration")
            self.controller.start_droplet_emergence_calibration()
        self._refresh_manual_control_lock_state()

    # def toggle_start_pressure_calibration(self):
    #     """
    #     Toggles whether the pressure calibration should be started.
    #     """
    #     if self.model.calibration_manager.activeCalibration is not None:
    #         print('Stopping calibration')
    #         self.calibrate_pressure_button.setText("Calibrate Pressure")
    #         self.controller.stop_calibration()
    #     else:
    #         print('Starting calibration')
    #         self.calibrate_pressure_button.setText("Stop Calibration")
    #         self.controller.start_pressure_calibration()

    def toggle_start_pressure_scan_calibration(self):
        """
        Start/stop the pressure scan using UI-provided low/high/step.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            # Stop any running calibration
            self._set_calibration_action_text("pressure_scan", use_default=True)
            self.controller.stop_calibration()
        else:
            # Launch
            self._set_calibration_action_text("pressure_scan", "Stop Calibration")
            self.controller.start_pressure_scan_calibration()
        self._refresh_manual_control_lock_state()

    def toggle_start_pressure_trajectory_calibration(self):
        """
        Toggles whether the pressure trajectory calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self._set_calibration_action_text("pressure_trajectory", use_default=True)
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self._set_calibration_action_text("pressure_trajectory", "Stop Calibration")
            self.controller.start_pressure_trajectory_calibration()
        self._refresh_manual_control_lock_state()

    # def toggle_start_droplet_search_calibration(self):
    #     """
    #     Toggles whether the droplet search calibration should be started.
    #     """
    #     if self.model.calibration_manager.activeCalibration is not None:
    #         print('Stopping calibration')
    #         self.calibrate_search_button.setText("Search for Droplets")
    #         self.controller.stop_calibration()
    #     else:
    #         print('Starting calibration')
    #         self.calibrate_search_button.setText("Stop Calibration")
    #         self.controller.start_droplet_search_calibration()

    def toggle_start_characterization_calibration(self):
        """
        Toggles whether the droplet characterization calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self._set_calibration_action_text("droplet_characterization", use_default=True)
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self._set_calibration_action_text("droplet_characterization", "Stop Calibration")
            self.controller.start_droplet_characterization_calibration()
        self._refresh_manual_control_lock_state()

    def toggle_start_pressure_sweep_calibration(self):
        """
        Toggles whether the pressure sweep characterization calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self._set_calibration_action_text("pressure_sweep_characterization", use_default=True)
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self._set_calibration_action_text("pressure_sweep_characterization", "Stop Calibration")
            self.controller.start_pressure_sweep_characterization()
        self._refresh_manual_control_lock_state()

    def toggle_start_timecourse_calibration(self):
        """
        Toggles whether the droplet timecourse imaging calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self._set_calibration_action_text("droplet_timecourse", use_default=True)
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self._set_calibration_action_text("droplet_timecourse", "Stop Calibration")
            self.controller.start_droplet_timecourse_process()
        self._refresh_manual_control_lock_state()

    def toggle_start_online_stream_calibration(self):
        """
        Toggles whether the online stream-volume calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self._set_calibration_action_text("online_stream_calibration", use_default=True)
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self._set_calibration_action_text("online_stream_calibration", "Stop Calibration")
            self.controller.start_online_stream_calibration()
        self._refresh_manual_control_lock_state()

    def toggle_start_all_stream_calibration(self):
        """
        Toggles whether the stream calibration sequence should be started.
        """
        manager = self.model.calibration_manager
        has_open_sequence = bool(
            getattr(manager, "has_open_stream_calibration_sequence", lambda: False)()
        )
        if (
            has_open_sequence
            or manager.activeCalibration is not None
            or len(getattr(manager, "calibration_queue", None) or []) > 0
        ):
            print('Stopping calibration')
            self._set_calibration_action_text("stream_calibrate_all", use_default=True)
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self._set_calibration_action_text("stream_calibrate_all", "Stop Calibration")
            self.controller.start_stream_calibration_sequence()
        self._refresh_manual_control_lock_state()

    def toggle_start_all_calibration(self):
        """
        Toggles whether all calibrations should be started.
        """
        manager = self.model.calibration_manager
        has_open_sequence = bool(
            getattr(manager, "has_open_droplet_calibration_sequence", lambda: False)()
        )
        if (
            has_open_sequence
            or manager.activeCalibration is not None
            or len(getattr(manager, "calibration_queue", None) or []) > 0
        ):
            print('Stopping calibration')
            self._set_calibration_action_text("calibrate_all", use_default=True)
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self._set_calibration_action_text("calibrate_all", "Stop Calibration")
            self.controller.start_droplet_calibration_sequence()
        self._refresh_manual_control_lock_state()

    def toggle_start_pw_sweep(self):
        """
        Start/stop running 'Calibrate All' for a sweep of pulse widths.
        Uses CalibrationManager's built-in sweep orchestration.
        """
        mgr = self.model.calibration_manager

        # If a sweep is active, stop it
        if mgr.is_pulsewidth_sweep_active():
            self._set_calibration_action_text("pulsewidth_sweep", use_default=True)
            mgr.stop_pulsewidth_sweep()
            self._refresh_manual_control_lock_state()
            return

        # If a calibration is currently running (single or queue), stop it first
        if mgr.activeCalibration is not None or len(mgr.calibration_queue) > 0:
            # mirror your other toggle patterns (stop via controller)
            try:
                self.controller.stop_calibration()
            except Exception:
                pass  # if controller not available, fall back to manager.stop()
            mgr.stop()
            # After stopping, fall through to start fresh

        # Read and validate PW range
        pw_start = int(self.pw_start_spin.value())
        pw_end   = int(self.pw_end_spin.value())
        pw_step  = int(self.pw_step_spin.value())

        if pw_step <= 0:
            QtWidgets.QMessageBox.warning(self, "Invalid step", "Pulse width step must be > 0.")
            return
        if pw_start == pw_end:
            QtWidgets.QMessageBox.warning(self, "Invalid range", "Start and end pulse widths cannot be equal.")
            return

        # Update button and kick off sweep
        self._set_calibration_action_text("pulsewidth_sweep", "Stop PW Range")
        mgr.start_pulsewidth_sweep(pw_start, pw_end, pw_step)
        self._refresh_manual_control_lock_state()

    def on_readiness_changed(self, readiness: dict):
        """
        Updates the UI based on the readiness of each calibration component.
        Applies a clear visual indication for inactive buttons.
        """
        self._last_calibration_readiness = {
            str(key): dict(value or {})
            for key, value in dict(readiness or {}).items()
        }
        self._apply_cached_calibration_readiness()

    def _apply_cached_calibration_readiness(self):
        readiness = dict(getattr(self, "_last_calibration_readiness", {}) or {})
        for key, action_key in getattr(self, "_calibration_readiness_button_specs", ()):
            if str(key) == "online_stream_calibration":
                continue
            info = dict(readiness.get(str(key), {}) or {})
            if not info:
                continue
            self._set_calibration_action_state(
                action_key,
                bool(info.get("ready")),
                info.get("missing"),
            )
        self._recompute_online_stream_button_state()
        self._recompute_stream_calibration_sequence_button_state()
        self._recompute_droplet_calibration_sequence_button_state()

    def _enable_non_readiness_calibration_buttons(self):
        for action_key in (
            "head_prime",
            "nozzle_position",
            "nozzle_focus",
            "droplet_emergence",
            "droplet_timecourse",
            "calibrate_all",
            "pulsewidth_sweep",
        ):
            self._set_calibration_action_enabled(action_key, True)

    def _get_start_p(self) -> float:
        return float(self.start_pressure_spin.value())
       
    def _set_btn_state(
        self,
        btn: QtWidgets.QPushButton,
        ready: bool,
        missing: list[str] | None = None,
        *,
        tooltip_override: str | None = None,
    ):
        """
        Uniform visual treatment for inactive buttons:
        - disabled state
        - greyed (opacity ~0.35)
        - forbidden cursor
        - tooltip listing missing prerequisites
        """
        btn.setEnabled(ready)

        # Tooltip + cursor
        if ready:
            btn.setToolTip(str(tooltip_override or ""))
            btn.setCursor(Qt.ArrowCursor)
        else:
            if tooltip_override:
                btn.setToolTip(str(tooltip_override))
            else:
                reason = ", ".join(missing or [])
                btn.setToolTip(f"Unavailable. Missing: {reason}" if reason else "Unavailable.")
            btn.setCursor(Qt.ForbiddenCursor)

        # Opacity effect (more obvious than default disabled styling)
        eff = btn.graphicsEffect()
        if ready:
            if isinstance(eff, QGraphicsOpacityEffect):
                btn.setGraphicsEffect(None)  # remove to restore native look
            # Clear any custom stylesheet if you added some elsewhere
            btn.setStyleSheet("")
        else:
            if not isinstance(eff, QGraphicsOpacityEffect):
                eff = QGraphicsOpacityEffect(btn)
                btn.setGraphicsEffect(eff)
            eff.setOpacity(0.35)  # tweak to taste

    def update_stage_and_log(self, stage: str, color_name: str):
        # Update the small status label
        self.stageLabel.setText(f"Status: {stage}")

        # Append to the log table (time + stage text)
        row = self.stage_table.rowCount()
        self.stage_table.insertRow(row)

        time_str = datetime.now().strftime("%H:%M:%S")
        time_item = QtWidgets.QTableWidgetItem(time_str)
        stage_item = QtWidgets.QTableWidgetItem(stage)

        # Resolve background color from main_window.color_dict
        # Fallbacks: "dark_gray" → hex → default gray if missing
        hex_color = self.color_dict.get(color_name) or self.color_dict.get("dark_gray") or "#444444"
        brush = QBrush(QColor(hex_color))

        time_item.setBackground(brush)
        stage_item.setBackground(brush)

        self.stage_table.setItem(row, 0, time_item)
        self.stage_table.setItem(row, 1, stage_item)

        # Auto-scroll to the newest row
        self.stage_table.scrollToBottom()

    def _bridge_get_calibration_manager(self):
        # Prefer the ExperimentModel-attached manager if present.
        return self.model.calibration_manager

    def _bridge_get_current_reagent_name(self) -> str | None:
        # Plan lookups need the design reagent name, not the display stock name.
        cm = self._bridge_get_calibration_manager()
        if cm is not None:
            try:
                identity_getter = getattr(cm, "_build_calibration_stock_identity_snapshot", None)
                if callable(identity_getter):
                    identity = identity_getter()
                    if isinstance(identity, dict):
                        r = identity.get("reagent_name") or (identity.get("stock_identity") or {}).get("reagent_name")
                        if r:
                            return str(r)
            except Exception:
                pass
        try:
            ph = self.model.rack_model.get_gripper_printer_head()
            if ph:
                r = ph.get_reagent_name()
                if r:
                    return str(r)
        except Exception:
            pass
        # Legacy fallback for older/fake managers that only expose a reagent-like string.
        if cm is not None:
            try:
                r = cm._safe_get_stock_solution()
                if r:
                    return str(r)
            except Exception:
                pass
        return None

    @staticmethod
    def _normalize_printing_mode_value(value, *, fallback="droplet") -> str | None:
        mode = str(value or "").strip().lower()
        if mode in ("droplet", "stream"):
            return mode
        if fallback is None:
            return None
        fb = str(fallback or "").strip().lower()
        return fb if fb in ("droplet", "stream") else "droplet"

    @staticmethod
    def _infer_printing_mode_from_volume(volume_nl, *, fallback="droplet") -> str:
        try:
            return "stream" if float(volume_nl) >= 40.0 else "droplet"
        except Exception:
            return DropletImagingDialog._normalize_printing_mode_value(fallback)

    @staticmethod
    def _printing_mode_label(mode: str | None) -> str:
        normalized = DropletImagingDialog._normalize_printing_mode_value(mode)
        return "Stream" if normalized == "stream" else "Droplet"

    def _bridge_resolve_current_printing_mode(self) -> str | None:
        try:
            ph = self.model.rack_model.get_gripper_printer_head()
        except Exception:
            ph = None
        if ph is not None:
            getter = getattr(ph, "get_printing_mode", None)
            if callable(getter):
                try:
                    mode = self._normalize_printing_mode_value(getter(), fallback=None)
                    if mode in ("droplet", "stream"):
                        return mode
                except Exception:
                    pass

        em = getattr(self.model, "experiment_model", None)
        reagent = self._bridge_get_current_reagent_name()
        if em is None or not reagent:
            return None

        try:
            fill_reagent = em.get_fill_reagent_name()
        except Exception:
            fill_reagent = None

        if reagent == fill_reagent:
            fill_volume = None
            try:
                fill_volume = em.metadata.get("fill_droplet_volume_nL")
            except Exception:
                pass
            return self._normalize_printing_mode_value(
                getattr(em, "metadata", {}).get("fill_printing_mode"),
                fallback=self._infer_printing_mode_from_volume(fill_volume),
            )

        try:
            key_opt = em.find_option_by_reagent_name(reagent)
        except Exception:
            key_opt = None
        if key_opt:
            _key, opt = key_opt
            return self._normalize_printing_mode_value(
                getattr(opt, "printing_mode", None),
                fallback=self._infer_printing_mode_from_volume(getattr(opt, "droplet_nL", None)),
            )

        return None

    def _summary_row_printing_mode(self, raw: dict | None) -> str | None:
        if not raw:
            return None
        phase = str(raw.get("phase") or "").strip().lower()
        fallback = "stream" if phase == "stream" else "droplet"
        return self._normalize_printing_mode_value(raw.get("printing_mode"), fallback=fallback)

    def _summary_row_mode_mismatch_message(self, raw: dict | None) -> str | None:
        if not raw:
            return None
        current_mode = self._bridge_resolve_current_printing_mode()
        result_mode = self._summary_row_printing_mode(raw)
        if current_mode in (None, "") or result_mode in (None, "") or current_mode == result_mode:
            return None
        return (
            f"Selected result is for {self._printing_mode_label(result_mode).lower()} mode, "
            f"but the current reagent uses {self._printing_mode_label(current_mode).lower()} mode."
        )

    def _bridge_get_current_design_droplet_volume_nL(self) -> float | None:
        em = getattr(self.model, "experiment_model", None)
        reagent = self._bridge_get_current_reagent_name()
        if em is None or not reagent:
            return None
        try:
            if reagent == em.get_fill_reagent_name():
                return float(em.metadata.get("fill_droplet_volume_nL", 10.0))
        except Exception:
            pass
        try:
            key_opt = em.find_option_by_reagent_name(reagent)
        except Exception:
            key_opt = None
        if not key_opt:
            return None
        _key, opt = key_opt
        try:
            return float(opt.droplet_nL)
        except Exception:
            return None

    def _get_calibration_memory_target_volume_nL(self) -> float | None:
        target = self._bridge_get_current_design_droplet_volume_nL()
        if target is not None:
            return target
        try:
            mean_nL, _source = self._preferred_char_mean_nL()
        except Exception:
            mean_nL = None
        try:
            return float(mean_nL) if mean_nL is not None else None
        except Exception:
            return None

    @staticmethod
    def _calibration_memory_source_label(aggregation_level: str | None) -> str:
        mapping = {
            "exact_pair": "Exact pair",
            "exact_reagent_head_type": "Reagent + head type",
            "reagent_family_head_type": "Reagent family + head type fallback",
            "reagent_only": "Reagent-only fallback",
            "head_type_only": "Head-type fallback",
        }
        return mapping.get(str(aggregation_level or ""), str(aggregation_level or "Unknown"))

    @staticmethod
    def _calibration_memory_mode_description(mode: str | None) -> str:
        mode = str(mode or "advisory")
        if mode == "off":
            return "Mode: off. No automatic prior steering; this panel is manual only."
        if mode == "seed_start":
            return "Mode: seed_start. Runtime may also seed startup internally; this button only preloads dialog controls."
        return "Mode: advisory. Recommendation is visible, but calibration stays manual unless you click apply."

    @staticmethod
    def _format_pressure_band_psi(band) -> str:
        if not isinstance(band, (list, tuple)) or len(band) != 2:
            return "-"
        try:
            lo = float(min(band[0], band[1]))
            hi = float(max(band[0], band[1]))
        except Exception:
            return "-"
        return f"{lo:.3f}-{hi:.3f} psi"

    @staticmethod
    def _calibration_memory_preview_fingerprint(preview: dict | None):
        preview = dict(preview or {})
        prior = dict(preview.get("prior") or {})
        return (
            bool(preview.get("candidate_found")),
            str(prior.get("aggregation_level") or ""),
            prior.get("pulse_width_us"),
            prior.get("recommended_pressure_psi"),
            prior.get("recommendation_confidence_adjusted", prior.get("recommendation_confidence")),
            tuple(prior.get("source_run_ids") or []),
        )

    def _bridge_refresh_design_labels(self):
        em = self.model.experiment_model
        reagent = self._bridge_get_current_reagent_name()
        self.bridge_reagent_label.setText(f"Reagent: {reagent or '—'}")

        # Special case: fill reagent
        if reagent and reagent == em.get_fill_reagent_name():
            dv = float(em.metadata.get("fill_droplet_volume_nL", 10.0))
            self.bridge_design_dv_label.setText(f"Design droplet volume (nL): {dv:.3f}  (fill)")
            self.bridge_design_targets_label.setText("Design targets: — (fill top-up)")
            self.bridge_design_stock_label.setText("Stock concentration(s): —")
            self._bridge_clear_preview()
            self.refresh_calibration_memory_recommendation()
            return

        # Normal reagents (unchanged)
        key_opt = em.find_option_by_reagent_name(reagent) if reagent else None
        if not key_opt:
            self.bridge_design_dv_label.setText("Design droplet volume (nL): —")
            self.bridge_design_targets_label.setText("Design targets: —")
            self.bridge_design_stock_label.setText("Stock concentration(s): —")
            return

        key, opt = key_opt
        self.bridge_design_dv_label.setText(f"Design droplet volume (nL): {opt.droplet_nL:.3f}")
        targets = em.get_targets_for_key(key)
        self.bridge_design_targets_label.setText(
            "Design targets: " + (", ".join(f"{t:g}" for t in targets) if targets else "—")
        )
        plan = em.get_plan_for_key(key)
        if not plan:
            self.bridge_design_stock_label.setText("Stock concentration(s): —")
        else:
            if plan["n_stocks"] == 1:
                scs = [plan["stocks"][0]["stock_concentration"]]
            else:
                scs = [plan["stocks"][0]["stock_concentration"], plan["stocks"][1]["stock_concentration"]]
            try:
                units = plan["stocks"][0].get("units", "")
            except Exception:
                units = ""
            scs_txt = ", ".join(f"{float(c):.4g}" for c in scs)
            self.bridge_design_stock_label.setText(f"Stock concentration(s): {scs_txt} {units}")
        self._bridge_clear_preview()
        
    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._startup_focus_initialized:
            self._startup_focus_initialized = True
            QTimer.singleShot(0, lambda: self.setFocus(QtCore.Qt.OtherFocusReason))
        # populate the labels when the dialog appears
        self._bridge_refresh_design_labels()
        self.refresh_calibration_memory_recommendation(force_log=True)
        self._set_equal_panel_widths()
        self._refresh_manual_control_lock_state()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._set_equal_panel_widths()

    def _render_calibration_memory_recommendation(self, preview: dict | None):
        preview = dict(preview or {})
        prior = dict(preview.get("prior") or {})
        mode = str(preview.get("mode") or "advisory")
        memory_enabled = bool(preview.get("memory_enabled", True))
        if hasattr(self, "enable_calibration_memory_checkbox"):
            self.enable_calibration_memory_checkbox.blockSignals(True)
            try:
                self.enable_calibration_memory_checkbox.setChecked(memory_enabled)
            finally:
                self.enable_calibration_memory_checkbox.blockSignals(False)
        self.memory_recommendation_mode_label.setText(
            "Mode: disabled. Calibration memory writes and prior lookup are off."
            if not memory_enabled
            else self._calibration_memory_mode_description(mode)
        )

        if not memory_enabled:
            self.memory_recommendation_status_label.setText(
                "Calibration memory is disabled. Calibration uses the legacy startup path."
            )
            self.memory_recommendation_seed_label.setText("Seed: -")
            self.memory_recommendation_expected_label.setText("Expected: -")
            self.memory_recommendation_refresh_btn.setEnabled(True)
            self.memory_recommendation_apply_btn.setEnabled(False)
            self.memory_recommendation_apply_btn.setToolTip("Calibration memory is disabled.")
            self.memory_recommendation_ignore_btn.setEnabled(False)
            self.memory_recommendation_ignore_btn.setToolTip("")
            return

        if not prior:
            self.memory_recommendation_status_label.setText(
                "No prior found for the current reagent / printer-head / pulse-width context."
            )
            self.memory_recommendation_seed_label.setText("Seed: -")
            self.memory_recommendation_expected_label.setText("Expected: -")
            self.memory_recommendation_apply_btn.setEnabled(False)
            self.memory_recommendation_apply_btn.setToolTip("No recommendation is available to preload.")
            self.memory_recommendation_ignore_btn.setEnabled(False)
            self.memory_recommendation_ignore_btn.setToolTip("")
            return

        source_label = self._calibration_memory_source_label(prior.get("aggregation_level"))
        confidence = prior.get("recommendation_confidence_adjusted", prior.get("recommendation_confidence"))
        conf_text = "-"
        try:
            conf_text = f"{float(confidence):.2f}"
        except Exception:
            pass
        source_runs = int(prior.get("contributing_runs") or 0)
        pulse_match = str(prior.get("pulse_match_type") or "")
        pulse_match_text = "exact pulse" if pulse_match == "exact" else ("nearest pulse" if pulse_match else "pulse n/a")
        authority_prefix = "Best prior"
        if str(prior.get("aggregation_level") or "") in {"reagent_family_head_type", "reagent_only", "head_type_only"}:
            authority_prefix = "Fallback prior"
        if not bool(preview.get("manual_apply_allowed")):
            authority_prefix = "Reference prior"
        self.memory_recommendation_status_label.setText(
            f"{authority_prefix}: {source_label} | confidence {conf_text} | {pulse_match_text} | {source_runs} run(s)"
        )

        seed_values = dict(preview.get("seed_values") or {})
        seed_pressure = seed_values.get("start_pressure_psi", prior.get("recommended_pressure_psi"))
        seed_parts = []
        if prior.get("pulse_width_us") is not None:
            try:
                seed_parts.append(f"PW {int(prior.get('pulse_width_us'))} us")
            except Exception:
                pass
        if seed_pressure is not None:
            try:
                seed_parts.append(f"start {float(seed_pressure):.3f} psi")
            except Exception:
                pass
        band = (
            prior.get("stable_single_droplet_band_psi")
            or prior.get("recommended_pressure_band_psi")
            or prior.get("trajectory_pressure_band_psi")
        )
        if band is not None:
            seed_parts.append(f"band {self._format_pressure_band_psi(band)}")
        if prior.get("emergence_time_us") is not None:
            try:
                seed_parts.append(f"emergence {int(prior.get('emergence_time_us'))} us")
            except Exception:
                pass
        self.memory_recommendation_seed_label.setText(
            "Seed: " + ("; ".join(seed_parts) if seed_parts else "-")
        )

        expected_parts = []
        if prior.get("expected_mean_volume_nL") is not None:
            try:
                expected_parts.append(f"volume {float(prior.get('expected_mean_volume_nL')):.3f} nL")
            except Exception:
                pass
        if prior.get("expected_cv_pct") is not None:
            try:
                expected_parts.append(f"CV {float(prior.get('expected_cv_pct')):.2f}%")
            except Exception:
                pass
        if prior.get("run_to_run_volume_cv_pct") is not None:
            try:
                expected_parts.append(f"run-to-run CV {float(prior.get('run_to_run_volume_cv_pct')):.2f}%")
            except Exception:
                pass
        if prior.get("source_run_ids"):
            expected_parts.append(f"sources {len(prior.get('source_run_ids') or [])}")
        if not bool(preview.get("manual_apply_allowed")):
            reason = str(preview.get("manual_apply_reason") or "")
            if reason:
                expected_parts.append(f"manual apply disabled: {reason}")
        self.memory_recommendation_expected_label.setText(
            "Expected: " + ("; ".join(expected_parts) if expected_parts else "-")
        )

        can_apply = bool(preview.get("manual_apply_allowed")) and bool(seed_values)
        self.memory_recommendation_apply_btn.setEnabled(can_apply)
        self.memory_recommendation_apply_btn.setToolTip(
            "" if can_apply else f"Recommendation is reference-only: {preview.get('manual_apply_reason') or 'not qualified'}."
        )
        self.memory_recommendation_ignore_btn.setEnabled(True)
        self.memory_recommendation_ignore_btn.setToolTip("Keep the current manual startup values and ignore this recommendation.")
        if DropletImagingDialog._is_calibration_busy(self):
            self.memory_recommendation_apply_btn.setEnabled(False)
            self.memory_recommendation_apply_btn.setToolTip("Unavailable while calibration is running.")

    def refresh_calibration_memory_recommendation(self, *, force_log: bool = False):
        if getattr(self, "_memory_recommendation_refresh_active", False):
            return dict(getattr(self, "_memory_recommendation_preview", {}) or {})

        self._memory_recommendation_refresh_active = True
        try:
            cm = self._bridge_get_calibration_manager()
            if cm is None:
                self._memory_recommendation_preview = None
                self._render_calibration_memory_recommendation({})
                return None
            try:
                target_pulse = int(self.print_pulse_width_spinbox.value())
            except Exception:
                target_pulse = None
            target_volume = self._get_calibration_memory_target_volume_nL()
            try:
                preview = cm.preview_calibration_memory_recommendation(
                    target_pulse_width_us=target_pulse,
                    target_volume_nl=target_volume,
                )
            except Exception as e:
                print(f"[CalibrationMemoryUI] preview failed: {e}")
                preview = {
                    "mode": "advisory",
                    "candidate_found": False,
                    "prior": None,
                    "qualification": {},
                    "seed_values": {},
                    "manual_apply_allowed": False,
                    "manual_apply_reason": "preview_error",
                }
            self._memory_recommendation_preview = dict(preview or {})
            self._render_calibration_memory_recommendation(self._memory_recommendation_preview)

            prior = dict(self._memory_recommendation_preview.get("prior") or {})
            fingerprint = self._calibration_memory_preview_fingerprint(self._memory_recommendation_preview)
            should_log = bool(force_log)
            if not should_log:
                try:
                    should_log = bool(self.isVisible())
                except Exception:
                    should_log = True
            if prior and should_log and (force_log or fingerprint != self._memory_recommendation_logged_fingerprint):
                try:
                    cm.record_calibration_memory_ui_interaction(
                        "shown",
                        self._memory_recommendation_preview,
                        extra={"visible_in_dialog": True},
                    )
                except Exception as e:
                    print(f"[CalibrationMemoryUI] show log failed: {e}")
                self._memory_recommendation_logged_fingerprint = fingerprint
            elif not prior:
                self._memory_recommendation_logged_fingerprint = None
            return self._memory_recommendation_preview
        finally:
            self._memory_recommendation_refresh_active = False

    def apply_calibration_memory_recommendation(self):
        if DropletImagingDialog._is_calibration_busy(self):
            return
        preview = dict(getattr(self, "_memory_recommendation_preview", None) or {})
        prior = dict(preview.get("prior") or {})
        if not prior:
            QtWidgets.QMessageBox.information(self, "Recommendation", "No recommendation is available to apply.")
            return
        if not bool(preview.get("manual_apply_allowed")):
            QtWidgets.QMessageBox.information(
                self,
                "Recommendation",
                f"This recommendation is shown for reference only: {preview.get('manual_apply_reason') or 'not qualified for direct apply'}.",
            )
            return

        seed_values = dict(preview.get("seed_values") or {})
        seed_pressure = seed_values.get("start_pressure_psi", prior.get("recommended_pressure_psi"))
        if seed_pressure is None:
            QtWidgets.QMessageBox.warning(self, "Recommendation", "The recommendation does not include a usable start pressure.")
            return
        try:
            seed_pressure = float(seed_pressure)
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Recommendation", "The recommended start pressure is not numeric.")
            return
        seed_pressure = min(max(seed_pressure, float(self.hw_lo)), float(self.hw_hi))

        recommended_pw = prior.get("pulse_width_us")
        try:
            recommended_pw = None if recommended_pw is None else int(round(float(recommended_pw)))
        except Exception:
            recommended_pw = None

        if recommended_pw is not None:
            DropletImagingDialog._sync_manual_spinbox_value(
                self,
                self.print_pulse_width_spinbox,
                recommended_pw,
                force=True,
            )
            self.handle_print_pulse_width_change(recommended_pw)

        self.start_pressure_spin.blockSignals(True)
        self.start_pressure_spin.setValue(seed_pressure)
        self.start_pressure_spin.blockSignals(False)
        self.set_start_pressure(seed_pressure)

        cm = self._bridge_get_calibration_manager()
        if cm is not None:
            try:
                cm.record_calibration_memory_ui_interaction(
                    "applied",
                    preview,
                    extra={
                        "seeded_start_pressure_psi": seed_pressure,
                        "seeded_pulse_width_us": recommended_pw,
                    },
                )
            except Exception as e:
                print(f"[CalibrationMemoryUI] apply log failed: {e}")

        source_label = self._calibration_memory_source_label(prior.get("aggregation_level"))
        if recommended_pw is not None:
            self.stageLabel.setText(
                f"Status: Loaded recommended seed ({source_label}, PW {recommended_pw} us, start {seed_pressure:.3f} psi)"
            )
        else:
            self.stageLabel.setText(
                f"Status: Loaded recommended seed ({source_label}, start {seed_pressure:.3f} psi)"
            )

    def ignore_calibration_memory_recommendation(self):
        preview = dict(getattr(self, "_memory_recommendation_preview", None) or {})
        prior = dict(preview.get("prior") or {})
        if not prior:
            return
        cm = self._bridge_get_calibration_manager()
        if cm is not None:
            try:
                cm.record_calibration_memory_ui_interaction(
                    "ignored",
                    preview,
                    extra={"reason": "user_kept_manual_start"},
                )
            except Exception as e:
                print(f"[CalibrationMemoryUI] ignore log failed: {e}")
        self.stageLabel.setText("Status: Keeping manual calibration start values")

    # def _bridge_preview_from_last_char(self):
    #     cm = self._bridge_get_calibration_manager()
    #     if cm is None:
    #         QtWidgets.QMessageBox.warning(self, "Preview", "No calibration manager available.")
    #         return
    #     mean_nL = cm.get_last_characterization_mean_nL()
    #     if not mean_nL:
    #         QtWidgets.QMessageBox.information(self, "Preview", "No recent characterization found for this stock.")
    #         return

    #     em = self.model.experiment_model
    #     reagent = self._bridge_get_current_reagent_name()
    #     key_opt = em.find_option_by_reagent_name(reagent) if reagent else None
    #     if not key_opt:
    #         QtWidgets.QMessageBox.warning(self, "Preview", "Could not match current reagent to the experiment design.")
    #         return
    #     key, _opt = key_opt

    #     preview = em.preview_requantized_for_option(key, float(mean_nL))
    #     if not preview.get("ok"):
    #         QtWidgets.QMessageBox.warning(self, "Preview", preview.get("reason", "Preview failed."))
    #         return

    #     # Fill table
    #     self._bridge_fill_preview_table(preview)
    #     # In step 1 we still keep apply disabled (we’ll enable in Step 2)
    #     self.bridge_apply_btn.setEnabled(True)

    def _bridge_fill_preview_table(self, preview: dict):
        rows = preview.get("rows") or []
        nstocks = preview.get("n_stocks", 1)
        self.bridge_table.clearContents()
        self.bridge_table.setRowCount(len(rows))

        if nstocks == 1:
            # columns: Target, Achievable, Error, Drops, Δ/drop, Printed nL (new), Δ printed nL
            for r, row in enumerate(rows):
                self.bridge_table.setItem(r, 0, QtWidgets.QTableWidgetItem(_format_bridge_number(row["target_final"], 2)))
                self.bridge_table.setItem(r, 1, QtWidgets.QTableWidgetItem(_format_bridge_number(row["achieved_final"], 2)))
                self.bridge_table.setItem(r, 2, QtWidgets.QTableWidgetItem(_format_bridge_error_percent(row["error"], row["target_final"])))
                self.bridge_table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(row["drops"])))
                self.bridge_table.setItem(r, 4, QtWidgets.QTableWidgetItem(
                    _format_bridge_number(row["delta_per_drop"], 4, trim=True, suffix=f' {row["units"]}/drop')
                ))
                self.bridge_table.setItem(r, 5, QtWidgets.QTableWidgetItem(_format_bridge_number(row["printed_nL_new"], 2, suffix=" nL")))
                self.bridge_table.setItem(r, 6, QtWidgets.QTableWidgetItem(_format_bridge_number(row["printed_nL_shift"], 2, signed=True, suffix=" nL")))
        else:
            # For two-stock, show a+b and indicate tuple in 'Drops'; Δ/drop shows "d1 | d2"
            for r, row in enumerate(rows):
                drops = row["drops"]; a, b = drops
                dtxt = (
                    f'{_format_bridge_number(row["delta_per_drop_leg1"], 4, trim=True)} | '
                    f'{_format_bridge_number(row["delta_per_drop_leg2"], 4, trim=True)} {row["units"]}/drop'
                )
                self.bridge_table.setItem(r, 0, QtWidgets.QTableWidgetItem(_format_bridge_number(row["target_final"], 2)))
                self.bridge_table.setItem(r, 1, QtWidgets.QTableWidgetItem(_format_bridge_number(row["achieved_final"], 2)))
                self.bridge_table.setItem(r, 2, QtWidgets.QTableWidgetItem(_format_bridge_error_percent(row["error"], row["target_final"])))
                self.bridge_table.setItem(r, 3, QtWidgets.QTableWidgetItem(f'({a},{b}) = {a+b}'))
                self.bridge_table.setItem(r, 4, QtWidgets.QTableWidgetItem(dtxt))
                self.bridge_table.setItem(r, 5, QtWidgets.QTableWidgetItem(_format_bridge_number(row["printed_nL_new"], 2, suffix=" nL")))
                self.bridge_table.setItem(r, 6, QtWidgets.QTableWidgetItem(_format_bridge_number(row["printed_nL_shift"], 2, signed=True, suffix=" nL")))

        self.bridge_table.resizeColumnsToContents()
        self.bridge_table.resizeRowsToContents()

    def _bridge_clear_preview(self):
        self._bridge_clear_preview_with_status()

    def _populate_bridge_preview_table(self, preview: dict):
        rows = preview.get("rows", [])
        self.bridge_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            # small helpers
            def it(v): 
                return QtWidgets.QTableWidgetItem("" if v is None else str(v))
            # columns: "Target", "Achievable", "Error (%)", "Drops", "Δ/drop", "Printed nL (new)", "Δ printed nL"
            self.bridge_table.setItem(i, 0, it(_format_bridge_number(r["target_final"], 2)))
            self.bridge_table.setItem(i, 1, it(_format_bridge_number(r["achieved_final"], 2)))
            self.bridge_table.setItem(i, 2, it(_format_bridge_error_percent(r["error"], r["target_final"])))

            drops = r.get("drops")
            drops_txt = f"{drops[0]}+{drops[1]}" if isinstance(drops, tuple) else str(int(drops))
            self.bridge_table.setItem(i, 3, it(drops_txt))

            if "delta_per_drop" in r:
                d_txt = _format_bridge_number(r["delta_per_drop"], 4, trim=True)
            else:
                d_txt = (
                    f'{_format_bridge_number(r["delta_per_drop_leg1"], 4, trim=True)} | '
                    f'{_format_bridge_number(r["delta_per_drop_leg2"], 4, trim=True)}'
                )
            self.bridge_table.setItem(i, 4, it(d_txt))

            self.bridge_table.setItem(i, 5, it(_format_bridge_number(r["printed_nL_new"], 2)))
            self.bridge_table.setItem(i, 6, it(_format_bridge_number(r["printed_nL_shift"], 2, signed=True)))

    def _bridge_preview_from_last_char(self):
        _, raw = self._selected_summary_row()
        if not raw:
            QtWidgets.QMessageBox.information(
                self,
                "Preview",
                "Select a characterization result to preview.",
            )
            return

        self._refresh_bridge_preview_from_selection()
        if self._bridge_preview_payload is None:
            QtWidgets.QMessageBox.information(
                self,
                "Preview",
                str(self.bridge_status_label.text() or "Preview unavailable."),
            )
            return

        mean_nL = self._selected_summary_mean_nL()
        if mean_nL is not None:
            self.stageLabel.setText(f"Status: Preview using selected result ({mean_nL:.3f} nL)")
        return

        cm = self._bridge_get_calibration_manager()
        if cm is None:
            QtWidgets.QMessageBox.warning(self, "Preview", "No calibration manager available.")
            return

        mean_nL, source = self._preferred_char_mean_nL()
        if mean_nL is None:
            QtWidgets.QMessageBox.information(
                self, "Preview",
                "No characterization found (selected row has no mean and no recent result exists)."
            )
            return

        try:
            mean_nL = float(mean_nL)
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Preview", "Characterization mean is not numeric.")
            return
        if mean_nL <= 0:
            QtWidgets.QMessageBox.warning(self, "Preview", "Characterization mean must be > 0.")
            return

        em = self.model.experiment_model
        reagent = self._bridge_get_current_reagent_name()
        if not reagent:
            QtWidgets.QMessageBox.warning(self, "Preview", "No current reagent detected.")
            return

        # Optional: warn if selected row was flagged invalid (still allow preview)
        if source == "selected":
            _, raw = self._selected_summary_row()
            if raw and raw.get("valid") is False:
                QtWidgets.QMessageBox.information(
                    self, "Using flagged condition",
                    "The selected row was flagged invalid; preview will still use its mean volume."
                )

        # --- Special case: fill reagent ---
        if reagent == em.get_fill_reagent_name():
            preview = em.preview_fill_requantized(mean_nL)
            if not preview.get("ok"):
                QtWidgets.QMessageBox.warning(self, "Preview", preview.get("reason", "Preview failed."))
                return

            # Reuse the existing single-row table fill
            self.bridge_table.clearContents()
            self.bridge_table.setRowCount(1)
            row = preview["rows"][0]

            def _it(txt):
                return QtWidgets.QTableWidgetItem("" if txt is None else str(txt))

            self.bridge_table.setItem(0, 0, _it("—"))
            self.bridge_table.setItem(0, 1, _it("—"))
            self.bridge_table.setItem(0, 2, _it("—"))
            self.bridge_table.setItem(0, 3, _it(preview["total_drops_new"]))
            self.bridge_table.setItem(0, 4, _it(_format_bridge_number(mean_nL, 4, trim=True, suffix=" nL/drop")))
            self.bridge_table.setItem(0, 5, _it(_format_bridge_number(row["printed_nL_new"], 2, suffix=" nL")))
            self.bridge_table.setItem(0, 6, _it(_format_bridge_number(row["printed_nL_shift"], 2, signed=True, suffix=" nL")))
            self.bridge_table.resizeColumnsToContents()
            self.bridge_table.resizeRowsToContents()

            # Stash payload and enable Apply
            self._bridge_preview_payload = {
                "is_fill": True,
                "new_fill_nL": float(mean_nL),
            }
            self.bridge_apply_btn.setEnabled(True)
            self.bridge_apply_btn.setToolTip("")
            return

        # --- Normal reagents ---
        try:
            key = em.find_key_for_reagent(reagent)  # -> (factor_name, option_or_None)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Preview", str(e))
            return

        preview = em.preview_requantized_for_option(key, float(mean_nL), quantum=0.1)
        if not preview.get("ok"):
            QtWidgets.QMessageBox.warning(self, "Preview", preview.get("reason", "Preview failed."))
            return

        self._populate_bridge_preview_table(preview)
        self._bridge_preview_payload = {
            "factor_name": key[0],
            "option_name": key[1],
            "new_droplet_nL": float(preview.get("new_droplet_nL", mean_nL)),
            "n_stocks": int(preview.get("n_stocks", 1)),
        }
        can_apply = self._bridge_preview_payload["n_stocks"] == 1
        self.bridge_apply_btn.setEnabled(can_apply)
        self.bridge_apply_btn.setToolTip("" if can_apply else "Apply supports single-stock reagents only right now.")
        self.stageLabel.setText(f"Status: Preview using {'selected row' if source=='selected' else 'latest'} ({mean_nL:.3f} nL)")

    def _apply_previewed_droplet_volume(self):
        payload = getattr(self, "_bridge_preview_payload", None)
        if not payload:
            QtWidgets.QMessageBox.information(self, "Apply", "Nothing to apply.")
            return

        em = self.model.experiment_model
        raw = None
        selected_row_getter = getattr(self, "_selected_summary_row", None)
        if callable(selected_row_getter):
            try:
                _, raw = selected_row_getter()
            except Exception:
                raw = None
        mismatch_message = None
        mismatch_getter = getattr(self, "_summary_row_mode_mismatch_message", None)
        if callable(mismatch_getter):
            mismatch_message = mismatch_getter(raw)
        if mismatch_message:
            QtWidgets.QMessageBox.information(self, "Apply", mismatch_message)
            return

        # --- Special case: fill reagent
        if payload.get("is_fill"):
            applied_calibration = self._build_applied_imaging_calibration_payload(
                raw,
                float(payload["new_fill_nL"]),
                source_row_fingerprint=payload.get("source_row_fingerprint"),
            )
            try:
                out = em.apply_fill_droplet_volume(
                    float(payload["new_fill_nL"]),
                    write_keys_if_assigned=True,
                    applied_calibration=applied_calibration,
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Apply failed", f"{e}")
                return

            # Refresh UI tables that show the per-stock + fill totals
            if hasattr(self.main_window, "refresh_stock_table"):
                try:
                    self.main_window.refresh_stock_table()
                except Exception:
                    pass

            self._set_saved_applied_summary_row_fingerprint(payload.get("source_row_fingerprint"))
            self._sync_applied_summary_row_highlight()
            settings_result = self._apply_print_settings_for_applied_calibration(
                applied_calibration,
                run_label=applied_calibration.get("run_id") or (raw or {}).get("run_no") or "-",
            )
            self._bridge_clear_preview()
            self._bridge_refresh_design_labels()
            self.refresh_calibration_memory_recommendation()
            if not bool(settings_result.get("ok")):
                QtWidgets.QMessageBox.warning(
                    self,
                    "Settings not changed",
                    (
                        "Calibration was applied to the design, but the machine settings "
                        f"could not be changed.\n\n{settings_result.get('message', '')}"
                    ),
                )
            QtWidgets.QMessageBox.information(
                self, "Applied (Fill)",
                (
                    f"Updated fill ejection volume to {out['new_fill_nL']:.3f} nL."
                    f"\nTotal fill drops: {out['total_drops_old']} → {out['total_drops_new']} "
                    f"({out['total_drops_delta']:+d})"
                )
            )
            return

        # --- Normal reagents (existing logic) ---
        if payload.get("n_stocks", 1) != 1:
            QtWidgets.QMessageBox.warning(self, "Apply", "Two-stock plans aren’t supported for auto-apply yet.")
            return

        key = (payload["factor_name"], payload["option_name"])
        plan = em.get_plan_for_key(key)
        if not plan:
            QtWidgets.QMessageBox.warning(self, "Apply", "No stock plan found; optimize first.")
            return

        try:
            cur_dv = float(plan["stocks"][0]["droplet_volume_nL"])
        except Exception:
            cur_dv = None
        new_dv = float(payload["new_droplet_nL"])
        volume_unchanged = cur_dv is not None and abs(new_dv - cur_dv) < 1e-9

        applied_calibration = self._build_applied_imaging_calibration_payload(
            raw,
            new_dv,
            source_row_fingerprint=payload.get("source_row_fingerprint"),
        )
        try:
            em.apply_droplet_volume_for_option(
                payload["factor_name"],
                payload["option_name"],
                new_dv,
                write_keys_if_assigned=True,
                applied_calibration=applied_calibration,
            )
        except NotImplementedError as e:
            QtWidgets.QMessageBox.warning(self, "Apply failed", str(e))
            return
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Apply failed", f"{e}")
            return

        self._set_saved_applied_summary_row_fingerprint(payload.get("source_row_fingerprint"))
        self._sync_applied_summary_row_highlight()
        settings_result = self._apply_print_settings_for_applied_calibration(
            applied_calibration,
            run_label=applied_calibration.get("run_id") or (raw or {}).get("run_no") or "-",
        )
        self._bridge_clear_preview()
        self._bridge_refresh_design_labels()
        self.refresh_calibration_memory_recommendation()
        if not bool(settings_result.get("ok")):
            QtWidgets.QMessageBox.warning(
                self,
                "Settings not changed",
                (
                    "Calibration was applied to the design, but the machine settings "
                    f"could not be changed.\n\n{settings_result.get('message', '')}"
                ),
            )
        reagent_label = f"{payload['factor_name']}{('/' + payload['option_name']) if payload['option_name'] else ''}"
        if volume_unchanged:
            message = f"Recorded applied imaging calibration for {reagent_label} at {new_dv:.3f} nL ejection volume."
        else:
            message = f"Updated {reagent_label} to {new_dv:.3f} nL ejection volume."
        QtWidgets.QMessageBox.information(
            self, "Applied",
            message
        )
        
    def _selected_summary_row(self):
        """Return (row_index, dict_of_raw_values) from the selected table row or (None, None)."""
        sel = self.summary_table.selectionModel().selectedRows()
        if not sel:
            return None, None
        row = sel[0].row()

        def _raw(col):
            it = self.summary_table.item(row, col)
            return None if it is None else it.data(Qt.UserRole)

        # Columns: 0=Run #, 1=PW, 2=Pressure, 3=Mean, 4=CV, 5=Valid
        raw = {
            "run_no":       _raw(0),
            "pw_us":        _raw(1),
            "pressure_psi": _raw(2),
            "mean_nL":      _raw(3),
            "cv_pct":       _raw(4),
            "valid":        _raw(5),
            # optional: also keep display text for messages
            "_row": row,
        }
        return row, raw

    def _update_load_button_state(self):
        """Enable the Load button only when we have a usable selection."""
        _, raw = self._selected_summary_row()
        mismatch_message = self._summary_row_mode_mismatch_message(raw)
        ok = bool(
            raw
            and mismatch_message is None
            and raw.get("pw_us") is not None
            and raw.get("pressure_psi") is not None
            and not DropletImagingDialog._is_calibration_busy(self)
        )
        self.load_selected_button.setEnabled(ok)
        if mismatch_message:
            self.load_selected_button.setToolTip(mismatch_message)
        else:
            self.load_selected_button.setToolTip(
                "Select a row above, then click to apply its PW and pressure."
            )
        self._update_recheck_button_state(raw=raw, mismatch_message=mismatch_message)

    def _summary_row_recheck_missing(self, raw):
        if not raw:
            return ["Selected characterization result"]
        mgr = getattr(getattr(self, "model", None), "calibration_manager", None)
        getter = getattr(mgr, "get_droplet_recheck_missing_requirements", None)
        if callable(getter):
            try:
                return list(getter(raw) or [])
            except Exception as exc:
                return [f"Recheck context unavailable ({exc})"]
        return ["Recheck support is unavailable"]

    def _update_recheck_button_state(self, *, raw=None, mismatch_message=None):
        if not hasattr(self, "recheck_selected_button"):
            return
        if raw is None:
            _, raw = self._selected_summary_row()
        if mismatch_message is None:
            mismatch_message = self._summary_row_mode_mismatch_message(raw)
        missing = self._summary_row_recheck_missing(raw)
        busy = DropletImagingDialog._is_calibration_busy(self)
        ok = bool(raw and mismatch_message is None and not missing and not busy)
        self.recheck_selected_button.setEnabled(ok)
        if mismatch_message:
            self.recheck_selected_button.setToolTip(mismatch_message)
        elif busy:
            self.recheck_selected_button.setToolTip("Wait for the current calibration to finish before rechecking.")
        elif missing:
            self.recheck_selected_button.setToolTip("Recheck unavailable: " + ", ".join(str(item) for item in missing))
        else:
            self.recheck_selected_button.setToolTip(
                "Image this selected condition again using its original delay, position, and trajectory."
            )

    def _handle_summary_double_click(self, _item):
        """Double-click loads immediately (same as pressing the button)."""
        self.load_selected_summary_row()

    # NEW: return the selected row's mean droplet volume (nL) or None
    def _selected_summary_mean_nL(self) -> float | None:
        _, raw = self._selected_summary_row()
        if not raw:
            return None
        val = raw.get("mean_nL")
        try:
            v = float(val) if val is not None else None
            return v if (v is not None and v > 0) else None
        except Exception:
            return None

    # NEW: choose selected-row mean if available; else fall back to latest
    def _preferred_char_mean_nL(self):
        """
        Returns (mean_nL, source) where source ∈ {"selected", "latest"} or (None, None)
        """
        sel = self._selected_summary_mean_nL()
        if sel is not None:
            return sel, "selected"
        cm = self._bridge_get_calibration_manager()
        if cm is None:
            return None, None
        m = cm.get_last_characterization_mean_nL()
        try:
            return (float(m) if m is not None else None), "latest"
        except Exception:
            return None, None
        
    # NEW: keep preview button label/tooltips in sync with selection
    def _update_preview_button_label(self):
        if self._selected_summary_mean_nL() is not None:
            self.bridge_preview_btn.setText("Preview from selected row")
            self.bridge_preview_btn.setToolTip("Uses the selected table row’s mean droplet volume.")
        else:
            self.bridge_preview_btn.setText("Preview from last characterization")
            self.bridge_preview_btn.setToolTip("Uses the most recent valid characterization for this stock.")

    # NEW: one slot to update both controls when selection changes
    def _on_summary_selection_changed(self):
        self._update_load_button_state()
        self._update_preview_button_label()

    def load_selected_summary_row(self):
        """Apply the selected row's PW & pressure to the machine (atomically if possible)."""
        if DropletImagingDialog._is_calibration_busy(self):
            return
        _, raw = self._selected_summary_row()
        if not raw:
            return

        mismatch_message = self._summary_row_mode_mismatch_message(raw)
        if mismatch_message:
            QtWidgets.QMessageBox.information(self, "Nothing to load", mismatch_message)
            return

        pw = raw.get("pw_us")
        pres = raw.get("pressure_psi")
        valid = raw.get("valid")
        run_no = raw.get("run_no")

        if pw is None or pres is None:
            QtWidgets.QMessageBox.information(self, "Nothing to load", "Selected row is missing PW or Pressure.")
            return

        # Clamp pressure to hardware bounds
        try:
            pres = float(pres)
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Invalid pressure", "Could not parse pressure value.")
            return
        pres = min(max(pres, self.hw_lo), self.hw_hi)

        try:
            pw = int(round(float(pw)))
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Invalid pulse width", "Could not parse pulse width value.")
            return

        # Optional confirm if the row was flagged invalid
        if valid is False:
            reason = "This condition was flagged invalid."
            QtWidgets.QMessageBox.information(self, "Loading flagged condition", reason)

        # Prefer the same atomic path your calibration uses:
        # ask the CalibrationManager to apply *both* settings in one go and wait for ack.
        mgr = self.model.calibration_manager
        self.stageLabel.setText(f"Status: Applying PW {pw} µs, Pressure {pres:.3f} psi (Run {run_no or '—'})…")

        def _after_apply(*_):
            # Reflect values into UI spinboxes without re-triggering handlers
            DropletImagingDialog._sync_manual_spinbox_value(
                self,
                self.print_pulse_width_spinbox,
                pw,
                force=True,
            )
            self.refresh_calibration_memory_recommendation()

            # We don't have a dedicated "live print pressure" spinbox in this panel;
            # if you add one later, mirror pres into it here.
            self.update_stage_and_log(f"Loaded PW {pw} µs & {pres:.3f} psi from Run {run_no or '—'}", "blue")

        try:
            # Use the existing manager→controller pathway for consistency/ack
            mgr.changeSettingsRequested.emit({"print_pulse_width": pw, "print_pressure": pres}, _after_apply)
        except Exception:
            # Fallback: call controller methods if direct setters exist
            applied_ok = False
            try:
                if hasattr(self.controller, "set_print_pulse_width"):
                    self.controller.set_print_pulse_width(pw, manual=True)
                    applied_ok = True
            except Exception:
                pass
            try:
                # If your controller exposes set_print_pressure(value, manual=...), use it.
                if hasattr(self.controller, "set_print_pressure"):
                    self.controller.set_print_pressure(pres, manual=True)
                    applied_ok = True
            except Exception:
                pass

            if applied_ok:
                _after_apply()
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Apply failed",
                    "Could not apply settings via manager or controller."
                )

    def recheck_selected_summary_row(self):
        """Start a one-condition recheck from the selected characterization result."""
        if DropletImagingDialog._is_calibration_busy(self):
            return
        _, raw = self._selected_summary_row()
        if not raw:
            return

        mismatch_message = self._summary_row_mode_mismatch_message(raw)
        if mismatch_message:
            QtWidgets.QMessageBox.information(self, "Cannot recheck", mismatch_message)
            return

        missing = self._summary_row_recheck_missing(raw)
        if missing:
            QtWidgets.QMessageBox.information(
                self,
                "Cannot recheck",
                "Selected result is missing: " + ", ".join(str(item) for item in missing),
            )
            self._update_recheck_button_state(raw=raw, mismatch_message=mismatch_message)
            return

        run_no = raw.get("run_no")
        pw = raw.get("pw_us")
        pres = raw.get("pressure_psi")
        self.stageLabel.setText(
            f"Status: Starting recheck for PW {pw or '-'} us, Pressure {pres or '-'} psi "
            f"(Run {run_no or '-'})..."
        )

        starter = getattr(self.controller, "start_droplet_recheck_characterization", None)
        if callable(starter):
            started = starter(dict(raw))
        else:
            mgr = getattr(getattr(self, "model", None), "calibration_manager", None)
            starter = getattr(mgr, "start_droplet_recheck_characterization", None)
            started = starter(dict(raw)) if callable(starter) else False
        if started is False:
            QtWidgets.QMessageBox.warning(
                self,
                "Recheck not started",
                "The selected result could not be rechecked. Check the status log for details.",
            )
        else:
            self.update_stage_and_log("Started droplet recheck characterization.", "blue")

    def populate_summary_table(self):
        mgr = self.model.calibration_manager
        rows = mgr.get_pressure_sweep_summary_rows()

        # Keep the manager-provided multi-key order (PW → Pressure → Run #)
        self.summary_table.setSortingEnabled(False)
        self.summary_table.setRowCount(0)

        # Subtle, readable “muted” text for invalid rows.
        # Try theme value first; fall back to semi-transparent light text for dark themes.
        muted_hex = (self.color_dict.get("muted_text")
                    or self.color_dict.get("light_gray")
                    or self.color_dict.get("gray")
                    or None)
        if muted_hex:
            muted_brush = QBrush(QColor(muted_hex))
        else:
            muted_brush = QBrush(QColor(255, 255, 255, 150))  # 150/255 alpha = ~60% opacity on dark bg

        def _mk(text):
            it = QtWidgets.QTableWidgetItem(text)
            it.setTextAlignment(Qt.AlignCenter)
            return it

        def _fmt(x, ndigits=2):
            return "" if x is None else f"{x:.{ndigits}f}"

        for r in rows:
            i = self.summary_table.rowCount()
            self.summary_table.insertRow(i)

            run_item  = _mk("" if r.get("run_no") is None else str(r["run_no"]))
            pw_item   = _mk(_fmt(r["pw_us"], 0))
            p_item    = _mk(_fmt(r["pressure_psi"], 3))
            mean_item = _mk(_fmt(r["mean_nL"], 3))
            cv_item   = _mk(_fmt(r["cv_pct"], 2))

            valid = r.get("valid")
            valid_text = "✓" if valid is True else ("✗" if valid is False else "")
            valid_item = _mk(valid_text)

            # NEW: subtle styling — valid rows use default dark theme;
            # invalid rows get muted (faded) text and optional italic to de-emphasize.
            if valid is False:
                for it in (run_item, pw_item, p_item, mean_item, cv_item, valid_item):
                    it.setForeground(muted_brush)
                    f = it.font()
                    f.setItalic(True)
                    it.setFont(f)
                reason = r.get("invalid_reason")
                if reason:
                    tip = f"Invalid: {reason}"
                    for it in (run_item, pw_item, p_item, mean_item, cv_item, valid_item):
                        it.setToolTip(tip)

            # Keep raw numbers accessible even if display text is formatted
            pw_item.setData(Qt.UserRole, r.get("pw_us"))
            p_item.setData(Qt.UserRole, r.get("pressure_psi"))
            valid_item.setData(Qt.UserRole, r.get("valid"))
            # (optional) keep invalid reason for tooltips/confirm
            run_item.setData(Qt.UserRole, r.get("run_no"))
            mean_item.setData(Qt.UserRole, r.get("mean_nL"))
            cv_item.setData(Qt.UserRole, r.get("cv_pct"))
            
            # No extra styling for valid rows (keeps your dark theme + alternating row colors)

            self.summary_table.setItem(i, 0, run_item)
            self.summary_table.setItem(i, 1, pw_item)
            self.summary_table.setItem(i, 2, p_item)
            self.summary_table.setItem(i, 3, mean_item)
            self.summary_table.setItem(i, 4, cv_item)
            self.summary_table.setItem(i, 5, valid_item)
        self.refresh_calibration_memory_recommendation()

    def _update_summary_count_label(self):
        visible = self.summary_table_proxy_model.rowCount()
        total = self.summary_table_model.rowCount()
        noun = "result" if total == 1 else "results"
        self.summary_count_label.setText(f"Showing {visible} of {total} {noun}")

    def _refresh_summary_detail_strip(self):
        _, raw = self._selected_summary_row()
        if not raw:
            self.summary_detail_meta_label.setText("Select a result to see run details.")
            self.summary_detail_status_label.setText("No result selected.")
            return

        run_text = raw.get("run_no")
        source_text = raw.get("phase_label") or "Unknown"
        recorded_text = raw.get("timestamp_display") or "Unknown"
        self.summary_detail_meta_label.setText(
            f"Run {run_text if run_text is not None else '-'} | Source {source_text} | Recorded {recorded_text}"
        )
        status_lines = []
        if raw.get("valid") is False:
            reason = raw.get("invalid_reason") or "flagged"
            status_lines.append(f"Invalid: {reason}")
        else:
            status_lines.append("Valid result")

        if str(raw.get("phase") or "").strip().lower() == "stream":
            stream_parts = []
            duration_us = raw.get("predicted_stream_duration_us")
            if duration_us not in (None, ""):
                stream_parts.append(f"Predicted duration {duration_us} us")
            flow_fit_status = raw.get("flow_fit_status")
            if flow_fit_status not in (None, ""):
                stream_parts.append(f"Flow fit {flow_fit_status}")
            tail_phase_status = raw.get("tail_phase_status")
            if tail_phase_status not in (None, ""):
                stream_parts.append(f"Tail {tail_phase_status}")
            warnings = raw.get("warnings") or []
            if warnings:
                stream_parts.append(f"Warnings: {', '.join(str(item) for item in warnings)}")
            if stream_parts:
                status_lines.append(" | ".join(stream_parts))
        elif str(raw.get("phase") or "").strip().lower() == "recheck":
            recheck_parts = []
            source = raw.get("recheck_source") or {}
            if isinstance(source, dict) and source.get("run_id"):
                recheck_parts.append(f"Source run {source.get('run_id')}")
            delta = raw.get("volume_delta_nL")
            try:
                if delta is not None:
                    recheck_parts.append(f"Delta {float(delta):+.3f} nL")
            except Exception:
                pass
            if recheck_parts:
                status_lines.append(" | ".join(recheck_parts))

        mismatch_message = self._summary_row_mode_mismatch_message(raw)
        if mismatch_message:
            status_lines.append(mismatch_message)

        self.summary_detail_status_label.setText("\n".join(status_lines))

    def _refresh_summary_filters(self):
        self.summary_table_proxy_model.setCurrentRunOnly(self.summary_current_run_checkbox.isChecked())
        self.summary_table_proxy_model.setValidOnly(self.summary_valid_only_checkbox.isChecked())
        self.summary_table_proxy_model.setSourceFilter(self.summary_source_combo.currentData())
        self._update_summary_count_label()
        self._update_load_button_state()
        self._refresh_summary_detail_strip()
        self._refresh_bridge_preview_from_selection()

    def _apply_summary_sort(self, column, order):
        self._summary_sort_column = column
        self._summary_sort_order = order
        header = self.summary_table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(column, order)
        self.summary_table_proxy_model.sort(column, order)

    def _handle_summary_header_click(self, section):
        if self._summary_sort_column == section:
            order = Qt.DescendingOrder if self._summary_sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            order = Qt.AscendingOrder
        self._apply_summary_sort(section, order)

    def open_characterization_history_dialog(self):
        mgr = self.model.calibration_manager
        getter = getattr(mgr, "get_characterization_summary_rows", None)
        if callable(getter):
            rows = getter()
        else:
            rows = mgr.get_pressure_sweep_summary_rows()
        dialog = CharacterizationHistoryDialog(
            self,
            rows=rows,
            muted_brush=getattr(self, "_summary_muted_brush", None),
        )
        dialog.show()
        try:
            dialog.raise_()
            dialog.activateWindow()
        except Exception:
            pass
        self.summary_history_dialog = dialog
        return dialog

    def _selected_summary_row(self):
        """Return (proxy_row_index, raw_row_dict) from the selected visible table row."""
        selection_model = self.summary_table.selectionModel()
        if selection_model is None:
            return None, None
        sel = selection_model.selectedRows()
        if not sel:
            return None, None
        proxy_index = sel[0]
        source_index = self.summary_table_proxy_model.mapToSource(proxy_index)
        if not source_index.isValid():
            return None, None
        raw = self.summary_table_model.raw_row_at(source_index.row())
        if raw is None:
            return None, None
        raw["_row"] = proxy_index.row()
        raw["_source_row"] = source_index.row()
        return proxy_index.row(), raw

    def _update_load_button_state(self):
        """Enable the Load button only when we have a usable selection."""
        _, raw = self._selected_summary_row()
        mismatch_message = self._summary_row_mode_mismatch_message(raw)
        ok = bool(
            raw
            and mismatch_message is None
            and raw.get("pw_us") is not None
            and raw.get("pressure_psi") is not None
            and not DropletImagingDialog._is_calibration_busy(self)
        )
        self.load_selected_button.setEnabled(ok)
        if mismatch_message:
            self.load_selected_button.setToolTip(mismatch_message)
        else:
            self.load_selected_button.setToolTip(
                "Select a row above, then click to apply its PW and pressure."
            )
        self._update_recheck_button_state(raw=raw, mismatch_message=mismatch_message)

    def _handle_summary_double_click(self, _index):
        """Double-click loads immediately (same as pressing the button)."""
        self.load_selected_summary_row()

    def _selected_summary_mean_nL(self) -> float | None:
        _, raw = self._selected_summary_row()
        if not raw:
            return None
        val = raw.get("mean_nL")
        try:
            v = float(val) if val is not None else None
            return v if (v is not None and v > 0) else None
        except Exception:
            return None

    def _preferred_char_mean_nL(self):
        """
        Returns (mean_nL, source) where source is "selected" or (None, None)
        """
        sel = self._selected_summary_mean_nL()
        if sel is not None:
            return sel, "selected"
        return None, None

    def _update_preview_button_label(self):
        return None

    def _on_summary_selection_changed(self, *_args):
        self._update_load_button_state()
        self._refresh_summary_detail_strip()
        self._refresh_bridge_preview_from_selection()

    def load_selected_summary_row(self):
        """Apply the selected row's PW & pressure to the machine (atomically if possible)."""
        if DropletImagingDialog._is_calibration_busy(self):
            return
        _, raw = self._selected_summary_row()
        if not raw:
            return

        mismatch_message = self._summary_row_mode_mismatch_message(raw)
        if mismatch_message:
            QtWidgets.QMessageBox.information(self, "Nothing to load", mismatch_message)
            return

        pw = raw.get("pw_us")
        pres = raw.get("pressure_psi")
        valid = raw.get("valid")
        run_no = raw.get("run_no")

        if pw is None or pres is None:
            QtWidgets.QMessageBox.information(self, "Nothing to load", "Selected row is missing PW or Pressure.")
            return

        try:
            pres = float(pres)
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Invalid pressure", "Could not parse pressure value.")
            return
        pres = min(max(pres, self.hw_lo), self.hw_hi)

        try:
            pw = int(round(float(pw)))
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Invalid pulse width", "Could not parse pulse width value.")
            return

        if valid is False:
            reason = raw.get("invalid_reason") or "This condition was flagged invalid."
            QtWidgets.QMessageBox.information(self, "Loading flagged condition", reason)

        mgr = self.model.calibration_manager
        self.stageLabel.setText(f"Status: Applying PW {pw} us, Pressure {pres:.3f} psi (Run {run_no or '-'})...")

        def _after_apply(*_):
            DropletImagingDialog._sync_manual_spinbox_value(
                self,
                self.print_pulse_width_spinbox,
                pw,
                force=True,
            )
            self.refresh_calibration_memory_recommendation()
            self.update_stage_and_log(f"Loaded PW {pw} us and {pres:.3f} psi from Run {run_no or '-'}", "blue")

        try:
            mgr.changeSettingsRequested.emit({"print_pulse_width": pw, "print_pressure": pres}, _after_apply)
        except Exception:
            applied_ok = False
            try:
                if hasattr(self.controller, "set_print_pulse_width"):
                    self.controller.set_print_pulse_width(pw, manual=True)
                    applied_ok = True
            except Exception:
                pass
            try:
                if hasattr(self.controller, "set_print_pressure"):
                    self.controller.set_print_pressure(pres, manual=True)
                    applied_ok = True
            except Exception:
                pass

            if applied_ok:
                _after_apply()
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Apply failed",
                    "Could not apply settings via manager or controller."
                )

    def populate_summary_table(self):
        mgr = self.model.calibration_manager
        getter = getattr(mgr, "get_characterization_summary_rows", None)
        if callable(getter):
            rows = getter()
        else:
            rows = mgr.get_pressure_sweep_summary_rows()
        self.summary_table_model.set_rows(rows)
        self._sync_applied_summary_row_highlight()
        self._refresh_summary_filters()
        if self._summary_sort_column is not None:
            self._apply_summary_sort(self._summary_sort_column, self._summary_sort_order)
        self.refresh_calibration_memory_recommendation()

    def _bridge_clear_preview_with_status(self, status_text=None):
        self._bridge_preview_payload = None
        self._set_bridge_apply_button_state(
            "unavailable",
            "Select a usable characterization result to preview a new ejection volume.",
        )
        self.bridge_table.clearContents()
        self.bridge_table.setRowCount(0)
        if hasattr(self, "bridge_status_label"):
            self.bridge_status_label.setText(
                str(status_text or "Select a characterization result to preview design impact.")
            )

    def _bridge_refresh_design_labels(self):
        em = getattr(self.model, "experiment_model", None)
        reagent = self._bridge_get_current_reagent_name()
        if hasattr(self, "reagent_title_label"):
            self.reagent_title_label.setText(reagent or "No reagent selected")
        if hasattr(self, "reagent_stock_label"):
            self.reagent_stock_label.setText("Stock concentration(s): —")
        if hasattr(self, "bridge_design_dv_label"):
            self.bridge_design_dv_label.setText("Design ejection volume (nL): —")

        if em is None or not reagent:
            self._sync_applied_summary_row_highlight()
            self._refresh_bridge_preview_from_selection()
            return

        try:
            fill_reagent = em.get_fill_reagent_name()
        except Exception:
            fill_reagent = None

        if reagent == fill_reagent:
            try:
                dv = float(em.metadata.get("fill_droplet_volume_nL", 10.0))
                self.bridge_design_dv_label.setText(f"Design ejection volume (nL): {dv:.3f}  (fill)")
            except Exception:
                self.bridge_design_dv_label.setText("Design ejection volume (nL): —")
            self._sync_applied_summary_row_highlight()
            self._refresh_bridge_preview_from_selection()
            self.refresh_calibration_memory_recommendation()
            return

        try:
            key_opt = em.find_option_by_reagent_name(reagent)
        except Exception:
            key_opt = None
        if not key_opt:
            self._sync_applied_summary_row_highlight()
            self._refresh_bridge_preview_from_selection()
            return

        key, opt = key_opt
        try:
            self.bridge_design_dv_label.setText(f"Design ejection volume (nL): {float(opt.droplet_nL):.3f}")
        except Exception:
            self.bridge_design_dv_label.setText("Design ejection volume (nL): —")

        plan = None
        try:
            plan = em.get_plan_for_key(key)
        except Exception:
            plan = None
        if plan and hasattr(self, "reagent_stock_label"):
            try:
                if plan["n_stocks"] == 1:
                    scs = [plan["stocks"][0]["stock_concentration"]]
                else:
                    scs = [plan["stocks"][0]["stock_concentration"], plan["stocks"][1]["stock_concentration"]]
                units = str(plan["stocks"][0].get("units", "") or "")
                scs_txt = ", ".join(f"{float(c):.4g}" for c in scs)
                suffix = f" {units}" if units else ""
                self.reagent_stock_label.setText(f"Stock concentration(s): {scs_txt}{suffix}")
            except Exception:
                self.reagent_stock_label.setText("Stock concentration(s): —")

        self._sync_applied_summary_row_highlight()
        self._refresh_bridge_preview_from_selection()

    def _refresh_bridge_preview_from_selection(self):
        _, raw = self._selected_summary_row()
        if not raw:
            self._bridge_clear_preview_with_status()
            return

        mean_nL = raw.get("mean_nL")
        try:
            mean_nL = float(mean_nL) if mean_nL is not None else None
        except Exception:
            mean_nL = None
        if mean_nL is None or mean_nL <= 0:
            self._bridge_clear_preview_with_status(
                "Selected result does not contain a usable ejection volume."
            )
            return

        em = getattr(self.model, "experiment_model", None)
        reagent = self._bridge_get_current_reagent_name()
        if em is None or not reagent:
            self._bridge_clear_preview_with_status(
                "No current reagent is available for bridge preview."
            )
            return

        mismatch_message = self._summary_row_mode_mismatch_message(raw)
        if mismatch_message:
            self._bridge_clear_preview_with_status(mismatch_message)
            return

        selected_fingerprint = self._summary_row_fingerprint(raw)
        invalid_reason = raw.get("invalid_reason")
        status_prefix = (
            f"Selected result is flagged invalid ({invalid_reason or 'flagged'}); "
            if raw.get("valid") is False
            else ""
        )

        try:
            fill_reagent = em.get_fill_reagent_name()
        except Exception:
            fill_reagent = None

        if reagent == fill_reagent:
            try:
                preview = em.preview_fill_requantized(mean_nL)
            except Exception as exc:
                self._bridge_clear_preview_with_status(f"Bridge preview failed: {exc}")
                return
            if not preview.get("ok"):
                self._bridge_clear_preview_with_status(
                    str(preview.get("reason") or "Bridge preview failed.")
                )
                return

            self.bridge_table.clearContents()
            self.bridge_table.setRowCount(1)
            row = preview["rows"][0]

            def _it(txt):
                return QtWidgets.QTableWidgetItem("" if txt is None else str(txt))

            self.bridge_table.setItem(0, 0, _it("—"))
            self.bridge_table.setItem(0, 1, _it("—"))
            self.bridge_table.setItem(0, 2, _it("—"))
            self.bridge_table.setItem(0, 3, _it(preview.get("total_drops_new")))
            self.bridge_table.setItem(0, 4, _it(_format_bridge_number(mean_nL, 4, trim=True, suffix=" nL/drop")))
            self.bridge_table.setItem(0, 5, _it(_format_bridge_number(row["printed_nL_new"], 2, suffix=" nL")))
            self.bridge_table.setItem(0, 6, _it(_format_bridge_number(row["printed_nL_shift"], 2, signed=True, suffix=" nL")))
            self.bridge_table.resizeColumnsToContents()
            self.bridge_table.resizeRowsToContents()
            self._bridge_preview_payload = {
                "is_fill": True,
                "new_fill_nL": float(mean_nL),
                "source_row_fingerprint": selected_fingerprint,
            }
            if self._selected_summary_row_matches_applied(raw):
                self._set_bridge_apply_button_state("applied")
            else:
                self._set_bridge_apply_button_state("ready")
            self.bridge_status_label.setText(
                f"{status_prefix}Preview uses the selected result ejection volume of {mean_nL:.3f} nL."
            )
            return

        try:
            key = em.find_key_for_reagent(reagent)
        except Exception as exc:
            self._bridge_clear_preview_with_status(f"Bridge preview unavailable: {exc}")
            return

        try:
            preview = em.preview_requantized_for_option(key, float(mean_nL), quantum=0.1)
        except Exception as exc:
            self._bridge_clear_preview_with_status(f"Bridge preview failed: {exc}")
            return
        if not preview.get("ok"):
            self._bridge_clear_preview_with_status(
                str(preview.get("reason") or "Bridge preview failed.")
            )
            return

        self._populate_bridge_preview_table(preview)
        self._bridge_preview_payload = {
            "factor_name": key[0],
            "option_name": key[1],
            "new_droplet_nL": float(preview.get("new_droplet_nL", mean_nL)),
            "n_stocks": int(preview.get("n_stocks", 1)),
            "source_row_fingerprint": selected_fingerprint,
        }
        can_apply = self._bridge_preview_payload["n_stocks"] == 1
        if can_apply and self._selected_summary_row_matches_applied(raw):
            self._set_bridge_apply_button_state("applied")
        elif can_apply:
            self._set_bridge_apply_button_state("ready")
        else:
            self._set_bridge_apply_button_state(
                "unavailable",
                "Apply supports single-stock reagents only right now.",
            )
        if can_apply:
            self.bridge_status_label.setText(
                f"{status_prefix}Preview uses the selected result ejection volume of {mean_nL:.3f} nL."
            )
        else:
            self.bridge_status_label.setText(
                f"{status_prefix}Preview is shown, but apply currently supports single-stock reagents only."
            )

    def center_nozzle(self):
        self.controller.center_nozzle_in_camera(position='top')

    def update_position_diffs(self, current_dict, position_diff_dict):
        """
        Updates the current position and position difference labels.
        """
        for motor, positions in self.diff_labels.items():
            positions['current'].setText(str(current_dict[motor]))
            positions['diff'].setText(str(position_diff_dict[motor]))


    def update_image(self):
        # 1) Get the full-resolution image from the model
        image = self.model.droplet_camera_model.get_original_image()
        if image is None:
            # Optionally clear the label or show a placeholder
            self.image_label.clear()
            self.image_label.setText("No image captured yet.")
            return

        self._maybe_hide_online_stream_debug_for_nonstream_preview()

        # 2) Convert it to QImage
        qimage = self.numpy_to_qimage(image)

        # 3) Convert QImage -> QPixmap
        pixmap = QPixmap.fromImage(qimage)

        # 4) Scale the pixmap to fit inside the label (640x480), preserving aspect ratio
        scaled_pixmap = pixmap.scaled(
            self.image_label.width(),
            self.image_label.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation  # for smoother resizing
        )

        # 5) Set the scaled pixmap
        self.image_label.setPixmap(scaled_pixmap)

    def display_analyzed_image(self, image):
        """
        Display the analyzed image.
        """
        self._maybe_hide_online_stream_debug_for_nonstream_preview()
        qimage = self.numpy_to_qimage(image)
        pixmap = QPixmap.fromImage(qimage)
        scaled_pixmap = pixmap.scaled(
            self.image_label.width(),
            self.image_label.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.image_label.setPixmap(scaled_pixmap)

    def closeEvent(self, event):
        """Handle the closing of the dialog."""
        if self._should_confirm_close_without_applied_calibration():
            response = QtWidgets.QMessageBox.question(
                self,
                "Exit without applied calibration?",
                self._close_without_applied_calibration_message(),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if response != QtWidgets.QMessageBox.Yes:
                event.ignore()
                return

        self._stream_capture_dialog_closing = True
        recovery_dialog = getattr(self, "_printer_head_recovery_dialog", None)
        if recovery_dialog is not None:
            try:
                recovery_dialog.close()
            except Exception:
                pass
        if getattr(self, "_optics_session_active", False):
            try:
                self.model.droplet_camera_model.stop_saving()
            except Exception:
                pass
            self._optics_session_active = False
        self._close_stream_capture_mass_dialog()
        self._reset_online_stream_debug_view(hide=True)
        self.camera_timer.stop()
        self._auto_export_refuel_performance_snapshot_on_close()
        self._stop_refuel_monitor("Monitoring disabled")
        try:
            self.controller.set_droplet_capture_profile("default")
            self.controller.set_command_dispatch_interval(90)
        except Exception:
            pass
        self.stop_droplet_camera()
        self._set_stream_capture_read_camera_enabled(False)
        self.controller.disable_print_profile()
        event.accept()


class NozzlePositionDatasetCaptureWindow(QtWidgets.QDialog):
    PROCESS_NAME = "NozzlePositionCalibrationProcess"
    _ALREADY_CONNECTED_HINTS = (
        "already connected",
        "already started",
        "already running",
        "device or resource busy",
        "resource busy",
    )

    def __init__(self, main_window, model, controller):
        super().__init__()
        self.main_window = main_window
        self.color_dict = getattr(main_window, "color_dict", {})
        self.model = model
        self.controller = controller
        self.droplet_camera_model = model.droplet_camera_model
        self.shortcut_manager = ShortcutManager(self)

        self.store = NozzlePositionChecklistStore(self.model, process_name=self.PROCESS_NAME)
        self.store.begin_session()

        self._rows = self.store.get_rows()
        self._capture_inflight = False
        self._cleanup_done = False
        self._camera_reused = False
        self._camera_start_error = None

        self._build_ui()
        self._configure_focus_behavior()
        self.setup_shortcuts()
        self._connect_signals()
        self._populate_checklist()
        self._sync_setting_controls_from_model()
        camera_ready = self._start_camera_session()
        if camera_ready:
            self._set_status(self._session_ready_text(), color="darkgreen")
        else:
            self._set_status(
                f"{self._session_ready_text()} (camera unavailable: {self._camera_start_error})",
                color="red",
            )
        self._apply_flash_safety_state()

    def _session_ready_text(self):
        msg = f"Session created: {self.store.session_id}"
        if self._camera_reused:
            msg += " (reused existing camera session)"
        return msg

    @staticmethod
    def _is_already_connected_error(exc: Exception) -> bool:
        msg = str(exc).strip().lower()
        return any(hint in msg for hint in NozzlePositionDatasetCaptureWindow._ALREADY_CONNECTED_HINTS)

    def _start_camera_session(self):
        try:
            self.controller.start_droplet_camera()
        except Exception as exc:
            if self._is_already_connected_error(exc):
                self._camera_reused = True
                print(f"[NozzleDataset] Reusing existing droplet camera session: {exc}")
            else:
                self._camera_start_error = str(exc)
                return False

        try:
            self.controller.start_read_camera()
        except Exception as exc:
            if self._is_already_connected_error(exc):
                self._camera_reused = True
                print(f"[NozzleDataset] Reusing existing read-camera stream: {exc}")
            else:
                self._camera_start_error = str(exc)
                return False
        return True

    def _configure_focus_behavior(self):
        self.setFocusPolicy(Qt.StrongFocus)
        no_focus_widgets = (
            self.checklist_table,
            self.flash_duration_spin,
            self.flash_delay_spin,
            self.exposure_spin,
            self.num_droplets_spin,
            self.print_pw_spin,
            self.print_pressure_spin,
            self.capture_preview_btn,
            self.capture_pair_btn,
            self.reject_last_btn,
        )
        for widget in no_focus_widgets:
            widget.setFocusPolicy(Qt.NoFocus)

    def _build_ui(self):
        self.setWindowTitle("Nozzle Position Dataset Capture")
        self.resize(1300, 900)

        root = QtWidgets.QHBoxLayout(self)

        left = QtWidgets.QWidget()
        left_v = QtWidgets.QVBoxLayout(left)
        left_v.setContentsMargins(6, 6, 6, 6)
        left_v.setSpacing(8)

        session_group = QtWidgets.QGroupBox("Dataset Session")
        session_form = QtWidgets.QFormLayout(session_group)
        self.root_path_value = QtWidgets.QLabel(self.store.base_dir)
        self.root_path_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.manifest_path_value = QtWidgets.QLabel(self.store.manifest_path)
        self.manifest_path_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.session_path_value = QtWidgets.QLabel(self.store.session_dir)
        self.session_path_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        session_form.addRow("Root:", self.root_path_value)
        session_form.addRow("Manifest:", self.manifest_path_value)
        session_form.addRow("Session:", self.session_path_value)
        left_v.addWidget(session_group)

        checklist_group = QtWidgets.QGroupBox("Image Checklist")
        checklist_v = QtWidgets.QVBoxLayout(checklist_group)
        self.checklist_table = QtWidgets.QTableWidget(0, 6)
        self.checklist_table.setHorizontalHeaderLabels(
            ["Status", "Case", "Step", "Expected", "Required", "Captured"]
        )
        self.checklist_table.verticalHeader().setVisible(False)
        self.checklist_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.checklist_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.checklist_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.checklist_table.setAlternatingRowColors(True)
        self.checklist_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.checklist_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.checklist_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.checklist_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self.checklist_table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        self.checklist_table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeToContents)
        checklist_v.addWidget(self.checklist_table)

        self.selected_label_value = QtWidgets.QLabel("Selected: -")
        self.selected_label_value.setWordWrap(True)
        checklist_v.addWidget(self.selected_label_value)
        left_v.addWidget(checklist_group, 1)

        settings_group = QtWidgets.QGroupBox("Imaging Conditions")
        settings_grid = QtWidgets.QGridLayout(settings_group)
        r = 0
        self.flash_duration_spin = QtWidgets.QSpinBox()
        self.flash_duration_spin.setRange(0, 10000)
        self.flash_duration_spin.setSingleStep(100)
        settings_grid.addWidget(QtWidgets.QLabel("Flash Duration (us):"), r, 0)
        settings_grid.addWidget(self.flash_duration_spin, r, 1)
        r += 1

        self.flash_delay_spin = QtWidgets.QSpinBox()
        self.flash_delay_spin.setRange(0, 50000)
        self.flash_delay_spin.setSingleStep(100)
        settings_grid.addWidget(QtWidgets.QLabel("Flash Delay (us):"), r, 0)
        settings_grid.addWidget(self.flash_delay_spin, r, 1)
        r += 1

        self.exposure_spin = QtWidgets.QSpinBox()
        self.exposure_spin.setRange(0, 1_000_000)
        self.exposure_spin.setSingleStep(1000)
        settings_grid.addWidget(QtWidgets.QLabel("Exposure (us):"), r, 0)
        settings_grid.addWidget(self.exposure_spin, r, 1)
        r += 1

        self.num_droplets_spin = QtWidgets.QSpinBox()
        self.num_droplets_spin.setRange(0, 20)
        self.num_droplets_spin.setValue(1)
        settings_grid.addWidget(QtWidgets.QLabel("Droplets per image:"), r, 0)
        settings_grid.addWidget(self.num_droplets_spin, r, 1)
        r += 1

        self.print_pw_spin = QtWidgets.QSpinBox()
        self.print_pw_spin.setRange(0, 10000)
        self.print_pw_spin.setSingleStep(50)
        settings_grid.addWidget(QtWidgets.QLabel("Print Pulse Width (us):"), r, 0)
        settings_grid.addWidget(self.print_pw_spin, r, 1)
        r += 1

        self.print_pressure_spin = QtWidgets.QDoubleSpinBox()
        self.print_pressure_spin.setDecimals(3)
        self.print_pressure_spin.setSingleStep(0.01)
        try:
            p_lo, p_hi = self.model.machine_model.get_print_pressure_bounds()
        except Exception:
            p_lo, p_hi = 0.1, 5.0
        self.print_pressure_spin.setRange(float(p_lo), float(p_hi))
        settings_grid.addWidget(QtWidgets.QLabel("Print Pressure (psi):"), r, 0)
        settings_grid.addWidget(self.print_pressure_spin, r, 1)
        r += 1

        left_v.addWidget(settings_group)

        capture_group = QtWidgets.QGroupBox("Capture")
        capture_v = QtWidgets.QVBoxLayout(capture_group)
        self.capture_preview_btn = QtWidgets.QPushButton("Capture Preview (No Save)")
        self.capture_pair_btn = QtWidgets.QPushButton("Capture Background + Droplet")
        self.reject_last_btn = QtWidgets.QPushButton("Reject Last Image")
        capture_v.addWidget(self.capture_preview_btn)
        capture_v.addWidget(self.capture_pair_btn)
        capture_v.addWidget(self.reject_last_btn)

        self.status_label = QtWidgets.QLabel("Idle")
        self.status_label.setWordWrap(True)
        capture_v.addWidget(self.status_label)
        self.flash_safety_label = QtWidgets.QLabel("Flash session disarmed.")
        self.flash_safety_label.setWordWrap(True)
        capture_v.addWidget(self.flash_safety_label)
        left_v.addWidget(capture_group)

        right = QtWidgets.QWidget()
        right_v = QtWidgets.QVBoxLayout(right)
        right_v.setContentsMargins(6, 6, 6, 6)
        right_v.setSpacing(8)

        self.preview_label = QtWidgets.QLabel("No image captured yet.")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(640, 640)
        self.preview_label.setStyleSheet("border: 1px solid #555;")
        right_v.addWidget(self.preview_label, 1)

        self.last_record_label = QtWidgets.QLabel("Last record: -")
        self.last_record_label.setWordWrap(True)
        right_v.addWidget(self.last_record_label)

        root.addWidget(left, 0)
        root.addWidget(right, 1)
        root.setStretchFactor(left, 0)
        root.setStretchFactor(right, 1)

    def _connect_signals(self):
        self.checklist_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.capture_preview_btn.clicked.connect(self._capture_preview_only)
        self.capture_pair_btn.clicked.connect(self._capture_background_then_droplet)
        self.reject_last_btn.clicked.connect(self._reject_last_image)
        self.model.droplet_camera_model.flash_signal.connect(self._apply_flash_safety_state)

        self.flash_duration_spin.valueChanged.connect(
            lambda v: self.controller.set_flash_duration(int(v))
        )
        self.flash_delay_spin.valueChanged.connect(
            lambda v: self.controller.set_flash_delay(int(v))
        )
        self.exposure_spin.valueChanged.connect(
            lambda v: self.controller.set_exposure_time(int(v))
        )
        self.print_pw_spin.valueChanged.connect(
            lambda v: self.controller.set_print_pulse_width(int(v), manual=True)
        )
        self.print_pressure_spin.valueChanged.connect(
            lambda v: self.controller.set_absolute_print_pressure(float(v), manual=True)
        )

    def _sync_setting_controls_from_model(self):
        try:
            self.flash_duration_spin.setValue(int(self.model.droplet_camera_model.get_flash_duration()))
        except Exception:
            pass
        try:
            self.flash_delay_spin.setValue(int(self.model.droplet_camera_model.get_flash_delay()))
        except Exception:
            pass
        try:
            self.exposure_spin.setValue(int(self.model.droplet_camera_model.get_exposure_time()))
        except Exception:
            pass
        try:
            self.print_pw_spin.setValue(int(self.model.machine_model.get_print_pulse_width()))
        except Exception:
            pass
        try:
            self.print_pressure_spin.setValue(float(self.model.machine_model.get_current_print_pressure()))
        except Exception:
            pass

    def _populate_checklist(self):
        statuses = self.store.get_all_status()
        rows = self.store.get_rows()
        self.checklist_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            st = statuses[row["row_key"]]
            bg = int(st["accepted_background"])
            dr = int(st["accepted_droplet"])
            bg_req = int(st["required_background"])
            dr_req = int(st["required_droplet"])
            if st["complete"]:
                status_text = "Complete"
            elif (bg > 0) or (dr > 0):
                status_text = "In Progress"
            else:
                status_text = "Missing"

            expected = f"{row.get('expected_status','')}/{row.get('expected_decision','')}".strip("/")
            required = f"bg>={bg_req}, dr>={dr_req}"
            captured = f"bg {bg}/{bg_req}, dr {dr}/{dr_req}"

            status_item = QtWidgets.QTableWidgetItem(status_text)
            status_item.setData(Qt.UserRole, row["row_key"])
            case_item = QtWidgets.QTableWidgetItem(row["case_id"])
            step_item = QtWidgets.QTableWidgetItem(row["step_label"])
            exp_item = QtWidgets.QTableWidgetItem(expected)
            req_item = QtWidgets.QTableWidgetItem(required)
            cap_item = QtWidgets.QTableWidgetItem(captured)

            tip = row.get("tooltip", "") or row["step_label"]
            for it in (status_item, case_item, step_item, exp_item, req_item, cap_item):
                it.setToolTip(tip)

            if st["complete"]:
                brush = QtGui.QBrush(QtGui.QColor(110, 200, 120))
                status_item.setForeground(brush)
            elif status_text == "In Progress":
                brush = QtGui.QBrush(QtGui.QColor(240, 200, 120))
                status_item.setForeground(brush)
            else:
                brush = QtGui.QBrush(QtGui.QColor(220, 120, 120))
                status_item.setForeground(brush)

            self.checklist_table.setItem(i, 0, status_item)
            self.checklist_table.setItem(i, 1, case_item)
            self.checklist_table.setItem(i, 2, step_item)
            self.checklist_table.setItem(i, 3, exp_item)
            self.checklist_table.setItem(i, 4, req_item)
            self.checklist_table.setItem(i, 5, cap_item)

        if rows and self.checklist_table.currentRow() < 0:
            self.checklist_table.selectRow(0)
        self._update_selection_label()

    def _on_selection_changed(self):
        self._update_selection_label()

    def _selected_row(self):
        ridx = self.checklist_table.currentRow()
        if ridx < 0:
            return None
        item = self.checklist_table.item(ridx, 0)
        if item is None:
            return None
        row_key = item.data(Qt.UserRole)
        if not row_key:
            return None
        return self.store.get_row(row_key)

    def _update_selection_label(self):
        row = self._selected_row()
        if not row:
            self.selected_label_value.setText("Selected: -")
            return
        txt = f"Selected: {row['case_id']} / {row['step_label']}\n{row.get('tooltip','')}"
        self.selected_label_value.setText(txt)

    def _set_buttons_enabled(self, enabled: bool):
        enabled = bool(enabled) and not self._is_flash_fault_latched()
        self.capture_preview_btn.setEnabled(enabled)
        self.capture_pair_btn.setEnabled(enabled)
        self.reject_last_btn.setEnabled(enabled)

    def _is_flash_fault_latched(self):
        getter = getattr(self.model.droplet_camera_model, "get_flash_fault_latched", None)
        if callable(getter):
            try:
                return bool(getter())
            except Exception:
                return False
        return bool(getattr(self.model.droplet_camera_model, "flash_fault_latched", False))

    def _flash_fault_reason_text(self):
        getter = getattr(self.model.droplet_camera_model, "get_flash_fault_reason_display", None)
        if callable(getter):
            try:
                return str(getter())
            except Exception:
                pass
        raw = str(getattr(self.model.droplet_camera_model, "flash_fault_reason", "") or "").strip()
        return raw.replace("_", " ") if raw else "None"

    def _apply_flash_safety_state(self):
        armed_getter = getattr(self.model.droplet_camera_model, "get_flash_session_armed", None)
        session_armed = bool(armed_getter()) if callable(armed_getter) else bool(
            getattr(self.model.droplet_camera_model, "flash_session_armed", False)
        )
        if self._is_flash_fault_latched():
            self._set_buttons_enabled(False)
            self.flash_safety_label.setText(
                "Flash safety fault latched: "
                f"{self._flash_fault_reason_text()}. Close and reopen the dataset window after PE8 is low."
            )
            self.flash_safety_label.setStyleSheet("color: darkred; font-weight: 600;")
        elif session_armed:
            self.flash_safety_label.setText("Flash session armed.")
            self.flash_safety_label.setStyleSheet("color: darkgreen;")
            if not self._capture_inflight:
                self._set_buttons_enabled(True)
        else:
            self.flash_safety_label.setText("Flash session disarmed.")
            self.flash_safety_label.setStyleSheet("color: #555555;")

    def setup_shortcuts(self):
        """
        Match movement shortcuts from the standard droplet imaging window.
        """
        self._movement_shortcuts = []

        def _add_move_shortcut(seq, description, callback):
            shortcut = self.shortcut_manager.add_shortcut(seq, description, callback)
            shortcut.setContext(Qt.ApplicationShortcut)
            self._movement_shortcuts.append(shortcut)

        _add_move_shortcut('Left', 'Move left', lambda: self.move_fraction_of_frame(-0.1, 0))
        _add_move_shortcut('Right', 'Move right', lambda: self.move_fraction_of_frame(0.1, 0))
        _add_move_shortcut('Up', 'Move up', lambda: self.move_fraction_of_frame(0, -0.1))
        _add_move_shortcut('Down', 'Move down', lambda: self.move_fraction_of_frame(0, 0.1))
        _add_move_shortcut('Ctrl+Left', 'Move left', lambda: self.move_fraction_of_frame(-1, 0))
        _add_move_shortcut('Ctrl+Right', 'Move right', lambda: self.move_fraction_of_frame(1, 0))
        _add_move_shortcut('Ctrl+Up', 'Move up', lambda: self.move_fraction_of_frame(0, -1))
        _add_move_shortcut('Ctrl+Down', 'Move down', lambda: self.move_fraction_of_frame(0, 1))
        _add_move_shortcut('k', 'Move forward', lambda: self.controller.set_relative_Y(5, manual=True))
        _add_move_shortcut('j', 'Move backward', lambda: self.controller.set_relative_Y(-5, manual=True))
        _add_move_shortcut('Ctrl+k', 'Move forward', lambda: self.controller.set_relative_Y(25, manual=True))
        _add_move_shortcut('Ctrl+j', 'Move backward', lambda: self.controller.set_relative_Y(-25, manual=True))

    def move_fraction_of_frame(self, x_fraction, y_fraction):
        dX, dY, dZ = self.model.droplet_camera_model.compute_move_by_fraction(x_fraction, y_fraction)
        self.controller.set_relative_coordinates(dX, dY, dZ, manual=False)

    def _set_status(self, text: str, *, color: str = "black"):
        self.status_label.setText(str(text))
        self.status_label.setStyleSheet(f"color: {color};")

    def _machine_state_snapshot(self):
        mm = self.model.machine_model
        try:
            pos = mm.get_current_position_dict() or {}
        except Exception:
            pos = {}
        out = {
            "X": int(pos.get("X", 0)) if isinstance(pos, dict) else 0,
            "Y": int(pos.get("Y", 0)) if isinstance(pos, dict) else 0,
            "Z": int(pos.get("Z", 0)) if isinstance(pos, dict) else 0,
        }
        try:
            out["print_pressure"] = float(mm.get_current_print_pressure())
        except Exception:
            out["print_pressure"] = None
        try:
            out["print_pulse_width_us"] = int(mm.get_print_pulse_width())
        except Exception:
            out["print_pulse_width_us"] = None
        return out

    def _camera_settings_snapshot(self):
        out = {}
        try:
            nf, fdur, fdelay, ndrop, exp = self.model.droplet_camera_model.get_image_metadata()
            out.update(
                {
                    "num_flashes": int(nf),
                    "flash_duration_us": int(fdur),
                    "flash_delay_us": int(fdelay),
                    "num_droplets": int(ndrop),
                    "exposure_time_us": int(exp),
                }
            )
        except Exception:
            pass
        return out

    def _store_capture_record(
        self,
        row,
        role: str,
        frame,
        *,
        pair_id: str | None = None,
        pair_role: str | None = None,
        pair_order: int | None = None,
        pair_capture_mode: str | None = None,
        subtract_background_record_id: str | None = None,
        subtract_background_image_relpath: str | None = None,
    ):
        selected_label = f"{row['case_label']} / {row['step_label']}"
        rec = self.store.capture_for_row(
            row["row_key"],
            role,
            frame,
            selected_label=selected_label,
            machine_state=self._machine_state_snapshot(),
            camera_settings=self._camera_settings_snapshot(),
            reagent_name=self.store.resolve_reagent_name(),
            pair_id=pair_id,
            pair_role=pair_role,
            pair_order=pair_order,
            pair_capture_mode=pair_capture_mode,
            subtract_background_record_id=subtract_background_record_id,
            subtract_background_image_relpath=subtract_background_image_relpath,
        )
        self._show_preview(frame)
        self.last_record_label.setText(
            f"Last record: {rec['record_id']} | {rec['capture_role']} | {rec['case_id']}:{rec['step_id']}\n"
            f"{rec['image_relpath']}"
        )
        return rec

    def _capture_background_then_droplet(self):
        if self._capture_inflight:
            return
        row = self._selected_row()
        if row is None:
            QtWidgets.QMessageBox.warning(self, "No selection", "Select a checklist row before capturing.")
            return

        target_droplets = int(max(1, self.num_droplets_spin.value()))
        pair_id = str(uuid.uuid4())
        pair_capture_mode = "background_then_droplet"
        self._capture_inflight = True
        self._set_buttons_enabled(False)
        self._set_status(
            f"Capturing background + droplet for {row['case_id']} / {row['step_id']}...",
            color="darkblue",
        )

        def _fail(message: str, *, critical: bool = False, dialog_message: str | None = None):
            self._capture_inflight = False
            self._set_buttons_enabled(True)
            self._set_status(message, color="red")
            if dialog_message:
                if critical:
                    QtWidgets.QMessageBox.critical(self, "Capture failed", dialog_message)
                else:
                    QtWidgets.QMessageBox.warning(self, "Capture failed", dialog_message)

        def _finish_success():
            self._capture_inflight = False
            self._set_buttons_enabled(True)
            self._populate_checklist()
            if self.store.is_complete():
                self._set_status("Checklist complete (minimum required replicates met).", color="darkgreen")
            else:
                self._set_status("Background + droplet capture stored.", color="darkgreen")

        def _on_background_frame(frame):
            if frame is None:
                _fail("Background capture failed.", dialog_message="Camera did not return a background frame.")
                return
            try:
                background_record = self._store_capture_record(
                    row,
                    "background",
                    frame,
                    pair_id=pair_id,
                    pair_role="background",
                    pair_order=1,
                    pair_capture_mode=pair_capture_mode,
                )
            except Exception as e:
                _fail(f"Background save failed: {e}", critical=True, dialog_message=str(e))
                return

            bg_rec_id = background_record.get("record_id")
            bg_relpath = background_record.get("image_relpath")

            def _start_paired_droplet_phase():
                self._set_status(
                    f"Capturing droplet for {row['case_id']} / {row['step_id']}...",
                    color="darkblue",
                )

                def _on_droplet_frame(frame):
                    if frame is None:
                        _fail("Droplet capture failed.", dialog_message="Camera did not return a droplet frame.")
                        return
                    try:
                        self._store_capture_record(
                            row,
                            "droplet",
                            frame,
                            pair_id=pair_id,
                            pair_role="droplet",
                            pair_order=2,
                            pair_capture_mode=pair_capture_mode,
                            subtract_background_record_id=bg_rec_id,
                            subtract_background_image_relpath=bg_relpath,
                        )
                    except Exception as e:
                        _fail(f"Droplet save failed: {e}", critical=True, dialog_message=str(e))
                        return
                    _finish_success()

                def _after_set_droplets():
                    ok = self.controller.capture_droplet_image(callback=_on_droplet_frame)
                    if ok is False:
                        _fail("Droplet capture request was dropped (capture already pending).")

                try:
                    self.controller.set_imaging_droplets(target_droplets, callback=_after_set_droplets)
                except Exception as e:
                    _fail(f"Unable to set imaging droplets for droplet capture: {e}")

            _start_paired_droplet_phase()

        def _after_set_background_droplets():
            ok = self.controller.capture_droplet_image(callback=_on_background_frame)
            if ok is False:
                _fail("Background capture request was dropped (capture already pending).")

        try:
            self.controller.set_imaging_droplets(0, callback=_after_set_background_droplets)
        except Exception as e:
            _fail(f"Unable to set imaging droplets for background capture: {e}")

    def _capture_preview_only(self):
        """
        Capture an image using current conditions but do not persist it to checklist storage.
        """
        if self._capture_inflight:
            return

        target_droplets = int(max(0, self.num_droplets_spin.value()))
        self._capture_inflight = True
        self._set_buttons_enabled(False)
        self._set_status(f"Capturing preview (droplets={target_droplets})...", color="darkblue")

        def _on_frame(frame):
            self._capture_inflight = False
            self._set_buttons_enabled(True)
            if frame is None:
                self._set_status("Preview capture failed.", color="red")
                QtWidgets.QMessageBox.warning(self, "Capture failed", "Camera did not return a frame.")
                return
            self._show_preview(frame)
            self._set_status("Preview captured (not saved).", color="darkgreen")

        def _after_set_droplets():
            ok = self.controller.capture_droplet_image(callback=_on_frame)
            if ok is False:
                self._capture_inflight = False
                self._set_buttons_enabled(True)
                self._set_status("Preview capture request was dropped (capture already pending).", color="red")

        try:
            self.controller.set_imaging_droplets(int(target_droplets), callback=_after_set_droplets)
        except Exception as e:
            self._capture_inflight = False
            self._set_buttons_enabled(True)
            self._set_status(f"Unable to set imaging droplets for preview: {e}", color="red")

    def _reject_last_image(self):
        reason, ok = QtWidgets.QInputDialog.getText(
            self,
            "Reject Last Image",
            "Reason (optional):",
            QtWidgets.QLineEdit.Normal,
            "",
        )
        if not ok:
            return
        evt = self.store.reject_last_capture(reason=reason)
        if evt is None:
            QtWidgets.QMessageBox.information(self, "Nothing to reject", "No previous capture to reject.")
            return
        self._populate_checklist()
        self._set_status("Last capture marked as rejected.", color="darkorange")

    def _numpy_to_qimage(self, image):
        if image is None:
            return QImage()
        if image.ndim == 2:
            h, w = image.shape
            return QImage(image.data, w, h, w, QImage.Format_Grayscale8).copy()
        if image.ndim == 3 and image.shape[2] == 3:
            h, w, c = image.shape
            return QImage(image.data, w, h, c * w, QImage.Format_RGB888).copy()
        if image.ndim == 3 and image.shape[2] == 4:
            h, w, c = image.shape
            return QImage(image.data, w, h, c * w, QImage.Format_RGBA8888).copy()
        return QImage()

    def _show_preview(self, image):
        q = self._numpy_to_qimage(image)
        pm = QPixmap.fromImage(q)
        pm = pm.scaled(
            self.preview_label.width(),
            self.preview_label.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(pm)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)

    def _shutdown_camera_resources(self):
        if self._cleanup_done:
            return
        self._cleanup_done = True
        try:
            self.controller.stop_read_camera()
        except Exception as exc:
            print(f"[NozzleDataset] stop_read_camera failed: {exc}")
        try:
            self.controller.stop_droplet_camera()
        except Exception as exc:
            print(f"[NozzleDataset] stop_droplet_camera failed: {exc}")
        try:
            self.controller.disable_print_profile()
        except Exception as exc:
            print(f"[NozzleDataset] disable_print_profile failed: {exc}")

    def done(self, r):
        self._shutdown_camera_resources()
        super().done(r)

    def closeEvent(self, event):
        self._shutdown_camera_resources()
        event.accept()


class RefuelCameraWindow(QtWidgets.QDialog):
    def __init__(self, main_window, model, controller):
        super().__init__()
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict

        self.model = model
        self.refuel_camera_model = self.model.refuel_camera_model
        self.refuel_camera_model.attach_owner_model(self.model)
        self.controller = controller
        self._camera_ready = False
        self._camera_failure_shown = False
        self._dataset_sequence_state = None
        self._capture_interval_ms = 500
        self._save_dir = Path(__file__).resolve().parents[2] / "artifacts" / "refuel_camera_frames"
        self.refuel_camera_model.set_capture_interval_ms(self._capture_interval_ms)

        self.shortcut_manager = ShortcutManager(self)
        self.setup_shortcuts()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Refuel Camera")
        self.resize(1320, 860)

        root = QHBoxLayout(self)

        control_container = QtWidgets.QWidget()
        control_layout = QVBoxLayout(control_container)
        control_layout.setContentsMargins(0, 0, 0, 0)

        capture_group = QtWidgets.QGroupBox("Capture")
        capture_form = QtWidgets.QFormLayout(capture_group)
        self.capture_button = QPushButton("Start Capturing Images")
        self.capture_button.clicked.connect(self.toggle_capture)
        self.save_button = QPushButton("Save Snapshot")
        self.save_button.clicked.connect(self.save_frame)

        self.level_label = QLabel("Current Level: N/A")
        self.level_label.setAlignment(Qt.AlignCenter)
        self.level_label.setStyleSheet("background-color: lightgray; border: 1px solid black; padding: 4px;")

        self.snapshot_folder_label = QLabel(str(self._save_dir))
        self.snapshot_folder_label.setWordWrap(True)
        self.snapshot_folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.last_snapshot_label = QLabel("-")
        self.last_snapshot_label.setWordWrap(True)
        self.last_snapshot_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.capture_help_label = QLabel(
            "Use Save Snapshot for ad hoc raw images. Use Dataset Capture below for training data."
        )
        self.capture_help_label.setWordWrap(True)

        capture_form.addRow(self.capture_button)
        capture_form.addRow(self.save_button)
        capture_form.addRow("Current Level", self.level_label)
        capture_form.addRow("Snapshot Folder", self.snapshot_folder_label)
        capture_form.addRow("Last Snapshot", self.last_snapshot_label)
        capture_form.addRow(self.capture_help_label)
        control_layout.addWidget(capture_group)

        analysis_group = QtWidgets.QGroupBox("Analysis")
        analysis_form = QtWidgets.QFormLayout(analysis_group)

        self.offset_spinbox = QSpinBox()
        self.offset_spinbox.setRange(0, 100)
        self.offset_spinbox.setValue(40)
        self.offset_spinbox.setSingleStep(2)
        self.offset_spinbox.valueChanged.connect(self.update_analysis)

        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(0, 200)
        self.width_spinbox.setValue(20)
        self.width_spinbox.setSingleStep(2)
        self.width_spinbox.valueChanged.connect(self.update_analysis)

        self.threshold_spinbox = QSpinBox()
        self.threshold_spinbox.setRange(5, 250)
        self.threshold_spinbox.setValue(60)
        self.threshold_spinbox.setSingleStep(5)
        self.threshold_spinbox.valueChanged.connect(self.update_analysis)

        self.prom_spinbox = QSpinBox()
        self.prom_spinbox.setRange(2, 20)
        self.prom_spinbox.setValue(4)
        self.prom_spinbox.setSingleStep(1)
        self.prom_spinbox.valueChanged.connect(self.update_analysis)

        self.empty_cutoff = QDoubleSpinBox()
        self.empty_cutoff.setDecimals(2)
        self.empty_cutoff.setRange(0.0, 2.0)
        self.empty_cutoff.setValue(0.25)
        self.empty_cutoff.setSingleStep(0.05)
        self.empty_cutoff.valueChanged.connect(self.update_analysis)

        analysis_form.addRow("Left Offset", self.offset_spinbox)
        analysis_form.addRow("Channel Width", self.width_spinbox)
        analysis_form.addRow("Threshold", self.threshold_spinbox)
        analysis_form.addRow("Prominence", self.prom_spinbox)
        analysis_form.addRow("Empty Cutoff", self.empty_cutoff)
        control_layout.addWidget(analysis_group)

        dataset_group = QtWidgets.QGroupBox("Dataset Capture")
        dataset_form = QtWidgets.QFormLayout(dataset_group)

        dataset_button_row = QtWidgets.QGridLayout()
        self.dataset_start_button = QPushButton("Start Dataset Session")
        self.dataset_start_button.clicked.connect(self.start_dataset_session)
        self.dataset_end_button = QPushButton("End Dataset Session")
        self.dataset_end_button.clicked.connect(self.end_dataset_session)
        self.dataset_scene_button = QPushButton("Start New Scene")
        self.dataset_scene_button.clicked.connect(self.start_dataset_scene)
        self.dataset_capture_single_button = QPushButton("Capture Single")
        self.dataset_capture_single_button.clicked.connect(self.capture_dataset_single)
        self.dataset_capture_sequence_button = QPushButton("Capture Sequence")
        self.dataset_capture_sequence_button.clicked.connect(self.capture_dataset_sequence)
        self.dataset_reject_last_button = QPushButton("Reject Last Capture")
        self.dataset_reject_last_button.clicked.connect(self.reject_last_dataset_capture)

        dataset_button_row.addWidget(self.dataset_start_button, 0, 0)
        dataset_button_row.addWidget(self.dataset_end_button, 0, 1)
        dataset_button_row.addWidget(self.dataset_scene_button, 1, 0)
        dataset_button_row.addWidget(self.dataset_capture_single_button, 1, 1)
        dataset_button_row.addWidget(self.dataset_capture_sequence_button, 2, 0)
        dataset_button_row.addWidget(self.dataset_reject_last_button, 2, 1)
        dataset_form.addRow(dataset_button_row)

        self.dataset_session_path_label = QLabel("-")
        self.dataset_session_path_label.setWordWrap(True)
        self.dataset_session_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.dataset_scene_label = QLabel("Scene: N/A")
        self.dataset_scene_label.setWordWrap(True)
        self.dataset_status_label = QLabel("Dataset idle.")
        self.dataset_status_label.setWordWrap(True)

        self.dataset_help_label = QLabel(
            "Workflow: start dataset session, start a scene, capture singles or sequences, then annotate offline."
        )
        self.dataset_help_label.setWordWrap(True)

        self.dataset_purpose_combo = QComboBox()
        self.dataset_purpose_combo.addItems(["nominal_static", "stress", "temporal"])

        self.dataset_scene_tags_edit = QLineEdit()
        self.dataset_scene_tags_edit.setPlaceholderText("comma-separated scene tags")
        self.dataset_frame_tags_edit = QLineEdit()
        self.dataset_frame_tags_edit.setPlaceholderText("comma-separated frame tags")

        self.dataset_sequence_length_spin = QSpinBox()
        self.dataset_sequence_length_spin.setRange(1, 1000)
        self.dataset_sequence_length_spin.setValue(10)

        self.dataset_sequence_interval_spin = QSpinBox()
        self.dataset_sequence_interval_spin.setRange(1, 60000)
        self.dataset_sequence_interval_spin.setValue(self._capture_interval_ms)
        self.dataset_sequence_interval_spin.setSuffix(" ms")

        self.dataset_notes_edit = QtWidgets.QPlainTextEdit()
        self.dataset_notes_edit.setPlaceholderText("Optional notes for the current dataset session/scene/frame.")
        self.dataset_notes_edit.setFixedHeight(80)

        dataset_form.addRow("Session Path", self.dataset_session_path_label)
        dataset_form.addRow("Current Scene", self.dataset_scene_label)
        dataset_form.addRow(self.dataset_help_label)
        dataset_form.addRow("Scene Purpose", self.dataset_purpose_combo)
        dataset_form.addRow("Scene Tags", self.dataset_scene_tags_edit)
        dataset_form.addRow("Frame Tags", self.dataset_frame_tags_edit)
        dataset_form.addRow("Sequence Length", self.dataset_sequence_length_spin)
        dataset_form.addRow("Sequence Interval", self.dataset_sequence_interval_spin)
        dataset_form.addRow("Notes", self.dataset_notes_edit)
        dataset_form.addRow("Status", self.dataset_status_label)
        control_layout.addWidget(dataset_group)
        control_layout.addStretch(1)

        control_scroll = QtWidgets.QScrollArea()
        control_scroll.setWidgetResizable(True)
        control_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        control_scroll.setMinimumWidth(380)
        control_scroll.setWidget(control_container)

        preview_container = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        preview_title = QLabel("Live Preview")
        preview_title.setAlignment(Qt.AlignCenter)
        preview_title.setStyleSheet("font-size: 16px; font-weight: 600;")

        self.image_label = QLabel("No image captured yet.")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(760, 560)
        self.image_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.image_label.setStyleSheet("background-color: black; border: 1px solid #444; padding: 8px;")
        self._preview_pixmap = None

        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(self.image_label, 1)

        root.addWidget(control_scroll, 0)
        root.addWidget(preview_container, 1)

        self.analysis_control_widgets = (
            self.offset_spinbox,
            self.width_spinbox,
            self.threshold_spinbox,
            self.prom_spinbox,
            self.empty_cutoff,
        )
        self.dataset_control_widgets = (
            self.dataset_end_button,
            self.dataset_scene_button,
            self.dataset_capture_single_button,
            self.dataset_capture_sequence_button,
            self.dataset_reject_last_button,
            self.dataset_purpose_combo,
            self.dataset_scene_tags_edit,
            self.dataset_frame_tags_edit,
            self.dataset_sequence_length_spin,
            self.dataset_sequence_interval_spin,
            self.dataset_notes_edit,
        )

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.capture_image)
        self.capturing = False

        self.refuel_camera_model.update_level_ui_signal.connect(self.update_refuel_ui)
        self.start_camera()
        self.update_analysis()
        self.update_refuel_ui()

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

        self.shortcut_manager.add_shortcut('1','Large refuel pressure decrease', lambda: self.controller.set_relative_refuel_pressure(-1,manual=True))
        self.shortcut_manager.add_shortcut('2','Small refuel pressure decrease', lambda: self.controller.set_relative_refuel_pressure(-0.1,manual=True))
        self.shortcut_manager.add_shortcut('3','Small refuel pressure increase', lambda: self.controller.set_relative_refuel_pressure(0.1,manual=True))
        self.shortcut_manager.add_shortcut('4','Large refuel pressure increase', lambda: self.controller.set_relative_refuel_pressure(1,manual=True))
        
        self.shortcut_manager.add_shortcut('6','Large print pressure decrease', lambda: self.controller.set_relative_print_pressure(-1,manual=True))
        self.shortcut_manager.add_shortcut('7','Small print pressure decrease', lambda: self.controller.set_relative_print_pressure(-0.1,manual=True))
        self.shortcut_manager.add_shortcut('8','Small print pressure increase', lambda: self.controller.set_relative_print_pressure(0.1,manual=True))
        self.shortcut_manager.add_shortcut('9','Large print pressure increase', lambda: self.controller.set_relative_print_pressure(1,manual=True))
  
        self.shortcut_manager.add_shortcut('z','Refuel only 20', lambda: self.controller.refuel_only(20))  
        self.shortcut_manager.add_shortcut('x','Refuel only 5', lambda: self.controller.refuel_only(5))  
        self.shortcut_manager.add_shortcut('c','Print only 5', lambda: self.controller.print_only(5))
        self.shortcut_manager.add_shortcut('v','Print only 20', lambda: self.controller.print_only(20))
        self.shortcut_manager.add_shortcut('t','Print 20 droplets', lambda: self.controller.print_droplets(20))

    @staticmethod
    def _format_value(value, suffix=""):
        if value is None:
            return "-"
        try:
            return f"{float(value):.1f}{suffix}"
        except Exception:
            return f"{value}{suffix}"

    @staticmethod
    def _parse_tag_text(text):
        parts = []
        seen = set()
        for raw in str(text or "").split(","):
            value = raw.strip()
            if not value:
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            parts.append(value)
        return parts

    def _dataset_camera_profile_name(self):
        machine = getattr(self.controller, "machine", None)
        refuel_camera = getattr(machine, "refuel_camera", None) if machine is not None else None
        if refuel_camera is None:
            return "refuel_camera_default"
        return str(refuel_camera.__class__.__name__ or "refuel_camera_default")

    def _build_dataset_machine_context(self, base_context=None):
        payload = dict(base_context or {})
        machine_model = getattr(self.model, "machine_model", None)
        if machine_model is None:
            return payload
        payload.setdefault("regulating_print_pressure", bool(getattr(machine_model, "regulating_print_pressure", False)))
        payload.setdefault("regulating_refuel_pressure", bool(getattr(machine_model, "regulating_refuel_pressure", False)))
        for key, getter_name in (
            ("print_pressure", "get_current_print_pressure"),
            ("refuel_pressure", "get_current_refuel_pressure"),
            ("print_pulse_width", "get_print_pulse_width"),
            ("refuel_pulse_width", "get_refuel_pulse_width"),
            ("location", "get_current_location"),
        ):
            getter = getattr(machine_model, getter_name, None)
            if callable(getter):
                try:
                    payload[key] = getter()
                except Exception:
                    pass
        return payload

    def _build_dataset_camera_context(self):
        return {
            "camera_profile_name": self._dataset_camera_profile_name(),
            "capture_interval_ms": int(self._capture_interval_ms),
            "analysis_parameters": {
                "left_offset": int(self.offset_spinbox.value()),
                "channel_width": int(self.width_spinbox.value()),
                "threshold": int(self.threshold_spinbox.value()),
                "prominence": int(self.prom_spinbox.value()),
                "empty_cutoff": float(self.empty_cutoff.value()),
            },
        }

    def _capture_refuel_frame_with_context(self):
        capture_with_context = getattr(self.controller, "capture_refuel_image_with_context", None)
        if callable(capture_with_context):
            return capture_with_context(analyze=True)
        frame = self.controller.capture_refuel_image()
        context_getter = getattr(self.controller, "get_refuel_capture_context", None)
        context = context_getter() if callable(context_getter) else {}
        return frame, context

    def _set_analysis_controls_enabled(self, enabled):
        for widget in self.analysis_control_widgets:
            widget.setEnabled(enabled)

    def _set_dataset_controls_enabled(self, enabled):
        for widget in self.dataset_control_widgets:
            widget.setEnabled(enabled)

    def _sync_dataset_labels(self):
        run_dir = self.refuel_camera_model.get_dataset_run_dir()
        self.dataset_session_path_label.setText(str(run_dir or "-"))
        scene = self.refuel_camera_model.get_dataset_current_scene()
        if scene:
            self.dataset_scene_label.setText(
                f"Scene: {scene.get('scene_id', 'N/A')} ({scene.get('purpose', 'unknown')})"
            )
        else:
            self.dataset_scene_label.setText("Scene: N/A")

    def _sync_session_controls(self):
        session_active = self.refuel_camera_model.is_session_active()
        burst_active = self.refuel_camera_model.is_burst_in_progress()
        dataset_active = self.refuel_camera_model.is_dataset_session_active()
        dataset_scene_active = self.refuel_camera_model.get_dataset_current_scene() is not None
        dataset_sequence_active = self._dataset_sequence_state is not None
        analysis_locked = session_active or burst_active

        self.capture_button.setEnabled(self._camera_ready)
        self.save_button.setEnabled(self.refuel_camera_model.get_raw_capture_image() is not None)
        self._set_analysis_controls_enabled(self._camera_ready and not analysis_locked)
        self.dataset_start_button.setEnabled(self._camera_ready and not dataset_active and not dataset_sequence_active)
        self.dataset_end_button.setEnabled(dataset_active and not dataset_sequence_active)
        self._set_dataset_controls_enabled(dataset_active and not dataset_sequence_active)
        if not dataset_scene_active:
            self.dataset_capture_single_button.setEnabled(False)
            self.dataset_capture_sequence_button.setEnabled(False)
        if not dataset_active:
            self.dataset_scene_button.setEnabled(False)
            self.dataset_capture_single_button.setEnabled(False)
            self.dataset_capture_sequence_button.setEnabled(False)
            self.dataset_reject_last_button.setEnabled(False)
        if not self._camera_ready:
            self.dataset_capture_single_button.setEnabled(False)
            self.dataset_capture_sequence_button.setEnabled(False)
        self.dataset_reject_last_button.setEnabled(
            dataset_active
            and not dataset_sequence_active
            and bool(self.refuel_camera_model.get_dataset_frame_records())
        )
        self._sync_dataset_labels()

    def start_dataset_session(self):
        if not self._camera_ready:
            QtWidgets.QMessageBox.warning(self, "Dataset Capture", "Refuel camera is not ready.")
            return
        run_dir = self.refuel_camera_model.start_dataset_session(
            operator_id=os.getenv("USERNAME") or "unknown",
            notes=self.dataset_notes_edit.toPlainText().strip(),
            camera_profile_name=self._dataset_camera_profile_name(),
            default_sequence_length=self.dataset_sequence_length_spin.value(),
            default_sequence_interval_ms=self.dataset_sequence_interval_spin.value(),
        )
        if not run_dir:
            QtWidgets.QMessageBox.warning(self, "Dataset Capture", "Unable to start a refuel dataset session.")
            return
        self.dataset_status_label.setText("Dataset session started. Create a scene before capturing frames.")
        self._sync_session_controls()

    def end_dataset_session(self):
        if not self.refuel_camera_model.is_dataset_session_active():
            return
        self._dataset_sequence_state = None
        run_dir = self.refuel_camera_model.end_dataset_session()
        self.dataset_status_label.setText(f"Dataset session ended. Last run: {run_dir or '-'}")
        self._sync_session_controls()

    def start_dataset_scene(self):
        if not self.refuel_camera_model.is_dataset_session_active():
            QtWidgets.QMessageBox.warning(self, "Dataset Capture", "Start a dataset session before creating a scene.")
            return
        machine_context = self._build_dataset_machine_context(
            getattr(self.controller, "get_refuel_capture_context", lambda: {})()
        )
        scene = self.refuel_camera_model.start_dataset_scene(
            purpose=self.dataset_purpose_combo.currentText(),
            scene_tags=self._parse_tag_text(self.dataset_scene_tags_edit.text()),
            notes=self.dataset_notes_edit.toPlainText().strip(),
            geometry_expected_static=True,
            machine_context=machine_context,
            camera_context=self._build_dataset_camera_context(),
        )
        self.dataset_status_label.setText(f"Active scene: {scene.get('scene_id', 'N/A')}")
        self._sync_session_controls()

    def _capture_dataset_frame(self, *, frame_kind, sequence_id="", sequence_index=1, sequence_length=1):
        if not self.refuel_camera_model.is_dataset_session_active():
            QtWidgets.QMessageBox.warning(self, "Dataset Capture", "Start a dataset session before capturing frames.")
            return False
        if self.refuel_camera_model.get_dataset_current_scene() is None:
            QtWidgets.QMessageBox.warning(self, "Dataset Capture", "Start a scene before capturing frames.")
            return False
        if not self._camera_ready:
            QtWidgets.QMessageBox.warning(self, "Dataset Capture", "Refuel camera is not ready.")
            return False

        frame, context = self._capture_refuel_frame_with_context()
        if frame is None:
            QtWidgets.QMessageBox.warning(self, "Dataset Capture", "Camera did not return a frame.")
            self.dataset_status_label.setText("Dataset capture failed: no frame returned.")
            return False

        record = self.refuel_camera_model.capture_dataset_frame(
            frame,
            frame_kind=frame_kind,
            sequence_id=sequence_id,
            sequence_index=sequence_index,
            sequence_length=sequence_length,
            frame_tags=self._parse_tag_text(self.dataset_frame_tags_edit.text()),
            notes=self.dataset_notes_edit.toPlainText().strip(),
            machine_context=self._build_dataset_machine_context(context),
            camera_context=self._build_dataset_camera_context(),
        )
        if record is None:
            QtWidgets.QMessageBox.warning(self, "Dataset Capture", "Failed to persist the dataset frame.")
            self.dataset_status_label.setText("Dataset capture failed while writing the frame.")
            return False
        self.dataset_status_label.setText(
            f"Captured {record.get('frame_id', '')} ({record.get('frame_kind', 'single')})."
        )
        self._sync_session_controls()
        return True

    def capture_dataset_single(self):
        self._capture_dataset_frame(frame_kind="single", sequence_index=1, sequence_length=1)

    def capture_dataset_sequence(self):
        if self._dataset_sequence_state is not None:
            return
        sequence_length = int(self.dataset_sequence_length_spin.value())
        if sequence_length <= 0:
            QtWidgets.QMessageBox.warning(self, "Dataset Capture", "Sequence length must be at least 1.")
            return
        sequence_id = self.refuel_camera_model.next_dataset_sequence_id()
        self._dataset_sequence_state = {
            "sequence_id": sequence_id,
            "sequence_length": sequence_length,
            "next_index": 1,
            "interval_ms": int(self.dataset_sequence_interval_spin.value()),
        }
        self.dataset_status_label.setText(f"Capturing sequence {sequence_id}...")
        self._sync_session_controls()
        QtCore.QTimer.singleShot(0, self._capture_next_dataset_sequence_frame)

    def _capture_next_dataset_sequence_frame(self):
        state = self._dataset_sequence_state
        if state is None:
            return

        ok = self._capture_dataset_frame(
            frame_kind="sequence",
            sequence_id=state["sequence_id"],
            sequence_index=state["next_index"],
            sequence_length=state["sequence_length"],
        )
        if not ok:
            self._dataset_sequence_state = None
            self.dataset_status_label.setText("Sequence capture stopped due to capture failure.")
            self._sync_session_controls()
            return

        if state["next_index"] >= state["sequence_length"]:
            self.dataset_status_label.setText(f"Sequence {state['sequence_id']} complete.")
            self._dataset_sequence_state = None
            self._sync_session_controls()
            return

        state["next_index"] += 1
        QtCore.QTimer.singleShot(int(state["interval_ms"]), self._capture_next_dataset_sequence_frame)

    def reject_last_dataset_capture(self):
        if not self.refuel_camera_model.get_dataset_frame_records():
            QtWidgets.QMessageBox.information(self, "Nothing to reject", "No dataset capture is available to reject.")
            return
        reason, ok = QtWidgets.QInputDialog.getText(
            self,
            "Reject Last Dataset Capture",
            "Reason (optional):",
            QtWidgets.QLineEdit.Normal,
            "",
        )
        if not ok:
            return
        evt = self.refuel_camera_model.reject_last_dataset_capture(reason=reason)
        if evt is None:
            QtWidgets.QMessageBox.information(self, "Nothing to reject", "No dataset capture is available to reject.")
            return
        self.dataset_status_label.setText("Last dataset capture marked as rejected.")
        self._sync_session_controls()

    def toggle_capture(self):
        """Starts or stops capturing images based on the button toggle."""
        if not self._camera_ready:
            return
        if self.capturing:
            self.timer.stop()
            self.capture_button.setText("Start Capturing Images")
            try:
                self.refuel_camera_model.set_refuel_diagnostic_capture_active(False)
            except Exception:
                pass
        else:
            self.timer.start(self._capture_interval_ms)
            self.capture_button.setText("Stop Capturing Images")
            try:
                self.refuel_camera_model.set_refuel_diagnostic_capture_active(True)
            except Exception:
                pass
        self.capturing = not self.capturing

    def _set_capture_idle(self):
        self.timer.stop()
        self.capturing = False
        self.capture_button.setText("Start Capturing Images")
        try:
            self.refuel_camera_model.set_refuel_diagnostic_capture_active(False)
        except Exception:
            pass

    def _handle_camera_failure(self, message, *, popup=False):
        self._camera_ready = False
        self._set_capture_idle()
        self._dataset_sequence_state = None
        self.capture_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self._preview_pixmap = None
        self.image_label.clear()
        self.image_label.setText(message)
        self.level_label.setText("Current Level: N/A")
        self.dataset_status_label.setText(message)
        if popup and not self._camera_failure_shown:
            self._camera_failure_shown = True
            QtWidgets.QMessageBox.warning(self, "Refuel Camera Unavailable", message)
        self._sync_session_controls()

    def start_camera(self):
        try:
            self.controller.start_refuel_camera()
            machine = getattr(self.controller, "machine", None)
            refuel_camera = getattr(machine, "refuel_camera", None) if machine is not None else None
            if isinstance(refuel_camera, NullCamera):
                raise RuntimeError("Refuel camera is unavailable on this system.")
        except Exception as exc:
            self._handle_camera_failure(str(exc), popup=True)
            return False

        self._camera_ready = True
        self.capture_button.setEnabled(True)
        self._sync_session_controls()
        return True

    def capture_image(self):
        if not self._camera_ready:
            return
        try:
            frame = self.controller.capture_refuel_image()
        except Exception as exc:
            self._handle_camera_failure(f"Refuel capture failed: {exc}", popup=True)
            return
        if frame is None:
            self._handle_camera_failure("Camera did not return a frame.", popup=True)

    def stop_camera(self):
        try:
            self.controller.stop_refuel_camera()
        except Exception as exc:
            print(f"[RefuelCamera] stop_camera failed: {exc}")

    def save_frame(self):
        """Save the latest raw frame to the snapshot directory."""
        raw_image = self.refuel_camera_model.get_raw_capture_image()
        if raw_image is None:
            QtWidgets.QMessageBox.information(
                self,
                "No Snapshot Available",
                "Capture an image before saving a snapshot.",
            )
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._save_dir.mkdir(parents=True, exist_ok=True)
        filename = self._save_dir / f"refuel_frame_{timestamp}.png"
        ok = cv2.imwrite(str(filename), raw_image)
        if not ok:
            QtWidgets.QMessageBox.warning(
                self,
                "Snapshot Failed",
                f"Unable to write snapshot to:\n{filename}",
            )
            return

        self.refuel_camera_model.record_manual_frame()
        self.last_snapshot_label.setText(str(filename.resolve()))
        self._sync_session_controls()

    def numpy_to_qimage(self, image):
        """Converts a numpy array (captured image) to a QImage."""
        height, width, channels = image.shape
        bytes_per_line = channels * width
        qimage = QImage(image.data, width, height, bytes_per_line, QImage.Format_RGB888)
        return qimage.rgbSwapped()

    def numpy_to_qimage_grayscale(self, image):
        """Converts a grayscale numpy array to a QImage."""
        height, width = image.shape
        bytes_per_line = width
        qimage = QImage(image.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
        return qimage

    def _update_preview_pixmap(self):
        if self._preview_pixmap is None:
            return
        scaled = self._preview_pixmap.scaled(
            self.image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview_pixmap()

    @staticmethod
    def _prepare_refuel_preview_image(raw_image, annotated_image):
        if raw_image is not None:
            return cv2.rotate(raw_image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return annotated_image

    def update_refuel_ui(self):
        raw_image = self.refuel_camera_model.get_raw_capture_image()
        annotated_image = self.refuel_camera_model.get_annotated_image()
        preview_image = self._prepare_refuel_preview_image(raw_image, annotated_image)

        if preview_image is not None:
            qimage = self.numpy_to_qimage(preview_image)
            self._preview_pixmap = QPixmap.fromImage(qimage)
            self._update_preview_pixmap()

        level = self.refuel_camera_model.get_current_level()
        if level is not None:
            self.level_label.setText(f"Current Level: {level:.1f}")
        else:
            self.level_label.setText("Current Level: N/A")

        self._sync_session_controls()

    def update_analysis(self):
        """Update the analysis parameters based on the spinbox values."""
        offset = self.offset_spinbox.value()
        width = self.width_spinbox.value()
        threshold = self.threshold_spinbox.value()
        prom = self.prom_spinbox.value()
        empty_cutoff = self.empty_cutoff.value()
        self.refuel_camera_model.update_analysis_parameters(offset, width, threshold, prom, empty_cutoff)

    def closeEvent(self, event):
        """Handle the closing of the dialog."""
        self._dataset_sequence_state = None
        try:
            self.refuel_camera_model.close_session()
        except Exception as exc:
            print(f"[RefuelCamera] close_session failed: {exc}")
        try:
            self.refuel_camera_model.end_dataset_session()
        except Exception as exc:
            print(f"[RefuelCamera] end_dataset_session failed: {exc}")
        self._set_capture_idle()
        self.stop_camera()
        try:
            self.controller.disable_print_profile()
        except Exception as exc:
            print(f"[RefuelCamera] disable_print_profile failed: {exc}")
        event.accept()
        super().closeEvent(event)


