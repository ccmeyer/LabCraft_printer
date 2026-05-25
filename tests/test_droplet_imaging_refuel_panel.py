from types import SimpleNamespace
from unittest.mock import ANY, Mock

from PySide6 import QtCore, QtGui

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs

ensure_calibration_import_stubs()

from CalibrationClasses.Model import RefuelCameraModel
from CalibrationClasses.View import DropletImagingDialog


def _series_points(series):
    return [series.at(index) for index in range(series.count())]


def _make_calibration_manager_stub():
    return SimpleNamespace(
        activeCalibration=None,
        calibration_queue=[],
        analyzedImageUpdated=SignalStub(),
        onlineStreamDebugUpdated=SignalStub(),
        calibrationStageChanged=SignalStub(),
        calibrationCompleted=SignalStub(),
        calibrationQueueCompleted=SignalStub(),
        calibrationError=SignalStub(),
        streamCaptureStateChanged=SignalStub(),
        streamCalibrationSequenceStateChanged=SignalStub(),
        dropletCalibrationSequenceStateChanged=SignalStub(),
        position_diff_dict_signal=SignalStub(),
        characterizationSummaryUpdated=SignalStub(),
        readinessChanged=SignalStub(),
        clear_calibration_memory_ui_recommendation_state=lambda: None,
        get_record_mode_enabled=lambda: True,
        get_calibration_memory_enabled=lambda: True,
        is_stream_gravimetric_capture_busy=lambda: False,
        is_stream_calibration_sequence_busy=lambda: False,
        is_droplet_calibration_sequence_busy=lambda: False,
        _emit_readiness=lambda: None,
    )


def _build_droplet_dialog(monkeypatch, qapp, *, refuel_model=None, main_window=None):
    monkeypatch.setattr(DropletImagingDialog, "_quick_controls_expanded_default", False, raising=False)
    for method_name in (
        "setup_shortcuts",
        "start_droplet_camera",
        "set_exposure_time",
        "set_flash_delay",
        "set_flash_duration",
        "set_imaging_droplets",
        "set_start_pressure",
        "set_num_pressure_tests",
        "populate_summary_table",
        "refresh_calibration_memory_recommendation",
        "update_stage_and_log",
        "on_calibration_completed",
        "on_calibration_queue_completed",
        "on_calibration_error",
        "_refresh_manual_control_lock_state",
        "_sync_stream_capture_panel_state",
        "_ensure_stream_capture_followup_state",
        "_ensure_stream_calibration_sequence_followup_state",
        "_ensure_droplet_calibration_sequence_followup_state",
    ):
        monkeypatch.setattr(DropletImagingDialog, method_name, lambda self, *args, **kwargs: None)

    droplet_camera_model = SimpleNamespace(
        flash_duration=1000,
        flash_delay=2000,
        num_droplets=1,
        exposure_time=5000,
        droplet_image_updated=SignalStub(),
        flash_signal=SignalStub(),
    )
    if refuel_model is None:
        refuel_model = RefuelCameraModel()
    model = SimpleNamespace(
        droplet_camera_model=droplet_camera_model,
        refuel_camera_model=refuel_model,
        calibration_manager=_make_calibration_manager_stub(),
        machine_model=SimpleNamespace(
            get_print_pressure_bounds=lambda: (0.10, 5.00),
            get_print_pulse_width=lambda: 1400,
            get_current_print_pressure=lambda: 0.80,
        ),
    )
    controller = SimpleNamespace(
        start_read_camera=Mock(),
        stop_read_camera=Mock(),
        start_refuel_camera=Mock(),
        stop_refuel_camera=Mock(),
        capture_refuel_image=Mock(),
        capture_refuel_image_with_context=Mock(
            return_value=(
                object(),
                {
                    "timestamp_utc": "2026-05-25T00:00:00Z",
                    "analysis_started": True,
                    "refuel_monitor_capture_duration_ms": 3.0,
                },
            )
        ),
        stop_droplet_camera=Mock(),
        disable_print_profile=Mock(),
        set_droplet_capture_profile=Mock(),
        set_command_dispatch_interval=Mock(),
    )
    if main_window is None:
        main_window = SimpleNamespace(color_dict={})
    dialog = DropletImagingDialog(main_window, model, controller)
    qapp.processEvents()
    return dialog, refuel_model, controller


