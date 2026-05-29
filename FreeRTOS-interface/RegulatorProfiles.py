import copy
import json
import os
import tempfile
from pathlib import Path

import LocalConfig


SCHEMA_VERSION = 1
PROFILE_FILENAME = "RegulatorProfiles.json"
MODES = {"droplet", "stream", "custom"}
REQUIRED_ACTIVE_MODES = ("droplet", "stream")
CHANNELS = ("print", "refuel")

SOURCE_KINDS = {
    "factory_default",
    "calibration_candidate",
    "promoted",
    "manual",
}

RECOVERY_BOUNDS = {
    "active_ticks": (0, 20),
    "base_boost_hz": (0, 6000),
    "pulse_coeff_hz_per_us": (0, 4),
    "pressure_coeff_hz_per_raw": (0, 4),
    "max_boost_hz": (0, 12000),
    "recovery_floor_hz": (0, 5000),
    "recovery_exit_error_raw": (1, 30),
    "max_extend_ticks": (0, 10),
}

RECOVERY_BOOL_FIELDS = (
    "allow_extend_while_undershoot",
    "boost_only_when_undershoot",
    "linear_decay",
)

SLEW_BOUNDS = {
    "max_hz_delta_up_per_loop": (1, 2500),
    "max_hz_delta_down_per_loop": (1, 2500),
    "recovery_bypass_slew_ticks": (0, 5),
}

READY_BOUNDS = {
    "ready_tol_raw": (1, 25),
    "consecutive_samples": (1, 5),
}

SOURCE_FIELDS = {
    "kind",
    "run_id",
    "promoted_at_utc",
    "operator",
    "notes",
}

CONDITION_TEXT_FIELDS = (
    "printer_head_id",
    "printer_head_type",
    "reagent_id",
)

CONDITION_NUMERIC_FIELDS = (
    "print_pressure_psi",
    "print_pulse_width_us",
    "refuel_pressure_psi",
    "refuel_pulse_width_us",
    "frequency_hz",
)


class RegulatorProfileError(ValueError):
    pass


def default_local_profile_path():
    return LocalConfig.LOCAL_DIR / PROFILE_FILENAME


def _default_channel_configs():
    return {
        "print": {
            "recovery": {
                "active_ticks": 2,
                "base_boost_hz": 300,
                "pulse_coeff_hz_per_us": 1,
                "pressure_coeff_hz_per_raw": 0,
                "max_boost_hz": 1500,
                "recovery_floor_hz": 0,
                "recovery_exit_error_raw": 3,
                "max_extend_ticks": 0,
                "allow_extend_while_undershoot": False,
                "boost_only_when_undershoot": True,
                "linear_decay": True,
            },
            "slew": {
                "max_hz_delta_up_per_loop": 600,
                "max_hz_delta_down_per_loop": 1200,
                "recovery_bypass_slew_ticks": 0,
            },
            "ready": {
                "ready_tol_raw": 4,
                "consecutive_samples": 1,
            },
        },
        "refuel": {
            "recovery": {
                "active_ticks": 8,
                "base_boost_hz": 2000,
                "pulse_coeff_hz_per_us": 2,
                "pressure_coeff_hz_per_raw": 1,
                "max_boost_hz": 10000,
                "recovery_floor_hz": 1200,
                "recovery_exit_error_raw": 4,
                "max_extend_ticks": 4,
                "allow_extend_while_undershoot": True,
                "boost_only_when_undershoot": True,
                "linear_decay": True,
            },
            "slew": {
                "max_hz_delta_up_per_loop": 1200,
                "max_hz_delta_down_per_loop": 450,
                "recovery_bypass_slew_ticks": 3,
            },
            "ready": {
                "ready_tol_raw": 4,
                "consecutive_samples": 1,
            },
        },
    }


def _default_profile(profile_id, mode, description):
    profile = {
        "profile_id": profile_id,
        "mode": mode,
        "description": description,
        "source": {
            "kind": "factory_default",
            "run_id": None,
            "promoted_at_utc": None,
            "operator": None,
            "notes": "",
        },
        "conditions": {
            "printer_head_id": None,
            "printer_head_type": None,
            "reagent_id": None,
            "print_pressure_psi": None,
            "print_pulse_width_us": None,
            "refuel_pressure_psi": None,
            "refuel_pulse_width_us": None,
            "frequency_hz": 20,
        },
    }
    profile.update(_default_channel_configs())
    return profile


