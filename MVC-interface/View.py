from PySide6 import QtCore, QtWidgets, QtGui, QtCharts
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QGridLayout, QGroupBox, QPushButton, QComboBox, QSpinBox, QSizePolicy,
    QSpacerItem, QFileDialog, QInputDialog, QMessageBox, QAbstractItemView, QDialog,QLineEdit,QDoubleSpinBox
)
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QWidget, QGraphicsEllipseItem, QGraphicsScene, QGraphicsView, QGraphicsRectItem
from PySide6.QtGui import QShortcut, QKeySequence, QPixmap, QColor, QPen, QBrush
from PySide6.QtCore import Qt, QTimer, QEventLoop
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import numpy as np
import json
import os
import random
import time
import shutil

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

class ShortcutManager:
    """Manage application shortcuts and their descriptions."""
    def __init__(self, parent):
        self.parent = parent
        self.shortcuts = []

    def add_shortcut(self, key_sequence, description, callback):
        """Add a shortcut to the application and store its description."""
        shortcut = QShortcut(QKeySequence(key_sequence), self.parent, activated=callback)
        self.shortcuts.append((key_sequence, description))
        return shortcut

    def get_shortcuts(self):
        """Return a list of shortcuts and their descriptions."""
        return self.shortcuts

class MainWindow(QMainWindow):
    def __init__(self, model, controller):
        super().__init__()
        self.model = model
        self.controller = controller
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
        left_panel.setFixedWidth(350)
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
        mid_panel.setFixedWidth(800)
        mid_panel.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        mid_layout = QtWidgets.QVBoxLayout(mid_panel)

        tab_widget = QtWidgets.QTabWidget()
        tab_widget.setFocusPolicy(QtCore.Qt.NoFocus)

        self.well_plate_widget = WellPlateWidget(self,self.model, self.controller)
        self.well_plate_widget.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        tab_widget.addTab(self.well_plate_widget, "Well Plate")

        self.movement_box = MovementBox(self, self.model, self.controller)
        self.movement_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        tab_widget.addTab(self.movement_box, "MOVEMENT")
        mid_layout.addWidget(tab_widget)

        self.rack_box = RackBox(self,self.model,self.controller)
        self.rack_box.setFixedHeight(250)
        self.rack_box.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        mid_layout.addWidget(self.rack_box)

        self.layout.addWidget(mid_panel)

        # Add other widgets to the right panel as needed
        right_panel = QtWidgets.QWidget()
        right_panel.setFixedWidth(350)
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

        self.shortcut_manager.add_shortcut('1','Set pulse width to 4200', lambda: self.controller.set_pulse_width(4200,manual=True))
        self.shortcut_manager.add_shortcut('5','Set pressure to 0', lambda: self.controller.set_absolute_pressure(0,manual=True))
        self.shortcut_manager.add_shortcut('6','Large pressure decrease', lambda: self.controller.set_relative_pressure(-1,manual=True))
        self.shortcut_manager.add_shortcut('7','Small pressure decrease', lambda: self.controller.set_relative_pressure(-0.1,manual=True))
        self.shortcut_manager.add_shortcut('8','Small pressure increase', lambda: self.controller.set_relative_pressure(0.1,manual=True))
        self.shortcut_manager.add_shortcut('9','Large pressure increase', lambda: self.controller.set_relative_pressure(1,manual=True))
        self.shortcut_manager.add_shortcut('0','Set pressure to 2.5', lambda: self.controller.set_absolute_pressure(2.5,manual=True))

        # self.shortcut_manager.add_shortcut('Shift+s','Save new location', lambda: self.add_new_location())
        self.shortcut_manager.add_shortcut('Shift+d','Modify location', lambda: self.modify_location())
        self.shortcut_manager.add_shortcut('l','Move to location', lambda: self.move_to_location(manual=True))
    
        self.shortcut_manager.add_shortcut('g','Close gripper', lambda: self.controller.close_gripper())
        self.shortcut_manager.add_shortcut('Shift+g','Open gripper', lambda: self.controller.open_gripper())

        self.shortcut_manager.add_shortcut('Shift+p','Print Array', lambda: self.controller.print_array())
        self.shortcut_manager.add_shortcut('Shift+r','Reset Single Array', lambda: self.reset_single_array())
        self.shortcut_manager.add_shortcut('Shift+e','Reset All Arrays', lambda: self.reset_all_arrays())

        self.shortcut_manager.add_shortcut('c','Print 5 droplets', lambda: self.controller.print_droplets(5))
        self.shortcut_manager.add_shortcut('v','Print 20 droplets', lambda: self.controller.print_droplets(20))
        self.shortcut_manager.add_shortcut('b','Print 100 droplets', lambda: self.controller.print_droplets(100))
        self.shortcut_manager.add_shortcut('Shift+s','Reset Syringe', lambda: self.controller.reset_syringe())
        self.shortcut_manager.add_shortcut('Shift+i','See calibrations', lambda: self.show_calibrations())
        self.shortcut_manager.add_shortcut('Esc', 'Pause Action', lambda: self.pause_machine())

    def make_transparent_icon(self):
        transparent_image = QtGui.QImage(1, 1, QtGui.QImage.Format_ARGB32)
        transparent_image.fill(QtCore.Qt.transparent)
        transparent_pixmap = QtGui.QPixmap.fromImage(transparent_image)
        transparent_icon = QtGui.QIcon(transparent_pixmap)
        return transparent_icon

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
        if self.model.machine_model.is_balance_connected():
            self.controller.disconnect_balance()
            print('Disconnected balance')

        event.accept()

