import csv
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from tools.stream_analysis import dataset as dataset_mod
from tools.stream_analysis import online_halo_debug_frame as mod
from tools.stream_analysis import online_report as report_mod


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _write_metadata_csv(exp_dir: Path, rows):
    fieldnames = [
        "Dataset name",
        "Print PW",
        "Print Pressure",
        "Rep",
        "Mass/print",
        "Num printed",
        "Capture Process",
    ]
    path = exp_dir / dataset_mod.METADATA_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _make_halo_frame(width: int = 420, height: int = 520, *, x_center: int = 210, nozzle_y: int = 130):
    image = np.full((height, width, 3), 245, dtype=np.uint8)
    background = np.full_like(image, 245)

    cv2.rectangle(image, (x_center - 34, 28), (x_center + 34, 74), (90, 90, 90), thickness=-1)
    cv2.rectangle(image, (x_center - 8, 60), (x_center + 8, nozzle_y + 26), (30, 30, 30), thickness=-1)
    cv2.rectangle(image, (x_center - 16, nozzle_y + 20), (x_center + 16, nozzle_y + 122), (25, 25, 25), thickness=-1)
    cv2.ellipse(image, (x_center, nozzle_y + 146), (40, 54), 0.0, 0.0, 360.0, (25, 25, 25), thickness=-1)

    # Bottom of attached stream / top of detached bulb halo.
    cv2.ellipse(image, (x_center, nozzle_y + 122), (20, 10), 0.0, 200.0, 340.0, (40, 40, 150), thickness=2)
    cv2.ellipse(image, (x_center, nozzle_y + 126), (20, 10), 0.0, 20.0, 160.0, (150, 40, 40), thickness=2)

    # Detached contour halo with red top / blue bottom.
    cv2.ellipse(image, (x_center, nozzle_y + 146), (44, 58), 0.0, 185.0, 355.0, (40, 40, 150), thickness=3)
    cv2.ellipse(image, (x_center, nozzle_y + 146), (44, 58), 0.0, 5.0, 175.0, (150, 40, 40), thickness=3)
    return image, background


def _mask_and_image_for_orientation(orientation: str):
    bgr = np.full((180, 180, 3), 245, dtype=np.uint8)
    mask = np.zeros((180, 180), dtype=np.uint8)
    if orientation == "horizontal":
        cv2.rectangle(mask, (50, 60), (130, 130), 255, thickness=-1)
        cv2.line(bgr, (50, 57), (130, 57), (40, 40, 150), thickness=2)
    elif orientation == "vertical":
        cv2.rectangle(mask, (50, 60), (130, 130), 255, thickness=-1)
        cv2.line(bgr, (133, 60), (133, 130), (150, 40, 40), thickness=2)
    elif orientation == "diagonal":
        contour = np.asarray([[90, 30], [145, 90], [90, 145], [35, 90]], dtype=np.int32).reshape((-1, 1, 2))
        cv2.fillPoly(mask, [contour], 255)
        cv2.line(bgr, (93, 27), (148, 87), (40, 40, 150), thickness=2)
    else:
        raise ValueError(f"Unsupported orientation: {orientation}")
    robust_mask = cv2.erode(mask, np.ones((5, 5), dtype=np.uint8), iterations=1)
    contour = mod._mask_to_contour(mask)
    centroid = np.asarray([90.0, 95.0], dtype=np.float32)
    return bgr, mask, robust_mask, contour, centroid


