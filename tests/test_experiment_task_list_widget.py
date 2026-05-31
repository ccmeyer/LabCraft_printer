from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6 import QtCore, QtTest

from View import ExperimentTaskListWidget


class SignalStub:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class HeadStub:
    def __init__(self, stock_id, name, *, calibrated=False, calibration_chip=False):
        self.stock_id = stock_id
        self.name = name
        self.calibrated = bool(calibrated)
        self.calibration_chip = bool(calibration_chip)

    def get_stock_id(self):
        return self.stock_id

    def get_display_stock_name(self, new_line=False):
        return self.name.replace(" ", "\n") if new_line else self.name

    def check_calibration_complete(self):
        return self.calibrated

    def is_calibration_chip(self):
        return self.calibration_chip


class ReactionStub:
    def __init__(self, stock_id, target):
        self.stock_id = stock_id
        self.target = int(target)

    def get_target_droplets_for_stock(self, stock_id):
        return self.target if stock_id == self.stock_id else 0


class WellStub:
    def __init__(self, stock_id, *, target=1, remaining=1):
        self.assigned_reaction = ReactionStub(stock_id, target)
        self._remaining_by_stock = {stock_id: int(remaining)}

    def get_remaining_droplets(self, stock_id):
        return self._remaining_by_stock.get(stock_id, 0)


class ExperimentModelStub:
    def __init__(self, applied_stock_ids=()):
        self.experiment_dir_path = "experiment-dir"
        self._applied_stock_ids = set(applied_stock_ids)
        self.applied_imaging_calibration_changed = SignalStub()

    def get_applied_imaging_calibration(self, *, printer_head=None, **_kwargs):
        stock_id = printer_head.get_stock_id() if printer_head is not None else None
        if stock_id in self._applied_stock_ids:
            return {"run_id": f"run-{stock_id}", "stock_id": stock_id}
        return None


class MachineModelStub:
    machine_state_updated = SignalStub()
    home_status_signal = SignalStub()
    regulation_state_changed = SignalStub()

    def __init__(self, *, connected=True, enabled=True, homed=True, pressure=True):
        self.connected = bool(connected)
        self.enabled = bool(enabled)
        self.homed = bool(homed)
        self.regulating_print_pressure = bool(pressure)

    def is_connected(self):
        return self.connected

    def motors_are_enabled(self):
        return self.enabled

    def motors_are_homed(self):
        return self.homed


