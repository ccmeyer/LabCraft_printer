from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

import CalibrationClasses.View as calibration_view
from CaptureCoordinator import CaptureCoordinatorState
from CaptureTypes import CaptureStatus
from Controller import Controller
from CalibrationClasses.View import DropletImagingDialog


class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs):
        for callback in list(self._callbacks):
            callback(*args, **kwargs)


class _CaptureGuardTimer:
    def __init__(self):
        self.timeout = _Signal()
        self.interval_ms = None
        self.active = False
        self.single_shot = False

    def setSingleShot(self, single_shot):
        self.single_shot = bool(single_shot)

    def setInterval(self, interval_ms):
        self.interval_ms = int(interval_ms)

    def start(self, interval_ms=None):
        if interval_ms is not None:
            self.interval_ms = int(interval_ms)
        self.active = True

    def stop(self):
        self.active = False

    def fire(self):
        if self.single_shot:
            self.active = False
        self.timeout.emit()


class _CloseEvent:
    def __init__(self):
        self.accepted = False
        self.ignored = False

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


class _WidgetState:
    def __init__(self):
        self.enabled = None
        self.text = ""
        self.tooltip = ""

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setText(self, text):
        self.text = str(text)

    def setToolTip(self, text):
        self.tooltip = str(text)


class _DropletCamera:
    def __init__(self):
        self.frame = np.full((8, 10, 3), 77, dtype=np.uint8)

    def get_latest_frame(self):
        return self.frame

    def get_last_capture_result(self):
        return {"cap_id": 123, "reason": "threshold"}


class _Machine:
    def __init__(self):
        self.droplet_camera = _DropletCamera()
        self.capture_calls = []
        self.last_capture_context = None
        self.recover_calls = []
        self.commands_idle = True
        self.capture_return = True
        self.recover_return = {"ok": True, "ready_for_retry": True}
        self.capture_state = {
            "cap_active": False,
            "worker_active": False,
            "camera_started": True,
        }

    def capture_droplet_image(self, *, throughput_mode=False, capture_request_id=None, capture_context=None):
        self.last_capture_context = capture_context
        self.capture_calls.append(
            {
                "throughput_mode": bool(throughput_mode),
                "capture_request_id": capture_request_id,
            }
        )
        return self.capture_return

    def recover_droplet_capture(self, reason=""):
        self.recover_calls.append(str(reason))
        self.capture_state.update(
            {
                "cap_active": False,
                "worker_active": False,
            }
        )
        return dict(self.recover_return)

    def get_droplet_capture_state(self):
        return dict(self.capture_state)

    def check_if_all_completed(self):
        return self.commands_idle


class _MachineModel:
    def get_current_position_dict(self):
        return {"X": 101, "Y": 202, "Z": 303}


class _CameraModel:
    def __init__(self):
        self.update_calls = []
        self.flash_session_armed = True
        self.flash_fault_latched = False
        self.flash_fault_reason = ""

    def get_flash_session_armed(self):
        return bool(self.flash_session_armed)

    def get_flash_fault_latched(self):
        return bool(self.flash_fault_latched)

    def get_flash_fault_reason(self):
        return str(self.flash_fault_reason or "")

    def update_image(self, frame, *, capture_info=None, save_metadata=None):
        self.update_calls.append(
            {
                "frame": frame,
                "capture_info": capture_info,
                "save_metadata": save_metadata,
            }
        )


def _make_controller():
    controller = Controller.__new__(Controller)
    machine = _Machine()
    camera_model = _CameraModel()
    clock = {"value": 100.0}
    controller.machine = machine
    controller.model = SimpleNamespace(
        machine_model=_MachineModel(),
        droplet_camera_model=camera_model,
        calibration_manager=SimpleNamespace(captureFailed=Mock(), activeCalibration=None),
    )
    controller.expected_position = {"X": 111, "Y": 222, "Z": 333}
    controller.pending_capture_callback = None
    controller.pending_capture_context = None
    controller.pending_capture_active = False
    controller.pending_capture_started_monotonic = None
    controller.pending_capture_timeout_ms = 8_000
    controller.pending_capture_throughput_timeout_ms = 1_500
    controller.pending_capture_guard_timer = None
    controller.pending_capture_request_id = None
    controller.pending_capture_recovery_attempted = False
    controller.pending_capture_throughput_mode = False
    controller.last_capture_queue_rejection_reason = None
    controller.last_capture_queue_rejection_state = None
    controller.droplet_imager_dirty_shutdown = False
    controller._timer_factory = lambda _parent: _CaptureGuardTimer()
    controller._monotonic_fn = lambda: clock["value"]
    controller._test_clock = clock
    return controller, machine, camera_model


def test_controller_lazily_creates_capture_coordinator_for_new_constructed_tests():
    controller, _machine, _camera_model = _make_controller()

    assert not hasattr(controller, "capture_coordinator")

    coordinator = controller._ensure_capture_coordinator()

    assert coordinator.state is CaptureCoordinatorState.IDLE
    assert controller.capture_coordinator is coordinator


def test_controller_bootstraps_coordinator_from_legacy_pending_fields():
    controller, _machine, _camera_model = _make_controller()
    callback = Mock()
    controller.pending_capture_active = True
    controller.pending_capture_request_id = "legacy-request"
    controller.pending_capture_callback = callback
    controller.pending_capture_context = "legacy_context"
    controller.pending_capture_started_monotonic = 42.5
    controller.pending_capture_recovery_attempted = True
    controller.pending_capture_throughput_mode = True

    coordinator = controller._ensure_capture_coordinator()
    snapshot = controller._capture_pending_snapshot()

    assert coordinator.pending_active is True
    assert coordinator.pending_request_id == "legacy-request"
    assert coordinator.pending_callback is callback
    assert coordinator.pending_context == "legacy_context"
    assert coordinator.pending_started_monotonic == 42.5
    assert coordinator.pending_recovery_attempted is True
    assert coordinator.pending_throughput_mode is True
    assert snapshot["request_id"] == "legacy-request"
    assert controller.pending_capture_active is True


def test_controller_droplet_capture_ui_state_reports_pending_last_result_and_dirty_shutdown():
    controller, _machine, _camera_model = _make_controller()

    idle_state = controller.get_droplet_capture_ui_state()

    assert idle_state["pending_active"] is False
    assert idle_state["pending_request_id"] is None
    assert idle_state["coordinator_state"] == "idle"
    assert idle_state["last_result_status"] is None
    assert idle_state["dirty_shutdown"] is False

    assert controller.capture_droplet_image(capture_context="optics_scale_bar") is True
    pending_state = controller.get_droplet_capture_ui_state()

    assert pending_state["pending_active"] is True
    assert pending_state["pending_request_id"] == controller.pending_capture_request_id
    assert pending_state["pending_context"] == "optics_scale_bar"
    assert pending_state["pending_started_monotonic"] == 100.0
    assert pending_state["pending_recovery_attempted"] is False
    assert pending_state["pending_throughput_mode"] is False
    assert pending_state["coordinator_state"] == "capturing"
    assert pending_state["flash_session_armed"] is True
    assert pending_state["flash_session_request_id"] == controller.pending_capture_request_id
    assert pending_state["flash_session_context"] == "optics_scale_bar"
    assert pending_state["flash_preflight_active"] is False

    controller._on_image_captured()
    completed_state = controller.get_droplet_capture_ui_state()

    assert completed_state["pending_active"] is False
    assert completed_state["last_result_status"] == CaptureStatus.SUCCESS.value
    assert completed_state["last_result_reason"] == "threshold"
    assert completed_state["last_result_stale"] is False
    assert completed_state["last_result_dirty_shutdown"] is False
    assert completed_state["flash_session_armed"] is False


def test_controller_droplet_capture_ui_state_bootstraps_legacy_pending_fields():
    controller, _machine, _camera_model = _make_controller()
    controller.pending_capture_active = True
    controller.pending_capture_request_id = "legacy-request"
    controller.pending_capture_context = "legacy_context"
    controller.pending_capture_started_monotonic = 42.5
    controller.pending_capture_recovery_attempted = True
    controller.pending_capture_throughput_mode = True

    state = controller.get_droplet_capture_ui_state()

    assert state["pending_active"] is True
    assert state["pending_request_id"] == "legacy-request"
    assert state["pending_context"] == "legacy_context"
    assert state["pending_started_monotonic"] == 42.5
    assert state["pending_recovery_attempted"] is True
    assert state["pending_throughput_mode"] is True
    assert state["coordinator_state"] == "capturing"


