from PySide6 import QtCore, QtWidgets, QtGui

from PySide6 import QtCharts
from PySide6.QtCore import QTimer, QPointF
import numpy as np
import pandas as pd
import itertools
import json
import os
from serial.tools.list_ports import comports

class Plate():
    """
    Represents a plate with a specified name, number of rows, number of columns, spacing, and default value.

    Attributes:
        name (str): The name of the plate.
        rows (int): The number of rows in the plate.
        columns (int): The number of columns in the plate.
        spacing (int): The spacing between elements in the plate.
        default (bool): The default value of the plate.
    """

    def __init__(self, name, rows=16, columns=24, spacing=10, default=False, calibrations={}):
        self.name = name
        self.rows = rows
        self.columns = columns
        self.spacing = spacing
        self.default = default
        self.calibrations = calibrations
    
    def to_dict(self):
        return self.__dict__

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

class PlateCalibrationDialog(QtWidgets.QDialog):
    plate_calibration_complete = QtCore.Signal(Plate)
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.machine = main_window.machine
        self.all_calibrations = ["top_left","top_right","bottom_right","bottom_left"]
        self.calibration_number = 0
        self.current_calibration = self.all_calibrations[self.calibration_number]

        self.current_plate = self.main_window.current_plate
        print('Currnet plate:',self.current_plate.name)
        self.updated_plate = self.current_plate

        self.setWindowTitle("Plate Calibration")
        self.resize(800, 400)

        # Create a QVBoxLayout for the main layout
        self.layout = QtWidgets.QVBoxLayout(self)

        self.instructions_label = QtWidgets.QLabel()
        self.instructions_label.setFont(QtGui.QFont("Arial", 20))  # Set the font size to 20
        # self.instructions_label.setFixedWidth(500)
        self.instructions_label.setWordWrap(True)
        self.instructions_label.setAlignment(QtCore.Qt.AlignCenter)
        self.layout.addWidget(self.instructions_label)

        # Create a QHBoxLayout for the simple_coord_box and movement_shortcuts_box
        self.box_layout = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.box_layout)

        self.simple_coord_box = SimpleCoordinateBox("Coordinates",self.main_window)
        self.simple_coord_box.setFixedWidth(400)
        self.box_layout.addWidget(self.simple_coord_box)

        self.movement_shortcuts = [
            Shortcut("Save Position", "s", "s", lambda: self.save_plate_position()),
            Shortcut("Move Forward",QtCore.Qt.Key_Up, "Up", lambda: self.machine.set_relative_coordinates(self.main_window.step_size,0,0)),
            Shortcut("Move Back",QtCore.Qt.Key_Down,"Down", lambda: self.machine.set_relative_coordinates(-self.main_window.step_size,0,0)),
            Shortcut("Move Left", QtCore.Qt.Key_Left,"Left", lambda: self.machine.set_relative_coordinates(0,-self.main_window.step_size,0)),
            Shortcut("Move Right",QtCore.Qt.Key_Right, "Right", lambda: self.machine.set_relative_coordinates(0,self.main_window.step_size,0)),
            Shortcut("Move Up", "k", "k", lambda: self.machine.set_relative_coordinates(0,0,self.main_window.step_size)),
            Shortcut("Move Down", "m","m", lambda: self.machine.set_relative_coordinates(0,0,-self.main_window.step_size)),
            Shortcut("Inc Step", ";",";", lambda: self.inc_step()),
            Shortcut("Dec Step", ".",".", lambda: self.dec_step()),
        ]

        self.movement_shortcuts_box = ShortcutTable(self.movement_shortcuts,"Movement Shortcuts")
        self.box_layout.addWidget(self.movement_shortcuts_box)

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_coordinates)
        self.update_timer.start(100)

        self.update_instructions()
        self.check_before_move()

    def keyPressEvent(self, event):
        for shortcut in self.movement_shortcuts:
            if isinstance(shortcut.key, str):  # If the shortcut key is a string
                if event.text() == shortcut.key:  # Convert the string to a key code
                    shortcut.function()
                    break
            elif event.key() == shortcut.key:  # If the shortcut key is a key code
                shortcut.function()
                break
        self.update_coordinates()

    def update_coordinates(self):
        current_coords = self.machine.get_coordinates()
        target_coords = self.machine.get_target_coordinates()
        self.simple_coord_box.update_coordinates(current_coords,target_coords)
    
    def inc_step(self):
        if self.main_window.step_num < len(self.main_window.possible_steps)-1:
            self.main_window.step_num += 1
            self.main_window.step_size = self.main_window.possible_steps[self.main_window.step_num]
            self.simple_coord_box.update_step_size(self.main_window.step_size)
    
    def dec_step(self):
        if self.main_window.step_num > 0:
            self.main_window.step_num -= 1
            self.main_window.step_size = self.main_window.possible_steps[self.main_window.step_num]
            self.simple_coord_box.update_step_size(self.main_window.step_size)
    
    def update_instructions(self):
        self.instructions_label.setText(f"Calibrate the {self.current_calibration} corner of the plate")
    
    def save_plate_position(self):
        response = self.main_window.popup_yes_no("Save Position",f"Are you sure you want to save the current position as the {self.current_calibration} corner of the plate?")
        if response == '&No':
            return
        if self.current_calibration not in self.updated_plate.calibrations.keys():
            self.updated_plate.calibrations.update({self.current_calibration: self.machine.get_XYZ_coordinates()})
        else:
            self.updated_plate.calibrations[self.current_calibration] = self.machine.get_XYZ_coordinates()
        self.calibration_number += 1
        if self.calibration_number < len(self.all_calibrations):
            print('Applying offset')
            self.machine.set_relative_coordinates(0,0,1000)
            self.current_calibration = self.all_calibrations[self.calibration_number]
            self.update_instructions()
            self.check_before_move()
        else:
            self.plate_calibration_complete.emit(self.updated_plate)
            self.main_window.popup_message("Calibration Complete","Plate calibration complete")
            self.close()

    def check_before_move(self):
        if self.current_calibration in self.updated_plate.calibrations.keys():
            response = self.main_window.popup_yes_no("Move to saved position",f"Would you like to move to the saved position for the {self.current_calibration} corner of the plate?")
            if response == '&Yes':
                new_coordinates = self.updated_plate.calibrations[self.current_calibration]
                x = new_coordinates['X']
                y = new_coordinates['Y']
                z = new_coordinates['Z']
                self.machine.set_absolute_coordinates(x,y,z)
    
