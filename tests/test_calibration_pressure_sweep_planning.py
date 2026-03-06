import inspect
import time
from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import Recorder, contour_from_rect, ensure_calibration_import_stubs


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


def test_pressure_sweep_analyze_batch_rejects_high_invalid_ratio():
    proc = PressureSweepCharacterizationProcess.__new__(PressureSweepCharacterizationProcess)
    proc.num_images = 20
    proc.circularity_threshold = 1.18
    proc.droplet_volumes = [1.0 + (i * 0.01) for i in range(20)]
    proc.circularity_values = [1.0] * 20
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
