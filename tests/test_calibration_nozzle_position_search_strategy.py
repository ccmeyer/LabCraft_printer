from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import NozzlePositionCalibrationProcess, _detect_nozzle_point_from_diff


def _bg_head_in_view_image():
    img = np.full((200, 200, 3), 245, dtype=np.uint8)
    img[:40, :, :] = 70
    return img


def _bg_head_out_of_view_image():
    return np.full((200, 200, 3), 240, dtype=np.uint8)


def _build_process_for_detection():
    proc = NozzlePositionCalibrationProcess.__new__(NozzlePositionCalibrationProcess)
    proc.fixed_thresh_value = 30
    proc.no_signal_min_fg_px = 120
    proc.min_stream_bbox_h_px = 10
    proc.search_top_band_frac = 0.60
    proc._last_detection_details = {}
    return proc


def _make_smear_pair():
    bg = np.zeros((320, 320, 3), dtype=np.uint8)
    dr = bg.copy()
    dr[20:240, 80:120, :] = 255
    dr[40:52, 120:250, :] = 255
    return bg, dr


def _make_clean_stream_pair():
    bg = np.zeros((320, 320, 3), dtype=np.uint8)
    dr = bg.copy()
    dr[20:240, 120:160, :] = 255
    return bg, dr


def _make_weak_vertical_support_pair():
    bg = np.zeros((320, 320, 3), dtype=np.uint8)
    dr = bg.copy()
    dr[40:52, 20:280, :] = 255
    return bg, dr


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
    decision_calls = []

    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            compute_move_by_fraction=lambda x_frac, y_frac: (1000 * float(x_frac), 0, 1000 * float(y_frac)),
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
        set_nozzle_detection_flash_delay_us=lambda *_: None,
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
    proc._record_decision = lambda decision, payload=None: decision_calls.append((decision, dict(payload or {})))
    proc._record_event = lambda *args, **kwargs: None
    proc._test_decisions = decision_calls

    proc.background_image = _bg_head_in_view_image()
    proc.droplet_image = np.zeros((16, 16, 3), dtype=np.uint8)
    proc._throwaway_pending = False
    proc._last_capture_refs = {
        "background_image": {},
        "droplet_image": {},
    }

    proc.initial_flash_delay_us = 2600
    proc._current_flash_delay_us = 2600
    proc.multi_contour_delay_step_us = 200
    proc.max_multi_contour_probe_steps = 3
    proc.multi_contour_match_max_center_px = 120.0
    proc.multi_contour_match_min_iou = 0.10
    proc.multi_contour_responsive_area_drop_frac = 0.15
    proc.multi_contour_responsive_height_drop_frac = 0.15
    proc.multi_contour_responsive_bottom_up_px = 25
    proc.multi_contour_static_area_change_frac = 0.08
    proc.multi_contour_static_height_change_frac = 0.10
    proc.multi_contour_static_center_shift_px = 25.0
    proc._reset_multi_contour_tracking()
    proc.min_flash_delay_us = 2000
    proc.max_flash_delay_us = 12_000
    proc.nozzle_search_half_fov_fraction = 0.5
    proc.nozzle_search_min_half_fov_x_steps = 200
    proc._x_scan_anchor = dict(anchor)
    proc._x_scan_half_fov_x_steps = 500
    proc._x_scan_attempt_index = 0
    proc._x_scan_active = False
    proc.downward_recovery_step_fov = 0.25
    proc.max_downward_recovery_steps = 4
    proc._downward_recovery_steps_taken = 0
    proc.head_view_top_band_frac = 0.20
    proc.head_view_mid_start_frac = 0.35
    proc.head_view_mid_end_frac = 0.65
    proc.head_not_in_view_ratio_min = 0.90
    proc.head_not_in_view_delta_max = 25.0
    proc._base_pressure = 1.0
    proc._recenter_iters = 0
    proc.move_timeout_ms = 15_000
    proc.max_xy_steps_per_correction = 1000
    proc._default_axis_spans = {"X": 20_000, "Y": 10_000, "Z": 20_000}
    proc.top_margin_frac = 0.12
    proc.center_tol_frac = 0.03
    proc.top_band_frac = 0.03
    proc.fixed_thresh_value = 30
    proc.no_signal_min_fg_px = 120
    proc.min_stream_bbox_h_px = 10
    proc.search_top_band_frac = 0.60
    proc._last_detection_details = {}
    proc.measurements = []

    return proc, pos, settings_calls, move_calls, recenter_calls


