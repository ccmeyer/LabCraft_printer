import pytest

from Model import PrinterHead, RackModel


LOCATION_DATA = {
    "rack_position_Left": {"X": 0, "Y": 0, "Z": 1000},
    "rack_position_Right": {"X": 0, "Y": 6000, "Z": 1000},
}


def _rack():
    return RackModel(5, location_data=LOCATION_DATA)


def _calibration_chip():
    return PrinterHead(None, color="#000000", calibration_chip=True)


def _printer_head():
    return PrinterHead(None, color="#123456", calibration_chip=False)


def _signals(rack):
    counts = {"slot": 0, "gripper": 0}
    rack.slot_updated.connect(lambda: counts.__setitem__("slot", counts["slot"] + 1))
    rack.gripper_updated.connect(lambda: counts.__setitem__("gripper", counts["gripper"] + 1))
    return counts


def _state_snapshot(rack):
    return {
        "slots": [slot.printer_head for slot in rack.slots],
        "locked": [slot.locked for slot in rack.slots],
        "confirmed": [slot.confirmed for slot in rack.slots],
        "gripper": rack.gripper_printer_head,
        "gripper_slot": rack.gripper_slot_number,
        "expected_slots": list(rack.expected_slot_printer_heads),
        "expected_gripper": rack.expected_gripper_printer_head,
        "expected_gripper_slot": rack.expected_gripper_slot_number,
    }


def test_manual_load_from_slot_moves_calibration_chip_to_gripper_and_syncs_expected_state(qapp):
    rack = _rack()
    chip = _calibration_chip()
    rack.update_slot_with_printer_head(4, chip)
    rack.confirm_slot(4)
    signals = _signals(rack)

    ok, message = rack.manual_load_calibration_chip_to_gripper(chip, origin_slot_number=4)

    assert (ok, message) == (True, "")
    assert rack.gripper_printer_head is chip
    assert rack.gripper_slot_number == 4
    assert rack.slots[4].printer_head is None
    assert rack.slots[4].locked is True
    assert rack.slots[4].confirmed is True
    assert rack.expected_gripper_printer_head is chip
    assert rack.expected_gripper_slot_number == 4
    assert rack.expected_slot_printer_heads[4] is None
    assert signals == {"slot": 1, "gripper": 1}


def test_manual_load_without_origin_slot_finds_calibration_chip_by_identity(qapp):
    rack = _rack()
    chip = _calibration_chip()
    other_chip = _calibration_chip()
    rack.update_slot_with_printer_head(2, chip)
    rack.update_slot_with_printer_head(4, other_chip)

    ok, message = rack.manual_load_calibration_chip_to_gripper(chip)

    assert (ok, message) == (True, "")
    assert rack.gripper_printer_head is chip
    assert rack.gripper_slot_number == 2
    assert rack.slots[2].printer_head is None
    assert rack.slots[4].printer_head is other_chip


def test_manual_load_rejects_non_calibration_head_without_changing_state(qapp):
    rack = _rack()
    head = _printer_head()
    rack.update_slot_with_printer_head(4, head)
    before = _state_snapshot(rack)
    signals = _signals(rack)

    ok, message = rack.manual_load_calibration_chip_to_gripper(head, origin_slot_number=4)

    assert ok is False
    assert message == "Manual load requires a calibration chip."
    assert _state_snapshot(rack) == before
    assert signals == {"slot": 0, "gripper": 0}


def test_manual_load_rejects_when_gripper_is_occupied_without_changing_state(qapp):
    rack = _rack()
    chip = _calibration_chip()
    occupied_head = _printer_head()
    rack.update_slot_with_printer_head(4, chip)
    rack.gripper_printer_head = occupied_head
    rack.gripper_slot_number = 0
    rack.sync_expected_to_actual()
    before = _state_snapshot(rack)
    signals = _signals(rack)

    ok, message = rack.manual_load_calibration_chip_to_gripper(chip, origin_slot_number=4)

    assert ok is False
    assert message == "Gripper is already holding a printer head."
    assert _state_snapshot(rack) == before
    assert signals == {"slot": 0, "gripper": 0}


@pytest.mark.parametrize(
    "origin_slot_number, setup_slot, expected_message",
    [
        (9, None, "Slot number 9 is out of range."),
        (4, None, "Origin slot does not contain the calibration chip."),
        (4, "different_head", "Origin slot does not contain the calibration chip."),
    ],
)
def test_manual_load_rejects_invalid_or_mismatched_origin_slot_without_changing_state(
    qapp, origin_slot_number, setup_slot, expected_message
):
    rack = _rack()
    chip = _calibration_chip()
    if setup_slot == "different_head":
        rack.update_slot_with_printer_head(4, _printer_head())
    before = _state_snapshot(rack)
    signals = _signals(rack)

    ok, message = rack.manual_load_calibration_chip_to_gripper(
        chip,
        origin_slot_number=origin_slot_number,
    )

    assert ok is False
    assert message == expected_message
    assert _state_snapshot(rack) == before
    assert signals == {"slot": 0, "gripper": 0}


def test_transfer_from_gripper_restores_manually_loaded_chip_to_original_slot(qapp):
    rack = _rack()
    chip = _calibration_chip()
    rack.update_slot_with_printer_head(4, chip)
    ok, message = rack.manual_load_calibration_chip_to_gripper(chip, origin_slot_number=4)
    assert (ok, message) == (True, "")

    rack.transfer_from_gripper(4)

    assert rack.gripper_printer_head is None
    assert rack.gripper_slot_number is None
    assert rack.slots[4].printer_head is chip
    assert rack.slots[4].locked is False
    assert rack.expected_slot_printer_heads[4] is chip
    assert rack.expected_gripper_printer_head is None
    assert rack.expected_gripper_slot_number is None


def test_manual_remove_calibration_chip_clears_gripper_and_leaves_chip_outside_rack_state(qapp):
    rack = _rack()
    chip = _calibration_chip()
    rack.update_slot_with_printer_head(4, chip)
    rack.confirm_slot(4)
    ok, message = rack.manual_load_calibration_chip_to_gripper(chip, origin_slot_number=4)
    assert (ok, message) == (True, "")
    signals = _signals(rack)

    ok, message = rack.manual_remove_calibration_chip_from_gripper()

    assert (ok, message) == (True, "")
    assert rack.gripper_printer_head is None
    assert rack.gripper_slot_number is None
    assert rack.slots[4].printer_head is None
    assert rack.slots[4].locked is False
    assert rack.slots[4].confirmed is False
    assert chip not in [slot.printer_head for slot in rack.slots]
    assert rack.expected_gripper_printer_head is None
    assert rack.expected_gripper_slot_number is None
    assert chip not in rack.expected_slot_printer_heads
    assert signals == {"slot": 1, "gripper": 1}


def test_manual_remove_rejects_empty_or_non_calibration_gripper_without_changing_state(qapp):
    rack = _rack()
    before = _state_snapshot(rack)
    signals = _signals(rack)

    ok, message = rack.manual_remove_calibration_chip_from_gripper()

    assert ok is False
    assert message == "Gripper is empty."
    assert _state_snapshot(rack) == before
    assert signals == {"slot": 0, "gripper": 0}

    rack.gripper_printer_head = _printer_head()
    rack.gripper_slot_number = 3
    rack.sync_expected_to_actual()
    before = _state_snapshot(rack)

    ok, message = rack.manual_remove_calibration_chip_from_gripper()

    assert ok is False
    assert message == "Gripper is not holding a calibration chip."
    assert _state_snapshot(rack) == before
    assert signals == {"slot": 0, "gripper": 0}
