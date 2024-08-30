import threading
import time
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QThread
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
            print('Connecting to virtual balance')
            self.connected = True
            self.simulate = True
            self.mass_simulate_timer = QtCore.QTimer()
            self.mass_simulate_timer.timeout.connect(self.update_simulated_mass)
            self.mass_simulate_timer.start(10)
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
            self.mass_simulate_timer.stop()
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
        print('\n---Begin reading balance---\n')
        self.mass_update_timer = QtCore.QTimer()
        self.mass_update_timer.timeout.connect(self.get_mass)
        self.mass_update_timer.start(20)

    def add_to_log(self,mass):
        # print('Adding to log:',mass)
        self.mass_log.append(mass)
        if len(self.mass_log) > 100:
            self.mass_log.pop(0)

    def get_recent_mass(self):
        if self.mass_log != []:
            return self.mass_log[-1]
        else:
            return 0

    def simulate_mass(self,num_droplets,psi):
        print('Simulating mass')
        # Reference points
        ref_droplets = 100
        ref_points = np.array([
            [1.8, 3],
            [2.2, 4],
        ])

        # Calculate the linear fit for the reference points
        coefficients = np.polyfit(ref_points[:, 0], ref_points[:, 1] / ref_droplets, 1)
        # print('Coefficients:',coefficients)
        # Calculate the mass per droplet for the given pressure
        mass_per_droplet = coefficients[0] * psi + coefficients[1]
        # for point in ref_points:
        #     print('Point:',point[0],point[1],coefficients[0] * point[0] + coefficients[1])
        # Calculate the mass for the given number of droplets
        mass = mass_per_droplet * num_droplets

        return mass
    
    def update_simulated_mass(self):
        # print('Updating simulated mass')
        if self.machine.balance_droplets != []:
            # print('Balance droplets:',self.machine.balance_droplets)
            [num_droplets,psi] = self.machine.balance_droplets.pop(0)
            # print('Found balance droplets',num_droplets,psi)
            mass = self.simulate_mass(num_droplets,psi)
            # print('Simulated mass:',mass,self.current_mass,self.target_mass)
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
        elif command.command_type == 'RESET_ACCEL':
            print('Resetting acceleration')
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
        # print(f'type params: {self.command_number}-{command_type} {type(param1)} {type(param2)} {type(param3)}')
        print(f'Adding command: {command_type} {param1} {param2} {param3}')
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

            # Remove oldest commands from the completed deque if it exceeds 100
            if len(self.completed) > 100:
                self.completed.popleft()

        self.queue_updated.emit()

    def clear_queue(self):
        """Clear the command queue."""
        self.queue.clear()
        self.completed.clear()
        self.command_number = 0
        self.queue_updated.emit()

class DisconnectWorker(QThread):
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

    def run(self):
        self.parent.gripper_off()
        self.parent.disable_motors()
        self.parent.deregulate_pressure()

        # Continuously check until all tasks are completed
        timeout_counter = 0
        while not self.parent.check_if_all_completed():
            timeout_counter += 1
            time.sleep(0.1)
            if timeout_counter > 100:
                print('Timeout disconnecting from machine')
                break

        self.parent.clear_command_queue()
        self.finished.emit()
    

