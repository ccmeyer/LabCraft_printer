from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.View import DropletImagingDialog


class _DropletCameraModelStub:
    def __init__(self):
        self.flash_duration = 1000
        self.flash_delay = 2000
        self.num_droplets = 1
        self.exposure_time = 5000
        self.num_flashes = 0
        self.ext_counter = 0
        self.flash_session_armed = False
        self.flash_fault_latched = False
        self.flash_fault_reason = ""
        self.droplet_image_updated = SignalStub()
        self.flash_signal = SignalStub()

    def get_flash_duration(self):
        return self.flash_duration

    def get_flash_delay(self):
        return self.flash_delay

    def get_num_droplets(self):
        return self.num_droplets

    def get_exposure_time(self):
        return self.exposure_time

    def get_num_flashes(self):
        return self.num_flashes

    def get_trigger_counter(self):
        return self.ext_counter

    def get_flash_session_armed(self):
        return self.flash_session_armed

    def get_flash_fault_latched(self):
        return self.flash_fault_latched

    def get_flash_fault_reason_display(self):
        return "None"

    def get_original_image(self):
        return np.full((120, 80), 180, dtype=np.uint8)


class _CalibrationManagerStub:
    def __init__(self):
        self.analyzedImageUpdated = SignalStub()
        self.onlineStreamDebugUpdated = SignalStub()
        self.calibrationStageChanged = SignalStub()
        self.calibrationCompleted = SignalStub()
        self.calibrationQueueCompleted = SignalStub()
        self.calibrationError = SignalStub()
        self.position_diff_dict_signal = SignalStub()
        self.characterizationSummaryUpdated = SignalStub()
        self.readinessChanged = SignalStub()
        self.streamCaptureStateChanged = SignalStub()
        self.activeCalibration = None
        self.calibration_queue = []
        self.state = {"status": "idle"}

    def clear_calibration_memory_ui_recommendation_state(self):
        return None

    def get_record_mode_enabled(self):
        return True

    def get_calibration_memory_enabled(self):
        return True

    def _emit_readiness(self):
        return None

    def is_pulsewidth_sweep_active(self):
        return False

    def is_stream_gravimetric_capture_busy(self):
        return str(self.state.get("status") or "idle") != "idle"

    def get_stream_gravimetric_capture_state(self):
        return dict(self.state)


class _ControllerStub:
    def __init__(self):
        self.start_online_stream_calls = 0
        self.start_nozzle_calls = 0
        self.stop_calibration_calls = 0

    def start_read_camera(self):
        return None

    def capture_droplet_image(self, throughput_mode=False):
        return None

    def start_nozzle_calibration(self):
        self.start_nozzle_calls += 1

    def start_online_stream_calibration(self):
        self.start_online_stream_calls += 1

    def stop_calibration(self):
        self.stop_calibration_calls += 1


def _build_dialog(monkeypatch, qapp):
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
    ):
        monkeypatch.setattr(DropletImagingDialog, method_name, lambda self, *args, **kwargs: None)

    manager = _CalibrationManagerStub()
    controller = _ControllerStub()
    model = SimpleNamespace(
        droplet_camera_model=_DropletCameraModelStub(),
        calibration_manager=manager,
        machine_model=SimpleNamespace(
            get_print_pressure_bounds=lambda: (0.10, 5.00),
            get_print_pulse_width=lambda: 1400,
            get_current_print_pressure=lambda: 0.80,
        ),
    )
    dialog = DropletImagingDialog(SimpleNamespace(color_dict={}), model, controller)
    qapp.processEvents()
    return dialog, manager, controller


def test_online_stream_button_is_created_and_reset_label_is_stable(monkeypatch, qapp):
    dialog, _manager, _controller = _build_dialog(monkeypatch, qapp)

    assert dialog.calibrate_online_stream_button.text() == "Calibrate Stream Volume"

    dialog.calibrate_online_stream_button.setText("Stop Calibration")
    dialog.reset_calibration_buttons()

    assert dialog.calibrate_online_stream_button.text() == "Calibrate Stream Volume"

    dialog.deleteLater()


def test_online_stream_toggle_starts_and_stops_via_controller(monkeypatch, qapp):
    dialog, manager, controller = _build_dialog(monkeypatch, qapp)

    dialog.calibrate_online_stream_button.click()
    qapp.processEvents()

    assert controller.start_online_stream_calls == 1
    assert dialog.calibrate_online_stream_button.text() == "Stop Calibration"

    manager.activeCalibration = object()
    dialog.calibrate_online_stream_button.click()
    qapp.processEvents()

    assert controller.stop_calibration_calls == 1
    assert dialog.calibrate_online_stream_button.text() == "Calibrate Stream Volume"

    dialog.deleteLater()


