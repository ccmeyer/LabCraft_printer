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


def _build_droplet_dialog(
    monkeypatch,
    qapp,
    *,
    refuel_model=None,
    main_window=None,
    open_refuel_camera_callback=None,
    start_read_camera_side_effect=None,
    status_calls=None,
):
    monkeypatch.setattr(DropletImagingDialog, "_quick_controls_expanded_default", False, raising=False)
    for method_name in (
        "setup_shortcuts",
        "set_exposure_time",
        "set_flash_delay",
        "set_flash_duration",
        "set_imaging_droplets",
        "set_start_pressure",
        "set_num_pressure_tests",
        "populate_summary_table",
        "refresh_calibration_memory_recommendation",
        "on_calibration_completed",
        "on_calibration_queue_completed",
        "on_calibration_error",
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
            get_target_refuel_pressure=lambda: 0.60,
            get_current_refuel_pressure=lambda: 0.55,
            get_refuel_pulse_width=lambda: 3200,
        ),
    )
    command_calls = []

    def _command_mock(name):
        def _side_effect(*args, **kwargs):
            command_calls.append((name, args, kwargs))
            return object()
        return Mock(side_effect=_side_effect)

    controller = SimpleNamespace(
        _command_calls=command_calls,
        start_droplet_camera=Mock(),
        start_read_camera=Mock(side_effect=start_read_camera_side_effect),
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
        enter_refuel_vacuum_mode=_command_mock("enter_refuel_vacuum_mode"),
        set_refuel_vacuum_pressure=_command_mock("set_refuel_vacuum_pressure"),
        exit_refuel_vacuum_mode=_command_mock("exit_refuel_vacuum_mode"),
        set_absolute_refuel_pressure=_command_mock("set_absolute_refuel_pressure"),
        set_refuel_pulse_width=_command_mock("set_refuel_pulse_width"),
        refuel_only=_command_mock("refuel_only"),
        move_to_location=_command_mock("move_to_location"),
    )
    if main_window is None:
        main_window = SimpleNamespace(color_dict={}, pause_machine=Mock())
    status_calls = [] if status_calls is None else status_calls
    monkeypatch.setattr(
        DropletImagingDialog,
        "update_stage_and_log",
        lambda self, message, color=None: status_calls.append((str(message), color)),
    )
    monkeypatch.setattr(
        DropletImagingDialog,
        "_refresh_manual_control_lock_state",
        lambda self, *args, **kwargs: None,
    )
    dialog = DropletImagingDialog(
        main_window,
        model,
        controller,
        open_refuel_camera_callback=open_refuel_camera_callback,
    )
    qapp.processEvents()
    return dialog, refuel_model, controller


