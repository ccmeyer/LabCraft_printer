from __future__ import annotations

# Import your model & dataclasses
from Model import ( FactorSpec, OptionSpec, ExperimentModel)

from PySide6 import QtCore, QtWidgets, QtGui, QtCharts
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QGridLayout, QGroupBox, QPushButton, QComboBox, QSpinBox, QSizePolicy,
    QSpacerItem, QFileDialog, QInputDialog, QMessageBox, QAbstractItemView, QDialog,QLineEdit,QDoubleSpinBox,
    QTabWidget, QCheckBox, QScrollArea, QFormLayout, QFrame
)
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QWidget, QGraphicsEllipseItem, QGraphicsScene, QGraphicsView, QGraphicsRectItem
from PySide6.QtGui import QShortcut, QKeySequence, QPixmap, QColor, QPen, QBrush, QImage, QPainter, QIcon
from PySide6.QtCore import Qt, QTimer, QEventLoop, Signal, Slot, QSignalBlocker
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
from datetime import datetime
import cv2
from utilities import ShortcutManager
import CalibrationClasses
import importlib
from typing import Mapping, Sequence, Optional, Any, List, Optional, Tuple, Set
from hardware.profile import CURRENT_PROFILE, HardwareProfile
from legacy.mass_calibration import MassCalibrationDialog

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

        self.setWindowTitle("Droplet Printer Interface")
        self.init_ui()
        self.disconnected = False

        self.controller.error_occurred_signal.connect(self.popup_message)
        self.controller.machine.disconnect_complete_signal.connect(self.disconnect_successful)
        self.controller.update_volumes_in_view_signal.connect(self.rack_box.update_all_slots)
        self.controller.machine.require_gripper_confirmation.connect(self.on_require_gripper_confirmation)

    def load_colors(self, file_path):
        with open(file_path, 'r') as file:
            return json.load(file)

    def init_ui(self):
        """Initialize the main user interface."""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        transparent_icon = self.make_transparent_icon()
        self.setWindowIcon(transparent_icon)

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

        self.shortcut_box = ShortcutTableWidget(self,self.shortcut_manager)
        self.shortcut_box.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        self.shortcut_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        right_layout.addWidget(self.shortcut_box)

        # Add the command queue table to the right panel
        self.command_queue_widget = CommandQueueWidget(self,self.controller.machine)
        right_layout.addWidget(self.command_queue_widget)

        self.layout.addWidget(right_panel)

        # Set the size of the main window to be 90% of the screen size
        screen_geometry = QApplication.primaryScreen().geometry()
        width = int(screen_geometry.width() * 0.9)
        height = int(screen_geometry.height() * 0.9)
        self.resize(width, height)
        

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

        self.shortcut_manager.add_shortcut('Shift+p','Print Array', lambda: self.controller.print_array())
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

    def show_well_plate_tab(self):
        """Switch the center tab widget to the Well Plate tab."""
        if not hasattr(self, "tab_widget") or not hasattr(self, "well_plate_widget"):
            return
        idx = self.tab_widget.indexOf(self.well_plate_widget)
        if idx != -1:
            self.tab_widget.setCurrentIndex(idx)

    def popup_message(self, title, message):
        """Display a popup message with a title and message."""
        #print(f"Popup message: {title} - {message}")
        msg = QtWidgets.QMessageBox()
        msg.setWindowTitle(title)
        msg.setText(message)
        transparent_icon = self.make_transparent_icon()
        msg.setWindowIcon(transparent_icon)
        msg.exec()

    def popup_options(self, title, message, options):
        dialog = OptionsDialog(title, message, options)
        clicked_option = dialog.exec()
        return clicked_option
    
    def popup_yes_no(self,title, message):
        msg = QtWidgets.QMessageBox()
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        transparent_icon = self.make_transparent_icon()
        msg.setWindowIcon(transparent_icon)
        msg.exec()
        return msg.clickedButton().text()
    
    def popup_input(self,title, message):
        text, ok = QtWidgets.QInputDialog.getText(self, title, message)
        if ok:
            return text
        else:
            return None

    def show_calibrations(self):
        """Print all printer head calibrations to terminal."""
        for printer_head in self.model.printer_head_manager.get_all_printer_heads():
            #print(f'Printer Head {printer_head.get_stock_id()}')
            print(printer_head.get_prediction_data())
        
    def reset_single_array(self):
        """Reset a single array."""
        active_printer_head = self.model.rack_model.get_gripper_printer_head()
        if active_printer_head == None:
            self.popup_message('Cannot reset:','Only resets the array for the loaded printer head')
            return
        else:
            response = self.popup_yes_no('Reset Array','Are you sure you want to reset the current array?')
            if response == '&Yes':
                self.controller.reset_single_array()

    def reset_all_arrays(self):
        """Reset all arrays."""
        response = self.popup_yes_no('Reset All Arrays','Are you sure you want to reset all arrays?')
        if response == '&Yes':
            self.controller.reset_all_arrays()
    
    def pause_machine(self):
        """Pause the machine."""
        self.controller.pause_commands()
        response = self.popup_yes_no('Pause','Execution paused. Do you want to resume?')
        if response == '&Yes':
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
        if ansewer == "&Yes":
            self.controller.save_locations()

    def modify_location(self):
        """Modify a saved location."""
        name = self.popup_options("Modify Location","Select a location to modify",self.model.location_model.get_location_names())
        if name is not None:
            self.controller.modify_location(name)
        ansewer = self.popup_yes_no("Write to file","Would you like to write the location to a file?")
        if ansewer == "&Yes":
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

    def complete_experiment_design(self):
        """Handle completion of experiment design."""
        print("[MainWindow] Experiment design completed.")
        self.model.load_experiment_from_model()
    
    def closeEvent(self, event):
        """Handle the window close event."""
        if self.model.machine_model.is_connected():
            response = self.popup_yes_no('Close Application','Disconnect from the machine and close the application?')
            if response == '&No':
                event.ignore()
                return
            else:
                self.controller.disconnect_machine()
                # Create an event loop to wait for the disconnection to complete
                loop = QEventLoop()

                # Temporarily connect the disconnect_complete_signal to the loop.quit() to unblock the close event
                self.controller.machine.disconnect_complete_signal.connect(loop.quit)

                # Run the event loop (non-blocking) until the disconnect is complete
                loop.exec()
                if self.disconnected:
                    print('Disconnected machine')
                else:
                    print('Failed to disconnect the machine')
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
            {"dark_blue": "#1b3a57", "light_blue": "#3b82f6"}
        )
        self.model = model
        self.controller = controller

        # Decide mode from profile (adjust attribute name to your actual profile)
        prof = getattr(self.main_window, "profile", None)
        self.legacy_mode = prof.name == "legacy" if prof else True

        # Defaults
        self.machine_default = self.model.get_default_machine_port()
        self.balance_default = self.model.get_default_balance_port()

        # # Fixed on-board port (e.g., "/dev/ttyACM0" on the Pi)
        # self.fixed_port = self.model.get_default_machine_port()  # must return a string

        self.init_ui()

        # Model → View
        self.model.machine_model.machine_state_updated.connect(
            self.update_machine_connect_button
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
        if self.model.machine_model.machine_connected:
            self.controller.disconnect_machine()
        else:
            self.connect_machine()

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


class PressurePlotBox(QtWidgets.QGroupBox):
    """
    A widget to display the pressure readings and target
    """
    toggle_regulation_requested = QtCore.Signal()
    # update_target_pressure_input = QtCore.Signal(float)
    # update_pulse_width_input = QtCore.Signal(int)
    popup_message_signal = QtCore.Signal(str,str)

    def __init__(self, main_window, model,controller):
        super().__init__('PRESSURE')
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.controller = controller

        prof = getattr(self.main_window, "profile", None)
        self.legacy_mode = prof.name == "legacy" if prof else True


        self.init_ui()
        self.model.machine_model.machine_state_updated.connect(self.update_regulation_button_state)
        self.model.machine_model.regulation_state_changed.connect(self.update_regulation_button)
        self.toggle_regulation_requested.connect(self.controller.toggle_regulation)
        # self.update_target_pressure_input.connect(self.controller.set_absolute_pressure)
        # self.update_pulse_width_input.connect(self.controller.set_pulse_width)

        self.update_regulation_button_state(self.model.machine_model.is_connected())
        self.popup_message_signal.connect(self.main_window.popup_message)

    def init_ui(self):
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout = QtWidgets.QGridLayout(self)

        self.current_print_pressure_label = QtWidgets.QLabel("Print Pressure:")  # Create a new QLabel for the current pressure label
        self.current_print_pressure_value = QtWidgets.QLabel()  # Create a new QLabel for the current pressure value
        self.target_print_pressure_label = QtWidgets.QLabel("Target Print:")  # Create a new QLabel for the target pressure label
        self.target_print_pressure_spinbox = QtWidgets.QDoubleSpinBox()  # Create a new QDoubleSpinBox for the target pressure value
        self.target_print_pressure_spinbox.setDecimals(2)  # Set the number of decimal places to 3
        self.target_print_pressure_spinbox.setSingleStep(0.1)  # Set the step size to 0.001
        self.target_print_pressure_spinbox.setRange(0, 5)  # Set the range of the spinbox to 0-10
        self.target_print_pressure_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.target_print_pressure_spinbox.valueChanged.connect(self.handle_target_print_pressure_change)  # Connect value changes to the update_pressure function

        self.layout.addWidget(self.current_print_pressure_label, 0, 0)  # Add the QLabel to the layout at position (0, 0)
        self.layout.addWidget(self.current_print_pressure_value, 0, 1)  # Add the QLabel to the layout at position (0, 1)
        self.layout.addWidget(self.target_print_pressure_label, 0, 2)  # Add the QLabel to the layout at position (1, 0)
        self.layout.addWidget(self.target_print_pressure_spinbox, 0, 3)  # Add the QDoubleSpinBox to the layout at position (1, 1)

        if not self.legacy_mode:
            self.current_refuel_pressure_label = QtWidgets.QLabel("Refuel Pressure:")  # Create a new QLabel for the current pressure label
            self.current_refuel_pressure_value = QtWidgets.QLabel()  # Create a new QLabel for the current pressure value
            self.target_refuel_pressure_label = QtWidgets.QLabel("Target Refuel:")  # Create a new QLabel for the target pressure label
            self.target_refuel_pressure_spinbox = QtWidgets.QDoubleSpinBox()  # Create a new QDoubleSpinBox for the target pressure value
            self.target_refuel_pressure_spinbox.setDecimals(2)  # Set the number of decimal places to 3
            self.target_refuel_pressure_spinbox.setSingleStep(0.1)  # Set the step size to 0.001
            self.target_refuel_pressure_spinbox.setRange(0, 5)  # Set the range of the spinbox to 0-10
            self.target_refuel_pressure_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
            self.target_refuel_pressure_spinbox.valueChanged.connect(self.handle_target_refuel_pressure_change)  # Connect value changes to the update_pressure function

            self.layout.addWidget(self.current_refuel_pressure_label, 1, 0)  # Add the QLabel to the layout at position (0, 0)
            self.layout.addWidget(self.current_refuel_pressure_value, 1, 1)  # Add the QLabel to the layout at position (0, 1)
            self.layout.addWidget(self.target_refuel_pressure_label, 1, 2)  # Add the QLabel to the layout at position (1, 0)
            self.layout.addWidget(self.target_refuel_pressure_spinbox, 1, 3)  # Add the QDoubleSpinBox to the layout at position (1, 1)


        self.pressure_regulation_button = QtWidgets.QPushButton("Regulate Pressure")
        self.pressure_regulation_button.setFocusPolicy(QtCore.Qt.NoFocus)
        # self.pressure_regulation_button.setCheckable(True)
        self.pressure_regulation_button.clicked.connect(self.request_toggle_regulation)
        self.layout.addWidget(self.pressure_regulation_button, 2, 0, 1, 4)  # Add the button to the layout at position (2, 0) and make it span 2 columns
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
        self.layout.addWidget(self.chart_view, 3, 0,1,4)

        self.calibrate_pressure_button = QtWidgets.QPushButton("Calibrate Pressure")
        self.calibrate_pressure_button.clicked.connect(self.calibrate_pressure)
        self.layout.addWidget(self.calibrate_pressure_button, 4, 0, 1, 2)


        if not self.legacy_mode:
            self.droplet_imager_button = QtWidgets.QPushButton("Imager")
            self.droplet_imager_button.clicked.connect(self.droplet_imager)
            self.layout.addWidget(self.droplet_imager_button, 5, 0, 1, 2)

        self.print_pulse_width_label = QtWidgets.QLabel("Print Pulse Width:")
        self.print_pulse_width_spinbox = QtWidgets.QSpinBox()
        self.print_pulse_width_spinbox.setRange(0, 10000)
        self.print_pulse_width_spinbox.setSingleStep(50)
        self.print_pulse_width_spinbox.setValue(3000)
        self.print_pulse_width_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.print_pulse_width_spinbox.valueChanged.connect(self.handle_print_pulse_width_change)
        self.layout.addWidget(self.print_pulse_width_label,4,2,1,1)
        self.layout.addWidget(self.print_pulse_width_spinbox,4,3,1,1)


        if not self.legacy_mode:
            self.refuel_pulse_width_label = QtWidgets.QLabel("Refuel Pulse Width:")
            self.refuel_pulse_width_spinbox = QtWidgets.QSpinBox()
            self.refuel_pulse_width_spinbox.setRange(0, 10000)
            self.refuel_pulse_width_spinbox.setSingleStep(50)
            self.refuel_pulse_width_spinbox.setValue(3000)
            self.refuel_pulse_width_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
            self.refuel_pulse_width_spinbox.valueChanged.connect(self.handle_refuel_pulse_width_change)
            self.layout.addWidget(self.refuel_pulse_width_label,5,2,1,1)
            self.layout.addWidget(self.refuel_pulse_width_spinbox,5,3,1,1)


        self.model.machine_model.pressure_updated.connect(self.update_pressure)

    def handle_target_print_pressure_change(self, value):
        """Handle changes to the target pressure value."""
        # self.update_target_pressure_input.emit(value)
        self.controller.set_absolute_print_pressure(value,manual=True)

    def handle_target_refuel_pressure_change(self, value):
        """Handle changes to the target pressure value."""
        # self.update_target_pressure_input.emit(value)
        self.controller.set_absolute_refuel_pressure(value,manual=True)

    def handle_print_pulse_width_change(self, value):
        """Handle changes to the pulse width value."""
        # self.update_pulse_width_input.emit(value)
        self.controller.set_print_pulse_width(value,manual=True)
    
    def handle_refuel_pulse_width_change(self, value):
        """Handle changes to the pulse width value."""
        # self.update_pulse_width_input.emit(value)
        self.controller.set_refuel_pulse_width(value,manual=True)

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

        self.target_print_pressure_spinbox.blockSignals(True)  # Block signals temporarily
        self.target_print_pressure_spinbox.setValue(target_print_pressure)
        self.target_print_pressure_spinbox.blockSignals(False)  # Unblock signals

        if not self.legacy_mode:
            self.target_refuel_pressure_spinbox.blockSignals(True)  # Block signals temporarily
            self.target_refuel_pressure_spinbox.setValue(self.model.machine_model.get_target_refuel_pressure())
            self.target_refuel_pressure_spinbox.blockSignals(False)  # Unblock signals

        self.print_pulse_width_spinbox.blockSignals(True)
        self.print_pulse_width_spinbox.setValue(self.model.machine_model.print_pulse_width)
        self.print_pulse_width_spinbox.blockSignals(False)

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
            importlib.reload(CalibrationClasses.View)
            importlib.reload(CalibrationClasses)
            self.model.reload_refuel_model()

            camera_dialog = CalibrationClasses.RefuelCameraWindow(self.main_window,self.model,self.controller)
            camera_dialog.exec()
        else:
            mass_calibration_dialog = MassCalibrationDialog(self.main_window,self.model,self.controller)
            mass_calibration_dialog.exec()
        # droplet_imaging_dialog = DropletImagingDialog(self.main_window,self.model,self.controller)
        # droplet_imaging_dialog.exec()

    def droplet_imager(self):
        """Open the droplet imager dialog."""
        self.controller.disconnect_droplet_camera_signals()
        importlib.reload(CalibrationClasses.View)
        importlib.reload(CalibrationClasses)
        self.model.reload_droplet_model()
        self.controller.connect_droplet_camera_signals()
        self.controller.enable_print_profile()
        droplet_imaging_dialog = CalibrationClasses.DropletImagingDialog(self.main_window,self.model,self.controller)
        droplet_imaging_dialog.exec()

    def print_calibration_droplets(self,num_droplets):
        print('Printing calibration droplets:',num_droplets,self.target_pressure)
        self.controller.print_calibration_droplets(num_droplets,self.target_pressure)

    def calibration_pressure_change(self,pressure):
        print('Pressure changed to:',pressure)
        self.target_pressure = pressure
        self.controller.set_absolute_print_pressure(pressure)

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
        self.model.rack_model.gripper_updated.connect(self.update_start_print_array_button)
        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout()
        self.top_layout = QHBoxLayout()
        self.plate_selection_label = QLabel("Plate Format:")
        self.plate_selection_label.setStyleSheet("color: white;")
        self.plate_selection_label.setAlignment(Qt.AlignRight)
        self.top_layout.addWidget(self.plate_selection_label)
        self.plate_selection = QComboBox()
        all_plate_names = self.model.well_plate.get_all_plate_names()
        self.plate_selection.addItems(all_plate_names)

        # Set the current index to match the model's plate format
        current_plate_name = self.model.well_plate.get_current_plate_name()
        self.plate_selection.setCurrentIndex(self.plate_selection.findText(current_plate_name))
        self.plate_selection.currentIndexChanged.connect(self.on_plate_selection_changed)
        self.top_layout.addWidget(self.plate_selection)
        
        # Create a calibration button
        self.calibration_button = QPushButton("Calibrate Plate", self)
        self.calibration_button.clicked.connect(self.open_calibration_dialog)
        self.top_layout.addWidget(self.calibration_button)
        
        self.bottom_layout = QHBoxLayout()

        self.design_experiment_button = QPushButton("Experiment Editor")
        self.design_experiment_button.clicked.connect(self.open_experiment_designer)
        self.bottom_layout.addWidget(self.design_experiment_button)

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
        self.reagent_selection.addItems(self.model.stock_solutions.get_stock_solution_names_formated())
        self.reagent_selection.currentIndexChanged.connect(self.update_well_colors)
        self.bottom_layout.addWidget(self.reagent_selection)

        self.layout.addLayout(self.top_layout)
        self.layout.addLayout(self.grid_layout)
        self.layout.addLayout(self.bottom_layout)

        self.setLayout(self.layout)
        self.update_grid()

    def update_start_print_array_button(self):
        if self.model.rack_model.gripper_printer_head is not None:
            self.start_print_array_button.setEnabled(True)
            self.start_print_array_button.setStyleSheet(f"background-color: {self.color_dict['dark_blue']}; color: white;")
        else:
            self.start_print_array_button.setEnabled(False)
            self.start_print_array_button.setStyleSheet(f"background-color: {self.color_dict['darker_gray']}; color: white;")

    def start_print_array(self):
        if not self.controller.check_if_all_completed():
            return
        response = self.main_window.popup_yes_no("Start Print Array","Are you sure you want to start the print array?")
        if response == "&Yes":
            self.controller.print_array()
        else:
            return

    def update_grid(self):
        """Update the grid layout to match the selected plate format."""
        self.grid_layout.setSpacing(1)
        self.clear_grid()

        rows, cols = self.model.well_plate.get_plate_dimensions()
        self.well_labels = [[QLabel() for _ in range(cols)] for _ in range(rows)]

        for row in range(rows):
            for col in range(cols):
                label = QLabel()
                label.setStyleSheet("border: 0.5px solid black; border-radius: 4px;")
                label.setAlignment(Qt.AlignCenter)
                self.grid_layout.addWidget(label, row, col)
                self.well_labels[row][col] = label

    def gripper_update_handler(self):
        """Handle when the gripper picks up a new printer head."""
        if self.model.rack_model.gripper_printer_head is not None:
            printer_head = self.model.rack_model.gripper_printer_head
            stock_name = printer_head.get_stock_name(new_line=False)
            self.reagent_selection.setCurrentIndex(self.reagent_selection.findText(stock_name))
            self.update_well_colors()            
    
    def update_well_colors(self):
        """Update the colors of the wells based on the selected reagent's concentration."""
        if not self.model.reaction_collection.is_empty():
            # Get the current reagent selection
            stock_index = self.reagent_selection.currentIndex()
            stock_formatted = self.reagent_selection.itemText(stock_index)
            stock_id = self.model.stock_solutions.get_stock_id_from_formatted(stock_formatted)
            #print(f"Stock ID: {stock_id}, Stock Index: {stock_index}, Stock Formatted: {stock_formatted}")
            if stock_id == None:
                print('No reagent selected')
                stock_id = self.model.stock_solutions.get_stock_solution_names()[0]
                stock_formatted = self.model.stock_solutions.get_formatted_from_stock_id(stock_id)
                self.reagent_selection.setCurrentIndex(self.reagent_selection.findText(stock_formatted))
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
            else:
                self.well_labels[well.row_num][well.col-1].setStyleSheet(f"background-color: none; border: 1px solid black;")


    def clear_grid(self):
        """Clear the existing grid."""
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def on_plate_selection_changed(self):
        """Handle plate selection changes."""
        previous_plate_format = self.model.well_plate.get_current_plate_name()
        plate_format = self.plate_selection.currentText()
        if self.model.rack_model.gripper_printer_head is not None:
            self.main_window.popup_message("Printer Head Loaded", "Please place the printer head back in the rack before changing out plates.")
            self.plate_selection.blockSignals(True)  # Block signals temporarily
            self.plate_selection.setCurrentIndex(self.plate_selection.findText(previous_plate_format))
            self.plate_selection.blockSignals(False)  # Unblock signals
            return
        if not self.model.reaction_collection.is_empty():
            response = self.main_window.popup_yes_no("Plate Selection", "Changing the plate format will clear the current experiment. Are you sure you want to continue?")
            if response == "&No":
                self.plate_selection.blockSignals(True)  # Block signals temporarily
                self.plate_selection.setCurrentIndex(self.plate_selection.findText(previous_plate_format))
                self.plate_selection.blockSignals(False)  # Unblock signals
                return
            else:
                # self.model.clear_experiment()
                # self.model.reload_experiment(plate_name=plate_format)
                self.model.load_experiment_from_model(plate_name=plate_format)
        else:
            self.model.well_plate.set_plate_format(plate_format)
    
    def on_experiment_loaded(self):
        """Handle the experiment loaded signal."""
        # Update the options in the reagent selection combobox
        self.reagent_selection.clear()
        self.reagent_selection.addItems(self.model.stock_solutions.get_stock_solution_names_formated())
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
            if response == "&No":
                return
        self.controller.move_to_location('plate',z_offset=500)
        plate_calibration_dialog = PlateCalibrationDialog(self.main_window,self.model,self.controller)
        
        # Execute the dialog and check if the user completes the calibration
        if plate_calibration_dialog.exec() == QDialog.Accepted:
            print("Calibration completed successfully.")
            self.model.well_plate.update_calibration_data()
            self.model.location_model.post_calibration_update(self.model.well_plate.calibrations['top_left'])

        else:
            print("Calibration was canceled or failed.")
            self.model.well_plate.discard_temp_calibrations()

    def open_experiment_designer(self):
        # dialog = ExperimentDesignDialog(self.main_window, self.model)
        dialog = ExperimentDesignDialog(self.model.experiment_model,self.main_window)
        if dialog.exec():
            print("Experiment file generated and loaded.")

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

        layout.addWidget(fw_group, row_after_table + 1, 0, 1, 3)

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
        layout.addWidget(self.reset_mcu_button, row_after_table + 2, 0, 1, 3)

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
        layout.addWidget(self.tasks_group, row_after_table + 3, 0, 1, 3)

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
        layout.addWidget(self.logs_group, row_after_table + 4, 0, 1, 3)          # NEW

        # Optional style
        self.logs_group.setStyleSheet(                                           # NEW
            f"QGroupBox {{ color: #DDD; border: 1px solid #444; margin-top: 6px; }}"
            f"QTableWidget {{ background-color: {self.color_dict['darker_gray']}; }}"
        )

        # Stretch/spacer row so everything stays at the top
        last_row = row_after_table + 5   # after logs_group                      # CHANGED
        spacer = QtWidgets.QSpacerItem(
            0, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding
        )
        layout.addItem(spacer, last_row, 0, 1, 4)
        layout.setRowStretch(last_row, 1)

        # Stretch/spacer row so everything stays at the top
        last_row = len(self._axis_rows) + 4  # header(0) + data rows
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
            if response != "&Yes":
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
    def _on_reset_mcu_requested(self):
        # Confirm with the user
        response = self.main_window.popup_yes_no("Reset MCU","Are you sure you want to reset the microcontroller unit (MCU)? This will interrupt any ongoing operations.")
        if response == "&Yes":
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
                    if selected_text == f"{printer_head.get_stock_name()}":
                        self.controller.swap_printer_head(slot_number, printer_head)
                        self.update_all_slots()  # Update all dropdowns after swapping
                        self.update_unassigned_printer_heads()  # Update the table to reflect the change
                        return

                # Check if the selected printer head is in another slot
                for i, slot in enumerate(self.rack_model.slots):
                    if i != slot_number and slot.printer_head:
                        slot_text = f"Slot {i+1}: {slot.printer_head.get_stock_name()}"
                        if selected_text == slot_text:
                            self.controller.swap_printer_heads_between_slots(slot_number, i)
                            self.update_all_slots()  # Update all dropdowns after swapping
                            self.update_unassigned_printer_heads()  # Update the table to reflect the change
                            return
        return swap_printer_head
    
    def update_all_slots(self):
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
            label.setText(f"{printer_head.get_stock_name(new_line=True)}")
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
            dropdown.addItem(printer_head.get_stock_name())

        # Add all printer heads in other slots
        for i, slot in enumerate(self.rack_model.get_all_slots()):
            if i != slot_number and slot.printer_head:
                dropdown.addItem(f"Slot {i+1}: {slot.printer_head.get_stock_name()}")
        
        dropdown.blockSignals(False)

    def update_gripper(self):
        """Update the UI when the gripper state changes."""
        if self.rack_model.gripper_printer_head:
            printer_head = self.rack_model.gripper_printer_head
            self.gripper_label.setText(f"{printer_head.get_stock_name(new_line=True)}")
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
            reagent_name = printer_head.get_reagent_name()
            concencentration = printer_head.get_stock_concentration()
            if not printer_head.is_calibration_chip():
                complete = printer_head.check_complete(self.model.well_plate)
            else:
                complete = True
            color = printer_head.get_color()
            color = QtGui.QColor(color)
            color.setAlphaF(0.5)

            text_name = f"{reagent_name} - {concencentration} M"
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

        if self.legacy_mode:
            self.labels['Mass'].setText(str(self.model.calibration_model.get_current_mass()))
            self.labels['Stable'].setText(str(self.model.calibration_model.is_mass_stable()))

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
                self.set_row_color(row_position, self.color_dict['darker_gray'])  # Dark grey
            elif command.status == "Sent":
                self.set_row_color(row_position, self.color_dict['mid_gray'])  # Light grey
            elif command.status == "Executing":
                self.set_row_color(row_position, self.color_dict['dark_red'])  # Red
            elif command.status == "Completed":
                self.set_row_color(row_position, self.color_dict['darker_gray'])  # Black

    def set_row_color(self, row, color):
        """Set the background color for a row."""
        for column in range(self.table.columnCount()):
            self.table.item(row, column).setBackground(QtGui.QColor(color))
        

class ExperimentDesignDialog(QDialog):
    """
    UI for composing reagents (additives and choice groups), optimizing stock solutions,
    and generating the design using ExperimentModelV2.
    """

    GROUP_ADDITIVE = "Additive"
    GROUP_NEW = "New choice group…"

    COL_REAGENT_NAME = 0
    COL_GROUP        = 1
    COL_STARTING     = 2
    COL_TARGETS      = 3
    COL_UNITS        = 4
    COL_SET_STOCK    = 5
    COL_DROPLET      = 6
    COL_DELETE       = 7

    def __init__(self, model: ExperimentModel, main_window):
        super().__init__()
        self.main_window = main_window
        self.color_dict = getattr(
            self.main_window, "color_dict",
            {"dark_red": "#8a0303","blue": "#1e64b4","dark_blue": "#1b3a57", "light_blue": "#3b82f6"}
        )
                
        prof = getattr(self.main_window, "profile", None)
        self.legacy_mode = prof.name == "legacy" if prof else True

        if self.legacy_mode:
            self.default_droplet_volume_nL = 40.0
        else:
            self.default_droplet_volume_nL = 10.0

        self.setWindowTitle("Experiment Design (v2)")
        self.setMinimumSize(1440, 820)

        self.model: ExperimentModel = model
        self.choice_groups: Set[str] = set(
            f.name for f in getattr(self.model, "factors", []) if getattr(f, "kind", "") == "choice"
        )

        # Uploaded design UI state
        self._uploaded_design_active: bool = bool(self.model.has_uploaded_design())
        self._uploaded_design_path: str | None = getattr(self.model, "_uploaded_design_source", None)


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
        self.reagent_table = QTableWidget(0, 8, self)
        self.reagent_table.setHorizontalHeaderLabels([
            "Reagent Name", "Group", "Starting", "Targets", "Units", "Set Stock Conc", "Droplet Vol (nL)", "Delete"
        ])
        self.reagent_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.reagent_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.reagent_table.setColumnWidth(0, 200)   # Reagent Name (wider)
        self.reagent_table.setColumnWidth(1, 150)   # Group
        self.reagent_table.setColumnWidth(2, 90)   # Starting
        self.reagent_table.setColumnWidth(3, 230)   # Targets (wider)
        self.reagent_table.setColumnWidth(4, 90)    # Units
        self.reagent_table.setColumnWidth(5, 120)   # Set Stock Conc
        self.reagent_table.setColumnWidth(6, 90)    # Droplet vol
        self.reagent_table.setColumnWidth(7, 90)    # Delete
        right.addWidget(self.reagent_table)

        # ---------- Stock table (bottom-right) ----------
        # Add "Max / Rxn (nL)" column
        self.stock_table = QTableWidget(0, 9, self)
        self.stock_table.setHorizontalHeaderLabels([
            "Factor/Group", "Option", "Stock Conc", "Δ per drop",
            "Units", "Drop Vol (nL)", "Max / Rxn (nL)", "Total Drops", "Total Vol (µL)"
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

        # Fill reagent name
        self.fill_name_edit = QLineEdit(self.model.metadata.get("fill_reagent_name", "Water"))
        form.addRow(QLabel("Fill Reagent Name"), self.fill_name_edit)

        # Fill droplet volume
        self.fill_dv_spin = QDoubleSpinBox()
        self.fill_dv_spin.setDecimals(1)
        self.fill_dv_spin.setRange(0.1, 100_000.0)
        self.fill_dv_spin.setSingleStep(1.0)
            
        self.fill_dv_spin.setValue(float(self.model.metadata.get("fill_droplet_volume_nL", self.default_droplet_volume_nL)))
        form.addRow(QLabel("Fill Droplet Vol (nL)"), self.fill_dv_spin)

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

        self.run_btn = new_btn = QPushButton("Optimize and Generate")
        # self.run_btn.setStyleSheet("background-color: #b33; color: white;")
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
            self._on_optimize_and_generate()
        self.randomize_chk.stateChanged.connect(_auto_update)
        self.random_seed_spin.valueChanged.connect(_auto_update)
        self.subset_chk.stateChanged.connect(_auto_update)
        self.reduction_spin.valueChanged.connect(_auto_update)
        self.start_col_spin.valueChanged.connect(_auto_update)
        self.start_row_spin.valueChanged.connect(_auto_update)

        self.exp_name_edit.textChanged.connect(self._schedule_auto_update)
        self.rep_spin.valueChanged.connect(self._schedule_auto_update)
        self.v_spin.valueChanged.connect(self._schedule_auto_update)
        self.final_v_spin.valueChanged.connect(self._schedule_auto_update)
        self.fill_name_edit.textChanged.connect(self._schedule_auto_update)
        self.fill_dv_spin.valueChanged.connect(self._schedule_auto_update)

        # ---- Model hooks & initial render ----
        self.model.stock_updated.connect(self._refresh_stock_table)
        self.model.experiment_generated.connect(self._on_experiment_generated)

        self._load_factors_into_table()
        self._refresh_stock_table()
        self._update_summary_labels(initial=True)
        self._apply_uploaded_design_mode_to_ui(active=self._uploaded_design_active)
        # Also enforce manual-assignment locking if applicable
        self._apply_manual_assignment_lock_state()


    # -----------------------------
    # Table row utilities
    # -----------------------------

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
        for row in range(self.reagent_table.rowCount()):
            c: QComboBox = self.reagent_table.cellWidget(row, 1)
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
                        forced_stock_conc: float | None = None):
        row = self.reagent_table.rowCount()
        self.reagent_table.insertRow(row)

        # 0 Name
        name_edit = QLineEdit(name or f"reagent-{row+1}")
        name_edit.textEdited.connect(self._schedule_auto_update)
        self.reagent_table.setCellWidget(row, 0, name_edit)

        # 1 Group
        group_combo = self._make_group_combo()
        group_combo.setCurrentIndex(
            group_combo.findText(group if group in self.choice_groups or group == self.GROUP_ADDITIVE
                                else self.GROUP_ADDITIVE)
        )
        group_combo.activated.connect(self._schedule_auto_update)
        self.reagent_table.setCellWidget(row, 1, group_combo)

        # 2 Starting concentration
        start_spin = QDoubleSpinBox()
        start_spin.setDecimals(4)
        start_spin.setRange(0.0, 1e12)
        start_spin.setSingleStep(0.1)
        start_spin.setValue(float(starting_conc or 0.0))
        start_spin.valueChanged.connect(self._schedule_auto_update)
        self.reagent_table.setCellWidget(row, 2, start_spin)

        # 3 Targets
        tgt_edit = QLineEdit(targets)
        tgt_edit.textEdited.connect(self._schedule_auto_update)
        self.reagent_table.setCellWidget(row, 3, tgt_edit)

        # 4 Units
        units_edit = QLineEdit(units)
        units_edit.textEdited.connect(self._schedule_auto_update)
        self.reagent_table.setCellWidget(row, 4, units_edit)

        # 5 Set Stock Conc (blank => optimize)
        stock_edit = QLineEdit("" if forced_stock_conc in (None, 0.0) else str(forced_stock_conc))
        stock_edit.setPlaceholderText("auto")
        stock_edit.setToolTip("Leave blank to auto-optimize. Enter a positive number to force the stock concentration.")
        stock_edit.textEdited.connect(self._schedule_auto_update)
        self.reagent_table.setCellWidget(row, 5, stock_edit)

        # 6 Droplet vol
        dv_spin = QDoubleSpinBox()
        dv_spin.setDecimals(1)
        dv_spin.setRange(0.1, 100_000.0)
        dv_spin.setSingleStep(1.0)
        dv_spin.setValue(float(droplet_nL))
        dv_spin.valueChanged.connect(self._schedule_auto_update)
        self.reagent_table.setCellWidget(row, 6, dv_spin)

        # 7 Delete
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(lambda _, r=row: self._delete_row(r))
        self.reagent_table.setCellWidget(row, 7, del_btn)

        self._schedule_auto_update()

    def _delete_row(self, r: int):
        self.reagent_table.removeRow(r)
        for i in range(self.reagent_table.rowCount()):
            btn: QPushButton = self.reagent_table.cellWidget(i, 7)  # delete is col 7 now
            try:
                btn.clicked.disconnect()
            except Exception:
                pass
            btn.clicked.connect(lambda _, rr=i: self._delete_row(rr))
        self._schedule_auto_update()

    def _schedule_auto_update(self):
        # Debounce rapid edits
        self._auto_timer.start()

    def _recompute_silent(self):
        # push UI -> model
        self._rebuild_model_from_table()
        self._update_metadata_from_controls()

        # Try optimize/generate without popping dialogs on failure (user may be mid-edit)
        res = self.model.optimize_stock_solutions(
            quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True
        )
        if not res.get("best"):
            # keep the stock table as-is; summary shows last successful run
            return

        self.model.generate_experiment()
        self._refresh_stock_table()
        self._update_summary_labels()
        self._apply_target_color_state()

    def _load_factors_into_table(self):
        """Populate the reagent table from the model's current factors (if any)."""
        self.reagent_table.setRowCount(0)
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
                    forced_stock_conc=getattr(o, "forced_stock_conc", None)
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
                        forced_stock_conc=getattr(o, "forced_stock_conc", None)
                    )
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
        #    - Reagent Name (0)
        #    - Group (1)
        #    - Targets (3)
        #    - Units (4)
        #    - Delete (7)
        #
        #  Keep editable:
        #    - Starting (2)
        #    - Set Stock Conc (5)
        #    - Droplet Vol (6)
        #
        lock_cols = {
            self.COL_REAGENT_NAME,
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
        self._apply_manual_assignment_lock_state()

    def _on_upload_design(self):
        """
        Let user pick a CSV containing explicit reactions.
        Each column is a reagent final concentration; each row is a reaction.
        """
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

        # Push into the model – this will rebuild factors and uploaded reactions.
        # We default to same droplet volume and units assumptions used elsewhere.
        self.model.set_uploaded_design_from_dataframe(
            df,
            units_default="",                    # user units come from header; blank defaults to "arb"
            droplet_nL_default=10.0,
            starting_conc_default=0.0,
            source_path=path,
        )

        # Update local flags
        self._uploaded_design_active = True
        self._uploaded_design_path = path

        # Rebuild UI from the model's new factors
        self.choice_groups = set(
            f.name for f in getattr(self.model, "factors", []) if getattr(f, "kind", "") == "choice"
        )
        self._load_factors_into_table()

        # Immediately optimize & generate using the uploaded design
        res = self.model.optimize_stock_solutions(
            quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True
        )
        if not res.get("best"):
            QMessageBox.warning(
                self,
                "Optimization failed",
                f"Could not find feasible stock solutions for the uploaded design:\n{res.get('reason','Unknown')}"
            )
            # Keep the design for inspection, but stock table may be empty.
        else:
            self.model.generate_experiment()

        self._refresh_stock_table()
        self._update_summary_labels()
        self._apply_target_color_state()
        self._apply_uploaded_design_mode_to_ui(active=True)

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

        # Re-optimize and generate in standard mode
        res = self.model.optimize_stock_solutions(
            quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True
        )
        if res.get("best"):
            self.model.generate_experiment()

        self._refresh_stock_table()
        self._update_summary_labels()
        self._apply_target_color_state()
        self._apply_uploaded_design_mode_to_ui(active=False)

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
        
    def _rebuild_model_from_table(self):
        """Clear and rebuild factors in the model based on the table."""
        self.model.factors.clear()
        created_choice_groups: Set[str] = set()

        for row in range(self.reagent_table.rowCount()):
            name_edit: QLineEdit = self.reagent_table.cellWidget(row, 0)
            group_combo: QComboBox = self.reagent_table.cellWidget(row, 1)
            start_spin: QDoubleSpinBox = self.reagent_table.cellWidget(row, 2)
            tgt_edit: QLineEdit = self.reagent_table.cellWidget(row, 3)
            units_edit: QLineEdit = self.reagent_table.cellWidget(row, 4)
            stock_edit: QLineEdit = self.reagent_table.cellWidget(row, 5)
            dv_spin: QDoubleSpinBox = self.reagent_table.cellWidget(row, 6)

            r_name = (name_edit.text() or "").strip()
            r_group = group_combo.currentText()
            r_start = float(start_spin.value() if start_spin is not None else 0.0)
            r_targets = self._parse_targets(tgt_edit.text())
            r_units = (units_edit.text() or "mM").strip()
            r_forced = self._parse_float_or_none(stock_edit.text())
            r_dv = float(dv_spin.value())

            if not r_name or not r_targets:
                continue

            if r_group == self.GROUP_ADDITIVE:
                self.model.add_additive(name=r_name, targets=r_targets,
                                        units=r_units, droplet_nL=r_dv,
                                        starting_conc=r_start,
                                        forced_stock_conc=r_forced)
            else:
                if r_group not in created_choice_groups:
                    self.model.add_choice_group(r_group)
                    created_choice_groups.add(r_group)
                self.model.add_choice_option(group_name=r_group, option_name=r_name,
                                            targets=r_targets, units=r_units, droplet_nL=r_dv,
                                            starting_conc=r_start,
                                            forced_stock_conc=r_forced)
        
    def _update_metadata_from_controls(self):
        # If randomize is checked and no seed yet, create a fresh one
        randomize = self.randomize_chk.isChecked()
        seed = int(self.random_seed_spin.value())

        self.model.set_metadata(
            name=self.exp_name_edit.text().strip() or "Untitled",
            replicates=int(self.rep_spin.value()),
            target_reaction_volume_nL=float(self.v_spin.value()),
            fill_reagent_name=self.fill_name_edit.text().strip() or "Water",
            fill_droplet_volume_nL=float(self.fill_dv_spin.value()),
            final_reaction_volume_nL=float(self.final_v_spin.value()),
            randomize_assignments=randomize,
            random_seed=(seed if randomize else None),
            use_subset_design=bool(self.subset_chk.isChecked()),
            reduction_factor=int(self.reduction_spin.value()) if self.subset_chk.isChecked() else 1,
            start_col=int(self.start_col_spin.value()),
            start_row=int(self.start_row_spin.value()),
        )
        print(f"[ExperimentDesignDialog] metadata updated: {self.model.metadata}")

    # -----------------------------
    # Actions
    # -----------------------------

    def _on_add_reagent(self):
        # Default to Additive (per your request)
        self._add_reagent_row(group=self.GROUP_ADDITIVE, droplet_nL=self.default_droplet_volume_nL)

    def _on_optimize_and_generate(self):
        # push UI -> model
        self._rebuild_model_from_table()
        self._update_metadata_from_controls()

        # Optimize (prefers fewest stocks, then min conc, then min volume)
        res = self.model.optimize_stock_solutions(
            quantum=0.1,      # supports fractional step sizes like 0.2, 0.5, etc.
            max_refine=60,    # search more single-stock steps if you wish
            two_max_refine=40,
            allow_two=True    # enable two-stock fallback where needed
        )
        if not res.get("best"):
            QMessageBox.warning(self, "Optimization failed", res.get("reason", "Unknown error"))
            return

        # Generate reactions, totals, and fill usage
        self.model.generate_experiment()
        # UI updates come from signals; but we also force a local refresh
        self._refresh_stock_table()
        self._update_summary_labels()
        self._apply_target_color_state()

    def _apply_target_color_state(self):
        """
        Colors each Targets cell red if a forced stock exists and at least one target is unreachable
        for that reagent (based on the model's preview map). Also sets a helpful tooltip.
        """
        preview = {}
        target_preview = {}
        try:
            preview = self.model.get_unreachable_preview_map() or {}
        except Exception:
            preview = {}
        try:
            target_preview = self.model.get_target_preview_map() or {}
        except Exception:
            target_preview = {}

        def _fmt_value(val: float) -> str:
            val = float(val)
            if abs(val) >= 0.001:
                txt = f"{val:.3f}"
                txt = txt.rstrip("0").rstrip(".")
                if "." not in txt:
                    txt += ".0"
                return txt
            return f"{val:.6g}"

        def _fmt_signed(val: float) -> str:
            val = float(val)
            if abs(val) < 5e-4:
                return "+0.0"
            txt = f"{val:+.3f}"
            txt = txt.rstrip("0").rstrip(".")
            if "." not in txt:
                txt += ".0"
            return txt

        def _reason_text(reason: str) -> str:
            if reason == "rounds_to_zero_drops":
                return "positive targets may not round to zero"
            if reason == "outside_half_step":
                return "outside half-step tolerance"
            if reason == "invalid_delta":
                return "invalid stock or volume"
            return reason.replace("_", " ")

        def _build_tooltip(rows: List[dict]) -> str:
            if not rows:
                return ""

            stock_conc = rows[0].get("stock_concentration", 0.0)
            units = rows[0].get("units", "") or ""
            header_units = f" {units}" if units else ""
            lines = [f"Achievable with forced stock {_fmt_value(stock_conc)}{header_units}:"]

            unreachable_rows = []
            for row in rows:
                req = _fmt_value(row.get("requested_final", 0.0))
                achieved = _fmt_value(row.get("achieved_final", 0.0))
                drops = int(row.get("droplets", 0))
                signed = _fmt_signed(row.get("signed_error", 0.0))
                line = f"{req} -> {achieved} ({drops} drops, {signed})"
                if row.get("reachable", False):
                    lines.append(line)
                else:
                    unreachable_rows.append(f"{line}; {_reason_text(str(row.get('reason', 'unreachable')))}")

            if unreachable_rows:
                lines.append("")
                lines.append("Unreachable:")
                lines.extend(unreachable_rows)

            return "\n".join(lines)

        for row in range(self.reagent_table.rowCount()):
            name_edit: QLineEdit = self.reagent_table.cellWidget(row, 0)
            group_combo: QComboBox = self.reagent_table.cellWidget(row, 1)
            stock_edit: QLineEdit = self.reagent_table.cellWidget(row, 5)
            tgt_edit: QLineEdit = self.reagent_table.cellWidget(row, 3)

            reagent_name = (name_edit.text() or "").strip()
            group_name = group_combo.currentText()

            # If no forced stock, clear any styling
            if not (stock_edit.text() or "").strip():
                tgt_edit.setStyleSheet("")
                tgt_edit.setToolTip("")
                continue

            # Map to key used by the model
            key = (reagent_name, None) if group_name == self.GROUP_ADDITIVE else (group_name, reagent_name)
            tooltip_rows = target_preview.get(key, [])
            unreachable = preview.get(key, [])

            if unreachable:
                tgt_edit.setStyleSheet("color: %s;" % self.color_dict.get("dark_red", "#8a0303"))
                tgt_edit.setToolTip(_build_tooltip(tooltip_rows))
            else:
                tgt_edit.setStyleSheet("")
                tgt_edit.setToolTip(_build_tooltip(tooltip_rows))

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
            self.stock_table.setItem(rr, 2, QTableWidgetItem(self._fmt_num(r.get("stock_concentration", ""))))
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

    def _update_summary_labels(self, initial: bool = False, total_reactions: int | None = None, worst_nonfill_nL: float | None = None):
        if total_reactions is None:
            df = self.model.get_reactions_dataframe()
            total_reactions = len(df)
        if worst_nonfill_nL is None:
            worst_nonfill_nL = self.model.get_worst_nonfill_volume_nL() or 0.0

        self.summary_lbl.setText(
            f"Summary: Total reactions = {total_reactions}  |  "
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
        blk(self.fill_name_edit); blk(self.fill_dv_spin)
        blk(self.randomize_chk); blk(self.random_seed_spin)
        blk(self.subset_chk); blk(self.reduction_spin)
        blk(self.start_col_spin); blk(self.start_row_spin)

        self.exp_name_edit.setText(md.get("name", "Untitled"))
        self.rep_spin.setValue(int(md.get("replicates", 1)))
        self.v_spin.setValue(float(md.get("target_reaction_volume_nL", 500.0)))
        self.fill_name_edit.setText(md.get("fill_reagent_name", "Water"))
        self.fill_dv_spin.setValue(float(md.get("fill_droplet_volume_nL", 10.0)))
        self.final_v_spin.setValue(float(md.get(
            "final_reaction_volume_nL",
            md.get("target_reaction_volume_nL", 500.0)
        )))

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
                    "fill_reagent_name": "Water",
                    "fill_droplet_volume_nL": 10.0,
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

        # Repaint UI from the fresh model (avoid auto-update churn while setting)
        blockers = [
            QSignalBlocker(self.exp_name_edit), QSignalBlocker(self.rep_spin),
            QSignalBlocker(self.v_spin), QSignalBlocker(self.fill_name_edit),
            QSignalBlocker(self.fill_dv_spin), QSignalBlocker(self.randomize_chk),
            QSignalBlocker(self.random_seed_spin), QSignalBlocker(self.subset_chk),
            QSignalBlocker(self.reduction_spin), QSignalBlocker(self.start_col_spin),
            QSignalBlocker(self.start_row_spin)
        ]

        self.choice_groups = set()
        self._load_factors_into_table()
        self._sync_controls_from_model()
        self._refresh_stock_table()
        self._update_summary_labels()

        self._set_status(f"New experiment created: {getattr(self.model, 'experiment_dir_path', '(unsaved yet)')}")

    def _on_save_design(self):
        """
        Save the current design (factors + metadata) to Experiments/<name>/experiment_design.json.
        If needed, optimize/generate so stock table is fresh in the preview.
        """
        # Push UI -> model
        self._rebuild_model_from_table()
        self._update_metadata_from_controls()

        # Keep tables in sync locally
        res = self.model.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)
        if not res.get("best"):
            QMessageBox.warning(self, "Optimization failed", res.get("reason", "Unknown error"))
            return
        self.model.generate_experiment()
        self._refresh_stock_table()
        self._update_summary_labels()

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

        # Load into the model (recomputes optimization + grid)
        self.model.load_experiment(path, exp_dir)

        # After loading, refresh uploaded-design UI state
        self._uploaded_design_active = self.model.has_uploaded_design()
        self._uploaded_design_path = getattr(self.model, "_uploaded_design_source", None)
        self._apply_uploaded_design_mode_to_ui(active=self._uploaded_design_active)

        # Repaint UI from model
        self.choice_groups = set(
            f.name for f in getattr(self.model, "factors", []) if getattr(f, "kind", "") == "choice"
        )
        self._load_factors_into_table()
        self._sync_controls_from_model()
        self._refresh_stock_table()
        self._update_summary_labels()

        self._set_status(f"Design loaded from: {exp_dir}")

    def _on_finish(self):
        """
        Optimize & generate, save the design (creating/renaming the folder if needed),
        then close the dialog. Your existing closeEvent handoff will populate the rest
        of the app (load_experiment_from_model).
        """
        # Reuse the same logic as Optimize & Generate
        self._on_optimize_and_generate()

        # Ensure the folder exists and save the design itself
        self._ensure_experiment_dir()
        self.model.save_experiment()

        self._set_status("Design finalized and saved. Closing…")

        # Propogate the experiment to the main window
        try:
            print("[ExperimentDesignDialog] attempting closeEvent handoff to parent")
            if self.main_window is not None and hasattr(self.main_window, "complete_experiment_design"):
                print("[ExperimentDesignDialog] handing off to main_window")
                self.main_window.complete_experiment_design()
        except Exception as e:
            print(f"[ExperimentDesignDialog] closeEvent handoff error: {e}")

        # Close; your closeEvent wiring can then call model.load_experiment_from_model()
        self.accept()

    def _set_status(self, msg: str):
        self.status_lbl.setToolTip(msg)
        self.status_lbl.setText(msg)

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
        When the dialog closes, make sure the model is up-to-date and hand off to the main window.
        """
        print("[ExperimentDesignDialog] closeEvent triggered")
        # Ensure latest edits are reflected in the model and a design exists
        try:
            # Debounced path might be pending; force a final recompute
            self._recompute_silent()
        except Exception:
            pass

        # Call parent window's handler if available
        try:
            print("[ExperimentDesignDialog] attempting closeEvent handoff to parent")
            if self.main_window is not None and hasattr(self.main_window, "complete_experiment_design"):
                print("[ExperimentDesignDialog] handing off to main_window")
                self.main_window.complete_experiment_design()
        except Exception as e:
            print(f"[ExperimentDesignDialog] closeEvent handoff error: {e}")

        super().closeEvent(event)
