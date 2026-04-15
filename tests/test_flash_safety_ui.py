from types import SimpleNamespace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QPushButton

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.View import DropletImagingDialog, NozzlePositionDatasetCaptureWindow


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
        if self.flash_fault_reason == "line_stuck_high":
            return "Trigger line stayed high for too long"
        if self.flash_fault_reason == "retrigger_while_high":
            return "Repeated trigger while line was still high"
        if self.flash_fault_reason == "line_high_on_arm":
            return "Trigger line high while arming"
        return "None"


def _make_calibration_manager_stub():
    return SimpleNamespace(
        analyzedImageUpdated=SignalStub(),
        calibrationStageChanged=SignalStub(),
        calibrationCompleted=SignalStub(),
        calibrationQueueCompleted=SignalStub(),
        calibrationError=SignalStub(),
        position_diff_dict_signal=SignalStub(),
        characterizationSummaryUpdated=SignalStub(),
        readinessChanged=SignalStub(),
        streamCaptureStateChanged=SignalStub(),
        streamCalibrationSequenceStateChanged=SignalStub(),
        dropletCalibrationSequenceStateChanged=SignalStub(),
        clear_calibration_memory_ui_recommendation_state=lambda: None,
        get_record_mode_enabled=lambda: True,
        get_calibration_memory_enabled=lambda: True,
        _emit_readiness=lambda: None,
        activeCalibration=None,
        calibration_queue=[],
        is_pulsewidth_sweep_active=lambda: False,
        is_stream_gravimetric_capture_busy=lambda: False,
        get_stream_gravimetric_capture_state=lambda: {"status": "idle"},
        is_stream_calibration_sequence_busy=lambda: False,
        has_open_stream_calibration_sequence=lambda: False,
        get_stream_calibration_sequence_state=lambda: {"status": "idle"},
        is_droplet_calibration_sequence_busy=lambda: False,
        has_open_droplet_calibration_sequence=lambda: False,
        get_droplet_calibration_sequence_state=lambda: {"status": "idle"},
    )


def _build_droplet_dialog(monkeypatch, qapp):
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
    ):
        monkeypatch.setattr(DropletImagingDialog, method_name, lambda self, *args, **kwargs: None)

    cam = _DropletCameraModelStub()
    model = SimpleNamespace(
        droplet_camera_model=cam,
        calibration_manager=_make_calibration_manager_stub(),
        machine_model=SimpleNamespace(
            get_print_pressure_bounds=lambda: (0.10, 5.00),
            get_print_pulse_width=lambda: 1400,
            get_current_print_pressure=lambda: 0.80,
        ),
    )
    controller = SimpleNamespace(
        start_read_camera=lambda: None,
        capture_droplet_image=lambda: None,
        start_droplet_calibration_sequence=lambda: None,
        begin_droplet_calibration_sequence_gripper_preamble=lambda: (True, ""),
        begin_droplet_calibration_sequence_gripper_restore=lambda: (True, ""),
    )
    dialog = DropletImagingDialog(SimpleNamespace(color_dict={}), model, controller)
    qapp.processEvents()
    return dialog, cam


def test_droplet_imager_disables_manual_flash_and_stops_timer_on_fault(monkeypatch, qapp):
    dialog, cam = _build_droplet_dialog(monkeypatch, qapp)

    dialog.on_readiness_changed(
        {
            "online_stream_calibration": {
                "ready": False,
                "missing": ["Emergence time"],
            }
        }
    )

    dialog.camera_timer.start(50)
    dialog.capturing = True
    cam.flash_session_armed = False
    cam.flash_fault_latched = True
    cam.flash_fault_reason = "line_stuck_high"

    dialog.update_flash_info()

    assert dialog.flash_button.isEnabled() is False
    assert dialog.flash_delay_spinbox.isEnabled() is False
    assert dialog.print_pulse_width_spinbox.isEnabled() is False
    assert dialog.calibrate_online_stream_button.isEnabled() is False
    assert dialog.calibrate_all_stream_button.isEnabled() is False
    assert dialog.calibrate_all_button.isEnabled() is False
    assert dialog.camera_timer.isActive() is False
    assert "Flash safety fault latched" in dialog.flash_safety_label.text()
    assert "Close and reopen the imager" in dialog.flash_safety_label.text()

    cam.flash_fault_latched = False
    cam.flash_fault_reason = ""
    dialog.update_flash_info()

    assert dialog.flash_delay_spinbox.isEnabled() is True
    assert dialog.print_pulse_width_spinbox.isEnabled() is True
    assert dialog.calibrate_online_stream_button.isEnabled() is False
    assert dialog.calibrate_all_stream_button.isEnabled() is True
    assert dialog.calibrate_all_button.isEnabled() is True
    assert "Emergence time" in dialog.calibrate_online_stream_button.toolTip()

    dialog.on_readiness_changed(
        {
            "online_stream_calibration": {
                "ready": True,
                "missing": [],
            }
        }
    )

    assert dialog.calibrate_online_stream_button.isEnabled() is True
    assert dialog.calibrate_all_stream_button.isEnabled() is True
    assert dialog.calibrate_all_button.isEnabled() is True

    dialog.deleteLater()


