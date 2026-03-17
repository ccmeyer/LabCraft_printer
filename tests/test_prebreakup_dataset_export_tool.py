from __future__ import annotations

import csv
import json
from pathlib import Path

from tools import export_prebreakup_dataset as mod


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _make_dataset_run(tmp_path: Path):
    exp_dir = tmp_path / "ExperimentA"
    run_dir = exp_dir / "calibration_recordings" / mod.PROCESS_NAME / "run_20260314_120000_deadbeef"
    captures_dir = run_dir / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)

    run_meta = {
        "schema_version": 1,
        "run_id": "run_20260314_120000_deadbeef",
        "process_name": mod.PROCESS_NAME,
        "phase_name": "pre_breakup_dataset_acquisition",
        "started_at_utc": "2026-03-14T19:00:00Z",
        "ended_at_utc": "2026-03-14T19:05:00Z",
        "outcome": "completed",
        "error_message": "",
    }
    (run_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    plan_snapshot = {
        "schema_version": 1,
        "source_plan_path": str(exp_dir / "plans" / "prebreakup_dataset_plan.json"),
        "conditions": [{"condition_id": "cond_0001"}],
    }
    (run_dir / "plan_snapshot.json").write_text(json.dumps(plan_snapshot, indent=2), encoding="utf-8")

    condition_row = {
        "condition_id": "cond_0001",
        "condition_index": 1,
        "run_id": run_meta["run_id"],
        "stock_solution": "water",
        "printer_head_id": "head_A",
        "nozzle_id": "n1",
        "pulse_width_us": 1300,
        "pressure_psi": 0.42,
        "delay_mode": "emergence_relative",
        "delay_start_us": 3300,
        "delay_stop_us": 3400,
        "delay_step_us": 50,
        "delay_start_offset_us": 100,
        "delay_stop_offset_us": 200,
        "replicates_per_delay": 2,
        "background_policy": "per_condition",
        "background_capture_id": "cap_bg",
        "background_image_relpath": "captures/background.png",
        "emergence_time_us": 3200,
        "nozzle_center_px": [160, 80],
        "label_key": "water_n1_pw1300",
        "notes": "unit test",
    }
    _write_jsonl(run_dir / "conditions.jsonl", [condition_row])

    frame_row = {
        "frame_id": "frame_001",
        "condition_id": "cond_0001",
        "condition_index": 1,
        "capture_id": "cap_frame",
        "capture_index": 2,
        "replicate_index": 1,
        "capture_role": "capture",
        "image_relpath": "captures/frame_0001.png",
        "background_image_relpath": "captures/background.png",
        "flash_delay_us": 3350,
        "delay_from_emergence_us": 150,
        "pulse_width_us": 1300,
        "pressure_psi": 0.42,
        "emergence_time_us": 3200,
        "nozzle_center_px": [160, 80],
        "stock_solution": "water",
        "printer_head_id": "head_A",
        "label_key": "water_n1_pw1300",
    }
    _write_jsonl(run_dir / "frames.jsonl", [frame_row])

    analysis_row = {
        "process_name": mod.PROCESS_NAME,
        "phase_name": "pre_breakup_dataset_acquisition",
        "stage": "dataset_frame_analysis",
        "condition_id": "cond_0001",
        "condition_index": 1,
        "frame_id": "frame_001",
        "capture_id": "cap_frame",
        "capture_index": 2,
        "image_relpath": "captures/frame_0001.png",
        "background_capture_id": "cap_bg",
        "background_image_relpath": "captures/background.png",
        "overlay_capture_id": "cap_overlay",
        "overlay_image_relpath": "captures/overlay_0001.png",
        "delay_us": 3350,
        "delay_from_emergence_us": 150,
        "replicate_index": 1,
        "pressure_psi": 0.42,
        "pulse_width_us": 1300,
        "stock_solution": "water",
        "printer_head_id": "head_A",
        "nozzle_id": "n1",
        "label_key": "water_n1_pw1300",
        "emergence_time_us": 3200,
        "nozzle_center_px": [160, 80],
        "metrics": {"protrusion_length_px": 42, "distance_nozzle_to_neck_px": 18},
        "details": {"status": "ok", "contour_class": "attached"},
    }
    _write_jsonl(run_dir / "analysis.jsonl", [analysis_row])

    for name in ("background.png", "frame_0001.png", "overlay_0001.png"):
        (captures_dir / name).write_bytes(b"stub")

    labels_path = exp_dir / "labels.csv"
    with labels_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "label_key",
                "stock_solution",
                "printer_head_id",
                "nozzle_id",
                "pulse_width_us",
                "band_low_psi",
                "band_high_psi",
                "recommended_pressure_psi",
                "label_source_process",
                "label_source_run_id",
                "label_confidence",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "label_key": "water_n1_pw1300",
                "stock_solution": "water",
                "printer_head_id": "head_A",
                "nozzle_id": "n1",
                "pulse_width_us": 1300,
                "band_low_psi": 0.40,
                "band_high_psi": 0.45,
                "recommended_pressure_psi": 0.43,
                "label_source_process": "pressure_scan",
                "label_source_run_id": "run_pressure_scan",
                "label_confidence": 0.91,
                "notes": "trusted label",
            }
        )

    return exp_dir, run_dir, labels_path


