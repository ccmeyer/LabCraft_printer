import time
import threading

class Machine():
    def __init__(self):
        print('Created Machine instance')
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
        self.pressure_log = []
        self.regulating_pressure = False

        self.update_interval = 0.1 # seconds
        self.update_thread = threading.Thread(target=self.update_states)
        self.update_thread.daemon = True
        self.update_thread.start()

        self.balance_port = 'Unknown'
        self.machine_port = 'Unknown'

        self.balance_connected = False
        self.machine_connected = False

    def update_states(self):
        while True:
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
    
    def get_com_ports(self):
        self.current_com_ports = ['COM1', 'COM2', 'COM3']
        return self.current_com_ports
    
    def refresh_com_ports(self):
        print('Refreshing COM ports')
        self.current_com_ports.append('COM4')
        return self.current_com_ports

    def set_balance_port(self, port):
        self.balance_port = port
    
    def set_machine_port(self, port):
        self.machine_port = port
    
    def connect_balance(self):
        if self.balance_port != 'COM1':
            print('Balance port not correctly set')
            return
        self.balance_connected = True
        print('Balance connected')
    
    def disconnect_balance(self):
        self.balance_connected = False
        print('Balance disconnected')
    
    def connect_machine(self):
        if self.machine_port != 'COM2':
            print('Machine port not correctly set')
            return
        self.machine_connected = True
        print('Machine connected')
    
    def disconnect_machine(self):
        self.machine_connected = False
        print('Machine disconnected')
    
    def is_connected(self):
        return self.machine_connected

    def activate_motors(self):
        if not self.machine_connected:
            print('Machine not connected')
            return
        self.motors_active = True
        print('Motors activated')
    
    def deactivate_motors(self):
        self.motors_active = False
        print('Motors deactivated')
    
    def get_coordinates(self):
        return self.coordinates
    
    def get_target_coordinates(self):
        return self.target_coordinates
    
    def move_relative(self, pos_changes):
        if not self.motors_active:
            print('Motors not activated')
            return
        self.target_coordinates['X'] += pos_changes['X']
        self.target_coordinates['Y'] += pos_changes['Y']
        self.target_coordinates['Z'] += pos_changes['Z']
        self.target_coordinates['P'] += pos_changes['P']
    
    def move_absolute(self, pos_changes):
        if not self.motors_active:
            print('Motors not activated')
            return
        self.target_coordinates['X'] = pos_changes['X']
        self.target_coordinates['Y'] = pos_changes['Y']
        self.target_coordinates['Z'] = pos_changes['Z']
        self.target_coordinates['P'] = pos_changes['P']

    def set_relative_pressure(self, pressure_change):
        self.target_pressure += pressure_change

    def set_absolute_pressure(self, pressure):
        self.target_pressure = pressure
