from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.stream_analysis import annotations as annotation_mod
from tools.stream_analysis import fit as fit_mod
from tools.stream_analysis import nozzle as nozzle_mod
from tools.stream_analysis import silhouette as silhouette_mod
from tools.stream_analysis import summary as summary_mod
from tools.stream_analysis import volume as volume_mod
from tools.stream_analysis import cli
from tests.test_stream_analysis_baseline import _make_baseline_experiment
from tests.test_stream_analysis_dataset import _make_experiment
from tests.test_stream_analysis_nozzle import _make_nozzle_experiment
from tests.test_stream_analysis_silhouette import _fake_stage2_run, _make_silhouette_experiment


def test_cli_inventory_main_writes_default_outputs(tmp_path, capsys):
    exp_dir, matched_run, _unmatched_run = _make_experiment(tmp_path)

    rc = cli.main(["inventory", "--experiment-root", str(exp_dir)])

    assert rc == 0
    output_root = Path(exp_dir) / "analysis" / "stream_characterization"
    assert (output_root / "run_inventory.csv").exists()
    assert (output_root / "unmatched_runs.csv").exists()
    assert (
        output_root / "runs" / matched_run.name / "stage_00_inventory" / "frame_index.csv"
    ).exists()

    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_run_count"] == 1
    assert payload["unmatched_run_count"] == 1
    assert payload["output_root"] == str(output_root.resolve())


def test_cli_baseline_main_writes_default_outputs(tmp_path, capsys):
    exp_dir, run_dir = _make_baseline_experiment(tmp_path)

    rc = cli.main(
        [
            "baseline",
            "--experiment-root",
            str(exp_dir),
            "--sample-count",
            "3",
        ]
    )

    assert rc == 0
    output_root = Path(exp_dir) / "analysis" / "stream_characterization"
    stage_dir = output_root / "runs" / run_dir.name / "stage_01_baseline"
    assert (stage_dir / "frame_metrics.csv").exists()
    assert (stage_dir / "baseline_manifest.json").exists()
    assert (stage_dir / "sample_contact_sheet.png").exists()

    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_run_count"] == 1
    assert payload["run_ids"] == [run_dir.name]


def test_cli_annotate_nozzle_help_lists_controls(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["annotate-nozzle", "--help"])

    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert "annotate-nozzle" in help_text
    assert "--zoom-half-width" in help_text
    assert "--show-prediction" in help_text


def test_cli_evaluate_nozzle_main_writes_outputs(tmp_path, capsys):
    exp_dir, _run_dir = _make_nozzle_experiment(tmp_path)
    output_root = tmp_path / "analysis" / "stream_characterization"
    nozzle_mod.export_stage2_nozzle(
        exp_dir,
        output_root=output_root,
        sample_count=4,
        search_width_frac=0.30,
        search_top_frac=0.08,
        search_bottom_frac=0.34,
        shift_threshold_px=3.0,
        confidence_threshold=0.48,
    )
    queue_payload = annotation_mod.build_annotation_queue(exp_dir, output_root=output_root)
    annotations_by_key = {}
    seed = annotation_mod.seed_annotation_for_queue_index(queue_payload["queue"], 0, annotations_by_key)
    annotation_mod.save_nozzle_annotation(
        experiment_root=exp_dir,
        output_root=output_root,
        queue=queue_payload["queue"],
        annotations_by_key=annotations_by_key,
        queue_index=0,
        seed=seed,
        marker_x_px=seed["x_px"] + 1.0,
        marker_y_px=seed["y_px"] + 1.0,
        annotation_mode="attached_black_droplet_center",
        session_id="cli_eval",
        show_prediction=True,
        zoom_half_width=90,
    )

    rc = cli.main(
        [
            "evaluate-nozzle",
            "--experiment-root",
            str(exp_dir),
            "--output-root",
            str(output_root),
            "--limit-worst-frames",
            "1",
        ]
    )

    assert rc == 0
    annotations_root = output_root / "annotations"
    assert (annotations_root / "nozzle_evaluation.csv").exists()
    assert (annotations_root / "nozzle_evaluation.json").exists()

    payload = json.loads(capsys.readouterr().out)
    assert payload["annotation_row_count"] == 1
    assert payload["matched_prediction_count"] == 1


