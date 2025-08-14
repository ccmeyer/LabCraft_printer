import pandas as pd
import numpy as np
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QThread
from PySide6.QtStateMachine import QStateMachine, QState, QFinalState, QSignalTransition
import json
import heapq
import os
import csv
import cv2
import itertools
from collections import Counter
from statistics import median
from itertools import combinations_with_replacement
import joblib
from scipy.optimize import minimize, fsolve
from scipy.signal import find_peaks
from skimage.metrics import structural_similarity as ssim

import random
import pyDOE3
import time
from datetime import datetime
import glob
import shutil
import csv
import math
import matplotlib.pyplot as plt
from enum import Enum

def numpy_encoder(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

class CalibrationManager(QObject):
    # Signal to update the current stage text (used by the view).
    calibrationStageChanged = Signal(str)

    # Signals to indicate overall process completion or failure.
    calibrationCompleted = Signal()
    calibrationError = Signal(str)
    calibrationQueueCompleted = Signal()

    # Signal to update the presented image in the view.
    analyzedImageUpdated = Signal(object)

    # Signals used for calibration actions.
    captureImageRequested = Signal(object)   # expects a callback function
    moveRequested = Signal(object, object)     # expects a move_vector and a callback
    moveAbsoluteRequested = Signal(object, object)  # expects a move_vector with absolute coordinates and a callback
    changeSettingsRequested = Signal(dict, object)  # expects settings and a callback

    # These signals will be used to drive the state machine transitions.
    settingsChangeCompleted = Signal()
    captureCompleted = Signal()
    moveCompleted = Signal()

    position_diff_dict_signal = Signal(dict, dict)
    
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.activeCalibration = None
        self.model = model
        self.data = {}

        # Variables to store calibration data across the process.
        self.background_image = None
        self.nozzle_center = None
        self.nozzle_center_image_position = None
        self.droplet_trajectory_vector = None
        self.min_start_delay = None
        self.intermediate_droplet_position = None

        self.calibration_file_path = None

        # New: a queue to hold calibration process instances.
        self.calibration_queue = []

        self.model.machine_state_updated.connect(self.update_offsets_from_nozzle)

    def create_calibration_file(self, file_path):
        self.calibration_file_path = file_path
        self.remove_all_calibrations()
        with open(file_path, 'w') as file:
            json.dump(self.data, file)

    def update_calibration_file_path(self, file_path):
        self.calibration_file_path = file_path

    def save_calibration_data(self, file_path):
        """Save the calibration data as a JSON file."""
        with open(file_path, 'w') as file:
            json.dump(self.data, file, indent=4, default=numpy_encoder)

    def load_calibration_data(self, file_path):
        """Load the calibration data from a JSON file."""
        self.calibration_file_path = file_path
        with open(file_path, 'r') as file:
            self.data = json.load(file)

    def remove_all_calibrations(self):
        """Removes all measurements."""
        self.data = {}
        if self.calibration_file_path:
            self.save_calibration_data(self.calibration_file_path)

    # --- Methods to start individual calibration processes ---
    def start_nozzle_calibration(self):
        self.activeCalibration = NozzlePositionCalibrationProcess(self, self.model)
        self.start_active_calibration()

    def start_nozzle_focus_calibration(self):
        self.activeCalibration = NozzleFocusCalibrationProcess(self, self.model)
        self.start_active_calibration()

    def start_droplet_emergence_calibration(self):
        self.activeCalibration = DropletEmergenceCalibrationProcess(self, self.model)
        self.start_active_calibration()

    def start_pressure_calibration(self):
        self.activeCalibration = PressureCalibrationProcess(self, self.model)
        self.start_active_calibration()

    def start_trajectory_calibration(self):
        self.activeCalibration = TrajectoryCalibrationProcess(self, self.model)
        self.start_active_calibration()

    def start_droplet_search_calibration(self):
        self.activeCalibration = DropletSearchCalibrationProcess(self, self.model)
        self.start_active_calibration()

    # --- Queue-related methods ---
    def add_all_calibrations_to_queue(self):
        self.add_calibration_to_queue('nozzle_position')
        self.add_calibration_to_queue('nozzle_focus')
        self.add_calibration_to_queue('droplet_emergence')
        self.add_calibration_to_queue('pressure')
        self.add_calibration_to_queue('trajectory')
        self.add_calibration_to_queue('droplet_search')

        self.start_calibration_queue()

    def add_calibration_to_queue(self, calibration_name):
        """Add a calibration process instance to the queue."""
        self.calibration_queue.append(calibration_name)

    def add_calibration_queue(self, calibration_list):
        """Add a list of calibration process names to the queue."""
        self.calibration_queue.extend(calibration_list)

    def clear_calibration_queue(self):
        """Clear the calibration queue."""
        self.calibration_queue = []

    def start_calibration_queue(self):
        """Start processing the queue sequentially."""
        if len(self.calibration_queue) > 0:
            next_calibration = self.calibration_queue.pop(0)
            if next_calibration == 'nozzle_position':
                self.activeCalibration = NozzlePositionCalibrationProcess(self, self.model)
            elif next_calibration == 'nozzle_focus':
                self.activeCalibration = NozzleFocusCalibrationProcess(self, self.model)
            elif next_calibration == 'droplet_emergence':
                self.activeCalibration = DropletEmergenceCalibrationProcess(self, self.model)
            elif next_calibration == 'pressure':
                self.activeCalibration = PressureCalibrationProcess(self, self.model)
            elif next_calibration == 'trajectory':
                self.activeCalibration = TrajectoryCalibrationProcess(self, self.model)
            elif next_calibration == 'droplet_search':
                self.activeCalibration = DropletSearchCalibrationProcess(self, self.model)
            self.start_active_calibration()
        else:
            self.calibrationStageChanged.emit("No calibrations in queue.")
            self.calibrationQueueCompleted.emit()

    # --- Start active calibration (used by individual start functions and queue processing) ---
    def start_active_calibration(self):
        if self.activeCalibration is not None:
            self.activeCalibration.stageChanged.connect(self.calibrationStageChanged)
            self.activeCalibration.calibrationCompleted.connect(self.onCalibrationCompleted)
            self.activeCalibration.calibrationError.connect(self.onCalibrationError)
            self.activeCalibration.calibrationDataUpdated.connect(self.onCalibrationDataUpdated)
            self.activeCalibration.presentImageSignal.connect(self.onPresentImage)
            self.activeCalibration.start()

    def stop(self):
        if self.activeCalibration is not None:
            self.activeCalibration.stop()
            self.activeCalibration = None
        if len(self.calibration_queue) > 0:
            self.clear_calibration_queue()
        self.calibrationStageChanged.emit("Calibration stopped")
        self.calibrationError.emit("Calibration terminated by user")

    def get_current_settings(self):
        num_flashes, flash_duration, flash_delay, num_droplets, exposure_time = self.model.droplet_camera_model.get_image_metadata()
        current_position = self.model.machine_model.get_current_position_dict()
        print_width = self.model.machine_model.get_print_pulse_width()
        refuel_width = self.model.machine_model.get_refuel_pulse_width()
        print_pressure = self.model.machine_model.get_current_print_pressure()
        refuel_pressure = self.model.machine_model.get_current_refuel_pressure()
        return {
            "num_flashes": num_flashes,
            "flash_duration": flash_duration,
            "flash_delay": flash_delay,
            "num_droplets": num_droplets,
            "exposure_time": exposure_time,
            "current_position": current_position,
            "print_width": print_width,
            "refuel_width": refuel_width,
            "print_pressure": print_pressure,
            "refuel_pressure": refuel_pressure
        }

    # Methods to retrieve calibration data.
    def get_centered_nozzle_position(self):
        if "nozzle_position" in self.data:
            position_data = self.data["nozzle_position"]
            return position_data[-1]["result"]
        else:
            print("No nozzle position calibration available")
            return None
        
    def get_emergence_time(self):
        if "droplet_emergence" in self.data:
            emergence_data = self.data["droplet_emergence"]
            return emergence_data[-1]["result"]["flash_delay"]
        else:
            print("No droplet emergence calibration available")
            return None
        
    def is_in_initial_position(self):
        if "pressure_calibration" in self.data:
            return True
        else:
            print("Not in initial position")
            return False
        
    def set_background_image(self, background):
        self.background_image = background

    def set_nozzle_center(self, center):
        self.nozzle_center = center

    def set_nozzle_center_image_position(self, center):
        self.nozzle_center_image_position = center

    def set_trajectory_vector(self, vector):
        self.droplet_trajectory_vector = vector

    def set_min_start_delay(self, delay):
        self.min_start_delay = delay

    def set_intermediate_droplet_position(self, position):
        self.intermediate_droplet_position = position

    def get_background_image(self):
        return self.background_image
    
    def get_nozzle_center(self):
        return self.nozzle_center
    
    def get_nozzle_center_image_position(self):
        return self.nozzle_center_image_position

    def get_trajectory_vector(self):
        return self.droplet_trajectory_vector

    def get_min_start_delay(self):
        return self.min_start_delay

    def get_intermediate_droplet_position(self):
        return self.intermediate_droplet_position

    def update_offsets_from_nozzle(self):
        current_dict = self.model.machine_model.get_current_position_dict()
        diff_dict = current_dict.copy()
        if self.nozzle_center is not None:
            for key in diff_dict:
                diff_dict[key] -= self.nozzle_center[key]
        else:
            for key in diff_dict:
                diff_dict[key] = 0
        
        self.position_diff_dict_signal.emit(current_dict, diff_dict)

    # Helper methods for callbacks in QStateMachine transitions.
    @Slot()
    def emitSettingsChangeCompleted(self):
        self.settingsChangeCompleted.emit()

    @Slot()
    def emitCaptureCompleted(self):
        self.captureCompleted.emit()

    @Slot()
    def emitMoveCompleted(self):
        self.moveCompleted.emit()
        print('Emit Move completed called')

    # Slots to handle calibration completion or error.
    @Slot()
    def onCalibrationCompleted(self):
        self.calibrationStageChanged.emit("Calibration completed successfully")
        self.activeCalibration = None
        self.calibrationCompleted.emit()
        # If there are more calibrations in the queue, start the next one.
        if len(self.calibration_queue) > 0:
            self.calibrationStageChanged.emit("Starting next calibration in queue...")
            self.start_calibration_queue()
        else:
            self.calibrationQueueCompleted.emit()

    @Slot(str)
    def onCalibrationError(self, error_message):
        self.calibrationStageChanged.emit("Calibration error: " + error_message)
        self.activeCalibration = None
        self.calibrationError.emit(error_message)
        # Stop the queue on error.
        if len(self.calibration_queue) > 0:
            self.calibrationStageChanged.emit("Calibration queue stopped due to error")
            self.clear_calibration_queue()

    @Slot(dict)
    def onCalibrationDataUpdated(self, data):
        phase = self.activeCalibration.phase_name
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data["timestamp"] = timestamp
        settings = self.get_current_settings()
        data["settings"] = settings
        if phase in self.data:
            self.data[phase].append(data)
        else:
            self.data[phase] = [data]
        if self.calibration_file_path:
            self.save_calibration_data(self.calibration_file_path)

    @Slot(object)
    def onPresentImage(self, image):
        self.analyzedImageUpdated.emit(image)

class BaseCalibrationProcess(QObject):
    # Signal to update the current stage text.
    stageChanged = Signal(str)

    # Signals to indicate overall process completion or failure.
    calibrationCompleted = Signal()
    calibrationError = Signal(str)

    calibrationDataUpdated = Signal(dict)

    # Signal to update the presented image in the view.
    presentImageSignal = Signal(object)

    def __init__(self, calibration_manager, model, parent=None):
        """
        calibration_manager: Reference to the CalibrationManager (providing action signals)
        model: Provides methods like image analysis and stage conversion.
        """
        super().__init__(parent)
        self.calibration_manager = calibration_manager
        self.model = model
        # The state machine will govern the asynchronous flow.
        self.state_machine = QStateMachine(self)
        self.phase_name = None
        self._active_timers = set()

    def start(self):
        """Start the calibration process by starting the state machine."""
        self.state_machine.start()

    def stop(self):
        """Stop the state machine if needed."""
        # Cancel all active timers.
        for t in list(self._active_timers):
            try:
                t.stop()
                t.deleteLater()
            except Exception:
                pass
            finally:
                self._active_timers.discard(t)
        self.state_machine.stop()
        self.stageChanged.emit("Calibration stopped")

    def onCalibrationCompleted(self):
        """Emit the completion signal."""
        self.calibrationCompleted.emit()

    # ---------- timeouts ----------
    def _start_timeout(self, msec, *, err_msg=None, on_timeout=None, name=None):
        """
        Start a one-shot timeout. If it fires, either call `on_timeout()` or emit calibrationError(err_msg).
        Returns the QTimer so you can cancel it when the awaited event arrives.
        """
        t = QTimer(self)
        t.setSingleShot(True)

        def _fire():
            # auto-remove from tracking
            try:
                self._active_timers.discard(t)
            except Exception:
                pass
            if on_timeout is not None:
                on_timeout()
            elif err_msg:
                self.calibrationError.emit(err_msg)

        t.timeout.connect(_fire)
        t.start(int(msec))
        self._active_timers.add(t)
        return t

    def _cancel_timeout(self, timer):
        """Stop and dispose a timer started by _start_timeout."""
        if timer is None:
            return
        try:
            timer.stop()
            timer.deleteLater()
        finally:
            self._active_timers.discard(timer)

class NozzlePositionCalibrationProcess(BaseCalibrationProcess):
    # Define signals to trigger transitions from analyze state.
    nozzleCentered = Signal()

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)

        self.phase_name = "nozzle_position"
        self.measurements = []  # Store (X, Y, Z) coordinates of machine and corresponding center XY positions in image.
        # Store captured images locally.
        self.background_image = None
        self.droplet_image = None

        # Define states
        self.state_initial_position = QState()
        self.state_prepare_background = QState()
        self.state_capture_background = QState()
        self.state_prepare_droplet = QState()
        self.state_capture_droplet = QState()
        self.state_analyze = QState()
        self.state_final = QFinalState()

        # Connect on-entry actions
        self.state_initial_position.entered.connect(self.onInitialPosition)
        self.state_prepare_background.entered.connect(self.onPrepareBackground)
        self.state_capture_background.entered.connect(self.onCaptureBackground)
        self.state_prepare_droplet.entered.connect(self.onPrepareDroplet)
        self.state_capture_droplet.entered.connect(self.onCaptureDroplet)
        self.state_analyze.entered.connect(self.onAnalyze)
        self.state_final.entered.connect(self.onCalibrationCompleted)

        # Create transitions using QSignalTransition:

        # Transition: Move to initial position -> prepare_background
        t0 = QSignalTransition()
        t0.setSenderObject(self.calibration_manager)
        t0.setSignal(b"2moveCompleted()")  # Use the normalized signature here.
        t0.setTargetState(self.state_prepare_background)
        self.state_initial_position.addTransition(t0)

        # Transition: prepare_background -> capture_background
        t1 = QSignalTransition() 
        t1.setSenderObject(self.calibration_manager)
        t1.setSignal(b"2settingsChangeCompleted()")  # Use the normalized signature here.
        t1.setTargetState(self.state_capture_background)
        self.state_prepare_background.addTransition(t1)

        # Transition: capture_background -> prepare_droplet (when background capture is complete)
        t2 = QSignalTransition()
        t2.setSenderObject(self.calibration_manager)
        t2.setSignal(b"2captureCompleted()")  # Use the normalized signature here.
        t2.setTargetState(self.state_prepare_droplet)
        self.state_capture_background.addTransition(t2)

        # Transition: prepare_droplet -> capture_droplet
        t3 = QSignalTransition()
        t3.setSenderObject(self.calibration_manager)
        t3.setSignal(b"2settingsChangeCompleted()")  # Use the normalized signature here.
        t3.setTargetState(self.state_capture_droplet)
        self.state_prepare_droplet.addTransition(t3)

        # Transition: capture_droplet -> analyze
        t4 = QSignalTransition()
        t4.setSenderObject(self.calibration_manager)
        t4.setSignal(b"2captureCompleted()")  # Use the normalized signature here.
        t4.setTargetState(self.state_analyze)
        self.state_capture_droplet.addTransition(t4)

        # In the analyze state we decide whether to move or finish:
        # If nozzle is centered:
        t5 = QSignalTransition()
        t5.setSenderObject(self)
        t5.setSignal(b"2nozzleCentered()")  # Use the normalized signature here.
        t5.setTargetState(self.state_final)
        self.state_analyze.addTransition(t5)
        # If nozzle is off-center, we need to move:
        # After moving, restart the process (or re-check alignment)
        t6 = QSignalTransition()
        t6.setSenderObject(self.calibration_manager)
        t6.setSignal(b"2moveCompleted()")  # Use the normalized signature here.
        t6.setTargetState(self.state_prepare_background)
        self.state_analyze.addTransition(t6)

        # Add states to the state machine
        self.state_machine.addState(self.state_initial_position)
        self.state_machine.addState(self.state_prepare_background)
        self.state_machine.addState(self.state_capture_background)
        self.state_machine.addState(self.state_prepare_droplet)
        self.state_machine.addState(self.state_capture_droplet)
        self.state_machine.addState(self.state_analyze)
        self.state_machine.addState(self.state_final)

        # Set the initial state
        self.state_machine.setInitialState(self.state_initial_position)

    @Slot()
    def onInitialPosition(self):
        self.stageChanged.emit("Moving to initial position")
        # Get the location of the camera in the location model
        initial_position = self.model.location_model.get_location_dict('camera')
        move_vector = (initial_position['X'], initial_position['Y'], initial_position['Z'])
        print(f"Moving to initial position: {move_vector}")
        self.calibration_manager.moveAbsoluteRequested.emit(move_vector, self.calibration_manager.emitMoveCompleted)


    @Slot()
    def onPrepareBackground(self):
        self.stageChanged.emit("Preparing background (0 droplets)")
        # Request to change droplet settings (0 droplets). The callback emits a signal.
        settings = {
            "num_droplets": 0,
            "flash_delay": 3800
        }
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureBackground(self):
        self.stageChanged.emit("Capturing background image")
        # Request a background capture. Use a calibration process callback to store the image.
        self.calibration_manager.captureImageRequested.emit(self.handleBackgroundCaptured)

    @Slot()
    def onPrepareDroplet(self):
        self.stageChanged.emit("Preparing droplet image (1 droplet)")
        # Request to change droplet settings (1 droplet). The callback emits a signal.
        settings = {
            "num_droplets": 1,
        }
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureDroplet(self):
        self.stageChanged.emit("Capturing droplet image")
        # Start a 10-second guard for capture
        self._cap_timeout = self._start_timeout(
            10_000,
            err_msg="Droplet capture timed out"
        )
        # Request a droplet capture. Use a callback that stores the droplet image.
        self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)

    @Slot()
    def onAnalyze(self):
        self.stageChanged.emit("Analyzing images")
        # Use the locally stored images.
        bg = self.background_image
        dr = self.droplet_image
        center, focus, image = self.model.droplet_camera_model.identify_nozzle(bg, dr)
        print(f'Identified nozzle at: {center}, focus: {focus}')
        if center is None:
            self.stageChanged.emit("No nozzle found, restarting")
            # Restart process by emitting the droplet change completed signal.
            # self.calibration_manager.emitDropletChangeCompleted()
            self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)
        else:
            machine_position = self.model.machine_model.get_current_position_dict()
            self.measurements.append((machine_position, center))
            if not self.isCentered(center):
                img_width, img_height = self.model.droplet_camera_model.get_image_size()
                target = (img_width // 2, img_height // 2)
                move_vector = self.model.droplet_camera_model.calculate_move_to_target(center,target)
                self.stageChanged.emit("Nozzle off-center; moving machine")
                self.calibration_manager.moveRequested.emit(move_vector, self.calibration_manager.emitMoveCompleted)
                print('Move requested')
            else:
                self.stageChanged.emit("Nozzle centered")
                self.presentImageSignal.emit(image)
                self.calibrationDataUpdated.emit({'measurements': self.measurements, 'result': {'center': center, 'machine_position': machine_position}})
                self.nozzleCentered.emit()

    def isCentered(self, center):
        img_width, img_height = self.model.droplet_camera_model.get_image_size()
        ideal_center = (img_width // 2, img_height // 2)
        tolerance = 0.01
        return (abs(center[0] - ideal_center[0]) <= tolerance * img_width and
                abs(center[1] - ideal_center[1]) <= tolerance * img_height)

    def onCalibrationCompleted(self):
        """Emit the completion signal."""
        self.calibration_manager.set_nozzle_center(self.measurements[-1][0])
        self.calibrationCompleted.emit()

    # Callbacks to store images in the calibration process
    def handleBackgroundCaptured(self, image):
        self.background_image = image
        self.calibration_manager.emitCaptureCompleted()

    def handleDropletCaptured(self, image):
        self.droplet_image = image

        # cancel the guard
        self._cancel_timeout(self._cap_timeout)
        self._cap_timeout = None

        self.calibration_manager.emitCaptureCompleted()

class NozzleFocusCalibrationProcess(BaseCalibrationProcess):
    nozzleFocused = Signal()

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)

        self.phase_name = "nozzle_focus"

        # List to store (focus, X position) measurements.
        self.focus_values = []   
        self.droplet_image = None
        self.direction = 1            # +1 or -1 indicating movement direction.
        self.initial_step_size = 4    # Initial step size.
        self.step_size = self.initial_step_size # Current step size.
        self.noise_threshold = 500000 # Minimum focus difference to consider significant.
        self.baseline_focus = 1e6     # Minimum focus value to consider in focus.
        self.min_step_size = 1        # Minimum allowed step size.
        self.max_step_size = 12           # Maximum number of steps to take.
        self.best_focus = None        # Best (maximum) focus seen so far.
        self.best_Y = None            # X position corresponding to the best focus.
        self.in_fine_search = False   # Flag to indicate fine search mode.
        
        self.final_nozzle_position = None   # Store the final nozzle position.

        self.timeout_counter = 0              # Number of steps taken so far.   
        self.max_timeout = 5       # Maximum number of steps before quitting the calibration.
        
        # Define states.
        self.state_capture_droplet = QState()
        self.state_analyze = QState()
        self.state_final = QFinalState()

        # Connect on-entry actions.
        self.state_capture_droplet.entered.connect(self.onCaptureDroplet)
        self.state_analyze.entered.connect(self.onAnalyze)
        self.state_final.entered.connect(self.onCalibrationCompleted)

        # Transition from capture to analyze:
        t1 = QSignalTransition()
        t1.setSenderObject(self.calibration_manager)
        t1.setSignal(b"2captureCompleted()")
        t1.setTargetState(self.state_analyze)
        self.state_capture_droplet.addTransition(t1)

        # Transition in analyze: if focused, go to final state.
        t2 = QSignalTransition()
        t2.setSenderObject(self)
        t2.setSignal(b"2nozzleFocused()")
        t2.setTargetState(self.state_final)
        self.state_analyze.addTransition(t2)
        # Otherwise, after a move, loop back to capture.
        t3 = QSignalTransition()
        t3.setSenderObject(self.calibration_manager)
        t3.setSignal(b"2moveCompleted()")
        t3.setTargetState(self.state_capture_droplet)
        self.state_analyze.addTransition(t3)

        # Add states to the state machine.
        self.state_machine.addState(self.state_capture_droplet)
        self.state_machine.addState(self.state_analyze)
        self.state_machine.addState(self.state_final)
        self.state_machine.setInitialState(self.state_capture_droplet)

    @Slot()
    def onCaptureDroplet(self):
        self.stageChanged.emit("Capturing droplet image")
        # Request a capture; when complete, handleDropletCaptured will be called.
        self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)

    @Slot()
    def onAnalyze(self):
        self.stageChanged.emit("Analyzing image")
        img = self.droplet_image
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        focus = self.model.droplet_camera_model.compute_tenengrad_variance(gray)
        if focus is None:
            if self.timeout_counter >= self.max_timeout:
                self.stageChanged.emit("No droplet found, calibration failed")
                self.calibration_manager.emitCaptureCompleted()
            self.stageChanged.emit("No droplet found, restarting capture")
            self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)
            self.timeout_counter += 1
            return

        # Get current position (assuming movement along the X-axis for focus).
        X_pos, Y_pos, Z_pos = self.model.machine_model.get_current_position()
        # Store this measurement.
        self.focus_values.append((focus, Y_pos))
        print(f'Focus: {focus:.2f} at Y: {Y_pos}')

        self.stageChanged.emit(f"Focus: {focus:.2f} at Y: {Y_pos}")

        # Update best focus if this is the highest seen so far.
        if self.best_focus is None or focus > self.best_focus:
            self.best_focus = focus
            self.best_Y = Y_pos

        # If only one measurement exists, take an initial step in the current direction.
        if len(self.focus_values) == 1:
            move_vector = (0, self.direction * self.step_size, 0)
            self.calibration_manager.moveRequested.emit(move_vector, self.calibration_manager.emitMoveCompleted)
            return

        # Compare the current focus with the previous measurement.
        prev_focus, prev_Y = self.focus_values[-2]
        delta = focus - prev_focus

        if len(self.focus_values) == 2:
            # If the focus has improved, continue in the same direction.
            if delta > 0:
                move_vector = (0, self.direction * self.step_size, 0)
                self.calibration_manager.moveRequested.emit(move_vector, self.calibration_manager.emitMoveCompleted)
            # If the focus has decreased, reverse direction and move.
            else:
                self.direction = -self.direction
                move_vector = (0, self.direction * self.step_size, 0)
                self.calibration_manager.moveRequested.emit(move_vector, self.calibration_manager.emitMoveCompleted)
            return
        # If the current focus is lower than the best focus (by more than the noise threshold),
        # then we've passed the peak.
        if focus < self.best_focus - self.noise_threshold:
            move_vector = (0, self.best_Y - Y_pos, 0)
            self.stageChanged.emit("Peak reached; moving to best focus position")
            self.calibration_manager.moveRequested.emit(move_vector, self.calibration_manager.emitMoveCompleted)
            self.calibrationDataUpdated.emit({'measurements': self.focus_values, 'result': {'best_focus': self.best_focus, 'best_Y': self.best_Y}})
            self.final_nozzle_position = {"X": X_pos, "Y": self.best_Y, "Z": Z_pos}
            self.nozzleFocused.emit()
            return

        # Otherwise, if the improvement from the previous step is marginal, increase step size.
        if abs(delta) < self.noise_threshold:
            self.step_size = min(self.step_size * 2, self.max_step_size)
            self.stageChanged.emit("Small improvement; increasing step size")
        else:
            self.step_size = self.initial_step_size
            self.stageChanged.emit("Focus improved; continuing in same direction")

        # Continue moving in the same direction.
        move_vector = (0, self.direction * self.step_size, 0)
        self.calibration_manager.moveRequested.emit(move_vector, self.calibration_manager.emitMoveCompleted)

    def handleDropletCaptured(self, image):
        self.droplet_image = image
        self.calibration_manager.emitCaptureCompleted()
    
    def onCalibrationCompleted(self):
        """Emit the completion signal."""
        self.calibration_manager.set_nozzle_center(self.final_nozzle_position)
        self.calibrationCompleted.emit()

