from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.View import CalibrationModePreflightDialog, DropletImagingDialog


_PRINT_PROFILES = [
    {
        "id": "water_droplet",
        "name": "Water - droplet",
        "mode": "droplet",
        "material": "water",
        "print_pressure": 0.6,
        "refuel_pressure": 0.3,
        "print_pulse_width": 1300,
        "refuel_pulse_width": 3000,
    },
    {
        "id": "water_stream",
        "name": "Water - stream",
        "mode": "stream",
        "material": "water",
        "print_pressure": 0.8,
        "refuel_pressure": 0.8,
        "print_pulse_width": 2500,
        "refuel_pulse_width": 6000,
    },
]


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
        self.streamCalibrationSequenceStateChanged = SignalStub()
        self.dropletCalibrationSequenceStateChanged = SignalStub()
        self.activeCalibration = None
        self.calibration_queue = []
        self.state = {"status": "idle"}
        self.sequence_state = {"status": "idle"}
        self.droplet_sequence_state = {"status": "idle"}

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

    def is_stream_calibration_sequence_busy(self):
        return str(self.sequence_state.get("status") or "idle") in {
            "pending_gripper_refresh",
            "refreshing_gripper",
            "suspending_gripper_refresh",
            "running",
            "pending_gripper_restore",
            "restoring_gripper_refresh",
        }

    def has_open_stream_calibration_sequence(self):
        return str(self.sequence_state.get("status") or "idle") != "idle"

    def get_stream_calibration_sequence_state(self):
        return dict(self.sequence_state)

    def is_droplet_calibration_sequence_busy(self):
        return str(self.droplet_sequence_state.get("status") or "idle") in {
            "pending_gripper_refresh",
            "refreshing_gripper",
            "suspending_gripper_refresh",
            "running",
            "pending_gripper_restore",
            "restoring_gripper_refresh",
        }

    def has_open_droplet_calibration_sequence(self):
        return str(self.droplet_sequence_state.get("status") or "idle") != "idle"

    def get_droplet_calibration_sequence_state(self):
        return dict(self.droplet_sequence_state)


class _MachineModelStub:
    def __init__(self, *, print_pulse_width=1400):
        self.print_pulse_width = int(print_pulse_width)

    def get_print_pressure_bounds(self):
        return (0.10, 5.00)

    def get_print_pulse_width(self):
        return int(self.print_pulse_width)

    def get_current_print_pressure(self):
        return 0.80