def test_controller_droplet_capture_perf_enable_disable_and_disabled_noop():
    controller, _machine, _camera_model = _make_controller()

    assert controller.record_droplet_capture_performance_marker("ui_trigger_received") is None
    assert not hasattr(controller, "_droplet_capture_performance_diagnostics")

    assert controller.set_droplet_capture_performance_diagnostics_enabled(True) is True
    assert controller.is_droplet_capture_performance_diagnostics_enabled() is True
    controller.record_droplet_capture_performance_marker("ui_trigger_received", {"ui_sequence": 1})
    snapshot = controller.build_droplet_capture_performance_snapshot()
    assert snapshot["event_count"] == 3
    assert snapshot["event_log_tail"][0]["event_kind"] == "diagnostics_enabled"
    assert snapshot["event_log_tail"][1]["event_kind"] == "calibration_diagnostics_bridge_status"

    assert controller.set_droplet_capture_performance_diagnostics_enabled(False) is False
    assert controller.is_droplet_capture_performance_diagnostics_enabled() is False
    controller.record_droplet_capture_performance_marker("ui_trigger_received", {"ui_sequence": 2})
    assert controller.build_droplet_capture_performance_snapshot()["event_count"] == 3


def test_controller_droplet_capture_perf_records_rejection_when_enabled():
    controller, _machine, _camera_model = _make_controller()
    controller.set_droplet_capture_performance_diagnostics_enabled(True)

    assert controller.capture_droplet_image(capture_context="first") is True
    assert controller.capture_droplet_image(capture_context="second") is False

    snapshot = controller.build_droplet_capture_performance_snapshot()
    rejected = [
        row for row in snapshot["event_log_tail"]
        if row["event_kind"] == "controller_capture_rejected"
    ]
    assert rejected
    assert rejected[-1]["reason"] == "controller_pending"
    assert rejected[-1]["pending_request_id"] == controller.pending_capture_request_id


def test_controller_droplet_capture_perf_records_camera_phase():
    controller, _machine, _camera_model = _make_controller()
    controller.set_droplet_capture_performance_diagnostics_enabled(True)

    controller._on_camera_capture_phase({"request_id": "r1", "phase": "edge_wait_done", "elapsed_ms": 5.0})

    snapshot = controller.build_droplet_capture_performance_snapshot()
    assert snapshot["event_counts"]["camera_phase"] == 1
    camera_phase = next(row for row in snapshot["event_log_tail"] if row["event_kind"] == "camera_phase")
    assert camera_phase["phase"] == "edge_wait_done"


def test_controller_droplet_capture_perf_completion_payload_timings():
    controller, _machine, _camera_model = _make_controller()
    controller.set_droplet_capture_performance_diagnostics_enabled(True)

    assert controller.capture_droplet_image(capture_context="perf") is True
    request_id = controller.pending_capture_request_id
    frame = np.full((4, 5, 3), 9, dtype=np.uint8)

    controller._on_capture_completed_payload(
        {
            "request_id": request_id,
            "status": "success",
            "frame": frame,
            "cap_id": 7,
            "generation": 10,
            "backend_id": 2,
            "capture_context": "perf",
            "queued_monotonic_ns": 1_000,
            "worker_started_monotonic_ns": 2_001_000,
            "worker_completed_monotonic_ns": 7_001_000,
        }
    )

    snapshot = controller.build_droplet_capture_performance_snapshot()
    completion = next(row for row in snapshot["event_log_tail"] if row["event_kind"] == "controller_completion_received")
    assert completion["request_id"] == request_id
    assert completion["status"] == "success"
    assert completion["queue_to_worker_start_ms"] == 2.0
    assert completion["worker_duration_ms"] == 5.0
    assert completion["worker_complete_to_controller_ms"] is not None
    assert any(row["event_kind"] == "model_image_updated" for row in snapshot["event_log_tail"])
    assert any(row["event_kind"] == "controller_pending_cleared" for row in snapshot["event_log_tail"])


def test_controller_mark_droplet_imager_force_close_marks_dirty_without_machine_cleanup():
    controller, machine, _camera_model = _make_controller()
    assert controller.capture_droplet_image(capture_context="force_close") is True
    timer = controller.pending_capture_guard_timer

    result = controller.mark_droplet_imager_force_close("imager_force_close")

    assert result == {
        "dirty_shutdown": True,
        "detached": True,
        "result_status": CaptureStatus.DETACHED_FORCE_CLOSE.value,
        "reason": "imager_force_close",
    }
    assert controller.droplet_imager_dirty_shutdown is True
    assert controller.pending_capture_active is False
    assert controller.capture_coordinator.pending_active is False
    assert controller.capture_coordinator.last_result.status is CaptureStatus.DETACHED_FORCE_CLOSE
    assert controller.capture_coordinator.last_result.dirty_shutdown is True
    assert controller.capture_coordinator.flash_session_snapshot()["armed"] is False
    assert controller.capture_coordinator.flash_session_snapshot()["disarm_reason"] == "imager_force_close"
    assert timer.active is False
    assert machine.recover_calls == []
    assert machine.capture_calls == [
        {"throughput_mode": False, "capture_request_id": controller.capture_coordinator.last_result.request_id}
    ]
    state = controller.get_droplet_capture_ui_state()
    assert state["dirty_shutdown"] is True
    assert state["last_result_dirty_shutdown"] is True


def test_controller_capture_context_is_written_to_next_frame_metadata():
    controller, machine, camera_model = _make_controller()

    assert controller.capture_droplet_image(capture_context="optics_scale_bar") is True
    assert machine.last_capture_context == "optics_scale_bar"
    assert machine.capture_calls[0]["throughput_mode"] is False
    assert machine.capture_calls[0]["capture_request_id"]
    assert controller.capture_coordinator.active_request.request_id == controller.pending_capture_request_id
    assert controller.capture_coordinator.pending_request_id == controller.pending_capture_request_id
    assert controller.capture_coordinator.state is CaptureCoordinatorState.CAPTURING
    assert controller.capture_coordinator.flash_session_snapshot()["armed"] is True
    assert controller._capture_pending_snapshot()["context"] == "optics_scale_bar"
    assert controller.pending_capture_context == "optics_scale_bar"
    assert controller.pending_capture_active is True

    controller._on_image_captured()

    assert controller.capture_coordinator.state is CaptureCoordinatorState.IDLE
    assert controller.capture_coordinator.active_request is None
    assert controller.capture_coordinator.pending_active is False
    assert controller.capture_coordinator.last_result.status is CaptureStatus.SUCCESS
    assert controller.capture_coordinator.flash_session_snapshot()["armed"] is False
    assert controller.capture_coordinator.flash_session_snapshot()["disarm_reason"] == "threshold"
    assert controller.pending_capture_context is None
    assert controller.pending_capture_active is False
    assert len(camera_model.update_calls) == 1
    call = camera_model.update_calls[0]
    assert call["capture_info"] == {"cap_id": 123, "reason": "threshold"}
    assert call["save_metadata"]["capture_context"] == "optics_scale_bar"
    assert call["save_metadata"]["X_position"] == 111
    assert call["save_metadata"]["Y_position"] == 222
    assert call["save_metadata"]["Z_position"] == 333
    assert call["save_metadata"]["controller_expected_position"] == {"X": 111, "Y": 222, "Z": 333}
    assert call["save_metadata"]["machine_position"] == {"X": 101, "Y": 202, "Z": 303}
    assert call["save_metadata"]["position_source"] == "controller_expected_position"
    assert call["save_metadata"]["commands_idle_at_frame"] is True
    assert isinstance(call["save_metadata"]["position_recorded_at"], str)


def test_controller_unarmed_flash_preflight_rejects_before_machine_capture():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()
    controller.model.droplet_camera_model.flash_session_armed = False
    controller.flash_session_preflight_timeout_ms = 0

    assert controller.capture_droplet_image(callback=callback, capture_context="preflight") is False

    assert machine.capture_calls == []
    assert controller.pending_capture_active is False
    assert controller.capture_coordinator.last_result.status is CaptureStatus.FLASH_DISARMED
    assert controller.capture_coordinator.flash_session_snapshot()["armed"] is False
    assert controller.capture_coordinator.flash_session_snapshot()["disarm_reason"] == "flash_disarmed"
    callback.assert_called_once_with(None)
    assert getattr(callback, "_capture_rejection_reason") == "flash_disarmed"
    assert getattr(callback, "_capture_result_status") == CaptureStatus.FLASH_DISARMED.value


