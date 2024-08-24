import pandas as pd
import numpy as np
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer
import json
import heapq
import os
import csv
import cv2
import itertools
from itertools import combinations_with_replacement


# class PressureCalibrationModel(QObject):
#     calibration_data_updated = Signal()  # Signal to notify when the calibration data is updated
#     def __init__(self):
#         super().__init__()
#         self.calibration_data = {}
#         self.calibration_data['positions'] = {}
#         self.calibration_data['calibrations'] = {}



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

    for combination in itertools.product(*reagent_solutions):
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

class ExperimentModel(QObject):
    data_updated = Signal(int)  # Signal to notify when reagent data is updated, passing the row index
    stock_updated = Signal()
    experiment_generated = Signal(int,int)  # Signal to notify when the experiment is generated, passing the total number of reactions
    update_max_droplets_signal = Signal(int) # Signal to notify when the max droplets is updated, passing the row index
    
    def __init__(self):
        super().__init__()
        self.reagents = []
        self.metadata = {
            "replicates": 1,
            "max_droplets": 20,
            'droplet_volume': 0.03,
            'fill_reagent': 'Water'
        }
        self.stock_solutions = []
        self.experiment_df = pd.DataFrame()
        self.complete_lookup_table = pd.DataFrame()
        self.all_droplet_df = pd.DataFrame()

        self.add_new_stock_solutions_for_reagent(self.metadata['fill_reagent'],[1.0])

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
        self.remove_stock_solutions_for_unused_reagents()
        self.generate_experiment()

    def update_metadata(self, replicates, max_droplets):
        self.metadata["replicates"] = replicates
        self.metadata["max_droplets"] = max_droplets
        self.generate_experiment()

    def update_fill_reagent_name(self,fill_reagent):
        self.stock_solutions = [stock for stock in self.stock_solutions if stock['reagent_name'] != self.metadata['fill_reagent']]
        self.metadata['fill_reagent'] = fill_reagent
        self.add_new_stock_solutions_for_reagent(fill_reagent,[1.0])
        self.generate_experiment()

    def calculate_concentrations(self, index,calc_experiment=True):
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
            
            if steps == 1:
                reagent["concentrations"] = [round(max_conc, 2)]
                print(f'Conc for {index} has steps {steps} and {reagent["concentrations"]}')
            elif mode == "Linear":
                reagent["concentrations"] = [round(x, 2) for x in np.linspace(min_conc, max_conc, steps).tolist()]
            elif mode == "Quadratic":
                reagent["concentrations"] = [round(x, 2) for x in (np.linspace(np.sqrt(min_conc), np.sqrt(max_conc), steps)**2).tolist()]
            elif mode == "Logarithmic":
                reagent["concentrations"] = [round(x, 2) for x in np.logspace(np.log10(min_conc), np.log10(max_conc), steps).tolist()]
        
        self.calculate_stock_solutions(index)
        
        # Emit signal to update the view
        self.data_updated.emit(index)
        if calc_experiment:
            self.generate_experiment()

    def calculate_all_concentrations(self):
        for i in range(len(self.reagents)):
            self.calculate_concentrations(i)

    def calculate_stock_solutions(self, index):
        self.remove_stock_solutions_for_unused_reagents()
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

    def remove_stock_solutions_for_unused_reagents(self):
        used_reagents = [reagent['name'] for reagent in self.reagents]
        used_reagents.append(self.metadata['fill_reagent'])
        self.stock_solutions = [stock for stock in self.stock_solutions if stock['reagent_name'] in used_reagents]
        # Update the stock solutions in the experiment DataFrame
        if not self.all_droplet_df.empty:
            self.all_droplet_df = self.all_droplet_df[self.all_droplet_df['reagent_name'].isin(used_reagents)].copy()
        # Update the stock solutions in the lookup table
        if not self.complete_lookup_table.empty:
            self.complete_lookup_table = self.complete_lookup_table[self.complete_lookup_table['reagent_name'].isin(used_reagents)].copy()


    def create_lookup_table(self,reagent_name,achievable_concentrations, stock_solutions):
        # Initialize a DataFrame with target concentrations as index and stock solutions as columns
        if achievable_concentrations == None:
            return pd.DataFrame()
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
        max_droplet_df = self.all_droplet_df[['reaction_id','unique_id','replicate','droplet_count']].groupby(['reaction_id','unique_id','replicate']).sum().reset_index()
        fill_reagent_df = max_droplet_df.copy()
        fill_reagent_df['reagent_name'] = self.metadata['fill_reagent']
        fill_reagent_df['stock_solution'] = 1
        fill_reagent_df['droplet_count'] = self.metadata['max_droplets'] - fill_reagent_df['droplet_count']
        fill_reagent_df['target_concentration'] = 0
        self.all_droplet_df = pd.concat([self.all_droplet_df,fill_reagent_df],ignore_index=True)
        
        droplet_count = max_droplet_df['droplet_count'].max()
        self.add_total_droplet_count_to_stock()
        self.stock_updated.emit()

        # Emit signal to notify that the experiment has been generated
        self.experiment_generated.emit(self.get_number_of_reactions(),droplet_count)

    def get_number_of_reactions(self):
        if self.all_droplet_df.empty:
            return 0
        return len(self.all_droplet_df['unique_id'].unique())
    
    def add_total_droplet_count_to_stock(self):
        for stock_solution in self.stock_solutions:
            print(f'Stock solution: {stock_solution}')
            total_droplets = self.all_droplet_df[(self.all_droplet_df['reagent_name'] == stock_solution['reagent_name']) & (self.all_droplet_df['stock_solution'] == stock_solution['concentration'])]['droplet_count'].sum()
            print(f'Total droplets: {total_droplets}')
            stock_solution['total_droplets'] = total_droplets
            stock_solution['total_volume'] = round(stock_solution['total_droplets'] * self.metadata['droplet_volume'],2)

    def optimize_stock_solutions(self):
        reagents_data = []
        for reagent in self.reagents:
            max_reag_droplets = reagent['max_droplets']
            if max_reag_droplets < 10:
                max_reag_droplets = 10  # Ensure a minimum of 10 droplets
            reagents_data.append((reagent['concentrations'], max_reag_droplets))

        max_total_droplets = self.metadata['max_droplets']
        optimized_solutions, max_droplets_per_reagent = multi_reagent_optimization(reagents_data, max_total_droplets)
        print(f"Optimized stock solutions: {optimized_solutions}")
        print(f"Max droplets per reagent: {max_droplets_per_reagent}")
        for i in range(len(max_droplets_per_reagent)):
            self.reagents[i]['max_droplets'] = max_droplets_per_reagent[i]

            self.update_max_droplets_signal.emit(i)
    
    def get_experiment_dataframe(self):
        """Return the experiment DataFrame."""
        return self.experiment_df
    
    def save_experiment(self, filename):
        """Save all information required to repopulate the model to a JSON file."""
        data_to_save = {
            "reagents": self.reagents,
            "metadata": self.metadata,
        }
        with open(filename, 'w') as file:
            json.dump(data_to_save, file, indent=4)
        print(f"Experiment data saved to {filename}")
    
    def load_experiment(self, filename):
        """Load all information required to repopulate the model from a JSON file."""
        with open(filename, 'r') as file:
            loaded_data = json.load(file)

        # Clear current data to avoid duplications or issues
        self.reagents = []
        self.metadata = {
            "replicates": 1,
            "max_droplets": 20,
            'droplet_volume': 0.03,
            'fill_reagent': 'Water'
        }
        self.stock_solutions = []
        self.experiment_df = pd.DataFrame()
        self.complete_lookup_table = pd.DataFrame()
        self.all_droplet_df = pd.DataFrame()

        # Load data from the JSON file
        self.reagents = loaded_data["reagents"]
        self.metadata = loaded_data["metadata"]

        # Recalculate any necessary information and emit signals to update the view
        for i in range(len(self.reagents)):

            self.data_updated.emit(i)
            self.calculate_concentrations(i,calc_experiment=True)
            print(f'finished conc for {i}\n{self.experiment_df}')

        print(f"Experiment data loaded from {filename}")
        


class StockSolution(QObject):
    '''
    Represents a specific instance of a reagent at a certain concentration
    Each stock solution can be assigned to a printer head.
    '''
    def __init__(self, stock_id, reagent_name,concentration,required_volume=None):
        super().__init__()
        self.stock_id = stock_id
        self.reagent_name = reagent_name
        self.concentration = concentration
        self.required_volume = required_volume

    def get_stock_id(self):
        return self.stock_id
    
    def get_reagent_name(self):
        return self.reagent_name
    
    def get_stock_concentration(self):
        return self.concentration
    
    def get_stock_name(self):
        return f"{self.reagent_name} - {self.concentration}M"

