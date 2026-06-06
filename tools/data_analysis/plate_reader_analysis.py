#!/usr/bin/env python3
"""Reusable endpoint and plate-position analysis for merged plate-reader data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations, permutations
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
OUTLIER_ROBUST_Z_THRESHOLD = 3.5
OUTLIER_MIN_RELATIVE_DELTA_PERCENT = 15.0
OUTLIER_TRIPLICATE_MIN_GROUP_CV_PERCENT = 35.0
OUTLIER_TRIPLICATE_LOW_SIGNAL_DROP_PERCENT = 60.0
OUTLIER_TRIPLICATE_MAX_HIGH_PAIR_CV_PERCENT = 30.0
OUTLIER_TRIPLICATE_HIGH_SIGNAL_ABOVE_MID_PERCENT = 100.0
ENDPOINT_EFFECT_VARIANTS = (
    ("including_outliers", "including outliers"),
    ("excluding_outliers", "excluding endpoint outliers"),
)
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
    "condition_endpoint_median_rfu",
    "condition_endpoint_mad_rfu",
    "condition_endpoint_robust_zscore",
    "condition_endpoint_relative_delta_percent",
    "is_endpoint_outlier_candidate",
    "outlier_candidate_reason",
    "is_endpoint_outlier",
    "outlier_reason",
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
    timecourse_summary_csv: Path
    timecourse_excluding_outliers_summary_csv: Path
    outlier_summary_csv: Path
    absolute_heatmap_csvs: list[Path]
    absolute_heatmap_pngs: list[Path]
    percent_difference_heatmap_csvs: list[Path]
    percent_difference_heatmap_pngs: list[Path]
    outlier_heatmap_csvs: list[Path]
    outlier_heatmap_pngs: list[Path]
    timecourse_plot_pngs: list[Path]
    combined_timecourse_plot_pngs: list[Path]
    main_effect_csvs: list[Path]
    main_effect_pngs: list[Path]
    pairwise_interaction_csvs: list[Path]
    pairwise_interaction_pngs: list[Path]
    faceted_dose_response_csvs: list[Path]
    faceted_dose_response_pngs: list[Path]
    faceted_timecourse_csvs: list[Path]
    faceted_timecourse_pngs: list[Path]
    outlier_count: int
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
    endpoint = add_endpoint_outlier_flags(endpoint)

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
            "condition_endpoint_median_rfu",
            "condition_endpoint_mad_rfu",
            "condition_endpoint_robust_zscore",
            "condition_endpoint_relative_delta_percent",
            "is_endpoint_outlier_candidate",
            "outlier_candidate_reason",
            "is_endpoint_outlier",
            "outlier_reason",
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


def coefficient_of_variation_percent(values: pd.Series | np.ndarray) -> float:
    array = np.asarray(values, dtype=float)
    mean = float(np.mean(array))
    if len(array) < 2 or mean == 0:
        return float("nan")
    return float(100.0 * np.std(array, ddof=1) / mean)


def triplicate_split_outlier(endpoint_group: pd.DataFrame) -> tuple[int, str] | None:
    if len(endpoint_group) != 3:
        return None

    sorted_group = endpoint_group.sort_values("endpoint_rfu", kind="stable")
    values = sorted_group["endpoint_rfu"].to_numpy(dtype=float)
    low, mid, high = values
    group_cv = coefficient_of_variation_percent(values)
    if not np.isfinite(group_cv) or group_cv < OUTLIER_TRIPLICATE_MIN_GROUP_CV_PERCENT:
        return None

    high_pair = values[1:]
    high_pair_mean = float(np.mean(high_pair))
    high_pair_cv = coefficient_of_variation_percent(high_pair)
    low_drop_percent = (
        100.0 * (high_pair_mean - low) / high_pair_mean
        if high_pair_mean != 0
        else float("nan")
    )
    if (
        np.isfinite(low_drop_percent)
        and np.isfinite(high_pair_cv)
        and low_drop_percent >= OUTLIER_TRIPLICATE_LOW_SIGNAL_DROP_PERCENT
        and high_pair_cv <= OUTLIER_TRIPLICATE_MAX_HIGH_PAIR_CV_PERCENT
    ):
        return int(sorted_group.index[0]), "triplicate_low_signal_split"

    if mid != 0:
        high_above_mid_percent = 100.0 * (high - mid) / mid
    else:
        high_above_mid_percent = float("inf") if high > mid else float("nan")
    if (
        np.isfinite(high_above_mid_percent)
        and high_above_mid_percent >= OUTLIER_TRIPLICATE_HIGH_SIGNAL_ABOVE_MID_PERCENT
    ):
        return int(sorted_group.index[2]), "triplicate_high_signal_split"

    return None


def add_endpoint_outlier_flags(endpoint: pd.DataFrame) -> pd.DataFrame:
    result = endpoint.copy()
    result["condition_endpoint_median_rfu"] = np.nan
    result["condition_endpoint_mad_rfu"] = np.nan
    result["condition_endpoint_robust_zscore"] = np.nan
    result["condition_endpoint_relative_delta_percent"] = np.nan
    result["is_endpoint_outlier_candidate"] = False
    result["outlier_candidate_reason"] = ""
    result["is_endpoint_outlier"] = False
    result["outlier_reason"] = ""

    keyed = result.loc[
        (result["condition_id"] != UNKEYED_CONDITION_ID)
        & result["is_keyed"].astype(bool)
    ]
    for (_condition_id, _fluorophore), group in keyed.groupby(["condition_id", "fluorophore"]):
        if len(group) < 3:
            continue

        values = group["endpoint_rfu"].astype(float)
        median = float(values.median())
        mad = float((values - median).abs().median())
        result.loc[group.index, "condition_endpoint_median_rfu"] = median
        result.loc[group.index, "condition_endpoint_mad_rfu"] = mad
        if median != 0:
            relative_delta_percent = 100.0 * (values - median) / median
        else:
            relative_delta_percent = values.map(lambda value: 0.0 if value == 0 else np.nan)
        result.loc[group.index, "condition_endpoint_relative_delta_percent"] = relative_delta_percent

        if mad == 0:
            differences = values - median
            robust_z = differences.map(
                lambda value: 0.0 if value == 0 else float(np.inf if value > 0 else -np.inf)
            )
            candidate_mask = differences != 0
            final_mask = candidate_mask & (
                relative_delta_percent.abs() >= OUTLIER_MIN_RELATIVE_DELTA_PERCENT
            )
            candidate_indices = group.index[candidate_mask.to_numpy()]
            final_indices = group.index[final_mask.to_numpy()]
            result.loc[group.index, "condition_endpoint_robust_zscore"] = robust_z
            result.loc[candidate_indices, "is_endpoint_outlier_candidate"] = True
            result.loc[candidate_indices, "outlier_candidate_reason"] = "mad_zero_nonmedian"
            result.loc[final_indices, "is_endpoint_outlier"] = True
            result.loc[final_indices, "outlier_reason"] = "mad_zero_nonmedian"
            if len(group) == 3 and not bool(result.loc[group.index, "is_endpoint_outlier"].any()):
                split_outlier = triplicate_split_outlier(group)
                if split_outlier is not None:
                    outlier_index, split_reason = split_outlier
                    result.loc[outlier_index, "is_endpoint_outlier_candidate"] = True
                    result.loc[outlier_index, "outlier_candidate_reason"] = split_reason
                    result.loc[outlier_index, "is_endpoint_outlier"] = True
                    result.loc[outlier_index, "outlier_reason"] = split_reason
            continue

        robust_z = 0.6745 * (values - median) / mad
        candidate_mask = robust_z.abs() >= OUTLIER_ROBUST_Z_THRESHOLD
        final_mask = candidate_mask & (
            relative_delta_percent.abs() >= OUTLIER_MIN_RELATIVE_DELTA_PERCENT
        )
        candidate_indices = group.index[candidate_mask.to_numpy()]
        final_indices = group.index[final_mask.to_numpy()]
        candidate_reason = f"robust_z_abs_ge_{OUTLIER_ROBUST_Z_THRESHOLD:g}"
        result.loc[group.index, "condition_endpoint_robust_zscore"] = robust_z
        result.loc[candidate_indices, "is_endpoint_outlier_candidate"] = True
        result.loc[candidate_indices, "outlier_candidate_reason"] = candidate_reason
        result.loc[final_indices, "is_endpoint_outlier"] = True
        result.loc[final_indices, "outlier_reason"] = candidate_reason

        if len(group) == 3 and not bool(result.loc[group.index, "is_endpoint_outlier"].any()):
            split_outlier = triplicate_split_outlier(group)
            if split_outlier is not None:
                outlier_index, split_reason = split_outlier
                result.loc[outlier_index, "is_endpoint_outlier_candidate"] = True
                result.loc[outlier_index, "outlier_candidate_reason"] = split_reason
                result.loc[outlier_index, "is_endpoint_outlier"] = True
                result.loc[outlier_index, "outlier_reason"] = split_reason

    return result


def summarize_condition_timecourses(dataframe: pd.DataFrame, condition_columns: list[str]) -> pd.DataFrame:
    keyed = dataframe.loc[dataframe["condition_id"] != UNKEYED_CONDITION_ID].copy()
    if keyed.empty:
        columns = [
            "condition_id",
            "condition_label",
            "fluorophore",
            "time_seconds",
            "time_minutes",
            "mean_rfu",
            "sd_rfu",
            "replicate_count",
        ] + condition_columns
        return pd.DataFrame(columns=columns)

    group_columns = ["condition_id", "fluorophore", "time_seconds", "time_minutes"]
    summary = (
        keyed.groupby(group_columns, as_index=False)
        .agg(
            condition_label=("condition_label", "first"),
            mean_rfu=("rfu", "mean"),
            sd_rfu=("rfu", "std"),
            replicate_count=("rfu", "count"),
        )
        .sort_values(["fluorophore", "condition_id", "time_seconds"], kind="stable")
        .reset_index(drop=True)
    )
    condition_values = (
        keyed[["condition_id"] + condition_columns]
        .drop_duplicates("condition_id")
        .reset_index(drop=True)
    )
    summary = summary.merge(condition_values, on="condition_id", how="left")
    ordered_columns = [
        "condition_id",
        "condition_label",
        "fluorophore",
        "time_seconds",
        "time_minutes",
        "mean_rfu",
        "sd_rfu",
        "replicate_count",
    ] + condition_columns
    return summary[ordered_columns].sort_values(
        ["fluorophore", "condition_id", "time_seconds"],
        kind="stable",
    ).reset_index(drop=True)


def has_timecourse_data(dataframe: pd.DataFrame) -> bool:
    return dataframe["time_seconds"].dropna().nunique() >= 2


def write_condition_timecourse_plot(
    replicate_data: pd.DataFrame,
    summary_data: pd.DataFrame,
    path: str | Path,
    *,
    condition_id: str,
    fluorophore: str,
    condition_label: str,
) -> None:
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    outlier_label_used = False

    for _well, well_df in replicate_data.groupby("well"):
        well_df = well_df.sort_values("time_seconds")
        is_outlier = bool(well_df.get("is_endpoint_outlier", pd.Series(False, index=well_df.index)).any())
        line_kwargs = {
            "color": "tab:red" if is_outlier else "0.35",
            "alpha": 0.9 if is_outlier else 0.25,
            "linewidth": 1.6 if is_outlier else 0.9,
            "zorder": 3 if is_outlier else 1,
        }
        if is_outlier and not outlier_label_used:
            line_kwargs["label"] = "endpoint outlier"
            outlier_label_used = True
        ax.plot(
            well_df["time_minutes"],
            well_df["rfu"],
            **line_kwargs,
        )

    summary_sorted = summary_data.sort_values("time_seconds")
    x = summary_sorted["time_minutes"].to_numpy(dtype=float)
    mean = summary_sorted["mean_rfu"].to_numpy(dtype=float)
    sd = summary_sorted["sd_rfu"].fillna(0).to_numpy(dtype=float)
    ax.fill_between(x, mean - sd, mean + sd, color="tab:blue", alpha=0.18)
    ax.plot(x, mean, color="tab:blue", linewidth=2.5, label="mean +/- SD")
    ax.set_title(f"{condition_id} {fluorophore}\n{condition_label}")
    ax.set_xlabel("Time (min)")
    ax.set_ylabel("RFU")
    ax.legend(frameon=False)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def build_condition_color_map(condition_ids: list[str]) -> dict[str, tuple[float, float, float]]:
    if not condition_ids:
        return {}
    palette = sns.color_palette("husl", n_colors=len(condition_ids))
    return dict(zip(condition_ids, palette))


def write_combined_condition_timecourse_plot(
    summary_data: pd.DataFrame,
    path: str | Path,
    *,
    fluorophore: str,
    title_suffix: str,
    color_by_condition: dict[str, tuple[float, float, float]],
) -> None:
    fig, ax = plt.subplots(figsize=(13, 7), constrained_layout=True)
    plotted_conditions = 0

    condition_ids = sorted(summary_data["condition_id"].dropna().astype(str).unique())
    for condition_id in condition_ids:
        condition_summary = summary_data.loc[summary_data["condition_id"] == condition_id].sort_values("time_seconds")
        if condition_summary.empty:
            continue

        color = color_by_condition.get(condition_id, "tab:blue")
        x = condition_summary["time_minutes"].to_numpy(dtype=float)
        mean = condition_summary["mean_rfu"].to_numpy(dtype=float)
        sd = condition_summary["sd_rfu"].fillna(0).to_numpy(dtype=float)
        ax.fill_between(x, mean - sd, mean + sd, color=color, alpha=0.14, linewidth=0)
        ax.plot(x, mean, color=color, linewidth=2.0, label=condition_id)
        plotted_conditions += 1

    if plotted_conditions:
        ax.legend(
            title="Composition",
            frameon=False,
            bbox_to_anchor=(1.01, 1.0),
            loc="upper left",
        )
    else:
        ax.text(
            0.5,
            0.5,
            "No keyed composition data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )

    ax.set_title(f"{fluorophore}\n{title_suffix}")
    ax.set_xlabel("Time (min)")
    ax.set_ylabel("RFU")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def faceted_timecourse_grid_assignments(varying_columns: list[str]) -> list[tuple[str | None, str, str]]:
    if len(varying_columns) == 2:
        first, second = varying_columns
        return [(None, first, second), (None, second, first)]
    if len(varying_columns) == 3:
        return [(row_reagent, col_reagent, hue_reagent) for row_reagent, col_reagent, hue_reagent in permutations(varying_columns, 3)]
    return []


def build_faceted_timecourse_grid_summary(
    dataframe: pd.DataFrame,
    *,
    fluorophore: str,
    row_reagent: str | None,
    col_reagent: str,
    hue_reagent: str,
) -> pd.DataFrame:
    columns = [
        "fluorophore",
        "row_reagent",
        "col_reagent",
        "hue_reagent",
        "row_value",
        "col_value",
        "hue_value",
        "time_seconds",
        "time_minutes",
        "mean_rfu",
        "sd_rfu",
        "replicate_count",
        "composition_count",
    ]
    channel = dataframe.loc[dataframe["fluorophore"] == fluorophore]
    if channel.empty:
        return pd.DataFrame(columns=columns)

    row_values = unique_sorted_values(channel[row_reagent]) if row_reagent is not None else [""]
    col_values = unique_sorted_values(channel[col_reagent])
    hue_values = unique_sorted_values(channel[hue_reagent])
    rows: list[dict[str, object]] = []
    for row_value in row_values:
        row_group = channel
        if row_reagent is not None:
            row_group = row_group.loc[condition_value_mask(row_group[row_reagent], row_value)]
        for col_value in col_values:
            col_group = row_group.loc[condition_value_mask(row_group[col_reagent], col_value)]
            for hue_value in hue_values:
                group = col_group.loc[condition_value_mask(col_group[hue_reagent], hue_value)]
                if group.empty:
                    continue
                time_summary = (
                    group.groupby(["time_seconds", "time_minutes"], as_index=False)
                    .agg(
                        mean_rfu=("rfu", "mean"),
                        sd_rfu=("rfu", "std"),
                        replicate_count=("rfu", "count"),
                        composition_count=("condition_id", "nunique"),
                    )
                    .sort_values("time_seconds", kind="stable")
                )
                for _, time_row in time_summary.iterrows():
                    rows.append(
                        {
                            "fluorophore": fluorophore,
                            "row_reagent": row_reagent or "",
                            "col_reagent": col_reagent,
                            "hue_reagent": hue_reagent,
                            "row_value": row_value,
                            "col_value": col_value,
                            "hue_value": hue_value,
                            "time_seconds": time_row["time_seconds"],
                            "time_minutes": time_row["time_minutes"],
                            "mean_rfu": time_row["mean_rfu"],
                            "sd_rfu": time_row["sd_rfu"],
                            "replicate_count": int(time_row["replicate_count"]),
                            "composition_count": int(time_row["composition_count"]),
                        }
                    )

    return pd.DataFrame(rows, columns=columns)


def write_faceted_timecourse_grid_plot(
    summary: pd.DataFrame,
    replicate_data: pd.DataFrame,
    path: str | Path,
    *,
    fluorophore: str,
    row_reagent: str | None,
    col_reagent: str,
    hue_reagent: str,
    variant_label: str,
) -> None:
    row_values = unique_sorted_values(summary["row_value"]) if row_reagent is not None else [""]
    col_values = unique_sorted_values(summary["col_value"])
    hue_values = unique_sorted_values(summary["hue_value"])
    hue_labels = [format_condition_value(value) for value in hue_values]
    palette = sns.color_palette("husl", n_colors=max(len(hue_labels), 1))
    color_by_hue = dict(zip(hue_labels, palette))
    row_count = len(row_values)
    col_count = len(col_values)
    fig_width = max(7.0, 4.8 * col_count)
    fig_height = max(5.0, 3.8 * row_count)
    fig, axes = plt.subplots(
        row_count,
        col_count,
        figsize=(fig_width, fig_height),
        sharex=True,
        sharey=True,
        constrained_layout=True,
    )
    axes = np.asarray(axes).reshape(row_count, col_count)

    for row_index, row_value in enumerate(row_values):
        row_summary = summary
        if row_reagent is not None:
            row_summary = row_summary.loc[condition_value_mask(row_summary["row_value"], row_value)]
            row_replicates = replicate_data.loc[condition_value_mask(replicate_data[row_reagent], row_value)]
        else:
            row_replicates = replicate_data
        for col_index, col_value in enumerate(col_values):
            ax = axes[row_index, col_index]
            panel = row_summary.loc[condition_value_mask(row_summary["col_value"], col_value)]
            panel_replicates = row_replicates.loc[condition_value_mask(row_replicates[col_reagent], col_value)]
            for hue_value, hue_label in zip(hue_values, hue_labels):
                hue_summary = panel.loc[condition_value_mask(panel["hue_value"], hue_value)].sort_values("time_seconds")
                if hue_summary.empty:
                    continue
                color = color_by_hue[hue_label]
                hue_replicates = panel_replicates.loc[condition_value_mask(panel_replicates[hue_reagent], hue_value)]
                for (_well, _condition_id), replicate in hue_replicates.groupby(["well", "condition_id"]):
                    replicate = replicate.sort_values("time_seconds")
                    ax.plot(
                        replicate["time_minutes"],
                        replicate["rfu"],
                        color=color,
                        alpha=0.22,
                        linewidth=0.8,
                        zorder=1,
                    )
                x = hue_summary["time_minutes"].to_numpy(dtype=float)
                mean = hue_summary["mean_rfu"].to_numpy(dtype=float)
                sd = hue_summary["sd_rfu"].fillna(0).to_numpy(dtype=float)
                ax.fill_between(x, mean - sd, mean + sd, color=color, alpha=0.16, linewidth=0, zorder=2)
                ax.plot(
                    x,
                    mean,
                    color=color,
                    linewidth=2.0,
                    label=f"{hue_reagent}={hue_label}",
                    zorder=3,
                )

            title_parts = [f"{col_reagent}={format_condition_value(col_value)}"]
            if row_reagent is not None:
                title_parts.insert(0, f"{row_reagent}={format_condition_value(row_value)}")
            ax.set_title(", ".join(title_parts))
            ax.grid(axis="y", color="0.9", linewidth=0.7)
            if row_index == row_count - 1:
                ax.set_xlabel("Time (min)")
            if col_index == 0:
                ax.set_ylabel("RFU")

    handles, labels = axes[0, 0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, frameon=False, title=hue_reagent, loc="upper right")
    row_part = f"row={row_reagent}, " if row_reagent is not None else ""
    fig.suptitle(
        f"{fluorophore} faceted timecourse grid ({variant_label})\n"
        f"{row_part}column={col_reagent}, hue={hue_reagent}"
    )
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_faceted_timecourse_grid_outputs(
    keyed_prepared: pd.DataFrame,
    condition_columns: list[str],
    output_root: Path,
) -> tuple[list[Path], list[Path]]:
    timecourse_root = output_root / "timecourses_faceted"
    timecourse_csvs: list[Path] = []
    timecourse_pngs: list[Path] = []

    for variant_name, variant_label in ENDPOINT_EFFECT_VARIANTS:
        variant_data = keyed_prepared
        if variant_name == "excluding_outliers":
            variant_data = variant_data.loc[~variant_data["is_endpoint_outlier"].astype(bool)]
        variant_dir = timecourse_root / variant_name
        variant_dir.mkdir(parents=True, exist_ok=True)
        if variant_data.empty or not condition_columns:
            continue

        for fluorophore in sorted(variant_data["fluorophore"].dropna().astype(str).unique()):
            channel = variant_data.loc[variant_data["fluorophore"] == fluorophore]
            varying_columns = varying_condition_columns(channel, condition_columns)
            assignments = faceted_timecourse_grid_assignments(varying_columns)
            if not assignments:
                continue

            safe_fluorophore = safe_filename(fluorophore)
            for row_reagent, col_reagent, hue_reagent in assignments:
                summary = build_faceted_timecourse_grid_summary(
                    variant_data,
                    fluorophore=fluorophore,
                    row_reagent=row_reagent,
                    col_reagent=col_reagent,
                    hue_reagent=hue_reagent,
                )
                if summary.empty:
                    continue
                if row_reagent is None:
                    stem = (
                        f"{safe_fluorophore}_col_{safe_filename(col_reagent)}"
                        f"_hue_{safe_filename(hue_reagent)}_timecourse_grid"
                    )
                else:
                    stem = (
                        f"{safe_fluorophore}_row_{safe_filename(row_reagent)}"
                        f"_col_{safe_filename(col_reagent)}"
                        f"_hue_{safe_filename(hue_reagent)}_timecourse_grid"
                    )
                csv_path = variant_dir / f"{stem}.csv"
                png_path = variant_dir / f"{stem}.png"
                summary.to_csv(csv_path, index=False)
                write_faceted_timecourse_grid_plot(
                    summary,
                    variant_data.loc[variant_data["fluorophore"] == fluorophore],
                    png_path,
                    fluorophore=fluorophore,
                    row_reagent=row_reagent,
                    col_reagent=col_reagent,
                    hue_reagent=hue_reagent,
                    variant_label=variant_label,
                )
                timecourse_csvs.append(csv_path)
                timecourse_pngs.append(png_path)

    return timecourse_csvs, timecourse_pngs


def build_plate_heatmap(endpoint: pd.DataFrame, fluorophore: str, value_column: str) -> pd.DataFrame:
    channel = endpoint.loc[endpoint["fluorophore"] == fluorophore]
    matrix = channel.pivot(index="plate_row", columns="plate_col", values=value_column)
    return matrix.reindex(index=PLATE_ROWS, columns=PLATE_COLUMNS)


def build_outlier_heatmap(endpoint: pd.DataFrame, fluorophore: str) -> pd.DataFrame:
    channel = endpoint.loc[endpoint["fluorophore"] == fluorophore].copy()
    evaluated = (
        channel["is_keyed"].astype(bool)
        & (channel["condition_id"] != UNKEYED_CONDITION_ID)
        & channel["condition_endpoint_median_rfu"].notna()
    )
    channel["endpoint_outlier_count"] = np.nan
    channel.loc[evaluated, "endpoint_outlier_count"] = channel.loc[
        evaluated, "is_endpoint_outlier"
    ].astype(int)
    matrix = channel.pivot(index="plate_row", columns="plate_col", values="endpoint_outlier_count")
    return matrix.reindex(index=PLATE_ROWS, columns=PLATE_COLUMNS)


def write_plate_heatmap_plot(
    matrix: pd.DataFrame,
    path: str | Path,
    *,
    title: str,
    label: str,
    cmap: str,
    center: float | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 7), constrained_layout=True)
    if matrix.isna().all().all():
        ax.text(
            0.5,
            0.5,
            "No data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_title(title)
        ax.set_xlabel("Plate column")
        ax.set_ylabel("Plate row")
        fig.savefig(path, dpi=150)
        plt.close(fig)
        return

    kwargs: dict[str, object] = {
        "cmap": cmap,
        "ax": ax,
        "cbar_kws": {"label": label},
        "linewidths": 0.2,
        "linecolor": "0.85",
    }
    if center is not None:
        kwargs["center"] = center
    if vmin is not None:
        kwargs["vmin"] = vmin
    if vmax is not None:
        kwargs["vmax"] = vmax
    sns.heatmap(matrix, **kwargs)
    ax.set_title(title)
    ax.set_xlabel("Plate column")
    ax.set_ylabel("Plate row")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def keyed_endpoint_for_effects(endpoint: pd.DataFrame, *, exclude_outliers: bool) -> pd.DataFrame:
    keyed = endpoint.loc[
        (endpoint["condition_id"] != UNKEYED_CONDITION_ID)
        & endpoint["is_keyed"].astype(bool)
    ].copy()
    if exclude_outliers:
        keyed = keyed.loc[~keyed["is_endpoint_outlier"].astype(bool)].copy()
    return keyed


def unique_sorted_values(series: pd.Series) -> list[object]:
    values = series.drop_duplicates().tolist()
    return sorted(values, key=sort_token)


def condition_value_mask(series: pd.Series, value: object) -> pd.Series:
    if pd.isna(value):
        return series.isna()
    return series == value


def varying_condition_columns(endpoint: pd.DataFrame, condition_columns: list[str]) -> list[str]:
    return [
        column
        for column in condition_columns
        if len(unique_sorted_values(endpoint[column])) >= 2
    ]


def build_main_effect_summary(
    endpoint: pd.DataFrame,
    *,
    fluorophore: str,
    reagent: str,
) -> pd.DataFrame:
    columns = [
        "fluorophore",
        "reagent",
        "reagent_value",
        "endpoint_mean_rfu",
        "endpoint_sd_rfu",
        "endpoint_n",
        "composition_count",
    ]
    channel = endpoint.loc[endpoint["fluorophore"] == fluorophore]
    values = unique_sorted_values(channel[reagent])
    if len(values) < 2:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for value in values:
        group = channel.loc[condition_value_mask(channel[reagent], value)]
        rows.append(
            {
                "fluorophore": fluorophore,
                "reagent": reagent,
                "reagent_value": value,
                "endpoint_mean_rfu": group["endpoint_rfu"].mean(),
                "endpoint_sd_rfu": group["endpoint_rfu"].std(),
                "endpoint_n": int(group["endpoint_rfu"].count()),
                "composition_count": int(group["condition_id"].nunique()),
            }
        )

    return pd.DataFrame(rows, columns=columns)


def build_main_effect_composition_points(
    endpoint: pd.DataFrame,
    *,
    fluorophore: str,
    reagent: str,
) -> pd.DataFrame:
    channel = endpoint.loc[endpoint["fluorophore"] == fluorophore]
    if channel.empty:
        return pd.DataFrame(columns=["reagent_value", "condition_id", "endpoint_mean_rfu"])
    points = (
        channel.groupby([reagent, "condition_id"], dropna=False, as_index=False)
        .agg(endpoint_mean_rfu=("endpoint_rfu", "mean"))
        .rename(columns={reagent: "reagent_value"})
    )
    points["value_label"] = points["reagent_value"].map(format_condition_value)
    return points


def write_main_effect_plot(
    summary: pd.DataFrame,
    composition_points: pd.DataFrame,
    path: str | Path,
    *,
    fluorophore: str,
    reagent: str,
    variant_label: str,
) -> None:
    summary_sorted = summary.copy()
    summary_sorted["value_label"] = summary_sorted["reagent_value"].map(format_condition_value)
    positions = np.arange(len(summary_sorted))
    position_by_label = dict(zip(summary_sorted["value_label"], positions))

    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    for label, points in composition_points.groupby("value_label", sort=False):
        if label not in position_by_label:
            continue
        base_position = position_by_label[label]
        offsets = np.linspace(-0.12, 0.12, num=len(points)) if len(points) > 1 else np.array([0.0])
        ax.scatter(
            np.full(len(points), base_position) + offsets,
            points["endpoint_mean_rfu"],
            color="0.35",
            alpha=0.35,
            s=28,
            linewidths=0,
            label=None,
        )

    y = summary_sorted["endpoint_mean_rfu"].to_numpy(dtype=float)
    yerr = summary_sorted["endpoint_sd_rfu"].fillna(0).to_numpy(dtype=float)
    ax.errorbar(
        positions,
        y,
        yerr=yerr,
        color="tab:blue",
        marker="o",
        linewidth=2.2,
        capsize=4,
        label="marginal mean +/- SD",
    )
    ax.set_xticks(positions)
    ax.set_xticklabels(summary_sorted["value_label"], rotation=45, ha="right")
    ax.set_title(f"{fluorophore} endpoint RFU by {reagent}\n{variant_label}")
    ax.set_xlabel(reagent)
    ax.set_ylabel("Endpoint RFU")
    ax.legend(frameon=False)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def build_pairwise_interaction_matrices(
    endpoint: pd.DataFrame,
    *,
    fluorophore: str,
    reagent_a: str,
    reagent_b: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    channel = endpoint.loc[endpoint["fluorophore"] == fluorophore]
    a_values = unique_sorted_values(channel[reagent_a])
    b_values = unique_sorted_values(channel[reagent_b])
    if len(a_values) < 2 or len(b_values) < 2:
        return pd.DataFrame(), pd.DataFrame()

    a_labels = [format_condition_value(value) for value in a_values]
    b_labels = [format_condition_value(value) for value in b_values]
    mean_matrix = pd.DataFrame(np.nan, index=b_labels, columns=a_labels)
    count_matrix = pd.DataFrame(np.nan, index=b_labels, columns=a_labels)

    for b_value, b_label in zip(b_values, b_labels):
        b_mask = condition_value_mask(channel[reagent_b], b_value)
        for a_value, a_label in zip(a_values, a_labels):
            group = channel.loc[b_mask & condition_value_mask(channel[reagent_a], a_value)]
            if group.empty:
                continue
            mean_matrix.loc[b_label, a_label] = group["endpoint_rfu"].mean()
            count_matrix.loc[b_label, a_label] = int(group["endpoint_rfu"].count())

    mean_matrix.index.name = reagent_b
    mean_matrix.columns.name = reagent_a
    count_matrix.index.name = reagent_b
    count_matrix.columns.name = reagent_a
    return mean_matrix, count_matrix


def write_pairwise_interaction_heatmap_plot(
    matrix: pd.DataFrame,
    path: str | Path,
    *,
    fluorophore: str,
    reagent_a: str,
    reagent_b: str,
    variant_label: str,
) -> None:
    fig, ax = plt.subplots(figsize=(9, 6), constrained_layout=True)
    sns.heatmap(
        matrix,
        cmap="viridis",
        ax=ax,
        cbar_kws={"label": "Mean endpoint RFU"},
        linewidths=0.2,
        linecolor="0.85",
    )
    ax.invert_yaxis()
    ax.set_title(f"{fluorophore} endpoint RFU: {reagent_a} x {reagent_b}\n{variant_label}")
    ax.set_xlabel(reagent_a)
    ax.set_ylabel(reagent_b)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def faceted_dose_response_assignments(varying_columns: list[str]) -> list[tuple[str, str, str | None]]:
    if len(varying_columns) == 2:
        first, second = varying_columns
        return [(first, second, None), (second, first, None)]
    if len(varying_columns) == 3:
        return [(x_reagent, hue_reagent, col_reagent) for x_reagent, hue_reagent, col_reagent in permutations(varying_columns, 3)]
    return []


def build_faceted_dose_response_summary(
    endpoint: pd.DataFrame,
    *,
    fluorophore: str,
    x_reagent: str,
    hue_reagent: str,
    col_reagent: str | None,
) -> pd.DataFrame:
    columns = [
        "fluorophore",
        "x_reagent",
        "hue_reagent",
        "col_reagent",
        "x_value",
        "hue_value",
        "col_value",
        "endpoint_mean_rfu",
        "endpoint_sd_rfu",
        "endpoint_n",
        "composition_count",
    ]
    channel = endpoint.loc[endpoint["fluorophore"] == fluorophore]
    if channel.empty:
        return pd.DataFrame(columns=columns)

    x_values = unique_sorted_values(channel[x_reagent])
    hue_values = unique_sorted_values(channel[hue_reagent])
    col_values = unique_sorted_values(channel[col_reagent]) if col_reagent is not None else [""]
    rows: list[dict[str, object]] = []
    for col_value in col_values:
        col_group = channel
        if col_reagent is not None:
            col_group = col_group.loc[condition_value_mask(col_group[col_reagent], col_value)]
        for x_value in x_values:
            x_group = col_group.loc[condition_value_mask(col_group[x_reagent], x_value)]
            for hue_value in hue_values:
                group = x_group.loc[condition_value_mask(x_group[hue_reagent], hue_value)]
                if group.empty:
                    continue
                rows.append(
                    {
                        "fluorophore": fluorophore,
                        "x_reagent": x_reagent,
                        "hue_reagent": hue_reagent,
                        "col_reagent": col_reagent or "",
                        "x_value": x_value,
                        "hue_value": hue_value,
                        "col_value": col_value,
                        "endpoint_mean_rfu": group["endpoint_rfu"].mean(),
                        "endpoint_sd_rfu": group["endpoint_rfu"].std(),
                        "endpoint_n": int(group["endpoint_rfu"].count()),
                        "composition_count": int(group["condition_id"].nunique()),
                    }
                )

    return pd.DataFrame(rows, columns=columns)


def build_faceted_dose_response_csv_data(
    endpoint: pd.DataFrame,
    summary: pd.DataFrame,
    *,
    fluorophore: str,
    x_reagent: str,
    hue_reagent: str,
    col_reagent: str | None,
) -> pd.DataFrame:
    columns = [
        "row_type",
        "fluorophore",
        "x_reagent",
        "hue_reagent",
        "col_reagent",
        "x_value",
        "hue_value",
        "col_value",
        "condition_id",
        "well",
        "endpoint_rfu",
        "endpoint_mean_rfu",
        "endpoint_sd_rfu",
        "endpoint_n",
        "composition_count",
    ]
    rows: list[dict[str, object]] = []
    for _, row in summary.iterrows():
        rows.append(
            {
                "row_type": "summary",
                "fluorophore": row["fluorophore"],
                "x_reagent": row["x_reagent"],
                "hue_reagent": row["hue_reagent"],
                "col_reagent": row["col_reagent"],
                "x_value": row["x_value"],
                "hue_value": row["hue_value"],
                "col_value": row["col_value"],
                "condition_id": "",
                "well": "",
                "endpoint_rfu": np.nan,
                "endpoint_mean_rfu": row["endpoint_mean_rfu"],
                "endpoint_sd_rfu": row["endpoint_sd_rfu"],
                "endpoint_n": row["endpoint_n"],
                "composition_count": row["composition_count"],
            }
        )

    channel = endpoint.loc[endpoint["fluorophore"] == fluorophore]
    col_values = unique_sorted_values(channel[col_reagent]) if col_reagent is not None else [""]
    x_values = unique_sorted_values(channel[x_reagent])
    hue_values = unique_sorted_values(channel[hue_reagent])
    for col_value in col_values:
        col_group = channel
        if col_reagent is not None:
            col_group = col_group.loc[condition_value_mask(col_group[col_reagent], col_value)]
        for x_value in x_values:
            x_group = col_group.loc[condition_value_mask(col_group[x_reagent], x_value)]
            for hue_value in hue_values:
                group = x_group.loc[condition_value_mask(x_group[hue_reagent], hue_value)]
                for _, endpoint_row in group.sort_values(["condition_id", "well"], kind="stable").iterrows():
                    rows.append(
                        {
                            "row_type": "replicate",
                            "fluorophore": fluorophore,
                            "x_reagent": x_reagent,
                            "hue_reagent": hue_reagent,
                            "col_reagent": col_reagent or "",
                            "x_value": x_value,
                            "hue_value": hue_value,
                            "col_value": col_value,
                            "condition_id": endpoint_row["condition_id"],
                            "well": endpoint_row["well"],
                            "endpoint_rfu": endpoint_row["endpoint_rfu"],
                            "endpoint_mean_rfu": np.nan,
                            "endpoint_sd_rfu": np.nan,
                            "endpoint_n": np.nan,
                            "composition_count": np.nan,
                        }
                    )

    return pd.DataFrame(rows, columns=columns)


def write_faceted_dose_response_plot(
    summary: pd.DataFrame,
    csv_data: pd.DataFrame,
    path: str | Path,
    *,
    fluorophore: str,
    x_reagent: str,
    hue_reagent: str,
    col_reagent: str | None,
    variant_label: str,
) -> None:
    replicate_points = csv_data.loc[csv_data["row_type"] == "replicate"].copy()
    x_values = unique_sorted_values(summary["x_value"])
    hue_values = unique_sorted_values(summary["hue_value"])
    col_values = unique_sorted_values(summary["col_value"]) if col_reagent is not None else [""]
    x_labels = [format_condition_value(value) for value in x_values]
    hue_labels = [format_condition_value(value) for value in hue_values]
    x_position_by_label = dict(zip(x_labels, np.arange(len(x_labels))))
    hue_offsets = np.linspace(-0.16, 0.16, len(hue_labels)) if len(hue_labels) > 1 else np.array([0.0])
    hue_offset_by_label = dict(zip(hue_labels, hue_offsets))
    palette = sns.color_palette("husl", n_colors=max(len(hue_labels), 1))
    color_by_hue = dict(zip(hue_labels, palette))

    fig_width = max(8.0, 4.8 * len(col_values))
    fig, axes = plt.subplots(
        1,
        len(col_values),
        figsize=(fig_width, 5.5),
        sharey=True,
        constrained_layout=True,
    )
    if len(col_values) == 1:
        axes = np.array([axes])

    for ax, col_value in zip(axes, col_values):
        facet_summary = summary
        facet_points = replicate_points
        if col_reagent is not None:
            facet_summary = facet_summary.loc[condition_value_mask(facet_summary["col_value"], col_value)]
            facet_points = facet_points.loc[condition_value_mask(facet_points["col_value"], col_value)]

        for hue_value, hue_label in zip(hue_values, hue_labels):
            color = color_by_hue[hue_label]
            hue_summary = facet_summary.loc[condition_value_mask(facet_summary["hue_value"], hue_value)]
            x_positions: list[float] = []
            means: list[float] = []
            errors: list[float] = []
            for x_value in x_values:
                group = hue_summary.loc[condition_value_mask(hue_summary["x_value"], x_value)]
                if group.empty:
                    continue
                x_label = format_condition_value(x_value)
                x_positions.append(float(x_position_by_label[x_label]) + float(hue_offset_by_label[hue_label]))
                means.append(float(group["endpoint_mean_rfu"].iloc[0]))
                sd_value = group["endpoint_sd_rfu"].iloc[0]
                errors.append(0.0 if pd.isna(sd_value) else float(sd_value))

                point_group = facet_points.loc[
                    condition_value_mask(facet_points["x_value"], x_value)
                    & condition_value_mask(facet_points["hue_value"], hue_value)
                ]
                if not point_group.empty:
                    jitter = (
                        np.linspace(-0.035, 0.035, len(point_group))
                        if len(point_group) > 1
                        else np.array([0.0])
                    )
                    ax.scatter(
                        np.full(len(point_group), x_position_by_label[x_label] + hue_offset_by_label[hue_label]) + jitter,
                        point_group["endpoint_rfu"].to_numpy(dtype=float),
                        color=color,
                        alpha=0.25,
                        s=20,
                        linewidths=0,
                        zorder=1,
                    )

            if x_positions:
                ax.errorbar(
                    x_positions,
                    means,
                    yerr=errors,
                    color=color,
                    marker="o",
                    linewidth=2.1,
                    capsize=3,
                    label=f"{hue_reagent}={hue_label}",
                    zorder=3,
                )

        ax.set_xticks(np.arange(len(x_labels)))
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_xlabel(x_reagent)
        ax.grid(axis="y", color="0.9", linewidth=0.7)
        if col_reagent is not None:
            ax.set_title(f"{col_reagent}={format_condition_value(col_value)}")

    axes[0].set_ylabel("Endpoint RFU")
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        axes[0].legend(handles, labels, frameon=False, title=hue_reagent)
    col_part = f", column={col_reagent}" if col_reagent is not None else ""
    fig.suptitle(
        f"{fluorophore} endpoint dose-response ({variant_label})\n"
        f"x={x_reagent}, hue={hue_reagent}{col_part}"
    )
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_endpoint_effect_outputs(
    endpoint: pd.DataFrame,
    condition_columns: list[str],
    output_root: Path,
) -> tuple[list[Path], list[Path], list[Path], list[Path], list[Path], list[Path]]:
    effects_root = output_root / "endpoint_effects"
    main_root = effects_root / "main_effects"
    pairwise_root = effects_root / "pairwise_interactions"
    dose_root = effects_root / "faceted_dose_response"
    main_csvs: list[Path] = []
    main_pngs: list[Path] = []
    pairwise_csvs: list[Path] = []
    pairwise_pngs: list[Path] = []
    dose_csvs: list[Path] = []
    dose_pngs: list[Path] = []

    for variant_name, variant_label in ENDPOINT_EFFECT_VARIANTS:
        variant_endpoint = keyed_endpoint_for_effects(
            endpoint,
            exclude_outliers=variant_name == "excluding_outliers",
        )
        main_dir = main_root / variant_name
        pairwise_dir = pairwise_root / variant_name
        dose_dir = dose_root / variant_name
        main_dir.mkdir(parents=True, exist_ok=True)
        pairwise_dir.mkdir(parents=True, exist_ok=True)
        dose_dir.mkdir(parents=True, exist_ok=True)
        if variant_endpoint.empty or not condition_columns:
            continue

        fluorophores = sorted(variant_endpoint["fluorophore"].dropna().astype(str).unique())
        for fluorophore in fluorophores:
            channel = variant_endpoint.loc[variant_endpoint["fluorophore"] == fluorophore]
            safe_fluorophore = safe_filename(fluorophore)

            for reagent in condition_columns:
                if len(unique_sorted_values(channel[reagent])) < 2:
                    continue
                safe_reagent = safe_filename(reagent)
                main_summary = build_main_effect_summary(
                    variant_endpoint,
                    fluorophore=fluorophore,
                    reagent=reagent,
                )
                composition_points = build_main_effect_composition_points(
                    variant_endpoint,
                    fluorophore=fluorophore,
                    reagent=reagent,
                )
                main_csv = main_dir / f"{safe_fluorophore}_{safe_reagent}_main_effect.csv"
                main_png = main_dir / f"{safe_fluorophore}_{safe_reagent}_main_effect.png"
                main_summary.to_csv(main_csv, index=False)
                write_main_effect_plot(
                    main_summary,
                    composition_points,
                    main_png,
                    fluorophore=fluorophore,
                    reagent=reagent,
                    variant_label=variant_label,
                )
                main_csvs.append(main_csv)
                main_pngs.append(main_png)

            for reagent_a, reagent_b in combinations(condition_columns, 2):
                if (
                    len(unique_sorted_values(channel[reagent_a])) < 2
                    or len(unique_sorted_values(channel[reagent_b])) < 2
                ):
                    continue
                mean_matrix, count_matrix = build_pairwise_interaction_matrices(
                    variant_endpoint,
                    fluorophore=fluorophore,
                    reagent_a=reagent_a,
                    reagent_b=reagent_b,
                )
                if mean_matrix.empty or mean_matrix.isna().all().all():
                    continue
                safe_reagent_a = safe_filename(reagent_a)
                safe_reagent_b = safe_filename(reagent_b)
                prefix = f"{safe_fluorophore}_{safe_reagent_a}_x_{safe_reagent_b}"
                mean_csv = pairwise_dir / f"{prefix}_mean_endpoint_rfu.csv"
                count_csv = pairwise_dir / f"{prefix}_endpoint_n.csv"
                heatmap_png = pairwise_dir / f"{prefix}_mean_endpoint_rfu.png"
                mean_matrix.to_csv(mean_csv)
                count_matrix.to_csv(count_csv)
                write_pairwise_interaction_heatmap_plot(
                    mean_matrix,
                    heatmap_png,
                    fluorophore=fluorophore,
                    reagent_a=reagent_a,
                    reagent_b=reagent_b,
                    variant_label=variant_label,
                )
                pairwise_csvs.extend([mean_csv, count_csv])
                pairwise_pngs.append(heatmap_png)

            varying_columns = varying_condition_columns(channel, condition_columns)
            for x_reagent, hue_reagent, col_reagent in faceted_dose_response_assignments(varying_columns):
                dose_summary = build_faceted_dose_response_summary(
                    variant_endpoint,
                    fluorophore=fluorophore,
                    x_reagent=x_reagent,
                    hue_reagent=hue_reagent,
                    col_reagent=col_reagent,
                )
                if dose_summary.empty:
                    continue
                dose_csv_data = build_faceted_dose_response_csv_data(
                    variant_endpoint,
                    dose_summary,
                    fluorophore=fluorophore,
                    x_reagent=x_reagent,
                    hue_reagent=hue_reagent,
                    col_reagent=col_reagent,
                )
                safe_x = safe_filename(x_reagent)
                safe_hue = safe_filename(hue_reagent)
                stem = f"{safe_fluorophore}_x_{safe_x}_hue_{safe_hue}"
                if col_reagent is not None:
                    stem = f"{stem}_col_{safe_filename(col_reagent)}"
                stem = f"{stem}_endpoint_dose_response"
                dose_csv = dose_dir / f"{stem}.csv"
                dose_png = dose_dir / f"{stem}.png"
                dose_csv_data.to_csv(dose_csv, index=False)
                write_faceted_dose_response_plot(
                    dose_summary,
                    dose_csv_data,
                    dose_png,
                    fluorophore=fluorophore,
                    x_reagent=x_reagent,
                    hue_reagent=hue_reagent,
                    col_reagent=col_reagent,
                    variant_label=variant_label,
                )
                dose_csvs.append(dose_csv)
                dose_pngs.append(dose_png)

    return main_csvs, main_pngs, pairwise_csvs, pairwise_pngs, dose_csvs, dose_pngs


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
    outlier_dir = output_root / "heatmaps_endpoint_outliers"
    timecourse_dir = output_root / "timecourses"
    combined_timecourse_dir = output_root / "timecourses_combined"
    absolute_dir.mkdir(parents=True, exist_ok=True)
    percent_dir.mkdir(parents=True, exist_ok=True)
    outlier_dir.mkdir(parents=True, exist_ok=True)
    timecourse_dir.mkdir(parents=True, exist_ok=True)
    combined_timecourse_dir.mkdir(parents=True, exist_ok=True)

    merged = load_merged_tidy(merged_csv)
    prepared, condition_columns = prepare_analysis_dataframe(merged)
    endpoint = compute_endpoint_by_well(
        prepared,
        condition_columns,
        endpoint_last_n=endpoint_last_n,
    )
    summary = summarize_compositions(endpoint, condition_columns)
    timecourse_summary = summarize_condition_timecourses(prepared, condition_columns)
    endpoint_flags = endpoint[["well", "fluorophore", "is_endpoint_outlier"]]
    keyed_prepared = prepared.loc[prepared["condition_id"] != UNKEYED_CONDITION_ID].merge(
        endpoint_flags,
        on=["well", "fluorophore"],
        how="left",
    )
    keyed_prepared["is_endpoint_outlier"] = keyed_prepared["is_endpoint_outlier"].fillna(False)
    timecourse_summary_excluding_outliers = summarize_condition_timecourses(
        keyed_prepared.loc[~keyed_prepared["is_endpoint_outlier"].astype(bool)],
        condition_columns,
    )
    should_write_timecourse_plots = has_timecourse_data(prepared)
    if should_write_timecourse_plots:
        faceted_timecourse_csvs, faceted_timecourse_pngs = write_faceted_timecourse_grid_outputs(
            keyed_prepared,
            condition_columns,
            output_root,
        )
    else:
        faceted_timecourse_csvs = []
        faceted_timecourse_pngs = []

    endpoint_csv = output_root / "endpoint_by_well.csv"
    composition_summary_csv = output_root / "composition_summary.csv"
    timecourse_summary_csv = output_root / "timecourse_summary.csv"
    timecourse_excluding_outliers_summary_csv = output_root / "timecourse_summary_excluding_outliers.csv"
    outlier_summary_csv = output_root / "outlier_summary.csv"
    endpoint.to_csv(endpoint_csv, index=False)
    summary.to_csv(composition_summary_csv, index=False)
    timecourse_summary.to_csv(timecourse_summary_csv, index=False)
    timecourse_summary_excluding_outliers.to_csv(timecourse_excluding_outliers_summary_csv, index=False)
    endpoint.loc[endpoint["is_endpoint_outlier"].astype(bool)].to_csv(outlier_summary_csv, index=False)
    (
        main_effect_csvs,
        main_effect_pngs,
        pairwise_csvs,
        pairwise_pngs,
        dose_csvs,
        dose_pngs,
    ) = write_endpoint_effect_outputs(
        endpoint,
        condition_columns,
        output_root,
    )

    absolute_csvs: list[Path] = []
    absolute_pngs: list[Path] = []
    percent_csvs: list[Path] = []
    percent_pngs: list[Path] = []
    outlier_csvs: list[Path] = []
    outlier_pngs: list[Path] = []
    timecourse_pngs: list[Path] = []
    combined_timecourse_pngs: list[Path] = []
    if should_write_timecourse_plots:
        for (condition_id, fluorophore), plot_summary in timecourse_summary.groupby(["condition_id", "fluorophore"]):
            plot_replicates = keyed_prepared.loc[
                (keyed_prepared["condition_id"] == condition_id)
                & (keyed_prepared["fluorophore"] == fluorophore)
            ]
            if plot_replicates.empty:
                continue

            safe_fluorophore = safe_filename(fluorophore)
            timecourse_png = timecourse_dir / f"{condition_id}_{safe_fluorophore}_timecourse.png"
            condition_label = str(plot_summary["condition_label"].iloc[0])
            write_condition_timecourse_plot(
                plot_replicates,
                plot_summary,
                timecourse_png,
                condition_id=str(condition_id),
                fluorophore=str(fluorophore),
                condition_label=condition_label,
            )
            timecourse_pngs.append(timecourse_png)

        for fluorophore in sorted(timecourse_summary["fluorophore"].dropna().astype(str).unique()):
            inclusive_summary = timecourse_summary.loc[timecourse_summary["fluorophore"] == fluorophore]
            excluded_summary = timecourse_summary_excluding_outliers.loc[
                timecourse_summary_excluding_outliers["fluorophore"] == fluorophore
            ]
            condition_ids = sorted(inclusive_summary["condition_id"].dropna().astype(str).unique())
            color_by_condition = build_condition_color_map(condition_ids)
            safe_name = safe_filename(fluorophore)

            including_png = combined_timecourse_dir / f"{safe_name}_all_conditions_including_outliers.png"
            write_combined_condition_timecourse_plot(
                inclusive_summary,
                including_png,
                fluorophore=fluorophore,
                title_suffix="All keyed compositions including endpoint outliers",
                color_by_condition=color_by_condition,
            )
            combined_timecourse_pngs.append(including_png)

            excluding_png = combined_timecourse_dir / f"{safe_name}_all_conditions_excluding_outliers.png"
            write_combined_condition_timecourse_plot(
                excluded_summary,
                excluding_png,
                fluorophore=fluorophore,
                title_suffix="All keyed compositions excluding endpoint outliers",
                color_by_condition=color_by_condition,
            )
            combined_timecourse_pngs.append(excluding_png)

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

        outlier_matrix = build_outlier_heatmap(endpoint, fluorophore)
        outlier_csv = outlier_dir / f"{safe_name}_endpoint_outlier_count.csv"
        outlier_png = outlier_dir / f"{safe_name}_endpoint_outlier_count.png"
        outlier_matrix.to_csv(outlier_csv)
        write_plate_heatmap_plot(
            outlier_matrix,
            outlier_png,
            title=f"{fluorophore} endpoint outliers",
            label="Endpoint outlier count",
            cmap="Reds",
            vmin=0.0,
            vmax=1.0,
        )
        outlier_csvs.append(outlier_csv)
        outlier_pngs.append(outlier_png)

    return AnalysisResult(
        output_dir=output_root,
        endpoint_csv=endpoint_csv,
        composition_summary_csv=composition_summary_csv,
        timecourse_summary_csv=timecourse_summary_csv,
        timecourse_excluding_outliers_summary_csv=timecourse_excluding_outliers_summary_csv,
        outlier_summary_csv=outlier_summary_csv,
        absolute_heatmap_csvs=absolute_csvs,
        absolute_heatmap_pngs=absolute_pngs,
        percent_difference_heatmap_csvs=percent_csvs,
        percent_difference_heatmap_pngs=percent_pngs,
        outlier_heatmap_csvs=outlier_csvs,
        outlier_heatmap_pngs=outlier_pngs,
        timecourse_plot_pngs=timecourse_pngs,
        combined_timecourse_plot_pngs=combined_timecourse_pngs,
        main_effect_csvs=main_effect_csvs,
        main_effect_pngs=main_effect_pngs,
        pairwise_interaction_csvs=pairwise_csvs,
        pairwise_interaction_pngs=pairwise_pngs,
        faceted_dose_response_csvs=dose_csvs,
        faceted_dose_response_pngs=dose_pngs,
        faceted_timecourse_csvs=faceted_timecourse_csvs,
        faceted_timecourse_pngs=faceted_timecourse_pngs,
        outlier_count=int(endpoint["is_endpoint_outlier"].sum()),
        condition_columns=condition_columns,
        endpoint_rows=len(endpoint),
        composition_rows=len(summary),
    )


def safe_filename(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    text = text.strip("._")
    return text or "channel"