def test_controller_fault_latched_preflight_rejects_before_machine_capture():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()
    machine.get_flash_safety_state = lambda: {
        "flash_session_armed": False,
        "flash_fault_latched": True,
        "flash_fault_reason": "line_stuck_high",
    }

    assert controller.capture_droplet_image(callback=callback, capture_context="preflight_fault") is False

    assert machine.capture_calls == []
    assert controller.pending_capture_active is False
    assert controller.capture_coordinator.last_result.status is CaptureStatus.FIRMWARE_FLASH_LATCHED
    assert controller.capture_coordinator.last_result.metadata["flash_fault_reason"] == "line_stuck_high"
    assert controller.capture_coordinator.last_result.metadata["flash_fault_source"] == "machine"
    assert controller.capture_coordinator.last_result.metadata["rejection_state"]["flash_fault_reason"] == "line_stuck_high"
    assert controller.capture_coordinator.flash_session_snapshot()["armed"] is False
    assert controller.capture_coordinator.flash_session_snapshot()["disarm_reason"] == "firmware_flash_latched"
    callback.assert_called_once_with(None)
    assert getattr(callback, "_capture_rejection_reason") == "firmware_flash_latched"
    assert getattr(callback, "_capture_result_status") == CaptureStatus.FIRMWARE_FLASH_LATCHED.value
    assert getattr(callback, "_capture_result_metadata")["flash_fault_reason"] == "line_stuck_high"


def test_controller_model_latched_fault_routes_through_coordinator():
    controller, machine, camera_model = _make_controller()
    callback = Mock()
    camera_model.flash_session_armed = False
    camera_model.flash_fault_latched = True
    camera_model.flash_fault_reason = "flash_ack_timeout"

    assert controller.capture_droplet_image(callback=callback, capture_context="model_fault") is False

    assert machine.capture_calls == []
    assert controller.pending_capture_active is False
    assert controller.capture_coordinator.last_result.status is CaptureStatus.FIRMWARE_FLASH_LATCHED
    assert controller.capture_coordinator.last_result.reason == "firmware_flash_latched"
    assert controller.capture_coordinator.last_result.metadata["flash_fault_reason"] == "flash_ack_timeout"
    assert controller.capture_coordinator.last_result.metadata["flash_fault_source"] == "model"
    callback.assert_called_once_with(None)
    assert getattr(callback, "_capture_rejection_reason") == "firmware_flash_latched"
    assert getattr(callback, "_capture_result_status") == CaptureStatus.FIRMWARE_FLASH_LATCHED.value

    cancel_result = controller.cancel_pending_droplet_capture(
        "after_fault_block",
        emit_capture_failed=False,
        recover=False,
    )
    assert cancel_result["cancelled"] is False
    assert camera_model.flash_fault_latched is True
    assert camera_model.flash_fault_reason == "flash_ack_timeout"


def test_controller_flash_safety_state_any_latched_source_wins():
    controller, machine, camera_model = _make_controller()
    camera_model.flash_session_armed = True
    camera_model.flash_fault_latched = True
    camera_model.flash_fault_reason = "line_high_on_arm"
    machine.get_flash_safety_state = lambda: {
        "flash_session_armed": True,
        "flash_fault_latched": False,
        "flash_fault_reason": "",
    }

    state = controller._get_flash_safety_state()

    assert state["flash_fault_latched"] is True
    assert state["flash_session_armed"] is False
    assert state["flash_fault_reason"] == "line_high_on_arm"
    assert state["flash_fault_source"] == "model"
    assert state["flash_armed_source"] == "model,machine"

    camera_model.flash_fault_latched = False
    camera_model.flash_fault_reason = ""
    machine.get_flash_safety_state = lambda: {
        "flash_session_armed": False,
        "flash_fault_latched": True,
        "flash_fault_reason": "print_completion_timeout",
    }

    state = controller._get_flash_safety_state()

    assert state["flash_fault_latched"] is True
    assert state["flash_session_armed"] is False
    assert state["flash_fault_reason"] == "print_completion_timeout"
    assert state["flash_fault_source"] == "machine"


def test_controller_droplet_capture_ui_state_reports_flash_fault_primitives():
    controller, _machine, camera_model = _make_controller()
    camera_model.flash_session_armed = False
    camera_model.flash_fault_latched = True
    camera_model.flash_fault_reason = "retrigger_while_high"

    state = controller.get_droplet_capture_ui_state()

    assert state["flash_fault_latched"] is True
    assert state["flash_fault_reason"] == "retrigger_while_high"
    assert state["flash_fault_status"] == CaptureStatus.FIRMWARE_FLASH_LATCHED.value


def test_controller_preflight_cancellation_does_not_queue_machine_capture():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()
    controller.model.droplet_camera_model.flash_session_armed = False
    controller.flash_session_preflight_timeout_ms = 50
    controller.flash_session_preflight_poll_ms = 1
    process_calls = []

    def cancel_during_preflight(_poll_ms):
        process_calls.append(_poll_ms)
        if len(process_calls) == 1:
            controller.cancel_pending_droplet_capture(
                "operator_stop_during_preflight",
                emit_capture_failed=False,
                recover=False,
            )

    controller._process_flash_preflight_events = cancel_during_preflight

    assert controller.capture_droplet_image(callback=callback, capture_context="preflight_cancel") is False

    assert process_calls
    assert machine.capture_calls == []
    callback.assert_called_once_with(None)
    assert controller.pending_capture_active is False
    assert controller.capture_coordinator.last_result.status is CaptureStatus.CANCELLED
    assert controller.capture_coordinator.flash_session_snapshot()["armed"] is False


def test_controller_queued_capture_stores_expected_machine_identity_metadata():
    controller, machine, _camera_model = _make_controller()
    machine.capture_state.update(
        {
            "generation": 7,
            "backend_id": "backend-A",
            "cap_id": 12,
            "request_id": "machine-request",
        }
    )

    assert controller.capture_droplet_image(capture_context="identity_ctx") is True

    metadata = controller.capture_coordinator.active_request.metadata
    assert metadata["expected_generation"] == 7
    assert metadata["expected_backend_id"] == "backend-A"
    assert metadata["queued_machine_request_id"] == "machine-request"
    assert metadata["queued_machine_cap_id"] == 12
    assert isinstance(metadata["queued_monotonic_ns"], int)
    assert metadata["capture_context"] == "identity_ctx"
    assert machine.last_capture_context == "identity_ctx"


def test_controller_matching_request_and_generation_completes_active_request():
    controller, machine, camera_model = _make_controller()
    callback = Mock()
    machine.capture_state.update({"generation": 4, "backend_id": "backend-A"})
    frame = np.full((4, 5, 3), 88, dtype=np.uint8)

    assert controller.capture_droplet_image(callback=callback, capture_context="identity_ctx") is True
    request_id = controller.pending_capture_request_id
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": request_id,
            "generation": 4,
            "backend_id": "backend-A",
            "capture_context": "identity_ctx",
            "cap_id": 321,
            "frame": frame,
            "capture_info": {"cap_id": 321, "reason": "threshold"},
            "queued_monotonic_ns": 10,
            "worker_started_monotonic_ns": 20,
            "worker_completed_monotonic_ns": 30,
        }
    )

    callback.assert_called_once_with(frame)
    assert controller.pending_capture_active is False
    assert controller.capture_coordinator.last_result.status is CaptureStatus.SUCCESS
    capture_info = camera_model.update_calls[0]["capture_info"]
    assert capture_info["generation"] == 4
    assert capture_info["backend_id"] == "backend-A"
    assert capture_info["capture_context"] == "identity_ctx"
    assert capture_info["worker_completed_monotonic_ns"] == 30


def test_controller_same_request_mismatched_generation_is_stale_ignored():
    controller, machine, camera_model = _make_controller()
    callback = Mock()
    machine.capture_state.update({"generation": 7, "backend_id": "backend-A"})
    frame = np.full((4, 5, 3), 44, dtype=np.uint8)

    assert controller.capture_droplet_image(callback=callback) is True
    request_id = controller.pending_capture_request_id
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": request_id,
            "generation": 8,
            "backend_id": "backend-A",
            "cap_id": 111,
            "frame": frame,
            "capture_info": {"cap_id": 111},
        }
    )

    callback.assert_not_called()
    assert camera_model.update_calls == []
    assert controller.pending_capture_active is True
    assert controller.pending_capture_request_id == request_id
    result = controller.capture_coordinator.last_result
    assert result.status is CaptureStatus.STALE_IGNORED
    assert result.metadata["mismatch_reason"] == "generation_mismatch"
    assert result.metadata["expected_generation"] == 7
    assert result.metadata["generation"] == 8


