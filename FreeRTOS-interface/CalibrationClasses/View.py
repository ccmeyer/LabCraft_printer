from PySide6 import QtCore, QtWidgets, QtGui, QtCharts
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QGridLayout, QGroupBox, QPushButton, QComboBox, QSpinBox, QSizePolicy,
    QSpacerItem, QFileDialog, QInputDialog, QMessageBox, QAbstractItemView, QDialog,QLineEdit,QDoubleSpinBox,QGraphicsOpacityEffect
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
from datetime import datetime
import cv2
from utilities import ShortcutManager

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

        
class DropletImagingDialog(QtWidgets.QDialog):
    def __init__(self, main_window, model, controller):
        super().__init__()
        print('\n---Created new droplet imaging dialog---\n')
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.droplet_camera_model = model.droplet_camera_model
        self.controller = controller

        # Hardware bounds for pressures (used globally)
        try:
            self.hw_lo, self.hw_hi = self.model.machine_model.get_print_pressure_bounds()
        except Exception:
            self.hw_lo, self.hw_hi = 0.10, 5.00

        self.shortcut_manager = ShortcutManager(self)
        self.setup_shortcuts()

        self.flash_active = False
        self.saving_active = False
        self.analysis_active = False
        self.start_droplet_camera()
        self.controller.start_read_camera()

        # Timer for periodic image capture
        self.camera_timer = QTimer(self)
        self.camera_timer.timeout.connect(self.capture_image)
        self.capturing = False

        self._bridge_preview_payload = None

        self.setWindowTitle("Droplet Imaging")
        self.resize(1200, 1000)

        # =========================
        # Main two-column layout
        # =========================
        self.layout = QtWidgets.QHBoxLayout(self)

        # ---------- LEFT PANEL (fixed width): two groups ----------
        left_panel = QtWidgets.QWidget()
        left_panel_v = QtWidgets.QVBoxLayout(left_panel)
        left_panel_v.setContentsMargins(6, 6, 6, 6)
        left_panel_v.setSpacing(8)

        # --- Group 1: Manual Controls ---
        manual_group = QtWidgets.QGroupBox("Manual Controls")
        manual_grid = QtWidgets.QGridLayout(manual_group)
        manual_grid.setHorizontalSpacing(8)
        manual_grid.setVerticalSpacing(6)
        row = 0

        # Counters
        self.flash_count_label = QtWidgets.QLabel("Flashes: 0")
        self.trigger_count_label = QtWidgets.QLabel("Triggers: 0")
        manual_grid.addWidget(self.flash_count_label,   row, 0, 1, 2); row += 1
        manual_grid.addWidget(self.trigger_count_label, row, 0, 1, 2); row += 1

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

        # Trigger flash
        self.flash_button = QtWidgets.QPushButton("Trigger Flash")
        self.flash_button.clicked.connect(self.toggle_flash)
        manual_grid.addWidget(self.flash_button, row, 0, 1, 2); row += 1

        self.benchmark_profile_button = QtWidgets.QPushButton("Apply Benchmark Capture Profile")
        self.benchmark_profile_button.clicked.connect(self.apply_benchmark_capture_profile)
        manual_grid.addWidget(self.benchmark_profile_button, row, 0, 1, 2); row += 1

        # --- Group 2: Calibration (with Starting Pressure) ---
        calib_group = QtWidgets.QGroupBox("Calibration")
        calib_grid = QtWidgets.QGridLayout(calib_group)
        calib_grid.setHorizontalSpacing(8)
        calib_grid.setVerticalSpacing(6)
        crow = 0

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

        # Calibration buttons

        self.prime_head_button = QtWidgets.QPushButton("Prime Printer Head")
        self.prime_head_button.clicked.connect(self.toggle_start_head_prime_calibration)
        calib_grid.addWidget(self.prime_head_button, crow, 0, 1, 2); crow += 1

        self.calibrate_nozzle_button = QtWidgets.QPushButton("Calibrate Nozzle Position")
        self.calibrate_nozzle_button.clicked.connect(self.toggle_start_nozzle_calibration)
        calib_grid.addWidget(self.calibrate_nozzle_button, crow, 0, 1, 2); crow += 1

        self.calibrate_focus_button = QtWidgets.QPushButton("Calibrate Nozzle Focus")
        self.calibrate_focus_button.clicked.connect(self.toggle_start_focus_calibration)
        calib_grid.addWidget(self.calibrate_focus_button, crow, 0, 1, 2); crow += 1

        self.calibrate_emergence_button = QtWidgets.QPushButton("Calibrate Droplet Emergence")
        self.calibrate_emergence_button.clicked.connect(self.toggle_start_emergence_calibration)
        calib_grid.addWidget(self.calibrate_emergence_button, crow, 0, 1, 2); crow += 1

        # self.calibrate_pressure_button = QtWidgets.QPushButton("Calibrate Pressure")
        # self.calibrate_pressure_button.clicked.connect(self.toggle_start_pressure_calibration)
        # calib_grid.addWidget(self.calibrate_pressure_button, crow, 0, 1, 2); crow += 1

        self.calibrate_pressure_scan_button = QtWidgets.QPushButton("Scan Pressures")
        self.calibrate_pressure_scan_button.clicked.connect(self.toggle_start_pressure_scan_calibration)
        calib_grid.addWidget(self.calibrate_pressure_scan_button, crow, 0, 1, 2); crow += 1

        # self.calibrate_trajectory_button = QtWidgets.QPushButton("Calibrate Droplet Trajectory")
        # self.calibrate_trajectory_button.clicked.connect(self.toggle_start_trajectory_calibration)
        # calib_grid.addWidget(self.calibrate_trajectory_button, crow, 0, 1, 2); crow += 1

        self.scan_trajectory_button = QtWidgets.QPushButton("Scan Trajectory Pressures")
        self.scan_trajectory_button.clicked.connect(self.toggle_start_pressure_trajectory_calibration)
        calib_grid.addWidget(self.scan_trajectory_button, crow, 0, 1, 2); crow += 1

        # self.calibrate_droplet_search_button = QtWidgets.QPushButton("Search for Droplets")
        # self.calibrate_droplet_search_button.clicked.connect(self.toggle_start_droplet_search_calibration)
        # calib_grid.addWidget(self.calibrate_droplet_search_button, crow, 0, 1, 2); crow += 1

        self.calibrate_pressure_sweep_button = QtWidgets.QPushButton("Pressure Sweep Characterization")
        self.calibrate_pressure_sweep_button.clicked.connect(self.toggle_start_pressure_sweep_calibration)
        calib_grid.addWidget(self.calibrate_pressure_sweep_button, crow, 0, 1, 2); crow += 1

        self.calibrate_characterization_button = QtWidgets.QPushButton("Manually Characterize Droplets")
        self.calibrate_characterization_button.clicked.connect(self.toggle_start_characterization_calibration)
        calib_grid.addWidget(self.calibrate_characterization_button, crow, 0, 1, 2); crow += 1

        self.calibrate_timecourse_button = QtWidgets.QPushButton("Droplet Timecourse Imaging")
        self.calibrate_timecourse_button.clicked.connect(self.toggle_start_timecourse_calibration)
        calib_grid.addWidget(self.calibrate_timecourse_button, crow, 0, 1, 2); crow += 1

        self.calibrate_all_button = QtWidgets.QPushButton("Calibrate All")
        self.calibrate_all_button.clicked.connect(self.toggle_start_all_calibration)
        calib_grid.addWidget(self.calibrate_all_button, crow, 0, 1, 2); crow += 1

        # ---- Pulse-Width Sweep controls ----
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

        calib_grid.addWidget(self.pw_start_label, crow, 0)
        calib_grid.addWidget(self.pw_start_spin,  crow, 1); crow += 1
        calib_grid.addWidget(self.pw_end_label,   crow, 0)
        calib_grid.addWidget(self.pw_end_spin,    crow, 1); crow += 1
        calib_grid.addWidget(self.pw_step_label,  crow, 0)
        calib_grid.addWidget(self.pw_step_spin,   crow, 1); crow += 1

        self.calibrate_all_pw_button = QtWidgets.QPushButton("Calibrate All (PW Range)")
        self.calibrate_all_pw_button.clicked.connect(self.toggle_start_pw_sweep)
        calib_grid.addWidget(self.calibrate_all_pw_button, crow, 0, 1, 2); crow += 1

        # Status
        self.stageLabel = QtWidgets.QLabel("Status: Idle")
        calib_grid.addWidget(self.stageLabel, crow, 0, 1, 2); crow += 1

        # Add groups to left panel
        left_panel_v.addWidget(manual_group)
        left_panel_v.addWidget(calib_group)

        # --- Group 3: Characterization Summary ---
        summary_group = QtWidgets.QGroupBox("Characterization Summary")
        summary_v = QtWidgets.QVBoxLayout(summary_group)

        self.summary_table = QtWidgets.QTableWidget()
        self.summary_table = QtWidgets.QTableWidget()
        self.summary_table.setColumnCount(6)
        self.summary_table.setHorizontalHeaderLabels(
            ["Run #", "PW (µs)", "Pressure (psi)", "Mean (nL)", "CV (%)", "Valid"]
        )
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.summary_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.summary_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.summary_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.summary_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        
        # Allow selecting entire rows (single selection)
        self.summary_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.summary_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

        self.summary_table.setMinimumHeight(180)
        self.summary_table.setMaximumHeight(300)
        self.summary_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.summary_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.summary_table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.summary_table.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)

        summary_v.addWidget(self.summary_table)

        # Load Selected button
        self.load_selected_button = QtWidgets.QPushButton("Load selected")
        self.load_selected_button.setEnabled(False)
        self.load_selected_button.setToolTip("Select a row above, then click to apply its PW & pressure.")
        self.load_selected_button.clicked.connect(self.load_selected_summary_row)
        summary_v.addWidget(self.load_selected_button)

        left_panel_v.addWidget(summary_group)

        left_panel_v.addStretch(1)

        # Keep left panel a stable width so buttons/labels don't resize
        left_panel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        # Use size hint to set a fixed width after contents are laid out
        left_panel.adjustSize()
        left_panel.setFixedWidth(max(500, left_panel.sizeHint().width()))

        # Add left panel to main layout
        self.layout.addWidget(left_panel, 0)
        self.layout.setStretchFactor(left_panel, 0)

        # ---------- RIGHT PANEL (image + analysis/logs): expands ----------
        self.analysis_layout = QtWidgets.QVBoxLayout()

        self.image_label = QLabel("No image captured yet.")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setFixedHeight(640)
        self.image_label.setFixedWidth(480)
        self.analysis_layout.addWidget(self.image_label)

        # Motor diffs table (unchanged)
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

        self.analysis_layout.addWidget(self.diff_widget, alignment=Qt.AlignTop | Qt.AlignLeft)

        # --- Group 3: Design ↔ Calibration Bridge (preview only in Step 1) ---
        bridge_group = QtWidgets.QGroupBox("Design ↔ Calibration Bridge")
        bridge_v = QtWidgets.QVBoxLayout(bridge_group)

        # Top labels (design targets & droplet nL)
        self.bridge_reagent_label = QtWidgets.QLabel("Reagent: —")
        self.bridge_design_dv_label = QtWidgets.QLabel("Design droplet volume (nL): —")
        self.bridge_design_targets_label = QtWidgets.QLabel("Design targets: —")
        self.bridge_design_stock_label = QtWidgets.QLabel("Stock concentration(s): —")

        # Preview controls
        preview_h = QtWidgets.QHBoxLayout()
        self.bridge_preview_btn = QtWidgets.QPushButton("Preview from last characterization")
        self.bridge_preview_btn.clicked.connect(self._bridge_preview_from_last_char)
        preview_h.addWidget(self.bridge_preview_btn)

        # Table for preview results
        self.bridge_table = QtWidgets.QTableWidget(0, 7, bridge_group)
        self.bridge_table.setHorizontalHeaderLabels([
            "Target (final)", "Achievable (final)", "Error", "Drops", "Δ/drop", "Printed nL (new)", "Δ printed nL"
        ])
        self.bridge_table.horizontalHeader().setStretchLastSection(True)
        self.bridge_table.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)

        # Apply button (disabled in Step 1)
        self.bridge_apply_btn = QtWidgets.QPushButton("Apply new droplet volume to design")
        self.bridge_apply_btn.setEnabled(False)  # Step 1: preview only
        self.bridge_apply_btn.clicked.connect(self._apply_previewed_droplet_volume)
        self.bridge_apply_btn.setToolTip("Update droplet counts & concentration key using this droplet size")

        # assemble
        bridge_v.addWidget(self.bridge_reagent_label)
        bridge_v.addWidget(self.bridge_design_dv_label)
        bridge_v.addWidget(self.bridge_design_targets_label)
        bridge_v.addWidget(self.bridge_design_stock_label)
        bridge_v.addLayout(preview_h)
        bridge_v.addWidget(self.bridge_table)
        bridge_v.addWidget(self.bridge_apply_btn)

        self.analysis_layout.addWidget(bridge_group)


        self.log_label = QtWidgets.QLabel("Calibration Log")
        self.log_label.setStyleSheet("font-weight: bold;")
        self.analysis_layout.addWidget(self.log_label)

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
        self.stage_table.setMinimumHeight(100)
        self.analysis_layout.addWidget(self.stage_table)

        # Add RIGHT to main layout; give it stretch to expand
        right_container = QtWidgets.QWidget()
        right_container.setLayout(self.analysis_layout)
        right_container.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.layout.addWidget(right_container, 1)
        self.layout.setStretchFactor(right_container, 1)

        # ---------------- Connections ----------------
        self.model.droplet_camera_model.droplet_image_updated.connect(self.update_image)
        self.model.droplet_camera_model.flash_signal.connect(self.update_flash_info)
        self.model.calibration_manager.analyzedImageUpdated.connect(self.display_analyzed_image)

        self.flash_duration_spinbox.valueChanged.connect(self.set_flash_duration)
        self.flash_delay_spinbox.valueChanged.connect(self.set_flash_delay)
        self.num_droplets_spinbox.valueChanged.connect(self.set_imaging_droplets)
        self.print_pulse_width_spinbox.valueChanged.connect(self.handle_print_pulse_width_change)
        self.exposure_time_spinbox.valueChanged.connect(self.set_exposure_time)

        self.start_pressure_spin.valueChanged.connect(self.set_start_pressure)
        self.num_pressure_tests_spin.valueChanged.connect(self.set_num_pressure_tests)
        self.summary_table.itemSelectionChanged.connect(self._update_load_button_state)
        # Double-click on any cell loads that row immediately
        self.summary_table.itemDoubleClicked.connect(self._handle_summary_double_click)
        self.summary_table.itemSelectionChanged.connect(self._on_summary_selection_changed)

        self.model.calibration_manager.calibrationStageChanged.connect(self.update_stage_and_log)
        self.model.calibration_manager.calibrationCompleted.connect(self.on_calibration_completed)
        self.model.calibration_manager.calibrationQueueCompleted.connect(self.on_calibration_queue_completed)
        self.model.calibration_manager.calibrationError.connect(self.on_calibration_error)
        self.model.calibration_manager.position_diff_dict_signal.connect(self.update_position_diffs)
        self.model.calibration_manager.characterizationSummaryUpdated.connect(self.populate_summary_table)

        self.model.calibration_manager.readinessChanged.connect(self.on_readiness_changed)
        self.model.calibration_manager._emit_readiness()

        self.set_exposure_time(self.droplet_camera_model.exposure_time)
        self.set_flash_delay(self.droplet_camera_model.flash_delay)
        self.set_flash_duration(self.droplet_camera_model.flash_duration)
        self.set_imaging_droplets(self.droplet_camera_model.num_droplets)
        self.set_start_pressure(self.start_pressure_spin.value())
        self.set_num_pressure_tests(self.num_pressure_tests_spin.value())
        self.populate_summary_table()

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
        
        self.shortcut_manager.add_shortcut('Space', "Toggle flash", self.toggle_flash)

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


    def move_fraction_of_frame(self, x_fraction, y_fraction):
        """
        Moves the camera frame by a fraction of the frame size.
        """
        dX, dY, dZ = self.model.droplet_camera_model.compute_move_by_fraction(x_fraction, y_fraction)
        self.controller.set_relative_coordinates(dX, dY, dZ, manual=False)
    
    def numpy_to_qimage(self,image):
        """
        Converts a numpy array (captured image) to a QImage.
        """
        if image is None:
            return QImage()  # return a null QImage if no frame

        # shape should be (height, width, 3)
        height, width, channels = image.shape
        if channels != 3:
            print("Warning: expected 3 channels (RGB), but got", channels)
            return QImage()
        
        height, width, channels = image.shape
        bytes_per_line = channels * width
        qimage = QImage(
            image,                 # the actual data (byte array)
            width,
            height,
            bytes_per_line,
            QImage.Format_RGB888  # We assume the data is truly RGB
        )        
        return qimage

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
        self.set_exposure_time(20000)
        self.num_droplets_spinbox.setValue(0)

    def apply_benchmark_capture_profile(self):
        """
        Apply a fixed, fast capture profile for throughput benchmarking.
        """
        self.controller.set_droplet_capture_profile("throughput")
        self.controller.set_command_dispatch_interval(20)
        self.flash_delay_spinbox.setValue(5000)
        self.flash_duration_spinbox.setValue(1000)
        self.exposure_time_spinbox.setValue(20000)
        self.num_droplets_spinbox.setValue(1)

    def toggle_flash(self):
        """
        Triggers a flash for the droplet imaging.
        """
        self.controller.capture_droplet_image()

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

    def update_flash_info(self):
        """
        Updates the flash info.
        """
        count = self.model.droplet_camera_model.get_num_flashes()
        self.flash_count_label.setText(f"Flashes: {count}")
        trigger_count = self.model.droplet_camera_model.get_trigger_counter()
        self.trigger_count_label.setText(f"Triggers: {trigger_count}")
        self.flash_duration_spinbox.blockSignals(True)
        self.flash_duration_spinbox.setValue(self.model.droplet_camera_model.get_flash_duration())
        self.flash_duration_spinbox.blockSignals(False)

        self.flash_delay_spinbox.blockSignals(True)
        self.flash_delay_spinbox.setValue(self.model.droplet_camera_model.get_flash_delay())
        self.flash_delay_spinbox.blockSignals(False)

        self.exposure_time_spinbox.blockSignals(True)
        self.exposure_time_spinbox.setValue(self.model.droplet_camera_model.get_exposure_time())
        self.exposure_time_spinbox.blockSignals(False)

    def start_droplet_camera(self):
        print('Starting droplet imaging')
        self.controller.start_droplet_camera()

    def capture_image(self):
        self.controller.capture_droplet_image(throughput_mode=bool(self.capturing))

    def stop_droplet_camera(self):
        self.controller.stop_droplet_camera()

    def on_calibration_completed(self):
        """
        Called when the calibration process is completed.
        """
        self.update_stage_and_log("Calibration Completed", "green")
        self.reset_calibration_buttons()

    def on_calibration_queue_completed(self):
        """
        Called when the calibration queue is completed.
        """
        self.update_stage_and_log("Calibration Queue Completed","green")
        self.reset_calibration_buttons()
        self.calibrate_all_button.setText("Calibrate All")
        self.calibrate_all_pw_button.setText("Calibrate All (PW Range)")

    def on_calibration_error(self, error_message):
        """
        Called when the calibration process encounters an error.
        """
        self.update_stage_and_log("Calibration Error", "red")
        self.reset_calibration_buttons()
        self.calibrate_all_button.setText("Calibrate All")
        self.calibrate_all_pw_button.setText("Calibrate All (PW Range)")
        QtWidgets.QMessageBox.warning(self, "Calibration Error", error_message)

    def reset_calibration_buttons(self):
        """
        Resets the calibration buttons to their default state.
        """
        self.prime_head_button.setText("Prime Printer Head")
        self.calibrate_nozzle_button.setText("Calibrate Nozzle Position")
        self.calibrate_focus_button.setText("Calibrate Nozzle Focus")
        self.calibrate_emergence_button.setText("Calibrate Droplet Emergence")
        # self.calibrate_pressure_button.setText("Calibrate Pressure")
        # self.calibrate_droplet_search_button.setText("Search for Droplets")
        self.calibrate_pressure_scan_button.setText("Scan Pressures")
        self.scan_trajectory_button.setText("Scan Trajectory Pressures")
        self.calibrate_timecourse_button.setText("Droplet Timecourse Imaging")
        self.calibrate_characterization_button.setText("Manually Characterize Droplets")
        self.calibrate_pressure_sweep_button.setText("Pressure Sweep Characterization")

    def toggle_start_head_prime_calibration(self):
        """
        Toggles whether the printer head priming should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self.prime_head_button.setText("Prime Printer Head")
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self.prime_head_button.setText("Stop Calibration")
            self.controller.start_head_prime_calibration()

    def toggle_start_nozzle_calibration(self):
        """
        Toggles whether the nozzle calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self.calibrate_nozzle_button.setText("Calibrate Nozzle Position")
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self.calibrate_nozzle_button.setText("Stop Calibration")
            self.controller.start_nozzle_calibration()

    def toggle_start_focus_calibration(self):
        """
        Toggles whether the focus calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self.calibrate_focus_button.setText("Calibrate Nozzle Focus")
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self.calibrate_focus_button.setText("Stop Calibration")
            self.controller.start_nozzle_focus_calibration()

    def toggle_start_emergence_calibration(self):
        """
        Toggles whether the droplet emergence calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self.calibrate_emergence_button.setText("Calibrate Droplet Emergence")
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self.calibrate_emergence_button.setText("Stop Calibration")
            self.controller.start_droplet_emergence_calibration()

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
            self.calibrate_pressure_scan_button.setText("Scan Pressures")
            self.controller.stop_calibration()
            return

        else:
            # Launch
            self.calibrate_pressure_scan_button.setText("Stop Calibration")
            self.controller.start_pressure_scan_calibration()

    def toggle_start_pressure_trajectory_calibration(self):
        """
        Toggles whether the pressure trajectory calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self.scan_trajectory_button.setText("Scan Trajectory Pressures")
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self.scan_trajectory_button.setText("Stop Calibration")
            self.controller.start_pressure_trajectory_calibration()

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
            self.calibrate_characterization_button.setText("Characterize Droplets")
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self.calibrate_characterization_button.setText("Stop Calibration")
            self.controller.start_droplet_characterization_calibration()

    def toggle_start_pressure_sweep_calibration(self):
        """
        Toggles whether the pressure sweep characterization calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self.calibrate_pressure_sweep_button.setText("Pressure Sweep Characterization")
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self.calibrate_pressure_sweep_button.setText("Stop Calibration")
            self.controller.start_pressure_sweep_characterization()

    def toggle_start_timecourse_calibration(self):
        """
        Toggles whether the droplet timecourse imaging calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self.calibrate_timecourse_button.setText("Droplet Timecourse Imaging")
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self.calibrate_timecourse_button.setText("Stop Calibration")
            self.controller.start_droplet_timecourse_process()

    def toggle_start_all_calibration(self):
        """
        Toggles whether all calibrations should be started.
        """
        if len(self.model.calibration_manager.calibration_queue) > 0 or self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self.calibrate_all_button.setText("Calibrate All")
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self.calibrate_all_button.setText("Stop Calibration")
            self.controller.start_all_calibrations()

    def toggle_start_pw_sweep(self):
        """
        Start/stop running 'Calibrate All' for a sweep of pulse widths.
        Uses CalibrationManager's built-in sweep orchestration.
        """
        mgr = self.model.calibration_manager

        # If a sweep is active, stop it
        if mgr.is_pulsewidth_sweep_active():
            self.calibrate_all_pw_button.setText("Calibrate All (PW Range)")
            mgr.stop_pulsewidth_sweep()
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
        self.calibrate_all_pw_button.setText("Stop PW Range")
        mgr.start_pulsewidth_sweep(pw_start, pw_end, pw_step)

    def on_readiness_changed(self, readiness: dict):
        """
        Updates the UI based on the readiness of each calibration component.
        Applies a clear visual indication for inactive buttons.
        """
        mapping = {
            # 'pressure_calibration':            self.calibrate_pressure_button,
            'pressure_scan':                   self.calibrate_pressure_scan_button,
            # 'droplet_trajectory':              self.calibrate_trajectory_button,
            'trajectory_pressure_scan':        self.scan_trajectory_button,
            # 'droplet_search':                  self.calibrate_search_button,
            'droplet_characterization':        self.calibrate_characterization_button,  # (same readiness as search)
            'pressure_sweep_characterization': self.calibrate_pressure_sweep_button,
        }

        # # If you also want the search button to mirror "droplet_characterization":
        # if 'droplet_characterization' in readiness:
        #     r = readiness['droplet_characterization']
        #     self._set_btn_state(self.calibrate_search_button, bool(r.get('ready')), r.get('missing'))

        for key, btn in mapping.items():
            info = readiness.get(key, {})
            self._set_btn_state(btn, bool(info.get('ready')), info.get('missing'))

    def _get_start_p(self) -> float:
        return float(self.start_pressure_spin.value())
       
    def _set_btn_state(self, btn: QtWidgets.QPushButton, ready: bool, missing: list[str] | None = None):
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
            btn.setToolTip("")
            btn.setCursor(Qt.ArrowCursor)
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
        # Try via calibration manager (stable with your existing _safe_get_stock_solution)
        cm = self._bridge_get_calibration_manager()
        if cm is not None:
            try:
                r = cm._safe_get_stock_solution()
                if r:
                    return str(r)
            except Exception:
                pass
        # Fallback to printer head in gripper
        try:
            ph = self.model.rack_model.get_gripper_printer_head()
            if ph:
                return ph.get_reagent_name()
        except Exception:
            pass
        return None

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
        # populate the labels when the dialog appears
        self._bridge_refresh_design_labels()

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
                self.bridge_table.setItem(r, 0, QtWidgets.QTableWidgetItem(f'{row["target_final"]:.6g} {row["units"]}'))
                self.bridge_table.setItem(r, 1, QtWidgets.QTableWidgetItem(f'{row["achieved_final"]:.6g} {row["units"]}'))
                self.bridge_table.setItem(r, 2, QtWidgets.QTableWidgetItem(f'{row["error"]:+.3g}'))
                self.bridge_table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(row["drops"])))
                self.bridge_table.setItem(r, 4, QtWidgets.QTableWidgetItem(f'{row["delta_per_drop"]:.6g} {row["units"]}/drop'))
                self.bridge_table.setItem(r, 5, QtWidgets.QTableWidgetItem(f'{row["printed_nL_new"]:.3f} nL'))
                self.bridge_table.setItem(r, 6, QtWidgets.QTableWidgetItem(f'{row["printed_nL_shift"]:+.3f} nL'))
        else:
            # For two-stock, show a+b and indicate tuple in 'Drops'; Δ/drop shows "d1 | d2"
            for r, row in enumerate(rows):
                drops = row["drops"]; a, b = drops
                dtxt = f'{row["delta_per_drop_leg1"]:.6g} | {row["delta_per_drop_leg2"]:.6g} {row["units"]}/drop'
                self.bridge_table.setItem(r, 0, QtWidgets.QTableWidgetItem(f'{row["target_final"]:.6g} {row["units"]}'))
                self.bridge_table.setItem(r, 1, QtWidgets.QTableWidgetItem(f'{row["achieved_final"]:.6g} {row["units"]}'))
                self.bridge_table.setItem(r, 2, QtWidgets.QTableWidgetItem(f'{row["error"]:+.3g}'))
                self.bridge_table.setItem(r, 3, QtWidgets.QTableWidgetItem(f'({a},{b}) = {a+b}'))
                self.bridge_table.setItem(r, 4, QtWidgets.QTableWidgetItem(dtxt))
                self.bridge_table.setItem(r, 5, QtWidgets.QTableWidgetItem(f'{row["printed_nL_new"]:.3f} nL'))
                self.bridge_table.setItem(r, 6, QtWidgets.QTableWidgetItem(f'{row["printed_nL_shift"]:+.3f} nL'))

        self.bridge_table.resizeColumnsToContents()
        self.bridge_table.resizeRowsToContents()

    def _bridge_clear_preview(self):
        self._bridge_preview_payload = None
        self.bridge_apply_btn.setEnabled(False)
        self.bridge_table.setRowCount(0)

    def _populate_bridge_preview_table(self, preview: dict):
        rows = preview.get("rows", [])
        self.bridge_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            # small helpers
            def it(v): 
                return QtWidgets.QTableWidgetItem("" if v is None else str(v))
            # columns: "Target (final)", "Achievable (final)", "Error", "Drops", "Δ/drop", "Printed nL (new)", "Δ printed nL"
            self.bridge_table.setItem(i, 0, it(f"{float(r['target_final']):.6g}"))
            self.bridge_table.setItem(i, 1, it(f"{float(r['achieved_final']):.6g}"))
            self.bridge_table.setItem(i, 2, it(f"{float(r['error']):+.6g}"))

            drops = r.get("drops")
            drops_txt = f"{drops[0]}+{drops[1]}" if isinstance(drops, tuple) else str(int(drops))
            self.bridge_table.setItem(i, 3, it(drops_txt))

            if "delta_per_drop" in r:
                d_txt = f"{float(r['delta_per_drop']):.6g}"
            else:
                d_txt = f"{float(r['delta_per_drop_leg1']):.6g}|{float(r['delta_per_drop_leg2']):.6g}"
            self.bridge_table.setItem(i, 4, it(d_txt))

            self.bridge_table.setItem(i, 5, it(f"{float(r['printed_nL_new']):.3f}"))
            self.bridge_table.setItem(i, 6, it(f"{float(r['printed_nL_shift']):+.3f}"))

    def _bridge_preview_from_last_char(self):
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
            self.bridge_table.setItem(0, 4, _it(f'{mean_nL:.6g} nL/drop'))
            self.bridge_table.setItem(0, 5, _it(f'{row["printed_nL_new"]:.3f} nL'))
            self.bridge_table.setItem(0, 6, _it(f'{row["printed_nL_shift"]:+.3f} nL'))
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

        # --- Special case: fill reagent
        if payload.get("is_fill"):
            try:
                out = em.apply_fill_droplet_volume(float(payload["new_fill_nL"]), write_keys_if_assigned=True)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Apply failed", f"{e}")
                return

            # Refresh UI tables that show the per-stock + fill totals
            if hasattr(self.main_window, "refresh_stock_table"):
                try:
                    self.main_window.refresh_stock_table()
                except Exception:
                    pass

            self._bridge_clear_preview()
            self._bridge_refresh_design_labels()
            QtWidgets.QMessageBox.information(
                self, "Applied (Fill)",
                (
                    f"Updated fill droplet volume to {out['new_fill_nL']:.3f} nL."
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

        if cur_dv is not None and abs(new_dv - cur_dv) < 1e-9:
            QtWidgets.QMessageBox.information(self, "Apply", "New droplet volume equals current design; nothing to change.")
            return

        try:
            em.apply_droplet_volume_for_option(
                payload["factor_name"], payload["option_name"], new_dv, write_keys_if_assigned=True
            )
        except NotImplementedError as e:
            QtWidgets.QMessageBox.warning(self, "Apply failed", str(e))
            return
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Apply failed", f"{e}")
            return

        self._bridge_clear_preview()
        self._bridge_refresh_design_labels()
        QtWidgets.QMessageBox.information(
            self, "Applied",
            f"Updated {payload['factor_name']}{('/' + payload['option_name']) if payload['option_name'] else ''} to {new_dv:.3f} nL."
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
        ok = bool(raw and raw.get("pw_us") is not None and raw.get("pressure_psi") is not None)
        self.load_selected_button.setEnabled(ok)

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
        _, raw = self._selected_summary_row()
        if not raw:
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
            self.print_pulse_width_spinbox.blockSignals(True)
            self.print_pulse_width_spinbox.setValue(pw)
            self.print_pulse_width_spinbox.blockSignals(False)

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
        self.camera_timer.stop()
        try:
            self.controller.set_droplet_capture_profile("default")
            self.controller.set_command_dispatch_interval(90)
        except Exception:
            pass
        self.stop_droplet_camera()
        self.controller.stop_read_camera()
        self.controller.disable_print_profile()
        event.accept()

class RefuelCameraWindow(QtWidgets.QDialog):
    def __init__(self,main_window,model,controller):
        super().__init__()
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict

        self.model = model
        self.refuel_camera_model = self.model.refuel_camera_model
        self.controller = controller

        self.shortcut_manager = ShortcutManager(self)
        self.setup_shortcuts()

        # self.controller.enter_print_mode()

        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Refuel Camera")
        self.resize(1200, 700)

        self.layout = QGridLayout()

        self.control_layout = QVBoxLayout()
        self.capture_button = QPushButton("Start Capturing Images")
        self.capture_button.clicked.connect(self.toggle_capture)

        self.save_button = QPushButton("Save Current Frame")
        self.save_button.clicked.connect(self.save_frame)

        # self.reference_button = QPushButton("Set Reference Image")
        # self.reference_button.clicked.connect(self.set_reference_image)

        self.offset_spinbox = QSpinBox()
        self.offset_spinbox.setRange(0, 100)  # Assuming cropped image max width
        self.offset_spinbox.setValue(40)
        self.offset_spinbox.setSingleStep(2)
        self.offset_spinbox.setPrefix("Left Offset: ")
        self.offset_spinbox.valueChanged.connect(self.update_analysis)

        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(0, 200)
        self.width_spinbox.setValue(20)
        self.width_spinbox.setSingleStep(2)
        self.width_spinbox.setPrefix("Channel width: ")
        self.width_spinbox.valueChanged.connect(self.update_analysis)

        self.threshold_spinbox = QSpinBox()
        self.threshold_spinbox.setRange(5, 250)  # Assuming cropped image max width
        self.threshold_spinbox.setValue(60)
        self.threshold_spinbox.setSingleStep(5)
        self.threshold_spinbox.setPrefix("Threshold: ")
        self.threshold_spinbox.valueChanged.connect(self.update_analysis)

        self.prom_spinbox = QSpinBox()
        self.prom_spinbox.setRange(2, 20)  # Assuming cropped image max height
        self.prom_spinbox.setValue(4)
        self.prom_spinbox.setSingleStep(1)
        self.prom_spinbox.setPrefix("Prominence: ")
        self.prom_spinbox.valueChanged.connect(self.update_analysis)

        self.empty_cutoff = QDoubleSpinBox()
        self.empty_cutoff.setDecimals(2)
        self.empty_cutoff.setRange(0.0, 2.0)
        self.empty_cutoff.setValue(0.25)
        self.empty_cutoff.setSingleStep(0.05)
        self.empty_cutoff.setPrefix("Empty Cutoff: ")
        self.empty_cutoff.valueChanged.connect(self.update_analysis)

        # Label to show the current level reading
        self.level_label = QLabel("Current Level: N/A")
        self.level_label.setAlignment(Qt.AlignCenter)
        self.level_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.level_label.setFixedHeight(30)
        self.level_label.setFixedWidth(200)
        self.level_label.setStyleSheet("background-color: lightgray; border: 1px solid black;")

        self.image_label = QLabel("No image captured yet.")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setFixedWidth(480)
        self.image_label.setFixedHeight(640)

        # Add a plot to show the level over time
        self.level_series = QtCharts.QLineSeries()
        self.level_series.setColor(QtCore.Qt.white)
        self.level_chart = QtCharts.QChart()
        self.level_chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.level_chart.setBackgroundBrush(QtGui.QBrush(self.color_dict['dark_gray']))  # Set the background color to grey
        self.level_chart.addSeries(self.level_series)
        # self.level_chart.createDefaultAxes()
        self.level_chart.setTitle("Refuel level over time")

        self.axisX = QtCharts.QValueAxis()
        self.axisX.setTickCount(3)
        self.axisX.setRange(0, 100)
        self.axisX.setTitleText("Time (s)")
        self.axisY = QtCharts.QValueAxis()
        self.axisY.setTickCount(3)
        self.axisY.setRange(0, 250)
        self.axisY.setTitleText("Level")

        self.level_chart.addAxis(self.axisX, QtCore.Qt.AlignBottom)
        self.level_chart.addAxis(self.axisY, QtCore.Qt.AlignLeft)
        self.level_series.attachAxis(self.axisX)
        self.level_series.attachAxis(self.axisY)

        # Create a chart view to display the chart
        self.level_chart_view = QtCharts.QChartView(self.level_chart)
        self.level_chart_view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.level_chart.legend().hide()  # Hide
        self.level_chart_view.setFocusPolicy(QtCore.Qt.NoFocus)
        self.level_chart_view.setFixedSize(480, 240)


        self.control_layout.addWidget(self.capture_button)
        self.control_layout.addWidget(self.save_button)
        # self.control_layout.addWidget(self.reference_button)
        self.control_layout.addWidget(self.offset_spinbox)
        self.control_layout.addWidget(self.width_spinbox)
        self.control_layout.addWidget(self.threshold_spinbox)
        self.control_layout.addWidget(self.prom_spinbox)
        self.control_layout.addWidget(self.empty_cutoff)
        self.control_layout.addWidget(self.level_label)


        self.layout.addLayout(self.control_layout, 0, 0, 2, 1)
        self.layout.addWidget(self.image_label, 0, 1)
        self.layout.addWidget(self.level_chart_view, 1, 1)
        # self.layout.addWidget(self.plot_canvas, 1, 1)

        self.setLayout(self.layout)

        # Timer for periodic image capture
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.capture_image)
        self.capturing = False

        self.start_camera()
        self.update_analysis()

        self.refuel_camera_model.update_level_ui_signal.connect(self.update_refuel_ui)

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

    def toggle_capture(self):
        """
        Starts or stops capturing images based on the button toggle.
        """
        if self.capturing:
            self.timer.stop()
            self.capture_button.setText("Start Capturing Images")
        else:
            self.timer.start(500)  # Capture every 100 milliseconds
            self.capture_button.setText("Stop Capturing Images")
        self.capturing = not self.capturing

    def start_camera(self):
        self.controller.start_refuel_camera()

    def capture_image(self):
        self.controller.capture_refuel_image()

    def stop_camera(self):
        self.controller.stop_refuel_camera()

    def save_frame(self):
        """
        Saves the current frame to a file.
        """
        original_image = self.refuel_camera_model.get_original_image()
        if original_image is not None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"./MVC-interface/Images/Refuel/refuel_frame_{timestamp}.png"
            cv2.imwrite(filename, original_image)
            print(f"Frame saved as {filename}")
        else:
            print("No image captured yet.")

    def numpy_to_qimage(self,image):
        """
        Converts a numpy array (captured image) to a QImage.
        """
        height, width, channels = image.shape
        bytes_per_line = channels * width
        qimage = QImage(image.data, width, height, bytes_per_line, QImage.Format_RGB888)
        return qimage.rgbSwapped()

    def numpy_to_qimage_grayscale(self,image):
        """
        Converts a grayscale numpy array to a QImage.
        """
        height, width = image.shape
        bytes_per_line = width
        qimage = QImage(image.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
        return qimage

    def update_refuel_ui(self):
        annotated_image = self.refuel_camera_model.get_annotated_image()

        # Convert numpy array to QImage for display
        qimage = self.numpy_to_qimage(annotated_image)

        # Display original image
        pixmap = QPixmap.fromImage(qimage)
        self.image_label.setPixmap(pixmap)
        self.image_label.setScaledContents(True)

        level = self.refuel_camera_model.get_current_level()
        if level is not None:
            self.level_label.setText(f"Current Level: {level:.1f}")
        else:
            self.level_label.setText("Current Level: N/A")

        # Update the level chart
        self.update_level_chart()

    def update_level_chart(self):
        """
        Update the level chart with the current level data.
        """
        level_log = self.refuel_camera_model.get_level_log()
        # if len(level_log) > 0:
        #     self.level_axisY.setRange(min(level_log) - 1, max(level_log) + 1)
        # else:
        #     self.level_axisY.setRange(0, 100)
        
        # Clear the series and add new data
        self.level_series.clear()
        for i, level in enumerate(level_log):
            self.level_series.append(i, level)
        # Update the X axis range based on the number of data points
        if len(level_log) > 0:
            self.axisX.setRange(0, len(level_log) - 1)
        else:
            self.axisX.setRange(0, 100)


    def update_analysis(self):
        """
        Update the analysis parameters based on the spinbox values.
        """
        offset = self.offset_spinbox.value()
        width = self.width_spinbox.value()
        threshold = self.threshold_spinbox.value()
        prom = self.prom_spinbox.value()
        empty_cutoff = self.empty_cutoff.value()
        # Update the model with the new parameters
        self.refuel_camera_model.update_analysis_parameters(offset, width, threshold, prom, empty_cutoff)

    def closeEvent(self, event):
        """Handle the closing of the dialog."""
        self.timer.stop()
        self.stop_camera()
        # self.controller.exit_print_mode()
        super().closeEvent(event)


