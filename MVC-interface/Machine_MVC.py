import threading
import time
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer
from collections import deque

import serial
import re
import json
import cv2
import numpy as np

class Balance():
    def __init__(self,machine):
        self.machine = machine
        self.connected = False
        self.port = None
        self.simulate = True
        self.error_count = 0
        self.current_mass = 0
        self.target_mass = 0
        self.mass_update_timer = None
        self.mass_log = []

    def is_connected(self):
        return self.connected

    def connect_balance(self,port):
        if port == 'Virtual':
            self.connected = True
            self.simulate = True
            self.mass_update_timer = QtCore.QTimer()
            self.mass_update_timer.timeout.connect(self.update_simulated_mass)
            self.mass_update_timer.start(25)
            self.show_connection()
            self.begin_reading()
            return True
        try:
            self.port = serial.Serial(port, baudrate=9600, bytesize=8, timeout=2, stopbits=serial.STOPBITS_ONE)
            if not self.port.is_open:  # Add this line
                raise serial.SerialException('Could not open port')  # Add this line
            self.connected = True
            self.simulate = False
            self.show_connection()
            self.begin_reading()
            return True
        except:
            self.main_window.popup_message('Connection error',f'Could not connect to balance at port {port}')
            self.connected = False
            return False
        
    def close_connection(self):
        if not self.simulate:
            self.port.close()
        else:
            self.mass_update_timer.stop()
        if self.mass_update_timer is not None:
            self.mass_update_timer.stop()
        self.connected = False
        return

    def show_connection(self):
        print('Balance connected')

    def get_mass(self):
        if not self.simulate:
            if self.port.in_waiting > 0:
                data = self.port.readline()
                try:
                    data = data.decode("ASCII")
                    # print('Data:',data)
                    [sign,mass] = re.findall(r'(-?) *([0-9]+\.[0-9]+) [a-zA-Z]*',data)[0]
                    mass = float(''.join([sign,mass]))
                    self.current_mass = mass
                    self.add_to_log(self.current_mass)
                except Exception as e:
                    print(f'--Error {e} reading from balance')
                    self.error_count += 1
                    if self.error_count > 100:
                        self.close_connection()
                        self.main_window.popup_message('Connection error','Lost connection to balance')
                    
        else:
            self.add_to_log(self.current_mass)
        
    def begin_reading(self):
        self.mass_update_timer = QtCore.QTimer()
        self.mass_update_timer.timeout.connect(self.get_mass)
        self.mass_update_timer.start(10)

    def add_to_log(self,mass):
        self.mass_log.append(mass)
        if len(self.mass_log) > 100:
            self.mass_log.pop(0)

    def get_recent_mass(self):
        if self.mass_log != []:
            return self.mass_log[-1]
        else:
            return 0

    def simulate_mass(self,num_droplets,psi):
        # Reference points
        ref_droplets = 100
        ref_points = np.array([
            [1.8, 3],
            [2.2, 4],
        ])

        # Calculate the linear fit for the reference points
        coefficients = np.polyfit(ref_points[:, 0], ref_points[:, 1] / ref_droplets, 1)
        print('Coefficients:',coefficients)
        # Calculate the mass per droplet for the given pressure
        mass_per_droplet = coefficients[0] * psi + coefficients[1]
        for point in ref_points:
            print('Point:',point[0],point[1],coefficients[0] * point[0] + coefficients[1])
        # Calculate the mass for the given number of droplets
        mass = mass_per_droplet * num_droplets

        return mass
    
    def update_simulated_mass(self):
        if self.machine.balance_droplets != []:
            print('Balance droplets:',self.machine.balance_droplets)
            [num_droplets,psi] = self.machine.balance_droplets.pop(0)
            print('Found balance droplets',num_droplets,psi)
            mass = self.simulate_mass(num_droplets,psi)
            print('Simulated mass:',mass,self.current_mass,self.target_mass)
            self.target_mass += mass
        
        if self.current_mass < self.target_mass:
            self.current_mass += 0.01

class BoardCommand():
    """
    Represents a command to be executed on the board.

    Attributes:
        command_number (int): The number of the command.
        command_type (str): The type of the command.
        param1 (any): The first parameter of the command.
        param2 (any): The second parameter of the command.
        param3 (any): The third parameter of the command.
        executed (bool): Indicates whether the command has been executed.
    """

    def __init__(self, command_number, command_type, param1, param2, param3):
        self.command_number = command_number
        self.command_type = command_type
        self.param1 = param1
        self.param2 = param2
        self.param3 = param3
        self.executed = False

