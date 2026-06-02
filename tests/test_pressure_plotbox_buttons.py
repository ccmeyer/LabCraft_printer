from types import SimpleNamespace
from unittest.mock import ANY, Mock

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox

import View
from View import PressurePlotBox
from hardware.profile import CURRENT_PROFILE, LEGACY_PROFILE


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


class _FakeMachineModel(QObject):
    machine_state_updated = Signal(bool)
    regulation_state_changed = Signal(bool)
    pressure_updated = Signal()
    printing_parameters_updated = Signal()

    def __init__(
        self,
        *,
        regulating_print_pressure=False,
        regulating_refuel_pressure=None,
        current_location="camera",
        target_print_pressure=1.0,
        target_refuel_pressure=1.0,
        print_pulse_width=3000,
        refuel_pulse_width=3000,
    ):
        super().__init__()
        self.regulating_print_pressure = regulating_print_pressure
        self.regulating_refuel_pressure = (
            regulating_print_pressure
            if regulating_refuel_pressure is None
            else regulating_refuel_pressure
        )
        self.current_location = current_location
        self.target_print_pressure = target_print_pressure
        self.target_refuel_pressure = target_refuel_pressure
        self.print_pulse_width = print_pulse_width
        self.refuel_pulse_width = refuel_pulse_width
        self.dispense_frequency_hz = 10

    def is_connected(self):
        return True

    def motors_are_enabled(self):
        return True

    def get_print_pressure_readings(self):
        return [1.0, 1.1]

    def get_refuel_pressure_readings(self):
        return [0.9, 1.0]

    def get_target_print_pressure(self):
        return self.target_print_pressure

    def get_target_refuel_pressure(self):
        return self.target_refuel_pressure

    def get_print_pulse_width(self):
        return self.print_pulse_width

    def get_refuel_pulse_width(self):
        return self.refuel_pulse_width

    def get_dispense_frequency_hz(self):
        return self.dispense_frequency_hz

    def get_current_location(self):
        return self.current_location


class _SignalStub:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            callback(*args)


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
        print_profiles=[dict(profile) for profile in _PRINT_PROFILES],
        reload_droplet_model=Mock(side_effect=lambda: events.append("reload_droplet_model")),
        reload_refuel_model=Mock(side_effect=lambda: events.append("reload_refuel_model")),
    )


def _make_controller(events, *, queue_clear=True):
    return SimpleNamespace(
        toggle_regulation=Mock(),
        set_absolute_print_pressure=Mock(),
        set_absolute_refuel_pressure=Mock(),
        set_print_pulse_width=Mock(),
        set_dispense_frequency_hz=Mock(),
        set_refuel_pulse_width=Mock(),
        apply_print_profile=Mock(side_effect=lambda profile, callback=None: True),
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
        def __init__(self, main_window_arg, model_arg, controller_arg, **kwargs):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            assert callable(kwargs.get("open_refuel_camera_callback"))
            self.finished = _SignalStub()
            events.append("droplet_dialog_init")

        def exec(self):
            events.append("droplet_dialog_exec")
            return 0

    monkeypatch.setattr(View.importlib, "reload", lambda module: module)
    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _DropletDialog)


def _patch_refuel_launch(monkeypatch, events, *, main_window, model, controller):
    class _RefuelDialog:
        def __init__(self, main_window_arg, model_arg, controller_arg):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            self.finished = _SignalStub()
            events.append("refuel_dialog_init")

        def exec(self):
            events.append("refuel_dialog_exec")
            return 0

    monkeypatch.setattr(View.importlib, "reload", lambda module: module)
    monkeypatch.setattr(View.CalibrationClasses, "RefuelCameraWindow", _RefuelDialog)


def test_current_profile_pressure_box_removes_extra_bottom_buttons(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        _make_controller(events),
    )

    assert hasattr(box, "calibrate_pressure_button")
    assert hasattr(box, "refuel_camera_button")
    assert hasattr(box, "print_frequency_spinbox")
    assert not hasattr(box, "droplet_imager_button")
    assert not hasattr(box, "nozzle_dataset_button")


def test_legacy_profile_pressure_box_hides_refuel_camera_button(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(LEGACY_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        _make_controller(events),
    )

    assert hasattr(box, "calibrate_pressure_button")
    assert hasattr(box, "print_frequency_spinbox")
    assert not hasattr(box, "refuel_camera_button")


def test_pressure_box_frequency_spinbox_calls_controller(qapp):
    events = []
    popups = []
    controller = _make_controller(events)
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        controller,
    )

    box.print_frequency_spinbox.setValue(12)
    box.handle_print_frequency_change()

    controller.set_dispense_frequency_hz.assert_called_once_with(12, manual=True)


