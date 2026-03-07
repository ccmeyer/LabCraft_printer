import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone

from CalibrationMemoryAggregator import CalibrationMemoryAggregator
from CalibrationIdentity import CalibrationIdentityRegistry


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
    def __init__(self, model=None, identity_registry=None):
        self.model = model
        self.identity_registry = identity_registry

    def set_model(self, model):
        self.model = model

    def set_identity_registry(self, identity_registry):
        self.identity_registry = identity_registry

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

        stock_concentration = None
        stock_units = None
        stock_display_name = None
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
            getter = getattr(stock_solution, "get_stock_name", None)
            if callable(getter):
                try:
                    stock_display_name = self._clean_str(getter())
                except Exception:
                    stock_display_name = None
            if stock_display_name is None:
                stock_display_name = reagent_name

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

        reagent_info = {
            "reagent_id": self._slugify(reagent_name),
            "display_name": reagent_name,
            "reagent_family": None,
            "glycerol_percent": None,
            "tags": [],
            "notes": "",
            "quality": {
                "stock_id": "explicit" if stock_id else "unknown",
                "reagent_id": "inferred" if reagent_name else "unknown",
            },
            "match_source": "derived_from_name" if reagent_name else "unknown",
        }
        head_info = {
            "printer_head_id": None,
            "display_name": None,
            "head_type_id": None,
            "head_type_display_name": None,
            "nominal_nozzle_diameter_um": None,
            "measured_nozzle_diameter_um": None,
            "manufacturer_batch": None,
            "tags": [],
            "notes": "",
            "quality": {
                "printer_head_id": "unknown",
                "head_type_id": "unknown",
                "nominal_nozzle_diameter_um": "unknown",
                "measured_nozzle_diameter_um": "unknown",
            },
            "match_source": {
                "printer_head": "unknown",
                "head_type": "unknown",
            },
        }

        if printer_head is not None:
            fallback_printer_head_id = self._clean_str(getattr(printer_head, "serial", None))
            if fallback_printer_head_id is None:
                fallback_printer_head_id = self._clean_str(getattr(printer_head, "id", None))
            if fallback_printer_head_id:
                head_info["printer_head_id"] = fallback_printer_head_id
                head_info["display_name"] = fallback_printer_head_id
                head_info["quality"]["printer_head_id"] = "explicit"
                head_info["match_source"]["printer_head"] = "runtime_id"
            elif slot_number is not None:
                head_info["printer_head_id"] = f"gripper_slot_{slot_number}"
                head_info["display_name"] = head_info["printer_head_id"]
                head_info["quality"]["printer_head_id"] = "inferred"
                head_info["match_source"]["printer_head"] = "gripper_slot"

        registry = getattr(self, "identity_registry", None)
        if registry is not None:
            try:
                reagent_info = registry.resolve_reagent(
                    stock_solution=stock_solution,
                    stock_id=stock_id,
                    reagent_name=reagent_name,
                )
            except Exception:
                pass
            try:
                head_info = registry.resolve_printer_head(
                    printer_head=printer_head,
                    slot_number=slot_number,
                )
            except Exception:
                pass

        context = {
            "reagent_id": reagent_info.get("reagent_id"),
            "reagent_name": reagent_name,
            "reagent_display_name": reagent_info.get("display_name") or reagent_name,
            "reagent_family": reagent_info.get("reagent_family"),
            "glycerol_percent": reagent_info.get("glycerol_percent"),
            "reagent_tags": list(reagent_info.get("tags") or []),
            "reagent_notes": reagent_info.get("notes") or "",
            "stock_id": stock_id,
            "stock_display_name": stock_display_name,
            "stock_concentration": stock_concentration,
            "stock_units": stock_units,
            "printer_head_id": head_info.get("printer_head_id"),
            "printer_head_display_name": head_info.get("display_name"),
            "gripper_slot_number": slot_number,
            "head_type_id": head_info.get("head_type_id"),
            "head_type_display_name": head_info.get("head_type_display_name"),
            "nominal_nozzle_diameter_um": head_info.get("nominal_nozzle_diameter_um"),
            "measured_nozzle_diameter_um": head_info.get("measured_nozzle_diameter_um"),
            "manufacturer_batch": head_info.get("manufacturer_batch"),
            "printer_head_tags": list(head_info.get("tags") or []),
            "printer_head_notes": head_info.get("notes") or "",
            "nozzle_diameter_um": head_info.get("nominal_nozzle_diameter_um"),
            "profile_name": profile_name,
            "experiment_dir": experiment_dir,
            "calibration_file_path": cal_path,
            "identity_sources": {
                "reagent": reagent_info.get("match_source"),
                "printer_head": (head_info.get("match_source") or {}).get("printer_head"),
                "head_type": (head_info.get("match_source") or {}).get("head_type"),
            },
            "identity_quality": {
                "reagent_id": (reagent_info.get("quality") or {}).get("reagent_id", "unknown"),
                "stock_id": (reagent_info.get("quality") or {}).get("stock_id", stock_quality),
                "printer_head_id": (head_info.get("quality") or {}).get("printer_head_id", "unknown"),
                "head_type_id": (head_info.get("quality") or {}).get("head_type_id", "unknown"),
                "nominal_nozzle_diameter_um": (head_info.get("quality") or {}).get("nominal_nozzle_diameter_um", "unknown"),
                "measured_nozzle_diameter_um": (head_info.get("quality") or {}).get("measured_nozzle_diameter_um", "unknown"),
                "nozzle_diameter_um": (head_info.get("quality") or {}).get("nominal_nozzle_diameter_um", "unknown"),
            },
        }
        return context