def test_cli_diagnose_nozzle_main_writes_outputs(tmp_path, capsys):
    exp_dir, _run_dir = _make_nozzle_experiment(tmp_path)
    output_root = tmp_path / "analysis" / "stream_characterization"
    nozzle_mod.export_stage2_nozzle(
        exp_dir,
        output_root=output_root,
        sample_count=4,
        search_width_frac=0.30,
        search_top_frac=0.08,
        search_bottom_frac=0.34,
        shift_threshold_px=3.0,
        confidence_threshold=0.48,
    )
    queue_payload = annotation_mod.build_annotation_queue(exp_dir, output_root=output_root)
    annotations_by_key = {}
    seed = annotation_mod.seed_annotation_for_queue_index(queue_payload["queue"], 0, annotations_by_key)
    annotation_mod.save_nozzle_annotation(
        experiment_root=exp_dir,
        output_root=output_root,
        queue=queue_payload["queue"],
        annotations_by_key=annotations_by_key,
        queue_index=0,
        seed=seed,
        marker_x_px=seed["x_px"],
        marker_y_px=seed["y_px"],
        annotation_mode="attached_black_droplet_center",
        session_id="cli_diag",
        show_prediction=True,
        zoom_half_width=90,
    )

    rc = cli.main(
        [
            "diagnose-nozzle",
            "--experiment-root",
            str(exp_dir),
            "--output-root",
            str(output_root),
            "--limit-worst-frames",
            "1",
        ]
    )

    assert rc == 0
    diagnostics_root = output_root / "annotations" / "diagnostics"
    assert (diagnostics_root / "nozzle_candidate_diagnostics.csv").exists()
    assert (diagnostics_root / "nozzle_candidate_summary.json").exists()

    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnostic_row_count"] == 1


def test_cli_nozzle_main_writes_default_outputs(tmp_path, capsys):
    exp_dir, run_dir = _make_nozzle_experiment(tmp_path)

    rc = cli.main(
        [
            "nozzle",
            "--experiment-root",
            str(exp_dir),
            "--sample-count",
            "4",
            "--search-width-frac",
            "0.30",
            "--search-top-frac",
            "0.08",
            "--search-bottom-frac",
            "0.34",
        ]
    )

    assert rc == 0
    output_root = Path(exp_dir) / "analysis" / "stream_characterization"
    stage_dir = output_root / "runs" / run_dir.name / "stage_02_nozzle"
    assert (stage_dir / "nozzle_track.csv").exists()
    assert (stage_dir / "shift_events.json").exists()
    assert (stage_dir / "nozzle_track.png").exists()

    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_run_count"] == 1
    assert payload["run_ids"] == [run_dir.name]


def test_cli_silhouette_main_writes_default_outputs(tmp_path, capsys, monkeypatch):
    exp_dir, run_dir = _make_silhouette_experiment(tmp_path)
    monkeypatch.setattr(silhouette_mod, "_build_stage2_run", _fake_stage2_run)

    rc = cli.main(
        [
            "silhouette",
            "--experiment-root",
            str(exp_dir),
            "--sample-count",
            "3",
            "--nozzle-guard-px",
            "2",
            "--min-component-area-px",
            "50",
        ]
    )

    assert rc == 0
    output_root = Path(exp_dir) / "analysis" / "stream_characterization"
    stage_dir = output_root / "runs" / run_dir.name / "stage_03_silhouette"
    assert (stage_dir / "silhouette_metrics.csv").exists()
    assert (stage_dir / "edge_traces.csv").exists()
    assert (stage_dir / "edge_traces.json").exists()
    assert (stage_dir / "sample_contact_sheet.png").exists()

    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_run_count"] == 1
    assert payload["run_ids"] == [run_dir.name]