def test_build_prebreakup_dataset_tables_flattens_and_joins_labels(tmp_path):
    exp_dir, run_dir, labels_path = _make_dataset_run(tmp_path)

    tables = mod.build_prebreakup_dataset_tables(exp_dir, labels_path=labels_path)

    assert tables["errors"] == []
    assert tables["run_count"] == 1
    assert tables["condition_count"] == 1
    assert tables["frame_count"] == 1
    run_row = tables["runs"][0]
    frame_row = tables["frames"][0]
    condition_row = tables["conditions"][0]

    assert run_row["run_id"] == "run_20260314_120000_deadbeef"
    assert run_row["condition_count"] == 1
    assert run_row["analysis_count"] == 1
    assert run_row["overlay_count"] == 1

    assert condition_row["background_image_exists"] is True
    assert condition_row["pressure_band_label"] == "good"
    assert condition_row["label_match_mode"] == "label_key"

    assert frame_row["run_id"] == run_row["run_id"]
    assert frame_row["image_exists"] is True
    assert frame_row["background_image_exists"] is True
    assert frame_row["overlay_image_exists"] is True
    assert frame_row["pressure_band_label"] == "good"
    assert frame_row["label_match_mode"] == "label_key"
    assert frame_row["label_band_low_psi"] == 0.40
    assert frame_row["label_band_high_psi"] == 0.45
    assert frame_row["analysis_metric_protrusion_length_px"] == 42
    assert frame_row["analysis_metric_distance_nozzle_to_neck_px"] == 18
    assert frame_row["analysis_detail_status"] == "ok"
    assert frame_row["analysis_detail_contour_class"] == "attached"
    assert frame_row["analysis_overlay_capture_id"] == "cap_overlay"
    assert frame_row["analysis_overlay_image_relpath"] == "captures/overlay_0001.png"
    assert frame_row["image_abs_path"].endswith("frame_0001.png")
    assert frame_row["overlay_image_abs_path"].endswith("overlay_0001.png")
    assert str(run_dir) in frame_row["image_abs_path"]


def test_export_prebreakup_dataset_tables_writes_csvs_and_manifest(tmp_path):
    exp_dir, _run_dir, labels_path = _make_dataset_run(tmp_path)
    out_dir = tmp_path / "exports"

    payload = mod.export_prebreakup_dataset_tables(
        exp_dir,
        out_dir=out_dir,
        labels_path=labels_path,
    )

    assert payload["run_count"] == 1
    assert payload["condition_count"] == 1
    assert payload["frame_count"] == 1
    assert payload["label_count"] == 1
    assert payload["parquet_ready"] is True

    runs_csv = out_dir / "prebreakup_dataset_runs.csv"
    conditions_csv = out_dir / "prebreakup_dataset_conditions.csv"
    frames_csv = out_dir / "prebreakup_dataset_frames.csv"
    manifest_json = out_dir / "prebreakup_dataset_export_manifest.json"

    assert runs_csv.exists()
    assert conditions_csv.exists()
    assert frames_csv.exists()
    assert manifest_json.exists()

    with frames_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["pressure_band_label"] == "good"
    assert rows[0]["label_match_mode"] == "label_key"
    assert rows[0]["analysis_metric_protrusion_length_px"] == "42"

    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    assert manifest["outputs"]["frames_csv"] == str(frames_csv)
    assert manifest["error_count"] == 0