class CalibrationMemoryStore:
    SCHEMA_FAMILY = "labcraft.calibration_memory"
    SCHEMA_VERSION = 1
    RUN_SUMMARY_SCHEMA = f"{SCHEMA_FAMILY}.run_summary"
    OBSERVATION_SCHEMA = f"{SCHEMA_FAMILY}.observation"
    RUN_CATALOG_SCHEMA = f"{SCHEMA_FAMILY}.run_catalog_entry"
    RUNTIME_CONFIG_SCHEMA = f"{SCHEMA_FAMILY}.runtime_config"

    PRIOR_MODE_OFF = "off"
    PRIOR_MODE_ADVISORY = "advisory"
    PRIOR_MODE_SEED_START = "seed_start"
    PRIOR_MODE_AGGRESSIVE = "aggressive"
    PRIOR_MODES = (
        PRIOR_MODE_OFF,
        PRIOR_MODE_ADVISORY,
        PRIOR_MODE_SEED_START,
        PRIOR_MODE_AGGRESSIVE,
    )

    def __init__(self, model=None, root_dir=None):
        self.model = model
        base_dir = root_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "CalibrationMemory")
        self.root_dir = os.path.abspath(base_dir)
        self.entities_dir = os.path.join(self.root_dir, "entities")
        self.indices_dir = os.path.join(self.root_dir, "indices")
        self.runs_dir = os.path.join(self.root_dir, "runs")
        self.schema_path = os.path.join(self.root_dir, "schema.json")
        self.runtime_config_path = os.path.join(self.root_dir, "config.json")
        self.run_catalog_path = os.path.join(self.indices_dir, "run_catalog.jsonl")
        self.identity_registry = CalibrationIdentityRegistry(self.root_dir)
        self.aggregator = CalibrationMemoryAggregator(self.root_dir)
        self.context_builder = CalibrationContextBuilder(model, identity_registry=self.identity_registry)
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

    def _warn(self, action, exc):
        print(f"[CalibrationMemory] {action} failed: {exc}")

    @classmethod
    def _default_runtime_config(cls):
        return {
            "schema_name": cls.RUNTIME_CONFIG_SCHEMA,
            "schema_version": int(cls.SCHEMA_VERSION),
            "updated_at_utc": cls._now_utc(),
            "prior_application_mode": cls.PRIOR_MODE_ADVISORY,
            "prior_application_policy": {
                "allowed_aggregation_levels_for_seed_start": [
                    CalibrationMemoryAggregator.AGGREGATION_LEVEL_EXACT_PAIR,
                    CalibrationMemoryAggregator.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE,
                ],
                "min_confidence_by_aggregation_level": {
                    CalibrationMemoryAggregator.AGGREGATION_LEVEL_EXACT_PAIR: 0.80,
                    CalibrationMemoryAggregator.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE: 0.78,
                },
                "max_pulse_distance_us_for_seed_start": 100,
                "max_age_days_for_seed_start": 365,
                "max_target_volume_relative_error": 0.25,
                "allow_grouped_seed_start": False,
                "allow_inferred_identity_seed_start": False,
            },
        }

    @classmethod
    def _normalize_prior_application_mode(cls, value):
        mode = cls._clean_str(value)
        if mode is None:
            return cls.PRIOR_MODE_ADVISORY
        mode = mode.lower()
        if mode not in cls.PRIOR_MODES:
            return cls.PRIOR_MODE_ADVISORY
        if mode == cls.PRIOR_MODE_AGGRESSIVE:
            return cls.PRIOR_MODE_SEED_START
        return mode

    @classmethod
    def _normalize_runtime_config(cls, payload):
        config = cls._default_runtime_config()
        raw = dict(payload or {})
        mode = raw.get("prior_application_mode", config["prior_application_mode"])
        config["prior_application_mode"] = cls._normalize_prior_application_mode(mode)
        policy = dict(config.get("prior_application_policy") or {})
        policy.update(dict(raw.get("prior_application_policy") or {}))
        policy["allowed_aggregation_levels_for_seed_start"] = list(
            dict.fromkeys(str(item) for item in list(policy.get("allowed_aggregation_levels_for_seed_start") or []))
        )
        min_conf = {}
        for key, value in dict(policy.get("min_confidence_by_aggregation_level") or {}).items():
            try:
                min_conf[str(key)] = float(value)
            except Exception:
                continue
        policy["min_confidence_by_aggregation_level"] = min_conf
        for key in (
            "max_pulse_distance_us_for_seed_start",
            "max_age_days_for_seed_start",
        ):
            try:
                policy[key] = int(policy.get(key))
            except Exception:
                policy[key] = int(config["prior_application_policy"][key])
        try:
            policy["max_target_volume_relative_error"] = float(policy.get("max_target_volume_relative_error"))
        except Exception:
            policy["max_target_volume_relative_error"] = float(
                config["prior_application_policy"]["max_target_volume_relative_error"]
            )
        policy["allow_grouped_seed_start"] = bool(policy.get("allow_grouped_seed_start", False))
        policy["allow_inferred_identity_seed_start"] = bool(policy.get("allow_inferred_identity_seed_start", False))
        config["prior_application_policy"] = policy
        config["schema_name"] = cls.RUNTIME_CONFIG_SCHEMA
        config["schema_version"] = int(cls.SCHEMA_VERSION)
        config["updated_at_utc"] = cls._now_utc()
        return config

    def ensure_initialized(self):
        with self._lock:
            os.makedirs(self.root_dir, exist_ok=True)
            os.makedirs(self.entities_dir, exist_ok=True)
            os.makedirs(self.indices_dir, exist_ok=True)
            os.makedirs(self.runs_dir, exist_ok=True)
            self.identity_registry.ensure_initialized()
            self.aggregator.ensure_initialized()
            if not os.path.exists(self.schema_path):
                payload = {
                    "schema_family": self.SCHEMA_FAMILY,
                    "schema_version": int(self.SCHEMA_VERSION),
                    "created_at_utc": self._now_utc(),
                }
                self._write_json_atomic(self.schema_path, payload)
            if not os.path.exists(self.runtime_config_path):
                self._write_json_atomic(self.runtime_config_path, self._default_runtime_config())

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

    @staticmethod
    def _summary_is_completed(payload):
        record = dict(payload or {})
        run_status = str(record.get("run_status") or "").strip().lower()
        if run_status == "completed":
            return True
        run_timing = record.get("run_timing") or {}
        return bool(run_timing.get("ended_at_utc"))

    def refresh_derived_memory(self):
        self.ensure_initialized()
        return self.aggregator.rebuild()

    def get_best_prior(self, context, *, target_pulse_width_us=None, target_volume_nl=None):
        self.ensure_initialized()
        return self.aggregator.get_best_prior(
            context,
            target_pulse_width_us=target_pulse_width_us,
            target_volume_nl=target_volume_nl,
        )

    def load_runtime_config(self):
        self.ensure_initialized()
        try:
            with open(self.runtime_config_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            payload = {}
        normalized = self._normalize_runtime_config(payload)
        if payload != normalized:
            self._write_json_atomic(self.runtime_config_path, normalized)
        return normalized

    def save_runtime_config(self, payload):
        self.ensure_initialized()
        normalized = self._normalize_runtime_config(payload)
        self._write_json_atomic(self.runtime_config_path, normalized)
        return normalized

    def get_prior_application_mode(self):
        config = self.load_runtime_config()
        return self._normalize_prior_application_mode(config.get("prior_application_mode"))

    def set_prior_application_mode(self, mode):
        config = self.load_runtime_config()
        config["prior_application_mode"] = self._normalize_prior_application_mode(mode)
        return self.save_runtime_config(config)

    def get_prior_application_policy(self):
        config = self.load_runtime_config()
        return dict(config.get("prior_application_policy") or {})

    @staticmethod
    def _parse_utc(value):
        if value is None:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    @staticmethod
    def _relative_volume_error(target_volume_nl, expected_volume_nl):
        try:
            target = float(target_volume_nl)
            expected = float(expected_volume_nl)
        except Exception:
            return None
        if abs(target) < 1e-9:
            return None
        return abs(expected - target) / abs(target)

    def qualify_prior_for_application(
        self,
        prior,
        *,
        context=None,
        target_pulse_width_us=None,
        target_volume_nl=None,
    ):
        policy = self.get_prior_application_policy()
        result = {
            "qualified": False,
            "reason": "no_prior",
            "mode": self.get_prior_application_mode(),
            "aggregation_level": None,
            "checks": {},
        }
        if not isinstance(prior, dict):
            return result

        aggregation_level = str(prior.get("aggregation_level") or "")
        confidence = prior.get("recommendation_confidence_adjusted", prior.get("recommendation_confidence"))
        pulse_distance_us = prior.get("pulse_distance_us")
        updated_at = self._parse_utc(prior.get("updated_at_utc"))
        now = datetime.now(timezone.utc)
        age_days = None
        if updated_at is not None:
            age_days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
        min_conf = dict(policy.get("min_confidence_by_aggregation_level") or {}).get(aggregation_level)
        allowed_levels = list(policy.get("allowed_aggregation_levels_for_seed_start") or [])
        allow_grouped = bool(policy.get("allow_grouped_seed_start", False))
        max_pulse_distance_us = int(policy.get("max_pulse_distance_us_for_seed_start", 100))
        max_age_days = int(policy.get("max_age_days_for_seed_start", 365))
        max_target_volume_relative_error = float(policy.get("max_target_volume_relative_error", 0.25))
        allow_inferred_identity = bool(policy.get("allow_inferred_identity_seed_start", False))

        quality_summary = dict(prior.get("identity_quality_summary") or {})
        inferred_identity_present = False
        for field_name in ("reagent_id", "printer_head_id", "head_type_id"):
            counts = dict(quality_summary.get(field_name) or {})
            if int(counts.get("inferred", 0) or 0) > 0 or int(counts.get("unknown", 0) or 0) > 0:
                inferred_identity_present = True
                break

        relative_volume_error = self._relative_volume_error(
            target_volume_nl,
            prior.get("expected_mean_volume_nL"),
        )
        grouped_level = aggregation_level not in (
            CalibrationMemoryAggregator.AGGREGATION_LEVEL_EXACT_PAIR,
            CalibrationMemoryAggregator.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE,
        )

        checks = {
            "allowed_aggregation_level": aggregation_level in allowed_levels or (allow_grouped and grouped_level),
            "confidence_threshold_met": (confidence is not None and min_conf is not None and float(confidence) >= float(min_conf)),
            "pulse_distance_ok": (
                pulse_distance_us is None or int(abs(float(pulse_distance_us))) <= int(max_pulse_distance_us)
            ),
            "age_ok": (age_days is None or age_days <= float(max_age_days)),
            "target_volume_ok": (
                relative_volume_error is None
                or relative_volume_error <= float(max_target_volume_relative_error)
            ),
            "identity_quality_ok": (allow_inferred_identity or not inferred_identity_present),
            "recommended_pressure_present": prior.get("recommended_pressure_psi") is not None
            or prior.get("stable_single_droplet_band_psi") is not None
            or prior.get("trajectory_pressure_band_psi") is not None,
        }
        result["checks"] = checks
        result["aggregation_level"] = aggregation_level
        result["confidence"] = None if confidence is None else float(confidence)
        result["pulse_distance_us"] = None if pulse_distance_us is None else int(abs(float(pulse_distance_us)))
        result["age_days"] = None if age_days is None else round(float(age_days), 3)
        result["relative_target_volume_error"] = (
            None if relative_volume_error is None else round(float(relative_volume_error), 4)
        )
        result["min_confidence_required"] = None if min_conf is None else float(min_conf)

        for reason, ok in (
            ("aggregation_level_not_allowed", checks["allowed_aggregation_level"]),
            ("confidence_below_threshold", checks["confidence_threshold_met"]),
            ("pulse_distance_too_large", checks["pulse_distance_ok"]),
            ("prior_is_stale", checks["age_ok"]),
            ("target_volume_incompatible", checks["target_volume_ok"]),
            ("identity_quality_too_weak", checks["identity_quality_ok"]),
            ("missing_seed_pressure", checks["recommended_pressure_present"]),
        ):
            if not ok:
                result["reason"] = reason
                return result

        result["qualified"] = True
        result["reason"] = "qualified"
        return result

    def derive_prior_seed_values(
        self,
        prior,
        *,
        baseline_start_pressure_psi=None,
        pressure_bounds=None,
    ):
        if not isinstance(prior, dict):
            raise ValueError("prior is required")

        stable_band = prior.get("stable_single_droplet_band_psi")
        trajectory_band = prior.get("trajectory_pressure_band_psi")
        recommended_pressure = prior.get("recommended_pressure_psi")
        seed_pressure = None
        seed_source = None
        if recommended_pressure is not None:
            seed_pressure = float(recommended_pressure)
            seed_source = "recommended_pressure_psi"
        elif isinstance(stable_band, (list, tuple)) and len(stable_band) == 2:
            seed_pressure = float((float(stable_band[0]) + float(stable_band[1])) / 2.0)
            seed_source = "stable_single_droplet_band_midpoint"
        elif isinstance(trajectory_band, (list, tuple)) and len(trajectory_band) == 2:
            seed_pressure = float((float(trajectory_band[0]) + float(trajectory_band[1])) / 2.0)
            seed_source = "trajectory_pressure_band_midpoint"
        else:
            raise ValueError("prior does not contain a usable seed pressure")

        clamped = False
        clamped_to_bounds = None
        if isinstance(pressure_bounds, (list, tuple)) and len(pressure_bounds) == 2:
            lo = float(min(pressure_bounds[0], pressure_bounds[1]))
            hi = float(max(pressure_bounds[0], pressure_bounds[1]))
            original = seed_pressure
            seed_pressure = max(lo, min(hi, seed_pressure))
            clamped = abs(seed_pressure - original) > 1e-9
            clamped_to_bounds = [lo, hi]

        return {
            "start_pressure_psi": float(seed_pressure),
            "baseline_start_pressure_psi": (
                None if baseline_start_pressure_psi is None else float(baseline_start_pressure_psi)
            ),
            "seed_pressure_delta_from_baseline_psi": (
                None
                if baseline_start_pressure_psi is None
                else float(seed_pressure) - float(baseline_start_pressure_psi)
            ),
            "seed_source": seed_source,
            "seed_single_droplet_band_psi": stable_band,
            "seed_trajectory_pressure_band_psi": trajectory_band,
            "seed_expected_mean_volume_nL": prior.get("expected_mean_volume_nL"),
            "seed_expected_cv_pct": prior.get("expected_cv_pct"),
            "seed_pulse_width_us": prior.get("pulse_width_us"),
            "pressure_bounds_psi": clamped_to_bounds,
            "clamped_to_bounds": bool(clamped),
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
        advisory_prior=None,
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
        prior_runtime = {}
        if calibration_manager is not None:
            try:
                runtime_getter = getattr(calibration_manager, "get_calibration_memory_prior_runtime_summary", None)
                if callable(runtime_getter):
                    prior_runtime = dict(runtime_getter() or {})
            except Exception:
                prior_runtime = {}
        run_idx = getattr(calibration_manager, "_run_idx", None) if calibration_manager is not None else None
        summary = {
            "schema_name": self.RUN_SUMMARY_SCHEMA,
            "schema_version": int(self.SCHEMA_VERSION),
            "run_id": run_id,
            "context": context,
            "run_status": "in_progress",
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
            "authoritative_refs": {
                "calibration_json_path": self._clean_str(getattr(calibration_manager, "calibration_file_path", None)),
                "calibration_run_id": run_id,
                "calibration_run_index": run_idx,
            },
            "manager_meta": dict(manager_meta or {}),
            "advisory_prior": dict(advisory_prior or {}) if advisory_prior else None,
            "prior_application_mode": prior_runtime.get("mode", self.get_prior_application_mode()),
            "prior_lookup_performed": bool(prior_runtime.get("looked_up")),
            "prior_candidate_found": bool(prior_runtime.get("candidate_found")) or bool(advisory_prior),
            "prior_candidate": dict(prior_runtime.get("candidate") or advisory_prior or {}),
            "prior_applied": bool(prior_runtime.get("applied")),
            "prior_application_reason": prior_runtime.get("application_reason"),
            "prior_rejected_reason": prior_runtime.get("rejected_reason"),
            "prior_seed_values": dict(prior_runtime.get("seed_values") or {}),
            "prior_fallback_triggered": bool(prior_runtime.get("fallback_triggered")),
            "prior_fallback_reason": prior_runtime.get("fallback_reason"),
            "prior_usefulness_summary": dict(prior_runtime.get("usefulness_summary") or {}),
            "prior_qualification": dict(prior_runtime.get("qualification") or {}),
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
                "reagent_family": context.get("reagent_family"),
                "printer_head_id": context.get("printer_head_id"),
                "printer_head_display_name": context.get("printer_head_display_name"),
                "head_type_id": context.get("head_type_id"),
                "nominal_nozzle_diameter_um": context.get("nominal_nozzle_diameter_um"),
                "nozzle_diameter_um": context.get("nozzle_diameter_um"),
                "identity_quality": context.get("identity_quality", {}),
                "identity_sources": context.get("identity_sources", {}),
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
        if self._summary_is_completed(record):
            try:
                self.refresh_derived_memory()
            except Exception as e:
                self._warn("refresh_derived_memory", e)
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
        paths = self.get_run_paths(run_id)

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

        run_status = "completed" if self._clean_str(run.get("ended_at")) else "in_progress"
        advisory_prior = getattr(calibration_manager, "_calibration_memory_prior_candidate", None)

        manager_meta = {}
        try:
            meta_getter = getattr(calibration_manager, "_build_recorder_meta", None)
            if callable(meta_getter):
                manager_meta = dict(meta_getter() or {})
        except Exception:
            manager_meta = {}

        summary = {
            "schema_name": self.RUN_SUMMARY_SCHEMA,
            "schema_version": int(self.SCHEMA_VERSION),
            "run_id": run_id,
            "context": context,
            "run_status": run_status,
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
            "source_refs": {
                "run_summary_path": paths["run_summary_path"],
                "observations_path": paths["observations_path"],
            },
            "manager_meta": manager_meta,
            "advisory_prior": dict(advisory_prior or {}) if advisory_prior else None,
            "last_updated_at_utc": self._now_utc(),
        }
        try:
            summary["derived_metrics"] = self.aggregator.extract_run_features(summary, authoritative_run=run)
        except Exception as e:
            self._warn("extract_run_features", e)
            summary["derived_metrics"] = {
                "schema_name": f"{self.SCHEMA_FAMILY}.run_features",
                "schema_version": int(self.SCHEMA_VERSION),
                "usable_for_aggregation": False,
                "qualification_reasons": ["feature_extraction_failed"],
            }
        prior_runtime_summary = {}
        try:
            runtime_getter = getattr(calibration_manager, "get_calibration_memory_prior_runtime_summary", None)
            if callable(runtime_getter):
                prior_runtime_summary = dict(runtime_getter(derived_metrics=summary.get("derived_metrics")) or {})
        except Exception as e:
            self._warn("get_prior_runtime_summary", e)
            prior_runtime_summary = {}
        summary["prior_application_mode"] = prior_runtime_summary.get("mode")
        summary["prior_lookup_performed"] = bool(prior_runtime_summary.get("looked_up"))
        summary["prior_candidate_found"] = bool(prior_runtime_summary.get("candidate_found"))
        summary["prior_qualified"] = bool(prior_runtime_summary.get("qualified"))
        summary["prior_candidate"] = dict(prior_runtime_summary.get("candidate") or {})
        summary["prior_applied"] = bool(prior_runtime_summary.get("applied"))
        summary["prior_application_reason"] = prior_runtime_summary.get("application_reason")
        summary["prior_rejected_reason"] = prior_runtime_summary.get("rejected_reason")
        summary["prior_seed_values"] = dict(prior_runtime_summary.get("seed_values") or {})
        summary["prior_fallback_triggered"] = bool(prior_runtime_summary.get("fallback_triggered"))
        summary["prior_fallback_reason"] = prior_runtime_summary.get("fallback_reason")
        summary["prior_usefulness_summary"] = dict(prior_runtime_summary.get("usefulness_summary") or {})
        summary["prior_qualification"] = dict(prior_runtime_summary.get("qualification") or {})
        if not summary.get("advisory_prior") and summary["prior_candidate"]:
            summary["advisory_prior"] = dict(summary["prior_candidate"])
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
