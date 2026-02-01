# legacy/mass_calibration.py
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6 import QtCore, QtWidgets, QtGui, QtCharts
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QGridLayout, QGroupBox, QPushButton, QComboBox, QSpinBox, QSizePolicy,
    QSpacerItem, QFileDialog, QInputDialog, QMessageBox, QAbstractItemView, QDialog,QLineEdit,QDoubleSpinBox
)
from PySide6.QtGui import QShortcut, QKeySequence, QPixmap, QColor, QPen, QBrush, QImage, QPainter, QIcon
from PySide6.QtCore import Qt, QTimer, QEventLoop, Signal, Slot
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QWidget, QGraphicsEllipseItem, QGraphicsScene, QGraphicsView, QGraphicsRectItem

import serial, re, os, time, json, glob
from scipy.optimize import fsolve
import numpy as np
import pandas as pd
import joblib
import random

from PySide6.QtGui import QShortcut, QKeySequence

class ShortcutManager:
    """Manage application shortcuts and their descriptions."""
    def __init__(self, parent):
        self.parent = parent
        self.shortcuts = []

    def add_shortcut(self, key_sequence, description, callback):
        """Add a shortcut to the application and store its description."""
        shortcut = QShortcut(QKeySequence(key_sequence), self.parent, activated=callback)
        self.shortcuts.append((key_sequence, description))
        return shortcut

    def get_shortcuts(self):
        """Return a list of shortcuts and their descriptions."""
        return self.shortcuts


