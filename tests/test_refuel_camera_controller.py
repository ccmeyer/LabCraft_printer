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


def test_capture_refuel_image_with_context_returns_frame_and_context_and_starts_analysis():
    controller = Controller.__new__(Controller)
    frame = object()
    controller.machine = SimpleNamespace(capture_refuel_image=Mock(return_value=frame))
    refuel_camera_model = SimpleNamespace(start_analysis=Mock())
    controller.model = SimpleNamespace(refuel_camera_model=refuel_camera_model)
    controller._build_refuel_capture_context = Mock(
        return_value={"timestamp_utc": "2026-03-21T10:00:00Z", "monotonic_s": 12.0}
    )

    captured_frame, context = Controller.capture_refuel_image_with_context(controller, analyze=True)

    assert captured_frame is frame
    assert context["monotonic_s"] == 12.0
    refuel_camera_model.start_analysis.assert_called_once_with(frame, context=context)


def test_capture_refuel_image_delegates_to_capture_with_context():
    controller = Controller.__new__(Controller)
    controller.capture_refuel_image_with_context = Mock(return_value=("frame", {"timestamp_utc": "2026-03-21T10:00:00Z"}))

    frame = Controller.capture_refuel_image(controller)

    assert frame == "frame"
    controller.capture_refuel_image_with_context.assert_called_once_with(analyze=True)
