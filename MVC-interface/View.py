from PySide6 import QtCore, QtWidgets, QtGui, QtCharts
from PySide6.QtWidgets import QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QGridLayout, QGroupBox, QPushButton, QComboBox, QSpinBox, QSizePolicy, QSpacerItem
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtCore import Qt

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

        self.setWindowTitle("Machine Status")
        self.init_ui()

    def init_ui(self):
        """Initialize the main user interface."""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QHBoxLayout(self.central_widget)

        # Create the left panel with the motor positions
        left_panel = QtWidgets.QWidget()
        left_panel.setFixedWidth(400)
        left_panel.setStyleSheet(f"background-color: #2c2c2c;")
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        
        # Add ConnectionWidget
        self.connection_widget = ConnectionWidget(self.model, self.controller)
        left_layout.addWidget(self.connection_widget)

        self.coordinates_box = MotorPositionWidget(self.model, self.controller)
        self.coordinates_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        left_layout.addWidget(self.coordinates_box)

        self.pressure_box = PressurePlotBox(self.model, self.controller)
        self.pressure_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        left_layout.addWidget(self.pressure_box)

        self.layout.addWidget(left_panel)

        mid_panel = QtWidgets.QWidget()
        mid_panel.setFixedWidth(800)
        mid_panel.setStyleSheet(f"background-color: #2c2c2c;")
        mid_layout = QtWidgets.QVBoxLayout(mid_panel)

        self.rack_box = RackBox(self.model.rack_model,self.controller)
        self.rack_box.setFixedHeight(200)
        self.rack_box.setStyleSheet(f"background-color: #4d4d4d;")
        mid_layout.addWidget(self.rack_box)

        self.layout.addWidget(mid_panel)

        # Add other widgets to the right panel as needed
        right_panel = QtWidgets.QWidget()
        right_panel.setFixedWidth(300)
        right_panel.setStyleSheet(f"background-color: #4d4d4d;")
        right_layout = QtWidgets.QVBoxLayout(right_panel)

        self.board_status_box = BoardStatusBox(self.model, self.controller)
        self.board_status_box.setStyleSheet(f"background-color: #4d4d4d;")
        self.board_status_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

        right_layout.addWidget(self.board_status_box)

        self.layout.addWidget(right_panel)

        # Set the size of the main window to be 90% of the screen size
        screen_geometry = QApplication.primaryScreen().geometry()
        width = int(screen_geometry.width() * 0.9)
        height = int(screen_geometry.height() * 0.9)
        self.resize(width, height)
        self.setup_shortcuts()

    def setup_shortcuts(self):
        """Set up keyboard shortcuts using the shortcut manager."""
        self.shortcut_manager.add_shortcut('Left', 'Move left', lambda: self.controller.set_relative_coordinates(-self.model.machine_model.step_size, 0, 0,manual=True))
        self.shortcut_manager.add_shortcut('Right', 'Move right', lambda: self.controller.set_relative_coordinates(self.model.machine_model.step_size, 0, 0,manual=True))
        self.shortcut_manager.add_shortcut('Up', 'Move forward', lambda: self.controller.set_relative_coordinates(0, self.model.machine_model.step_size, 0,manual=True))
        self.shortcut_manager.add_shortcut('Down', 'Move backward', lambda: self.controller.set_relative_coordinates(0, -self.model.machine_model.step_size, 0,manual=True))
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

