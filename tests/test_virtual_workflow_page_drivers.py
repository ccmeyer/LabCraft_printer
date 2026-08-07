from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtWidgets

from tools.virtual_workflows.page_drivers import (
    ArrayDriver,
    ExperimentEditorDriver,
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


def test_array_driver_owns_soft_stop_and_resume_qtest_mechanics(qapp):
    window = QtWidgets.QWidget()
    button = QtWidgets.QPushButton("Stop After Well", window)
    state = {"value": "running"}

    def drive_control():
        if state["value"] == "running":
            state["value"] = "resume_ready"
            button.setText("Stop Pending")
            button.setEnabled(False)
            return
        answer = QtWidgets.QMessageBox.question(
            window, "Resume Print Array", "Resume?"
        )
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            state["value"] = "running"
            button.setText("Stop After Well")

    button.clicked.connect(drive_control)
    window.show()
    qapp.processEvents()
    context = _context(qapp, SimpleNamespace(
        well_plate_widget=SimpleNamespace(start_print_array_button=button)
    ))
    context.controller = SimpleNamespace(
        get_array_run_state=lambda: state["value"]
    )
    driver = ArrayDriver(context)

    stop = driver.request_soft_stop()
    assert stop["button_text_after"] == "Stop Pending"
    button.setText("Resume Print")
    button.setEnabled(True)
    resumed = driver.resume()
    assert resumed["array_state"] == "running"
    assert [row["title"] for row in resumed["dialogs"]] == ["Resume Print Array"]
    window.close()


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


def test_editor_revision_driver_delegates_to_existing_bounded_mechanics(
    qapp, monkeypatch
):
    import tools.virtual_workflows.actions as actions

    context = _context(qapp, QtWidgets.QWidget())
    runner = object()
    observed = {}

    def drive(received_context, **values):
        observed.update(values)
        assert received_context is context
        return {"refinalized": True}

    monkeypatch.setattr(actions, "drive_editor_prestart_rename_refinalize", drive)
    result = ExperimentEditorDriver(
        context,
        action_runner=runner,
    ).revise_prepared_design(
        initial_name="initial",
        renamed_name="renamed",
        experiment={"refinalized_replicates": 3},
        reagent={"refinalized_targets": [0.5, 1.0]},
    )

    assert result == {"refinalized": True}
    assert observed == {
        "initial_name": "initial",
        "renamed_name": "renamed",
        "experiment": {"refinalized_replicates": 3},
        "reagent": {"refinalized_targets": [0.5, 1.0]},
        "action_runner": runner,
    }
