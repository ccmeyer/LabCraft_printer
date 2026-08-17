from types import SimpleNamespace
from unittest.mock import ANY, Mock

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QSignalSpy
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
        connected=True,
    ):
        super().__init__()
        self.machine_connected = bool(connected)
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
        self.print_pressure_readings = [1.0, 1.1]
        self.refuel_pressure_readings = [0.9, 1.0]

    def is_connected(self):
        return self.machine_connected

    def motors_are_enabled(self):
        return True

    def get_print_pressure_readings(self):
        return list(self.print_pressure_readings)

    def get_refuel_pressure_readings(self):
        return list(self.refuel_pressure_readings)

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


def _make_model(
    machine_model,
    events,
    *,
    printer_head=None,
    read_only_experiment=False,
):
    return SimpleNamespace(
        machine_model=machine_model,
        experiment_loaded=_SignalStub(),
        rack_model=SimpleNamespace(get_gripper_printer_head=Mock(return_value=printer_head)),
        print_profiles=[dict(profile) for profile in _PRINT_PROFILES],
        reload_droplet_model=Mock(side_effect=lambda: events.append("reload_droplet_model")),
        reload_refuel_model=Mock(side_effect=lambda: events.append("reload_refuel_model")),
        is_read_only_experiment_view_active=lambda: bool(read_only_experiment),
    )


def _make_controller(events, *, queue_clear=True, imaging_preflight=None, refuel_preflight=None):
    if imaging_preflight is None:
        imaging_preflight = {
            "ok": True,
            "code": "ok",
            "message": "",
            "record": {"run_id": "stream_calibration"},
        }
    if refuel_preflight is None:
        refuel_preflight = {
            "ok": False,
            "code": "required_refuel_check",
            "message": "Manual refuel check is required.",
            "record": {"status": "required"},
        }
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
        enable_print_profile=Mock(
            side_effect=lambda *, deferred_gripper_refresh=False: events.append("enable_print_profile")
        ),
        disable_print_profile=Mock(side_effect=lambda: events.append("disable_print_profile")),
        clear_command_queue=Mock(),
        get_print_array_imaging_calibration_preflight=Mock(return_value=imaging_preflight),
        get_print_array_refuel_check_preflight=Mock(return_value=refuel_preflight),
    )


def _patch_droplet_launch(monkeypatch, events, *, main_window, model, controller):
    class _DropletDialog:
        def __init__(self, main_window_arg, model_arg, controller_arg, **kwargs):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            assert callable(kwargs.get("open_refuel_camera_callback"))
            assert callable(kwargs.get("post_apply_manual_refuel_check_callback"))
            self.finished = _SignalStub()
            self.sessionDeactivated = _SignalStub()
            self._active = False
            events.append("droplet_dialog_init")

        def activate_session(self, mode="calibration"):
            self._active = True
            events.append(f"droplet_dialog_activate:{mode}")

        def deactivate_session(self, reason="closed"):
            if not self._active:
                return False
            self._active = False
            self.sessionDeactivated.emit(reason)
            return True

        def session_is_active(self):
            return self._active

        def exec(self):
            events.append("droplet_dialog_exec")
            self.deactivate_session("done")
            self.finished.emit(0)
            return 0

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

    monkeypatch.setattr(View.CalibrationClasses, "RefuelCameraWindow", _RefuelDialog)


def _patch_manual_refuel_launch(monkeypatch, events, *, main_window, model, controller):
    class _ManualRefuelDialog:
        def __init__(self, main_window_arg, model_arg, controller_arg):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            self.finished = _SignalStub()
            self.focus_calls = []
            events.append("manual_refuel_dialog_init")

        def show(self):
            self.focus_calls.append("show")
            events.append("manual_refuel_dialog_show")

        def raise_(self):
            self.focus_calls.append("raise")
            events.append("manual_refuel_dialog_raise")

        def activateWindow(self):
            self.focus_calls.append("activate")
            events.append("manual_refuel_dialog_activate")

        def exec(self):
            events.append("manual_refuel_dialog_exec")
            return 0

    monkeypatch.setattr(View.CalibrationClasses, "ManualRefuelCheckDialog", _ManualRefuelDialog)


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
    assert box.chart.property("pressureLegendEntries") == ["Print"]