class Reagent(QObject):
    '''
    Represents an amount of a stock solution that should be added to a specific reaction
    A reaction composition is comprised of one or more Reagents that when mixed together creates the target composition
    Contains the stock solution, the number of droplets needed and tracks how much of the reagent has been added
    '''
    def __init__(self, stock_solution, droplets):
        super().__init__()
        self.stock_solution = stock_solution
        self.target_droplets = droplets     # Number of droplets to be added to the reaction
        self.added_droplets = 0             # Number of droplets that have already been added
        self.completed = False              # States whether all required droplets have been added

    def get_target_droplets(self):
        return self.target_droplets
    
    def get_remaining_droplets(self):
        return self.target_droplets - self.added_droplets
    
    def add_droplets(self, droplets):
        self.added_droplets += droplets

    def is_complete(self):
        if self.added_droplets == self.target_droplets:
            self.completed = True
            return True
        else:
            self.completed = False
            return False
    
class StockSolutionManager(QObject):
    '''
    Manages all the stock solutions that are included in the experiment
    When a new stock solution is to be added, it creates a new instance of the StockSolution class and assigns it a unique id
    This class is mostly used to coordinate which stock solutions go to which printer head
    '''
    def __init__(self):
        super().__init__()
        self.stock_solutions = {}

    def add_all_stock_solutions(self,stock_solution_list):
        for stock_id in stock_solution_list:
            reagent_name, concentration_str = stock_id.split('_')
            concentration = float(concentration_str[:])  # Remove 'M' and convert to float
            if stock_id in self.stock_solutions.keys():
                print('Duplicate stock solution found:',stock_id)
            else:
                self.stock_solutions.update({stock_id:StockSolution(stock_id,reagent_name,concentration)})

    def add_stock_solution(self, reagent_name, concentration,required_volume=None):
        # Generates a unique identifier for the reagent/concentration pair
        stock_id = '_'.join([reagent_name,str(concentration)])
        self.stock_solutions.update({stock_id:StockSolution(stock_id,reagent_name,concentration,required_volume=required_volume)})

    def get_stock_solution(self, reagent_name, concentration):
        """Retrieve a reagent-concentration pair."""
        unique_id = '_'.join([reagent_name,str(float(concentration))])
        print('Getting stock solution:',unique_id)
        return self.stock_solutions.get(unique_id)
        
    def get_stock_by_id(self, stock_id):
        return self.stock_solutions[stock_id]
    
    def get_all_stock_solutions(self):
        return self.stock_solutions.values()

    def get_stock_solution_names(self):
        return list(self.stock_solutions.keys())
    
    def get_formatted_from_stock_id(self,stock_id):
        stock = self.get_stock_by_id(stock_id)
        return stock.get_stock_name()

    def get_stock_solution_names_formated(self):
        return [stock.get_stock_name() for stock_id,stock in self.stock_solutions.items()]
    
    def get_stock_id_from_formatted(self,formatted_name):
        for stock_id,stock in self.stock_solutions.items():
            if formatted_name == stock.get_stock_name():
                return stock_id
        return None
    
    def clear_all_stock_solutions(self):
        self.stock_solutions = {}

class ReactionComposition(QObject):
    '''
    Represents a reaction composition which will be assigned to a well
    It is comprised of multiple Reagent objects which represent how many droplets of each stock solution need to be added to the reaction
    Each reaction composition should only have one Reagent instance per stock solution
    '''
    def __init__(self, unique_id):
        super().__init__()
        self.unique_id = unique_id
        self.reagents = {}  # Dictionary to hold Reagent objects with the required number of droplets
    
    def add_reagent(self, stock_solution,droplets):
        """
        Create an instance of the Reagent class using a StockSolution instance and the target number of droplets.
        Reagents are stored in a dictionary using the stock id to reference them
        """
        self.reagents.update({stock_solution.stock_id:Reagent(stock_solution,droplets)})
    
    def get_all_reagents(self):
        """Get all reagents and their concentrations in this reaction."""
        return self.reagents
    
    def get_target_droplets_for_stock(self,stock_id):
        return self.reagents[stock_id].get_target_droplets()
    
    def get_remaining_droplets_for_stock(self,stock_id):
        return self.reagents[stock_id].get_remaining_droplets()
    
    def record_stock_print(self,stock_id,droplets):
        self.reagents[stock_id].add_droplets(droplets)

    def check_stock_complete(self,stock_id):
        return self.reagents[stock_id].is_complete()
    
    def check_all_complete(self):
        for reagent in self.reagents.values():
            if not reagent.is_complete():
                return False
        else:
            return True
        
    def reset_all_reagents(self):
        for reagent in self.reagents.values():
            reagent.added_droplets = 0
            reagent.completed = False

    def reset_reagent_by_id(self,stock_id):
        self.reagents[stock_id].added_droplets = 0
        self.reagents[stock_id].completed = False

    def get_reagent_by_id(self,stock_id):
        return self.reagents[stock_id]
    


class ReactionCollection(QObject):
    '''
    Represents the collection of all reactions that make up an experiment.
    The reaction collection contains all the specific reaction composition objects.
    It also allows for general information to be extracted from the pool of reactions.
    '''
    def __init__(self):
        super().__init__()
        self.reactions = {}  # Dictionary to hold ReactionComposition objects by name

    def add_reaction(self, reaction):
        """Add a unique reaction to the collection."""
        if not isinstance(reaction, ReactionComposition):
            raise ValueError("Must add a ReactionComposition object.")
        if reaction.unique_id not in self.reactions:
            self.reactions[reaction.unique_id] = reaction
        else:
            raise ValueError(f"Reaction '{reaction.name}' already exists in the collection.")

    def remove_reaction(self, name):
        """Remove a reaction from the collection by its name."""
        if name in self.reactions:
            del self.reactions[name]
        else:
            raise ValueError(f"Reaction '{name}' not found in the collection.")

    def is_empty(self):
        """Check if the collection is empty."""
        return len(self.reactions) == 0

    def get_reaction(self, name):
        """Get a reaction by its name."""
        return self.reactions.get(name, None)

    def get_all_reactions(self):
        """Get all reactions in the collection."""
        return list(self.reactions.values())
    
    def get_max_droplets(self, stock_id):
        """Get the maximum concentration of a specific reagent across all reactions."""
        max_droplets = None
        for reaction in self.get_all_reactions():
            droplets = reaction.get_target_droplets_for_stock(stock_id)
            if droplets is not None:
                if max_droplets is None or droplets > max_droplets:
                    max_droplets = droplets
        return max_droplets

    def clear_all_reactions(self):
        """Clear all reactions from the collection."""
        self.reactions = {}
    
class Well(QObject):
    '''
    Represents a single well in a well plate.
    The object is instantiated with an identifier such as "A1" or "B2".
    Each well can only be assigned a single reaction composition.
    '''
    state_changed = Signal(str)  # Signal to notify when the state of the well changes, sending the well ID
    def __init__(self, well_id):
        super().__init__()
        self.well_id = well_id  # Unique identifier for the well (e.g., "A1", "B2")
        self.row = well_id[0]  # Row of the well (e.g., "A", "B")
        self.row_num = ord(self.row) - 65  # Row number (0-indexed, A=0, B=1)
        self.col = int(well_id[1:])  # Column of the well (e.g., 1, 2)
        self.assigned_reaction = None  # The reaction assigned to this well
        self.coordinates = None  # The x, y, and z coordinates of the well on the plate

    def assign_reaction(self, reaction):
        """Assign a reaction to the well."""
        if not isinstance(reaction, ReactionComposition):
            raise ValueError("Must assign a ReactionComposition object.")
        self.assigned_reaction = reaction

    def assign_coordinates(self, x, y,z):
        """Assign coordinates to the well."""
        self.coordinates = {'X':x, 'Y':y, 'Z':z}

    def get_coordinates(self):
        """Get the coordinates of the well."""
        return self.coordinates

    def get_target_droplets(self,stock_id):
        return self.assigned_reaction.get_target_droplets_for_stock(stock_id)

    def get_remaining_droplets(self,stock_id):
        return self.assigned_reaction.get_remaining_droplets_for_stock(stock_id)
    
    def record_stock_print(self,stock_id,droplets):
        self.assigned_reaction.record_stock_print(stock_id,droplets)
        print('emitting state changed',self.well_id)
        self.state_changed.emit(self.well_id)

    def check_stock_complete(self,stock_id):
        return self.assigned_reaction.check_stock_complete(stock_id)

    def check_all_complete(self):
        return self.assign_reaction.check_all_complete()

