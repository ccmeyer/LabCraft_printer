from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np

from tools.stream_analysis import baseline as mod
from tools.stream_analysis import dataset as dataset_mod


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _make_frame(width: int, height: int, *, body_top: int, body_bottom: int, body_half_width: int):
    image = np.full((height, width), 245, dtype=np.uint8)
    x_center = width // 2
    cv2.rectangle(
        image,
        (x_center - body_half_width, body_top),
        (x_center + body_half_width, body_bottom),
        40,
        thickness=-1,
    )
    return image


def _make_baseline_experiment(tmp_path: Path):
    exp_dir = tmp_path / "Stream_characterization-20260327_225650"
    process_root = exp_dir / "calibration_recordings" / dataset_mod.PROCESS_NAME
    run_dir = process_root / "run_20260327_230520_9567e1ee"
    captures_dir = run_dir / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)

    run_meta = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "process_name": dataset_mod.PROCESS_NAME,
        "phase_name": "droplet_timecourse",
        "started_at_utc": "2026-03-28T06:05:20.630838Z",
        "ended_at_utc": "2026-03-28T06:05:50.176087Z",
        "outcome": "completed",
        "error_message": "",
    }
    (run_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    events = [
        {
            "event_index": 1,
            "event_type": "stage_changed",
            "payload": {"message": "Timecourse: emergence=4800 us, start=4750 us, step=50 us, window=6000 us (3 frames)"},
        }
    ]
    frames = [
        _make_frame(120, 160, body_top=48, body_bottom=86, body_half_width=7),
        _make_frame(120, 160, body_top=52, body_bottom=108, body_half_width=9),
        _make_frame(120, 160, body_top=60, body_bottom=72, body_half_width=5),
    ]
    for idx, image in enumerate(frames, start=1):
        image_name = f"cap_{idx:06d}_raw_frame.jpg"
        image_relpath = f"captures/{image_name}"
        cv2.imwrite(str(captures_dir / image_name), image)
        flash_delay_us = 4750 + ((idx - 1) * 50)
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
                            "width": 120,
                            "height": 160,
                            "captured_at_utc": f"2026-03-28T06:05:{20 + idx:02d}.000000Z",
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


def test_export_stage1_baseline_writes_metrics_and_contact_sheet(tmp_path):
    exp_dir, run_dir = _make_baseline_experiment(tmp_path)
    out_dir = tmp_path / "analysis" / "stream_characterization"

    payload = mod.export_stage1_baseline(
        exp_dir,
        output_root=out_dir,
        sample_count=3,
        roi_width_frac=0.35,
        roi_top_frac=0.10,
    )

    assert payload["selected_run_count"] == 1
    run_info = payload["runs"][0]
    assert run_info["run_id"] == run_dir.name

    frame_metrics_csv = Path(run_info["frame_metrics_csv"])
    baseline_manifest_json = Path(run_info["baseline_manifest_json"])
    contact_sheet_png = Path(run_info["sample_contact_sheet_png"])

    assert frame_metrics_csv.exists()
    assert baseline_manifest_json.exists()
    assert contact_sheet_png.exists()

    with frame_metrics_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert rows[0]["threshold_method"] == "otsu_dark"
    assert float(rows[0]["threshold_value"]) > 0
    assert int(rows[1]["largest_component_area_px"]) > 0
    assert rows[2]["sample_frame"] == "True"

    manifest = json.loads(baseline_manifest_json.read_text(encoding="utf-8"))
    assert manifest["run_id"] == run_dir.name
    assert manifest["summary"]["frame_count"] == 3
    assert manifest["sample_capture_indices"] == [1, 2, 3]
