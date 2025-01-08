import pandas as pd
import numpy as np
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QThread
import json
import heapq
import os
import csv
import cv2
import itertools
from itertools import combinations_with_replacement
import joblib
from scipy.optimize import minimize, fsolve
from scipy.signal import find_peaks
import random
import pyDOE3
import time
import glob
import shutil
import csv

class DropletCameraModel(QObject):
    droplet_image_updated = Signal()
    flash_signal = Signal()
    record_metadata_signal = Signal(str)
    def __init__(self):
        super().__init__()
        self.latest_image = None
        self.reading = False
        self.signal = False
        self.num_flashes = 0
        self.flash_duration = 0
        self.flash_delay = 0
        self.num_droplets = 1
        self.exposure_time = 1000000
        self.save_images = False

        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.image_dir = os.path.join(self.script_dir, 'Images')

    def get_num_flashes(self):
        return self.num_flashes
    
    def update_num_flashes(self,num):
        self.num_flashes = int(num)
        self.flash_signal.emit()

    def get_flash_duration(self):
        return self.flash_duration
    
    def update_flash_duration(self,duration):
        self.flash_duration = int(duration)
        self.flash_signal.emit()

    def get_flash_delay(self):
        return self.flash_delay
    
    def update_flash_delay(self,delay):
        self.flash_delay = int(delay)
        self.flash_signal.emit()

    def get_num_droplets(self):
        return self.num_droplets
    
    def update_num_droplets(self,num):
        self.num_droplets = int(num)
        self.flash_signal.emit()
    
    def update_exposure_time(self,exposure_time):
        self.exposure_time = int(exposure_time)
        self.flash_signal.emit()

    def get_image_metadata(self):
        return self.num_flashes, self.flash_duration, self.flash_delay, self.num_droplets, self.exposure_time

    def get_original_image(self):
        return self.latest_frame

    def start_saving(self):
        self.save_images = True

    def stop_saving(self):
        self.save_images = False
    
    def update_image(self,frame):
        self.latest_frame = frame
        self.droplet_image_updated.emit()
        if self.save_images:
            self.save_frame()

    def save_frame(self):
        if self.latest_frame is not None:
            os.makedirs(self.image_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            save_path = os.path.join(self.image_dir, f"image-{timestamp}.png")
            cv2.imwrite(save_path, self.latest_frame)
            print(f"Frame saved to {save_path}")
            self.record_metadata_signal.emit(timestamp)


def find_key_points(columns, line_values):
    """
    Identifies two low points and the high point between them in the data.

    Args:
        columns (np.array): The column indices (x-axis values).
        line_values (np.array): The pixel sum values (y-axis values).

    Returns:
        tuple: (low1_index, high_index, low2_index)
            Indices of the first low point, the high point, and the second low point.
    """
    # Negate the line_values to find minima using find_peaks
    inverted_values = -line_values
    low_points_indices = find_peaks(inverted_values)[0]  # Indices of local minima

    # Find the first two minima (low points)
    if len(low_points_indices) < 2:
        # ValueError("Not enough local minima found to identify two low points.")
        return None,None,None

    low1_index = low_points_indices[0]
    low2_index = low_points_indices[1]

    # Ensure the first low point comes before the second
    if low1_index > low2_index:
        low1_index, low2_index = low2_index, low1_index

    # Find the local maximum (high point) between the two low points
    high_point_indices = find_peaks(line_values)[0]  # Indices of local maxima
    high_index = None

    for idx in high_point_indices:
        if low1_index < idx < low2_index:
            high_index = idx
            break

    if high_index is None:
        raise ValueError("No local maximum found between the two low points.")

    return low1_index, high_index, low2_index
    
def find_low_point(rows,row_values):
    inverted_values = -row_values
    all_peaks = find_peaks(inverted_values)
    if len(all_peaks) > 0:
        if len(all_peaks[0]) > 0:
            lowest_point = all_peaks[0][0]
        else:
            lowest_point = None
    else:
        lowest_point = None
    return lowest_point
    
def calculate_rate_of_change(x, y):
    """
    Calculates the rate of change (first derivative) of y with respect to x.

    Args:
        x (np.array): Array of x values.
        y (np.array): Array of y values.

    Returns:
        np.array: Rate of change values.
        np.array: Midpoint x values where rate of change is calculated.
    """
    rate_of_change = np.diff(y) / np.diff(x)  # First derivative
    mid_x = (x[:-1] + x[1:]) / 2  # Midpoints between consecutive x values
    return rate_of_change

def find_largest_prominent_peak(rate_of_change):
    """
    Finds the largest peak based on prominence or width in the rate of change.

    Args:
        rate_of_change (np.array): Array of rate of change values.

    Returns:
        int: Index of the largest prominent peak.
    """
    peaks, _ = find_peaks(np.abs(rate_of_change))  # Find peaks of absolute rate of change
    if len(peaks) == 0:
        #raise ValueError("No peaks found in rate of change.")
        return None
    largest_peak_index = peaks[np.argmax(np.abs(rate_of_change[peaks]))]

    return largest_peak_index

class ImageAnalysisThread(QThread):
    # Define signals to send results back to the main thread
    analysis_done = Signal(object, object)  # Send analyzed image and result

    def __init__(self, frame, blur_size, threshold_value, left_bound, right_bound, parent=None):
        super().__init__(parent)
        self.blur_size = blur_size
        self.threshold_value = threshold_value
        self.left_bound = left_bound
        self.right_bound = right_bound
        self.original_frame = frame
        self.level_image = None
        self.level_data = None

    def run(self):
        # Perform image analysis
        self.analyze_image()
        # Emit results
        self.analysis_done.emit(self.level_image, self.level_data)

    def analyze_image(self):
        frame = self.original_frame.copy()

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Ensure blur size is odd
        if self.blur_size % 2 == 0:
            self.blur_size += 1


        frame = cv2.GaussianBlur(frame, (self.blur_size, self.blur_size), 0)

        _, frame = cv2.threshold(frame, self.threshold_value, 255, cv2.THRESH_BINARY)

        # Find contours in the thresholded image
        contours, _ = cv2.findContours(frame, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Identify the largest contour by area
        largest_contour = max(contours, key=cv2.contourArea) if contours else None

        cropped_image = None

        if largest_contour is not None:
            x, y, w, h = cv2.boundingRect(largest_contour)

            # Crop the original image based on the bounding rectangle
            frame = self.original_frame[y:y + h, x:x + w]

            # Draw vertical lines on the cropped image
            if frame is not None:
                frame = np.ascontiguousarray(frame)  # Ensure memory is contiguous
                self.level_image = frame.copy()
                height, width, _ = frame.shape
                red_line_x = np.clip(self.left_bound, 0, width - 1)
                blue_line_x = np.clip(self.right_bound, 0, width - 1)

                # Generate plot data
                if red_line_x < blue_line_x - 1:  # Ensure there's at least one column between the lines
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    line_values = frame[:, red_line_x + 1:blue_line_x].sum(axis=0)  # Exclude red_line_x column
                    columns = np.arange(red_line_x + 1, blue_line_x)
                    
                    left_edge_idx, center_idx, right_edge_idx = find_key_points(columns, line_values)

                    if center_idx is not None:
                        buffer_rows = 10
                        channel_thickness = 3
                        row_values = np.array(frame[buffer_rows:-buffer_rows, columns[center_idx]-channel_thickness:columns[center_idx]+channel_thickness].sum(axis=1))
                        row_x_values = np.array(range(buffer_rows,len(row_values)+buffer_rows))
                        row_values = row_values.astype(np.int64)  # Cast to safe integer type

                        # Calculate rate of change
                        rate_of_change = calculate_rate_of_change(row_x_values,row_values)

                        # Find largest peak in rate of change
                        largest_peak_index = find_largest_prominent_peak(rate_of_change)

                        if largest_peak_index is not None:
                            largest_peak_x = row_x_values[largest_peak_index+1]

                            cv2.line(self.level_image, (0, largest_peak_x), (width, largest_peak_x), (0, 0, 255), 1)
                            self.level_data = 1- (largest_peak_x / height)
                    else:
                        print('Error: Center index is None')
            else:
                print('Error: No contour')
        else:
            print('Error: No contour')

        return

class RefuelCameraModel(QObject):
    '''
    Stores all the data from the refuel camera system
    '''
    update_level_ui_signal = Signal()
    # level_updated_signal = Signal()

    def __init__(self):
        super().__init__()
        self.threshold_value = 120
        self.blur_size = 31
        self.left_bound = 10
        self.right_bound = 30
        self.current_level = None
        self.level_log = []
        self.stable = False

        self.latest_image = None
        self.level_image = None

    def update_threshold(self, value):
        self.threshold_value = value

    def update_blur(self, value):
        self.blur_size = value

    def update_left_bound(self, value):
        self.left_bound = value

    def update_right_bound(self, value):
        self.right_bound = value

    def update_current_level(self, level):
        self.current_level = level

    def start_analysis(self, frame):
        # Resize the image to fit within 640x480 while maintaining aspect ratio
        frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_AREA)
        self.analysis_thread = ImageAnalysisThread(frame, self.blur_size, self.threshold_value, self.left_bound, self.right_bound)
        self.analysis_thread.analysis_done.connect(self.update_ui_with_analysis)
        self.analysis_thread.start()

    def update_ui_with_analysis(self, level_image, level_data):
        # self.latest_image = analyzed_images
        if level_image is not None:
            self.level_image = level_image
        if level_data is not None:
            self.update_current_level(level_data)
            self.update_level_log(level_data)
        self.update_level_ui_signal.emit()

    def get_original_image(self):
        return self.latest_frame

    def get_level_image(self):
        return self.level_image

    def update_level_log(self,level):
        '''Add a new level to the existing log'''
        if level > 1 or level < 0:
            print('Error: level is ',level)
            return
        self.level_log.append(level)
        if len(self.level_log) > 100:
            self.level_log.pop(0)

    def get_level_log(self):
        return self.level_log
        
    
        

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
        # self.resistance_model_path = None
        # self.resistance_model = None
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
        self.standard_pressure = None

        self.rack_model.gripper_updated.connect(self.update_current_info)

    def read_all_model_metadata(self):
        """Read the metadata for all models in the prediction model directory and return a dictionary of the metadata.
        Each model is stored in a separate directory, with the metadata stored in a JSON file.
        The path to the predictive model and the resistance model are stored in the metadata."""
        model_metadata = {}
        for model_dir in os.listdir(self.prediction_model_dir):
            metadata_path = os.path.join(self.prediction_model_dir, model_dir, "metadata.json")
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as file:
                    metadata = json.load(file)
                    model_metadata[model_dir] = metadata
            model_names = glob.glob(os.path.join(self.prediction_model_dir, model_dir, "*.pkl"))
            print(f"Model names: {model_names}")
            # model_metadata[model_dir]['resistance_dir'] = [model for model in model_names if 'resistance' in model][0]
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

    # def get_selected_resistance_model_path(self):
    #     return self.resistance_model_path
    
    def set_models_by_name(self,name):
        """Set the prediction and resistance models by name."""
        for model_dir in self.model_metadata.keys():
            if self.model_metadata[model_dir]['model_name'] == name:
                self.selected_dir = model_dir
                self.prediction_model_path = self.model_metadata[model_dir]['prediction_dir']
                # self.resistance_model_path = self.model_metadata[model_dir]['resistance_dir']
                self.standard_pulse_width = self.model_metadata[model_dir]['resistance_pulse_width']
                self.standard_pressure = self.model_metadata[model_dir]['standard_pressure']
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
    
    def initiate_new_measurement(self, measurement_type,calibration_droplets,stock_id=None,starting_volume=None,print_pulse_width=None,refuel_pulse_width=None,target_print_pressure=None,target_refuel_pressure=None,target_volume=None,applied_bias=0):
        if print_pulse_width is None:
            print_pulse_width = self.machine_model.get_print_pulse_width()
        if refuel_pulse_width is None:
            refuel_pulse_width = self.machine_model.get_refuel_pulse_width()
        if target_print_pressure is None:
            target_print_pressure = self.machine_model.get_target_print_pressure()
        if target_refuel_pressure is None:
            target_refuel_pressure = self.machine_model.get_target_refuel_pressure()

        if stock_id is None:
            stock_id = self.current_stock_id
        if starting_volume is None:
            starting_volume = self.get_current_printer_head_volume()

        if measurement_type == 'resistance':
            print_pulse_width = self.standard_pulse_width
            target_print_pressure = self.standard_pressure
        
        self.current_measurement = {
            'model_name':self.model_metadata[self.selected_dir]['model_name'],
            'measurement_type':measurement_type,
            'stock_id':stock_id,
            "starting_volume": starting_volume,
            "initial_mass": 0,
            "final_mass": 0,
            "mass_difference": 0,
            "droplet_volume": 0,
            "print_pressure": target_print_pressure,
            "print_pulse_width": print_pulse_width,
            "refuel_pressure": target_refuel_pressure,
            "refuel_pulse_width": refuel_pulse_width,
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
        with open(file_path, 'w') as file:
            json.dump(self.measurements, file, indent=4)
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
            # resistance_model_path = self.get_resistance_model_path_from_name(model_name)
            if prediction_model_path is not None:
                prediction_model = joblib.load(prediction_model_path)
                # resistance_model = joblib.load(resistance_model_path)
            resistance_pulse_width = self.get_resistance_pulse_width_from_name(model_name)
            standard_pressure = self.get_standard_pressure_from_name(model_name)
        printer_head = self.printer_head_manager.get_printer_head_by_id(stock_id)
        printer_head.set_calibration_data(resistance,bias,target_droplet_volume,prediction_model,resistance_pulse_width)

    def get_measurements(self):
        return [[m['print_pressure'],m['print_pulse_width'],m['refuel_pressure'],m['refuel_pulse_width'],m['droplets'],m['droplet_volume']] for m in self.measurements if m['stock_id'] == self.current_stock_id]
    
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
            # return '65um low viscosity'
            return '150um dual channel v2'
            # return self.model_metadata[list(self.model_metadata.keys())[0]]['model_name']

    def get_prediction_model_path_from_name(self,name):
        for model_dir in self.model_metadata.keys():
            if self.model_metadata[model_dir]['model_name'] == name:
                return self.model_metadata[model_dir]['prediction_dir']
        return None

    # def get_resistance_model_path_from_name(self,name):
    #     for model_dir in self.model_metadata.keys():
    #         if self.model_metadata[model_dir]['model_name'] == name:
    #             return self.model_metadata[model_dir]['resistance_dir']
    #     return None

    def get_resistance_pulse_width_from_name(self,name):
        for model_dir in self.model_metadata.keys():
            if self.model_metadata[model_dir]['model_name'] == name:
                return self.model_metadata[model_dir]['resistance_pulse_width']
        return None
    
    def get_standard_pressure_from_name(self,name):
        for model_dir in self.model_metadata.keys():
            if self.model_metadata[model_dir]['model_name'] == name:
                return self.model_metadata[model_dir]['standard_pressure']
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
        # self.resistance_model = joblib.load(self.resistance_model_path)

    def calculate_resistance_for_stock(self,stock_id):
        stock_measurements = [m for m in self.measurements if m['stock_id'] == stock_id]
        if len(stock_measurements) == 0:
            #print(f"No measurements found for stock '{stock_id}'")
            return None
        stock_data = pd.DataFrame(stock_measurements)
        standard_data = stock_data[(stock_data['print_pulse_width'] == self.standard_pulse_width) & (stock_data['print_pressure'] == self.standard_pressure)].copy()
        if len(standard_data) == 0:
            print(f"No standard measurements found for stock '{stock_id}'")
            return None
        # res_df = standard_data[['starting_volume','droplet_volume']].copy().rename(columns={'starting_volume':'resistance_volume','droplet_volume':'resistance'})
        # res_df['effective_resistance'] = self.resistance_model.predict(res_df)
        resistance = standard_data['droplet_volume'].mean()
        print(f"Resistance for stock '{stock_id}': {resistance:.2f} nL")
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
    
    def predict_pressure_for_droplet(self, target_droplet_volume,calc_bias=True):
        total_volume = self.get_current_printer_head_volume()
        resistance = self.calculate_resistance_for_stock(self.current_stock_id)
        if resistance is None:
            print(f"Resistance for stock '{self.current_stock_id}' is None")
            return self.standard_pressure,0
        if calc_bias:
            bias = self.calculate_bias(self.current_stock_id)
            if bias is None:
                bias = 0
        else:
            bias = 0
        pressure = self.predict_pressure(resistance, target_droplet_volume,bias=bias)
        print(f"Required pressure for {target_droplet_volume} nL droplet: {pressure:.2f} psi")
        return pressure, bias
    
    def predict_pressure(self, effective_resistance, target_droplet_volume,bias=0,prediction_model=None,resistance_pulse_width=None):
        if prediction_model is None:
            prediction_model = self.prediction_model
        if resistance_pulse_width is None:
            standard_pulse_width = self.standard_pulse_width
        else:
            standard_pulse_width = resistance_pulse_width
        def func(pressure):
            input_features = pd.DataFrame({
                'print_pressure':[pressure],
                'print_pulse_width': [standard_pulse_width],
                'effective_resistance': [effective_resistance]
            })
            predicted_volume = prediction_model.predict(input_features)[0] + bias
            return predicted_volume - target_droplet_volume

        # Initial guess for pulse width
        print(f'Effective resistance: {effective_resistance}, Standard pulse width {standard_pulse_width},Target droplet volume: {target_droplet_volume}, Bias: {bias}')
        initial_guess = self.standard_pressure
        pressure_solution = fsolve(func, initial_guess)
        print(f"Pressure solution: {pressure_solution[0]:.2f} psi, initial guess: {initial_guess:.2f} psi")
        return round(pressure_solution[0],2)


def find_minimal_stock_solutions_backtracking(target_concentrations, max_droplets):
    target_concentrations.sort()

    def can_achieve_all(stock_solutions):
        achievable_concentrations = {0: []}  # concentration -> list of (stock_solution, droplets)
        for num_droplets in range(1, max_droplets + 1):
            for comb in combinations_with_replacement(stock_solutions, num_droplets):
                total_concentration = sum(comb)
                if total_concentration not in achievable_concentrations:
                    achievable_concentrations[total_concentration] = comb
        return achievable_concentrations

    def backtrack(current_solutions, index):
        achievable_concentrations = can_achieve_all(current_solutions)

        if all(tc in achievable_concentrations for tc in target_concentrations):
            return current_solutions, achievable_concentrations

        if index == len(target_concentrations):
            return None, None

        # Explore both including and excluding the current concentration as a stock solution
        with_current, achievable_with = backtrack(current_solutions + [target_concentrations[index]], index + 1)
        without_current, achievable_without = backtrack(current_solutions, index + 1)

        if with_current is None:
            return without_current, achievable_without
        if without_current is None:
            return with_current, achievable_with
        
        # Prioritize the solution with fewer stock solutions
        if len(with_current) < len(without_current):
            return with_current, achievable_with
        elif len(with_current) > len(without_current):
            return without_current, achievable_without
        else:
            # If the number of stock solutions is the same, choose the one with the lower sum of concentrations
            if sum(with_current) < sum(without_current):
                return with_current, achievable_with
            else:
                return without_current, achievable_without

    minimal_solutions, achievable_concentrations = backtrack([], 0)
    return minimal_solutions, achievable_concentrations

def multi_reagent_optimization(reagents_data, max_total_droplets):
    reagent_solutions = []
    for target_concentrations, max_droplets in reagents_data:
        solutions = []
        for droplet_limit in range(1, max_droplets + 1):
            stock_solutions, achievable_concentrations = find_minimal_stock_solutions_backtracking(target_concentrations, droplet_limit)
            max_droplets_for_any_concentration = max([len(achievable_concentrations[tc]) for tc in target_concentrations])
            solutions.append((stock_solutions, max_droplets_for_any_concentration))
        reagent_solutions.append(solutions)

    best_combination = None
    min_stock_count = float('inf')
    min_concentration_sum = float('inf')

    for combination in itertools.product(*reagent_solutions):
        stock_solution_set = set()
        total_droplets = 0
        max_droplets_per_reagent = []
        concentration_sum = 0

        for stock_solutions, droplets_used in combination:
            stock_solution_set.update(stock_solutions)
            total_droplets += droplets_used
            max_droplets_per_reagent.append(droplets_used)
            concentration_sum += sum(stock_solutions)  # Sum the concentrations used

        # Prioritize by fewest stock solutions, then by lowest concentration sum
        if total_droplets <= max_total_droplets:
            if len(stock_solution_set) < min_stock_count or (len(stock_solution_set) == min_stock_count and concentration_sum < min_concentration_sum):
                best_combination = combination
                min_stock_count = len(stock_solution_set)
                min_concentration_sum = concentration_sum

    if best_combination:
        final_stock_solutions = [sol[0] for sol in best_combination]
        max_droplets_per_reagent = [sol[1] for sol in best_combination]
    else:
        final_stock_solutions = []
        max_droplets_per_reagent = []

    return final_stock_solutions, max_droplets_per_reagent

def check_stock_solution_calculations(target_concentrations, stock_solutions, units, max_droplets):
    target_concentrations.sort()
    target_concentrations = [round(tc, 3) for tc in target_concentrations]
    unachievable_concentrations = []
    droplet_usage = {}

    achievable_concentrations = {0: []}  # concentration -> list of (stock_solution, droplets)
    
    # Generate all possible combinations of stock solutions within the max droplet count
    for num_droplets in range(1, max_droplets + 1):
        for comb in combinations_with_replacement(stock_solutions, num_droplets):
            total_concentration = sum(comb)
            if total_concentration not in achievable_concentrations:
                achievable_concentrations[total_concentration] = comb
    
    # Check which target concentrations are achievable and calculate droplet usage
    for tc in target_concentrations:
        if tc not in achievable_concentrations:
            unachievable_concentrations.append(tc)
        else:
            # Calculate the number of droplets used from each stock solution
            droplets = achievable_concentrations[tc]
            droplet_count = {stock: droplets.count(stock) for stock in stock_solutions}
            droplet_usage[tc] = droplet_count

    lookup_table = pd.DataFrame(droplet_usage).T.stack().reset_index().rename(columns={'level_0':'target_concentration', 'level_1':'stock_solution', 0:'droplet_count'})
    lookup_table['units'] = units
    # Calculate the most droplets used for any target concentration
    if lookup_table.empty:
        max_droplets_for_any_concentration = 0
    else:
        max_droplets_for_any_concentration = lookup_table.groupby('target_concentration')['droplet_count'].sum().max()

    # #print(f'Max droplets for any concentration: {max_droplets_for_any_concentration}')
    # If there are unachievable concentrations, return them
    if unachievable_concentrations:
        return False, unachievable_concentrations, lookup_table, max_droplets_for_any_concentration
    else:
        return True, None, lookup_table, max_droplets_for_any_concentration


class ExperimentModel(QObject):
    data_updated = Signal(int)  # Signal to notify when reagent data is updated, passing the row index
    stock_updated = Signal()
    experiment_generated = Signal(int,int)  # Signal to notify when the experiment is generated, passing the total number of reactions
    update_max_droplets_signal = Signal(int) # Signal to notify when the max droplets is updated, passing the row index
    unsaved_changes_signal = Signal() # Signal to notify when there are unsaved changes

    def __init__(self,well_plate,calibration_model):
        super().__init__()
        self.well_plate = well_plate
        self.calibration_model = calibration_model
        self.reagents = []
        temp_name = "Untitled-" + time.strftime("%Y%m%d_%H%M%S")
        self.metadata = {
            "name": temp_name,
            "replicates": 1,
            "max_droplets": 50,
            'droplet_volume': 0.03,
            'fill_reagent': 'Water',
            'random_seed': None,
            'reduction_factor': 1,
            'start_row':0,
            'start_col':0
        }
        self.stock_solutions = []
        self.experiment_df = pd.DataFrame()
        self.complete_lookup_table = pd.DataFrame()
        self.all_droplet_df = pd.DataFrame()

        self.experiment_dir_path = None
        self.experiment_file_path = None
        self.progress_file_path = None
        self.progress_data = {}
        self.calibration_file_path = None
        self.key_file_path = None

        self.add_new_stock_solutions_for_reagent(self.metadata['fill_reagent'],[1.0],'--')
        self.initialize_experiment()

        self.unsaved_changes = False

    def mark_unsaved_changes(self):
        self.unsaved_changes = True
        self.unsaved_changes_signal.emit()

    def reset_unsaved_changes(self):
        print('reset unsaved changes')
        self.unsaved_changes = False
        self.unsaved_changes_signal.emit()

    def has_unsaved_changes(self):
        return self.unsaved_changes
    
    def add_reagent(self, name, min_conc, max_conc, steps, mode, manual_input,units,max_droplets,stock_solutions):
        reagent = {
            "name": name,
            "min_conc": min_conc,
            "max_conc": max_conc,
            "steps": steps,
            "mode": mode,
            "manual_input": manual_input,
            "concentrations": [],
            'units':units,
            "max_droplets": max_droplets,
            "stock_solutions": stock_solutions,
            "missing_concentrations": [],
            "max_droplets_for_conc": 0
        }
        self.reagents.append(reagent)
        self.calculate_concentrations(len(self.reagents) - 1)
        self.mark_unsaved_changes()

    def update_reagent(self, index, name=None, min_conc=None, max_conc=None, steps=None, mode=None, manual_input=None, units=None, max_droplets=None,stock_solutions=None):
        reagent = self.reagents[index]
        if name is not None:
            reagent["name"] = name
        if min_conc is not None:
            reagent["min_conc"] = min_conc
        if max_conc is not None:
            reagent["max_conc"] = max_conc
        if steps is not None:
            reagent["steps"] = steps
        if mode is not None:
            reagent["mode"] = mode
        if manual_input is not None:
            reagent["manual_input"] = manual_input
        if units is not None:
            reagent['units'] = units
        if max_droplets is not None:
            reagent["max_droplets"] = max_droplets
        if stock_solutions is not None:
            reagent["stock_solutions"] = stock_solutions

        # Update concentrations preview based on the new data
        self.calculate_concentrations(index)
        self.mark_unsaved_changes()

    def delete_reagent(self, name):
        self.reagents = [reagent for reagent in self.reagents if reagent["name"] != name]
        self.remove_stock_solutions_for_unused_reagents()
        self.generate_experiment(feasible=False)
        self.mark_unsaved_changes()

    def change_random_seed(self,remove_seed=False):
        if remove_seed:
            self.metadata['random_seed'] = None
        else:
            self.metadata['random_seed'] = random.randint(0,100000)
        self.generate_experiment(feasible=False)
        self.mark_unsaved_changes()

    def get_random_seed(self):
        return self.metadata['random_seed']

    def update_metadata(self, replicates, max_droplets,reduction_factor,start_row,start_col):
        self.metadata["replicates"] = replicates
        self.metadata["max_droplets"] = max_droplets
        self.metadata["reduction_factor"] = reduction_factor
        self.metadata['start_row'] = start_row
        self.metadata['start_col'] = start_col

        self.generate_experiment(feasible=False)
        self.mark_unsaved_changes()

    def update_fill_reagent_name(self,fill_reagent):
        self.stock_solutions = [stock for stock in self.stock_solutions if stock['reagent_name'] != self.metadata['fill_reagent']]
        self.metadata['fill_reagent'] = fill_reagent
        self.add_new_stock_solutions_for_reagent(fill_reagent,[1.0],'--')
        self.generate_experiment(feasible=False)
        self.mark_unsaved_changes()

    def get_start_row(self):
        return self.metadata['start_row']
    
    def get_start_col(self):
        return self.metadata['start_col']

    def calculate_concentrations(self, index,calc_experiment=True):
        reagent = self.reagents[index]
        mode = reagent["mode"]
        if mode == "Manual":
            try:
                reagent["concentrations"] = [round(float(c.strip()), 2) for c in reagent["manual_input"].split(',') if c.strip()]
            except ValueError:
                reagent["concentrations"] = []
        else:
            min_conc = reagent["min_conc"]
            max_conc = reagent["max_conc"]
            steps = reagent["steps"]

            if min_conc >= max_conc:
                reagent["concentrations"] = []
                return
            
            if steps == 1:
                reagent["concentrations"] = [round(max_conc, 2)]
                # #print(f'Conc for {index} has steps {steps} and {reagent["concentrations"]}')
            elif mode == "Linear":
                reagent["concentrations"] = [round(x, 2) for x in np.linspace(min_conc, max_conc, steps).tolist()]
            elif mode == "Quadratic":
                reagent["concentrations"] = [round(x, 2) for x in (np.linspace(np.sqrt(min_conc), np.sqrt(max_conc), steps)**2).tolist()]
            elif mode == "Logarithmic":
                reagent["concentrations"] = [round(x, 2) for x in np.logspace(np.log10(min_conc), np.log10(max_conc), steps).tolist()]
        
        # self.calculate_stock_solutions(index)
        feasible = self.check_stock_solutions(index)
        
        # Emit signal to update the view
        self.data_updated.emit(index)
        if calc_experiment:
            self.generate_experiment(feasible=feasible)


    def calculate_all_concentrations(self):
        for i in range(len(self.reagents)):
            self.calculate_concentrations(i)

    def check_stock_solutions(self, index):
        """Check if the specified stock solutions are able to produce the target concentrations."""
        self.remove_stock_solutions_for_unused_reagents()
        reagent = self.reagents[index]
        if type(reagent["stock_solutions"]) == str:
            current_stock_solutions = [round(float(c.strip()), 3) for c in reagent["stock_solutions"].split(',') if c.strip()]
            reagent['stock_solutions'] = current_stock_solutions
        else:
            current_stock_solutions = reagent["stock_solutions"]
        feasible, unachievable, lookup_table, max_droplets_for_conc = check_stock_solution_calculations(reagent['concentrations'], current_stock_solutions, reagent['units'], reagent['max_droplets'])
        if not feasible:
            reagent['missing_concentrations'] = unachievable
            self.remove_stock_solutions_for_reagent(reagent['name'])
        else:
            reagent['missing_concentrations'] = []
            self.add_lookup_table(reagent['name'],lookup_table)
            self.add_new_stock_solutions_for_reagent(reagent['name'], current_stock_solutions,reagent['units'])
        reagent['max_droplets_for_conc'] = max_droplets_for_conc
        return feasible

    def add_new_stock_solutions_for_reagent(self, reagent_name, concentrations,units):
        # Remove any existing stock solutions for this reagent
        self.stock_solutions = [stock for stock in self.stock_solutions if stock['reagent_name'] != reagent_name]
        # Check if this stock solution already exists to avoid duplicates
        for concentration in concentrations:
            self.stock_solutions.append({
                "reagent_name": reagent_name,
                "concentration": concentration,
                "units":units,
                "total_droplets": 0,
                'total_volume': 0
            })
        self.mark_unsaved_changes()

    def remove_stock_solutions_for_reagent(self, reagent_name):
        self.stock_solutions = [stock for stock in self.stock_solutions if stock['reagent_name'] != reagent_name]
        # Update the stock solutions in the experiment DataFrame
        if not self.all_droplet_df.empty:
            self.all_droplet_df = self.all_droplet_df[self.all_droplet_df['reagent_name'] != reagent_name].copy()
        # Update the stock solutions in the lookup table
        if not self.complete_lookup_table.empty:
            self.complete_lookup_table = self.complete_lookup_table[self.complete_lookup_table['reagent_name'] != reagent_name].copy()
        self.mark_unsaved_changes()
    
    def remove_stock_solutions_for_unused_reagents(self):
        used_reagents = [reagent['name'] for reagent in self.reagents]
        used_reagents.append(self.metadata['fill_reagent'])
        self.stock_solutions = [stock for stock in self.stock_solutions if stock['reagent_name'] in used_reagents]
        # Update the stock solutions in the experiment DataFrame
        if not self.all_droplet_df.empty:
            self.all_droplet_df = self.all_droplet_df[self.all_droplet_df['reagent_name'].isin(used_reagents)].copy()
        # Update the stock solutions in the lookup table
        # #print(f'Complete lookup table:\n{self.complete_lookup_table}')
        if not self.complete_lookup_table.empty:
            self.complete_lookup_table = self.complete_lookup_table[self.complete_lookup_table['reagent_name'].isin(used_reagents)].copy()

        

    def check_missing_concentrations(self):
        for reagent in self.reagents:
            if len(reagent['missing_concentrations']) > 0:
                return True
        return False

    def create_lookup_table(self,reagent_name,achievable_concentrations, stock_solutions):
        # Initialize a DataFrame with target concentrations as index and stock solutions as columns
        if achievable_concentrations == None:
            return pd.DataFrame()
        lookup_table = pd.DataFrame(index=achievable_concentrations.keys(), columns=stock_solutions)
        # Iterate over the achievable concentrations and populate the lookup table
        for concentration, droplets in achievable_concentrations.items():
            droplet_counts = {stock: 0 for stock in stock_solutions}  # Initialize droplet counts
            for droplet in droplets:
                droplet_counts[droplet] += 1  # Count how many droplets of each stock solution are used
            lookup_table.loc[concentration] = pd.Series(droplet_counts)
        
        # Replace NaN values with 0 (indicating no droplets of that stock solution are used)
        lookup_table['reagent_name'] = reagent_name
        lookup_table = lookup_table.reset_index().rename(columns={'index': 'target_concentration'})
        lookup_table = lookup_table.set_index(['reagent_name','target_concentration']).stack().reset_index().rename(columns={0: 'droplet_count', 'level_2': 'stock_solution'})
        # print('\nLookup table:\n',lookup_table)
        return lookup_table
    
    def add_lookup_table(self,reagent_name,lookup_table):
        lookup_table['reagent_name'] = reagent_name
        if self.complete_lookup_table.empty:
            self.complete_lookup_table = lookup_table
            return
        # Remove any existing rows with the same reagent name
        self.complete_lookup_table = self.complete_lookup_table[self.complete_lookup_table['reagent_name'] != reagent_name].copy()
        # Append the new lookup table
        self.complete_lookup_table = pd.concat([self.complete_lookup_table, lookup_table], ignore_index=True)
        # print('\nLookup table:\n',self.complete_lookup_table)


    def get_reagent(self, index):
        return self.reagents[index]

    def get_all_reagents(self):
        return self.reagents
    
    def get_all_stock_solutions(self):
        return self.stock_solutions

    def generate_experiment(self,feasible=True):
        """Generate the experiment combinations as a pandas DataFrame."""
        reagent_names = [reagent['name'] for reagent in self.reagents]
        # print('\nReagent names:\n',reagent_names)
        # concentrations = [reagent['concentrations'] for reagent in self.reagents]
        # conc_units = []
        concentrations = []
        for reag in self.reagents:
            concentrations.append(['_'.join([str(conc),reag['units']]) for conc in reag['concentrations']])
        # print('\nConcentrations:\n',concentrations)
        if self.metadata['reduction_factor'] == 1:
            concentration_combinations = list(itertools.product(*concentrations))
            self.experiment_df = pd.DataFrame(concentration_combinations, columns=reagent_names)
        else:
            num_concentrations = [len(c) for c in concentrations]
            try:
                reduced_comb = pyDOE3.gsd(num_concentrations, self.metadata['reduction_factor'])
                self.experiment_df = pd.DataFrame(
                    [[concentrations[j][idx] for j, idx in enumerate(row)] for row in reduced_comb],
                    columns=reagent_names
                )
            except Exception as e:
                print('Error generating reduced experiment:',e)
                self.experiment_df = pd.DataFrame()
                return
        self.experiment_df = self.experiment_df.stack().reset_index().rename(columns={'level_0':'reaction_id','level_1':'reagent_name',0: 'target_concentration'})
        self.experiment_df['units'] = self.experiment_df['target_concentration'].apply(lambda x: x.split('_')[-1])
        self.experiment_df['target_concentration'] = self.experiment_df['target_concentration'].apply(lambda x: x.split('_')[0]).astype(float)
        #print(f'\nExperiment df:\n{self.experiment_df}')
        # Apply replicates
        all_dfs = []
        for i in range(self.metadata["replicates"]):
            temp_df = self.experiment_df.copy()
            if not temp_df.empty:
                temp_df['replicate'] = i
                temp_df['unique_id'] = temp_df['reaction_id'] + (temp_df['replicate']*(max(temp_df['reaction_id'])+1))
            all_dfs.append(temp_df)
        self.experiment_df = pd.concat(all_dfs, ignore_index=True)
        # #print(f'Experiment df:\n{self.experiment_df}')
        # #print(f'complete lookup table:\n{self.complete_lookup_table}')
        
        try:
            self.all_droplet_df = self.experiment_df.merge(self.complete_lookup_table, on=['reagent_name','target_concentration','units'], how='left')
            max_droplet_df = self.all_droplet_df[['reaction_id','unique_id','replicate','droplet_count']].groupby(['reaction_id','unique_id','replicate']).sum().reset_index()
            fill_reagent_df = max_droplet_df.copy()
            fill_reagent_df['reagent_name'] = self.metadata['fill_reagent']
            fill_reagent_df['stock_solution'] = 1
            fill_reagent_df['droplet_count'] = self.metadata['max_droplets'] - fill_reagent_df['droplet_count']
            fill_reagent_df['target_concentration'] = 0
            fill_reagent_df['units'] = '--'
            self.all_droplet_df = pd.concat([self.all_droplet_df,fill_reagent_df],ignore_index=True)
            droplet_count = max_droplet_df['droplet_count'].max()
            self.add_total_droplet_count_to_stock()

        except Exception as e:
            #print(f'Generate experiment error: {e}')
            droplet_count = 0
            self.all_droplet_df = pd.DataFrame()

        self.stock_updated.emit()

        # Emit signal to notify that the experiment has been generated
        self.experiment_generated.emit(self.get_number_of_reactions(),droplet_count)

    def get_number_of_reactions(self):
        if self.experiment_df.empty:
            return 0
        return len(self.experiment_df['unique_id'].unique())
    
    def add_total_droplet_count_to_stock(self):
        for stock_solution in self.stock_solutions:
            # #print(f'Stock solution: {stock_solution}')
            total_droplets = self.all_droplet_df[(self.all_droplet_df['reagent_name'] == stock_solution['reagent_name']) & (self.all_droplet_df['stock_solution'] == stock_solution['concentration'])]['droplet_count'].sum()
            # #print(f'Total droplets: {total_droplets}')
            stock_solution['total_droplets'] = total_droplets
            stock_solution['total_volume'] = round(stock_solution['total_droplets'] * self.metadata['droplet_volume'],2)

    def optimize_stock_solutions(self):
        reagents_data = []
        for reagent in self.reagents:
            max_reag_droplets = reagent['max_droplets']
            if max_reag_droplets < 10:
                max_reag_droplets = 10  # Ensure a minimum of 10 droplets
            reagents_data.append((reagent['concentrations'], max_reag_droplets))

        max_total_droplets = self.metadata['max_droplets']
        optimized_solutions, max_droplets_per_reagent = multi_reagent_optimization(reagents_data, max_total_droplets)
        # #print(f"Optimized stock solutions: {optimized_solutions}")
        # #print(f"Max droplets per reagent: {max_droplets_per_reagent}")
        for i in range(len(max_droplets_per_reagent)):
            self.reagents[i]['max_droplets'] = max_droplets_per_reagent[i]

            self.update_max_droplets_signal.emit(i)
    
    def get_experiment_dataframe(self):
        """Return the experiment DataFrame."""
        return self.experiment_df
    
    def convert_to_serializable(self,obj):
        if isinstance(obj, np.generic):
            return obj.item()  # Convert numpy data types to native Python types
        if isinstance(obj, np.ndarray):
            return obj.tolist()  # Convert numpy arrays to lists
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

    
    def initialize_experiment(self):
        """Generates the initial directory for the experiment and all initial files"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_experiment_dir = os.path.join(script_dir, "Experiments")
        if not os.path.exists(base_experiment_dir):
            os.makedirs(base_experiment_dir)
        self.experiment_dir_path = os.path.join(base_experiment_dir, self.metadata['name'])
        print(f'Experiment directory: {self.experiment_dir_path}')
        if not os.path.exists(self.experiment_dir_path):
            os.makedirs(self.experiment_dir_path)
            print(f'Experiment directory created at {self.experiment_dir_path}')
        self.update_all_paths()
        self.save_experiment()
        self.create_progress_file()
        self.create_key_file()
        self.calibration_model.create_calibration_file(self.calibration_file_path)

    def rename_experiment(self,new_name):
        """Rename the experiment directory and update the metadata."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_experiment_dir = os.path.join(script_dir, "Experiments")
        new_experiment_dir = os.path.join(base_experiment_dir, new_name)
        print(f'New experiment directory: {new_experiment_dir}')
        if os.path.exists(new_experiment_dir):
            return False
        os.rename(self.experiment_dir_path, new_experiment_dir)
        self.metadata['name'] = new_name
        self.experiment_dir_path = new_experiment_dir
        self.update_all_paths()
        self.save_experiment()
        return True
    
    def duplicate_experiment(self,new_name,new_experiment_path,copy_calibrations=False):
        """Copy the experiment design information and create a new experiment directory using the new name.
        The progress and calibration files are not copied.
        """
        # shutil.copytree(self.experiment_dir_path, new_experiment_path)
        self.metadata['name'] = new_name
        self.experiment_dir_path = new_experiment_path
        self.update_all_paths()
        self.save_experiment()
        self.create_progress_file()
        self.create_key_file()
        if not copy_calibrations:
            print('Deleting calibration file')
            self.calibration_model.remove_all_calibrations()
            self.calibration_model.create_calibration_file(self.calibration_file_path)
        else:
            print('Copying calibration file')
            self.calibration_model.update_calibration_file_path(self.calibration_file_path)
            self.calibration_model.save_calibration_data(self.calibration_file_path)
        return True

    def update_all_paths(self):
        """Update all file paths based on the experiment directory."""
        if self.experiment_dir_path is None:
            return
        self.experiment_file_path = os.path.join(self.experiment_dir_path, "experiment_design.json")
        self.progress_file_path = os.path.join(self.experiment_dir_path, "progress.json")
        self.calibration_file_path = os.path.join(self.experiment_dir_path, "calibration.json")
        self.calibration_model.update_calibration_file_path(self.calibration_file_path)
        self.key_file_path = os.path.join(self.experiment_dir_path, "key.csv")

    def save_experiment(self,create_progress=True):
        """Save all information required to repopulate the model to a JSON file."""
        data_to_save = {
            "reagents": self.reagents,
            "metadata": self.metadata,
        }
        with open(self.experiment_file_path, 'w') as file:
            json.dump(data_to_save, file, indent=4, default=self.convert_to_serializable)
        print(f"Experiment data saved to {self.experiment_file_path}")

        self.reset_unsaved_changes()

    def create_progress_file(self,file_name=None):
        """Create a JSON file to store the progress of the experiment."""
        if file_name is not None:
            self.progress_file_path = file_name

        #print(f'Creating progress file at {self.progress_file_path}')
        self.progress_data = {}
        for well in self.well_plate.get_all_wells():
            well_id = well.well_id
            reaction = well.assigned_reaction
            
            if reaction:
                self.progress_data[well_id] = {
                    "reaction_id": reaction.unique_id,
                    "reagents": {
                        stock_id: {
                            "target_droplets": reagent.get_target_droplets(),
                            "added_droplets": reagent.added_droplets
                        }
                        for stock_id, reagent in reaction.get_all_reagents().items()
                    },
                    "completed": reaction.check_all_complete()
                }
        #print(f'Create progress file: {self.progress_file_path}')
        with open(self.progress_file_path, 'w') as f:
            json.dump(self.progress_data, f, indent=4)

    # Function to convert JSON to pandas DataFrame
    def progress_to_key(self):
        data = {}

        for well_id, well_data in self.progress_data.items():
            reagents = well_data['reagents']
            data[well_id] = {reagent: details['target_droplets'] for reagent, details in reagents.items()}

        df = pd.DataFrame.from_dict(data, orient='index')
        return df

    def create_key_file(self,file_name=None):
        if file_name is not None:
            self.key_file_path = file_name
        print(f'Creating key file at {self.key_file_path}')
        print(self.progress_data)
        key_df = self.progress_to_key()
        print(key_df)
        key_df.to_csv(self.key_file_path, index_label='Well ID')
        

    def update_progress(self, well_id):
        """Update the progress of a specific well in the experiment."""
        well = self.well_plate.get_well(well_id)
        reaction = well.assigned_reaction
        
        # Update the specific entry
        self.progress_data[well_id] = {
                "reaction_id": reaction.unique_id,
                "reagents": {
                    stock_id: {
                        "target_droplets": reagent.get_target_droplets(),
                        "added_droplets": reagent.added_droplets
                    }
                    for stock_id, reagent in reaction.get_all_reagents().items()
                },
                "completed": reaction.check_all_complete()
            }

        # Save the updated progress back to the file
        if self.progress_file_path is None:
            return
        with open(self.progress_file_path, 'w') as f:
            json.dump(self.progress_data, f, indent=4)


    def load_experiment(self, filename,experiment_dir):
        """Load all information required to repopulate the model from a JSON file."""
        self.experiment_file_path = filename
        self.experiment_dir_path = experiment_dir
        self.update_all_paths()
        
        with open(filename, 'r') as file:
            loaded_data = json.load(file)

        # Clear current data to avoid duplications or issues
        self.reagents = []
        self.metadata = {
            "replicates": 1,
            "max_droplets": 20,
            'droplet_volume': 0.03,
            'fill_reagent': 'Water'
        }
        self.stock_solutions = []
        self.experiment_df = pd.DataFrame()
        self.complete_lookup_table = pd.DataFrame()
        self.all_droplet_df = pd.DataFrame()

        # Load data from the JSON file
        self.reagents = loaded_data["reagents"]
        self.metadata = loaded_data["metadata"]

        self.add_new_stock_solutions_for_reagent(self.metadata['fill_reagent'],[1.0],'--')

        # Recalculate any necessary information and emit signals to update the view
        for i in range(len(self.reagents)):

            self.data_updated.emit(i)
            self.calculate_concentrations(i,calc_experiment=True)
            # #print(f'finished conc for {i}\n{self.experiment_df}')
        
        #print(f"Experiment data loaded from {filename}")

    def read_progress_file(self, progress_file):
        """Read the progress of the experiment from a JSON file."""
        self.progress_file_path = progress_file
        with open(progress_file, 'r') as file:
            self.progress_data = json.load(file)

    def return_progress_data(self):
        if self.progress_file_path == None:
            print('No progress file path set')
            return {}
        with open(self.progress_file_path, 'r') as file:
            return json.load(file)

    def load_progress(self):
        print('Loading progress data')
        if self.return_progress_data() == {}:
            print('No progress data found in file, writing new progress file')
            self.create_progress_file()
        for well_id, well_data in self.progress_data.items():
            well = self.well_plate.get_well(well_id)
            reaction = well.assigned_reaction
            
            if reaction and reaction.unique_id == well_data["reaction_id"]:
                for stock_id, reagent_data in well_data["reagents"].items():
                    reagent = reaction.get_reagent_by_id(stock_id)
                    reagent.added_droplets = reagent_data["added_droplets"]
                    reagent.completed = reagent.is_complete()

                if well_data["completed"]:
                    well.state_changed.emit(well_id)

    def reset_experiment_model(self):
        """Reset the experiment model to its initial state."""
        self.reagents = []
        temp_name = "Untitled-" + time.strftime("%Y%m%d_%H%M%S")
        self.metadata = {
            "name": temp_name,
            "replicates": 1,
            "max_droplets": 50,
            'droplet_volume': 0.03,
            'fill_reagent': 'Water',
            'random_seed': None,
            'reduction_factor': 1,
            'start_row':0,
            'start_col':0
        }
        self.stock_solutions = []
        self.experiment_df = pd.DataFrame()
        self.complete_lookup_table = pd.DataFrame()
        self.all_droplet_df = pd.DataFrame()

        self.experiment_dir_path = None
        self.experiment_file_path = None
        self.progress_file_path = None
        self.progress_data = {}
        self.calibration_file_path = None
        self.key_file_path = None

        self.add_new_stock_solutions_for_reagent(self.metadata['fill_reagent'],[1.0],'--')
        self.initialize_experiment()

        self.unsaved_changes = False
            


class StockSolution(QObject):
    '''
    Represents a specific instance of a reagent at a certain concentration
    Each stock solution can be assigned to a printer head.
    '''
    def __init__(self, stock_id, reagent_name,concentration,units, required_volume=None):
        super().__init__()
        self.stock_id = stock_id
        self.reagent_name = reagent_name
        self.concentration = concentration
        self.units = units
        self.required_volume = required_volume

    def get_stock_id(self):
        return self.stock_id
    
    def get_reagent_name(self):
        return self.reagent_name
    
    def get_stock_concentration(self):
        return self.concentration
    
    def get_stock_name(self,new_line=False):
        if self.units == '--':
            return f"{self.reagent_name}"
        elif new_line:
            return f"{self.reagent_name}\n{self.concentration} {self.units}"
        else:
            return f"{self.reagent_name} - {self.concentration} {self.units}"


class Reagent(QObject):
    '''
    Represents an amount of a stock solution that should be added to a specific reaction
    A reaction composition is comprised of one or more Reagents that when mixed together creates the target composition
    Contains the stock solution, the number of droplets needed and tracks how much of the reagent has been added
    '''
    def __init__(self, stock_solution, droplets):
        super().__init__()
        self.stock_solution = stock_solution
        self.target_droplets = droplets     # Number of droplets to be added to the reaction
        self.added_droplets = 0             # Number of droplets that have already been added
        self.completed = False              # States whether all required droplets have been added

    def get_target_droplets(self):
        return self.target_droplets
    
    def get_remaining_droplets(self):
        return self.target_droplets - self.added_droplets
    
    def add_droplets(self, droplets):
        self.added_droplets += droplets

    def is_complete(self):
        if self.added_droplets == self.target_droplets:
            self.completed = True
            return True
        else:
            self.completed = False
            return False
    
class StockSolutionManager(QObject):
    '''
    Manages all the stock solutions that are included in the experiment
    When a new stock solution is to be added, it creates a new instance of the StockSolution class and assigns it a unique id
    This class is mostly used to coordinate which stock solutions go to which printer head
    '''
    def __init__(self):
        super().__init__()
        self.stock_solutions = {}

    def add_all_stock_solutions(self,stock_solution_list):
        for stock_id in stock_solution_list:
            reagent_name, concentration_str, units = stock_id.split('_')
            concentration = float(concentration_str[:])  # Remove 'M' and convert to float
            if stock_id in self.stock_solutions.keys():
                print('Duplicate stock solution found:',stock_id)
            else:
                self.stock_solutions.update({stock_id:StockSolution(stock_id,reagent_name,concentration,units)})

    def add_stock_solution(self, reagent_name, concentration,units,required_volume=None):
        # Generates a unique identifier for the reagent/concentration pair
        stock_id = '_'.join([reagent_name,str(concentration),units])
        self.stock_solutions.update({stock_id:StockSolution(stock_id,reagent_name,concentration,units,required_volume=required_volume)})

    def get_stock_solution(self, reagent_name, concentration,units):
        """Retrieve a reagent-concentration pair."""
        unique_id = '_'.join([reagent_name,str(float(concentration)),units])
        # print('Getting stock solution:',unique_id)
        return self.stock_solutions.get(unique_id)
        
    def get_stock_by_id(self, stock_id):
        return self.stock_solutions[stock_id]
    
    def get_all_stock_solutions(self):
        return self.stock_solutions.values()

    def get_stock_solution_names(self):
        return list(self.stock_solutions.keys())
    
    def get_formatted_from_stock_id(self,stock_id):
        stock = self.get_stock_by_id(stock_id)
        return stock.get_stock_name()

    def get_stock_solution_names_formated(self):
        return [stock.get_stock_name() for stock_id,stock in self.stock_solutions.items()]
    
    def get_stock_id_from_formatted(self,formatted_name):
        for stock_id,stock in self.stock_solutions.items():
            if formatted_name == stock.get_stock_name():
                return stock_id
        return None
    
    def clear_all_stock_solutions(self):
        self.stock_solutions = {}

class ReactionComposition(QObject):
    '''
    Represents a reaction composition which will be assigned to a well
    It is comprised of multiple Reagent objects which represent how many droplets of each stock solution need to be added to the reaction
    Each reaction composition should only have one Reagent instance per stock solution
    '''
    def __init__(self, unique_id):
        super().__init__()
        self.unique_id = unique_id
        self.reagents = {}  # Dictionary to hold Reagent objects with the required number of droplets
    
    def add_reagent(self, stock_solution,droplets):
        """
        Create an instance of the Reagent class using a StockSolution instance and the target number of droplets.
        Reagents are stored in a dictionary using the stock id to reference them
        """
        self.reagents.update({stock_solution.stock_id:Reagent(stock_solution,droplets)})
    
    def get_all_reagents(self):
        """Get all reagents and their concentrations in this reaction."""
        return self.reagents
    
    def get_all_target_droplets(self):
        return {stock_id:reagent.get_target_droplets() for stock_id,reagent in self.reagents.items()}
    
    def get_target_droplets_for_stock(self,stock_id):
        return self.reagents[stock_id].get_target_droplets()
    
    def get_remaining_droplets_for_stock(self,stock_id):
        return self.reagents[stock_id].get_remaining_droplets()
    
    def record_stock_print(self,stock_id,droplets):
        self.reagents[stock_id].add_droplets(droplets)

    def check_stock_complete(self,stock_id):
        return self.reagents[stock_id].is_complete()
    
    def check_all_complete(self):
        for reagent in self.reagents.values():
            if not reagent.is_complete():
                return False
        else:
            return True
        
    def reset_all_reagents(self):
        for reagent in self.reagents.values():
            reagent.added_droplets = 0
            reagent.completed = False

    def reset_reagent_by_id(self,stock_id):
        self.reagents[stock_id].added_droplets = 0
        self.reagents[stock_id].completed = False

    def get_reagent_by_id(self,stock_id):
        return self.reagents[stock_id]
    


class ReactionCollection(QObject):
    '''
    Represents the collection of all reactions that make up an experiment.
    The reaction collection contains all the specific reaction composition objects.
    It also allows for general information to be extracted from the pool of reactions.
    '''
    def __init__(self):
        super().__init__()
        self.reactions = {}  # Dictionary to hold ReactionComposition objects by name

    def add_reaction(self, reaction):
        """Add a unique reaction to the collection."""
        if not isinstance(reaction, ReactionComposition):
            raise ValueError("Must add a ReactionComposition object.")
        if reaction.unique_id not in self.reactions:
            self.reactions[reaction.unique_id] = reaction
        else:
            raise ValueError(f"Reaction '{reaction.name}' already exists in the collection.")

    def remove_reaction(self, name):
        """Remove a reaction from the collection by its name."""
        if name in self.reactions:
            del self.reactions[name]
        else:
            raise ValueError(f"Reaction '{name}' not found in the collection.")

    def is_empty(self):
        """Check if the collection is empty."""
        return len(self.reactions) == 0

    def get_reaction(self, name):
        """Get a reaction by its name."""
        return self.reactions.get(name, None)

    def get_all_reactions(self):
        """Get all reactions in the collection."""
        return list(self.reactions.values())
    
    def get_max_droplets(self, stock_id):
        """Get the maximum concentration of a specific reagent across all reactions."""
        max_droplets = None
        for reaction in self.get_all_reactions():
            droplets = reaction.get_target_droplets_for_stock(stock_id)
            if droplets is not None:
                if max_droplets is None or droplets > max_droplets:
                    max_droplets = droplets
        return max_droplets

    def clear_all_reactions(self):
        """Clear all reactions from the collection."""
        self.reactions = {}
    
class Well(QObject):
    '''
    Represents a single well in a well plate.
    The object is instantiated with an identifier such as "A1" or "B2".
    Each well can only be assigned a single reaction composition.
    '''
    state_changed = Signal(str)  # Signal to notify when the state of the well changes, sending the well ID
    def __init__(self, well_id):
        super().__init__()
        self.well_id = well_id  # Unique identifier for the well (e.g., "A1", "B2")
        self.row = well_id[0]  # Row of the well (e.g., "A", "B")
        self.row_num = ord(self.row) - 65  # Row number (0-indexed, A=0, B=1)
        self.col = int(well_id[1:])  # Column of the well (e.g., 1, 2)
        self.assigned_reaction = None  # The reaction assigned to this well
        self.coordinates = None  # The x, y, and z coordinates of the well on the plate

    def assign_reaction(self, reaction):
        """Assign a reaction to the well."""
        if not isinstance(reaction, ReactionComposition):
            raise ValueError("Must assign a ReactionComposition object.")
        self.assigned_reaction = reaction

    def assign_coordinates(self, x, y,z):
        """Assign coordinates to the well."""
        self.coordinates = {'X':x, 'Y':y, 'Z':z}

    def get_coordinates(self):
        """Get the coordinates of the well."""
        return self.coordinates

    def get_target_droplets(self,stock_id):
        return self.assigned_reaction.get_target_droplets_for_stock(stock_id)

    def get_remaining_droplets(self,stock_id):
        return self.assigned_reaction.get_remaining_droplets_for_stock(stock_id)
    
    def get_assigned_reaction(self):
        return self.assigned_reaction

    def record_stock_print(self,stock_id,droplets):
        self.assigned_reaction.record_stock_print(stock_id,droplets)
        print('emitting state changed',self.well_id)
        self.state_changed.emit(self.well_id)

    def check_stock_complete(self,stock_id):
        return self.assigned_reaction.check_stock_complete(stock_id)

    def check_all_complete(self):
        return self.assign_reaction.check_all_complete()

class WellPlate(QObject):
    well_state_changed_signal = Signal(str)  # Signal to notify when the state of a well changes, sending the well ID
    clear_all_wells_signal = Signal()  # Signal to notify when all wells are cleared
    plate_format_changed_signal = Signal()  # Signal to notify when the well plate is updated

    def __init__(self, all_plate_data):
        super().__init__()
        self.all_plate_data = all_plate_data
        self.current_plate_data = self.get_default_plate_data()
        self.calibrations = self.current_plate_data['calibrations']
        self.rows = self.current_plate_data['rows']
        self.cols = self.current_plate_data['columns']
        self.wells = self.create_wells()
        self.excluded_wells = set()

        self.calibration_applied = False
        self.temp_calibration_data = {}
    
        self.apply_calibration_data()

    def check_calibration_applied(self):
        return self.calibration_applied
    
    def get_current_plate_name(self):
        return self.current_plate_data['name']
    
    def get_all_current_plate_calibrations(self):
        return self.calibrations
    
    def get_calibration_by_name(self, name):
        return self.calibrations.get(name, None)
    
    def get_temp_calibration_by_name(self, name):
        return self.temp_calibration_data.get(name, None)
    
    def set_calibration_position(self, position_name, coordinates):
        """Set a temporary calibration position."""
        self.temp_calibration_data[position_name] = coordinates
    
    def update_calibration_data(self):
        """Run the full update of all calibration data."""
        self.store_calibrations()
        self.save_calibrations_to_file()
        self.apply_calibration_data()

    def get_plate_data_by_name(self, plate_name):
        for plate_data in self.all_plate_data:
            if plate_data['name'] == plate_name:
                return plate_data
        raise ValueError(f"Plate format '{plate_name}' not found.")        

    def store_calibrations(self):
        """Save the temporary calibration data to the main calibration data."""
        plate_name = self.get_current_plate_name()
        for plate_data in self.all_plate_data:
            print(plate_data['name'])
            if plate_data['name'] == plate_name:
                plate_data['calibrations'] = self.temp_calibration_data.copy()
                self.calibrations = self.temp_calibration_data.copy()
                # Clear the temporary data after saving
                self.temp_calibration_data.clear()
                return
        raise ValueError(f"Plate format '{plate_name}' not found.")

    def save_calibrations_to_file(self, file_path='.\\MVC-interface\\Presets\\Plates.json'):
        """Save the current calibration data to a JSON file."""
        try:
            with open(file_path, 'w') as file:
                json.dump(self.all_plate_data, file, indent=4)
            #print(f"Calibration data saved to {file_path}")
        except Exception as e:
            pass
            #print(f"Error saving calibration data to file: {e}")

    def discard_temp_calibrations(self):
        """Discard the temporary calibration data."""
        self.temp_calibration_data.clear()

    def get_default_plate_data(self):
        """Get the data for the plate set to default"""
        for plate_data in self.all_plate_data:
            if plate_data['default']:
                return plate_data

    def get_all_plate_names(self):
        return [plate_data['name'] for plate_data in self.all_plate_data]
    
    def get_current_plate_name(self):
        return self.current_plate_data['name']
    
    def create_wells(self):
        """Create wells based on the plate format."""
        wells = {}
        for row in range(self.rows):
            for col in range(self.cols):
                well_id = f"{chr(row + 65)}{col + 1}"
                well = Well(well_id)
                well.state_changed.connect(self.well_state_changed)
                wells[well_id] = well
        self.plate_format_changed_signal.emit()
        return wells
    
    def set_plate_format(self, plate_name):
        """Set the plate format based on the selected name."""
        for plate_data in self.all_plate_data:
            if plate_data['name'] == plate_name:
                self.current_plate_data = plate_data
                self.rows = plate_data['rows']
                self.cols = plate_data['columns']
                self.wells = self.create_wells()
                self.calibrations = plate_data['calibrations']
                self.calibration_applied = False
                self.apply_calibration_data()
                self.plate_format_changed_signal.emit()
                return
        raise ValueError(f"Plate format '{plate_name}' not found.")
    
    def get_plate_dimensions(self):
        return self.rows,self.cols
    
    def get_coords(self,coords):
        return np.array(list(coords.values()))
    
    def calculate_plate_matrix(self):
        """Calculate the transformation matrix for the plate."""
        self.corners = np.array([
            [self.get_coords(self.calibrations['top_left'])[0:2]],
            [self.get_coords(self.calibrations['top_right'])[0:2]],
            [self.get_coords(self.calibrations['bottom_right'])[0:2]],
            [self.get_coords(self.calibrations['bottom_left'])[0:2]]
        ], dtype = "float32")

        self.max_columns = self.cols - 1
        self.max_rows = self.rows - 1
        self.plate_width = self.max_columns * self.current_plate_data['spacing']
        self.plate_depth = self.max_rows * self.current_plate_data['spacing']

        self.plate_dimensions = np.array([
            [0, 0],
            [0, self.plate_width],
            [self.plate_depth, self.plate_width],
            [self.plate_depth, 0]
        ], dtype = "float32")

        self.generate_transformation_matrix()

        self.row_z_step = (self.calibrations['bottom_left']['Z'] - self.calibrations['top_left']['Z']) / (self.rows)
        self.col_z_step =  (self.calibrations['top_right']['Z'] - self.calibrations['top_left']['Z']) / (self.cols)

        well_coords_df = self.calculate_all_well_positions()
        return well_coords_df

    def generate_transformation_matrix(self):
        '''
        Performs a 4-point transformation of the coordinate plane using the
        experimentally derived plate corners. This takes the machine coordinates
        and finds the matrix required to convert them into the coordinate plane
        that matches the defined geometry of the plate. This matrix can then be
        reversed and used to take the positions where wells should be and
        convert them into the corresponding dobot coordinates.

        This transformation accounts for the deviations in the machine coordinate
        system but only applies to the X and Y dimensions.
        '''
        self.trans_matrix = cv2.getPerspectiveTransform(self.corners, self.plate_dimensions)
        self.inv_trans_matrix = np.linalg.pinv(self.trans_matrix)
    
    def correct_xy_coords(self,x,y):
        '''
        Uses the transformation matrix to correct the XY coordinates
        '''
        target = np.array([[x,y]], dtype = "float32")
        target_transformed = cv2.perspectiveTransform(np.array(target[None,:,:]), self.inv_trans_matrix)
        return target_transformed[0][0]

    def get_well_coords(self,row,column):
        '''
        Uses the well indices to determine the dobot coordinates of the well
        '''
        x,y = self.correct_xy_coords(row*self.current_plate_data['spacing'],column*self.current_plate_data['spacing'])
        z = self.calibrations['top_left']['Z'] + (row * self.row_z_step) + (column * self.col_z_step)
        x = int(round(x,0))
        y = int(round(y,0))
        z = int(round(z,0))
        return {'X':x, 'Y':y, 'Z':z}
    
    def calculate_all_well_positions(self):
        # Create an empty list for the well positions
        well_positions = []

        # Iterate over all the rows and columns of the plate
        for row in range(self.rows):
            for column in range(self.cols):
                # Calculate the corrected coordinates for the well
                coords = self.get_well_coords(row, column)

                # Add the well position to the list
                well_positions.append({
                    'row': row,
                    'column': column,
                    'X': coords['X'],
                    'Y': coords['Y'],
                    'Z': coords['Z']
                })

        # Create a DataFrame from the list
        well_positions_df = pd.DataFrame(well_positions)
        return well_positions_df
    
    def assign_well_coordinates(self, well_id, x, y,z):
        """Assign coordinates to a specific well."""
        well = self.wells.get(well_id)
        if well is not None:
            well.assign_coordinates(x,y,z)
        else:
            raise ValueError(f"Well '{well_id}' does not exist in the plate.")

    def assign_well_coordinates_by_row_col(self, row, col, x, y,z):
        """Assign coordinates to a well by its row and column."""
        well_id = f"{chr(row + 65)}{col + 1}"
        self.assign_well_coordinates(well_id, x, y,z)

    def assign_all_well_coordinates(self, well_coords_df):
        """Assign coordinates to all wells in the plate."""
        for i,row in well_coords_df.iterrows():
            well_id = f"{chr(row['row'] + 65)}{row['column'] + 1}"
            self.assign_well_coordinates(well_id, row['X'], row['Y'],row['Z'])

    def apply_calibration_data(self):
        if len(list(self.calibrations)) < 4:
            self.calibration_applied = False
            #print(f"Calibration is incomplete. Need at least 4 calibration points, but only {len(list(self.calibrations))} provided.")
            return
        else:
            well_coords_df = self.calculate_plate_matrix()
            self.assign_all_well_coordinates(well_coords_df)
            self.calibration_applied = True

    def get_num_rows(self):
        """Get the number of rows in the plate."""
        return self.rows
    
    def get_num_cols(self):
        """Get the number of columns in the plate."""
        return self.cols

    def exclude_well(self, well_id):
        """Exclude a well from being used."""
        if well_id in self.wells:
            self.excluded_wells.add(well_id)
        else:
            raise ValueError(f"Well '{well_id}' does not exist in the plate.")

    def include_well(self, well_id):
        """Include an excluded well back into use."""
        self.excluded_wells.discard(well_id)

    def get_well(self, well_id):
        """Retrieve a specific well by its ID."""
        return self.wells.get(well_id, None)

    def zigzag_order(self,wells, fill_by="columns"):
        """
        Return wells ordered in a zigzag pattern.

        Args:
            wells (list of Well): The list of wells to be ordered.
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            list of Well: The list of wells ordered in a zigzag pattern.
        """
        def row_to_num(row):
            """Convert the row letter to a number (e.g., 'A' -> 0, 'B' -> 1)."""
            return ord(row) - ord('A')

        if fill_by == "rows":
            # Sort by row first (converted to number), and by column within each row, alternating the column order
            wells.sort(key=lambda w: (row_to_num(w.row), w.col if row_to_num(w.row) % 2 == 0 else -w.col))
        else:  # fill_by == "columns"
            # Sort by column first, and by row (converted to number) within each column, starting with A1
            wells.sort(key=lambda w: (w.col, -row_to_num(w.row) if w.col % 2 == 0 else row_to_num(w.row)))

        return wells

    def get_available_wells(self, fill_by="columns",start_row=0,start_col=0):
        """
        Get a list of available wells, sorted by rows or columns in a zigzag pattern.

        Args:
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            list of Well: Sorted list of available wells.
        """
        if fill_by not in ["rows", "columns"]:
            raise ValueError("fill_by must be 'rows' or 'columns'.")

        available_wells = [well for well in self.wells.values() if well not in self.excluded_wells and well.assigned_reaction is None]
        available_wells = [well for well in available_wells if well.row_num >= start_row and well.col >= start_col+1]
        return self.zigzag_order(available_wells, fill_by=fill_by)
    
    def get_all_wells(self):
        """Get a list of all wells."""
        return list(self.wells.values())

    def clear_all_wells(self):
        """Clear all wells and reset their status."""
        self.wells = {}
        self.exclude_wells = set()
        self.wells = self.create_wells()
        self.clear_all_wells_signal.emit()

    def reset_all_wells_for_stock(self,stock_id):
        for well in self.wells.values():
            if well.assigned_reaction is not None:
                well.assigned_reaction.reset_reagent_by_id(stock_id)
                # well.state_changed.emit(well.well_id)
        self.well_state_changed_signal.emit('all')
        

    def reset_all_wells(self):
        for well in self.wells.values():
            if well.assigned_reaction is not None:
                well.assigned_reaction.reset_all_reagents()
                # well.state_changed.emit(well.well_id)
        self.well_state_changed_signal.emit('all')

    def get_plate_status(self):
        """Get the status of the entire well plate."""
        status = {}
        for well_id, well in self.wells.items():
            status[well_id] = well.get_status()
        return status

    def assign_reactions_to_wells(self, reactions, fill_by="columns",start_row=0,start_col=0):
        """
        Systematically assign reactions to available wells.

        Args:
            reactions (list of ReactionComposition): The reactions to assign to wells.
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            dict: A dictionary mapping reaction names to well IDs.
        """
        available_wells = self.get_available_wells(fill_by=fill_by,start_row=start_row,start_col=start_col)
        reaction_assignment = {}

        if len(reactions) > len(available_wells):
            raise ValueError("Not enough available wells to assign all reactions.")
        #print(f"Assigning {len(reactions)} reactions to {len(available_wells)} available wells.")
        for i, reaction in enumerate(reactions):
            well = available_wells[i]
            well.assign_reaction(reaction)
            reaction_assignment[reaction.unique_id] = well.well_id
            # print(f"Assigned reaction '{reaction.unique_id}' to well '{well.well_id}'.")

        return reaction_assignment
    
    def get_all_wells_with_reactions(self, fill_by="columns"):
        """
        Get all wells that have been assigned a reaction, sorted in a zigzag pattern.

        Args:
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            list of Well: Sorted list of wells with assigned reactions.
        """
        wells_with_reactions = [well for well in self.wells.values() if well.assigned_reaction is not None]

        return self.zigzag_order(wells_with_reactions, fill_by=fill_by)
    
    def well_state_changed(self, well_id):
        """Handle changes in the state of a well."""
        self.well_state_changed_signal.emit(well_id)

class PrinterHead(QObject):
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
    volume_changed_signal = Signal(str) # Signal to notify when the volume of the printer head changes
    def __init__(self, stock_solution,color='Blue',calibration_chip=False):
        super().__init__()
        self.stock_solution = stock_solution
        self.color = color
        self.confirmed = False
        self.completed = False
        self.current_volume = None
        self.effective_resistance = None
        self.bias = None
        self.target_droplet_volume = None
        self.calibration_chip = calibration_chip
        self.predictive_model = None
        self.resistance_pulse_width = None

    def record_droplet_volume_lost(self,droplet_count):
        if self.target_droplet_volume is not None:
            self.current_volume -= (droplet_count * self.target_droplet_volume) / 1000
            self.volume_changed_signal.emit(self.stock_solution.get_stock_id())
        else:
            print('No target droplet volume set for printer head:',self.stock_solution.get_stock_id())

    def set_absolute_volume(self,volume):            
        self.current_volume = volume
        self.volume_changed_signal.emit(self.stock_solution.get_stock_id())

    def change_volume(self,volume):
        if self.current_volume is None:
            self.current_volume = volume
        self.current_volume += volume
        self.volume_changed_signal.emit(self.stock_solution.get_stock_id())

    def is_calibration_chip(self):
        return self.calibration_chip
    
    def get_current_volume(self):
        return self.current_volume
    
    def get_target_droplet_volume(self):
        return self.target_droplet_volume

    def get_stock_solution(self):
        return self.stock_solution

    def get_stock_id(self):
        if self.stock_solution is None:
            return 'Calibration'
        return self.stock_solution.get_stock_id()
    
    def get_reagent_name(self):
        if self.stock_solution is None:
            return 'Calibration'
        return self.stock_solution.get_reagent_name()
    
    def get_stock_concentration(self):
        if self.stock_solution is None:
            return '--'
        return self.stock_solution.get_stock_concentration()
    
    def get_stock_name(self,new_line=False):
        if self.stock_solution is None:
            return 'Calibration'
        return self.stock_solution.get_stock_name(new_line=new_line)

    def get_color(self):
        return self.color

    def change_stock_solution(self, stock_solution):
        self.stock_solution = stock_solution
    
    def change_color(self, new_color):
        self.color = new_color

    def mark_complete(self):
        self.completed = True

    def mark_incomplete(self):
        self.completed = False

    def check_complete(self,well_plate):
        '''Check the stock solution to see if all droplets have been added'''
        stock_id = self.get_stock_id()
        print('Checking stock complete:',stock_id)
        for well in well_plate.get_all_wells():
            if well.assigned_reaction is not None:
                if not well.check_stock_complete(stock_id):
                    self.mark_incomplete()
                    return False
        if not self.calibration_chip:
            self.mark_complete()
        return True

    def check_calibration_complete(self):
        '''Check if the calibration data has been set for the printer head'''
        if self.effective_resistance is not None and self.bias is not None and self.target_droplet_volume is not None and self.predictive_model is not None and self.resistance_model is not None:
            return True
        else:
            return False
    
    def set_calibration_data(self, resistance, bias, target_droplet_volume,predictive_model,resistance_pulse_width):
        #print(f'Calibration data set for printer head {self.stock_solution.get_stock_id()}, R:{resistance}, B:{bias}, V:{target_droplet_volume}')
        self.effective_resistance = resistance
        self.bias = bias
        self.target_droplet_volume = target_droplet_volume
        self.predictive_model = predictive_model
        self.resistance_pulse_width = resistance_pulse_width

    def get_prediction_data(self):
        return self.current_volume,self.effective_resistance, self.target_droplet_volume, self.bias, self.predictive_model, self.resistance_pulse_width


class PrinterHeadManager(QObject):
    """
    Manages all printer heads in the system, including tracking, assignment, and swapping.

    Attributes:
    - printer_heads (list): List of all printer heads created from the reaction collection.
    - assigned_printer_heads (dict): Mapping of slot numbers to assigned printer heads.
    - unassigned_printer_heads (list): List of printer heads that have not yet been assigned to any slot.
    """
    volume_changed_signal = Signal()
    def __init__(self,color_dict,rack_model):
        super().__init__()
        self.print_head_colors = color_dict
        self.rack_model = rack_model
        self.printer_heads = []
        self.assigned_printer_heads = {}
        self.unassigned_printer_heads = []
        self.create_calibration_chip()
        calibration_chip = self.get_calibration_chip()
        self.swap_printer_head(4,calibration_chip)


    def create_printer_heads(self, stock_solutions_manager):
        """
        Create printer heads based on the reagents and concentrations in the reaction collection.
        
        Args:
        - reaction_collection (ReactionCollection): The collection of reactions from which to create printer heads.
        """
        stock_solutions = stock_solutions_manager.get_all_stock_solutions()
        for stock_solution in stock_solutions:
            printer_head = PrinterHead(stock_solution, color=self.generate_color())
            printer_head.volume_changed_signal.connect(self.volume_changed)
            self.printer_heads.append(printer_head)
            self.unassigned_printer_heads.append(printer_head)
        #print(f"Created {len(self.printer_heads)} printer heads.")

    def create_calibration_chip(self):
        '''Create a calibration chip printer head'''
        calibration_chip = PrinterHead(None,color="#000000",calibration_chip=True)
        self.printer_heads.append(calibration_chip)
        self.unassigned_printer_heads.append(calibration_chip)
        print('Created calibration chip printer head.')

    def get_calibration_chip(self):
        for printer_head in self.printer_heads:
            if printer_head.is_calibration_chip():
                print('Found calibration chip printer head')
                return printer_head
        print('No calibration chip printer head found.')
        return None

    def volume_changed(self,stock_id):
        print(f'Volume changed for printer head {stock_id}')
        self.volume_changed_signal.emit()


    def assign_printer_head_to_slot(self, slot_number):
        """
        Assign an available printer head to a specified slot in the rack.

        Args:
        - slot_number (int): The slot number where the printer head should be assigned.
        - rack_model (RackModel): The rack model where the slot is located.
        
        Returns:
        - bool: True if a printer head was successfully assigned, False if no more unassigned printer heads are available.
        """
        if self.unassigned_printer_heads:
            printer_head = self.unassigned_printer_heads.pop(0)
            self.rack_model.update_slot_with_printer_head(slot_number, printer_head)
            self.assigned_printer_heads[slot_number] = printer_head
            print(f"Assigned printer head '{printer_head.get_stock_id()}' to slot {slot_number}.")
            return True
        else:
            print("No more unassigned printer heads available.")
            return False

    def swap_printer_head(self, slot_number, new_printer_head):
        """
        Swap the printer head in the specified slot with the provided unassigned printer head.
        """
        old_printer_head = self.rack_model.slots[slot_number].printer_head
        if old_printer_head:
            self.unassigned_printer_heads.append(old_printer_head)
            self.unassigned_printer_heads.remove(new_printer_head)
            self.rack_model.update_slot_with_printer_head(slot_number, new_printer_head)
            self.assigned_printer_heads[slot_number] = new_printer_head
            print(f"Swapped printer head in slot {slot_number} with '{new_printer_head.get_stock_id()}'.")
        else:
            self.rack_model.update_slot_with_printer_head(slot_number, new_printer_head)
            self.assigned_printer_heads[slot_number] = new_printer_head
            self.unassigned_printer_heads.remove(new_printer_head)
            print(f"No printer head in slot {slot_number} to swap.")


    def generate_color(self):
        """
        Generate a color for the printer head. This is a placeholder function.
        
        Returns:
        - str: The color code or name.
        """
        colors = list(self.print_head_colors.values())
        return colors[len(self.printer_heads) % len(colors)]

    def get_all_printer_heads(self):
        """
        Get all printer heads managed by this class.

        Returns:
        - list: List of all printer heads.
        """
        return self.printer_heads

    def get_unassigned_printer_heads(self):
        """
        Get all unassigned printer heads.

        Returns:
        - list: List of unassigned printer heads.
        """
        return self.unassigned_printer_heads

    def get_assigned_printer_heads(self):
        """
        Get all assigned printer heads.

        Returns:
        - dict: Dictionary mapping slot numbers to assigned printer heads.
        """
        return self.assigned_printer_heads
    
    def get_printer_head_by_id(self, stock_id):
        for printer_head in self.printer_heads:
            if printer_head.get_stock_id() == stock_id:
                return printer_head
        return None
    
    def clear_all_printer_heads(self):
        """
        Clear all printer heads and reset the assignment status.
        """
        self.printer_heads = []
        self.assigned_printer_heads = {}
        self.unassigned_printer_heads = []

class Slot(QObject):
    """
    Represents a slot in a system.

    Attributes:
        number (int): The slot number.
        printer_head (PrinterHead): The printer head in the slot.
        confirmed (bool): Indicates if the slot has been confirmed.
    """

    def __init__(self, number, printer_head):
        super().__init__()
        self.number = number
        self.printer_head = printer_head
        self.confirmed = False
        self.locked = False
        self.coordinates = None

    def set_locked(self, locked):
        self.locked = locked

    def is_locked(self):
        return self.locked
    
    def assign_coordinates(self, x, y,z):
        """Assign coordinates to the slot."""
        self.coordinates = {'X':x, 'Y':y, 'Z':z}

    def get_coordinates(self):
        """Get the coordinates of the slot."""
        return self.coordinates
    
    def change_printer_head(self, new_printer_head,returned=False):
        self.printer_head = new_printer_head
        if not returned:
            self.unconfirm()
    
    def confirm(self):
        """
        Confirms the slot.
        """
        self.confirmed = True

    def unconfirm(self):
        """
        Unconfirms the slot.
        """
        self.confirmed = False


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

    slot_updated = Signal()
    gripper_updated = Signal()
    error_occurred = Signal(str)
    rack_calibration_updated_signal = Signal()

    def __init__(self, num_slots,location_data=None):
        super().__init__()
        self.slots = [Slot(i, None) for i in range(num_slots)]
        self.gripper_printer_head = None
        self.gripper_slot_number = None
        self.calibrations = {}
        if location_data is not None:
            self.process_location_data(location_data)

        self.calibration_applied = False
        self.temp_calibration_data = {}
    
        self.apply_calibration_data()

    def apply_calibration_data(self):
        if self.calibrations['rack_position_Left'] == {} or self.calibrations['rack_position_Right'] == {}:
            self.calibration_applied = False
            #print(f"Calibration is incomplete. Need at least 2 calibration points, but only {len(list(self.calibrations))} provided.")
            return
        else:
            slot_positions = self.calculate_slot_positions()
            self.assign_slot_positions(slot_positions)
            self.calibration_applied = True
        
    def calculate_slot_positions(self):
        '''
        Calculate the positions of the slots based on the calibration data
        '''
        slot_positions = []
        left_calibration = self.calibrations['rack_position_Left']
        right_calibration = self.calibrations['rack_position_Right']

        x_diff = right_calibration['X'] - left_calibration['X']
        y_diff = right_calibration['Y'] - left_calibration['Y']
        z_diff = right_calibration['Z'] - left_calibration['Z']
        num_slots = self.get_num_slots()

        slot_depth = x_diff / (num_slots + 1)
        slot_width = y_diff / (num_slots + 1)
        slot_height = z_diff / (num_slots + 1)
        for i in range(1,num_slots+1):
            slot_positions.append({
                'X': int(round(left_calibration['X'] + (i * slot_depth),0)),
                'Y': int(round(left_calibration['Y'] + (i * slot_width),0)),
                'Z': int(round(left_calibration['Z'] + (i * slot_height),0))
            })
        return slot_positions
    
    def assign_slot_positions(self,slot_positions):
        for i,slot in enumerate(self.slots):
            slot.assign_coordinates(slot_positions[i]['X'],slot_positions[i]['Y'],slot_positions[i]['Z'])

    def process_location_data(self,location_data):
        if location_data.get('rack_position_Right',None) is not None:
            self.calibrations['rack_position_Right'] = location_data['rack_position_Right']
        else:
            self.calibrations['rack_position_Right'] = {}
        if location_data.get('rack_position_Left',None) is not None:
            self.calibrations['rack_position_Left'] = location_data['rack_position_Left']
        else:
            self.calibrations['rack_position_Left'] = {}

    def get_all_current_rack_calibrations(self):
        return self.calibrations
    
    def get_calibration_by_name(self, name):
        return self.calibrations.get(name, None)
    
    def get_temp_calibration_by_name(self, name):
        return self.temp_calibration_data.get(name, None)
    
    def set_calibration_position(self, position_name, coordinates):
        """Set a temporary calibration position."""
        self.temp_calibration_data[position_name] = coordinates

    def store_calibrations(self):
        """Save the temporary calibration data to the main calibration data."""
        for position_name, coords in self.temp_calibration_data.items():
            self.calibrations[position_name] = coords
        self.temp_calibration_data.clear()

    def discard_temp_calibrations(self):
        """Discard the temporary calibration data."""
        self.temp_calibration_data.clear()

    def update_calibration_data(self):
        """Run the full update of all calibration data."""
        self.store_calibrations()
        self.save_calibrations_to_file()
        self.apply_calibration_data()

    def save_calibrations_to_file(self):
        self.rack_calibration_updated_signal.emit()

    def check_calibration_applied(self):
        return self.calibration_applied
    
    def get_slot_coordinates(self,slot_number):
        return self.slots[slot_number].get_coordinates()

    def get_num_slots(self):
        return len(self.slots)
    
    def get_all_slots(self):
        return self.slots

    def update_slot_with_printer_head(self, slot_number, printer_head):
        """
        Update a slot with a new printer head.

        Args:
        - slot_number (int): The slot number to update.
        - printer_head (PrinterHead): The printer head to place in the slot.
        """
        if 0 <= slot_number < len(self.slots):
            slot = self.slots[slot_number]
            slot.change_printer_head(printer_head)
            slot.set_locked(False)
            self.slot_updated.emit()
            #print(f"Slot {slot_number} updated with printer head: {printer_head.get_stock_id()}, {printer_head.color}")

    def lock_slot(self, slot_number):
        """
        Lock a slot when its printer head is in the gripper.
        """
        slot = self.slots[slot_number]
        slot.set_locked(True)
        self.slot_updated.emit()

    def unlock_slot(self, slot_number):
        """
        Unlock a slot when its printer head is returned from the gripper.
        """
        slot = self.slots[slot_number]
        slot.set_locked(False)
        self.slot_updated.emit()
    
    def confirm_slot(self, slot_number):
        """
        Confirm a slot.

        Args:
        - slot_number (int): The slot number to confirm.
        """
        if 0 <= slot_number < len(self.slots):
            if self.slots[slot_number].printer_head is not None:
                self.slots[slot_number].confirm()
                self.slot_updated.emit()
                self.gripper_updated.emit()
                #print(f"Slot {slot_number} confirmed.")
            else:
                error_msg = f"Slot {slot_number} has no printer head to confirm."
                self.error_occurred.emit(error_msg)
                print(error_msg)

    def clear_all_slots(self):
        """
        Clear all slots in the rack.
        """
        for slot in self.slots:
            slot.change_printer_head(None)
            slot.unconfirm()
        self.gripper_printer_head = None
        self.gripper_slot_number = None
        self.slot_updated.emit()
        self.gripper_updated.emit()
        print("All slots cleared.")
    
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
            slot.change_printer_head(None,returned=True)
            self.lock_slot(slot_number)
            self.slot_updated.emit()
            self.gripper_updated.emit()
            #print(f"Printer head from slot {slot_number} transferred to gripper.")
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
            slot.change_printer_head(self.gripper_printer_head,returned=True)
            self.unlock_slot(slot_number)
            self.gripper_printer_head = None
            self.gripper_slot_number = None
            self.slot_updated.emit()
            self.gripper_updated.emit()
            #print(f"Printer head transferred from gripper to slot {slot_number}.")
        else:
            self.error_occurred.emit(error_msg)
            print(error_msg)

    def swap_printer_heads_between_slots(self, slot_number_1, slot_number_2):
        """
        Swap the printer heads between two slots and emit signals.
        """
        slot_1 = self.slots[slot_number_1]
        slot_2 = self.slots[slot_number_2]
        origial_slot_1_printer_head = slot_1.printer_head
        slot_1.change_printer_head(slot_2.printer_head)
        slot_2.change_printer_head(origial_slot_1_printer_head)
        self.slot_updated.emit()

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
                if slot.printer_head.is_calibration_chip():
                    printer_head_info = {
                        "reagent": "Calibration",
                        "concentration": "--",
                        "color": slot.printer_head.color
                    }
                else:
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
                "reagent": self.gripper_printer_head.get_reagent_name(),
                "concentration": self.gripper_printer_head.get_stock_concentration(),
                "color": self.gripper_printer_head.color
            }
        return None
    
    def get_gripper_printer_head(self):
        return self.gripper_printer_head
    
    def assign_reagents_to_printer_heads(self, reaction_collection):
        """
        Assigns reagents from the reaction collection to printer heads and places them in available slots.
        """
        slot_index = 0
        for reagent_name,concentration in reaction_collection.get_unique_reagent_conc_pairs():
            if slot_index >= len(self.slots):
                raise ValueError("Not enough slots to assign all reagents.")
            
            # Create a PrinterHead for this reagent and concentration
            printer_head = PrinterHead(reagent=reagent_name, concentration=concentration, color=self.generate_color(slot_index))
            
            # Assign the PrinterHead to the current slot and confirm the slot
            self.update_slot_with_printer_head(slot_index, printer_head)
            
            slot_index += 1

    def generate_color(self, slot_index):
        """
        Generate a color for the printer head based on the slot index. This is a placeholder function.
        """
        colors = ["red", "green", "blue", "yellow", "purple", "orange"]
        return colors[slot_index % len(colors)]

class LocationModel(QObject):
    """
    Model for managing location data, including reading and writing to a JSON file.

    Attributes:
    - locations: A dictionary of location names and their XYZ coordinates.
    """

    locations_updated = Signal()  # Signal to notify when locations are updated
    current_location_updated = Signal(str)  # Signal to notify when the current location is updated

    def __init__(self, json_file_path='Presets\\Locations.json',obstacle_path='Presets\\Obstacles.json'):
        super().__init__()
        # Get the directory of the current script    
        self.json_file_path = json_file_path   
        self.locations = {}  # Dictionary to hold location data
        self.obstacle_path = obstacle_path
        self.boundaries = []
        self.obstacles = []

    def load_locations(self):
        """Load locations from a JSON file."""
        try:
            with open(self.json_file_path, "r") as file:
                self.locations = json.load(file)
            self.locations_updated.emit()
            #print(f"Locations loaded from {self.json_file_path}")
        except FileNotFoundError:
            #print(f"{self.json_file_path} not found. Starting with an empty locations dictionary.")
            self.locations = {}
        except json.JSONDecodeError:
            #print(f"Error decoding JSON from {self.json_file_path}. Starting with an empty locations dictionary.")
            self.locations = {}
        except Exception as e:
            pass
            #print(f"Failed to load locations: {e}")

    def save_locations(self):
        """Save locations to a JSON file."""
        try:
            with open(self.json_file_path, "w") as file:
                json.dump(self.locations, file, indent=4)
            #print(f"Locations saved to {self.json_file_path}")

        except Exception as e:
            #print(f"Failed to save locations: {e}")
            pass

    def load_obstacles(self):
        """Load locations from a JSON file."""
        try:
            with open(self.obstacle_path, "r") as file:
                data = json.load(file)
                self.boundaries = data['boundaries']
                self.obstacles = data['obstacles']
            #print(f"Obstacles loaded from {self.obstacle_path}")
        except FileNotFoundError:
            #print(f"{self.obstacle_path} not found. Starting with an empty obstacles dictionary.")
            self.obstacles = {}
        except json.JSONDecodeError:
            #print(f"Error decoding JSON from {self.obstacle_path}. Starting with an empty locations dictionary.")
            self.obstacles = {}
        except Exception as e:
            pass
            #print(f"Failed to load locations: {e}")

    def get_obstacles(self):
        return self.obstacles
    
    def get_boundaries(self):
        return self.boundaries

    def add_location(self, name, x, y, z):
        """Add a new location or update an existing one."""
        self.locations[name] = {'X': x, 'Y': y, 'Z': z}
        self.locations_updated.emit(name)
        #print(f"Location '{name}' added/updated.")

    def update_location(self, name, x, y, z):
        """Update an existing location by name."""
        if name in self.locations:
            self.locations[name] = {'X': x, 'Y': y, 'Z': z}
            self.current_location_updated.emit(name)
            self.locations_updated.emit()
            #print(f"Location '{name}' updated.")
        else:
            pass
            #print(f"Location '{name}' not found.")

    def update_location_coords(self, name, coords):
        """Update an existing location by name."""
        if name in self.locations:
            self.locations[name] = coords
            self.locations_updated.emit()
            #print(f"Location '{name}' updated.")
        else:
            pass
            #print(f"Location '{name}' not found.")

    def remove_location(self, name):
        """Remove a location by name."""
        if name in self.locations:
            del self.locations[name]
            self.locations_updated.emit()
            #print(f"Location '{name}' removed.")
        else:
            pass
            #print(f"Location '{name}' not found.")

    def get_location(self, name):
        """Get a location's coordinates by name in an array [x,y,z]."""
        if name in self.locations:
            return [self.locations[name]['X'], self.locations[name]['Y'], self.locations[name]['Z']]
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
    
    def post_calibration_update(self,calibration_data):
        self.update_pause_location(calibration_data)
        self.update_plate_locatin(calibration_data)
        self.save_locations()
    
    def update_pause_location(self,coords):
        offset_coords = {'X':coords['X']-500,'Y':coords['Y']-500,'Z':coords['Z']}
        self.update_location_coords('pause',offset_coords)
        self.locations_updated.emit()
        #print(f"Pause location updated.")

    def update_plate_locatin(self,coords):
        self.update_location_coords('plate',coords)
        self.locations_updated.emit()
        #print(f"Plate location updated.")

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
    pressure_updated = Signal()  # Signal to emit when print pressure readings are updated
    printing_parameters_updated = Signal()  # Signal to emit when printing parameters are updated
    ports_updated = Signal(list)  # Signal to notify view of available ports update
    connection_requested = Signal(str, str)  # Signal to request connection
    gripper_state_changed = Signal(bool)  # Signal to notify when gripper state changes
    machine_paused = Signal()  # Signal to notify when machine is paused
    home_status_signal = Signal()
    command_numbers_updated = Signal()

    def __init__(self):
        super().__init__()
        self.available_ports = []
        self.machine_connected = False
        self.balance_connected = False
        # self.machine_port = "Virtual"
        self.balance_port = "Virtual"

        self.motors_enabled = False
        self.target_x = 0
        self.target_y = 0
        self.target_z = 0
        self.target_p = 0
        self.target_r = 0

        self.current_x = 0
        self.current_y = 0
        self.current_z = 0
        self.current_p = 0
        self.current_r = 0

        self.motors_homed = False
        self.current_location = "Unknown"
        self.paused = False
        self.machine_free = True
        self.current_command_num = 0
        self.last_completed_command_num = 0
        self.current_micros = 0

        self.gripper_open = False
        self.gripper_active = False

        self.step_num = 4
        self.possible_steps = [2,10,50,250,500,1000,2000]
        self.step_size = self.possible_steps[self.step_num]

        self.current_print_pressure = 0
        self.print_pressure_readings = np.zeros(100)  # Array to store the last 100 pressure readings
        self.current_refuel_pressure = 0
        self.refuel_pressure_readings = np.zeros(100)  # Array to store the last 100 pressure readings
        
        self.target_print_pressure = 0
        self.target_refuel_pressure = 0
        self.print_pulse_width = 0
        self.refuel_pulse_width = 0

        self.fss = 6553
        self.psi_offset = 8192
        self.psi_max = 15

        self.regulating_print_pressure = False
        self.regulating_refuel_pressure = False

        self.max_cycle = 0
        self.cycle_count = 0

    def update_ports(self, ports):
        self.available_ports = ports
        self.ports_updated.emit(self.available_ports)

    def connect_machine(self):
        self.machine_connected = True
        self.machine_state_updated.emit(self.machine_connected)

    def disconnect_machine(self):
        self.machine_connected = False
        self.machine_state_updated.emit(self.machine_connected)
        self.motors_enabled = False
        self.motor_state_changed.emit(self.motors_enabled)
        self.regulating_print_pressure = False
        self.regulating_refuel_pressure = False
        self.regulation_state_changed.emit(self.regulating_print_pressure)
        self.reset_home_status()
        self.home_status_signal.emit()
    
    def is_connected(self):
        return self.machine_connected
    
    def is_balance_connected(self):
        return self.balance_connected
    
    def motors_are_enabled(self):
        return self.motors_enabled
    
    def motors_are_homed(self):
        return self.motors_homed

    def connect_balance(self, port):
        self.balance_port = port
        self.balance_connected = True
        self.balance_state_updated.emit(self.balance_connected)

    def disconnect_balance(self):
        self.balance_connected = False
        self.balance_state_updated.emit(self.balance_connected)

    def pause_commands(self):
        self.paused = True
        self.machine_paused.emit()

    def resume_commands(self):
        self.paused = False
        self.machine_paused.emit()

    def clear_command_queue(self):
        self.paused = False
        self.machine_paused.emit()

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
        return round(((float(pressure) - self.psi_offset) / self.fss) * self.psi_max,4)
    
    def convert_to_raw_pressure(self,psi):
        return int((float(psi) / self.psi_max) * self.fss + self.psi_offset)

    def set_step_size(self, new_step_size):
        """Set the step size and emit a signal if it changes."""
        if self.step_size != new_step_size:
            self.step_size = new_step_size
            self.step_num = self.possible_steps.index(new_step_size)
            self.step_size_changed.emit(self.step_size)
            #print(f"Step size set to {self.step_size}")

    def increase_step_size(self):
        """Increase the step size if possible."""
        if self.step_num < len(self.possible_steps) - 1:
            self.step_num += 1
            self.step_size = self.possible_steps[self.step_num]
            self.step_size_changed.emit(self.step_size)
            #print(f"Step size increased to {self.step_size}")

    def decrease_step_size(self):
        """Decrease the step size if possible."""
        if self.step_num > 0:
            self.step_num -= 1
            self.step_size = self.possible_steps[self.step_num]
            self.step_size_changed.emit(self.step_size)
            #print(f"Step size decreased to {self.step_size}")
    
    def toggle_motor_state(self):
        """Toggle the motor state and emit a signal."""
        self.motors_enabled = not self.motors_enabled
        if not self.motors_enabled:
            self.regulating_print_pressure = False
            self.regulating_refuel_pressure = False
            self.regulation_state_changed.emit(self.regulating_print_pressure)
        self.motor_state_changed.emit(self.motors_enabled)
        #print(f"Motors {'enabled' if self.motors_enabled else 'disabled'}")

    def toggle_regulation_state(self):
        """Toggle the motor state and emit a signal."""
        self.regulating_print_pressure = not self.regulating_print_pressure
        self.regulating_refuel_pressure = not self.regulating_refuel_pressure
        self.regulation_state_changed.emit(self.regulating_print_pressure)
        #print(f"Pressure regulation {'enabled' if self.regulating_pressure else 'disabled'}")

    def update_command_numbers(self, current_command_num, last_completed_command_num):
        self.current_command_num = current_command_num
        self.last_completed_command_num = last_completed_command_num
        if self.last_completed_command_num != self.current_command_num:
            self.machine_free = False
            # #print(f"Machine busy. Current command: {self.current_command_num}, Last completed command: {self.last_completed_command_num}")
        else:
            self.machine_free = True
            # #print(f"Machine free. Current command: {self.current_command_num}, Last completed command: {self.last_completed_command_num}")
        self.command_numbers_updated.emit()

    def get_command_numbers(self):
        return self.current_command_num, self.last_completed_command_num
    
    def update_target_position(self, x, y, z):
        self.target_x = int(x)
        self.target_y = int(y)
        self.target_z = int(z)

    def update_target_p_motor(self, p):
        self.target_p = int(p)
    
    def update_target_r_motor(self, r):
        self.target_r = int(r)

    def update_current_position(self, x, y, z):
        self.current_x = int(x)
        self.current_y = int(y)
        self.current_z = int(z)

    def update_current_p_motor(self, p):
        self.current_p = int(p)

    def update_current_r_motor(self, r):
        self.current_r = int(r)
    
    def update_target_print_pressure(self, pressure):
        self.target_print_pressure = self.convert_to_psi(pressure)
        self.printing_parameters_updated.emit()
    
    def update_target_refuel_pressure(self, pressure):
        self.target_refuel_pressure = self.convert_to_psi(pressure)
        self.printing_parameters_updated.emit()

    def update_print_pressure(self, new_pressure):
        """Update the print pressure readings with a new value."""
        # Shift the existing readings and add the new reading
        converted_pressure = self.convert_to_psi(new_pressure)
        self.current_print_pressure = converted_pressure
        self.print_pressure_readings = np.roll(self.print_pressure_readings, -1)
        self.print_pressure_readings[-1] = converted_pressure
        self.pressure_updated.emit()

    def update_refuel_pressure(self,new_pressure):
        """Update the print pressure readings with a new value."""
        # Shift the existing readings and add the new reading
        converted_pressure = self.convert_to_psi(new_pressure)
        self.current_refuel_pressure = converted_pressure
        self.refuel_pressure_readings = np.roll(self.refuel_pressure_readings, -1)
        self.refuel_pressure_readings[-1] = converted_pressure
        self.pressure_updated.emit()

    def get_print_pressure_readings(self):
        return self.print_pressure_readings
    
    def get_refuel_pressure_readings(self):
        return self.refuel_pressure_readings
    
    def update_current_micros(self, micros):
        self.current_micros = micros

    def get_current_print_pressure(self):
        return self.current_print_pressure
    
    def get_current_refuel_pressure(self):
        return self.current_refuel_pressure
    
    def get_target_print_pressure(self):
        return self.target_print_pressure
    
    def get_target_refuel_pressure(self):
        return self.target_refuel_pressure
    
    def get_print_pulse_width(self):
        return self.print_pulse_width

    def get_refuel_pulse_width(self):
        return self.refuel_pulse_width
    
    def get_current_p_motor(self):
        return self.current_p
    
    def get_current_r_motor(self):
        return self.current_r
    
    def update_print_pulse_width(self,pulse_width):
        self.print_pulse_width = int(pulse_width)
        self.printing_parameters_updated.emit()
    
    def update_refuel_pulse_width(self,pulse_width):
        self.refuel_pulse_width = int(pulse_width)
        self.printing_parameters_updated.emit()

    def update_cycle_count(self,cycle_count):
        self.cycle_count = int(cycle_count)

    def update_max_cycle(self,max_cycle):
        self.max_cycle = int(max_cycle)

    def get_current_position(self):
        return [self.current_x, self.current_y, self.current_z]

    def get_current_position_dict(self):
        return {"X": self.current_x, "Y": self.current_y, "Z": self.current_z}

    def get_current_position_dict_capital(self):
        return {"X": self.current_x, "Y": self.current_y, "Z": self.current_z}

    def handle_home_complete(self):
        self.motors_homed = True
        self.current_location = "Home"
        self.home_status_signal.emit()
        print("Motors homed.")

    def reset_home_status(self):
        self.motors_homed = False
        self.current_location = "Unknown"

    def get_current_location(self):
        return self.current_location

    def update_current_location(self, location):
        self.current_location = location

    def is_busy(self):
        return not self.machine_free



class Model(QObject):
    '''
    Model class for the MVC architecture
    '''
    machine_state_updated = Signal()  # Signal to notify the view of state changes
    experiment_loaded = Signal()  # Signal to notify the view of an experiment being loaded

    def __init__(self):
        super().__init__()
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.locations_path = os.path.join(self.script_dir, 'Presets','Locations.json')
        self.plates_path = os.path.join(self.script_dir, 'Presets','Plates.json')
        self.colors_path = os.path.join(self.script_dir, 'Presets','Printer_head_colors.json')
        self.settings_path = os.path.join(self.script_dir, 'Presets','Settings.json')
        self.obstacles_path = os.path.join(self.script_dir, 'Presets','Obstacles.json')
        self.predictive_model_dir = os.path.join(self.script_dir, 'Presets','Predictive_models')
        # self.prediction_model_path = os.path.join(self.script_dir, 'Presets','150um_50per_large_lr_pipeline.pkl')
        # self.resistance_model_path = os.path.join(self.script_dir, 'Presets','150um_50per_large_resistance_pipeline.pkl')
    
        self.printer_head_colors = self.load_colors(self.colors_path)
        self.settings = self.load_settings(self.settings_path)
        self.machine_model = MachineModel()
        self.num_slots = 5
        self.location_data = self.load_all_location_data(self.locations_path)
        self.rack_model = RackModel(self.num_slots,location_data=self.location_data)
        self.location_model = LocationModel(json_file_path=self.locations_path,obstacle_path=self.obstacles_path)
        self.location_model.load_locations()  # Load locations at startup
        self.location_model.load_obstacles()
        self.all_plate_data = self.load_all_plate_data(self.plates_path)
        self.well_plate = WellPlate(self.all_plate_data)
        self.stock_solutions = StockSolutionManager()
        self.reaction_collection = ReactionCollection()
        self.printer_head_manager = PrinterHeadManager(self.printer_head_colors,self.rack_model)
        self.calibration_model = MassCalibrationModel(self.machine_model,self.printer_head_manager,self.rack_model,self.predictive_model_dir)
        self.experiment_model = ExperimentModel(self.well_plate,self.calibration_model)
        self.experiment_file_path = None
        self.refuel_camera_model = RefuelCameraModel()
        self.droplet_camera_model = DropletCameraModel()

        self.well_plate.plate_format_changed_signal.connect(self.update_well_plate)
        self.rack_model.rack_calibration_updated_signal.connect(self.update_rack_calibration)
        self.location_model.current_location_updated.connect(self.machine_model.update_current_location)
        self.droplet_camera_model.record_metadata_signal.connect(self.record_image_metadata)

    def load_colors(self, file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
        
    def load_all_plate_data(self,file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
        
    def load_all_location_data(self,file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
        
    def load_settings(self,file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
        
    def get_default_machine_port(self):
        return self.settings['MACHINE_PORT']
    
    def get_default_balance_port(self):
        return self.settings['BALANCE_PORT']
        
    def update_rack_calibration(self):
        print('\n---Updating rack calibration')
        self.location_model.update_location_coords('rack_position_Left',self.rack_model.get_calibration_by_name('rack_position_Left'))
        self.location_model.update_location_coords('rack_position_Right',self.rack_model.get_calibration_by_name('rack_position_Right'))
        self.location_model.save_locations()

    def update_state(self, status_dict):
        '''
        Update the state of the machine model
        '''
        status_keys = status_dict.keys()
        self.machine_model.update_current_position(status_dict.get('X', self.machine_model.current_x),
                                                   status_dict.get('Y', self.machine_model.current_y),
                                                   status_dict.get('Z', self.machine_model.current_z))
        
        self.machine_model.update_current_p_motor(status_dict.get('P', self.machine_model.current_p))
        self.machine_model.update_current_r_motor(status_dict.get('R', self.machine_model.current_r))   
        self.machine_model.update_target_position(status_dict.get('Tar_X', self.machine_model.target_x),
                                                  status_dict.get('Tar_Y', self.machine_model.target_y),
                                                  status_dict.get('Tar_Z', self.machine_model.target_z))
        self.machine_model.update_target_p_motor(status_dict.get('Tar_P', self.machine_model.target_p))
        self.machine_model.update_target_r_motor(status_dict.get('Tar_R', self.machine_model.target_r))
        if 'Pressure_P' in status_keys:
            self.machine_model.update_print_pressure(status_dict['Pressure_P'])
        if 'Pressure_R' in status_keys:
            self.machine_model.update_refuel_pressure(status_dict['Pressure_R'])
        if 'Tar_print' in status_keys:
            self.machine_model.update_target_print_pressure(status_dict['Tar_print'])
        if 'Tar_refuel' in status_keys:
            self.machine_model.update_target_refuel_pressure(status_dict['Tar_refuel'])
        if 'Cycle_count' in status_keys:
            self.machine_model.update_cycle_count(status_dict['Cycle_count'])
        if 'Max_cycle' in status_keys:
            self.machine_model.update_max_cycle(status_dict['Max_cycle'])
        if 'Print_width' in status_keys:
            self.machine_model.update_print_pulse_width(status_dict['Print_width'])
        if 'Refuel_width' in status_keys:
            self.machine_model.update_refuel_pulse_width(status_dict['Refuel_width'])
        if 'Micros' in status_keys:
            self.machine_model.update_current_micros(status_dict['Micros'])
        if 'Flashes' in status_keys:
            self.droplet_camera_model.update_num_flashes(status_dict['Flashes'])
        if 'Flash_width' in status_keys:
            self.droplet_camera_model.update_flash_duration(status_dict['Flash_width'])
        if 'Flash_delay' in status_keys:
            self.droplet_camera_model.update_flash_delay(status_dict['Flash_delay'])
        if 'Flash_droplets' in status_keys:
            self.droplet_camera_model.update_num_droplets(status_dict['Flash_droplets'])

        self.machine_model.update_command_numbers(status_dict.get('Current_command', self.machine_model.current_command_num),
                                                    status_dict.get('Last_completed', self.machine_model.last_completed_command_num))
        self.machine_state_updated.emit()
    
    def load_reactions_from_csv(self,csv_file_path):
        """
        Load reactions from a CSV file and return a ReactionCollection.
        
        The CSV should have a 'reaction_id' column followed by columns for each reagent with target concentrations.
        """
        df = pd.read_csv(csv_file_path)
        stock_solutions = StockSolutionManager()
        stock_names = [c for c in df.columns if c != 'reaction_id']
        stock_solutions.add_all_stock_solutions(stock_names)
        
        reaction_collection = ReactionCollection()

        for _, row in df.iterrows():
            reaction_name = row['reaction_id']
            reaction = ReactionComposition(reaction_name)

            for stock_id, droplets in row.items():
                if stock_id != 'reaction_id':  # Skip the 'reaction_id' column
                    current_stock = stock_solutions.get_stock_by_id(stock_id)
                    reaction.add_reagent(current_stock, droplets)
            
            reaction_collection.add_reaction(reaction)

        return stock_solutions,reaction_collection
    
    def load_experiment_from_file(self, file_path, plate_name=None):
        """Load an experiment from a CSV file. Remove any existing experiment data."""
        if not file_path.endswith('.csv'):
            raise ValueError("Invalid file format. Please load a CSV file.")
        if len(self.reaction_collection.get_all_reactions()) > 0:
            self.stock_solutions = StockSolutionManager()
            self.reaction_collection = ReactionCollection()
            self.well_plate.clear_all_wells()
        if plate_name is not None:
            self.well_plate.set_plate_format(plate_name)
        self.stock_solutions, self.reaction_collection = self.load_reactions_from_csv(file_path)
        #print(f'Stock Solutions:{self.stock_solutions.get_stock_solution_names()}')
        self.well_plate.assign_reactions_to_wells(self.reaction_collection.get_all_reactions())
        self.assign_printer_heads()
        self.experiment_loaded.emit()
        self.experiment_file_path = file_path

    def load_reactions_from_model(self):
        stock_solutions = StockSolutionManager()
        for stock in self.experiment_model.get_all_stock_solutions():
            stock_solutions.add_stock_solution(stock['reagent_name'],stock['concentration'],stock['units'],required_volume=stock['total_volume'])
        #print(f'All stock solutions:\n{stock_solutions.get_stock_solution_names()}')
        #print(f'Stock formated:\n{stock_solutions.get_stock_solution_names_formated()}')
        reaction_collection = ReactionCollection()
        if self.experiment_model.all_droplet_df.empty:
            print("No reactions in the experiment model.")
            return None, None
        for unique_id, reaction_df in self.experiment_model.all_droplet_df.groupby('unique_id'):
            reaction = ReactionComposition(unique_id)
            for _, row in reaction_df.iterrows():
                #print(f'Row:{row}')
                #print(f'Stock Solution:{row["reagent_name"]},{row["stock_solution"]}')
                current_stock = stock_solutions.get_stock_solution(row['reagent_name'],row['stock_solution'],row['units'])
                reaction.add_reagent(current_stock, row['droplet_count'])
            
            reaction_collection.add_reaction(reaction)
        return stock_solutions,reaction_collection

    def load_experiment_from_model(self,plate_name=None,load_progress=False):
        if self.experiment_model.get_number_of_reactions() == 0:
            print("No reactions in the experiment model.")
            return
        self.clear_experiment()
        if plate_name is not None:
            self.well_plate.set_plate_format(plate_name)
        
        stock_solutions, reaction_collection = self.load_reactions_from_model()
        if stock_solutions is None or reaction_collection is None:
            print("No stock solutions or reactions found in the experiment model.")
            self.clear_experiment()
            return
        self.stock_solutions = stock_solutions
        self.reaction_collection = reaction_collection
        #print(f'Stock Solutions:{self.stock_solutions.get_stock_solution_names()}')
        all_reactions = self.reaction_collection.get_all_reactions()
        random_seed = self.experiment_model.get_random_seed()
        if random_seed is not None:
            random.seed(random_seed)
            random.shuffle(all_reactions)

        start_row = self.experiment_model.get_start_row()
        start_col = self.experiment_model.get_start_col()

        self.well_plate.assign_reactions_to_wells(all_reactions,start_row=start_row,start_col=start_col)
        self.well_plate.apply_calibration_data()
        self.assign_printer_heads()
        self.experiment_model.update_all_paths()
        if load_progress:
            print('Loading progress in load experiment from model')
            self.experiment_model.load_progress()
        else:
            print('Creating new progress file from load experiment from model')
            self.experiment_model.create_progress_file()
        self.experiment_model.create_key_file()
        self.calibration_model.apply_calibrations_to_all_printer_heads()
        self.experiment_loaded.emit()

    def reload_experiment(self, plate_name=None):
        """Reload the experiment from the last loaded file."""
        if self.experiment_file_path is not None:
            self.load_experiment_from_file(self.experiment_file_path,plate_name=plate_name)
        else:
            print("No experiment file path found. Please load an experiment file.")

    def update_well_plate(self):
        if self.reaction_collection is not None:
            start_row = self.experiment_model.get_start_row()
            start_col = self.experiment_model.get_start_col()

            self.well_plate.assign_reactions_to_wells(self.reaction_collection.get_all_reactions(),start_row=start_row,start_col=start_col)
            self.experiment_loaded.emit()
        else:
            print("No experiment data loaded.")

    def clear_experiment(self):
        """Clear all experiment data and reset the well plate."""
        if self.stock_solutions is not None:
            self.stock_solutions.clear_all_stock_solutions()
        if self.reaction_collection is not None:
            self.reaction_collection.clear_all_reactions()
        
        self.well_plate.clear_all_wells()
        self.printer_head_manager.clear_all_printer_heads()
        self.rack_model.clear_all_slots()
        self.experiment_loaded.emit()
        self.printer_head_manager.create_calibration_chip()
        calibration_chip = self.printer_head_manager.get_calibration_chip()
        self.printer_head_manager.swap_printer_head(4,calibration_chip)

    def assign_printer_heads(self):
        """Assign printer heads to the slots in the rack."""
        # Create and assign printer heads for each unique pair
        self.printer_head_manager.create_printer_heads(self.stock_solutions)
        for i in range(self.rack_model.get_num_slots()):
            current_slot = self.rack_model.get_slot_info(i)
            if current_slot['printer_head'] != None:
                if current_slot['printer_head']['reagent'] == 'Calibration':
                    print('Skipping slot:',i)
                    continue
            if not self.printer_head_manager.assign_printer_head_to_slot(i):
                break  # Stop assigning if there are no more unassigned printer heads

    def record_image_metadata(self,timestamp):
        """Record metadata for the droplet images."""
        num_flashes, flash_duration, flash_delay, num_droplets, exposure_time = self.droplet_camera_model.get_image_metadata()
        current_position = self.machine_model.get_current_position_dict()
        print_width = self.machine_model.get_print_pulse_width()
        refuel_width = self.machine_model.get_refuel_pulse_width()
        print_pressure = self.machine_model.get_current_print_pressure()
        refuel_pressure = self.machine_model.get_current_refuel_pressure()

        file_dir = os.path.join(self.droplet_camera_model.image_dir, "metadata.csv")
        # Prepare metadata
        metadata = [
            timestamp,
            flash_duration,
            flash_delay,
            num_droplets,
            exposure_time,
            current_position['X'],
            current_position['Y'],
            current_position['Z'],
            print_width,
            refuel_width,
            print_pressure,
            refuel_pressure,
        ]

        # Save metadata to CSV
        file_exists = os.path.isfile(file_dir)
        with open(file_dir, 'a', newline='') as csv_file:
            writer = csv.writer(csv_file)
            if not file_exists:  # Write header only once
                writer.writerow(["timestamp", "flash_duration", "flash_delay", "num_droplets", "exposure_time", "X_position", "Y_position", "Z_position", "print_pulse_width", "refuel_pulse_width", "print_pressure", "refuel_pressure"])
            writer.writerow(metadata)
        print(f"Metadata saved to {file_dir}")


if __name__ == "__main__":
    model = Model()
    model.load_experiment_from_file('mock_reaction_compositions.csv')