class DropletEmergenceCalibrationProcess(BaseCalibrationProcess):
    # Custom signals for state transitions.
    continueSearch = Signal()
    dropletDetected = Signal()

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)
        self.phase_name = "droplet_emergence"
        
        # Set initial binary search bounds for the flash delay (in microseconds, for example).
        self.lower_delay = 2000
        self.upper_delay = 5000  # Adjust as appropriate.
        self.candidate_delay = 3000  # Initial guess.
        
        # Store the background image (captured once) and the droplet image.
        self.background_image = None
        self.droplet_image = None
        
        # Target contour area range.
        self.min_area = 1000
        self.max_area = 2000

        # Store all measurements, includes the delay and the computed area.
        self.measurements = []

        # Define states.
        self.state_prepare_background = QState()
        self.state_capture_background = QState()
        self.state_set_delay = QState()
        self.state_capture_droplet = QState()
        self.state_analyze = QState()
        self.state_final = QFinalState()

        # Connect on-entry actions.
        self.state_prepare_background.entered.connect(self.onPrepareBackground)
        self.state_capture_background.entered.connect(self.onCaptureBackground)
        self.state_set_delay.entered.connect(self.onSetDelay)
        self.state_capture_droplet.entered.connect(self.onCaptureDroplet)
        self.state_analyze.entered.connect(self.onAnalyze)
        self.state_final.entered.connect(self.onCalibrationCompleted)

        # Transitions:

        # 0. Prepare background -> capture background.
        t0 = QSignalTransition()
        t0.setSenderObject(self.calibration_manager)
        t0.setSignal(b"2settingsChangeCompleted()")
        t0.setTargetState(self.state_capture_background)
        self.state_prepare_background.addTransition(t0)

        # 1. After capturing the background, transition to set_delay.
        t1 = QSignalTransition()
        t1.setSenderObject(self.calibration_manager)
        t1.setSignal(b"2captureCompleted()")  # from background capture.
        t1.setTargetState(self.state_set_delay)
        self.state_capture_background.addTransition(t1)
        
        # 2. After setting the flash delay, transition to capture droplet.
        t2 = QSignalTransition()
        t2.setSenderObject(self.calibration_manager)
        t2.setSignal(b"2settingsChangeCompleted()")  # assume calibration_manager emits this after setting delay.
        t2.setTargetState(self.state_capture_droplet)
        self.state_set_delay.addTransition(t2)
        
        # 3. After capturing the droplet image, transition to analyze.
        t3 = QSignalTransition()
        t3.setSenderObject(self.calibration_manager)
        t3.setSignal(b"2captureCompleted()")
        t3.setTargetState(self.state_analyze)
        self.state_capture_droplet.addTransition(t3)
        
        # 4a. In analyze, if the computed area is within the target range, signal success.
        t4 = QSignalTransition()
        t4.setSenderObject(self)
        t4.setSignal(b"2dropletDetected()")
        t4.setTargetState(self.state_final)
        self.state_analyze.addTransition(t4)
        
        # 4b. Otherwise, signal to continue the binary search.
        t5 = QSignalTransition()
        t5.setSenderObject(self)
        t5.setSignal(b"2continueSearch()")
        t5.setTargetState(self.state_set_delay)
        self.state_analyze.addTransition(t5)
        
        # Add states to the state machine.
        self.state_machine.addState(self.state_prepare_background)
        self.state_machine.addState(self.state_capture_background)
        self.state_machine.addState(self.state_set_delay)
        self.state_machine.addState(self.state_capture_droplet)
        self.state_machine.addState(self.state_analyze)
        self.state_machine.addState(self.state_final)
        
        # Set the initial state.
        self.state_machine.setInitialState(self.state_prepare_background)

    @Slot()
    def onPrepareBackground(self):
        self.stageChanged.emit("Preparing background image")
        # Request to change droplet settings (0 droplets).
        settings = {
            "num_droplets": 0,
        }
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureBackground(self):
        self.stageChanged.emit("Capturing background image")
        # Capture the background image.
        self.calibration_manager.captureImageRequested.emit(self.handleBackgroundCaptured)

    @Slot()
    def onSetDelay(self):
        self.stageChanged.emit(f"Setting flash delay to {self.candidate_delay} μs")
        # Request to set the flash delay to candidate_delay.
        settings = {
            "flash_delay": self.candidate_delay,
            "num_droplets": 1
        }
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureDroplet(self):
        self.stageChanged.emit("Capturing droplet image")
        self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)

    @Slot()
    def onAnalyze(self):
        self.stageChanged.emit("Analyzing droplet image")
        # Compute the bounding rectangle area from the difference image.
        area, center, image = self.model.droplet_camera_model.calc_bounding_rect_area(self.background_image, self.droplet_image)
        print(f"Computed area: {area}, center: {center}")
        self.stageChanged.emit(f"Rectangle area: {area}")
        self.measurements.append((self.candidate_delay, area))
        
        # If the area is within target range, we consider it a success.
        if area is not None and self.min_area <= area <= self.max_area:
            self.stageChanged.emit("Target area reached")
            self.presentImageSignal.emit(image)

            machine_position = self.model.machine_model.get_current_position_dict()
            nozzle_machine_position = self.model.droplet_camera_model.convert_pixel_position_to_motor_steps(center, machine_position)

            self.calibration_manager.set_nozzle_center(nozzle_machine_position)
            self.calibrationDataUpdated.emit({'measurements': self.measurements, 'result': {'area': area, 'flash_delay': self.candidate_delay}})
            self.emitDropletDetected()
        else:
            # Update the binary search bounds:
            if area is None or area < self.min_area:
                # Too little area: droplet hasn't begun emerging.
                self.lower_delay = self.candidate_delay
            else:
                # Too much area: droplet is too advanced.
                self.upper_delay = self.candidate_delay
            # Compute new candidate.
            # new_candidate = int((self.lower_delay + self.upper_delay) / 2)
            new_candidate = (self.lower_delay + self.upper_delay)//2
            if new_candidate == self.candidate_delay or self.upper_delay - self.lower_delay < 50:
                self.calibrationError.emit("Emergence binary search stalled")
                return
            self.stageChanged.emit(f"Adjusting flash delay from {self.candidate_delay} to {new_candidate}")
            self.candidate_delay = new_candidate
            self.emitContinueSearch()

    @Slot()
    def onCalibrationCompleted(self):
        self.stageChanged.emit("Droplet emergence calibration complete")
        self.calibrationCompleted.emit()

    def handleBackgroundCaptured(self, image):
        self.background_image = image
        self.calibration_manager.emitCaptureCompleted()

    def handleDropletCaptured(self, image):
        self.droplet_image = image
        self.calibration_manager.emitCaptureCompleted()

    def emitContinueSearch(self):
        # Emit the custom signal to trigger the transition.
        self.continueSearch.emit()

    def emitDropletDetected(self):
        self.dropletDetected.emit()