def test_pressure_plot_uses_shared_channel_and_target_styling(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        _make_controller(events),
    )

    assert box.print_series.name() == "Print"
    assert box.refuel_series.name() == "Refuel"
    assert box.target_print_pressure_series.name() == "Print target"
    assert box.target_refuel_pressure_series.name() == "Refuel target"
    assert box.print_series.pen().color().name() == "#60a5fa"
    assert box.refuel_series.pen().color().name() == "#ffffff"
    assert box.target_print_pressure_series.pen().color() == box.print_series.pen().color()
    assert box.target_refuel_pressure_series.pen().color() == box.refuel_series.pen().color()
    for series in (box.print_series, box.refuel_series):
        assert series.pen().widthF() == pytest.approx(1.25)
        assert series.pen().style() == Qt.PenStyle.SolidLine
    for series in (
        box.target_print_pressure_series,
        box.target_refuel_pressure_series,
    ):
        assert series.pen().widthF() == pytest.approx(1.25)
        assert series.pen().style() == Qt.PenStyle.DashLine
    assert box.chart.property("pressureLegendEntries") == ["Print", "Refuel"]
    assert box.chart.animationOptions() == View.QtCharts.QChart.AnimationOption.NoAnimation


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


def test_pressure_updates_are_coalesced_and_render_latest_values(qapp):
    events = []
    popups = []
    machine_model = _FakeMachineModel()
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(machine_model, events),
        _make_controller(events),
    )
    render = Mock(wraps=box.update_pressure)
    box.update_pressure = render
    timer_spy = QSignalSpy(box._pressure_render_timer.timeout)

    for _ in range(20):
        machine_model.pressure_updated.emit()

    assert box._pressure_render_timer.isSingleShot()
    assert box._pressure_render_timer.interval() == 100
    assert box._pressure_render_timer.isActive()
    assert render.call_count == 0

    machine_model.print_pressure_readings = [1.5, 1.75]
    machine_model.refuel_pressure_readings = [0.5, 0.625]

    assert timer_spy.wait(1000)
    assert render.call_count == 1
    assert box.print_series.count() == 2
    assert box.print_series.at(1).y() == 1.75
    assert box.refuel_series.count() == 2
    assert box.refuel_series.at(1).y() == 0.625
    assert box.target_print_pressure_series.count() == 2
    assert box.target_refuel_pressure_series.count() == 2
    assert box.target_refuel_pressure_series.at(1).y() == 1.0
    assert box.current_print_pressure_value.text() == "1.750"
    assert box.current_refuel_pressure_value.text() == "0.625"


def test_pressure_render_suspension_stops_requests_and_catches_up_once(qapp):
    events = []
    popups = []
    machine_model = _FakeMachineModel()
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(machine_model, events),
        _make_controller(events),
    )
    render = Mock(wraps=box.update_pressure)
    box.update_pressure = render

    machine_model.pressure_updated.emit()
    assert box._pressure_render_timer.isActive()
    box.set_pressure_render_suspended(True)
    assert box._pressure_render_suspended is True
    assert not box._pressure_render_timer.isActive()

    machine_model.print_pressure_readings = [1.8, 1.9]
    machine_model.refuel_pressure_readings = [0.7, 0.8]
    for _ in range(10):
        machine_model.pressure_updated.emit()
    assert not box._pressure_render_timer.isActive()
    assert render.call_count == 0

    box.set_pressure_render_suspended(False)
    assert render.call_count == 1
    assert box.print_series.at(1).y() == 1.9
    assert box.refuel_series.at(1).y() == 0.8

    box.set_pressure_render_suspended(False)
    assert render.call_count == 1
    box.set_pressure_render_suspended(True)
    box.set_pressure_render_suspended(True)
    box.set_pressure_render_suspended(False)
    assert render.call_count == 2


def test_stale_imager_cleanup_does_not_resume_active_renderer(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        _make_controller(events),
    )
    stale_dialog = object()
    active_dialog = object()
    box._set_active_droplet_imager_dialog(active_dialog)

    box._clear_droplet_imager_launch_state(stale_dialog)

    assert box._droplet_imager_dialog is active_dialog
    assert box._pressure_render_suspended is True
    box._clear_droplet_imager_launch_state(active_dialog)
    assert box._droplet_imager_dialog is active_dialog
    assert box._droplet_imager_dialog_state == "inactive"
    assert box._pressure_render_suspended is False


def test_pressure_render_timer_stops_when_widget_closes(qapp):
    events = []
    popups = []
    machine_model = _FakeMachineModel()
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(machine_model, events),
        _make_controller(events),
    )

    machine_model.pressure_updated.emit()
    assert box._pressure_render_timer.isActive()

    box.close()

    assert not box._pressure_render_timer.isActive()


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


def test_disconnected_print_profile_disables_apply(qapp):
    events = []
    popups = []
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(_FakeMachineModel(connected=False), events),
        _make_controller(events),
    )

    assert box.print_profile_apply_button.text() == "Apply"
    assert not box.print_profile_apply_button.isEnabled()
    assert "#777777" in box.print_profile_apply_button.styleSheet()


