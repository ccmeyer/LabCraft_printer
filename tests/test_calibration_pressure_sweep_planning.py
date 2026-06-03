import inspect
import time
from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import Recorder, SignalStub, contour_from_rect, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from PySide6.QtCore import QObject, Signal  # noqa: E402
from CalibrationClasses.Model import CalibrationManager, PressureSweepCharacterizationProcess  # noqa: E402


def _build_pressure_sweep_focus_proc(focus_values, *, roundness_values=None):
    overlay = np.zeros((400, 400, 3), dtype=np.uint8)
    state = {"pos": {"X": 500, "Y": 1000, "Z": 700}}
    values = list(focus_values)
    roundness = list(roundness_values if roundness_values is not None else [0.95] * len(values))

    def _characterize(_img, _bg):
        if not values:
            raise AssertionError("No more focus values queued")
        if not roundness:
            raise AssertionError("No more roundness values queued")
        ellipse_roundness = float(roundness.pop(0))
        return (
            {
                "center": (200, 200),
                "focus": float(values.pop(0)),
                "circularity_ellipse": float(ellipse_roundness),
                "ellipse_roundness": float(ellipse_roundness),
                "volume": 1.0,
            },
            overlay.copy(),
        )

    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.droplet_image = overlay.copy()
    proc.background_image = overlay.copy()
    proc.nozzle_center_machine = {"X": 500, "Y": 1000, "Z": 700}
    proc.focus_ok_threshold = 5_000_000
    proc.focus_dir = +1
    proc.focus_step = 16
    proc.focus_min_step = 8
    proc.focus_dir_switches = 0
    proc.focus_switch_limit = 6
    proc._focus_best = 0.0
    proc._focus_same_dir_tries = 0
    proc._focus_moves_done = 0
    proc._focus_move_budget = 60
    proc._min_focus_gain = 0.02
    proc._focus_best_y_offset_steps = None
    proc._focus_best_source = ""
    proc._y_focus_offset_steps = 0
    proc._y_focus_ema_alpha = 0.35
    proc._centered = True
    proc._char_need_capture = False
    proc.center_first_tol_px = 140
    proc.boundary_tol_px = 250
    proc._center_last_center = (200, 200)
    proc._center_stable_hits = 3
    proc._center_jump_reject_streak = 0
    proc.center_jump_reject_px = 320.0
    proc.center_stable_hits_for_bias_update = 3
    proc._xz_offset_updated_this_pressure = True
    proc._oob_total = 0
    proc.max_oob_total = 12
    proc._recenter_moves = 0
    proc.max_recenter_moves = 10
    proc.circularity_threshold = 0.95
    proc.circularity_values = []
    proc.droplet_positions = []
    proc.droplet_focus = []
    proc.droplet_volumes = []
    proc.image_counter = 0
    proc.num_images = 20
    proc.repl_target = 20
    proc.multiple_droplet_hits = 0
    proc._char_stream_hits = 0
    proc._char_invalid_hits = 0
    proc._char_frames_evaluated = 0
    proc._char_attempts = 0
    proc._char_attempt_limit = 60
    proc.char_max_invalid_ratio = 0.45
    proc.char_max_multiple_ratio = 0.20
    proc.char_max_stream_ratio = 0.20
    proc.char_stream_circularity_max = 0.58
    proc.char_delay_retarget_roundness_min = 0.95
    proc.char_delay_retarget_bad_hits_required = 3
    proc.char_delay_retarget_window_frames = 4
    proc.char_delay_retarget_steps_us = [1000, 2000]
    proc.char_delay_retarget_cap = 2
    proc._morphology_window_evaluable_count = 0
    proc._morphology_window_nonround_hits = 0
    proc._morphology_nonround_hits_total = 0
    proc._morphology_retarget_count = 0
    proc._morphology_retarget_history_us = []
    proc.current_delay_us = 7000
    proc.target_delay_us = 7000
    proc.min_delay_us = 0
    proc.max_delay_us = 50000
    proc.targeting_mode = "fixed_z_plane"
    proc.imaging_z_offset_steps = -2500
    proc.target_z_steps = -1800
    proc.current_plan_record = None
    proc.nominal_target_xyz = None
    proc.nominal_target_delay_us = None
    proc.cur_pressure = 1.2
    proc.measurements = []
    proc.enable_early_stop = False
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.continueCap = Recorder()
    proc.analyzeBatch = Recorder()
    proc.nextPressure = Recorder()
    proc._record_pressure_sweep_analysis = lambda *args, **kwargs: None
    proc._record_decision = lambda *args, **kwargs: None
    proc._emit_incremental_pressure_step = lambda *_args, **_kwargs: None
    proc._update_xz_track_offset = lambda: None
    proc._check_boundary_and_maybe_recenter = lambda _center_px: False
    proc._should_early_stop_batch = lambda: False
    proc._annotate_char_summary_image = lambda *_args, **_kwargs: overlay.copy()
    proc._search_anchor_xyz = (500, 1000, 700)
    proc._background_stale = False
    proc._mark_background_stale = lambda *_args, **_kwargs: setattr(proc, "_background_stale", True)
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: dict(state["pos"])
        ),
        droplet_camera_model=SimpleNamespace(
            characterize_droplet=_characterize,
            convert_pixel_position_to_motor_steps=lambda _center, pos: dict(pos),
        ),
    )

    moves = []

    def _safe_move_abs(xyz):
        xyz = tuple(map(int, xyz))
        moves.append(xyz)
        state["pos"] = {"X": xyz[0], "Y": xyz[1], "Z": xyz[2]}

    proc._safe_move_abs = _safe_move_abs
    return proc, state, moves


class _PressureSweepInitManager(QObject):
    settingsChangeCompleted = Signal()
    captureCompleted = Signal()

    def __init__(self):
        super().__init__()
        self._background = np.zeros((64, 64), dtype=np.uint8)
        self._traj = {
            "pressures": [
                {
                    "pressure": 1.20,
                    "fit": {"vx_px_per_us": 0.02, "vy_px_per_us": 0.10},
                }
            ]
        }

    def get_num_pressure_tests(self):
        return 1

    def get_nozzle_center(self):
        return {"X": 1000, "Y": 2000, "Z": 9000}

    def get_pressure_scan_nozzle_center_image_position(self):
        return (100, 100)

    def get_real_nozzle_center_image_position(self):
        return (100, 100)

    def get_emergence_time(self):
        return 4000

    def get_background_image(self):
        return self._background.copy()

    def get_trajectory_pressure_band(self):
        return (1.20, 1.20)

    def get_trajectory_valid_fit_pressures(self):
        return [1.20]

    def get_pressure_trajectory_result(self):
        return dict(self._traj)

    def emitSettingsChangeCompleted(self):
        self.settingsChangeCompleted.emit()


def _build_pressure_sweep_init_model():
    def _convert_pixel_position_to_motor_steps(pixel_position, current_motor_position):
        px, py = pixel_position
        return {
            "X": int(current_motor_position["X"] + (px - 100)),
            "Y": int(current_motor_position["Y"]),
            "Z": int(current_motor_position["Z"] + (py - 100)),
        }

    return SimpleNamespace(
        machine_model=SimpleNamespace(
            get_axis_bounds=lambda axis: {
                "X": (0, 30000),
                "Y": (0, 30000),
                "Z": (0, 30000),
            }[axis],
            get_current_position_dict=lambda: {"X": 1000, "Y": 2000, "Z": 9000},
        ),
        droplet_camera_model=SimpleNamespace(
            convert_pixel_position_to_motor_steps=_convert_pixel_position_to_motor_steps
        ),
    )


