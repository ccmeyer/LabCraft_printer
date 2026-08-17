from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtCharts
from PySide6.QtTest import QSignalSpy

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs
from tests.test_calibration_memory_ui_recommendation import (
    _build_real_dialog_for_layout,
)


ensure_calibration_import_stubs()


PRINT_PROFILES = [
    {
        "id": "water_droplet",
        "name": "Water - droplet",
        "mode": "droplet",
        "print_pressure": 0.6,
        "refuel_pressure": 0.3,
        "print_pulse_width": 1300,
        "refuel_pulse_width": 3000,
    },
    {
        "id": "water_stream",
        "name": "Water - stream",
        "mode": "stream",
        "print_pressure": 0.8,
        "refuel_pressure": 0.8,
        "print_pulse_width": 2500,
        "refuel_pulse_width": 6000,
    },
    {
        "id": "protein_stream",
        "name": "Protein - stream",
        "mode": "stream",
        "print_pressure": 1.2,
        "refuel_pressure": 1.4,
        "print_pulse_width": 2500,
        "refuel_pulse_width": 8000,
    },
]


@pytest.fixture
def printing_dialog(monkeypatch, qapp):
    main_window = SimpleNamespace(color_dict={})
    dialog = _build_real_dialog_for_layout(
        monkeypatch,
        qapp,
        main_window=main_window,
    )
    settings = {
        "current_print": 0.62,
        "current_refuel": 0.32,
        "target_print": 0.65,
        "target_refuel": 0.35,
        "print_pw": 1400,
        "refuel_pw": 3100,
    }
    connection = {"connected": True}
    machine_model = dialog.model.machine_model
    camera_model = dialog.model.droplet_camera_model
    camera_model.get_flash_duration = lambda: camera_model.flash_duration
    camera_model.get_flash_delay = lambda: camera_model.flash_delay
    camera_model.get_num_droplets = lambda: camera_model.num_droplets
    camera_model.get_exposure_time = lambda: camera_model.exposure_time
    machine_model.machine_connected = True
    machine_model.is_connected = lambda: connection["connected"]
    machine_model.get_current_print_pressure = lambda: settings["current_print"]
    machine_model.get_current_refuel_pressure = lambda: settings["current_refuel"]
    machine_model.get_target_print_pressure = lambda: settings["target_print"]
    machine_model.get_target_refuel_pressure = lambda: settings["target_refuel"]
    machine_model.get_print_pulse_width = lambda: settings["print_pw"]
    machine_model.get_refuel_pulse_width = lambda: settings["refuel_pw"]
    pressure_histories = {
        "print": [0.50, 0.58, 0.62],
        "refuel": [0.25, 0.29, 0.32],
    }
    machine_model.get_print_pressure_readings = lambda: list(
        pressure_histories["print"]
    )
    machine_model.get_refuel_pressure_readings = lambda: list(
        pressure_histories["refuel"]
    )
    dialog.model.print_profiles = [dict(profile) for profile in PRINT_PROFILES]
    head = SimpleNamespace(printing_mode="droplet")
    dialog.model.rack_model = SimpleNamespace(
        get_gripper_printer_head=lambda: head
    )
    calls = []

    def set_value(key, value, name, **kwargs):
        settings[key] = value
        calls.append((name, value, dict(kwargs)))
        machine_model.printing_parameters_updated.emit()
        return True

    dialog.controller.set_absolute_print_pressure = lambda value, **kwargs: set_value(
        "target_print", float(value), "print_pressure", **kwargs
    )
    dialog.controller.set_absolute_refuel_pressure = lambda value, **kwargs: set_value(
        "target_refuel", float(value), "refuel_pressure", **kwargs
    )
    dialog.controller.set_print_pulse_width = lambda value, **kwargs: set_value(
        "print_pw", int(value), "print_pw", **kwargs
    )
    dialog.controller.set_refuel_pulse_width = lambda value, **kwargs: set_value(
        "refuel_pw", int(value), "refuel_pw", **kwargs
    )
    dialog.controller.set_relative_print_pressure = lambda value, **kwargs: calls.append(
        ("relative_print", float(value), dict(kwargs))
    )
    dialog.controller.set_relative_refuel_pressure = lambda value, **kwargs: calls.append(
        ("relative_refuel", float(value), dict(kwargs))
    )

    def apply_profile(profile, callback=None):
        calls.append(("profile", str(profile["id"]), {}))
        settings.update(
            target_print=float(profile["print_pressure"]),
            target_refuel=float(profile["refuel_pressure"]),
            print_pw=int(profile["print_pulse_width"]),
            refuel_pw=int(profile["refuel_pulse_width"]),
        )
        machine_model.printing_parameters_updated.emit()
        if callable(callback):
            callback()
        return True

    dialog.controller.apply_print_profile = apply_profile
    dialog.refresh_calibration_memory_recommendation = lambda *args, **kwargs: None
    dialog._refresh_print_profile_options()
    dialog._sync_printing_controls_from_model(force=True)
    dialog._refresh_manual_control_lock_state()
    dialog.show()
    qapp.processEvents()
    yield SimpleNamespace(
        dialog=dialog,
        settings=settings,
        connection=connection,
        calls=calls,
        head=head,
        machine_model=machine_model,
        pressure_histories=pressure_histories,
    )
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def _profile_ids(dialog):
    return [
        dialog.print_profile_combo.itemData(index)["id"]
        for index in range(dialog.print_profile_combo.count())
    ]


