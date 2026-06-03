from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tools.data_analysis import analyze_plate_reader as cli
from tools.data_analysis import plate_reader_analysis as analysis


def _merged_rows_for_well(
    well: str,
    values: list[float],
    *,
    is_keyed: bool,
    dna_mM: float | None,
    mg_mM: float | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, rfu in enumerate(values):
        rows.append(
            {
                "time": f"00:0{index}:00",
                "time_seconds": float(index * 60),
                "time_minutes": float(index),
                "temperature_c": 37.0,
                "well": well,
                "is_keyed": is_keyed,
                "fluorophore": "488_509",
                "excitation_nm": 488,
                "emission_nm": 509,
                "rfu": rfu,
                "DNA_mM": dna_mM,
                "Mg_mM": mg_mM,
            }
        )
    return rows


def _write_synthetic_merged_csv(path: Path) -> Path:
    rows: list[dict[str, object]] = []
    rows.extend(_merged_rows_for_well("A1", [10, 12, 14, 16], is_keyed=True, dna_mM=np.nan, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("A2", [10, 18, 20, 22], is_keyed=True, dna_mM=0.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("A3", [90, 110], is_keyed=True, dna_mM=1.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("B1", [40, 45, 50, 55], is_keyed=False, dna_mM=np.nan, mg_mM=np.nan))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_outlier_merged_csv(path: Path) -> Path:
    rows: list[dict[str, object]] = []
    rows.extend(_merged_rows_for_well("A1", [100, 100, 100], is_keyed=True, dna_mM=1.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("A2", [101, 101, 101], is_keyed=True, dna_mM=1.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("A3", [102, 102, 102], is_keyed=True, dna_mM=1.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("A4", [130, 130, 130], is_keyed=True, dna_mM=1.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("B1", [10, 10, 10], is_keyed=True, dna_mM=2.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("B2", [1000, 1000, 1000], is_keyed=True, dna_mM=2.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("C1", [500, 500, 500], is_keyed=False, dna_mM=np.nan, mg_mM=np.nan))
    rows.extend(_merged_rows_for_well("D1", [100, 100, 100], is_keyed=True, dna_mM=1.5, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("D2", [101, 101, 101], is_keyed=True, dna_mM=1.5, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("D3", [102, 102, 102], is_keyed=True, dna_mM=1.5, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("D4", [113, 113, 113], is_keyed=True, dna_mM=1.5, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("E1", [100, 100, 100], is_keyed=True, dna_mM=3.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("E2", [100, 100, 100], is_keyed=True, dna_mM=3.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("E3", [100, 100, 100], is_keyed=True, dna_mM=3.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("E4", [110, 110, 110], is_keyed=True, dna_mM=3.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("F1", [200, 200, 200], is_keyed=True, dna_mM=4.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("F2", [200, 200, 200], is_keyed=True, dna_mM=4.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("F3", [200, 200, 200], is_keyed=True, dna_mM=4.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("F4", [240, 240, 240], is_keyed=True, dna_mM=4.0, mg_mM=5.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_endpoint_summary_groups_conditions_and_computes_replicate_stats(tmp_path):
    merged_csv = _write_synthetic_merged_csv(tmp_path / "experiment_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    endpoint = pd.read_csv(result.endpoint_csv)
    summary = pd.read_csv(result.composition_summary_csv)

    assert result.condition_columns == ["DNA_mM", "Mg_mM"]
    assert len(endpoint) == 4
    assert len(summary) == 2

    a1 = endpoint.loc[endpoint["well"] == "A1"].iloc[0]
    a2 = endpoint.loc[endpoint["well"] == "A2"].iloc[0]
    a3 = endpoint.loc[endpoint["well"] == "A3"].iloc[0]
    b1 = endpoint.loc[endpoint["well"] == "B1"].iloc[0]

    assert a1["endpoint_rfu"] == pytest.approx(14.0)
    assert a1["endpoint_timepoint_count"] == 3
    assert a3["endpoint_rfu"] == pytest.approx(100.0)
    assert a3["endpoint_timepoint_count"] == 2

    assert a1["DNA_mM"] == pytest.approx(0.0)
    assert a1["condition_id"] == a2["condition_id"] == "condition_001"
    assert a3["condition_id"] == "condition_002"
    assert b1["condition_id"] == "unkeyed"
    assert pd.isna(b1["condition_endpoint_mean_rfu"])

    expected_mean = 17.0
    expected_sd = np.std([14.0, 20.0], ddof=1)
    expected_cv = 100.0 * expected_sd / expected_mean
    assert a1["condition_endpoint_mean_rfu"] == pytest.approx(expected_mean)
    assert a1["condition_endpoint_sd_rfu"] == pytest.approx(expected_sd)
    assert a1["condition_endpoint_cv_percent"] == pytest.approx(expected_cv)
    assert a1["condition_percent_difference_rfu"] == pytest.approx(100.0 * (14.0 - 17.0) / 17.0)
    assert a2["condition_percent_difference_rfu"] == pytest.approx(100.0 * (20.0 - 17.0) / 17.0)
    assert pd.isna(a3["condition_percent_difference_rfu"])

    condition_001 = summary.loc[summary["condition_id"] == "condition_001"].iloc[0]
    assert condition_001["replicate_count"] == 2
    assert condition_001["endpoint_mean_rfu"] == pytest.approx(expected_mean)
    assert condition_001["endpoint_sd_rfu"] == pytest.approx(expected_sd)
    assert condition_001["endpoint_cv_percent"] == pytest.approx(expected_cv)
    assert set(summary["condition_id"]) == {"condition_001", "condition_002"}
    assert "unkeyed" not in set(summary["condition_id"])


def test_heatmap_matrices_place_wells_by_plate_row_and_column(tmp_path):
    merged_csv = _write_synthetic_merged_csv(tmp_path / "experiment_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    absolute = pd.read_csv(
        result.output_dir / "heatmaps_absolute_rfu" / "488_509_endpoint_rfu.csv",
        index_col=0,
    )
    percent = pd.read_csv(
        result.output_dir
        / "heatmaps_condition_percent_difference"
        / "488_509_condition_percent_difference.csv",
        index_col=0,
    )

    assert absolute.loc["A", "1"] == pytest.approx(14.0)
    assert absolute.loc["A", "2"] == pytest.approx(20.0)
    assert absolute.loc["A", "3"] == pytest.approx(100.0)
    assert absolute.loc["B", "1"] == pytest.approx(50.0)
    assert pd.isna(absolute.loc["P", "24"])

    assert percent.loc["A", "1"] == pytest.approx(100.0 * (14.0 - 17.0) / 17.0)
    assert percent.loc["A", "2"] == pytest.approx(100.0 * (20.0 - 17.0) / 17.0)
    assert pd.isna(percent.loc["A", "3"])
    assert pd.isna(percent.loc["B", "1"])

    assert (result.output_dir / "heatmaps_absolute_rfu" / "488_509_endpoint_rfu.png").stat().st_size > 0
    percent_png = (
        result.output_dir
        / "heatmaps_condition_percent_difference"
        / "488_509_condition_percent_difference.png"
    )
    assert percent_png.stat().st_size > 0


def test_timecourse_summary_and_plots_are_generated_for_keyed_conditions(tmp_path):
    merged_csv = _write_synthetic_merged_csv(tmp_path / "experiment_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    timecourse = pd.read_csv(result.timecourse_summary_csv)

    assert set(timecourse["condition_id"]) == {"condition_001", "condition_002"}
    assert "unkeyed" not in set(timecourse["condition_id"])
    assert len(timecourse) == 6

    selected = timecourse.loc[
        (timecourse["condition_id"] == "condition_001")
        & (timecourse["fluorophore"] == "488_509")
        & (timecourse["time_seconds"] == 120.0)
    ].iloc[0]
    assert selected["mean_rfu"] == pytest.approx(17.0)
    assert selected["sd_rfu"] == pytest.approx(np.std([14.0, 20.0], ddof=1))
    assert selected["replicate_count"] == 2

    one_replicate = timecourse.loc[
        (timecourse["condition_id"] == "condition_002")
        & (timecourse["time_seconds"] == 60.0)
    ].iloc[0]
    assert one_replicate["mean_rfu"] == pytest.approx(110.0)
    assert pd.isna(one_replicate["sd_rfu"])
    assert one_replicate["replicate_count"] == 1

    multi_plot = result.output_dir / "timecourses" / "condition_001_488_509_timecourse.png"
    single_plot = result.output_dir / "timecourses" / "condition_002_488_509_timecourse.png"
    unkeyed_plot = result.output_dir / "timecourses" / "unkeyed_488_509_timecourse.png"
    assert multi_plot.stat().st_size > 0
    assert single_plot.stat().st_size > 0
    assert not unkeyed_plot.exists()
    assert set(result.timecourse_plot_pngs) == {multi_plot, single_plot}


def test_endpoint_outlier_detection_flags_only_evaluated_keyed_replicates(tmp_path):
    merged_csv = _write_outlier_merged_csv(tmp_path / "outlier_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    endpoint = pd.read_csv(result.endpoint_csv)
    outlier_summary = pd.read_csv(result.outlier_summary_csv)

    expected_columns = {
        "condition_endpoint_median_rfu",
        "condition_endpoint_mad_rfu",
        "condition_endpoint_robust_zscore",
        "condition_endpoint_relative_delta_percent",
        "is_endpoint_outlier_candidate",
        "outlier_candidate_reason",
        "is_endpoint_outlier",
        "outlier_reason",
    }
    assert expected_columns.issubset(endpoint.columns)

    a1 = endpoint.loc[endpoint["well"] == "A1"].iloc[0]
    a4 = endpoint.loc[endpoint["well"] == "A4"].iloc[0]
    b2 = endpoint.loc[endpoint["well"] == "B2"].iloc[0]
    c1 = endpoint.loc[endpoint["well"] == "C1"].iloc[0]
    d4 = endpoint.loc[endpoint["well"] == "D4"].iloc[0]
    e4 = endpoint.loc[endpoint["well"] == "E4"].iloc[0]
    f4 = endpoint.loc[endpoint["well"] == "F4"].iloc[0]

    assert a1["condition_endpoint_median_rfu"] == pytest.approx(101.5)
    assert a1["condition_endpoint_mad_rfu"] == pytest.approx(1.0)
    assert a1["condition_endpoint_robust_zscore"] == pytest.approx(0.6745 * (100.0 - 101.5))
    assert a1["condition_endpoint_relative_delta_percent"] == pytest.approx(100.0 * (100.0 - 101.5) / 101.5)
    assert not bool(a1["is_endpoint_outlier_candidate"])
    assert not bool(a1["is_endpoint_outlier"])
    assert bool(a4["is_endpoint_outlier_candidate"])
    assert a4["outlier_candidate_reason"] == "robust_z_abs_ge_3.5"
    assert bool(a4["is_endpoint_outlier"])
    assert a4["outlier_reason"] == "robust_z_abs_ge_3.5"
    assert a4["condition_endpoint_robust_zscore"] == pytest.approx(0.6745 * (130.0 - 101.5))
    assert a4["condition_endpoint_relative_delta_percent"] == pytest.approx(100.0 * (130.0 - 101.5) / 101.5)

    assert bool(d4["is_endpoint_outlier_candidate"])
    assert d4["outlier_candidate_reason"] == "robust_z_abs_ge_3.5"
    assert not bool(d4["is_endpoint_outlier"])
    assert pd.isna(d4["outlier_reason"]) or d4["outlier_reason"] == ""
    assert d4["condition_endpoint_relative_delta_percent"] == pytest.approx(100.0 * (113.0 - 101.5) / 101.5)

    assert bool(e4["is_endpoint_outlier_candidate"])
    assert e4["outlier_candidate_reason"] == "mad_zero_nonmedian"
    assert not bool(e4["is_endpoint_outlier"])
    assert pd.isna(e4["outlier_reason"]) or e4["outlier_reason"] == ""
    assert e4["condition_endpoint_relative_delta_percent"] == pytest.approx(10.0)

    assert bool(f4["is_endpoint_outlier_candidate"])
    assert f4["outlier_candidate_reason"] == "mad_zero_nonmedian"
    assert bool(f4["is_endpoint_outlier"])
    assert f4["outlier_reason"] == "mad_zero_nonmedian"
    assert f4["condition_endpoint_relative_delta_percent"] == pytest.approx(20.0)

    assert pd.isna(b2["condition_endpoint_median_rfu"])
    assert not bool(b2["is_endpoint_outlier_candidate"])
    assert not bool(b2["is_endpoint_outlier"])
    assert pd.isna(c1["condition_endpoint_median_rfu"])
    assert not bool(c1["is_endpoint_outlier_candidate"])
    assert not bool(c1["is_endpoint_outlier"])

    assert result.outlier_count == 2
    assert set(outlier_summary["well"]) == {"A4", "F4"}

    outlier_heatmap = pd.read_csv(
        result.output_dir / "heatmaps_endpoint_outliers" / "488_509_endpoint_outlier_count.csv",
        index_col=0,
    )
    assert outlier_heatmap.loc["A", "1"] == pytest.approx(0.0)
    assert outlier_heatmap.loc["A", "4"] == pytest.approx(1.0)
    assert pd.isna(outlier_heatmap.loc["B", "1"])
    assert pd.isna(outlier_heatmap.loc["C", "1"])
    assert outlier_heatmap.loc["D", "4"] == pytest.approx(0.0)
    assert outlier_heatmap.loc["E", "4"] == pytest.approx(0.0)
    assert outlier_heatmap.loc["F", "4"] == pytest.approx(1.0)

    outlier_png = result.output_dir / "heatmaps_endpoint_outliers" / "488_509_endpoint_outlier_count.png"
    timecourse_png = result.output_dir / "timecourses" / "condition_001_488_509_timecourse.png"
    assert outlier_png.stat().st_size > 0
    assert timecourse_png.stat().st_size > 0


def test_combined_timecourse_summaries_and_plots_exclude_final_outliers_only(tmp_path):
    merged_csv = _write_outlier_merged_csv(tmp_path / "outlier_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    inclusive = pd.read_csv(result.timecourse_summary_csv)
    excluded = pd.read_csv(result.timecourse_excluding_outliers_summary_csv)

    assert result.timecourse_excluding_outliers_summary_csv.exists()
    assert set(inclusive["condition_id"]) == {
        "condition_001",
        "condition_002",
        "condition_003",
        "condition_004",
        "condition_005",
    }
    assert set(excluded["condition_id"]) == set(inclusive["condition_id"])
    assert "unkeyed" not in set(inclusive["condition_id"])
    assert "unkeyed" not in set(excluded["condition_id"])

    a_inclusive = inclusive.loc[
        (inclusive["condition_id"] == "condition_001")
        & (inclusive["fluorophore"] == "488_509")
        & (inclusive["time_seconds"] == 120.0)
    ].iloc[0]
    a_excluded = excluded.loc[
        (excluded["condition_id"] == "condition_001")
        & (excluded["fluorophore"] == "488_509")
        & (excluded["time_seconds"] == 120.0)
    ].iloc[0]
    assert a_inclusive["replicate_count"] == 4
    assert a_inclusive["mean_rfu"] == pytest.approx(np.mean([100.0, 101.0, 102.0, 130.0]))
    assert a_inclusive["sd_rfu"] == pytest.approx(np.std([100.0, 101.0, 102.0, 130.0], ddof=1))
    assert a_excluded["replicate_count"] == 3
    assert a_excluded["mean_rfu"] == pytest.approx(101.0)
    assert a_excluded["sd_rfu"] == pytest.approx(np.std([100.0, 101.0, 102.0], ddof=1))

    d_candidate_only = excluded.loc[
        (excluded["condition_id"] == "condition_002")
        & (excluded["fluorophore"] == "488_509")
        & (excluded["time_seconds"] == 120.0)
    ].iloc[0]
    assert d_candidate_only["replicate_count"] == 4
    assert d_candidate_only["mean_rfu"] == pytest.approx(np.mean([100.0, 101.0, 102.0, 113.0]))
    assert d_candidate_only["sd_rfu"] == pytest.approx(np.std([100.0, 101.0, 102.0, 113.0], ddof=1))

    e_candidate_only = excluded.loc[
        (excluded["condition_id"] == "condition_004")
        & (excluded["fluorophore"] == "488_509")
        & (excluded["time_seconds"] == 120.0)
    ].iloc[0]
    assert e_candidate_only["replicate_count"] == 4
    assert e_candidate_only["mean_rfu"] == pytest.approx(102.5)

    f_excluded = excluded.loc[
        (excluded["condition_id"] == "condition_005")
        & (excluded["fluorophore"] == "488_509")
        & (excluded["time_seconds"] == 120.0)
    ].iloc[0]
    assert f_excluded["replicate_count"] == 3
    assert f_excluded["mean_rfu"] == pytest.approx(200.0)
    assert f_excluded["sd_rfu"] == pytest.approx(0.0)

    including_png = (
        result.output_dir
        / "timecourses_combined"
        / "488_509_all_conditions_including_outliers.png"
    )
    excluding_png = (
        result.output_dir
        / "timecourses_combined"
        / "488_509_all_conditions_excluding_outliers.png"
    )
    assert including_png.stat().st_size > 0
    assert excluding_png.stat().st_size > 0
    assert set(result.combined_timecourse_plot_pngs) == {including_png, excluding_png}


def test_cli_with_merged_csv_creates_expected_outputs(tmp_path, capsys):
    merged_csv = _write_synthetic_merged_csv(tmp_path / "experiment_merged_tidy.csv")
    output_dir = tmp_path / "custom_analysis"

    assert cli.main(["--merged-csv", str(merged_csv), "--output-dir", str(output_dir)]) == 0

    assert (output_dir / "endpoint_by_well.csv").exists()
    assert (output_dir / "composition_summary.csv").exists()
    assert (output_dir / "timecourse_summary.csv").exists()
    assert (output_dir / "timecourse_summary_excluding_outliers.csv").exists()
    assert (output_dir / "outlier_summary.csv").exists()
    assert (output_dir / "heatmaps_absolute_rfu" / "488_509_endpoint_rfu.png").exists()
    assert (output_dir / "heatmaps_endpoint_outliers" / "488_509_endpoint_outlier_count.png").exists()
    assert (output_dir / "timecourses" / "condition_001_488_509_timecourse.png").exists()
    assert (
        output_dir / "timecourses_combined" / "488_509_all_conditions_including_outliers.png"
    ).exists()
    assert (
        output_dir / "timecourses_combined" / "488_509_all_conditions_excluding_outliers.png"
    ).exists()

    captured = capsys.readouterr()
    assert "Endpoint rows: 4" in captured.out
    assert "Composition rows: 2" in captured.out
    assert "Timecourse summary excluding outliers:" in captured.out
    assert "Endpoint outliers: 0" in captured.out
    assert "Timecourse plots: 2" in captured.out
    assert "Combined timecourse plots: 2" in captured.out


def test_cli_with_experiment_directory_uses_single_existing_merged_csv(tmp_path):
    exp_dir = tmp_path / "ExperimentA-20260602_120000"
    _write_synthetic_merged_csv(exp_dir / "ExperimentA_merged_tidy.csv")
    output_dir = tmp_path / "analysis_out"

    assert cli.main([str(exp_dir), "--output-dir", str(output_dir)]) == 0

    endpoint = pd.read_csv(output_dir / "endpoint_by_well.csv")
    assert set(endpoint["well"]) == {"A1", "A2", "A3", "B1"}


def test_cli_with_multiple_existing_merged_csvs_requires_explicit_choice(tmp_path, capsys):
    exp_dir = tmp_path / "ExperimentA-20260602_120000"
    _write_synthetic_merged_csv(exp_dir / "First_merged_tidy.csv")
    _write_synthetic_merged_csv(exp_dir / "Second_merged_tidy.csv")

    assert cli.main([str(exp_dir)]) == 1

    captured = capsys.readouterr()
    assert "Multiple merged tidy CSV files were found" in captured.err
    assert "--merged-csv" in captured.err
