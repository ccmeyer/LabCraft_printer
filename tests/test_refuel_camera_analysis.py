import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

import CalibrationClasses.Model as CalibrationModelModule
from CalibrationClasses.Model import ImageAnalysisThread, RefuelCameraModel


def _build_analysis_view(
    *,
    head_rect=(200, 80, 120, 180),
    left_offset=40,
    channel_width=20,
    meniscus_row=None,
    channel_intensity=80,
    top_intensity=40,
    bottom_intensity=220,
    reference_intensity=220,
):
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    x, y, w, h = head_rect
    image[y : y + h, x : x + w] = 160

    x0 = x + left_offset
    channel = image[y : y + h, x0 : x0 + channel_width]
    channel[:] = channel_intensity
    if meniscus_row is not None:
        channel[:meniscus_row] = top_intensity
        channel[meniscus_row:] = bottom_intensity

    ref_x0 = x0 + channel_width + 5
    image[y : y + h, ref_x0 : ref_x0 + channel_width] = reference_intensity
    return image, head_rect


def _thread_input_from_analysis_view(image):
    return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)


def _draw_split_head_image(parts, *, separator_row=None, led_start_row=None):
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    for rect in parts:
        x, y, w, h = rect
        image[y : y + h, x : x + w] = 160
    if separator_row is not None:
        for rect in parts:
            x, y, w, _h = rect
            image[y + separator_row : y + separator_row + 3, x : x + w] = 20
    if led_start_row is not None:
        for rect in parts:
            x, y, w, h = rect
            image[y + led_start_row : y + h, x : x + w] = 220
    return image


def _draw_channel_wall_profile_image(
    *,
    head_rect=(200, 80, 220, 180),
    wall_left_rel=48,
    wall_spacing=20,
    edge_peak_rel=None,
    reservoir_peak_rel=None,
):
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    x, y, w, h = head_rect
    image[y : y + h, x : x + w] = 170

    if edge_peak_rel is not None:
        image[y : y + h, x + edge_peak_rel : x + edge_peak_rel + 3] = 30

    left = x + wall_left_rel
    right = left + wall_spacing
    image[y : y + h, left : left + 3] = 35
    image[y : y + h, right : right + 3] = 35
    image[y : y + h, left + 3 : right] = 215

    if reservoir_peak_rel is not None:
        reservoir_left = x + reservoir_peak_rel
        reservoir_right = reservoir_left + wall_spacing
        image[y : y + h, reservoir_left : reservoir_left + 3] = 5
        image[y : y + h, reservoir_right : reservoir_right + 3] = 5

    return image


def _sample_context(*, ts="2026-03-21T10:00:00Z", mono=100.0, level=100.0):
    return {
        "timestamp_utc": ts,
        "monotonic_s": mono,
        "print_pressure": 1.2,
        "refuel_pressure": 0.9,
        "print_pulse_width": 1400,
        "refuel_pulse_width": 900,
        "location": "camera",
        "level_hint": level,
    }


def _selection_thread():
    return ImageAnalysisThread(
        np.zeros((4, 4, 3), dtype=np.uint8),
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
        capture_debug=True,
    )


def _owner_model(tmp_path, *, record_mode=True):
    calibration_manager = SimpleNamespace(
        get_record_mode_enabled=lambda: record_mode,
        _build_recorder_meta=lambda: {"test_meta": True},
    )
    experiment_model = SimpleNamespace(experiment_dir_path=str(tmp_path))
    return SimpleNamespace(
        calibration_manager=calibration_manager,
        experiment_model=experiment_model,
    )


def test_refuel_camera_model_tracking_toggle_emits_update_signal():
    model = RefuelCameraModel()
    calls = []
    model.update_level_ui_signal.connect(lambda: calls.append(True))

    assert model.is_refuel_tracking_enabled() is False
    assert model.set_refuel_tracking_enabled(True) is True
    assert model.is_refuel_tracking_enabled() is True
    assert calls == [True]

    assert model.set_refuel_tracking_enabled(True) is False
    assert calls == [True]

    assert model.set_refuel_tracking_enabled(False) is True
    assert model.is_refuel_tracking_enabled() is False
    assert calls == [True, True]


def test_refuel_camera_model_initializes_detector_defaults():
    model = RefuelCameraModel()

    assert model.offset == 40
    assert model.width == 20
    assert model.threshold == 60
    assert model.prominence == 4
    assert model.empty_cutoff == 0.25
    assert model.bottom_guard_px == 2
    assert model._seed_analysis_parameters() == {
        "offset": 40,
        "width": 20,
        "threshold": 60,
        "prominence": 4,
        "empty_cutoff": 0.25,
        "bottom_guard_px": 2,
    }


def test_refuel_camera_model_monitor_state_and_counters_emit_update_signal():
    model = RefuelCameraModel()
    calls = []
    model.update_level_ui_signal.connect(lambda: calls.append(True))

    assert model.set_refuel_monitor_state("starting", "Starting refuel camera") is True
    model.record_refuel_monitor_attempt()
    model.record_refuel_monitor_success()
    model.record_refuel_monitor_skip("analysis_in_progress", message="Waiting for refuel analysis")
    model.record_refuel_monitor_failure("Camera did not return a frame.")
    assert model.set_refuel_diagnostic_capture_active(True) is True

    status = model.get_refuel_monitor_status()
    assert status["state"] == "unavailable"
    assert status["message"] == "Camera did not return a frame."
    assert status["attempted_captures"] == 1
    assert status["successful_captures"] == 1
    assert status["skipped_captures"] == 1
    assert status["failed_captures"] == 1
    assert status["consecutive_failures"] == 1
    assert status["diagnostic_capture_active"] is True
    assert len(calls) >= 6


def test_refuel_camera_model_tracking_toggle_does_not_clear_samples_or_monitor_counters():
    model = RefuelCameraModel()
    model.update_ui_with_analysis(None, None, 33.0, 9)
    model.record_refuel_monitor_success()

    assert model.set_refuel_tracking_enabled(True) is True
    assert model.set_refuel_tracking_enabled(False) is True

    assert len(model.get_sample_trace()) == 1
    assert model.get_sample_trace()[0]["level_px"] == 33.0
    assert model.get_refuel_monitor_status()["successful_captures"] == 1


def test_refuel_camera_model_ejection_counter_records_resets_and_caps_log():
    model = RefuelCameraModel()

    assert model.record_refuel_ejection_event(3, source="ignored") is None
    model.set_refuel_tracking_enabled(True)
    model.record_refuel_ejection_event(
        3,
        source="capture",
        event_kind="capture_completed",
        count_kind="observed",
        payload={"nested": np.int64(4)},
    )
    model.record_refuel_ejection_event(
        5,
        source="print_command",
        event_kind="print_queued",
        count_kind="commanded",
    )

    counter = model.get_refuel_ejection_counter()
    assert counter["observed_ejection_count"] == 3
    assert counter["commanded_ejection_count"] == 5
    assert counter["event_count"] == 2
    assert counter["latest_event"]["count_kind"] == "commanded"
    assert model.get_refuel_ejection_events()[0]["nested"] == 4
    json.dumps(model.get_refuel_ejection_events()[0])

    for _idx in range(305):
        model.record_refuel_ejection_event(1, source="loop", count_kind="observed")
    events = model.get_refuel_ejection_events()
    assert len(events) == 300
    assert events[0]["event_index"] == 8

    model.set_refuel_tracking_enabled(False)
    model.set_refuel_tracking_enabled(True)
    counter = model.get_refuel_ejection_counter()
    assert counter["observed_ejection_count"] == 0
    assert counter["commanded_ejection_count"] == 0
    assert counter["event_count"] == 0


