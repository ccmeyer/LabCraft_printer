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
OUTLIER_ROBUST_Z_THRESHOLD = 3.5
OUTLIER_MIN_RELATIVE_DELTA_PERCENT = 15.0
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
    outlier_summary_csv: Path
    absolute_heatmap_csvs: list[Path]
    absolute_heatmap_pngs: list[Path]
    percent_difference_heatmap_csvs: list[Path]
    percent_difference_heatmap_pngs: list[Path]
    outlier_heatmap_csvs: list[Path]
    outlier_heatmap_pngs: list[Path]
    timecourse_plot_pngs: list[Path]
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
    absolute_dir.mkdir(parents=True, exist_ok=True)
    percent_dir.mkdir(parents=True, exist_ok=True)
    outlier_dir.mkdir(parents=True, exist_ok=True)
    timecourse_dir.mkdir(parents=True, exist_ok=True)

    merged = load_merged_tidy(merged_csv)
    prepared, condition_columns = prepare_analysis_dataframe(merged)
    endpoint = compute_endpoint_by_well(
        prepared,
        condition_columns,
        endpoint_last_n=endpoint_last_n,
    )
    summary = summarize_compositions(endpoint, condition_columns)
    timecourse_summary = summarize_condition_timecourses(prepared, condition_columns)

    endpoint_csv = output_root / "endpoint_by_well.csv"
    composition_summary_csv = output_root / "composition_summary.csv"
    timecourse_summary_csv = output_root / "timecourse_summary.csv"
    outlier_summary_csv = output_root / "outlier_summary.csv"
    endpoint.to_csv(endpoint_csv, index=False)
    summary.to_csv(composition_summary_csv, index=False)
    timecourse_summary.to_csv(timecourse_summary_csv, index=False)
    endpoint.loc[endpoint["is_endpoint_outlier"].astype(bool)].to_csv(outlier_summary_csv, index=False)

    absolute_csvs: list[Path] = []
    absolute_pngs: list[Path] = []
    percent_csvs: list[Path] = []
    percent_pngs: list[Path] = []
    outlier_csvs: list[Path] = []
    outlier_pngs: list[Path] = []
    timecourse_pngs: list[Path] = []
    endpoint_flags = endpoint[["well", "fluorophore", "is_endpoint_outlier"]]
    keyed_prepared = prepared.loc[prepared["condition_id"] != UNKEYED_CONDITION_ID].merge(
        endpoint_flags,
        on=["well", "fluorophore"],
        how="left",
    )
    keyed_prepared["is_endpoint_outlier"] = keyed_prepared["is_endpoint_outlier"].fillna(False)
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
        outlier_summary_csv=outlier_summary_csv,
        absolute_heatmap_csvs=absolute_csvs,
        absolute_heatmap_pngs=absolute_pngs,
        percent_difference_heatmap_csvs=percent_csvs,
        percent_difference_heatmap_pngs=percent_pngs,
        outlier_heatmap_csvs=outlier_csvs,
        outlier_heatmap_pngs=outlier_pngs,
        timecourse_plot_pngs=timecourse_pngs,
        outlier_count=int(endpoint["is_endpoint_outlier"].sum()),
        condition_columns=condition_columns,
        endpoint_rows=len(endpoint),
        composition_rows=len(summary),
    )


def safe_filename(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    text = text.strip("._")
    return text or "channel"