def test_shared_nozzle_buttons_mirror_start_and_stop_text(monkeypatch, qapp):
    dialog, manager, controller = _build_dialog(monkeypatch, qapp)

    dialog.calibrate_nozzle_stream_button.click()
    qapp.processEvents()

    assert controller.start_nozzle_calls == 1
    assert dialog.calibrate_nozzle_button.text() == "Stop Calibration"
    assert dialog.calibrate_nozzle_stream_button.text() == "Stop Calibration"

    manager.activeCalibration = object()
    dialog.calibrate_nozzle_button.click()
    qapp.processEvents()

    assert controller.stop_calibration_calls == 1
    assert dialog.calibrate_nozzle_button.text() == "Calibrate Nozzle Position"
    assert dialog.calibrate_nozzle_stream_button.text() == "Calibrate Nozzle Position"

    dialog.deleteLater()


def test_online_stream_readiness_controls_enabled_state_and_tooltip(monkeypatch, qapp):
    dialog, _manager, _controller = _build_dialog(monkeypatch, qapp)

    dialog.on_readiness_changed(
        {
            "online_stream_calibration": {
                "ready": False,
                "missing": ["Emergence time", "Active printer head"],
            }
        }
    )

    assert dialog.calibrate_online_stream_button.isEnabled() is False
    assert "Emergence time" in dialog.calibrate_online_stream_button.toolTip()
    assert "Active printer head" in dialog.calibrate_online_stream_button.toolTip()

    dialog.on_readiness_changed(
        {
            "online_stream_calibration": {
                "ready": True,
                "missing": [],
            }
        }
    )

    assert dialog.calibrate_online_stream_button.isEnabled() is True
    assert dialog.calibrate_online_stream_button.toolTip() == ""

    dialog.deleteLater()


def test_online_stream_flash_fault_overrides_ready_and_recovers_without_new_readiness(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)
    cam = dialog.model.droplet_camera_model

    dialog.on_readiness_changed(
        {
            "online_stream_calibration": {
                "ready": True,
                "missing": [],
            }
        }
    )
    assert dialog.calibrate_online_stream_button.isEnabled() is True

    cam.flash_fault_latched = True
    cam.flash_fault_reason = "line_stuck_high"
    dialog.update_flash_info()
    qapp.processEvents()

    assert dialog.calibrate_online_stream_button.isEnabled() is False
    assert "flash safety fault" in dialog.calibrate_online_stream_button.toolTip().lower()

    cam.flash_fault_latched = False
    cam.flash_fault_reason = ""
    dialog.update_flash_info()
    qapp.processEvents()

    assert manager.activeCalibration is None
    assert dialog.calibrate_online_stream_button.isEnabled() is True
    assert dialog.calibrate_online_stream_button.toolTip() == ""

    dialog.deleteLater()


def test_online_stream_stream_capture_lockout_overrides_ready_state(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)

    dialog.on_readiness_changed(
        {
            "online_stream_calibration": {
                "ready": True,
                "missing": [],
            }
        }
    )
    manager.state["status"] = "running"
    dialog._sync_stream_capture_panel_state()
    qapp.processEvents()

    assert dialog.calibrate_online_stream_button.isEnabled() is False
    assert "stream gravimetric capture" in dialog.calibrate_online_stream_button.toolTip().lower()

    dialog.deleteLater()


def test_tabs_lock_during_active_calibration_and_unlock_when_idle(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)

    dialog.calibration_tabs.setCurrentIndex(1)
    qapp.processEvents()

    manager.activeCalibration = object()
    dialog._refresh_manual_control_lock_state()
    qapp.processEvents()

    assert dialog.calibration_tabs.isTabEnabled(0) is False
    assert dialog.calibration_tabs.isTabEnabled(1) is True
    assert dialog.calibration_tabs.isTabEnabled(2) is False

    manager.activeCalibration = None
    dialog._refresh_manual_control_lock_state()
    qapp.processEvents()

    assert dialog.calibration_tabs.isTabEnabled(0) is True
    assert dialog.calibration_tabs.isTabEnabled(1) is True
    assert dialog.calibration_tabs.isTabEnabled(2) is True

    dialog.deleteLater()


def test_tabs_lock_during_pulsewidth_sweep_and_unlock_afterwards(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)

    dialog.calibration_tabs.setCurrentIndex(2)
    qapp.processEvents()

    monkeypatch.setattr(manager, "is_pulsewidth_sweep_active", lambda: True)
    dialog._refresh_calibration_tab_lock_state()
    qapp.processEvents()

    assert dialog.calibration_tabs.isTabEnabled(0) is False
    assert dialog.calibration_tabs.isTabEnabled(1) is False
    assert dialog.calibration_tabs.isTabEnabled(2) is True

    monkeypatch.setattr(manager, "is_pulsewidth_sweep_active", lambda: False)
    dialog._refresh_calibration_tab_lock_state()
    qapp.processEvents()

    assert dialog.calibration_tabs.isTabEnabled(0) is True
    assert dialog.calibration_tabs.isTabEnabled(1) is True
    assert dialog.calibration_tabs.isTabEnabled(2) is True

    dialog.deleteLater()