def _make_widget(
    qapp,
    *,
    assigned=True,
    connected=True,
    enabled=True,
    homed=True,
    pressure=True,
    plate_calibrated=True,
    queue_idle=True,
    active_stock=None,
    calibrated_stock_ids=(),
    applied_stock_ids=(),
    progress_by_stock=None,
    preflight=None,
    array_state="idle",
    calibration_summary_rows=None,
):
    if progress_by_stock is None:
        progress_by_stock = {"stock-a": [1, 1], "stock-b": [1]}
    if preflight is None:
        preflight = {"ok": True}

    heads = {
        "stock-a": HeadStub("stock-a", "Reagent A", calibrated="stock-a" in calibrated_stock_ids),
        "stock-b": HeadStub("stock-b", "Reagent B", calibrated="stock-b" in calibrated_stock_ids),
    }
    active_head = heads.get(active_stock)
    wells = []
    if assigned:
        for stock_id, remaining_values in progress_by_stock.items():
            for remaining in remaining_values:
                wells.append(WellStub(stock_id, target=1, remaining=remaining))

    model = SimpleNamespace()
    model.experiment_model = ExperimentModelStub(applied_stock_ids)
    model.machine_model = MachineModelStub(
        connected=connected,
        enabled=enabled,
        homed=homed,
        pressure=pressure,
    )
    model.reaction_collection = SimpleNamespace(is_empty=lambda: not assigned)
    model.well_plate = SimpleNamespace(
        get_all_wells=lambda: list(wells),
        check_calibration_applied=lambda: bool(plate_calibrated),
        well_state_changed_signal=SignalStub(),
        clear_all_wells_signal=SignalStub(),
        plate_format_changed_signal=SignalStub(),
    )
    model.rack_model = SimpleNamespace(
        get_gripper_printer_head=lambda: active_head,
        gripper_printer_head=active_head,
        slots=[],
        gripper_updated=SignalStub(),
        slot_updated=SignalStub(),
    )
    model.printer_head_manager = SimpleNamespace(
        printer_heads=list(heads.values()),
        get_unassigned_printer_heads=lambda: [],
    )
    model.experiment_loaded = SignalStub()
    calibration_manager = SimpleNamespace(
        calibrationCompleted=SignalStub(),
        calibrationStageChanged=SignalStub(),
        characterizationSummaryUpdated=SignalStub(),
    )
    calibration_manager.summary_rows = list(calibration_summary_rows or [])
    calibration_manager.get_characterization_summary_rows = lambda: list(calibration_manager.summary_rows)
    model.calibration_manager = calibration_manager

    command_queue = SimpleNamespace(
        queue_updated=SignalStub(),
        commands_completed=SignalStub(),
    )
    controller = SimpleNamespace(
        check_if_all_completed=Mock(return_value=queue_idle),
        get_array_run_state=Mock(return_value=array_state),
        get_print_array_imaging_calibration_preflight=Mock(return_value=preflight),
        array_state_changed=SignalStub(),
        array_complete=SignalStub(),
        machine=SimpleNamespace(command_queue=command_queue),
        print_array=Mock(),
        pick_up_printer_head=Mock(),
        drop_off_printer_head=Mock(),
    )
    main_window = SimpleNamespace(
        color_dict={
            "darker_gray": "#111111",
            "dark_gray": "#333333",
            "light_gray": "#cccccc",
        }
    )

    widget = ExperimentTaskListWidget(main_window, model, controller)
    qapp.processEvents()
    return widget, model, controller, heads


def _wait_for_debounced_refresh(qapp):
    QtTest.QTest.qWait(ExperimentTaskListWidget.REFRESH_DEBOUNCE_MS + 50)
    qapp.processEvents()


def _count_layout_clears(widget):
    clear_calls = []
    original_clear_layout = widget._clear_layout

    def counted_clear_layout(layout):
        clear_calls.append("clear")
        return original_clear_layout(layout)

    widget._clear_layout = counted_clear_layout
    return clear_calls


def _spy_method(widget, name):
    calls = []
    original = getattr(widget, name)

    def wrapper(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    setattr(widget, name, wrapper)
    return calls


def _summary_row(**overrides):
    row = {
        "run_id": "run-1",
        "source_run_id": "run-1",
        "source_phase_key": "droplet_search",
        "source_step_index": 0,
        "source_pressure_index": None,
        "phase": "search",
        "pw_us": 2500,
        "pressure_psi": 0.75,
        "delay_us": 5000,
        "printing_mode": "droplet",
        "valid": True,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"assigned": False}, "Next: Load or create an experiment"),
        ({"connected": False}, "Next: Connect to the machine"),
        ({"enabled": False}, "Next: Enable motors"),
        ({"homed": False}, "Next: Home motors"),
        ({"pressure": False}, "Next: Start pressure regulation"),
        ({"plate_calibrated": False}, "Next: Apply plate calibration"),
    ],
)
def test_global_readiness_selects_first_missing_step(qapp, kwargs, expected):
    widget, _model, _controller, _heads = _make_widget(qapp, **kwargs)

    assert widget.next_label.text() == expected
    assert widget._sections["global"]["button"].isChecked() is True


def test_global_readiness_does_not_show_command_queue_idle(qapp):
    widget, _model, _controller, _heads = _make_widget(qapp, queue_idle=False)

    global_tasks = widget._global_tasks()

    assert "queue_idle" not in {task["key"] for task in global_tasks}
    assert widget.next_label.text() == "Next: Load printer head for Reagent A"


def test_refresh_debounce_interval_is_500_ms(qapp):
    widget, _model, _controller, _heads = _make_widget(qapp)

    assert widget.REFRESH_DEBOUNCE_MS == 500
    assert widget._refresh_timer.interval() == 500