class WellPlate(QObject):
    well_state_changed_signal = Signal(str)  # Signal to notify when the state of a well changes, sending the well ID
    clear_all_wells_signal = Signal()  # Signal to notify when all wells are cleared
    plate_format_changed_signal = Signal()  # Signal to notify when the well plate is updated

    def __init__(self, all_plate_data):
        super().__init__()
        self.all_plate_data = all_plate_data
        self.current_plate_data = self.get_default_plate_data()
        self.calibrations = self.current_plate_data['calibrations']
        self.rows = self.current_plate_data['rows']
        self.cols = self.current_plate_data['columns']
        self.wells = self.create_wells()
        self.excluded_wells = set()

        self.calibration_applied = False
        self.temp_calibration_data = {}
    
        self.apply_calibration_data()

    def check_calibration_applied(self):
        return self.calibration_applied
    
    def get_current_plate_name(self):
        return self.current_plate_data['name']
    
    def get_all_current_plate_calibrations(self):
        return self.calibrations
    
    def get_calibration_by_name(self, name):
        return self.calibrations.get(name, None)
    
    def get_temp_calibration_by_name(self, name):
        return self.temp_calibration_data.get(name, None)
    
    def set_calibration_position(self, position_name, coordinates):
        """Set a temporary calibration position."""
        self.temp_calibration_data[position_name] = coordinates
    
    def update_calibration_data(self):
        """Run the full update of all calibration data."""
        self.store_calibrations()
        self.save_calibrations_to_file()
        self.apply_calibration_data()

    def get_plate_data_by_name(self, plate_name):
        for plate_data in self.all_plate_data:
            if plate_data['name'] == plate_name:
                return plate_data
        raise ValueError(f"Plate format '{plate_name}' not found.")        

    def store_calibrations(self):
        """Save the temporary calibration data to the main calibration data."""
        plate_name = self.get_current_plate_name()
        for plate_data in self.all_plate_data:
            print(plate_data['name'])
            if plate_data['name'] == plate_name:
                plate_data['calibrations'] = self.temp_calibration_data.copy()
                self.calibrations = self.temp_calibration_data.copy()
                # Clear the temporary data after saving
                self.temp_calibration_data.clear()
                return
        raise ValueError(f"Plate format '{plate_name}' not found.")

    def save_calibrations_to_file(self, file_path='.\\MVC-interface\\Presets\\Plates.json'):
        """Save the current calibration data to a JSON file."""
        try:
            with open(file_path, 'w') as file:
                json.dump(self.all_plate_data, file, indent=4)
            print(f"Calibration data saved to {file_path}")
        except Exception as e:
            print(f"Error saving calibration data to file: {e}")

    def discard_temp_calibrations(self):
        """Discard the temporary calibration data."""
        self.temp_calibration_data.clear()

    def get_default_plate_data(self):
        """Get the data for the plate set to default"""
        for plate_data in self.all_plate_data:
            if plate_data['default']:
                return plate_data

    def get_all_plate_names(self):
        return [plate_data['name'] for plate_data in self.all_plate_data]
    
    def get_current_plate_name(self):
        return self.current_plate_data['name']
    
    def create_wells(self):
        """Create wells based on the plate format."""
        wells = {}
        for row in range(self.rows):
            for col in range(self.cols):
                well_id = f"{chr(row + 65)}{col + 1}"
                well = Well(well_id)
                well.state_changed.connect(self.well_state_changed)
                wells[well_id] = well
        self.plate_format_changed_signal.emit()
        return wells
    
    def set_plate_format(self, plate_name):
        """Set the plate format based on the selected name."""
        for plate_data in self.all_plate_data:
            if plate_data['name'] == plate_name:
                self.current_plate_data = plate_data
                self.rows = plate_data['rows']
                self.cols = plate_data['columns']
                self.wells = self.create_wells()
                self.calibrations = plate_data['calibrations']
                self.calibration_applied = False
                self.apply_calibration_data()
                self.plate_format_changed_signal.emit()
                return
        raise ValueError(f"Plate format '{plate_name}' not found.")
    
    def get_plate_dimensions(self):
        return self.rows,self.cols
    
    def get_coords(self,coords):
        return np.array(list(coords.values()))
    
    def calculate_plate_matrix(self):
        """Calculate the transformation matrix for the plate."""
        self.corners = np.array([
            [self.get_coords(self.calibrations['top_left'])[0:2]],
            [self.get_coords(self.calibrations['top_right'])[0:2]],
            [self.get_coords(self.calibrations['bottom_right'])[0:2]],
            [self.get_coords(self.calibrations['bottom_left'])[0:2]]
        ], dtype = "float32")

        self.max_columns = self.cols - 1
        self.max_rows = self.rows - 1
        self.plate_width = self.max_columns * self.current_plate_data['spacing']
        self.plate_depth = self.max_rows * self.current_plate_data['spacing']

        self.plate_dimensions = np.array([
            [0, 0],
            [0, self.plate_width],
            [self.plate_depth, self.plate_width],
            [self.plate_depth, 0]
        ], dtype = "float32")

        self.generate_transformation_matrix()

        self.row_z_step = (self.calibrations['bottom_left']['Z'] - self.calibrations['top_left']['Z']) / (self.rows)
        self.col_z_step =  (self.calibrations['top_right']['Z'] - self.calibrations['top_left']['Z']) / (self.cols)

        well_coords_df = self.calculate_all_well_positions()
        return well_coords_df

    def generate_transformation_matrix(self):
        '''
        Performs a 4-point transformation of the coordinate plane using the
        experimentally derived plate corners. This takes the machine coordinates
        and finds the matrix required to convert them into the coordinate plane
        that matches the defined geometry of the plate. This matrix can then be
        reversed and used to take the positions where wells should be and
        convert them into the corresponding dobot coordinates.

        This transformation accounts for the deviations in the machine coordinate
        system but only applies to the X and Y dimensions.
        '''
        self.trans_matrix = cv2.getPerspectiveTransform(self.corners, self.plate_dimensions)
        self.inv_trans_matrix = np.linalg.pinv(self.trans_matrix)
    
    def correct_xy_coords(self,x,y):
        '''
        Uses the transformation matrix to correct the XY coordinates
        '''
        target = np.array([[x,y]], dtype = "float32")
        target_transformed = cv2.perspectiveTransform(np.array(target[None,:,:]), self.inv_trans_matrix)
        return target_transformed[0][0]

    def get_well_coords(self,row,column):
        '''
        Uses the well indices to determine the dobot coordinates of the well
        '''
        x,y = self.correct_xy_coords(row*self.current_plate_data['spacing'],column*self.current_plate_data['spacing'])
        z = self.calibrations['top_left']['Z'] + (row * self.row_z_step) + (column * self.col_z_step)
        x = int(round(x,0))
        y = int(round(y,0))
        z = int(round(z,0))
        return {'X':x, 'Y':y, 'Z':z}
    
    def calculate_all_well_positions(self):
        # Create an empty list for the well positions
        well_positions = []

        # Iterate over all the rows and columns of the plate
        for row in range(self.rows):
            for column in range(self.cols):
                # Calculate the corrected coordinates for the well
                coords = self.get_well_coords(row, column)

                # Add the well position to the list
                well_positions.append({
                    'row': row,
                    'column': column,
                    'X': coords['X'],
                    'Y': coords['Y'],
                    'Z': coords['Z']
                })

        # Create a DataFrame from the list
        well_positions_df = pd.DataFrame(well_positions)
        return well_positions_df
    
    def assign_well_coordinates(self, well_id, x, y,z):
        """Assign coordinates to a specific well."""
        well = self.wells.get(well_id)
        if well is not None:
            well.assign_coordinates(x,y,z)
        else:
            raise ValueError(f"Well '{well_id}' does not exist in the plate.")

    def assign_well_coordinates_by_row_col(self, row, col, x, y,z):
        """Assign coordinates to a well by its row and column."""
        well_id = f"{chr(row + 65)}{col + 1}"
        self.assign_well_coordinates(well_id, x, y,z)

    def assign_all_well_coordinates(self, well_coords_df):
        """Assign coordinates to all wells in the plate."""
        for i,row in well_coords_df.iterrows():
            well_id = f"{chr(row['row'] + 65)}{row['column'] + 1}"
            self.assign_well_coordinates(well_id, row['X'], row['Y'],row['Z'])

    def apply_calibration_data(self):
        if len(list(self.calibrations)) < 4:
            self.calibration_applied = False
            print(f"Calibration is incomplete. Need at least 4 calibration points, but only {len(list(self.calibrations))} provided.")
            return
        else:
            well_coords_df = self.calculate_plate_matrix()
            self.assign_all_well_coordinates(well_coords_df)
            self.calibration_applied = True

    def get_num_rows(self):
        """Get the number of rows in the plate."""
        return self.rows
    
    def get_num_cols(self):
        """Get the number of columns in the plate."""
        return self.cols

    def exclude_well(self, well_id):
        """Exclude a well from being used."""
        if well_id in self.wells:
            self.excluded_wells.add(well_id)
        else:
            raise ValueError(f"Well '{well_id}' does not exist in the plate.")

    def include_well(self, well_id):
        """Include an excluded well back into use."""
        self.excluded_wells.discard(well_id)

    def get_well(self, well_id):
        """Retrieve a specific well by its ID."""
        return self.wells.get(well_id, None)

    def zigzag_order(self,wells, fill_by="columns"):
        """
        Return wells ordered in a zigzag pattern.

        Args:
            wells (list of Well): The list of wells to be ordered.
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            list of Well: The list of wells ordered in a zigzag pattern.
        """
        def row_to_num(row):
            """Convert the row letter to a number (e.g., 'A' -> 0, 'B' -> 1)."""
            return ord(row) - ord('A')

        if fill_by == "rows":
            # Sort by row first (converted to number), and by column within each row, alternating the column order
            wells.sort(key=lambda w: (row_to_num(w.row), w.col if row_to_num(w.row) % 2 == 0 else -w.col))
        else:  # fill_by == "columns"
            # Sort by column first, and by row (converted to number) within each column, starting with A1
            wells.sort(key=lambda w: (w.col, -row_to_num(w.row) if w.col % 2 == 0 else row_to_num(w.row)))

        return wells

    def get_available_wells(self, fill_by="columns"):
        """
        Get a list of available wells, sorted by rows or columns in a zigzag pattern.

        Args:
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            list of Well: Sorted list of available wells.
        """
        if fill_by not in ["rows", "columns"]:
            raise ValueError("fill_by must be 'rows' or 'columns'.")

        available_wells = [well for well in self.wells.values() if well not in self.excluded_wells and well.assigned_reaction is None]

        return self.zigzag_order(available_wells, fill_by=fill_by)
    
    def get_all_wells(self):
        """Get a list of all wells."""
        return list(self.wells.values())

    def clear_all_wells(self):
        """Clear all wells and reset their status."""
        self.wells = {}
        self.exclude_wells = set()
        self.wells = self.create_wells()
        self.clear_all_wells_signal.emit()

    def reset_all_wells_for_stock(self,stock_id):
        for well in self.wells.values():
            if well.assigned_reaction is not None:
                well.assigned_reaction.reset_reagent_by_id(stock_id)
                # well.state_changed.emit(well.well_id)
        self.well_state_changed_signal.emit('all')
        

    def reset_all_wells(self):
        for well in self.wells.values():
            if well.assigned_reaction is not None:
                well.assigned_reaction.reset_all_reagents()
                # well.state_changed.emit(well.well_id)
        self.well_state_changed_signal.emit('all')

    def get_plate_status(self):
        """Get the status of the entire well plate."""
        status = {}
        for well_id, well in self.wells.items():
            status[well_id] = well.get_status()
        return status

    def assign_reactions_to_wells(self, reactions, fill_by="columns"):
        """
        Systematically assign reactions to available wells.

        Args:
            reactions (list of ReactionComposition): The reactions to assign to wells.
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            dict: A dictionary mapping reaction names to well IDs.
        """
        available_wells = self.get_available_wells(fill_by=fill_by)
        reaction_assignment = {}

        if len(reactions) > len(available_wells):
            raise ValueError("Not enough available wells to assign all reactions.")
        print(f"Assigning {len(reactions)} reactions to {len(available_wells)} available wells.")
        for i, reaction in enumerate(reactions):
            well = available_wells[i]
            well.assign_reaction(reaction)
            reaction_assignment[reaction.unique_id] = well.well_id
            print(f"Assigned reaction '{reaction.unique_id}' to well '{well.well_id}'.")

        return reaction_assignment
    
    def get_all_wells_with_reactions(self, fill_by="columns"):
        """
        Get all wells that have been assigned a reaction, sorted in a zigzag pattern.

        Args:
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            list of Well: Sorted list of wells with assigned reactions.
        """
        wells_with_reactions = [well for well in self.wells.values() if well.assigned_reaction is not None]

        return self.zigzag_order(wells_with_reactions, fill_by=fill_by)
    
    def well_state_changed(self, well_id):
        """Handle changes in the state of a well."""
        self.well_state_changed_signal.emit(well_id)

