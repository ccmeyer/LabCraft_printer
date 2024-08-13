import pandas as pd
import numpy as np
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer
import json
import heapq
import os


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
    def __init__(self):
        super().__init__()
        self.machine_model = MachineModel()
        self.num_slots = 5
        self.rack_model = RackModel(self.num_slots)
        self.location_model = LocationModel()
        self.location_model.load_locations()  # Load locations at startup

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