def test_refuel_panel_default_disabled_and_no_capture(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    assert dialog.control_panel_scroll.widget() is dialog.control_panel
    assert dialog.layout.itemAt(0).widget() is dialog.control_panel_scroll
    assert dialog.control_panel_scroll.widgetResizable() is True
    assert dialog.control_panel_scroll.horizontalScrollBarPolicy() == QtCore.Qt.ScrollBarAlwaysOff
    assert dialog.control_panel_scroll.verticalScrollBarPolicy() == QtCore.Qt.ScrollBarAsNeeded
    assert dialog.enable_refuel_level_tracking_checkbox.text() == "Enable Refuel Level Tracking"
    assert dialog.enable_refuel_level_tracking_checkbox.isChecked() is False
    assert dialog.enable_refuel_process_monitoring_checkbox.text() == "Monitor Calibration Processes"
    assert dialog.enable_refuel_process_monitoring_checkbox.isChecked() is False
    assert dialog.enable_refuel_process_monitoring_checkbox.isEnabled() is False
    assert refuel_model.is_refuel_tracking_enabled() is False
    assert refuel_model.is_refuel_process_monitoring_enabled() is False
    assert dialog.refuel_level_group.isHidden() is True
    assert dialog.refuel_level_status_label.text() == "Off"
    assert dialog.refuel_level_process_label.text() == "Process monitoring off"
    assert dialog.refuel_level_ejection_label.text() == "-"
    assert dialog.export_refuel_performance_button.isEnabled() is False
    assert dialog.refuel_monitor_timer.isActive() is False
    controller.start_refuel_camera.assert_not_called()
    controller.capture_refuel_image.assert_not_called()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_enabling_refuel_tracking_starts_monitor_without_immediate_capture(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    qapp.processEvents()

    assert refuel_model.is_refuel_tracking_enabled() is True
    assert refuel_model.is_refuel_process_monitoring_enabled() is False
    assert dialog.enable_refuel_process_monitoring_checkbox.isEnabled() is True
    assert dialog.enable_refuel_process_monitoring_checkbox.isChecked() is False
    assert dialog.refuel_level_group.isHidden() is False
    assert dialog.refuel_monitor_timer.isActive() is True
    assert dialog.control_panel_scroll.widget() is dialog.control_panel
    assert refuel_model.get_refuel_monitor_status()["state"] == "monitoring"
    assert dialog.refuel_level_status_label.text() == "No sample"
    assert dialog.refuel_level_process_label.text() == "Process monitoring off"
    assert dialog.refuel_level_ejection_label.text() == "Observed 0 | commanded 0"
    assert dialog.export_refuel_performance_button.isEnabled() is True
    assert dialog.refuel_level_advisory_label.text() == "Waiting for refuel samples"
    controller.start_refuel_camera.assert_called_once_with()
    controller.capture_refuel_image.assert_not_called()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_disabling_refuel_tracking_hides_panel_and_keeps_controls_available(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.enable_refuel_level_tracking_checkbox.setChecked(False)
    qapp.processEvents()

    assert refuel_model.is_refuel_tracking_enabled() is False
    assert refuel_model.is_refuel_process_monitoring_enabled() is False
    assert dialog.enable_refuel_process_monitoring_checkbox.isEnabled() is False
    assert dialog.enable_refuel_process_monitoring_checkbox.isChecked() is False
    assert dialog.refuel_level_group.isHidden() is True
    assert dialog.refuel_monitor_timer.isActive() is False
    assert refuel_model.get_refuel_monitor_status()["state"] == "off"
    assert dialog.calibration_tabs.isEnabled() is True
    assert dialog.run_options_group.isEnabled() is True
    controller.start_refuel_camera.assert_called_once_with()
    controller.stop_refuel_camera.assert_called_once_with()
    controller.capture_refuel_image.assert_not_called()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_refuel_panel_updates_from_sample_trace_when_enabled(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.analysis_thread = SimpleNamespace(
        detected_status="visible",
        detected_details={"channel_bounds": [10, 20, 15, 120]},
    )
    refuel_model.update_ui_with_analysis(None, None, 42.5, 12)
    qapp.processEvents()

    assert dialog.refuel_level_value_label.text() == "42.5 px"
    assert dialog.refuel_level_status_label.text() == "Visible"
    assert dialog.refuel_level_last_update_label.text().endswith(" s")
    assert dialog.refuel_level_process_label.text() == "Process monitoring off"
    assert dialog._refuel_level_chart_bundle["primary_series"].count() == 1
    assert dialog._refuel_level_chart_bundle["current_series"].count() == 1
    point = dialog._refuel_level_chart_bundle["primary_series"].at(0)
    assert point.x() == 0.0
    assert point.y() == 42.5
    assert dialog._refuel_level_chart_bundle["axis_x"].min() == 0.0
    assert dialog._refuel_level_chart_bundle["axis_x"].max() == 99.0
    assert dialog._refuel_level_chart_bundle["axis_y"].min() == 0.0
    assert dialog._refuel_level_chart_bundle["axis_y"].max() == 120.0
    controller.start_refuel_camera.assert_called_once_with()
    controller.capture_refuel_image.assert_not_called()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_refuel_update_signal_is_ignored_while_tracking_disabled(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    refuel_model.update_ui_with_analysis(None, None, 55.0, 10)
    qapp.processEvents()

    assert dialog.refuel_level_group.isHidden() is True
    assert dialog.refuel_level_value_label.text() == "-"
    assert dialog.refuel_level_status_label.text() == "Off"
    assert dialog.refuel_level_timing_label.text() == "-"
    assert dialog._refuel_level_chart_bundle["primary_series"].count() == 0
    controller.start_refuel_camera.assert_not_called()
    controller.capture_refuel_image.assert_not_called()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_refuel_level_chart_uses_fixed_fallback_scale_without_channel_height(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    for level in (10.0, 45.0, 90.0):
        refuel_model.analysis_thread = SimpleNamespace(
            detected_status="visible",
            detected_details={},
        )
        refuel_model.update_ui_with_analysis(None, None, level, int(100 - level))
    qapp.processEvents()

    bundle = dialog._refuel_level_chart_bundle
    points = _series_points(bundle["primary_series"])
    assert [(point.x(), point.y()) for point in points] == [(0.0, 10.0), (1.0, 45.0), (2.0, 90.0)]
    assert bundle["axis_x"].min() == 0.0
    assert bundle["axis_x"].max() == 99.0
    assert bundle["axis_y"].min() == 0.0
    assert bundle["axis_y"].max() == 100.0


def test_refuel_level_chart_rolls_last_100_samples_without_truncating_trace(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    for level in range(105):
        refuel_model.analysis_thread = SimpleNamespace(
            detected_status="visible",
            detected_details={"channel_bounds": [10, 20, 15, 150]},
        )
        refuel_model.update_ui_with_analysis(None, None, float(level), 150 - level)
    qapp.processEvents()

    bundle = dialog._refuel_level_chart_bundle
    points = _series_points(bundle["primary_series"])
    current_points = _series_points(bundle["current_series"])
    assert len(refuel_model.get_sample_trace()) == 105
    assert bundle["primary_series"].count() == 100
    assert points[0].x() == 0.0
    assert points[0].y() == 5.0
    assert points[-1].x() == 99.0
    assert points[-1].y() == 104.0
    assert current_points[0].x() == 99.0
    assert current_points[0].y() == 104.0
    assert bundle["axis_x"].min() == 0.0
    assert bundle["axis_x"].max() == 99.0
    assert bundle["axis_y"].min() == 0.0
    assert bundle["axis_y"].max() == 150.0


def test_refuel_monitor_tick_captures_with_context_and_updates_counters(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog._capture_refuel_monitor_sample()
    qapp.processEvents()

    controller.capture_refuel_image_with_context.assert_called_once_with(
        analyze=True,
        context_overrides=ANY,
    )
    status = refuel_model.get_refuel_monitor_status()
    assert status["attempted_captures"] == 1
    assert status["successful_captures"] == 1
    assert status["failed_captures"] == 0
    assert status["state"] == "monitoring"
    assert refuel_model.get_refuel_monitor_timing_log() == []


def test_refuel_monitor_success_timing_shows_after_analysis_result(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog._capture_refuel_monitor_sample()
    context_overrides = controller.capture_refuel_image_with_context.call_args.kwargs["context_overrides"]
    refuel_model._analysis_context = {
        **context_overrides,
        "refuel_monitor_capture_duration_ms": 3.0,
        "analysis_started": True,
        "timestamp_utc": "2026-05-25T00:00:00Z",
        "monotonic_s": 20.0,
    }
    refuel_model._analysis_timing_context = {"copy_resize_duration_ms": 2.0}
    refuel_model.analysis_thread = SimpleNamespace(
        detector_runtime_ms=4.0,
        detected_status="visible",
    )

    refuel_model.update_ui_with_analysis(None, None, 44.0, 8)
    qapp.processEvents()

    timing = refuel_model.get_refuel_monitor_timing_log()[-1]
    assert timing["event_kind"] == "sample_result"
    assert timing["capture_duration_ms"] == 3.0
    assert timing["copy_resize_duration_ms"] == 2.0
    assert timing["detector_runtime_ms"] == 4.0
    assert timing["total_latency_ms"] >= 0.0
    assert dialog.refuel_level_timing_label.text().startswith("Capture 3 ms | Detector 4 ms | Total")


def test_refuel_monitor_tick_skips_when_analysis_in_progress(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model._analysis_in_progress = True
    dialog._capture_refuel_monitor_sample()
    qapp.processEvents()

    controller.capture_refuel_image_with_context.assert_not_called()
    status = refuel_model.get_refuel_monitor_status()
    assert status["skipped_captures"] == 1
    assert status["message"] == "Waiting for refuel analysis"
    timing = refuel_model.get_refuel_monitor_timing_log()[-1]
    assert timing["event_kind"] == "skip"
    assert timing["skip_reason"] == "analysis_in_progress"
    assert dialog.refuel_level_timing_label.text() == "Skipped: analysis_in_progress"


def test_refuel_monitor_capture_failure_marks_unavailable_without_raising(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    controller.capture_refuel_image_with_context.side_effect = RuntimeError("camera busy")

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog._capture_refuel_monitor_sample()
    qapp.processEvents()

    status = refuel_model.get_refuel_monitor_status()
    assert status["state"] == "unavailable"
    assert status["failed_captures"] == 1
    assert "camera busy" in status["message"]
    assert dialog.refuel_level_advisory_label.text().startswith("Refuel capture failed")
    timing = refuel_model.get_refuel_monitor_timing_log()[-1]
    assert timing["event_kind"] == "failure"
    assert "camera busy" in timing["failure_message"]
    assert dialog.refuel_level_timing_label.text().startswith("Failure: Refuel capture failed")


def test_refuel_monitor_stops_after_three_none_frames(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    controller.capture_refuel_image_with_context.return_value = (None, {})

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    for _ in range(3):
        dialog._capture_refuel_monitor_sample()
    qapp.processEvents()

    status = refuel_model.get_refuel_monitor_status()
    assert status["state"] == "unavailable"
    assert status["failed_captures"] == 3
    assert status["consecutive_failures"] == 3
    assert dialog.refuel_monitor_timer.isActive() is False
    controller.stop_refuel_camera.assert_called_once_with()
    assert refuel_model.get_refuel_monitor_timing_log()[-1]["event_kind"] == "failure"


def test_refuel_monitor_records_analysis_not_started(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    controller.capture_refuel_image_with_context.return_value = (
        object(),
        {
            "analysis_started": False,
            "refuel_monitor_capture_duration_ms": 5.0,
        },
    )

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog._capture_refuel_monitor_sample()
    qapp.processEvents()

    timing = refuel_model.get_refuel_monitor_timing_log()[-1]
    assert timing["event_kind"] == "analysis_not_started"
    assert timing["analysis_started"] is False
    assert timing["capture_duration_ms"] == 5.0
    assert dialog.refuel_level_timing_label.text() == "Analysis not started"


def test_refuel_performance_export_button_writes_snapshot_without_capture(monkeypatch, qapp, tmp_path):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    export_path = tmp_path / "snapshot.json"
    refuel_model.write_refuel_performance_snapshot = Mock(return_value=str(export_path))

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.export_refuel_performance_button.click()
    qapp.processEvents()

    refuel_model.write_refuel_performance_snapshot.assert_called_once_with(reason="manual_export")
    assert str(export_path) in dialog.refuel_level_advisory_label.text()
    assert str(export_path) in dialog.export_refuel_performance_button.toolTip()
    controller.capture_refuel_image_with_context.assert_not_called()
    assert refuel_model.is_refuel_process_monitoring_enabled() is False


def test_refuel_performance_export_button_failure_does_not_start_capture(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    refuel_model.write_refuel_performance_snapshot = Mock(side_effect=RuntimeError("disk full"))

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.export_refuel_performance_button.click()
    qapp.processEvents()

    assert "disk full" in dialog.refuel_level_advisory_label.text()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_refuel_monitor_close_stops_camera_before_dialog_cleanup(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    monkeypatch.setattr(dialog, "_should_confirm_close_without_applied_calibration", lambda: False)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    event = QtGui.QCloseEvent()
    dialog.closeEvent(event)

    assert event.isAccepted() is True
    assert dialog.refuel_monitor_timer.isActive() is False
    assert refuel_model.get_refuel_monitor_status()["state"] == "off"
    controller.stop_refuel_camera.assert_called_once_with()
    controller.stop_droplet_camera.assert_called_once_with()
    controller.disable_print_profile.assert_called_once_with()


def test_refuel_monitor_close_auto_exports_when_timing_exists(monkeypatch, qapp, tmp_path):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    monkeypatch.setattr(dialog, "_should_confirm_close_without_applied_calibration", lambda: False)
    export_path = tmp_path / "close_snapshot.json"
    refuel_model.write_refuel_performance_snapshot = Mock(return_value=str(export_path))

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.record_refuel_monitor_timing({"tick_index": 1, "event_kind": "skip"})
    event = QtGui.QCloseEvent()
    dialog.closeEvent(event)

    assert event.isAccepted() is True
    refuel_model.write_refuel_performance_snapshot.assert_called_once_with(reason="dialog_close")
    controller.stop_refuel_camera.assert_called_once_with()


def test_refuel_monitor_close_auto_export_failure_does_not_crash(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    monkeypatch.setattr(dialog, "_should_confirm_close_without_applied_calibration", lambda: False)
    refuel_model.write_refuel_performance_snapshot = Mock(side_effect=RuntimeError("no permission"))

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.record_refuel_monitor_timing({"tick_index": 1, "event_kind": "skip"})
    event = QtGui.QCloseEvent()
    dialog.closeEvent(event)

    assert event.isAccepted() is True
    controller.stop_refuel_camera.assert_called_once_with()


def test_refuel_monitor_close_auto_exports_baseline_stopwatch_when_tracking_off(monkeypatch, qapp, tmp_path):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    manager = dialog.model.calibration_manager
    monkeypatch.setattr(dialog, "_should_confirm_close_without_applied_calibration", lambda: False)
    export_path = tmp_path / "baseline_snapshot.json"
    refuel_model.write_refuel_performance_snapshot = Mock(return_value=str(export_path))

    manager.calibrationStageChanged.emit("Baseline process", "blue")
    manager.calibrationCompleted.emit()
    qapp.processEvents()
    event = QtGui.QCloseEvent()
    dialog.closeEvent(event)

    assert event.isAccepted() is True
    assert refuel_model.is_refuel_tracking_enabled() is False
    assert refuel_model.get_refuel_calibration_performance_summary()["last"]["outcome"] == "completed"
    refuel_model.write_refuel_performance_snapshot.assert_called_once_with(reason="dialog_close")
    controller.start_refuel_camera.assert_not_called()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_refuel_monitor_skips_while_diagnostic_window_capture_active(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.set_refuel_diagnostic_capture_active(True)
    dialog._capture_refuel_monitor_sample()
    qapp.processEvents()

    controller.capture_refuel_image_with_context.assert_not_called()
    status = refuel_model.get_refuel_monitor_status()
    assert status["state"] == "paused"
    assert status["skipped_captures"] == 1
    assert dialog.refuel_level_advisory_label.text() == "Paused by refuel camera window"
    timing = refuel_model.get_refuel_monitor_timing_log()[-1]
    assert timing["event_kind"] == "skip"
    assert timing["skip_reason"] == "diagnostic_capture_active"


def test_process_monitor_can_be_enabled_without_changing_level_tracking(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.enable_refuel_process_monitoring_checkbox.setChecked(True)
    qapp.processEvents()

    assert refuel_model.is_refuel_tracking_enabled() is True
    assert refuel_model.is_refuel_process_monitoring_enabled() is True
    assert dialog.refuel_monitor_timer.isActive() is True
    controller.start_refuel_camera.assert_called_once_with()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_process_monitor_records_stage_and_completion_drift(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)
    manager = dialog.model.calibration_manager
    manager.activeCalibration = SimpleNamespace(
        phase_name="droplet_search",
        session_id="session-123",
    )

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.update_ui_with_analysis(None, None, 40.0, 12)
    dialog.enable_refuel_process_monitoring_checkbox.setChecked(True)

    manager.calibrationStageChanged.emit("Printing droplets", "blue")
    qapp.processEvents()

    markers = refuel_model.get_refuel_process_markers()
    assert [row["event_kind"] for row in markers[-2:]] == ["process_started", "stage_changed"]
    assert markers[-1]["stage_message"] == "Printing droplets"
    assert markers[-1]["phase_name"] == "droplet_search"
    assert dialog.refuel_level_process_label.text() == "Monitoring droplet_search"

    refuel_model.update_ui_with_analysis(None, None, 34.5, 10)
    manager.calibrationCompleted.emit()
    qapp.processEvents()

    summary = refuel_model.get_refuel_process_summary()["last"]
    assert summary["outcome"] == "completed"
    assert summary["baseline_level_px"] == 40.0
    assert summary["end_level_px"] == 34.5
    assert summary["drift_px"] == -5.5
    assert refuel_model.get_refuel_process_markers()[-1]["event_kind"] == "calibration_completed"
    assert dialog.refuel_level_process_label.text() == "Drift -5.5 px"
    assert "fell by 5.5 px" in dialog.refuel_level_advisory_label.text()


def test_process_monitor_off_ignores_calibration_signals(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)
    manager = dialog.model.calibration_manager

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    manager.calibrationStageChanged.emit("Ignored", "blue")
    manager.streamCaptureStateChanged.emit({"status": "running", "session_id": "stream-1"})
    qapp.processEvents()

    assert refuel_model.is_refuel_process_monitoring_enabled() is False
    assert refuel_model.get_refuel_process_markers() == []
    assert dialog.refuel_level_process_label.text() == "Process monitoring off"


def test_advisory_label_stays_passive_with_only_level_tracking(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.analysis_thread = SimpleNamespace(
        detected_status="empty",
        detected_details={"channel_bounds": [10, 20, 15, 100]},
    )
    refuel_model.update_ui_with_analysis(None, None, 4.0, 96)
    qapp.processEvents()

    assert refuel_model.get_refuel_advisory()["enabled"] is False
    assert refuel_model.get_refuel_advisory_log() == []
    assert dialog.refuel_level_advisory_label.text() == "Monitoring"


def test_advisory_label_shows_process_monitor_empty_and_full_guidance(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.enable_refuel_process_monitoring_checkbox.setChecked(True)
    refuel_model.analysis_thread = SimpleNamespace(
        detected_status="empty",
        detected_details={"channel_bounds": [10, 20, 15, 100]},
    )
    refuel_model.update_ui_with_analysis(None, None, 4.0, 96)
    qapp.processEvents()

    assert "empty" in dialog.refuel_level_advisory_label.text()

    refuel_model.analysis_thread = SimpleNamespace(
        detected_status="visible",
        detected_details={"channel_bounds": [10, 20, 15, 100]},
    )
    refuel_model.update_ui_with_analysis(None, None, 95.0, 5)
    qapp.processEvents()

    assert "near full" in dialog.refuel_level_advisory_label.text()


def test_disabling_process_monitor_keeps_level_tracking_active(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    manager = dialog.model.calibration_manager

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.enable_refuel_process_monitoring_checkbox.setChecked(True)
    manager.calibrationStageChanged.emit("Active", "blue")
    assert refuel_model.get_refuel_process_markers()
    refuel_model.update_ui_with_analysis(None, None, 4.0, 20)
    assert refuel_model.get_refuel_advisory()["enabled"] is True

    dialog.enable_refuel_process_monitoring_checkbox.setChecked(False)
    marker_count = len(refuel_model.get_refuel_process_markers())
    manager.calibrationStageChanged.emit("Ignored after off", "blue")
    qapp.processEvents()

    assert refuel_model.is_refuel_tracking_enabled() is True
    assert refuel_model.is_refuel_process_monitoring_enabled() is False
    assert dialog.refuel_monitor_timer.isActive() is True
    assert len(refuel_model.get_refuel_process_markers()) == marker_count
    assert refuel_model.get_refuel_advisory()["enabled"] is False
    assert dialog.refuel_level_advisory_label.text() == "Monitoring"
    controller.stop_refuel_camera.assert_not_called()


def test_level_tracking_off_disables_process_monitoring(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.enable_refuel_process_monitoring_checkbox.setChecked(True)
    dialog.enable_refuel_level_tracking_checkbox.setChecked(False)
    qapp.processEvents()

    assert refuel_model.is_refuel_tracking_enabled() is False
    assert refuel_model.is_refuel_process_monitoring_enabled() is False
    assert dialog.enable_refuel_process_monitoring_checkbox.isChecked() is False
    assert dialog.enable_refuel_process_monitoring_checkbox.isEnabled() is False
    assert dialog.refuel_level_process_label.text() == "Process monitoring off"
    assert dialog.refuel_level_advisory_label.text() == "Monitoring disabled"


def test_refuel_panel_shows_live_ejection_counts_without_process_advisory(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.record_refuel_ejection_event(
        2,
        source="capture",
        event_kind="capture_completed",
        count_kind="observed",
    )
    refuel_model.record_refuel_ejection_event(
        5,
        source="command",
        event_kind="print_queued",
        count_kind="commanded",
    )
    qapp.processEvents()

    assert refuel_model.is_refuel_process_monitoring_enabled() is False
    assert dialog.refuel_level_ejection_label.text() == "Observed 2 | commanded 5"
    assert refuel_model.get_refuel_advisory()["enabled"] is False


def test_process_monitor_records_sequence_and_capture_state_signals(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)
    manager = dialog.model.calibration_manager

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.enable_refuel_process_monitoring_checkbox.setChecked(True)

    manager.streamCaptureStateChanged.emit({"status": "running", "session_id": "stream-capture"})
    manager.streamCalibrationSequenceStateChanged.emit({"status": "running", "session_id": "stream-seq"})
    manager.dropletCalibrationSequenceStateChanged.emit({"status": "running", "session_id": "droplet-seq"})
    manager.calibrationError.emit("camera failed")
    manager.calibrationQueueCompleted.emit()
    qapp.processEvents()

    event_kinds = [row["event_kind"] for row in refuel_model.get_refuel_process_markers()]
    assert "stream_capture_state_changed" in event_kinds
    assert "stream_sequence_state_changed" in event_kinds
    assert "droplet_sequence_state_changed" in event_kinds
    assert "calibration_error" in event_kinds
    assert "queue_completed" in event_kinds


def test_process_monitor_uses_stream_printed_count_for_drift_per_ejection(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)
    manager = dialog.model.calibration_manager

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.update_ui_with_analysis(None, None, 50.0, 10)
    dialog.enable_refuel_process_monitoring_checkbox.setChecked(True)
    manager.streamCaptureStateChanged.emit({"status": "running", "session_id": "stream-capture"})
    refuel_model.record_refuel_ejection_event(2, source="capture", count_kind="observed")
    refuel_model.update_ui_with_analysis(None, None, 45.0, 15)

    manager.streamCaptureStateChanged.emit(
        {
            "status": "completed",
            "session_id": "stream-capture",
            "printed_capture_count": 10,
            "printed_capture_event_count": 10,
            "background_capture_count": 1,
            "raw_flash_delta": 11,
        }
    )
    qapp.processEvents()

    summary = refuel_model.get_refuel_process_summary()["last"]
    assert summary["ejection_count_delta"] == 10
    assert summary["ejection_count_source"] == "printed_capture_count"
    assert summary["drift_px_per_ejection"] == -0.5
    assert dialog.refuel_level_process_label.text() == "Drift -5.0 px | -0.500 px/ejection"
    assert dialog.refuel_level_ejection_label.text() == "10 | -0.500 px/ejection"