def test_online_stream_running_process_keeps_stop_button_enabled_when_readiness_regresses(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)
    manager.activeCalibration = SimpleNamespace(phase_name="online_stream_calibration")
    dialog.calibrate_online_stream_button.setText("Stop Calibration")

    dialog.on_readiness_changed(
        {
            "online_stream_calibration": {
                "ready": False,
                "missing": ["Emergence time"],
            }
        }
    )
    qapp.processEvents()

    assert dialog.calibrate_online_stream_button.isEnabled() is True
    assert dialog.calibrate_online_stream_button.text() == "Stop Calibration"

    dialog.deleteLater()


def test_online_stream_debug_widgets_are_created_in_analysis_and_info_panels(monkeypatch, qapp):
    dialog, _manager, _controller = _build_dialog(monkeypatch, qapp)

    assert dialog.online_stream_plot_container.objectName() == "online_stream_plot_container"
    assert dialog.online_stream_flow_chart_view.objectName() == "online_stream_flow_chart_view"
    assert dialog.online_stream_tail_chart_view.objectName() == "online_stream_tail_chart_view"
    assert dialog.online_stream_plot_container.isHidden() is True
    assert dialog.machine_position_group.objectName() == "machine_position_group"
    assert dialog.machine_position_group.parentWidget() is dialog.info_panel

    dialog.deleteLater()


def test_online_stream_debug_payload_shows_plots_and_updates_chart_series(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)
    manager.activeCalibration = SimpleNamespace(phase_name="online_stream_calibration")

    manager.onlineStreamDebugUpdated.emit(
        {
            "phase_name": "online_stream_calibration",
            "subphase": "tail_backtrack",
            "flow_plot": {
                "points": [
                    {"x_us": 650, "y_nl": 6.5, "provisional": False},
                    {"x_us": 850, "y_nl": 8.5, "provisional": True},
                ],
                "current_frame_point": {"x_us": 850, "y_nl": 8.5, "accepted": True},
                "fit": {
                    "status": "ok",
                    "slope_nl_per_us": 0.01,
                    "intercept_nl": 0.0,
                    "x_start_us": 650,
                    "x_end_us": 850,
                },
            },
            "tail_plot": {
                "baseline_width_px": 74.0,
                "scout_points": [{"x_us": 1550, "y_px": 73.0, "provisional": False}],
                "backtrack_points": [{"x_us": 1750, "y_px": 61.0, "provisional": True}],
                "current_frame_point": {
                    "x_us": 1750,
                    "y_px": 61.0,
                    "accepted": True,
                    "mode": "backtrack",
                },
                "tail_start_x_us": 1800,
            },
        }
    )
    qapp.processEvents()

    assert dialog.online_stream_plot_container.isHidden() is False
    assert dialog._online_stream_flow_chart_bundle["primary_series"].count() == 1
    assert dialog._online_stream_flow_chart_bundle["secondary_series"].count() == 1
    assert dialog._online_stream_flow_chart_bundle["current_series"].count() == 1
    assert dialog._online_stream_flow_chart_bundle["reference_series"].count() == 2
    assert dialog._online_stream_tail_chart_bundle["primary_series"].count() == 1
    assert dialog._online_stream_tail_chart_bundle["secondary_series"].count() == 1
    assert dialog._online_stream_tail_chart_bundle["reference_series"].count() == 2
    assert dialog._online_stream_tail_chart_bundle["marker_series"].count() == 2

    dialog.deleteLater()


def test_online_stream_debug_plots_reset_when_nonstream_preview_replaces_center_image(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)
    manager.activeCalibration = SimpleNamespace(phase_name="online_stream_calibration")
    manager.onlineStreamDebugUpdated.emit(
        {
            "phase_name": "online_stream_calibration",
            "subphase": "flow_rate",
            "flow_plot": {
                "points": [{"x_us": 650, "y_nl": 6.5, "provisional": False}],
                "current_frame_point": {"x_us": 650, "y_nl": 6.5, "accepted": True},
                "fit": None,
            },
            "tail_plot": {
                "baseline_width_px": None,
                "scout_points": [],
                "backtrack_points": [],
                "current_frame_point": None,
                "tail_start_x_us": None,
            },
        }
    )
    qapp.processEvents()
    assert dialog.online_stream_plot_container.isHidden() is False

    manager.activeCalibration = None
    dialog.display_analyzed_image(np.full((50, 50), 120, dtype=np.uint8))
    qapp.processEvents()

    assert dialog.online_stream_plot_container.isHidden() is True
    assert dialog._online_stream_flow_chart_bundle["primary_series"].count() == 0
    assert dialog._online_stream_tail_chart_bundle["primary_series"].count() == 0

    dialog.deleteLater()
