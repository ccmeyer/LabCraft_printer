#!/usr/bin/env python3
"""Reusable endpoint and plate-position analysis for merged plate-reader data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402


PLATE_ROWS = list("ABCDEFGHIJKLMNOP")
PLATE_COLUMNS = list(range(1, 25))
WELL_RE = re.compile(r"^([A-P])([1-9]|1[0-9]|2[0-4])$")
UNKEYED_CONDITION_ID = "unkeyed"
BASE_MERGED_COLUMNS = {
    "time",
    "time_seconds",
    "time_minutes",
    "temperature_c",
    "well",
    "is_keyed",
    "fluorophore",
    "excitation_nm",
    "emission_nm",
    "rfu",
}
ANALYSIS_COLUMNS = {
    "plate_row",
    "plate_col",
    "condition_id",
    "condition_label",
    "endpoint_rfu",
    "endpoint_timepoint_count",
    "endpoint_time_minutes_min",
    "endpoint_time_minutes_max",
    "condition_endpoint_mean_rfu",
    "condition_endpoint_sd_rfu",
    "condition_endpoint_cv_percent",
    "condition_endpoint_n",
    "condition_percent_difference_rfu",
}
REQUIRED_MERGED_COLUMNS = {
    "time_seconds",
    "time_minutes",
    "well",
    "is_keyed",
    "fluorophore",
    "rfu",
}


@dataclass(frozen=True)
class AnalysisResult:
    output_dir: Path
    endpoint_csv: Path
    composition_summary_csv: Path
    absolute_heatmap_csvs: list[Path]
    absolute_heatmap_pngs: list[Path]
    percent_difference_heatmap_csvs: list[Path]
    percent_difference_heatmap_pngs: list[Path]
    condition_columns: list[str]
    endpoint_rows: int
    composition_rows: int


def load_merged_tidy(path: str | Path) -> pd.DataFrame:
    merged_csv = Path(path)
    dataframe = pd.read_csv(merged_csv)
    validate_merged_tidy(dataframe)
    dataframe = dataframe.copy()
    dataframe["rfu"] = pd.to_numeric(dataframe["rfu"], errors="coerce")
    dataframe["time_seconds"] = pd.to_numeric(dataframe["time_seconds"], errors="coerce")
    dataframe["time_minutes"] = pd.to_numeric(dataframe["time_minutes"], errors="coerce")
    dataframe["well"] = dataframe["well"].astype(str).str.strip().str.upper()
    dataframe["fluorophore"] = dataframe["fluorophore"].astype(str).str.strip()
    dataframe["is_keyed"] = coerce_bool_series(dataframe["is_keyed"])
    return dataframe


def validate_merged_tidy(dataframe: pd.DataFrame) -> None:
    missing = sorted(REQUIRED_MERGED_COLUMNS - set(dataframe.columns))
    if missing:
        raise ValueError(f"Merged tidy CSV is missing required columns: {', '.join(missing)}")


def coerce_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)

    truthy = {"true", "1", "yes", "y"}
    return series.fillna(False).map(lambda value: str(value).strip().lower() in truthy)


def infer_condition_columns(dataframe: pd.DataFrame) -> list[str]:
    excluded = BASE_MERGED_COLUMNS | ANALYSIS_COLUMNS
    return [column for column in dataframe.columns if column not in excluded]


def add_plate_coordinates(dataframe: pd.DataFrame) -> pd.DataFrame:
    parsed_rows: list[str] = []
    parsed_columns: list[int] = []
    invalid_wells: set[str] = set()

    for well in dataframe["well"].astype(str):
        match = WELL_RE.match(well.strip().upper())
        if not match:
            invalid_wells.add(well)
            parsed_rows.append("")
            parsed_columns.append(0)
            continue
        parsed_rows.append(match.group(1))
        parsed_columns.append(int(match.group(2)))

    if invalid_wells:
        names = ", ".join(sorted(invalid_wells))
        raise ValueError(f"Invalid 384-well plate well IDs: {names}")

    result = dataframe.copy()
    result["plate_row"] = parsed_rows
    result["plate_col"] = parsed_columns
    return result


def prepare_analysis_dataframe(dataframe: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    prepared = add_plate_coordinates(dataframe)
    condition_columns = infer_condition_columns(prepared)
    prepared = normalize_keyed_condition_values(prepared, condition_columns)
    prepared = assign_condition_ids(prepared, condition_columns)
    return prepared, condition_columns


def normalize_keyed_condition_values(dataframe: pd.DataFrame, condition_columns: Iterable[str]) -> pd.DataFrame:
    result = dataframe.copy()
    keyed_mask = result["is_keyed"].astype(bool)
    for column in condition_columns:
        result.loc[keyed_mask, column] = result.loc[keyed_mask, column].map(normalize_condition_value)
    return result


def normalize_condition_value(value: object) -> object:
    if pd.isna(value):
        return 0
    if isinstance(value, str) and value.strip() == "":
        return 0
    return value


def assign_condition_ids(dataframe: pd.DataFrame, condition_columns: list[str]) -> pd.DataFrame:
    result = dataframe.copy()
    result["condition_id"] = UNKEYED_CONDITION_ID
    result["condition_label"] = UNKEYED_CONDITION_ID

    keyed_mask = result["is_keyed"].astype(bool)
    keyed_rows = result.loc[keyed_mask, condition_columns]
    if keyed_rows.empty:
        return result

    condition_keys = sorted(
        {condition_key_from_values(row, condition_columns) for _, row in keyed_rows.iterrows()},
        key=condition_sort_key,
    )
    condition_id_by_key = {
        key: f"condition_{index:03d}" for index, key in enumerate(condition_keys, start=1)
    }
    condition_label_by_key = {
        key: build_condition_label(key, condition_columns) for key in condition_keys
    }

    for index, row in result.loc[keyed_mask, condition_columns].iterrows():
        key = condition_key_from_values(row, condition_columns)
        result.at[index, "condition_id"] = condition_id_by_key[key]
        result.at[index, "condition_label"] = condition_label_by_key[key]

    return result


def condition_key_from_values(values: pd.Series, condition_columns: list[str]) -> tuple[object, ...]:
    return tuple(normalize_condition_value(values[column]) for column in condition_columns)


def condition_sort_key(condition_key: tuple[object, ...]) -> tuple[tuple[int, object], ...]:
    return tuple(sort_token(value) for value in condition_key)


def sort_token(value: object) -> tuple[int, object]:
    if isinstance(value, (int, float, np.integer, np.floating)) and not pd.isna(value):
        return (0, float(value))
    return (1, str(value))


def build_condition_label(condition_key: tuple[object, ...], condition_columns: list[str]) -> str:
    if not condition_columns:
        return "all_keyed_wells"
    parts = [
        f"{column}={format_condition_value(value)}"
        for column, value in zip(condition_columns, condition_key)
    ]
    return ", ".join(parts)


def format_condition_value(value: object) -> str:
    if isinstance(value, (int, float, np.integer, np.floating)) and not pd.isna(value):
        return f"{float(value):g}"
    return str(value)


def compute_endpoint_by_well(
    dataframe: pd.DataFrame,
    condition_columns: list[str],
    *,
    endpoint_last_n: int = 3,
) -> pd.DataFrame:
    if endpoint_last_n < 1:
        raise ValueError("--endpoint-last-n must be at least 1.")

    rows: list[dict[str, object]] = []
    sort_columns = ["well", "fluorophore", "time_seconds"]
    for (_well, _fluorophore), group in dataframe.sort_values(sort_columns).groupby(["well", "fluorophore"]):
        group_sorted = group.sort_values("time_seconds")
        endpoint_window = group_sorted.tail(endpoint_last_n)
        first_row = group_sorted.iloc[0]
        row = {
            "well": first_row["well"],
            "plate_row": first_row["plate_row"],
            "plate_col": int(first_row["plate_col"]),
            "fluorophore": first_row["fluorophore"],
            "is_keyed": bool(first_row["is_keyed"]),
            "condition_id": first_row["condition_id"],
            "condition_label": first_row["condition_label"],
            "endpoint_rfu": endpoint_window["rfu"].mean(),
            "endpoint_timepoint_count": int(endpoint_window["rfu"].count()),
            "endpoint_time_minutes_min": endpoint_window["time_minutes"].min(),
            "endpoint_time_minutes_max": endpoint_window["time_minutes"].max(),
        }
        for column in condition_columns:
            row[column] = first_row[column]
        rows.append(row)

    endpoint = pd.DataFrame(rows)
    summary = summarize_compositions(endpoint, condition_columns)
    endpoint = endpoint.merge(
        summary[
            [
                "condition_id",
                "fluorophore",
                "endpoint_mean_rfu",
                "endpoint_sd_rfu",
                "endpoint_cv_percent",
                "replicate_count",
            ]
        ].rename(
            columns={
                "endpoint_mean_rfu": "condition_endpoint_mean_rfu",
                "endpoint_sd_rfu": "condition_endpoint_sd_rfu",
                "endpoint_cv_percent": "condition_endpoint_cv_percent",
                "replicate_count": "condition_endpoint_n",
            }
        ),
        on=["condition_id", "fluorophore"],
        how="left",
    )
    endpoint["condition_percent_difference_rfu"] = np.nan
    eligible = (
        endpoint["is_keyed"].astype(bool)
        & (endpoint["condition_endpoint_n"] >= 2)
        & endpoint["condition_endpoint_mean_rfu"].notna()
        & (endpoint["condition_endpoint_mean_rfu"] != 0)
    )
    endpoint.loc[eligible, "condition_percent_difference_rfu"] = (
        100.0
        * (
            endpoint.loc[eligible, "endpoint_rfu"]
            - endpoint.loc[eligible, "condition_endpoint_mean_rfu"]
        )
        / endpoint.loc[eligible, "condition_endpoint_mean_rfu"]
    )

    ordered_columns = (
        [
            "well",
            "plate_row",
            "plate_col",
            "fluorophore",
            "is_keyed",
            "condition_id",
            "condition_label",
        ]
        + condition_columns
        + [
            "endpoint_rfu",
            "endpoint_timepoint_count",
            "endpoint_time_minutes_min",
            "endpoint_time_minutes_max",
            "condition_endpoint_mean_rfu",
            "condition_endpoint_sd_rfu",
            "condition_endpoint_cv_percent",
            "condition_endpoint_n",
            "condition_percent_difference_rfu",
        ]
    )
    return endpoint[ordered_columns].sort_values(
        ["fluorophore", "condition_id", "plate_row", "plate_col", "well"],
        kind="stable",
    ).reset_index(drop=True)


def summarize_compositions(endpoint: pd.DataFrame, condition_columns: list[str]) -> pd.DataFrame:
    keyed_endpoint = endpoint.loc[endpoint["condition_id"] != UNKEYED_CONDITION_ID].copy()
    if keyed_endpoint.empty:
        columns = [
            "condition_id",
            "condition_label",
            "fluorophore",
            "replicate_count",
            "endpoint_mean_rfu",
            "endpoint_sd_rfu",
            "endpoint_cv_percent",
            "endpoint_min_rfu",
            "endpoint_max_rfu",
        ] + condition_columns
        return pd.DataFrame(columns=columns)

    grouped = keyed_endpoint.groupby(["condition_id", "fluorophore"], as_index=False)
    summary = grouped.agg(
        condition_label=("condition_label", "first"),
        replicate_count=("endpoint_rfu", "count"),
        endpoint_mean_rfu=("endpoint_rfu", "mean"),
        endpoint_sd_rfu=("endpoint_rfu", "std"),
        endpoint_min_rfu=("endpoint_rfu", "min"),
        endpoint_max_rfu=("endpoint_rfu", "max"),
    )
    summary["endpoint_cv_percent"] = np.where(
        summary["endpoint_mean_rfu"].notna() & (summary["endpoint_mean_rfu"] != 0),
        100.0 * summary["endpoint_sd_rfu"] / summary["endpoint_mean_rfu"],
        np.nan,
    )

    condition_values = (
        keyed_endpoint[["condition_id"] + condition_columns]
        .drop_duplicates("condition_id")
        .reset_index(drop=True)
    )
    summary = summary.merge(condition_values, on="condition_id", how="left")
    ordered_columns = [
        "condition_id",
        "condition_label",
        "fluorophore",
        "replicate_count",
        "endpoint_mean_rfu",
        "endpoint_sd_rfu",
        "endpoint_cv_percent",
        "endpoint_min_rfu",
        "endpoint_max_rfu",
    ] + condition_columns
    return summary[ordered_columns].sort_values(
        ["fluorophore", "condition_id"],
        kind="stable",
    ).reset_index(drop=True)


def build_plate_heatmap(endpoint: pd.DataFrame, fluorophore: str, value_column: str) -> pd.DataFrame:
    channel = endpoint.loc[endpoint["fluorophore"] == fluorophore]
    matrix = channel.pivot(index="plate_row", columns="plate_col", values=value_column)
    return matrix.reindex(index=PLATE_ROWS, columns=PLATE_COLUMNS)


def write_plate_heatmap_plot(
    matrix: pd.DataFrame,
    path: str | Path,
    *,
    title: str,
    label: str,
    cmap: str,
    center: float | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 7), constrained_layout=True)
    kwargs: dict[str, object] = {
        "cmap": cmap,
        "ax": ax,
        "cbar_kws": {"label": label},
        "linewidths": 0.2,
        "linecolor": "0.85",
    }
    if center is not None:
        kwargs["center"] = center
    sns.heatmap(matrix, **kwargs)
    ax.set_title(title)
    ax.set_xlabel("Plate column")
    ax.set_ylabel("Plate row")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def analyze_merged_tidy_csv(
    merged_csv: str | Path,
    output_dir: str | Path,
    *,
    endpoint_last_n: int = 3,
) -> AnalysisResult:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    absolute_dir = output_root / "heatmaps_absolute_rfu"
    percent_dir = output_root / "heatmaps_condition_percent_difference"
    absolute_dir.mkdir(parents=True, exist_ok=True)
    percent_dir.mkdir(parents=True, exist_ok=True)

    merged = load_merged_tidy(merged_csv)
    prepared, condition_columns = prepare_analysis_dataframe(merged)
    endpoint = compute_endpoint_by_well(
        prepared,
        condition_columns,
        endpoint_last_n=endpoint_last_n,
    )
    summary = summarize_compositions(endpoint, condition_columns)

    endpoint_csv = output_root / "endpoint_by_well.csv"
    composition_summary_csv = output_root / "composition_summary.csv"
    endpoint.to_csv(endpoint_csv, index=False)
    summary.to_csv(composition_summary_csv, index=False)

    absolute_csvs: list[Path] = []
    absolute_pngs: list[Path] = []
    percent_csvs: list[Path] = []
    percent_pngs: list[Path] = []
    for fluorophore in sorted(endpoint["fluorophore"].dropna().astype(str).unique()):
        safe_name = safe_filename(fluorophore)

        absolute_matrix = build_plate_heatmap(endpoint, fluorophore, "endpoint_rfu")
        absolute_csv = absolute_dir / f"{safe_name}_endpoint_rfu.csv"
        absolute_png = absolute_dir / f"{safe_name}_endpoint_rfu.png"
        absolute_matrix.to_csv(absolute_csv)
        write_plate_heatmap_plot(
            absolute_matrix,
            absolute_png,
            title=f"{fluorophore} endpoint RFU",
            label="Endpoint RFU",
            cmap="viridis",
        )
        absolute_csvs.append(absolute_csv)
        absolute_pngs.append(absolute_png)

        percent_matrix = build_plate_heatmap(endpoint, fluorophore, "condition_percent_difference_rfu")
        percent_csv = percent_dir / f"{safe_name}_condition_percent_difference.csv"
        percent_png = percent_dir / f"{safe_name}_condition_percent_difference.png"
        percent_matrix.to_csv(percent_csv)
        write_plate_heatmap_plot(
            percent_matrix,
            percent_png,
            title=f"{fluorophore} condition percent difference",
            label="Percent difference from condition mean (%)",
            cmap="coolwarm",
            center=0.0,
        )
        percent_csvs.append(percent_csv)
        percent_pngs.append(percent_png)

    return AnalysisResult(
        output_dir=output_root,
        endpoint_csv=endpoint_csv,
        composition_summary_csv=composition_summary_csv,
        absolute_heatmap_csvs=absolute_csvs,
        absolute_heatmap_pngs=absolute_pngs,
        percent_difference_heatmap_csvs=percent_csvs,
        percent_difference_heatmap_pngs=percent_pngs,
        condition_columns=condition_columns,
        endpoint_rows=len(endpoint),
        composition_rows=len(summary),
    )


def safe_filename(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    text = text.strip("._")
    return text or "channel"