class MassCalibrationModel(QObject):
    mass_updated_signal = Signal()
    initial_mass_captured_signal = Signal()
    calibration_complete_signal = Signal()
    change_volume_signal = Signal()
    
    def __init__(self, machine_model,printer_head_manager,rack_model,prediction_model_dir):
        super().__init__()
        self.machine_model = machine_model
        self.printer_head_manager = printer_head_manager
        self.rack_model = rack_model

        self.prediction_model_dir = prediction_model_dir
        self.model_metadata = self.read_all_model_metadata()

        self.prediction_model_path = None
        self.prediction_model = None
        self.resistance_model_path = None
        self.resistance_model = None
        self.selected_dir = None

        self.current_printer_head = None
        self.current_stock_id = None

        self.current_mass = 0
        self.mass_log = []
        self.stable_counter = 0
        self.mass_stable = False
        self.balance_tolerance = 0.01
        self.measurements = []
        self.current_measurement = {}
        self.measurement_stage = 'Complete'
        self.calibration_file_path = None
        self.standard_pulse_width = None

        self.rack_model.gripper_updated.connect(self.update_current_info)

    def read_all_model_metadata(self):
        """Read the metadata for all models in the prediction model directory and return a dictionary of the metadata.
        Each model is stored in a separate directory, with the metadata stored in a JSON file.
        The path to the predictive model and the resistance model are stored in the metadata."""
        model_metadata = {}
        print(f"Prediction model dir: {self.prediction_model_dir}")
        for model_dir in os.listdir(self.prediction_model_dir):
            print(f"Model dir: {model_dir}")
            metadata_path = os.path.join(self.prediction_model_dir, model_dir, "metadata.json")
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as file:
                    metadata = json.load(file)
                    model_metadata[model_dir] = metadata
            model_names = glob.glob(os.path.join(self.prediction_model_dir, model_dir, "*.pkl"))
            print(f"Model names: {model_names}")
            model_metadata[model_dir]['resistance_dir'] = [model for model in model_names if 'resistance' in model][0]
            model_metadata[model_dir]['prediction_dir'] = [model for model in model_names if 'resistance' not in model][0]

        print(f"Model metadata loaded: {model_metadata}")
        return model_metadata
    
    def get_all_model_names(self):
        """Return all the names of each model"""
        model_names = []
        for model_dir in self.model_metadata.keys():
            model_names.append(self.model_metadata[model_dir]['model_name'])
        return model_names
    
    def get_default_values(self):
        if self.selected_dir is not None:
            target_volume = self.model_metadata[self.selected_dir]['target_droplet_volume']
            printer_head_type = self.model_metadata[self.selected_dir]['printer_head_type']
            resistance_pulse_width = self.model_metadata[self.selected_dir]['resistance_pulse_width']
            standard_pressure = self.model_metadata[self.selected_dir]['standard_pressure']
            return target_volume, printer_head_type, resistance_pulse_width, standard_pressure

    def get_selected_model_path(self):
        return self.prediction_model_path

    def get_selected_resistance_model_path(self):
        return self.resistance_model_path
    
    def set_models_by_name(self,name):
        """Set the prediction and resistance models by name."""
        for model_dir in self.model_metadata.keys():
            if self.model_metadata[model_dir]['model_name'] == name:
                self.selected_dir = model_dir
                self.prediction_model_path = self.model_metadata[model_dir]['prediction_dir']
                self.resistance_model_path = self.model_metadata[model_dir]['resistance_dir']
                self.standard_pulse_width = self.model_metadata[model_dir]['resistance_pulse_width']
                self.load_prediction_models()
                return True
        return False

    def update_current_info(self):
        print('\n\n---Updating current info...\n\n')
        self.current_printer_head = self.rack_model.get_gripper_printer_head()
        if self.current_printer_head is not None:
            self.current_stock_id = self.current_printer_head.get_stock_id()
        else:
            self.current_stock_id = None

    def set_current_volume(self,volume):
        self.current_printer_head.set_absolute_volume(volume)
        self.change_volume_signal.emit()

    def change_current_volume(self, change):
        self.current_printer_head.change_volume(change)
        self.change_volume_signal.emit()

    def get_current_stock_id(self):
        #print(f'\n--Current stock ID: {self.current_stock_id}\n')
        return self.current_stock_id
    
    def get_current_printer_head_volume(self):
        if self.current_printer_head is not None:
            return self.current_printer_head.get_current_volume()
        else:
            return 0

    def update_mass(self, mass):
        self.add_mass_to_log(mass)
        self.mass_updated_signal.emit()

    def add_mass_to_log(self, mass):
        self.mass_log.append(mass)
        if len(self.mass_log) > 100:
            self.mass_log.pop(0)
        if len(self.mass_log) > 10:
            self.current_mass = round(np.mean(self.mass_log[-10:]),3)
        else:
            self.current_mass = round(np.mean(self.mass_log),3)
        self.check_mass_stability()

    def check_mass_stability(self):
        if len(self.mass_log) > 20:
            recent_mass = self.mass_log[-20:]
            mass_std = np.std(recent_mass)
            if mass_std < self.balance_tolerance:
                self.stable_counter += 1
                if self.stable_counter > 30:
                    self.mass_stable = True
                    if self.measurement_stage == 'Initial':
                        self.current_measurement['initial_mass'] = self.current_mass
                        self.measurement_stage = 'Waiting'
                        self.initial_mass_captured_signal.emit()
                    elif self.measurement_stage == 'Final':
                        self.current_measurement['final_mass'] = self.current_mass
                        self.complete_measurement()
            else:
                self.stable_counter = 0
                self.mass_stable = False
        else:
            self.mass_stable = False

    def get_current_mass(self):
        return self.current_mass

    def get_mass_log(self):
        return self.mass_log
    
    def is_mass_stable(self):
        return self.mass_stable
    
    def initiate_new_measurement(self, measurement_type,calibration_droplets,stock_id=None,starting_volume=None,pulse_width=None,target_pressure=None,target_volume=None,applied_bias=0):
        if pulse_width is None:
            pulse_width = self.machine_model.get_print_pulse_width()
        if target_pressure is None:
            target_pressure = self.machine_model.get_target_print_pressure()
        if stock_id is None:
            stock_id = self.current_stock_id
        if starting_volume is None:
            starting_volume = self.get_current_printer_head_volume()

        if measurement_type == 'resistance':
            pulse_width = self.standard_pulse_width
        
        self.current_measurement = {
            'model_name':self.model_metadata[self.selected_dir]['model_name'],
            'measurement_type':measurement_type,
            'stock_id':stock_id,
            "starting_volume": starting_volume,
            "initial_mass": 0,
            "final_mass": 0,
            "mass_difference": 0,
            "droplet_volume": 0,
            "pressure": target_pressure,
            "pulse_width": pulse_width,
            "droplets": calibration_droplets,
            "target_volume": target_volume,
            "syringe_position": self.machine_model.get_current_p_motor(),
            "applied_bias": applied_bias,
            "bias": None,
            "completed": False
        }
        self.measurement_stage = 'Initial'

    def check_for_final_mass(self):
        print('Checking for final mass...')
        if self.measurement_stage == 'Waiting':
            self.measurement_stage = 'Final'

    def complete_measurement(self):
        self.current_measurement['mass_difference'] = self.current_measurement['final_mass'] - self.current_measurement['initial_mass']
        self.current_measurement['droplet_volume'] = round((self.current_measurement['mass_difference'] / self.current_measurement['droplets']) * 1000,2)
        self.current_measurement['completed'] = True
        if self.current_measurement['measurement_type'] == 'predicted':
            self.current_measurement['bias'] = self.current_measurement['droplet_volume'] - self.current_measurement['target_volume']
        self.change_current_volume(-self.current_measurement['mass_difference'])
        self.apply_calibrations_to_printer_head(self.current_measurement['stock_id'])
        #print(f'Completed measurement: {self.current_measurement}')

        self.measurements.append(self.current_measurement)
        self.current_measurement = {}
        self.measurement_stage = 'Complete'
        self.calibration_complete_signal.emit()
        self.save_calibration_data(self.calibration_file_path)

    def get_last_droplet_volume(self):
        for m in reversed(self.measurements):
            if m['stock_id'] == self.current_stock_id:
                return m['droplet_volume']
        return 0
    
    def update_calibration_file_path(self, file_path):
        self.calibration_file_path = file_path

    def create_calibration_file(self, file_path):
        self.calibration_file_path = file_path
        self.remove_all_calibrations()
        with open(file_path, 'w') as file:
            json.dump([], file)
        #print(f"Calibration file created at {file_path}")

    def save_calibration_data(self, file_path):
        """Save the calibration data as a JSON file."""
        pass
        # with open(file_path, 'w') as file:
        #     json.dump(self.measurements, file, indent=4)
        #print(f"Calibration data saved to {file_path}")

    def load_calibration_data(self, file_path):
        """Load the calibration data from a JSON file."""
        self.calibration_file_path = file_path
        with open(file_path, 'r') as file:
            self.measurements = json.load(file)
        self.apply_calibrations_to_all_printer_heads()
        #print(f"Calibration data loaded from {file_path}")

    def apply_calibrations_to_all_printer_heads(self):
        for printer_head in self.printer_head_manager.get_all_printer_heads():
            self.apply_calibrations_to_printer_head(printer_head.get_stock_id())

    def apply_calibrations_to_printer_head(self,stock_id):
        resistance = self.calculate_resistance_for_stock(stock_id)
        bias = self.calculate_bias(stock_id)
        target_droplet_volume = self.get_target_droplet_volume_for_stock(stock_id)
        model_name = self.get_last_model_name(stock_id=stock_id)
        if model_name is not None:
            prediction_model_path = self.get_prediction_model_path_from_name(model_name)
            resistance_model_path = self.get_resistance_model_path_from_name(model_name)
            if prediction_model_path is not None and resistance_model_path is not None:
                prediction_model = joblib.load(prediction_model_path)
                resistance_model = joblib.load(resistance_model_path)
            resistance_pulse_width = self.get_resistance_pulse_width_from_name(model_name)
        printer_head = self.printer_head_manager.get_printer_head_by_id(stock_id)
        printer_head.set_calibration_data(resistance,bias,target_droplet_volume,prediction_model,resistance_model,resistance_pulse_width)

    def get_measurements(self):
        return [[m['pressure'],m['pulse_width'],m['droplets'],m['droplet_volume']] for m in self.measurements if m['stock_id'] == self.current_stock_id]
    
    def get_last_model_name(self,stock_id=None):
        if stock_id is None:
            stock_id = self.current_stock_id
        current_measurements = [m for m in self.measurements if m['stock_id'] == stock_id]
        if len(current_measurements) > 0:
            return current_measurements[-1]['model_name']
        elif len(self.measurements) > 0:
            return self.measurements[-1]['model_name']
        elif self.selected_dir is not None:
            return self.model_metadata[self.selected_dir]['model_name']
        else:
            return '65um low viscosity'
            # return self.model_metadata[list(self.model_metadata.keys())[0]]['model_name']

    def get_prediction_model_path_from_name(self,name):
        for model_dir in self.model_metadata.keys():
            if self.model_metadata[model_dir]['model_name'] == name:
                return self.model_metadata[model_dir]['prediction_dir']
        return None

    def get_resistance_model_path_from_name(self,name):
        for model_dir in self.model_metadata.keys():
            if self.model_metadata[model_dir]['model_name'] == name:
                return self.model_metadata[model_dir]['resistance_dir']
        return None

    def get_resistance_pulse_width_from_name(self,name):
        for model_dir in self.model_metadata.keys():
            if self.model_metadata[model_dir]['model_name'] == name:
                return self.model_metadata[model_dir]['resistance_pulse_width']
        return None

    def remove_last_measurement(self):
        """Removes the last measurement."""
        if len(self.measurements) > 0:
            if self.measurements[-1]['stock_id'] == self.current_stock_id:
                self.measurements.pop()
                self.calibration_complete_signal.emit()
            else:
                print('Last measurement does not match stock ID')
        else:
            print('No measurements to remove')

        self.save_calibration_data(self.calibration_file_path)

    def remove_all_calibrations_for_stock(self,):
        """Removes all measurements for the specified stock ID."""
        self.measurements = [m for m in self.measurements if m['stock_id'] != self.current_stock_id]
        self.calibration_complete_signal.emit()
        self.save_calibration_data(self.calibration_file_path)

    def remove_all_calibrations(self):
        """Removes all measurements."""
        self.measurements = []
        self.calibration_complete_signal.emit()
        self.save_calibration_data(self.calibration_file_path)

    def load_prediction_models(self):
        """Load the prediction model from the specified file path."""
        self.prediction_model = joblib.load(self.prediction_model_path)
        self.resistance_model = joblib.load(self.resistance_model_path)

    def calculate_resistance_for_stock(self,stock_id):
        stock_measurements = [m for m in self.measurements if m['stock_id'] == stock_id]
        if len(stock_measurements) == 0:
            #print(f"No measurements found for stock '{stock_id}'")
            return None
        stock_data = pd.DataFrame(stock_measurements)
        standard_data = stock_data[stock_data['pulse_width'] == self.standard_pulse_width].copy()
        if len(standard_data) == 0:
            print(f"No standard measurements found for stock '{stock_id}'")
            return None
        res_df = standard_data[['starting_volume','droplet_volume']].copy().rename(columns={'starting_volume':'resistance_volume','droplet_volume':'resistance'})
        res_df['effective_resistance'] = self.resistance_model.predict(res_df)
        resistance = res_df['effective_resistance'].mean()
        #print(f"\nEffective resistance for stock '{stock_id}': {resistance:.2f} nL\n")
        return round(resistance,2)
    
    def calculate_bias(self,stock_id):
        stock_measurements = [m for m in self.measurements if m['stock_id'] == stock_id]
        if len(stock_measurements) == 0:
            #print(f"No measurements found for stock '{stock_id}'")
            return None
        stock_data = pd.DataFrame(stock_measurements).dropna(subset=['bias'])
        if len(stock_data) == 0:
            #print(f"No bias measurements found for stock '{stock_id}'")
            return None
        stock_data['total_bias'] = stock_data['bias'] + stock_data['applied_bias']
        num_measurements = len(stock_data)
        if num_measurements < 3:
            bias = stock_data['total_bias'].mean()
        else:
            bias = stock_data['total_bias'].iloc[-3:].mean()
            
        print(f"Bias for stock '{stock_id}': {bias:.2f} nL")
        return round(bias,2)
    
    def get_target_droplet_volume_for_stock(self,stock_id):
        stock_measurements = [m for m in self.measurements if m['stock_id'] == stock_id]
        if len(stock_measurements) == 0:
            #print(f"No measurements found for stock '{stock_id}'")
            return None
        stock_data = pd.DataFrame(stock_measurements).dropna(subset=['target_volume'])
        if len(stock_data) == 0:
            #print(f"No target volume measurements found for stock '{stock_id}'")
            return None
        target_droplet_volume = stock_data.iloc[-1]['target_volume']
        #print(f"Target droplet volume for stock '{stock_id}': {target_droplet_volume:.2f} nL")
        return target_droplet_volume
    
    def predict_pulse_width_for_droplet(self, target_droplet_volume,calc_bias=True):
        total_volume = self.get_current_printer_head_volume()
        resistance = self.calculate_resistance_for_stock(self.current_stock_id)
        if resistance is None:
            return self.standard_pulse_width
        if calc_bias:
            bias = self.calculate_bias(self.current_stock_id)
            if bias is None:
                bias = 0
        else:
            bias = 0
        pulse_width = self.predict_pulse_width(total_volume, resistance, target_droplet_volume,bias=bias)
        #print(f"Required pulse width for {target_droplet_volume} nL droplet: {pulse_width:.2f} µs")
        return pulse_width, bias
    
    def predict_pulse_width(self, total_volume, effective_resistance, target_droplet_volume,bias=0,prediction_model=None,resistance_pulse_width=None):
        if prediction_model is None:
            prediction_model = self.prediction_model
        if resistance_pulse_width is None:
            standard_pulse_width = self.standard_pulse_width
        else:
            standard_pulse_width = resistance_pulse_width
        def func(pulse_width):
            input_features = pd.DataFrame({
                'pulse_width': [pulse_width],
                'starting_volume': [total_volume],
                'effective_resistance': [effective_resistance]
            })
            predicted_volume = prediction_model.predict(input_features)[0] + bias
            return predicted_volume - target_droplet_volume

        # Initial guess for pulse width
        initial_guess = standard_pulse_width
        pulse_width_solution = fsolve(func, initial_guess)
        return round(pulse_width_solution[0],0)