class RackCalibrationDialog(QtWidgets.QDialog):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.machine = main_window.machine
        self.all_calibrations = ["Left","Right"]
        self.calibration_number = 0
        self.current_calibration = self.all_calibrations[self.calibration_number]

        self.setWindowTitle("Rack Calibration")
        self.resize(800, 400)

        # Create a QVBoxLayout for the main layout
        self.layout = QtWidgets.QVBoxLayout(self)

        self.instructions_label = QtWidgets.QLabel()
        self.instructions_label.setFont(QtGui.QFont("Arial", 20))  # Set the font size to 20
        # self.instructions_label.setFixedWidth(500)
        self.instructions_label.setWordWrap(True)
        self.instructions_label.setAlignment(QtCore.Qt.AlignCenter)
        self.layout.addWidget(self.instructions_label)

        # Create a QHBoxLayout for the simple_coord_box and movement_shortcuts_box
        self.box_layout = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.box_layout)

        self.simple_coord_box = SimpleCoordinateBox("Coordinates",self.main_window)
        self.simple_coord_box.setFixedWidth(400)
        self.box_layout.addWidget(self.simple_coord_box)

        self.movement_shortcuts = [
            Shortcut("Save Position", "s", "s", lambda: self.save_position()),
            Shortcut("Move Forward",QtCore.Qt.Key_Up, "Up", lambda: self.machine.set_relative_coordinates(self.main_window.step_size,0,0)),
            Shortcut("Move Back",QtCore.Qt.Key_Down,"Down", lambda: self.machine.set_relative_coordinates(-self.main_window.step_size,0,0)),
            Shortcut("Move Left", QtCore.Qt.Key_Left,"Left", lambda: self.machine.set_relative_coordinates(0,-self.main_window.step_size,0)),
            Shortcut("Move Right",QtCore.Qt.Key_Right, "Right", lambda: self.machine.set_relative_coordinates(0,self.main_window.step_size,0)),
            Shortcut("Move Up", "k", "k", lambda: self.machine.set_relative_coordinates(0,0,self.main_window.step_size)),
            Shortcut("Move Down", "m","m", lambda: self.machine.set_relative_coordinates(0,0,-self.main_window.step_size)),
            Shortcut("Inc Step", ";",";", lambda: self.inc_step()),
            Shortcut("Dec Step", ".",".", lambda: self.dec_step()),
        ]

        self.movement_shortcuts_box = ShortcutTable(self.movement_shortcuts,"Movement Shortcuts")
        self.box_layout.addWidget(self.movement_shortcuts_box)
        
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_coordinates)
        self.update_timer.start(100)

        self.update_instructions()
        self.check_before_move()
    
    def keyPressEvent(self, event):
        for shortcut in self.movement_shortcuts:
            if isinstance(shortcut.key, str):  # If the shortcut key is a string
                if event.text() == shortcut.key:  # Convert the string to a key code
                    shortcut.function()
                    break
            elif event.key() == shortcut.key:  # If the shortcut key is a key code
                shortcut.function()
                break
        self.update_coordinates()

    def update_coordinates(self):
        current_coords = self.machine.get_coordinates()
        target_coords = self.machine.get_target_coordinates()
        self.simple_coord_box.update_coordinates(current_coords,target_coords)
    
    def inc_step(self):
        if self.main_window.step_num < len(self.main_window.possible_steps)-1:
            self.main_window.step_num += 1
            self.main_window.step_size = self.main_window.possible_steps[self.main_window.step_num]
            self.simple_coord_box.update_step_size(self.main_window.step_size)
    
    def dec_step(self):
        if self.main_window.step_num > 0:
            self.main_window.step_num -= 1
            self.main_window.step_size = self.main_window.possible_steps[self.main_window.step_num]
            self.simple_coord_box.update_step_size(self.main_window.step_size)

    def check_before_move(self):
        if f'rack_position_{self.current_calibration}' in self.machine.calibration_data.keys():
            response = self.main_window.popup_yes_no("Move to saved position",f"Would you like to move to the saved position for the {self.current_calibration} side of the rack? It will apply an X-offset of {self.machine.rack_offset}")
            if response == '&Yes':
                self.machine.move_to_location(location=f'rack_position_{self.current_calibration}')


    def update_instructions(self):
        self.instructions_label.setText(f"Calibrate the {self.current_calibration} side of the rack")
    
    def save_position(self):
        response = self.main_window.popup_yes_no("Save Position",f"Are you sure you want to save the current position as the {self.current_calibration} side of the rack?")
        if response == '&No':
            return
        self.machine.save_location(location=f'rack_position_{self.current_calibration}',ask=False)
        self.calibration_number += 1
        if self.calibration_number < len(self.all_calibrations):
            print('Applying offset')
            self.machine.set_relative_coordinates(self.machine.rack_offset,0,0)
            self.current_calibration = self.all_calibrations[self.calibration_number]
            self.update_instructions()
            self.check_before_move()
        else:
            self.calculate_rack_positions()
            self.main_window.popup_message("Calibration Complete","Rack calibration complete")
            self.close()

    def calculate_rack_positions(self):
        left_coords = self.machine.calibration_data['rack_position_Left']
        right_coords = self.machine.calibration_data['rack_position_Right']
        x_diff = right_coords['x'] - left_coords['x']
        y_diff = right_coords['y'] - left_coords['y']
        z_diff = right_coords['z'] - left_coords['z']
        num_slots = self.main_window.rack_slots
        slot_width = x_diff / (num_slots + 1)
        slot_height = y_diff / (num_slots + 1)
        slot_depth = z_diff / (num_slots + 1)
        for i in range(1,num_slots+1):
            x = int(left_coords['x'] + i*slot_width)
            y = int(left_coords['y'] + i*slot_height)
            z = int(left_coords['z'] + i*slot_depth)
            self.machine.calibration_data[f"rack_position_{i}_{num_slots}"] = {'x':x,'y':y,'z':z}
        with open(self.machine.calibration_file_path, 'w') as outfile:
            json.dump(self.machine.calibration_data, outfile)
        self.machine.load_positions_from_file()
            

class MovementBox(QtWidgets.QGroupBox):
    """
    A custom widget for displaying past and future movements.
    """

    def __init__(self, title, main_window):
        super().__init__(title)
        self.main_window = main_window
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
        self.xy_chart.setBackgroundBrush(QtGui.QBrush(self.main_window.colors['dark_gray']))  # Set the background color to grey
        self.xy_chart_view = QtCharts.QChartView(self.xy_chart)
        self.xy_series = QtCharts.QLineSeries()
        self.xy_position_series = QtCharts.QScatterSeries()

        # Add the series to the XY chart
        self.xy_chart.addSeries(self.xy_series)
        self.xy_chart.addSeries(self.xy_position_series)

        # Create a chart, a chart view and a line series for Z coordinate
        self.z_chart = QtCharts.QChart()
        self.z_chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.z_chart.setBackgroundBrush(QtGui.QBrush(self.main_window.colors['dark_gray']))  # Set the background color to grey
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
        self.xy_chart.axisX().setRange(self.y_min, self.y_max)

        self.z_chart.createDefaultAxes()
        self.z_chart.axisX().setRange(-1, 1)
        self.z_chart.axisX().setLabelsVisible(False)
        self.z_chart.axisY().setRange(self.z_min, self.z_max)
        

    def plot_movements(self):
        # Clear the series
        self.xy_series.clear()
        self.z_series.clear()

        # Get the target coordinates from the machine
        target_coordinates = self.main_window.machine.target_coordinates

        # Add the coordinates to the series
        for coord in target_coordinates:
            self.xy_series.append(coord[0], coord[1])
            self.z_series.append(coord[2], 0)

    def update_machine_position(self):
        # Clear the position series
        self.xy_position_series.clear()
        self.z_position_series.clear()

        # Get the current position from the machine
        x_pos = self.main_window.machine.x_pos
        y_pos = self.main_window.machine.y_pos
        z_pos = self.main_window.machine.z_pos

        # Add the current position to the position series
        self.xy_position_series.append(y_pos, x_pos)
        self.z_position_series.append(0,z_pos)

