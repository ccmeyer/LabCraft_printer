import json
import os
import tempfile
import copy
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType


REPO_ROOT = Path(__file__).resolve().parents[1]
PRESETS_DIR = Path(__file__).resolve().parent / "Presets"
CALIBRATION_MEMORY_TEMPLATE_DIR = Path(__file__).resolve().parent / "CalibrationMemory"
LOCAL_DIR = REPO_ROOT / "local"

_EXPECTED_TOP_LEVEL_TYPES = {
    "Settings.json": dict,
    "Plates.json": list,
    "Locations.json": dict,
    "Obstacles.json": dict,
    "RegulatorProfiles.json": dict,
}

_CALIBRATION_MEMORY_SEED_TYPES = {
    "schema.json": dict,
    "config.json": dict,
    "entities/reagents.json": dict,
    "entities/printer_head_types.json": dict,
    "entities/printer_heads.json": dict,
}

_MACHINE_CONFIG_TOP_LEVEL_TYPES_VIEW = MappingProxyType(_EXPECTED_TOP_LEVEL_TYPES)
_CALIBRATION_MEMORY_SEED_TYPES_VIEW = MappingProxyType(_CALIBRATION_MEMORY_SEED_TYPES)


def machine_config_top_level_types() -> Mapping[str, type]:
    """Return the read-only managed machine-config filename/type contract."""
    return _MACHINE_CONFIG_TOP_LEVEL_TYPES_VIEW


def calibration_memory_seed_top_level_types() -> Mapping[str, type]:
    """Return the read-only CalibrationMemory starter-file contract."""
    return _CALIBRATION_MEMORY_SEED_TYPES_VIEW


def _validate_json_top_level(path: Path, expected_type: type, label: str):
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as exc:
        raise ValueError(f"Invalid machine config '{path}': {exc}") from exc

    if not isinstance(payload, expected_type):
        expected_name = expected_type.__name__
        actual_name = type(payload).__name__
        raise ValueError(
            f"Invalid machine config '{path}': expected top-level {expected_name}, got {actual_name}"
        )
    return payload


def _validate_json_file(path: Path, filename: str):
    expected_type = _EXPECTED_TOP_LEVEL_TYPES[filename]
    return _validate_json_top_level(path, expected_type, filename)


def validate_machine_config_file(path: str | Path, filename: str):
    """Validate a managed config file using the existing production contract."""
    if filename not in _EXPECTED_TOP_LEVEL_TYPES:
        supported = ", ".join(sorted(_EXPECTED_TOP_LEVEL_TYPES))
        raise ValueError(f"Unsupported machine config '{filename}'. Supported: {supported}")
    return _validate_json_file(Path(path), filename)


