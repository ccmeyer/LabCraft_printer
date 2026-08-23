from types import SimpleNamespace

from ConfigurationSafetyPolicy import ConfigurationSafetyError
from Controller import Controller


class SignalStub:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class FakeMachine:
    def __init__(self, *, fail_axis=None):
        self.fail_axis = fail_axis
        self.calls = []

    def _record(self, axis, *values, **kwargs):
        self.calls.append((axis, *values, kwargs))
        return False if self.fail_axis == axis else object()

    def set_relative_X(self, value, **kwargs):
        return self._record("relative_X", value, **kwargs)

    def set_relative_Y(self, value, **kwargs):
        return self._record("relative_Y", value, **kwargs)

    def set_relative_Z(self, value, **kwargs):
        return self._record("relative_Z", value, **kwargs)

    def set_absolute_X(self, value, **kwargs):
        return self._record("absolute_X", value, **kwargs)

    def set_absolute_Y(self, value, **kwargs):
        return self._record("absolute_Y", value, **kwargs)

    def set_absolute_Z(self, value, **kwargs):
        return self._record("absolute_Z", value, **kwargs)

    def set_absolute_XY(self, x, y, **kwargs):
        return self._record("absolute_XY", x, y, **kwargs)


def _controller(*, current=None, fail_axis=None):
    controller = Controller.__new__(Controller)
    controller.machine = FakeMachine(fail_axis=fail_axis)
    controller.model = SimpleNamespace()
    controller.expected_position = dict(
        current or {"X": 43840, "Y": 29870, "Z": 85550}
    )
    controller.configuration_safety_guard = None
    controller.error_occurred_signal = SignalStub()
    controller._pending_motion_endpoint_evidence = None
    return controller


def test_observed_plate_xy_request_queues_and_expects_canonical_endpoint():
    controller = _controller()

    accepted = Controller.set_absolute_XY(
        controller,
        33050,
        29875,
        override=True,
    )

    assert accepted is True
    assert controller.machine.calls == [
        (
            "absolute_XY",
            33050,
            29874,
            {"manual": False, "handler": None},
        )
    ]
    assert controller.expected_position == {"X": 33050, "Y": 29874, "Z": 85550}
    evidence = controller._pending_motion_endpoint_evidence
    assert evidence["requested_position"]["Y"] == 29875
    assert evidence["canonical_position"]["Y"] == 29874
    assert evidence["adjustments"] == {"X": 0, "Y": -1, "Z": 0}
    assert evidence["queue_result"] == "accepted"


def test_single_axis_absolute_and_relative_paths_use_canonical_values():
    controller = _controller(current={"X": 100, "Y": 100, "Z": 100})

    assert Controller.set_relative_X(controller, 5, override=True) is True
    assert Controller.set_relative_Y(controller, -5, override=True) is True
    assert Controller.set_absolute_Z(controller, 105, override=True) is True

    assert controller.machine.calls == [
        ("relative_X", 4, {"manual": False, "handler": None}),
        ("relative_Y", -4, {"manual": False, "handler": None}),
        ("absolute_Z", 104, {"manual": False, "handler": None}),
    ]
    assert controller.expected_position == {"X": 104, "Y": 96, "Z": 104}


def test_relative_coordinates_canonicalize_each_axis_before_queueing():
    controller = _controller(current={"X": 100, "Y": 200, "Z": 300})
    completed = []

    accepted = Controller.set_relative_coordinates(
        controller,
        5,
        -5,
        3,
        override=True,
        handler=lambda: completed.append("done"),
    )

    assert accepted is True
    assert controller.machine.calls[:2] == [
        ("relative_Y", -4, {"manual": False, "handler": None}),
        ("relative_X", 4, {"manual": False, "handler": None}),
    ]
    assert controller.machine.calls[-1][0:2] == ("relative_Z", 2)
    assert controller.machine.calls[-1][-1]["manual"] is False
    assert callable(controller.machine.calls[-1][-1]["handler"])
    assert completed == []
    assert controller.expected_position == {"X": 104, "Y": 196, "Z": 302}


