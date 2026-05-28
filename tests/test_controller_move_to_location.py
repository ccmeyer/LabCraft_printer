import sys
import types

try:
    import Model  # noqa: F401
except ImportError:
    fake_model = types.ModuleType("Model")
    fake_model.Model = object
    fake_model.PrinterHead = object
    fake_model.Slot = object
    sys.modules["Model"] = fake_model

from types import SimpleNamespace

import pytest

from Controller import Controller


def _build_controller(
    current_location,
    current_z,
    target,
    *,
    profile_name="current",
    well_plate=None,
    location_lookup=None,
    current_position=None,
):
    calls = []
    c = Controller.__new__(Controller)
    c.profile = SimpleNamespace(name=profile_name)
    c.expected_position = (
        dict(current_position)
        if current_position is not None
        else {"X": 0, "Y": 0, "Z": current_z}
    )
    c.expected_location = current_location
    if location_lookup is None:
        location_lookup = lambda name: target.copy()
    c.model = SimpleNamespace(
        location_model=SimpleNamespace(get_location_dict=location_lookup),
        well_plate=well_plate,
    )
    c.error_occurred_signal = SimpleNamespace(emit=lambda *args, **kwargs: None)

    def _set_absolute_Z(z, **kwargs):
        calls.append(("z", z))
        c.expected_position["Z"] = z
        return True

    def _set_absolute_Y(y, **kwargs):
        calls.append(("y", y))
        c.expected_position["Y"] = y
        return True

    def _set_absolute_X(x, **kwargs):
        calls.append(("x", x))
        c.expected_position["X"] = x
        return True

    def _set_absolute_coordinates(x, y, z, **kwargs):
        calls.append(("xyz", x, y, z))
        c.expected_position.update({"X": x, "Y": y, "Z": z})
        return True

    c.set_absolute_Z = _set_absolute_Z
    c.set_absolute_Y = _set_absolute_Y
    c.set_absolute_X = _set_absolute_X
    c.set_absolute_coordinates = _set_absolute_coordinates
    c.update_location_handler = lambda **kwargs: None
    return c, calls


def _assert_call_order(calls, expected):
    indexes = [calls.index(call) for call in expected]
    assert indexes == sorted(indexes)


def _assert_plate_entry_dogleg(calls, target):
    _assert_call_order(
        calls,
        [
            ("xyz", target["X"] - 5000, target["Y"], 500),
            ("xyz", target["X"], target["Y"], 500),
            ("xyz", target["X"], target["Y"], target["Z"]),
        ],
    )


@pytest.mark.parametrize(
    "profile_name,current_z,target_z",
    [
        ("current", 36000, 36000),
        ("legacy", 6000, 6000),
    ],
)
def test_move_to_location_plate_entry_uses_plate_safe_z_from_camera(profile_name, current_z, target_z):
    target = {"X": 10000, "Y": 2000, "Z": target_z}
    c, calls = _build_controller("camera", current_z, target, profile_name=profile_name)

    Controller.move_to_location(c, "plate")

    assert ("z", 500) in calls
    assert calls.index(("z", 500)) < calls.index(("xyz", 5000, 2000, 500))
    _assert_plate_entry_dogleg(calls, target)


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
    target = {"X": 10000, "Y": 2000, "Z": 60000}
    c, calls = _build_controller("camera", 50000, target)

    Controller.move_to_location(c, "plate")

    assert ("z", 500) in calls
    assert calls.index(("z", 500)) < calls.index(("xyz", 5000, 2000, 500))
    _assert_plate_entry_dogleg(calls, target)
    assert c.expected_location == "plate"


def test_move_to_location_slot_transition_applies_safe_z_before_xyz():
    target = {"X": 700, "Y": 800, "Z": 60000}
    c, calls = _build_controller("home", 50000, target)

    Controller.move_to_location(c, "Slot-1")

    assert ("z", 35000) in calls
    assert calls.index(("z", 35000)) < calls.index(("xyz", 700, 800, 60000))
    assert c.expected_location == "Slot-1"


def test_move_to_location_balance_route_applies_safe_z_then_safe_y_then_x_then_xyz():
    target = {"X": 1111, "Y": 2222, "Z": 60000}
    c, calls = _build_controller("loading", 50000, target)

    Controller.move_to_location(c, "balance")

    z_idx = calls.index(("z", 35000))
    y_idx = calls.index(("y", 15000))
    x_idx = calls.index(("x", 1111))
    xyz_idx = calls.index(("xyz", 1111, 2222, 60000))
    assert z_idx < y_idx < x_idx < xyz_idx
    assert c.expected_location == "balance"


def test_move_to_location_legacy_profile_uses_legacy_safe_height_before_balance_route():
    target = {"X": 1111, "Y": 2222, "Z": 6500}
    c, calls = _build_controller("loading", 6200, target, profile_name="legacy")

    Controller.move_to_location(c, "balance")

    z_idx = calls.index(("z", 5000))
    y_idx = calls.index(("y", 15000))
    x_idx = calls.index(("x", 1111))
    xyz_idx = calls.index(("xyz", 1111, 2222, 6500))
    assert z_idx < y_idx < x_idx < xyz_idx