def test_pressure_sweep_safe_bounds_prefer_camera_location_before_nozzle_center():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.nozzle_center_machine = {"X": 100, "Y": 200, "Z": 300}
    proc.stageChanged = Recorder()
    proc._record_event = lambda *args, **kwargs: None
    proc.model = SimpleNamespace(
        location_model=SimpleNamespace(
            get_location_dict=lambda name: {"X": 5000, "Y": 6000, "Z": 7000} if name == "camera" else None
        ),
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: {"X": 9000, "Y": 10000, "Z": 11000}
        ),
    )

    assert proc._get_axis_bounds_safe("X", 20_000) == (-15_000, 25_000)
    assert proc._get_axis_bounds_safe("Y", 10_000) == (-4_000, 16_000)
    assert proc._get_axis_bounds_safe("Z", 20_000) == (-13_000, 27_000)


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
    proc.circularity_threshold = 0.95
    proc.droplet_volumes = [1.0] * 20
    proc.circularity_values = [0.95] * 19 + [0.85]
    proc.stageChanged = Recorder()
    recorded = []
    proc._record_pressure_result = (
        lambda valid, reason=None, **_kwargs: recorded.append((bool(valid), str(reason)))
    )
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
    proc.circularity_threshold = 0.95
    proc.droplet_volumes = [1.0 + (i * 0.01) for i in range(20)]
    proc.circularity_values = [0.95] * 20
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


def test_pressure_sweep_analyze_batch_final_phase_accepts_point92_circularity():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.num_images = 20
    proc.circularity_threshold = 0.95
    proc.char_delay_retarget_cap = 2
    proc._morphology_retarget_count = 2
    proc.droplet_volumes = [1.0 + (i * 0.01) for i in range(20)]
    proc.circularity_values = [0.92] * 20
    proc.droplet_positions = [(120, 230)] * 20
    proc.cur_pressure = 1.20
    proc.current_delay_us = 9500
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
    proc._record_analysis = lambda *_args, **_kwargs: None
    proc._record_decision = lambda *_args, **_kwargs: None
    proc.i = 0
    proc._reset_char_buffers = lambda: None
    proc.nextPressure = Recorder()

    proc.onAnalyzeBatch()

    assert proc.samples
    assert proc.samples[-1]["valid"] is True
    assert proc.samples[-1]["accepted_replicates"] == 20
    assert proc.samples[-1]["circularity_threshold_active"] == 0.90
    assert proc.samples[-1]["circularity_threshold_final_phase_active"] is True
    assert emitted
    assert proc.nextPressure.calls


def test_pressure_sweep_defaults_disable_early_stop_and_keep_20_replicates():
    sig = inspect.signature(PressureSweepCharacterizationProcess.__init__)
    assert sig.parameters["replicates_per_pressure"].default == 20
    assert sig.parameters["imaging_z_offset_steps"].default == -3500
    assert sig.parameters["max_nominal_delay_us"].default == 15000
    assert sig.parameters["min_nozzle_clearance_z_steps"].default == 1000
    assert sig.parameters["enable_early_stop"].default is False
    assert sig.parameters["char_delay_retarget_roundness_min"].default == 0.95
    assert sig.parameters["char_delay_retarget_bad_hits_required"].default == 3
    assert sig.parameters["char_delay_retarget_window_frames"].default == 4
    assert sig.parameters["char_delay_retarget_steps_us"].default == (1000, 2000)
    assert sig.parameters["char_delay_retarget_cap"].default == 2
    assert sig.parameters["manual_current_context"].default is None


def test_pressure_sweep_constructor_initializes_bounds_before_nominal_target_planning():
    mgr = _PressureSweepInitManager()
    model = _build_pressure_sweep_init_model()

    proc = PressureSweepCharacterizationProcess(
        mgr,
        model,
        imaging_z_offset_steps=-1000,
        max_nominal_delay_us=15000,
    )

    assert (proc.x_lo, proc.x_hi) == (0, 30000)
    assert (proc.y_lo, proc.y_hi) == (0, 30000)
    assert (proc.z_lo, proc.z_hi) == (0, 30000)
    assert proc.plan
    assert len(proc.plan) == 1
    assert proc.plan[0]["pressure"] == 1.2
    assert proc.plan[0]["target_plane_reachable"] is True
    assert proc.plan[0]["nominal_delay_us"] == 14000
    assert proc.plan[0]["nominal_target_xyz"] == [1200, 2000, 8000]


def _build_recheck_context():
    return {
        "print_pulse_width_us": 1450,
        "pressure_psi": 1.20,
        "delay_us": 9000,
        "target_xyz": [1234, 2000, 7654],
        "nozzle_center_machine": {"X": 1000, "Y": 2000, "Z": 9000},
        "nozzle_center_px": [100, 100],
        "emergence_time_us": 4000,
        "vec_steps_per_s": [20_000.0, 0.0, -100_000.0],
        "reference_mean_volume_nL": 9.5,
        "reference_cv_volume_percent": 3.2,
        "source_result": {
            "run_id": "run_a",
            "phase_key": "pressure_sweep_characterization",
            "step_index": 0,
            "pressure_index": 0,
        },
    }


def test_pressure_sweep_recheck_mode_builds_single_plan_and_uses_prior_target():
    mgr = _PressureSweepInitManager()
    model = _build_pressure_sweep_init_model()
    context = _build_recheck_context()

    proc = PressureSweepCharacterizationProcess(
        mgr,
        model,
        recheck_context=context,
        replicates_per_pressure=20,
    )

    assert proc.phase_name == "droplet_recheck"
    assert proc.recheck_mode is True
    assert len(proc.plan) == 1
    assert proc.plan[0]["pressure"] == 1.2
    assert proc.plan[0]["print_pulse_width_us"] == 1450

    proc.onPickPressure()

    assert proc.target_delay_us == 9000
    assert proc.nominal_target_xyz == (1100, 2000, 8500)
    assert proc._target_xyz_for_delay(9000, include_offsets=False) == (1100, 2000, 8500)
    assert proc._target_xyz_for_delay(9000, include_offsets=True) == (1234, 2000, 7654)

    offset_xyz = proc._target_xyz_for_delay(9500, include_offsets=False)
    assert offset_xyz != (1234, 2000, 7654)
    assert offset_xyz[0] > 1000


def test_pressure_sweep_recheck_offset_delays_follow_prior_target_bias():
    mgr = _PressureSweepInitManager()
    model = _build_pressure_sweep_init_model()
    context = _build_recheck_context()
    proc = PressureSweepCharacterizationProcess(
        mgr,
        model,
        recheck_context=context,
        replicates_per_pressure=20,
    )

    proc.onPickPressure()

    raw_nominal = proc._target_xyz_for_delay(9000, include_offsets=False)
    raw_later = proc._target_xyz_for_delay(9500, include_offsets=False)
    biased_nominal = proc._target_xyz_for_delay(9000, include_offsets=True)
    biased_later = proc._target_xyz_for_delay(9500, include_offsets=True)

    assert raw_nominal == (1100, 2000, 8500)
    assert biased_nominal == (1234, 2000, 7654)
    assert (
        biased_later[0] - biased_nominal[0],
        biased_later[1] - biased_nominal[1],
        biased_later[2] - biased_nominal[2],
    ) == (
        raw_later[0] - raw_nominal[0],
        raw_later[1] - raw_nominal[1],
        raw_later[2] - raw_nominal[2],
    )
    assert biased_later == (1244, 2000, 7604)