class _ControllerStub:
    def __init__(self, manager=None, *, preflight_enabled=False):
        self.manager = manager
        self.model = None
        self.preflight_enabled = bool(preflight_enabled)
        self.start_online_stream_calls = 0
        self.start_stream_calibration_sequence_calls = 0
        self.start_droplet_calibration_sequence_calls = 0
        self.start_droplet_calibration_sequence_modes = []
        self.start_nozzle_calls = 0
        self.stop_calibration_calls = 0
        self.apply_print_profile_calls = []
        self.set_print_pulse_width_calls = []

    def start_read_camera(self):
        return None

    def capture_droplet_image(self, throughput_mode=False):
        return None

    def start_nozzle_calibration(self):
        self.start_nozzle_calls += 1

    def start_online_stream_calibration(self):
        self.start_online_stream_calls += 1

    def start_stream_calibration_sequence(self):
        self.start_stream_calibration_sequence_calls += 1
        if self.manager is not None:
            self.manager.sequence_state["status"] = "pending_gripper_refresh"
            self.manager.streamCalibrationSequenceStateChanged.emit(
                dict(self.manager.sequence_state)
            )

    def begin_stream_calibration_sequence_gripper_preamble(self):
        if self.manager is not None:
            self.manager.sequence_state["status"] = "running"
            self.manager.streamCalibrationSequenceStateChanged.emit(
                dict(self.manager.sequence_state)
            )
        return True, ""

    def begin_stream_calibration_sequence_gripper_restore(self):
        if self.manager is not None:
            self.manager.sequence_state["status"] = "restoring_gripper_refresh"
            self.manager.streamCalibrationSequenceStateChanged.emit(
                dict(self.manager.sequence_state)
            )
        return True, ""

    def start_droplet_calibration_sequence(self, *, pressure_scan_mode="band"):
        self.start_droplet_calibration_sequence_calls += 1
        self.start_droplet_calibration_sequence_modes.append(str(pressure_scan_mode))
        if self.manager is not None:
            self.manager.droplet_sequence_state["status"] = "pending_gripper_refresh"
            self.manager.droplet_sequence_state["pressure_scan_mode"] = str(pressure_scan_mode)
            self.manager.dropletCalibrationSequenceStateChanged.emit(
                dict(self.manager.droplet_sequence_state)
            )

    def begin_droplet_calibration_sequence_gripper_preamble(self):
        if self.manager is not None:
            self.manager.droplet_sequence_state["status"] = "running"
            self.manager.dropletCalibrationSequenceStateChanged.emit(
                dict(self.manager.droplet_sequence_state)
            )
        return True, ""

    def begin_droplet_calibration_sequence_gripper_restore(self):
        if self.manager is not None:
            self.manager.droplet_sequence_state["status"] = "restoring_gripper_refresh"
            self.manager.dropletCalibrationSequenceStateChanged.emit(
                dict(self.manager.droplet_sequence_state)
            )
        return True, ""

    def stop_calibration(self):
        self.stop_calibration_calls += 1

    def get_calibration_mode_preflight(self, requested_mode):
        if not self.preflight_enabled:
            return {
                "ok": True,
                "code": "ok",
                "requested_mode": str(requested_mode or "droplet"),
                "head_mode": str(requested_mode or "droplet"),
                "current_print_pulse_width_us": None,
                "expected_print_pulse_width_us": None,
                "matching_profiles": [],
                "message": "",
            }
        requested_mode = str(requested_mode or "droplet").strip().lower()
        expected = 2500 if requested_mode == "stream" else 1300
        current = self.model.machine_model.get_print_pulse_width()
        printer_head = self.model.rack_model.get_gripper_printer_head()
        matching_profiles = [
            dict(profile)
            for profile in list(getattr(self.model, "print_profiles", []) or [])
            if str(profile.get("mode") or "").strip().lower() == requested_mode
            and int(profile.get("print_pulse_width") or 0) == expected
        ]
        if printer_head is None:
            return {
                "ok": False,
                "code": "no_printer_head",
                "requested_mode": requested_mode,
                "head_mode": None,
                "current_print_pulse_width_us": current,
                "expected_print_pulse_width_us": expected,
                "matching_profiles": matching_profiles,
                "message": "No printer head is loaded.",
            }
        head_mode = str(printer_head.get_printing_mode()).strip().lower()
        if head_mode != requested_mode:
            return {
                "ok": False,
                "code": "head_mode_mismatch",
                "requested_mode": requested_mode,
                "head_mode": head_mode,
                "current_print_pulse_width_us": current,
                "expected_print_pulse_width_us": expected,
                "matching_profiles": matching_profiles,
                "message": "Head mode does not match.",
            }
        if current != expected:
            return {
                "ok": False,
                "code": "pulse_width_mismatch",
                "requested_mode": requested_mode,
                "head_mode": head_mode,
                "current_print_pulse_width_us": current,
                "expected_print_pulse_width_us": expected,
                "matching_profiles": matching_profiles,
                "message": "Pulse width does not match.",
            }
        return {
            "ok": True,
            "code": "ok",
            "requested_mode": requested_mode,
            "head_mode": head_mode,
            "current_print_pulse_width_us": current,
            "expected_print_pulse_width_us": expected,
            "matching_profiles": matching_profiles,
            "message": "",
        }

    def apply_print_profile(self, profile, callback=None):
        profile = dict(profile)
        self.apply_print_profile_calls.append(profile)
        self.model.machine_model.print_pulse_width = int(profile["print_pulse_width"])
        if callback is not None:
            callback()
        return True

    def set_print_pulse_width(self, pulse_width, *, manual=False, handler=None):
        self.set_print_pulse_width_calls.append(
            {"pulse_width": int(pulse_width), "manual": bool(manual)}
        )
        self.model.machine_model.print_pulse_width = int(pulse_width)
        if handler is not None:
            handler()
        return True


