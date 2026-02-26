import time
from types import SimpleNamespace

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from View import MainWindow


def test_mainwindow_closeevent_has_timeout_if_disconnect_signal_missing(qapp, fake_signal):
    disconnect_calls = {"count": 0}

    mw = MainWindow.__new__(MainWindow)
    mw.model = SimpleNamespace(machine_model=SimpleNamespace(is_connected=lambda: True))
    mw.controller = SimpleNamespace(
        disconnect_machine=lambda: disconnect_calls.__setitem__("count", disconnect_calls["count"] + 1),
        machine=SimpleNamespace(disconnect_complete_signal=fake_signal),
    )
    mw.popup_yes_no = lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    mw.close_disconnect_timeout_ms = 20
    mw.disconnected = False

    event = QCloseEvent()
    t0 = time.monotonic()
    MainWindow.closeEvent(mw, event)
    elapsed = time.monotonic() - t0

    assert disconnect_calls["count"] == 1
    assert elapsed < 0.5
    assert event.isAccepted() is True


def test_mainwindow_closeevent_returns_quickly_when_disconnect_signal_arrives(qapp, fake_signal):
    disconnect_calls = {"count": 0}

    mw = MainWindow.__new__(MainWindow)
    mw.model = SimpleNamespace(machine_model=SimpleNamespace(is_connected=lambda: True))
    mw.controller = SimpleNamespace(
        disconnect_machine=lambda: (
            disconnect_calls.__setitem__("count", disconnect_calls["count"] + 1),
            QTimer.singleShot(0, fake_signal.emit),
        ),
        machine=SimpleNamespace(disconnect_complete_signal=fake_signal),
    )
    mw.popup_yes_no = lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    mw.close_disconnect_timeout_ms = 200
    mw.disconnected = True

    event = QCloseEvent()
    t0 = time.monotonic()
    MainWindow.closeEvent(mw, event)
    elapsed = time.monotonic() - t0

    assert disconnect_calls["count"] == 1
    assert elapsed < 0.5
    assert event.isAccepted() is True