def test_active_head_auto_expands_and_inactive_manual_expansion_persists(qapp):
    widget, _model, _controller, _heads = _make_widget(qapp, active_stock="stock-a")

    assert widget._sections["head:stock-a"]["button"].isChecked() is True
    assert widget._sections["head:stock-b"]["button"].isChecked() is False

    widget._sections["head:stock-b"]["button"].setChecked(True)
    widget._sections["head:stock-a"]["button"].setChecked(False)
    widget.refresh()

    assert widget._sections["head:stock-a"]["button"].isChecked() is True
    assert widget._sections["head:stock-b"]["button"].isChecked() is True


def test_head_header_shows_task_and_well_progress(qapp):
    widget, _model, _controller, _heads = _make_widget(
        qapp,
        active_stock="stock-a",
        calibrated_stock_ids={"stock-a"},
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [0, 1], "stock-b": [1]},
    )

    header = widget._sections["head:stock-a"]["button"].text()

    assert "Reagent A" in header
    assert "3/5" in header
    assert "1/2 wells" in header
    assert "Loaded" in header


def test_printed_well_progress_updates_only_loaded_head_header(qapp):
    widget, model, _controller, _heads = _make_widget(
        qapp,
        active_stock="stock-a",
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [1, 1], "stock-b": [1]},
        array_state="running",
    )
    full_rebuild_calls = _spy_method(widget, "_full_rebuild")
    section_update_calls = _spy_method(widget, "_update_head_section")
    progress_update_calls = _spy_method(widget, "_update_head_progress_header")
    clear_calls = _count_layout_clears(widget)

    for well in model.well_plate.get_all_wells():
        if "stock-a" in well._remaining_by_stock:
            well._remaining_by_stock["stock-a"] = 0
            break

    widget.refresh()

    assert full_rebuild_calls == []
    assert section_update_calls == []
    assert clear_calls == []
    assert [call[0]["key"] for call in progress_update_calls] == ["stock-a"]
    assert "1/2 wells" in widget._sections["head:stock-a"]["button"].text()


def test_progress_for_one_head_does_not_retitle_other_head(qapp):
    widget, model, _controller, _heads = _make_widget(
        qapp,
        active_stock="stock-a",
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [1, 1], "stock-b": [1]},
    )
    stock_b_header = widget._sections["head:stock-b"]["button"].text()
    progress_update_calls = _spy_method(widget, "_update_head_progress_header")

    for well in model.well_plate.get_all_wells():
        if "stock-a" in well._remaining_by_stock:
            well._remaining_by_stock["stock-a"] = 0
            break

    widget.refresh()

    assert [call[0]["key"] for call in progress_update_calls] == ["stock-a"]
    assert widget._sections["head:stock-b"]["button"].text() == stock_b_header


def test_missing_calibration_highlights_calibration_as_next_head_task(qapp):
    widget, _model, _controller, heads = _make_widget(qapp, active_stock="stock-a")

    context = widget._head_context(heads["stock-a"])

    assert widget.next_label.text() == "Next: Calibrate printer head for Reagent A"
    assert context["current_task"]["key"] == "calibrate"
    assert context["current_task"]["state"] == "current"


def test_applied_calibration_with_remaining_wells_highlights_print(qapp):
    widget, _model, _controller, heads = _make_widget(
        qapp,
        active_stock="stock-a",
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [0, 1]},
    )

    context = widget._head_context(heads["stock-a"])

    assert widget.next_label.text() == "Next: Print array for Reagent A"
    assert context["current_task"]["key"] == "print"
    assert context["current_task"]["state"] == "current"


def test_print_preflight_message_is_contextual_blocking_text(qapp):
    widget, _model, _controller, heads = _make_widget(
        qapp,
        active_stock="stock-a",
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [1]},
        preflight={"ok": False, "message": "Print pressure does not match the applied calibration."},
    )

    context = widget._head_context(heads["stock-a"])

    assert context["current_task"]["key"] == "print"
    assert context["current_task"]["state"] == "blocked"
    assert widget.blocking_label.text() == "Print pressure does not match the applied calibration."