class PlateBox(QtWidgets.QGroupBox):
    """
    A custom widget representing a plate box.

    Args:
        main_window (QtWidgets.QMainWindow): The main window object.
        title (str): The title of the plate box.

    Attributes:
        main_window (QtWidgets.QMainWindow): The main window object.
        layout (QtWidgets.QVBoxLayout): The layout of the plate box.
        top_layout (QtWidgets.QHBoxLayout): The top layout of the plate box.
        experiment_label (QtWidgets.QLabel): The label for the experiment.
        experiment_name (QtWidgets.QLabel): The label for the experiment name.
        plate_label (QtWidgets.QLabel): The label for the plate.
        plate_combo (QtWidgets.QComboBox): The combo box for selecting the plate.
        plate_activate_button (QtWidgets.QPushButton): The button for activating the plate.
        grid (QtWidgets.QGridLayout): The grid layout for the plate cells.
        bottom_layout (QtWidgets.QHBoxLayout): The bottom layout of the plate box.
        reagent_combo_label (QtWidgets.QLabel): The label for the active reagent combo box.
        reagent_combo (QtWidgets.QComboBox): The combo box for selecting the active reagent.
        cells (dict): A dictionary mapping well numbers to cell buttons.
        current_plate (Plate): The currently selected plate.
        rows (int): The number of rows in the plate.
        columns (int): The number of columns in the plate.
        wells_df (pd.DataFrame): The DataFrame representing the wells in the plate.
        full_array (pd.DataFrame): The DataFrame representing the full plate array.

    Methods:
        update_plate_box(): Updates the plate box.
        update_plate_reagents(): Updates the available reagents in the reagent combo box.
        update_experiment_name(): Updates the experiment name label.
        read_plate_file(): Reads the plate options from a JSON file.
        create_plate(plate): Creates the plate cells based on the selected plate.
        activate_plate(): Activates the selected plate.
        snake_df(df): Sorts the DataFrame in a snake-like pattern.
        assign_wells(): Assigns reactions to wells in the plate.
        preview_array(): Previews the plate array for the selected reagent.
        update_plate_single(current_array, reagent): Updates the plate cells for a single reagent.
        set_cell_color(well_number, reagent, target_amount, max_amount): Sets the color of a cell based on the reagent and amount.

    """
    plate_changed = QtCore.Signal(Plate)
    calibrate_plate_signal = QtCore.Signal()
    def __init__(self,main_window, title):
        super().__init__(title)
        self.main_window = main_window
        self.plate_options = self.main_window.plate_options
        self.current_plate = self.main_window.current_plate

        self.layout = QtWidgets.QVBoxLayout(self)
        self.top_layout = QtWidgets.QHBoxLayout()

        self.experiment_label = QtWidgets.QLabel("Experiment:")
        self.experiment_label.setFixedWidth(70)
        self.top_layout.addWidget(self.experiment_label)

        self.experiment_name = QtWidgets.QLabel(self.main_window.experiment_name)
        self.experiment_name.setStyleSheet(f"font-weight: bold; background-color: {self.main_window.colors['mid_gray']}")
        self.experiment_name.setAlignment(QtCore.Qt.AlignCenter)
        self.experiment_name.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.top_layout.addWidget(self.experiment_name)

        self.plate_label = QtWidgets.QLabel("Plate:")
        self.plate_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.plate_label.setFixedWidth(50)
        self.top_layout.addWidget(self.plate_label)

        self.plate_combo = QtWidgets.QComboBox()
        self.plate_combo.setFocusPolicy(QtCore.Qt.NoFocus)
        self.plate_combo.addItems([plate.name for plate in self.plate_options])
        self.top_layout.addWidget(self.plate_combo)

        self.plate_activate_button = QtWidgets.QPushButton("Activate")
        self.plate_activate_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.plate_activate_button.setStyleSheet(f"background-color: {self.main_window.colors['blue']}")
        self.plate_activate_button.clicked.connect(self.activate_plate)
        self.top_layout.addWidget(self.plate_activate_button)

        self.plate_calibrate_button = QtWidgets.QPushButton("Calibrate")
        self.plate_calibrate_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.plate_calibrate_button.setStyleSheet(f"background-color: {self.main_window.colors['blue']}")
        self.plate_calibrate_button.clicked.connect(self.calibrate_plate)
        self.top_layout.addWidget(self.plate_calibrate_button)

        self.layout.addLayout(self.top_layout)

        self.grid = QtWidgets.QGridLayout()
        self.plate_combo.setCurrentText(self.current_plate.name)
        self.create_plate(self.current_plate)
        self.layout.addLayout(self.grid)

        self.bottom_layout = QtWidgets.QHBoxLayout()
        self.reagent_combo_label = QtWidgets.QLabel("Active reagent:")
        self.bottom_layout.addWidget(self.reagent_combo_label)

        self.reagent_combo = QtWidgets.QComboBox()
        self.reagent_combo.setFocusPolicy(QtCore.Qt.NoFocus)
        if not self.main_window.all_reactions.empty:
            for reagent in self.main_window.reagents:
                self.reagent_combo.addItem(reagent.name)
        self.reagent_combo.currentIndexChanged.connect(self.activate_plate)
        self.bottom_layout.addWidget(self.reagent_combo)
        self.layout.addLayout(self.bottom_layout)

    def get_current_plate(self):
        return self.current_plate
    
    def get_plate_options(self):
        return self.plate_options

    def update_plate_box(self):
        self.update_experiment_name()
        self.update_plate_reagents()
    
    def update_plate_reagents(self):
        self.reagent_combo.clear()
        for reagent in self.main_window.all_reactions.columns:
            if reagent != 'replicate_id' and reagent != 'unique_id':
                self.reagent_combo.addItem(reagent)
    
    def update_experiment_name(self):
        self.experiment_name.setText(self.main_window.experiment_name)
    
    def read_plate_file(self):
        with open('./Pyside6_interface/Presets/Plates.json', 'r') as f:
            plates = json.load(f)
        self.plate_options = [Plate(plate['name'],rows=plate['rows'],columns=plate['columns'],spacing=plate['spacing'],default=plate['default'],calibrations=plate['calibrations']) for plate in plates]
    
    def write_plate_file(self):
        with open('./Pyside6_interface/Presets/Plates.json', 'w') as f:
            json.dump([plate.__dict__ for plate in self.plate_options], f, indent=4)

    def create_plate(self,plate):
        self.cells = {}
        self.current_plate = plate
        self.rows = plate.rows
        self.columns = plate.columns
        available_rows = range(self.rows)
        available_cols = range(self.columns)

        wells = list(itertools.product(*[available_cols,available_rows]))
        self.wells_df = pd.DataFrame(wells,columns=['column','row'])
        self.wells_df['well_number'] = [i for i in range(len(self.wells_df))]
        self.main_window.wells_df = self.wells_df

        for i,well in self.wells_df.iterrows():
            cell = QtWidgets.QPushButton(f"")
            cell.setFocusPolicy(QtCore.Qt.NoFocus)
            cell.setStyleSheet("border: 0.5px solid black; border-radius: 4px;")
            self.grid.addWidget(cell, well['row'], well['column'])
            self.cells.update({well['well_number']:cell})

    def activate_plate(self):
        # Clear the current plate from the grid
        for i in reversed(range(self.grid.count())): 
            widget_to_remove = self.grid.itemAt(i).widget()
            # remove it from the layout list
            self.grid.removeWidget(widget_to_remove)
            # remove it from the gui
            widget_to_remove.setParent(None)
        # Create the new plate
        plate_name = self.plate_combo.currentText()
        plate = next(p for p in self.plate_options if p.name == plate_name)
        self.create_plate(plate)
        if self.main_window.actual_array.empty:
            self.assign_wells()
        self.preview_array()
        self.plate_changed.emit(plate)
    
    def calibrate_plate(self):
        self.calibrate_plate_signal.emit()
    
    def snake_df(self,df):
        sorted_array = []
        for col, col_df in df.groupby('column'):
            if col % 2 == 0:
                col_df = col_df.sort_values('row',ascending=True)
            else:
                col_df = col_df.sort_values('row',ascending=False)
            sorted_array.append(col_df)
        
        return pd.concat(sorted_array)

    def assign_wells(self):
        sorted_df = self.snake_df(self.main_window.wells_df)
        reaction_df = self.main_window.all_reactions
        if len(sorted_df) < len(reaction_df):
            self.main_window.popup_message("Error","The number of wells in the plate is less than the number of reactions")
            reaction_df = reaction_df.iloc[:len(sorted_df)]
            
        self.full_array = pd.concat([sorted_df.iloc[:len(reaction_df)].reset_index(drop=True),reaction_df.reset_index(drop=True)],axis=1)
        self.full_array = self.full_array.set_index(['well_number','row','column','replicate_id','unique_id']).stack()
        self.full_array = self.full_array.reset_index()
        self.full_array.columns = ['well_number','row','column','replicate_id','unique_id','reagent','amount']
        self.full_array['Added'] = False 
        self.main_window.full_array = self.full_array

    def preview_array(self):
        reagent_name = self.reagent_combo.currentText()
        if reagent_name == '':
            reagent_name = self.main_window.full_array['reagent'].iloc[0]
        
        reagent = next(r for r in self.main_window.reagents if r.name == reagent_name)
        current_array = self.main_window.full_array
        if 'reagent' in current_array.columns:
            current_array = current_array[current_array['reagent'] == reagent_name]
            if current_array.empty:
                self.main_window.popup_message("Error", f"No rows found for reagent {reagent_name}")
                return
            self.update_plate_single(current_array, reagent)
        else:
            self.main_window.popup_message("Error","'reagent' column not found in the DataFrame")

    def update_plate_single(self, current_array,reagent):
        max_amount = max(current_array['amount'])
        # print(current_array)
        for i, row in current_array.iterrows():
            self.set_cell_color(row['well_number'], reagent, row['amount'], max_amount,row['Added'])

    def set_cell_color(self, well_number, reagent,target_amount,max_amount,added):
        cell = self.cells[well_number]
        if max_amount == 0:
            opacity = 0
        else:
            opacity = target_amount / max_amount
        color = QtGui.QColor(reagent.hex_color)
        color.setAlphaF(opacity)
        rgba_color = f"rgba({color.red()},{color.green()},{color.blue()},{color.alpha()})"
        if added:
            cell.setStyleSheet(f"background-color: {rgba_color}; border: 1px solid {self.main_window.colors['white']};")
        else:
            cell.setStyleSheet(f"background-color: {rgba_color}; border: 1px solid black;")

    def mark_reagent_as_added(self, well_number, reagent_name):
        # Find the row with the matching well_number and reagent_name
        mask = (self.main_window.full_array['well_number'] == well_number) & (self.main_window.full_array['reagent'] == reagent_name)
        
        # Set the 'Added' column to True for this row
        self.main_window.full_array.loc[mask, 'Added'] = True
    
class ArrayWidget(QtWidgets.QWidget):
    """
    A custom widget for handling array-related functionality.

    Args:
        main_window (QtWidgets.QMainWindow): The main window of the application.

    Attributes:
        main_window (QtWidgets.QMainWindow): The main window of the application.
        layout (QtWidgets.QHBoxLayout): The layout of the widget.
        array_load_button (QtWidgets.QPushButton): The button for loading an array.
        reagent_input_button (QtWidgets.QPushButton): The button for editing experiment design.
        array_design_window (ArrayDesignWindow): The window for array design.

    Methods:
        open_reagent_input: Opens the reagent input window.
        load_experiment: Loads the experiment.
        deactivate_array_buttons: Deactivates the array buttons.
        activate_array_buttons: Activates the array buttons.
    """

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

        self.layout = QtWidgets.QHBoxLayout(self)

        self.array_load_button = QtWidgets.QPushButton("Load Array")
        self.array_load_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.array_load_button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}")
        self.array_load_button.clicked.connect(self.load_experiment)
        self.layout.addWidget(self.array_load_button)

        self.reagent_input_button = QtWidgets.QPushButton("Edit Experiment Design")
        self.reagent_input_button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}")
        self.reagent_input_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.reagent_input_button.clicked.connect(self.open_reagent_input)
        self.layout.addWidget(self.reagent_input_button)

        self.print_array_button = QtWidgets.QPushButton("Print Array")
        self.print_array_button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}")
        self.print_array_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.print_array_button.clicked.connect(self.main_window.print_array)

        self.activate_array_buttons()

    def open_reagent_input(self):
        """
        Opens the reagent input window.
        """
        self.array_design_window = ArrayDesignWindow(self.main_window)
        self.array_design_window.show()
    
    def load_experiment(self):
        """
        Loads the experiment.
        """
        self.main_window.load_experiment()

    def deactivate_array_buttons(self):
        """
        Deactivates the array buttons.
        """
        self.array_load_button.setEnabled(False)
        self.reagent_input_button.setEnabled(False)
        self.array_load_button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}; color: {self.main_window.colors['mid_gray']}")
        self.reagent_input_button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}; color: {self.main_window.colors['mid_gray']}")
    
    def activate_array_buttons(self):
        """
        Activates the array buttons.
        """
        self.array_load_button.setEnabled(True)
        self.reagent_input_button.setEnabled(True)
        self.array_load_button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}; color: {self.main_window.colors['white']}")
        self.reagent_input_button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}; color: {self.main_window.colors['white']}")

