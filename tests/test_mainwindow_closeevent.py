from types import SimpleNamespace

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from View import MainWindow


def _make_stub_mainwindow(fake_signal, *, popup_response=QMessageBox.StandardButton.Yes):
    disconnect_calls = {"count": 0}
    close_calls = {"count": 0}
    dismiss_calls = {"count": 0}
    cancel_update_calls = {"count": 0}
    popup_calls = {"count": 0}
    messages = []
    dialog_states = []

    mw = MainWindow.__new__(MainWindow)
    mw.model = SimpleNamespace(machine_model=SimpleNamespace(is_connected=lambda: True))
    mw.controller = SimpleNamespace(
        disconnect_machine=lambda: disconnect_calls.__setitem__("count", disconnect_calls["count"] + 1),
        cancel_app_update_process=lambda: cancel_update_calls.__setitem__(
            "count", cancel_update_calls["count"] + 1
        ),
        machine=SimpleNamespace(disconnect_complete_signal=fake_signal),
    )
    def _popup_yes_no(*args, **kwargs):
        popup_calls["count"] += 1
        return popup_response

    mw.popup_yes_no = _popup_yes_no
    mw.popup_message = lambda title, message: messages.append((title, message))
    mw.close_disconnect_timeout_ms = 20
    mw.disconnected = False
    mw._close_disconnect_pending = False
    mw._close_after_disconnect = False
    mw._app_update_close_requested = False
    mw._close_disconnect_dialog = None
    mw._close_disconnect_timer = None
    mw._close_disconnect_timeout_prompt = False
    mw._close_disconnect_signal_hooked = False
    mw._show_close_disconnect_dialog = lambda timed_out=False: dialog_states.append(
        "timeout" if timed_out else "waiting"
    )
    mw._dismiss_close_disconnect_dialog = lambda: dismiss_calls.__setitem__(
        "count", dismiss_calls["count"] + 1
    )
    mw.close = lambda: close_calls.__setitem__("count", close_calls["count"] + 1)
    mw._cancel_update_calls = cancel_update_calls
    mw._popup_calls = popup_calls
    mw._popup_messages = messages

    return mw, disconnect_calls, close_calls, dismiss_calls, dialog_states


def test_mainwindow_closeevent_starts_pending_disconnect_and_ignores_initial_close(qapp, fake_signal):
    mw, disconnect_calls, close_calls, dismiss_calls, dialog_states = _make_stub_mainwindow(fake_signal)

    event = QCloseEvent()
    MainWindow.closeEvent(mw, event)

    assert disconnect_calls["count"] == 1
    assert close_calls["count"] == 0
    assert dismiss_calls["count"] == 0
    assert dialog_states == ["waiting"]
    assert mw._close_disconnect_pending is True
    assert mw._close_disconnect_timeout_prompt is False
    assert event.isAccepted() is False


def test_mainwindow_closeevent_closes_after_disconnect_signal(qapp, fake_signal):
    mw, disconnect_calls, close_calls, dismiss_calls, dialog_states = _make_stub_mainwindow(fake_signal)

    event = QCloseEvent()
    MainWindow.closeEvent(mw, event)
    fake_signal.emit()

    assert disconnect_calls["count"] == 1
    assert close_calls["count"] == 1
    assert dismiss_calls["count"] == 1
    assert dialog_states == ["waiting"]
    assert mw._close_disconnect_pending is False
    assert mw._close_after_disconnect is True


def test_mainwindow_closeevent_followup_close_accepts_without_reprompt(qapp, fake_signal):
    mw, _disconnect_calls, close_calls, _dismiss_calls, _dialog_states = _make_stub_mainwindow(fake_signal)

    first_event = QCloseEvent()
    MainWindow.closeEvent(mw, first_event)
    fake_signal.emit()

    second_event = QCloseEvent()
    MainWindow.closeEvent(mw, second_event)

    assert close_calls["count"] == 1
    assert second_event.isAccepted() is True
    assert mw._close_after_disconnect is False


def test_mainwindow_closeevent_timeout_can_cancel_pending_close(qapp, fake_signal):
    mw, disconnect_calls, close_calls, dismiss_calls, dialog_states = _make_stub_mainwindow(fake_signal)

    event = QCloseEvent()
    MainWindow.closeEvent(mw, event)
    MainWindow._handle_close_disconnect_timeout(mw)

    class _CancelDialog:
        def standardButton(self, _button):
            return QMessageBox.Cancel

    mw._close_disconnect_dialog = _CancelDialog()
    MainWindow._handle_close_disconnect_dialog_clicked(mw, object())

    assert disconnect_calls["count"] == 1
    assert close_calls["count"] == 0
    assert dismiss_calls["count"] == 1
    assert dialog_states == ["waiting", "timeout"]
    assert mw._close_disconnect_pending is False
    assert mw._close_disconnect_timeout_prompt is False


def test_mainwindow_closeevent_timeout_keep_waiting_restores_wait_dialog(qapp, fake_signal):
    mw, disconnect_calls, close_calls, dismiss_calls, dialog_states = _make_stub_mainwindow(fake_signal)

    event = QCloseEvent()
    MainWindow.closeEvent(mw, event)
    MainWindow._handle_close_disconnect_timeout(mw)

    class _RetryDialog:
        def standardButton(self, _button):
            return QMessageBox.Retry

    mw._close_disconnect_dialog = _RetryDialog()
    MainWindow._handle_close_disconnect_dialog_clicked(mw, object())

    assert disconnect_calls["count"] == 1
    assert close_calls["count"] == 0
    assert dismiss_calls["count"] == 0
    assert dialog_states == ["waiting", "timeout", "waiting"]
    assert mw._close_disconnect_pending is True
    assert mw._close_disconnect_timeout_prompt is False
    assert mw._close_disconnect_timer.isActive() is True


def test_mainwindow_closeevent_update_pending_connected_starts_disconnect_without_reprompt(qapp, fake_signal):
    mw, disconnect_calls, close_calls, dismiss_calls, dialog_states = _make_stub_mainwindow(fake_signal)
    mw._app_update_close_requested = True

    event = QCloseEvent()
    MainWindow.closeEvent(mw, event)

    assert disconnect_calls["count"] == 1
    assert close_calls["count"] == 0
    assert dismiss_calls["count"] == 0
    assert dialog_states == ["waiting"]
    assert mw._popup_calls["count"] == 0
    assert event.isAccepted() is False


def test_mainwindow_closeevent_update_disconnect_cancel_terminates_updater_and_resets_state(qapp, fake_signal):
    mw, disconnect_calls, close_calls, dismiss_calls, dialog_states = _make_stub_mainwindow(fake_signal)
    mw._app_update_close_requested = True

    event = QCloseEvent()
    MainWindow.closeEvent(mw, event)
    MainWindow._handle_close_disconnect_timeout(mw)

    class _CancelDialog:
        def standardButton(self, _button):
            return QMessageBox.Cancel

    mw._close_disconnect_dialog = _CancelDialog()
    MainWindow._handle_close_disconnect_dialog_clicked(mw, object())

    assert disconnect_calls["count"] == 1
    assert close_calls["count"] == 0
    assert dismiss_calls["count"] == 1
    assert dialog_states == ["waiting", "timeout"]
    assert mw._cancel_update_calls["count"] == 1
    assert mw._app_update_close_requested is False
    assert mw._close_disconnect_pending is False
    assert mw._popup_messages == [
        ("Update Cancelled", "Application update was cancelled. The app will remain open.")
    ]
