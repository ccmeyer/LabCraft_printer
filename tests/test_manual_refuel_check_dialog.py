from types import SimpleNamespace
from unittest.mock import Mock

from PySide6 import QtCore, QtGui, QtWidgets

from CalibrationClasses.View import ManualRefuelCheckDialog


def _make_dialog(qapp, *, queue_idle=True, record_result=None):
    controller = SimpleNamespace(
        check_if_all_completed=Mock(return_value=queue_idle),
        move_to_location=Mock(return_value=True),
        refuel_only=Mock(return_value=True),
        print_only=Mock(return_value=True),
        print_droplets=Mock(return_value=True),
        set_relative_refuel_pressure=Mock(return_value=True),
        record_manual_refuel_check_outcome=Mock(
            return_value=record_result if record_result is not None else {"status": "passed"}
        ),
        pause_commands=Mock(),
        start_refuel_camera=Mock(),
        capture_refuel_image=Mock(),
        stop_refuel_camera=Mock(),
    )
    model = SimpleNamespace()
    dialog = ManualRefuelCheckDialog(None, model, controller)
    return dialog, controller


def _activate_shortcut(dialog, key_sequence):
    expected = QtGui.QKeySequence(key_sequence).toString().lower()
    for shortcut in dialog._shortcut_handles:
        if shortcut.key().toString().lower() == expected:
            shortcut.activated.emit()
            return shortcut
    raise AssertionError(f"Shortcut {key_sequence!r} not found")


def _grid_position(layout, widget):
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.widget() is widget:
            row, column, _row_span, _column_span = layout.getItemPosition(index)
            return row, column
    raise AssertionError(f"{widget!r} not found in grid")


def _layout_widgets(layout):
    return [
        layout.itemAt(index).widget()
        for index in range(layout.count())
        if layout.itemAt(index).widget() is not None
    ]


def test_manual_refuel_check_defaults_and_guidance_are_visible(qapp):
    dialog, _controller = _make_dialog(qapp)

    assert dialog.trial_droplets_spin.value() == 5
    group_titles = {group.title() for group in dialog.findChildren(QtWidgets.QGroupBox)}
    visible_text = "\n".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))

    assert {"1. Center level", "2. Run paired trial", "3. Record result"}.issubset(group_titles)
    assert "Step 1" in dialog.status_label.text()
    assert "middle of the channel" in visible_text
    assert "Run paired print/refuel droplets" in visible_text
    assert "Run a paired trial before recording" in visible_text
    assert "Shortcuts:" in dialog.shortcut_help_label.text()
    assert "Refuel only 20 pulses (z)" in dialog.shortcut_help_label.text()
    assert "Print only 20 pulses (v)" in dialog.shortcut_help_label.text()
    assert "+1.0 psi (4)" in dialog.shortcut_help_label.text()
    assert "w/e/r/t paired trial 1/5/10/20" in dialog.shortcut_help_label.text()


def test_manual_refuel_check_visual_control_order_and_labels(qapp):
    dialog, _controller = _make_dialog(qapp)

    assert dialog.refuel_20_button.text() == "Refuel only 20 pulses (z)"
    assert dialog.refuel_5_button.text() == "Refuel only 5 pulses (x)"
    assert dialog.print_only_5_button.text() == "Print only 5 pulses (c)"
    assert dialog.print_only_20_button.text() == "Print only 20 pulses (v)"
    assert dialog.increase_level_label.text() == "Increase level"
    assert dialog.decrease_level_label.text() == "Decrease level"

    assert _grid_position(dialog.pulse_grid, dialog.increase_level_label) == (0, 0)
    assert _grid_position(dialog.pulse_grid, dialog.refuel_20_button) == (0, 1)
    assert _grid_position(dialog.pulse_grid, dialog.refuel_5_button) == (1, 1)
    assert _grid_position(dialog.pulse_grid, dialog.print_only_5_button) == (2, 1)
    assert _grid_position(dialog.pulse_grid, dialog.decrease_level_label) == (3, 0)
    assert _grid_position(dialog.pulse_grid, dialog.print_only_20_button) == (3, 1)

    assert dialog.center_level_divider.frameShape() == QtWidgets.QFrame.VLine
    assert dialog.refuel_20_button.property("manual_refuel_style_role") == "increase_strong"
    assert dialog.refuel_5_button.property("manual_refuel_style_role") == "increase_soft"
    assert dialog.print_only_5_button.property("manual_refuel_style_role") == "decrease_soft"
    assert dialog.print_only_20_button.property("manual_refuel_style_role") == "decrease_strong"