class PrinterHead(QObject):
    """
    Represents a printer head in a system.
    reagent (str): The reagent in the printer head.
    concentration (float): The concentration of the reagent.
    color (str): The color of the printer head.
    Methods:
    change_reagent(new_reagent): Changes the reagent in the printer head.
    change_concentration(new_concentration): Changes the concentration of the reagent.
    change_color(new_color): Changes the color of the printer head.
    """

    def __init__(self, stock_solution,color='Blue'):
        super().__init__()
        self.stock_solution = stock_solution
        self.color = color
        self.confirmed = False
        self.completed = False
        self.calibrations = []

    def get_stock_solution(self):
        return self.stock_solution

    def get_stock_id(self):
        return self.stock_solution.get_stock_id()
    
    def get_reagent_name(self):
        return self.stock_solution.get_reagent_name()
    
    def get_stock_concentration(self):
        return self.stock_solution.get_stock_concentration()
    
    def get_stock_name(self):
        return self.stock_solution.get_stock_name()

    def get_color(self):
        return self.color

    def change_stock_solution(self, stock_solution):
        self.stock_solution = stock_solution
    
    def change_color(self, new_color):
        self.color = new_color

    def mark_complete(self):
        self.completed = True

    def mark_incomplete(self):
        self.completed = False

    def check_complete(self,well_plate):
        '''Check the stock solution to see if all droplets have been added'''
        stock_id = self.get_stock_id()
        for well in well_plate.get_all_wells():
            if well.assigned_reaction is not None:
                if not well.check_stock_complete(stock_id):
                    self.mark_incomplete()
                    return False
        self.mark_complete()
        return True
    
    def add_calibration(self,calibration):
        self.calibrations.append(calibration)

    def get_calibrations(self):
        return self.calibrations