class ArrayDesignWindow(QtWidgets.QDialog):
    """
    A dialog window for designing arrays.

    This class provides a dialog window for designing arrays. It allows users to input reagent information,
    such as reagent name, minimum and maximum concentration, number of concentrations, and other parameters.
    Users can add, edit, and delete reagent rows, and calculate the number of combinations based on the input.

    Args:
        main_window (QtWidgets.QMainWindow): The main window object.

    Attributes:
        main_window (QtWidgets.QMainWindow): The main window object.
        all_reactions (list): A list of all reactions.
        reaction_metadata (pandas.DataFrame): Metadata for reactions.
        layout (QtWidgets.QVBoxLayout): The layout of the dialog window.
        reagent_table (QtWidgets.QTableWidget): The table widget for displaying reagent information.
        grid_layout (QtWidgets.QGridLayout): The grid layout for the widgets below the table.
        experiment_name_input (QtWidgets.QLineEdit): The input field for the experiment name.
        fill_reagent_input (QtWidgets.QComboBox): The combo box for selecting the fill reagent.
        volume_input (QtWidgets.QDoubleSpinBox): The spin box for entering the volume.
        replicates_input (QtWidgets.QDoubleSpinBox): The spin box for entering the number of replicates.
        combinations_value (QtWidgets.QLabel): The label for displaying the number of combinations.

    Methods:
        calculate_combinations: Calculates the number of combinations based on the input.
        update_combinations_label: Updates the label for displaying the number of combinations.
        edit_reagents: Opens the reagent editor dialog.
        add_reagent_to_main: Adds a reagent to the main window.
        add_reagent_row: Adds a new row to the reagent table.
        update_all_reagent_combo_boxes: Updates all reagent combo boxes.
        delete_reagent_row: Deletes a reagent row from the table.
        calculate_reactions: Calculates the reactions based on the input.
    """
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setWindowTitle("Reagent Input")
        self.resize(800, 600)
        self.all_reactions = self.main_window.all_reactions
        self.reaction_metadata = self.main_window.reaction_metadata

        self.layout = QtWidgets.QVBoxLayout(self)

        self.reagent_table = QtWidgets.QTableWidget(0, 5)  # 0 rows, 4 columns
        self.reagent_table.setHorizontalHeaderLabels(["Reagent Name", "Min Concentration", "Max Concentration", "Number of Concentrations","Delete"])
        self.layout.addWidget(self.reagent_table)
        # Set the width of the columns
        for i in range(self.reagent_table.columnCount()):
            self.reagent_table.setColumnWidth(i, 150)

        # Create a grid layout for the widgets below the table
        self.grid_layout = QtWidgets.QGridLayout()
        self.grid_layout.setColumnStretch(0, 1)  # Set the stretch factor of the first column to 1
        self.grid_layout.setColumnStretch(1, 1)  # Set the stretch factor of the second column to 1
        self.grid_layout.setColumnStretch(2, 3)  # Set the stretch factor of the third column to 1

        add_reagent_button = QtWidgets.QPushButton("Add Row")
        add_reagent_button.clicked.connect(self.add_reagent_row)
        self.grid_layout.addWidget(add_reagent_button, 0, 2)

        add_new_reagent_button = QtWidgets.QPushButton("Edit Reagent")
        add_new_reagent_button.clicked.connect(self.edit_reagents)
        self.grid_layout.addWidget(add_new_reagent_button,1,2)

        submit_button = QtWidgets.QPushButton("Submit")
        submit_button.setStyleSheet(f"background-color: {self.main_window.colors['red']}")
        submit_button.clicked.connect(self.submit)
        self.grid_layout.addWidget(submit_button,2,2)

        experiment_name_label = QtWidgets.QLabel("Experiment Name:")
        self.grid_layout.addWidget(experiment_name_label, 0, 0)
        self.experiment_name_input = QtWidgets.QLineEdit()
        self.grid_layout.addWidget(self.experiment_name_input, 0, 1)

        fill_reagent_label = QtWidgets.QLabel("Fill reagent:")
        self.grid_layout.addWidget(fill_reagent_label, 1, 0)
        self.fill_reagent_input = QtWidgets.QComboBox()
        names = self.main_window.get_reagent_names()
        self.fill_reagent_input.addItems(names)
        self.fill_reagent_input.setEditable(False)
        self.grid_layout.addWidget(self.fill_reagent_input, 1, 1)

        volume_label = QtWidgets.QLabel("Volume (uL):")
        self.grid_layout.addWidget(volume_label, 2, 0)

        self.volume_input = QtWidgets.QDoubleSpinBox()
        self.volume_input.setRange(1, 50)  # Set a minimum and maximum value
        self.volume_input.setDecimals(0)  # Set the number of decimal places
        self.volume_input.setAlignment(QtCore.Qt.AlignLeft)  # Align to the left
        self.grid_layout.addWidget(self.volume_input, 2, 1)

        self.replicates_label = QtWidgets.QLabel("Number of replicates:")
        self.grid_layout.addWidget(self.replicates_label, 3, 0)

        self.replicates_input = QtWidgets.QDoubleSpinBox()
        self.replicates_input.setRange(1, 100)  # Set a minimum and maximum value
        self.replicates_input.setDecimals(0)  # Set the number of decimal places
        self.replicates_input.setAlignment(QtCore.Qt.AlignLeft)  # Align to the left
        self.replicates_input.valueChanged.connect(self.update_combinations_label)
        self.grid_layout.addWidget(self.replicates_input,3,1)
        
        self.combinations_label = QtWidgets.QLabel("Number of combinations:")
        self.grid_layout.addWidget(self.combinations_label,4,0)
        self.combinations_value = QtWidgets.QLabel()
        self.grid_layout.addWidget(self.combinations_value,4,1)
        
        self.layout.addLayout(self.grid_layout)
        # Prepopulate the table if reaction_metadata is not None
        if not self.reaction_metadata.empty:
            for _, row in self.reaction_metadata.iterrows():
                self.add_reagent_row(row)
            self.experiment_name_input.setText(self.reaction_metadata['Experiment_name'][0])
            self.fill_reagent_input.setCurrentText(self.reaction_metadata['Fill_reagent'][0])
            self.volume_input.setValue(self.reaction_metadata['Final_volume'][0])
            self.replicates_input.setValue(self.reaction_metadata['Replicates'][0])
        else:
            self.add_reagent_row()

        self.update_combinations_label()

    def calculate_combinations(self):
        combinations = 1
        for row in range(self.reagent_table.rowCount()):
            num_concentrations = self.reagent_table.cellWidget(row, 3).value()
            combinations *= num_concentrations
        combinations *= self.replicates_input.value()
        return int(combinations)

    def update_combinations_label(self):
        combinations = self.calculate_combinations()
        self.combinations_value.setText(str(combinations))

    def edit_reagents(self):
        editor = ReagentEditor(self.main_window, self.add_reagent_to_main)
        editor.exec()

    def add_reagent_to_main(self):
        # Update the items in the combo boxes
        for row in range(self.reagent_table.rowCount()):
            combo_box = self.reagent_table.cellWidget(row, 0)
            current_reagent = combo_box.currentText()

            combo_box.clear()
            combo_box.addItems(self.main_window.get_reagent_names())

            index = combo_box.findText(current_reagent)
            if index != -1:
                combo_box.setCurrentIndex(index)
        self.fill_reagent_input.clear()
        self.fill_reagent_input.addItems(self.main_window.get_reagent_names())
        self.fill_reagent_input.currentIndexChanged.connect(self.update_all_reagent_combo_boxes)
        # self.main_window.update_slot_reagents()

    def add_reagent_row(self,row_data=None):
        row = self.reagent_table.rowCount()
        self.reagent_table.insertRow(row)

        reagent_name_input = QtWidgets.QComboBox()
        names = [name for name in self.main_window.get_reagent_names() if name != self.fill_reagent_input.currentText()]
        reagent_name_input.addItems(names)
        reagent_name_input.setEditable(False)  # The user must select one of the provided options
        reagent_name_input.currentIndexChanged.connect(self.update_all_reagent_combo_boxes)
        min_concentration_input = QtWidgets.QDoubleSpinBox()
        min_concentration_input.setRange(0, 100)  # Set a minimum and maximum value
        min_concentration_input.setDecimals(2)  # Set the number of decimal places
        
        max_concentration_input = QtWidgets.QDoubleSpinBox()
        max_concentration_input.setRange(0, 100)  # Set a minimum and maximum value
        max_concentration_input.setDecimals(2)  # Set the number of decimal places
        
        num_concentrations_input = QtWidgets.QSpinBox()
        num_concentrations_input.setRange(1, 100)  # Set a minimum and maximum value
        num_concentrations_input.valueChanged.connect(self.update_combinations_label)

        self.reagent_table.setCellWidget(row, 0, reagent_name_input)
        self.reagent_table.setCellWidget(row, 1, min_concentration_input)
        self.reagent_table.setCellWidget(row, 2, max_concentration_input)
        self.reagent_table.setCellWidget(row, 3, num_concentrations_input)

        delete_button = QtWidgets.QPushButton("Delete")
        delete_button.clicked.connect(lambda: self.delete_reagent_row(row))
        self.reagent_table.setCellWidget(row, 4, delete_button)
        self.reagent_table.setRowHeight(row, delete_button.sizeHint().height())
        if row_data is not None and not self.reaction_metadata.empty and type(row_data) != bool:
            reagent_name_input.setCurrentText(row_data['Reagent'])
            min_concentration_input.setValue(row_data['Min Concentration'])
            max_concentration_input.setValue(row_data['Max Concentration'])
            num_concentrations_input.setValue(row_data['Num Concentrations'])
        self.update_all_reagent_combo_boxes()

    def update_all_reagent_combo_boxes(self):
        currently_selected_reagents = [self.fill_reagent_input.currentText()]

        for row in range(self.reagent_table.rowCount()):
            combo_box = self.reagent_table.cellWidget(row, 0)
            current_reagent = combo_box.currentText()
            combo_box.blockSignals(True)  # Block signals
            combo_box.clear()
            available_reagents = [name for name in self.main_window.get_reagent_names() if name not in currently_selected_reagents]
            combo_box.addItems(available_reagents)
            index = combo_box.findText(current_reagent)
            if index != -1:
                combo_box.setCurrentIndex(index)
            combo_box.blockSignals(False)  # Unblock signals
            currently_selected_reagents.append(combo_box.currentText())  # Append after updating the combo box

    
    def delete_reagent_row(self, row):
        self.reagent_table.removeRow(row)
        self.update_combinations_label()

        # Update the row numbers in the lambda functions
        for row in range(self.reagent_table.rowCount()):
            delete_button = self.reagent_table.cellWidget(row, 4)
            delete_button.clicked.disconnect()
            delete_button.clicked.connect(lambda: self.delete_reagent_row(row))

    def calculate_reactions(self):
        data = []
        target_concentrations_list = []
        for row in range(self.reagent_table.rowCount()):
            reagent_name = self.reagent_table.cellWidget(row, 0).currentText()
            min_concentration = self.reagent_table.cellWidget(row, 1).value()
            max_concentration = self.reagent_table.cellWidget(row, 2).value()
            num_concentrations = self.reagent_table.cellWidget(row, 3).value()
            if num_concentrations == 1:
                target_concentrations = [max_concentration]
            else:
                target_concentrations = np.linspace(min_concentration, max_concentration, num_concentrations).tolist()
            data.append([reagent_name, min_concentration, max_concentration, num_concentrations, target_concentrations])
            target_concentrations_list.append(target_concentrations)

        df = pd.DataFrame(data, columns=['Reagent', 'Min Concentration', 'Max Concentration', 'Num Concentrations', 'Target Concentrations'])
        df['Experiment_name'] = self.experiment_name_input.text()
        df['Fill_reagent'] = self.fill_reagent_input.currentText()
        df['Final_volume'] = self.volume_input.value()
        df['Replicates'] = self.replicates_input.value()
        self.reaction_metadata = df

        combinations = list(itertools.product(*target_concentrations_list))
        combinations_df = pd.DataFrame(combinations, columns=[row[0] for row in data])
        combinations_df[self.fill_reagent_input.currentText()] = self.volume_input.value() - combinations_df.sum(axis=1)
        combinations_df['replicate_id'] = combinations_df.index
        # Replicate rows based on replicates_input value
        replicates_df = pd.concat([combinations_df for i in range(int(self.replicates_input.value()))], ignore_index=True)
        replicates_df['unique_id'] = replicates_df.index
        replicates_df = replicates_df.set_index(['replicate_id','unique_id']).reset_index()

        experiment_name = self.experiment_name_input.text()
        experiment_dir = f'./Experiments/{experiment_name}'
        os.makedirs(experiment_dir, exist_ok=True)

        # Write metadata to a CSV file
        df.to_csv(f'{experiment_dir}/{experiment_name}_metadata.csv', index=False)

        # Write replicates_df to a CSV file
        replicates_df.to_csv(f'{experiment_dir}/{experiment_name}_reactions.csv', index=False)

        self.all_reactions = replicates_df
    
    def validate_input(self):
        if self.experiment_name_input.text() == '':
            self.main_window.popup_message("Error", "Please enter an experiment name")
            return False
        total_volume = self.volume_input.value()
        for row in range(self.reagent_table.rowCount()):
            reagent_name = self.reagent_table.cellWidget(row, 0).currentText()
            min_concentration = self.reagent_table.cellWidget(row, 1).value()
            max_concentration = self.reagent_table.cellWidget(row, 2).value()
            num_concentrations = self.reagent_table.cellWidget(row, 3).value()
            if min_concentration >= max_concentration:
                self.main_window.popup_message("Error", f"Min concentration for {reagent_name} must be less than max concentration")
                return False
            target_concentrations = np.linspace(min_concentration, max_concentration, num_concentrations).tolist()
            if not all(concentration.is_integer() for concentration in target_concentrations):
                self.main_window.popup_message("Error", f"Target concentrations for {reagent_name} must be whole numbers")
                return False
            total_volume -= max_concentration
        if total_volume < 0:
            self.main_window.popup_message("Error", "Total volume must be greater than or equal to 0")
            return False
        return True
    
    def submit(self):
        self.update_combinations_label()
        if not self.validate_input():
            return
        self.calculate_reactions()
        self.main_window.all_reactions = self.all_reactions
        self.main_window.reaction_metadata = self.reaction_metadata
        self.main_window.experiment_name = self.experiment_name_input.text()
        self.main_window.update_plate_box()
        self.main_window.set_cartridges()
        self.close()

