from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np

from tools.stream_analysis import dataset as dataset_mod
from tools.stream_analysis import nozzle as mod
from tests.test_stream_analysis_baseline import _write_jsonl


def _make_black_droplet_frame(width: int, height: int, *, x_center: int, nozzle_y: int, droplet_radius: int):
    image = np.full((height, width), 245, dtype=np.uint8)
    cv2.rectangle(image, (x_center - 42, 22), (x_center + 42, 68), 95, thickness=-1)
    cv2.rectangle(image, (x_center - 8, 52), (x_center + 8, nozzle_y), 35, thickness=-1)
    cv2.ellipse(
        image,
        (x_center, nozzle_y + droplet_radius),
        (droplet_radius, int(round(droplet_radius * 1.25))),
        0.0,
        0.0,
        360.0,
        38,
        thickness=-1,
    )
    return image


def _make_two_core_frame(width: int, height: int, *, x_center: int, nozzle_y: int):
    image = np.full((height, width), 245, dtype=np.uint8)
    cv2.rectangle(image, (x_center - 42, 22), (x_center + 42, 68), 95, thickness=-1)
    cv2.rectangle(image, (x_center - 10, 52), (x_center + 10, nozzle_y + 10), 35, thickness=-1)
    cv2.ellipse(image, (x_center, nozzle_y + 24), (34, 26), 0.0, 0.0, 360.0, 35, thickness=-1)
    cv2.ellipse(image, (x_center, nozzle_y + 92), (38, 68), 0.0, 0.0, 360.0, 35, thickness=-1)
    cv2.ellipse(image, (x_center, nozzle_y + 16), (10, 10), 0.0, 0.0, 360.0, 205, thickness=-1)
    cv2.ellipse(image, (x_center, nozzle_y + 84), (12, 34), 0.0, 0.0, 360.0, 212, thickness=-1)
    cv2.line(image, (x_center - 12, nozzle_y + 48), (x_center + 12, nozzle_y + 48), 22, thickness=3)
    return image


def _make_attached_core_separation_frame(width: int, height: int, *, x_center: int, nozzle_y: int):
    image = np.full((height, width), 245, dtype=np.uint8)
    cv2.rectangle(image, (x_center - 42, 22), (x_center + 42, 68), 95, thickness=-1)
    cv2.rectangle(image, (x_center - 10, 52), (x_center + 10, nozzle_y + 8), 35, thickness=-1)
    cv2.ellipse(image, (x_center, nozzle_y + 18), (10, 12), 0.0, 0.0, 360.0, 182, thickness=-1)
    cv2.ellipse(image, (x_center, nozzle_y + 86), (12, 36), 0.0, 0.0, 360.0, 214, thickness=-1)
    cv2.line(image, (x_center - 10, nozzle_y + 44), (x_center + 10, nozzle_y + 44), 62, thickness=2)
    return image


def _make_attached_visible_line_frame(width: int, height: int, *, x_center: int, nozzle_y: int):
    image = np.full((height, width), 245, dtype=np.uint8)
    cv2.rectangle(image, (x_center - 42, 22), (x_center + 42, 68), 95, thickness=-1)
    cv2.rectangle(image, (x_center - 9, 52), (x_center + 9, nozzle_y + 12), 35, thickness=-1)
    cv2.ellipse(image, (x_center, nozzle_y + 26), (14, 18), 0.0, 0.0, 360.0, 216, thickness=-1)
    cv2.ellipse(image, (x_center, nozzle_y + 100), (14, 54), 0.0, 0.0, 360.0, 222, thickness=-1)
    cv2.line(image, (x_center - 12, nozzle_y + 52), (x_center + 12, nozzle_y + 52), 18, thickness=3)
    return image


def _make_long_attached_visible_line_frame(width: int, height: int, *, x_center: int, nozzle_y: int):
    image = np.full((height, width), 245, dtype=np.uint8)
    cv2.rectangle(image, (x_center - 42, 22), (x_center + 42, 68), 95, thickness=-1)
    cv2.rectangle(image, (x_center - 9, 52), (x_center + 9, nozzle_y + 10), 35, thickness=-1)
    cv2.ellipse(image, (x_center, nozzle_y + 170), (40, 190), 0.0, 0.0, 360.0, 34, thickness=-1)
    cv2.rectangle(image, (x_center - 16, nozzle_y + 26), (x_center + 16, nozzle_y + 148), 220, thickness=-1)
    cv2.rectangle(image, (x_center - 16, nozzle_y + 164), (x_center + 16, nozzle_y + 320), 220, thickness=-1)
    cv2.line(image, (x_center - 18, nozzle_y + 156), (x_center + 18, nozzle_y + 156), 30, thickness=4)
    return image


def _make_visible_line_frame(width: int, height: int, *, x_center: int, nozzle_y: int):
    image = np.full((height, width), 245, dtype=np.uint8)
    cv2.line(image, (x_center - 26, nozzle_y), (x_center + 26, nozzle_y), 32, thickness=2)
    cv2.ellipse(image, (x_center + 12, nozzle_y + 46), (14, 20), 0.0, 0.0, 360.0, 45, thickness=-1)
    return image


def _detect(image: np.ndarray):
    return mod._detect_raw_nozzle(
        image,
        search_width_frac=0.30,
        search_top_frac=0.08,
        search_bottom_frac=0.34,
        blur_sigma=12.0,
        residual_scale=2.5,
        residual_threshold=18,
        min_area_px=120,
        top_band_slack_px=14,
    )


def _make_nozzle_experiment(tmp_path: Path):
    exp_dir = tmp_path / "Stream_characterization-20260327_225650"
    process_root = exp_dir / "calibration_recordings" / dataset_mod.PROCESS_NAME
    run_dir = process_root / "run_20260327_225848_829e10c1"
    captures_dir = run_dir / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)

    run_meta = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "process_name": dataset_mod.PROCESS_NAME,
        "phase_name": "droplet_timecourse",
        "started_at_utc": "2026-03-28T05:58:48.000000Z",
        "ended_at_utc": "2026-03-28T05:59:10.000000Z",
        "outcome": "completed",
        "error_message": "",
    }
    (run_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    events = [
        {
            "event_index": 1,
            "event_type": "stage_changed",
            "payload": {"message": "Timecourse: emergence=4250 us, start=4200 us, step=50 us, window=6000 us (6 frames)"},
        }
    ]
    frames = [
        _make_black_droplet_frame(360, 480, x_center=176, nozzle_y=102, droplet_radius=18),
        _make_black_droplet_frame(360, 480, x_center=176, nozzle_y=102, droplet_radius=20),
        _make_two_core_frame(360, 480, x_center=176, nozzle_y=96),
        _make_two_core_frame(360, 480, x_center=186, nozzle_y=102),
        _make_visible_line_frame(360, 480, x_center=186, nozzle_y=108),
        _make_visible_line_frame(360, 480, x_center=186, nozzle_y=108),
    ]
    for idx, image in enumerate(frames, start=1):
        image_name = f"cap_{idx:06d}_raw_frame.jpg"
        image_relpath = f"captures/{image_name}"
        cv2.imwrite(str(captures_dir / image_name), image)
        flash_delay_us = 4200 + ((idx - 1) * 50)
        events.extend(
            [
                {
                    "event_index": (idx * 3) - 1,
                    "event_type": "stage_changed",
                    "payload": {"message": f"Setting flash_delay = {flash_delay_us} us"},
                },
                {
                    "event_index": idx * 3,
                    "event_type": "capture_saved",
                    "payload": {
                        "capture_id": f"cap_{idx:06d}",
                        "capture_role": "raw_frame",
                        "image_relpath": image_relpath,
                        "metadata": {"stage_text": f"Capturing timecourse frame @ {flash_delay_us} us"},
                    },
                },
                {
                    "event_index": (idx * 3) + 1,
                    "event_type": "capture_result",
                    "payload": {
                        "status": "success",
                        "stage_text": f"Capturing timecourse frame @ {flash_delay_us} us",
                        "capture_ref": {
                            "capture_id": f"cap_{idx:06d}",
                            "capture_index": idx,
                            "capture_role": "raw_frame",
                            "image_relpath": image_relpath,
                            "width": 360,
                            "height": 480,
                            "captured_at_utc": f"2026-03-28T05:58:{48 + idx:02d}.000000Z",
                            "stage_text": f"Capturing timecourse frame @ {flash_delay_us} us",
                        },
                    },
                },
            ]
        )

    _write_jsonl(run_dir / "events.jsonl", events)
    _write_jsonl(run_dir / "analysis.jsonl", [{"kind": "calibration_data_updated"}])

    metadata_path = exp_dir / dataset_mod.METADATA_FILENAME
    with metadata_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Dataset name",
                "Print PW",
                "Print Pressure",
                "Refuel PW",
                "Refuel Pressure",
                "Rep",
                "Starting mass",
                "Starting flash",
                "Ending flash",
                "Ending mass",
                "Mass Change",
                "Num printed",
                "Mass/print",
                "CV",
                "Notes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Dataset name": run_dir.name,
                "Print PW": "3000",
                "Print Pressure": "0.65",
                "Refuel PW": "5000",
                "Refuel Pressure": "0.8",
                "Rep": "1",
                "Starting mass": "0",
                "Starting flash": "1987",
                "Ending flash": "2128",
                "Ending mass": "10.03",
                "Mass Change": "10.03",
                "Num printed": "141",
                "Mass/print": "0.0711",
                "CV": "0.99%",
                "Notes": "",
            }
        )
    return exp_dir, run_dir


def _add_top_shadow_band(image: np.ndarray, *, y0: int = 38, y1: int = 60, intensity: int = 96):
    shaded = image.copy()
    cv2.rectangle(
        shaded,
        (0, int(y0)),
        (int(shaded.shape[1]) - 1, int(y1)),
        int(intensity),
        thickness=-1,
    )
    return shaded


def _make_fixed_early_reflection_frame(
    width: int,
    height: int,
    *,
    x_center: int,
    nozzle_y: int,
    droplet_radius: int,
):
    image = np.full((height, width), 245, dtype=np.uint8)
    shadow_y0 = int(round(float(height) * 0.08))
    shadow_y1 = int(shadow_y0 + 22)
    image = _add_top_shadow_band(image, y0=shadow_y0, y1=shadow_y1, intensity=96)
    cv2.rectangle(image, (x_center - 8, nozzle_y - 20), (x_center + 8, nozzle_y + 20), 35, thickness=-1)
    cv2.ellipse(
        image,
        (x_center, nozzle_y),
        (droplet_radius, int(round(droplet_radius * 1.25))),
        0.0,
        0.0,
        360.0,
        38,
        thickness=-1,
    )
    return image


def _write_stream_capture_log(exp_dir: Path, *, run_id: str, gripper_refresh_suspended: bool):
    _write_jsonl(
        exp_dir / dataset_mod.STREAM_CAPTURE_LOG_FILENAME,
        [
            {
                "timecourse_run_id": run_id,
                "gripper_refresh_suspended": bool(gripper_refresh_suspended),
            }
        ],
    )


