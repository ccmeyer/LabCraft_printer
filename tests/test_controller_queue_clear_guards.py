import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from Controller import (
    Controller,
    QUEUE_CLEAR_INTENT_ARRAY_TERMINAL,
    QUEUE_CLEAR_INTENT_CALIBRATION_CLEANUP,
)


class _Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def _controller(*, connected=True, array_state="idle", context=None):
    controller = Controller.__new__(Controller)
    controller._array_state = array_state
    controller._array_context = context
    controller._soft_stop_clear_uncertain = False
    controller.error_occurred_signal = _Emitter()
    controller.array_state_changed = _Emitter()
    controller._record_print_array_audit_event = Mock()
    controller._emit_machine_workflow_interrupted = Mock()
    controller.update_expected_with_current = Mock()

    callbacks = []

    def _clear_command_queue(handler=None):
        callbacks.append(handler)
        return True

    machine_model = SimpleNamespace(
        machine_connected=bool(connected),
        clear_command_queue=Mock(),
        pause_commands=Mock(),
        transport_paused=True,
        pause_watermark_reached=True,
    )
    controller.model = SimpleNamespace(machine_model=machine_model)
    controller.machine = SimpleNamespace(
        clear_command_queue=Mock(side_effect=_clear_command_queue),
        pause_commands=Mock(return_value=True),
        get_xy_motion_recovery_state=Mock(return_value="idle"),
    )
    return controller, callbacks


def _confirmed_result(**overrides):
    result = {
        "ack_received": True,
        "ack_timed_out": False,
        "status_confirmed": True,
        "status_timed_out": False,
    }
    result.update(overrides)
    return result


def test_unclassified_clear_fails_closed_without_machine_or_model_mutation():
    controller, _callbacks = _controller()

    assert Controller.clear_command_queue(controller) is False

    controller.machine.clear_command_queue.assert_not_called()
    controller.model.machine_model.clear_command_queue.assert_not_called()
    assert Controller.get_queue_clear_state(controller)["last_rejection_reason"] == (
        "unclassified_clear_request"
    )


def test_confirmed_clear_updates_model_and_position_only_after_confirmed_status():
    controller, callbacks = _controller()

    assert Controller.clear_command_queue(controller, confirmed=True) is True
    assert len(callbacks) == 1
    controller.model.machine_model.clear_command_queue.assert_not_called()
    controller.update_expected_with_current.assert_not_called()
    assert Controller.get_queue_clear_state(controller)["state"] == "pending"

    callbacks[0](_confirmed_result())

    controller.model.machine_model.clear_command_queue.assert_called_once_with()
    controller.update_expected_with_current.assert_called_once_with()
    assert Controller.get_queue_clear_state(controller)["state"] == "idle"


def test_unconfirmed_status_keeps_model_conservative_and_marks_clear_uncertain():
    controller, callbacks = _controller()

    assert Controller.clear_command_queue(controller, confirmed=True) is True
    callbacks[0](_confirmed_result(status_confirmed=False, status_timed_out=True))

    controller.model.machine_model.clear_command_queue.assert_not_called()
    controller.update_expected_with_current.assert_not_called()
    assert Controller.get_queue_clear_state(controller)["state"] == "uncertain"


def test_confirmed_retry_resolves_legacy_soft_stop_clear_uncertainty():
    controller, callbacks = _controller()
    controller._queue_clear_state = "uncertain"
    controller._queue_clear_uncertain = True
    controller._soft_stop_clear_uncertain = True

    assert Controller.clear_command_queue(controller, confirmed=True) is True
    callbacks[0](_confirmed_result())

    assert Controller.get_queue_clear_state(controller)["state"] == "idle"
    assert controller._soft_stop_clear_uncertain is False


def test_rejected_retry_preserves_prior_uncertain_state():
    controller, _callbacks = _controller()
    controller._queue_clear_state = "uncertain"
    controller._queue_clear_uncertain = True
    controller.machine.clear_command_queue = Mock(return_value=False)

    assert Controller.clear_command_queue(controller, confirmed=True) is False

    assert Controller.get_queue_clear_state(controller)["state"] == "uncertain"
    controller.model.machine_model.clear_command_queue.assert_not_called()


