import json
from pathlib import Path

import numpy as np
import pytest

from tools.annotate_refuel_dataset import (
    InteractiveRefuelAnnotator,
    RefuelDatasetAnnotationSession,
    build_label_record,
    compute_derived,
    display_line_to_raw,
    display_point_to_raw,
    raw_line_to_display,
    raw_point_to_display,
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


class _KeyEvent:
    def __init__(self, key):
        self.key = key


class _ClickEvent:
    def __init__(self, point, inaxes):
        self.xdata = point[0]
        self.ydata = point[1]
        self.inaxes = inaxes


def _make_test_annotator(session, frame_id="frame_000001"):
    annotator = InteractiveRefuelAnnotator(session)
    annotator.index = annotator.frame_ids.index(frame_id)
    annotator.raw_shape = [20, 30, 3]
    annotator.ax = object()
    annotator.proposed = session.propose_interactive_label(frame_id)
    annotator._render = lambda: None
    return annotator


def _click_raw_point(annotator, raw_point):
    display_point = raw_point_to_display(raw_point, annotator.raw_shape)
    annotator._on_click(_ClickEvent(display_point, annotator.ax))


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


def test_annotation_coordinate_transform_round_trips_non_square_image():
    raw_shape = [20, 30, 3]

    for point in ([0, 0], [29, 0], [0, 19], [29, 19], [13, 7]):
        display_point = raw_point_to_display(point, raw_shape)
        assert display_point_to_raw(display_point, raw_shape) == point


def test_raw_line_to_display_rotates_existing_raw_label():
    raw_shape = [20, 30, 3]
    raw_line = [[10, 2], [10, 18]]

    display_line = raw_line_to_display(raw_line, raw_shape)

    assert display_line == [[2, 19], [18, 19]]
    assert display_line_to_raw(display_line, raw_shape) == raw_line


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


def test_interactive_proposal_omits_seed_but_copies_scene_geometry(tmp_path):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")

    proposed = session.propose_interactive_label("frame_000002")

    assert proposed["status"] == "visible"
    assert proposed["channel_geometry"] is None
    assert proposed["meniscus_line"] is None

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

    proposed = session.propose_interactive_label("frame_000002")

    assert proposed["geometry_source"] == "copied_scene"
    assert proposed["channel_geometry"]["left_wall"] == [[11, 3], [11, 17]]
    assert proposed["meniscus_line"] is None


def test_interactive_key_handling_changes_mode_without_points(tmp_path):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")
    annotator = _make_test_annotator(session)

    annotator._on_key(_KeyEvent("g"))

    assert annotator.mode == "geometry"
    assert annotator.pending_points == []

    annotator._on_key(_KeyEvent("m"))

    assert annotator.mode == "meniscus"
    assert annotator.pending_points == []


def test_interactive_title_reserves_status_line(tmp_path):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")
    annotator = _make_test_annotator(session)

    annotator.status_message = ""
    idle_title = annotator._build_title("frame_000001", "scene_001")
    annotator.status_message = "Saved frame_000001 as visible."
    saved_title = annotator._build_title("frame_000002", "scene_001")

    assert len(idle_title.splitlines()) == len(saved_title.splitlines()) == 4
    assert idle_title.splitlines()[-1] == " "
    assert saved_title.splitlines()[-1] == "Saved frame_000001 as visible."


def test_interactive_click_ignores_points_outside_drawing_modes(tmp_path):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")
    annotator = _make_test_annotator(session)

    _click_raw_point(annotator, [11, 3])

    assert annotator.pending_points == []
    assert annotator.proposed["channel_geometry"] is None


def test_interactive_geometry_mode_converts_display_clicks_to_raw_geometry(tmp_path):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")
    annotator = _make_test_annotator(session)
    raw_points = [
        [11, 3],
        [19, 3],
        [19, 17],
        [11, 17],
    ]

    annotator._on_key(_KeyEvent("g"))
    for point in raw_points:
        _click_raw_point(annotator, point)

    assert annotator.mode == "meniscus"
    assert annotator.proposed["geometry_source"] == "adjusted"
    assert annotator.proposed["channel_geometry"] == {
        "left_wall": [[11, 3], [11, 17]],
        "right_wall": [[19, 3], [19, 17]],
        "top_line": [[11, 3], [19, 3]],
        "bottom_line": [[11, 17], [19, 17]],
    }
    assert annotator.proposed["meniscus_line"] is None


def test_interactive_meniscus_mode_converts_display_clicks_to_raw_line(tmp_path):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")
    annotator = _make_test_annotator(session)

    annotator._on_key(_KeyEvent("m"))
    _click_raw_point(annotator, [11, 10])
    _click_raw_point(annotator, [19, 10])

    assert annotator.mode is None
    assert annotator.proposed["status"] == "visible"
    assert annotator.proposed["meniscus_line"] == [[11, 10], [19, 10]]


def test_interactive_clear_meniscus_key_removes_existing_line(tmp_path):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")
    annotator = _make_test_annotator(session)
    annotator.proposed["meniscus_line"] = [[11, 10], [19, 10]]
    annotator.mode = "meniscus"
    annotator.pending_points = [[11, 10]]

    annotator._on_key(_KeyEvent("x"))

    assert annotator.proposed["meniscus_line"] is None
    assert annotator.mode is None
    assert annotator.pending_points == []
    assert "Meniscus cleared" in annotator.status_message


def test_interactive_repairing_visible_geometry_requires_fresh_meniscus(tmp_path):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")
    old_label = build_label_record(
        frame_id="frame_000001",
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
    session.save_label(old_label)
    annotator = _make_test_annotator(session)
    annotator._load_current_frame = lambda message="", start_mode=None: None
    geometry_points = [
        [11, 3],
        [19, 3],
        [19, 17],
        [11, 17],
    ]

    annotator._on_key(_KeyEvent("g"))
    for point in geometry_points:
        _click_raw_point(annotator, point)

    assert annotator.index == 0
    assert annotator.mode == "meniscus"
    assert annotator.proposed["meniscus_line"] is None
    assert session.labels_by_frame["frame_000001"]["channel_geometry"]["left_wall"] == [[10, 2], [10, 18]]


@pytest.mark.parametrize(("key", "status"), [("5", "bad_frame"), ("6", "skip")])
def test_interactive_bad_frame_and_skip_save_without_geometry(tmp_path, key, status):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")
    annotator = _make_test_annotator(session)
    annotator._load_current_frame = lambda message="", start_mode=None: None

    annotator._on_key(_KeyEvent(key))

    assert annotator.index == 1
    assert session.labels_by_frame["frame_000001"]["status"] == status
    assert session.labels_by_frame["frame_000001"]["channel_geometry"] is None


def test_interactive_auto_saves_and_advances_after_complete_visible_label(tmp_path):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")
    annotator = _make_test_annotator(session)
    annotator._load_current_frame = lambda message="", start_mode=None: None
    geometry_points = [
        [11, 3],
        [19, 3],
        [19, 17],
        [11, 17],
    ]

    annotator._on_key(_KeyEvent("g"))
    for point in geometry_points:
        _click_raw_point(annotator, point)
    annotator._on_key(_KeyEvent("m"))
    _click_raw_point(annotator, [11, 10])
    _click_raw_point(annotator, [19, 10])

    assert annotator.index == 1
    saved = session.labels_by_frame["frame_000001"]
    assert saved["status"] == "visible"
    assert saved["meniscus_line"] == [[11, 10], [19, 10]]
    assert saved["derived"]["level_from_bottom_px"] == 7.0


def test_interactive_visible_save_primes_next_frame_meniscus_mode(tmp_path):
    run_dir = _make_run(tmp_path)
    session = RefuelDatasetAnnotationSession(run_dir, annotator_id="annotator_a")
    annotator = _make_test_annotator(session)
    annotator._load_image = lambda _frame_id: np.zeros((20, 30, 3), dtype=np.uint8)
    geometry_points = [
        [11, 3],
        [19, 3],
        [19, 17],
        [11, 17],
    ]

    annotator._on_key(_KeyEvent("g"))
    for point in geometry_points:
        _click_raw_point(annotator, point)
    annotator._on_key(_KeyEvent("m"))
    _click_raw_point(annotator, [11, 10])
    _click_raw_point(annotator, [19, 10])

    assert annotator.index == 1
    assert annotator.mode == "meniscus"
    assert annotator.pending_points == []
    assert annotator.proposed["frame_id"] == "frame_000002"
    assert annotator.proposed["channel_geometry"]["left_wall"] == [[11, 3], [11, 17]]