def _build_experiment_layout(tmp_path: Path):
    experiment_root = tmp_path / "experiment"
    online_run_id = "run_20260415_115351_a8c665e4"
    emergence_run_id = "run_20260415_115349_emergence"
    online_run_dir = experiment_root / "calibration_recordings" / dataset_mod.ONLINE_STREAM_PROCESS_NAME / online_run_id
    emergence_run_dir = experiment_root / "calibration_recordings" / "DropletEmergenceCalibrationProcess" / emergence_run_id
    captures_dir = online_run_dir / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    emergence_run_dir.mkdir(parents=True, exist_ok=True)

    frame_image, background_image = _make_halo_frame()
    frame_path = captures_dir / "cap_000014_flow_frame.jpg"
    background_path = captures_dir / "cap_000001_background.jpg"
    cv2.imwrite(str(frame_path), frame_image)
    cv2.imwrite(str(background_path), background_image)

    _write_metadata_csv(
        experiment_root,
        [
            {
                "Dataset name": online_run_id,
                "Print PW": 2500,
                "Print Pressure": 0.74,
                "Rep": 1,
                "Mass/print": 0.036,
                "Num printed": 1,
                "Capture Process": dataset_mod.ONLINE_STREAM_PROCESS_NAME,
            }
        ],
    )
    _write_jsonl(
        experiment_root / dataset_mod.STREAM_CAPTURE_LOG_FILENAME,
        [
            {
                "dataset_run_id": online_run_id,
                "child_processes": [
                    {
                        "process_name": "DropletEmergenceCalibrationProcess",
                        "run_id": emergence_run_id,
                    }
                ],
            }
        ],
    )
    _write_jsonl(
        emergence_run_dir / "analysis.jsonl",
        [
            {
                "kind": "calibration_data_updated",
                "payload": {
                    "result": {
                        "selected_center_px": [210, 130],
                        "flash_delay": 4700,
                    }
                },
            }
        ],
    )
    (online_run_dir / "plan_snapshot.json").write_text(
        json.dumps(
            {
                "analysis_config": {},
                "condition": {"emergence_time_us": 4700},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        online_run_dir / "frames.jsonl",
        [
            {
                "phase": "flow_rate",
                "status": "accepted",
                "delay_us": 6550,
                "flash_delay_us": 6550,
                "capture_index": 14,
                "image_ref": {
                    "capture_id": "cap_000014",
                    "capture_index": 14,
                    "image_relpath": "captures/cap_000014_flow_frame.jpg",
                    "subtract_background_image_relpath": "captures/cap_000001_background.jpg",
                    "delay_us": 6550,
                },
            }
        ],
    )
    return experiment_root, online_run_id, "cap_000014"


def test_load_frame_context_matches_report_resolution(tmp_path):
    experiment_root, run_id, capture_id = _build_experiment_layout(tmp_path)
    run_dir = experiment_root / "calibration_recordings" / dataset_mod.ONLINE_STREAM_PROCESS_NAME / run_id
    plan_snapshot = report_mod._load_json(run_dir / "plan_snapshot.json")

    context = mod._load_frame_context(experiment_root, run_id, capture_id)
    expected = report_mod._resolve_online_stream_correction_context(
        experiment_root,
        run_dir,
        plan_snapshot=plan_snapshot,
        correction_cache={},
    )

    assert context["delay_us"] == 6550
    assert context["image_path"].name == "cap_000014_flow_frame.jpg"
    assert context["background_path"].name == "cap_000001_background.jpg"
    assert context["emergence_time_us"] == expected["emergence_time_us"]
    assert context["nozzle_center_px"] == expected["nozzle_center_px"]


def test_candidate_regions_cover_detached_top_and_bottom_caps():
    bgr, mask, robust_mask, contour, centroid = _mask_and_image_for_orientation("horizontal")
    config = mod._resolved_config(
        {
            "min_arc_point_count": 3,
            "candidate_min_window_px": 8.0,
            "detached_cap_window_frac": 0.12,
        }
    )
    result = mod._detect_suspicious_arcs(
        component_kind="detached",
        contour=contour,
        mask=mask,
        robust_mask=robust_mask,
        centroid=centroid,
        bgr_frame=bgr,
        config=config,
    )

    region_labels = {str(arc["region_label"]) for arc in result["candidate_arcs"]}
    y_values = np.asarray(contour[:, 1], dtype=np.float32)
    y_min = float(np.min(y_values))
    y_max = float(np.max(y_values))
    cap_window_px = max(float(config["candidate_min_window_px"]), (y_max - y_min) * float(config["detached_cap_window_frac"]))

    assert region_labels == {"detached_top_cap", "detached_bottom_cap"}
    selected_indexes = sorted({int(index) for arc in result["candidate_arcs"] for index in arc["indexes"]})
    assert selected_indexes
    assert all(
        float(contour[index][1]) <= float(y_min + cap_window_px + 1.0)
        or float(contour[index][1]) >= float(y_max - cap_window_px - 1.0)
        for index in selected_indexes
    )


def test_candidate_regions_cover_only_attached_lower_boundary():
    bgr, mask, robust_mask, contour, centroid = _mask_and_image_for_orientation("horizontal")
    config = mod._resolved_config(
        {
            "min_arc_point_count": 3,
            "candidate_min_window_px": 8.0,
            "attached_lower_window_frac": 0.12,
        }
    )
    result = mod._detect_suspicious_arcs(
        component_kind="attached",
        contour=contour,
        mask=mask,
        robust_mask=robust_mask,
        centroid=centroid,
        bgr_frame=bgr,
        config=config,
    )

    region_labels = {str(arc["region_label"]) for arc in result["candidate_arcs"]}
    y_values = np.asarray(contour[:, 1], dtype=np.float32)
    y_min = float(np.min(y_values))
    y_max = float(np.max(y_values))
    lower_window_px = max(float(config["candidate_min_window_px"]), (y_max - y_min) * float(config["attached_lower_window_frac"]))

    assert region_labels == {"attached_lower_boundary"}
    selected_indexes = sorted({int(index) for arc in result["candidate_arcs"] for index in arc["indexes"]})
    assert selected_indexes
    assert all(float(contour[index][1]) >= float(y_max - lower_window_px - 1.0) for index in selected_indexes)
    assert all(float(result["normals"][index][1]) >= float(config["suspicious_min_vertical_normal"]) for index in selected_indexes)


def test_profile_gate_rejects_ambiguous_profile_without_directional_halo():
    profile_rows = [
        {"offset_px": -3, "signed_halo": 7.0, "halo_robust_gray": 100.0},
        {"offset_px": -2, "signed_halo": 8.0, "halo_robust_gray": 100.0},
        {"offset_px": -1, "signed_halo": 8.0, "halo_robust_gray": 101.0},
        {"offset_px": 0, "signed_halo": 9.0, "halo_robust_gray": 101.0},
        {"offset_px": 1, "signed_halo": 9.0, "halo_robust_gray": 101.0},
        {"offset_px": 2, "signed_halo": 10.0, "halo_robust_gray": 102.0},
        {"offset_px": 3, "signed_halo": 9.0, "halo_robust_gray": 102.0},
    ]
    shift, metrics = mod._profile_inward_shift(
        profile_rows,
        region_label="detached_bottom_cap",
        inward_offset_px=3.0,
        max_inward_shift_px=4,
        min_inside_signed_halo=16.0,
        min_outside_signed_halo=16.0,
        min_signed_halo_margin=6.0,
        min_transition=2.0,
    )

    assert shift == pytest.approx(0.0)
    assert metrics["valid"] is False


def test_profile_gate_accepts_directional_bottom_halo_without_mask_offset():
    profile_rows = [
        {"offset_px": -3, "signed_halo": 1.0, "halo_robust_gray": 45.0},
        {"offset_px": -2, "signed_halo": 2.0, "halo_robust_gray": 60.0},
        {"offset_px": -1, "signed_halo": 3.0, "halo_robust_gray": 85.0},
        {"offset_px": 0, "signed_halo": 18.0, "halo_robust_gray": 128.0},
        {"offset_px": 1, "signed_halo": 24.0, "halo_robust_gray": 176.0},
        {"offset_px": 2, "signed_halo": 28.0, "halo_robust_gray": 220.0},
        {"offset_px": 3, "signed_halo": 22.0, "halo_robust_gray": 245.0},
    ]
    shift, metrics = mod._profile_inward_shift(
        profile_rows,
        region_label="detached_bottom_cap",
        inward_offset_px=0.0,
        max_inward_shift_px=4,
        min_inside_signed_halo=16.0,
        min_outside_signed_halo=16.0,
        min_signed_halo_margin=6.0,
        min_transition=2.0,
    )

    assert metrics["valid"] is True
    assert shift > 0.0
    assert metrics["shift_from_peak_px"] > 0.0


def test_profile_gate_accepts_directional_top_halo_from_inside_signal():
    profile_rows = [
        {"offset_px": -4, "signed_halo": 30.0, "halo_robust_gray": 38.0},
        {"offset_px": -3, "signed_halo": 54.0, "halo_robust_gray": 55.0},
        {"offset_px": -2, "signed_halo": 88.0, "halo_robust_gray": 78.0},
        {"offset_px": -1, "signed_halo": 126.0, "halo_robust_gray": 104.0},
        {"offset_px": 0, "signed_halo": 44.0, "halo_robust_gray": 148.0},
        {"offset_px": 1, "signed_halo": 22.0, "halo_robust_gray": 190.0},
        {"offset_px": 2, "signed_halo": 10.0, "halo_robust_gray": 225.0},
    ]
    shift, metrics = mod._profile_inward_shift(
        profile_rows,
        region_label="detached_top_cap",
        inward_offset_px=0.0,
        max_inward_shift_px=4,
        min_inside_signed_halo=16.0,
        min_outside_signed_halo=16.0,
        min_signed_halo_margin=6.0,
        min_transition=2.0,
    )

    assert metrics["valid"] is True
    assert metrics["gate_mode"] == "inside"
    assert shift > 0.0


def test_component_correction_moves_inward_on_halo_segment_only():
    bgr = np.full((180, 180, 3), 245, dtype=np.uint8)
    mask = np.zeros((180, 180), dtype=np.uint8)
    cv2.rectangle(mask, (50, 60), (130, 130), 255, thickness=-1)
    cv2.line(bgr, (50, 133), (130, 133), (150, 40, 40), thickness=2)
    robust_mask = cv2.erode(mask, np.ones((5, 5), dtype=np.uint8), iterations=1)
    contour = mod._mask_to_contour(mask)
    centroid = np.asarray([90.0, 95.0], dtype=np.float32)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    halo_robust_gray = np.clip(
        gray.astype(np.float32) + (0.75 * np.abs(bgr[:, :, 2].astype(np.float32) - bgr[:, :, 0].astype(np.float32))),
        0.0,
        255.0,
    ).astype(np.uint8)
    config = mod._resolved_config(
        {
            "min_arc_point_count": 3,
            "boundary_band_radius_px": 3,
            "suspicious_signed_halo_min": 8.0,
            "profile_min_outside_signed_halo": 8.0,
        }
    )
    suspicious = mod._detect_suspicious_arcs(
        component_kind="detached",
        contour=contour,
        mask=mask,
        robust_mask=robust_mask,
        centroid=centroid,
        bgr_frame=bgr,
        config=config,
    )
    correction = mod._apply_component_correction(
        component_entry={
            "component": {"component_role": "detached", "component_rank": 1},
            "component_kind": "detached",
            "component_id": "detached_01",
            "contour": contour,
            "full_mask": mask,
            "edge_rows": [],
            "volume_nl": 0.0,
        },
        suspicious_debug=suspicious,
        bgr_frame=bgr,
        gray_frame=gray,
        halo_robust_gray=halo_robust_gray,
        roi={"x0": 0, "y0": 0, "x1": bgr.shape[1], "y1": bgr.shape[0]},
        frame_row={"run_id": "synthetic", "capture_id": "cap_000001", "capture_index": 1, "flash_delay_us": 1000},
        config=config,
    )

    assert correction["max_inward_shift_px"] > 0.0
    top_mean_y_before = float(np.mean([point[1] for point in contour if point[1] < centroid[1]]))
    top_mean_y_after = float(
        np.mean([point[1] for point in correction["corrected_contour"] if point[1] < centroid[1]])
    )
    bottom_mean_y_before = float(np.mean([point[1] for point in contour if point[1] > centroid[1]]))
    bottom_mean_y_after = float(
        np.mean([point[1] for point in correction["corrected_contour"] if point[1] > centroid[1]])
    )
    assert abs(top_mean_y_after - top_mean_y_before) < 1.0
    assert bottom_mean_y_after < bottom_mean_y_before


def test_export_online_halo_debug_bundle_writes_expected_artifacts(tmp_path):
    pytest.importorskip("matplotlib")

    experiment_root, run_id, capture_id = _build_experiment_layout(tmp_path)
    output_root = tmp_path / "halo_debug_bundle"
    payload = mod.export_online_halo_debug_bundle(
        experiment_root,
        run_id,
        capture_id,
        output_root=output_root,
    )

    assert payload["analysis"] == mod.ANALYSIS_NAME
    assert Path(payload["paths"]["bundle_manifest_json"]).exists()
    assert Path(payload["paths"]["frame_summary_json"]).exists()
    assert Path(payload["paths"]["baseline_vs_corrected_overlay_png"]).exists()
    assert Path(payload["paths"]["suspicious_arcs_overlay_png"]).exists()
    assert Path(payload["paths"]["accepted_correction_overlay_png"]).exists()
    assert Path(payload["paths"]["halo_robust_scalar_png"]).exists()
    assert Path(payload["paths"]["profiles_dir"]).exists()
    assert len(payload["profile_outputs"]) >= 1
    assert Path(payload["profile_outputs"][0]["plot_path"]).exists()
    assert Path(payload["profile_outputs"][0]["csv_path"]).exists()
