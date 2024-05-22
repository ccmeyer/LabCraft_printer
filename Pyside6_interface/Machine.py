import threading
import time
from PySide6 import QtCore, QtWidgets, QtGui
from CustomWidgets import *



class BoardCommand():
    def __init__(self,command_number,command_type,param1,param2,param3):
        self.command_number = command_number
        self.command_type = command_type
        self.param1 = param1
        self.param2 = param2
        self.param3 = param3
        self.executed = False

class ControlBoard():
    def __init__(self,machine,simulate):
        """
        Initializes a ControlBoard object.

        Attributes:
            command_number: Current command number.
            command_queue: List containing the command queue.
            past_commands: List containing the executed commands.
            state: Current state of the machine (Free or Busy).
        """
        self.machine = machine
        self.command_queue = []
        self.current_command_number = 0
        self.last_completed_command_number = 0
        self.last_added_command_number = 0
        self.state = "Free"
        self.simulate = simulate

        self.motors_active = False
        self.x_pos = 0
        self.y_pos = 0
        self.z_pos = 0
        self.p_pos = 0
        self.correct_pos = True

        self.target_x = 0
        self.target_y = 0
        self.target_z = 0
        self.target_p = 0

        self.pressure = 0
        self.target_pressure = 0
        self.regulate_pressure = False
        self.correct_pressure = True

        self.total_droplets = 0

        self.gripper_open = False
        self.target_gripper_open = False
    
    def get_complete_state(self):
        if self.simulate:
            full_string = f'State:{self.state},Last_added:{self.last_added_command_number},Current_command:{self.current_command_number},Last_completed:{self.last_completed_command_number},X:{self.x_pos},Y:{self.y_pos},Z:{self.z_pos},P:{self.p_pos},Pressure:{self.pressure},Gripper:{self.gripper_open}'
            return full_string

    def check_for_command(self):
        if self.machine.sent_command is not None:
            self.add_command_to_queue(self.machine.sent_command.get_command())
            self.machine.sent_command = None
    
    def update_states(self):
        if self.motors_active:
            if self.z_pos < self.target_z:
                self.z_pos += 1
            elif self.z_pos > self.target_z:
                self.z_pos -= 1
            elif self.y_pos < self.target_y:
                self.y_pos += 1
            elif self.y_pos > self.target_y:
                self.y_pos -= 1
            elif self.x_pos < self.target_x:
                self.x_pos += 1
            elif self.x_pos > self.target_x:
                self.x_pos -= 1
            else:
                self.correct_pos = True
        else:
            self.correct_pos = True

        if self.regulate_pressure:
            if self.pressure < self.target_pressure:
                self.pressure += 1
            elif self.pressure > self.target_pressure:
                self.pressure -= 1
            else:
                self.correct_pressure = True
        else:
            self.correct_pressure = True

        if self.gripper_open != self.target_gripper_open:
            self.gripper_open = self.target_gripper_open
        if self.correct_pos and self.correct_pressure:
            self.state = "Free"
            self.last_completed_command_number = self.current_command_number
            self.execute_command_from_queue()
        
    def add_command_to_queue(self, command):
        new_command = self.convert_command(command)
        self.command_queue.append(new_command)

    def convert_command(self, command):
        [command_number,command_type,p1,p2,p3] = command[1:-1].split(',')
        self.last_added_command_number = int(command_number)
        return BoardCommand(command_number,command_type,p1,p2,p3)
    
    def execute_command_from_queue(self):
        for i,command in enumerate(self.command_queue):
            if not command.executed:
                self.current_command_number = int(command.command_number)
                self.execute_command(i)
                break            

    def execute_command(self,command_index):
        command = self.command_queue[command_index]
        print('Board Executing command:',command.command_type,command.param1,command.param2,command.param3)
        if command.command_type == 'RELATIVE_XYZ':
            self.correct_pos = False
            self.target_x += int(command.param1)
            self.target_y += int(command.param2)
            self.target_z += int(command.param3)
        elif command.command_type == 'ABSOLUTE_XYZ':
            self.correct_pos = False
            self.target_x = int(command.param1)
            self.target_y = int(command.param2)
            self.target_z = int(command.param3)
        elif command.command_type == 'RELATIVE_PRESSURE':
            self.correct_pressure = False
            self.target_pressure += int(command.param1)
        elif command.command_type == 'ABSOLUTE_PRESSURE':
            self.correct_pressure = False
            self.target_pressure = int(command.param1)
        elif command.command_type == 'REGULATE_PRESSURE':
            self.correct_pressure = False
            self.regulate_pressure = True
        elif command.command_type == 'DEREGULATE_PRESSURE':
            self.correct_pressure = True
            self.regulate_pressure = False
        elif command.command_type == 'OPEN_GRIPPER':
            self.target_gripper_open = True
        elif command.command_type == 'CLOSE_GRIPPER':
            self.target_gripper_open = False
        elif command.command_type == 'ENABLE_MOTORS':
            self.motors_active = True
        elif command.command_type == 'DISABLE_MOTORS':
            self.motors_active = False
        else:
            print('Unknown command:',command.command_type)
        self.command_queue[command_index].executed = True