def _build_dialog(
    monkeypatch,
    qapp,
    *,
    printing_mode=None,
    print_pulse_width=1400,
    preflight_enabled=False,
    print_profiles=None,
    **dialog_kwargs,
):
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

    manager = _CalibrationManagerStub()
    controller = _ControllerStub(manager, preflight_enabled=preflight_enabled)
    printer_head = (
        SimpleNamespace(get_printing_mode=lambda mode=printing_mode: mode)
        if printing_mode is not None
        else None
    )
    machine_model = _MachineModelStub(print_pulse_width=print_pulse_width)
    model = SimpleNamespace(
        droplet_camera_model=_DropletCameraModelStub(),
        calibration_manager=manager,
        machine_model=machine_model,
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: printer_head),
        print_profiles=list(print_profiles if print_profiles is not None else _PRINT_PROFILES),
    )
    controller.model = model
    dialog = DropletImagingDialog(SimpleNamespace(color_dict={}, model=model), model, controller, **dialog_kwargs)
    qapp.processEvents()
    return dialog, manager, controller


def test_droplet_imaging_dialog_defaults_to_droplet_tab_without_stream_head(monkeypatch, qapp):
    dialog, _manager, _controller = _build_dialog(monkeypatch, qapp)

    assert dialog.calibration_tabs.currentWidget() is dialog.droplet_tab

    dialog.deleteLater()


def test_droplet_imaging_dialog_defaults_to_stream_tab_for_stream_head(monkeypatch, qapp):
    dialog, _manager, _controller = _build_dialog(monkeypatch, qapp, printing_mode="stream")

    assert dialog.calibration_tabs.currentWidget() is dialog.stream_tab

    dialog.deleteLater()


def test_droplet_imaging_dialog_opens_optics_tab_in_service_mode(monkeypatch, qapp):
    dialog, _manager, _controller = _build_dialog(
        monkeypatch,
        qapp,
        service_mode=True,
        initial_tab="optics",
    )

    assert dialog.calibration_tabs.currentWidget() is dialog.optics_tab

    dialog.deleteLater()


def test_online_stream_button_is_created_and_reset_label_is_stable(monkeypatch, qapp):
    dialog, _manager, _controller = _build_dialog(monkeypatch, qapp)

    assert dialog.calibrate_online_stream_button.text() == "Calibrate Stream Volume"

    dialog.calibrate_online_stream_button.setText("Stop Calibration")
    dialog.reset_calibration_buttons()

    assert dialog.calibrate_online_stream_button.text() == "Calibrate Stream Volume"

    dialog.deleteLater()


def test_stream_calibrate_all_button_is_created_and_reset_label_is_stable(monkeypatch, qapp):
    dialog, _manager, _controller = _build_dialog(monkeypatch, qapp)

    assert dialog.calibrate_all_stream_button.text() == "Calibrate All"

    dialog.calibrate_all_stream_button.setText("Stop Calibration")
    dialog.reset_calibration_buttons()

    assert dialog.calibrate_all_stream_button.text() == "Calibrate All"

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


def test_stream_preflight_ok_starts_without_dialog(monkeypatch, qapp):
    dialog, _manager, controller = _build_dialog(
        monkeypatch,
        qapp,
        printing_mode="stream",
        print_pulse_width=2500,
        preflight_enabled=True,
    )
    dialog_calls = []
    monkeypatch.setattr(
        DropletImagingDialog,
        "_run_calibration_mode_preflight_dialog",
        lambda self, preflight: dialog_calls.append(dict(preflight))
        or (CalibrationModePreflightDialog.ACTION_CANCEL, None),
    )

    dialog.calibrate_online_stream_button.click()
    qapp.processEvents()

    assert dialog_calls == []
    assert controller.start_online_stream_calls == 1
    assert dialog.calibrate_online_stream_button.text() == "Stop Calibration"

    dialog.deleteLater()


