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


def _write_metadata_csv(exp_dir: Path, rows):
    fieldnames = [
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
        "Capture Mode",
        "Capture Process",
        "Flow Fit Status",
        "Tail Phase Status",
        "Flow Rate (nL/us)",
        "Tail Start From Emergence (us)",
        "Predicted Stream Duration (us)",
        "Predicted Volume (nL)",
        "Analysis Warnings",
    ]
    metadata_path = exp_dir / mod.METADATA_FILENAME
    with metadata_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return metadata_path


def _make_run(
    process_root: Path,
    *,
    run_id: str,
    outcome: str = "completed",
    capture_count: int = 2,
    first_delay_us: int = 4750,
    capture_saved_after_result: bool = False,
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
        saved_event_index = capture_index * 3
        result_event_index = (capture_index * 3) + 1
        if capture_saved_after_result:
            result_event_index = capture_index * 3
            saved_event_index = (capture_index * 3) + 1
        saved_event = {
            "event_index": saved_event_index,
            "event_type": "capture_saved",
            "payload": {
                "capture_id": f"cap_{capture_index:06d}",
                "capture_role": "raw_frame",
                "image_relpath": image_relpath,
                "metadata": {
                    "stage_text": f"Capturing timecourse frame @ {flash_delay_us} us",
                },
            },
        }
        result_event = {
            "event_index": result_event_index,
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
        }
        per_capture_events = [
            {
                "event_index": (capture_index * 3) - 1,
                "event_type": "stage_changed",
                "payload": {"message": f"Setting flash_delay = {flash_delay_us} us"},
            },
        ]
        if capture_saved_after_result:
            per_capture_events.extend([result_event, saved_event])
        else:
            per_capture_events.extend([saved_event, result_event])
        events.extend(per_capture_events)

    _write_jsonl(run_dir / "events.jsonl", events)
    _write_jsonl(run_dir / "analysis.jsonl", [{"kind": "calibration_data_updated"}])
    return run_dir


def _make_online_run(
    process_root: Path,
    *,
    run_id: str,
    outcome: str = "completed",
):
    run_dir = process_root / run_id
    captures_dir = run_dir / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)

    run_meta = {
        "schema_version": 1,
        "run_id": run_id,
        "process_name": mod.ONLINE_STREAM_PROCESS_NAME,
        "phase_name": "online_stream_calibration",
        "started_at_utc": "2026-03-28T06:15:20.630838Z",
        "ended_at_utc": "2026-03-28T06:15:50.176087Z",
        "outcome": outcome,
        "error_message": "",
    }
    (run_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    capture_specs = [
        ("background", 1, 4700, "background"),
        ("flow", 2, 4800, "raw_frame"),
        ("tail", 3, 5200, "raw_frame"),
    ]
    events = []
    event_index = 1
    for label, capture_index, flash_delay_us, capture_role in capture_specs:
        image_name = f"cap_{capture_index:06d}_{label}.jpg"
        image_relpath = f"captures/{image_name}"
        (captures_dir / image_name).write_bytes(b"frame")
        num_droplets = 0 if label == "background" else 1
        events.extend(
            [
                {
                    "event_index": event_index,
                    "event_type": "settings_requested",
                    "payload": {
                        "settings": {"num_droplets": num_droplets},
                        "context": f"online_stream_{label}",
                    },
                },
                {
                    "event_index": event_index + 1,
                    "event_type": "settings_completed",
                    "payload": {
                        "settings": {"num_droplets": num_droplets},
                        "context": f"online_stream_{label}",
                    },
                },
                {
                    "event_index": event_index + 2,
                    "event_type": "capture_saved",
                    "payload": {
                        "capture_id": f"cap_{capture_index:06d}",
                        "capture_role": capture_role,
                        "image_relpath": image_relpath,
                        "metadata": {"stage_text": f"Online stream {label} @ {flash_delay_us} us"},
                    },
                },
                {
                    "event_index": event_index + 3,
                    "event_type": "capture_result",
                    "payload": {
                        "status": "success",
                        "stage_text": f"Online stream {label} @ {flash_delay_us} us",
                        "capture_ref": {
                            "capture_id": f"cap_{capture_index:06d}",
                            "capture_index": capture_index,
                            "capture_role": capture_role,
                            "image_relpath": image_relpath,
                            "width": 1088,
                            "height": 1456,
                            "captured_at_utc": f"2026-03-28T06:15:{20 + capture_index:02d}.000000Z",
                            "stage_text": f"Online stream {label} @ {flash_delay_us} us",
                        },
                    },
                },
            ]
        )
        event_index += 4

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

    _write_metadata_csv(
        exp_dir,
        [
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
                "Capture Mode": "timecourse",
                "Capture Process": mod.PROCESS_NAME,
            }
        ],
    )
    return exp_dir, matched_run, unmatched_run