def _make_fixed_early_nozzle_experiment(tmp_path: Path, *, variant: str = "happy"):
    exp_dir = tmp_path / "Stream_characterization-20260327_225650"
    process_root = exp_dir / "calibration_recordings" / dataset_mod.PROCESS_NAME
    run_dir = process_root / "run_20260327_225848_fixed"
    captures_dir = run_dir / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)

    run_meta = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "process_name": dataset_mod.PROCESS_NAME,
        "phase_name": "droplet_timecourse",
        "started_at_utc": "2026-03-28T05:58:48.000000Z",
        "ended_at_utc": "2026-03-28T05:59:10.000000Z",
        "outcome": "completed",
        "error_message": "",
    }
    (run_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    frames = [
        _make_fixed_early_reflection_frame(360, 480, x_center=176, nozzle_y=118, droplet_radius=10),
        _make_fixed_early_reflection_frame(360, 480, x_center=176, nozzle_y=118, droplet_radius=14),
        _make_fixed_early_reflection_frame(
            360,
            480,
            x_center=200 if variant in {"rescue", "failure"} else 176,
            nozzle_y=118,
            droplet_radius=18,
        ),
        _make_fixed_early_reflection_frame(
            360,
            480,
            x_center=200 if variant == "failure" else 176,
            nozzle_y=118,
            droplet_radius=22,
        ),
        _make_fixed_early_reflection_frame(
            360,
            480,
            x_center=200 if variant == "failure" else 176,
            nozzle_y=118,
            droplet_radius=26,
        ),
        _make_visible_line_frame(360, 480, x_center=176, nozzle_y=108),
    ]

    events = [
        {
            "event_index": 1,
            "event_type": "stage_changed",
            "payload": {"message": "Timecourse: emergence=4250 us, start=4200 us, step=50 us, window=6000 us (6 frames)"},
        }
    ]
    for idx, image in enumerate(frames, start=1):
        image_name = f"cap_{idx:06d}_raw_frame.jpg"
        image_relpath = f"captures/{image_name}"
        cv2.imwrite(str(captures_dir / image_name), image)
        flash_delay_us = 4200 + ((idx - 1) * 50)
        events.extend(
            [
                {
                    "event_index": (idx * 3) - 1,
                    "event_type": "stage_changed",
                    "payload": {"message": f"Setting flash_delay = {flash_delay_us} us"},
                },
                {
                    "event_index": idx * 3,
                    "event_type": "capture_saved",
                    "payload": {
                        "capture_id": f"cap_{idx:06d}",
                        "capture_role": "raw_frame",
                        "image_relpath": image_relpath,
                        "metadata": {"stage_text": f"Capturing timecourse frame @ {flash_delay_us} us"},
                    },
                },
                {
                    "event_index": (idx * 3) + 1,
                    "event_type": "capture_result",
                    "payload": {
                        "status": "success",
                        "stage_text": f"Capturing timecourse frame @ {flash_delay_us} us",
                        "capture_ref": {
                            "capture_id": f"cap_{idx:06d}",
                            "capture_index": idx,
                            "capture_role": "raw_frame",
                            "image_relpath": image_relpath,
                            "width": 360,
                            "height": 480,
                            "captured_at_utc": f"2026-03-28T05:58:{48 + idx:02d}.000000Z",
                            "stage_text": f"Capturing timecourse frame @ {flash_delay_us} us",
                        },
                    },
                },
            ]
        )

    _write_jsonl(run_dir / "events.jsonl", events)
    _write_jsonl(run_dir / "analysis.jsonl", [{"kind": "calibration_data_updated"}])

    metadata_path = exp_dir / dataset_mod.METADATA_FILENAME
    with metadata_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Dataset name",
                "Print PW",
                "Print Pressure",
                "Refuel PW",
                "Refuel Pressure",
                "Rep",
                "Starting mass",
                "Starting flash",
                "Ending flash",
                "Ending mass",
                "Mass Change",
                "Num printed",
                "Mass/print",
                "CV",
                "Notes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Dataset name": run_dir.name,
                "Print PW": "3000",
                "Print Pressure": "0.65",
                "Refuel PW": "5000",
                "Refuel Pressure": "0.8",
                "Rep": "1",
                "Starting mass": "0",
                "Starting flash": "1987",
                "Ending flash": "2128",
                "Ending mass": "10.03",
                "Mass Change": "10.03",
                "Num printed": "141",
                "Mass/print": "0.0711",
                "CV": "0.99%",
                "Notes": f"fixed_early_{variant}",
            }
        )

    _write_stream_capture_log(
        exp_dir,
        run_id=run_dir.name,
        gripper_refresh_suspended=True,
    )
    return exp_dir, run_dir


def test_fixed_early_rejection_reason_flags_upper_shadow_band_only():
    shadow_band = {
        "bbox_y": 0,
        "bbox_x": 0,
        "bbox_x1": 107,
        "bbox_w": 108,
        "bbox_h": 24,
    }
    lower_nozzle = {
        "bbox_y": 78,
        "bbox_x": 34,
        "bbox_x1": 73,
        "bbox_w": 40,
        "bbox_h": 42,
    }

    assert mod._fixed_early_rejection_reason(shadow_band, search_width=108) == "upper_shadow_band"
    assert mod._fixed_early_rejection_reason(lower_nozzle, search_width=108) is None


def test_fixed_early_candidate_rows_rejects_top_shadow_band():
    image = _make_fixed_early_reflection_frame(
        360,
        480,
        x_center=176,
        nozzle_y=118,
        droplet_radius=14,
    )
    diagnostics = _detect(image)

    bundle = mod._fixed_early_candidate_rows(
        {
            "capture_id": "cap_000001",
            "capture_index": 1,
            "image_relpath": "captures/cap_000001_raw_frame.jpg",
        },
        diagnostics,
        early_frame_rank=1,
        min_area_px=120,
    )

    assert bundle["raw_anchor_candidate_count"] == 2
    assert bundle["shadow_band_rejected_count"] == 1
    assert bundle["filtered_anchor_candidate_count"] == 1
    assert len(bundle["candidates"]) == 1
    candidate = bundle["candidates"][0]
    assert int(candidate["bbox_w_px"]) < int(diagnostics["search"]["width"])
    assert int(candidate["bbox_y_px"]) > int(diagnostics["search"]["y0"]) + 30


def test_detect_raw_nozzle_prefers_centroid_for_black_attached_droplet():
    image = _make_black_droplet_frame(360, 480, x_center=180, nozzle_y=98, droplet_radius=18)
    result = _detect(image)

    assert result["mode"] == "attached_black_droplet_center"
    assert abs(float(result["raw_x"]) - 180.0) <= 3.5
    assert 70.0 <= float(result["raw_y"]) <= 100.0


def test_choose_raw_detection_v2_prefers_core_when_neck_score_beats_compact_droplet():
    droplet = mod._candidate_payload(
        "attached_black_droplet_center",
        raw_x_local=54.0,
        raw_y_local=72.0,
        confidence=0.63,
    )
    core = mod._candidate_payload(
        "attached_core_separation",
        raw_x_local=54.0,
        raw_y_local=61.0,
        confidence=0.74,
        separation_y_local=61.0,
    )
    chosen = mod._choose_raw_detection_v2(
        {
            "attached_black_droplet_center": droplet,
            "attached_core_separation": core,
        },
        compact_droplet_score=0.61,
        neck_score=0.74,
        line_band_score=0.08,
        only_nozzle_score=0.0,
        attached_support_score=0.74,
    )

    assert chosen is core


def test_choose_raw_detection_v2_prefers_visible_line_when_line_score_wins():
    droplet = mod._candidate_payload(
        "attached_black_droplet_center",
        raw_x_local=54.0,
        raw_y_local=76.0,
        confidence=0.66,
    )
    visible = mod._candidate_payload(
        "visible_nozzle_line",
        raw_x_local=54.0,
        raw_y_local=63.0,
        confidence=0.59,
        separation_y_local=63.0,
    )
    chosen = mod._choose_raw_detection_v2(
        {
            "attached_black_droplet_center": droplet,
            "visible_nozzle_line": visible,
        },
        compact_droplet_score=0.64,
        neck_score=0.12,
        line_band_score=0.59,
        only_nozzle_score=0.0,
        attached_support_score=0.59,
    )

    assert chosen is visible


def test_choose_raw_detection_v2_keeps_visible_line_with_stable_prior_hysteresis():
    droplet = mod._candidate_payload(
        "attached_black_droplet_center",
        raw_x_local=54.0,
        raw_y_local=78.0,
        confidence=0.72,
    )
    visible = mod._candidate_payload(
        "visible_nozzle_line",
        raw_x_local=54.0,
        raw_y_local=63.0,
        confidence=0.30,
        separation_y_local=63.0,
    )
    chosen = mod._choose_raw_detection_v2(
        {
            "attached_black_droplet_center": droplet,
            "visible_nozzle_line": visible,
        },
        compact_droplet_score=0.72,
        neck_score=0.08,
        line_band_score=0.30,
        only_nozzle_score=0.0,
        attached_support_score=0.66,
        stable_visible_line_y_local=63.0,
        neck_y_local=52.0,
        line_candidate_used_hysteresis=True,
        missing_visible_line_count=1,
    )

    assert chosen is visible


def test_choose_raw_detection_v2_prefers_only_nozzle_for_detached_family():
    droplet = mod._candidate_payload(
        "attached_black_droplet_center",
        raw_x_local=54.0,
        raw_y_local=80.0,
        confidence=0.68,
    )
    only_nozzle = mod._candidate_payload(
        "only_nozzle",
        raw_x_local=54.0,
        raw_y_local=41.0,
        confidence=0.71,
    )
    chosen = mod._choose_raw_detection_v2(
        {
            "attached_black_droplet_center": droplet,
            "only_nozzle": only_nozzle,
        },
        compact_droplet_score=0.68,
        neck_score=0.0,
        line_band_score=0.0,
        only_nozzle_score=0.71,
        attached_support_score=0.12,
    )

    assert chosen is only_nozzle


def test_detect_raw_nozzle_uses_only_nozzle_over_detached_blobs():
    image = _make_visible_line_frame(360, 480, x_center=180, nozzle_y=108)
    result = _detect(image)

    assert result["mode"] == "only_nozzle"
    assert abs(float(result["raw_x"]) - 180.0) <= 4.0
    assert abs(float(result["raw_y"]) - 108.0) <= 6.0


def test_visible_line_search_config_prefers_stable_prior_over_weak_neck():
    image = _make_long_attached_visible_line_frame(360, 480, x_center=180, nozzle_y=90)
    detected = mod._detect_raw_nozzle(
        image,
        search_width_frac=0.30,
        search_top_frac=0.08,
        search_bottom_frac=0.78,
        blur_sigma=12.0,
        residual_scale=2.5,
        residual_threshold=18,
        min_area_px=120,
        top_band_slack_px=14,
    )
    geometry = detected["geometry"]

    config = mod._visible_line_search_config_v2(
        geometry,
        neck_metrics={"index": 10, "neck_y_local": 120.0, "score": 0.54},
        compact_droplet_score=0.0,
        droplet_y_local=None,
        previous_attached_y_local=214.0,
        previous_mode_history=("visible_nozzle_line", "visible_nozzle_line", "visible_nozzle_line"),
        stable_visible_line_y_local=208.0,
        visible_line_streak_length=3,
        missing_visible_line_count=0,
    )

    assert config["source"] == "stable_visible_line_prior"
    assert abs(float(config["center_y_local"]) - 208.0) <= 2.0
    assert int(config["radius_px"]) == 10


def test_visible_line_search_config_without_prior_prefers_compact_upper_neck():
    geometry = {
        "rows": np.arange(200, 260, dtype=np.int32),
        "widths": np.concatenate(
            [
                np.full(10, 14.0, dtype=np.float32),
                np.full(20, 18.0, dtype=np.float32),
                np.full(30, 42.0, dtype=np.float32),
            ]
        ),
        "height": 60,
    }

    config = mod._visible_line_search_config_v2(
        geometry,
        neck_metrics=None,
        compact_droplet_score=0.72,
        droplet_y_local=214.0,
        previous_attached_y_local=246.0,
        previous_mode_history=("attached_black_droplet_center",),
        stable_visible_line_y_local=None,
        provisional_visible_line_y_local=None,
        visible_line_streak_length=0,
        missing_visible_line_count=0,
    )

    assert config["source"] == "compact_droplet_upper_neck"
    assert abs(float(config["center_y_local"]) - 214.0) <= 1.0
    assert float(config["acquisition_upper_bound_y_local"]) <= 233.0


def test_visible_line_search_config_uses_provisional_prior_before_reacquisition():
    geometry = {
        "rows": np.arange(200, 260, dtype=np.int32),
        "widths": np.full(60, 22.0, dtype=np.float32),
        "height": 60,
    }

    config = mod._visible_line_search_config_v2(
        geometry,
        neck_metrics=None,
        compact_droplet_score=0.35,
        droplet_y_local=244.0,
        previous_attached_y_local=244.0,
        previous_mode_history=("visible_nozzle_line", "attached_black_droplet_center"),
        stable_visible_line_y_local=None,
        provisional_visible_line_y_local=228.0,
        visible_line_streak_length=1,
        missing_visible_line_count=1,
    )

    assert config["source"] == "provisional_visible_line_prior"
    assert abs(float(config["center_y_local"]) - 228.0) <= 1.0
    assert bool(config["allow_hysteresis"]) is True


def test_visible_line_search_config_prefers_previous_attached_upper_continuity():
    geometry = {
        "rows": np.arange(200, 260, dtype=np.int32),
        "widths": np.concatenate(
            [
                np.full(12, 16.0, dtype=np.float32),
                np.full(20, 28.0, dtype=np.float32),
                np.full(28, 42.0, dtype=np.float32),
            ]
        ),
        "height": 60,
    }

    config = mod._visible_line_search_config_v2(
        geometry,
        neck_metrics=None,
        compact_droplet_score=0.22,
        droplet_y_local=248.0,
        previous_attached_y_local=214.0,
        previous_mode_history=("attached_black_droplet_center",),
        stable_visible_line_y_local=None,
        provisional_visible_line_y_local=None,
        visible_line_streak_length=0,
        missing_visible_line_count=0,
    )

    assert config["source"] == "previous_attached_upper_continuity"
    assert abs(float(config["center_y_local"]) - 214.0) <= 1.0


