import csv
import json
import math
from pathlib import Path

import pytest

from tools import evaluate_refuel_detector as evaluator
from tools.annotate_refuel_dataset import build_label_record


RAW_SHAPE = [20, 30, 3]
GEOMETRY = {
    "left_wall": [[25, 2], [5, 2]],
    "right_wall": [[25, 18], [5, 18]],
    "top_line": [[25, 2], [25, 18]],
    "bottom_line": [[5, 2], [5, 18]],
}


def _geometry_with_display_x(left_x, right_x):
    return {
        "left_wall": [[25, left_x], [5, left_x]],
        "right_wall": [[25, right_x], [5, right_x]],
        "top_line": [[25, left_x], [25, right_x]],
        "bottom_line": [[5, left_x], [5, right_x]],
    }


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _overlay_deps():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    if not hasattr(cv2, "imwrite") or not hasattr(cv2, "imread") or not hasattr(np, "zeros"):
        pytest.skip("functional cv2 and numpy are required for overlay tests")
    return cv2, np


def _visible_label(frame_id, scene_id, meniscus_line, geometry=None):
    return build_label_record(
        frame_id=frame_id,
        scene_id=scene_id,
        annotator_id="annotator_a",
        status="visible",
        channel_geometry=geometry or GEOMETRY,
        meniscus_line=meniscus_line,
    )


def _state_label(frame_id, scene_id, status):
    return build_label_record(
        frame_id=frame_id,
        scene_id=scene_id,
        annotator_id="annotator_a",
        status=status,
        channel_geometry=GEOMETRY,
    )


def _seed(frame_id, status, meniscus_line=None, geometry=None):
    payload = {
        "schema_version": 1,
        "kind": "refuel_dataset_seed",
        "frame_id": frame_id,
        "predicted_status": status,
        "predicted_channel_geometry": geometry or GEOMETRY,
        "predicted_meniscus_line": meniscus_line,
        "predicted_level_px": None,
        "confidence": 0.8 if status == "visible" else 0.35,
    }
    return payload


def _make_frame(frame_id, scene_id, capture_index, *, rejected=False):
    return {
        "schema_version": 1,
        "frame_id": frame_id,
        "scene_id": scene_id,
        "capture_id": f"cap_{capture_index:06d}",
        "capture_index": capture_index,
        "image_relpath": f"captures/cap_{capture_index:06d}_raw.png",
        "captured_at_utc": "2026-03-21T10:00:00Z",
        "raw_image_shape": RAW_SHAPE,
        "frame_kind": "single",
        "sequence_id": "",
        "sequence_index": 1,
        "sequence_length": 1,
        "frame_tags": [],
        "notes": "",
        "machine_context": {"location": "camera"},
        "camera_context": {"camera_profile_name": "RefuelCamera"},
        "rejected": rejected,
    }


def _make_run(tmp_path):
    run_dir = tmp_path / "run_20260524_eval"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_meta.json").write_text(
        json.dumps({"schema_version": 1, "run_id": run_dir.name}),
        encoding="utf-8",
    )
    _write_jsonl(
        run_dir / "scenes.jsonl",
        [
            {
                "schema_version": 1,
                "scene_id": "scene_001",
                "scene_index": 1,
                "scene_tags": ["centered"],
            },
            {
                "schema_version": 1,
                "scene_id": "scene_002",
                "scene_index": 2,
                "scene_tags": ["offset"],
            },
        ],
    )
    frames = [
        _make_frame("frame_000001", "scene_001", 1),
        _make_frame("frame_000002", "scene_001", 2),
        _make_frame("frame_000003", "scene_001", 3),
        _make_frame("frame_000004", "scene_002", 4),
        _make_frame("frame_000005", "scene_002", 5),
        _make_frame("frame_000006", "scene_002", 6, rejected=True),
    ]
    _write_jsonl(run_dir / "frames.jsonl", frames)
    _write_jsonl(
        run_dir / "labels.jsonl",
        [
            _visible_label("frame_000001", "scene_001", [[20, 1], [10, 18]]),
            _visible_label("frame_000002", "scene_001", [[12, 1], [8, 18]]),
            _state_label("frame_000003", "scene_001", "empty"),
            _state_label("frame_000004", "scene_002", "full"),
            _visible_label("frame_000005", "scene_002", [[14, 1], [14, 18]]),
            _visible_label("frame_000006", "scene_002", [[16, 1], [16, 18]]),
        ],
    )
    _write_jsonl(
        run_dir / "analysis.jsonl",
        [
            _seed("frame_000001", "visible", [[18, 0], [8, 19]]),
            _seed("frame_000002", "visible", [[15, 0], [11, 19]]),
            _seed("frame_000003", "full"),
            _seed("frame_000005", "not_found"),
            _seed("frame_000006", "visible", [[12, 0], [12, 19]]),
        ],
    )
    return run_dir


