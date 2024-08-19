import pandas as pd
import numpy as np
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer
import json
import heapq
import os
import csv
import cv2

class StockSolution(QObject):
    '''
    Represents a specific instance of a reagent at a certain concentration
    Each stock solution can be assigned to a printer head.
    '''
    def __init__(self, stock_id, reagent_name,concentration):
        super().__init__()
        self.stock_id = stock_id
        self.reagent_name = reagent_name
        self.concentration = concentration

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

    def add_stock_solution(self, reagent_name, concentration):
        # Generates a unique identifier for the reagent/concentration pair
        stock_id = '_'.join([reagent_name,str(concentration)])
        self.stock_solutions.update({stock_id:StockSolution(reagent_name,concentration)})

    def get_stock_solution(self, reagent_name, concentration):
        """Retrieve a reagent-concentration pair."""
        unique_id = '_'.join([reagent_name,str(concentration)])
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
    def __init__(self, name):
        super().__init__()
        self.name = name
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
        if reaction.name not in self.reactions:
            self.reactions[reaction.name] = reaction
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
        self.coordinates = (x, y,z)

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
        self.rows = self.current_plate_data['rows']
        self.cols = self.current_plate_data['columns']
        self.wells = self.create_wells()
        self.excluded_wells = set()
        self.calibrations = {}  # Dictionary to hold calibration data for the 4 corners of the plate
        self.transform_matrix = None  # Matrix to hold the transformation matrix to apply calibration data

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
                self.plate_format_changed_signal.emit()
                return
        raise ValueError(f"Plate format '{plate_name}' not found.")
    
    def get_plate_dimensions(self):
        return self.rows,self.cols

    def incorporate_calibration_data(self, calibration_data):
        """Incorporate calibration data for the plate."""
        self.calibrations = calibration_data

    def calculate_plate_matrix(self):
        """Calculate the transformation matrix for the plate."""
        if len(self.calibrations) < 4:
            raise ValueError("Not enough calibration data points to calculate the transformation matrix.")
        # Define the corners of the plate in the machine coordinate system

            

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
        self.transform_matrix = cv2.getPerspectiveTransform(self.corners, self.plate_dimensions)
        self.inv_trans_matrix = np.linalg.pinv(self.transform_matrix)
    
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
                well.state_changed.emit(well.well_id)

    def reset_all_wells(self):
        for well in self.wells.values():
            if well.assigned_reaction is not None:
                well.assigned_reaction.reset_all_reagents()
                well.state_changed.emit(well.well_id)

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
            reaction_assignment[reaction.name] = well.well_id
            print(f"Assigned reaction '{reaction.name}' to well '{well.well_id}'.")

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

    def set_locked(self, locked):
        self.locked = locked

    def is_locked(self):
        return self.locked
    
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

    def __init__(self, num_slots):
        super().__init__()
        self.slots = [Slot(i, None) for i in range(num_slots)]
        self.gripper_printer_head = None
        self.gripper_slot_number = None

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

    def __init__(self, json_file_path="locations.json"):
        super().__init__()
        # Get the directory of the current script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Construct the full file path
        self.json_file_path = os.path.join(script_dir, json_file_path)        
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
        self.locations[name] = {"x": x, "y": y, "z": z}
        self.locations_updated.emit()
        print(f"Location '{name}' added/updated.")

    def update_location(self, name, x, y, z):
        """Update an existing location by name."""
        if name in self.locations:
            self.locations[name] = {"x": x, "y": y, "z": z}
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
            return [self.locations[name]["x"], self.locations[name]["y"], self.locations[name]["z"]]
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
        return round(((int(pressure) - self.psi_offset) / self.fss) * self.psi_max,4)
    
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
        self.pressure_readings = np.roll(self.pressure_readings, -1)
        self.pressure_readings[-1] = converted_pressure
        self.pressure_updated.emit(self.pressure_readings)

    def update_cycle_count(self,cycle_count):
        self.cycle_count = cycle_count

    def update_max_cycle(self,max_cycle):
        self.max_cycle = max_cycle

    def get_current_position(self):
        return [self.current_x, self.current_y, self.current_z]

    def get_current_position_dict(self):
        return {"x": self.current_x, "y": self.current_y, "z": self.current_z}

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


class Model(QObject):
    '''
    Model class for the MVC architecture
    '''
    machine_state_updated = Signal()  # Signal to notify the view of state changes
    experiment_loaded = Signal()  # Signal to notify the view of an experiment being loaded

    def __init__(self):
        super().__init__()
        self.printer_head_colors = self.load_colors('.\\MVC-interface\\Presets\\Printer_head_colors.json')
        self.machine_model = MachineModel()
        self.num_slots = 5
        self.rack_model = RackModel(self.num_slots)
        self.location_model = LocationModel()
        self.location_model.load_locations()  # Load locations at startup
        self.all_plate_data = self.load_all_plate_data('.\\MVC-interface\\Presets\\Plates.json')
        self.well_plate = WellPlate(self.all_plate_data)
        self.stock_solutions = StockSolutionManager()
        self.reaction_collection = ReactionCollection()
        self.printer_head_manager = PrinterHeadManager(self.printer_head_colors)

        self.experiment_file_path = None

        self.well_plate.plate_format_changed_signal.connect(self.update_well_plate)

    def load_colors(self, file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
        
    def load_all_plate_data(self,file_path):
        with open(file_path, 'r') as file:
            return json.load(file)


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