def test_move_to_location_ignore_safe_height_does_not_skip_plate_entry_safe_z():
    target = {"X": 10000, "Y": 2000, "Z": 60000}
    c, calls = _build_controller("camera", 50000, target)

    Controller.move_to_location(c, "plate", ignore_safe_height=True)

    assert ("z", 500) in calls
    assert calls.index(("z", 500)) < calls.index(("xyz", 5000, 2000, 500))
    _assert_plate_entry_dogleg(calls, target)
    assert calls[-1] == ("xyz", 10000, 2000, 60000)


def test_move_to_location_ignore_safe_height_still_skips_non_plate_route_safe_z():
    target = {"X": 1000, "Y": 2000, "Z": 60000}
    c, calls = _build_controller("camera", 50000, target)

    Controller.move_to_location(c, "home", ignore_safe_height=True)

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

    Controller.move_to_location(c, "home")

    assert ("z", safe_z) not in calls
    assert calls[-1] == ("xyz", 1000, 2000, target_z)


def test_move_to_location_above_safe_height_skips_safe_z_even_if_target_below_safe():
    target = {"X": 1000, "Y": 2000, "Z": 50000}
    c, calls = _build_controller("camera", 30000, target)

    Controller.move_to_location(c, "home")

    assert ("z", 35000) not in calls
    assert calls[-1] == ("xyz", 1000, 2000, 50000)


def test_move_to_location_plate_entry_moves_to_500_from_non_plate_location():
    target = {"X": 21060, "Y": 11415, "Z": 120050}
    c, calls = _build_controller("loading", 50000, target)

    Controller.move_to_location(c, "pause")

    assert ("z", 500) in calls
    assert calls.index(("z", 500)) < calls.index(("xyz", 16060, 11415, 500))
    _assert_plate_entry_dogleg(calls, target)


def test_move_to_location_plate_entry_skips_extra_z_when_already_at_500():
    target = {"X": 21060, "Y": 11415, "Z": 120050}
    c, calls = _build_controller("home", 500, target)

    Controller.move_to_location(c, "plate")

    assert ("z", 500) not in calls
    _assert_plate_entry_dogleg(calls, target)
    assert calls[-1] == ("xyz", 21060, 11415, 120050)


def test_move_to_location_pause_to_plate_does_not_lift_to_plate_entry_safe_z():
    target = {"X": 1000, "Y": 2000, "Z": 120050}
    c, calls = _build_controller("pause", 120050, target)

    Controller.move_to_location(c, "plate")

    assert ("z", 500) not in calls
    assert calls[-1] == ("xyz", 1000, 2000, 120050)


def test_move_to_location_plate_to_pause_does_not_lift_to_plate_entry_safe_z():
    target = {"X": 1000, "Y": 2000, "Z": 120050}
    c, calls = _build_controller("plate", 120050, target)

    Controller.move_to_location(c, "pause")

    assert ("z", 500) not in calls
    assert calls[-1] == ("xyz", 1000, 2000, 120050)


def test_move_to_location_pause_to_camera_doglegs_out_through_current_x_offset():
    target = {"X": 11563, "Y": 39550, "Z": 99388}
    c, calls = _build_controller(
        "pause",
        120050,
        target,
        current_position={"X": 21060, "Y": 11415, "Z": 120050},
    )

    Controller.move_to_location(c, "camera")

    assert ("z", 500) in calls
    assert ("z", 35000) not in calls
    _assert_call_order(
        calls,
        [
            ("z", 500),
            ("xyz", 16060, 11415, 500),
            ("xyz", 11563, 39550, 99388),
        ],
    )


def test_move_to_location_plate_to_camera_doglegs_out_through_current_x_offset():
    target = {"X": 11563, "Y": 39550, "Z": 99388}
    c, calls = _build_controller(
        "plate",
        120050,
        target,
        current_position={"X": 21060, "Y": 11915, "Z": 120050},
    )

    Controller.move_to_location(c, "camera")

    assert ("z", 500) in calls
    assert ("z", 35000) not in calls
    _assert_call_order(
        calls,
        [
            ("z", 500),
            ("xyz", 16060, 11915, 500),
            ("xyz", 11563, 39550, 99388),
        ],
    )


def test_move_to_location_balance_to_plate_uses_approach_x_before_dogleg():
    target = {"X": 21060, "Y": 11915, "Z": 120050}
    c, calls = _build_controller("balance", 74100, target)

    Controller.move_to_location(c, "plate")

    z_idx = calls.index(("z", 500))
    y_idx = calls.index(("y", 15000))
    x_idx = calls.index(("x", 16060))
    approach_idx = calls.index(("xyz", 16060, 11915, 500))
    seated_idx = calls.index(("xyz", 21060, 11915, 500))
    xyz_idx = calls.index(("xyz", 21060, 11915, 120050))
    assert ("z", 35000) not in calls
    assert z_idx < y_idx < x_idx < approach_idx < seated_idx < xyz_idx


