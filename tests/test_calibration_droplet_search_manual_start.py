from types import SimpleNamespace

import cv2
import numpy as np

from tests.calibration_test_utils import Recorder, contour_from_rect, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import DropletCameraModel, DropletSearchCalibrationProcess


def _recorder_texts(recorder):
    return [args[0] for args, _kwargs in recorder.calls if args]


def _camera_stub():
    cam = DropletCameraModel.__new__(DropletCameraModel)
    cam._k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cam._last_droplet_center_px = None
    return cam


def _build_proc(*, manual_start=False, contour_fn=None, characterize_fn=None):
    proc = DropletSearchCalibrationProcess.__new__(DropletSearchCalibrationProcess)
    proc._aborted = False
    proc._finished = False
    proc._save_enabled = False
    proc._bg_saved = False
    proc.manual_start = bool(manual_start)
    proc.measurements = []
    proc.background_image = np.zeros((120, 160, 3), dtype=np.uint8)
    proc.droplet_image = np.zeros((120, 160, 3), dtype=np.uint8)
    proc.num_images = 3
    proc.image_counter = 0
    proc.circularity_threshold = 0.91
    proc.droplet_positions = []
    proc.droplet_focus = []
    proc.circularity_values = []
    proc.droplet_volumes = []
    proc.early_stop_min_reps = 6
    proc.early_stop_window = 3
    proc.early_stop_mean_drift_pct = 1.5
    proc.early_stop_cv_drift_pct = 1.0
    proc._early_stop_satisfied = False

    proc.current_delay_us = 4300
    proc.target_delay_us = 4300
    proc._manual_fixed_delay_us = 4300
    proc.delay_offsets_us = [0, 500, -500]
    proc._delay_try_index = 0
    proc.min_delay_us = 0
    proc.max_delay_us = 50_000
    proc._not_found_count = 0
    proc._not_found_limit = 4
    proc._lost_count = 0
    proc._lost_limit = 2
    proc._manual_search_miss_count = 0
    proc._manual_search_miss_limit = 2
    proc.vel_steps_per_s = (500.0, 0.0, 0.0)

    proc.search_stable_hits_required = 2
    proc.search_center_jump_max_px = 280.0
    proc.search_cross_delay_jump_scale = 1.8
    proc.search_min_signal_p95 = 10.0
    proc.center_jump_reject_px = 320.0
    proc.center_stable_hits_for_bias_update = 3
    proc.boundary_tol_px = 250
    proc.center_first_tol_px = 30
    proc.max_recenter_moves = 6
    proc.max_oob_total = 5
    proc.char_stream_circularity_max = 0.58
    proc.char_max_invalid_ratio = 0.45
    proc.char_max_multiple_ratio = 0.20
    proc.char_max_stream_ratio = 0.20

    proc._centered = False
    proc._char_need_capture = False
    proc._search_last_center = None
    proc._search_last_delay_us = None
    proc._search_stable_hits = 0
    proc._search_confirm_same_settings_pending = False
    proc._center_last_center = None
    proc._center_stable_hits = 0
    proc._center_jump_reject_streak = 0
    proc._recenter_moves = 0
    proc._oob_total = 0
    proc._oob_streak = 0
    proc._oob_positions = []
    proc._xz_offset_updated_this_pressure = False
    proc._discard_post_move_pending = False
    proc._discard_post_move_reason = ""
    proc._discard_post_move_target_xyz = None

    proc.focus_ok_threshold = 500_000.0
    proc.focus_min_step = 1
    proc.focus_step = 4
    proc.focus_dir = 1
    proc.focus_dir_switches = 0
    proc.focus_switch_limit = 2
    proc._focus_best = 0.0
    proc._focus_same_dir_tries = 0
    proc._focus_moves_done = 0
    proc._focus_move_budget = 10
    proc._min_focus_gain = 0.01
    proc._focus_best_y_offset_steps = None
    proc._focus_best_source = ""
    proc._y_focus_offset_steps = 0
    proc._y_focus_ema_alpha = 0.35

    proc._char_invalid_hits = 0
    proc._char_stream_hits = 0
    proc.multiple_droplet_hits = 0
    proc._char_frames_evaluated = 0
    proc._char_attempts = 0
    proc._char_attempt_limit = 20
    proc._final_invalid_reason = None
    proc.x_lo, proc.x_hi = 0, 50_000
    proc.y_lo, proc.y_hi = 0, 50_000
    proc.z_lo, proc.z_hi = 0, 50_000
    proc.max_anchor_dx_steps = 350
    proc.max_anchor_dy_steps = 500
    proc.max_anchor_dz_steps = 5_000
    proc.imaging_guard_hit_cap = 6
    proc._imaging_guard_hit_count = 0
    proc._motion_anchor_xyz = (1000, 2000, 3000)
    proc._last_safe_xyz = (1000, 2000, 3000)
    proc._last_observed_live_xyz = None

    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.continueSearch = Recorder()
    proc.dropletFound = Recorder()
    proc.readyToCharacterize = Recorder()
    proc.dropletCentered = Recorder()
    proc.continueCharacterization = Recorder()
    proc.initiateCharacterizationAnalysis = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.characterizationCompleted = Recorder()
    proc.calibrationError = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.changePressure = Recorder()

    proc.state_machine = SimpleNamespace(stop=lambda: None)
    move_done = []
    proc.calibration_manager = SimpleNamespace(
        changeSettingsRequested=Recorder(),
        emitSettingsChangeCompleted=lambda: None,
        emitMoveCompleted=lambda: move_done.append(True),
    )

    analysis_rows = []
    move_targets = []
    xz_updates = []
    tracker_resets = []
    live_position = {"X": 1000, "Y": 2000, "Z": 3000}

    proc._save_capture = lambda *_args, **_kwargs: {"index": 1}
    proc._save_overlay = lambda *_args, **_kwargs: None
    proc._append_analysis = lambda row: analysis_rows.append(dict(row))
    proc._ensure_saving = lambda: None
    proc._stop_saving_if_started = lambda: None
    proc._annotate_final = lambda *_args, **_kwargs: np.ones_like(proc.droplet_image)
    proc._update_xz_track_offset = lambda: xz_updates.append("updated")
    proc._reset_contour_tracker = lambda: tracker_resets.append(True)

    def _request_move_absolute_with_timeout(target, *, on_done=None, **_kwargs):
        tgt = tuple(map(int, target))
        move_targets.append(tgt)
        live_position.update({"X": tgt[0], "Y": tgt[1], "Z": tgt[2]})
        if callable(on_done):
            on_done()

    proc._request_move_absolute_with_timeout = _request_move_absolute_with_timeout

    if contour_fn is None:
        contour = contour_from_rect(60, 45, 20, 20)

        def contour_fn(image, _bg, return_details=False):
            overlay = image.copy()
            details = {"center": (70, 55), "p95": 15.0, "reason": "ok"}
            if return_details:
                return contour, overlay, details
            return contour, overlay

    if characterize_fn is None:

        def characterize_fn(image, _bg):
            return {
                "center": (80, 60),
                "focus": 800_000.0,
                "circularity": 0.95,
                "circularity_ellipse": 0.95,
                "volume": 10.0,
            }, image.copy()

    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: dict(live_position),
            get_current_print_pressure=lambda: 1.61,
            get_print_pulse_width=lambda: 1500,
        ),
        droplet_camera_model=SimpleNamespace(
            identify_droplet_contour=contour_fn,
            characterize_droplet=characterize_fn,
            calculate_move_to_target=lambda center, target: (
                int(target[0] - center[0]),
                0,
                int(target[1] - center[1]),
            ),
            convert_pixel_position_to_motor_steps=lambda center, machine_position: {
                "X": int(center[0]),
                "Y": int(machine_position["Y"]),
                "Z": int(center[1]),
            },
            write_json=lambda *_args, **_kwargs: None,
        ),
    )
    proc.nozzle_center_machine = {"X": 1000, "Y": 2000, "Z": 3000}

    return proc, {
        "analysis_rows": analysis_rows,
        "move_targets": move_targets,
        "live_position": live_position,
        "move_done": move_done,
        "tracker_resets": tracker_resets,
        "xz_updates": xz_updates,
    }