def test_pressure_box_frequency_spinbox_tracks_machine_model_updates(qapp):
    events = []
    popups = []
    machine_model = _FakeMachineModel()
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(machine_model, events),
        _make_controller(events),
    )

    machine_model.dispense_frequency_hz = 18
    machine_model.printing_parameters_updated.emit()

    assert box.print_frequency_spinbox.value() == 18


def test_pressure_refresh_does_not_overwrite_frequency_field(qapp):
    events = []
    popups = []
    machine_model = _FakeMachineModel()
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(machine_model, events),
        _make_controller(events),
    )

    box.print_frequency_spinbox.blockSignals(True)
    box.print_frequency_spinbox.setValue(10)
    box.print_frequency_spinbox.blockSignals(False)

    box.update_pressure()

    assert box.print_frequency_spinbox.value() == 10


def test_current_profile_frequency_field_sits_below_pulse_width_fields(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        _make_controller(events),
    )

    assert box.layout.itemAtPosition(7, 2).widget() is box.print_frequency_label
    assert box.layout.itemAtPosition(7, 3).widget() is box.print_frequency_spinbox


def test_legacy_profile_frequency_field_sits_below_pulse_width_fields(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(LEGACY_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        _make_controller(events),
    )

    assert box.layout.itemAtPosition(5, 2).widget() is box.print_frequency_label
    assert box.layout.itemAtPosition(5, 3).widget() is box.print_frequency_spinbox


def test_current_profile_print_profile_row_sits_above_pressure_controls(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        _make_controller(events),
    )

    assert box.layout.itemAtPosition(0, 0).widget() is box.print_profile_label
    assert box.layout.itemAtPosition(0, 1).widget() is box.print_profile_combo
    assert box.layout.itemAtPosition(0, 3).widget() is box.print_profile_apply_button
    assert box.layout.itemAtPosition(1, 0).widget() is box.current_print_pressure_label


def test_legacy_profile_hides_print_profile_row(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(LEGACY_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        _make_controller(events),
    )

    assert not hasattr(box, "print_profile_combo")
    assert box.layout.itemAtPosition(0, 0).widget() is box.current_print_pressure_label


def test_print_profile_tooltips_show_profile_parameters(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        _make_controller(events),
    )

    tooltip = box.print_profile_combo.itemData(0, Qt.ToolTipRole)

    assert "Print pressure: 0.60 psi" in tooltip
    assert "Refuel pressure: 0.30 psi" in tooltip
    assert "Print PW: 1300 us" in tooltip
    assert "Refuel PW: 3000 us" in tooltip


def test_matching_print_profile_shows_loaded_button(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(
            _FakeMachineModel(
                target_print_pressure=0.6,
                target_refuel_pressure=0.3,
                print_pulse_width=1300,
                refuel_pulse_width=3000,
            ),
            events,
        ),
        _make_controller(events),
    )

    assert box.print_profile_apply_button.text() == "Loaded"
    assert not box.print_profile_apply_button.isEnabled()
    assert "#777777" in box.print_profile_apply_button.styleSheet()


def test_selecting_different_print_profile_enables_apply(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(
            _FakeMachineModel(
                target_print_pressure=0.6,
                target_refuel_pressure=0.3,
                print_pulse_width=1300,
                refuel_pulse_width=3000,
            ),
            events,
        ),
        _make_controller(events),
    )

    box.print_profile_combo.setCurrentIndex(1)

    assert box.print_profile_apply_button.text() == "Apply"
    assert box.print_profile_apply_button.isEnabled()
    assert "#60a5fa" in box.print_profile_apply_button.styleSheet()


def test_manual_print_profile_setting_change_returns_button_to_apply(qapp):
    events = []
    popups = []
    controller = _make_controller(events)
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(
            _FakeMachineModel(
                target_print_pressure=0.6,
                target_refuel_pressure=0.3,
                print_pulse_width=1300,
                refuel_pulse_width=3000,
            ),
            events,
        ),
        controller,
    )

    box.target_print_pressure_spinbox.setValue(0.7)
    box.handle_target_print_pressure_change()

    controller.set_absolute_print_pressure.assert_called_with(0.7, manual=True)
    assert box.print_profile_apply_button.text() == "Apply"
    assert box.print_profile_apply_button.isEnabled()


def test_apply_print_profile_calls_controller_and_enters_applying_state(qapp):
    events = []
    popups = []
    controller = _make_controller(events)
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        controller,
    )

    box.handle_print_profile_apply()

    controller.apply_print_profile.assert_called_once_with(_PRINT_PROFILES[0], callback=ANY)
    assert box.print_profile_apply_button.text() == "Applying..."
    assert not box.print_profile_apply_button.isEnabled()


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