def test_manual_refuel_check_button_styles_use_app_like_shaded_fills(qapp):
    dialog, _controller = _make_dialog(qapp)

    assert "#063f99" in dialog.refuel_20_button.styleSheet()
    assert "#275fb8" in dialog.refuel_5_button.styleSheet()
    assert "#a92222" in dialog.print_only_5_button.styleSheet()
    assert "#8a0303" in dialog.print_only_20_button.styleSheet()
    assert "color: #ffffff" in dialog.refuel_20_button.styleSheet()
    assert "qlineargradient" in dialog.refuel_20_button.styleSheet()
    assert "QPushButton:hover" in dialog.refuel_20_button.styleSheet()
    assert "QPushButton:pressed" in dialog.refuel_20_button.styleSheet()
    assert "border: 1px solid #4d4d4d" in dialog.refuel_20_button.styleSheet()
    assert "border: 1px solid #063f99" not in dialog.refuel_20_button.styleSheet()


def test_manual_refuel_check_pressure_buttons_are_ordered_by_effect(qapp):
    dialog, _controller = _make_dialog(qapp)

    assert [button.text() for button in _layout_widgets(dialog.pressure_layout)] == [
        "+1.0 psi (4)",
        "+0.1 psi (3)",
        "-0.1 psi (2)",
        "-1.0 psi (1)",
    ]
    assert [button.property("manual_refuel_style_role") for button in dialog.refuel_pressure_buttons] == [
        "increase_strong",
        "increase_soft",
        "decrease_soft",
        "decrease_strong",
    ]


def test_manual_refuel_check_outcome_buttons_are_vertical_and_semantic(qapp):
    dialog, _controller = _make_dialog(qapp)

    assert [button.text() for button in _layout_widgets(dialog.outcome_button_layout)] == [
        "Stable",
        "Level moved up",
        "Level moved down",
        "Unclear",
    ]
    assert [button.property("manual_refuel_style_role") for button in dialog.outcome_buttons] == [
        "stable",
        "increase_soft",
        "decrease_soft",
        "neutral",
    ]


def test_manual_refuel_check_buttons_queue_existing_manual_commands(qapp):
    dialog, controller = _make_dialog(qapp)

    dialog.move_loading_button.click()
    dialog.refuel_5_button.click()
    dialog.refuel_20_button.click()
    dialog.print_only_5_button.click()
    dialog.print_only_20_button.click()
    dialog.trial_droplets_spin.setValue(12)
    dialog.run_trial_button.click()

    controller.move_to_location.assert_called_once_with("loading", manual=True)
    assert controller.refuel_only.call_args_list[0].args == (5,)
    assert controller.refuel_only.call_args_list[0].kwargs == {"manual": True}
    assert controller.refuel_only.call_args_list[1].args == (20,)
    assert controller.refuel_only.call_args_list[1].kwargs == {"manual": True}
    assert controller.print_only.call_args_list[0].args == (5,)
    assert controller.print_only.call_args_list[0].kwargs == {"manual": True}
    assert controller.print_only.call_args_list[1].args == (20,)
    assert controller.print_only.call_args_list[1].kwargs == {"manual": True}
    controller.print_droplets.assert_called_once_with(12, manual=True)
    assert dialog.trial_count == 1
    assert dialog.last_trial_droplet_count == 12
    assert dialog.stable_button.isEnabled()


def test_manual_refuel_check_pressure_buttons_queue_expected_deltas(qapp):
    dialog, controller = _make_dialog(qapp)

    for button in dialog.refuel_pressure_buttons:
        button.click()

    assert [call.args[0] for call in controller.set_relative_refuel_pressure.call_args_list] == [
        1.0,
        0.1,
        -0.1,
        -1.0,
    ]
    assert all(call.kwargs == {"manual": True} for call in controller.set_relative_refuel_pressure.call_args_list)


def test_manual_refuel_check_shortcuts_queue_expected_manual_commands(qapp):
    dialog, controller = _make_dialog(qapp)

    for key in ("1", "2", "3", "4"):
        _activate_shortcut(dialog, key)
    for key in ("z", "x", "c", "v"):
        _activate_shortcut(dialog, key)
    for key in ("w", "e", "r", "t"):
        _activate_shortcut(dialog, key)

    assert [call.args[0] for call in controller.set_relative_refuel_pressure.call_args_list] == [
        -1.0,
        -0.1,
        0.1,
        1.0,
    ]
    assert [call.args[0] for call in controller.refuel_only.call_args_list] == [20, 5]
    assert [call.args[0] for call in controller.print_only.call_args_list] == [5, 20]
    assert [call.args[0] for call in controller.print_droplets.call_args_list] == [1, 5, 10, 20]
    assert all(call.kwargs == {"manual": True} for call in controller.refuel_only.call_args_list)
    assert all(call.kwargs == {"manual": True} for call in controller.print_only.call_args_list)
    assert all(call.kwargs == {"manual": True} for call in controller.print_droplets.call_args_list)
    assert dialog.trial_count == 4
    assert dialog.last_trial_droplet_count == 20
    assert dialog.trial_droplets_spin.value() == 20


