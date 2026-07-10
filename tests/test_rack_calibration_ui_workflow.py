from types import SimpleNamespace

from PySide6 import QtWidgets

import View


class FakePrinterHead:
    def __init__(self, *, calibration_chip=True):
        self._calibration_chip = calibration_chip

    def is_calibration_chip(self):
        return self._calibration_chip


class FakeSlot:
    def __init__(self, printer_head=None):
        self.printer_head = printer_head


class FakeRackModel:
    def __init__(self, *, calibration_chip=None, origin_slot_number=4, gripper_printer_head=None):
        self.slots = [FakeSlot() for _ in range(6)]
        if calibration_chip is not None and origin_slot_number is not None:
            self.slots[origin_slot_number].printer_head = calibration_chip
        self.gripper_printer_head = gripper_printer_head
        self.gripper_slot_number = origin_slot_number if gripper_printer_head is not None else None
        self.update_calls = 0
        self.discard_calls = 0

    def get_gripper_printer_head(self):
        return self.gripper_printer_head

    def find_slot_for_printer_head(self, printer_head):
        for slot_number, slot in enumerate(self.slots):
            if slot.printer_head is printer_head:
                return slot_number
        return None

    def get_all_slots(self):
        return self.slots

    def update_calibration_data(self):
        self.update_calls += 1

    def discard_temp_calibrations(self):
        self.discard_calls += 1


class FakeMainWindow:
    def __init__(self, *, yes_no=None, choices=None):
        self.yes_no = list(yes_no or [])
        self.choices = list(choices or [])
        self.messages = []
        self.yes_no_prompts = []
        self.choice_prompts = []

    def popup_message(self, title, message):
        self.messages.append((title, message))

    def popup_yes_no(self, title, message):
        self.yes_no_prompts.append((title, message))
        if self.yes_no:
            return self.yes_no.pop(0)
        return "yes"

    def popup_choice(self, title, message, options, *, default=None):
        self.choice_prompts.append((title, message, tuple(options), default))
        if self.choices:
            return self.choices.pop(0)
        return default or options[0]

    @staticmethod
    def _is_no_response(response):
        return str(response).replace("&", "").strip().lower() in {"no", "n"}


class FakeController:
    def __init__(self, events, rack_model, calibration_chip):
        self.events = events
        self.rack_model = rack_model
        self.calibration_chip = calibration_chip
        self.dropoff_result = True
        self.move_result = True
        self.begin_remove_result = True
        self.begin_remove_message = "open failed"
        self.complete_remove_result = True
        self.complete_remove_message = "close failed"

    def begin_manual_calibration_chip_load(self, origin_slot_number=None, on_open=None, on_failed=None):
        self.events.append(("begin_load", origin_slot_number))
        if callable(on_open):
            on_open()
        return True

    def complete_manual_calibration_chip_load(self, origin_slot_number=None, on_loaded=None, on_failed=None):
        self.events.append(("complete_load", origin_slot_number))
        self.rack_model.gripper_printer_head = self.calibration_chip
        self.rack_model.gripper_slot_number = origin_slot_number
        self.rack_model.slots[origin_slot_number].printer_head = None
        if callable(on_loaded):
            on_loaded()
        return True

    def drop_off_printer_head(self, slot_number, manual=False):
        self.events.append(("dropoff", slot_number, manual))
        return self.dropoff_result

    def move_to_location(self, name, **kwargs):
        self.events.append(("move_to_location", name, kwargs))
        if self.move_result is False:
            return False
        on_complete = kwargs.get("on_complete")
        if callable(on_complete):
            on_complete()
        return self.move_result

    def begin_manual_calibration_chip_removal(self, on_open=None, on_failed=None):
        self.events.append(("begin_remove",))
        if self.begin_remove_result is False:
            if callable(on_failed):
                on_failed(self.begin_remove_message)
            return False
        if callable(on_open):
            on_open()
        return self.begin_remove_result

    def complete_manual_calibration_chip_removal(self, on_removed=None, on_failed=None):
        self.events.append(("complete_remove",))
        if self.complete_remove_result is False:
            if callable(on_failed):
                on_failed(self.complete_remove_message)
            return False
        self.rack_model.gripper_printer_head = None
        self.rack_model.gripper_slot_number = None
        if callable(on_removed):
            on_removed()
        return self.complete_remove_result


