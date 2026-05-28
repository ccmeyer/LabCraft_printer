from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from CalibrationClasses.Model import RefuelCameraModel
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


def test_run_refuel_balance_burst_records_commanded_ejections_when_queued():
    controller = _make_refuel_controller()
    refuel_model = SimpleNamespace(record_refuel_ejection_event=Mock())
    controller.model.refuel_camera_model = refuel_model

    ok = Controller.run_refuel_balance_burst(controller, 20, 1000)

    assert ok is True
    refuel_model.record_refuel_ejection_event.assert_called_once()
    args, kwargs = refuel_model.record_refuel_ejection_event.call_args
    assert args == (20,)
    assert kwargs["count_kind"] == "commanded"
    assert kwargs["source"] == "Controller.run_refuel_balance_burst"


def test_run_refuel_balance_burst_does_not_record_when_print_queue_rejected():
    controller = _make_refuel_controller()
    controller.machine.print_droplets.return_value = False
    refuel_model = SimpleNamespace(record_refuel_ejection_event=Mock())
    controller.model.refuel_camera_model = refuel_model

    ok = Controller.run_refuel_balance_burst(controller, 20, 1000)

    assert ok is False
    refuel_model.record_refuel_ejection_event.assert_not_called()


def test_capture_refuel_image_with_context_returns_frame_and_context_and_starts_analysis():
    controller = Controller.__new__(Controller)
    frame = object()
    controller.machine = SimpleNamespace(capture_refuel_image=Mock(return_value=frame))
    refuel_camera_model = SimpleNamespace(start_analysis=Mock(return_value=True))
    controller.model = SimpleNamespace(refuel_camera_model=refuel_camera_model)
    controller._build_refuel_capture_context = Mock(
        return_value={"timestamp_utc": "2026-03-21T10:00:00Z", "monotonic_s": 12.0}
    )

    captured_frame, context = Controller.capture_refuel_image_with_context(
        controller,
        analyze=True,
        context_overrides={"refuel_monitor_tick_index": 7},
    )

    assert captured_frame is frame
    assert context["monotonic_s"] == 12.0
    assert context["refuel_monitor_tick_index"] == 7
    assert context["refuel_monitor_capture_duration_ms"] >= 0.0
    assert context["analysis_started"] is True
    refuel_camera_model.start_analysis.assert_called_once_with(frame, context=context)


def test_capture_refuel_image_with_context_adds_frame_signature_for_monitor_capture():
    controller = Controller.__new__(Controller)
    frame = np.full((12, 16, 3), 25, dtype=np.uint8)
    controller.machine = SimpleNamespace(capture_refuel_image=Mock(return_value=frame))
    refuel_camera_model = RefuelCameraModel()
    refuel_camera_model.start_analysis = Mock(return_value=True)
    controller.model = SimpleNamespace(refuel_camera_model=refuel_camera_model)
    controller._build_refuel_capture_context = Mock(
        return_value={"timestamp_utc": "2026-03-21T10:00:00Z", "monotonic_s": 12.0}
    )

    captured_frame, context = Controller.capture_refuel_image_with_context(
        controller,
        analyze=True,
        context_overrides={"refuel_monitor_tick_index": 7},
    )

    assert captured_frame is frame
    assert context["frame_signature_available"] is True
    assert context["frame_hash"]
    assert context["frame_signature_duration_ms"] >= 0.0
    assert context["frame_signature_source"] == "sampled_thumbnail"
    assert context["frame_signature_sample_shape"] == [12, 16, 3]
    assert context["captured_frame_count"] == 1
    assert refuel_camera_model.get_refuel_monitor_status()["captured_frames"] == 1
    refuel_camera_model.start_analysis.assert_called_once_with(frame, context=context)


def test_capture_refuel_image_with_context_continues_when_frame_signature_fails():
    controller = Controller.__new__(Controller)
    frame = np.full((12, 16, 3), 25, dtype=np.uint8)
    controller.machine = SimpleNamespace(capture_refuel_image=Mock(return_value=frame))
    refuel_camera_model = SimpleNamespace(
        build_refuel_frame_signature=Mock(side_effect=RuntimeError("signature failed")),
        record_refuel_monitor_frame_captured=Mock(return_value=1),
        start_analysis=Mock(return_value=True),
    )
    controller.model = SimpleNamespace(refuel_camera_model=refuel_camera_model)
    controller._build_refuel_capture_context = Mock(
        return_value={"timestamp_utc": "2026-03-21T10:00:00Z", "monotonic_s": 12.0}
    )

    captured_frame, context = Controller.capture_refuel_image_with_context(
        controller,
        analyze=True,
        context_overrides={"refuel_monitor_tick_index": 7},
    )

    assert captured_frame is frame
    assert context["frame_signature_available"] is False
    assert context["frame_signature_duration_ms"] >= 0.0
    assert context["captured_frame_count"] == 1
    refuel_camera_model.start_analysis.assert_called_once_with(frame, context=context)