def test_refuel_camera_model_timing_records_are_json_safe_and_rolling_capped():
    model = RefuelCameraModel()
    calls = []
    model.update_level_ui_signal.connect(lambda: calls.append(True))

    for idx in range(105):
        model.record_refuel_monitor_timing(
            {
                "tick_index": idx + 1,
                "event_kind": "sample_result",
                "capture_duration_ms": np.float64(1.5),
                "detector_runtime_ms": float("nan"),
                "total_latency_ms": 4.0,
                "extra": {"nested": np.int64(3)},
            }
        )

    log = model.get_refuel_monitor_timing_log()
    assert len(log) == 100
    assert log[0]["tick_index"] == 6
    assert log[-1]["tick_index"] == 105
    assert log[-1]["capture_duration_ms"] == 1.5
    assert log[-1]["detector_runtime_ms"] is None
    assert log[-1]["extra"]["nested"] == 3
    json.dumps(log[-1])
    assert calls


def test_refuel_camera_model_timing_summary_and_samples_are_independent():
    model = RefuelCameraModel()
    model.update_ui_with_analysis(None, None, 33.0, 9)
    model.record_refuel_monitor_success()
    model.record_refuel_monitor_timing({"tick_index": 1, "event_kind": "skip", "skip_reason": "analysis_in_progress"})
    model.record_refuel_monitor_timing(
        {
            "tick_index": 2,
            "event_kind": "sample_result",
            "capture_duration_ms": 3.0,
            "detector_runtime_ms": 5.0,
            "total_latency_ms": 12.0,
        }
    )

    summary = model.get_refuel_monitor_timing_summary()
    assert summary["record_count"] == 2
    assert summary["sample_result_count"] == 1
    assert summary["skip_count"] == 1
    assert summary["mean_capture_duration_ms"] == 3.0
    assert summary["mean_detector_runtime_ms"] == 5.0
    assert summary["mean_total_latency_ms"] == 12.0
    assert len(model.get_sample_trace()) == 1
    assert model.get_refuel_monitor_status()["successful_captures"] == 1


def test_refuel_camera_model_calibration_performance_stopwatch_records_elapsed():
    model = RefuelCameraModel()

    context = model.record_refuel_calibration_performance_marker(
        "stage_changed",
        {
            "source": "calibrationStageChanged",
            "process_name": "DropletCalibrationProcess",
            "phase_name": "droplet_search",
            "stage_message": "Starting",
        },
    )
    summary = model.get_refuel_calibration_performance_summary()
    assert summary["active"]["process_name"] == "DropletCalibrationProcess"
    assert summary["event_count"] == 2

    completed = model.complete_refuel_calibration_performance_observation(
        "completed",
        {"event_kind": "calibration_completed"},
    )

    assert completed["outcome"] == "completed"
    assert completed["elapsed_s"] >= 0.0
    summary = model.get_refuel_calibration_performance_summary()
    assert summary["active"] is None
    assert summary["last"]["outcome"] == "completed"
    events = model.get_refuel_calibration_performance_events()
    assert [row["event_kind"] for row in events] == [
        "calibration_performance_started",
        "stage_changed",
        "calibration_completed",
    ]
    json.dumps(events[-1])


def test_refuel_camera_model_timing_summary_includes_max_and_p95():
    model = RefuelCameraModel()
    for value in (10.0, 20.0, 30.0, 40.0):
        model.record_refuel_monitor_timing(
            {
                "tick_index": int(value),
                "event_kind": "sample_result",
                "capture_duration_ms": value,
                "detector_runtime_ms": value / 2.0,
                "total_latency_ms": value * 2.0,
            }
        )

    summary = model.get_refuel_monitor_timing_summary()

    assert summary["mean_capture_duration_ms"] == 25.0
    assert summary["max_capture_duration_ms"] == 40.0
    assert summary["p95_capture_duration_ms"] == 38.5
    assert summary["max_detector_runtime_ms"] == 20.0
    assert summary["p95_total_latency_ms"] == 77.0


def test_refuel_camera_model_build_performance_snapshot_is_json_safe_and_caps_samples():
    model = RefuelCameraModel()
    model.set_refuel_tracking_enabled(True)
    model.record_refuel_monitor_timing(
        {
            "tick_index": 1,
            "event_kind": "sample_result",
            "capture_duration_ms": np.float64(3.0),
            "detector_runtime_ms": 4.0,
            "total_latency_ms": 5.0,
        }
    )
    model.record_refuel_ejection_event(2, source="capture", count_kind="observed")
    model.sample_trace = [{"sample_index": idx, "level_px": np.float64(idx)} for idx in range(1005)]

    snapshot = model.build_refuel_performance_snapshot(reason="unit_test")

    assert snapshot["kind"] == "refuel_monitor_performance_snapshot"
    assert snapshot["reason"] == "unit_test"
    assert snapshot["tracking_enabled"] is True
    assert snapshot["calibration_performance"]["event_count"] == 0
    assert snapshot["timing_summary"]["max_capture_duration_ms"] == 3.0
    assert snapshot["ejection_counter"]["observed_ejection_count"] == 2
    assert snapshot["sample_count"] == 1005
    assert snapshot["exported_sample_count"] == 1000
    assert snapshot["sample_trace_tail"][0]["sample_index"] == 5
    assert len(model.get_sample_trace()) == 1005
    json.dumps(snapshot)


