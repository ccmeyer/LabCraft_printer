import pandas as pd
import numpy as np
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer
import json
import heapq
import os

class Reagent:
    def __init__(self, name):
        self.name = name
        self.concentrations = {}

    def add_concentration(self, concentration, volume):
        """Add a specific concentration of the reagent with its available volume."""
        self.concentrations[concentration] = volume

    def get_volume(self, concentration):
        """Return the available volume for a specific concentration."""
        return self.concentrations.get(concentration, 0)

    def use_volume(self, concentration, volume_used):
        """Use a specific volume of a concentration, reducing its available amount."""
        if concentration in self.concentrations:
            if self.concentrations[concentration] >= volume_used:
                self.concentrations[concentration] -= volume_used
            else:
                raise ValueError("Not enough volume available")
        else:
            raise ValueError("Concentration not available")
        
class ConcentrationManager:
    def __init__(self):
        self.reagents = {}

    def add_reagent(self, name):
        """Add a new reagent to the manager."""
        if name not in self.reagents:
            self.reagents[name] = Reagent(name)

    def add_concentration(self, reagent_name, concentration, volume):
        """Add a concentration and volume to a specific reagent."""
        if reagent_name in self.reagents:
            self.reagents[reagent_name].add_concentration(concentration, volume)
        else:
            raise ValueError("Reagent not found")

    def use_reagent(self, reagent_name, concentration, volume_used):
        """Use a specific volume of a reagent's concentration."""
        if reagent_name in self.reagents:
            self.reagents[reagent_name].use_volume(concentration, volume_used)
        else:
            raise ValueError("Reagent not found")
        
class ReactionComposition:
    def __init__(self, name):
        self.name = name
        self.reagents = {}  # Dictionary to hold reagent name and its target concentration

    def add_reagent(self, reagent_name, concentration):
        """Add a reagent and its target concentration to the reaction."""
        self.reagents[reagent_name] = concentration

    def remove_reagent(self, reagent_name):
        """Remove a reagent from the reaction."""
        if reagent_name in self.reagents:
            del self.reagents[reagent_name]
        else:
            raise ValueError(f"Reagent '{reagent_name}' not found in this reaction.")

    def get_concentration(self, reagent_name):
        """Get the target concentration of a reagent in this reaction."""
        print(self.reagents)
        return self.reagents.get(reagent_name, None)

    def get_all_reagents(self):
        """Get all reagents and their concentrations in this reaction."""
        return self.reagents

    def __eq__(self, other):
        """Equality check to ensure unique reactions."""
        if not isinstance(other, ReactionComposition):
            return False
        return self.reagents == other.reagents

    def __hash__(self):
        """Hash function to allow use in sets and dictionaries."""
        return hash(frozenset(self.reagents.items()))

class ReactionCollection:
    def __init__(self):
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

    def get_reaction(self, name):
        """Get a reaction by its name."""
        return self.reactions.get(name, None)

    def get_all_reactions(self):
        """Get all reactions in the collection."""
        return list(self.reactions.values())
    
    def get_all_reagent_names(self):
        """Get a list of all reagent names across all reactions."""
        reagent_names = set()
        for reaction in self.get_all_reactions():
            reagent_names.update(reaction.get_all_reagents())
        return list(reagent_names)

    def find_duplicate(self, reaction):
        """Check if a similar reaction already exists in the collection."""
        for existing_reaction in self.reactions.values():
            if existing_reaction == reaction:
                return True
        return False
    
    def get_max_concentration(self, reagent_name):
        """Get the maximum concentration of a specific reagent across all reactions."""
        max_concentration = None
        for reaction in self.get_all_reactions():
            concentration = reaction.get_concentration(reagent_name)
            if concentration is not None:
                if max_concentration is None or concentration > max_concentration:
                    max_concentration = concentration
        return max_concentration
    
    def get_min_concentration(self, reagent_name):
        """Get the minimum concentration of a specific reagent across all reactions."""
        min_concentration = None
        for reaction in self.get_all_reactions():
            concentration = reaction.get_concentration(reagent_name)
            if concentration is not None:
                if min_concentration is None or concentration < min_concentration:
                    min_concentration = concentration
        return min_concentration
    