def test_controller_same_request_missing_generation_is_stale_when_expected_known():
    controller, machine, camera_model = _make_controller()
    callback = Mock()
    machine.capture_state.update({"generation": 7, "backend_id": "backend-A"})

    assert controller.capture_droplet_image(callback=callback) is True
    request_id = controller.pending_capture_request_id
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": request_id,
            "backend_id": "backend-A",
            "cap_id": 112,
            "frame": np.full((4, 5, 3), 45, dtype=np.uint8),
            "capture_info": {"cap_id": 112},
        }
    )

    callback.assert_not_called()
    assert camera_model.update_calls == []
    assert controller.pending_capture_request_id == request_id
    assert controller.capture_coordinator.last_result.status is CaptureStatus.STALE_IGNORED
    assert controller.capture_coordinator.last_result.metadata["mismatch_reason"] == "missing_generation"


def test_controller_same_request_mismatched_backend_is_stale_when_both_present():
    controller, machine, camera_model = _make_controller()
    callback = Mock()
    machine.capture_state.update({"generation": 7, "backend_id": "backend-A"})

    assert controller.capture_droplet_image(callback=callback) is True
    request_id = controller.pending_capture_request_id
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": request_id,
            "generation": 7,
            "backend_id": "backend-B",
            "cap_id": 113,
            "frame": np.full((4, 5, 3), 46, dtype=np.uint8),
            "capture_info": {"cap_id": 113},
        }
    )

    callback.assert_not_called()
    assert camera_model.update_calls == []
    assert controller.pending_capture_request_id == request_id
    assert controller.capture_coordinator.last_result.status is CaptureStatus.STALE_IGNORED
    assert controller.capture_coordinator.last_result.metadata["mismatch_reason"] == "backend_id_mismatch"


def test_controller_capture_context_is_one_shot():
    controller, _machine, camera_model = _make_controller()

    assert controller.capture_droplet_image(capture_context="optics_scale_bar") is True
    controller._on_image_captured()
    controller._on_image_captured()

    assert camera_model.update_calls[0]["save_metadata"]["capture_context"] == "optics_scale_bar"
    assert "capture_context" not in camera_model.update_calls[1]["save_metadata"]


def test_controller_clears_pending_callback_when_camera_rejects_capture():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()
    machine.capture_return = False

    assert controller.capture_droplet_image(callback=callback, capture_context="optics_scale_bar") is False

    assert controller.pending_capture_callback is None
    assert controller.pending_capture_context is None
    assert controller.pending_capture_active is False
    assert controller.capture_coordinator.state is CaptureCoordinatorState.IDLE
    assert controller.capture_coordinator.pending_active is False
    assert controller._capture_pending_snapshot()["active"] is False
    assert controller.capture_coordinator.last_result.status is CaptureStatus.QUEUE_REJECTED
    callback.assert_called_once_with(None)
    assert getattr(callback, "_capture_rejection_reason") == "machine_rejected"


def test_controller_clear_pending_capture_respects_callback_and_context_filters():
    controller, _machine, _camera_model = _make_controller()
    callback = Mock()

    assert controller.capture_droplet_image(callback=callback, capture_context="ctx") is True
    request_id = controller.pending_capture_request_id

    assert controller._clear_pending_capture(callback=Mock()) is False
    assert controller.pending_capture_active is True
    assert controller.pending_capture_request_id == request_id
    assert controller.capture_coordinator.pending_request_id == request_id

    assert controller._clear_pending_capture(capture_context="other") is False
    assert controller.pending_capture_active is True
    assert controller.pending_capture_request_id == request_id

    assert controller._clear_pending_capture(callback=callback, capture_context="ctx") is True
    assert controller.pending_capture_active is False
    assert controller.capture_coordinator.pending_active is False


def test_controller_classifies_backend_unavailable_queue_rejection():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()
    machine.capture_return = False
    machine.capture_state.update(
        {
            "backend_available": False,
            "backend_error": "[Errno 16] Device or resource busy",
            "backend_create_step": "edge_input",
        }
    )

    assert controller.capture_droplet_image(callback=callback, capture_context="optics_scale_bar") is False

    callback.assert_called_once_with(None)
    assert getattr(callback, "_capture_rejection_reason") == "camera_backend_unavailable"


def test_controller_queue_rejection_callback_metadata_preserves_typed_camera_states():
    cases = [
        (
            {"cap_active": True},
            "camera_capture_active",
            CaptureStatus.BUSY.value,
        ),
        (
            {"camera_started": False},
            "camera_not_started",
            CaptureStatus.BACKEND_UNAVAILABLE.value,
        ),
        (
            {
                "camera_started": True,
                "backend_available": False,
                "backend_error": "gpio_edge_fd_unavailable: missing event_get_fd",
            },
            "camera_backend_unsupported",
            CaptureStatus.BACKEND_UNAVAILABLE.value,
        ),
    ]
    for state_update, expected_reason, expected_status in cases:
        controller, machine, _camera_model = _make_controller()
        callback = Mock()
        machine.capture_return = False
        machine.capture_state.update(state_update)

        assert controller.capture_droplet_image(callback=callback, capture_context="optics_scale_bar") is False

        callback.assert_called_once_with(None)
        assert getattr(callback, "_capture_rejection_reason") == expected_reason
        assert getattr(callback, "_capture_result_status") == expected_status


def test_controller_classifies_missing_gpio_fd_as_backend_unsupported():
    assert Controller._classify_capture_queue_rejection(
        {
            "camera_started": True,
            "backend_available": False,
            "backend_error": "gpio_edge_fd_unavailable: missing event_get_fd",
        }
    ) == "camera_backend_unsupported"


def test_controller_blocks_overlapping_capture_until_frame_finishes():
    controller, machine, _camera_model = _make_controller()

    assert controller.capture_droplet_image() is True
    assert controller.capture_droplet_image() is False
    assert len(machine.capture_calls) == 1

    controller._on_image_captured()

    assert controller.capture_droplet_image() is True
    assert len(machine.capture_calls) == 2


def test_controller_failed_edge_timeout_completion_clears_pending_before_guard_timeout():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()

    assert controller.capture_droplet_image(callback=callback) is True
    request_id = controller.pending_capture_request_id
    timer = controller.pending_capture_guard_timer

    controller._on_capture_completed_payload(
        {
            "status": "failed",
            "request_id": request_id,
            "cap_id": 0,
            "reason": "edge_timeout",
            "error": "Flash capture failed after 1 attempts (last_reason=edge_timeout)",
        }
    )

    callback.assert_called_once_with(None)
    controller.model.calibration_manager.captureFailed.emit.assert_called_once()
    assert controller.pending_capture_active is False
    assert machine.recover_calls == []

    controller._test_clock["value"] = 109.0
    timer.fire()

    assert machine.recover_calls == []


def test_controller_cancel_pending_capture_recovers_clears_waiter_and_ignores_late_frame():
    controller, machine, camera_model = _make_controller()
    callback = Mock()

    assert controller.capture_droplet_image(callback=callback, capture_context="unit_cancel") is True
    request_id = controller.pending_capture_request_id
    timer = controller.pending_capture_guard_timer

    result = controller.cancel_pending_droplet_capture("unit_test")

    assert result["cancelled"] is True
    assert result["request_id"] == request_id
    assert result["capture_context"] == "unit_cancel"
    assert result["recovery_result"]["ok"] is True
    assert machine.recover_calls
    assert "unit_test" in machine.recover_calls[-1]
    assert timer.active is False
    assert controller.pending_capture_callback is None
    assert controller.pending_capture_context is None
    assert controller.pending_capture_active is False
    assert controller.capture_coordinator.state is CaptureCoordinatorState.IDLE
    assert controller.capture_coordinator.pending_active is False
    assert controller.capture_coordinator.last_result.status is CaptureStatus.CANCELLED
    assert controller.capture_coordinator.last_result.retryable is False
    assert controller.capture_coordinator.last_result.recoverable is False
    assert controller.capture_coordinator.last_result.metadata["capture_context"] == "unit_cancel"
    assert controller.capture_coordinator.last_result.metadata["state_before"]["camera_started"] is True
    assert controller.capture_coordinator.last_result.metadata["state_after"]["worker_active"] is False
    assert controller.capture_coordinator.last_result.metadata["recovery_result"]["ok"] is True
    callback.assert_called_once_with(None)
    assert getattr(callback, "_capture_rejection_reason") == "capture_cancelled"
    assert getattr(callback, "_capture_cancel_reason") == "unit_test"
    controller.model.calibration_manager.captureFailed.emit.assert_called_once()

    late_frame = np.full((4, 5, 3), 55, dtype=np.uint8)
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": request_id,
            "cap_id": 999,
            "frame": late_frame,
            "capture_info": {"cap_id": 999, "reason": "threshold"},
        }
    )

    assert camera_model.update_calls == []
    assert controller.capture_coordinator.last_result.status is CaptureStatus.STALE_IGNORED
    assert controller.capture_coordinator.last_result.metadata["state"]["camera_started"] is True