def test_visible_line_acquisition_upper_bound_expands_for_recent_upper_continuity():
    geometry = {
        "rows": np.arange(168, 437, dtype=np.int32),
        "widths": np.full(269, 88.0, dtype=np.float32),
        "height": 269,
    }

    upper_bound = mod._visible_line_acquisition_upper_bound_y_local_v2(
        geometry,
        previous_attached_y_local=327.0,
        droplet_y_local=None,
    )

    assert upper_bound is not None
    assert abs(float(upper_bound) - 331.0) <= 1.0


def test_hollow_bulb_guard_rejects_lower_closure_candidate():
    geometry = {
        "rows": np.arange(200, 280, dtype=np.int32),
        "widths": np.concatenate(
            [
                np.full(20, 14.0, dtype=np.float32),
                np.full(20, 18.0, dtype=np.float32),
                np.full(40, 42.0, dtype=np.float32),
            ]
        ),
        "height": 80,
    }

    result = mod._hollow_bulb_guard_v2(
        geometry,
        contour_completeness_score=0.92,
        candidate_y_local=258.0,
    )

    assert bool(result["active"]) is True
    assert bool(result["candidate_rejected"]) is True


def test_update_visible_line_state_v2_uses_provisional_until_confirmed():
    state = mod._update_visible_line_state_v2(
        {
            "raw_mode": "visible_nozzle_line",
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 238.0,
            "line_band_score": 0.74,
        },
        stable_visible_line_y_px=None,
        stable_visible_line_history=[],
        visible_line_streak_length=0,
        missing_visible_line_count=0,
        pending_visible_line_y_px=None,
        pending_visible_line_count=0,
        provisional_visible_line_y_px=None,
        provisional_visible_line_count=0,
        attached_support_low=0.20,
    )

    assert state["stable_visible_line_y_px"] is None
    assert float(state["provisional_visible_line_y_px"]) == 238.0
    assert int(state["provisional_visible_line_count"]) == 1


def test_update_visible_line_state_v2_promotes_confirmed_provisional_visible_line():
    state = mod._update_visible_line_state_v2(
        {
            "raw_mode": "visible_nozzle_line",
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 240.0,
            "line_band_score": 0.78,
        },
        stable_visible_line_y_px=None,
        stable_visible_line_history=[],
        visible_line_streak_length=1,
        missing_visible_line_count=0,
        pending_visible_line_y_px=None,
        pending_visible_line_count=0,
        provisional_visible_line_y_px=238.0,
        provisional_visible_line_count=1,
        attached_support_low=0.20,
    )

    assert state["provisional_visible_line_y_px"] is None
    assert int(state["provisional_visible_line_count"]) == 0
    assert abs(float(state["stable_visible_line_y_px"]) - 239.0) <= 1.0


def test_update_visible_line_state_v2_keeps_provisional_during_attached_gap():
    state = mod._update_visible_line_state_v2(
        {
            "raw_mode": "attached_black_droplet_center",
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 236.0,
            "compact_droplet_score": 0.12,
            "attached_support_score": 0.12,
        },
        stable_visible_line_y_px=None,
        stable_visible_line_history=[],
        visible_line_streak_length=1,
        missing_visible_line_count=0,
        pending_visible_line_y_px=None,
        pending_visible_line_count=0,
        provisional_visible_line_y_px=238.0,
        provisional_visible_line_count=1,
        attached_support_low=0.20,
    )

    assert state["stable_visible_line_y_px"] is None
    assert float(state["provisional_visible_line_y_px"]) == 238.0
    assert int(state["provisional_visible_line_count"]) == 1
    assert int(state["missing_visible_line_count"]) == 1


def test_update_visible_line_state_v2_promotes_provisional_from_nearby_attached_confirmation():
    state = mod._update_visible_line_state_v2(
        {
            "raw_mode": "attached_black_droplet_center",
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 236.0,
            "compact_droplet_score": 0.62,
            "attached_support_score": 0.62,
        },
        stable_visible_line_y_px=None,
        stable_visible_line_history=[],
        visible_line_streak_length=1,
        missing_visible_line_count=0,
        pending_visible_line_y_px=None,
        pending_visible_line_count=0,
        provisional_visible_line_y_px=238.0,
        provisional_visible_line_count=1,
        attached_support_low=0.20,
    )

    assert state["provisional_visible_line_y_px"] is None
    assert int(state["provisional_visible_line_count"]) == 0
    assert abs(float(state["stable_visible_line_y_px"]) - 237.0) <= 1.0


def test_update_visible_line_state_v2_expires_provisional_after_attached_gaps():
    state = mod._update_visible_line_state_v2(
        {
            "raw_mode": "attached_black_droplet_center",
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 236.0,
            "compact_droplet_score": 0.38,
            "attached_support_score": 0.30,
        },
        stable_visible_line_y_px=None,
        stable_visible_line_history=[],
        visible_line_streak_length=0,
        missing_visible_line_count=2,
        pending_visible_line_y_px=None,
        pending_visible_line_count=0,
        provisional_visible_line_y_px=238.0,
        provisional_visible_line_count=1,
        attached_support_low=0.20,
    )

    assert state["provisional_visible_line_y_px"] is None
    assert int(state["provisional_visible_line_count"]) == 0
    assert int(state["missing_visible_line_count"]) == 0


def test_update_visible_line_state_v2_does_not_replace_provisional_with_conflicting_line():
    state = mod._update_visible_line_state_v2(
        {
            "raw_mode": "visible_nozzle_line",
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 228.0,
            "line_band_score": 0.92,
            "visible_line_rejected_by_upper_cue_conflict": True,
        },
        stable_visible_line_y_px=None,
        stable_visible_line_history=[],
        visible_line_streak_length=1,
        missing_visible_line_count=0,
        pending_visible_line_y_px=None,
        pending_visible_line_count=0,
        provisional_visible_line_y_px=236.0,
        provisional_visible_line_count=1,
        attached_support_low=0.20,
    )

    assert float(state["provisional_visible_line_y_px"]) == 236.0
    assert int(state["provisional_visible_line_count"]) == 1
    assert int(state["missing_visible_line_count"]) == 1


def test_visible_line_metrics_v2_prefers_row_near_stable_prior_for_broad_band(monkeypatch):
    geometry = {
        "rows": np.arange(200, 212, dtype=np.int32),
        "widths": np.full(12, 40.0, dtype=np.float32),
        "centerlines": np.full(12, 24.0, dtype=np.float32),
        "lefts": np.full(12, 4.0, dtype=np.float32),
        "rights": np.full(12, 44.0, dtype=np.float32),
    }
    profiles = {
        "centerline_mean_smooth": np.full(12, 100.0, dtype=np.float32),
        "inner_p90_smooth": np.full(12, 180.0, dtype=np.float32),
        "inner_p10_smooth": np.full(12, 60.0, dtype=np.float32),
    }

    def fake_search_config(*_args, **_kwargs):
        return {
            "center_index": 6,
            "center_y_local": 206.0,
            "radius_px": 4,
            "source": "stable_visible_line_prior",
            "stable_visible_line_y_local": 207.0,
            "recent_visible_history": True,
            "stable_prior_exists": True,
            "allow_hysteresis": True,
        }

    metrics_by_index = {
        4: {
            "row_y_local": 204.0,
            "span_width_px": 28,
            "span_fraction": 0.90,
            "centerline_in_run": 1.0,
            "dark_delta": 12.0,
            "vertical_overlap": 0.80,
            "upper_peak_index": 1,
            "lower_peak_index": 10,
            "upper_peak_y_local": 201.0,
            "lower_peak_y_local": 210.0,
            "dark_threshold": 120.0,
            "shoulder_valid": True,
            "upper_gap_px": 3.0,
            "lower_gap_px": 7.0,
            "bridge_x0_local": 12.0,
            "bridge_x1_local": 34.0,
            "score": 0.88,
            "valid_fresh": True,
            "valid_hysteresis": True,
        },
        5: {
            "row_y_local": 205.0,
            "span_width_px": 28,
            "span_fraction": 0.91,
            "centerline_in_run": 1.0,
            "dark_delta": 12.5,
            "vertical_overlap": 0.84,
            "upper_peak_index": 1,
            "lower_peak_index": 10,
            "upper_peak_y_local": 201.0,
            "lower_peak_y_local": 210.0,
            "dark_threshold": 120.0,
            "shoulder_valid": True,
            "upper_gap_px": 4.0,
            "lower_gap_px": 6.0,
            "bridge_x0_local": 12.0,
            "bridge_x1_local": 34.0,
            "score": 0.90,
            "valid_fresh": True,
            "valid_hysteresis": True,
        },
        6: {
            "row_y_local": 206.0,
            "span_width_px": 28,
            "span_fraction": 0.92,
            "centerline_in_run": 1.0,
            "dark_delta": 13.0,
            "vertical_overlap": 0.86,
            "upper_peak_index": 1,
            "lower_peak_index": 10,
            "upper_peak_y_local": 201.0,
            "lower_peak_y_local": 210.0,
            "dark_threshold": 120.0,
            "shoulder_valid": True,
            "upper_gap_px": 5.0,
            "lower_gap_px": 5.0,
            "bridge_x0_local": 12.0,
            "bridge_x1_local": 34.0,
            "score": 0.91,
            "valid_fresh": True,
            "valid_hysteresis": True,
        },
        7: {
            "row_y_local": 207.0,
            "span_width_px": 28,
            "span_fraction": 0.89,
            "centerline_in_run": 1.0,
            "dark_delta": 11.2,
            "vertical_overlap": 0.82,
            "upper_peak_index": 1,
            "lower_peak_index": 10,
            "upper_peak_y_local": 201.0,
            "lower_peak_y_local": 210.0,
            "dark_threshold": 120.0,
            "shoulder_valid": True,
            "upper_gap_px": 6.0,
            "lower_gap_px": 4.0,
            "bridge_x0_local": 12.0,
            "bridge_x1_local": 34.0,
            "score": 0.87,
            "valid_fresh": True,
            "valid_hysteresis": True,
        },
        8: {
            "row_y_local": 208.0,
            "span_width_px": 28,
            "span_fraction": 0.88,
            "centerline_in_run": 1.0,
            "dark_delta": 10.8,
            "vertical_overlap": 0.80,
            "upper_peak_index": 1,
            "lower_peak_index": 10,
            "upper_peak_y_local": 201.0,
            "lower_peak_y_local": 210.0,
            "dark_threshold": 120.0,
            "shoulder_valid": True,
            "upper_gap_px": 7.0,
            "lower_gap_px": 4.0,
            "bridge_x0_local": 12.0,
            "bridge_x1_local": 34.0,
            "score": 0.86,
            "valid_fresh": True,
            "valid_hysteresis": True,
        },
    }

    monkeypatch.setattr(mod, "_visible_line_search_config_v2", fake_search_config)
    monkeypatch.setattr(
        mod,
        "_visible_line_row_bridge_metrics_v2",
        lambda _search_gray, _geometry, _profiles, index, **_kwargs: dict(metrics_by_index[index]) if index in metrics_by_index else None,
    )

    result = mod._visible_line_metrics_v2(
        np.full((240, 80), 200, dtype=np.uint8),
        geometry,
        profiles,
        neck_metrics=None,
        previous_attached_y_local=206.0,
        previous_mode_history=("visible_nozzle_line", "visible_nozzle_line"),
        stable_visible_line_y_local=207.0,
        visible_line_streak_length=4,
        missing_visible_line_count=0,
        attached_support_score=0.50,
        recent_attached_width_median_px=40.0,
        recent_attached_center_x_local=24.0,
    )

    assert result is not None
    assert float(result["raw_y_local"]) == 207.0
    assert int(result["band_height_px"]) >= 5