def test_refuel_panel_default_disabled_and_no_capture(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    controller.start_droplet_camera.assert_called_once_with()
    controller.start_read_camera.assert_called_once_with()
    assert dialog._read_camera_stream_armed is True
    assert dialog._read_camera_stream_reconciled is True
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
    assert dialog.refuel_performance_debug_group.title() == "Refuel Performance Debug"
    assert dialog.enable_refuel_performance_diagnostics_checkbox.isChecked() is False
    assert dialog.export_refuel_performance_button.isEnabled() is False
    assert dialog.refuel_performance_debug_status_label.text() == "Performance diagnostics disabled"
    assert refuel_model.is_refuel_tracking_enabled() is False
    assert refuel_model.is_refuel_process_monitoring_enabled() is False
    assert refuel_model.is_refuel_calibration_performance_enabled() is False
    assert dialog.refuel_level_group.isHidden() is True
    assert dialog.refuel_level_value_label.text() == "Level: -"
    assert dialog.refuel_level_status_label.parent() is None
    assert dialog.refuel_level_last_update_label.parent() is None
    assert dialog.refuel_level_timing_label.parent() is None
    assert dialog.refuel_level_process_label.parent() is None
    assert dialog.refuel_level_ejection_label.parent() is None
    assert dialog.refuel_level_process_result_label.text() == ""
    assert dialog.refuel_level_process_result_label.isHidden() is True
    assert dialog.open_refuel_camera_button.isEnabled() is False
    assert dialog.refuel_monitor_timer.isActive() is False
    controller.start_refuel_camera.assert_not_called()
    controller.capture_refuel_image.assert_not_called()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_droplet_imager_startup_read_camera_arm_failure_is_nonfatal(monkeypatch, qapp):
    status_calls = []
    dialog, _refuel_model, controller = _build_droplet_dialog(
        monkeypatch,
        qapp,
        start_read_camera_side_effect=RuntimeError("queue offline"),
        status_calls=status_calls,
    )

    controller.start_droplet_camera.assert_called_once_with()
    controller.start_read_camera.assert_called_once_with()
    assert dialog._read_camera_stream_armed is False
    assert dialog._read_camera_stream_reconciled is False
    assert status_calls
    assert "Could not arm droplet flash/read-camera session on open: queue offline" in status_calls[0][0]


def test_refuel_panel_open_camera_button_uses_explicit_callback_without_capture(monkeypatch, qapp):
    opener = Mock()
    dialog, _refuel_model, controller = _build_droplet_dialog(
        monkeypatch,
        qapp,
        open_refuel_camera_callback=opener,
    )

    assert dialog.open_refuel_camera_button.isEnabled() is True

    dialog.open_refuel_camera_button.click()
    qapp.processEvents()

    opener.assert_called_once_with()
    controller.start_refuel_camera.assert_not_called()
    controller.capture_refuel_image.assert_not_called()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_refuel_panel_open_camera_callback_preserves_shared_refuel_model(monkeypatch, qapp):
    holder = {}

    def _open_refuel_camera():
        dialog = holder["dialog"]
        assert dialog.model.refuel_camera_model is dialog.refuel_camera_model
        dialog.refuel_camera_model.set_refuel_diagnostic_capture_active(True)

    dialog, refuel_model, controller = _build_droplet_dialog(
        monkeypatch,
        qapp,
        open_refuel_camera_callback=_open_refuel_camera,
    )
    holder["dialog"] = dialog

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    qapp.processEvents()
    controller.capture_refuel_image_with_context.reset_mock()

    dialog.open_refuel_camera_button.click()
    qapp.processEvents()

    assert dialog.model.refuel_camera_model is refuel_model
    assert dialog.refuel_camera_model is refuel_model
    assert refuel_model.is_refuel_monitor_camera_active() is True
    assert refuel_model.is_refuel_diagnostic_capture_active() is True
    controller.start_refuel_camera.assert_called_once_with()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_enabling_refuel_tracking_starts_monitor_and_schedules_immediate_capture(monkeypatch, qapp):
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
    assert dialog.refuel_level_value_label.text() == "Level: -"
    assert dialog.export_refuel_performance_button.isEnabled() is False
    assert dialog.refuel_level_advisory_label.text() == "Waiting for first refuel sample"
    assert dialog.refuel_level_process_result_label.isHidden() is True
    controller.start_refuel_camera.assert_called_once_with()
    assert refuel_model.is_refuel_monitor_camera_active() is True
    assert refuel_model.get_refuel_monitor_status()["monitor_camera_active"] is True
    controller.capture_refuel_image.assert_not_called()
    controller.capture_refuel_image_with_context.assert_called_once_with(
        analyze=True,
        context_overrides=ANY,
    )


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
    assert refuel_model.is_refuel_monitor_camera_active() is False
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

    assert dialog.refuel_level_value_label.text() == "Level: 42.5 px"
    assert dialog.refuel_level_status_label.parent() is None
    assert dialog.refuel_level_last_update_label.parent() is None
    assert dialog.refuel_level_process_label.parent() is None
    assert dialog._refuel_level_chart_bundle["primary_series"].count() == 1
    assert dialog._refuel_level_chart_bundle["current_series"].count() == 1
    assert dialog._refuel_level_chart_bundle["current_series"].color().name().lower() == "#ffffff"
    point = dialog._refuel_level_chart_bundle["primary_series"].at(0)
    assert point.x() == 0.0
    assert point.y() == 42.5
    assert dialog._refuel_level_chart_bundle["axis_x"].min() == 0.0
    assert dialog._refuel_level_chart_bundle["axis_x"].max() == 99.0
    assert dialog._refuel_level_chart_bundle["axis_y"].min() == 0.0
    assert dialog._refuel_level_chart_bundle["axis_y"].max() == 120.0
    controller.start_refuel_camera.assert_called_once_with()
    controller.capture_refuel_image.assert_not_called()
    controller.capture_refuel_image_with_context.assert_called_once_with(
        analyze=True,
        context_overrides=ANY,
    )


def test_refuel_update_signal_is_ignored_while_tracking_disabled(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    refuel_model.update_ui_with_analysis(None, None, 55.0, 10)
    qapp.processEvents()

    assert dialog.refuel_level_group.isHidden() is True
    assert dialog.refuel_level_value_label.text() == "Level: -"
    assert dialog.refuel_level_status_label.parent() is None
    assert dialog.refuel_level_timing_label.parent() is None
    assert dialog._refuel_level_chart_bundle["primary_series"].count() == 0
    controller.start_refuel_camera.assert_not_called()
    controller.capture_refuel_image.assert_not_called()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_refuel_panel_auto_refresh_is_coalesced_to_monitor_interval(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    qapp.processEvents()

    refresh_calls = []
    original_refresh = dialog._refresh_refuel_level_panel

    def counted_refresh(*args, **kwargs):
        refresh_calls.append(True)
        return original_refresh(*args, **kwargs)

    monkeypatch.setattr(dialog, "_refresh_refuel_level_panel", counted_refresh)

    refuel_model.record_refuel_monitor_timing({"tick_index": 1, "event_kind": "sample_result"})
    refuel_model.record_refuel_monitor_timing({"tick_index": 2, "event_kind": "sample_result"})
    refuel_model.record_refuel_monitor_timing({"tick_index": 3, "event_kind": "sample_result"})
    qapp.processEvents()

    assert len(refresh_calls) == 1

    refuel_model.record_refuel_monitor_timing({"tick_index": 4, "event_kind": "sample_result"})
    qapp.processEvents()

    assert len(refresh_calls) == 1

    dialog._schedule_refuel_level_panel_refresh(force=True)

    assert len(refresh_calls) == 2


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


def test_refuel_level_chart_process_markers_clip_to_visible_sample_window(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.sample_trace = [
        {
            "sample_index": index,
            "level_px": float(index),
            "channel_height_px": 150.0,
        }
        for index in range(1, 106)
    ]
    refuel_model.last_refuel_process_summary = {
        "baseline_sample_index": 1,
        "baseline_level_px": 10.0,
        "end_sample_index": 105,
        "end_level_px": 105.0,
        "drift_px": 95.0,
    }

    dialog._schedule_refuel_level_panel_refresh(force=True)

    bundle = dialog._refuel_level_chart_bundle
    assert bundle["process_start_line_series"].count() == 2
    assert bundle["process_start_line_series"].at(0).y() == 10.0
    assert bundle["process_end_line_series"].count() == 2
    assert bundle["process_end_line_series"].at(0).y() == 105.0
    assert bundle["process_start_marker_series"].count() == 0
    assert bundle["process_end_marker_series"].count() == 1
    assert bundle["process_end_marker_series"].at(0).x() == 99.0


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
    assert dialog.refuel_level_timing_label.parent() is None


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
    assert dialog.refuel_level_timing_label.parent() is None


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
    assert dialog.refuel_level_timing_label.parent() is None


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
    assert refuel_model.is_refuel_monitor_camera_active() is False
    controller.stop_refuel_camera.assert_called_once_with()
    assert refuel_model.get_refuel_monitor_timing_log()[-1]["event_kind"] == "failure"


def test_printer_head_recovery_opens_in_pull_back_and_commits_on_editing_finished(monkeypatch, qapp):
    dialog, _refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    assert dialog.printer_head_recovery_button.text() == "Printer Head Recovery"

    dialog.open_printer_head_recovery_dialog()
    qapp.processEvents()

    recovery = dialog._printer_head_recovery_dialog
    assert recovery is not None
    assert recovery.windowTitle() == "Printer Head Recovery"
    assert recovery.mode_label.text() == "Pull Back Mode"
    controller.enter_refuel_vacuum_mode.assert_called_once()
    enter_kwargs = controller.enter_refuel_vacuum_mode.call_args.kwargs
    assert enter_kwargs["target_psi"] == -1.0
    assert enter_kwargs["prep_position_steps"] == 20000
    assert enter_kwargs["move_hz"] == 5000
    assert enter_kwargs["manual"] is True
    assert recovery.pulse_button.isEnabled() is False

    enter_kwargs["handler"]()
    assert recovery.pulse_button.isEnabled() is True
    assert recovery.camera_button.isEnabled() is False
    assert recovery.switch_to_refill_button.isEnabled() is True
    assert recovery.pressure_spin.minimum() == -1.0
    assert recovery.pressure_spin.maximum() == 0.0

    recovery.pressure_spin.setValue(-0.5)
    controller.set_refuel_vacuum_pressure.assert_not_called()
    recovery.pressure_spin.editingFinished.emit()
    controller.set_refuel_vacuum_pressure.assert_called_with(-0.5, manual=True)

    recovery.pulse_width_spin.setValue(3500)
    controller.set_refuel_pulse_width.assert_not_called()
    recovery.pulse_width_spin.editingFinished.emit()
    controller.set_refuel_pulse_width.assert_called_with(3500, manual=True)


def test_printer_head_recovery_refill_mode_and_camera_return(monkeypatch, qapp):
    dialog, _refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.open_printer_head_recovery_dialog()
    qapp.processEvents()

    recovery = dialog._printer_head_recovery_dialog
    controller.enter_refuel_vacuum_mode.call_args.kwargs["handler"]()
    controller._command_calls.clear()

    recovery._switch_to_refill_mode()

    assert recovery.mode_label.text() == "Refill Mode"
    assert recovery.pressure_spin.minimum() == 0.0
    assert recovery.pressure_spin.maximum() == 5.0
    assert recovery.pressure_spin.value() == 2.0
    assert recovery.pulse_width_spin.value() == 5000
    assert recovery.pulse_button.isEnabled() is False
    assert controller.exit_refuel_vacuum_mode.call_args.args == (2.0,)
    assert controller.exit_refuel_vacuum_mode.call_args.kwargs["manual"] is True
    controller.set_refuel_pulse_width.assert_called_with(5000, handler=recovery._on_refill_entered, manual=True)
    assert [entry[0] for entry in controller._command_calls[-2:]] == [
        "exit_refuel_vacuum_mode",
        "set_refuel_pulse_width",
    ]

    controller.set_refuel_pulse_width.call_args.kwargs["handler"]()
    assert recovery.pulse_button.isEnabled() is True
    assert recovery.camera_button.isEnabled() is True
    assert recovery.switch_to_pull_back_button.isEnabled() is True
    assert recovery.switch_to_refill_button.isEnabled() is False

    recovery.pressure_spin.setValue(1.75)
    controller.set_absolute_refuel_pressure.assert_not_called()
    recovery.pressure_spin.editingFinished.emit()
    controller.set_absolute_refuel_pressure.assert_called_once_with(1.75, manual=True)

    recovery._move_to_loading()
    controller.move_to_location.assert_called_with("loading", manual=True)
    recovery._move_to_camera()
    controller.move_to_location.assert_called_with("camera", manual=True)


def test_printer_head_recovery_can_switch_back_to_pull_back(monkeypatch, qapp):
    dialog, _refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.open_printer_head_recovery_dialog()
    qapp.processEvents()

    recovery = dialog._printer_head_recovery_dialog
    controller.enter_refuel_vacuum_mode.call_args.kwargs["handler"]()
    recovery._switch_to_refill_mode()
    controller.set_refuel_pulse_width.call_args.kwargs["handler"]()
    controller.enter_refuel_vacuum_mode.reset_mock()

    recovery._switch_to_pull_back_mode()

    assert recovery.mode_label.text() == "Pull Back Mode"
    assert recovery.pressure_spin.minimum() == -1.0
    assert recovery.pressure_spin.maximum() == 0.0
    assert recovery.pressure_spin.value() == -1.0
    assert recovery.pulse_button.isEnabled() is False
    controller.enter_refuel_vacuum_mode.assert_called_once()
    enter_kwargs = controller.enter_refuel_vacuum_mode.call_args.kwargs
    assert enter_kwargs["target_psi"] == -1.0
    enter_kwargs["handler"]()
    assert recovery.pulse_button.isEnabled() is True
    assert recovery.camera_button.isEnabled() is False


def test_printer_head_recovery_pulse_action_commits_active_edits_first(monkeypatch, qapp):
    dialog, _refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.open_printer_head_recovery_dialog()
    qapp.processEvents()

    recovery = dialog._printer_head_recovery_dialog
    controller.enter_refuel_vacuum_mode.call_args.kwargs["handler"]()

    recovery.pressure_spin.setValue(-0.5)
    recovery.pulse_width_spin.setValue(3500)
    recovery.pulse_count_spin.setValue(7)
    recovery._pulse_refuel()

    controller.set_refuel_vacuum_pressure.assert_called_once_with(-0.5, manual=True)
    controller.set_refuel_pulse_width.assert_called_once_with(3500, manual=True)
    controller.refuel_only.assert_called_with(7, manual=True)


def test_printer_head_recovery_shortcuts_queue_dialog_refuel_counts(monkeypatch, qapp):
    dialog, _refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.open_printer_head_recovery_dialog()
    qapp.processEvents()

    recovery = dialog._printer_head_recovery_dialog
    controller.enter_refuel_vacuum_mode.call_args.kwargs["handler"]()

    recovery.shortcut_refuel_many.activated.emit()
    recovery.shortcut_refuel_few.activated.emit()

    assert controller.refuel_only.call_args_list[0].args == (5,)
    assert controller.refuel_only.call_args_list[0].kwargs == {"manual": True}
    assert controller.refuel_only.call_args_list[1].args == (1,)
    assert controller.refuel_only.call_args_list[1].kwargs == {"manual": True}


def test_printer_head_recovery_escape_pauses_without_closing_or_restoring(monkeypatch, qapp):
    main_window = SimpleNamespace(color_dict={}, pause_machine=Mock())
    dialog, _refuel_model, controller = _build_droplet_dialog(
        monkeypatch,
        qapp,
        main_window=main_window,
    )

    dialog.open_printer_head_recovery_dialog()
    qapp.processEvents()

    recovery = dialog._printer_head_recovery_dialog
    controller.enter_refuel_vacuum_mode.call_args.kwargs["handler"]()
    recovery.pressure_spin.setValue(-0.5)

    event = QtGui.QKeyEvent(
        QtCore.QEvent.KeyPress,
        QtCore.Qt.Key_Escape,
        QtCore.Qt.NoModifier,
    )
    recovery.keyPressEvent(event)

    assert event.isAccepted() is True
    main_window.pause_machine.assert_called_once_with()
    assert recovery.isVisible() is True
    controller.set_refuel_vacuum_pressure.assert_not_called()
    controller.set_refuel_pulse_width.assert_not_called()
    controller.exit_refuel_vacuum_mode.assert_not_called()
    assert dialog._printer_head_recovery_dialog is recovery


def test_printer_head_recovery_window_close_restores_without_motion(monkeypatch, qapp):
    dialog, _refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.open_printer_head_recovery_dialog()
    qapp.processEvents()

    recovery = dialog._printer_head_recovery_dialog
    controller.enter_refuel_vacuum_mode.call_args.kwargs["handler"]()
    recovery.close()
    qapp.processEvents()

    controller.set_refuel_pulse_width.assert_called_once_with(3200, manual=True)
    controller.exit_refuel_vacuum_mode.assert_called_once_with(0.6, manual=True)
    controller.move_to_location.assert_not_called()


def test_printer_head_recovery_reject_restores_without_pause(monkeypatch, qapp):
    main_window = SimpleNamespace(color_dict={}, pause_machine=Mock())
    dialog, _refuel_model, controller = _build_droplet_dialog(
        monkeypatch,
        qapp,
        main_window=main_window,
    )

    dialog.open_printer_head_recovery_dialog()
    qapp.processEvents()

    recovery = dialog._printer_head_recovery_dialog
    controller.enter_refuel_vacuum_mode.call_args.kwargs["handler"]()
    recovery.reject()
    qapp.processEvents()

    main_window.pause_machine.assert_not_called()
    controller.set_refuel_pulse_width.assert_called_once_with(3200, manual=True)
    controller.exit_refuel_vacuum_mode.assert_called_once_with(0.6, manual=True)
    controller.move_to_location.assert_not_called()


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
    assert dialog.refuel_level_timing_label.parent() is None


def test_refuel_panel_warns_when_monitor_has_no_valid_level_samples(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.refuel_monitor_captured_frames = 3
    refuel_model.refuel_monitor_valid_level_samples = 0
    refuel_model.set_refuel_monitor_state("monitoring", "Monitoring")
    dialog._schedule_refuel_level_panel_refresh(force=True)

    assert refuel_model.get_sample_trace() == []
    assert dialog.refuel_level_advisory_label.text() == "No new valid refuel level detected"


def test_refuel_panel_warns_when_camera_frames_repeat(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.sample_trace = [
        {
            "sample_index": 1,
            "elapsed_s": 0.0,
            "monotonic_s": 1.0,
            "level_px": 42.0,
        }
    ]
    refuel_model.refuel_monitor_captured_frames = 4
    refuel_model.refuel_monitor_valid_level_samples = 1
    refuel_model.consecutive_repeated_refuel_frame_count = 3
    refuel_model.last_refuel_frame_signature = {
        "frame_signature_available": True,
        "frame_hash": "same",
        "frame_mean_abs_delta": 0.0,
    }
    refuel_model.set_refuel_monitor_state("monitoring", "Monitoring")
    dialog._schedule_refuel_level_panel_refresh(force=True)

    assert dialog.refuel_level_value_label.text() == "Level: 42.0 px"
    assert dialog.refuel_level_advisory_label.text() == "Refuel camera image appears stale"


def test_refuel_panel_allows_constant_level_when_frames_are_fresh(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.sample_trace = [
        {"sample_index": 1, "elapsed_s": 0.0, "monotonic_s": 1.0, "level_px": 42.0},
        {
            "sample_index": 2,
            "elapsed_s": 1.0,
            "monotonic_s": 2.0,
            "level_px": 42.0,
            "same_level_streak_count": 1,
            "frame_hash": "fresh",
        },
    ]
    refuel_model.refuel_monitor_captured_frames = 2
    refuel_model.refuel_monitor_valid_level_samples = 2
    refuel_model.consecutive_repeated_refuel_frame_count = 0
    refuel_model.refuel_same_level_streak_count = 1
    refuel_model.set_refuel_monitor_state("monitoring", "Monitoring")
    dialog._schedule_refuel_level_panel_refresh(force=True)

    assert dialog.refuel_level_value_label.text() == "Level: 42.0 px"
    assert dialog.refuel_level_advisory_label.text() == "Level stable"


def test_refuel_performance_export_button_writes_snapshot_without_capture(monkeypatch, qapp, tmp_path):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    export_path = tmp_path / "snapshot.json"
    refuel_model.write_refuel_performance_snapshot = Mock(return_value=str(export_path))

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.enable_refuel_performance_diagnostics_checkbox.setChecked(True)
    qapp.processEvents()
    controller.capture_refuel_image_with_context.reset_mock()
    dialog.export_refuel_performance_button.click()
    qapp.processEvents()

    refuel_model.write_refuel_performance_snapshot.assert_called_once_with(reason="manual_export")
    assert str(export_path) in dialog.refuel_performance_debug_status_label.text()
    assert str(export_path) in dialog.export_refuel_performance_button.toolTip()
    controller.capture_refuel_image_with_context.assert_not_called()
    assert refuel_model.is_refuel_process_monitoring_enabled() is False


def test_refuel_performance_export_button_is_debug_gated(monkeypatch, qapp, tmp_path):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    refuel_model.write_refuel_performance_snapshot = Mock(return_value=str(tmp_path / "snapshot.json"))

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    qapp.processEvents()
    controller.capture_refuel_image_with_context.reset_mock()
    dialog._export_refuel_performance_snapshot()
    qapp.processEvents()

    assert dialog.export_refuel_performance_button.isEnabled() is False
    refuel_model.write_refuel_performance_snapshot.assert_not_called()
    assert "Enable refuel performance diagnostics" in dialog.refuel_performance_debug_status_label.text()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_refuel_performance_export_button_failure_does_not_start_capture(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    refuel_model.write_refuel_performance_snapshot = Mock(side_effect=RuntimeError("disk full"))

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.enable_refuel_performance_diagnostics_checkbox.setChecked(True)
    qapp.processEvents()
    controller.capture_refuel_image_with_context.reset_mock()
    dialog.export_refuel_performance_button.click()
    qapp.processEvents()

    assert "disk full" in dialog.refuel_performance_debug_status_label.text()
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
    assert refuel_model.is_refuel_monitor_camera_active() is False
    controller.stop_refuel_camera.assert_called_once_with()
    controller.stop_droplet_camera.assert_called_once_with()
    controller.disable_print_profile.assert_called_once_with()


def test_refuel_monitor_close_does_not_auto_export_without_debug_diagnostics(monkeypatch, qapp, tmp_path):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    monkeypatch.setattr(dialog, "_should_confirm_close_without_applied_calibration", lambda: False)
    export_path = tmp_path / "close_snapshot.json"
    refuel_model.write_refuel_performance_snapshot = Mock(return_value=str(export_path))

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    refuel_model.record_refuel_monitor_timing({"tick_index": 1, "event_kind": "skip"})
    event = QtGui.QCloseEvent()
    dialog.closeEvent(event)

    assert event.isAccepted() is True
    refuel_model.write_refuel_performance_snapshot.assert_not_called()
    controller.stop_refuel_camera.assert_called_once_with()


def test_refuel_monitor_close_auto_exports_when_diagnostics_enabled(monkeypatch, qapp, tmp_path):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    monkeypatch.setattr(dialog, "_should_confirm_close_without_applied_calibration", lambda: False)
    export_path = tmp_path / "close_snapshot.json"
    refuel_model.write_refuel_performance_snapshot = Mock(return_value=str(export_path))

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.enable_refuel_performance_diagnostics_checkbox.setChecked(True)
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
    dialog.enable_refuel_performance_diagnostics_checkbox.setChecked(True)
    refuel_model.record_refuel_monitor_timing({"tick_index": 1, "event_kind": "skip"})
    event = QtGui.QCloseEvent()
    dialog.closeEvent(event)

    assert event.isAccepted() is True
    controller.stop_refuel_camera.assert_called_once_with()


def test_refuel_monitor_close_does_not_record_or_export_baseline_stopwatch_without_diagnostics(monkeypatch, qapp, tmp_path):
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
    assert refuel_model.get_refuel_calibration_performance_summary()["last"] is None
    assert refuel_model.get_refuel_calibration_performance_events() == []
    refuel_model.write_refuel_performance_snapshot.assert_not_called()
    controller.start_refuel_camera.assert_not_called()
    controller.capture_refuel_image_with_context.assert_not_called()


def test_refuel_monitor_close_auto_exports_baseline_stopwatch_when_diagnostics_enabled(monkeypatch, qapp, tmp_path):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)
    manager = dialog.model.calibration_manager
    monkeypatch.setattr(dialog, "_should_confirm_close_without_applied_calibration", lambda: False)
    export_path = tmp_path / "baseline_snapshot.json"
    refuel_model.write_refuel_performance_snapshot = Mock(return_value=str(export_path))

    dialog.enable_refuel_performance_diagnostics_checkbox.setChecked(True)
    manager.activeCalibration = SimpleNamespace(
        PROCESS_NAME="DropletCalibrationProcess",
        phase_name="droplet_search",
        session_id="session-123",
    )
    manager.calibrationStageChanged.emit("Baseline process", "blue")
    manager.activeCalibration = None
    manager.calibrationCompleted.emit()
    qapp.processEvents()
    event = QtGui.QCloseEvent()
    dialog.closeEvent(event)

    assert event.isAccepted() is True
    summary = refuel_model.get_refuel_calibration_performance_summary()["last"]
    assert summary["outcome"] == "completed"
    assert summary["process_name"] == "DropletCalibrationProcess"
    assert summary["phase_name"] == "droplet_search"
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


def test_refuel_monitor_resumes_after_diagnostic_window_capture_stops(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    qapp.processEvents()
    controller.capture_refuel_image_with_context.reset_mock()

    refuel_model.set_refuel_diagnostic_capture_active(True)
    dialog._capture_refuel_monitor_sample()
    refuel_model.set_refuel_diagnostic_capture_active(False)
    dialog._capture_refuel_monitor_sample()

    controller.capture_refuel_image_with_context.assert_called_once_with(
        analyze=True,
        context_overrides=ANY,
    )
    status = refuel_model.get_refuel_monitor_status()
    assert status["state"] == "monitoring"
    assert status["monitor_camera_active"] is True
    assert status["skipped_captures"] == 1
    assert status["attempted_captures"] >= 1


def test_process_monitor_can_be_enabled_without_changing_level_tracking(monkeypatch, qapp):
    dialog, refuel_model, controller = _build_droplet_dialog(monkeypatch, qapp)

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.enable_refuel_process_monitoring_checkbox.setChecked(True)
    qapp.processEvents()

    assert refuel_model.is_refuel_tracking_enabled() is True
    assert refuel_model.is_refuel_process_monitoring_enabled() is True
    assert dialog.refuel_monitor_timer.isActive() is True
    controller.start_refuel_camera.assert_called_once_with()
    controller.capture_refuel_image_with_context.assert_called_once_with(
        analyze=True,
        context_overrides=ANY,
    )


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
    assert dialog.refuel_level_process_label.parent() is None
    dialog._schedule_refuel_level_panel_refresh(force=True)
    bundle = dialog._refuel_level_chart_bundle
    assert bundle["process_start_line_series"].count() == 2
    assert bundle["process_start_marker_series"].count() == 1
    assert bundle["process_start_marker_series"].at(0).x() == 0.0
    assert bundle["process_start_marker_series"].at(0).y() == 40.0
    assert bundle["process_end_line_series"].count() == 0
    assert bundle["process_end_marker_series"].count() == 0

    refuel_model.update_ui_with_analysis(None, None, 34.5, 10)
    manager.calibrationCompleted.emit()
    qapp.processEvents()

    summary = refuel_model.get_refuel_process_summary()["last"]
    assert summary["outcome"] == "completed"
    assert summary["baseline_level_px"] == 40.0
    assert summary["end_level_px"] == 34.5
    assert summary["drift_px"] == -5.5
    assert refuel_model.get_refuel_process_markers()[-1]["event_kind"] == "calibration_completed"
    dialog._schedule_refuel_level_panel_refresh(force=True)
    assert dialog.refuel_level_process_label.parent() is None
    assert "fell by 5.5 px" in dialog.refuel_level_advisory_label.text()
    assert dialog.refuel_level_process_result_label.isHidden() is False
    assert dialog.refuel_level_process_result_label.text() == "Last process: level fell 5.5 px"
    assert bundle["process_start_line_series"].count() == 2
    assert bundle["process_start_line_series"].at(0).y() == 40.0
    assert bundle["process_end_line_series"].count() == 2
    assert bundle["process_end_line_series"].at(0).y() == 34.5
    assert bundle["process_start_marker_series"].count() == 1
    assert bundle["process_start_marker_series"].at(0).x() == 0.0
    assert bundle["process_end_marker_series"].count() == 1
    assert bundle["process_end_marker_series"].at(0).x() == 1.0

    dialog.enable_refuel_process_monitoring_checkbox.setChecked(False)
    refuel_model.update_ui_with_analysis(None, None, 35.0, 9)
    dialog._schedule_refuel_level_panel_refresh(force=True)

    assert dialog.refuel_level_advisory_label.text() == "Level stable"
    assert dialog.refuel_level_process_result_label.text() == "Last process: level fell 5.5 px"


def test_process_result_replaces_on_next_completed_process_and_active_annotations_reset(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)
    manager = dialog.model.calibration_manager

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    dialog.enable_refuel_process_monitoring_checkbox.setChecked(True)
    refuel_model.update_ui_with_analysis(None, None, 50.0, 10)
    manager.calibrationStageChanged.emit("First process", "blue")
    refuel_model.update_ui_with_analysis(None, None, 45.0, 15)
    manager.calibrationCompleted.emit()
    dialog._schedule_refuel_level_panel_refresh(force=True)

    assert dialog.refuel_level_process_result_label.text() == "Last process: level fell 5.0 px"
    assert dialog._refuel_level_chart_bundle["process_end_line_series"].count() == 2

    refuel_model.update_ui_with_analysis(None, None, 60.0, 5)
    manager.calibrationStageChanged.emit("Second process", "blue")
    dialog._schedule_refuel_level_panel_refresh(force=True)

    bundle = dialog._refuel_level_chart_bundle
    assert dialog.refuel_level_process_result_label.isHidden() is True
    assert bundle["process_start_line_series"].count() == 2
    assert bundle["process_start_line_series"].at(0).y() == 60.0
    assert bundle["process_end_line_series"].count() == 0
    assert bundle["process_end_marker_series"].count() == 0

    refuel_model.update_ui_with_analysis(None, None, 62.0, 4)
    manager.calibrationCompleted.emit()
    dialog._schedule_refuel_level_panel_refresh(force=True)

    assert dialog.refuel_level_process_result_label.text() == "Last process: level rose 2.0 px"
    assert bundle["process_end_line_series"].count() == 2
    assert bundle["process_end_line_series"].at(0).y() == 62.0


def test_process_monitor_off_ignores_calibration_signals(monkeypatch, qapp):
    dialog, refuel_model, _controller = _build_droplet_dialog(monkeypatch, qapp)
    manager = dialog.model.calibration_manager

    dialog.enable_refuel_level_tracking_checkbox.setChecked(True)
    manager.calibrationStageChanged.emit("Ignored", "blue")
    manager.streamCaptureStateChanged.emit({"status": "running", "session_id": "stream-1"})
    qapp.processEvents()

    assert refuel_model.is_refuel_process_monitoring_enabled() is False
    assert refuel_model.get_refuel_process_markers() == []
    assert dialog.refuel_level_process_label.parent() is None


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
    assert dialog.refuel_level_advisory_label.text() == "Level stable"


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
    dialog._schedule_refuel_level_panel_refresh(force=True)

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
    assert dialog.refuel_level_advisory_label.text() == "Level stable"
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
    assert dialog.refuel_level_process_label.parent() is None
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
    assert dialog.refuel_level_ejection_label.parent() is None
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
    dialog._schedule_refuel_level_panel_refresh(force=True)
    assert "-0.500 px/ejection over 10 ejections" in dialog.refuel_level_advisory_label.text()
    assert dialog.refuel_level_process_result_label.text() == (
        "Last process: level fell 5.0 px over 10 ejections (-0.500 px/ejection)"
    )
    assert dialog.refuel_level_process_label.parent() is None
    assert dialog.refuel_level_ejection_label.parent() is None
