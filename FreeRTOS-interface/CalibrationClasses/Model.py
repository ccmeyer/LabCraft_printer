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
from datetime import datetime, timezone
import glob
import shutil
import csv
import math
import matplotlib.pyplot as plt
from enum import Enum
from collections import deque
import queue

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


class NozzlePositionChecklistStore:
    """
    Manifest-backed image/metadata recorder for NozzlePositionCalibrationProcess.
    Saves captures under:
      FreeRTOS-interface/CalibrationClasses/test_images/NozzlePositionCalibrationProcess/
    """

    PROCESS_NAME = "NozzlePositionCalibrationProcess"

    def __init__(
        self,
        model,
        *,
        process_name: str | None = None,
        base_dir: str | None = None,
        manifest_path: str | None = None,
    ):
        self.model = model
        self.process_name = process_name or self.PROCESS_NAME
        self.base_dir = os.path.abspath(
            base_dir
            or os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_images", self.process_name)
        )
        self.manifest_path = os.path.abspath(
            manifest_path or os.path.join(self.base_dir, "checklist_manifest.v1.json")
        )

        self.manifest = None
        self.rows = []
        self._row_map = {}

        self.session_id = None
        self.session_dir = None
        self.images_dir = None
        self.records_path = None
        self.session_meta_path = None

        self._capture_records = []
        self._capture_by_id = {}
        self._rejected_ids = set()
        self._last_capture_record_id = None

        os.makedirs(self.base_dir, exist_ok=True)
        self.load_manifest()

    @staticmethod
    def validate_manifest(manifest: dict):
        if not isinstance(manifest, dict):
            raise ValueError("Checklist manifest must be a JSON object.")
        if int(manifest.get("schema_version", -1)) != 1:
            raise ValueError("Checklist manifest schema_version must be 1.")
        if str(manifest.get("process_name", "")).strip() == "":
            raise ValueError("Checklist manifest missing process_name.")

        cases = manifest.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ValueError("Checklist manifest must define non-empty 'cases'.")

        seen_case_ids = set()
        for case in cases:
            case_id = str(case.get("case_id", "")).strip()
            if not case_id:
                raise ValueError("Checklist case missing case_id.")
            if case_id in seen_case_ids:
                raise ValueError(f"Duplicate checklist case_id: {case_id}")
            seen_case_ids.add(case_id)

            steps = case.get("steps")
            if not isinstance(steps, list) or not steps:
                raise ValueError(f"Checklist case '{case_id}' must define non-empty steps.")

            seen_step_ids = set()
            for step in steps:
                step_id = str(step.get("step_id", "")).strip()
                if not step_id:
                    raise ValueError(f"Checklist case '{case_id}' has step with missing step_id.")
                if step_id in seen_step_ids:
                    raise ValueError(f"Checklist case '{case_id}' has duplicate step_id '{step_id}'.")
                seen_step_ids.add(step_id)

                req = step.get("required", {})
                if not isinstance(req, dict):
                    raise ValueError(f"Checklist case '{case_id}' step '{step_id}' required must be an object.")
                for role in ("background", "droplet"):
                    v = req.get(role, None)
                    if v is None:
                        continue
                    if int(v) < 0:
                        raise ValueError(
                            f"Checklist case '{case_id}' step '{step_id}' has invalid required count for {role}."
                        )

    def load_manifest(self):
        if not os.path.exists(self.manifest_path):
            raise FileNotFoundError(f"Checklist manifest not found: {self.manifest_path}")
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.validate_manifest(data)

        self.manifest = data
        self.rows = self._flatten_rows(data)
        self._row_map = {r["row_key"]: r for r in self.rows}
        return self.manifest

    def _flatten_rows(self, manifest: dict):
        defaults = manifest.get("defaults", {}) or {}
        bg_default = max(0, int(defaults.get("background_replicates_min", 1)))
        dr_default = max(0, int(defaults.get("droplet_replicates_min", 3)))

        rows = []
        for case in manifest.get("cases", []):
            case_id = str(case.get("case_id", "")).strip()
            case_label = str(case.get("label", case_id)).strip() or case_id
            case_tip = str(case.get("tooltip", "")).strip()
            steps = case.get("steps", []) or []

            for idx, step in enumerate(steps):
                step_id = str(step.get("step_id", "")).strip() or f"step_{idx+1}"
                step_label = str(step.get("label", step_id)).strip() or step_id
                step_tip = str(step.get("tooltip", "")).strip()
                req = step.get("required", {}) or {}
                bg_req = max(0, int(req.get("background", bg_default)))
                dr_req = max(0, int(req.get("droplet", dr_default)))
                expected_status = str(step.get("expected_status", case.get("expected_status", ""))).strip()
                expected_decision = str(step.get("expected_decision", case.get("expected_decision", ""))).strip()

                row_key = f"{case_id}:{step_id}"
                rows.append(
                    {
                        "row_key": row_key,
                        "case_id": case_id,
                        "case_label": case_label,
                        "case_tooltip": case_tip,
                        "step_id": step_id,
                        "step_label": step_label,
                        "step_tooltip": step_tip,
                        "required_background": bg_req,
                        "required_droplet": dr_req,
                        "expected_status": expected_status,
                        "expected_decision": expected_decision,
                        "tooltip": step_tip or case_tip or step_label,
                    }
                )
        return rows

    def begin_session(self, *, session_id: str | None = None):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = session_id or f"session_{ts}"
        self.session_dir = os.path.join(self.base_dir, self.session_id)
        self.images_dir = os.path.join(self.session_dir, "images")
        self.records_path = os.path.join(self.session_dir, "records.jsonl")
        self.session_meta_path = os.path.join(self.session_dir, "session_meta.json")

        os.makedirs(self.images_dir, exist_ok=True)

        self._capture_records = []
        self._capture_by_id = {}
        self._rejected_ids = set()
        self._last_capture_record_id = None

        meta = {
            "schema_version": 1,
            "process_name": self.process_name,
            "manifest_path": os.path.relpath(self.manifest_path, self.session_dir).replace("\\", "/"),
            "manifest_schema_version": int((self.manifest or {}).get("schema_version", 1)),
            "session_id": self.session_id,
            "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        with open(self.session_meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return self.session_dir

    def ensure_session(self):
        if self.session_dir is None:
            self.begin_session()

    def get_rows(self):
        return list(self.rows)

    def get_row(self, row_key: str):
        return self._row_map.get(str(row_key))

    def resolve_reagent_name(self) -> str:
        try:
            ph = self.model.rack_model.get_gripper_printer_head()
            if ph is None:
                return "unknown"
            stock = ph.get_stock_solution()
            name = getattr(stock, "reagent_name", None)
            if name:
                return str(name)
            return str(stock) if stock is not None else "unknown"
        except Exception:
            return "unknown"

    def _append_record(self, payload: dict):
        self.ensure_session()
        with open(self.records_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=numpy_encoder) + "\n")

    def _prepare_image_for_write(self, image):
        arr = np.asarray(image)
        if arr.ndim == 2:
            return arr
        if arr.ndim == 3 and arr.shape[2] == 3:
            # UI frames are RGB; OpenCV writer expects BGR.
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        if arr.ndim == 3 and arr.shape[2] == 4:
            return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGRA)
        raise ValueError(f"Unsupported image shape for write: {arr.shape}")

    def _accepted_count(self, row_key: str, role: str) -> int:
        count = 0
        for rec in self._capture_records:
            if rec.get("row_key") != row_key:
                continue
            if rec.get("capture_role") != role:
                continue
            rid = rec.get("record_id")
            if rid in self._rejected_ids:
                continue
            count += 1
        return count

    def capture_for_row(
        self,
        row_key: str,
        capture_role: str,
        image,
        *,
        selected_label: str,
        machine_state: dict | None = None,
        camera_settings: dict | None = None,
        reagent_name: str | None = None,
        fsm_hint: str | None = None,
        operator_note: str | None = None,
        pair_id: str | None = None,
        pair_role: str | None = None,
        pair_order: int | None = None,
        pair_capture_mode: str | None = None,
        subtract_background_record_id: str | None = None,
        subtract_background_image_relpath: str | None = None,
    ):
        self.ensure_session()
        role = str(capture_role).lower().strip()
        if role not in ("background", "droplet"):
            raise ValueError(f"Unsupported capture role: {capture_role}")
        row = self.get_row(row_key)
        if row is None:
            raise KeyError(f"Unknown checklist row key: {row_key}")

        idx = self._accepted_count(row_key, role) + 1
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
        filename = f"{stamp}_{role}_{idx:03d}.jpg"
        relpath = os.path.join("images", row["case_id"], row["step_id"], role, filename)
        relpath = relpath.replace("\\", "/")
        abspath = os.path.join(self.session_dir, *relpath.split("/"))
        os.makedirs(os.path.dirname(abspath), exist_ok=True)

        out = self._prepare_image_for_write(image)
        ok = cv2.imwrite(abspath, out)
        if not ok:
            raise IOError(f"Failed to write capture image: {abspath}")

        record_id = str(uuid.uuid4())
        payload = {
            "type": "capture",
            "record_id": record_id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "session_id": self.session_id,
            "process_name": self.process_name,
            "row_key": row["row_key"],
            "case_id": row["case_id"],
            "case_label": row["case_label"],
            "step_id": row["step_id"],
            "step_label": row["step_label"],
            "selected_label": str(selected_label),
            "capture_role": role,
            "image_relpath": relpath,
            "required_background": int(row["required_background"]),
            "required_droplet": int(row["required_droplet"]),
            "expected_status": row.get("expected_status"),
            "expected_decision": row.get("expected_decision"),
            "machine_state": machine_state or {},
            "camera_settings": camera_settings or {},
            "reagent_name": str(reagent_name or "unknown"),
            "fsm_hint": str(fsm_hint or ""),
            "operator_note": str(operator_note or ""),
            # Pair metadata enables deterministic background subtraction matching during analysis.
            "pair_id": str(pair_id or ""),
            "pair_role": str(pair_role or ""),
            "pair_order": int(pair_order) if pair_order is not None else None,
            "pair_capture_mode": str(pair_capture_mode or ""),
            "subtract_background_record_id": str(subtract_background_record_id or ""),
            "subtract_background_image_relpath": str(subtract_background_image_relpath or ""),
            "rejected": False,
        }
        self._append_record(payload)
        self._capture_records.append(payload)
        self._capture_by_id[record_id] = payload
        self._last_capture_record_id = record_id
        return payload

    def reject_last_capture(self, *, reason: str = ""):
        self.ensure_session()
        rid = self._last_capture_record_id
        if not rid:
            return None
        if rid in self._rejected_ids:
            return None

        self._rejected_ids.add(rid)
        if rid in self._capture_by_id:
            self._capture_by_id[rid]["rejected"] = True
            self._capture_by_id[rid]["rejected_at"] = (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            )

        evt = {
            "type": "reject",
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "session_id": self.session_id,
            "target_record_id": rid,
            "reason": str(reason or ""),
        }
        self._append_record(evt)
        return evt

    def get_row_status(self, row_key: str):
        row = self.get_row(row_key)
        if row is None:
            raise KeyError(f"Unknown checklist row key: {row_key}")
        bg = self._accepted_count(row_key, "background")
        dr = self._accepted_count(row_key, "droplet")
        complete = (bg >= int(row["required_background"])) and (dr >= int(row["required_droplet"]))
        return {
            "row_key": row_key,
            "accepted_background": bg,
            "accepted_droplet": dr,
            "required_background": int(row["required_background"]),
            "required_droplet": int(row["required_droplet"]),
            "complete": bool(complete),
        }

    def get_all_status(self):
        out = {}
        for row in self.rows:
            out[row["row_key"]] = self.get_row_status(row["row_key"])
        return out

    def is_complete(self) -> bool:
        statuses = self.get_all_status()
        return all(s.get("complete", False) for s in statuses.values())


class CalibrationProcessRecorder:
    """
    Per-process recorder for calibration runs.
    Stores raw captures, structured events, analysis payloads, and operator verdict.
    """

    SCHEMA_VERSION = 1

    def __init__(self, model):
        self.model = model
        self._lock = threading.Lock()
        self._active = None
        self._last = None

    @staticmethod
    def _now_utc() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _write_json_atomic(path: str, payload: dict):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=numpy_encoder)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    @staticmethod
    def _append_jsonl(path: str, payload: dict):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=numpy_encoder) + "\n")

    @staticmethod
    def _prepare_image_for_write(image):
        arr = np.asarray(image)
        if arr.ndim == 2:
            return arr
        if arr.ndim == 3 and arr.shape[2] == 3:
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        if arr.ndim == 3 and arr.shape[2] == 4:
            return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGRA)
        raise ValueError(f"Unsupported image shape for write: {arr.shape}")

    def _default_root_dir(self) -> str:
        exp = getattr(self.model, "experiment_model", None)
        exp_dir = getattr(exp, "experiment_dir_path", None)
        if exp_dir:
            return os.path.abspath(os.path.join(exp_dir, "calibration_recordings"))
        cal_path = getattr(exp, "calibration_file_path", None)
        if cal_path:
            return os.path.abspath(os.path.join(os.path.dirname(cal_path), "calibration_recordings"))
        return os.path.abspath(os.path.join(os.getcwd(), "calibration_recordings"))

    def _active_or_last(self):
        return self._active or self._last

    def get_active_run_dir(self) -> str | None:
        with self._lock:
            if not self._active:
                return None
            return self._active["run_dir"]

    def get_last_run_dir(self) -> str | None:
        with self._lock:
            if not self._last:
                return None
            return self._last["run_dir"]

    def start_run(self, process_name: str, phase_name: str, *, extra_meta: dict | None = None):
        with self._lock:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_id = f"run_{ts}_{uuid.uuid4().hex[:8]}"
            root = self._default_root_dir()
            run_dir = os.path.join(root, str(process_name), run_id)
            captures_dir = os.path.join(run_dir, "captures")
            os.makedirs(captures_dir, exist_ok=True)

            run = {
                "run_id": run_id,
                "process_name": str(process_name),
                "phase_name": str(phase_name),
                "run_dir": run_dir,
                "captures_dir": captures_dir,
                "events_path": os.path.join(run_dir, "events.jsonl"),
                "analysis_path": os.path.join(run_dir, "analysis.jsonl"),
                "meta_path": os.path.join(run_dir, "run_meta.json"),
                "verdict_path": os.path.join(run_dir, "verdict.json"),
                "capture_index": 0,
                "event_index": 0,
            }

            meta = {
                "schema_version": int(self.SCHEMA_VERSION),
                "run_id": run_id,
                "process_name": str(process_name),
                "phase_name": str(phase_name),
                "started_at_utc": self._now_utc(),
                "ended_at_utc": None,
                "outcome": "running",
                "error_message": "",
            }
            if isinstance(extra_meta, dict):
                meta.update(extra_meta)

            verdict = {
                "schema_version": int(self.SCHEMA_VERSION),
                "run_id": run_id,
                "process_name": str(process_name),
                "phase_name": str(phase_name),
                "outcome": "unknown",
                "failure_summary": "",
                "suspected_cause": "",
                "notes": "",
                "submitted_by": "system",
                "submitted_at_utc": self._now_utc(),
            }

            self._write_json_atomic(run["meta_path"], meta)
            self._write_json_atomic(run["verdict_path"], verdict)

            self._active = run
            self._last = dict(run)
            return run_dir

    def append_event(
        self,
        event_type: str,
        payload: dict | None = None,
        *,
        state_name: str | None = None,
        level: str = "info",
    ) -> dict | None:
        with self._lock:
            if not self._active:
                return None
            self._active["event_index"] += 1
            evt = {
                "schema_version": int(self.SCHEMA_VERSION),
                "event_id": str(uuid.uuid4()),
                "event_index": int(self._active["event_index"]),
                "ts_utc": self._now_utc(),
                "run_id": self._active["run_id"],
                "process_name": self._active["process_name"],
                "phase_name": self._active["phase_name"],
                "event_type": str(event_type),
                "state_name": str(state_name or ""),
                "level": str(level),
                "payload": payload or {},
            }
            self._append_jsonl(self._active["events_path"], evt)
            return evt

    def append_analysis(self, record: dict) -> dict | None:
        with self._lock:
            if not self._active:
                return None
            payload = dict(record or {})
            payload.setdefault("schema_version", int(self.SCHEMA_VERSION))
            payload.setdefault("analysis_id", str(uuid.uuid4()))
            payload.setdefault("ts_utc", self._now_utc())
            payload.setdefault("run_id", self._active["run_id"])
            payload.setdefault("process_name", self._active["process_name"])
            payload.setdefault("phase_name", self._active["phase_name"])
            self._append_jsonl(self._active["analysis_path"], payload)
            return payload

    def save_capture_image(
        self,
        image,
        *,
        role: str = "capture",
        file_ext: str = "jpg",
        metadata: dict | None = None,
    ) -> dict | None:
        with self._lock:
            if not self._active:
                return None
            self._active["capture_index"] += 1
            idx = int(self._active["capture_index"])
            capture_id = f"cap_{idx:06d}"
            ext = str(file_ext or "jpg").lstrip(".").lower()
            filename = f"{capture_id}_{str(role)}.{ext}"
            abspath = os.path.join(self._active["captures_dir"], filename)
            relpath = os.path.join("captures", filename).replace("\\", "/")

            out = self._prepare_image_for_write(image)
            ok = cv2.imwrite(abspath, out)
            if not ok:
                raise IOError(f"Failed to write capture image: {abspath}")

            h = int(out.shape[0]) if hasattr(out, "shape") and len(out.shape) >= 2 else None
            w = int(out.shape[1]) if hasattr(out, "shape") and len(out.shape) >= 2 else None
            info = {
                "capture_id": capture_id,
                "capture_index": idx,
                "capture_role": str(role),
                "image_relpath": relpath,
                "width": w,
                "height": h,
                "captured_at_utc": self._now_utc(),
            }
            if isinstance(metadata, dict):
                info.update(metadata)
            return info

    def finalize_run(self, outcome: str, *, error_message: str = ""):
        with self._lock:
            if not self._active:
                return
            run = self._active
            meta_path = run["meta_path"]
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {
                    "schema_version": int(self.SCHEMA_VERSION),
                    "run_id": run["run_id"],
                    "process_name": run["process_name"],
                    "phase_name": run["phase_name"],
                    "started_at_utc": "",
                }
            meta["ended_at_utc"] = self._now_utc()
            meta["outcome"] = str(outcome)
            meta["error_message"] = str(error_message or "")
            self._write_json_atomic(meta_path, meta)
            self._last = dict(run)
            self._active = None

    def write_verdict(
        self,
        outcome: str,
        *,
        failure_summary: str = "",
        suspected_cause: str = "",
        notes: str = "",
        submitted_by: str = "ui",
    ):
        with self._lock:
            run = self._active_or_last()
            if not run:
                return None
            verdict = {
                "schema_version": int(self.SCHEMA_VERSION),
                "run_id": run["run_id"],
                "process_name": run["process_name"],
                "phase_name": run["phase_name"],
                "outcome": str(outcome or "unknown"),
                "failure_summary": str(failure_summary or ""),
                "suspected_cause": str(suspected_cause or ""),
                "notes": str(notes or ""),
                "submitted_by": str(submitted_by or "ui"),
                "submitted_at_utc": self._now_utc(),
            }
            self._write_json_atomic(run["verdict_path"], verdict)
            return verdict