def test_combined_absolute_move_uses_canonical_endpoint_and_preserves_order():
    controller = _controller(current={"X": 43840, "Y": 29870, "Z": 85550})

    accepted = Controller.set_absolute_coordinates(
        controller,
        33050,
        29875,
        85049,
        override=True,
    )

    assert accepted is True
    assert controller.machine.calls == [
        (
            "absolute_Z",
            85050,
            {"manual": False, "handler": None, "kwargs": None},
        ),
        (
            "absolute_XY",
            33050,
            29874,
            {"manual": False, "handler": None, "kwargs": None},
        ),
    ]
    assert controller.expected_position == {"X": 33050, "Y": 29874, "Z": 85050}


def test_collision_check_receives_actual_canonical_path():
    controller = _controller()
    collision_calls = []
    controller.check_collision = lambda origin, target: collision_calls.append(
        (dict(origin), dict(target))
    ) or False

    assert Controller.set_absolute_XY(controller, 33050, 29875) is True

    assert collision_calls == [
        (
            {"X": 43840, "Y": 29870, "Z": 85550},
            {"X": 33050, "Y": 29874, "Z": 85550},
        )
    ]


def test_requested_endpoint_is_validated_before_canonical_endpoint():
    controller = _controller(current={"X": 100, "Y": 59998, "Z": 100})

    class Guard:
        def __init__(self):
            self.calls = []

        def validate_endpoint(self, value):
            self.calls.append(dict(value))
            if value["Y"] > 60000:
                raise ConfigurationSafetyError("Y is outside global bounds")

    guard = Guard()
    controller.configuration_safety_guard = guard

    assert Controller.set_absolute_Y(controller, 60001, override=True) is False
    assert guard.calls == [{"X": 100, "Y": 60001, "Z": 100}]
    assert controller.machine.calls == []
    assert controller.expected_position == {"X": 100, "Y": 59998, "Z": 100}


def test_queue_rejection_does_not_advance_expected_or_replace_evidence():
    controller = _controller(fail_axis="absolute_XY")
    previous = {"queue_result": "previous"}
    controller._pending_motion_endpoint_evidence = previous

    assert Controller.set_absolute_XY(
        controller, 33050, 29875, override=True
    ) is False

    assert controller.expected_position == {"X": 43840, "Y": 29870, "Z": 85550}
    assert controller._pending_motion_endpoint_evidence is previous


def test_partial_combined_move_tracks_only_the_accepted_frontier():
    controller = _controller(
        current={"X": 0, "Y": 0, "Z": 1000},
        fail_axis="absolute_XY",
    )

    accepted = Controller.set_absolute_coordinates(
        controller,
        101,
        201,
        501,
        override=True,
    )

    assert accepted is False
    assert controller.machine.calls[0][0:2] == ("absolute_Z", 502)
    assert controller.machine.calls[1][0:3] == ("absolute_XY", 100, 200)
    assert controller.expected_position == {"X": 0, "Y": 0, "Z": 502}
    evidence = controller._pending_motion_endpoint_evidence
    assert evidence["queue_result"] == "partial"
    assert evidence["failed_axis"] == "XY"
    assert evidence["canonical_position"] == {"X": 100, "Y": 200, "Z": 502}
    assert evidence["accepted_position"] == {"X": 0, "Y": 0, "Z": 502}


def test_canonical_noop_calls_handler_without_overwriting_queued_evidence():
    controller = _controller(current={"X": 0, "Y": 0, "Z": 0})
    completed = []
    prior = {"queue_result": "prior_queued_motion"}
    controller._pending_motion_endpoint_evidence = prior

    assert Controller.set_absolute_coordinates(
        controller,
        1,
        1,
        1,
        override=True,
        handler=lambda: completed.append("done"),
    ) is True

    assert completed == ["done"]
    assert controller.machine.calls == []
    assert controller.expected_position == {"X": 0, "Y": 0, "Z": 0}
    assert controller._pending_motion_endpoint_evidence is prior


def test_noninteger_target_is_rejected_without_queue_or_expected_change():
    controller = _controller()

    assert Controller.set_absolute_Y(controller, 29875.5, override=True) is False

    assert controller.machine.calls == []
    assert controller.expected_position == {"X": 43840, "Y": 29870, "Z": 85550}
    assert controller.error_occurred_signal.calls[0][0] == "Motion Target Rejected"


def test_noninteger_relative_displacement_is_rejected_before_arithmetic():
    controller = _controller()

    assert Controller.set_relative_X(controller, True, override=True) is False

    assert controller.machine.calls == []
    assert controller.expected_position == {"X": 43840, "Y": 29870, "Z": 85550}
    assert controller.error_occurred_signal.calls[0][0] == "Motion Target Rejected"