def test_queue_busy_is_contextual_print_blocker_only(qapp):
    widget, _model, _controller, heads = _make_widget(
        qapp,
        active_stock="stock-a",
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [1]},
        queue_idle=False,
    )

    context = widget._head_context(heads["stock-a"])

    assert widget.next_label.text() == "Next: Print array for Reagent A"
    assert context["current_task"]["key"] == "print"
    assert context["current_task"]["state"] == "blocked"
    assert widget.blocking_label.text() == "The command queue must finish before printing."


def test_commands_completed_does_not_refresh_contextual_blocker(qapp):
    widget, _model, controller, heads = _make_widget(
        qapp,
        active_stock="stock-a",
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [1]},
        queue_idle=False,
    )
    assert widget._head_context(heads["stock-a"])["current_task"]["state"] == "blocked"
    assert widget.blocking_label.text() == "The command queue must finish before printing."

    clear_calls = _count_layout_clears(widget)
    controller.check_if_all_completed.return_value = True
    controller.machine.command_queue.commands_completed.emit()
    _wait_for_debounced_refresh(qapp)

    assert clear_calls == []
    assert widget.blocking_label.text() == "The command queue must finish before printing."


def test_applied_calibration_signal_refreshes_guide(qapp):
    widget, model, _controller, heads = _make_widget(qapp, active_stock="stock-a")
    assert widget.next_label.text() == "Next: Calibrate printer head for Reagent A"

    model.experiment_model._applied_stock_ids.add("stock-a")
    model.experiment_model.applied_imaging_calibration_changed.emit({"stock_id": "stock-a"})
    _wait_for_debounced_refresh(qapp)

    context = widget._head_context(heads["stock-a"])
    assert context["current_task"]["key"] == "print"
    assert widget.next_label.text() == "Next: Print array for Reagent A"


def test_applied_calibration_updates_only_active_head_section(qapp):
    widget, model, _controller, _heads = _make_widget(
        qapp,
        active_stock="stock-a",
        calibrated_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [1], "stock-b": [1]},
    )
    assert widget.next_label.text() == "Next: Apply calibration to experiment for Reagent A"

    full_rebuild_calls = _spy_method(widget, "_full_rebuild")
    global_update_calls = _spy_method(widget, "_update_global_section")
    head_update_calls = _spy_method(widget, "_update_head_section")
    progress_update_calls = _spy_method(widget, "_update_head_progress_header")

    model.experiment_model._applied_stock_ids.add("stock-a")
    model.experiment_model.applied_imaging_calibration_changed.emit({"stock_id": "stock-a"})
    _wait_for_debounced_refresh(qapp)

    assert full_rebuild_calls == []
    assert global_update_calls == []
    assert progress_update_calls == []
    assert [call[0]["key"] for call in head_update_calls] == ["stock-a"]
    assert widget.next_label.text() == "Next: Print array for Reagent A"


def test_queue_updated_does_not_refresh_contextual_blocker(qapp):
    widget, _model, controller, heads = _make_widget(
        qapp,
        active_stock="stock-a",
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [1]},
        queue_idle=False,
    )
    assert widget._head_context(heads["stock-a"])["current_task"]["state"] == "blocked"
    assert widget.blocking_label.text() == "The command queue must finish before printing."

    clear_calls = _count_layout_clears(widget)
    controller.check_if_all_completed.return_value = True
    for _ in range(10):
        controller.machine.command_queue.queue_updated.emit()

    qapp.processEvents()
    assert clear_calls == []

    _wait_for_debounced_refresh(qapp)

    assert clear_calls == []
    assert widget.blocking_label.text() == "The command queue must finish before printing."


def test_calibration_completed_does_not_refresh_guide(qapp):
    widget, model, _controller, _heads = _make_widget(qapp, active_stock="stock-a")
    clear_calls = _count_layout_clears(widget)

    model.calibration_manager.calibrationCompleted.emit()
    _wait_for_debounced_refresh(qapp)

    assert clear_calls == []


