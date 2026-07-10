from types import SimpleNamespace

import pytest

from Controller import Controller


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class FakePrinterHead:
    def __init__(self, *, calibration_chip=True):
        self._calibration_chip = calibration_chip

    def is_calibration_chip(self):
        return self._calibration_chip


class FakeSlot:
    def __init__(self, printer_head=None):
        self.printer_head = printer_head


class FakeRackModel:
    def __init__(
        self,
        *,
        chip=None,
        origin_slot_number=4,
        gripper_printer_head=None,
        load_result=(True, ""),
        remove_result=(True, ""),
        slot_count=6,
    ):
        self.slots = [FakeSlot() for _ in range(slot_count)]
        if chip is not None and origin_slot_number is not None:
            self.slots[origin_slot_number].printer_head = chip
        self.gripper_printer_head = gripper_printer_head
        self.gripper_slot_number = origin_slot_number if gripper_printer_head is not None else None
        self.load_result = load_result
        self.remove_result = remove_result
        self.load_calls = []
        self.remove_calls = 0

    def get_gripper_printer_head(self):
        return self.gripper_printer_head

    def find_slot_for_printer_head(self, printer_head):
        for slot_number, slot in enumerate(self.slots):
            if slot.printer_head is printer_head:
                return slot_number
        return None

    def manual_load_calibration_chip_to_gripper(self, calibration_chip, origin_slot_number=None):
        self.load_calls.append((calibration_chip, origin_slot_number))
        ok, message = self.load_result
        if ok:
            self.gripper_printer_head = calibration_chip
            self.gripper_slot_number = origin_slot_number
            self.slots[origin_slot_number].printer_head = None
        return ok, message

    def manual_remove_calibration_chip_from_gripper(self):
        self.remove_calls += 1
        ok, message = self.remove_result
        if ok:
            self.gripper_printer_head = None
            self.gripper_slot_number = None
        return ok, message


class FakeMachine:
    def __init__(self, events, *, open_result=True, close_result=True):
        self.events = events
        self.open_result = open_result
        self.close_result = close_result

    def open_gripper(self, handler=None):
        self.events.append("open")
        if self.open_result is False:
            return False
        if callable(handler):
            handler()
        return self.open_result

    def close_gripper(self, handler=None):
        self.events.append("close")
        if self.close_result is False:
            return False
        if callable(handler):
            handler()
        return self.close_result


def make_controller(*, chip=None, rack_model=None, machine=None, events=None):
    if events is None and machine is not None and hasattr(machine, "events"):
        events = machine.events
    events = events if events is not None else []
    if rack_model is None:
        rack_model = FakeRackModel(chip=chip)
    if machine is None:
        machine = FakeMachine(events)

    controller = Controller.__new__(Controller)
    controller.error_occurred_signal = Emitter()
    controller.machine = machine
    controller.model = SimpleNamespace(
        rack_model=rack_model,
        printer_head_manager=SimpleNamespace(get_calibration_chip=lambda: chip),
    )
    return controller, events, rack_model


def test_begin_manual_calibration_chip_load_queues_open_and_calls_callback():
    chip = FakePrinterHead()
    controller, events, rack_model = make_controller(chip=chip)

    result = controller.begin_manual_calibration_chip_load(on_open=lambda: events.append("opened"))

    assert result is True
    assert events == ["open", "opened"]
    assert rack_model.load_calls == []
    assert controller.error_occurred_signal.calls == []


@pytest.mark.parametrize(
    ("chip", "rack_model", "origin_slot_number", "expected_message"),
    [
        (None, FakeRackModel(), None, "Calibration chip is unavailable."),
        (
            FakePrinterHead(calibration_chip=False),
            None,
            None,
            "Manual load requires a calibration chip.",
        ),
        (
            FakePrinterHead(),
            None,
            99,
            "Slot number 99 is out of range.",
        ),
    ],
)
def test_begin_manual_calibration_chip_load_rejects_invalid_chip_or_slot(
    chip,
    rack_model,
    origin_slot_number,
    expected_message,
):
    if rack_model is None:
        rack_model = FakeRackModel(chip=chip)
    controller, events, _rack_model = make_controller(chip=chip, rack_model=rack_model)
    failures = []

    result = controller.begin_manual_calibration_chip_load(
        origin_slot_number=origin_slot_number,
        on_failed=failures.append,
    )

    assert result is False
    assert events == []
    assert failures == [expected_message]
    assert controller.error_occurred_signal.calls == [
        ("Manual Calibration Chip Load Failed", expected_message)
    ]


