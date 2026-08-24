import copy
from types import SimpleNamespace

import pytest

from Controller import CALIBRATION_TRAVEL_SAFE_Z, Controller


MACHINE_UUID = "00000000-0000-0000-0000-000000000005"
LEFT = {"X": 104, "Y": 2000, "Z": 65500}
RIGHT = {"X": 204, "Y": 41350, "Z": 66600}
SLOT_5 = {"X": 3186, "Y": 34792, "Z": 66416}


class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _Rack:
    def __init__(self):
        self.temp_calibration_data = {}

    def get_all_current_rack_calibrations(self):
        return {
            "rack_position_Left": copy.deepcopy(LEFT),
            "rack_position_Right": copy.deepcopy(RIGHT),
        }

    def set_calibration_position(self, name, position):
        self.temp_calibration_data[name] = copy.deepcopy(position)

    def discard_temp_calibrations(self):
        self.temp_calibration_data.clear()


def _entry_preflight(*, verified):
    return {
        "allowed": True,
        "machine_uuid": MACHINE_UUID,
        "trust_epoch": 7,
        "target_key": "rack:primary",
        "target_state": (
            "verified_by_controlled_calibration"
            if verified
            else "revoked_pending_verification"
        ),
        "verified": bool(verified),
        "initial_calibrations": {
            "rack_position_Left": copy.deepcopy(LEFT),
            "rack_position_Right": copy.deepcopy(RIGHT),
        },
        "initial_value_sha256": "a" * 64,
    }


def _route_controller(*, verified, reject_call=None):
    controller = Controller.__new__(Controller)
    controller._rack_calibration_session = None
    controller._plate_calibration_session = None
    controller._configuration_capture_evidence = {}
    controller.expected_position = copy.deepcopy(SLOT_5)
    controller.expected_location = "Slot-5"
    controller.error_occurred_signal = _Signal()
    rack = _Rack()
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            is_busy=lambda: False,
            get_current_position_dict_capital=lambda: copy.deepcopy(
                controller.expected_position
            ),
        ),
        rack_model=rack,
    )
    controller.rack_calibration_entry_preflight = lambda: _entry_preflight(
        verified=verified
    )
    controller._emit_optional = lambda *_args, **_kwargs: None
    calls = []

    def record(kind, coordinates, kwargs):
        calls.append((kind, *coordinates, dict(kwargs)))
        if reject_call is not None and len(calls) == reject_call:
            return False
        if kind == "Z":
            controller.expected_position["Z"] = int(coordinates[0])
        elif kind == "XY":
            controller.expected_position.update(
                {"X": int(coordinates[0]), "Y": int(coordinates[1])}
            )
        return True

    controller.set_absolute_Z = lambda z, **kwargs: record("Z", (z,), kwargs)
    controller.set_absolute_XY = lambda x, y, **kwargs: record(
        "XY", (x, y), kwargs
    )
    return controller, calls


def _command_values(calls):
    return [(call[0], *call[1:-1]) for call in calls]


def test_verified_slot_five_entry_raises_before_any_rack_directed_xy():
    controller, calls = _route_controller(verified=True)

    result = controller.begin_rack_calibration_entry(manual_first=False)

    assert result["state"] == "staging"
    assert _command_values(calls) == [
        ("Z", CALIBRATION_TRAVEL_SAFE_Z),
        ("XY", LEFT["X"] + 2500, LEFT["Y"]),
        ("Z", LEFT["Z"]),
        ("XY", LEFT["X"], LEFT["Y"]),
    ]
    assert calls[0][-1]["override"] is False
    assert calls[1][-1]["override"] is False
    assert calls[2][-1]["override"] is True
    assert calls[3][-1]["handler"] is not None


def test_unverified_entry_stops_at_safe_z_and_left_clearance():
    controller, calls = _route_controller(verified=False)

    result = controller.begin_rack_calibration_entry(manual_first=True)

    assert result["state"] == "staging"
    assert result["manual_first"] is True
    assert result["expected_endpoint"] == {
        "X": LEFT["X"] + 2500,
        "Y": LEFT["Y"],
        "Z": CALIBRATION_TRAVEL_SAFE_Z,
    }
    assert _command_values(calls) == [
        ("Z", CALIBRATION_TRAVEL_SAFE_Z),
        ("XY", LEFT["X"] + 2500, LEFT["Y"]),
    ]
    assert calls[-1][-1]["handler"] is not None


