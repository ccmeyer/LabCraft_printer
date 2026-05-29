import json
import os
import tempfile
from pathlib import Path


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


def get_machine_config_path(filename: str) -> Path:
    """Return the ignored local machine config path, seeding it from Presets once."""
    if filename not in _EXPECTED_TOP_LEVEL_TYPES:
        supported = ", ".join(sorted(_EXPECTED_TOP_LEVEL_TYPES))
        raise ValueError(f"Unsupported machine config '{filename}'. Supported: {supported}")

    local_path = LOCAL_DIR / filename
    if local_path.exists():
        _validate_json_file(local_path, filename)
        return local_path

    preset_path = PRESETS_DIR / filename
    _validate_json_file(preset_path, filename)
    _atomic_copy_bytes(preset_path, local_path)
    _validate_json_file(local_path, filename)
    return local_path


def get_calibration_memory_root() -> Path:
    """Return the ignored local calibration-memory root, seeding starter JSONs once."""
    local_root = LOCAL_DIR / "CalibrationMemory"

    for relative_path, expected_type in _CALIBRATION_MEMORY_SEED_TYPES.items():
        local_path = local_root / relative_path
        if local_path.exists():
            _validate_json_top_level(local_path, expected_type, relative_path)
            continue

        template_path = CALIBRATION_MEMORY_TEMPLATE_DIR / relative_path
        _validate_json_top_level(template_path, expected_type, relative_path)
        _atomic_copy_bytes(template_path, local_path)
        _validate_json_top_level(local_path, expected_type, relative_path)

    return local_root