def test_stream_preflight_applies_matching_profile_then_starts(monkeypatch, qapp):
    dialog, _manager, controller = _build_dialog(
        monkeypatch,
        qapp,
        printing_mode="stream",
        print_pulse_width=1300,
        preflight_enabled=True,
    )

    def choose_profile(self, preflight):
        return (
            CalibrationModePreflightDialog.ACTION_APPLY_PROFILE,
            preflight["matching_profiles"][0],
        )

    monkeypatch.setattr(
        DropletImagingDialog,
        "_run_calibration_mode_preflight_dialog",
        choose_profile,
    )

    dialog.calibrate_online_stream_button.click()
    qapp.processEvents()
    qapp.processEvents()

    assert controller.apply_print_profile_calls == [_PRINT_PROFILES[1]]
    assert dialog.model.machine_model.get_print_pulse_width() == 2500
    assert controller.start_online_stream_calls == 1
    assert dialog.calibrate_online_stream_button.text() == "Stop Calibration"

    dialog.deleteLater()


def test_stream_preflight_review_settings_does_not_start(monkeypatch, qapp):
    dialog, _manager, controller = _build_dialog(
        monkeypatch,
        qapp,
        printing_mode="stream",
        print_pulse_width=1300,
        preflight_enabled=True,
    )
    monkeypatch.setattr(
        DropletImagingDialog,
        "_run_calibration_mode_preflight_dialog",
        lambda self, preflight: (CalibrationModePreflightDialog.ACTION_REVIEW_SETTINGS, None),
    )

    dialog.calibrate_online_stream_button.click()
    qapp.processEvents()

    assert controller.start_online_stream_calls == 0
    assert controller.apply_print_profile_calls == []
    assert dialog.acquisition_controls_toggle.isChecked() is True
    assert dialog.calibrate_online_stream_button.text() == "Calibrate Stream Volume"

    dialog.deleteLater()


def test_stream_preflight_continue_anyway_starts_without_profile(monkeypatch, qapp):
    dialog, manager, controller = _build_dialog(
        monkeypatch,
        qapp,
        printing_mode="stream",
        print_pulse_width=1300,
        preflight_enabled=True,
    )
    monkeypatch.setattr(
        DropletImagingDialog,
        "_run_calibration_mode_preflight_dialog",
        lambda self, preflight: (CalibrationModePreflightDialog.ACTION_CONTINUE_ANYWAY, None),
    )

    dialog.calibrate_online_stream_button.click()
    qapp.processEvents()

    assert controller.apply_print_profile_calls == []
    assert controller.start_online_stream_calls == 1
    assert manager.calibrationStageChanged.calls
    assert "Continuing calibration despite" in manager.calibrationStageChanged.calls[0][0][0]

    dialog.deleteLater()


def test_droplet_preflight_head_mismatch_switches_to_stream_tab(monkeypatch, qapp):
    dialog, _manager, controller = _build_dialog(
        monkeypatch,
        qapp,
        printing_mode="stream",
        print_pulse_width=1300,
        preflight_enabled=True,
    )
    dialog.calibration_tabs.setCurrentWidget(dialog.droplet_tab)
    monkeypatch.setattr(
        DropletImagingDialog,
        "_run_calibration_mode_preflight_dialog",
        lambda self, preflight: (CalibrationModePreflightDialog.ACTION_SWITCH_TAB, None),
    )

    dialog.calibrate_all_button.click()
    qapp.processEvents()

    assert controller.start_droplet_calibration_sequence_calls == 0
    assert dialog.calibration_tabs.currentWidget() is dialog.stream_tab
    assert dialog.calibrate_all_button.text() == "Calibrate All"

    dialog.deleteLater()


def test_stream_calibrate_all_toggle_starts_and_stops_via_controller(monkeypatch, qapp):
    dialog, manager, controller = _build_dialog(monkeypatch, qapp)

    dialog.calibrate_all_stream_button.click()
    qapp.processEvents()

    assert controller.start_stream_calibration_sequence_calls == 1
    assert dialog.calibrate_all_stream_button.text() == "Stop Calibration"

    manager.sequence_state["status"] = "running"
    dialog.calibrate_all_stream_button.click()
    qapp.processEvents()

    assert controller.stop_calibration_calls == 1
    assert dialog.calibrate_all_stream_button.text() == "Stop Calibration"

    manager.sequence_state["status"] = "idle"
    dialog._refresh_manual_control_lock_state()
    qapp.processEvents()

    assert dialog.calibrate_all_stream_button.text() == "Calibrate All"

    dialog.deleteLater()