def _candidate(area, bbox, nozzle_xy=None):
    x, y, w, h = bbox
    return {
        "area": float(area),
        "bbox": [int(x), int(y), int(w), int(h)],
        "top_y": int(y),
        "bottom_y": int(y + h - 1),
        "width": int(w),
        "height": int(h),
        "bbox_mid_x": int(round(x + w / 2.0)),
        "bbox_mid_y": int(round(y + h / 2.0)),
        "support_mid_x": None if nozzle_xy is None else int(nozzle_xy[0]),
        "support_span_px": max(0, int(w // 2)),
        "support_threshold_px": 30,
        "support_peak_px": int(h),
        "support_column_count": max(0, int(w // 2)),
        "bbox_support_dx": 0,
        "x_measurement_mode": "vertical_support" if nozzle_xy is not None else "insufficient_vertical_support",
        "ambiguous_lateral_spread": False,
        "nozzle_xy": None if nozzle_xy is None else [int(nozzle_xy[0]), int(nozzle_xy[1])],
    }


def _install_detection(proc, status, candidates):
    dbg = np.zeros((16, 16, 3), dtype=np.uint8)

    def _detect(_bg, _dr):
        proc._last_detection_details = {
            "status": str(status),
            "candidates": [dict(c) for c in candidates],
            "candidate_summaries": [
                {
                    "area": float(c["area"]),
                    "top_y": int(c["top_y"]),
                    "bbox": list(c["bbox"]),
                    "bottom_y": int(c["bottom_y"]),
                }
                for c in candidates
            ],
        }
        nozzle = None
        if str(status) == "OK" and candidates:
            nozzle = tuple(candidates[0].get("nozzle_xy") or (0, 0))
        return str(status), nozzle, len(candidates) if str(status) == "OK" else 0, dbg

    proc._detect_nozzle_point = _detect


def test_background_head_view_metrics_discriminates_in_view_vs_out_of_view():
    proc, _pos, _settings_calls, _move_calls, _recenter_calls = _build_process_for_analyze()

    in_view = proc._background_head_view_metrics(_bg_head_in_view_image())
    out_view = proc._background_head_view_metrics(_bg_head_out_of_view_image())

    assert in_view["valid"] is True and in_view["head_in_view"] is True
    assert out_view["valid"] is True and out_view["head_in_view"] is False
    assert out_view["top_to_mid_ratio"] > in_view["top_to_mid_ratio"]
    assert out_view["top_mid_delta"] < in_view["top_mid_delta"]


def test_detect_nozzle_uses_vertical_support_midpoint_for_connected_smear():
    proc = _build_process_for_detection()
    bg, dr = _make_smear_pair()

    status, nozzle_px, n_contours, _ = proc._detect_nozzle_point(bg, dr)

    assert status == "OK"
    assert n_contours == 1
    assert nozzle_px is not None
    assert 95 <= nozzle_px[0] <= 105
    assert nozzle_px[0] < 130
    assert proc._last_detection_details["x_measurement_mode"] == "vertical_support_guardrailed"
    assert proc._last_detection_details["ambiguous_lateral_spread"] is True
    assert proc._last_detection_details["bbox_mid_x"] - proc._last_detection_details["support_mid_x"] >= 50


def test_detect_nozzle_uses_vertical_support_for_clean_stream():
    proc = _build_process_for_detection()
    bg, dr = _make_clean_stream_pair()

    status, nozzle_px, n_contours, _ = proc._detect_nozzle_point(bg, dr)

    assert status == "OK"
    assert n_contours == 1
    assert nozzle_px is not None
    assert 138 <= nozzle_px[0] <= 142
    assert proc._last_detection_details["x_measurement_mode"] == "vertical_support"
    assert proc._last_detection_details["ambiguous_lateral_spread"] is False
    assert abs(proc._last_detection_details["bbox_mid_x"] - proc._last_detection_details["support_mid_x"]) <= 2


def test_shared_nozzle_detector_matches_nozzle_position_detector():
    proc = _build_process_for_detection()
    bg, dr = _make_clean_stream_pair()

    direct = proc._detect_nozzle_point(bg, dr)[:3]
    proc._last_detection_details = {}
    shared = _detect_nozzle_point_from_diff(proc, bg, dr)[:3]

    assert shared == direct
    assert proc._last_detection_details["status"] == "OK"
    assert proc._last_detection_details["x_measurement_mode"] == "vertical_support"


def test_detect_nozzle_rejects_frames_without_vertical_support_band():
    proc = _build_process_for_detection()
    bg, dr = _make_weak_vertical_support_pair()

    status, nozzle_px, n_contours, _ = proc._detect_nozzle_point(bg, dr)

    assert status == "NONE"
    assert nozzle_px is None
    assert n_contours == 0
    assert proc._last_detection_details["reason"] == "no_vertical_support_band"
    assert proc._last_detection_details["support_column_count"] == 0


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


def test_nozzle_head_out_of_view_moves_down_before_any_x_scan():
    proc, _pos, settings_calls, move_calls, _ = _build_process_for_analyze()
    proc.background_image = _bg_head_out_of_view_image()
    proc._detect_nozzle_point = lambda bg, dr: ("NO_SIGNAL", None, 0, None)

    proc.onAnalyze()

    assert len(move_calls) == 1
    assert move_calls[0] == (10000, 2000, 3250)
    assert proc._x_scan_attempt_index == 0
    assert proc._downward_recovery_steps_taken == 1
    assert proc.calibrationError.calls == []
    assert settings_calls == []


def test_nozzle_downward_recovery_capped_after_one_full_fov():
    proc, pos, settings_calls, move_calls, _ = _build_process_for_analyze()
    proc.background_image = _bg_head_out_of_view_image()
    proc._detect_nozzle_point = lambda bg, dr: ("NO_SIGNAL", None, 0, None)

    for _ in range(5):
        proc.onAnalyze()
        if proc.calibrationError.calls:
            break
        if move_calls:
            last = move_calls[-1]
            pos.update({"X": int(last[0]), "Y": int(last[1]), "Z": int(last[2])})

    # Four downward recovery steps max; then abort.
    assert move_calls == [
        (10000, 2000, 3250),
        (10000, 2000, 3500),
        (10000, 2000, 3750),
        (10000, 2000, 4000),
    ]
    assert proc._downward_recovery_steps_taken == 4
    assert proc.calibrationError.calls
    assert "printer head not visible" in proc.calibrationError.calls[-1][0][0].lower()
    assert settings_calls == []


def test_nozzle_uses_x_scan_after_head_becomes_visible():
    proc, pos, settings_calls, move_calls, _ = _build_process_for_analyze()
    proc.background_image = _bg_head_out_of_view_image()
    proc._detect_nozzle_point = lambda bg, dr: ("NO_SIGNAL", None, 0, None)

    # First miss while head out of view -> downward move only.
    proc.onAnalyze()
    assert move_calls == [(10000, 2000, 3250)]
    pos.update({"X": 10000, "Y": 2000, "Z": 3250})

    # Once head is visible, X scan begins.
    proc.background_image = _bg_head_in_view_image()
    proc.onAnalyze()
    assert move_calls[-1] == (9500, 2000, 3250)
    assert proc._x_scan_attempt_index == 1
    assert settings_calls == []


def test_multiple_contours_first_frame_probes_flash_delay_once():
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
    assert proc._test_decisions[-1][0] == "multi_contour_delay_probe"


def test_multiple_contours_delay_floor_clamps_at_2000():
    proc, _pos, settings_calls, _move_calls, _recenter_calls = _build_process_for_analyze()
    dbg = np.zeros((16, 16, 3), dtype=np.uint8)
    proc._detect_nozzle_point = lambda bg, dr: ("OK", (300, 120), 2, dbg)
    proc._current_flash_delay_us = 2100

    proc.onAnalyze()

    assert settings_calls and settings_calls[0]["flash_delay"] == 2000
    assert proc.calibrationError.calls == []
    assert proc._test_decisions[-1][0] == "multi_contour_delay_probe"


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


def test_delay_responsive_candidate_is_selected_after_probe():
    proc, _pos, settings_calls, move_calls, recenter_calls = _build_process_for_analyze()
    proc._current_flash_delay_us = 5100
    high_delay = [
        _candidate(60_000, [220, 20, 200, 520], [315, 20]),
        _candidate(30_000, [470, 25, 205, 200], [575, 25]),
    ]
    low_delay = [
        _candidate(42_000, [225, 20, 195, 390], [314, 20]),
        _candidate(29_500, [472, 26, 204, 199], [574, 26]),
    ]

    _install_detection(proc, "OK", high_delay)
    proc.onAnalyze()
    assert settings_calls[-1]["flash_delay"] == 4900
    assert recenter_calls == []

    _install_detection(proc, "OK", low_delay)
    proc.onAnalyze()

    assert recenter_calls == [(314, 20)]
    assert move_calls == []
    assert proc.calibrationError.calls == []
    assert settings_calls == [{"num_droplets": 1, "flash_delay": 4900}]
    assert any(d[0] == "multi_contour_selected_responsive_candidate" for d in proc._test_decisions)


def test_aligned_single_contour_after_probe_is_accepted_as_attached_stream():
    proc, _pos, settings_calls, move_calls, recenter_calls = _build_process_for_analyze()
    proc._current_flash_delay_us = 5100
    late_separated = [
        _candidate(18_111.0, [827, 538, 149, 164], [901, 538]),
        _candidate(27_802.5, [859, 102, 102, 390], [915, 102]),
    ]
    earlier_attached = [
        _candidate(37_122.5, [857, 103, 113, 463], [918, 103]),
    ]

    _install_detection(proc, "OK", late_separated)
    proc.onAnalyze()
    assert settings_calls[-1]["flash_delay"] == 4900
    assert recenter_calls == []

    _install_detection(proc, "OK", earlier_attached)
    proc.onAnalyze()

    assert recenter_calls == [(918, 103)]
    assert move_calls == []
    assert proc.calibrationError.calls == []
    assert any(d[0] == "multi_contour_selected_attached_single_candidate" for d in proc._test_decisions)


def test_highlighted_shape_does_not_jump_to_static_artifact():
    proc, _pos, settings_calls, move_calls, recenter_calls = _build_process_for_analyze()
    proc._current_flash_delay_us = 5100
    high_delay = [
        _candidate(62731.0, [230, 20, 210, 543], [314, 20]),
        _candidate(29795.5, [471, 27, 205, 201], [574, 27]),
    ]
    low_delay = [
        _candidate(8251.5, [238, 115, 209, 77], [313, 115]),
        _candidate(30820.5, [470, 24, 208, 204], [574, 24]),
    ]

    _install_detection(proc, "OK", high_delay)
    proc.onAnalyze()
    assert settings_calls[-1]["flash_delay"] == 4900

    _install_detection(proc, "OK", low_delay)
    proc.onAnalyze()

    assert recenter_calls == [(313, 115)]
    assert recenter_calls[0][0] != 574
    assert move_calls == []
    assert proc.calibrationError.calls == []


def test_static_single_contour_after_probe_aborts_without_recenter_or_x_scan():
    proc, _pos, settings_calls, move_calls, recenter_calls = _build_process_for_analyze()
    proc._current_flash_delay_us = 5100
    high_delay = [
        _candidate(62_000, [230, 20, 210, 540], [314, 20]),
        _candidate(30_000, [470, 25, 205, 200], [575, 25]),
    ]
    static_artifact = [
        _candidate(29_500, [472, 26, 204, 199], [574, 26]),
    ]

    _install_detection(proc, "OK", high_delay)
    proc.onAnalyze()
    assert settings_calls[-1]["flash_delay"] == 4900

    _install_detection(proc, "OK", static_artifact)
    proc.onAnalyze()

    assert recenter_calls == []
    assert move_calls == []
    assert proc.calibrationError.calls
    assert "ambiguous contours" in proc.calibrationError.calls[-1][0][0].lower()
    assert proc._test_decisions[-1][0] == "multi_contour_ambiguous_abort"


def test_no_signal_after_multi_contour_probe_aborts_without_x_scan():
    proc, _pos, settings_calls, move_calls, recenter_calls = _build_process_for_analyze()
    proc._current_flash_delay_us = 5100
    high_delay = [
        _candidate(60_000, [220, 20, 200, 520], [315, 20]),
        _candidate(30_000, [470, 25, 205, 200], [575, 25]),
    ]

    _install_detection(proc, "OK", high_delay)
    proc.onAnalyze()
    assert settings_calls[-1]["flash_delay"] == 4900

    _install_detection(proc, "NONE", [])
    proc.onAnalyze()

    assert recenter_calls == []
    assert move_calls == []
    assert proc.calibrationError.calls
    assert proc._test_decisions[-1][0] == "multi_contour_ambiguous_abort"


def test_static_multiple_contours_abort_at_probe_limit():
    proc, _pos, settings_calls, move_calls, recenter_calls = _build_process_for_analyze()
    proc.max_multi_contour_probe_steps = 1
    proc._current_flash_delay_us = 5100
    high_delay = [
        _candidate(30_000, [220, 20, 200, 200], [320, 20]),
        _candidate(28_000, [470, 25, 205, 200], [575, 25]),
    ]
    low_delay = [
        _candidate(29_500, [221, 21, 199, 199], [320, 21]),
        _candidate(27_700, [471, 25, 205, 201], [574, 25]),
    ]

    _install_detection(proc, "OK", high_delay)
    proc.onAnalyze()
    assert settings_calls[-1]["flash_delay"] == 4900

    _install_detection(proc, "OK", low_delay)
    proc.onAnalyze()

    assert recenter_calls == []
    assert move_calls == []
    assert proc.calibrationError.calls
    assert proc._test_decisions[-1][0] == "multi_contour_ambiguous_abort"


def test_single_contour_still_uses_recenter_path():
    proc, _pos, settings_calls, move_calls, recenter_calls = _build_process_for_analyze()
    dbg = np.zeros((16, 16, 3), dtype=np.uint8)
    proc._detect_nozzle_point = lambda bg, dr: ("OK", (300, 120), 1, dbg)

    proc.onAnalyze()

    assert recenter_calls == [(300, 120)]
    assert settings_calls == []
    assert move_calls == []
    assert proc.calibrationError.calls == []


def test_on_analyze_routes_real_detector_result_to_recenter_once():
    proc, _pos, settings_calls, move_calls, recenter_calls = _build_process_for_analyze()
    bg, dr = _make_smear_pair()
    proc.background_image = bg
    proc.droplet_image = dr

    proc.onAnalyze()

    assert len(recenter_calls) == 1
    assert 95 <= recenter_calls[0][0] <= 105
    assert 18 <= recenter_calls[0][1] <= 21
    assert settings_calls == []
    assert move_calls == []
    assert proc._last_detection_details["x_measurement_mode"] == "vertical_support_guardrailed"