class PrinterHeadManager(QObject):
    """
    Manages all printer heads in the system, including tracking, assignment, and swapping.

    Attributes:
    - printer_heads (list): List of all printer heads created from the reaction collection.
    - assigned_printer_heads (dict): Mapping of slot numbers to assigned printer heads.
    - unassigned_printer_heads (list): List of printer heads that have not yet been assigned to any slot.
    """

    def __init__(self,color_dict):
        super().__init__()
        self.print_head_colors = color_dict
        self.printer_heads = []
        self.assigned_printer_heads = {}
        self.unassigned_printer_heads = []

    def create_printer_heads(self, stock_solutions_manager):
        """
        Create printer heads based on the reagents and concentrations in the reaction collection.
        
        Args:
        - reaction_collection (ReactionCollection): The collection of reactions from which to create printer heads.
        """
        stock_solutions = stock_solutions_manager.get_all_stock_solutions()
        for stock_solution in stock_solutions:
            printer_head = PrinterHead(stock_solution, color=self.generate_color())
            self.printer_heads.append(printer_head)
            self.unassigned_printer_heads.append(printer_head)
        print(f"Created {len(self.printer_heads)} printer heads.")

    def assign_printer_head_to_slot(self, slot_number, rack_model):
        """
        Assign an available printer head to a specified slot in the rack.

        Args:
        - slot_number (int): The slot number where the printer head should be assigned.
        - rack_model (RackModel): The rack model where the slot is located.
        
        Returns:
        - bool: True if a printer head was successfully assigned, False if no more unassigned printer heads are available.
        """
        if self.unassigned_printer_heads:
            printer_head = self.unassigned_printer_heads.pop(0)
            rack_model.update_slot_with_printer_head(slot_number, printer_head)
            self.assigned_printer_heads[slot_number] = printer_head
            print(f"Assigned printer head '{printer_head.get_stock_id()}' to slot {slot_number}.")
            return True
        else:
            print("No more unassigned printer heads available.")
            return False

    def swap_printer_head(self, slot_number, new_printer_head, rack_model):
        """
        Swap the printer head in the specified slot with the provided unassigned printer head.
        """
        old_printer_head = rack_model.slots[slot_number].printer_head
        if old_printer_head:
            self.unassigned_printer_heads.append(old_printer_head)
            self.unassigned_printer_heads.remove(new_printer_head)
            rack_model.update_slot_with_printer_head(slot_number, new_printer_head)
            self.assigned_printer_heads[slot_number] = new_printer_head
            print(f"Swapped printer head in slot {slot_number} with '{new_printer_head.get_stock_id()}'.")


    def generate_color(self):
        """
        Generate a color for the printer head. This is a placeholder function.
        
        Returns:
        - str: The color code or name.
        """
        colors = list(self.print_head_colors.values())
        return colors[len(self.printer_heads) % len(colors)]

    def get_all_printer_heads(self):
        """
        Get all printer heads managed by this class.

        Returns:
        - list: List of all printer heads.
        """
        return self.printer_heads

    def get_unassigned_printer_heads(self):
        """
        Get all unassigned printer heads.

        Returns:
        - list: List of unassigned printer heads.
        """
        return self.unassigned_printer_heads

    def get_assigned_printer_heads(self):
        """
        Get all assigned printer heads.

        Returns:
        - dict: Dictionary mapping slot numbers to assigned printer heads.
        """
        return self.assigned_printer_heads
    
    def get_printer_head_by_id(self, stock_id):
        for printer_head in self.printer_heads:
            if printer_head.get_stock_id() == stock_id:
                return printer_head
        return None
    
    def clear_all_printer_heads(self):
        """
        Clear all printer heads and reset the assignment status.
        """
        self.printer_heads = []
        self.assigned_printer_heads = {}
        self.unassigned_printer_heads = []

class Slot(QObject):
    """
    Represents a slot in a system.

    Attributes:
        number (int): The slot number.
        printer_head (PrinterHead): The printer head in the slot.
        confirmed (bool): Indicates if the slot has been confirmed.
    """

    def __init__(self, number, printer_head):
        super().__init__()
        self.number = number
        self.printer_head = printer_head
        self.confirmed = False
        self.locked = False
        self.coordinates = None

    def set_locked(self, locked):
        self.locked = locked

    def is_locked(self):
        return self.locked
    
    def assign_coordinates(self, x, y,z):
        """Assign coordinates to the slot."""
        self.coordinates = {'X':x, 'Y':y, 'Z':z}

    def get_coordinates(self):
        """Get the coordinates of the slot."""
        return self.coordinates
    
    def change_printer_head(self, new_printer_head,returned=False):
        self.printer_head = new_printer_head
        if not returned:
            self.unconfirm()
    
    def confirm(self):
        """
        Confirms the slot.
        """
        self.confirmed = True

    def unconfirm(self):
        """
        Unconfirms the slot.
        """
        self.confirmed = False