class PressureCalibrationProcess(BaseCalibrationProcess):
    """
    A calibration process to identify the highest pressure that yields a single droplet
    (with a small nozzle droplet area) at a fixed pulse width. Instead of a pure binary
    search, this process mimics a manual calibration: it increases pressure in large
    steps (coarse search) until the droplet condition becomes unacceptable, then switches
    to a fine search (small steps) to home in on the optimum pressure.
    """
    # Custom signals for state transitions.
    continueSearch = Signal()
    nozzleDetected = Signal()
    dropletDetected = Signal()
    replicateContinue = Signal()  # loop Analyze -> Capture for more replicates

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)
        self.phase_name = "pressure_calibration"

        self.nozzle_position = None
        self.start_delay = None
        self.start_delay_offset =  max(self.model.machine_model.get_print_pulse_width() + 1000, 0)

        # Set initial binary search bounds for pressure (in psi, for example).
        self.lower_pressure = 0.4   # example minimum pressure
        self.upper_pressure = 0.8   # example maximum pressure
        # Start with a candidate near the lower bound.
        self.candidate_pressure = self.model.machine_model.get_current_print_pressure()
        
        # --- bracketed search state ---
        self.bracket_lo = None   # highest pressure confirmed ACCEPTABLE
        self.bracket_hi = None   # lowest pressure confirmed TOO_HIGH
        self.phase = "bracket"   # "bracket" -> "refine"

        # remember most recent “too low” and most recent “one drop”
        self.last_too_low_pressure = None
        self.last_one_pressure     = None

        # --- Replicates per pressure ---
        self.replicates_per_pressure = 3     # tune: 2–5 usually good
        self._rep_results = []               # [(droplet_count, nozzle_area), ...]
        self._rep_captured = 0               # how many taken at current pressure

        # Convergence threshold for binary search (if needed).
        self.pressure_threshold = 0.01  # stop when hi-lo <= this
        self.hysteresis_frac = 0.10

        # New variables for two-phase search.
        self.coarse_search = True
        self.coarse_step = 0.1
        self.fine_step = 0.02
        self.last_acceptable_pressure = None
        self.transition_found = False
        self.direction = 1  # 1 for increasing pressure, -1 for decreasing.
        # We'll consider the droplet acceptable only if exactly 1 droplet is seen and its area is below this threshold.
        self.nozzle_droplet_threshold = 8000

        # Store images.
        self.background_image = None
        self.droplet_image = None

        # Measurements: list of tuples (pressure, droplet_count, nozzle_area).
        self.measurements = []

        self.counter = 0
        self.max_iterations = 20
        self.final_condition_found = False

        # Define states.
        self.state_initial_position = QState()
        self.state_prepare_background = QState()
        self.state_capture_background = QState()
        self.state_set_delay = QState()
        self.state_capture_nozzle = QState()
        self.state_analyze_nozzle = QState()
        self.state_set_pressure = QState()
        self.state_capture_droplet = QState()
        self.state_analyze = QState()
        self.state_final = QFinalState()

        # Connect on-entry actions.
        self.state_initial_position.entered.connect(self.onInitialPosition)
        self.state_prepare_background.entered.connect(self.onPrepareBackground)
        self.state_capture_background.entered.connect(self.onCaptureBackground)
        self.state_set_delay.entered.connect(self.onSetDelay)
        self.state_capture_nozzle.entered.connect(self.onCaptureNozzle)
        self.state_analyze_nozzle.entered.connect(self.onAnalyzeNozzle)
        self.state_set_pressure.entered.connect(self.onSetPressure)
        self.state_capture_droplet.entered.connect(self.onCaptureDroplet)
        self.state_analyze.entered.connect(self.onAnalyze)
        self.state_final.entered.connect(self.onCalibrationCompleted)

        # Create transitions.
        # Transition: Initial position -> prepare background.
        t0 = QSignalTransition()
        t0.setSenderObject(self.calibration_manager)
        t0.setSignal(b"2moveCompleted()")
        t0.setTargetState(self.state_prepare_background)
        self.state_initial_position.addTransition(t0)

        # Transition: Prepare background -> capture background.
        t1 = QSignalTransition()
        t1.setSenderObject(self.calibration_manager)
        t1.setSignal(b"2settingsChangeCompleted()")
        t1.setTargetState(self.state_capture_background)
        self.state_prepare_background.addTransition(t1)

        # Transition: Capture background -> set delay.
        t2 = QSignalTransition()
        t2.setSenderObject(self.calibration_manager)
        t2.setSignal(b"2captureCompleted()")
        t2.setTargetState(self.state_set_delay)
        self.state_capture_background.addTransition(t2)

        # Transition: Set delay -> capture nozzle.
        t3 = QSignalTransition()
        t3.setSenderObject(self.calibration_manager)
        t3.setSignal(b"2settingsChangeCompleted()")
        t3.setTargetState(self.state_capture_nozzle)
        self.state_set_delay.addTransition(t3)

        # Transition: Capture nozzle -> analyze nozzle.
        t4 = QSignalTransition()
        t4.setSenderObject(self.calibration_manager)
        t4.setSignal(b"2captureCompleted()")
        t4.setTargetState(self.state_analyze_nozzle)
        self.state_capture_nozzle.addTransition(t4)

        # Transition: Analyze nozzle -> set pressure.
        t5 = QSignalTransition()
        t5.setSenderObject(self)
        t5.setSignal(b"2nozzleDetected()")
        t5.setTargetState(self.state_set_pressure)
        self.state_analyze_nozzle.addTransition(t5)

        # Transition: Set pressure -> capture droplet.
        t6 = QSignalTransition()
        t6.setSenderObject(self.calibration_manager)
        t6.setSignal(b"2settingsChangeCompleted()")
        t6.setTargetState(self.state_capture_droplet)
        self.state_set_pressure.addTransition(t6)

        # Transition: Capture droplet -> analyze.
        t7 = QSignalTransition()
        t7.setSenderObject(self.calibration_manager)
        t7.setSignal(b"2captureCompleted()")
        t7.setTargetState(self.state_analyze)
        self.state_capture_droplet.addTransition(t7)

        # Analyze -> Capture (replicate loop)
        t7b = QSignalTransition()
        t7b.setSenderObject(self)
        t7b.setSignal(b"2replicateContinue()")
        t7b.setTargetState(self.state_capture_droplet)
        self.state_analyze.addTransition(t7b)

        # Transition: Analyze -> set pressure (continue search).
        t8 = QSignalTransition()
        t8.setSenderObject(self)
        t8.setSignal(b"2continueSearch()")
        t8.setTargetState(self.state_set_pressure)
        self.state_analyze.addTransition(t8)

        # Transition: Analyze -> final (droplet detected).
        t9 = QSignalTransition()
        t9.setSenderObject(self)
        t9.setSignal(b"2dropletDetected()")
        t9.setTargetState(self.state_final)
        self.state_analyze.addTransition(t9)

        # Add states to the state machine.
        self.state_machine.addState(self.state_initial_position)
        self.state_machine.addState(self.state_prepare_background)
        self.state_machine.addState(self.state_capture_background)
        self.state_machine.addState(self.state_set_delay)
        self.state_machine.addState(self.state_capture_nozzle)
        self.state_machine.addState(self.state_analyze_nozzle)
        self.state_machine.addState(self.state_set_pressure)
        self.state_machine.addState(self.state_capture_droplet)
        self.state_machine.addState(self.state_analyze)
        self.state_machine.addState(self.state_final)

        # Set the initial state.
        self.state_machine.setInitialState(self.state_initial_position)

    @Slot()
    def onInitialPosition(self):
        self.stageChanged.emit("Moving to initial position")
        centered_nozzle_position = self.calibration_manager.get_nozzle_center()
        # Create a copy of the centered nozzle position
        target_position = centered_nozzle_position.copy()
        if target_position is None:
            print('Nozzle center not found')
            self.calibrationError.emit("Nozzle center not found")
            return

        current = self.model.droplet_camera_model.get_center_in_pixels()
        move_vector = self.model.droplet_camera_model.calculate_move_to_top_center(current,offset=350)
        dX, dY, dZ = move_vector
        target_position['X'] += dX
        target_position['Y'] += dY
        target_position['Z'] += dZ
        absolute_move_vector = (target_position['X'], target_position['Y'],target_position['Z'])
        print(f'Requesting move to initial position: {absolute_move_vector}')
        self.calibration_manager.moveAbsoluteRequested.emit(absolute_move_vector, self.calibration_manager.emitMoveCompleted)

    @Slot()
    def onPrepareBackground(self):
        self.stageChanged.emit("Preparing background (0 droplets)")
        settings = {"num_droplets": 0}
        print(f"Requesting settings change: {settings}")
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureBackground(self):
        self.stageChanged.emit("Capturing background image")
        print("Requesting background capture")
        self.calibration_manager.captureImageRequested.emit(self.handleBackgroundCaptured)

    @Slot()
    def onSetDelay(self):
        self.stageChanged.emit("Setting flash delay to start time")
        self.start_delay = self.calibration_manager.get_emergence_time()
        if self.start_delay is None:
            self.calibrationError.emit("No start time available")
            print("No start time available")
            return
        settings = {"flash_delay": self.start_delay, "num_droplets": 1}
        print(f"Requesting settings change: {settings}")
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureNozzle(self):
        self.stageChanged.emit("Capturing nozzle image")
        print("Requesting nozzle capture")
        self.calibration_manager.captureImageRequested.emit(self.handleNozzleCaptured)

    @Slot()
    def onAnalyzeNozzle(self):
        self.stageChanged.emit("Analyzing nozzle image")
        nozzle_center, focus, image = self.model.droplet_camera_model.identify_nozzle(self.background_image, self.nozzle_image)
        if nozzle_center is None:
            self.calibrationError.emit("No nozzle detected")
            print("No nozzle detected")
            return
        self.presentImageSignal.emit(image)
        self.nozzle_center = nozzle_center
        self.stageChanged.emit(f"Nozzle center: {nozzle_center}")
        print(f"Nozzle center: {nozzle_center}")
        self.emitNozzleDetected()

    @Slot()
    def onSetPressure(self):
        self.stageChanged.emit(f"Setting pressure to {self.candidate_pressure:.2f}")
        new_flash_delay = max(0, int(self.start_delay + self.start_delay_offset))
        print(f"New flash delay: {new_flash_delay}")
        settings = {
            "flash_delay": new_flash_delay,
            "num_droplets": 1,
            "print_pressure": self.candidate_pressure,
        }
        # reset replicate bookkeeping
        self._rep_results = []
        self._rep_captured = 0
        
        print(f"Requesting settings change: {settings}")
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureDroplet(self):
        self.stageChanged.emit("Capturing droplet image at set pressure")
        print("Requesting droplet capture")
        self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)

    def _record_replicate(self, droplet_count: int, nozzle_area):
        """Store one replicate result for the current pressure."""
        self._rep_results.append((droplet_count, nozzle_area))
        self._rep_captured += 1

    def _aggregate_replicates(self):
        """
        Returns (agg_droplet_count, agg_nozzle_area, debug_dict)

        - droplet_count aggregation:
          * if any replicate has >=2 → classify as 2 (too high)
          * elif majority == 0 → classify as 0 (too low)
          * else majority == 1 → classify as 1 and use median
            nozzle_area from those 1-drop replicates
        - agg_nozzle_area is None unless agg_count == 1
        """
        counts = [c for (c, _a) in self._rep_results]
        areas_1 = [a for (c, a) in self._rep_results if c == 1 and a is not None]

        debug = {
            "replicates": list(self._rep_results),
            "n": len(self._rep_results),
        }

        # any multi-drop → too high
        if any(c >= 2 for c in counts):
            debug["rule"] = "any>=2 → too high"
            return (2, None, debug)

        # majority vote between 0 and 1
        tally = Counter(counts)
        # tie-breaker: prefer stability—pick 1 if it exists (you can invert if you prefer conservative)
        maj, _ = max(tally.items(), key=lambda kv: (kv[1], kv[0] == 1))
        if maj == 0:
            debug["rule"] = "majority 0 → too low"
            return (0, None, debug)

        # maj == 1
        med_area = median(areas_1) if areas_1 else None
        debug["rule"] = "majority 1 → use median area"
        debug["median_area"] = med_area
        return (1, med_area, debug)

    # def evaluate_condition(self,droplet_count, nozzle_area, threshold):
    #     """Return one of: 'TOO_LOW', 'ACCEPTABLE', 'BORDERLINE', 'TOO_HIGH'."""
    #     if droplet_count == 0:
    #         return "TOO_LOW"
    #     if droplet_count >= 2:
    #         return "TOO_HIGH"

    #     # droplet_count == 1
    #     if nozzle_area is None:
    #         return "TOO_HIGH"

    #     low = threshold * (1.0 - self.hysteresis_frac)
    #     high = threshold * (1.0 + self.hysteresis_frac)

    #     if nozzle_area <= low:
    #         return "ACCEPTABLE"
    #     elif nozzle_area <= high:
    #         return "BORDERLINE"   # treat as acceptable during bracketing
    #     else:
    #         return "TOO_HIGH"

    def _clamp(self, p):
        return max(self.lower_pressure, min(self.upper_pressure, p))

    def evaluate_condition(self, droplet_count, nozzle_area, threshold):
        """
        Returns one of: 'TOO_LOW', 'ACCEPTABLE', 'BORDERLINE', 'NEAR', 'TOO_HIGH'.

        Semantics:
        - TOO_LOW:   0 droplets
        - ACCEPTABLE: 1 droplet with nozzle_area <= low band
        - BORDERLINE: 1 droplet with nozzle_area in [low, high] (still okay)
        - NEAR:      1 droplet with nozzle_area > high (close but a bit “wet”)
        - TOO_HIGH:  >= 2 droplets
        """
        if droplet_count == 0:
            return "TOO_LOW"
        if droplet_count >= 2:
            return "TOO_HIGH"

        # droplet_count == 1
        if nozzle_area is None:
            # be tolerant: still a one-drop condition, just treat as NEAR
            return "NEAR"

        low  = threshold * (1.0 - self.hysteresis_frac)
        high = threshold * (1.0 + self.hysteresis_frac)

        if nozzle_area <= low:
            return "ACCEPTABLE"
        elif nozzle_area <= high:
            return "BORDERLINE"
        else:
            return "NEAR"

    # Then you can have a dispatch dictionary:
    def handle_too_low(self):
        self.stageChanged.emit("Condition TOO_LOW: increasing pressure")
        if self.initial_state == "TOO_LOW":
            if self.coarse_search:
                print("increase by coarse step")
                self.candidate_pressure += self.coarse_step
            else:
                print("increase by fine step")
                self.candidate_pressure += self.fine_step
        else:
            if self.coarse_search:
                print("--- Transition found, now increasing pressure")
                self.transition_found = True
                self.coarse_search = False
                self.candidate_pressure = self.candidate_pressure + self.fine_step
            else:
                print("Still back tracking - increase by fine step")
                self.candidate_pressure += self.fine_step
        self.emitContinueSearch()

    def handle_acceptable(self):
        self.stageChanged.emit("Condition ACCEPTABLE: recording pressure")
        self.last_acceptable_pressure = self.candidate_pressure
        if self.initial_state == 'TOO_LOW':
            if self.coarse_search:
                print("Still increasing by coarse step")
                self.candidate_pressure += self.coarse_step
            # If the transition has already been found and a new acceptable pressure is found
            # end the calibration process
            elif self.transition_found:
                print("Final condition found")
                self.emitDropletDetected()
            else:
                print("SHOULD NOT OCCUR - increase by fine step")
                self.candidate_pressure += self.fine_step
        else:
            if self.coarse_search:
                print("--- Transition found, now increasing pressure")
                self.transition_found = True
                self.coarse_search = False
                self.candidate_pressure = self.candidate_pressure + self.fine_step
            else:
                print("Back tracking - increase by fine step")
                self.candidate_pressure += self.fine_step
        self.emitContinueSearch()

    def handle_too_high(self):
        self.stageChanged.emit("Condition TOO_HIGH: decreasing pressure")
        if self.initial_state == 'TOO_HIGH':
            if self.coarse_search:
                print("Still too high, decreasing pressure coarsely")
                self.candidate_pressure -= self.coarse_step
            # Indicates that it has already found the transition and so it should revert to the last 
            # acceptable pressure
            elif self.transition_found:
                print("Final condition found, new unacceptable pressure")
                if self.last_acceptable_pressure is not None:
                    print("Last acceptable pressure found")
                    self.final_condition_found = True
                    self.candidate_pressure = self.last_acceptable_pressure
                else:
                    print("No last acceptable pressure found")
                    self.candidate_pressure -= self.fine_step
                
            else:
                print("SHOULD NOT OCCUR - decrease by fine step")
                self.candidate_pressure -= self.fine_step
        else:
            if self.coarse_search:
                print("--- Transition found, now decreasing pressure")
                self.transition_found = True
                self.coarse_search = False
                self.candidate_pressure = self.candidate_pressure - self.fine_step

            else:
                print("Still decreasing looking for acceptable condition")
                self.candidate_pressure -= self.fine_step
        self.emitContinueSearch()

    dispatch = {
        "TOO_LOW": handle_too_low,
        "ACCEPTABLE": handle_acceptable,
        "TOO_HIGH": handle_too_high,
    }

    @Slot()
    def onAnalyze(self):
        self.stageChanged.emit("Analyzing droplet image")
        print("Analyzing droplet image")

        # --- analyze this replicate ---
        droplets, nozzle_area, image = self.model.droplet_camera_model.identify_droplets(
            self.droplet_image, self.background_image, self.nozzle_center
        )
        droplet_count = len(droplets) if droplets is not None else 0
        self.presentImageSignal.emit(image)

        # --- record replicate and maybe loop for more ---
        self._record_replicate(droplet_count, nozzle_area)
        print(f"[P-Cal] replicate {self._rep_captured}/{self.replicates_per_pressure} "
            f"@P={self.candidate_pressure:.3f}: count={droplet_count}, area={nozzle_area}")

        if self._rep_captured < self.replicates_per_pressure:
            self.replicateContinue.emit()
            return

        # --- aggregate replicates into a single decision for this pressure ---
        agg_count, agg_area, dbg = self._aggregate_replicates()
        print(f"[P-Cal] aggregated @P={self.candidate_pressure:.3f}: "
            f"count={agg_count}, area={agg_area}, rule={dbg.get('rule')} "
            f"reps={dbg.get('replicates')}")
        self.measurements.append((self.candidate_pressure, agg_count, agg_area))
        self.stageChanged.emit(
            f"Aggregated — Pressure: {self.candidate_pressure:.3f}, "
            f"Droplet count: {agg_count}, Nozzle area: {agg_area}"
        )

        # classify with hysteresis-aware evaluator
        outcome = self.evaluate_condition(agg_count, agg_area, self.nozzle_droplet_threshold)
        one_drop = (outcome in ("ACCEPTABLE", "BORDERLINE", "NEAR"))

        # -------- Phase 1: build a bracket quickly and switch to refine --------
        if self.phase == "bracket":
            if outcome == "TOO_LOW":
                # remember and step up coarsely
                self.last_too_low_pressure = self.candidate_pressure
                self.candidate_pressure = self._clamp(self.candidate_pressure + self.coarse_step)
                print(f"[P-Cal] TOO_LOW → stepping up to {self.candidate_pressure:.3f}")
                self.emitContinueSearch()
                self.counter += 1
                if self.counter >= self.max_iterations:
                    self.calibrationError.emit("Pressure search did not converge (too low region)")
                return

            if one_drop:
                # first time we see any 1-drop → set hi and seed lo, then REFINE
                self.last_one_pressure = self.candidate_pressure
                self.bracket_hi = self.candidate_pressure
                if self.last_too_low_pressure is not None:
                    self.bracket_lo = self.last_too_low_pressure
                else:
                    # seed lo just below current
                    self.bracket_lo = self._clamp(self.candidate_pressure - self.coarse_step)

                self.phase = "refine"
                self.candidate_pressure = 0.5 * (self.bracket_lo + self.bracket_hi)
                print(f"[P-Cal] BRACKET→REFINE: lo={self.bracket_lo:.3f} hi={self.bracket_hi:.3f} "
                    f"→ mid={self.candidate_pressure:.3f} (outcome={outcome})")
                self.emitContinueSearch()
                self.counter += 1
                if self.counter >= self.max_iterations:
                    self.calibrationError.emit("Pressure search did not converge (switching to refine)")
                return

            # outcome == TOO_HIGH (>=2 droplets)
            if self.last_one_pressure is not None:
                # we’ve seen 1-drop before; refine between last too-low and that 1-drop
                self.bracket_hi = self.last_one_pressure
                if self.last_too_low_pressure is not None:
                    self.bracket_lo = self.last_too_low_pressure
                else:
                    self.bracket_lo = self._clamp(self.bracket_hi - self.coarse_step)

                self.phase = "refine"
                self.candidate_pressure = 0.5 * (self.bracket_lo + self.bracket_hi)
                print(f"[P-Cal] TOO_HIGH but seen ONE_DROP before → REFINE: "
                    f"lo={self.bracket_lo:.3f} hi={self.bracket_hi:.3f} mid={self.candidate_pressure:.3f}")
                self.emitContinueSearch()
                self.counter += 1
                if self.counter >= self.max_iterations:
                    self.calibrationError.emit("Pressure search did not converge (post-high → refine)")
                return
            else:
                # haven’t seen a one-drop yet; step down to find it
                self.candidate_pressure = self._clamp(self.candidate_pressure - self.coarse_step)
                print(f"[P-Cal] TOO_HIGH with no ONE_DROP yet → stepping down to {self.candidate_pressure:.3f}")
                self.emitContinueSearch()
                self.counter += 1
                if self.counter >= self.max_iterations:
                    self.calibrationError.emit("Pressure search did not converge (too high region)")
                return

        # -------- Phase 2: refine with bisection until hi-lo <= threshold --------
        if self.phase == "refine":
            if outcome == "TOO_LOW":
                # still below onset of one-droplet → move lo up
                self.bracket_lo = max(self.bracket_lo, self.candidate_pressure) if self.bracket_lo is not None else self.candidate_pressure
            else:
                # ANY one-drop (ACCEPTABLE/BORDERLINE/NEAR) OR multi-drop (TOO_HIGH) means "at/above onset"
                # For our goal (lowest 1-drop), treat both as tightening hi downward.
                self.bracket_hi = min(self.bracket_hi, self.candidate_pressure) if self.bracket_hi is not None else self.candidate_pressure

            if (self.bracket_lo is not None) and (self.bracket_hi is not None):
                gap = self.bracket_hi - self.bracket_lo
                print(f"[P-Cal] REFINE: lo={self.bracket_lo:.3f} hi={self.bracket_hi:.3f} gap={gap:.4f}")
                if gap <= self.pressure_threshold:
                    # **return the LOWEST pressure that yields a single droplet**
                    self.candidate_pressure = self.bracket_hi
                    self.final_condition_found = True
                    self.stageChanged.emit("Final condition found (bisection converged to lowest one-drop)")
                    self.calibrationDataUpdated.emit({
                        'measurements': self.measurements,
                        'result': {'pressure': self.candidate_pressure}
                    })
                    self.emitDropletDetected()
                    return

                # continue bisection
                self.candidate_pressure = 0.5 * (self.bracket_lo + self.bracket_hi)
                print(f"[P-Cal] Next mid={self.candidate_pressure:.3f}")
                self.emitContinueSearch()
                self.counter += 1
                if self.counter >= self.max_iterations:
                    # fall back to best available bound; choose hi (our goal)
                    if self.bracket_hi is not None:
                        self.candidate_pressure = self.bracket_hi
                        self.final_condition_found = True
                        self.emitDropletDetected()
                    else:
                        self.calibrationError.emit("Pressure search did not converge (refine phase)")
                return
        
    # @Slot()
    # def onAnalyze(self):
    #     self.stageChanged.emit("Analyzing droplet image")
    #     print("Analyzing droplet image")
    #     droplets, nozzle_area, image = self.model.droplet_camera_model.identify_droplets(self.droplet_image, self.background_image, self.nozzle_center)
    #     droplet_count = len(droplets) if droplets is not None else 0
    #     self.measurements.append((self.candidate_pressure, droplet_count, nozzle_area))
    #     self.presentImageSignal.emit(image)
    #     self.stageChanged.emit(f"Pressure: {self.candidate_pressure:.2f}, Droplet count: {droplet_count}, Nozzle area: {nozzle_area}")
    #     print(f"Counter: {self.counter}, Pressure: {self.candidate_pressure:.2f}, Droplet count: {droplet_count}, Nozzle area: {nozzle_area}")
    #     if self.final_condition_found:
    #         self.stageChanged.emit("Final condition found")
    #         print("Final condition found")
    #         self.calibrationDataUpdated.emit({'measurements': self.measurements, 'result': {'pressure': self.candidate_pressure}})
    #         self.emitDropletDetected()
    #         return

    #     outcome = self.evaluate_condition(droplet_count, nozzle_area, self.nozzle_droplet_threshold)
        
    #     if self.counter == 0:
    #         if outcome == 'TOO_HIGH':
    #             self.initial_state = 'TOO_HIGH'
    #             print('--- Initial state: TOO_HIGH ---')
    #         else:
    #             self.initial_state = 'TOO_LOW'
    #             print('--- Initial state: TOO_LOW ---')
        
    #     self.dispatch[outcome](self)
    #     self.counter += 1
    #     if self.counter >= self.max_iterations:
    #         self.calibrationError.emit("Pressure search did not converge")
    #         return

    @Slot()
    def onCalibrationCompleted(self):
        self.stageChanged.emit("Pressure calibration complete")
        self.calibrationDataUpdated.emit({'measurements': self.measurements, 'result': {'pressure': self.candidate_pressure}})
        self.calibrationCompleted.emit()

    def handleBackgroundCaptured(self, image):
        self.background_image = image
        self.calibration_manager.emitCaptureCompleted()

    def handleNozzleCaptured(self, image):
        self.nozzle_image = image
        self.calibration_manager.emitCaptureCompleted()

    def handleDropletCaptured(self, image):
        self.droplet_image = image
        self.calibration_manager.emitCaptureCompleted()

    def emitNozzleDetected(self):
        self.nozzleDetected.emit()

    def emitContinueSearch(self):
        self.continueSearch.emit()

    def emitDropletDetected(self):
        self.calibration_manager.set_background_image(self.background_image)
        # self.calibration_manager.set_nozzle_center(self.nozzle_center)
        self.calibration_manager.set_nozzle_center_image_position(self.nozzle_center)
        self.calibration_manager.set_min_start_delay(self.start_delay + self.start_delay_offset)
        self.dropletDetected.emit()