def test_capture_refuel_image_with_context_marks_analysis_not_started_for_none_frame():
    controller = Controller.__new__(Controller)
    controller.machine = SimpleNamespace(capture_refuel_image=Mock(return_value=None))
    refuel_camera_model = SimpleNamespace(start_analysis=Mock())
    controller.model = SimpleNamespace(refuel_camera_model=refuel_camera_model)
    controller._build_refuel_capture_context = Mock(
        return_value={"timestamp_utc": "2026-03-21T10:00:00Z", "monotonic_s": 12.0}
    )

    captured_frame, context = Controller.capture_refuel_image_with_context(
        controller,
        analyze=True,
        context_overrides={"refuel_monitor_tick_index": 3},
    )

    assert captured_frame is None
    assert context["refuel_monitor_tick_index"] == 3
    assert context["refuel_monitor_capture_duration_ms"] >= 0.0
    assert context["analysis_started"] is False
    assert context["frame_signature_available"] is False
    refuel_camera_model.start_analysis.assert_not_called()


def test_capture_refuel_image_with_context_records_false_analysis_start():
    controller = Controller.__new__(Controller)
    frame = object()
    controller.machine = SimpleNamespace(capture_refuel_image=Mock(return_value=frame))
    refuel_camera_model = SimpleNamespace(start_analysis=Mock(return_value=False))
    controller.model = SimpleNamespace(refuel_camera_model=refuel_camera_model)
    controller._build_refuel_capture_context = Mock(
        return_value={"timestamp_utc": "2026-03-21T10:00:00Z", "monotonic_s": 12.0}
    )

    captured_frame, context = Controller.capture_refuel_image_with_context(controller, analyze=True)

    assert captured_frame is frame
    assert context["analysis_started"] is False


def test_capture_refuel_image_delegates_to_capture_with_context():
    controller = Controller.__new__(Controller)
    controller.capture_refuel_image_with_context = Mock(return_value=("frame", {"timestamp_utc": "2026-03-21T10:00:00Z"}))

    frame = Controller.capture_refuel_image(controller)

    assert frame == "frame"
    controller.capture_refuel_image_with_context.assert_called_once_with(analyze=True)


def test_print_droplets_records_commanded_ejections_after_success():
    controller = Controller.__new__(Controller)
    controller.profile = SimpleNamespace(name="current")
    controller.machine = SimpleNamespace(print_droplets=Mock(return_value=True))
    refuel_model = SimpleNamespace(record_refuel_ejection_event=Mock())
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(regulating_print_pressure=True),
        refuel_camera_model=refuel_model,
    )

    result = Controller.print_droplets(controller, 7, manual=True)

    assert result is True
    refuel_model.record_refuel_ejection_event.assert_called_once()
    args, kwargs = refuel_model.record_refuel_ejection_event.call_args
    assert args == (7,)
    assert kwargs["count_kind"] == "commanded"
    assert kwargs["event_kind"] == "print_droplets_queued"


def test_print_droplets_does_not_record_when_queue_rejected():
    controller = Controller.__new__(Controller)
    controller.profile = SimpleNamespace(name="current")
    controller.machine = SimpleNamespace(print_droplets=Mock(return_value=False))
    refuel_model = SimpleNamespace(record_refuel_ejection_event=Mock())
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(regulating_print_pressure=True),
        refuel_camera_model=refuel_model,
    )

    result = Controller.print_droplets(controller, 7)

    assert result is False
    refuel_model.record_refuel_ejection_event.assert_not_called()


def test_droplet_capture_success_records_observed_ejections():
    controller = Controller.__new__(Controller)
    refuel_model = SimpleNamespace(record_refuel_ejection_event=Mock())
    droplet_camera_model = SimpleNamespace(
        update_image=Mock(),
        get_num_droplets=Mock(return_value=3),
    )
    controller.model = SimpleNamespace(
        droplet_camera_model=droplet_camera_model,
        refuel_camera_model=refuel_model,
        machine_model=SimpleNamespace(get_current_position_dict=lambda: None),
        calibration_manager=SimpleNamespace(activeCalibration=None),
    )
    controller.machine = SimpleNamespace()
    controller.check_if_all_completed = Mock(return_value=True)
    controller.pending_capture_request_id = "req-1"
    controller.pending_capture_context = "droplet"
    controller.pending_capture_callback = None
    controller.pending_capture_active = True
    controller.pending_capture_guard_timer = None
    controller.pending_capture_started_monotonic = 1.0
    controller.pending_capture_recovery_attempted = False
    controller.pending_capture_throughput_mode = False

    Controller._complete_pending_capture_success(
        controller,
        object(),
        cap_info={"cap_id": "cap-1"},
    )

    refuel_model.record_refuel_ejection_event.assert_called_once()
    args, kwargs = refuel_model.record_refuel_ejection_event.call_args
    assert args == (3,)
    assert kwargs["count_kind"] == "observed"
    assert kwargs["event_kind"] == "capture_completed"
    assert kwargs["payload"]["cap_id"] == "cap-1"


