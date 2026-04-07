import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
TOOLS_DIR = REPO_ROOT / "tools"


def _run_bootstrap_probe(code: str):
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert lines, f"Probe returned no output. stderr={result.stderr!r}"
    return json.loads(lines[-1])


def test_calibration_model_bootstraps_repo_root_for_ui_script_like_imports():
    code = f"""
import importlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(r"{REPO_ROOT}")
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
TOOLS_DIR = REPO_ROOT / "tools"

from tests.calibration_test_utils import ensure_calibration_import_stubs
ensure_calibration_import_stubs(force=True)

sys.path[:] = [str(UI_DIR)] + [
    p for p in sys.path
    if p not in ("", str(REPO_ROOT), str(UI_DIR), str(TOOLS_DIR))
]

for name in list(sys.modules):
    if name == "CalibrationClasses" or name.startswith("CalibrationClasses."):
        sys.modules.pop(name, None)
    if name == "tools" or name.startswith("tools."):
        sys.modules.pop(name, None)

module = importlib.import_module("CalibrationClasses.Model")

print(json.dumps({{
    "repo_root_on_path": str(REPO_ROOT) in sys.path,
    "tools_runtime_loaded": "tools.stream_analysis.online_runtime" in sys.modules,
    "has_online_fit": hasattr(module, "online_fit_mod"),
}}))
"""
    payload = _run_bootstrap_probe(code)

    assert payload["repo_root_on_path"] is True
    assert payload["tools_runtime_loaded"] is True
    assert payload["has_online_fit"] is True


def test_replay_calibration_run_bootstraps_repo_root_before_ui_imports():
    code = f"""
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(r"{REPO_ROOT}")
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
TOOLS_DIR = REPO_ROOT / "tools"

from tests.calibration_test_utils import ensure_calibration_import_stubs
ensure_calibration_import_stubs(force=True)

sys.path[:] = [str(TOOLS_DIR)] + [
    p for p in sys.path
    if p not in ("", str(REPO_ROOT), str(UI_DIR), str(TOOLS_DIR))
]

for name in list(sys.modules):
    if name == "CalibrationClasses" or name.startswith("CalibrationClasses."):
        sys.modules.pop(name, None)
    if name == "tools" or name.startswith("tools."):
        sys.modules.pop(name, None)
    if name == "replay_calibration_run_bootstrap":
        sys.modules.pop(name, None)

spec = importlib.util.spec_from_file_location(
    "replay_calibration_run_bootstrap",
    REPO_ROOT / "tools" / "replay_calibration_run.py",
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

print(json.dumps({{
    "repo_root_on_path": str(REPO_ROOT) in sys.path,
    "ui_dir_on_path": str(UI_DIR) in sys.path,
    "has_process": hasattr(module, "NozzlePositionCalibrationProcess"),
}}))
"""
    payload = _run_bootstrap_probe(code)

    assert payload["repo_root_on_path"] is True
    assert payload["ui_dir_on_path"] is True
    assert payload["has_process"] is True
