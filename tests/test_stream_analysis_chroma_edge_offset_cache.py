from pathlib import Path

import numpy as np

from tools.stream_analysis import online_chroma_edge_offset_cache as mod


def _synthetic_frame_analysis(*, run_dir: Path | None = None) -> dict:
    frame_color = np.full((6, 24, 3), 240, dtype=np.uint8)
    gray = np.full((6, 24), 240, dtype=np.uint8)

    y_px = 3
    edge_pixels = {
        9: np.asarray([210, 170, 120], dtype=np.uint8),
        10: np.asarray([200, 160, 115], dtype=np.uint8),
        13: np.asarray([200, 160, 115], dtype=np.uint8),
        14: np.asarray([210, 170, 120], dtype=np.uint8),
    }
    sample_pixels = {
        8: np.asarray([220, 185, 145], dtype=np.uint8),
        7: np.asarray([225, 190, 150], dtype=np.uint8),
        6: np.asarray([230, 195, 155], dtype=np.uint8),
        15: np.asarray([220, 185, 145], dtype=np.uint8),
        16: np.asarray([225, 190, 150], dtype=np.uint8),
        17: np.asarray([230, 195, 155], dtype=np.uint8),
    }
    for x_px, pixel in {**edge_pixels, **sample_pixels}.items():
        frame_color[y_px, x_px] = pixel

    gray[y_px, 9] = 132
    gray[y_px, 10] = 130
    gray[y_px, 13] = 130
    gray[y_px, 14] = 132
    gray[y_px, 8] = 145
    gray[y_px, 7] = 152
    gray[y_px, 6] = 158
    gray[y_px, 15] = 145
    gray[y_px, 16] = 152
    gray[y_px, 17] = 158

    attached_mask = np.zeros((4, 12), dtype=np.uint8)
    attached_mask[2, 3:9] = 255

    return {
        "run_dir": run_dir or Path("run_001"),
        "capture_id": "cap_000001",
        "capture_index": 1,
        "delay_us": 5350,
        "delay_from_emergence_us": 650,
        "frame_color": frame_color,
        "gray": gray,
        "threshold_value": 140,
        "roi": {"x0": 6, "y0": 1, "x1": 18, "y1": 5, "width": 12, "height": 4},
        "attached_mask": attached_mask,
        "attached_edge_rows": [
            {
                "y_px": y_px,
                "x_left_px": 9,
                "x_right_px": 14,
                "width_px": 6,
                "center_x_px": 11.5,
            }
        ],
        "current_attached_volume_nl": 12.5,
        "current_total_visible_volume_nl": 13.0,
        "detached_visible_volume_nl": 0.5,
        "image_path": Path("captures/cap_000001.jpg"),
    }


def test_extract_row_side_offset_features_captures_offsets_through_three_pixels():
    frame_analysis = _synthetic_frame_analysis()

    rows = mod._extract_row_side_offset_features(frame_analysis, max_offset_px=3)

    assert len(rows) == 6
    assert {int(row["sample_offset_px"]) for row in rows} == {1, 2, 3}
    assert {str(row["side"]) for row in rows} == {"left", "right"}

    left_offset_3 = next(
        row
        for row in rows
        if str(row["side"]) == "left" and int(row["sample_offset_px"]) == 3
    )
    right_offset_2 = next(
        row
        for row in rows
        if str(row["side"]) == "right" and int(row["sample_offset_px"]) == 2
    )

    assert left_offset_3["sample_x_px"] == 6
    assert left_offset_3["sample_is_excluded"] is True
    assert left_offset_3["intermediate_pixels_all_excluded"] is True
    assert left_offset_3["intermediate_excluded_count"] == 3
    assert left_offset_3["gray_headroom"] == 18.0
    assert left_offset_3["contiguous_to_attached_mask"] is True
    assert left_offset_3["sample_lab_chroma"] is not None
    assert left_offset_3["delta_lab_chroma"] is not None

    assert right_offset_2["sample_x_px"] == 16
    assert right_offset_2["gray_headroom"] == 12.0
    assert right_offset_2["sample_bg_gap"] == 35.0


def test_export_online_chroma_edge_offset_cache_writes_run_artifacts(tmp_path, monkeypatch):
    experiment_root = tmp_path / "experiment"
    run_dir = experiment_root / "calibration_recordings" / "OnlineStreamCalibrationProcess" / "run_001"
    run_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mod.dataset_mod, "resolve_experiment_root", lambda root: Path(root).resolve())
    monkeypatch.setattr(
        mod.report_mod,
        "_metadata_rows",
        lambda _experiment_root: [
            {
                "Dataset name": "run_001",
                "Capture Process": mod.report_mod.PROCESS_NAME,
                "Print Pressure": 1.0,
                "Print PW": 3500,
                "Rep": 2,
                "Mass/print": 0.071,
            }
        ],
    )
    monkeypatch.setattr(
        mod.report_mod,
        "_run_dir_for_row",
        lambda _experiment_root, _metadata_row: run_dir,
    )
    monkeypatch.setattr(
        mod.report_mod,
        "_load_json",
        lambda path: {"analysis_config": {"min_component_area_px": 10}} if path.name == "plan_snapshot.json" else {},
    )
    monkeypatch.setattr(
        mod.report_mod,
        "_iter_jsonl",
        lambda _path: [
            {
                "capture_id": "cap_000001",
                "capture_index": 1,
                "delay_us": 5350,
                "image_ref": {
                    "capture_id": "cap_000001",
                    "capture_index": 1,
                    "image_relpath": "captures/cap_000001.jpg",
                },
                "phase": "flow_rate",
                "status": "accepted",
            }
        ],
    )
    monkeypatch.setattr(
        mod.report_mod,
        "_resolve_online_stream_correction_context",
        lambda *_args, **_kwargs: {
            "run_id": "run_001",
            "emergence_time_us": 4700,
            "nozzle_center_px": [180, 110],
            "selected_rule": dict(mod.proto_mod.SELECTED_V2_RULE),
        },
    )
    monkeypatch.setattr(
        mod.proto_mod,
        "_frame_analysis_from_capture",
        lambda **kwargs: _synthetic_frame_analysis(run_dir=kwargs.get("run_dir")),
    )

    output_root = experiment_root / "analysis" / "cache_test"
    payload = mod.export_online_chroma_edge_offset_cache(
        experiment_root,
        print_pressure=1.0,
        max_offset_px=3,
        output_root=output_root,
    )

    assert payload["analysis"] == "online_chroma_edge_offset_cache"
    assert payload["run_count"] == 1
    assert payload["frame_count"] == 1
    assert payload["edge_row_count"] == 1
    assert payload["feature_row_count"] == 6
    assert Path(payload["cache_manifest_json"]).exists()
    assert Path(payload["paths"]["run_summary_csv"]).exists()

    run_entry = payload["runs"][0]
    run_manifest = Path(run_entry["run_manifest_json"])
    feature_csv = Path(run_entry["paths"]["row_side_offset_features_csv"])
    edge_csv = Path(run_entry["paths"]["baseline_edge_rows_csv"])
    frame_csv = Path(run_entry["paths"]["frame_summary_csv"])

    assert run_manifest.exists()
    assert feature_csv.exists()
    assert edge_csv.exists()
    assert frame_csv.exists()

    feature_lines = feature_csv.read_text(encoding="utf-8").splitlines()
    assert "sample_offset_px" in feature_lines[0]
    assert any(",3," in line for line in feature_lines[1:])