class TrajectoryCalibrationProcess(BaseCalibrationProcess):
    # Custom signals for state transitions.
    continueTrajectory = Signal()       # To trigger capture of next droplet image.
    trajectoryCalculated = Signal()       # To trigger transition from trajectory analysis to final.
    trajectoryFinalized = Signal()        # To indicate that final trajectory analysis is complete.
    changePressure = Signal()             # To trigger a change in pressure.

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)
        self.phase_name = "trajectory_calibration"
        
        # Use information passed from previous calibrations:
        # (Assume these were set by the pressure calibration process and passed to the model.)
        self.import_calibration_data()

        # Number of droplet images to capture.
        self.num_images = 5
        self.image_counter = 0

        # Variables to change pressure
        self.pressure_step = 0.02
        self.max_pressure = 1.2
        self.min_pressure = 0.3
        self.new_pressure = None
        
        # Lists to store droplet analysis results.
        self.droplet_positions = []  # List of (x, y) positions.
        self.droplet_focus = []      # List of focus values.
        self.annotated_images = []   # Annotated images for record.
        
        # Define states.
        self.state_capture_droplet = QState()
        self.state_analyze = QState()
        self.state_change_pressure = QState()
        self.state_trajectory_analysis = QState()
        self.state_final = QFinalState()
        
        # Connect on-entry actions.
        self.state_capture_droplet.entered.connect(self.onCaptureDroplet)
        self.state_analyze.entered.connect(self.onAnalyze)
        self.state_change_pressure.entered.connect(self.onChangePressure)
        self.state_trajectory_analysis.entered.connect(self.onTrajectoryAnalysis)
        self.state_final.entered.connect(self.onCalibrationCompleted)
        
        # Create transitions.
        # Transition: After capturing a droplet image, move to analysis.
        t1 = QSignalTransition()
        t1.setSenderObject(self.calibration_manager)
        t1.setSignal(b"2captureCompleted()")
        t1.setTargetState(self.state_analyze)
        self.state_capture_droplet.addTransition(t1)
        
        # Transition: In the analysis state, decide whether to capture the next image or perform trajectory analysis.
        t2 = QSignalTransition()
        t2.setSenderObject(self)
        t2.setSignal(b"2continueTrajectory()")
        t2.setTargetState(self.state_capture_droplet)
        self.state_analyze.addTransition(t2)
        
        t3 = QSignalTransition()
        t3.setSenderObject(self)
        t3.setSignal(b"2trajectoryCalculated()")
        t3.setTargetState(self.state_trajectory_analysis)
        self.state_analyze.addTransition(t3)

        # If no droplets or multiple droplets are identified then change the pressure and recapture
        t0 = QSignalTransition()
        t0.setSenderObject(self)
        t0.setSignal(b"2changePressure()")
        t0.setTargetState(self.state_change_pressure)
        self.state_analyze.addTransition(t0)
        
        t01 = QSignalTransition()
        t01.setSenderObject(self.calibration_manager)
        t01.setSignal(b"2settingsChangeCompleted()")
        t01.setTargetState(self.state_capture_droplet)
        self.state_change_pressure.addTransition(t01)
        
        # Transition: After trajectory analysis, move to final state.
        t4 = QSignalTransition()
        t4.setSenderObject(self)
        t4.setSignal(b"2trajectoryFinalized()")
        t4.setTargetState(self.state_final)
        self.state_trajectory_analysis.addTransition(t4)
        
        # Add states to the state machine.
        self.state_machine.addState(self.state_capture_droplet)
        self.state_machine.addState(self.state_analyze)
        self.state_machine.addState(self.state_change_pressure)
        self.state_machine.addState(self.state_trajectory_analysis)
        self.state_machine.addState(self.state_final)
        
        # Set the initial state.
        self.state_machine.setInitialState(self.state_capture_droplet)
    
    def import_calibration_data(self):
        self.nozzle_center_image_position = self.calibration_manager.get_nozzle_center_image_position()
        self.nozzle_center_machine = self.calibration_manager.get_nozzle_center()  
        self.background_image = self.calibration_manager.get_background_image()
        if self.nozzle_center_machine is None or self.background_image is None or self.nozzle_center_image_position is None:
            self.calibrationError.emit("Must complete pressure calibration first")
            return
    @Slot()
    def onCaptureDroplet(self):
        self.stageChanged.emit(f"Capturing droplet image {self.image_counter + 1} of {self.num_images}")
        self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)
    
    def handleDropletCaptured(self, image):
        self.droplet_image = image
        self.calibration_manager.emitCaptureCompleted()
    
    @Slot()
    def onAnalyze(self):
        self.stageChanged.emit(f"Analyzing droplet image {self.image_counter + 1}")
        # Assume the model's droplet camera model provides a method that analyzes the droplet.
        # For example, identify_droplet(image, background, nozzle_center) returns (center, focus, annotated_image)
        droplets, nozzle_area, annotated_image = self.model.droplet_camera_model.identify_droplets(self.droplet_image, self.background_image, self.nozzle_center_image_position)
        if droplets is None or len(droplets) == 0:
            current_pressure = self.model.machine_model.get_current_print_pressure()
            self.new_pressure = current_pressure + self.pressure_step
            if self.new_pressure > self.max_pressure:
                self.calibrationError.emit("Maximum pressure reached")
                return

            self.stageChanged.emit(f"No droplet detected, increasing pressure to {self.new_pressure}")
            print(f"No droplet detected, increasing pressure to {self.new_pressure}")
            self.emitChangePressure()
            return
        droplet_count = len(droplets) if droplets is not None else 0
        if droplet_count > 1:
            current_pressure = self.model.machine_model.get_current_print_pressure()
            self.new_pressure = current_pressure - self.pressure_step
            if self.new_pressure < self.min_pressure:
                self.calibrationError.emit("Minimum pressure reached")
                return
            self.stageChanged.emit(f"Multiple droplets detected, decreasing pressure to {self.new_pressure}")
            print(f"Multiple droplets detected, decreasing pressure to {self.new_pressure}")
            
            # Reset the droplet positions and focus values for the new pressure.
            self.droplet_positions = []
            # self.droplet_focus = []
            self.annotated_images = []
            self.image_counter = 0
            
            self.emitChangePressure()
            return
        # If not the first droplet, overlay the previous droplet centers.
        for pos in self.droplet_positions:
            cv2.circle(annotated_image, pos, 5, (0, 255, 255), -1)
        # Draw the current droplet center.
        droplet_center = droplets[0]
        cv2.circle(annotated_image, droplet_center, 10, (0, 0, 255), -1)
        self.presentImageSignal.emit(annotated_image)
        # Record the measurement.
        self.droplet_positions.append(droplet_center)
        # self.droplet_focus.append(focus)
        self.annotated_images.append(annotated_image)
        self.image_counter += 1
        
        if self.image_counter < self.num_images:
            self.emitContinueTrajectory()
        else:
            self.emitTrajectoryCalculated()

    @Slot()
    def onChangePressure(self):
        self.stageChanged.emit("Changing pressure")
        settings = {
            "print_pressure": self.new_pressure,
        }
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)
    
    @Slot()
    def onTrajectoryAnalysis(self):
        self.stageChanged.emit("Performing final trajectory analysis")
        # Compute mean and standard deviation of droplet positions.
        positions = np.array(self.droplet_positions)  # shape (n,2)
        mean_pos = list(np.mean(positions, axis=0).astype(int))
        print(f"Mean position: {mean_pos}")
        std_dev = np.std(positions, axis=0)
        # Annotate the final image.
        final_image = self.annotated_images[-1].copy()
        for pos in self.droplet_positions:
            cv2.circle(final_image, pos, 5, (255, 0, 0), -1)
        cv2.circle(final_image, mean_pos, 8, (0, 255, 0), -1)
        cv2.line(final_image, self.nozzle_center_image_position, mean_pos, (0, 255, 255), 2)
        self.presentImageSignal.emit(final_image)

        machine_position = self.model.machine_model.get_current_position_dict()
        droplet_machine_position = self.model.droplet_camera_model.convert_pixel_position_to_motor_steps(mean_pos, machine_position)

        # Package results.
        results = {
            'droplet_positions': self.droplet_positions,
            'mean_position': droplet_machine_position,
            'std_dev': std_dev.tolist(),
            'trajectory_vector': (droplet_machine_position['X'] - self.nozzle_center_machine['X'], droplet_machine_position['Y'] - self.nozzle_center_machine['Y'], droplet_machine_position['Z'] - self.nozzle_center_machine['Z'])
        }
        print(f"Trajectory results: {results}")
        
        self.calibration_manager.set_trajectory_vector(results['trajectory_vector'])
        self.calibration_manager.set_intermediate_droplet_position(droplet_machine_position)
        self.calibrationDataUpdated.emit({'measurements': self.droplet_positions, 'result': results})
        self.emitTrajectoryFinalized()
    
    def emitContinueTrajectory(self):
        self.continueTrajectory.emit()
    
    def emitChangePressure(self):
        self.changePressure.emit()
    
    def emitTrajectoryCalculated(self):
        self.trajectoryCalculated.emit()
    
    def emitTrajectoryFinalized(self):
        self.trajectoryFinalized.emit()
    
    @Slot()
    def onCalibrationCompleted(self):
        self.stageChanged.emit("Trajectory calibration complete")
        self.calibrationCompleted.emit()