def _make_mixed_experiment(tmp_path: Path):
    exp_dir = tmp_path / "Stream_characterization-20260327_225650"
    timecourse_root = exp_dir / "calibration_recordings" / mod.PROCESS_NAME
    online_root = exp_dir / "calibration_recordings" / mod.ONLINE_STREAM_PROCESS_NAME
    timecourse_root.mkdir(parents=True, exist_ok=True)
    online_root.mkdir(parents=True, exist_ok=True)

    timecourse_run = _make_run(timecourse_root, run_id="run_20260327_230520_9567e1ee")
    online_run = _make_online_run(online_root, run_id="run_20260327_231520_online")

    _write_metadata_csv(
        exp_dir,
        [
            {
                "Dataset name": timecourse_run.name,
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
                "Capture Mode": "timecourse",
                "Capture Process": mod.PROCESS_NAME,
            },
            {
                "Dataset name": online_run.name,
                "Print PW": "3000",
                "Print Pressure": "0.65",
                "Refuel PW": "5000",
                "Refuel Pressure": "0.8",
                "Rep": "2",
                "Starting mass": "1.0",
                "Starting flash": "2200",
                "Ending flash": "2214",
                "Ending mass": "4.5",
                "Mass Change": "3.5",
                "Num printed": "2",
                "Mass/print": "1.75",
                "CV": "",
                "Notes": "online row",
                "Capture Mode": "online_stream",
                "Capture Process": mod.ONLINE_STREAM_PROCESS_NAME,
                "Flow Fit Status": "warning",
                "Tail Phase Status": "resolved",
                "Flow Rate (nL/us)": "0.123456",
                "Tail Start From Emergence (us)": "5200",
                "Predicted Stream Duration (us)": "6400",
                "Predicted Volume (nL)": "0.7901",
                "Analysis Warnings": "tail advisory; budget low",
            },
        ],
    )
    _write_jsonl(
        exp_dir / mod.STREAM_CAPTURE_LOG_FILENAME,
        [
            {
                "timecourse_run_id": timecourse_run.name,
                "capture_mode": "timecourse",
                "dataset_process_name": mod.PROCESS_NAME,
                "gripper_refresh_suspended": False,
            },
            {
                "dataset_run_id": online_run.name,
                "timecourse_run_id": "legacy_wrong_run_id",
                "capture_mode": "online_stream",
                "dataset_process_name": mod.ONLINE_STREAM_PROCESS_NAME,
                "gripper_refresh_suspended": True,
            },
        ],
    )
    return exp_dir, timecourse_run, online_run


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