def test_printing_controls_show_feedback_commit_settings_and_filter_profiles(
    printing_dialog,
    qapp,
):
    host = printing_dialog
    dialog = host.dialog

    assert dialog.printing_controls_toggle.isChecked()
    assert dialog.printing_controls_content.isVisible()
    assert dialog.current_print_pressure_value.text() == "0.62 psi"
    assert dialog.current_refuel_pressure_value.text() == "0.32 psi"
    assert _profile_ids(dialog) == ["water_droplet"]
    assert "Workflow: Droplet" in dialog.printing_mode_status_label.text()

    dialog.target_print_pressure_spinbox.setValue(0.72)
    dialog.target_refuel_pressure_spinbox.setValue(0.42)
    dialog.print_pulse_width_spinbox.setValue(1450)
    dialog.refuel_pulse_width_spinbox.setValue(3250)
    qapp.processEvents()

    assert host.settings["target_print"] == 0.72
    assert host.settings["target_refuel"] == 0.42
    assert host.settings["print_pw"] == 1450
    assert host.settings["refuel_pw"] == 3250
    assert [call[0] for call in host.calls] == [
        "print_pressure",
        "refuel_pressure",
        "print_pw",
        "refuel_pw",
    ]
    assert all(call[2]["manual"] is True for call in host.calls)

    host.settings["current_print"] = 0.71
    host.settings["current_refuel"] = 0.41
    host.machine_model.pressure_updated.emit()
    qapp.processEvents()
    assert dialog.current_print_pressure_value.text() == "0.71 psi"
    assert dialog.current_refuel_pressure_value.text() == "0.41 psi"

    dialog.calibration_tabs.setCurrentWidget(dialog.stream_tab)
    qapp.processEvents()
    assert _profile_ids(dialog) == ["water_stream", "protein_stream"]
    assert "Workflow: Stream" in dialog.printing_mode_status_label.text()
    assert host.head.printing_mode == "droplet"
    dialog.print_profile_combo.setCurrentIndex(1)
    dialog.calibration_tabs.setCurrentWidget(dialog.droplet_tab)
    dialog.calibration_tabs.setCurrentWidget(dialog.stream_tab)
    qapp.processEvents()
    assert dialog.print_profile_combo.currentData()["id"] == "protein_stream"

    dialog.calibration_tabs.setCurrentWidget(dialog.debug_tab)
    qapp.processEvents()
    assert dialog.printing_controls_section.isHidden()


