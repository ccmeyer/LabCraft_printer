from __future__ import annotations

import csv
import json
from pathlib import Path

from tools.stream_analysis import annotations as mod
from tools.stream_analysis import nozzle as nozzle_mod
from tests.test_stream_analysis_nozzle import _make_nozzle_experiment


def _export_predictions(exp_dir: Path, output_root: Path):
    return nozzle_mod.export_stage2_nozzle(
        exp_dir,
        output_root=output_root,
        sample_count=4,
        search_width_frac=0.30,
        search_top_frac=0.08,
        search_bottom_frac=0.34,
        shift_threshold_px=3.0,
        confidence_threshold=0.48,
    )


def test_build_annotation_queue_links_frames_and_stage2_predictions(tmp_path):
    exp_dir, run_dir = _make_nozzle_experiment(tmp_path)
    output_root = tmp_path / "analysis" / "stream_characterization"
    _export_predictions(exp_dir, output_root)

    payload = mod.build_annotation_queue(exp_dir, output_root=output_root)

    assert payload["selected_run_ids"] == [run_dir.name]
    assert len(payload["queue"]) == 6
    first = payload["queue"][0]
    assert first["frame_key"] == f"{run_dir.name}:0001"
    assert Path(str(first["image_abs_path"])).exists()
    assert first["predicted_x_px"] is not None
    assert first["predicted_y_px"] is not None
    assert first["search_x1"] > first["search_x0"]
    assert first["search_y1"] > first["search_y0"]


def test_seed_annotation_precedence_prefers_previous_frame_then_predictions_then_roi():
    queue = [
        {
            "frame_key": "run_a:0001",
            "run_id": "run_a",
            "capture_index": 1,
            "search_x0": 100,
            "search_x1": 140,
            "search_y0": 40,
            "search_y1": 80,
            "tracked_prediction_x_px": 123.0,
            "tracked_prediction_y_px": 51.0,
            "tracked_prediction_mode": "visible_nozzle_line",
            "raw_prediction_x_px": 120.0,
            "raw_prediction_y_px": 49.0,
            "raw_prediction_mode": "attached_core_separation",
        },
        {
            "frame_key": "run_a:0002",
            "run_id": "run_a",
            "capture_index": 2,
            "search_x0": 100,
            "search_x1": 140,
            "search_y0": 40,
            "search_y1": 80,
            "tracked_prediction_x_px": None,
            "tracked_prediction_y_px": None,
            "tracked_prediction_mode": None,
            "raw_prediction_x_px": 121.0,
            "raw_prediction_y_px": 52.0,
            "raw_prediction_mode": "attached_core_separation",
        },
        {
            "frame_key": "run_b:0001",
            "run_id": "run_b",
            "capture_index": 1,
            "search_x0": 10,
            "search_x1": 30,
            "search_y0": 60,
            "search_y1": 100,
            "tracked_prediction_x_px": None,
            "tracked_prediction_y_px": None,
            "tracked_prediction_mode": None,
            "raw_prediction_x_px": 22.0,
            "raw_prediction_y_px": 77.0,
            "raw_prediction_mode": "attached_core_separation",
        },
        {
            "frame_key": "run_c:0001",
            "run_id": "run_c",
            "capture_index": 1,
            "search_x0": 200,
            "search_x1": 260,
            "search_y0": 80,
            "search_y1": 140,
            "tracked_prediction_x_px": None,
            "tracked_prediction_y_px": None,
            "tracked_prediction_mode": None,
            "raw_prediction_x_px": None,
            "raw_prediction_y_px": None,
            "raw_prediction_mode": None,
        },
    ]

    first_seed = mod.seed_annotation_for_queue_index(queue, 0, {})
    assert first_seed["source"] == "tracked_prediction"
    assert first_seed["x_px"] == 123.0
    assert first_seed["mode"] == "visible_nozzle_line"

    annotations_by_key = {
        "run_a:0001": {
            "annotated_nozzle_x_px": 130.0,
            "annotated_nozzle_y_px": 58.0,
            "annotation_mode": "attached_black_droplet_center",
        }
    }
    second_seed = mod.seed_annotation_for_queue_index(queue, 1, annotations_by_key)
    assert second_seed["source"] == "previous_annotation"
    assert second_seed["x_px"] == 130.0
    assert second_seed["mode"] == "attached_black_droplet_center"

    raw_seed = mod.seed_annotation_for_queue_index(queue, 2, {})
    assert raw_seed["source"] == "raw_prediction"
    assert raw_seed["x_px"] == 22.0
    assert raw_seed["mode"] == "attached_core_separation"

    roi_seed = mod.seed_annotation_for_queue_index(queue, 3, {})
    assert roi_seed["source"] == "search_roi_center"
    assert roi_seed["x_px"] == 230.0
    assert roi_seed["y_px"] == 110.0
    assert roi_seed["mode"] == "manual_other"


