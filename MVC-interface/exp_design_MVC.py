from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, 
    QPushButton, QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, 
    QAbstractItemView, QMessageBox, QMainWindow, QFileDialog, QApplication,
    QSplitter, QWidget
)
from PySide6.QtCore import Qt, Signal, QObject, QEvent
import numpy as np
from itertools import combinations_with_replacement, product
import json

def find_minimal_stock_solutions_backtracking(target_concentrations, max_droplets):
    target_concentrations.sort()

    def can_achieve_all(stock_solutions):
        achievable_concentrations = {0: []}  # concentration -> list of (stock_solution, droplets)
        for num_droplets in range(1, max_droplets + 1):
            for comb in combinations_with_replacement(stock_solutions, num_droplets):
                total_concentration = sum(comb)
                if total_concentration not in achievable_concentrations:
                    achievable_concentrations[total_concentration] = comb
        return achievable_concentrations

    def backtrack(current_solutions, index):
        achievable_concentrations = can_achieve_all(current_solutions)

        if all(tc in achievable_concentrations for tc in target_concentrations):
            return current_solutions, achievable_concentrations

        if index == len(target_concentrations):
            return None, None

        # Explore both including and excluding the current concentration as a stock solution
        with_current, achievable_with = backtrack(current_solutions + [target_concentrations[index]], index + 1)
        without_current, achievable_without = backtrack(current_solutions, index + 1)

        if with_current is None:
            return without_current, achievable_without
        if without_current is None:
            return with_current, achievable_with
        
        # Prioritize the solution with fewer stock solutions
        if len(with_current) < len(without_current):
            return with_current, achievable_with
        elif len(with_current) > len(without_current):
            return without_current, achievable_without
        else:
            # If the number of stock solutions is the same, choose the one with the lower sum of concentrations
            if sum(with_current) < sum(without_current):
                return with_current, achievable_with
            else:
                return without_current, achievable_without

    minimal_solutions, achievable_concentrations = backtrack([], 0)
    return minimal_solutions, achievable_concentrations

def multi_reagent_optimization(reagents_data, max_total_droplets):
    reagent_solutions = []
    for target_concentrations, max_droplets in reagents_data:
        solutions = []
        for droplet_limit in range(1, max_droplets + 1):
            stock_solutions, achievable_concentrations = find_minimal_stock_solutions_backtracking(target_concentrations, droplet_limit)
            max_droplets_for_any_concentration = max([len(achievable_concentrations[tc]) for tc in target_concentrations])
            solutions.append((stock_solutions, max_droplets_for_any_concentration))
        reagent_solutions.append(solutions)

    best_combination = None
    min_stock_count = float('inf')
    min_concentration_sum = float('inf')

    for combination in product(*reagent_solutions):
        stock_solution_set = set()
        total_droplets = 0
        max_droplets_per_reagent = []
        concentration_sum = 0

        for stock_solutions, droplets_used in combination:
            stock_solution_set.update(stock_solutions)
            total_droplets += droplets_used
            max_droplets_per_reagent.append(droplets_used)
            concentration_sum += sum(stock_solutions)  # Sum the concentrations used

        # Prioritize by fewest stock solutions, then by lowest concentration sum
        if total_droplets <= max_total_droplets:
            if len(stock_solution_set) < min_stock_count or (len(stock_solution_set) == min_stock_count and concentration_sum < min_concentration_sum):
                best_combination = combination
                min_stock_count = len(stock_solution_set)
                min_concentration_sum = concentration_sum

    if best_combination:
        final_stock_solutions = [sol[0] for sol in best_combination]
        max_droplets_per_reagent = [sol[1] for sol in best_combination]
    else:
        final_stock_solutions = []
        max_droplets_per_reagent = []

    return final_stock_solutions, max_droplets_per_reagent