def test_droplet_search_manual_mode_keeps_fixed_delay():
    proc, _ctx = _build_proc(manual_start=True)
    proc.current_delay_us = None
    proc.target_delay_us = 4825
    proc._manual_fixed_delay_us = 4825

    proc.onSetDelay()

    settings = proc.calibration_manager.changeSettingsRequested.calls[0][0][0]
    assert settings == {"flash_delay": 4825, "num_droplets": 1}
    assert proc.current_delay_us == 4825
    assert "print_pressure" not in settings
    assert "Using fixed manual delay 4825" in _recorder_texts(proc.stageChanged)[-1]


def test_droplet_search_regular_mode_preserves_delay_sweep_search():
    proc, _ctx = _build_proc(manual_start=False)
    proc.target_delay_us = 4300
    proc.delay_offsets_us = [0, 250, -250]
    proc._delay_try_index = 1

    proc.onSetDelay()

    settings = proc.calibration_manager.changeSettingsRequested.calls[0][0][0]
    assert settings == {"flash_delay": 4550, "num_droplets": 1}
    assert proc.current_delay_us == 4550
    assert proc._delay_try_index == 2


def test_droplet_search_manual_mode_retries_and_aborts_when_no_droplet_visible():
    def contour_fn(image, _bg, return_details=False):
        overlay = image.copy()
        details = {"center": None, "p95": 0.0, "reason": "no_contour"}
        if return_details:
            return None, overlay, details
        return None, overlay

    proc, _ctx = _build_proc(manual_start=True, contour_fn=contour_fn)
    proc._manual_search_miss_limit = 2

    proc.onAnalyze()

    assert proc._manual_search_miss_count == 1
    assert proc._search_confirm_same_settings_pending is True
    assert len(proc.continueSearch.calls) == 1
    assert proc.calibrationError.calls == []
    assert "No droplet visible" in _recorder_texts(proc.stageChanged)[-1]

    proc.onAnalyze()

    assert proc._manual_search_miss_count == 2
    assert len(proc.continueSearch.calls) == 1
    assert len(proc.calibrationError.calls) == 1
    assert "fixed manual settings" in proc.calibrationError.calls[0][0][0]