class CalibrationManager(QObject):
    calibrationStageChanged = Signal(str, str)  # (message, color_name)
    calibrationCompleted = Signal()
    calibrationError = Signal(str)
    calibrationQueueCompleted = Signal()
    characterizationSummaryUpdated = Signal()  # Notify UI to rebuild the summary table

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
        "head_prime": "head_prime",
        "pressure": "pressure_calibration",
        "pressure_calibration": "pressure_calibration",
        "pressure_scan": "pressure_scan",
        "nozzle": "nozzle_position",
        "nozzle_position": "nozzle_position",
        "nozzle_focus": "nozzle_focus",
        "droplet_emergence": "droplet_emergence",
        "trajectory": "trajectory",
        "trajectory_calibration": "trajectory",
        "droplet_trajectory": "trajectory",
        "droplet_search": "droplet_search",
    }

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.activeCalibration = None
        self.model = model

        # Recorder mode: captures per-process runtime telemetry for offline replay/debug.
        self.record_mode_enabled = True
        self._process_recorder = CalibrationProcessRecorder(model)

        # Persisted JSON
        self._lock = threading.Lock()
        self.data = {"schema_version": 1, "runs": []}
        self.calibration_file_path = None

        # Current run envelope
        self._run_id = None
        self._run_idx = None

        # --- Pulse-Width Sweep State ---
        self._pw_sweep_active = False
        self._pw_values = []     # list[int] pulse widths in us
        self._pw_index  = -1     # current index in _pw_values

        # --- Async apply-PW wait plumbing ---
        self._pw_apply_timer = None         # QTimer guard
        self._pw_apply_slot = None          # one-off slot connected to settingsChangeCompleted
        self._pw_apply_token = None         # uniqueness token to ignore stale callbacks

        # Cross-step tunable parameters
        self.start_pressure = 0.8
        self.num_pressure_tests = 4

        # Cross-step ephemeral cache (images, etc.)
        self.background_image = None
        self.nozzle_center = None
        self.nozzle_center_image_position = None
        self.emergence_nozzle_center_image_position = None
        self.droplet_trajectory_vector = None
        self.trajectory_delay = None
        self.min_start_delay = None
        self.intermediate_droplet_position = None

        self._last_pressure_scan_result = None
        self._pressure_traj_result = None

        self.calibration_queue = []

        self.model.machine_state_updated.connect(self.update_offsets_from_nozzle)
        self.calibrationQueueCompleted.connect(self._on_queue_completed_for_pw_sweep)

    # ------------- Per-process recorder -------------

    def _build_recorder_meta(self):
        meta = {
            "stock_solution": self._safe_get_stock_solution(),
            "printer_head_id": self._safe_get_printer_head_id(),
            "calibration_file_path": str(self.calibration_file_path or ""),
        }
        try:
            exp_dir = getattr(self.model.experiment_model, "experiment_dir_path", None)
            meta["experiment_dir"] = str(exp_dir or "")
        except Exception:
            meta["experiment_dir"] = ""
        try:
            meta["settings_snapshot"] = self.get_current_settings()
        except Exception:
            meta["settings_snapshot"] = {}
        return meta

    def _begin_process_recording(self, process_obj):
        if not getattr(self, "record_mode_enabled", False):
            return
        recorder = getattr(self, "_process_recorder", None)
        if recorder is None:
            return
        if process_obj is None:
            return
        try:
            process_name = process_obj.__class__.__name__
            phase_name = getattr(process_obj, "phase_name", None) or process_name
            run_dir = recorder.start_run(
                process_name,
                phase_name,
                extra_meta=self._build_recorder_meta(),
            )
            recorder.append_event(
                "process_started",
                {
                    "process_name": process_name,
                    "phase_name": phase_name,
                    "queue_depth": int(len(self.calibration_queue)),
                    "run_dir": run_dir,
                },
            )
        except Exception as e:
            print(f"[CalibrationRecorder] Failed to start process recording: {e}")

    def _finalize_process_recording(self, outcome: str, *, error_message: str = ""):
        recorder = getattr(self, "_process_recorder", None)
        if recorder is None:
            return
        # Finalize any active run even if record mode was toggled off mid-process.
        active_dir = None
        try:
            active_dir = recorder.get_active_run_dir()
        except Exception:
            active_dir = None
        if (not getattr(self, "record_mode_enabled", False)) and (not active_dir):
            return
        try:
            if getattr(self, "record_mode_enabled", False):
                recorder.append_event(
                    "process_finished",
                    {"outcome": str(outcome), "error_message": str(error_message or "")},
                )
            recorder.finalize_run(str(outcome), error_message=str(error_message or ""))
            if str(outcome) == "error":
                recorder.write_verdict(
                    "failed",
                    failure_summary=str(error_message or ""),
                    submitted_by="system",
                )
            elif str(outcome) == "completed":
                recorder.write_verdict("unknown", submitted_by="system")
        except Exception as e:
            print(f"[CalibrationRecorder] Failed to finalize process recording: {e}")

    def record_process_event(
        self,
        event_type: str,
        payload: dict | None = None,
        *,
        state_name: str | None = None,
        level: str = "info",
    ):
        if not getattr(self, "record_mode_enabled", False):
            return None
        recorder = getattr(self, "_process_recorder", None)
        if recorder is None:
            return None
        try:
            return recorder.append_event(
                str(event_type),
                payload or {},
                state_name=state_name,
                level=level,
            )
        except Exception as e:
            print(f"[CalibrationRecorder] Failed to append event '{event_type}': {e}")
            return None

    def record_analysis(self, record: dict):
        if not getattr(self, "record_mode_enabled", False):
            return None
        recorder = getattr(self, "_process_recorder", None)
        if recorder is None:
            return None
        try:
            return recorder.append_analysis(record or {})
        except Exception as e:
            print(f"[CalibrationRecorder] Failed to append analysis: {e}")
            return None

    def record_capture_frame(self, image, *, role: str = "capture", metadata: dict | None = None):
        if not getattr(self, "record_mode_enabled", False):
            return None
        recorder = getattr(self, "_process_recorder", None)
        if recorder is None:
            return None
        if image is None:
            return None
        try:
            rec = recorder.save_capture_image(
                image,
                role=str(role),
                metadata=metadata or {},
            )
            if rec is not None:
                recorder.append_event(
                    "capture_saved",
                    {
                        "capture_id": rec.get("capture_id"),
                        "capture_role": rec.get("capture_role"),
                        "image_relpath": rec.get("image_relpath"),
                        "metadata": metadata or {},
                    },
                )
            return rec
        except Exception as e:
            print(f"[CalibrationRecorder] Failed to save capture image: {e}")
            return None

    def submit_latest_process_verdict(
        self,
        *,
        outcome: str,
        failure_summary: str = "",
        suspected_cause: str = "",
        notes: str = "",
        submitted_by: str = "ui",
    ):
        if not getattr(self, "record_mode_enabled", False):
            return None
        recorder = getattr(self, "_process_recorder", None)
        if recorder is None:
            return None
        try:
            verdict = recorder.write_verdict(
                str(outcome or "unknown"),
                failure_summary=str(failure_summary or ""),
                suspected_cause=str(suspected_cause or ""),
                notes=str(notes or ""),
                submitted_by=str(submitted_by or "ui"),
            )
            recorder.append_event(
                "verdict_submitted",
                verdict or {},
            )
            return verdict
        except Exception as e:
            print(f"[CalibrationRecorder] Failed to write verdict: {e}")
            return None

    def get_latest_recording_directory(self):
        try:
            recorder = getattr(self, "_process_recorder", None)
            if recorder is None:
                return None
            return recorder.get_last_run_dir()
        except Exception:
            return None

    def set_record_mode_enabled(self, enabled: bool):
        self.record_mode_enabled = bool(enabled)
        state = "enabled" if self.record_mode_enabled else "disabled"
        self.calibrationStageChanged.emit(f"Calibration recorder {state}.", "dark_blue")

    def get_record_mode_enabled(self) -> bool:
        return bool(getattr(self, "record_mode_enabled", False))

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
        # Per-run derived center used by pressure band; avoid stale cross-session carryover.
        self.emergence_nozzle_center_image_position = None
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
        self.characterizationSummaryUpdated.emit()
        self._emit_readiness()

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

    def ensure_loaded(self):
        """
        Lazily load calibration data from the configured path so callers like
        get_pressure_sweep_summary_rows() can work on first open.
        """
        if self.calibration_file_path is None:
            try:
                path = self.model.experiment_model.get_calibration_file_path()
            except Exception:
                path = None
            # Default sensibly if model didn't provide a path
            if not path:
                path = os.path.abspath("calibration.json")
            self.calibration_file_path = path

        # If file exists, load it into self.data once
        if os.path.exists(self.calibration_file_path) and not (self.data.get("runs")):
            try:
                with open(self.calibration_file_path, "r") as f:
                    self.data = json.load(f)
            except Exception:
                # keep empty structure on failure
                self.data = {"schema_version": 1, "runs": []}

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
        # self.add_calibration_to_queue('pressure')
        # self.add_calibration_to_queue('trajectory')
        # self.add_calibration_to_queue('droplet_search')
        self.add_calibration_to_queue('pressure_scan')
        self.add_calibration_to_queue('pressure_trajectory')
        self.add_calibration_to_queue('pressure_sweep_characterization')
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
            'head_prime': HeadPrimeCalibrationProcess,
            'nozzle_position': NozzlePositionCalibrationProcess,
            'nozzle_focus': NozzleFocusCalibrationProcess,
            'droplet_emergence': DropletEmergenceCalibrationProcess,
            'pressure': PressureCalibrationProcess,
            'pressure_scan': PressureBandCalibrationProcess,
            'trajectory': TrajectoryCalibrationProcess,
            'droplet_search': DropletSearchCalibrationProcess,
            'pressure_trajectory': PressureTrajectoryCalibrationProcess,
            'pressure_sweep_characterization': PressureSweepCharacterizationProcess,
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
            self._begin_process_recording(self.activeCalibration)
            self.activeCalibration.start()

    def stop(self):
        # --- Clear PW sweep state, if any ---
        self._pw_sweep_active = False
        self._pw_values = []
        self._pw_index = -1
        self._cancel_pw_apply_wait()

        if self.activeCalibration is not None:
            # Prefer graceful finalize if the process supports it
            if hasattr(self.activeCalibration, "requestGracefulStop"):
                try:
                    self.activeCalibration.requestGracefulStop("User requested graceful stop")
                    self._finalize_process_recording("stopped", error_message="Calibration terminated by user")
                    return
                except Exception:
                    pass
            self.activeCalibration.stop()
            self.activeCalibration = None
        if len(self.calibration_queue) > 0:
            self.clear_calibration_queue()
        self.calibrationStageChanged.emit("Calibration stopped","orange")
        self._finalize_process_recording("stopped", error_message="Calibration terminated by user")
        self.calibrationError.emit("Calibration terminated by user")

    # =================== Pulse-Width Sweep Orchestration ===================

    def is_pulsewidth_sweep_active(self) -> bool:
        return bool(self._pw_sweep_active)

    def stop_pulsewidth_sweep(self):
        """Abort any in-progress PW sweep and stop any running calibration."""
        if self._pw_sweep_active:
            self._pw_sweep_active = False
            self._pw_values = []
            self._pw_index = -1
            self.calibrationStageChanged.emit("Pulse-width sweep stopped by user", "orange")
        # Also stop any active calibration/queue
        self._cancel_pw_apply_wait()
        self.stop()

    def start_pulsewidth_sweep(self, pw_start_us: int, pw_end_us: int, pw_step_us: int):
        """
        Run 'Calibrate All' for each pulse width in [start, end] with given step (inclusive).
        Supports start > end (will step downward).
        """
        # Guard: active run or queue?
        if self.activeCalibration is not None or len(self.calibration_queue) > 0:
            self.calibrationStageChanged.emit(
                "Cannot start PW sweep while a calibration is running. Stop it first.", "red"
            )
            self.calibrationError.emit("Busy: active calibration")
            return

        # Validate
        try:
            s = int(pw_start_us); e = int(pw_end_us); st = int(pw_step_us)
        except Exception:
            self.calibrationStageChanged.emit("Invalid PW sweep values (must be integers).", "red")
            self.calibrationError.emit("Invalid PW sweep values")
            return
        if st == 0:
            self.calibrationStageChanged.emit("Pulse width step must be non-zero.", "red")
            self.calibrationError.emit("Invalid step")
            return

        # Build inclusive list with correct step sign
        if s <= e and st < 0:
            st = -st
        if s > e and st > 0:
            st = -st

        vals = []
        cur = s
        if st > 0:
            while cur <= e:
                vals.append(cur)
                cur += st
        else:
            while cur >= e:
                vals.append(cur)
                cur += st

        if not vals:
            self.calibrationStageChanged.emit("No pulse widths generated for sweep.", "red")
            self.calibrationError.emit("Empty PW set")
            return

        # Initialize state and kick off first PW
        self._pw_sweep_active = True
        self._pw_values = vals
        self._pw_index = -1
        self.calibrationStageChanged.emit(
            f"Starting pulse-width sweep: {vals[0]}→{vals[-1]} us (n={len(vals)}, step={abs(st)} us)", "dark_blue"
        )
        self._advance_pw_sweep()

    def _cancel_pw_apply_wait(self):
        """Cancel any in-flight 'apply PW and wait' guard + one-off slot."""
        # timer
        if self._pw_apply_timer is not None:
            try:
                self._pw_apply_timer.stop()
                self._pw_apply_timer.deleteLater()
            except Exception:
                pass
            finally:
                self._pw_apply_timer = None
        # temporary slot
        if self._pw_apply_slot is not None:
            try:
                self.settingsChangeCompleted.disconnect(self._pw_apply_slot)
            except Exception:
                pass
            finally:
                self._pw_apply_slot = None
        # token
        self._pw_apply_token = None


    def _apply_print_width_and_wait(self, pw_us: int, *, timeout_ms: int = 10000):
        """
        Asynchronously apply print pulse width using changeSettingsRequested and do not proceed
        until the controller confirms via either:
        - the provided callback, or
        - settingsChangeCompleted
        Also uses a guard timeout. On success, queues Calibrate All for this PW.
        On failure/timeout, aborts the PW sweep and raises a calibrationError.
        """
        # Clear any previous wait
        self._cancel_pw_apply_wait()

        # If sweep was cancelled mid-flight, do nothing
        if not self._pw_sweep_active:
            return

        self.calibrationStageChanged.emit(
            f"Applying print pulse width = {pw_us} us…", "dark_blue"
        )

        token = object()
        self._pw_apply_token = token

        fired = {"done": False}

        def _finish(ok: bool, why: str):
            # Single-fire; ignore stale or cancelled cases
            if fired["done"] or self._pw_apply_token is not token or not self._pw_sweep_active:
                return
            fired["done"] = True

            # cleanup guards
            self._cancel_pw_apply_wait()

            if not ok:
                self.calibrationStageChanged.emit(
                    f"Failed to apply PW {pw_us} us ({why}). Stopping sweep.", "red"
                )
                # Stop sweep + any activity
                self._pw_sweep_active = False
                self._pw_values = []
                self._pw_index = -1
                # propagate an error for UI feedback
                self.calibrationError.emit(f"Pulse-width apply failed: {why}")
                # ensure queues are cleared & active process stopped
                self.stop()
                return

            # Success → queue “Calibrate All” for this PW
            self.calibrationStageChanged.emit(
                f"PW applied: {pw_us} us. Running Calibrate All…", "blue"
            )
            self.clear_calibration_queue()
            self.add_all_calibrations_to_queue()

        # One-off slot for settingsChangeCompleted
        def _slot_settings_applied():
            _finish(True, "settingsChangeCompleted")

        self._pw_apply_slot = _slot_settings_applied
        self.settingsChangeCompleted.connect(self._pw_apply_slot)

        # Guard timeout
        self._pw_apply_timer = QTimer(self)
        self._pw_apply_timer.setSingleShot(True)
        self._pw_apply_timer.timeout.connect(lambda: _finish(False, "timeout"))
        self._pw_apply_timer.start(int(timeout_ms))

        # Controller will call this when settings application finishes
        def _cb(*args, **kwargs):
            _finish(True, "callback")

        # Emit the change request (controller consumes dict & callback)
        # NOTE: If your controller expects a different key name, adjust "print_width" here.
        self.changeSettingsRequested.emit({"print_pulse_width": int(pw_us)}, _cb)

    def _advance_pw_sweep(self):
        """Move to next PW in the sweep; apply PW (async) and then run Calibrate All."""
        if not self._pw_sweep_active:
            return

        self._pw_index += 1
        if self._pw_index >= len(self._pw_values):
            # Done
            self._pw_sweep_active = False
            self._pw_values = []
            self._pw_index = -1
            self.calibrationStageChanged.emit("Pulse-width sweep completed.", "green")
            self.calibrationQueueCompleted.emit()
            return

        pw = int(self._pw_values[self._pw_index])
        self.calibrationStageChanged.emit(
            f"PW sweep [{self._pw_index+1}/{len(self._pw_values)}]: target = {pw} us", "blue"
        )

        # Apply PW via controller (with callback) and only proceed on confirmation
        self._apply_print_width_and_wait(pw)

    @Slot()
    def _on_queue_completed_for_pw_sweep(self):
        """When a per-PW queue finishes, advance to the next PW if sweep is active."""
        if self._pw_sweep_active:
            self._advance_pw_sweep()

    # --- Methods to start individual calibration processes ---
    def start_head_prime_calibration(self):
        self._try_start_process(HeadPrimeCalibrationProcess)
    
    def start_nozzle_calibration(self):
        self.activeCalibration = NozzlePositionCalibrationProcess(self, self.model)
        self.start_active_calibration()

    def start_nozzle_focus_calibration(self):
        self._try_start_process(NozzleFocusCalibrationProcess)

    def start_droplet_emergence_calibration(self):
        self._try_start_process(DropletEmergenceCalibrationProcess)

    def start_pressure_calibration(self):
        self.activeCalibration = PressureCalibrationProcess(self, self.model)
        self.start_active_calibration()

    # def start_pressure_scan_calibration(self):
    #     self.activeCalibration = PressureBandCalibrationProcess(self, self.model)
    #     self.start_active_calibration()

    def start_pressure_scan_calibration(self, *, start_pressure: float | None = None):
        """
        Start the pressure-band scan with optional user-defined range and step.
        """
        kwargs = {}
        if start_pressure is not None:
            kwargs["start_pressure"] = float(start_pressure)
        self._try_start_process(PressureBandCalibrationProcess, **kwargs)

    def start_trajectory_calibration(self):
        self._try_start_process(TrajectoryCalibrationProcess)

    def start_pressure_trajectory_calibration(self):
        self._try_start_process(PressureTrajectoryCalibrationProcess)

    def start_droplet_search_calibration(self):
        self._try_start_process(DropletSearchCalibrationProcess)

    def start_manual_droplet_characterization(self, *, start_delay_us: int | None = None):
        self._try_start_process(DropletSearchCalibrationProcess, manual_start=True)

    def start_pressure_sweep_characterization(self, *, sphere_delay_us=10000, replicates_per_pressure=20, order="desc"):
        self._try_start_process(PressureSweepCharacterizationProcess,
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
        canonical = steps.get(phase_key, [])
        if canonical:
            return canonical

        # Backward compatibility: older runs may have stored the legacy alias
        # key directly (e.g. "trajectory_calibration"). Fall back to those keys
        # when the canonical list is empty or missing.
        for alias_key, canonical_key in self.PHASE_ALIASES.items():
            if canonical_key != phase_key or alias_key == phase_key:
                continue
            legacy_rows = steps.get(alias_key, [])
            if legacy_rows:
                return legacy_rows
        return canonical

    def get_centered_nozzle_position(self):
        recs = self._latest_step_list("nozzle_position")
        if recs:
            return recs[-1].get("result")
        self.calibrationStageChanged.emit("No nozzle position calibration available", "red")
        return None

    def get_emergence_time(self, *, quiet: bool = True):
        """
        Return the last recorded emergence delay for the current run, or None.
        Pure lookup (no logging). If quiet=False, emit a one-shot warning.
        Accept multiple possible key names used by processes.
        """
        recs = self._latest_step_list("droplet_emergence")
        if recs:
            res = (recs[-1].get("result") or {})
            # Accept alternative field names
            val = (res.get("flash_delay")
                or res.get("flash_delay_us")
                or res.get("delay_us"))
            if val is None:
                # Fallback to settings snapshot stored with the step
                val = (recs[-1].get("settings") or {}).get("flash_delay")
            return val

        # Only complain if the caller explicitly asks
        if not quiet:
            self.calibrationStageChanged.emit("No droplet emergence calibration available", "red")
        return None

    def is_in_initial_position(self):
        # kept for compatibility—presence of any pressure step
        return bool(self._latest_step_list("pressure_calibration"))

    # ------------- Cross-step setters/getters -------------

    def set_start_pressure(self, pressure):
        self.start_pressure = pressure
    def set_num_pressure_tests(self, num_tests):
        self.num_pressure_tests = num_tests
    def set_background_image(self, background): 
        self.background_image = background
        self._emit_readiness()
    def set_nozzle_center(self, center): 
        self.nozzle_center = center
        self._emit_readiness()
    def set_nozzle_center_image_position(self, center): 
        self.nozzle_center_image_position = center
        self._emit_readiness()
    def set_emergence_nozzle_center_image_position(self, center):
        self.emergence_nozzle_center_image_position = center
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
        # Normalize inputs:
        if isinstance(result, dict):
            # Merge into existing dict result if present
            cur = self._last_pressure_scan_result if isinstance(self._last_pressure_scan_result, dict) else {}
            cur = dict(cur)  # shallow copy
            cur.update(result)
            # Ensure primary_band is a clean 2-float list if present
            if "primary_band" in cur and isinstance(cur["primary_band"], (list, tuple)) and len(cur["primary_band"]) == 2:
                lo, hi = cur["primary_band"]
                cur["primary_band"] = [float(lo), float(hi)]
            self._last_pressure_scan_result = cur

        elif isinstance(result, (list, tuple)) and len(result) == 2:
            # Update-only semantics: keep existing result dict, just replace the band
            cur = self._last_pressure_scan_result if isinstance(self._last_pressure_scan_result, dict) else {}
            cur = dict(cur)
            lo, hi = result
            cur["primary_band"] = [float(lo), float(hi)]
            self._last_pressure_scan_result = cur

        else:
            # Ignore invalid input types
            return

        self._emit_readiness()
    def set_pressure_trajectory_result(self, result_dict):
        self._pressure_traj_result = result_dict
        self._emit_readiness()

    def get_start_pressure(self): return self.start_pressure
    def get_num_pressure_tests(self): return self.num_pressure_tests
    def get_background_image(self): return self.background_image
    def get_nozzle_center(self): return self.nozzle_center
    def get_nozzle_center_image_position(self): return self.nozzle_center_image_position
    def get_emergence_nozzle_center_image_position(self):
        return self.emergence_nozzle_center_image_position
    def get_pressure_scan_nozzle_center_image_position(self):
        return (
            self.emergence_nozzle_center_image_position
            if self.emergence_nozzle_center_image_position is not None
            else self.nozzle_center_image_position
        )
    def get_pressure_scan_nozzle_center_source(self):
        if self.emergence_nozzle_center_image_position is not None:
            return "emergence"
        if self.nozzle_center_image_position is not None:
            return "nozzle_position"
        return "none"
    def get_trajectory_vector(self): return self.droplet_trajectory_vector
    def get_trajectory_delay(self): return self.trajectory_delay
    def get_min_start_delay(self): return self.min_start_delay
    def get_intermediate_droplet_position(self): return self.intermediate_droplet_position

    def get_primary_pressure_band(self):
        res = self._last_pressure_scan_result
        if not res:
            return None

        # Back-compat: if someone shoved a tuple/list in here, accept it
        if isinstance(res, (list, tuple)) and len(res) == 2:
            lo, hi = res
            return float(lo), float(hi)

        if isinstance(res, dict):
            band = res.get("primary_band")
            if isinstance(band, (list, tuple)) and len(band) == 2:
                lo, hi = band
                return float(lo), float(hi)

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
        self.record_process_event(
            "stage_changed",
            {"message": str(message)},
            state_name=getattr(self.activeCalibration, "phase_name", None),
        )

    @Slot()
    def onCalibrationCompleted(self):
        self.calibrationStageChanged.emit("Calibration completed successfully", "green")
        self._finalize_process_recording("completed")
        self.activeCalibration = None
        self._emit_readiness()
        self.calibrationCompleted.emit()
        if len(self.calibration_queue) > 0:
            self.calibrationStageChanged.emit("Starting next calibration in queue...", "blue")
            self.start_calibration_queue()
        else:
            self.calibrationQueueCompleted.emit()

    @Slot(str)
    def onCalibrationError(self, error_message):
        self.calibrationStageChanged.emit("Calibration error: " + error_message, "red")
        self._finalize_process_recording("error", error_message=str(error_message))
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

        self.record_analysis(
            {
                "kind": "calibration_data_updated",
                "phase": phase_key,
                "payload": payload,
            }
        )

        # Optional: emit flat rows if droplet arrays present (from droplet_search / characterization)
        # self._try_append_flat_rows_from_payload(run, phase_key, payload)

        self._save_atomic()

        # Notify listeners to refresh the summary table when relevant
        if phase_key in ("pressure_sweep_characterization", "droplet_search"):
            try:
                self.characterizationSummaryUpdated.emit()
            except Exception:
                pass

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
        phase_name = getattr(proc_cls, "phase_name", None) or getattr(proc_cls, "__name__", "unknown")

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
            # "trajectory":                     pack(TrajectoryCalibrationProcess),
            "trajectory_pressure_scan":       pack(PressureTrajectoryCalibrationProcess),
            # "droplet_search":                 pack(DropletSearchCalibrationProcess),
            "droplet_characterization":       pack(DropletSearchCalibrationProcess),
            "pressure_sweep_characterization":pack(PressureSweepCharacterizationProcess),
        }
        self.readinessChanged.emit(readiness)

    def get_last_characterization_mean_nL(self) -> float | None:
        """
        Return the most recent mean droplet volume (nL) for the *current* stock solution,
        preferring droplet_search rows, else the latest valid sweep row.
        """
        try:
            rows = self.get_pressure_sweep_summary_rows()
        except Exception:
            rows = []
        if not rows:
            return None

        # prefer 'search' rows, newest first
        def _key(r):
            # sort by phase preference, then timestamp
            phase_rank = 0 if r.get("phase") == "search" else 1
            return (phase_rank, r.get("timestamp") or "")
        rows = sorted([r for r in rows if r.get("mean_nL") is not None and (r.get("valid", True))], key=_key)
        if not rows:
            return None
        # take the last (newest) by our ordering
        return float(rows[-1]["mean_nL"])

    def get_pressure_sweep_summary_rows(self):
        # Ensure self.data is populated from disk on first use
        self.ensure_loaded()

        runs = self.data.get("runs") or []
        if not runs:
            return []

        # Prefer current stock; fallback to most recent known stock
        cur_stock = self._safe_get_stock_solution()
        if cur_stock is None:
            for run in reversed(runs):
                s = run.get("stock_solution")
                if s:
                    cur_stock = s
                    break
        if cur_stock is None:
            return []

        matching = [(idx, run) for idx, run in enumerate(runs) if run.get("stock_solution") == cur_stock]
        if not matching:
            return []

        run_ids_in_order = [run.get("run_id") for _, run in matching]
        id_to_run_no = {rid: i + 1 for i, rid in enumerate(run_ids_in_order)}

        rows = []
        for _, run in matching:
            rid = run.get("run_id")
            run_no = id_to_run_no.get(rid)

            # ---- (A) Full sweep steps: each step contains result["pressures"] list
            for step in run.get("steps", {}).get("pressure_sweep_characterization", []):
                pw = (step.get("settings") or {}).get("print_width")
                ts = step.get("timestamp")
                pressures = (step.get("result") or {}).get("pressures") or []
                for p in pressures:
                    rows.append({
                        "run_no": run_no,
                        "pw_us": pw,
                        "pressure_psi": p.get("pressure"),
                        "mean_nL": p.get("mean_volume"),
                        "cv_pct": p.get("cv_volume_percent"),
                        "valid": p.get("valid"),
                        "invalid_reason": p.get("invalid_reason"),
                        "timestamp": ts,
                        "phase": "sweep",
                    })

            # ---- (B) Droplet-search steps: single pressure at current PW/pressure
            for step in run.get("steps", {}).get("droplet_search", []):
                ts = step.get("timestamp")
                res = (step.get("result") or {})
                settings = (step.get("settings") or {})

                # Prefer settings snapshot; fallback to fields we added in (2)
                pw = settings.get("print_width")
                pr = settings.get("print_pressure")
                if pw is None:
                    pw = res.get("print_pulse_width_us")
                if pr is None:
                    pr = res.get("pressure")

                mean_nL = res.get("mean_volume")
                cv_pct  = res.get("cv_volume_percent")

                # Only add a row if we have something meaningful
                if (pw is not None) and (pr is not None) and (mean_nL is not None):
                    rows.append({
                        "run_no": run_no,
                        "pw_us": pw,
                        "pressure_psi": pr,
                        "mean_nL": mean_nL,
                        "cv_pct": cv_pct,
                        "valid": bool(res.get("valid", True)),
                        "invalid_reason": None if res.get("valid", True) else "invalid",
                        "timestamp": ts,
                        "phase": "search",
                    })

        # Sort: PW → Pressure → Run # → Timestamp
        def _last_if_none(val, fill):
            return (val is None, fill if val is None else val)

        rows.sort(key=lambda r: (
            _last_if_none(r["pw_us"],        10**9),
            _last_if_none(r["pressure_psi"], 10**9),
            _last_if_none(r["run_no"],       10**9),
            r["timestamp"] or ""
        ))
        return rows
    
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
        self._last_capture_refs = {}
        self._active_capture_pair_id = None

    def start(self):
        """Start the calibration process by starting the state machine."""
        self._record_event("state_machine_start", {"phase_name": str(self.phase_name or "")})
        self.state_machine.start()

    def stop(self):
        """Stop the state machine if needed."""
        self._record_event("state_machine_stop", {"phase_name": str(self.phase_name or "")})
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

    # ---------- recorder helpers ----------
    def _record_event(self, event_type: str, payload: dict | None = None, *, state_name: str | None = None, level: str = "info"):
        try:
            if hasattr(self.calibration_manager, "record_process_event"):
                self.calibration_manager.record_process_event(
                    str(event_type),
                    payload or {},
                    state_name=state_name or getattr(self, "phase_name", None),
                    level=level,
                )
        except Exception:
            pass

    def _record_analysis(self, payload: dict):
        try:
            if hasattr(self.calibration_manager, "record_analysis"):
                self.calibration_manager.record_analysis(payload or {})
        except Exception:
            pass

    def _record_decision(self, decision: str, payload: dict | None = None):
        out = dict(payload or {})
        out["decision"] = str(decision)
        self._record_event("decision", out)

    def _record_error(self, message: str, payload: dict | None = None):
        out = dict(payload or {})
        out["error_message"] = str(message)
        self._record_event("error", out, level="error")

    def _record_capture(self, frame, *, role: str, metadata: dict | None = None):
        if frame is None:
            return None
        try:
            if hasattr(self.calibration_manager, "record_capture_frame"):
                return self.calibration_manager.record_capture_frame(
                    frame,
                    role=str(role),
                    metadata=metadata or {},
                )
        except Exception:
            return None
        return None

    def _request_settings_with_recording(self, settings: dict, callback, *, context: str = ""):
        settings_obj = dict(settings or {})
        self._record_event("settings_requested", {"settings": settings_obj, "context": str(context or "")})

        def _wrapped(*args, **kwargs):
            self._record_event("settings_completed", {"settings": settings_obj, "context": str(context or "")})
            if callback is not None:
                callback(*args, **kwargs)

        self.calibration_manager.changeSettingsRequested.emit(settings_obj, _wrapped)

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
            self._record_event(
                "capture_attempt",
                {
                    "set_attr": str(set_attr),
                    "stage_text": str(stage_text),
                    "attempt": int(state["attempt"]),
                    "attempts_total": int(attempts_total),
                },
            )
            # # Stage text (with retry suffix after the first attempt)
            # if state["attempt"] == 1:
            #     self.stageChanged.emit(stage_text)
            # else:
            #     self.stageChanged.emit(stage_text + retry_stage_suffix.format(
            #         i=state["attempt"], n=attempts_total
            #     ))

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
                    self._record_event(
                        "capture_result",
                        {
                            "set_attr": str(set_attr),
                            "stage_text": str(stage_text),
                            "attempt": int(state["attempt"]),
                            "status": "failed",
                        },
                        level="warning",
                    )
                    # Failed this attempt
                    if state["attempt"] < attempts_total:
                        state["attempt"] += 1
                        # Schedule the next try
                        QTimer.singleShot(retry_delay_ms, _arm_one_attempt)
                        return
                    # Final failure
                    self._record_error(
                        final_error_msg,
                        {
                            "set_attr": str(set_attr),
                            "stage_text": str(stage_text),
                            "attempts_total": int(attempts_total),
                        },
                    )
                    if on_final_failure is not None:
                        on_final_failure()
                    else:
                        self.calibrationError.emit(final_error_msg)
                    return

                # Success
                setattr(self, set_attr, frame)
                role = str(set_attr).replace("_image", "")
                capture_meta = {
                    "set_attr": str(set_attr),
                    "stage_text": str(stage_text),
                    "attempt": int(state["attempt"]),
                }
                if set_attr == "background_image":
                    self._active_capture_pair_id = str(uuid.uuid4())
                    capture_meta.update(
                        {
                            "pair_id": self._active_capture_pair_id,
                            "pair_role": "background",
                            "pair_order": 1,
                        }
                    )
                elif set_attr == "droplet_image":
                    bg_ref = self._last_capture_refs.get("background_image") or {}
                    pair_id = self._active_capture_pair_id or bg_ref.get("pair_id") or str(uuid.uuid4())
                    capture_meta.update(
                        {
                            "pair_id": pair_id,
                            "pair_role": "droplet",
                            "pair_order": 2,
                            "subtract_background_capture_id": bg_ref.get("capture_id", ""),
                            "subtract_background_image_relpath": bg_ref.get("image_relpath", ""),
                        }
                    )
                capture_ref = self._record_capture(frame, role=role or "capture", metadata=capture_meta)
                if capture_ref is not None:
                    self._last_capture_refs[set_attr] = capture_ref
                self._record_event(
                    "capture_result",
                    {
                        "set_attr": str(set_attr),
                        "stage_text": str(stage_text),
                        "attempt": int(state["attempt"]),
                        "status": "success",
                        "capture_ref": capture_ref or {},
                    },
                )
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

    def _request_move_relative_with_timeout(
        self,
        move_vector,
        *,
        on_done=None,
        timeout_ms: int = 15_000,
        err_msg: str | None = None,
    ):
        """
        Request a relative stage move and fail deterministically if move completion
        callback is never observed.
        """
        done = {"fired": False}
        t_ref = {"t": None}
        fail_msg = err_msg or f"Move timeout after {int(timeout_ms)} ms (relative {move_vector})"

        def _finish(ok: bool, why: str | None = None):
            if done["fired"]:
                return
            done["fired"] = True
            self._cancel_timeout(t_ref["t"])
            t_ref["t"] = None
            if not ok:
                self._record_error(why or fail_msg, {"mode": "relative", "move_vector": move_vector})
                self.calibrationError.emit(why or fail_msg)
                return
            self._record_event("move_completed", {"mode": "relative", "move_vector": move_vector})
            if callable(on_done):
                try:
                    on_done()
                except Exception as e:
                    self.calibrationError.emit(f"Move completion handler failed: {e}")
            else:
                self.calibration_manager.emitMoveCompleted()

        t_ref["t"] = self._start_timeout(
            int(timeout_ms),
            on_timeout=lambda: _finish(False, fail_msg),
        )
        self._record_event(
            "move_requested",
            {"mode": "relative", "move_vector": move_vector, "timeout_ms": int(timeout_ms)},
        )
        try:
            self.calibration_manager.moveRequested.emit(
                move_vector,
                lambda *args, **kwargs: _finish(True, "callback"),
            )
        except Exception as e:
            _finish(False, f"Move request failed: {e}")

    def _request_move_absolute_with_timeout(
        self,
        target_position,
        *,
        on_done=None,
        timeout_ms: int = 15_000,
        err_msg: str | None = None,
    ):
        """
        Request an absolute stage move and fail deterministically if move completion
        callback is never observed.
        """
        done = {"fired": False}
        t_ref = {"t": None}
        fail_msg = err_msg or f"Move timeout after {int(timeout_ms)} ms (absolute {target_position})"

        def _finish(ok: bool, why: str | None = None):
            if done["fired"]:
                return
            done["fired"] = True
            self._cancel_timeout(t_ref["t"])
            t_ref["t"] = None
            if not ok:
                self._record_error(why or fail_msg, {"mode": "absolute", "target_position": target_position})
                self.calibrationError.emit(why or fail_msg)
                return
            self._record_event("move_completed", {"mode": "absolute", "target_position": target_position})
            if callable(on_done):
                try:
                    on_done()
                except Exception as e:
                    self.calibrationError.emit(f"Move completion handler failed: {e}")
            else:
                self.calibration_manager.emitMoveCompleted()

        t_ref["t"] = self._start_timeout(
            int(timeout_ms),
            on_timeout=lambda: _finish(False, fail_msg),
        )
        self._record_event(
            "move_requested",
            {"mode": "absolute", "target_position": target_position, "timeout_ms": int(timeout_ms)},
        )
        try:
            self.calibration_manager.moveAbsoluteRequested.emit(
                target_position,
                lambda *args, **kwargs: _finish(True, "callback"),
            )
        except Exception as e:
            _finish(False, f"Move request failed: {e}")