def test_controller_cancel_pending_capture_clears_waiter_when_recovery_fails():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()
    machine.recover_return = {"ok": False, "ready_for_retry": False, "reason": "backend_still_busy"}

    assert controller.capture_droplet_image(callback=callback, capture_context="unit_cancel_fail") is True
    request_id = controller.pending_capture_request_id

    result = controller.cancel_pending_droplet_capture("unit_test_failure")

    assert result["cancelled"] is True
    assert result["request_id"] == request_id
    assert result["recovery_result"]["ok"] is False
    assert result["recovery_result"]["reason"] == "backend_still_busy"
    assert controller.pending_capture_active is False
    assert controller.pending_capture_callback is None
    assert controller.capture_coordinator.pending_active is False
    assert controller.capture_coordinator.last_result.status is CaptureStatus.CANCELLED
    assert controller.capture_coordinator.last_result.metadata["recovery_result"]["ok"] is False
    callback.assert_called_once_with(None)
    controller.model.calibration_manager.captureFailed.emit.assert_called_once()


def test_controller_cancel_pending_capture_is_idempotent_without_pending_capture():
    controller, machine, _camera_model = _make_controller()

    result = controller.cancel_pending_droplet_capture("nothing_to_cancel")

    assert result["cancelled"] is False
    assert result["reason"] == "no_pending_capture"
    assert machine.recover_calls == []
    controller.model.calibration_manager.captureFailed.emit.assert_not_called()


def test_controller_stop_calibration_cancels_pending_capture_before_manager_stop():
    controller, _machine, _camera_model = _make_controller()
    callback = Mock()
    stop_observations = []

    def _stop():
        stop_observations.append(controller.pending_capture_active)

    controller.model.calibration_manager.stop = Mock(side_effect=_stop)

    assert controller.capture_droplet_image(callback=callback) is True

    controller.stop_calibration()

    assert stop_observations == [False]
    callback.assert_called_once_with(None)
    controller.model.calibration_manager.stop.assert_called_once_with()
    controller.model.calibration_manager.captureFailed.emit.assert_called_once()


def test_droplet_imager_close_defers_while_capture_or_calibration_is_active():
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    event = _CloseEvent()
    cancel_pending = Mock()
    stop_calibration = Mock()
    camera_timer = SimpleNamespace(stop=Mock())
    manager = SimpleNamespace(activeCalibration=object(), calibration_queue=[])
    pending_values = []

    def _set_capture_request_pending(pending):
        pending_values.append(bool(pending))
        dialog._capture_request_pending = bool(pending)

    dialog.model = SimpleNamespace(calibration_manager=manager)
    dialog.controller = SimpleNamespace(
        pending_capture_active=True,
        cancel_pending_droplet_capture=cancel_pending,
        stop_calibration=stop_calibration,
    )
    dialog.camera_timer = camera_timer
    dialog._capture_request_pending = True
    dialog._stream_capture_dialog_closing = False
    dialog._imager_close_after_stop_requested = False
    dialog._imager_close_after_stop_started_monotonic = None
    dialog._imager_close_retry_count = 0
    dialog._imager_force_close_requested = False
    dialog._imager_force_close_prompt_active = False
    dialog._should_confirm_close_without_applied_calibration = lambda: False
    dialog.update_stage_and_log = Mock()
    dialog._set_capture_request_pending = _set_capture_request_pending
    dialog._schedule_imager_close_retry = Mock()
    dialog._imager_close_monotonic = Mock(return_value=123.0)

    DropletImagingDialog.closeEvent(dialog, event)

    assert event.ignored is True
    assert event.accepted is False
    assert dialog._stream_capture_dialog_closing is True
    assert dialog._imager_close_after_stop_requested is True
    assert dialog._imager_close_after_stop_started_monotonic == 123.0
    assert dialog._imager_close_retry_count == 0
    camera_timer.stop.assert_called_once_with()
    cancel_pending.assert_called_once_with("imager_close", emit_capture_failed=True, recover=True)
    stop_calibration.assert_called_once_with()
    dialog.update_stage_and_log.assert_called_once()
    assert pending_values == [False]
    dialog._schedule_imager_close_retry.assert_called_once_with(100)


def test_droplet_imager_close_ignores_stale_local_pending_when_coordinator_idle():
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    event = _CloseEvent()
    manager = SimpleNamespace(activeCalibration=None, calibration_queue=[])
    controller = SimpleNamespace(
        get_droplet_capture_ui_state=Mock(
            return_value={
                "pending_active": False,
                "dirty_shutdown": False,
                "last_result_dirty_shutdown": False,
            }
        ),
        set_droplet_capture_profile=Mock(),
        set_command_dispatch_interval=Mock(),
        disable_print_profile=Mock(),
    )
    dialog.model = SimpleNamespace(calibration_manager=manager)
    dialog.controller = controller
    dialog._capture_request_pending = True
    dialog._stream_capture_dialog_closing = False
    dialog._imager_close_after_stop_requested = False
    dialog._imager_close_after_stop_started_monotonic = None
    dialog._imager_close_retry_count = 0
    dialog._imager_force_close_requested = False
    dialog._imager_force_close_prompt_active = False
    dialog._should_confirm_close_without_applied_calibration = lambda: False
    dialog._printer_head_recovery_dialog = None
    dialog._optics_session_active = False
    dialog._close_stream_capture_mass_dialog = Mock()
    dialog._reset_online_stream_debug_view = Mock()
    dialog.camera_timer = SimpleNamespace(stop=Mock())
    dialog._auto_export_refuel_performance_snapshot_on_close = Mock()
    dialog._stop_refuel_monitor = Mock()
    dialog.stop_droplet_camera = Mock()
    dialog._set_stream_capture_read_camera_enabled = Mock()

    DropletImagingDialog.closeEvent(dialog, event)

    assert event.accepted is True
    assert event.ignored is False
    assert dialog._capture_request_pending is False
    controller.set_droplet_capture_profile.assert_called_once_with("default")
    dialog.stop_droplet_camera.assert_called_once_with()


def test_droplet_imager_close_defers_on_coordinator_pending_even_when_local_idle():
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    event = _CloseEvent()
    cancel_pending = Mock()
    stop_calibration = Mock()
    camera_timer = SimpleNamespace(stop=Mock())
    manager = SimpleNamespace(activeCalibration=object(), calibration_queue=[])
    controller = SimpleNamespace(
        get_droplet_capture_ui_state=Mock(
            return_value={
                "pending_active": True,
                "pending_request_id": "request-1",
                "dirty_shutdown": False,
                "last_result_dirty_shutdown": False,
            }
        ),
        cancel_pending_droplet_capture=cancel_pending,
        stop_calibration=stop_calibration,
    )
    dialog.model = SimpleNamespace(calibration_manager=manager)
    dialog.controller = controller
    dialog.camera_timer = camera_timer
    dialog._capture_request_pending = False
    dialog._stream_capture_dialog_closing = False
    dialog._imager_close_after_stop_requested = False
    dialog._imager_close_after_stop_started_monotonic = None
    dialog._imager_close_retry_count = 0
    dialog._imager_force_close_requested = False
    dialog._imager_force_close_prompt_active = False
    dialog._should_confirm_close_without_applied_calibration = lambda: False
    dialog.update_stage_and_log = Mock()
    dialog._set_capture_request_pending = Mock(
        side_effect=lambda pending: setattr(dialog, "_capture_request_pending", bool(pending))
    )
    dialog._schedule_imager_close_retry = Mock()
    dialog._imager_close_monotonic = Mock(return_value=123.0)

    DropletImagingDialog.closeEvent(dialog, event)

    assert event.ignored is True
    assert dialog._capture_request_pending is False
    camera_timer.stop.assert_called_once_with()
    cancel_pending.assert_called_once_with("imager_close", emit_capture_failed=True, recover=True)
    stop_calibration.assert_called_once_with()
    dialog._schedule_imager_close_retry.assert_called_once_with(100)


