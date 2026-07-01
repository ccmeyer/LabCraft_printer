from __future__ import annotations

import json
from types import SimpleNamespace

from Controller import Controller, DropletCapturePerformanceDiagnostics


def test_droplet_capture_perf_disabled_recording_is_noop():
    diagnostics = DropletCapturePerformanceDiagnostics(max_events=3)

    assert diagnostics.record("ui_trigger_received", {"request_id": "a"}) is None
    assert diagnostics.build_snapshot()["event_count"] == 0


def test_droplet_capture_perf_default_buffer_is_large_enough_for_calibration_runs():
    diagnostics = DropletCapturePerformanceDiagnostics()

    assert diagnostics.max_events == 20000


def test_droplet_capture_perf_enabled_events_are_bounded_and_json_safe():
    diagnostics = DropletCapturePerformanceDiagnostics(max_events=2)
    diagnostics.set_enabled(True)

    diagnostics.record("ui_trigger_received", {"request_id": "old"})
    diagnostics.record("ui_request_returned", {"request_id": "new", "accepted": True})
    diagnostics.record("controller_completion_received", {"request_id": "new", "status": "success"})
    snapshot = diagnostics.build_snapshot(reason="unit_test")

    assert snapshot["kind"] == "droplet_capture_performance_snapshot"
    assert snapshot["schema_version"] == 3
    assert snapshot["reason"] == "unit_test"
    assert snapshot["event_count"] == 2
    assert snapshot["event_counts"]["controller_completion_received"] == 1
    assert [row["request_id"] for row in snapshot["event_log_tail"]] == ["new", "new"]
    json.dumps(snapshot)


def test_droplet_capture_perf_snapshot_summarizes_timings():
    diagnostics = DropletCapturePerformanceDiagnostics(max_events=10)
    diagnostics.set_enabled(True)

    diagnostics.record("ui_trigger_received", {"ui_sequence": 1})
    diagnostics.record("ui_request_returned", {"ui_sequence": 1, "request_id": "r1", "accepted": True})
    diagnostics.record(
        "controller_completion_received",
        {
            "request_id": "r1",
            "status": "success",
            "cap_id": 12,
            "generation": 44,
            "backend_id": 1,
            "queue_to_worker_start_ms": 1.5,
            "worker_duration_ms": 8.0,
            "worker_complete_to_controller_ms": 0.25,
        },
    )
    diagnostics.record("controller_pending_cleared", {"request_id": "r1"})
    diagnostics.record("ui_pending_cleared", {"request_id": "r1"})

    snapshot = diagnostics.build_snapshot()

    request_summary = snapshot["request_summaries"][0]
    assert request_summary["request_id"] == "r1"
    assert request_summary["status"] == "success"
    assert request_summary["queue_to_worker_start_ms"] == 1.5
    assert request_summary["worker_duration_ms"] == 8.0
    assert request_summary["worker_complete_to_controller_ms"] == 0.25
    assert request_summary["controller_completion_to_pending_clear_ms"] is not None
    assert snapshot["ui_sequence_summaries"][0]["accepted"] is True