class ExperimentDesignDialog(QDialog):
    def __init__(self, main_window, model):
        super().__init__()
        self.main_window = main_window
        self.model = model
        self.setWindowTitle("Experiment Design")
        self.setFixedSize(1500, 400)

        self.layout = QHBoxLayout(self)
        
        # Table to hold all reagent information
        self.reagent_table = QTableWidget(0, 10, self)
        self.reagent_table.setHorizontalHeaderLabels([
            "Reagent Name", "Min Conc", "Max Conc", "Steps", 
            "Mode", "Manual Input", "Max Droplets",
            "Concentrations Preview", "Stock Solutions", "Delete"
        ])
        self.reagent_table.setColumnWidth(7, 200)
        self.reagent_table.setColumnWidth(8, 100)
        self.reagent_table.setSelectionMode(QAbstractItemView.NoSelection)

        # Stock solutions table
        self.stock_table = QTableWidget(0, 4, self)
        self.stock_table.setHorizontalHeaderLabels([
            "Reagent Name", "Concentration", "Total Droplets", "Total Volume (uL)"
        ])
        self.stock_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.stock_table.setFixedWidth(400)

        self.left_layout = QVBoxLayout()
        self.left_layout.addWidget(self.reagent_table)
        self.bottom_layout = QHBoxLayout()

        self.right_layout = QVBoxLayout()
        self.right_layout.addWidget(self.stock_table)

        self.bottom_layout = QHBoxLayout()
        # Label and spin box for total reactions and replicates
        self.info_layout = QVBoxLayout()
        self.total_reactions_label = QLabel("Total Reactions: 0", self)
        self.info_layout.addWidget(self.total_reactions_label)

        self.replica_label = QLabel("Replicates:", self)
        self.replicate_spinbox = QSpinBox(self)
        self.replicate_spinbox.setMinimum(1)
        self.replicate_spinbox.setValue(self.model.metadata.get("replicates", 1))
        self.replicate_spinbox.valueChanged.connect(self.update_model_metadata)
        self.info_layout.addWidget(self.replica_label)
        self.info_layout.addWidget(self.replicate_spinbox)

        self.total_droplets_label = QLabel("Total Droplets Available:", self)
        self.total_droplets_spinbox = QSpinBox(self)
        self.total_droplets_spinbox.setMinimum(1)
        self.total_droplets_spinbox.setMaximum(100)
        self.total_droplets_spinbox.setValue(self.model.metadata.get("max_droplets", 20))
        self.total_droplets_spinbox.valueChanged.connect(self.update_model_metadata)

        self.total_droplets_used_label = QLabel("Total Droplets Used: 0", self)

        self.info_layout.addWidget(self.total_droplets_label)
        self.info_layout.addWidget(self.total_droplets_spinbox)
        self.info_layout.addWidget(self.total_droplets_used_label)

        self.button_layout = QVBoxLayout()
        # Button to add a new reagent
        self.add_reagent_button = QPushButton("Add Reagent")
        self.add_reagent_button.clicked.connect(self.add_reagent)
        self.button_layout.addWidget(self.add_reagent_button)
        
        # # Button to optimize stock solutions
        # self.optimize_button = QPushButton("Optimize Stock Solutions")
        # self.optimize_button.clicked.connect(self.optimize_stock_solutions)
        # self.button_layout.addWidget(self.optimize_button)
        
        # Button to generate the experiment
        self.generate_experiment_button = QPushButton("Generate Experiment")
        self.generate_experiment_button.clicked.connect(self.generate_experiment)
        self.button_layout.addWidget(self.generate_experiment_button)

        self.bottom_layout.addLayout(self.info_layout)
        self.bottom_layout.addLayout(self.button_layout)
        self.left_layout.addLayout(self.bottom_layout)

        self.layout.addLayout(self.left_layout)
        self.layout.addLayout(self.right_layout)

        # Connect model signals
        self.model.data_updated.connect(self.update_preview)
        self.model.stock_updated.connect(self.update_stock_table)
        self.model.experiment_generated.connect(self.update_total_reactions)
        # self.model.update_max_droplets_signal.connect(self.update_max_droplets)

    def add_reagent(self, name="", min_conc=0.0, max_conc=1.0, steps=2, mode="Linear", manual_input="", max_droplets=10, stock_solutions=""):
        """Add a new reagent row to the table and model."""
        row_position = self.reagent_table.rowCount()
        self.reagent_table.insertRow(row_position)

        # Generate a default name for the reagent
        default_name = f"reagent-{row_position + 1}"

        # Add cells for reagent name, min/max concentrations, steps, and mode
        reagent_name_item = QTableWidgetItem(default_name)
        reagent_name_item.setFlags(reagent_name_item.flags() | Qt.ItemIsEditable)
        self.reagent_table.setItem(row_position, 0, reagent_name_item)

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
        steps_item.setMinimum(2)
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

        max_droplets_item = QSpinBox()
        max_droplets_item.setMinimum(1)
        max_droplets_item.setValue(max_droplets)
        self.reagent_table.setCellWidget(row_position, 6, max_droplets_item)

        preview_item = QTableWidgetItem()
        preview_item.setTextAlignment(Qt.AlignCenter)
        self.reagent_table.setItem(row_position, 7, preview_item)

        stock_solutions_item = QTableWidgetItem(stock_solutions)
        stock_solutions_item.setTextAlignment(Qt.AlignCenter)
        self.reagent_table.setItem(row_position, 8, stock_solutions_item)

        # Delete button
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(lambda: self.delete_reagent(row_position))
        self.reagent_table.setCellWidget(row_position, 9, delete_button)

        # Add reagent to model
        self.model.add_reagent(
            name=default_name,
            min_conc=min_conc,
            max_conc=max_conc,
            steps=steps,
            mode=mode,
            manual_input=manual_input,
            max_droplets=max_droplets
        )

        # Connect signals after initializing the row to avoid 'NoneType' errors
        min_conc_item.valueChanged.connect(lambda: self.update_model_reagent(row_position))
        max_conc_item.valueChanged.connect(lambda: self.update_model_reagent(row_position))
        steps_item.valueChanged.connect(lambda: self.update_model_reagent(row_position))
        mode_item.currentIndexChanged.connect(lambda: self.update_model_reagent(row_position))
        mode_item.currentIndexChanged.connect(lambda: self.toggle_manual_entry(row_position))
        manual_conc_item.textChanged.connect(lambda: self.update_model_reagent(row_position))
        max_droplets_item.valueChanged.connect(lambda: self.update_model_reagent(row_position))
        
        self.update_model_reagent(row_position)

    def delete_reagent(self, row):
        reagent_name = self.reagent_table.item(row, 0).text()
        self.model.delete_reagent(reagent_name)
        self.reagent_table.removeRow(row)

    def update_model_reagent(self, row):
        """Update the reagent in the model based on the current row values."""
        name = self.reagent_table.item(row, 0).text()
        min_conc = self.reagent_table.cellWidget(row, 1).value()
        max_conc = self.reagent_table.cellWidget(row, 2).value()
        steps = self.reagent_table.cellWidget(row, 3).value()
        mode = self.reagent_table.cellWidget(row, 4).currentText()
        manual_input = self.reagent_table.cellWidget(row, 5).text()
        max_droplets = self.reagent_table.cellWidget(row, 6).value()

        self.model.update_reagent(row, name=name, min_conc=min_conc, max_conc=max_conc, steps=steps, mode=mode, manual_input=manual_input, max_droplets=max_droplets)

    def update_model_metadata(self):
        """Update the metadata in the model based on the current values."""
        replicates = self.replicate_spinbox.value()
        max_droplets = self.total_droplets_spinbox.value()
        self.model.update_metadata(replicates, max_droplets)

    # def optimize_stock_solutions(self):
    #     self.model.optimize_stock_solutions()
    
    def toggle_manual_entry(self, row):
        """Enable or disable the manual entry field based on mode selection."""
        mode = self.reagent_table.cellWidget(row, 4).currentText()
        manual_conc_item = self.reagent_table.cellWidget(row, 5)
        manual_conc_item.setEnabled(mode == "Manual")
        self.update_model_reagent(row)

    def update_preview(self, row):
        """Update the concentrations preview in the table based on the model."""
        reagent = self.model.get_reagent(row)   

        preview_text = ", ".join(map(str, reagent["concentrations"]))
        preview_item = self.reagent_table.item(row, 7)
        preview_item.setText(preview_text)
        preview_item.setTextAlignment(Qt.AlignCenter)

        stock_solution_text = ", ".join(map(str, reagent["stock_solutions"]))
        stock_solution_item = self.reagent_table.item(row, 8)
        stock_solution_item.setText(stock_solution_text)
        stock_solution_item.setTextAlignment(Qt.AlignCenter)

    # def update_max_droplets(self,row):
    #     print(f"Updating max droplets for row {row}")
    #     reagent = self.model.get_reagent(row)  
    #     max_droplets_item = self.reagent_table.item(row, 6)
    #     max_droplets_item.setValue(reagent["max_droplets"])       

    def update_stock_table(self):
        # Populate the stock table
        print("Updating stock table")
        self.stock_table.setRowCount(0)  # Clear existing rows
        for stock_solution in self.model.get_all_stock_solutions():
            print(f"---Adding stock solution: {stock_solution}")
            row_position = self.stock_table.rowCount()
            self.stock_table.insertRow(row_position)
            self.stock_table.setItem(row_position, 0, QTableWidgetItem(stock_solution['reagent_name']))
            self.stock_table.setItem(row_position, 1, QTableWidgetItem(str(stock_solution['concentration'])))
            self.stock_table.setItem(row_position, 2, QTableWidgetItem(str(stock_solution['total_droplets'])))
            self.stock_table.setItem(row_position, 3, QTableWidgetItem(str(stock_solution['total_volume'])))


    def generate_experiment(self):
        """Generate the experiment by asking the model to calculate it."""
        self.model.generate_experiment()

    def update_total_reactions(self, total_reactions, total_droplets_used):
        """Update the total number of reactions displayed."""
        print(f"Updating total reactions: {total_reactions}, total droplets used: {total_droplets_used}")
        self.total_reactions_label.setText(f"Total Reactions: {total_reactions}")
        
        self.total_droplets_used_label.setText(f"Total Droplets Used: {total_droplets_used}")
        if total_droplets_used > self.total_droplets_spinbox.value():
            self.total_droplets_used_label.setStyleSheet("color: red;")
        else:
            self.total_droplets_used_label.setStyleSheet("color: white;")
        

