from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QMessageBox

import View
from View import ClearQueueConfirmationDialog, MainWindow, PauseActionDialog


class _PauseDialogStub:
    RESUME = PauseActionDialog.RESUME
    KEEP_PAUSED = PauseActionDialog.KEEP_PAUSED
    REQUEST_CLEAR = PauseActionDialog.REQUEST_CLEAR
    next_action = KEEP_PAUSED
    instances = []

    def __init__(self, parent=None, *, array_active=False):
        self.parent = parent
        self.array_active = bool(array_active)
        self.exec_action = Mock(return_value=self.next_action)
        self.show = Mock()
        self.raise_ = Mock()
        self.activateWindow = Mock()
        self.instances.append(self)


class _ConfirmationDialogStub:
    next_confirmation = False
    instances = []

    def __init__(self, parent=None, *, array_active=False):
        self.parent = parent
        self.array_active = bool(array_active)
        self.exec_confirmed = Mock(return_value=self.next_confirmation)
        self.show = Mock()
        self.raise_ = Mock()
        self.activateWindow = Mock()
        self.instances.append(self)


@pytest.fixture(autouse=True)
def _reset_dialog_stubs():
    _PauseDialogStub.next_action = _PauseDialogStub.KEEP_PAUSED
    _PauseDialogStub.instances = []
    _ConfirmationDialogStub.next_confirmation = False
    _ConfirmationDialogStub.instances = []


def _make_main_window(*, array_state="idle", connected=True, paused=False):
    machine_model = SimpleNamespace(
        machine_connected=bool(connected),
        paused=bool(paused),
    )
    controller = SimpleNamespace(
        pause_commands=Mock(side_effect=lambda: setattr(machine_model, "paused", True)),
        resume_commands=Mock(side_effect=lambda: setattr(machine_model, "paused", False)),
        clear_command_queue=Mock(side_effect=lambda: setattr(machine_model, "paused", False)),
        get_array_run_state=Mock(return_value=array_state),
    )
    main_window = MainWindow.__new__(MainWindow)
    main_window.model = SimpleNamespace(machine_model=machine_model)
    main_window.controller = controller
    main_window.popup_message = Mock()
    main_window._pause_action_flow_active = False
    main_window._pause_action_dialog = None
    return main_window


def _install_dialog_stubs(monkeypatch):
    monkeypatch.setattr(View, "PauseActionDialog", _PauseDialogStub)
    monkeypatch.setattr(View, "ClearQueueConfirmationDialog", _ConfirmationDialogStub)


def test_active_array_pause_sends_one_pause_and_resumes_without_clearing(monkeypatch):
    _install_dialog_stubs(monkeypatch)
    _PauseDialogStub.next_action = _PauseDialogStub.RESUME
    main_window = _make_main_window(array_state="running")

    MainWindow.pause_machine(main_window)

    main_window.controller.pause_commands.assert_called_once_with()
    main_window.controller.resume_commands.assert_called_once_with()
    main_window.controller.clear_command_queue.assert_not_called()
    assert _PauseDialogStub.instances[0].array_active is True


@pytest.mark.parametrize("array_state", ["running", "stop_requested"])
def test_keep_paused_is_non_destructive_for_active_array(monkeypatch, array_state):
    _install_dialog_stubs(monkeypatch)
    main_window = _make_main_window(array_state=array_state)

    MainWindow.pause_machine(main_window)

    main_window.controller.pause_commands.assert_called_once_with()
    main_window.controller.resume_commands.assert_not_called()
    main_window.controller.clear_command_queue.assert_not_called()
    assert main_window.model.machine_model.paused is True
    assert _PauseDialogStub.instances[0].array_active is True


def test_clear_request_requires_confirmation_and_cancel_keeps_paused(monkeypatch):
    _install_dialog_stubs(monkeypatch)
    _PauseDialogStub.next_action = _PauseDialogStub.REQUEST_CLEAR
    _ConfirmationDialogStub.next_confirmation = False
    main_window = _make_main_window(array_state="running")

    MainWindow.pause_machine(main_window)

    main_window.controller.clear_command_queue.assert_not_called()
    assert main_window.model.machine_model.paused is True
    assert len(_ConfirmationDialogStub.instances) == 1
    assert _ConfirmationDialogStub.instances[0].array_active is True


def test_confirmed_clear_aborts_exactly_once(monkeypatch):
    _install_dialog_stubs(monkeypatch)
    _PauseDialogStub.next_action = _PauseDialogStub.REQUEST_CLEAR
    _ConfirmationDialogStub.next_confirmation = True
    main_window = _make_main_window(array_state="running")

    MainWindow.pause_machine(main_window)

    main_window.controller.clear_command_queue.assert_called_once_with()
    main_window.controller.resume_commands.assert_not_called()