def test_visible_line_metrics_v2_relaxed_fallback_recovers_short_dropout(monkeypatch):
    geometry = {
        "rows": np.arange(200, 212, dtype=np.int32),
        "widths": np.full(12, 40.0, dtype=np.float32),
        "centerlines": np.full(12, 24.0, dtype=np.float32),
        "lefts": np.full(12, 4.0, dtype=np.float32),
        "rights": np.full(12, 44.0, dtype=np.float32),
    }
    profiles = {
        "centerline_mean_smooth": np.full(12, 100.0, dtype=np.float32),
        "inner_p90_smooth": np.full(12, 180.0, dtype=np.float32),
        "inner_p10_smooth": np.full(12, 60.0, dtype=np.float32),
    }

    def fake_search_config(*_args, **_kwargs):
        return {
            "center_index": 5,
            "center_y_local": 205.0,
            "radius_px": 4,
            "source": "stable_visible_line_prior",
            "stable_visible_line_y_local": 205.0,
            "recent_visible_history": True,
            "stable_prior_exists": True,
            "allow_hysteresis": True,
        }

    metrics_by_index = {
        5: {
            "row_y_local": 205.0,
            "span_width_px": 20,
            "span_fraction": 0.56,
            "centerline_in_run": 1.0,
            "dark_delta": 3.5,
            "vertical_overlap": 0.60,
            "upper_peak_index": 1,
            "lower_peak_index": 9,
            "upper_peak_y_local": 201.0,
            "lower_peak_y_local": 209.0,
            "dark_threshold": 120.0,
            "shoulder_valid": True,
            "upper_gap_px": 4.0,
            "lower_gap_px": 4.0,
            "bridge_x0_local": 14.0,
            "bridge_x1_local": 32.0,
            "score": 0.31,
            "valid_fresh": False,
            "valid_hysteresis": False,
        }
    }

    monkeypatch.setattr(mod, "_visible_line_search_config_v2", fake_search_config)
    monkeypatch.setattr(
        mod,
        "_visible_line_row_bridge_metrics_v2",
        lambda _search_gray, _geometry, _profiles, index, **_kwargs: dict(metrics_by_index[index]) if index in metrics_by_index else None,
    )

    result = mod._visible_line_metrics_v2(
        np.full((240, 80), 200, dtype=np.uint8),
        geometry,
        profiles,
        neck_metrics=None,
        previous_attached_y_local=205.0,
        previous_mode_history=("visible_nozzle_line", "visible_nozzle_line", "visible_nozzle_line"),
        stable_visible_line_y_local=205.0,
        visible_line_streak_length=4,
        missing_visible_line_count=1,
        attached_support_score=0.20,
        recent_attached_width_median_px=40.0,
        recent_attached_center_x_local=24.0,
    )

    assert result is not None
    assert bool(result["used_relaxed_fallback"]) is True
    assert float(result["raw_y_local"]) == 205.0


def test_residual_masks_v2_keeps_weak_connected_one_sided_wall():
    residual = np.zeros((24, 24), dtype=np.float32)
    residual[6:18, 5:8] = 10.0
    residual[6:18, 14:16] = 5.0
    residual[10:13, 8:14] = 5.0

    _scaled, strong_mask, contour_mask, _weak_mask, weak_connected = mod._residual_masks_v2(
        residual,
        residual_scale=2.5,
        residual_threshold=18,
        min_area_px=20,
    )

    assert int(np.count_nonzero(strong_mask[:, 14:16])) == 0
    assert int(np.count_nonzero(weak_connected[:, 14:16])) > 0
    assert int(np.count_nonzero(contour_mask[:, 14:16])) > 0


def test_contour_completeness_metrics_v2_flags_clipped_one_sided_contour():
    geometry = {
        "rows": np.arange(200, 211, dtype=np.int32),
        "widths": np.full(11, 35.0, dtype=np.float32),
        "centerlines": np.full(11, 37.0, dtype=np.float32),
        "lefts": np.full(11, 20.0, dtype=np.float32),
        "rights": np.full(11, 54.0, dtype=np.float32),
    }

    metrics = mod._contour_completeness_metrics_v2(
        geometry,
        search_center_index=5,
        search_radius_px=4,
        recent_attached_width_median_px=60.0,
        recent_attached_center_x_local=50.0,
    )

    assert metrics is not None
    assert bool(metrics["clipped_warning"]) is True
    assert float(metrics["width_ratio"]) < 0.75


def test_late_widening_metrics_v2_returns_plateau_row_near_stable_prior():
    geometry = {
        "rows": np.arange(200, 211, dtype=np.int32),
        "widths": np.array([22, 22, 22, 22, 26, 31, 34, 34, 34, 34, 34], dtype=np.float32),
        "centerlines": np.full(11, 24.0, dtype=np.float32),
        "lefts": np.array([13, 13, 13, 13, 11, 9, 8, 8, 8, 8, 8], dtype=np.float32),
        "rights": np.array([35, 35, 35, 35, 39, 41, 42, 42, 42, 42, 42], dtype=np.float32),
    }
    contour_metrics = {
        "completeness_score": 0.82,
    }

    result = mod._late_widening_metrics_v2(
        geometry,
        contour_metrics,
        search_center_y_local=204.0,
        stable_visible_line_y_local=204.0,
    )

    assert result is not None
    assert float(result["raw_y_local"]) == 206.0
    assert float(result["plateau_top_y_local"]) == 206.0
    assert float(result["plateau_bottom_y_local"]) == 210.0
    assert float(result["score"]) > 0.0


def test_visible_line_row_bridge_metrics_v2_marks_late_band_near_stable_prior(monkeypatch):
    search_gray = np.full((240, 60), 210, dtype=np.uint8)
    search_gray[204, 14:38] = 72
    search_gray[203, 18:34] = 84
    search_gray[205, 18:34] = 86
    geometry = {
        "rows": np.arange(200, 209, dtype=np.int32),
        "widths": np.full(9, 40.0, dtype=np.float32),
        "centerlines": np.full(9, 24.0, dtype=np.float32),
        "lefts": np.full(9, 4.0, dtype=np.float32),
        "rights": np.full(9, 44.0, dtype=np.float32),
    }
    profiles = {
        "inner_p90_smooth": np.full(9, 180.0, dtype=np.float32),
    }

    monkeypatch.setattr(
        mod,
        "_local_band_refine_score_v2",
        lambda _profiles, _index: {
            "upper_bright_index": 2,
            "lower_bright_index": 7,
        },
    )

    result = mod._visible_line_row_bridge_metrics_v2(
        search_gray,
        geometry,
        profiles,
        4,
        stable_visible_line_y_local=204.0,
        contour_completeness_score=0.92,
    )

    assert result is not None
    assert bool(result["valid_fresh"]) is False
    assert bool(result["valid_hysteresis"]) is False
    assert bool(result["valid_hysteresis_late_band"]) is True


def test_visible_line_metrics_v2_prefers_widening_over_too_high_bridge(monkeypatch):
    geometry = {
        "rows": np.arange(200, 212, dtype=np.int32),
        "widths": np.full(12, 40.0, dtype=np.float32),
        "centerlines": np.full(12, 24.0, dtype=np.float32),
        "lefts": np.full(12, 4.0, dtype=np.float32),
        "rights": np.full(12, 44.0, dtype=np.float32),
    }
    profiles = {
        "centerline_mean_smooth": np.full(12, 100.0, dtype=np.float32),
        "inner_p90_smooth": np.full(12, 180.0, dtype=np.float32),
        "inner_p10_smooth": np.full(12, 60.0, dtype=np.float32),
    }

    monkeypatch.setattr(
        mod,
        "_visible_line_search_config_v2",
        lambda *_args, **_kwargs: {
            "center_index": 8,
            "center_y_local": 208.0,
            "radius_px": 6,
            "source": "stable_visible_line_prior",
            "stable_visible_line_y_local": 210.0,
            "recent_visible_history": True,
            "stable_prior_exists": True,
            "allow_hysteresis": True,
        },
    )
    monkeypatch.setattr(
        mod,
        "_contour_completeness_metrics_v2",
        lambda *_args, **_kwargs: {
            "completeness_score": 0.78,
            "bilateral_row_fraction": 0.82,
            "width_median_px": 40.0,
            "width_iqr_px": 2.0,
            "clipped_warning": True,
        },
    )
    monkeypatch.setattr(
        mod,
        "_visible_line_row_bridge_metrics_v2",
        lambda _search_gray, _geometry, _profiles, index, **_kwargs: {
            "row_y_local": float(_geometry["rows"][index]),
            "span_width_px": 24,
            "span_fraction": 0.88,
            "centerline_in_run": 1.0,
            "dark_delta": 12.0,
            "vertical_overlap": 0.82,
            "upper_peak_index": 1,
            "lower_peak_index": 11,
            "upper_peak_y_local": 202.0,
            "lower_peak_y_local": 212.0,
            "dark_threshold": 120.0,
            "shoulder_valid": True,
            "upper_gap_px": 3.0,
            "lower_gap_px": 6.0,
            "bridge_x0_local": 12.0,
            "bridge_x1_local": 34.0,
            "score": 0.84 if index == 3 else -1.0,
            "valid_fresh": bool(index == 3),
            "valid_hysteresis": bool(index == 3),
        }
        if index == 3
        else None,
    )
    monkeypatch.setattr(
        mod,
        "_late_widening_metrics_v2",
        lambda *_args, **_kwargs: {
            "index": 10,
            "raw_x_local": 24.0,
            "raw_y_local": 210.0,
            "score": 0.56,
        },
    )

    result = mod._visible_line_metrics_v2(
        np.full((240, 80), 200, dtype=np.uint8),
        geometry,
        profiles,
        neck_metrics=None,
        previous_attached_y_local=210.0,
        previous_mode_history=("visible_nozzle_line", "visible_nozzle_line", "visible_nozzle_line"),
        stable_visible_line_y_local=210.0,
        visible_line_streak_length=5,
        missing_visible_line_count=0,
        attached_support_score=0.60,
        recent_attached_width_median_px=40.0,
        recent_attached_center_x_local=24.0,
    )

    assert result is not None
    assert bool(result["late_widening_used"]) is True
    assert bool(result["bridge_suppressed_by_clipped_contour"]) is True
    assert bool(result["bridge_suppressed_by_plateau"]) is True
    assert float(result["raw_y_local"]) == 210.0


def test_visible_line_metrics_v2_prefers_plateau_near_prior_over_bridge_below_prior(monkeypatch):
    geometry = {
        "rows": np.arange(200, 220, dtype=np.int32),
        "widths": np.full(20, 40.0, dtype=np.float32),
        "centerlines": np.full(20, 24.0, dtype=np.float32),
        "lefts": np.full(20, 4.0, dtype=np.float32),
        "rights": np.full(20, 44.0, dtype=np.float32),
    }
    profiles = {
        "centerline_mean_smooth": np.full(20, 100.0, dtype=np.float32),
        "inner_p90_smooth": np.full(20, 180.0, dtype=np.float32),
        "inner_p10_smooth": np.full(20, 60.0, dtype=np.float32),
    }

    monkeypatch.setattr(
        mod,
        "_visible_line_search_config_v2",
        lambda *_args, **_kwargs: {
            "center_index": 10,
            "center_y_local": 210.0,
            "radius_px": 8,
            "source": "stable_visible_line_prior",
            "stable_visible_line_y_local": 210.0,
            "recent_visible_history": True,
            "stable_prior_exists": True,
            "allow_hysteresis": True,
        },
    )
    monkeypatch.setattr(
        mod,
        "_contour_completeness_metrics_v2",
        lambda *_args, **_kwargs: {
            "completeness_score": 0.82,
            "bilateral_row_fraction": 0.85,
            "width_median_px": 40.0,
            "width_iqr_px": 2.0,
            "clipped_warning": False,
        },
    )
    monkeypatch.setattr(
        mod,
        "_visible_line_row_bridge_metrics_v2",
        lambda _search_gray, _geometry, _profiles, index, **_kwargs: {
            "row_y_local": float(_geometry["rows"][index]),
            "span_width_px": 28,
            "span_fraction": 0.92,
            "centerline_in_run": 1.0,
            "dark_delta": 12.0,
            "vertical_overlap": 0.85,
            "upper_peak_index": 4,
            "lower_peak_index": 18,
            "upper_peak_y_local": 204.0,
            "lower_peak_y_local": 218.0,
            "effective_lower_peak_y_local": 218.0,
            "lower_peak_prior_constrained": False,
            "dark_threshold": 120.0,
            "shoulder_valid": True,
            "upper_gap_px": 4.0,
            "lower_gap_px": 4.0,
            "bridge_x0_local": 12.0,
            "bridge_x1_local": 34.0,
                "score": 0.86 if index == 16 else -1.0,
                "valid_fresh": bool(index == 16),
                "valid_hysteresis": bool(index == 16),
                "used_hysteresis": False,
            }
        if index == 16
        else None,
    )
    monkeypatch.setattr(
        mod,
        "_late_widening_metrics_v2",
        lambda *_args, **_kwargs: {
            "index": 10,
            "raw_x_local": 24.0,
            "raw_y_local": 210.0,
            "score": 0.44,
            "plateau_top_y_local": 209.0,
            "plateau_bottom_y_local": 211.0,
            "plateau_height_px": 3,
            "plateau_max_width_px": 36.0,
        },
    )

    result = mod._visible_line_metrics_v2(
        np.full((240, 80), 200, dtype=np.uint8),
        geometry,
        profiles,
        neck_metrics=None,
        previous_attached_y_local=210.0,
        previous_mode_history=("visible_nozzle_line", "visible_nozzle_line", "visible_nozzle_line"),
        stable_visible_line_y_local=210.0,
        visible_line_streak_length=5,
        missing_visible_line_count=0,
        attached_support_score=0.60,
        recent_attached_width_median_px=40.0,
        recent_attached_center_x_local=24.0,
    )

    assert result is not None
    assert bool(result["late_widening_used"]) is True
    assert bool(result["bridge_suppressed_by_prior_conflict"]) is True
    assert float(result["raw_y_local"]) == 210.0