@pytest.mark.parametrize(
    ("reject_call", "expected_reason"),
    [
        (1, "safe_z_rejected"),
        (2, "rack_clearance_xy_rejected"),
        (3, "rack_clearance_descent_rejected"),
        (4, "rack_entry_endpoint_rejected"),
    ],
)
def test_rejected_rack_entry_step_suppresses_every_dependent_command(
    reject_call, expected_reason
):
    controller, calls = _route_controller(
        verified=True, reject_call=reject_call
    )

    result = controller.begin_rack_calibration_entry(manual_first=False)

    assert result is False
    expected_commands = [
        ("Z", CALIBRATION_TRAVEL_SAFE_Z),
        ("XY", LEFT["X"] + 2500, LEFT["Y"]),
        ("Z", LEFT["Z"]),
        ("XY", LEFT["X"], LEFT["Y"]),
    ]
    assert _command_values(calls) == expected_commands[:reject_call]
    assert controller._rack_calibration_session["state"] == "failed"
    assert controller._rack_calibration_session["failure_reason"] == expected_reason


def test_first_capture_retracts_lifts_and_approaches_predicted_right_anchor():
    controller, calls = _route_controller(verified=False)
    captured_left = {"X": 204, "Y": 2100, "Z": 65600}
    controller._rack_calibration_session = {
        **_entry_preflight(verified=False),
        "session_token": "rack-session",
        "state": "manual_first_point",
        "phase": "entry",
        "manual_first": True,
        "captured_points": {},
        "next_point_index": 0,
        "expected_point": "rack_position_Left",
    }
    controller._rack_calibration_session_invariants = lambda _session: (True, "")
    controller.check_if_all_completed = lambda: True
    controller.capture_configuration_point = lambda *_args, **_kwargs: copy.deepcopy(
        captured_left
    )
    controller.expected_position = copy.deepcopy(captured_left)

    result = controller.capture_and_advance_rack_calibration(
        "rack-session", "rack_position_Left"
    )

    predicted_right = {"X": 304, "Y": 41450, "Z": 66700}
    assert result is True
    assert controller.model.rack_model.temp_calibration_data[
        "rack_position_Left"
    ] == captured_left
    assert _command_values(calls) == [
        ("XY", captured_left["X"] + 2500, captured_left["Y"]),
        ("Z", CALIBRATION_TRAVEL_SAFE_Z),
        ("XY", predicted_right["X"] + 2500, predicted_right["Y"]),
        ("Z", predicted_right["Z"]),
        ("XY", predicted_right["X"], predicted_right["Y"]),
    ]
    assert controller._rack_calibration_session["expected_point"] == (
        "rack_position_Right"
    )
    assert controller._rack_calibration_session["expected_endpoint"] == (
        predicted_right
    )


def test_final_capture_retracts_in_x_then_raises_to_safe_z():
    controller, calls = _route_controller(verified=True)
    captured_right = {"X": 304, "Y": 41450, "Z": 66700}
    controller._rack_calibration_session = {
        **_entry_preflight(verified=True),
        "session_token": "rack-session",
        "state": "automatic_points",
        "phase": "point",
        "manual_first": False,
        "captured_points": {"rack_position_Left": copy.deepcopy(LEFT)},
        "next_point_index": 1,
        "expected_point": "rack_position_Right",
    }
    controller._rack_calibration_session_invariants = lambda _session: (True, "")
    controller.check_if_all_completed = lambda: True
    controller.capture_configuration_point = lambda *_args, **_kwargs: copy.deepcopy(
        captured_right
    )
    controller.expected_position = copy.deepcopy(captured_right)

    result = controller.capture_and_advance_rack_calibration(
        "rack-session", "rack_position_Right"
    )

    assert result is True
    assert _command_values(calls) == [
        ("XY", captured_right["X"] + 2500, captured_right["Y"]),
        ("Z", CALIBRATION_TRAVEL_SAFE_Z),
    ]
    assert calls[-1][-1]["handler"] is not None
    assert controller._rack_calibration_session["phase"] == "final_lift"
    assert controller._rack_calibration_session["expected_endpoint"] == {
        "X": captured_right["X"] + 2500,
        "Y": captured_right["Y"],
        "Z": CALIBRATION_TRAVEL_SAFE_Z,
    }


def test_interruption_discards_partial_rack_capture_and_invalidates_callback():
    controller, calls = _route_controller(verified=False)
    controller.begin_rack_calibration_entry(manual_first=True)
    token = controller._rack_calibration_session["session_token"]
    stale_callback = calls[-1][-1]["handler"]
    controller.model.rack_model.temp_calibration_data["rack_position_Left"] = {
        "X": 1,
        "Y": 2,
        "Z": 3,
    }

    controller._on_rack_calibration_workflow_interrupted(
        {"reason": "queue_cleared"}
    )

    assert controller._rack_calibration_session["state"] == "failed"
    assert controller.model.rack_model.temp_calibration_data == {}
    assert stale_callback() is False
    assert controller._rack_calibration_session["session_token"] == token
    assert controller._rack_calibration_session["state"] == "failed"