def _write_run_images(run_dir: Path):
    cv2, np = _overlay_deps()
    frames = []
    with (run_dir / "frames.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            frames.append(json.loads(line))
    for index, frame in enumerate(frames):
        image_path = run_dir / frame["image_relpath"]
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image = np.zeros((RAW_SHAPE[0], RAW_SHAPE[1], RAW_SHAPE[2]), dtype=np.uint8)
        image[:, :, 0] = 30 + index * 10
        image[:, :, 1] = 45
        image[:, :, 2] = 60
        assert cv2.imwrite(str(image_path), image)


def _assert_color_close(pixel, expected, tolerance=35):
    assert all(
        abs(int(actual) - int(wanted)) <= tolerance
        for actual, wanted in zip(pixel, expected)
    )


def _build_debug_analysis_view(meniscus_row=60):
    _cv2, np = _overlay_deps()
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    x, y, w, h = 200, 80, 120, 180
    left_offset = 40
    channel_width = 20
    image[y : y + h, x : x + w] = 160
    x0 = x + left_offset
    channel = image[y : y + h, x0 : x0 + channel_width]
    channel[:meniscus_row] = 40
    channel[meniscus_row:] = 220
    image[y : y + h, x0 + channel_width + 5 : x0 + 2 * channel_width + 5] = 220
    return image


def _debug_raw_frame(meniscus_row=60):
    cv2, _np = _overlay_deps()
    return cv2.rotate(_build_debug_analysis_view(meniscus_row), cv2.ROTATE_90_CLOCKWISE)


def _make_debug_run(tmp_path):
    cv2, _np = _overlay_deps()
    from CalibrationClasses.Model import RefuelCameraModel

    run_dir = tmp_path / "run_20260524_debug"
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_frame = _debug_raw_frame(meniscus_row=60)
    image_relpath = "captures/cap_000001_raw.png"
    image_path = run_dir / image_relpath
    image_path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(image_path), raw_frame)

    model = RefuelCameraModel()
    model.update_analysis_parameters(40, 20, 80, 4, 0.25)
    seed = model.build_dataset_analysis_seed(raw_frame)
    assert seed is not None
    seed["details"]["analysis_parameters"] = {
        "offset": 40,
        "width": 20,
        "threshold": 80,
        "prominence": 4,
        "empty_cutoff": 0.25,
    }

    (run_dir / "run_meta.json").write_text(
        json.dumps({"schema_version": 1, "run_id": run_dir.name}),
        encoding="utf-8",
    )
    _write_jsonl(
        run_dir / "scenes.jsonl",
        [{"schema_version": 1, "scene_id": "scene_001", "scene_index": 1, "scene_tags": ["debug"]}],
    )
    frame = {
        **_make_frame("frame_000001", "scene_001", 1),
        "image_relpath": image_relpath,
        "raw_image_shape": list(raw_frame.shape),
    }
    _write_jsonl(run_dir / "frames.jsonl", [frame])
    _write_jsonl(
        run_dir / "labels.jsonl",
        [
            _visible_label(
                "frame_000001",
                "scene_001",
                seed["predicted_meniscus_line"],
                geometry=seed["predicted_channel_geometry"],
            )
        ],
    )
    _write_jsonl(
        run_dir / "analysis.jsonl",
        [
            {
                "kind": "refuel_dataset_seed",
                "frame_id": "frame_000001",
                "capture_id": "cap_000001",
                "capture_index": 1,
                "image_relpath": image_relpath,
                **seed,
            }
        ],
    )
    return run_dir


