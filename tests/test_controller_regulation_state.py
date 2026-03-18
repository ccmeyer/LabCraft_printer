from types import SimpleNamespace
from unittest.mock import Mock

from Controller import Controller


def _make_controller(regulating):
    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            regulating_print_pressure=regulating,
            toggle_regulation_state=Mock(),
        )
    )
    controller.machine = SimpleNamespace(
        regulate_print_pressure=Mock(return_value=True),
        regulate_refuel_pressure=Mock(return_value=True),
        deregulate_print_pressure=Mock(return_value=True),
        deregulate_refuel_pressure=Mock(return_value=True),
    )
    return controller


def test_toggle_regulation_queues_start_commands_without_local_toggle():
    controller = _make_controller(False)

    ok = Controller.toggle_regulation(controller)

    assert ok is True
    controller.machine.regulate_print_pressure.assert_called_once_with()
    controller.machine.regulate_refuel_pressure.assert_called_once_with()
    controller.machine.deregulate_print_pressure.assert_not_called()
    controller.machine.deregulate_refuel_pressure.assert_not_called()
    controller.model.machine_model.toggle_regulation_state.assert_not_called()


def test_toggle_regulation_queues_stop_commands_without_local_toggle():
    controller = _make_controller(True)

    ok = Controller.toggle_regulation(controller)

    assert ok is True
    controller.machine.deregulate_print_pressure.assert_called_once_with()
    controller.machine.deregulate_refuel_pressure.assert_called_once_with()
    controller.machine.regulate_print_pressure.assert_not_called()
    controller.machine.regulate_refuel_pressure.assert_not_called()
    controller.model.machine_model.toggle_regulation_state.assert_not_called()
