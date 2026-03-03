import sys
import types

if "Model" not in sys.modules:
    fake_model = types.ModuleType("Model")
    fake_model.Model = object
    fake_model.PrinterHead = object
    fake_model.Slot = object
    sys.modules["Model"] = fake_model

from types import SimpleNamespace

import pytest

from Controller import Controller


def _build_controller(current_location, current_z, target, *, profile_name="current"):
    calls = []
    c = Controller.__new__(Controller)
    c.profile = SimpleNamespace(name=profile_name)
    c.expected_position = {"X": 0, "Y": 0, "Z": current_z}
    c.expected_location = current_location
    c.model = SimpleNamespace(
        location_model=SimpleNamespace(get_location_dict=lambda name: target.copy())
    )
    c.error_occurred_signal = SimpleNamespace(emit=lambda *args, **kwargs: None)
    c.set_absolute_Z = lambda z, **kwargs: calls.append(("z", z))
    c.set_absolute_Y = lambda y, **kwargs: calls.append(("y", y))
    c.set_absolute_X = lambda x, **kwargs: calls.append(("x", x))
    c.set_absolute_coordinates = lambda x, y, z, **kwargs: calls.append(("xyz", x, y, z))
    c.update_location_handler = lambda **kwargs: None
    return c, calls


@pytest.mark.parametrize(
    "profile_name,safe_z,current_z,target_z",
    [
        ("current", 35000, 36000, 36000),  # both at/below safe height (numerically deeper)
        ("legacy", 5000, 6000, 6000),      # both at/below safe height (legacy)
    ],
)
def test_move_to_location_enforces_safe_z_when_below_threshold(profile_name, safe_z, current_z, target_z):
    target = {"X": 1000, "Y": 2000, "Z": target_z}
    c, calls = _build_controller("camera", current_z, target, profile_name=profile_name)

    Controller.move_to_location(c, "plate")

    assert ("z", safe_z) in calls
    assert calls.index(("z", safe_z)) < calls.index(("xyz", 1000, 2000, target_z))


def test_move_to_location_camera_to_home_skips_safe_z_when_target_is_above_safe_plane():
    target = {"X": 1000, "Y": 2000, "Z": 30000}
    c, calls = _build_controller("camera", 50000, target)

    Controller.move_to_location(c, "home")

    assert ("z", 35000) not in calls
    assert calls[-1] == ("xyz", 1000, 2000, 30000)


def test_move_to_location_slot_to_home_skips_safe_z_when_target_is_above_safe_plane():
    target = {"X": 700, "Y": 800, "Z": 30000}
    c, calls = _build_controller("slot-2", 50000, target)

    Controller.move_to_location(c, "home")

    assert ("z", 35000) not in calls
    assert calls[-1] == ("xyz", 700, 800, 30000)


def test_move_to_location_camera_transition_applies_safe_z_before_xyz():
    target = {"X": 1000, "Y": 2000, "Z": 60000}
    c, calls = _build_controller("camera", 50000, target)

    Controller.move_to_location(c, "plate")

    assert ("z", 35000) in calls
    assert calls.index(("z", 35000)) < calls.index(("xyz", 1000, 2000, 60000))
    assert c.expected_location == "plate"


def test_move_to_location_slot_transition_applies_safe_z_before_xyz():
    target = {"X": 700, "Y": 800, "Z": 60000}
    c, calls = _build_controller("pause", 50000, target)

    Controller.move_to_location(c, "Slot-1")

    assert ("z", 35000) in calls
    assert calls.index(("z", 35000)) < calls.index(("xyz", 700, 800, 60000))
    assert c.expected_location == "Slot-1"


def test_move_to_location_balance_route_applies_safe_z_then_safe_y_then_x_then_xyz():
    target = {"X": 1111, "Y": 2222, "Z": 60000}
    c, calls = _build_controller("pause", 50000, target)

    Controller.move_to_location(c, "balance")

    z_idx = calls.index(("z", 35000))
    y_idx = calls.index(("y", 15000))
    x_idx = calls.index(("x", 1111))
    xyz_idx = calls.index(("xyz", 1111, 2222, 60000))
    assert z_idx < y_idx < x_idx < xyz_idx
    assert c.expected_location == "balance"