class HeadPrimeCalibrationProcess(BaseCalibrationProcess):
    """
    Purpose: give a newly loaded printer head a forceful first ejection so it begins behaving normally.
    This process *does not* search or measure anything; it:
      1) snapshots current settings
      2) applies priming settings (pressure +1 psi, PW=3500 us, flash_delay=10000, 1 droplet)
      3) captures & presents the image
      4) restores the original settings
    """
    phase_name = "head_prime"

    # ---------- minimal readiness check ----------
    # @staticmethod
    # def missing_requirements(calibration_manager) -> list[str]:
    #     m = calibration_manager.model
    #     missing = []
    #     # Machine connected & can report pressure
    #     try:
    #         _ = m.machine_model.get_current_print_pressure()
    #     except Exception:
    #         missing.append("machine connection")
    #     # Camera available
    #     try:
    #         _ = m.droplet_camera_model.get_image_size()
    #     except Exception:
    #         missing.append("droplet camera")
    #     return missing

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)

        # Snapshots
        self._orig = None
        self._priming = None
        self.captured_image = None

        # Safety bounds if machine_model doesn't expose them
        self._min_print_pressure_fallback = 0.35
        self._max_print_pressure_fallback = 3.00

        # ---- States ----
        self.state_apply_prime   = QState()
        self.state_capture       = QState()
        self.state_restore       = QState()
        self.state_final         = QFinalState()

        # ---- Wiring ----
        self.state_apply_prime.entered.connect(self.onApplyPrimingSettings)
        self.state_capture.entered.connect(self.onCapture)
        self.state_restore.entered.connect(self.onRestoreOriginal)
        self.state_final.entered.connect(self.onCalibrationCompleted)

        # Transitions
        t1 = QSignalTransition()
        t1.setSenderObject(self.calibration_manager)
        t1.setSignal(b"2settingsChangeCompleted()")
        t1.setTargetState(self.state_capture)
        self.state_apply_prime.addTransition(t1)

        t2 = QSignalTransition()
        t2.setSenderObject(self.calibration_manager)
        t2.setSignal(b"2captureCompleted()")
        t2.setTargetState(self.state_restore)
        self.state_capture.addTransition(t2)

        t3 = QSignalTransition()
        t3.setSenderObject(self.calibration_manager)
        t3.setSignal(b"2settingsChangeCompleted()")
        t3.setTargetState(self.state_final)
        self.state_restore.addTransition(t3)

        self.state_machine.addState(self.state_apply_prime)
        self.state_machine.addState(self.state_capture)
        self.state_machine.addState(self.state_restore)
        self.state_machine.addState(self.state_final)
        self.state_machine.setInitialState(self.state_apply_prime)

    # ---------- helpers ----------
    def _clamp_pressure(self, p: float) -> float:
        mm = self.model.machine_model
        pmin = float(getattr(mm, "min_print_pressure", self._min_print_pressure_fallback))
        pmax = float(getattr(mm, "max_print_pressure", self._max_print_pressure_fallback))
        return max(pmin, min(pmax, float(p)))

    # ---------- state handlers ----------
    @Slot()
    def onApplyPrimingSettings(self):
        self.stageChanged.emit("Head Prime – Snapshotting & applying priming settings")

        # Snapshot current settings from the manager helper (stable with your stack)
        self._orig = dict(self.calibration_manager.get_current_settings() or {})

        cur_pressure = float(self._orig.get("print_pressure", 0.0))
        priming_pressure = self._clamp_pressure(cur_pressure + 1.0)

        self._priming = {
            "num_droplets": 1,
            "print_pulse_width": int(3500),
            "flash_delay": int(10000),
            "print_pressure": float(priming_pressure),
        }

        # Apply priming settings; proceed when controller emits settingsChangeCompleted
        self.calibration_manager.changeSettingsRequested.emit(
            self._priming,
            self.calibration_manager.emitSettingsChangeCompleted
        )

    @Slot()
    def onCapture(self):
        self.stageChanged.emit("Head Prime – Capturing single priming image")

        # Capture (with small retry policy) and present image immediately on success
        def _on_success(frame):
            # Surface image to the UI
            self.presentImageSignal.emit(frame)
            self.captured_image = frame

        self._capture_with_policy(
            set_attr="captured_image",
            stage_text="Capturing priming image",
            attempts_total=3,
            retry_delay_ms=100,
            guard_timeout_ms=10_000,
            on_success=_on_success,
            final_error_msg="Failed to capture image during head prime."
        )

    @Slot()
    def onRestoreOriginal(self):
        self.stageChanged.emit("Head Prime – Restoring original settings")

        # Only restore keys we changed; keep other user settings untouched
        restore = {}
        if self._orig is not None:
            if "num_droplets" in self._orig:
                restore["num_droplets"] = int(self._orig["num_droplets"])
            if "flash_delay" in self._orig:
                restore["flash_delay"] = int(self._orig["flash_delay"])
            if "print_width" in self._orig:  # snapshot key name → controller key name
                restore["print_pulse_width"] = int(self._orig["print_width"])
            if "print_pressure" in self._orig:
                restore["print_pressure"] = float(self._orig["print_pressure"])

        # Emit a row to persist what we did (lightweight — no arrays)
        try:
            payload = {
                "result": {
                    "action": "head_prime",
                    "priming_settings": self._priming,
                    "original_settings": {
                        "num_droplets": self._orig.get("num_droplets"),
                        "flash_delay": self._orig.get("flash_delay"),
                        "print_pulse_width_us": self._orig.get("print_width"),
                        "print_pressure": self._orig.get("print_pressure"),
                    },
                    "captured": self.captured_image is not None,
                }
            }
            self.calibrationDataUpdated.emit(payload)
        except Exception:
            pass

        # Restore and move to final on settingsChangeCompleted
        self.calibration_manager.changeSettingsRequested.emit(
            restore,
            self.calibration_manager.emitSettingsChangeCompleted
        )