def install_fake_rack_dialog(monkeypatch, events, result):
    class FakeRackCalibrationDialog:
        def __init__(self, main_window, model, controller):
            self.main_window = main_window
            self.model = model
            self.controller = controller
            events.append(("dialog_init",))

        def exec(self):
            events.append(("dialog_exec",))
            return result

    monkeypatch.setattr(View, "RackCalibrationDialog", FakeRackCalibrationDialog)


def make_widget(
    *,
    calibration_chip=None,
    gripper_printer_head=None,
    motors_enabled=True,
    motors_homed=True,
    main_window=None,
):
    events = []
    if calibration_chip is None:
        calibration_chip = FakePrinterHead()
    rack_model = FakeRackModel(
        calibration_chip=calibration_chip,
        gripper_printer_head=gripper_printer_head,
    )
    main_window = main_window or FakeMainWindow()
    controller = FakeController(events, rack_model, calibration_chip)

    widget = View.RackBox.__new__(View.RackBox)
    widget.main_window = main_window
    widget.rack_model = rack_model
    widget.controller = controller
    widget.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            motors_are_enabled=lambda: motors_enabled,
            motors_are_homed=lambda: motors_homed,
        ),
        rack_model=rack_model,
        printer_head_manager=SimpleNamespace(get_calibration_chip=lambda: calibration_chip),
    )
    return widget, events, rack_model, main_window


def test_loaded_calibration_chip_opens_guided_rack_dialog_and_updates(monkeypatch):
    chip = FakePrinterHead()
    widget, events, rack_model, main_window = make_widget(gripper_printer_head=chip)
    install_fake_rack_dialog(monkeypatch, events, QtWidgets.QDialog.Accepted)

    result = View.RackBox.open_rack_calibration_dialog(widget)

    assert result is True
    assert events == [("dialog_init",), ("dialog_exec",)]
    assert rack_model.update_calls == 1
    assert rack_model.discard_calls == 0
    assert main_window.messages == []


def test_cancelled_guided_rack_dialog_discards_temp_calibrations(monkeypatch):
    chip = FakePrinterHead()
    widget, events, rack_model, _main_window = make_widget(gripper_printer_head=chip)
    install_fake_rack_dialog(monkeypatch, events, QtWidgets.QDialog.Rejected)

    result = View.RackBox.open_rack_calibration_dialog(widget)

    assert result is True
    assert events == [("dialog_init",), ("dialog_exec",)]
    assert rack_model.update_calls == 0
    assert rack_model.discard_calls == 1


def test_rack_calibration_blocks_when_motors_are_not_ready(monkeypatch):
    widget, events, rack_model, main_window = make_widget(motors_enabled=False)
    install_fake_rack_dialog(monkeypatch, events, QtWidgets.QDialog.Accepted)

    result = View.RackBox.open_rack_calibration_dialog(widget)

    assert result is False
    assert events == []
    assert rack_model.update_calls == 0
    assert main_window.messages == [
        ("Motors Not Enabled or Homed", "Please enable and home the motors before calibrating the rack.")
    ]


def test_rack_calibration_blocks_non_calibration_gripper_head(monkeypatch):
    head = FakePrinterHead(calibration_chip=False)
    widget, events, rack_model, main_window = make_widget(gripper_printer_head=head)
    install_fake_rack_dialog(monkeypatch, events, QtWidgets.QDialog.Accepted)

    result = View.RackBox.open_rack_calibration_dialog(widget)

    assert result is False
    assert events == []
    assert rack_model.update_calls == 0
    assert main_window.messages == [
        (
            "Calibration Chip Required",
            "Please remove the current printer head and load the calibration chip before calibrating the rack.",
        )
    ]


