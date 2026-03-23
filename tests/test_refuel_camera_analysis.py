import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

import CalibrationClasses.Model as CalibrationModelModule
from CalibrationClasses.Model import ImageAnalysisThread, RefuelCameraModel


def _build_analysis_view(
    *,
    head_rect=(200, 80, 120, 180),
    left_offset=40,
    channel_width=20,
    meniscus_row=None,
    channel_intensity=80,
    top_intensity=40,
    bottom_intensity=220,
    reference_intensity=220,
):
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    x, y, w, h = head_rect
    image[y : y + h, x : x + w] = 160

    x0 = x + left_offset
    channel = image[y : y + h, x0 : x0 + channel_width]
    channel[:] = channel_intensity
    if meniscus_row is not None:
        channel[:meniscus_row] = top_intensity
        channel[meniscus_row:] = bottom_intensity

    ref_x0 = x0 + channel_width + 5
    image[y : y + h, ref_x0 : ref_x0 + channel_width] = reference_intensity
    return image, head_rect


def _thread_input_from_analysis_view(image):
    return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)


def _sample_context(*, ts="2026-03-21T10:00:00Z", mono=100.0, level=100.0):
    return {
        "timestamp_utc": ts,
        "monotonic_s": mono,
        "print_pressure": 1.2,
        "refuel_pressure": 0.9,
        "print_pulse_width": 1400,
        "refuel_pulse_width": 900,
        "location": "camera",
        "level_hint": level,
    }


def _owner_model(tmp_path, *, record_mode=True):
    calibration_manager = SimpleNamespace(
        get_record_mode_enabled=lambda: record_mode,
        _build_recorder_meta=lambda: {"test_meta": True},
    )
    experiment_model = SimpleNamespace(experiment_dir_path=str(tmp_path))
    return SimpleNamespace(
        calibration_manager=calibration_manager,
        experiment_model=experiment_model,
    )


def test_image_analysis_thread_detects_meniscus_row_and_level():
    expected_row = 60
    analysis_view, head_rect = _build_analysis_view(meniscus_row=expected_row)
    thread = ImageAnalysisThread(
        _thread_input_from_analysis_view(analysis_view),
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
    )

    thread.analyze_image()

    expected_level = head_rect[3] - expected_row
    assert thread.meniscus_row is not None
    assert abs(thread.meniscus_row - expected_row) <= 3
    assert abs(thread.level_data - expected_level) <= 3


def test_image_analysis_thread_empty_fallback_sets_bottom_row():
    analysis_view, head_rect = _build_analysis_view(
        meniscus_row=None,
        channel_intensity=10,
        reference_intensity=220,
    )
    thread = ImageAnalysisThread(
        _thread_input_from_analysis_view(analysis_view),
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
    )

    thread.analyze_image()

    assert thread.meniscus_row == head_rect[3] - 3
    assert thread.level_data == 3


def test_image_analysis_thread_full_fallback_sets_top_row():
    analysis_view, head_rect = _build_analysis_view(
        meniscus_row=None,
        channel_intensity=220,
        reference_intensity=220,
    )
    thread = ImageAnalysisThread(
        _thread_input_from_analysis_view(analysis_view),
        offset=40,
        width=20,
        threshold=80,
        prominence=4,
        empty_cutoff=0.25,
        last_row=None,
    )

    thread.analyze_image()

    assert thread.meniscus_row == 3
    assert thread.level_data == head_rect[3] - 3


def test_refuel_camera_model_start_analysis_uses_last_meniscus_row(monkeypatch):
    captured = {}

    class _SignalStub:
        def connect(self, fn):
            captured["connected"] = fn

    class _ThreadStub:
        def __init__(self, image, offset, width, threshold, prominence, empty_cutoff, last_row, parent=None):
            captured["shape"] = image.shape
            captured["last_row"] = last_row
            self.analysis_done = _SignalStub()

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(CalibrationModelModule, "ImageAnalysisThread", _ThreadStub)

    model = RefuelCameraModel()
    model.last_meniscus_row = 17
    model.level_log = [91]

    ok = model.start_analysis(np.zeros((16, 16, 3), dtype=np.uint8))

    assert ok is True
    assert captured["last_row"] == 17
    assert captured["shape"] == (640, 480, 3)
    assert captured["started"] is True