class Well:
    def __init__(self, well_id):
        self.well_id = well_id  # Unique identifier for the well (e.g., "A1", "B2")
        self.row = well_id[0]  # Row of the well (e.g., "A", "B")
        self.row_num = ord(self.row) - 65  # Row number (0-indexed, A=0, B=1)
        self.col = int(well_id[1:])  # Column of the well (e.g., 1, 2)
        self.assigned_reaction = None  # The reaction assigned to this well
        self.printed_droplets = {}  # Track the number of droplets printed for each reagent
        self.timestamp = None  # Timestamp when the well was last printed

    def assign_reaction(self, reaction):
        """Assign a reaction to the well."""
        if not isinstance(reaction, ReactionComposition):
            raise ValueError("Must assign a ReactionComposition object.")
        self.assigned_reaction = reaction

    def record_droplet(self, reagent_name, count):
        """Record the number of droplets printed for a specific reagent."""
        if reagent_name in self.printed_droplets:
            self.printed_droplets[reagent_name] += count
        else:
            self.printed_droplets[reagent_name] = count
        self.timestamp = QtCore.QDateTime.currentDateTime().toString(QtCore.Qt.ISODate)

    def get_status(self):
        """Get the status of the well."""
        return {
            "reaction": self.assigned_reaction.name if self.assigned_reaction else None,
            "printed_droplets": self.printed_droplets,
            "timestamp": self.timestamp,
        }

    def clear(self):
        """Clear the well's assigned reaction and status."""
        self.assigned_reaction = None
        self.printed_droplets.clear()
        self.timestamp = None

class WellPlate:
    def __init__(self, plate_format):
        self.plate_format = plate_format  # '96', '384', '1536'
        self.wells = self.create_wells()
        self.excluded_wells = set()

    def create_wells(self):
        """Create wells based on the plate format."""
        wells = []
        if self.plate_format == '96':
            rows = 'ABCDEFGH'
            cols = range(1, 13)
        elif self.plate_format == '384':
            rows = [chr(i) for i in range(65, 81)]  # A-P
            cols = range(1, 25)
        elif self.plate_format == '1536':
            rows = [chr(i) for i in range(65, 81)]  # A-P
            cols = range(1, 49)
        else:
            raise ValueError("Invalid plate format")

        for row in rows:
            for col in cols:
                well_id = f"{row}{col}"
                wells.append(Well(well_id))

        return wells

    def _get_plate_dimensions(self, format):
        """Return the dimensions (rows, cols) based on the plate format."""
        if format == "96":
            return 8, 12
        elif format == "384":
            return 16, 24
        elif format == "1536":
            return 32, 48
        else:
            raise ValueError("Unsupported plate format. Use '96', '384', or '1536'.")

    def exclude_well(self, well_id):
        """Exclude a well from being used."""
        if well_id in self.wells:
            self.excluded_wells.add(well_id)
        else:
            raise ValueError(f"Well '{well_id}' does not exist in the plate.")

    def include_well(self, well_id):
        """Include an excluded well back into use."""
        self.excluded_wells.discard(well_id)

    def assign_reaction_to_well(self, well_id, reaction):
        """Assign a reaction to a specific well."""
        if well_id in self.wells and well_id not in self.excluded_wells:
            self.wells[well_id].assign_reaction(reaction)
        else:
            raise ValueError(f"Cannot assign reaction to well '{well_id}'. It may be excluded or does not exist.")

    def get_well(self, well_id):
        """Retrieve a specific well by its ID."""
        return self.wells.get(well_id, None)

    def get_available_wells(self, fill_by="rows"):
        """
        Get a list of available wells, sorted by rows or columns.

        Args:
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            list of Well: Sorted list of available wells.
        """
        if fill_by not in ["rows", "columns"]:
            raise ValueError("fill_by must be 'rows' or 'columns'.")

        available_wells = [well for well in self.wells if well not in self.excluded_wells and well.assigned_reaction is None]

        if fill_by == "rows":
            available_wells.sort(key=lambda w: (w.row, w.col))
        else:  # fill_by == "columns"
            available_wells.sort(key=lambda w: (w.col, w.row))

        return available_wells
    
    def get_all_wells(self):
        """Get a list of all wells."""
        return list(self.wells)

    def clear_all_wells(self):
        """Clear all wells and reset their status."""
        for well in self.wells:
            well.clear()

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

class PrinterHead:
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

    def __init__(self, reagent,concentration,color):
        self.reagent = reagent
        self.concentration = concentration
        self.color = color
        self.confirmed = False
    
    def change_reagent(self, new_reagent):
        self.reagent = new_reagent

    def change_concentration(self, new_concentration):
        self.concentration = new_concentration
    
    def change_color(self, new_color):
        self.color = new_color