def test_visible_line_metrics_v2_prefers_plateau_at_negative_four_pixel_boundary(monkeypatch):
    geometry = {
        "rows": np.arange(200, 218, dtype=np.int32),
        "widths": np.full(18, 40.0, dtype=np.float32),
        "centerlines": np.full(18, 24.0, dtype=np.float32),
        "lefts": np.full(18, 4.0, dtype=np.float32),
        "rights": np.full(18, 44.0, dtype=np.float32),
    }
    profiles = {
        "centerline_mean_smooth": np.full(18, 100.0, dtype=np.float32),
        "inner_p90_smooth": np.full(18, 180.0, dtype=np.float32),
        "inner_p10_smooth": np.full(18, 60.0, dtype=np.float32),
    }

    monkeypatch.setattr(
        mod,
        "_visible_line_search_config_v2",
        lambda *_args, **_kwargs: {
            "center_index": 10,
            "center_y_local": 210.0,
            "radius_px": 8,
            "source": "stable_visible_line_prior",
            "stable_visible_line_y_local": 210.0,
            "recent_visible_history": True,
            "stable_prior_exists": True,
            "allow_hysteresis": True,
        },
    )
    monkeypatch.setattr(
        mod,
        "_contour_completeness_metrics_v2",
        lambda *_args, **_kwargs: {
            "completeness_score": 0.90,
            "bilateral_row_fraction": 0.90,
            "width_median_px": 40.0,
            "width_iqr_px": 2.0,
            "clipped_warning": False,
        },
    )

    metrics_by_index = {
        6: {
            "row_y_local": 206.0,
            "span_width_px": 28,
            "span_fraction": 0.90,
            "centerline_in_run": 1.0,
            "dark_delta": 12.0,
            "vertical_overlap": 0.85,
            "upper_peak_index": 2,
            "lower_peak_index": 12,
            "upper_peak_y_local": 202.0,
            "lower_peak_y_local": 214.0,
            "effective_lower_peak_y_local": 214.0,
            "lower_peak_prior_constrained": False,
            "dark_threshold": 120.0,
            "shoulder_valid": True,
            "upper_gap_px": 4.0,
            "lower_gap_px": 8.0,
            "bridge_x0_local": 12.0,
            "bridge_x1_local": 34.0,
            "score": 0.66,
            "valid_fresh": True,
            "valid_hysteresis": False,
            "valid_hysteresis_late_band": False,
        },
        10: {
            "row_y_local": 210.0,
            "span_width_px": 22,
            "span_fraction": 0.36,
            "centerline_in_run": 1.0,
            "dark_delta": 5.6,
            "vertical_overlap": 0.62,
            "upper_peak_index": 6,
            "lower_peak_index": 13,
            "upper_peak_y_local": 206.0,
            "lower_peak_y_local": 215.0,
            "effective_lower_peak_y_local": 215.0,
            "lower_peak_prior_constrained": False,
            "dark_threshold": 120.0,
            "shoulder_valid": True,
            "upper_gap_px": 4.0,
            "lower_gap_px": 5.0,
            "bridge_x0_local": 14.0,
            "bridge_x1_local": 30.0,
            "score": 0.30,
            "valid_fresh": False,
            "valid_hysteresis": False,
            "valid_hysteresis_late_band": True,
        },
    }
    monkeypatch.setattr(
        mod,
        "_visible_line_row_bridge_metrics_v2",
        lambda _search_gray, _geometry, _profiles, index, **_kwargs: dict(metrics_by_index[index]) if index in metrics_by_index else None,
    )
    monkeypatch.setattr(
        mod,
        "_late_widening_metrics_v2",
        lambda *_args, **_kwargs: {
            "index": 10,
            "raw_x_local": 24.0,
            "raw_y_local": 210.0,
            "score": 0.58,
            "plateau_top_y_local": 209.0,
            "plateau_bottom_y_local": 211.0,
            "plateau_height_px": 3,
            "plateau_max_width_px": 36.0,
        },
    )

    result = mod._visible_line_metrics_v2(
        np.full((240, 80), 200, dtype=np.uint8),
        geometry,
        profiles,
        neck_metrics=None,
        previous_attached_y_local=210.0,
        previous_mode_history=("visible_nozzle_line", "visible_nozzle_line", "visible_nozzle_line"),
        stable_visible_line_y_local=210.0,
        visible_line_streak_length=5,
        missing_visible_line_count=0,
        attached_support_score=0.60,
        recent_attached_width_median_px=40.0,
        recent_attached_center_x_local=24.0,
    )

    assert result is not None
    assert bool(result["late_widening_used"]) is True
    assert bool(result["bridge_suppressed_by_prior_conflict"]) is True
    assert float(result["raw_y_local"]) == 210.0


def test_visible_line_metrics_v2_prefers_near_prior_hysteresis_candidate_over_high_fresh_bridge(monkeypatch):
    geometry = {
        "rows": np.arange(200, 214, dtype=np.int32),
        "widths": np.full(14, 40.0, dtype=np.float32),
        "centerlines": np.full(14, 24.0, dtype=np.float32),
        "lefts": np.full(14, 4.0, dtype=np.float32),
        "rights": np.full(14, 44.0, dtype=np.float32),
    }
    profiles = {
        "centerline_mean_smooth": np.full(14, 100.0, dtype=np.float32),
        "inner_p90_smooth": np.full(14, 180.0, dtype=np.float32),
        "inner_p10_smooth": np.full(14, 60.0, dtype=np.float32),
    }

    monkeypatch.setattr(
        mod,
        "_visible_line_search_config_v2",
        lambda *_args, **_kwargs: {
            "center_index": 9,
            "center_y_local": 209.0,
            "radius_px": 8,
            "source": "stable_visible_line_prior",
            "stable_visible_line_y_local": 210.0,
            "recent_visible_history": True,
            "stable_prior_exists": True,
            "allow_hysteresis": True,
        },
    )
    metrics_by_index = {
        1: {
            "row_y_local": 201.0,
            "span_width_px": 26,
            "span_fraction": 0.90,
            "centerline_in_run": 1.0,
            "dark_delta": 12.0,
            "vertical_overlap": 0.84,
            "upper_peak_index": 1,
            "lower_peak_index": 8,
            "upper_peak_y_local": 198.0,
            "lower_peak_y_local": 208.0,
            "effective_lower_peak_y_local": 208.0,
            "lower_peak_prior_constrained": True,
            "dark_threshold": 120.0,
            "shoulder_valid": True,
            "upper_gap_px": 3.0,
            "lower_gap_px": 5.0,
            "bridge_x0_local": 12.0,
            "bridge_x1_local": 34.0,
            "score": 0.82,
            "valid_fresh": True,
            "valid_hysteresis": False,
            "used_hysteresis": False,
        },
        9: {
            "row_y_local": 209.0,
            "span_width_px": 20,
            "span_fraction": 0.64,
            "centerline_in_run": 1.0,
            "dark_delta": 5.6,
            "vertical_overlap": 0.60,
            "upper_peak_index": 4,
            "lower_peak_index": 12,
            "upper_peak_y_local": 204.0,
            "lower_peak_y_local": 213.0,
            "effective_lower_peak_y_local": 213.0,
            "lower_peak_prior_constrained": False,
            "dark_threshold": 120.0,
            "shoulder_valid": True,
            "upper_gap_px": 5.0,
            "lower_gap_px": 4.0,
            "bridge_x0_local": 14.0,
            "bridge_x1_local": 30.0,
            "score": 0.36,
            "valid_fresh": False,
            "valid_hysteresis": True,
            "used_hysteresis": True,
        },
    }
    monkeypatch.setattr(
        mod,
        "_visible_line_row_bridge_metrics_v2",
        lambda _search_gray, _geometry, _profiles, index, **_kwargs: dict(metrics_by_index[index]) if index in metrics_by_index else None,
    )
    monkeypatch.setattr(mod, "_late_widening_metrics_v2", lambda *_args, **_kwargs: None)

    result = mod._visible_line_metrics_v2(
        np.full((240, 80), 200, dtype=np.uint8),
        geometry,
        profiles,
        neck_metrics=None,
        previous_attached_y_local=210.0,
        previous_mode_history=("visible_nozzle_line", "visible_nozzle_line", "visible_nozzle_line"),
        stable_visible_line_y_local=210.0,
        visible_line_streak_length=4,
        missing_visible_line_count=0,
        attached_support_score=0.45,
        recent_attached_width_median_px=40.0,
        recent_attached_center_x_local=24.0,
    )

    assert result is not None
    assert float(result["raw_y_local"]) == 209.0
    assert bool(result["used_hysteresis"]) is True


def test_visible_line_metrics_v2_uses_plateau_when_contour_complete_and_no_bridge(monkeypatch):
    geometry = {
        "rows": np.arange(200, 212, dtype=np.int32),
        "widths": np.array([22, 22, 22, 22, 26, 31, 34, 34, 34, 34, 34, 34], dtype=np.float32),
        "centerlines": np.full(12, 24.0, dtype=np.float32),
        "lefts": np.array([13, 13, 13, 13, 11, 9, 8, 8, 8, 8, 8, 8], dtype=np.float32),
        "rights": np.array([35, 35, 35, 35, 39, 41, 42, 42, 42, 42, 42, 42], dtype=np.float32),
    }
    profiles = {
        "centerline_mean_smooth": np.full(12, 100.0, dtype=np.float32),
        "inner_p90_smooth": np.full(12, 180.0, dtype=np.float32),
        "inner_p10_smooth": np.full(12, 60.0, dtype=np.float32),
    }

    monkeypatch.setattr(
        mod,
        "_visible_line_search_config_v2",
        lambda *_args, **_kwargs: {
            "center_index": 4,
            "center_y_local": 204.0,
            "radius_px": 8,
            "source": "stable_visible_line_prior",
            "stable_visible_line_y_local": 204.0,
            "recent_visible_history": True,
            "stable_prior_exists": True,
            "allow_hysteresis": True,
        },
    )
    monkeypatch.setattr(
        mod,
        "_visible_line_row_bridge_metrics_v2",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        mod,
        "_late_widening_metrics_v2",
        lambda *_args, **_kwargs: {
            "index": 6,
            "raw_x_local": 24.0,
            "raw_y_local": 206.0,
            "score": 0.48,
            "plateau_top_y_local": 206.0,
            "plateau_bottom_y_local": 210.0,
            "plateau_height_px": 5,
            "plateau_max_width_px": 34.0,
        },
    )

    result = mod._visible_line_metrics_v2(
        np.full((240, 80), 200, dtype=np.uint8),
        geometry,
        profiles,
        neck_metrics=None,
        previous_attached_y_local=204.0,
        previous_mode_history=("visible_nozzle_line", "visible_nozzle_line", "visible_nozzle_line"),
        stable_visible_line_y_local=204.0,
        visible_line_streak_length=0,
        missing_visible_line_count=0,
        attached_support_score=0.20,
        recent_attached_width_median_px=32.0,
        recent_attached_center_x_local=24.0,
    )

    assert result is not None
    assert bool(result["late_widening_used"]) is True
    assert bool(result["used_plateau_only_fallback"]) is True
    assert float(result["raw_y_local"]) == 206.0


