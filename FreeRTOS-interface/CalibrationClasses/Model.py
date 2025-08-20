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
from collections import deque

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

    captureFailed = Signal(str)

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

    def _capture_with_policy(
        self,
        *,
        set_attr: str,                # attribute name to store frame (e.g., "background_image")
        stage_text: str,              # text for Stage display, e.g., "Capturing background image"
        attempts_total: int = 3,      # total number of tries (first + retries)
        retry_delay_ms: int = 75,     # delay between tries
        guard_timeout_ms: int = 10_000,  # hard guard for each try
        retry_stage_suffix: str = " (retry {i}/{n})",  # appended to stage text on retries
        on_success = None,  # called after setting the attribute (optional)
        on_final_failure = None,  # called after we exhaust attempts (optional)
        final_error_msg: str = "Image capture failed repeatedly."  # default error if no handler
    ):
        """
        Issue a capture request that will retry if the controller reports failure (frame=None).
        On success: setattr(self, set_attr, frame) and emit captureCompleted.
        On final failure: call on_final_failure() or emit calibrationError(final_error_msg).
        """

        # We track attempts in a small closure state
        state = {"attempt": 1}  # 1-based for user-friendly messages
        guard_timer_ref = {"t": None}  # so we can cancel from inner callback

        def _arm_one_attempt():
            # Stage text (with retry suffix after the first attempt)
            if state["attempt"] == 1:
                self.stageChanged.emit(stage_text)
            else:
                self.stageChanged.emit(stage_text + retry_stage_suffix.format(
                    i=state["attempt"], n=attempts_total
                ))

            # Start a guard timeout for this attempt
            guard_timer_ref["t"] = self._start_timeout(
                guard_timeout_ms,
                err_msg=None,  # we’ll treat it as a normal capture failure below
                on_timeout=lambda: _on_result(None)  # resolve like a failed capture
            )

            # Single-shot callback used by the controller
            def _on_result(frame):
                # Cancel the guard
                self._cancel_timeout(guard_timer_ref["t"])
                guard_timer_ref["t"] = None

                if frame is None:
                    # Failed this attempt
                    if state["attempt"] < attempts_total:
                        state["attempt"] += 1
                        # Schedule the next try
                        QTimer.singleShot(retry_delay_ms, _arm_one_attempt)
                        return
                    # Final failure
                    if on_final_failure is not None:
                        on_final_failure()
                    else:
                        self.calibrationError.emit(final_error_msg)
                    return

                # Success
                setattr(self, set_attr, frame)
                if on_success is not None:
                    try:
                        on_success(frame)
                    except Exception:
                        pass
                # Inform the state machine we’re done with this capture
                self.calibration_manager.emitCaptureCompleted()

            # Fire the request (controller will call _on_result with frame or None)
            self.calibration_manager.captureImageRequested.emit(_on_result)

        # Kick off the first attempt
        _arm_one_attempt()

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
    """
    Identify the nozzle by diffing background vs droplet image. If not found,
    scan a handful of longer flash delays; if still not found, raise pressure (clamped)
    and repeat the delay scan. Use the *top of the contour* as nozzle coordinate
    and move near the *top-center* of the frame. Verify and iterate with safety caps.
    """
    # Define signals to trigger transitions from analyze state.
    nozzleCentered = Signal()

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)

        self.phase_name = "nozzle_position"
        self.measurements = []  # Store (X, Y, Z) coordinates of machine and corresponding center XY positions in image.
        # Store captured images locally.
        self.background_image = None
        self.droplet_image = None

        # ---- Safety & search tuning ----
        # flash delay search (in microseconds), added to base (initial) delay
        self.initial_flash_delay_us = 3800
        self.delay_scan_increments = [0, 400, 800, 1200, 1600]   # try a few longer delays
        self.min_flash_delay_us = 0
        self.max_flash_delay_us = 12000

        # pressure search (psi)
        self.max_pressure_levels = 3          # total pressure levels: base + two bumps
        self.pressure_step = 0.1              # psi per bump
        self.min_print_pressure = 0.35        # safe fallback bounds if model doesn’t expose them
        self.max_print_pressure = 1.00

        # recenter loop guard
        self.max_recenter_iterations = 8
        self._recenter_iters = 0

        # movement clamp (motor steps). Adjust to your mechanics.
        self.max_xy_steps_per_correction = 1000

        # top-center target: x center, y near top
        self.top_margin_frac = 0.12           # ~12% down from top
        self.center_tol_frac = 0.03           # within 3% of width (x) and 3% of height (y band around target)
        self.top_band_frac   = 0.03

        # ---- internal scan state (reset in onPrepareDroplet) ----
        self._base_delay_us = self.initial_flash_delay_us
        self._delay_idx = 0
        self._base_pressure = None
        self._pressure_level = 0  # 0=base,1=+step,2=+2*step

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

                # Transitions
        t0 = QSignalTransition()
        t0.setSenderObject(self.calibration_manager)
        t0.setSignal(b"2moveCompleted()")
        t0.setTargetState(self.state_prepare_background)
        self.state_initial_position.addTransition(t0)

        t1 = QSignalTransition()
        t1.setSenderObject(self.calibration_manager)
        t1.setSignal(b"2settingsChangeCompleted()")
        t1.setTargetState(self.state_capture_background)
        self.state_prepare_background.addTransition(t1)

        t2 = QSignalTransition()
        t2.setSenderObject(self.calibration_manager)
        t2.setSignal(b"2captureCompleted()")
        t2.setTargetState(self.state_prepare_droplet)
        self.state_capture_background.addTransition(t2)

        t3 = QSignalTransition()
        t3.setSenderObject(self.calibration_manager)
        t3.setSignal(b"2settingsChangeCompleted()")
        t3.setTargetState(self.state_capture_droplet)
        self.state_prepare_droplet.addTransition(t3)

        t4 = QSignalTransition()
        t4.setSenderObject(self.calibration_manager)
        t4.setSignal(b"2captureCompleted()")
        t4.setTargetState(self.state_analyze)
        self.state_capture_droplet.addTransition(t4)

        # If we move, re-take background at the new location
        t5 = QSignalTransition()
        t5.setSenderObject(self.calibration_manager)
        t5.setSignal(b"2moveCompleted()")
        t5.setTargetState(self.state_prepare_background)
        self.state_analyze.addTransition(t5)

        # Success → final
        t6 = QSignalTransition()
        t6.setSenderObject(self)
        t6.setSignal(b"2nozzleCentered()")
        t6.setTargetState(self.state_final)
        self.state_analyze.addTransition(t6)

        # NEW: allow Analyze → Capture when we tweak settings (delay/pressure) for rescans
        t7 = QSignalTransition()
        t7.setSenderObject(self.calibration_manager)
        t7.setSignal(b"2settingsChangeCompleted()")
        t7.setTargetState(self.state_capture_droplet)
        self.state_analyze.addTransition(t7)

        self.state_machine.addState(self.state_initial_position)
        self.state_machine.addState(self.state_prepare_background)
        self.state_machine.addState(self.state_capture_background)
        self.state_machine.addState(self.state_prepare_droplet)
        self.state_machine.addState(self.state_capture_droplet)
        self.state_machine.addState(self.state_analyze)
        self.state_machine.addState(self.state_final)
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
            "flash_delay": int(self.initial_flash_delay_us)
        }
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureBackground(self):
        self._capture_with_policy(
            set_attr="background_image",
            stage_text="Capturing background image",
            attempts_total=3,
            retry_delay_ms=100,
            guard_timeout_ms=10_000,
            final_error_msg="Failed to capture background image."
        )

    @Slot()
    def onPrepareDroplet(self):
        # Reset the scan plan for this search loop
        self.stageChanged.emit("Preparing droplet capture (init scan plan)")
        self._base_delay_us = int(self.initial_flash_delay_us)
        self._delay_idx = 0
        self._base_pressure = float(self.model.machine_model.get_current_print_pressure())
        self._pressure_level = 0

        settings = {
            "num_droplets": 1,
            "flash_delay": int(self._clamp_delay(self._base_delay_us)),
            # don't force pressure yet; use whatever current pressure is for the first shot
        }
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureDroplet(self):
        # Slightly more aggressive retries for flash timing hiccups
        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text="Capturing droplet image",
            attempts_total=5,
            retry_delay_ms=75,
            guard_timeout_ms=10_000,
            final_error_msg="Failed to capture droplet image."
        )

    @Slot()
    def onAnalyze(self):
        self.stageChanged.emit("Analyzing diff to locate nozzle")
        bg, dr = self.background_image, self.droplet_image

        status, nozzle_px, n_contours, debug_img = self._detect_nozzle_point(bg, dr)
        if status == "OK":
            # success; move toward top-center
            if n_contours > 1:
                self.stageChanged.emit(f"Multiple contours found ({n_contours}); using top-most candidate.")

            self.presentImageSignal.emit(debug_img)
            self._recenter_or_finish(nozzle_px)
            return

        # Not found → advance scan plan: delays first, then pressure bumps (bounded)
        advanced, settings = self._advance_scan_plan()
        if not advanced:
            self.calibrationError.emit(
                "No droplet/nozzle detected after scanning delays and pressure levels."
            )
            return

        # Apply new settings and loop: Analyze -> (settingsChangeCompleted) -> CaptureDroplet -> Analyze
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    # def isCentered(self, center):
    #     img_width, img_height = self.model.droplet_camera_model.get_image_size()
    #     ideal_center = (img_width // 2, img_height // 2)
    #     tolerance = 0.01
    #     return (abs(center[0] - ideal_center[0]) <= tolerance * img_width and
    #             abs(center[1] - ideal_center[1]) <= tolerance * img_height)
    # ----------------- Helpers: detection & movement -----------------

    def _detect_nozzle_point(self, bg, dr):
        """
        Return (status, (x,y), n_contours, debug_img)
        status: "OK" or "NONE"
        (x,y):  (x_mid_of_bounding_box, top_y_of_contour) for the chosen candidate
        Robust diff with thresholding + morphology, then contour filtering.
        """
        if bg is None or dr is None:
            return ("NONE", None, 0, None)

        a = dr
        b = bg
        # diff → gray
        if a.ndim == 3 and a.shape[2] == 3:
            diff = cv2.absdiff(a, b)
            gray = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)
        else:
            diff = cv2.absdiff(a, b)
            gray = diff if diff.ndim == 2 else cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

        # denoise + threshold
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.count_nonzero(th) < 10:
            # fallback if Otsu gives almost nothing
            t = max(10, int(np.mean(blur) + 3 * np.std(blur)))
            _, th = cv2.threshold(blur, t, 255, cv2.THRESH_BINARY)

        # clean specks
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, k, iterations=1)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k, iterations=1)

        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            dbg = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
            return ("NONE", None, 0, dbg)

        # basic area filter
        areas = [cv2.contourArea(c) for c in contours]
        keep = [(c, a) for (c, a) in zip(contours, areas) if a >= 20]
        if not keep:
            dbg = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
            return ("NONE", None, 0, dbg)

        # choose the top-most contour (min y); tie-break by larger area
        def contour_top_y(contour):
            ys = contour[:, :, 1].flatten()
            return int(ys.min())

        keep_sorted = sorted(
            keep,
            key=lambda ca: (contour_top_y(ca[0]), -ca[1])
        )
        chosen, chosen_area = keep_sorted[0]
        n = len(keep)

        # compute top y from contour and horizontal middle from bounding box
        ys = chosen[:, :, 1].flatten()
        top_y = int(ys.min())

        x, y, w, h = cv2.boundingRect(chosen)
        mid_x = int(round(x + w / 2.0))

        nozzle_xy = (mid_x, top_y)

        # debug overlay
        if a.ndim == 3 and a.shape[2] == 3:
            dbg = a.copy()
        else:
            dbg = cv2.cvtColor(a, cv2.COLOR_GRAY2RGB)

        # contour and bbox
        cv2.drawContours(dbg, [chosen], -1, (0, 255, 0), 2)
        cv2.rectangle(dbg, (x, y), (x + w, y + h), (255, 165, 0), 1)  # orange box
        # top edge line + point
        cv2.line(dbg, (x, top_y), (x + w, top_y), (0, 200, 255), 1)
        cv2.circle(dbg, nozzle_xy, 4, (255, 0, 0), -1)  # chosen nozzle point

        return ("OK", nozzle_xy, n, dbg)

    def _recenter_or_finish(self, nozzle_px):
        img_w, img_h = self.model.droplet_camera_model.get_image_size()
        target = (img_w // 2, int(self.top_margin_frac * img_h))
        if self._is_top_centered(nozzle_px, (img_w, img_h), target):
            self.stageChanged.emit("Nozzle near top-center; done.")
            # record final machine position
            machine_pos = self.model.machine_model.get_current_position_dict()
            self.measurements.append((machine_pos, nozzle_px))
            self.nozzleCentered.emit()
            return

        # compute move vector from pixel→motor; clamp to avoid huge jumps
        move_vector = self.model.droplet_camera_model.calculate_move_to_target(nozzle_px, target)
        move_vector = self._clamp_move(move_vector)
        self.stageChanged.emit(f"Nozzle offset detected; moving by {move_vector}")
        self.calibration_manager.moveRequested.emit(move_vector, self.calibration_manager.emitMoveCompleted)
        self._recenter_iters += 1
        if self._recenter_iters > self.max_recenter_iterations:
            self.calibrationError.emit("Too many recenter attempts—aborting to avoid oscillation.")

    def _is_top_centered(self, pt, img_size, target):
        x, y = pt
        w, h = img_size
        tx, ty = target
        tol_x = self.center_tol_frac * w
        band_y = self.top_band_frac * h
        return (abs(x - tx) <= tol_x) and (abs(y - ty) <= band_y)

    def _clamp_move(self, mv):
        """Limit per-correction XY steps; keep Z unchanged (usually zero for this)."""
        try:
            dx, dy, dz = mv
        except Exception:
            # if model returns 2D, extend to 3D
            dx, dy = mv
            dz = 0
        cap = float(self.max_xy_steps_per_correction)
        dx = max(-cap, min(cap, float(dx)))
        dy = max(-cap, min(cap, float(dy)))
        return (dx, dy, dz)

    # ----------------- Helpers: scan plan & bounds -----------------

    def _advance_scan_plan(self):
        """
        Advance either to the next delay (same pressure) or bump pressure (reset delay).
        Returns (advanced: bool, settings: dict|None)
        """
        # next delay?
        if self._delay_idx + 1 < len(self.delay_scan_increments):
            self._delay_idx += 1
            new_delay = self._clamp_delay(self._base_delay_us + self.delay_scan_increments[self._delay_idx])
            self.stageChanged.emit(f"No contour; trying longer flash delay: {new_delay} µs (idx={self._delay_idx})")
            return True, {"num_droplets": 1, "flash_delay": int(new_delay)}
        # else try next pressure level (if any)
        if self._pressure_level + 1 < self.max_pressure_levels:
            self._pressure_level += 1
            self._delay_idx = 0
            new_pressure = self._clamp_pressure(self._base_pressure + self._pressure_level * self.pressure_step)
            new_delay = self._clamp_delay(self._base_delay_us)
            self.stageChanged.emit(
                f"No contour after delay scan; raising pressure to {new_pressure:.3f} psi and resetting delay to {new_delay} µs"
            )
            return True, {"num_droplets": 1, "flash_delay": int(new_delay), "print_pressure": float(new_pressure)}
        # out of options
        return False, None

    def _clamp_delay(self, us):
        us = int(max(self.min_flash_delay_us, min(self.max_flash_delay_us, us)))
        return us

    def _clamp_pressure(self, p):
        # If your model exposes min/max, prefer that:
        try:
            pmin = float(getattr(self.model.machine_model, "min_print_pressure", self.min_print_pressure))
            pmax = float(getattr(self.model.machine_model, "max_print_pressure", self.max_print_pressure))
        except Exception:
            pmin, pmax = self.min_print_pressure, self.max_print_pressure
        p_clamped = max(pmin, min(pmax, float(p)))
        if p_clamped != p:
            self.stageChanged.emit(f"Clamped print pressure from {p:.3f} to {p_clamped:.3f} psi")
        return p_clamped

    # ----------------- Capture callbacks -----------------

    def handleBackgroundCaptured(self, image):
        self.background_image = image
        self.calibration_manager.emitCaptureCompleted()

    def handleDropletCaptured(self, image):
        self.droplet_image = image
        self._cancel_timeout(getattr(self, "_cap_timeout", None))
        self._cap_timeout = None
        self.calibration_manager.emitCaptureCompleted()

class NozzleFocusCalibrationProcess(BaseCalibrationProcess):
    nozzleFocused = Signal()

    # --------- Tuning / Safety ---------
    FOCUS_AXIS = "Y"
    SAFE_SWEEP_STEPS = 500

    # (Raised defaults you tested)
    STEP_INIT = 16
    STEP_GROWTH = 1.6
    STEP_MIN = 4
    STEP_MAX = 128

    TENENGRAD_ABS_EPS = 1e5
    TENENGRAD_REL_EPS = 0.03

    MAX_EVALS = 60
    MIN_REFINE_EVALS = 8
    BRACKET_TOL = 1

    # Oscillation guard
    _OSC_HISTORY = 6  # keep last N targets for pattern detection

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)
        self.phase_name = "nozzle_focus"

        self.droplet_image = None
        self.background_image = None

        self.mode = "probe_dir"
        self.direction = +1
        self.step = self.STEP_INIT

        self.eval_count = 0
        self.refine_evals = 0

        self.best_focus = None
        self.best_pos = None
        self.prev_focus = None

        self._start_pos = None
        self._loY = None
        self._hiY = None

        self._prev_y = None
        self._prev_f = None
        self._last_y = None
        self._last_f = None

        self._lo_br_y = None
        self._lo_br_f = None
        self._hi_br_y = None
        self._hi_br_f = None

        self._last_mask = None
        self._last_bbox = None

        self.focus_curve = []

        # NEW: target history to detect ABAB oscillation
        self._targets = deque(maxlen=self._OSC_HISTORY)

        # --- state machine wiring (unchanged) ---
        self.state_capture = QState()
        self.state_analyze = QState()
        self.state_final   = QFinalState()

        self.state_capture.entered.connect(self.onCaptureDroplet)
        self.state_analyze.entered.connect(self.onAnalyze)
        self.state_final.entered.connect(self.onCalibrationCompleted)

        t_cap_done = QSignalTransition()
        t_cap_done.setSenderObject(self.calibration_manager)
        t_cap_done.setSignal(b"2captureCompleted()")
        t_cap_done.setTargetState(self.state_analyze)
        self.state_capture.addTransition(t_cap_done)

        t_move_done = QSignalTransition()
        t_move_done.setSenderObject(self.calibration_manager)
        t_move_done.setSignal(b"2moveCompleted()")
        t_move_done.setTargetState(self.state_capture)
        self.state_analyze.addTransition(t_move_done)

        t_focused = QSignalTransition()
        t_focused.setSenderObject(self)
        t_focused.setSignal(b"2nozzleFocused()")
        t_focused.setTargetState(self.state_final)
        self.state_analyze.addTransition(t_focused)

        self.state_machine.addState(self.state_capture)
        self.state_machine.addState(self.state_analyze)
        self.state_machine.addState(self.state_final)
        self.state_machine.setInitialState(self.state_capture)

    # ---------- capture ----------
    @Slot()
    def onCaptureDroplet(self):
        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text="Capturing focus frame",
            attempts_total=7,
            retry_delay_ms=75,
            guard_timeout_ms=12_000,
            final_error_msg="Failed to capture droplet for focus."
        )

    # ---------- analyze / drive search ----------
    @Slot()
    def onAnalyze(self):
        import numpy as np, cv2

        self.stageChanged.emit(f"Analyzing focus ({self.mode})")

        if self.background_image is None:
            self.background_image = self.calibration_manager.get_background_image()

        img = self.droplet_image
        if img is None:
            self._abort_with_error("No image to analyze (capture failed).")
            return

        mask = self._build_focus_mask(self.background_image, img) if self.background_image is not None else None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        focus = float(self.model.droplet_camera_model.compute_tenengrad_variance(gray, mask=mask))

        overlay = img.copy()
        self._draw_focus_overlay(overlay, mask, focus)
        self.presentImageSignal.emit(overlay)

        pos = self.model.machine_model.get_current_position_dict()
        Y = pos["Y"]
        if self._start_pos is None:
            self._start_pos = dict(pos)
            y0 = self._start_pos["Y"]
            self._loY = y0 - self.SAFE_SWEEP_STEPS
            self._hiY = y0 + self.SAFE_SWEEP_STEPS
            self.stageChanged.emit(f"Focus sweep bounds on Y: [{self._loY}, {self._hiY}]")

        self.eval_count += 1
        self.focus_curve.append((focus, pos["X"], pos["Y"], pos["Z"], int(self.step), self.mode))

        # update best
        if (self.best_focus is None) or (focus > self.best_focus):
            self.best_focus = focus
            self.best_pos = dict(pos)

        # hard eval caps
        if self.eval_count >= self.MAX_EVALS and self.mode != "refine":
            self.stageChanged.emit("Max evals reached (pre-refine) → refine around best.")
            self._seed_refine_from_best()
            self._refine_next()
            return
        if self.eval_count >= self.MAX_EVALS and self.mode == "refine":
            self.stageChanged.emit("Max evals reached → move to best & finish.")
            self._move_to_best_then_finish()
            return

        # ---------- probe_dir ----------
        if self.mode == "probe_dir":
            if self._prev_y is None:
                self._prev_y, self._prev_f = Y, focus
                self._move_to_Y_clamped(Y + self.step)
                return
            else:
                # at Y0+step
                if focus > self._prev_f + self._improve_eps(self._prev_f):
                    self.direction = +1
                    self._last_y, self._last_f = Y, focus
                    self.mode = "run_up"
                    self._run_up_next()
                    return
                else:
                    # try the other side
                    y0 = self._start_pos["Y"]
                    self.direction = -1
                    self._prev_y, self._prev_f = y0, self._prev_f
                    self._last_y, self._last_f = None, None
                    self._move_to_Y_clamped(y0 - self.step)
                    self.mode = "probe_dir_neg"
                    return

        if self.mode == "probe_dir_neg":
            if focus > self._prev_f + self._improve_eps(self._prev_f):
                self.direction = -1
                self._last_y, self._last_f = Y, focus
                self.mode = "run_up"
                self._run_up_next()
                return
            else:
                # start near peak → refine locally
                y0 = self._start_pos["Y"]
                a, b = y0 - self.step, y0 + self.step
                if a > b: a, b = b, a
                self._lo_br_y, self._hi_br_y = a, b
                self._lo_br_f = self._hi_br_f = None
                self.mode = "refine"
                self.refine_evals = 0
                self._refine_next()
                return

        # ---------- run_up ----------
        if self.mode == "run_up":
            if self._last_y is None:
                self._last_y, self._last_f = Y, focus
                self._run_up_next()
                return

            # decline → bracketed
            if focus < self._last_f - self._improve_eps(self._last_f):
                a_y, a_f = self._prev_y, self._prev_f
                b_y, b_f = Y, focus
                if a_y > b_y:
                    a_y, b_y = b_y, a_y
                    a_f, b_f = b_f, a_f
                self._lo_br_y, self._lo_br_f = a_y, a_f
                self._hi_br_y, self._hi_br_f = b_y, b_f
                self.stageChanged.emit("Peak bracketed → refine.")
                self.mode = "refine"
                self.refine_evals = 0
                self._refine_next()
                return

            # still improving
            self._prev_y, self._prev_f = self._last_y, self._last_f
            self._last_y, self._last_f = Y, focus
            self.step = min(self.STEP_MAX, max(self.STEP_MIN, int(round(self.step * self.STEP_GROWTH))))
            self._run_up_next()
            return

        # ---------- refine ----------
        if self.mode == "refine":
            self.refine_evals += 1

            # tighten bracket w.r.t. best_y
            best_y = self.best_pos["Y"] if self.best_pos else Y
            if best_y <= Y:
                if self._hi_br_y is None or Y < self._hi_br_y:
                    self._hi_br_y, self._hi_br_f = Y, focus
            if best_y >= Y:
                if self._lo_br_y is None or Y > self._lo_br_y:
                    self._lo_br_y, self._lo_br_f = Y, focus

            a = self._lo_br_y if self._lo_br_y is not None else Y
            b = self._hi_br_y if self._hi_br_y is not None else Y
            if a > b: a, b = b, a
            span = b - a
            plateau = (self.refine_evals >= self.MIN_REFINE_EVALS and self._recent_improvement_small())

            # NEW: oscillation & tight-span guards
            if self._is_oscillating() or (span <= 2*self.STEP_MIN and plateau):
                self.stageChanged.emit("Oscillation/tight-span detected → snap to best & finish.")
                self._move_to_best_then_finish()
                return

            # Bias the next probe toward the side **away from current side of best**
            # so we don't cross best every time.
            if Y <= best_y:
                # we are on/before best → sample between best and upper bound
                mid = int(round((best_y + b) / 2))
            else:
                # we are after best → sample between lower bound and best
                mid = int(round((a + best_y) / 2))

            # ensure we make progress: avoid equal-to-current or immediate repeat
            mid = self._avoid_revisit(mid, Y, a, b)

            self._move_to_Y_clamped(mid)
            return

        # fallback
        self.stageChanged.emit("Unexpected state; finishing at best.")
        self._move_to_best_then_finish()

    # ---------- finish ----------
    @Slot()
    def onCalibrationCompleted(self):
        if self.best_pos is None:
            self.best_pos = self._start_pos or self.model.machine_model.get_current_position_dict()

        final = dict(self.model.machine_model.get_current_position_dict())
        final["Y"] = self.best_pos["Y"]

        self.calibration_manager.set_nozzle_center(final)
        self.calibrationDataUpdated.emit({
            "measurements": self.focus_curve,
            "result": {"best_focus": self.best_focus, "best_position": final, "focus_axis": "Y"}
        })
        self.calibrationCompleted.emit()

    # ---------- helpers ----------
    def _abort_with_error(self, msg): self.stageChanged.emit(msg); self.calibrationError.emit(msg)

    def _improve_eps(self, ref: float) -> float:
        return max(self.TENENGRAD_ABS_EPS, self.TENENGRAD_REL_EPS * max(abs(ref), 1.0))

    def _recent_improvement_small(self) -> bool:
        if len(self.focus_curve) < 6: return False
        recent = [f for (f, *_) in self.focus_curve[-5:]]
        earlier = [f for (f, *_) in self.focus_curve[:-5]]
        if not earlier: return False
        latest_best = max(recent)
        older_best  = max(earlier)
        return (latest_best - older_best) < self._improve_eps(max(older_best, 1.0))

    def _seed_refine_from_best(self):
        yb = self.best_pos["Y"] if self.best_pos else self._start_pos["Y"]
        a = max(self._loY, yb - max(self.STEP_INIT, self.BRACKET_TOL))
        b = min(self._hiY, yb + max(self.STEP_INIT, self.BRACKET_TOL))
        if a > b: a, b = b, a
        self._lo_br_y, self._hi_br_y = int(a), int(b)
        self._lo_br_f = self._hi_br_f = None
        self.mode = "refine"
        self.refine_evals = 0

    def _run_up_next(self):
        cur = self.model.machine_model.get_current_position_dict()
        target = cur["Y"] + self.direction * self.step
        target = max(self._loY, min(self._hiY, target))
        if target == cur["Y"]:
            # hit a bound → refine around last two points
            a_y, a_f = self._prev_y, self._prev_f
            b_y, b_f = self._last_y, self._last_f
            if a_y is None or b_y is None:
                self._seed_refine_from_best()
            else:
                if a_y > b_y: a_y, b_y, a_f, b_f = b_y, a_y, b_f, a_f
                self._lo_br_y, self._lo_br_f = a_y, a_f
                self._hi_br_y, self._hi_br_f = b_y, b_f
                self.mode = "refine"
                self.refine_evals = 0
            self._refine_next()
            return
        self._move_to_Y_clamped(target)

    def _refine_next(self):
        a = self._lo_br_y if self._lo_br_y is not None else self.model.machine_model.get_current_position_dict()["Y"]
        b = self._hi_br_y if self._hi_br_y is not None else self.model.machine_model.get_current_position_dict()["Y"]
        if a > b: a, b = b, a
        mid = int(round((a + b) / 2))
        mid = self._avoid_revisit(mid, self.model.machine_model.get_current_position_dict()["Y"], a, b)
        self._move_to_Y_clamped(mid)

    def _move_to_best_then_finish(self):
        if self.best_pos is None:
            self.nozzleFocused.emit(); return
        cur = self.model.machine_model.get_current_position_dict()
        dY = self.best_pos["Y"] - cur["Y"]
        if dY == 0:
            self.nozzleFocused.emit(); return
        self.calibration_manager.moveRequested.emit((0, dY, 0), self.nozzleFocused.emit)

    def _move_to_Y_clamped(self, target_y: int):
        cur = self.model.machine_model.get_current_position_dict()
        tgt = int(max(self._loY, min(self._hiY, target_y)))
        dY = tgt - cur["Y"]
        # record proposed target for oscillation detection
        self._targets.append(tgt)

        if dY == 0:
            if self.mode == "refine":
                # try a one-side nudge toward farther bound
                a = self._lo_br_y if self._lo_br_y is not None else cur["Y"]
                b = self._hi_br_y if self._hi_br_y is not None else cur["Y"]
                alt = cur["Y"] + (self.STEP_MIN if (b - cur["Y"]) >= (cur["Y"] - a) else -self.STEP_MIN)
                alt = int(max(self._loY, min(self._hiY, alt)))
                if alt != cur["Y"] and (len(self._targets) < 2 or alt != self._targets[-2]):
                    self._targets.append(alt)
                    self.calibration_manager.moveRequested.emit((0, alt - cur["Y"], 0), self.calibration_manager.emitMoveCompleted)
                    return
                # nothing else to try → snap to best
                self._move_to_best_then_finish()
                return
            # pre-refine: just recapture
            self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)
            return

        self.calibration_manager.moveRequested.emit((0, dY, 0), self.calibration_manager.emitMoveCompleted)

    # ---- oscillation avoidance helpers ----
    def _avoid_revisit(self, candidate: int, current_y: int, a: int, b: int) -> int:
        """Keep the next target inside [a,b], not equal to current or last target; nudge if needed."""
        cand = int(max(a, min(b, candidate)))
        if cand == current_y or (len(self._targets) > 0 and cand == self._targets[-1]):
            # nudge toward farther side
            cand2 = current_y + (self.STEP_MIN if (b - current_y) >= (current_y - a) else -self.STEP_MIN)
            cand2 = int(max(a, min(b, cand2)))
            if cand2 != current_y:
                return cand2
        return cand

    def _is_oscillating(self) -> bool:
        """Detect ABAB or A…B…A…B pattern in the recent target sequence."""
        t = list(self._targets)
        if len(t) < 4: return False
        # ABAB check on last 4
        if t[-1] != t[-2] and t[-1] == t[-3] and t[-2] == t[-4]:
            return True
        # two-value flip over longer window
        last4 = t[-4:]
        if len(set(last4)) == 2 and (last4[0] == last4[2]) and (last4[1] == last4[3]):
            return True
        return False

    # ---- image/ROI helpers (unchanged from your working version) ----
    def _build_focus_mask(self, bg, dr):
        # ... (same as before) ...
        # import numpy as np, cv2
        try:
            a = dr; b = bg
            if a.ndim == 3 and a.shape[2] == 3:
                diff = cv2.absdiff(a, b)
                gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            else:
                diff = cv2.absdiff(a, b)
                gray = diff if diff.ndim == 2 else cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            if np.count_nonzero(th) < 20:
                t = max(15, int(np.mean(blur) + 3*np.std(blur)))
                _, th = cv2.threshold(blur, t, 255, cv2.THRESH_BINARY)
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            th = cv2.morphologyEx(th, cv2.MORPH_OPEN, k, iterations=1)
            th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k, iterations=1)
            contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours: self._last_bbox = None; self._last_mask = None; return None
            areas = [cv2.contourArea(c) for c in contours]
            keep = [(c, a_) for (c, a_) in zip(contours, areas) if a_ >= 20]
            if not keep: self._last_bbox = None; self._last_mask = None; return None
            def top_y(c): return int(c[:, :, 1].min())
            keep.sort(key=lambda ca: (top_y(ca[0]), -ca[1]))
            chosen, _ = keep[0]
            x, y, w, h = cv2.boundingRect(chosen)
            pad_x = max(6, int(round(0.25 * w)))
            pad_y = max(6, int(round(0.25 * h)))
            x0 = max(0, x - pad_x); y0 = max(0, y - pad_y)
            x1 = min(dr.shape[1] - 1, x + w + pad_x)
            y1 = min(dr.shape[0] - 1, y + h + pad_y)
            mask = np.zeros((dr.shape[0], dr.shape[1]), np.uint8)
            mask[y0:y1+1, x0:x1+1] = 255
            self._last_bbox = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
            self._last_mask = mask
            return mask
        except Exception:
            self._last_bbox = None
            self._last_mask = None
            return None

    def _draw_focus_overlay(self, img_bgr, mask, focus_value: float):
        # import cv2
        if self._last_bbox is not None:
            x, y, bw, bh = self._last_bbox
            cv2.rectangle(img_bgr, (x, y), (x + bw - 1, y + bh - 1), (0, 255, 0), 2)
        if mask is not None:
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(img_bgr, contours, -1, (255, 0, 255), 1)
        pos = self.model.machine_model.get_current_position_dict()
        lines = [
            f"Focus (Tenengrad): {focus_value:.0f}",
            f"Y: {pos['Y']}  step:{self.step}  mode:{self.mode}",
            f"Best: {self.best_focus:.0f}" if self.best_focus is not None else "Best: -",
        ]
        for i, line in enumerate(lines):
            cv2.putText(img_bgr, line, (8, 18 + i*18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 220, 20), 1, cv2.LINE_AA)