class Slot:
    """
    Represents a slot in a system.

    Attributes:
        number (int): The slot number.
        printer_head (PrinterHead): The printer head in the slot.
        confirmed (bool): Indicates if the slot has been confirmed.
    """

    def __init__(self, number, printer_head):
        self.number = number
        self.printer_head = printer_head
        self.confirmed = False
    
    def change_printer_head(self, new_printer_head):
        self.printer_head = new_printer_head
    
    def confirm(self):
        """
        Confirms the slot.
        """
        self.confirmed = True

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

    slot_updated = Signal(int)
    slot_confirmed = Signal(int)
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
            self.slots[slot_number].change_printer_head(printer_head)
            self.slot_updated.emit(slot_number)
            print(f"Slot {slot_number} updated with printer head: {printer_head.reagent}, {printer_head.concentration}, {printer_head.color}")

    def confirm_slot(self, slot_number):
        """
        Confirm a slot.

        Args:
        - slot_number (int): The slot number to confirm.
        """
        if 0 <= slot_number < len(self.slots):
            if self.slots[slot_number].printer_head is not None:
                self.slots[slot_number].confirm()
                self.slot_confirmed.emit(slot_number)
                self.gripper_updated.emit()
                print(f"Slot {slot_number} confirmed.")
            else:
                error_msg = f"Slot {slot_number} has no printer head to confirm."
                self.error_occurred.emit(error_msg)
                print(error_msg)

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
            slot.change_printer_head(None)
            self.slot_updated.emit(slot_number)
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
            slot.change_printer_head(self.gripper_printer_head)
            self.gripper_printer_head = None
            self.gripper_slot_number = None
            self.slot_updated.emit(slot_number)
            self.gripper_updated.emit()
            print(f"Printer head transferred from gripper to slot {slot_number}.")
        else:
            self.error_occurred.emit(error_msg)
            print(error_msg)

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
                "reagent": self.gripper_printer_head.reagent,
                "concentration": self.gripper_printer_head.concentration,
                "color": self.gripper_printer_head.color
            }
        return None

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


    def __init__(self):
        super().__init__()
        self.available_ports = []
        self.machine_connected = False
        self.balance_connected = False
        self.machine_port = "Virtual"
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

    def connect_machine(self, port):
        self.machine_port = port
        self.machine_connected = True
        self.machine_state_updated.emit(self.machine_connected)

    def disconnect_machine(self):
        self.machine_connected = False
        self.machine_state_updated.emit(self.machine_connected)

    def connect_balance(self, port):
        self.balance_port = port
        self.balance_connected = True
        self.balance_state_updated.emit(self.balance_connected)

    def disconnect_balance(self):
        self.balance_connected = False
        self.balance_state_updated.emit(self.balance_connected)

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
        
        print("Motors homed.")

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
        self.machine_model = MachineModel()
        self.num_slots = 5
        self.rack_model = RackModel(self.num_slots)
        self.location_model = LocationModel()
        self.location_model.load_locations()  # Load locations at startup
        self.well_plate = WellPlate("384")
        self.reaction_collection = ReactionCollection()

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
        reaction_collection = ReactionCollection()

        for _, row in df.iterrows():
            reaction_name = row['reaction_id']
            reaction = ReactionComposition(reaction_name)

            for reagent_name, concentration in row.items():
                if reagent_name != 'reaction_id':  # Skip the 'reaction_id' column
                    reaction.add_reagent(reagent_name, concentration)
            
            reaction_collection.add_reaction(reaction)

        return reaction_collection
    
    def load_experiment_from_file(self, file_path):
        """Load an experiment from a CSV file. Remove any existing experiment data."""
        if not file_path.endswith('.csv'):
            raise ValueError("Invalid file format. Please load a CSV file.")
        if len(self.reaction_collection.get_all_reactions()) > 0:
            self.reaction_collection = ReactionCollection()
            self.well_plate.clear_all_wells()
        self.reaction_collection = self.load_reactions_from_csv(file_path)
        self.well_plate.assign_reactions_to_wells(self.reaction_collection.get_all_reactions())
        self.experiment_loaded.emit()

    def update_well_plate(self,plate_format):
        self.well_plate = WellPlate(plate_format)
        if self.reaction_collection is not None:
            self.well_plate.assign_reactions_to_wells(self.reaction_collection.get_all_reactions())
            self.experiment_loaded.emit()
        else:
            print("No experiment data loaded.")