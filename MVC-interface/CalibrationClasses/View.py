from PySide6 import QtCore, QtWidgets, QtGui, QtCharts
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QGridLayout, QGroupBox, QPushButton, QComboBox, QSpinBox, QSizePolicy,
    QSpacerItem, QFileDialog, QInputDialog, QMessageBox, QAbstractItemView, QDialog,QLineEdit,QDoubleSpinBox
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

        # Track whether we are in multi-capture mode:
        self.multi_capturing = False

        # Stores the steps in the process (positions/moves or captures) in a queue:
        self.multi_capture_queue = []

        # A timer that processes one step of multi-capture at a time
        self.multi_capture_timer = QtCore.QTimer(self)
        self.multi_capture_timer.setInterval(500)  # e.g. 500 ms per step
        self.multi_capture_timer.timeout.connect(self.next_multi_capture_step)


        self.setWindowTitle("Droplet Imaging New")
        self.resize(1200, 1000)

        self.layout = QtWidgets.QHBoxLayout()

        self.button_layout = QtWidgets.QGridLayout()

        row = 0
    
        # Add a label to show the number of recorded flashes
        self.flash_count_label = QtWidgets.QLabel("Flashes: 0")
        self.button_layout.addWidget(self.flash_count_label, row, 0, 1, 2)
        row += 1

        # Add a spinbox to set the duration of the flash
        self.flash_duration_label = QtWidgets.QLabel("Flash Duration (us):")
        self.flash_duration_spinbox = QtWidgets.QSpinBox()
        self.flash_duration_spinbox.setRange(0, 10000)
        self.flash_duration_spinbox.setSingleStep(1000)
        self.flash_duration_spinbox.setValue(self.droplet_camera_model.flash_duration)
        self.button_layout.addWidget(self.flash_duration_label, row, 0)
        self.button_layout.addWidget(self.flash_duration_spinbox, row, 1)
        row += 1

        # Add a spinbox to set the delay before the flash
        self.flash_delay_label = QtWidgets.QLabel("Flash Delay (us):")
        self.flash_delay_spinbox = QtWidgets.QSpinBox()
        self.flash_delay_spinbox.setRange(0, 50000)
        self.flash_delay_spinbox.setSingleStep(100)
        self.flash_delay_spinbox.setValue(self.droplet_camera_model.flash_delay)
        self.button_layout.addWidget(self.flash_delay_label, row, 0)
        self.button_layout.addWidget(self.flash_delay_spinbox, row, 1)
        row += 1

        # Add a spinbox to set the number of droplets to print before imaging
        self.num_droplets_label = QtWidgets.QLabel("Number of droplets:")
        self.num_droplets_spinbox = QtWidgets.QSpinBox()
        self.num_droplets_spinbox.setRange(0, 20)
        self.num_droplets_spinbox.setSingleStep(1)
        self.num_droplets_spinbox.setValue(self.droplet_camera_model.num_droplets)
        self.button_layout.addWidget(self.num_droplets_label, row, 0)
        self.button_layout.addWidget(self.num_droplets_spinbox, row, 1)
        row += 1

        # Add a spinbox to set the print pulse width
        self.print_pulse_width_label = QtWidgets.QLabel("Print Pulse Width:")
        self.print_pulse_width_spinbox = QtWidgets.QSpinBox()
        self.print_pulse_width_spinbox.setRange(0, 10000)
        self.print_pulse_width_spinbox.setSingleStep(50)
        self.print_pulse_width_spinbox.setValue(self.model.machine_model.get_print_pulse_width())
        self.button_layout.addWidget(self.print_pulse_width_label, row, 0)
        self.button_layout.addWidget(self.print_pulse_width_spinbox, row, 1)
        row += 1

        # Add a spinbox for exposure time
        self.exposure_time_label = QtWidgets.QLabel("Exposure Time (ms):")
        self.exposure_time_spinbox = QtWidgets.QSpinBox()
        self.exposure_time_spinbox.setRange(0, 2000000)
        self.exposure_time_spinbox.setSingleStep(10000)
        self.exposure_time_spinbox.setValue(self.droplet_camera_model.exposure_time)
        self.button_layout.addWidget(self.exposure_time_label, row, 0)
        self.button_layout.addWidget(self.exposure_time_spinbox, row, 1)
        row += 1

        # Add a button to trigger a flash
        self.flash_button = QtWidgets.QPushButton("Trigger Flash")
        self.flash_button.clicked.connect(self.toggle_flash)
        self.button_layout.addWidget(self.flash_button, row, 0, 1, 2)
        row += 1

        # Add line to separate buttons
        self.button_layout.addWidget(QtWidgets.QLabel(" "), row, 0, 1, 2)
        row += 1

        # Add text edit box for the directory name to save images in
        self.save_directory_label = QtWidgets.QLabel("Save Directory:")
        self.save_directory_edit = QtWidgets.QLineEdit()
        self.save_directory_edit.setText(self.droplet_camera_model.dir_name)
        self.button_layout.addWidget(self.save_directory_label, row, 0)
        self.button_layout.addWidget(self.save_directory_edit, row, 1)
        row += 1

        # Add a button to toggle whether the captured image should be saved
        self.save_button = QtWidgets.QPushButton("Save Images")
        self.save_button.clicked.connect(self.toggle_saving)
        self.button_layout.addWidget(self.save_button, row, 0, 1, 2)
        row += 1

        # Add a button for repeated image capture
        self.repeat_capture_button = QtWidgets.QPushButton("Start Repeated Capture")
        self.repeat_capture_button.clicked.connect(self.toggle_repeat_capture)
        self.button_layout.addWidget(self.repeat_capture_button, row, 0, 1, 2)
        # self.layout.addLayout(self.button_layout)
        row += 1

        self.multi_start_label = QtWidgets.QLabel("Multi-Capture Start Delay (us):")
        self.multi_start_spinbox = QtWidgets.QSpinBox()
        self.multi_start_spinbox.setRange(0, 50000)
        self.multi_start_spinbox.setSingleStep(100)
        self.multi_start_spinbox.setValue(15000)
        self.button_layout.addWidget(self.multi_start_label, row, 0)
        self.button_layout.addWidget(self.multi_start_spinbox, row, 1)
        row += 1

        self.multi_end_label = QtWidgets.QLabel("Multi-Capture End Delay (us):")
        self.multi_end_spinbox = QtWidgets.QSpinBox()
        self.multi_end_spinbox.setRange(0, 50000)
        self.multi_end_spinbox.setSingleStep(100)
        self.multi_end_spinbox.setValue(15000)
        self.button_layout.addWidget(self.multi_end_label, row, 0)
        self.button_layout.addWidget(self.multi_end_spinbox, row, 1)
        row += 1

        self.multi_steps_label = QtWidgets.QLabel("Number of Time Steps:")
        self.multi_steps_spinbox = QtWidgets.QSpinBox()
        self.multi_steps_spinbox.setRange(1, 1000)
        self.multi_steps_spinbox.setValue(1)
        self.button_layout.addWidget(self.multi_steps_label, row, 0)
        self.button_layout.addWidget(self.multi_steps_spinbox, row, 1)
        row += 1

        self.frame_shift_label = QtWidgets.QLabel("Percent of frame:")
        self.frame_shift_spinbox = QtWidgets.QDoubleSpinBox()
        self.frame_shift_spinbox.setDecimals(1)
        self.frame_shift_spinbox.setRange(0, 1)
        self.frame_shift_spinbox.setSingleStep(0.1)
        self.frame_shift_spinbox.setValue(1)
        self.button_layout.addWidget(self.frame_shift_label, row, 0)
        self.button_layout.addWidget(self.frame_shift_spinbox, row, 1)
        row += 1

        self.multi_frames_below_label = QtWidgets.QLabel("Frames Below Start:")
        self.multi_frames_below_spinbox = QtWidgets.QSpinBox()
        self.multi_frames_below_spinbox.setRange(0, 100)
        self.multi_frames_below_spinbox.setValue(0)
        self.button_layout.addWidget(self.multi_frames_below_label, row, 0)
        self.button_layout.addWidget(self.multi_frames_below_spinbox, row, 1)
        row += 1

        # Add spin box for multi-execute timer interval
        self.multi_timer_interval_label = QtWidgets.QLabel("Timer Interval (ms):")
        self.multi_timer_interval_spinbox = QtWidgets.QSpinBox()
        self.multi_timer_interval_spinbox.setRange(0, 10000)
        self.multi_timer_interval_spinbox.setSingleStep(100)
        self.multi_timer_interval_spinbox.setValue(500)
        self.button_layout.addWidget(self.multi_timer_interval_label, row, 0)
        self.button_layout.addWidget(self.multi_timer_interval_spinbox, row, 1)
        row += 1

        # Add spin box for replicate images of each condition
        self.multi_replicate_label = QtWidgets.QLabel("Replicate Images:")
        self.multi_replicate_spinbox = QtWidgets.QSpinBox()
        self.multi_replicate_spinbox.setRange(1, 100)
        self.multi_replicate_spinbox.setValue(10)
        self.button_layout.addWidget(self.multi_replicate_label, row, 0)
        self.button_layout.addWidget(self.multi_replicate_spinbox, row, 1)
        row += 1

        # Button to start/stop the multi-capture
        self.multi_capture_button = QtWidgets.QPushButton("Execute Multi-Capture")
        self.multi_capture_button.clicked.connect(self.toggle_multi_capture)
        self.button_layout.addWidget(self.multi_capture_button, row, 0, 1, 2)
        row += 1

        # Button to toggle analysis of captured images
        self.analyze_button = QtWidgets.QPushButton("Analyze Images")
        self.analyze_button.clicked.connect(self.toggle_analyzing)
        self.button_layout.addWidget(self.analyze_button, row, 0, 1, 2)
        row += 1

        intensity_threshold, circularity_threshold, min_area, edge_margin = self.droplet_camera_model.get_analysis_parameters()
        print(f'Analysis parameters: {min_area}, {intensity_threshold}, {circularity_threshold}, {edge_margin}')
        
        # Add a spin box to set the min area threshold for the analysis
        self.min_area_label = QtWidgets.QLabel("Min Area Threshold:")
        self.min_area_spinbox = QtWidgets.QSpinBox()
        self.min_area_spinbox.setRange(0, 10000000)
        self.min_area_spinbox.setSingleStep(1000)
        self.min_area_spinbox.setValue(min_area)
        self.button_layout.addWidget(self.min_area_label, row, 0)
        self.button_layout.addWidget(self.min_area_spinbox, row, 1)
        row += 1

        # Add a spin box to set the intensity threshold for the analysis
        self.intensity_threshold_label = QtWidgets.QLabel("Intensity Threshold:")
        self.intensity_threshold_spinbox = QtWidgets.QSpinBox()
        self.intensity_threshold_spinbox.setRange(0, 255)
        self.intensity_threshold_spinbox.setSingleStep(10)
        self.intensity_threshold_spinbox.setValue(intensity_threshold)
        self.button_layout.addWidget(self.intensity_threshold_label, row, 0)
        self.button_layout.addWidget(self.intensity_threshold_spinbox, row, 1)
        row += 1

        # Add a spin box to set the circularity threshold for the analysis
        self.circularity_threshold_label = QtWidgets.QLabel("Circularity Threshold:")
        self.circularity_threshold_spinbox = QtWidgets.QDoubleSpinBox()
        self.circularity_threshold_spinbox.setDecimals(2)
        self.circularity_threshold_spinbox.setRange(0, 2)
        self.circularity_threshold_spinbox.setSingleStep(0.1)
        self.circularity_threshold_spinbox.setValue(circularity_threshold)
        self.button_layout.addWidget(self.circularity_threshold_label, row, 0)
        self.button_layout.addWidget(self.circularity_threshold_spinbox, row, 1)
        row += 1

        # Add a spin box to set the edge margin for the analysis
        self.edge_margin_label = QtWidgets.QLabel("Edge Margin:")
        self.edge_margin_spinbox = QtWidgets.QSpinBox()
        self.edge_margin_spinbox.setRange(0, 1000)
        self.edge_margin_spinbox.setSingleStep(5)
        self.edge_margin_spinbox.setValue(edge_margin)
        self.button_layout.addWidget(self.edge_margin_label, row, 0)
        self.button_layout.addWidget(self.edge_margin_spinbox, row, 1)
        row += 1

        # Add a button to trigger the nozzle position calibration
        self.calibrate_nozzle_button = QtWidgets.QPushButton("Calibrate Nozzle Position")
        self.calibrate_nozzle_button.clicked.connect(self.toggle_start_nozzle_calibration)
        self.button_layout.addWidget(self.calibrate_nozzle_button, row, 0, 1, 2)
        row += 1

        # Add a button to move the machine to position the nozzle in the center of the screen
        self.center_nozzle_button = QtWidgets.QPushButton("Center Nozzle")
        self.center_nozzle_button.clicked.connect(self.center_nozzle)
        self.button_layout.addWidget(self.center_nozzle_button, row, 0, 1, 2)
        row += 1

        # Add a button to trigger the nozzle focus calibration
        self.calibrate_focus_button = QtWidgets.QPushButton("Calibrate Nozzle Focus")
        self.calibrate_focus_button.clicked.connect(self.toggle_start_focus_calibration)
        self.button_layout.addWidget(self.calibrate_focus_button, row, 0, 1, 2)
        row += 1

        # Add a button to trigger the droplet emergence calibration
        self.calibrate_emergence_button = QtWidgets.QPushButton("Calibrate Droplet Emergence")
        self.calibrate_emergence_button.clicked.connect(self.toggle_start_emergence_calibration)
        self.button_layout.addWidget(self.calibrate_emergence_button, row, 0, 1, 2)
        row += 1

        # Add a button to trigger the pressure calibration
        self.calibrate_pressure_button = QtWidgets.QPushButton("Calibrate Pressure")
        self.calibrate_pressure_button.clicked.connect(self.toggle_start_pressure_calibration)
        self.button_layout.addWidget(self.calibrate_pressure_button, row, 0, 1, 2)
        row += 1

        # Add a button to trigger the droplet trajectory calibration
        self.calibrate_trajectory_button = QtWidgets.QPushButton("Calibrate Droplet Trajectory")
        self.calibrate_trajectory_button.clicked.connect(self.toggle_start_trajectory_calibration)
        self.button_layout.addWidget(self.calibrate_trajectory_button, row, 0, 1, 2)
        row += 1

        # Add a button to trigger the droplet search calibration
        self.calibrate_search_button = QtWidgets.QPushButton("Calibrate Droplet Search")
        self.calibrate_search_button.clicked.connect(self.toggle_start_search_calibration)
        self.button_layout.addWidget(self.calibrate_search_button, row, 0, 1, 2)
        row += 1

        # Add a button to trigger all calibrations
        self.calibrate_all_button = QtWidgets.QPushButton("Calibrate All")
        self.calibrate_all_button.clicked.connect(self.toggle_start_all_calibration)
        self.button_layout.addWidget(self.calibrate_all_button, row, 0, 1, 2)
        row += 1

        # Add a label that updates with the state of the calibration
        self.stageLabel = QtWidgets.QLabel("Status: Idle")
        self.button_layout.addWidget(self.stageLabel, row, 0, 1, 2)
        row += 1


        self.button_container_layout = QtWidgets.QVBoxLayout()
        self.button_container_layout.addLayout(self.button_layout)
        self.button_container_layout.addStretch()  # Add a stretch at the bottom to push everything up
        self.layout.addLayout(self.button_container_layout)

        # Add vertical layout for the image and analysis below it
        self.analysis_layout = QtWidgets.QVBoxLayout()

        self.image_label = QLabel("No image captured yet.")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setFixedHeight(640)
        self.image_label.setFixedWidth(480)
        self.analysis_layout.addWidget(self.image_label)

        # Create a container widget for the motor position labels.
        self.diff_widget = QWidget()
        # Create a grid layout for the diff labels and set its alignment to top left.
        self.diff_layout = QGridLayout(self.diff_widget)
        self.diff_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

                # Add column headers
        motor_label = QLabel('Motor')
        current_label = QLabel('Current')
        target_label = QLabel('Diff')
        motor_label.setAlignment(Qt.AlignCenter)
        current_label.setAlignment(Qt.AlignCenter)
        target_label.setAlignment(Qt.AlignCenter)

        self.diff_layout.addWidget(motor_label, 0, 0)
        self.diff_layout.addWidget(current_label, 0, 1)
        self.diff_layout.addWidget(target_label, 0, 2)

        # Labels to display motor positions.
        self.diff_labels = {
            'X': {'current': QLabel('0'), 'diff': QLabel('0')},
            'Y': {'current': QLabel('0'), 'diff': QLabel('0')},
            'Z': {'current': QLabel('0'), 'diff': QLabel('0')},
        }

        row = 1
        for motor, positions in self.diff_labels.items():
            # Create a fixed-size motor label.
            motor_label = QLabel(motor)
            motor_label.setAlignment(Qt.AlignCenter)
            motor_label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            # Set fixed size policies for current and diff labels.
            positions['current'].setAlignment(Qt.AlignCenter)
            positions['current'].setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            positions['diff'].setAlignment(Qt.AlignCenter)
            positions['diff'].setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            
            self.diff_layout.addWidget(motor_label, row, 0)
            self.diff_layout.addWidget(positions['current'], row, 1)
            self.diff_layout.addWidget(positions['diff'], row, 2)
            row += 1

        # Add the diff_widget (which now contains the grid of labels) to the analysis layout.
        self.analysis_layout.addWidget(self.diff_widget, alignment=Qt.AlignTop | Qt.AlignLeft)

        # Finally, add the analysis_layout to your main layout.
        self.layout.addLayout(self.analysis_layout)

        self.setLayout(self.layout)

        self.model.droplet_camera_model.droplet_image_updated.connect(self.update_image)
        self.model.droplet_camera_model.flash_signal.connect(self.update_flash_info)
        
        self.model.calibration_manager.analyzedImageUpdated.connect(self.display_analyzed_image)
        
        self.flash_duration_spinbox.valueChanged.connect(self.set_flash_duration)
        self.flash_delay_spinbox.valueChanged.connect(self.set_flash_delay)
        self.num_droplets_spinbox.valueChanged.connect(self.set_imaging_droplets)
        self.save_directory_edit.textChanged.connect(self.set_save_directory)
        self.print_pulse_width_spinbox.valueChanged.connect(self.handle_print_pulse_width_change)
        self.exposure_time_spinbox.valueChanged.connect(self.set_exposure_time)
        self.multi_timer_interval_spinbox.valueChanged.connect(self.set_multi_timer_interval)
        self.min_area_spinbox.valueChanged.connect(self.update_analysis_parameters)
        self.intensity_threshold_spinbox.valueChanged.connect(self.update_analysis_parameters)
        self.circularity_threshold_spinbox.valueChanged.connect(self.update_analysis_parameters)
        self.edge_margin_spinbox.valueChanged.connect(self.update_analysis_parameters)

        # Connect the model's calibration stage signal to update the UI.
        self.model.calibration_manager.calibrationStageChanged.connect(self.update_stage)
        self.model.calibration_manager.calibrationCompleted.connect(self.on_calibration_completed)
        self.model.calibration_manager.calibrationQueueCompleted.connect(self.on_calibration_queue_completed)
        self.model.calibration_manager.calibrationError.connect(self.on_calibration_error)

        self.model.calibration_manager.position_diff_dict_signal.connect(self.update_position_diffs)

        self.set_exposure_time(self.droplet_camera_model.exposure_time)
        self.set_flash_delay(self.droplet_camera_model.flash_delay)
        self.set_flash_duration(self.droplet_camera_model.flash_duration)
        self.set_imaging_droplets(self.droplet_camera_model.num_droplets)
        

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
        
        self.shortcut_manager.add_shortcut('k', 'Move forward', lambda: self.controller.set_relative_Y(2,manual=True))
        self.shortcut_manager.add_shortcut('j', 'Move backward', lambda: self.controller.set_relative_Y(-2,manual=True))
        self.shortcut_manager.add_shortcut('Ctrl+k', 'Move forward', lambda: self.controller.set_relative_Y(10,manual=True))
        self.shortcut_manager.add_shortcut('Ctrl+j', 'Move backward', lambda: self.controller.set_relative_Y(-10,manual=True))
        
        # self.shortcut_manager.add_shortcut('Left', 'Move left', lambda: self.controller.set_relative_X(2, manual=True))
        # self.shortcut_manager.add_shortcut('Right', 'Move right', lambda: self.controller.set_relative_X(-2, manual=True))
        # self.shortcut_manager.add_shortcut('Up', 'Move up', lambda: self.controller.set_relative_Z(-10, manual=True))
        # self.shortcut_manager.add_shortcut('Down', 'Move down', lambda: self.controller.set_relative_Z(10, manual=True))
        # self.shortcut_manager.add_shortcut('Ctrl+Left', 'Move left', lambda: self.controller.set_relative_X(10, manual=True))
        # self.shortcut_manager.add_shortcut('Ctrl+Right', 'Move right', lambda: self.controller.set_relative_X(-10, manual=True))
        # self.shortcut_manager.add_shortcut('Ctrl+Up', 'Move up', lambda: self.controller.set_relative_Z(-50, manual=True))
        # self.shortcut_manager.add_shortcut('Ctrl+Down', 'Move down', lambda: self.controller.set_relative_Z(50, manual=True))
        
        # self.shortcut_manager.add_shortcut('k', 'Move forward', lambda: self.controller.set_relative_Y(2,manual=True))
        # self.shortcut_manager.add_shortcut('j', 'Move backward', lambda: self.controller.set_relative_Y(-2,manual=True))
        # self.shortcut_manager.add_shortcut('Ctrl+k', 'Move forward', lambda: self.controller.set_relative_Y(10,manual=True))
        # self.shortcut_manager.add_shortcut('Ctrl+j', 'Move backward', lambda: self.controller.set_relative_Y(-10,manual=True))
        
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
            self.camera_timer.start(1000)  # Capture every 100 milliseconds
            self.repeat_capture_button.setText("Stop Repeated Capture")
        self.capturing = not self.capturing

    def enter_repeat_capture_mode(self):
        """
        Enters the repeat capture mode.
        """
        self.set_exposure_time(200000)
        self.num_droplets_spinbox.setValue(0)

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

    def toggle_multi_capture(self):
        """
        Toggles the multi-capture process on/off using one button.
        """
        if not self.multi_capturing:
            # START multi-capture
            self.start_multi_capture()
        else:
            # STOP multi-capture
            self.stop_multi_capture()

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

    def set_multi_timer_interval(self, interval):
        """
        Sets the interval for the multi-capture timer.
        """
        self.multi_capture_timer.setInterval(interval)

    def set_save_directory(self, directory):
        """
        Sets the directory to save images in.
        """
        self.controller.set_save_directory(directory)

    def update_flash_info(self):
        """
        Updates the flash info.
        """
        count = self.model.droplet_camera_model.get_num_flashes()
        self.flash_count_label.setText(f"Flashes: {count}")
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
        self.controller.capture_droplet_image()

    def stop_droplet_camera(self):
        self.controller.stop_droplet_camera()

    def start_multi_capture(self):
        start_delay = self.multi_start_spinbox.value()
        end_delay = self.multi_end_spinbox.value()
        num_steps = self.multi_steps_spinbox.value()
        frames_below = self.multi_frames_below_spinbox.value()
        shift_percent = self.frame_shift_spinbox.value()
        replicates = self.multi_replicate_spinbox.value()

        if num_steps < 1 or start_delay > end_delay:
            QtWidgets.QMessageBox.warning(
                self, "Invalid Parameters",
                "Check that end_delay >= start_delay and num_steps > 0."
            )
            return

        # Build the time delay list
        if num_steps == 1:
            time_delays = [start_delay]
        else:
            step_size = (end_delay - start_delay) / (num_steps - 1)
            time_delays = [int(round(start_delay + i * step_size)) 
                        for i in range(num_steps)]

        # Clear any old queue
        self.multi_capture_queue.clear()

        # We'll create a queue of (action, data) items.
        # For each 'position', we add a set of captures for each time_delay
        # Then, if not last position, we add a "move" step.

        for position_index in range(frames_below + 1):
            # Add capture actions for each time in time_delays
            for delay in time_delays:
                # We'll store ('capture', delay)
                for replicate in range(replicates):
                    self.multi_capture_queue.append(('capture', delay))
            
            # Move up after finishing this position, except for the last one
            if position_index < frames_below:
                self.multi_capture_queue.append(('move', (0,-shift_percent)))
                # -> This will call self.move_fraction_of_frame(0, 1) when triggered
                self.multi_capture_queue.append(('skip',0))
                # -> This gives the machine time to get to the target lcation prior to the next capture

        # Return to the original position
        self.multi_capture_queue.append(('move', (0,frames_below*shift_percent)))

        # Mark capturing as True and update button text
        self.multi_capturing = True
        self.multi_capture_button.setText("Stop Multi-Capture")

        # Start the timer that processes each step
        self.multi_capture_timer.start()

    def stop_multi_capture(self):
        self.multi_capture_timer.stop()
        self.multi_capturing = False
        self.multi_capture_button.setText("Execute Multi-Capture")
        self.multi_capture_queue.clear()

    def next_multi_capture_step(self):
        """
        Processes the next item in the multi-capture queue (non-blocking).
        Called periodically by self.multi_capture_timer.
        """
        # If we've run out of steps or the user requested stop:
        if not self.multi_capture_queue or not self.multi_capturing:
            self.finish_multi_capture()
            return

        action, data = self.multi_capture_queue.pop(0)  # pop front of list

        if action == 'capture':
            if delay is not None:
                delay = data
                # Set spinbox and flash delay
                self.flash_delay_spinbox.setValue(delay)
                time.sleep(0.05)
            # Trigger a capture
            self.controller.capture_droplet_image()

        elif action == 'move':
            # data is (x_fraction, y_fraction)
            (x_fraction, y_fraction) = data
            self.move_fraction_of_frame(x_fraction, y_fraction)

        elif action == 'skip':
            return

        elif action == 'droplet':
            self.num_droplets_spinbox.setValue(data)


        # Once this method returns, the UI is free to process events, so it's non-blocking.
        # We'll pick up the next step on the next timer tick.
    
    def finish_multi_capture(self):
        """
        Called when the multi-capture sequence is complete or aborted.
        """
        self.multi_capture_timer.stop()
        self.multi_capturing = False
        self.multi_capture_queue.clear()
        self.multi_capture_button.setText("Execute Multi-Capture")

        # Optionally show a message that we completed all steps
        QtWidgets.QMessageBox.information(
            self,
            "Multi-Capture Complete",
            "All requested positions and time delays have been captured."
        )

    def on_calibration_completed(self):
        """
        Called when the calibration process is completed.
        """
        self.update_stage("Calibration Completed")
        self.reset_calibration_buttons()

    def on_calibration_queue_completed(self):
        """
        Called when the calibration queue is completed.
        """
        self.update_stage("Calibration Queue Completed")
        self.reset_calibration_buttons()
        self.calibrate_all_button.setText("Calibrate All")

    def on_calibration_error(self, error_message):
        """
        Called when the calibration process encounters an error.
        """
        self.update_stage("Calibration Error")
        self.reset_calibration_buttons()
        self.calibrate_all_button.setText("Calibrate All")
        QtWidgets.QMessageBox.warning(self, "Calibration Error", error_message)

    def reset_calibration_buttons(self):
        """
        Resets the calibration buttons to their default state.
        """
        self.calibrate_nozzle_button.setText("Calibrate Nozzle Position")
        self.calibrate_focus_button.setText("Calibrate Nozzle Focus")
        self.calibrate_emergence_button.setText("Calibrate Droplet Emergence")
        self.calibrate_pressure_button.setText("Calibrate Pressure")
        self.calibrate_trajectory_button.setText("Calibrate Droplet Trajectory")
        self.calibrate_search_button.setText("Calibrate Droplet Search")

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

    def toggle_start_pressure_calibration(self):
        """
        Toggles whether the pressure calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self.calibrate_pressure_button.setText("Calibrate Pressure")
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self.calibrate_pressure_button.setText("Stop Calibration")
            self.controller.start_pressure_calibration()

    def toggle_start_trajectory_calibration(self):
        """
        Toggles whether the droplet trajectory calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self.calibrate_trajectory_button.setText("Calibrate Droplet Trajectory")
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self.calibrate_trajectory_button.setText("Stop Calibration")
            self.controller.start_trajectory_calibration()

    def toggle_start_search_calibration(self):
        """
        Toggles whether the droplet search calibration should be started.
        """
        if self.model.calibration_manager.activeCalibration is not None:
            print('Stopping calibration')
            self.calibrate_search_button.setText("Calibrate Droplet Search")
            self.controller.stop_calibration()
        else:
            print('Starting calibration')
            self.calibrate_search_button.setText("Stop Calibration")
            self.controller.start_droplet_search_calibration()

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

    def update_stage(self, stage):
        """
        Updates the stage label based on the calibration stage.
        """
        self.stageLabel.setText(f"Status: {stage}")

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
        self.stop_droplet_camera()
        self.controller.stop_read_camera()
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

        self.controller.enter_print_mode()

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
        self.controller.exit_print_mode()
        super().closeEvent(event)

