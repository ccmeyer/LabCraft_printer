from collections import deque
from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import Recorder, SignalStub, ensure_calibration_import_stubs


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


def test_focus_process_uses_tracked_y_when_machine_feedback_lags():
    move_completed = Recorder()
    nozzle_focused = Recorder()
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    proc.stageChanged = Recorder()
    proc.calibrationError = Recorder()
    proc.nozzleFocused = nozzle_focused
    proc.calibration_manager = SimpleNamespace(
        emitMoveCompleted=move_completed.emit,
        captureImageRequested=SignalStub(),
    )
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 10, "Y": 100, "Z": 20})
    )
    proc.best_pos = {"Y": 120}
    proc.valid_focus_evals = 6
    proc.best_focus_stats = {"p90_ratio_to_background": 1.45}
    proc._tracked_pos = {"X": 10, "Y": 100, "Z": 20}
    proc._loY = 0
    proc._hiY = 500
    proc.mode = "probe_dir"
    proc._targets = deque(maxlen=proc._OSC_HISTORY)

    requested_moves = []

    def _stub_move(move_vector, *, on_done=None, **kwargs):
        requested_moves.append(move_vector)
        if callable(on_done):
            on_done()

    proc._request_move_relative_with_timeout = _stub_move

    proc._move_to_Y_clamped(116)

    assert requested_moves[0] == (0, 16, 0)
    assert proc._tracked_pos["Y"] == 116
    assert move_completed.calls

    proc._move_to_best_then_finish()

    assert requested_moves[1] == (0, 4, 0)
    assert proc._tracked_pos["Y"] == 120
    assert nozzle_focused.calls
    assert proc.calibrationError.calls == []


def test_focus_no_move_pre_refine_recapture_uses_shared_capture_policy():
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    capture_signal = SignalStub()
    proc.calibration_manager = SimpleNamespace(captureImageRequested=capture_signal)
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 10, "Y": 100, "Z": 20})
    )
    proc._tracked_pos = {"X": 10, "Y": 100, "Z": 20}
    proc._loY = 0
    proc._hiY = 500
    proc._lo_br_y = None
    proc._hi_br_y = None
    proc.mode = "probe_dir"
    proc._targets = deque(maxlen=proc._OSC_HISTORY)
    capture_policy_calls = []
    proc._capture_with_policy = lambda **kwargs: capture_policy_calls.append(dict(kwargs))

    proc._move_to_Y_clamped(100)

    assert capture_signal.calls == []
    assert len(capture_policy_calls) == 1
    assert capture_policy_calls[0] == {
        "set_attr": "droplet_image",
        "stage_text": "Recapturing focus frame",
        "attempts_total": 7,
        "retry_delay_ms": 75,
        "guard_timeout_ms": 12_000,
        "final_error_msg": "Failed to capture droplet for focus.",
    }


def test_initialize_focus_bounds_clamps_to_axis_limits():
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_axis_bounds=lambda axis: (100, 200))
    )
    proc.SAFE_SWEEP_STEPS = 500

    proc._initialize_focus_bounds(150)

    assert proc._loY == 100
    assert proc._hiY == 200


def _build_post_focus_refresh_proc(prior_center=(546, 196)):
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.postFocusNozzleRefreshFinished = Recorder()
    proc.min_flash_delay_us = 2000
    proc.max_flash_delay_us = 12_000
    proc.post_focus_nozzle_refresh_flash_delay_us = 2600
    proc.fixed_thresh_value = 30
    proc.no_signal_min_fg_px = 120
    proc.min_stream_bbox_h_px = 10
    proc.search_top_band_frac = 0.60
    proc._last_detection_details = {}
    proc._pre_focus_nozzle_center_px = tuple(prior_center)
    proc._post_focus_nozzle_refresh_done = False
    proc._last_capture_refs = {
        "background_image": {"capture_id": "bg-1", "image_relpath": "bg.png"},
        "droplet_image": {"capture_id": "dr-1", "image_relpath": "dr.png"},
    }
    proc.phase_name = "nozzle_focus"

    calls = {"background": [], "image_center": [], "decisions": [], "analysis": []}
    proc._record_decision = lambda name, payload=None: calls["decisions"].append((name, dict(payload or {})))
    proc._record_analysis = lambda payload: calls["analysis"].append(dict(payload or {}))
    proc.calibration_manager = SimpleNamespace(
        set_background_image=lambda image: calls["background"].append(image),
        set_nozzle_center_image_position=lambda center, source="": calls["image_center"].append(
            (tuple(center), source)
        ),
    )
    return proc, calls


