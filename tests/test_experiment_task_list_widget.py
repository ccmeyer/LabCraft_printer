from types import SimpleNamespace
from unittest.mock import Mock

import pytest

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
    model.calibration_manager = SimpleNamespace(
        calibrationCompleted=SignalStub(),
        calibrationStageChanged=SignalStub(),
    )

    controller = SimpleNamespace(
        check_if_all_completed=Mock(return_value=queue_idle),
        get_array_run_state=Mock(return_value="idle"),
        get_print_array_imaging_calibration_preflight=Mock(return_value=preflight),
        array_state_changed=SignalStub(),
        array_complete=SignalStub(),
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


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"assigned": False}, "Next: Load or create an experiment"),
        ({"connected": False}, "Next: Connect to the machine"),
        ({"enabled": False}, "Next: Enable motors"),
        ({"homed": False}, "Next: Home motors"),
        ({"pressure": False}, "Next: Start pressure regulation"),
        ({"plate_calibrated": False}, "Next: Apply plate calibration"),
        ({"queue_idle": False}, "Next: Wait for queued commands"),
    ],
)
def test_global_readiness_selects_first_missing_step(qapp, kwargs, expected):
    widget, _model, _controller, _heads = _make_widget(qapp, **kwargs)

    assert widget.next_label.text() == expected
    assert widget._sections["global"]["button"].isChecked() is True


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


def test_refresh_does_not_trigger_hardware_actions(qapp):
    widget, _model, controller, _heads = _make_widget(qapp, active_stock="stock-a")

    widget.refresh()

    controller.print_array.assert_not_called()
    controller.pick_up_printer_head.assert_not_called()
    controller.drop_off_printer_head.assert_not_called()
