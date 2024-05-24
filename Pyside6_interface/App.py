from PySide6 import QtCore, QtWidgets, QtGui

from PySide6 import QtCharts
from PySide6.QtCore import QTimer, QPointF
import numpy as np
from Machine import Machine,Command
from CustomWidgets import *
import json
import pandas as pd


class Shortcut:
    def __init__(self, name, key, key_name, function):
            """
            Initialize a new instance of the class.

            Args:
                name (str): The name of the instance.
                key (str): The key of the instance.
                function (callable): The function associated with the instance.
            """
            self.name = name
            self.key = key
            self.key_name = key_name
            self.function = function

class MainWindow(QtWidgets.QMainWindow):
    """
    The main window of the application.

    This class represents the main window of the application and contains various widgets and functionality.
    It inherits from the `QtWidgets.QMainWindow` class.

    Attributes:
        shortcuts (list): A list of shortcuts defined for the application.
        machine (Machine): An instance of the `Machine` class representing the machine used in the application.
        gripper_reagent (Reagent): An instance of the `Reagent` class representing the gripper reagent.
        experiment_name (str): The name of the current experiment.
        all_reactions (pd.DataFrame): A pandas DataFrame containing all the reactions.
        reaction_metadata (pd.DataFrame): A pandas DataFrame containing the metadata of the reactions.
        wells_df (pd.DataFrame): A pandas DataFrame containing the wells information.
        full_array (pd.DataFrame): A pandas DataFrame containing the full array information.
        communication_timer (QTimer): A QTimer object for updating machine states.
        num_slots (int): The number of slots in the rack.
        slots (list): A list of Slot objects representing the slots in the rack.

    Methods:
        update_plate_box: Updates the plate box widget.
        print_status: Prints a status message on the status bar.
        popup_message: Displays a popup message box.
        read_reagents_file: Reads the reagents from a JSON file.
        write_reagents_file: Writes the reagents to a JSON file.
        select_experiment_directory: Opens a file dialog to select an experiment directory.
        load_experiment: Loads an experiment from the selected directory.
        get_printing_reagents: Returns a list of reagents used in the printing process.
        set_cartridges: Sets the cartridges in the rack based on the printing reagents.
        read_colors_file: Reads the colors from a JSON file.
        keyPressEvent: Overrides the key press event handler.
    """

    def __init__(self):
        super().__init__()
        self.shortcuts = [
            Shortcut("Move Forward",QtCore.Qt.Key_Up, "Up", lambda: self.machine.set_relative_coordinates(self.step_size,0,0)),
            Shortcut("Move Back",QtCore.Qt.Key_Down,"Down", lambda: self.machine.set_relative_coordinates(-self.step_size,0,0)),
            Shortcut("Move Left", QtCore.Qt.Key_Left,"Left", lambda: self.machine.set_relative_coordinates(0,-self.step_size,0)),
            Shortcut("Move Right",QtCore.Qt.Key_Right, "Right", lambda: self.machine.set_relative_coordinates(0,self.step_size,0)),
            Shortcut("Move Up", "k", "k", lambda: self.machine.set_relative_coordinates(0,0,self.step_size)),
            Shortcut("Move Down", "m","m", lambda: self.machine.set_relative_coordinates(0,0,-self.step_size)),
            Shortcut("Large Increase Pressure", "9","9", lambda: self.machine.set_relative_pressure(0.5)),
            Shortcut("Small Increase Pressure", "8","8", lambda: self.machine.set_relative_pressure(0.1)),
            Shortcut("Small Decrease Pressure", "7","7", lambda: self.machine.set_relative_pressure(-0.1)),
            Shortcut("Large Decrease Pressure", "6","6", lambda: self.machine.set_relative_pressure(-0.5)),
            Shortcut("Regulate Pressure", QtCore.Qt.Key_Plus,"+", lambda: self.machine.regulate_pressure),
            Shortcut("Deregulate Pressure", QtCore.Qt.Key_Minus,"-", lambda: self.machine.deregulate_pressure),
            Shortcut("Add Reagent", "A","A", lambda: self.add_reagent()),
            Shortcut("Test Popup", "T","T", lambda: self.test_popup()),
            Shortcut("Pick Up Reagent", "O","O", lambda: self.machine.pick_up_reagent()),
            Shortcut("Open Gripper", "G","G", lambda: self.manual_open_gripper()),
            Shortcut("Close Gripper", "g","g", lambda: self.manual_close_gripper()),
            Shortcut("Move to location", "L","L", lambda: self.machine.move_to_location(location=False)),
            Shortcut("Print array", "P","P", lambda: self.print_array()),
            Shortcut("Pause", QtCore.Qt.Key_Escape,"Esc", lambda: self.pause_execution()),
            Shortcut("Inc Step", ";",";", lambda: self.inc_step()),
            Shortcut("Dec Step", ".",".", lambda: self.dec_step()),
            Shortcut("Print 5", "c","c", lambda: self.print_droplets(5)),
            Shortcut("Print 20", "v","v", lambda: self.print_droplets(20)),
            Shortcut("Print 100", "b","b", lambda: self.print_droplets(100)),
        ]
        self.read_settings_file()
        self.select_mode(mode_name=self.settings['DEFAULT_DISPENSER'])
        self.read_colors_file()
        self.read_reagents_file()

        self.machine = Machine(self)
        self.gripper_reagent = Reagent("Empty", self.colors, "dark_gray")
        self.experiment_name = 'Untitled Experiment'

        self.all_reactions = pd.DataFrame()
        self.reaction_metadata = pd.DataFrame()
        self.wells_df = pd.DataFrame()
        self.full_array = pd.DataFrame()
        self.actual_array = pd.DataFrame()

        self.communication_timer = QTimer()
        self.communication_timer.timeout.connect(self.machine.get_state_from_board)
        self.communication_timer.start(101)  # Update every 100 ms
        
        self.execution_timer = QTimer()
        self.execution_timer.timeout.connect(self.machine.execute_command_from_queue)
        self.execution_timer.start(90)  # Update every 100 ms
        
        self.slots = [Slot(i, Reagent('Empty',self.colors,'red')) for i in range(self.rack_slots)]
        
        self.setWindowTitle("My App")
        transparent_icon = self.make_transparent_icon()
        self.setWindowIcon(transparent_icon)
        # Create the menu bar
        menu_bar = self.menuBar()

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
        self.connection_box = ConnectionBox("CONNECTION",self)
        self.connection_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.connection_box.machine_connected.connect(self.set_machine_connected_status)
        self.connection_box.balance_connected.connect(self.set_balance_connected_status)
        left_layout.addWidget(self.connection_box)

        self.step_num = 4
        self.possible_steps = [2,10,50,250,500,1000,2000]
        self.step_size = self.possible_steps[self.step_num]
        
        self.coordinates_box = CoordinateBox("COORDINATES",self)
        self.coordinates_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.coordinates_box.motors_activated.connect(self.set_motors_active)
        self.coordinates_box.home_motors.connect(self.home_motors)
        left_layout.addWidget(self.coordinates_box)

        self.pressure_box = PressurePlotBox("PRESSURE", self)
        self.pressure_box.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.pressure_box.regulating_pressure.connect(self.toggle_regulation)

        left_layout.addWidget(self.pressure_box)
        layout.addWidget(left_panel)

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_coordinates)
        self.update_timer.timeout.connect(self.update_pressure)

        self.update_timer.start(100)  # Update every 100 ms
        
        mid_panel = QtWidgets.QWidget()
        mid_panel.setStyleSheet(f"background-color: {self.colors['darker_gray']};")
        mid_layout = QtWidgets.QVBoxLayout(mid_panel)

        tab_widget = QtWidgets.QTabWidget()

        tab_widget.setFocusPolicy(QtCore.Qt.NoFocus)

        self.current_plate = Plate('5x10',rows=16,columns=24)
        self.plate_box = PlateBox(self,'PLATE')
        self.plate_box.setStyleSheet(f"background-color: {self.colors['darker_gray']};")
        
        tab_widget.addTab(self.plate_box, "Plate")
        # Create another widget and add it to the second tab
        self.movement_box = MovementBox("MOVEMENT",self)
        tab_widget.addTab(self.movement_box, "MOVEMENT")
        
        mid_layout.addWidget(tab_widget)

        self.array_widget = ArrayWidget(self)
        mid_layout.addWidget(self.array_widget)

        self.rack_box = RackBox(self,self.slots,self.reagents)
        self.rack_box.setFixedHeight(200)
        self.rack_box.setStyleSheet(f"background-color: {self.colors['dark_gray']};")
        self.rack_box.reagent_confirmed.connect(self.confirm_reagent)
        self.rack_box.reagent_loaded.connect(self.transfer_reagent)
        mid_layout.addWidget(self.rack_box)

        layout.addWidget(mid_panel)

        right_panel = QtWidgets.QWidget()
        right_panel.setFixedWidth(300)
        right_panel.setStyleSheet(f"background-color: {self.colors['dark_gray']};")
        right_layout = QtWidgets.QVBoxLayout(right_panel)  # Use a vertical box layout

        self.command_box = CommandTable(self,self.machine.get_command_log(),"COMMANDS")
        self.command_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        right_layout.addWidget(self.command_box)
        self.machine.command_added.connect(self.add_command)
        self.machine.command_sent.connect(self.sent_command)
        self.machine.command_executed.connect(self.execute_command)
        self.machine.command_completed.connect(self.completed_command)

        self.shortcut_box = ShortcutTable(self.shortcuts,"SHORTCUTS")
        self.shortcut_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        right_layout.addWidget(self.shortcut_box)

        layout.addWidget(right_panel)

        # Window dimensions
        geometry = self.screen().availableGeometry()
        self.setFixedSize(geometry.width() * 0.95, geometry.height() * 0.9)
    
    def closeEvent(self, event):
        response = self.popup_yes_no('Exit','Are you sure you want to exit?')
        if response == '&Yes':
            # self.machine.pause_commands()
            self.machine.clear_command_queue()
            time.sleep(1)
            self.machine.disconnect_machine()
            event.accept()
        else:
            event.ignore()

    def print_droplets(self,num_droplets):
        self.machine.print_droplets(num_droplets)
    
    def inc_step(self):
        if self.step_num < len(self.possible_steps)-1:
            self.step_num += 1
            self.step_size = self.possible_steps[self.step_num]
            self.coordinates_box.update_step_size(self.step_size)
    
    def dec_step(self):
        if self.step_num > 0:
            self.step_num -= 1
            self.step_size = self.possible_steps[self.step_num]
            self.coordinates_box.update_step_size(self.step_size)
    
    def update_plate_box(self):
        self.plate_box.update_plate_box()
    
    def print_status(self, status):
        self.statusBar().showMessage(status)

    def popup_message(self,title, message):
        msg = QtWidgets.QMessageBox()
        msg.setWindowTitle(title)
        msg.setText(message)
        transparent_icon = self.make_transparent_icon()
        msg.setWindowIcon(transparent_icon)
        msg.exec()

    def test_popup(self):
        response = self.popup_options('Test','This is a test message',['Option 1','Option 2'])
        print(response)

    def popup_options(self,title, message, options):
        msg = QtWidgets.QMessageBox()
        msg.setWindowTitle(title)
        msg.setText(message)
        for option in options:
            msg.addButton(option, QtWidgets.QMessageBox.AcceptRole)
        transparent_icon = self.make_transparent_icon()
        msg.setWindowIcon(transparent_icon)
        msg.exec()
        return msg.clickedButton().text()
    
    def popup_yes_no(self,title, message):
        msg = QtWidgets.QMessageBox()
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        transparent_icon = self.make_transparent_icon()
        msg.setWindowIcon(transparent_icon)
        msg.exec()
        return msg.clickedButton().text()
    
    def read_settings_file(self):
        with open('./Pyside6_interface/Presets/Settings.json', 'r') as f:
            settings = json.load(f)
        self.settings = settings
        self.base = settings['BASE_PATH']
        self.possible_dispensers = list(self.settings['DISPENSER_TYPES'].keys())
        self.rack_slots = settings['RACK_SLOTS']
        self.mode = None
        return
    
    def select_mode(self,mode_name=False):
        if not mode_name:
            mode_name = self.popup_options('Select Mode','Select the mode you want to use',self.possible_dispensers)
        elif self.mode == mode_name:
            return
        if mode_name not in self.possible_dispensers:
            self.popup_message('Error','Invalid mode selected')
            return
        self.load_dispenser_settings(mode_name)
    
    def load_dispenser_settings(self,mode_name):
        self.safe_height = self.settings['DISPENSER_TYPES'][mode_name]['height']
        self.safe_y = self.settings['DISPENSER_TYPES'][mode_name]['safe_y']
        self.pulse_width = self.settings['DISPENSER_TYPES'][mode_name]['pulse_width']
        self.default_pressure = self.settings['DISPENSER_TYPES'][mode_name]['print_pressure']
        self.target_volume = self.settings['DISPENSER_TYPES'][mode_name]['target_disp_volume']
        self.frequency = self.settings['DISPENSER_TYPES'][mode_name]['frequency']
        self.max_volume = self.settings['DISPENSER_TYPES'][mode_name]['max_volume']
        self.min_volume = self.settings['DISPENSER_TYPES'][mode_name]['min_volume']
        self.rack_offset = self.settings['DISPENSER_TYPES'][mode_name]['rack_offset']
        self.calibrated = False
        self.mode = mode_name
        return
    
    def read_reagents_file(self):
        with open('./Pyside6_interface/Presets/Reagents.json', 'r') as f:
            reagents = json.load(f)
        self.reagents = [Reagent(reagent['name'],self.colors,reagent['color_name']) for reagent in reagents]
    
    def write_reagents_file(self):
        reagents = [reagent.to_dict() for reagent in self.reagents]
        with open('./Pyside6_interface/Presets/Reagents.json', 'w') as f:
            json.dump(reagents, f)

    def select_experiment_directory(self):
        current_directory = os.getcwd()  # Get the current working directory
        dialog = QtWidgets.QFileDialog(self)
        dialog.setFileMode(QtWidgets.QFileDialog.Directory)
        current_directory += '.\Pyside6_interface\Experiments'
        dialog.setDirectory(current_directory)
        if dialog.exec():
            selected_directory = dialog.selectedFiles()[0]
            return selected_directory
        else:
            return None
        
    def load_experiment(self):
        selected_directory = self.select_experiment_directory()
        if selected_directory:
            self.experiment_name = selected_directory.split('/')[-1]
            self.all_reactions = pd.read_csv(f"{selected_directory}/{self.experiment_name}_reactions.csv")
            self.reaction_metadata = pd.read_csv(f"{selected_directory}/{self.experiment_name}_metadata.csv")
            self.update_plate_box()
            self.set_cartridges()
        else:
            self.popup_message('Error','No experiment selected')
    
    def get_printing_reagents(self):
        return self.full_array['reagent'].unique().tolist()
    
    def set_cartridges(self):
        reagents_to_print = self.get_printing_reagents()
        for i,reagent in enumerate(reagents_to_print):
            reagent_obj = next((r for r in self.reagents if r.name == reagent), None)
            self.rack_box.change_reagent(i,reagent_obj)
        self.rack_box.reset_confirmation()
    
    def read_colors_file(self):
        with open('./Pyside6_interface/Presets/Colors.json', 'r') as f:
            self.colors = json.load(f)

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

    def pause_execution(self):
        self.machine.pause_commands()
        response = self.popup_yes_no('Pause','Execution paused. Do you want to resume?')
        if response == '&Yes':
            print('Resuming execution')
            self.machine.resume_commands()
            return
        else:
            print('Clearing Queue')
            self.machine.clear_command_queue()
        
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
        target_psi = self.machine.get_target_psi()
        self.pressure_box.update_pressure(pressure_log,target_psi)
    
    def update_slot_reagents(self):
        self.rack_box.update_reagents_dropdown()

    def deactivate_loading_and_editing(self):
        self.array_widget.deactivate_array_buttons()

    def activate_loading_and_editing(self):
        self.array_widget.activate_array_buttons()

    def manual_open_gripper(self):
        self.machine.open_gripper()
        self.rack_box.open_gripper(True)
    
    def manual_close_gripper(self):
        self.machine.close_gripper()
        self.rack_box.close_gripper(False)
    
    def open_gripper(self):
        self.rack_box.open_gripper()
    
    def close_gripper(self):
        self.rack_box.close_gripper()

    def print_array(self):
        self.machine.print_array(self.full_array)

    def mark_reagent_as_added(self,well_number,reagent_name):
        self.plate_box.mark_reagent_as_added(well_number,reagent_name)
        print(self.full_array['Added'].value_counts())
        self.plate_box.preview_array()

    def update_movement_plot(self):
        self.movement_box.plot_movements()
    
    def update_machine_position(self):
        self.movement_box.update_machine_position()

    def remove_commands(self,removed_commands):
        for command in removed_commands:
            self.command_box.remove_command(command.get_number())

    def change_connection_button(self):
        if self.machine.machine_connected:
            self.connection_box.machine_connect_button.setStyleSheet("background-color: #a92222")
            self.connection_box.machine_connect_button.setText("Disconnect")
        else:
            self.connection_box.machine_connect_button.setStyleSheet("background-color: #1e64b4")
            self.connection_box.machine_connect_button.setText("Connect")
    
    @QtCore.Slot(str)
    def set_machine_connected_status(self, port):
        if self.connection_box.machine_connect_button.text() == "Disconnect":
            self.machine.disconnect_machine()
        else:
            self.machine.connect_machine(port)
        self.change_connection_button()

    def change_balance_connection_button(self):
        if self.machine.balance_connected:
            self.connection_box.balance_connect_button.setStyleSheet("background-color: #a92222")
            self.connection_box.balance_connect_button.setText("Disconnect")
        else:
            self.connection_box.balance_connect_button.setStyleSheet("background-color: #1e64b4")
            self.connection_box.balance_connect_button.setText("Connect")
    
    
    @QtCore.Slot(str)
    def set_balance_connected_status(self, port):
        if self.connection_box.balance_connect_button.text() == "Disconnect":
            self.machine.disconnect_balance()
        else:
            self.machine.connect_balance(port)
        self.change_balance_connection_button()
        
    def change_motor_activation(self,activated=False):
        if activated:
            self.coordinates_box.activate_motors_button.setStyleSheet("background-color: #a92222")
            self.coordinates_box.activate_motors_button.setText("Deactivate")
            self.coordinates_box.set_text_bg_color(self.colors['white'],self.colors['darker_gray'])
        else:
            self.coordinates_box.activate_motors_button.setStyleSheet("background-color: #1e64b4")
            self.coordinates_box.activate_motors_button.setText("Activate")
            self.coordinates_box.set_text_bg_color(self.colors['white'],self.colors['dark_gray'])
    
    @QtCore.Slot(bool)
    def set_motors_active(self):
        if self.coordinates_box.activate_motors_button.text() == "Activate":
            self.machine.enable_motors()
        else:
            self.machine.disable_motors()

    @QtCore.Slot(bool)
    def home_motors(self):
        self.machine.home_motors()

    def change_regulation_button(self):
        if not self.machine.get_regulation_state():
            self.pressure_box.pressure_regulation_button.setStyleSheet(f"background-color: {self.colors['blue']}")
            self.pressure_box.pressure_regulation_button.setText("Regulate Pressure")
            self.pressure_box.set_text_bg_color(self.colors['white'],self.colors['dark_gray'])
        else:
            self.pressure_box.pressure_regulation_button.setStyleSheet(f"background-color: {self.colors['red']}")
            self.pressure_box.pressure_regulation_button.setText("Deregulate Pressure")
            self.pressure_box.set_text_bg_color(self.colors['white'],self.colors['darker_gray'])
    
    @QtCore.Slot(str)
    def toggle_regulation(self):
        if self.machine.get_regulation_state():
            self.machine.deregulate_pressure()
        else:
            self.machine.regulate_pressure()

    @QtCore.Slot(Command)
    def add_command(self, command):
        self.command_box.add_command(command)

    @QtCore.Slot(Command)
    def sent_command(self, command):
        self.command_box.sent_command(command.get_number())

    @QtCore.Slot(Command)
    def execute_command(self, command):
        self.command_box.execute_command(command.get_number())
    
    @QtCore.Slot(Command)
    def completed_command(self, command):
        self.command_box.completed_command(command.get_number())
        print(f"Command {command.get_number()} completed")

    @QtCore.Slot(Slot)
    def confirm_reagent(self,slot_obj):
        self.statusBar().showMessage(f"Slot-{slot_obj.number} loaded with {slot_obj.reagent.name} confirmed")
        self.rack_box.confirm_reagent(slot_obj.number, slot_obj.reagent)

    def change_reagent_pickup(self,slot):
        self.rack_box.change_reagent(slot.number,Reagent("Empty", self.colors, "dark_gray"))
        self.rack_box.change_gripper_reagent(slot.reagent)
        self.rack_box.update_load_buttons()
    
    def change_reagent_drop(self,slot):
        self.rack_box.change_reagent(slot.number,self.gripper_reagent)
        self.rack_box.change_gripper_reagent(Reagent("Empty", self.colors, "dark_gray"))
        self.rack_box.update_load_buttons()

    @QtCore.Slot(Slot)
    def transfer_reagent(self,slot):
        if self.machine.motors_active:
            reagent = slot.reagent
            if reagent.name != "Empty" and self.gripper_reagent.name == "Empty":
                self.machine.pick_up_reagent(slot)
                self.deactivate_loading_and_editing()
            elif reagent.name == "Empty" and self.gripper_reagent.name != "Empty":
                self.machine.drop_reagent(slot)
                self.activate_loading_and_editing()
            else:
                print(f"Invalid transfer-{reagent.name}-{self.gripper_reagent.name}")

            self.rack_box.update_load_buttons()
        else:
            self.popup_message('Error','Machine not connected')

if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    
    with open("./Pyside6_interface/stylesheet.qss", "r") as f:
        app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()
    app.exec()