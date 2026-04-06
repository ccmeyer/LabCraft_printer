from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tools.stream_analysis import fov as fov_mod
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
    phase_feature_rows = [
        {
            "run_id": run_id,
            "capture_id": f"cap_{capture_index:06d}",
            "capture_index": capture_index,
            "flash_delay_us": 4700 + (capture_index * 50),
            "delay_from_emergence_us": capture_index * 100,
            "total_visible_volume_nl": float(capture_index * 10),
            "volume_trust_label": (
                fov_mod.TRUST_LABEL_TRUSTED if capture_index <= 3 else fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT
            ),
            "attached_near_nozzle_width_median_px": 80.0 - float((capture_index - 1) * 1.5),
            "attached_near_nozzle_width_smoothed_px": 80.0 - float((capture_index - 1) * 1.5),
        }
        for capture_index in range(1, 6)
    ]
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
            "predicted_volume_uncertainty_width_nl": 4.0,
            "tail_volume_nl": None,
            "middle_extrapolation_status": "ok",
            "final_total_status": "tail_pending",
            "tail_peak_shrink_rate_delay_us": 3600,
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
            "flow_fit_positions": [0, 1, 2],
            "steady_rate_nl_per_us": 0.02,
            "steady_intercept_nl": 0.0,
        },
        "steady_fit": {
            "run_id": run_id,
            "steady_fit_status": "ok",
            "flow_fit_positions": [0, 1, 2],
            "steady_rate_nl_per_us": 0.02,
            "steady_intercept_nl": 0.0,
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
        "tail_onset": {
            "tail_confirmation_capture_index": 66,
            "tail_confirmation_delay_from_emergence_us": 3300,
            "preliminary_tail_start_capture_index": 60,
            "preliminary_tail_start_delay_from_emergence_us": 3000,
            "direct_final_tail_start_capture_index": 68,
            "direct_final_tail_start_delay_from_emergence_us": 3400,
            "tail_shoulder_end_capture_index": 68,
            "tail_shoulder_end_delay_from_emergence_us": 3400,
            "tail_start_capture_index": 70,
            "tail_start_delay_from_emergence_us": 3500,
            "tail_peak_shrink_rate_delay_us": 3600,
        },
        "stage4_run": {
            "fov_report": {
                "first_untrusted_capture_index": 25,
                "first_fov_exit_delay_from_emergence_us": 1250,
                "trigger_components": [],
            }
        },
        "phase_feature_rows": phase_feature_rows,
    }


def _condition_feature_row(
    run_id: str,
    capture_index: int,
    *,
    delay_from_emergence_us: int,
    total_visible_volume_nl: float | None,
    width_px: float | None,
    trust_label: str,
):
    return {
        "run_id": run_id,
        "capture_id": f"cap_{capture_index:06d}",
        "capture_index": capture_index,
        "flash_delay_us": 4700 + (capture_index * 50),
        "delay_from_emergence_us": delay_from_emergence_us,
        "total_visible_volume_nl": total_visible_volume_nl,
        "volume_trust_label": trust_label,
        "attached_near_nozzle_width_median_px": width_px,
        "attached_near_nozzle_width_smoothed_px": width_px,
    }


