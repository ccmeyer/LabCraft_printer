import json
from pathlib import Path

from tools.stream_analysis.build_tail_validation_manifest import (
    DEFAULT_OUTPUT,
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


def test_stream_tail_validation_manifest_has_replayable_relative_paths():
    manifest = _load_manifest()

    for run in manifest["runs"]:
        artifacts = run["artifacts"]
        for key in ("run_dir", "flow_fit_json", "tail_fit_json", "frames_jsonl", "events_jsonl", "captures_dir"):
            path_text = artifacts[key]
            assert not Path(path_text).is_absolute()
            assert (REPO_ROOT / path_text).exists(), path_text
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


def test_stream_tail_validation_manifest_matches_regenerated_summary():
    manifest = _load_manifest()
    regenerated = build_manifest(REPO_ROOT)

    assert regenerated["summary"] == manifest["summary"]
    assert [run["run_id"] for run in regenerated["runs"]] == [
        run["run_id"] for run in manifest["runs"]
    ]
    assert [row["run_id"] for row in regenerated["excluded_rows"]] == [
        row["run_id"] for row in manifest["excluded_rows"]
    ]
