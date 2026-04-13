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


def _make_online_run_with_images(
    process_root: Path,
    *,
    run_id: str,
    replicate_index: int,
    gravimetric_nl: float,
    predicted_volume_nl: float,
    tail_start_delay_us: int,
    first_detachment_delay_us: int,
    emergence_time_us: int = 1000,
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
    _write_json(
        run_dir / "plan_snapshot.json",
        {
            "schema_version": 1,
            "condition": {
                "emergence_time_us": emergence_time_us,
                "print_pressure_psi": 1.2,
                "print_pulse_width_us": 3000,
            },
            "analysis_config": {},
        },
    )

    def _frame_row(*, phase, delay_from_emergence_us, visible_volume_nl, attached_width_px, warnings=None, **extra):
        delay_us = int(emergence_time_us + delay_from_emergence_us)
        capture_index = int(extra.pop("capture_index"))
        capture_id = f"cap_{capture_index:06d}"
        return {
            "phase": phase,
            "status": "accepted",
            "delay_us": delay_us,
            "flash_delay_us": delay_us,
            "delay_from_emergence_us": delay_from_emergence_us,
            "capture_index": capture_index,
            "attached_width_px": attached_width_px,
            "visible_volume_nl": visible_volume_nl,
            "attached_bottom_clearance_px": extra.pop("attached_bottom_clearance_px", 120.0),
            "warnings": list(warnings or []),
            "image_ref": {
                "capture_id": capture_id,
                "capture_index": capture_index,
                "image_relpath": f"captures/{capture_id}_{phase}.jpg",
            },
            **extra,
        }

    flow_rows = [
        _frame_row(
            phase="flow_rate",
            delay_from_emergence_us=3000,
            visible_volume_nl=60.0,
            attached_width_px=72.0,
            capture_index=1,
            attached_bottom_clearance_px=200.0,
        ),
        _frame_row(
            phase="flow_rate",
            delay_from_emergence_us=3500,
            visible_volume_nl=70.0,
            attached_width_px=72.0,
            capture_index=2,
            attached_bottom_clearance_px=150.0,
        ),
        _frame_row(
            phase="flow_rate",
            delay_from_emergence_us=4000,
            visible_volume_nl=80.0,
            attached_width_px=72.0,
            capture_index=3,
            attached_bottom_clearance_px=120.0,
        ),
    ]
    tail_rows = [
        _frame_row(
            phase="tail_scout",
            delay_from_emergence_us=4100,
            visible_volume_nl=82.0,
            attached_width_px=72.0,
            capture_index=4,
            warnings=["attached_bottom_guard_hit"],
        ),
        _frame_row(
            phase="tail_scout",
            delay_from_emergence_us=4600,
            visible_volume_nl=90.0,
            attached_width_px=60.0,
            capture_index=5,
            warnings=["attached_bottom_guard_hit"],
        ),
        _frame_row(
            phase="tail_backtrack",
            delay_from_emergence_us=4000,
            visible_volume_nl=80.0,
            attached_width_px=72.0,
            capture_index=6,
            warnings=["attached_bottom_guard_hit"],
        ),
        _frame_row(
            phase="tail_backtrack",
            delay_from_emergence_us=tail_start_delay_us,
            visible_volume_nl=84.0,
            attached_width_px=70.0,
            capture_index=7,
            warnings=["attached_bottom_guard_hit"],
            tail_start_candidate=True,
        ),
        _frame_row(
            phase="tail_backtrack",
            delay_from_emergence_us=first_detachment_delay_us,
            visible_volume_nl=88.0,
            attached_width_px=65.0,
            capture_index=8,
            warnings=["attached_bottom_guard_hit"],
            separated_from_nozzle_landmark=True,
            landmark_reason="separated_from_nozzle",
        ),
        _frame_row(
            phase="tail_backtrack",
            delay_from_emergence_us=4700,
            visible_volume_nl=92.0,
            attached_width_px=60.0,
            capture_index=9,
            warnings=["attached_bottom_guard_hit"],
        ),
    ]
    _write_jsonl(run_dir / "frames.jsonl", flow_rows + tail_rows)

    slope = 0.02
    intercept = 0.0
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
                "steady_width_baseline_px": 72.0,
            }
        },
    )
    _write_json(
        run_dir / "tail_fit.json",
        {
            "tail_plan": {
                "search_method": "separation_landmark_backtrack_v1",
                "scout_anchor_delay_us": 3900,
            },
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
            },
        },
    )

    return {
        "run_dir": run_dir,
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
    }