def _condition_bundle(
    run_id: str,
    *,
    replicate_index: int | None,
    feature_rows: list[dict],
    steady_rate_nl_per_us: float,
    flow_fit_start_after_first_trusted_us: float,
    flow_fit_end_to_fov_exit_us: float,
    tail_confirmation_delay_from_emergence_us: float,
    tail_start_delay_from_emergence_us: float,
    partial_total_without_tail_nl: float,
    predicted_volume_uncertainty_width_nl: float,
    print_pressure: float = 0.65,
    print_pw_us: int = 3000,
):
    summary_row = {
        "run_id": run_id,
        "print_pressure": print_pressure,
        "print_pw_us": print_pw_us,
        "replicate_index": replicate_index,
        "steady_rate_nl_per_us": steady_rate_nl_per_us,
        "tail_confirmation_delay_from_emergence_us": tail_confirmation_delay_from_emergence_us,
        "tail_start_delay_from_emergence_us": tail_start_delay_from_emergence_us,
        "partial_total_without_tail_nl": partial_total_without_tail_nl,
        "predicted_volume_uncertainty_width_nl": predicted_volume_uncertainty_width_nl,
        "preliminary_tail_start_delay_from_emergence_us": tail_start_delay_from_emergence_us - 180.0,
        "direct_final_tail_start_delay_from_emergence_us": tail_start_delay_from_emergence_us - 90.0,
        "tail_shoulder_end_delay_from_emergence_us": tail_start_delay_from_emergence_us - 40.0,
        "tail_peak_shrink_rate_delay_us": tail_start_delay_from_emergence_us + 70.0,
        "fov_exit_delay_from_emergence_us": max(
            float(row["delay_from_emergence_us"])
            for row in feature_rows
            if row.get("delay_from_emergence_us") is not None
        ),
    }
    return {
        "condition_key": mod._condition_key(summary_row),
        "run_id": run_id,
        "replicate_index": replicate_index,
        "summary_row": summary_row,
        "phase_feature_rows": feature_rows,
        "steady_fit": {
            "steady_fit_status": "ok",
            "steady_rate_nl_per_us": steady_rate_nl_per_us,
            "steady_intercept_nl": 0.0,
            "flow_fit_positions": [0, 1, 2],
        },
        "tail_onset": {},
        "phase_boundaries": {
            "steady_start_delay_from_emergence_us": feature_rows[0]["delay_from_emergence_us"],
            "steady_end_delay_from_emergence_us": feature_rows[2]["delay_from_emergence_us"],
            "first_untrusted_delay_from_emergence_us": summary_row["fov_exit_delay_from_emergence_us"],
        },
        "fov_report": {
            "first_fov_exit_delay_from_emergence_us": summary_row["fov_exit_delay_from_emergence_us"],
        },
        "steady_fit_review_metrics": {
            "flow_fit_start_after_first_trusted_us": flow_fit_start_after_first_trusted_us,
            "flow_fit_end_to_fov_exit_us": flow_fit_end_to_fov_exit_us,
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
    assert (output_root / "condition_consistency_summary.csv").exists()
    assert (output_root / "condition_consistency_summary.json").exists()
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


def test_condition_consistency_rows_ok_and_tail_variance(tmp_path):
    run_a = _condition_bundle(
        "run_a",
        replicate_index=1,
        feature_rows=[
            _condition_feature_row("run_a", 1, delay_from_emergence_us=0, total_visible_volume_nl=0.0, width_px=80.0, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_a", 2, delay_from_emergence_us=100, total_visible_volume_nl=10.0, width_px=79.0, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_a", 3, delay_from_emergence_us=200, total_visible_volume_nl=20.0, width_px=78.0, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_a", 4, delay_from_emergence_us=300, total_visible_volume_nl=30.0, width_px=72.0, trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT),
        ],
        steady_rate_nl_per_us=0.100,
        flow_fit_start_after_first_trusted_us=0.0,
        flow_fit_end_to_fov_exit_us=100.0,
        tail_confirmation_delay_from_emergence_us=2900.0,
        tail_start_delay_from_emergence_us=3200.0,
        partial_total_without_tail_nl=80.0,
        predicted_volume_uncertainty_width_nl=4.0,
    )
    run_b = _condition_bundle(
        "run_b",
        replicate_index=2,
        feature_rows=[
            _condition_feature_row("run_b", 1, delay_from_emergence_us=0, total_visible_volume_nl=0.4, width_px=80.3, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_b", 2, delay_from_emergence_us=100, total_visible_volume_nl=10.3, width_px=79.1, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_b", 3, delay_from_emergence_us=200, total_visible_volume_nl=20.2, width_px=78.2, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_b", 4, delay_from_emergence_us=300, total_visible_volume_nl=30.1, width_px=72.1, trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT),
        ],
        steady_rate_nl_per_us=0.102,
        flow_fit_start_after_first_trusted_us=10.0,
        flow_fit_end_to_fov_exit_us=110.0,
        tail_confirmation_delay_from_emergence_us=2910.0,
        tail_start_delay_from_emergence_us=3400.0,
        partial_total_without_tail_nl=81.0,
        predicted_volume_uncertainty_width_nl=4.5,
    )

    rows = mod._condition_consistency_rows([run_a, run_b], review_dir=tmp_path / "consistency")

    assert len(rows) == 1
    row = rows[0]
    assert row["consistency_status"] == "ok"
    assert row["vt_band_sample_count"] > 0
    assert row["width_band_sample_count"] > 0
    assert row["trusted_vt_band_width_nl_median"] < 1.0
    assert row["width_band_width_px_median"] < 1.0
    assert row["tail_start_delay_from_emergence_us_std"] > 0.0
    assert row["vt_overlay_png"]
    assert Path(row["vt_overlay_png"]).exists()
    assert row["width_overlay_png"]
    assert Path(row["width_overlay_png"]).exists()


def test_condition_consistency_rows_singleton_condition(tmp_path):
    run_a = _condition_bundle(
        "run_a",
        replicate_index=1,
        feature_rows=[
            _condition_feature_row("run_a", 1, delay_from_emergence_us=0, total_visible_volume_nl=0.0, width_px=80.0, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_a", 2, delay_from_emergence_us=100, total_visible_volume_nl=10.0, width_px=79.0, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_a", 3, delay_from_emergence_us=200, total_visible_volume_nl=20.0, width_px=78.0, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
        ],
        steady_rate_nl_per_us=0.10,
        flow_fit_start_after_first_trusted_us=0.0,
        flow_fit_end_to_fov_exit_us=100.0,
        tail_confirmation_delay_from_emergence_us=2900.0,
        tail_start_delay_from_emergence_us=3200.0,
        partial_total_without_tail_nl=80.0,
        predicted_volume_uncertainty_width_nl=4.0,
    )

    rows = mod._condition_consistency_rows([run_a], review_dir=tmp_path / "consistency")

    assert rows[0]["consistency_status"] == "insufficient_runs"
    assert rows[0]["vt_overlay_png"] is None
    assert rows[0]["width_overlay_png"] is None


def test_condition_consistency_rows_no_common_vt_samples(tmp_path):
    run_a = _condition_bundle(
        "run_a",
        replicate_index=1,
        feature_rows=[
            _condition_feature_row("run_a", 1, delay_from_emergence_us=0, total_visible_volume_nl=0.0, width_px=80.0, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_a", 2, delay_from_emergence_us=100, total_visible_volume_nl=10.0, width_px=79.0, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_a", 3, delay_from_emergence_us=200, total_visible_volume_nl=20.0, width_px=78.0, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
        ],
        steady_rate_nl_per_us=0.10,
        flow_fit_start_after_first_trusted_us=0.0,
        flow_fit_end_to_fov_exit_us=100.0,
        tail_confirmation_delay_from_emergence_us=2900.0,
        tail_start_delay_from_emergence_us=3200.0,
        partial_total_without_tail_nl=80.0,
        predicted_volume_uncertainty_width_nl=4.0,
    )
    run_b = _condition_bundle(
        "run_b",
        replicate_index=2,
        feature_rows=[
            _condition_feature_row("run_b", 1, delay_from_emergence_us=0, total_visible_volume_nl=None, width_px=80.2, trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT),
            _condition_feature_row("run_b", 2, delay_from_emergence_us=100, total_visible_volume_nl=None, width_px=79.2, trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT),
            _condition_feature_row("run_b", 3, delay_from_emergence_us=200, total_visible_volume_nl=None, width_px=78.2, trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT),
            _condition_feature_row("run_b", 4, delay_from_emergence_us=1000, total_visible_volume_nl=40.0, width_px=77.5, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_b", 5, delay_from_emergence_us=1100, total_visible_volume_nl=50.0, width_px=76.5, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_b", 6, delay_from_emergence_us=1200, total_visible_volume_nl=60.0, width_px=75.5, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
        ],
        steady_rate_nl_per_us=0.11,
        flow_fit_start_after_first_trusted_us=20.0,
        flow_fit_end_to_fov_exit_us=120.0,
        tail_confirmation_delay_from_emergence_us=3000.0,
        tail_start_delay_from_emergence_us=3300.0,
        partial_total_without_tail_nl=82.0,
        predicted_volume_uncertainty_width_nl=4.2,
    )

    rows = mod._condition_consistency_rows([run_a, run_b], review_dir=tmp_path / "consistency")

    assert rows[0]["consistency_status"] == "no_common_vt_samples"
    assert rows[0]["vt_band_sample_count"] == 0
    assert rows[0]["width_band_sample_count"] > 0


def test_condition_consistency_rows_no_common_width_samples(tmp_path):
    run_a = _condition_bundle(
        "run_a",
        replicate_index=1,
        feature_rows=[
            _condition_feature_row("run_a", 1, delay_from_emergence_us=0, total_visible_volume_nl=0.0, width_px=80.0, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_a", 2, delay_from_emergence_us=100, total_visible_volume_nl=10.0, width_px=79.0, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_a", 3, delay_from_emergence_us=200, total_visible_volume_nl=20.0, width_px=78.0, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
        ],
        steady_rate_nl_per_us=0.10,
        flow_fit_start_after_first_trusted_us=0.0,
        flow_fit_end_to_fov_exit_us=100.0,
        tail_confirmation_delay_from_emergence_us=2900.0,
        tail_start_delay_from_emergence_us=3200.0,
        partial_total_without_tail_nl=80.0,
        predicted_volume_uncertainty_width_nl=4.0,
    )
    run_b = _condition_bundle(
        "run_b",
        replicate_index=2,
        feature_rows=[
            _condition_feature_row("run_b", 1, delay_from_emergence_us=0, total_visible_volume_nl=0.2, width_px=None, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_b", 2, delay_from_emergence_us=100, total_visible_volume_nl=10.2, width_px=None, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_b", 3, delay_from_emergence_us=200, total_visible_volume_nl=20.2, width_px=None, trust_label=fov_mod.TRUST_LABEL_TRUSTED),
            _condition_feature_row("run_b", 4, delay_from_emergence_us=1000, total_visible_volume_nl=None, width_px=78.5, trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT),
            _condition_feature_row("run_b", 5, delay_from_emergence_us=1100, total_visible_volume_nl=None, width_px=77.5, trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT),
            _condition_feature_row("run_b", 6, delay_from_emergence_us=1200, total_visible_volume_nl=None, width_px=76.5, trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT),
        ],
        steady_rate_nl_per_us=0.11,
        flow_fit_start_after_first_trusted_us=20.0,
        flow_fit_end_to_fov_exit_us=120.0,
        tail_confirmation_delay_from_emergence_us=3000.0,
        tail_start_delay_from_emergence_us=3300.0,
        partial_total_without_tail_nl=82.0,
        predicted_volume_uncertainty_width_nl=4.2,
    )

    rows = mod._condition_consistency_rows([run_a, run_b], review_dir=tmp_path / "consistency")

    assert rows[0]["consistency_status"] == "no_common_width_samples"
    assert rows[0]["vt_band_sample_count"] > 0
    assert rows[0]["width_band_sample_count"] == 0


def test_export_stage6_summary_condition_consistency_matches_between_raw_and_cache(tmp_path, monkeypatch):
    raw_output_root = tmp_path / "raw_analysis"
    cache_output_root = tmp_path / "cache_analysis"
    inventory = {
        "experiment_root": str((tmp_path / "exp").resolve()),
        "selected_runs": [
            _inventory_run("run_a", print_pw="3000", print_pressure="0.65", rep="1", mass_print="0.0711"),
            _inventory_run("run_b", print_pw="3000", print_pressure="0.65", rep="2", mass_print="0.0712"),
        ],
        "frames_by_run_id": {
            "run_a": [{"capture_index": 1}],
            "run_b": [{"capture_index": 1}],
        },
    }
    raw_stage5_runs = {
        "run_a": _fake_stage5_run("run_a", 80.0),
        "run_b": _fake_stage5_run("run_b", 80.5),
    }
    cache_root = tmp_path / "cache_root"
    cache_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mod, "build_stage0_inventory", lambda *args, **kwargs: inventory)
    monkeypatch.setattr(
        mod.fit_mod,
        "_build_stage5_run",
        lambda run_id, frame_rows, **kwargs: raw_stage5_runs[run_id],
    )

    raw_payload = mod.export_stage6_summary(tmp_path / "exp", output_root=raw_output_root)

    import tools.stream_analysis.review_cache as review_cache_mod

    selected_entries = []
    phase_input_csv = cache_root / "phase_input.csv"
    phase_input_csv.write_text("capture_index\n1\n", encoding="utf-8")
    for run_id in ("run_a", "run_b"):
        run_context_json = cache_root / f"{run_id}_run_context.json"
        run_context_json.write_text(
            json.dumps(
                {
                    "metadata_snapshot": {
                        "run_id": run_id,
                        "run_dir": f"C:\\fake\\{run_id}",
                        "metadata_match_status": "matched_csv",
                        "metadata_row_index": 1,
                        "outcome": "completed",
                        "started_at_utc": "2026-03-28T00:00:00Z",
                        "ended_at_utc": "2026-03-28T00:00:10Z",
                        "metadata_dataset_name": run_id,
                        "metadata_print_pw": "3000",
                        "metadata_print_pressure": "0.65",
                        "metadata_refuel_pw": "5000",
                        "metadata_refuel_pressure": "0.8",
                        "metadata_rep": "1" if run_id == "run_a" else "2",
                        "metadata_num_printed": "141",
                        "metadata_mass_print": "0.0711" if run_id == "run_a" else "0.0712",
                    },
                    "metadata_metrics": {
                        "print_pw_us": 3000,
                        "print_pressure": 0.65,
                        "refuel_pw_us": 5000,
                        "refuel_pressure": 0.8,
                        "replicate_index": 1 if run_id == "run_a" else 2,
                        "num_printed": 141,
                        "mass_per_print_mg": 0.0711 if run_id == "run_a" else 0.0712,
                    },
                    "frozen_anchors": {},
                    "frozen_steady_fit": {},
                    "fov_report": {},
                    "source": {"kind": "imported_stage5"},
                    "default_include_in_gravimetric_plots": True,
                    "gravimetric_reference_status": "ok",
                }
            ),
            encoding="utf-8",
        )
        selected_entries.append(
            {
                "run_id": run_id,
                "run_context": json.loads(run_context_json.read_text(encoding="utf-8")),
                "paths": {
                    "phase_input_csv": str(phase_input_csv),
                    "run_context_json": str(run_context_json),
                },
            }
        )

    monkeypatch.setattr(review_cache_mod, "_selected_cache_entries", lambda *args, **kwargs: selected_entries)
    monkeypatch.setattr(review_cache_mod, "_load_csv_rows", lambda path: [{"capture_index": "1"}])
    monkeypatch.setattr(
        mod.fit_mod,
        "_build_stage5_review_run",
        lambda run_id, phase_input_rows, **kwargs: raw_stage5_runs[run_id],
    )

    cache_payload = mod.export_stage6_summary(
        cache_root=cache_root,
        output_root=cache_output_root,
    )

    raw_rows = json.loads((raw_output_root / "condition_consistency_summary.json").read_text(encoding="utf-8"))["rows"]
    cache_rows = json.loads((cache_output_root / "condition_consistency_summary.json").read_text(encoding="utf-8"))["rows"]

    def _normalized(rows):
        normalized_rows = []
        for row in rows:
            normalized = dict(row)
            normalized["vt_overlay_png"] = None if not normalized.get("vt_overlay_png") else "__plot__"
            normalized["width_overlay_png"] = None if not normalized.get("width_overlay_png") else "__plot__"
            normalized_rows.append(normalized)
        return normalized_rows

    assert raw_payload["eligible_condition_count"] == cache_payload["eligible_condition_count"] == 1
    assert raw_payload["plotted_condition_count"] == cache_payload["plotted_condition_count"] == 1
    assert _normalized(raw_rows) == _normalized(cache_rows)