def test_machine_connection_update_enables_print_profile_apply(qapp):
    events = []
    popups = []
    machine_model = _FakeMachineModel(connected=False)
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(machine_model, events),
        _make_controller(events),
    )

    machine_model.machine_connected = True
    machine_model.machine_state_updated.emit(True)

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


def test_apply_print_profile_ignores_disconnected_machine(qapp):
    events = []
    popups = []
    controller = _make_controller(events)
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(_FakeMachineModel(connected=False), events),
        controller,
    )

    box.handle_print_profile_apply()

    controller.apply_print_profile.assert_not_called()
    assert box.print_profile_apply_button.text() == "Apply"
    assert not box.print_profile_apply_button.isEnabled()


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
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_activate:calibration",
        "droplet_dialog_exec",
        "disable_print_profile",
    ]
    main_window.popup_yes_no.assert_not_called()
    controller.move_to_location.assert_not_called()
    model.reload_refuel_model.assert_not_called()
    controller.enable_print_profile.assert_called_once_with(
        deferred_gripper_refresh=False,
    )
    controller.disable_print_profile.assert_called_once_with()
    assert box._pressure_render_suspended is False


def test_same_session_completion_keeps_printer_head_calibration_available(qapp):
    events = []
    popups = []
    model = _make_model(
        _FakeMachineModel(regulating_print_pressure=True, current_location="camera"),
        events,
        printer_head=object(),
        read_only_experiment=False,
    )
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        model,
        _make_controller(events),
    )

    box._refresh_droplet_imager_button_state()

    assert box.calibrate_pressure_button.isEnabled()
    assert box.calibrate_pressure_button.toolTip() == ""


def test_historical_read_only_view_disables_and_rejects_calibration_launch(qapp):
    events = []
    popups = []
    controller = _make_controller(events)
    model = _make_model(
        _FakeMachineModel(regulating_print_pressure=True, current_location="camera"),
        events,
        printer_head=object(),
        read_only_experiment=True,
    )
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        model,
        controller,
    )

    box._refresh_droplet_imager_button_state()
    box.droplet_imager()

    assert not box.calibrate_pressure_button.isEnabled()
    assert "Historical experiments are analysis-only" in box.calibrate_pressure_button.toolTip()
    assert popups == [
        (
            "Historical Experiment Read-Only",
            "Historical experiments are analysis-only. Return to a live experiment "
            "to run printer-head diagnostics.",
        )
    ]
    controller.check_if_all_completed.assert_not_called()
    assert events == []


def test_experiment_load_refreshes_historical_calibration_launch_state(qapp):
    events = []
    popups = []
    read_only = {"active": False}
    model = _make_model(
        _FakeMachineModel(regulating_print_pressure=True, current_location="camera"),
        events,
        printer_head=object(),
    )
    model.is_read_only_experiment_view_active = lambda: read_only["active"]
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        model,
        _make_controller(events),
    )

    assert box.calibrate_pressure_button.isEnabled()

    read_only["active"] = True
    model.experiment_loaded.emit()

    assert not box.calibrate_pressure_button.isEnabled()
    assert "Historical experiments are analysis-only" in box.calibrate_pressure_button.toolTip()


def test_nested_refuel_window_shares_calibration_profile_lease(monkeypatch, qapp):
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
        def __init__(self, *_args):
            self.finished = _SignalStub()
            events.append("refuel_dialog_init")

        def exec(self):
            events.append("refuel_dialog_exec")
            return 0

    class _DropletDialog:
        def __init__(self, *_args, **_kwargs):
            self.finished = _SignalStub()
            self.sessionDeactivated = _SignalStub()
            self._active = False
            events.append("droplet_dialog_init")

        def activate_session(self, mode="calibration"):
            self._active = True
            events.append(f"droplet_dialog_activate:{mode}")

        def deactivate_session(self, reason="closed"):
            if not self._active:
                return False
            self._active = False
            self.sessionDeactivated.emit(reason)
            return True

        def session_is_active(self):
            return self._active

        def exec(self):
            events.append("droplet_dialog_exec")
            box._launch_refuel_camera_dialog()
            assert controller.disable_print_profile.call_count == 0
            return 0

    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _DropletDialog)
    monkeypatch.setattr(View.CalibrationClasses, "RefuelCameraWindow", _RefuelDialog)

    box.calibrate_pressure()

    controller.enable_print_profile.assert_called_once_with(
        deferred_gripper_refresh=False,
    )
    controller.disable_print_profile.assert_called_once_with()
    assert events == [
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_activate:calibration",
        "droplet_dialog_exec",
        "refuel_dialog_init",
        "refuel_dialog_exec",
        "disable_print_profile",
    ]


