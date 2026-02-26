from types import SimpleNamespace

from Controller import Controller


def test_move_to_location_camera_transition_raises_to_safe_z():
    calls = []
    c = Controller.__new__(Controller)
    c.profile = SimpleNamespace(name="current")
    c.expected_position = {"X": 0, "Y": 0, "Z": 50000}
    c.expected_location = "camera"
    c.model = SimpleNamespace(
        location_model=SimpleNamespace(get_location_dict=lambda name: {"X": 1000, "Y": 2000, "Z": 60000})
    )
    c.set_absolute_Z = lambda z, **kwargs: calls.append(("z", z))
    c.set_absolute_Y = lambda y, **kwargs: calls.append(("y", y))
    c.set_absolute_X = lambda x, **kwargs: calls.append(("x", x))
    c.set_absolute_coordinates = lambda x, y, z, **kwargs: calls.append(("xyz", x, y, z))
    c.update_location_handler = lambda **kwargs: None

    Controller.move_to_location(c, "plate")

    assert ("z", 35000) in calls
    assert calls[-1] == ("xyz", 1000, 2000, 60000)
    assert c.expected_location == "plate"


def test_move_to_location_balance_route_applies_safe_y_and_x_first():
    calls = []
    c = Controller.__new__(Controller)
    c.profile = SimpleNamespace(name="current")
    c.expected_position = {"X": 0, "Y": 0, "Z": 50000}
    c.expected_location = "pause"
    c.model = SimpleNamespace(
        location_model=SimpleNamespace(get_location_dict=lambda name: {"X": 1111, "Y": 2222, "Z": 60000})
    )
    c.set_absolute_Z = lambda z, **kwargs: calls.append(("z", z))
    c.set_absolute_Y = lambda y, **kwargs: calls.append(("y", y))
    c.set_absolute_X = lambda x, **kwargs: calls.append(("x", x))
    c.set_absolute_coordinates = lambda x, y, z, **kwargs: calls.append(("xyz", x, y, z))
    c.update_location_handler = lambda **kwargs: None

    Controller.move_to_location(c, "balance")

    assert ("z", 35000) in calls
    assert ("y", 15000) in calls
    assert ("x", 1111) in calls
    assert calls[-1] == ("xyz", 1111, 2222, 60000)