def test_resolve_online_stream_correction_context_uses_stream_capture_log_and_emergence_analysis(tmp_path):
    exp_dir = tmp_path / "Stream_context-20260411_120000"
    online_run_dir = exp_dir / "calibration_recordings" / dataset_mod.ONLINE_STREAM_PROCESS_NAME / "run_online_001"
    online_run_dir.mkdir(parents=True, exist_ok=True)
    plan_snapshot = {"condition": {"emergence_time_us": 4700}}
    _write_json(online_run_dir / "plan_snapshot.json", plan_snapshot)

    emergence_run_dir = exp_dir / "calibration_recordings" / "DropletEmergenceCalibrationProcess" / "run_emergence_001"
    emergence_run_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        emergence_run_dir / "analysis.jsonl",
        [
            {
                "kind": "calibration_data_updated",
                "payload": {
                    "result": {
                        "flash_delay": 4700,
                        "selected_center_px": [531, 305],
                        "pressure_band_nozzle_center_px": [530, 304],
                    }
                },
            }
        ],
    )
    _write_jsonl(
        exp_dir / dataset_mod.STREAM_CAPTURE_LOG_FILENAME,
        [
            {
                "dataset_run_id": "run_online_001",
                "child_processes": [
                    {
                        "process_name": "DropletEmergenceCalibrationProcess",
                        "run_id": "run_emergence_001",
                    }
                ],
            }
        ],
    )

    context = mod._resolve_online_stream_correction_context(
        exp_dir,
        online_run_dir,
        plan_snapshot=plan_snapshot,
        correction_cache={},
    )

    assert context["emergence_run_id"] == "run_emergence_001"
    assert context["emergence_time_us"] == 4700
    assert context["nozzle_center_px"] == [531, 305]
    assert context["resolved_from_stream_capture_log"] is True
    assert context["selected_rule"]["candidate_id"] == "gh40_dlc-4_ebg45_sup2"


def test_export_online_stream_report_replays_with_chroma_correction(tmp_path, monkeypatch):
    pytest.importorskip("matplotlib")

    exp_dir = tmp_path / "Stream_report_chroma-20260411_120000"
    process_root = exp_dir / "calibration_recordings" / dataset_mod.ONLINE_STREAM_PROCESS_NAME
    run = _make_online_run_with_images(
        process_root,
        run_id="run_001",
        replicate_index=1,
        gravimetric_nl=90.0,
        predicted_volume_nl=84.0,
        tail_start_delay_us=4200,
        first_detachment_delay_us=4400,
    )
    _write_metadata_csv(exp_dir, [run["metadata_row"]])

    corrected_frame_rows = []
    for row in mod._iter_jsonl(run["run_dir"] / "frames.jsonl"):
        corrected = dict(row)
        if corrected.get("visible_volume_nl") is not None:
            corrected["visible_volume_nl"] = float(corrected["visible_volume_nl"]) + 2.0
        corrected_frame_rows.append(corrected)

    monkeypatch.setattr(
        mod,
        "_replay_corrected_online_stream_run",
        lambda *args, **kwargs: {
            "frame_rows": corrected_frame_rows,
            "fit": {
                "fit_status": "ok",
                "flow_rate_nl_per_us": 0.02,
                "flow_intercept_nl": 2.0,
                "steady_rate_ci95_low_nl_per_us": 0.019,
                "steady_rate_ci95_high_nl_per_us": 0.021,
                "steady_rate_ci95_relative_width": 0.10,
            },
            "tail_result": {
                "predicted_volume_nl": 86.0,
                "tail_phase": {
                    "status": "ok",
                    "tail_start_selection_method": "earliest_transition_before_confirmed_collapse",
                    "tail_start_delay_from_emergence_us": 4200,
                    "confirmed_collapse_delay_from_emergence_us": 4300,
                    "last_plateau_delay_from_emergence_us": 4100,
                    "landmark_reason": "separated_from_nozzle",
                },
            },
            "correction_context": {
                "selected_rule": dict(mod.chroma_proto_mod.SELECTED_V2_RULE),
            },
        },
    )

    payload = mod.export_online_stream_experiment_report(
        exp_dir,
        correction_mode="chroma_edge_v2",
    )

    assert payload["correction_mode"] == "chroma_edge_v2"
    assert payload["correction_rule"]["candidate_id"] == "gh40_dlc-4_ebg45_sup2"

    summary_path = Path(payload["paths"]["run_summary_csv"])
    assert summary_path.exists()
    with summary_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    row = rows[0]
    assert float(row["predicted_volume_nl"]) == pytest.approx(86.0)
    assert Path(payload["paths"]["predicted_vs_gravimetric_png"]).exists()