def test_choose_raw_detection_v2_suppresses_reflection_droplet_during_only_nozzle_transition():
    droplet = mod._candidate_payload(
        "attached_black_droplet_center",
        raw_x_local=54.0,
        raw_y_local=120.0,
        confidence=0.68,
    )
    only_nozzle = mod._candidate_payload(
        "only_nozzle",
        raw_x_local=55.0,
        raw_y_local=242.0,
        confidence=0.33,
    )

    chosen = mod._choose_raw_detection_v2(
        {
            "attached_black_droplet_center": droplet,
            "only_nozzle": only_nozzle,
        },
        compact_droplet_score=0.68,
        neck_score=0.0,
        line_band_score=0.0,
        only_nozzle_score=0.33,
        attached_support_score=0.0,
        stable_visible_line_y_local=200.0,
        droplet_y_local=120.0,
    )

    assert chosen is only_nozzle


def test_mode_threshold_for_row_lowers_only_nozzle_threshold_during_transition():
    threshold = mod._mode_threshold_for_row(
        {
            "raw_mode": "only_nozzle",
            "raw_nozzle_y_px": 335.4,
            "stable_visible_line_y_px": 336.0,
            "attached_support_score": 0.0,
        }
    )

    assert float(threshold) == 0.30


def test_only_nozzle_candidate_v2_sweeps_multiple_roi_centers(monkeypatch):
    calls = []

    def fake_detect_in_roi(_roi_gray, *, roi, **_kwargs):
        calls.append(float(roi["center_y_local"]))
        if abs(float(roi["center_y_local"]) - 96.0) <= 0.5:
            candidate = mod._candidate_payload(
                "only_nozzle",
                raw_x_local=24.0,
                raw_y_local=100.0,
                confidence=0.35,
            )
            candidate["selected_roi_center_y_local"] = float(roi["center_y_local"])
            return candidate
        return None

    monkeypatch.setattr(mod, "_detect_only_nozzle_candidate_in_roi_v2", fake_detect_in_roi)

    result = mod._detect_only_nozzle_candidate_v2(
        np.full((180, 80), 200, dtype=np.uint8),
        previous_x_local=24.0,
        previous_y_local=109.0,
        stable_visible_line_y_local=100.0,
        previous_tracked_y_local=109.0,
        attached_support_score=0.0,
    )

    assert result is not None
    assert abs(float(result["selected_roi_center_y_local"]) - 96.0) <= 0.5
    assert 100.0 in [round(value, 1) for value in result["roi_centers_y_local"]]
    assert 96.0 in [round(value, 1) for value in calls]


def test_detect_only_nozzle_candidate_in_roi_v2_prefers_near_prior_nozzle_over_lower_reflection():
    roi_gray = np.full((140, 100), 242, dtype=np.uint8)
    cv2.ellipse(roi_gray, (50, 52), (5, 18), 0.0, 0.0, 360.0, 36, thickness=-1)
    cv2.ellipse(roi_gray, (50, 103), (13, 13), 0.0, 0.0, 360.0, 36, thickness=-1)

    result = mod._detect_only_nozzle_candidate_in_roi_v2(
        roi_gray,
        roi={"x0": 0, "y0": 280, "center_y_local": 332.0},
        previous_x_local=50.0,
        stable_visible_line_y_local=332.0,
        attached_support_score=0.0,
    )

    assert result is not None
    assert bool(result["transition_scoring_used"]) is True
    assert bool(result["rejected_lower_reflection"]) is True
    assert abs(float(result["raw_y_local"]) - 332.0) <= 6.0


def test_detect_only_nozzle_candidate_in_roi_v2_uses_prior_band_for_faint_near_prior_strip():
    roi_gray = np.full((140, 100), 242, dtype=np.uint8)
    cv2.ellipse(roi_gray, (50, 28), (12, 16), 0.0, 0.0, 360.0, 36, thickness=-1)
    cv2.ellipse(roi_gray, (50, 108), (12, 16), 0.0, 0.0, 360.0, 36, thickness=-1)
    cv2.rectangle(roi_gray, (34, 68), (66, 72), 170, thickness=-1)

    result = mod._detect_only_nozzle_candidate_in_roi_v2(
        roi_gray,
        roi={"x0": 0, "y0": 260, "center_y_local": 330.0},
        previous_x_local=50.0,
        stable_visible_line_y_local=330.0,
        attached_support_score=0.0,
    )

    assert result is not None
    assert result["candidate_source"] == "prior_band"
    assert bool(result["prior_band_used"]) is True
    assert int(result["prior_band_candidate_count"]) >= 1
    assert bool(result["rejected_far_from_prior"]) is True
    assert abs(float(result["raw_y_local"]) - 330.0) <= 4.0


def test_detect_only_nozzle_candidate_in_roi_v2_rejects_far_above_false_candidate_when_near_prior_exists():
    roi_gray = np.full((140, 100), 242, dtype=np.uint8)
    cv2.ellipse(roi_gray, (50, 24), (12, 18), 0.0, 0.0, 360.0, 36, thickness=-1)
    cv2.ellipse(roi_gray, (50, 108), (10, 14), 0.0, 0.0, 360.0, 42, thickness=-1)
    cv2.rectangle(roi_gray, (36, 69), (64, 72), 172, thickness=-1)

    result = mod._detect_only_nozzle_candidate_in_roi_v2(
        roi_gray,
        roi={"x0": 0, "y0": 260, "center_y_local": 330.0},
        previous_x_local=50.0,
        stable_visible_line_y_local=330.0,
        attached_support_score=0.0,
    )

    assert result is not None
    assert bool(result["rejected_far_from_prior"]) is True
    assert float(result["raw_y_local"]) > 320.0
    assert float(result["raw_y_local"]) < 336.0


def test_detect_only_nozzle_candidate_in_roi_v2_returns_none_when_only_far_candidates_survive():
    roi_gray = np.full((140, 100), 242, dtype=np.uint8)
    cv2.ellipse(roi_gray, (50, 28), (12, 16), 0.0, 0.0, 360.0, 36, thickness=-1)
    cv2.ellipse(roi_gray, (50, 108), (12, 16), 0.0, 0.0, 360.0, 36, thickness=-1)

    result = mod._detect_only_nozzle_candidate_in_roi_v2(
        roi_gray,
        roi={"x0": 0, "y0": 260, "center_y_local": 330.0},
        previous_x_local=50.0,
        stable_visible_line_y_local=330.0,
        attached_support_score=0.0,
    )

    assert result is None


def test_only_nozzle_candidate_v2_marks_low_reflection_anchor_rejection(monkeypatch):
    def fake_detect_in_roi(_roi_gray, *, roi, **_kwargs):
        candidate = mod._candidate_payload(
            "only_nozzle",
            raw_x_local=24.0,
            raw_y_local=float(roi["center_y_local"]),
            confidence=0.34,
        )
        candidate["selected_roi_center_y_local"] = float(roi["center_y_local"])
        candidate["transition_scoring_used"] = True
        candidate["distance_from_stable_prior"] = abs(float(roi["center_y_local"]) - 100.0)
        candidate["rejected_lower_reflection"] = bool(abs(float(roi["center_y_local"]) - 100.0) <= 0.5)
        return candidate

    monkeypatch.setattr(mod, "_detect_only_nozzle_candidate_in_roi_v2", fake_detect_in_roi)

    result = mod._detect_only_nozzle_candidate_v2(
        np.full((180, 80), 200, dtype=np.uint8),
        previous_x_local=24.0,
        previous_y_local=109.0,
        stable_visible_line_y_local=100.0,
        previous_tracked_y_local=109.0,
        attached_support_score=0.0,
    )

    assert result is not None
    assert bool(result["anchor_rejected_as_low_reflection"]) is True
    assert abs(float(result["raw_y_local"]) - 100.0) <= 0.5


def test_update_visible_line_state_v2_relaxed_fallback_does_not_update_stable_prior():
    state = mod._update_visible_line_state_v2(
        {
            "raw_mode": "visible_nozzle_line",
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 206.0,
            "line_band_score": 0.34,
            "visible_line_used_relaxed_fallback": True,
        },
        stable_visible_line_y_px=200.0,
        stable_visible_line_history=[199.0, 200.0, 201.0],
        visible_line_streak_length=3,
        missing_visible_line_count=1,
        pending_visible_line_y_px=None,
        pending_visible_line_count=0,
        provisional_visible_line_y_px=None,
        provisional_visible_line_count=0,
        attached_support_low=0.20,
    )

    assert float(state["stable_visible_line_y_px"]) == 200.0
    assert state["pending_visible_line_y_px"] is None
    assert int(state["pending_visible_line_count"]) == 0


def test_update_visible_line_state_v2_prior_conflict_does_not_update_stable_prior():
    state = mod._update_visible_line_state_v2(
        {
            "raw_mode": "visible_nozzle_line",
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 214.0,
            "line_band_score": 0.86,
            "bridge_suppressed_by_prior_conflict": True,
        },
        stable_visible_line_y_px=210.0,
        stable_visible_line_history=[209.0, 210.0, 211.0],
        visible_line_streak_length=3,
        missing_visible_line_count=0,
        pending_visible_line_y_px=None,
        pending_visible_line_count=0,
        provisional_visible_line_y_px=None,
        provisional_visible_line_count=0,
        attached_support_low=0.20,
    )

    assert float(state["stable_visible_line_y_px"]) == 210.0
    assert state["pending_visible_line_y_px"] is None


def test_update_visible_line_state_v2_plateau_recovery_does_not_update_stable_prior():
    state = mod._update_visible_line_state_v2(
        {
            "raw_mode": "visible_nozzle_line",
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 206.0,
            "line_band_score": 0.40,
            "visible_line_used_relaxed_fallback": False,
            "late_widening_used": True,
            "late_widening_score": 0.44,
        },
        stable_visible_line_y_px=200.0,
        stable_visible_line_history=[199.0, 200.0, 201.0],
        visible_line_streak_length=3,
        missing_visible_line_count=1,
        pending_visible_line_y_px=None,
        pending_visible_line_count=0,
        provisional_visible_line_y_px=None,
        provisional_visible_line_count=0,
        attached_support_low=0.20,
    )

    assert float(state["stable_visible_line_y_px"]) == 200.0
    assert state["pending_visible_line_y_px"] is None
    assert int(state["pending_visible_line_count"]) == 0


def test_update_visible_line_state_v2_preserves_prior_for_nearby_only_nozzle_transition():
    state = mod._update_visible_line_state_v2(
        {
            "raw_mode": "only_nozzle",
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 335.4,
            "only_nozzle_score": 0.34,
            "stable_visible_line_y_px": 336.0,
            "attached_support_score": 0.0,
        },
        stable_visible_line_y_px=336.0,
        stable_visible_line_history=[335.0, 336.0, 337.0],
        visible_line_streak_length=4,
        missing_visible_line_count=0,
        pending_visible_line_y_px=None,
        pending_visible_line_count=0,
        provisional_visible_line_y_px=None,
        provisional_visible_line_count=0,
        attached_support_low=0.20,
    )

    assert float(state["stable_visible_line_y_px"]) == 336.0
    assert int(state["missing_visible_line_count"]) == 1
    assert state["pending_visible_line_y_px"] is None


def test_detect_raw_nozzle_uses_bridge_visible_line_near_stable_prior():
    image = _make_long_attached_visible_line_frame(360, 480, x_center=180, nozzle_y=90)
    result = mod._detect_raw_nozzle(
        image,
        search_width_frac=0.30,
        search_top_frac=0.08,
        search_bottom_frac=0.78,
        blur_sigma=12.0,
        residual_scale=2.5,
        residual_threshold=18,
        min_area_px=120,
        top_band_slack_px=14,
        previous_attached_y_px=246.0,
        previous_mode_history=("visible_nozzle_line", "visible_nozzle_line", "visible_nozzle_line"),
        stable_visible_line_y_px=246.0,
        visible_line_streak_length=3,
        missing_visible_line_count=0,
    )

    assert result["mode"] == "visible_nozzle_line"
    assert abs(float(result["raw_y"]) - 246.0) <= 5.0
    assert float(result["visible_line_span_fraction"]) >= 0.62
    assert result["visible_line_search_center_y_local"] is not None


