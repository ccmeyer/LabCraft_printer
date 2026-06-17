from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tools.data_analysis import analyze_plate_reader as cli
from tools.data_analysis import plate_reader_analysis as analysis

pytestmark = pytest.mark.analysis_pipeline


def _merged_rows_for_well(
    well: str,
    values: list[float],
    *,
    is_keyed: bool,
    dna_mM: float | None,
    mg_mM: float | None,
    fluorophore: str = "488_509",
) -> list[dict[str, object]]:
    excitation_nm, emission_nm = fluorophore.split("_", maxsplit=1)
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
                "fluorophore": fluorophore,
                "excitation_nm": int(excitation_nm),
                "emission_nm": int(emission_nm),
                "rfu": rfu,
                "DNA_mM": dna_mM,
                "Mg_mM": mg_mM,
            }
        )
    return rows


def _effect_rows_for_well(
    well: str,
    values: list[float],
    *,
    is_keyed: bool,
    dna_mM: float | None,
    mg_mM: float | None,
    salt_mM: float | None,
    buffer_x: float | None,
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
                "Salt_mM": salt_mM,
                "Buffer_x": buffer_x,
            }
        )
    return rows


def _categorical_effect_rows_for_well(
    well: str,
    values: list[float],
    *,
    dose_label: str,
    mg_mM: float,
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
                "is_keyed": True,
                "fluorophore": "488_509",
                "excitation_nm": 488,
                "emission_nm": 509,
                "rfu": rfu,
                "Dose_label": dose_label,
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


def _write_endpoint_only_merged_csv(path: Path) -> Path:
    rows: list[dict[str, object]] = []
    rows.extend(_merged_rows_for_well("A1", [10], is_keyed=True, dna_mM=0.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("A2", [12], is_keyed=True, dna_mM=0.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("A3", [50], is_keyed=True, dna_mM=1.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("B1", [40], is_keyed=False, dna_mM=np.nan, mg_mM=np.nan))
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


def _write_triplicate_split_outlier_merged_csv(path: Path) -> Path:
    rows: list[dict[str, object]] = []
    rows.extend(_merged_rows_for_well("A1", [1798, 1798, 1798], is_keyed=True, dna_mM=1.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("A2", [9546, 9546, 9546], is_keyed=True, dna_mM=1.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("A3", [13092, 13092, 13092], is_keyed=True, dna_mM=1.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("B1", [665, 665, 665], is_keyed=True, dna_mM=2.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("B2", [1978, 1978, 1978], is_keyed=True, dna_mM=2.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("B3", [7490, 7490, 7490], is_keyed=True, dna_mM=2.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("C1", [1214, 1214, 1214], is_keyed=True, dna_mM=3.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("C2", [1422, 1422, 1422], is_keyed=True, dna_mM=3.0, mg_mM=5.0))
    rows.extend(_merged_rows_for_well("C3", [2007, 2007, 2007], is_keyed=True, dna_mM=3.0, mg_mM=5.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_large_group_kinetic_outlier_merged_csv(path: Path) -> Path:
    rows: list[dict[str, object]] = []
    traces = {
        "A1": [10, 70, 120, 160, 150, 130, 100, 70, 40, 20],
        "A2": [10, 50, 80, 100, 100, 95, 95, 95, 95, 95],
        "A3": [10, 70, 120, 142, 143, 143, 143, 143, 143, 143],
        "A4": [10, 70, 125, 144, 145, 145, 145, 145, 145, 145],
        "A5": [10, 75, 130, 148, 149, 149, 149, 149, 149, 149],
        "A6": [10, 76, 131, 149, 150, 150, 150, 150, 150, 150],
        "A7": [10, 77, 132, 150, 151, 151, 151, 151, 151, 151],
        "A8": [10, 78, 133, 151, 152, 152, 152, 152, 152, 152],
        "A9": [10, 79, 134, 153, 154, 154, 154, 154, 154, 154],
        "A10": [10, 95, 160, 185, 187, 187, 187, 187, 187, 187],
        "A11": [10, 100, 170, 190, 193, 193, 193, 193, 193, 193],
        "A12": [10, 110, 180, 200, 206, 206, 206, 206, 206, 206],
    }
    for well, values in traces.items():
        rows.extend(_merged_rows_for_well(well, values, is_keyed=True, dna_mM=5.0, mg_mM=5.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_cross_channel_well_outlier_merged_csv(path: Path) -> Path:
    rows: list[dict[str, object]] = []
    for well, values in [
        ("A1", [100, 100, 100]),
        ("A2", [101, 101, 101]),
        ("A3", [102, 102, 102]),
        ("A4", [130, 130, 130]),
    ]:
        rows.extend(_merged_rows_for_well(well, values, is_keyed=True, dna_mM=1.0, mg_mM=5.0, fluorophore="488_509"))
    for well, values in [
        ("A1", [1000, 1000, 1000]),
        ("A2", [1001, 1001, 1001]),
        ("A3", [1002, 1002, 1002]),
        ("A4", [1003, 1003, 1003]),
    ]:
        rows.extend(_merged_rows_for_well(well, values, is_keyed=True, dna_mM=1.0, mg_mM=5.0, fluorophore="561_590"))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_endpoint_effects_merged_csv(path: Path) -> Path:
    rows: list[dict[str, object]] = []
    rows.extend(_effect_rows_for_well("A1", [10, 10, 10], is_keyed=True, dna_mM=0.0, mg_mM=1.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A2", [12, 12, 12], is_keyed=True, dna_mM=0.0, mg_mM=1.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A3", [20, 20, 20], is_keyed=True, dna_mM=0.0, mg_mM=2.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A4", [22, 22, 22], is_keyed=True, dna_mM=0.0, mg_mM=2.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A5", [100, 100, 100], is_keyed=True, dna_mM=1.0, mg_mM=1.0, salt_mM=1.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A6", [101, 101, 101], is_keyed=True, dna_mM=1.0, mg_mM=1.0, salt_mM=1.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A7", [102, 102, 102], is_keyed=True, dna_mM=1.0, mg_mM=1.0, salt_mM=1.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A8", [130, 130, 130], is_keyed=True, dna_mM=1.0, mg_mM=1.0, salt_mM=1.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("B1", [100, 100, 100], is_keyed=True, dna_mM=1.0, mg_mM=2.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("B2", [101, 101, 101], is_keyed=True, dna_mM=1.0, mg_mM=2.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("B3", [102, 102, 102], is_keyed=True, dna_mM=1.0, mg_mM=2.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("B4", [113, 113, 113], is_keyed=True, dna_mM=1.0, mg_mM=2.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("C1", [999, 999, 999], is_keyed=False, dna_mM=np.nan, mg_mM=np.nan, salt_mM=np.nan, buffer_x=np.nan))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_two_reagent_effects_merged_csv(path: Path) -> Path:
    rows: list[dict[str, object]] = []
    rows.extend(_effect_rows_for_well("A1", [10, 10, 10], is_keyed=True, dna_mM=0.0, mg_mM=1.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A2", [11, 11, 11], is_keyed=True, dna_mM=0.0, mg_mM=1.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A3", [20, 20, 20], is_keyed=True, dna_mM=0.0, mg_mM=2.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A4", [21, 21, 21], is_keyed=True, dna_mM=0.0, mg_mM=2.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A5", [30, 30, 30], is_keyed=True, dna_mM=1.0, mg_mM=1.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A6", [31, 31, 31], is_keyed=True, dna_mM=1.0, mg_mM=1.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A7", [40, 40, 40], is_keyed=True, dna_mM=1.0, mg_mM=2.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A8", [41, 41, 41], is_keyed=True, dna_mM=1.0, mg_mM=2.0, salt_mM=0.0, buffer_x=1.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_four_reagent_effects_merged_csv(path: Path) -> Path:
    rows: list[dict[str, object]] = []
    rows.extend(_effect_rows_for_well("A1", [10, 10, 10], is_keyed=True, dna_mM=0.0, mg_mM=1.0, salt_mM=0.0, buffer_x=0.0))
    rows.extend(_effect_rows_for_well("A2", [20, 20, 20], is_keyed=True, dna_mM=1.0, mg_mM=1.0, salt_mM=0.0, buffer_x=1.0))
    rows.extend(_effect_rows_for_well("A3", [30, 30, 30], is_keyed=True, dna_mM=0.0, mg_mM=2.0, salt_mM=1.0, buffer_x=0.0))
    rows.extend(_effect_rows_for_well("A4", [40, 40, 40], is_keyed=True, dna_mM=1.0, mg_mM=2.0, salt_mM=1.0, buffer_x=1.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_uneven_numeric_axis_merged_csv(path: Path) -> Path:
    rows: list[dict[str, object]] = []
    well_index = 1
    for dna_mM, mg_mM, base_rfu in [
        (0.0, 1.0, 10.0),
        (0.1, 1.0, 20.0),
        (1.0, 1.0, 100.0),
        (0.0, 2.0, 15.0),
        (0.1, 2.0, 30.0),
        (1.0, 2.0, 150.0),
    ]:
        for replicate_offset in [0.0, 2.0]:
            rows.extend(
                _effect_rows_for_well(
                    f"A{well_index}",
                    [base_rfu + replicate_offset] * 3,
                    is_keyed=True,
                    dna_mM=dna_mM,
                    mg_mM=mg_mM,
                    salt_mM=0.0,
                    buffer_x=1.0,
                )
            )
            well_index += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_categorical_axis_merged_csv(path: Path) -> Path:
    rows: list[dict[str, object]] = []
    rows.extend(_categorical_effect_rows_for_well("A1", [10, 10, 10], dose_label="low", mg_mM=1.0))
    rows.extend(_categorical_effect_rows_for_well("A2", [12, 12, 12], dose_label="low", mg_mM=2.0))
    rows.extend(_categorical_effect_rows_for_well("A3", [20, 20, 20], dose_label="medium", mg_mM=1.0))
    rows.extend(_categorical_effect_rows_for_well("A4", [22, 22, 22], dose_label="medium", mg_mM=2.0))
    rows.extend(_categorical_effect_rows_for_well("A5", [30, 30, 30], dose_label="high", mg_mM=1.0))
    rows.extend(_categorical_effect_rows_for_well("A6", [32, 32, 32], dose_label="high", mg_mM=2.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_endpoint_summary_groups_conditions_and_computes_replicate_stats(tmp_path):
    merged_csv = _write_synthetic_merged_csv(tmp_path / "experiment_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    endpoint = pd.read_csv(result.endpoint_csv)
    summary = pd.read_csv(result.composition_summary_csv)
    assert result.manifest_json.exists()
    assert result.report_html.exists()

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
        "condition_endpoint_iqr_rfu",
        "condition_endpoint_outer_fence_low_rfu",
        "condition_endpoint_outer_fence_high_rfu",
        "condition_endpoint_robust_zscore",
        "condition_endpoint_relative_delta_percent",
        "timecourse_peak_rfu",
        "timecourse_peak_time_minutes",
        "timecourse_drop_from_peak_percent",
        "timecourse_peak_vs_group_median_percent",
        "is_timecourse_shape_outlier",
        "is_well_outlier",
        "is_linked_well_outlier",
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


def test_outlier_exclusion_removes_all_channels_for_flagged_wells(tmp_path):
    merged_csv = _write_cross_channel_well_outlier_merged_csv(tmp_path / "cross_channel_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    endpoint = pd.read_csv(result.endpoint_csv)
    outlier_summary = pd.read_csv(result.outlier_summary_csv)
    excluded_timecourse = pd.read_csv(result.timecourse_excluding_outliers_summary_csv)

    direct = endpoint.loc[(endpoint["well"] == "A4") & (endpoint["fluorophore"] == "488_509")].iloc[0]
    linked = endpoint.loc[(endpoint["well"] == "A4") & (endpoint["fluorophore"] == "561_590")].iloc[0]
    clean = endpoint.loc[(endpoint["well"] == "A3") & (endpoint["fluorophore"] == "561_590")].iloc[0]

    assert bool(direct["is_endpoint_outlier"])
    assert bool(direct["is_well_outlier"])
    assert not bool(direct["is_linked_well_outlier"])
    assert not bool(linked["is_endpoint_outlier"])
    assert bool(linked["is_well_outlier"])
    assert bool(linked["is_linked_well_outlier"])
    assert not bool(clean["is_endpoint_outlier"])
    assert not bool(clean["is_well_outlier"])
    assert not bool(clean["is_linked_well_outlier"])

    assert result.outlier_count == 1
    assert set(outlier_summary["well"]) == {"A4"}
    assert set(outlier_summary["fluorophore"]) == {"488_509"}

    excluded_488 = excluded_timecourse.loc[
        (excluded_timecourse["fluorophore"] == "488_509")
        & (excluded_timecourse["time_seconds"] == 120.0)
    ].iloc[0]
    excluded_561 = excluded_timecourse.loc[
        (excluded_timecourse["fluorophore"] == "561_590")
        & (excluded_timecourse["time_seconds"] == 120.0)
    ].iloc[0]
    assert excluded_488["replicate_count"] == 3
    assert excluded_488["mean_rfu"] == pytest.approx(np.mean([100.0, 101.0, 102.0]))
    assert excluded_561["replicate_count"] == 3
    assert excluded_561["mean_rfu"] == pytest.approx(np.mean([1000.0, 1001.0, 1002.0]))

    outlier_heatmap_488 = pd.read_csv(
        result.output_dir / "heatmaps_endpoint_outliers" / "488_509_endpoint_outlier_count.csv",
        index_col=0,
    )
    outlier_heatmap_561 = pd.read_csv(
        result.output_dir / "heatmaps_endpoint_outliers" / "561_590_endpoint_outlier_count.csv",
        index_col=0,
    )
    assert outlier_heatmap_488.loc["A", "4"] == pytest.approx(1.0)
    assert outlier_heatmap_561.loc["A", "4"] == pytest.approx(0.0)


def test_triplicate_split_outlier_detection_adds_low_and_high_signal_fallbacks(tmp_path):
    merged_csv = _write_triplicate_split_outlier_merged_csv(tmp_path / "triplicate_split_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    endpoint = pd.read_csv(result.endpoint_csv)
    outlier_summary = pd.read_csv(result.outlier_summary_csv)
    excluded_timecourse = pd.read_csv(result.timecourse_excluding_outliers_summary_csv)

    low_split = endpoint.loc[endpoint["well"] == "A1"].iloc[0]
    low_split_neighbor = endpoint.loc[endpoint["well"] == "A2"].iloc[0]
    high_split = endpoint.loc[endpoint["well"] == "B3"].iloc[0]
    high_split_neighbor = endpoint.loc[endpoint["well"] == "B2"].iloc[0]
    moderate_high = endpoint.loc[endpoint["well"] == "C3"].iloc[0]

    assert bool(low_split["is_endpoint_outlier_candidate"])
    assert bool(low_split["is_endpoint_outlier"])
    assert low_split["outlier_candidate_reason"] == "triplicate_low_signal_split"
    assert low_split["outlier_reason"] == "triplicate_low_signal_split"
    assert not bool(low_split_neighbor["is_endpoint_outlier"])

    assert bool(high_split["is_endpoint_outlier_candidate"])
    assert bool(high_split["is_endpoint_outlier"])
    assert high_split["outlier_candidate_reason"] == "triplicate_high_signal_split"
    assert high_split["outlier_reason"] == "triplicate_high_signal_split"
    assert not bool(high_split_neighbor["is_endpoint_outlier"])

    assert not bool(moderate_high["is_endpoint_outlier_candidate"])
    assert not bool(moderate_high["is_endpoint_outlier"])
    assert result.outlier_count == 2
    assert set(outlier_summary["well"]) == {"A1", "B3"}
    assert set(outlier_summary["outlier_reason"]) == {
        "triplicate_low_signal_split",
        "triplicate_high_signal_split",
    }

    outlier_heatmap = pd.read_csv(
        result.output_dir / "heatmaps_endpoint_outliers" / "488_509_endpoint_outlier_count.csv",
        index_col=0,
    )
    assert outlier_heatmap.loc["A", "1"] == pytest.approx(1.0)
    assert outlier_heatmap.loc["A", "2"] == pytest.approx(0.0)
    assert outlier_heatmap.loc["B", "3"] == pytest.approx(1.0)
    assert outlier_heatmap.loc["C", "3"] == pytest.approx(0.0)

    low_split_excluded = excluded_timecourse.loc[
        (excluded_timecourse["condition_id"] == "condition_001")
        & (excluded_timecourse["time_seconds"] == 120.0)
    ].iloc[0]
    high_split_excluded = excluded_timecourse.loc[
        (excluded_timecourse["condition_id"] == "condition_002")
        & (excluded_timecourse["time_seconds"] == 120.0)
    ].iloc[0]
    moderate_excluded = excluded_timecourse.loc[
        (excluded_timecourse["condition_id"] == "condition_003")
        & (excluded_timecourse["time_seconds"] == 120.0)
    ].iloc[0]
    assert low_split_excluded["replicate_count"] == 2
    assert low_split_excluded["mean_rfu"] == pytest.approx(np.mean([9546.0, 13092.0]))
    assert high_split_excluded["replicate_count"] == 2
    assert high_split_excluded["mean_rfu"] == pytest.approx(np.mean([665.0, 1978.0]))
    assert moderate_excluded["replicate_count"] == 3
    assert moderate_excluded["mean_rfu"] == pytest.approx(np.mean([1214.0, 1422.0, 2007.0]))


def test_large_replicate_kinetic_outlier_detection_flags_late_collapse_only(tmp_path):
    merged_csv = _write_large_group_kinetic_outlier_merged_csv(tmp_path / "large_group_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    endpoint = pd.read_csv(result.endpoint_csv)
    outlier_summary = pd.read_csv(result.outlier_summary_csv)
    excluded_timecourse = pd.read_csv(result.timecourse_excluding_outliers_summary_csv)

    expected_columns = {
        "condition_endpoint_iqr_rfu",
        "condition_endpoint_outer_fence_low_rfu",
        "condition_endpoint_outer_fence_high_rfu",
        "timecourse_peak_rfu",
        "timecourse_peak_time_minutes",
        "timecourse_drop_from_peak_percent",
        "timecourse_peak_vs_group_median_percent",
        "is_timecourse_shape_outlier",
        "is_well_outlier",
        "is_linked_well_outlier",
    }
    assert expected_columns.issubset(endpoint.columns)

    collapse = endpoint.loc[endpoint["well"] == "A1"].iloc[0]
    low_plateau = endpoint.loc[endpoint["well"] == "A2"].iloc[0]
    high_candidate = endpoint.loc[endpoint["well"] == "A12"].iloc[0]

    assert bool(collapse["is_endpoint_outlier_candidate"])
    assert bool(collapse["is_endpoint_outlier"])
    assert bool(collapse["is_timecourse_shape_outlier"])
    assert collapse["outlier_candidate_reason"] == "timecourse_late_signal_collapse"
    assert collapse["outlier_reason"] == "timecourse_late_signal_collapse"
    assert collapse["timecourse_peak_rfu"] == pytest.approx(160.0)
    assert collapse["timecourse_drop_from_peak_percent"] >= 60.0
    assert collapse["timecourse_peak_vs_group_median_percent"] >= 40.0

    assert bool(low_plateau["is_endpoint_outlier_candidate"])
    assert not bool(low_plateau["is_endpoint_outlier"])
    assert not bool(low_plateau["is_timecourse_shape_outlier"])
    assert low_plateau["outlier_candidate_reason"] == "robust_z_abs_ge_3.5"
    assert pd.isna(low_plateau["outlier_reason"]) or low_plateau["outlier_reason"] == ""

    assert bool(high_candidate["is_endpoint_outlier_candidate"])
    assert not bool(high_candidate["is_endpoint_outlier"])
    assert not bool(high_candidate["is_timecourse_shape_outlier"])
    assert high_candidate["condition_endpoint_robust_zscore"] >= 3.5
    assert high_candidate["condition_endpoint_relative_delta_percent"] < 60.0
    assert high_candidate["endpoint_rfu"] < high_candidate["condition_endpoint_outer_fence_high_rfu"]

    assert result.outlier_count == 1
    assert set(outlier_summary["well"]) == {"A1"}
    assert set(outlier_summary["outlier_reason"]) == {"timecourse_late_signal_collapse"}

    final_timepoint = excluded_timecourse.loc[
        (excluded_timecourse["condition_id"] == "condition_001")
        & (excluded_timecourse["time_seconds"] == 540.0)
    ].iloc[0]
    assert final_timepoint["replicate_count"] == 11

    outlier_heatmap = pd.read_csv(
        result.output_dir / "heatmaps_endpoint_outliers" / "488_509_endpoint_outlier_count.csv",
        index_col=0,
    )
    assert outlier_heatmap.loc["A", "1"] == pytest.approx(1.0)
    assert outlier_heatmap.loc["A", "2"] == pytest.approx(0.0)
    assert outlier_heatmap.loc["A", "12"] == pytest.approx(0.0)


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


def test_endpoint_main_effects_and_pairwise_interactions(tmp_path):
    merged_csv = _write_endpoint_effects_merged_csv(tmp_path / "effects_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    assert len(result.main_effect_pngs) == 6
    assert len(result.main_effect_csvs) == 6
    assert len(result.pairwise_interaction_pngs) == 6
    assert len(result.pairwise_interaction_csvs) == 12

    including_dna = pd.read_csv(
        result.output_dir
        / "endpoint_effects"
        / "main_effects"
        / "including_outliers"
        / "488_509_DNA_mM_main_effect.csv"
    )
    excluding_dna = pd.read_csv(
        result.output_dir
        / "endpoint_effects"
        / "main_effects"
        / "excluding_outliers"
        / "488_509_DNA_mM_main_effect.csv"
    )
    dna0 = including_dna.loc[including_dna["reagent_value"] == 0.0].iloc[0]
    dna1_including = including_dna.loc[including_dna["reagent_value"] == 1.0].iloc[0]
    dna1_excluding = excluding_dna.loc[excluding_dna["reagent_value"] == 1.0].iloc[0]

    assert dna0["endpoint_mean_rfu"] == pytest.approx(np.mean([10.0, 12.0, 20.0, 22.0]))
    assert dna0["endpoint_sd_rfu"] == pytest.approx(np.std([10.0, 12.0, 20.0, 22.0], ddof=1))
    assert dna0["endpoint_n"] == 4
    assert dna0["composition_count"] == 2
    assert dna1_including["endpoint_mean_rfu"] == pytest.approx(
        np.mean([100.0, 101.0, 102.0, 130.0, 100.0, 101.0, 102.0, 113.0])
    )
    assert dna1_including["endpoint_n"] == 8
    assert dna1_including["composition_count"] == 2
    assert dna1_excluding["endpoint_mean_rfu"] == pytest.approx(
        np.mean([100.0, 101.0, 102.0, 100.0, 101.0, 102.0, 113.0])
    )
    assert dna1_excluding["endpoint_n"] == 7
    assert dna1_excluding["composition_count"] == 2

    buffer_main_effect = (
        result.output_dir
        / "endpoint_effects"
        / "main_effects"
        / "including_outliers"
        / "488_509_Buffer_x_main_effect.csv"
    )
    assert not buffer_main_effect.exists()

    main_effect_png = (
        result.output_dir
        / "endpoint_effects"
        / "main_effects"
        / "excluding_outliers"
        / "488_509_DNA_mM_main_effect.png"
    )
    assert main_effect_png.stat().st_size > 0

    mean_matrix = pd.read_csv(
        result.output_dir
        / "endpoint_effects"
        / "pairwise_interactions"
        / "excluding_outliers"
        / "488_509_DNA_mM_x_Mg_mM_mean_endpoint_rfu.csv",
        index_col=0,
    )
    count_matrix = pd.read_csv(
        result.output_dir
        / "endpoint_effects"
        / "pairwise_interactions"
        / "excluding_outliers"
        / "488_509_DNA_mM_x_Mg_mM_endpoint_n.csv",
        index_col=0,
    )
    mean_matrix.index = mean_matrix.index.astype(str)
    count_matrix.index = count_matrix.index.astype(str)
    assert mean_matrix.loc["1", "0"] == pytest.approx(11.0)
    assert mean_matrix.loc["2", "0"] == pytest.approx(21.0)
    assert mean_matrix.loc["1", "1"] == pytest.approx(101.0)
    assert mean_matrix.loc["2", "1"] == pytest.approx(np.mean([100.0, 101.0, 102.0, 113.0]))
    assert count_matrix.loc["1", "1"] == pytest.approx(3.0)
    assert count_matrix.loc["2", "1"] == pytest.approx(4.0)

    missing_matrix = pd.read_csv(
        result.output_dir
        / "endpoint_effects"
        / "pairwise_interactions"
        / "including_outliers"
        / "488_509_DNA_mM_x_Salt_mM_mean_endpoint_rfu.csv",
        index_col=0,
    )
    missing_matrix.index = missing_matrix.index.astype(str)
    assert pd.isna(missing_matrix.loc["1", "0"])
    assert missing_matrix.loc["1", "1"] == pytest.approx(np.mean([100.0, 101.0, 102.0, 130.0]))

    pairwise_png = (
        result.output_dir
        / "endpoint_effects"
        / "pairwise_interactions"
        / "excluding_outliers"
        / "488_509_DNA_mM_x_Mg_mM_mean_endpoint_rfu.png"
    )
    assert pairwise_png.stat().st_size > 0


def test_endpoint_effect_plots_use_numeric_x_positions_for_numeric_reagents(tmp_path, monkeypatch):
    merged_csv = _write_uneven_numeric_axis_merged_csv(tmp_path / "numeric_axis_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    main_csv = (
        result.output_dir
        / "endpoint_effects"
        / "main_effects"
        / "including_outliers"
        / "488_509_DNA_mM_main_effect.csv"
    )
    main_summary = pd.read_csv(main_csv)
    assert set(main_summary["reagent_axis_type"]) == {"numeric"}
    assert list(main_summary["reagent_value"]) == pytest.approx([0.0, 0.1, 1.0])
    assert list(main_summary["reagent_plot_value"]) == pytest.approx([0.0, 0.1, 1.0])

    dose_csv = (
        result.output_dir
        / "endpoint_effects"
        / "faceted_dose_response"
        / "including_outliers"
        / "488_509_x_DNA_mM_hue_Mg_mM_endpoint_dose_response.csv"
    )
    dose_data = pd.read_csv(dose_csv)
    assert set(dose_data["x_axis_type"]) == {"numeric"}
    assert sorted(dose_data["x_plot_value"].dropna().unique()) == pytest.approx([0.0, 0.1, 1.0])

    numeric_string_axis = analysis.build_condition_axis(["10", "2", "0.1"])
    assert numeric_string_axis.axis_type == "numeric"
    assert numeric_string_axis.values == ["0.1", "2", "10"]
    assert numeric_string_axis.plot_values == pytest.approx([0.1, 2.0, 10.0])

    endpoint = pd.read_csv(result.endpoint_csv)
    plot_summary = analysis.build_main_effect_summary(endpoint, fluorophore="488_509", reagent="DNA_mM")
    plot_points = analysis.build_main_effect_composition_points(endpoint, fluorophore="488_509", reagent="DNA_mM")
    original_close = analysis.plt.close
    monkeypatch.setattr(analysis.plt, "close", lambda fig=None: None)
    analysis.write_main_effect_plot(
        plot_summary,
        plot_points,
        tmp_path / "numeric_main_effect.png",
        fluorophore="488_509",
        reagent="DNA_mM",
        variant_label="including outliers",
    )
    main_fig = analysis.plt.gcf()
    main_line = next(line for line in main_fig.axes[0].get_lines() if line.get_marker() == "o")
    assert list(main_line.get_xdata()) == pytest.approx([0.0, 0.1, 1.0])
    original_close(main_fig)

    dose_summary = analysis.build_faceted_dose_response_summary(
        endpoint,
        fluorophore="488_509",
        x_reagent="DNA_mM",
        hue_reagent="Mg_mM",
        col_reagent=None,
    )
    dose_plot_data = analysis.build_faceted_dose_response_csv_data(
        endpoint,
        dose_summary,
        fluorophore="488_509",
        x_reagent="DNA_mM",
        hue_reagent="Mg_mM",
        col_reagent=None,
    )
    analysis.write_faceted_dose_response_plot(
        dose_summary,
        dose_plot_data,
        tmp_path / "numeric_dose_response.png",
        fluorophore="488_509",
        x_reagent="DNA_mM",
        hue_reagent="Mg_mM",
        col_reagent=None,
        variant_label="including outliers",
    )
    dose_fig = analysis.plt.gcf()
    dose_lines = [
        line
        for line in dose_fig.axes[0].get_lines()
        if line.get_marker() == "o"
    ]
    assert len(dose_lines) == 2
    for line in dose_lines:
        assert list(line.get_xdata()) == pytest.approx([0.0, 0.1, 1.0])
    original_close(dose_fig)


def test_endpoint_effect_plots_keep_categorical_x_positions_for_text_reagents(tmp_path, monkeypatch):
    merged_csv = _write_categorical_axis_merged_csv(tmp_path / "categorical_axis_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    main_csv = (
        result.output_dir
        / "endpoint_effects"
        / "main_effects"
        / "including_outliers"
        / "488_509_Dose_label_main_effect.csv"
    )
    main_summary = pd.read_csv(main_csv)
    assert set(main_summary["reagent_axis_type"]) == {"categorical"}
    assert list(main_summary["reagent_plot_value"]) == pytest.approx([0.0, 1.0, 2.0])

    dose_csv = (
        result.output_dir
        / "endpoint_effects"
        / "faceted_dose_response"
        / "including_outliers"
        / "488_509_x_Dose_label_hue_Mg_mM_endpoint_dose_response.csv"
    )
    dose_data = pd.read_csv(dose_csv)
    assert set(dose_data["x_axis_type"]) == {"categorical"}
    assert sorted(dose_data["x_plot_value"].dropna().unique()) == pytest.approx([0.0, 1.0, 2.0])

    endpoint = pd.read_csv(result.endpoint_csv)
    plot_summary = analysis.build_main_effect_summary(endpoint, fluorophore="488_509", reagent="Dose_label")
    plot_points = analysis.build_main_effect_composition_points(endpoint, fluorophore="488_509", reagent="Dose_label")
    original_close = analysis.plt.close
    monkeypatch.setattr(analysis.plt, "close", lambda fig=None: None)
    analysis.write_main_effect_plot(
        plot_summary,
        plot_points,
        tmp_path / "categorical_main_effect.png",
        fluorophore="488_509",
        reagent="Dose_label",
        variant_label="including outliers",
    )
    fig = analysis.plt.gcf()
    main_line = next(line for line in fig.axes[0].get_lines() if line.get_marker() == "o")
    assert list(main_line.get_xdata()) == pytest.approx([0.0, 1.0, 2.0])
    original_close(fig)


def test_endpoint_variability_outputs_compare_signal_and_replicate_spread(tmp_path):
    merged_csv = _write_endpoint_effects_merged_csv(tmp_path / "effects_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    assert len(result.endpoint_variability_csvs) == 2
    assert len(result.endpoint_variability_pngs) == 4

    including_csv = (
        result.output_dir
        / "endpoint_variability"
        / "including_outliers"
        / "488_509_endpoint_variability.csv"
    )
    excluding_csv = (
        result.output_dir
        / "endpoint_variability"
        / "excluding_outliers"
        / "488_509_endpoint_variability.csv"
    )
    including = pd.read_csv(including_csv)
    excluding = pd.read_csv(excluding_csv)

    assert "unkeyed" not in set(including["condition_id"])
    assert "unkeyed" not in set(excluding["condition_id"])

    final_outlier_condition = {
        "DNA_mM": 1.0,
        "Mg_mM": 1.0,
        "Salt_mM": 1.0,
        "Buffer_x": 1.0,
    }
    candidate_only_condition = {
        "DNA_mM": 1.0,
        "Mg_mM": 2.0,
        "Salt_mM": 0.0,
        "Buffer_x": 1.0,
    }

    final_including = including.loc[
        (including[list(final_outlier_condition)] == pd.Series(final_outlier_condition)).all(axis=1)
    ].iloc[0]
    final_excluding = excluding.loc[
        (excluding[list(final_outlier_condition)] == pd.Series(final_outlier_condition)).all(axis=1)
    ].iloc[0]
    candidate_excluding = excluding.loc[
        (excluding[list(candidate_only_condition)] == pd.Series(candidate_only_condition)).all(axis=1)
    ].iloc[0]

    all_final_values = [100.0, 101.0, 102.0, 130.0]
    non_outlier_final_values = [100.0, 101.0, 102.0]
    candidate_values = [100.0, 101.0, 102.0, 113.0]
    expected_including_sd = np.std(all_final_values, ddof=1)
    expected_excluding_sd = np.std(non_outlier_final_values, ddof=1)

    assert final_including["replicate_count"] == 4
    assert final_including["endpoint_mean_rfu"] == pytest.approx(np.mean(all_final_values))
    assert final_including["endpoint_sd_rfu"] == pytest.approx(expected_including_sd)
    assert final_including["endpoint_cv_percent"] == pytest.approx(
        100.0 * expected_including_sd / np.mean(all_final_values)
    )
    assert final_including["endpoint_min_rfu"] == pytest.approx(100.0)
    assert final_including["endpoint_max_rfu"] == pytest.approx(130.0)

    assert final_excluding["replicate_count"] == 3
    assert final_excluding["endpoint_mean_rfu"] == pytest.approx(np.mean(non_outlier_final_values))
    assert final_excluding["endpoint_sd_rfu"] == pytest.approx(expected_excluding_sd)
    assert final_excluding["endpoint_cv_percent"] == pytest.approx(
        100.0 * expected_excluding_sd / np.mean(non_outlier_final_values)
    )

    assert candidate_excluding["replicate_count"] == 4
    assert candidate_excluding["endpoint_mean_rfu"] == pytest.approx(np.mean(candidate_values))

    for png in [
        result.output_dir
        / "endpoint_variability"
        / "including_outliers"
        / "488_509_cv_vs_mean_endpoint_rfu.png",
        result.output_dir
        / "endpoint_variability"
        / "including_outliers"
        / "488_509_sd_vs_mean_endpoint_rfu.png",
        result.output_dir
        / "endpoint_variability"
        / "excluding_outliers"
        / "488_509_cv_vs_mean_endpoint_rfu.png",
        result.output_dir
        / "endpoint_variability"
        / "excluding_outliers"
        / "488_509_sd_vs_mean_endpoint_rfu.png",
    ]:
        assert png.stat().st_size > 0


def test_pairwise_interaction_heatmap_puts_lowest_y_value_at_bottom(tmp_path, monkeypatch):
    matrix = pd.DataFrame(
        [[1.0, 2.0], [3.0, 4.0]],
        index=["1", "2"],
        columns=["0", "1"],
    )
    original_close = analysis.plt.close
    monkeypatch.setattr(analysis.plt, "close", lambda fig=None: None)

    analysis.write_pairwise_interaction_heatmap_plot(
        matrix,
        tmp_path / "pairwise.png",
        fluorophore="488_509",
        reagent_a="DNA_mM",
        reagent_b="Mg_mM",
        variant_label="including outliers",
    )

    fig = analysis.plt.gcf()
    ax = fig.axes[0]
    assert not ax.yaxis_inverted()
    assert (tmp_path / "pairwise.png").stat().st_size > 0
    original_close(fig)


def test_faceted_endpoint_dose_response_plots_three_reagent_assignments(tmp_path):
    merged_csv = _write_endpoint_effects_merged_csv(tmp_path / "effects_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    assert len(result.faceted_dose_response_pngs) == 12
    assert len(result.faceted_dose_response_csvs) == 12

    including_csv = (
        result.output_dir
        / "endpoint_effects"
        / "faceted_dose_response"
        / "including_outliers"
        / "488_509_x_DNA_mM_hue_Mg_mM_col_Salt_mM_endpoint_dose_response.csv"
    )
    excluding_csv = (
        result.output_dir
        / "endpoint_effects"
        / "faceted_dose_response"
        / "excluding_outliers"
        / "488_509_x_DNA_mM_hue_Mg_mM_col_Salt_mM_endpoint_dose_response.csv"
    )
    including = pd.read_csv(including_csv)
    excluding = pd.read_csv(excluding_csv)
    including_summary = including.loc[including["row_type"] == "summary"]
    excluding_summary = excluding.loc[excluding["row_type"] == "summary"]

    assert list(including_summary[["col_value", "x_value", "hue_value"]].itertuples(index=False, name=None)) == [
        (0.0, 0.0, 1.0),
        (0.0, 0.0, 2.0),
        (0.0, 1.0, 2.0),
        (1.0, 1.0, 1.0),
    ]

    outlier_group = including_summary.loc[
        (including_summary["col_value"] == 1.0)
        & (including_summary["x_value"] == 1.0)
        & (including_summary["hue_value"] == 1.0)
    ].iloc[0]
    outlier_group_excluded = excluding_summary.loc[
        (excluding_summary["col_value"] == 1.0)
        & (excluding_summary["x_value"] == 1.0)
        & (excluding_summary["hue_value"] == 1.0)
    ].iloc[0]
    candidate_group_excluded = excluding_summary.loc[
        (excluding_summary["col_value"] == 0.0)
        & (excluding_summary["x_value"] == 1.0)
        & (excluding_summary["hue_value"] == 2.0)
    ].iloc[0]

    assert outlier_group["endpoint_mean_rfu"] == pytest.approx(np.mean([100.0, 101.0, 102.0, 130.0]))
    assert outlier_group["endpoint_sd_rfu"] == pytest.approx(np.std([100.0, 101.0, 102.0, 130.0], ddof=1))
    assert outlier_group["endpoint_n"] == 4
    assert outlier_group["composition_count"] == 1
    assert outlier_group_excluded["endpoint_mean_rfu"] == pytest.approx(101.0)
    assert outlier_group_excluded["endpoint_n"] == 3
    assert candidate_group_excluded["endpoint_mean_rfu"] == pytest.approx(np.mean([100.0, 101.0, 102.0, 113.0]))
    assert candidate_group_excluded["endpoint_n"] == 4

    including_replicates = including.loc[
        (including["row_type"] == "replicate")
        & (including["col_value"] == 1.0)
        & (including["x_value"] == 1.0)
        & (including["hue_value"] == 1.0)
    ]
    excluding_replicates = excluding.loc[
        (excluding["row_type"] == "replicate")
        & (excluding["col_value"] == 1.0)
        & (excluding["x_value"] == 1.0)
        & (excluding["hue_value"] == 1.0)
    ]
    candidate_replicates = excluding.loc[
        (excluding["row_type"] == "replicate")
        & (excluding["col_value"] == 0.0)
        & (excluding["x_value"] == 1.0)
        & (excluding["hue_value"] == 2.0)
    ]
    assert set(including_replicates["well"]) == {"A5", "A6", "A7", "A8"}
    assert set(excluding_replicates["well"]) == {"A5", "A6", "A7"}
    assert set(candidate_replicates["well"]) == {"B1", "B2", "B3", "B4"}

    including_png = including_csv.with_suffix(".png")
    excluding_png = excluding_csv.with_suffix(".png")
    assert including_png.stat().st_size > 0
    assert excluding_png.stat().st_size > 0


def test_faceted_endpoint_dose_response_two_and_four_reagent_generation_rules(tmp_path):
    two_reagent_csv = _write_two_reagent_effects_merged_csv(tmp_path / "two_reagent_merged_tidy.csv")
    two_reagent_result = analysis.analyze_merged_tidy_csv(two_reagent_csv, tmp_path / "two_reagent_analysis")

    assert len(two_reagent_result.faceted_dose_response_pngs) == 4
    assert len(two_reagent_result.faceted_dose_response_csvs) == 4
    assert (
        two_reagent_result.output_dir
        / "endpoint_effects"
        / "faceted_dose_response"
        / "including_outliers"
        / "488_509_x_DNA_mM_hue_Mg_mM_endpoint_dose_response.png"
    ).stat().st_size > 0

    four_reagent_csv = _write_four_reagent_effects_merged_csv(tmp_path / "four_reagent_merged_tidy.csv")
    four_reagent_result = analysis.analyze_merged_tidy_csv(four_reagent_csv, tmp_path / "four_reagent_analysis")

    assert four_reagent_result.faceted_dose_response_pngs == []
    assert four_reagent_result.faceted_dose_response_csvs == []


def test_faceted_timecourse_grids_three_reagent_assignments(tmp_path):
    merged_csv = _write_endpoint_effects_merged_csv(tmp_path / "effects_merged_tidy.csv")
    result = analysis.analyze_merged_tidy_csv(merged_csv, tmp_path / "analysis")

    assert len(result.faceted_timecourse_pngs) == 12
    assert len(result.faceted_timecourse_csvs) == 12

    including_csv = (
        result.output_dir
        / "timecourses_faceted"
        / "including_outliers"
        / "488_509_row_DNA_mM_col_Mg_mM_hue_Salt_mM_timecourse_grid.csv"
    )
    excluding_csv = (
        result.output_dir
        / "timecourses_faceted"
        / "excluding_outliers"
        / "488_509_row_DNA_mM_col_Mg_mM_hue_Salt_mM_timecourse_grid.csv"
    )
    including = pd.read_csv(including_csv)
    excluding = pd.read_csv(excluding_csv)

    assert list(
        including.loc[including["time_seconds"] == 120.0, ["row_value", "col_value", "hue_value"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    ) == [
        (0.0, 1.0, 0.0),
        (0.0, 2.0, 0.0),
        (1.0, 1.0, 1.0),
        (1.0, 2.0, 0.0),
    ]

    outlier_group = including.loc[
        (including["row_value"] == 1.0)
        & (including["col_value"] == 1.0)
        & (including["hue_value"] == 1.0)
        & (including["time_seconds"] == 120.0)
    ].iloc[0]
    outlier_group_excluded = excluding.loc[
        (excluding["row_value"] == 1.0)
        & (excluding["col_value"] == 1.0)
        & (excluding["hue_value"] == 1.0)
        & (excluding["time_seconds"] == 120.0)
    ].iloc[0]
    candidate_group_excluded = excluding.loc[
        (excluding["row_value"] == 1.0)
        & (excluding["col_value"] == 2.0)
        & (excluding["hue_value"] == 0.0)
        & (excluding["time_seconds"] == 120.0)
    ].iloc[0]

    assert outlier_group["mean_rfu"] == pytest.approx(np.mean([100.0, 101.0, 102.0, 130.0]))
    assert outlier_group["sd_rfu"] == pytest.approx(np.std([100.0, 101.0, 102.0, 130.0], ddof=1))
    assert outlier_group["replicate_count"] == 4
    assert outlier_group["composition_count"] == 1
    assert outlier_group_excluded["mean_rfu"] == pytest.approx(101.0)
    assert outlier_group_excluded["sd_rfu"] == pytest.approx(np.std([100.0, 101.0, 102.0], ddof=1))
    assert outlier_group_excluded["replicate_count"] == 3
    assert outlier_group_excluded["composition_count"] == 1
    assert candidate_group_excluded["mean_rfu"] == pytest.approx(np.mean([100.0, 101.0, 102.0, 113.0]))
    assert candidate_group_excluded["replicate_count"] == 4

    including_png = including_csv.with_suffix(".png")
    excluding_png = excluding_csv.with_suffix(".png")
    assert including_png.stat().st_size > 0
    assert excluding_png.stat().st_size > 0


def test_faceted_timecourse_grids_two_and_four_reagent_generation_rules(tmp_path):
    two_reagent_csv = _write_two_reagent_effects_merged_csv(tmp_path / "two_reagent_merged_tidy.csv")
    two_reagent_result = analysis.analyze_merged_tidy_csv(two_reagent_csv, tmp_path / "two_reagent_analysis")

    assert len(two_reagent_result.faceted_timecourse_pngs) == 4
    assert len(two_reagent_result.faceted_timecourse_csvs) == 4
    assert (
        two_reagent_result.output_dir
        / "timecourses_faceted"
        / "including_outliers"
        / "488_509_col_DNA_mM_hue_Mg_mM_timecourse_grid.png"
    ).stat().st_size > 0

    four_reagent_csv = _write_four_reagent_effects_merged_csv(tmp_path / "four_reagent_merged_tidy.csv")
    four_reagent_result = analysis.analyze_merged_tidy_csv(four_reagent_csv, tmp_path / "four_reagent_analysis")

    assert four_reagent_result.faceted_timecourse_pngs == []
    assert four_reagent_result.faceted_timecourse_csvs == []


def test_faceted_timecourse_grid_plot_uses_faint_replicate_lines_without_mean_markers(tmp_path, monkeypatch):
    summary = pd.DataFrame(
        [
            {
                "fluorophore": "488_509",
                "row_reagent": "",
                "col_reagent": "DNA_mM",
                "hue_reagent": "Mg_mM",
                "row_value": "",
                "col_value": 0.0,
                "hue_value": 1.0,
                "time_seconds": 0.0,
                "time_minutes": 0.0,
                "mean_rfu": 11.0,
                "sd_rfu": np.std([10.0, 12.0], ddof=1),
                "replicate_count": 2,
                "composition_count": 1,
            },
            {
                "fluorophore": "488_509",
                "row_reagent": "",
                "col_reagent": "DNA_mM",
                "hue_reagent": "Mg_mM",
                "row_value": "",
                "col_value": 0.0,
                "hue_value": 1.0,
                "time_seconds": 60.0,
                "time_minutes": 1.0,
                "mean_rfu": 16.0,
                "sd_rfu": np.std([14.0, 18.0], ddof=1),
                "replicate_count": 2,
                "composition_count": 1,
            },
        ]
    )
    replicate_data = pd.DataFrame(
        [
            {"well": "A1", "condition_id": "condition_001", "fluorophore": "488_509", "time_seconds": 0.0, "time_minutes": 0.0, "rfu": 10.0, "DNA_mM": 0.0, "Mg_mM": 1.0},
            {"well": "A1", "condition_id": "condition_001", "fluorophore": "488_509", "time_seconds": 60.0, "time_minutes": 1.0, "rfu": 14.0, "DNA_mM": 0.0, "Mg_mM": 1.0},
            {"well": "A2", "condition_id": "condition_001", "fluorophore": "488_509", "time_seconds": 0.0, "time_minutes": 0.0, "rfu": 12.0, "DNA_mM": 0.0, "Mg_mM": 1.0},
            {"well": "A2", "condition_id": "condition_001", "fluorophore": "488_509", "time_seconds": 60.0, "time_minutes": 1.0, "rfu": 18.0, "DNA_mM": 0.0, "Mg_mM": 1.0},
        ]
    )
    original_close = analysis.plt.close
    monkeypatch.setattr(analysis.plt, "close", lambda fig=None: None)

    analysis.write_faceted_timecourse_grid_plot(
        summary,
        replicate_data,
        tmp_path / "grid.png",
        fluorophore="488_509",
        row_reagent=None,
        col_reagent="DNA_mM",
        hue_reagent="Mg_mM",
        variant_label="including outliers",
    )

    fig = analysis.plt.gcf()
    ax = fig.axes[0]
    replicate_lines = [line for line in ax.get_lines() if line.get_linewidth() == pytest.approx(0.8)]
    mean_lines = [line for line in ax.get_lines() if line.get_label() == "Mg_mM=1"]
    assert len(replicate_lines) == 2
    assert len(mean_lines) == 1
    mean_line = mean_lines[0]
    assert mean_line.get_marker() in {"None", "", None}
    for replicate_line in replicate_lines:
        assert replicate_line.get_color() == mean_line.get_color()
        assert replicate_line.get_alpha() == pytest.approx(0.22)
    assert (tmp_path / "grid.png").stat().st_size > 0
    original_close(fig)


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
    assert (
        output_dir / "endpoint_effects" / "main_effects" / "including_outliers" / "488_509_DNA_mM_main_effect.png"
    ).exists()
    assert (
        output_dir
        / "endpoint_variability"
        / "including_outliers"
        / "488_509_cv_vs_mean_endpoint_rfu.png"
    ).exists()
    manifest_path = output_dir / "analysis_manifest.json"
    report_path = output_dir / "analysis_report.html"
    assert manifest_path.exists()
    assert report_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "plate_reader_analysis_manifest_v1"
    assert manifest["inputs"]["endpoint_last_n"] == 3
    assert manifest["dataset"]["total_rows"] == 14
    assert manifest["dataset"]["endpoint_rows"] == 4
    assert manifest["dataset"]["composition_rows"] == 2
    assert manifest["dataset"]["keyed_well_count"] == 3
    assert manifest["dataset"]["measured_well_count"] == 4
    assert manifest["dataset"]["fluorophores"] == ["488_509"]
    assert manifest["dataset"]["condition_columns"] == ["DNA_mM", "Mg_mM"]
    assert manifest["dataset"]["has_timecourse_data"] is True
    assert manifest["outliers"]["final_outlier_count"] == 0
    output_records = manifest["outputs"]
    assert all(not Path(record["path"]).is_absolute() for record in output_records)
    output_categories = {record["category"] for record in output_records}
    assert {
        "analysis_package",
        "summary_tables",
        "absolute_rfu_heatmaps",
        "endpoint_outlier_heatmaps",
        "endpoint_variability",
        "combined_timecourse_plots",
        "endpoint_main_effects",
    }.issubset(output_categories)
    assert any(record["path"] == "endpoint_by_well.csv" for record in output_records)

    report_html = report_path.read_text(encoding="utf-8")
    assert "Plate Reader Analysis Report" in report_html
    assert "endpoint_by_well.csv" in report_html
    assert "heatmaps_absolute_rfu/488_509_endpoint_rfu.png" in report_html

    captured = capsys.readouterr()
    assert "[analysis] Resolving merged tidy data input" in captured.out
    assert "[analysis] Loading merged tidy CSV:" in captured.out
    assert "[analysis] Writing endpoint variability plots" in captured.out
    assert "[analysis] Writing per-composition timecourse plots: 2 plot(s)" in captured.out
    assert "[analysis] Analysis output generation complete" in captured.out
    assert "Endpoint rows: 4" in captured.out
    assert "Composition rows: 2" in captured.out
    assert "Timecourse summary excluding outliers:" in captured.out
    assert f"Analysis manifest: {manifest_path}" in captured.out
    assert f"Analysis report: {report_path}" in captured.out
    assert "Endpoint outliers: 0" in captured.out
    assert "Timecourse plots: 2" in captured.out
    assert "Combined timecourse plots: 2" in captured.out
    assert "Faceted timecourse grid plots: 0" in captured.out
    assert "Endpoint variability plots: 4" in captured.out
    assert "Endpoint main-effect plots: 2" in captured.out
    assert "Endpoint pairwise interaction plots: 0" in captured.out
    assert "Endpoint faceted dose-response plots: 0" in captured.out


def test_analysis_progress_callback_reports_major_steps(tmp_path):
    merged_csv = _write_synthetic_merged_csv(tmp_path / "experiment_merged_tidy.csv")
    messages: list[str] = []

    analysis.analyze_merged_tidy_csv(
        merged_csv,
        tmp_path / "analysis",
        progress_callback=messages.append,
    )

    assert messages[0].startswith("Preparing output directory:")
    assert any(message.startswith("Loaded ") for message in messages)
    assert any(message == "Preparing condition groups and plate coordinates" for message in messages)
    assert any(message.startswith("Endpoint table ready:") for message in messages)
    assert any(message == "Writing endpoint variability plots" for message in messages)
    assert any(message.startswith("Writing per-composition timecourse plots:") for message in messages)
    assert messages[-1] == "Analysis output generation complete"


def test_cli_with_endpoint_only_data_skips_timecourse_plots(tmp_path, capsys):
    merged_csv = _write_endpoint_only_merged_csv(tmp_path / "endpoint_merged_tidy.csv")
    output_dir = tmp_path / "endpoint_analysis"

    assert cli.main(["--merged-csv", str(merged_csv), "--output-dir", str(output_dir)]) == 0

    assert (output_dir / "endpoint_by_well.csv").exists()
    assert (output_dir / "composition_summary.csv").exists()
    assert (output_dir / "timecourse_summary.csv").exists()
    assert (output_dir / "timecourse_summary_excluding_outliers.csv").exists()
    assert (output_dir / "heatmaps_absolute_rfu" / "488_509_endpoint_rfu.png").exists()
    assert (
        output_dir / "endpoint_effects" / "main_effects" / "including_outliers" / "488_509_DNA_mM_main_effect.png"
    ).exists()

    timecourse = pd.read_csv(output_dir / "timecourse_summary.csv")
    assert len(timecourse) == 2
    assert set(timecourse["time_seconds"]) == {0.0}
    endpoint = pd.read_csv(output_dir / "endpoint_by_well.csv")
    assert endpoint["timecourse_peak_rfu"].isna().all()
    assert endpoint["timecourse_peak_time_minutes"].isna().all()
    assert endpoint["timecourse_drop_from_peak_percent"].isna().all()
    assert endpoint["timecourse_peak_vs_group_median_percent"].isna().all()
    assert not endpoint["is_timecourse_shape_outlier"].astype(bool).any()
    assert not list((output_dir / "timecourses").glob("*.png"))
    assert not list((output_dir / "timecourses_combined").glob("*.png"))
    assert not (output_dir / "timecourses_faceted").exists()
    manifest = json.loads((output_dir / "analysis_manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"]["has_timecourse_data"] is False
    assert manifest["warnings"] == [
        "Timecourse plots were skipped because fewer than two timepoints were found."
    ]
    report_html = (output_dir / "analysis_report.html").read_text(encoding="utf-8")
    assert "Timecourse plots were skipped because fewer than two timepoints were found." in report_html

    captured = capsys.readouterr()
    assert "Endpoint rows: 4" in captured.out
    assert "Timecourse plots: 0" in captured.out
    assert "Combined timecourse plots: 0" in captured.out
    assert "Faceted timecourse grid plots: 0" in captured.out
    assert "Endpoint main-effect plots: 2" in captured.out


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
