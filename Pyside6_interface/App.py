from PySide6 import QtCore, QtWidgets, QtGui

from PySide6 import QtCharts
from PySide6.QtCore import QTimer, QPointF
import numpy as np
from Machine import Machine,Command
from CustomWidgets import *


class Shortcut:
    def __init__(self, name, key, function):
        self.name = name
        self.key = key
        self.function = function

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.machine = Machine(self)
        self.shortcuts = [
            Shortcut("Move Forward",QtCore.Qt.Key_Up, lambda: self.machine.move_relative({'X': 0, 'Y': 10, 'Z': 0, 'P': 0})),
            Shortcut("Move Back",QtCore.Qt.Key_Down, lambda: self.machine.move_relative({'X': 0, 'Y': -10, 'Z': 0, 'P': 0})),
            Shortcut("Move Left", QtCore.Qt.Key_Left, lambda: self.machine.move_relative({'X': -10, 'Y': 0, 'Z': 0, 'P': 0})),
            Shortcut("Move Right",QtCore.Qt.Key_Right, lambda: self.machine.move_relative({'X': 10, 'Y': 0, 'Z': 0, 'P': 0})),
            Shortcut("Move Up", "k", lambda: self.machine.move_relative({'X': 0, 'Y': 0, 'Z': 10, 'P': 0})),
            Shortcut("Move Down", "m", lambda: self.machine.move_relative({'X': 0, 'Y': 0, 'Z': -10, 'P': 0})),
            Shortcut("Large Increase Pressure", "9", lambda: self.machine.set_relative_pressure(10)),
            Shortcut("Small Increase Pressure", "8", lambda: self.machine.set_relative_pressure(2)),
            Shortcut("Small Decrease Pressure", "7", lambda: self.machine.set_relative_pressure(-2)),
            Shortcut("Large Decrease Pressure", "6", lambda: self.machine.set_relative_pressure(-10)),
            Shortcut("Regulate Pressure", QtCore.Qt.Key_Plus, lambda: self.machine.regulate_pressure),
            Shortcut("Deregulate Pressure", QtCore.Qt.Key_Minus, lambda: self.machine.deregulate_pressure),
            Shortcut("Print to Console Upper", "P", lambda: self.print_to_console_upper()),
            Shortcut("Print to Console Lower", "p", lambda: self.print_to_console_lower()),
            Shortcut("Add Reagent", "A", lambda: self.add_reagent())
        ]
        self.colors = {
            'black': '#000000',
            'darker_gray': '#2c2c2c',
            'dark_gray': '#4d4d4d',
            'mid_gray': '#6e6e6e',
            'light_gray': '#7c7c7c',
            'white': '#ffffff',
            'red': '#a92222',
            'green': '#1c591e',
            'blue': '#1e64b4',
            'yellow': '#f4d13b',
            'teal': '#26b5b2',
            'orange': '#f4743b',
            'purple': '#842593',
            'brown': '#915b3d',
        }
        self.num_slots = 6
        self.slots = [Slot(i, Reagent('Empty',color=self.colors['red'])) for i in range(self.num_slots)]

        self.reagents = [Reagent('Water',color=self.colors['blue']),Reagent('Mg',self.colors['green']),Reagent('K',self.colors['red']),Reagent('Empty',self.colors['dark_gray'])]
        
        self.setWindowTitle("My App")
        transparent_icon = self.make_transparent_icon()
        self.setWindowIcon(transparent_icon)
        # Create the menu bar
        menu_bar = self.menuBar()

        font_id = QtGui.QFontDatabase.addApplicationFont("./Fonts/Inter.ttc")
        if font_id != -1:  # If the font loaded successfully
            font_families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
            if font_families:  # If the font has any families
                # Create a QFont object
                self.font_obj = QtGui.QFont(font_families[0], 12)  # 10 is the font size, you can change it as per your needs

        # Create a menu
        file_menu = menu_bar.addMenu("File")

        # Create an action for the menu
        exit_action = QtGui.QAction("Exit", self)
        exit_action.triggered.connect(self.close)

        # Add the action to the menu
        file_menu.addAction(exit_action)

        # Create the toolbar
        toolbar = self.addToolBar("Main Toolbar")

        # Add the action to the toolbar
        toolbar.addAction(exit_action)

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)

        layout = QtWidgets.QHBoxLayout(central_widget)

        # Create the status bar
        status_bar = self.statusBar()

        # Show a message on the status bar
        status_bar.showMessage("Ready")

        left_panel = QtWidgets.QWidget()
        left_panel.setFixedWidth(400)
        left_panel.setStyleSheet(f"background-color: {self.colors['dark_gray']};")
        left_layout = QtWidgets.QVBoxLayout(left_panel)  # Use a vertical box layout

        # Create three sections with different numbers of variables
        self.connection_box = DropdownBox("CONNECTION",self)
        self.connection_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.connection_box.machine_connected.connect(self.set_machine_connected_status)
        self.connection_box.balance_connected.connect(self.set_balance_connected_status)
        left_layout.addWidget(self.connection_box)

        self.coordinates_box = CoordinateBox("COORDINATES",self)
        self.coordinates_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        left_layout.addWidget(self.coordinates_box)

        self.pressure_box = PressurePlotBox("PRESSURE", self)
        self.pressure_box.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.pressure_box.regulating_pressure.connect(self.toggle_regulation)

        left_layout.addWidget(self.pressure_box)
        layout.addWidget(left_panel)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_coordinates)
        self.timer.timeout.connect(self.update_pressure)

        self.timer.start(100)  # Update every 100 ms
        
        mid_panel = QtWidgets.QWidget()
        mid_panel.setStyleSheet(f"background-color: {self.colors['darker_gray']};")
        mid_layout = QtWidgets.QVBoxLayout(mid_panel)

        self.custom_widget = CustomWidget(self)
        mid_layout.addWidget(self.custom_widget)

        self.rack_box = RackBox(self,self.slots,self.reagents)
        self.rack_box.setFixedHeight(200)
        self.rack_box.setStyleSheet(f"background-color: {self.colors['dark_gray']};")
        self.rack_box.reagent_loaded.connect(self.change_reagent)
        mid_layout.addWidget(self.rack_box)

        layout.addWidget(mid_panel)

        right_panel = QtWidgets.QWidget()
        right_panel.setFixedWidth(300)
        right_panel.setStyleSheet("background-color: #474747;")
        right_layout = QtWidgets.QVBoxLayout(right_panel)  # Use a vertical box layout

        self.command_box = CommandTable(self.machine.get_command_log())
        self.command_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        right_layout.addWidget(self.command_box)
        self.machine.command_executed.connect(self.add_command)

        self.shortcut_box = ShortcutTable(self.shortcuts)
        self.shortcut_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        right_layout.addWidget(self.shortcut_box)

        layout.addWidget(right_panel)

        # Window dimensions
        geometry = self.screen().availableGeometry()
        self.setFixedSize(geometry.width() * 0.95, geometry.height() * 0.9)

    def keyPressEvent(self, event):
        for shortcut in self.shortcuts:
            if isinstance(shortcut.key, str):  # If the shortcut key is a string
                if event.text() == shortcut.key:  # Convert the string to a key code
                    shortcut.function()
                    break
            elif event.key() == shortcut.key:  # If the shortcut key is a key code
                shortcut.function()
                break
        self.update_coordinates()

    def add_reagent(self):
        self.rack_box.add_reagent()

    def get_reagent_names(self):
        return [reagent.name for reagent in self.reagents if reagent.name != 'Empty']
    
    def make_transparent_icon(self):
        transparent_image = QtGui.QImage(1, 1, QtGui.QImage.Format_ARGB32)
        transparent_image.fill(QtCore.Qt.transparent)
        transparent_pixmap = QtGui.QPixmap.fromImage(transparent_image)
        transparent_icon = QtGui.QIcon(transparent_pixmap)
        return transparent_icon

    def print_to_console_upper(self):
        self.statusBar().showMessage("Print to console upper")

    def print_to_console_lower(self):
        self.statusBar().showMessage("Print to console lower")
    
    def update_coordinates(self):
        current_coords = self.machine.get_coordinates()
        target_coords = self.machine.get_target_coordinates()
        self.coordinates_box.update_coordinates(current_coords,target_coords)

    def update_pressure(self):
        pressure_log = self.machine.get_pressure_log()
        target_pressure = self.machine.get_target_pressure()
        self.pressure_box.update_pressure(pressure_log,target_pressure)

    @QtCore.Slot(str)
    def set_machine_connected_status(self, port):
        if self.connection_box.machine_connect_button.text() == "Disconnect":
            self.machine.deactivate_motors()
            self.statusBar().showMessage("Machine disconnected")
            self.connection_box.machine_connect_button.setStyleSheet(f"background-color: {self.colors['blue']}")
            self.connection_box.machine_connect_button.setText("Connect")
            self.coordinates_box.set_text_bg_color(self.colors['white'],self.colors['dark_gray'])
        elif port == 'COM1':
            self.machine.activate_motors()
            self.statusBar().showMessage(f"Machine connected to port {port}")
            self.connection_box.machine_connect_button.setStyleSheet(f"background-color: {self.colors['red']}")
            self.connection_box.machine_connect_button.setText("Disconnect")
            self.coordinates_box.set_text_bg_color(self.colors['white'],self.colors['darker_gray'])
        else:
            self.machine.deactivate_motors()
            self.statusBar().showMessage("Machine not connected")
            self.connection_box.machine_connect_button.setStyleSheet(f"background-color: {self.colors['blue']}")
            self.connection_box.machine_connect_button.setText("Connect")
            self.coordinates_box.set_text_bg_color(self.colors['white'],self.colors['dark_gray'])

    @QtCore.Slot(str)
    def set_balance_connected_status(self, port):
        if port == 'COM2':
            self.machine.motors_active = True
            self.statusBar().showMessage(f"Balance connected to port {port}")
            self.connection_box.balance_connect_button.setStyleSheet("background-color: #a92222")
            self.connection_box.balance_connect_button.setText("Disconnect")
        else:
            self.machine.motors_active = False
            self.statusBar().showMessage("Balance not connected")
            self.connection_box.balance_connect_button.setStyleSheet("background-color: #1e64b4")
            self.connection_box.balance_connect_button.setText("Connect")
        
    @QtCore.Slot(str)
    def toggle_regulation(self):
        if self.machine.get_regulation_state():
            self.machine.deregulate_pressure()
            self.pressure_box.pressure_regulation_button.setStyleSheet("background-color: #1e64b4")
            self.pressure_box.pressure_regulation_button.setText("Regulate Pressure")
        else:
            self.machine.regulate_pressure()
            self.pressure_box.pressure_regulation_button.setStyleSheet("background-color: #a92222")
            self.pressure_box.pressure_regulation_button.setText("Deregulate Pressure")

    @QtCore.Slot(Command)
    def add_command(self, command):
        self.command_box.add_command(command)

    @QtCore.Slot(Slot)
    def change_reagent(self,slot_obj):
        self.statusBar().showMessage(f"Slot-{slot_obj.number} loaded with {slot_obj.reagent.name}")
        self.rack_box.load_reagent(slot_obj.number, slot_obj.reagent)




if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    # Load the font file
    
    with open("stylesheet.qss", "r") as f:
        app.setStyleSheet(f.read())
    window = MainWindow()
    window.show()
    app.exec()