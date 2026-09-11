import csv
import hashlib
import json
from pathlib import Path

import pytest

from tools.stream_analysis.build_tail_validation_manifest import (
    DEFAULT_EXPERIMENTS_ROOT,
    DEFAULT_OUTPUT,
    DENSITY_MEASUREMENTS_CSV,
    MANIFEST_ID,
    SCHEMA_VERSION,
    build_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / DEFAULT_OUTPUT


def _load_manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_stream_tail_validation_manifest_counts_and_subsets():
    manifest = _load_manifest()

    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["manifest_id"] == MANIFEST_ID
    assert manifest["summary"]["total_gravimetric_rows"] == 210
    assert manifest["summary"]["full_replayable_rows"] == 156
    assert manifest["summary"]["excluded_rows"] == 54
    assert len(manifest["runs"]) == 156
    assert len(manifest["excluded_rows"]) == 54

    subset_counts = manifest["summary"]["subset_counts"]
    assert subset_counts["current_120um_issue"] == 7
    assert subset_counts["segmented_window_bank"] == 30
    assert subset_counts["legacy_regression"] == 126
    assert subset_counts["root_window_override_cases"] == 7
    assert subset_counts["selected_lower_window_cases"] == 10
    assert subset_counts["segmented_no_lower_window_cases"] == 13

    exclusion_counts = manifest["summary"]["exclusion_reason_counts"]
    assert exclusion_counts == {
        "missing_run_dir": 53,
        "missing_tail_summaries": 1,
    }

    assert manifest["summary"]["density_solution_counts"] == {
        "BSA_50per": 43,
        "EFTs": 13,
        "EFTu": 6,
        "Pmix": 4,
        "Ribo": 1,
        "SolB": 5,
        "Water": 84,
    }
    assert manifest["summary"]["density_unassigned_rows"] == 0
    assert manifest["summary"]["total_density_solution_counts"] == {
        "BSA_50per": 43,
        "EFTs": 13,
        "EFTu": 6,
        "Pmix": 4,
        "Ribo": 1,
        "SolB": 5,
        "Water": 138,
    }
    assert manifest["summary"]["total_density_unassigned_rows"] == 0


def test_stream_tail_validation_manifest_density_layer_assignments():
    manifest = _load_manifest()

    density_layer = manifest["density_layer"]
    assert density_layer["schema_version"] == "density_assignment_v1"
    assert density_layer["assignment_source"] == "user_confirmed_manifest_review"
    assert density_layer["assignment_basis"] == "experiment_id"
    assert (REPO_ROOT / density_layer["density_source_csv"]).exists()
    assert density_layer["measurements_g_per_ml"]["Water"] == 1.0
    assert density_layer["measurements_g_per_ml"]["BSA_50per"] == 1.095
    assert density_layer["experiment_assignments"]["Stream_online_rep11-20260409_093958"] == "Water"
    assert density_layer["experiment_assignments"]["stream_120um_rep2-20260612_113906"] == "Water"

    assert all(run["density"]["assignment_confidence"] == "confirmed" for run in manifest["runs"])
    assert all(row["density"]["assignment_confidence"] == "confirmed" for row in manifest["excluded_rows"])

    by_run = {run["run_id"]: run for run in manifest["runs"]}
    eft_run = by_run["run_20260424_230828_897abe11"]
    assert eft_run["density"]["solution_id"] == "EFTs"
    assert eft_run["density"]["density_g_per_ml"] == 1.087
    density_corrected_volume_nl = 0.0809 * 1000.0 / 1.087
    assert eft_run["gravimetric"]["gravimetric_volume_nl"] == round(density_corrected_volume_nl, 3)
    assert eft_run["gravimetric"]["gravimetric_volume_nl_water_density"] == 80.9
    assert eft_run["current_analysis"]["volume_error_vs_gravimetric_density_corrected_nl"] == round(
        eft_run["current_analysis"]["predicted_volume_nl"] - density_corrected_volume_nl,
        6,
    )

    water_run = by_run["run_20260612_115255_6b9e930d"]
    assert water_run["density"]["solution_id"] == "Water"
    assert water_run["gravimetric"]["gravimetric_volume_nl"] == water_run["gravimetric"][
        "gravimetric_volume_nl_water_density"
    ]


def test_stream_tail_validation_manifest_declares_contained_relative_paths():
    manifest = _load_manifest()

    for run in manifest["runs"]:
        artifacts = run["artifacts"]
        for key in ("run_dir", "flow_fit_json", "tail_fit_json", "frames_jsonl", "events_jsonl", "captures_dir"):
            path_text = artifacts[key]
            assert not Path(path_text).is_absolute()
            assert ".." not in Path(path_text).parts
            assert (REPO_ROOT / path_text).resolve().is_relative_to(REPO_ROOT)
            assert Path(artifacts["run_dir"]).name == run["run_id"]
            if key != "run_dir":
                assert Path(path_text).parent == Path(artifacts["run_dir"])
        assert artifacts["capture_count"] > 0
        assert artifacts["has_tail_summaries"] is True


def test_stream_tail_validation_manifest_current_120um_rows_are_labeled():
    manifest = _load_manifest()

    rows = [
        run
        for run in manifest["runs"]
        if "current_120um_issue" in run["subsets"]
    ]

    assert len(rows) == 7
    assert {run["condition"]["print_pulse_width_us"] for run in rows} == {2500}
    assert {run["condition"]["print_pressure_psi"] for run in rows} == {0.7004}
    assert {
        run["current_analysis"]["segmented"]["window_selection_reason"]
        for run in rows
    } == {"root_window_override_steep_collapse"}
    assert all(
        run["current_analysis"]["gravimetric_equivalent_tail_start_us"] is not None
        for run in rows
    )


@pytest.fixture
def synthetic_recording(tmp_path):
    density = tmp_path / DENSITY_MEASUREMENTS_CSV
    density.parent.mkdir(parents=True)
    density.write_bytes((REPO_ROOT / DENSITY_MEASUREMENTS_CSV).read_bytes())
    experiment = tmp_path / DEFAULT_EXPERIMENTS_ROOT / "EF-Ts_rep1-20260424_223016"
    run = experiment / "calibration_recordings/OnlineStreamCalibrationProcess/run_synthetic"
    (run / "captures").mkdir(parents=True)
    # The manifest builder inventories captures; it does not decode images.
    (run / "captures/frame.txt").write_text("synthetic capture inventory entry")
    (run / "frames.jsonl").write_text("{}\n")
    (run / "events.jsonl").write_text("{}\n")
    (run / "flow_fit.json").write_text(json.dumps({"fit": {
        "flow_rate_nl_per_us": 0.02, "flow_intercept_nl": 1.0}}))
    (run / "tail_fit.json").write_text(json.dumps({
        "scout_delay_summaries": [{"delay_us": 4000}],
        "backtrack_delay_summaries": [{"delay_us": 3900}],
        "result": {"predicted_volume_nl": 75.0, "predicted_stream_duration_us": 4000.0},
    }))
    with (experiment / "stream_metadata.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Dataset name", "Mass/print", "Print PW", "Print Pressure"])
        writer.writerow(["run_synthetic", "0.0809", "2500", "0.7004"])
        writer.writerow(["run_absent", "0.1", "2500", "0.7004"])
        writer.writerow(["run_without_mass", "NaN", "2500", "0.7004"])
    return tmp_path, run