def test_profile_application_waits_for_callback_and_preserves_head_mode(
    printing_dialog,
    qapp,
):
    host = printing_dialog
    dialog = host.dialog
    pending = {}

    def apply_later(profile, callback=None):
        pending["profile"] = dict(profile)
        pending["callback"] = callback
        return True

    dialog.controller.apply_print_profile = apply_later
    assert dialog.print_profile_apply_button.text() == "Apply"

    dialog.print_profile_apply_button.click()
    qapp.processEvents()
    assert dialog.print_profile_apply_button.text() == "Applying..."
    assert dialog.target_print_pressure_spinbox.isEnabled() is False
    assert dialog.refuel_pulse_width_spinbox.isEnabled() is False

    profile = pending["profile"]
    host.settings.update(
        target_print=profile["print_pressure"],
        target_refuel=profile["refuel_pressure"],
        print_pw=profile["print_pulse_width"],
        refuel_pw=profile["refuel_pulse_width"],
    )
    host.machine_model.printing_parameters_updated.emit()
    assert dialog.print_profile_apply_button.text() == "Applying..."
    pending["callback"]()
    qapp.processEvents()

    assert dialog.print_profile_apply_button.text() == "Loaded"
    assert dialog.target_print_pressure_spinbox.value() == 0.6
    assert dialog.target_refuel_pressure_spinbox.value() == 0.3
    assert dialog.print_pulse_width_spinbox.value() == 1300
    assert dialog.refuel_pulse_width_spinbox.value() == 3000
    assert host.head.printing_mode == "droplet"
    assert dialog.target_print_pressure_spinbox.isEnabled() is True
    assert dialog.target_refuel_pressure_spinbox.isEnabled() is True
    assert dialog.print_pulse_width_spinbox.isEnabled() is True
    assert dialog.refuel_pulse_width_spinbox.isEnabled() is True
    assert dialog.print_profile_combo.isEnabled() is True

    dialog.target_print_pressure_spinbox.setValue(0.68)
    qapp.processEvents()

    assert host.settings["target_print"] == 0.68
    assert dialog.print_profile_apply_button.text() == "Apply"


def test_printing_controls_and_pressure_shortcuts_fail_closed(
    printing_dialog,
    qapp,
):
    host = printing_dialog
    dialog = host.dialog

    assert dialog._handle_relative_pressure_shortcut("print", 0.01) is True
    assert host.calls[-1][0] == "relative_print"
    baseline_count = len(host.calls)

    host.connection["connected"] = False
    host.machine_model.machine_connected = False
    host.machine_model.machine_state_updated.emit(False)
    qapp.processEvents()
    assert dialog.target_print_pressure_spinbox.isEnabled() is False
    assert dialog.print_profile_apply_button.isEnabled() is False
    assert dialog._handle_relative_pressure_shortcut("refuel", 0.1) is False
    assert len(host.calls) == baseline_count

    host.connection["connected"] = True
    host.machine_model.machine_connected = True
    host.machine_model.machine_state_updated.emit(True)
    dialog.model.calibration_manager.activeCalibration = object()
    dialog._refresh_manual_control_lock_state()
    assert dialog.target_refuel_pressure_spinbox.isEnabled() is False
    assert dialog._handle_relative_pressure_shortcut("print", -0.1) is False

    dialog.model.calibration_manager.activeCalibration = None
    dialog.droplet_camera_model.flash_fault_latched = True
    dialog._refresh_manual_control_lock_state()
    assert dialog.print_pulse_width_spinbox.isEnabled() is False
    assert dialog.print_profile_combo.isEnabled() is False
    assert len(host.calls) == baseline_count


def test_transport_fault_releases_pending_profile_without_sending_more_commands(
    printing_dialog,
    qapp,
):
    host = printing_dialog
    dialog = host.dialog
    dialog.controller.apply_print_profile = lambda _profile, callback=None: True

    dialog.print_profile_apply_button.click()
    qapp.processEvents()
    assert dialog._print_profile_apply_pending is True
    assert dialog.print_profile_apply_button.text() == "Applying..."

    dialog._handle_printing_controls_transport_fault({"summary": "test fault"})
    qapp.processEvents()
    assert dialog._print_profile_apply_pending is False
    assert dialog.print_profile_apply_button.text() == "Apply"
    assert dialog.target_print_pressure_spinbox.isEnabled() is True
    assert host.calls == []