def test_droplet_capture_perf_snapshot_summarizes_calibration_capture_and_settings():
    diagnostics = DropletCapturePerformanceDiagnostics(max_events=20)
    diagnostics.set_enabled(True)

    diagnostics.record(
        "calibration_process_started",
        {
            "calibration_run_id": "run-1",
            "calibration_run_index": 0,
            "calibration_process": "NozzlePositionCalibrationProcess",
            "calibration_phase": "nozzle_position",
        },
    )
    diagnostics.record(
        "calibration_capture_attempt_started",
        {
            "capture_diag_id": "cap-diag-1",
            "calibration_run_id": "run-1",
            "calibration_run_index": 0,
            "calibration_process": "NozzlePositionCalibrationProcess",
            "calibration_phase": "nozzle_position",
            "stage_text": "Capturing background image",
            "set_attr": "background_image",
            "capture_role": "background",
            "attempt": 1,
            "attempts_total": 3,
        },
    )
    diagnostics.record(
        "calibration_capture_callback_received",
        {
            "capture_diag_id": "cap-diag-1",
            "request_id": "request-1",
            "capture_status": "success",
            "frame_present": True,
        },
    )
    diagnostics.record(
        "calibration_capture_result",
        {
            "capture_diag_id": "cap-diag-1",
            "request_id": "request-1",
            "status": "success",
            "capture_status": "success",
        },
    )
    diagnostics.record(
        "calibration_settings_requested",
        {
            "settings_request_id": "settings-1",
            "calibration_run_id": "run-1",
            "calibration_process": "NozzlePositionCalibrationProcess",
            "calibration_phase": "nozzle_position",
            "context": "background",
            "requested_settings": {"flash_delay": 6100},
        },
    )
    diagnostics.record(
        "calibration_settings_bound",
        {
            "settings_request_id": "settings-1",
            "commands": [{"command_number": 44, "command_type": "SET_DELAY_F"}],
            "completion_command_number": 44,
        },
    )
    diagnostics.record("calibration_settings_completed", {"settings_request_id": "settings-1"})
    diagnostics.record(
        "calibration_process_completed",
        {
            "calibration_run_id": "run-1",
            "calibration_run_index": 0,
            "calibration_process": "NozzlePositionCalibrationProcess",
            "calibration_phase": "nozzle_position",
        },
    )

    snapshot = diagnostics.build_snapshot()

    process_summary = snapshot["calibration_process_summaries"][0]
    assert process_summary["calibration_process"] == "NozzlePositionCalibrationProcess"
    assert process_summary["terminal_event_kind"] == "calibration_process_completed"

    capture_summary = snapshot["calibration_capture_summaries"][0]
    assert capture_summary["capture_diag_id"] == "cap-diag-1"
    assert capture_summary["request_id"] == "request-1"
    assert capture_summary["calibration_run_index"] == 0
    assert capture_summary["set_attr"] == "background_image"
    assert capture_summary["status"] == "success"

    settings_summary = snapshot["settings_request_summaries"][0]
    assert settings_summary["settings_request_id"] == "settings-1"
    assert settings_summary["command_count"] == 1
    assert settings_summary["completion_command_number"] == 44


def test_droplet_capture_perf_snapshot_recovers_nested_capture_context():
    diagnostics = DropletCapturePerformanceDiagnostics(max_events=20)
    diagnostics.set_enabled(True)
    capture_context = {
        "kind": "calibration_capture",
        "capture_diag_id": "cap-nested",
        "calibration_run_id": "run-nested",
        "calibration_run_index": 0,
        "calibration_process": "NozzleFocusCalibrationProcess",
        "calibration_phase": "focus",
        "stage_text": "Capturing focus frame",
        "set_attr": "droplet_image",
        "capture_role": "focus_frame",
        "attempt": 2,
        "attempts_total": 7,
    }

    diagnostics.record(
        "controller_request_received",
        {
            "request_id": "request-nested",
            "capture_context": capture_context,
        },
    )
    diagnostics.record("camera_phase", {"request_id": "request-nested", "phase": "trigger_high"})
    diagnostics.record(
        "camera_phase",
        {
            "request_id": "request-nested",
            "phase": "edge_wait_done",
            "fired": True,
            "elapsed_ms": 155.5,
        },
    )
    diagnostics.record(
        "camera_phase",
        {
            "request_id": "request-nested",
            "phase": "retry_attempt_result",
            "reason": "threshold",
            "mean": 200.0,
            "threshold": 29.0,
        },
    )
    diagnostics.record(
        "controller_completion_received",
        {
            "request_id": "request-nested",
            "status": "success",
            "worker_duration_ms": 40.0,
            "queue_to_worker_start_ms": 1.0,
            "worker_complete_to_controller_ms": 0.5,
        },
    )

    snapshot = diagnostics.build_snapshot()

    capture_summary = snapshot["calibration_capture_summaries"][0]
    assert capture_summary["capture_diag_id"] == "cap-nested"
    assert capture_summary["request_id"] == "request-nested"
    assert capture_summary["calibration_run_index"] == 0
    assert capture_summary["calibration_process"] == "NozzleFocusCalibrationProcess"
    assert capture_summary["stage_text"] == "Capturing focus frame"
    assert capture_summary["capture_role"] == "focus_frame"
    assert capture_summary["attempts_total"] == 7
    assert capture_summary["status"] == "success"
    assert capture_summary["worker_duration_ms"] == 40.0
    assert capture_summary["trigger_count"] == 1
    assert capture_summary["edge_wait_done_count"] == 1
    assert capture_summary["edge_timeout_count"] == 0
    assert capture_summary["delayed_ack_count"] == 1
    assert capture_summary["retry_reasons"] == ["threshold"]