def test_empty_gripper_manual_load_then_guided_dialog(monkeypatch):
    main_window = FakeMainWindow(yes_no=["yes"], choices=["Leave in Gripper"])
    widget, events, rack_model, main_window = make_widget(main_window=main_window)
    install_fake_rack_dialog(monkeypatch, events, QtWidgets.QDialog.Accepted)

    result = View.RackBox.open_rack_calibration_dialog(widget)

    assert result is True
    assert events == [
        ("begin_load", 4),
        ("complete_load", 4),
        ("dialog_init",),
        ("dialog_exec",),
    ]
    assert main_window.yes_no_prompts[0][0] == "Manual Calibration Chip Load"
    assert main_window.messages == [
        (
            "Insert Calibration Chip",
            "Insert the calibration chip into the gripper, then click OK to close the gripper.",
        )
    ]
    assert main_window.choice_prompts[0][0] == "Calibration Chip Cleanup"
    assert rack_model.gripper_printer_head is widget.model.printer_head_manager.get_calibration_chip()
    assert rack_model.gripper_slot_number == 4
    assert rack_model.update_calls == 1


def test_empty_gripper_manual_load_can_be_declined(monkeypatch):
    main_window = FakeMainWindow(yes_no=["no"])
    widget, events, rack_model, _main_window = make_widget(main_window=main_window)
    install_fake_rack_dialog(monkeypatch, events, QtWidgets.QDialog.Accepted)

    result = View.RackBox.open_rack_calibration_dialog(widget)

    assert result is False
    assert events == []
    assert rack_model.update_calls == 0
    assert rack_model.discard_calls == 0


def test_manual_load_cleanup_can_drop_chip_back_to_origin_slot(monkeypatch):
    main_window = FakeMainWindow(yes_no=["yes"], choices=["Drop Off in Rack"])
    widget, events, rack_model, _main_window = make_widget(main_window=main_window)
    install_fake_rack_dialog(monkeypatch, events, QtWidgets.QDialog.Accepted)

    result = View.RackBox.open_rack_calibration_dialog(widget)

    assert result is True
    assert events[-1] == ("dropoff", 4, True)
    assert rack_model.update_calls == 1


def test_manual_load_cleanup_dropoff_falls_back_to_gripper_slot_number():
    chip = FakePrinterHead()
    widget, events, rack_model, _main_window = make_widget(gripper_printer_head=chip)
    rack_model.gripper_slot_number = 2

    result = widget._drop_off_manual_rack_calibration_chip(None)

    assert result is True
    assert events == [("dropoff", 2, True)]


def test_manual_load_cleanup_dropoff_unknown_origin_shows_error():
    chip = FakePrinterHead()
    widget, events, rack_model, main_window = make_widget(gripper_printer_head=chip)
    rack_model.gripper_slot_number = None

    result = widget._drop_off_manual_rack_calibration_chip(None)

    assert result is False
    assert events == []
    assert main_window.messages == [
        (
            "Calibration Chip Cleanup",
            "Cannot drop off the calibration chip automatically because its origin slot is unknown.",
        )
    ]


def test_manual_load_cleanup_dropoff_invalid_origin_shows_error():
    chip = FakePrinterHead()
    widget, events, _rack_model, main_window = make_widget(gripper_printer_head=chip)

    result = widget._drop_off_manual_rack_calibration_chip(99)

    assert result is False
    assert events == []
    assert main_window.messages == [
        ("Calibration Chip Cleanup", "Calibration chip origin slot 99 is out of range.")
    ]


def test_manual_load_cleanup_dropoff_queue_failure_shows_error():
    chip = FakePrinterHead()
    widget, events, _rack_model, main_window = make_widget(gripper_printer_head=chip)
    widget.controller.dropoff_result = False

    result = widget._drop_off_manual_rack_calibration_chip(4)

    assert result is False
    assert events == [("dropoff", 4, True)]
    assert main_window.messages == [
        ("Calibration Chip Cleanup", "Failed to queue automatic calibration chip dropoff.")
    ]


