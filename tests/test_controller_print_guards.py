import Controller as controller_module
from types import SimpleNamespace
from unittest.mock import Mock, call

from Controller import Controller


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def _controller_for_print_guard(calibration_ok, gripper_info, regulation_on):
    c = Controller.__new__(Controller)
    c.error_occurred_signal = Emitter()
    c.close_gripper = Mock()
    c.move_to_location = Mock()
    c.enable_print_profile = Mock()
    c.print_droplets = Mock()

    c.model = SimpleNamespace(
        well_plate=SimpleNamespace(check_calibration_applied=lambda: calibration_ok),
        rack_model=SimpleNamespace(get_gripper_info=lambda: gripper_info),
        machine_model=SimpleNamespace(regulating_print_pressure=regulation_on),
    )
    return c


def test_print_array_blocks_when_plate_not_calibrated():
    c = _controller_for_print_guard(calibration_ok=False, gripper_info=object(), regulation_on=True)
    Controller.print_array(c)
    assert c.error_occurred_signal.calls[0][1] == "Calibration has not been applied to this plate"
    c.close_gripper.assert_not_called()


def test_print_array_blocks_when_no_printer_head_loaded():
    c = _controller_for_print_guard(calibration_ok=True, gripper_info=None, regulation_on=True)
    Controller.print_array(c)
    assert c.error_occurred_signal.calls[0][1] == "No printer head is loaded"
    c.close_gripper.assert_not_called()


def test_print_array_blocks_when_regulation_disabled():
    c = _controller_for_print_guard(calibration_ok=True, gripper_info=object(), regulation_on=False)
    Controller.print_array(c)
    assert c.error_occurred_signal.calls[0][1] == "Pressure regulation is not enabled"
    c.close_gripper.assert_not_called()


def test_last_well_complete_handler_persists_progress_and_emits_completion(monkeypatch):
    c = Controller.__new__(Controller)
    c.disable_print_profile = Mock()
    c.move_to_location = Mock()
    c.array_complete = Emitter()
    c.error_occurred_signal = Emitter()

    printer_head = SimpleNamespace(record_droplet_volume_lost=Mock())
    well = SimpleNamespace(record_stock_print=Mock())
    c.model = SimpleNamespace(
        rack_model=SimpleNamespace(get_gripper_printer_head=Mock(return_value=printer_head)),
        well_plate=SimpleNamespace(get_well=Mock(return_value=well)),
        experiment_model=SimpleNamespace(create_progress_file=Mock()),
    )

    monkeypatch.setattr(
        controller_module.QtCore.QTimer,
        "singleShot",
        staticmethod(lambda _ms, cb: cb()),
        raising=False,
    )

    Controller.last_well_complete_handler(
        c,
        well_id="P1",
        stock_id="stock-a",
        target_droplets=5,
        update_volume=True,
    )

    printer_head.record_droplet_volume_lost.assert_called_once_with(5)
    c.disable_print_profile.assert_called_once_with()
    assert c.move_to_location.call_args_list == [
        call("pause"),
        call("pause", z_offset=-5000),
    ]
    c.model.well_plate.get_well.assert_called_once_with("P1")
    well.record_stock_print.assert_called_once_with("stock-a", 5)
    c.model.experiment_model.create_progress_file.assert_called_once_with()
    assert c.array_complete.calls == [()]
    assert c.error_occurred_signal.calls == []
