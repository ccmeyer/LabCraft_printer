from types import SimpleNamespace
from unittest.mock import Mock

from Controller import Controller


class _SignalRecorder:
    def __init__(self, events=None):
        self.calls = []
        self._events = events

    def emit(self, payload):
        payload = dict(payload)
        self.calls.append(payload)
        if self._events is not None:
            self._events.append(("interrupted", payload))


def _controller(events=None):
    controller = Controller.__new__(Controller)
    controller.machine_workflow_interrupted_signal = _SignalRecorder(events)
    controller._array_state = "idle"
    controller._array_context = None
    controller.update_expected_with_current = Mock(
        side_effect=(
            (lambda: events.append(("expected_updated", None)))
            if events is not None
            else None
        )
    )
    controller._reject_physical_action = Mock(return_value=None)
    return controller


def test_clear_queue_interrupts_pending_workflows_before_machine_clear():
    events = []
    controller = _controller(events)
    controller.machine = SimpleNamespace(
        clear_command_queue=lambda: events.append(("machine_clear", None))
    )
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            clear_command_queue=lambda: events.append(("model_clear", None))
        )
    )

    Controller.clear_command_queue(controller)

    assert events == [
        (
            "interrupted",
            {"reason": "queue_clear_requested", "notify_user": True},
        ),
        ("machine_clear", None),
        ("model_clear", None),
        ("expected_updated", None),
    ]


def test_mcu_reset_interrupts_pending_workflows_before_reset():
    events = []
    controller = _controller(events)
    controller.machine = SimpleNamespace(
        reset_mcu_board=lambda: events.append(("gpio_reset", None)),
        reset_board=lambda: events.append(("transport_reset", None)),
    )

    Controller.reset_mcu_board(controller)

    assert events == [
        (
            "interrupted",
            {"reason": "mcu_reset_requested", "notify_user": True},
        ),
        ("gpio_reset", None),
        ("transport_reset", None),
    ]


def test_disconnect_interrupts_pending_workflows_before_disconnect():
    events = []
    controller = _controller(events)
    controller.runtime_context = SimpleNamespace(is_simulation=True)
    controller.machine = SimpleNamespace(
        disconnect_board=lambda: events.append(("disconnect", None)) or True
    )

    assert Controller.disconnect_machine(controller) is True

    assert events == [
        (
            "interrupted",
            {"reason": "disconnect_requested", "notify_user": False},
        ),
        ("disconnect", None),
    ]


def test_workflow_interruption_payload_defaults_to_non_notifying():
    controller = _controller()

    payload = Controller._emit_machine_workflow_interrupted(
        controller,
        "serial_connection_lost",
    )

    assert payload == {
        "reason": "serial_connection_lost",
        "notify_user": False,
    }
    assert controller.machine_workflow_interrupted_signal.calls == [payload]