def test_droplet_imager_deferred_close_rechecks_unapplied_prompt_and_can_be_cancelled(monkeypatch):
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    event = _CloseEvent()
    close_calls = []
    prompt_calls = []
    manager = SimpleNamespace(activeCalibration=None, calibration_queue=[])

    def _close():
        close_calls.append(True)
        DropletImagingDialog.closeEvent(dialog, event)

    monkeypatch.setattr(
        calibration_view.QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: prompt_calls.append(args) or calibration_view.QtWidgets.QMessageBox.No,
    )

    dialog.model = SimpleNamespace(calibration_manager=manager)
    dialog.controller = SimpleNamespace(pending_capture_active=False)
    dialog._capture_request_pending = False
    dialog._stream_capture_dialog_closing = True
    dialog._imager_close_after_stop_requested = True
    dialog._imager_close_after_stop_started_monotonic = 10.0
    dialog._imager_close_retry_count = 2
    dialog._imager_force_close_requested = False
    dialog._imager_force_close_prompt_active = False
    dialog._should_confirm_close_without_applied_calibration = lambda: True
    dialog._close_without_applied_calibration_message = lambda: "Apply result before closing?"
    dialog.update_stage_and_log = Mock()
    dialog.close = Mock(side_effect=_close)

    DropletImagingDialog._retry_imager_close_after_stop(dialog)

    assert close_calls == [True]
    assert prompt_calls
    assert event.ignored is True
    assert event.accepted is False
    assert dialog._imager_close_after_stop_requested is False
    assert dialog._imager_close_after_stop_started_monotonic is None
    assert dialog._imager_close_retry_count == 0
    assert dialog._stream_capture_dialog_closing is False
    dialog.update_stage_and_log.assert_called_once_with(
        "Close cancelled; calibration stop completed.",
        "orange",
    )


def test_droplet_imager_deferred_close_timeout_keep_waiting_resumes_retry():
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    dialog._capture_request_pending = True
    dialog._stream_capture_dialog_closing = True
    dialog._imager_close_after_stop_requested = True
    dialog._imager_close_after_stop_started_monotonic = 100.0
    dialog._imager_close_retry_count = 5
    dialog._imager_force_close_requested = False
    dialog._imager_force_close_prompt_active = False
    dialog.IMAGER_CLOSE_STOP_TIMEOUT_S = 10.0
    dialog._imager_close_monotonic = Mock(return_value=111.0)
    dialog._schedule_imager_close_retry = Mock()
    dialog._ask_force_close_imager_after_timeout = Mock(return_value=False)
    dialog.update_stage_and_log = Mock()
    dialog.close = Mock()

    DropletImagingDialog._retry_imager_close_after_stop(dialog)

    assert dialog._imager_close_after_stop_requested is True
    assert dialog._imager_close_after_stop_started_monotonic == 111.0
    assert dialog._imager_close_retry_count == 0
    assert dialog._stream_capture_dialog_closing is True
    assert dialog._imager_force_close_requested is False
    assert dialog._imager_force_close_prompt_active is False
    dialog._ask_force_close_imager_after_timeout.assert_called_once_with()
    dialog._schedule_imager_close_retry.assert_called_once_with(100)
    dialog.close.assert_not_called()
    dialog.update_stage_and_log.assert_called_once_with(
        "Still waiting for calibration/camera cleanup before closing.",
        "orange",
    )


def test_droplet_imager_deferred_close_timeout_force_close_requests_minimal_close():
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    dialog._capture_request_pending = True
    dialog.capturing = True
    dialog._stream_capture_dialog_closing = True
    dialog._imager_close_after_stop_requested = True
    dialog._imager_close_after_stop_started_monotonic = 100.0
    dialog._imager_close_retry_count = 5
    dialog._imager_force_close_requested = False
    dialog._imager_force_close_prompt_active = False
    dialog.IMAGER_CLOSE_STOP_TIMEOUT_S = 10.0
    dialog._imager_close_monotonic = Mock(return_value=111.0)
    dialog._ask_force_close_imager_after_timeout = Mock(return_value=True)
    dialog._schedule_imager_close_retry = Mock()
    dialog._set_capture_request_pending = Mock(side_effect=lambda pending: setattr(dialog, "_capture_request_pending", bool(pending)))
    dialog.controller = SimpleNamespace(mark_droplet_imager_force_close=Mock())
    dialog.camera_timer = SimpleNamespace(stop=Mock())
    dialog.refuel_monitor_timer = SimpleNamespace(stop=Mock())
    dialog.refuel_panel_refresh_timer = SimpleNamespace(stop=Mock())
    dialog.close = Mock()

    DropletImagingDialog._retry_imager_close_after_stop(dialog)

    assert dialog._imager_force_close_requested is True
    assert dialog._imager_close_after_stop_requested is False
    assert dialog._imager_close_after_stop_started_monotonic is None
    assert dialog._imager_close_retry_count == 0
    assert dialog.capturing is False
    dialog.controller.mark_droplet_imager_force_close.assert_called_once_with("imager_force_close")
    dialog._ask_force_close_imager_after_timeout.assert_called_once_with()
    dialog._set_capture_request_pending.assert_called_once_with(False)
    dialog.camera_timer.stop.assert_called_once_with()
    dialog.refuel_monitor_timer.stop.assert_called_once_with()
    dialog.refuel_panel_refresh_timer.stop.assert_called_once_with()
    dialog._schedule_imager_close_retry.assert_not_called()
    dialog.close.assert_called_once_with()


def test_droplet_imager_force_close_event_accepts_without_controller_cleanup():
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    event = _CloseEvent()
    controller = SimpleNamespace(
        set_droplet_capture_profile=Mock(),
        set_command_dispatch_interval=Mock(),
        disable_print_profile=Mock(),
    )
    dialog.controller = controller
    dialog._imager_force_close_requested = True
    dialog._imager_close_after_stop_requested = True
    dialog._imager_close_after_stop_started_monotonic = 100.0
    dialog._imager_close_retry_count = 3
    dialog._imager_force_close_prompt_active = False
    dialog._stream_capture_dialog_closing = True
    dialog._should_confirm_close_without_applied_calibration = Mock(side_effect=AssertionError("force close should skip unapplied prompt"))
    dialog._imager_close_blocked_by_capture_or_calibration = Mock(side_effect=AssertionError("force close should skip blocked check"))
    dialog.stop_droplet_camera = Mock()
    dialog._set_stream_capture_read_camera_enabled = Mock()
    dialog._stop_refuel_monitor = Mock()

    DropletImagingDialog.closeEvent(dialog, event)

    assert event.accepted is True
    assert event.ignored is False
    assert dialog._imager_force_close_requested is False
    assert dialog._imager_close_after_stop_requested is False
    assert dialog._imager_close_after_stop_started_monotonic is None
    assert dialog._imager_close_retry_count == 0
    assert dialog._stream_capture_dialog_closing is True
    controller.set_droplet_capture_profile.assert_not_called()
    controller.set_command_dispatch_interval.assert_not_called()
    controller.disable_print_profile.assert_not_called()
    dialog.stop_droplet_camera.assert_not_called()
    dialog._set_stream_capture_read_camera_enabled.assert_not_called()
    dialog._stop_refuel_monitor.assert_not_called()


def test_droplet_imager_force_close_prompt_warns_to_restart_app():
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)

    message = DropletImagingDialog._force_close_imager_prompt_message(dialog)

    assert "Close and reopen the app before using the droplet imager again." in message


def test_controller_overlapping_capture_resolves_waiting_callback():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()

    assert controller.capture_droplet_image() is True
    assert controller.capture_droplet_image(callback=callback) is False

    assert len(machine.capture_calls) == 1
    assert controller.pending_capture_active is True
    callback.assert_called_once_with(None)


def test_controller_capture_guard_recovers_once_and_requeues_original_callback():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()

    assert controller.capture_droplet_image(callback=callback) is True
    timer = controller.pending_capture_guard_timer
    assert timer is not None
    assert timer.active is True
    assert timer.interval_ms == 8_000
    first_request_id = controller.pending_capture_request_id

    controller._test_clock["value"] = 108.25
    timer.fire()

    assert machine.recover_calls
    assert len(machine.capture_calls) == 2
    assert controller.pending_capture_active is True
    assert controller.pending_capture_recovery_attempted is True
    assert controller.pending_capture_request_id != first_request_id
    assert controller.capture_coordinator.active_request.request_id == controller.pending_capture_request_id
    assert controller.capture_coordinator.pending_request_id == controller.pending_capture_request_id
    assert controller._capture_pending_snapshot()["recovery_attempted"] is True
    callback.assert_not_called()
    controller.model.calibration_manager.captureFailed.emit.assert_not_called()

    frame = np.full((4, 5, 3), 99, dtype=np.uint8)
    retry_request_id = controller.pending_capture_request_id
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": retry_request_id,
            "cap_id": 456,
            "frame": frame,
            "capture_info": {"cap_id": 456, "reason": "threshold"},
        }
    )

    callback.assert_called_once()
    assert callback.call_args.args[0] is frame
    assert controller.pending_capture_callback is None
    assert controller.pending_capture_context is None
    assert controller.pending_capture_active is False
    assert controller.pending_capture_started_monotonic is None
    assert controller.capture_coordinator.state is CaptureCoordinatorState.IDLE
    assert controller.capture_coordinator.pending_active is False
    assert controller.capture_coordinator.last_result.status is CaptureStatus.SUCCESS

    assert controller.capture_droplet_image() is True
    assert len(machine.capture_calls) == 3