def test_cli_volume_main_writes_default_outputs(tmp_path, capsys, monkeypatch):
    exp_dir, run_dir = _make_silhouette_experiment(tmp_path)
    monkeypatch.setattr(volume_mod.silhouette_mod, "_build_stage2_run", _fake_stage2_run)

    rc = cli.main(
        [
            "volume",
            "--experiment-root",
            str(exp_dir),
            "--sample-count",
            "3",
            "--nozzle-guard-px",
            "2",
            "--min-component-area-px",
            "50",
        ]
    )

    assert rc == 0
    output_root = Path(exp_dir) / "analysis" / "stream_characterization"
    stage_dir = output_root / "runs" / run_dir.name / "stage_04_volume"
    assert (stage_dir / "frame_metrics.csv").exists()
    assert (stage_dir / "component_volumes.csv").exists()
    assert (stage_dir / "volume_timeseries.csv").exists()
    assert (stage_dir / "volume_timeseries.json").exists()
    assert (stage_dir / "fov_exit_report.json").exists()
    assert (stage_dir / "Vt.png").exists()
    assert (stage_dir / "sample_contact_sheet.png").exists()

    report = json.loads((stage_dir / "fov_exit_report.json").read_text(encoding="utf-8"))
    assert "fov_near_bottom_px" in report
    assert "trigger_components" in report

    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_run_count"] == 1
    assert payload["run_ids"] == [run_dir.name]


def test_cli_fit_main_writes_default_outputs(tmp_path, capsys, monkeypatch):
    exp_dir, run_dir = _make_silhouette_experiment(tmp_path)
    monkeypatch.setattr(fit_mod.volume_mod.silhouette_mod, "_build_stage2_run", _fake_stage2_run)

    rc = cli.main(
        [
            "fit",
            "--experiment-root",
            str(exp_dir),
            "--sample-count",
            "3",
            "--nozzle-guard-px",
            "2",
            "--min-component-area-px",
            "50",
            "--min-steady-frames",
            "2",
            "--width-smooth-window",
            "3",
            "--tail-persist-frames",
            "1",
        ]
    )

    assert rc == 0
    output_root = Path(exp_dir) / "analysis" / "stream_characterization"
    stage_dir = output_root / "runs" / run_dir.name / "stage_05_fit"
    assert (stage_dir / "phase_features.csv").exists()
    assert (stage_dir / "phase_boundaries.json").exists()
    assert (stage_dir / "steady_fit.json").exists()
    assert (stage_dir / "middle_extrapolation.json").exists()
    assert (stage_dir / "Vt_fit.png").exists()
    assert (stage_dir / "width_trace.png").exists()
    assert (stage_dir / "fit_manifest.json").exists()

    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_run_count"] == 1
    assert payload["run_ids"] == [run_dir.name]


def test_cli_fit_cache_main_dispatches_and_prints_payload(tmp_path, capsys, monkeypatch):
    exp_dir, run_dir, _unmatched_run = _make_experiment(tmp_path)
    captured = {}

    def _fake_export_stage5_review_cache(experiment_root, **kwargs):
        captured["experiment_root"] = experiment_root
        captured["kwargs"] = kwargs
        return {
            "cache_root": str(tmp_path / "cache"),
            "selected_run_count": 1,
            "cached_run_count": 1,
            "runs": [{"run_id": run_dir.name}],
        }

    monkeypatch.setattr(cli, "export_stage5_review_cache", _fake_export_stage5_review_cache)

    rc = cli.main(
        [
            "fit-cache",
            "--experiment-root",
            str(exp_dir),
            "--run-id",
            run_dir.name,
            "--rebuild",
        ]
    )

    assert rc == 0
    assert captured["experiment_root"] == str(exp_dir)
    assert captured["kwargs"]["run_ids"] == [run_dir.name]
    assert captured["kwargs"]["rebuild"] is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["cached_run_count"] == 1