def test_pressure_sweep_recheck_mode_applies_pulse_width_and_pressure():
    mgr = _PressureSweepInitManager()
    model = _build_pressure_sweep_init_model()
    proc = PressureSweepCharacterizationProcess(
        mgr,
        model,
        recheck_context=_build_recheck_context(),
        replicates_per_pressure=20,
    )
    proc.onPickPressure()
    requests = []
    proc._request_settings_with_timeout = lambda settings, **_kwargs: requests.append(dict(settings))

    proc.onApplyPressure()

    assert requests
    assert requests[0]["print_pulse_width"] == 1450
    assert requests[0]["print_pressure"] == 1.2
    assert requests[0]["num_droplets"] == 0


def _build_manual_current_context():
    context = _build_recheck_context()
    context.update(
        {
            "manual_current": True,
            "target_xyz": [1234, 2000, 7654],
            "mean_position_machine": [1234, 2000, 7654],
            "source_result": {
                "phase": "search",
                "phase_key": "droplet_search",
                "phase_source": "manual_current",
                "pressure_psi": 1.20,
                "pw_us": 1450,
                "delay_us": 9000,
                "target_xyz": [1234, 2000, 7654],
            },
        }
    )
    return context


def test_pressure_sweep_manual_current_mode_builds_single_plan_from_current_target():
    mgr = _PressureSweepInitManager()
    model = _build_pressure_sweep_init_model()
    context = _build_manual_current_context()

    proc = PressureSweepCharacterizationProcess(
        mgr,
        model,
        manual_current_context=context,
        replicates_per_pressure=20,
    )

    assert proc.phase_name == "droplet_search"
    assert proc.manual_current_mode is True
    assert proc.recheck_mode is False
    assert len(proc.plan) == 1
    assert proc.plan[0]["pressure"] == 1.2
    assert proc.plan[0]["print_pulse_width_us"] == 1450
    assert proc.plan[0]["manual_current"] is True

    proc.onPickPressure()

    assert proc.target_delay_us == 9000
    assert proc.nominal_target_xyz == (1100, 2000, 8500)
    assert proc._target_xyz_for_delay(9000, include_offsets=False) == (1100, 2000, 8500)
    assert proc._target_xyz_for_delay(9000, include_offsets=True) == (1234, 2000, 7654)

    pressure_entry = proc._attach_manual_current_metadata(
        {"pressure": 1.2, "delay_us": 9000, "mean_volume": 9.8, "cv_volume_percent": 4.2, "valid": True}
    )
    assert pressure_entry["print_pulse_width_us"] == 1450
    assert pressure_entry["nozzle_center_px"] == [100, 100]
    assert pressure_entry["nozzle_center_machine"] == {"X": 1000, "Y": 2000, "Z": 9000}
    assert pressure_entry["emergence_time_us"] == 4000
    assert pressure_entry["manual_current"] is True


def test_manual_droplet_characterization_starts_pressure_sweep_with_current_position(tmp_path):
    model = SimpleNamespace(
        machine_state_updated=SignalStub(),
        experiment_model=SimpleNamespace(get_calibration_file_path=lambda: str(tmp_path / "calibration.json")),
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: None),
        droplet_camera_model=SimpleNamespace(
            get_image_metadata=lambda: (1, 1000, 4300, 1, 30000),
        ),
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: {"X": 2222, "Y": 3333, "Z": 4444},
            get_print_pulse_width=lambda: 1450,
            get_refuel_pulse_width=lambda: 0,
            get_current_print_pressure=lambda: 1.2,
            get_current_refuel_pressure=lambda: 0.0,
        ),
        calibration_memory_store=None,
    )
    manager = CalibrationManager(model)
    manager.nozzle_center = {"X": 1000, "Y": 2000, "Z": 9000}
    manager.real_nozzle_center_image_position = [100, 100]
    manager.get_emergence_time = lambda: 4000
    manager._pressure_traj_result = {
        "pressures": [
            {"pressure": 1.2, "fit": {"vx_px_per_us": 0.02, "vy_px_per_us": 0.10}},
        ],
        "valid_fit_pressures": [1.2],
    }
    started = {}
    manager._try_start_process = lambda proc_cls, **kwargs: started.update(
        {"proc_cls": proc_cls, "kwargs": dict(kwargs)}
    ) or True

    assert manager.start_manual_droplet_characterization() is True

    assert started["proc_cls"] is PressureSweepCharacterizationProcess
    context = started["kwargs"]["manual_current_context"]
    assert context["target_xyz"] == [2222, 3333, 4444]
    assert context["pressure_psi"] == 1.2
    assert context["print_pulse_width_us"] == 1450
    assert context["delay_us"] == 4300
    assert context["vx_px_per_us"] == 0.02
    assert context["vy_px_per_us"] == 0.10


def test_manual_current_no_droplet_finishes_without_pressure_row():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.manual_current_mode = True
    proc._search_candidate_seen_ever = False
    proc.plan = [{"pressure": 1.2}]
    proc.i = 0
    proc.cur_pressure = 1.2
    proc.current_delay_us = None
    proc.target_delay_us = 4300
    proc.stageChanged = Recorder()
    proc.nextPressure = Recorder()
    proc._search_streak_snapshot = lambda: {}
    proc._char_ratio_snapshot = lambda: {}
    proc._morphology_snapshot = lambda: {}
    proc._circularity_threshold_context = lambda: {}
    decisions = []
    analyses = []
    recorded_rows = []
    proc._record_decision = lambda kind, payload: decisions.append((kind, dict(payload)))
    proc._record_pressure_sweep_analysis = lambda kind, payload=None: analyses.append((kind, dict(payload or {})))
    proc._record_pressure_result = lambda *args, **kwargs: recorded_rows.append((args, kwargs))

    proc._invalidate_current_pressure("search_no_contour_streak_limit")

    assert recorded_rows == []
    assert proc.i == len(proc.plan)
    assert proc.nextPressure.calls
    assert any(kind == "manual_current_no_droplet" for kind, _payload in decisions)
    assert any(kind == "manual_current_no_droplet" for kind, _payload in analyses)


def test_pressure_sweep_solves_nominal_delay_from_fixed_z_plane():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.nozzle_center_machine = {"X": 100, "Y": 200, "Z": 9000}
    proc.emergence_time_us = 4000
    proc.min_delay_us = 0
    proc.max_delay_us = 50000
    proc.max_nominal_delay_us = 15000

    solved = proc._solve_delay_for_target_z_steps((0.0, 0.0, -500000.0), 6500)

    assert solved["ok"] is True
    assert solved["dt_us"] == 5000
    assert solved["target_delay_us"] == 9000


def test_pressure_sweep_solves_nominal_delay_rejects_over_limit():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.nozzle_center_machine = {"X": 100, "Y": 200, "Z": 9000}
    proc.emergence_time_us = 4000
    proc.min_delay_us = 0
    proc.max_delay_us = 50000
    proc.max_nominal_delay_us = 15000

    solved = proc._solve_delay_for_target_z_steps((0.0, 0.0, -100000.0), 5500)

    assert solved["ok"] is False
    assert solved["reason"] == "target_plane_delay_over_limit"
    assert solved["delay_us"] == 39000


def test_pressure_sweep_clamp_xyz_lazily_initializes_bounds():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.nozzle_center_machine = {"X": 1000, "Y": 2000, "Z": 3000}
    proc.model = _build_pressure_sweep_init_model()

    xyz = proc._clamp_xyz(-5, 200, 40000)

    assert xyz == (0, 200, 30000)
    assert (proc.x_lo, proc.x_hi) == (0, 30000)
    assert (proc.y_lo, proc.y_hi) == (0, 30000)
    assert (proc.z_lo, proc.z_hi) == (0, 30000)


