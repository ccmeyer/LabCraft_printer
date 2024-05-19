from PySide6 import QtCore, QtWidgets, QtGui

from PySide6 import QtCharts
from PySide6.QtCore import QTimer, QPointF
import numpy as np
import pandas as pd
import itertools
import json
import os


class Plate():
    def __init__(self, name, rows=16, columns=24,spacing=10,default=False):
        self.name = name
        self.rows = rows
        self.columns = columns
        self.spacing = spacing
        self.default = default

class PlateBox(QtWidgets.QGroupBox):
    def __init__(self,main_window, title):
        super().__init__(title)
        self.main_window = main_window
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

        self.read_plate_file()
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

        self.layout.addLayout(self.top_layout)

        self.grid = QtWidgets.QGridLayout()
        self.current_plate = [plate for plate in self.plate_options if plate.default][0]
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
        # self.simulate_button = QtWidgets.QPushButton("Simulate")
        # self.simulate_button.setFocusPolicy(QtCore.Qt.NoFocus)
        # self.simulate_button.clicked.connect(self.simulate_plate)
        # self.layout.addWidget(self.simulate_button)

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
        with open('./Presets/Plates.json', 'r') as f:
            plates = json.load(f)
        self.plate_options = [Plate(plate['name'],rows=plate['rows'],columns=plate['columns'],spacing=plate['spacing'],default=plate['default']) for plate in plates]
    
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
        self.assign_wells()
        self.preview_array()
    
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
        for i, row in current_array.iterrows():
            self.set_cell_color(row['well_number'], reagent, row['amount'], max_amount)

    def set_cell_color(self, well_number, reagent,target_amount,max_amount):
        cell = self.cells[well_number]
        if max_amount == 0:
            opacity = 0
        else:
            opacity = target_amount / max_amount
        color = QtGui.QColor(reagent.hex_color)
        color.setAlphaF(opacity)
        rgba_color = f"rgba({color.red()},{color.green()},{color.blue()},{color.alpha()})"
        cell.setStyleSheet(f"background-color: {rgba_color}; border: 1px solid black;")


class ArrayWidget(QtWidgets.QWidget):
    def __init__(self,main_window):
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

        self.activate_array_buttons()

    def open_reagent_input(self):
        self.array_design_window = ArrayDesignWindow(self.main_window)
        self.array_design_window.show()
    
    def load_experiment(self):
        self.main_window.load_experiment()

    def deactivate_array_buttons(self):
        self.array_load_button.setEnabled(False)
        self.reagent_input_button.setEnabled(False)
        self.array_load_button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}; color: {self.main_window.colors['mid_gray']}")
        self.reagent_input_button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}; color: {self.main_window.colors['mid_gray']}")
    
    def activate_array_buttons(self):
        self.array_load_button.setEnabled(True)
        self.reagent_input_button.setEnabled(True)
        self.array_load_button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}; color: {self.main_window.colors['white']}")
        self.reagent_input_button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}; color: {self.main_window.colors['white']}")

class ArrayDesignWindow(QtWidgets.QDialog):
    def __init__(self,main_window):
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
        self.volume_input.setRange(1, 10)  # Set a minimum and maximum value
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


        

class CoordinateBox(QtWidgets.QGroupBox):
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


    def update_coordinates(self, values,target_values):
        for axis in values.keys():
            self.entries[axis].setText(str(values[axis]))
            self.target_entries[axis].setText(str(target_values[axis]))

    def set_text_bg_color(self, color,bg_color):
        for axis in self.entries.keys():
            self.entries[axis].setStyleSheet(f"color: {color}")
            self.entries[axis].setStyleSheet(f"background-color: {bg_color}")
            self.target_entries[axis].setStyleSheet(f"color: {color}")
            self.target_entries[axis].setStyleSheet(f"background-color: {bg_color}")


class DropdownBox(QtWidgets.QGroupBox):
    machine_connected = QtCore.Signal(str)  # Define a new signal
    balance_connected = QtCore.Signal(str)  # Define a new signal
    
    def __init__(self, title,main_window):
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

class PressurePlotBox(QtWidgets.QGroupBox):
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

        min_pressure = min(pressure_log + [target_pressure]) - 2
        max_pressure = max(pressure_log + [target_pressure]) + 2

        self.axisY.setRange(min_pressure, max_pressure)

        self.current_pressure_value.setText(f"{pressure_log[-1]}")  # Update the current pressure value
        self.target_pressure_value.setText(f"{target_pressure}")  # Update the target pressure value
    
    def toggle_regulation(self):
        self.regulating = not self.regulating
        self.regulating_pressure.emit(self.regulating)

class ShortcutTable(QtWidgets.QGroupBox):
    def __init__(self, shortcuts,title):
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
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(str(shortcut.key)))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(shortcut.name))
        self.table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout.addWidget(self.table)

class CommandTable(QtWidgets.QGroupBox):
    def __init__(self, main_window,commands,title):
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
        self.table.insertRow(0)
        self.table.setItem(0, 0, QtWidgets.QTableWidgetItem(str(new_command.get_number())))
        self.table.setItem(0, 1, QtWidgets.QTableWidgetItem(new_command.get_command()))
        self.table.item(0, 0).setBackground(QtGui.QBrush(QtGui.QColor(self.main_window.colors['darker_gray'])))  # Set initial color to red
        self.table.item(0, 1).setBackground(QtGui.QBrush(QtGui.QColor(self.main_window.colors['darker_gray'])))  # Set initial color to red
        self.table.viewport().update()

    def execute_command(self, command_number):
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0).text() == str(command_number):
                for j in range(self.table.columnCount()):
                    self.table.item(i, j).setBackground(QtGui.QBrush(QtGui.QColor(self.main_window.colors['dark_gray'])))
                break
        self.table.viewport().update()

class Reagent():
    def __init__(self, name, color_dict,color_name):
        self.name = name
        self.color_dict = color_dict
        self.color_name = color_name
        self.hex_color = self.color_dict[self.color_name]

    def to_dict(self):
        return {"name": self.name, "color_name": self.color_name}

class Slot:
    def __init__(self, number, reagent):
        self.number = number
        self.reagent = reagent
        self.confirmed = False
    
    def change_reagent(self, new_reagent):
        self.reagent = new_reagent
    
    def confirm(self):
        self.confirmed = True

class ReagentEditor():
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
    reagent_confirmed = QtCore.Signal(Slot)
    reagent_loaded = QtCore.Signal(Slot)

    def __init__(self,main_window, slots,reagents):
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
        self.layout.addWidget(self.gripper_slot, 1, 0,4,1)

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