class RackModel(QObject):
    """
    Model for all data related to the rack state.

    Attributes:
    - slots (list of Slot): List of slots in the rack.
    - gripper_printer_head (PrinterHead): The printer head currently held by the gripper.
    - gripper_slot_number (int): The original slot number from which the printer head was loaded.

    Signals:
    - slot_updated: Emitted when a slot is updated.
    - slot_confirmed: Emitted when a slot is confirmed.
    - gripper_updated: Emitted when the gripper state changes.
    - error_occurred: Emitted when an invalid operation is attempted.
    """

    slot_updated = Signal()
    gripper_updated = Signal()
    error_occurred = Signal(str)
    rack_calibration_updated_signal = Signal()

    def __init__(self, num_slots,location_data=None):
        super().__init__()
        self.slots = [Slot(i, None) for i in range(num_slots)]
        self.gripper_printer_head = None
        self.gripper_slot_number = None
        self.calibrations = {}
        if location_data is not None:
            self.process_location_data(location_data)

        self.calibration_applied = False
        self.temp_calibration_data = {}
    
        self.apply_calibration_data()

    def apply_calibration_data(self):
        if self.calibrations['rack_position_Left'] == {} or self.calibrations['rack_position_Right'] == {}:
            self.calibration_applied = False
            print(f"Calibration is incomplete. Need at least 2 calibration points, but only {len(list(self.calibrations))} provided.")
            return
        else:
            slot_positions = self.calculate_slot_positions()
            self.assign_slot_positions(slot_positions)
            self.calibration_applied = True
        
    def calculate_slot_positions(self):
        '''
        Calculate the positions of the slots based on the calibration data
        '''
        slot_positions = []
        left_calibration = self.calibrations['rack_position_Left']
        right_calibration = self.calibrations['rack_position_Right']

        x_diff = right_calibration['X'] - left_calibration['X']
        y_diff = right_calibration['Y'] - left_calibration['Y']
        z_diff = right_calibration['Z'] - left_calibration['Z']
        num_slots = self.get_num_slots()

        slot_depth = x_diff / (num_slots + 1)
        slot_width = y_diff / (num_slots + 1)
        slot_height = z_diff / (num_slots + 1)
        for i in range(1,num_slots+1):
            slot_positions.append({
                'X': int(round(left_calibration['X'] + (i * slot_depth),0)),
                'Y': int(round(left_calibration['Y'] + (i * slot_width),0)),
                'Z': int(round(left_calibration['Z'] + (i * slot_height),0))
            })
        return slot_positions
    
    def assign_slot_positions(self,slot_positions):
        for i,slot in enumerate(self.slots):
            slot.assign_coordinates(slot_positions[i]['X'],slot_positions[i]['Y'],slot_positions[i]['Z'])

    def process_location_data(self,location_data):
        if location_data.get('rack_position_Right',None) is not None:
            self.calibrations['rack_position_Right'] = location_data['rack_position_Right']
        else:
            self.calibrations['rack_position_Right'] = {}
        if location_data.get('rack_position_Left',None) is not None:
            self.calibrations['rack_position_Left'] = location_data['rack_position_Left']
        else:
            self.calibrations['rack_position_Left'] = {}

    def get_all_current_rack_calibrations(self):
        return self.calibrations
    
    def get_calibration_by_name(self, name):
        return self.calibrations.get(name, None)
    
    def get_temp_calibration_by_name(self, name):
        return self.temp_calibration_data.get(name, None)
    
    def set_calibration_position(self, position_name, coordinates):
        """Set a temporary calibration position."""
        self.temp_calibration_data[position_name] = coordinates

    def store_calibrations(self):
        """Save the temporary calibration data to the main calibration data."""
        for position_name, coords in self.temp_calibration_data.items():
            self.calibrations[position_name] = coords
        self.temp_calibration_data.clear()

    def discard_temp_calibrations(self):
        """Discard the temporary calibration data."""
        self.temp_calibration_data.clear()

    def update_calibration_data(self):
        """Run the full update of all calibration data."""
        self.store_calibrations()
        self.save_calibrations_to_file()
        self.apply_calibration_data()

    def save_calibrations_to_file(self):
        self.rack_calibration_updated_signal.emit()

    def check_calibration_applied(self):
        return self.calibration_applied
    
    def get_slot_coordinates(self,slot_number):
        return self.slots[slot_number].get_coordinates()

    def get_num_slots(self):
        return len(self.slots)

    def update_slot_with_printer_head(self, slot_number, printer_head):
        """
        Update a slot with a new printer head.

        Args:
        - slot_number (int): The slot number to update.
        - printer_head (PrinterHead): The printer head to place in the slot.
        """
        if 0 <= slot_number < len(self.slots):
            slot = self.slots[slot_number]
            slot.change_printer_head(printer_head)
            slot.set_locked(False)
            self.slot_updated.emit()
            print(f"Slot {slot_number} updated with printer head: {printer_head.get_stock_id()}, {printer_head.color}")

    def lock_slot(self, slot_number):
        """
        Lock a slot when its printer head is in the gripper.
        """
        slot = self.slots[slot_number]
        slot.set_locked(True)
        self.slot_updated.emit()

    def unlock_slot(self, slot_number):
        """
        Unlock a slot when its printer head is returned from the gripper.
        """
        slot = self.slots[slot_number]
        slot.set_locked(False)
        self.slot_updated.emit()
    
    def confirm_slot(self, slot_number):
        """
        Confirm a slot.

        Args:
        - slot_number (int): The slot number to confirm.
        """
        if 0 <= slot_number < len(self.slots):
            if self.slots[slot_number].printer_head is not None:
                self.slots[slot_number].confirm()
                self.slot_updated.emit()
                self.gripper_updated.emit()
                print(f"Slot {slot_number} confirmed.")
            else:
                error_msg = f"Slot {slot_number} has no printer head to confirm."
                self.error_occurred.emit(error_msg)
                print(error_msg)

    def clear_all_slots(self):
        """
        Clear all slots in the rack.
        """
        for slot in self.slots:
            slot.change_printer_head(None)
            slot.unconfirm()
        self.gripper_printer_head = None
        self.gripper_slot_number = None
        self.slot_updated.emit()
        self.gripper_updated.emit()
        print("All slots cleared.")
    
    def verify_transfer_to_gripper(self, slot_number):
        """
        Verify if the transfer of the printer head from a slot to the gripper is valid.

        Args:
        - slot_number (int): The slot number to transfer from.

        Returns:
        - bool: True if the transfer is valid, False otherwise.
        - str: Error message if the transfer is not valid, empty string otherwise.
        """
        if 0 <= slot_number < len(self.slots):
            slot = self.slots[slot_number]
            if slot.printer_head is not None and slot.confirmed:
                if self.gripper_printer_head is None:
                    return True, ""
                else:
                    return False, "Gripper is already holding a printer head."
            else:
                return False, f"Slot {slot_number} is not confirmed or empty."
        else:
            return False, f"Slot number {slot_number} is out of range."

    def transfer_to_gripper(self, slot_number):
        """
        Transfer the printer head from a slot to the gripper if the transfer is valid.

        Args:
        - slot_number (int): The slot number to transfer from.
        """
        is_valid, error_msg = self.verify_transfer_to_gripper(slot_number)
        if is_valid:
            slot = self.slots[slot_number]
            self.gripper_printer_head = slot.printer_head
            self.gripper_slot_number = slot_number
            slot.change_printer_head(None,returned=True)
            self.lock_slot(slot_number)
            self.slot_updated.emit()
            self.gripper_updated.emit()
            print(f"Printer head from slot {slot_number} transferred to gripper.")
        else:
            self.error_occurred.emit(error_msg)
            print(error_msg)

    def verify_transfer_from_gripper(self, slot_number):
        """
        Verify if the transfer of the printer head from the gripper to a slot is valid.

        Args:
        - slot_number (int): The slot number to transfer to.

        Returns:
        - bool: True if the transfer is valid, False otherwise.
        - str: Error message if the transfer is not valid, empty string otherwise.
        """
        if 0 <= slot_number < len(self.slots):
            slot = self.slots[slot_number]
            if slot_number == self.gripper_slot_number:
                if slot.printer_head is None and self.gripper_printer_head is not None:
                    return True, ""
                else:
                    return False, "Slot is already occupied or gripper is empty."
            else:
                return False, f"Printer head can only be unloaded to its original slot {self.gripper_slot_number}."
        else:
            return False, f"Slot number {slot_number} is out of range."

    def transfer_from_gripper(self, slot_number):
        """
        Transfer the printer head from the gripper to a slot if the transfer is valid.

        Args:
        - slot_number (int): The slot number to transfer to.
        """
        is_valid, error_msg = self.verify_transfer_from_gripper(slot_number)
        if is_valid:
            slot = self.slots[slot_number]
            slot.change_printer_head(self.gripper_printer_head,returned=True)
            self.unlock_slot(slot_number)
            self.gripper_printer_head = None
            self.gripper_slot_number = None
            self.slot_updated.emit()
            self.gripper_updated.emit()
            print(f"Printer head transferred from gripper to slot {slot_number}.")
        else:
            self.error_occurred.emit(error_msg)
            print(error_msg)

    def swap_printer_heads_between_slots(self, slot_number_1, slot_number_2):
        """
        Swap the printer heads between two slots and emit signals.
        """
        slot_1 = self.slots[slot_number_1]
        slot_2 = self.slots[slot_number_2]
        origial_slot_1_printer_head = slot_1.printer_head
        slot_1.change_printer_head(slot_2.printer_head)
        slot_2.change_printer_head(origial_slot_1_printer_head)
        self.slot_updated.emit()

    def get_slot_info(self, slot_number):
        """
        Get information about a slot.

        Args:
        - slot_number (int): The slot number to get information from.

        Returns:
        - dict: A dictionary containing the slot's information.
        """
        if 0 <= slot_number < len(self.slots):
            slot = self.slots[slot_number]
            printer_head_info = None
            if slot.printer_head is not None:
                printer_head_info = {
                    "reagent": slot.printer_head.reagent,
                    "concentration": slot.printer_head.concentration,
                    "color": slot.printer_head.color
                }
            return {
                "slot_number": slot.number,
                "confirmed": slot.confirmed,
                "printer_head": printer_head_info
            }
        return None

    def get_gripper_info(self):
        """
        Get information about the printer head in the gripper.

        Returns:
        - dict: A dictionary containing the printer head's information or None if empty.
        """
        if self.gripper_printer_head is not None:
            return {
                "reagent": self.gripper_printer_head.get_reagent_name(),
                "concentration": self.gripper_printer_head.get_stock_concentration(),
                "color": self.gripper_printer_head.color
            }
        return None
    
    def get_gripper_printer_head(self):
        return self.gripper_printer_head
    
    def assign_reagents_to_printer_heads(self, reaction_collection):
        """
        Assigns reagents from the reaction collection to printer heads and places them in available slots.
        """
        slot_index = 0
        for reagent_name,concentration in reaction_collection.get_unique_reagent_conc_pairs():
            if slot_index >= len(self.slots):
                raise ValueError("Not enough slots to assign all reagents.")
            
            # Create a PrinterHead for this reagent and concentration
            printer_head = PrinterHead(reagent=reagent_name, concentration=concentration, color=self.generate_color(slot_index))
            
            # Assign the PrinterHead to the current slot and confirm the slot
            self.update_slot_with_printer_head(slot_index, printer_head)
            
            slot_index += 1

    def generate_color(self, slot_index):
        """
        Generate a color for the printer head based on the slot index. This is a placeholder function.
        """
        colors = ["red", "green", "blue", "yellow", "purple", "orange"]
        return colors[slot_index % len(colors)]

class LocationModel(QObject):
    """
    Model for managing location data, including reading and writing to a JSON file.

    Attributes:
    - locations: A dictionary of location names and their XYZ coordinates.
    """

    locations_updated = Signal()  # Signal to notify when locations are updated

    def __init__(self, json_file_path='Presets\\Locations.json'):
        super().__init__()
        # Get the directory of the current script
        # script_dir = os.path.dirname(os.path.abspath(__file__))
        # Construct the full file path
        # self.json_file_path = os.path.join(script_dir, json_file_path)     
        self.json_file_path = json_file_path   
        self.locations = {}  # Dictionary to hold location data

    def load_locations(self):
        """Load locations from a JSON file."""
        try:
            with open(self.json_file_path, "r") as file:
                self.locations = json.load(file)
            self.locations_updated.emit()
            print(f"Locations loaded from {self.json_file_path}")
        except FileNotFoundError:
            print(f"{self.json_file_path} not found. Starting with an empty locations dictionary.")
            self.locations = {}
        except json.JSONDecodeError:
            print(f"Error decoding JSON from {self.json_file_path}. Starting with an empty locations dictionary.")
            self.locations = {}
        except Exception as e:
            print(f"Failed to load locations: {e}")

    def save_locations(self):
        """Save locations to a JSON file."""
        try:
            with open(self.json_file_path, "w") as file:
                json.dump(self.locations, file, indent=4)
            print(f"Locations saved to {self.json_file_path}")
        except Exception as e:
            print(f"Failed to save locations: {e}")

    def add_location(self, name, x, y, z):
        """Add a new location or update an existing one."""
        self.locations[name] = {'X': x, 'Y': y, 'Z': z}
        self.locations_updated.emit()
        print(f"Location '{name}' added/updated.")

    def update_location(self, name, x, y, z):
        """Update an existing location by name."""
        if name in self.locations:
            self.locations[name] = {'X': x, 'Y': y, 'Z': z}
            self.locations_updated.emit()
            print(f"Location '{name}' updated.")
        else:
            print(f"Location '{name}' not found.")

    def update_location_coords(self, name, coords):
        """Update an existing location by name."""
        if name in self.locations:
            self.locations[name] = coords
            self.locations_updated.emit()
            print(f"Location '{name}' updated.")
        else:
            print(f"Location '{name}' not found.")

    def remove_location(self, name):
        """Remove a location by name."""
        if name in self.locations:
            del self.locations[name]
            self.locations_updated.emit()
            print(f"Location '{name}' removed.")
        else:
            print(f"Location '{name}' not found.")

    def get_location(self, name):
        """Get a location's coordinates by name in an array [x,y,z]."""
        if name in self.locations:
            return [self.locations[name]['X'], self.locations[name]['Y'], self.locations[name]['Z']]
        else:
            return None
    
    def get_location_dict(self, name):
        """Get a location's coordinates by name in a dictionary."""
        if name in self.locations:
            return self.locations[name]
        else:
            return None
        
    def get_all_locations(self):
        """Get all locations."""
        return self.locations

    def get_location_names(self):
        """Get a list of all location names."""
        return list(self.locations.keys())