class NozzlePositionCalibrationProcess(BaseCalibrationProcess):
    """
    Identify the nozzle by diffing background vs droplet image.
    - Missing contour/no-signal -> scan X around the start anchor (right then left).
    - Multiple contours -> reduce flash delay until a single contour is observed.
    - Single contour -> use contour top as nozzle coordinate and recenter near top-center.
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
        # flash delay handling (in microseconds)
        self.initial_flash_delay_us = max(self.model.machine_model.get_print_pulse_width() + 2600, 0)
        self.delay_scan_increments = [0, 400, 800, 1200, 1600]   # try a few longer delays
        self.min_flash_delay_us = 2000
        self.max_flash_delay_us = 12000
        self.multi_contour_delay_step_us = 200
        self._current_flash_delay_us = int(self.initial_flash_delay_us)

        # pressure search (psi)
        self.max_pressure_levels = 3          # total pressure levels: base + two bumps
        self.pressure_step = 0.2              # psi per bump
        self.min_print_pressure = 0.35        # safe fallback bounds if model doesn’t expose them
        self.max_print_pressure = 2.00

        self.no_signal_min_fg_px = 120  # min foreground pixels to consider "signal" present

        # recenter loop guard
        self.max_recenter_iterations = 8
        self._recenter_iters = 0

        # movement clamp (motor steps). Adjust to your mechanics.
        self.max_xy_steps_per_correction = 1000
        self.move_timeout_ms = 15_000
        self._default_axis_spans = {"X": 20_000, "Y": 10_000, "Z": 20_000}

        # top-center target: x center, y near top
        self.top_margin_frac = 0.12           # ~12% down from top
        self.center_tol_frac = 0.03           # within 3% of width (x) and 3% of height (y band around target)
        self.top_band_frac   = 0.03

        # Missing-nozzle search around start anchor (X axis only).
        self.nozzle_search_half_fov_fraction = 0.5
        self.nozzle_search_min_half_fov_x_steps = 200
        self._x_scan_anchor = None
        self._x_scan_half_fov_x_steps = 0
        self._x_scan_attempt_index = 0
        self._x_scan_active = False

        # Z recovery when nozzle is likely above FOV.
        self.downward_recovery_step_fov = 0.25
        self.max_downward_recovery_steps = 4  # total span = 1.0 FOV
        self._downward_recovery_steps_taken = 0

        # Background-top brightness heuristic for "head in view" check.
        self.head_view_top_band_frac = 0.20
        self.head_view_mid_start_frac = 0.35
        self.head_view_mid_end_frac = 0.65
        self.head_not_in_view_ratio_min = 0.90
        self.head_not_in_view_delta_max = 25.0

        # ---- internal scan state (reset in onPrepareDroplet) ----
        self._base_delay_us = self.initial_flash_delay_us
        self._delay_idx = 0
        self._base_pressure = None
        self._pressure_level = 0  # 0=base,1=+step,2=+2*step

        # --- Fixed thresholding controls (replaces Otsu for nozzle detection) ---
        self.fixed_thresh_value = 30         # 8-bit gray value; tune 20–45
        self.no_signal_min_fg_px = 120       # already present; keep/tune 80–200
        self.min_stream_bbox_h_px = 10       # reject tiny blobs
        self.search_top_band_frac = 0.60     # top_y must be within top 60% of image

        # --- Warm-up (throwaway) frame control ---
        self._throwaway_pending = False      # set True when we want to discard next droplet frame


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
        self.stageChanged.emit("Nozzle Pos - Moving to initial position")
        # Get the location of the camera in the location model
        initial_position = self.model.location_model.get_location_dict('camera')
        move_vector = self._clamp_abs_target(
            initial_position['X'],
            initial_position['Y'],
            initial_position['Z'],
        )
        print(f"Moving to initial position: {move_vector}")
        self._record_event("initial_position_target", {"target_position": move_vector})
        self._request_move_absolute_with_timeout(
            move_vector,
            timeout_ms=self.move_timeout_ms,
            err_msg="Nozzle Pos - Initial move timed out."
        )


    @Slot()
    def onPrepareBackground(self):
        self.stageChanged.emit("Nozzle Pos - Preparing background (0 droplets)")
        # Request to change droplet settings (0 droplets). The callback emits a signal.
        settings = {
            "num_droplets": 0,
            "flash_delay": int(self._clamp_delay(getattr(self, "_current_flash_delay_us", self.initial_flash_delay_us))),
        }
        self._request_settings_with_recording(
            settings,
            self.calibration_manager.emitSettingsChangeCompleted,
            context="nozzle_prepare_background",
        )

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
        self.stageChanged.emit("Nozzle Pos - Preparing droplet capture")
        self._current_flash_delay_us = int(
            self._clamp_delay(getattr(self, "_current_flash_delay_us", self.initial_flash_delay_us))
        )
        self._base_delay_us = int(self._current_flash_delay_us)
        self._delay_idx = 0
        self._base_pressure = float(self.model.machine_model.get_current_print_pressure())
        self._pressure_level = 0

        if not bool(getattr(self, "_x_scan_active", False)):
            self._x_scan_anchor = self._current_position_dict()
            self._x_scan_half_fov_x_steps = self._estimate_half_fov_x_steps()
            self._x_scan_attempt_index = 0

        # First shot is a warm-up to discard
        self._throwaway_pending = True

        settings = {
            "num_droplets": 1,
            "flash_delay": int(self._current_flash_delay_us),
        }
        self._request_settings_with_recording(
            settings,
            self.calibration_manager.emitSettingsChangeCompleted,
            context="nozzle_prepare_droplet",
        )
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
        self.stageChanged.emit("Nozzle Pos - Analyzing diff to locate nozzle")
        bg, dr = self.background_image, self.droplet_image

        # If a warm-up frame was requested, discard this one and re-capture
        if self._throwaway_pending:
            self._throwaway_pending = False
            self.stageChanged.emit("Nozzle Pos - Discarding warm-up droplet frame")
            # Re-shoot with the *same* settings (one droplet, current delay/pressure)
            settings = {
                "num_droplets": 1,
                "flash_delay": int(self._current_flash_delay_us),
                # keep current pressure (no key needed if your stack preserves it)
            }
            self._record_decision(
                "discard_warmup_frame",
                {
                    "settings": settings,
                    "flash_delay_us": int(self._current_flash_delay_us),
                    "x_scan_attempt_index": int(self._x_scan_attempt_index),
                },
            )
            self._request_settings_with_recording(
                settings,
                self.calibration_manager.emitSettingsChangeCompleted,
                context="nozzle_warmup_recapture",
            )
            return

        status, nozzle_px, n_contours, debug_img = self._detect_nozzle_point(bg, dr)
        pair_ctx = {
            "background_capture_id": (self._last_capture_refs.get("background_image") or {}).get("capture_id", ""),
            "background_image_relpath": (self._last_capture_refs.get("background_image") or {}).get("image_relpath", ""),
            "droplet_capture_id": (self._last_capture_refs.get("droplet_image") or {}).get("capture_id", ""),
            "droplet_image_relpath": (self._last_capture_refs.get("droplet_image") or {}).get("image_relpath", ""),
        }
        self._record_analysis(
            {
                "kind": "nozzle_detection",
                "status": str(status),
                "nozzle_px": nozzle_px,
                "n_contours": int(n_contours),
                "scan_state": {
                    "flash_delay_us": int(self._current_flash_delay_us),
                    "x_scan_attempt_index": int(self._x_scan_attempt_index),
                    "x_scan_half_fov_x_steps": int(self._x_scan_half_fov_x_steps),
                    "x_scan_anchor": dict(self._x_scan_anchor or {}),
                    "downward_recovery_steps_taken": int(self._downward_recovery_steps_taken),
                    "max_downward_recovery_steps": int(self.max_downward_recovery_steps),
                    "base_pressure": float(self._base_pressure) if self._base_pressure is not None else None,
                    "recenter_iterations": int(self._recenter_iters),
                },
                "detection": dict(getattr(self, "_last_detection_details", {}) or {}),
                "pair": pair_ctx,
            }
        )

        if status == "OK":
            self._x_scan_active = False
            self.presentImageSignal.emit(debug_img)
            if n_contours > 1:
                self._handle_multiple_contours(int(n_contours), nozzle_px)
                return
            decision = self._recenter_or_finish(nozzle_px)
            if decision:
                self._record_decision(
                    decision,
                    {"status": "OK", "nozzle_px": nozzle_px, "n_contours": int(n_contours)},
                )
            return

        if status == "NO_SIGNAL":
            self._handle_missing_nozzle(status)
            return

        # status == "NONE" → keep your existing delay-scan plan, then (smaller) pressure bump
        self._handle_missing_nozzle(status)

    def _current_position_dict(self):
        pos = self.model.machine_model.get_current_position_dict() or {}
        return {
            "X": int(pos.get("X", 0)),
            "Y": int(pos.get("Y", 0)),
            "Z": int(pos.get("Z", 0)),
        }

    def _estimate_half_fov_x_steps(self):
        try:
            dX, _dY, _dZ = self.model.droplet_camera_model.compute_move_by_fraction(
                float(self.nozzle_search_half_fov_fraction),
                0.0,
            )
            mag = abs(int(round(float(dX))))
            if mag > 0:
                return int(mag)
        except Exception:
            pass
        return int(max(1, int(self.nozzle_search_min_half_fov_x_steps)))

    def _next_x_scan_target(self):
        if self._x_scan_anchor is None:
            self._x_scan_anchor = self._current_position_dict()
        half_steps = int(max(1, int(self._x_scan_half_fov_x_steps or self._estimate_half_fov_x_steps())))
        attempts = (
            ("x_scan_right_from_anchor", -half_steps, "Nozzle Pos - No contour; scanning right from start point."),
            ("x_scan_left_from_anchor", +half_steps, "Nozzle Pos - No contour; scanning left from start point."),
        )
        cur = self._current_position_dict()
        anchor = self._x_scan_anchor

        while self._x_scan_attempt_index < len(attempts):
            decision, dx, msg = attempts[self._x_scan_attempt_index]
            self._x_scan_attempt_index += 1
            tgt = self._clamp_abs_target(
                int(anchor["X"]) + int(dx),
                int(anchor["Y"]),
                int(anchor["Z"]),
            )
            if (int(tgt[0]), int(tgt[1]), int(tgt[2])) == (int(cur["X"]), int(cur["Y"]), int(cur["Z"])):
                self._record_event(
                    "x_scan_target_collapsed",
                    {
                        "decision": str(decision),
                        "target_position": tgt,
                        "anchor": dict(anchor),
                        "half_fov_x_steps": int(half_steps),
                    },
                    level="warning",
                )
                continue
            return True, decision, msg, tgt
        return False, "", "", None

    def _background_head_view_metrics(self, bg):
        if bg is None:
            return {
                "valid": False,
                "reason": "missing_background",
            }
        try:
            arr = np.asarray(bg)
            if arr.ndim == 3:
                if arr.shape[2] == 3:
                    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
                else:
                    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
            else:
                gray = arr

            h, w = gray.shape[:2]
            top_h = max(1, int(round(float(self.head_view_top_band_frac) * h)))
            mid_y0 = max(0, int(round(float(self.head_view_mid_start_frac) * h)))
            mid_y1 = max(mid_y0 + 1, int(round(float(self.head_view_mid_end_frac) * h)))
            mid_y1 = min(h, mid_y1)
            if mid_y1 <= mid_y0:
                return {
                    "valid": False,
                    "reason": "invalid_mid_band",
                    "height": int(h),
                    "width": int(w),
                }

            top = gray[:top_h, :]
            mid = gray[mid_y0:mid_y1, :]
            top_mean = float(np.mean(top))
            mid_mean = float(np.mean(mid))
            ratio = float(top_mean / (mid_mean + 1e-9))
            delta = float(mid_mean - top_mean)
            head_in_view = not (
                ratio >= float(self.head_not_in_view_ratio_min)
                and delta <= float(self.head_not_in_view_delta_max)
            )
            return {
                "valid": True,
                "head_in_view": bool(head_in_view),
                "top_mean": float(top_mean),
                "mid_mean": float(mid_mean),
                "top_to_mid_ratio": float(ratio),
                "top_mid_delta": float(delta),
                "thresholds": {
                    "ratio_min": float(self.head_not_in_view_ratio_min),
                    "delta_max": float(self.head_not_in_view_delta_max),
                },
                "bands": {
                    "top_band_frac": float(self.head_view_top_band_frac),
                    "mid_start_frac": float(self.head_view_mid_start_frac),
                    "mid_end_frac": float(self.head_view_mid_end_frac),
                },
                "height": int(h),
                "width": int(w),
            }
        except Exception as e:
            return {
                "valid": False,
                "reason": "metric_exception",
                "error": str(e),
            }

    def _downward_recovery_target(self):
        try:
            mv = self.model.droplet_camera_model.compute_move_by_fraction(
                0.0,
                float(self.downward_recovery_step_fov),
            )
        except Exception:
            mv = (0, 0, 0)
        try:
            dx, dy, dz = mv
        except Exception:
            try:
                dx, dy = mv
                dz = 0
            except Exception:
                dx, dy, dz = 0, 0, 0
        cur = self._current_position_dict()
        tgt = self._clamp_abs_target(
            int(cur["X"]) + int(round(float(dx))),
            int(cur["Y"]) + int(round(float(dy))),
            int(cur["Z"]) + int(round(float(dz))),
        )
        applied = (
            int(tgt[0] - int(cur["X"])),
            int(tgt[1] - int(cur["Y"])),
            int(tgt[2] - int(cur["Z"])),
        )
        return tgt, applied

    def _handle_missing_nozzle(self, status: str):
        metrics = self._background_head_view_metrics(self.background_image)
        head_not_in_view = bool(metrics.get("valid")) and (not bool(metrics.get("head_in_view", True)))
        if head_not_in_view:
            self._x_scan_active = False
            # Defer X-scan until head is visible; restart X-scan plan once we regain visibility.
            self._x_scan_anchor = None
            self._x_scan_half_fov_x_steps = 0
            self._x_scan_attempt_index = 0

            if int(self._downward_recovery_steps_taken) >= int(self.max_downward_recovery_steps):
                self._record_decision(
                    "z_scan_exhausted_abort",
                    {
                        "status": str(status),
                        "downward_steps_taken": int(self._downward_recovery_steps_taken),
                        "max_downward_steps": int(self.max_downward_recovery_steps),
                        "downward_step_fov": float(self.downward_recovery_step_fov),
                        "head_view_metrics": metrics,
                    },
                )
                self.calibrationError.emit(
                    "Nozzle Pos - Printer head not visible after downward recovery scan (1.0 FOV total)."
                )
                return

            self._downward_recovery_steps_taken += 1
            tgt_down, applied_move = self._downward_recovery_target()
            if applied_move == (0, 0, 0):
                self._record_decision(
                    "z_recovery_move_collapsed_abort",
                    {
                        "status": str(status),
                        "metrics": metrics,
                        "downward_steps_taken": int(self._downward_recovery_steps_taken),
                        "max_downward_steps": int(self.max_downward_recovery_steps),
                        "target_position": tgt_down,
                        "applied_move": applied_move,
                    },
                )
                self.calibrationError.emit(
                    "Nozzle Pos - Unable to move down for out-of-view recovery (move collapsed at bounds)."
                )
                return

            self._record_decision(
                "z_scan_step_down",
                {
                    "status": str(status),
                    "downward_steps_taken": int(self._downward_recovery_steps_taken),
                    "max_downward_steps": int(self.max_downward_recovery_steps),
                    "downward_step_fov": float(self.downward_recovery_step_fov),
                    "target_position": tgt_down,
                    "applied_move": applied_move,
                    "head_view_metrics": metrics,
                },
            )
            self.stageChanged.emit(
                "Nozzle Pos - Top band indicates head out of view; "
                f"moving down by {float(self.downward_recovery_step_fov):.2f} FOV "
                f"(step {int(self._downward_recovery_steps_taken)}/{int(self.max_downward_recovery_steps)})."
            )
            self._request_move_absolute_with_timeout(
                tgt_down,
                timeout_ms=self.move_timeout_ms,
                err_msg="Nozzle Pos - Downward recovery move timed out.",
            )
            return

        advanced, decision, stage_msg, tgt = self._next_x_scan_target()
        if not advanced:
            self._x_scan_active = False
            msg = "Nozzle Pos - No nozzle contour detected after X-axis scan around start point. Check X/Z alignment."
            self._record_decision(
                "x_scan_exhausted_abort",
                {
                    "status": str(status),
                    "anchor": dict(self._x_scan_anchor or {}),
                    "half_fov_x_steps": int(self._x_scan_half_fov_x_steps),
                    "attempt_index": int(self._x_scan_attempt_index),
                    "downward_steps_taken": int(self._downward_recovery_steps_taken),
                    "max_downward_steps": int(self.max_downward_recovery_steps),
                    "head_view_metrics": metrics,
                },
            )
            self.calibrationError.emit(msg)
            return

        self.stageChanged.emit(f"{stage_msg} target={tgt}")
        self._record_decision(
            decision,
            {
                "status": str(status),
                "target_position": tgt,
                "anchor": dict(self._x_scan_anchor or {}),
                "half_fov_x_steps": int(self._x_scan_half_fov_x_steps),
                "attempt_index": int(self._x_scan_attempt_index),
            },
        )
        self._x_scan_active = True
        self._request_move_absolute_with_timeout(
            tgt,
            timeout_ms=self.move_timeout_ms,
            err_msg="Nozzle Pos - X scan move timed out.",
        )

    def _handle_multiple_contours(self, n_contours: int, nozzle_px):
        self._x_scan_active = False
        cur_delay = int(self._clamp_delay(getattr(self, "_current_flash_delay_us", self.initial_flash_delay_us)))
        if cur_delay <= int(self.min_flash_delay_us):
            msg = (
                f"Nozzle Pos - Multiple contours persist at minimum flash delay "
                f"({int(self.min_flash_delay_us)} us); unable to isolate attached droplet."
            )
            self._record_decision(
                "multi_contour_min_delay_abort",
                {
                    "n_contours": int(n_contours),
                    "flash_delay_us": int(cur_delay),
                    "nozzle_px": nozzle_px,
                },
            )
            self.calibrationError.emit(msg)
            return

        new_delay = int(self._clamp_delay(cur_delay - int(self.multi_contour_delay_step_us)))
        if new_delay >= cur_delay:
            msg = "Nozzle Pos - Unable to reduce flash delay for multi-contour recovery."
            self._record_decision(
                "multi_contour_min_delay_abort",
                {
                    "n_contours": int(n_contours),
                    "flash_delay_us": int(cur_delay),
                    "requested_new_delay_us": int(new_delay),
                    "nozzle_px": nozzle_px,
                },
            )
            self.calibrationError.emit(msg)
            return

        self._current_flash_delay_us = int(new_delay)
        settings = {
            "num_droplets": 1,
            "flash_delay": int(self._current_flash_delay_us),
        }
        self.stageChanged.emit(
            f"Nozzle Pos - Multiple contours ({int(n_contours)}); decreasing flash delay to "
            f"{int(self._current_flash_delay_us)} us and reassessing."
        )
        self._record_decision(
            "multi_contour_delay_backoff",
            {
                "n_contours": int(n_contours),
                "previous_flash_delay_us": int(cur_delay),
                "flash_delay_us": int(self._current_flash_delay_us),
                "step_us": int(self.multi_contour_delay_step_us),
                "nozzle_px": nozzle_px,
                "settings": settings,
            },
        )
        self._request_settings_with_recording(
            settings,
            self.calibration_manager.emitSettingsChangeCompleted,
            context="nozzle_multi_contour_delay_backoff",
        )

    # ----------------- Helpers: detection & movement -----------------

    def _escalate_pressure_on_no_signal(self):
        """
        For frames with effectively no foreground after Otsu:
        bump pressure by +0.2 psi up to a hard ceiling (≤ 2.0 psi or hardware max).
        Returns (True, settings_dict) or (False, error_message).
        """
        try:
            cur = float(self.model.machine_model.get_current_print_pressure())
        except Exception:
            # fall back to last known base or min
            cur = float(self._base_pressure if self._base_pressure is not None else self.min_print_pressure)

        ceiling = float(self.max_print_pressure)
        if cur >= ceiling - 1e-9:
            return (False, f"Unable to detect nozzle: increased pressure up to {ceiling:.3f} psi without any signal.")

        new_p = float(min(ceiling, cur + self.pressure_step))
        msg = f"No signal in diff → raising pressure to {new_p:.3f} psi and retesting"
        # keep current flash delay; ensure one droplet
        settings = {
            "num_droplets": 1,
            "flash_delay": int(self._clamp_delay(self._base_delay_us + self.delay_scan_increments[self._delay_idx])),
            "print_pressure": new_p,
            "_stage_msg": msg,  # internal note for UI stage text
        }
        return (True, settings)

    def _detect_nozzle_point(self, bg, dr):
        """
        Return (status, (x,y), n_contours, debug_img)
        status ∈ {"OK", "NONE", "NO_SIGNAL"}
        - NO_SIGNAL: Otsu mask has too few foreground pixels → likely nothing ejected.
        - NONE: some foreground but no valid contour after filtering (noise/specks).
        """
        self._last_detection_details = {}
        if bg is None or dr is None:
            self._last_detection_details = {
                "status": "NO_SIGNAL",
                "reason": "missing_frame",
                "threshold_value": int(self.fixed_thresh_value),
            }
            return ("NO_SIGNAL", None, 0, None)

        a = dr; b = bg
        if a.ndim == 3 and a.shape[2] == 3:
            diff = cv2.absdiff(a, b)
            gray = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)
        else:
            diff = cv2.absdiff(a, b)
            gray = diff if diff.ndim == 2 else cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

        blur = cv2.GaussianBlur(gray, (5, 5), 0)

        # FIXED THRESHOLD (no Otsu). This prevents adapting to background speckle.
        _, th = cv2.threshold(blur, int(self.fixed_thresh_value), 255, cv2.THRESH_BINARY)

        fg_px = int(np.count_nonzero(th))
        details = {
            "threshold_value": int(self.fixed_thresh_value),
            "foreground_pixels": int(fg_px),
            "no_signal_min_fg_px": int(self.no_signal_min_fg_px),
        }
        if fg_px < int(self.no_signal_min_fg_px):
            dbg = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
            details.update({"status": "NO_SIGNAL", "reason": "foreground_below_min"})
            self._last_detection_details = details
            return ("NO_SIGNAL", None, 0, dbg)

        # Morphological clean-up
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, k, iterations=1)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k, iterations=1)

        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        details["raw_contour_count"] = int(len(contours))
        if not contours:
            dbg = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
            details.update({"status": "NONE", "reason": "no_contours_after_threshold"})
            self._last_detection_details = details
            return ("NONE", None, 0, dbg)

        H, W = gray.shape[:2]
        top_band_limit = int(self.search_top_band_frac * H)

        # Filter: area, min bbox height, and contour top must be in the upper band
        kept = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < 2000:
                continue
            x, y, w, h = cv2.boundingRect(c)
            if h < self.min_stream_bbox_h_px:
                continue
            ys = c[:, :, 1].flatten()
            top_y = int(ys.min())
            if top_y > top_band_limit:
                continue
            kept.append((c, area, top_y, x, y, w, h))

        details["kept_contour_count"] = int(len(kept))
        details["top_band_limit_px"] = int(top_band_limit)
        if not kept:
            dbg = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
            details.update({"status": "NONE", "reason": "no_contours_after_filters"})
            self._last_detection_details = details
            return ("NONE", None, 0, dbg)

        # Prefer the contour with the lowest *bottom* (closest to nozzle top origin) and larger area
        def bottom_y(c):
            ys = c[:, :, 1].flatten()
            return int(ys.max())

        kept.sort(key=lambda t: (-bottom_y(t[0]), -t[1]))
        chosen, _, top_y, x, y, w, h = kept[0]
        n = len(kept)
        mid_x = int(round(x + w / 2.0))
        nozzle_xy = (mid_x, int(top_y))
        details["candidate_summaries"] = [
            {
                "area": float(it[1]),
                "top_y": int(it[2]),
                "bbox": [int(it[3]), int(it[4]), int(it[5]), int(it[6])],
                "bottom_y": int(bottom_y(it[0])),
            }
            for it in kept[:5]
        ]
        details["chosen"] = {
            "bbox": [int(x), int(y), int(w), int(h)],
            "top_y": int(top_y),
            "nozzle_xy": [int(nozzle_xy[0]), int(nozzle_xy[1])],
        }
        details["status"] = "OK"
        self._last_detection_details = details

        # Debug overlay
        dbg = a.copy() if (a.ndim == 3 and a.shape[2] == 3) else cv2.cvtColor(a, cv2.COLOR_GRAY2RGB)
        cv2.drawContours(dbg, [chosen], -1, (0, 255, 0), 2)
        cv2.rectangle(dbg, (x, y), (x + w, y + h), (255, 165, 0), 1)
        cv2.line(dbg, (x, int(top_y)), (x + w, int(top_y)), (0, 200, 255), 1)
        cv2.circle(dbg, nozzle_xy, 4, (255, 0, 0), -1)

        return ("OK", nozzle_xy, n, dbg)

    def _recenter_or_finish(self, nozzle_px):
        img_w, img_h = self.model.droplet_camera_model.get_image_size()
        target = (img_w // 2, int(self.top_margin_frac * img_h))
        if self._is_top_centered(nozzle_px, (img_w, img_h), target):
            self._x_scan_active = False
            self.stageChanged.emit("Nozzle near top-center; done.")
            # record final machine position
            machine_pos = self.model.machine_model.get_current_position_dict()
            self.measurements.append((machine_pos, nozzle_px))
            self.calibration_manager.set_background_image(self.background_image)
            self.calibration_manager.set_nozzle_center_image_position(nozzle_px)
            self.calibration_manager.set_nozzle_center(machine_pos)
            self.nozzleCentered.emit()
            return "finish"

        if self._recenter_iters >= self.max_recenter_iterations:
            self._record_error(
                "Too many recenter attempts-aborting to avoid oscillation.",
                {
                    "recenter_iterations": int(self._recenter_iters),
                    "max_recenter_iterations": int(self.max_recenter_iterations),
                    "nozzle_px": nozzle_px,
                    "target_px": target,
                },
            )
            self.calibrationError.emit("Too many recenter attempts-aborting to avoid oscillation.")
            return None

        # compute move vector from pixel-to-motor; clamp per-step + absolute target
        move_vector = self.model.droplet_camera_model.calculate_move_to_target(nozzle_px, target)
        move_vector = self._clamp_move(move_vector)
        cur = self.model.machine_model.get_current_position_dict()
        tgt = self._clamp_abs_target(
            int(cur['X']) + int(move_vector[0]),
            int(cur['Y']) + int(move_vector[1]),
            int(cur['Z']) + int(move_vector[2]),
        )
        clamped_move = (
            int(tgt[0] - int(cur['X'])),
            int(tgt[1] - int(cur['Y'])),
            int(tgt[2] - int(cur['Z'])),
        )
        if clamped_move != tuple(map(int, move_vector)):
            self.stageChanged.emit(
                f"Nozzle offset move clamped: requested {move_vector}, applied {clamped_move}"
            )
        if clamped_move == (0, 0, 0):
            self._record_error(
                "Nozzle Pos - Recenter move collapsed to zero at bounds.",
                {
                    "requested_move": move_vector,
                    "applied_move": clamped_move,
                    "target_position": tgt,
                },
            )
            self.calibrationError.emit("Nozzle Pos - Recenter move collapsed to zero at bounds.")
            return None

        self.stageChanged.emit(f"Nozzle offset detected; moving by {clamped_move}")
        self._x_scan_active = False
        self._record_event(
            "recenter_planned",
            {
                "nozzle_px": nozzle_px,
                "target_px": target,
                "requested_move": move_vector,
                "applied_move": clamped_move,
                "target_position": tgt,
                "recenter_iterations": int(self._recenter_iters),
            },
        )
        self._recenter_iters += 1
        self._request_move_absolute_with_timeout(
            tgt,
            timeout_ms=self.move_timeout_ms,
            err_msg="Nozzle Pos - Recenter move timed out."
        )
        return "recenter_move"

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
        return (int(round(dx)), int(round(dy)), int(round(dz)))

    def _axis_bounds(self, axis: str):
        axis = str(axis).upper()
        try:
            lo, hi = self.model.machine_model.get_axis_bounds(axis)
            return int(lo), int(hi)
        except Exception:
            pass
        try:
            bounds = self.model.location_model.get_boundaries()
            if isinstance(bounds, dict) and "min" in bounds and "max" in bounds:
                return int(bounds["min"][axis]), int(bounds["max"][axis])
        except Exception:
            pass
        cur = self.model.machine_model.get_current_position_dict()
        base = int(cur.get(axis, 0))
        span = int(self._default_axis_spans.get(axis, 10_000))
        return base - span, base + span

    def _clamp_abs_target(self, X: int, Y: int, Z: int):
        x_lo, x_hi = self._axis_bounds("X")
        y_lo, y_hi = self._axis_bounds("Y")
        z_lo, z_hi = self._axis_bounds("Z")
        Xc = max(x_lo, min(x_hi, int(X)))
        Yc = max(y_lo, min(y_hi, int(Y)))
        Zc = max(z_lo, min(z_hi, int(Z)))
        return (Xc, Yc, Zc)

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
            self.stageChanged.emit(f"No contour; trying longer flash delay: {new_delay} us (idx={self._delay_idx})")
            return True, {"num_droplets": 1, "flash_delay": int(new_delay)}
        # else try next pressure level (if any)
        if self._pressure_level + 1 < self.max_pressure_levels:
            self._pressure_level += 1
            self._delay_idx = 0
            new_pressure = self._clamp_pressure(self._base_pressure + self._pressure_level * self.pressure_step)
            new_delay = self._clamp_delay(self._base_delay_us)
            self.stageChanged.emit(
                f"No contour after delay scan; raising pressure to {new_pressure:.3f} psi and resetting delay to {new_delay} us"
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

    # Quality acceptance guards: background-normalized to avoid brittle absolute focus thresholds.
    MIN_MASK_PIXELS = 1200
    MIN_VALID_FOCUS_EVALS = 4
    MAX_CONSEC_INVALID_MASK = 8
    MIN_BEST_P90_BG_RATIO = 1.18

    @staticmethod
    def missing_requirements(cm) -> list[str]:
        missing = []
        try:
            if cm.get_nozzle_center() is None:
                missing.append("nozzle center (run nozzle position)")
        except Exception:
            missing.append("nozzle center (run nozzle position)")
        try:
            if cm.get_nozzle_center_image_position() is None:
                missing.append("nozzle center image position")
        except Exception:
            missing.append("nozzle center image position")
        try:
            if cm.get_background_image() is None:
                missing.append("background image")
        except Exception:
            missing.append("background image")
        try:
            _ = cm.model.machine_model.get_current_position_dict()
        except Exception:
            missing.append("machine position feedback")
        try:
            _ = cm.model.droplet_camera_model.get_image_size()
        except Exception:
            missing.append("droplet camera")
        return missing

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)
        self.phase_name = "nozzle_focus"

        self.droplet_image = None
        self.background_image = None
        self._bg_g2_cache = None
        self._bg_cache_sig = None

        self.mode = "probe_dir"
        self.direction = +1
        self.step = self.STEP_INIT

        self.eval_count = 0
        self.refine_evals = 0

        self.best_focus = None
        self.best_pos = None
        self.best_focus_stats = None
        self.prev_focus = None
        self.valid_focus_evals = 0
        self.invalid_focus_evals = 0
        self._consec_invalid_mask = 0

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
        bg_g2 = self._ensure_bg_g2_cache()

        img = self.droplet_image
        if img is None:
            self._abort_with_error("No image to analyze (capture failed).")
            return

        mask = self._build_focus_mask(self.background_image, img) if self.background_image is not None else None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        focus_stats = self._compute_focus_stats(gray, mask)
        if focus_stats.get("valid", False):
            focus = float(focus_stats.get("var", 0.0))
        else:
            focus = float(self.model.droplet_camera_model.compute_tenengrad_variance(gray, mask=mask))
        bg_stats = None
        p90_ratio = None
        if bg_g2 is not None and focus_stats.get("valid", False):
            try:
                bg_stats = self._compute_focus_stats(None, mask, g2_precomputed=bg_g2)
                if bg_stats.get("valid", False):
                    p90_ratio = float((focus_stats["p90"] + 1.0) / (bg_stats["p90"] + 1.0))
            except Exception:
                bg_stats = None
                p90_ratio = None

        overlay = img.copy()
        self._draw_focus_overlay(overlay, mask, focus, p90_ratio=p90_ratio)
        self.presentImageSignal.emit(overlay)

        pos = self.model.machine_model.get_current_position_dict()
        Y = pos["Y"]
        if self._start_pos is None:
            self._start_pos = dict(pos)
            y0 = self._start_pos["Y"]
            self._initialize_focus_bounds(y0)
            self.stageChanged.emit(f"Focus sweep bounds on Y: [{self._loY}, {self._hiY}]")

        self.eval_count += 1
        self.focus_curve.append((focus, pos["X"], pos["Y"], pos["Z"], int(self.step), self.mode))
        focus_stats_record = dict(focus_stats or {})
        focus_stats_record["p90_ratio_to_background"] = (None if p90_ratio is None else float(p90_ratio))
        self._record_analysis(
            {
                "process_name": "NozzleFocusCalibrationProcess",
                "phase_name": str(self.phase_name or ""),
                "mode": str(self.mode),
                "eval_count": int(self.eval_count),
                "position": {"X": int(pos["X"]), "Y": int(pos["Y"]), "Z": int(pos["Z"])},
                "focus_value": float(focus),
                "focus_stats": focus_stats_record,
                "background_stats": dict(bg_stats or {}),
            }
        )

        # update best
        if focus_stats.get("valid", False):
            self.valid_focus_evals += 1
            self._consec_invalid_mask = 0
            if (self.best_focus is None) or (focus > self.best_focus):
                self.best_focus = focus
                self.best_pos = dict(pos)
                self.best_focus_stats = {
                    "mask_pixels": int(focus_stats.get("mask_pixels", 0)),
                    "p90": float(focus_stats.get("p90", 0.0)),
                    "mean": float(focus_stats.get("mean", 0.0)),
                    "var": float(focus_stats.get("var", 0.0)),
                    "p90_ratio_to_background": (None if p90_ratio is None else float(p90_ratio)),
                }
        else:
            self.invalid_focus_evals += 1
            self._consec_invalid_mask += 1
            if self._consec_invalid_mask >= int(self.MAX_CONSEC_INVALID_MASK):
                self._abort_with_error(
                    "Focus ROI could not be detected consistently; verify nozzle stream visibility and rerun nozzle position."
                )
                return

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
            "result": {
                "best_focus": self.best_focus,
                "best_position": final,
                "focus_axis": "Y",
                "best_focus_stats": dict(self.best_focus_stats or {}),
                "valid_focus_evals": int(self.valid_focus_evals),
                "invalid_focus_evals": int(self.invalid_focus_evals),
            }
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
        ok, msg = self._assess_best_focus_quality()
        if not ok:
            self._abort_with_error(msg)
            return
        if self.best_pos is None:
            self.nozzleFocused.emit(); return
        cur = self.model.machine_model.get_current_position_dict()
        dY = self.best_pos["Y"] - cur["Y"]
        if dY == 0:
            self.nozzleFocused.emit(); return
        self._request_move_relative_with_timeout(
            (0, dY, 0),
            on_done=self.nozzleFocused.emit,
            timeout_ms=15_000,
            err_msg="Nozzle focus move-to-best timed out."
        )

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
                    self._request_move_relative_with_timeout(
                        (0, alt - cur["Y"], 0),
                        timeout_ms=15_000,
                        err_msg="Nozzle focus nudge move timed out."
                    )
                    return
                # nothing else to try → snap to best
                self._move_to_best_then_finish()
                return
            # pre-refine: just recapture
            self.calibration_manager.captureImageRequested.emit(self.handleDropletCaptured)
            return

        self._request_move_relative_with_timeout(
            (0, dY, 0),
            timeout_ms=15_000,
            err_msg="Nozzle focus step move timed out."
        )

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

    def _axis_y_bounds(self):
        try:
            bounds = self.model.machine_model.get_axis_bounds("Y")
            if isinstance(bounds, (tuple, list)) and len(bounds) == 2:
                lo = int(bounds[0]); hi = int(bounds[1])
                if lo > hi:
                    lo, hi = hi, lo
                return (lo, hi)
        except Exception:
            pass
        return None

    def _initialize_focus_bounds(self, start_y: int):
        lo = int(start_y - self.SAFE_SWEEP_STEPS)
        hi = int(start_y + self.SAFE_SWEEP_STEPS)
        axis_bounds = self._axis_y_bounds()
        if axis_bounds is not None:
            lo = max(lo, int(axis_bounds[0]))
            hi = min(hi, int(axis_bounds[1]))
        if lo > hi:
            lo = hi = int(start_y)
        self._loY = int(lo)
        self._hiY = int(hi)

    def _to_gray(self, image):
        if image is None:
            return None
        if image.ndim == 2:
            return image
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def _ensure_bg_g2_cache(self):
        if self.background_image is None:
            self._bg_g2_cache = None
            self._bg_cache_sig = None
            return None
        try:
            bg_gray = self._to_gray(self.background_image)
            if bg_gray is None:
                return None
            sig = (id(self.background_image), int(bg_gray.shape[0]), int(bg_gray.shape[1]))
            if self._bg_g2_cache is not None and self._bg_cache_sig == sig:
                return self._bg_g2_cache
            gx = cv2.Sobel(bg_gray, cv2.CV_64F, 1, 0, ksize=3)
            gy = cv2.Sobel(bg_gray, cv2.CV_64F, 0, 1, ksize=3)
            self._bg_g2_cache = gx * gx + gy * gy
            self._bg_cache_sig = sig
            return self._bg_g2_cache
        except Exception:
            self._bg_g2_cache = None
            self._bg_cache_sig = None
            return None

    def _compute_focus_stats(self, gray, mask, *, g2_precomputed=None):
        if mask is None:
            return {"valid": False, "reason": "missing_gray_or_mask", "mask_pixels": 0}
        try:
            roi_selector = mask > 0
            mask_pixels = int(np.count_nonzero(roi_selector))
            if mask_pixels < int(self.MIN_MASK_PIXELS):
                return {"valid": False, "reason": "mask_too_small", "mask_pixels": int(mask_pixels)}
            if g2_precomputed is not None:
                g2 = g2_precomputed
            else:
                if gray is None:
                    return {"valid": False, "reason": "missing_gray_or_mask", "mask_pixels": int(mask_pixels)}
                gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
                gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
                g2 = gx * gx + gy * gy
            roi = g2[roi_selector]
            if roi.size == 0:
                return {"valid": False, "reason": "empty_roi", "mask_pixels": int(mask_pixels)}
            var = float(np.var(roi))
            mean = float(np.mean(roi))
            p90 = float(np.percentile(roi, 90))
            if not (np.isfinite(var) and np.isfinite(mean) and np.isfinite(p90)):
                return {"valid": False, "reason": "non_finite_focus_metric", "mask_pixels": int(mask_pixels)}
            return {
                "valid": True,
                "reason": "ok",
                "mask_pixels": int(mask_pixels),
                "var": var,
                "mean": mean,
                "p90": p90,
            }
        except Exception as e:
            return {"valid": False, "reason": f"focus_stat_error:{e}", "mask_pixels": 0}

    def _assess_best_focus_quality(self):
        if self.best_pos is None:
            return False, "No valid focus ROI observed; rerun nozzle position/focus calibration."
        if int(self.valid_focus_evals) < int(self.MIN_VALID_FOCUS_EVALS):
            return (
                False,
                f"Insufficient valid focus samples ({self.valid_focus_evals}/{self.MIN_VALID_FOCUS_EVALS}); check stream visibility.",
            )
        ratio = (self.best_focus_stats or {}).get("p90_ratio_to_background")
        if ratio is None:
            return False, "Focus quality could not be normalized against background; reacquire nozzle/background and retry."
        ratio = float(ratio)
        if ratio < float(self.MIN_BEST_P90_BG_RATIO):
            return (
                False,
                f"Best focus quality too low (p90/bg={ratio:.2f} < {self.MIN_BEST_P90_BG_RATIO:.2f}).",
            )
        return True, ""

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

    def _draw_focus_overlay(self, img_bgr, mask, focus_value: float, p90_ratio: float | None = None):
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
            (f"P90/bg: {p90_ratio:.2f}" if p90_ratio is not None else "P90/bg: -"),
            f"Best: {self.best_focus:.0f}" if self.best_focus is not None else "Best: -",
        ]
        for i, line in enumerate(lines):
            cv2.putText(img_bgr, line, (8, 18 + i*18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 220, 20), 1, cv2.LINE_AA)

class DropletEmergenceCalibrationProcess(BaseCalibrationProcess):
    continueSearch = Signal()
    dropletDetected = Signal()
    replicateContinue = Signal()

    # ---- tuning / safety ----
    DELAY_MIN = 1500          # us
    DELAY_MAX = 8000          # us
    COARSE_STEP = 500
    FINE_STEP   = 100
    BIG_JUMP_US = 800         # used during visibility escalation
    MAX_EVALS   = 50
    REPLICATES  = 3
    MONO_TOL_FRAC = 0.10      # monotonic tolerance

    # acceptable area band (target window)
    MIN_AREA = 3000
    MAX_AREA = 8000

    # start-delay model vs pulse width (us)
    START_DELAY_BASE_US = 5000
    START_DELAY_REF_PW  = 3000
    START_DELAY_SLOPE   = 0.5   # +0.5 us delay per +1 us pulse width

    SETTINGS_TIMEOUT_MS = 10_000
    SEEK_REPLICATES = 1
    MIN_REPLICATES = 2
    MAX_REPLICATES = 3
    REPLICATE_CV_OK = 0.12
    REPLICATE_RANGE_OK = 900

    @staticmethod
    def missing_requirements(cm) -> list[str]:
        missing = []
        try:
            if cm.get_nozzle_center() is None:
                missing.append("nozzle center")
        except Exception:
            missing.append("nozzle center")
        try:
            if cm.get_nozzle_center_image_position() is None:
                missing.append("nozzle center image position")
        except Exception:
            missing.append("nozzle center image position")
        try:
            _ = cm.model.machine_model.get_current_position_dict()
        except Exception:
            missing.append("machine position feedback")
        try:
            _ = cm.model.droplet_camera_model.get_image_size()
        except Exception:
            missing.append("droplet camera")
        return missing

    def __init__(self, calibration_manager, model, parent=None):
        super().__init__(calibration_manager, model, parent)
        self.phase_name = "droplet_emergence"

        self.background_image = None
        self.droplet_image = None

        self.lower_delay = 2000
        self.upper_delay = 5000
        self.candidate_delay = 3000

        self.min_area = self.MIN_AREA
        self.max_area = self.MAX_AREA

        self.measurements = []
        self._eval_count = 0
        self._last_delay = None

        self._phase = "seek_visible"   # seek_visible -> scan_down -> fine_adjust
        self._prev_area = None

        self._rep_areas = []
        self._replicate_details = []
        self._last_agg_details = {}
        self._trend_noise_events = 0

        self.nozzle_center_px = self.calibration_manager.get_nozzle_center_image_position()
        self.selected_area = None
        self.selected_center_px = None
        self.selected_quality = {}

        self._orig_settings = None
        self._restored_settings = False

        # states
        self.state_prepare_background = QState()
        self.state_capture_background = QState()
        self.state_set_delay = QState()
        self.state_capture_droplet = QState()
        self.state_analyze = QState()
        self.state_final = QFinalState()

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

        t5b = QSignalTransition(); t5b.setSenderObject(self); t5b.setSignal(b"2replicateContinue()"); t5b.setTargetState(self.state_capture_droplet)
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
        self._replicate_details.clear()
        self._prev_area = None
        self._phase = "seek_visible"
        self._trend_noise_events = 0
        self._last_agg_details = {}
        self.nozzle_center_px = self.calibration_manager.get_nozzle_center_image_position()
        self.selected_area = None
        self.selected_center_px = None
        self.selected_quality = {}

        try:
            cur = self.calibration_manager.get_current_settings()
            self._orig_settings = {
                "num_droplets": int(cur.get("num_droplets")),
                "flash_delay": int(cur.get("flash_delay")),
            }
        except Exception:
            self._orig_settings = None
        self._restored_settings = False

        self.candidate_delay = self._compute_start_delay_for_pw()
        self.stageChanged.emit(f"Initial candidate delay (PW-adaptive): {self.candidate_delay} us")

        settings = {"num_droplets": 0}
        self._request_settings_with_timeout(
            settings,
            context="emergence_prepare_background",
            timeout_ms=self.SETTINGS_TIMEOUT_MS,
        )

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
        self.stageChanged.emit(f"Setting flash delay to {d} us  [phase={self._phase}]")
        settings = {"flash_delay": d, "num_droplets": 1}
        self._request_settings_with_timeout(
            settings,
            context=f"emergence_set_delay_{self._phase}",
            timeout_ms=self.SETTINGS_TIMEOUT_MS,
        )

    @Slot()
    def onCaptureDroplet(self):
        target_reps = int(self._required_replicates_for_phase())
        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text=f"Capturing droplet @ {self.candidate_delay} us (rep {len(self._rep_areas)+1}/{target_reps})",
            attempts_total=5,
            retry_delay_ms=75,
            guard_timeout_ms=10_000,
            final_error_msg=f"Failed to capture droplet at {self.candidate_delay} us."
        )

    @Slot()
    def onAnalyze(self):
        self.stageChanged.emit("Analyzing droplet image (emergence)")

        # Do not anchor emergence analysis to prior nozzle-position center.
        # The emergence contour center itself is used to refine nozzle center for pressure-band.
        area, center, overlay, details = self.model.droplet_camera_model.calc_emergence_area(
            self.background_image,
            self.droplet_image,
            return_details=True,
        )
        details = details or {}
        self.presentImageSignal.emit(overlay)
        self._eval_count += 1

        area_i = int(area) if area is not None else 0
        self._rep_areas.append(area_i)
        self._replicate_details.append({"area": area_i, "center": center, "details": details})

        self.stageChanged.emit(
            f"Delay {self.candidate_delay} us replicate -> area {area_i} "
            f"(class={details.get('contour_class', 'unknown')})"
        )

        required = int(self._required_replicates_for_phase())
        if len(self._rep_areas) < required and (not self._can_accept_replicates_early()):
            self.replicateContinue.emit()
            return

        agg_area, agg = self._aggregate_replicates()
        self._rep_areas.clear()
        self._replicate_details.clear()
        self.measurements.append((self.candidate_delay, agg_area))
        self._last_agg_details = dict(agg)

        self._record_analysis(
            {
                "process_name": "DropletEmergenceCalibrationProcess",
                "phase_name": str(self.phase_name or ""),
                "phase": str(self._phase),
                "eval_count": int(self._eval_count),
                "candidate_delay_us": int(self.candidate_delay),
                "aggregate_area": int(agg_area),
                "aggregate": dict(agg),
            }
        )

        if self._phase in ("scan_down", "fine_adjust") and self._prev_area is not None:
            if agg_area > (1.0 + self.MONO_TOL_FRAC) * float(self._prev_area):
                self._trend_noise_events += 1
                self._record_decision(
                    "non_monotonic_noise",
                    {
                        "prev_area": int(self._prev_area),
                        "agg_area": int(agg_area),
                        "trend_noise_events": int(self._trend_noise_events),
                    },
                )
                self.stageChanged.emit(
                    f"Non-monotonic area rise detected ({self._prev_area} -> {agg_area}); stepping earlier"
                )
                self._set_next_delay(self.candidate_delay - self.FINE_STEP)
                if self._eval_count >= self.MAX_EVALS:
                    self._fail("Emergence search did not converge (max evaluations)")
                    return
                self.continueSearch.emit()
                return

        if self._phase == "seek_visible":
            visible_thresh = max(40, int(0.03 * self.MIN_AREA))
            cls = str(agg.get("contour_class", "none"))
            if agg_area <= visible_thresh or cls == "none":
                next_delay = self.candidate_delay + self.BIG_JUMP_US
                self._record_decision(
                    "seek_visible_increase_delay",
                    {
                        "agg_area": int(agg_area),
                        "visible_thresh": int(visible_thresh),
                        "next_delay": int(next_delay),
                    },
                )
                self.stageChanged.emit(f"No emergence contour; escalating delay to {next_delay} us")
                if next_delay > self.DELAY_MAX:
                    self._fail("No emergence detected up to maximum delay")
                    return
                self._set_next_delay(next_delay)
                self.continueSearch.emit()
                return

            self._record_decision(
                "seek_visible_found_signal",
                {"agg_area": int(agg_area), "class": cls},
            )
            self._prev_area = agg_area
            self._phase = "scan_down"
            self._set_next_delay(self.candidate_delay - self.COARSE_STEP)
            self.continueSearch.emit()
            return

        # Area-band is the primary convergence criterion for emergence timing.
        # Keep contour classification as diagnostics rather than a hard reject gate.
        if self.MIN_AREA <= agg_area <= self.MAX_AREA:
            self._finish_success(agg_area, agg)
            return

        if self._phase == "scan_down":
            if agg_area > self.MAX_AREA:
                self._prev_area = agg_area
                self._set_next_delay(self.candidate_delay - self.COARSE_STEP)
                if self._eval_count >= self.MAX_EVALS:
                    self._fail("Emergence search did not converge (max evaluations)")
                    return
                self.continueSearch.emit()
                return

            self._phase = "fine_adjust"
            self._set_next_delay(self.candidate_delay + self.FINE_STEP)
            self.continueSearch.emit()
            return

        if self._phase == "fine_adjust":
            if agg_area < self.MIN_AREA:
                self._set_next_delay(self.candidate_delay + self.FINE_STEP)
            elif agg_area > self.MAX_AREA:
                self._set_next_delay(self.candidate_delay - self.FINE_STEP)
            else:
                self._finish_success(agg_area, agg)
                return

            if self._eval_count >= self.MAX_EVALS:
                self._fail("Emergence fine-adjust did not converge (max evaluations)")
                return
            self.continueSearch.emit()

    # ---------- completion ----------
    @Slot()
    def onCalibrationCompleted(self):
        self.stageChanged.emit("Droplet emergence calibration complete")
        self._restore_original_settings_best_effort()
        self.calibrationDataUpdated.emit(
            {
                "measurements": self.measurements,
                "result": {
                    "flash_delay": int(self.candidate_delay),
                    "area": (None if self.selected_area is None else int(self.selected_area)),
                    "selected_center_px": self.selected_center_px,
                    "pressure_band_nozzle_center_px": self.selected_center_px,
                    "selected_quality": dict(self.selected_quality or {}),
                    "phase": str(self._phase),
                    "trend_noise_events": int(self._trend_noise_events),
                },
            }
        )
        self.calibrationCompleted.emit()

    # ---------- helpers ----------

    def handleDropletCaptured(self, img):
        self.calibration_manager.emitCaptureCompleted()

    def _fail(self, msg: str):
        self._restore_original_settings_best_effort()
        self.calibrationError.emit(str(msg))

    def _request_settings_with_timeout(self, settings: dict, *, context: str, timeout_ms: int):
        done = {"fired": False}
        t_ref = {"t": None}

        def _finish(ok: bool, why: str):
            if done["fired"]:
                return
            done["fired"] = True
            self._cancel_timeout(t_ref["t"])
            t_ref["t"] = None
            if not ok:
                self._fail(f"Settings apply failed during {context}: {why}")
                return
            self.calibration_manager.emitSettingsChangeCompleted()

        t_ref["t"] = self._start_timeout(
            int(timeout_ms),
            on_timeout=lambda: _finish(False, "timeout"),
        )
        self._request_settings_with_recording(
            settings,
            lambda *args, **kwargs: _finish(True, "callback"),
            context=context,
        )

    def _required_replicates_for_phase(self) -> int:
        if self._phase == "seek_visible":
            return int(self.SEEK_REPLICATES)
        return int(self.MAX_REPLICATES)

    def _can_accept_replicates_early(self) -> bool:
        n = len(self._rep_areas)
        if n < int(self.MIN_REPLICATES):
            return False
        if n >= int(self.MAX_REPLICATES):
            return True
        arr = np.asarray(self._rep_areas, dtype=float)
        m = float(arr.mean()) if arr.size else 0.0
        s = float(arr.std()) if arr.size else 0.0
        cv = (s / max(abs(m), 1.0))
        span = float(arr.max() - arr.min()) if arr.size else 0.0
        return (cv <= float(self.REPLICATE_CV_OK)) and (span <= float(self.REPLICATE_RANGE_OK))

    def _aggregate_replicates(self):
        areas = [int(v) for v in self._rep_areas]
        agg_area = int(median(areas)) if areas else 0

        classes = [str((r.get("details") or {}).get("contour_class", "none")) for r in self._replicate_details]
        class_counts = Counter(classes)
        cls = class_counts.most_common(1)[0][0] if class_counts else "none"

        centers = [r.get("center") for r in self._replicate_details if r.get("center") is not None]
        center = None
        if centers:
            xs = [int(c[0]) for c in centers]
            ys = [int(c[1]) for c in centers]
            center = (int(median(xs)), int(median(ys)))

        contour_areas = [float((r.get("details") or {}).get("contour_area", 0.0)) for r in self._replicate_details]
        bbox_areas = [float((r.get("details") or {}).get("bbox_area", 0.0)) for r in self._replicate_details]
        p95s = [float((r.get("details") or {}).get("p95", 0.0)) for r in self._replicate_details]

        arr = np.asarray(areas, dtype=float) if areas else np.asarray([0.0], dtype=float)
        m = float(arr.mean())
        s = float(arr.std())
        cv = float(s / max(abs(m), 1.0))
        span = float(arr.max() - arr.min())

        summary = {
            "contour_class": cls,
            "center": center,
            "contour_area": float(median(contour_areas)) if contour_areas else 0.0,
            "bbox_area": float(median(bbox_areas)) if bbox_areas else 0.0,
            "p95": float(median(p95s)) if p95s else 0.0,
            "replicate_count": int(len(areas)),
            "replicate_areas": areas,
            "replicate_cv": cv,
            "replicate_range": span,
        }
        return agg_area, summary

    def _finish_success(self, agg_area: int, agg: dict):
        self.stageChanged.emit("Target area window reached")
        machine_pos = self.model.machine_model.get_current_position_dict()
        # Keep nozzle image center from nozzle-position calibration; publish emergence-refined
        # center separately for pressure-band classification.
        self.calibration_manager.set_nozzle_center(machine_pos)

        self.selected_area = int(agg_area)
        self.selected_center_px = agg.get("center")
        self.selected_quality = dict(agg or {})
        if self.selected_center_px is not None and hasattr(self.calibration_manager, "set_emergence_nozzle_center_image_position"):
            try:
                cx, cy = self.selected_center_px
                self.calibration_manager.set_emergence_nozzle_center_image_position((int(cx), int(cy)))
            except Exception:
                pass

        self._record_decision(
            "emergence_target_reached",
            {
                "flash_delay": int(self.candidate_delay),
                "aggregate_area": int(agg_area),
                "quality": dict(agg or {}),
            },
        )
        self.dropletDetected.emit()

    def _restore_original_settings_best_effort(self):
        if self._restored_settings:
            return
        self._restored_settings = True
        if not isinstance(self._orig_settings, dict):
            return
        restore = {}
        if "num_droplets" in self._orig_settings:
            try:
                restore["num_droplets"] = int(self._orig_settings["num_droplets"])
            except Exception:
                pass
        if "flash_delay" in self._orig_settings:
            try:
                restore["flash_delay"] = int(self._orig_settings["flash_delay"])
            except Exception:
                pass
        if not restore:
            return
        try:
            self._request_settings_with_recording(restore, lambda *args, **kwargs: None, context="emergence_restore_settings")
        except Exception:
            pass

    def _set_next_delay(self, d: int):
        d = int(self._clamp_delay(d))
        self._last_delay = self.candidate_delay
        self.candidate_delay = d
        self.stageChanged.emit(f"Next candidate delay: {self.candidate_delay} us")

    def _clamp_delay(self, d: int) -> int:
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
        self._request_move_absolute_with_timeout(
            nozzle_vector,
            timeout_ms=15_000,
            err_msg="Pressure calibration initial move timed out."
        )

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
                 *,
                 min_reps: int = 5,
                 escalate_to: int = 9,
                 classification_delay_us: int | None = None,
                 reverse_order: bool = True,
                 safety_clearance_px: int = 350,
                 auto_stop_on_nozzle_wet: bool = True,
                 parent=None):
        super().__init__(calibration_manager, model, parent)

        missing_requirements = PressureBandCalibrationProcess.missing_requirements(calibration_manager)
        if missing_requirements:
            raise ValueError(f"PressureBandCalibrationProcess requires: {', '.join(missing_requirements)}.")
        
        self.phase_name = "pressure_scan"

        # --- prerequisites ---
        self.start_pressure     = self.calibration_manager.get_start_pressure()
        get_ps_center = getattr(self.calibration_manager, "get_pressure_scan_nozzle_center_image_position", None)
        if callable(get_ps_center):
            self.nozzle_center_px = get_ps_center()
        else:
            self.nozzle_center_px = self.calibration_manager.get_nozzle_center_image_position()
        get_ps_source = getattr(self.calibration_manager, "get_pressure_scan_nozzle_center_source", None)
        self.nozzle_center_source = str(get_ps_source()) if callable(get_ps_source) else "legacy"
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
            classification_delay_us = int(max(0, (self.emergence_time_us or 0) + pw + 1000))
        self.classify_delay_us = int(classification_delay_us)
        self._base_classify_delay_us = int(self.classify_delay_us)
        self._active_classify_delay_us = int(self.classify_delay_us)
        self.delay_retest_step_us = 500
        self.delay_retest_min_us = 2000
        self.delay_retest_max_earlier_steps = 1
        self.delay_retest_max_later_steps = 2
        self.delay_retest_max_later_offset_us = 1000
        self.delay_retest_abs_max_us = 20_000
        self.delay_retest_timeout_ms = 15_000
        self._delay_retest_done_for_pressure = False
        self._delay_retest_steps_done_for_pressure = 0
        self._delay_retest_earlier_steps_done_for_pressure = 0
        self._delay_retest_later_steps_done_for_pressure = 0
        self._delay_retest_in_progress = False
        self._delay_retest_context = None

        # --- pressure bounds ---
        try:
            hw_lo, hw_hi = self.model.machine_model.get_print_pressure_bounds()
        except Exception:
            hw_lo, hw_hi = 0.3, 5.0
        self.P_MIN = float(hw_lo)
        self.P_MAX = float(hw_hi)

        # Requested scan range (we still honor the user’s start/end direction)
        # p0, p1 = float(min(p_start, p_end)), float(max(p_start, p_end))
        # self._p_lo = max(self.P_MIN, p0)
        # self._p_hi = min(self.P_MAX, p1)

        # ---- Adaptive step settings ----
        # base_step = abs(float(p_step)) if p_step else 0.1
        self.dp_min = 0.01                         # smallest step when near nozzle
        self.dp_max = 0.05                         # largest allowed step
        # self.dp     = max(self.dp_min, min(base_step, self.dp_max))
        self.dp     = max(self.dp_min, self.dp_max)

        # Special jumps for specific states
        self.multiple_big_step = 0.10              # when MULTIPLE → drop faster
        self.none_jump_up      = 0.10              # when NONE → push up to re-acquire
        
        # Movement heuristics (pixels)
        self.small_move_px = 8                    # “barely moved” threshold
        self.large_move_px = 40                    # “moved a lot” threshold

        # --- thresholds & safety ---
        self.nozzle_area_threshold     = 8000
        self.pre_ejection_attached_area_px = 8000
        self.pre_ejection_attached_ratio = 0.60
        self.safety_clearance_px       = int(safety_clearance_px)
        self.near_nozzle_px            = int(self.safety_clearance_px * 1.6)
        self.far_nozzle_px             = int(self.safety_clearance_px * 3.0)
        self.auto_stop_on_nozzle_wet   = bool(auto_stop_on_nozzle_wet)

        # --- replicate policy ---
        self.min_reps           = int(min_reps)
        self.escalate_to        = max(int(escalate_to), self.min_reps)
        self.replicates_target  = self.min_reps
        self.reps               = []
        self._invalid_skip_count = 0
        self._invalid_skip_cap   = 6
        self._discard_next       = True   # skip first frame after pressure change (settling)
        # Confidence gates reduce overreaction to single noisy replicates.
        self.single_confidence_min = 0.70
        self.none_confidence_min = 0.70
        self.multiple_confidence_min = 0.40
        self.multiple_min_count = 2
        # Guard against false "single" at high pressure when extra droplets leave FOV.
        self.fast_single_bottom_margin_px = 220
        self.fast_single_risk_fraction = 0.60
        self.fast_single_risk_min_count = 3
        self.fast_single_dy_threshold_px = int(self.far_nozzle_px)

        # --- outputs ---
        self.samples          = []
        self.annotated_image  = None

        # --- flags ---
        self._current_pressure   = None
        self._next_pressure        = float(self.start_pressure)  # start at the starting pressure
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
        self._seek_upper_steps = 0
        self._seek_upper_max_steps = 10
        self._seek_upper_max_span_psi = 0.80

        # Upward re-acquire params (used if first verdict is NONE or “too close”)
        self._reacquire_step = 0.10
        self._reacquire_step_max = 0.30
        self._reacquire_growth = 1.7
        self._reacquire_steps_taken = 0
        self._reacquire_max_steps = 18

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
        self.stageChanged.emit(
            f"Pressure scan: preparing background (num_droplets=0, nozzle_center_source={self.nozzle_center_source})"
        )
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
            fallback = (self._current_pressure if self._current_pressure is not None else self.start_pressure)
            fallback = float(max(self.P_MIN, min(self.P_MAX, fallback - max(self.dp, self.dp_min))))
            self._next_pressure = fallback

        # If we’ve scanned below the requested low bound, finish
        if self._next_pressure < (self.P_MIN - 1e-6):
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
        self._active_classify_delay_us = int(self._base_classify_delay_us)
        self._delay_retest_done_for_pressure = False
        self._delay_retest_steps_done_for_pressure = 0
        self._delay_retest_earlier_steps_done_for_pressure = 0
        self._delay_retest_later_steps_done_for_pressure = 0
        self._delay_retest_in_progress = False
        self._delay_retest_context = None

        settings = {
            "print_pressure": self._current_pressure,
            "num_droplets": 1,
            "flash_delay": int(self._active_classify_delay_us),
        }
        self.stageChanged.emit(
            f"Set pressure={self._current_pressure:.3f} psi; delay={self._active_classify_delay_us} μs"
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
            if str(getattr(self, "_phase", "")) == "reacquire_up":
                self.stageChanged.emit(
                    f"Re-acquire sample too close to nozzle (dy={int(dy_min)} px); continuing upward scan"
                )
                self._record_decision(
                    "reacquire_near_nozzle_reclassified_none",
                    {
                        "pressure_psi": float(self._current_pressure),
                        "dy_min_px": int(dy_min),
                        "safety_clearance_px": int(self.safety_clearance_px),
                    },
                )
                cls = "none"
                dy_min = None
            elif self._prev_verdict is None:
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
            "frame_height_px": int(self.droplet_image.shape[0]) if getattr(self, "droplet_image", None) is not None else None,
            "flash_delay_us": int(
                getattr(self, "_active_classify_delay_us", getattr(self, "classify_delay_us", 0))
            ),
        }
        self.reps.append(rep)
        self.replicateReady.emit()
    @Slot()
    def onDecide(self):
        counts, total = self._replicate_class_counts()
        if total < self.min_reps:
            self.replicates_target = self.min_reps
            self.continueReplicate.emit()
            return

        verdict, confidence, decision = self._classify_replicate_outcome(counts, total)
        if verdict == "single":
            risk = self._single_exit_risk_summary()
            has_upper_multi = self._has_multiple_at_or_above_current_pressure()
            decision["single_exit_risk"] = dict(risk)
            decision["has_upper_multiple_evidence"] = bool(has_upper_multi)
            if (
                bool(has_upper_multi)
                and int(risk.get("risky_single_count", 0)) >= int(self.fast_single_risk_min_count)
                and float(risk.get("risky_single_fraction", 0.0)) >= float(self.fast_single_risk_fraction)
            ):
                verdict = "multiple"
                confidence = max(float(confidence), float(risk.get("risky_single_fraction", 0.0)))
                decision["reason"] = "single_exit_risk_override"
                decision["override_from"] = "single"

        timing = self._attached_timing_summary()
        decision["attached_timing"] = dict(timing)
        if self._should_shift_delay_later_for_attached(verdict, counts, timing):
            if self._start_delay_retest(
                "attached_stream_requires_later_delay",
                verdict,
                counts,
                decision,
                confidence,
                direction="later",
            ):
                return
            msg = (
                f"Unable to resolve pre-ejection attached-stream timing "
                f"@ {self._current_pressure:.3f} psi."
            )
            self._record_error(
                msg,
                {
                    "pressure_psi": float(self._current_pressure),
                    "active_delay_us": int(getattr(self, "_active_classify_delay_us", 0)),
                    "base_delay_us": int(getattr(self, "_base_classify_delay_us", 0)),
                    "attached_timing": dict(timing),
                },
            )
            self.calibrationError.emit(msg)
            self.finalize.emit()
            return

        retest_reason = self._should_run_delay_retest(verdict, counts, decision)
        if retest_reason is not None:
            if self._start_delay_retest(retest_reason, verdict, counts, decision, confidence):
                return

        if verdict == "ambiguous" and total < self.escalate_to:
            self.replicates_target = self.escalate_to
            self.stageChanged.emit(
                f"Pressure {self._current_pressure:.3f} psi ambiguous "
                f"(single={counts['single']}, none={counts['none']}, multiple={counts['multiple']}); "
                f"collecting up to {self.escalate_to} reps"
            )
            self.continueReplicate.emit()
            return

        if verdict == "ambiguous":
            verdict = self._fallback_verdict_from_counts(counts)
            decision["reason"] = "ambiguous_fallback"
            decision["fallback_verdict"] = verdict

        verdict, confidence, decision = self._merge_delay_retest_decision(
            verdict,
            confidence,
            counts,
            decision,
        )

        base_delay_us = int(getattr(self, "_base_classify_delay_us", getattr(self, "classify_delay_us", 0)))
        active_delay_us = int(getattr(self, "_active_classify_delay_us", base_delay_us))
        retest_ctx = dict(getattr(self, "_delay_retest_context", {}) or {})

        decision.update(
            {
                "class_counts": dict(counts),
                "class_fractions": dict(decision.get("fractions") or {}),
                "confidence": float(confidence),
                "total_reps": int(total),
                "classify_delay_us": int(active_delay_us),
                "base_classify_delay_us": int(base_delay_us),
                "delay_retest_applied": bool(int(active_delay_us) != int(base_delay_us)),
                "delay_retest_steps_done": int(getattr(self, "_delay_retest_steps_done_for_pressure", 0)),
                "delay_retest_earlier_steps_done": int(
                    getattr(self, "_delay_retest_earlier_steps_done_for_pressure", 0)
                ),
                "delay_retest_later_steps_done": int(
                    getattr(self, "_delay_retest_later_steps_done_for_pressure", 0)
                ),
            }
        )
        if retest_ctx:
            decision.setdefault("retest_trigger_reason", str(retest_ctx.get("trigger_reason", "")))
            decision.setdefault("retest_prior_verdict", str(retest_ctx.get("prior_verdict", "")))
        escalated = total > self.min_reps
        self._store_pressure_summary(verdict, escalated=escalated, decision=decision)
        self._record_decision(
            "pressure_scan_verdict",
            {
                "pressure_psi": float(self._current_pressure),
                "verdict": str(verdict),
                "decision": dict(decision),
            },
        )
        self._apply_verdict_and_advance(verdict)

    @Slot()
    def onCalibrationCompleted(self):
        bands = self._compute_single_bands()
        if not bands:
            msg = "Pressure scan found no valid single-droplet pressure band."
            self._record_error(
                msg,
                {
                    "pressure_count": int(len(self.samples)),
                    "start_pressure": float(self.start_pressure),
                    "pressure_bounds": [float(self.P_MIN), float(self.P_MAX)],
                },
            )
            self.calibrationError.emit(msg)
            return

        result = {
            "pulse_width_us": self._pulse_width_us,
            "delay_us": int(self.classify_delay_us),
            "start_pressure": float(self.start_pressure),
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

    def _replicate_class_counts(self):
        counts = {"none": 0, "single": 0, "multiple": 0}
        for r in self.reps:
            cls = str(r.get("cls", ""))
            if cls in counts:
                counts[cls] += 1
        total = int(sum(counts.values()))
        return counts, total

    @staticmethod
    def _class_fractions_from_counts(counts: dict, total: int):
        if int(total) <= 0:
            return {"none": 0.0, "single": 0.0, "multiple": 0.0}
        d = float(total)
        return {
            "none": float(counts.get("none", 0)) / d,
            "single": float(counts.get("single", 0)) / d,
            "multiple": float(counts.get("multiple", 0)) / d,
        }

    def _classify_replicate_outcome(self, counts: dict, total: int):
        fr = self._class_fractions_from_counts(counts, total)
        p_none = float(fr["none"])
        p_single = float(fr["single"])
        p_multiple = float(fr["multiple"])

        # Treat "multiple" conservatively, but require repeat evidence to ignore one-off noise.
        if int(counts.get("multiple", 0)) >= int(self.multiple_min_count) and p_multiple >= float(self.multiple_confidence_min):
            return "multiple", p_multiple, {"reason": "multiple_confident", "fractions": fr}

        # For single/none, only declare confidence if no multiple was observed.
        if int(counts.get("multiple", 0)) == 0 and p_single >= float(self.single_confidence_min):
            return "single", p_single, {"reason": "single_confident", "fractions": fr}
        if int(counts.get("multiple", 0)) == 0 and p_none >= float(self.none_confidence_min):
            return "none", p_none, {"reason": "none_confident", "fractions": fr}

        top = max(fr.items(), key=lambda kv: kv[1])
        return "ambiguous", float(top[1]), {"reason": "insufficient_confidence", "fractions": fr}

    def _fallback_verdict_from_counts(self, counts: dict):
        # Conservative deterministic fallback at replicate cap.
        if int(counts.get("multiple", 0)) >= int(self.multiple_min_count):
            return "multiple"
        if int(counts.get("single", 0)) > int(counts.get("none", 0)):
            return "single"
        return "none"

    def _apply_verdict_and_advance(self, verdict: str):
        if self._maybe_start_or_update_brackets(verdict):
            self._prev_verdict = verdict
            self._prev_pressure = self._current_pressure
            self._advance_or_finish()
            return
        self._choose_next_pressure(verdict)
        self._prev_verdict = verdict
        self._prev_pressure = self._current_pressure
        self._advance_or_finish()

    def _has_multiple_at_or_above_current_pressure(self) -> bool:
        cur = float(self._current_pressure) if self._current_pressure is not None else None
        if cur is None:
            return False
        for rec in self.samples:
            if str(rec.get("verdict", "")) != "multiple":
                continue
            try:
                p = float(rec.get("pressure"))
            except Exception:
                continue
            if p >= (cur - 1e-9):
                return True
        return False

    def _single_exit_risk_summary(self):
        singles = [r for r in self.reps if str(r.get("cls", "")) == "single"]
        if not singles:
            return {
                "single_count": 0,
                "risky_single_count": 0,
                "risky_single_fraction": 0.0,
            }

        risky = 0
        for r in singles:
            dy = r.get("dy_min_px")
            c = r.get("center_px")
            fh = r.get("frame_height_px")
            by_dy = (dy is not None) and (int(dy) >= int(self.fast_single_dy_threshold_px))
            by_bottom = False
            if (
                fh is not None
                and c is not None
                and isinstance(c, (tuple, list))
                and len(c) >= 2
            ):
                try:
                    cy = int(c[1])
                    by_bottom = cy >= max(0, int(fh) - int(self.fast_single_bottom_margin_px))
                except Exception:
                    by_bottom = False
            if by_dy or by_bottom:
                risky += 1

        n = len(singles)
        return {
            "single_count": int(n),
            "risky_single_count": int(risky),
            "risky_single_fraction": (float(risky) / float(n)) if n > 0 else 0.0,
            "dy_threshold_px": int(self.fast_single_dy_threshold_px),
            "bottom_margin_px": int(self.fast_single_bottom_margin_px),
        }

    def _attached_timing_summary(self):
        reps = list(getattr(self, "reps", []) or [])
        total = int(len(reps))
        if total <= 0:
            return {
                "total_reps": 0,
                "attached_hits": 0,
                "attached_ratio": 0.0,
                "attached_single_hits": 0,
                "attached_none_hits": 0,
                "attached_area_median_px": 0,
                "attached_area_threshold_px": int(getattr(self, "pre_ejection_attached_area_px", 8000)),
                "attached_ratio_threshold": float(getattr(self, "pre_ejection_attached_ratio", 0.60)),
                "attached_dominant": False,
            }

        threshold_px = int(getattr(self, "pre_ejection_attached_area_px", 8000))
        ratio_threshold = float(getattr(self, "pre_ejection_attached_ratio", 0.60))
        attached_hits = 0
        attached_single_hits = 0
        attached_none_hits = 0
        attached_areas = []
        for r in reps:
            cls = str(r.get("cls", ""))
            area = int(r.get("nozzle_attached_area") or 0)
            wet = bool(r.get("nozzle_wet"))
            attached = wet or (area >= threshold_px)
            if not attached:
                continue
            attached_hits += 1
            attached_areas.append(area)
            if cls == "single":
                attached_single_hits += 1
            elif cls == "none":
                attached_none_hits += 1

        from statistics import median

        attached_ratio = (float(attached_hits) / float(total)) if total > 0 else 0.0
        area_med = int(median(attached_areas)) if attached_areas else 0
        attached_dominant = bool(
            attached_ratio >= ratio_threshold and (attached_single_hits > 0 or attached_none_hits > 0)
        )
        return {
            "total_reps": int(total),
            "attached_hits": int(attached_hits),
            "attached_ratio": float(attached_ratio),
            "attached_single_hits": int(attached_single_hits),
            "attached_none_hits": int(attached_none_hits),
            "attached_area_median_px": int(area_med),
            "attached_area_threshold_px": int(threshold_px),
            "attached_ratio_threshold": float(ratio_threshold),
            "attached_dominant": bool(attached_dominant),
        }

    def _should_shift_delay_later_for_attached(self, verdict: str, counts: dict, timing: dict):
        if not bool((timing or {}).get("attached_dominant", False)):
            return False
        if str(verdict) == "multiple":
            return False

        n_single = int((counts or {}).get("single", 0))
        n_multiple = int((counts or {}).get("multiple", 0))
        base = int(getattr(self, "_base_classify_delay_us", getattr(self, "classify_delay_us", 0)))
        active = int(getattr(self, "_active_classify_delay_us", base))
        # If current delay is already earlier than base, attached-dominant behavior is
        # strong evidence of pre-ejection timing (move later).
        if active < base:
            return True
        # Otherwise require some free-droplet evidence so pure NONE-at-low-pressure does
        # not force delay growth.
        return bool(n_single > 0 or n_multiple > 0)

    def _earlier_delay_candidate_us(self):
        base = int(getattr(self, "_base_classify_delay_us", getattr(self, "classify_delay_us", 0)))
        cur = int(getattr(self, "_active_classify_delay_us", base))
        step = int(max(0, getattr(self, "delay_retest_step_us", 500)))
        min_delay = int(max(0, getattr(self, "delay_retest_min_us", 2000)))
        candidate = int(max(min_delay, cur - step))
        if candidate >= cur:
            return None
        return candidate

    def _later_delay_candidate_us(self):
        base = int(getattr(self, "_base_classify_delay_us", getattr(self, "classify_delay_us", 0)))
        cur = int(getattr(self, "_active_classify_delay_us", base))
        step = int(max(0, getattr(self, "delay_retest_step_us", 500)))
        max_offset = int(max(0, getattr(self, "delay_retest_max_later_offset_us", 1000)))
        abs_max = int(max(base, getattr(self, "delay_retest_abs_max_us", 20_000)))
        if step <= 0:
            return None

        # First move back toward base, then allow limited extension past base.
        if cur < base:
            candidate = min(base, cur + step)
        else:
            candidate = min(cur + step, base + max_offset)
        candidate = int(min(candidate, abs_max))
        if candidate <= cur:
            return None
        return candidate

    def _should_run_delay_retest(self, verdict: str, counts: dict, decision: dict):
        steps_done = int(max(0, getattr(self, "_delay_retest_earlier_steps_done_for_pressure", 0)))
        steps_max = int(max(0, getattr(self, "delay_retest_max_earlier_steps", 1)))
        if steps_max <= 0 or steps_done >= steps_max:
            return None
        if self._earlier_delay_candidate_us() is None:
            return None

        n_single = int((counts or {}).get("single", 0))
        n_multiple = int((counts or {}).get("multiple", 0))
        if n_single > 0 and n_multiple > 0:
            return "mixed_single_multiple"
        if str(verdict) == "single" and bool((decision or {}).get("has_upper_multiple_evidence", False)):
            return "edge_single_with_upper_multiple"

        return None

    def _merge_delay_retest_decision(self, verdict: str, confidence: float, counts: dict, decision: dict):
        ctx = dict(getattr(self, "_delay_retest_context", {}) or {})
        if not ctx:
            return verdict, confidence, decision

        prior_verdict = str(ctx.get("prior_verdict", ""))
        prior_counts = dict(ctx.get("prior_counts", {}) or {})
        prior_conf = float(ctx.get("prior_confidence", 0.0))
        prior_reason = str(ctx.get("prior_reason", ""))
        trigger_reason = str(ctx.get("trigger_reason", ""))
        prior_multiple = int(prior_counts.get("multiple", 0))
        had_multiple_evidence = (prior_verdict == "multiple") or (prior_multiple > 0)

        if had_multiple_evidence and str(verdict) == "single":
            # Conservative fusion: do not allow a retest single to erase
            # earlier multiple evidence at the same pressure.
            decision["reason"] = "retest_conflict_keep_multiple"
            decision["override_from"] = "single"
            decision["retest_trigger_reason"] = str(trigger_reason)
            decision["retest_prior_verdict"] = str(prior_verdict)
            decision["retest_prior_reason"] = str(prior_reason)
            decision["retest_prior_counts"] = dict(prior_counts)
            verdict = "multiple"
            confidence = max(float(confidence), float(prior_conf), float(self.multiple_confidence_min))
        elif (prior_verdict == "single") and (str(verdict) == "multiple"):
            decision["reason"] = "retest_conflict_multiple_wins"
            decision["retest_trigger_reason"] = str(trigger_reason)
            decision["retest_prior_verdict"] = str(prior_verdict)
            decision["retest_prior_reason"] = str(prior_reason)
            confidence = max(float(confidence), float(prior_conf))

        return verdict, confidence, decision

    def _start_delay_retest(
        self,
        reason: str,
        verdict: str,
        counts: dict,
        decision: dict,
        confidence: float,
        direction: str = "earlier",
    ):
        direction = str(direction or "earlier").strip().lower()
        if direction not in ("earlier", "later"):
            direction = "earlier"

        if direction == "later":
            steps_done = int(max(0, getattr(self, "_delay_retest_later_steps_done_for_pressure", 0)))
            steps_max = int(max(0, getattr(self, "delay_retest_max_later_steps", 2)))
            if steps_max <= 0 or steps_done >= steps_max:
                return False
            new_delay = self._later_delay_candidate_us()
        else:
            steps_done = int(max(0, getattr(self, "_delay_retest_earlier_steps_done_for_pressure", 0)))
            steps_max = int(max(0, getattr(self, "delay_retest_max_earlier_steps", 1)))
            if steps_max <= 0 or steps_done >= steps_max:
                return False
            new_delay = self._earlier_delay_candidate_us()

        if new_delay is None:
            return False

        self._delay_retest_done_for_pressure = True
        self._delay_retest_steps_done_for_pressure = int(
            max(0, getattr(self, "_delay_retest_steps_done_for_pressure", 0)) + 1
        )
        if direction == "later":
            self._delay_retest_later_steps_done_for_pressure = int(
                max(0, getattr(self, "_delay_retest_later_steps_done_for_pressure", 0)) + 1
            )
        else:
            self._delay_retest_earlier_steps_done_for_pressure = int(
                max(0, getattr(self, "_delay_retest_earlier_steps_done_for_pressure", 0)) + 1
            )

        self._delay_retest_in_progress = True
        if not getattr(self, "_delay_retest_context", None):
            self._delay_retest_context = {
                "trigger_reason": str(reason),
                "prior_verdict": str(verdict),
                "prior_counts": dict(counts or {}),
                "prior_decision": dict(decision or {}),
                "prior_confidence": float(confidence),
                "prior_reason": str((decision or {}).get("reason", "")),
            }
        prev_delay = int(
            getattr(self, "_active_classify_delay_us", getattr(self, "classify_delay_us", 0))
        )
        self._active_classify_delay_us = int(new_delay)
        self.reps = []
        self.replicates_target = int(self.min_reps)
        self._invalid_skip_count = 0
        self._discard_next = True

        self.stageChanged.emit(
            f"Pressure {self._current_pressure:.3f} psi {str(reason).replace('_', ' ')}; "
            f"retesting at {direction} delay {self._active_classify_delay_us} us"
        )
        self._record_decision(
            "pressure_step_delay_retest",
            {
                "pressure_psi": float(self._current_pressure),
                "reason": str(reason),
                "direction": str(direction),
                "from_delay_us": int(prev_delay),
                "to_delay_us": int(self._active_classify_delay_us),
                "prior_verdict": str(verdict),
                "class_counts": dict(counts or {}),
                "decision_reason": str((decision or {}).get("reason", "")),
                "retest_step": int(getattr(self, "_delay_retest_steps_done_for_pressure", 0)),
                "retest_step_direction": int(
                    getattr(
                        self,
                        "_delay_retest_later_steps_done_for_pressure" if direction == "later"
                        else "_delay_retest_earlier_steps_done_for_pressure",
                        0,
                    )
                ),
            },
        )

        done = {"fired": False}
        t_ref = {"t": None}

        def _finish(ok: bool, why: str):
            if done["fired"]:
                return
            done["fired"] = True
            self._cancel_timeout(t_ref["t"])
            t_ref["t"] = None
            self._delay_retest_in_progress = False
            if not ok:
                msg = (
                    f"Failed to apply delay retest settings @ {self._current_pressure:.3f} psi "
                    f"({why})"
                )
                self._record_error(
                    msg,
                    {
                        "pressure_psi": float(self._current_pressure),
                        "to_delay_us": int(self._active_classify_delay_us),
                        "reason": str(reason),
                        "direction": str(direction),
                    },
                )
                self.calibrationError.emit(msg)
                self.finalize.emit()
                return
            self.continueReplicate.emit()

        t_ref["t"] = self._start_timeout(
            int(getattr(self, "delay_retest_timeout_ms", 15_000)),
            on_timeout=lambda: _finish(False, "timeout"),
        )
        self._request_settings_with_recording(
            {"flash_delay": int(self._active_classify_delay_us), "num_droplets": 1},
            lambda *args, **kwargs: _finish(True, "callback"),
            context=f"pressure_delay_retest:{reason}:{direction}",
        )
        return True
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

    def _store_pressure_summary(self, verdict: str, escalated: bool, decision: dict | None = None):
        counts, total = self._replicate_class_counts()
        fractions = self._class_fractions_from_counts(counts, total)
        decision = dict(decision or {})
        rec = {
            "pressure": float(self._current_pressure),
            "n_reps": len(self.reps),
            "escalated": bool(escalated),
            "verdict": verdict,
            "dy_min_px_med": self._median_dy(self.reps),
            "replicates": self.reps[:],
            "class_counts": dict(counts),
            "class_fractions": dict(fractions),
            "decision_reason": str(decision.get("reason", "")),
            "confidence": float(decision.get("confidence", 0.0)),
        }
        if "fallback_verdict" in decision:
            rec["fallback_verdict"] = str(decision.get("fallback_verdict"))
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

        wet_hits = sum(1 for r in self.reps if bool(r.get("nozzle_wet")))
        if wet_hits > 0 and self.auto_stop_on_nozzle_wet:
            # High-start scans can show wet/nozzle-contact at clearly-too-high pressures.
            # If we have not discovered any single-droplet region yet and this point is
            # still MULTIPLE, continue scanning downward instead of terminating immediately.
            if (verdict == "multiple") and (self._min_single_pressure is None):
                self._record_decision(
                    "nozzle_wet_deferred_while_high_multiple",
                    {
                        "pressure_psi": float(self._current_pressure),
                        "wet_replicates": int(wet_hits),
                        "n_reps": int(len(self.reps)),
                    },
                )
            else:
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
                self._reacquire_steps_taken = 0
                self._reacquire_step = 0.10
                self._next_pressure = float(min(self.P_MAX, cur + self._reacquire_step))
                self.stageChanged.emit(
                    f"First point {verdict.upper()} @ {cur:.3f} psi → re-acquiring upward (+{self._reacquire_step:.2f} psi)"
                )
                return True

            # FIRST SINGLE → seek upper (only if upper not yet locked)
            if verdict == "single" and self.backtrack_after_first_single and prev_v is None and not self._upper_edge_locked:
                self._first_single_pressure = cur
                self._phase = "seek_upper"
                self._seek_upper_steps = 0
                self._seek_step = max(self.dp_min, min(0.05, self.dp))
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
                self._seek_upper_steps = 0
                self._seek_step = max(self.dp_min, min(0.05, self.dp))
                self._next_pressure = float(min(self.P_MAX, cur + self._seek_step))
                self.stageChanged.emit("Re-acquired SINGLE at higher pressure → seeking MULTIPLE upward")
                return True

            # Still NONE/AMBIG – keep going up, grow step
            self._reacquire_steps_taken = int(max(0, getattr(self, "_reacquire_steps_taken", 0)) + 1)
            if self._reacquire_steps_taken >= int(max(1, getattr(self, "_reacquire_max_steps", 18))):
                self._phase = "scan"
                self._next_pressure = float(max(self.P_MIN, cur - max(self.dp_min, 0.05)))
                self._record_decision(
                    "reacquire_guard_resume_scan",
                    {
                        "pressure_psi": float(cur),
                        "steps_taken": int(self._reacquire_steps_taken),
                        "max_steps": int(getattr(self, "_reacquire_max_steps", 18)),
                    },
                )
                self.stageChanged.emit("Re-acquire step guard hit; resuming downward scan")
                return True
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

            self._seek_upper_steps = int(max(0, getattr(self, "_seek_upper_steps", 0)) + 1)
            span = 0.0
            if self._first_single_pressure is not None:
                span = abs(float(cur) - float(self._first_single_pressure))
            if (
                self._seek_upper_steps >= int(max(1, getattr(self, "_seek_upper_max_steps", 10)))
                or span >= float(max(0.05, getattr(self, "_seek_upper_max_span_psi", 0.80)))
            ):
                self._phase = "scan"
                resume_from = self._first_single_pressure if self._first_single_pressure is not None else cur
                self._next_pressure = float(max(self.P_MIN, resume_from - max(self.dp_min, 0.02)))
                self._record_decision(
                    "seek_upper_guard_resume_scan",
                    {
                        "pressure_psi": float(cur),
                        "steps_taken": int(self._seek_upper_steps),
                        "max_steps": int(getattr(self, "_seek_upper_max_steps", 10)),
                        "span_psi": float(span),
                        "max_span_psi": float(getattr(self, "_seek_upper_max_span_psi", 0.80)),
                    },
                )
                self.stageChanged.emit("Seek-upper guard hit; resuming downward scan")
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
            base = (self._current_pressure if self._current_pressure is not None else self.start_pressure)
            self._next_pressure = float(max(self.P_MIN, min(self.P_MAX, base - max(self.dp, self.dp_min))))

        # If walking off the scan range, finish
        if self._next_pressure < (self.P_MIN - 1e-6):
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
        self.phase_name = "trajectory"

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
    reapplyPressure   = Signal()   # reapply the current pressure

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
                    cur = float(self.model.machine_model.get_target_print_pressure())
                except Exception:
                    hw_lo, hw_hi = self.model.machine_model.get_print_pressure_bounds()
                    cur = (hw_lo + hw_hi) * 0.5
                pressures = [round(cur, 3)]
        self.pressures = list(pressures)
        self.p_index = 0
        self._current_pressure = None

        # --- delays (absolute flash delays, in us) ---
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
        
        self._pending_pressure_adjustment = None  # float | None
        self._adjust_attempts_at_pressure = 0
        self._adjust_attempts_limit = 5          # avoid infinite loops

        # Low-pressure detection thresholds (tunable)
        self._min_radial_growth_px  = 4.0        # net |r(t_last) - r(t_first)| must exceed this
        self._reverse_step_px       = 1.0        # allow small noise; require >1 px reversal to trigger

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
        self.state_decide.addTransition(self.reapplyPressure, self.state_apply)

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
        if cm.get_primary_pressure_band() is None:
            missing.append("Primary pressure band")
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
            self._pending_pressure_adjustment = None
            self._adjust_attempts_at_pressure = 0
            self._saw_multiple_this_pressure = False

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
            f"Trajectory: P={self._current_pressure:.3f} psi, delay={delay} us "
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
            f"Trajectory: update delay → {delay} us at P={self._current_pressure:.3f} psi"
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
            stage_text=f"Capture @ {self._current_pressure:.3f} psi, delay={self.delays_us[self.d_index]} us "
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

        # High-pressure edge case – multiple droplets → schedule a downward adjust & reapply
        if droplets and (len(droplets) > 1):
            new_p = round(float(self._current_pressure) - 0.01, 3)
            self.stageChanged.emit(
                f"Multiple droplets detected at P={self._current_pressure:.3f} → retest at {new_p:.3f} psi"
            )
            self._pending_pressure_adjustment = new_p
            self._saw_multiple_this_pressure = True
            # Continue to present overlay and let state flow into onDecide()
            try:
                self.presentImageSignal.emit(overlay)
            except Exception:
                pass
            self.timepointReady.emit()
            return

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
        if self._pending_pressure_adjustment is not None:
            self._restart_current_pressure_with(self._pending_pressure_adjustment,
                                                reason="multiple_droplets")
            return
        # 1) too many fails at this delay → mark completed (skipped) and move on
        if self._failed_caps_this_delay >= self.max_failed_captures_per_delay:
            self.stageChanged.emit(
                f"Delay {self.delays_us[self.d_index]} us: too many failed captures → skipping"
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

            # Low-pressure edge case — check radial growth vs. nozzle across delays
            if self._should_raise_low_pressure_due_to_retraction():
                new_p = round(float(self._current_pressure) + 0.01, 3)
                self.stageChanged.emit(
                    f"Weak/negative radial motion at P={self._current_pressure:.3f} → retest at {new_p:.3f} psi"
                )
                self._restart_current_pressure_with(new_p, reason="low_pressure_retraction")
                return

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
        self._pending_pressure_adjustment = None
        self._adjust_attempts_at_pressure = 0
        self._saw_multiple_this_pressure = False

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
        """Least-squares for x(t), y(t). Returns (vx, vy) in px/us."""
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

    def _should_raise_low_pressure_due_to_retraction(self) -> bool:
        """
        Return True if aggregated points at the current pressure show that the droplet
        is not moving away from the nozzle (flat) or is reversing toward it.
        Uses radial distance r = sqrt(dx^2+dy^2) vs. delay.
        """
        if len(self.points) < 2:
            return False

        pts = sorted(self.points, key=lambda p: p["t_us"])
        r = [float(math.hypot(p["center_px"][0], p["center_px"][1])) for p in pts]

        # Net growth across the window
        net = r[-1] - r[0]
        if net <= self._min_radial_growth_px:
            return True

        # Local reversal on last step (be tolerant to noise)
        if len(r) >= 2 and (r[-1] < (r[-2] - self._reverse_step_px)):
            return True

        return False
    
    def _restart_current_pressure_with(self, new_pressure: float, *, reason: str):
        """
        Do NOT advance p_index. Replace the current pressure value with `new_pressure`,
        reset per-pressure state, optionally update the band, then jump back to state_apply.
        """
        # safety clamp to hardware bounds if available
        try:
            lo, hi = self.model.machine_model.get_print_pressure_bounds()
            new_pressure = float(min(max(new_pressure, lo), hi))
        except Exception:
            pass
        new_pressure = round(float(new_pressure), 3)

        # Guard against infinite loops
        self._adjust_attempts_at_pressure += 1
        if self._adjust_attempts_at_pressure > self._adjust_attempts_limit:
            self.stageChanged.emit(
                f"Adjustment limit reached at pressure slot → skipping this slot (reason: {reason})"
            )
            # record a no-fit sample and move on to the next pressure
            self.samples.append({
                "pressure": float(self._current_pressure),
                "points": self.points[:],
                "fit": None,
                "note": f"skipped after repeated '{reason}' adjustments"
            })
            self._pending_pressure_adjustment = None
            self._finish_pressure_and_advance()
            return

        # Update the pressure list for this index (stay on this slot)
        if 0 <= self.p_index < len(self.pressures):
            self.pressures[self.p_index] = new_pressure

        # Optional: try to update the primary pressure band on the manager
        try:
            band = self.calibration_manager.get_primary_pressure_band()
            if isinstance(band, (list, tuple)) and len(band) == 2:
                lo, hi = float(min(band)), float(max(band))
                if reason == "low_pressure_retraction":
                    lo = min(hi, new_pressure)
                elif reason == "multiple_droplets":
                    hi = max(lo, new_pressure)
                setter = getattr(self.calibration_manager, "set_primary_pressure_band", None)
                if callable(setter):
                    # Before (problematic): setter((round(lo, 3), round(hi, 3)))
                    setter({"primary_band": (round(lo, 3), round(hi, 3))})
        except Exception:
            pass

        # Reset per-pressure state
        self._current_pressure = None
        self.points = []
        self._completed = [False] * len(self.delays_us)
        self._reset_delay_state()
        self._miss_streak = 0
        self._stop_delays_after_this = False
        self._max_delay_allowed_us = None
        self._pending_pressure_adjustment = None
        self._saw_multiple_this_pressure = False
        self._discard_next = bool(self.discard_first_after_pressure)

        # Jump back to apply state for this same p_index
        self.reapplyPressure.emit()
    
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
        self.num_images = 100
        self.image_counter = 0
        self.circularity_threshold = 1.15
        self.droplet_positions, self.droplet_focus = [], []
        self.circularity_values, self.droplet_volumes = [], []
        self.measurements = []
        self.early_stop_min_reps = 12
        self.early_stop_window = 6
        self.early_stop_mean_drift_pct = 1.5
        self.early_stop_cv_drift_pct = 1.0

        # --- lifecycle/guards ---
        self._aborted = False
        self._finished = False

        # --- see if we should save in this run ---
        self._save_enabled = bool(self.manual_start)  # you said you want this in manual start mode
        self._save_started_here = False
        self._save_dir = None

        self._bg_saved = False
        self._last_capture = None  # dict returned by camera_model.save_frame_with_metadata()

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
        self._x_track_offset_steps = 0
        self._z_track_offset_steps = 0
        self._xz_offset_ema_alpha = 0.35

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

    def _ensure_saving(self):
        if not self._save_enabled:
            return
        cam = self.model.droplet_camera_model
        if not cam.is_saving():
            self._save_dir = cam.start_saving(prefix="droplet_search", root_dir=cam.get_save_root_directory())
            self._save_started_here = True

    def _stop_saving_if_started(self):
        if self._save_started_here:
            try:
                self.model.droplet_camera_model.stop_saving()
            except Exception:
                pass
            self._save_started_here = False

    def _save_capture(self, frame, *, stage: str, extra: dict | None = None) -> dict | None:
        """
        Save a raw captured frame + metadata for this process.
        Returns the camera_model saved dict (index/filename/path).
        """
        if not self._save_enabled:
            return None
        self._ensure_saving()

        cam = self.model.droplet_camera_model

        # capture context
        try:
            cur_pressure = float(self.model.machine_model.get_current_print_pressure())
        except Exception:
            cur_pressure = None
        try:
            cur_pw_us = int(self.model.machine_model.get_print_pulse_width() or 0)
        except Exception:
            cur_pw_us = None

        info = {
            "process": "DropletSearchCalibrationProcess",
            "manual_start": bool(self.manual_start),
            "stage": stage,
            "flash_delay_us": int(getattr(self, "current_delay_us", -1)) if getattr(self, "current_delay_us", None) is not None else None,
            "print_pressure_psi": cur_pressure,
            "print_pulse_width_us": cur_pw_us,
            "replicate_index": int(self.image_counter) if hasattr(self, "image_counter") else None,
            "timestamp": datetime.now().isoformat(),
        }
        if extra:
            info.update(extra)

        saved = cam.save_frame_with_metadata(frame, capture_info=info)
        self._last_capture = saved
        return saved

    def _save_overlay(self, image, *, role: str, frame_index: int, meta_extra: dict | None = None):
        if not self._save_enabled:
            return
        self._ensure_saving()
        self.model.droplet_camera_model.save_aux_image(
            image, index=int(frame_index), role=role, meta_extra=meta_extra
        )

    def _append_analysis(self, record: dict):
        if not self._save_enabled:
            return
        self._ensure_saving()
        self.model.droplet_camera_model.append_analysis_record(record)

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
        self._request_move_absolute_with_timeout(
            (X, Y, Z),
            timeout_ms=15_000,
            err_msg="Droplet search move timed out."
        )

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
        self._stop_saving_if_started()
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
        if self._save_enabled:
            self._ensure_saving()
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
        if self._save_enabled and (self.background_image is not None) and (not self._bg_saved):
            self._save_capture(self.background_image, stage="background", extra={"num_droplets_setting": 0})
            self._bg_saved = True
        
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

        saved = self._save_capture(self.droplet_image, stage="search_capture")
        frame_idx = saved["index"] if saved else None

        contour, overlay = self.model.droplet_camera_model.identify_droplet_contour(
            self.droplet_image, self.background_image
        )
        center_px = None
        if contour is not None:
            x, y, w, h = cv2.boundingRect(contour)
            center_px = (int(x + w // 2), int(y + h // 2))

        if frame_idx is not None and overlay is not None:
            self._save_overlay(
                overlay,
                role="search_overlay",
                frame_index=frame_idx,
                meta_extra={"stage": "search_overlay", "had_contour": bool(contour is not None)}
            )

            self._append_analysis({
                "kind": "search_result",
                "frame_index": int(frame_idx),
                "flash_delay_us": int(self.current_delay_us),
                "found": bool(contour is not None),
                "center_px": center_px,
                "timestamp": datetime.now().isoformat(),
            })

        if contour is None:
            self.stageChanged.emit("No droplet: trying next delay/position")
            self.presentImageSignal.emit(overlay)
            self.emitContinueSearch()
            return

        cxy = center_px
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

        # Save the *raw* frame that produced this characterization result
        saved = self._save_capture(self.droplet_image, stage="characterization_capture", extra={
            "attempt_image_counter": int(self.image_counter),
        })
        frame_idx = saved["index"] if saved else None

        # Save annotated image + per-frame analysis record
        if frame_idx is not None:
            if annotated is not None:
                self._save_overlay(
                    annotated,
                    role="char_annotated",
                    frame_index=frame_idx,
                    meta_extra={"stage": "characterization_annotated"}
                )

            # record result (even if focus is low; you can filter later)
            if isinstance(result, dict):
                self._append_analysis({
                    "kind": "characterization_result",
                    "frame_index": int(frame_idx),
                    "replicate_index": int(self.image_counter),
                    "flash_delay_us": int(getattr(self, "current_delay_us", -1)),
                    "center_px": result.get("center"),
                    "volume_nL": result.get("volume"),
                    "circularity": result.get("circularity"),
                    "circularity_ellipse": result.get("circularity_ellipse"),
                    "focus": result.get("focus"),
                    "timestamp": datetime.now().isoformat(),
                })

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

        if self._should_early_stop_characterization():
            self.stageChanged.emit(
                f"Characterization converged early at {self.image_counter} replicates."
            )
            self.emitInitiateAnalyzeCharacterization()
            return

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
        cv_vol   = float(np.std(self.droplet_volumes) / (mean_vol + 1e-9) * 100.0)
        mean_center = tuple(np.mean(np.array(self.droplet_positions), axis=0).astype(int))
        final_img = self._annotate_final(mean_center, mean_vol, cv_vol)
        self.presentImageSignal.emit(final_img)

        machine_position = self.model.machine_model.get_current_position_dict()
        drop_machine = self.model.droplet_camera_model.convert_pixel_position_to_motor_steps(
            mean_center, machine_position
        )

        # NEW: include current pressure & pulse width for easy summarization
        cur_pressure = float(self.model.machine_model.get_current_print_pressure())
        cur_pw_us    = int(self.model.machine_model.get_print_pulse_width() or 0)

        results = {
            # harmonize with sweep fields
            "pressure": cur_pressure,                       # convenience field
            "delay_us": int(self.current_delay_us),
            "mean_center_px": mean_center,
            "mean_volume": mean_vol,
            "cv_volume_percent": cv_vol,
            "mean_position_machine": drop_machine,
            "valid": True,

            # keep detailed arrays as before
            "droplet_positions": self.droplet_positions,
            "positions_px": self.droplet_positions,         # alias retained
            "droplet_volumes": [float(v) for v in self.droplet_volumes],
            "circularity_values": [float(c) for c in self.circularity_values],
            "droplet_focus": [float(f) for f in self.droplet_focus],

            # pulse width convenience for downstream use
            "print_pulse_width_us": cur_pw_us,
        }

        # Persist the full result payload for later plotting without re-running
        if self._save_enabled:
            self.model.droplet_camera_model.write_json("droplet_search_summary.json", {
                "measurements": self.measurements,
                "result": results
            })

            # Also stream a final record
            self._append_analysis({
                "kind": "final_summary",
                "mean_volume_nL": results.get("mean_volume"),
                "cv_volume_percent": results.get("cv_volume_percent"),
                "mean_center_px": results.get("mean_center_px"),
                "delay_us": results.get("delay_us"),
                "pressure": results.get("pressure"),
                "print_pulse_width_us": results.get("print_pulse_width_us"),
                "timestamp": datetime.now().isoformat(),
            })

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
        self._stop_saving_if_started()
        self.calibrationCompleted.emit()

    # helpers
    def _should_early_stop_characterization(self) -> bool:
        vals = [float(v) for v in self.droplet_volumes if v is not None]
        min_needed = int(self.early_stop_min_reps)
        w = int(self.early_stop_window)
        if len(vals) < min_needed or len(vals) < (2 * w):
            return False
        prev = np.array(vals[-2*w:-w], dtype=float)
        last = np.array(vals[-w:], dtype=float)
        if prev.size == 0 or last.size == 0:
            return False
        prev_mean = float(np.mean(prev))
        last_mean = float(np.mean(last))
        mean_drift_pct = abs(last_mean - prev_mean) / max(abs(prev_mean), 1e-9) * 100.0
        prev_cv = float(np.std(prev) / max(abs(prev_mean), 1e-9) * 100.0)
        last_cv = float(np.std(last) / max(abs(last_mean), 1e-9) * 100.0)
        cv_drift = abs(last_cv - prev_cv)
        return (
            mean_drift_pct <= float(self.early_stop_mean_drift_pct)
            and cv_drift <= float(self.early_stop_cv_drift_pct)
        )

    def _annotate_final(self, mean_center, mean_vol, cv_vol):
        img = self.droplet_image.copy()
        for p in self.droplet_positions:
            cv2.circle(img, p, 5, (255, 0, 0), -1)
        cv2.circle(img, mean_center, 8, (0, 255, 0), -1)
        cv2.putText(img, f"Mean vol: {mean_vol:.2f}", (10, 32), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,0), 2)
        cv2.putText(img, f"CV vol: {cv_vol:.2f}%", (10, 64), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,0), 2)
        return img

    def _update_xz_track_offset(self):
        """
        Update persistent X/Z bias (steps) so future predicted targets include this correction.
        Uses EMA toward the difference between 'predicted' and 'actual centered' pose.
        """
        try:
            # prefer the searched-and-found delay for accuracy
            used_delay = int(self.current_delay_us) if self.current_delay_us is not None else int(self.target_delay_us)
            predX, predY, predZ = self._predict_stage_target(used_delay)
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
                 sphere_delay_us: int = 10000,
                 replicates_per_pressure: int = 20,
                 order: str = "desc",            # "desc" = high -> low (safer)
                 edge_guard_px: int = 200,
                 focus_ok_threshold: float = 5_000_000,
                 min_pressure_separation: float = 0.005,
                 max_search_cycles: int = 4,
                 max_recenter_moves: int = 10,
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
        self.num_samples           = self.calibration_manager.get_num_pressure_tests()
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
                grid = self._make_pressure_set_by_count(p_lo, p_hi, int(self.num_samples), float(min_pressure_separation))

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
        self.early_stop_min_reps = 12
        self.early_stop_window = 6
        self.early_stop_mean_drift_pct = 1.5
        self.early_stop_cv_drift_pct = 1.0

        self.max_search_cycles   = int(max_search_cycles)
        self.max_recenter_moves  = int(max_recenter_moves)
        self.max_oob_total       = int(max_oob_total)

        self.lightweight_overlays = bool(lightweight_overlays)
        self.present_every_k      = int(max(1, present_every_k))

        self.boundary_tol_px = 250          # pixels around image center accepted as "in-bounds"
        self.center_first_tol_px = 140      # first center attempt tolerance
        self._oob_streak = 0                # consecutive out-of-bound hits
        self._oob_positions = []            # recent out-of-bound centers (pixels)

        self._incremental_emitted = False

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
        self._request_move_absolute_with_timeout(
            (X, Y, Z),
            on_done=self.moveDone.emit,
            timeout_ms=15_000,
            err_msg="Pressure sweep move timed out."
        )

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
        self._recenter_moves = 0          # number of recenter moves issued during characterization
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
        s_per_us = 1e6  # us -> s
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
                               f"(vx={vx:.4f} px/us, vy={vy:.4f} px/us)")
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
        self.stageChanged.emit(f"Moving to predicted target @ {self.target_delay_us} us → {tgt}")
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
            self._vertical_probe_tries = 0
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

        d = self.target_delay_us + self._delay_offsets_us[self._delay_try_index]
        self._delay_try_index += 1
        self.current_delay_us = self._clamp_delay(d)
        self.stageChanged.emit(f"Setting flash delay to {self.current_delay_us} us (search)")
        self.calibration_manager.changeSettingsRequested.emit(
            {"flash_delay": int(self.current_delay_us), "num_droplets": 1},
            self.delayApplied.emit
        )

    @Slot()
    def onCaptureDroplet(self):
        self._capture_with_policy(
            set_attr="droplet_image",
            stage_text=f"Capture droplet @ {self.current_delay_us} us",
            attempts_total=5, retry_delay_ms=75, guard_timeout_ms=10_000,
            final_error_msg=f"Failed to capture droplet @ {self.current_delay_us} us."
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
        self._recenter_moves += 1
        print('Recenter counter (onCenter):', self._recenter_moves)
        self.stageChanged.emit(f"Centering recenter #{self._recenter_moves}/{self.max_recenter_moves}")
        if self._recenter_moves >= self.max_recenter_moves:
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
            self._recenter_moves += 1
            print('Recenter counter (onCharacterizeLoop):', self._recenter_moves)

            self.stageChanged.emit(f"Center-first recenter #{self._recenter_moves}/{self.max_recenter_moves}")

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
            if self._recenter_moves >= self.max_recenter_moves:
                self.stageChanged.emit("Inconsistent imaging: too many recenter moves (center-first) → skip pressure")
                self._bad_reason = "recentre_limit_centerfirst"
                self._record_pressure_result(valid=False, reason=self._bad_reason)
                self.i += 1
                self.nextPressure.emit()
                return

            # Proceed with the move
            self._recenter_immediate(center_px)
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

        if self._check_boundary_and_maybe_recenter(center_px):
            # A recenter move was issued (average of 2 consecutive OOB hits).
            # After the move completes, state_char → (moveDone) → state_capture → fresh frame.
            return

        if self._should_early_stop_batch():
            self.stageChanged.emit(
                f"Pressure {self.cur_pressure:.3f} characterization converged early at {self.image_counter} replicates."
            )
            self.analyzeBatch.emit()
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

            rec = {                                        # <- name it so we can emit it
                "pressure": float(self.cur_pressure),
                "delay_us": int(self.current_delay_us),
                "mean_center_px": mean_center,
                "mean_volume": mean_vol,
                "cv_volume_percent": cv_vol,
                "volumes": [float(v) for v in self.droplet_volumes],
                "circularity_values": [float(c) for c in self.circularity_values],
                "mean_position_machine": drop_machine,
                "multiple_detections": int(self.multiple_droplet_hits),
                "y_focus_offset_steps": int(self._y_focus_offset_steps),
                "valid": True
            }
            self.samples.append(rec)
            self._emit_incremental_pressure_step(rec)      # <- NEW incremental emit

        # advance plan
        self.i += 1
        self._reset_char_buffers()
        self.nextPressure.emit()

    def _should_early_stop_batch(self) -> bool:
        vals = [float(v) for v in self.droplet_volumes if v is not None]
        min_needed = int(self.early_stop_min_reps)
        w = int(self.early_stop_window)
        if len(vals) < min_needed or len(vals) < (2 * w):
            return False
        prev = np.array(vals[-2*w:-w], dtype=float)
        last = np.array(vals[-w:], dtype=float)
        if prev.size == 0 or last.size == 0:
            return False
        prev_mean = float(np.mean(prev))
        last_mean = float(np.mean(last))
        mean_drift_pct = abs(last_mean - prev_mean) / max(abs(prev_mean), 1e-9) * 100.0
        prev_cv = float(np.std(prev) / max(abs(prev_mean), 1e-9) * 100.0)
        last_cv = float(np.std(last) / max(abs(last_mean), 1e-9) * 100.0)
        cv_drift = abs(last_cv - prev_cv)
        return (
            mean_drift_pct <= float(self.early_stop_mean_drift_pct)
            and cv_drift <= float(self.early_stop_cv_drift_pct)
        )

    def _record_pressure_result(self, valid: bool, reason: str | None = None):
        rec = {
            "pressure": float(self.cur_pressure),
            "delay_us": int(self.current_delay_us or self.target_delay_us),
            "mean_center_px": None,
            "mean_volume": None,
            "cv_volume_percent": None,
            # "positions_px": [],
            "volumes": [],
            # "focus_values": [],
            "circularity_values": [],
            "mean_position_machine": None,
            "valid": bool(valid),
            "invalid_reason": (None if valid else (reason or "unspecified"))
        }
        
        self.samples.append(rec)
        self._emit_incremental_pressure_step(rec)  # <- NEW incremental emit
    
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


    def _recenter_immediate(self, center_px) -> None:
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

    def _check_boundary_and_maybe_recenter(self, center_px) -> bool:
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
        
        self._recenter_moves += 1               # NEW: count recenter moves
        print('Recenter counter (check_boundary):', self._recenter_moves)
        if self._recenter_moves >= self.max_recenter_moves:
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
            # self.stageChanged.emit(f"Focus OK → update Y-offset = {self._y_focus_offset_steps} steps (EMA)")
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
    
    def _emit_incremental_pressure_step(self, pressure_entry: dict) -> None:
        """
        Emit a single-pressure result so the UI can update immediately.
        Includes run metadata but only one pressure record in 'pressures'.
        """
        result = {
            "pressures": [pressure_entry],                     # <- exactly one pressure
            "order": "desc",                                   # keep same metadata as final
            "sphere_delay_us": int(self.sphere_delay_us),
            "nozzle_center_px": self.nozzle_center_px,
            "nozzle_center_machine": self.nozzle_center_machine,
            "emergence_time_us": int(self.emergence_time_us),
        }
        self.calibrationDataUpdated.emit({"measurements": [], "result": result})
        self._incremental_emitted = True

    @Slot()
    def onCompleted(self):
        if self._incremental_emitted:
            # We've already emitted each pressure; just stamp metadata + completion.
            result = {
                "pressures": [],  # nothing new here; avoids duplicates in summary rows
                "order": "desc",
                "sphere_delay_us": int(self.sphere_delay_us),
                "nozzle_center_px": self.nozzle_center_px,
                "nozzle_center_machine": self.nozzle_center_machine,
                "emergence_time_us": int(self.emergence_time_us),
                "complete": True
            }
            self.calibrationDataUpdated.emit({"measurements": [], "result": result})
        else:
            # Back-compat: original behavior (single emit with all pressures)
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
      - Compute start = first whole 100 us BEFORE the emergence time (clamped at 0).
      - Capture 1 image every 100 us from start to start + window_us (inclusive).
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
                 step_us: int = 50,
                 window_us: int = 6000,
                 parent=None):
        super().__init__(calibration_manager, model, parent)
        self.phase_name = "droplet_timecourse"
        self._save_dir = None

        # ensure we stop saving on success or error
        self.calibrationCompleted.connect(self._cleanup_saving)
        self.calibrationError.connect(self._cleanup_saving_on_error)

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

    def start(self):
        # Pick a sensible default root: next to calibration.json, in droplet_imager_captures/
        root = self.model.droplet_camera_model.get_save_root_directory()
        if not root:
            try:
                cal_path = self.calibration_manager.calibration_file_path
                if not cal_path:
                    cal_path = self.model.experiment_model.get_calibration_file_path()
                base_dir = os.path.dirname(os.path.abspath(cal_path))
            except Exception:
                base_dir = os.getcwd()
            root = os.path.join(base_dir, "droplet_imager_captures")

        self._save_dir = self.model.droplet_camera_model.start_saving(
            root_dir=root,
            prefix="droplet_timecourse",
            create_subdir=True,
            image_ext="jpg",
            jpeg_quality=95,
        )

        # Helpful UI log
        try:
            self.stageChanged.emit(f"Timecourse saving frames to: {self._save_dir}")
        except Exception:
            pass

        # Optional: persist path in calibration.json for traceability
        try:
            self.calibrationDataUpdated.emit({
                "event": "timecourse_capture_started",
                "save_dir": self._save_dir,
            })
        except Exception:
            pass

        super().start()  # run your existing FSM / logic

    def _cleanup_saving(self, *args):
        try:
            if self.model and getattr(self.model, "droplet_camera_model", None):
                self.model.droplet_camera_model.stop_saving()
        except Exception:
            pass

    def _cleanup_saving_on_error(self, *args):
        self._cleanup_saving()

    def stop(self):
        # if your BaseCalibrationProcess has stop(), keep it
        self._cleanup_saving()
        super().stop()

    def requestGracefulStop(self, *args, **kwargs):
        self._cleanup_saving()
        return super().requestGracefulStop(*args, **kwargs)

    # ---------- helpers ----------
    def _put_delay_stamp(self, img, delay_us: int):
        """Draw large black 'XXXX us' at bottom-right."""
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
            f"Timecourse: emergence={int(self.emergence_time_us)} us, "
            f"start={self.start_delay_us} us, step={self.step_us} us, window={self.window_us} us "
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
        self.stageChanged.emit(f"Setting flash_delay = {d} us")
        # Only manipulate flash delay and ensure a single droplet per capture
        settings = {"flash_delay": d, "num_droplets": 1}
        self.calibration_manager.changeSettingsRequested.emit(settings, self.delayApplied.emit)

    @Slot()
    def onCaptureFrame(self):
        d = int(self.current_delay_us)
        self._capture_with_policy(
            set_attr="raw_frame_image",
            stage_text=f"Capturing timecourse frame @ {d} us",
            attempts_total=5, retry_delay_ms=50, guard_timeout_ms=8000,
            final_error_msg=f"Capture failed at delay {d} us"
        )

    @Slot()
    def onAnnotateAndAdvance(self):
        d = int(self.current_delay_us)
        ok = hasattr(self, "raw_frame_image") and (self.raw_frame_image is not None)
        if not ok:
            self.frames.append({"delay_us": d, "ok": False})
            self.stageChanged.emit(f"Frame @ {d} us: missing image")
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
        self.latest_frame = None
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
        self._last_droplet_center_px = None

        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.image_dir = os.path.join(self.script_dir, 'Images')
        # self.dir_name = "Untitled"
        # self.save_dir = os.path.join(self.script_dir, self.dir_name)

        # --- Saving state ---
        self._save_root_dir = None        # user-set “root” directory
        self._save_dir = None             # active run directory
        self._saving_enabled = False

        self._save_prefix = "frame"
        self._save_ext = "jpg"
        self._jpeg_quality = 95
        self._save_index = 0

        self._save_queue = queue.Queue(maxsize=256)
        self._save_stop_evt = threading.Event()
        self._save_thread = None
        self._meta_fp = None
        self._analysis_fp = None
        self._meta_lock = threading.Lock()
        self._analysis_lock = threading.Lock()

        # Track last saved capture
        self._last_saved = None  # dict with index/filename/path/etc.

        # optional: store last capture info
        self._last_capture_info = None

        self.steps_conv_path = steps_conv_path
        self.intercept_cx, self.intercept_cy, self.A, self.A_inv = self.load_step_calibration(self.steps_conv_path)

    @staticmethod
    def _json_default(o):
        # makes numpy + tuples json-friendly
        if isinstance(o, (np.integer, np.floating)):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (tuple, set)):
            return list(o)
        return str(o)

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

    def start_saving(
        self,
        *,
        root_dir: str | None = None,
        prefix: str = "capture",
        create_subdir: bool = True,
        image_ext: str = "jpg",
        jpeg_quality: int = 95,
    ):
        """
        Enables saving of every captured frame into a *new directory*.
        Returns the active save directory.
        """
        # If already saving, stop and start fresh (new folder)
        if self._saving_enabled:
            self.stop_saving()

        root = root_dir or self._save_root_dir
        if not root:
            # reasonable fallback if nothing else is configured
            root = os.path.abspath(os.path.join(os.getcwd(), "droplet_imager_captures"))

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = f"{prefix}_{ts}" if create_subdir else ""

        if create_subdir:
            save_dir = self._make_unique_dir(root, folder_name)
        else:
            save_dir = os.path.abspath(root)
            os.makedirs(save_dir, exist_ok=True)

        self._save_dir = save_dir
        self._save_prefix = "frame"
        self._save_ext = image_ext.lstrip(".").lower()
        self._jpeg_quality = int(jpeg_quality)
        self._save_index = 0

        # metadata jsonl
        try:
            meta_path = os.path.join(self._save_dir, "metadata.jsonl")
            self._meta_fp = open(meta_path, "a", buffering=1)
        except Exception as e:
            self._meta_fp = None
            print(f"[DropletCameraModel] Could not open metadata.jsonl: {e}")

        # analysis jsonl (NEW)
        try:
            analysis_path = os.path.join(self._save_dir, "analysis.jsonl")
            self._analysis_fp = open(analysis_path, "a", buffering=1)
        except Exception as e:
            self._analysis_fp = None
            print(f"[DropletCameraModel] Could not open analysis.jsonl: {e}")

        self._saving_enabled = True
        self._start_save_thread()

        print(f"[DropletCameraModel] Saving enabled -> {self._save_dir}")
        return self._save_dir

    def stop_saving(self):
        """
        Stops saving and flushes the writer queue.
        """
        if not self._saving_enabled:
            return

        self._saving_enabled = False

        # try to flush queued work quickly
        try:
            # wait a bit for queue to drain
            self._save_queue.join()
        except Exception:
            pass

        self._stop_save_thread()

        # close metadata file
        try:
            if self._meta_fp:
                self._meta_fp.close()
        except Exception:
            pass
        self._meta_fp = None

        try:
            if self._analysis_fp:
                self._analysis_fp.close()
        except Exception:
            pass
        self._analysis_fp = None

        print(f"[DropletCameraModel] Saving stopped (dir was {self._save_dir})")
        self._save_dir = None
        self._last_saved = None

    def save_frame_with_metadata(self, frame: np.ndarray, *, capture_info: dict | None = None) -> dict | None:
        """
        Save a captured frame into the active run folder, returning a dict describing the saved item:
        {"index":..., "filename":..., "path":..., "saved_at":...}
        This does NOT emit UI signals; it’s safe to call from calibration processes.
        """
        if frame is None or not self._saving_enabled or not self._save_dir:
            return None

        self._save_index += 1
        idx = self._save_index
        fname = f"frame_{idx:06d}.{self._save_ext}"
        fpath = os.path.join(self._save_dir, fname)

        # snapshot metadata
        try:
            num_flashes, flash_duration, flash_delay, num_droplets, exposure_time = self.get_image_metadata()
        except Exception:
            num_flashes = flash_duration = flash_delay = num_droplets = exposure_time = None

        meta = {
            "kind": "frame",
            "index": idx,
            "filename": fname,
            "saved_at": datetime.now().isoformat(),
            "num_flashes": num_flashes,
            "flash_duration_us": flash_duration,
            "flash_delay_us": flash_delay,
            "num_droplets": num_droplets,
            "exposure_time_us": exposure_time,
            "capture_info": capture_info,
        }

        try:
            self._save_queue.put_nowait((fpath, frame.copy(), meta))
        except queue.Full:
            print("[DropletCameraModel] Save queue full — dropping frame.")
            return None

        self._last_saved = {"index": idx, "filename": fname, "path": fpath, "saved_at": meta["saved_at"]}
        return dict(self._last_saved)

    def save_aux_image(self, image: np.ndarray, *, index: int, role: str, meta_extra: dict | None = None) -> str | None:
        """
        Save an auxiliary image (overlay/annotated/final) tied to an existing frame index.
        Filename example: overlay_000123.jpg
        """
        if image is None or not self._saving_enabled or not self._save_dir:
            return None

        fname = f"{role}_{int(index):06d}.{self._save_ext}"
        fpath = os.path.join(self._save_dir, fname)

        meta = {
            "kind": role,
            "index": int(index),
            "filename": fname,
            "guessed_pair_frame": f"frame_{int(index):06d}.{self._save_ext}",
            "saved_at": datetime.now().isoformat(),
        }
        if meta_extra:
            meta.update(meta_extra)

        try:
            self._save_queue.put_nowait((fpath, image.copy(), meta))
            return fpath
        except queue.Full:
            print("[DropletCameraModel] Save queue full — dropping aux image.")
            return None

    def append_analysis_record(self, record: dict):
        """
        Append a single JSON line to analysis.jsonl (stream-friendly).
        """
        if not self._analysis_fp:
            return
        try:
            with self._analysis_lock:
                self._analysis_fp.write(json.dumps(record, default=self._json_default) + "\n")
                self._analysis_fp.flush()
        except Exception as e:
            print(f"[DropletCameraModel] Failed to write analysis record: {e}")

    def write_json(self, filename: str, data: dict):
        """
        Convenience: write a full JSON file into the active run folder.
        """
        if not self._save_dir:
            return
        try:
            path = os.path.join(self._save_dir, filename)
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=self._json_default)
        except Exception as e:
            print(f"[DropletCameraModel] Failed to write {filename}: {e}")

    def set_save_directory(self, directory: str | None):
        """
        Backwards-compatible setter:
        - If `directory` is absolute -> use as root.
        - If relative (e.g. "MyExperiment") -> create under self.image_dir/MyExperiment.
        This sets the *root* directory where new timestamped run folders will be created.
        """
        if directory is None:
            self._save_root_dir = None
            return

        if os.path.isabs(directory):
            root = directory
        else:
            # Keep your old behavior of saving under .../Images/<name>
            root = os.path.join(self.image_dir, directory)

        self._save_root_dir = os.path.abspath(root)

    def get_save_root_directory(self) -> str | None:
        return self._save_root_dir

    def get_active_save_directory(self) -> str | None:
        return self._save_dir

    def is_saving(self) -> bool:
        return bool(self._saving_enabled)

    def _make_unique_dir(self, parent: str, name: str) -> str:
        os.makedirs(parent, exist_ok=True)
        out = os.path.join(parent, name)
        if not os.path.exists(out):
            os.makedirs(out, exist_ok=True)
            return out
        # if it exists, add suffix
        for i in range(1, 1000):
            cand = f"{out}_{i:03d}"
            if not os.path.exists(cand):
                os.makedirs(cand, exist_ok=True)
                return cand
        raise RuntimeError("Could not create a unique capture directory (too many collisions).")

    def _start_save_thread(self):
        if self._save_thread and self._save_thread.is_alive():
            return
        self._save_stop_evt.clear()
        self._save_thread = threading.Thread(target=self._save_worker, daemon=True)
        self._save_thread.start()

    def _stop_save_thread(self):
        self._save_stop_evt.set()
        if self._save_thread:
            self._save_thread.join(timeout=3.0)
            self._save_thread = None

    def _save_worker(self):
        """
        Background writer: pulls (path, image_rgb, meta_dict) and writes to disk.
        """
        while (not self._save_stop_evt.is_set()) or (not self._save_queue.empty()):
            try:
                item = self._save_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if item is None:
                continue

            path, img_rgb, meta = item
            try:
                # cv2.imwrite expects BGR; your frames are RGB
                img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)

                if self._save_ext.lower() in ("jpg", "jpeg"):
                    cv2.imwrite(
                        path,
                        img_bgr,
                        [int(cv2.IMWRITE_JPEG_QUALITY), int(self._jpeg_quality)]
                    )
                else:
                    # png or others
                    cv2.imwrite(path, img_bgr)

                # append metadata jsonl
                if self._meta_fp:
                    with self._meta_lock:
                        self._meta_fp.write(json.dumps(meta, default=str) + "\n")
                        self._meta_fp.flush()

            except Exception as e:
                # don’t crash the writer; log and continue
                print(f"[DropletCameraModel] Failed to save {path}: {e}")
            finally:
                try:
                    self._save_queue.task_done()
                except Exception:
                    pass

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

    # def set_save_directory(self,dir):
    #     self.dir_name = dir
    #     self.save_dir = os.path.join(self.image_dir, self.dir_name)
    
    def update_image(self, frame: np.ndarray, capture_info: dict | None = None):
        """
        Called by Controller when a new droplet image arrives.
        """
        if frame is None:
            return

        # store image (whatever you currently do)
        self._last_capture_info = capture_info
        self.latest_frame = frame  # or frame.copy() if you prefer

        # --- enqueue save if enabled ---
        if self._saving_enabled and self._save_dir:
            self._save_index += 1
            fname = f"{self._save_prefix}_{self._save_index:06d}.{self._save_ext}"
            fpath = os.path.join(self._save_dir, fname)

            # snapshot metadata at capture time
            try:
                num_flashes, flash_duration, flash_delay, num_droplets, exposure_time = self.get_image_metadata()
            except Exception:
                num_flashes = flash_duration = flash_delay = num_droplets = exposure_time = None

            meta = {
                "index": self._save_index,
                "filename": fname,
                "saved_at": datetime.now().isoformat(),
                "num_flashes": num_flashes,
                "flash_duration_us": flash_duration,
                "flash_delay_us": flash_delay,
                "num_droplets": num_droplets,
                "exposure_time_us": exposure_time,
                "capture_info": capture_info,  # includes cap_id/reason/threshold/mean if provided
            }

            # hand a copy to the writer to avoid accidental mutation
            try:
                self._save_queue.put_nowait((fpath, frame.copy(), meta))
            except queue.Full:
                print("[DropletCameraModel] Save queue full — dropping frame.")

        # continue your usual flow (emit, analyze, etc.)
        self.droplet_image_updated.emit()

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

        blur = cv2.GaussianBlur(diff, (5, 5), 0)
        mu, sd = float(np.mean(blur)), float(np.std(blur))
        t_hard = max(20, int(mu + 2.5 * sd))
        _, thresh = cv2.threshold(blur, t_hard, 255, cv2.THRESH_BINARY)
        if cv2.countNonZero(thresh) < 80:
            _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, self._k3, iterations=1)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, self._k3, iterations=1)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            print('No contours detected')
            cv2.putText(image, 'No contours detected', (image.shape[1]//2, image.shape[0]//2), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            return None, None, image

        large_contours = [c for c in contours if cv2.contourArea(c) > 800]
        if not large_contours:
            large_contours = contours

        # Keep deterministic selection in multi-contour scenes: prefer lower contour then larger area.
        def _rank(c):
            x, y, w, h = cv2.boundingRect(c)
            return (-(y + h), -cv2.contourArea(c))

        chosen = sorted(large_contours, key=_rank)[0]
        x, y, w, h = cv2.boundingRect(chosen)
        center = (x + w//2, y + h//2)
        focus = self.compute_tenengrad_variance(image_gray)

        annotated = image.copy()
        cv2.drawContours(annotated, [chosen], -1, (0, 255, 0), 2)
        cv2.rectangle(annotated, (x, y), (x+w, y+h), (255, 0, 0), 2)
        cv2.circle(annotated, center, 10, (0, 0, 255), -1)
        cv2.putText(annotated, f'Center: {center}', (x+w, y+h), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        cv2.putText(annotated, f'Focus: {focus:.2f}', (x+w, y+h+30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        if len(large_contours) > 1:
            cv2.putText(annotated, f'Candidates: {len(large_contours)}', (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)

        return center, focus, annotated
    
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
    
    def calc_emergence_area(
        self,
        background,
        image,
        roi_top_frac=0.06,
        roi_bottom_frac=0.55,
        roi_x_center_frac=0.50,
        roi_x_half_frac=0.18,
        min_fg_pix=60,
        min_contour_area=40,
        min_peak_delta=18,
        *,
        nozzle_center=None,
        roi_x_center_px=None,
        return_details: bool = False,
    ):
        """
        Emergence detector tuned for dark fluid against a background.
        - Uses dark-only diff (background - image).
        - Uses a top ROI, anchored to calibrated nozzle center when available.
        - Returns (bbox_area|None, center|None, overlay[, details]).
        """
        details = {
            "status": "init",
            "reason": "",
            "roi": None,
            "candidate_count": 0,
            "chosen_bbox": None,
            "contour_class": "none",
            "bbox_area": 0,
            "contour_area": 0.0,
            "p95": 0.0,
        }

        if background is None or image is None:
            details.update({"status": "none", "reason": "missing_image_or_background"})
            if return_details:
                return None, None, image, details
            return None, None, image

        img_gray, dark = self.calc_neg_diff_image(image, background)
        if dark is None:
            details.update({"status": "none", "reason": "dark_diff_failed"})
            if return_details:
                return None, None, image, details
            return None, None, image

        h, w = dark.shape[:2]

        nzx = None
        nzy = None
        if nozzle_center is not None and isinstance(nozzle_center, (tuple, list)) and len(nozzle_center) >= 2:
            try:
                nzx = int(max(0, min(w - 1, int(nozzle_center[0]))))
                nzy = int(max(0, min(h - 1, int(nozzle_center[1]))))
            except Exception:
                nzx = None
                nzy = None

        if roi_x_center_px is not None:
            x_mid = int(max(0, min(w - 1, int(roi_x_center_px))))
        elif nzx is not None:
            x_mid = int(nzx)
        else:
            x_mid = int(round(roi_x_center_frac * w))

        x_half = int(round(roi_x_half_frac * w))
        if x_half < 8:
            x_half = 8
        x0 = max(0, x_mid - x_half)
        x1 = min(w, x_mid + x_half)

        if nzy is not None:
            up = int(max(8, round(0.08 * h)))
            down = int(max(24, round(0.42 * h)))
            y0 = max(0, nzy - up)
            y1 = min(h, nzy + down)
        else:
            y0 = int(max(0, min(h - 1, round(roi_top_frac * h))))
            y1 = int(max(0, min(h, round(roi_bottom_frac * h))))

        if y1 <= y0 or x1 <= x0:
            details.update({"status": "none", "reason": "invalid_roi", "roi": [int(x0), int(y0), int(x1), int(y1)]})
            if return_details:
                return None, None, image, details
            return None, None, image

        details["roi"] = [int(x0), int(y0), int(x1), int(y1)]

        roi = dark[y0:y1, x0:x1].copy()
        blur = cv2.GaussianBlur(roi, (5, 5), 0)

        mu, sd = float(np.mean(blur)), float(np.std(blur))
        t_hard = max(10, int(mu + 2.5 * sd))
        _, th = cv2.threshold(blur, t_hard, 255, cv2.THRESH_BINARY)
        if np.count_nonzero(th) < min_fg_pix:
            _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        k = self._k3
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, k, iterations=1)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k, iterations=1)

        overlay = image.copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        cv2.rectangle(overlay, (x0, y0), (x1, y1), (128, 128, 255), 1)
        if nzx is not None and nzy is not None:
            cv2.circle(overlay, (nzx, nzy), 4, (255, 0, 0), -1)

        if np.count_nonzero(th) < min_fg_pix:
            details.update({"status": "none", "reason": "insufficient_fg"})
            cv2.putText(overlay, "No FG in ROI", (x0 + 5, y0 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 255), 1)
            if return_details:
                return None, None, overlay, details
            return None, None, overlay

        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            details.update({"status": "none", "reason": "no_contours"})
            if return_details:
                return None, None, overlay, details
            return None, None, overlay

        keep = []
        for c in contours:
            c_area = float(cv2.contourArea(c))
            if c_area < float(min_contour_area):
                continue
            rx, ry, rw, rh = cv2.boundingRect(c)
            fx, fy = int(rx + x0), int(ry + y0)
            bottom = int(fy + rh)
            cx = float(fx + rw / 2.0)

            cls = "unknown"
            if nzy is not None:
                if fy <= nzy <= (fy + rh + 2):
                    cls = "attached"
                elif fy > (nzy + 6):
                    cls = "detached"
                else:
                    cls = "ambiguous"

            if cls == "attached":
                pri = 0
            elif cls == "detached":
                pri = 2
            else:
                pri = 1

            anchor_x = float(nzx if nzx is not None else x_mid)
            x_pen = abs(cx - anchor_x)
            keep.append({
                "contour": c,
                "contour_area": c_area,
                "bbox": [fx, fy, int(rw), int(rh)],
                "bottom": bottom,
                "x_pen": float(x_pen),
                "class": cls,
                "pri": pri,
            })

        details["candidate_count"] = int(len(keep))
        if not keep:
            details.update({"status": "none", "reason": "no_contours_after_filters"})
            if return_details:
                return None, None, overlay, details
            return None, None, overlay

        keep.sort(key=lambda d: (int(d["pri"]), float(d["x_pen"]), -float(d["contour_area"]), -int(d["bottom"])))
        chosen = keep[0]

        x, y, ww, hh = [int(v) for v in chosen["bbox"]]
        patch = dark[y:y + hh, x:x + ww]
        if patch.size == 0:
            details.update({"status": "none", "reason": "empty_patch_after_bbox"})
            if return_details:
                return None, None, overlay, details
            return None, None, overlay

        p95 = float(np.percentile(patch, 95))
        if p95 < float(min_peak_delta):
            details.update({
                "status": "none",
                "reason": "weak_signal",
                "p95": float(p95),
                "contour_class": str(chosen.get("class", "unknown")),
                "chosen_bbox": [int(x), int(y), int(ww), int(hh)],
                "bbox_area": int(ww * hh),
                "contour_area": float(chosen.get("contour_area", 0.0)),
            })
            cv2.putText(overlay, f"weak p95:{int(p95)}", (x0 + 5, y0 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 160, 255), 1)
            if return_details:
                return None, None, overlay, details
            return None, None, overlay

        contour_full = chosen["contour"] + np.array([[[x0, y0]]], dtype=chosen["contour"].dtype)
        color = (0, 255, 0) if str(chosen.get("class")) == "attached" else (0, 200, 255)
        cv2.drawContours(overlay, [contour_full], -1, color, 2)
        cv2.rectangle(overlay, (x, y), (x + ww, y + hh), (255, 0, 0), 2)

        metric_area = int(ww * hh)
        center = (int(x + ww // 2), int(y + hh // 2))

        details.update({
            "status": "ok",
            "reason": "ok",
            "contour_class": str(chosen.get("class", "unknown")),
            "chosen_bbox": [int(x), int(y), int(ww), int(hh)],
            "bbox_area": int(metric_area),
            "contour_area": float(chosen.get("contour_area", 0.0)),
            "p95": float(p95),
            "center": [int(center[0]), int(center[1])],
        })

        cv2.putText(overlay, f"Area:{metric_area}", (x + ww + 6, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (50, 200, 50), 2)
        cv2.putText(overlay, f"Class:{details['contour_class']}", (x + ww + 6, y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (50, 200, 50), 1)

        if return_details:
            return metric_area, center, overlay, details
        return metric_area, center, overlay

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

        def _threshold_region(region):
            blur = cv2.GaussianBlur(region, (5, 5), 0)
            mu, sd = float(np.mean(blur)), float(np.std(blur))
            t_hard = max(20, int(mu + 2.5 * sd))
            _, th = cv2.threshold(blur, t_hard, 255, cv2.THRESH_BINARY)
            if cv2.countNonZero(th) < 80:
                _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            th = cv2.morphologyEx(th, cv2.MORPH_OPEN, self._k3, iterations=1)
            th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, self._k3, iterations=1)
            return th

        def _filter(contours):
            out = []
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < 800 or area > 120000:
                    continue
                x, y, w, h = cv2.boundingRect(contour)
                if h <= 0:
                    continue
                if (w / float(h)) >= 3.2:
                    continue
                out.append(contour)
            return out

        # Fast path: ROI around last center, fallback to full frame if no valid contour.
        roi_used = False
        x0 = y0 = 0
        x1, y1 = diff.shape[1], diff.shape[0]
        last = self._last_droplet_center_px
        if last is not None:
            cx, cy = int(last[0]), int(last[1])
            half = 240
            x0 = max(0, cx - half)
            y0 = max(0, cy - half)
            x1 = min(diff.shape[1], cx + half)
            y1 = min(diff.shape[0], cy + half)
            if (x1 - x0) >= 80 and (y1 - y0) >= 80:
                roi = diff[y0:y1, x0:x1]
                th_roi = _threshold_region(roi)
                contours_roi, _ = cv2.findContours(th_roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                filtered_roi = _filter(contours_roi)
                if filtered_roi:
                    roi_used = True
                    # map ROI contour -> full image coords
                    filtered = [c + np.array([[[x0, y0]]], dtype=c.dtype) for c in filtered_roi]
                else:
                    filtered = []
            else:
                filtered = []
        else:
            filtered = []

        if not filtered:
            th = _threshold_region(diff)
            contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if len(contours) == 0:
                print('No contours detected')
                return None, image
            filtered = _filter(contours)
            if len(filtered) == 0:
                print('No large contours detected')
                annotated_image = image.copy()
                cv2.drawContours(annotated_image, contours, -1, (0, 255, 0), 2)
                for contour in contours:
                    area = cv2.contourArea(contour)
                    x, y, w, h = cv2.boundingRect(contour)
                    cv2.putText(annotated_image, f'{area:.0f}', (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                return None, annotated_image

        # Deterministic contour selection in ambiguous scenes.
        largest_contour = sorted(
            filtered,
            key=lambda c: (-cv2.contourArea(c), -cv2.boundingRect(c)[1])
        )[0]

        annotated_image = image.copy()
        cv2.drawContours(annotated_image, [largest_contour], -1, (0, 255, 0), 2)
        x, y, w, h = cv2.boundingRect(largest_contour)
        self._last_droplet_center_px = (int(x + w // 2), int(y + h // 2))
        if roi_used:
            cv2.rectangle(annotated_image, (x0, y0), (x1, y1), (128, 128, 255), 1)

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

        blur = cv2.GaussianBlur(diff, (5, 5), 0)
        mu, sd = float(np.mean(blur)), float(np.std(blur))
        t_hard = max(20, int(mu + 2.5 * sd))
        _, thresh = cv2.threshold(blur, t_hard, 255, cv2.THRESH_BINARY)
        if cv2.countNonZero(thresh) < 80:
            _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, self._k3, iterations=1)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, self._k3, iterations=1)

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

        # Deterministic ranking for multi-candidate frames.
        ranked = sorted(large_contours, key=lambda c: (-cv2.contourArea(c), -cv2.boundingRect(c)[1]))
        if len(ranked) > 1:
            a0 = cv2.contourArea(ranked[0]) + 1e-9
            a1 = cv2.contourArea(ranked[1])
            if (a1 / a0) >= 0.65:
                print('Multiple large contours detected')
                cv2.drawContours(image, ranked[:2], -1, (0, 255, 0), 2)
                cv2.putText(image, 'Multiple large contours detected', (image.shape[1]//2, image.shape[0]//2), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                return "Multiple", image

        largest_contour = ranked[0]

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
        self._last_droplet_center_px = center_ellipse

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
        