def test_refuel_camera_model_none_frame_is_safe_noop():
    model = RefuelCameraModel()
    model.current_level = 42
    model.level_log = [42]
    model.last_meniscus_row = 11
    model.original_image = "keep"
    model.annotated_image = "keep"

    ok = model.start_analysis(None)

    assert ok is False
    assert model.current_level == 42
    assert model.level_log == [42]
    assert model.last_meniscus_row == 11
    assert model.original_image == "keep"
    assert model.annotated_image == "keep"


def test_refuel_camera_model_build_dataset_analysis_seed_returns_geometry_and_level():
    analysis_view, head_rect = _build_analysis_view(meniscus_row=60)
    raw_frame = _thread_input_from_analysis_view(analysis_view)
    model = RefuelCameraModel()
    model.update_analysis_parameters(40, 20, 80, 4, 0.25)

    seed = model.build_dataset_analysis_seed(raw_frame)

    assert seed is not None
    assert seed["predicted_status"] == "visible"
    assert abs(seed["predicted_level_px"] - (head_rect[3] - 60)) <= 3
    assert seed["predicted_channel_geometry"]["left_wall"] is not None
    assert seed["predicted_meniscus_line"] is not None
    for point in seed["predicted_meniscus_line"]:
        assert 0 <= point[0] < raw_frame.shape[1]
        assert 0 <= point[1] < raw_frame.shape[0]


def test_refuel_camera_model_lock_target_tracks_setpoint_and_status():
    model = RefuelCameraModel()
    model.current_level = 52.5
    model.last_meniscus_row = 17

    ok, message = model.lock_current_as_target(5)

    assert ok is True
    assert message == ""
    assert model.get_target_level_px() == 52.5
    assert model.get_target_meniscus_row() == 17
    assert model.is_session_active() is True
    assert model.get_live_status() == "In Band"
    assert model.classify_live_status(46.0) == "Low"
    assert model.classify_live_status(60.0) == "High"


def test_refuel_camera_model_update_ui_records_timestamped_sample_context():
    model = RefuelCameraModel()
    model._analysis_context = _sample_context(mono=25.0)

    model.update_ui_with_analysis("orig", "ann", 42.0, 11)

    trace = model.get_sample_trace()
    assert len(trace) == 1
    assert trace[0]["timestamp_utc"] == "2026-03-21T10:00:00Z"
    assert trace[0]["elapsed_s"] == 0.0
    assert trace[0]["print_pressure"] == 1.2
    assert trace[0]["refuel_pressure"] == 0.9
    assert trace[0]["print_pulse_width"] == 1400
    assert trace[0]["refuel_pulse_width"] == 900
    assert trace[0]["location"] == "camera"
    assert model.get_level_log() == [42.0]


def test_refuel_camera_model_invalid_analysis_does_not_append_sample():
    model = RefuelCameraModel()
    model._analysis_context = _sample_context(mono=30.0)

    model.update_ui_with_analysis("orig", "ann", None, None)

    assert model.get_sample_trace() == []
    assert model.get_level_log() == []


def test_refuel_camera_model_start_analysis_skips_overlap(monkeypatch):
    started = []

    class _SignalStub:
        def connect(self, fn):
            started.append(fn)

    class _ThreadStub:
        def __init__(self, *args, **kwargs):
            self.analysis_done = _SignalStub()
            self.finished = _SignalStub()

        def start(self):
            started.append("start")

    monkeypatch.setattr(CalibrationModelModule, "ImageAnalysisThread", _ThreadStub)

    model = RefuelCameraModel()
    model._analysis_in_progress = True

    ok = model.start_analysis(np.zeros((8, 8, 3), dtype=np.uint8), context=_sample_context())

    assert ok is False
    assert started == []


