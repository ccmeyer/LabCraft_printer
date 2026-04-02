from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.stream_analysis import annotations as annotation_mod
from tools.stream_analysis import nozzle as nozzle_mod
from tools.stream_analysis import cli
from tests.test_stream_analysis_baseline import _make_baseline_experiment
from tests.test_stream_analysis_dataset import _make_experiment
from tests.test_stream_analysis_nozzle import _make_nozzle_experiment


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