class CustomSpinBox(QtWidgets.QDoubleSpinBox):
    def __init__(self,possible_steps, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.values = possible_steps
        self.setDecimals(0)

    def stepBy(self, steps):
        current_index = self.values.index(self.value())
        new_index = max(0, min(current_index + steps, len(self.values) - 1))
        self.setValue(self.values[new_index])

class SimpleCoordinateBox(QtWidgets.QGroupBox):
    def __init__(self, title, main_window):
        super().__init__(title)
        self.main_window = main_window
        self.layout = QtWidgets.QGridLayout(self)
        self.value_labels = []

        labels = ["X", "Y", "Z", "P"]
        self.entries = {}
        self.target_entries = {}

        for i, axis in enumerate(labels):
            label = QtWidgets.QLabel(axis)
            self.layout.addWidget(label, i, 0)

            entry = QtWidgets.QLabel()
            entry.setAlignment(QtCore.Qt.AlignCenter)
            self.layout.addWidget(entry, i, 1)
            self.entries[axis] = entry

            target_entry = QtWidgets.QLabel()
            target_entry.setAlignment(QtCore.Qt.AlignCenter)
            self.layout.addWidget(target_entry, i, 2)
            self.target_entries[axis] = target_entry
            
        self.step_size_label = QtWidgets.QLabel("Step Size:")
        self.layout.addWidget(self.step_size_label, 2, 3)
        self.step_size_input = CustomSpinBox(self.main_window.possible_steps)
        self.step_size_input.setRange(2, 2000)
        self.step_size_input.setValue(500)
        self.step_size_input.setFocusPolicy(QtCore.Qt.NoFocus)
        self.step_size_input.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        self.layout.addWidget(self.step_size_input, 3, 3, 1, 1)

    def update_coordinates(self, values,target_values):
        for axis in values.keys():
            self.entries[axis].setText(str(values[axis]))
            self.target_entries[axis].setText(str(target_values[axis]))

    def update_step_size(self,step_size):
        self.step_size_input.setValue(step_size)


class CoordinateBox(QtWidgets.QGroupBox):
    """
    A custom widget that displays coordinate values.

    Args:
        title (str): The title of the coordinate box.
        main_window (QtWidgets.QMainWindow): The main window object.

    Attributes:
        main_window (QtWidgets.QMainWindow): The main window object.
        layout (QtWidgets.QGridLayout): The layout of the coordinate box.
        value_labels (list): A list of value labels.
        entries (dict): A dictionary of coordinate value labels.
        target_entries (dict): A dictionary of target coordinate value labels.

    """
    motors_activated = QtCore.Signal(bool)
    home_motors = QtCore.Signal(bool)
    def __init__(self, title, main_window):
        super().__init__(title)
        self.main_window = main_window
        self.layout = QtWidgets.QGridLayout(self)
        self.value_labels = []

        labels = ["X", "Y", "Z", "P"]
        self.entries = {}
        self.target_entries = {}

        for i, axis in enumerate(labels):
            label = QtWidgets.QLabel(axis)
            self.layout.addWidget(label, i, 0)

            entry = QtWidgets.QLabel()
            entry.setAlignment(QtCore.Qt.AlignCenter)
            self.layout.addWidget(entry, i, 1)
            self.entries[axis] = entry

            target_entry = QtWidgets.QLabel()
            target_entry.setAlignment(QtCore.Qt.AlignCenter)
            self.layout.addWidget(target_entry, i, 2)
            self.target_entries[axis] = target_entry
        self.set_text_bg_color('white',self.main_window.colors['dark_gray'])
        self.activate_motors_button = QtWidgets.QPushButton("Activate")
        self.activate_motors_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.activate_motors_button.setStyleSheet(f"background-color: {self.main_window.colors['blue']}")
        self.activate_motors_button.clicked.connect(lambda: self.motors_activated.emit(True))
        self.activate_motors_button.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        self.layout.addWidget(self.activate_motors_button, 0, 3, 1, 1)

        self.home_motors_button = QtWidgets.QPushButton("Home")
        self.home_motors_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.home_motors_button.setStyleSheet(f"background-color: {self.main_window.colors['green']}")
        self.home_motors_button.clicked.connect(lambda: self.home_motors.emit(True))
        self.home_motors_button.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        self.layout.addWidget(self.home_motors_button, 1, 3, 1, 1)

        self.step_size_label = QtWidgets.QLabel("Step Size:")
        self.layout.addWidget(self.step_size_label, 2, 3)
        self.step_size_input = CustomSpinBox(self.main_window.possible_steps)
        self.step_size_input.setRange(2, 2000)
        self.step_size_input.setValue(500)
        self.step_size_input.setFocusPolicy(QtCore.Qt.NoFocus)
        self.step_size_input.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        self.layout.addWidget(self.step_size_input, 3, 3, 1, 1)

    def update_step_size(self,step_size):
        self.step_size_input.setValue(step_size)

    def update_coordinates(self, values,target_values):
        """
        Update the coordinate values and target coordinate values.

        Args:
            values (dict): A dictionary of coordinate values.
            target_values (dict): A dictionary of target coordinate values.

        """
        for axis in values.keys():
            self.entries[axis].setText(str(values[axis]))
            self.target_entries[axis].setText(str(target_values[axis]))

    def set_text_bg_color(self, color,bg_color):
        """
        Set the text and background color of the coordinate value labels.

        Args:
            color (str): The color of the text.
            bg_color (str): The background color.

        """
        for axis in self.entries.keys():
            self.entries[axis].setStyleSheet(f"color: {color}")
            self.entries[axis].setStyleSheet(f"background-color: {bg_color}")
            self.target_entries[axis].setStyleSheet(f"color: {color}")
            self.target_entries[axis].setStyleSheet(f"background-color: {bg_color}")


class ConnectionBox(QtWidgets.QGroupBox):
    """
    A custom widget for managing connections.

    This widget provides options for connecting to machine and balance ports.

    Signals:
        - machine_connected: emitted when the machine is connected, with the selected port as the argument.
        - balance_connected: emitted when the balance is connected, with the selected port as the argument.
    """

    machine_connected = QtCore.Signal(str)  # Define a new signal
    balance_connected = QtCore.Signal(str)  # Define a new signal
    
    def __init__(self, title, main_window):
        """
        Initialize the ConnectionBox.

        Args:
            title (str): The title of the group box.
            main_window (QtWidgets.QMainWindow): The main window object.

        """
        super().__init__(title)
        self.main_window = main_window
        self.layout = QtWidgets.QGridLayout(self)

        self.machine_port_options = QtWidgets.QComboBox()
        self.machine_port_options.addItems(["COM1", "COM2", "COM3"])
        self.machine_port_options.setFocusPolicy(QtCore.Qt.NoFocus)
        self.machine_connect_button = QtWidgets.QPushButton("Connect")
        self.machine_connect_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.machine_connect_button.setStyleSheet(f"background-color: {self.main_window.colors['blue']}")
        self.machine_connect_button.clicked.connect(lambda: self.machine_connected.emit(self.machine_port_options.currentText()))

        self.layout.addWidget(QtWidgets.QLabel("Machine Ports:"), 0, 0)
        self.layout.addWidget(self.machine_port_options, 0, 1)
        self.layout.addWidget(self.machine_connect_button, 0, 2)

        self.balance_port_options = QtWidgets.QComboBox()
        self.balance_port_options.addItems(["COM1", "COM2", "COM3"])
        self.balance_port_options.setFocusPolicy(QtCore.Qt.NoFocus)
        self.balance_connect_button = QtWidgets.QPushButton("Connect")
        self.balance_connect_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.balance_connect_button.setStyleSheet(f"background-color: {self.main_window.colors['blue']}")
        self.balance_connect_button.clicked.connect(lambda: self.balance_connected.emit(self.balance_port_options.currentText()))
        self.layout.addWidget(QtWidgets.QLabel("Balance Ports:"), 1, 0)
        self.layout.addWidget(self.balance_port_options, 1, 1)
        self.layout.addWidget(self.balance_connect_button, 1, 2)

        self.update_ports()

    def update_ports(self):
        # Get a list of all connected COM ports
        ports = comports()
        port_names = [port.device for port in ports]

        # Clear the current items in the combo boxes
        self.machine_port_options.clear()
        self.balance_port_options.clear()

        # Add the new items to the combo boxes
        self.machine_port_options.addItems(port_names+['Virtual machine'])
        self.balance_port_options.addItems(port_names+['Virtual balance'])

class PressurePlotBox(QtWidgets.QGroupBox):
    """
    A custom widget that displays a pressure plot with current and target pressure values.

    Args:
        title (str): The title of the group box.
        main_window (QtWidgets.QMainWindow): The main window object.

    Signals:
        regulating_pressure(bool): Signal emitted when the pressure regulation button is toggled.

    """

    regulating_pressure = QtCore.Signal(bool)

    def __init__(self, title, main_window):
        super().__init__(title)
        self.main_window = main_window
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
        self.pressure_regulation_button.setStyleSheet(f"background-color: {self.main_window.colors['blue']}")
        self.regulating = False
        self.pressure_regulation_button.clicked.connect(self.toggle_regulation)
        self.layout.addWidget(self.pressure_regulation_button, 1, 0, 1, 4)  # Add the button to the layout at position (2, 0) and make it span 2 columns

        self.chart = QtCharts.QChart()
        self.chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.chart.setBackgroundBrush(QtGui.QBrush(self.main_window.colors['dark_gray']))  # Set the background color to grey
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

    def set_text_bg_color(self, color,bg_color):
        self.current_pressure_value.setStyleSheet(f"color: {color}")
        self.current_pressure_value.setStyleSheet(f"background-color: {bg_color}")
        self.target_pressure_value.setStyleSheet(f"color: {color}")
        self.target_pressure_value.setStyleSheet(f"background-color: {bg_color}")
    
    def update_pressure(self, pressure_log,target_pressure):
        self.series.clear()
        self.target_pressure_series.clear()
        for i, pressure in enumerate(pressure_log):
            self.series.append(i, pressure)

        self.target_pressure_series.append(0,target_pressure)  # Add the lower point of the target pressure line
        self.target_pressure_series.append(100,target_pressure)  # Add the upper point of the target pressure line

        min_pressure = min(pressure_log + [target_pressure]) - 0.5
        max_pressure = max(pressure_log + [target_pressure]) + 0.5

        self.axisY.setRange(min_pressure, max_pressure)

        self.current_pressure_value.setText(f"{pressure_log[-1]:.3f}")  # Update the current pressure value
        self.target_pressure_value.setText(f"{target_pressure:.3f}")  # Update the target pressure value
    
    def toggle_regulation(self):
        self.regulating = not self.regulating
        self.regulating_pressure.emit(self.regulating)

class ShortcutTable(QtWidgets.QGroupBox):
    """
    A custom widget that displays a table of shortcuts.

    Args:
        shortcuts (list): A list of Shortcut objects.
        title (str): The title of the group box.

    Attributes:
        layout (QtWidgets.QVBoxLayout): The layout of the group box.
        table (QtWidgets.QTableWidget): The table widget that displays the shortcuts.

    """
    def __init__(self, shortcuts, title):
        super().__init__(title)
        self.setFocusPolicy(QtCore.Qt.NoFocus)

        self.layout = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Shortcut Name", "Shortcut Key"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setRowCount(len(shortcuts))

        for i, shortcut in enumerate(shortcuts):
            item = QtWidgets.QTableWidgetItem(shortcut.key_name)
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.table.setItem(i, 0, item)
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(shortcut.name))
        self.table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout.addWidget(self.table)