def test_refuel_camera_model_finalize_burst_recommends_pressure_increase():
    model = RefuelCameraModel()
    model.target_level_px = 100.0
    model.target_meniscus_row = 25
    model.tolerance_px = 5.0
    model.session_active = True
    model.sample_trace = [
        {"elapsed_s": 0.0, "monotonic_s": 1.0, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 0.5, "monotonic_s": 1.5, "level_px": 101.0, "phase": "live"},
        {"elapsed_s": 1.0, "monotonic_s": 2.0, "level_px": 99.0, "phase": "live"},
        {"elapsed_s": 1.5, "monotonic_s": 2.5, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 2.0, "monotonic_s": 3.0, "level_px": 100.0, "phase": "live"},
    ]

    result = model.begin_burst(pre_samples=5, post_samples=3, settle_ms=1000, droplet_count=20)
    assert result["ok"] is True
    model.mark_burst_started()
    model.mark_burst_wait_complete(_sample_context(mono=10.0))

    model._analysis_context = _sample_context(ts="2026-03-21T10:00:11Z", mono=10.1)
    model.update_ui_with_analysis("orig", "ann", 93.0, 20)
    model._analysis_context = _sample_context(ts="2026-03-21T10:00:12Z", mono=10.2)
    model.update_ui_with_analysis("orig", "ann", 92.0, 21)
    model._analysis_context = _sample_context(ts="2026-03-21T10:00:13Z", mono=10.3)
    model.update_ui_with_analysis("orig", "ann", 94.0, 22)

    burst = model.get_last_burst_result()
    assert burst is not None
    assert burst["recommendation"] == "Increase refuel pressure"
    assert model.is_burst_in_progress() is False


def test_refuel_camera_model_begin_burst_blocks_when_baseline_is_out_of_band():
    model = RefuelCameraModel()
    model.target_level_px = 100.0
    model.tolerance_px = 5.0
    model.session_active = True
    model.sample_trace = [
        {"elapsed_s": 0.0, "monotonic_s": 1.0, "level_px": 112.0, "phase": "live"},
        {"elapsed_s": 0.5, "monotonic_s": 1.5, "level_px": 111.0, "phase": "live"},
        {"elapsed_s": 1.0, "monotonic_s": 2.0, "level_px": 113.0, "phase": "live"},
        {"elapsed_s": 1.5, "monotonic_s": 2.5, "level_px": 112.0, "phase": "live"},
        {"elapsed_s": 2.0, "monotonic_s": 3.0, "level_px": 111.0, "phase": "live"},
    ]

    result = model.begin_burst(pre_samples=5, post_samples=3, settle_ms=1000, droplet_count=20)

    assert result["ok"] is False
    assert result["code"] == "baseline_out_of_band"


def test_refuel_camera_model_finalize_burst_recommends_decrease_and_in_band():
    high_model = RefuelCameraModel()
    high_model.target_level_px = 100.0
    high_model.tolerance_px = 5.0
    high_model.session_active = True
    high_model.sample_trace = [
        {"elapsed_s": 0.0, "monotonic_s": 1.0, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 0.5, "monotonic_s": 1.5, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 1.0, "monotonic_s": 2.0, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 1.5, "monotonic_s": 2.5, "level_px": 100.0, "phase": "live"},
        {"elapsed_s": 2.0, "monotonic_s": 3.0, "level_px": 100.0, "phase": "live"},
    ]
    assert high_model.begin_burst(5, 3, 1000, 20)["ok"] is True
    high_model.mark_burst_wait_complete(_sample_context(mono=10.0))
    for mono, level in ((10.1, 108.0), (10.2, 109.0), (10.3, 107.0)):
        high_model._analysis_context = _sample_context(mono=mono)
        high_model.update_ui_with_analysis("orig", "ann", level, 10)
    assert high_model.get_last_burst_result()["recommendation"] == "Decrease refuel pressure"

    band_model = RefuelCameraModel()
    band_model.target_level_px = 100.0
    band_model.tolerance_px = 5.0
    band_model.session_active = True
    band_model.sample_trace = list(high_model.sample_trace[:5])
    assert band_model.begin_burst(5, 3, 1000, 20)["ok"] is True
    band_model.mark_burst_wait_complete(_sample_context(mono=20.0))
    for mono, level in ((20.1, 102.0), (20.2, 101.0), (20.3, 100.0)):
        band_model._analysis_context = _sample_context(mono=mono)
        band_model.update_ui_with_analysis("orig", "ann", level, 10)
    assert band_model.get_last_burst_result()["recommendation"] == "Refuel balance is within band"


