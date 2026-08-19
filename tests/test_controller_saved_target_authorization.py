from types import SimpleNamespace

from Controller import Controller
from MachineDataVerification import SavedTargetAuthorizationDecision


MACHINE_UUID = "00000000-0000-0000-0000-000000000123"


class RecordingAuthorizer:
    def __init__(self, *, allowed):
        self.allowed = bool(allowed)
        self.requests = []

    def authorize(self, request):
        self.requests.append(request)
        return SavedTargetAuthorizationDecision(
            allowed=self.allowed,
            reason_code="authorized" if self.allowed else "target_unverified",
            message=(
                "Saved target matches verification."
                if self.allowed
                else "Saved target is not verified."
            ),
            target_key=request.target_key,
        )


def _move_controller(target, *, allowed, name="camera", rack=None, plate=None):
    commands = []
    errors = []
    authorizer = RecordingAuthorizer(allowed=allowed)
    controller = Controller.__new__(Controller)
    controller.profile = SimpleNamespace(name="current")
    controller.expected_position = {"X": 0, "Y": 0, "Z": 50000}
    controller.expected_location = "home"
    controller.saved_target_authorizer = authorizer
    controller.machine_data_paths = SimpleNamespace(machine_uuid=MACHINE_UUID)
    controller.model = SimpleNamespace(
        location_model=SimpleNamespace(
            get_location_dict=lambda _name: dict(target),
        ),
        rack_model=rack or SimpleNamespace(calibrations={}),
        well_plate=plate,
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda *args: errors.append(args)
    )
    controller.set_absolute_Z = lambda value, **_kwargs: commands.append(
        ("z", value)
    ) or True
    controller.set_absolute_Y = lambda value, **_kwargs: commands.append(
        ("y", value)
    ) or True
    controller.set_absolute_X = lambda value, **_kwargs: commands.append(
        ("x", value)
    ) or True
    controller.set_absolute_coordinates = (
        lambda x, y, z, **_kwargs: commands.append(("xyz", x, y, z)) or True
    )
    controller.update_location_handler = lambda **_kwargs: None
    return controller, commands, errors, authorizer, name


def test_unverified_camera_is_denied_before_safe_route_or_final_command():
    controller, commands, errors, authorizer, name = _move_controller(
        {"X": 11000, "Y": 22000, "Z": 33000},
        allowed=False,
    )

    result = Controller.move_to_location(controller, name)

    assert result is False
    assert commands == []
    assert errors == [("Move Blocked", "Saved target is not verified.")]
    assert authorizer.requests[0].target_key == "location:camera"


def test_manual_override_and_ignore_safe_height_do_not_bypass_authorization():
    controller, commands, _errors, authorizer, name = _move_controller(
        {"X": 11000, "Y": 22000, "Z": 33000},
        allowed=False,
    )

    result = Controller.move_to_location(
        controller,
        name,
        manual=True,
        override=True,
        ignore_safe_height=True,
    )

    assert result is False
    assert commands == []
    request = authorizer.requests[0]
    assert request.manual is True
    assert request.override is True
    assert request.ignore_safe_height is True


def test_authorized_camera_preserves_existing_route_behavior():
    controller, commands, errors, authorizer, name = _move_controller(
        {"X": 11000, "Y": 22000, "Z": 33000},
        allowed=True,
    )

    result = Controller.move_to_location(controller, name)

    assert result is True
    assert commands == [("xyz", 11000, 22000, 33000)]
    assert errors == []
    assert len(authorizer.requests) == 1


def test_rack_slot_uses_pair_authorization_and_denial_queues_nothing():
    calibrations = {
        "rack_position_Left": {"X": 100, "Y": 200, "Z": 300},
        "rack_position_Right": {"X": 400, "Y": 500, "Z": 600},
    }
    rack = SimpleNamespace(calibrations=calibrations)
    controller, commands, _errors, authorizer, _name = _move_controller(
        {"X": 250, "Y": 350, "Z": 450},
        allowed=False,
        name="Slot-2",
        rack=rack,
    )

    result = Controller.move_to_location(
        controller,
        "Slot-2",
        coords={"X": 250, "Y": 350, "Z": 450},
        override=True,
    )

    assert result is False
    assert commands == []
    request = authorizer.requests[0]
    assert request.target_key == "rack:primary"
    assert request.target_kind == "rack"
    assert request.base_value == {
        "Left": calibrations["rack_position_Left"],
        "Right": calibrations["rack_position_Right"],
    }


def test_plate_location_uses_four_corner_authorization():
    calibrations = {
        "top_left": {"X": 1, "Y": 2, "Z": 3},
        "top_right": {"X": 4, "Y": 5, "Z": 6},
        "bottom_right": {"X": 7, "Y": 8, "Z": 9},
        "bottom_left": {"X": 10, "Y": 11, "Z": 12},
    }
    plate = SimpleNamespace(
        get_current_plate_name=lambda: "Plate96",
        get_all_current_plate_calibrations=lambda: calibrations,
        get_plate_reference_coords=lambda: {"X": 1, "Y": 2, "Z": 3},
    )
    controller, commands, _errors, authorizer, _name = _move_controller(
        {"X": 1, "Y": 2, "Z": 3},
        allowed=False,
        name="plate",
        plate=plate,
    )

    assert Controller.move_to_location(controller, "plate") is False
    assert commands == []
    request = authorizer.requests[0]
    assert request.target_key == "plate:plate96"
    assert request.target_kind == "plate"
    assert request.base_value == calibrations


def test_plate_array_denial_precedes_overshoot_and_well_commands():
    commands = []
    finalized = []
    errors = []
    authorizer = RecordingAuthorizer(allowed=False)
    calibrations = {
        "top_left": {"X": 1, "Y": 2, "Z": 3},
        "top_right": {"X": 4, "Y": 5, "Z": 6},
        "bottom_right": {"X": 7, "Y": 8, "Z": 9},
        "bottom_left": {"X": 10, "Y": 11, "Z": 12},
    }
    well = SimpleNamespace(
        well_id="A1",
        get_remaining_droplets=lambda _stock_id: 5,
        get_coordinates=lambda: {"X": 100, "Y": 200, "Z": 300},
    )
    controller = Controller.__new__(Controller)
    controller._array_context = {"stock_id": "stock-1"}
    controller._get_next_unplanned_array_well = lambda _context: well
    controller._complete_array_finalize = lambda reason: finalized.append(reason)
    controller.saved_target_authorizer = authorizer
    controller.machine_data_paths = SimpleNamespace(machine_uuid=MACHINE_UUID)
    controller.model = SimpleNamespace(
        well_plate=SimpleNamespace(
            get_current_plate_name=lambda: "Plate96",
            get_all_current_plate_calibrations=lambda: calibrations,
        )
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda *args: errors.append(args)
    )
    controller.set_absolute_coordinates = (
        lambda *args, **kwargs: commands.append((args, kwargs)) or True
    )

    assert Controller._queue_next_array_well(controller) is False
    assert commands == []
    assert finalized == ["hard_abort"]
    assert errors == [("Move Blocked", "Saved target is not verified.")]
    assert authorizer.requests[0].target_key == "plate:plate96"