class MachineModel(QObject):
    '''
    Model for all data related to the machine state
    Data includes:
    - Current position of all motors
    - Target position of all motors
    - Current pressure
    - Target pressure

    Methods include:
    - Update position
    - Update pressure
    - Update target position
    - Update target pressure
    '''
    step_size_changed = QtCore.Signal(int)  # Signal to notify when step size changes
    machine_state_updated = QtCore.Signal(bool)  # Signal to notify when machine state changes
    balance_state_updated = QtCore.Signal(bool)  # Signal to notify when balance state changes
    motor_state_changed = QtCore.Signal(bool)  # Signal to notify when motor state changes
    regulation_state_changed = QtCore.Signal(bool)  # Signal to notify when pressure regulation state changes
    pressure_updated = Signal(np.ndarray)  # Signal to emit when pressure readings are updated
    ports_updated = Signal(list)  # Signal to notify view of available ports update
    connection_requested = Signal(str, str)  # Signal to request connection
    gripper_state_changed = Signal(bool)  # Signal to notify when gripper state changes
    machine_paused = Signal()  # Signal to notify when machine is paused
    home_status_signal = Signal()

    def __init__(self):
        super().__init__()
        self.available_ports = []
        self.machine_connected = False
        self.balance_connected = False
        # self.machine_port = "Virtual"
        self.balance_port = "Virtual"

        self.motors_enabled = False
        self.target_x = 0
        self.target_y = 0
        self.target_z = 0
        self.target_p = 0

        self.current_x = 0
        self.current_y = 0
        self.current_z = 0
        self.current_p = 0

        self.motors_homed = False
        self.current_location = "Unknown"
        self.paused = False
        self.machine_free = True


        self.gripper_open = False
        self.gripper_active = False

        self.step_num = 4
        self.possible_steps = [2,10,50,250,500,1000,2000]
        self.step_size = self.possible_steps[self.step_num]

        self.current_pressure = 0
        self.pressure_readings = np.zeros(100)  # Array to store the last 100 pressure readings
        self.target_pressure = 0

        self.fss = 13107
        self.psi_offset = 1638
        self.psi_max = 15

        self.regulating_pressure = False

        self.max_cycle = 0
        self.cycle_count = 0

    def update_ports(self, ports):
        self.available_ports = ports
        self.ports_updated.emit(self.available_ports)

    def connect_machine(self):
        self.machine_connected = True
        self.machine_state_updated.emit(self.machine_connected)

    def disconnect_machine(self):
        self.machine_connected = False
        self.machine_state_updated.emit(self.machine_connected)
        self.motors_enabled = False
        self.motor_state_changed.emit(self.motors_enabled)
        self.regulating_pressure = False
        self.regulation_state_changed.emit(self.regulating_pressure)
        self.reset_home_status()
        self.home_status_signal.emit()
    
    def is_connected(self):
        return self.machine_connected
    
    def motors_are_enabled(self):
        return self.motors_enabled
    
    def motors_are_homed(self):
        return self.motors_homed

    def connect_balance(self, port):
        self.balance_port = port
        self.balance_connected = True
        self.balance_state_updated.emit(self.balance_connected)

    def disconnect_balance(self):
        self.balance_connected = False
        self.balance_state_updated.emit(self.balance_connected)

    def pause_commands(self):
        self.paused = True
        self.machine_paused.emit()

    def resume_commands(self):
        self.paused = False
        self.machine_paused.emit()

    def clear_command_queue(self):
        self.paused = False
        self.machine_paused.emit()

    def open_gripper(self):
        self.gripper_open = True
        self.gripper_active = True
        self.gripper_state_changed.emit(self.gripper_open)
    
    def close_gripper(self):
        self.gripper_open = False
        self.gripper_active = True
        self.gripper_state_changed.emit(self.gripper_open)

    def gripper_off(self):
        self.gripper_active = False
    
    def convert_to_psi(self,pressure):
        return round(((float(pressure) - self.psi_offset) / self.fss) * self.psi_max,4)
    
    def convert_to_raw_pressure(self,psi):
        return int((float(psi) / self.psi_max) * self.fss + self.psi_offset)

    def set_step_size(self, new_step_size):
        """Set the step size and emit a signal if it changes."""
        if self.step_size != new_step_size:
            self.step_size = new_step_size
            self.step_num = self.possible_steps.index(new_step_size)
            self.step_size_changed.emit(self.step_size)
            print(f"Step size set to {self.step_size}")

    def increase_step_size(self):
        """Increase the step size if possible."""
        if self.step_num < len(self.possible_steps) - 1:
            self.step_num += 1
            self.step_size = self.possible_steps[self.step_num]
            self.step_size_changed.emit(self.step_size)
            print(f"Step size increased to {self.step_size}")

    def decrease_step_size(self):
        """Decrease the step size if possible."""
        if self.step_num > 0:
            self.step_num -= 1
            self.step_size = self.possible_steps[self.step_num]
            self.step_size_changed.emit(self.step_size)
            print(f"Step size decreased to {self.step_size}")
    
    def toggle_motor_state(self):
        """Toggle the motor state and emit a signal."""
        self.motors_enabled = not self.motors_enabled
        if not self.motors_enabled:
            self.regulating_pressure = False
            self.regulation_state_changed.emit(self.regulating_pressure)
        self.motor_state_changed.emit(self.motors_enabled)
        print(f"Motors {'enabled' if self.motors_enabled else 'disabled'}")

    def toggle_regulation_state(self):
        """Toggle the motor state and emit a signal."""
        self.regulating_pressure = not self.regulating_pressure
        self.regulation_state_changed.emit(self.regulating_pressure)
        print(f"Pressure regulation {'enabled' if self.regulating_pressure else 'disabled'}")

    def update_target_position(self, x, y, z):
        self.target_x = int(x)
        self.target_y = int(y)
        self.target_z = int(z)

    def update_target_p_motor(self, p):
        self.target_p = int(p)

    def update_current_position(self, x, y, z):
        self.current_x = int(x)
        self.current_y = int(y)
        self.current_z = int(z)

    def update_current_p_motor(self, p):
        self.current_p = int(p)
    
    def update_target_pressure(self, pressure):
        self.target_pressure = self.convert_to_psi(pressure)

    def update_pressure(self, new_pressure):
        """Update the pressure readings with a new value."""
        # Shift the existing readings and add the new reading
        converted_pressure = self.convert_to_psi(new_pressure)
        self.current_pressure = converted_pressure
        self.pressure_readings = np.roll(self.pressure_readings, -1)
        self.pressure_readings[-1] = converted_pressure
        self.pressure_updated.emit(self.pressure_readings)

    def get_current_pressure(self):
        return self.current_pressure

    def update_cycle_count(self,cycle_count):
        self.cycle_count = int(cycle_count)

    def update_max_cycle(self,max_cycle):
        self.max_cycle = int(max_cycle)

    def get_current_position(self):
        return [self.current_x, self.current_y, self.current_z]

    def get_current_position_dict(self):
        return {"X": self.current_x, "Y": self.current_y, "Z": self.current_z}

    def get_current_position_dict_capital(self):
        return {"X": self.current_x, "Y": self.current_y, "Z": self.current_z}

    def handle_home_complete(self):
        self.motors_homed = True
        self.current_location = "Home"
        self.home_status_signal.emit()
        print("Motors homed.")

    def reset_home_status(self):
        self.motors_homed = False
        self.current_location = "Unknown"

    def update_current_location(self, location):
        self.current_location = location

    def is_busy(self):
        return not self.machine_free



