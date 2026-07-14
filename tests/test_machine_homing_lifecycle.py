from types import SimpleNamespace
from unittest.mock import Mock

import Machine_FreeRTOS as mfr
from Controller import Controller


def test_machine_home_request_invalidates_old_home_until_final_handler(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    machine.homed = True
    machine.location = "Home"
    completed = []
    machine.homing_completed.connect(lambda: completed.append(True))

    machine.home_motors()

    assert machine.homed is False
    assert machine.location == "Unknown"
    commands = list(machine.command_queue.queue)[-3:]
    assert [command.command_type for command in commands] == [
        "HOME_Z",
        "HOME_XY",
        "HOME_PR_BOTH",
    ]
    assert commands[0].handler is None
    assert commands[1].handler is None
    assert commands[2].handler == machine.home_motor_handler
    assert completed == []

    commands[2].handler()

    assert machine.homed is True
    assert machine.location == "Home"
    assert completed == [True]


def test_controller_invalidates_model_before_queuing_home():
    events = []
    machine_model = SimpleNamespace(
        reset_home_status=Mock(side_effect=lambda: events.append("reset")),
        home_status_signal=SimpleNamespace(emit=lambda: events.append("emit")),
    )
    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(machine_model=machine_model)
    controller.machine = SimpleNamespace(home_motors=lambda: events.append("queue"))

    Controller.home_machine(controller)

    assert events == ["reset", "emit", "queue"]


def test_canceled_home_command_does_not_run_completion_handler(qapp):
    completed = []
    queue = mfr.CommandQueue()
    command = mfr.Command(7, "HOME_PR_BOTH", 10000, 1000, 1000, handler=lambda: completed.append(True))
    command.mark_as_sent()
    queue.queue.append(command)

    queue.update_command_status(
        current_executing_command=7,
        last_completed_command=6,
        last_accepted_command=7,
        last_retired_command=7,
    )

    assert command.status == "Canceled"
    assert completed == []