def test_manual_refuel_check_shortcuts_do_not_fire_while_trial_count_has_focus(qapp):
    dialog, controller = _make_dialog(qapp)
    dialog.show()
    dialog.trial_droplets_spin.setFocus()
    qapp.processEvents()

    _activate_shortcut(dialog, "1")
    _activate_shortcut(dialog, "e")

    controller.set_relative_refuel_pressure.assert_not_called()
    controller.print_droplets.assert_not_called()
    assert dialog.trial_count == 0


def test_manual_refuel_check_busy_queue_blocks_commands(qapp):
    dialog, controller = _make_dialog(qapp, queue_idle=False)

    dialog.move_loading_button.click()
    dialog.refuel_5_button.click()
    dialog.print_only_5_button.click()
    dialog.run_trial_button.click()
    dialog.refuel_pressure_buttons[0].click()

    controller.move_to_location.assert_not_called()
    controller.refuel_only.assert_not_called()
    controller.print_only.assert_not_called()
    controller.print_droplets.assert_not_called()
    controller.set_relative_refuel_pressure.assert_not_called()
    assert "Commands are still running" in dialog.status_label.text()


def test_manual_refuel_check_busy_queue_blocks_outcome_recording(qapp):
    dialog, controller = _make_dialog(qapp, queue_idle=False)
    dialog.trial_count = 1
    dialog.last_trial_droplet_count = 5
    dialog._update_outcome_buttons_enabled()

    dialog.stable_button.click()

    controller.record_manual_refuel_check_outcome.assert_not_called()
    assert "Commands are still running" in dialog.status_label.text()


def test_manual_refuel_check_blocks_outcomes_before_paired_trial(qapp):
    dialog, controller = _make_dialog(qapp)

    assert not dialog.stable_button.isEnabled()
    assert "Run a paired trial" in dialog.stable_button.toolTip()
    assert "Run a paired trial" in dialog.outcome_help_label.text()
    assert dialog.record_outcome("passed", "stable") is False

    controller.record_manual_refuel_check_outcome.assert_not_called()
    assert "Run a paired trial" in dialog.status_label.text()


def test_manual_refuel_check_outcomes_record_status_judgment_and_trial_metadata(qapp):
    dialog, controller = _make_dialog(qapp)
    dialog.trial_droplets_spin.setValue(25)
    dialog.run_trial_button.click()

    dialog.stable_button.click()
    assert "passed" in dialog.status_label.text()
    assert dialog.close_button.text() == "Done"
    assert dialog.close_button.property("manual_refuel_style_role") == "done"
    dialog.level_rose_button.click()
    assert "Decrease refuel pressure" in dialog.status_label.text()
    dialog.level_fell_button.click()
    assert "Increase refuel pressure" in dialog.status_label.text()
    dialog.unclear_button.click()
    assert "unclear" in dialog.status_label.text()

    assert [call.args[:2] for call in controller.record_manual_refuel_check_outcome.call_args_list] == [
        ("passed", "manual_refuel_check_dialog"),
        ("failed", "manual_refuel_check_dialog"),
        ("failed", "manual_refuel_check_dialog"),
        ("unclear", "manual_refuel_check_dialog"),
    ]
    assert [call.kwargs["operator_judgment"] for call in controller.record_manual_refuel_check_outcome.call_args_list] == [
        "stable",
        "level_rose",
        "level_fell",
        "unclear",
    ]
    for call in controller.record_manual_refuel_check_outcome.call_args_list:
        assert call.kwargs["trial_droplet_count"] == 25
        assert call.kwargs["trial_count"] == 1


def test_manual_refuel_check_recording_failure_shows_status_and_stays_open(qapp):
    dialog, _controller = _make_dialog(
        qapp,
        record_result={"ok": False, "message": "recording failed"},
    )
    dialog.show()
    dialog.run_paired_trial()

    assert dialog.record_outcome("passed", "stable") is False

    assert "recording failed" in dialog.status_label.text()
    assert dialog.isVisible() is True


def test_manual_refuel_check_does_not_use_camera_apis(qapp):
    dialog, controller = _make_dialog(qapp)

    dialog.move_loading_button.click()
    dialog.run_trial_button.click()
    dialog.stable_button.click()

    controller.start_refuel_camera.assert_not_called()
    controller.capture_refuel_image.assert_not_called()
    controller.stop_refuel_camera.assert_not_called()


def test_manual_refuel_check_escape_requests_pause_without_closing(qapp):
    dialog, controller = _make_dialog(qapp)
    event = QtGui.QKeyEvent(
        QtCore.QEvent.KeyPress,
        QtCore.Qt.Key_Escape,
        QtCore.Qt.NoModifier,
    )

    dialog.keyPressEvent(event)

    controller.pause_commands.assert_called_once_with()
    assert event.isAccepted()