class VirtualMachine():
    def __init__(self,machine):
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
        self.wait_flag = False
        self.wait_time = 0
        self.pause = False
        self.initial_time = 0
        self.state = "Free"
        self.com_open = True
        self.max_cycle = 300
        self.cycle_count = 10000

        self.board_check_timer = QTimer()
        self.board_check_timer.timeout.connect(self.check_for_command)
        self.board_check_timer.start(20)  # Update every 20 ms
        
        self.board_update_timer = QTimer()
        self.board_update_timer.timeout.connect(self.update_states)
        self.board_update_timer.start(10)  # Update every 20 ms

        self.motors_active = False
        self.x_pos = 0
        self.y_pos = 0
        self.z_pos = 0
        self.p_pos = 0
        self.x_correct = False
        self.y_correct = False
        self.z_correct = False

        self.correct_pos = True
        self.xy_speed = 50
        self.z_speed = 50

        self.target_x = 0
        self.target_y = 0
        self.target_z = 0
        self.target_p = 0

        self.pressure = 1638
        self.target_pressure = 1638
        self.regulate_pressure = False
        self.correct_pressure = True

        self.current_droplets = 0
        self.target_droplets = 0
        self.correct_droplets = True

        self.gripper_active = False
        self.gripper_open = False
        self.target_gripper_open = False
        self.correct_gripper = True
    
    def pause_commands(self):
        self.state = "Paused"
        self.pause = True
        
    def resume_commands(self):
        self.state = "Free"
        self.pause = False

    def clear_command_queue(self):
        # new_command_queue = [command for command in self.command_queue if command.executed]
        self.command_queue = []
        self.current_command_number = 0
        self.last_completed_command_number = 0
        self.last_added_command_number = 0
        self.state = "Free"
        self.pause = False

        self.target_x = self.x_pos
        self.target_y = self.y_pos
        self.target_z = self.z_pos
        self.target_pressure = self.pressure
        self.target_gripper_open = self.gripper_open
        self.target_droplets = self.current_droplets

    
    def get_complete_state(self):
        # if self.simulate:
        full_string = (
            f'State:{self.state},'
            f'Com_open:{self.com_open},'
            f'Last_added:{self.last_added_command_number},'
            f'Current_command:{self.current_command_number},'
            f'Last_completed:{self.last_completed_command_number},'
            f'X:{self.x_pos},'
            f'Y:{self.y_pos},'
            f'Z:{self.z_pos},'
            f'P:{self.p_pos},'
            f'Tar_X:{self.target_x},'
            f'Tar_Y:{self.target_y},'
            f'Tar_Z:{self.target_z},'
            f'Tar_P:{self.target_p},'
            f'Pressure:{self.pressure},'
            f'Tar_pressure:{self.target_pressure},'
            f'Gripper:{self.gripper_open},'
            f'Droplets:{self.current_droplets},'
            f'Max_cycle:{self.max_cycle},'
            f'Cycle_count:{self.cycle_count}'
        )
        return full_string

    def check_for_command(self):
        if self.machine.sent_command is not None:
            self.add_command_to_queue(self.machine.sent_command.get_command())
            self.machine.sent_command = None
    
    def update_states(self):
        if self.pause:
            return
        if self.wait_flag:
            if time.time() - self.initial_time > self.wait_time:
                self.wait_flag = False
            else:
                return
        if self.motors_active:
            self.x_correct = False
            self.y_correct = False
            self.z_correct = False

            if abs(self.y_pos - self.target_y) < self.xy_speed:
                self.y_pos = self.target_y
                self.y_correct = True
            elif self.y_pos < self.target_y:
                self.y_pos += self.xy_speed
            elif self.y_pos > self.target_y:
                self.y_pos -= self.xy_speed

            # Only move the X axis if the Y axis has reached its target position
            if self.y_correct:
                if abs(self.x_pos - self.target_x) < self.xy_speed:
                    self.x_pos = self.target_x
                    self.x_correct = True
                elif self.x_pos < self.target_x:
                    self.x_pos += self.xy_speed
                elif self.x_pos > self.target_x:
                    self.x_pos -= self.xy_speed

            # Only move the Z axis if the X and Y axes have reached their target positions
            if self.x_correct and self.y_correct:
                if abs(self.z_pos - self.target_z) < self.z_speed:
                    self.z_pos = self.target_z
                    self.z_correct = True
                elif self.z_pos < self.target_z:
                    self.z_pos += self.z_speed
                elif self.z_pos > self.target_z:
                    self.z_pos -= self.z_speed

            if self.x_correct and self.y_correct and self.z_correct:
                self.correct_pos = True
        else:
            self.correct_pos = True

        if self.regulate_pressure:
            if abs(self.pressure - self.target_pressure) < 5:
                self.pressure = self.target_pressure
                self.correct_pressure = True
            elif self.pressure < self.target_pressure:
                self.pressure += 5
            elif self.pressure > self.target_pressure:
                self.pressure -= 5
        else:
            self.correct_pressure = True

        if self.correct_pos and self.correct_pressure:
            if self.gripper_open != self.target_gripper_open:
                self.gripper_open = self.target_gripper_open
            else:
                self.correct_gripper = True

        if self.correct_pos and self.correct_pressure and self.correct_gripper:
            if self.current_droplets < self.target_droplets:
                self.current_droplets += 1
            else:
                self.correct_droplets = True

        self.max_cycle += np.random.randint(-10,10)
        self.cycle_count += np.random.randint(-10,10)

        if self.correct_pos and self.correct_pressure and self.correct_gripper and self.correct_droplets:
            self.state = "Free"
            self.last_completed_command_number = self.current_command_number
            self.execute_command_from_queue()
        
    def add_command_to_queue(self, command):            
        new_command = self.convert_command(command)
        if new_command.command_type == 'PAUSE':
            self.pause_commands()
            print('Received pause command')
        elif new_command.command_type == 'RESUME':
            self.resume_commands()
            print('Received resume command')
        elif new_command.command_type == 'CLEAR_QUEUE':
            self.clear_command_queue()
            print('Received clear command')
        else:
            self.command_queue.append(new_command)

    def convert_command(self, command):
        [command_number,command_type,p1,p2,p3] = command[1:-1].split(',')
        self.last_added_command_number = int(command_number)
        return BoardCommand(command_number,command_type,p1,p2,p3)
    
    def execute_command_from_queue(self):
        if self.state == "Free":
            for i,command in enumerate(self.command_queue):
                if not command.executed:
                    self.current_command_number = int(command.command_number)
                    self.execute_command(i)
                    self.command_queue[i].executed = True
                    self.command_queue.pop(i)
                    self.state = "Busy"
                    break            

    def execute_command(self,command_index):
        command = self.command_queue[command_index]
        print('Board Executing command:',command.command_number,command.command_type,command.param1,command.param2,command.param3,command.executed)
        if command.command_type == 'RELATIVE_XYZ':
            self.correct_pos = False
            self.correct_x = False
            self.correct_y = False
            self.correct_z = False

            self.target_x += int(command.param1)
            self.target_y += int(command.param2)
            self.target_z += int(command.param3)
        elif command.command_type == 'ABSOLUTE_XYZ':
            self.correct_pos = False
            self.correct_x = False
            self.correct_y = False
            self.correct_z = False

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
            if not self.gripper_active:
                self.gripper_active = True
            self.target_gripper_open = True
        elif command.command_type == 'CLOSE_GRIPPER':
            if not self.gripper_active:
                self.gripper_active = True
            self.target_gripper_open = False
        elif command.command_type == 'GRIPPER_OFF':
            self.gripper_active = False
        elif command.command_type == 'ENABLE_MOTORS':
            self.motors_active = True
        elif command.command_type == 'DISABLE_MOTORS':
            self.motors_active = False
        elif command.command_type == 'WAIT':
            self.wait_time = int(command.param1) / 1000
            self.initial_time = time.time()
            self.wait_flag = True
        elif command.command_type == 'PRINT':
            self.correct_droplets = False
            self.target_droplets = int(command.param1)
        elif command.command_type == 'RESET_P':
            self.p_pos = 0
        elif command.command_type == 'HOME_ALL':
            self.x_pos = 0
            self.y_pos = 0
            self.z_pos = 0
            self.p_pos = 0
            self.target_x = 0
            self.target_y = 0
            self.target_z = 0
            self.target_p = 0
        elif command.command_type == 'CHANGE_ACCEL':
            print('Changing acceleration')

        else:
            print('Unknown command:',command.command_type)
        self.correct_pos = False
        self.correct_pressure = False
        self.correct_gripper = False
        # self.command_queue[command_index].executed = True
        self.state = "Busy"

