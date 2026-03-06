import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone


def _json_default(obj):
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
    try:
        return obj.__json__()
    except Exception:
        pass
    return str(obj)


class CalibrationContextBuilder:
    def __init__(self, model=None):
        self.model = model

    def set_model(self, model):
        self.model = model

    @staticmethod
    def _now_utc():
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _clean_str(value):
        if value is None:
            return None
        out = str(value).strip()
        return out or None

    @staticmethod
    def _slugify(value):
        value = CalibrationContextBuilder._clean_str(value)
        if value is None:
            return None
        chars = []
        prev_us = False
        for ch in value.lower():
            if ch.isalnum():
                chars.append(ch)
                prev_us = False
            else:
                if not prev_us:
                    chars.append("_")
                    prev_us = True
        slug = "".join(chars).strip("_")
        return slug or None

    def _get_model(self, model=None):
        return model or self.model

    def _get_gripper_printer_head(self, model=None):
        mdl = self._get_model(model)
        if mdl is None:
            return None
        try:
            rack = getattr(mdl, "rack_model", None)
            if rack is None:
                return None
            getter = getattr(rack, "get_gripper_printer_head", None)
            if callable(getter):
                return getter()
        except Exception:
            return None
        return None

    def _get_gripper_slot_number(self, model=None):
        mdl = self._get_model(model)
        if mdl is None:
            return None
        rack = getattr(mdl, "rack_model", None)
        if rack is None:
            return None
        try:
            slot_number = getattr(rack, "gripper_slot_number", None)
            if slot_number is None:
                return None
            return int(slot_number)
        except Exception:
            return None

    def _get_stock_solution(self, printer_head):
        if printer_head is None:
            return None
        try:
            getter = getattr(printer_head, "get_stock_solution", None)
            if callable(getter):
                return getter()
        except Exception:
            return None
        return getattr(printer_head, "stock_solution", None)

    def build(self, *, model=None, calibration_file_path=None):
        mdl = self._get_model(model)
        printer_head = self._get_gripper_printer_head(model=mdl)
        stock_solution = self._get_stock_solution(printer_head)
        slot_number = self._get_gripper_slot_number(model=mdl)

        stock_id = None
        stock_quality = "missing"
        if stock_solution is not None:
            try:
                getter = getattr(stock_solution, "get_stock_id", None)
                if callable(getter):
                    stock_id = self._clean_str(getter())
            except Exception:
                stock_id = None
        if stock_id:
            stock_quality = "explicit"

        reagent_name = None
        if stock_solution is not None:
            try:
                getter = getattr(stock_solution, "get_reagent_name", None)
                if callable(getter):
                    reagent_name = self._clean_str(getter())
            except Exception:
                reagent_name = None
            if reagent_name is None:
                reagent_name = self._clean_str(getattr(stock_solution, "reagent_name", None))

        reagent_id = self._slugify(reagent_name)
        reagent_quality = "derived" if reagent_id else "missing"

        stock_concentration = None
        stock_units = None
        if stock_solution is not None:
            try:
                getter = getattr(stock_solution, "get_stock_concentration", None)
                if callable(getter):
                    stock_concentration = self._clean_str(getter())
            except Exception:
                stock_concentration = None
            if stock_concentration is None:
                stock_concentration = self._clean_str(getattr(stock_solution, "concentration", None))
            stock_units = self._clean_str(getattr(stock_solution, "units", None))

        printer_head_id = None
        printer_head_quality = "missing"
        if printer_head is not None:
            printer_head_id = self._clean_str(getattr(printer_head, "serial", None))
            if printer_head_id is None:
                printer_head_id = self._clean_str(getattr(printer_head, "id", None))
            if printer_head_id:
                printer_head_quality = "explicit"
            elif slot_number is not None:
                printer_head_id = f"gripper_slot_{slot_number}"
                printer_head_quality = "derived"

        experiment_dir = None
        if mdl is not None:
            try:
                experiment_dir = self._clean_str(
                    getattr(getattr(mdl, "experiment_model", None), "experiment_dir_path", None)
                )
            except Exception:
                experiment_dir = None

        cal_path = self._clean_str(calibration_file_path)
        if cal_path is None and mdl is not None:
            try:
                exp = getattr(mdl, "experiment_model", None)
                getter = getattr(exp, "get_calibration_file_path", None)
                if callable(getter):
                    cal_path = self._clean_str(getter())
                if cal_path is None:
                    cal_path = self._clean_str(getattr(exp, "calibration_file_path", None))
            except Exception:
                cal_path = None

        if experiment_dir is None and cal_path:
            experiment_dir = os.path.dirname(cal_path)

        profile_name = None
        if mdl is not None:
            profile_name = self._clean_str(getattr(getattr(mdl, "profile", None), "name", None))

        context = {
            "reagent_id": reagent_id,
            "reagent_name": reagent_name,
            "reagent_display_name": reagent_name,
            "stock_id": stock_id,
            "stock_concentration": stock_concentration,
            "stock_units": stock_units,
            "printer_head_id": printer_head_id,
            "gripper_slot_number": slot_number,
            "head_type_id": None,
            "nozzle_diameter_um": None,
            "profile_name": profile_name,
            "experiment_dir": experiment_dir,
            "calibration_file_path": cal_path,
            "identity_quality": {
                "reagent_id": reagent_quality,
                "stock_id": stock_quality,
                "printer_head_id": printer_head_quality,
                "head_type_id": "missing",
                "nozzle_diameter_um": "missing",
            },
        }
        return context


