import os
import sys
import types
import importlib.util
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))


def _ensure_optional_module(name: str) -> None:
    if importlib.util.find_spec(name) is None and name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)


for _mod in ("cv2", "joblib", "pandas"):
    _ensure_optional_module(_mod)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