class ConnectionWidget(QGroupBox):
    connect_machine_requested = QtCore.Signal(str)
    connect_balance_requested = QtCore.Signal(str)
    refresh_ports_requested = QtCore.Signal()

    def __init__(self, main_window,model,controller):
        super().__init__("CONNECTION")
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.controller = controller

        self.init_ui()

        # Connect signals from the model to update the view
        self.model.machine_model.ports_updated.connect(self.update_machine_ports)
        self.model.machine_model.ports_updated.connect(self.update_balance_ports)
        self.model.machine_model.machine_state_updated.connect(self.update_machine_connect_button)
        self.model.machine_model.balance_state_updated.connect(self.update_balance_connect_button)

        # Connect signals from the view to the controller
        self.connect_machine_requested.connect(self.controller.connect_machine)
        self.connect_balance_requested.connect(self.controller.connect_balance)
        self.refresh_ports_requested.connect(self.controller.update_available_ports)

        # Populate ports initially
        self.refresh_ports()

    def init_ui(self):
        """Initialize the user interface."""
        self.setLayout(QGridLayout())

        # Labels
        self.layout().addWidget(QLabel("Device"), 0, 0)
        self.layout().addWidget(QLabel("COM Port"), 0, 1)
        self.layout().addWidget(QLabel("Connect"), 0, 2)

        # Machine row
        self.machine_label = QLabel("Machine")
        self.machine_port_combobox = QComboBox()
        self.machine_connect_button = QPushButton("Connect")
        self.machine_connect_button.setCheckable(True)
        self.machine_connect_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.machine_connect_button.clicked.connect(self.request_machine_connect_change)
        self.update_machine_connect_button(self.model.machine_model.machine_connected)

        self.layout().addWidget(self.machine_label, 1, 0)
        self.layout().addWidget(self.machine_port_combobox, 1, 1)
        self.layout().addWidget(self.machine_connect_button, 1, 2)
        
        # Balance row
        self.balance_label = QLabel("Balance")
        self.balance_port_combobox = QComboBox()
        self.balance_connect_button = QPushButton("Connect")
        self.balance_connect_button.setCheckable(True)
        self.balance_connect_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.balance_connect_button.clicked.connect(self.request_balance_connect_change)
        self.update_balance_connect_button(self.model.machine_model.balance_connected)

        self.layout().addWidget(self.balance_label, 2, 0)
        self.layout().addWidget(self.balance_port_combobox, 2, 1)
        self.layout().addWidget(self.balance_connect_button, 2, 2)

        # Refresh button
        self.refresh_button = QPushButton("Refresh Ports")
        self.refresh_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.layout().addWidget(self.refresh_button, 3, 1, 1, 2)

    def update_machine_ports(self, ports):
        """Update the COM port selections for the machine."""
        ports_with_virtual = ports + ["Virtual"]
        self.machine_port_combobox.clear()
        self.machine_port_combobox.addItems(ports_with_virtual)
        default_port = self.model.get_default_machine_port()
        if default_port in ports:
            self.machine_port_combobox.setCurrentText(default_port)
        else:
            self.machine_port_combobox.setCurrentText(ports_with_virtual[0])

    def update_balance_ports(self, ports):
        """Update the COM port selections for the balance."""
        ports_with_virtual = ports + ["Virtual"]
        self.balance_port_combobox.clear()
        self.balance_port_combobox.addItems(ports_with_virtual)
        default_port = self.model.get_default_balance_port()
        if default_port in ports:
            self.balance_port_combobox.setCurrentText(default_port)
        else:
            self.balance_port_combobox.setCurrentText(ports_with_virtual[0])

    def request_machine_connect_change(self):
        """Handle machine connection request."""
        if self.model.machine_model.machine_connected:
            self.controller.disconnect_machine()
        else:
            self.connect_machine()

    def connect_machine(self):
        """Handle machine connection request."""
        port = self.machine_port_combobox.currentText()
        self.connect_machine_requested.emit(port)

    def request_balance_connect_change(self):
        """Handle balance connection request."""
        if self.model.machine_model.balance_connected:
            self.controller.disconnect_balance()
        else:
            self.connect_balance()

    def connect_balance(self):
        """Handle balance connection request."""
        port = self.balance_port_combobox.currentText()
        self.connect_balance_requested.emit(port)

    def refresh_ports(self):
        """Handle refresh ports request."""
        self.refresh_ports_requested.emit()

    def update_machine_connect_button(self, machine_connected):
        """Update the machine connect button text and color based on the connection state."""
        if machine_connected:
            self.machine_connect_button.setText("Disconnect")
            self.machine_connect_button.setStyleSheet(f"background-color: {self.color_dict['dark_blue']}; color: white;")
        else:
            self.machine_connect_button.setText("Connect")
            self.machine_connect_button.setStyleSheet(f"background-color: {self.color_dict['light_blue']}; color: white;")

    def update_balance_connect_button(self, balance_connected):
        """Update the balance connect button text and color based on the connection state."""
        if balance_connected:
            self.balance_connect_button.setText("Disconnect")
            self.balance_connect_button.setStyleSheet(f"background-color: {self.color_dict['dark_blue']}; color: white;")
        else:
            self.balance_connect_button.setText("Connect")
            self.balance_connect_button.setStyleSheet(f"background-color: {self.color_dict['light_blue']}; color: white;")



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

        self.current_pressure_label = QtWidgets.QLabel("Current Pressure:")  # Create a new QLabel for the current pressure label
        self.current_pressure_value = QtWidgets.QLabel()  # Create a new QLabel for the current pressure value
        self.target_pressure_label = QtWidgets.QLabel("Target Pressure:")  # Create a new QLabel for the target pressure label
        self.target_pressure_spinbox = QtWidgets.QDoubleSpinBox()  # Create a new QDoubleSpinBox for the target pressure value
        self.target_pressure_spinbox.setDecimals(2)  # Set the number of decimal places to 3
        self.target_pressure_spinbox.setSingleStep(0.1)  # Set the step size to 0.001
        self.target_pressure_spinbox.setRange(0, 5)  # Set the range of the spinbox to 0-10
        self.target_pressure_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.target_pressure_spinbox.valueChanged.connect(self.handle_target_pressure_change)  # Connect value changes to the update_pressure function

        self.layout.addWidget(self.current_pressure_label, 0, 0)  # Add the QLabel to the layout at position (0, 0)
        self.layout.addWidget(self.current_pressure_value, 0, 1)  # Add the QLabel to the layout at position (0, 1)
        self.layout.addWidget(self.target_pressure_label, 0, 2)  # Add the QLabel to the layout at position (1, 0)
        self.layout.addWidget(self.target_pressure_spinbox, 0, 3)  # Add the QDoubleSpinBox to the layout at position (1, 1)

        self.pressure_regulation_button = QtWidgets.QPushButton("Regulate Pressure")
        self.pressure_regulation_button.setFocusPolicy(QtCore.Qt.NoFocus)
        # self.pressure_regulation_button.setCheckable(True)
        self.pressure_regulation_button.clicked.connect(self.request_toggle_regulation)
        self.layout.addWidget(self.pressure_regulation_button, 1, 0, 1, 4)  # Add the button to the layout at position (2, 0) and make it span 2 columns
        self.update_regulation_button(self.model.machine_model.regulating_pressure)

        self.chart = QtCharts.QChart()
        self.chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.chart.setBackgroundBrush(QtGui.QBrush(self.color_dict['darker_gray']))  # Set the background color to grey
        self.chart_view = QtCharts.QChartView(self.chart)
        self.series = QtCharts.QLineSeries()
        self.series.setColor(QtCore.Qt.white)
        self.chart.addSeries(self.series)

        self.target_pressure_series = QtCharts.QLineSeries()  # Create a new line series for the target pressure
        self.target_pressure_series.setColor(QtCore.Qt.red)  # Set the line color to red
        self.chart.addSeries(self.target_pressure_series)

        self.axisX = QtCharts.QValueAxis()
        self.axisX.setTickCount(3)
        self.axisX.setRange(0, len(self.model.machine_model.pressure_readings))
        self.axisY = QtCharts.QValueAxis()
        self.axisY.setTitleText("Pressure (psi)")

        self.chart.addAxis(self.axisX, QtCore.Qt.AlignBottom)
        self.chart.addAxis(self.axisY, QtCore.Qt.AlignLeft)

        self.series.attachAxis(self.axisX)
        self.series.attachAxis(self.axisY)
        self.target_pressure_series.attachAxis(self.axisX)
        self.target_pressure_series.attachAxis(self.axisY)

        self.chart.legend().hide()  # Hide the legend
        self.chart_view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.chart_view.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout.addWidget(self.chart_view, 2, 0,1,4)

        self.calibrate_pressure_button = QtWidgets.QPushButton("Calibrate Pressure")
        self.calibrate_pressure_button.clicked.connect(self.calibrate_pressure)
        self.layout.addWidget(self.calibrate_pressure_button, 3, 0, 2, 2)

        self.pulse_width_label = QtWidgets.QLabel("Pulse Width:")
        self.pulse_width_spinbox = QtWidgets.QSpinBox()
        self.pulse_width_spinbox.setRange(0, 10000)
        self.pulse_width_spinbox.setSingleStep(50)
        self.pulse_width_spinbox.setValue(3000)
        self.pulse_width_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.pulse_width_spinbox.valueChanged.connect(self.handle_pulse_width_change)
        self.layout.addWidget(self.pulse_width_label,3,2,1,1)
        self.layout.addWidget(self.pulse_width_spinbox,3,3,1,1)


        self.model.machine_model.pressure_updated.connect(self.update_pressure)

    def handle_target_pressure_change(self, value):
        """Handle changes to the target pressure value."""
        # self.update_target_pressure_input.emit(value)
        self.controller.set_absolute_pressure(value,manual=True)

    def handle_pulse_width_change(self, value):
        """Handle changes to the pulse width value."""
        # self.update_pulse_width_input.emit(value)
        self.controller.set_pulse_width(value,manual=True)

    def update_pressure(self, pressure_log):
        """Update the current pressure label and plot with the new pressure values."""
        # Clear previous data
        self.series.clear()
        self.target_pressure_series.clear()

        # Append new pressure data
        for i, pressure in enumerate(pressure_log):
            self.series.append(i, pressure)

        # Get the target pressure and append target line points
        target_pressure = self.model.machine_model.target_pressure
        self.target_pressure_series.append(0, target_pressure)  # Add lower point of target pressure line
        self.target_pressure_series.append(len(pressure_log) - 1, target_pressure)  # Add upper point of target pressure line

        # Calculate min and max pressure for y-axis range
        min_pressure = min([*pressure_log,target_pressure]) - 0.5
        max_pressure = max([*pressure_log,target_pressure]) + 0.5

        # Update y-axis range with calculated min and max
        self.axisY.setRange(min_pressure, max_pressure)

        # Update the pressure display labels
        self.current_pressure_value.setText(f"{pressure_log[-1]:.3f}")

        self.target_pressure_spinbox.blockSignals(True)  # Block signals temporarily
        self.target_pressure_spinbox.setValue(target_pressure)
        self.target_pressure_spinbox.blockSignals(False)  # Unblock signals

        self.pulse_width_spinbox.blockSignals(True)
        self.pulse_width_spinbox.setValue(self.model.machine_model.pulse_width)
        self.pulse_width_spinbox.blockSignals(False)

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
        if self.model.rack_model.get_gripper_printer_head() == None:
            self.popup_message_signal.emit("No Printer Head","Please load a printer head before calibrating pressure")
            return
        if self.model.machine_model.get_current_location() != 'balance':
            response = self.main_window.popup_yes_no("Must be positioned at the balance","Would you like to move to the balance?")
            if response == '&No':
                self.popup_message_signal.emit("Must be positioned at the balance","Please move to the balance before calibrating pressure")
                return
            elif response == '&Yes':
                self.controller.move_to_location('balance',manual=False)
        mass_calibration_dialog = MassCalibrationDialog(self.main_window,self.model,self.controller)
        mass_calibration_dialog.exec()
    
    # def calibrate_pressure(self):
    #     """Calibrate the pressure for a specific printer head."""
    #     if self.model.rack_model.gripper_printer_head is None:
    #         self.popup_message_signal.emit("No Printer Head","Please load a printer head before calibrating pressure")
    #         return
        
    #     self.target_pressure = self.model.machine_model.get_current_pressure()
    #     pressure_calibration_dialog = PressureCalibrationDialog(self.main_window,self.model,self.controller)
    #     pressure_calibration_dialog.print_calibration_droplets.connect(self.print_calibration_droplets)
    #     pressure_calibration_dialog.change_pressure.connect(self.calibration_pressure_change)
    #     # pressure_calibration_dialog.calibration_complete.connect(self.store_calibrations)
    #     pressure_calibration_dialog.exec()
    #     print('Calibrating pressure')

    def print_calibration_droplets(self,num_droplets):
        print('Printing calibration droplets:',num_droplets,self.target_pressure)
        self.controller.print_calibration_droplets(num_droplets,self.target_pressure)

    def calibration_pressure_change(self,pressure):
        print('Pressure changed to:',pressure)
        self.target_pressure = pressure
        self.controller.set_absolute_pressure(pressure)
        
