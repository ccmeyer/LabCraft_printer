from types import SimpleNamespace
from unittest.mock import Mock

import Machine_FreeRTOS as mfr
from Controller import Controller


def _machine_stub():
    machine = mfr.Machine.__new__(mfr.Machine)
    machine.add_command_to_queue = Mock(
        return_value=SimpleNamespace(command_type="queued")
    )
    return machine


def test_enable_print_profile_defaults_to_refresh_disabled():
    machine = _machine_stub()

    result = machine.enable_print_profile()

    assert result is not False
    machine.add_command_to_queue.assert_called_once_with(
        "ENABLE_PRINT_PROFILE",
        0,
        0,
        0,
        handler=None,
        kwargs=None,
        manual=False,
    )


def test_enable_print_profile_serializes_deferred_refresh_as_one():
    machine = _machine_stub()

    result = machine.enable_print_profile(deferred_gripper_refresh=True)

    assert result is not False
    machine.add_command_to_queue.assert_called_once_with(
        "ENABLE_PRINT_PROFILE",
        1,
        0,
        0,
        handler=None,
        kwargs=None,
        manual=False,
    )


def test_controller_profile_enable_defaults_calibration_to_refresh_disabled():
    controller = Controller.__new__(Controller)
    controller.machine = SimpleNamespace(enable_print_profile=Mock(return_value=True))

    assert Controller.enable_print_profile(controller) is True

    controller.machine.enable_print_profile.assert_called_once_with(
        deferred_gripper_refresh=False
    )