def test_calibration_profile_enable_rejection_prevents_dialog_construction(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(regulating_print_pressure=True, current_location="camera"),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    controller.enable_print_profile = Mock(return_value=False)
    box = PressurePlotBox(main_window, model, controller)
    _patch_droplet_launch(
        monkeypatch,
        events,
        main_window=main_window,
        model=model,
        controller=controller,
    )

    box.calibrate_pressure()

    controller.disable_print_profile.assert_not_called()
    assert "droplet_dialog_init" not in events
    assert popups == [
        (
            "Calibration Profile Failed",
            "Could not queue the calibration pressure profile. The calibration window was not opened.",
        )
    ]


def test_calibration_profile_constructor_failure_releases_lease(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(_FakeMachineModel(), events, printer_head=object())
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    class _FailingDialog:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("injected constructor failure")

    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _FailingDialog)

    with pytest.raises(RuntimeError, match="injected constructor failure"):
        box._launch_droplet_imager_dialog()

    controller.enable_print_profile.assert_called_once_with(
        deferred_gripper_refresh=False,
    )
    controller.disable_print_profile.assert_called_once_with()
    assert box._calibration_profile_leases == {}


def test_calibration_profile_disable_failure_uses_queue_clear_fallback(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(_FakeMachineModel(), events, printer_head=object())
    controller = _make_controller(events)
    controller.disable_print_profile = Mock(return_value=False)
    box = PressurePlotBox(main_window, model, controller)
    _patch_droplet_launch(
        monkeypatch,
        events,
        main_window=main_window,
        model=model,
        controller=controller,
    )

    box._launch_droplet_imager_dialog()

    controller.clear_command_queue.assert_called_once_with()
    assert popups == [
        (
            "Calibration Profile Cleanup Failed",
            "Could not queue the calibration pressure-profile disable command. Verify the machine is idle before continuing.",
        )
    ]


def test_nozzle_dataset_capture_uses_calibration_profile_lease(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(_FakeMachineModel(), events, printer_head=object())
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    class _DatasetDialog:
        def __init__(self, *_args):
            events.append("dataset_dialog_init")

        def exec(self):
            events.append("dataset_dialog_exec")
            return 0

    monkeypatch.setattr(
        View.CalibrationClasses,
        "NozzlePositionDatasetCaptureWindow",
        _DatasetDialog,
    )

    box.nozzle_position_dataset_capture()

    controller.enable_print_profile.assert_called_once_with(
        deferred_gripper_refresh=False,
    )
    controller.disable_print_profile.assert_called_once_with()
    assert events == [
        "enable_print_profile",
        "dataset_dialog_init",
        "dataset_dialog_exec",
        "disable_print_profile",
    ]


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
            assert callable(kwargs.get("post_apply_manual_refuel_check_callback"))
            self.finished = _SignalStub()
            self.sessionDeactivated = _SignalStub()
            self._active = False
            events.append("droplet_dialog_init")

        def activate_session(self, mode="calibration"):
            self._active = True
            events.append(f"droplet_dialog_activate:{mode}")

        def deactivate_session(self, reason="closed"):
            if not self._active:
                return False
            self._active = False
            self.sessionDeactivated.emit(reason)
            return True

        def session_is_active(self):
            return self._active

        def show(self):
            pass

        def raise_(self):
            pass

        def activateWindow(self):
            pass

        def exec(self):
            events.append("droplet_dialog_exec")
            assert box._pressure_render_suspended is True
            box.calibrate_pressure()
            assert box._pressure_render_suspended is True
            return 0

    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _DropletDialog)

    box.calibrate_pressure()

    assert events == [
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_activate:calibration",
        "droplet_dialog_exec",
        "disable_print_profile",
    ]
    assert popups == [
        (
            "Droplet Imager Already Open",
            "The droplet imager is already opening or open. Close it before starting another calibration window.",
        )
    ]
    main_window.popup_yes_no.assert_not_called()
    controller.move_to_location.assert_not_called()
    assert box._pressure_render_suspended is False


def test_manual_optics_launch_transfers_and_restores_pressure_rendering(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(_FakeMachineModel(), events)
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    class _OpticsDialog:
        def __init__(self, *_args, **_kwargs):
            self.finished = _SignalStub()
            self.sessionDeactivated = _SignalStub()
            self._active = False

        def activate_session(self, mode="calibration"):
            assert mode == "optics"
            self._active = True

        def deactivate_session(self, reason="closed"):
            if not self._active:
                return False
            self._active = False
            self.sessionDeactivated.emit(reason)
            return True

        def session_is_active(self):
            return self._active

        def exec(self):
            assert box._pressure_render_suspended is True
            events.append("optics_exec")
            return 7

    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _OpticsDialog)

    assert box._launch_manual_optics_calibration_dialog() == 7
    assert "optics_exec" in events
    assert events[-1] == "disable_print_profile"
    assert box._droplet_imager_dialog is not None
    assert box._droplet_imager_dialog_state == "inactive"
    assert box._pressure_render_suspended is False


def test_failed_simulation_dialog_open_restores_pressure_rendering(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    main_window.runtime_context = View.SIMULATION_RUNTIME_CONTEXT
    model = _make_model(_FakeMachineModel(), events)
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    class _FailedDialog(View.QtWidgets.QDialog):
        def __init__(self, *_args, **_kwargs):
            super().__init__()
            self._active = False

        def activate_session(self, mode="calibration"):
            self._active = True

        def deactivate_session(self, reason="closed"):
            self._active = False

        def session_is_active(self):
            return self._active

        def open(self):
            assert box._pressure_render_suspended is True
            raise RuntimeError("show failed")

    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _FailedDialog)

    with pytest.raises(RuntimeError, match="show failed"):
        box._launch_simulation_calibration_dialog()
    assert box._droplet_imager_dialog is not None
    assert box._droplet_imager_dialog_state == "inactive"
    assert box._pressure_render_suspended is False


def test_result_only_dialog_transfers_pressure_rendering_until_finished(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    main_window.runtime_context = View.SIMULATION_RUNTIME_CONTEXT
    model = _make_model(_FakeMachineModel(), events)
    model.calibration_manager = SimpleNamespace(
        _transient_characterization_candidate={
            "candidate": SimpleNamespace(candidate_id="candidate-1")
        }
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    class _ResultDialog(View.QtWidgets.QDialog):
        def __init__(self, *_args, **kwargs):
            super().__init__()
            assert kwargs["result_presentation_only"] is True
            assert kwargs["transient_candidate_id"] == "candidate-1"
            self._active = False

        def activate_session(self, mode="calibration"):
            self._active = True

        def deactivate_session(self, reason="closed"):
            self._active = False

        def session_is_active(self):
            return self._active

    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _ResultDialog)

    dialog = box.open_simulated_calibration_result("candidate-1")
    assert box._pressure_render_suspended is True
    dialog.reject()
    qapp.processEvents()
    assert box._droplet_imager_dialog is None
    assert box._pressure_render_suspended is False


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
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_activate:calibration",
        "droplet_dialog_exec",
        "disable_print_profile",
    ]
    assert box.calibrate_pressure_button.isEnabled()


def test_transport_fault_releases_pending_camera_launch_controls(qapp):
    events = []
    popups = []
    controller = _make_controller(events)
    controller.transport_fault_ui_signal = _SignalStub()
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, popups),
        _make_model(_FakeMachineModel(), events),
        controller,
    )
    box._set_droplet_imager_launch_pending(True)
    box._set_refuel_camera_launch_pending(True)
    box._manual_refuel_check_launch_pending = True
    box._manual_refuel_check_after_imager_pending = True
    box._print_profile_apply_pending = True

    controller.transport_fault_ui_signal.emit({"fault_code": "missing_expected_seq32"})

    assert box._droplet_imager_launch_pending is False
    assert box._refuel_camera_launch_pending is False
    assert box._manual_refuel_check_launch_pending is False
    assert box._manual_refuel_check_after_imager_pending is False
    assert box._print_profile_apply_pending is False
    assert box.calibrate_pressure_button.isEnabled()
    assert box.refuel_camera_button.isEnabled()


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

    _patch_droplet_launch(
        monkeypatch,
        events,
        main_window=main_window,
        model=model,
        controller=controller,
    )

    box.calibrate_pressure()
    box.calibrate_pressure()

    assert events == [
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_activate:calibration",
        "droplet_dialog_exec",
        "disable_print_profile",
        "enable_print_profile",
        "droplet_dialog_activate:calibration",
        "droplet_dialog_exec",
        "disable_print_profile",
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
        "disable_print_profile",
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

    monkeypatch.setattr(View.CalibrationClasses, "RefuelCameraWindow", _RefuelDialog)

    box.refuel_camera()

    assert events == [
        "enable_print_profile",
        "refuel_dialog_init",
        "refuel_dialog_exec",
        "disable_print_profile",
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

    monkeypatch.setattr(View.CalibrationClasses, "RefuelCameraWindow", _RefuelDialog)

    box.refuel_camera()
    box.refuel_camera()

    assert events == [
        "enable_print_profile",
        "refuel_dialog_init",
        "refuel_dialog_exec",
        "disable_print_profile",
        "enable_print_profile",
        "refuel_dialog_init",
        "refuel_dialog_exec",
        "disable_print_profile",
    ]
    assert popups == []
    assert box.refuel_camera_button.isEnabled()


def test_current_profile_manual_refuel_check_rejects_when_queue_not_empty(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events, queue_clear=False)
    box = PressurePlotBox(main_window, model, controller)

    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.manual_refuel_check()

    assert popups == [
        (
            "Commands Still Running",
            "Please wait for the current commands to finish before starting the manual refuel check.",
        )
    ]
    assert events == []
    controller.get_print_array_imaging_calibration_preflight.assert_not_called()
    controller.get_print_array_refuel_check_preflight.assert_not_called()


def test_current_profile_manual_refuel_check_requires_gripper_head(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
        ),
        events,
        printer_head=None,
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.manual_refuel_check()

    assert popups == [
        (
            "No Printer Head",
            "Please load a printer head into the gripper before starting the manual refuel check.",
        )
    ]
    assert events == []
    controller.get_print_array_imaging_calibration_preflight.assert_not_called()
    controller.get_print_array_refuel_check_preflight.assert_not_called()


def test_current_profile_manual_refuel_check_requires_both_regulated_pressures(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=False,
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.manual_refuel_check()

    assert popups == [
        (
            "Pressure Not Regulated",
            "Please regulate both print and refuel pressure before starting the manual refuel check.",
        )
    ]
    assert events == []
    controller.get_print_array_imaging_calibration_preflight.assert_not_called()
    controller.get_print_array_refuel_check_preflight.assert_not_called()


def test_current_profile_manual_refuel_check_requires_valid_imaging_calibration(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(
        events,
        imaging_preflight={
            "ok": False,
            "code": "missing_applied_calibration",
            "message": "Apply a stream calibration first.",
        },
    )
    box = PressurePlotBox(main_window, model, controller)

    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.manual_refuel_check()

    assert popups == [
        (
            "Applied Calibration Required",
            "Apply a stream calibration first.",
        )
    ]
    assert events == []
    controller.get_print_array_imaging_calibration_preflight.assert_called_once_with()
    controller.get_print_array_refuel_check_preflight.assert_not_called()


def test_current_profile_manual_refuel_check_rejects_non_stream_context(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(
        events,
        refuel_preflight={
            "ok": True,
            "code": "not_required",
            "message": "Manual refuel check is not required.",
        },
    )
    box = PressurePlotBox(main_window, model, controller)

    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.manual_refuel_check()

    assert popups == [
        (
            "Stream Mode Required",
            "Manual refuel checks are only required for stream-mode printer heads.",
        )
    ]
    assert events == []
    controller.get_print_array_imaging_calibration_preflight.assert_called_once_with()
    controller.get_print_array_refuel_check_preflight.assert_called_once_with()


def test_current_profile_manual_refuel_check_rejects_unavailable_context(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(
        events,
        refuel_preflight={
            "ok": False,
            "code": "context_unavailable",
            "message": "Load a printer head first.",
        },
    )
    box = PressurePlotBox(main_window, model, controller)

    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.manual_refuel_check()

    assert popups == [
        (
            "Cannot Start Manual Refuel Check",
            "Load a printer head first.",
        )
    ]
    assert events == []
    controller.get_print_array_imaging_calibration_preflight.assert_called_once_with()
    controller.get_print_array_refuel_check_preflight.assert_called_once_with()


def test_current_profile_manual_refuel_check_opens_dialog(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.manual_refuel_check()

    assert events == [
        "manual_refuel_dialog_init",
        "manual_refuel_dialog_exec",
    ]
    assert popups == []
    controller.move_to_location.assert_not_called()
    controller.get_print_array_imaging_calibration_preflight.assert_called_once_with()
    controller.get_print_array_refuel_check_preflight.assert_called_once_with()


def test_current_profile_post_apply_manual_refuel_check_moves_to_loading_then_opens(monkeypatch, qapp):
    events = []
    popups = []
    deferred_callbacks = []
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

    monkeypatch.setattr(
        View.QtCore.QTimer,
        "singleShot",
        lambda delay_ms, callback: deferred_callbacks.append((delay_ms, callback)),
    )
    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.manual_refuel_check_after_stream_apply()

    controller.move_to_location.assert_called_once()
    move_args = controller.move_to_location.call_args
    assert move_args.args == ("loading",)
    assert move_args.kwargs["manual"] is True
    assert callable(move_args.kwargs["on_complete"])
    assert events == []

    move_args.kwargs["on_complete"]()

    assert events == []
    assert len(deferred_callbacks) == 1
    delay_ms, launch_callback = deferred_callbacks.pop()
    assert delay_ms == 0

    launch_callback()

    assert events == [
        "manual_refuel_dialog_init",
        "manual_refuel_dialog_exec",
    ]
    assert popups == []


def test_current_profile_post_apply_manual_refuel_check_opens_immediately_at_loading(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
            current_location="loading",
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.manual_refuel_check_after_stream_apply()

    controller.move_to_location.assert_not_called()
    assert events == [
        "manual_refuel_dialog_init",
        "manual_refuel_dialog_exec",
    ]
    assert popups == []


def test_current_profile_post_apply_manual_refuel_check_rejects_duplicate_loading_move(monkeypatch, qapp):
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

    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.manual_refuel_check_after_stream_apply()
    box.manual_refuel_check_after_stream_apply()

    controller.move_to_location.assert_called_once()
    assert popups == [
        (
            "Manual Refuel Check Already Open",
            "The manual refuel check is already opening or open. Close it before starting another check.",
        )
    ]
    assert events == []


def test_current_profile_post_apply_manual_refuel_check_move_failure_clears_pending(monkeypatch, qapp):
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
    controller.move_to_location.return_value = False
    box = PressurePlotBox(main_window, model, controller)

    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    box.manual_refuel_check_after_stream_apply()

    assert popups == [
        (
            "Move To Loading Failed",
            "Could not queue the move to loading for the manual refuel check.",
        )
    ]
    assert box._manual_refuel_check_launch_is_active() is False
    assert events == []


def test_current_profile_post_apply_request_waits_for_imager_cleanup(monkeypatch, qapp):
    events = []
    popups = []
    callbacks = []
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
    box._droplet_imager_dialog = object()
    box._droplet_imager_dialog_state = "active"

    monkeypatch.setattr(View.QtCore.QTimer, "singleShot", lambda _ms, callback: callbacks.append(callback))
    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    assert box.request_manual_refuel_check_after_imager_close() is True
    assert box._manual_refuel_check_after_imager_pending is True
    assert len(callbacks) == 1

    callbacks.pop(0)()

    assert box._manual_refuel_check_after_imager_pending is True
    assert controller.move_to_location.call_count == 0
    assert len(callbacks) == 1

    box._droplet_imager_dialog_state = "inactive"
    callbacks.pop(0)()

    controller.move_to_location.assert_called_once()
    assert box._manual_refuel_check_after_imager_pending is False
    assert events == []


def test_current_profile_post_apply_request_waits_for_cleanup_queue(monkeypatch, qapp):
    events = []
    popups = []
    callbacks = []
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
    controller.check_if_all_completed.side_effect = [False, False, True, True]
    box = PressurePlotBox(main_window, model, controller)
    box._droplet_imager_dialog = object()
    box._droplet_imager_dialog_state = "active"

    monkeypatch.setattr(View.QtCore.QTimer, "singleShot", lambda _ms, callback: callbacks.append(callback))
    _patch_manual_refuel_launch(monkeypatch, events, main_window=main_window, model=model, controller=controller)

    assert box.request_manual_refuel_check_after_imager_close() is True
    callbacks.pop(0)()
    box._droplet_imager_dialog_state = "inactive"

    callbacks.pop(0)()
    assert controller.move_to_location.call_count == 0
    assert box._manual_refuel_check_after_imager_pending is True

    callbacks.pop(0)()
    assert controller.move_to_location.call_count == 0
    assert box._manual_refuel_check_after_imager_pending is True

    callbacks.pop(0)()

    controller.move_to_location.assert_called_once()
    assert box._manual_refuel_check_after_imager_pending is False
    assert popups == []
    assert events == []


def test_simulation_calibration_close_advances_manual_refuel_handoff(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    main_window.runtime_context = View.SIMULATION_RUNTIME_CONTEXT
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
    box.bind_simulation_workflows(
        calibration_generate_callback=lambda _profile: {"ok": True},
        calibration_availability_callback=lambda _profile: {"ok": True},
        manual_refuel_outcome_callback=lambda _status, **_kwargs: {"ok": True},
        manual_refuel_deferred_callback=lambda: {"ok": True},
        manual_refuel_availability_callback=lambda: {
            "ok": True,
            "calibration_fingerprint": "stream-fingerprint",
        },
    )

    class _SimulationCalibrationDialog(View.QtWidgets.QDialog):
        def __init__(self, main_window_arg, model_arg, controller_arg, **kwargs):
            super().__init__()
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            assert kwargs.get("simulation_workflow_mode") is True
            assert callable(kwargs.get("post_apply_manual_refuel_check_callback"))
            self._active = False
            events.append("simulation_calibration_dialog_init")

        def activate_session(self, mode="calibration"):
            self._active = True

        def deactivate_session(self, reason="closed"):
            self._active = False

        def session_is_active(self):
            return self._active

    class _SimulationManualRefuelDialog:
        def __init__(self, main_window_arg, model_arg, controller_arg, **kwargs):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            assert callable(kwargs.get("simulation_outcome_callback"))
            assert kwargs.get("expected_calibration_fingerprint") == "stream-fingerprint"
            self.finished = _SignalStub()
            events.append("simulation_manual_refuel_dialog_init")

        def exec(self):
            events.append("simulation_manual_refuel_dialog_exec")
            return 0

    monkeypatch.setattr(
        View.CalibrationClasses,
        "DropletImagingDialog",
        _SimulationCalibrationDialog,
    )
    monkeypatch.setattr(
        View.CalibrationClasses,
        "ManualRefuelCheckDialog",
        _SimulationManualRefuelDialog,
    )

    dialog = box._launch_simulation_calibration_dialog()
    assert dialog is box._droplet_imager_dialog
    assert box._pressure_render_suspended is True
    assert not box.calibrate_pressure_button.isEnabled()
    assert box.request_manual_refuel_check_after_imager_close() is True

    dialog.close()
    qapp.processEvents()

    assert box._droplet_imager_dialog is dialog
    assert box._droplet_imager_dialog_state == "inactive"
    assert box._pressure_render_suspended is False
    assert box.calibrate_pressure_button.isEnabled()
    assert box._manual_refuel_check_after_imager_pending is False
    controller.move_to_location.assert_called_once()
    move_call = controller.move_to_location.call_args
    assert move_call.args == ("loading",)
    assert move_call.kwargs["manual"] is True
    assert callable(move_call.kwargs["on_complete"])

    move_call.kwargs["on_complete"]()
    qapp.processEvents()

    assert box._manual_refuel_check_launch_is_active() is False
    box.manual_refuel_check()
    assert events == [
        "simulation_calibration_dialog_init",
        "simulation_manual_refuel_dialog_init",
        "simulation_manual_refuel_dialog_exec",
        "simulation_manual_refuel_dialog_init",
        "simulation_manual_refuel_dialog_exec",
    ]
    assert popups == []


def test_current_profile_manual_refuel_check_rejects_duplicate_while_dialog_open(monkeypatch, qapp):
    events = []
    popups = []
    main_window = _make_main_window(CURRENT_PROFILE, popups)
    model = _make_model(
        _FakeMachineModel(
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
        ),
        events,
        printer_head=object(),
    )
    controller = _make_controller(events)
    box = PressurePlotBox(main_window, model, controller)

    class _ManualRefuelDialog:
        def __init__(self, main_window_arg, model_arg, controller_arg):
            assert main_window_arg is main_window
            assert model_arg is model
            assert controller_arg is controller
            self.finished = _SignalStub()
            events.append("manual_refuel_dialog_init")

        def show(self):
            events.append("manual_refuel_dialog_show")

        def raise_(self):
            events.append("manual_refuel_dialog_raise")

        def activateWindow(self):
            events.append("manual_refuel_dialog_activate")

        def exec(self):
            events.append("manual_refuel_dialog_exec")
            box.manual_refuel_check()
            return 0

    monkeypatch.setattr(View.CalibrationClasses, "ManualRefuelCheckDialog", _ManualRefuelDialog)

    box.manual_refuel_check()

    assert events == [
        "manual_refuel_dialog_init",
        "manual_refuel_dialog_exec",
        "manual_refuel_dialog_show",
        "manual_refuel_dialog_raise",
        "manual_refuel_dialog_activate",
    ]
    assert popups == [
        (
            "Manual Refuel Check Already Open",
            "The manual refuel check is already opening or open. Close it before starting another check.",
        )
    ]
    assert controller.get_print_array_imaging_calibration_preflight.call_count == 1
    assert controller.get_print_array_refuel_check_preflight.call_count == 1


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
        "enable_print_profile",
        "droplet_dialog_init",
        "droplet_dialog_activate:calibration",
        "droplet_dialog_exec",
        "disable_print_profile",
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
        "disable_print_profile",
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
        "disable_print_profile",
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
            self.deactivate_session("done")
            self.finished.emit(0)
            return 0

    monkeypatch.setattr(View, "MassCalibrationDialog", _MassDialog)
    monkeypatch.setattr(View.CalibrationClasses, "DropletImagingDialog", _DropletDialog)

    box.calibrate_pressure()

    assert events == ["mass_dialog_init", "mass_dialog_exec"]
    controller.move_to_location.assert_not_called()
    controller.disconnect_droplet_camera_signals.assert_not_called()
    controller.connect_droplet_camera_signals.assert_not_called()
    controller.enable_print_profile.assert_not_called()
    model.reload_droplet_model.assert_not_called()