def test_unchanged_calibration_summary_update_does_not_refresh_guide(qapp):
    widget, model, _controller, _heads = _make_widget(
        qapp,
        active_stock="stock-a",
        calibration_summary_rows=[_summary_row()],
    )
    clear_calls = _count_layout_clears(widget)

    model.calibration_manager.characterizationSummaryUpdated.emit()
    _wait_for_debounced_refresh(qapp)

    assert clear_calls == []


def test_new_calibration_summary_row_refreshes_guide(qapp):
    widget, model, _controller, heads = _make_widget(qapp, active_stock="stock-a")
    assert widget.next_label.text() == "Next: Calibrate printer head for Reagent A"

    clear_calls = _count_layout_clears(widget)
    model.calibration_manager.summary_rows.append(_summary_row())
    model.calibration_manager.characterizationSummaryUpdated.emit()

    qapp.processEvents()
    assert clear_calls == []

    _wait_for_debounced_refresh(qapp)

    context = widget._head_context(heads["stock-a"])
    assert clear_calls == ["clear"]
    assert context["current_task"]["key"] == "apply"
    assert widget.next_label.text() == "Next: Apply calibration to experiment for Reagent A"


def test_machine_readiness_change_updates_only_run_readiness(qapp):
    widget, model, _controller, _heads = _make_widget(qapp, connected=False)
    assert widget.next_label.text() == "Next: Connect to the machine"

    full_rebuild_calls = _spy_method(widget, "_full_rebuild")
    global_update_calls = _spy_method(widget, "_update_global_section")
    head_update_calls = _spy_method(widget, "_update_head_section")
    progress_update_calls = _spy_method(widget, "_update_head_progress_header")

    model.machine_model.connected = True
    widget.refresh()

    assert full_rebuild_calls == []
    assert len(global_update_calls) == 1
    assert head_update_calls == []
    assert progress_update_calls == []
    assert widget.next_label.text() == "Next: Load printer head for Reagent A"


def test_head_list_change_full_rebuilds_and_preserves_active_auto_expansion(qapp):
    widget, model, _controller, _heads = _make_widget(qapp, active_stock="stock-a")
    full_rebuild_calls = _spy_method(widget, "_full_rebuild")

    model.printer_head_manager.printer_heads.append(HeadStub("stock-c", "Reagent C"))
    widget.refresh()

    assert len(full_rebuild_calls) == 1
    assert widget._sections["head:stock-a"]["button"].isChecked() is True
    assert "head:stock-c" in widget._sections


def test_unchanged_refresh_skips_full_layout_rebuild(qapp):
    widget, _model, _controller, _heads = _make_widget(qapp)
    clear_calls = []
    original_clear_layout = widget._clear_layout

    def counted_clear_layout(layout):
        clear_calls.append("clear")
        return original_clear_layout(layout)

    widget._clear_layout = counted_clear_layout

    widget.refresh()

    assert clear_calls == []


def test_calibration_stage_changes_do_not_refresh_guide(qapp):
    widget, model, _controller, _heads = _make_widget(qapp, active_stock="stock-a")
    clear_calls = []
    original_clear_layout = widget._clear_layout

    def counted_clear_layout(layout):
        clear_calls.append("clear")
        return original_clear_layout(layout)

    widget._clear_layout = counted_clear_layout

    model.calibration_manager.calibrationStageChanged.emit("stage")
    _wait_for_debounced_refresh(qapp)

    assert clear_calls == []


def test_running_print_array_is_in_progress_not_blocked(qapp):
    widget, _model, _controller, heads = _make_widget(
        qapp,
        active_stock="stock-a",
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [1]},
        queue_idle=False,
        array_state="running",
    )

    context = widget._head_context(heads["stock-a"])

    assert widget.next_label.text() == "Next: Printing array for Reagent A"
    assert context["current_task"]["key"] == "print"
    assert context["current_task"]["state"] == "in_progress"


