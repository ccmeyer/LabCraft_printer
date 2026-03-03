import sys
import types

if "Model" not in sys.modules:
    fake_model = types.ModuleType("Model")
    fake_model.Model = object
    fake_model.PrinterHead = object
    fake_model.Slot = object
    sys.modules["Model"] = fake_model

from types import SimpleNamespace

from Controller import Controller


def _controller_with_config(boundaries, obstacles):
    c = Controller.__new__(Controller)
    c.model = SimpleNamespace(
        location_model=SimpleNamespace(
            get_boundaries=lambda: boundaries,
            get_obstacles=lambda: obstacles,
        )
    )
    return c


def test_check_collision_missing_boundaries_is_safe_blocking():
    c = _controller_with_config([], [])
    assert Controller.check_collision(c, {"X": 0, "Y": 0, "Z": 0}, {"X": 1, "Y": 1, "Z": 1}) is True


def test_check_collision_invalid_obstacle_payload_is_safe_blocking():
    boundaries = {
        "min": {"X": -500, "Y": 0, "Z": 0},
        "max": {"X": 80000, "Y": 50000, "Z": 130000},
    }
    c = _controller_with_config(boundaries, [{"corner1": {"X": 0}}])
    assert Controller.check_collision(c, {"X": 0, "Y": 0, "Z": 0}, {"X": 1, "Y": 1, "Z": 1}) is True
