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

import os, json, time, uuid, tempfile, threading
import numpy as np

# ---- numpy encoder helper (robust JSON) ----
def numpy_encoder(obj):
    try:
        import numpy as _np
        if isinstance(obj, (_np.integer,)):
            return int(obj)
        if isinstance(obj, (_np.floating,)):
            return float(obj)
        if isinstance(obj, _np.ndarray):
            return obj.tolist()
    except Exception:
        pass
    # Allow datetime-like, etc.
    try:
        return obj.__json__()
    except Exception:
        pass
    return str(obj)


class CalibrationManager(QObject):
    calibrationStageChanged = Signal(str, str)  # (message, color_name)
    calibrationCompleted = Signal()
    calibrationError = Signal(str)
    calibrationQueueCompleted = Signal()

    analyzedImageUpdated = Signal(object)

    captureImageRequested = Signal(object)       # callback(image)
    moveRequested = Signal(object, object)       # (move_vector, callback)
    moveAbsoluteRequested = Signal(object, object)
    changeSettingsRequested = Signal(dict, object)

    settingsChangeCompleted = Signal()
    captureCompleted = Signal()
    moveCompleted = Signal()

    captureFailed = Signal(str)
    position_diff_dict_signal = Signal(dict, dict)

    # Map alternate phase names to canonical keys
    PHASE_ALIASES = {
        "pressure": "pressure_calibration",
        "pressure_calibration": "pressure_calibration",
        "nozzle": "nozzle_position",
        "nozzle_position": "nozzle_position",
        "nozzle_focus": "nozzle_focus",
        "droplet_emergence": "droplet_emergence",
        "trajectory": "trajectory",
        "droplet_search": "droplet_search",
    }

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.activeCalibration = None
        self.model = model

        # Persisted JSON
        self._lock = threading.Lock()
        self.data = {"schema_version": 1, "runs": []}
        self.calibration_file_path = None

        # Current run envelope
        self._run_id = None
        self._run_idx = None

        # Cross-step ephemeral cache (images, etc.)
        self.background_image = None
        self.nozzle_center = None
        self.nozzle_center_image_position = None
        self.droplet_trajectory_vector = None
        self.trajectory_delay = None
        self.min_start_delay = None
        self.intermediate_droplet_position = None

        self.calibration_queue = []

        self.model.machine_state_updated.connect(self.update_offsets_from_nozzle)

    # ------------- Session / File management -------------

    def begin_session(self, calibration_file_path: str, notes: str = None):
        """
        Start a new calibration run under the given directory.
        Creates/loads calibration.json and opens a new run envelope
        including printer head + stock solution metadata.
        """
        # print(f"Starting calibration session in {experiment_dir}")
        # if not os.path.exists(experiment_dir):
        #     os.makedirs(experiment_dir, exist_ok=True)
        self.calibration_file_path = calibration_file_path
        print(f"Calibration file path: {self.calibration_file_path}")
        # Load if exists
        if os.path.exists(self.calibration_file_path):
            try:
                with open(self.calibration_file_path, "r") as f:
                    self.data = json.load(f)
            except Exception:
                # Corrupted? Keep a backup and start fresh structure
                backup = self.calibration_file_path + ".corrupt." + time.strftime("%Y%m%d-%H%M%S")
                try:
                    os.rename(self.calibration_file_path, backup)
                except Exception:
                    pass
                self.data = {"schema_version": 1, "runs": []}

        # Build run envelope
        self._run_id = str(uuid.uuid4())
        run_meta = {
            "run_id": self._run_id,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ended_at": None,
            "printer_head_id": self._safe_get_printer_head_id(),
            "stock_solution": self._safe_get_stock_solution(),
            "notes": notes or "",
            "steps": {k: [] for k in set(self.PHASE_ALIASES.values())},
            "flat_measurements": []
        }
        self.data.setdefault("schema_version", 1)
        self.data.setdefault("runs", [])
        self.data["runs"].append(run_meta)
        self._run_idx = len(self.data["runs"]) - 1
        self._save_atomic()

        self.calibrationStageChanged.emit(
            f"Calibration session started (run_id={self._run_id}, stock={run_meta['stock_solution']})",
            "dark_blue"
        )

    def end_session(self):
        """Stamp end time for the current run."""
        if self._run_idx is not None and 0 <= self._run_idx < len(self.data.get("runs", [])):
            self.data["runs"][self._run_idx]["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._save_atomic()
            self.calibrationStageChanged.emit("Calibration session ended", "purple")

        self._run_id = None
        self._run_idx = None

    # Back-compat: keep these, but redirect through session I/O
    def create_calibration_file(self, file_path):
        """Creates a brand-new file and clears any prior data."""
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        self.calibration_file_path = file_path
        self.remove_all_calibrations()

    def update_calibration_file_path(self, file_path):
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        self.calibration_file_path = file_path
        # Try to load existing; else start a new envelope
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {"schema_version": 1, "runs": []}
        else:
            self.data = {"schema_version": 1, "runs": []}
        self._save_atomic()

    def save_calibration_data(self, file_path):
        self.calibration_file_path = file_path
        self._save_atomic()

    def load_calibration_data(self, file_path):
        self.calibration_file_path = file_path
        with open(file_path, 'r') as file:
            self.data = json.load(file)

    def remove_all_calibrations(self):
        self.data = {"schema_version": 1, "runs": []}
        self._save_atomic()

    def _save_atomic(self):
        """Atomic write to avoid truncation on crash."""
        if not self.calibration_file_path:
            # safe default so nothing is lost silently
            self.calibration_file_path = os.path.abspath("calibration.json")
            self.calibrationStageChanged.emit(
                f"Warning: calibration_file_path not set — writing to {self.calibration_file_path}", "red"
            )
        with self._lock:
            tmp = self.calibration_file_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, indent=2, default=numpy_encoder)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.calibration_file_path)

    # ------------- Calibration queue -------------

    def add_all_calibrations_to_queue(self):
        self.add_calibration_to_queue('nozzle_position')
        self.add_calibration_to_queue('nozzle_focus')
        self.add_calibration_to_queue('droplet_emergence')
        self.add_calibration_to_queue('pressure')
        self.add_calibration_to_queue('trajectory')
        self.add_calibration_to_queue('droplet_search')
        self.start_calibration_queue()

    def add_calibration_to_queue(self, calibration_name):
        self.calibration_queue.append(calibration_name)

    def add_calibration_queue(self, calibration_list):
        self.calibration_queue.extend(calibration_list)

    def clear_calibration_queue(self):
        self.calibration_queue = []

    def start_calibration_queue(self):
        if len(self.calibration_queue) > 0:
            next_cal = self.calibration_queue.pop(0)
            if next_cal == 'nozzle_position':
                self.activeCalibration = NozzlePositionCalibrationProcess(self, self.model)
            elif next_cal == 'nozzle_focus':
                self.activeCalibration = NozzleFocusCalibrationProcess(self, self.model)
            elif next_cal == 'droplet_emergence':
                self.activeCalibration = DropletEmergenceCalibrationProcess(self, self.model)
            elif next_cal == 'pressure':
                self.activeCalibration = PressureCalibrationProcess(self, self.model)
            elif next_cal == 'trajectory':
                self.activeCalibration = TrajectoryCalibrationProcess(self, self.model)
            elif next_cal == 'droplet_search':
                self.activeCalibration = DropletSearchCalibrationProcess(self, self.model)
            self.start_active_calibration()
        else:
            self.calibrationStageChanged.emit("No calibrations in queue.", "red")
            self.calibrationQueueCompleted.emit()

    def start_active_calibration(self):
        if self.activeCalibration is not None:
            # Ensure we have an open run to write into
            if self._run_idx is None:
                # Create a default session in CWD if the caller forgot
                self.begin_session(self.model.experiment_model.get_calibration_file_path(), notes="auto-started session")
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
        self.calibrationStageChanged.emit("Calibration stopped","orange")
        self.calibrationError.emit("Calibration terminated by user")

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

    # ------------- Settings snapshot -------------

    def get_current_settings(self):
        (num_flashes, flash_duration, flash_delay,
         num_droplets, exposure_time) = self.model.droplet_camera_model.get_image_metadata()
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

    # ------------- Getters (alias-aware) -------------

    def _resolve_phase_key(self, phase_name):
        c = self.PHASE_ALIASES.get(phase_name, phase_name)
        return c

    def _latest_step_list(self, phase_name):
        if self._run_idx is None:
            return []
        phase_key = self._resolve_phase_key(phase_name)
        steps = self.data["runs"][self._run_idx]["steps"]
        return steps.get(phase_key, [])

    def get_centered_nozzle_position(self):
        recs = self._latest_step_list("nozzle_position")
        if recs:
            return recs[-1].get("result")
        self.calibrationStageChanged.emit("No nozzle position calibration available", "red")
        return None

    def get_emergence_time(self):
        recs = self._latest_step_list("droplet_emergence")
        if recs:
            return recs[-1].get("result", {}).get("flash_delay")
        self.calibrationStageChanged.emit("No droplet emergence calibration available", "red")
        return None

    def is_in_initial_position(self):
        # kept for compatibility—presence of any pressure step
        return bool(self._latest_step_list("pressure_calibration"))

    # ------------- Cross-step setters/getters -------------

    def set_background_image(self, background): self.background_image = background
    def set_nozzle_center(self, center): self.nozzle_center = center
    def set_nozzle_center_image_position(self, center): self.nozzle_center_image_position = center
    def set_trajectory_vector(self, vector): self.droplet_trajectory_vector = vector
    def set_trajectory_delay(self, delay): self.trajectory_delay = delay
    def set_min_start_delay(self, delay): self.min_start_delay = delay
    def set_intermediate_droplet_position(self, position): self.intermediate_droplet_position = position

    def get_background_image(self): return self.background_image
    def get_nozzle_center(self): return self.nozzle_center
    def get_nozzle_center_image_position(self): return self.nozzle_center_image_position
    def get_trajectory_vector(self): return self.droplet_trajectory_vector
    def get_trajectory_delay(self): return self.trajectory_delay
    def get_min_start_delay(self): return self.min_start_delay
    def get_intermediate_droplet_position(self): return self.intermediate_droplet_position

    # ------------- Offsets helper -------------

    def update_offsets_from_nozzle(self):
        current_dict = self.model.machine_model.get_current_position_dict()
        diff_dict = current_dict.copy()
        if self.nozzle_center is not None:
            for k in diff_dict:
                diff_dict[k] -= self.nozzle_center[k]
        else:
            for k in diff_dict:
                diff_dict[k] = 0
        self.position_diff_dict_signal.emit(current_dict, diff_dict)

    # ------------- Transition helpers -------------

    @Slot()
    def emitSettingsChangeCompleted(self): self.settingsChangeCompleted.emit()
    
    @Slot()
    def emitCaptureCompleted(self): self.captureCompleted.emit()
    
    @Slot()
    def emitMoveCompleted(self):
        self.moveCompleted.emit()
        print('Emit Move completed called')

    # ------------- Completion / Error -------------

    @Slot()
    def onCalibrationCompleted(self):
        self.calibrationStageChanged.emit("Calibration completed successfully", "green")
        self.activeCalibration = None
        self.calibrationCompleted.emit()
        if len(self.calibration_queue) > 0:
            self.calibrationStageChanged.emit("Starting next calibration in queue...", "blue")
            self.start_calibration_queue()
        else:
            self.calibrationQueueCompleted.emit()

    @Slot(str)
    def onCalibrationError(self, error_message):
        self.calibrationStageChanged.emit("Calibration error: " + error_message, "red")
        # NEW: hard-stop the running calibration FSM to prevent any queued transitions
        if self.activeCalibration is not None:
            try:
                self.activeCalibration.stop()
            except Exception:
                pass
        self.activeCalibration = None
        self.calibrationError.emit(error_message)
        if len(self.calibration_queue) > 0:
            self.calibrationStageChanged.emit("Calibration queue stopped due to error", "red")
            self.clear_calibration_queue()

    # ------------- The key hook: persist every step -------------

    @Slot(dict)
    def onCalibrationDataUpdated(self, data):
        """
        Augment per-step payload with timestamp + settings + run metadata,
        append under current run.steps[phase], and also append flat per-droplet
        rows when present (droplet volumes list, etc.).
        """
        if self._run_idx is None:
            # fallback to default session in CWD
            self.begin_session(self.model.experiment_model.get_calibration_file_path(), notes="auto-started during data update")

        phase = getattr(self.activeCalibration, "phase_name", "unknown")
        phase_key = self._resolve_phase_key(phase)

        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        settings = self.get_current_settings()

        # Run metadata
        meta = {
            "run_id": self._run_id,
            "stock_solution": self._safe_get_stock_solution(),
            "printer_head_id": self._safe_get_printer_head_id()
        }

        # Augment
        payload = dict(data)  # shallow copy
        payload["timestamp"] = stamp
        payload["settings"] = settings
        payload["meta"] = meta
        payload["phase"] = phase_key

        # Append to steps
        run = self.data["runs"][self._run_idx]
        run["steps"].setdefault(phase_key, []).append(payload)

        # Optional: emit flat rows if droplet arrays present (from droplet_search / characterization)
        self._try_append_flat_rows_from_payload(run, phase_key, payload)

        self._save_atomic()

    def _try_append_flat_rows_from_payload(self, run_obj, phase_key, payload):
        """
        Try to normalize per-droplet replicates into flat rows.
        Accepts both 'droplet_positions' and 'positions_px' for centers.
        """
        # Lists of replicates (prefer 'result' block; fallback to top-level)
        per_vols = (
            payload.get("result", {}).get("droplet_volumes")
            or payload.get("droplet_volumes")
        )

        # Centers: accept either 'droplet_positions' or 'positions_px'
        centers = (
            payload.get("result", {}).get("droplet_positions")
            or payload.get("droplet_positions")
            or payload.get("result", {}).get("positions_px")
            or payload.get("positions_px")
        )

        circ = (
            payload.get("result", {}).get("circularity_values")
            or payload.get("circularity_values")
        )
        focus_list = (
            payload.get("result", {}).get("droplet_focus")
            or payload.get("droplet_focus")
        )

        if isinstance(per_vols, list) and per_vols:
            N = len(per_vols)
            # Align optional lists to N
            centers = centers if isinstance(centers, list) and len(centers) == N else [None] * N
            circ = circ if isinstance(circ, list) and len(circ) == N else [None] * N
            focus_list = focus_list if isinstance(focus_list, list) and len(focus_list) == N else [None] * N

            # Stable settings for all rows from this payload snapshot
            flash_delay = payload.get("result", {}).get("delay_us")
            if flash_delay is None:
                flash_delay = payload.get("settings", {}).get("flash_delay")

            print_pw = payload.get("settings", {}).get("print_width")
            print_p = payload.get("settings", {}).get("print_pressure")
            nozzle_px = self.nozzle_center_image_position

            for i in range(N):
                row = {
                    "phase": phase_key,
                    "timestamp": payload.get("timestamp"),
                    "flash_delay_us": flash_delay,
                    "print_pressure": print_p,
                    "print_pulse_width_us": print_pw,
                    "volume_pL": per_vols[i],
                    "circularity_ellipse": circ[i],
                    "focus": focus_list[i],
                    "center_px": centers[i],
                    "nozzle_center_px": nozzle_px,
                    "stock_solution": self._safe_get_stock_solution(),
                    "printer_head_id": self._safe_get_printer_head_id(),
                }
                run_obj["flat_measurements"].append(row)

    @Slot(object)
    def onPresentImage(self, image):
        self.analyzedImageUpdated.emit(image)

    # ------------- Small helpers -------------

    def _safe_get_stock_solution(self):
        try:
            ph = self.model.rack_model.get_gripper_printer_head()
            return getattr(ph.get_stock_solution(), "name", None) or str(ph.get_stock_solution())
        except Exception:
            return None

    def _safe_get_printer_head_id(self):
        try:
            ph = self.model.rack_model.get_gripper_printer_head()
            # Prefer a stable id/serial if available; fallback to str()
            return getattr(ph, "serial", None) or getattr(ph, "id", None) or str(ph)
        except Exception:
            return None

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
            self.calibration_manager.set_background_image(self.background_image)
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
    MIN_REFINE_EVALS = 3
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
    replicateContinue = Signal()

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
        
        # analyze -> capture_droplet for more replicates at the SAME delay
        t5b = QSignalTransition()
        t5b.setSenderObject(self)
        t5b.setSignal(b"2replicateContinue()")
        t5b.setTargetState(self.state_capture_droplet)
        self.state_analyze.addTransition(t5b)

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
        self.stageChanged.emit("Analyzing droplet image")

        area, center, overlay = self.model.droplet_camera_model.calc_emergence_area(
            self.background_image, self.droplet_image
        )
        self.presentImageSignal.emit(overlay)
        self._eval_count += 1

        # treat "no contour" as zero area
        if area is None:
            area = 0

        self._rep_areas.append(area)
        self.stageChanged.emit(f"Delay {self.candidate_delay} μs replicate → area {area}")

        # Need more replicates? loop back to capture_droplet via signal/transition
        if len(self._rep_areas) < self.REPLICATES:
            self.replicateContinue.emit()     # <-- FIX: use state transition, not a direct capture call
            return

        # Aggregate this delay
        agg_area = int(median(self._rep_areas))
        self._rep_areas.clear()
        self.measurements.append((self.candidate_delay, agg_area))
        self.stageChanged.emit(f"Delay {self.candidate_delay} μs → median area {agg_area}")

        # classify result for this delay
        cls = self._classify(agg_area)
        if cls == "TARGET":
            self.stageChanged.emit("Target area reached")
            self.calibrationDataUpdated.emit({
                'measurements': self.measurements,
                'result': {'area': agg_area, 'flash_delay': self.candidate_delay}
            })
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

        self.continueSearch.emit()

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
        self.upper_pressure = 1.5   # example maximum pressure
        # Start with a candidate near the lower bound.
        self.candidate_pressure = self.model.machine_model.get_current_print_pressure()
        
        lo_hw, hi_hw = self._pressure_bounds()
        self.lower_pressure = max(lo_hw, self.lower_pressure)
        self.upper_pressure = min(hi_hw, self.upper_pressure)
        self.candidate_pressure = self._clampP(self.candidate_pressure)
        
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
        nozzle_vector = self.calibration_manager.get_nozzle_center()
        if nozzle_vector is None:
            self.calibrationError.emit("Nozzle center not found")
            return
        print(f"Requesting move to initial position: {nozzle_vector}")
        self.calibration_manager.moveAbsoluteRequested.emit(nozzle_vector, self.calibration_manager.emitMoveCompleted)

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
        self.stageChanged.emit(f"Setting pressure to {self.candidate_pressure:.3f}")
        new_flash_delay = max(0, int(self.start_delay + self.start_delay_offset))  # keep non-negative
        self.candidate_pressure = self._clampP(self.candidate_pressure)

        settings = {
            "flash_delay": new_flash_delay,
            "num_droplets": 1,
            "print_pressure": self.candidate_pressure,
        }
        self._rep_results = []
        self._rep_captured = 0
        self.calibration_manager.changeSettingsRequested.emit(
            settings, self.calibration_manager.emitSettingsChangeCompleted
        )

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
    
    def _pressure_bounds(self):
        # Try to read from the machine; fallback to safe defaults
        try:
            lo, hi = self.model.machine_model.get_print_pressure_bounds()
        except Exception:
            lo, hi = 0.2, 1.50  # psi, conservative
        return float(lo), float(hi)

    def _clampP(self, p: float) -> float:
        lo, hi = self.lower_pressure, self.upper_pressure
        return max(lo, min(hi, float(p)))

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
        tested_pressure = float(self.candidate_pressure)  # freeze the value we just tested
        self._record_replicate(droplet_count, nozzle_area)
        print(f"[P-Cal] replicate {self._rep_captured}/{self.replicates_per_pressure} "
            f"@P={tested_pressure:.3f}: count={droplet_count}, area={nozzle_area}")

        # ---- Early-exit replicates (strong signals) ----
        if self._rep_captured >= 2:
            counts = [c for (c, _a) in self._rep_results]
            if counts.count(0) >= 2 or sum(1 for c in counts if c >= 2) >= 2:
                # force aggregation now
                self._rep_captured = self.replicates_per_pressure

        if self._rep_captured < self.replicates_per_pressure:
            self.replicateContinue.emit()
            return

        # --- aggregate replicates into a single decision for this pressure ---
        agg_count, agg_area, dbg = self._aggregate_replicates()
        print(f"[P-Cal] aggregated @P={tested_pressure:.3f}: "
            f"count={agg_count}, area={agg_area}, rule={dbg.get('rule')} "
            f"reps={dbg.get('replicates')}")
        self.measurements.append((tested_pressure, agg_count, agg_area))
        self.stageChanged.emit(
            f"Aggregated — Pressure: {tested_pressure:.3f}, "
            f"Droplet count: {agg_count}, Nozzle area: {agg_area}"
        )

        # classify with hysteresis-aware evaluator
        outcome = self.evaluate_condition(agg_count, agg_area, self.nozzle_droplet_threshold)
        acceptable = (outcome in ("ACCEPTABLE", "BORDERLINE"))
        # one_drop   = (outcome in ("ACCEPTABLE", "BORDERLINE", "NEAR"))

        if acceptable:
            self.last_acceptable_pressure = tested_pressure

        # # SNAPSHOTS for anti-oscillation logic
        # prev_outcome  = self._last_outcome
        # prev_pressure = self._last_pressure
        # tested_pressure = self.candidate_pressure  # the pressure we just evaluated
        print(f"\n\n[P-Cal] - new measurement: P={tested_pressure:.3f}, count={agg_count}, area={agg_area}")

        # --------- Anti-oscillation guard (BRACKET only) ----------
        # If we flip across the boundary in back-to-back steps (TOO_LOW ↔ NEAR/TOO_HIGH),
        # stop coarse stepping and enter REFINE immediately with those two points.
        if self.phase == "bracket" and self._last_outcome is not None:
            flipped_low_to_highish = (self._last_outcome == "TOO_LOW" and outcome in ("NEAR", "TOO_HIGH"))
            flipped_highish_to_low = (self._last_outcome in ("NEAR", "TOO_HIGH") and outcome == "TOO_LOW")
            if flipped_low_to_highish or flipped_highish_to_low:
                lo = self.last_too_low_pressure if self.last_too_low_pressure is not None else (
                    min(self._last_pressure, tested_pressure))
                hi = max(self._last_pressure, tested_pressure)
                self._switch_to_refine(lo, hi)
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
                self.candidate_pressure = self._clampP(tested_pressure + step)
                print(f"[P-Cal] TOO_LOW → +{step:.3f} → {self.candidate_pressure:.3f}")
                self.emitContinueSearch()
                self.counter += 1
                if self.counter >= self.max_iterations:
                    self.calibrationError.emit("Pressure search did not converge (too low region)")
                self._last_outcome  = outcome
                self._last_pressure = tested_pressure
                return

            if acceptable:
                if (self.bracket_lo is None) or (tested_pressure > self.bracket_lo):
                    self.bracket_lo = tested_pressure
                step = self._adaptive_step(outcome, agg_area)
                self.candidate_pressure = self._clampP(tested_pressure + step)
                print(f"[P-Cal] {outcome} → +{step:.3f} → {self.candidate_pressure:.3f} (lo={self.bracket_lo:.3f})")
                self.emitContinueSearch()
                self.counter += 1
                if self.counter >= self.max_iterations:
                    self.calibrationError.emit("Pressure search did not converge (bracket acceptable climb)")
                self._last_outcome  = outcome
                self._last_pressure = tested_pressure
                return

            # outcome == NEAR or TOO_HIGH → we’re at/above the upper boundary
            self.bracket_hi = tested_pressure
            if self.bracket_lo is None:
                if self.last_too_low_pressure is not None:
                    self._switch_to_refine(self.last_too_low_pressure, self.bracket_hi)
                else:
                    step = self._adaptive_step(outcome, agg_area)
                    self.candidate_pressure = self._clampP(tested_pressure - step)
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
            self._last_pressure = tested_pressure
            if self.counter >= self.max_iterations:
                self.calibrationError.emit("Pressure search did not converge (switching to refine)")
            return

        # -------------------- Phase 2: REFINE (bisection to highest acceptable) --------------------
        if self.phase == "refine":
            if outcome in ("ACCEPTABLE", "BORDERLINE", "TOO_LOW"):
                self.bracket_lo = tested_pressure if self.bracket_lo is None else max(self.bracket_lo, tested_pressure)
            else:
                self.bracket_hi = tested_pressure if self.bracket_hi is None else min(self.bracket_hi, tested_pressure)

            if (self.bracket_lo is not None) and (self.bracket_hi is not None):
                gap = self.bracket_hi - self.bracket_lo
                print(f"[P-Cal] REFINE: lo={self.bracket_lo:.3f} hi={self.bracket_hi:.3f} gap={gap:.4f}")
                if gap <= self.pressure_threshold:
                    if self.last_acceptable_pressure is None:
                        self.calibrationError.emit(
                            "Pressure search narrowed but never observed a valid single-droplet condition."
                        )
                        return
                    self.candidate_pressure = self.bracket_lo  # highest acceptable
                    self.final_condition_found = True
                    self.stageChanged.emit("Final condition found (bisection → highest acceptable)")
                    self.calibrationDataUpdated.emit({
                        'measurements': self.measurements,
                        'result': {'pressure': self.candidate_pressure}
                    })
                    self.emitDropletDetected()
                    return

                self.candidate_pressure = self._clampP(0.5 * (self.bracket_lo + self.bracket_hi))
                print(f"[P-Cal] Next mid={self.candidate_pressure:.3f}")
                self.emitContinueSearch()
                self.counter += 1
                if self.counter >= self.max_iterations:
                    if self.last_acceptable_pressure is not None:
                        self.candidate_pressure = self.last_acceptable_pressure
                        self.final_condition_found = True
                        self.emitDropletDetected()
                    else:
                        self.calibrationError.emit("Pressure search did not converge (refine phase)")
                self._last_outcome  = outcome
                self._last_pressure = tested_pressure
                return

        # Fallback bookkeeping
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
        self.calibration_manager.set_nozzle_center_image_position(self.nozzle_center)
        self.calibration_manager.set_min_start_delay(self.start_delay + self.start_delay_offset)
        self.dropletDetected.emit()

