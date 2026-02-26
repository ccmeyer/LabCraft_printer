import os
import sys
import types
import importlib.util
from pathlib import Path
from types import SimpleNamespace

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


@pytest.fixture
def test_profile():
    return SimpleNamespace(
        name="current",
        has_refuel_camera=False,
        has_droplet_camera=False,
        has_log_channel=False,
    )


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