def test_update_visible_line_state_v2_requires_confirmation_before_large_prior_jump():
    state = mod._update_visible_line_state_v2(
        {
            "raw_mode": "visible_nozzle_line",
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 210.0,
            "line_band_score": 0.82,
            "visible_line_used_relaxed_fallback": False,
        },
        stable_visible_line_y_px=200.0,
        stable_visible_line_history=[199.0, 200.0, 201.0],
        visible_line_streak_length=3,
        missing_visible_line_count=0,
        pending_visible_line_y_px=None,
        pending_visible_line_count=0,
        provisional_visible_line_y_px=None,
        provisional_visible_line_count=0,
        attached_support_low=0.20,
    )

    assert float(state["stable_visible_line_y_px"]) == 200.0
    assert float(state["pending_visible_line_y_px"]) == 210.0
    assert int(state["pending_visible_line_count"]) == 1


def test_update_visible_line_state_v2_accepts_two_consistent_pending_jumps():
    state = mod._update_visible_line_state_v2(
        {
            "raw_mode": "visible_nozzle_line",
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 211.0,
            "line_band_score": 0.80,
            "visible_line_used_relaxed_fallback": False,
        },
        stable_visible_line_y_px=200.0,
        stable_visible_line_history=[199.0, 200.0, 201.0],
        visible_line_streak_length=3,
        missing_visible_line_count=0,
        pending_visible_line_y_px=210.0,
        pending_visible_line_count=1,
        provisional_visible_line_y_px=None,
        provisional_visible_line_count=0,
        attached_support_low=0.20,
    )

    assert float(state["stable_visible_line_y_px"]) == 211.0
    assert state["pending_visible_line_y_px"] is None
    assert int(state["pending_visible_line_count"]) == 0


def test_apply_tracking_keeps_confident_attached_raw_detections():
    raw_rows = [
        {
            "capture_index": 1,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 112.0,
            "raw_confidence": 0.70,
            "raw_mode": "attached_black_droplet_center",
            "compact_droplet_score": 0.70,
        },
        {
            "capture_index": 2,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 122.0,
            "raw_confidence": 0.52,
            "raw_mode": "attached_core_separation",
            "neck_score": 0.86,
        },
        {
            "capture_index": 3,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 134.0,
            "raw_confidence": 0.90,
            "raw_mode": "visible_nozzle_line",
            "line_band_score": 0.90,
        },
    ]

    tracked_rows, _boundaries = mod._apply_tracking(
        raw_rows,
        shift_threshold_px=20.0,
        confidence_threshold=0.55,
    )

    assert tracked_rows[0]["final_mode"] == "attached_black_droplet_center"
    assert tracked_rows[0]["tracked_nozzle_y_px"] == 112.0
    assert tracked_rows[0]["used_segment_fill"] is False
    assert tracked_rows[1]["final_mode"] == "attached_core_separation"
    assert tracked_rows[1]["tracked_nozzle_y_px"] == 122.0
    assert tracked_rows[1]["used_segment_fill"] is False


def test_apply_tracking_does_not_use_provisional_visible_line_anchor():
    raw_rows = [
        {
            "capture_index": 1,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 214.0,
            "raw_confidence": 0.34,
            "raw_mode": "attached_black_droplet_center",
            "compact_droplet_score": 0.34,
            "stable_visible_line_y_px": None,
            "provisional_visible_line_y_px": None,
            "provisional_visible_line_count": 0,
            "attached_support_score": 0.42,
        },
        {
            "capture_index": 2,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 360.0,
            "raw_confidence": 0.70,
            "raw_mode": "visible_nozzle_line",
            "line_band_score": 0.70,
            "stable_visible_line_y_px": None,
            "provisional_visible_line_y_px": 360.0,
            "provisional_visible_line_count": 1,
            "attached_support_score": 0.70,
        },
    ]

    tracked_rows, _boundaries = mod._apply_tracking(
        raw_rows,
        shift_threshold_px=20.0,
        confidence_threshold=0.55,
    )

    assert abs(float(tracked_rows[0]["tracked_nozzle_y_px"]) - 214.0) <= 1.0
    assert abs(float(tracked_rows[0]["tracked_nozzle_y_px"]) - 360.0) >= 40.0


def test_apply_tracking_keeps_confident_only_nozzle_raw_detection():
    raw_rows = [
        {
            "capture_index": 1,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 170.0,
            "raw_confidence": 0.90,
            "raw_mode": "attached_core_separation",
        },
        {
            "capture_index": 2,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 171.0,
            "raw_confidence": 0.92,
            "raw_mode": "attached_core_separation",
        },
        {
            "capture_index": 3,
            "raw_nozzle_x_px": 182.0,
            "raw_nozzle_y_px": 240.0,
            "raw_confidence": 0.80,
            "raw_mode": "only_nozzle",
        },
        {
            "capture_index": 4,
            "raw_nozzle_x_px": 181.0,
            "raw_nozzle_y_px": 170.0,
            "raw_confidence": 0.91,
            "raw_mode": "attached_core_separation",
        },
        {
            "capture_index": 5,
            "raw_nozzle_x_px": 181.0,
            "raw_nozzle_y_px": 171.0,
            "raw_confidence": 0.90,
            "raw_mode": "attached_core_separation",
        },
    ]

    tracked_rows, _boundaries = mod._apply_tracking(
        raw_rows,
        shift_threshold_px=20.0,
        confidence_threshold=0.55,
    )

    assert tracked_rows[2]["final_mode"] == "only_nozzle"
    assert tracked_rows[2]["tracked_nozzle_y_px"] == 240.0
    assert tracked_rows[2]["used_segment_fill"] is False


def test_apply_tracking_keeps_transition_only_nozzle_near_stable_prior():
    raw_rows = [
        {
            "capture_index": 1,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 336.0,
            "raw_confidence": 0.88,
            "raw_mode": "visible_nozzle_line",
            "line_band_score": 0.88,
            "stable_visible_line_y_px": 336.0,
            "attached_support_score": 0.90,
            "visible_line_used_hysteresis": False,
        },
        {
            "capture_index": 2,
            "raw_nozzle_x_px": 180.5,
            "raw_nozzle_y_px": 335.4,
            "raw_confidence": 0.34,
            "raw_mode": "only_nozzle",
            "only_nozzle_score": 0.34,
            "stable_visible_line_y_px": 336.0,
            "attached_support_score": 0.0,
        },
        {
            "capture_index": 3,
            "raw_nozzle_x_px": 180.2,
            "raw_nozzle_y_px": 335.1,
            "raw_confidence": 0.37,
            "raw_mode": "only_nozzle",
            "only_nozzle_score": 0.37,
            "stable_visible_line_y_px": 336.0,
            "attached_support_score": 0.0,
        },
    ]

    tracked_rows, _boundaries = mod._apply_tracking(
        raw_rows,
        shift_threshold_px=20.0,
        confidence_threshold=0.55,
    )

    assert tracked_rows[1]["final_mode"] == "only_nozzle"
    assert tracked_rows[1]["used_segment_fill"] is False
    assert tracked_rows[2]["final_mode"] == "only_nozzle"
    assert tracked_rows[2]["used_segment_fill"] is False


def test_apply_tracking_prefers_stable_visible_prior_fill_for_short_gap():
    raw_rows = [
        {
            "capture_index": 1,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 200.0,
            "raw_confidence": 0.86,
            "raw_mode": "visible_nozzle_line",
            "line_band_score": 0.86,
            "stable_visible_line_y_px": 200.0,
            "attached_support_score": 0.80,
            "visible_line_used_hysteresis": False,
        },
        {
            "capture_index": 2,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 201.0,
            "raw_confidence": 0.88,
            "raw_mode": "visible_nozzle_line",
            "line_band_score": 0.88,
            "stable_visible_line_y_px": 200.5,
            "attached_support_score": 0.82,
            "visible_line_used_hysteresis": False,
        },
        {
            "capture_index": 3,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 156.0,
            "raw_confidence": 0.40,
            "raw_mode": "attached_black_droplet_center",
            "compact_droplet_score": 0.40,
            "stable_visible_line_y_px": 200.5,
            "attached_support_score": 0.74,
            "visible_line_used_hysteresis": False,
        },
        {
            "capture_index": 4,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 202.0,
            "raw_confidence": 0.87,
            "raw_mode": "visible_nozzle_line",
            "line_band_score": 0.87,
            "stable_visible_line_y_px": 201.0,
            "attached_support_score": 0.83,
            "visible_line_used_hysteresis": False,
        },
    ]

    tracked_rows, _boundaries = mod._apply_tracking(
        raw_rows,
        shift_threshold_px=20.0,
        confidence_threshold=0.55,
    )

    assert tracked_rows[2]["final_mode"] == "segment_fill"
    assert abs(float(tracked_rows[2]["tracked_nozzle_y_px"]) - 200.5) <= 1.0
    assert tracked_rows[2]["used_segment_fill"] is True


def test_apply_tracking_allows_nearby_local_raw_fallback_without_stable_prior():
    raw_rows = [
        {
            "capture_index": 1,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 205.0,
            "raw_confidence": 0.05,
            "raw_mode": "attached_black_droplet_center",
            "compact_droplet_score": 0.05,
            "stable_visible_line_y_px": None,
            "attached_support_score": 0.30,
            "visible_line_acquisition_search_center_y_px": 200.0,
        },
    ]

    tracked_rows, _boundaries = mod._apply_tracking(
        raw_rows,
        shift_threshold_px=20.0,
        confidence_threshold=0.55,
    )

    assert tracked_rows[0]["final_mode"] == "segment_fill"
    assert abs(float(tracked_rows[0]["tracked_nozzle_y_px"]) - 205.0) <= 1.0
    assert tracked_rows[0]["transition_fill_source"] == "local_raw_fallback"
    assert bool(tracked_rows[0]["local_raw_fallback_rejected"]) is False
    assert abs(float(tracked_rows[0]["local_raw_fallback_reference_y_px"]) - 200.0) <= 1.0


def test_apply_tracking_rejects_far_local_raw_fallback_and_uses_continuity_hold():
    raw_rows = [
        {
            "capture_index": 1,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 200.0,
            "raw_confidence": 0.82,
            "raw_mode": "attached_core_separation",
            "neck_score": 0.82,
            "stable_visible_line_y_px": None,
            "attached_support_score": 0.82,
        },
        {
            "capture_index": 2,
            "raw_nozzle_x_px": 181.0,
            "raw_nozzle_y_px": 240.0,
            "raw_confidence": 0.05,
            "raw_mode": "attached_black_droplet_center",
            "compact_droplet_score": 0.05,
            "stable_visible_line_y_px": None,
            "attached_support_score": 0.30,
            "visible_line_acquisition_search_center_y_px": 200.0,
        },
    ]

    tracked_rows, _boundaries = mod._apply_tracking(
        raw_rows,
        shift_threshold_px=20.0,
        confidence_threshold=0.55,
    )

    assert bool(tracked_rows[1]["local_raw_fallback_rejected"]) is True
    assert tracked_rows[1]["transition_fill_source"] == "attached_continuity_hold"
    assert bool(tracked_rows[1]["attached_continuity_hold_used"]) is True
    assert int(tracked_rows[1]["attached_continuity_hold_count"]) == 1
    assert abs(float(tracked_rows[1]["tracked_nozzle_y_px"]) - 200.0) <= 1.0


def test_apply_tracking_bypasses_attached_cap_for_strong_reacquisition_after_fallback():
    raw_rows = [
        {
            "capture_index": 1,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 200.0,
            "raw_confidence": 0.82,
            "raw_mode": "attached_core_separation",
            "neck_score": 0.82,
            "stable_visible_line_y_px": None,
            "attached_support_score": 0.82,
        },
        {
            "capture_index": 2,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 206.0,
            "raw_confidence": 0.05,
            "raw_mode": "attached_black_droplet_center",
            "compact_droplet_score": 0.05,
            "stable_visible_line_y_px": None,
            "attached_support_score": 0.30,
            "visible_line_acquisition_search_center_y_px": 200.0,
        },
        {
            "capture_index": 3,
            "raw_nozzle_x_px": 180.0,
            "raw_nozzle_y_px": 250.0,
            "raw_confidence": 0.95,
            "raw_mode": "visible_nozzle_line",
            "line_band_score": 0.95,
            "stable_visible_line_y_px": None,
            "attached_support_score": 0.95,
        },
    ]

    tracked_rows, _boundaries = mod._apply_tracking(
        raw_rows,
        shift_threshold_px=20.0,
        confidence_threshold=0.55,
    )

    assert tracked_rows[1]["transition_fill_source"] == "local_raw_fallback"
    assert tracked_rows[2]["final_mode"] == "visible_nozzle_line"
    assert abs(float(tracked_rows[2]["tracked_nozzle_y_px"]) - 250.0) <= 1.0
    assert bool(tracked_rows[2]["attached_tracking_cap_applied"]) is False
    assert bool(tracked_rows[2]["attached_tracking_cap_bypassed_for_reacquisition"]) is True
    assert tracked_rows[2]["attached_tracking_cap_reference_source"] in (None, "")


