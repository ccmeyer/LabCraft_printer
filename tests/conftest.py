import os
import sys
import types
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.fakes import FakeSerialFactory, FakeSerialMain, FakeSignal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))


def _ensure_optional_module(name: str) -> None:
    if importlib.util.find_spec(name) is None and name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)


for _mod in ("cv2", "joblib", "pandas", "numpy"):
    _ensure_optional_module(_mod)


def _ensure_pyside6_stub() -> None:
    if importlib.util.find_spec("PySide6") is not None or "PySide6" in sys.modules:
        return

    pyside6 = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")

    class _Signal:
        def __init__(self, *args, **kwargs):
            self._subs = []

        def connect(self, fn):
            self._subs.append(fn)

        def disconnect(self, fn):
            if fn in self._subs:
                self._subs.remove(fn)

        def emit(self, *args, **kwargs):
            for fn in list(self._subs):
                fn(*args, **kwargs)

    class _QObject:
        def __init__(self, *args, **kwargs):
            super().__init__()

    class _QThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            return None

    class _QTimer:
        def __init__(self, parent=None):
            self._interval = 0
            self.timeout = _Signal()

        def setInterval(self, ms):
            self._interval = ms

        def start(self):
            return None

        def stop(self):
            return None

    class _QApplication:
        _instance = None

        def __init__(self, *args, **kwargs):
            _QApplication._instance = self

        @staticmethod
        def instance():
            return _QApplication._instance

    qtcore.Signal = _Signal
    qtcore.QObject = _QObject
    qtcore.QThread = _QThread
    qtcore.QTimer = _QTimer
    qtcore.Slot = lambda *a, **k: (lambda fn: fn)
    qtwidgets.QApplication = _QApplication

    pyside6.QtCore = qtcore
    pyside6.QtWidgets = qtwidgets

    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtWidgets"] = qtwidgets


_ensure_pyside6_stub()


def _ensure_serial_stub() -> None:
    if importlib.util.find_spec("serial") is not None or "serial" in sys.modules:
        return

    serial_mod = types.ModuleType("serial")
    tools_mod = types.ModuleType("serial.tools")
    list_ports_mod = types.ModuleType("serial.tools.list_ports")

    class SerialException(Exception):
        pass

    list_ports_mod.comports = lambda: []
    tools_mod.list_ports = list_ports_mod
    serial_mod.tools = tools_mod
    serial_mod.SerialException = SerialException

    sys.modules["serial"] = serial_mod
    sys.modules["serial.tools"] = tools_mod
    sys.modules["serial.tools.list_ports"] = list_ports_mod


_ensure_serial_stub()

if "numpy" in sys.modules:
    _np = sys.modules["numpy"]
    if not hasattr(_np, "array"):
        _np.array = lambda x, *a, **k: x
    if not hasattr(_np, "zeros"):
        _np.zeros = lambda n, *a, **k: [0 for _ in range(n if isinstance(n, int) else 0)]


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def test_profile():
    return SimpleNamespace(
        name="current",
        has_refuel_camera=False,
        has_droplet_camera=False,
        has_log_channel=False,
    )


@pytest.fixture
def fake_signal():
    return FakeSignal()


@pytest.fixture
def fake_serial_main():
    return FakeSerialMain()


@pytest.fixture
def fake_serial_factory():
    return FakeSerialFactory()


@pytest.fixture
def experiment_model_factory(tmp_path):
    import json
    from types import SimpleNamespace

    from hardware.profile import CURRENT_PROFILE
    from Model import (
        Model,
        ExperimentModel,
        StockSolutionManager,
        ReactionCollection,
        WellPlate,
    )

    plates_src = REPO_ROOT / "FreeRTOS-interface" / "Presets" / "Plates.json"
    plates_data = json.loads(plates_src.read_text(encoding="utf-8"))

    def _make(*, plate_data_override=None):
        m = Model.__new__(Model)
        m.experiment_model = ExperimentModel(prof=CURRENT_PROFILE)

        plate_data = plate_data_override if plate_data_override is not None else plates_data
        plates_tmp = tmp_path / "Plates.json"
        plates_tmp.write_text(json.dumps(plate_data), encoding="utf-8")
        m.well_plate = WellPlate(plate_data, str(plates_tmp))

        m.stock_solutions = StockSolutionManager()
        m.reaction_collection = ReactionCollection()
        m.experiment_loaded = SimpleNamespace(emit=lambda *a, **k: None)

        m.clear_experiment = lambda: (
            m.stock_solutions.clear_all_stock_solutions(),
            m.reaction_collection.clear_all_reactions(),
            m.well_plate.clear_all_wells(),
        )
        m.assign_printer_heads = lambda: None

        exp_dir = tmp_path / f"exp_{id(m)}"
        exp_dir.mkdir(exist_ok=True)
        m.experiment_model.experiment_dir_path = str(exp_dir)
        m.experiment_model.update_all_paths()

        return m

    return _make
