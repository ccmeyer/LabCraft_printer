import csv
import json
from pathlib import Path

import pytest

from tools.stream_analysis import dataset as dataset_mod
from tools.stream_analysis import online_report as mod


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
        "Predicted Volume (nL)",
        "Analysis Warnings",
    ]
    metadata_path = exp_dir / dataset_mod.METADATA_FILENAME
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with metadata_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return metadata_path


def _make_online_run(
    process_root: Path,
    *,
    run_id: str,
    replicate_index: int,
    gravimetric_nl: float,
    predicted_volume_nl: float,
    tail_start_delay_us: int,
    first_detachment_delay_us: int,
):
    run_dir = process_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        run_dir / "run_meta.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "process_name": dataset_mod.ONLINE_STREAM_PROCESS_NAME,
            "phase_name": "online_stream_calibration",
            "outcome": "completed",
            "error_message": "",
        },
    )

    slope = 0.02
    intercept = 0.0
    gravimetric_delay = gravimetric_nl / slope
    tail_rows = [
        {
            "phase": "tail_backtrack",
            "status": "accepted",
            "delay_from_emergence_us": 4000,
            "attached_width_px": 72.0,
            "visible_volume_nl": 80.0,
            "attached_bottom_clearance_px": 120.0,
            "attached_bottom_guard_hit": True,
            "warnings": ["attached_bottom_guard_hit"],
        },
        {
            "phase": "tail_backtrack",
            "status": "accepted",
            "delay_from_emergence_us": tail_start_delay_us,
            "attached_width_px": 70.0,
            "visible_volume_nl": 84.0,
            "attached_bottom_clearance_px": 108.0,
            "attached_bottom_guard_hit": True,
            "warnings": ["attached_bottom_guard_hit"],
            "tail_start_candidate": True,
        },
        {
            "phase": "tail_backtrack",
            "status": "accepted",
            "delay_from_emergence_us": first_detachment_delay_us,
            "attached_width_px": 65.0,
            "visible_volume_nl": 88.0,
            "attached_bottom_clearance_px": 96.0,
            "attached_bottom_guard_hit": True,
            "warnings": ["attached_bottom_guard_hit"],
            "separated_from_nozzle_landmark": True,
            "landmark_reason": "separated_from_nozzle",
        },
        {
            "phase": "tail_backtrack",
            "status": "accepted",
            "delay_from_emergence_us": 4700,
            "attached_width_px": 60.0,
            "visible_volume_nl": 92.0,
            "attached_bottom_clearance_px": 85.0,
            "attached_bottom_guard_hit": True,
            "warnings": ["attached_bottom_guard_hit"],
        },
    ]
    flow_rows = [
        {
            "phase": "flow_rate",
            "status": "accepted",
            "delay_from_emergence_us": 3000,
            "attached_width_px": 72.0,
            "visible_volume_nl": 60.0,
            "attached_bottom_clearance_px": 200.0,
            "warnings": [],
        },
        {
            "phase": "flow_rate",
            "status": "accepted",
            "delay_from_emergence_us": 3500,
            "attached_width_px": 72.0,
            "visible_volume_nl": 70.0,
            "attached_bottom_clearance_px": 150.0,
            "warnings": [],
        },
        {
            "phase": "flow_rate",
            "status": "accepted",
            "delay_from_emergence_us": 4000,
            "attached_width_px": 72.0,
            "visible_volume_nl": 80.0,
            "attached_bottom_clearance_px": 120.0,
            "warnings": [],
        },
    ]
    _write_jsonl(run_dir / "frames.jsonl", flow_rows + tail_rows)

    _write_json(
        run_dir / "flow_fit.json",
        {
            "fit": {
                "fit_status": "ok",
                "flow_rate_nl_per_us": slope,
                "flow_intercept_nl": intercept,
                "steady_rate_ci95_low_nl_per_us": 0.019,
                "steady_rate_ci95_high_nl_per_us": 0.021,
                "steady_rate_ci95_relative_width": 0.10,
                "steady_r2": 0.995,
            }
        },
    )
    _write_json(
        run_dir / "tail_fit.json",
        {
            "result": {
                "predicted_volume_nl": predicted_volume_nl,
                "predicted_stream_duration_us": tail_start_delay_us,
                "tail_phase": {
                    "status": "ok",
                    "tail_start_selection_method": "earliest_transition_before_confirmed_collapse",
                    "tail_start_delay_from_emergence_us": tail_start_delay_us,
                    "confirmed_collapse_delay_from_emergence_us": tail_start_delay_us + 100,
                    "last_plateau_delay_from_emergence_us": tail_start_delay_us - 100,
                    "landmark_reason": "separated_from_nozzle",
                },
            }
        },
    )

    return {
        "metadata_row": {
            "Dataset name": run_id,
            "Print PW": "3000",
            "Print Pressure": "1.2",
            "Rep": str(replicate_index),
            "Mass/print": f"{gravimetric_nl / 1000.0}",
            "Num printed": "10",
            "Capture Process": dataset_mod.ONLINE_STREAM_PROCESS_NAME,
            "Predicted Volume (nL)": f"{predicted_volume_nl}",
            "Analysis Warnings": "attached_bottom_guard_hit",
        },
        "gravimetric_delay": gravimetric_delay,
    }