class Command:
    """
    Represents a command to be sent to the machine.
    
    Attributes:
    command_number (int): The number of the command.
    command_type (str): The type of the command.
    param1: The first parameter of the command.
    param2: The second parameter of the command.
    param3: The third parameter of the command.
    handler (function, optional): The handler function for the command.
    kwargs (dict, optional): Additional keyword arguments for the handler function.
    """
    def __init__(self, command_number, command_type, param1, param2, param3, handler=None, kwargs=None):
        self.command_number = command_number
        self.command_type = command_type
        self.param1 = param1
        self.param2 = param2
        self.param3 = param3
        self.signal = f'<{self.command_number},{command_type},{param1},{param2},{param3}>'
        self.status = "Added"
        self.timestamp = time.time()
        self.handler = handler
        self.kwargs = kwargs if kwargs is not None else {}

    def mark_as_sent(self):
        self.status = "Sent"

    def mark_as_executing(self):
        self.status = "Executing"

    def mark_as_completed(self):
        self.status = "Completed"
        self.execute_handler()

    def get_number(self):
        return self.command_number

    def get_command(self):
        return self.signal

    def get_timestamp(self):
        return self.timestamp

    def execute_handler(self):
        if self.handler is not None:
            self.handler(**self.kwargs)


class CommandQueue(QObject):
    """
    Represents a queue of commands to be sent to the machine.
    Uses deque to store the commands.
    Completed commands are transferred to the completed queue.
    """
    queue_updated = Signal()  # Signal to emit when the queue is updated

    def __init__(self):
        super().__init__()  # Initialize the QObject
        self.queue = deque()
        self.completed = deque()
        self.command_number = 0
        self.max_sent_commands = 3  # Maximum number of commands that can be sent to the machine at once

    def add_command(self, command_type, param1, param2, param3, handler=None, kwargs=None):
        """Add a command to the queue."""
        self.command_number += 1
        command = Command(self.command_number, command_type, param1, param2, param3, handler, kwargs)
        self.queue.append(command)
        return command

    def get_number_of_sent_commands(self):
        """Returns the number of commands that have been sent to the machine."""
        return len([command for command in self.queue if command.status == "Sent"])

    def get_next_command(self):
        """Send the next command to the machine if the buffer allows."""
        if self.queue and self.get_number_of_sent_commands() < self.max_sent_commands:
            for command in self.queue:
                if command.status == "Added":
                    command.mark_as_sent()
                    return command
        return None

    def update_command_status(self, current_executing_command, last_completed_command):
        """Update command statuses based on the machine's current state."""
        if current_executing_command is None or last_completed_command is None:
            print('No commands to update')
            return
        for command in self.queue:
            if command.status == "Sent" and command.command_number == int(current_executing_command):
                command.mark_as_executing()
            if command.command_number <= int(last_completed_command):
                command.mark_as_completed()

        # Remove completed commands from the queue
        while self.queue and self.queue[0].status == "Completed":
            completed_command = self.queue.popleft()
            print(f"Command '{completed_command.command_type}' completed and removed from queue.")
            self.completed.append(completed_command)

        self.queue_updated.emit()
    