def test_current_profile_refuel_camera_rejects_when_queue_not_empty(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
            current_location="camera",
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events, queue_clear=False)
    box = PressurePlotBox(main_window, model, controller)

    _patch_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.refuel_camera()

    assert popups == [
        (
            "Commands Still Running",
            "Please wait for the current commands to finish before starting the refuel camera.",
        )
    ]
    controller.move_to_location.assert_not_called()
    model.reload_refuel_model.assert_not_called()


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


def test_current_profile_refuel_camera_requires_gripper_head(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
            current_location="camera",
        ),
        events,
        printer_head=None,
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.refuel_camera()

    assert popups == [
        (
            "No Printer Head",
            "Please load a printer head into the gripper before starting refuel imaging.",
        )
    ]
    controller.move_to_location.assert_not_called()
    model.reload_refuel_model.assert_not_called()


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


def test_current_profile_refuel_camera_requires_both_regulated_pressures(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=False,
            current_location="camera",
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.refuel_camera()

    assert popups == [
        (
            "Pressure Not Regulated",
            "Please regulate both print and refuel pressure before starting the refuel camera.",
        )
    ]
    controller.move_to_location.assert_not_called()
    model.reload_refuel_model.assert_not_called()


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


def test_current_profile_calibrate_pressure_rejects_duplicate_while_droplet_dialog_open(monkeypatch, qapp):
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

    class _DropletDialog:
        def __init__(self, main_window_arg, model_arg, controller_arg, **kwargs):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            assert callable(kwargs.get("open_refuel_camera_callback"))
            self.finished = _SignalStub()
            events.append("droplet_dialog_init")

        def show(self):
            pass

        def raise_(self):
            pass

        def activateWindow(self):
            pass

        def exec(self):
            events.append("droplet_dialog_exec")
            box.calibrate_pressure()
            return 0

    monkeypatch.setattr(View.importlib, "reload", lambda module: module)
    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _DropletDialog)

    box.calibrate_pressure()

    assert events == [
        "disconnect_droplet_camera_signals",
        "reload_droplet_model",
        "connect_droplet_camera_signals",
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_exec",
    ]
    assert popups == [
        (
            "Droplet Imager Already Open",
            "The droplet imager is already opening or open. Close it before starting another calibration window.",
        )
    ]
    main_window.popup_yes_no.assert_not_called()
    controller.move_to_location.assert_not_called()


def test_current_profile_calibrate_pressure_rejects_duplicate_while_camera_move_pending(monkeypatch, qapp):
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
    box.calibrate_pressure()

    main_window.popup_yes_no.assert_called_once()
    controller.move_to_location.assert_called_once()
    assert popups == [
        (
            "Droplet Imager Already Open",
            "The droplet imager is already opening or open. Close it before starting another calibration window.",
        )
    ]
    assert events == []
    assert not box.calibrate_pressure_button.isEnabled()

    on_complete = controller.move_to_location.call_args.kwargs["on_complete"]
    on_complete()

    assert events == [
        "disconnect_droplet_camera_signals",
        "reload_droplet_model",
        "connect_droplet_camera_signals",
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_exec",
    ]
    assert box.calibrate_pressure_button.isEnabled()


def test_current_profile_calibrate_pressure_allows_relaunch_after_droplet_dialog_cleanup(monkeypatch, qapp):
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

    class _DropletDialog:
        def __init__(self, main_window_arg, model_arg, controller_arg, **kwargs):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            assert callable(kwargs.get("open_refuel_camera_callback"))
            self.finished = _SignalStub()
            events.append("droplet_dialog_init")

        def exec(self):
            events.append("droplet_dialog_exec")
            self.finished.emit(0)
            return 0

    monkeypatch.setattr(View.importlib, "reload", lambda module: module)
    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _DropletDialog)

    box.calibrate_pressure()
    box.calibrate_pressure()

    assert events == [
        "disconnect_droplet_camera_signals",
        "reload_droplet_model",
        "connect_droplet_camera_signals",
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_exec",
        "disconnect_droplet_camera_signals",
        "reload_droplet_model",
        "connect_droplet_camera_signals",
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_exec",
    ]
    assert popups == []
    assert box.calibrate_pressure_button.isEnabled()


