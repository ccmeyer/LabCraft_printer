from __future__ import annotations

import csv
import json
from pathlib import Path

from tools.stream_analysis import summary as mod


def _inventory_run(run_id: str, *, print_pw: str, print_pressure: str, rep: str, mass_print: str):
    return {
        "run_id": run_id,
        "run_dir": f"C:\\fake\\{run_id}",
        "metadata_match_status": "matched_csv",
        "metadata_row_index": 1,
        "outcome": "completed",
        "started_at_utc": "2026-03-28T00:00:00Z",
        "ended_at_utc": "2026-03-28T00:00:10Z",
        "metadata_dataset_name": run_id,
        "metadata_print_pw": print_pw,
        "metadata_print_pressure": print_pressure,
        "metadata_refuel_pw": "5000",
        "metadata_refuel_pressure": "0.8",
        "metadata_rep": rep,
        "metadata_num_printed": "141",
        "metadata_mass_print": mass_print,
    }


def _fake_stage5_run(run_id: str, partial_total_without_tail_nl: float):
    return {
        "summary": {
            "steady_fit_status": "ok",
            "steady_start_capture_index": 10,
            "steady_end_capture_index": 20,
            "steady_fit_point_count": 11,
            "steady_rate_nl_per_us": 0.02,
            "steady_rate_ci95_low_nl_per_us": 0.019,
            "steady_rate_ci95_high_nl_per_us": 0.021,
            "steady_rate_ci95_relative_width": 0.1,
            "steady_rate_confidence_status": "ok",
            "steady_r2": 0.998,
            "steady_nrmse": 0.01,
            "steady_width_plateau_px": 74.0,
            "tail_confirmation_capture_index": 66,
            "tail_confirmation_delay_from_emergence_us": 3300,
            "tail_detection_mode": "confirmed_persistent",
            "tail_start_selection_mode": "shoulder_adjusted",
            "preliminary_tail_start_capture_index": 60,
            "preliminary_tail_start_delay_from_emergence_us": 3000,
            "direct_final_tail_start_capture_index": 68,
            "direct_final_tail_start_delay_from_emergence_us": 3400,
            "tail_shoulder_end_capture_index": 68,
            "tail_shoulder_end_delay_from_emergence_us": 3400,
            "tail_start_capture_index": 70,
            "tail_start_delay_from_emergence_us": 3500,
            "tail_onset_status": "ok",
            "trusted_visible_volume_nl": 30.0,
            "middle_extrapolated_volume_nl": partial_total_without_tail_nl - 30.0,
            "partial_total_without_tail_nl": partial_total_without_tail_nl,
            "tail_volume_nl": None,
            "middle_extrapolation_status": "ok",
            "final_total_status": "tail_pending",
        },
        "phase_boundaries": {
            "steady_start_delay_from_emergence_us": 500,
            "steady_end_delay_from_emergence_us": 1000,
            "first_untrusted_capture_index": 25,
            "first_untrusted_delay_from_emergence_us": 1250,
            "tail_confirmation_capture_index": 66,
            "tail_confirmation_delay_from_emergence_us": 3300,
            "tail_detection_mode": "confirmed_persistent",
            "tail_start_selection_mode": "shoulder_adjusted",
            "preliminary_tail_start_capture_index": 60,
            "preliminary_tail_start_delay_from_emergence_us": 3000,
            "direct_final_tail_start_capture_index": 68,
            "direct_final_tail_start_delay_from_emergence_us": 3400,
            "tail_shoulder_end_capture_index": 68,
            "tail_shoulder_end_delay_from_emergence_us": 3400,
            "tail_start_capture_index": 70,
            "tail_start_delay_from_emergence_us": 3500,
        },
        "steady_fit_payload": {
            "run_id": run_id,
            "steady_fit_status": "ok",
        },
        "middle_payload": {
            "run_id": run_id,
            "tail_confirmation_capture_index": 66,
            "tail_confirmation_delay_from_emergence_us": 3300,
            "tail_detection_mode": "confirmed_persistent",
            "tail_start_selection_mode": "shoulder_adjusted",
            "preliminary_tail_start_capture_index": 60,
            "preliminary_tail_start_delay_from_emergence_us": 3000,
            "direct_final_tail_start_capture_index": 68,
            "direct_final_tail_start_delay_from_emergence_us": 3400,
            "tail_shoulder_end_capture_index": 68,
            "tail_shoulder_end_delay_from_emergence_us": 3400,
            "middle_extrapolation_status": "ok",
        },
        "stage4_run": {
            "fov_report": {
                "first_untrusted_capture_index": 25,
                "first_fov_exit_delay_from_emergence_us": 1250,
                "trigger_components": [],
            }
        },
    }


def test_metadata_metrics_parses_numeric_metadata_fields():
    metrics = mod._metadata_metrics(
        {
            "metadata_print_pw": "3000",
            "metadata_print_pressure": "0.65",
            "metadata_refuel_pw": "5000",
            "metadata_refuel_pressure": "0.8",
            "metadata_rep": "2",
            "metadata_num_printed": "141",
            "metadata_mass_print": "0.0711",
        }
    )

    assert metrics["print_pw_us"] == 3000
    assert metrics["print_pressure"] == 0.65
    assert metrics["refuel_pw_us"] == 5000
    assert metrics["refuel_pressure"] == 0.8
    assert metrics["replicate_index"] == 2
    assert metrics["num_printed"] == 141
    assert metrics["mass_per_print_mg"] == 0.0711