class Balance(QObject):
    connected_signal = Signal(bool)
    balance_mass_updated_signal = Signal(float)
    balance_error_signal = Signal(str, str)   # (title, message)

    def __init__(self, machine, model,baud=9600, probe_cmd=b"SI\r\n", probe_timeout_s=1.0):
        super().__init__()
        self.machine = machine
        self.model = model
        self.baud = baud
        self.probe_cmd = probe_cmd
        self.probe_timeout_s = probe_timeout_s

        self.connected = False
        self.ser = None
        self.port = None

        self.simulate = True
        self.error_count = 0
        self.current_mass = 0.0
        self.target_mass = 0.0
        self.mass_update_timer = None
        self.mass_log = []

        self.prediction_model = None
        self.resistance_model = None
        self.target_volume = None
        self.resistance_dict = {}

    def connect_balance(self, port: str) -> bool:
        if port == "Virtual":
            self.connected = True
            self.simulate = True
            self.mass_simulate_timer = QTimer()
            self.mass_simulate_timer.timeout.connect(self.update_simulated_mass)
            self.mass_simulate_timer.start(10)
            self.begin_reading()
            self.connected_signal.emit(True)
            return True

        try:
            self.port = port
            self.ser = serial.Serial(self.port, baudrate=self.baud, bytesize=8, timeout=2, stopbits=serial.STOPBITS_ONE)
            if not self.ser.is_open:
                raise serial.SerialException("Could not open port")
            self.connected = True
            self.simulate = False
            self.begin_reading()
            self.connected_signal.emit(True)
            return True
        except Exception as e:
            self.connected = False
            self.connected_signal.emit(False)
            self.balance_error_signal.emit("Balance connection error", f"Could not connect to balance at {port}: {e}")
            return False

    def update_prediction_models(self, prediction_model_path, resistance_model_path, target_volume):
        self.prediction_model = joblib.load(prediction_model_path)
        self.resistance_model = joblib.load(resistance_model_path)
        self.target_volume = target_volume

    def begin_reading(self):
        self.mass_update_timer = QTimer()
        self.mass_update_timer.timeout.connect(self.get_mass)
        self.mass_update_timer.start(20)

    def close_connection(self):
        try:
            if not self.simulate and self.ser is not None and self.ser.is_open:
                self.ser.close()
            if self.simulate and hasattr(self, "mass_simulate_timer"):
                self.mass_simulate_timer.stop()
            if self.mass_update_timer:
                self.mass_update_timer.stop()
        finally:
            self.connected_signal.emit(False)
            self.connected = False

    @Slot()
    def get_mass(self):
        if not self.simulate:
            if self.ser and self.ser.in_waiting > 0:
                data = self.ser.readline()
                try:
                    data = data.decode("ASCII")
                    sign, mass = re.findall(r"(-?) *([0-9]+\.[0-9]+) [a-zA-Z]*", data)[0]
                    mass = float("".join([sign, mass]))
                    self.current_mass = mass
                    self._add_to_log(self.current_mass)
                    # print(f"Balance mass: {self.current_mass}")
                    self.balance_mass_updated_signal.emit(self.current_mass)
                except Exception:
                    self.error_count += 1
                    print(f"Balance read error #{self.error_count}")
                    if self.error_count > 100:
                        self.close_connection()
                        self.balance_error_signal.emit("Balance error", "Lost connection to balance")
        else:
            self._add_to_log(self.current_mass)
            print(f"Simulated mass: {self.current_mass}")
            self.balance_mass_updated_signal.emit(self.current_mass)

    def _add_to_log(self, mass):
        self.mass_log.append(mass)
        if len(self.mass_log) > 100:
            self.mass_log.pop(0)

    # --- your existing simulate_mass/update_simulated_mass can stay the same ---
    def simulate_mass(self, num_droplets, pulse_width):
        printer_head = self.model.rack_model.get_gripper_printer_head()
        if printer_head is None or self.prediction_model is None:
            return 0.0

        current_id = printer_head.get_stock_id()
        if current_id not in self.resistance_dict:
            tv = self.target_volume or 40
            resistance = np.random.randint(tv - 10, tv + 30) if tv > 50 else np.random.randint(tv - 15, tv + 10)
            self.resistance_dict[current_id] = resistance

        effective_resistance = self.resistance_dict[current_id]
        current_volume, _, _, _, _, _, _ = printer_head.get_prediction_data()

        input_features = pd.DataFrame({
            "pulse_width": [pulse_width],
            "starting_volume": [current_volume],
            "effective_resistance": [effective_resistance]
        })
        predicted_volume = self.prediction_model.predict(input_features)[0]
        mass = predicted_volume * num_droplets / 1000.0
        mass += np.random.normal(0, 0.005)
        return float(mass)

    @Slot()
    def update_simulated_mass(self):
        if self.machine.balance_droplets:
            time.sleep(0.5)
            num_droplets, pulse_width = self.machine.balance_droplets.pop(0)
            mass = self.simulate_mass(num_droplets, pulse_width)
            self.target_mass += mass

        if self.current_mass < self.target_mass:
            self.current_mass += 0.01