def test_build_frame_index_handles_capture_saved_after_capture_result(tmp_path):
    process_root = tmp_path / "calibration_recordings" / mod.PROCESS_NAME
    process_root.mkdir(parents=True, exist_ok=True)
    run_dir = _make_run(
        process_root,
        run_id="run_async_ordering",
        capture_saved_after_result=True,
    )

    frame_index = mod.build_frame_index(run_dir, run_id=run_dir.name)

    assert frame_index["run_id"] == run_dir.name
    assert len(frame_index["frames"]) == 2
    assert frame_index["frames"][0]["flash_delay_us"] == 4750
    assert frame_index["frames"][0]["image_relpath"] == "captures/cap_000001_raw_frame.jpg"
    assert frame_index["frames"][0]["image_exists"] is True


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


def test_resolve_experiment_root_accepts_online_process_root_and_run_dir(tmp_path):
    exp_dir, _timecourse_run, online_run = _make_mixed_experiment(tmp_path)

    online_process_root = exp_dir / "calibration_recordings" / mod.ONLINE_STREAM_PROCESS_NAME

    assert mod.resolve_experiment_root(online_process_root) == exp_dir.resolve()
    assert mod.resolve_experiment_root(online_run) == exp_dir.resolve()
    assert mod.resolve_experiment_root(online_run / "run_meta.json") == exp_dir.resolve()


def test_load_stream_capture_rows_prefers_dataset_run_id_for_online_runs(tmp_path):
    exp_dir, _timecourse_run, online_run = _make_mixed_experiment(tmp_path)

    rows_by_run_id, _log_path = mod.load_stream_capture_rows(exp_dir)

    assert online_run.name in rows_by_run_id
    assert "legacy_wrong_run_id" not in rows_by_run_id
    assert rows_by_run_id[online_run.name]["capture_mode"] == "online_stream"
    assert rows_by_run_id[online_run.name]["dataset_process_name"] == mod.ONLINE_STREAM_PROCESS_NAME


def test_build_stage0_inventory_discovers_timecourse_and_online_runs(tmp_path):
    exp_dir, timecourse_run, online_run = _make_mixed_experiment(tmp_path)

    inventory = mod.build_stage0_inventory(exp_dir)

    assert inventory["discovered_run_dir_count"] == 2
    assert inventory["matched_run_count"] == 2
    assert inventory["selected_run_count"] == 2
    assert inventory["process_root"].endswith(mod.PROCESS_NAME)

    rows_by_id = {row["run_id"]: row for row in inventory["selected_runs"]}
    assert set(rows_by_id) == {timecourse_run.name, online_run.name}
    assert rows_by_id[timecourse_run.name]["process_name"] == mod.PROCESS_NAME
    assert rows_by_id[online_run.name]["process_name"] == mod.ONLINE_STREAM_PROCESS_NAME
    assert rows_by_id[online_run.name]["capture_mode"] == "online_stream"
    assert rows_by_id[online_run.name]["dataset_process_name"] == mod.ONLINE_STREAM_PROCESS_NAME
    assert rows_by_id[online_run.name]["tracking_mode"] == mod.TRACKING_MODE_FIXED_EARLY
    assert rows_by_id[online_run.name]["timecourse_emergence_us"] is None
    assert rows_by_id[online_run.name]["timecourse_start_us"] is None
    assert rows_by_id[online_run.name]["timecourse_planned_frame_count"] is None


def test_export_stage0_inventory_handles_online_runs_without_timecourse_summary(tmp_path):
    exp_dir, _timecourse_run, online_run = _make_mixed_experiment(tmp_path)
    out_dir = tmp_path / "analysis" / "stream_characterization"

    payload = mod.export_stage0_inventory(exp_dir, output_root=out_dir)

    assert payload["selected_run_count"] == 2

    with (out_dir / "run_inventory.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = {row["run_id"]: row for row in csv.DictReader(handle)}

    assert rows[online_run.name]["process_name"] == mod.ONLINE_STREAM_PROCESS_NAME
    assert rows[online_run.name]["tracking_mode"] == mod.TRACKING_MODE_FIXED_EARLY
    assert rows[online_run.name]["timecourse_emergence_us"] == ""
    assert rows[online_run.name]["timecourse_start_us"] == ""
