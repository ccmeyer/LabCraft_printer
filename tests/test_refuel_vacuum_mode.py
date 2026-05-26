from types import SimpleNamespace
from unittest.mock import Mock

import Machine_FreeRTOS as mfr
from Controller import Controller


def _machine_stub():
    machine = mfr.Machine.__new__(mfr.Machine)
    machine.fss = 13107
    machine.psi_offset = 1638
    machine.psi_max = 15
    machine.check_param_limits = Mock(side_effect=lambda value, lo, hi: lo <= value <= hi)
    machine.add_command_to_queue = Mock(return_value=SimpleNamespace(command_type="queued"))
    return machine


def test_machine_refuel_vacuum_enter_uses_bounded_negative_raw_target():
    machine = _machine_stub()

    result = mfr.Machine.enter_refuel_vacuum_mode(machine)

    assert result is not False
    machine.add_command_to_queue.assert_called_once_with(
        "REFUEL_VACUUM_ENTER",
        764,
        20000,
        5000,
        handler=None,
        kwargs=None,
        manual=False,
    )


def test_machine_absolute_refuel_pressure_rejects_negative_pressure():
    machine = _machine_stub()

    result = mfr.Machine.set_absolute_refuel_pressure(machine, -0.1)

    assert result is None
    machine.add_command_to_queue.assert_not_called()


def test_machine_refuel_vacuum_set_target_rejects_positive_pressure():
    machine = _machine_stub()

    result = mfr.Machine.set_refuel_vacuum_pressure(machine, 0.1)

    assert result is False
    machine.add_command_to_queue.assert_not_called()


def test_machine_refuel_vacuum_exit_clamps_restore_to_nonnegative_pressure():
    machine = _machine_stub()

    result = mfr.Machine.exit_refuel_vacuum_mode(machine, -0.5)

    assert result is not False
    machine.add_command_to_queue.assert_called_once_with(
        "REFUEL_VACUUM_EXIT",
        1638,
        0,
        0,
        handler=None,
        kwargs=None,
        manual=False,
    )


def _controller_stub():
    controller = Controller.__new__(Controller)
    controller.error_occurred_signal = SimpleNamespace(emit=Mock())
    controller.machine = SimpleNamespace(
        enter_refuel_vacuum_mode=Mock(return_value=object()),
        set_refuel_vacuum_pressure=Mock(return_value=object()),
        exit_refuel_vacuum_mode=Mock(return_value=object()),
    )
    return controller


def test_controller_refuel_vacuum_wrappers_forward_valid_requests():
    controller = _controller_stub()

    assert Controller.enter_refuel_vacuum_mode(controller, handler="done", manual=True) is not False
    controller.machine.enter_refuel_vacuum_mode.assert_called_once_with(
        target_psi=-1.0,
        prep_position_steps=20000,
        move_hz=5000,
        handler="done",
        manual=True,
    )

    assert Controller.set_refuel_vacuum_pressure(controller, -0.25, manual=True) is not False
    controller.machine.set_refuel_vacuum_pressure.assert_called_once_with(
        -0.25,
        handler=None,
        manual=True,
    )

    assert Controller.exit_refuel_vacuum_mode(controller, -0.5, manual=True) is not False
    controller.machine.exit_refuel_vacuum_mode.assert_called_once_with(
        0.0,
        handler=None,
        manual=True,
    )


def test_controller_refuel_vacuum_rejects_out_of_range_pressure():
    controller = _controller_stub()

    result = Controller.set_refuel_vacuum_pressure(controller, -1.2, manual=True)

    assert result is False
    controller.error_occurred_signal.emit.assert_called_once()
    controller.machine.set_refuel_vacuum_pressure.assert_not_called()
