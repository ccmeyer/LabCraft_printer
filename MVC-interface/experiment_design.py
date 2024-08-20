from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, 
    QPushButton, QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, 
    QAbstractItemView, QMessageBox, QMainWindow, QFileDialog, QApplication,
    QSplitter
)
from PySide6.QtCore import Qt
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
        self.setFixedSize(1500, 600)

        # Main layout with a splitter to separate reagent table and stock solutions table
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
        self.stock_table = QTableWidget(0, 3, self)
        self.stock_table.setHorizontalHeaderLabels([
            "Reagent Name", "Concentration", "Total Droplets"
        ])
        self.stock_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.stock_table.setFixedWidth(300)

        self.left_layout = QVBoxLayout()
        self.left_layout.addWidget(self.reagent_table)
        self.bottom_layout = QHBoxLayout()

        self.right_layout = QVBoxLayout()
        self.right_layout.addWidget(self.stock_table)

        # Label and spin box for total reactions and replicates
        self.info_layout = QVBoxLayout()
        self.total_reactions_label = QLabel("Total Reactions: 0", self)
        self.info_layout.addWidget(self.total_reactions_label)

        self.replica_label = QLabel("Replicates:", self)
        self.replicate_spinbox = QSpinBox(self)
        self.replicate_spinbox.setMinimum(1)
        self.replicate_spinbox.setValue(self.model.metadata.get("replicates", 1))
        self.replicate_spinbox.valueChanged.connect(self.update_total_reactions)
        self.info_layout.addWidget(self.replica_label)
        self.info_layout.addWidget(self.replicate_spinbox)

        self.total_droplets_label = QLabel("Total Droplets Available:", self)
        self.total_droplets_spinbox = QSpinBox(self)
        self.total_droplets_spinbox.setMinimum(1)
        self.total_droplets_spinbox.setMaximum(100)
        self.total_droplets_spinbox.setValue(self.model.metadata.get("max_droplets", 20))
        self.total_droplets_spinbox.valueChanged.connect(self.update_preview)
        self.info_layout.addWidget(self.total_droplets_label)
        self.info_layout.addWidget(self.total_droplets_spinbox)

        self.total_droplets_used_label = QLabel("Total Droplets Used: 0", self)
        self.info_layout.addWidget(self.total_droplets_used_label)
        
        # Button to add a new reagent
        self.button_layout = QVBoxLayout()
        self.add_reagent_button = QPushButton("Add Reagent")
        self.add_reagent_button.clicked.connect(self.add_reagent)
        self.button_layout.addWidget(self.add_reagent_button)

        # Button to optimize stock solutions
        self.optimize_button = QPushButton("Optimize Stock Solutions")
        self.optimize_button.clicked.connect(self.optimize_stock_solutions)
        self.button_layout.addWidget(self.optimize_button)
        
        # Button to generate the experiment
        self.generate_experiment_button = QPushButton("Generate Experiment")
        self.generate_experiment_button.clicked.connect(self.generate_experiment)
        self.button_layout.addWidget(self.generate_experiment_button)

        self.bottom_layout.addLayout(self.info_layout)
        self.bottom_layout.addLayout(self.button_layout)
        self.left_layout.addLayout(self.bottom_layout)

        self.layout.addLayout(self.left_layout)
        self.layout.addLayout(self.right_layout)        

        self.populate_table_from_model()

    def add_reagent(self, name="", min_conc=0.0, max_conc=1.0, steps=2, mode="Linear", manual_input="", max_droplets=10, stock_solutions=""):
        """Add a new reagent row to the table."""
        row_position = self.reagent_table.rowCount()
        self.reagent_table.insertRow(row_position)

        # Add cells for reagent name, min/max concentrations, steps, and mode
        reagent_name_item = QTableWidgetItem(name)
        self.reagent_table.setItem(row_position, 0, reagent_name_item)

        min_conc_item = QDoubleSpinBox()
        min_conc_item.setMinimum(0.0)
        min_conc_item.setValue(min_conc)
        min_conc_item.valueChanged.connect(lambda: self.update_preview(row_position))
        self.reagent_table.setCellWidget(row_position, 1, min_conc_item)

        max_conc_item = QDoubleSpinBox()
        max_conc_item.setMinimum(0.0)
        max_conc_item.setMaximum(1000.0)
        max_conc_item.setValue(max_conc)
        max_conc_item.valueChanged.connect(lambda: self.update_preview(row_position))
        self.reagent_table.setCellWidget(row_position, 2, max_conc_item)

        steps_item = QSpinBox()
        steps_item.setMinimum(2)
        steps_item.setValue(steps)
        steps_item.valueChanged.connect(lambda: self.update_preview(row_position))
        self.reagent_table.setCellWidget(row_position, 3, steps_item)

        mode_item = QComboBox()
        mode_item.addItems(["Linear", "Quadratic", "Logarithmic", "Manual"])
        mode_item.setCurrentText(mode)
        mode_item.currentIndexChanged.connect(lambda: self.toggle_manual_entry(row_position))
        mode_item.currentIndexChanged.connect(lambda: self.update_preview(row_position))
        self.reagent_table.setCellWidget(row_position, 4, mode_item)

        # Manual concentration input (always visible, but inactive unless in "Manual" mode)
        manual_conc_item = QLineEdit(manual_input)
        manual_conc_item.setPlaceholderText("e.g., 0.1, 0.5, 1.0")
        manual_conc_item.setEnabled(mode == "Manual")  # Activate based on mode
        manual_conc_item.textChanged.connect(lambda: self.update_preview(row_position))
        self.reagent_table.setCellWidget(row_position, 5, manual_conc_item)

        max_droplets_item = QSpinBox()
        max_droplets_item.setMinimum(1)
        max_droplets_item.setValue(max_droplets)
        max_droplets_item.valueChanged.connect(lambda: self.update_preview(row_position))
        self.reagent_table.setCellWidget(row_position, 6, max_droplets_item)

        # Concentrations preview cell
        preview_item = QTableWidgetItem()
        preview_item.setTextAlignment(Qt.AlignCenter)
        self.reagent_table.setItem(row_position, 7, preview_item)

        # Stock solutions preview cell
        stock_solutions_item = QTableWidgetItem(stock_solutions)
        stock_solutions_item.setTextAlignment(Qt.AlignCenter)
        self.reagent_table.setItem(row_position, 8, stock_solutions_item)

        # Delete button
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(lambda: self.delete_reagent(row_position))
        self.reagent_table.setCellWidget(row_position, 9, delete_button)
        
        self.update_preview(row_position)

    def delete_reagent(self, row):
        """Delete a reagent row and remove it from the model."""
        reagent_name = self.reagent_table.item(row, 0).text()
        if reagent_name in self.model.reagents:
            del self.model.reagents[reagent_name]

        self.reagent_table.removeRow(row)
        self.update_total_reactions()
        self.update_stock_table()

    def populate_table_from_model(self):
        """Populate the reagent table based on the data in the model."""
        for reagent_name, data in self.model.reagents.items():
            self.add_reagent(
                name=reagent_name,
                min_conc=data['min_conc'],
                max_conc=data['max_conc'],
                steps=data['steps'],
                mode=data['mode'],
                manual_input=", ".join(map(str, data['concentrations'])) if data['mode'] == "Manual" else "",
                max_droplets=data['max_droplets'],
                stock_solutions=", ".join(map(str, data['stock_solutions']))
            )

    def toggle_manual_entry(self, row):
        """Enable or disable the manual entry field based on mode selection."""
        mode = self.reagent_table.cellWidget(row, 4).currentText()
        manual_conc_item = self.reagent_table.cellWidget(row, 5)
        manual_conc_item.setEnabled(mode == "Manual")
        self.update_preview(row)

    def update_preview(self, row=None):
        """Update the concentration preview based on input values."""
        total_droplets_used = 0
        for row in range(self.reagent_table.rowCount()):
            min_conc = self.reagent_table.cellWidget(row, 1).value()
            max_conc = self.reagent_table.cellWidget(row, 2).value()
            steps = self.reagent_table.cellWidget(row, 3).value()
            mode = self.reagent_table.cellWidget(row, 4).currentText()
            manual_conc = self.reagent_table.cellWidget(row, 5).text()

            concentrations = []

            if mode == "Manual":
                try:
                    concentrations = [round(float(c.strip()), 2) for c in manual_conc.split(',') if c.strip()]
                except ValueError:
                    concentrations = []
            else:
                concentrations = self.generate_concentrations(min_conc, max_conc, steps, mode)

            preview_text = ", ".join(map(str, concentrations))
            preview_item = self.reagent_table.item(row, 7)
            preview_item.setText(preview_text)
            preview_item.setTextAlignment(Qt.AlignCenter)

            # Update stock solutions
            max_droplets = self.reagent_table.cellWidget(row, 6).value()
            stock_solutions, achievable_concentrations = find_minimal_stock_solutions_backtracking(concentrations, max_droplets)
            stock_solution_text = ", ".join(map(str, stock_solutions))
            stock_solution_item = self.reagent_table.item(row, 8)
            stock_solution_item.setText(stock_solution_text)
            stock_solution_item.setTextAlignment(Qt.AlignCenter)

            # Calculate the maximum number of droplets used for this reagent
            if achievable_concentrations:
                droplet_counts = [len(achievable_concentrations[tc]) for tc in concentrations if tc in achievable_concentrations]
                if droplet_counts:
                    max_droplets_for_reagent = max(droplet_counts)
                else:
                    max_droplets_for_reagent = 0  # Set a default value if the list is empty
                total_droplets_used += max_droplets_for_reagent

        self.total_droplets_used_label.setText(f"Total Droplets Used: {total_droplets_used}")
        if total_droplets_used > self.total_droplets_spinbox.value():
            self.total_droplets_used_label.setStyleSheet("color: red;")
        else:
            self.total_droplets_used_label.setStyleSheet("color: white;")
        
        self.update_total_reactions()  # Update total reactions whenever the preview changes

    def optimize_stock_solutions(self):
        """Optimize the stock solutions using multi-reagent optimization."""
        reagents_data = []
        for row in range(self.reagent_table.rowCount()):
            preview_text = self.reagent_table.item(row, 7).text()
            if preview_text:
                concentrations = [float(c) for c in preview_text.split(", ")]
                max_droplets = self.reagent_table.cellWidget(row, 6).value()
                if max_droplets < 10:
                    max_droplets = 10  # Ensure a minimum of 10 droplets
                reagents_data.append((concentrations, max_droplets))

        max_total_droplets = self.total_droplets_spinbox.value()
        optimized_solutions, max_droplets_per_reagent = multi_reagent_optimization(reagents_data, max_total_droplets)

        # Update the table with the optimized stock solutions and droplet counts
        for row, (optimized_stock, max_droplets) in enumerate(zip(optimized_solutions, max_droplets_per_reagent)):
            self.reagent_table.cellWidget(row, 6).setValue(max_droplets)
            stock_solution_item = self.reagent_table.item(row, 8)
            stock_solution_text = ", ".join(map(str, optimized_stock))
            stock_solution_item.setText(stock_solution_text)
            stock_solution_item.setTextAlignment(Qt.AlignCenter)

        self.update_preview()  # Recalculate the total droplets used

    def generate_concentrations(self, min_conc, max_conc, steps, mode):
        """Generate concentration values based on the mode."""
        if min_conc >= max_conc:
            return []

        if mode == "Linear":
            return [round(x, 2) for x in np.linspace(min_conc, max_conc, steps).tolist()]
        elif mode == "Quadratic":
            return [round(x, 2) for x in (np.linspace(np.sqrt(min_conc), np.sqrt(max_conc), steps)**2).tolist()]
        elif mode == "Logarithmic":
            return [round(x, 2) for x in np.logspace(np.log10(min_conc), np.log10(max_conc), steps).tolist()]
        else:
            return []

    def update_total_reactions(self):
        """Update the total number of reactions label."""
        total_reactions = 1
        for row in range(self.reagent_table.rowCount()):
            preview_text = self.reagent_table.item(row, 7).text()
            if preview_text:
                concentrations = preview_text.split(", ")
                total_reactions *= len(concentrations)
        
        total_reactions *= self.replicate_spinbox.value()
        self.total_reactions_label.setText(f"Total Reactions: {total_reactions}")
        self.model.metadata["max_droplets"] = self.total_droplets_spinbox.value()
        self.model.metadata["replicates"] = self.replicate_spinbox.value()
        self.update_stock_table()

    def update_stock_table(self):
        """Update the stock solutions table based on the current experiment setup."""
        stock_data = {}

        # Calculate the total droplets for each stock solution
        for row in range(self.reagent_table.rowCount()):
            reagent_name = self.reagent_table.item(row, 0).text()
            stock_solutions = self.reagent_table.item(row, 8).text().split(", ")
            concentrations = self.reagent_table.item(row, 7).text().split(", ")
            max_droplets = self.reagent_table.cellWidget(row, 6).value()

            for stock in stock_solutions:
                try:
                    stock = float(stock)
                    if stock == 0:
                        continue  # Skip if stock is zero to prevent division by zero
                    total_droplets_for_stock = sum(int(float(c) / stock) for c in concentrations if float(c) % stock == 0)
                    if (reagent_name, stock) not in stock_data:
                        stock_data[(reagent_name, stock)] = 0
                    stock_data[(reagent_name, stock)] += total_droplets_for_stock
                except ValueError:
                    continue  # Skip invalid stock values

        # Populate the stock table
        self.stock_table.setRowCount(0)  # Clear existing rows
        for (reagent_name, stock), total_droplets in stock_data.items():
            row_position = self.stock_table.rowCount()
            self.stock_table.insertRow(row_position)
            self.stock_table.setItem(row_position, 0, QTableWidgetItem(reagent_name))
            self.stock_table.setItem(row_position, 1, QTableWidgetItem(str(stock)))
            self.stock_table.setItem(row_position, 2, QTableWidgetItem(str(total_droplets)))


    def generate_experiment(self):
        """Generate the experiment based on the table data."""
        self.model.reagents = {}  # Reset reagents in model
        self.model.metadata["replicates"] = self.replicate_spinbox.value()
        self.model.metadata["max_droplets"] = self.total_droplets_spinbox.value()

        for row in range(self.reagent_table.rowCount()):
            reagent_name = self.reagent_table.item(row, 0).text()
            concentrations = self.reagent_table.item(row, 8).text().split(', ')
            concentrations = list(map(float, concentrations))
            mode = self.reagent_table.cellWidget(row, 4).currentText()
            min_conc = self.reagent_table.cellWidget(row, 1).value()
            max_conc = self.reagent_table.cellWidget(row, 2).value()
            steps = self.reagent_table.cellWidget(row, 3).value()
            max_droplets = self.reagent_table.cellWidget(row, 6).value()
            stock_solutions = list(map(float, self.reagent_table.item(row, 7).text().split(", ")))

            if reagent_name and concentrations:
                self.model.add_reagent(
                    name=reagent_name, 
                    concentrations=concentrations,
                    mode=mode,
                    min_conc=min_conc,
                    max_conc=max_conc,
                    steps=steps,
                    max_droplets=max_droplets,
                    stock_solutions=stock_solutions
                )

        if self.model.reagents:
            experiment = self.model.generate_experiment()
            self.main_window.load_experiment(experiment)
            self.accept()
        else:
            QMessageBox.warning(self, "Input Error", "Please add at least one reagent.")