import pandas as pd
import itertools

class ExperimentModel(QObject):
    data_updated = Signal(int)  # Signal to notify when reagent data is updated, passing the row index
    stock_updated = Signal()
    experiment_generated = Signal(int,int)  # Signal to notify when the experiment is generated, passing the total number of reactions
    # update_max_droplets_signal = Signal(int) # Signal to notify when the max droplets is updated, passing the row index
    def __init__(self):
        super().__init__()
        self.reagents = []
        self.metadata = {
            "replicates": 1,
            "max_droplets": 20,
            'droplet_volume': 0.03
        }
        self.stock_solutions = []
        self.experiment_df = pd.DataFrame()
        self.complete_lookup_table = pd.DataFrame()
        self.all_droplet_df = pd.DataFrame()

    def add_reagent(self, name, min_conc, max_conc, steps, mode, manual_input,max_droplets):
        reagent = {
            "name": name,
            "min_conc": min_conc,
            "max_conc": max_conc,
            "steps": steps,
            "mode": mode,
            "manual_input": manual_input,
            "concentrations": [],
            "max_droplets": max_droplets,
            "stock_solutions": []
        }
        self.reagents.append(reagent)
        self.calculate_concentrations(len(self.reagents) - 1)

    def update_reagent(self, index, name=None, min_conc=None, max_conc=None, steps=None, mode=None, manual_input=None, max_droplets=None):
        reagent = self.reagents[index]
        if name is not None:
            reagent["name"] = name
        if min_conc is not None:
            reagent["min_conc"] = min_conc
        if max_conc is not None:
            reagent["max_conc"] = max_conc
        if steps is not None:
            reagent["steps"] = steps
        if mode is not None:
            reagent["mode"] = mode
        if manual_input is not None:
            reagent["manual_input"] = manual_input
        if max_droplets is not None:
            reagent["max_droplets"] = max_droplets

        # Update concentrations preview based on the new data
        self.calculate_concentrations(index)

    def delete_reagent(self, name):
        self.reagents = [reagent for reagent in self.reagents if reagent["name"] != name]
        self.generate_experiment()

    def update_metadata(self, replicates, max_droplets):
        self.metadata["replicates"] = replicates
        self.metadata["max_droplets"] = max_droplets
        self.generate_experiment()

    # def optimize_stock_solutions(self):
    #     """Optimize the stock solutions using multi-reagent optimization."""
    #     # Extract the concentrations and max droplets for each reagent
    #     print("Optimizing stock solutions")
    #     reagents_data = [(reagent["concentrations"], reagent["max_droplets"]) for reagent in self.reagents]
    #     optimized_solutions, max_droplets_per_reagent = multi_reagent_optimization(reagents_data, self.metadata["max_droplets"])
    #     print(f'Optimized solutions: {optimized_solutions}')
    #     print(f'Max droplets per reagent: {max_droplets_per_reagent}')
    #     for i, reagent in enumerate(self.reagents):
    #         print(f'Updating reagent {reagent["name"]} with optimized solutions')
    #         reagent['max_droplets'] = max_droplets_per_reagent[i]
    #         self.update_max_droplets_signal.emit(i)
    #         self.calculate_stock_solutions(i)
    #     self.generate_experiment()

    def calculate_concentrations(self, index):
        reagent = self.reagents[index]
        mode = reagent["mode"]
        if mode == "Manual":
            try:
                reagent["concentrations"] = [round(float(c.strip()), 2) for c in reagent["manual_input"].split(',') if c.strip()]
            except ValueError:
                reagent["concentrations"] = []
        else:
            min_conc = reagent["min_conc"]
            max_conc = reagent["max_conc"]
            steps = reagent["steps"]

            if min_conc >= max_conc:
                reagent["concentrations"] = []
                return

            if mode == "Linear":
                reagent["concentrations"] = [round(x, 2) for x in np.linspace(min_conc, max_conc, steps).tolist()]
            elif mode == "Quadratic":
                reagent["concentrations"] = [round(x, 2) for x in (np.linspace(np.sqrt(min_conc), np.sqrt(max_conc), steps)**2).tolist()]
            elif mode == "Logarithmic":
                reagent["concentrations"] = [round(x, 2) for x in np.logspace(np.log10(min_conc), np.log10(max_conc), steps).tolist()]
        
        self.calculate_stock_solutions(index)
        
        # Emit signal to update the view
        self.data_updated.emit(index)
        self.generate_experiment()

    def calculate_stock_solutions(self, index):
        reagent = self.reagents[index]
        stock_solutions, achievable_concentrations = find_minimal_stock_solutions_backtracking(reagent['concentrations'], reagent['max_droplets'])
        reagent['stock_solutions'] = stock_solutions
        reagent_lookup_table = self.create_lookup_table(reagent['name'],achievable_concentrations,stock_solutions)
        self.add_lookup_table(reagent['name'],reagent_lookup_table)
        self.add_new_stock_solutions_for_reagent(reagent['name'], stock_solutions)

    def add_new_stock_solutions_for_reagent(self, reagent_name, concentrations):
        # Remove any existing stock solutions for this reagent
        self.stock_solutions = [stock for stock in self.stock_solutions if stock['reagent_name'] != reagent_name]
        # Check if this stock solution already exists to avoid duplicates
        for concentration in concentrations:
            self.stock_solutions.append({
                "reagent_name": reagent_name,
                "concentration": concentration,
                "total_droplets": 0,
                'total_volume': 0
            })

    def create_lookup_table(self,reagent_name,achievable_concentrations, stock_solutions):
        # Initialize a DataFrame with target concentrations as index and stock solutions as columns
        lookup_table = pd.DataFrame(index=achievable_concentrations.keys(), columns=stock_solutions)
        # Iterate over the achievable concentrations and populate the lookup table
        for concentration, droplets in achievable_concentrations.items():
            droplet_counts = {stock: 0 for stock in stock_solutions}  # Initialize droplet counts
            for droplet in droplets:
                droplet_counts[droplet] += 1  # Count how many droplets of each stock solution are used
            lookup_table.loc[concentration] = pd.Series(droplet_counts)
        
        # Replace NaN values with 0 (indicating no droplets of that stock solution are used)
        lookup_table['reagent_name'] = reagent_name
        lookup_table = lookup_table.reset_index().rename(columns={'index': 'target_concentration'})
        lookup_table = lookup_table.set_index(['reagent_name','target_concentration']).stack().reset_index().rename(columns={0: 'droplet_count', 'level_2': 'stock_solution'})
        
        return lookup_table
    
    def add_lookup_table(self,reagent_name,lookup_table):
        if self.complete_lookup_table.empty:
            self.complete_lookup_table = lookup_table
            return
        # Remove any existing rows with the same reagent name
        self.complete_lookup_table = self.complete_lookup_table[self.complete_lookup_table['reagent_name'] != reagent_name].copy()
        # Append the new lookup table
        self.complete_lookup_table = pd.concat([self.complete_lookup_table, lookup_table], ignore_index=True)

    def get_reagent(self, index):
        return self.reagents[index]

    def get_all_reagents(self):
        return self.reagents
    
    def get_all_stock_solutions(self):
        return self.stock_solutions

    def generate_experiment(self):
        """Generate the experiment combinations as a pandas DataFrame."""
        reagent_names = [reagent['name'] for reagent in self.reagents]
        concentrations = [reagent['concentrations'] for reagent in self.reagents]
        concentration_combinations = list(itertools.product(*concentrations))
        self.experiment_df = pd.DataFrame(concentration_combinations, columns=reagent_names)
        self.experiment_df = self.experiment_df.stack().reset_index().rename(columns={'level_0':'reaction_id','level_1':'reagent_name',0: 'target_concentration'})
        
        # Apply replicates
        all_dfs = []
        for i in range(self.metadata["replicates"]):
            temp_df = self.experiment_df.copy()
            if not temp_df.empty:
                temp_df['replicate'] = i
                temp_df['unique_id'] = temp_df['reaction_id'] + (temp_df['replicate']*(max(temp_df['reaction_id'])+1))
            all_dfs.append(temp_df)
        self.experiment_df = pd.concat(all_dfs, ignore_index=True)

        self.all_droplet_df = self.experiment_df.merge(self.complete_lookup_table, on=['reagent_name','target_concentration'], how='left')
        max_droplet_df = self.all_droplet_df[['unique_id','droplet_count']].groupby(['unique_id']).sum().reset_index()
        print(f'Max droplet df: {max_droplet_df}')
        droplet_count = max_droplet_df['droplet_count'].max()
        print(f'Max droplet count: {droplet_count}')
        self.add_total_droplet_count_to_stock()
        self.stock_updated.emit()

        # Emit signal to notify that the experiment has been generated
        self.experiment_generated.emit(len(self.experiment_df),droplet_count)

    def add_total_droplet_count_to_stock(self):
        for stock_solution in self.stock_solutions:
            stock_solution['total_droplets'] = self.all_droplet_df[(self.all_droplet_df['reagent_name'] == stock_solution['reagent_name']) & (self.all_droplet_df['stock_solution'] == stock_solution['concentration'])]['droplet_count'].sum()
            stock_solution['total_volume'] = round(stock_solution['total_droplets'] * self.metadata['droplet_volume'],2)

    def get_experiment_dataframe(self):
        """Return the experiment DataFrame."""
        return self.experiment_df


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.model = ExperimentModel()
        self.initUI()

    def initUI(self):

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)

        self.setWindowTitle("Experiment Designer")
        self.setGeometry(100, 100, 300, 300)

        self.design_button = QPushButton("Design Experiment", self)
        self.design_button.clicked.connect(self.open_experiment_design_dialog)

        self.save_button = QPushButton("Save Experiment Design", self)
        self.save_button.clicked.connect(self.save_experiment_design)
        self.save_button.setGeometry(10, 50, 180, 40)

        self.load_button = QPushButton("Load Experiment Design", self)
        self.load_button.clicked.connect(self.load_experiment_design)
        self.load_button.setGeometry(10, 100, 180, 40)

        self.layout.addWidget(self.design_button)
        self.layout.addWidget(self.save_button)
        self.layout.addWidget(self.load_button)

    def open_experiment_design_dialog(self):
        dialog = ExperimentDesignDialog(self, self.model)
        if dialog.exec():
            print("Experiment file generated and loaded.")

    def load_experiment(self, experiment):
        """Load the generated experiment into the main application."""
        print(f"Loaded experiment with {len(experiment)} reactions.")
        for reaction in experiment:
            print(reaction)

    def save_experiment_design(self):
        """Save the current experiment design to a file."""
        filename, _ = QFileDialog.getSaveFileName(self, "Save Experiment Design", "", "JSON Files (*.json)")
        if filename:
            self.model.save_experiment(filename)

    def load_experiment_design(self):
        """Load an experiment design from a file."""
        filename, _ = QFileDialog.getOpenFileName(self, "Load Experiment Design", "", "JSON Files (*.json)")
        if filename:
            self.model.load_experiment(filename)
            self.open_experiment_design_dialog()



if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()