def test_label_meniscus_measurement_averages_display_y_and_ignores_x():
    frame = {"raw_image_shape": RAW_SHAPE}
    label = _visible_label("frame_000001", "scene_001", [[20, 1], [10, 18]])

    measured = evaluator.label_measurements(label, frame)

    assert measured["meniscus_y_px"] == 14.0
    assert measured["level_from_bottom_px"] == 10.0


def test_prediction_meniscus_measurement_uses_same_display_y_average():
    frame = {"raw_image_shape": RAW_SHAPE}
    seed = _seed("frame_000001", "visible", [[18, 0], [8, 19]])

    measured = evaluator.prediction_measurements(seed, frame)

    assert measured["meniscus_y_px"] == 16.0
    assert measured["level_from_bottom_px"] == 8.0


def test_frame_metric_reports_signed_channel_x_errors():
    frame = _make_frame("frame_000001", "scene_001", 1)
    label_geometry = _geometry_with_display_x(2, 18)
    pred_geometry = _geometry_with_display_x(0, 14)
    label = _visible_label(
        "frame_000001",
        "scene_001",
        [[20, 1], [10, 18]],
        geometry=label_geometry,
    )
    seed = _seed(
        "frame_000001",
        "visible",
        [[18, 0], [8, 19]],
        geometry=pred_geometry,
    )

    row = evaluator._frame_metric(frame, None, label, seed)

    assert row["label_channel_left_x_px"] == pytest.approx(2.0)
    assert row["label_channel_right_x_px"] == pytest.approx(18.0)
    assert row["label_channel_center_x_px"] == pytest.approx(10.0)
    assert row["predicted_channel_left_x_px"] == pytest.approx(0.0)
    assert row["predicted_channel_right_x_px"] == pytest.approx(14.0)
    assert row["predicted_channel_center_x_px"] == pytest.approx(7.0)
    assert row["channel_left_dx_px"] == pytest.approx(-2.0)
    assert row["channel_right_dx_px"] == pytest.approx(-4.0)
    assert row["channel_center_dx_px"] == pytest.approx(-3.0)
    assert row["channel_center_abs_error_px"] == pytest.approx(3.0)
    assert row["channel_width_error_px"] == pytest.approx(-2.0)


def test_evaluation_confusion_matrix_includes_not_found_and_missing_prediction(tmp_path):
    run_dir = _make_run(tmp_path)

    result = evaluator.evaluate_refuel_run(run_dir)

    assert result["summary"]["prediction_source"] == "saved"
    assert result["confusion_matrix"]["visible"]["visible"] == 2
    assert result["confusion_matrix"]["visible"]["not_found"] == 1
    assert result["confusion_matrix"]["empty"]["full"] == 1
    assert result["confusion_matrix"]["full"]["missing_prediction"] == 1
    assert result["summary"]["status_accuracy"] == pytest.approx(2 / 5)


def test_visible_meniscus_summary_uses_predicted_visible_frames(tmp_path):
    run_dir = _make_run(tmp_path)

    result = evaluator.evaluate_refuel_run(run_dir)
    summary = result["summary"]["meniscus_y_error_px"]

    assert summary["count"] == 2
    assert summary["mae"] == pytest.approx(2.5)
    assert summary["median_abs_error"] == pytest.approx(2.5)
    assert summary["rmse"] == pytest.approx(math.sqrt(6.5))
    assert summary["p90_abs_error"] == pytest.approx(3.0)
    assert summary["max_abs_error"] == pytest.approx(3.0)