def test_pressure_sweep_pick_pressure_skips_when_fixed_plane_unreachable():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc._ready = True
    proc.i = 0
    proc.plan = [
        {
            "pressure": 1.25,
            "vx": 0.02,
            "vy": 0.03,
            "vec_steps_per_s": [1500.0, 0.0, 0.0],
            "targeting_mode": "fixed_z_plane",
            "imaging_z_offset_steps": -2500,
            "target_z_steps": 6500,
            "target_plane_reachable": False,
            "target_plane_reason": "target_plane_vz_zero",
        }
    ]
    proc.stageChanged = Recorder()
    proc.pressureReady = Recorder()
    proc._reset_char_buffers = lambda: None
    proc._reset_contour_tracker = lambda: None
    proc._record_decision = lambda *args, **kwargs: None
    invalidated = []
    proc._invalidate_current_pressure = lambda reason, stage_message=None: invalidated.append(
        (str(reason), str(stage_message))
    )

    proc.onPickPressure()

    assert invalidated
    assert invalidated[-1][0] == "target_plane_vz_zero"
    assert not proc.pressureReady.calls


def test_pressure_sweep_pick_pressure_skips_when_nominal_delay_is_over_limit():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc._ready = True
    proc.i = 0
    proc.plan = [
        {
            "pressure": 1.25,
            "vx": 0.02,
            "vy": 0.03,
            "vec_steps_per_s": [1500.0, 0.0, -500.0],
            "targeting_mode": "fixed_z_plane",
            "imaging_z_offset_steps": -3500,
            "target_z_steps": 5500,
            "target_plane_reachable": False,
            "target_plane_reason": "target_plane_delay_over_limit",
        }
    ]
    proc.stageChanged = Recorder()
    proc.pressureReady = Recorder()
    proc._reset_char_buffers = lambda: None
    proc._reset_contour_tracker = lambda: None
    proc._record_decision = lambda *args, **kwargs: None
    invalidated = []
    proc._invalidate_current_pressure = lambda reason, stage_message=None: invalidated.append(
        (str(reason), str(stage_message))
    )

    proc.onPickPressure()

    assert invalidated
    assert invalidated[-1][0] == "target_plane_delay_over_limit"
    assert not proc.pressureReady.calls


def test_pressure_sweep_move_to_target_uses_stored_nominal_absolute_target():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.vec_steps_per_s = (999999.0, 0.0, -999999.0)
    proc.target_delay_us = 9100
    proc.nominal_target_delay_us = 9100
    proc.nominal_target_xyz = (5000, 6000, 7000)
    proc._x_track_offset_steps = 120
    proc._y_focus_offset_steps = -40
    proc._z_track_offset_steps = 75
    proc._clamp_xyz = lambda x, y, z: (int(x), int(y), int(z))
    proc._mark_background_stale = lambda *_args, **_kwargs: None
    proc.stageChanged = Recorder()
    moved = {}
    proc._safe_move_abs = lambda xyz: moved.__setitem__("target", tuple(map(int, xyz)))

    proc.onMoveToTarget()

    assert proc._search_anchor_xyz == (5120, 5960, 7075)
    assert moved["target"] == (5120, 5960, 7075)


def test_pressure_sweep_set_delay_applies_forced_nozzle_clearance_delay_first():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.search_max_elapsed_s = 90.0
    proc._search_started_at_monotonic = time.monotonic()
    proc._forced_delay_us = 14500
    proc.max_nominal_delay_us = 15000
    proc.min_delay_us = 0
    proc.max_delay_us = 50000
    proc.target_delay_us = 7000
    proc.current_delay_us = 7000
    proc._delay_try_index = 4
    proc._delay_offsets_us = [0, 500, -500]
    proc._search_confirm_same_delay_pending = True
    proc._search_reacquire_same_delay_remaining = 2
    proc.stageChanged = Recorder()
    proc.delayApplied = Recorder()
    reset_calls = {"n": 0}
    proc._reset_contour_tracker = lambda: reset_calls.__setitem__("n", reset_calls["n"] + 1)
    called = {}
    proc._request_settings_with_timeout = lambda settings, on_done, context: called.update(
        {"settings": dict(settings), "context": str(context)}
    )

    proc.onSetDelay()

    assert proc._forced_delay_us is None
    assert proc.target_delay_us == 14500
    assert proc.current_delay_us == 14500
    assert proc._delay_try_index == 0
    assert proc._search_confirm_same_delay_pending is False
    assert proc._search_reacquire_same_delay_remaining == 0
    assert reset_calls["n"] == 1
    assert called["settings"]["flash_delay"] == 14500
    assert called["context"] == "pressure_sweep_set_delay_nozzle_clearance"


def test_pressure_sweep_nozzle_clearance_retargets_delay_instead_of_recenter_move():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.nozzle_center_machine = {"X": 1000, "Y": 2000, "Z": 9000}
    proc.emergence_time_us = 4000
    proc.min_nozzle_clearance_z_steps = 1000
    proc.nozzle_clearance_limit_z_steps = 8000
    proc.max_nominal_delay_us = 15000
    proc.min_delay_us = 0
    proc.max_delay_us = 50000
    proc.current_delay_us = 7000
    proc.target_delay_us = 7000
    proc.vec_steps_per_s = (0.0, 0.0, -500000.0)
    proc._delay_offsets_us = [0, 500, -500]
    proc._centered = True
    proc.stageChanged = Recorder()
    proc.continueSearch = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    proc._set_startup_centering_mode = lambda *args, **kwargs: None
    proc._reset_search_consistency_after_motion = lambda: None
    proc._reset_contour_tracker = lambda: None
    invalidated = []
    proc._invalidate_current_pressure = lambda reason, stage_message=None: invalidated.append(
        (str(reason), str(stage_message))
    )
    proc.droplet_image = np.zeros((500, 500, 3), dtype=np.uint8)
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 500, "Y": 600, "Z": 8100}),
        droplet_camera_model=SimpleNamespace(
            calculate_move_to_target=lambda *_args, **_kwargs: (0, 0, 300),
        ),
    )
    proc._damped_recenter_move = lambda dX, dZ, tracking_mode: (int(dX), int(dZ))
    proc._safe_move_abs = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("should retarget delay instead of moving closer to the nozzle")
    )

    proc._recenter_immediate((250, 250))

    assert invalidated == []
    assert proc._forced_delay_us == 7500
    assert proc.target_delay_us == 7500
    assert proc.continueSearch.calls


def test_pressure_sweep_nozzle_clearance_invalidates_if_later_delay_exceeds_limit():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.nozzle_center_machine = {"X": 1000, "Y": 2000, "Z": 9000}
    proc.emergence_time_us = 4000
    proc.min_nozzle_clearance_z_steps = 1000
    proc.nozzle_clearance_limit_z_steps = 8000
    proc.max_nominal_delay_us = 15000
    proc.min_delay_us = 0
    proc.max_delay_us = 50000
    proc.current_delay_us = 14900
    proc.target_delay_us = 14900
    proc.vec_steps_per_s = (0.0, 0.0, -500000.0)
    proc._delay_offsets_us = [0, 500, -500]
    proc.stageChanged = Recorder()
    proc.continueSearch = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    proc._set_startup_centering_mode = lambda *args, **kwargs: None
    proc._reset_search_consistency_after_motion = lambda: None
    proc._reset_contour_tracker = lambda: None
    invalidated = []
    proc._invalidate_current_pressure = lambda reason, stage_message=None: invalidated.append(
        (str(reason), str(stage_message))
    )

    handled = proc._maybe_retarget_delay_for_nozzle_clearance(
        (1000, 2000, 8500),
        source="unit_test_clearance",
        center_px=(250, 250),
        move_xyz=(0, 0, 300),
        move_raw_xyz=(0, 0, 300),
    )

    assert handled is True
    assert invalidated
    assert invalidated[-1][0] == "nozzle_clearance_delay_over_limit"
    assert not proc.continueSearch.calls