def test_current_profile_refuel_camera_opens_refuel_dialog_at_camera(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
            current_location="camera",
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.refuel_camera()

    assert events == [
        "enable_print_profile",
        "refuel_dialog_init",
        "refuel_dialog_exec",
    ]
    model.reload_refuel_model.assert_not_called()
    main_window.popup_yes_no.assert_not_called()
    controller.move_to_location.assert_not_called()
    controller.disconnect_droplet_camera_signals.assert_not_called()
    controller.connect_droplet_camera_signals.assert_not_called()
    model.reload_droplet_model.assert_not_called()


def test_current_profile_refuel_camera_rejects_duplicate_while_dialog_open(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
            current_location="camera",
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    class _RefuelDialog:
        def __init__(self, main_window_arg, model_arg, controller_arg):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            self.finished = _SignalStub()
            events.append("refuel_dialog_init")

        def show(self):
            pass

        def raise_(self):
            pass

        def activateWindow(self):
            pass

        def exec(self):
            events.append("refuel_dialog_exec")
            box.refuel_camera()
            return 0

    monkeypatch.setattr(View.importlib, "reload", lambda module: module)
    monkeypatch.setattr(View.CalibrationClasses, "RefuelCameraWindow", _RefuelDialog)

    box.refuel_camera()

    assert events == [
        "enable_print_profile",
        "refuel_dialog_init",
        "refuel_dialog_exec",
    ]
    assert popups == [
        (
            "Refuel Camera Already Open",
            "The refuel camera is already opening or open. Close it before starting another refuel camera window.",
        )
    ]
    main_window.popup_yes_no.assert_not_called()
    controller.move_to_location.assert_not_called()
    model.reload_droplet_model.assert_not_called()
    model.reload_refuel_model.assert_not_called()
    assert box.refuel_camera_button.isEnabled()


def test_current_profile_refuel_camera_allows_relaunch_after_dialog_cleanup(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
            current_location="camera",
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    class _RefuelDialog:
        def __init__(self, main_window_arg, model_arg, controller_arg):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            self.finished = _SignalStub()
            events.append("refuel_dialog_init")

        def exec(self):
            events.append("refuel_dialog_exec")
            self.finished.emit(0)
            return 0

    monkeypatch.setattr(View.importlib, "reload", lambda module: module)
    monkeypatch.setattr(View.CalibrationClasses, "RefuelCameraWindow", _RefuelDialog)

    box.refuel_camera()
    box.refuel_camera()

    assert events == [
        "enable_print_profile",
        "refuel_dialog_init",
        "refuel_dialog_exec",
        "enable_print_profile",
        "refuel_dialog_init",
        "refuel_dialog_exec",
    ]
    assert popups == []
    assert box.refuel_camera_button.isEnabled()


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


def test_current_profile_refuel_camera_requires_camera_position_on_decline(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(
        CURRENT_PROFILE,
        popups,
        popup_response=QMessageBox.StandardButton.No,
    )
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
            current_location="plate",
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.refuel_camera()

    main_window.popup_yes_no.assert_called_once()
    assert popups == [
        (
            "Must Be At Camera",
            "Please move the machine to the camera position before starting refuel imaging.",
        )
    ]
    controller.move_to_location.assert_not_called()
    model.reload_refuel_model.assert_not_called()


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


def test_current_profile_refuel_camera_moves_then_launches_refuel_dialog(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(
        CURRENT_PROFILE,
        popups,
        popup_response=QMessageBox.StandardButton.Yes,
    )
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
            current_location="plate",
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.refuel_camera()

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
        "enable_print_profile",
        "refuel_dialog_init",
        "refuel_dialog_exec",
    ]
    model.reload_refuel_model.assert_not_called()
    controller.disconnect_droplet_camera_signals.assert_not_called()
    controller.connect_droplet_camera_signals.assert_not_called()
    assert popups == []


def test_current_profile_refuel_camera_rejects_duplicate_while_camera_move_pending(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(
        CURRENT_PROFILE,
        popups,
        popup_response=QMessageBox.StandardButton.Yes,
    )
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
            current_location="plate",
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.refuel_camera()
    box.refuel_camera()

    main_window.popup_yes_no.assert_called_once()
    controller.move_to_location.assert_called_once()
    assert popups == [
        (
            "Refuel Camera Already Open",
            "The refuel camera is already opening or open. Close it before starting another refuel camera window.",
        )
    ]
    assert events == []
    assert not box.refuel_camera_button.isEnabled()

    on_complete = controller.move_to_location.call_args.kwargs["on_complete"]
    on_complete()

    assert events == [
        "enable_print_profile",
        "refuel_dialog_init",
        "refuel_dialog_exec",
    ]
    assert box.refuel_camera_button.isEnabled()


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