class ExperimentModel:
    def __init__(self):
        self.reagents = {}
        self.metadata = {
            "replicates": 1,
            "max_droplets": 20,
        }

    def add_reagent(self, name, concentrations, mode, min_conc, max_conc, steps, max_droplets, stock_solutions):
        self.reagents[name] = {
            "concentrations": concentrations,
            "mode": mode,
            "min_conc": min_conc,
            "max_conc": max_conc,
            "steps": steps,
            "max_droplets": max_droplets,
            "stock_solutions": stock_solutions
        }

    def generate_experiment(self):
        from itertools import product
        experiment = []
        reagent_names = list(self.reagents.keys())
        concentration_combinations = product(*[self.reagents[name]["concentrations"] for name in reagent_names])
        for combo in concentration_combinations:
            experiment.append(dict(zip(reagent_names, combo)))
        return experiment

    def save_experiment(self, file_path):
        """Save the experiment design to a file."""
        data = {
            "metadata": self.metadata,
            "reagents": self.reagents
        }
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4)

    def load_experiment(self, file_path):
        """Load the experiment design from a file."""
        with open(file_path, 'r') as f:
            data = json.load(f)
            self.metadata = data.get("metadata", {})
            self.reagents = data.get("reagents", {})


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.model = ExperimentModel()
        self.initUI()

    def initUI(self):
        self.setWindowTitle("Experiment Designer")
        self.setGeometry(100, 100, 800, 600)

        self.design_button = QPushButton("Design Experiment", self)
        self.design_button.clicked.connect(self.open_experiment_design_dialog)

        self.save_button = QPushButton("Save Experiment Design", self)
        self.save_button.clicked.connect(self.save_experiment_design)
        self.save_button.setGeometry(10, 50, 180, 40)

        self.load_button = QPushButton("Load Experiment Design", self)
        self.load_button.clicked.connect(self.load_experiment_design)
        self.load_button.setGeometry(10, 100, 180, 40)

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