class MassCalibrationDialog(QtWidgets.QDialog):

    def __init__(self, main_window,model,controller):
        super().__init__()
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.controller = controller

        self.controller.enter_print_mode()
        
        # self.current_printer_head = self.model.rack_model.get_gripper_printer_head()
        # self.current_stock_solution = self.current_printer_head.get_stock_solution()

        self.num_calibration_droplets = 50
        self.repeat_measurements = 0
        self.pressures_to_screen = []
        self.current_set_pulse_width = 4200

        self.setWindowTitle("Mass Calibration")
        self.resize(1200, 700)

        self.layout = QtWidgets.QVBoxLayout()
        self.label = QtWidgets.QLabel("Begin the mass calibration")
        self.layout.addWidget(self.label)

        self.charts_layout = QtWidgets.QHBoxLayout()

        # Create a series and chart to display mass over time
        self.series = QtCharts.QLineSeries()
        self.series.setColor(QtCore.Qt.white)
        self.chart = QtCharts.QChart()
        self.chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.chart.setBackgroundBrush(QtGui.QBrush(self.color_dict['dark_gray']))  # Set the background color to grey
        self.chart.addSeries(self.series)
        # self.chart.createDefaultAxes()
        self.chart.setTitle("Mass over time")

        self.axisX = QtCharts.QValueAxis()
        self.axisX.setTickCount(3)
        self.axisX.setRange(0, 300)
        self.axisY = QtCharts.QValueAxis()
        self.axisY.setTitleText("Mass (mg)")

        self.chart.addAxis(self.axisX, QtCore.Qt.AlignBottom)
        self.chart.addAxis(self.axisY, QtCore.Qt.AlignLeft)
        self.series.attachAxis(self.axisX)
        self.series.attachAxis(self.axisY)

        # Create a chart view to display the chart
        self.chart_view = QtCharts.QChartView(self.chart)
        self.chart_view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.chart.legend().hide()  # Hide
        self.chart_view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.chart_view.setFocusPolicy(QtCore.Qt.NoFocus)

        # Add the chart view to the layout
        self.charts_layout.addWidget(self.chart_view)

        self.volume_pressure_series = QtCharts.QScatterSeries()
        self.volume_pressure_series.setColor(QtCore.Qt.white)
        self.volume_pressure_series.setMarkerSize(3.0)
        self.volume_pressure_chart = QtCharts.QChart()
        self.volume_pressure_chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.volume_pressure_chart.setBackgroundBrush(QtGui.QBrush(self.color_dict['dark_gray']))  # Set the background color to grey
        self.volume_pressure_chart.addSeries(self.volume_pressure_series)
        self.volume_pressure_chart.setTitle("Mass versus Pressure")

        self.volume_pressure_axisX = QtCharts.QValueAxis()
        self.volume_pressure_axisX.setTitleText("Pulse Width (us)")
        self.volume_pressure_axisY = QtCharts.QValueAxis()
        self.volume_pressure_axisY.setTitleText("Volume (nL)")

        self.volume_pressure_chart.addAxis(self.volume_pressure_axisX, QtCore.Qt.AlignBottom)
        self.volume_pressure_chart.addAxis(self.volume_pressure_axisY, QtCore.Qt.AlignLeft)
        self.volume_pressure_series.attachAxis(self.volume_pressure_axisX)
        self.volume_pressure_series.attachAxis(self.volume_pressure_axisY)

        # Create a series for the linear fit
        self.linear_fit_series = QtCharts.QLineSeries()
        self.linear_fit_series.setColor(QtCore.Qt.red)
        self.volume_pressure_chart.addSeries(self.linear_fit_series)
        self.linear_fit_series.attachAxis(self.volume_pressure_axisX)
        self.linear_fit_series.attachAxis(self.volume_pressure_axisY)

        # Ensure proper pen settings for each line
        line_pen = QtGui.QPen(QtCore.Qt.black)
        line_pen.setWidth(1)

        # Add horizontal lines using QLineSeries
        # Target line at 40 nL (red)
        target_line = QtCharts.QLineSeries()
        target_line.setColor(QtCore.Qt.red)
        target_line.append(0, 40)  # Starting point of the line at (0, 40)
        target_line.append(10000, 40)  # Ending point of the line at (5, 40)
        self.volume_pressure_chart.addSeries(target_line)
        target_line.attachAxis(self.volume_pressure_axisX)
        target_line.attachAxis(self.volume_pressure_axisY)

        # Line above target at 41 nL (black)
        above_target_line = QtCharts.QLineSeries()
        above_target_line.setPen(line_pen)  # Apply custom pen for consistent color and width
        above_target_line.append(0, 41)
        above_target_line.append(10000, 41)
        self.volume_pressure_chart.addSeries(above_target_line)
        above_target_line.attachAxis(self.volume_pressure_axisX)
        above_target_line.attachAxis(self.volume_pressure_axisY)

        # Line below target at 39 nL (black)
        below_target_line = QtCharts.QLineSeries()
        below_target_line.setPen(line_pen)  # Apply custom pen for consistent color and width
        below_target_line.append(0, 39)
        below_target_line.append(10000, 39)
        self.volume_pressure_chart.addSeries(below_target_line)
        below_target_line.attachAxis(self.volume_pressure_axisX)
        below_target_line.attachAxis(self.volume_pressure_axisY)

        # Create a chart view to display the chart
        self.volume_pressure_chart_view = QtCharts.QChartView(self.volume_pressure_chart)
        self.volume_pressure_chart_view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.volume_pressure_chart.legend().hide()  # Hide the legend
        self.volume_pressure_chart_view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.volume_pressure_chart_view.setFocusPolicy(QtCore.Qt.NoFocus)

        # Add the chart view to the layout
        self.charts_layout.addWidget(self.volume_pressure_chart_view)

        row = 0

        self.user_input_layout = QtWidgets.QGridLayout()

        self.current_stock_label = QtWidgets.QLabel("Current Stock Solution:")
        self.current_stock_value = QtWidgets.QLabel(self.model.calibration_model.get_current_stock_id())
        self.user_input_layout.addWidget(self.current_stock_label, row, 0)
        self.user_input_layout.addWidget(self.current_stock_value, row, 1)
        row += 1

        # Add a combo box to select the desired predictive model
        self.model_label = QtWidgets.QLabel("Predictive Model:")
        self.model_combobox = QtWidgets.QComboBox()
        model_names = self.model.calibration_model.get_all_model_names()
        self.model_combobox.addItems(model_names)
        self.model_combobox.currentIndexChanged.connect(self.handle_model_change)
        self.user_input_layout.addWidget(self.model_label, row, 0)
        self.user_input_layout.addWidget(self.model_combobox, row, 1)
        row += 1

        self.current_volume_label = QtWidgets.QLabel("Current Volume:")
        current_volume = self.model.calibration_model.get_current_printer_head_volume()
        if current_volume == None:
            current_volume = 0
        self.current_volume_value = QtWidgets.QLabel(f"{current_volume:.2f} uL")
        self.user_input_layout.addWidget(self.current_volume_label, row, 0)
        self.user_input_layout.addWidget(self.current_volume_value, row, 1)
        row += 1

        self.set_volume_label = QtWidgets.QLabel("Set Volume:")
        self.set_volume_spinbox = QtWidgets.QDoubleSpinBox()
        self.set_volume_spinbox.setDecimals(1)
        self.set_volume_spinbox.setSingleStep(10)
        self.set_volume_spinbox.setRange(0, 1000)
        self.set_volume_spinbox.setValue(100)
        # self.set_volume_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.user_input_layout.addWidget(self.set_volume_label, row, 0)
        self.user_input_layout.addWidget(self.set_volume_spinbox, row, 1)
        row += 1

        self.set_volume_button = QtWidgets.QPushButton("Set Volume")
        self.set_volume_button.clicked.connect(self.set_volume)
        self.user_input_layout.addWidget(self.set_volume_button, row, 0, 1, 2)
        row += 1

        self.target_drop_volume_label = QtWidgets.QLabel("Target Droplet Volume:")
        self.target_drop_volume_spinbox = QtWidgets.QDoubleSpinBox()
        self.target_drop_volume_spinbox.setDecimals(1)
        self.target_drop_volume_spinbox.setSingleStep(1)
        self.target_drop_volume_spinbox.setRange(1, 100)
        self.target_drop_volume_spinbox.setValue(40)
        self.target_drop_volume_spinbox.valueChanged.connect(self.handle_target_drop_volume_change)
        # self.target_drop_volume_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.user_input_layout.addWidget(self.target_drop_volume_label, row, 0)
        self.user_input_layout.addWidget(self.target_drop_volume_spinbox, row, 1)
        row += 1

        self.resistance_calibration_button = QtWidgets.QPushButton("Resistance Calibration")
        self.resistance_calibration_button.clicked.connect(self.initiate_resistance_calibration)
        self.user_input_layout.addWidget(self.resistance_calibration_button, row, 0, 1, 2)
        row += 1

        self.predict_pulse_width_button = QtWidgets.QPushButton("Predict pulse")
        self.predict_pulse_width_button.clicked.connect(self.evaluate_predicted_pulse_width)
        self.user_input_layout.addWidget(self.predict_pulse_width_button, row, 0, 1, 2)
        row += 1

        self.predict_pulse_width_no_bias_button = QtWidgets.QPushButton("Predict pulse no bias")
        self.predict_pulse_width_no_bias_button.clicked.connect(self.evaluate_predict_pulse_width_no_bias)
        self.user_input_layout.addWidget(self.predict_pulse_width_no_bias_button, row, 0, 1, 2)
        row += 1

        self.current_pressure_label = QtWidgets.QLabel("Current Pressure:")
        self.current_pressure_value = QtWidgets.QLabel()
        self.user_input_layout.addWidget(self.current_pressure_label, row, 0)
        self.user_input_layout.addWidget(self.current_pressure_value, row, 1)
        row += 1

        self.target_pressure_label = QtWidgets.QLabel("Target Pressure:")
        self.target_pressure_spinbox = QtWidgets.QDoubleSpinBox()
        self.target_pressure_spinbox.setDecimals(2)
        self.target_pressure_spinbox.setSingleStep(0.1)
        self.target_pressure_spinbox.setRange(0, 5)
        # self.target_pressure_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.target_pressure_spinbox.valueChanged.connect(self.handle_target_pressure_change)
        
        self.user_input_layout.addWidget(self.target_pressure_label, row, 0)
        self.user_input_layout.addWidget(self.target_pressure_spinbox, row, 1)
        row += 1

        self.pulse_width_label = QtWidgets.QLabel("Pulse Width:")
        self.pulse_width_spinbox = QtWidgets.QSpinBox()
        self.pulse_width_spinbox.setRange(10, 10000)
        self.pulse_width_spinbox.setSingleStep(5)
        self.pulse_width_spinbox.setValue(4200)
        # self.pulse_width_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.pulse_width_spinbox.valueChanged.connect(self.handle_pulse_width_change)
        self.user_input_layout.addWidget(self.pulse_width_label, row, 0)
        self.user_input_layout.addWidget(self.pulse_width_spinbox, row, 1)
        row += 1

        self.num_droplets_label = QtWidgets.QLabel("Number of Droplets:")
        self.num_droplets_spinbox = QtWidgets.QSpinBox()
        self.num_droplets_spinbox.setRange(1, 100)
        self.num_droplets_spinbox.setSingleStep(5)
        self.num_droplets_spinbox.setValue(50)
        # self.num_droplets_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.num_droplets_spinbox.valueChanged.connect(self.handle_num_droplets_change)
        self.user_input_layout.addWidget(self.num_droplets_label, row, 0)
        self.user_input_layout.addWidget(self.num_droplets_spinbox, row, 1)
        row += 1

        self.calibrate_button = QtWidgets.QPushButton("Calibrate")
        self.calibrate_button.clicked.connect(self.initiate_calibration_process)
        self.user_input_layout.addWidget(self.calibrate_button, row, 0, 1, 2)
        row += 1

        self.pressure_screen_low_label = QtWidgets.QLabel("Screen Low:")
        self.pressure_screen_low_spinbox = QtWidgets.QDoubleSpinBox()
        self.pressure_screen_low_spinbox.setDecimals(0)
        self.pressure_screen_low_spinbox.setSingleStep(10)
        self.pressure_screen_low_spinbox.setRange(10,7000)
        self.pressure_screen_low_spinbox.setValue(3500)
        # self.pressure_screen_low_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.user_input_layout.addWidget(self.pressure_screen_low_label, row, 0)
        self.user_input_layout.addWidget(self.pressure_screen_low_spinbox, row, 1)
        row += 1

        self.pressure_screen_high_label = QtWidgets.QLabel("Screen High:")
        self.pressure_screen_high_spinbox = QtWidgets.QDoubleSpinBox()
        self.pressure_screen_high_spinbox.setDecimals(0)
        self.pressure_screen_high_spinbox.setSingleStep(10)
        self.pressure_screen_high_spinbox.setRange(10, 7000)
        self.pressure_screen_high_spinbox.setValue(4500)
        # self.pressure_screen_high_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.user_input_layout.addWidget(self.pressure_screen_high_label, row, 0)
        self.user_input_layout.addWidget(self.pressure_screen_high_spinbox, row, 1)
        row += 1

        self.repeat_measurement_label = QtWidgets.QLabel("Repeat Measurements:")
        self.repeat_measurement_spinbox = QtWidgets.QSpinBox()
        self.repeat_measurement_spinbox.setRange(1, 100)
        self.repeat_measurement_spinbox.setSingleStep(1)
        self.repeat_measurement_spinbox.setValue(3)
        # self.repeat_measurement_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.user_input_layout.addWidget(self.repeat_measurement_label, row, 0)
        self.user_input_layout.addWidget(self.repeat_measurement_spinbox, row, 1)
        row += 1
        
        self.repeat_measurement_button = QtWidgets.QPushButton("Repeat Measurement")
        self.repeat_measurement_button.clicked.connect(self.initiate_repeat_calibration_process)
        self.user_input_layout.addWidget(self.repeat_measurement_button, row, 0, 1, 2)
        row += 1

        self.start_screen_button = QtWidgets.QPushButton("Start Screen")
        self.start_screen_button.clicked.connect(self.start_screen)
        self.user_input_layout.addWidget(self.start_screen_button, row, 0, 1, 2)
        row += 1

        self.stop_repeat_measurement_button = QtWidgets.QPushButton("Stop Repeating")
        self.stop_repeat_measurement_button.clicked.connect(self.stop_repeat_calibration_process)
        self.user_input_layout.addWidget(self.stop_repeat_measurement_button, row, 0, 1, 2)
        row += 1

        self.remove_last_measurement_button = QtWidgets.QPushButton("Remove Last")
        self.remove_last_measurement_button.clicked.connect(self.remove_last_measurement)
        self.user_input_layout.addWidget(self.remove_last_measurement_button, row, 0, 1, 2)
        row += 1

        self.remove_all_calibrations_button = QtWidgets.QPushButton("Remove All")
        self.remove_all_calibrations_button.clicked.connect(self.remove_all_calibrations_for_stock)
        self.user_input_layout.addWidget(self.remove_all_calibrations_button, row, 0, 1, 2)
        row += 1

        self.results_label = QtWidgets.QLabel("Calibration Results:")
        self.results_value = QtWidgets.QLabel()
        self.user_input_layout.addWidget(self.results_label, row, 0)
        self.user_input_layout.addWidget(self.results_value, row, 1)
        row += 1


        # Add the grid layout into a QVBoxLayout
        self.user_input_container_layout = QtWidgets.QVBoxLayout()
        self.user_input_container_layout.addLayout(self.user_input_layout)
        self.user_input_container_layout.addStretch()  # Add a stretch at the bottom to push everything up

        # Add the QVBoxLayout to the charts_layout without alignment argument
        self.charts_layout.addLayout(self.user_input_container_layout)

        # Set the alignment to top after adding the layout
        self.charts_layout.setAlignment(self.user_input_container_layout, QtCore.Qt.AlignTop)

        self.layout.addLayout(self.charts_layout)
        self.setLayout(self.layout)

        self.model.calibration_model.mass_updated_signal.connect(self.update_mass_time_plot)
        self.model.machine_model.printing_parameters_updated.connect(self.update_printing_parameters)
        self.model.calibration_model.initial_mass_captured_signal.connect(self.initiate_calibration_print)
        self.model.calibration_model.calibration_complete_signal.connect(self.handle_calibration_complete)
        self.model.calibration_model.change_volume_signal.connect(self.update_volume)
        
        last_model_name = self.model.calibration_model.get_last_model_name()
        if last_model_name in model_names:
            self.model_combobox.setCurrentText(last_model_name)
        self.handle_model_change(self.model_combobox.currentIndex())

        self.update_printing_parameters()
        self.update_volume_pressure_plot()

    def add_horizontal_line(self, y_value, color=QtCore.Qt.black, pen=None):
        """
        Adds a horizontal line to the given chart at the specified y_value.

        :param chart: The chart to which the line will be added.
        :param axisX: The X axis to attach the line to.
        :param axisY: The Y axis to attach the line to.
        :param y_value: The y-coordinate at which the line will be drawn.
        :param color: The color of the line. Default is black.
        :param pen: Optional QPen object to customize the line's appearance.
        """
        line_series = QtCharts.QLineSeries()
        if pen:
            line_series.setPen(pen)
        else:
            line_series.setColor(color)
        line_series.append(0, y_value)
        line_series.append(10000, y_value)
        self.volume_pressure_chart.addSeries(line_series)
        line_series.attachAxis(self.volume_pressure_axisX)
        line_series.attachAxis(self.volume_pressure_axisY)

    def add_target_volume_lines(self,target_volume,tolerance=0.03):
        line_pen = QtGui.QPen(QtCore.Qt.black)
        line_pen.setWidth(1)
        self.add_horizontal_line(target_volume,color=QtCore.Qt.red)
        self.add_horizontal_line(target_volume*(1+tolerance),color=QtCore.Qt.black,pen=line_pen)
        self.add_horizontal_line(target_volume*(1-tolerance),color=QtCore.Qt.black,pen=line_pen)

    def handle_model_change(self,index):
        """Handle changes to the predictive model."""
        model_name = self.model_combobox.currentText()
        result = self.model.calibration_model.set_models_by_name(model_name)
        if not result:
            self.main_window.popup_message("Model Error","Model not found")
        else:
            target_volume, printer_head_type, resistance_pulse_width, standard_pressure = self.model.calibration_model.get_default_values()
            self.pulse_width_spinbox.blockSignals(True)
            self.pulse_width_spinbox.setValue(resistance_pulse_width)
            self.pulse_width_spinbox.blockSignals(False)
            self.controller.set_pulse_width(resistance_pulse_width,manual=False)

            self.target_pressure_spinbox.blockSignals(True)
            self.target_pressure_spinbox.setValue(standard_pressure)
            self.target_pressure_spinbox.blockSignals(False)
            self.controller.set_absolute_pressure(standard_pressure,manual=False)

            self.target_drop_volume_spinbox.setValue(target_volume)
            self.handle_target_drop_volume_change(target_volume)
            self.controller.update_balance_prediction_models(target_volume=target_volume)

    def handle_target_drop_volume_change(self, value):
        """Handle changes to the target drop volume value. Redraws the volume-pressure plot with a horizontal line at the target volume."""
        current_target_volume = self.target_drop_volume_spinbox.value()
        # Remove old lines
        # Remove only the target volume lines
        lines_to_remove = [series for series in self.volume_pressure_chart.series() if series not in [self.volume_pressure_series, self.linear_fit_series]]
        for series in lines_to_remove:
            self.volume_pressure_chart.removeSeries(series)
        # Add new lines
        self.add_target_volume_lines(current_target_volume)
        self.update_volume_pressure_plot()

            
    def handle_target_pressure_change(self, value):
        """Handle changes to the target pressure value."""
        self.controller.set_absolute_pressure(value,manual=True)

    def handle_pulse_width_change(self, value):
        """Handle changes to the pulse width value."""
        self.controller.set_pulse_width(value,manual=True)

    def handle_num_droplets_change(self, value):
        """Handle changes to the number of droplets value."""
        self.num_calibration_droplets = value

    def update_printing_parameters(self):
        """Update the spinboxes with the current printing parameters."""

        self.current_pressure_value.setText(f"{self.model.machine_model.current_pressure:.3f}")

        self.target_pressure_spinbox.blockSignals(True)
        self.target_pressure_spinbox.setValue(self.model.machine_model.target_pressure)
        self.target_pressure_spinbox.blockSignals(False)

        self.pulse_width_spinbox.blockSignals(True)
        self.pulse_width_spinbox.setValue(self.model.machine_model.pulse_width)
        self.pulse_width_spinbox.blockSignals(False)

    def set_volume(self):
        """Set the volume of the printer head."""
        volume = self.set_volume_spinbox.value()
        self.model.calibration_model.set_current_volume(volume)
    
    def update_volume(self):
        """Update the volume value."""
        volume = self.model.calibration_model.get_current_printer_head_volume()
        self.current_volume_value.setText(f"{volume:.2f} uL")
    
    def update_mass_time_plot(self):
        """Update the mass over time plot."""
        mass_log = self.model.calibration_model.get_mass_log()

        self.series.clear()
        for i, mass in enumerate(mass_log):
            self.series.append(i, mass)

        if len(mass_log) > 0:
            self.axisX.setRange(0, len(mass_log))
            self.axisY.setRange(min(mass_log) - 0.5, max(mass_log) + 0.5)

    def initiate_resistance_calibration(self):
        """Initiate a measurement of the resistance of the printer head using the standard condition."""
        self.label.setText("Started resistance calibration process, waiting for mass stabilization")
        self.controller.check_syringe_position()
        self.controller.set_pulse_width(self.model.calibration_model.standard_pulse_width,manual=False)
        self.current_set_pulse_width = self.model.calibration_model.standard_pulse_width
        self.model.calibration_model.initiate_new_measurement('resistance',self.num_calibration_droplets)
        
    def predict_pulse_width(self):
        """Predict the pulse width for a given volume."""
        target_volume = self.target_drop_volume_spinbox.value()
        return self.model.calibration_model.predict_pulse_width_for_droplet(target_volume,calc_bias=True)
    
    def evaluate_predicted_pulse_width(self):
        """Evaluate the predicted pulse width for a given volume."""
        self.label.setText("Evaluating prediction, waiting for mass stabilization")
        self.controller.check_syringe_position()
        predicted_pulse_width, applied_bias = self.predict_pulse_width()
        self.current_set_pulse_width = predicted_pulse_width
        target_volume = self.target_drop_volume_spinbox.value()
        self.pulse_width_spinbox.blockSignals(True)
        self.pulse_width_spinbox.setValue(predicted_pulse_width)
        self.pulse_width_spinbox.blockSignals(False)
        self.controller.set_pulse_width(predicted_pulse_width,manual=False)
        self.model.calibration_model.initiate_new_measurement('predicted',self.num_calibration_droplets,pulse_width=predicted_pulse_width,target_volume=target_volume,applied_bias=applied_bias)

    def predict_pulse_width_no_bias(self):
        """Predict the pulse width for a given volume without bias."""
        target_volume = self.target_drop_volume_spinbox.value()
        return self.model.calibration_model.predict_pulse_width_for_droplet(target_volume,calc_bias=False)
    
    def evaluate_predict_pulse_width_no_bias(self):
        """Evaluate the predicted pulse width for a given volume without bias."""
        self.label.setText("Evaluating prediction without bias, waiting for mass stabilization")
        self.controller.check_syringe_position()
        predicted_pulse_width, applied_bias = self.predict_pulse_width_no_bias()
        self.current_set_pulse_width = predicted_pulse_width
        target_volume = self.target_drop_volume_spinbox.value()
        self.pulse_width_spinbox.blockSignals(True)
        self.pulse_width_spinbox.setValue(predicted_pulse_width)
        self.pulse_width_spinbox.blockSignals(False)
        self.controller.set_pulse_width(predicted_pulse_width,manual=False,update_model=True)
        self.model.calibration_model.initiate_new_measurement('predicted',self.num_calibration_droplets,pulse_width=predicted_pulse_width,target_volume=target_volume,applied_bias=applied_bias)



    def start_screen(self):
        """Start the screen for the current stock solution."""
        # self.start_screen_button.setDisabled(True)
        # self.calibrate_button.setDisabled(True)
        # self.repeat_measurement_button.setDisabled(True)
        # self.stop_repeat_measurement_button.setDisabled(False)

        screen_low = self.pressure_screen_low_spinbox.value()
        screen_high = self.pressure_screen_high_spinbox.value()
        steps = self.repeat_measurement_spinbox.value()
        self.pressures_to_screen = list(np.linspace(screen_low,screen_high,steps))
        random.shuffle(self.pressures_to_screen)
        #print(f'Screening pulse widths: {self.pressures_to_screen}')

        self.repeat_measurements = steps
        self.repeat_measurements -= 1
        current_screen_pressure = self.pressures_to_screen.pop()
        self.label.setText(f"---Testing {current_screen_pressure} psi, {self.repeat_measurements} remaining---")
        #print(f'Screening pulse widths: {current_screen_pressure}')
        self.controller.set_pulse_width(current_screen_pressure,manual=False)
        self.current_set_pulse_width = current_screen_pressure
        self.model.calibration_model.initiate_new_measurement('screen',self.num_calibration_droplets,pulse_width=current_screen_pressure)

    
    def initiate_repeat_calibration_process(self):
        """Initiate the process of capturing a new measurement."""
        # self.start_screen_button.setDisabled(True)
        # self.calibrate_button.setDisabled(True)
        # self.repeat_measurement_button.setDisabled(True)
        self.label.setText(f"---{self.repeat_measurements} measurements remaining---")
        self.repeat_measurements = self.repeat_measurement_spinbox.value()
        pulse_width,applied_bias = self.predict_pulse_width()
        self.current_set_pulse_width = pulse_width
        target_volume = self.target_drop_volume_spinbox.value()
        self.controller.set_pulse_width(pulse_width,manual=False)
        self.controller.check_syringe_position()
        self.model.calibration_model.initiate_new_measurement('repeat',self.num_calibration_droplets,pulse_width=pulse_width,target_volume=target_volume,applied_bias=applied_bias)
        self.repeat_measurements -= 1

    def stop_repeat_calibration_process(self):
        """Stop the process of capturing a new measurement."""
        self.label.setText(f'Stopping repeat measurements')
        self.repeat_measurements = 0
        self.pressures_to_screen = []
    
    def initiate_calibration_process(self):
        """Initiate the process of capturing a new measurement."""
        self.label.setText("Started calibration process, waiting for mass stabilization")
        self.controller.check_syringe_position()
        self.model.calibration_model.initiate_new_measurement('standard',self.num_calibration_droplets)
    
    def initiate_calibration_print(self):
        """Initiate the printing of calibration droplets."""
        self.label.setText("Printing calibration droplets")
        print('View: Printing calibration droplets')
        self.controller.print_calibration_droplets(self.num_calibration_droplets,pulse_width=self.current_set_pulse_width)

    def handle_calibration_complete(self):
        """Handle the completion of the calibration process."""
        self.update_volume_pressure_plot()
        self.results_value.setText(f"{self.model.calibration_model.get_last_droplet_volume():.2f} nL")
        if self.repeat_measurements > 0:
            #print(f'---{self.repeat_measurements} measurements remaining---')
            self.repeat_measurements -= 1
            if len(self.pressures_to_screen) > 0:
                current_screening_pressure = self.pressures_to_screen.pop()
                #print(f'Screening pressure: {current_screening_pressure}')
                self.label.setText(f"---Testing {current_screening_pressure} psi, {self.repeat_measurements} remaining---")
                self.current_set_pulse_width = current_screening_pressure
                self.controller.set_pulse_width(current_screening_pressure,manual=False)
                self.controller.check_syringe_position()
                self.model.calibration_model.initiate_new_measurement('screen',self.num_calibration_droplets,pulse_width=current_screening_pressure)
            else:
                pulse_width,applied_bias = self.predict_pulse_width()
                self.current_set_pulse_width = pulse_width
                self.controller.set_pulse_width(pulse_width,manual=False)
                target_volume = self.target_drop_volume_spinbox.value()
                self.controller.check_syringe_position()
                self.label.setText(f"---{self.repeat_measurements} measurements remaining---")
                self.model.calibration_model.initiate_new_measurement('repeat',self.num_calibration_droplets,pulse_width=pulse_width,target_volume=target_volume,applied_bias=applied_bias)
        else:
            self.label.setText("Calibration complete")

    
    def update_volume_pressure_plot(self):
        self.volume_pressure_series.clear()
        measurements = self.model.calibration_model.get_measurements()
        print(f'Measurements:\n{measurements}')
        pressures = []
        volumes = []
        for pressure,pulse_width,droplets, volume in measurements:
            print(f'Pressure: {pressure}, Pulse Width: {pulse_width}, Droplets: {droplets}, Volume: {volume}')
            self.volume_pressure_series.append(pulse_width, volume)
            pressures.append(pulse_width)
            volumes.append(volume)
        
        if len(measurements) >= 2 and np.std(pressures) > 0.01:
            # Calculate the linear fit
            slope, intercept = np.polyfit(pressures, volumes, 1)

            # Update the linear fit series
            self.linear_fit_series.clear()
            min_pressure = min(pressures)
            max_pressure = max(pressures)
            self.linear_fit_series.append(min_pressure, min_pressure * slope + intercept)
            self.linear_fit_series.append(max_pressure, max_pressure * slope + intercept)

        if len(pressures) > 0:
            min_pressure = min(pressures) - 200
            max_pressure = max(pressures) + 200
        else:
            min_pressure = 1500
            max_pressure = 3500
        
        if len(volumes) > 0:
            min_volume = min(volumes) - 10
            max_volume = max(volumes) + 10
        else:
            print('No volumes')
            current_target_volume = self.target_drop_volume_spinbox.value()
            min_volume = current_target_volume - 20
            max_volume = current_target_volume + 20

        self.volume_pressure_axisX.setRange(min_pressure, max_pressure)
        self.volume_pressure_axisY.setRange(min_volume, max_volume)

    def remove_last_measurement(self):
        """Remove the last measurement from the calibration log."""
        self.model.calibration_model.remove_last_measurement()

    def remove_all_calibrations_for_stock(self):
        """Remove all the calibration measurements for the current stock solution."""
        self.model.calibration_model.remove_all_calibrations_for_stock()

    def closeEvent(self, event):
        """Handle the closing of the dialog."""
        self.model.calibration_model.mass_updated_signal.disconnect(self.update_mass_time_plot)
        self.model.machine_model.printing_parameters_updated.disconnect(self.update_printing_parameters)
        self.model.calibration_model.initial_mass_captured_signal.disconnect(self.initiate_calibration_print)
        self.model.calibration_model.calibration_complete_signal.disconnect(self.handle_calibration_complete)
        self.model.calibration_model.change_volume_signal.disconnect(self.update_volume)
        self.controller.exit_print_mode()
        event.accept()


