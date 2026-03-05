import inspect
from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import CalibrationManager, PressureSweepCharacterizationProcess  # noqa: E402


def test_manager_trajectory_helpers_prefer_explicit_fields():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._pressure_traj_result = {
        "trajectory_pressure_band": [1.30, 1.10],
        "valid_fit_pressures": [1.20, 1.10, 1.30, 1.20],
    }

    assert CalibrationManager.get_trajectory_valid_fit_pressures(mgr) == [1.1, 1.2, 1.3]
    assert CalibrationManager.get_trajectory_pressure_band(mgr) == (1.1, 1.3)


def test_manager_trajectory_helpers_fallback_from_legacy_records():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._pressure_traj_result = {
        "pressures": [
            {"pressure": 1.00, "fit": {"vx_px_per_us": 0.01, "vy_px_per_us": 0.02}},
            {"pressure": 0.95, "fit": None},
            {"pressure": 0.90, "fit": {"vx_px_per_us": 0.02, "vy_px_per_us": 0.03}, "disqualified": True},
            {"pressure": 1.10, "fit": {"vx_px_per_us": 0.02, "vy_px_per_us": 0.03}},
        ]
    }

    assert CalibrationManager.get_trajectory_valid_fit_pressures(mgr) == [1.0, 1.1]
    assert CalibrationManager.get_trajectory_pressure_band(mgr) == (1.0, 1.1)


def test_pressure_sweep_missing_requirements_requires_trajectory_band():
    cm = SimpleNamespace(
        get_nozzle_center=lambda: {"X": 0, "Y": 0, "Z": 0},
        get_real_nozzle_center_image_position=lambda: (100, 100),
        get_background_image=lambda: np.zeros((64, 64), dtype=np.uint8),
        get_emergence_time=lambda: 4500,
        get_pressure_trajectory_result=lambda: {"pressures": [{"pressure": 1.0, "fit": None}]},
        get_trajectory_pressure_band=lambda: None,
        get_trajectory_valid_fit_pressures=lambda: [],
    )
    missing = PressureSweepCharacterizationProcess.missing_requirements(cm)
    assert "Trajectory-derived pressure band" in missing

    cm_ok = SimpleNamespace(
        get_nozzle_center=lambda: {"X": 0, "Y": 0, "Z": 0},
        get_real_nozzle_center_image_position=lambda: (100, 100),
        get_background_image=lambda: np.zeros((64, 64), dtype=np.uint8),
        get_emergence_time=lambda: 4500,
        get_pressure_trajectory_result=lambda: {
            "pressures": [{"pressure": 1.0, "fit": {"vx_px_per_us": 0.01, "vy_px_per_us": 0.02}}]
        },
        get_trajectory_pressure_band=lambda: (1.0, 1.0),
        get_trajectory_valid_fit_pressures=lambda: [1.0],
    )
    assert PressureSweepCharacterizationProcess.missing_requirements(cm_ok) == []


def test_pressure_sweep_resolve_planning_band_prefers_trajectory_band():
    band = PressureSweepCharacterizationProcess._resolve_trajectory_planning_band(
        (1.25, 1.15),
        [0.9, 1.0],
    )
    assert band == (1.15, 1.25)

    fallback = PressureSweepCharacterizationProcess._resolve_trajectory_planning_band(
        None,
        [1.05, 0.95, 1.00],
    )
    assert fallback == (0.95, 1.05)


def test_pressure_sweep_analyze_batch_requires_full_target_replicates():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.num_images = 20
    proc.circularity_threshold = 1.18
    proc.droplet_volumes = [1.0] * 20
    proc.circularity_values = [1.0] * 19 + [1.5]
    proc.stageChanged = Recorder()
    recorded = []
    proc._record_pressure_result = lambda valid, reason=None: recorded.append((bool(valid), str(reason)))
    proc.i = 0
    proc._reset_char_buffers = lambda: None
    proc.nextPressure = Recorder()

    proc.onAnalyzeBatch()

    assert recorded
    assert recorded[-1] == (False, "insufficient_good_replicates")
    assert proc.nextPressure.calls


