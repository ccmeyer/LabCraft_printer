from types import SimpleNamespace

import Machine_FreeRTOS as mfr


def _machine(test_profile):
    return mfr.Machine(SimpleNamespace(), profile=test_profile)


def test_absolute_xy_accepts_negative_rack_x_minimum(qapp, test_profile):
    machine = _machine(test_profile)

    command = machine.set_absolute_XY(-500, 1200)

    assert command.command_type == "ABSOLUTE_XY"
    assert command.param1 == -500
    assert command.param2 == 1200
    assert command.param3 == 30000
    assert list(machine.command_queue.queue)[-1] is command


def test_absolute_x_accepts_negative_rack_x_minimum_as_sign_and_magnitude(qapp, test_profile):
    machine = _machine(test_profile)

    command = machine.set_absolute_X(-500)

    assert command.command_type == "ABSOLUTE_X"
    assert command.param1 == 0
    assert command.param2 == 500
    assert command.param3 == 30000
    assert list(machine.command_queue.queue)[-1] is command


def test_absolute_x_paths_reject_below_negative_rack_x_minimum(qapp, test_profile):
    machine = _machine(test_profile)
    errors = []
    machine.error_occurred.connect(errors.append)

    assert machine.set_absolute_XY(-501, 1200) is False
    assert machine.set_absolute_X(-501) is False

    assert len(machine.command_queue.queue) == 0
    assert errors == [
        "Parameter out of range: -501 not in (-500,80000)",
        "Parameter out of range: -501 not in (-500,80000)",
    ]


def test_absolute_x_paths_preserve_positive_x_maximum(qapp, test_profile):
    machine = _machine(test_profile)
    errors = []
    machine.error_occurred.connect(errors.append)

    xy_command = machine.set_absolute_XY(80000, 1200)
    x_command = machine.set_absolute_X(80000)

    assert xy_command.command_type == "ABSOLUTE_XY"
    assert xy_command.param1 == 80000
    assert x_command.command_type == "ABSOLUTE_X"
    assert x_command.param1 == 1
    assert x_command.param2 == 80000

    assert machine.set_absolute_XY(80001, 1200) is False
    assert machine.set_absolute_X(80001) is False
    assert len(machine.command_queue.queue) == 2
    assert errors == [
        "Parameter out of range: 80001 not in (-500,80000)",
        "Parameter out of range: 80001 not in (-500,80000)",
    ]