def test_stream_tail_manifest_generation_uses_owned_inputs(synthetic_recording):
    root, run_dir = synthetic_recording
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    manifest = build_manifest(root)
    assert manifest["summary"]["total_gravimetric_rows"] == 2
    assert manifest["summary"]["full_replayable_rows"] == 1
    assert manifest["summary"]["excluded_rows"] == 1
    assert manifest["summary"]["exclusion_reason_counts"] == {"missing_run_dir": 1}
    assert [r["run_id"] for r in manifest["excluded_rows"]] == ["run_absent"]
    run, = manifest["runs"]
    assert run["run_id"] == "run_synthetic"
    assert run["density"]["solution_id"] == "EFTs"
    assert run["gravimetric"]["gravimetric_volume_nl"] == round(80.9 / 1.087, 3)
    assert run["current_analysis"]["gravimetric_density_corrected_equivalent_tail_start_us"] == round((80.9 / 1.087 - 1.0) / 0.02, 3)
    assert run["artifacts"]["capture_count"] == 1
    for key in ("run_dir", "flow_fit_json", "tail_fit_json", "frames_jsonl", "events_jsonl", "captures_dir"):
        assert (root / run["artifacts"][key]).exists()
        assert (root / run["artifacts"][key]).resolve().is_relative_to(root)
    assert manifest == build_manifest(root)
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("missing,reason", [
    ("flow_fit.json", "missing_flow_fit"), ("tail_fit.json", "missing_tail_fit"),
    ("frames.jsonl", "missing_frames_jsonl"), ("events.jsonl", "missing_events_jsonl"),
    ("captures/frame.txt", "missing_captures"), ("summaries", "missing_tail_summaries"),
])
def test_stream_tail_manifest_excludes_incomplete_inputs(synthetic_recording, missing, reason):
    root, run_dir = synthetic_recording
    if missing == "summaries":
        (run_dir / "tail_fit.json").write_text("{}")
    else:
        (run_dir / missing).unlink()
    manifest = build_manifest(root)
    assert manifest["runs"] == []
    excluded = next(r for r in manifest["excluded_rows"] if r["run_id"] == "run_synthetic")
    assert excluded["exclusion_reasons"] == [reason]