def test_pressure_sweep_capture_redirects_to_background_when_stale():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc._background_stale = True
    proc._background_refresh_count = 0
    proc.background_refresh_limit_per_pressure = 5
    proc.stageChanged = Recorder()
    proc.backgroundRefreshNeeded = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    proc._invalidate_current_pressure = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("should not invalidate while under refresh cap")
    )
    called = {"capture": False}
    proc._capture_with_policy = lambda **kwargs: called.__setitem__("capture", True)

    proc.onCaptureDroplet()

    assert proc.backgroundRefreshNeeded.calls
    assert called["capture"] is False


def test_pressure_sweep_capture_stale_limit_skips_pressure():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc._background_stale = True
    proc._background_refresh_count = 1
    proc.background_refresh_limit_per_pressure = 1
    proc.stageChanged = Recorder()
    proc.backgroundRefreshNeeded = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    invalidated = []
    proc._invalidate_current_pressure = lambda reason, stage_message=None: invalidated.append((reason, stage_message))

    proc.onCaptureDroplet()

    assert invalidated
    assert invalidated[-1][0] == "background_refresh_limit"
    assert not proc.backgroundRefreshNeeded.calls


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
    proc._discard_post_move_pending = False
    proc._discard_post_move_reason = ""
    proc._discard_post_move_target_xyz = None
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
    assert proc._discard_post_move_pending is True
    assert proc._discard_post_move_reason == "stage_move"
    assert proc._discard_post_move_target_xyz == [1200, 2000, 3400]
    assert proc.moveDone.calls


def test_pressure_sweep_safe_move_abs_noop_move_does_not_arm_post_move_discard():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.x_lo, proc.x_hi = 0, 50000
    proc.y_lo, proc.y_hi = 0, 50000
    proc.z_lo, proc.z_hi = 0, 200000
    proc._search_anchor_xyz = (1000, 2000, 3000)
    proc.max_anchor_dx_steps = 500
    proc.max_anchor_dz_steps = 500
    proc.imaging_guard_hit_cap = 5
    proc._imaging_guard_hit_count = 0
    proc.stageChanged = Recorder()
    proc._record_event = lambda *args, **kwargs: None
    proc._record_pressure_result = lambda *args, **kwargs: None
    proc.nextPressure = Recorder()
    proc._discard_post_move_pending = False
    proc._discard_post_move_reason = ""
    proc._discard_post_move_target_xyz = None
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 1200, "Y": 2000, "Z": 3400})
    )
    proc.moveDone = Recorder()
    proc._request_move_absolute_with_timeout = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("no-op move should not issue a move request")
    )

    proc._safe_move_abs((1200, 2000, 3400))

    assert proc._discard_post_move_pending is False
    assert proc._discard_post_move_target_xyz is None
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


def test_pressure_sweep_analyze_droplet_startup_centers_on_first_hit():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    contour = contour_from_rect(20, 30, 8, 8)
    overlay = np.zeros((80, 80, 3), dtype=np.uint8)
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplet_contour=lambda *_args, **_kwargs: (
                contour,
                overlay,
                {"reason": "ok", "p95": 15.0, "center": [24, 34]},
            )
        )
    )
    proc.droplet_image = overlay.copy()
    proc.background_image = overlay.copy()
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.continueSearch = Recorder()
    proc.dropletFound = Recorder()
    proc.readyToCharacterize = Recorder()
    proc.measurements = []
    proc.current_delay_us = 7000
    proc._centered = False
    proc._lost_count = 0
    proc._vertical_probe_tries = 0
    proc.search_stable_hits_required = 2
    proc.search_min_signal_p95 = 10.0
    proc.search_center_jump_max_px = 280.0
    proc.search_low_signal_streak_limit = 10
    proc.search_no_contour_streak_limit = 8
    proc.search_center_jump_streak_limit = 4
    proc._search_last_center = None
    proc._search_stable_hits = 0
    proc._search_low_signal_streak = 0
    proc._search_no_contour_streak = 0
    proc._search_center_jump_streak = 0
    proc._record_pressure_sweep_analysis = lambda *args, **kwargs: None
    proc._record_decision = lambda *args, **kwargs: None
    proc._invalidate_current_pressure = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("should not invalidate in startup immediate-center test")
    )

    proc.onAnalyzeDroplet()
    assert proc.dropletFound.calls
    assert not proc.continueSearch.calls
    assert len(proc.measurements) == 1


def test_pressure_sweep_analyze_droplet_quantification_requires_confirmation():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    contour = contour_from_rect(20, 30, 8, 8)
    overlay = np.zeros((80, 80, 3), dtype=np.uint8)
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplet_contour=lambda *_args, **_kwargs: (
                contour,
                overlay,
                {"reason": "ok", "p95": 15.0, "center": [24, 34]},
            )
        )
    )
    proc.droplet_image = overlay.copy()
    proc.background_image = overlay.copy()
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.continueSearch = Recorder()
    proc.dropletFound = Recorder()
    proc.readyToCharacterize = Recorder()
    proc.measurements = []
    proc.current_delay_us = 7000
    proc._centered = True
    proc._lost_count = 0
    proc._vertical_probe_tries = 0
    proc.search_stable_hits_required = 2
    proc.search_min_signal_p95 = 10.0
    proc.search_center_jump_max_px = 280.0
    proc.search_low_signal_streak_limit = 10
    proc.search_no_contour_streak_limit = 8
    proc.search_center_jump_streak_limit = 4
    proc._search_last_center = None
    proc._search_stable_hits = 0
    proc._search_low_signal_streak = 0
    proc._search_no_contour_streak = 0
    proc._search_center_jump_streak = 0
    proc._record_pressure_sweep_analysis = lambda *args, **kwargs: None
    proc._record_decision = lambda *args, **kwargs: None
    proc._invalidate_current_pressure = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("should not invalidate in quantification confirmation test")
    )

    proc.onAnalyzeDroplet()
    assert proc.continueSearch.calls
    assert not proc.readyToCharacterize.calls

    proc.onAnalyzeDroplet()
    assert proc.readyToCharacterize.calls
    assert not proc.dropletFound.calls
    assert len(proc.measurements) == 1


def test_pressure_sweep_analyze_droplet_discards_first_post_move_frame():
    overlay = np.zeros((80, 80, 3), dtype=np.uint8)
    called = {"identify": 0}

    def _identify(*_args, **_kwargs):
        called["identify"] += 1
        raise AssertionError("post-move discard should happen before contour analysis")

    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(identify_droplet_contour=_identify)
    )
    proc.droplet_image = overlay.copy()
    proc.background_image = overlay.copy()
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.discardRecapture = Recorder()
    proc.continueSearch = Recorder()
    proc.dropletFound = Recorder()
    proc.readyToCharacterize = Recorder()
    proc.current_delay_us = 7200
    proc.target_delay_us = 7200
    proc.cur_pressure = 1.1
    proc._discard_post_move_pending = True
    proc._discard_post_move_reason = "stage_move"
    proc._discard_post_move_target_xyz = [100, 200, 300]
    proc._record_pressure_sweep_analysis = lambda *args, **kwargs: None
    proc._record_decision = lambda *args, **kwargs: None

    proc.onAnalyzeDroplet()

    assert called["identify"] == 0
    assert proc._discard_post_move_pending is False
    assert proc._discard_post_move_reason == ""
    assert proc._discard_post_move_target_xyz is None
    assert proc.discardRecapture.calls
    assert not proc.continueSearch.calls
    assert not proc.dropletFound.calls
    assert not proc.readyToCharacterize.calls


