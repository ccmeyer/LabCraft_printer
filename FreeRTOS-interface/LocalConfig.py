import json
import os
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PRESETS_DIR = Path(__file__).resolve().parent / "Presets"
LOCAL_DIR = REPO_ROOT / "local"

_EXPECTED_TOP_LEVEL_TYPES = {
    "Settings.json": dict,
    "Plates.json": list,
    "Locations.json": dict,
    "Obstacles.json": dict,
}


def _validate_json_file(path: Path, filename: str):
    expected_type = _EXPECTED_TOP_LEVEL_TYPES[filename]
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