def test_back_uses_the_same_retract_lift_traverse_and_approach_route():
    controller, calls = _route_controller(verified=True)
    captured_left = {"X": 154, "Y": 2050, "Z": 65550}
    captured_right = {"X": 254, "Y": 41400, "Z": 66650}
    controller._rack_calibration_session = {
        **_entry_preflight(verified=True),
        "session_token": "rack-session",
        "state": "automatic_points",
        "phase": "point",
        "manual_first": False,
        "captured_points": {
            "rack_position_Left": copy.deepcopy(captured_left),
            "rack_position_Right": copy.deepcopy(captured_right),
        },
        "next_point_index": 1,
        "expected_point": "rack_position_Right",
    }
    controller.model.rack_model.temp_calibration_data = {
        "rack_position_Left": copy.deepcopy(captured_left),
        "rack_position_Right": copy.deepcopy(captured_right),
    }
    controller._configuration_capture_evidence = {
        ("rack_calibration", "rack_position_Left"): {"ready": True},
        ("rack_calibration", "rack_position_Right"): {"ready": True},
    }
    controller._rack_calibration_session_invariants = lambda _session: (True, "")
    controller.check_if_all_completed = lambda: True
    controller.expected_position = copy.deepcopy(captured_right)

    result = controller.move_rack_calibration_to_point(
        "rack-session", "rack_position_Left"
    )

    assert result is True
    assert _command_values(calls) == [
        ("XY", captured_right["X"] + 2500, captured_right["Y"]),
        ("Z", CALIBRATION_TRAVEL_SAFE_Z),
        ("XY", captured_left["X"] + 2500, captured_left["Y"]),
        ("Z", captured_left["Z"]),
        ("XY", captured_left["X"], captured_left["Y"]),
    ]
    assert controller.model.rack_model.temp_calibration_data == {}
    assert controller._configuration_capture_evidence == {}
    assert controller._rack_calibration_session["expected_point"] == (
        "rack_position_Left"
    )


@pytest.mark.parametrize(
    ("reconciliation_state", "expected_reason"),
    [
        ("timed_out", "position_reconciliation_timeout"),
        ("trust_changed", "position_reconciliation_trust_changed"),
        ("mismatch", "expected_position_mismatch"),
    ],
)
def test_rack_reconciliation_failures_never_enable_capture(
    reconciliation_state, expected_reason
):
    controller, _calls = _route_controller(verified=True)
    controller._rack_calibration_session = {
        **_entry_preflight(verified=True),
        "session_token": "rack-session",
        "state": "reconciling",
        "phase": "entry",
        "manual_first": False,
        "awaiting_queue_drain": False,
        "expected_endpoint": copy.deepcopy(LEFT),
    }
    controller._rack_calibration_session_invariants = lambda _session: (True, "")
    controller._advance_position_reconciliation = lambda **_kwargs: {
        "state": reconciliation_state,
        "expected_position": copy.deepcopy(LEFT),
    }

    result = controller._advance_rack_calibration_session()

    assert result["state"] == "failed"
    assert result["failure_reason"] == expected_reason


def test_duplicate_rack_entry_is_rejected_before_machine_access():
    controller = Controller.__new__(Controller)
    controller._rack_calibration_session = {
        "session_token": "rack-session",
        "state": "staging",
    }

    result = controller.rack_calibration_entry_preflight()

    assert result["allowed"] is False
    assert result["reason_code"] == "rack_calibration_already_active"


def test_missing_rack_calibration_head_precedes_position_reconciliation():
    controller = Controller.__new__(Controller)
    controller._rack_calibration_session = None
    controller._plate_calibration_session = None
    controller.expected_location = "Home"
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            is_connected=lambda: True,
            motors_are_enabled=lambda: True,
            motors_are_homed=lambda: True,
            paused=False,
            transport_paused=False,
            is_busy=lambda: False,
        ),
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: None),
    )
    controller.check_if_all_completed = lambda: True
    readiness_calls = []
    controller._configuration_capture_readiness = lambda: readiness_calls.append(
        True
    ) or {
        "ready": False,
        "reason_codes": ["expected_position_mismatch"],
    }

    result = controller.rack_calibration_entry_preflight()

    assert result["allowed"] is False
    assert result["reason_code"] == "calibration_head_required"
    assert readiness_calls == []


def test_unrelated_motion_is_blocked_while_rack_session_owns_motion():
    controller = Controller.__new__(Controller)
    controller._plate_calibration_session = None
    controller._rack_calibration_session = {
        "session_token": "rack-session",
        "state": "manual_first_point",
    }
    controller.error_occurred_signal = _Signal()

    result = Controller.set_absolute_Z(controller, 1234)

    assert result is False
    assert controller.error_occurred_signal.calls == [
        (
            "Rack Calibration Active",
            "Other motion is blocked while the guarded rack-calibration session is active.",
        )
    ]