def test_flash_fault_disables_shared_nozzle_buttons_in_both_tabs(monkeypatch, qapp):
    dialog, cam = _build_droplet_dialog(monkeypatch, qapp)

    cam.flash_fault_latched = True
    cam.flash_fault_reason = "line_stuck_high"
    dialog.update_flash_info()
    qapp.processEvents()

    assert dialog.calibrate_nozzle_button.isEnabled() is False
    assert dialog.calibrate_nozzle_stream_button.isEnabled() is False
    assert dialog.calibrate_focus_button.isEnabled() is False
    assert dialog.calibrate_focus_stream_button.isEnabled() is False
    assert dialog.calibrate_emergence_button.isEnabled() is False
    assert dialog.calibrate_emergence_stream_button.isEnabled() is False

    dialog.deleteLater()


def test_flash_fault_keeps_active_online_stream_stop_button_enabled(monkeypatch, qapp):
    dialog, cam = _build_droplet_dialog(monkeypatch, qapp)
    dialog.model.calibration_manager.activeCalibration = SimpleNamespace(
        phase_name="online_stream_calibration"
    )
    dialog.calibrate_online_stream_button.setText("Stop Calibration")
    dialog.on_readiness_changed(
        {
            "online_stream_calibration": {
                "ready": True,
                "missing": [],
            }
        }
    )

    cam.flash_fault_latched = True
    cam.flash_fault_reason = "line_stuck_high"
    dialog.update_flash_info()

    assert dialog.calibrate_online_stream_button.isEnabled() is True
    assert dialog.calibrate_online_stream_button.text() == "Stop Calibration"
    assert dialog.calibrate_all_stream_button.isEnabled() is False

    dialog.deleteLater()


def test_nozzle_dataset_capture_buttons_stay_disabled_while_fault_is_latched(qapp):
    cam = _DropletCameraModelStub()
    cam.flash_fault_latched = True
    cam.flash_fault_reason = "retrigger_while_high"
    window = SimpleNamespace(
        model=SimpleNamespace(droplet_camera_model=cam),
        capture_preview_btn=QPushButton(),
        capture_pair_btn=QPushButton(),
        reject_last_btn=QPushButton(),
        flash_safety_label=QLabel(),
        _capture_inflight=False,
    )
    window._is_flash_fault_latched = (
        NozzlePositionDatasetCaptureWindow._is_flash_fault_latched.__get__(
            window, NozzlePositionDatasetCaptureWindow
        )
    )
    window._flash_fault_reason_text = (
        NozzlePositionDatasetCaptureWindow._flash_fault_reason_text.__get__(
            window, NozzlePositionDatasetCaptureWindow
        )
    )
    window._set_buttons_enabled = (
        NozzlePositionDatasetCaptureWindow._set_buttons_enabled.__get__(
            window, NozzlePositionDatasetCaptureWindow
        )
    )
    window._apply_flash_safety_state = (
        NozzlePositionDatasetCaptureWindow._apply_flash_safety_state.__get__(
            window, NozzlePositionDatasetCaptureWindow
        )
    )

    window._apply_flash_safety_state()

    assert window.capture_preview_btn.isEnabled() is False
    assert window.capture_pair_btn.isEnabled() is False
    assert window.reject_last_btn.isEnabled() is False
    assert "Flash safety fault latched" in window.flash_safety_label.text()
