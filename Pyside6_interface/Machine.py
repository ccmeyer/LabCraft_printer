import threading
import time
from PySide6 import QtCore, QtWidgets, QtGui

class Command():
    def __init__(self,command_number, command_string):
        self.command_number = command_number
        self.command_string = command_string
        self.timestamp = time.time()
    
    def get_number(self):
        return self.command_number
    
    def get_command(self):
        return self.command_string
    
    def get_timestamp(self):
        return self.timestamp

class Machine(QtWidgets.QWidget):
    command_executed = QtCore.Signal(Command)

    def __init__(self, app):
        super().__init__()
        print('Created Machine instance')
        self.app = app
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

        self.command_number = 0
        self.command_log = {self.command_number:Command(0, 'INITIALIZE')}
        self.command_number += 1

        self.update_interval = 0.1 # seconds
        self.update_thread = threading.Thread(target=self.update_states)
        self.update_thread.daemon = True
        self.update_thread.start()

    def get_command_number(self):
        return self.command_number
    
    def get_command_log(self):
        return self.command_log
    
    def execute_command(self, command):
        new_command = Command(self.command_number, command)
        self.command_log.update({self.command_number:new_command})
        print('Command executed:', command)
        self.command_executed.emit(new_command)
        self.command_number += 1
    
    def activate_motors(self):
        self.motors_active = True
        self.execute_command('ENABLE_MOTORS')

    def deactivate_motors(self):
        self.motors_active = False
        self.execute_command('DISABLE_MOTORS')
    
    def get_coordinates(self):
        return self.coordinates
    
    def get_target_coordinates(self):
        return self.target_coordinates
    
    def move_relative(self, relative_coordinates):
        if self.motors_active:
            for axis in ['X', 'Y', 'Z', 'P']:
                self.target_coordinates[axis] += relative_coordinates[axis]
            self.execute_command(f'RELATIVE_XYZ,{relative_coordinates["X"]},{relative_coordinates["Y"]},{relative_coordinates["Z"]}')
    
    
    def set_relative_pressure(self, pressure_change):
        self.target_pressure += pressure_change
        self.execute_command(f'RELATIVE_PRESSURE,{pressure_change}')
    
    def get_target_pressure(self):
        return self.target_pressure
    
    def get_pressure_log(self):
        return self.pressure_log

    def regulate_pressure(self):
        self.regulating_pressure = True
        self.execute_command('REGULATE_PRESSURE')

    def deregulate_pressure(self):
        self.regulating_pressure = False
        self.execute_command('DEGULATE_PRESSURE')
    
    def get_regulation_state(self):
        return self.regulating_pressure

    def update_states(self):
        while True:
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

            self.pressure_log.append(self.current_pressure)
            if len(self.pressure_log) > 100:
                self.pressure_log.pop(0)  # Remove the oldest reading
            time.sleep(self.update_interval)