def test_begin_manual_calibration_chip_load_rejects_occupied_gripper():
    chip = FakePrinterHead()
    occupied_head = FakePrinterHead(calibration_chip=False)
    rack_model = FakeRackModel(chip=chip, gripper_printer_head=occupied_head)
    controller, events, _rack_model = make_controller(chip=chip, rack_model=rack_model)

    result = controller.begin_manual_calibration_chip_load()

    assert result is False
    assert events == []
    assert controller.error_occurred_signal.calls == [
        ("Manual Calibration Chip Load Failed", "Gripper is already holding a printer head.")
    ]


def test_begin_manual_calibration_chip_load_rejects_mismatched_origin_slot():
    chip = FakePrinterHead()
    rack_model = FakeRackModel(chip=chip, origin_slot_number=4)
    rack_model.slots[2].printer_head = FakePrinterHead()
    controller, events, _rack_model = make_controller(chip=chip, rack_model=rack_model)

    result = controller.begin_manual_calibration_chip_load(origin_slot_number=2)

    assert result is False
    assert events == []
    assert controller.error_occurred_signal.calls == [
        ("Manual Calibration Chip Load Failed", "Origin slot does not contain the calibration chip.")
    ]


def test_begin_manual_calibration_chip_load_reports_open_queue_failure():
    chip = FakePrinterHead()
    machine = FakeMachine([], open_result=False)
    controller, events, _rack_model = make_controller(chip=chip, machine=machine)
    failures = []

    result = controller.begin_manual_calibration_chip_load(on_failed=failures.append)

    assert result is False
    assert events == ["open"]
    assert failures == ["Failed to send open gripper command."]
    assert controller.error_occurred_signal.calls == [
        ("Manual Calibration Chip Load Failed", "Failed to send open gripper command.")
    ]


def test_complete_manual_calibration_chip_load_closes_then_records_model_state():
    chip = FakePrinterHead()
    controller, events, rack_model = make_controller(chip=chip)

    result = controller.complete_manual_calibration_chip_load(on_loaded=lambda: events.append("loaded"))

    assert result is True
    assert events == ["close", "loaded"]
    assert rack_model.load_calls == [(chip, 4)]
    assert rack_model.gripper_printer_head is chip
    assert rack_model.gripper_slot_number == 4
    assert rack_model.slots[4].printer_head is None
    assert controller.error_occurred_signal.calls == []


def test_complete_manual_calibration_chip_load_uses_explicit_origin_slot():
    chip = FakePrinterHead()
    rack_model = FakeRackModel(chip=chip, origin_slot_number=2)
    controller, _events, rack_model = make_controller(chip=chip, rack_model=rack_model)

    result = controller.complete_manual_calibration_chip_load(origin_slot_number="2")

    assert result is True
    assert rack_model.load_calls == [(chip, 2)]


def test_complete_manual_calibration_chip_load_reports_model_failure_after_close():
    chip = FakePrinterHead()
    rack_model = FakeRackModel(chip=chip, load_result=(False, "model rejected load"))
    controller, events, rack_model = make_controller(chip=chip, rack_model=rack_model)
    failures = []

    result = controller.complete_manual_calibration_chip_load(
        on_loaded=lambda: events.append("loaded"),
        on_failed=failures.append,
    )

    assert result is True
    assert events == ["close"]
    assert rack_model.load_calls == [(chip, 4)]
    assert failures == ["model rejected load"]
    assert controller.error_occurred_signal.calls == [
        ("Manual Calibration Chip Load Failed", "model rejected load")
    ]


def test_complete_manual_calibration_chip_load_reports_close_queue_failure():
    chip = FakePrinterHead()
    machine = FakeMachine([], close_result=False)
    controller, events, rack_model = make_controller(chip=chip, machine=machine)
    failures = []

    result = controller.complete_manual_calibration_chip_load(on_failed=failures.append)

    assert result is False
    assert events == ["close"]
    assert rack_model.load_calls == []
    assert failures == ["Failed to send close gripper command."]
    assert controller.error_occurred_signal.calls == [
        ("Manual Calibration Chip Load Failed", "Failed to send close gripper command.")
    ]