def test_channel_x_error_summary_is_reported_by_dataset_and_scene(tmp_path):
    run_dir = _make_run(tmp_path)
    shifted = _seed(
        "frame_000001",
        "visible",
        [[18, 0], [8, 19]],
        geometry=_geometry_with_display_x(0, 14),
    )
    rows = []
    for line in (run_dir / "analysis.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("frame_id") == "frame_000001":
            row.update(shifted)
        rows.append(row)
    _write_jsonl(run_dir / "analysis.jsonl", rows)

    result = evaluator.evaluate_refuel_run(run_dir)
    channel = result["summary"]["channel_x_error_px"]
    scene_channel = result["scenes"]["scene_001"]["channel_x_error_px"]

    assert channel["channel_center_dx_px"]["count"] == 4
    assert channel["channel_center_dx_px"]["mean_error"] == pytest.approx(-0.75)
    assert channel["channel_center_dx_px"]["max_abs_error"] == pytest.approx(3.0)
    assert channel["channel_width_error_px"]["max_abs_error"] == pytest.approx(2.0)
    assert scene_channel["channel_center_dx_px"]["max_abs_error"] == pytest.approx(3.0)


def test_rejected_frames_are_skipped_by_default_and_can_be_included(tmp_path):
    run_dir = _make_run(tmp_path)

    default_result = evaluator.evaluate_refuel_run(run_dir)
    included_result = evaluator.evaluate_refuel_run(run_dir, include_rejected=True)

    assert default_result["summary"]["evaluated_frame_count"] == 5
    assert default_result["summary"]["skipped_rejected_count"] == 1
    assert all(row["frame_id"] != "frame_000006" for row in default_result["frame_metrics"])
    assert included_result["summary"]["evaluated_frame_count"] == 6
    assert any(row["frame_id"] == "frame_000006" for row in included_result["frame_metrics"])


def test_cli_writes_json_and_csv_outputs(tmp_path, capsys):
    run_dir = _make_run(tmp_path)
    json_out = tmp_path / "report.json"
    csv_out = tmp_path / "frame_metrics.csv"

    rc = evaluator.main([
        str(run_dir),
        "--json-out",
        str(json_out),
        "--csv-out",
        str(csv_out),
        "--worst",
        "2",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Refuel Detector Evaluation" in captured.out
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert report["summary"]["prediction_source"] == "saved"
    assert report["summary"]["evaluated_frame_count"] == 5
    with csv_out.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 5
    assert rows[0]["prediction_source"] == "saved"
    assert rows[0]["frame_id"] == "frame_000001"
    assert rows[0]["meniscus_abs_error_px"] == "2.0"
    assert "channel_center_dx_px" in rows[0]
    assert "channel_width_error_px" in rows[0]


def test_prediction_source_rerun_ignores_stale_saved_seed(tmp_path, monkeypatch):
    cv2, _np = _overlay_deps()
    run_dir = _make_debug_run(tmp_path)
    loaded = evaluator.load_refuel_evaluation_run(run_dir)
    good_seed = loaded["analysis_by_frame"]["frame_000001"]
    stale_seed = {
        **good_seed,
        "predicted_status": "empty",
        "predicted_meniscus_line": None,
        "predicted_level_px": 3.0,
        "details": {
            **(good_seed.get("details") or {}),
            "last_row": 105,
        },
    }
    _write_jsonl(
        run_dir / "analysis.jsonl",
        [
            {
                "kind": "refuel_dataset_seed",
                "frame_id": "frame_000001",
                **stale_seed,
            }
        ],
    )

    seen_last_rows = []
    real_rerun = evaluator.rerun_refuel_detector_prediction

    def _spy_rerun(*args, **kwargs):
        seen_last_rows.append(kwargs.get("last_row"))
        return real_rerun(*args, **kwargs)

    monkeypatch.setattr(evaluator, "rerun_refuel_detector_prediction", _spy_rerun)
    saved = evaluator.evaluate_refuel_run(run_dir, prediction_source="saved")
    rerun = evaluator.evaluate_refuel_run(run_dir, prediction_source="rerun")
    raw_image = cv2.imread(str(run_dir / "captures/cap_000001_raw.png"), cv2.IMREAD_COLOR)
    rerun_seed = real_rerun(
        raw_image,
        params={"offset": 40, "width": 20, "threshold": 80, "prominence": 4, "empty_cutoff": 0.25},
    )["seed"]

    assert saved["frame_metrics"][0]["prediction_source"] == "saved"
    assert saved["frame_metrics"][0]["predicted_status"] == "empty"
    assert rerun["summary"]["prediction_source"] == "rerun"
    assert rerun["frame_metrics"][0]["prediction_source"] == "rerun"
    assert rerun["frame_metrics"][0]["predicted_status"] == "visible"
    assert rerun["frame_metrics"][0]["meniscus_abs_error_px"] == pytest.approx(0.0, abs=1.0)
    assert seen_last_rows == [None]
    assert rerun_seed["details"]["analysis_parameters"]["bottom_guard_px"] == 2


def test_cli_prediction_source_both_writes_both_reports_json_and_csv(tmp_path, capsys):
    run_dir = _make_run(tmp_path)
    _write_run_images(run_dir)
    json_out = tmp_path / "both_report.json"
    csv_out = tmp_path / "both_metrics.csv"

    rc = evaluator.main([
        str(run_dir),
        "--prediction-source",
        "both",
        "--json-out",
        str(json_out),
        "--csv-out",
        str(csv_out),
        "--worst",
        "1",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Prediction Source: saved" in captured.out
    assert "Prediction Source: rerun" in captured.out
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert report["prediction_source"] == "both"
    assert set(report["sources"]) == {"saved", "rerun"}
    with csv_out.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 10
    assert {row["prediction_source"] for row in rows} == {"saved", "rerun"}


def test_overlay_draws_scalar_meniscus_lines_across_channel_width():
    _cv2, np = _overlay_deps()
    raw_image = np.zeros((RAW_SHAPE[0], RAW_SHAPE[1], RAW_SHAPE[2]), dtype=np.uint8)
    frame = _make_frame("frame_overlay", "scene_001", 1)
    label = _visible_label("frame_overlay", "scene_001", [[20, 9], [10, 10]])
    seed = _seed("frame_overlay", "visible", [[18, 3], [8, 4]])
    metric = {
        "frame_id": "frame_overlay",
        "scene_id": "scene_001",
        "label_status": "visible",
        "predicted_status": "visible",
        "label_meniscus_y_px": 14.0,
        "predicted_meniscus_y_px": 16.0,
        "meniscus_abs_error_px": 2.0,
    }

    overlay = evaluator.draw_refuel_evaluation_overlay(
        raw_image,
        frame,
        label=label,
        seed=seed,
        metric=metric,
        category="test",
    )

    assert overlay.shape[:2] == (RAW_SHAPE[1], RAW_SHAPE[0])
    _assert_color_close(overlay[14, 2], evaluator.LABEL_MENISCUS_COLOR_BGR)
    _assert_color_close(overlay[14, 18], evaluator.LABEL_MENISCUS_COLOR_BGR)
    _assert_color_close(overlay[16, 2], evaluator.PREDICTED_MENISCUS_COLOR_BGR)
    _assert_color_close(overlay[16, 18], evaluator.PREDICTED_MENISCUS_COLOR_BGR)


def test_select_overlay_frames_includes_failure_categories(tmp_path):
    run_dir = _make_run(tmp_path)
    result = evaluator.evaluate_refuel_run(run_dir)

    selected = evaluator.select_overlay_frames(result, worst_overlay_count=5, overlay_all=True)

    worst_ids = [row["frame_id"] for row in selected["worst_meniscus_errors"]]
    mismatch_ids = [row["frame_id"] for row in selected["status_mismatches"]]
    per_scene_ids = [row["frame_id"] for row in selected["per_scene_worst"]]
    channel_ids = [row["frame_id"] for row in selected["worst_channel_geometry_errors"]]
    all_ids = [row["frame_id"] for row in selected["all_evaluated_frames"]]
    assert worst_ids[:2] == ["frame_000002", "frame_000001"]
    assert {"frame_000003", "frame_000004", "frame_000005"}.issubset(set(mismatch_ids))
    assert "frame_000002" in per_scene_ids
    assert "worst_channel_geometry_errors" in selected
    assert channel_ids
    assert all_ids == [row["frame_id"] for row in result["frame_metrics"]]


def test_cli_writes_overlay_artifacts(tmp_path, capsys):
    cv2, _np = _overlay_deps()
    run_dir = _make_run(tmp_path)
    _write_run_images(run_dir)
    overlay_dir = tmp_path / "overlays"

    rc = evaluator.main([
        str(run_dir),
        "--overlay-dir",
        str(overlay_dir),
        "--worst-overlay-count",
        "5",
        "--contact-sheet-cols",
        "2",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Overlay artifacts:" in captured.out
    manifest_path = overlay_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frame_ids = [entry["frame_id"] for entry in manifest["frames"]]
    assert len(frame_ids) == len(set(frame_ids))
    assert "frame_000002" in frame_ids
    assert "frame_000005" in frame_ids
    for sheet_relpath in manifest["contact_sheets"].values():
        assert (overlay_dir / sheet_relpath).exists()
    overlay_path = overlay_dir / "frames" / "frame_000002_overlay.png"
    assert overlay_path.exists()
    overlay_image = cv2.imread(str(overlay_path), cv2.IMREAD_COLOR)
    assert overlay_image is not None
    assert int(overlay_image.max()) > 0


def test_rerun_refuel_detector_debug_matches_seed_on_synthetic_visible_frame(tmp_path):
    cv2, _np = _overlay_deps()
    run_dir = _make_debug_run(tmp_path)
    result = evaluator.evaluate_refuel_run(run_dir)
    frame_metric = result["frame_metrics"][0]
    seed = evaluator.load_refuel_evaluation_run(run_dir)["analysis_by_frame"]["frame_000001"]
    raw_image = cv2.imread(str(run_dir / "captures/cap_000001_raw.png"), cv2.IMREAD_COLOR)

    rerun = evaluator.rerun_refuel_detector_debug(
        raw_image,
        seed["details"]["analysis_parameters"],
        last_row=None,
    )
    rerun_metric = evaluator._frame_metric(
        evaluator.load_refuel_evaluation_run(run_dir)["frames"][0],
        None,
        evaluator.load_refuel_evaluation_run(run_dir)["labels"][0],
        rerun["seed"],
    )

    assert rerun["seed"]["predicted_status"] == "visible"
    assert rerun["seed"]["detector_version"] == "phase2_offline_rerun_v7_aspect_preserving_640"
    assert rerun["debug_details"]["analysis_preprocessing_mode"] == "aspect_preserving_long_side_640"
    assert rerun["debug_details"]["analysis_image_shape"] == [480, 640, 3]
    assert rerun["debug_details"]["kept_contour_count"] >= 1
    assert rerun["debug_details"]["selected_peak_row"] is not None
    assert rerun["debug_details"]["best_peak_row"] is not None
    assert rerun["debug_details"]["merged_head_bbox"] is not None
    assert rerun["debug_details"]["head_bottom_reason"] in {"merged_bbox_bottom", "led_separator"}
    assert "channel_wall_peaks" in rerun["debug_details"]
    assert "channel_wall_pair_candidates" in rerun["debug_details"]
    assert "channel_wall_profile_parameters" in rerun["debug_details"]
    assert "head_closed_mask" in rerun["debug_artifacts"]
    assert "top_tie_eligible_rows" in rerun["debug_details"]
    assert "tracking_eligible_rows" in rerun["debug_details"]
    assert "fill_state_reason" in rerun["debug_details"]
    assert "profile" in rerun["debug_artifacts"]
    assert rerun_metric["predicted_meniscus_y_px"] == pytest.approx(frame_metric["predicted_meniscus_y_px"])


def test_cli_writes_detector_debug_artifacts_and_debug_all(tmp_path, capsys):
    cv2, _np = _overlay_deps()
    run_dir = _make_run(tmp_path)
    _write_run_images(run_dir)
    debug_dir = tmp_path / "debug_artifacts"

    rc = evaluator.main([
        str(run_dir),
        "--debug-dir",
        str(debug_dir),
        "--debug-count",
        "5",
        "--debug-all",
        "--contact-sheet-cols",
        "2",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Detector debug artifacts:" in captured.out
    manifest = json.loads((debug_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["parameters"]["debug_all"] is True
    assert len(manifest["frames"]) == 5
    assert len({entry["frame_id"] for entry in manifest["frames"]}) == 5
    assert "all_evaluated_frames" in manifest["categories"]
    assert (debug_dir / "frame_debug.jsonl").exists()
    debug_rows = [
        json.loads(line)
        for line in (debug_dir / "frame_debug.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(debug_rows) == 5
    assert all("debug_details" in row for row in debug_rows)
    for sheet_relpath in manifest["contact_sheets"].values():
        assert (debug_dir / sheet_relpath).exists()
    panel_path = debug_dir / "frames" / f"{manifest['frames'][0]['frame_id']}_steps.png"
    panel_image = cv2.imread(str(panel_path), cv2.IMREAD_COLOR)
    assert panel_image is not None
    assert int(panel_image.max()) > 0


def test_cli_prediction_source_both_splits_overlay_and_debug_artifacts(tmp_path, capsys):
    run_dir = _make_run(tmp_path)
    _write_run_images(run_dir)
    analysis_rows = [
        json.loads(line)
        for line in (run_dir / "analysis.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for row in analysis_rows:
        row["details"] = {**(row.get("details") or {}), "last_row": 77}
    _write_jsonl(run_dir / "analysis.jsonl", analysis_rows)
    overlay_dir = tmp_path / "both_overlays"
    debug_dir = tmp_path / "both_debug"

    rc = evaluator.main([
        str(run_dir),
        "--prediction-source",
        "both",
        "--overlay-dir",
        str(overlay_dir),
        "--debug-dir",
        str(debug_dir),
        "--overlay-all",
        "--debug-all",
        "--worst-overlay-count",
        "2",
        "--debug-count",
        "2",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Overlay artifacts (saved):" in captured.out
    assert "Overlay artifacts (rerun):" in captured.out
    assert "Detector debug artifacts (saved):" in captured.out
    assert "Detector debug artifacts (rerun):" in captured.out
    for source in ("saved", "rerun"):
        assert (overlay_dir / source / "manifest.json").exists()
        assert (debug_dir / source / "manifest.json").exists()
        assert (debug_dir / source / "frame_debug.jsonl").exists()
        rows = [
            json.loads(line)
            for line in (debug_dir / source / "frame_debug.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert all(row["debug_details"].get("last_row") is None for row in rows)


def test_detector_debug_projects_manual_scalar_height_into_channel_row(tmp_path):
    cv2, _np = _overlay_deps()
    run_dir = _make_debug_run(tmp_path)
    result = evaluator.evaluate_refuel_run(run_dir)
    loaded = evaluator.load_refuel_evaluation_run(run_dir)
    frame = loaded["frames"][0]
    seed = loaded["analysis_by_frame"]["frame_000001"]
    raw_image = cv2.imread(str(run_dir / "captures/cap_000001_raw.png"), cv2.IMREAD_COLOR)
    rerun = evaluator.rerun_refuel_detector_debug(raw_image, seed["details"]["analysis_parameters"])

    projected = evaluator._project_label_y_to_channel_row(
        result["frame_metrics"][0]["label_meniscus_y_px"],
        frame,
        rerun["debug_details"],
    )

    assert projected == pytest.approx(rerun["debug_details"]["meniscus_row"], abs=1.0)
