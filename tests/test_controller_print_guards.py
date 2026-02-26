from types import SimpleNamespace
from unittest.mock import Mock

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