def test_cli_fit_review_main_dispatches_and_prints_payload(tmp_path, capsys, monkeypatch):
    captured = {}

    def _fake_export_stage5_cached_review(cache_root, **kwargs):
        captured["cache_root"] = cache_root
        captured["kwargs"] = kwargs
        return {
            "cache_root": str(cache_root),
            "selected_run_count": 1,
            "analyzed_run_count": 1,
        }

    monkeypatch.setattr(cli, "export_stage5_cached_review", _fake_export_stage5_cached_review)

    rc = cli.main(
        [
            "fit-review",
            "--cache-root",
            str(tmp_path / "cache"),
            "--width-smooth-window",
            "7",
            "--steady-fit-mode",
            "recompute",
            "--steady-fit-exclude-last-trusted-frames",
            "3",
            "--flow-fit-backfill-max-frames",
            "4",
            "--flow-fit-backfill-width-delta-px",
            "6.5",
            "--flow-fit-backfill-monotonic-slack-px",
            "0.5",
            "--tail-start-mode",
            "descriptor-unified",
            "--tail-direct-target-drop-to-threshold-frac",
            "0.18",
            "--tail-direct-target-peak-lead-us",
            "210",
            "--tail-direct-target-shrink-rate-ratio",
            "0.11",
            "--tail-shoulder-target-drop-to-threshold-frac",
            "0.20",
            "--tail-shoulder-target-peak-lead-us",
            "250",
            "--tail-shoulder-target-shrink-rate-ratio",
            "0.10",
            "--tail-score-drop-weight",
            "2.5",
            "--tail-score-peak-lead-weight",
            "1.25",
            "--tail-score-shrink-rate-weight",
            "0.8",
            "--tail-score-drop-scale",
            "0.07",
            "--tail-score-peak-lead-scale-us",
            "55",
            "--tail-score-shrink-rate-scale",
            "0.03",
            "--tail-unified-band-drop-min",
            "0.16",
            "--tail-unified-band-drop-max",
            "0.34",
            "--tail-unified-band-peak-lead-min-us",
            "170",
            "--tail-unified-band-peak-lead-max-us",
            "310",
            "--tail-unified-band-shrink-rate-ratio-min",
            "0.06",
            "--tail-unified-band-shrink-rate-ratio-max",
            "0.17",
            "--tail-unified-target-drop-to-threshold-frac",
            "0.20",
            "--tail-unified-target-peak-lead-us",
            "240",
            "--tail-unified-target-shrink-rate-ratio",
            "0.12",
            "--volume-uncertainty-sample-count",
            "2048",
            "--volume-uncertainty-seed",
            "11",
            "--tail-uncertainty-score-tolerance",
            "1.25",
            "--tail-drop-frac",
            "0.05",
            "--tail-persist-frames",
            "4",
            "--include-suspect-gravimetric",
        ]
    )

    assert rc == 0
    assert captured["cache_root"] == str(tmp_path / "cache")
    assert captured["kwargs"]["width_smooth_window"] == 7
    assert captured["kwargs"]["steady_fit_mode"] == "recompute"
    assert captured["kwargs"]["steady_fit_exclude_last_trusted_frames"] == 3
    assert captured["kwargs"]["flow_fit_backfill_max_frames"] == 4
    assert captured["kwargs"]["flow_fit_backfill_width_delta_px"] == 6.5
    assert captured["kwargs"]["flow_fit_backfill_monotonic_slack_px"] == 0.5
    assert captured["kwargs"]["tail_start_mode"] == "descriptor-unified"
    assert captured["kwargs"]["tail_direct_target_drop_to_threshold_frac"] == 0.18
    assert captured["kwargs"]["tail_direct_target_peak_lead_us"] == 210.0
    assert captured["kwargs"]["tail_direct_target_shrink_rate_ratio"] == 0.11
    assert captured["kwargs"]["tail_shoulder_target_drop_to_threshold_frac"] == 0.20
    assert captured["kwargs"]["tail_shoulder_target_peak_lead_us"] == 250.0
    assert captured["kwargs"]["tail_shoulder_target_shrink_rate_ratio"] == 0.10
    assert captured["kwargs"]["tail_score_drop_weight"] == 2.5
    assert captured["kwargs"]["tail_score_peak_lead_weight"] == 1.25
    assert captured["kwargs"]["tail_score_shrink_rate_weight"] == 0.8
    assert captured["kwargs"]["tail_score_drop_scale"] == 0.07
    assert captured["kwargs"]["tail_score_peak_lead_scale_us"] == 55.0
    assert captured["kwargs"]["tail_score_shrink_rate_scale"] == 0.03
    assert captured["kwargs"]["tail_unified_band_drop_min"] == 0.16
    assert captured["kwargs"]["tail_unified_band_drop_max"] == 0.34
    assert captured["kwargs"]["tail_unified_band_peak_lead_min_us"] == 170.0
    assert captured["kwargs"]["tail_unified_band_peak_lead_max_us"] == 310.0
    assert captured["kwargs"]["tail_unified_band_shrink_rate_ratio_min"] == 0.06
    assert captured["kwargs"]["tail_unified_band_shrink_rate_ratio_max"] == 0.17
    assert captured["kwargs"]["tail_unified_target_drop_to_threshold_frac"] == 0.20
    assert captured["kwargs"]["tail_unified_target_peak_lead_us"] == 240.0
    assert captured["kwargs"]["tail_unified_target_shrink_rate_ratio"] == 0.12
    assert captured["kwargs"]["volume_uncertainty_sample_count"] == 2048
    assert captured["kwargs"]["volume_uncertainty_seed"] == 11
    assert captured["kwargs"]["tail_uncertainty_score_tolerance"] == 1.25
    assert captured["kwargs"]["tail_drop_frac"] == 0.05
    assert captured["kwargs"]["tail_persist_frames"] == 4
    assert captured["kwargs"]["include_suspect_gravimetric"] is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["analyzed_run_count"] == 1