def test_begin_manual_calibration_chip_removal_queues_open_and_calls_callback():
    chip = FakePrinterHead()
    rack_model = FakeRackModel(gripper_printer_head=chip)
    controller, events, _rack_model = make_controller(chip=chip, rack_model=rack_model)

    result = controller.begin_manual_calibration_chip_removal(on_open=lambda: events.append("opened"))

    assert result is True
    assert events == ["open", "opened"]
    assert controller.error_occurred_signal.calls == []


@pytest.mark.parametrize(
    ("gripper_head", "expected_message"),
    [
        (None, "Gripper is empty."),
        (FakePrinterHead(calibration_chip=False), "Gripper is not holding a calibration chip."),
    ],
)
def test_begin_manual_calibration_chip_removal_rejects_invalid_gripper_state(
    gripper_head,
    expected_message,
):
    rack_model = FakeRackModel(gripper_printer_head=gripper_head)
    controller, events, _rack_model = make_controller(rack_model=rack_model)
    failures = []

    result = controller.begin_manual_calibration_chip_removal(on_failed=failures.append)

    assert result is False
    assert events == []
    assert failures == [expected_message]
    assert controller.error_occurred_signal.calls == [
        ("Manual Calibration Chip Removal Failed", expected_message)
    ]


def test_begin_manual_calibration_chip_removal_reports_open_queue_failure():
    chip = FakePrinterHead()
    rack_model = FakeRackModel(gripper_printer_head=chip)
    machine = FakeMachine([], open_result=False)
    controller, events, _rack_model = make_controller(
        chip=chip,
        rack_model=rack_model,
        machine=machine,
    )
    failures = []

    result = controller.begin_manual_calibration_chip_removal(on_failed=failures.append)

    assert result is False
    assert events == ["open"]
    assert failures == ["Failed to send open gripper command."]
    assert controller.error_occurred_signal.calls == [
        ("Manual Calibration Chip Removal Failed", "Failed to send open gripper command.")
    ]


def test_complete_manual_calibration_chip_removal_closes_then_records_model_state():
    chip = FakePrinterHead()
    rack_model = FakeRackModel(gripper_printer_head=chip)
    controller, events, rack_model = make_controller(chip=chip, rack_model=rack_model)

    result = controller.complete_manual_calibration_chip_removal(
        on_removed=lambda: events.append("removed")
    )

    assert result is True
    assert events == ["close", "removed"]
    assert rack_model.remove_calls == 1
    assert rack_model.gripper_printer_head is None
    assert rack_model.gripper_slot_number is None
    assert controller.error_occurred_signal.calls == []


def test_complete_manual_calibration_chip_removal_reports_model_failure_after_close():
    chip = FakePrinterHead()
    rack_model = FakeRackModel(gripper_printer_head=chip, remove_result=(False, "model rejected removal"))
    controller, events, rack_model = make_controller(chip=chip, rack_model=rack_model)
    failures = []

    result = controller.complete_manual_calibration_chip_removal(
        on_removed=lambda: events.append("removed"),
        on_failed=failures.append,
    )

    assert result is True
    assert events == ["close"]
    assert rack_model.remove_calls == 1
    assert failures == ["model rejected removal"]
    assert controller.error_occurred_signal.calls == [
        ("Manual Calibration Chip Removal Failed", "model rejected removal")
    ]


def test_complete_manual_calibration_chip_removal_reports_close_queue_failure():
    chip = FakePrinterHead()
    rack_model = FakeRackModel(gripper_printer_head=chip)
    machine = FakeMachine([], close_result=False)
    controller, events, rack_model = make_controller(chip=chip, rack_model=rack_model, machine=machine)
    failures = []

    result = controller.complete_manual_calibration_chip_removal(on_failed=failures.append)

    assert result is False
    assert events == ["close"]
    assert rack_model.remove_calls == 0
    assert failures == ["Failed to send close gripper command."]
    assert controller.error_occurred_signal.calls == [
        ("Manual Calibration Chip Removal Failed", "Failed to send close gripper command.")
    ]