class TrajectoryCalibrationProcess(BaseCalibrationProcess):
    continueTrajectory = Signal()
    trajectoryCalculated = Signal()
    trajectoryFinalized = Signal()
    changePressure = Signal()

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)
        self.phase_name = "trajectory_calibration"

        # ---- prerequisites from earlier calibrations ----
        self._ready = True
        self.import_calibration_data()
        if not self._ready:
            return

        # ---- delay plan (sample well after emergence) ----
        # Base = emergence time + offset (to ensure free-flight), then 2 more later points
        self.start_delay_offset = max(self.model.machine_model.get_print_pulse_width() + 1000, 0)
        self.t_emerge_us = int(self.start_delay)  # from emergence calibration
        base_us = int(max(0, self.t_emerge_us + self.start_delay_offset))  # free-flight start
        # Plan (us) relative to base: tune spacings to keep droplet inside FOV
        self.plan_offsets_us = [0, 500, 1000]     # 0 ms, +0.5 ms, +1 ms
        self.delay_plan_us = [base_us + d for d in self.plan_offsets_us]
        self._delay_index = 0
        self._current_delay_us = None

        # Delay bounds (safe guard)
        self.min_delay_us = 0
        self.max_delay_us = 20000  # 20 ms hard cap (adjust if needed)
        self.delay_plan_us = [int(min(max(d, self.min_delay_us), self.max_delay_us))
                              for d in self.delay_plan_us]

        # Replicates per delay and storage
        self.reps_per_delay = 3
        self._positions_by_delay = {d: [] for d in self.delay_plan_us}

        # ---- pressure management (same guardrails as before) ----
        try:
            p_lo, p_hi = self.model.machine_model.get_print_pressure_bounds()
        except Exception:
            p_lo, p_hi = 0.3, 1.5
        self.min_pressure = float(p_lo)
        self.max_pressure = float(p_hi)

        self.pressure_step = 0.02
        self.new_pressure = None
        self._adjustments = 0
        self._max_adjustments = 8
        self._discard_next = False  # discard first shot after pressure change

        # ---- capture state ----
        self._settings_applied = False
        self.image_counter = 0
        self.annotated_images = []  # for the *current* delay only (debug view)

        # Early stability check per-delay (keeps time down if very repeatable)
        self.std_tol_px = 3.0

        # ---- states ----
        self.state_capture_droplet = QState()
        self.state_analyze = QState()
        self.state_change_pressure = QState()
        self.state_trajectory_analysis = QState()
        self.state_final = QFinalState()

        self.state_capture_droplet.entered.connect(self.onCaptureDroplet)
        self.state_analyze.entered.connect(self.onAnalyze)
        self.state_change_pressure.entered.connect(self.onChangePressure)
        self.state_trajectory_analysis.entered.connect(self.onTrajectoryAnalysis)
        self.state_final.entered.connect(self.onCalibrationCompleted)

        t1 = QSignalTransition()
        t1.setSenderObject(self.calibration_manager)
        t1.setSignal(b"2captureCompleted()")
        t1.setTargetState(self.state_analyze)
        self.state_capture_droplet.addTransition(t1)

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

        # allow finishing directly from capture state too
        t3_cap = QSignalTransition()
        t3_cap.setSenderObject(self)
        t3_cap.setSignal(b"2trajectoryCalculated()")
        t3_cap.setTargetState(self.state_trajectory_analysis)
        self.state_capture_droplet.addTransition(t3_cap)

        tP = QSignalTransition()
        tP.setSenderObject(self)
        tP.setSignal(b"2changePressure()")
        tP.setTargetState(self.state_change_pressure)
        self.state_analyze.addTransition(tP)

        tPdone = QSignalTransition()
        tPdone.setSenderObject(self.calibration_manager)
        tPdone.setSignal(b"2settingsChangeCompleted()")
        tPdone.setTargetState(self.state_capture_droplet)
        self.state_change_pressure.addTransition(tPdone)

        t4 = QSignalTransition()
        t4.setSenderObject(self)
        t4.setSignal(b"2trajectoryFinalized()")
        t4.setTargetState(self.state_final)
        self.state_trajectory_analysis.addTransition(t4)

        self.state_machine.addState(self.state_capture_droplet)
        self.state_machine.addState(self.state_analyze)
        self.state_machine.addState(self.state_change_pressure)
        self.state_machine.addState(self.state_trajectory_analysis)
        self.state_machine.addState(self.state_final)
        self.state_machine.setInitialState(self.state_capture_droplet)

    # ---------- helpers ----------
    def _clampP(self, p: float) -> float:
        return max(self.min_pressure, min(self.max_pressure, float(p)))

    def import_calibration_data(self):
        self.nozzle_center_image_position = self.calibration_manager.get_nozzle_center_image_position()
        self.nozzle_center_machine = self.calibration_manager.get_nozzle_center()
        self.background_image = self.calibration_manager.get_background_image()
        self.start_delay = self.calibration_manager.get_emergence_time()
        if (self.nozzle_center_machine is None or
            self.background_image is None or
            self.nozzle_center_image_position is None or
            self.start_delay is None):
            self._ready = False
            self.calibrationError.emit("Must complete pressure + emergence + nozzle-center first")

    def _apply_settings_and_capture(self, delay_us):
        """Set (flash_delay, num_droplets=1) and capture in the callback."""
        self._settings_applied = True
        self._current_delay_us = int(delay_us)
        current_p = self._clampP(self.model.machine_model.get_current_print_pressure())
        settings = {
            "flash_delay": self._current_delay_us,
            "num_droplets": 1,
            "print_pressure": current_p,
        }
        def _after():
            self._capture_with_policy(
                set_attr="droplet_image",
                stage_text=f"Capturing at delay {self._current_delay_us} μs "
                           f"({len(self._positions_by_delay[self._current_delay_us]) + 1}"
                           f"/{self.reps_per_delay})",
                attempts_total=5,
                retry_delay_ms=75,
                guard_timeout_ms=10_000,
                final_error_msg=f"Failed to capture droplet at delay={self._current_delay_us} μs."
            )
        self.calibration_manager.changeSettingsRequested.emit(settings, _after)

    def _positions_are_tight(self, pts, tol_px=3.0):
        if len(pts) < 2: return False
        a = np.array(pts, dtype=np.float32)
        std = np.std(a, axis=0)
        return bool((std[0] <= tol_px) and (std[1] <= tol_px))

    def _robust_mean(self, pts):
        """MAD filter then mean. Returns (mean_tuple, kept_points)."""
        if len(pts) == 1:
            return tuple(map(int, pts[0])), pts[:]
        a = np.array(pts, dtype=np.float32)
        med = np.median(a, axis=0)
        d = np.linalg.norm(a - med, axis=1)
        mad = np.median(np.abs(d - np.median(d))) + 1e-6
        keep = a[d <= (np.median(d) + 2.5 * mad)]
        if keep.size == 0:
            keep = a
        mean_xy = tuple(np.mean(keep, axis=0).astype(int))
        return mean_xy, [tuple(map(int, xy)) for xy in keep]

    # ---------- states ----------
    @Slot()
    def onCaptureDroplet(self):
        if not self._ready:
            self.calibrationError.emit("Trajectory calibration prerequisites missing")
            return
        # Choose the delay for this shot
        if self._delay_index >= len(self.delay_plan_us):
            # We have everything we need; proceed to analysis
            self.emitTrajectoryCalculated()
            return

        target_delay = int(self.delay_plan_us[self._delay_index])
        if target_delay not in self._positions_by_delay:
            self._positions_by_delay[target_delay] = []
        current_delay = self._current_delay_us

        # If this is our first shot or we need to switch delay, set settings then capture
        if (not self._settings_applied) or (current_delay != target_delay):
            self._apply_settings_and_capture(target_delay)
            return

        # Settings are already correct → capture now
        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text=f"Capturing at delay {current_delay} μs "
                       f"({len(self._positions_by_delay[current_delay]) + 1}"
                       f"/{self.reps_per_delay})",
            attempts_total=5,
            retry_delay_ms=75,
            guard_timeout_ms=10_000,
            final_error_msg=f"Failed to capture droplet at delay={current_delay} μs."
        )

    @Slot()
    def onAnalyze(self):
        # Optionally discard the first shot after any pressure change (settling)
        if self._discard_next:
            self._discard_next = False
            self.stageChanged.emit("Discarding first shot after pressure change (settling)")
            self.emitContinueTrajectory()
            return

        delay_us = int(self._current_delay_us)
        if delay_us not in self._positions_by_delay:
            self._positions_by_delay[delay_us] = []
        self.stageChanged.emit(f"Analyzing droplet at {delay_us} μs")

        droplets, nozzle_area, annotated = self.model.droplet_camera_model.identify_droplets(
            self.droplet_image, self.background_image, self.nozzle_center_image_position
        )

        # Pressure corrections (unchanged logic)
        if not droplets:
            self._adjustments += 1
            if self._adjustments > self._max_adjustments:
                self.calibrationError.emit("Unable to obtain a clear droplet (max adjustments)")
                return
            cur_p = self._clampP(self.model.machine_model.get_current_print_pressure())
            self.new_pressure = self._clampP(cur_p + self.pressure_step)
            if self.new_pressure <= cur_p and cur_p >= self.max_pressure:
                self.calibrationError.emit("Maximum pressure reached")
                return
            self.stageChanged.emit(f"No droplet → increasing pressure to {self.new_pressure:.3f} psi")
            self.emitChangePressure()
            return

        if len(droplets) > 1:
            self._adjustments += 1
            if self._adjustments > self._max_adjustments:
                self.calibrationError.emit("Multiple droplets persist (max adjustments)")
                return
            cur_p = self._clampP(self.model.machine_model.get_current_print_pressure())
            self.new_pressure = self._clampP(cur_p - self.pressure_step)
            if self.new_pressure >= cur_p and cur_p <= self.min_pressure:
                self.calibrationError.emit("Minimum pressure reached")
                return
            self.stageChanged.emit(f"Multiple droplets → decreasing pressure to {self.new_pressure:.3f} psi")
            # Reset samples for current delay so we don’t mix conditions
            self._positions_by_delay[delay_us].clear()
            self.annotated_images.clear()
            self.emitChangePressure()
            return

        # Exactly one droplet
        dxy = tuple(map(int, droplets[0]))
        # Visual overlay (nozzle -> droplet)
        cv2.circle(annotated, dxy, 8, (0, 0, 255), -1)
        cv2.circle(annotated, self.nozzle_center_image_position, 6, (255, 0, 0), -1)
        cv2.line(annotated, self.nozzle_center_image_position, dxy, (0, 255, 255), 2)
        self.presentImageSignal.emit(annotated)

        self._positions_by_delay[delay_us].append(dxy)
        self.annotated_images.append(annotated)

        # Early “tight” check within this delay to speed up if extremely stable
        if (len(self._positions_by_delay[delay_us]) >= 2
                and self._positions_are_tight(self._positions_by_delay[delay_us], self.std_tol_px)):
            # proceed to next delay immediately
            self.stageChanged.emit(f"Delay {delay_us} μs samples stable; advancing")
            self._delay_index += 1
            self.emitContinueTrajectory()
            return

        # Enough replicates for this delay?
        if len(self._positions_by_delay[delay_us]) < self.reps_per_delay:
            self.emitContinueTrajectory()
            return

        # Move to next delay (if any)
        self._delay_index += 1
        if self._delay_index < len(self.delay_plan_us):
            self.emitContinueTrajectory()
        else:
            self.emitTrajectoryCalculated()

    @Slot()
    def onChangePressure(self):
        self.stageChanged.emit("Changing pressure")
        self._discard_next = True
        settings = { "print_pressure": self.new_pressure }
        self.calibration_manager.changeSettingsRequested.emit(
            settings, self.calibration_manager.emitSettingsChangeCompleted
        )

    @Slot()
    def onTrajectoryAnalysis(self):
        self.stageChanged.emit("Fitting velocity from multi-delay samples")

        # Build robust per-delay means (in pixel coords) and flight times (seconds)
        t_s = []
        pts = []
        kept_by_delay = {}
        for dly in self.delay_plan_us:
            samples = self._positions_by_delay.get(dly, [])
            if not samples:
                continue
            mean_xy, kept = self._robust_mean(samples)
            kept_by_delay[dly] = kept
            pts.append(mean_xy)
            # Flight time since emergence (convert μs → s)
            t_s.append(max(0.0, (dly - self.t_emerge_us) * 1e-6))

        if len(pts) < 2:
            self.calibrationError.emit("Not enough valid delays to fit velocity (need ≥2).")
            return

        pts = np.array(pts, dtype=np.float32)  # (n,2)
        t_s = np.array(t_s, dtype=np.float64)  # (n,)

        # Linear fit: x(t) = a_x + b_x t ; y(t) = a_y + b_y t
        # b_x, b_y are pixels/second
        A = np.vstack([np.ones_like(t_s), t_s]).T
        bx = np.linalg.lstsq(A, pts[:,0], rcond=None)[0][1]
        by = np.linalg.lstsq(A, pts[:,1], rcond=None)[0][1]

        v_px_per_s = np.array([bx, by], dtype=np.float64)
        v_px_per_us = v_px_per_s / 1e6

        # Map pixel velocity to stage units using camera model (A_inv)
        # A_inv maps [Δcx, Δcy] → [ΔX, ΔZ] (dY=0 in your model).
        A_inv = getattr(self.model.droplet_camera_model, "A_inv", None)
        if A_inv is None:
            self.calibrationError.emit("Camera model A_inv missing; cannot convert velocity to stage units.")
            return
        vXZ_steps_per_s = A_inv.dot(v_px_per_s)  # [vX_steps/s, vZ_steps/s]
        v_vec_steps_per_s = (float(vXZ_steps_per_s[0]), 0.0, float(vXZ_steps_per_s[1]))
        speed_steps_per_s = float(np.hypot(vXZ_steps_per_s[0], vXZ_steps_per_s[1]))

        # Final debug image: draw per-delay means and fit direction
        final_image = self.annotated_images[-1].copy() if self.annotated_images else self.droplet_image.copy()
        for dly, kept in kept_by_delay.items():
            for (x, y) in kept:
                cv2.circle(final_image, (int(x), int(y)), 4, (255, 0, 0), -1)
        # Draw a small velocity ray from the last mean
        p_last = tuple(map(int, pts[-1]))
        ray = (int(p_last[0] + 0.002 * v_px_per_s[0]), int(p_last[1] + 0.002 * v_px_per_s[1]))  # scale for view
        cv2.arrowedLine(final_image, p_last, ray, (0, 255, 0), 2, tipLength=0.25)
        cv2.circle(final_image, self.nozzle_center_image_position, 6, (255, 0, 0), -1)
        self.presentImageSignal.emit(final_image)

        # Package results (keep pixel and stage-space velocities)
        results = {
            'delays_us': self.delay_plan_us,
            't_flight_s': t_s.tolist(),
            'pixel_means': pts.astype(int).tolist(),
            'velocity_px_per_s': (float(v_px_per_s[0]), float(v_px_per_s[1])),
            'velocity_steps_per_s': v_vec_steps_per_s,
            'speed_steps_per_s': speed_steps_per_s,
            'emergence_time_us': int(self.t_emerge_us)
        }

        # Persist for the next calibration step
        self.calibration_manager.set_trajectory_vector(v_vec_steps_per_s)         # direction & magnitude in stage units
        self.calibration_manager.set_trajectory_delay(int(self.delay_plan_us[0])) # first delay used (for reference)
        self.calibration_manager.set_intermediate_droplet_position(
            self.model.droplet_camera_model.convert_pixel_position_to_motor_steps(
                tuple(map(int, pts[-1])), self.model.machine_model.get_current_position_dict()
            )
        )

        self.calibrationDataUpdated.emit({'measurements': results['pixel_means'], 'result': results})
        self.emitTrajectoryFinalized()

    def emitContinueTrajectory(self): self.continueTrajectory.emit()
    def emitChangePressure(self): self.changePressure.emit()
    def emitTrajectoryCalculated(self): self.trajectoryCalculated.emit()
    def emitTrajectoryFinalized(self): self.trajectoryFinalized.emit()

    @Slot()
    def onCalibrationCompleted(self):
        self.stageChanged.emit("Trajectory calibration complete")
        self.calibrationCompleted.emit()

