from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtWidgets

from tools.virtual_workflows.page_drivers import MainWindowDriver


def _context(qapp, view):
    return SimpleNamespace(
        app=qapp,
        view=view,
        deadline=SimpleNamespace(remaining_seconds=lambda timeout=None: timeout or 10.0),
        pump_events=qapp.processEvents,
        dialogs=[],
        record_event=lambda *args, **kwargs: None,
    )


def test_qtest_driver_clicks_only_visible_enabled_controls(qapp):
    view = QtWidgets.QWidget()
    button = QtWidgets.QPushButton("Drive", view)
    view.show()
    qapp.processEvents()
    clicked = []
    button.clicked.connect(lambda: clicked.append(True))
    driver = MainWindowDriver(_context(qapp, view))

    driver.click(button)
    assert clicked == [True]

    button.setEnabled(False)
    with pytest.raises(RuntimeError, match="visible and enabled"):
        driver.click(button)
    view.close()


def test_dialog_sequence_rejects_unexpected_title(qapp):
    view = QtWidgets.QWidget()
    button = QtWidgets.QPushButton("Open", view)

    def show_wrong_dialog():
        QtWidgets.QMessageBox.question(view, "Wrong title", "Unexpected")

    button.clicked.connect(show_wrong_dialog)
    view.show()
    qapp.processEvents()
    driver = MainWindowDriver(_context(qapp, view))

    with pytest.raises(RuntimeError, match="unexpected dialog title"):
        driver.click_with_message_boxes(
            button,
            [("Expected title", QtWidgets.QMessageBox.StandardButton.Yes)],
        )
    view.close()