def test_manual_load_cleanup_rejects_non_calibration_chip_during_cleanup():
    head = FakePrinterHead(calibration_chip=False)
    widget, events, _rack_model, main_window = make_widget(gripper_printer_head=head)

    result = widget._prompt_manual_rack_calibration_chip_cleanup(4)

    assert result is False
    assert events == []
    assert main_window.messages == [
        ("Calibration Chip Cleanup", "The gripper is not holding a calibration chip. Cleanup was not started.")
    ]


def test_manual_load_cleanup_can_manually_remove_chip_at_home(monkeypatch):
    main_window = FakeMainWindow(yes_no=["yes"], choices=["Manual Remove"])
    widget, events, rack_model, main_window = make_widget(main_window=main_window)
    install_fake_rack_dialog(monkeypatch, events, QtWidgets.QDialog.Accepted)

    result = View.RackBox.open_rack_calibration_dialog(widget)

    assert result is True
    assert events[-3:] == [
        ("move_to_location", "home", {"manual": True, "on_complete": events[-3][2]["on_complete"]}),
        ("begin_remove",),
        ("complete_remove",),
    ]
    assert rack_model.gripper_printer_head is None
    assert main_window.messages[-1] == (
        "Remove Calibration Chip",
        "Hold the calibration chip, remove it from the gripper, then click OK to close the gripper.",
    )


def test_manual_load_cleanup_manual_remove_home_move_failure_shows_error():
    chip = FakePrinterHead()
    widget, events, rack_model, main_window = make_widget(gripper_printer_head=chip)
    widget.controller.move_result = False

    result = widget._begin_manual_rack_calibration_chip_removal()

    assert result is False
    assert events == [("move_to_location", "home", events[0][2])]
    assert rack_model.gripper_printer_head is chip
    assert main_window.messages == [
        (
            "Calibration Chip Cleanup",
            "Failed to queue the move home before manual calibration chip removal.",
        )
    ]


def test_manual_load_cleanup_manual_remove_open_failure_shows_error():
    chip = FakePrinterHead()
    widget, events, rack_model, main_window = make_widget(gripper_printer_head=chip)
    widget.controller.begin_remove_result = False
    widget.controller.begin_remove_message = "open command failed"

    result = widget._begin_manual_rack_calibration_chip_removal()

    assert result is True
    assert events == [
        ("move_to_location", "home", events[0][2]),
        ("begin_remove",),
    ]
    assert rack_model.gripper_printer_head is chip
    assert main_window.messages == [("Calibration Chip Cleanup", "open command failed")]


def test_manual_load_cleanup_manual_remove_close_failure_shows_error():
    chip = FakePrinterHead()
    widget, events, rack_model, main_window = make_widget(gripper_printer_head=chip)
    widget.controller.complete_remove_result = False
    widget.controller.complete_remove_message = "close command failed"

    result = widget._begin_manual_rack_calibration_chip_removal()

    assert result is True
    assert events == [
        ("move_to_location", "home", events[0][2]),
        ("begin_remove",),
        ("complete_remove",),
    ]
    assert rack_model.gripper_printer_head is chip
    assert main_window.messages == [
        (
            "Remove Calibration Chip",
            "Hold the calibration chip, remove it from the gripper, then click OK to close the gripper.",
        ),
        ("Calibration Chip Cleanup", "close command failed"),
    ]


def test_manual_load_cleanup_runs_after_cancelled_guided_dialog(monkeypatch):
    main_window = FakeMainWindow(yes_no=["yes"], choices=["Drop Off in Rack"])
    widget, events, rack_model, _main_window = make_widget(main_window=main_window)
    install_fake_rack_dialog(monkeypatch, events, QtWidgets.QDialog.Rejected)

    result = View.RackBox.open_rack_calibration_dialog(widget)

    assert result is True
    assert rack_model.update_calls == 0
    assert rack_model.discard_calls == 1
    assert events[-1] == ("dropoff", 4, True)
