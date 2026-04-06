from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tools.stream_analysis import fit as fit_mod
from tools.stream_analysis import fov as fov_mod
from tools.stream_analysis import review_cache as mod


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


def _phase_feature_row(
    capture_index: int,
    *,
    delay_from_emergence_us: int,
    total_visible_volume_nl: float,
    width_px: float,
    trust_label: str,
):
    return {
        "run_id": "run_a",
        "capture_id": f"cap_{capture_index:06d}",
        "capture_index": capture_index,
        "flash_delay_us": 4700 + (capture_index * 50),
        "delay_from_emergence_us": delay_from_emergence_us,
        "total_visible_volume_nl": total_visible_volume_nl,
        "volume_trust_label": trust_label,
        "attached_near_nozzle_width_median_px": width_px,
        "attached_near_nozzle_width_smoothed_px": width_px,
        "phase_label": "steady",
        "steady_candidate": True,
        "steady_selected": capture_index <= 3,
        "tail_drop_candidate": capture_index >= 5,
        "tail_confirmation_frame": capture_index == 5,
        "tail_shoulder_end_frame": False,
        "tail_start_frame": capture_index == 4,
    }


def _write_stage5_source_artifacts(source_root: Path, run_id: str):
    stage_dir = source_root / "runs" / run_id / fit_mod.FIT_STAGE_DIRNAME
    stage_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        _phase_feature_row(
            1,
            delay_from_emergence_us=100,
            total_visible_volume_nl=10.0,
            width_px=80.0,
            trust_label=fov_mod.TRUST_LABEL_TRUSTED,
        ),
        _phase_feature_row(
            2,
            delay_from_emergence_us=200,
            total_visible_volume_nl=20.0,
            width_px=80.0,
            trust_label=fov_mod.TRUST_LABEL_TRUSTED,
        ),
        _phase_feature_row(
            3,
            delay_from_emergence_us=300,
            total_visible_volume_nl=30.0,
            width_px=80.0,
            trust_label=fov_mod.TRUST_LABEL_TRUSTED,
        ),
        _phase_feature_row(
            4,
            delay_from_emergence_us=400,
            total_visible_volume_nl=31.0,
            width_px=76.0,
            trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        ),
        _phase_feature_row(
            5,
            delay_from_emergence_us=500,
            total_visible_volume_nl=32.0,
            width_px=70.0,
            trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        ),
    ]
    with (stage_dir / "phase_features.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fit_mod.PHASE_FEATURE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    (stage_dir / "steady_fit.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "steady_fit_status": "ok",
                "steady_capture_indices": [1, 2, 3],
                "steady_start_capture_index": 1,
                "steady_end_capture_index": 3,
                "steady_rate_nl_per_us": 0.01,
                "steady_intercept_nl": 0.0,
                "steady_r2": 1.0,
                "steady_nrmse": 0.0,
                "steady_width_plateau_px": 80.0,
                "steady_width_span_px": 0.0,
                "steady_width_tolerance_px": 4.0,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (stage_dir / "middle_extrapolation.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "trusted_visible_volume_nl": 30.0,
                "first_untrusted_capture_index": 4,
                "first_untrusted_delay_from_emergence_us": 400,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (stage_dir / "phase_boundaries.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "steady_start_delay_from_emergence_us": 100,
                "steady_end_delay_from_emergence_us": 300,
                "first_untrusted_capture_index": 4,
                "first_untrusted_delay_from_emergence_us": 400,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (stage_dir / "fit_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "fov_report": {
                    "first_untrusted_capture_index": 4,
                    "first_fov_exit_delay_from_emergence_us": 400,
                    "trigger_components": [],
                },
                "width_smooth_window": 5,
                "tail_drop_frac": 0.08,
                "tail_persist_frames": 3,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _fake_stage5_run(run_id: str):
    phase_feature_rows = [
        _phase_feature_row(
            1,
            delay_from_emergence_us=100,
            total_visible_volume_nl=10.0,
            width_px=80.0,
            trust_label=fov_mod.TRUST_LABEL_TRUSTED,
        ),
        _phase_feature_row(
            2,
            delay_from_emergence_us=200,
            total_visible_volume_nl=20.0,
            width_px=80.0,
            trust_label=fov_mod.TRUST_LABEL_TRUSTED,
        ),
        _phase_feature_row(
            3,
            delay_from_emergence_us=300,
            total_visible_volume_nl=30.0,
            width_px=80.0,
            trust_label=fov_mod.TRUST_LABEL_TRUSTED,
        ),
    ]
    return {
        "phase_feature_rows": phase_feature_rows,
        "steady_fit_payload": {
            "run_id": run_id,
            "steady_fit_status": "ok",
            "steady_capture_indices": [1, 2, 3],
            "steady_start_capture_index": 1,
            "steady_end_capture_index": 3,
            "steady_rate_nl_per_us": 0.01,
            "steady_intercept_nl": 0.0,
            "steady_r2": 1.0,
            "steady_nrmse": 0.0,
            "steady_width_plateau_px": 80.0,
            "steady_width_span_px": 0.0,
            "steady_width_tolerance_px": 4.0,
        },
        "middle_payload": {
            "run_id": run_id,
            "trusted_visible_volume_nl": 30.0,
            "first_untrusted_capture_index": 4,
            "first_untrusted_delay_from_emergence_us": 400,
        },
        "stage4_run": {
            "fov_report": {
                "first_untrusted_capture_index": 4,
                "first_fov_exit_delay_from_emergence_us": 400,
                "trigger_components": [],
            }
        },
    }


def _fake_review_run(run_id: str, partial_total_without_tail_nl: float):
    feature_rows = [
        _phase_feature_row(
            1,
            delay_from_emergence_us=100,
            total_visible_volume_nl=10.0,
            width_px=80.0,
            trust_label=fov_mod.TRUST_LABEL_TRUSTED,
        ),
        _phase_feature_row(
            2,
            delay_from_emergence_us=200,
            total_visible_volume_nl=20.0,
            width_px=80.0,
            trust_label=fov_mod.TRUST_LABEL_TRUSTED,
        ),
        _phase_feature_row(
            3,
            delay_from_emergence_us=300,
            total_visible_volume_nl=30.0,
            width_px=80.0,
            trust_label=fov_mod.TRUST_LABEL_TRUSTED,
        ),
        _phase_feature_row(
            4,
            delay_from_emergence_us=400,
            total_visible_volume_nl=31.0,
            width_px=76.0,
            trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        ),
        _phase_feature_row(
            5,
            delay_from_emergence_us=500,
            total_visible_volume_nl=32.0,
            width_px=70.0,
            trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        ),
    ]
    return {
        "phase_feature_rows": feature_rows,
        "summary": {
            "steady_fit_status": "ok",
            "steady_start_capture_index": 1,
            "steady_end_capture_index": 3,
            "plateau_capture_indices": [1, 2, 3],
            "plateau_point_count": 3,
            "flow_fit_capture_indices": [1, 2, 3],
            "flow_fit_start_capture_index": 1,
            "flow_fit_end_capture_index": 3,
            "flow_fit_point_count": 3,
            "flow_fit_eligible_point_count": 3,
            "flow_fit_backfill_point_count": 0,
            "flow_fit_outlier_prune_status": "legacy_unspecified",
            "flow_fit_dropped_outlier_capture_index": None,
            "flow_fit_dropped_outlier_delay_from_emergence_us": None,
            "flow_fit_dropped_outlier_local_deviation_nl": None,
            "steady_fit_point_count": 3,
            "steady_rate_nl_per_us": 0.01,
            "steady_rate_ci95_low_nl_per_us": 0.009,
            "steady_rate_ci95_high_nl_per_us": 0.011,
            "steady_rate_ci95_relative_width": 0.2,
            "steady_rate_ci95_contains_central": True,
            "steady_rate_confidence_status": "ok",
            "steady_r2": 1.0,
            "steady_nrmse": 0.0,
            "steady_width_plateau_px": 80.0,
            "tail_confirmation_capture_index": 5,
            "tail_confirmation_delay_from_emergence_us": 500,
            "tail_detection_mode": "confirmed_persistent",
            "tail_start_selection_mode": "direct_backtrack",
            "tail_start_refinement_mode": "legacy",
            "tail_start_band_selection_status": None,
            "tail_in_band_candidate_count": 0,
            "preliminary_tail_start_capture_index": 4,
            "preliminary_tail_start_delay_from_emergence_us": 400,
            "direct_final_tail_start_capture_index": 4,
            "direct_final_tail_start_delay_from_emergence_us": 400,
            "tail_shoulder_end_capture_index": None,
            "tail_shoulder_end_delay_from_emergence_us": None,
            "tail_start_capture_index": 4,
            "tail_start_delay_from_emergence_us": 400,
            "tail_onset_status": "ok",
            "tail_start_score": None,
            "tail_score_candidate_count": 2,
            "tail_score_window_start_capture_index": 4,
            "tail_score_window_end_capture_index": 5,
            "tail_start_drop_frac": 0.05,
            "tail_start_drop_to_threshold_frac": 0.25,
            "tail_start_shrink_rate_norm_per_ms": 0.12,
            "tail_start_shrink_rate_ratio": 0.10,
            "tail_peak_shrink_rate_norm_per_ms": 1.2,
            "tail_peak_shrink_rate_delay_us": 650.0,
            "tail_start_to_tail_peak_delta_us": 250.0,
            "trusted_visible_volume_nl": 30.0,
            "middle_extrapolated_volume_nl": partial_total_without_tail_nl - 30.0,
            "partial_total_without_tail_nl": partial_total_without_tail_nl,
            "tail_start_uncertainty_p05_us": 400.0,
            "tail_start_uncertainty_p95_us": 500.0,
            "tail_start_uncertainty_candidate_count": 2,
            "tail_start_uncertainty_source": "unified_band",
            "predicted_volume_uncertainty_p05_nl": partial_total_without_tail_nl - 2.0,
            "predicted_volume_uncertainty_p95_nl": partial_total_without_tail_nl + 2.0,
            "predicted_volume_uncertainty_width_nl": 4.0,
            "predicted_volume_uncertainty_relative_width": 4.0 / partial_total_without_tail_nl,
            "predicted_volume_uncertainty_status": "ok",
            "volume_uncertainty_sample_count": 1024,
            "tail_volume_nl": None,
            "middle_extrapolation_status": "ok",
            "final_total_status": "tail_pending",
        },
        "phase_boundaries": {
            "steady_start_delay_from_emergence_us": 100,
            "steady_end_delay_from_emergence_us": 300,
            "flow_fit_start_delay_from_emergence_us": 100,
            "flow_fit_end_delay_from_emergence_us": 300,
            "first_untrusted_capture_index": 4,
            "first_untrusted_delay_from_emergence_us": 400,
            "tail_confirmation_capture_index": 5,
            "tail_confirmation_delay_from_emergence_us": 500,
            "tail_detection_mode": "confirmed_persistent",
            "tail_start_selection_mode": "direct_backtrack",
            "preliminary_tail_start_capture_index": 4,
            "preliminary_tail_start_delay_from_emergence_us": 400,
            "direct_final_tail_start_capture_index": 4,
            "direct_final_tail_start_delay_from_emergence_us": 400,
            "tail_shoulder_end_capture_index": None,
            "tail_shoulder_end_delay_from_emergence_us": None,
            "tail_start_capture_index": 4,
            "tail_start_delay_from_emergence_us": 400,
        },
        "steady_fit": {
            "steady_fit_status": "ok",
            "positions": [0, 1, 2],
            "plateau_positions": [0, 1, 2],
            "flow_fit_positions": [0, 1, 2],
            "steady_capture_indices": [1, 2, 3],
            "plateau_capture_indices": [1, 2, 3],
            "flow_fit_capture_indices": [1, 2, 3],
            "steady_start_capture_index": 1,
            "steady_end_capture_index": 3,
            "plateau_point_count": 3,
            "flow_fit_start_capture_index": 1,
            "flow_fit_end_capture_index": 3,
            "flow_fit_point_count": 3,
            "flow_fit_eligible_point_count": 3,
            "flow_fit_backfill_point_count": 0,
            "flow_fit_outlier_prune_status": "legacy_unspecified",
            "flow_fit_dropped_outlier_capture_index": None,
            "flow_fit_dropped_outlier_delay_from_emergence_us": None,
            "flow_fit_dropped_outlier_local_deviation_nl": None,
            "steady_fit_point_count": 3,
            "steady_rate_nl_per_us": 0.01,
            "steady_rate_ci95_low_nl_per_us": 0.009,
            "steady_rate_ci95_high_nl_per_us": 0.011,
            "steady_rate_ci95_relative_width": 0.2,
            "steady_rate_ci95_contains_central": True,
            "steady_rate_confidence_status": "ok",
            "steady_intercept_nl": 0.0,
            "steady_r2": 1.0,
            "steady_nrmse": 0.0,
            "steady_width_plateau_px": 80.0,
            "steady_width_tolerance_px": 4.0,
        },
        "tail_onset": {
            "tail_width_threshold_px": 73.6,
            "tail_confirmation_capture_index": 5,
            "tail_confirmation_position": 4,
            "direct_final_tail_start_position": 3,
            "tail_start_capture_index": 4,
            "tail_start_position": 3,
            "tail_shoulder_end_capture_index": None,
            "tail_start_refinement_mode": "legacy",
            "tail_start_band_selection_status": None,
            "tail_in_band_candidate_count": 0,
            "tail_start_score": None,
            "tail_score_candidate_count": 2,
            "tail_score_window_start_capture_index": 4,
            "tail_score_window_end_capture_index": 5,
            "tail_start_drop_frac": 0.05,
            "tail_start_drop_to_threshold_frac": 0.25,
            "tail_start_shrink_rate_norm_per_ms": 0.12,
            "tail_start_shrink_rate_ratio": 0.10,
            "tail_peak_shrink_rate_norm_per_ms": 1.2,
            "tail_peak_shrink_rate_delay_us": 650.0,
            "tail_start_to_tail_peak_delta_us": 250.0,
        },
        "middle_extrapolation": {
            "trusted_visible_volume_nl": 30.0,
            "middle_extrapolated_volume_nl": partial_total_without_tail_nl - 30.0,
            "partial_total_without_tail_nl": partial_total_without_tail_nl,
            "tail_start_uncertainty_p05_us": 400.0,
            "tail_start_uncertainty_p95_us": 500.0,
            "tail_start_uncertainty_candidate_count": 2,
            "tail_start_uncertainty_source": "unified_band",
            "predicted_volume_uncertainty_p05_nl": partial_total_without_tail_nl - 2.0,
            "predicted_volume_uncertainty_p95_nl": partial_total_without_tail_nl + 2.0,
            "predicted_volume_uncertainty_width_nl": 4.0,
            "predicted_volume_uncertainty_relative_width": 4.0 / partial_total_without_tail_nl,
            "predicted_volume_uncertainty_status": "ok",
            "volume_uncertainty_sample_count": 1024,
            "tail_volume_nl": None,
            "middle_extrapolation_status": "ok",
            "final_total_status": "tail_pending",
            "first_untrusted_capture_index": 4,
            "tail_start_capture_index": 4,
        },
        "steady_fit_payload": {"run_id": run_id, "steady_fit_status": "ok"},
        "middle_payload": {"run_id": run_id, "middle_extrapolation_status": "ok"},
        "tail_start_candidate_rows": [
            {
                "candidate_window_kind": "direct_backtrack",
                "position": 3,
                "capture_index": 4,
                "delay_from_emergence_us": 400.0,
                "width_px": 76.0,
                "drop_frac": 0.05,
                "drop_to_threshold_frac": 0.25,
                "shrink_rate_norm_per_ms": 0.12,
                "shrink_rate_ratio": 0.10,
                "tail_peak_lead_us": 250.0,
                "within_drop_band": None,
                "within_peak_lead_band": None,
                "within_shrink_rate_band": None,
                "within_unified_band": None,
                "score_drop_term": None,
                "score_peak_lead_term": None,
                "score_shrink_rate_term": None,
                "score_total": None,
                "selection_reason": "legacy_anchor",
                "is_selected": True,
                "is_legacy_anchor": True,
            },
            {
                "candidate_window_kind": "direct_backtrack",
                "position": 4,
                "capture_index": 5,
                "delay_from_emergence_us": 500.0,
                "width_px": 70.0,
                "drop_frac": 0.125,
                "drop_to_threshold_frac": 0.625,
                "shrink_rate_norm_per_ms": 0.40,
                "shrink_rate_ratio": 0.33,
                "tail_peak_lead_us": 150.0,
                "within_drop_band": None,
                "within_peak_lead_band": None,
                "within_shrink_rate_band": None,
                "within_unified_band": None,
                "score_drop_term": None,
                "score_peak_lead_term": None,
                "score_shrink_rate_term": None,
                "score_total": None,
                "selection_reason": None,
                "is_selected": False,
                "is_legacy_anchor": False,
            },
        ],
        "stage4_run": {
            "fov_report": {
                "first_untrusted_capture_index": 4,
                "first_fov_exit_delay_from_emergence_us": 400,
                "trigger_components": [],
            }
        },
    }


def test_export_stage5_review_cache_imports_existing_stage5_outputs(tmp_path, monkeypatch):
    exp_root = tmp_path / "exp"
    exp_root.mkdir(parents=True, exist_ok=True)
    run_row = _inventory_run("run_ok", print_pw="3000", print_pressure="0.75", rep="1", mass_print="0.0900")
    inventory = {
        "experiment_root": str(exp_root.resolve()),
        "selected_runs": [run_row],
        "frames_by_run_id": {"run_ok": [{"capture_index": 1}]},
    }
    source_root = tmp_path / "source"
    cache_root = tmp_path / "cache"
    _write_stage5_source_artifacts(source_root, "run_ok")

    monkeypatch.setattr(mod, "build_stage0_inventory", lambda *args, **kwargs: inventory)
    monkeypatch.setattr(mod, "default_output_root", lambda *args, **kwargs: exp_root / "analysis")

    payload = mod.export_stage5_review_cache(
        exp_root,
        cache_root=cache_root,
        source_output_root=source_root,
    )

    assert payload["stage5_import_count"] == 1
    assert payload["raw_fallback_count"] == 0

    phase_input_csv = cache_root / "runs" / "run_ok" / mod.FIT_CACHE_STAGE_DIRNAME / "phase_input.csv"
    run_context_json = cache_root / "runs" / "run_ok" / mod.FIT_CACHE_STAGE_DIRNAME / "run_context.json"
    with phase_input_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    run_context = json.loads(run_context_json.read_text(encoding="utf-8"))

    assert rows
    assert "phase_label" not in fieldnames
    assert "steady_selected" not in fieldnames
    assert "tail_start_frame" not in fieldnames
    assert run_context["frozen_steady_fit"]["steady_rate_nl_per_us"] == 0.01
    assert run_context["frozen_anchors"]["trusted_visible_volume_nl"] == 30.0
    assert run_context["gravimetric_reference_status"] == "ok"
    assert run_context["source"]["kind"] == "stage5_output_import"


def test_gravimetric_equality_delay_metrics_uses_rate_interval():
    metrics = mod._gravimetric_equality_delay_metrics(
        {
            "gravimetric_total_nl": 90.0,
            "trusted_visible_volume_nl": 30.0,
            "fov_exit_delay_from_emergence_us": 400,
            "steady_rate_nl_per_us": 0.01,
            "steady_rate_ci95_low_nl_per_us": 0.009,
            "steady_rate_ci95_high_nl_per_us": 0.011,
        }
    )

    assert metrics["gravimetric_equality_delay_us"] == pytest.approx(6400.0, rel=1e-6)
    assert metrics["gravimetric_equality_delay_low_us"] == pytest.approx(5854.5454545, rel=1e-6)
    assert metrics["gravimetric_equality_delay_high_us"] == pytest.approx(7066.6666667, rel=1e-6)
    assert metrics["gravimetric_equality_band_width_us"] == pytest.approx(1212.1212121, rel=1e-6)
    assert metrics["gravimetric_equality_confidence_status"] == "ok"


def test_gravimetric_trace_metrics_interpolate_width_and_shrink_rate():
    stage5_run = {
        "phase_feature_rows": [
            _phase_feature_row(
                1,
                delay_from_emergence_us=100,
                total_visible_volume_nl=10.0,
                width_px=100.0,
                trust_label=fov_mod.TRUST_LABEL_TRUSTED,
            ),
            _phase_feature_row(
                2,
                delay_from_emergence_us=200,
                total_visible_volume_nl=20.0,
                width_px=98.0,
                trust_label=fov_mod.TRUST_LABEL_TRUSTED,
            ),
            _phase_feature_row(
                3,
                delay_from_emergence_us=300,
                total_visible_volume_nl=30.0,
                width_px=90.0,
                trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
            ),
            _phase_feature_row(
                4,
                delay_from_emergence_us=400,
                total_visible_volume_nl=40.0,
                width_px=80.0,
                trust_label=fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
            ),
        ],
        "steady_fit": {
            "steady_width_plateau_px": 100.0,
        },
        "tail_onset": {
            "tail_width_threshold_px": 80.0,
        },
    }

    metrics = mod._gravimetric_trace_metrics(
        stage5_run,
        {
            "steady_width_plateau_px": 100.0,
            "gravimetric_equality_delay_us": 250.0,
            "gravimetric_equality_delay_low_us": 200.0,
            "gravimetric_equality_delay_high_us": 350.0,
        },
    )

    assert metrics["gravimetric_eq_width_px"] == pytest.approx(94.0, rel=1e-6)
    assert metrics["gravimetric_eq_drop_frac"] == pytest.approx(0.06, rel=1e-6)
    assert metrics["gravimetric_eq_drop_to_threshold_frac"] == pytest.approx(0.3, rel=1e-6)
    assert metrics["gravimetric_eq_width_low_px"] == pytest.approx(98.0, rel=1e-6)
    assert metrics["gravimetric_eq_width_high_px"] == pytest.approx(85.0, rel=1e-6)
    assert metrics["gravimetric_eq_drop_to_threshold_low_frac"] == pytest.approx(0.1, rel=1e-6)
    assert metrics["gravimetric_eq_drop_to_threshold_high_frac"] == pytest.approx(0.75, rel=1e-6)
    assert metrics["max_shrink_rate_norm_per_ms"] == pytest.approx(1.0, rel=1e-6)
    assert metrics["max_shrink_rate_delay_us"] == pytest.approx(400.0, rel=1e-6)
    assert metrics["gravimetric_eq_shrink_rate_norm_per_ms"] == pytest.approx(0.7, rel=1e-6)
    assert metrics["gravimetric_eq_to_max_shrink_rate_delta_us"] == pytest.approx(-150.0, rel=1e-6)


def test_condition_summary_rows_add_precision_accuracy_and_uncertainty_metrics():
    rows = [
        {
            "print_pressure": 0.75,
            "print_pw_us": 3000,
            "replicate_index": 1,
            "include_in_gravimetric_plots": True,
            "gravimetric_total_nl": 82.0,
            "partial_total_without_tail_nl": 80.0,
            "signed_residual_nl": 2.0,
            "signed_residual_fraction": 2.0 / 82.0,
            "partial_to_gravimetric_ratio": 80.0 / 82.0,
            "partial_exceeds_gravimetric": False,
            "predicted_volume_uncertainty_width_nl": 4.0,
            "predicted_volume_uncertainty_relative_width": 0.05,
        },
        {
            "print_pressure": 0.75,
            "print_pw_us": 3000,
            "replicate_index": 2,
            "include_in_gravimetric_plots": True,
            "gravimetric_total_nl": 98.0,
            "partial_total_without_tail_nl": 100.0,
            "signed_residual_nl": -2.0,
            "signed_residual_fraction": -2.0 / 98.0,
            "partial_to_gravimetric_ratio": 100.0 / 98.0,
            "partial_exceeds_gravimetric": True,
            "predicted_volume_uncertainty_width_nl": 6.0,
            "predicted_volume_uncertainty_relative_width": 0.06,
        },
        {
            "print_pressure": 0.85,
            "print_pw_us": 2500,
            "replicate_index": 1,
            "include_in_gravimetric_plots": True,
            "gravimetric_total_nl": 60.0,
            "partial_total_without_tail_nl": 59.0,
            "signed_residual_nl": 1.0,
            "signed_residual_fraction": 1.0 / 60.0,
            "partial_to_gravimetric_ratio": 59.0 / 60.0,
            "partial_exceeds_gravimetric": False,
            "predicted_volume_uncertainty_width_nl": 3.0,
            "predicted_volume_uncertainty_relative_width": 0.05,
        },
    ]

    condition_rows = mod._condition_summary_rows(rows)
    row_a = next(row for row in condition_rows if row["condition_key"] == "0.75bar__3000us")
    row_b = next(row for row in condition_rows if row["condition_key"] == "0.85bar__2500us")

    assert row_a["predicted_volume_nl_mean"] == pytest.approx(90.0, rel=1e-6)
    assert row_a["predicted_volume_nl_std_sample"] == pytest.approx(14.14213562, rel=1e-6)
    assert row_a["predicted_volume_cv"] == pytest.approx(14.14213562 / 90.0, rel=1e-6)
    assert row_a["gravimetric_total_nl_std_sample"] == pytest.approx(11.3137085, rel=1e-6)
    assert row_a["gravimetric_total_nl_cv"] == pytest.approx(11.3137085 / 90.0, rel=1e-6)
    assert row_a["absolute_residual_nl_mean"] == pytest.approx(2.0, rel=1e-6)
    assert row_a["absolute_residual_fraction_mean"] == pytest.approx(
        ((2.0 / 82.0) + (2.0 / 98.0)) / 2.0,
        rel=1e-6,
    )
    assert row_a["predicted_volume_uncertainty_width_nl_median"] == pytest.approx(5.0, rel=1e-6)
    assert row_a["predicted_volume_uncertainty_relative_width_median"] == pytest.approx(
        0.055,
        rel=1e-6,
    )
    assert row_b["predicted_volume_nl_std_sample"] is None
    assert row_b["predicted_volume_cv"] is None
    assert row_b["gravimetric_total_nl_std_sample"] is None
    assert row_b["gravimetric_total_nl_cv"] is None


def test_export_stage5_review_cache_falls_back_to_raw_stage5_builder(tmp_path, monkeypatch):
    exp_root = tmp_path / "exp"
    exp_root.mkdir(parents=True, exist_ok=True)
    run_row = _inventory_run("run_raw", print_pw="3000", print_pressure="0.75", rep="1", mass_print="0.0900")
    inventory = {
        "experiment_root": str(exp_root.resolve()),
        "selected_runs": [run_row],
        "frames_by_run_id": {"run_raw": [{"capture_index": 1}]},
    }
    cache_root = tmp_path / "cache"

    monkeypatch.setattr(mod, "build_stage0_inventory", lambda *args, **kwargs: inventory)
    monkeypatch.setattr(mod, "default_output_root", lambda *args, **kwargs: exp_root / "analysis")
    monkeypatch.setattr(
        mod.fit_mod,
        "_build_stage5_run",
        lambda run_id, frame_rows, **kwargs: _fake_stage5_run(run_id),
    )

    payload = mod.export_stage5_review_cache(
        exp_root,
        cache_root=cache_root,
        source_output_root=tmp_path / "missing_source",
    )

    run_context_json = cache_root / "runs" / "run_raw" / mod.FIT_CACHE_STAGE_DIRNAME / "run_context.json"
    run_context = json.loads(run_context_json.read_text(encoding="utf-8"))

    assert payload["raw_fallback_count"] == 1
    assert payload["stage5_import_count"] == 0
    assert run_context["source"]["kind"] == "raw_stage5_fallback"
    assert run_context["source"]["stage5_kwargs"]["width_smooth_window"] == 5


def test_export_stage5_cached_review_uses_cache_only_and_excludes_suspect_gravimetric_by_default(
    tmp_path,
    monkeypatch,
):
    cache_root = tmp_path / "cache"
    output_root = tmp_path / "review"
    captured_review_kwargs = []

    suspect_run = _inventory_run(
        "run_suspect",
        print_pw="3000",
        print_pressure="0.65",
        rep="1",
        mass_print="0.0711",
    )
    ok_run = _inventory_run(
        "run_ok",
        print_pw="3000",
        print_pressure="0.75",
        rep="1",
        mass_print="0.0900",
    )

    for run_row in [suspect_run, ok_run]:
        cache_entry = {
            "phase_input_rows": fit_mod._phase_input_rows_from_feature_rows(_fake_stage5_run(run_row["run_id"])["phase_feature_rows"]),
            "run_context": mod._cache_context_payload(
                run_row,
                steady_fit_payload={
                    "run_id": run_row["run_id"],
                    "steady_fit_status": "ok",
                    "steady_capture_indices": [1, 2, 3],
                    "steady_start_capture_index": 1,
                    "steady_end_capture_index": 3,
                    "steady_rate_nl_per_us": 0.01,
                    "steady_intercept_nl": 0.0,
                    "steady_r2": 1.0,
                    "steady_nrmse": 0.0,
                    "steady_width_plateau_px": 80.0,
                    "steady_width_span_px": 0.0,
                    "steady_width_tolerance_px": 4.0,
                },
                trusted_visible_volume_nl=30.0,
                first_untrusted_capture_index=4,
                first_untrusted_delay_from_emergence_us=400,
                fov_report={
                    "first_untrusted_capture_index": 4,
                    "first_fov_exit_delay_from_emergence_us": 400,
                    "trigger_components": [],
                },
                source={"kind": "stage5_output_import", "source_output_root": str(tmp_path / "source")},
            ),
        }
        mod._write_cache_entry(cache_root, run_row["run_id"], cache_entry)

    monkeypatch.setattr(
        mod.fit_mod,
        "_build_stage5_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("raw Stage 5 builder should not run")),
    )
    monkeypatch.setattr(
        mod.fit_mod,
        "_build_stage5_review_run",
        lambda run_id, phase_input_rows, **kwargs: (
            captured_review_kwargs.append(dict(kwargs)),
            _fake_review_run(
                run_id,
                75.0 if run_id == "run_suspect" else 92.0,
            ),
        )[-1],
    )
    monkeypatch.setattr(
        mod.fit_mod,
        "_plot_width_trace",
        lambda path, *args, **kwargs: (Path(path).parent.mkdir(parents=True, exist_ok=True), Path(path).write_bytes(b"plot"))[-1],
    )
    monkeypatch.setattr(
        mod.fit_mod,
        "_plot_vt_fit",
        lambda path, *args, **kwargs: (Path(path).parent.mkdir(parents=True, exist_ok=True), Path(path).write_bytes(b"plot"))[-1],
    )
    monkeypatch.setattr(
        mod,
        "_plot_width_trace_with_gravimetric",
        lambda path, *args, **kwargs: (Path(path).parent.mkdir(parents=True, exist_ok=True), Path(path).write_bytes(b"plot"))[-1],
    )
    monkeypatch.setattr(
        mod,
        "_plot_width_review_contact_sheet",
        lambda path, rows: (Path(path).parent.mkdir(parents=True, exist_ok=True), Path(path).write_bytes(b"sheet"))[-1],
    )
    monkeypatch.setattr(
        mod,
        "_plot_vt_review_contact_sheet",
        lambda path, rows: (Path(path).parent.mkdir(parents=True, exist_ok=True), Path(path).write_bytes(b"sheet"))[-1],
    )

    payload = mod.export_stage5_cached_review(
        cache_root,
        output_root=output_root,
        steady_fit_mode="recompute",
        steady_fit_exclude_last_trusted_frames=3,
        tail_start_mode=fit_mod.TAIL_START_MODE_DESCRIPTOR_SCORE,
    )

    assert payload["selected_run_count"] == 2
    assert payload["usable_gravimetric_row_count"] == 1
    assert captured_review_kwargs
    assert captured_review_kwargs[0]["steady_fit_mode"] == "recompute"
    assert captured_review_kwargs[0]["steady_fit_exclude_last_trusted_frames"] == 3
    assert captured_review_kwargs[0]["flow_fit_backfill_max_frames"] == 3
    assert captured_review_kwargs[0]["flow_fit_backfill_width_delta_px"] == pytest.approx(8.0, rel=1e-6)
    assert captured_review_kwargs[0]["flow_fit_backfill_monotonic_slack_px"] == pytest.approx(0.75, rel=1e-6)
    assert captured_review_kwargs[0]["tail_start_mode"] == fit_mod.TAIL_START_MODE_DESCRIPTOR_SCORE
    assert captured_review_kwargs[0]["tail_unified_band_drop_min"] == pytest.approx(
        fit_mod.TAIL_UNIFIED_BAND_DROP_MIN,
        rel=1e-6,
    )
    assert captured_review_kwargs[0]["tail_direct_target_drop_to_threshold_frac"] == pytest.approx(
        fit_mod.TAIL_DIRECT_TARGET_DROP_TO_THRESHOLD_FRAC,
        rel=1e-6,
    )
    assert captured_review_kwargs[0]["volume_uncertainty_sample_count"] == fit_mod.VOLUME_UNCERTAINTY_SAMPLE_COUNT
    assert captured_review_kwargs[0]["volume_uncertainty_seed"] == fit_mod.VOLUME_UNCERTAINTY_SEED
    assert captured_review_kwargs[0]["tail_uncertainty_score_tolerance"] == pytest.approx(
        fit_mod.TAIL_UNCERTAINTY_SCORE_TOLERANCE,
        rel=1e-6,
    )
    assert (output_root / "experiment_summary.csv").exists()
    assert (output_root / "condition_summary.csv").exists()
    assert (output_root / "condition_confidence_summary.csv").exists()
    assert (output_root / "condition_confidence_summary.json").exists()
    assert (output_root / "predicted_vs_gravimetric_cv_by_condition.png").exists()
    assert (output_root / "predicted_volume_with_uncertainty_by_condition.png").exists()
    assert (output_root / "gravimetric_width_review" / "width_trace_review_index.csv").exists()
    assert (
        output_root / "gravimetric_width_review" / "width_trace_review_contact_sheet.png"
    ).exists()
    assert (output_root / "vt_fit_review" / "vt_fit_review_index.csv").exists()
    assert (output_root / "vt_fit_review" / "vt_fit_review_contact_sheet.png").exists()
    assert (
        output_root / "runs" / "run_suspect" / mod.FIT_REVIEW_STAGE_DIRNAME / "run_summary.json"
    ).exists()
    assert (
        output_root / "runs" / "run_suspect" / mod.FIT_REVIEW_STAGE_DIRNAME / "tail_start_candidates.csv"
    ).exists()

    with (output_root / "experiment_summary.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    suspect_row = next(row for row in rows if row["run_id"] == "run_suspect")
    ok_row = next(row for row in rows if row["run_id"] == "run_ok")
    assert suspect_row["gravimetric_reference_status"] == "suspect_pre_microbalance"
    assert suspect_row["include_in_gravimetric_plots"] == "False"
    assert suspect_row["preliminary_tail_start_capture_index"] == "4"
    assert suspect_row["direct_final_tail_start_capture_index"] == "4"
    assert suspect_row["tail_start_refinement_mode"] == "legacy"
    assert "tail_start_band_selection_status" in suspect_row
    assert suspect_row["tail_score_candidate_count"] == "2"
    assert suspect_row["tail_start_drop_to_threshold_frac"] == "0.25"
    assert suspect_row["tail_start_uncertainty_source"] == "unified_band"
    assert suspect_row["predicted_volume_uncertainty_width_nl"] == "4.0"
    assert suspect_row["predicted_volume_uncertainty_status"] == "ok"
    assert float(suspect_row["gravimetric_equality_delay_us"]) == pytest.approx(4510.0, rel=1e-6)
    assert float(suspect_row["gravimetric_equality_delay_low_us"]) == pytest.approx(
        4136.3636364, rel=1e-6
    )
    assert float(suspect_row["gravimetric_equality_delay_high_us"]) == pytest.approx(
        4966.6666667, rel=1e-6
    )
    assert suspect_row["steady_rate_confidence_status"] == "ok"
    assert ok_row["include_in_gravimetric_plots"] == "True"

    with (output_root / "condition_summary.csv").open("r", encoding="utf-8", newline="") as handle:
        condition_rows = list(csv.DictReader(handle))
    suspect_condition = next(
        row for row in condition_rows if row["condition_key"] == "0.65bar__3000us"
    )
    assert suspect_condition["included_run_count"] == "0"
    assert suspect_condition["excluded_run_count"] == "1"
    assert suspect_condition["signed_residual_nl_mean"] == ""

    with (output_root / "condition_confidence_summary.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        confidence_rows = list(csv.DictReader(handle))
    ok_confidence_row = next(row for row in confidence_rows if row["condition_key"] == "0.75bar__3000us")
    assert ok_confidence_row["predicted_volume_cv"] == ""
    assert ok_confidence_row["predicted_volume_uncertainty_relative_width_median"] == str(
        4.0 / 92.0
    )

    with (
        output_root / "gravimetric_width_review" / "width_trace_review_index.csv"
    ).open("r", encoding="utf-8", newline="") as handle:
        width_rows = list(csv.DictReader(handle))
    assert {row["run_id"] for row in width_rows} == {"run_ok"}
    ok_width_row = width_rows[0]
    assert float(ok_width_row["gravimetric_equality_delay_us"]) == pytest.approx(6400.0, rel=1e-6)
    assert ok_width_row["tail_start_refinement_mode"] == "legacy"
    assert "tail_start_band_selection_status" in ok_width_row
    assert ok_width_row["tail_start_drop_to_threshold_frac"] == "0.25"

    with (output_root / "vt_fit_review" / "vt_fit_review_index.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        vt_rows = list(csv.DictReader(handle))
    assert {row["run_id"] for row in vt_rows} == {"run_ok", "run_suspect"}
    ok_vt_row = next(row for row in vt_rows if row["run_id"] == "run_ok")
    assert ok_vt_row["steady_fit_status"] == "ok"
    assert ok_vt_row["plateau_point_count"] == "3"
    assert ok_vt_row["flow_fit_start_capture_index"] == "1"
    assert ok_vt_row["flow_fit_end_capture_index"] == "3"
    assert ok_vt_row["flow_fit_backfill_point_count"] == "0"
    assert ok_vt_row["flow_fit_outlier_prune_status"] == "legacy_unspecified"
    assert ok_vt_row["steady_rate_ci95_contains_central"] == "True"
    assert float(ok_vt_row["flow_fit_duration_us"]) == pytest.approx(200.0, rel=1e-6)
    assert float(ok_vt_row["plateau_start_after_first_trusted_us"]) == pytest.approx(0.0, rel=1e-6)
    assert float(ok_vt_row["flow_fit_end_to_fov_exit_us"]) == pytest.approx(100.0, rel=1e-6)
    assert float(ok_vt_row["steady_start_after_first_trusted_us"]) == pytest.approx(0.0, rel=1e-6)
    assert float(ok_vt_row["steady_end_to_fov_exit_us"]) == pytest.approx(100.0, rel=1e-6)

    manifest_payload = json.loads((output_root / mod.REVIEW_MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest_payload["flow_fit_backfill_max_frames"] == 3
    assert manifest_payload["flow_fit_backfill_width_delta_px"] == pytest.approx(8.0, rel=1e-6)
    assert manifest_payload["flow_fit_backfill_monotonic_slack_px"] == pytest.approx(0.75, rel=1e-6)
    assert manifest_payload["tail_start_mode"] == fit_mod.TAIL_START_MODE_DESCRIPTOR_SCORE
    assert manifest_payload["tail_unified_band_drop_min"] == pytest.approx(
        fit_mod.TAIL_UNIFIED_BAND_DROP_MIN,
        rel=1e-6,
    )
    assert manifest_payload["tail_direct_target_peak_lead_us"] == pytest.approx(
        fit_mod.TAIL_DIRECT_TARGET_PEAK_LEAD_US,
        rel=1e-6,
    )
    assert manifest_payload["volume_uncertainty_sample_count"] == fit_mod.VOLUME_UNCERTAINTY_SAMPLE_COUNT
    assert manifest_payload["volume_uncertainty_seed"] == fit_mod.VOLUME_UNCERTAINTY_SEED
    assert manifest_payload["tail_uncertainty_score_tolerance"] == pytest.approx(
        fit_mod.TAIL_UNCERTAINTY_SCORE_TOLERANCE,
        rel=1e-6,
    )
