from unittest import result
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

    readinessChanged = Signal(dict)   # {"pressure_scan": {"missing": [...], "ready": bool}, ...}

    # Map alternate phase names to canonical keys
    PHASE_ALIASES = {
        "pressure": "pressure_calibration",
        "pressure_calibration": "pressure_calibration",
        "pressure_scan": "pressure_scan",
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

        self._last_pressure_scan_result = None
        self._pressure_traj_result = None

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
        if not self.calibration_queue:
            self.calibrationStageChanged.emit("No calibrations in queue.", "red")
            self.calibrationQueueCompleted.emit()
            return

        next_cal = self.calibration_queue.pop(0)

        mapping = {
            'nozzle_position': NozzlePositionCalibrationProcess,
            'nozzle_focus': NozzleFocusCalibrationProcess,
            'droplet_emergence': DropletEmergenceCalibrationProcess,
            'pressure': PressureCalibrationProcess,
            'pressure_scan': PressureBandCalibrationProcess,
            'trajectory': TrajectoryCalibrationProcess,
            'droplet_search': DropletSearchCalibrationProcess,
        }
        proc_cls = mapping.get(next_cal)
        if not proc_cls:
            self.calibrationStageChanged.emit(f"Unknown calibration '{next_cal}'", "red")
            self.start_calibration_queue()  # try next
            return

        if not self._try_start_process(proc_cls):
            # Stop the queue on error to avoid cascading failures.
            self.calibrationStageChanged.emit("Calibration queue stopped due to missing prerequisites.", "red")
            self.clear_calibration_queue()
            self.calibrationQueueCompleted.emit()

    def start_active_calibration(self):
        if self.activeCalibration is not None:
            # Ensure we have an open run to write into
            if self._run_idx is None:
                # Create a default session in CWD if the caller forgot
                self.begin_session(self.model.experiment_model.get_calibration_file_path(), notes="auto-started session")
            self.activeCalibration.stageChanged.connect(self.onCalibrationStageChanged)
            self.activeCalibration.calibrationCompleted.connect(self.onCalibrationCompleted)
            self.activeCalibration.calibrationError.connect(self.onCalibrationError)
            self.activeCalibration.calibrationDataUpdated.connect(self.onCalibrationDataUpdated)
            self.activeCalibration.presentImageSignal.connect(self.onPresentImage)
            self.activeCalibration.start()

    def stop(self):
        if self.activeCalibration is not None:
            # Prefer graceful finalize if the process supports it
            if hasattr(self.activeCalibration, "requestGracefulStop"):
                try:
                    self.activeCalibration.requestGracefulStop("User requested graceful stop")
                    return
                except Exception:
                    pass
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

    # def start_pressure_scan_calibration(self):
    #     self.activeCalibration = PressureBandCalibrationProcess(self, self.model)
    #     self.start_active_calibration()

    def start_pressure_scan_calibration(self, *, p_lo: float | None = None, p_hi: float | None = None, step: float | None = None):
        """
        Start the pressure-band scan with optional user-defined range and step.
        """
        kwargs = {}
        if step is not None:
            kwargs["p_step"] = float(step)
        # If your PressureBandCalibrationProcess supports user bounds, pass them:
        if p_lo is not None:
            kwargs["p_start"] = float(p_lo)
        if p_hi is not None:
            kwargs["p_end"] = float(p_hi)
        self._try_start_process(PressureBandCalibrationProcess, **kwargs)

    def start_trajectory_calibration(self):
        self._try_start_process(TrajectoryCalibrationProcess)

    def start_pressure_trajectory_calibration(self):
        self._try_start_process(PressureTrajectoryCalibrationProcess)

    def start_droplet_search_calibration(self):
        self._try_start_process(DropletSearchCalibrationProcess)

    def start_manual_droplet_characterization(self, *, start_delay_us: int | None = None):
        self._try_start_process(DropletSearchCalibrationProcess, manual_start=True)

    def start_pressure_sweep_characterization(self, *, p_step=0.2, sphere_delay_us=10000, replicates_per_pressure=20, order="desc"):
        self._try_start_process(PressureSweepCharacterizationProcess,
            p_step=p_step,
            sphere_delay_us=sphere_delay_us,
            replicates_per_pressure=replicates_per_pressure,
            order=order
        )

    def start_droplet_timecourse_process(self):
        self._try_start_process(DropletTimecourseProcess)

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

    def set_background_image(self, background): 
        self.background_image = background
        self._emit_readiness()
    def set_nozzle_center(self, center): 
        self.nozzle_center = center
        self._emit_readiness()
    def set_nozzle_center_image_position(self, center): 
        self.nozzle_center_image_position = center
        self._emit_readiness()
    def set_trajectory_vector(self, vector): 
        self.droplet_trajectory_vector = vector
        self._emit_readiness()
    def set_trajectory_delay(self, delay): 
        self.trajectory_delay = delay
        self._emit_readiness()
    def set_min_start_delay(self, delay): 
        self.min_start_delay = delay
        self._emit_readiness()
    def set_intermediate_droplet_position(self, position): 
        self.intermediate_droplet_position = position
        self._emit_readiness()
    def set_primary_pressure_band(self, result): 
        print("Setting primary pressure band:", result)
        self._last_pressure_scan_result = result
        self._emit_readiness()
    def set_pressure_trajectory_result(self, result_dict):
        self._pressure_traj_result = result_dict
        self._emit_readiness()

    def get_background_image(self): return self.background_image
    def get_nozzle_center(self): return self.nozzle_center
    def get_nozzle_center_image_position(self): return self.nozzle_center_image_position
    def get_trajectory_vector(self): return self.droplet_trajectory_vector
    def get_trajectory_delay(self): return self.trajectory_delay
    def get_min_start_delay(self): return self.min_start_delay
    def get_intermediate_droplet_position(self): return self.intermediate_droplet_position

    def get_primary_pressure_band(self):
        res = self._last_pressure_scan_result
        if not res:
            return None
        band = res.get("primary_band")
        if band and len(band) == 2:
            return float(band[0]), float(band[1])
        return None
    
    def get_pressure_trajectory_result(self):
        return self._pressure_traj_result

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

    @Slot(str)
    def onCalibrationStageChanged(self, message):
        self.calibrationStageChanged.emit(message, "dark_gray")

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
        # self._try_append_flat_rows_from_payload(run, phase_key, payload)

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
            # Prefer a stable name if available; fallback to str()
            return getattr(ph.get_stock_solution(), "reagent_name", None) or str(ph.get_stock_solution())
        except Exception:
            return None

    def _safe_get_printer_head_id(self):
        try:
            ph = self.model.rack_model.get_gripper_printer_head()
            # Prefer a stable id/serial if available; fallback to str()
            return getattr(ph, "serial", None) or getattr(ph, "id", None) or str(ph)
        except Exception:
            return None

    def _process_missing(self, proc_cls) -> list[str]:
        fn = getattr(proc_cls, "missing_requirements", None)
        if callable(fn):
            return list(fn(self)) or []
        return []

    def _try_start_process(self, proc_cls, *args, **kwargs) -> bool:
        missing = self._process_missing(proc_cls)
        phase_name = getattr(proc_cls, "phase_name", None) or getattr(proc_cls(self, self.model), "phase_name", "unknown")

        if missing:
            msg = f"{phase_name.replace('_',' ').title()} prerequisites missing: {', '.join(missing)}"
            self.calibrationStageChanged.emit(msg, "red")
            self.calibrationError.emit(msg)
            return False

        self.activeCalibration = proc_cls(self, self.model, *args, **kwargs)
        self.start_active_calibration()
        return True

    def _emit_readiness(self):
        # Helper to pack readiness + missing list for each process class
        def pack(proc_cls):
            missing = proc_cls.missing_requirements(self)
            return {"ready": len(missing) == 0, "missing": missing}

        readiness = {
            "pressure_calibration":           pack(PressureCalibrationProcess),
            "pressure_scan":                  pack(PressureBandCalibrationProcess),
            "droplet_trajectory":             pack(TrajectoryCalibrationProcess),
            "trajectory_pressure_scan":       pack(PressureTrajectoryCalibrationProcess),
            "droplet_characterization":       pack(DropletSearchCalibrationProcess),
            "pressure_sweep_characterization":pack(PressureSweepCharacterizationProcess),
        }
        self.readinessChanged.emit(readiness)

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
        self.initial_flash_delay_us = max(self.model.machine_model.get_print_pulse_width() + 2600, 0)
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
        keep = [(c, a) for (c, a) in zip(contours, areas) if a >= 2000]
        if not keep:
            dbg = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
            return ("NONE", None, 0, dbg)

        # choose the lowest contour (max y); tie-break by larger area
        def contour_bottom_y(contour):
            ys = contour[:, :, 1].flatten()
            return int(ys.max())

        keep_sorted = sorted(
            keep,
            key=lambda ca: (-contour_bottom_y(ca[0]), -ca[1])
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
            self.calibration_manager.set_nozzle_center_image_position(nozzle_px)
            self.calibration_manager.set_nozzle_center(machine_pos)
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
            keep = [(c, a_) for (c, a_) in zip(contours, areas) if a_ >= 2000]
            if not keep: self._last_bbox = None; self._last_mask = None; return None
            # choose the lowest contour (max y); tie-break by larger area
            def contour_bottom_y(contour):
                ys = contour[:, :, 1].flatten()
                return int(ys.max())

            keep_sorted = sorted(
                keep,
                key=lambda ca: (-contour_bottom_y(ca[0]), -ca[1])
            )
            chosen, chosen_area = keep_sorted[0]
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
    DELAY_MIN = 1500          # μs
    DELAY_MAX = 8000          # μs
    COARSE_STEP = 500
    FINE_STEP   = 100
    BIG_JUMP_US = 800         # used during "visibility escalation"
    MAX_EVALS   = 50
    REPLICATES  = 3
    MONO_TOL_FRAC = 0.10      # monotonic tolerance (10% increase considered suspicious)

    # acceptable area band (target window)
    MIN_AREA = 3000
    MAX_AREA = 6000

    # start-delay model vs pulse width (μs)
    START_DELAY_BASE_US = 5000
    START_DELAY_REF_PW  = 3000
    START_DELAY_SLOPE   = 0.5   # +0.5 μs delay per +1 μs pulse width

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

        self._phase = "seek_visible"   # phases: seek_visible -> scan_down -> fine_adjust
        self._prev_area = None         # last *valid* area (at higher delay)

        # # bracket: (delay, area) where area < min_area (low) and > max_area (high)
        # self._lo = None   # tuple (d, area)
        # self._hi = None   # tuple (d, area)

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
        self._rep_areas.clear()
        self._prev_area = None
        self._phase = "seek_visible"

        # Start delay depends on pulse width (counterintuitively: higher PW ⇒ later emergence ⇒ larger delay)
        self.candidate_delay = self._compute_start_delay_for_pw()
        self.stageChanged.emit(f"Initial candidate delay (PW-adaptive): {self.candidate_delay} μs")

        # keep current nozzle/pressure; ensure no drops for background
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
        self.stageChanged.emit(f"Setting flash delay to {d} μs  [phase={self._phase}]")
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
        self.stageChanged.emit("Analyzing droplet image (emergence)")

        # Use the updated ROI + dark-only method
        area, center, overlay = self.model.droplet_camera_model.calc_emergence_area(
            self.background_image, self.droplet_image
        )
        self.presentImageSignal.emit(overlay)
        self._eval_count += 1

        if area is None:
            area = 0

        self._rep_areas.append(int(area))
        self.stageChanged.emit(f"Delay {self.candidate_delay} μs replicate → area {area}")

        # Need replicates at same delay?
        if len(self._rep_areas) < self.REPLICATES:
            self.replicateContinue.emit()
            return

        # Aggregate replicates
        agg_area = int(median(self._rep_areas))
        self._rep_areas.clear()
        self.measurements.append((self.candidate_delay, agg_area))

        # Enforce monotonic trend: as we DECREASE delay, area should not INCREASE
        if self._prev_area is not None and agg_area > (1.0 + self.MONO_TOL_FRAC) * self._prev_area:
            self.stageChanged.emit(
                f"Non-monotonic increase detected (prev={self._prev_area}, now={agg_area}). Treating as noise."
            )
            # Push further down to bypass spurious edge/glare
            next_delay = self.candidate_delay - self.FINE_STEP
            self._set_next_delay(next_delay)
            if self._eval_count >= self.MAX_EVALS:
                self.calibrationError.emit("Emergence search did not converge (max evaluations)")
                return
            self.continueSearch.emit()
            return

        # Phase logic
        if self._phase == "seek_visible":
            if agg_area <= max(40, int(0.03 * self.MIN_AREA)):
                # Not visible yet → bump UP in big steps (visibility escalation)
                next_delay = self.candidate_delay + self.BIG_JUMP_US
                self.stageChanged.emit(f"No contour; escalating delay to {next_delay} μs")
                if next_delay > self.DELAY_MAX:
                    self.calibrationError.emit("No emergence detected up to maximum delay")
                    return
                self._set_next_delay(next_delay)
                self.continueSearch.emit()
                return
            else:
                # Seen! Start scanning DOWN
                self._prev_area = agg_area
                self._phase = "scan_down"
                self._set_next_delay(self.candidate_delay - self.COARSE_STEP)
                self.continueSearch.emit()
                return

        # When scanning down, accept as soon as we enter the target window
        if self.MIN_AREA <= agg_area <= self.MAX_AREA:
            self.stageChanged.emit("Target area window reached")
            self.calibrationDataUpdated.emit({
                'measurements': self.measurements,
                'result': {'area': agg_area, 'flash_delay': self.candidate_delay}
            })
            machine_pos = self.model.machine_model.get_current_position_dict()
            self.calibration_manager.set_nozzle_center_image_position(center)
            self.calibration_manager.set_nozzle_center(machine_pos)
            self.dropletDetected.emit()
            return

        if self._phase == "scan_down":
            if agg_area > self.MAX_AREA:
                # Still too late (big area) → keep moving earlier
                self._prev_area = agg_area
                self._set_next_delay(self.candidate_delay - self.COARSE_STEP)
                if self._eval_count >= self.MAX_EVALS:
                    self.calibrationError.emit("Emergence search did not converge (max evaluations)")
                    return
                self.continueSearch.emit()
                return

            # We went too far (area < MIN) → fine adjust upward
            self._phase = "fine_adjust"
            self._set_next_delay(self.candidate_delay + self.FINE_STEP)
            self.continueSearch.emit()
            return

        if self._phase == "fine_adjust":
            if agg_area < self.MIN_AREA:
                # Still too small → step later slightly
                self._set_next_delay(self.candidate_delay + self.FINE_STEP)
            elif agg_area > self.MAX_AREA:
                # Overshot again → step earlier slightly
                self._set_next_delay(self.candidate_delay - self.FINE_STEP)
            else:
                # In window
                self.stageChanged.emit("Target area window reached (fine adjust)")
                self.calibrationDataUpdated.emit({
                    'measurements': self.measurements,
                    'result': {'area': agg_area, 'flash_delay': self.candidate_delay}
                })
                machine_pos = self.model.machine_model.get_current_position_dict()
                self.calibration_manager.set_nozzle_center_image_position(center)
                self.calibration_manager.set_nozzle_center(machine_pos)
                self.dropletDetected.emit()
                return

            if self._eval_count >= self.MAX_EVALS:
                self.calibrationError.emit("Emergence fine-adjust did not converge (max evaluations)")
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

    def _compute_start_delay_for_pw(self):
        try:
            pw = float(self.model.machine_model.get_print_pulse_width())
        except Exception:
            pw = float(self.START_DELAY_REF_PW)
        d = self.START_DELAY_BASE_US + self.START_DELAY_SLOPE * (pw - self.START_DELAY_REF_PW)
        return int(self._clamp_delay(d))
    
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
        missing_requirements = self.missing_requirements(calibration_manager)
        if missing_requirements:
            raise ValueError(f"PressureBandCalibrationProcess requires: {', '.join(missing_requirements)}.")
        self.phase_name = "pressure_calibration"

        self.nozzle_position = None
        self.start_delay = None
        self.start_delay_offset =  max(self.model.machine_model.get_print_pulse_width() + 1000, 0)

        # Set initial binary search bounds for pressure (in psi, for example).
        self.lower_pressure = 0.4   # example minimum pressure
        self.upper_pressure = 5.0   # example maximum pressure
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

    @staticmethod
    def missing_requirements(cm) -> list[str]:
        """Return a list of human-readable missing prerequisites."""
        missing = []
        if cm.get_nozzle_center() is None:
            missing.append("Nozzle center (machine coords)")
        if cm.get_nozzle_center_image_position() is None:
            missing.append("Nozzle center (image coords)")
        if cm.get_background_image() is None:
            missing.append("Background image")
        if cm.get_emergence_time() is None:
            missing.append("Emergence time")
        return missing

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
            lo, hi = 0.2, 5.00  # psi, conservative
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

def make_pressure_grid(p0, p1, step, hw_lo, hw_hi):
    import math
    # clamp & order
    lo = max(hw_lo, min(hw_hi, min(p0, p1)))
    hi = max(hw_lo, min(hw_hi, max(p0, p1)))
    # number of *inclusive* points
    n = int(math.floor((hi - lo) / step + 1e-9)) + 1
    grid = [round(lo + i * step, 5) for i in range(max(n, 1))]
    return grid

class PressureBandCalibrationProcess(BaseCalibrationProcess):
    """
    Fixed-range pressure scan for a given pulse width (PW).

    Changes:
      - Scans pressures HIGH → LOW (safe-by-default).
      - Manual early stop (requestGracefulStop) preserves progress.
      - Auto-stop if droplet approaches the nozzle (safety_clearance_px) or nozzle gets wet.
      - Robust state transitions; finalize allowed from any state.

    Result payload (unchanged shape + termination metadata):
      {
        "pulse_width_us": ...,
        "delay_us": ...,
        "pressure_bounds": [P_MIN, P_MAX],
        "pressures": [ ... per-pressure records ... ],
        "single_bands": [[p_lo, p_hi], ...],
        "primary_band": [p_lo, p_hi] | None,
        "terminated_early": bool,
        "stop_reason": str | None,
        "terminate_pressure": float | None
      }
    """

    # State-machine signals
    pressureApplied = Signal()
    replicateReady  = Signal()
    continueScan    = Signal()         # advance to NEXT pressure (goes to state_apply)
    continueReplicate = Signal()       # NEW: capture another rep at SAME pressure (goes to state_capture)
    finalize        = Signal()

    def __init__(self, calibration_manager, model,
                 p_start: float = 0.3,
                 p_end: float = 2.5,
                 p_step: float = 0.05,
                 *,
                 min_reps: int = 5,
                 escalate_to: int = 9,
                 classification_delay_us: int | None = None,
                 reverse_order: bool = True,
                 safety_clearance_px: int = 400,
                 auto_stop_on_nozzle_wet: bool = True,
                 parent=None):
        super().__init__(calibration_manager, model, parent)

        missing_requirements = PressureBandCalibrationProcess.missing_requirements(calibration_manager)
        if missing_requirements:
            raise ValueError(f"PressureBandCalibrationProcess requires: {', '.join(missing_requirements)}.")
        
        self.phase_name = "pressure_scan"

        # --- prerequisites ---
        self.nozzle_center_px   = self.calibration_manager.get_nozzle_center_image_position()
        self.background_image   = self.calibration_manager.get_background_image()
        self.emergence_time_us  = self.calibration_manager.get_emergence_time()
        self._ready = not (self.nozzle_center_px is None or
                           self.background_image is None or
                           self.emergence_time_us is None)

        # --- imaging delay ---
        if classification_delay_us is None:
            try:
                pw = int(self.model.machine_model.get_print_pulse_width())
            except Exception:
                pw = 1500
            classification_delay_us = int(max(0, (self.emergence_time_us or 0) + pw + 1300))
        self.classify_delay_us = int(classification_delay_us)

        # --- pressure bounds ---
        try:
            hw_lo, hw_hi = self.model.machine_model.get_print_pressure_bounds()
        except Exception:
            hw_lo, hw_hi = 0.3, 5.0
        self.P_MIN = float(hw_lo)
        self.P_MAX = float(hw_hi)

        # Requested scan range (we still honor the user’s start/end direction)
        p0, p1 = float(min(p_start, p_end)), float(max(p_start, p_end))
        self._p_lo = max(self.P_MIN, p0)
        self._p_hi = min(self.P_MAX, p1)

        # ---- Adaptive step settings ----
        base_step = abs(float(p_step)) if p_step else 0.1
        self.dp_min = 0.01                         # smallest step when near nozzle
        self.dp_max = 0.05                         # largest allowed step
        self.dp     = max(self.dp_min, min(base_step, self.dp_max))

        # Special jumps for specific states
        self.multiple_big_step = 0.10              # when MULTIPLE → drop faster
        self.none_jump_up      = 0.10              # when NONE → push up to re-acquire
        
        # Movement heuristics (pixels)
        self.small_move_px = 8                    # “barely moved” threshold
        self.large_move_px = 40                    # “moved a lot” threshold

        # --- thresholds & safety ---
        self.nozzle_area_threshold     = 8000
        self.safety_clearance_px       = int(safety_clearance_px)
        self.near_nozzle_px            = int(self.safety_clearance_px * 1.6)
        self.far_nozzle_px             = int(self.safety_clearance_px * 3.0)
        # self.auto_stop_on_nozzle_wet   = bool(auto_stop_on_nozzle_wet)
        self.auto_stop_on_nozzle_wet   = False

        # --- replicate policy ---
        self.min_reps           = int(min_reps)
        self.escalate_to        = int(escalate_to)
        self.replicates_target  = self.min_reps
        self.reps               = []
        self._invalid_skip_count = 0
        self._invalid_skip_cap   = 6
        self._discard_next       = True   # skip first frame after pressure change (settling)

        # --- outputs ---
        self.samples          = []
        self.annotated_image  = None

        # --- flags ---
        self._current_pressure   = None
        self._next_pressure        = float(self._p_hi)  # start at high bound
        self._prev_pressure        = None
        self._prev_dy              = None               # previous (median) distance to nozzle in px
        self._early_stop           = False
        self._stop_reason          = None
        self._terminate_at_pressure = None

        # --- edge refine / backtrack ---
        self.backtrack_after_first_single = True   # new: enable upper-edge backtrack
        self._phase = "scan"                       # scan | refine_upper | refine_lower
        self._upper_bracket = None                 # [lo(single), hi(multiple)]
        self._lower_bracket = None                 # [lo(none/too_close), hi(single)]
        self._edge_eps = 0.01                        # stop refining upper/lower once bracket ≤ 0.01 psi
        self._prev_verdict = None
        self._first_single_pressure = None
        self._min_single_pressure = None
        self._upper_edge_locked = False

        self._lower_edge_locked = False          
        self._lower_edge_value  = None
        self._lower_snap_eps    = self._edge_eps

        self._straddle_bracket  = None          # [lo(none-side), hi(multiple-side)]
        self._bisect_eps        = max(self._edge_eps, 0.01)  # tighter convergence for gap-bisection

        # Upward seek params (used if first verdict is SINGLE)
        self._seek_step = max(self.dp_min, min(0.05, self.dp))  # gentle initial nudge up
        self._seek_step_max = 0.20
        self._seek_growth = 1.7

        # Upward re-acquire params (used if first verdict is NONE or “too close”)
        self._reacquire_step = 0.10
        self._reacquire_step_max = 0.10
        self._reacquire_growth = 1.7

        try:
            self._pulse_width_us = int(self.model.machine_model.get_print_pulse_width())
        except Exception:
            self._pulse_width_us = None

        # ---------- states ----------
        self.state_prepare_bg = QState()
        self.state_apply      = QState()
        self.state_capture    = QState()
        self.state_analyze    = QState()
        self.state_decide     = QState()
        self.state_final      = QFinalState()

        self.state_prepare_bg.entered.connect(self.onPrepareBackground)
        self.state_apply.entered.connect(self.onApplyPressure)
        self.state_capture.entered.connect(self.onCaptureReplicate)
        self.state_analyze.entered.connect(self.onAnalyzeReplicate)
        self.state_decide.entered.connect(self.onDecide)
        self.state_final.entered.connect(self.onCalibrationCompleted)

        # ---------- transitions ----------
        self.state_prepare_bg.addTransition(
            self.calibration_manager.settingsChangeCompleted, self.state_apply
        )
        for st in (self.state_prepare_bg, self.state_apply, self.state_capture,
                   self.state_analyze, self.state_decide):
            st.addTransition(self.finalize, self.state_final)

        # apply -> capture (after pressure actually set)
        self.state_apply.addTransition(self.pressureApplied, self.state_capture)
        # capture -> analyze
        self.state_capture.addTransition(self.calibration_manager.captureCompleted, self.state_analyze)
        # analyze -> decide
        self.state_analyze.addTransition(self.replicateReady, self.state_decide)
        # decide branches:
        #   same pressure → more reps: straight back to capture (NO re-apply)
        self.state_decide.addTransition(self.continueReplicate, self.state_capture)
        #   next pressure → apply (set pressure once)
        self.state_decide.addTransition(self.continueScan, self.state_apply)

        # register
        for s in (self.state_prepare_bg, self.state_apply, self.state_capture,
                  self.state_analyze, self.state_decide, self.state_final):
            self.state_machine.addState(s)
        self.state_machine.setInitialState(self.state_prepare_bg)

    @staticmethod
    def missing_requirements(cm) -> list[str]:
        """Return a list of human-readable missing prerequisites."""
        missing = []
        if cm.get_nozzle_center() is None:
            missing.append("Nozzle center (machine coords)")
        if cm.get_nozzle_center_image_position() is None:
            missing.append("Nozzle center (image coords)")
        if cm.get_background_image() is None:
            missing.append("Background image")
        if cm.get_emergence_time() is None:
            missing.append("Emergence time")
        return missing

    # ---------- public ----------
    @Slot()
    def requestGracefulStop(self, reason: str = "User requested stop"):
        self._early_stop = True
        self._stop_reason = str(reason)
        self._terminate_at_pressure = float(self._current_pressure) if self._current_pressure is not None else None
        self.stageChanged.emit("Pressure scan: graceful stop requested")
        self.finalize.emit()

    # ---------- state handlers ----------
    @Slot()
    def onPrepareBackground(self):
        if not self._ready:
            self.calibrationError.emit("Pressure scan requires nozzle-center, background, and emergence time.")
            self.finalize.emit(); return
        self.stageChanged.emit("Pressure scan: preparing background (num_droplets=0)")
        self.calibration_manager.changeSettingsRequested.emit(
            {"num_droplets": 0},
            self.calibration_manager.emitSettingsChangeCompleted
        )

    @Slot()
    def onApplyPressure(self):
        # Out-of-range or done?
        if self._next_pressure is None:
            print("Next pressure is None")
            # Synthesize a fallback next step instead of finalizing
            fallback = (self._current_pressure if self._current_pressure is not None else self._p_hi)
            fallback = float(max(self.P_MIN, min(self.P_MAX, fallback - max(self.dp, self.dp_min))))
            self._next_pressure = fallback

        # If we’ve scanned below the requested low bound, finish
        if self._next_pressure < (self._p_lo - 1e-6):
            self.stageChanged.emit("Reached lower pressure bound; finalizing")
            self.finalize.emit(); return

        # Clamp to hardware limits
        target = float(max(self.P_MIN, min(self.P_MAX, self._next_pressure)))

        # If the clamp doesn't change pressure, try ONE nudge down before giving up
        if self._current_pressure is not None and abs(target - self._current_pressure) < 1e-9:
            # Nudge by dp_min
            target = float(max(self.P_MIN, min(self.P_MAX, self._current_pressure - max(self.dp_min, 0.01))))
            if abs(target - self._current_pressure) < 1e-9:
                self.stageChanged.emit("No further pressure change possible; finalizing")
                self.finalize.emit(); return

        # Set up for this pressure
        self._current_pressure = target
        self._next_pressure = None
        self.reps = []
        self.replicates_target = self.min_reps
        self._invalid_skip_count = 0
        self._discard_next = True

        settings = {
            "print_pressure": self._current_pressure,
            "num_droplets": 1,
            "flash_delay": int(self.classify_delay_us)
        }
        self.stageChanged.emit(
            f"Set pressure={self._current_pressure:.3f} psi; delay={self.classify_delay_us} μs"
        )
        def _after(): self.pressureApplied.emit()
        self.calibration_manager.changeSettingsRequested.emit(settings, _after)
        
    @Slot()
    def onCaptureReplicate(self):
        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text=f"Capturing @ {self._current_pressure:.3f} psi (rep {len(self.reps)+1}/{self.replicates_target})",
            attempts_total=5, retry_delay_ms=75, guard_timeout_ms=10_000,
            final_error_msg=f"Capture failed @ {self._current_pressure:.3f} psi"
        )

    @Slot()
    def onAnalyzeReplicate(self):
        if self._discard_next:
            self._discard_next = False
            self.stageChanged.emit("Settling shot discarded; capturing again")
            self.replicateReady.emit()
            return

        droplets, nozzle_area, overlay = self.model.droplet_camera_model.identify_droplets(
            self.droplet_image,
            self.background_image,
            self.nozzle_center_px,
            min_area=1000,
            satellite_band_px=12,
            min_free_offset_px=18
        )
        self.presentImageSignal.emit(overlay)

        # Classify first so safety-stop logic can depend on class
        cls = self._classify_from_detection(droplets)

        nx, ny = int(self.nozzle_center_px[0]), int(self.nozzle_center_px[1])
        dy_min = None
        if droplets:
            dy_list = [(cy - ny) for (cx, cy) in droplets if cy >= ny]
            if dy_list:
                dy_min = min(dy_list)

        # ---- SAFETY: ignore "too close" if MULTIPLE ----
        # If "too close" and this is the FIRST point, do NOT terminate.
        if (cls != "multiple") and (dy_min is not None) and (dy_min < self.safety_clearance_px):
            if self._prev_verdict is None:
                self.stageChanged.emit(
                    "First sample is too close to nozzle → increasing pressure to re-acquire safely"
                )
                # Let decision logic handle upward seek; treat as a normal SINGLE result.
                pass
            else:
                self._early_stop = True
                self._stop_reason = f"Droplet too close to nozzle (dy={int(dy_min)} px < {self.safety_clearance_px})"
                self._terminate_at_pressure = float(self._current_pressure)
                self.stageChanged.emit(
                    f"Safety stop: droplet too close (dy={int(dy_min)} px) at {self._current_pressure:.3f} psi"
                )
                self.finalize.emit()
                return


        # Nozzle-wet handling stays as-is (we log per-rep; final stop handled in _choose_next_pressure)
        if cls == "invalid":
            self._invalid_skip_count += 1
            self.stageChanged.emit("Nozzle-contact / invalid replicate → re-capturing")
            if self._invalid_skip_count > self._invalid_skip_cap:
                self.calibrationError.emit("Too many invalid replicates at this pressure.")
                self.finalize.emit()
                return
            self.replicateReady.emit()
            return

        rep = {
            "cls": cls,
            "center_px": (None if not droplets else droplets[0]),
            "dy_min_px": (None if dy_min is None else int(dy_min)),
            "nozzle_attached_area": int(nozzle_area or 0),
            "nozzle_wet": bool(nozzle_area and nozzle_area > self.nozzle_area_threshold),
        }
        self.reps.append(rep)
        self.replicateReady.emit()

    @Slot()
    def onDecide(self):
        # Short-circuit: if any non-single appears, decide immediately
        classes = [r["cls"] for r in self.reps]

        if "multiple" in classes:
            verdict = "multiple"
            self._store_pressure_summary(verdict, escalated=False)
            if self._maybe_start_or_update_brackets(verdict):
                self._prev_verdict = verdict
                self._prev_pressure = self._current_pressure
                self._advance_or_finish(); return
            self._choose_next_pressure(verdict)
            self._prev_verdict = verdict
            self._prev_pressure = self._current_pressure
            self._advance_or_finish(); return

        if ("none" in classes) and ("multiple" not in classes):
            verdict = "none"
            self._store_pressure_summary(verdict, escalated=False)
            if self._maybe_start_or_update_brackets(verdict):
                self._prev_verdict = verdict
                self._prev_pressure = self._current_pressure
                self._advance_or_finish(); return
            self._choose_next_pressure(verdict)
            self._prev_verdict = verdict
            self._prev_pressure = self._current_pressure
            self._advance_or_finish(); return

        # All observed so far are single; collect enough reps for confidence
        if len(self.reps) < self.min_reps:
            self.continueReplicate.emit()
            return

        # After min_reps, still all single → call it SINGLE
        verdict = "single"
        self._store_pressure_summary(verdict, escalated=False)
        if self._maybe_start_or_update_brackets(verdict):
            self._prev_verdict = verdict
            self._prev_pressure = self._current_pressure
            self._advance_or_finish(); return
        self._choose_next_pressure(verdict)
        self._prev_verdict = verdict
        self._prev_pressure = self._current_pressure
        self._advance_or_finish()

    @Slot()
    def onCalibrationCompleted(self):
        bands = self._compute_single_bands()
        result = {
            "pulse_width_us": self._pulse_width_us,
            "delay_us": int(self.classify_delay_us),
            "pressure_bounds": [self.P_MIN, self.P_MAX],
            "pressures": self.samples,
            "single_bands": bands,
            "primary_band": (bands[0] if bands else None),
            "terminated_early": bool(self._early_stop),
            "stop_reason": (self._stop_reason if self._early_stop else None),
            "terminate_pressure": (float(self._terminate_at_pressure)
                                   if self._terminate_at_pressure is not None else None),
        }
        self.calibrationDataUpdated.emit({"measurements": [], "result": result})
        self.calibration_manager.set_primary_pressure_band(result)
        self.stageChanged.emit(f"Pressure scan complete: single bands: {bands}")
        self.calibrationCompleted.emit()

    # ---------- helpers (unchanged) ----------
    def _classify_from_detection(self, droplets):
        if not droplets or len(droplets) == 0:
            return "none"
        return "single" if len(droplets) == 1 else "multiple"

    def _majority_verdict(self, reps):
        counts = {"none": 0, "single": 0, "multiple": 0}
        for r in reps:
            c = r.get("cls")
            if c in counts:
                counts[c] += 1
        max_ct = max(counts.values())
        winners = [k for k, v in counts.items() if v == max_ct]
        return winners[0] if len(winners) == 1 else "ambiguous"

    def _effective_step_caps(self):
        """
        Returns (dp_max_eff, multi_big_eff, none_jump_eff) based on pulse width
        and any active bracket width (upper/lower/straddle).
        """
        pw = self._pulse_width_us or 1500
        # Clamp PW range we care about (t in [0,1] for ~1200→2100 us)
        lo_pw, hi_pw = 1200.0, 2100.0
        t = 0.0 if pw <= lo_pw else (1.0 if pw >= hi_pw else (pw - lo_pw) / (hi_pw - lo_pw))

        # Base caps vs PW: higher PW → smaller steps
        dp_max_pw     = 0.05 - t * (0.05 - 0.02)  # 0.05 at low PW → 0.02 at high PW
        big_step_pw   = 0.10 - t * (0.10 - 0.04)  # for MULTIPLE downward nudge
        none_jump_pw  = 0.10 - t * (0.10 - 0.04)  # for NONE upward nudge

        # Further cap by any known bracket width (don’t step more than ~45% of the bracket)
        widths = []
        if self._upper_bracket:
            widths.append(abs(self._upper_bracket[1] - self._upper_bracket[0]))
        if self._lower_bracket:
            widths.append(abs(self._lower_bracket[1] - self._lower_bracket[0]))
        if self._straddle_bracket:
            widths.append(abs(self._straddle_bracket[1] - self._straddle_bracket[0]))

        if widths:
            w = max(2*self.dp_min, min(widths))  # use smallest active bracket, but not absurdly tiny
            cap_by_bracket = max(self.dp_min, 0.45 * w)
            dp_max_pw   = min(dp_max_pw, cap_by_bracket)
            big_step_pw = min(big_step_pw, cap_by_bracket)
            none_jump_pw = min(none_jump_pw, cap_by_bracket)

        return dp_max_pw, big_step_pw, none_jump_pw

    def _store_pressure_summary(self, verdict: str, escalated: bool):
        rec = {
            "pressure": float(self._current_pressure),
            "n_reps": len(self.reps),
            "escalated": bool(escalated),
            "verdict": verdict,
            "dy_min_px_med": self._median_dy(self.reps),
            "replicates": self.reps[:]
        }
        self.samples.append(rec)

        # Track lowest SINGLE tested so far (for skipping duplicates after upper-edge refine)
        if verdict == "single":
            if self._min_single_pressure is None:
                self._min_single_pressure = rec["pressure"]
            else:
                self._min_single_pressure = min(self._min_single_pressure, rec["pressure"])

    def _median_dy(self, reps):
        vals = [r.get("dy_min_px") for r in reps if r.get("dy_min_px") is not None]
        if not vals:
            return None
        from statistics import median
        return int(median(vals))

    def _choose_next_pressure(self, verdict: str):
        if self._phase != "scan":
            return

        dp_max_eff, multi_big_eff, none_jump_eff = self._effective_step_caps()

        dy_med = self._median_dy(self.reps)
        moved_px = None
        if dy_med is not None and self._prev_dy is not None and self._prev_pressure is not None:
            moved_px = abs(dy_med - self._prev_dy)

        if any(r.get("nozzle_wet") for r in self.reps) and self.auto_stop_on_nozzle_wet:
            self._early_stop = True
            self._stop_reason = "Nozzle wet detected during scan"
            self._terminate_at_pressure = float(self._current_pressure)
            self.finalize.emit()
            return

        if verdict == "multiple":
            # Downward nudge but obey PW/Bracket caps
            step = min(dp_max_eff, max(self.dp, multi_big_eff))
            next_p = self._current_pressure - step

        elif verdict == "single":
            # Movement-sensitive tuning, then obey cap
            if moved_px is not None:
                if moved_px < self.small_move_px:
                    self.dp = min(dp_max_eff, max(self.dp * 1.9, self.dp + 0.10))
                elif moved_px > self.large_move_px:
                    self.dp = max(max(self.dp_min, 0.02), min(self.dp * 0.6, self.dp - 0.06))
            if dy_med is not None:
                if dy_med <= self.near_nozzle_px:
                    self.dp = max(max(self.dp_min, 0.03), min(self.dp, 0.06))
                elif dy_med >= self.far_nozzle_px:
                    self.dp = min(dp_max_eff, max(self.dp, 0.10))
            self.dp = min(self.dp, dp_max_eff)
            next_p = self._current_pressure - self.dp

        else:  # verdict == "none"
            up = max(self.dp, none_jump_eff)
            self.dp = min(dp_max_eff, max(self.dp, none_jump_eff))
            proposed = self._current_pressure + up
            if self._min_single_pressure is not None:
                if (self._min_single_pressure - self._current_pressure) <= max(self._lower_snap_eps, 0.02):
                    next_p = float(self._min_single_pressure)
                else:
                    next_p = float(min(proposed, self._min_single_pressure))
            else:
                next_p = float(proposed)

        next_p = float(max(self.P_MIN, min(self.P_MAX, next_p)))
        self._prev_dy = dy_med if dy_med is not None else self._prev_dy
        self._prev_pressure = self._current_pressure
        self._next_pressure = next_p

    def _maybe_start_or_update_brackets(self, verdict: str) -> bool:
        cur = self._current_pressure
        prev_p = self._prev_pressure
        prev_v = self._prev_verdict

        if self._phase == "scan":
            # Re-acquire upward if the first point was NONE/AMBIG (unchanged)
            if prev_v is None and verdict in ("none", "ambiguous"):
                self._phase = "reacquire_up"
                self._next_pressure = float(min(self.P_MAX, cur + self._reacquire_step))
                self.stageChanged.emit(
                    f"First point {verdict.upper()} @ {cur:.3f} psi → re-acquiring upward (+{self._reacquire_step:.2f} psi)"
                )
                return True

            # FIRST SINGLE → seek upper (only if upper not yet locked)
            if verdict == "single" and self.backtrack_after_first_single and prev_v is None and not self._upper_edge_locked:
                self._first_single_pressure = cur
                self._phase = "seek_upper"
                self._next_pressure = float(min(self.P_MAX, cur + self._seek_step))
                self.stageChanged.emit(
                    f"First point SINGLE @ {cur:.3f} psi → seeking MULTIPLE upward (+{self._seek_step:.2f} psi)"
                )
                return True

            # MULTIPLE → SINGLE → refine upper (only if upper not yet locked)
            if (verdict == "single" and self.backtrack_after_first_single
                and prev_v == "multiple" and prev_p is not None and not self._upper_edge_locked):
                lo = min(cur, prev_p)
                hi = max(cur, prev_p)
                self._upper_bracket = [lo, hi]
                self._phase = "refine_upper"
                width = hi - lo
                self.dp = max(self.dp_min, min(self.dp, width/2.0))
                self._next_pressure = (lo + hi) / 2.0
                self.stageChanged.emit(
                    f"Refining upper edge between {hi:.3f} psi (multi) and {lo:.3f} psi (single)"
                )
                return True

            # SINGLE → NONE → refine lower (but not if already locked)
            if (verdict == "none" and prev_v == "single" and prev_p is not None and not self._lower_edge_locked):
                lo = min(cur, prev_p)  # none side (lower)
                hi = max(cur, prev_p)  # single side (higher)
                self._lower_bracket = [lo, hi]
                self._phase = "refine_lower"
                width = hi - lo
                self.dp = max(self.dp_min, min(self.dp, width/2.0))
                self._next_pressure = (lo + hi) / 2.0
                self.stageChanged.emit(
                    f"Refining lower edge between {hi:.3f} psi (single) and {lo:.3f} psi (none)"
                )
                return True
            
            # STRADDLE: immediate MULTIPLE→NONE or NONE→MULTIPLE without seeing SINGLE.
            if prev_v in ("multiple", "none") and verdict in ("multiple", "none") and prev_v != verdict and prev_p is not None:
                lo = min(prev_p if prev_v == "none" else cur, cur if verdict == "none" else prev_p)
                hi = max(prev_p if prev_v == "multiple" else cur, cur if verdict == "multiple" else prev_p)
                # Ensure lo < hi and lo is the NONE side, hi is the MULTIPLE side
                if lo > hi:
                    lo, hi = hi, lo
                self._straddle_bracket = [lo, hi]
                self._phase = "bisect_gap"
                self.dp = max(self.dp_min, min(self.dp, (hi - lo) / 2.0))
                self._next_pressure = (lo + hi) / 2.0
                self.stageChanged.emit(f"Straddle detected ({prev_v}→{verdict}) → bisection in [{lo:.3f}, {hi:.3f}]")
                return True
            
            return False

        # ---------- RE-ACQUIRE UP: climb until SINGLE or MULTIPLE appears ----------
        if self._phase == "reacquire_up":
            if verdict == "multiple":
                # Found multi at higher P → resume normal downward scan immediately
                self._phase = "scan"
                self.dp = min(self.dp_max, max(self.dp, 0.12))
                self._next_pressure = float(max(self.P_MIN, cur - self.dp))
                self.stageChanged.emit("Re-acquired MULTIPLE at higher pressure → scanning down")
                return True
            if verdict == "single":
                # Got SINGLE at higher P → immediately start seek_upper to bracket upper edge
                self._first_single_pressure = cur
                self._phase = "seek_upper"
                self._next_pressure = float(min(self.P_MAX, cur + self._seek_step))
                self.stageChanged.emit("Re-acquired SINGLE at higher pressure → seeking MULTIPLE upward")
                return True

            # Still NONE/AMBIG – keep going up, grow step
            next_up = float(min(self.P_MAX, cur + self._reacquire_step))
            if next_up <= cur + 1e-9:
                # Can't go higher → give up and scan down anyway
                self._phase = "scan"
                self._next_pressure = float(max(self.P_MIN, cur - max(self.dp_min, 0.05)))
                self.stageChanged.emit("Re-acquire hit upper limit; scanning down")
                return True
            self._reacquire_step = min(self._reacquire_step_max, max(self._reacquire_step * self._reacquire_growth,
                                                                    self._reacquire_step + 0.05))
            self._next_pressure = next_up
            self.stageChanged.emit(f"Re-acquiring upward → next {self._next_pressure:.3f} psi")
            return True

        # ---------- SEEK UPPER: climb until MULTIPLE, then refine upper ----------
        if self._phase == "seek_upper":
            if verdict == "multiple":
                lo = min(self._first_single_pressure, cur)
                hi = max(self._first_single_pressure, cur)
                self._upper_bracket = [lo, hi]
                self._phase = "refine_upper"
                width = hi - lo
                self.dp = max(self.dp_min, min(self.dp, width/2.0))
                self._next_pressure = (lo + hi) / 2.0
                self.stageChanged.emit(
                    f"Found MULTIPLE @ {cur:.3f} psi → refining upper edge in [{lo:.3f}, {hi:.3f}]"
                )
                return True

            # keep stepping up
            next_up = float(min(self.P_MAX, cur + self._seek_step))
            if next_up <= cur + 1e-9:
                # No MULTIPLE above: resume scan down from the first SINGLE
                self._phase = "scan"
                resume_from = self._first_single_pressure if self._first_single_pressure is not None else cur
                self._next_pressure = float(max(self.P_MIN, resume_from - max(self.dp_min, 0.02)))
                self.stageChanged.emit("Seek upper hit limit; resuming downward scan")
                return True
            self._seek_step = min(self._seek_step_max, max(self._seek_step * self._seek_growth, self._seek_step + 0.02))
            self._next_pressure = next_up
            self.stageChanged.emit(f"Seeking MULTIPLE upward → next {self._next_pressure:.3f} psi")
            return True
        
        # ---------- BISECT GAP: between NONE (lo) and MULTIPLE (hi) until SINGLE or convergence ----------
        if self._phase == "bisect_gap":
            lo, hi = self._straddle_bracket
            # Tighten by verdict
            if verdict == "single":
                # Found a SINGLE → start refining lower edge immediately
                self._lower_bracket = [lo, max(lo, min(hi, self._current_pressure))]
                self._phase = "refine_lower"
                width = self._lower_bracket[1] - self._lower_bracket[0]
                self.dp = max(self.dp_min, min(self.dp, width/2.0))
                self._next_pressure = sum(self._lower_bracket) / 2.0
                self.stageChanged.emit(
                    f"Single found in gap → refining lower edge in [{self._lower_bracket[0]:.3f}, {self._lower_bracket[1]:.3f}]"
                )
                return True

            if verdict == "multiple":
                hi = min(hi, self._current_pressure) if self._current_pressure < hi else self._current_pressure
            else:  # none or ambiguous → treat as NONE side
                lo = max(lo, self._current_pressure) if self._current_pressure > lo else self._current_pressure

            if hi < lo:
                lo, hi = hi, lo
            self._straddle_bracket = [lo, hi]
            width = hi - lo

            if width <= self._bisect_eps:
                # Converged without a clean SINGLE; try a gentle step inside the gap (toward NONE side)
                candidate = float(max(self.P_MIN, min(self.P_MAX, hi - max(width*0.25, self.dp_min))))
                self._phase = "scan"
                self._next_pressure = candidate
                self.stageChanged.emit(f"Gap converged (≤{self._bisect_eps:.3f}) → probing {candidate:.3f} psi")
            else:
                self._next_pressure = (lo + hi) / 2.0
                self.stageChanged.emit(f"Bisect gap → next {(lo+hi)/2.0:.3f} psi")
            return True
        
        # ---------- Refine UPPER edge ----------
        if self._phase == "refine_upper":
            lo, hi = self._upper_bracket
            if verdict == "multiple":
                hi = max(hi, cur) if cur > hi else cur
            else:  # single/none/ambiguous → tighten single side
                lo = min(lo, cur) if cur < lo else cur

            if hi < lo:
                lo, hi = hi, lo
            width = hi - lo
            self._upper_bracket = [lo, hi]

            if width <= self._edge_eps:
                self.stageChanged.emit(f"Upper edge ≈ {lo:.3f}–{hi:.3f} psi (≤ {self._edge_eps:.2f}); resume scan")
                self._phase = "scan"
                self._upper_edge_locked = True
                self._upper_bracket = None
                self._first_single_pressure = None
                # NEW: jump to just below the LOWEST SINGLE we have already tested, to avoid retesting
                resume_from = self._min_single_pressure if self._min_single_pressure is not None else lo
                self._next_pressure = float(max(self.P_MIN, resume_from - max(self.dp_min, 0.02)))
            else:
                self.dp = max(self.dp_min, min(self.dp, width/2.0))
                self._next_pressure = (lo + hi) / 2.0
            return True

        # ---------- Refine LOWER edge (unchanged except for style) ----------
        if self._phase == "refine_lower":
            lo, hi = self._lower_bracket
            if verdict in ("none", "ambiguous"):
                lo = min(lo, cur) if cur < lo else cur
            else:  # single/multiple → tighten the single side
                hi = max(hi, cur) if cur > hi else cur

            if hi < lo:
                lo, hi = hi, lo
            width = hi - lo
            self._lower_bracket = [lo, hi]

            if width <= self._edge_eps:
                # SNAP to the lowest known SINGLE if we're close, and lock the lower edge
                snap_to = None
                if self._min_single_pressure is not None:
                    # If the single-side bound is within eps of our known lowest single, snap to it
                    if abs(self._min_single_pressure - hi) <= self._lower_snap_eps or \
                    abs(self._min_single_pressure - lo) <= self._lower_snap_eps:
                        snap_to = float(self._min_single_pressure)

                self._lower_edge_locked = True
                self._lower_edge_value  = float(snap_to if snap_to is not None else hi)

                self.stageChanged.emit(
                    f"Lower edge locked at ~{self._lower_edge_value:.3f} psi (≤ {self._edge_eps:.2f})."
                )

                # If upper also locked, we're done
                if self._upper_edge_locked:
                    self.finalize.emit()
                    return True

                # Otherwise resume scan from just below the lowest SINGLE to continue normal sweep
                self._phase = "scan"
                resume_from = self._min_single_pressure if self._min_single_pressure is not None else self._lower_edge_value
                self._next_pressure = float(max(self.P_MIN, resume_from - max(self.dp_min, width/2.0)))
            else:
                self.dp = max(self.dp_min, min(self.dp, width/2.0))
                self._next_pressure = (lo + hi) / 2.0
            return True

        return False

    def _advance_or_finish(self):
        if self._early_stop:
            print("Early stop triggered")
            self.finalize.emit()
            return

        # If next pressure didn't get set (e.g., unanimous SINGLE on first point), synthesize a safe step
        if self._next_pressure is None:
            base = (self._current_pressure if self._current_pressure is not None else self._p_hi)
            self._next_pressure = float(max(self.P_MIN, min(self.P_MAX, base - max(self.dp, self.dp_min))))

        # If walking off the scan range, finish
        if self._next_pressure < (self._p_lo - 1e-6):
            print("Next pressure below scan range")
            self.finalize.emit()
            return

        self.continueScan.emit()   # → state_apply (will use _next_pressure)
    
    def _compute_single_bands(self):
        if not self.samples:
            return []

        # Gather singles and non-singles
        singles = sorted([rec["pressure"] for rec in self.samples if rec.get("verdict") == "single"])
        if not singles:
            return []

        non_single = sorted([rec["pressure"] for rec in self.samples if rec.get("verdict") != "single"])

        def has_separator(a: float, b: float) -> bool:
            lo, hi = (a, b) if a <= b else (b, a)
            # Is there any TESTED non-single strictly in between?
            for p in non_single:
                if lo < p < hi:
                    return True
            return False

        # Build bands by merging across gaps unless a tested non-single lies between
        bands = []
        band_lo = band_hi = singles[0]
        for s in singles[1:]:
            if has_separator(band_hi, s):
                # finalize current band
                lo, hi = (band_lo, band_hi) if band_lo <= band_hi else (band_hi, band_lo)
                bands.append([lo, hi])
                band_lo = band_hi = s
            else:
                # merge/extend band
                if s < band_lo:
                    band_lo = s
                if s > band_hi:
                    band_hi = s

        # finalize last
        lo, hi = (band_lo, band_hi) if band_lo <= band_hi else (band_hi, band_lo)
        bands.append([lo, hi])

        # Sort by width (largest first) to keep your previous behavior
        bands.sort(key=lambda ab: (ab[1] - ab[0]), reverse=True)
        return bands
    
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
            p_lo, p_hi = 0.3, 5.0
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

    @staticmethod
    def missing_requirements(cm) -> list[str]:
        """Return a list of human-readable missing prerequisites."""
        missing = []
        if cm.get_nozzle_center() is None:
            missing.append("Nozzle center (machine coords)")
        if cm.get_nozzle_center_image_position() is None:
            missing.append("Nozzle center (image coords)")
        if cm.get_background_image() is None:
            missing.append("Background image")
        if cm.get_emergence_time() is None:
            missing.append("Emergence time")
        return missing

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

class PressureTrajectoryCalibrationProcess(BaseCalibrationProcess):
    """
    Measure droplet trajectory (vx, vy) for one or more pressures.

    For each pressure:
      - (optional) discard first frame after pressure change (settling)
      - For each flash delay:
          * take R replicates, keep the *median* center (robust)
          * if near the image edge, DO NOT try larger delays; instead
            adaptively insert earlier/mid delays to secure >= min_points
      - Fit a line center(t) -> (vx, vy) using aggregated points (one per delay)

    Emits: per-pressure raw aggregated points and the fit.

    Requires: background image, nozzle_center_px, emergence_time_us.
    """

    # process-local signals for the state machine
    pressureApplied   = Signal()   # pressure (and initial delay) applied
    delayApplied      = Signal()   # per-timepoint flash delay applied
    timepointReady    = Signal()   # analysis for one capture completed
    continueCapture   = Signal()   # take another replicate at same delay
    setNextDelay      = Signal()   # advance to another delay at same pressure
    advancePressure   = Signal()   # advance to next pressure
    finalize          = Signal()   # finish entirely

    def __init__(self,
                 calibration_manager,
                 model,
                 *,
                 pressures: list[float] | None = None,
                 delays_us: list[int] | None = None,
                 min_points: int = 3,
                 replicates_per_delay: int = 3,
                 max_failed_captures_per_delay: int = 4,
                 discard_first_after_pressure_change: bool = True,
                 edge_guard_px: int = 200,
                 miss_streak_limit: int = 2,
                 delay_floor_margin_us: int = 300,           # emergence+PW+margin is the earliest allowed
                 parent=None):
        super().__init__(calibration_manager, model, parent)
        missing_requirements = self.missing_requirements(calibration_manager)
        if missing_requirements:
            raise ValueError("Cannot start PressureTrajectoryCalibrationProcess; missing prerequisites: "
                               + ", ".join(missing_requirements))
        
        self.phase_name = "pressure_trajectory"

        # --- prerequisites ---
        self.nozzle_center_px  = self.calibration_manager.get_nozzle_center_image_position()
        self.background_image  = self.calibration_manager.get_background_image()
        self.emergence_time_us = self.calibration_manager.get_emergence_time()
        self._ready = (self.nozzle_center_px is not None and
                       self.background_image is not None and
                       self.emergence_time_us is not None)

        # --- pressures to measure ---
        if pressures is None:
            band = self.calibration_manager.get_primary_pressure_band()
            if band:
                p_lo, p_hi = float(band[0]), float(band[1])
                p_mid = round((p_lo + p_hi) / 2.0, 3)
                pressures = [round(p_lo, 3), p_mid, round(p_hi, 3)]
            else:
                try:
                    cur = float(self.model.machine_model.get_print_pressure())
                except Exception:
                    hw_lo, hw_hi = self.model.machine_model.get_print_pressure_bounds()
                    cur = (hw_lo + hw_hi) * 0.5
                pressures = [round(cur, 3)]
        self.pressures = list(pressures)
        self.p_index = 0
        self._current_pressure = None

        # --- delays (absolute flash delays, in µs) ---
        if delays_us is None:
            # Default: 3 timepoints ~ clean free-flight window
            try:
                pw = int(self.model.machine_model.get_print_pulse_width())
            except Exception:
                pw = 1500
            start = int((self.emergence_time_us or 1000) + pw + 1500)
            step  = 700
            delays_us = [start + i * step for i in range(3)]
        self.delays_us = sorted(list(map(int, delays_us)))
        self.d_index = 0

        # --- policy / guards ---
        self.min_points                       = int(min_points)
        self.replicates_per_delay             = int(replicates_per_delay)
        self.max_failed_captures_per_delay    = int(max_failed_captures_per_delay)
        self.discard_first_after_pressure     = bool(discard_first_after_pressure_change)
        self.edge_guard_px                    = int(edge_guard_px)
        self.miss_streak_limit                = int(miss_streak_limit)
        self.delay_floor_margin_us            = int(delay_floor_margin_us)

        # earliest allowable delay (do not go earlier than this)
        try:
            pw = int(self.model.machine_model.get_print_pulse_width())
        except Exception:
            pw = 1500
        self._delay_floor_us = int((self.emergence_time_us or 1000) + pw + self.delay_floor_margin_us)

        # --- replicate bookkeeping for current delay ---
        self._discard_next = False
        self._rep_count    = 0
        self._rep_buffer   = []
        self._failed_caps_this_delay = 0
        self._miss_streak = 0
        self._stop_delays_after_this = False
        self._max_delay_allowed_us = None  # hard ceiling for allowed delays after edge is detected


        # track which delays have been aggregated (or skipped)
        self._completed: list[bool] = [False] * len(self.delays_us)

        # --- accumulators ---
        # points: aggregated timepoints (one per delay): [{"t_us": int, "center_px": (dx,dy)} ...]
        self.points = []
        self.samples = []

        # -------------- states --------------
        self.state_prepare_bg = QState()
        self.state_apply      = QState()   # set pressure & initial delay
        self.state_set_delay  = QState()   # update delay for next timepoint
        self.state_capture    = QState()
        self.state_analyze    = QState()
        self.state_decide     = QState()
        self.state_final      = QFinalState()

        # entered handlers
        self.state_prepare_bg.entered.connect(self.onPrepare)
        self.state_apply.entered.connect(self.onApplyPressure)
        self.state_set_delay.entered.connect(self.onSetDelay)
        self.state_capture.entered.connect(self.onCaptureTimepoint)
        self.state_analyze.entered.connect(self.onAnalyzeTimepoint)
        self.state_decide.entered.connect(self.onDecide)
        self.state_final.entered.connect(self.onCalibrationCompleted)

        # ---------- transitions (bound signals; robust) ----------
        self.state_prepare_bg.addTransition(
            self.calibration_manager.settingsChangeCompleted, self.state_apply
        )
        for st in (self.state_prepare_bg, self.state_apply, self.state_set_delay,
                   self.state_capture, self.state_analyze, self.state_decide):
            st.addTransition(self.finalize, self.state_final)

        self.state_apply.addTransition(self.pressureApplied, self.state_capture)
        self.state_set_delay.addTransition(self.delayApplied, self.state_capture)
        self.state_capture.addTransition(self.calibration_manager.captureCompleted, self.state_analyze)
        self.state_analyze.addTransition(self.timepointReady, self.state_decide)

        self.state_decide.addTransition(self.continueCapture, self.state_capture)   # more reps at same delay
        self.state_decide.addTransition(self.setNextDelay,    self.state_set_delay) # move to another delay
        self.state_decide.addTransition(self.advancePressure, self.state_apply)     # next pressure

        # register states
        for s in (self.state_prepare_bg, self.state_apply, self.state_set_delay,
                  self.state_capture, self.state_analyze, self.state_decide,
                  self.state_final):
            self.state_machine.addState(s)
        self.state_machine.setInitialState(self.state_prepare_bg)

    @staticmethod
    def missing_requirements(cm) -> list[str]:
        """Return a list of human-readable missing prerequisites."""
        missing = []
        if cm.get_nozzle_center() is None:
            missing.append("Nozzle center (machine coords)")
        if cm.get_nozzle_center_image_position() is None:
            missing.append("Nozzle center (image coords)")
        if cm.get_background_image() is None:
            missing.append("Background image")
        if cm.get_emergence_time() is None:
            missing.append("Emergence time")
        return missing

    # ----------------- state handlers -----------------

    @Slot()
    def onPrepare(self):
        if not self._ready:
            self.calibrationError.emit("Trajectory prerequisites missing (nozzle center, background, or emergence).")
            self.finalize.emit()
            return

        self.stageChanged.emit("Trajectory: preparing (num_droplets=0)")
        self.calibration_manager.changeSettingsRequested.emit(
            {"num_droplets": 0},
            self.calibration_manager.emitSettingsChangeCompleted
        )

    @Slot()
    def onApplyPressure(self):
        if self.p_index >= len(self.pressures):
            self.finalize.emit()
            return

        target = float(self.pressures[self.p_index])
        if self._current_pressure != target:
            self._current_pressure = target
            self.points = []
            self.d_index = 0
            self._reset_delay_state()
            self._miss_streak = 0
            self._stop_delays_after_this = False
            self._discard_next = bool(self.discard_first_after_pressure)
            self._max_delay_allowed_us = None

            # reset completion map for this pressure
            self._completed = [False] * len(self.delays_us)

        # pick earliest uncompleted delay to start
        nxt = self._find_next_uncompleted_index(prefer="earliest")
        if nxt is None:
            # no work to do at this pressure
            self._finish_pressure_and_advance()
            return
        self.d_index = nxt

        delay = int(self.delays_us[self.d_index])
        settings = {"print_pressure": self._current_pressure, "num_droplets": 1, "flash_delay": delay}
        self.stageChanged.emit(
            f"Trajectory: P={self._current_pressure:.3f} psi, delay={delay} µs "
            f"({self._completed.count(True)+1}/{len(self.delays_us)})"
        )
        def _after(): self.pressureApplied.emit()
        self.calibration_manager.changeSettingsRequested.emit(settings, _after)

    @Slot()
    def onSetDelay(self):
        if self._current_pressure is None or not (0 <= self.d_index < len(self.delays_us)):
            self.calibrationError.emit("Internal error: invalid delay/pressure state.")
            self.finalize.emit()
            return

        self._reset_delay_state()

        delay = int(self.delays_us[self.d_index])
        self.stageChanged.emit(
            f"Trajectory: update delay → {delay} µs at P={self._current_pressure:.3f} psi"
        )
        def _after(): self.delayApplied.emit()
        self.calibration_manager.changeSettingsRequested.emit({"flash_delay": delay}, _after)

    @Slot()
    def onCaptureTimepoint(self):
        if self._current_pressure is None or not (0 <= self.d_index < len(self.delays_us)):
            self.calibrationError.emit("Capture guard failed (pressure/delay invalid).")
            self.finalize.emit()
            return

        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text=f"Capture @ {self._current_pressure:.3f} psi, delay={self.delays_us[self.d_index]} µs "
                       f"(rep {self._rep_count+1}/{self.replicates_per_delay})",
            attempts_total=5,
            retry_delay_ms=75,
            guard_timeout_ms=10_000,
            final_error_msg=f"Capture failed @ {self._current_pressure:.3f} psi"
        )

    @Slot()
    def onAnalyzeTimepoint(self):
        if self._discard_next:
            self._discard_next = False
            self.stageChanged.emit("Settling frame discarded; re-capturing")
            self.timepointReady.emit()
            return

        droplets, nozzle_area, overlay = self.model.droplet_camera_model.identify_droplets(
            self.droplet_image,
            self.background_image,
            self.nozzle_center_px,
            min_area=900,
            satellite_band_px=12,
            min_free_offset_px=18
        )

        good = False
        edge_close_now = False
        abs_center = None

        if droplets and (len(droplets) == 1):
            (cx, cy) = droplets[0]
            nx, ny = int(self.nozzle_center_px[0]), int(self.nozzle_center_px[1])
            dx, dy = float(cx - nx), float(cy - ny)
            self._rep_buffer.append((dx, dy))
            self._rep_count += 1
            self._failed_caps_this_delay = 0
            good = True
            abs_center = (int(cx), int(cy))

            # Edge check
            h, w = self.droplet_image.shape[:2]
            if (cx < self.edge_guard_px or cx > (w-1 - self.edge_guard_px) or
                cy < self.edge_guard_px or cy > (h-1 - self.edge_guard_px)):
                edge_close_now = True
                # We won't schedule larger delays; we will adapt earlier/mid delays in decide
                self._stop_delays_after_this = True
                t_now = int(self.delays_us[self.d_index])
                if (self._max_delay_allowed_us is None) or (t_now < self._max_delay_allowed_us):
                    self._max_delay_allowed_us = t_now
            self._miss_streak = 0
        else:
            self._failed_caps_this_delay += 1
            if self.d_index > 0:
                self._miss_streak += 1

        # annotate path
        try:
            overlay = self._annotate_path_overlay(overlay, abs_center)
        except Exception:
            pass

        self.presentImageSignal.emit(overlay)
        self._analyze_good = good
        self._edge_close_now = edge_close_now
        self.timepointReady.emit()

    @Slot()
    def onDecide(self):
        # 1) too many fails at this delay → mark completed (skipped) and move on
        if self._failed_caps_this_delay >= self.max_failed_captures_per_delay:
            self.stageChanged.emit(
                f"Delay {self.delays_us[self.d_index]} µs: too many failed captures → skipping"
            )
            self._mark_current_delay_completed(aggregated=False)
            if self._stop_delays_after_this and len(self.points) >= self.min_points:
                self.stageChanged.emit("Near edge and have enough points → finishing this pressure")
                self._finish_pressure_and_advance()
                return
            nxt = self._pick_next_delay_index()
            if nxt is None:
                self._finish_pressure_and_advance()
            else:
                self.d_index = nxt
                self.setNextDelay.emit()
            return

        # 2) need more replicates at this delay (last capture was good)
        if self._rep_count < self.replicates_per_delay and self._analyze_good:
            self.continueCapture.emit()
            return

        # 3) last capture was bad but we haven't exceeded fail cap → retry same delay
        if not self._analyze_good:
            self.continueCapture.emit()
            return

        # 4) aggregate a timepoint for this delay
        if self._rep_count >= self.replicates_per_delay and len(self._rep_buffer) > 0:
            dx_med = float(np.median([p[0] for p in self._rep_buffer]))
            dy_med = float(np.median([p[1] for p in self._rep_buffer]))
            t_now  = int(self.delays_us[self.d_index])
            self.points.append({"t_us": t_now, "center_px": (dx_med, dy_med)})
            self._mark_current_delay_completed(aggregated=True)

            if self._stop_delays_after_this and len(self.points) >= self.min_points:
                self.stageChanged.emit("Near edge and have enough points → finishing this pressure")
                self._finish_pressure_and_advance()
                return

            # If near the edge, adapt the plan so we can still hit min_points.
            if self._stop_delays_after_this and len(self.points) < self.min_points:
                inserted = self._ensure_min_points_by_inserting_earlier_delays()
                if not inserted and len(self.points) < self.min_points:
                    # As a secondary attempt, try inserting a midpoint between earliest two sampled points
                    self._insert_midpoint_delay_if_helpful()

                # Pick the earliest uncompleted delay next (avoid larger delays near edge)
                nxt = self._find_next_uncompleted_index(prefer="earliest")
                if nxt is None:
                    # Could not schedule anything else
                    self._finish_pressure_and_advance()
                else:
                    self.d_index = nxt
                    self.setNextDelay.emit()
                return

            # Also stop if we've been missing repeatedly at later delays
            if self._miss_streak >= self.miss_streak_limit and len(self.points) >= self.min_points:
                self.stageChanged.emit(f"Miss streak (≥{self.miss_streak_limit}) → stop larger delays")
                self._finish_pressure_and_advance()
                return

            # Otherwise: pick next delay (prefer > current if not at edge; earliest if at edge)
            nxt = self._pick_next_delay_index()
            if nxt is None:
                self._finish_pressure_and_advance()
            else:
                self.d_index = nxt
                self.setNextDelay.emit()
            return

        # Fallback: keep capturing at this delay
        self.continueCapture.emit()

    # ----------------- end states -----------------

    def _finish_pressure_and_advance(self):
        """Fit (if enough points) and move to next pressure or finalize."""
        if len(self.points) < self.min_points:
            self.stageChanged.emit(
                f"Trajectory: insufficient points at {self._current_pressure:.3f} psi; skipping fit."
            )
            self.samples.append({
                "pressure": float(self._current_pressure),
                "points": self.points[:],
                "fit": None
            })
        else:
            vx, vy = self._fit_velocity(self.points)
            speed = math.hypot(vx, vy)
            angle_deg = math.degrees(math.atan2(vy, vx))  # image coords; +y downward
            self.samples.append({
                "pressure": float(self._current_pressure),
                "points": self.points[:],
                "fit": {
                    "vx_px_per_us": float(vx),
                    "vy_px_per_us": float(vy),
                    "speed_px_per_us": float(speed),
                    "angle_deg": float(angle_deg),
                    "n_points": int(len(self.points))
                }
            })

        # advance pressure or finish
        self.p_index += 1
        self._current_pressure = None
        self.d_index = 0
        self._reset_delay_state()
        self._miss_streak = 0
        self._stop_delays_after_this = False
        self._max_delay_allowed_us = None
        self._completed = [False] * len(self.delays_us)

        if self.p_index >= len(self.pressures):
            self.finalize.emit()
        else:
            self.advancePressure.emit()

    @Slot()
    def onCalibrationCompleted(self):
        result = {
            "pressures": self.samples,
            "delays_us": self.delays_us,
            "band_used": self.calibration_manager.get_primary_pressure_band(),
            "nozzle_center_px": self.nozzle_center_px,
            "emergence_time_us": self.emergence_time_us
        }
        self.calibrationDataUpdated.emit({"measurements": [], "result": result})
        try:
            self.calibration_manager.set_pressure_trajectory_result(result)
        except Exception:
            pass
        self.stageChanged.emit("Trajectory calibration complete")
        self.calibrationCompleted.emit()

    # ----------------- helpers -----------------

    def _reset_delay_state(self):
        self._rep_count = 0
        self._rep_buffer = []
        self._failed_caps_this_delay = 0
        self._analyze_good = False
        self._edge_close_now = False

    def _mark_current_delay_completed(self, aggregated: bool):
        # Bounds guard
        if 0 <= self.d_index < len(self._completed):
            self._completed[self.d_index] = True
        self._reset_delay_state()

    def _typical_step_us(self) -> int:
        d = sorted(set(self.delays_us))
        if len(d) < 2:
            return 500
        diffs = [b - a for a, b in zip(d[:-1], d[1:])]
        diffs.sort()
        step = int(diffs[len(diffs)//2])
        return max(100, step)

    def _ensure_min_points_by_inserting_earlier_delays(self) -> bool:
        """
        If we don't yet have min_points and we're near the edge, insert earlier delays
        (and mark them uncompleted) until we *can* reach min_points, staying above the floor.
        Returns True if we inserted any new delays.
        """
        needed = self.min_points - len(self.points)
        if needed <= 0:
            return False

        inserted_any = False
        step = max(100, self._typical_step_us() // 2)  # go denser & earlier
        current_first = min(self.delays_us) if self.delays_us else self._delay_floor_us + step
        cands = []
        t = current_first

        while needed > 0:
            t_new = t - step
            if t_new < self._delay_floor_us:
                break
            cands.append(int(t_new))
            t = t_new
            needed -= 1

        if not cands:
            return False

        # merge + sort; rebuild completion map keeping completed marks for existing delays
        existing = list(zip(self.delays_us, self._completed))
        # add new ones as uncompleted
        for c in cands:
            existing.append((c, False))

        existing.sort(key=lambda x: x[0])
        self.delays_us = [x[0] for x in existing]
        self._completed = [x[1] for x in existing]
        inserted_any = True
        return inserted_any

    def _insert_midpoint_delay_if_helpful(self):
        if len(self.points) >= self.min_points:
            return False
        if not self.points or len(self.delays_us) < 2:
            return False

        delays_sorted = sorted(self.delays_us)
        a, b = delays_sorted[0], delays_sorted[1]
        mid = int((a + b) // 2)
        if mid <= self._delay_floor_us:
            return False
        if (self._max_delay_allowed_us is not None) and (mid > self._max_delay_allowed_us):
            return False
        if mid in self.delays_us:
            return False

        existing = list(zip(self.delays_us, self._completed))
        existing.append((mid, False))
        existing.sort(key=lambda x: x[0])
        self.delays_us = [x[0] for x in existing]
        self._completed = [x[1] for x in existing]
        return True

    def _find_next_uncompleted_index(self, prefer: str = "after_current"):
        """
        Return the index of the next uncompleted delay, respecting the cap
        self._max_delay_allowed_us (if set).
        prefer:
        - "after_current": smallest eligible delay strictly greater than current,
                            else the smallest eligible delay
        - "earliest": smallest eligible delay
        """
        if not self.delays_us:
            return None

        # Build eligible indices (uncompleted and <= cap if cap is set)
        cap = self._max_delay_allowed_us
        eligible = []
        for i, done in enumerate(self._completed):
            if done:
                continue
            if (cap is not None) and (self.delays_us[i] > cap):
                continue
            eligible.append(i)

        if not eligible:
            return None

        def _min_by_delay(indices):
            return min(indices, key=lambda k: self.delays_us[k])

        if prefer == "earliest":
            return _min_by_delay(eligible)

        # prefer == "after_current"
        cur_delay = self.delays_us[self.d_index] if (0 <= self.d_index < len(self.delays_us)) else -1
        after = [i for i in eligible if self.delays_us[i] > cur_delay]
        if after:
            return _min_by_delay(after)
        return _min_by_delay(eligible)

    def _pick_next_delay_index(self):
        """
        If near edge: prefer earliest uncompleted delay (and never exceed cap).
        Else: prefer next uncompleted after current.
        """
        if self._stop_delays_after_this:
            return self._find_next_uncompleted_index(prefer="earliest")
        return self._find_next_uncompleted_index(prefer="after_current")

    def _fit_velocity(self, points):
        """Least-squares for x(t), y(t). Returns (vx, vy) in px/µs."""
        t = np.array([p["t_us"] for p in points], dtype=float)
        x = np.array([p["center_px"][0] for p in points], dtype=float)
        y = np.array([p["center_px"][1] for p in points], dtype=float)
        t_mean = t.mean()
        denom = np.sum((t - t_mean) ** 2) or 1.0
        vx = np.sum((t - t_mean) * (x - x.mean())) / denom
        vy = np.sum((t - t_mean) * (y - y.mean())) / denom
        return -float(vx), float(vy)

    def _annotate_path_overlay(self, overlay, abs_center_now):
        """
        Draw historical aggregated points (green) and current replicate center (cyan).
        Also draw nozzle center marker and a polyline path + edge guard box.
        """
        if overlay is None:
            return overlay
        if overlay.ndim == 2:
            overlay = cv2.cvtColor(overlay, cv2.COLOR_GRAY2BGR)

        nx, ny = int(self.nozzle_center_px[0]), int(self.nozzle_center_px[1])
        cv2.drawMarker(overlay, (nx, ny), (255, 0, 0), markerType=cv2.MARKER_CROSS, markerSize=10, thickness=1)

        if self.points:
            pts_abs = []
            for p in self.points:
                dx, dy = p["center_px"]
                cx, cy = int(round(nx + dx)), int(round(ny + dy))
                pts_abs.append((cx, cy))
                cv2.circle(overlay, (cx, cy), 4, (0, 200, 0), -1)
            for i in range(len(pts_abs) - 1):
                cv2.line(overlay, pts_abs[i], pts_abs[i+1], (0, 200, 0), 1)

        if abs_center_now is not None:
            cv2.circle(overlay, abs_center_now, 4, (200, 200, 0), -1)

        h, w = overlay.shape[:2]
        eg = self.edge_guard_px
        cv2.rectangle(overlay, (eg, eg), (w-1-eg, h-1-eg), (80, 80, 80), 1)
        return overlay
    
class DropletSearchCalibrationProcess(BaseCalibrationProcess):
    """
    Find/center/focus a droplet and characterize replicates.
    If manual_start=True, skip the initial trajectory-based move and
    use the current XYZ as the starting point.
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

    def __init__(self, calibration_manager, model, parent=None,
                 *, manual_start: bool = False, start_delay_us: int | None = None):
        super().__init__(calibration_manager, model, parent)
        missing_requirements = self.missing_requirements(calibration_manager)
        if missing_requirements:
            raise ValueError("Cannot start DropletSearchCalibrationProcess; missing prerequisites: "
                               + ", ".join(missing_requirements))
        self.phase_name = "droplet_search"
        self.manual_start = bool(manual_start)

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
            p_lo, p_hi = 0.3, 5.0
        self.min_pressure, self.max_pressure = float(p_lo), float(p_hi)
        self.pressure_step = 0.02
        self.new_pressure = None

        # Upstream calibration (relaxed when manual_start=True)
        self._ready = True
        self._import_calibration_data(manual_mode=self.manual_start)
        if not self._ready:
            return

        # Time-of-flight plan / delay
        self.sphere_delay_us = 8000
        # Pick a starting delay:
        if self.manual_start:
            # use current camera setting (if available)
            _, _, cam_flash_delay, _, _ = self.model.droplet_camera_model.get_image_metadata()
            seed_delay = int(cam_flash_delay or 0)
        else:
            if start_delay_us is not None:
                seed_delay = int(start_delay_us)
            else:
                # prefer emergence+sphere when available; otherwise current camera setting
                if self.emergence_time_us is not None:
                    seed_delay = int(max(0, self.emergence_time_us + self.sphere_delay_us))
                else:
                    # (num_flashes, flash_dur, flash_delay, num_droplets, exposure)
                    _, _, cam_flash_delay, _, _ = self.model.droplet_camera_model.get_image_metadata()
                    seed_delay = int(cam_flash_delay or 0)

        self.delay_offsets_us = [0, +500, -500, +1000, -1000, +1500, -1500]
        self._delay_try_index = 0
        self.min_delay_us, self.max_delay_us = 0, 40000
        self.target_delay_us = self._clamp_delay(seed_delay)

        # Movement safety
        self.max_center_step, self.max_focus_step = 1200, 16
        self.x_lo, self.x_hi = self._get_axis_bounds_safe('X', default_span=20000)
        self.y_lo, self.y_hi = self._get_axis_bounds_safe('Y', default_span=10000)
        self.z_lo, self.z_hi = self._get_axis_bounds_safe('Z', default_span=20000)

        # Target position (only used if we actually move there)
        self.predicted_target = self._predict_stage_target(self.target_delay_us)

        # Focus control + robustness
        self.focus_dir, self.focus_step = +1, 16
        self.focus_min_step = 8
        self.focus_dir_switches, self.focus_switch_limit = 0, 6
        self.last_focus_val = None
        self.focus_ok_threshold = 5_000_000

        self._focus_best = 0.0
        self._focus_same_dir_tries = 0
        self._focus_moves_done = 0
        self._focus_move_budget = 60
        self._min_focus_gain = 0.01

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

        # center → set_delay when droplet lost
        t4c = QSignalTransition(); t4c.setSenderObject(self); t4c.setSignal(b"2continueSearch()")
        t4c.setTargetState(self.state_set_delay)
        self.state_center.addTransition(t4c)

        # per-state moveCompleted transitions
        t7_center = QSignalTransition(); t7_center.setSenderObject(self.calibration_manager)
        t7_center.setSignal(b"2moveCompleted()"); t7_center.setTargetState(self.state_capture_droplet)
        self.state_center.addTransition(t7_center)

        t7_char = QSignalTransition(); t7_char.setSenderObject(self.calibration_manager)
        t7_char.setSignal(b"2moveCompleted()"); t7_char.setTargetState(self.state_capture_droplet)
        self.state_characterization.addTransition(t7_char)

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

        # >>> Initial state depends on manual_start
        if self.manual_start:
            self.state_machine.setInitialState(self.state_prepare_background)
        else:
            self.state_machine.setInitialState(self.state_move_to_target)
        # <<<

    @staticmethod
    def missing_requirements(cm) -> list[str]:
        """Return a list of human-readable missing prerequisites."""
        missing = []
        if cm.get_nozzle_center() is None:
            missing.append("Nozzle center (machine coords)")
        if cm.get_nozzle_center_image_position() is None:
            missing.append("Nozzle center (image coords)")
        if cm.get_background_image() is None:
            missing.append("Background image")
        if cm.get_emergence_time() is None:
            missing.append("Emergence time")
        if cm.get_trajectory_vector() is None:
            missing.append("Trajectory vector")
        return missing

    # ----- utils -----
    def _import_calibration_data(self, *, manual_mode: bool):
        """Relax prerequisites in manual mode."""
        self.vel_steps_per_s = self.calibration_manager.get_trajectory_vector()      # (vX, vY, vZ)
        self.nozzle_center_machine = self.calibration_manager.get_nozzle_center()
        self.emergence_time_us = self.calibration_manager.get_emergence_time()
        self.prev_background = self.calibration_manager.get_background_image()

        if manual_mode:
            # In manual mode, we don't require velocity/nozzle; allow emergence to be None.
            self._ready = True
        else:
            if (self.vel_steps_per_s is None or self.nozzle_center_machine is None
                or self.emergence_time_us is None):
                self._ready = False
                self._abort("Must complete trajectory + nozzle center + emergence first")

    def _clamp_delay(self, d_us:int)->int:
        return int(max(self.min_delay_us, min(self.max_delay_us, int(d_us))))

    def _get_axis_bounds_safe(self, axis:str, default_span:int):
        try:
            lo, hi = self.model.machine_model.get_axis_bounds(axis)
            return int(lo), int(hi)
        except Exception:
            base = int(self.nozzle_center_machine.get(axis, 0)) if self.nozzle_center_machine else 0
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

    def _predict_stage_target(self, delay_us:int):
        # If we don't have velocity/nozzle (manual mode), return current position as "target"
        if not self.vel_steps_per_s or not self.nozzle_center_machine:
            cur = self.model.machine_model.get_current_position_dict()
            return self._clamp_abs(cur['X'], cur['Y'], cur['Z'])
        dt_s = max(0.0, (int(delay_us) - int(self.emergence_time_us or 0)) * 1e-6)
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
        if self._aborted:
            return
        self._aborted = True
        try:
            self.state_machine.stop()
        except Exception:
            pass
        self.calibrationError.emit(msg)

    # ----- states -----
    @Slot()
    def onMoveToTarget(self):
        if self._is_dead():
            return
        if self.manual_start:
            # Explicitly skip movement; proceed as if move completed.
            self.stageChanged.emit("Manual start: using current position (no trajectory move)")
            self.calibration_manager.emitMoveCompleted()
            return
        if not self._ready:
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
                return self._abort("Droplet not found (max retries).")
            # Retry strategy differs for manual mode:
            if not self.manual_start and self.vel_steps_per_s:
                self.stageChanged.emit("Droplet not found yet → nudging along velocity and retrying")
                vX, vY, vZ = map(float, self.vel_steps_per_s)
                nudge = 0.02
                self._safe_move_relative((int(vX * nudge), int(vY * nudge), int((-vZ) * nudge)))
            else:
                self.stageChanged.emit("Droplet not found yet → skipping stage nudge (manual start); retrying delay sweep")
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
            if not getattr(self, "_xz_offset_updated_this_pressure", False):
                self._update_xz_track_offset()
                self._xz_offset_updated_this_pressure = True
            self._centered = True
            self._char_need_capture = True   # first entry to char should capture
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
                return self._abort("Minimum pressure reached (multiple droplets persist).")
            self.stageChanged.emit(f"Multiple droplets → decreasing pressure to {self.new_pressure:.3f} psi")
            self.droplet_positions.clear(); self.droplet_focus.clear()
            self.circularity_values.clear(); self.droplet_volumes.clear()
            self.image_counter = 0
            self.emitChangePressure()
            return

        focus_val = float(result.get('focus', 0.0))
        self.presentImageSignal.emit(annotated)

        # -------- focus control with 2-step probe per direction --------
        if focus_val < self.focus_ok_threshold:
            if self._focus_best <= 0.0:
                self._focus_best = focus_val

            improved = (focus_val >= (1.0 + self._min_focus_gain) * self._focus_best)

            if improved:
                self._focus_best = focus_val
                self._focus_same_dir_tries = 0
                self.focus_step = max(self.focus_min_step, self.focus_step // 2)
            else:
                self._focus_same_dir_tries += 1
                if self._focus_same_dir_tries >= 3:
                    self._focus_same_dir_tries = 0
                    self.focus_dir *= -1
                    self.focus_dir_switches += 1
                    self.focus_step = min(self.max_focus_step, max(self.focus_min_step, self.focus_step * 2))
                    if self.focus_dir_switches > self.focus_switch_limit:
                        return self._abort("Focus oscillation limit reached.")

            self._focus_moves_done += 1
            if self._focus_moves_done > self._focus_move_budget:
                return self._abort("Focus move budget exceeded.")

            dY = int(self.focus_dir * self.focus_step)
            self.stageChanged.emit(f"Focus low ({focus_val:.0f}) → Y move {dY} steps")
            self._safe_move_relative((0, dY, 0))
            return
        # -----------------------------------------------------------------

        # Accept replicate
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
            return self._abort("No droplet volumes captured.")
        if not all(c < self.circularity_threshold for c in self.circularity_values):
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

class PressureSweepCharacterizationProcess(BaseCalibrationProcess):
    """
    Sweep across the pressures that were measured in the trajectory scan (high -> low).
    For each pressure:
      - compute per-pressure stage velocity (steps/s) from the trajectory fit (px/us)
      - predict droplet XYZ at (emergence + sphere_delay) and move there
      - capture background, find/center/focus the droplet
      - capture N replicates and quantify volume consistency
    Emits: per-pressure entries with mean volume, CV, centers, etc.
    """

    # local signals
    pressureReady   = Signal()
    moveDone        = Signal()
    delayApplied    = Signal()
    timepointReady  = Signal()
    continueCap     = Signal()
    continueSearch  = Signal()
    dropletFound    = Signal()
    dropletCentered = Signal()
    readyToCharacterize = Signal()
    analyzeBatch    = Signal()
    nextPressure    = Signal()
    finalize        = Signal()

    def __init__(self,
                 calibration_manager,
                 model,
                 *,
                 p_step: float = None,               # pressure grid step (psi)
                 sphere_delay_us: int = 10000,
                 replicates_per_pressure: int = 20,
                 order: str = "desc",            # "desc" = high -> low (safer)
                 edge_guard_px: int = 200,
                 focus_ok_threshold: float = 5_000_000,
                 num_samples: int = 4,
                 min_pressure_separation: float = 0.005,
                 max_search_cycles: int = 4,
                 max_recentre_moves: int = 5,
                 max_oob_total: int = 12,
                 lightweight_overlays: bool = True,
                 present_every_k: int = 3,
                 parent=None):
        super().__init__(calibration_manager, model, parent)
        missing_requirements = self.missing_requirements(calibration_manager)
        if missing_requirements:
            raise ValueError("Cannot start PressureSweepCharacterizationProcess; missing prerequisites: "
                               + ", ".join(missing_requirements))
        self.phase_name = "pressure_sweep_characterization"

        # ---------- prerequisites ----------
        self.nozzle_center_machine = self.calibration_manager.get_nozzle_center()
        self.nozzle_center_px      = self.calibration_manager.get_nozzle_center_image_position()
        self.emergence_time_us     = self.calibration_manager.get_emergence_time()
        self.prev_background       = self.calibration_manager.get_background_image()
        
        get_band = getattr(self.calibration_manager, "get_primary_pressure_band", None)
        self.primary_band = get_band() if callable(get_band) else None

        # pull per-pressure trajectory fits
        traj = getattr(self.calibration_manager, "get_pressure_trajectory_result", None)
        self.traj = traj() if callable(traj) else None

        if not (self.nozzle_center_machine and self.nozzle_center_px and self.emergence_time_us and self.traj and self.traj.get("pressures")):
            self.calibrationError.emit("Sweep requires nozzle center, background, emergence, and trajectory scan results.")
            self._ready = False
        else:
            self._ready = True

        # list of (pressure, fit) we’ll actually use (build grid from traj min/max using scan step)
        self.plan = []
        if self._ready:
            all_tested = [float(rec.get("pressure")) for rec in self.traj["pressures"] if "pressure" in rec]
            if self.primary_band and len(self.primary_band) == 2:
                p_lo, p_hi = float(min(self.primary_band)), float(max(self.primary_band))
            elif all_tested:
                p_lo, p_hi = min(all_tested), max(all_tested)
            else:
                self.calibrationError.emit("Sweep needs a single band or trajectory pressures to plan.")
                self._ready = False


            if self._ready:
                # 2) Build evenly-spaced set with min-separation guard
                grid = self._make_pressure_set_by_count(p_lo, p_hi, int(num_samples), float(min_pressure_separation))

                # 3) Prepare velocity interpolation from trajectory fits
                fit_pts = [(float(rec["pressure"]),
                            float(rec.get("fit", {}).get("vx_px_per_us", 0.0)),
                            float(rec.get("fit", {}).get("vy_px_per_us", 0.0)))
                           for rec in (self.traj["pressures"] if self.traj else []) if rec.get("fit")]
                if not fit_pts:
                    self.calibrationError.emit("Trajectory scan had no valid fits to interpolate velocities.")
                    self._ready = False
                else:
                    fit_pts.sort(key=lambda t: t[0])
                    P_fit  = np.array([t[0] for t in fit_pts], dtype=float)
                    VX_fit = np.array([t[1] for t in fit_pts], dtype=float)
                    VY_fit = np.array([t[2] for t in fit_pts], dtype=float)

                    for p in grid:
                        vx = float(np.interp(p, P_fit, VX_fit))
                        vy = float(np.interp(p, P_fit, VY_fit))
                        self.plan.append({"pressure": float(round(p, 3)), "vx": vx, "vy": vy})

        if self._ready and not self.plan:
            self.calibrationError.emit("No pressures to characterize after planning.")
            self._ready = False

        if order.lower().startswith("desc"):
            self.plan.sort(key=lambda r: r["pressure"], reverse=True)
        else:
            self.plan.sort(key=lambda r: r["pressure"])

        self.i = 0  # plan index

        # ---------- policy / settings ----------
        self.sphere_delay_us   = int(sphere_delay_us)
        self.edge_guard_px     = int(edge_guard_px)
        self.repl_target       = int(replicates_per_pressure)
        self.focus_ok_threshold = float(focus_ok_threshold)

        self.max_search_cycles   = int(max_search_cycles)
        self.max_recentre_moves  = int(max_recentre_moves)
        self.max_oob_total       = int(max_oob_total)

        self.lightweight_overlays = bool(lightweight_overlays)
        self.present_every_k      = int(max(1, present_every_k))

        self.boundary_tol_px = 250          # pixels around image center accepted as "in-bounds"
        self.center_first_tol_px = 140      # first center attempt tolerance
        self._oob_streak = 0                # consecutive out-of-bound hits
        self._oob_positions = []            # recent out-of-bound centers (pixels)

        # --- offsets (persist across pressures) ---
        self._y_focus_offset_steps = 0            # persistent Y offset (steps) for best focus so far
        self._y_focus_ema_alpha    = 0.35         # EMA smoothing (0..1). Higher = react faster
        self._x_track_offset_steps = 0            # persistent X offset in steps
        self._z_track_offset_steps = 0            # persistent Z offset in steps
        self._xz_offset_ema_alpha  = 0.35         # EMA smoothing for X/Z bias
        self._xz_offset_updated_this_pressure = False

        # delay clamps (safety)
        self.min_delay_us, self.max_delay_us = 0, 50000

        # characterize buffers (per pressure)
        self._reset_char_buffers()
        self._centered = False
        self._char_need_capture = False

        self._vertical_probe_tries = 0
        self._max_vertical_probes = 2

        # stage bounds safety
        self.x_lo, self.x_hi = self._get_axis_bounds_safe('X', default_span=20000)
        self.y_lo, self.y_hi = self._get_axis_bounds_safe('Y', default_span=10000)
        self.z_lo, self.z_hi = self._get_axis_bounds_safe('Z', default_span=20000)

        # results
        self.samples = []   # list of per-pressure dicts

        # ---------- states ----------
        self.state_pick      = QState()
        self.state_applyP    = QState()
        self.state_move      = QState()
        self.state_prepBG    = QState()
        self.state_capBG     = QState()
        self.state_setDelay  = QState()
        self.state_capture   = QState()
        self.state_analyze   = QState()
        self.state_center    = QState()
        self.state_char      = QState()
        self.state_anBatch   = QState()
        self.state_final     = QFinalState()

        # enter handlers
        self.state_pick.entered.connect(self.onPickPressure)
        self.state_applyP.entered.connect(self.onApplyPressure)
        self.state_move.entered.connect(self.onMoveToTarget)
        self.state_prepBG.entered.connect(self.onPrepareBG)
        self.state_capBG.entered.connect(self.onCaptureBG)
        self.state_setDelay.entered.connect(self.onSetDelay)
        self.state_capture.entered.connect(self.onCaptureDroplet)
        self.state_analyze.entered.connect(self.onAnalyzeDroplet)
        self.state_center.entered.connect(self.onCenter)
        self.state_char.entered.connect(self.onCharacterizeLoop)
        self.state_anBatch.entered.connect(self.onAnalyzeBatch)
        self.state_final.entered.connect(self.onCompleted)

        # transitions
        for st in (self.state_pick, self.state_applyP, self.state_move, self.state_prepBG,
                   self.state_capBG, self.state_setDelay, self.state_capture, self.state_analyze,
                   self.state_center, self.state_char, self.state_anBatch):
            st.addTransition(self.finalize, self.state_final)

        self.state_pick.addTransition(self.pressureReady, self.state_applyP)
        self.state_applyP.addTransition(self.calibration_manager.settingsChangeCompleted, self.state_move)
        self.state_move.addTransition(self.moveDone, self.state_prepBG)

        self.state_prepBG.addTransition(self.calibration_manager.settingsChangeCompleted, self.state_capBG)
        self.state_capBG.addTransition(self.calibration_manager.captureCompleted, self.state_setDelay)

        self.state_setDelay.addTransition(self.delayApplied, self.state_capture)
        self.state_setDelay.addTransition(self.moveDone, self.state_setDelay)
        self.state_capture.addTransition(self.calibration_manager.captureCompleted, self.state_analyze)

        # search: loop until found or retries exhausted
        self.state_analyze.addTransition(self.continueSearch, self.state_setDelay)  # keep sweeping delay
        self.state_analyze.addTransition(self.dropletFound,  self.state_center)
        self.state_analyze.addTransition(self.readyToCharacterize, self.state_char)

        # center -> either continue search if lost, or go characterize when centered
        self.state_center.addTransition(self.continueSearch, self.state_setDelay)
        self.state_center.addTransition(self.dropletCentered, self.state_char)
        self.state_center.addTransition(self.moveDone, self.state_capture)  # recapture after recenter move

        # characterization loop
        self.state_char.addTransition(self.continueCap,  self.state_capture)
        self.state_char.addTransition(self.analyzeBatch, self.state_anBatch)
        self.state_char.addTransition(self.moveDone,   self.state_capture)  # recapture after focus move
        
        # after analysis, go to next pressure
        self.state_anBatch.addTransition(self.nextPressure, self.state_pick)

        # register
        for s in (self.state_pick, self.state_applyP, self.state_move, self.state_prepBG, self.state_capBG,
                  self.state_setDelay, self.state_capture, self.state_analyze, self.state_center,
                  self.state_char, self.state_anBatch, self.state_final):
            self.state_machine.addState(s)

        _all_pressure_states = (
            self.state_pick, self.state_applyP, self.state_move, self.state_prepBG,
            self.state_capBG, self.state_setDelay, self.state_capture, self.state_analyze,
            self.state_center, self.state_char, self.state_anBatch
        )
        for st in _all_pressure_states:
            st.addTransition(self.nextPressure, self.state_pick)

        self.state_machine.setInitialState(self.state_pick)

    @staticmethod
    def missing_requirements(cm) -> list[str]:
        """Return a list of human-readable missing prerequisites."""
        missing = []
        if cm.get_nozzle_center() is None:
            missing.append("Nozzle center (machine coords)")
        if cm.get_nozzle_center_image_position() is None:
            missing.append("Nozzle center (image coords)")
        if cm.get_background_image() is None:
            missing.append("Background image")
        if cm.get_emergence_time() is None:
            missing.append("Emergence time")
        if cm.get_pressure_trajectory_result() is None:
            missing.append("Pressure trajectory scan results")
        return missing

    # ---------- helpers (generic) ----------
    def _get_axis_bounds_safe(self, axis:str, default_span:int):
        try:
            lo, hi = self.model.machine_model.get_axis_bounds(axis)
            return int(lo), int(hi)
        except Exception:
            base = int(self.nozzle_center_machine.get(axis, 0)) if self.nozzle_center_machine else 0
            return base - default_span, base + default_span

    def _clamp_xyz(self, x:int, y:int, z:int):
        return (max(self.x_lo, min(self.x_hi, int(x))),
                max(self.y_lo, min(self.y_hi, int(y))),
                max(self.z_lo, min(self.z_hi, int(z))))

    def _safe_move_abs(self, xyz):
        X, Y, Z = self._clamp_xyz(*xyz)
        cur = self.model.machine_model.get_current_position_dict()
        if (int(cur['X']) == X) and (int(cur['Y']) == Y) and (int(cur['Z']) == Z):
            self.moveDone.emit()
            return
        self.calibration_manager.moveAbsoluteRequested.emit((X, Y, Z), self.moveDone.emit)

    def _make_pressure_set_by_count(self, p_lo: float, p_hi: float, n: int, min_sep: float=0.005) -> list[float]:
        lo, hi = (float(min(p_lo, p_hi)), float(max(p_lo, p_hi)))
        width = hi - lo
        if n <= 1:
            return [round((lo + hi) * 0.5, 3)]
        # enforce feasible n under min separation
        max_points = int(width // max(min_sep, 1e-6)) + 1
        n_eff = max(2, min(n, max_points))  # always include both ends
        vals = list(np.linspace(lo, hi, n_eff))
        # drop candidates that violate min_sep after rounding/uniqueness
        out = []
        for v in sorted({round(x, 3) for x in vals}):
            if not out or (v - out[-1]) >= (min_sep - 1e-9):
                out.append(v)
        # Guarantee exact lo/hi are present
        if out[0] != round(lo, 3):
            out[0] = round(lo, 3)
        if out[-1] != round(hi, 3):
            out[-1] = round(hi, 3)
        # If spacing collapsed, trim middle points until all gaps ≥ min_sep
        def gaps_ok(seq):
            return all((seq[i+1]-seq[i]) >= (min_sep - 1e-9) for i in range(len(seq)-1))
        while len(out) > 2 and not gaps_ok(out):
            # remove the closest pair's middle index (bias to remove a middle)
            diffs = [(out[i+1]-out[i], i) for i in range(len(out)-1)]
            _, i = min(diffs, key=lambda t: t[0])
            # drop whichever of {i or i+1} is more interior
            drop = i+1 if (i+1) < (len(out)-1) else i
            out.pop(drop)
        return out

    def _reset_char_buffers(self):
        self._delay_offsets_us = [0, +500, -500, +1000, -1000, +1500, -1500]
        self._delay_try_index = 0
        self.current_delay_us = None
        self.num_images = self.repl_target
        self.image_counter = 0
        self.circularity_threshold = 1.18
        self.circularity_values = []
        self.droplet_volumes = []
        self.droplet_positions = []
        self.droplet_focus = []
        self.measurements = []

        # track multiple-droplet frames & a guard to prevent hangs
        self.multiple_droplet_hits = 0
        self._char_attempts = 0
        # e.g., allow up to 4× the requested replicates worth of attempts
        self._char_attempt_limit = max(3 * self.repl_target, self.repl_target + 20)


        # focus controls
        self.focus_ok_threshold = float(self.focus_ok_threshold)
        self.focus_dir, self.focus_step = +1, 16
        self.focus_min_step = 8
        self.focus_dir_switches, self.focus_switch_limit = 0, 6
        self._focus_best = 0.0
        self._focus_same_dir_tries = 0
        self._focus_moves_done = 0
        self._focus_move_budget = 60
        self._min_focus_gain = 0.02
        self._lost_count, self._lost_limit = 0, 5
        self._oob_streak = 0
        self._oob_positions = []

        self._xz_offset_updated_this_pressure = False

        # search & OOB/recenter guards (reset each pressure)
        self._search_fail_cycles = 0      # times we exhausted delay sweep + nudged
        self._recentre_moves = 0          # number of recenter moves issued during characterization
        self._oob_total = 0               # total OOB hits seen during characterization
        self._bad_reason = None           # reason string when we abort this pressure

        self._vertical_probe_tries = 0    # how many half-frame-up probes we've tried (max 2)
        self._max_vertical_probes  = 2

    # ---------- per-pressure planning ----------
    def _compute_stage_scales_steps_per_px(self):
        """
        Estimate steps/px mapping at current pose using the camera model.
        Returns (kx, ky, kz) as steps per +1px in image (x or y).
        (Ky is usually ~0 for in-plane centering; keep for completeness.)
        """
        cur = self.model.machine_model.get_current_position_dict()
        nx, ny = int(self.nozzle_center_px[0]), int(self.nozzle_center_px[1])

        def pix_to_steps(px, py):
            m = self.model.droplet_camera_model.convert_pixel_position_to_motor_steps((px, py), cur)
            return int(m['X']), int(m.get('Y', 0)), int(m['Z'])

        x0, y0, z0 = pix_to_steps(nx, ny)
        x1, y1, z1 = pix_to_steps(nx + 100, ny)
        x2, y2, z2 = pix_to_steps(nx, ny + 100)

        kx = (x1 - x0) / 100.0
        ky = (y1 - y0) / 100.0 if 'Y' in cur else 0.0
        kz = (z2 - z0) / 100.0
        return float(kx), float(ky), float(kz)

    def _image_vel_to_stage_vel(self, vx_px_per_us: float, vy_px_per_us: float):
        """
        Convert (vx, vy) in px/us into (vX, vY, vZ) in steps/s.
        We assume image-x -> stage X; image-y -> stage Z (note: image y+ is down).
        """
        kx, ky, kz = self._compute_stage_scales_steps_per_px()
        s_per_us = 1e6  # µs -> s
        vX = kx * vx_px_per_us * s_per_us
        # many rigs don't shift stage Y from image motion; keep 0 unless you really map it
        vY = 0.0
        # image y increases downward; many Z axes are positive upward, so invert:
        vZ = -kz * vy_px_per_us * s_per_us
        return float(vX), float(vY), float(vZ)

    def _predict_target_xyz(self, vec_steps_per_s, delay_us: int):
        dt_s = max(0.0, (int(delay_us) - int(self.emergence_time_us)) * 1e-6)
        vX, vY, vZ = vec_steps_per_s
        X = int(round(self.nozzle_center_machine['X'] + vX * dt_s))
        Y = int(round(self.nozzle_center_machine['Y'] + vY * dt_s))
        Z = int(round(self.nozzle_center_machine['Z'] + vZ * dt_s))
        return self._clamp_xyz(X, Y, Z)

    def _clamp_delay(self, d_us: int) -> int:
        return int(max(self.min_delay_us, min(self.max_delay_us, int(d_us))))

    def _make_pressure_grid(self, p_lo: float, p_hi: float, step: float) -> list[float]:
        """Inclusive grid from p_lo to p_hi using step, rounded nicely."""
        lo, hi = (float(p_lo), float(p_hi))
        if hi < lo:
            lo, hi = hi, lo
        if step <= 0:
            step = 0.05
        n = int(max(1, round((hi - lo) / step))) + 1
        grid = [round(lo + i * step, 3) for i in range(n)]
        if grid[-1] < hi - 1e-6:
            grid.append(round(hi, 3))
        return grid

    # ---------- states ----------
    @Slot()
    def onPickPressure(self):
        if not self._ready:
            self.finalize.emit()
            return
        if self.i >= len(self.plan):
            self.finalize.emit()
            return

        rec = self.plan[self.i]
        self.cur_pressure = float(rec["pressure"])
        vx, vy = float(rec["vx"]), float(rec["vy"])
        # compute per-pressure stage velocity
        self.vec_steps_per_s = self._image_vel_to_stage_vel(vx, vy)

        # choose a good initial delay
        seed = int(self.emergence_time_us + self.sphere_delay_us)
        self.target_delay_us = self._clamp_delay(seed)

        self.stageChanged.emit(f"[{self.i+1}/{len(self.plan)}] Pressure {self.cur_pressure:.3f} psi "
                               f"(vx={vx:.4f} px/µs, vy={vy:.4f} px/µs)")
        self._reset_char_buffers()
        self._centered = False
        self._char_need_capture = False
        self.pressureReady.emit()

    @Slot()
    def onApplyPressure(self):
        settings = {"print_pressure": float(self.cur_pressure), "num_droplets": 0}
        self.stageChanged.emit(f"Applying pressure {self.cur_pressure:.3f} psi and preparing background")
        self.calibration_manager.changeSettingsRequested.emit(settings, self.calibration_manager.emitSettingsChangeCompleted)

    @Slot()
    def onMoveToTarget(self):
        tgt = self._predict_target_xyz(self.vec_steps_per_s, self.target_delay_us)
        # apply persistent corrections
        tgt = ( int(tgt[0] + self._x_track_offset_steps),
                int(tgt[1] + self._y_focus_offset_steps),
                int(tgt[2] + self._z_track_offset_steps) )
        self.stageChanged.emit(f"Moving to predicted target @ {self.target_delay_us} µs → {tgt}")
        self._safe_move_abs(tgt)

    @Slot()
    def onPrepareBG(self):
        self.stageChanged.emit("Setting num_droplets=0 and capturing background")
        self.calibration_manager.changeSettingsRequested.emit(
            {"num_droplets": 0}, self.calibration_manager.emitSettingsChangeCompleted
        )

    @Slot()
    def onCaptureBG(self):
        self._capture_with_policy(
            set_attr="background_image",
            stage_text="Capturing background",
            attempts_total=3, retry_delay_ms=120, guard_timeout_ms=10_000,
            final_error_msg="Background capture failed."
        )

    @Slot()
    def onSetDelay(self):
        if self._delay_try_index >= len(self._delay_offsets_us):
            # exhausted a sweep
            self._delay_try_index = 0

            # try up to two half-frame-up probes BEFORE counting a search cycle
            if self._vertical_probe_tries < self._max_vertical_probes:
                self._vertical_probe_tries += 1
                self._probe_half_frame_up()
                return  # will come back here via moveDone→state_setDelay

            # If probes are exhausted, proceed with your existing nudge/cycle logic
            self._vertical_probe_tries = 0  # reset for future sweeps at this pressure
            self._search_fail_cycles += 1
            if self._search_fail_cycles >= self.max_search_cycles:
                self.stageChanged.emit("Inconsistent imaging: too many delay sweeps → skip pressure")
                self._bad_reason = "search_fail_cycles"
                self._record_pressure_result(valid=False, reason=self._bad_reason)
                self.i += 1
                self.nextPressure.emit()
                return

            nudge = 0.002
            self.stageChanged.emit("Droplet not found yet → nudging along predicted path")
            self._safe_move_abs(
                self._predict_target_xyz(self.vec_steps_per_s,
                                        self.target_delay_us + int(1000 * nudge))
            )
            return  # wait for moveDone

    @Slot()
    def onCaptureDroplet(self):
        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text=f"Capture droplet @ {self.current_delay_us} µs",
            attempts_total=5, retry_delay_ms=75, guard_timeout_ms=10_000,
            final_error_msg=f"Failed to capture droplet @ {self.current_delay_us} µs."
        )

    @Slot()
    def onAnalyzeDroplet(self):
        contour, overlay = self.model.droplet_camera_model.identify_droplet_contour(
            self.droplet_image, self.background_image
        )
        if contour is None:
            self.stageChanged.emit("No droplet in frame → try next delay")
            self.presentImageSignal.emit(overlay)
            self.continueSearch.emit()
            return

        # Found something
        x, y, w, h = cv2.boundingRect(contour)
        cxy = (x + w//2, y + h//2)
        self.presentImageSignal.emit(overlay)
        self.measurements.append({"flash_delay": int(self.current_delay_us), "center": cxy})
        self._lost_count = 0
        self._vertical_probe_tries = 0
        if self._centered:
            # In replicate mode: go straight to characterization (don’t re-center)
            self.readyToCharacterize.emit()
        else:
            # In search mode: go center it
            self.dropletFound.emit()
        return

    @Slot()
    def onCenter(self):
        contour, overlay = self.model.droplet_camera_model.identify_droplet_contour(
            self.droplet_image, self.background_image
        )
        if contour is None:
            self._lost_count += 1
            if self._lost_count > self._lost_limit:
                self.stageChanged.emit("Droplet repeatedly lost while centering → restart search")
                self.continueSearch.emit()
                return
            self.stageChanged.emit("Droplet lost while centering → retry delay sweep")
            self.presentImageSignal.emit(overlay)
            self.continueSearch.emit()
            return

        x, y, w, h = cv2.boundingRect(contour)
        cxy = (x + w//2, y + h//2)
        H, W = overlay.shape[:2]
        target = (W//2, H//2)
        tol = 150
        if abs(cxy[0]-target[0]) <= tol and abs(cxy[1]-target[1]) <= tol:
            self.stageChanged.emit("Droplet centered")
            self._centered = True
            self._char_need_capture = True
            self.dropletCentered.emit()
            return

        dX, dY, dZ = self.model.droplet_camera_model.calculate_move_to_target(cxy, target)
        dX = int(max(-1200, min(1200, dX)))
        dZ = int(max(-1200, min(1200, dZ)))

        # Count recenter attempt during centering
        self._recentre_moves += 1
        print('Recenter counter (onCenter):', self._recentre_moves)
        self.stageChanged.emit(f"Centering recenter #{self._recentre_moves}/{self.max_recentre_moves}")
        if self._recentre_moves >= self.max_recentre_moves:
            self.stageChanged.emit("Inconsistent imaging: too many recenter moves (centering) → skip pressure")
            self._bad_reason = "recentre_limit_center"
            self._record_pressure_result(valid=False, reason=self._bad_reason)
            self.i += 1
            self.nextPressure.emit()
            return
        
        self.stageChanged.emit(f"Recentering move (clamped): {dX},{0},{dZ}")
        self._safe_move_abs(self._clamp_xyz(
            self.model.machine_model.get_current_position_dict()['X'] + dX,
            self.model.machine_model.get_current_position_dict()['Y'] + 0,
            self.model.machine_model.get_current_position_dict()['Z'] + dZ
        ))

    @Slot()
    def onCharacterizeLoop(self):
        # First time after centering: capture a fresh frame
        if self._char_need_capture:
            self._char_need_capture = False
            self.continueCap.emit()
            return
        # capture a replicate; when focus inadequate, adjust Y and recapture
        result, annotated = self.model.droplet_camera_model.characterize_droplet(
            self.droplet_image, self.background_image
        )

        # Count every frame we evaluate so we can bail out safely if needed
        self._char_attempts += 1

        if result is None:
            self.stageChanged.emit("Replicate failed → recapturing")
            if self._char_attempts >= self._char_attempt_limit:
                self.stageChanged.emit("Too many failed frames → analyzing partial batch")
                self.analyzeBatch.emit()
                return
            self.continueCap.emit()
            return

        # tolerate multiple droplets — log and keep going, do not count as a replicate
        if result == 'Multiple':
            self.multiple_droplet_hits += 1
            self.measurements.append({
                "flash_delay": int(self.current_delay_us),
                "pressure": float(self.cur_pressure),
                "event": "multiple_droplets"
            })
            self.presentImageSignal.emit(annotated)
            self.stageChanged.emit("Multiple droplets in frame → skipping (replicate not counted)")
            if self._char_attempts >= self._char_attempt_limit:
                self.stageChanged.emit("Too many problematic frames (multiple/failed) → analyzing partial batch")
                self.analyzeBatch.emit()
                return
            self.continueCap.emit()
            return
        
        # ---------- CENTER FIRST ----------
        center_px = tuple(map(int, result.get("center", (0, 0))))
        self.presentImageSignal.emit(annotated)
        if self._is_within(center_px, self.center_first_tol_px) and not getattr(self, "_xz_offset_updated_this_pressure", False):
            self._update_xz_track_offset()
            self._xz_offset_updated_this_pressure = True

        # If not tightly centered, recenter immediately before any focus work
        if not self._is_within(center_px, self.center_first_tol_px):
            # Count as a recenter attempt (center-first path)
            self._recentre_moves += 1
            print('Recenter counter (onCharacterizeLoop):', self._recentre_moves)

            self.stageChanged.emit(f"Center-first recenter #{self._recentre_moves}/{self.max_recentre_moves}")

            # If it's far outside the broader boundary, count as OOB too
            if not self._is_within(center_px, self.boundary_tol_px):
                self._oob_total += 1
                self.stageChanged.emit(f"OOB (center-first path): total={self._oob_total}/{self.max_oob_total}")
                if self._oob_total >= self.max_oob_total:
                    self.stageChanged.emit("Inconsistent imaging: too many out-of-bounds hits → skip pressure")
                    self._bad_reason = "oob_total_limit_centerfirst"
                    self._record_pressure_result(valid=False, reason=self._bad_reason)
                    self.i += 1
                    self.nextPressure.emit()
                    return

            # Recenter-move guard
            if self._recentre_moves >= self.max_recentre_moves:
                self.stageChanged.emit("Inconsistent imaging: too many recenter moves (center-first) → skip pressure")
                self._bad_reason = "recentre_limit_centerfirst"
                self._record_pressure_result(valid=False, reason=self._bad_reason)
                self.i += 1
                self.nextPressure.emit()
                return

            # Proceed with the move
            self._recentre_immediate(center_px)
            return
        
        focus_val = float(result.get('focus', 0.0))
        self.presentImageSignal.emit(annotated)

        # If focus is already good, capture this Y as a candidate best
        if focus_val >= self.focus_ok_threshold:
            self._update_y_focus_offset()

        # focus control (same policy as your search process)
        if focus_val < self.focus_ok_threshold:
            if self._focus_best <= 0.0:
                self._focus_best = focus_val

            improved = (focus_val >= (1.0 + self._min_focus_gain) * self._focus_best)
            if improved:
                self._focus_best = focus_val
                self._focus_same_dir_tries = 0
                self.focus_step = max(self.focus_min_step, self.focus_step // 2)
            else:
                self._focus_same_dir_tries += 1
                if self._focus_same_dir_tries >= 4:
                    self._focus_same_dir_tries = 0
                    self.focus_dir *= -1
                    self.focus_dir_switches += 1
                    self.focus_step = min(16, max(self.focus_min_step, self.focus_step * 2))
                    if self.focus_dir_switches > 6:
                        self.stageChanged.emit("Focus oscillation limit reached → advance pressure")
                        self._record_pressure_result(valid=False)
                        self.i += 1
                        self.nextPressure.emit()
                        return

            self._focus_moves_done += 1
            if self._focus_moves_done > 60:
                self.stageChanged.emit("Focus budget exceeded → advance pressure")
                self._record_pressure_result(valid=False)
                self.i += 1
                self.nextPressure.emit()
                return

            dY = int(self.focus_dir * self.focus_step)
            self.stageChanged.emit(f"Focus low ({focus_val:.0f}) → Y move {dY} steps")
            cur = self.model.machine_model.get_current_position_dict()
            self._safe_move_abs((cur['X'], cur['Y'] + dY, cur['Z']))
            return

        # Accept replicate
        self.focus_step = max(self.focus_min_step, self.focus_step // 2)
        center_px = tuple(map(int, result.get("center", (0, 0))))
        self.circularity_values.append(float(result.get("circularity_ellipse", 99.0)))
        self.droplet_positions.append(center_px)
        self.droplet_focus.append(focus_val)
        self.droplet_volumes.append(float(result.get("volume", 0.0)))
        self.image_counter += 1

        if self._check_boundary_and_maybe_recentre(center_px):
            # A recenter move was issued (average of 2 consecutive OOB hits).
            # After the move completes, state_char → (moveDone) → state_capture → fresh frame.
            return

        if self.image_counter < self.num_images:
            self.continueCap.emit()
        else:
            self.analyzeBatch.emit()

    @Slot()
    def onAnalyzeBatch(self):
        # Only keep “good” (circular) replicates
        good = [v for v, c in zip(self.droplet_volumes, self.circularity_values) if c < self.circularity_threshold]
        if len(good) < max(3, self.num_images // 2):
            self.stageChanged.emit("Too few good replicates (circularity) → mark invalid and continue")
            self._record_pressure_result(valid=False)
        else:
            mean_vol = float(np.mean(good))
            cv_vol   = float(np.std(good) / (mean_vol + 1e-9) * 100.0)
            mean_center = tuple(np.mean(np.array(self.droplet_positions), axis=0).astype(int))

            machine_position = self.model.machine_model.get_current_position_dict()
            drop_machine = self.model.droplet_camera_model.convert_pixel_position_to_motor_steps(
                mean_center, machine_position
            )

            try:
                summary_img = self._annotate_char_summary_image(mean_center, mean_vol, cv_vol)
                self.presentImageSignal.emit(summary_img)
            except Exception:
                pass

            self.samples.append({
                "pressure": float(self.cur_pressure),
                "delay_us": int(self.current_delay_us),
                "mean_center_px": mean_center,
                "mean_volume": mean_vol,
                "cv_volume_percent": cv_vol,
                "positions_px": [tuple(map(int, p)) for p in self.droplet_positions],
                "volumes": [float(v) for v in self.droplet_volumes],
                "focus_values": [float(f) for f in self.droplet_focus],
                "circularity_values": [float(c) for c in self.circularity_values],
                "mean_position_machine": drop_machine,
                "multiple_detections": int(self.multiple_droplet_hits),
                "y_focus_offset_steps": int(self._y_focus_offset_steps),
                "valid": True
            })

        # advance plan
        self.i += 1
        self._reset_char_buffers()
        self.nextPressure.emit()

    def _record_pressure_result(self, valid: bool, reason: str | None = None):
        self.samples.append({
            "pressure": float(self.cur_pressure),
            "delay_us": int(self.current_delay_us or self.target_delay_us),
            "mean_center_px": None,
            "mean_volume": None,
            "cv_volume_percent": None,
            "positions_px": [],
            "volumes": [],
            "focus_values": [],
            "circularity_values": [],
            "mean_position_machine": None,
            "valid": bool(valid),
            "invalid_reason": (None if valid else (reason or "unspecified"))
        })
    
    def _annotate_char_summary_image(self, mean_center, mean_vol, cv_vol):
        """
        Draw all replicate centers (red), the mean center (green), and mean/CV text.
        """
        img = (self.droplet_image.copy()
               if self.droplet_image.ndim == 3
               else cv2.cvtColor(self.droplet_image, cv2.COLOR_GRAY2BGR))
        for p in self.droplet_positions:
            cv2.circle(img, tuple(map(int, p)), 5, (0, 0, 255), -1)
        cv2.circle(img, tuple(map(int, mean_center)), 8, (0, 255, 0), -1)
        cv2.putText(img, f"Mean vol: {mean_vol:.2f}", (10, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,0), 2)
        cv2.putText(img, f"CV vol: {cv_vol:.2f}%", (10, 64),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,0), 2)
        # draw the accepted boundary box for clarity
        H, W = img.shape[:2]
        b = int(self.boundary_tol_px)
        cv2.rectangle(img, (W//2 - b, H//2 - b), (W//2 + b, H//2 + b), (80,80,80), 1)
        return img
    
    def _is_within(self, center_px, tol_px:int) -> bool:
        """Return True if `center_px` is within a tol_px box around the image center."""
        H, W = self.droplet_image.shape[:2]
        cx, cy = int(center_px[0]), int(center_px[1])
        tx, ty = W // 2, H // 2
        return (abs(cx - tx) <= int(tol_px)) and (abs(cy - ty) <= int(tol_px))


    def _recentre_immediate(self, center_px) -> None:
        """Single-shot recenter to the current droplet center, then recapture."""
        H, W = self.droplet_image.shape[:2]
        target = (W // 2, H // 2)
        dX, dY, dZ = self.model.droplet_camera_model.calculate_move_to_target(
            (int(center_px[0]), int(center_px[1])), target
        )
        # center moves are X/Z only; clamp for safety
        dX = int(max(-1200, min(1200, dX)))
        dZ = int(max(-1200, min(1200, dZ)))

        cur = self.model.machine_model.get_current_position_dict()
        self.stageChanged.emit(f"Center-first policy: recenter before focusing (move XZ=({dX},{dZ}))")
        self._char_need_capture = True  # after motion, take a fresh frame
        self._safe_move_abs(self._clamp_xyz(cur['X'] + dX, cur['Y'], cur['Z'] + dZ))

    def _check_boundary_and_maybe_recentre(self, center_px) -> bool:
        """
        Track out-of-bound streaks during characterization.
        Only after >=2 consecutive OOB hits do a single recenter move to the *average*
        of those OOB centers. Returns True iff a move was issued.
        """
        if self._is_within(center_px, self.boundary_tol_px):
            # Good sample → reset streak
            self._oob_streak = 0
            self._oob_positions.clear()
            return False

        # OOB sample
        self._oob_streak += 1
        self._oob_total  += 1
        self._oob_positions.append(tuple(map(int, center_px)))

                # Hard limits on OOB behavior
        if self._oob_total >= self.max_oob_total:
            self.stageChanged.emit("Inconsistent imaging: too many out-of-bounds hits → skip pressure")
            self._bad_reason = "oob_total_limit"
            self._record_pressure_result(valid=False, reason=self._bad_reason)
            self.i += 1
            self.nextPressure.emit()
            return True  # (we are leaving anyway)

        if self._oob_streak < 2:
            # First miss → just flag it, no movement
            self.stageChanged.emit("Out-of-bound droplet (1st) → holding position")
            return False

        # Two consecutive OOB → move once to average offset
        avgx = int(round(sum(p[0] for p in self._oob_positions) / len(self._oob_positions)))
        avgy = int(round(sum(p[1] for p in self._oob_positions) / len(self._oob_positions)))

        H, W = self.droplet_image.shape[:2]
        target = (W // 2, H // 2)
        dX, dY, dZ = self.model.droplet_camera_model.calculate_move_to_target((avgx, avgy), target)
        # center moves are X/Z only
        dX = int(max(-1200, min(1200, dX)))
        dZ = int(max(-1200, min(1200, dZ)))

        cur = self.model.machine_model.get_current_position_dict()
        self.stageChanged.emit(f"2x out-of-bound → recenter to averaged offset: move XZ=({dX},{dZ})")
        self._oob_streak = 0
        self._oob_positions.clear()
        self._char_need_capture = True  # get a fresh frame after motion
        
        self._recentre_moves += 1               # NEW: count recenter moves
        print('Recenter counter (check_boundary):', self._recentre_moves)
        if self._recentre_moves >= self.max_recentre_moves:
            self.stageChanged.emit("Inconsistent imaging: too many recenter moves → skip pressure")
            self._bad_reason = "recentre_limit"
            self._record_pressure_result(valid=False, reason=self._bad_reason)
            self.i += 1
            self.nextPressure.emit()
            return True
        
        self._safe_move_abs(self._clamp_xyz(cur['X'] + dX, cur['Y'], cur['Z'] + dZ))
        return True

    def _update_y_focus_offset(self):
        """
        Measure current stage Y relative to the nozzle-center Y and
        update the EMA'd focus offset in steps.
        """
        try:
            cur = self.model.machine_model.get_current_position_dict()
            baseY = int(self.nozzle_center_machine.get('Y', 0))
            curY  = int(cur.get('Y', baseY))
            delta = curY - baseY
            a = float(self._y_focus_ema_alpha)
            self._y_focus_offset_steps = int(round((1.0 - a) * self._y_focus_offset_steps + a * delta))
            self.stageChanged.emit(f"Focus OK → update Y-offset = {self._y_focus_offset_steps} steps (EMA)")
        except Exception as e:
            # Non-fatal: just log
            self.stageChanged.emit(f"Could not update Y-offset (using previous): {e}")
    
    def _update_xz_track_offset(self):
        """
        Update persistent X/Z bias (steps) so future predicted targets include this correction.
        Uses EMA toward the difference between 'predicted' and 'actual centered' pose.
        """
        try:
            # prefer the searched-and-found delay for accuracy
            used_delay = int(self.current_delay_us) if self.current_delay_us is not None else int(self.target_delay_us)
            predX, predY, predZ = self._predict_target_xyz(self.vec_steps_per_s, used_delay)
            cur = self.model.machine_model.get_current_position_dict()
            ex = int(cur['X']) - int(predX)
            ez = int(cur['Z']) - int(predZ)
            a  = float(self._xz_offset_ema_alpha)
            self._x_track_offset_steps = int(round((1.0 - a) * self._x_track_offset_steps + a * ex))
            self._z_track_offset_steps = int(round((1.0 - a) * self._z_track_offset_steps + a * ez))
            self.stageChanged.emit(
                f"Trajectory bias update → X:{self._x_track_offset_steps} Z:{self._z_track_offset_steps} (EMA)"
            )
        except Exception as e:
            self.stageChanged.emit(f"Could not update X/Z bias: {e}")
    
    def _probe_half_frame_up(self):
        """
        Move the FoV 'up' by half a frame so we can see droplets closer to the nozzle.
        We interpret 'up' as negative image-y. Using kz [steps/px], we translate to a Z move.
        """
        try:
            if self.background_image is not None:
                H, W = self.background_image.shape[:2]
            elif getattr(self, "droplet_image", None) is not None:
                H, W = self.droplet_image.shape[:2]
            else:
                # conservative default if we somehow don't have an image yet
                H, W = 1080, 1920

            kx, ky, kz = self._compute_stage_scales_steps_per_px()
            dy_px = - (H // 2)   # 'up' in image (if your sign is opposite, change to +H//2)
            dZ = int(round(kz * dy_px))

            cur = self.model.machine_model.get_current_position_dict()
            tgt = (cur['X'], cur['Y'], cur['Z'] + dZ)
            self.stageChanged.emit(f"No droplet after sweep → half-frame UP probe #{self._vertical_probe_tries}/{self._max_vertical_probes}")
            self._safe_move_abs(self._clamp_xyz(*tgt))  # state_setDelay has a moveDone→state_setDelay transition
        except Exception as e:
            self.stageChanged.emit(f"Half-frame probe failed: {e}")

    @Slot()
    def onCompleted(self):
        result = {
            "pressures": self.samples,
            "order": "desc",
            "sphere_delay_us": int(self.sphere_delay_us),
            "nozzle_center_px": self.nozzle_center_px,
            "nozzle_center_machine": self.nozzle_center_machine,
            "emergence_time_us": int(self.emergence_time_us),
        }
        self.calibrationDataUpdated.emit({"measurements": [], "result": result})
        self.stageChanged.emit("Pressure sweep characterization complete")
        self.calibrationCompleted.emit()

class DropletTimecourseProcess(BaseCalibrationProcess):
    """
    Capture a time course of the droplet generation process.

    Behavior:
      - Compute start = first whole 100 µs BEFORE the emergence time (clamped at 0).
      - Capture 1 image every 100 µs from start to start + window_us (inclusive).
      - Stamp each image with the current flash delay (bottom-right, large black font).
      - Do NOT change pressure or pulse width; we only set flash_delay and num_droplets=1.

    Result payload shape:
      {
        "emergence_time_us": ...,
        "start_delay_us": ...,
        "step_us": 100,
        "window_us": 8000,
        "delays": [list of delays],
        "frames": [
            {"delay_us": d, "ok": true/false}
            ...
        ]
      }
    """

    # State-machine signals
    setupReady     = Signal()
    delayApplied   = Signal()
    nextDelay      = Signal()
    finalize       = Signal()

    def __init__(self, calibration_manager, model,
                 *,
                 step_us: int = 200,
                 window_us: int = 8000,
                 parent=None):
        super().__init__(calibration_manager, model, parent)
        self.phase_name = "droplet_timecourse"

        # --- prerequisites ---
        self.emergence_time_us = self.calibration_manager.get_emergence_time()
        self.background_image  = self.calibration_manager.get_background_image()
        self._ready = self.emergence_time_us is not None

        if not self._ready:
            self.calibrationError.emit("Timecourse requires an estimated emergence time.")
            return

        # --- schedule of delays ---
        self.step_us   = int(max(1, step_us))
        self.window_us = int(max(self.step_us, window_us))
        self.start_delay_us = max(0, (int(self.emergence_time_us) // self.step_us) * self.step_us - self.step_us)
        stop = self.start_delay_us + self.window_us
        self.delays = list(range(self.start_delay_us, stop + 1, self.step_us))
        self._delay_index = 0

        # --- outputs ---
        self.frames = []  # list of {"delay_us": int, "ok": bool}
        self.annotated_image = None

        # ---------- states ----------
        self.state_prepare = QState()
        self.state_apply   = QState()
        self.state_capture = QState()
        self.state_annot   = QState()
        self.state_final   = QFinalState()

        # enters
        self.state_prepare.entered.connect(self.onPrepare)
        self.state_apply.entered.connect(self.onApplyDelay)
        self.state_capture.entered.connect(self.onCaptureFrame)
        self.state_annot.entered.connect(self.onAnnotateAndAdvance)
        self.state_final.entered.connect(self.onCompleted)

        # robust finalize from anywhere
        for st in (self.state_prepare, self.state_apply, self.state_capture, self.state_annot):
            st.addTransition(self.finalize, self.state_final)

        # transitions
        self.state_prepare.addTransition(self.setupReady, self.state_apply)
        self.state_apply.addTransition(self.delayApplied, self.state_capture)
        self.state_capture.addTransition(self.calibration_manager.captureCompleted, self.state_annot)
        self.state_annot.addTransition(self.nextDelay, self.state_apply)

        # register
        for s in (self.state_prepare, self.state_apply, self.state_capture, self.state_annot, self.state_final):
            self.state_machine.addState(s)
        self.state_machine.setInitialState(self.state_prepare)

    # ---------- helpers ----------
    def _put_delay_stamp(self, img, delay_us: int):
        """Draw large black 'XXXX µs' at bottom-right."""
        if img is None:
            return None
        if img.ndim == 2:
            vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        else:
            vis = img.copy()

        text = f"{int(delay_us)} usec"
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 2.0
        thickness = 4
        (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
        H, W = vis.shape[:2]
        x = max(8, W - tw - 16)
        y = max(th + 8, H - 16)
        # Draw the text (black as requested)
        cv2.putText(vis, text, (x, y), font, scale, (0, 0, 0), thickness, cv2.LINE_AA)
        return vis

    # ---------- state handlers ----------
    @Slot()
    def onPrepare(self):
        if not self._ready or not self.delays:
            self.calibrationError.emit("Timecourse not ready or no delays scheduled.")
            self.finalize.emit()
            return

        self.stageChanged.emit(
            f"Timecourse: emergence={int(self.emergence_time_us)} µs, "
            f"start={self.start_delay_us} µs, step={self.step_us} µs, window={self.window_us} µs "
            f"({len(self.delays)} frames)"
        )

        # Optional: ensure we are not printing during background view
        # We won't recapture background here—use any existing background if needed downstream.
        self.setupReady.emit()

    @Slot()
    def onApplyDelay(self):
        if self._delay_index >= len(self.delays):
            self.finalize.emit()
            return

        d = int(self.delays[self._delay_index])
        self.current_delay_us = d
        self.stageChanged.emit(f"Setting flash_delay = {d} µs")
        # Only manipulate flash delay and ensure a single droplet per capture
        settings = {"flash_delay": d, "num_droplets": 1}
        self.calibration_manager.changeSettingsRequested.emit(settings, self.delayApplied.emit)

    @Slot()
    def onCaptureFrame(self):
        d = int(self.current_delay_us)
        self._capture_with_policy(
            set_attr="raw_frame_image",
            stage_text=f"Capturing timecourse frame @ {d} µs",
            attempts_total=5, retry_delay_ms=50, guard_timeout_ms=8000,
            final_error_msg=f"Capture failed at delay {d} µs"
        )

    @Slot()
    def onAnnotateAndAdvance(self):
        d = int(self.current_delay_us)
        ok = hasattr(self, "raw_frame_image") and (self.raw_frame_image is not None)
        if not ok:
            self.frames.append({"delay_us": d, "ok": False})
            self.stageChanged.emit(f"Frame @ {d} µs: missing image")
        else:
            ann = self._put_delay_stamp(self.raw_frame_image, d)
            self.annotated_image = ann
            # stream to UI
            try:
                self.presentImageSignal.emit(ann)
            except Exception:
                pass
            self.frames.append({"delay_us": d, "ok": True})

        # advance
        self._delay_index += 1
        if self._delay_index >= len(self.delays):
            self.finalize.emit()
        else:
            self.nextDelay.emit()

    @Slot()
    def onCompleted(self):
        result = {
            "emergence_time_us": int(self.emergence_time_us),
            "start_delay_us": int(self.start_delay_us),
            "step_us": int(self.step_us),
            "window_us": int(self.window_us),
            "delays": [int(x) for x in self.delays],
            "frames": self.frames[:],  # shallow copy
        }
        # Publish results (no “measurements” for this simple capture)
        self.calibrationDataUpdated.emit({"measurements": [], "result": result})
        self.stageChanged.emit("Droplet timecourse capture complete")
        self.calibrationCompleted.emit()


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
        self.ext_counter = 0
        self.flash_duration = 1000
        self.flash_delay = 5000
        self.num_droplets = 1
        self.exposure_time = 30000
        self.analysis_active = False
        self.saving_active = False
        self.image_width = 1088
        self.image_height = 1456

        self.intensity_threshold = 150
        self.circularity_threshold = 1.18
        self.min_area_threshold = 10
        self.edge_margin = 10

        self._k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self._roi_cache = None  # (h, w, nzy, margin_up, band_half, roi_top, mask)

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

    def get_trigger_counter(self):
        return self.ext_counter
    
    def update_trigger_counter(self,counter):
        self.ext_counter = int(counter)
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
        um_per_pixel=1.5696,
        intensity_threshold=150,
        circularity_threshold=1.18,
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
    
    def calc_neg_diff_image(self, image, background):
        """
        Dark-only difference: where the current frame got darker vs the background.
        Returns (image_gray, dark_diff) with values in [0,255].
        """
        if image is None:
            print('Image is None')
            return None, None
        image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if background is None:
            print('Background image is None')
            # If no background, treat the whole image as "darkened" region inverted
            # (keeps downstream code running)
            dark = cv2.bitwise_not(image_gray)
            return image_gray, dark

        bg_gray = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)
        # Saturating subtraction: negative values get clamped to 0
        # => only pixels that got darker are nonzero
        dark = cv2.subtract(bg_gray, image_gray)
        return image_gray, dark

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
    
    def calc_emergence_area(self, background, image,
                            roi_top_frac=0.06, roi_bottom_frac=0.55,
                            roi_x_center_frac=0.50, roi_x_half_frac=0.18,
                            min_fg_pix=60, min_contour_area=40,
                            min_peak_delta=18):
        """
        Emergence detector tuned for droplets that appear darker than background.
        - Uses DARK-ONLY diff (background - image) to prefer black droplets.
        - Restricts to a TOP-CENTER ROI (configurable by fractions).
        - Returns (bbox_area:int|None, center:(x,y)|None, overlay_bgr).

        The ROI is:
        rows  : [roi_top_frac*h, roi_bottom_frac*h]
        cols  : [x_mid - roi_x_half_frac*w, x_mid + roi_x_half_frac*w]
        """

        if background is None or image is None:
            return None, None, image

        img_gray, dark = self.calc_neg_diff_image(image, background)
        if dark is None:
            return None, None, image

        h, w = dark.shape[:2]
        y0 = int(max(0, min(h-1, round(roi_top_frac    * h))))
        y1 = int(max(0, min(h,   round(roi_bottom_frac * h))))
        x_mid = int(round(roi_x_center_frac * w))
        x_half = int(round(roi_x_half_frac * w))
        x0 = max(0, x_mid - x_half)
        x1 = min(w, x_mid + x_half)
        if y1 <= y0 or x1 <= x0:
            return None, None, image

        roi = dark[y0:y1, x0:x1].copy()
        # Slight denoise
        blur = cv2.GaussianBlur(roi, (5,5), 0)

        # Adaptive threshold: try mean+2.5σ first, fallback to Otsu if too strict
        mu, sd = float(np.mean(blur)), float(np.std(blur))
        t_hard = max(10, int(mu + 2.5*sd))
        _, th = cv2.threshold(blur, t_hard, 255, cv2.THRESH_BINARY)
        if np.count_nonzero(th) < min_fg_pix:
            _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Clean up
        k = self._k3
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN,  k, iterations=1)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k, iterations=1)

        if np.count_nonzero(th) < min_fg_pix:
            overlay = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            # draw ROI for visual debugging
            cv2.rectangle(overlay, (x0, y0), (x1, y1), (128, 128, 255), 1)
            cv2.putText(overlay, "No FG in ROI", (x0+5, y0+18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128,128,255), 1)
            return None, None, overlay

        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            overlay = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            cv2.rectangle(overlay, (x0, y0), (x1, y1), (128, 128, 255), 1)
            return None, None, overlay

        # Rank by bottom-most y (in full image) then by larger area – favors the droplet lip at top
        def full_bottom_y(c):
            yy = c[:,:,1].max()
            return int(yy) + y0
        keep = [(c, cv2.contourArea(c)) for c in contours if cv2.contourArea(c) >= min_contour_area]
        if not keep:
            overlay = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            cv2.rectangle(overlay, (x0, y0), (x1, y1), (128, 128, 255), 1)
            return None, None, overlay

        keep.sort(key=lambda ca: (-full_bottom_y(ca[0]), -ca[1]))
        chosen, _ = keep[0]

        # Map ROI → full image coords
        rx, ry, rw, rh = cv2.boundingRect(chosen)
        x, y, ww, hh = rx + x0, ry + y0, rw, rh

        # Sanity: require some “signal” within bbox
        patch = dark[y:y+hh, x:x+ww]
        if patch.size == 0:
            overlay = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            return None, None, overlay
        p95 = float(np.percentile(patch, 95))
        if p95 < min_peak_delta:
            overlay = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            cv2.rectangle(overlay, (x0, y0), (x1, y1), (128, 128, 255), 1)
            cv2.putText(overlay, f"weak p95:{int(p95)}", (x0+5, y0+18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80,160,255), 1)
            return None, None, overlay

        overlay = image.copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        cv2.rectangle(overlay, (x0, y0), (x1, y1), (128, 128, 255), 1)              # ROI box
        cv2.drawContours(overlay, [chosen + np.array([[[x0, y0]]], dtype=chosen.dtype)], -1, (0, 255, 0), 2)
        cv2.rectangle(overlay, (x, y), (x+ww, y+hh), (255, 0, 0), 2)
        cv2.putText(overlay, f'Area:{ww*hh}', (x+ww+6, y+12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (50,200,50), 2)

        center = (x + ww//2, y + hh//2)
        return int(ww*hh), center, overlay

    def identify_droplets(self, image, background, nozzle_center, min_area=1000,
                          margin_up_px: int=8,satellite_band_px: int=12, min_free_offset_px: int=18):
        """
        Robust droplet identification:
          - works on diff = |image - background|
          - restricts to ROI below the nozzle row (+margin)
          - morphology to clean noise
          - classifies "nozzle-attached" area (area below nozzle within any bbox that contains the nozzle center)
          - counts free droplets entirely below the nozzle
        Returns: 
          droplets: list[(cx, cy)] or None
          nozzle_attached_area: int or None   # includes band satellites + area below nozzle within nozzle bbox
          overlay_bgr: np.ndarray
        """

        img_gray, diff = self.calc_diff_image(image, background)
        if diff is None or nozzle_center is None:
            return None, None, image

        h, w = diff.shape[:2]
        nzx, nzy = int(nozzle_center[0]), int(nozzle_center[1])
        nzy = max(0, min(h - 1, nzy))

        # ---------- ROI (crop) ----------
        # We process only rows from (nzy - margin_up) down to bottom.
        roi_top = max(0, nzy - int(margin_up_px))
        roi = diff[roi_top:, :]  # H_roi x W

        # ---------- threshold on ROI ----------
        # Small Gaussian -> Otsu on ROI (fast); fall back to a "mu+3*sd" if ROI is too empty
        blur = cv2.GaussianBlur(roi, (5, 5), 0)
        # mask is full in ROI; if needed we can add a col-mask but not necessary for speed
        _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if cv2.countNonZero(th) < 60:
            mu, sd = float(blur.mean()), float(blur.std())
            t = max(20, int(mu + 3.0 * sd))
            _, th = cv2.threshold(blur, t, 255, cv2.THRESH_BINARY)

        # morphology (very light)
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN,  self._k3, iterations=1)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, self._k3, iterations=1)
        if cv2.countNonZero(th) < 60:
            overlay = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            return None, None, overlay

        # ---------- components (faster than findContours) ----------
        # labels: 0 is background; stats: [x, y, w, h, area] in ROI coords
        nlab, labels, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
        overlay = image.copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        # Draw nozzle row reference
        cv2.line(overlay, (0, nzy), (w - 1, nzy), (128, 128, 255), 1)
        cv2.circle(overlay, (nzx, nzy), 5, (255, 0, 0), -1)

        droplets = []
        nozzle_attached_area = 0

        # Define bands in *full-image* coordinates
        band_top = max(0, nzy - int(satellite_band_px))
        band_bot = min(h - 1, nzy + int(satellite_band_px))
        free_min_y = min(h - 1, band_bot + int(min_free_offset_px))

        for lab in range(1, nlab):
            x, y, ww, hh, area = stats[lab]
            if area < max(40, int(min_area * 0.05)):
                continue

            # Convert ROI coords -> full-image coords
            y0 = y + roi_top
            x0 = x
            x1 = x0 + ww
            y1 = y0 + hh

            # Ignore blobs entirely above nozzle row (should be unlikely due to ROI, but keep guard)
            if y1 <= nzy:
                continue

            # Does bbox contain nozzle center?
            bbox_contains_nozzle = (x0 <= nzx <= x1) and (y0 <= nzy <= y1)

            # If bbox contains the nozzle OR overlaps the horizontal "satellite" band → treat as attached
            overlaps_band = not (y1 < band_top or y0 > band_bot)
            if bbox_contains_nozzle or overlaps_band:
                # Accumulate "attached" area as an *approximation* of the portion below the nozzle
                # Fast approximation: area below nozzle row within bbox footprint
                below_h = max(0, y1 - max(y0, nzy))
                if below_h > 0:
                    nozzle_attached_area += int(below_h * ww)
                cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 200, 255), 2)  # amber: attached
                continue

            # Else: candidate free droplet (must be sufficiently below the band and large enough)
            if (y0 >= free_min_y) and (area >= int(min_area)):
                cx = x0 + ww // 2
                cy = y0 + hh // 2
                droplets.append((cx, cy))
                cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 0, 255), 2)
                cv2.circle(overlay, (cx, cy), 6, (0, 0, 255), -1)

        if droplets:
            cv2.putText(overlay, f"Droplets: {len(droplets)}", (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0), 2)

        return (droplets if droplets else None,
                (int(nozzle_attached_area) if nozzle_attached_area > 0 else None),
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
            return None, image
        
        large_contours = [contour for contour in contours if cv2.contourArea(contour) > 1000 and cv2.contourArea(contour) < 100000]
        
        # Remove contours that have a very high width to height ratio
        
        large_contours = [contour for contour in large_contours if cv2.boundingRect(contour)[2] / cv2.boundingRect(contour)[3] < 3]


        if len(large_contours) == 0:
            print('No large contours detected')
            # Draw all contours and write their areas on the image
            annotated_image = image.copy()
            cv2.drawContours(annotated_image, contours, -1, (0, 255, 0), 2)
            for i, contour in enumerate(contours):
                area = cv2.contourArea(contour)
                x, y, w, h = cv2.boundingRect(contour)
                cv2.putText(annotated_image, f'{area:.0f}', (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            return None, annotated_image

        # Find the largest contour
        # largest_contour = max(large_contours, key=cv2.contourArea)
        largest_contour = max(large_contours, key=cv2.contourArea)

        # Draw the contour
        annotated_image = image.copy()
        cv2.drawContours(annotated_image, [largest_contour], -1, (0, 255, 0), 2)

        return largest_contour, annotated_image

    def characterize_droplet(self, image, background,um_per_pixel=1.5696):
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
        large_contours = [contour for contour in contours if cv2.contourArea(contour) > 1000 and cv2.contourArea(contour) < 100000]
        large_contours = [contour for contour in large_contours if cv2.boundingRect(contour)[2] / cv2.boundingRect(contour)[3] < 3]

        if len(large_contours) > 1:
            print('Multiple large contours detected')
            cv2.drawContours(image, large_contours, -1, (0, 255, 0), 2)
            # Add text in the middle of the screen saying multiple large contours detected
            cv2.putText(image, 'Multiple large contours detected', (image.shape[1]//2, image.shape[0]//2), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            return "Multiple", image
        
        if len(large_contours) == 0:
            print('No large contours detected')
            # Draw all contours and write their areas on the image
            annotated_image = image.copy()
            cv2.drawContours(annotated_image, contours, -1, (0, 255, 0), 2)
            for i, contour in enumerate(contours):
                area = cv2.contourArea(contour)
                x, y, w, h = cv2.boundingRect(contour)
                cv2.putText(annotated_image, f'{area:.0f}', (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            return None, annotated_image

        # Find the largest contour
        largest_contour = max(large_contours, key=cv2.contourArea)

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
        