from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QObject, Signal

import View
from View import PressurePlotBox
from hardware.profile import CURRENT_PROFILE, LEGACY_PROFILE


class _FakeMachineModel(QObject):
    machine_state_updated = Signal(bool)
    regulation_state_changed = Signal(bool)
    pressure_updated = Signal()

    def __init__(self):
        super().__init__()
        self.regulating_print_pressure = False
        self.print_pulse_width = 3000
        self.refuel_pulse_width = 3000

    def is_connected(self):
        return True

    def motors_are_enabled(self):
        return True

    def get_print_pressure_readings(self):
        return [1.0, 1.1]

    def get_refuel_pressure_readings(self):
        return [0.9, 1.0]

    def get_target_print_pressure(self):
        return 1.0

    def get_target_refuel_pressure(self):
        return 1.0


def _make_main_window(profile):
    return SimpleNamespace(
        color_dict={
            "darker_gray": "#2f2f2f",
            "dark_blue": "#1d4ed8",
            "light_blue": "#60a5fa",
        },
        profile=profile,
        popup_message=lambda *args, **kwargs: None,
    )


def _make_model(machine_model, events):
    return SimpleNamespace(
        machine_model=machine_model,
        reload_droplet_model=Mock(side_effect=lambda: events.append("reload_droplet_model")),
        reload_refuel_model=Mock(side_effect=lambda: events.append("reload_refuel_model")),
    )


def _make_controller(events):
    return SimpleNamespace(
        toggle_regulation=Mock(),
        set_absolute_print_pressure=Mock(),
        set_absolute_refuel_pressure=Mock(),
        set_print_pulse_width=Mock(),
        set_refuel_pulse_width=Mock(),
        disconnect_droplet_camera_signals=Mock(
            side_effect=lambda: events.append("disconnect_droplet_camera_signals")
        ),
        connect_droplet_camera_signals=Mock(
            side_effect=lambda: events.append("connect_droplet_camera_signals")
        ),
        enable_print_profile=Mock(side_effect=lambda: events.append("enable_print_profile")),
    )


def test_current_profile_pressure_box_removes_extra_bottom_buttons(qapp):
    events = []
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE),
        _make_model(_FakeMachineModel(), events),
        _make_controller(events),
    )

    assert box.calibrate_pressure_button.text() == "Calibrate Pressure"
    assert not hasattr(box, "droplet_imager_button")
    assert not hasattr(box, "nozzle_dataset_button")


def test_current_profile_calibrate_pressure_opens_droplet_imager(monkeypatch, qapp):
    events = []
    main_window = _make_main_window(CURRENT_PROFILE)
    model = _make_model(_FakeMachineModel(), events)
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    class _DropletDialog:
        def __init__(self, main_window_arg, model_arg, controller_arg):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            events.append("droplet_dialog_init")

        def exec(self):
            events.append("droplet_dialog_exec")
            return 0

    class _RefuelDialog:
        def __init__(self, *args, **kwargs):
            events.append("refuel_dialog_init")

        def exec(self):
            events.append("refuel_dialog_exec")
            return 0

    monkeypatch.setattr(View.importlib, "reload", lambda module: module)
    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _DropletDialog)
    monkeypatch.setattr(View.CalibrationClasses, "RefuelCameraWindow", _RefuelDialog)

    box.calibrate_pressure()

    assert events == [
        "disconnect_droplet_camera_signals",
        "reload_droplet_model",
        "connect_droplet_camera_signals",
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_exec",
    ]
    model.reload_refuel_model.assert_not_called()


def test_legacy_profile_calibrate_pressure_keeps_mass_calibration(monkeypatch, qapp):
    events = []
    main_window = _make_main_window(LEGACY_PROFILE)
    model = _make_model(_FakeMachineModel(), events)
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    class _MassDialog:
        def __init__(self, main_window_arg, model_arg, controller_arg):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            events.append("mass_dialog_init")

        def exec(self):
            events.append("mass_dialog_exec")
            return 0

    class _DropletDialog:
        def __init__(self, *args, **kwargs):
            events.append("droplet_dialog_init")

        def exec(self):
            events.append("droplet_dialog_exec")
            return 0

    monkeypatch.setattr(View, "MassCalibrationDialog", _MassDialog)
    monkeypatch.setattr(View.importlib, "reload", lambda module: module)
    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _DropletDialog)

    box.calibrate_pressure()

    assert events == ["mass_dialog_init", "mass_dialog_exec"]
    controller.disconnect_droplet_camera_signals.assert_not_called()
    controller.connect_droplet_camera_signals.assert_not_called()
    controller.enable_print_profile.assert_not_called()
    model.reload_droplet_model.assert_not_called()