def test_non_array_pause_uses_generic_dialog(monkeypatch):
    _install_dialog_stubs(monkeypatch)
    main_window = _make_main_window(array_state="idle")

    MainWindow.pause_machine(main_window)

    assert _PauseDialogStub.instances[0].array_active is False
    assert _ConfirmationDialogStub.instances == []


def test_already_paused_reopens_actions_without_duplicate_pause(monkeypatch):
    _install_dialog_stubs(monkeypatch)
    main_window = _make_main_window(array_state="running", paused=True)

    MainWindow.pause_machine(main_window)

    main_window.controller.pause_commands.assert_not_called()
    assert len(_PauseDialogStub.instances) == 1


def test_reentrant_pause_focuses_existing_dialog_without_dispatch(monkeypatch):
    _install_dialog_stubs(monkeypatch)
    main_window = _make_main_window(array_state="running", paused=True)
    active_dialog = _PauseDialogStub(main_window, array_active=True)
    main_window._pause_action_flow_active = True
    main_window._pause_action_dialog = active_dialog

    MainWindow.pause_machine(main_window)

    active_dialog.show.assert_called_once_with()
    active_dialog.raise_.assert_called_once_with()
    active_dialog.activateWindow.assert_called_once_with()
    main_window.controller.pause_commands.assert_not_called()
    main_window.controller.resume_commands.assert_not_called()
    main_window.controller.clear_command_queue.assert_not_called()


def test_disconnected_pause_shows_unavailable_without_dispatch(monkeypatch):
    _install_dialog_stubs(monkeypatch)
    main_window = _make_main_window(connected=False)

    MainWindow.pause_machine(main_window)

    main_window.popup_message.assert_called_once_with(
        "Pause Unavailable",
        "The machine is not connected, so there are no machine commands to pause.",
    )
    main_window.controller.pause_commands.assert_not_called()
    main_window.controller.resume_commands.assert_not_called()
    main_window.controller.clear_command_queue.assert_not_called()
    assert _PauseDialogStub.instances == []


def test_array_pause_dialog_copy_and_safe_defaults(qapp):
    dialog = PauseActionDialog(array_active=True)

    assert dialog.windowTitle() == "Print Array Paused Immediately"
    assert "current well may be incomplete" in dialog.text()
    assert "permanently aborts this experiment" in dialog.text()
    assert dialog.resume_button.text() == "Resume Array"
    assert dialog.keep_paused_button.text() == "Keep Paused"
    assert dialog.clear_queue_button.text() == "Abort Array and Clear Queue…"
    assert dialog.defaultButton() is dialog.keep_paused_button
    assert dialog.escapeButton() is dialog.keep_paused_button
    assert dialog.buttonRole(dialog.clear_queue_button) == QMessageBox.DestructiveRole
    assert dialog.action_for_button(None) == PauseActionDialog.KEEP_PAUSED


def test_non_array_pause_dialog_copy_and_safe_defaults(qapp):
    dialog = PauseActionDialog(array_active=False)

    assert dialog.windowTitle() == "Machine Paused"
    assert "cancels queued commands" in dialog.text()
    assert dialog.resume_button.text() == "Resume Commands"
    assert dialog.clear_queue_button.text() == "Clear Command Queue…"
    assert dialog.defaultButton() is dialog.keep_paused_button
    assert dialog.escapeButton() is dialog.keep_paused_button


def test_clear_confirmation_copy_and_safe_defaults(qapp):
    array_dialog = ClearQueueConfirmationDialog(array_active=True)
    generic_dialog = ClearQueueConfirmationDialog(array_active=False)

    assert array_dialog.windowTitle() == "Abort Print Array?"
    assert "incomplete or uncertain" in array_dialog.text()
    assert "cannot be resumed" in array_dialog.text()
    assert array_dialog.confirm_button.text() == "Abort Array and Clear Queue"
    assert array_dialog.defaultButton() is array_dialog.keep_paused_button
    assert array_dialog.escapeButton() is array_dialog.keep_paused_button
    assert array_dialog.confirmed_for_button(None) is False

    assert generic_dialog.windowTitle() == "Clear Command Queue?"
    assert "cannot be resumed" in generic_dialog.text()
    assert generic_dialog.confirm_button.text() == "Clear Command Queue"
    assert generic_dialog.defaultButton() is generic_dialog.keep_paused_button
    assert generic_dialog.escapeButton() is generic_dialog.keep_paused_button
