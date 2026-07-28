from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6 import QtWidgets

from CalibrationClasses.View import DropletImagingDialog


def _dialog_with_plan_state(state):
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    QtWidgets.QDialog.__init__(dialog)
    plan_state = SimpleNamespace(value=state) if state is not None else None
    experiment_model = SimpleNamespace(
        get_execution_plan_snapshot=lambda: (
            SimpleNamespace(state=plan_state) if plan_state is not None else None
        )
    )
    dialog.model = SimpleNamespace(
        experiment_model=experiment_model,
        calibration_manager=SimpleNamespace(
            activeCalibration=None,
            calibration_queue=[],
            has_open_stream_calibration_sequence=lambda: False,
            has_open_droplet_calibration_sequence=lambda: False,
        ),
    )
    dialog._set_calibration_action_text = Mock()
    dialog._refresh_manual_control_lock_state = Mock()
    return dialog


def _click_message_box_button(message_box, text):
    button = next(
        button for button in message_box.buttons() if button.text() == text
    )
    button.click()


def test_prepared_volume_calibration_confirmation_has_safe_default(
    qapp,
    monkeypatch,
):
    dialog = _dialog_with_plan_state("prepared")
    observed = {}

    def cancel(message_box):
        observed["default"] = message_box.defaultButton().text()
        observed["escape"] = message_box.escapeButton().text()
        observed["text"] = message_box.text()
        observed["detail"] = message_box.informativeText()
        _click_message_box_button(message_box, "Cancel")
        return 0

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", cancel)

    assert dialog._confirm_first_volume_calibration_lock() is False
    assert observed["default"] == "Cancel"
    assert observed["escape"] == "Cancel"
    assert "lock this experiment design" in observed["text"]
    assert "reagents, targets, wells, and design volumes" in observed["detail"]
    assert "has not yet dispensed" in observed["detail"]


def test_prepared_volume_calibration_confirmation_accepts_start(
    qapp,
    monkeypatch,
):
    dialog = _dialog_with_plan_state("prepared")

    def accept(message_box):
        _click_message_box_button(message_box, "Start Calibration")
        return 0

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", accept)

    assert dialog._confirm_first_volume_calibration_lock() is True


def test_volume_calibration_cancel_precedes_mode_preflight_and_queue_changes(qapp):
    dialog = _dialog_with_plan_state("prepared")
    original_queue = dialog.model.calibration_manager.calibration_queue
    dialog._confirm_first_volume_calibration_lock = Mock(return_value=False)
    dialog._start_mode_guarded_calibration = Mock()
    start_callback = Mock()

    result = dialog._start_volume_calibration(
        "stream",
        "online_stream_calibration",
        start_callback,
    )

    assert result is False
    dialog._start_mode_guarded_calibration.assert_not_called()
    start_callback.assert_not_called()
    assert dialog.model.calibration_manager.calibration_queue is original_queue
    assert original_queue == []


def test_volume_calibration_confirmation_is_prepared_only(
    qapp,
    monkeypatch,
):
    state = {"value": "prepared"}
    dialog = _dialog_with_plan_state("prepared")
    dialog.model.experiment_model.get_execution_plan_snapshot = lambda: (
        SimpleNamespace(state=SimpleNamespace(value=state["value"]))
    )
    prompts = {"count": 0}

    def accept(message_box):
        prompts["count"] += 1
        _click_message_box_button(message_box, "Start Calibration")
        return 0

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", accept)
    dialog._start_mode_guarded_calibration = Mock(return_value=True)

    assert dialog._start_volume_calibration("droplet", "first", Mock()) is True
    state["value"] = "active"
    assert dialog._start_volume_calibration("droplet", "later", Mock()) is True

    assert prompts["count"] == 1
    assert dialog._start_mode_guarded_calibration.call_count == 2


@pytest.mark.parametrize(
    "method_name,requested_mode,action_key,controller_method",
    [
        (
            "toggle_start_pressure_sweep_calibration",
            "droplet",
            "pressure_sweep_characterization",
            "start_pressure_sweep_characterization",
        ),
        (
            "toggle_start_online_stream_calibration",
            "stream",
            "online_stream_calibration",
            "start_online_stream_calibration",
        ),
        (
            "toggle_start_all_stream_calibration",
            "stream",
            "stream_calibrate_all",
            "start_stream_calibration_sequence",
        ),
        (
            "toggle_start_all_calibration",
            "droplet",
            "calibrate_all",
            "start_droplet_calibration_sequence",
        ),
    ],
)
def test_volume_affecting_start_paths_use_confirmation_guard(
    qapp,
    method_name,
    requested_mode,
    action_key,
    controller_method,
):
    dialog = _dialog_with_plan_state("prepared")
    controller_callback = Mock()
    dialog.controller = SimpleNamespace(
        stop_calibration=Mock(),
        start_pressure_sweep_characterization=Mock(),
        start_online_stream_calibration=Mock(),
        start_stream_calibration_sequence=Mock(),
        start_droplet_calibration_sequence=Mock(),
    )
    setattr(dialog.controller, controller_method, controller_callback)
    dialog._start_volume_calibration = Mock(return_value=True)
    dialog._get_calibrate_all_pressure_scan_mode = Mock(return_value="band")

    getattr(dialog, method_name)()

    requested = dialog._start_volume_calibration.call_args.args
    assert requested[:2] == (requested_mode, action_key)
    assert callable(requested[2])


def test_nonvolume_pressure_scan_keeps_existing_mode_guard(qapp):
    dialog = _dialog_with_plan_state("prepared")
    dialog.controller = SimpleNamespace(
        stop_calibration=Mock(),
        start_pressure_scan_calibration=Mock(),
    )
    dialog._start_mode_guarded_calibration = Mock(return_value=True)
    dialog._start_volume_calibration = Mock()

    dialog.toggle_start_pressure_scan_calibration()

    dialog._start_mode_guarded_calibration.assert_called_once_with(
        "droplet",
        "pressure_scan",
        dialog.controller.start_pressure_scan_calibration,
    )
    dialog._start_volume_calibration.assert_not_called()
