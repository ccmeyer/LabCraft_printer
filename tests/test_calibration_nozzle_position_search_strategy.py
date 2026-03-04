from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import NozzlePositionCalibrationProcess


def _build_process_for_analyze():
    proc = NozzlePositionCalibrationProcess.__new__(NozzlePositionCalibrationProcess)
    proc.stageChanged = Recorder()
    proc.calibrationError = Recorder()
    proc.presentImageSignal = Recorder()
    proc.nozzleCentered = Recorder()

    anchor = {"X": 10_000, "Y": 2_000, "Z": 3_000}
    pos = dict(anchor)
    settings_calls = []
    move_calls = []
    recenter_calls = []

    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            compute_move_by_fraction=lambda x_frac, y_frac: (1000 * float(x_frac), 0, 0),
            get_image_size=lambda: (1000, 1000),
            calculate_move_to_target=lambda nozzle_px, target_px: (0, 0, 0),
        ),
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: dict(pos),
            get_axis_bounds=lambda axis: (0, 20_000),
            get_current_print_pressure=lambda: 1.0,
        ),
        location_model=SimpleNamespace(
            get_boundaries=lambda: {
                "min": {"X": 0, "Y": 0, "Z": 0},
                "max": {"X": 20_000, "Y": 20_000, "Z": 20_000},
            }
        ),
    )
    proc.calibration_manager = SimpleNamespace(
        emitSettingsChangeCompleted=lambda *args, **kwargs: None,
        set_background_image=lambda *_: None,
        set_nozzle_center_image_position=lambda *_: None,
        set_nozzle_center=lambda *_: None,
    )

    proc._request_settings_with_recording = (
        lambda settings, callback, **kwargs: settings_calls.append(dict(settings))
    )
    proc._request_move_absolute_with_timeout = (
        lambda target, **kwargs: move_calls.append(tuple(target))
    )
    proc._recenter_or_finish = lambda nozzle_px: recenter_calls.append(tuple(nozzle_px)) or "recenter_move"
    proc._record_analysis = lambda payload: None
    proc._record_decision = lambda decision, payload=None: None
    proc._record_event = lambda *args, **kwargs: None

    proc.background_image = object()
    proc.droplet_image = object()
    proc._throwaway_pending = False
    proc._last_capture_refs = {
        "background_image": {},
        "droplet_image": {},
    }

    proc.initial_flash_delay_us = 2600
    proc._current_flash_delay_us = 2600
    proc.multi_contour_delay_step_us = 200
    proc.min_flash_delay_us = 2000
    proc.max_flash_delay_us = 12_000
    proc.nozzle_search_half_fov_fraction = 0.5
    proc.nozzle_search_min_half_fov_x_steps = 200
    proc._x_scan_anchor = dict(anchor)
    proc._x_scan_half_fov_x_steps = 500
    proc._x_scan_attempt_index = 0
    proc._x_scan_active = False
    proc._base_pressure = 1.0
    proc._recenter_iters = 0
    proc.move_timeout_ms = 15_000
    proc.max_xy_steps_per_correction = 1000
    proc._default_axis_spans = {"X": 20_000, "Y": 10_000, "Z": 20_000}
    proc.top_margin_frac = 0.12
    proc.center_tol_frac = 0.03
    proc.top_band_frac = 0.03
    proc.measurements = []

    return proc, pos, settings_calls, move_calls, recenter_calls


def test_nozzle_missing_contour_scans_right_then_left_from_anchor_then_aborts():
    proc, pos, settings_calls, move_calls, _ = _build_process_for_analyze()
    proc._detect_nozzle_point = lambda bg, dr: ("NONE", None, 0, None)

    proc.onAnalyze()
    assert move_calls == [(9500, 2000, 3000)]
    assert settings_calls == []

    pos.update({"X": 9500, "Y": 2000, "Z": 3000})
    proc.onAnalyze()
    assert move_calls == [(9500, 2000, 3000), (10500, 2000, 3000)]
    assert settings_calls == []

    pos.update({"X": 10500, "Y": 2000, "Z": 3000})
    proc.onAnalyze()
    assert len(move_calls) == 2
    assert proc.calibrationError.calls
    assert "x-axis scan" in proc.calibrationError.calls[0][0][0].lower()


def test_nozzle_x_scan_anchor_is_preserved_across_prepare_cycle():
    proc, pos, settings_calls, move_calls, _ = _build_process_for_analyze()
    proc._detect_nozzle_point = lambda bg, dr: ("NONE", None, 0, None)

    proc.onAnalyze()
    assert move_calls == [(9500, 2000, 3000)]
    assert proc._x_scan_active is True

    pos.update({"X": 9500, "Y": 2000, "Z": 3000})
    proc.onPrepareDroplet()
    assert settings_calls and settings_calls[-1]["flash_delay"] == 2600
    proc._throwaway_pending = False

    proc.onAnalyze()
    assert move_calls == [(9500, 2000, 3000), (10500, 2000, 3000)]


def test_nozzle_no_signal_uses_x_scan_not_pressure_bump():
    proc, _pos, settings_calls, move_calls, _ = _build_process_for_analyze()
    proc._detect_nozzle_point = lambda bg, dr: ("NO_SIGNAL", None, 0, None)

    proc.onAnalyze()

    assert move_calls == [(9500, 2000, 3000)]
    assert settings_calls == []
    assert proc.calibrationError.calls == []


def test_multiple_contours_decreases_flash_delay_by_200():
    proc, _pos, settings_calls, move_calls, recenter_calls = _build_process_for_analyze()
    dbg = np.zeros((16, 16, 3), dtype=np.uint8)
    proc._detect_nozzle_point = lambda bg, dr: ("OK", (300, 120), 2, dbg)
    proc._current_flash_delay_us = 2600

    proc.onAnalyze()

    assert settings_calls and settings_calls[0]["flash_delay"] == 2400
    assert settings_calls[0]["num_droplets"] == 1
    assert move_calls == []
    assert recenter_calls == []
    assert proc.calibrationError.calls == []


def test_multiple_contours_delay_floor_clamps_at_2000():
    proc, _pos, settings_calls, _move_calls, _recenter_calls = _build_process_for_analyze()
    dbg = np.zeros((16, 16, 3), dtype=np.uint8)
    proc._detect_nozzle_point = lambda bg, dr: ("OK", (300, 120), 2, dbg)
    proc._current_flash_delay_us = 2100

    proc.onAnalyze()

    assert settings_calls and settings_calls[0]["flash_delay"] == 2000
    assert proc.calibrationError.calls == []


def test_multiple_contours_at_min_delay_aborts():
    proc, _pos, settings_calls, move_calls, recenter_calls = _build_process_for_analyze()
    dbg = np.zeros((16, 16, 3), dtype=np.uint8)
    proc._detect_nozzle_point = lambda bg, dr: ("OK", (300, 120), 3, dbg)
    proc._current_flash_delay_us = 2000

    proc.onAnalyze()

    assert settings_calls == []
    assert move_calls == []
    assert recenter_calls == []
    assert proc.calibrationError.calls
    assert "minimum flash delay" in proc.calibrationError.calls[0][0][0].lower()


def test_single_contour_still_uses_recenter_path():
    proc, _pos, settings_calls, move_calls, recenter_calls = _build_process_for_analyze()
    dbg = np.zeros((16, 16, 3), dtype=np.uint8)
    proc._detect_nozzle_point = lambda bg, dr: ("OK", (300, 120), 1, dbg)

    proc.onAnalyze()

    assert recenter_calls == [(300, 120)]
    assert settings_calls == []
    assert move_calls == []
    assert proc.calibrationError.calls == []