def test_apply_tracking_uses_transition_fill_and_rejects_reflection_anchor():
    raw_rows = [
        {
            "capture_index": 1,
            "raw_nozzle_x_px": 593.0,
            "raw_nozzle_y_px": 336.0,
            "raw_confidence": 0.92,
            "raw_mode": "visible_nozzle_line",
            "line_band_score": 0.92,
            "stable_visible_line_y_px": 336.0,
            "attached_support_score": 0.88,
            "visible_line_used_hysteresis": False,
        },
        {
            "capture_index": 2,
            "raw_nozzle_x_px": 593.0,
            "raw_nozzle_y_px": 337.0,
            "raw_confidence": 0.90,
            "raw_mode": "visible_nozzle_line",
            "line_band_score": 0.90,
            "stable_visible_line_y_px": 336.0,
            "attached_support_score": 0.84,
            "visible_line_used_hysteresis": False,
        },
        {
            "capture_index": 3,
            "raw_nozzle_x_px": 590.0,
            "raw_nozzle_y_px": 212.8,
            "raw_confidence": 0.61,
            "raw_mode": "attached_black_droplet_center",
            "compact_droplet_score": 0.61,
            "stable_visible_line_y_px": 336.0,
            "attached_support_score": 0.0,
        },
        {
            "capture_index": 4,
            "raw_nozzle_x_px": None,
            "raw_nozzle_y_px": None,
            "raw_confidence": 0.0,
            "raw_mode": "no_signal",
            "stable_visible_line_y_px": 336.0,
            "attached_support_score": 0.0,
        },
    ]

    tracked_rows, _boundaries = mod._apply_tracking(
        raw_rows,
        shift_threshold_px=20.0,
        confidence_threshold=0.55,
    )

    assert tracked_rows[3]["final_mode"] == "segment_fill"
    assert abs(float(tracked_rows[3]["tracked_nozzle_y_px"]) - 336.0) <= 1.0
    assert bool(tracked_rows[3]["transition_fill_used"]) is True
    assert tracked_rows[3]["transition_fill_source"] == "stable_visible_line_prior"
    assert bool(tracked_rows[3]["anchor_rejected_as_reflection"]) is True


def test_shift_boundaries_ignore_unstable_centroid_mode():
    raw_rows = []
    for capture_index, raw_y in enumerate([150.0, 151.0, 235.0, 236.0, 150.0, 151.0], start=1):
        raw_rows.append(
            {
                "capture_index": capture_index,
                "raw_nozzle_x_px": 180.0,
                "raw_nozzle_y_px": raw_y,
                "raw_confidence": 0.95,
                "raw_mode": "attached_black_droplet_center",
            }
        )

    boundaries = mod._shift_boundaries(
        raw_rows,
        shift_threshold_px=8.0,
        confidence_threshold=0.55,
    )

    assert boundaries == []


def test_export_stage2_nozzle_writes_tracks_and_shift_report(tmp_path):
    exp_dir, run_dir = _make_nozzle_experiment(tmp_path)
    out_dir = tmp_path / "analysis" / "stream_characterization"

    payload = mod.export_stage2_nozzle(
        exp_dir,
        output_root=out_dir,
        sample_count=4,
        search_width_frac=0.30,
        search_top_frac=0.08,
        search_bottom_frac=0.34,
        shift_threshold_px=3.0,
        confidence_threshold=0.48,
    )

    assert payload["selected_run_count"] == 1
    run_info = payload["runs"][0]
    assert run_info["run_id"] == run_dir.name

    track_csv = Path(run_info["nozzle_track_csv"])
    track_json = Path(run_info["nozzle_track_json"])
    shift_json = Path(run_info["shift_events_json"])
    track_png = Path(run_info["nozzle_track_png"])
    contact_sheet = Path(run_info["sample_contact_sheet_png"])

    assert track_csv.exists()
    assert track_json.exists()
    assert shift_json.exists()
    assert track_png.exists()
    assert contact_sheet.exists()

    with track_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 6
    assert rows[0]["tracked_nozzle_x_px"]
    assert rows[0]["tracked_nozzle_y_px"]
    assert rows[0]["raw_mode"]
    assert rows[0]["final_mode"]
    assert any(row["final_mode"] in {"visible_nozzle_line", "only_nozzle"} for row in rows)

    shift_payload = json.loads(shift_json.read_text(encoding="utf-8"))
    assert "shift_events" in shift_payload


def test_export_stage2_nozzle_auto_selects_fixed_early_from_metadata(tmp_path):
    exp_dir, run_dir = _make_fixed_early_nozzle_experiment(tmp_path, variant="happy")
    out_dir = tmp_path / "analysis" / "stream_characterization"

    payload = mod.export_stage2_nozzle(
        exp_dir,
        output_root=out_dir,
        sample_count=2,
        search_width_frac=0.30,
        search_top_frac=0.08,
        search_bottom_frac=0.34,
        shift_threshold_px=3.0,
        confidence_threshold=0.48,
    )

    run_info = payload["runs"][0]
    track_csv = Path(run_info["nozzle_track_csv"])
    fixed_anchor_json = Path(run_info["fixed_anchor_json"])
    fixed_anchor_frames_csv = Path(run_info["fixed_anchor_frames_csv"])
    shift_json = Path(run_info["shift_events_json"])
    stage_dir = out_dir / "runs" / run_dir.name / mod.NOZZLE_STAGE_DIRNAME

    assert fixed_anchor_json.exists()
    assert fixed_anchor_frames_csv.exists()
    assert (stage_dir / "samples" / "frame_001_panel.png").exists()
    assert (stage_dir / "samples" / "frame_005_panel.png").exists()

    with track_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    tracked_x = {row["tracked_nozzle_x_px"] for row in rows}
    tracked_y = {row["tracked_nozzle_y_px"] for row in rows}
    assert {row["tracking_mode"] for row in rows} == {dataset_mod.TRACKING_MODE_FIXED_EARLY}
    assert {row["final_mode"] for row in rows} == {dataset_mod.TRACKING_MODE_FIXED_EARLY}
    assert {row["detection_mode"] for row in rows} == {dataset_mod.TRACKING_MODE_FIXED_EARLY}
    assert "fixed_early_anchor" in {row["raw_mode"] for row in rows}
    assert "fixed_early_reuse" in {row["raw_mode"] for row in rows}
    assert len(tracked_x) == 1
    assert len(tracked_y) == 1
    assert all(row["used_segment_fill"] == "False" for row in rows)
    assert all(row["attached_continuity_hold_used"] == "False" for row in rows)
    assert all(row["transition_fill_source"] == "" for row in rows)

    anchor_payload = json.loads(fixed_anchor_json.read_text(encoding="utf-8"))
    assert anchor_payload["anchor_status"] == "ok"
    assert anchor_payload["selected_early_frame_ranks"] == [1, 2, 3]
    assert anchor_payload["frames"][0]["raw_anchor_candidate_count"] == 2
    assert anchor_payload["frames"][0]["shadow_band_rejected_count"] == 1
    assert anchor_payload["frames"][0]["filtered_anchor_candidate_count"] == 1

    with fixed_anchor_frames_csv.open("r", encoding="utf-8", newline="") as handle:
        anchor_rows = list(csv.DictReader(handle))
    assert anchor_rows[0]["raw_anchor_candidate_count"] == "2"
    assert anchor_rows[0]["shadow_band_rejected_count"] == "1"
    assert anchor_rows[0]["filtered_anchor_candidate_count"] == "1"

    shift_payload = json.loads(shift_json.read_text(encoding="utf-8"))
    assert shift_payload["shift_events"] == []


def test_build_stage2_run_fixed_early_rescues_with_frame_4(tmp_path):
    exp_dir, run_dir = _make_fixed_early_nozzle_experiment(tmp_path, variant="rescue")
    inventory = dataset_mod.build_stage0_inventory(exp_dir)
    frame_rows = list(inventory["frames_by_run_id"][run_dir.name])

    stage2_run = mod._build_stage2_run(
        run_dir.name,
        frame_rows,
        tracking_mode=dataset_mod.TRACKING_MODE_FIXED_EARLY,
        search_width_frac=0.30,
        search_top_frac=0.08,
        search_bottom_frac=0.34,
        blur_sigma=12.0,
        residual_scale=2.5,
        residual_threshold=18,
        min_area_px=120,
        top_band_slack_px=14,
        shift_threshold_px=3.0,
        confidence_threshold=0.48,
    )

    fixed_anchor = stage2_run["fixed_anchor"]
    tracked_rows = stage2_run["tracked_rows"]
    anchor_frame_rows = stage2_run["fixed_anchor_frame_rows"]

    assert fixed_anchor["anchor_status"] == "ok"
    assert fixed_anchor["selected_early_frame_ranks"] == [1, 2, 4]
    assert anchor_frame_rows[0]["raw_anchor_candidate_count"] == 2
    assert anchor_frame_rows[0]["shadow_band_rejected_count"] == 1
    assert anchor_frame_rows[0]["filtered_anchor_candidate_count"] == 1
    assert [row["raw_mode"] for row in tracked_rows[:4]] == [
        "fixed_early_anchor",
        "fixed_early_anchor",
        "fixed_early_reuse",
        "fixed_early_anchor",
    ]
    assert len({row["tracked_nozzle_y_px"] for row in tracked_rows}) == 1


def test_build_stage2_run_fixed_early_fails_clearly_without_dynamic_fallback(tmp_path):
    exp_dir, run_dir = _make_fixed_early_nozzle_experiment(tmp_path, variant="failure")
    inventory = dataset_mod.build_stage0_inventory(exp_dir)
    frame_rows = list(inventory["frames_by_run_id"][run_dir.name])

    stage2_run = mod._build_stage2_run(
        run_dir.name,
        frame_rows,
        tracking_mode=dataset_mod.TRACKING_MODE_FIXED_EARLY,
        search_width_frac=0.30,
        search_top_frac=0.08,
        search_bottom_frac=0.34,
        blur_sigma=12.0,
        residual_scale=2.5,
        residual_threshold=18,
        min_area_px=120,
        top_band_slack_px=14,
        shift_threshold_px=3.0,
        confidence_threshold=0.48,
    )

    fixed_anchor = stage2_run["fixed_anchor"]
    tracked_rows = stage2_run["tracked_rows"]
    anchor_frame_rows = stage2_run["fixed_anchor_frame_rows"]

    assert fixed_anchor["anchor_status"] == "failed"
    assert fixed_anchor["anchor_failure_reason"] == "no_valid_3_frame_anchor_family"
    assert anchor_frame_rows[0]["raw_anchor_candidate_count"] == 2
    assert anchor_frame_rows[0]["shadow_band_rejected_count"] == 1
    assert anchor_frame_rows[0]["filtered_anchor_candidate_count"] == 1
    assert stage2_run["shift_events"] == []
    assert all(row["tracking_mode"] == dataset_mod.TRACKING_MODE_FIXED_EARLY for row in tracked_rows)
    assert all(row["tracked_nozzle_x_px"] is None for row in tracked_rows)
    assert all(row["tracked_nozzle_y_px"] is None for row in tracked_rows)
    assert all(row["final_mode"] == mod.FIXED_EARLY_FAILURE_MODE for row in tracked_rows)
    assert all(row["detection_mode"] == mod.FIXED_EARLY_FAILURE_MODE for row in tracked_rows)
    assert all(bool(row["used_segment_fill"]) is False for row in tracked_rows)
    assert all(bool(row["attached_continuity_hold_used"]) is False for row in tracked_rows)


def test_export_stage2_nozzle_keeps_dynamic_mode_when_metadata_is_false_or_missing(tmp_path):
    exp_dir, run_dir = _make_nozzle_experiment(tmp_path)
    inventory_missing = dataset_mod.build_stage0_inventory(exp_dir)

    assert inventory_missing["selected_runs"][0]["run_id"] == run_dir.name
    assert inventory_missing["selected_runs"][0]["tracking_mode"] == dataset_mod.TRACKING_MODE_DYNAMIC

    _write_stream_capture_log(
        exp_dir,
        run_id=run_dir.name,
        gripper_refresh_suspended=False,
    )
    inventory_false = dataset_mod.build_stage0_inventory(exp_dir)
    assert inventory_false["selected_runs"][0]["tracking_mode"] == dataset_mod.TRACKING_MODE_DYNAMIC