def test_droplet_capture_perf_snapshot_parses_stringified_capture_context_only_on_export():
    diagnostics = DropletCapturePerformanceDiagnostics(max_events=10)
    diagnostics.set_enabled(True)
    capture_context = {
        "capture_diag_id": "cap-string",
        "calibration_process": "TrajectoryCalibrationProcess",
        "calibration_phase": "trajectory",
        "capture_role": "trajectory_frame",
    }

    diagnostics.record(
        "controller_completion_received",
        {
            "request_id": "request-string",
            "capture_context": str(capture_context),
            "status": "success",
        },
    )

    assert diagnostics.events[0]["capture_context"] == str(capture_context)

    snapshot = diagnostics.build_snapshot()
    capture_summary = snapshot["calibration_capture_summaries"][0]
    assert capture_summary["capture_diag_id"] == "cap-string"
    assert capture_summary["request_id"] == "request-string"
    assert capture_summary["calibration_process"] == "TrajectoryCalibrationProcess"
    assert capture_summary["capture_role"] == "trajectory_frame"


def test_controller_writes_droplet_capture_perf_snapshot(tmp_path):
    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(experiment_model=SimpleNamespace(experiment_dir_path=str(tmp_path)))
    controller.set_droplet_capture_performance_diagnostics_enabled(True)
    controller.record_droplet_capture_performance_marker("ui_trigger_received", {"ui_sequence": 1})

    path = controller.write_droplet_capture_performance_snapshot(reason="unit_test")

    assert path.parent == tmp_path / "calibration_recordings" / "droplet_capture_performance"
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["reason"] == "unit_test"
    assert payload["event_count"] == 3
    assert {
        row["event_kind"] for row in payload["event_log_tail"]
    } == {
        "diagnostics_enabled",
        "calibration_diagnostics_bridge_status",
        "ui_trigger_received",
    }


class _SignalStub:
    def __init__(self):
        self._slots = []

    def connect(self, slot, *_args):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


def test_controller_bridges_calibration_performance_markers():
    manager_enabled = {"value": False}

    def _set_manager_enabled(enabled):
        manager_enabled["value"] = bool(enabled)

    manager = SimpleNamespace(
        capturePerformanceDiagnosticEvent=_SignalStub(),
        set_capture_performance_diagnostics_enabled=_set_manager_enabled,
        is_capture_performance_diagnostics_enabled=lambda: manager_enabled["value"],
    )
    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(calibration_manager=manager)
    controller._connect_calibration_capture_performance_diagnostics()

    controller.set_droplet_capture_performance_diagnostics_enabled(True)
    controller._connect_calibration_capture_performance_diagnostics()
    manager.capturePerformanceDiagnosticEvent.emit(
        "calibration_stage_changed",
        {"calibration_process": "NozzlePositionCalibrationProcess", "stage_text": "Capturing"},
    )

    snapshot = controller.build_droplet_capture_performance_snapshot()
    assert snapshot["event_count"] == 3
    assert snapshot["event_log_tail"][0]["event_kind"] == "diagnostics_enabled"
    assert snapshot["event_log_tail"][0]["max_events"] == 20000
    assert snapshot["event_log_tail"][0]["bridge_connected"] is True
    assert snapshot["event_log_tail"][0]["calibration_manager_enabled"] is True
    assert snapshot["event_log_tail"][1]["event_kind"] == "calibration_diagnostics_bridge_status"
    assert snapshot["event_log_tail"][2]["event_kind"] == "calibration_stage_changed"
    assert snapshot["event_log_tail"][2]["stage_text"] == "Capturing"


def test_controller_handle_capture_request_passes_calibration_context():
    controller = Controller.__new__(Controller)
    captured = {}
    controller.capture_droplet_image = lambda **kwargs: captured.update(kwargs) or True

    def callback(_frame):
        pass

    callback._capture_diag_id = "diag-1"
    callback._capture_calibration_run_id = "run-1"
    callback._capture_calibration_run_index = 4
    callback._capture_calibration_process = "NozzlePositionCalibrationProcess"
    callback._capture_calibration_phase = "nozzle_position"
    callback._capture_stage_text = "Capturing background image"
    callback._capture_set_attr = "background_image"
    callback._capture_role = "background"
    callback._capture_attempt = 1
    callback._capture_attempts_total = 3

    controller.handle_capture_request(callback)

    assert captured["callback"] is callback
    context = captured["capture_context"]
    assert context["kind"] == "calibration_capture"
    assert context["capture_diag_id"] == "diag-1"
    assert context["calibration_run_id"] == "run-1"
    assert context["calibration_run_index"] == 4
    assert context["calibration_process"] == "NozzlePositionCalibrationProcess"
    assert context["set_attr"] == "background_image"
