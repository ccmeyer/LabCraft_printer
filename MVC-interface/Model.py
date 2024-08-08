import pandas as pd
import numpy as np
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer

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
    def __init__(self):
        super().__init__()
        self.target_x = 0
        self.target_y = 0
        self.target_z = 0
        self.target_p = 0

        self.current_x = 0
        self.current_y = 0
        self.current_z = 0
        self.current_p = 0

        self.current_pressure = 0
        self.target_pressure = 0

    def update_target_position(self, x, y, z):
        self.target_x = x
        self.target_y = y
        self.target_z = z

    def update_target_p_motor(self, p):
        self.target_p = p

    def update_current_position(self, x, y, z):
        self.current_x = x
        self.current_y = y
        self.current_z = z

    def update_current_p_motor(self, p):
        self.current_p = p

    def update_current_pressure(self, pressure):
        self.current_pressure = pressure
    
    def update_target_pressure(self, pressure):
        self.target_pressure = pressure


class Model(QObject):
    '''
    Model class for the MVC architecture
    '''
    machine_state_updated = Signal()  # Signal to notify the view of state changes
    def __init__(self):
        super().__init__()
        self.machine_model = MachineModel()


    def update_state(self, status_dict):
        '''
        Update the state of the machine model
        '''
        self.machine_model.update_current_position(status_dict.get('X', self.machine_model.current_x),
                                                   status_dict.get('Y', self.machine_model.current_y),
                                                   status_dict.get('Z', self.machine_model.current_z))
        
        self.machine_model.update_current_p_motor(status_dict.get('P', self.machine_model.current_p))   
        self.machine_model.update_current_pressure(status_dict.get('Pressure', self.machine_model.current_pressure))
        self.machine_model.update_target_position(status_dict.get('Tar_X', self.machine_model.target_x),
                                                  status_dict.get('Tar_Y', self.machine_model.target_y),
                                                  status_dict.get('Tar_Z', self.machine_model.target_z))
        self.machine_model.update_target_p_motor(status_dict.get('Tar_P', self.machine_model.target_p))
        self.machine_model.update_target_pressure(status_dict.get('Tar_pressure', self.machine_model.target_pressure))
        self.machine_state_updated.emit()