def validate_machine_config_payload(filename: str, payload):
    """Validate a complete governed document without writing it.

    These are structural compatibility checks.  Motion bounds and calibration
    geometry belong to the guarded-change policy, not this persistence layer.
    """

    if filename not in _EXPECTED_TOP_LEVEL_TYPES:
        supported = ", ".join(sorted(_EXPECTED_TOP_LEVEL_TYPES))
        raise ValueError(f"Unsupported machine config '{filename}'. Supported: {supported}")
    expected_type = _EXPECTED_TOP_LEVEL_TYPES[filename]
    if not isinstance(payload, expected_type):
        raise ValueError(
            f"Invalid {filename}: expected top-level {expected_type.__name__}, "
            f"got {type(payload).__name__}"
        )
    try:
        # Round-trip also rejects non-JSON objects and non-finite floats.
        cloned = json.loads(
            json.dumps(payload, ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {filename}: {exc}") from exc

    if filename == "Locations.json":
        folded = set()
        for name, coords in cloned.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Locations.json names must be nonempty text.")
            key = name.casefold()
            if key in folded:
                raise ValueError("Locations.json names must be unique ignoring case.")
            folded.add(key)
            if not isinstance(coords, dict):
                raise ValueError(f"Location {name!r} must be an object.")
            for axis in ("X", "Y", "Z"):
                value = coords.get(axis)
                if type(value) is not int:
                    raise ValueError(f"Location {name!r} {axis} must be an integer.")

    elif filename == "Plates.json":
        names = set()
        default_count = 0
        corners = {"top_left", "top_right", "bottom_right", "bottom_left"}
        required = {"name", "rows", "columns", "spacing", "default", "calibrations"}
        if not cloned:
            raise ValueError("Plates.json must contain at least one plate.")
        for plate in cloned:
            if not isinstance(plate, dict) or not required.issubset(plate):
                raise ValueError("Every plate must contain the required plate fields.")
            name = plate.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Plate names must be nonempty text.")
            key = name.casefold()
            if key in names:
                raise ValueError("Plate names must be unique ignoring case.")
            names.add(key)
            if type(plate.get("rows")) is not int or plate["rows"] <= 0:
                raise ValueError(f"Plate {name!r} rows must be a positive integer.")
            if type(plate.get("columns")) is not int or plate["columns"] <= 0:
                raise ValueError(f"Plate {name!r} columns must be a positive integer.")
            spacing = plate.get("spacing")
            if isinstance(spacing, bool) or not isinstance(spacing, (int, float)) or spacing <= 0:
                raise ValueError(f"Plate {name!r} spacing must be positive.")
            if type(plate.get("default")) is not bool:
                raise ValueError(f"Plate {name!r} default must be a boolean.")
            default_count += int(plate["default"])
            calibrations = plate.get("calibrations")
            if not isinstance(calibrations, dict):
                raise ValueError(f"Plate {name!r} calibrations must be an object.")
            if calibrations and set(calibrations) != corners:
                raise ValueError(f"Plate {name!r} calibration must contain all four corners.")
            for corner, coords in calibrations.items():
                if not isinstance(coords, dict):
                    raise ValueError(f"Plate {name!r} {corner} must be an object.")
                for axis in ("X", "Y", "Z"):
                    if type(coords.get(axis)) is not int:
                        raise ValueError(f"Plate {name!r} {corner} {axis} must be an integer.")
        if default_count != 1:
            raise ValueError("Plates.json must define exactly one default plate.")

    elif filename == "Settings.json":
        profile = cloned.get("HARDWARE_PROFILE", "current")
        if not isinstance(profile, str) or not profile.strip():
            raise ValueError("Settings.json HARDWARE_PROFILE must be nonempty text.")
        default_plate = cloned.get("DEFAULT_PLATE")
        if not isinstance(default_plate, str) or not default_plate.strip():
            raise ValueError("Settings.json DEFAULT_PLATE must be nonempty text.")

    elif filename == "Obstacles.json":
        if "boundaries" in cloned and not isinstance(cloned["boundaries"], (dict, list)):
            raise ValueError("Obstacles.json boundaries must be an object or list.")
        if "obstacles" in cloned and not isinstance(cloned["obstacles"], list):
            raise ValueError("Obstacles.json obstacles must be a list.")

    return copy.deepcopy(cloned)


def _atomic_copy_bytes(source: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def get_machine_config_path(
    filename: str,
    *,
    local_root: str | Path | None = None,
) -> Path:
    """Return the ignored local machine config path, seeding it from Presets once."""
    if filename not in _EXPECTED_TOP_LEVEL_TYPES:
        supported = ", ".join(sorted(_EXPECTED_TOP_LEVEL_TYPES))
        raise ValueError(f"Unsupported machine config '{filename}'. Supported: {supported}")

    root = Path(local_root) if local_root is not None else LOCAL_DIR
    local_path = root / filename
    if local_path.exists():
        _validate_json_file(local_path, filename)
        return local_path

    preset_path = PRESETS_DIR / filename
    _validate_json_file(preset_path, filename)
    _atomic_copy_bytes(preset_path, local_path)
    _validate_json_file(local_path, filename)
    return local_path


def get_existing_machine_config_path(
    filename: str,
    *,
    config_root: str | Path,
) -> Path:
    """Return an existing canonical config file without preset fallback."""

    if filename not in _EXPECTED_TOP_LEVEL_TYPES:
        supported = ", ".join(sorted(_EXPECTED_TOP_LEVEL_TYPES))
        raise ValueError(f"Unsupported machine config '{filename}'. Supported: {supported}")
    if config_root is None:
        raise ValueError("Canonical config_root is required.")
    root = Path(config_root).expanduser().resolve(strict=False)
    path = (root / filename).resolve(strict=False)
    if root not in path.parents or path.parent != root:
        raise ValueError(f"Canonical config path escaped its root: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Canonical machine config is missing: {path}")
    _validate_json_file(path, filename)
    return path


def get_calibration_memory_root(
    *,
    local_root: str | Path | None = None,
) -> Path:
    """Return the ignored local calibration-memory root, seeding starter JSONs once."""
    target_root = (
        Path(local_root)
        if local_root is not None
        else LOCAL_DIR / "CalibrationMemory"
    )

    for relative_path, expected_type in _CALIBRATION_MEMORY_SEED_TYPES.items():
        local_path = target_root / relative_path
        if local_path.exists():
            _validate_json_top_level(local_path, expected_type, relative_path)
            continue

        template_path = CALIBRATION_MEMORY_TEMPLATE_DIR / relative_path
        _validate_json_top_level(template_path, expected_type, relative_path)
        _atomic_copy_bytes(template_path, local_path)
        _validate_json_top_level(local_path, expected_type, relative_path)

    return target_root


def get_existing_calibration_memory_root(
    *,
    root: str | Path,
) -> Path:
    """Validate the migrated CalibrationMemory baseline without creating it."""

    if root is None:
        raise ValueError("Canonical CalibrationMemory root is required.")
    target_root = Path(root).expanduser().resolve(strict=False)
    if not target_root.is_dir():
        raise FileNotFoundError(
            f"Canonical CalibrationMemory root is missing: {target_root}"
        )
    for relative_path, expected_type in _CALIBRATION_MEMORY_SEED_TYPES.items():
        path = (target_root / relative_path).resolve(strict=False)
        if target_root not in path.parents or not path.is_file():
            raise FileNotFoundError(
                f"Canonical CalibrationMemory baseline is missing: {path}"
            )
        _validate_json_top_level(path, expected_type, relative_path)
    return target_root