def test_pressure_sweep_set_delay_uses_same_delay_for_confirmation():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc._search_confirm_same_delay_pending = True
    proc.current_delay_us = 7300
    proc._centered = True
    proc._delay_try_index = 4
    proc._delay_offsets_us = [0, 500, -500]
    proc.stageChanged = Recorder()
    proc.delayApplied = Recorder()
    decisions = []
    proc._record_decision = lambda *args, **kwargs: decisions.append((args, kwargs))
    called = {}
    proc._request_settings_with_timeout = lambda settings, on_done, context: called.update(
        {"settings": dict(settings), "context": str(context)}
    )

    proc.onSetDelay()

    assert called["settings"]["flash_delay"] == 7300
    assert called["settings"]["num_droplets"] == 1
    assert called["context"] == "pressure_sweep_set_delay_confirm"
    assert proc._delay_try_index == 4
    assert proc._search_confirm_same_delay_pending is True
    assert decisions


def test_pressure_sweep_set_delay_uses_reacquire_same_delay_budget():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.search_max_elapsed_s = 90.0
    proc._search_started_at_monotonic = time.monotonic()
    proc._search_confirm_same_delay_pending = False
    proc._centered = False
    proc.current_delay_us = 7300
    proc._delay_try_index = 2
    proc._delay_offsets_us = [0, 500, -500]
    proc._search_reacquire_same_delay_remaining = 2
    proc.search_reacquire_same_delay_retries = 2
    proc.stageChanged = Recorder()
    proc.delayApplied = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    called = {}
    proc._request_settings_with_timeout = lambda settings, on_done, context: called.update(
        {"settings": dict(settings), "context": str(context)}
    )

    proc.onSetDelay()

    assert called["settings"]["flash_delay"] == 7300
    assert called["settings"]["num_droplets"] == 1
    assert called["context"] == "pressure_sweep_set_delay_reacquire"
    assert proc._delay_try_index == 2
    assert proc._search_reacquire_same_delay_remaining == 1


def test_pressure_sweep_set_delay_repeats_sweep_when_candidate_seen():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.search_max_elapsed_s = 90.0
    proc._search_started_at_monotonic = time.monotonic()
    proc._search_confirm_same_delay_pending = False
    proc._delay_offsets_us = [0, 500, -500]
    proc._delay_try_index = 3
    proc._search_candidate_seen_since_sweep = True
    proc.current_delay_us = 8100
    proc.target_delay_us = 7200
    proc._vertical_probe_tries = 0
    proc._max_vertical_probes = 2
    proc._search_fail_cycles = 0
    proc.min_delay_us = 0
    proc.max_delay_us = 50000
    proc.stageChanged = Recorder()
    proc.delayApplied = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    proc._probe_half_frame_up = lambda: (_ for _ in ()).throw(
        AssertionError("candidate-seen sweep should not probe")
    )
    proc._safe_move_abs = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("candidate-seen sweep should not nudge")
    )
    called = {}
    proc._request_settings_with_timeout = lambda settings, on_done, context: called.update(
        {"settings": dict(settings), "context": str(context)}
    )

    proc.onSetDelay()

    assert proc.target_delay_us == 8100
    assert proc.current_delay_us == 8100
    assert proc._delay_try_index == 1
    assert proc._search_candidate_seen_since_sweep is False
    assert proc._search_fail_cycles == 0
    assert called["settings"]["flash_delay"] == 8100
    assert called["context"] == "pressure_sweep_set_delay"


def test_pressure_sweep_analyze_droplet_refreshes_on_background_artifact_streak():
    overlay = np.zeros((80, 80, 3), dtype=np.uint8)
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplet_contour=lambda *_args, **_kwargs: (
                None,
                overlay,
                {"reason": "background_artifact", "p95": 2.0, "center": None},
            )
        )
    )
    proc.droplet_image = overlay.copy()
    proc.background_image = overlay.copy()
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.continueSearch = Recorder()
    proc.search_background_artifact_refresh_streak = 2
    proc.search_low_signal_streak_limit = 10
    proc.search_no_contour_streak_limit = 8
    proc.search_center_jump_streak_limit = 4
    proc.search_background_artifact_streak_limit = 8
    proc.search_max_elapsed_s = 90.0
    proc._search_started_at_monotonic = time.monotonic()
    proc._search_confirm_same_delay_pending = False
    proc._search_background_artifact_streak = 0
    proc._search_no_contour_streak = 0
    proc._search_low_signal_streak = 0
    proc._search_stable_hits = 0
    proc._search_last_center = None
    proc._search_last_delay_us = None
    proc._search_center_jump_streak = 0
    proc._background_stale = False
    mark_calls = {"n": 0}
    proc._mark_background_stale = lambda *_args, **_kwargs: mark_calls.__setitem__("n", mark_calls["n"] + 1)
    proc._record_pressure_sweep_analysis = lambda *args, **kwargs: None
    proc._record_decision = lambda *args, **kwargs: None
    proc._invalidate_current_pressure = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("artifact streak should refresh, not invalidate")
    )

    proc.onAnalyzeDroplet()
    assert mark_calls["n"] == 0

    proc.onAnalyzeDroplet()
    assert mark_calls["n"] == 1
    assert proc._search_confirm_same_delay_pending is True
    assert proc.continueSearch.calls


def test_pressure_sweep_set_delay_invalidates_on_search_elapsed_timeout():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.search_max_elapsed_s = 1.0
    proc._search_started_at_monotonic = time.monotonic() - 3.0
    proc._search_confirm_same_delay_pending = False
    proc._delay_try_index = 0
    proc._delay_offsets_us = [0, 500]
    proc.stageChanged = Recorder()
    proc._request_settings_with_timeout = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("timeout path should invalidate before settings call")
    )
    invalidated = []
    proc._invalidate_current_pressure = lambda reason, stage_message=None: invalidated.append(
        (str(reason), str(stage_message))
    )

    proc.onSetDelay()

    assert invalidated
    assert invalidated[-1][0] == "search_elapsed_timeout"


def test_pressure_sweep_search_jump_streak_does_not_abort_after_center_lock():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.search_low_signal_streak_limit = 10
    proc.search_no_contour_streak_limit = 8
    proc.search_center_jump_streak_limit = 4
    proc.search_background_artifact_streak_limit = 8
    proc.search_max_elapsed_s = 90.0
    proc._search_started_at_monotonic = time.monotonic()
    proc._centered = True
    proc._search_low_signal_streak = 0
    proc._search_no_contour_streak = 0
    proc._search_center_jump_streak = 4
    proc._search_background_artifact_streak = 0

    assert proc._search_streak_abort_reason() is None