def test_droplet_search_centered_reacquire_goes_directly_to_characterization():
    proc, _ctx = _build_proc(manual_start=True)
    proc._centered = True
    proc._search_last_center = (70, 55)
    proc._search_last_delay_us = 4300
    proc._search_stable_hits = 1

    proc.onAnalyze()

    assert len(proc.readyToCharacterize.calls) == 1
    assert proc.dropletFound.calls == []
    assert any("reacquired" in text for text in _recorder_texts(proc.stageChanged))


def test_droplet_search_discards_first_post_move_frame_and_requests_same_settings_retry():
    proc, _ctx = _build_proc(manual_start=True)
    proc._discard_post_move_pending = True
    proc._discard_post_move_reason = "stage_move"
    proc._discard_post_move_target_xyz = [100, 200, 300]

    proc.onAnalyze()

    assert proc._discard_post_move_pending is False
    assert proc._discard_post_move_reason == ""
    assert proc._discard_post_move_target_xyz is None
    assert proc._search_confirm_same_settings_pending is True
    assert proc.measurements == []
    assert len(proc.continueSearch.calls) == 1
    assert "Discarding first post-move frame" in _recorder_texts(proc.stageChanged)[-1]


def test_droplet_search_multiple_detection_does_not_change_pressure():
    def characterize_fn(image, _bg):
        return "Multiple", image.copy()

    proc, _ctx = _build_proc(manual_start=True, characterize_fn=characterize_fn)

    proc.onCharacterization()

    assert proc.multiple_droplet_hits == 1
    assert proc._char_invalid_hits == 1
    assert len(proc.continueCharacterization.calls) == 1
    assert proc.changePressure.calls == []
    assert proc.image_counter == 0


