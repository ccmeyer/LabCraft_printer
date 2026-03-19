from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

import View
from View import PressurePlotBox
from hardware.profile import CURRENT_PROFILE, LEGACY_PROFILE


class _FakeMachineModel(QObject):
    machine_state_updated = Signal(bool)
    regulation_state_changed = Signal(bool)
    pressure_updated = Signal()

    def __init__(self, *, regulating_print_pressure=False, current_location="camera"):
        super().__init__()
        self.regulating_print_pressure = regulating_print_pressure
        self.current_location = current_location
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

    def get_current_location(self):
        return self.current_location


def _make_main_window(profile, popups, *, popup_response=QMessageBox.StandardButton.No):
    return SimpleNamespace(
        color_dict={
            "darker_gray": "#2f2f2f",
            "dark_blue": "#1d4ed8",
            "light_blue": "#60a5fa",
        },
        profile=profile,
        popup_message=lambda title, message: popups.append((title, message)),
        popup_yes_no=Mock(return_value=popup_response),
        _is_yes_response=View.MainWindow._is_yes_response,
    )


def _make_model(machine_model, events, *, printer_head=None):
    return SimpleNamespace(
        machine_model=machine_model,
        rack_model=SimpleNamespace(get_gripper_printer_head=Mock(return_value=printer_head)),
        reload_droplet_model=Mock(side_effect=lambda: events.append("reload_droplet_model")),
        reload_refuel_model=Mock(side_effect=lambda: events.append("reload_refuel_model")),
    )


def _make_controller(events, *, queue_clear=True):
    return SimpleNamespace(
        toggle_regulation=Mock(),
        set_absolute_print_pressure=Mock(),
        set_absolute_refuel_pressure=Mock(),
        set_print_pulse_width=Mock(),
        set_refuel_pulse_width=Mock(),
        check_if_all_completed=Mock(return_value=queue_clear),
        move_to_location=Mock(),
        disconnect_droplet_camera_signals=Mock(
            side_effect=lambda: events.append("disconnect_droplet_camera_signals")
        ),
        connect_droplet_camera_signals=Mock(
            side_effect=lambda: events.append("connect_droplet_camera_signals")
        ),
        enable_print_profile=Mock(side_effect=lambda: events.append("enable_print_profile")),
    )


def _patch_droplet_launch(monkeypatch, events, *, main_window, model, controller):
    class _DropletDialog:
        def __init__(self, main_window_arg, model_arg, controller_arg):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            events.append("droplet_dialog_init")

        def exec(self):
            events.append("droplet_dialog_exec")
            return 0

    monkeypatch.setattr(View.importlib, "reload", lambda module: module)
    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _DropletDialog)


def test_current_profile_pressure_box_removes_extra_bottom_buttons(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        _make_controller(events),
    )

    assert hasattr(box, "calibrate_pressure_button")
    assert not hasattr(box, "droplet_imager_button")
    assert not hasattr(box, "nozzle_dataset_button")


def test_current_profile_calibrate_pressure_rejects_when_queue_not_empty(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(regulating_print_pressure=True, current_location="camera"),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events, queue_clear=False)
    box = PressurePlotBox(main_window, model, controller)

    _patch_droplet_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.calibrate_pressure()

    assert popups == [
        (
            "Commands Still Running",
            "Please wait for the current commands to finish before starting the droplet imager.",
        )
    ]
    controller.move_to_location.assert_not_called()
    model.reload_droplet_model.assert_not_called()


def test_current_profile_calibrate_pressure_requires_gripper_head(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(regulating_print_pressure=True, current_location="camera"),
        events,
        printer_head=None,
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_droplet_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.calibrate_pressure()

    assert popups == [
        (
            "No Printer Head",
            "Please load a printer head into the gripper before starting calibration.",
        )
    ]
    controller.move_to_location.assert_not_called()
    model.reload_droplet_model.assert_not_called()


def test_current_profile_calibrate_pressure_requires_regulated_pressure(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(regulating_print_pressure=False, current_location="camera"),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_droplet_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.calibrate_pressure()

    assert popups == [
        (
            "Pressure Not Regulated",
            "Please regulate pressure before starting calibration.",
        )
    ]
    controller.move_to_location.assert_not_called()
    model.reload_droplet_model.assert_not_called()


def test_current_profile_calibrate_pressure_opens_droplet_imager_at_camera(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(regulating_print_pressure=True, current_location="camera"),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_droplet_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.calibrate_pressure()

    assert events == [
        "disconnect_droplet_camera_signals",
        "reload_droplet_model",
        "connect_droplet_camera_signals",
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_exec",
    ]
    main_window.popup_yes_no.assert_not_called()
    controller.move_to_location.assert_not_called()
    model.reload_refuel_model.assert_not_called()


def test_current_profile_calibrate_pressure_requires_camera_position_on_decline(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(
        CURRENT_PROFILE,
        popups,
        popup_response=QMessageBox.StandardButton.No,
    )
    model = _make_model(
        _FakeMachineModel(regulating_print_pressure=True, current_location="plate"),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_droplet_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.calibrate_pressure()

    main_window.popup_yes_no.assert_called_once()
    assert popups == [
        (
            "Must Be At Camera",
            "Please move the machine to the camera position before starting calibration.",
        )
    ]
    controller.move_to_location.assert_not_called()
    model.reload_droplet_model.assert_not_called()


def test_current_profile_calibrate_pressure_moves_then_launches_droplet_imager(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(
        CURRENT_PROFILE,
        popups,
        popup_response=QMessageBox.StandardButton.Yes,
    )
    model = _make_model(
        _FakeMachineModel(regulating_print_pressure=True, current_location="plate"),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_droplet_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.calibrate_pressure()

    main_window.popup_yes_no.assert_called_once()
    controller.move_to_location.assert_called_once()
    move_args = controller.move_to_location.call_args
    assert move_args.args == ("camera",)
    assert move_args.kwargs["manual"] is True
    on_complete = move_args.kwargs["on_complete"]
    assert callable(on_complete)
    assert events == []

    on_complete()

    assert events == [
        "disconnect_droplet_camera_signals",
        "reload_droplet_model",
        "connect_droplet_camera_signals",
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_exec",
    ]
    assert popups == []


def test_legacy_profile_calibrate_pressure_keeps_mass_calibration(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(LEGACY_PROFILE, popups)
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
    controller.move_to_location.assert_not_called()
    controller.disconnect_droplet_camera_signals.assert_not_called()
    controller.connect_droplet_camera_signals.assert_not_called()
    controller.enable_print_profile.assert_not_called()
    model.reload_droplet_model.assert_not_called()
