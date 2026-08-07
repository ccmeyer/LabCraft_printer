from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from tools.virtual_workflows.page_drivers import (
    ArrayDriver,
    ExperimentEditorDriver,
    ExperimentLoaderDriver,
    MainWindowDriver,
    MachineControlsDriver,
    ManualRefuelCheckDriver,
    RackDriver,
)


def _context(qapp, view):
    return SimpleNamespace(
        app=qapp,
        view=view,
        deadline=SimpleNamespace(
            remaining_seconds=lambda timeout=None: timeout or 10.0,
            elapsed_seconds=lambda: 0.0,
        ),
        pump_events=qapp.processEvents,
        dialogs=[],
        action_results=[],
        closed=False,
        application_session_id=None,
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


def test_array_driver_start_waits_for_running_state(qapp):
    window = QtWidgets.QWidget()
    button = QtWidgets.QPushButton("Start Array", window)
    state = {"value": "idle"}

    def drive_control():
        answer = QtWidgets.QMessageBox.question(
            window, "Start Print Array", "Start?"
        )
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            state["value"] = "running"

    button.clicked.connect(drive_control)
    window.show()
    qapp.processEvents()
    context = _context(qapp, SimpleNamespace(
        well_plate_widget=SimpleNamespace(start_print_array_button=button)
    ))
    context.controller = SimpleNamespace(
        get_array_run_state=lambda: state["value"]
    )

    dialogs = ArrayDriver(context).start(
        [("Start Print Array", QtWidgets.QMessageBox.StandardButton.Yes)]
    )

    assert state["value"] == "running"
    assert [row["title"] for row in dialogs] == ["Start Print Array"]
    window.close()


def test_pressure_regulation_waits_for_the_simulated_command_queue(qapp):
    window = QtWidgets.QWidget()
    button = QtWidgets.QPushButton("Regulate Pressure", window)
    machine_model = SimpleNamespace(regulating_print_pressure=False)
    button.clicked.connect(
        lambda: setattr(machine_model, "regulating_print_pressure", True)
    )
    queue_checks = []

    def queue_drained():
        queue_checks.append(True)
        return len(queue_checks) >= 2

    window.show()
    qapp.processEvents()
    context = _context(qapp, SimpleNamespace(
        pressure_box=SimpleNamespace(pressure_regulation_button=button)
    ))
    context.model = SimpleNamespace(machine_model=machine_model)
    context.machine = SimpleNamespace(check_if_all_completed=queue_drained)

    MachineControlsDriver(context).enable_pressure_regulation()

    assert len(queue_checks) >= 2
    window.close()


def test_machine_settings_and_pressure_gate_include_optional_refuel_controls(qapp):
    window = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(window)
    print_pulse = QtWidgets.QSpinBox()
    print_pressure = QtWidgets.QDoubleSpinBox()
    frequency = QtWidgets.QSpinBox()
    refuel_pulse = QtWidgets.QSpinBox()
    refuel_pressure = QtWidgets.QDoubleSpinBox()
    for widget in (print_pulse, print_pressure, frequency, refuel_pulse, refuel_pressure):
        widget.setRange(0, 10000)
        layout.addWidget(widget)
    button = QtWidgets.QPushButton("Regulate", window)
    layout.addWidget(button)
    machine_model = SimpleNamespace(
        regulating_print_pressure=False,
        regulating_refuel_pressure=False,
    )
    button.clicked.connect(
        lambda: (
            setattr(machine_model, "regulating_print_pressure", True),
            setattr(machine_model, "regulating_refuel_pressure", True),
        )
    )
    window.show()
    qapp.processEvents()
    context = _context(qapp, SimpleNamespace(pressure_box=SimpleNamespace(
        print_pulse_width_spinbox=print_pulse,
        target_print_pressure_spinbox=print_pressure,
        print_frequency_spinbox=frequency,
        refuel_pulse_width_spinbox=refuel_pulse,
        target_refuel_pressure_spinbox=refuel_pressure,
        pressure_regulation_button=button,
    )))
    context.model = SimpleNamespace(machine_model=machine_model)
    context.machine = SimpleNamespace(check_if_all_completed=lambda: True)
    driver = MachineControlsDriver(context)

    driver.configure_print_settings(
        pulse_width_us=2500,
        pressure_psi=1.2,
        frequency_hz=20,
        refuel_pulse_width_us=6000,
        refuel_pressure_psi=0.4,
    )
    driver.enable_pressure_regulation(require_refuel=True)

    assert [print_pulse.value(), frequency.value(), refuel_pulse.value()] == [2500, 20, 6000]
    assert print_pressure.value() == pytest.approx(1.2)
    assert refuel_pressure.value() == pytest.approx(0.4)
    window.close()


def _manual_refuel_driver_fixture(qapp, *, fingerprint="fingerprint-1"):
    parent = QtWidgets.QWidget()
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle("Manual Refuel Check")
    dialog.setModal(True)
    layout = QtWidgets.QVBoxLayout(dialog)
    dialog.trial_droplets_spin = QtWidgets.QSpinBox(dialog)
    dialog.trial_droplets_spin.setRange(1, 1000)
    dialog.trial_droplets_spin.setValue(5)
    dialog.run_trial_button = QtWidgets.QPushButton("Run Trial", dialog)
    dialog.stable_button = QtWidgets.QPushButton("Stable", dialog)
    dialog.level_rose_button = QtWidgets.QPushButton("Level moved up", dialog)
    dialog.level_fell_button = QtWidgets.QPushButton("Level moved down", dialog)
    dialog.unclear_button = QtWidgets.QPushButton("Unclear", dialog)
    dialog.close_button = QtWidgets.QPushButton("Close", dialog)
    for widget in (
        dialog.trial_droplets_spin, dialog.run_trial_button, dialog.stable_button,
        dialog.level_rose_button, dialog.level_fell_button, dialog.unclear_button,
        dialog.close_button,
    ):
        layout.addWidget(widget)
    dialog.trial_count = 0
    dialog.expected_calibration_fingerprint = "fingerprint-1"
    record = {
        "status": "passed",
        "source": "sil_simulated_manual_refuel_check",
        "stock_id": "stream-stock",
        "printer_head_id": "stream-head",
        "printing_mode": "stream",
        "trial_count": 2,
        "trial_droplet_count": 5,
        "operator_judgment": "stable",
        "applied_calibration_fingerprint": fingerprint,
    }
    dialog.run_trial_button.clicked.connect(
        lambda: setattr(dialog, "trial_count", dialog.trial_count + 1)
    )
    dialog.stable_button.clicked.connect(lambda: dialog.close_button.setText("Done"))
    dialog.close_button.clicked.connect(dialog.accept)
    pressure_box = SimpleNamespace(
        _manual_refuel_check_dialog=None,
        _manual_refuel_check_launch_is_active=lambda: bool(dialog.isVisible()),
    )
    context = _context(qapp, SimpleNamespace(pressure_box=pressure_box))
    context.machine = SimpleNamespace(check_if_all_completed=lambda: True)
    context.model = SimpleNamespace(
        rack_model=SimpleNamespace(
            get_gripper_printer_head=lambda: SimpleNamespace()
        )
    )
    context.experiment_model = SimpleNamespace(
        get_manual_refuel_check=lambda **_kwargs: dict(record)
    )

    class Calibration:
        dialog = QtWidgets.QDialog(parent)

        def close(self):
            pressure_box._manual_refuel_check_dialog = dialog
            dialog.exec()
            pressure_box._manual_refuel_check_dialog = None

    return parent, context, Calibration(), record


def test_manual_refuel_driver_completes_two_trials_and_closes_nested_modal(qapp):
    parent, context, calibration, record = _manual_refuel_driver_fixture(qapp)
    captured = []

    evidence = ManualRefuelCheckDriver(context).complete_after_calibration_close(
        calibration,
        stock_id="stream-stock",
        printer_head_id="stream-head",
        trial_count=2,
        trial_droplet_count=5,
        outcome="passed",
        operator_judgment="stable",
        capture_passed=lambda value: captured.append(dict(value)),
    )

    assert evidence["trial_count"] == 2
    assert evidence["record"] == record
    assert evidence["dialog_closed"] is True
    assert captured == [record]
    parent.close()


def test_manual_refuel_driver_fails_closed_on_stale_fingerprint(qapp):
    parent, context, calibration, _record = _manual_refuel_driver_fixture(
        qapp, fingerprint="stale"
    )

    with pytest.raises(RuntimeError, match="matching record"):
        ManualRefuelCheckDriver(context).complete_after_calibration_close(
            calibration,
            stock_id="stream-stock",
            printer_head_id="stream-head",
            trial_count=2,
            trial_droplet_count=5,
            outcome="passed",
            operator_judgment="stable",
        )
    parent.close()


def test_machine_driver_disconnects_through_normal_control(qapp):
    window = QtWidgets.QWidget()
    button = QtWidgets.QPushButton("Disconnect", window)
    machine_model = SimpleNamespace(connected=True)
    machine_model.is_connected = lambda: machine_model.connected
    machine = SimpleNamespace(
        state=SimpleNamespace(connected=True),
        check_if_all_completed=lambda: True,
    )
    connection_widget = SimpleNamespace(
        machine_connect_button=button,
        _machine_disconnect_pending=False,
    )

    def disconnect():
        connection_widget._machine_disconnect_pending = True
        machine_model.connected = False
        machine.state.connected = False
        connection_widget._machine_disconnect_pending = False
        button.setText("Connect")

    button.clicked.connect(disconnect)
    window.show()
    qapp.processEvents()
    context = _context(qapp, SimpleNamespace(connection_widget=connection_widget))
    context.model = SimpleNamespace(machine_model=machine_model)
    context.machine = machine

    evidence = MachineControlsDriver(context).disconnect()

    assert evidence["before"]["button_text"] == "Disconnect"
    assert evidence["button_text_after"] == "Connect"
    assert evidence["model_connected_after"] is False
    assert evidence["simulator_connected_after"] is False
    assert evidence["simulator_queue_empty"] is True
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


def test_directory_loader_rejects_unexpected_editor_dialog(qapp, tmp_path):
    window = QtWidgets.QWidget()
    button = QtWidgets.QPushButton("Design Experiment", window)
    wrong = QtWidgets.QDialog(window)
    wrong.setWindowTitle("Unexpected editor")
    button.clicked.connect(wrong.exec)
    window.show()
    qapp.processEvents()
    context = _context(qapp, SimpleNamespace(
        well_plate_widget=SimpleNamespace(design_experiment_button=button)
    ))
    context.scenario_root = tmp_path

    with pytest.raises(RuntimeError, match="unexpected modal while opening"):
        ExperimentLoaderDriver(context)._drive_directory_load(
            tmp_path, purpose="prepared", on_loaded=lambda _dialog: {}
        )
    window.close()


def test_directory_loader_rejects_unexpected_folder_dialog(
    qapp, tmp_path, monkeypatch
):
    import View

    class FakeEditor(QtWidgets.QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.load_btn = QtWidgets.QPushButton("Load", self)
            self.wrong = QtWidgets.QMessageBox(
                QtWidgets.QMessageBox.Icon.Warning,
                "Wrong folder surface",
                "Expected a QFileDialog.",
                parent=self,
            )
            self.load_btn.clicked.connect(self.wrong.exec)

    monkeypatch.setattr(View, "ExperimentDesignDialog", FakeEditor)
    window = QtWidgets.QWidget()
    button = QtWidgets.QPushButton("Design Experiment", window)
    editor = FakeEditor(window)
    button.clicked.connect(editor.exec)
    window.show()
    qapp.processEvents()
    context = _context(qapp, SimpleNamespace(
        well_plate_widget=SimpleNamespace(design_experiment_button=button)
    ))
    context.scenario_root = tmp_path

    with pytest.raises(RuntimeError, match="unexpected modal while selecting"):
        ExperimentLoaderDriver(context)._drive_directory_load(
            tmp_path, purpose="prepared", on_loaded=lambda _dialog: {}
        )
    window.close()


def test_authoritative_loader_rejects_wrong_load_execution_label(
    qapp, tmp_path, monkeypatch
):
    design = tmp_path / "experiment_design.json"
    design.write_text("{}\n", encoding="utf-8")
    label = lambda value: SimpleNamespace(text=lambda: value)
    dialog = SimpleNamespace(
        exp_name_edit=label("expected"),
        finish_btn=SimpleNamespace(text=lambda: "Finish", isEnabled=lambda: True),
        status_lbl=label("Execution plan validated; load execution."),
        lifecycle_banner=SimpleNamespace(
            text=lambda: "Load execution without starting or resuming printing",
            isHidden=lambda: False,
        ),
    )
    context = _context(qapp, QtWidgets.QWidget())
    context.scenario_root = tmp_path
    context.experiment_model = SimpleNamespace(
        get_execution_resume_eligibility=lambda: {"status": "ready_to_resume"},
        is_authoritative_execution_runtime_active=lambda: False,
        experiment_file_path=str(design),
        experiment_dir_path=str(tmp_path),
        to_dict=lambda: {},
        get_execution_plan_snapshot=lambda: SimpleNamespace(design_sha256="sha"),
    )
    driver = ExperimentLoaderDriver(context)

    def invoke_loaded(_directory, **values):
        return {"loaded": values["on_loaded"](dialog), "activated": None}

    monkeypatch.setattr(driver, "_drive_directory_load", invoke_loaded)
    with pytest.raises(RuntimeError, match="loaded authoritative editor state"):
        driver.load_authoritative_execution(tmp_path, expected_name="expected")


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


def test_rack_driver_swaps_consecutive_heads_through_repopulated_combobox(
    qapp, monkeypatch
):
    class Head:
        def __init__(self, stock_id, head_id):
            self.stock_id = stock_id
            self.printer_head_id = head_id

        def get_stock_id(self):
            return self.stock_id

        def get_display_stock_name(self):
            return self.stock_id

    previous = Head("stock-old", "head-old")
    first_target = Head("stock-new-1", "head-new-1")
    second_target = Head("stock-new-2", "head-new-2")
    slot = SimpleNamespace(printer_head=previous)
    manager = SimpleNamespace(
        unassigned=[first_target, second_target],
        get_unassigned_printer_heads=lambda: manager.unassigned,
    )
    rack_model = SimpleNamespace(
        slots=[slot], get_gripper_printer_head=lambda: None
    )
    window = QtWidgets.QWidget()
    combo = QtWidgets.QComboBox(window)
    shortcut_activations = []
    shortcut = QtGui.QShortcut(QtGui.QKeySequence("Down"), window)
    shortcut.activated.connect(lambda: shortcut_activations.append(True))

    def repopulate():
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Swap")
        for head in manager.unassigned:
            combo.addItem(head.get_display_stock_name())
        combo.blockSignals(False)

    def swap(index):
        if index <= 0:
            return
        selected_text = combo.itemText(index)
        matches = [
            head
            for head in manager.unassigned
            if head.get_display_stock_name() == selected_text
        ]
        if len(matches) != 1:
            return
        target = matches[0]
        manager.unassigned.remove(target)
        manager.unassigned.append(slot.printer_head)
        slot.printer_head = target
        repopulate()

    combo.currentIndexChanged.connect(swap)
    repopulate()
    window.show()
    qapp.processEvents()
    context = _context(qapp, SimpleNamespace(
        rack_box=SimpleNamespace(slot_widgets=[(None, None, None, combo)])
    ))
    context.model = SimpleNamespace(
        rack_model=rack_model, printer_head_manager=manager
    )
    context.controller = SimpleNamespace(get_array_run_state=lambda: "idle")
    context.machine = SimpleNamespace(check_if_all_completed=lambda: True)

    real_mouse_press = QtTest.QTest.mousePress
    real_mouse_release = QtTest.QTest.mouseRelease
    item_clicks = []
    swallow = {"first": True}

    def swallow_first_item_press(widget, *args, **kwargs):
        if widget is combo.view().viewport() and swallow["first"]:
            item_clicks.append(combo.itemText(1))
            return None
        return real_mouse_press(widget, *args, **kwargs)

    def swallow_first_item_release(widget, *args, **kwargs):
        if widget is combo.view().viewport():
            if swallow["first"]:
                swallow["first"] = False
                return None
            item_clicks.append(combo.itemText(1))
        return real_mouse_release(widget, *args, **kwargs)

    monkeypatch.setattr(QtTest.QTest, "mousePress", swallow_first_item_press)
    monkeypatch.setattr(QtTest.QTest, "mouseRelease", swallow_first_item_release)

    driver = RackDriver(context)
    combo.showPopup()
    qapp.processEvents()
    assert combo.view().isVisible()
    first_evidence = driver.swap_unassigned_head(0, "stock-new-1")
    second_evidence = driver.swap_unassigned_head(0, "stock-new-2")

    assert slot.printer_head is second_target
    assert manager.unassigned == [previous, first_target]
    assert item_clicks == ["stock-new-1", "stock-new-1", "stock-new-2"]
    assert shortcut_activations == []
    assert first_evidence == {
        "slot": 0,
        "stock_id": "stock-new-1",
        "printer_head_id": "head-new-1",
        "replaced_printer_head_id": "head-old",
        "control": "rack_swap_combobox",
    }
    assert second_evidence == {
        "slot": 0,
        "stock_id": "stock-new-2",
        "printer_head_id": "head-new-2",
        "replaced_printer_head_id": "head-new-1",
        "control": "rack_swap_combobox",
    }
    shortcut.setEnabled(False)
    window.close()


def test_rack_driver_waits_for_delayed_mouse_release(qapp, monkeypatch):
    class Head:
        printer_head_id = "head-new"

        def get_stock_id(self):
            return "stock-new"

        def get_display_stock_name(self):
            return "stock-new"

    target = Head()
    previous = SimpleNamespace(printer_head_id="head-old")
    slot = SimpleNamespace(printer_head=previous)
    manager = SimpleNamespace(
        get_unassigned_printer_heads=lambda: [target],
    )
    rack_model = SimpleNamespace(
        slots=[slot], get_gripper_printer_head=lambda: None
    )
    window = QtWidgets.QWidget()
    combo = QtWidgets.QComboBox(window)
    combo.addItems(["Swap", "stock-new"])
    combo.currentIndexChanged.connect(
        lambda index: setattr(slot, "printer_head", target) if index == 1 else None
    )
    window.show()
    qapp.processEvents()
    context = _context(qapp, SimpleNamespace(
        rack_box=SimpleNamespace(slot_widgets=[(None, None, None, combo)])
    ))
    context.model = SimpleNamespace(
        rack_model=rack_model, printer_head_manager=manager
    )
    context.controller = SimpleNamespace(get_array_run_state=lambda: "idle")
    context.machine = SimpleNamespace(check_if_all_completed=lambda: True)

    real_mouse_release = QtTest.QTest.mouseRelease
    deferred = {"scheduled": False}

    def delay_first_release(widget, *args, **kwargs):
        if widget is combo.view().viewport() and not deferred["scheduled"]:
            deferred["scheduled"] = True
            QtCore.QTimer.singleShot(
                50, lambda: real_mouse_release(widget, *args, **kwargs)
            )
            return None
        return real_mouse_release(widget, *args, **kwargs)

    monkeypatch.setattr(QtTest.QTest, "mouseRelease", delay_first_release)

    evidence = RackDriver(context).swap_unassigned_head(0, "stock-new")

    assert deferred["scheduled"] is True
    assert slot.printer_head is target
    assert evidence["printer_head_id"] == "head-new"
    assert not combo.view().isVisible()
    window.close()


def test_rack_driver_rejects_activation_without_rack_postcondition(qapp):
    target = SimpleNamespace(
        printer_head_id="head-new",
        get_stock_id=lambda: "stock-new",
        get_display_stock_name=lambda: "stock-new",
    )
    previous = SimpleNamespace(printer_head_id="head-old")
    slot = SimpleNamespace(printer_head=previous)
    window = QtWidgets.QWidget()
    combo = QtWidgets.QComboBox(window)
    combo.addItems(["Swap", "stock-new"])
    window.show()
    qapp.processEvents()
    context = _context(qapp, SimpleNamespace(
        rack_box=SimpleNamespace(slot_widgets=[(None, None, None, combo)])
    ))
    context.model = SimpleNamespace(
        rack_model=SimpleNamespace(
            slots=[slot], get_gripper_printer_head=lambda: None
        ),
        printer_head_manager=SimpleNamespace(
            get_unassigned_printer_heads=lambda: [target]
        ),
    )
    context.controller = SimpleNamespace(get_array_run_state=lambda: "idle")
    context.machine = SimpleNamespace(check_if_all_completed=lambda: True)

    with pytest.raises(RuntimeError, match="activation had no postcondition"):
        RackDriver(context).swap_unassigned_head(0, "stock-new")

    assert slot.printer_head is previous
    assert not combo.view().isVisible()
    window.close()


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