class CommandTable(QtWidgets.QGroupBox):
    """
    A custom widget that displays a table of commands.

    Args:
        main_window (QtWidgets.QMainWindow): The main window of the application.
        commands (list): A list of command objects.
        title (str): The title of the group box.

    Attributes:
        main_window (QtWidgets.QMainWindow): The main window of the application.
        layout (QtWidgets.QVBoxLayout): The layout of the group box.
        table (QtWidgets.QTableWidget): The table widget that displays the commands.

    """

    def __init__(self, main_window, commands, title):
        super().__init__(title)
        self.main_window = main_window
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Number", "Command"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setRowCount(1)

        for i, command in enumerate(commands):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(str(command.get_number())))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(command.get_command()))
        self.table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout.addWidget(self.table)
        self.table.setColumnWidth(0, 60)

    def add_command(self, new_command):
        """
        Adds a new command to the table.

        Args:
            new_command: The new command object to be added.

        """
        self.table.insertRow(0)
        self.table.setItem(0, 0, QtWidgets.QTableWidgetItem(str(new_command.get_number())))
        self.table.setItem(0, 1, QtWidgets.QTableWidgetItem(new_command.get_command()))
        self.table.item(0, 0).setBackground(QtGui.QBrush(QtGui.QColor(self.main_window.colors['darker_gray'])))  # Set initial color to red
        self.table.item(0, 1).setBackground(QtGui.QBrush(QtGui.QColor(self.main_window.colors['darker_gray'])))  # Set initial color to red
        self.table.viewport().update()

    def sent_command(self, command_number):
        """
        Executes a command by highlighting it in the table.

        Args:
            command_number: The number of the command to be executed.

        """
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0).text() == str(command_number):
                for j in range(self.table.columnCount()):
                    self.table.item(i, j).setBackground(QtGui.QBrush(QtGui.QColor(self.main_window.colors['mid_gray'])))
                break
        self.table.viewport().update()

    def execute_command(self, command_number):
        """
        Executes a command by highlighting it in the table.

        Args:
            command_number: The number of the command to be executed.

        """
        current_command_found = False
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item is not None:
                if item.text() == str(command_number):
                    current_command_found = True
                    for j in range(self.table.columnCount()):
                        self.table.item(i, j).setBackground(QtGui.QBrush(QtGui.QColor(self.main_window.colors['red'])))
                elif current_command_found and int(item.text()) < command_number:
                    for j in range(self.table.columnCount()):
                        self.table.item(i, j).setBackground(QtGui.QBrush(QtGui.QColor(self.main_window.colors['dark_gray'])))
        self.table.viewport().update()
    
    def completed_command(self, command_number):
        """
        Marks a command as completed by highlighting it in the table.

        Args:
            command_number: The number of the command to be marked as completed.

        """
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0).text() == str(command_number):
                for j in range(self.table.columnCount()):
                    self.table.item(i, j).setBackground(QtGui.QBrush(QtGui.QColor(self.main_window.colors['dark_gray'])))
                break
        self.table.viewport().update()

    def remove_command(self, command_number):
        """
        Removes a command from the table.

        Args:
            command_number: The number of the command to be removed.

        """
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0).text() == str(command_number):
                self.table.removeRow(i)
                break
        self.table.viewport().update()