def test_droplet_calibrate_all_toggle_starts_and_stops_via_controller(monkeypatch, qapp):
    dialog, manager, controller = _build_dialog(monkeypatch, qapp)

    dialog.calibrate_all_button.click()
    qapp.processEvents()

    assert controller.start_droplet_calibration_sequence_calls == 1
    assert controller.start_droplet_calibration_sequence_modes == ["band"]
    assert dialog.calibrate_all_button.text() == "Stop Calibration"

    manager.droplet_sequence_state["status"] = "running"
    dialog.calibrate_all_button.click()
    qapp.processEvents()

    assert controller.stop_calibration_calls == 1
    assert controller.start_droplet_calibration_sequence_calls == 1
    assert dialog.calibrate_all_button.text() == "Stop Calibration"

    manager.droplet_sequence_state["status"] = "idle"
    dialog._refresh_manual_control_lock_state()
    qapp.processEvents()

    assert dialog.calibrate_all_button.text() == "Calibrate All"

    dialog.deleteLater()


def test_droplet_calibrate_all_single_pressure_mode_passes_to_controller(monkeypatch, qapp):
    dialog, _manager, controller = _build_dialog(monkeypatch, qapp)

    dialog.calibrate_all_pressure_single_radio.setChecked(True)
    dialog.calibrate_all_button.click()
    qapp.processEvents()

    assert controller.start_droplet_calibration_sequence_calls == 1
    assert controller.start_droplet_calibration_sequence_modes == ["single_candidate"]

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


def test_stream_calibrate_all_ignores_emergence_only_readiness_blockers(monkeypatch, qapp):
    dialog, _manager, _controller = _build_dialog(monkeypatch, qapp)

    dialog.on_readiness_changed(
        {
            "online_stream_calibration": {
                "ready": False,
                "missing": [
                    "Emergence time",
                    "Emergence-derived nozzle center (image coords)",
                ],
            }
        }
    )
    qapp.processEvents()

    assert dialog.calibrate_all_stream_button.isEnabled() is True
    assert dialog.calibrate_all_stream_button.toolTip() == ""

    dialog.on_readiness_changed(
        {
            "online_stream_calibration": {
                "ready": False,
                "missing": [
                    "Emergence time",
                    "Active printer head",
                ],
            }
        }
    )
    qapp.processEvents()

    assert dialog.calibrate_all_stream_button.isEnabled() is False
    assert "Active printer head" in dialog.calibrate_all_stream_button.toolTip()

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
    assert dialog.calibrate_all_stream_button.isEnabled() is False
    assert "flash safety fault" in dialog.calibrate_all_stream_button.toolTip().lower()

    cam.flash_fault_latched = False
    cam.flash_fault_reason = ""
    dialog.update_flash_info()
    qapp.processEvents()

    assert manager.activeCalibration is None
    assert dialog.calibrate_online_stream_button.isEnabled() is True
    assert dialog.calibrate_online_stream_button.toolTip() == ""
    assert dialog.calibrate_all_stream_button.isEnabled() is True
    assert dialog.calibrate_all_stream_button.toolTip() == ""

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
    assert dialog.calibrate_all_stream_button.isEnabled() is False
    assert "stream gravimetric capture" in dialog.calibrate_all_stream_button.toolTip().lower()

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
    assert dialog.flash_delay_spinbox.isEnabled() is False
    assert dialog.print_pulse_width_spinbox.isEnabled() is False
    assert dialog.flash_button.isEnabled() is False

    manager.activeCalibration = None
    dialog._refresh_manual_control_lock_state()
    qapp.processEvents()

    assert dialog.calibration_tabs.isTabEnabled(0) is True
    assert dialog.calibration_tabs.isTabEnabled(1) is True
    assert dialog.calibration_tabs.isTabEnabled(2) is True
    assert dialog.flash_delay_spinbox.isEnabled() is True
    assert dialog.print_pulse_width_spinbox.isEnabled() is True
    assert dialog.flash_button.isEnabled() is True

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