class Machine(QObject):
    """
    Class for the machine object. This class is responsible for 
    sending and receiving data from the machine and organizing
    the command queue.
    """
    status_updated = Signal(dict)  # Signal to emit status updates
    command_sent = Signal(dict)    # Signal to emit when a command is sent
    error_occurred = Signal(str)   # Signal to emit errors

    def __init__(self):
        super().__init__()
        self.command_queue = CommandQueue()
        self.board = None
        self.port = 'Virtual'
        self.simulate = True
        self.communication_timer = None
        self.execution_timer = None
        self.sent_command = None

        self.fss = 13107
        self.psi_offset = 1638
        self.psi_max = 15

    def begin_communication_timer(self):
        self.communication_timer = QTimer()
        self.communication_timer.timeout.connect(self.request_status_update)
        self.communication_timer.start(10)  # Update every 100 ms

    def begin_execution_timer(self):
        self.execution_timer = QTimer()
        self.execution_timer.timeout.connect(self.send_next_command)
        self.execution_timer.start(90)  # Update every 100 ms

    def stop_communication_timer(self):
        self.communication_timer.stop()

    def stop_execution_timer(self):
        self.execution_timer.stop()

    def connect_board(self,port):
        if port == 'Virtual':
            self.board = VirtualMachine(self)
            self.simulate = True

        self.request_status_update()
        self.begin_communication_timer()
        self.begin_execution_timer()
        return True

    def disconnect_board(self, error=False):
        self.stop_communication_timer()
        self.stop_execution_timer()
        self.board = None
        return True
    
    def connect_balance(self,port):
        self.balance = Balance(self)
        self.balance.connect_balance(port)
        return True
    
    def disconnect_balance(self):
        self.balance.close_connection()
        return True

    def request_status_update(self):
        """Send a request to the control board for a status update."""
        if self.board is not None:
            if self.simulate:
                status_string = self.board.get_complete_state()
            try:
                status_dict = self.parse_status_string(status_string)
                self.command_queue.update_command_status(status_dict.get('Current_command', None),
                                                         status_dict.get('Last_completed', None))
                self.status_updated.emit(status_dict)  # Emit the status update signal
            except ValueError as e:
                self.error_occurred.emit(f"Error parsing status string: {str(e)}")
            except Exception as e:
                self.error_occurred.emit(f"Unexpected error: {str(e)}")

    def parse_status_string(self, status_string):
        """Convert status string into a dictionary."""
        if not status_string:
            raise ValueError("Status string is empty")

        status_dict = {}
        for item in status_string.split(','):
            try:
                key, value = item.split(':')
                status_dict[key] = value
            except ValueError:
                raise ValueError(f"Malformed item in status string: {item}")

        return status_dict

    def add_command_to_queue(self, command_type, param1, param2, param3, handler=None, kwargs=None, manual=False):
        """Add a command to the queue."""
        if manual and self.command_queue.get_number_of_sent_commands() > 0:
            print('Cannot add manual command while commands are being sent.')
            return False
        return self.command_queue.add_command(command_type, param1, param2, param3, handler, kwargs)

    def send_next_command(self):
        """Send the next command to the machine."""
        command = self.command_queue.get_next_command()
        if command is not None:
            if self.simulate:
                print(f'Sending command: {command.get_command()}')
                self.sent_command = command
                self.command_sent.emit({"command": command.get_command()})
            return True
        return False

    def update_state(self, state):
        """Update the machine state."""
        self.status_updated.emit(state)

    def enable_motors(self,handler=None,kwargs=None,manual=False):
        self.add_command_to_queue('ENABLE_MOTORS',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
        return
    
    def disable_motors(self,handler=None,kwargs=None,manual=False):
        self.add_command_to_queue('DISABLE_MOTORS',0,0,0,handler=handler,kwargs=kwargs, manual=manual)
        self.add_command_to_queue('GRIPPER_OFF',0,0,0)
        return
    
    def regulate_pressure(self,handler=None,kwargs=None,manual=False):
        self.add_command_to_queue('REGULATE_PRESSURE',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
        return
    
    def deregulate_pressure(self,handler=None,kwargs=None,manual=False):
        self.add_command_to_queue('DEREGULATE_PRESSURE',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
        return

    def set_relative_coordinates(self, x, y, z, handler=None, kwargs=None, manual=False):
        self.add_command_to_queue('RELATIVE_XYZ', x, y, z, handler=handler, kwargs=kwargs, manual=manual)
        return

    def set_absolute_coordinates(self, x, y, z, handler=None, kwargs=None, manual=False):
        self.add_command_to_queue('ABSOLUTE_XYZ', x, y, z, handler=handler, kwargs=kwargs, manual=manual)
        return
    
    def convert_to_psi(self,pressure):
        return round(((pressure - self.psi_offset) / self.fss) * self.psi_max,4)
    
    def convert_to_raw_pressure(self,psi):
        return int((psi / self.psi_max) * self.fss + self.psi_offset)

    def set_relative_pressure(self,psi,handler=None,kwargs=None,manual=False):
        pressure = self.convert_to_raw_pressure(psi)
        pressure -= self.psi_offset
        print('Setting relative pressure:',pressure)
        self.add_command_to_queue('RELATIVE_PRESSURE',pressure,0,0,handler=handler,kwargs=kwargs,manual=manual)
        return

    def home_motor_handler(self):
        self.homed = True
        self.location = 'Home'

    def home_motors(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            handler = self.home_motor_handler
        self.add_command_to_queue('HOME_ALL',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    
    

