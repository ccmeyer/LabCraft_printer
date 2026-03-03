import sys
import types
from types import SimpleNamespace


if "Model" not in sys.modules:
    fake_model = types.ModuleType("Model")
    fake_model.Model = object
    fake_model.PrinterHead = object
    fake_model.Slot = object
    sys.modules["Model"] = fake_model

from Controller import Controller


class _Recorder:
    def __init__(self):
        self.calls = []

    def emit(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def _build_controller():
    c = Controller.__new__(Controller)
    proc_err = _Recorder()
    mgr_err = _Recorder()
    c.model = SimpleNamespace(
        calibration_manager=SimpleNamespace(
            activeCalibration=SimpleNamespace(calibrationError=proc_err),
            calibrationError=mgr_err,
        )
    )
    return c, proc_err, mgr_err

def _build_controller_without_active():
    c = Controller.__new__(Controller)
    proc_err = _Recorder()
    mgr_err = _Recorder()
    c.model = SimpleNamespace(
        calibration_manager=SimpleNamespace(
            activeCalibration=None,
            calibrationError=mgr_err,
        )
    )
    return c, proc_err, mgr_err


def test_handle_move_request_emits_active_calibration_error_on_reject():
    c, proc_err, _ = _build_controller()
    c.set_relative_coordinates = lambda *args, **kwargs: False

    Controller.handle_move_request(c, (1, 2, 3), lambda: None)

    assert proc_err.calls, "Expected active calibration error on rejected move"
    assert "rejected" in proc_err.calls[0][0][0].lower()


def test_handle_move_request_emits_active_calibration_error_on_exception():
    c, proc_err, _ = _build_controller()

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    c.set_relative_coordinates = _boom
    Controller.handle_move_request(c, (1, 2, 3), lambda: None)

    assert proc_err.calls, "Expected active calibration error on move exception"
    assert "failed" in proc_err.calls[0][0][0].lower()


def test_handle_absolute_move_request_emits_active_calibration_error_on_reject():
    c, proc_err, _ = _build_controller()
    c.set_absolute_coordinates = lambda *args, **kwargs: False

    Controller.handle_absolute_move_request(c, {"X": 10, "Y": 20, "Z": 30}, lambda: None)

    assert proc_err.calls, "Expected active calibration error on rejected absolute move"
    assert "rejected" in proc_err.calls[0][0][0].lower()


def test_handle_absolute_move_request_success_does_not_emit_error():
    c, proc_err, mgr_err = _build_controller()

    def _ok(*args, **kwargs):
        cb = kwargs.get("handler")
        if callable(cb):
            cb()
        return True

    c.set_absolute_coordinates = _ok

    called = {"done": False}
    Controller.handle_absolute_move_request(
        c,
        (1, 2, 3),
        lambda: called.__setitem__("done", True),
    )

    assert called["done"] is True
    assert proc_err.calls == []
    assert mgr_err.calls == []


def test_handle_absolute_move_request_emits_error_on_exception():
    c, proc_err, _ = _build_controller()

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    c.set_absolute_coordinates = _boom

    Controller.handle_absolute_move_request(c, (1, 2, 3), lambda: None)

    assert proc_err.calls, "Expected active calibration error on absolute move exception"
    assert "failed" in proc_err.calls[0][0][0].lower()


def test_move_handler_falls_back_to_manager_error_when_no_active_calibration():
    c, _, mgr_err = _build_controller_without_active()
    c.set_relative_coordinates = lambda *args, **kwargs: False

    Controller.handle_move_request(c, (5, 0, 0), lambda: None)

    assert mgr_err.calls, "Expected manager-level calibrationError emit when active process is missing"