class ConnectionWidget(QGroupBox):
    connect_machine_requested = QtCore.Signal(str)
    connect_balance_requested = QtCore.Signal(str)
    refresh_ports_requested = QtCore.Signal()

    def __init__(self, model,controller):
        super().__init__("Connection Setup")
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
        self.machine_port_combobox.setCurrentText(self.model.machine_model.machine_port)
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
            self.machine_connect_button.setStyleSheet("background-color: #063f99; color: white;")
        else:
            self.machine_connect_button.setText("Connect")
            self.machine_connect_button.setStyleSheet("background-color: #275fb8; color: white;")

    def update_balance_connect_button(self, balance_connected):
        """Update the balance connect button text and color based on the connection state."""
        if balance_connected:
            self.balance_connect_button.setText("Disconnect")
            self.balance_connect_button.setStyleSheet("background-color: #063f99; color: white;")
        else:
            self.balance_connect_button.setText("Connect")
            self.balance_connect_button.setStyleSheet("background-color: #275fb8; color: white;")



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

    def __init__(self, model, controller):
        super().__init__('Motor Positions')
        self.model = model
        self.controller = controller

        self.init_ui()

        # Connect the model's state_updated signal to the update_labels method
        self.model.machine_state_updated.connect(self.update_labels)
        self.model.machine_model.step_size_changed.connect(self.update_step_size)
        self.model.machine_model.motor_state_changed.connect(self.update_motor_button)

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
        self.toggle_motor_button.setCheckable(True)
        self.toggle_motor_button.clicked.connect(self.request_toggle_motors)
        self.toggle_motor_button.setFixedWidth(fixed_width)  # Set fixed width
        self.toggle_motor_button.setFixedHeight(fixed_height)  # Set a fixed height
        button_layout.addWidget(self.toggle_motor_button, alignment=Qt.AlignRight)
        self.update_motor_button(self.model.machine_model.motors_enabled)

        # Add Home button
        self.home_button = QtWidgets.QPushButton("Home")
        self.home_button.clicked.connect(self.request_homing)
        self.home_button.setStyleSheet("background-color: green; color: white;")
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

    def update_motor_button(self, motors_enabled):
        """Update the motor button text and color based on the motor state."""
        if motors_enabled:
            self.toggle_motor_button.setText("Disable Motors")
            self.toggle_motor_button.setStyleSheet("background-color: #063f99; color: white;")
        else:
            self.toggle_motor_button.setText("Enable Motors")
            self.toggle_motor_button.setStyleSheet("background-color: #275fb8; color: white;")


class PressurePlotBox(QtWidgets.QGroupBox):
    """
    A widget to display the pressure readings and target
    """
    toggle_regulation_requested = QtCore.Signal()

    def __init__(self, model,controller):
        super().__init__('Pressure Plot')
        self.model = model
        self.controller = controller
        self.init_ui()
        self.model.machine_model.regulation_state_changed.connect(self.update_regulation_button)
        self.toggle_regulation_requested.connect(self.controller.toggle_regulation)

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
        self.pressure_regulation_button.setCheckable(True)
        self.pressure_regulation_button.clicked.connect(self.request_toggle_regulation)
        self.layout.addWidget(self.pressure_regulation_button, 1, 0, 1, 4)  # Add the button to the layout at position (2, 0) and make it span 2 columns
        self.update_regulation_button(self.model.machine_model.regulating_pressure)

        self.chart = QtCharts.QChart()
        self.chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.chart.setBackgroundBrush(QtGui.QBrush('#4d4d4d'))  # Set the background color to grey
        self.chart_view = QtCharts.QChartView(self.chart)
        self.series = QtCharts.QLineSeries()
        self.series.setColor(QtCore.Qt.white)
        self.chart.addSeries(self.series)

        self.target_pressure_series = QtCharts.QLineSeries()  # Create a new line series for the target pressure
        self.target_pressure_series.setColor(QtCore.Qt.red)  # Set the line color to red
        self.chart.addSeries(self.target_pressure_series)

        self.axisX = QtCharts.QValueAxis()
        self.axisX.setTickCount(3)
        self.axisX.setRange(0, 100)
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
        self.toggle_regulation_requested.emit()

    def update_regulation_button(self, regulating_pressure):
        """Update the motor button text and color based on the motor state."""
        if regulating_pressure:
            self.pressure_regulation_button.setText("Deregulate Pressure")
            self.pressure_regulation_button.setStyleSheet("background-color: #063f99; color: white;")
        else:
            self.pressure_regulation_button.setText("Regulate Pressure")
            self.pressure_regulation_button.setStyleSheet("background-color: #275fb8; color: white;")