def test_refuel_camera_model_write_performance_snapshot_uses_experiment_dir(tmp_path):
    owner = _owner_model(tmp_path)
    model = RefuelCameraModel(owner_model=owner)
    model.record_refuel_monitor_timing(
        {
            "tick_index": 1,
            "event_kind": "failure",
            "failure_message": "camera busy",
            "total_latency_ms": 9.0,
        }
    )

    path = Path(model.write_refuel_performance_snapshot(reason="manual_export"))

    assert path.parent == tmp_path / "calibration_recordings" / "refuel_monitor_performance"
    assert path.name.startswith("refuel_monitor_performance_")
    assert model.last_refuel_performance_snapshot_path == str(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["reason"] == "manual_export"
    assert payload["timing_summary"]["failure_count"] == 1


def test_refuel_camera_model_empty_performance_snapshot_is_valid():
    model = RefuelCameraModel()

    snapshot = model.build_refuel_performance_snapshot()

    assert snapshot["timing_summary"]["record_count"] == 0
    assert snapshot["timing_log"] == []
    assert snapshot["process_markers"] == []
    assert snapshot["calibration_performance"]["active"] is None
    assert snapshot["calibration_performance"]["last"] is None
    assert snapshot["calibration_performance_events"] == []
    assert snapshot["advisory_log"] == []
    assert snapshot["ejection_events"] == []
    assert snapshot["sample_count"] == 0
    json.dumps(snapshot)


def test_refuel_camera_model_timing_recorder_append_only_when_run_active():
    model = RefuelCameraModel()
    recorder = SimpleNamespace(append_analysis=Mock(return_value={"ok": True}))
    model._process_recorder = recorder

    model.record_refuel_monitor_timing({"tick_index": 1, "event_kind": "skip"})
    recorder.append_analysis.assert_not_called()

    model._recorder_run_dir = Path("run")
    model.record_refuel_monitor_timing({"tick_index": 2, "event_kind": "sample_result"})
    recorder.append_analysis.assert_called_once()
    payload = recorder.append_analysis.call_args.args[0]
    assert payload["kind"] == "refuel_monitor_timing"
    assert payload["tick_index"] == 2


def test_refuel_camera_model_process_monitor_toggle_defaults_off_and_emits():
    model = RefuelCameraModel()
    calls = []
    model.update_level_ui_signal.connect(lambda: calls.append(True))

    assert model.is_refuel_process_monitoring_enabled() is False
    assert model.set_refuel_process_monitoring_enabled(True) is True
    assert model.is_refuel_process_monitoring_enabled() is True
    assert model.is_refuel_tracking_enabled() is False
    assert model.set_refuel_process_monitoring_enabled(True) is False
    assert model.set_refuel_process_monitoring_enabled(False) is True
    assert model.is_refuel_process_monitoring_enabled() is False
    assert calls == [True, True]


def test_refuel_camera_model_process_markers_are_json_safe_and_capped():
    model = RefuelCameraModel()
    model.record_refuel_monitor_timing({"tick_index": 1, "event_kind": "skip", "extra": np.int64(2)})

    for idx in range(305):
        model.record_refuel_process_marker(
            "stage_changed",
            {
                "source": "test",
                "stage_message": f"stage {idx}",
                "sequence_status": np.str_("running"),
                "value": np.float64(1.25),
            },
        )

    markers = model.get_refuel_process_markers()
    assert len(markers) == 300
    assert markers[0]["marker_index"] == 6
    assert markers[-1]["marker_index"] == 305
    assert markers[-1]["value"] == 1.25
    assert markers[-1]["monitor_status"]["state"] == "off"
    assert markers[-1]["latest_timing"]["extra"] == 2
    json.dumps(markers[-1])


def test_refuel_camera_model_process_observation_computes_signed_drift():
    model = RefuelCameraModel()
    model.update_ui_with_analysis(None, None, 42.0, 9)
    model.set_refuel_process_monitoring_enabled(True)

    context = model.begin_refuel_process_observation(
        {
            "source": "test",
            "process_name": "PressureCalibrationProcess",
            "phase_name": "pressure_search",
            "session_id": "session-1",
        }
    )
    model.update_ui_with_analysis(None, None, 37.5, 8)
    summary = model.complete_refuel_process_observation("completed", {"event_kind": "calibration_completed"})

    assert context["baseline_level_px"] == 42.0
    assert summary["baseline_level_px"] == 42.0
    assert summary["end_level_px"] == 37.5
    assert summary["drift_px"] == -4.5
    assert summary["process_name"] == "PressureCalibrationProcess"
    assert model.get_refuel_process_summary()["active"] is None
    assert model.get_refuel_process_summary()["last"]["outcome"] == "completed"
    assert [row["event_kind"] for row in model.get_refuel_process_markers()] == [
        "process_started",
        "calibration_completed",
    ]


def test_refuel_camera_model_process_summary_prefers_reported_ejection_count():
    model = RefuelCameraModel()
    model.set_refuel_tracking_enabled(True)
    model.update_ui_with_analysis(None, None, 50.0, 10)
    model.set_refuel_process_monitoring_enabled(True)
    model.begin_refuel_process_observation({"source": "test"})
    model.record_refuel_ejection_event(2, source="capture", count_kind="observed")
    model.record_refuel_ejection_event(12, source="command", count_kind="commanded")
    model.update_ui_with_analysis(None, None, 44.0, 16)

    summary = model.complete_refuel_process_observation(
        "completed",
        {
            "printed_capture_count": 4,
            "printed_capture_event_count": 4,
            "background_capture_count": 1,
            "raw_flash_delta": 5,
        },
    )

    assert summary["drift_px"] == -6.0
    assert summary["observed_ejection_delta"] == 2
    assert summary["commanded_ejection_delta"] == 12
    assert summary["printed_capture_count"] == 4
    assert summary["ejection_count_delta"] == 4
    assert summary["ejection_count_source"] == "printed_capture_count"
    assert summary["drift_px_per_ejection"] == -1.5
    advisory = model.get_refuel_advisory()
    assert advisory["drift_px_per_ejection"] == -1.5
    assert "px/ejection" in advisory["message"]


def test_refuel_camera_model_process_summary_falls_back_to_observed_then_commanded_counts():
    model = RefuelCameraModel()
    model.set_refuel_tracking_enabled(True)
    model.update_ui_with_analysis(None, None, 30.0, 10)
    model.set_refuel_process_monitoring_enabled(True)
    model.begin_refuel_process_observation({"source": "test"})
    model.record_refuel_ejection_event(3, source="capture", count_kind="observed")
    model.record_refuel_ejection_event(10, source="command", count_kind="commanded")
    model.update_ui_with_analysis(None, None, 24.0, 16)
    summary = model.complete_refuel_process_observation("completed")

    assert summary["ejection_count_delta"] == 3
    assert summary["ejection_count_source"] == "observed_capture_ejections"
    assert summary["drift_px_per_ejection"] == -2.0

    model.begin_refuel_process_observation({"source": "test"})
    model.record_refuel_ejection_event(8, source="command", count_kind="commanded")
    model.update_ui_with_analysis(None, None, 20.0, 20)
    summary = model.complete_refuel_process_observation("completed")

    assert summary["observed_ejection_delta"] == 0
    assert summary["commanded_ejection_delta"] == 8
    assert summary["ejection_count_delta"] == 8
    assert summary["ejection_count_source"] == "commanded_dispense_ejections"
    assert summary["drift_px_per_ejection"] == -0.5


def test_refuel_camera_model_reported_zero_ejections_suppresses_drift_per_ejection():
    model = RefuelCameraModel()
    model.set_refuel_tracking_enabled(True)
    model.update_ui_with_analysis(None, None, 30.0, 10)
    model.set_refuel_process_monitoring_enabled(True)
    model.begin_refuel_process_observation({"source": "test", "printed_capture_count": 0})
    model.record_refuel_ejection_event(5, source="capture", count_kind="observed")
    model.update_ui_with_analysis(None, None, 25.0, 15)

    summary = model.complete_refuel_process_observation("completed", {"printed_capture_count": 0})

    assert summary["ejection_count_delta"] == 0
    assert summary["ejection_count_source"] == "printed_capture_count"
    assert summary["drift_px_per_ejection"] is None


def test_refuel_camera_model_append_sample_stamps_active_process_context_only():
    model = RefuelCameraModel()
    model.update_ui_with_analysis(None, None, 50.0, 11)
    base_sample_count = len(model.get_sample_trace())
    model.set_refuel_process_monitoring_enabled(True)
    model.begin_refuel_process_observation(
        {
            "source": "test",
            "process_name": "StreamCalibrationProcess",
            "phase_name": "stream_sequence",
            "session_id": "stream-1",
        }
    )
    marker_count = len(model.get_refuel_process_markers())
    model.update_ui_with_analysis(None, None, 52.0, 12)

    trace = model.get_sample_trace()
    assert len(trace) == base_sample_count + 1
    assert len(model.get_refuel_process_markers()) == marker_count
    assert trace[-1]["process_monitoring_enabled"] is True
    assert trace[-1]["process_name"] == "StreamCalibrationProcess"
    assert trace[-1]["process_phase_name"] == "stream_sequence"
    assert trace[-1]["process_session_id"] == "stream-1"
    assert trace[-1]["process_baseline_level_px"] == 50.0


def test_refuel_camera_model_process_marker_recorder_append_only_when_run_active():
    model = RefuelCameraModel()
    recorder = SimpleNamespace(append_analysis=Mock(return_value={"ok": True}))
    model._process_recorder = recorder

    model.record_refuel_process_marker("stage_changed", {"source": "test"})
    recorder.append_analysis.assert_not_called()

    model._recorder_run_dir = Path("run")
    model.record_refuel_process_marker("stage_changed", {"source": "test"})
    recorder.append_analysis.assert_called_once()
    payload = recorder.append_analysis.call_args.args[0]
    assert payload["kind"] == "refuel_process_marker"
    assert payload["event_kind"] == "stage_changed"


def test_refuel_camera_model_advisory_disabled_when_process_monitoring_off():
    model = RefuelCameraModel()
    model.set_refuel_tracking_enabled(True)
    model.update_ui_with_analysis(None, None, 4.0, 20)

    advisory = model.get_refuel_advisory()
    assert advisory["enabled"] is False
    assert advisory["code"] == "disabled"
    assert model.evaluate_refuel_advisory()["enabled"] is False
    assert model.get_refuel_advisory_log() == []


def test_refuel_camera_model_advisory_near_empty_from_level_or_status():
    model = RefuelCameraModel()
    model.set_refuel_process_monitoring_enabled(True)
    model.analysis_thread = SimpleNamespace(
        detected_status="visible",
        detected_details={"channel_bounds": [10, 20, 15, 100]},
    )
    model.update_ui_with_analysis(None, None, 8.0, 92)

    advisory = model.get_refuel_advisory()
    assert advisory["enabled"] is True
    assert advisory["code"] == "near_empty"
    assert "near empty" in advisory["message"]
    assert model.get_sample_trace()[-1]["detector_status"] == "visible"
    assert model.get_sample_trace()[-1]["channel_height_px"] == 100.0

    model.analysis_thread = SimpleNamespace(
        detected_status="empty",
        detected_details={"channel_bounds": [10, 20, 15, 100]},
    )
    model.update_ui_with_analysis(None, None, 25.0, 75)
    assert model.get_refuel_advisory()["code"] == "near_empty"


def test_refuel_camera_model_advisory_near_full_from_status_or_headroom():
    model = RefuelCameraModel()
    model.set_refuel_process_monitoring_enabled(True)
    model.analysis_thread = SimpleNamespace(
        detected_status="visible",
        detected_details={"channel_bounds": [10, 20, 15, 100]},
    )
    model.update_ui_with_analysis(None, None, 94.0, 6)
    assert model.get_refuel_advisory()["code"] == "near_full"

    model.analysis_thread = SimpleNamespace(
        detected_status="full",
        detected_details={"channel_bounds": [10, 20, 15, 100]},
    )
    model.update_ui_with_analysis(None, None, 60.0, 3)
    assert model.get_refuel_advisory()["code"] == "near_full"


def test_refuel_camera_model_advisory_completed_process_drift_recommendations():
    model = RefuelCameraModel()
    model.set_refuel_process_monitoring_enabled(True)
    model.update_ui_with_analysis(None, None, 50.0, 10)
    model.begin_refuel_process_observation({"source": "test"})
    model.update_ui_with_analysis(None, None, 44.0, 16)
    model.complete_refuel_process_observation("completed")

    advisory = model.get_refuel_advisory()
    assert advisory["code"] == "increase_refuel"
    assert "increasing refuel pressure" in advisory["message"]
    assert advisory["drift_px"] == -6.0

    model.begin_refuel_process_observation({"source": "test"})
    model.update_ui_with_analysis(None, None, 57.0, 5)
    model.complete_refuel_process_observation("completed")
    advisory = model.get_refuel_advisory()
    assert advisory["code"] == "decrease_refuel"
    assert "decreasing refuel pressure" in advisory["message"]
    assert advisory["drift_px"] == 13.0


def test_refuel_camera_model_advisory_completed_process_stable():
    model = RefuelCameraModel()
    model.set_refuel_process_monitoring_enabled(True)
    model.update_ui_with_analysis(None, None, 50.0, 10)
    model.begin_refuel_process_observation({"source": "test"})
    model.update_ui_with_analysis(None, None, 53.0, 7)
    model.complete_refuel_process_observation("completed")

    advisory = model.get_refuel_advisory()
    assert advisory["code"] == "stable"
    assert "stable" in advisory["message"]
    assert advisory["drift_px"] == 3.0


def test_refuel_camera_model_advisory_stale_and_unavailable_priority():
    model = RefuelCameraModel()
    model.set_refuel_process_monitoring_enabled(True)
    model.update_ui_with_analysis(None, None, 50.0, 10)
    model.sample_trace[-1]["monotonic_s"] = time.monotonic() - 10.0
    stale = model.evaluate_refuel_advisory(reason="manual_check")
    assert stale["code"] == "monitor_stale"

    model.last_refuel_process_summary = {"drift_px": -20.0}
    model.record_refuel_monitor_failure("Camera did not return a frame.")
    unavailable = model.get_refuel_advisory()
    assert unavailable["code"] == "monitor_unavailable"
    assert "unavailable" in unavailable["message"]


def test_refuel_camera_model_advisory_records_json_safe_capped_and_recorder_gated():
    model = RefuelCameraModel()
    recorder = SimpleNamespace(append_analysis=Mock(return_value={"ok": True}))
    model._process_recorder = recorder
    model.set_refuel_process_monitoring_enabled(True)
    model.update_ui_with_analysis(None, None, 50.0, 10)
    recorder.append_analysis.assert_not_called()

    for idx in range(105):
        model.last_refuel_process_summary = {"drift_px": np.float64(float(idx))}
        model.evaluate_refuel_advisory(reason="loop")

    log = model.get_refuel_advisory_log()
    assert len(log) == 100
    assert log[-1]["reason"] == "loop"
    json.dumps(log[-1])

    model._recorder_run_dir = Path("run")
    model.evaluate_refuel_advisory(reason="recorded")
    recorder.append_analysis.assert_called_once()
    payload = recorder.append_analysis.call_args.args[0]
    assert payload["kind"] == "refuel_advisory"
    assert payload["reason"] == "recorded"


def test_image_analysis_thread_run_records_detector_runtime():
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    thread = ImageAnalysisThread(
        image,
        offset=40,
        width=20,
        threshold=60,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
    )

    thread.run()

    assert thread.detector_runtime_ms is not None
    assert thread.detector_runtime_ms >= 0.0


def test_geometry_merges_split_head_pieces_across_channel_gap():
    image = _draw_split_head_image([
        (200, 80, 42, 180),
        (264, 80, 96, 180),
    ])
    thread = _selection_thread()

    geometry = thread._detect_refuel_head_geometry(image, threshold_value=80)

    assert geometry["merged_head_bbox"][0] == 200
    assert geometry["merged_head_bbox"][2] >= 150
    assert geometry["channel_bounds"][0] == 240
    assert geometry["channel_detection_reason"] == "fallback_offset"


def test_geometry_merges_split_right_reservoir_component():
    image = _draw_split_head_image([
        (200, 80, 120, 180),
        (342, 80, 78, 180),
    ])
    thread = _selection_thread()

    geometry = thread._detect_refuel_head_geometry(image, threshold_value=80)

    assert geometry["merged_head_bbox"][0] == 200
    assert geometry["merged_head_bbox"][2] >= 220
    assert geometry["channel_bounds"][0] == 240


def test_geometry_keeps_channel_x_stable_when_largest_raw_contour_shifts():
    full = _draw_split_head_image([(200, 80, 220, 180)])
    split = _draw_split_head_image([
        (200, 80, 42, 180),
        (264, 80, 156, 180),
    ])
    thread = _selection_thread()

    full_geometry = thread._detect_refuel_head_geometry(full, threshold_value=80)
    split_geometry = thread._detect_refuel_head_geometry(split, threshold_value=80)

    assert full_geometry["channel_bounds"][0] == split_geometry["channel_bounds"][0]
    assert full_geometry["merged_head_bbox"][0] == split_geometry["merged_head_bbox"][0]


def test_geometry_trims_visible_led_from_short_wide_head():
    image = _draw_split_head_image(
        [(200, 80, 230, 100)],
        separator_row=58,
        led_start_row=61,
    )
    thread = _selection_thread()

    geometry = thread._detect_refuel_head_geometry(image, threshold_value=80)

    assert geometry["head_bottom_reason"] == "led_separator"
    assert abs(geometry["head_bottom_row"] - (80 + 58)) <= 2
    assert geometry["channel_bounds"][3] < geometry["merged_head_bbox"][3]


def test_geometry_does_not_trim_normal_tall_head():
    image = _draw_split_head_image([(200, 80, 220, 180)])
    thread = _selection_thread()

    geometry = thread._detect_refuel_head_geometry(image, threshold_value=80)

    assert geometry["head_bottom_reason"] == "merged_bbox_bottom"
    assert geometry["channel_bounds"][3] == geometry["merged_head_bbox"][3]


def test_channel_profile_selects_wall_pair_after_initial_edge_peak():
    image = _draw_channel_wall_profile_image(edge_peak_rel=28, wall_left_rel=49, wall_spacing=20)
    thread = _selection_thread()

    geometry = thread._detect_refuel_head_geometry(image, threshold_value=80)

    assert geometry["channel_detection_reason"] == "profile_wall_pair"
    assert abs(geometry["channel_bounds"][0] - 249) <= 1
    assert abs(geometry["channel_bounds"][2] - 20) <= 1
    assert geometry["selected_channel_wall_pair"] is not None
    assert geometry["selected_channel_wall_pair_score"] <= thread.CHANNEL_WALL_PAIR_ACCEPT_SCORE_MAX


def test_channel_profile_corrects_hard_offset_when_head_left_is_shifted():
    image = _draw_channel_wall_profile_image(
        head_rect=(190, 80, 230, 180),
        wall_left_rel=49,
        wall_spacing=20,
        edge_peak_rel=30,
    )
    thread = _selection_thread()

    geometry = thread._detect_refuel_head_geometry(image, threshold_value=80)

    assert geometry["channel_detection_reason"] == "profile_wall_pair"
    assert abs(geometry["channel_bounds"][0] - 239) <= 1
    assert geometry["channel_bounds"][0] != 230


def test_channel_profile_ignores_far_right_reservoir_peaks():
    image = _draw_channel_wall_profile_image(
        wall_left_rel=48,
        wall_spacing=20,
        reservoir_peak_rel=112,
    )
    thread = _selection_thread()

    geometry = thread._detect_refuel_head_geometry(image, threshold_value=80)

    assert geometry["channel_detection_reason"] == "profile_wall_pair"
    assert abs(geometry["channel_bounds"][0] - 248) <= 1
    assert abs(geometry["channel_bounds"][2] - 20) <= 1


def test_channel_profile_falls_back_when_no_valid_wall_pair_exists():
    image = _draw_split_head_image([(200, 80, 220, 180)])
    thread = _selection_thread()

    geometry = thread._detect_refuel_head_geometry(image, threshold_value=80)

    assert geometry["channel_detection_reason"] == "fallback_offset"
    assert geometry["channel_bounds"][0] == 240
    assert geometry["channel_bounds"][2] == 20
    assert geometry["selected_channel_wall_pair"] is None


def test_channel_profile_debug_details_include_candidates_and_parameters():
    image = _draw_channel_wall_profile_image(edge_peak_rel=28, wall_left_rel=49, wall_spacing=20)
    thread = _selection_thread()

    geometry = thread._detect_refuel_head_geometry(image, threshold_value=80)

    assert geometry["channel_wall_peaks"]
    assert geometry["channel_wall_pair_candidates"]
    assert geometry["selected_channel_wall_pair"]["left_relative_x"] in {49, 50}
    assert geometry["channel_wall_profile_parameters"]["peak_prominence_min"] == 6.0
    assert thread.debug_details["channel_detection_reason"] == "profile_wall_pair"


def test_peak_selection_prefers_comparable_top_candidate_over_stale_last_row():
    thread = _selection_thread()

    selection = thread._select_peak_candidate(
        np.array([8, 105, 116]),
        np.array([10.25, 5.15, 5.15]),
        last_row=67,
    )

    assert selection["selected_peak_row"] == 8
    assert selection["selected_peak_reason"] == "top_tie_candidate"
    assert selection["top_tie_eligible_rows"] == [8]


def test_peak_selection_uses_last_row_only_when_gated_by_distance_and_prominence():
    thread = _selection_thread()

    tracked = thread._select_peak_candidate(
        np.array([60, 80]),
        np.array([10.0, 8.0]),
        last_row=82,
    )
    weak = thread._select_peak_candidate(
        np.array([50, 82]),
        np.array([10.0, 6.0]),
        last_row=82,
    )

    assert tracked["selected_peak_row"] == 80
    assert tracked["selected_peak_reason"] == "nearest_last_row_gated"
    assert weak["selected_peak_row"] == 50
    assert weak["selected_peak_reason"] == "max_prominence"


def test_peak_selection_falls_back_to_max_prominence_without_valid_top_or_tracking():
    thread = _selection_thread()

    selection = thread._select_peak_candidate(
        np.array([60, 100]),
        np.array([12.0, 8.0]),
        last_row=None,
    )

    assert selection["selected_peak_row"] == 60
    assert selection["selected_peak_reason"] == "max_prominence"


def test_weak_top_boundary_peak_classifies_as_full_without_credible_interior_peak():
    thread = _selection_thread()
    selection = {
        "selected_peak_row": 7,
        "selected_peak_prominence": 4.55,
        "candidate_rows": [7, 64, 105, 116],
        "candidate_prominences": [4.55, 4.0, 5.15, 5.2],
    }

    state, reason = thread._selected_peak_fill_override(selection, channel_height=122)

    assert state == "full"
    assert reason == "weak_top_boundary_full"


def test_strong_top_boundary_peak_remains_visible():
    thread = _selection_thread()
    selection = {
        "selected_peak_row": 7,
        "selected_peak_prominence": 5.1,
        "candidate_rows": [7, 105, 116],
        "candidate_prominences": [5.1, 5.15, 4.95],
    }

    state, reason = thread._selected_peak_fill_override(selection, channel_height=122)

    assert state is None
    assert reason == "visible_peak"


def test_visible_gate_rejects_frame_000002_style_bottom_artifact_when_fill_is_full():
    thread = _selection_thread()
    selection = {
        "selected_peak_row": 106,
        "selected_peak_prominence": 5.15,
        "candidate_rows": [8, 106, 117],
        "candidate_prominences": [4.15, 5.15, 4.95],
    }

    accepted, reason = thread._selected_peak_visible_decision(selection, channel_height=123, fill_state="full")

    assert accepted is False
    assert reason == "bottom_artifact_with_top_boundary_full"
    assert thread.debug_details["credible_visible_peak"] is False
    assert thread.debug_details["boundary_peak_rows"] == [8]
    assert thread.debug_details["bottom_artifact_rows"] == [106, 117]


def test_visible_gate_rejects_bottom_peak_with_negative_full_profile_polarity():
    thread = _selection_thread()
    selection = {
        "selected_peak_row": 111,
        "selected_peak_prominence": 7.27,
        "candidate_rows": [111],
        "candidate_prominences": [7.27],
    }
    profile = np.concatenate([
        np.full(90, 125.0),
        np.linspace(125.0, 40.0, 27),
    ])

    accepted, reason = thread._selected_peak_visible_decision(
        selection,
        channel_height=117,
        fill_state="full",
        profile=profile,
    )

    assert accepted is False
    assert reason == "bottom_negative_profile_full_artifact"
    assert thread.debug_details["visible_peak_reason"] == "bottom_negative_profile_full_artifact"
    assert thread.debug_details["bottom_peak_polarity_available"] is True
    assert thread.debug_details["bottom_peak_polarity_post_minus_pre"] <= -20.0
    assert thread.debug_details["bottom_peak_polarity_slope"] <= -1.5


def test_visible_gate_keeps_bottom_peak_with_mild_negative_profile_polarity():
    thread = _selection_thread()
    selection = {
        "selected_peak_row": 111,
        "selected_peak_prominence": 16.76,
        "candidate_rows": [111],
        "candidate_prominences": [16.76],
    }
    profile = np.concatenate([
        np.full(90, 82.0),
        np.linspace(82.0, 64.0, 27),
    ])

    accepted, reason = thread._selected_peak_visible_decision(
        selection,
        channel_height=117,
        fill_state="full",
        profile=profile,
    )

    assert accepted is True
    assert reason == "bottom_visible_without_top_boundary"
    assert thread.debug_details["bottom_peak_polarity_available"] is True
    assert thread.debug_details["bottom_peak_polarity_post_minus_pre"] > -20.0


def test_visible_gate_keeps_negative_bottom_peak_when_fill_state_is_empty():
    thread = _selection_thread()
    selection = {
        "selected_peak_row": 111,
        "selected_peak_prominence": 13.0,
        "candidate_rows": [111],
        "candidate_prominences": [13.0],
    }
    profile = np.concatenate([
        np.full(90, 125.0),
        np.linspace(125.0, 40.0, 27),
    ])

    accepted, reason = thread._selected_peak_visible_decision(
        selection,
        channel_height=117,
        fill_state="empty",
        profile=profile,
    )

    assert accepted is True
    assert reason == "bottom_visible_without_top_boundary"
    assert thread.debug_details["bottom_peak_polarity_post_minus_pre"] <= -20.0


def test_visible_gate_keeps_strong_top_visible_after_full_frame():
    thread = _selection_thread()
    selection = {
        "selected_peak_row": 5,
        "selected_peak_prominence": 8.45,
        "candidate_rows": [5, 106, 117],
        "candidate_prominences": [8.45, 5.0, 4.85],
    }

    accepted, reason = thread._selected_peak_visible_decision(selection, channel_height=123, fill_state="full")

    assert accepted is True
    assert reason == "top_visible_prominence"
    assert thread.debug_details["visible_peak_required_prominence"] == 8.0


def test_visible_gate_rejects_short_channel_top_boundary_below_visible_threshold():
    thread = _selection_thread()
    selection = {
        "selected_peak_row": 8,
        "selected_peak_prominence": 8.24,
        "candidate_rows": [8],
        "candidate_prominences": [8.24],
    }

    accepted, reason = thread._selected_peak_visible_decision(selection, channel_height=61, fill_state="full")

    assert accepted is False
    assert reason == "top_boundary_below_visible_threshold"
    assert thread.debug_details["visible_peak_required_prominence"] == 14.0


def test_visible_gate_accepts_modest_tall_top_peak_without_bottom_artifact():
    thread = _selection_thread()
    selection = {
        "selected_peak_row": 12,
        "selected_peak_prominence": 5.9,
        "candidate_rows": [12],
        "candidate_prominences": [5.9],
    }

    accepted, reason = thread._selected_peak_visible_decision(selection, channel_height=118, fill_state="full")

    assert accepted is True
    assert reason == "modest_top_visible_without_bottom_artifact"


def test_visible_gate_accepts_short_channel_strong_top_meniscus():
    thread = _selection_thread()
    selection = {
        "selected_peak_row": 7,
        "selected_peak_prominence": 19.33,
        "candidate_rows": [7],
        "candidate_prominences": [19.33],
    }

    accepted, reason = thread._selected_peak_visible_decision(selection, channel_height=58, fill_state="full")

    assert accepted is True
    assert reason == "top_visible_prominence"


def test_image_analysis_thread_detects_meniscus_row_and_level():
    expected_row = 60
    analysis_view, head_rect = _build_analysis_view(meniscus_row=expected_row)
    thread = ImageAnalysisThread(
        _thread_input_from_analysis_view(analysis_view),
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
    )

    thread.analyze_image()

    expected_level = head_rect[3] - expected_row
    assert thread.meniscus_row is not None
    assert abs(thread.meniscus_row - expected_row) <= 3
    assert abs(thread.level_data - expected_level) <= 3


def test_image_analysis_thread_debug_capture_records_visible_detection_steps():
    expected_row = 60
    analysis_view, _head_rect = _build_analysis_view(meniscus_row=expected_row)
    thread = ImageAnalysisThread(
        _thread_input_from_analysis_view(analysis_view),
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
        capture_debug=True,
    )

    thread.analyze_image()

    details = thread.debug_details
    artifacts = thread.debug_artifacts
    assert details["raw_contour_count"] >= 1
    assert details["kept_contour_count"] >= 1
    assert details["selected_head_bbox"] == list(thread.head_bbox)
    assert details["channel_bounds"] == list(thread.channel_bounds)
    assert details["analysis_parameters"]["bottom_guard_px"] == 2
    assert details["profile_stats"]["length"] == thread.channel_bounds[3]
    assert details["peak_rows"]
    assert abs(details["selected_peak_row"] - expected_row) <= 3
    assert "analysis_image" in artifacts
    assert "head_threshold_mask" in artifacts
    assert "channel_crop_blur" in artifacts
    assert "profile" in artifacts
    assert "oriented_signal" in artifacts


def test_image_analysis_thread_detects_near_bottom_visible_meniscus_with_bottom_guard():
    head_rect = (200, 80, 120, 180)
    expected_row = head_rect[3] - 3
    analysis_view, _head_rect = _build_analysis_view(
        head_rect=head_rect,
        meniscus_row=expected_row,
    )
    thread = ImageAnalysisThread(
        _thread_input_from_analysis_view(analysis_view),
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.9,
        last_row=None,
        capture_debug=True,
    )

    thread.analyze_image()

    assert thread.detected_status == "visible"
    assert abs(thread.meniscus_row - expected_row) <= 3
    assert thread.level_data <= 6
    assert thread.debug_details["search_band"] == [0, head_rect[3] - 2]
    assert thread.debug_details["analysis_parameters"]["bottom_guard_px"] == 2
    assert thread.debug_details["visible_peak_reason"] == "bottom_visible_without_top_boundary"


def test_image_analysis_thread_debug_capture_records_fill_fallback():
    analysis_view, head_rect = _build_analysis_view(
        meniscus_row=None,
        channel_intensity=10,
        reference_intensity=220,
    )
    thread = ImageAnalysisThread(
        _thread_input_from_analysis_view(analysis_view),
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
        capture_debug=True,
    )

    thread.analyze_image()

    assert thread.detected_status == "empty"
    assert thread.meniscus_row == head_rect[3] - 3
    assert thread.debug_details["fill_state"] == "empty"
    assert thread.debug_details["fill_score"] < 0.25
    assert thread.debug_details["fill_score_method"] == "max_reference_ssim"
    assert "fill_channel_patch" in thread.debug_artifacts
    assert "fill_reference_patch" in thread.debug_artifacts


def test_fill_state_uses_best_valid_reference_patch():
    analysis_view, head_rect = _build_analysis_view(
        meniscus_row=None,
        channel_intensity=110,
        reference_intensity=135,
    )
    thread = ImageAnalysisThread(
        _thread_input_from_analysis_view(analysis_view),
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
        capture_debug=True,
    )
    cur_img = cv2.rotate(thread.original_image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    x0 = head_rect[0] + 40
    y0 = head_rect[1]
    w0 = 20
    h0 = head_rect[3]

    _row, state, score, reason = thread.classify_fill_state(cur_img, x0, y0, w0, h0, empty_cutoff=0.25)

    assert state == "full"
    assert reason == "ssim_at_or_above_empty_cutoff"
    assert score >= 0.25
    assert thread.debug_details["fill_score_method"] == "max_reference_ssim"
    assert thread.debug_details["fill_reference_choice"] is not None
    assert len(thread.debug_details["fill_reference_scores"]) >= 3


def test_image_analysis_thread_default_does_not_store_debug_artifacts():
    analysis_view, _head_rect = _build_analysis_view(meniscus_row=60)
    thread = ImageAnalysisThread(
        _thread_input_from_analysis_view(analysis_view),
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
    )

    thread.analyze_image()

    assert thread.debug_details == {}
    assert thread.debug_artifacts == {}


def test_image_analysis_thread_empty_fallback_sets_bottom_row():
    analysis_view, head_rect = _build_analysis_view(
        meniscus_row=None,
        channel_intensity=10,
        reference_intensity=220,
    )
    thread = ImageAnalysisThread(
        _thread_input_from_analysis_view(analysis_view),
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
    )

    thread.analyze_image()

    assert thread.meniscus_row == head_rect[3] - 3
    assert thread.level_data == 3


def test_image_analysis_thread_full_fallback_sets_top_row():
    analysis_view, head_rect = _build_analysis_view(
        meniscus_row=None,
        channel_intensity=220,
        reference_intensity=220,
    )
    thread = ImageAnalysisThread(
        _thread_input_from_analysis_view(analysis_view),
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
    )

    thread.analyze_image()

    assert thread.meniscus_row == 3
    assert thread.level_data == head_rect[3] - 3


def test_refuel_camera_model_start_analysis_uses_last_meniscus_row(monkeypatch):
    captured = {}

    class _SignalStub:
        def connect(self, fn):
            captured["connected"] = fn

    class _ThreadStub:
        def __init__(
            self,
            image,
            offset,
            width,
            threshold,
            prominence,
            empty_cutoff,
            last_row,
            parent=None,
            capture_debug=False,
            bottom_guard_px=2,
        ):
            captured["shape"] = image.shape
            captured["last_row"] = last_row
            captured["bottom_guard_px"] = bottom_guard_px
            self.analysis_done = _SignalStub()

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(CalibrationModelModule, "ImageAnalysisThread", _ThreadStub)

    model = RefuelCameraModel()
    model.last_meniscus_row = 17
    model.level_log = [91]

    ok = model.start_analysis(np.zeros((16, 16, 3), dtype=np.uint8))

    assert ok is True
    assert captured["last_row"] == 17
    assert captured["bottom_guard_px"] == 2
    assert captured["shape"] == (640, 480, 3)
    assert captured["started"] is True
    assert model.get_raw_capture_image().shape == (16, 16, 3)


def test_refuel_camera_model_none_frame_is_safe_noop():
    model = RefuelCameraModel()
    model.current_level = 42
    model.level_log = [42]
    model.last_meniscus_row = 11
    model.raw_capture_image = "keep"
    model.annotated_image = "keep"

    ok = model.start_analysis(None)

    assert ok is False
    assert model.current_level == 42
    assert model.level_log == [42]
    assert model.last_meniscus_row == 11
    assert model.get_raw_capture_image() == "keep"
    assert model.annotated_image == "keep"


def test_refuel_camera_model_build_dataset_analysis_seed_returns_geometry_and_level():
    analysis_view, head_rect = _build_analysis_view(meniscus_row=60)
    raw_frame = _thread_input_from_analysis_view(analysis_view)
    model = RefuelCameraModel()
    model.update_analysis_parameters(40, 20, 80, 4, 0.25)

    seed = model.build_dataset_analysis_seed(raw_frame)

    assert seed is not None
    assert seed["detector_version"] == "phase2_dataset_seed_v6_bottom_polarity_gate"
    assert seed["predicted_status"] == "visible"
    assert seed["details"]["analysis_parameters"]["bottom_guard_px"] == 2
    assert abs(seed["predicted_level_px"] - (head_rect[3] - 60)) <= 3
    assert seed["predicted_channel_geometry"]["left_wall"] is not None
    assert seed["predicted_meniscus_line"] is not None
    for point in seed["predicted_meniscus_line"]:
        assert 0 <= point[0] < raw_frame.shape[1]
        assert 0 <= point[1] < raw_frame.shape[0]


def test_refuel_camera_model_lock_target_tracks_setpoint_and_status():
    model = RefuelCameraModel()
    model.current_level = 52.5
    model.last_meniscus_row = 17

    ok, message = model.lock_current_as_target(5)

    assert ok is True
    assert message == ""
    assert model.get_target_level_px() == 52.5
    assert model.get_target_meniscus_row() == 17
    assert model.is_session_active() is True
    assert model.get_live_status() == "In Band"
    assert model.classify_live_status(46.0) == "Low"
    assert model.classify_live_status(60.0) == "High"


def test_refuel_camera_model_update_ui_records_timestamped_sample_context():
    model = RefuelCameraModel()
    raw_frame = np.zeros((15, 11, 3), dtype=np.uint8)
    model.raw_capture_image = raw_frame.copy()
    model._analysis_context = _sample_context(mono=25.0)

    model.update_ui_with_analysis("orig", "ann", 42.0, 11)

    trace = model.get_sample_trace()
    assert len(trace) == 1
    assert trace[0]["timestamp_utc"] == "2026-03-21T10:00:00Z"
    assert trace[0]["elapsed_s"] == 0.0
    assert trace[0]["print_pressure"] == 1.2
    assert trace[0]["refuel_pressure"] == 0.9
    assert trace[0]["print_pulse_width"] == 1400
    assert trace[0]["refuel_pulse_width"] == 900
    assert trace[0]["location"] == "camera"
    assert model.get_level_log() == [42.0]
    assert np.array_equal(model.get_raw_capture_image(), raw_frame)
    assert model.get_analysis_input_image() == "orig"


def test_refuel_camera_model_invalid_analysis_does_not_append_sample():
    model = RefuelCameraModel()
    model._analysis_context = _sample_context(mono=30.0)

    model.update_ui_with_analysis("orig", "ann", None, None)

    assert model.get_sample_trace() == []
    assert model.get_level_log() == []


def test_refuel_camera_model_start_analysis_skips_overlap(monkeypatch):
    started = []

    class _SignalStub:
        def connect(self, fn):
            started.append(fn)

    class _ThreadStub:
        def __init__(self, *args, **kwargs):
            self.analysis_done = _SignalStub()
            self.finished = _SignalStub()

        def start(self):
            started.append("start")

    monkeypatch.setattr(CalibrationModelModule, "ImageAnalysisThread", _ThreadStub)

    model = RefuelCameraModel()
    model._analysis_in_progress = True

    ok = model.start_analysis(np.zeros((8, 8, 3), dtype=np.uint8), context=_sample_context())

    assert ok is False
    assert started == []


def test_refuel_camera_model_finalize_burst_recommends_pressure_increase():
    model = RefuelCameraModel()
    model.target_level_px = 100.0
    model.target_meniscus_row = 25
    model.tolerance_px = 5.0
    model.session_active = True
    model.sample_trace = [
        {"elapsed_s": 0.0, "monotonic_s": 1.0, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 0.5, "monotonic_s": 1.5, "level_px": 101.0, "phase": "live"},
        {"elapsed_s": 1.0, "monotonic_s": 2.0, "level_px": 99.0, "phase": "live"},
        {"elapsed_s": 1.5, "monotonic_s": 2.5, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 2.0, "monotonic_s": 3.0, "level_px": 100.0, "phase": "live"},
    ]

    result = model.begin_burst(pre_samples=5, post_samples=3, settle_ms=1000, droplet_count=20)
    assert result["ok"] is True
    model.mark_burst_started()
    model.mark_burst_wait_complete(_sample_context(mono=10.0))

    model._analysis_context = _sample_context(ts="2026-03-21T10:00:11Z", mono=10.1)
    model.update_ui_with_analysis("orig", "ann", 93.0, 20)
    model._analysis_context = _sample_context(ts="2026-03-21T10:00:12Z", mono=10.2)
    model.update_ui_with_analysis("orig", "ann", 92.0, 21)
    model._analysis_context = _sample_context(ts="2026-03-21T10:00:13Z", mono=10.3)
    model.update_ui_with_analysis("orig", "ann", 94.0, 22)

    burst = model.get_last_burst_result()
    assert burst is not None
    assert burst["recommendation"] == "Increase refuel pressure"
    assert model.is_burst_in_progress() is False


def test_refuel_camera_model_begin_burst_blocks_when_baseline_is_out_of_band():
    model = RefuelCameraModel()
    model.target_level_px = 100.0
    model.tolerance_px = 5.0
    model.session_active = True
    model.sample_trace = [
        {"elapsed_s": 0.0, "monotonic_s": 1.0, "level_px": 112.0, "phase": "live"},
        {"elapsed_s": 0.5, "monotonic_s": 1.5, "level_px": 111.0, "phase": "live"},
        {"elapsed_s": 1.0, "monotonic_s": 2.0, "level_px": 113.0, "phase": "live"},
        {"elapsed_s": 1.5, "monotonic_s": 2.5, "level_px": 112.0, "phase": "live"},
        {"elapsed_s": 2.0, "monotonic_s": 3.0, "level_px": 111.0, "phase": "live"},
    ]

    result = model.begin_burst(pre_samples=5, post_samples=3, settle_ms=1000, droplet_count=20)

    assert result["ok"] is False
    assert result["code"] == "baseline_out_of_band"


def test_refuel_camera_model_finalize_burst_recommends_decrease_and_in_band():
    high_model = RefuelCameraModel()
    high_model.target_level_px = 100.0
    high_model.tolerance_px = 5.0
    high_model.session_active = True
    high_model.sample_trace = [
        {"elapsed_s": 0.0, "monotonic_s": 1.0, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 0.5, "monotonic_s": 1.5, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 1.0, "monotonic_s": 2.0, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 1.5, "monotonic_s": 2.5, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 2.0, "monotonic_s": 3.0, "level_px": 100.0, "phase": "live"},
    ]
    assert high_model.begin_burst(5, 3, 1000, 20)["ok"] is True
    high_model.mark_burst_wait_complete(_sample_context(mono=10.0))
    for mono, level in ((10.1, 108.0), (10.2, 109.0), (10.3, 107.0)):
        high_model._analysis_context = _sample_context(mono=mono)
        high_model.update_ui_with_analysis("orig", "ann", level, 10)
    assert high_model.get_last_burst_result()["recommendation"] == "Decrease refuel pressure"

    band_model = RefuelCameraModel()
    band_model.target_level_px = 100.0
    band_model.tolerance_px = 5.0
    band_model.session_active = True
    band_model.sample_trace = list(high_model.sample_trace[:5])
    assert band_model.begin_burst(5, 3, 1000, 20)["ok"] is True
    band_model.mark_burst_wait_complete(_sample_context(mono=20.0))
    for mono, level in ((20.1, 102.0), (20.2, 101.0), (20.3, 100.0)):
        band_model._analysis_context = _sample_context(mono=mono)
        band_model.update_ui_with_analysis("orig", "ann", level, 10)
    assert band_model.get_last_burst_result()["recommendation"] == "Refuel balance is within band"


def test_refuel_camera_model_record_mode_creates_run_and_analysis_files(tmp_path):
    owner = _owner_model(tmp_path, record_mode=True)
    model = RefuelCameraModel(owner)
    model.current_level = 88.0
    model.last_meniscus_row = 19
    model.raw_capture_image = np.zeros((12, 12, 3), dtype=np.uint8)

    ok, _ = model.lock_current_as_target(5)

    assert ok is True
    run_root = Path(tmp_path) / "calibration_recordings" / "RefuelBalanceCalibrationProcess"
    run_dirs = list(run_root.iterdir())
    assert len(run_dirs) == 1

    run_meta = json.loads((run_dirs[0] / "run_meta.json").read_text(encoding="utf-8"))
    assert run_meta["target_level_px"] == 88.0
    assert run_meta["target_meniscus_row"] == 19
    assert run_meta["tolerance_px"] == 5.0

    model._analysis_context = _sample_context(mono=50.0)
    model.update_ui_with_analysis("orig", "ann", 88.5, 20)
    analysis_lines = (run_dirs[0] / "analysis.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(line)["kind"] == "refuel_level_sample" for line in analysis_lines)

    model.sample_trace = [
        {"elapsed_s": 0.0, "monotonic_s": 1.0, "level_px": 88.0, "phase": "live"},
        {"elapsed_s": 0.5, "monotonic_s": 1.5, "level_px": 88.0, "phase": "live"},
        {"elapsed_s": 1.0, "monotonic_s": 2.0, "level_px": 88.0, "phase": "live"},
        {"elapsed_s": 1.5, "monotonic_s": 2.5, "level_px": 88.0, "phase": "live"},
        {"elapsed_s": 2.0, "monotonic_s": 3.0, "level_px": 88.0, "phase": "live"},
    ]
    assert model.begin_burst(5, 3, 1000, 20)["ok"] is True
    model.mark_burst_wait_complete(_sample_context(mono=10.0))
    for mono, level in ((10.1, 90.0), (10.2, 91.0), (10.3, 90.0)):
        model._analysis_context = _sample_context(mono=mono)
        image = np.zeros((12, 12, 3), dtype=np.uint8)
        model.update_ui_with_analysis(image, image.copy(), level, 20)

    assert model.get_last_burst_result() is not None
    analysis_lines = (run_dirs[0] / "analysis.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(line)["kind"] == "refuel_burst_result" for line in analysis_lines)

    model.close_session()
    capture_files = list((run_dirs[0] / "captures").iterdir())
    capture_names = {path.name for path in capture_files}
    assert any(name.endswith("_target_lock.jpg") for name in capture_names)
    assert any(name.endswith("_burst_completion.jpg") for name in capture_names)


def test_refuel_camera_model_record_mode_off_does_not_create_run(tmp_path):
    owner = _owner_model(tmp_path, record_mode=False)
    model = RefuelCameraModel(owner)
    model.current_level = 77.0
    model.last_meniscus_row = 14
    model.raw_capture_image = np.zeros((8, 8, 3), dtype=np.uint8)

    ok, _ = model.lock_current_as_target(5)

    assert ok is True
    run_root = Path(tmp_path) / "calibration_recordings" / "RefuelBalanceCalibrationProcess"
    assert run_root.exists() is False