def test_tabs_lock_during_stream_calibration_sequence_and_unlock_when_idle(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)

    dialog.calibration_tabs.setCurrentIndex(1)
    qapp.processEvents()

    manager.sequence_state["status"] = "pending_gripper_restore"
    dialog._refresh_manual_control_lock_state()
    qapp.processEvents()

    assert dialog.calibration_tabs.isTabEnabled(0) is False
    assert dialog.calibration_tabs.isTabEnabled(1) is True
    assert dialog.calibration_tabs.isTabEnabled(2) is False

    manager.sequence_state["status"] = "idle"
    dialog._refresh_manual_control_lock_state()
    qapp.processEvents()

    assert dialog.calibration_tabs.isTabEnabled(0) is True
    assert dialog.calibration_tabs.isTabEnabled(1) is True
    assert dialog.calibration_tabs.isTabEnabled(2) is True

    dialog.deleteLater()


def test_tabs_lock_during_droplet_calibration_sequence_and_unlock_when_idle(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)

    dialog.calibration_tabs.setCurrentIndex(0)
    qapp.processEvents()

    manager.droplet_sequence_state["status"] = "pending_gripper_restore"
    dialog._refresh_manual_control_lock_state()
    qapp.processEvents()

    assert dialog.calibration_tabs.isTabEnabled(0) is True
    assert dialog.calibration_tabs.isTabEnabled(1) is False
    assert dialog.calibration_tabs.isTabEnabled(2) is False

    manager.droplet_sequence_state["status"] = "idle"
    dialog._refresh_manual_control_lock_state()
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
    assert dialog.machine_position_group.parentWidget() is dialog.machine_position_section_content

    dialog.deleteLater()


def test_stream_calibration_sequence_keeps_stop_button_enabled_through_restore(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)

    manager.sequence_state["status"] = "running"
    manager.streamCalibrationSequenceStateChanged.emit(dict(manager.sequence_state))
    qapp.processEvents()

    assert dialog.calibrate_all_stream_button.isEnabled() is True
    assert dialog.calibrate_all_stream_button.text() == "Stop Calibration"

    manager.sequence_state["status"] = "pending_gripper_restore"
    manager.streamCalibrationSequenceStateChanged.emit(dict(manager.sequence_state))
    qapp.processEvents()

    assert dialog.calibrate_all_stream_button.isEnabled() is True
    assert dialog.calibrate_all_stream_button.text() == "Stop Calibration"

    manager.sequence_state["status"] = "idle"
    manager.streamCalibrationSequenceStateChanged.emit(dict(manager.sequence_state))
    qapp.processEvents()

    assert dialog.calibrate_all_stream_button.text() == "Calibrate All"

    dialog.deleteLater()


def test_droplet_calibration_sequence_keeps_stop_button_enabled_through_restore(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)

    manager.droplet_sequence_state["status"] = "running"
    manager.dropletCalibrationSequenceStateChanged.emit(dict(manager.droplet_sequence_state))
    qapp.processEvents()

    assert dialog.calibrate_all_button.isEnabled() is True
    assert dialog.calibrate_all_button.text() == "Stop Calibration"

    manager.droplet_sequence_state["status"] = "pending_gripper_restore"
    manager.dropletCalibrationSequenceStateChanged.emit(dict(manager.droplet_sequence_state))
    qapp.processEvents()

    assert dialog.calibrate_all_button.isEnabled() is True
    assert dialog.calibrate_all_button.text() == "Stop Calibration"

    manager.droplet_sequence_state["status"] = "idle"
    manager.dropletCalibrationSequenceStateChanged.emit(dict(manager.droplet_sequence_state))
    qapp.processEvents()

    assert dialog.calibrate_all_button.text() == "Calibrate All"

    dialog.deleteLater()