def test_focus_post_refresh_success_updates_image_center_and_diagnostics():
    proc, calls = _build_post_focus_refresh_proc(prior_center=(546, 196))
    proc.background_image = np.zeros((320, 800, 3), dtype=np.uint8)
    proc.droplet_image = proc.background_image.copy()
    proc.droplet_image[20:240, 646:686, :] = 255

    proc.onPostFocusAnalyzeNozzle()

    assert len(calls["image_center"]) == 1
    refreshed_center, refreshed_source = calls["image_center"][0]
    assert refreshed_source == "nozzle_focus_refresh"
    assert abs(refreshed_center[0] - 666) <= 2
    assert abs(refreshed_center[1] - 20) <= 2
    assert len(calls["background"]) == 1
    assert calls["background"][0] is proc.background_image
    result = proc._post_focus_nozzle_refresh_result
    assert result["status"] == "ok"
    assert result["pre_focus_nozzle_center_px"] == (546, 196)
    assert result["post_focus_nozzle_center_px"] == refreshed_center
    assert result["post_focus_nozzle_delta_px"] == (
        refreshed_center[0] - 546,
        refreshed_center[1] - 196,
    )
    assert result["post_focus_nozzle_center_source"] == "nozzle_focus_refresh"
    assert calls["analysis"][-1]["kind"] == "post_focus_nozzle_detection"
    assert proc.postFocusNozzleRefreshFinished.calls


def test_focus_post_refresh_delay_prefers_accepted_nozzle_detection_delay():
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    proc.min_flash_delay_us = 2000
    proc.max_flash_delay_us = 12_000
    proc.calibration_manager = SimpleNamespace(
        get_nozzle_detection_flash_delay_us=lambda: 4600,
    )

    assert proc._resolve_post_focus_refresh_delay_us(2500) == 4600

    proc.calibration_manager = SimpleNamespace(
        get_nozzle_detection_flash_delay_us=lambda: None,
    )
    assert proc._resolve_post_focus_refresh_delay_us(2500) == 5100


def test_focus_post_refresh_multi_contour_preserves_prior_center():
    proc, calls = _build_post_focus_refresh_proc(prior_center=(546, 196))
    proc.post_focus_nozzle_refresh_flash_delay_us = 4600
    proc.background_image = np.zeros((800, 800, 3), dtype=np.uint8)
    proc.droplet_image = proc.background_image.copy()
    proc.droplet_image[100:360, 500:560, :] = 255
    proc.droplet_image[430:550, 490:610, :] = 255

    proc.onPostFocusAnalyzeNozzle()

    assert calls["image_center"] == []
    assert calls["background"] == []
    result = proc._post_focus_nozzle_refresh_result
    assert result["status"] == "failed"
    assert result["reason"] == "multi_contour_refresh_preserved_prior"
    assert result["pre_focus_nozzle_center_px"] == (546, 196)
    assert result["post_focus_nozzle_center_px"] is None
    assert result["post_focus_nozzle_center_source"] == "none"
    assert result["n_contours"] == 2
    assert calls["decisions"][0][0] == "post_focus_nozzle_refresh_preserved_prior"
    assert proc.postFocusNozzleRefreshFinished.calls


def test_focus_post_refresh_failure_preserves_prior_center():
    proc, calls = _build_post_focus_refresh_proc(prior_center=(546, 196))

    proc._finish_post_focus_nozzle_refresh(
        "failed",
        reason="foreground_below_min",
        detection={"status": "NO_SIGNAL"},
    )

    assert calls["image_center"] == []
    assert calls["background"] == []
    result = proc._post_focus_nozzle_refresh_result
    assert result["status"] == "failed"
    assert result["reason"] == "foreground_below_min"
    assert result["pre_focus_nozzle_center_px"] == (546, 196)
    assert result["post_focus_nozzle_center_px"] is None
    assert result["post_focus_nozzle_center_source"] == "none"
    assert calls["decisions"][0][0] == "post_focus_nozzle_refresh_preserved_prior"
    assert proc.postFocusNozzleRefreshFinished.calls


def test_focus_completion_includes_post_refresh_diagnostics():
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    proc.best_pos = {"Y": 273}
    proc._start_pos = {"X": 10, "Y": 200, "Z": 30}
    proc._tracked_pos = {"X": 10, "Y": 273, "Z": 30}
    proc.focus_curve = []
    proc.best_focus = 123.0
    proc.best_focus_stats = {"p90_ratio_to_background": 1.4}
    proc.valid_focus_evals = 5
    proc.invalid_focus_evals = 1
    proc._post_focus_nozzle_refresh_result = {
        "status": "ok",
        "pre_focus_nozzle_center_px": (546, 196),
        "post_focus_nozzle_center_px": (666, 273),
        "post_focus_nozzle_delta_px": (120, 77),
        "post_focus_nozzle_center_source": "nozzle_focus_refresh",
    }
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 10, "Y": 273, "Z": 30})
    )
    calls = {"machine": []}
    proc.calibration_manager = SimpleNamespace(
        set_nozzle_center=lambda center: calls["machine"].append(dict(center))
    )
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()

    proc.onCalibrationCompleted()

    result = proc.calibrationDataUpdated.calls[0][0][0]["result"]
    assert calls["machine"] == [{"X": 10, "Y": 273, "Z": 30}]
    assert result["post_focus_nozzle_refresh_status"] == "ok"
    assert result["post_focus_nozzle_center_px"] == (666, 273)
    assert result["post_focus_nozzle_delta_px"] == (120, 77)
    assert proc.calibrationCompleted.calls
