from types import SimpleNamespace

import pytest

from Controller import Controller


def _build_controller(current_location, current_z, target):
    calls = []
    c = Controller.__new__(Controller)
    c.profile = SimpleNamespace(name="current")
    c.expected_position = {"X": 0, "Y": 0, "Z": current_z}
    c.expected_location = current_location
    c.model = SimpleNamespace(
        location_model=SimpleNamespace(get_location_dict=lambda name: target.copy())
    )
    c.set_absolute_Z = lambda z, **kwargs: calls.append(("z", z))
    c.set_absolute_Y = lambda y, **kwargs: calls.append(("y", y))
    c.set_absolute_X = lambda x, **kwargs: calls.append(("x", x))
    c.set_absolute_coordinates = lambda x, y, z, **kwargs: calls.append(("xyz", x, y, z))
    c.update_location_handler = lambda **kwargs: None
    return c, calls


@pytest.mark.parametrize(
    "current_z,target_z",
    [
        (36000, 30000),  # current below safe height (numerically deeper)
        (30000, 36000),  # target below safe height (numerically deeper)
        (36000, 36000),  # both below safe height
    ],
)
def test_move_to_location_enforces_safe_z_when_below_threshold(current_z, target_z):
    target = {"X": 1000, "Y": 2000, "Z": target_z}
    c, calls = _build_controller("camera", current_z, target)

    Controller.move_to_location(c, "plate")

    assert ("z", 35000) in calls
    assert calls.index(("z", 35000)) < calls.index(("xyz", 1000, 2000, target_z))


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


def test_move_to_location_ignore_safe_height_skips_safe_z_when_requested():
    target = {"X": 1000, "Y": 2000, "Z": 60000}
    c, calls = _build_controller("camera", 50000, target)

    Controller.move_to_location(c, "plate", ignore_safe_height=True)

    assert ("z", 35000) not in calls
    assert calls[-1] == ("xyz", 1000, 2000, 60000)


def test_move_to_location_when_already_above_safe_height_skips_safe_z():
    target = {"X": 1000, "Y": 2000, "Z": 32000}
    c, calls = _build_controller("camera", 30000, target)

    Controller.move_to_location(c, "plate")

    assert ("z", 35000) not in calls
    assert calls[-1] == ("xyz", 1000, 2000, 32000)
