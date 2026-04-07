from types import SimpleNamespace

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs(force=True)

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


class _CalibrationManagerStub:
    def __init__(self):
        self.analyzedImageUpdated = SignalStub()
        self.calibrationStageChanged = SignalStub()
        self.calibrationCompleted = SignalStub()
        self.calibrationQueueCompleted = SignalStub()
        self.calibrationError = SignalStub()
        self.position_diff_dict_signal = SignalStub()
        self.characterizationSummaryUpdated = SignalStub()
        self.readinessChanged = SignalStub()
        self.activeCalibration = None
        self.calibration_queue = []

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
        return False


class _ControllerStub:
    def __init__(self):
        self.start_online_stream_calls = 0
        self.stop_calibration_calls = 0

    def start_read_camera(self):
        return None

    def capture_droplet_image(self, throughput_mode=False):
        return None

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