def test_pressure_sweep_recenter_immediate_keeps_background_and_reenters_startup_mode():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.droplet_image = np.zeros((80, 80, 3), dtype=np.uint8)
    proc._centered = True
    proc._center_last_center = (30, 30)
    proc._center_stable_hits = 4
    proc._center_jump_reject_streak = 1
    proc.search_reacquire_same_delay_retries = 2
    proc._search_reacquire_same_delay_remaining = 0
    proc.center_recenter_gain_tracking = 0.5
    proc.center_recenter_max_step_tracking = 700
    proc._recenter_moves = 1
    proc.stageChanged = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    proc._reset_search_consistency_after_motion = lambda: None
    proc._clamp_xyz = lambda x, y, z: (int(x), int(y), int(z))
    moved = {}
    proc._safe_move_abs = lambda xyz: moved.__setitem__("target", tuple(map(int, xyz)))
    proc._mark_background_stale = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("recenter_immediate should not force background refresh")
    )
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 100, "Y": 200, "Z": 300}),
        droplet_camera_model=SimpleNamespace(calculate_move_to_target=lambda *_args, **_kwargs: (1000, 0, 1000)),
    )

    proc._recenter_immediate((12, 18))

    assert proc._centered is False
    assert proc._char_need_capture is True
    assert proc._search_reacquire_same_delay_remaining == 2
    assert moved["target"] == (600, 200, 800)


def test_pressure_sweep_on_center_recenter_uses_damped_move_without_bg_refresh():
    contour = contour_from_rect(0, 0, 8, 8)
    overlay = np.zeros((500, 500, 3), dtype=np.uint8)
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.droplet_image = overlay.copy()
    proc.background_image = overlay.copy()
    proc._centered = False
    proc._center_last_center = None
    proc._center_stable_hits = 0
    proc._center_jump_reject_streak = 0
    proc._lost_count = 0
    proc._lost_limit = 5
    proc._recenter_moves = 0
    proc.max_recenter_moves = 10
    proc.center_jump_reject_px = 320.0
    proc.search_center_jump_streak_limit = 4
    proc.center_stable_hits_for_bias_update = 3
    proc.center_recenter_gain_startup = 0.5
    proc.center_recenter_max_step_startup = 600
    proc.search_reacquire_same_delay_retries = 2
    proc._search_reacquire_same_delay_remaining = 0
    proc._xz_offset_updated_this_pressure = False
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.continueSearch = Recorder()
    proc.dropletCentered = Recorder()
    proc._record_pressure_sweep_analysis = lambda *args, **kwargs: None
    proc._record_decision = lambda *args, **kwargs: None
    proc._reset_search_consistency_after_motion = lambda: None
    proc._clamp_xyz = lambda x, y, z: (int(x), int(y), int(z))
    proc._invalidate_current_pressure = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("centering recenter move should not invalidate in this scenario")
    )
    proc._mark_background_stale = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("centering recenter should not force background refresh")
    )
    moved = {}
    proc._safe_move_abs = lambda xyz: moved.__setitem__("target", tuple(map(int, xyz)))
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 500, "Y": 600, "Z": 700}),
        droplet_camera_model=SimpleNamespace(
            identify_droplet_contour=lambda *_args, **_kwargs: (
                contour,
                overlay,
                {"reason": "ok", "center": [4, 4]},
            ),
            calculate_move_to_target=lambda *_args, **_kwargs: (1000, 0, -1000),
        ),
    )

    proc.onCenter()

    assert moved["target"] == (1000, 600, 200)
    assert proc._search_reacquire_same_delay_remaining == 2
    assert not proc.dropletCentered.calls
    assert not proc.continueSearch.calls


def test_pressure_sweep_analyze_batch_rejects_high_invalid_ratio():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.num_images = 20
    proc.circularity_threshold = 0.95
    proc.droplet_volumes = [1.0 + (i * 0.01) for i in range(20)]
    proc.circularity_values = [0.95] * 20
    proc.droplet_positions = [(120, 230)] * 20
    proc.cur_pressure = 1.20
    proc.current_delay_us = 7000
    proc.target_delay_us = 7000
    proc.multiple_droplet_hits = 0
    proc._char_stream_hits = 0
    proc._char_invalid_hits = 9
    proc._char_frames_evaluated = 20
    proc.char_max_invalid_ratio = 0.20
    proc.char_max_multiple_ratio = 0.90
    proc.char_max_stream_ratio = 0.90
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
    proc._record_decision = lambda *args, **kwargs: None
    proc._record_pressure_sweep_analysis = lambda *args, **kwargs: None
    proc._emit_incremental_pressure_step = lambda rec: None
    proc.i = 0
    proc._reset_char_buffers = lambda: None
    proc.nextPressure = Recorder()

    proc.onAnalyzeBatch()

    assert proc.samples
    assert proc.samples[-1]["valid"] is False
    assert proc.samples[-1]["invalid_reason"] == "char_invalid_ratio_exceeded"


def test_pressure_sweep_nonround_characterization_retargets_same_pressure_and_updates_anchor():
    proc, _state, moves = _build_pressure_sweep_focus_proc(
        [6_000_000, 6_000_000, 6_000_000],
        roundness_values=[0.85, 0.84, 0.83],
    )
    proc._target_xyz_for_delay = lambda delay_us, include_offsets=True: (int(delay_us), 1100, 2100)
    proc.nextPressure = Recorder()

    proc.onCharacterizeLoop()
    proc.onCharacterizeLoop()
    proc.onCharacterizeLoop()

    assert proc._morphology_retarget_count == 1
    assert proc._morphology_retarget_history_us == [8000]
    assert proc.target_delay_us == 8000
    assert proc._forced_delay_us == 8000
    assert proc.image_counter == 0
    assert proc.circularity_values == []
    assert proc.droplet_volumes == []
    assert proc._search_anchor_xyz == (8000, 1100, 2100)
    assert moves[-1] == (8000, 1100, 2100)
    assert proc._background_stale is True
    assert not proc.nextPressure.calls


def test_pressure_sweep_second_morphology_retarget_uses_second_step():
    proc, _state, moves = _build_pressure_sweep_focus_proc(
        [6_000_000],
        roundness_values=[0.85],
    )
    proc.current_delay_us = 7500
    proc.target_delay_us = 7500
    proc._morphology_retarget_count = 1
    proc._morphology_retarget_history_us = [7500]
    proc._morphology_window_evaluable_count = 2
    proc._morphology_window_nonround_hits = 2
    proc._morphology_nonround_hits_total = 2
    proc._target_xyz_for_delay = lambda delay_us, include_offsets=True: (int(delay_us), 1200, 2200)

    handled = proc._maybe_retarget_for_morphology(
        (200, 200),
        0.85,
        focus_val=6_000_000.0,
        stream_like=False,
    )

    assert handled is True
    assert proc._morphology_retarget_count == 2
    assert proc._morphology_retarget_history_us == [7500, 9500]
    assert proc.target_delay_us == 9500
    assert proc._forced_delay_us == 9500
    assert proc._search_anchor_xyz == (9500, 1200, 2200)
    assert moves[-1] == (9500, 1200, 2200)


def test_pressure_sweep_pre_final_phase_keeps_strict_roundness_gate():
    proc, _state, moves = _build_pressure_sweep_focus_proc(
        [6_000_000],
        roundness_values=[0.92],
    )
    proc.current_delay_us = 7500
    proc.target_delay_us = 7500
    proc._morphology_retarget_count = 1
    proc._morphology_retarget_history_us = [7500]
    proc._morphology_window_evaluable_count = 2
    proc._morphology_window_nonround_hits = 2
    proc._morphology_nonround_hits_total = 2
    proc._target_xyz_for_delay = lambda delay_us, include_offsets=True: (int(delay_us), 1200, 2200)

    handled = proc._maybe_retarget_for_morphology(
        (200, 200),
        0.92,
        focus_val=6_000_000.0,
        stream_like=False,
    )

    assert handled is True
    assert proc._morphology_retarget_count == 2
    assert proc._morphology_retarget_history_us == [7500, 9500]
    assert proc.target_delay_us == 9500
    assert proc._forced_delay_us == 9500
    assert moves[-1] == (9500, 1200, 2200)