class Machine(QObject):
    """
    Class for the machine object. This class is responsible for 
    sending and receiving data from the machine and organizing
    the command queue.
    """
    status_updated = Signal(dict)  # Signal to emit status updates
    command_sent = Signal(dict)    # Signal to emit when a command is sent
    error_occurred = Signal(str)   # Signal to emit errors
    homing_completed = Signal()    # Signal to emit when homing is completed
    gripper_open = Signal()      # Signal to emit when the gripper is opened
    gripper_closed = Signal()    # Signal to emit when the gripper is closed
    gripper_on_signal = Signal()        # Signal to emit when the gripper is turned on
    gripper_off_signal = Signal()       # Signal to emit when the gripper is turned off
    disconnect_complete_signal = Signal()  # Signal to stop timers
    machine_connected_signal = Signal(bool)  # Signal to emit when the machine is connected
    
    def __init__(self):
        super().__init__()
        self.command_queue = CommandQueue()
        self.board = None
        self.port = 'Virtual'
        self.simulate = True
        self.communication_timer = None
        self.execution_timer = None
        self.sent_command = None
        self.error_count = 0

        self.fss = 13107
        self.psi_offset = 1638
        self.psi_max = 15

        self.simulate_balance = True
        self.balance = Balance(self)
        self.balance_connected = False
        self.balance_droplets = []

    def begin_communication_timer(self):
        print('Starting communication timer')
        self.communication_timer = QTimer()
        self.communication_timer.timeout.connect(self.request_status_update)
        self.communication_timer.start(5)  # Update every 100 ms

    def begin_execution_timer(self):
        print('Starting execution timer')
        self.execution_timer = QTimer()
        self.execution_timer.timeout.connect(self.send_next_command)
        self.execution_timer.start(90)  # Update every 100 ms

    def stop_communication_timer(self):
        print('Stopping communication timer')
        self.communication_timer.stop()

    def stop_execution_timer(self):
        print('Stopping execution timer')
        self.execution_timer.stop()

    def reset_board(self):
        print('Resetting board')
        self.board = None
        self.port = None
        self.command_queue.clear_queue()
        self.stop_communication_timer()
        self.stop_execution_timer()

    def connect_board(self,port):
        if port == 'Virtual':
            self.board = VirtualMachine(self)
            self.machine_connected_signal.emit(True)
            self.simulate = True
            self.port = port
        else:
            print('Connecting to machine at port:',port)
            try:
                self.board = serial.Serial(port, baudrate=115200,timeout=2)
                if not self.board.is_open:  # Add this line
                    self.error_occurred.emit('Could not open port')
                    raise serial.SerialException('Could not open port')  # Add this line
                self.machine_connected_signal.emit(True)
                self.simulate = False
                self.port = port
            except Exception as e:
                self.error_occurred.emit(f'Could not connect to machine at port {port}\nError: {e}')
                self.machine_connected_signal.emit(False)
                self.port = None
                return False
        self.request_status_update()
        self.begin_communication_timer()
        self.begin_execution_timer()
        return True
    
    def disconnect_handler(self):
        if not self.simulate:
            self.board.close()
        self.reset_board()
        self.disconnect_complete_signal.emit()

    def disconnect_board(self, error=False):
        print('--------Disconnecting from machine---------')
        if not error:
            self.worker = DisconnectWorker(self)
            self.worker.finished.connect(self.disconnect_handler)
            self.worker.start()
        else:
            self.disconnect_handler()
    
    def get_machine_port(self):
        return self.port
    
    def connect_balance(self,port):
        if self.balance.connect_balance(port):
            self.balance_connected = True
            return True
        else:
            self.balance_connected = False
            return False
    
    def disconnect_balance(self):
        self.balance.close_connection()
        self.balance_connected = False
        return
    
    def is_balance_connected(self):
        return self.balance_connected
    
    def update_command_numbers(self,current_command,last_completed):
        self.command_queue.update_command_status(current_command,last_completed)

    def request_status_update(self):
        """Send a request to the control board for a status update."""
        if self.board is not None:
            if self.simulate:
                status_string = self.board.get_complete_state()
            else:
                try:
                    if self.board.in_waiting > 0:
                        status_string = self.board.readline().decode('utf-8').strip()
                        # print('Status string:',status_string)
                    else:
                        status_string = ''
                except Exception as e:
                    status_string = ''
                    self.error_occurred.emit(f'Error reading from machine\n Error: {e}')
                    self.error_count += 1
                    if self.error_count > 100:
                        print('------- Automatic disconnect -------')
                        self.disconnect_board(error=True)
            try:
                if status_string == '':
                    # print('No status string received')
                    return
                status_dict = self.parse_status_string(status_string)
                if status_dict == {}:
                    return
                self.status_updated.emit(status_dict)  # Emit the status update signal
                self.error_count = 0
            except ValueError as e:
                self.error_occurred.emit(f"Error parsing status string: {str(e)}-{status_string}")
            except Exception as e:
                self.error_occurred.emit(f"Unexpected error: {str(e)}-{status_string}")
                self.error_count += 1
                if self.error_count > 100:
                    print('------- Automatic disconnect -------')
                    self.disconnect_board(error=True)

    def parse_status_string(self, status_string):
        """Convert status string into a dictionary."""
        if not status_string:
            raise ValueError("Status string is empty")
        
        if "DEBUG" in status_string:
            # print('Status string:',status_string)
            return {}

        status_dict = {}
        # for item in status_string.split(','):
        try:
            key, value = status_string.split(':')
            status_dict[key] = value
        except ValueError:
            raise ValueError(f"Malformed item in status string: {status_string}")

        return status_dict

    def check_if_all_completed(self):
        """Check if all commands have been completed."""
        if len(self.command_queue.queue) == 0:
            return True
        return False
    
    def get_remaining_commands(self):
        return len(self.command_queue.queue)
    
    def add_command_to_queue(self, command_type, param1, param2, param3, handler=None, kwargs=None, manual=False):
        """Add a command to the queue."""
        if self.board is None:
            print('No board connected')
            return False
        if manual:
            completed = self.check_if_all_completed()
            if not completed:
                print('Cannot add manual command while commands are in queue')
                return False
        return self.command_queue.add_command(command_type, param1, param2, param3, handler, kwargs)

    def send_command_to_board(self, command):
        """Send a command to the board."""
        if self.board is not None:
            if self.simulate:
                print(f'Sending command: {command.get_command()}')
                self.sent_command = command
                self.command_sent.emit({"command": command.get_command()})
                return True
            else:
                self.board.write(command.get_command().encode('utf-8'))
                self.board.flush()
                self.command_sent.emit({"command": command.get_command()})
                return True
        else:
            print('No board connected')
        return False

    def send_next_command(self):
        """Send the next command to the machine."""
        command = self.command_queue.get_next_command()
        if command is not None:
            self.send_command_to_board(command)
        return False
    
    def pause_commands(self):
        print('Pausing commands')
        new_command = Command(0, 'PAUSE', 0, 0, 0)
        if self.sent_command is not None:
            print('Overriding command:',self.sent_command.get_command())
        print('Sending pause command')
        self.send_command_to_board(new_command)

    def resume_commands(self):
        print('Resuming commands')
        new_command = Command(0, 'RESUME', 0, 0, 0)
        if self.sent_command is not None:
            print('Overriding command:',self.sent_command.get_command())
        print('Sending resume command')
        self.send_command_to_board(new_command)

    def clear_command_queue(self,handler=None):
        print('Clearing command queue')
        new_command = Command(0, 'CLEAR_QUEUE', 0, 0, 0, handler=handler)
        if self.sent_command is not None:
            print('Overriding command:',self.sent_command.get_command())
        print('Sending clear command')
        self.send_command_to_board(new_command)
        self.command_queue.clear_queue()

    def update_state(self, state):
        """Update the machine state."""
        self.status_updated.emit(state)

    def enable_motors(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('ENABLE_MOTORS',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def disable_motors(self,handler=None,kwargs=None,manual=False):
        outcome = self.add_command_to_queue('DISABLE_MOTORS',0,0,0,handler=handler,kwargs=kwargs, manual=manual)
        self.add_command_to_queue('GRIPPER_OFF',0,0,0)
        return outcome
    
    def change_acceleration(self,acceleration,handler=None,kwargs=None,manual=False):
        self.add_command_to_queue('CHANGE_ACCEL',acceleration,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def reset_acceleration(self,handler=None,kwargs=None,manual=False):
        self.add_command_to_queue('RESET_ACCEL',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def regulate_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('REGULATE_PRESSURE',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def deregulate_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('DEREGULATE_PRESSURE',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def reset_syringe(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('RESET_P',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def set_relative_X(self, x, handler=None, kwargs=None, manual=False):
        return self.add_command_to_queue('RELATIVE_X', x, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def set_absolute_X(self, x, handler=None, kwargs=None, manual=False):
        return self.add_command_to_queue('ABSOLUTE_X', x, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def set_relative_Y(self, y, handler=None, kwargs=None, manual=False):
        return self.add_command_to_queue('RELATIVE_Y', y, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def set_absolute_Y(self, y, handler=None, kwargs=None, manual=False):
        return self.add_command_to_queue('ABSOLUTE_Y', y, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def set_relative_Z(self, z, handler=None, kwargs=None, manual=False):
        return self.add_command_to_queue('RELATIVE_Z', z, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def set_absolute_Z(self, z, handler=None, kwargs=None, manual=False):
        return self.add_command_to_queue('ABSOLUTE_Z', z, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def set_relative_coordinates(self, x, y, z, handler=None, kwargs=None, manual=False):
        return self.add_command_to_queue('RELATIVE_XYZ', x, y, z, handler=handler, kwargs=kwargs, manual=manual)
        
    def set_absolute_coordinates(self, x, y, z, handler=None, kwargs=None, manual=False):
        return self.add_command_to_queue('ABSOLUTE_XYZ', x, y, z, handler=handler, kwargs=kwargs, manual=manual)
        
    def convert_to_psi(self,pressure):
        return round(((pressure - self.psi_offset) / self.fss) * self.psi_max,4)
    
    def convert_to_raw_pressure(self,psi):
        return int((psi / self.psi_max) * self.fss + self.psi_offset)

    def set_relative_pressure(self,psi,handler=None,kwargs=None,manual=False):
        pressure = self.convert_to_raw_pressure(psi)
        pressure -= self.psi_offset
        print('Setting relative pressure:',pressure)
        return self.add_command_to_queue('RELATIVE_PRESSURE',pressure,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def set_absolute_pressure(self,psi,handler=None,kwargs=None,manual=False):
        pressure = self.convert_to_raw_pressure(psi)
        print('Setting absolute pressure:',pressure)
        return self.add_command_to_queue('ABSOLUTE_PRESSURE',pressure,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def home_motor_handler(self):
        self.homed = True
        self.location = 'Home'
        self.homing_completed.emit()

    def home_motors(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            handler = self.home_motor_handler
        self.add_command_to_queue('HOME_Z',0,0,0,handler=None,kwargs=kwargs,manual=manual)
        self.add_command_to_queue('HOME_X',0,0,0,handler=None,kwargs=kwargs,manual=manual)
        self.add_command_to_queue('HOME_Y',0,0,0,handler=None,kwargs=kwargs,manual=manual)
        self.add_command_to_queue('HOME_P',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
        return True
    
    def open_gripper_handler(self,additional_handler=None):
        if additional_handler is not None:
            additional_handler()
        self.gripper_open.emit()

    def open_gripper(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            new_handler = self.open_gripper_handler
        else:
            new_handler = lambda: self.open_gripper_handler(handler)
        return self.add_command_to_queue('OPEN_GRIPPER',0,0,0,handler=new_handler,kwargs=kwargs,manual=manual)
    
    def close_gripper_handler(self,additional_handler=None):
        if additional_handler is not None:
            additional_handler()
        self.gripper_closed.emit()

    def close_gripper(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            new_handler = self.close_gripper_handler
        else:
            new_handler = lambda: self.close_gripper_handler(handler)
        return self.add_command_to_queue('CLOSE_GRIPPER',0,0,0,handler=new_handler,kwargs=kwargs,manual=manual)
        
    def gripper_off_handler(self):
        self.gripper_off_signal.emit()

    def gripper_off(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            handler = self.gripper_off_handler
        return self.add_command_to_queue('GRIPPER_OFF',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def wait_command(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('WAIT',500,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def print_droplets(self,droplet_count,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('PRINT',droplet_count,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def calibrate_pressure_handler(self,num_droplets=100,psi=1.8):
        self.balance_droplets.append([num_droplets,psi])

    def print_calibration_droplets(self,num_droplets,pressure,manual=False):
        self.print_droplets(num_droplets,handler=self.calibrate_pressure_handler,kwargs={'num_droplets':num_droplets,'psi':pressure},manual=manual)