class Command():
    def __init__(self, command_number,command_type,param1,param2,param3):
        """
        Initializes a Command object.

        Args:
            command_number (int): The number associated with the command.
            command_string (str): The command string.

        Attributes:
            command_number (int): The number associated with the command.
            command_string (str): The command string.
            executed (bool): Indicates whether the command has been executed.
            timestamp (float): The timestamp when the command was created.
        """
        self.command_number = command_number
        self.command_type = command_type
        self.param1 = param1
        self.param2 = param2
        self.param3 = param3
        self.signal = f'<{self.command_number},{command_type},{param1},{param2},{param3}>'
        self.executed = False
        self.timestamp = time.time()
    
    def get_number(self):
        return self.command_number
    
    def get_command(self):
        return self.signal
    
    def get_timestamp(self):
        return self.timestamp
    
    def execute(self):
        self.executed = True

class Machine(QtWidgets.QWidget):
    """
    Represents a machine with various functionalities such as controlling motors, gripper, reagents, and pressure regulation.

    Signals:
        - command_added: Signal emitted when a command is added to the command queue.
        - command_executed: Signal emitted when a command is executed from the command queue.

    Attributes:
        - main_window: Reference to the main window object.
        - machine_connected: Boolean indicating if the machine is connected.
        - balance_connected: Boolean indicating if the balance is connected.
        - motors_active: Boolean indicating if the motors are active.
        - x_pos: Current X-axis position.
        - y_pos: Current Y-axis position.
        - z_pos: Current Z-axis position.
        - p_pos: Current P-axis position.
        - coordinates: Dictionary containing the current coordinates (X, Y, Z, P).
        - target_x: Target X-axis position.
        - target_y: Target Y-axis position.
        - target_z: Target Z-axis position.
        - target_p: Target P-axis position.
        - target_coordinates: Dictionary containing the target coordinates (X, Y, Z, P).
        - current_pressure: Current pressure value.
        - target_pressure: Target pressure value.
        - pressure_log: List containing the pressure log history.
        - regulating_pressure: Boolean indicating if pressure regulation is active.
        - gripper_open: Boolean indicating if the gripper is open.
        - gripper_empty: Boolean indicating if the gripper is empty.
        - gripper_reagent: Reagent object representing the loaded reagent.
        - command_number: Current command number.
        - command_queue: List containing the command queue.
        - past_commands: List containing the executed commands.
        - state: Current state of the machine (Free or Busy).
    """

    command_added = QtCore.Signal(Command)
    command_sent = QtCore.Signal(Command)
    command_executed = QtCore.Signal(Command)
    command_completed = QtCore.Signal(Command)

    def __init__(self, main_window):
        super().__init__()
        print('Created Machine instance')
        self.main_window = main_window
        self.simulate = True
        self.board = ControlBoard(self,self.simulate)

        self.machine_connected = False
        self.balance_connected = False
        self.motors_active = False
        self.x_pos = 0
        self.y_pos = 0
        self.z_pos = 0
        self.p_pos = 0
        self.coordinates = {'X': self.x_pos, 'Y': self.y_pos, 'Z': self.z_pos, 'P': self.p_pos}
        self.location = 'Unknown'

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
        self.command_queue = []
        self.last_added_command_number = 0
        self.current_command_number = 0
        self.last_completed_command_number = 0
        self.sent_command = None
        self.state = "Free"

        self.calibration_file_path = './Calibrations/default_positions.json'
        self.calibration_data = {}

    def add_command_to_queue(self, command_type, param1, param2, param3,):
        new_command = Command(self.command_number, command_type=command_type, param1=param1, param2=param2, param3=param3)
        self.command_queue.append(new_command)
        self.command_added.emit(new_command)
        self.command_number += 1

    def execute_command_from_queue(self):
        if self.sent_command == None:
            if self.last_added_command_number < self.last_completed_command_number + 3:
                for command in self.command_queue:
                    if not command.executed:
                        print('Executing command:',command.get_command())
                        self.send_command_to_board(command)
                        self.update_targets_from_command(command)
                        self.command_sent.emit(command)
                        break                

    def update_targets_from_command(self,command):
        if command.command_type == 'RELATIVE_XYZ':
            self.target_coordinates['X'] += int(command.param1)
            self.target_coordinates['Y'] += int(command.param2)
            self.target_coordinates['Z'] += int(command.param3)
        elif command.command_type == 'ABSOLUTE_XYZ':
            self.target_coordinates['X'] = int(command.param1)
            self.target_coordinates['Y'] = int(command.param2)
            self.target_coordinates['Z'] = int(command.param3)
        elif command.command_type == 'RELATIVE_PRESSURE':
            self.target_pressure += int(command.param1)
        elif command.command_type == 'ABSOLUTE_PRESSURE':
            self.target_pressure = int(command.param1)
        elif command.command_type == 'REGULATE_PRESSURE':
            self.regulating_pressure = True
        elif command.command_type == 'DEREGULATE_PRESSURE':
            self.regulating_pressure = False
        elif command.command_type == 'OPEN_GRIPPER':
            self.gripper_open = True
        elif command.command_type == 'CLOSE_GRIPPER':
            self.gripper_open = False
        elif command.command_type == 'ENABLE_MOTORS':
            self.motors_active = True
        elif command.command_type == 'DISABLE_MOTORS':
            self.motors_active = False
        else:
            print('Unknown command:',command.command_type)

    def send_command_to_board(self,command):
        if self.simulate:
            self.sent_command = command
            command.execute()

    def get_state_from_board(self):
        signal = self.board.get_complete_state()
        self.update_state(self.convert_state(signal))
        return signal
    
    def convert_state(self, state):
        state_dict = {}
        state_list = state.split(',')
        for item in state_list:
            key,value = item.split(':')
            state_dict[key] = value
        return state_dict
    
    def update_state(self, state):
        self.state = state['State']
        self.last_added_command_number = int(state['Last_added'])
        self.current_command_number = int(state['Current_command'])
        self.last_completed_command_number = int(state['Last_completed'])
        self.x_pos = int(state['X'])
        self.y_pos = int(state['Y'])
        self.z_pos = int(state['Z'])
        self.p_pos = int(state['P'])
        self.coordinates = {'X': self.x_pos, 'Y': self.y_pos, 'Z': self.z_pos, 'P': self.p_pos}
        self.current_pressure = int(state['Pressure'])
        self.gripper_open = state['Gripper']

        self.pressure_log.append(self.current_pressure)
        if len(self.pressure_log) > 100:
            self.pressure_log.pop(0)  # Remove the oldest reading
        if self.command_queue != []:
            if self.current_command_number == self.last_completed_command_number:
                self.command_completed.emit(self.command_queue[self.current_command_number])
            else:
                self.command_executed.emit(self.command_queue[self.current_command_number])

    def enable_motors(self):
        self.add_command_to_queue('ENABLE_MOTORS',0,0,0)
        return
    
    def disable_motors(self):
        self.add_command_to_queue('DISABLE_MOTORS',0,0,0)
        return

    def set_absolute_coordinates(self,x,y,z):
        self.add_command_to_queue('ABSOLUTE_XYZ',x,y,z)
        return
    
    def set_relative_coordinates(self,x,y,z):
        self.add_command_to_queue('RELATIVE_XYZ',x,y,z)
        return
    
    def set_absolute_pressure(self,pressure):
        self.add_command_to_queue('ABSOLUTE_PRESSURE',pressure,0,0)
        return
    
    def set_relative_pressure(self,pressure):
        self.add_command_to_queue('RELATIVE_PRESSURE',pressure,0,0)
        return
    
    def regulate_pressure(self):
        self.add_command_to_queue('REGULATE_PRESSURE',0,0,0)
        return
    
    def deregulate_pressure(self):
        self.add_command_to_queue('DEREGULATE_PRESSURE',0,0,0)
        return
    


    # def load_positions_from_file(self):
    #     with open(self.calibration_file_path, 'r') as file:
    #         self.calibration_data = json.load(file)

    # def move_to_location(self,location=False,direct=False,safe_y=False):
    #     '''
    #     Tells the robot to move to a location based on the defined coordinates in the calibration file.
    #     If direct is set to True, the robot will move directly to the location. If safe_y is set to True, 
    #     the robot will move to the safe_y position before moving to the location to avoid running into an obsticle.
    #     '''
    #     if self.motors_active == False:
    #         print('Motors must be active')
    #         return
    #     print('Current',self.location)
    #     if not location:
    #         location = self.main_window.popup_options('Move to Location','Select location:',list(self.calibration_data.keys()))

    #     if self.location == location:
    #         print('Already in {} position'.format(location))
    #         return
    #     available_locations = list(self.calibration_data.keys())
    #     if location not in available_locations:
    #         self.main_window.popup_message('Location not present','{} not present in calibration data'.format(location))
    #         return
        
    #     if location == 'balance' or self.location == 'balance':
    #         safe_y = True
    #         direct = False

    #     target_coordinates = self.calibration_data[location].copy()
        
    #     if 'rack_position' in location:
    #         print('Moving to rack position:',location,'Applying X offset')
    #         target_coordinates['x'] += self.rack_offset
    #     else:
    #         print('Moving to:',location)

    #     up_first = False
    #     if direct and self.z_pos < target_coordinates['z']:
    #         up_first = True
    #         self.set_absolute_coordinates(self.x_pos, self.y_pos, target_coordinates['z'])

    #     x_limit = -5500
    #     if self.x_pos > x_limit and target_coordinates['x'] < x_limit or self.x_pos < x_limit and target_coordinates['x'] > x_limit:
    #         safe_y = True

    #     if direct and not safe_y:
    #         self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
    #     elif not direct and not safe_y:
    #         self.set_absolute_coordinates(self.x_pos, self.y_pos, self.height)
    #         self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], self.height)
    #         self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], self.target_coordinates['z'])
    #     elif not direct and safe_y:
    #         self.set_absolute_coordinates(self.x_pos, self.y_pos, self.height)
    #         self.set_absolute_coordinates(self.x_pos, self.safe_y, self.height)
    #         self.set_absolute_coordinates(target_coordinates['x'], self.safe_y, self.height)
    #         self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], self.height)
    #         self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
    #     elif direct and safe_y:
    #         if up_first:
    #             self.set_absolute_coordinates(self.x_pos, self.safe_y, target_coordinates['z'])
    #             self.set_absolute_coordinates(target_coordinates['x'], self.safe_y, target_coordinates['z'])
    #             self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
    #         else:
    #             self.set_absolute_coordinates(self.x_pos, self.safe_y, self.z_pos)
    #             self.set_absolute_coordinates(target_coordinates['x'], self.safe_y, self.z_pos)
    #             self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], self.z_pos)
    #             self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
    #     self.location = location
    #     return


    








    # def activate_motors(self):
    #     self.motors_active = True
    #     self.add_command_to_queue('ENABLE_MOTORS')

    # def deactivate_motors(self):
    #     self.motors_active = False
    #     self.add_command_to_queue('DISABLE_MOTORS')
    
    # def open_gripper(self):
    #     self.gripper_open = True
    #     self.add_command_to_queue('OPEN_GRIPPER')
    
    # def close_gripper(self):
    #     self.gripper_open = False
    #     self.add_command_to_queue('CLOSE_GRIPPER')

    # def get_gripper_state(self):
    #     return self.gripper_open
    
    # def get_loaded_reagent(self):
    #     return self.loaded_reagent
    
    # def move_to_slot(self, slot_number):
    #     if self.motors_active:
    #         self.add_command_to_queue(f'MOVE_TO_SLOT_{slot_number}')
    #     else:
    #         self.main_window.print_status('Motors are not active')
    
    # def move_to_print(self):
    #     if self.motors_active:
    #         self.add_command_to_queue(f'MOVE_TO_PRINT')
    #     else:
    #         self.main_window.print_status('Motors are not active')

    # def pick_up_reagent(self, slot):
    #     if self.motors_active:
    #         self.open_gripper()
    #         self.move_to_slot(slot.number)
    #         self.close_gripper()
    #         self.loaded_reagent = slot.reagent
    #         self.move_to_print()
    #     else:
    #         self.main_window.print_status('Motors are not active')
    
    # def drop_reagent(self,slot):
    #     if self.motors_active:
    #         self.move_to_slot(slot.number)
    #         self.open_gripper()
    #         self.loaded_reagent = None
    #         self.move_to_print()
    #         self.close_gripper()
    #     else:
    #         self.main_window.print_status('Motors are not active')

    def get_coordinates(self):
        return self.coordinates
    
    def get_target_coordinates(self):
        return self.target_coordinates
    
    # def move_relative(self, relative_coordinates):
    #     if self.motors_active:
    #         for axis in ['X', 'Y', 'Z', 'P']:
    #             self.target_coordinates[axis] += relative_coordinates[axis]
    #         self.add_command_to_queue(f'RELATIVE_XYZ,{relative_coordinates["X"]},{relative_coordinates["Y"]},{relative_coordinates["Z"]}')

    # def move_absolute(self, target_coordinates):
    #     if self.motors_active:
    #         for axis in ['X', 'Y', 'Z', 'P']:
    #             self.target_coordinates[axis] = target_coordinates[axis]
    #         self.add_command_to_queue(f'ABSOLUTE_XYZ,{target_coordinates["X"]},{target_coordinates["Y"]},{target_coordinates["Z"]}')
    
    # def set_relative_pressure(self, pressure_change):
    #     self.target_pressure += pressure_change
    #     self.add_command_to_queue(f'RELATIVE_PRESSURE,{pressure_change}')
    
    def get_target_pressure(self):
        return self.target_pressure
    
    def get_pressure_log(self):
        return self.pressure_log

    # def regulate_pressure(self):
    #     self.regulating_pressure = True
    #     self.add_command_to_queue('REGULATE_PRESSURE')

    # def deregulate_pressure(self):
    #     self.regulating_pressure = False
    #     self.add_command_to_queue('DEGULATE_PRESSURE')
    
    def get_regulation_state(self):
        return self.regulating_pressure

    def get_command_number(self):
        return self.command_number
    
    def get_command_log(self):
        return self.command_queue
    
    # def add_command_to_queue(self, command):
    #     new_command = Command(self.command_number, command)
    #     self.command_queue.append(new_command)
    #     self.command_added.emit(new_command)
    #     print('Command added:', command)
    #     self.command_number += 1

    # def execute_command_from_queue(self):
    #     for command in self.command_queue:
    #         if not command.executed:
    #             print('Command executed:', command.get_command())
    #             command.execute()  # Set the command as executed
    #             self.command_executed.emit(command)
    #             break  # Exit the loop after executing a command
    
    
    # def check_board(self):
    #     self.update_state(self.convert_state(self.get_state_from_board()))

    # def update_states(self):
    #     if self.motors_active:
    #         for axis in ['X', 'Y', 'Z', 'P']:
    #             if self.coordinates[axis] < self.target_coordinates[axis]:
    #                 self.coordinates[axis] += 1
    #             elif self.coordinates[axis] > self.target_coordinates[axis]:
    #                 self.coordinates[axis] -= 1
    #     if self.regulating_pressure:
    #         if self.current_pressure < self.target_pressure:
    #             self.current_pressure += 1
    #         elif self.current_pressure > self.target_pressure:
    #             self.current_pressure -= 1

    #     # Check if all coordinates and pressure equal their target values
    #     if (self.coordinates == self.target_coordinates and
    #         self.current_pressure == self.target_pressure):
    #         self.state = "Free"
    #     else:
    #         self.state = "Busy"

    #     if self.state == "Free":
    #         self.main_window.print_status('Machine is idle')
    #         self.execute_command_from_queue()

    #     self.pressure_log.append(self.current_pressure)
    #     if len(self.pressure_log) > 100:
    #         self.pressure_log.pop(0)  # Remove the oldest reading