class CalibrationMemoryStore:
    SCHEMA_FAMILY = "labcraft.calibration_memory"
    SCHEMA_VERSION = 1
    RUN_SUMMARY_SCHEMA = f"{SCHEMA_FAMILY}.run_summary"
    OBSERVATION_SCHEMA = f"{SCHEMA_FAMILY}.observation"
    RUN_CATALOG_SCHEMA = f"{SCHEMA_FAMILY}.run_catalog_entry"

    def __init__(self, model=None, root_dir=None):
        self.model = model
        base_dir = root_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "CalibrationMemory")
        self.root_dir = os.path.abspath(base_dir)
        self.entities_dir = os.path.join(self.root_dir, "entities")
        self.indices_dir = os.path.join(self.root_dir, "indices")
        self.runs_dir = os.path.join(self.root_dir, "runs")
        self.schema_path = os.path.join(self.root_dir, "schema.json")
        self.run_catalog_path = os.path.join(self.indices_dir, "run_catalog.jsonl")
        self.context_builder = CalibrationContextBuilder(model)
        self._lock = threading.Lock()

    @staticmethod
    def _now_utc():
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _clean_str(value):
        if value is None:
            return None
        out = str(value).strip()
        return out or None

    def set_model(self, model):
        self.model = model
        self.context_builder.set_model(model)

    def ensure_initialized(self):
        with self._lock:
            os.makedirs(self.root_dir, exist_ok=True)
            os.makedirs(self.entities_dir, exist_ok=True)
            os.makedirs(self.indices_dir, exist_ok=True)
            os.makedirs(self.runs_dir, exist_ok=True)
            if not os.path.exists(self.schema_path):
                payload = {
                    "schema_family": self.SCHEMA_FAMILY,
                    "schema_version": int(self.SCHEMA_VERSION),
                    "created_at_utc": self._now_utc(),
                }
                self._write_json_atomic(self.schema_path, payload)

    @staticmethod
    def _write_json_atomic(path, payload):
        path = os.path.abspath(path)
        parent = os.path.dirname(path)
        os.makedirs(parent, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix="._tmp_",
            suffix=os.path.splitext(path)[1] or ".tmp",
            dir=parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, default=_json_default)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            except Exception:
                pass
            raise

    @staticmethod
    def _append_jsonl(path, payload):
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=_json_default) + "\n")

    def _get_run_dir(self, run_id):
        return os.path.join(self.runs_dir, str(run_id))

    def _get_run_summary_path(self, run_id):
        return os.path.join(self._get_run_dir(run_id), "run_summary.json")

    def _get_observations_path(self, run_id):
        return os.path.join(self._get_run_dir(run_id), "observations.jsonl")

    def get_run_paths(self, run_id):
        run_dir = self._get_run_dir(run_id)
        return {
            "run_dir": run_dir,
            "run_summary_path": self._get_run_summary_path(run_id),
            "observations_path": self._get_observations_path(run_id),
        }

    def _build_artifact_refs(self, *, context=None, calibration_manager=None):
        context = dict(context or {})
        calibration_path = self._clean_str(context.get("calibration_file_path"))
        experiment_dir = self._clean_str(context.get("experiment_dir"))
        if experiment_dir is None and calibration_path:
            experiment_dir = os.path.dirname(calibration_path)

        camera_root = None
        camera_active_dir = None
        model = getattr(calibration_manager, "model", None) if calibration_manager is not None else self.model
        if model is not None:
            try:
                cam = getattr(model, "droplet_camera_model", None)
                if cam is not None:
                    getter = getattr(cam, "get_save_root_directory", None)
                    if callable(getter):
                        camera_root = self._clean_str(getter())
                    getter = getattr(cam, "get_active_save_directory", None)
                    if callable(getter):
                        camera_active_dir = self._clean_str(getter())
            except Exception:
                camera_root = None
                camera_active_dir = None

        process_recordings_root = None
        if experiment_dir is not None:
            process_recordings_root = os.path.abspath(os.path.join(experiment_dir, "calibration_recordings"))

        return {
            "calibration_json_path": calibration_path,
            "process_recordings_root": process_recordings_root,
            "camera_capture_root": camera_root,
            "camera_active_save_dir": camera_active_dir,
        }

    def create_run(
        self,
        run_id,
        *,
        context=None,
        calibration_manager=None,
        notes=None,
        manager_meta=None,
    ):
        self.ensure_initialized()
        run_id = str(run_id)
        if context is None:
            model = getattr(calibration_manager, "model", None) if calibration_manager is not None else self.model
            calibration_file_path = getattr(calibration_manager, "calibration_file_path", None)
            context = self.context_builder.build(model=model, calibration_file_path=calibration_file_path)

        paths = self.get_run_paths(run_id)
        os.makedirs(paths["run_dir"], exist_ok=True)
        open(paths["observations_path"], "a", encoding="utf-8").close()

        now = self._now_utc()
        summary = {
            "schema_name": self.RUN_SUMMARY_SCHEMA,
            "schema_version": int(self.SCHEMA_VERSION),
            "run_id": run_id,
            "context": context,
            "run_timing": {
                "started_at_utc": now,
                "ended_at_utc": None,
            },
            "notes": str(notes or ""),
            "phase_counts": {},
            "process_results": {},
            "artifact_refs": self._build_artifact_refs(context=context, calibration_manager=calibration_manager),
            "source_refs": {
                "run_summary_path": paths["run_summary_path"],
                "observations_path": paths["observations_path"],
            },
            "manager_meta": dict(manager_meta or {}),
            "last_updated_at_utc": now,
        }
        self.write_run_summary(run_id, summary)

        catalog_entry = {
            "schema_name": self.RUN_CATALOG_SCHEMA,
            "schema_version": int(self.SCHEMA_VERSION),
            "run_id": run_id,
            "created_at_utc": now,
            "context": {
                "reagent_id": context.get("reagent_id"),
                "stock_id": context.get("stock_id"),
                "reagent_display_name": context.get("reagent_display_name"),
                "printer_head_id": context.get("printer_head_id"),
                "head_type_id": context.get("head_type_id"),
                "nozzle_diameter_um": context.get("nozzle_diameter_um"),
                "identity_quality": context.get("identity_quality", {}),
            },
            "notes": str(notes or ""),
            "paths": paths,
        }
        self.append_run_catalog(catalog_entry)
        return paths

    def append_run_catalog(self, payload):
        self.ensure_initialized()
        record = dict(payload or {})
        record.setdefault("schema_name", self.RUN_CATALOG_SCHEMA)
        record.setdefault("schema_version", int(self.SCHEMA_VERSION))
        record.setdefault("created_at_utc", self._now_utc())
        self._append_jsonl(self.run_catalog_path, record)
        return record

    def write_run_summary(self, run_id, payload):
        self.ensure_initialized()
        record = dict(payload or {})
        record["schema_name"] = self.RUN_SUMMARY_SCHEMA
        record["schema_version"] = int(self.SCHEMA_VERSION)
        record["run_id"] = str(run_id)
        record.setdefault("last_updated_at_utc", self._now_utc())
        self._write_json_atomic(self._get_run_summary_path(run_id), record)
        return record

    def append_observation(self, run_id, payload):
        self.ensure_initialized()
        record = dict(payload or {})
        record["schema_name"] = self.OBSERVATION_SCHEMA
        record["schema_version"] = int(self.SCHEMA_VERSION)
        record["run_id"] = str(run_id)
        record.setdefault("observation_id", f"obs_{uuid.uuid4().hex}")
        record.setdefault("ts_utc", self._now_utc())
        self._append_jsonl(self._get_observations_path(run_id), record)
        return record

    def build_run_summary(self, calibration_manager):
        if calibration_manager is None:
            raise ValueError("calibration_manager is required")

        run = None
        run_idx = getattr(calibration_manager, "_run_idx", None)
        data = getattr(calibration_manager, "data", {}) or {}
        runs = data.get("runs") or []
        if isinstance(run_idx, int) and 0 <= run_idx < len(runs):
            run = runs[run_idx]
        else:
            run_id = getattr(calibration_manager, "_run_id", None)
            if run_id is not None:
                for candidate in reversed(runs):
                    if candidate.get("run_id") == run_id:
                        run = candidate
                        break
        if run is None:
            raise ValueError("no active calibration run available for summary")

        context = self.context_builder.build(
            model=getattr(calibration_manager, "model", None),
            calibration_file_path=getattr(calibration_manager, "calibration_file_path", None),
        )
        run_id = str(run.get("run_id") or getattr(calibration_manager, "_run_id", ""))

        phase_counts = {}
        process_results = {}
        for phase_name, steps in (run.get("steps") or {}).items():
            step_list = list(steps or [])
            phase_counts[phase_name] = len(step_list)
            if not step_list:
                continue
            latest = step_list[-1]
            result_entry = {
                "step_count": len(step_list),
                "latest_timestamp": latest.get("timestamp"),
                "latest_settings": latest.get("settings"),
                "latest_meta": latest.get("meta"),
            }
            if isinstance(latest.get("result"), dict):
                result_entry["latest_result"] = latest.get("result")
            else:
                result_entry["latest_payload"] = latest
            process_results[phase_name] = result_entry

        summary = {
            "schema_name": self.RUN_SUMMARY_SCHEMA,
            "schema_version": int(self.SCHEMA_VERSION),
            "run_id": run_id,
            "context": context,
            "run_timing": {
                "started_at_utc": run.get("started_at"),
                "ended_at_utc": run.get("ended_at"),
            },
            "notes": str(run.get("notes") or ""),
            "phase_counts": phase_counts,
            "process_results": process_results,
            "artifact_refs": self._build_artifact_refs(context=context, calibration_manager=calibration_manager),
            "authoritative_refs": {
                "calibration_json_path": self._clean_str(getattr(calibration_manager, "calibration_file_path", None)),
                "calibration_run_id": run_id,
                "calibration_run_index": run_idx,
            },
            "last_updated_at_utc": self._now_utc(),
        }
        return summary

    def build_observation(
        self,
        calibration_manager,
        observation_type,
        payload,
        *,
        phase_name=None,
        artifact_refs=None,
    ):
        if calibration_manager is None:
            raise ValueError("calibration_manager is required")

        run_id = getattr(calibration_manager, "_run_id", None)
        if not run_id:
            raise ValueError("calibration_manager has no active run id")

        context = self.context_builder.build(
            model=getattr(calibration_manager, "model", None),
            calibration_file_path=getattr(calibration_manager, "calibration_file_path", None),
        )

        try:
            settings = calibration_manager.get_current_settings()
        except Exception:
            settings = {}

        machine_pos = None
        if isinstance(settings, dict):
            machine_pos = settings.get("current_position")

        phase = phase_name
        if phase is None:
            phase = getattr(getattr(calibration_manager, "activeCalibration", None), "phase_name", None)
        resolver = getattr(calibration_manager, "_resolve_phase_key", None)
        if callable(resolver) and phase is not None:
            phase = resolver(phase)

        return {
            "schema_name": self.OBSERVATION_SCHEMA,
            "schema_version": int(self.SCHEMA_VERSION),
            "observation_id": f"obs_{uuid.uuid4().hex}",
            "run_id": str(run_id),
            "ts_utc": self._now_utc(),
            "phase": self._clean_str(phase),
            "observation_type": str(observation_type),
            "context": context,
            "settings": settings or {},
            "machine": {
                "position": machine_pos,
            },
            "payload": dict(payload or {}),
            "artifact_refs": dict(artifact_refs or {}),
        }

    def append_observation_from_manager(
        self,
        calibration_manager,
        observation_type,
        payload,
        *,
        phase_name=None,
        artifact_refs=None,
    ):
        record = self.build_observation(
            calibration_manager,
            observation_type,
            payload,
            phase_name=phase_name,
            artifact_refs=artifact_refs,
        )
        return self.append_observation(record["run_id"], record)
