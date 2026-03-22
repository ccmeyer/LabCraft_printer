from types import SimpleNamespace
from unittest.mock import Mock

from Controller import Controller


def _make_refuel_controller(*, queue_empty=True, regulating_print_pressure=True):
    controller = Controller.__new__(Controller)
    controller.machine = SimpleNamespace(
        check_if_all_completed=lambda: queue_empty,
        print_droplets=Mock(return_value=True),
        wait_ms=Mock(return_value=True),
    )
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(regulating_print_pressure=regulating_print_pressure)
    )
    controller._build_refuel_capture_context = Mock(
        return_value={"timestamp_utc": "2026-03-21T10:00:00Z", "monotonic_s": 10.0}
    )
    return controller


def test_run_refuel_balance_burst_rejects_nonempty_queue():
    controller = _make_refuel_controller(queue_empty=False)
    on_error = Mock()

    ok = Controller.run_refuel_balance_burst(controller, 20, 1000, on_error=on_error)

    assert ok is False
    controller.machine.print_droplets.assert_not_called()
    controller.machine.wait_ms.assert_not_called()
    on_error.assert_called_once()


def test_run_refuel_balance_burst_rejects_without_print_regulation():
    controller = _make_refuel_controller(regulating_print_pressure=False)
    on_error = Mock()

    ok = Controller.run_refuel_balance_burst(controller, 20, 1000, on_error=on_error)

    assert ok is False
    controller.machine.print_droplets.assert_not_called()
    controller.machine.wait_ms.assert_not_called()
    on_error.assert_called_once()


def test_run_refuel_balance_burst_queues_dispense_and_wait_and_completes():
    controller = _make_refuel_controller()
    on_complete = Mock()

    ok = Controller.run_refuel_balance_burst(controller, 20, 1000, on_complete=on_complete)

    assert ok is True
    controller.machine.print_droplets.assert_called_once_with(20, manual=True)
    controller.machine.wait_ms.assert_called_once()
    _, kwargs = controller.machine.wait_ms.call_args
    assert kwargs["manual"] is True
    assert callable(kwargs["handler"])

    kwargs["handler"]()

    on_complete.assert_called_once_with(
        {"timestamp_utc": "2026-03-21T10:00:00Z", "monotonic_s": 10.0}
    )