def test_only_nozzle_is_supported_annotation_mode():
    assert "only_nozzle" in mod.ANNOTATION_MODES
    assert mod._normalize_prediction_mode("only_nozzle") == "only_nozzle"


def test_save_nozzle_annotation_writes_canonical_files_and_state(tmp_path):
    exp_dir, _run_dir = _make_nozzle_experiment(tmp_path)
    output_root = tmp_path / "analysis" / "stream_characterization"
    _export_predictions(exp_dir, output_root)
    queue_payload = mod.build_annotation_queue(exp_dir, output_root=output_root)
    annotations_by_key = {}
    seed = mod.seed_annotation_for_queue_index(queue_payload["queue"], 0, annotations_by_key)

    row = mod.save_nozzle_annotation(
        experiment_root=exp_dir,
        output_root=output_root,
        queue=queue_payload["queue"],
        annotations_by_key=annotations_by_key,
        queue_index=0,
        seed=seed,
        marker_x_px=seed["x_px"] + 2.0,
        marker_y_px=seed["y_px"] + 1.0,
        annotation_mode="attached_black_droplet_center",
        session_id="session_abc",
        show_prediction=True,
        zoom_half_width=90,
    )

    paths = mod.annotation_paths(exp_dir, output_root=output_root)
    assert Path(paths["annotations_csv"]).exists()
    assert Path(paths["events_jsonl"]).exists()
    assert Path(paths["state_json"]).exists()
    assert Path(paths["manifest_json"]).exists()
    assert row["frame_key"] in mod.load_nozzle_annotations(exp_dir, output_root=output_root)

    with Path(paths["annotations_csv"]).open("r", encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 1
    assert csv_rows[0]["session_id"] == "session_abc"
    assert float(csv_rows[0]["annotated_nozzle_x_px"]) == seed["x_px"] + 2.0

    event_rows = [json.loads(line) for line in Path(paths["events_jsonl"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(event_rows) == 1
    assert event_rows[0]["event_type"] == "annotation_saved"

    state = json.loads(Path(paths["state_json"]).read_text(encoding="utf-8"))
    assert state["current_frame_key"] == row["frame_key"]
    assert state["last_saved_frame_key"] == row["frame_key"]

    manifest = json.loads(Path(paths["manifest_json"]).read_text(encoding="utf-8"))
    assert manifest["summary"]["annotated_frame_count"] == 1
    assert manifest["selected_run_ids"]


def test_resolve_annotation_start_index_prefers_explicit_target_over_resume_state():
    queue = [
        {"frame_key": "run_a:0001", "run_id": "run_a", "capture_index": 1},
        {"frame_key": "run_a:0002", "run_id": "run_a", "capture_index": 2},
        {"frame_key": "run_b:0001", "run_id": "run_b", "capture_index": 1},
    ]

    assert mod.resolve_annotation_start_index(queue, state={"current_frame_key": "run_a:0002"}, resume=True) == 1
    assert mod.resolve_annotation_start_index(
        queue,
        state={"current_frame_key": "run_a:0002"},
        resume=True,
        start_run_id="run_b",
        start_frame_index=1,
    ) == 2


def test_evaluate_nozzle_annotations_writes_metrics_and_worst_frame_overlays(tmp_path):
    exp_dir, _run_dir = _make_nozzle_experiment(tmp_path)
    output_root = tmp_path / "analysis" / "stream_characterization"
    _export_predictions(exp_dir, output_root)
    queue_payload = mod.build_annotation_queue(exp_dir, output_root=output_root)
    annotations_by_key = {}

    for queue_index in [0, 1]:
        seed = mod.seed_annotation_for_queue_index(queue_payload["queue"], queue_index, annotations_by_key)
        mod.save_nozzle_annotation(
            experiment_root=exp_dir,
            output_root=output_root,
            queue=queue_payload["queue"],
            annotations_by_key=annotations_by_key,
            queue_index=queue_index,
            seed=seed,
            marker_x_px=seed["x_px"] + 3.0,
            marker_y_px=seed["y_px"] + 4.0,
            annotation_mode="attached_black_droplet_center" if queue_index == 0 else "attached_core_separation",
            session_id="session_eval",
            show_prediction=True,
            zoom_half_width=90,
        )

    payload = mod.evaluate_nozzle_annotations(
        exp_dir,
        output_root=output_root,
        limit_worst_frames=2,
    )

    paths = mod.annotation_paths(exp_dir, output_root=output_root)
    assert payload["annotation_row_count"] == 2
    assert payload["matched_prediction_count"] == 2
    assert Path(paths["evaluation_csv"]).exists()
    assert Path(paths["evaluation_json"]).exists()
    assert payload["worst_frame_count"] >= 1

    with Path(paths["evaluation_csv"]).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert all(row["distance_px"] for row in rows)

    worst_frames = list(Path(paths["worst_frames_dir"]).glob("*.png"))
    assert worst_frames


def test_evaluate_nozzle_annotations_reports_only_nozzle_separately(tmp_path):
    exp_dir, _run_dir = _make_nozzle_experiment(tmp_path)
    output_root = tmp_path / "analysis" / "stream_characterization"
    _export_predictions(exp_dir, output_root)
    queue_payload = mod.build_annotation_queue(exp_dir, output_root=output_root)
    annotations_by_key = {}

    for queue_index, annotation_mode in [(0, "attached_black_droplet_center"), (4, "only_nozzle")]:
        seed = mod.seed_annotation_for_queue_index(queue_payload["queue"], queue_index, annotations_by_key)
        mod.save_nozzle_annotation(
            experiment_root=exp_dir,
            output_root=output_root,
            queue=queue_payload["queue"],
            annotations_by_key=annotations_by_key,
            queue_index=queue_index,
            seed=seed,
            marker_x_px=seed["x_px"],
            marker_y_px=seed["y_px"],
            annotation_mode=annotation_mode,
            session_id="session_eval_modes",
            show_prediction=True,
            zoom_half_width=90,
        )

    payload = mod.evaluate_nozzle_annotations(exp_dir, output_root=output_root, limit_worst_frames=1)

    assert "only_nozzle" in payload["per_mode_summary"]
    assert "attached_black_droplet_center" in payload["per_mode_summary"]


def test_diagnose_nozzle_candidates_writes_candidate_report_and_overlays(tmp_path):
    exp_dir, _run_dir = _make_nozzle_experiment(tmp_path)
    output_root = tmp_path / "analysis" / "stream_characterization"
    _export_predictions(exp_dir, output_root)
    queue_payload = mod.build_annotation_queue(exp_dir, output_root=output_root)
    annotations_by_key = {}

    for queue_index, annotation_mode in [(0, "attached_black_droplet_center"), (2, "attached_core_separation"), (4, "only_nozzle")]:
        seed = mod.seed_annotation_for_queue_index(queue_payload["queue"], queue_index, annotations_by_key)
        mod.save_nozzle_annotation(
            experiment_root=exp_dir,
            output_root=output_root,
            queue=queue_payload["queue"],
            annotations_by_key=annotations_by_key,
            queue_index=queue_index,
            seed=seed,
            marker_x_px=seed["x_px"],
            marker_y_px=seed["y_px"],
            annotation_mode=annotation_mode,
            session_id="session_diag",
            show_prediction=True,
            zoom_half_width=90,
        )

    payload = mod.diagnose_nozzle_candidates(
        exp_dir,
        output_root=output_root,
        limit_worst_frames=2,
    )

    paths = mod.annotation_paths(exp_dir, output_root=output_root)
    assert Path(paths["diagnostics_csv"]).exists()
    assert Path(paths["diagnostics_json"]).exists()
    assert payload["diagnostic_row_count"] == 3
    assert "attached_black_droplet_center" in payload["candidate_summaries"]
    assert "only_nozzle" in payload["candidate_summaries"]

    with Path(paths["diagnostics_csv"]).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert "best_candidate_name" in rows[0]
    assert list(Path(paths["candidate_overlays_root"]).rglob("*.png"))