def test_droplet_search_characterization_accepts_replicate_and_reports_progress():
    def characterize_fn(image, _bg, return_details=False):
        result = {
            "center": (80, 60),
            "focus": 800_000.0,
            "circularity": 0.95,
            "circularity_ellipse": 0.95,
            "volume": 10.25,
        }
        details = {"reason": "ok", "center": (80, 60), "bbox": [60, 40, 40, 40], "contour_area": 1200.0}
        if return_details:
            return result, image.copy(), details
        return result, image.copy()

    proc, _ctx = _build_proc(manual_start=True, characterize_fn=characterize_fn)

    proc.onCharacterization()

    assert proc.image_counter == 1
    assert proc.droplet_volumes == [10.25]
    assert len(proc.continueCharacterization.calls) == 1
    assert any("Accepted replicate 1/3" in text for text in _recorder_texts(proc.stageChanged))


def test_droplet_search_characterization_recenters_before_focus_work():
    def characterize_fn(image, _bg):
        return {
            "center": (10, 10),
            "focus": 900_000.0,
            "circularity": 0.96,
            "circularity_ellipse": 0.96,
            "volume": 9.8,
        }, image.copy()

    proc, _ctx = _build_proc(manual_start=True, characterize_fn=characterize_fn)
    recenter_calls = []
    proc._recenter_immediate = lambda center_px: recenter_calls.append(tuple(center_px))

    proc.onCharacterization()

    assert recenter_calls == [(10, 10)]
    assert proc.image_counter == 0
    assert proc.droplet_volumes == []
    assert proc.continueCharacterization.calls == []
    assert proc.initiateCharacterizationAnalysis.calls == []


def test_droplet_search_characterization_preserves_specific_failure_reason_at_attempt_limit():
    def characterize_fn(image, _bg, return_details=False):
        details = {"reason": "no_large_contours", "bbox": None, "contour_area": 0.0}
        if return_details:
            return None, image.copy(), details
        return None, image.copy()

    proc, _ctx = _build_proc(manual_start=True, characterize_fn=characterize_fn)
    proc._char_attempt_limit = 2

    proc.onCharacterization()
    assert len(proc.continueCharacterization.calls) == 1
    assert proc._final_invalid_reason is None

    proc.onCharacterization()
    assert proc._final_invalid_reason == "no_large_contours"
    assert len(proc.initiateCharacterizationAnalysis.calls) == 1

    proc.onAnalyzeCharacterization()
    payload = proc.calibrationDataUpdated.calls[0][0][0]["result"]
    assert payload["invalid_reason"] == "no_large_contours"


def test_droplet_search_invalid_characterization_payload_includes_reason_and_diagnostics():
    proc, _ctx = _build_proc(manual_start=True)
    proc._char_invalid_hits = 4
    proc._char_stream_hits = 1
    proc.multiple_droplet_hits = 2
    proc._char_frames_evaluated = 7
    proc._focus_best = 987_654.0
    proc._focus_moves_done = 5
    proc.focus_dir_switches = 2
    proc._y_focus_offset_steps = 11
    proc._focus_best_y_offset_steps = 14
    proc._final_invalid_reason = "char_invalid_ratio_exceeded"

    proc.onAnalyzeCharacterization()

    payload = proc.calibrationDataUpdated.calls[0][0][0]["result"]
    assert payload["valid"] is False
    assert payload["invalid_reason"] == "char_invalid_ratio_exceeded"
    assert payload["accepted_replicates"] == 0
    assert payload["captured_replicates"] == 0
    assert payload["multiple_detections"] == 2
    assert payload["stream_like_detections"] == 1
    assert payload["invalid_frame_hits"] == 4
    assert payload["characterization_frames"] == 7
    assert payload["y_focus_offset_steps"] == 11
    assert payload["best_focus_seen"] == 987_654.0
    assert payload["focus_moves_done"] == 5
    assert payload["focus_dir_switches"] == 2
    assert payload["best_focus_y_offset_steps"] == 14