def test_move_to_location_balance_to_plate_ignore_safe_height_still_starts_at_plate_safe_z():
    target = {"X": 21060, "Y": 11915, "Z": 120050}
    c, calls = _build_controller("balance", 74100, target)

    Controller.move_to_location(c, "plate", ignore_safe_height=True)

    assert ("z", 500) in calls
    assert ("z", 35000) not in calls
    assert calls.index(("z", 500)) < calls.index(("y", 15000))
    assert calls.index(("y", 15000)) < calls.index(("x", 16060))
    _assert_plate_entry_dogleg(calls, target)


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
    target = {"X": 21060, "Y": 11415, "Z": 120050}
    c, calls = _build_controller("slot-1", 50000, target)

    Controller.move_to_location(c, "pause")

    assert ("z", 500) in calls
    _assert_plate_entry_dogleg(calls, target)


def test_move_to_location_balance_departure_respects_ignore_safe_height_but_not_plate_dogleg():
    target = {"X": 1111, "Y": 2222, "Z": 60000}
    c, calls = _build_controller(
        "pause",
        120050,
        target,
        current_position={"X": 21060, "Y": 11415, "Z": 120050},
    )

    Controller.move_to_location(c, "balance", ignore_safe_height=True)

    assert ("z", 500) in calls
    assert ("z", 35000) not in calls
    assert ("xyz", 16060, 11415, 500) in calls
    assert ("y", 15000) in calls
    assert ("x", 1111) in calls


def test_move_to_location_on_complete_runs_after_location_update():
    events = []
    target = {"X": 1000, "Y": 2000, "Z": 60000}
    c = Controller.__new__(Controller)
    c.profile = SimpleNamespace(name="current")
    c.expected_position = {"X": 0, "Y": 0, "Z": 50000}
    c.expected_location = "pause"
    c.error_occurred_signal = SimpleNamespace(emit=lambda *args, **kwargs: None)
    c.model = SimpleNamespace(
        location_model=SimpleNamespace(
            get_location_dict=lambda name: target.copy(),
            update_current_location=lambda name: events.append(("location", name)),
        )
    )
    c.set_absolute_Z = lambda z, **kwargs: events.append(("z", z))
    c.set_absolute_Y = lambda y, **kwargs: events.append(("y", y))
    c.set_absolute_X = lambda x, **kwargs: events.append(("x", x))

    def _set_absolute_coordinates(x, y, z, **kwargs):
        events.append(("xyz", x, y, z))
        kwargs["handler"]()
        return True

    c.set_absolute_coordinates = _set_absolute_coordinates

    Controller.move_to_location(c, "plate", on_complete=lambda: events.append("complete"))

    assert ("location", "plate") in events
    assert events.index(("location", "plate")) < events.index("complete")


def test_move_to_location_plate_prefers_active_plate_reference_coords():
    location_lookups = []
    plate_target = {"X": 700, "Y": 800, "Z": 900}
    fallback_target = {"X": 1000, "Y": 2000, "Z": 3000}
    c, calls = _build_controller(
        "pause",
        50000,
        fallback_target,
        well_plate=SimpleNamespace(get_plate_reference_coords=lambda: plate_target.copy()),
        location_lookup=lambda name: location_lookups.append(name) or fallback_target.copy(),
    )

    Controller.move_to_location(c, "plate")

    assert location_lookups == []
    assert calls[-1] == ("xyz", 700, 800, 900)
    assert c.expected_location == "plate"


def test_move_to_location_plate_falls_back_to_legacy_location_when_plate_reference_missing():
    location_lookups = []
    fallback_target = {"X": 10000, "Y": 2000, "Z": 60000}
    c, calls = _build_controller(
        "camera",
        50000,
        fallback_target,
        well_plate=SimpleNamespace(get_plate_reference_coords=lambda: None),
        location_lookup=lambda name: location_lookups.append(name) or fallback_target.copy(),
    )

    Controller.move_to_location(c, "plate")

    assert location_lookups == ["plate"]
    assert ("z", 500) in calls
    _assert_plate_entry_dogleg(calls, fallback_target)
    assert calls[-1] == ("xyz", 10000, 2000, 60000)


def test_move_to_location_non_plate_names_ignore_well_plate_reference():
    location_lookups = []
    loading_target = {"X": 111, "Y": 222, "Z": 333}
    c, calls = _build_controller(
        "home",
        50000,
        loading_target,
        well_plate=SimpleNamespace(get_plate_reference_coords=lambda: {"X": 9, "Y": 9, "Z": 9}),
        location_lookup=lambda name: location_lookups.append(name) or loading_target.copy(),
    )

    Controller.move_to_location(c, "loading")

    assert location_lookups == ["loading"]
    assert calls[-1] == ("xyz", 111, 222, 333)