class Reagent():
    """
    Represents a reagent with a name, color dictionary, color name, and hex color.

    Attributes:
        name (str): The name of the reagent.
        color_dict (dict): A dictionary mapping color names to hex values.
        color_name (str): The name of the color for the reagent.
        hex_color (str): The hex value of the color for the reagent.
    """

    def __init__(self, name, color_dict, color_name):
        self.name = name
        self.color_dict = color_dict
        self.color_name = color_name
        self.hex_color = self.color_dict[self.color_name]

    def to_dict(self):
        """
        Converts the reagent object to a dictionary.

        Returns:
            dict: A dictionary representation of the reagent object.
        """
        return {"name": self.name, "color_name": self.color_name}

class Slot:
    """
    Represents a slot in a system.

    Attributes:
        number (int): The slot number.
        reagent (str): The reagent in the slot.
        confirmed (bool): Indicates if the slot has been confirmed.
    """

    def __init__(self, number, reagent):
        self.number = number
        self.reagent = reagent
        self.confirmed = False
    
    def change_reagent(self, new_reagent):
        """
        Changes the reagent in the slot.

        Args:
            new_reagent (str): The new reagent to be placed in the slot.
        """
        self.reagent = new_reagent
    
    def confirm(self):
        """
        Confirms the slot.
        """
        self.confirmed = True

class ReagentEditor():
    """
    A class that represents a reagent editor window.

    Args:
        main_window (QtWidgets.QMainWindow): The main window of the application.
        on_submit (function): A callback function to be called when reagents are submitted.

    Attributes:
        main_window (QtWidgets.QMainWindow): The main window of the application.
        reagents (list): A list of reagents.
        colors (dict): A dictionary of color names and corresponding values.
        on_submit (function): A callback function to be called when reagents are submitted.
        new_reagent_window (QtWidgets.QDialog): The dialog window for editing reagents.
        reagent_table (QtWidgets.QTableWidget): The table widget for displaying reagents.

    Methods:
        add_reagent_to_table: Adds a reagent to the table widget.
        add_new_reagent_row: Adds a new row to the table widget for adding a new reagent.
        submit_reagents: Submits the edited reagents and performs necessary actions.
        exec: Executes the reagent editor window.
    """

    def __init__(self, main_window, on_submit):
        self.main_window = main_window
        self.reagents = self.main_window.reagents
        self.colors = self.main_window.colors
        self.on_submit = on_submit

        self.new_reagent_window = QtWidgets.QDialog()
        self.new_reagent_window.setWindowTitle("Edit reagents")
        self.new_reagent_window.resize(400, 600)
        window_layout = QtWidgets.QVBoxLayout(self.new_reagent_window)

        self.reagent_table = QtWidgets.QTableWidget()
        self.reagent_table.setColumnCount(2)
        self.reagent_table.setHorizontalHeaderLabels(["Name", "Color"])
        window_layout.addWidget(self.reagent_table)

        for reagent in self.reagents:
            self.add_reagent_to_table(reagent)

        add_button = QtWidgets.QPushButton("Add Reagent")
        add_button.clicked.connect(self.add_new_reagent_row)
        window_layout.addWidget(add_button)

        submit_button = QtWidgets.QPushButton("Submit")
        submit_button.clicked.connect(self.submit_reagents)
        window_layout.addWidget(submit_button)
    
    def add_reagent_to_table(self, reagent):
        row = self.reagent_table.rowCount()
        self.reagent_table.insertRow(row)

        name_item = QtWidgets.QTableWidgetItem(reagent.name)
        self.reagent_table.setItem(row, 0, name_item)

        color_input = QtWidgets.QComboBox()
        color_input.addItems(list(self.colors.keys()))
        color_input.setCurrentText(reagent.color_name)
        self.reagent_table.setCellWidget(row, 1, color_input)

    def add_new_reagent_row(self):
        row = self.reagent_table.rowCount()
        self.reagent_table.insertRow(row)

        name_input = QtWidgets.QLineEdit()
        self.reagent_table.setCellWidget(row, 0, name_input)

        color_input = QtWidgets.QComboBox()
        color_input.addItems(list(self.main_window.colors.keys()))
        self.reagent_table.setCellWidget(row, 1, color_input) 
           
    def submit_reagents(self):
        self.reagents.clear()

        for row in range(self.reagent_table.rowCount()):
            name_item_or_widget = self.reagent_table.item(row, 0)
            if name_item_or_widget is None:
                name_item_or_widget = self.reagent_table.cellWidget(row, 0)
            name = name_item_or_widget.text()

            color_item_or_widget = self.reagent_table.cellWidget(row, 1)
            color = color_item_or_widget.currentText()

            new_reagent = Reagent(name, self.colors, color)
            self.reagents.append(new_reagent)
        self.main_window.reagents = self.reagents
        self.main_window.write_reagents_file()
        self.on_submit()
        self.new_reagent_window.close()
    
    def exec(self):
        self.new_reagent_window.exec()