def test_pressure_sweep_analyze_batch_marks_valid_with_20_good():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.num_images = 20
    proc.circularity_threshold = 1.18
    proc.droplet_volumes = [1.0 + (i * 0.01) for i in range(20)]
    proc.circularity_values = [1.0] * 20
    proc.droplet_positions = [(120, 230)] * 20
    proc.cur_pressure = 1.20
    proc.current_delay_us = 7000
    proc.multiple_droplet_hits = 0
    proc._y_focus_offset_steps = 0
    proc.samples = []
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 1, "Y": 2, "Z": 3}),
        droplet_camera_model=SimpleNamespace(
            convert_pixel_position_to_motor_steps=lambda _center, pos: dict(pos)
        ),
    )
    proc._annotate_char_summary_image = lambda *_args, **_kwargs: np.zeros((32, 32, 3), dtype=np.uint8)
    emitted = []
    proc._emit_incremental_pressure_step = lambda rec: emitted.append(dict(rec))
    proc.i = 0
    proc._reset_char_buffers = lambda: None
    proc.nextPressure = Recorder()

    proc.onAnalyzeBatch()

    assert proc.samples
    assert proc.samples[-1]["valid"] is True
    assert proc.samples[-1]["accepted_replicates"] == 20
    assert emitted
    assert proc.nextPressure.calls


def test_pressure_sweep_defaults_disable_early_stop_and_keep_20_replicates():
    sig = inspect.signature(PressureSweepCharacterizationProcess.__init__)
    assert sig.parameters["replicates_per_pressure"].default == 20
    assert sig.parameters["enable_early_stop"].default is False


def test_pressure_sweep_capture_redirects_to_background_when_stale():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc._background_stale = True
    proc.stageChanged = Recorder()
    proc.backgroundRefreshNeeded = Recorder()
    called = {"capture": False}
    proc._capture_with_policy = lambda **kwargs: called.__setitem__("capture", True)

    proc.onCaptureDroplet()

    assert proc.backgroundRefreshNeeded.calls
    assert called["capture"] is False


def test_pressure_sweep_mark_background_stale_resets_contour_tracker():
    reset_calls = {"n": 0}
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            reset_droplet_contour_tracker=lambda: reset_calls.__setitem__("n", reset_calls["n"] + 1)
        )
    )
    proc._record_event = lambda *args, **kwargs: None
    proc._background_stale = False

    proc._mark_background_stale("unit_test")

    assert proc._background_stale is True
    assert reset_calls["n"] == 1


def test_pressure_sweep_safe_move_abs_clamps_to_imaging_envelope():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.x_lo, proc.x_hi = 0, 50000
    proc.y_lo, proc.y_hi = 0, 50000
    proc.z_lo, proc.z_hi = 0, 200000
    proc._search_anchor_xyz = (1000, 2000, 3000)
    proc.max_anchor_dx_steps = 200
    proc.max_anchor_dz_steps = 400
    proc.imaging_guard_hit_cap = 5
    proc._imaging_guard_hit_count = 0
    proc.stageChanged = Recorder()
    proc._record_event = lambda *args, **kwargs: None
    proc._record_pressure_result = lambda *args, **kwargs: None
    proc.nextPressure = Recorder()
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 1000, "Y": 2000, "Z": 3000})
    )
    proc.moveDone = Recorder()
    captured = {"target": None}

    def _req(target, *, on_done=None, **_kwargs):
        captured["target"] = tuple(target)
        if callable(on_done):
            on_done()

    proc._request_move_absolute_with_timeout = _req

    proc._safe_move_abs((4000, 2000, 12000))

    assert captured["target"] == (1200, 2000, 3400)
    assert proc.moveDone.calls


def test_pressure_sweep_safe_move_abs_guard_cap_skips_pressure():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.x_lo, proc.x_hi = 0, 50000
    proc.y_lo, proc.y_hi = 0, 50000
    proc.z_lo, proc.z_hi = 0, 200000
    proc._search_anchor_xyz = (1000, 2000, 3000)
    proc.max_anchor_dx_steps = 50
    proc.max_anchor_dz_steps = 100
    proc.imaging_guard_hit_cap = 1
    proc._imaging_guard_hit_count = 0
    proc.stageChanged = Recorder()
    proc._record_event = lambda *args, **kwargs: None
    recorded = []
    proc._record_pressure_result = lambda valid, reason=None: recorded.append((valid, reason))
    proc.nextPressure = Recorder()
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 1000, "Y": 2000, "Z": 3000})
    )
    proc.moveDone = Recorder()
    proc.i = 0
    proc._bad_reason = None
    proc._request_move_absolute_with_timeout = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("should not issue move when imaging guard cap is exceeded")
    )

    proc._safe_move_abs((9000, 2000, 9000))

    assert recorded
    assert recorded[-1] == (False, "imaging_guard_limit")
    assert proc.nextPressure.calls
