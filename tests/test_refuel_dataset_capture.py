import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import RefuelCameraModel


def _owner_model(tmp_path):
    calibration_manager = SimpleNamespace(
        get_record_mode_enabled=lambda: True,
        _build_recorder_meta=lambda: {
            "stock_solution": "water",
            "printer_head_id": "ph-001",
        },
    )
    experiment_model = SimpleNamespace(experiment_dir_path=str(tmp_path))
    return SimpleNamespace(
        calibration_manager=calibration_manager,
        experiment_model=experiment_model,
    )


def _build_analysis_view(
    *,
    head_rect=(200, 80, 120, 180),
    left_offset=40,
    channel_width=20,
    meniscus_row=60,
):
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    x, y, w, h = head_rect
    image[y : y + h, x : x + w] = 160
    x0 = x + left_offset
    channel = image[y : y + h, x0 : x0 + channel_width]
    channel[:meniscus_row] = 40
    channel[meniscus_row:] = 220
    ref_x0 = x0 + channel_width + 5
    image[y : y + h, ref_x0 : ref_x0 + channel_width] = 220
    return image


def _thread_input_from_analysis_view(image):
    return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)


def test_refuel_dataset_session_start_writes_run_layout(tmp_path):
    model = RefuelCameraModel(_owner_model(tmp_path))

    run_dir = Path(
        model.start_dataset_session(
            operator_id="operator_a",
            notes="collecting nominal dataset",
            camera_profile_name="RefuelCamera",
            default_sequence_length=7,
            default_sequence_interval_ms=250,
        )
    )

    assert run_dir.exists()
    assert (run_dir / "run_meta.json").exists()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "scenes.jsonl").exists()
    assert (run_dir / "frames.jsonl").exists()
    assert (run_dir / "analysis.jsonl").exists()
    assert (run_dir / "labels.jsonl").exists()

    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["process_name"] == "RefuelLevelDatasetCaptureProcess"
    assert meta["phase_name"] == "refuel_level_dataset_capture"
    assert meta["operator_id"] == "operator_a"
    assert meta["notes"] == "collecting nominal dataset"
    assert meta["default_sequence_length"] == 7
    assert meta["default_sequence_interval_ms"] == 250
    assert meta["image_format"] == "png"
    assert meta["raw_only"] is True


def test_refuel_dataset_scene_and_frame_capture_write_jsonl_and_png(tmp_path):
    model = RefuelCameraModel(_owner_model(tmp_path))
    run_dir = Path(model.start_dataset_session(operator_id="operator_a"))
    scene = model.start_dataset_scene(
        purpose="nominal_static",
        scene_tags=["head_recentered", "head_recentered"],
        notes="scene note",
        machine_context={"location": "camera"},
        camera_context={"camera_profile_name": "RefuelCamera"},
    )

    analysis_view = _build_analysis_view()
    raw_frame = _thread_input_from_analysis_view(analysis_view)
    single = model.capture_dataset_frame(
        raw_frame,
        frame_kind="single",
        sequence_index=1,
        sequence_length=1,
        frame_tags=["good", "good"],
        notes="single note",
        machine_context={"location": "camera"},
        camera_context={"camera_profile_name": "RefuelCamera"},
    )
    sequence = model.capture_dataset_frame(
        raw_frame,
        frame_kind="sequence",
        sequence_id="seq_001",
        sequence_index=2,
        sequence_length=5,
        frame_tags=["temporal"],
        notes="sequence note",
        machine_context={"location": "camera"},
        camera_context={"camera_profile_name": "RefuelCamera"},
    )

    scenes = [json.loads(line) for line in (run_dir / "scenes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    frames = [json.loads(line) for line in (run_dir / "frames.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    analysis_rows = [json.loads(line) for line in (run_dir / "analysis.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(scenes) == 1
    assert scenes[0]["scene_id"] == scene["scene_id"]
    assert scenes[0]["purpose"] == "nominal_static"
    assert scenes[0]["scene_tags"] == ["head_recentered"]

    assert len(frames) == 2
    assert frames[0]["frame_kind"] == "single"
    assert frames[1]["frame_kind"] == "sequence"
    assert frames[1]["sequence_id"] == "seq_001"
    assert single["image_relpath"].endswith(".png")
    assert sequence["image_relpath"].endswith(".png")

    saved = cv2.cvtColor(cv2.imread(str(run_dir / single["image_relpath"])), cv2.COLOR_BGR2RGB)
    assert saved.shape == raw_frame.shape
    assert np.array_equal(saved, raw_frame)

    assert analysis_rows
    assert analysis_rows[0]["kind"] == "refuel_dataset_seed"
    assert analysis_rows[0]["frame_id"] == single["frame_id"]
    assert analysis_rows[0]["predicted_status"] == "visible"


def test_refuel_dataset_reject_last_marks_frame_and_removes_from_accepted_set(tmp_path):
    model = RefuelCameraModel(_owner_model(tmp_path))
    run_dir = Path(model.start_dataset_session(operator_id="operator_a"))
    model.start_dataset_scene(
        purpose="stress",
        scene_tags=["glare_setup"],
        machine_context={"location": "camera"},
        camera_context={"camera_profile_name": "RefuelCamera"},
    )

    frame = np.zeros((16, 12, 3), dtype=np.uint8)
    model.capture_dataset_frame(
        frame,
        frame_kind="single",
        frame_tags=["glare"],
        machine_context={"location": "camera"},
        camera_context={"camera_profile_name": "RefuelCamera"},
    )

    evt = model.reject_last_dataset_capture(reason="bad glare")

    assert evt is not None
    assert model.get_dataset_frame_records(accepted_only=True) == []
    frames = [json.loads(line) for line in (run_dir / "frames.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert frames[0]["rejected"] is True
    assert frames[0]["reject_reason"] == "bad glare"


def test_refuel_dataset_session_end_finalizes_run_meta(tmp_path):
    model = RefuelCameraModel(_owner_model(tmp_path))
    run_dir = Path(model.start_dataset_session(operator_id="operator_a"))
    model.start_dataset_scene(
        purpose="temporal",
        scene_tags=["bubble_present"],
        machine_context={"location": "camera"},
        camera_context={"camera_profile_name": "RefuelCamera"},
    )

    ended = model.end_dataset_session()

    assert Path(ended) == run_dir
    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["outcome"] == "completed"
    assert meta["ended_at_utc"] is not None