def test_pending_clear_rejects_duplicate_and_late_callback_after_disconnect():
    controller, callbacks = _controller()

    assert Controller.clear_command_queue(controller, confirmed=True) is True
    assert Controller.clear_command_queue(controller, confirmed=True) is False
    controller.machine.clear_command_queue.assert_called_once()

    assert Controller._invalidate_queue_clear_attempt(
        controller,
        "machine_disconnected",
    ) is True
    callbacks[0](_confirmed_result())

    controller.model.machine_model.clear_command_queue.assert_not_called()
    assert Controller.get_queue_clear_state(controller)["state"] == "uncertain"


def test_disconnected_clear_is_rejected_before_transport():
    controller, _callbacks = _controller(connected=False)

    assert Controller.clear_command_queue(controller, confirmed=True) is False

    controller.machine.clear_command_queue.assert_not_called()
    assert Controller.get_queue_clear_state(controller)["last_rejection_reason"] == (
        "machine_disconnected"
    )


def test_calibration_cleanup_clear_is_blocked_for_active_or_uncertain_array():
    active, _callbacks = _controller(
        array_state="running",
        context={"finalize_reason": None},
    )
    assert Controller.request_calibration_cleanup_queue_clear(active) is False
    active.machine.clear_command_queue.assert_not_called()

    uncertain, _callbacks = _controller()
    uncertain._queue_clear_state = "uncertain"
    uncertain._queue_clear_uncertain = True
    assert Controller.request_calibration_cleanup_queue_clear(uncertain) is False
    uncertain.machine.clear_command_queue.assert_not_called()


def test_safe_stop_clear_requires_and_consumes_boundary_proof_once():
    context = {
        "soft_stop_pending": True,
        "soft_stop_phase": "clearing",
        "finalize_reason": "soft_stop",
        "soft_stop_clear_boundary_proof": None,
        "soft_stop_clear_boundary_proof_consumed": False,
    }
    controller, callbacks = _controller(
        array_state="stop_requested",
        context=context,
    )

    assert Controller._clear_command_queue_for_soft_stop(controller) is False
    controller.machine.clear_command_queue.assert_not_called()

    context["soft_stop_clear_boundary_proof"] = "watermark_reached"
    assert Controller._clear_command_queue_for_soft_stop(controller) is True
    assert context["soft_stop_clear_boundary_proof_consumed"] is True
    controller.machine.clear_command_queue.assert_called_once()

    callbacks[0](_confirmed_result())
    assert Controller._clear_command_queue_for_soft_stop(controller) is False
    controller.machine.clear_command_queue.assert_called_once()


def test_array_terminal_clear_requires_committed_finalization():
    controller, callbacks = _controller(
        array_state="stop_requested",
        context={"finalize_reason": None},
    )

    assert Controller._request_guarded_queue_clear(
        controller,
        QUEUE_CLEAR_INTENT_ARRAY_TERMINAL,
        reason="array_queue_clear",
    ) is False
    controller.machine.clear_command_queue.assert_not_called()

    controller._array_context["finalize_reason"] = "hard_abort"
    assert Controller._request_guarded_queue_clear(
        controller,
        QUEUE_CLEAR_INTENT_ARRAY_TERMINAL,
        reason="array_queue_clear",
    ) is True
    callbacks[0](_confirmed_result())
    controller.model.machine_model.clear_command_queue.assert_called_once_with()


def test_calibration_cleanup_intent_is_allowed_only_when_experiment_is_safe():
    controller, callbacks = _controller(array_state="resume_ready")

    assert Controller._request_guarded_queue_clear(
        controller,
        QUEUE_CLEAR_INTENT_CALIBRATION_CLEANUP,
        reason="calibration_profile_cleanup_clear",
    ) is True
    callbacks[0](_confirmed_result())

    controller.model.machine_model.clear_command_queue.assert_called_once_with()


def test_machine_clear_primitive_has_one_application_gateway():
    source_path = Path(__file__).parents[1] / "FreeRTOS-interface" / "Controller.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    callers = []

    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
            func = call.func
            if not isinstance(func, ast.Attribute) or func.attr != "clear_command_queue":
                continue
            owner = func.value
            if (
                isinstance(owner, ast.Attribute)
                and isinstance(owner.value, ast.Name)
                and owner.value.id == "self"
                and owner.attr == "machine"
            ):
                callers.append(function.name)

    assert callers == ["_request_guarded_queue_clear"]