class DropletEmergenceCalibrationProcess(BaseCalibrationProcess):
    continueSearch = Signal()
    dropletDetected = Signal()

    # ---- tuning / safety ----
    DELAY_MIN = 1500          # μs hard clamp
    DELAY_MAX = 8000          # μs hard clamp
    COARSE_STEP = 300         # first-phase step
    FINE_STEP   = 60          # min bisection resolution before we stop trying to split hairs
    MAX_EVALS   = 32          # hard cap, including replicates
    REPLICATES  = 3           # median over replicates per delay
    STALL_DELTA = 20          # μs; if mid repeats, nudge by this

    # acceptable area band (target window)
    MIN_AREA = 1000
    MAX_AREA = 2000

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)
        self.phase_name = "droplet_emergence"

        # working vars
        self.background_image = None
        self.droplet_image = None

        self.lower_delay  = 2000
        self.upper_delay  = 5000
        self.candidate_delay = 3000

        self.min_area = self.MIN_AREA
        self.max_area = self.MAX_AREA

        self.measurements = []    # (delay, area)
        self._eval_count  = 0
        self._last_delay  = None

        # bracket: (delay, area) where area < min_area (low) and > max_area (high)
        self._lo = None   # tuple (d, area)
        self._hi = None   # tuple (d, area)

        # replicates buffer at current delay
        self._rep_areas = []

        # states
        self.state_prepare_background = QState()
        self.state_capture_background = QState()
        self.state_set_delay          = QState()
        self.state_capture_droplet    = QState()
        self.state_analyze            = QState()
        self.state_final              = QFinalState()

        self.state_prepare_background.entered.connect(self.onPrepareBackground)
        self.state_capture_background.entered.connect(self.onCaptureBackground)
        self.state_set_delay.entered.connect(self.onSetDelay)
        self.state_capture_droplet.entered.connect(self.onCaptureDroplet)
        self.state_analyze.entered.connect(self.onAnalyze)
        self.state_final.entered.connect(self.onCalibrationCompleted)

        t0 = QSignalTransition(); t0.setSenderObject(self.calibration_manager); t0.setSignal(b"2settingsChangeCompleted()"); t0.setTargetState(self.state_capture_background)
        self.state_prepare_background.addTransition(t0)

        t1 = QSignalTransition(); t1.setSenderObject(self.calibration_manager); t1.setSignal(b"2captureCompleted()"); t1.setTargetState(self.state_set_delay)
        self.state_capture_background.addTransition(t1)

        t2 = QSignalTransition(); t2.setSenderObject(self.calibration_manager); t2.setSignal(b"2settingsChangeCompleted()"); t2.setTargetState(self.state_capture_droplet)
        self.state_set_delay.addTransition(t2)

        t3 = QSignalTransition(); t3.setSenderObject(self.calibration_manager); t3.setSignal(b"2captureCompleted()"); t3.setTargetState(self.state_analyze)
        self.state_capture_droplet.addTransition(t3)

        t4 = QSignalTransition(); t4.setSenderObject(self); t4.setSignal(b"2dropletDetected()"); t4.setTargetState(self.state_final)
        self.state_analyze.addTransition(t4)

        t5 = QSignalTransition(); t5.setSenderObject(self); t5.setSignal(b"2continueSearch()"); t5.setTargetState(self.state_set_delay)
        self.state_analyze.addTransition(t5)

        self.state_machine.addState(self.state_prepare_background)
        self.state_machine.addState(self.state_capture_background)
        self.state_machine.addState(self.state_set_delay)
        self.state_machine.addState(self.state_capture_droplet)
        self.state_machine.addState(self.state_analyze)
        self.state_machine.addState(self.state_final)
        self.state_machine.setInitialState(self.state_prepare_background)

    # ---------- phases ----------

    @Slot()
    def onPrepareBackground(self):
        self.stageChanged.emit("Preparing background image")
        self._eval_count = 0
        self._lo = None; self._hi = None
        self._last_delay = None
        self._rep_areas.clear()

        # keep your current nozzle/pressure settings; ensure 0 drops
        settings = {"num_droplets": 0}
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureBackground(self):
        self._capture_with_policy(
            set_attr="background_image",
            stage_text="Capturing background image",
            attempts_total=3,
            retry_delay_ms=100,
            guard_timeout_ms=10_000,
            final_error_msg="Failed to capture background image."
        )

    @Slot()
    def onSetDelay(self):
        d = int(self._clamp_delay(self.candidate_delay))
        self.candidate_delay = d
        self.stageChanged.emit(f"Setting flash delay to {d} μs (lo={self._lo}, hi={self._hi})")
        settings = {"flash_delay": d, "num_droplets": 1}
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onCaptureDroplet(self):
        # median over a few replicates at the same delay
        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text=f"Capturing droplet @ {self.candidate_delay} μs (rep {len(self._rep_areas)+1}/{self.REPLICATES})",
            attempts_total=5,
            retry_delay_ms=75,
            guard_timeout_ms=10_000,
            final_error_msg=f"Failed to capture droplet at {self.candidate_delay} μs."
        )

    @Slot()
    def onAnalyze(self):
        # measure area
        area, center, overlay = self.model.droplet_camera_model.calc_emergence_area(self.background_image, self.droplet_image)
        self.presentImageSignal.emit(overlay)
        self._eval_count += 1

        # treat "no contour" as zero area (still valid info)
        if area is None:
            area = 0

        self._rep_areas.append(area)
        self.stageChanged.emit(f"Delay {self.candidate_delay} μs replicate → area {area}")

        # collect replicates
        if len(self._rep_areas) < self.REPLICATES:
            # request another capture at the *same* delay
            self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)
            return

        # aggregate
        agg_area = int(median(self._rep_areas))
        self._rep_areas.clear()
        self.measurements.append((self.candidate_delay, agg_area))
        self.stageChanged.emit(f"Delay {self.candidate_delay} μs → median area {agg_area}")

        # classify
        cls = self._classify(agg_area)
        if cls == "TARGET":
            self.stageChanged.emit("Target area reached")
            # store result; consumers read via calibration file
            self.calibrationDataUpdated.emit({'measurements': self.measurements,
                                              'result': {'area': agg_area, 'flash_delay': self.candidate_delay}})
            self.dropletDetected.emit()
            return

        # update bracket
        if cls == "LOW":
            self._lo = (self.candidate_delay, agg_area)
        else:  # "HIGH"
            self._hi = (self.candidate_delay, agg_area)

        # try to ensure we *have* a bracket; expand if needed
        if self._lo is None and self._hi is None:
            # first datapoint → step up or down based on class
            step = self._adaptive_step(cls, agg_area)
            self._set_next_delay(self.candidate_delay + (step if cls == "LOW" else -step))
        elif self._lo is None:
            # have only HIGH → step downward to find LOW
            step = self._adaptive_step("HIGH", agg_area)
            self._set_next_delay(self.candidate_delay - step)
        elif self._hi is None:
            # have only LOW → step upward to find HIGH
            step = self._adaptive_step("LOW", agg_area)
            self._set_next_delay(self.candidate_delay + step)
        else:
            # refine (bisection), with anti-stall nudge
            d_lo, _ = self._lo; d_hi, _ = self._hi
            if d_hi < d_lo:
                d_lo, d_hi = d_hi, d_lo
            width = d_hi - d_lo

            if width <= self.FINE_STEP:
                # close enough—pick the side whose area is nearer the window edge
                chosen = d_lo if abs(self._lo[1] - self.min_area) < abs(self._hi[1] - self.max_area) else d_hi
                self.candidate_delay = int(self._clamp_delay(chosen))
                self.stageChanged.emit("Bracket tight; taking best boundary and finishing as TARGET-ish.")
                self.calibrationDataUpdated.emit({'measurements': self.measurements,
                                                  'result': {'area': agg_area, 'flash_delay': self.candidate_delay}})
                self.dropletDetected.emit()
                return

            mid = (d_lo + d_hi) // 2
            if self._last_delay is not None and mid == self._last_delay:
                mid = mid + (self.STALL_DELTA if cls == "LOW" else -self.STALL_DELTA)
            self._set_next_delay(mid)

        # safety caps
        if self._eval_count >= self.MAX_EVALS:
            self.calibrationError.emit("Emergence search did not converge (max evaluations)")
            return

        self.emitContinueSearch()

    # ---------- completion ----------
    @Slot()
    def onCalibrationCompleted(self):
        self.stageChanged.emit("Droplet emergence calibration complete")
        self.calibrationCompleted.emit()

    # ---------- helpers ----------

    def handleDropletCaptured(self, img):
        # Base _capture_with_policy sets attribute; we just re-emit captureCompleted
        self.calibration_manager.emitCaptureCompleted()

    def _classify(self, area:int) -> str:
        if area < self.min_area:      return "LOW"
        if area > self.max_area:      return "HIGH"
        return "TARGET"

    def _adaptive_step(self, cls:str, area:int) -> int:
        """
        Adapt step based on how far we are from the window (in 'area' units).
        Converts that to a delay step using coarse heuristic (monotonic area↑ with delay↑).
        """
        # rough scaling: relative distance to window edges
        if cls == "LOW":
            frac = 1.0 if self.min_area <= 0 else min(2.0, max(0.2, (self.min_area - area) / max(self.min_area, 1)))
            step = int(round(self.COARSE_STEP * frac))
        elif cls == "HIGH":
            frac = 1.0 if self.max_area <= 0 else min(2.0, max(0.2, (area - self.max_area) / max(self.max_area, 1)))
            step = int(round(self.COARSE_STEP * frac))
        else:
            step = self.FINE_STEP
        return max(self.FINE_STEP, min(4*self.COARSE_STEP, step))

    def _set_next_delay(self, d:int):
        d = int(self._clamp_delay(d))
        # avoid exact repeats if we can (nudge by FINE_STEP)
        if self._last_delay is not None and d == self._last_delay:
            d = int(self._clamp_delay(d + (self.FINE_STEP if d + self.FINE_STEP <= self.DELAY_MAX else -self.FINE_STEP)))
        self._last_delay = self.candidate_delay
        self.candidate_delay = d
        self.stageChanged.emit(f"Next candidate delay: {self.candidate_delay} μs")

    def _clamp_delay(self, d:int) -> int:
        return max(self.DELAY_MIN, min(self.DELAY_MAX, int(d)))
    
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

        # ----- adaptive step & anti-oscillation tuning -----
        self.pw_ref_us = 1500            # reference PW for scaling coarse step
        self.min_step  = max(0.5*self.fine_step, 0.005)  # psi, floor for adaptive step
        self.max_step  = max(self.coarse_step, 0.15)     # psi, ceiling for adaptive step

        # when we flip across the boundary (e.g., TOO_LOW ↔ NEAR) in bracket phase,
        # immediately switch to REFINE using these bounds
        self._last_outcome  = None
        self._last_pressure = None

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
        self._capture_with_policy(
            set_attr="background_image",
            stage_text="Capturing background image",
            attempts_total=3,
            retry_delay_ms=100,
            guard_timeout_ms=10_000,
            final_error_msg="Failed to capture background image."
        )

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
        self._capture_with_policy(
            set_attr="nozzle_image",
            stage_text="Capturing nozzle image",
            attempts_total=3,
            retry_delay_ms=100,
            guard_timeout_ms=10_000,
            final_error_msg="Failed to capture nozzle image."
        )

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
        # For emergence, misses can happen; retry a bit more before we bail.
        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text=f"Capturing droplet image at {self.candidate_pressure} psi",
            attempts_total=5,
            retry_delay_ms=75,
            guard_timeout_ms=10_000,
            final_error_msg=(
                f"Failed to capture droplet at pressure={self.candidate_pressure} psi. "
                "Try widening exposure or checking flash timing."
            )
        )

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
        
    def _pw_scaled_coarse(self) -> float:
        """Shrink coarse step at higher pulse widths (where pressure is 'more sensitive')."""
        try:
            pw = max(int(self.model.machine_model.get_print_pulse_width()), 1)
        except Exception:
            pw = self.pw_ref_us
        # scale ~ 1/sqrt(PW); clamp so we don't go crazy small/large
        scale = (self.pw_ref_us / float(pw)) ** 0.5
        scale = max(0.25, min(2.0, scale))
        return self.coarse_step * scale
    
    def _adaptive_step(self, outcome: str, nozzle_area) -> float:
        """
        Outcome-informed step:
        - TOO_LOW:
            very low area  -> big step up
            low area       -> medium step up
            near threshold -> small step up
        - ACCEPTABLE/BORDERLINE: small/medium step up (still bracketing)
        - NEAR: small step down (close above boundary)
        - TOO_HIGH: medium/big step down
        """
        base = self._pw_scaled_coarse()

        # compute bands once
        low_band  = self.nozzle_droplet_threshold * (1.0 - self.hysteresis_frac)
        high_band = self.nozzle_droplet_threshold * (1.0 + self.hysteresis_frac)
        area = 0.0 if nozzle_area is None else float(nozzle_area)

        if outcome == "TOO_LOW":
            # how "dry" is the nozzle?
            if area < 0.5 * low_band:      mult = 1.6    # far below → bigger push
            elif area < 0.9 * low_band:    mult = 1.0    # moderately below
            else:                          mult = 0.6    # almost there → smaller step
        elif outcome in ("ACCEPTABLE", "BORDERLINE"):
            mult = 0.8                      # keep moving up, but gently
        elif outcome == "NEAR":
            mult = 0.5                      # just above acceptable → small step down
        elif outcome == "TOO_HIGH":
            # if we ever see >=2, we're clearly high
            mult = 1.3
        else:
            mult = 1.0

        step = base * mult
        # clamp to configured bounds
        return max(self.min_step, min(self.max_step, step))

    def _switch_to_refine(self, lo: float, hi: float):
        """Enter refine with [lo, hi] and jump to the midpoint."""
        self.bracket_lo = max(self.lower_pressure, min(self.upper_pressure, lo))
        self.bracket_hi = max(self.lower_pressure, min(self.upper_pressure, hi))
        if self.bracket_lo > self.bracket_hi:
            self.bracket_lo, self.bracket_hi = self.bracket_hi, self.bracket_lo
        self.phase = "refine"
        self.candidate_pressure = 0.5 * (self.bracket_lo + self.bracket_hi)
        print(f"[P-Cal] Anti-oscillation → REFINE: lo={self.bracket_lo:.3f} hi={self.bracket_hi:.3f} "
            f"mid={self.candidate_pressure:.3f}")
        self.emitContinueSearch()
        self.counter += 1

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
        acceptable = (outcome in ("ACCEPTABLE", "BORDERLINE"))
        one_drop   = (outcome in ("ACCEPTABLE", "BORDERLINE", "NEAR"))

        if acceptable:
            self.last_acceptable_pressure = self.candidate_pressure

        # SNAPSHOTS for anti-oscillation logic
        prev_outcome  = self._last_outcome
        prev_pressure = self._last_pressure
        tested_pressure = self.candidate_pressure  # the pressure we just evaluated
        print(f"\n\n[P-Cal] - new measurement: P={tested_pressure:.3f}, count={agg_count}, area={agg_area}")

        # --------- Anti-oscillation guard (BRACKET only) ----------
        # If we flip across the boundary in back-to-back steps (TOO_LOW ↔ NEAR/TOO_HIGH),
        # stop coarse stepping and enter REFINE immediately with those two points.
        if self.phase == "bracket" and self._last_outcome is not None:
            flipped_low_to_highish = (self._last_outcome == "TOO_LOW" and outcome in ("NEAR", "TOO_HIGH"))
            flipped_highish_to_low = (self._last_outcome in ("NEAR", "TOO_HIGH") and outcome == "TOO_LOW")
            if flipped_low_to_highish or flipped_highish_to_low:
                lo = self.last_too_low_pressure if self.last_too_low_pressure is not None else (
                    min(prev_pressure, tested_pressure))
                hi = max(prev_pressure, tested_pressure)
                self._switch_to_refine(lo, hi)
                # update "last" bookkeeping and return
                self._last_outcome  = outcome
                self._last_pressure = tested_pressure
                if self.counter >= self.max_iterations:
                    self.calibrationError.emit("Pressure search did not converge (anti-oscillation)")
                return

        # -------------------- Phase 1: BRACKET --------------------
        if self.phase == "bracket":
            if outcome == "TOO_LOW":
                self.last_too_low_pressure = tested_pressure
                step = self._adaptive_step(outcome, agg_area)
                self.candidate_pressure = self._clamp(tested_pressure + step)
                print(f"[P-Cal] TOO_LOW → +{step:.3f} → {self.candidate_pressure:.3f}")
                self.emitContinueSearch()
                self.counter += 1
                if self.counter >= self.max_iterations:
                    self.calibrationError.emit("Pressure search did not converge (too low region)")
                self._last_outcome  = outcome
                self._last_pressure = tested_pressure
                return

            if acceptable:
                # keep the *highest acceptable* as lo; continue stepping up, but adaptively
                if (self.bracket_lo is None) or (tested_pressure > self.bracket_lo):
                    self.bracket_lo = tested_pressure
                step = self._adaptive_step(outcome, agg_area)
                self.candidate_pressure = self._clamp(tested_pressure + step)
                print(f"[P-Cal] {outcome} → +{step:.3f} → {self.candidate_pressure:.3f} (lo={self.bracket_lo:.3f})")
                self.emitContinueSearch()
                self.counter += 1
                if self.counter >= self.max_iterations:
                    self.calibrationError.emit("Pressure search did not converge (bracket acceptable climb)")
                self._last_outcome  = outcome
                self._last_pressure = self.candidate_pressure
                return

            # outcome == NEAR or TOO_HIGH → we’re at/above the upper boundary
            self.bracket_hi = tested_pressure
            if self.bracket_lo is None:
                # No acceptable yet: if we have a recorded TOO_LOW, use it; otherwise step down adaptively.
                if self.last_too_low_pressure is not None:
                    self._switch_to_refine(self.last_too_low_pressure, self.bracket_hi)
                else:
                    step = self._adaptive_step(outcome, agg_area)
                    self.candidate_pressure = self._clamp(tested_pressure - step)
                    print(f"[P-Cal] {outcome} (no lo yet) → -{step:.3f} → {self.candidate_pressure:.3f}")
                    self.emitContinueSearch()
                    self.counter += 1
                    if self.counter >= self.max_iterations:
                        self.calibrationError.emit("Pressure search did not converge (no acceptable found)")
                self._last_outcome  = outcome
                self._last_pressure = tested_pressure
                return

            # We have both lo and hi → enter REFINE right away.
            self._switch_to_refine(self.bracket_lo, self.bracket_hi)
            self._last_outcome  = outcome
            self._last_pressure = self.candidate_pressure
            if self.counter >= self.max_iterations:
                self.calibrationError.emit("Pressure search did not converge (switching to refine)")
            return

        # -------------------- Phase 2: REFINE (bisection to highest acceptable) --------------------
        if self.phase == "refine":
            if outcome in ("ACCEPTABLE", "BORDERLINE", "TOO_LOW"):
                # too low or acceptable → move lower bound up (we are below/at boundary)
                self.bracket_lo = (tested_pressure if self.bracket_lo is None
                                   else max(self.bracket_lo, tested_pressure))
                print(f"[P-Cal] REFINE: lo={self.bracket_lo:.3f}")
            else:
                # NEAR or TOO_HIGH → move upper bound down
                self.bracket_hi = (tested_pressure if self.bracket_hi is None
                                   else min(self.bracket_hi, tested_pressure))
                print(f"[P-Cal] REFINE: hi={self.bracket_hi:.3f}")
            # if acceptable:
            #     self.bracket_lo = max(self.bracket_lo, self.candidate_pressure) if self.bracket_lo is not None else self.candidate_pressure
            # else:
            #     self.bracket_hi = min(self.bracket_hi, self.candidate_pressure) if self.bracket_hi is not None else self.candidate_pressure

            if (self.bracket_lo is not None) and (self.bracket_hi is not None):
                gap = self.bracket_hi - self.bracket_lo
                print(f"[P-Cal] REFINE: lo={self.bracket_lo:.3f} hi={self.bracket_hi:.3f} gap={gap:.4f}")
                if gap <= self.pressure_threshold:
                    if self.last_acceptable_pressure is None:
                        self.calibrationError.emit(
                            "Pressure search narrowed but never observed a valid single-droplet condition."
                        )
                        return
                    # return the HIGHEST acceptable
                    self.candidate_pressure = self.bracket_lo
                    self.final_condition_found = True
                    self.stageChanged.emit("Final condition found (bisection → highest acceptable)")
                    self.calibrationDataUpdated.emit({
                        'measurements': self.measurements,
                        'result': {'pressure': self.candidate_pressure}
                    })
                    self.emitDropletDetected()
                    return

                self.candidate_pressure = 0.5 * (self.bracket_lo + self.bracket_hi)
                print(f"[P-Cal] Next mid={self.candidate_pressure:.3f}")
                self.emitContinueSearch()
                self.counter += 1
                if self.counter >= self.max_iterations:
                    # Prefer a real acceptable result if we have one; otherwise error
                    if self.last_acceptable_pressure is not None:
                        self.candidate_pressure = self.last_acceptable_pressure
                        self.final_condition_found = True
                        self.emitDropletDetected()
                    else:
                        self.calibrationError.emit("Pressure search did not converge (refine phase)")
                    # if self.bracket_lo is not None:
                    #     self.candidate_pressure = self.bracket_lo
                    #     self.final_condition_found = True
                    #     self.emitDropletDetected()
                    # else:
                    #     self.calibrationError.emit("Pressure search did not converge (refine phase)")
                self._last_outcome  = outcome
                self._last_pressure = tested_pressure
                return

        # Bookkeeping if we somehow fell through
        self._last_outcome  = outcome
        self._last_pressure = tested_pressure

    @Slot()
    def onCalibrationCompleted(self):
        self.stageChanged.emit("Pressure calibration complete")
        self.calibrationDataUpdated.emit({'measurements': self.measurements, 'result': {'pressure': self.candidate_pressure}})
        self.calibrationCompleted.emit()

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
    # @Slot()
    # def onCaptureDroplet(self):
    #     self.stageChanged.emit(f"Capturing droplet image {self.image_counter + 1} of {self.num_images}")
    #     self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)
    
    @Slot()
    def onCaptureDroplet(self):
        # Slightly more aggressive retries for flash timing hiccups
        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text=f"Capturing droplet image {self.image_counter + 1} of {self.num_images}",
            attempts_total=5,
            retry_delay_ms=75,
            guard_timeout_ms=10_000,
            final_error_msg="Failed to capture droplet image."
        )

    # def handleDropletCaptured(self, image):
    #     self.droplet_image = image
    #     self.calibration_manager.emitCaptureCompleted()
    
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

    # @Slot()
    # def onCaptureBackground(self):
    #     self.stageChanged.emit("Capturing background image")
    #     self.calibration_manager.captureImageRequested.emit(self.handleBackgroundCaptured)

    @Slot()
    def onCaptureBackground(self):
        # One line: capture, retry a little, store to self.background_image
        self._capture_with_policy(
            set_attr="background_image",
            stage_text="Capturing background image",
            attempts_total=3,
            retry_delay_ms=100,
            guard_timeout_ms=10_000,
            final_error_msg="Failed to capture background image."
        )

    @Slot()
    def onSetDelay(self):
        # The flash delay for droplet imaging is set to the delay used in the pressure calibration.
        self.stageChanged.emit(f"Setting flash delay to {self.current_delay} μs")
        settings = {"flash_delay": self.current_delay, "num_droplets": 1}
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    # @Slot()
    # def onCaptureDroplet(self):
    #     self.stageChanged.emit("Capturing droplet image at set delay")
    #     self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)

    @Slot()
    def onCaptureDroplet(self):
        # For emergence, misses can happen; retry a bit more before we bail.
        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text=f"Capturing droplet image at {self.current_delay} μs",
            attempts_total=5,
            retry_delay_ms=75,
            guard_timeout_ms=10_000,
            final_error_msg=(
                f"Failed to capture droplet at delay={self.current_delay} μs. "
                "Try widening exposure or checking flash timing."
            )
        )

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

    # def handleBackgroundCaptured(self, image):
    #     self.background_image = image
    #     self.calibration_manager.emitCaptureCompleted()

    # def handleDropletCaptured(self, image):
    #     self.droplet_image = image
    #     self.calibration_manager.emitCaptureCompleted()

    # def handleNozzleCaptured(self, image):
    #     self.nozzle_image = image
    #     self.calibration_manager.emitCaptureCompleted()

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
        # Compute the gradient magnitude squared
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
    
    def calc_emergence_area(self, background, image):
        """
        Robustly estimate emergence 'size' at a delay:
          - abs diff, Otsu threshold fallback, morphology cleanup
          - choose *top-most* external contour (most likely the nozzle/droplet)
          - return bounding-rect area, bbox center, and an overlay image
        Returns: (area:int|None, center:(x,y)|None, overlay_bgr)
        """
        import numpy as np, cv2
        if background is None or image is None:
            return None, None, image

        # diff → gray
        if image.ndim == 3 and image.shape[2] == 3:
            diff = cv2.absdiff(image, background)
            gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        else:
            diff = cv2.absdiff(image, background)
            gray = diff if diff.ndim == 2 else cv2.cvtColor(diff, cv2.COLOR_GRAY2BGR)
            gray = gray if gray.ndim == 2 else cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        # Otsu; fallback to mean+3σ if too few pixels
        _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.count_nonzero(th) < 20:
            t = max(15, int(np.mean(blur) + 3*np.std(blur)))
            _, th = cv2.threshold(blur, t, 255, cv2.THRESH_BINARY)

        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN,  k, iterations=1)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k, iterations=1)

        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, None, image

        # pick the *top-most* contour (min y of its points), break ties by larger area
        def top_y(c): return int(c[:,:,1].min())
        areas = [cv2.contourArea(c) for c in contours]
        keep  = [(c, a) for (c, a) in zip(contours, areas) if a >= 20]
        if not keep:
            return None, None, image
        keep.sort(key=lambda ca: (top_y(ca[0]), -ca[1]))
        chosen, _ = keep[0]

        x, y, w, h = cv2.boundingRect(chosen)
        area = int(w*h)
        center = (x + w//2, y + h//2)

        # overlay
        overlay = image.copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        cv2.drawContours(overlay, [chosen], -1, (0,255,0), 2)
        cv2.rectangle(overlay, (x,y), (x+w, y+h), (255,0,0), 2)
        cv2.putText(overlay, f'Area: {area}', (x+w+5, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (50,200,50), 2)

        return area, center, overlay

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
        