class DropletSearchCalibrationProcess(BaseCalibrationProcess):
    """
    A calibration process to locate the droplet when printed at a fixed flash delay.
    Using trajectory information (from a previous calibration), it computes the target
    machine position to image the droplet at a defined distance from the nozzle. Then,
    after moving there and capturing a new background image, it iterates over a range of
    flash delays until a droplet contour is detected. Once detected, the droplet is analyzed
    to determine its center. If the droplet is not centered in the image, a move command is
    issued to re-center it. This loop continues until the droplet is centered within tolerance,
    after which the process emits its final calibration data.
    """
    # Custom signals for state transitions.
    continueSearch = Signal()
    restartSearch = Signal()    # To restart the flash delay screen with a shift in position
    changePressure = Signal()   # To trigger a change in pressure
    dropletFound = Signal()  # Emitted when a droplet is detected (but may not be centered)
    dropletCentered = Signal()  # Emitted when the droplet is centered within tolerance
    continueCharacterization = Signal()  # Emitted to continue droplet characterization
    analyzeCharacterization = Signal()  # Emitted to analyze droplet characterization data
    initiateCharacterizationAnalysis = Signal()  # Emitted to start droplet characterization analysis
    characterizationCompleted = Signal()  # Emitted when the droplet is centered and characterized

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)
        self.phase_name = "droplet_search"
        
        # New background image at target.
        self.background_image = None
        # The droplet image captured at a given flash delay.
        self.droplet_image = None

        # Variables for characterization
        self.num_images = 20
        self.image_counter = 0
        self.circularity_threshold = 1.15  # Example threshold for circularity.
        self.droplet_positions = []  # List of droplet positions.
        self.droplet_focus = []  # List of focus values.
        self.circularity_values = []  # List of circularity values.
        self.droplet_volumes = []  # List of droplet volumes.

        # Trajectory information should have been previously determined.
        self.import_calibration_data()

        # Set the target distance from the nozzle (in pixels).
        self.desired_distance = 2000 # example in pixels
        self.correction_offset = 0  # Offset to shift the target position (in Y motor steps).
        self.offset_counter = 0  # Counter to track the number of corrections.

        # Compute target machine position.
        # self.target_position = self.calculate_target_position(self.nozzle_center_machine, self.trajectory_vector, self.desired_distance)
        
        # print(f"Nozzle center: {self.nozzle_center_machine}, Target position: {self.target_position}")
        # print(f"Desired distance: {self.desired_distance}, Trajectory vector: {self.trajectory_vector}")

        
        # Flash delay search parameters.
        self.initial_delay_offset = 5000
        self.delay_range = (self.min_start_delay + self.initial_delay_offset, self.min_start_delay + 25000)  # adjust range as needed.
        self.delay_step_size = 2000  # adjust step size as needed.
        self.current_delay = self.min_start_delay + self.initial_delay_offset
        
        # Tolerance for centering the droplet (in pixels).
        self.center_tolerance = 100  
        
        # Variables for focus adjustment.
        self.focus_threshold = 5000000  # The focus value must exceed this number
        self.focus_step_size = 2
        self.focus_direction = 1  # 1 for increasing focus, -1 for decreasing.
        self.direction_counter = 0  # Counter to track focus direction changes.
        self.last_focus = None

        # Measurements for trajectory (if desired, could store focus values, droplet center, etc.).
        self.measurements = []  # e.g., list of (flash_delay, droplet_center, focus)

        # Variables to change pressure
        self.pressure_step = 0.02
        self.max_pressure = 1.2
        self.min_pressure = 0.3
        self.new_pressure = None

        # Define states.
        self.state_move_to_target = QState()
        self.state_prepare_background = QState()
        self.state_capture_background = QState()
        self.state_set_delay = QState()
        self.state_capture_droplet = QState()
        self.state_analyze = QState()
        self.state_center = QState()
        self.state_characterization = QState()
        self.state_change_pressure = QState()
        self.state_analyze_characterization = QState()
        self.state_continue_move_to_target = QState()
        self.state_final = QFinalState()

        # Connect on-entry actions.
        self.state_move_to_target.entered.connect(self.onMoveToTarget)
        self.state_prepare_background.entered.connect(self.onPrepareBackground)
        self.state_capture_background.entered.connect(self.onCaptureBackground)
        self.state_set_delay.entered.connect(self.onSetDelay)
        self.state_capture_droplet.entered.connect(self.onCaptureDroplet)
        self.state_analyze.entered.connect(self.onAnalyze)
        self.state_center.entered.connect(self.onCenter)
        self.state_characterization.entered.connect(self.onCharacterization)
        self.state_change_pressure.entered.connect(self.onChangePressure)
        self.state_analyze_characterization.entered.connect(self.onAnalyzeCharacterization)
        self.state_continue_move_to_target.entered.connect(self.onContinueMoveToTarget)
        self.state_final.entered.connect(self.onCalibrationCompleted)

        # Create transitions.
        # 0. After moving to target, transition to preparing background.
        t0 = QSignalTransition()
        t0.setSenderObject(self.calibration_manager)
        t0.setSignal(b"2moveCompleted()")
        t0.setTargetState(self.state_prepare_background)
        self.state_move_to_target.addTransition(t0)

        # 1. Prepare background, transition to capture background.
        tnew = QSignalTransition()
        tnew.setSenderObject(self.calibration_manager)
        tnew.setSignal(b"2settingsChangeCompleted()")
        tnew.setTargetState(self.state_capture_background)
        self.state_prepare_background.addTransition(tnew)

        # 2. After background capture, transition to set delay.
        t1 = QSignalTransition()
        t1.setSenderObject(self.calibration_manager)
        t1.setSignal(b"2captureCompleted()")
        t1.setTargetState(self.state_set_delay)
        self.state_capture_background.addTransition(t1)

        # 3. After setting delay, capture droplet.
        t2 = QSignalTransition()
        t2.setSenderObject(self.calibration_manager)
        t2.setSignal(b"2settingsChangeCompleted()")
        t2.setTargetState(self.state_capture_droplet)
        self.state_set_delay.addTransition(t2)

        # 4. After capturing droplet image, transition to analyze.
        t3 = QSignalTransition()
        t3.setSenderObject(self.calibration_manager)
        t3.setSignal(b"2captureCompleted()")
        t3.setTargetState(self.state_analyze)
        self.state_capture_droplet.addTransition(t3)

        # 5. In analyze state:
        # If no droplet contour is detected, emit continueSearch to loop back to state_set_delay.
        t4 = QSignalTransition()
        t4.setSenderObject(self)
        t4.setSignal(b"2continueSearch()")
        t4.setTargetState(self.state_set_delay)
        self.state_analyze.addTransition(t4)
        # If a droplet is detected, emit dropletFound to transition to state_center.
        t5 = QSignalTransition()
        t5.setSenderObject(self)
        t5.setSignal(b"2dropletFound()")
        t5.setTargetState(self.state_center)
        self.state_analyze.addTransition(t5)
        # If the range of delays are exhausted, move the target position and restart the search
        t51 = QSignalTransition()
        t51.setSenderObject(self)
        t51.setSignal(b"2restartSearch()")
        t51.setTargetState(self.state_move_to_target)
        self.state_analyze.addTransition(t51)


        # 6. In center state:
        # If droplet is centered within tolerance, emit dropletCentered to transition to droplet characterization.
        t6 = QSignalTransition()
        t6.setSenderObject(self)
        t6.setSignal(b"2dropletCentered()")
        t6.setTargetState(self.state_characterization)
        self.state_center.addTransition(t6)
        # If not centered, remain in state_center (or loop back to capture droplet) after commanding a re-centering move.
        t7 = QSignalTransition()
        t7.setSenderObject(self.calibration_manager)
        t7.setSignal(b"2moveCompleted()")
        t7.setTargetState(self.state_capture_droplet)
        self.state_center.addTransition(t7)

        # 7. In characterization state:
        # If all images have been characterized, transition to final state.
        t8 = QSignalTransition()
        t8.setSenderObject(self)
        t8.setSignal(b"initiateCharacterizationAnalysis()")
        t8.setTargetState(self.state_analyze_characterization)
        self.state_characterization.addTransition(t8)
        # If not all images have been characterized, emit continueCharacterization to loop back to capture droplet.
        t9 = QSignalTransition()
        t9.setSenderObject(self)
        t9.setSignal(b"2continueCharacterization()")
        t9.setTargetState(self.state_capture_droplet)
        self.state_characterization.addTransition(t9)
        # If the droplet is not in focus, move the machine and recapture the droplet image.
        t10 = QSignalTransition()
        t10.setSenderObject(self.calibration_manager)
        t10.setSignal(b"2moveCompleted()")
        t10.setTargetState(self.state_capture_droplet)
        self.state_characterization.addTransition(t10)

        # If multiplet droplets are found the pressure needs to change and the process needs to restart
        t11 = QSignalTransition()
        t11.setSenderObject(self)
        t11.setSignal(b"2changePressure()")
        t11.setTargetState(self.state_change_pressure)
        self.state_characterization.addTransition(t11)

        t12 = QSignalTransition()
        t12.setSenderObject(self.calibration_manager)
        t12.setSignal(b"2settingsChangeCompleted()")
        t12.setTargetState(self.state_capture_droplet)
        self.state_change_pressure.addTransition(t12)

        # 8. In analyze characterization state:
        # If the droplets were found to be circular, emit dropletCharacterized to transition to final state.
        t10 = QSignalTransition()
        t10.setSenderObject(self)
        t10.setSignal(b"characterizationCompleted()")
        t10.setTargetState(self.state_final)
        self.state_analyze_characterization.addTransition(t10)
        # If the droplets were not circular, loop back to the beginning setting a new target distance.
        t11 = QSignalTransition()
        t11.setSenderObject(self)
        t11.setSignal(b"2continueSearch()")
        t11.setTargetState(self.state_continue_move_to_target)
        self.state_analyze_characterization.addTransition(t11)

        # Add states to the state machine.
        self.state_machine.addState(self.state_move_to_target)
        self.state_machine.addState(self.state_prepare_background)
        self.state_machine.addState(self.state_capture_background)
        self.state_machine.addState(self.state_set_delay)
        self.state_machine.addState(self.state_capture_droplet)
        self.state_machine.addState(self.state_analyze)
        self.state_machine.addState(self.state_center)
        self.state_machine.addState(self.state_characterization)
        self.state_machine.addState(self.state_change_pressure)
        self.state_machine.addState(self.state_analyze_characterization)
        self.state_machine.addState(self.state_continue_move_to_target)
        self.state_machine.addState(self.state_final)
        
        # Set initial state.
        self.state_machine.setInitialState(self.state_move_to_target)

    def import_calibration_data(self):
        # Import trajectory information from previous calibration.
        self.trajectory_vector = self.calibration_manager.get_trajectory_vector()
        self.min_start_delay = self.calibration_manager.get_min_start_delay()
        # Import nozzle center from previous calibration.
        self.nozzle_center_machine = self.calibration_manager.get_nozzle_center()
        if self.trajectory_vector is None or self.min_start_delay is None or self.nozzle_center_machine is None:
            self.calibrationError.emit("Must complete previous calibration first")
            return

    # def calculate_target_position(self, nozzle_center, trajectory_vector, desired_distance,horizontal_offset=0):
    #     # Convert nozzle_center from dict of motor positions to array of positions
    #     nozzle_center = np.array([nozzle_center['X'], nozzle_center['Y'], nozzle_center['Z']])
        
    #     # Compute the offset by normalizing the trajectory vector and scaling by desired_distance.
    #     nozzle = np.array(nozzle_center, dtype=float)
    #     vec = np.array(trajectory_vector, dtype=float)
    #     # # Invert the Y axis to match the image coordinates
    #     # vec[1] = -vec[1]
    #     norm = np.linalg.norm(vec)
    #     if norm == 0:
    #         offset = np.array([0,0,0])
    #     else:
    #         offset = (vec / norm) * desired_distance
    #     print(f"Nozzle: {nozzle}, Type: {type(nozzle)}")
    #     print(f"Trajectory vector: {vec}, Type: {type(vec)}")
    #     print(f"Normalized vector: {norm}, Type: {type(norm)}")
    #     print(f"Offset: {offset}, Type: {type(offset)}")

    #     target = nozzle + offset

    #     # If the Y component is negative add the offset to the Y component
    #     if vec[1] > 0:
    #         target[1] -= horizontal_offset
    #     else:
    #         target[1] += horizontal_offset
    #     print(f"Target position: {target}, Type: {type(target)}")
    #     return tuple(target.astype(int))

    def calculate_target_position(self, nozzle_center, trajectory_vector, desired_distance_px, horizontal_offset_steps=0):
        """
        Choose a target point 'desired_distance_px' pixels away from the nozzle
        along the droplet direction, then convert that pixel offset to machine steps
        using the image Jacobian A (2x2 mapping [dX,dZ] -> [delta_cx, delta_cy]).

        Args:
            nozzle_center: dict {"X","Y","Z"} in machine steps (or mm mapped to steps)
            trajectory_vector: tuple/list (dX, dY, dZ) in machine steps
            desired_distance_px: scalar distance in pixels along the droplet direction
            horizontal_offset_steps: extra Y offset in *machine steps* (focus axis)

        Returns:
            (X_target, Y_target, Z_target) in machine steps (ints)
        """
        # Access camera calibration matrices
        A     = self.model.droplet_camera_model.A      # shape (2,2) maps [dX,dZ] -> [delta_cx, delta_cy]
        A_inv = self.model.droplet_camera_model.A_inv  # inverse

        # Use only X/Z for image-plane mapping (Y is focus-only in this model)
        vx, _, vz = trajectory_vector
        v_xz = np.array([float(vx), float(vz)], dtype=float)

        # If trajectory has no X/Z component, bail out to a trivial target
        if np.linalg.norm(v_xz) < 1e-9:
            X = int(round(nozzle_center["X"]))
            Y = int(round(nozzle_center["Y"] + horizontal_offset_steps))
            Z = int(round(nozzle_center["Z"]))
            return (X, Y, Z)

        # Image-plane direction (in pixels) produced by moving along v_xz
        dir_px = A @ v_xz  # shape (2,)
        norm_px = np.linalg.norm(dir_px)
        if norm_px < 1e-9:
            # Degenerate mapping; fall back to pure +X pixel direction
            dir_px = np.array([1.0, 0.0], dtype=float)
            norm_px = 1.0

        # Unit direction in pixels
        u_px = dir_px / norm_px

        # Desired pixel delta along the droplet direction
        delta_px = desired_distance_px * u_px  # shape (2,)

        # Convert desired pixel delta back to machine steps (X,Z)
        dX_dZ = A_inv @ delta_px               # shape (2,)
        dX, dZ = dX_dZ[0], dX_dZ[1]

        # Compose target in machine space (add optional Y offset in steps)
        X = int(round(nozzle_center["X"] + dX))
        Y = int(round(nozzle_center["Y"] + horizontal_offset_steps))
        Z = int(round(nozzle_center["Z"] + dZ))
        return (X, Y, Z)

    @Slot()
    def onMoveToTarget(self):
        self.stageChanged.emit("Moving to target position based on trajectory")
        # self.target_position = self.calculate_target_position(self.nozzle_center_machine, self.trajectory_vector, self.desired_distance,horizontal_offset=self.correction_offset)
        self.target_position = self.calculate_target_position(
            self.nozzle_center_machine,
            self.trajectory_vector,           # (dX, dY, dZ) in steps
            self.desired_distance,            # pixels
            horizontal_offset_steps=self.correction_offset  # this is *steps*
        )
        print(f"Move vector: {self.target_position}")

        move_vector = self.target_position
        print(f"Move vector: {move_vector}")
        self.calibration_manager.moveAbsoluteRequested.emit(self.target_position, self.calibration_manager.emitMoveCompleted)

    @Slot()
    def onPrepareBackground(self):
        self.stageChanged.emit("Capturing new background image at target position")
        settings = {"num_droplets": 0}
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureBackground(self):
        self.stageChanged.emit("Capturing background image")
        self.calibration_manager.captureImageRequested.emit(self.handleBackgroundCaptured)

    @Slot()
    def onSetDelay(self):
        # The flash delay for droplet imaging is set to the delay used in the pressure calibration.
        self.stageChanged.emit(f"Setting flash delay to {self.current_delay} μs")
        settings = {"flash_delay": self.current_delay, "num_droplets": 1}
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureDroplet(self):
        self.stageChanged.emit("Capturing droplet image at set delay")
        self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)

    @Slot()
    def onAnalyze(self):
        self.stageChanged.emit("Analyzing droplet image for contour")
        # Use the model to detect a droplet contour.
        droplet_contour, annotated_image = self.model.droplet_camera_model.identify_droplet_contour(self.droplet_image, self.background_image)
        if droplet_contour is None:
            self.stageChanged.emit("No droplet contour detected, trying next delay")
            # Increment flash delay and try again.
            self.current_delay += self.delay_step_size  # Increment delay; adjust step as needed.
            if self.current_delay <= self.delay_range[1]:
                self.emitContinueSearch()
            else:
                if self.offset_counter < 3:
                    self.stageChanged.emit("Delay range exhausted, moving machine and restarting search")
                    self.current_delay = self.min_start_delay
                    self.correction_offset += 30
                    # self.delay_step_size = 1000
                    self.offset_counter += 1
                    self.emitRestartSearch()
                else:
                    self.stageChanged.emit("Delay range exhausted, unable to find droplet")
                    self.calibrationError.emit("Unable to find droplet")

        else:
            # Identify the bounding box of the contour and use its center.
            x, y, w, h = cv2.boundingRect(droplet_contour)
            droplet_center = (x + w//2, y + h//2)
            self.presentImageSignal.emit(annotated_image)
            self.measurements.append({"flash_delay": self.current_delay, "center": droplet_center})
            # If a contour is found, signal that a droplet has been found.
            self.emitDropletFound()

    @Slot()
    def onCenter(self):
        self.stageChanged.emit("Centering droplet in the frame")
        # In this state, capture a droplet image and compute its contour center.
        droplet_contour, annotated_image = self.model.droplet_camera_model.identify_droplet_contour(self.droplet_image, self.background_image)
        if droplet_contour is None:
            self.stageChanged.emit("Droplet lost during centering, recapturing")
            self.presentImageSignal.emit(annotated_image)
            self.emitContinueSearch()
            return
        
        x, y, w, h = cv2.boundingRect(droplet_contour)
        droplet_center = (x + w//2, y + h//2)
        # Draw the current droplet center.
        cv2.circle(annotated_image, droplet_center, 8, (0, 0, 255), -1)
        # Also draw the desired center (typically the center of the image).
        img_h, img_w = annotated_image.shape[:2]
        target = (img_w//2, img_h//2)
        cv2.circle(annotated_image, target, 8, (0, 255, 0), -1)
        self.presentImageSignal.emit(annotated_image)
        # Check if the droplet is centered within tolerance.
        if abs(droplet_center[0] - target[0]) <= self.center_tolerance and abs(droplet_center[1] - target[1]) <= self.center_tolerance:
            self.stageChanged.emit("Droplet centered")
            self.center_tolerance = 300  # Increase tolerance for characterization.
            self.emitDropletCentered()
        else:
            # Calculate move vector needed to center the droplet.
            move_vector = self.model.droplet_camera_model.calculate_move_to_target(droplet_center,target)
            self.stageChanged.emit(f"Moving machine by {move_vector} to re-center droplet")
            self.calibration_manager.moveRequested.emit(move_vector, self.calibration_manager.emitMoveCompleted)
            # After the move, re-capture droplet image.
            # The transition (t7 in the state_center handler) will loop back to state_capture_droplet.

    @Slot()
    def onCharacterization(self):
        self.stageChanged.emit("Characterizing droplet")
        # Use the model to characterize the droplet.
        droplet_characteristics, annotated_image = self.model.droplet_camera_model.characterize_droplet(self.droplet_image, self.background_image)
        if droplet_characteristics is None:
            self.stageChanged.emit("Droplet capture failed, recapturing")
            self.emitContinueCharacterization()
            return
        elif droplet_characteristics == 'Multiple':
            current_pressure = self.model.machine_model.get_current_print_pressure()
            self.new_pressure = current_pressure - self.pressure_step
            if self.new_pressure < self.min_pressure:
                self.calibrationError.emit("Minimum pressure reached")
                return
            self.stageChanged.emit(f"Multiple droplets detected, decreasing pressure to {self.new_pressure}")
            print(f"Multiple droplets detected, decreasing pressure to {self.new_pressure}")
            
            # Reset the droplet positions and focus values for the new pressure.
            self.droplet_positions = []
            self.droplet_focus = []
            self.circularity_values = []
            self.droplet_volumes = []
            self.image_counter = 0

            self.emitChangePressure()
            return
        print(f"{self.image_counter}:Droplet characteristics: {droplet_characteristics}")
        self.presentImageSignal.emit(annotated_image)

        if droplet_characteristics['focus'] < self.focus_threshold:
            if self.last_focus is not None:
                if droplet_characteristics['focus'] < self.last_focus:
                    self.focus_direction *= -1
                    self.direction_counter += 1
                    if self.direction_counter > 10:
                        print("Focus direction changed too many times, aborting")
                        self.calibrationError.emit("Unable to focus on the droplet")
                        return
                    elif self.direction_counter > 2:
                        print("Focus direction changed too many times, increasing step size")
                        self.focus_step_size = 4
            self.last_focus = droplet_characteristics['focus']

            # Scale the step size based on the focus value.
            if droplet_characteristics['focus'] < 1000000:
                self.focus_step_size = 10
            elif droplet_characteristics['focus'] < 300000:
                self.focus_step_size = 4
            else:
                self.focus_step_size = 2

            move_vector = (0, self.focus_step_size * self.focus_direction, 0)
            self.stageChanged.emit(f"Focus too low: {droplet_characteristics['focus']}, moving by {move_vector}")
            print(f"Focus too low: {droplet_characteristics['focus']}")
            self.calibration_manager.moveRequested.emit(move_vector, self.calibration_manager.emitMoveCompleted)
        else:
            self.focus_step_size = 2
            self.circularity_values.append(droplet_characteristics["circularity_ellipse"])
            self.droplet_positions.append(droplet_characteristics["center"])
            self.droplet_focus.append(droplet_characteristics["focus"])
            self.droplet_volumes.append(droplet_characteristics["volume"])
            self.image_counter += 1
            if self.image_counter < self.num_images:
                self.emitContinueCharacterization()
            else:
                self.emitInitiateAnalyzeCharacterization()

    @Slot()
    def onChangePressure(self):
        self.stageChanged.emit("Changing pressure")
        settings = {
            "print_pressure": self.new_pressure,
        }
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)
    

    @Slot()
    def onAnalyzeCharacterization(self):
        self.stageChanged.emit("Analyzing droplet characterization")
        # Check if all droplets are circular.
        circular = all([c < self.circularity_threshold for c in self.circularity_values])
        if circular:
            self.stageChanged.emit("Droplet characterized")
            self.emitCharacterizationCompleted()
        else:
            self.desired_distance += 500  # Increase distance for next iteration.
            self.stageChanged.emit("Droplet not circular, recapturing")
            self.emitContinueSearch()

    @Slot()
    def onContinueMoveToTarget(self):
        self.stageChanged.emit("Moving to new target position")
        # Calculate target using trajectory info.
        self.target_position = self.calculate_target_position(self.nozzle_center_machine, self.trajectory_vector, self.desired_distance)
        # Command the machine to move to target position.
        # move_vector = self.model.droplet_camera_model.calculate_move_to_target(self.target_position, self.nozzle_center_machine)
        move_vector = self.target_position
        print(f"Move vector: {move_vector}")
        self.calibration_manager.moveAbsoluteRequested.emit(move_vector, self.calibration_manager.emitMoveCompleted)
    
    @Slot()
    def onCalibrationCompleted(self):
        # After centering, perform final trajectory analysis.
        self.stageChanged.emit("Trajectory calibration complete")

        mean_center = tuple(np.mean(self.droplet_positions, axis=0).astype(int))
        std_center = np.std(self.droplet_positions, axis=0).tolist()
        # Compute trajectory vector from nozzle to mean droplet position.
        machine_position = self.model.machine_model.get_current_position_dict()
        droplet_machine_position = self.model.droplet_camera_model.convert_pixel_position_to_motor_steps(mean_center, machine_position)

        trajectory_vector = (droplet_machine_position['X'] - self.nozzle_center_machine['X'], droplet_machine_position['Y'] - self.nozzle_center_machine['Y'], droplet_machine_position['Z'] - self.nozzle_center_machine['Z'])
        print(f"Trajectory results: {trajectory_vector}")
        # Annotate final image.
        final_image = self.annotate_final_image(mean_center)
        results = {
            "droplet_positions": self.droplet_positions,
            "mean_position": droplet_machine_position,
            "std_dev": std_center,
            "trajectory_vector": trajectory_vector,
        }
        # Calculate the velocity based on the intermediate droplet position.
        intermediate_delay = self.calibration_manager.get_min_start_delay()
        intermediate_position = self.calibration_manager.get_intermediate_droplet_position()
        velocity_axis, velocity_total = self.model.droplet_camera_model.calculate_velocity(intermediate_delay, intermediate_position, self.current_delay, droplet_machine_position)
        print(f"Velocity axis: {velocity_axis}, Velocity total: {velocity_total}")
        # Calculate the mean and cv of droplet volumes.
        mean_volume = np.mean(self.droplet_volumes)
        cv_volume = (np.std(self.droplet_volumes) / mean_volume) * 100

        # Put text saying the mean and CV volume on the final image.
        cv2.putText(final_image, f"Mean volume: {mean_volume:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        cv2.putText(final_image, f"CV volume: {cv_volume:.2f}%", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        self.presentImageSignal.emit(final_image)

        print(f"Mean volume: {mean_volume}, CV volume: {cv_volume}")
        self.calibrationDataUpdated.emit({"measurements": self.measurements, "result": results})
        self.calibrationCompleted.emit()

    def annotate_final_image(self, mean_center):
        # Copy the last annotated image and overlay all droplet positions, the mean, and a line.
        final_img = self.droplet_image.copy()
        print("Annotating final image")
        for pos in self.droplet_positions:
            print(f"Position: {pos}")
            cv2.circle(final_img, pos, 5, (255, 0, 0), -1)
        cv2.circle(final_img, mean_center, 8, (0, 255, 0), -1)
        # cv2.line(final_img, self.nozzle_center, mean_center, (0, 255, 255), 2)
        return final_img        

    def handleBackgroundCaptured(self, image):
        self.background_image = image
        self.calibration_manager.emitCaptureCompleted()

    def handleDropletCaptured(self, image):
        self.droplet_image = image
        self.calibration_manager.emitCaptureCompleted()

    def handleNozzleCaptured(self, image):
        self.nozzle_image = image
        self.calibration_manager.emitCaptureCompleted()

    def emitContinueSearch(self):
        self.continueSearch.emit()

    def emitRestartSearch(self):
        self.restartSearch.emit()

    def emitChangePressure(self):
        self.changePressure.emit()
    
    def emitDropletFound(self):
        self.dropletFound.emit()

    def emitDropletCentered(self):
        self.dropletCentered.emit()

    def emitContinueCharacterization(self):
        self.continueCharacterization.emit()

    def emitInitiateAnalyzeCharacterization(self):
        self.initiateCharacterizationAnalysis.emit()

    def emitCharacterizationCompleted(self):
        self.characterizationCompleted.emit()


class DropletCameraModel(QObject):
    droplet_image_updated = Signal()
    flash_signal = Signal()
    record_metadata_signal = Signal(str)
    def __init__(self,steps_conv_path):
        super().__init__()
        print("\n--- DropletCameraModel initialized ---\n")
        self.latest_image = None
        self.analyzed_image = None
        self.reading = False
        self.signal = False
        self.num_flashes = 0
        self.flash_duration = 1000
        self.flash_delay = 5000
        self.num_droplets = 1
        self.exposure_time = 20000
        self.analysis_active = False
        self.saving_active = False
        self.image_width = 1088
        self.image_height = 1456

        self.intensity_threshold = 150
        self.circularity_threshold = 1.15
        self.min_area_threshold = 10
        self.edge_margin = 10

        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.image_dir = os.path.join(self.script_dir, 'Images')
        self.dir_name = "Untitled"
        self.save_dir = os.path.join(self.script_dir, self.dir_name)

        self.steps_conv_path = steps_conv_path
        self.intercept_cx, self.intercept_cy, self.A, self.A_inv = self.load_step_calibration(self.steps_conv_path)

    def get_image_size(self):
        return self.image_width, self.image_height

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

    def get_exposure_time(self):
        return self.exposure_time
    
    def update_exposure_time(self,exposure_time):
        self.exposure_time = int(exposure_time)
        self.flash_signal.emit()

    def get_image_metadata(self):
        return self.num_flashes, self.flash_duration, self.flash_delay, self.num_droplets, self.exposure_time

    def get_original_image(self):
        if self.analysis_active:
            return self.analyzed_image
        else:
            return self.latest_frame

    def start_saving(self):
        self.saving_active = True

    def stop_saving(self):
        self.saving_active = False

    def start_analyzing(self):
        self.analysis_active = True
        self.update_image(self.latest_frame)

    def stop_analyzing(self):
        self.analysis_active = False
        self.update_image(self.latest_frame)

    def set_analysis_parameters(self,intensity_threshold,circularity_threshold,min_area_threshold,edge_margin):
        self.intensity_threshold = intensity_threshold
        self.circularity_threshold = circularity_threshold
        self.min_area_threshold = min_area_threshold
        self.edge_margin = edge_margin
        self.update_image(self.latest_frame)
        print(f'Updated analysis parameters: {self.intensity_threshold}, {self.circularity_threshold}, {self.min_area_threshold}, {self.edge_margin}')

    def get_analysis_parameters(self):
        return self.intensity_threshold, self.circularity_threshold, self.min_area_threshold, self.edge_margin

    def set_save_directory(self,dir):
        self.dir_name = dir
        self.save_dir = os.path.join(self.image_dir, self.dir_name)
    
    def update_image(self,frame):
        self.latest_frame = frame
        if self.analysis_active:
            print('Analyzing...')
            results, self.analyzed_image = self.analyze_droplets(
                frame,
                intensity_threshold=self.intensity_threshold,
                circularity_threshold=self.circularity_threshold,
                min_area_threshold=self.min_area_threshold,
                edge_margin=self.edge_margin
            )
        self.droplet_image_updated.emit()
        if self.saving_active:
            self.save_frame()

    def compute_tenengrad_variance(self, gray, mask=None):
        """
        Computes the Tenengrad variance (a focus metric) in the grayscale image.
        Optionally applies a 'mask' to limit focus measurement to a region.
        A higher variance indicates sharper focus (steeper gradients).
        """
        Gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        Gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        # gradient_magnitude = cv2.magnitude(sobel_x ** 2, sobel_y ** 2)

        # if mask is not None:
        #     masked_vals = gradient_magnitude[mask > 0]
        #     variance = np.var(masked_vals)
        # else:
        #     variance = np.var(gradient_magnitude)
        G2 = Gx*Gx + Gy*Gy
        variance = np.var(G2 if mask is None else G2[mask > 0])
        return variance


    def identify_droplet(self, gray):
        """
        Finds the largest contour in the grayscale image after thresholding,
        and returns a minEnclosingCircle for that contour if it exists.
        Otherwise returns None.
        """
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, 50, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            c = max(contours, key=cv2.contourArea)
            ((x, y), r) = cv2.minEnclosingCircle(c)
            return (int(x), int(y), int(r))
        else:
            return None
            
    def create_ring_mask(self, shape, center_x, center_y, inner_radius, outer_radius):
        """
        Creates a 'ring-shaped' mask in a binary array of 'shape' (H,W).
        The ring is defined between inner_radius and outer_radius around (center_x, center_y).
        """
        mask = np.zeros(shape, dtype=np.uint8)
        center = (center_x, center_y)
        cv2.circle(mask, center, outer_radius, 255, -1)
        cv2.circle(mask, center, inner_radius, 0, -1)
        return mask

    def calc_droplet_focus(self, image, threshold=50):
        """
        Computes a focus metric (Tenengrad variance) around the largest droplet
        by creating a ring mask near the droplet boundary.
        Returns None if no droplet found.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        droplet_info = self.identify_droplet(gray)
        if droplet_info is None:
            return None
        droplet_x, droplet_y, droplet_radius = droplet_info
        # Expand/shrink radius by 10 px to define the ring
        mask = self.create_ring_mask(gray.shape, droplet_x, droplet_y,
                                max(0, droplet_radius - 10),
                                droplet_radius + 10)
        return self.compute_tenengrad_variance(gray, mask)

    def analyze_droplets(
        self,
        image,
        um_per_pixel=1.545,
        intensity_threshold=150,
        circularity_threshold=1.15,
        min_area_threshold=10,
        edge_margin=10,
    ):
        """
        Analyzes the droplet(s) in image. 
        Returns a list of droplet dictionaries, one for each detected droplet.

        Each droplet dict includes (among others):
        - 'near_edge_contour': bool (True if the contour bounding box touches the image edge)
        - 'near_edge_ellipse': bool (True if the ellipse bounding box touches the image edge)
        - 'warning': string with any caution messages (near edge, low circularity, etc.)

        If 'debug=True', displays intermediary images (original, threshold, final with contour).
        """
        if image is None:
            print(f"No image was provided for droplet analysis.")
            return [], None

        # 1) Compute focus metric
        focus = self.calc_droplet_focus(image, intensity_threshold)

        # 2) Convert to grayscale and threshold
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        thresh = cv2.threshold(gray, intensity_threshold, 255, cv2.THRESH_BINARY_INV)[1]

        # 3) Find contours
        contours, hierarchy = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        imgH, imgW = gray.shape[:2]

        droplet_results = []
        droplet_id = 0
        annotated = image.copy()

        for i, cnt in enumerate(contours):
            area_px = cv2.contourArea(cnt)
            if area_px < min_area_threshold:
                continue

            perimeter_px = cv2.arcLength(cnt, True)
            if perimeter_px < 1:
                continue

            # (A) Basic geometry
            circularity = (4.0 * math.pi * area_px) / (perimeter_px ** 2)
            radius_px = math.sqrt(area_px / math.pi)
            radius_um = radius_px * um_per_pixel
            volume_um3 = (4.0/3.0) * math.pi * (radius_um ** 3)
            volume_nL = volume_um3 * 1e-6

            # (B) Fit ellipse if possible
            major_axis_um = None
            minor_axis_um = None
            angle_deg = None
            center_ellipse = None
            ellipse_volume_nL = None
            radius_ratio = None

            if len(cnt) >= 5:
                ellipse = cv2.fitEllipse(cnt)
                (xc, yc), (MA, ma), angle = ellipse
                major_axis_um = MA * um_per_pixel
                minor_axis_um = ma * um_per_pixel
                angle_deg = angle
                center_ellipse = (xc, yc)
                # Approx sphere volume from "average" radius of major/minor
                ellipse_radius_um = ((major_axis_um / 2.0) + (minor_axis_um / 2.0)) / 2.0
                ellipse_volume_um3 = (4.0/3.0) * math.pi * (ellipse_radius_um ** 3)
                ellipse_volume_nL = ellipse_volume_um3 * 1e-6
                radius_ratio = (minor_axis_um / major_axis_um) if major_axis_um != 0 else None
            else:
                continue

            # (C) Edge Check
            near_edge_ellipse = False
            if center_ellipse is not None:
                ex, ey = center_ellipse
                rx = MA / 2.0
                ry = ma / 2.0
                left   = ex - rx
                right  = ex + rx
                top    = ey - ry
                bottom = ey + ry
                near_edge_ellipse = (
                    (left <= edge_margin) or 
                    (right >= (imgW - edge_margin)) or
                    (top <= edge_margin) or
                    (bottom >= (imgH - edge_margin))
                )

            # (D) Warnings
            warning_msg = []
            if radius_ratio > circularity_threshold:
                warning_msg.append(f"Circularity={radius_ratio:.2f} > threshold={circularity_threshold}")
            if near_edge_ellipse:
                warning_msg.append("Droplet is near image edge; volume may be inaccurate.")

            droplet_info = {
                "droplet_id": droplet_id,
                "center": center_ellipse,
                "circularity": circularity,
                "circularity_ellipse": radius_ratio,
                "ellipse_volume_nL": ellipse_volume_nL,
                "ellipse_center_px": center_ellipse,
                "focus": focus,
                "near_edge_ellipse": near_edge_ellipse,
                "warning": "; ".join(warning_msg) if warning_msg else None
            }
            if near_edge_ellipse:
                continue
            
            droplet_results.append(droplet_info)

            # (E) Annotated image
            
            cv2.drawContours(annotated, [cnt], -1, (0,255,0), 2)

            x, y, w, h = cv2.boundingRect(cnt)
            
            # Add number to the top right of the droplet
            cv2.putText(annotated, str(droplet_id), (x+w, y), cv2.FONT_HERSHEY_SIMPLEX,1, (0, 0, 255), 2)
            
            if ellipse_volume_nL is not None:
                cv2.putText(annotated, f"{ellipse_volume_nL:.2f} nL", (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            
            if radius_ratio is not None:
                cv2.putText(annotated, f"{radius_ratio:.2f}", (x, y-30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            
            if focus is not None:
                cv2.putText(annotated, f"{focus / 1e9:.2f}*10^9", (x, y-55), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            
            # bounding rect
            cv2.rectangle(
                annotated, (x, y), (x+w, y+h), (255,0,0), 2
            )

            # If ellipse
            if center_ellipse is not None:
                cv2.ellipse(annotated, ellipse, (255, 0, 255), 2)

            droplet_id += 1

        # # Sort largest droplet first
        # droplet_results.sort(key=lambda d: d["area_pixels"], reverse=True)

        return droplet_results, annotated

    def calc_diff_image(self,image, background):
        """
        Compute the difference image between the image and the background.
        """
        if image is None:
            print('Image is None')
            return None, None

        image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if background is None:
            print('Background image is None')
            # Diff equals the inverse of the image
            diff = cv2.bitwise_not(image_gray)

        else:
            background_gray = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)

            # Compute the absolute difference between the background and the image
            diff = cv2.absdiff(background_gray, image_gray)

        return image_gray,diff

    def identify_nozzle(self, background,image):

        image_gray, diff = self.calc_diff_image(image, background)
        if diff is None:
            return None, None, image
        
        # Apply a threshold to the difference image
        _, thresh = cv2.threshold(diff, 60, 255, cv2.THRESH_BINARY)

        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Check if there are any contours
        if len(contours) == 0:
            print('No contours detected')
            # Add text in the middle of the screen saying no contours detected
            cv2.putText(image, 'No contours detected', (image.shape[1]//2, image.shape[0]//2), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

            return None, None, image

        # Determine if there are mutliple large contours
        large_contours = [contour for contour in contours if cv2.contourArea(contour) > 1000]
        if len(large_contours) > 1:
            print('Multiple large contours detected')
            cv2.drawContours(image, large_contours, -1, (0, 255, 0), 2)
            # Add text in the middle of the screen saying multiple large contours detected
            cv2.putText(image, 'Multiple large contours detected', (image.shape[1]//2, image.shape[0]//2), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            return None, None, image

        # Find the largest contour and identify the center
        largest_contour = max(contours, key=cv2.contourArea)

        # Detect if the contour is in contact with the edge of the image

        x, y, w, h = cv2.boundingRect(largest_contour)
        center = (x + w//2, y + h//2)
        if x == 0 or y == 0 or x+w == image.shape[1] or y+h == image.shape[0]:
            print('Contour is in contact with the edge of the image')

        focus = self.compute_tenengrad_variance(image_gray)

        # Draw the contour
        cv2.drawContours(image, [largest_contour], -1, (0, 255, 0), 2)

        # Draw the bounding box
        cv2.rectangle(image, (x, y), (x+w, y+h), (255, 0, 0), 2)

        # Draw the center
        cv2.circle(image, center, 10, (0, 0, 255), -1)

        # Add the center coordinates and focus value to the bottom right of the nozzle
        cv2.putText(image, f'Center: {center}', (x+w, y+h), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        cv2.putText(image, f'Focus: {focus:.2f}', (x+w, y+h+30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        return center, focus, image
    
    def calc_bounding_rect_area(self, background, image):
        """
        Computes the area of the bounding rectangle around the largest contour in the image.
        """
        image_gray, diff = self.calc_diff_image(image, background)
        if diff is None:
            return None, None, image

        _, thresh = cv2.threshold(diff, 60, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if len(contours) == 0:
            print('No contours detected')
            return None, None, image

        largest_contour = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(largest_contour)
        center = (x + w//2, y + h//2)

        cv2.drawContours(image, [largest_contour], -1, (0, 255, 0), 2)
        cv2.rectangle(image, (x, y), (x+w, y+h), (255, 0, 0), 2)
        cv2.putText(image, f'Area: {w*h}', (x+w+5, y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        return w * h, center, image
    
    def identify_droplets(self,image, background, nozzle_center,min_area=1000):
        """
        Identifies the number of droplets and their locations in the image.
        - Uses the background image to compute the difference image.
        - Uses the nozzle to identify what contours are still in contact with the nozzle.
        - Excludes all contours that are above the nozzle as these are reflections in the image.
        """

        image_gray, diff = self.calc_diff_image(image, background)
        if diff is None:
            print('Difference image is None')
            return None, None, None

        # Apply a threshold to the difference image
        _, thresh = cv2.threshold(diff, 60, 255, cv2.THRESH_BINARY)

        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Check if there are any contours
        if len(contours) == 0:
            print('No contours detected')
            return None, None, None

        # Identify the droplets
        droplets = []
        large_contours = [contour for contour in contours if cv2.contourArea(contour) > min_area]
        cv2.drawContours(image, large_contours, -1, (0, 255, 0), 2)
        
        nozzle_droplet_area = 0
        for contour in large_contours:
            x, y, w, h = cv2.boundingRect(contour)

            # Check if the nozzle center is inside the bounding box
            if x < nozzle_center[0] < x+w and y < nozzle_center[1] < y+h:
                # print('Nozzle is inside the bounding box')
                cv2.circle(image, nozzle_center, 10, (255, 0, 0), -1)
                # Calculate the area of the bounding box, but only include the area that is below the nozzle center
                area = (y + h - nozzle_center[1]) * w

                # Add text to the bottom right of the bounding box
                cv2.putText(image, f'Area: {area}', (x+w, y+h), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                nozzle_droplet_area = max(nozzle_droplet_area, area)
                continue

            # Check if the contour is above the nozzle
            if y < nozzle_center[1]:
                print('Contour is above the nozzle')
                continue
            droplet_center = (x + w//2, y + h//2)
            droplets.append(droplet_center)

            # Draw the bounding box
            cv2.rectangle(image, (x, y), (x+w, y+h), (0, 0, 255), 2)
            cv2.circle(image, droplet_center, 10, (0, 0, 255), -1)

            # Add the droplet count to the top left of the image
            cv2.putText(image, f'Droplet count: {len(droplets)}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        return droplets, nozzle_droplet_area, image

    def identify_droplet_contour(self, image, background):
        """
        Identifies the contour of the droplet in the image.
        - Uses the background image to compute the difference image.
        - Applies a threshold to the difference image.
        - Finds the largest contour in the thresholded image.
        - Returns the contour and the annotated image.
        """
        image_gray, diff = self.calc_diff_image(image, background)
        if diff is None:
            print('Difference image is None')
            return None, None

        # Apply a threshold to the difference image
        _, thresh = cv2.threshold(diff, 60, 255, cv2.THRESH_BINARY)

        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Check if there are any contours
        if len(contours) == 0:
            print('No contours detected')
            return None, None

        # Find the largest contour
        largest_contour = max(contours, key=cv2.contourArea)

        # Draw the contour
        annotated_image = image.copy()
        cv2.drawContours(annotated_image, [largest_contour], -1, (0, 255, 0), 2)

        return largest_contour, annotated_image

    def characterize_droplet(self, image, background,um_per_pixel=1.545):
        """
        Characterizes the droplet in the image.
        - Uses the background image to compute the difference image.
        - Applies a threshold to the difference image.
        - Finds the largest contour in the thresholded image.
        - Computes the circularity of the droplet.
        - Fits an ellipse to the contour and computes the circularity of the ellipse.
        - Returns the circularity of the droplet and the ellipse.
        """
        image_gray, diff = self.calc_diff_image(image, background)
        if diff is None:
            print('Difference image is None')
            return None, None

        # Apply a threshold to the difference image
        _, thresh = cv2.threshold(diff, 60, 255, cv2.THRESH_BINARY)

        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Check if there are any contours
        if len(contours) == 0:
            cv2.putText(image, 'No contours detected', (image.shape[1]//2, image.shape[0]//2), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            print('No contours detected')
            return None, image

        # Determine if there are mutliple large contours
        large_contours = [contour for contour in contours if cv2.contourArea(contour) > 1000]
        if len(large_contours) > 1:
            print('Multiple large contours detected')
            cv2.drawContours(image, large_contours, -1, (0, 255, 0), 2)
            # Add text in the middle of the screen saying multiple large contours detected
            cv2.putText(image, 'Multiple large contours detected', (image.shape[1]//2, image.shape[0]//2), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            return "Multiple", image

        # Find the largest contour
        largest_contour = max(contours, key=cv2.contourArea)

        # Compute the circularity of the droplet
        area = cv2.contourArea(largest_contour)
        perimeter = cv2.arcLength(largest_contour, True)
        circularity = (4 * math.pi * area) / (perimeter ** 2)

        if len(largest_contour) < 5:
            print('Not enough points to fit an ellipse')
            cv2.putText(image, 'Not enough points to fit an ellipse', (image.shape[1]//2, image.shape[0]//2), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            return None, image

        # Fit an ellipse to the contour
        ellipse = cv2.fitEllipse(largest_contour)
        (xc, yc), (MA, ma), angle = ellipse
        major_axis_um = MA * um_per_pixel
        minor_axis_um = ma * um_per_pixel
        center_ellipse = (int(xc), int(yc))
        ellipse_circularity = minor_axis_um / major_axis_um
        ellipse_radius_um = ((major_axis_um / 2.0) + (minor_axis_um / 2.0)) / 2.0
        ellipse_volume_um3 = (4.0/3.0) * math.pi * (ellipse_radius_um ** 3)
        ellipse_volume_nL = ellipse_volume_um3 * 1e-6

        focus = self.compute_tenengrad_variance(diff)

        annotated = image.copy()
        cv2.drawContours(annotated, [largest_contour], -1, (0, 255, 0), 2)
        cv2.ellipse(annotated, ellipse, (255, 0, 255), 2)

        x, y, w, h = cv2.boundingRect(largest_contour)
        cv2.putText(annotated, f"{ellipse_volume_nL:.2f} nL", (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        cv2.putText(annotated, f"{ellipse_circularity:.2f}", (x, y-30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        cv2.putText(annotated, f"{focus / 1e6:.2f}*10^6", (x, y-55), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        results = {
            "center": center_ellipse,
            "circularity": circularity,
            "circularity_ellipse": ellipse_circularity,
            "volume": ellipse_volume_nL,
            "focus": focus
        }

        return results, annotated
    
    def save_frame(self):
        if self.latest_frame is not None:
            os.makedirs(self.save_dir, exist_ok=True)
            # Record the timestamp for when the image was captured including milliseconds
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")
            save_path = os.path.join(self.save_dir, f"image-{timestamp}.png")
            cv2.imwrite(save_path, self.latest_frame)
            print(f"Frame saved to {save_path}")
            self.record_metadata_signal.emit(timestamp)

    def load_step_calibration(self, json_path):
        """
        Reads a JSON file containing calibration info for the droplet printer.
        Returns intercept_cx, intercept_cy, A, A_inv.
        """
        with open(json_path, 'r') as f:
            data = json.load(f)
        
        intercept_cx = data["intercept_cx"]
        intercept_cy = data["intercept_cy"]
        
        # Convert the Python list to a NumPy array
        A = np.array(data["A"])
        
        # Compute or store the inverse
        A_inv = np.linalg.inv(A)
        
        return intercept_cx, intercept_cy, A, A_inv

    def compute_stage_move(self, delta_cx, delta_cy):
        """
        Given desired changes in (cx, cy), return the necessary (dX, dY, dZ)
        stage moves that achieve that image-plane shift, using the matrix inverse.
        
        This code assumes:
        delta_cx = A[0,0]*dX + A[0,1]*dZ
        delta_cy = A[1,0]*dX + A[1,1]*dZ
        with dY = 0 in this model.
        """
        delta_c = np.array([delta_cx, delta_cy])
        dX, dZ = self.A_inv.dot(delta_c)
        
        # Y controls the focus so it was not part of the calibration (coefficient = 0),
        # so we leave it at 0.0
        dY = 0.0
        dX = round(dX)
        dZ = round(dZ)
        
        return dX, dY, dZ

    def compute_move_by_fraction(self, x_frac, y_frac):
        """
        Given desired fractions of the image size (0.0 to 1.0), return the necessary
        (dX, dY, dZ) stage moves that achieve that image-plane shift.
        """
        delta_cx = x_frac * self.image_width
        delta_cy = y_frac * self.image_height

        return self.compute_stage_move(delta_cx, delta_cy)
    
    def calculate_move_to_target(self, current, target):
        delta_cx = target[0] - current[0]
        delta_cy = target[1] - current[1]
        print(f"Delta cx: {delta_cx}, Delta cy: {delta_cy}")
        steps_x, steps_y, steps_z = self.compute_stage_move(delta_cx, delta_cy)
        return (steps_x, steps_y, steps_z)
    
    def calculate_move_to_target_machine(self, current, target):
        "Coordinates are in dict with keys 'X', 'Y', and 'Z'"
        dX = target["X"] - current["X"]
        dY = target["Y"] - current["Y"]
        dZ = target["Z"] - current["Z"]
        return dX, dY, dZ

    def calculate_move_to_top_center(self, current,offset=150):
        target = (self.image_width//2, offset)
        print(f"-Applied offset: {offset} to target center at {target}")
        return self.calculate_move_to_target(current, target)

    def get_center_in_pixels(self):
        return self.image_width//2, self.image_height//2
    
    def convert_pixel_position_to_motor_steps(self, pixel_position,current_motor_position):
        """
        Converts the pixel position to motor steps. Assumes that the current machine 
        position is at the center of the image. The motor positions are in a dict with
        "X", "Y", and "Z" keys.
        """
        machine_pos = current_motor_position.copy()
        center = self.get_center_in_pixels()
        dX, dY, dZ = self.calculate_move_to_target(center, pixel_position)
        machine_pos["X"] += dX
        machine_pos["Y"] -= dY
        machine_pos["Z"] += dZ
        return machine_pos

    def calculate_velocity(self, t1, p1, t2, p2):
        """
        Calculates the velocity given two points in time and position.
        Position is given as a dict with "X", "Y", and "Z" keys.
        """
        delta_t = t2 - t1
        delta_p = {k: p2[k] - p1[k] for k in p1}
        for k in delta_p:
            delta_p[k] = abs(delta_p[k])
        velocity_axis = {k: delta_p[k] / delta_t for k in delta_p}
        velocity_total = math.sqrt(sum([v**2 for v in velocity_axis.values()]))
        return velocity_axis, velocity_total



class ImageAnalysisThread(QThread):
    # Define signals to send results back to the main thread
    # analysis_done = Signal(object,object,object,object)  # Send original, thresholded, and analyzed image and result
    analysis_done = Signal(object, object, object)  # Send original, and annotated image and detected level

    def __init__(self, image, offset, width, threshold, prominence, empty_cutoff, last_row, parent=None):
        super().__init__(parent)
        self.offset = offset
        self.width = width
        self.threshold = threshold
        self.prominence = prominence
        self.empty_cutoff = empty_cutoff
        self.last_row = last_row
        self.original_image = image
        self.annotated_image = None
        self.level_data = None

    def run(self):
        # Perform image analysis
        self.analyze_image()
        # Emit results
        self.analysis_done.emit(self.original_image, self.annotated_image, self.level_data)

    def find_printer_head(self,cur_img, threshold_value=50):
        """
        Given a current image, this function detects the printer head in the image.
        It returns the bounding box coordinates of the detected printer head.
        """
        cur_gray = cv2.cvtColor(cur_img, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(cur_gray, threshold_value, 255, cv2.THRESH_BINARY)

        # Find contours
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Filter contours based on area
        cnts = [c for c in cnts if cv2.contourArea(c) > 1000]
        # Filter contours based on location in the image
        cnts = [c for c in cnts if cv2.boundingRect(c)[0] > 100 and cv2.boundingRect(c)[0] < 400]

        if len(cnts) == 0:
            print("No contours found.")
            return None, None, None, None
        big = max(cnts, key=cv2.contourArea)
        # 3C) Get its bounding box (this is the full printer head)
        x, y, w, h = cv2.boundingRect(big)
        return x, y, w, h

    def get_channel_bounds(self,cur_img, x, y, w, h, left_offset=40, channel_width=30):
        """
        Given the bounding box coordinates of the printer head, this function identifies the channel area.
        It returns the bounding box coordinates of the detected channel area.
        """
        # Identify the channel area using the sides of the bounding box
        x0 = x + left_offset
        return x0, y, channel_width, h

    def get_channel_profile(self,image, x0, y0, w, h):
        """
        Extracts the channel profile from the image.
        """
        crop = image[y0:y0+h, x0:x0+w]              # 1. crop to channel  
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5,5), 0)    # 2. smooth out noise  

        profile = blur.mean(axis=1)
        return profile


    def detect_meniscus_row(self,profile,
                        last_row=None,
                        fluid_darker=True,
                        search_band=None,
                        min_prominence=8):
        """
        profile       : 1-D numpy array of mean‐intensities per row
        last_row      : previous detection (for temporal smoothing / disambiguation)
        fluid_darker  : True if liquid is darker than air (so meniscus is a downward step)
        search_band   : (row_min, row_max)  to restrict valid meniscus locations
        min_prominence: threshold to reject small bumps
        
        returns meniscus_row  (index into `profile` where the level sits)
        """
        # 1) gradient
        grad = np.diff(profile)

        # 2) orient so meniscus becomes a *peak* in `sig`
        sig = -grad if fluid_darker else grad

        # 3) find all peaks above a certain prominence
        peaks, props = find_peaks(sig, prominence=min_prominence)

        # 4) if we have a band, throw away peaks outside it
        if search_band is not None:
            lo, hi = search_band
            mask = (peaks >= lo) & (peaks < hi)
            peaks = peaks[mask]
            for k in list(props):
                props[k] = props[k][mask]

        # 5) if any candidates remain, pick best
        if len(peaks):
            # a) if tracking over time, pick the one nearest last_row
            if last_row is not None:
                idx = np.argmin(np.abs(peaks - last_row))
                # plt.plot(peaks[idx], sig[peaks[idx]], "o", color="red", label="Best Peak")
                # plt.show()
                return peaks[idx]
            # b) otherwise pick the most prominent
            best = np.argmax(props["prominences"])

            return peaks[best]
        if last_row is not None:
            if last_row < len(profile) -20 and last_row > 20 and min_prominence > 4:
                print(f"No peaks with {min_prominence}, trying again with {min_prominence-1}")
                # If we have a last row, we can try to find the meniscus row again with a lower prominence
                # This is useful if the meniscus is not very pronounced
                return self.detect_meniscus_row(profile,
                            last_row=last_row,
                            fluid_darker=fluid_darker,
                            search_band=search_band,
                            min_prominence=min_prominence-1)

        # 6) If no peaks were found, return None
        print("No peaks found")
        return None

    def check_fill_state(self,image,x0,y0,w0,h0,empty_cutoff=0.15):
        """
        When no peaks are found, this function checks the profile to determine if the channel is empty or full.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        square_start = y0 + h0 - w0 - 30
        square_end = square_start + w0
        channel_patch = gray[square_start:square_end, x0:x0+w0]
        reference_patch = gray[square_start:square_end, x0+w0+5:x0+2*w0+5]
        score, _ = ssim(channel_patch, reference_patch, full=True)
        print(f"SSIM score: {score}")

        if score < empty_cutoff:
            print("Channel is empty.")
            return h0 - 3
        else:
            print("Channel is full.")
            return 3

    def analyze_image(self):
        # self.original_image = cv2.rotate(self.original_image, cv2.ROTATE_180)
        # Rotate the image 90 degrees counter-clockwise
        self.original_image = cv2.rotate(self.original_image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        cur_img = self.original_image.copy()

        x,y,w,h = self.find_printer_head(cur_img, threshold_value=self.threshold)
        if x is None or y is None or w is None or h is None:
            print("Printer head not found, using default values")
            self.annotated_image = cur_img.copy()
            self.level_data = None
            return
        else:
            x0, y0, w0, h0 = self.get_channel_bounds(cur_img, x, y, w, h, left_offset=self.offset, channel_width=self.width)

        profile = self.get_channel_profile(cur_img, x0, y0, w0, h0)

        meniscus_row = self.detect_meniscus_row(profile,
                            last_row=self.last_row,
                            fluid_darker=False,
                            search_band=(0,h0-30),
                            min_prominence=self.prominence)

        if meniscus_row is None:
            meniscus_row = self.check_fill_state(cur_img, x0, y0, w0, h0, empty_cutoff=self.empty_cutoff)
        level_y = y0 + meniscus_row

        cv2.line(cur_img, (x0, level_y), (x0 + w0, level_y), (0, 0, 255), 2)  # Red line
        cv2.rectangle(cur_img, (x0, y0), (x0 + w0, y0 + h0), (255, 0, 0), 2)  # Blue rectangle
        # Draw the printer head bounding box
        cv2.rectangle(cur_img, (x, y), (x + w, y + h), (0, 255, 0), 2)  # Green rectangle

        self.annotated_image = cur_img.copy()

        # Calculate level data by calculating the difference between the meniscus row and the bottom of the channel
        self.level_data = h0 - meniscus_row

class RefuelCameraModel(QObject):
    '''
    Stores all the data from the refuel camera system
    '''
    update_level_ui_signal = Signal()
    # level_updated_signal = Signal()

    def __init__(self):
        super().__init__()
        print("Loaded New")
        self.offset = None
        self.width = None
        self.threshold = None
        self.prominence = None
        self.empty_cutoff = None

        self.current_level = None
        self.level_log = []
        self.stable = False
        self.original_image = None
        self.annotated_image = None

    def update_threshold(self, value):
        self.threshold_value = value

    def update_blur(self, value):
        self.blur_size = value

    def update_left_bound(self, value):
        self.left_bound = value

    def update_right_bound(self, value):
        self.right_bound = value

    def update_analysis_parameters(self, offset, width, threshold, prom, empty_cutoff):
        self.offset = offset
        self.width = width
        self.threshold = threshold
        self.prominence = prom
        self.empty_cutoff = empty_cutoff

    def update_current_level(self, level):
        self.current_level = level

    def start_analysis(self, frame):
        # Resize the image to fit within 640x480 while maintaining aspect ratio
        frame = cv2.resize(frame, (480, 640), interpolation=cv2.INTER_AREA)
        if len(self.level_log) > 0:
            last_level = self.level_log[-1]
        else:
            last_level = None
        self.analysis_thread = ImageAnalysisThread(frame, self.offset, self.width, self.threshold, self.prominence, self.empty_cutoff,last_level)
        self.analysis_thread.analysis_done.connect(self.update_ui_with_analysis)
        self.analysis_thread.start()

    # def update_ui_with_analysis(self, original_image, thresholded_image, level_image, level_data):
    def update_ui_with_analysis(self, original_image, annotated_image, level_data):
        # self.original_image = analyzed_images
        if original_image is not None:
            self.original_image = original_image
        if annotated_image is not None:
            self.annotated_image = annotated_image
        if level_data is not None:
            self.update_current_level(level_data)
            self.update_level_log(level_data)
        self.update_level_ui_signal.emit()

    def get_original_image(self):
        return self.original_image

    def get_annotated_image(self):
        return self.annotated_image

    def update_level_log(self,level):
        '''Add a new level to the existing log'''
        self.level_log.append(level)
        if len(self.level_log) > 100:
            self.level_log.pop(0)

    def get_level_log(self):
        return self.level_log

    def get_current_level(self):
        return self.current_level
        