class DropletSearchCalibrationProcess(BaseCalibrationProcess):
    """
    Final step: find droplet at a fixed time-of-flight, center safely, ensure focus, then
    capture replicates to estimate mean volume and CV. Uses velocity (steps/s) and emergence
    time from TrajectoryCalibration to predict a machine target and a flash delay.
    """

    # Signals
    continueSearch = Signal()
    restartSearch = Signal()
    changePressure = Signal()
    dropletFound = Signal()
    dropletCentered = Signal()
    continueCharacterization = Signal()
    initiateCharacterizationAnalysis = Signal()
    characterizationCompleted = Signal()

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)
        self.phase_name = "droplet_search"

        # Images / measurements
        self.background_image = None
        self.droplet_image = None
        self.num_images = 20
        self.image_counter = 0
        self.circularity_threshold = 1.15
        self.droplet_positions, self.droplet_focus = [], []
        self.circularity_values, self.droplet_volumes = [], []
        self.measurements = []

        # --- lifecycle/guards ---
        self._aborted = False
        self._finished = False

        # Pressure guardrails
        try:
            p_lo, p_hi = self.model.machine_model.get_print_pressure_bounds()
        except Exception:
            p_lo, p_hi = 0.3, 1.5
        self.min_pressure, self.max_pressure = float(p_lo), float(p_hi)
        self.pressure_step = 0.02
        self.new_pressure = None

        # Upstream calibration
        self._ready = True
        self._import_calibration_data()
        if not self._ready:
            return

        # Time-of-flight plan
        self.sphere_delay_us = 8000
        self.target_delay_us = int(max(0, self.emergence_time_us + self.sphere_delay_us))
        self.delay_offsets_us = [0, +500, -500, +1000, -1000, +1500, -1500]
        self._delay_try_index = 0
        self.min_delay_us, self.max_delay_us = 0, 40000
        self.target_delay_us = self._clamp_delay(self.target_delay_us)

        # Movement safety
        self.max_center_step, self.max_focus_step = 1200, 16
        self.x_lo, self.x_hi = self._get_axis_bounds_safe('X', default_span=20000)
        self.y_lo, self.y_hi = self._get_axis_bounds_safe('Y', default_span=10000)
        self.z_lo, self.z_hi = self._get_axis_bounds_safe('Z', default_span=20000)

        # Predict target AFTER bounds are known
        self.predicted_target = self._predict_stage_target(self.target_delay_us)

        # Focus control
        self.focus_dir, self.focus_step = +1, 16
        self.focus_min_step = 8
        self.focus_dir_switches, self.focus_switch_limit = 0, 6
        self.last_focus_val = None
        self.focus_ok_threshold = 5_000_000

        # Focus robustness
        self._focus_best = 0.0               # best focus seen during this run
        self._focus_same_dir_tries = 0       # how many steps we’ve tried in current dir since last improvement
        self._focus_moves_done = 0
        self._focus_move_budget = 60         # absolute safety cap on focus moves
        self._min_focus_gain = 0.05          # require ≥5% improvement to call it “better” (noise guard)

        # Retry counters
        self._not_found_count, self._not_found_limit = 0, 10
        self._lost_count, self._lost_limit = 0, 5

        # ----- states -----
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
        self.state_final = QFinalState()

        # Handlers
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
        self.state_final.entered.connect(self.onCalibrationCompleted)

        # Transitions
        t0 = QSignalTransition(); t0.setSenderObject(self.calibration_manager)
        t0.setSignal(b"2moveCompleted()"); t0.setTargetState(self.state_prepare_background)
        self.state_move_to_target.addTransition(t0)

        t1a = QSignalTransition(); t1a.setSenderObject(self.calibration_manager)
        t1a.setSignal(b"2settingsChangeCompleted()"); t1a.setTargetState(self.state_capture_background)
        self.state_prepare_background.addTransition(t1a)

        t1 = QSignalTransition(); t1.setSenderObject(self.calibration_manager)
        t1.setSignal(b"2captureCompleted()"); t1.setTargetState(self.state_set_delay)
        self.state_capture_background.addTransition(t1)

        t2 = QSignalTransition(); t2.setSenderObject(self.calibration_manager)
        t2.setSignal(b"2settingsChangeCompleted()"); t2.setTargetState(self.state_capture_droplet)
        self.state_set_delay.addTransition(t2)

        t3 = QSignalTransition(); t3.setSenderObject(self.calibration_manager)
        t3.setSignal(b"2captureCompleted()"); t3.setTargetState(self.state_analyze)
        self.state_capture_droplet.addTransition(t3)

        # analyze → set_delay (no droplet)
        t4 = QSignalTransition(); t4.setSenderObject(self); t4.setSignal(b"2continueSearch()")
        t4.setTargetState(self.state_set_delay)
        self.state_analyze.addTransition(t4)

        # analyze → center (droplet found)
        t5 = QSignalTransition(); t5.setSenderObject(self); t5.setSignal(b"2dropletFound()")
        t5.setTargetState(self.state_center)
        self.state_analyze.addTransition(t5)

        # center → set_delay when droplet lost (already added)
        t4c = QSignalTransition(); t4c.setSenderObject(self); t4c.setSignal(b"2continueSearch()")
        t4c.setTargetState(self.state_set_delay)
        self.state_center.addTransition(t4c)

        # >>> FIX #1: separate moveCompleted transitions per state (no reuse!)
        t7_center = QSignalTransition(); t7_center.setSenderObject(self.calibration_manager)
        t7_center.setSignal(b"2moveCompleted()"); t7_center.setTargetState(self.state_capture_droplet)
        self.state_center.addTransition(t7_center)

        t7_char = QSignalTransition(); t7_char.setSenderObject(self.calibration_manager)
        t7_char.setSignal(b"2moveCompleted()"); t7_char.setTargetState(self.state_capture_droplet)
        self.state_characterization.addTransition(t7_char)
        # <<<

        # center → characterization when centered
        t6 = QSignalTransition(); t6.setSenderObject(self); t6.setSignal(b"2dropletCentered()")
        t6.setTargetState(self.state_characterization)
        self.state_center.addTransition(t6)

        # characterization loop
        t8 = QSignalTransition(); t8.setSenderObject(self); t8.setSignal(b"2continueCharacterization()")
        t8.setTargetState(self.state_capture_droplet)
        self.state_characterization.addTransition(t8)

        t8b = QSignalTransition(); t8b.setSenderObject(self); t8b.setSignal(b"initiateCharacterizationAnalysis()")
        t8b.setTargetState(self.state_analyze_characterization)
        self.state_characterization.addTransition(t8b)

        tP = QSignalTransition(); tP.setSenderObject(self); tP.setSignal(b"2changePressure()")
        tP.setTargetState(self.state_change_pressure)
        self.state_characterization.addTransition(tP)

        tPdone = QSignalTransition(); tPdone.setSenderObject(self.calibration_manager)
        tPdone.setSignal(b"2settingsChangeCompleted()"); tPdone.setTargetState(self.state_capture_droplet)
        self.state_change_pressure.addTransition(tPdone)

        t10 = QSignalTransition(); t10.setSenderObject(self); t10.setSignal(b"characterizationCompleted()")
        t10.setTargetState(self.state_final)
        self.state_analyze_characterization.addTransition(t10)

        # Add states
        for s in (self.state_move_to_target, self.state_prepare_background, self.state_capture_background,
                  self.state_set_delay, self.state_capture_droplet, self.state_analyze, self.state_center,
                  self.state_characterization, self.state_change_pressure, self.state_analyze_characterization,
                  self.state_final):
            self.state_machine.addState(s)
        self.state_machine.setInitialState(self.state_move_to_target)

    # ----- utils -----
    def _import_calibration_data(self):
        self.vel_steps_per_s = self.calibration_manager.get_trajectory_vector()  # (vX, vY, vZ) steps/s
        self.nozzle_center_machine = self.calibration_manager.get_nozzle_center()
        self.emergence_time_us = self.calibration_manager.get_emergence_time()
        self.prev_background = self.calibration_manager.get_background_image()
        if (self.vel_steps_per_s is None or self.nozzle_center_machine is None
            or self.emergence_time_us is None or self.prev_background is None):
            self._ready = False
            # self.calibrationError.emit("Must complete trajectory + nozzle center + emergence first")
            return self._abort("Must complete trajectory + nozzle center + emergence first")

    def _clamp_delay(self, d_us:int)->int:
        return int(max(self.min_delay_us, min(self.max_delay_us, int(d_us))))

    def _get_axis_bounds_safe(self, axis:str, default_span:int):
        try:
            lo, hi = self.model.machine_model.get_axis_bounds(axis)
            return int(lo), int(hi)
        except Exception:
            base = int(self.nozzle_center_machine.get(axis, 0))
            print(f"Using {axis} bounds from nozzle center: {base} ± {default_span}")
            return base - default_span, base + default_span

    def _clamp_abs(self, X:int, Y:int, Z:int):
        Xc = max(self.x_lo, min(self.x_hi, int(X)))
        Yc = max(self.y_lo, min(self.y_hi, int(Y)))
        Zc = max(self.z_lo, min(self.z_hi, int(Z)))
        return Xc, Yc, Zc

    def _safe_move_absolute(self, XYZ_tuple):
        if self._is_dead():
            return
        X, Y, Z = self._clamp_abs(*map(int, XYZ_tuple))
        cur = self.model.machine_model.get_current_position_dict()
        if (X == int(cur['X'])) and (Y == int(cur['Y'])) and (Z == int(cur['Z'])):
            # No movement necessary; synthesize completion to keep the FSM flowing.
            self.calibration_manager.emitMoveCompleted()
            return
        self.calibration_manager.moveAbsoluteRequested.emit((X, Y, Z),
                                                            self.calibration_manager.emitMoveCompleted)

    def _safe_move_relative(self, dXYZ_tuple):
        if self._is_dead():
            return
        cur = self.model.machine_model.get_current_position_dict()
        tgt = (cur['X'] + int(dXYZ_tuple[0]),
               cur['Y'] + int(dXYZ_tuple[1]),
               cur['Z'] + int(dXYZ_tuple[2]))
        self._safe_move_absolute(tgt)
    # <<<

    def _predict_stage_target(self, delay_us:int):
        dt_s = max(0.0, (int(delay_us) - int(self.emergence_time_us)) * 1e-6)
        vX, vY, vZ = map(float, self.vel_steps_per_s)
        X = int(round(self.nozzle_center_machine['X'] + vX * dt_s))
        Y = int(round(self.nozzle_center_machine['Y'] + vY * dt_s))
        Z = int(round(self.nozzle_center_machine['Z'] + (-vZ) * dt_s))  # Z inverted
        return self._clamp_abs(X, Y, Z)

    def _bounded_center_move(self, droplet_xy, target_xy):
        dX, dY, dZ = self.model.droplet_camera_model.calculate_move_to_target(droplet_xy, target_xy)
        dX = int(max(-self.max_center_step, min(self.max_center_step, dX)))
        dZ = int(max(-self.max_center_step, min(self.max_center_step, dZ)))
        return (dX, 0, dZ)
    
    def _is_dead(self) -> bool:
        return self._aborted or self._finished

    def _abort(self, msg: str):
        """Stop issuing commands and stop the FSM, then raise the error once."""
        if self._aborted:
            return
        self._aborted = True
        try:
            self.state_machine.stop()
        except Exception:
            pass
        self.calibrationError.emit(msg)

    # ----- states (unchanged handlers omitted for brevity; keep yours) -----
    @Slot()
    def onMoveToTarget(self):
        if self._is_dead():
            return
        if not self._ready:
            # self.calibrationError.emit("Droplet search prerequisites missing")
            return self._abort("Droplet search prerequisites missing.")
        self.stageChanged.emit(f"Moving to predicted target @ {self.target_delay_us} μs")
        self._safe_move_absolute(self.predicted_target)

    @Slot()
    def onPrepareBackground(self):
        if self._is_dead():
            return
        self.stageChanged.emit("Capturing background at target")
        self.calibration_manager.changeSettingsRequested.emit(
            {"num_droplets": 0},
            self.calibration_manager.emitSettingsChangeCompleted
        )

    @Slot()
    def onCaptureBackground(self):
        if self._is_dead():
            return
        self._capture_with_policy(
            set_attr="background_image",
            stage_text="Capturing background image",
            attempts_total=3, retry_delay_ms=100, guard_timeout_ms=10_000,
            final_error_msg="Failed to capture background image."
        )

    @Slot()
    def onSetDelay(self):
        if self._is_dead():
            return
        if self._delay_try_index < len(self.delay_offsets_us):
            d_us = self.target_delay_us + self.delay_offsets_us[self._delay_try_index]
            self._delay_try_index += 1
        else:
            self._not_found_count += 1
            if self._not_found_count > self._not_found_limit:
                # self.calibrationError.emit("Droplet not found (max retries).")
                return self._abort("Droplet not found (max retries).")
            self.stageChanged.emit("Droplet not found yet → nudging along velocity and retrying")
            vX, vY, vZ = map(float, self.vel_steps_per_s)
            nudge = 0.002
            self._safe_move_relative((int(vX * nudge), int(vY * nudge), int((-vZ) * nudge)))  # Z inverted
            self._delay_try_index = 0
            d_us = self.target_delay_us + self.delay_offsets_us[self._delay_try_index]
            self._delay_try_index += 1

        self.current_delay_us = self._clamp_delay(d_us)
        self.stageChanged.emit(f"Setting flash delay to {self.current_delay_us} μs")
        self.calibration_manager.changeSettingsRequested.emit(
            {"flash_delay": int(self.current_delay_us), "num_droplets": 1},
            self.calibration_manager.emitSettingsChangeCompleted
        )

    @Slot()
    def onCaptureDroplet(self):
        if self._is_dead():
            return
        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text=f"Capturing droplet @ {self.current_delay_us} μs",
            attempts_total=5, retry_delay_ms=75, guard_timeout_ms=10_000,
            final_error_msg=f"Failed to capture droplet @ {self.current_delay_us} μs."
        )

    @Slot()
    def onAnalyze(self):
        if self._is_dead():
            return
        self.stageChanged.emit("Analyzing droplet for contour")
        contour, overlay = self.model.droplet_camera_model.identify_droplet_contour(
            self.droplet_image, self.background_image
        )
        if contour is None:
            self.stageChanged.emit("No droplet: trying next delay/position")
            self.presentImageSignal.emit(overlay)
            self.emitContinueSearch()
            return

        x, y, w, h = cv2.boundingRect(contour)
        cxy = (x + w//2, y + h//2)
        self.presentImageSignal.emit(overlay)
        self.measurements.append({"flash_delay": int(self.current_delay_us), "center": cxy})
        self._lost_count = 0
        self.emitDropletFound()

    @Slot()
    def onCenter(self):
        if self._is_dead():
            return
        self.stageChanged.emit("Centering droplet in frame")
        contour, overlay = self.model.droplet_camera_model.identify_droplet_contour(
            self.droplet_image, self.background_image
        )
        if contour is None:
            self._lost_count += 1
            if self._lost_count > self._lost_limit:
                # self.calibrationError.emit("Droplet repeatedly lost during centering.")
                return self._abort("Droplet repeatedly lost during centering.")
            self.stageChanged.emit("Droplet lost while centering → retrying")
            self.presentImageSignal.emit(overlay)
            self.emitContinueSearch()
            return

        x, y, w, h = cv2.boundingRect(contour)
        cxy = (x + w//2, y + h//2)
        H, W = overlay.shape[:2]
        target = (W//2, H//2)
        tol = 150
        if abs(cxy[0]-target[0]) <= tol and abs(cxy[1]-target[1]) <= tol:
            self.stageChanged.emit("Droplet centered")
            self.emitDropletCentered()
            return

        dX, dY, dZ = self._bounded_center_move(cxy, target)
        self.stageChanged.emit(f"Recenter move (clamped): {dX},{dY},{dZ}")
        self._safe_move_relative((dX, dY, dZ))

    @Slot()
    def onCharacterization(self):
        if self._is_dead():
            return
        self.stageChanged.emit("Characterizing droplet")
        result, annotated = self.model.droplet_camera_model.characterize_droplet(
            self.droplet_image, self.background_image
        )
        if result is None:
            self.stageChanged.emit("Capture failed → recapturing")
            self.emitContinueCharacterization()
            return
        if result == 'Multiple':
            cur_p = float(self.model.machine_model.get_current_print_pressure())
            self.new_pressure = max(self.min_pressure, cur_p - self.pressure_step)
            if self.new_pressure >= cur_p and cur_p <= self.min_pressure:
                # self.calibrationError.emit("Minimum pressure reached (multiple droplets persist)")
                return self._abort("Minimum pressure reached (multiple droplets persist).")
            self.stageChanged.emit(f"Multiple droplets → decreasing pressure to {self.new_pressure:.3f} psi")
            self.droplet_positions.clear(); self.droplet_focus.clear()
            self.circularity_values.clear(); self.droplet_volumes.clear()
            self.image_counter = 0
            self.emitChangePressure()
            return

        focus_val = float(result.get('focus', 0.0))
        self.presentImageSignal.emit(annotated)
        # ---------- focus control with 2-step probe in one direction ----------
        if focus_val < self.focus_ok_threshold:
            # First sample initializes “best”
            if self._focus_best <= 0.0:
                self._focus_best = focus_val

            improved = (focus_val >= (1.0 + self._min_focus_gain) * self._focus_best)

            if improved:
                # Keep direction, reset probe counter, update best and gently reduce step
                self._focus_best = focus_val
                self._focus_same_dir_tries = 0
                self.focus_step = max(self.focus_min_step, self.focus_step // 2)
            else:
                # Not improved: try a second step in the SAME direction before switching
                self._focus_same_dir_tries += 1
                if self._focus_same_dir_tries >= 3:
                    # Switch direction after two non-improving probes, expand step a bit
                    self._focus_same_dir_tries = 0
                    self.focus_dir *= -1
                    self.focus_dir_switches += 1
                    self.focus_step = min(self.max_focus_step, max(self.focus_min_step, self.focus_step * 2))
                    if self.focus_dir_switches > self.focus_switch_limit:
                        return self._abort("Focus oscillation limit reached.")

            # Budget guard
            self._focus_moves_done += 1
            if self._focus_moves_done > self._focus_move_budget:
                return self._abort("Focus move budget exceeded.")

            dY = int(self.focus_dir * self.focus_step)
            self.stageChanged.emit(f"Focus low ({focus_val:.0f}) → Y move {dY} steps")
            self._safe_move_relative((0, dY, 0))
            return
        # ---------------------------------------------------------------------


        self.focus_step = max(self.focus_min_step, self.focus_step // 2)
        self.circularity_values.append(float(result.get("circularity_ellipse", 99.0)))
        self.droplet_positions.append(tuple(map(int, result.get("center", (0,0)))))
        self.droplet_focus.append(focus_val)
        self.droplet_volumes.append(float(result.get("volume", 0.0)))
        self.image_counter += 1

        if self.image_counter < self.num_images:
            self.emitContinueCharacterization()
        else:
            self.emitInitiateAnalyzeCharacterization()

    @Slot()
    def onChangePressure(self):
        if self._is_dead():
            return
        self.stageChanged.emit("Changing pressure")
        self.calibration_manager.changeSettingsRequested.emit(
            {"print_pressure": float(self.new_pressure)},
            self.calibration_manager.emitSettingsChangeCompleted
        )

    @Slot()
    def onAnalyzeCharacterization(self):
        if self._is_dead():
            return
        self.stageChanged.emit("Analyzing droplet characterization")
        if not self.droplet_volumes:
            # self.calibrationError.emit("No droplet volumes captured.")
            return self._abort("No droplet volumes captured.")
        if not all(c < self.circularity_threshold for c in self.circularity_values):
            # self.calibrationError.emit("Droplets not circular enough — consider a later delay.")
            return self._abort("Droplets not circular enough — consider a later delay.")

        mean_vol = float(np.mean(self.droplet_volumes))
        cv_vol = float(np.std(self.droplet_volumes) / (mean_vol + 1e-9) * 100.0)
        mean_center = tuple(np.mean(np.array(self.droplet_positions), axis=0).astype(int))
        final_img = self._annotate_final(mean_center, mean_vol, cv_vol)
        self.presentImageSignal.emit(final_img)

        machine_position = self.model.machine_model.get_current_position_dict()
        drop_machine = self.model.droplet_camera_model.convert_pixel_position_to_motor_steps(
            mean_center, machine_position
        )

        # ---- IMPORTANT: include raw replicate arrays so the manager can flatten them ----
        results = {
            "delay_us": int(self.current_delay_us),
            "positions_px": self.droplet_positions,
            "droplet_positions": self.droplet_positions,
            "droplet_volumes": [float(v) for v in self.droplet_volumes],
            "circularity_values": [float(c) for c in self.circularity_values],
            "droplet_focus": [float(f) for f in self.droplet_focus],
            "mean_center_px": mean_center,
            "mean_volume": mean_vol,
            "cv_volume_percent": cv_vol,
            "mean_position_machine": drop_machine,
        }

        # Measurements you collected during search are still included
        self.calibrationDataUpdated.emit({"measurements": self.measurements, "result": results})
        self.emitCharacterizationCompleted()

    @Slot()
    def onCalibrationCompleted(self):
        if self._finished:
            return
        self._finished = True
        try:
            self.state_machine.stop()
        except Exception:
            pass
        self.stageChanged.emit("Droplet search + characterization complete")
        self.calibrationCompleted.emit()

    # helpers
    def _annotate_final(self, mean_center, mean_vol, cv_vol):
        img = self.droplet_image.copy()
        for p in self.droplet_positions:
            cv2.circle(img, p, 5, (255, 0, 0), -1)
        cv2.circle(img, mean_center, 8, (0, 255, 0), -1)
        cv2.putText(img, f"Mean vol: {mean_vol:.2f}", (10, 32), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,0), 2)
        cv2.putText(img, f"CV vol: {cv_vol:.2f}%", (10, 64), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,0), 2)
        return img

    # emitters
    def emitContinueSearch(self): self.continueSearch.emit()
    def emitDropletFound(self): self.dropletFound.emit()
    def emitDropletCentered(self): self.dropletCentered.emit()
    def emitContinueCharacterization(self): self.continueCharacterization.emit()
    def emitInitiateAnalyzeCharacterization(self): self.initiateCharacterizationAnalysis.emit()
    def emitCharacterizationCompleted(self): self.characterizationCompleted.emit()

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
        self.exposure_time = 30000
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
        Robustly estimate emergence area and overlay.
        Returns: (area:int|None, center:(x,y)|None, overlay_bgr)
        Rejects background/ghosts via:
          - min foreground pixel count after threshold
          - min contour area
          - min peak intensity in the diff
          - optional top-band gate (nozzle expected near top)
        """
        import numpy as np, cv2
        if background is None or image is None:
            return None, None, image

        # Tunables (adjust for your scene)
        MIN_FG_PIX       = 60      # require at least this many mask pixels
        MIN_CONTOUR_AREA = 40      # reject tiny specks
        MIN_PEAK_DELTA   = 25      # min 95th-percentile of diff (0..255)
        TOP_BAND_FRAC    = 0.45    # accept contours whose top is in top 45% image

        # --- diff → gray ---
        if image.ndim == 3 and image.shape[2] == 3:
            diff = cv2.absdiff(image, background)
            gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        else:
            diff = cv2.absdiff(image, background)
            gray = diff if diff.ndim == 2 else cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

        h, w = gray.shape[:2]

        # --- denoise + threshold (guarded) ---
        blur = cv2.GaussianBlur(gray, (5,5), 0)

        # Try mean+3σ (harder threshold) first; fall back to Otsu only if too strict
        mu, sd = float(np.mean(blur)), float(np.std(blur))
        t_hard = max(20, int(mu + 3.0 * sd))
        _, th = cv2.threshold(blur, t_hard, 255, cv2.THRESH_BINARY)
        if np.count_nonzero(th) < MIN_FG_PIX:
            # too strict → try Otsu
            _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # morphology cleanup
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN,  k, iterations=1)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k, iterations=1)

        # quick reject: not enough foreground
        if np.count_nonzero(th) < MIN_FG_PIX:
            return None, None, image

        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, None, image

        def top_y(c): return int(c[:,:,1].min())
        areas = [cv2.contourArea(c) for c in contours]
        keep  = [(c, a) for (c, a) in zip(contours, areas) if a >= MIN_CONTOUR_AREA]
        if not keep:
            return None, None, image

        # Prefer top-most; break ties by larger area
        keep.sort(key=lambda ca: (top_y(ca[0]), -ca[1]))
        chosen, a_cont = keep[0]
        ty = top_y(chosen)

        # top-band gate (optional but helpful)
        if ty > int(TOP_BAND_FRAC * h):
            return None, None, image

        x, y, ww, hh = cv2.boundingRect(chosen)
        area = int(ww * hh)
        center = (x + ww//2, y + hh//2)

        # Peak intensity check inside bbox
        roi = gray[y:y+hh, x:x+ww]
        if roi.size == 0:
            return None, None, image
        p95 = float(np.percentile(roi, 95))
        if p95 < MIN_PEAK_DELTA:
            return None, None, image

        overlay = image.copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        cv2.drawContours(overlay, [chosen], -1, (0,255,0), 2)
        cv2.rectangle(overlay, (x, y), (x+ww, y+hh), (255,0,0), 2)
        cv2.putText(overlay, f'Area:{area} p95:{int(p95)}', (x+ww+5, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (50,200,50), 2)

        return area, center, overlay
    
    def identify_droplets(self, image, background, nozzle_center, min_area=1000):
        """
        Robust droplet identification:
          - works on diff = |image - background|
          - restricts to ROI below the nozzle row (+margin)
          - morphology to clean noise
          - classifies "nozzle-attached" area (area below nozzle within any bbox that contains the nozzle center)
          - counts free droplets entirely below the nozzle
        Returns: (droplets_list_or_None, nozzle_attached_area_or_None, overlay_bgr)
        """

        image_gray, diff = self.calc_diff_image(image, background)
        if diff is None or nozzle_center is None:
            return None, None, image

        h, w = diff.shape[:2]
        nzx, nzy = int(nozzle_center[0]), int(nozzle_center[1])
        nzy = max(0, min(h-1, nzy))

        # ---- ROI: only rows at/under the nozzle (+ small margin) ----
        MARGIN = 8
        mask = np.zeros_like(diff, dtype=np.uint8)
        mask[max(0, nzy - MARGIN):, :] = 255

        # ---- threshold (hard first, then Otsu fallback) ----
        blur = cv2.GaussianBlur(diff, (5,5), 0)
        mu, sd = float(np.mean(blur[mask>0])), float(np.std(blur[mask>0]))
        t_hard = max(20, int(mu + 3.0 * sd))
        _, th = cv2.threshold(blur, t_hard, 255, cv2.THRESH_BINARY)
        th = cv2.bitwise_and(th, th, mask=mask)

        MIN_FG = 60
        if np.count_nonzero(th) < MIN_FG:
            _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            th = cv2.bitwise_and(th, th, mask=mask)

        # morphology cleanup
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN,  k, iterations=1)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k, iterations=1)
        if np.count_nonzero(th) < MIN_FG:
            return None, None, image

        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, None, image

        overlay = image.copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        cv2.line(overlay, (0, nzy), (w-1, nzy), (128, 128, 255), 1)  # nozzle row reference
        cv2.circle(overlay, (nzx, nzy), 5, (255, 0, 0), -1)

        nozzle_attached_area = 0
        droplets = []

        for c in contours:
            area = cv2.contourArea(c)
            if area < max(40, min_area*0.05):  # drop tiny specks up-front
                continue
            x, y, ww, hh = cv2.boundingRect(c)

            # ignore blobs whose entire bbox is above nozzle row (reflection/ghosts)
            if y + hh <= nzy:
                continue

            bbox_contains_nozzle = (x <= nzx <= x+ww) and (y <= nzy <= y+hh)

            if bbox_contains_nozzle:
                # nozzle-attached: only count below the nozzle row
                # clip the bbox to rows >= nzy
                below_h = (y + hh) - nzy
                if below_h > 0:
                    area_below = below_h * ww
                    nozzle_attached_area = max(nozzle_attached_area, int(area_below))
                cv2.rectangle(overlay, (x, y), (x+ww, y+hh), (0, 200, 255), 2)
            else:
                # free droplet(s) below the nozzle
                if area >= min_area:
                    cx, cy = x + ww//2, y + hh//2
                    droplets.append((cx, cy))
                    cv2.rectangle(overlay, (x, y), (x+ww, y+hh), (0, 0, 255), 2)
                    cv2.circle(overlay, (cx, cy), 6, (0, 0, 255), -1)

        if droplets:
            cv2.putText(overlay, f'Droplets: {len(droplets)}', (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0), 2)

        return (droplets if droplets else None,
                (nozzle_attached_area if nozzle_attached_area > 0 else None),
                overlay)

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
        