def test_droplet_calibration_sequence_disables_manual_quick_controls(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)

    manager.droplet_sequence_state["status"] = "running"
    dialog._refresh_manual_control_lock_state()
    qapp.processEvents()

    assert dialog.flash_delay_spinbox.isEnabled() is False
    assert dialog.print_pulse_width_spinbox.isEnabled() is False
    assert dialog.flash_button.isEnabled() is False

    manager.droplet_sequence_state["status"] = "idle"
    dialog._refresh_manual_control_lock_state()
    qapp.processEvents()

    assert dialog.flash_delay_spinbox.isEnabled() is True
    assert dialog.print_pulse_width_spinbox.isEnabled() is True
    assert dialog.flash_button.isEnabled() is True

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


def test_online_stream_debug_payload_draws_segmented_tail_overlay(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)
    manager.activeCalibration = SimpleNamespace(phase_name="online_stream_calibration")

    manager.onlineStreamDebugUpdated.emit(
        {
            "phase_name": "online_stream_calibration",
            "subphase": "tail_backtrack",
            "flow_plot": {"points": [], "current_frame_point": None, "fit": None},
            "tail_plot": {
                "baseline_width_px": 74.0,
                "scout_points": [{"x_us": 1550, "y_px": 73.0, "provisional": False}],
                "backtrack_points": [{"x_us": 1600, "y_px": 70.0, "provisional": False}],
                "current_frame_point": None,
                "tail_start_x_us": 1650,
                "width_trace_source_window_step_index": 3,
                "segmented_tail": {
                    "status": "ok",
                    "model_name": "three_break_two_break_midpoint",
                    "tail_start_source": "three_two_midpoint",
                    "tail_start_delay_from_emergence_us": 1625,
                    "segmented_tail_source_window_step_index": 3,
                    "predicted_volume_nl": 29.1875,
                    "runtime_predicted_volume_nl": 30.125,
                    "knee_delay_from_emergence_us": 1700,
                    "second_knee_delay_from_emergence_us": 1750,
                    "three_break_tail_start_delay_from_emergence_us": 1600,
                    "two_break_tail_start_delay_from_emergence_us": 1650,
                    "fit_points": [
                        {"delay_from_emergence_us": 1550, "fitted_width_px": 73.5},
                        {"delay_from_emergence_us": 1600, "fitted_width_px": 70.0},
                        {"delay_from_emergence_us": 1650, "fitted_width_px": 66.0},
                    ],
                },
            },
        }
    )
    qapp.processEvents()

    bundle = dialog._online_stream_tail_chart_bundle
    assert bundle["marker_series"].count() == 2
    assert bundle["segmented_fit_series"].count() == 3
    assert bundle["segmented_marker_series"].count() == 2
    assert bundle["segmented_knee_series"].count() == 2
    assert bundle["segmented_second_knee_series"].count() == 2
    assert bundle["segmented_bracket_left_series"].count() == 2
    assert bundle["segmented_bracket_right_series"].count() == 2
    assert "segmented 1625 us" in bundle["chart"].title()
    assert "segmented window step=3" in bundle["chart"].title()
    assert "trace window step=3" in bundle["chart"].title()
    assert "runtime vol 30.12 nL" in bundle["chart"].title()
    assert "segmented vol 29.19 nL" in bundle["chart"].title()

    dialog.deleteLater()


def test_online_stream_debug_payload_shows_segmented_tail_busy_title(monkeypatch, qapp):
    dialog, manager, _controller = _build_dialog(monkeypatch, qapp)
    manager.activeCalibration = SimpleNamespace(phase_name="online_stream_calibration")

    manager.onlineStreamDebugUpdated.emit(
        {
            "phase_name": "online_stream_calibration",
            "subphase": "tail_segmented_fit",
            "flow_plot": {"points": [], "current_frame_point": None, "fit": None},
            "tail_plot": {
                "baseline_width_px": 74.0,
                "scout_points": [{"x_us": 1550, "y_px": 73.0, "provisional": False}],
                "backtrack_points": [],
                "current_frame_point": None,
                "tail_start_x_us": None,
                "segmented_tail": {
                    "status": "running",
                    "fit_status": "running",
                },
            },
        }
    )
    qapp.processEvents()

    bundle = dialog._online_stream_tail_chart_bundle
    assert "segmented fit running" in bundle["chart"].title()
    assert bundle["segmented_fit_series"].count() == 0
    assert bundle["segmented_marker_series"].count() == 0

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