def test_cli_summary_main_writes_default_outputs(tmp_path, capsys, monkeypatch):
    exp_dir, run_dir = _make_silhouette_experiment(tmp_path)

    def _fake_stage5_run(run_id: str, frame_rows: list[dict], **_kwargs):
        return {
            "summary": {
                "steady_fit_status": "ok",
                "steady_start_capture_index": 10,
                "steady_end_capture_index": 20,
                "steady_rate_nl_per_us": 0.02,
                "steady_r2": 0.998,
                "steady_nrmse": 0.01,
                "steady_width_plateau_px": 74.0,
                "tail_confirmation_capture_index": 66,
                "tail_confirmation_delay_from_emergence_us": 3300,
                "tail_detection_mode": "confirmed_persistent",
                "tail_start_selection_mode": "shoulder_adjusted",
                "tail_shoulder_end_capture_index": 68,
                "tail_shoulder_end_delay_from_emergence_us": 3400,
                "tail_start_capture_index": 70,
                "tail_start_delay_from_emergence_us": 3500,
                "tail_onset_status": "ok",
                "trusted_visible_volume_nl": 30.0,
                "middle_extrapolated_volume_nl": 40.0,
                "partial_total_without_tail_nl": 70.0,
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

    monkeypatch.setattr(summary_mod.fit_mod, "_build_stage5_run", _fake_stage5_run)

    rc = cli.main(
        [
            "summary",
            "--experiment-root",
            str(exp_dir),
            "--sample-count",
            "3",
        ]
    )

    assert rc == 0
    output_root = Path(exp_dir) / "analysis" / "stream_characterization"
    assert (output_root / "experiment_summary.csv").exists()
    assert (output_root / "condition_summary.csv").exists()
    assert (output_root / "condition_consistency_summary.csv").exists()
    assert (output_root / "condition_consistency_summary.json").exists()
    assert (output_root / "summary_progress.json").exists()
    assert (output_root / "summary_manifest.json").exists()
    stage_dir = output_root / "runs" / run_dir.name / "stage_06_summary"
    assert (stage_dir / "run_summary.json").exists()

    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_run_count"] == 1
    assert payload["analyzed_run_count"] == 1
