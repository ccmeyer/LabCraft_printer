from types import SimpleNamespace

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import BaseCalibrationProcess


def _build_base_process():
    proc = BaseCalibrationProcess.__new__(BaseCalibrationProcess)
    proc.calibrationError = Recorder()
    proc.calibration_manager = SimpleNamespace(
        moveRequested=SimpleNamespace(emit=lambda *args, **kwargs: None),
        moveAbsoluteRequested=SimpleNamespace(emit=lambda *args, **kwargs: None),
        emitMoveCompleted=lambda: None,
    )
    return proc


def test_relative_move_timeout_emits_calibration_error():
    proc = _build_base_process()
    state = {"timeout_cb": None}

    def _start_timeout(_msec, **kwargs):
        state["timeout_cb"] = kwargs.get("on_timeout")
        return "timer-token"

    proc._start_timeout = _start_timeout
    proc._cancel_timeout = lambda timer: None
    proc.calibration_manager.moveRequested = SimpleNamespace(
        emit=lambda move, callback: None  # callback never called
    )

    proc._request_move_relative_with_timeout((10, 20, 30), timeout_ms=15000)
    assert callable(state["timeout_cb"])

    state["timeout_cb"]()
    assert proc.calibrationError.calls
    assert "timeout" in proc.calibrationError.calls[0][0][0].lower()


def test_absolute_move_callback_clears_timeout_and_runs_on_done():
    proc = _build_base_process()
    flags = {"done": False, "cancelled": []}

    proc._start_timeout = lambda msec, **kwargs: "timer-token"
    proc._cancel_timeout = lambda timer: flags["cancelled"].append(timer)
    proc.calibration_manager.moveAbsoluteRequested = SimpleNamespace(
        emit=lambda target, callback: callback()
    )

    proc._request_move_absolute_with_timeout(
        (100, 200, 300),
        timeout_ms=15000,
        on_done=lambda: flags.__setitem__("done", True),
    )

    assert flags["done"] is True
    assert flags["cancelled"] == ["timer-token"]
    assert proc.calibrationError.calls == []


def test_relative_move_request_exception_emits_error():
    proc = _build_base_process()
    proc._start_timeout = lambda msec, **kwargs: "timer-token"
    proc._cancel_timeout = lambda timer: None

    def _boom(*args, **kwargs):
        raise RuntimeError("move bus fault")

    proc.calibration_manager.moveRequested = SimpleNamespace(emit=_boom)
    proc._request_move_relative_with_timeout((1, 2, 3), timeout_ms=15000)

    assert proc.calibrationError.calls
    assert "failed" in proc.calibrationError.calls[0][0][0].lower()
