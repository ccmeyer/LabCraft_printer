import json
from pathlib import Path

from tools.annotate_refuel_dataset import (
    RefuelDatasetAnnotationSession,
    build_label_record,
    compute_derived,
)


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _make_run(tmp_path: Path):
    run_dir = tmp_path / "calibration_recordings" / "RefuelLevelDatasetCaptureProcess" / "run_20260321_120000_deadbeef"
    captures = run_dir / "captures"
    captures.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_meta.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_dir.name,
                "process_name": "RefuelLevelDatasetCaptureProcess",
                "phase_name": "refuel_level_dataset_capture",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        run_dir / "scenes.jsonl",
        [
            {
                "schema_version": 1,
                "scene_id": "scene_001",
                "scene_index": 1,
                "started_at_utc": "2026-03-21T10:00:00Z",
                "ended_at_utc": "2026-03-21T10:05:00Z",
                "purpose": "nominal_static",
                "geometry_expected_static": True,
                "scene_tags": [],
                "notes": "",
                "machine_context": {"location": "camera"},
                "camera_context": {"camera_profile_name": "RefuelCamera"},
            }
        ],
    )
    _write_jsonl(
        run_dir / "frames.jsonl",
        [
            {
                "schema_version": 1,
                "frame_id": "frame_000001",
                "scene_id": "scene_001",
                "capture_id": "cap_000001",
                "capture_index": 1,
                "image_relpath": "captures/cap_000001_raw.png",
                "captured_at_utc": "2026-03-21T10:00:00Z",
                "raw_image_shape": [20, 30, 3],
                "frame_kind": "single",
                "sequence_id": "",
                "sequence_index": 1,
                "sequence_length": 1,
                "frame_tags": [],
                "notes": "",
                "machine_context": {"location": "camera"},
                "camera_context": {"camera_profile_name": "RefuelCamera"},
                "rejected": False,
            },
            {
                "schema_version": 1,
                "frame_id": "frame_000002",
                "scene_id": "scene_001",
                "capture_id": "cap_000002",
                "capture_index": 2,
                "image_relpath": "captures/cap_000002_raw.png",
                "captured_at_utc": "2026-03-21T10:00:01Z",
                "raw_image_shape": [20, 30, 3],
                "frame_kind": "single",
                "sequence_id": "",
                "sequence_index": 1,
                "sequence_length": 1,
                "frame_tags": [],
                "notes": "",
                "machine_context": {"location": "camera"},
                "camera_context": {"camera_profile_name": "RefuelCamera"},
                "rejected": False,
            },
        ],
    )
    _write_jsonl(
        run_dir / "analysis.jsonl",
        [
            {
                "schema_version": 1,
                "frame_id": "frame_000002",
                "predicted_status": "visible",
                "predicted_channel_geometry": {
                    "left_wall": [[10, 2], [10, 18]],
                    "right_wall": [[18, 2], [18, 18]],
                    "top_line": [[10, 2], [18, 2]],
                    "bottom_line": [[10, 18], [18, 18]],
                },
                "predicted_meniscus_line": [[10, 9], [18, 9]],
                "predicted_level_px": 9.0,
                "confidence": 0.8,
            }
        ],
    )
    _write_jsonl(run_dir / "labels.jsonl", [])
    _write_jsonl(run_dir / "events.jsonl", [])
    (captures / "cap_000001_raw.png").write_bytes(b"stub")
    (captures / "cap_000002_raw.png").write_bytes(b"stub")
    return run_dir


def test_compute_derived_returns_bottom_relative_level():
    derived = compute_derived(
        {
            "left_wall": [[10, 2], [10, 18]],
            "right_wall": [[18, 2], [18, 18]],
            "top_line": [[10, 2], [18, 2]],
            "bottom_line": [[10, 18], [18, 18]],
        },
        [[10, 9], [18, 9]],
    )

    assert derived["channel_center_x_px"] == 14.0
    assert derived["meniscus_y_px"] == 9.0
    assert derived["channel_bottom_y_px"] == 18.0
    assert derived["level_from_bottom_px"] == 9.0


def test_annotation_session_proposes_copied_scene_geometry(tmp_path):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")
    first = build_label_record(
        frame_id="frame_000001",
        scene_id="scene_001",
        annotator_id="annotator_a",
        status="visible",
        channel_geometry={
            "left_wall": [[11, 3], [11, 17]],
            "right_wall": [[19, 3], [19, 17]],
            "top_line": [[11, 3], [19, 3]],
            "bottom_line": [[11, 17], [19, 17]],
        },
        meniscus_line=[[11, 10], [19, 10]],
    )
    session.save_label(first)

    proposed = session.propose_label("frame_000002")

    assert proposed["geometry_source"] == "copied_scene"
    assert proposed["channel_geometry"]["left_wall"] == [[11, 3], [11, 17]]


def test_annotation_session_save_label_writes_labels_and_event(tmp_path):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")
    label = build_label_record(
        frame_id="frame_000002",
        scene_id="scene_001",
        annotator_id="annotator_a",
        status="visible",
        channel_geometry={
            "left_wall": [[10, 2], [10, 18]],
            "right_wall": [[18, 2], [18, 18]],
            "top_line": [[10, 2], [18, 2]],
            "bottom_line": [[10, 18], [18, 18]],
        },
        meniscus_line=[[10, 9], [18, 9]],
    )

    saved = session.save_label(label)

    labels = [json.loads(line) for line in (run_dir / "labels.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert saved["derived"]["level_from_bottom_px"] == 9.0
    assert len(labels) == 1
    assert labels[0]["frame_id"] == "frame_000002"
    assert events[-1]["event_type"] == "annotation_completed"
    assert events[-1]["payload"]["frame_id"] == "frame_000002"


def test_annotation_session_handles_missing_analysis_seed(tmp_path):
    run_dir = _make_run(tmp_path)
    (run_dir / "analysis.jsonl").write_text("", encoding="utf-8")
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")

    proposed = session.propose_label("frame_000002")

    assert proposed["status"] == "skip"
    assert proposed["channel_geometry"] is None