def test_refuel_camera_model_record_mode_creates_run_and_analysis_files(tmp_path):
    owner = _owner_model(tmp_path, record_mode=True)
    model = RefuelCameraModel(owner)
    model.current_level = 88.0
    model.last_meniscus_row = 19
    model.original_image = np.zeros((12, 12, 3), dtype=np.uint8)

    ok, _ = model.lock_current_as_target(5)

    assert ok is True
    run_root = Path(tmp_path) / "calibration_recordings" / "RefuelBalanceCalibrationProcess"
    run_dirs = list(run_root.iterdir())
    assert len(run_dirs) == 1

    run_meta = json.loads((run_dirs[0] / "run_meta.json").read_text(encoding="utf-8"))
    assert run_meta["target_level_px"] == 88.0
    assert run_meta["target_meniscus_row"] == 19
    assert run_meta["tolerance_px"] == 5.0

    model._analysis_context = _sample_context(mono=50.0)
    model.update_ui_with_analysis("orig", "ann", 88.5, 20)
    analysis_lines = (run_dirs[0] / "analysis.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(line)["kind"] == "refuel_level_sample" for line in analysis_lines)

    capture_files = list((run_dirs[0] / "captures").iterdir())
    assert capture_files

    model.sample_trace = [
        {"elapsed_s": 0.0, "monotonic_s": 1.0, "level_px": 88.0, "phase": "live"},
        {"elapsed_s": 0.5, "monotonic_s": 1.5, "level_px": 88.0, "phase": "live"},
        {"elapsed_s": 1.0, "monotonic_s": 2.0, "level_px": 88.0, "phase": "live"},
        {"elapsed_s": 1.5, "monotonic_s": 2.5, "level_px": 88.0, "phase": "live"},
        {"elapsed_s": 2.0, "monotonic_s": 3.0, "level_px": 88.0, "phase": "live"},
    ]
    assert model.begin_burst(5, 3, 1000, 20)["ok"] is True
    model.mark_burst_wait_complete(_sample_context(mono=10.0))
    for mono, level in ((10.1, 90.0), (10.2, 91.0), (10.3, 90.0)):
        model._analysis_context = _sample_context(mono=mono)
        image = np.zeros((12, 12, 3), dtype=np.uint8)
        model.update_ui_with_analysis(image, image.copy(), level, 20)

    capture_files = list((run_dirs[0] / "captures").iterdir())
    assert len(capture_files) >= 2


def test_refuel_camera_model_record_mode_off_does_not_create_run(tmp_path):
    owner = _owner_model(tmp_path, record_mode=False)
    model = RefuelCameraModel(owner)
    model.current_level = 77.0
    model.last_meniscus_row = 14
    model.original_image = np.zeros((8, 8, 3), dtype=np.uint8)

    ok, _ = model.lock_current_as_target(5)

    assert ok is True
    run_root = Path(tmp_path) / "calibration_recordings" / "RefuelBalanceCalibrationProcess"
    assert run_root.exists() is False