def test_pressure_sweep_morphology_delay_over_limit_invalidates_pressure():
    proc, _state, moves = _build_pressure_sweep_focus_proc(
        [6_000_000],
        roundness_values=[0.85],
    )
    proc.current_delay_us = 14900
    proc.target_delay_us = 14900
    proc.max_nominal_delay_us = 15000
    proc._morphology_window_evaluable_count = 2
    proc._morphology_window_nonround_hits = 2
    proc._morphology_nonround_hits_total = 2
    invalidated = []
    proc._invalidate_current_pressure = lambda reason, stage_message=None: invalidated.append(
        (str(reason), str(stage_message))
    )

    handled = proc._maybe_retarget_for_morphology(
        (200, 200),
        0.85,
        focus_val=6_000_000.0,
        stream_like=False,
    )

    assert handled is True
    assert invalidated
    assert invalidated[-1][0] == "morphology_delay_over_limit"
    assert moves == []


def test_pressure_sweep_morphology_retarget_exhausted_invalidates_pressure():
    proc, _state, moves = _build_pressure_sweep_focus_proc(
        [6_000_000],
        roundness_values=[0.85],
    )
    proc._morphology_retarget_count = 2
    proc.char_delay_retarget_cap = 2
    proc._morphology_window_evaluable_count = 2
    proc._morphology_window_nonround_hits = 2
    proc._morphology_nonround_hits_total = 2
    invalidated = []
    proc._invalidate_current_pressure = lambda reason, stage_message=None: invalidated.append(
        (str(reason), str(stage_message))
    )

    handled = proc._maybe_retarget_for_morphology(
        (200, 200),
        0.85,
        focus_val=6_000_000.0,
        stream_like=False,
    )

    assert handled is True
    assert invalidated
    assert invalidated[-1][0] == "morphology_retarget_exhausted"
    assert moves == []


def test_pressure_sweep_final_phase_accepts_point92_roundness():
    proc, _state, moves = _build_pressure_sweep_focus_proc(
        [6_000_000],
        roundness_values=[0.92],
    )
    proc.current_delay_us = 9500
    proc.target_delay_us = 9500
    proc._morphology_retarget_count = 2
    proc._morphology_retarget_history_us = [7500, 9500]
    proc._morphology_nonround_hits_total = 2

    proc.onCharacterizeLoop()

    assert proc.image_counter == 1
    assert proc.circularity_values == [0.92]
    assert proc.droplet_volumes == [1.0]
    assert proc._morphology_window_evaluable_count == 1
    assert proc._morphology_window_nonround_hits == 0
    assert proc._char_stream_hits == 0
    assert proc.continueCap.calls
    assert not moves


def test_pressure_sweep_final_phase_still_rejects_stream_like_frames():
    proc, _state, _moves = _build_pressure_sweep_focus_proc(
        [6_000_000],
        roundness_values=[0.55],
    )
    proc.current_delay_us = 9500
    proc.target_delay_us = 9500
    proc._morphology_retarget_count = 2
    proc._morphology_retarget_history_us = [7500, 9500]
    proc._morphology_nonround_hits_total = 2

    proc.onCharacterizeLoop()

    assert proc.image_counter == 0
    assert proc.circularity_values == []
    assert proc._char_stream_hits == 1
    assert proc._char_invalid_hits == 1
    assert proc.continueCap.calls


def test_pressure_sweep_morphology_evidence_ignores_none_and_multiple_frames():
    proc, _state, _moves = _build_pressure_sweep_focus_proc(
        [6_000_000],
        roundness_values=[0.85],
    )
    overlay = np.zeros((400, 400, 3), dtype=np.uint8)
    sequence = [
        (None, overlay.copy()),
        ("Multiple", overlay.copy()),
        (
            {
                "center": (200, 200),
                "focus": 6_000_000.0,
                "circularity_ellipse": 0.85,
                "ellipse_roundness": 0.85,
                "volume": 1.0,
            },
            overlay.copy(),
        ),
    ]
    proc.model.droplet_camera_model = SimpleNamespace(
        characterize_droplet=lambda *_args, **_kwargs: sequence.pop(0),
        convert_pixel_position_to_motor_steps=lambda _center, pos: dict(pos),
    )

    proc.onCharacterizeLoop()
    assert proc._morphology_window_evaluable_count == 0
    assert proc._morphology_window_nonround_hits == 0

    proc.onCharacterizeLoop()
    assert proc._morphology_window_evaluable_count == 0
    assert proc._morphology_window_nonround_hits == 0

    proc.onCharacterizeLoop()
    assert proc._morphology_window_evaluable_count == 1
    assert proc._morphology_window_nonround_hits == 1
    assert proc._morphology_nonround_hits_total == 1


def test_pressure_sweep_focus_below_threshold_does_not_count_as_invalid_ratio_hit():
    proc, _state, moves = _build_pressure_sweep_focus_proc([4_800_000])
    proc._char_invalid_hits = 4
    proc._char_frames_evaluated = 9
    proc._char_attempts = 9
    invalidated = []
    proc._invalidate_current_pressure = lambda reason, stage_message=None: invalidated.append(
        (str(reason), str(stage_message))
    )

    proc.onCharacterizeLoop()

    assert proc._char_invalid_hits == 4
    assert invalidated == []
    assert proc.analyzeBatch.calls == []
    assert moves
    assert moves[-1][1] > 1000


def test_pressure_sweep_focus_progress_updates_persistent_y_offset_before_threshold():
    proc, _state, moves = _build_pressure_sweep_focus_proc([4_600_000, 4_760_000])
    invalidated = []
    proc._invalidate_current_pressure = lambda reason, stage_message=None: invalidated.append(
        (str(reason), str(stage_message))
    )

    proc.onCharacterizeLoop()
    proc.onCharacterizeLoop()

    assert invalidated == []
    assert len(moves) >= 2
    assert proc._focus_best >= 4_760_000
    assert proc._focus_best_y_offset_steps is not None
    assert proc._focus_best_y_offset_steps > 0
    assert proc._y_focus_offset_steps > 0

    proc.vec_steps_per_s = (0.0, 0.0, 0.0)
    proc._x_track_offset_steps = 0
    proc._z_track_offset_steps = 0
    proc._predict_target_xyz = lambda *_args, **_kwargs: (100, 200, 300)
    proc._clamp_xyz = lambda x, y, z: (int(x), int(y), int(z))
    proc._mark_background_stale = lambda *_args, **_kwargs: None
    target = {}
    proc._safe_move_abs = lambda xyz: target.__setitem__("xyz", tuple(map(int, xyz)))

    proc.onMoveToTarget()

    assert target["xyz"][1] == 200 + int(proc._y_focus_offset_steps)


def test_pressure_sweep_focus_stall_still_invalidates_on_move_budget():
    proc, _state, _moves = _build_pressure_sweep_focus_proc([4_700_000])
    proc._focus_best = 4_800_000
    proc._focus_moves_done = 60
    invalidated = []
    proc._invalidate_current_pressure = lambda reason, stage_message=None: invalidated.append(
        (str(reason), str(stage_message))
    )

    proc.onCharacterizeLoop()

    assert invalidated
    assert invalidated[-1][0] == "focus_move_budget_exceeded"
