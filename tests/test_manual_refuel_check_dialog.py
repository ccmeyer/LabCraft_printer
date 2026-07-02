from types import SimpleNamespace
from unittest.mock import Mock

from PySide6 import QtCore, QtGui

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


def test_manual_refuel_check_pressure_buttons_queue_expected_deltas(qapp):
    dialog, controller = _make_dialog(qapp)

    for button in dialog.refuel_pressure_buttons:
        button.click()

    assert [call.args[0] for call in controller.set_relative_refuel_pressure.call_args_list] == [
        -1.0,
        -0.1,
        0.1,
        1.0,
    ]
    assert all(call.kwargs == {"manual": True} for call in controller.set_relative_refuel_pressure.call_args_list)


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

    dialog.stable_button.click()

    controller.record_manual_refuel_check_outcome.assert_not_called()
    assert "Commands are still running" in dialog.status_label.text()


def test_manual_refuel_check_outcomes_record_status_judgment_and_trial_metadata(qapp):
    dialog, controller = _make_dialog(qapp)
    dialog.trial_droplets_spin.setValue(25)
    dialog.run_trial_button.click()

    dialog.stable_button.click()
    assert "stable" in dialog.status_label.text()
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