def test_controller_second_capture_timeout_fails_cleanly_and_allows_manual_capture():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()

    assert controller.capture_droplet_image(callback=callback) is True
    controller._test_clock["value"] = 108.25
    controller.pending_capture_guard_timer.fire()

    assert controller.pending_capture_active is True
    assert controller.pending_capture_recovery_attempted is True
    callback.assert_not_called()

    controller._test_clock["value"] = 116.50
    controller.pending_capture_guard_timer.fire()

    assert len(machine.recover_calls) == 2
    callback.assert_called_once_with(None)
    controller.model.calibration_manager.captureFailed.emit.assert_called_once()
    assert controller.pending_capture_callback is None
    assert controller.pending_capture_active is False

    assert controller.capture_droplet_image() is True
    assert len(machine.capture_calls) == 3


def test_controller_timeout_without_retry_ready_fails_and_allows_manual_capture():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()
    machine.recover_return = {"ok": True, "ready_for_retry": False}

    assert controller.capture_droplet_image(callback=callback) is True
    controller._test_clock["value"] = 108.25
    controller.pending_capture_guard_timer.fire()

    assert len(machine.recover_calls) == 1
    assert len(machine.capture_calls) == 1
    callback.assert_called_once_with(None)
    controller.model.calibration_manager.captureFailed.emit.assert_called_once()
    assert controller.pending_capture_callback is None
    assert controller.pending_capture_active is False

    assert controller.capture_droplet_image() is True
    assert len(machine.capture_calls) == 2


def test_controller_late_stale_completion_cannot_satisfy_requeued_capture():
    controller, machine, camera_model = _make_controller()
    callback = Mock()

    assert controller.capture_droplet_image(callback=callback) is True
    old_request_id = controller.pending_capture_request_id
    controller._test_clock["value"] = 108.25
    controller.pending_capture_guard_timer.fire()
    new_request_id = controller.pending_capture_request_id

    old_frame = np.full((4, 5, 3), 10, dtype=np.uint8)
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": old_request_id,
            "cap_id": 111,
            "frame": old_frame,
            "capture_info": {"cap_id": 111},
        }
    )

    callback.assert_not_called()
    assert camera_model.update_calls == []
    assert controller.pending_capture_request_id == new_request_id
    assert controller.capture_coordinator.last_result.status is CaptureStatus.STALE_IGNORED
    assert controller.capture_coordinator.active_request.request_id == new_request_id
    assert controller.capture_coordinator.pending_request_id == new_request_id
    assert controller.pending_capture_active is True

    new_frame = np.full((4, 5, 3), 20, dtype=np.uint8)
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": new_request_id,
            "cap_id": 222,
            "frame": new_frame,
            "capture_info": {"cap_id": 222},
        }
    )

    callback.assert_called_once()
    assert callback.call_args.args[0] is new_frame
    assert camera_model.update_calls[-1]["capture_info"]["cap_id"] == 222


def test_controller_recovery_requeue_refreshes_expected_machine_generation():
    controller, machine, camera_model = _make_controller()
    callback = Mock()
    generations = [10, 11]
    original_capture = machine.capture_droplet_image

    def capture_with_generation(*, throughput_mode=False, capture_request_id=None, capture_context=None):
        idx = len(machine.capture_calls)
        machine.capture_state.update({"generation": generations[idx], "backend_id": "backend-A"})
        return original_capture(
            throughput_mode=throughput_mode,
            capture_request_id=capture_request_id,
            capture_context=capture_context,
        )

    machine.capture_droplet_image = capture_with_generation

    assert controller.capture_droplet_image(callback=callback, capture_context="retry_identity") is True
    first_request_id = controller.pending_capture_request_id
    assert controller.capture_coordinator.active_request.metadata["expected_generation"] == 10

    controller._test_clock["value"] = 108.25
    controller.pending_capture_guard_timer.fire()

    retry_request_id = controller.pending_capture_request_id
    assert retry_request_id != first_request_id
    assert controller.capture_coordinator.active_request.metadata["expected_generation"] == 11
    assert controller.capture_coordinator.active_request.metadata["expected_backend_id"] == "backend-A"

    stale_frame = np.full((4, 5, 3), 55, dtype=np.uint8)
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": retry_request_id,
            "generation": 10,
            "backend_id": "backend-A",
            "cap_id": 301,
            "frame": stale_frame,
            "capture_info": {"cap_id": 301},
        }
    )

    callback.assert_not_called()
    assert camera_model.update_calls == []
    assert controller.pending_capture_request_id == retry_request_id
    assert controller.capture_coordinator.last_result.status is CaptureStatus.STALE_IGNORED
    assert controller.capture_coordinator.last_result.metadata["mismatch_reason"] == "generation_mismatch"

    fresh_frame = np.full((4, 5, 3), 66, dtype=np.uint8)
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": retry_request_id,
            "generation": 11,
            "backend_id": "backend-A",
            "cap_id": 302,
            "frame": fresh_frame,
            "capture_info": {"cap_id": 302},
        }
    )

    callback.assert_called_once_with(fresh_frame)
    assert controller.pending_capture_active is False
    assert camera_model.update_calls[-1]["capture_info"]["generation"] == 11
    assert camera_model.update_calls[-1]["capture_info"]["cap_id"] == 302


def _make_optics_dialog(*, commands_idle=True, active=True):
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    dialog._optics_session_active = active
    dialog._capture_request_pending = False
    dialog.statuses = []
    dialog._set_optics_status = lambda message, color=None: dialog.statuses.append((message, color))
    dialog._set_capture_request_pending = lambda pending: setattr(dialog, "_capture_request_pending", bool(pending))
    dialog.controller = SimpleNamespace(
        check_if_all_completed=Mock(return_value=commands_idle),
        capture_droplet_image=Mock(return_value=True),
    )
    return dialog


def test_optics_capture_blocks_when_commands_are_active():
    dialog = _make_optics_dialog(commands_idle=False)

    DropletImagingDialog.capture_optics_frame(dialog)

    dialog.controller.capture_droplet_image.assert_not_called()
    assert dialog.statuses == [
        ("Wait for all machine commands to finish before capturing an optics frame.", "red")
    ]


def test_optics_capture_passes_scale_bar_context_when_idle():
    dialog = _make_optics_dialog(commands_idle=True)

    DropletImagingDialog.capture_optics_frame(dialog)

    dialog.controller.capture_droplet_image.assert_called_once_with(capture_context="optics_scale_bar")
    assert dialog._capture_request_pending is True
    assert dialog.statuses == [("Capture requested.", "green")]


def test_optics_capture_previews_without_session_and_without_save_context():
    dialog = _make_optics_dialog(commands_idle=True, active=False)

    DropletImagingDialog.capture_optics_frame(dialog)

    dialog.controller.capture_droplet_image.assert_called_once_with()
    assert dialog._capture_request_pending is True
    assert dialog.statuses == [
        ("Preview capture requested. Start a session when ready to save frames.", "green")
    ]


def test_optics_capture_uses_coordinator_pending_state_when_local_idle():
    dialog = _make_optics_dialog(commands_idle=True)
    dialog._capture_request_pending = False
    dialog.controller.get_droplet_capture_ui_state = Mock(
        return_value={
            "pending_active": True,
            "pending_request_id": "request-1",
            "dirty_shutdown": False,
            "last_result_dirty_shutdown": False,
        }
    )

    DropletImagingDialog.capture_optics_frame(dialog)

    dialog.controller.capture_droplet_image.assert_not_called()
    assert dialog._capture_request_pending is True
    assert dialog.statuses == [
        ("Capture already pending; wait for it to finish before requesting another.", "red")
    ]


def test_optics_controls_disable_capture_from_coordinator_pending_even_when_local_idle():
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    dialog._capture_request_pending = False
    dialog._optics_session_active = True
    dialog._optics_session_dir = "session"
    dialog._optics_last_analysis = {}
    dialog.controller = SimpleNamespace(
        get_droplet_capture_ui_state=Mock(
            return_value={
                "pending_active": True,
                "dirty_shutdown": False,
                "last_result_dirty_shutdown": False,
            }
        )
    )
    dialog._is_flash_fault_latched = lambda: False
    dialog._optics_current_factor = lambda: 1.0
    dialog._optics_current_source = lambda: "preset"
    dialog._optics_step_conversion_source = lambda: "preset"
    dialog.optics_current_factor_label = _WidgetState()
    dialog.optics_session_dir_label = _WidgetState()
    dialog.optics_start_session_button = _WidgetState()
    dialog.optics_capture_frame_button = _WidgetState()
    dialog.optics_reject_last_button = _WidgetState()
    dialog.optics_analyze_button = _WidgetState()
    dialog.optics_apply_button = _WidgetState()
    dialog.optics_manual_override_button = _WidgetState()

    DropletImagingDialog._refresh_optics_controls(dialog)

    assert dialog._capture_request_pending is True
    assert dialog.optics_capture_frame_button.enabled is False
    assert dialog.optics_reject_last_button.enabled is False
    assert dialog.optics_analyze_button.enabled is False


