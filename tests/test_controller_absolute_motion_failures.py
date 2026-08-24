from types import SimpleNamespace

import pytest

from Controller import Controller


class FakeMachine:
    def __init__(self, fail_axis=None):
        self.fail_axis = fail_axis
        self.calls = []

    def set_absolute_XY(self, x, y, **kwargs):
        self.calls.append(("xy", x, y, kwargs))
        return False if self.fail_axis == "xy" else object()

    def set_absolute_X(self, x, **kwargs):
        self.calls.append(("x", x, kwargs))
        return False if self.fail_axis == "x" else object()

    def set_absolute_Y(self, y, **kwargs):
        self.calls.append(("y", y, kwargs))
        return False if self.fail_axis == "y" else object()

    def set_absolute_Z(self, z, **kwargs):
        self.calls.append(("z", z, kwargs))
        return False if self.fail_axis == "z" else object()


def _controller(fail_axis=None, current=None):
    controller = Controller.__new__(Controller)
    controller.machine = FakeMachine(fail_axis=fail_axis)
    controller.expected_position = dict(current or {"X": 10, "Y": 20, "Z": 30})
    controller.model = SimpleNamespace()
    return controller


@pytest.mark.parametrize(
    ("method_name", "fail_axis", "args"),
    [
        ("set_absolute_XY", "xy", (-500, 1200)),
        ("set_absolute_X", "x", (-500,)),
        ("set_absolute_Y", "y", (1200,)),
        ("set_absolute_Z", "z", (500,)),
    ],
)
def test_absolute_helpers_leave_expected_position_unchanged_on_queue_failure(
    method_name,
    fail_axis,
    args,
):
    controller = _controller(fail_axis=fail_axis)
    before = dict(controller.expected_position)
    completed = []

    ok = getattr(Controller, method_name)(
        controller,
        *args,
        override=True,
        handler=lambda: completed.append("done"),
    )

    assert ok is False
    assert controller.expected_position == before
    assert completed == []


def test_absolute_coordinates_accepts_negative_rack_x_when_machine_queues_move():
    controller = _controller(current={"X": 0, "Y": 1200, "Z": 500})

    ok = Controller.set_absolute_coordinates(
        controller,
        -500,
        1200,
        500,
        override=True,
    )

    assert ok is True
    assert controller.machine.calls == [
        ("xy", -500, 1200, {"manual": False, "handler": None, "kwargs": None}),
    ]
    assert controller.expected_position == {"X": -500, "Y": 1200, "Z": 500}


def test_absolute_coordinates_rejection_leaves_expected_position_and_skips_handler():
    controller = _controller(fail_axis="xy", current={"X": 0, "Y": 1200, "Z": 500})
    completed = []
    handler = lambda: completed.append("done")

    ok = Controller.set_absolute_coordinates(
        controller,
        -501,
        1200,
        500,
        override=True,
        handler=handler,
    )

    assert ok is False
    assert controller.machine.calls == [
        (
            "xy",
            -500,
            1200,
            {"manual": False, "handler": handler, "kwargs": None},
        ),
    ]
    assert controller.expected_position == {"X": 0, "Y": 1200, "Z": 500}
    assert completed == []


def test_absolute_coordinates_preserves_successful_intermediate_z_on_later_failure():
    controller = _controller(
        fail_axis="xy",
        current={"X": 0, "Y": 0, "Z": 1000},
    )
    completed = []

    ok = Controller.set_absolute_coordinates(
        controller,
        100,
        200,
        500,
        override=True,
        handler=lambda: completed.append("done"),
    )

    assert ok is False
    assert controller.machine.calls[0][:2] == ("z", 500)
    assert controller.machine.calls[1][:3] == ("xy", 100, 200)
    assert controller.expected_position == {"X": 0, "Y": 0, "Z": 500}
    assert completed == []
