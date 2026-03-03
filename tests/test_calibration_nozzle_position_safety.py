from types import SimpleNamespace

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import NozzlePositionCalibrationProcess


def _build_process_for_recenter():
    proc = NozzlePositionCalibrationProcess.__new__(NozzlePositionCalibrationProcess)
    proc.stageChanged = Recorder()
    proc.calibrationError = Recorder()
    proc.nozzleCentered = Recorder()
    proc.calibration_manager = SimpleNamespace(
        set_background_image=lambda *_: None,
        set_nozzle_center_image_position=lambda *_: None,
        set_nozzle_center=lambda *_: None,
    )
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            get_image_size=lambda: (1000, 1000),
            calculate_move_to_target=lambda nozzle_px, target_px: (5000, 5000, 0),
        ),
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: {"X": 500, "Y": 500, "Z": 500},
            get_axis_bounds=lambda axis: (0, 1000),
        ),
    )
    proc.top_margin_frac = 0.12
    proc.center_tol_frac = 0.03
    proc.top_band_frac = 0.03
    proc.max_xy_steps_per_correction = 1000
    proc.max_recenter_iterations = 8
    proc._recenter_iters = 0
    proc.move_timeout_ms = 15000
    proc.background_image = object()
    proc.measurements = []
    return proc


def test_nozzle_recenter_clamps_target_within_axis_bounds():
    proc = _build_process_for_recenter()
    moved = {"target": None}
    proc._request_move_absolute_with_timeout = (
        lambda target, **kwargs: moved.__setitem__("target", target)
    )

    proc._recenter_or_finish((100, 900))

    assert moved["target"] == (1000, 1000, 500)
    assert proc._recenter_iters == 1
    assert proc.calibrationError.calls == []


def test_nozzle_recenter_stops_before_move_when_iteration_cap_reached():
    proc = _build_process_for_recenter()
    proc._recenter_iters = proc.max_recenter_iterations
    moved = {"count": 0}
    proc._request_move_absolute_with_timeout = (
        lambda *args, **kwargs: moved.__setitem__("count", moved["count"] + 1)
    )

    proc._recenter_or_finish((100, 900))

    assert moved["count"] == 0
    assert proc.calibrationError.calls
    assert "too many recenter attempts" in proc.calibrationError.calls[0][0][0].lower()
