from types import SimpleNamespace

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import CalibrationManager, NozzleFocusCalibrationProcess


def _ready_cm():
    return SimpleNamespace(
        get_nozzle_center=lambda: {"X": 1, "Y": 2, "Z": 3},
        get_nozzle_center_image_position=lambda: (100, 50),
        get_background_image=lambda: object(),
        model=SimpleNamespace(
            machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 0, "Y": 0, "Z": 0}),
            droplet_camera_model=SimpleNamespace(get_image_size=lambda: (1280, 1024)),
        ),
    )


def test_nozzle_focus_missing_requirements_reports_dependencies():
    cm = _ready_cm()
    cm.get_nozzle_center = lambda: None
    cm.get_nozzle_center_image_position = lambda: None
    cm.get_background_image = lambda: None

    missing = NozzleFocusCalibrationProcess.missing_requirements(cm)

    joined = " | ".join(missing).lower()
    assert "nozzle center" in joined
    assert "image position" in joined
    assert "background image" in joined


def test_nozzle_focus_missing_requirements_ready_case_is_empty():
    missing = NozzleFocusCalibrationProcess.missing_requirements(_ready_cm())
    assert missing == []


def test_start_nozzle_focus_uses_try_start_process():
    mgr = CalibrationManager.__new__(CalibrationManager)
    called = {"proc_cls": None}

    def _stub(proc_cls, *args, **kwargs):
        called["proc_cls"] = proc_cls
        return True

    mgr._try_start_process = _stub
    CalibrationManager.start_nozzle_focus_calibration(mgr)

    assert called["proc_cls"] is NozzleFocusCalibrationProcess


def _build_quality_proc(*, ratio: float, valid_evals: int, best_y: int, current_y: int):
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    proc.stageChanged = Recorder()
    proc.calibrationError = Recorder()
    proc.nozzleFocused = Recorder()
    proc.best_pos = {"Y": int(best_y)}
    proc.valid_focus_evals = int(valid_evals)
    proc.best_focus_stats = {"p90_ratio_to_background": float(ratio)}
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position_dict=lambda: {"Y": int(current_y)})
    )
    return proc


def test_focus_quality_gate_blocks_low_ratio_move_to_best():
    proc = _build_quality_proc(ratio=1.05, valid_evals=6, best_y=20, current_y=0)
    moves = {"count": 0}
    proc._request_move_relative_with_timeout = (
        lambda *args, **kwargs: moves.__setitem__("count", moves["count"] + 1)
    )

    proc._move_to_best_then_finish()

    assert moves["count"] == 0
    assert proc.calibrationError.calls
    assert "focus quality too low" in proc.calibrationError.calls[0][0][0].lower()


def test_focus_quality_gate_allows_good_ratio_move_to_best():
    proc = _build_quality_proc(ratio=1.45, valid_evals=6, best_y=20, current_y=5)
    captured = {"move": None}

    def _req(move, **kwargs):
        captured["move"] = move

    proc._request_move_relative_with_timeout = _req

    proc._move_to_best_then_finish()

    assert captured["move"] == (0, 15, 0)
    assert proc.calibrationError.calls == []


def test_initialize_focus_bounds_clamps_to_axis_limits():
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_axis_bounds=lambda axis: (100, 200))
    )
    proc.SAFE_SWEEP_STEPS = 500

    proc._initialize_focus_bounds(150)

    assert proc._loY == 100
    assert proc._hiY == 200