class PressureCalibrationDialog(QtWidgets.QDialog):
    print_calibration_droplets = QtCore.Signal(int)
    change_pressure = QtCore.Signal(float)
    calibration_complete = QtCore.Signal()
    def __init__(self, main_window,model,controller):
        super().__init__()
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.controller = controller

        self.machine = self.controller.machine
        self.balance = self.controller.machine.balance
        self.printer_head = self.model.rack_model.gripper_printer_head
        self.setWindowTitle("Pressure Calibration")
        self.resize(800, 400)

        self.init_mass = None
        self.final_mass = None
        self.target_mass = 4  # Set your target mass here
        self.max_pressure_step = 1  # Set your pressure step here
        self.mass_tolerance = 0.05
        self.min_pressure = 1.2

        self.mass_log = []
        self.tolerance = 0.01
        self.stable_count = 0
        self.stable = False

        self.psi_max = 4
        
        self.layout = QtWidgets.QVBoxLayout()
        self.label = QtWidgets.QLabel("Waiting for stable mass...")
        self.layout.addWidget(self.label)

        self.charts_layout = QtWidgets.QHBoxLayout()

        # Create a series and chart to display mass over time
        self.series = QtCharts.QLineSeries()
        self.series.setColor(QtCore.Qt.white)
        self.chart = QtCharts.QChart()
        self.chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.chart.setBackgroundBrush(QtGui.QBrush(self.color_dict['dark_gray']))  # Set the background color to grey
        self.chart.addSeries(self.series)
        # self.chart.createDefaultAxes()
        self.chart.setTitle("Mass over time")

        self.axisX = QtCharts.QValueAxis()
        self.axisX.setTickCount(3)
        self.axisX.setRange(0, 300)
        self.axisY = QtCharts.QValueAxis()
        self.axisY.setTitleText("Mass (g)")

        self.chart.addAxis(self.axisX, QtCore.Qt.AlignBottom)
        self.chart.addAxis(self.axisY, QtCore.Qt.AlignLeft)
        self.series.attachAxis(self.axisX)
        self.series.attachAxis(self.axisY)

        # Create a chart view to display the chart
        self.chart_view = QtCharts.QChartView(self.chart)
        self.chart_view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.chart.legend().hide()  # Hide the legend
        self.chart_view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.chart_view.setFocusPolicy(QtCore.Qt.NoFocus)

        # Add the chart view to the layout
        self.charts_layout.addWidget(self.chart_view)

        self.mass_pressure_series = QtCharts.QScatterSeries()
        self.mass_pressure_series.setColor(QtCore.Qt.white)
        self.mass_pressure_series.setMarkerSize(3.0)
        self.mass_pressure_chart = QtCharts.QChart()
        self.mass_pressure_chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.mass_pressure_chart.setBackgroundBrush(QtGui.QBrush(self.color_dict['dark_gray']))  # Set the background color to grey
        self.mass_pressure_chart.addSeries(self.mass_pressure_series)
        self.mass_pressure_chart.setTitle("Mass versus Pressure")

        self.mass_pressure_axisX = QtCharts.QValueAxis()
        self.mass_pressure_axisX.setTitleText("Pressure (psi)")
        self.mass_pressure_axisY = QtCharts.QValueAxis()
        self.mass_pressure_axisY.setTitleText("Mass (g)")

        self.mass_pressure_chart.addAxis(self.mass_pressure_axisX, QtCore.Qt.AlignBottom)
        self.mass_pressure_chart.addAxis(self.mass_pressure_axisY, QtCore.Qt.AlignLeft)
        self.mass_pressure_series.attachAxis(self.mass_pressure_axisX)
        self.mass_pressure_series.attachAxis(self.mass_pressure_axisY)

        # Create a series for the linear fit
        self.linear_fit_series = QtCharts.QLineSeries()
        self.linear_fit_series.setColor(QtCore.Qt.red)
        self.mass_pressure_chart.addSeries(self.linear_fit_series)
        self.linear_fit_series.attachAxis(self.mass_pressure_axisX)
        self.linear_fit_series.attachAxis(self.mass_pressure_axisY)

        # Create a chart view to display the chart
        self.mass_pressure_chart_view = QtCharts.QChartView(self.mass_pressure_chart)
        self.mass_pressure_chart_view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.mass_pressure_chart.legend().hide()  # Hide the legend
        self.mass_pressure_chart_view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.mass_pressure_chart_view.setFocusPolicy(QtCore.Qt.NoFocus)

        # Add the chart view to the layout
        self.charts_layout.addWidget(self.mass_pressure_chart_view)

        self.layout.addLayout(self.charts_layout)
        self.setLayout(self.layout)
        # List to store the mass and pressure values from each calibration pass
        previous_data = self.printer_head.get_calibrations()
        # print(self.mass_pressure_data)
        if len(previous_data) >= 2:
            response = self.main_window.popup_yes_no("Use previous calibration data","Would you like to use the previous calibration data?")
            if response == '&No':
                self.mass_pressure_data = []
            elif response == '&Yes':
                self.mass_pressure_data = previous_data
                target_psi = self.calculate_pressure_from_fit(self.target_mass,self.mass_pressure_data)
                self.machine.set_absolute_pressure(target_psi)
                self.target_pressure = target_psi
                self.update_mass_pressure_plot()
        else:
            self.mass_pressure_data = []

        self.get_mass_timer = QTimer()
        self.get_mass_timer.timeout.connect(self.get_recent_mass)
        self.get_mass_timer.start(50)  # Check balance every 50 msec

        self.printing = False
        self.print_delay_timer = QTimer()
        self.print_delay_timer.setSingleShot(True)
        self.print_delay_timer.timeout.connect(self.end_print_delay)
    
    def update_mass_pressure_plot(self):
        self.mass_pressure_series.clear()
        for pressure, mass in self.mass_pressure_data:
            self.mass_pressure_series.append(pressure, mass)
        
        if len(self.mass_pressure_data) >= 2:
            # Calculate the linear fit
            pressures, masses = zip(*self.mass_pressure_data)
            slope, intercept = np.polyfit(pressures, masses, 1)

            # Update the linear fit series
            self.linear_fit_series.clear()
            min_pressure = min(pressures)
            max_pressure = max(pressures)
            self.linear_fit_series.append(min_pressure, min_pressure * slope + intercept)
            self.linear_fit_series.append(max_pressure, max_pressure * slope + intercept)

        min_pressure = min(pressure for pressure, mass in self.mass_pressure_data) - 0.5
        max_pressure = max(pressure for pressure, mass in self.mass_pressure_data) + 0.5
        min_mass = min(mass for pressure, mass in self.mass_pressure_data) - 0.5
        max_mass = max(mass for pressure, mass in self.mass_pressure_data) + 0.5

        self.mass_pressure_axisX.setRange(min_pressure, max_pressure)
        self.mass_pressure_axisY.setRange(min_mass, max_mass)

    def get_recent_mass(self):
        mass = self.balance.get_recent_mass()

        if mass is not None:
            self.add_mass_to_log(mass)
            self.update_mass_plot()

            if self.printing:
                return
            
            self.check_stability()
            
            if self.stable:
                self.label.setText("Stable mass detected")
                self.log_stable_mass(mass)

    def update_mass_plot(self):
        self.series.clear()
        for i, mass in enumerate(self.mass_log):
            self.series.append(i, mass)

        min_mass = min(self.mass_log) - 0.5
        max_mass = max(self.mass_log) + 0.5
        self.axisY.setRange(min_mass, max_mass)

    def add_mass_to_log(self, mass):
        self.mass_log.append(mass)
        if len(self.mass_log) > 300:
            self.mass_log.pop(0)
    
    def check_stability(self):
        if len(self.mass_log) > 10:
            recent_masses = self.mass_log[-10:]
            std_dev = np.std(recent_masses)
            if std_dev < self.tolerance:
                self.stable_count += 1
            else:
                self.stable_count = 0
            if self.stable_count > 10:
                self.stable = True
            else:
                self.stable = False
        else:
            self.stable = False

    def log_stable_mass(self, mass):

        if self.init_mass is None:
            self.init_mass = mass
            self.label.setText(f"Initial mass: {self.init_mass} g")
            self.print_droplets()

        elif self.final_mass is None:
            self.final_mass = mass
            self.label.setText(f"Final mass: {self.final_mass} g")
            self.adjust_pressure()
        else:
            print("Both initial and final mass have already been measured.")
            self.init_mass = self.final_mass
            self.final_mass = None

    def adjust_pressure(self):
        mass_change = (self.final_mass - self.init_mass)
        current_psi = self.model.machine_model.get_current_pressure()
        self.mass_pressure_data.append((current_psi, mass_change))
        self.update_mass_pressure_plot()
        
        #print(f"Mass change: {mass_change} g, Target drop mass: {self.target_mass} g")
        if abs(mass_change - self.target_mass) < self.mass_tolerance:  # If the droplet mass is close enough to the target
            self.label.setText("Calibration complete!")
            print("=== Calibration complete! ===")
            self.printer_head.add_calibration(self.mass_pressure_data)
            self.calibration_complete.emit()
            self.get_mass_timer.stop()

        else:
            response = self.main_window.popup_yes_no("Pressure Calibration",f"Would you like to adjust the pressure? Current mass change: {mass_change} g, Target drop mass: {self.target_mass} g")
            if response == '&No':
                self.get_mass_timer.stop()
                return

            if len(self.mass_pressure_data) >= 2:
                # Calculate the linear fit
                target_psi = self.calculate_pressure_from_fit(self.target_mass,self.mass_pressure_data)
            else:
                proportion = mass_change / self.target_mass
                target_psi = current_psi / proportion

            if target_psi > self.psi_max:
                target_psi = self.psi_max
            elif target_psi < self.min_pressure:
                target_psi = self.min_pressure

            if target_psi - current_psi > self.max_pressure_step:
                print('Over max pressure step')
                target_psi = current_psi + self.max_pressure_step
            elif current_psi - target_psi > self.max_pressure_step:
                print('Under max pressure step')
                target_psi = current_psi - self.max_pressure_step
            self.main_window.popup_message("Pressure Calibration",f"Adjusting pressure from {current_psi} to {target_psi} psi")
            #print(f"- Adjusting pressure from {current_psi} to {target_psi} psi")
            self.label.setText(f"Adjusted pressure to {target_psi} psi")
            self.change_pressure.emit(target_psi)
            # Here you should add code to adjust the machine's pressure
            self.init_mass = None
            self.final_mass = None

    def calculate_pressure_from_fit(self, target_mass,mass_pressure_data):
        pressures, masses = zip(*mass_pressure_data)
        slope, intercept = np.polyfit(pressures, masses, 1)
        target_psi = (target_mass - intercept) / slope
        return float(target_psi)

    def print_droplets(self):
        # Add code to print droplets here
        self.print_calibration_droplets.emit(100)
        self.printing = True
        print('--- Start of print delay ---')
        self.print_delay_timer.start(5000)  # 5 second delay

    def end_print_delay(self):
        print('--- End of print delay ---')
        self.printing = False


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
            self.main_window.popup_message("Gripper Empty","Please load the calibration chip into the gripper before calibrating the rack.")
            return
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
        dialog = ExperimentDesignDialog(self.main_window, self.model)
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
        super().__init__("MOVEMENT")
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
            self.main_window.popup_message("Gripper Empty","Please load the calibration chip into the gripper before calibrating the rack.")
            return
        rack_calibration_dialog = RackCalibrationDialog(self.main_window,self.model,self.controller)
        
        # Execute the dialog and check if the user completes the calibration
        if rack_calibration_dialog.exec() == QDialog.Accepted:
            print("Calibration completed successfully.")
            self.model.rack_model.update_calibration_data()
        else:
            print("Calibration was canceled or failed.")
            self.model.rack_model.discard_temp_calibrations()
            # self.model.well_plate.discard_temp_calibrations()

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

        self.init_ui()

        # Connect model signals to the update methods
        self.model.machine_state_updated.connect(self.update_status)
        self.model.location_model.locations_updated.connect(self.update_status)
        self.model.machine_model.machine_paused.connect(self.update_status)
        self.model.machine_model.home_status_signal.connect(self.update_status)
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
            'Mass': QLabel('0'),
            'Stable': QLabel('False')
        }

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
    def __init__(self, main_window, model):
        super().__init__()
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.experiment_model = self.model.experiment_model
        self.setWindowTitle("Experiment Design")
        self.setFixedSize(1500, 600)

        self.layout = QHBoxLayout(self)
        print('NEW WINDOW')
        self.no_changes = True
        self.load_progress = False
        
        # Table to hold all reagent information
        self.reagent_table = QTableWidget(0, 13, self)
        self.reagent_table.setHorizontalHeaderLabels([
            "Reagent Name", "Min Conc", "Max Conc", "Steps", 
            "Mode", "Manual Input", "Units", "Max Droplets",
            "Concentrations Preview", "Conc Step Sizes", "Missing", "Used","Delete"
        ])
        self.reagent_table.setColumnWidth(0, 100)
        self.reagent_table.setColumnWidth(1, 75)
        self.reagent_table.setColumnWidth(2, 75)
        self.reagent_table.setColumnWidth(3, 50)
        self.reagent_table.setColumnWidth(6, 75)
        self.reagent_table.setColumnWidth(8, 200)
        self.reagent_table.setColumnWidth(9, 100)
        self.reagent_table.setColumnWidth(10, 100)
        self.reagent_table.setColumnWidth(11, 50)
        self.reagent_table.setColumnWidth(12, 50)
        self.reagent_table.setSelectionMode(QAbstractItemView.NoSelection)

        self.reagent_table.setWordWrap(True)

        # Stock solutions table
        self.stock_table = QTableWidget(0, 5, self)
        self.stock_table.setHorizontalHeaderLabels([
            "Reagent Name", "Concentration", "Units", "Total\nDroplets", "Total\nVolume (uL)"
        ])
        self.stock_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.stock_table.setFixedWidth(350)
        self.stock_table.setColumnWidth(0, 100)
        self.stock_table.setColumnWidth(1, 100)
        self.stock_table.setColumnWidth(2, 50)
        self.stock_table.setColumnWidth(3, 50)
        self.stock_table.setColumnWidth(4, 100)

        self.left_layout = QVBoxLayout()
        self.left_layout.addWidget(self.reagent_table)
        self.bottom_layout = QHBoxLayout()

        self.right_layout = QVBoxLayout()
        self.right_layout.addWidget(self.stock_table)

        self.bottom_layout = QHBoxLayout()
        # Label and spin box for total reactions and replicates
        self.info_layout = QVBoxLayout()

        # Add text edit field for experiment name
        self.experiment_name_label = QLabel("Experiment Name:", self)
        self.experiment_name_input = QLineEdit(self)
        self.experiment_name_input.setText(self.experiment_model.metadata.get("name", "Experiment"))
        self.experiment_name_input.textChanged.connect(self.update_experiment_name)
        self.info_layout.addWidget(self.experiment_name_label)
        self.info_layout.addWidget(self.experiment_name_input)

        self.replica_label = QLabel("Replicates:", self)
        self.replicate_spinbox = QSpinBox(self)
        self.replicate_spinbox.setMinimum(1)
        self.replicate_spinbox.setMaximum(384)
        self.replicate_spinbox.setValue(self.experiment_model.metadata.get("replicates", 1))
        self.replicate_spinbox.valueChanged.connect(self.update_model_metadata)
        self.info_layout.addWidget(self.replica_label)
        self.info_layout.addWidget(self.replicate_spinbox)

        ## Add a reduction factor spinbox
        self.reduction_factor_label = QLabel("Reduction Factor:", self)
        self.reduction_factor_spinbox = QSpinBox(self)
        self.reduction_factor_spinbox.setMinimum(1)
        self.reduction_factor_spinbox.setMaximum(10)
        self.reduction_factor_spinbox.setValue(self.experiment_model.metadata.get("reduction_factor", 1))
        self.reduction_factor_spinbox.valueChanged.connect(self.update_model_metadata)
        self.info_layout.addWidget(self.reduction_factor_label)
        self.info_layout.addWidget(self.reduction_factor_spinbox)

        self.total_droplets_label = QLabel("Total Droplets Available:", self)
        self.total_droplets_spinbox = QSpinBox(self)
        self.total_droplets_spinbox.setMinimum(1)
        self.total_droplets_spinbox.setMaximum(1000)
        self.total_droplets_spinbox.setValue(self.experiment_model.metadata.get("max_droplets", 20))
        self.total_droplets_spinbox.valueChanged.connect(self.update_model_metadata)

        # Add the fill reagent label and input field
        self.fill_reagent_label = QLabel("Fill Reagent:", self)
        self.fill_reagent_input = QLineEdit(self)
        self.fill_reagent_input.setText(self.experiment_model.metadata.get("fill_reagent", 'Water'))  # Set default value
        self.fill_reagent_input.textChanged.connect(self.update_fill_reagent)

        self.start_row_label = QLabel("Start Row",self)
        self.start_row_spinbox = QSpinBox(self)
        self.start_row_spinbox.setMinimum(0)
        self.start_row_spinbox.setMaximum(15)
        self.start_row_spinbox.setValue(self.experiment_model.metadata.get("start_row", 0))
        self.start_row_spinbox.valueChanged.connect(self.update_model_metadata)

        self.start_col_label = QLabel("Start Col",self)
        self.start_col_spinbox = QSpinBox(self)
        self.start_col_spinbox.setMinimum(0)
        self.start_col_spinbox.setMaximum(23)
        self.start_col_spinbox.setValue(self.experiment_model.metadata.get("start_col", 0))
        self.start_col_spinbox.valueChanged.connect(self.update_model_metadata)

        self.total_droplets_used_label = QLabel("Total Droplets Used: 0", self)

        self.total_reactions_label = QLabel("Total Reactions: 0", self)        

        self.info_layout.addWidget(self.total_droplets_label)
        self.info_layout.addWidget(self.total_droplets_spinbox)
        self.info_layout.addWidget(self.fill_reagent_label)
        self.info_layout.addWidget(self.fill_reagent_input)
        self.info_layout.addWidget(self.start_row_label)
        self.info_layout.addWidget(self.start_row_spinbox)
        self.info_layout.addWidget(self.start_col_label)
        self.info_layout.addWidget(self.start_col_spinbox)
        self.info_layout.addWidget(self.total_droplets_used_label)
        self.info_layout.addWidget(self.total_reactions_label)

        self.button_layout = QVBoxLayout()
        # Button to add a new reagent
        self.add_reagent_button = QPushButton("Add Reagent")
        self.add_reagent_button.clicked.connect(self.add_reagent)
        self.button_layout.addWidget(self.add_reagent_button)


        self.randomize_wells_button = QPushButton("Randomize Wells")
        self.randomize_wells_button.setCheckable(True)
        self.randomize_wells_button.setChecked(self.experiment_model.metadata.get("randomize_wells", False))
        self.randomize_wells_button.toggled.connect(self.update_randomize_wells)                       # Checkable button to specify if the wells should be randomized or not       
        self.button_layout.addWidget(self.randomize_wells_button) 
        
        # # Button to update the table
        # self.update_table_button = QPushButton("Update Table")
        # self.update_table_button.clicked.connect(self.update_all_model_reagents)
        # self.button_layout.addWidget(self.update_table_button)

        # Button to create a new experiment
        self.new_experiment_button = QPushButton("New Experiment")
        self.new_experiment_button.clicked.connect(self.new_experiment)
        self.button_layout.addWidget(self.new_experiment_button)

        # Button to load an experiment
        self.load_experiment_button = QPushButton("Load Experiment")
        self.load_experiment_button.clicked.connect(self.load_experiment)
        self.button_layout.addWidget(self.load_experiment_button)

        # Button to save the experiment
        self.save_experiment_button = QPushButton("Save Experiment")
        self.save_experiment_button.setStyleSheet(f"background-color: {self.color_dict['dark_blue']}; color: white;")
        self.save_experiment_button.clicked.connect(self.save_experiment)
        self.button_layout.addWidget(self.save_experiment_button)

        # Button to duplicate the experiment and save it as a new one
        self.duplicate_experiment_button = QPushButton("Duplicate Experiment")
        self.duplicate_experiment_button.clicked.connect(self.duplicate_experiment)
        self.button_layout.addWidget(self.duplicate_experiment_button)

        # Button to generate the experiment
        self.generate_experiment_button = QPushButton("Generate Experiment")
        self.generate_experiment_button.setStyleSheet(f"background-color: {self.color_dict['dark_red']}; color: white;")
        self.generate_experiment_button.clicked.connect(self.close)
        self.button_layout.addWidget(self.generate_experiment_button)

        self.bottom_layout.addLayout(self.info_layout)
        self.bottom_layout.addLayout(self.button_layout)
        self.left_layout.addLayout(self.bottom_layout)

        self.layout.addLayout(self.left_layout)
        self.layout.addLayout(self.right_layout)

        # Connect model signals
        self.experiment_model.data_updated.connect(self.update_preview)
        self.experiment_model.stock_updated.connect(self.update_stock_table)
        self.experiment_model.experiment_generated.connect(self.update_total_reactions)
        self.experiment_model.unsaved_changes_signal.connect(self.update_save_button)
        self.experiment_model.unsaved_changes_signal.connect(self.update_change_tracker)

        self.load_experiment_to_view()

        if self.model.rack_model.get_gripper_printer_head() != None:
            self.activate_read_only_mode(title="Experiment Design (Read-Only) - Unload gripper to edit or create new experiment",fully_restrict=True)
        elif self.experiment_in_progress(self.experiment_model.progress_file_path):
            self.activate_read_only_mode(title="Experiment Design (Read-Only) - Clear progress to edit")
        else:
            self.activate_edit_mode()

    def update_save_button(self):
        """Change the color of the save button if the experiment has unsaved changes."""
        if self.experiment_model.unsaved_changes:
            self.save_experiment_button.setStyleSheet(f"background-color: {self.color_dict['dark_blue']}; color: white;")
        else:
            self.save_experiment_button.setStyleSheet(f"background-color: {self.color_dict['darker_gray']}; color: white;")
    
    def update_change_tracker(self):
        """Update the change tracker to indicate if changes have been made."""
        if self.experiment_model.unsaved_changes:
            # self.no_changes = False
            print('Changes made')
        else:
            # self.no_changes = True
            print('No changes made')
    
    def update_experiment_name(self):
        """Update the experiment name in the model."""
        new_name = self.experiment_name_input.text()
        self.experiment_model.rename_experiment(new_name)

    def update_randomize_wells(self, checked):
        """Update the model with the randomize wells setting."""
        if not checked:
            self.randomize_wells_button.setText("Randomize Wells")
            print('Setting the random seed to None')
            # self.experiment_model.metadata["random_seed"] = None
            self.experiment_model.change_random_seed(remove_seed=True)
        else:
            self.randomize_wells_button.setText("Randomized")
            self.experiment_model.change_random_seed(remove_seed=False)
        self.no_changes = False

    def add_reagent(self, name="", min_conc=0.0, max_conc=1.0, steps=2, mode="Linear", manual_input="", units='mM',max_droplets=10,stock_solutions="",droplets_used="",view_only=False):
        """Add a new reagent row to the table and model."""
        row_position = self.reagent_table.rowCount()
        self.reagent_table.insertRow(row_position)

        # Generate a default name for the reagent
        if not name:
            name = f"reagent-{row_position + 1}"
        reagent_name_item = QLineEdit(name)
        self.reagent_table.setCellWidget(row_position, 0, reagent_name_item)

        min_conc_item = QDoubleSpinBox()
        min_conc_item.setMinimum(0.0)
        min_conc_item.setValue(min_conc)
        self.reagent_table.setCellWidget(row_position, 1, min_conc_item)

        max_conc_item = QDoubleSpinBox()
        max_conc_item.setMinimum(0.0)
        max_conc_item.setMaximum(1000.0)
        max_conc_item.setValue(max_conc)
        self.reagent_table.setCellWidget(row_position, 2, max_conc_item)

        steps_item = QSpinBox()
        steps_item.setMinimum(1)
        steps_item.setValue(steps)
        self.reagent_table.setCellWidget(row_position, 3, steps_item)

        mode_item = QComboBox()
        mode_item.addItems(["Linear", "Quadratic", "Logarithmic", "Manual"])
        mode_item.setCurrentText(mode)
        self.reagent_table.setCellWidget(row_position, 4, mode_item)

        manual_conc_item = QLineEdit(manual_input)
        manual_conc_item.setPlaceholderText("e.g., 0.1, 0.5, 1.0")
        manual_conc_item.setEnabled(mode == "Manual")  # Enabled only if mode is "Manual"
        self.reagent_table.setCellWidget(row_position, 5, manual_conc_item)

        unit_item = QComboBox()
        unit_item.addItems(['mM','uM','M','g/L','ng/uL','%','__'])
        unit_item.setCurrentText(units)
        self.reagent_table.setCellWidget(row_position, 6, unit_item)


        max_droplets_item = QSpinBox()
        max_droplets_item.setMinimum(1)
        max_droplets_item.setMaximum(1000)
        max_droplets_item.setValue(max_droplets)
        self.reagent_table.setCellWidget(row_position, 7, max_droplets_item)

        preview_item = QTableWidgetItem()
        preview_item.setTextAlignment(Qt.AlignCenter)
        self.reagent_table.setItem(row_position, 8, preview_item)

        stock_solutions_item = QLineEdit(stock_solutions)
        stock_solutions_item.setPlaceholderText("e.g., 0.5, 1, 5")
        self.reagent_table.setCellWidget(row_position, 9, stock_solutions_item)

        missing_conc_item = QTableWidgetItem()
        missing_conc_item.setTextAlignment(Qt.AlignCenter)
        self.reagent_table.setItem(row_position, 10, missing_conc_item)

        droplets_used_item = QTableWidgetItem()
        droplets_used_item.setTextAlignment(Qt.AlignCenter)
        self.reagent_table.setItem(row_position, 11, droplets_used_item)

        # Delete button
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(lambda: self.delete_reagent(row_position))
        self.reagent_table.setCellWidget(row_position, 12, delete_button)

        if not view_only:
            # Add reagent to model
            self.experiment_model.add_reagent(
                name=name,
                min_conc=min_conc,
                max_conc=max_conc,
                steps=steps,
                mode=mode,
                manual_input=manual_input,
                units=units,
                max_droplets=max_droplets,
                stock_solutions=stock_solutions
            )

        # Connect signals after initializing the row to avoid 'NoneType' errors
        reagent_name_item.textChanged.connect(lambda: self.update_model_reagent(row_position))
        min_conc_item.valueChanged.connect(lambda: self.update_model_reagent(row_position))
        max_conc_item.valueChanged.connect(lambda: self.update_model_reagent(row_position))
        steps_item.valueChanged.connect(lambda: self.update_model_reagent(row_position))
        mode_item.currentIndexChanged.connect(lambda: self.update_model_reagent(row_position))
        mode_item.currentIndexChanged.connect(lambda: self.toggle_manual_entry(row_position))
        unit_item.currentIndexChanged.connect(lambda: self.update_model_reagent(row_position))
        manual_conc_item.textChanged.connect(lambda: self.update_model_reagent(row_position))
        max_droplets_item.valueChanged.connect(lambda: self.update_model_reagent(row_position))
        stock_solutions_item.textChanged.connect(lambda: self.update_model_reagent(row_position))
        # if not view_only:
        self.update_model_reagent(row_position)
        self.no_changes = False

    def delete_reagent(self, row):
        reagent_name = self.reagent_table.cellWidget(row, 0).text()
        self.experiment_model.delete_reagent(reagent_name)
        self.reagent_table.removeRow(row)
        self.no_changes = False

    def activate_read_only_mode(self,title="Experiment Design (Read-Only)",fully_restrict=False):
        """Disable all input fields in the table and the rest of the window."""
        self.setWindowTitle(title)
        self.experiment_name_input.setReadOnly(True)
        self.total_droplets_spinbox.setReadOnly(True)
        self.replicate_spinbox.setReadOnly(True)
        self.fill_reagent_input.setReadOnly(True)
        self.randomize_wells_button.setDisabled(True)
        self.add_reagent_button.setDisabled(True)
        if fully_restrict:
            self.load_experiment_button.setDisabled(True)
            self.duplicate_experiment_button.setDisabled(True)
            self.new_experiment_button.setDisabled(True)
            self.save_experiment_button.setDisabled(True)
            self.generate_experiment_button.setDisabled(True)
        self.save_experiment_button.setDisabled(True)
        self.generate_experiment_button.setDisabled(True)
        self.reagent_table.setDisabled(True)
        self.stock_table.setDisabled(True)
        self.generate_experiment_button.setStyleSheet(f"background-color: {self.color_dict['dark_gray']}; color: white;")


    def activate_edit_mode(self):
        """Enable all input fields in the table and the rest of the window."""
        self.setWindowTitle("Experiment Design")
        self.experiment_name_input.setReadOnly(False)
        self.total_droplets_spinbox.setReadOnly(False)
        self.replicate_spinbox.setReadOnly(False)
        self.fill_reagent_input.setReadOnly(False)
        self.randomize_wells_button.setDisabled(False)
        self.add_reagent_button.setDisabled(False)
        # self.update_table_button.setDisabled(False)
        self.load_experiment_button.setDisabled(False)
        self.save_experiment_button.setDisabled(False)
        self.generate_experiment_button.setDisabled(False)
        self.reagent_table.setDisabled(False)
        self.stock_table.setDisabled(False)
        self.generate_experiment_button.setStyleSheet(f"background-color: {self.color_dict['dark_red']}; color: white;")


    def update_model_reagent(self, row,mark_change=True):
        """Update the reagent in the model based on the current row values."""
        name = self.reagent_table.cellWidget(row, 0).text()
        min_conc = self.reagent_table.cellWidget(row, 1).value()
        max_conc = self.reagent_table.cellWidget(row, 2).value()
        steps = self.reagent_table.cellWidget(row, 3).value()
        mode = self.reagent_table.cellWidget(row, 4).currentText()
        manual_input = self.reagent_table.cellWidget(row, 5).text()
        units = self.reagent_table.cellWidget(row, 6).currentText()
        max_droplets = self.reagent_table.cellWidget(row, 7).value()
        stock_solutions = self.reagent_table.cellWidget(row, 9).text()

        self.experiment_model.update_reagent(row, name=name, min_conc=min_conc, max_conc=max_conc, steps=steps, mode=mode, manual_input=manual_input, units=units,max_droplets=max_droplets,stock_solutions=stock_solutions)
        if mark_change:
            self.no_changes = False

    def update_all_model_reagents(self):
        """Update all reagents in the model based on the current row values."""
        for row in range(self.reagent_table.rowCount()):
            self.update_model_reagent(row,mark_change=False)

    def update_model_metadata(self,mark_change=True):
        """Update the metadata in the model based on the current values."""
        replicates = self.replicate_spinbox.value()
        max_droplets = self.total_droplets_spinbox.value()
        reduction_factor = self.reduction_factor_spinbox.value()
        start_row = self.start_row_spinbox.value()
        start_col = self.start_col_spinbox.value()
        self.experiment_model.update_metadata(replicates, max_droplets, reduction_factor,start_row,start_col)
        if mark_change:
            self.no_changes = False

    def update_fill_reagent(self):
        """Update the fill reagent in the model based on the current value."""
        fill_reagent = self.fill_reagent_input.text()
        self.experiment_model.update_fill_reagent_name(fill_reagent)
        self.no_changes = False

    def load_experiment_to_view(self):
        """Load reagents, stock solutions, and metadata from the model to the view."""
        self.reagent_table.setRowCount(0)  # Clear the table first
        print("Loading experiment to view")

        # Temporarily disconnect the signals
        self.experiment_name_input.blockSignals(True)
        self.total_droplets_spinbox.blockSignals(True)
        self.replicate_spinbox.blockSignals(True)
        self.randomize_wells_button.blockSignals(True)

        self.experiment_name_input.setText(self.experiment_model.metadata.get("name", "Untitled Experiment"))
        self.total_droplets_spinbox.setValue(self.experiment_model.metadata.get("max_droplets", 20))
        self.replicate_spinbox.setValue(self.experiment_model.metadata.get("replicates", 1))
        self.fill_reagent_input.setText(self.experiment_model.metadata.get("fill_reagent", 'Water'))
        if self.experiment_model.metadata['random_seed'] is not None:
            self.randomize_wells_button.setChecked(True)
            self.randomize_wells_button.setText("Randomized")

        # Reconnect the signals
        self.experiment_name_input.blockSignals(False)
        self.total_droplets_spinbox.blockSignals(False)
        self.replicate_spinbox.blockSignals(False)
        self.randomize_wells_button.blockSignals(False)
        
        original_reagents = self.experiment_model.get_all_reagents().copy()
        # print(f"Original reagents: {original_reagents}")

        for i, reagent in enumerate(original_reagents):
            # print(f"-=-=-Adding reagent: {reagent}-{i}")

            self.add_reagent(
                name=reagent["name"],
                min_conc=reagent["min_conc"],
                max_conc=reagent["max_conc"],
                steps=reagent["steps"],
                mode=reagent["mode"],
                units=reagent['units'],
                manual_input=reagent["manual_input"],
                max_droplets=reagent["max_droplets"],
                stock_solutions=", ".join(map(str, reagent["stock_solutions"])),
                view_only=True
            )
            self.experiment_model.calculate_concentrations(i,calc_experiment=False)
            self.experiment_model.reset_unsaved_changes()
            self.no_changes = True

    def save_experiment(self):
        """Save the current experiment setup to a new directory."""
        self.update_all_model_reagents()
        self.experiment_model.save_experiment()

    def experiment_in_progress(self, progress_file_path):
        with open(progress_file_path, 'r') as file:
            loaded_data = json.load(file)
        for well_id, well_data in loaded_data.items():
            for stock_id, reagent_data in well_data["reagents"].items():
                if reagent_data["added_droplets"] > 0:
                    return True
                
        return False
    
    def new_experiment(self):
        """Clears all existing experiment design information and data and resets to how the program is at launch"""
        self.model.clear_experiment()
        self.experiment_model.reset_experiment_model()
        self.load_experiment_to_view()
        self.activate_edit_mode()
        self.no_changes = False
        
    
    def load_experiment(self):
        """Load a saved experiment setup from a directory."""
        # Get the directory where the currently executed script is located
        script_dir = os.path.dirname(os.path.abspath(__file__))

        # Define the directory for experiments relative to the script location
        experiment_dir = os.path.join(script_dir, "Experiments")

        # Ensure the directory exists
        if not os.path.exists(experiment_dir):
            os.makedirs(experiment_dir)

        # Ask the user to select the experiment directory
        chosen_dir = QFileDialog.getExistingDirectory(self, "Select Experiment Directory", experiment_dir)

        if chosen_dir:
            # Define the path for the experiment design JSON file within the selected directory
            experiment_file_path = os.path.join(chosen_dir, "experiment_design.json")

            # Check if the experiment design file exists
            if os.path.exists(experiment_file_path):
                self.experiment_model.load_experiment(experiment_file_path,chosen_dir)
                print("\n----Finished model loading----\n")
                self.load_experiment_to_view()
                self.no_changes = False

                calibration_file_path = os.path.join(chosen_dir, "calibration.json")
                if os.path.exists(calibration_file_path):
                    self.model.calibration_model.load_calibration_data(calibration_file_path)
                else:
                    self.model.calibration_model.create_calibration_file(calibration_file_path)
                
                progress_file_path = os.path.join(chosen_dir, "progress.json")
                if os.path.exists(progress_file_path):
                    in_progress = self.experiment_in_progress(progress_file_path)
                    if in_progress:
                        resume = QMessageBox.question(self, "Resume previous run?", 
                                                    "A previous run is saved for this experiment. Do you want to resume the previous run?",
                                                    QMessageBox.Yes | QMessageBox.No)
                        if resume == QMessageBox.No:
                            self.experiment_model.create_progress_file(file_name=progress_file_path)
                            self.load_progress = False
                            return
                        elif resume == QMessageBox.Yes:
                            self.experiment_model.read_progress_file(progress_file_path)
                            self.load_progress = True
                            self.close()
                    else:
                        self.activate_edit_mode()

                else:
                    self.experiment_model.create_progress_file(file_name=progress_file_path) 
                    self.activate_edit_mode()
            else:
                pass

    def duplicate_experiment(self):
        """Open a dialog to duplicate the experiment and save it as a new one.
        The user can choose a new directory for the duplicated experiment. The dialogue also has a toggle button to 
        transfer the calibration data from the original experiment to the duplicated one."""
        # Open a dialog for a new name for the experiment directory
        new_experiment_name, ok = QInputDialog.getText(self, "New Experiment Name", "Enter a name for the new experiment:")
        if not ok:
            return
        # Get the directory where the currently executed script is located
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Define the path to the new experiment directory
        experiment_dir = os.path.join(script_dir, "Experiments", new_experiment_name)
        
        # Check if the directory already exists
        if os.path.exists(experiment_dir):
            overwrite = QMessageBox.question(self, "Overwrite Existing Experiment?", 
                                            "An experiment with the same name already exists. Do you want to overwrite it?",
                                            QMessageBox.Yes | QMessageBox.No)
            # If the user does want to overwrite, delete the existing directory and its contents and create a new one
            if overwrite == QMessageBox.Yes:
                shutil.rmtree(experiment_dir)
                os.makedirs(experiment_dir)
            else:
                return
        else:
            os.makedirs(experiment_dir)
        
        # Ask the user if they would like to transfer the calibration data
        transfer = QMessageBox.question(self, "Transfer Calibration Data?", 
                                            "Do you want to transfer the calibration data to the new experiment?",
                                            QMessageBox.Yes | QMessageBox.No)
        if transfer == QMessageBox.Yes:
            copy_calibrations = True
        else:
            copy_calibrations = False

        # Execute the duplication in the model
        self.experiment_model.duplicate_experiment(new_experiment_name, experiment_dir, copy_calibrations=copy_calibrations)

        # Load the duplicated experiment to the view
        self.load_experiment_to_view()

        # Activate edit mode
        self.activate_edit_mode()

        # Set the flag to indicate that changes have been made
        self.no_changes = False

    

    def toggle_manual_entry(self, row):
        """Enable or disable the manual entry field based on mode selection."""
        mode = self.reagent_table.cellWidget(row, 4).currentText()
        manual_conc_item = self.reagent_table.cellWidget(row, 5)
        manual_conc_item.setEnabled(mode == "Manual")
        self.update_model_reagent(row)

    def update_preview(self, row):
        """Update the concentrations preview in the table based on the model."""
        reagent = self.experiment_model.get_reagent(row)   
        preview_text = ", ".join(map(str, reagent["concentrations"]))
        preview_item = self.reagent_table.item(row, 8)
        if type(preview_item) != type(None):
            preview_item.setText(preview_text)
            preview_item.setToolTip(preview_text)
            preview_item.setTextAlignment(Qt.AlignCenter)

        missing_conc_text = ", ".join(map(str, reagent["missing_concentrations"]))
        missing_conc_item = self.reagent_table.item(row, 10)
        if type(missing_conc_item) != type(None):
            missing_conc_item.setText(missing_conc_text)
            missing_conc_item.setToolTip(missing_conc_text)
            missing_conc_item.setTextAlignment(Qt.AlignCenter)

        droplets_used_text = reagent['max_droplets_for_conc']
        droplets_used_item = self.reagent_table.item(row, 11)
        if type(droplets_used_item) != type(None):
            droplets_used_item.setText(str(droplets_used_text))
            droplets_used_item.setTextAlignment(Qt.AlignCenter)

    def update_stock_table(self):
        # Populate the stock table
        # print("Updating stock table")
        self.stock_table.setRowCount(0)  # Clear existing rows
        for stock_solution in self.experiment_model.get_all_stock_solutions():
            #print(f"---Adding stock solution: {stock_solution}")
            row_position = self.stock_table.rowCount()
            self.stock_table.insertRow(row_position)
            self.stock_table.setItem(row_position, 0, QTableWidgetItem(stock_solution['reagent_name']))
            self.stock_table.setItem(row_position, 1, QTableWidgetItem(str(stock_solution['concentration'])))
            self.stock_table.setItem(row_position, 2, QTableWidgetItem(str(stock_solution['units'])))
            self.stock_table.setItem(row_position, 3, QTableWidgetItem(str(stock_solution['total_droplets'])))
            self.stock_table.setItem(row_position, 4, QTableWidgetItem(str(stock_solution['total_volume'])))

    def complete_experiment_design(self):
        if self.no_changes:
            print('No changes made to the experiment design')
        else:
            print('Changes made to the experiment design')
            self.model.load_experiment_from_model(load_progress=self.load_progress)
            self.no_changes = True

    def generate_experiment(self):
        """Generate the experiment by asking the model to calculate it."""
        self.experiment_model.generate_experiment()

    def update_total_reactions(self, total_reactions, total_droplets_used):
        """Update the total number of reactions displayed."""
        #print(f"Updating total reactions: {total_reactions}, total droplets used: {total_droplets_used}")
        self.total_reactions_label.setText(f"Total Reactions: {total_reactions}")
        
        self.total_droplets_used_label.setText(f"Total Droplets Used: {total_droplets_used}")
        if total_droplets_used > self.total_droplets_spinbox.value():
            self.total_droplets_used_label.setStyleSheet("color: red;")
        else:
            self.total_droplets_used_label.setStyleSheet("color: white;")

    def closeEvent(self, event):
        """Handle the window close event."""
        # self.update_all_model_reagents()  # Update all reagents before closing
        # Add check that there are no missing concentrations
        if self.experiment_model.check_missing_concentrations():
            self.main_window.popup_message("Missing Concentrations","There are missing concentrations. Please fill in all concentrations before closing the window.")
            event.ignore()
            # response = self.main_window.popup_yes_no("Missing Concentrations","There are missing concentrations. Are you sure you want to close the experiment design window?")
            # if response == '&Yes':
            #     self.complete_experiment_design()
            #     event.accept()
            # else:
            #     event.ignore()
        elif self.experiment_model.has_unsaved_changes():
            self.main_window.popup_message("Unsaved Changes","There are unsaved changes. Please save your changes prior to closing the window.")
            event.ignore()
        else:
            self.complete_experiment_design()
            event.accept()
        