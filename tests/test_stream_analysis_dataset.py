from __future__ import annotations

import csv
import json
from pathlib import Path

from tools.stream_analysis import dataset as mod


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _make_run(
    process_root: Path,
    *,
    run_id: str,
    outcome: str = "completed",
    capture_count: int = 2,
    first_delay_us: int = 4750,
):
    run_dir = process_root / run_id
    captures_dir = run_dir / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)

    run_meta = {
        "schema_version": 1,
        "run_id": run_id,
        "process_name": mod.PROCESS_NAME,
        "phase_name": "droplet_timecourse",
        "started_at_utc": "2026-03-28T06:05:20.630838Z",
        "ended_at_utc": "2026-03-28T06:05:50.176087Z",
        "outcome": outcome,
        "error_message": "",
    }
    (run_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    events = [
        {
            "event_index": 1,
            "event_type": "stage_changed",
            "payload": {
                "message": (
                    f"Timecourse: emergence=4800 us, start={first_delay_us} us, step=50 us, "
                    f"window=6000 us ({capture_count} frames)"
                )
            },
        }
    ]

    for offset in range(capture_count):
        capture_index = offset + 1
        flash_delay_us = first_delay_us + (50 * offset)
        image_name = f"cap_{capture_index:06d}_raw_frame.jpg"
        image_relpath = f"captures/{image_name}"
        (captures_dir / image_name).write_bytes(b"frame")
        events.extend(
            [
                {
                    "event_index": (capture_index * 3) - 1,
                    "event_type": "stage_changed",
                    "payload": {"message": f"Setting flash_delay = {flash_delay_us} us"},
                },
                {
                    "event_index": capture_index * 3,
                    "event_type": "capture_saved",
                    "payload": {
                        "capture_id": f"cap_{capture_index:06d}",
                        "capture_role": "raw_frame",
                        "image_relpath": image_relpath,
                        "metadata": {
                            "stage_text": f"Capturing timecourse frame @ {flash_delay_us} us",
                        },
                    },
                },
                {
                    "event_index": (capture_index * 3) + 1,
                    "event_type": "capture_result",
                    "payload": {
                        "status": "success",
                        "stage_text": f"Capturing timecourse frame @ {flash_delay_us} us",
                        "capture_ref": {
                            "capture_id": f"cap_{capture_index:06d}",
                            "capture_index": capture_index,
                            "capture_role": "raw_frame",
                            "image_relpath": image_relpath,
                            "width": 1088,
                            "height": 1456,
                            "captured_at_utc": f"2026-03-28T06:05:{20 + capture_index:02d}.000000Z",
                            "stage_text": f"Capturing timecourse frame @ {flash_delay_us} us",
                        },
                    },
                },
            ]
        )

    _write_jsonl(run_dir / "events.jsonl", events)
    _write_jsonl(run_dir / "analysis.jsonl", [{"kind": "calibration_data_updated"}])
    return run_dir


def _make_experiment(tmp_path: Path):
    exp_dir = tmp_path / "Stream_characterization-20260327_225650"
    process_root = exp_dir / "calibration_recordings" / mod.PROCESS_NAME
    process_root.mkdir(parents=True, exist_ok=True)

    matched_run = _make_run(process_root, run_id="run_20260327_230520_9567e1ee")
    unmatched_run = _make_run(
        process_root,
        run_id="run_20260327_225848_829e10c1",
        outcome="stopped",
        capture_count=1,
        first_delay_us=4900,
    )

    metadata_path = exp_dir / mod.METADATA_FILENAME
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
                "Dataset name": matched_run.name,
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
    return exp_dir, matched_run, unmatched_run


def test_build_frame_index_parses_flash_delay_and_timecourse(tmp_path):
    exp_dir, matched_run, _unmatched_run = _make_experiment(tmp_path)

    frame_index = mod.build_frame_index(matched_run, run_id=matched_run.name)

    assert frame_index["run_id"] == matched_run.name
    assert frame_index["timecourse_emergence_us"] == 4800
    assert frame_index["timecourse_start_us"] == 4750
    assert frame_index["timecourse_step_us"] == 50
    assert frame_index["timecourse_planned_frame_count"] == 2
    assert len(frame_index["frames"]) == 2
    assert frame_index["frames"][0]["flash_delay_us"] == 4750
    assert frame_index["frames"][0]["delay_from_emergence_us"] == -50
    assert frame_index["frames"][1]["flash_delay_us"] == 4800
    assert frame_index["frames"][1]["image_exists"] is True
    assert frame_index["frames"][1]["image_abs_path"].endswith("cap_000002_raw_frame.jpg")
    assert mod.resolve_experiment_root(exp_dir) == exp_dir.resolve()


def test_build_stage0_inventory_defaults_to_csv_matched_runs(tmp_path):
    exp_dir, matched_run, unmatched_run = _make_experiment(tmp_path)

    inventory = mod.build_stage0_inventory(exp_dir)

    assert inventory["metadata_row_count"] == 1
    assert inventory["discovered_run_dir_count"] == 2
    assert inventory["matched_run_count"] == 1
    assert inventory["selected_run_count"] == 1
    assert inventory["unmatched_run_count"] == 1
    assert inventory["selected_runs"][0]["run_id"] == matched_run.name
    assert inventory["selected_runs"][0]["metadata_print_pw"] == "3000"
    assert inventory["selected_runs"][0]["indexed_frame_count"] == 2
    assert inventory["unmatched_runs"][0]["run_id"] == unmatched_run.name
    assert inventory["unmatched_runs"][0]["metadata_match_status"] == "unmatched_run_dir"


def test_export_stage0_inventory_writes_artifacts(tmp_path):
    exp_dir, matched_run, unmatched_run = _make_experiment(tmp_path)
    out_dir = tmp_path / "analysis" / "stream_characterization"

    payload = mod.export_stage0_inventory(exp_dir, output_root=out_dir)

    assert payload["selected_run_count"] == 1
    assert payload["unmatched_run_count"] == 1
    assert payload["outputs"]["run_inventory_csv"] == str(out_dir / "run_inventory.csv")

    run_inventory_csv = out_dir / "run_inventory.csv"
    run_inventory_json = out_dir / "run_inventory.json"
    unmatched_csv = out_dir / "unmatched_runs.csv"
    manifest_json = out_dir / "inventory_manifest.json"
    frame_csv = out_dir / "runs" / matched_run.name / mod.STAGE_DIRNAME / "frame_index.csv"
    frame_json = out_dir / "runs" / matched_run.name / mod.STAGE_DIRNAME / "frame_index.json"

    assert run_inventory_csv.exists()
    assert run_inventory_json.exists()
    assert unmatched_csv.exists()
    assert manifest_json.exists()
    assert frame_csv.exists()
    assert frame_json.exists()

    with run_inventory_csv.open("r", encoding="utf-8", newline="") as handle:
        run_rows = list(csv.DictReader(handle))
    assert len(run_rows) == 1
    assert run_rows[0]["run_id"] == matched_run.name
    assert run_rows[0]["metadata_match_status"] == "matched_csv"
    assert run_rows[0]["indexed_frame_count"] == "2"

    with unmatched_csv.open("r", encoding="utf-8", newline="") as handle:
        unmatched_rows = list(csv.DictReader(handle))
    assert len(unmatched_rows) == 1
    assert unmatched_rows[0]["run_id"] == unmatched_run.name

    frame_payload = json.loads(frame_json.read_text(encoding="utf-8"))
    assert frame_payload["run_id"] == matched_run.name
    assert frame_payload["frame_count"] == 2