def test_droplet_capture_finished_reenables_optics_controls_when_coordinator_idle():
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    dialog._capture_request_pending = True
    dialog._optics_session_active = True
    dialog._optics_session_dir = "session"
    dialog._optics_last_analysis = {}
    dialog.controller = SimpleNamespace(
        get_droplet_capture_ui_state=Mock(
            return_value={
                "pending_active": False,
                "dirty_shutdown": False,
                "last_result_dirty_shutdown": False,
            }
        )
    )
    dialog._is_flash_fault_latched = lambda: False
    dialog._optics_current_factor = lambda: 1.0
    dialog._optics_current_source = lambda: "preset"
    dialog._optics_step_conversion_source = lambda: "preset"
    dialog._refresh_manual_control_lock_state = Mock()
    dialog.optics_current_factor_label = _WidgetState()
    dialog.optics_session_dir_label = _WidgetState()
    dialog.optics_start_session_button = _WidgetState()
    dialog.optics_capture_frame_button = _WidgetState()
    dialog.optics_reject_last_button = _WidgetState()
    dialog.optics_analyze_button = _WidgetState()
    dialog.optics_apply_button = _WidgetState()
    dialog.optics_manual_override_button = _WidgetState()

    DropletImagingDialog._on_droplet_capture_finished(dialog)

    assert dialog._capture_request_pending is False
    assert dialog.optics_capture_frame_button.enabled is True
    assert dialog.optics_reject_last_button.enabled is True
    assert dialog.optics_analyze_button.enabled is True


def test_dirty_shutdown_blocks_later_imager_capture_requests():
    dialog = _make_optics_dialog(commands_idle=True)
    dialog.controller.get_droplet_capture_ui_state = Mock(
        return_value={
            "pending_active": False,
            "dirty_shutdown": True,
            "last_result_dirty_shutdown": True,
        }
    )

    DropletImagingDialog.capture_optics_frame(dialog)

    dialog.controller.capture_droplet_image.assert_not_called()
    assert dialog.statuses == [
        (
            "Droplet imager was force closed. Close and reopen the app before using the droplet imager again.",
            "red",
        )
    ]


def test_dirty_shutdown_blocks_live_preview_capture_requests():
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    dialog.capturing = False
    dialog._capture_request_pending = False
    dialog.controller = SimpleNamespace(
        get_droplet_capture_ui_state=Mock(
            return_value={
                "pending_active": False,
                "dirty_shutdown": True,
                "last_result_dirty_shutdown": True,
            }
        ),
        capture_droplet_image=Mock(return_value=True),
    )
    dialog.update_stage_and_log = Mock()

    DropletImagingDialog.capture_image(dialog)

    dialog.controller.capture_droplet_image.assert_not_called()
    dialog.update_stage_and_log.assert_called_once_with(
        "Droplet imager was force closed. Close and reopen the app before using the droplet imager again.",
        "red",
    )


def test_optics_end_analyze_runs_scale_then_motion_and_writes_combined_payload(tmp_path, monkeypatch):
    import tools.scale_bar_conversion as scale_mod
    import tools.scale_bar_motion_conversion as motion_mod

    scale_analysis = {
        "schema_version": 1,
        "status": "ok",
        "summary": {
            "status": "ok",
            "median_um_per_pixel": 1.5,
            "mean_um_per_pixel": 1.51,
            "std_um_per_pixel": 0.01,
            "cv_pct": 0.5,
            "division_um": 10.0,
            "accepted_count": 30,
            "rejected_count": 1,
            "failed_count": 0,
            "run_directory": str(tmp_path),
        },
    }
    motion_analysis = {
        "schema_version": 1,
        "status": "ok",
        "summary": {
            "status": "ok",
            "run_directory": str(tmp_path),
            "accepted_count": 30,
            "rejected_count": 1,
            "error_count": 0,
            "repeat_position_group_count": 4,
        },
        "motion_fit": {
            "status": "ok",
            "fit_count": 29,
            "intercept": [10.0, 20.0],
            "matrix": [[2.0, 0.0], [0.0, 4.0]],
            "inverse_matrix": [[0.5, 0.0], [0.0, 0.25]],
            "determinant": 8.0,
            "rmse_2d_px": 5.0,
            "p95_2d_residual_px": 9.0,
            "max_2d_residual_px": 10.0,
        },
    }
    quality = {"apply_ready": True, "failed_criteria": [], "fit_count": 29}
    scale_call = Mock(return_value=scale_analysis)
    motion_call = Mock(return_value=motion_analysis)
    quality_call = Mock(return_value=quality)

    def fake_debug(payload, output_dir, **kwargs):
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        (output / "index.html").write_text("debug", encoding="utf-8")
        return {"output_dir": str(output), "summary_only": kwargs.get("summary_only")}

    monkeypatch.setattr(scale_mod, "analyze_scale_bar_directory", scale_call)
    monkeypatch.setattr(motion_mod, "analyze_scale_bar_motion_directory", motion_call)
    monkeypatch.setattr(motion_mod, "summarize_motion_fit_quality", quality_call)
    monkeypatch.setattr(motion_mod, "write_debug_outputs", fake_debug)

    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    dialog._optics_session_active = True
    dialog._optics_session_dir = str(tmp_path)
    dialog._optics_rejected_filenames = ["scale_bar_000004.png"]
    dialog._optics_last_analysis = None
    dialog.optics_division_um_spin = SimpleNamespace(value=Mock(return_value=10.0))
    dialog.optics_results_text = SimpleNamespace(setPlainText=Mock())
    dialog.statuses = []
    dialog._set_optics_status = lambda message, color=None: dialog.statuses.append((message, color))
    dialog._refresh_optics_controls = Mock()
    dialog._optics_camera_model = Mock(return_value=SimpleNamespace(stop_saving=Mock()))

    DropletImagingDialog.end_and_analyze_optics_session(dialog)

    scale_call.assert_called_once_with(
        str(tmp_path),
        division_um=10.0,
        rejected_filenames={"scale_bar_000004.png"},
    )
    motion_call.assert_called_once_with(
        str(tmp_path),
        rejected_filenames={"scale_bar_000004.png"},
    )
    assert dialog._optics_last_analysis["summary"]["apply_ready"] is True
    assert "scale_bar_analysis" in dialog._optics_last_analysis
    assert "motion_analysis" in dialog._optics_last_analysis
    assert (tmp_path / "scale_bar_analysis.json").exists()
    assert (tmp_path / "scale_bar_motion_analysis.json").exists()
    combined = json.loads((tmp_path / "optics_calibration_analysis.json").read_text(encoding="utf-8"))
    assert combined["summary"]["motion_debug_index_path"].endswith("motion_fit_summary\\index.html") or combined["summary"]["motion_debug_index_path"].endswith("motion_fit_summary/index.html")


class _FakeButton:
    def __init__(self):
        self.enabled = None
        self.tooltip = ""

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setToolTip(self, text):
        self.tooltip = str(text)


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = str(text)


def test_optics_apply_button_requires_combined_quality_gate():
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    dialog._optics_session_active = False
    dialog._capture_request_pending = False
    dialog._optics_last_analysis = {
        "summary": {
            "status": "ok",
            "apply_ready": False,
            "failed_criteria": ["rmse_2d>15"],
        }
    }
    dialog._is_flash_fault_latched = Mock(return_value=False)
    dialog._optics_current_factor = Mock(return_value=1.5)
    dialog._optics_current_source = Mock(return_value="unit")
    dialog._optics_step_conversion_source = Mock(return_value="preset")
    dialog.optics_current_factor_label = _FakeLabel()
    dialog.optics_session_dir_label = _FakeLabel()
    dialog.optics_start_session_button = _FakeButton()
    dialog.optics_capture_frame_button = _FakeButton()
    dialog.optics_reject_last_button = _FakeButton()
    dialog.optics_analyze_button = _FakeButton()
    dialog.optics_apply_button = _FakeButton()
    dialog.optics_manual_override_button = _FakeButton()

    DropletImagingDialog._refresh_optics_controls(dialog)

    assert dialog.optics_apply_button.enabled is False
    assert "rmse_2d>15" in dialog.optics_apply_button.tooltip