def factory_default_document():
    return {
        "schema_version": SCHEMA_VERSION,
        "active_profiles": {
            "droplet": "droplet_default",
            "stream": "stream_default",
        },
        "profiles": {
            "droplet_default": _default_profile(
                "droplet_default",
                "droplet",
                "Default droplet-mode regulator profile",
            ),
            "stream_default": _default_profile(
                "stream_default",
                "stream",
                "Default stream-mode regulator profile",
            ),
        },
    }


def _profile_error(path, message):
    if path:
        return RegulatorProfileError(f"{path}: {message}")
    return RegulatorProfileError(message)


def _require_object(payload, label, path=None):
    if not isinstance(payload, dict):
        raise _profile_error(path, f"{label} must be an object")
    return payload


def _require_string(value, label, *, allow_empty=False, allow_none=False, path=None):
    if value is None and allow_none:
        return value
    if not isinstance(value, str):
        raise _profile_error(path, f"{label} must be a string")
    if not allow_empty and not value.strip():
        raise _profile_error(path, f"{label} cannot be empty")
    return value


def _require_int(config, field, min_value, max_value, path=None):
    if field not in config:
        raise _profile_error(path, f"missing required field {field}")
    value = config[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _profile_error(path, f"{field} must be an integer")
    if value < min_value or value > max_value:
        raise _profile_error(path, f"{field} out of range: {value} not in ({min_value},{max_value})")
    return value


def _require_bool(config, field, path=None):
    if field not in config:
        raise _profile_error(path, f"missing required field {field}")
    if not isinstance(config[field], bool):
        raise _profile_error(path, f"{field} must be a boolean")
    return config[field]


def _validate_bounded_ints(config, bounds, label, path=None):
    _require_object(config, label, path=path)
    for field, (min_value, max_value) in bounds.items():
        _require_int(config, field, min_value, max_value, path=path)


def _validate_recovery(config, path=None):
    _validate_bounded_ints(config, RECOVERY_BOUNDS, "recovery", path=path)
    for field in RECOVERY_BOOL_FIELDS:
        _require_bool(config, field, path=path)


def _validate_source(source, path=None):
    _require_object(source, "source", path=path)
    missing = SOURCE_FIELDS - set(source)
    if missing:
        raise _profile_error(path, f"source missing required fields: {sorted(missing)}")
    kind = _require_string(source["kind"], "source.kind", path=path)
    if kind not in SOURCE_KINDS:
        raise _profile_error(path, f"source.kind must be one of {sorted(SOURCE_KINDS)}")
    _require_string(source["run_id"], "source.run_id", allow_none=True, path=path)
    _require_string(source["promoted_at_utc"], "source.promoted_at_utc", allow_none=True, path=path)
    _require_string(source["operator"], "source.operator", allow_none=True, path=path)
    _require_string(source["notes"], "source.notes", allow_empty=True, path=path)


def _validate_conditions(conditions, path=None):
    _require_object(conditions, "conditions", path=path)
    for field in CONDITION_TEXT_FIELDS:
        if field not in conditions:
            raise _profile_error(path, f"conditions missing required field {field}")
        _require_string(conditions[field], f"conditions.{field}", allow_none=True, path=path)
    for field in CONDITION_NUMERIC_FIELDS:
        if field not in conditions:
            raise _profile_error(path, f"conditions missing required field {field}")
        value = conditions[field]
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _profile_error(path, f"conditions.{field} must be numeric or null")


def validate_profile(profile, profile_id=None):
    profile = copy.deepcopy(profile)
    _require_object(profile, "profile")

    if "profile_id" not in profile:
        raise RegulatorProfileError("profile missing required field profile_id")
    actual_profile_id = _require_string(profile["profile_id"], "profile_id")
    if profile_id is not None and actual_profile_id != profile_id:
        raise RegulatorProfileError(f"profile_id must match profiles key {profile_id}")

    mode = _require_string(profile.get("mode"), "mode")
    if mode not in MODES:
        raise RegulatorProfileError(f"mode must be one of {sorted(MODES)}")
    _require_string(profile.get("description"), "description", allow_empty=True)

    for section in ("source", "conditions", "print", "refuel"):
        if section not in profile:
            raise RegulatorProfileError(f"profile {actual_profile_id} missing required section {section}")

    _validate_source(profile["source"], path=f"profile {actual_profile_id}")
    _validate_conditions(profile["conditions"], path=f"profile {actual_profile_id}")

    for channel in CHANNELS:
        channel_config = _require_object(profile[channel], f"{channel} channel", path=f"profile {actual_profile_id}")
        for section in ("recovery", "slew", "ready"):
            if section not in channel_config:
                raise RegulatorProfileError(
                    f"profile {actual_profile_id} {channel} channel missing required section {section}"
                )
        _validate_recovery(channel_config["recovery"], path=f"profile {actual_profile_id} {channel}.recovery")
        _validate_bounded_ints(channel_config["slew"], SLEW_BOUNDS, "slew", path=f"profile {actual_profile_id} {channel}.slew")
        _validate_bounded_ints(channel_config["ready"], READY_BOUNDS, "ready", path=f"profile {actual_profile_id} {channel}.ready")

    return profile


def validate_document(payload):
    document = copy.deepcopy(payload)
    _require_object(document, "RegulatorProfiles document")

    if document.get("schema_version") != SCHEMA_VERSION:
        raise RegulatorProfileError(f"schema_version must be {SCHEMA_VERSION}")
    active_profiles = _require_object(document.get("active_profiles"), "active_profiles")
    profiles = _require_object(document.get("profiles"), "profiles")

    for mode in REQUIRED_ACTIVE_MODES:
        if mode not in active_profiles:
            raise RegulatorProfileError(f"active_profiles missing required mode {mode}")

    validated_profiles = {}
    for profile_id, profile in profiles.items():
        profile_id = _require_string(profile_id, "profile key")
        validated_profiles[profile_id] = validate_profile(profile, profile_id=profile_id)
    document["profiles"] = validated_profiles

    for mode, active_profile_id in active_profiles.items():
        mode = _require_string(mode, "active_profiles key")
        if active_profile_id is None:
            continue
        _require_string(active_profile_id, f"active_profiles.{mode}")
        if active_profile_id not in validated_profiles:
            raise RegulatorProfileError(f"active profile {active_profile_id} for mode {mode} does not exist")
        if mode in MODES and validated_profiles[active_profile_id]["mode"] != mode:
            raise RegulatorProfileError(
                f"active profile {active_profile_id} mode {validated_profiles[active_profile_id]['mode']} "
                f"does not match active mode {mode}"
            )

    return document


def write_json_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class RegulatorProfileStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self.document = None

    def _resolve_path(self):
        if self.path is None:
            self.path = default_local_profile_path()
            self.path = Path(LocalConfig.get_machine_config_path(PROFILE_FILENAME))
        return self.path

    def load(self):
        path = self._resolve_path()
        if not path.exists():
            self.document = factory_default_document()
            return copy.deepcopy(self.document)
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            raise RegulatorProfileError(f"Invalid regulator profiles file '{path}': {exc}") from exc
        self.document = validate_document(payload)
        return copy.deepcopy(self.document)

    def save(self, document=None):
        path = self._resolve_path()
        if document is None:
            document = self.document if self.document is not None else factory_default_document()
        validated = validate_document(document)
        write_json_atomic(path, validated)
        self.document = copy.deepcopy(validated)
        return copy.deepcopy(self.document)

    def _ensure_loaded(self):
        if self.document is None:
            self.load()

    def get_active_profile(self, mode):
        self._ensure_loaded()
        mode = str(mode or "").strip().lower()
        active_profile_id = self.document.get("active_profiles", {}).get(mode)
        if active_profile_id is None:
            return None
        profile = self.document.get("profiles", {}).get(active_profile_id)
        return copy.deepcopy(profile) if profile is not None else None

    def list_profiles(self):
        self._ensure_loaded()
        profiles = self.document.get("profiles", {})
        return [
            copy.deepcopy(profiles[profile_id])
            for profile_id in sorted(profiles)
        ]

    def upsert_profile(self, profile, make_active=False):
        self._ensure_loaded()
        validated_profile = validate_profile(profile)
        profile_id = validated_profile["profile_id"]
        document = copy.deepcopy(self.document)
        document["profiles"][profile_id] = validated_profile
        if make_active:
            document["active_profiles"][validated_profile["mode"]] = profile_id
        self.document = validate_document(document)
        return copy.deepcopy(validated_profile)

    def set_active_profile(self, mode, profile_id_or_none):
        self._ensure_loaded()
        mode = str(mode or "").strip().lower()
        if mode not in MODES:
            raise RegulatorProfileError(f"mode must be one of {sorted(MODES)}")
        document = copy.deepcopy(self.document)
        if profile_id_or_none is None:
            document["active_profiles"][mode] = None
        else:
            profile_id = _require_string(profile_id_or_none, "profile_id")
            if profile_id not in document["profiles"]:
                raise RegulatorProfileError(f"profile {profile_id} does not exist")
            if document["profiles"][profile_id]["mode"] != mode:
                raise RegulatorProfileError(f"profile {profile_id} mode does not match {mode}")
            document["active_profiles"][mode] = profile_id
        self.document = validate_document(document)
        return copy.deepcopy(self.document)
