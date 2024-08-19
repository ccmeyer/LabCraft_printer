from PySide6 import QtCore, QtWidgets, QtGui, QtCharts
from PySide6.QtWidgets import QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QTableWidget,\
        QTableWidgetItem, QHeaderView, QLabel, QGridLayout, QGroupBox, QPushButton, QComboBox, QSpinBox, QSizePolicy,\
        QSpacerItem, QFileDialog, QInputDialog, QMessageBox, QAbstractItemView
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtCore import Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import numpy as np
import json

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
        self.color_dict = self.load_colors('.\\MVC-interface\\Presets\\Colors.json')

        self.setWindowTitle("Droplet Printer Interface")
        self.init_ui()

        self.controller.error_occurred_signal.connect(self.popup_message)

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
        left_panel.setFixedWidth(400)
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
        self.rack_box.setFixedHeight(200)
        self.rack_box.setStyleSheet(f"background-color: {self.color_dict['darker_gray']};")
        mid_layout.addWidget(self.rack_box)

        self.layout.addWidget(mid_panel)

        # Add other widgets to the right panel as needed
        right_panel = QtWidgets.QWidget()
        right_panel.setFixedWidth(400)
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
        self.shortcut_manager.add_shortcut('Left', 'Move left', lambda: self.controller.set_relative_coordinates(0, -self.model.machine_model.step_size, 0,manual=True))
        self.shortcut_manager.add_shortcut('Right', 'Move right', lambda: self.controller.set_relative_coordinates(0, self.model.machine_model.step_size, 0,manual=True))
        self.shortcut_manager.add_shortcut('Up', 'Move forward', lambda: self.controller.set_relative_coordinates(self.model.machine_model.step_size,0 , 0,manual=True))
        self.shortcut_manager.add_shortcut('Down', 'Move backward', lambda: self.controller.set_relative_coordinates(-self.model.machine_model.step_size,0, 0,manual=True))
        self.shortcut_manager.add_shortcut('k', 'Move up', lambda: self.controller.set_relative_coordinates(0, 0, self.model.machine_model.step_size,manual=True))
        self.shortcut_manager.add_shortcut('m', 'Move down', lambda: self.controller.set_relative_coordinates(0, 0, -self.model.machine_model.step_size,manual=True))
        
        self.shortcut_manager.add_shortcut(
            'Ctrl+Up', 'Increase step size', 
            self.model.machine_model.increase_step_size
        )
        self.shortcut_manager.add_shortcut(
            'Ctrl+Down', 'Decrease step size', 
            self.model.machine_model.decrease_step_size
        )
        self.shortcut_manager.add_shortcut('6','Large pressure decrease', lambda: self.controller.set_relative_pressure(-1,manual=True))
        self.shortcut_manager.add_shortcut('7','Small pressure decrease', lambda: self.controller.set_relative_pressure(-0.1,manual=True))
        self.shortcut_manager.add_shortcut('8','Small pressure increase', lambda: self.controller.set_relative_pressure(0.1,manual=True))
        self.shortcut_manager.add_shortcut('9','Large pressure increase', lambda: self.controller.set_relative_pressure(1,manual=True)) 
        self.shortcut_manager.add_shortcut('1','Add reagent to slot 1', lambda: self.controller.add_reagent_to_slot(0))
        self.shortcut_manager.add_shortcut('2','Add reagent to slot 2', lambda: self.controller.add_reagent_to_slot(1))
        self.shortcut_manager.add_shortcut('3','Add reagent to slot 3', lambda: self.controller.add_reagent_to_slot(2))
        self.shortcut_manager.add_shortcut('4','Add reagent to slot 4', lambda: self.controller.add_reagent_to_slot(3))
        self.shortcut_manager.add_shortcut('s','Save new location', lambda: self.add_new_location())
        self.shortcut_manager.add_shortcut('d','Modify location', lambda: self.modify_location())
        self.shortcut_manager.add_shortcut('l','Move to location', lambda: self.move_to_location(manual=True))
        self.shortcut_manager.add_shortcut('Shift+n','Popup message', lambda: self.popup_message('Title','Message'))
        self.shortcut_manager.add_shortcut('Shift+o','Popup options', lambda: self.popup_options('Title','Message',['Option 1','Option 2','Option 3']))
        self.shortcut_manager.add_shortcut('Shift+y','Popup yes/no', lambda: self.popup_yes_no('Title','Message'))
        self.shortcut_manager.add_shortcut('Shift+i','Popup input', lambda: self.popup_input('Title','Message'))
        self.shortcut_manager.add_shortcut('g','Close gripper', lambda: self.controller.close_gripper())
        self.shortcut_manager.add_shortcut('Shift+g','Open gripper', lambda: self.controller.open_gripper())
        self.shortcut_manager.add_shortcut('Shift+p','Print Array', lambda: self.controller.print_array())
        self.shortcut_manager.add_shortcut('Shift+r','Reset Single Array', lambda: self.reset_single_array())
        self.shortcut_manager.add_shortcut('Shift+e','Reset All Arrays', lambda: self.reset_all_arrays())
        self.shortcut_manager.add_shortcut('Esc', 'Pause Action', lambda: self.pause_machine())

    def make_transparent_icon(self):
        transparent_image = QtGui.QImage(1, 1, QtGui.QImage.Format_ARGB32)
        transparent_image.fill(QtCore.Qt.transparent)
        transparent_pixmap = QtGui.QPixmap.fromImage(transparent_image)
        transparent_icon = QtGui.QIcon(transparent_pixmap)
        return transparent_icon

    def popup_message(self, title, message):
        """Display a popup message with a title and message."""
        print(f"Popup message: {title} - {message}")
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
        self.model.machine_model.ports_updated.connect(self.update_ports)
        self.model.machine_model.machine_state_updated.connect(self.update_machine_connect_button)
        self.model.machine_model.balance_state_updated.connect(self.update_balance_connect_button)

        # Connect signals from the view to the controller
        self.connect_machine_requested.connect(self.controller.connect_machine)
        self.connect_balance_requested.connect(self.controller.connect_balance)
        self.refresh_ports_requested.connect(self.controller.update_available_ports)

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

        # Populate ports initially
        self.update_ports(self.model.machine_model.available_ports)

    def update_ports(self, ports):
        """Update the COM port selections."""
        ports_with_virtual = ports + ["Virtual","COM1"]
        
        self.machine_port_combobox.clear()
        self.balance_port_combobox.clear()
        
        self.machine_port_combobox.addItems(ports_with_virtual)
        self.balance_port_combobox.addItems(ports_with_virtual)

        # Set the default selected port
        self.machine_port_combobox.setCurrentText(self.controller.get_machine_port())
        self.balance_port_combobox.setCurrentText(self.model.machine_model.balance_port)

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

        self.update_regulation_button_state(self.model.machine_model.is_connected())
        self.popup_message_signal.connect(self.main_window.popup_message)

    def init_ui(self):
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout = QtWidgets.QGridLayout(self)

        self.current_pressure_label = QtWidgets.QLabel("Current Pressure:")  # Create a new QLabel for the current pressure label
        self.current_pressure_value = QtWidgets.QLabel()  # Create a new QLabel for the current pressure value
        self.target_pressure_label = QtWidgets.QLabel("Target Pressure:")  # Create a new QLabel for the target pressure label
        self.target_pressure_value = QtWidgets.QLabel()  # Create a new QLabel for the target pressure value

        self.layout.addWidget(self.current_pressure_label, 0, 0)  # Add the QLabel to the layout at position (0, 0)
        self.layout.addWidget(self.current_pressure_value, 0, 1)  # Add the QLabel to the layout at position (0, 1)
        self.layout.addWidget(self.target_pressure_label, 0, 2)  # Add the QLabel to the layout at position (1, 0)
        self.layout.addWidget(self.target_pressure_value, 0, 3)  # Add the QLabel to the layout at position (1, 1)

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

        self.model.machine_model.pressure_updated.connect(self.update_pressure)

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
        self.target_pressure_value.setText(f"{target_pressure:.3f}")

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
        
        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout()
        self.top_layout = QHBoxLayout()
        self.plate_selection_label = QLabel("Plate Format:")
        self.plate_selection_label.setStyleSheet("color: white;")
        self.plate_selection_label.setAlignment(Qt.AlignRight)
        self.top_layout.addWidget(self.plate_selection_label)
        self.plate_selection = QComboBox()
        self.plate_selection.addItems(['96', '384', '1536'])
        # Set the current index to match the model's plate format
        self.plate_selection.setCurrentIndex(self.plate_selection.findText(str(self.model.well_plate.plate_format)))
        self.plate_selection.currentIndexChanged.connect(self.on_plate_selection_changed)
        self.top_layout.addWidget(self.plate_selection)

        self.bottom_layout = QHBoxLayout()
        self.experiment_button = QPushButton("Load Experiment")
        self.experiment_button.clicked.connect(self.on_load_experiment)
        self.bottom_layout.addWidget(self.experiment_button)

        self.reagent_selection = QComboBox()
        self.reagent_selection.addItems(self.model.stock_solutions.get_stock_solution_names_formated())
        self.reagent_selection.currentIndexChanged.connect(self.update_well_colors)
        self.bottom_layout.addWidget(self.reagent_selection)

        self.layout.addLayout(self.top_layout)
        self.layout.addLayout(self.grid_layout)
        self.layout.addLayout(self.bottom_layout)

        self.setLayout(self.layout)
        self.update_grid(self.model.well_plate.plate_format)

    def update_grid(self, plate_format):
        """Update the grid layout to match the selected plate format."""
        self.grid_layout.setSpacing(1)
        self.clear_grid()

        rows, cols = self.model.well_plate._get_plate_dimensions(plate_format)
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
            stock_name = printer_head.get_stock_name()
            self.reagent_selection.setCurrentIndex(self.reagent_selection.findText(stock_name))
            self.update_well_colors()            
    
    def update_well_colors(self):
        """Update the colors of the wells based on the selected reagent's concentration."""
        if not self.model.reaction_collection.is_empty():
            # Get the current reagent selection
            stock_index = self.reagent_selection.currentIndex()
            stock_formatted = self.reagent_selection.itemText(stock_index)
            stock_id = self.model.stock_solutions.get_stock_id_from_formatted(stock_formatted)
            print(f"Stock ID: {stock_id}, Stock Index: {stock_index}, Stock Formatted: {stock_formatted}")
            if stock_id == None:
                print('No reagent selected')
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
        plate_format = self.plate_selection.currentText()
        self.update_grid(plate_format)
        self.model.update_well_plate(plate_format)

    def on_load_experiment(self):
        """Load an experiment CSV file."""
        # Check if a printer head is picked up
        if self.model.rack_model.gripper_printer_head is not None:
            self.main_window.popup_message("Printer Head Loaded", "Please place the printer head back in the rack before loading an experiment.")
            return
        # Check if an experiment is already loaded
        if not self.model.reaction_collection.is_empty():
            response = self.main_window.popup_yes_no("Load Experiment", "An experiment is already loaded. Do you want to clear it and load a new one?")
            if response == "&No":
                return
            else:
                self.model.clear_experiment()
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Experiment CSV", "", "CSV Files (*.csv)")
        if file_path:
            self.model.load_experiment_from_file(file_path)

    def on_experiment_loaded(self):
        """Handle the experiment loaded signal."""
        # Update the options in the reagent selection combobox
        self.reagent_selection.clear()
        self.reagent_selection.addItems(self.model.stock_solutions.get_stock_solution_names_formated())
        self.reagent_selection.setCurrentIndex(0)

        self.update_well_colors()  # Update with a default reagent on load
        print('Completed experiment load')


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

        self.x_min = -15000
        self.x_max = 0
        self.y_min = 0
        self.y_max = 10000
        self.z_min = -35000
        self.z_max = 0

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
        self.z_chart.axisY().setRange(self.z_min, self.z_max)
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
            self.z_series.append(coord[2], 0)

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
        self.z_position_series.append(0,z_pos)


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

        self.gripper_state = QLabel("Closed")
        self.gripper_state.setAlignment(Qt.AlignCenter)
        self.gripper_state.setStyleSheet(f"background-color: {self.color_dict['darker_gray']}; color: white;")
        self.gripper_state.setMaximumHeight(20)
        gripper_layout.addWidget(self.gripper_state)

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

            combined_button = QPushButton("Confirm")
            combined_button.clicked.connect(self.create_combined_button_callback(slot.number))

            swap_combobox = QComboBox()
            swap_combobox.addItem("Swap")
            swap_combobox.currentIndexChanged.connect(self.create_swap_callback(slot.number, swap_combobox))

            slot_layout.addWidget(slot_label)
            slot_layout.addWidget(combined_button)
            # slot_layout.addWidget(confirm_button)
            # slot_layout.addWidget(load_button)
            slot_layout.addWidget(swap_combobox)

            slots_layout.addWidget(slot_widget)
            # self.slot_widgets.append((slot_label, confirm_button, load_button, swap_combobox))
            self.slot_widgets.append((slot_label, combined_button, swap_combobox))

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
    
    def update_button_states(self, machine_connected):
        """Update the button states based on the machine connection state."""
        for _, combined_button, _ in self.slot_widgets:
            combined_button.setEnabled(machine_connected)

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
                    if selected_text == f"{printer_head.get_reagent_name()} ({printer_head.get_stock_concentration()} M)":
                        self.controller.swap_printer_head(slot_number, printer_head)
                        self.update_all_slots()  # Update all dropdowns after swapping
                        self.update_unassigned_printer_heads()  # Update the table to reflect the change
                        return

                # Check if the selected printer head is in another slot
                for i, slot in enumerate(self.rack_model.slots):
                    if i != slot_number and slot.printer_head:
                        slot_text = f"Slot {i+1}: {slot.printer_head.get_reagent_name()} ({slot.printer_head.get_stock_concentration()} M)"
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
        label, combined_button, swap_combobox = self.slot_widgets[slot_number]

        if slot.printer_head:
            printer_head = slot.printer_head
            complete = printer_head.check_complete(self.model.well_plate)
            label.setText(f"{printer_head.get_reagent_name()}\n{printer_head.get_stock_concentration()} M")
            color = QtGui.QColor(printer_head.color)
            color.setAlphaF(0.7)
            rgba_color = f"rgba({color.red()},{color.green()},{color.blue()},{color.alpha()})"
            if complete:
                border_color = 'white'
                label.setStyleSheet(f"background-color: {rgba_color}; border: 2px solid {border_color}; color: white;")
            else:
                label.setStyleSheet(f"background-color: {rgba_color}; color: white;")

            print(f'slot: {slot_number} locked: {slot.locked} confirmed: {slot.confirmed}')
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
            dropdown.addItem(f"{printer_head.get_reagent_name()} ({printer_head.get_stock_concentration()} M)")

        # Add all printer heads in other slots
        for i, slot in enumerate(self.rack_model.slots):
            if i != slot_number and slot.printer_head:
                dropdown.addItem(f"Slot {i+1}: {slot.printer_head.get_reagent_name()} ({slot.printer_head.get_stock_concentration()} M)")
        
        dropdown.blockSignals(False)

    def update_gripper(self):
        """Update the UI when the gripper state changes."""
        if self.rack_model.gripper_printer_head:
            printer_head = self.rack_model.gripper_printer_head
            self.gripper_label.setText(f"{printer_head.get_reagent_name()}\n{printer_head.get_stock_concentration()} M")
            self.gripper_label.setStyleSheet(f"background-color: {printer_head.color}; color: white;")
        else:
            self.gripper_label.setText("Gripper Empty")
            self.gripper_label.setStyleSheet("background-color: none; color: white;")

    def update_unassigned_printer_heads(self):
        """Update the table with unassigned printer heads."""
        unassigned_printer_heads = self.model.printer_head_manager.get_unassigned_printer_heads()
        self.unassigned_table.setRowCount(len(unassigned_printer_heads))

        for row, printer_head in enumerate(unassigned_printer_heads):
            reagent_name = printer_head.get_reagent_name()
            concencentration = printer_head.get_stock_concentration()
            complete = printer_head.check_complete(self.model.well_plate)
            color = printer_head.get_color()
            color = QtGui.QColor(color)
            color.setAlphaF(0.5)

            text_name = f"{reagent_name} - {concencentration} M"
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
        self.model.machine_model.machine_paused.connect(self.update_status)

    def init_ui(self):
        """Initialize the user interface."""
        self.layout = QtWidgets.QGridLayout(self)

        self.labels = {
            'Homed': QLabel('False'),
            'Paused': QLabel('False'),
            'Location': QLabel('Unknown'),
            'Cycle Count': QLabel('0'),
            'Max Cycle Time': QLabel('0')
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
        self.labels['Max Cycle Time'].setText(str(self.model.machine_model.max_cycle))

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
        all_commands = list(self.machine.command_queue.queue) + list(self.machine.command_queue.completed)
        
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