def test_live_pressure_plot_renders_four_series_on_every_tab(printing_dialog, qapp):
    host = printing_dialog
    dialog = host.dialog
    dialog.live_pressure_render_timer.stop()
    dialog._render_live_pressure_plot()

    assert dialog.live_pressure_toggle.isChecked()
    assert dialog.live_pressure_content.isVisible()
    assert [
        dialog.live_print_pressure_series.name(),
        dialog.live_refuel_pressure_series.name(),
        dialog.live_target_print_pressure_series.name(),
        dialog.live_target_refuel_pressure_series.name(),
    ] == ["Print", "Refuel", "Print target", "Refuel target"]
    assert dialog.live_print_pressure_series.pen().color().name() == "#275fb8"
    assert dialog.live_refuel_pressure_series.pen().color().name() == "#ffffff"
    assert (
        dialog.live_target_print_pressure_series.pen().color()
        == dialog.live_print_pressure_series.pen().color()
    )
    assert (
        dialog.live_target_refuel_pressure_series.pen().color()
        == dialog.live_refuel_pressure_series.pen().color()
    )
    for series in (
        dialog.live_print_pressure_series,
        dialog.live_refuel_pressure_series,
    ):
        assert series.pen().widthF() == pytest.approx(1.25)
        assert series.pen().style() == QtCore.Qt.PenStyle.SolidLine
    for series in (
        dialog.live_target_print_pressure_series,
        dialog.live_target_refuel_pressure_series,
    ):
        assert series.pen().widthF() == pytest.approx(1.25)
        assert series.pen().style() == QtCore.Qt.PenStyle.DashLine
    assert dialog.live_pressure_chart.property("pressureLegendEntries") == [
        "Print",
        "Refuel",
    ]
    assert (
        dialog.live_pressure_chart.animationOptions()
        == QtCharts.QChart.AnimationOption.NoAnimation
    )
    assert dialog.live_print_pressure_series.count() == 3
    assert dialog.live_print_pressure_series.at(2).y() == pytest.approx(0.62)
    assert dialog.live_refuel_pressure_series.at(2).y() == pytest.approx(0.32)
    assert dialog.live_target_print_pressure_series.at(1).y() == pytest.approx(0.65)
    assert dialog.live_target_refuel_pressure_series.at(1).y() == pytest.approx(0.35)
    assert dialog.live_pressure_axis_x.titleText() == "Recent samples"
    assert dialog.live_pressure_axis_y.titleText() == "Pressure (psi)"
    assert dialog.live_pressure_axis_y.min() >= 0.0
    assert dialog.live_pressure_axis_y.min() < 0.25
    assert dialog.live_pressure_axis_y.max() > 0.65

    for tab in (
        dialog.droplet_tab,
        dialog.stream_tab,
        dialog.debug_tab,
        dialog.optics_tab,
    ):
        dialog.calibration_tabs.setCurrentWidget(tab)
        qapp.processEvents()
        assert dialog.live_pressure_section.isVisible()


def test_live_pressure_plot_coalesces_targets_and_stops_while_collapsed(
    printing_dialog,
    qapp,
):
    host = printing_dialog
    dialog = host.dialog
    dialog.live_pressure_render_timer.stop()
    timer_spy = QSignalSpy(dialog.live_pressure_render_timer.timeout)

    for _ in range(20):
        host.machine_model.pressure_updated.emit()
    qapp.processEvents()
    assert dialog.live_pressure_render_timer.isSingleShot()
    assert dialog.live_pressure_render_timer.interval() == 100
    assert dialog.live_pressure_render_timer.isActive()

    host.pressure_histories["print"] = [0.7, 0.8]
    host.pressure_histories["refuel"] = [0.4, 0.5]
    assert timer_spy.wait(1000)
    assert timer_spy.count() == 1
    assert dialog.live_print_pressure_series.at(1).y() == pytest.approx(0.8)
    assert dialog.live_refuel_pressure_series.at(1).y() == pytest.approx(0.5)

    host.settings["target_print"] = 0.9
    host.settings["target_refuel"] = 0.45
    host.machine_model.printing_parameters_updated.emit()
    assert timer_spy.wait(1000)
    assert dialog.live_target_print_pressure_series.at(1).y() == pytest.approx(0.9)
    assert dialog.live_target_refuel_pressure_series.at(1).y() == pytest.approx(0.45)

    dialog.live_pressure_toggle.click()
    qapp.processEvents()
    prior_latest = dialog.live_print_pressure_series.at(1).y()
    host.pressure_histories["print"] = [1.0, 1.1]
    host.machine_model.pressure_updated.emit()
    assert not dialog.live_pressure_render_timer.isActive()
    assert dialog.live_print_pressure_series.at(1).y() == pytest.approx(prior_latest)

    dialog.live_pressure_toggle.click()
    qapp.processEvents()
    assert dialog.live_print_pressure_series.at(1).y() == pytest.approx(1.1)

    host.machine_model.pressure_updated.emit()
    assert dialog.live_pressure_render_timer.isActive()
    dialog._imager_force_close_requested = True
    dialog.close()
    qapp.processEvents()
    assert not dialog.live_pressure_render_timer.isActive()
    assert dialog._live_pressure_closing is True