def test_droplet_search_manual_move_guard_clamps_target_inside_anchor_envelope():
    proc, ctx = _build_proc(manual_start=True)

    proc._safe_move_relative((4000, 0, 12000))

    assert ctx["move_targets"] == [(1350, 2000, 8000)]
    assert proc._last_safe_xyz == (1350, 2000, 8000)
    assert any("Imaging guard clamped target" in text for text in _recorder_texts(proc.stageChanged))


def test_droplet_search_manual_focus_move_stays_inside_y_guard_window():
    proc, ctx = _build_proc(manual_start=True)

    proc._safe_move_relative((0, 700, 0))

    assert ctx["move_targets"] == [(1000, 2500, 3000)]
    assert proc._last_safe_xyz == (1000, 2500, 3000)


def test_droplet_search_manual_guard_limit_aborts_before_dangerous_move():
    proc, ctx = _build_proc(manual_start=True)
    proc.imaging_guard_hit_cap = 1

    proc._safe_move_relative((4000, 0, 12000))

    assert ctx["move_targets"] == []
    assert proc._final_invalid_reason == "imaging_guard_limit"
    assert len(proc.calibrationError.calls) == 1
    assert "imaging_guard_limit" in proc.calibrationError.calls[0][0][0]


def test_droplet_search_manual_safe_move_uses_last_safe_xyz_not_stale_live_position():
    proc, ctx = _build_proc(manual_start=True)
    ctx["live_position"].update({"X": 11125, "Y": 10000, "Z": 20000})

    proc._safe_move_relative((100, 0, 200))

    assert ctx["move_targets"] == [(1100, 2000, 3200)]
    assert proc._last_safe_xyz == (1100, 2000, 3200)


def test_characterize_droplet_return_details_reports_no_large_contours():
    cam = _camera_stub()
    bg = np.zeros((420, 420, 3), dtype=np.uint8)
    img = bg.copy()
    cv2.circle(img, (210, 220), 8, (255, 255, 255), -1)

    result, _annotated, details = cam.characterize_droplet(img, bg, return_details=True)

    assert result is None
    assert details["reason"] == "no_large_contours"


def test_characterize_droplet_return_details_reports_multiple_large_contours():
    cam = _camera_stub()
    bg = np.zeros((420, 420, 3), dtype=np.uint8)
    img = bg.copy()
    cv2.circle(img, (130, 210), 30, (255, 255, 255), -1)
    cv2.circle(img, (300, 220), 28, (255, 255, 255), -1)

    result, _annotated, details = cam.characterize_droplet(img, bg, return_details=True)

    assert result == "Multiple"
    assert details["reason"] == "multiple_large_contours"


def test_characterize_droplet_accepts_contour_that_matches_search_filter_window():
    cam = _camera_stub()
    bg = np.zeros((420, 420, 3), dtype=np.uint8)
    img = bg.copy()
    cv2.ellipse(img, (210, 220), (40, 13), 0, 0, 360, (255, 255, 255), -1)

    contour, _overlay, search_details = cam.identify_droplet_contour(img, bg, return_details=True)
    result, _annotated, char_details = cam.characterize_droplet(img, bg, return_details=True)

    assert contour is not None
    assert search_details["reason"] == "ok"
    assert isinstance(result, dict)
    assert char_details["reason"] == "ok"
    assert abs(float(result["ellipse_roundness"]) - float(result["circularity_ellipse"])) < 1e-9
    assert abs(float(char_details["ellipse_roundness"]) - float(char_details["circularity_ellipse"])) < 1e-9