def test_gravimetric_fields_convert_mg_to_nl_and_keep_signed_residual():
    fields = mod._gravimetric_fields(
        mass_per_print_mg=0.0711,
        partial_total_without_tail_nl=80.56297459392785,
    )

    assert fields["gravimetric_total_nl"] == 71.1
    assert fields["signed_residual_nl"] < 0.0
    assert fields["partial_exceeds_gravimetric"] is True


def test_gravimetric_fields_return_nulls_when_inputs_missing():
    fields = mod._gravimetric_fields(
        mass_per_print_mg=None,
        partial_total_without_tail_nl=80.0,
    )

    assert fields["gravimetric_total_nl"] is None
    assert fields["signed_residual_nl"] is None
    assert fields["partial_to_gravimetric_ratio"] is None
    assert fields["partial_exceeds_gravimetric"] is None


def test_condition_summary_groups_by_pressure_and_pw():
    rows = [
        {"print_pressure": 0.65, "print_pw_us": 3000, "replicate_index": 1, "gravimetric_total_nl": 71.1, "partial_total_without_tail_nl": 80.5, "signed_residual_nl": -9.4, "signed_residual_fraction": -0.13, "partial_to_gravimetric_ratio": 1.13, "partial_exceeds_gravimetric": True},
        {"print_pressure": 0.65, "print_pw_us": 3000, "replicate_index": 2, "gravimetric_total_nl": 72.0, "partial_total_without_tail_nl": 79.0, "signed_residual_nl": -7.0, "signed_residual_fraction": -0.097, "partial_to_gravimetric_ratio": 1.097, "partial_exceeds_gravimetric": True},
        {"print_pressure": 0.8, "print_pw_us": 2500, "replicate_index": 1, "gravimetric_total_nl": 60.0, "partial_total_without_tail_nl": 58.0, "signed_residual_nl": 2.0, "signed_residual_fraction": 0.033, "partial_to_gravimetric_ratio": 0.967, "partial_exceeds_gravimetric": False},
    ]

    condition_rows = mod._condition_summary_rows(rows)

    assert len(condition_rows) == 2
    row_3000 = next(row for row in condition_rows if row["print_pw_us"] == 3000)
    assert row_3000["run_count"] == 2
    assert row_3000["overprediction_run_count"] == 2
    assert row_3000["signed_residual_nl_mean"] < 0.0


def test_export_stage6_summary_writes_outputs_and_progress(tmp_path, monkeypatch):
    output_root = tmp_path / "analysis" / "stream_characterization"
    inventory = {
        "experiment_root": str((tmp_path / "exp").resolve()),
        "selected_runs": [
            _inventory_run("run_a", print_pw="3000", print_pressure="0.65", rep="1", mass_print="0.0711"),
            _inventory_run("run_b", print_pw="2500", print_pressure="0.65", rep="2", mass_print="0.1040"),
        ],
        "frames_by_run_id": {
            "run_a": [{"capture_index": 1}],
            "run_b": [{"capture_index": 1}],
        },
    }
    progress_payloads = []

    monkeypatch.setattr(mod, "build_stage0_inventory", lambda *args, **kwargs: inventory)
    monkeypatch.setattr(
        mod.fit_mod,
        "_build_stage5_run",
        lambda run_id, frame_rows, **kwargs: _fake_stage5_run(
            run_id,
            80.5 if run_id == "run_a" else 100.0,
        ),
    )

    def _capture_progress(path, payload):
        progress_payloads.append(dict(payload))
        return mod._write_json(path, payload)

    monkeypatch.setattr(mod, "_write_progress", _capture_progress)

    payload = mod.export_stage6_summary(
        tmp_path / "exp",
        output_root=output_root,
    )

    assert payload["selected_run_count"] == 2
    assert payload["analyzed_run_count"] == 2
    assert (output_root / "experiment_summary.csv").exists()
    assert (output_root / "experiment_summary.json").exists()
    assert (output_root / "condition_summary.csv").exists()
    assert (output_root / "condition_summary.json").exists()
    assert (output_root / "summary_progress.json").exists()
    assert (output_root / "partial_vs_gravimetric_scatter.png").exists()
    assert (output_root / "signed_residual_by_condition.png").exists()
    assert (output_root / "signed_residual_fraction_by_condition.png").exists()
    assert (output_root / "signed_residual_vs_middle_duration.png").exists()
    assert (output_root / "runs" / "run_a" / "stage_06_summary" / "run_summary.json").exists()
    assert len(progress_payloads) >= 5
    assert progress_payloads[-1]["completed_run_count"] == 2
    assert progress_payloads[-1]["pending_run_count"] == 0

    with (output_root / "experiment_summary.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    row_a = next(row for row in rows if row["run_id"] == "run_a")
    assert float(row_a["gravimetric_total_nl"]) == 71.1
    assert float(row_a["partial_total_without_tail_nl"]) == 80.5
    assert float(row_a["signed_residual_nl"]) < 0.0
    assert row_a["steady_fit_point_count"] == "11"
    assert row_a["steady_rate_confidence_status"] == "ok"
    assert row_a["steady_rate_ci95_low_nl_per_us"] == "0.019"
    assert row_a["steady_rate_ci95_high_nl_per_us"] == "0.021"
    assert row_a["tail_detection_mode"] == "confirmed_persistent"
    assert row_a["tail_start_selection_mode"] == "shoulder_adjusted"
    assert row_a["preliminary_tail_start_capture_index"] == "60"
    assert row_a["direct_final_tail_start_capture_index"] == "68"
    assert row_a["tail_shoulder_end_capture_index"] == "68"
    assert row_a["tail_confirmation_capture_index"] == "66"