def test_move_to_location_legacy_profile_uses_legacy_safe_height_before_balance_route():
    target = {"X": 1111, "Y": 2222, "Z": 6500}
    c, calls = _build_controller("pause", 6200, target, profile_name="legacy")

    Controller.move_to_location(c, "balance")

    z_idx = calls.index(("z", 5000))
    y_idx = calls.index(("y", 15000))
    x_idx = calls.index(("x", 1111))
    xyz_idx = calls.index(("xyz", 1111, 2222, 6500))
    assert z_idx < y_idx < x_idx < xyz_idx


def test_move_to_location_ignore_safe_height_skips_safe_z_when_requested():
    target = {"X": 1000, "Y": 2000, "Z": 60000}
    c, calls = _build_controller("camera", 50000, target)

    Controller.move_to_location(c, "plate", ignore_safe_height=True)

    assert ("z", 35000) not in calls
    assert calls[-1] == ("xyz", 1000, 2000, 60000)


@pytest.mark.parametrize(
    "profile_name,safe_z,current_z,target_z",
    [
        # Inverted Z convention: smaller numeric Z means physically higher.
        ("current", 35000, 30000, 32000),
        ("legacy", 5000, 3000, 4000),
    ],
)
def test_move_to_location_inverted_z_convention_skips_safe_z_when_already_high(
    profile_name, safe_z, current_z, target_z
):
    target = {"X": 1000, "Y": 2000, "Z": target_z}
    c, calls = _build_controller("camera", current_z, target, profile_name=profile_name)

    Controller.move_to_location(c, "plate")

    assert ("z", safe_z) not in calls
    assert calls[-1] == ("xyz", 1000, 2000, target_z)


def test_move_to_location_above_safe_height_skips_safe_z_even_if_target_below_safe():
    target = {"X": 1000, "Y": 2000, "Z": 50000}
    c, calls = _build_controller("camera", 30000, target)

    Controller.move_to_location(c, "plate")

    assert ("z", 35000) not in calls
    assert calls[-1] == ("xyz", 1000, 2000, 50000)


def test_move_to_location_missing_location_returns_false_and_stops():
    calls = []
    errors = []
    c = Controller.__new__(Controller)
    c.profile = SimpleNamespace(name="current")
    c.expected_position = {"X": 0, "Y": 0, "Z": 50000}
    c.expected_location = "pause"
    c.error_occurred_signal = SimpleNamespace(emit=lambda title, msg: errors.append((title, msg)))
    c.model = SimpleNamespace(
        location_model=SimpleNamespace(get_location_dict=lambda name: None)
    )
    c.set_absolute_Z = lambda z, **kwargs: calls.append(("z", z))
    c.set_absolute_Y = lambda y, **kwargs: calls.append(("y", y))
    c.set_absolute_X = lambda x, **kwargs: calls.append(("x", x))
    c.set_absolute_coordinates = lambda x, y, z, **kwargs: calls.append(("xyz", x, y, z))
    c.update_location_handler = lambda **kwargs: None

    ok = Controller.move_to_location(c, "does-not-exist")

    assert ok is False
    assert calls == []
    assert errors and "not found" in errors[-1][1]


def test_move_to_location_aborts_when_safe_z_guard_move_fails():
    target = {"X": 1000, "Y": 2000, "Z": 60000}
    c, calls = _build_controller("camera", 50000, target)
    errors = []
    c.error_occurred_signal = SimpleNamespace(emit=lambda title, msg: errors.append((title, msg)))
    c.set_absolute_Z = lambda z, **kwargs: False

    ok = Controller.move_to_location(c, "plate")

    assert ok is False
    assert calls == []
    assert errors and "safe Z" in errors[-1][1]


def test_move_to_location_slot_detection_is_case_insensitive():
    target = {"X": 700, "Y": 800, "Z": 60000}
    c, calls = _build_controller("slot-1", 50000, target)

    Controller.move_to_location(c, "pause")

    assert ("z", 35000) in calls


def test_move_to_location_balance_respects_ignore_safe_height():
    target = {"X": 1111, "Y": 2222, "Z": 60000}
    c, calls = _build_controller("pause", 50000, target)

    Controller.move_to_location(c, "balance", ignore_safe_height=True)

    assert ("z", 35000) not in calls
    assert ("y", 15000) in calls
    assert ("x", 1111) in calls