def test_export_online_stream_report_writes_artifacts_and_expected_timing(tmp_path):
    pytest.importorskip("matplotlib")

    exp_dir = tmp_path / "Stream_report-20260410_120000"
    process_root = exp_dir / "calibration_recordings" / dataset_mod.ONLINE_STREAM_PROCESS_NAME
    first = _make_online_run(
        process_root,
        run_id="run_001",
        replicate_index=1,
        gravimetric_nl=90.0,
        predicted_volume_nl=84.0,
        tail_start_delay_us=4200,
        first_detachment_delay_us=4400,
    )
    second = _make_online_run(
        process_root,
        run_id="run_002",
        replicate_index=2,
        gravimetric_nl=88.0,
        predicted_volume_nl=83.0,
        tail_start_delay_us=4250,
        first_detachment_delay_us=4520,
    )
    _write_metadata_csv(exp_dir, [first["metadata_row"], second["metadata_row"]])

    payload = mod.export_online_stream_experiment_report(exp_dir)

    assert payload["run_count"] == 2
    assert payload["condition_count"] == 1

    summary_path = Path(payload["paths"]["run_summary_csv"])
    condition_path = Path(payload["paths"]["condition_summary_csv"])
    predicted_plot = Path(payload["paths"]["predicted_vs_gravimetric_png"])
    delay_plot = Path(payload["paths"]["delay_gap_by_condition_png"])

    assert summary_path.exists()
    assert condition_path.exists()
    assert predicted_plot.exists()
    assert delay_plot.exists()

    with summary_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    by_run = {row["run_id"]: row for row in rows}
    assert set(by_run) == {"run_001", "run_002"}

    run_one = by_run["run_001"]
    assert float(run_one["gravimetric_equality_delay_us"]) == pytest.approx(4500.0)
    assert float(run_one["gravimetric_minus_tail_start_us"]) == pytest.approx(300.0)
    assert float(run_one["gravimetric_minus_first_detachment_us"]) == pytest.approx(100.0)
    assert run_one["gravimetric_vs_detachment_status"] == "after_first_detachment_landmark"
    assert run_one["gravimetric_vs_observed_tail_status"] == "within_observed_tail_window"
    assert Path(run_one["run_report_png"]).exists()

    run_two = by_run["run_002"]
    assert float(run_two["gravimetric_equality_delay_us"]) == pytest.approx(4400.0)
    assert run_two["gravimetric_vs_detachment_status"] == "before_first_detachment_landmark"
    assert Path(run_two["run_report_png"]).exists()

    with condition_path.open("r", encoding="utf-8", newline="") as handle:
        condition_rows = list(csv.DictReader(handle))

    assert len(condition_rows) == 1
    condition_row = condition_rows[0]
    assert condition_row["run_count"] == "2"
    assert float(condition_row["gravimetric_minus_tail_start_us_mean"]) == pytest.approx(225.0)
    assert condition_row["gravimetric_after_detachment_count"] == "1"
    assert Path(condition_row["condition_overlay_png"]).exists()