def test_stop_requested_print_array_shows_stopping_guidance(qapp):
    widget, _model, _controller, heads = _make_widget(
        qapp,
        active_stock="stock-a",
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [1]},
        queue_idle=False,
        array_state="stop_requested",
    )

    context = widget._head_context(heads["stock-a"])

    assert widget.next_label.text() == "Next: Stopping after current well for Reagent A"
    assert context["current_task"]["key"] == "print"
    assert context["current_task"]["state"] == "stopping"


def test_printed_active_head_highlights_dropoff_and_keeps_recheck_optional(qapp):
    widget, _model, _controller, heads = _make_widget(
        qapp,
        active_stock="stock-a",
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [0, 0]},
    )

    context = widget._head_context(heads["stock-a"])
    tasks_by_key = {task["key"]: task for task in context["tasks"]}

    assert widget.next_label.text() == "Next: Drop off printer head for Reagent A"
    assert context["current_task"]["key"] == "dropoff"
    assert tasks_by_key["recheck"]["state"] == "optional"


def test_print_completion_boundary_rebuilds_only_active_head_section(qapp):
    widget, model, _controller, _heads = _make_widget(
        qapp,
        active_stock="stock-a",
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [1], "stock-b": [1]},
    )
    assert widget.next_label.text() == "Next: Print array for Reagent A"

    full_rebuild_calls = _spy_method(widget, "_full_rebuild")
    global_update_calls = _spy_method(widget, "_update_global_section")
    head_update_calls = _spy_method(widget, "_update_head_section")
    progress_update_calls = _spy_method(widget, "_update_head_progress_header")

    for well in model.well_plate.get_all_wells():
        if "stock-a" in well._remaining_by_stock:
            well._remaining_by_stock["stock-a"] = 0
            break

    widget.refresh()

    assert full_rebuild_calls == []
    assert global_update_calls == []
    assert progress_update_calls == []
    assert [call[0]["key"] for call in head_update_calls] == ["stock-a"]
    assert widget.next_label.text() == "Next: Drop off printer head for Reagent A"


def test_printed_dropped_off_head_is_complete(qapp):
    widget, _model, _controller, heads = _make_widget(
        qapp,
        active_stock=None,
        calibrated_stock_ids={"stock-a"},
        applied_stock_ids={"stock-a"},
        progress_by_stock={"stock-a": [0, 0]},
    )

    context = widget._head_context(heads["stock-a"])

    assert context["current_task"] is None
    assert context["done_count"] == context["total_count"]
    assert "Complete" in widget._sections["head:stock-a"]["button"].text()


def test_all_printed_and_dropped_off_heads_show_experiment_complete_even_if_queue_busy(qapp):
    widget, _model, _controller, _heads = _make_widget(
        qapp,
        active_stock=None,
        calibrated_stock_ids={"stock-a", "stock-b"},
        applied_stock_ids={"stock-a", "stock-b"},
        progress_by_stock={"stock-a": [0, 0], "stock-b": [0]},
        queue_idle=False,
    )

    assert widget.next_label.text() == "Next: Experiment complete"
    assert widget.blocking_label.text() == ""


def test_refresh_does_not_trigger_hardware_actions(qapp):
    widget, _model, controller, _heads = _make_widget(qapp, active_stock="stock-a")

    widget.refresh()

    controller.print_array.assert_not_called()
    controller.pick_up_printer_head.assert_not_called()
    controller.drop_off_printer_head.assert_not_called()


def test_section_headers_do_not_emit_stylesheet_parse_warning(qapp):
    if not hasattr(QtCore, "qInstallMessageHandler"):
        pytest.skip("Qt message handler is unavailable")
    messages = []
    old_handler = QtCore.qInstallMessageHandler(
        lambda _mode, _context, message: messages.append(str(message))
    )
    try:
        _make_widget(qapp, active_stock="stock-a")
        qapp.processEvents()
    finally:
        QtCore.qInstallMessageHandler(old_handler)

    assert not any("Could not parse stylesheet" in message for message in messages)
