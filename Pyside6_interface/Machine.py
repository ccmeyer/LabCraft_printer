import threading
import time
from PySide6 import QtCore, QtWidgets, QtGui
from CustomWidgets import *
import serial
import re
import json
import cv2

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
        if port == 'Virtual balance':
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

class ControlBoard():
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
            f'Pressure:{self.pressure},'
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
                    self.state = "Busy"
                    break            

    def execute_command(self,command_index):
        command = self.command_queue[command_index]
        print('Board Executing command:',command.command_type,command.param1,command.param2,command.param3)
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

class Command():
    def __init__(self, command_number,command_type,param1,param2,param3,handler=None,kwargs=None):
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
        self.sent = False
        self.executed = False
        self.completed = False
        self.timestamp = time.time()
        self.handler = handler
        self.kwargs = kwargs if kwargs is not None else {}
    
    def get_number(self):
        return self.command_number
    
    def get_command(self):
        return self.signal
    
    def get_timestamp(self):
        return self.timestamp
    
    def send(self):
        self.sent = True
    
    def execute_handler(self):
        if self.handler is not None:
            self.handler(**self.kwargs)
        self.executed = True
    
    def complete(self):
        self.completed = True

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
    board_connected = QtCore.Signal(bool)
    stop_timers_signal = QtCore.Signal()

    def __init__(self, main_window):
        super().__init__()
        print('Created Machine instance')
        self.main_window = main_window
        self.simulate = True
        self.simulate_balance = True
        self.board = ControlBoard(self)
        self.balance = Balance(self)
        self.balance_connected = False
        self.balance_droplets = []

        self.machine_connected = False
        self.motors_active = False
        self.x_pos = 0
        self.y_pos = 0
        self.z_pos = 0
        self.p_pos = 0
        self.coordinates = {'X': self.x_pos, 'Y': self.y_pos, 'Z': self.z_pos, 'P': self.p_pos}
        self.location = 'Unknown'
        self.homed = False
        self.cycle_count = 0
        self.max_cycle = 0

        self.target_x = 0
        self.target_y = 0
        self.target_z = 0
        self.target_p = 0
        self.target_coordinates = {'X': self.target_x, 'Y': self.target_y, 'Z': self.target_z, 'P': self.target_p}

        self.current_pressure = 0
        self.current_psi = 0
        self.target_psi = 0
        self.fss = self.main_window.settings['PRESSURE_CONVERSION']['FSS']
        self.psi_offset = self.main_window.settings['PRESSURE_CONVERSION']['OFFSET']
        self.psi_max = self.main_window.settings['PRESSURE_CONVERSION']['MAX_PRESSURE']

        self.pressure_log = [0]
        self.regulating_pressure = False

        self.previous_gripper_state = False
        self.gripper_open = False
        self.gripper_empty = True
        self.gripper_busy = False
        self.gripper_reagent = Reagent("Empty", self.main_window.colors, "dark_gray")

        self.current_droplets = 0

        self.led_active = False
        self.led_triggered = False

        self.command_number = 0
        self.command_queue = []
        self.incomplete_commands = []
        self.last_added_command_number = 0
        self.current_command_number = 0
        self.last_completed_command_number = 0
        self.sent_command = None
        self.com_open = True
        self.state = "Free"

        self.calibration_file_path = os.path.join('Pyside6_interface', 'Calibrations', 'default_positions.json')
        self.calibration_data = {}
        self.load_positions_from_file()
        self.well_positions = pd.DataFrame()

        self.rack_offset = self.main_window.rack_offset
        self.safe_height = self.main_window.safe_height
        self.safe_y = self.main_window.safe_y
        self.max_x = self.main_window.max_x
        self.max_y = self.main_window.max_y
        self.max_z = self.main_window.max_z

        self.picking_up = False
        self.dropping_off = False

    def begin_communication_timer(self):
        self.communication_timer = QTimer()
        self.communication_timer.timeout.connect(self.get_state_from_board)
        self.communication_timer.start(10)  # Update every 100 ms
    
    def begin_execution_timer(self):
        self.execution_timer = QTimer()
        self.execution_timer.timeout.connect(self.execute_command_from_queue)
        self.execution_timer.start(90)  # Update every 100 ms

    def stop_communication_timer(self):
        self.communication_timer.stop()

    def stop_execution_timer(self):
        self.execution_timer.stop()

    def connect_machine(self,port):
        if port == 'Virtual machine':
            self.simulate = True
            self.board = ControlBoard(self)
            self.machine_connected = True
        else:
            try:
                self.board = serial.Serial(port, baudrate=115200,timeout=2)
                if not self.board.is_open:  # Add this line
                    raise serial.SerialException('Could not open port')  # Add this line
                self.machine_connected = True
                self.simulate = False
            except:
                self.main_window.popup_message('Connection error',f'Could not connect to machine at port {port}')
                self.machine_connected = False
                return False
        self.get_state_from_board()
        self.begin_communication_timer()
        self.begin_execution_timer()

        self.target_x = self.x_pos
        self.target_y = self.y_pos
        self.target_z = self.z_pos
        self.target_p = self.p_pos
        self.target_coordinates = {'X': self.target_x, 'Y': self.target_y, 'Z': self.target_z, 'P': self.target_p}
        self.target_psi = self.current_psi
        self.target_gripper_open = self.gripper_open
        self.target_droplets = self.current_droplets
        return True
                
    def disconnect_machine(self,error=False):
        def disconnect():
            print('Disconnecting from machine')
            if not error:
                self.gripper_off()
                self.disable_motors()
                self.deregulate_pressure()
                # self.clear_command_queue()
            if not self.simulate:
                while self.incomplete_commands != []:
                    print('--Waiting', self.incomplete_commands)
                    self.execute_command_from_queue()
                    self.get_state_from_board()
                    time.sleep(0.1)

            print('Disconnected from machine')
            self.stop_timers_signal.emit()
            if not self.simulate:
                self.board.close()
            self.machine_connected = False
            if error:
                self.board_connected.emit(False)
                print('Emitting connection error')
            else:
                self.board_connected.emit(True)
                print('Emitting disconnection')

        disconnect_thread = threading.Thread(target=disconnect)
        disconnect_thread.start()
    
    def stop_timers(self):
        self.communication_timer.stop()
        self.execution_timer.stop()
        print('Stopped timers')
    
    def connect_balance(self,port):
        if self.balance.connect_balance(port):
            self.balance_connected = True
            return True
        else:
            self.balance_connected = False
            return False
        
    def disconnect_balance(self):
        print('Disconnected from balance')
        self.balance.close_connection()
        return
    
    def is_balance_connected(self):
        return self.balance.connected
    
    def add_command_to_queue(self, command_type, param1, param2, param3,handler=None,kwargs=None):
        new_command = Command(self.command_number, command_type=command_type, param1=param1, param2=param2, param3=param3,handler=handler,kwargs=kwargs)
        self.command_queue.append(new_command)
        self.incomplete_commands.append(new_command)
        self.command_added.emit(new_command)
        self.command_number += 1

    def execute_command_from_queue(self):
        if self.sent_command == None:
            if self.last_added_command_number < self.last_completed_command_number + 3:
                for command in self.command_queue:
                    if not command.sent:
                        print('Sending command:',command.get_command())
                        if self.send_command_to_board(command):
                            self.update_targets_from_command(command)
                            self.command_sent.emit(command)
                        else:
                            print('Failed to send command:',command.get_command(),self.com_open)
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
            rel_pressure = int(command.param1) + self.psi_offset
            rel_psi = round(self.convert_to_psi(rel_pressure),3)
            self.target_psi += rel_psi
        elif command.command_type == 'ABSOLUTE_PRESSURE':
            self.target_psi = self.convert_to_psi(int(command.param1))
        elif command.command_type == 'REGULATE_PRESSURE':
            self.regulating_pressure = True
        elif command.command_type == 'DEREGULATE_PRESSURE':
            self.regulating_pressure = False
        elif command.command_type == 'OPEN_GRIPPER':
            pass
        elif command.command_type == 'CLOSE_GRIPPER':
            pass
        elif command.command_type == 'WAIT':
            pass
        elif command.command_type == 'ENABLE_MOTORS':
            self.motors_active = True
        elif command.command_type == 'DISABLE_MOTORS':
            self.motors_active = False
        elif command.command_type == 'PRINT':
            pass
        elif command.command_type == 'PAUSE':
            print('--Pausing')
            pass
        elif command.command_type == 'RESUME':
            print('--Resuming')
            pass
        elif command.command_type == 'CLEAR_QUEUE':
            pass
        elif command.command_type == 'RESET_P':
            self.target_p = 0
        elif command.command_type == 'HOME_ALL':
            self.target_x = 0
            self.target_y = 0
            self.target_z = 0
            self.target_p = 0
            self.target_coordinates = {'X': self.target_x, 'Y': self.target_y, 'Z': self.target_z, 'P': self.target_p}
        else:
            print('Unknown command:',command.command_type)

    def send_command_to_board(self,command):
        if self.com_open == True:
            if self.simulate:
                self.sent_command = command
            else:
                self.board.write(command.get_command().encode())
                self.board.flush()
            command.send()
            return True
        else:
            print('Cannot send command, communication is closed')
            return False
        
    def get_command_number(self):
        return self.command_number
    
    def get_command_log(self):
        return self.command_queue
    
    def get_incomplete_commands(self):
        return self.incomplete_commands
    
    def get_state_from_board(self):
        try:
            if self.simulate:
                signal = self.board.get_complete_state()
            else:
                if self.board.in_waiting > 0:
                    try:
                        signal = self.board.readline().decode('utf-8').strip()
                    except:
                        signal = ''
                        self.window.popup_message('Connection error','Could not read from board')
                else:
                    signal = ''
            self.update_state(self.convert_state(signal))
            return signal
        except serial.SerialException:
            self.disconnect_machine(error=True)
            return ''
    
    def convert_to_psi(self,pressure):
        return round(((pressure - self.psi_offset) / self.fss) * self.psi_max,4)
    
    def convert_to_raw_pressure(self,psi):
        return int((psi / self.psi_max) * self.fss + self.psi_offset)

    def convert_state(self, state):
        if state == '':
            return {}
        # print('Received state:',state)
        if 'DEBUG' in state:
            # print('Received state:',state)
            return {}
        state_dict = {}
        state_list = state.split(',')
        for item in state_list:
            key,value = item.split(':')
            state_dict[key] = value.strip()
        return state_dict
    
    def update_state(self, state):
        if state == {}:
            return
        self.state = state['State']
        self.last_added_command_number = int(state['Last_added'])
        self.current_command_number = int(state['Current_command'])
        self.last_completed_command_number = int(state['Last_completed'])
        # print('State:',self.state,self.last_added_command_number,self.current_command_number,self.last_completed_command_number)
        # print('--Com_open:',state['Com_open'],type(state['Com_open']))
        if state['Com_open'] == 'True' or state['Com_open'] == '1':
            self.com_open = True
        # self.com_open = state['Com_open'] == 'True'
        self.x_pos = int(state['X'])
        self.y_pos = int(state['Y'])
        self.z_pos = int(state['Z'])
        self.p_pos = int(state['P'])
        self.coordinates = {'X': self.x_pos, 'Y': self.y_pos, 'Z': self.z_pos, 'P': self.p_pos}
        self.current_pressure = float(state['Pressure'])
        self.current_psi = self.convert_to_psi(self.current_pressure)
        self.current_droplets = int(state['Droplets'])

        self.led_active = int(state['LED_Active'])
        self.led_triggered = state['LED_Triggered'] == 'True'

        self.max_cycle = int(state['Max_cycle'])
        self.cycle_count = int(state['Cycle_count'])

        target_gripper_open = state['Gripper'] == 'True'
        if self.gripper_open != target_gripper_open:
            # The gripper state has changed
            if not self.gripper_busy:
                # The gripper is not currently in the process of opening or closing
                self.gripper_open = target_gripper_open
                self.gripper_busy = True  # The gripper is now in the process of opening or closing
                if self.gripper_open:
                    self.main_window.open_gripper()
                else:
                    self.main_window.close_gripper()
        elif self.gripper_busy:
            # The gripper has finished opening or closing
            self.gripper_busy = False

        self.pressure_log.append(self.current_psi)
        if len(self.pressure_log) > 100:
            self.pressure_log.pop(0)  # Remove the oldest reading
        
        if self.command_queue != []:
            if self.current_command_number == self.last_completed_command_number:
                current_command = self.command_queue[self.current_command_number]
                if current_command.executed and not current_command.completed:
                    self.command_completed.emit(self.command_queue[self.current_command_number])
                    current_command.complete()
            else:
                try:
                    self.command_executed.emit(self.command_queue[self.current_command_number])
                except IndexError:
                    print('Index error:',self.current_command_number,len(self.command_queue),self.command_queue[0].get_number(),self.command_queue[0].get_command())
                    self.current_command_number = self.command_queue[-1].get_number()

        if self.incomplete_commands != []:
            for i,command in enumerate(self.incomplete_commands):
                if command.get_number() <= self.current_command_number:
                    if command.sent and not command.executed:
                        completed_command = self.incomplete_commands.pop(i)
                        completed_command.execute_handler()

        self.main_window.update_machine_position()

    def print_handler(self,message='Default message'):
        print(message)

    def well_complete_handler(self, well_number=None,reagent=None):
        print(f'Well {well_number} printed with {reagent}')
        self.main_window.mark_reagent_as_added(well_number,reagent)

    def last_well_complete_handler(self, well_number=None,reagent=None):
        print(f'Last Well {well_number} printed with {reagent}')
        self.main_window.mark_reagent_as_added(well_number,reagent)
        self.reset_acceleration()
        self.move_to_location('pause')

    def pause_commands(self):
        print('Pausing commands')
        new_command = Command(0, command_type='PAUSE', param1=0, param2=0, param3=0)
        if self.sent_command is not None:
            print('Overriding command:',self.sent_command.get_command())
        print('Sending pause command')
        self.send_command_to_board(new_command)
    
    def resume_commands(self):
        new_command = Command(0, command_type='RESUME', param1=0, param2=0, param3=0)
        if self.sent_command is not None:
            print('Overriding command:',self.sent_command.get_command())
        self.send_command_to_board(new_command)

    def clear_command_queue(self):
        print('Clearing command queue')
        new_command = Command(0, command_type='CLEAR_QUEUE', param1=0, param2=0, param3=0)
        if self.sent_command is not None:
            print('Overriding command:',self.sent_command.get_command())
        self.send_command_to_board(new_command)

        self.main_window.remove_commands(self.command_queue)
        self.command_queue = []
        self.current_command_number = 0
        self.last_completed_command_number = 0
        self.command_number = 0
        self.incomplete_commands = []

        self.target_x = self.x_pos
        self.target_y = self.y_pos
        self.target_z = self.z_pos
        self.target_p = self.p_pos
        self.target_coordinates = {'X': self.target_x, 'Y': self.target_y, 'Z': self.target_z, 'P': self.target_p}
        self.coordinates = {'X': self.x_pos, 'Y': self.y_pos, 'Z': self.z_pos, 'P': self.p_pos}
        self.target_psi = self.current_psi
        self.target_gripper_open = self.gripper_open
        self.target_droplets = self.current_droplets

        self.main_window.update_coordinates()
        self.main_window.update_pressure()
    
    def enable_motors_handler(self):
        self.motors_active = True
        self.main_window.change_motor_activation(True)
    
    def disable_motors_handler(self):
        self.motors_active = False
        self.main_window.change_motor_activation(False)

    def enable_motors(self,handler=None,kwargs=None):
        if handler is None:
            handler = self.enable_motors_handler
        self.add_command_to_queue('ENABLE_MOTORS',0,0,0,handler=handler,kwargs=kwargs)
        return
    
    def disable_motors(self,handler=None,kwargs=None):
        if handler is None:
            handler = self.disable_motors_handler
        self.add_command_to_queue('DISABLE_MOTORS',0,0,0,handler=handler,kwargs=kwargs)
        self.add_command_to_queue('GRIPPER_OFF',0,0,0)
        return

    def set_absolute_coordinates(self,x,y,z):
        self.add_command_to_queue('ABSOLUTE_XYZ',x,y,z)
        return
    
    def set_relative_coordinates(self,x,y,z):
        if self.homed:
            if self.x_pos - x < self.max_x:
                self.main_window.popup_message('X-axis limit','Cannot move beyond X-axis limit')
                x = 0
            if self.y_pos + y > self.max_y:
                self.main_window.popup_message('Y-axis limit','Cannot move beyond Y-axis limit')
                y = 0
            if self.z_pos - z < self.max_z:
                self.main_window.popup_message('Z-axis limit','Cannot move beyond Z-axis limit')
                z = 0
            
        self.add_command_to_queue('RELATIVE_XYZ',x,y,z)
        return
    
    def set_absolute_pressure(self,psi):
        pressure = self.convert_to_raw_pressure(psi)
        self.add_command_to_queue('ABSOLUTE_PRESSURE',pressure,0,0)
        return
    
    def set_relative_pressure(self,psi):
        pressure = self.convert_to_raw_pressure(psi)
        pressure -= self.psi_offset
        print('Setting relative pressure:',pressure)
        self.add_command_to_queue('RELATIVE_PRESSURE',pressure,0,0)
        return
    
    def regulate_pressure_handler(self):
        self.regulating_pressure = True
        self.main_window.change_regulation_button()

    def regulate_pressure(self,handler=None,kwargs=None):
        if handler is None:
            handler = self.regulate_pressure_handler
        self.add_command_to_queue('REGULATE_PRESSURE',0,0,0,handler=handler,kwargs=kwargs)
        return
    
    def deregulate_pressure_handler(self):
        self.regulating_pressure = False
        self.main_window.change_regulation_button()

    def deregulate_pressure(self,handler=None,kwargs=None):
        if handler is None:
            handler = self.deregulate_pressure_handler
        self.add_command_to_queue('DEREGULATE_PRESSURE',0,0,0,handler=handler,kwargs=kwargs)
        return
    
    def open_gripper(self,handler=None,kwargs=None):
        self.add_command_to_queue('OPEN_GRIPPER',0,0,0,handler=handler,kwargs=kwargs)
        return

    def close_gripper(self,handler=None,kwargs=None):
        self.add_command_to_queue('CLOSE_GRIPPER',0,0,0,handler=handler,kwargs=kwargs)
        return
    
    def gripper_off_handler(self):
        self.gripper_active = False
    
    def gripper_off(self,handler=None,kwargs=None):
        if handler is None:
            handler = self.gripper_off_handler
        self.add_command_to_queue('GRIPPER_OFF',0,0,0,handler=handler,kwargs=kwargs)
        return

    def wait_command(self):
        self.add_command_to_queue('WAIT',2000,0,0)

    def calibrate_pressure_handler(self,num_droplets=100,psi=1.8):
        self.balance_droplets.append([num_droplets,psi])

    def print_calibration_droplets(self,num_droplets,pressure):
        self.print_droplets(num_droplets,handler=self.calibrate_pressure_handler,kwargs={'num_droplets':num_droplets,'psi':pressure})

    def print_droplets(self,droplet_count,handler=None,kwargs=None):
        if not self.regulating_pressure:
            self.main_window.popup_message('Pressure not regulated','Pressure must be regulated to print droplets')
            return
        self.add_command_to_queue('PRINT',droplet_count,0,0,handler=handler,kwargs=kwargs)

    def reset_syringe(self):
        self.add_command_to_queue('RESET_P',0,0,0)
    
    def home_motor_handler(self):
        self.homed = True
        self.location = 'Home'

    def home_motors(self,handler=None,kwargs=None):
        if handler == None:
            handler = self.home_motor_handler
        self.add_command_to_queue('HOME_ALL',0,0,0,handler=handler,kwargs=kwargs)

    def change_acceleration(self,acceleration):
        self.add_command_to_queue('CHANGE_ACCEL',acceleration,0,0)

    def reset_acceleration(self):
        self.add_command_to_queue('RESET_ACCEL',0,0,0)

    def gate_on(self):
        self.add_command_to_queue('GATE_ON',0,0,0)
    
    def gate_off(self):
        self.add_command_to_queue('GATE_OFF',0,0,0)
    
    def activate_led(self):
        self.add_command_to_queue('ACTIVATE_LED',0,0,0)

    def deactivate_led(self):
        self.add_command_to_queue('DEACTIVATE_LED',0,0,0)

    def set_flash_parameters(self,num_flashes,flash_duration,inter_flash_delay):
        self.add_command_to_queue('SET_FLASH',num_flashes,flash_duration,inter_flash_delay)

    def set_flash_delay(self,start_delay,pulse_width):
        self.add_command_to_queue('SET_DELAY',start_delay,pulse_width,0)

    def set_start_parameters(self,start_droplets,start_width,printing_interval):
        self.add_command_to_queue('SET_START',start_droplets,start_width,printing_interval)

    def flash_led(self):
        self.add_command_to_queue('FLASH_ON',0,0,0)

    def take_image(self,flash_delay,flash_duration):
        self.add_command_to_queue('CAMERA_ON',flash_delay,flash_duration,0)

    def get_coordinates(self):
        return self.coordinates
    
    def get_XYZ_coordinates(self):
        return {'X': self.x_pos, 'Y': self.y_pos, 'Z': self.z_pos}
    
    def get_target_coordinates(self):
        return self.target_coordinates
    
    def get_target_psi(self):
        return self.target_psi
    
    def get_pressure_log(self):
        return self.pressure_log
    
    def get_regulation_state(self):
        return self.regulating_pressure
    
    def get_max_cycle(self):
        return self.max_cycle
    
    def get_cycle_count(self):
        return self.cycle_count
    
    def get_led_active(self):
        return self.led_active
    
    def get_led_triggered(self):
        return self.led_triggered
    
    def set_gripper_reagent(self,reagent):
        self.gripper_reagent = reagent
        return

    def pick_up_reagent_handler(self,slot=None):
        self.main_window.change_reagent_pickup(slot)

    def drop_reagent_handler(self,slot=None):
        self.main_window.change_reagent_drop(slot)

    
    def pick_up_reagent(self,slot,handler=None,kwargs=None):
        if handler is None:
            handler = self.pick_up_reagent_handler
            kwargs = {'slot':slot}
        self.open_gripper()
        self.wait_command()
        print('Picking up reagent:',slot.reagent.name)
        location = f'rack_position_{slot.number+1}_{self.main_window.rack_slots}'
        self.move_to_location(location)
        target_coordinates = self.calibration_data[location].copy()
        self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
        self.close_gripper(handler=handler,kwargs=kwargs)
        self.wait_command()
        self.set_gripper_reagent(slot.reagent)
        self.set_absolute_coordinates(target_coordinates['x']+self.rack_offset, target_coordinates['y'], target_coordinates['z'])
        return
    
    def drop_reagent(self,slot):
        location = f'rack_position_{slot.number+1}_{self.main_window.rack_slots}'
        self.move_to_location(location)
        target_coordinates = self.calibration_data[location].copy()
        self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
        self.open_gripper(handler=self.drop_reagent_handler,kwargs={'slot':slot})
        self.wait_command()
        self.set_gripper_reagent(Reagent("Empty", self.main_window.colors, "dark_gray"))
        self.set_absolute_coordinates(target_coordinates['x']+self.rack_offset, target_coordinates['y'], target_coordinates['z'])
        self.close_gripper()
        self.wait_command()
        return

    def calibrate_pressure_handler(self,num_droplets=100,psi=1.8):
        self.balance_droplets.append([num_droplets,psi])
    
    def calibrate_pressure(self,target_volume=30,tolerance=0.02,ask=True,num_droplets=100):
        if not self.is_balance_connected():
            self.main_window.popup_message('Balance not connected','Connect to balance to calibrate pressure')
            return
        if not self.regulating_pressure:
            self.main_window.popup_message('Pressure not regulated','Pressure must be regulated to calibrate pressure')
            return
        if self.gripper_reagent.name == 'Empty':
            self.main_window.popup_message('No reagent loaded','A reagent must be loaded to calibrate pressure')
            return
        if ask:
            response = self.main_window.popup_yes_no('Calibrate pressure','Calibrate pressure? (y/n)')
            if response == '&No':
                print('Not calibrating pressure')
                return
        
        self.move_to_location('balance',direct=False,safe_y=True)
        # target_mass = (target_volume * self.gripper_reagent.density) / 1000
        density = 1
        target_mass = (target_volume * density) / 1000
        target_mass *= num_droplets
        max_pressure_change = 0.5
        while True:
            mass_initial = self.balance.get_stable_mass()
            self.print_droplets(num_droplets,handler=self.calibrate_pressure_handler,kwargs={'num_droplets':num_droplets,'psi':self.current_psi})
            mass_final = self.balance.get_stable_mass()
            mass_change = mass_final - mass_initial
            print(mass_change)
            if abs(mass_change - target_mass) < tolerance:
                print('Calibration complete')
                break
            if mass_change > target_mass:
                proportion = mass_change / target_mass
                pressure_change = self.current_psi / proportion
                if pressure_change > max_pressure_change:
                    pressure_change = max_pressure_change
                new_psi = self.current_psi + pressure_change
                response = self.main_window.popup_yes_no('Pressure incorrect',f'Volume was off by {proportion:3f}\n Continue calibration and set pressure to {new_psi:3f} psi?')
                if response == '&No':
                    break
                self.set_absolute_pressure(new_psi)
                time.sleep(0.2)

    
    def load_positions_from_file(self):
        with open(self.calibration_file_path, 'r') as file:
            self.calibration_data = json.load(file)

    def move_to_location(self,location=False,direct=True,safe_y=False):
        '''
        Tells the robot to move to a location based on the defined coordinates in the calibration file.
        If direct is set to True, the robot will move directly to the location. If safe_y is set to True, 
        the robot will move to the safe_y position before moving to the location to avoid running into an obsticle.
        '''
        if self.motors_active == False or self.homed == False:
            self.main_window.popup_message('Motors not active or homed','Motors must be active and homed to move to location')
            return
        print('Current',self.location)
        if not location:
            location = self.main_window.popup_options('Move to Location','Select location:',list(self.calibration_data.keys()))

        # if self.location == location:
        #     print('Already in {} position'.format(location))
        #     return
        available_locations = list(self.calibration_data.keys())
        if location not in available_locations:
            self.main_window.popup_message('Location not present','{} not present in calibration data'.format(location))
            return
        print('Moving to:',location,'from:',self.location)
        print('Current:',self.x_pos,self.y_pos,self.z_pos)
        print('Target:',self.calibration_data[location]['x'],self.calibration_data[location]['y'],self.calibration_data[location]['z'])
        print("Direct:",direct,"Safe Y:",safe_y)
        if location == 'balance' or self.location == 'balance':
            safe_y = True
            direct = False
        print("After-Direct:",direct,"Safe Y:",safe_y)

        target_coordinates = self.calibration_data[location].copy()
        
        if 'rack_position' in location:
            print('Moving to rack position:',location,'Applying X offset')
            target_coordinates['x'] += self.rack_offset
        else:
            print('Moving to:',location)

        up_first = False
        if direct and self.z_pos < target_coordinates['z']:
            up_first = True
            self.set_absolute_coordinates(self.x_pos, self.y_pos, target_coordinates['z'])

        x_limit = -5500
        if self.x_pos > x_limit and target_coordinates['x'] < x_limit or self.x_pos < x_limit and target_coordinates['x'] > x_limit:
            safe_y = True
        print("X-limit-Direct:",direct,"Safe Y:",safe_y)

        if direct and not safe_y:
            print('Moving directly')
            self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
        elif not direct and not safe_y:
            print('Not direct, not safe-y')
            self.set_absolute_coordinates(self.x_pos, self.y_pos, self.safe_height)
            self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], self.safe_height)
            self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
        elif not direct and safe_y:
            print('Not direct, safe-y')
            self.set_absolute_coordinates(self.x_pos, self.y_pos, self.safe_height)
            self.set_absolute_coordinates(self.x_pos, self.safe_y, self.safe_height)
            self.set_absolute_coordinates(target_coordinates['x'], self.safe_y, self.safe_height)
            self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], self.safe_height)
            self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
        elif direct and safe_y:
            print('Direct, safe-y')
            if up_first:
                print('up first')
                self.set_absolute_coordinates(self.x_pos, self.safe_y, target_coordinates['z'])
                self.set_absolute_coordinates(target_coordinates['x'], self.safe_y, target_coordinates['z'])
                self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
            else:
                print('not up first')
                self.set_absolute_coordinates(self.x_pos, self.safe_y, self.z_pos)
                self.set_absolute_coordinates(target_coordinates['x'], self.safe_y, self.z_pos)
                self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], self.z_pos)
                self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
        self.location = location
        print('Moved to:',self.location)
        return

    def save_location(self, location=False, new=False, ask=True):
        if new:
            location = self.main_window.popup_input('Save Location','Enter location name:')
            if location == '' or location == None:
                return
            self.calibration_data.update({location:{'x':self.x_pos,'y':self.y_pos,'z':self.z_pos}})
        elif not location and not new:
            location = self.main_window.popup_options('Save Location','Select location:',list(self.calibration_data.keys()))
            if location == None:
                return
            self.calibration_data[location] = {'x':self.x_pos,'y':self.y_pos,'z':self.z_pos}
        elif location and not new:
            if location not in self.calibration_data.keys():
                response = self.main_window.popup_yes_no('Location not present','Location {} not present in calibration data. Add?'.format(location))
                if response == '&No':
                    return
                self.calibration_data.update({location:{'x':self.x_pos,'y':self.y_pos,'z':self.z_pos}})
            else:
                self.calibration_data[location] = {'x':self.x_pos,'y':self.y_pos,'z':self.z_pos}
        self.location = location
        if ask:
            response = self.main_window.popup_yes_no('Save Location','Write location {} to file?'.format(location))
            if response == '&No':
                return
        with open(self.calibration_file_path, 'w') as outfile:
            json.dump(self.calibration_data, outfile)
        self.load_positions_from_file()
        self.main_window.popup_message('Location saved','Location {} saved to file'.format(location))

    def set_well_positions(self,well_positions):
        self.well_positions = well_positions

    def move_to_well(self,row,col):
        # Find the well position in the DataFrame
        well_position = self.well_positions[(self.well_positions['row'] == row) & (self.well_positions['column'] == col)]

        # If the well position is found, move to it
        if not well_position.empty:
            new_x = well_position['X'].values[0]
            new_y = well_position['Y'].values[0]
            new_z = well_position['Z'].values[0]
            self.set_absolute_coordinates(new_x, new_y, new_z)
        else:
            print(f"Coordinates for well ({row}, {col}) not found.")

    
    def print_array(self,array,ask=True):
        if not self.motors_active:
            self.main_window.popup_message('Motors not active','Motors must be active to print an array')
            return
        if not self.regulating_pressure:
            self.main_window.popup_message('Pressure not regulated','Pressure must be regulated to print an array')
            return
        if self.gripper_reagent.name == 'Empty':
            self.main_window.popup_message('No reagent loaded','A reagent must be loaded to print an array')
            return
        if self.main_window.full_array.empty:
            self.main_window.popup_message('No array loaded','Please load an array first')
            return
        if self.well_positions.empty:
            self.main_window.popup_message('No well positions','Well positions not calibrated. Please calibrate the plate to proceed')
            return
        
        if ask:
            response = self.main_window.popup_yes_no('Print array',message='Print an array? (y/n)')
            if response == '&No':
                print('Not printing')
                return

        self.main_window.actual_array = array.copy()

        self.close_gripper()
        self.wait_command()

        location = 'pause'
        self.move_to_location(location)
        self.change_acceleration(8000)
        
        current_reagent = self.gripper_reagent.name
        print('Current reagent:',current_reagent)
        reagent_array = array[array['reagent'] == current_reagent].copy()
        self.location = 'plate'
        for i,(index, line) in enumerate(reagent_array.iterrows()):
            if line['Added'] == True:
                continue
            print('Printing:', line['row'], line['column'], line['amount'])
            self.move_to_well(line['row'], line['column'])
            
            # Check if this is the last iteration
            is_last_iteration = i == len(reagent_array) - 1
            print('---Is last iteration:', is_last_iteration, i, len(reagent_array) - 1)
            if is_last_iteration:
                # Use a different handler for the last iteration
                self.print_droplets(int(line['amount']), handler=self.last_well_complete_handler, kwargs={'well_number': line['well_number'], 'reagent': current_reagent})
            else:
                self.print_droplets(int(line['amount']), handler=self.well_complete_handler, kwargs={'well_number': line['well_number'], 'reagent': current_reagent})
    
            