class Model(QObject):
    '''
    Model class for the MVC architecture
    '''
    machine_state_updated = Signal()  # Signal to notify the view of state changes
    experiment_loaded = Signal()  # Signal to notify the view of an experiment being loaded

    def __init__(self):
        super().__init__()

        self.locations_path = '.\\MVC-interface\\Presets\\Locations.json'
        self.plates_path = '.\\MVC-interface\\Presets\\Plates.json'
        self.colors_path = '.\\MVC-interface\\Presets\\Printer_head_colors.json'


        self.printer_head_colors = self.load_colors(self.colors_path)
        self.machine_model = MachineModel()
        self.num_slots = 5
        self.location_data = self.load_all_location_data(self.locations_path)
        self.rack_model = RackModel(self.num_slots,location_data=self.location_data)
        self.location_model = LocationModel(json_file_path=self.locations_path)
        self.location_model.load_locations()  # Load locations at startup
        self.all_plate_data = self.load_all_plate_data(self.plates_path)
        self.well_plate = WellPlate(self.all_plate_data)
        self.stock_solutions = StockSolutionManager()
        self.reaction_collection = ReactionCollection()
        self.printer_head_manager = PrinterHeadManager(self.printer_head_colors)
        self.experiment_model = ExperimentModel()
        self.experiment_file_path = None

        self.well_plate.plate_format_changed_signal.connect(self.update_well_plate)
        self.rack_model.rack_calibration_updated_signal.connect(self.update_rack_calibration)

    def load_colors(self, file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
        
    def load_all_plate_data(self,file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
        
    def load_all_location_data(self,file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
        
    def update_rack_calibration(self):
        print('\n---Updating rack calibration')
        self.location_model.update_location_coords('rack_position_Left',self.rack_model.get_calibration_by_name('rack_position_Left'))
        self.location_model.update_location_coords('rack_position_Right',self.rack_model.get_calibration_by_name('rack_position_Right'))
        self.location_model.save_locations()

    def update_state(self, status_dict):
        '''
        Update the state of the machine model
        '''
        self.machine_model.update_current_position(status_dict.get('X', self.machine_model.current_x),
                                                   status_dict.get('Y', self.machine_model.current_y),
                                                   status_dict.get('Z', self.machine_model.current_z))
        
        self.machine_model.update_current_p_motor(status_dict.get('P', self.machine_model.current_p))   
        self.machine_model.update_target_position(status_dict.get('Tar_X', self.machine_model.target_x),
                                                  status_dict.get('Tar_Y', self.machine_model.target_y),
                                                  status_dict.get('Tar_Z', self.machine_model.target_z))
        self.machine_model.update_target_p_motor(status_dict.get('Tar_P', self.machine_model.target_p))
        self.machine_model.update_target_pressure(status_dict.get('Tar_pressure', self.machine_model.target_pressure))
        self.machine_model.update_pressure(status_dict.get('Pressure', self.machine_model.current_pressure))
        self.machine_model.update_cycle_count(status_dict.get('Cycle_count', self.machine_model.cycle_count))
        self.machine_model.update_max_cycle(status_dict.get('Max_cycle', self.machine_model.max_cycle))
        if status_dict['Last_completed'] != status_dict['Current_command']:
            self.machine_model.machine_free = False
        else:
            self.machine_model.machine_free = True
        self.machine_state_updated.emit()
    
    def load_reactions_from_csv(self,csv_file_path):
        """
        Load reactions from a CSV file and return a ReactionCollection.
        
        The CSV should have a 'reaction_id' column followed by columns for each reagent with target concentrations.
        """
        df = pd.read_csv(csv_file_path)
        stock_solutions = StockSolutionManager()
        stock_names = [c for c in df.columns if c != 'reaction_id']
        stock_solutions.add_all_stock_solutions(stock_names)
        
        reaction_collection = ReactionCollection()

        for _, row in df.iterrows():
            reaction_name = row['reaction_id']
            reaction = ReactionComposition(reaction_name)

            for stock_id, droplets in row.items():
                if stock_id != 'reaction_id':  # Skip the 'reaction_id' column
                    current_stock = stock_solutions.get_stock_by_id(stock_id)
                    reaction.add_reagent(current_stock, droplets)
            
            reaction_collection.add_reaction(reaction)

        return stock_solutions,reaction_collection
    
    def load_experiment_from_file(self, file_path, plate_name=None):
        """Load an experiment from a CSV file. Remove any existing experiment data."""
        if not file_path.endswith('.csv'):
            raise ValueError("Invalid file format. Please load a CSV file.")
        if len(self.reaction_collection.get_all_reactions()) > 0:
            self.stock_solutions = StockSolutionManager()
            self.reaction_collection = ReactionCollection()
            self.well_plate.clear_all_wells()
        if plate_name is not None:
            self.well_plate.set_plate_format(plate_name)
        self.stock_solutions, self.reaction_collection = self.load_reactions_from_csv(file_path)
        print(f'Stock Solutions:{self.stock_solutions.get_stock_solution_names()}')
        self.well_plate.assign_reactions_to_wells(self.reaction_collection.get_all_reactions())
        self.assign_printer_heads()
        self.experiment_loaded.emit()
        self.experiment_file_path = file_path

    def load_reactions_from_model(self):
        stock_solutions = StockSolutionManager()
        for stock in self.experiment_model.get_all_stock_solutions():
            stock_solutions.add_stock_solution(stock['reagent_name'],stock['concentration'],required_volume=stock['total_volume'])
        print(f'All stock solutions:\n{stock_solutions.get_stock_solution_names()}')
        print(f'Stock formated:\n{stock_solutions.get_stock_solution_names_formated()}')
        reaction_collection = ReactionCollection()
        for unique_id, reaction_df in self.experiment_model.all_droplet_df.groupby('unique_id'):
            reaction = ReactionComposition(unique_id)
            for _, row in reaction_df.iterrows():
                print(f'Row:{row}')
                print(f'Stock Solution:{row["reagent_name"]},{row["stock_solution"]}')
                current_stock = stock_solutions.get_stock_solution(row['reagent_name'],row['stock_solution'])
                reaction.add_reagent(current_stock, row['droplet_count'])
            
            reaction_collection.add_reaction(reaction)
        return stock_solutions,reaction_collection

    def load_experiment_from_model(self,plate_name=None):
        if self.experiment_model.get_number_of_reactions() == 0:
            print("No reactions in the experiment model.")
            return
        if len(self.reaction_collection.get_all_reactions()) > 0:
            self.clear_experiment()
        if plate_name is not None:
            self.well_plate.set_plate_format(plate_name)
        
        self.stock_solutions, self.reaction_collection = self.load_reactions_from_model()
        print(f'Stock Solutions:{self.stock_solutions.get_stock_solution_names()}')
        self.well_plate.assign_reactions_to_wells(self.reaction_collection.get_all_reactions())
        self.well_plate.apply_calibration_data()
        self.assign_printer_heads()
        self.experiment_loaded.emit()

    def reload_experiment(self, plate_name=None):
        """Reload the experiment from the last loaded file."""
        if self.experiment_file_path is not None:
            self.load_experiment_from_file(self.experiment_file_path,plate_name=plate_name)
        else:
            print("No experiment file path found. Please load an experiment file.")

    def update_well_plate(self):
        if self.reaction_collection is not None:
            self.well_plate.assign_reactions_to_wells(self.reaction_collection.get_all_reactions())
            self.experiment_loaded.emit()
        else:
            print("No experiment data loaded.")

    def clear_experiment(self):
        """Clear all experiment data and reset the well plate."""
        self.stock_solutions.clear_all_stock_solutions()
        self.reaction_collection.clear_all_reactions()
        self.well_plate.clear_all_wells()
        self.printer_head_manager.clear_all_printer_heads()
        self.rack_model.clear_all_slots()
        self.experiment_loaded.emit()

    def assign_printer_heads(self):
        """Assign printer heads to the slots in the rack."""
        # Create and assign printer heads for each unique pair
        self.printer_head_manager.create_printer_heads(self.stock_solutions)
        for i in range(self.rack_model.get_num_slots()):
            if not self.printer_head_manager.assign_printer_head_to_slot(i, self.rack_model):
                break  # Stop assigning if there are no more unassigned printer heads


if __name__ == "__main__":
    model = Model()
    model.load_experiment_from_file('mock_reaction_compositions.csv')