class MassCalibrationDialog(QtWidgets.QDialog):
    popup_message_signal = QtCore.Signal(str,str)
    def __init__(self, main_window,model,controller):
        super().__init__()
        self.main_window = main_window
        self.color_dict = self.main_window.color_dict
        self.model = model
        self.controller = controller

        self.controller.enter_print_mode()

        self.num_calibration_droplets = 50
        self.repeat_measurements = 0
        self.pressures_to_screen = []
        self.current_set_pulse_width = 3100
        self.test_started = False

        self.setWindowTitle("Mass Calibration")
        self.resize(1200, 700)

        self.layout = QtWidgets.QVBoxLayout()
        self.label = QtWidgets.QLabel("Begin the mass calibration")
        self.layout.addWidget(self.label)

        self.charts_layout = QtWidgets.QHBoxLayout()

        # Create a series and chart to display mass over time
        self.series = QtCharts.QLineSeries()
        self.series.setColor(QtCore.Qt.white)
        self.chart = QtCharts.QChart()
        self.chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.chart.setBackgroundBrush(QtGui.QBrush(self.color_dict['dark_gray']))  # Set the background color to grey
        self.chart.addSeries(self.series)
        # self.chart.createDefaultAxes()
        self.chart.setTitle("Mass over time")

        self.axisX = QtCharts.QValueAxis()
        self.axisX.setTickCount(3)
        self.axisX.setRange(0, 300)
        self.axisY = QtCharts.QValueAxis()
        self.axisY.setTitleText("Mass (mg)")

        self.chart.addAxis(self.axisX, QtCore.Qt.AlignBottom)
        self.chart.addAxis(self.axisY, QtCore.Qt.AlignLeft)
        self.series.attachAxis(self.axisX)
        self.series.attachAxis(self.axisY)

        # Create a chart view to display the chart
        self.chart_view = QtCharts.QChartView(self.chart)
        self.chart_view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.chart.legend().hide()  # Hide
        self.chart_view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.chart_view.setFocusPolicy(QtCore.Qt.NoFocus)

        # Add the chart view to the layout
        self.charts_layout.addWidget(self.chart_view)

        self.volume_pressure_series = QtCharts.QScatterSeries()
        self.volume_pressure_series.setColor(QtCore.Qt.white)
        self.volume_pressure_series.setMarkerSize(3.0)
        self.volume_pressure_chart = QtCharts.QChart()
        self.volume_pressure_chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.volume_pressure_chart.setBackgroundBrush(QtGui.QBrush(self.color_dict['dark_gray']))  # Set the background color to grey
        self.volume_pressure_chart.addSeries(self.volume_pressure_series)
        self.volume_pressure_chart.setTitle("Mass versus Pressure")

        self.volume_pressure_axisX = QtCharts.QValueAxis()
        self.volume_pressure_axisX.setTitleText("Pulse Width (us)")
        self.volume_pressure_axisY = QtCharts.QValueAxis()
        self.volume_pressure_axisY.setTitleText("Volume (nL)")

        self.volume_pressure_chart.addAxis(self.volume_pressure_axisX, QtCore.Qt.AlignBottom)
        self.volume_pressure_chart.addAxis(self.volume_pressure_axisY, QtCore.Qt.AlignLeft)
        self.volume_pressure_series.attachAxis(self.volume_pressure_axisX)
        self.volume_pressure_series.attachAxis(self.volume_pressure_axisY)
       
        # Add a series for the last measurement
        self.last_measurement_series = QtCharts.QScatterSeries()
        self.last_measurement_series.setColor(QtCore.Qt.red)
        self.last_measurement_series.setMarkerSize(5.0)
        self.volume_pressure_chart.addSeries(self.last_measurement_series)
        self.last_measurement_series.attachAxis(self.volume_pressure_axisX)
        self.last_measurement_series.attachAxis(self.volume_pressure_axisY)


        # Create a series for the linear fit
        self.linear_fit_series = QtCharts.QLineSeries()
        self.linear_fit_series.setColor(QtCore.Qt.red)
        self.volume_pressure_chart.addSeries(self.linear_fit_series)
        self.linear_fit_series.attachAxis(self.volume_pressure_axisX)
        self.linear_fit_series.attachAxis(self.volume_pressure_axisY)

        # Ensure proper pen settings for each line
        line_pen = QtGui.QPen(QtCore.Qt.black)
        line_pen.setWidth(1)

        # Add horizontal lines using QLineSeries
        # Target line at 40 nL (red)
        target_line = QtCharts.QLineSeries()
        target_line.setColor(QtCore.Qt.red)
        target_line.append(0, 40)  # Starting point of the line at (0, 40)
        target_line.append(10000, 40)  # Ending point of the line at (5, 40)
        self.volume_pressure_chart.addSeries(target_line)
        target_line.attachAxis(self.volume_pressure_axisX)
        target_line.attachAxis(self.volume_pressure_axisY)

        # Line above target at 41 nL (black)
        above_target_line = QtCharts.QLineSeries()
        above_target_line.setPen(line_pen)  # Apply custom pen for consistent color and width
        above_target_line.append(0, 41)
        above_target_line.append(10000, 41)
        self.volume_pressure_chart.addSeries(above_target_line)
        above_target_line.attachAxis(self.volume_pressure_axisX)
        above_target_line.attachAxis(self.volume_pressure_axisY)

        # Line below target at 39 nL (black)
        below_target_line = QtCharts.QLineSeries()
        below_target_line.setPen(line_pen)  # Apply custom pen for consistent color and width
        below_target_line.append(0, 39)
        below_target_line.append(10000, 39)
        self.volume_pressure_chart.addSeries(below_target_line)
        below_target_line.attachAxis(self.volume_pressure_axisX)
        below_target_line.attachAxis(self.volume_pressure_axisY)

        # Create a chart view to display the chart
        self.volume_pressure_chart_view = QtCharts.QChartView(self.volume_pressure_chart)
        self.volume_pressure_chart_view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.volume_pressure_chart.legend().hide()  # Hide the legend
        self.volume_pressure_chart_view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.volume_pressure_chart_view.setFocusPolicy(QtCore.Qt.NoFocus)

        # Add the chart view to the layout
        self.charts_layout.addWidget(self.volume_pressure_chart_view)

        row = 0

        self.user_input_layout = QtWidgets.QGridLayout()

        self.current_stock_label = QtWidgets.QLabel("Current Stock Solution:")
        self.current_stock_value = QtWidgets.QLabel(self.model.calibration_model.get_current_stock_id())
        self.user_input_layout.addWidget(self.current_stock_label, row, 0)
        self.user_input_layout.addWidget(self.current_stock_value, row, 1)
        row += 1

        # Add a combo box to select the desired predictive model
        self.model_label = QtWidgets.QLabel("Predictive Model:")
        self.model_combobox = QtWidgets.QComboBox()
        model_names = self.model.calibration_model.get_all_model_names()
        self.model_combobox.addItems(model_names)
        self.model_combobox.currentIndexChanged.connect(self.handle_model_change)
        self.user_input_layout.addWidget(self.model_label, row, 0)
        self.user_input_layout.addWidget(self.model_combobox, row, 1)
        row += 1

        self.current_volume_label = QtWidgets.QLabel("Current Volume:")
        current_volume = self.model.calibration_model.get_current_printer_head_volume()
        if current_volume == None:
            current_volume = 0
        self.current_volume_value = QtWidgets.QLabel(f"{current_volume:.2f} uL")
        self.user_input_layout.addWidget(self.current_volume_label, row, 0)
        self.user_input_layout.addWidget(self.current_volume_value, row, 1)
        row += 1

        self.set_volume_label = QtWidgets.QLabel("Set Volume:")
        self.set_volume_spinbox = QtWidgets.QDoubleSpinBox()
        self.set_volume_spinbox.setDecimals(1)
        self.set_volume_spinbox.setSingleStep(10)
        self.set_volume_spinbox.setRange(0, 1000)
        self.set_volume_spinbox.setValue(100)
        self.user_input_layout.addWidget(self.set_volume_label, row, 0)
        self.user_input_layout.addWidget(self.set_volume_spinbox, row, 1)
        row += 1

        self.set_volume_button = QtWidgets.QPushButton("Set Volume")
        self.set_volume_button.clicked.connect(self.set_volume)
        self.user_input_layout.addWidget(self.set_volume_button, row, 0, 1, 2)
        row += 1

        self.target_drop_volume_label = QtWidgets.QLabel("Target Droplet Volume:")
        self.target_drop_volume_spinbox = QtWidgets.QDoubleSpinBox()
        self.target_drop_volume_spinbox.setDecimals(1)
        self.target_drop_volume_spinbox.setSingleStep(1)
        self.target_drop_volume_spinbox.setRange(1, 100)
        self.target_drop_volume_spinbox.setValue(40)
        self.target_drop_volume_spinbox.valueChanged.connect(self.handle_target_drop_volume_change)
        self.user_input_layout.addWidget(self.target_drop_volume_label, row, 0)
        self.user_input_layout.addWidget(self.target_drop_volume_spinbox, row, 1)
        row += 1

        self.resistance_calibration_button = QtWidgets.QPushButton("Resistance Calibration")
        self.resistance_calibration_button.clicked.connect(self.initiate_resistance_calibration)
        self.user_input_layout.addWidget(self.resistance_calibration_button, row, 0, 1, 2)
        row += 1

        self.predict_pulse_width_button = QtWidgets.QPushButton("Predict pulse")
        self.predict_pulse_width_button.clicked.connect(self.evaluate_predicted_pulse_width)
        self.user_input_layout.addWidget(self.predict_pulse_width_button, row, 0, 1, 2)
        row += 1

        self.predict_pulse_width_no_bias_button = QtWidgets.QPushButton("Predict pulse no bias")
        self.predict_pulse_width_no_bias_button.clicked.connect(self.evaluate_predict_pulse_width_no_bias)
        self.user_input_layout.addWidget(self.predict_pulse_width_no_bias_button, row, 0, 1, 2)
        row += 1

        self.current_pressure_label = QtWidgets.QLabel("Current Pressure:")
        self.current_pressure_value = QtWidgets.QLabel()
        self.user_input_layout.addWidget(self.current_pressure_label, row, 0)
        self.user_input_layout.addWidget(self.current_pressure_value, row, 1)
        row += 1

        self.target_pressure_label = QtWidgets.QLabel("Target Pressure:")
        self.target_pressure_spinbox = QtWidgets.QDoubleSpinBox()
        self.target_pressure_spinbox.setDecimals(2)
        self.target_pressure_spinbox.setSingleStep(0.1)
        self.target_pressure_spinbox.setRange(0, 5)
        self.target_pressure_spinbox.valueChanged.connect(self.handle_target_pressure_change)
       
        self.user_input_layout.addWidget(self.target_pressure_label, row, 0)
        self.user_input_layout.addWidget(self.target_pressure_spinbox, row, 1)
        row += 1

        self.pulse_width_label = QtWidgets.QLabel("Pulse Width:")
        self.pulse_width_spinbox = QtWidgets.QSpinBox()
        self.pulse_width_spinbox.setRange(10, 10000)
        self.pulse_width_spinbox.setSingleStep(5)
        self.pulse_width_spinbox.setValue(4200)
        self.pulse_width_spinbox.valueChanged.connect(self.handle_pulse_width_change)
        self.user_input_layout.addWidget(self.pulse_width_label, row, 0)
        self.user_input_layout.addWidget(self.pulse_width_spinbox, row, 1)
        row += 1

        self.num_droplets_label = QtWidgets.QLabel("Number of Droplets:")
        self.num_droplets_spinbox = QtWidgets.QSpinBox()
        self.num_droplets_spinbox.setRange(1, 100)
        self.num_droplets_spinbox.setSingleStep(5)
        self.num_droplets_spinbox.setValue(50)
        self.num_droplets_spinbox.valueChanged.connect(self.handle_num_droplets_change)
        self.user_input_layout.addWidget(self.num_droplets_label, row, 0)
        self.user_input_layout.addWidget(self.num_droplets_spinbox, row, 1)
        row += 1

        self.calibrate_button = QtWidgets.QPushButton("Calibrate")
        self.calibrate_button.clicked.connect(self.initiate_calibration_process)
        self.user_input_layout.addWidget(self.calibrate_button, row, 0, 1, 2)
        row += 1

        self.pressure_screen_low_label = QtWidgets.QLabel("Screen Low:")
        self.pressure_screen_low_spinbox = QtWidgets.QDoubleSpinBox()
        self.pressure_screen_low_spinbox.setDecimals(0)
        self.pressure_screen_low_spinbox.setSingleStep(10)
        self.pressure_screen_low_spinbox.setRange(10,7000)
        self.pressure_screen_low_spinbox.setValue(3500)
        # self.pressure_screen_low_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.user_input_layout.addWidget(self.pressure_screen_low_label, row, 0)
        self.user_input_layout.addWidget(self.pressure_screen_low_spinbox, row, 1)
        row += 1

        self.pressure_screen_high_label = QtWidgets.QLabel("Screen High:")
        self.pressure_screen_high_spinbox = QtWidgets.QDoubleSpinBox()
        self.pressure_screen_high_spinbox.setDecimals(0)
        self.pressure_screen_high_spinbox.setSingleStep(10)
        self.pressure_screen_high_spinbox.setRange(10, 7000)
        self.pressure_screen_high_spinbox.setValue(4500)
        # self.pressure_screen_high_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.user_input_layout.addWidget(self.pressure_screen_high_label, row, 0)
        self.user_input_layout.addWidget(self.pressure_screen_high_spinbox, row, 1)
        row += 1

        self.repeat_measurement_label = QtWidgets.QLabel("Repeat Measurements:")
        self.repeat_measurement_spinbox = QtWidgets.QSpinBox()
        self.repeat_measurement_spinbox.setRange(1, 100)
        self.repeat_measurement_spinbox.setSingleStep(1)
        self.repeat_measurement_spinbox.setValue(3)
        # self.repeat_measurement_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.user_input_layout.addWidget(self.repeat_measurement_label, row, 0)
        self.user_input_layout.addWidget(self.repeat_measurement_spinbox, row, 1)
        row += 1
       
        self.repeat_measurement_button = QtWidgets.QPushButton("Repeat Measurement")
        self.repeat_measurement_button.clicked.connect(self.initiate_repeat_calibration_process)
        self.user_input_layout.addWidget(self.repeat_measurement_button, row, 0, 1, 2)
        row += 1

        self.start_screen_button = QtWidgets.QPushButton("Start Screen")
        self.start_screen_button.clicked.connect(self.start_screen)
        self.user_input_layout.addWidget(self.start_screen_button, row, 0, 1, 2)
        row += 1

        self.stop_repeat_measurement_button = QtWidgets.QPushButton("Stop Repeating")
        self.stop_repeat_measurement_button.clicked.connect(self.stop_repeat_calibration_process)
        self.user_input_layout.addWidget(self.stop_repeat_measurement_button, row, 0, 1, 2)
        row += 1

        self.remove_last_measurement_button = QtWidgets.QPushButton("Remove Last")
        self.remove_last_measurement_button.clicked.connect(self.remove_last_measurement)
        self.user_input_layout.addWidget(self.remove_last_measurement_button, row, 0, 1, 2)
        row += 1

        self.remove_all_calibrations_button = QtWidgets.QPushButton("Remove All")
        self.remove_all_calibrations_button.clicked.connect(self.remove_all_calibrations_for_stock)
        self.user_input_layout.addWidget(self.remove_all_calibrations_button, row, 0, 1, 2)
        row += 1

        self.results_label = QtWidgets.QLabel("Calibration Results:")
        self.results_value = QtWidgets.QLabel()
        self.user_input_layout.addWidget(self.results_label, row, 0)
        self.user_input_layout.addWidget(self.results_value, row, 1)
        row += 1


        # Add the grid layout into a QVBoxLayout
        self.user_input_container_layout = QtWidgets.QVBoxLayout()
        self.user_input_container_layout.addLayout(self.user_input_layout)
        self.user_input_container_layout.addStretch()  # Add a stretch at the bottom to push everything up

        # Add the QVBoxLayout to the charts_layout without alignment argument
        self.charts_layout.addLayout(self.user_input_container_layout)

        # Set the alignment to top after adding the layout
        self.charts_layout.setAlignment(self.user_input_container_layout, QtCore.Qt.AlignTop)

        self.layout.addLayout(self.charts_layout)
        self.setLayout(self.layout)

        self.model.calibration_model.mass_updated_signal.connect(self.update_mass_time_plot)
        self.model.machine_model.printing_parameters_updated.connect(self.update_printing_parameters)
        self.model.calibration_model.initial_mass_captured_signal.connect(self.initiate_calibration_print)
        self.model.calibration_model.calibration_complete_signal.connect(self.handle_calibration_complete)
        self.model.calibration_model.change_volume_signal.connect(self.update_volume)
        self.popup_message_signal.connect(self.main_window.popup_message)

       
        last_model_name = self.model.calibration_model.get_last_model_name()
        if last_model_name in model_names:
            self.model_combobox.setCurrentText(last_model_name)
        self.handle_model_change(self.model_combobox.currentIndex())

        self.update_printing_parameters()
        self.update_volume_pressure_plot()

    def add_horizontal_line(self, y_value, color=QtCore.Qt.black, pen=None):
        """
        Adds a horizontal line to the given chart at the specified y_value.

        :param chart: The chart to which the line will be added.
        :param axisX: The X axis to attach the line to.
        :param axisY: The Y axis to attach the line to.
        :param y_value: The y-coordinate at which the line will be drawn.
        :param color: The color of the line. Default is black.
        :param pen: Optional QPen object to customize the line's appearance.
        """
        line_series = QtCharts.QLineSeries()
        if pen:
            line_series.setPen(pen)
        else:
            line_series.setColor(color)
        line_series.append(0, y_value)
        line_series.append(10000, y_value)
        self.volume_pressure_chart.addSeries(line_series)
        line_series.attachAxis(self.volume_pressure_axisX)
        line_series.attachAxis(self.volume_pressure_axisY)

    def add_target_volume_lines(self,target_volume,tolerance=0.03):
        line_pen = QtGui.QPen(QtCore.Qt.black)
        line_pen.setWidth(1)
        self.add_horizontal_line(target_volume,color=QtCore.Qt.red)
        self.add_horizontal_line(target_volume*(1+tolerance),color=QtCore.Qt.black,pen=line_pen)
        self.add_horizontal_line(target_volume*(1-tolerance),color=QtCore.Qt.black,pen=line_pen)

    def handle_model_change(self,index):
        """Handle changes to the predictive model."""
        model_name = self.model_combobox.currentText()
        result = self.model.calibration_model.set_models_by_name(model_name)
        if not result:
            self.main_window.popup_message("Model Error","Model not found")
        else:
            target_volume, printer_head_type, resistance_pulse_width, standard_pressure = self.model.calibration_model.get_default_values()
            self.pulse_width_spinbox.blockSignals(True)
            self.pulse_width_spinbox.setValue(resistance_pulse_width)
            self.pulse_width_spinbox.blockSignals(False)
            self.controller.set_print_pulse_width(resistance_pulse_width,manual=False)

            self.target_pressure_spinbox.blockSignals(True)
            self.target_pressure_spinbox.setValue(standard_pressure)
            self.target_pressure_spinbox.blockSignals(False)
            self.controller.set_absolute_print_pressure(standard_pressure,manual=False)

            self.target_drop_volume_spinbox.setValue(target_volume)
            self.handle_target_drop_volume_change(target_volume)
            self.controller.update_balance_prediction_models(target_volume=target_volume)

    def handle_target_drop_volume_change(self, value):
        """Handle changes to the target drop volume value. Redraws the volume-pressure plot with a horizontal line at the target volume."""
        current_target_volume = self.target_drop_volume_spinbox.value()
        # Remove old lines
        # Remove only the target volume lines
        lines_to_remove = [series for series in self.volume_pressure_chart.series() if series not in [self.volume_pressure_series, self.linear_fit_series]]
        for series in lines_to_remove:
            self.volume_pressure_chart.removeSeries(series)
        # Add new lines
        self.add_target_volume_lines(current_target_volume)
        self.update_volume_pressure_plot()

           
    def handle_target_pressure_change(self, value):
        """Handle changes to the target pressure value."""
        self.controller.set_absolute_print_pressure(value,manual=True)

    def handle_pulse_width_change(self, value):
        """Handle changes to the pulse width value."""
        self.controller.set_print_pulse_width(value,manual=True)

    def handle_num_droplets_change(self, value):
        """Handle changes to the number of droplets value."""
        self.num_calibration_droplets = value

    def update_printing_parameters(self):
        """Update the spinboxes with the current printing parameters."""

        self.current_pressure_value.setText(f"{self.model.machine_model.get_current_print_pressure():.3f}")

        self.target_pressure_spinbox.blockSignals(True)
        self.target_pressure_spinbox.setValue(self.model.machine_model.get_target_print_pressure())
        self.target_pressure_spinbox.blockSignals(False)

        self.pulse_width_spinbox.blockSignals(True)
        self.pulse_width_spinbox.setValue(self.model.machine_model.get_print_pulse_width())
        self.pulse_width_spinbox.blockSignals(False)

    def set_volume(self):
        """Set the volume of the printer head."""
        volume = self.set_volume_spinbox.value()
        self.model.calibration_model.set_current_volume(volume)
   
    def update_volume(self):
        """Update the volume value."""
        volume = self.model.calibration_model.get_current_printer_head_volume()
        self.current_volume_value.setText(f"{volume:.2f} uL")
   
    def update_mass_time_plot(self):
        """Update the mass over time plot."""
        mass_log = self.model.calibration_model.get_mass_log()

        self.series.clear()
        for i, mass in enumerate(mass_log):
            self.series.append(i, mass)

        if len(mass_log) > 0:
            self.axisX.setRange(0, len(mass_log))
            self.axisY.setRange(min(mass_log) - 0.5, max(mass_log) + 0.5)

    def handle_initiate_test(self):
        """Sets a flag that a test has started and inactivates all buttons that could interfere with the test."""
        if self.model.calibration_model.get_current_printer_head_volume() == None:
            self.popup_message_signal.emit("No Printer Head","Please set the printer head volume before starting a test")
            return False
        self.test_started = True
        # self.calibrate_button.setDisabled(True)
        # self.repeat_measurement_button.setDisabled(True)
        # self.start_screen_button.setDisabled(True)
        self.set_volume_button.setDisabled(True)
        self.resistance_calibration_button.setDisabled(True)
        self.predict_pulse_width_button.setDisabled(True)
        self.predict_pulse_width_no_bias_button.setDisabled(True)
        self.model_combobox.setDisabled(True)
        self.target_drop_volume_spinbox.setDisabled(True)
        self.target_pressure_spinbox.setDisabled(True)
        self.pulse_width_spinbox.setDisabled(True)
        self.num_droplets_spinbox.setDisabled(True)
        return True

    def handle_test_completion(self):
        """Resets the test started flag and reactivates all buttons that were inactivated."""
        self.test_started = False
        # self.calibrate_button.setDisabled(False)
        # self.repeat_measurement_button.setDisabled(False)
        # self.start_screen_button.setDisabled(False)
        self.set_volume_button.setDisabled(False)
        self.resistance_calibration_button.setDisabled(False)
        self.predict_pulse_width_button.setDisabled(False)
        self.predict_pulse_width_no_bias_button.setDisabled(False)
        self.model_combobox.setDisabled(False)
        self.target_drop_volume_spinbox.setDisabled(False)
        self.target_pressure_spinbox.setDisabled(False)
        self.pulse_width_spinbox.setDisabled(False)
        self.num_droplets_spinbox.setDisabled(False)

    def initiate_resistance_calibration(self):
        """Initiate a measurement of the resistance of the printer head using the standard condition."""
        if not self.handle_initiate_test():
            return
        self.label.setText("Started resistance calibration process, waiting for mass stabilization")
        self.controller.check_print_syringe_position()
        self.controller.set_print_pulse_width(self.model.calibration_model.standard_pulse_width,manual=False)
        self.current_set_pulse_width = self.model.calibration_model.standard_pulse_width
        self.model.calibration_model.initiate_new_measurement('resistance',self.num_calibration_droplets)
       
    def predict_pulse_width(self):
        """Predict the pulse width for a given volume."""
        target_volume = self.target_drop_volume_spinbox.value()
        return self.model.calibration_model.predict_pulse_width_for_droplet(target_volume,calc_bias=True)
   
    def evaluate_predicted_pulse_width(self):
        """Evaluate the predicted pulse width for a given volume."""
        if not self.handle_initiate_test():
            return
        self.label.setText("Evaluating prediction, waiting for mass stabilization")
        self.controller.check_print_syringe_position()
        predicted_pulse_width, applied_bias = self.predict_pulse_width()
        self.current_set_pulse_width = predicted_pulse_width
        target_volume = self.target_drop_volume_spinbox.value()
        self.pulse_width_spinbox.blockSignals(True)
        self.pulse_width_spinbox.setValue(predicted_pulse_width)
        self.pulse_width_spinbox.blockSignals(False)
        self.controller.set_print_pulse_width(predicted_pulse_width,manual=False)
        self.model.calibration_model.initiate_new_measurement('predicted',self.num_calibration_droplets,pulse_width=predicted_pulse_width,target_volume=target_volume,applied_bias=applied_bias)

    def predict_pulse_width_no_bias(self):
        """Predict the pulse width for a given volume without bias."""
        target_volume = self.target_drop_volume_spinbox.value()
        return self.model.calibration_model.predict_pulse_width_for_droplet(target_volume,calc_bias=False)
   
    def evaluate_predict_pulse_width_no_bias(self):
        """Evaluate the predicted pulse width for a given volume without bias."""
        if not self.handle_initiate_test():
            return
        self.label.setText("Evaluating prediction without bias, waiting for mass stabilization")
        self.controller.check_print_syringe_position()
        predicted_pulse_width, applied_bias = self.predict_pulse_width_no_bias()
        self.current_set_pulse_width = predicted_pulse_width
        target_volume = self.target_drop_volume_spinbox.value()
        self.pulse_width_spinbox.blockSignals(True)
        self.pulse_width_spinbox.setValue(predicted_pulse_width)
        self.pulse_width_spinbox.blockSignals(False)
        self.controller.set_print_pulse_width(predicted_pulse_width,manual=False,update_model=True)
        self.model.calibration_model.initiate_new_measurement('predicted',self.num_calibration_droplets,pulse_width=predicted_pulse_width,target_volume=target_volume,applied_bias=applied_bias)



    def start_screen(self):
        """Start the screen for the current stock solution."""
        if not self.handle_initiate_test():
            return
        screen_low = self.pressure_screen_low_spinbox.value()
        screen_high = self.pressure_screen_high_spinbox.value()
        steps = self.repeat_measurement_spinbox.value()
        self.pressures_to_screen = list(np.linspace(screen_low,screen_high,steps))
        random.shuffle(self.pressures_to_screen)
        #print(f'Screening pulse widths: {self.pressures_to_screen}')

        self.repeat_measurements = steps
        self.repeat_measurements -= 1
        current_screen_pressure = self.pressures_to_screen.pop()
        self.label.setText(f"---Testing {current_screen_pressure} psi, {self.repeat_measurements} remaining---")
        #print(f'Screening pulse widths: {current_screen_pressure}')
        self.controller.set_print_pulse_width(current_screen_pressure,manual=False)
        self.current_set_pulse_width = current_screen_pressure
        self.model.calibration_model.initiate_new_measurement('screen',self.num_calibration_droplets,pulse_width=current_screen_pressure)

   
    def initiate_repeat_calibration_process(self):
        """Initiate the process of capturing a new measurement."""
        if not self.handle_initiate_test():
            return
        self.label.setText(f"---{self.repeat_measurements} measurements remaining---")
        self.repeat_measurements = self.repeat_measurement_spinbox.value()
        pulse_width,applied_bias = self.predict_pulse_width()
        self.current_set_pulse_width = pulse_width
        target_volume = self.target_drop_volume_spinbox.value()
        self.controller.set_print_pulse_width(pulse_width,manual=False)
        self.controller.check_print_syringe_position()
        self.model.calibration_model.initiate_new_measurement('repeat',self.num_calibration_droplets,pulse_width=pulse_width,target_volume=target_volume,applied_bias=applied_bias)
        self.repeat_measurements -= 1

    def stop_repeat_calibration_process(self):
        """Stop the process of capturing a new measurement."""
        self.label.setText(f'Stopping repeat measurements')
        self.repeat_measurements = 0
        self.pressures_to_screen = []
   
    def initiate_calibration_process(self):
        """Initiate the process of capturing a new measurement."""
        self.label.setText("Started calibration process, waiting for mass stabilization")
        self.controller.check_print_syringe_position()
        self.model.calibration_model.initiate_new_measurement('standard',self.num_calibration_droplets)
   
    def initiate_calibration_print(self):
        """Initiate the printing of calibration droplets."""
        self.label.setText("Printing calibration droplets")
        print('View: Printing calibration droplets')
        self.controller.print_calibration_droplets(self.num_calibration_droplets,pulse_width=self.current_set_pulse_width)

    def handle_calibration_complete(self):
        """Handle the completion of the calibration process."""
        self.handle_test_completion()
        self.update_volume_pressure_plot()
        self.results_value.setText(f"{self.model.calibration_model.get_last_droplet_volume():.2f} nL")
        if self.repeat_measurements > 0:
            #print(f'---{self.repeat_measurements} measurements remaining---')
            self.repeat_measurements -= 1
            if len(self.pressures_to_screen) > 0:
                current_screening_pressure = self.pressures_to_screen.pop()
                #print(f'Screening pressure: {current_screening_pressure}')
                self.label.setText(f"---Testing {current_screening_pressure} psi, {self.repeat_measurements} remaining---")
                self.current_set_pulse_width = current_screening_pressure
                self.controller.set_print_pulse_width(current_screening_pressure,manual=False)
                self.controller.check_print_syringe_position()
                self.model.calibration_model.initiate_new_measurement('screen',self.num_calibration_droplets,pulse_width=current_screening_pressure)
            else:
                pulse_width,applied_bias = self.predict_pulse_width()
                self.current_set_pulse_width = pulse_width
                self.controller.set_print_pulse_width(pulse_width,manual=False)
                target_volume = self.target_drop_volume_spinbox.value()
                self.controller.check_print_syringe_position()
                self.label.setText(f"---{self.repeat_measurements} measurements remaining---")
                self.model.calibration_model.initiate_new_measurement('repeat',self.num_calibration_droplets,pulse_width=pulse_width,target_volume=target_volume,applied_bias=applied_bias)
        else:
            self.label.setText("Calibration complete")

   
    def update_volume_pressure_plot(self):
        self.volume_pressure_series.clear()
        self.linear_fit_series.clear()
        self.last_measurement_series.clear()
        measurements = self.model.calibration_model.get_measurements()
        print(f'Measurements:\n{measurements}')
        pressures = []
        volumes = []
        for pressure,pulse_width,droplets, volume in measurements:
            print(f'Pressure: {pressure}, Pulse Width: {pulse_width}, Droplets: {droplets}, Volume: {volume}')
            self.volume_pressure_series.append(pulse_width, volume)
            pressures.append(pulse_width)
            volumes.append(volume)

        if len(measurements) > 0:
            last_measurement = measurements[-1]
            self.last_measurement_series.append(last_measurement[1],last_measurement[3])
       
        if len(measurements) >= 2 and np.std(pressures) > 0.01:
            # Calculate the linear fit
            slope, intercept = np.polyfit(pressures, volumes, 1)

            # Update the linear fit series
            self.linear_fit_series.clear()
            min_pressure = min(pressures)
            max_pressure = max(pressures)
            self.linear_fit_series.append(min_pressure, min_pressure * slope + intercept)
            self.linear_fit_series.append(max_pressure, max_pressure * slope + intercept)

        if len(pressures) > 0:
            min_pressure = min(pressures) - 200
            max_pressure = max(pressures) + 200
        else:
            min_pressure = 1500
            max_pressure = 3500
       
        if len(volumes) > 0:
            min_volume = min(volumes) - 10
            max_volume = max(volumes) + 10
        else:
            print('No volumes')
            current_target_volume = self.target_drop_volume_spinbox.value()
            min_volume = current_target_volume - 20
            max_volume = current_target_volume + 20

        self.volume_pressure_axisX.setRange(min_pressure, max_pressure)
        self.volume_pressure_axisY.setRange(min_volume, max_volume)

    def remove_last_measurement(self):
        """Remove the last measurement from the calibration log."""
        self.model.calibration_model.remove_last_measurement()

    def remove_all_calibrations_for_stock(self):
        """Remove all the calibration measurements for the current stock solution."""
        self.model.calibration_model.remove_all_calibrations_for_stock()

    def closeEvent(self, event):
        """Handle the closing of the dialog."""
        self.model.calibration_model.mass_updated_signal.disconnect(self.update_mass_time_plot)
        self.model.machine_model.printing_parameters_updated.disconnect(self.update_printing_parameters)
        self.model.calibration_model.initial_mass_captured_signal.disconnect(self.initiate_calibration_print)
        self.model.calibration_model.calibration_complete_signal.disconnect(self.handle_calibration_complete)
        self.model.calibration_model.change_volume_signal.disconnect(self.update_volume)
        self.controller.exit_print_mode()
        event.accept()