class RackBox(QGroupBox):
    """
    A widget to display the reagent rack and the gripper.

    Each slot can contain 0 or 1 printer head. The reagent loaded in the printer head is displayed as a label, and the color of the slot changes to match the printer head color.
    - There is a button below the label to confirm the correct printer head is loaded.
    - There is a button to load the printer head into the gripper of the machine.
    - If the gripper is loaded, the button will unload the gripper to the empty slot.
    - The gripper section shows the printer head currently held by the gripper.
    """

    def __init__(self, rack_model, controller):
        super().__init__("Reagent Rack")
        self.rack_model = rack_model
        self.controller = controller

        self.init_ui()

        # Connect model signals to the update methods
        self.rack_model.slot_updated.connect(self.update_slot)
        self.rack_model.slot_confirmed.connect(self.confirm_slot)
        self.rack_model.gripper_updated.connect(self.update_gripper)

    def init_ui(self):
        """Initialize the user interface."""
        main_layout = QHBoxLayout(self)
        self.setLayout(main_layout)

        # Gripper section
        gripper_widget = QWidget()
        gripper_layout = QVBoxLayout(gripper_widget)
        self.gripper_label = QLabel("Gripper Empty")
        self.gripper_label.setAlignment(Qt.AlignCenter)
        gripper_layout.addWidget(self.gripper_label)

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

            confirm_button = QPushButton("Confirm")
            confirm_button.clicked.connect(self.create_confirm_slot_callback(slot.number))

            load_button = QPushButton("Load")
            load_button.clicked.connect(self.create_toggle_load_callback(slot.number))

            slot_layout.addWidget(slot_label)
            slot_layout.addWidget(confirm_button)
            slot_layout.addWidget(load_button)

            slots_layout.addWidget(slot_widget)
            self.slot_widgets.append((slot_label, confirm_button, load_button))

        # Add slots, spacer, and gripper to the main layout
        main_layout.addWidget(gripper_widget)
        main_layout.addItem(spacer)
        main_layout.addLayout(slots_layout)

    def create_confirm_slot_callback(self, slot_number):
        """Create a callback function for confirming a slot."""
        return lambda: self.controller.confirm_slot(slot_number)

    def create_toggle_load_callback(self, slot_number):
        """Create a callback function for toggling load/unload."""
        return lambda: self.toggle_load(slot_number)

    def update_slot(self, slot_number):
        """Update the UI for a specific slot."""
        slot = self.rack_model.slots[slot_number]
        label, confirm_button, load_button = self.slot_widgets[slot_number]

        if slot.printer_head:
            printer_head = slot.printer_head
            label.setText(f"{printer_head.reagent}\n{printer_head.concentration} M")
            label.setStyleSheet(f"background-color: {printer_head.color}; color: white;")
            load_button.setText("Load")
            confirm_button.setEnabled(not slot.confirmed)
        else:
            label.setText("Empty")
            label.setStyleSheet("background-color: none; color: white;")
            load_button.setText("Load")
            confirm_button.setEnabled(False)

    def confirm_slot(self, slot_number):
        """Update the UI when a slot is confirmed."""
        _, confirm_button, _ = self.slot_widgets[slot_number]
        confirm_button.setText("Confirmed")
        confirm_button.setEnabled(False)

    def update_gripper(self):
        """Update the UI when the gripper state changes."""
        if self.rack_model.gripper_printer_head:
            printer_head = self.rack_model.gripper_printer_head
            self.gripper_label.setText(f"{printer_head.reagent}\n{printer_head.concentration} M")
            self.gripper_label.setStyleSheet(f"background-color: {printer_head.color}; color: white;")
        else:
            self.gripper_label.setText("Gripper Empty")
            self.gripper_label.setStyleSheet("background-color: none; color: white;")

        # Update load buttons based on gripper state and original slot
        for slot_number, (label, _, load_button) in enumerate(self.slot_widgets):
            slot = self.rack_model.slots[slot_number]
            if self.rack_model.gripper_printer_head:
                if slot_number == self.rack_model.gripper_slot_number:
                    load_button.setText("Unload")
                    load_button.setEnabled(True)
                else:
                    load_button.setEnabled(False)
            else:
                load_button.setText("Load")
                load_button.setEnabled(slot.confirmed and slot.printer_head is not None)

    def toggle_load(self, slot_number):
        """Toggle loading/unloading between the slot and gripper."""
        slot = self.rack_model.slots[slot_number]
        if slot.printer_head is None and self.rack_model.gripper_printer_head:
            self.controller.transfer_from_gripper(slot_number)
        elif slot.printer_head and self.rack_model.gripper_printer_head is None:
            self.controller.transfer_to_gripper(slot_number)


class BoardStatusBox(QGroupBox):
    '''
    A widget to display the status of the machine board.
    Displays a grid with the label of the variable from the board and the value of the variable.
    Includes the cycle count and max cycle time for the board.
    '''
    def __init__(self, model, controller):
        super().__init__('Board Status')
        self.model = model
        self.controller = controller

        self.init_ui()

        # Connect model signals to the update methods
        self.model.machine_state_updated.connect(self.update_status)

    def init_ui(self):
        """Initialize the user interface."""
        self.layout = QtWidgets.QGridLayout(self)

        self.labels = {
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
        self.labels['Cycle Count'].setText(str(self.model.machine_model.cycle_count))
        self.labels['Max Cycle Time'].setText(str(self.model.machine_model.max_cycle))


        
        