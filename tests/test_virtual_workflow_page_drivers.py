from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtWidgets

from tools.virtual_workflows.page_drivers import (
    ExperimentLoaderDriver,
    MainWindowDriver,
    RackDriver,
)


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


def test_prepared_loader_rejects_directory_outside_session_root(qapp, tmp_path):
    context = _context(qapp, QtWidgets.QWidget())
    context.scenario_root = tmp_path / "scenario-root"
    context.scenario_root.mkdir()

    with pytest.raises(RuntimeError, match="escaped the SIL session root"):
        ExperimentLoaderDriver(context).load_prepared_design(
            tmp_path / "outside",
            expected_name="example",
            expected_plan_id="plan",
            expected_plan_revision=1,
        )


def test_rack_driver_requires_one_unambiguous_stock_slot(qapp):
    head = SimpleNamespace(get_stock_id=lambda: "stock-1")
    slots = [
        SimpleNamespace(printer_head=head),
        SimpleNamespace(printer_head=None),
    ]
    context = _context(qapp, QtWidgets.QWidget())
    context.model = SimpleNamespace(rack_model=SimpleNamespace(slots=slots))
    driver = RackDriver(context)
    assert driver.find_slot_for_stock("stock-1") == 0
    with pytest.raises(RuntimeError, match="expected one rack slot"):
        driver.find_slot_for_stock("missing")