def test_droplet_capture_background_records_no_observed_ejections():
    controller = Controller.__new__(Controller)
    refuel_model = SimpleNamespace(record_refuel_ejection_event=Mock())
    droplet_camera_model = SimpleNamespace(
        update_image=Mock(),
        get_num_droplets=Mock(return_value=0),
    )
    controller.model = SimpleNamespace(
        droplet_camera_model=droplet_camera_model,
        refuel_camera_model=refuel_model,
        machine_model=SimpleNamespace(get_current_position_dict=lambda: None),
        calibration_manager=SimpleNamespace(activeCalibration=None),
    )
    controller.machine = SimpleNamespace()
    controller.check_if_all_completed = Mock(return_value=True)
    controller.pending_capture_request_id = "req-1"
    controller.pending_capture_context = "background"
    controller.pending_capture_callback = None
    controller.pending_capture_active = True
    controller.pending_capture_guard_timer = None
    controller.pending_capture_started_monotonic = 1.0
    controller.pending_capture_recovery_attempted = False
    controller.pending_capture_throughput_mode = False

    Controller._complete_pending_capture_success(controller, object(), cap_info={"cap_id": "cap-1"})

    refuel_model.record_refuel_ejection_event.assert_not_called()


def test_start_refuel_camera_starts_camera_then_turns_led_on():
    controller = Controller.__new__(Controller)
    calls = []
    controller.machine = SimpleNamespace(
        start_refuel_camera=Mock(side_effect=lambda: calls.append("start_camera")),
        refuel_led_on=Mock(side_effect=lambda: calls.append("led_on")),
        refuel_led_off=Mock(),
        stop_refuel_camera=Mock(),
    )

    Controller.start_refuel_camera(controller)

    assert calls == ["start_camera", "led_on"]
    controller.machine.refuel_led_off.assert_not_called()
    controller.machine.stop_refuel_camera.assert_not_called()


def test_start_refuel_camera_cleans_up_if_led_on_fails():
    controller = Controller.__new__(Controller)
    controller.machine = SimpleNamespace(
        start_refuel_camera=Mock(),
        refuel_led_on=Mock(side_effect=RuntimeError("led on failed")),
        refuel_led_off=Mock(),
        stop_refuel_camera=Mock(),
    )

    with pytest.raises(RuntimeError, match="led on failed"):
        Controller.start_refuel_camera(controller)

    controller.machine.start_refuel_camera.assert_called_once_with()
    controller.machine.refuel_led_on.assert_called_once_with()
    controller.machine.refuel_led_off.assert_called_once_with()
    controller.machine.stop_refuel_camera.assert_called_once_with()


def test_stop_refuel_camera_stops_camera_then_turns_led_off():
    controller = Controller.__new__(Controller)
    calls = []
    controller.machine = SimpleNamespace(
        stop_refuel_camera=Mock(side_effect=lambda: calls.append("stop_camera")),
        refuel_led_off=Mock(side_effect=lambda: calls.append("led_off")),
    )

    Controller.stop_refuel_camera(controller)

    assert calls == ["stop_camera", "led_off"]


def test_stop_refuel_camera_turns_led_off_when_camera_stop_fails():
    controller = Controller.__new__(Controller)
    controller.machine = SimpleNamespace(
        stop_refuel_camera=Mock(side_effect=RuntimeError("camera stop failed")),
        refuel_led_off=Mock(),
    )

    with pytest.raises(RuntimeError, match="camera stop failed"):
        Controller.stop_refuel_camera(controller)

    controller.machine.stop_refuel_camera.assert_called_once_with()
    controller.machine.refuel_led_off.assert_called_once_with()


def test_stop_refuel_camera_propagates_led_off_failure():
    controller = Controller.__new__(Controller)
    controller.machine = SimpleNamespace(
        stop_refuel_camera=Mock(),
        refuel_led_off=Mock(side_effect=RuntimeError("led off failed")),
    )

    with pytest.raises(RuntimeError, match="led off failed"):
        Controller.stop_refuel_camera(controller)

    controller.machine.stop_refuel_camera.assert_called_once_with()
    controller.machine.refuel_led_off.assert_called_once_with()


def test_stop_refuel_camera_prioritizes_led_off_failure_over_camera_stop_failure():
    controller = Controller.__new__(Controller)
    controller.machine = SimpleNamespace(
        stop_refuel_camera=Mock(side_effect=RuntimeError("camera stop failed")),
        refuel_led_off=Mock(side_effect=RuntimeError("led off failed")),
    )

    with pytest.raises(RuntimeError, match="led off failed"):
        Controller.stop_refuel_camera(controller)

    controller.machine.stop_refuel_camera.assert_called_once_with()
    controller.machine.refuel_led_off.assert_called_once_with()