class RackBox(QtWidgets.QWidget):
    """
    A custom widget representing a rack box.

    This widget displays slots for reagents and provides functionality to confirm and load/unload reagents.

    Signals:
        - reagent_confirmed: Signal emitted when a reagent is confirmed in a slot.
        - reagent_loaded: Signal emitted when a reagent is loaded into a slot.

    Args:
        main_window (QtWidgets.QMainWindow): The main window of the application.
        slots (List[Slot]): A list of Slot objects representing the slots in the rack box.
        reagents (List[Reagent]): A list of Reagent objects representing the available reagents.

    Attributes:
        main_window (QtWidgets.QMainWindow): The main window of the application.
        layout (QtWidgets.QGridLayout): The layout of the widget.
        reagents (List[Reagent]): A list of Reagent objects representing the available reagents.
        current_reagents (List[QtWidgets.QLabel]): A list of QLabel objects representing the current reagents in each slot.
        slot_dropdowns (List[QtWidgets.QComboBox]): A list of QComboBox objects representing the dropdowns for selecting reagents.
        slot_buttons (List[QtWidgets.QPushButton]): A list of QPushButtons representing the confirmation buttons for each slot.
        loading_buttons (List[QtWidgets.QPushButton]): A list of QPushButtons representing the loading/unloading buttons for each slot.
        slots (List[Slot]): A list of Slot objects representing the slots in the rack box.
        reagent_names (List[str]): A list of reagent names.

    Methods:
        - emit_confirmation_signal(slot): Returns a function that emits the reagent_confirmed signal for the given slot.
        - emit_loading_signal(slot): Returns a function that emits the reagent_loaded signal for the given slot.
        - reset_confirmation(): Resets the confirmation status of all slots.
        - confirm_reagent(slot_num, reagent): Confirms the reagent in the specified slot.
        - change_reagent(slot_num, reagent): Changes the reagent in the specified slot.
        - change_gripper_reagent(reagent): Changes the reagent in the gripper slot.
        - activate_button(button, text, color): Activates the specified button with the given text and color.
        - deactivate_button(button, text): Deactivates the specified button with the given text.
        - update_load_buttons(): Updates the state of the load/unload buttons based on the current slot and gripper reagents.
        - make_transparent_icon(): Creates a transparent QIcon.

    """
    reagent_confirmed = QtCore.Signal(Slot)
    reagent_loaded = QtCore.Signal(Slot)
    gripper_toggled = QtCore.Signal()
    calibrate_rack = QtCore.Signal()

    def __init__(self, main_window, slots, reagents):
        """
        Initializes a RackBox object.

        Args:
            main_window (QtWidgets.QMainWindow): The main window of the application.
            slots (List[Slot]): A list of Slot objects representing the slots in the rack box.
            reagents (List[Reagent]): A list of Reagent objects representing the available reagents.
        """
        super().__init__()
        self.main_window = main_window
        self.layout = QtWidgets.QGridLayout(self)
        self.reagents = reagents
        self.current_reagents = []
        self.slot_dropdowns = []
        self.slot_buttons = []
        self.loading_buttons = []
        self.slots = slots
        num_slots = len(slots)
        self.reagent_names = [reagent.name for reagent in reagents]

        # Add gripper label
        self.gripper_label = QtWidgets.QLabel("Gripper")
        self.gripper_label.setAlignment(QtCore.Qt.AlignCenter)
        self.gripper_label.setStyleSheet(f"background-color: {self.main_window.colors['darker_gray']}; color: white;")
        self.gripper_label.setFixedHeight(20)
        self.layout.addWidget(self.gripper_label, 0, 0)

        # Add gripper slot
        self.gripper_slot = QtWidgets.QLabel()
        self.gripper_slot.setStyleSheet(f"background-color: {self.main_window.colors['darker_gray']}")
        self.gripper_slot.setStyleSheet("color: white")
        self.gripper_slot.setText("Empty")
        self.gripper_slot.setAlignment(QtCore.Qt.AlignCenter)
        self.layout.addWidget(self.gripper_slot, 1, 0,2,1)

        self.gripper_state_label = QtWidgets.QLabel("Gripper Open")
        self.gripper_state_label.setAlignment(QtCore.Qt.AlignCenter)
        self.gripper_state_label.setStyleSheet(f"background-color: {self.main_window.colors['darker_gray']}; color: white;")
        self.gripper_state_label.setFixedHeight(20)
        self.layout.addWidget(self.gripper_state_label, 3, 0)

        self.calibrate_rack_button = QtWidgets.QPushButton("Calibrate Rack")
        self.calibrate_rack_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.calibrate_rack_button.setStyleSheet(f"background-color: {self.main_window.colors['blue']}")
        self.calibrate_rack_button.clicked.connect(self.calibrate_rack)
        self.layout.addWidget(self.calibrate_rack_button, 4, 0)


        self.close_gripper()
        # Add an empty column for the gap
        self.layout.setColumnMinimumWidth(1, 10)

        for slot in range(num_slots):
            # Add slot label
            slot_label = QtWidgets.QLabel(f"Slot {slot+1}")
            slot_label.setAlignment(QtCore.Qt.AlignCenter)
            slot_label.setStyleSheet(f"background-color: {self.main_window.colors['darker_gray']}; color: white;")
            slot_label.setFixedHeight(20)
            self.layout.addWidget(slot_label, 0, slot+2)

            current_reagent = QtWidgets.QLabel()
            current_reagent.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}")
            current_reagent.setStyleSheet("color: white")
            current_reagent.setText("Empty")
            current_reagent.setAlignment(QtCore.Qt.AlignCenter)
            self.current_reagents.append(current_reagent)
            self.layout.addWidget(self.current_reagents[slot], 1, slot+2,2,1)

            slot_button = QtWidgets.QPushButton("Confirm")
            slot_button.setFocusPolicy(QtCore.Qt.NoFocus)
            slot_button.setStyleSheet("background-color: #1e64b4")
            self.slot_buttons.append(slot_button)
            self.slot_buttons[slot].clicked.connect(self.emit_confirmation_signal(slot))
            self.layout.addWidget(self.slot_buttons[slot], 3, slot+2)

            loading_button = QtWidgets.QPushButton("Load")
            loading_button.setFocusPolicy(QtCore.Qt.NoFocus)
            loading_button.setStyleSheet(f"background-color: {self.main_window.colors['red']}")
            self.loading_buttons.append(loading_button)
            self.loading_buttons[slot].clicked.connect(self.emit_loading_signal(slot))
            self.layout.addWidget(self.loading_buttons[slot], 4, slot+2)
        self.update_load_buttons()
    
    def open_gripper(self):
        self.gripper_state_label.setText("Gripper Open")
        self.gripper_state_label.setStyleSheet(f"background-color: {self.main_window.colors['red']}; color: white;")
    
    def close_gripper(self):
        self.gripper_state_label.setText("Gripper Closed")
        self.gripper_state_label.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}; color: white;")

    def emit_confirmation_signal(self, slot):
        def emit_confirmation_signal():
            self.reagent_confirmed.emit(self.slots[slot])
        return emit_confirmation_signal

    def emit_loading_signal(self, slot):
        def emit_loading_signal():
            target_name = self.current_reagents[slot].text()
            reagent = next((r for r in self.reagents if r.name == target_name), None)
            self.reagent_loaded.emit(Slot(slot, reagent))
        return emit_loading_signal
    
    def reset_confirmation(self):
        for slot in self.slots:
            slot.confirmed = False
        self.update_load_buttons()

    def confirm_reagent(self, slot_num, reagent):
        self.slots[slot_num].confirm()
        self.slot_buttons[slot_num].setEnabled(False)
        self.slot_buttons[slot_num].setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}; color: {self.main_window.colors['light_gray']}")
        self.update_load_buttons()
    
    def change_reagent(self, slot_num, reagent):    
        self.slots[slot_num].reagent = reagent
        self.current_reagents[slot_num].setText(reagent.name)
        self.current_reagents[slot_num].setStyleSheet(f"background-color: {reagent.hex_color}")

    def change_gripper_reagent(self, reagent):
        self.main_window.gripper_reagent = reagent
        self.gripper_slot.setText(reagent.name)
        self.gripper_slot.setStyleSheet(f"background-color: {reagent.hex_color}")
    
    def activate_button(self,button,text,color):
        button.setEnabled(True)
        button.setText(text)
        button.setStyleSheet(f"background-color: {self.main_window.colors[color]}; color: white")

    def deactivate_button(self,button,text):
        button.setEnabled(False)
        button.setText(text)
        button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}; color: {self.main_window.colors['light_gray']}")

    def update_load_buttons(self):
        for i, slot in enumerate(self.slots):
            if not slot.confirmed:
                self.deactivate_button(self.loading_buttons[i],"Load")
                self.activate_button(self.slot_buttons[i],"Confirm","blue")
            else:
                if slot.reagent.name == "Empty" and self.main_window.gripper_reagent.name == "Empty":
                    self.deactivate_button(self.loading_buttons[i],"Load")
                elif slot.reagent.name != "Empty" and self.main_window.gripper_reagent.name == "Empty":
                    self.activate_button(self.loading_buttons[i],"Load","blue")
                elif slot.reagent.name == "Empty" and self.main_window.gripper_reagent.name != "Empty":
                    self.activate_button(self.loading_buttons[i],"Unload","red")
                else:
                    self.deactivate_button(self.loading_buttons[i],"Unload")

    def make_transparent_icon(self):
        transparent_image = QtGui.QImage(1, 1, QtGui.QImage.Format_ARGB32)
        transparent_image.fill(QtCore.Qt.transparent)
        transparent_pixmap = QtGui.QPixmap.fromImage(transparent_image)
        transparent_icon = QtGui.QIcon(transparent_pixmap)
        return transparent_icon
