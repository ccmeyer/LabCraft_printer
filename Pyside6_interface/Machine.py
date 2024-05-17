import threading
import time
from PySide6 import QtCore, QtWidgets, QtGui
from CustomWidgets import *

class Command():
    def __init__(self,command_number, command_string):
        self.command_number = command_number
        self.command_string = command_string
        self.executed = False
        self.timestamp = time.time()
    
    def get_number(self):
        return self.command_number
    
    def get_command(self):
        return self.command_string
    
    def get_timestamp(self):
        return self.timestamp
    
    def execute(self):
        self.executed = True

class Machine(QtWidgets.QWidget):
    command_added = QtCore.Signal(Command)
    command_executed = QtCore.Signal(Command)

    def __init__(self, main_window):
        super().__init__()
        print('Created Machine instance')
        self.main_window = main_window
        self.machine_connected = False
        self.balance_connected = False
        self.motors_active = False
        self.x_pos = 0
        self.y_pos = 0
        self.z_pos = 0
        self.p_pos = 0
        self.coordinates = {'X': self.x_pos, 'Y': self.y_pos, 'Z': self.z_pos, 'P': self.p_pos}
        
        self.target_x = 0
        self.target_y = 0
        self.target_z = 0
        self.target_p = 0
        self.target_coordinates = {'X': self.target_x, 'Y': self.target_y, 'Z': self.target_z, 'P': self.target_p}

        self.current_pressure = 0
        self.target_pressure = 0
        self.pressure_log = [0]
        self.regulating_pressure = False

        self.gripper_open = False
        self.gripper_empty = True
        self.gripper_reagent = Reagent("Empty", self.main_window.colors, "dark_gray")

        self.command_number = 0
        self.command_queue = [Command(0, 'INITIALIZE')]
        self.past_commands = []
        self.command_number += 1
        self.state = "Free"

    def activate_motors(self):
        self.motors_active = True
        self.add_command_to_queue('ENABLE_MOTORS')

    def deactivate_motors(self):
        self.motors_active = False
        self.add_command_to_queue('DISABLE_MOTORS')
    
    def open_gripper(self):
        self.gripper_open = True
        self.add_command_to_queue('OPEN_GRIPPER')
    
    def close_gripper(self):
        self.gripper_open = False
        self.add_command_to_queue('CLOSE_GRIPPER')

    def get_gripper_state(self):
        return self.gripper_open
    
    def get_loaded_reagent(self):
        return self.loaded_reagent
    
    def move_to_slot(self, slot_number):
        if self.motors_active:
            self.add_command_to_queue(f'MOVE_TO_SLOT_{slot_number}')
        else:
            self.main_window.print_status('Motors are not active')
    
    def move_to_print(self):
        if self.motors_active:
            self.add_command_to_queue(f'MOVE_TO_PRINT')
        else:
            self.main_window.print_status('Motors are not active')

    def pick_up_reagent(self, slot):
        if self.motors_active:
            self.open_gripper()
            self.move_to_slot(slot.number)
            self.close_gripper()
            self.loaded_reagent = slot.reagent
            self.move_to_print()
        else:
            self.main_window.print_status('Motors are not active')
    
    def drop_reagent(self,slot):
        if self.motors_active:
            self.move_to_slot(slot.number)
            self.open_gripper()
            self.loaded_reagent = None
            self.move_to_print()
            self.close_gripper()
        else:
            self.main_window.print_status('Motors are not active')

    def get_coordinates(self):
        return self.coordinates
    
    def get_target_coordinates(self):
        return self.target_coordinates
    
    def move_relative(self, relative_coordinates):
        if self.motors_active:
            for axis in ['X', 'Y', 'Z', 'P']:
                self.target_coordinates[axis] += relative_coordinates[axis]
            self.add_command_to_queue(f'RELATIVE_XYZ,{relative_coordinates["X"]},{relative_coordinates["Y"]},{relative_coordinates["Z"]}')
    
    
    def set_relative_pressure(self, pressure_change):
        self.target_pressure += pressure_change
        self.add_command_to_queue(f'RELATIVE_PRESSURE,{pressure_change}')
    
    def get_target_pressure(self):
        return self.target_pressure
    
    def get_pressure_log(self):
        return self.pressure_log

    def regulate_pressure(self):
        self.regulating_pressure = True
        self.add_command_to_queue('REGULATE_PRESSURE')

    def deregulate_pressure(self):
        self.regulating_pressure = False
        self.add_command_to_queue('DEGULATE_PRESSURE')
    
    def get_regulation_state(self):
        return self.regulating_pressure

    def get_command_number(self):
        return self.command_number
    
    def get_command_log(self):
        return self.command_queue
    
    def add_command_to_queue(self, command):
        new_command = Command(self.command_number, command)
        self.command_queue.append(new_command)
        self.command_added.emit(new_command)
        print('Command added:', command)
        self.command_number += 1

    def execute_command_from_queue(self):
        for command in self.command_queue:
            if not command.executed:
                print('Command executed:', command.get_command())
                command.execute()  # Set the command as executed
                self.command_executed.emit(command)
                break  # Exit the loop after executing a command

    def update_states(self):
        if self.motors_active:
            for axis in ['X', 'Y', 'Z', 'P']:
                if self.coordinates[axis] < self.target_coordinates[axis]:
                    self.coordinates[axis] += 1
                elif self.coordinates[axis] > self.target_coordinates[axis]:
                    self.coordinates[axis] -= 1
        if self.regulating_pressure:
            if self.current_pressure < self.target_pressure:
                self.current_pressure += 1
            elif self.current_pressure > self.target_pressure:
                self.current_pressure -= 1

        # Check if all coordinates and pressure equal their target values
        if (self.coordinates == self.target_coordinates and
            self.current_pressure == self.target_pressure):
            self.state = "Free"
        else:
            self.state = "Busy"

        if self.state == "Free":
            self.main_window.print_status('Machine is idle')
            self.execute_command_from_queue()

        self.pressure_log.append(self.current_pressure)
        if len(self.pressure_log) > 100:
            self.pressure_log.pop(0)  # Remove the oldest reading
