from types import SimpleNamespace
from unittest.mock import Mock

from Controller import Controller


def _controller_with_machine():
    controller = Controller.__new__(Controller)
    controller.machine = SimpleNamespace(
        set_regulator_recovery_profile=Mock(return_value="recovery"),
        set_regulator_slew_profile=Mock(return_value="slew"),
        set_regulator_ready_profile=Mock(return_value="ready"),
        restore_regulator_profile=Mock(return_value="restore"),
    )
    return controller


def test_controller_regulator_profile_wrappers_forward_to_machine():
    controller = _controller_with_machine()
    handler = object()
    kwargs = {"k": "v"}
    recovery = {"active_ticks": 2}
    slew = {"max_hz_delta_up_per_loop": 1200}
    ready = {"ready_tol_raw": 4}

    assert controller.set_regulator_recovery_profile(
        "print",
        recovery,
        handler=handler,
        kwargs=kwargs,
        manual=True,
    ) == "recovery"
    assert controller.set_regulator_slew_profile(
        "refuel",
        slew,
        handler=handler,
        kwargs=kwargs,
        manual=True,
    ) == "slew"
    assert controller.set_regulator_ready_profile(
        "print",
        ready,
        handler=handler,
        kwargs=kwargs,
        manual=True,
    ) == "ready"
    assert controller.restore_regulator_profile(
        ["print", "refuel"],
        source="defaults",
        handler=handler,
        kwargs=kwargs,
        manual=True,
    ) == "restore"

    controller.machine.set_regulator_recovery_profile.assert_called_once_with(
        "print",
        recovery,
        handler=handler,
        kwargs=kwargs,
        manual=True,
    )
    controller.machine.set_regulator_slew_profile.assert_called_once_with(
        "refuel",
        slew,
        handler=handler,
        kwargs=kwargs,
        manual=True,
    )
    controller.machine.set_regulator_ready_profile.assert_called_once_with(
        "print",
        ready,
        handler=handler,
        kwargs=kwargs,
        manual=True,
    )
    controller.machine.restore_regulator_profile.assert_called_once_with(
        ["print", "refuel"],
        source="defaults",
        handler=handler,
        kwargs=kwargs,
        manual=True,
    )
