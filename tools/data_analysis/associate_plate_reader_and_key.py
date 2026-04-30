#!/usr/bin/env python3
"""
Parse a LabCraft plate-reader export and merge it with an experiment concentration key.

Primary workflow:
    python tools/data_analysis/associate_plate_reader_and_key.py <experiment_dir>

The experiment directory must contain:
- concentration_key.csv
- one plate-reader export matching *_data.xls

The plate-reader export may have an .xls extension, but is expected to be a
UTF-16, tab-delimited text export.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


WELL_RE = re.compile(r"^[A-P](?:[1-9]|1[0-9]|2[0-4])$")
EX_EM_RE = re.compile(r"^(\d+)\s+(\d+)$")
TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
DEFAULT_KEY_FILENAME = "concentration_key.csv"
DEFAULT_PLATE_PATTERN = "*_data.xls"


@dataclass(frozen=True)
class ResolvedInputs:
    experiment_dir: Path
    plate_file: Path
    key_file: Path
    output_file: Path


@dataclass(frozen=True)
class TimepointFilterResult:
    dataframe: pd.DataFrame
    dropped_timepoints: list[dict[str, int | str]]
    active_wells: list[str]


@dataclass(frozen=True)
class MergeSummary:
    keyed_wells: list[str]
    unkeyed_measured_wells: list[str]
    missing_key_wells: list[str]


def extract_channel_labels(metadata_row: list[str]) -> list[str]:
    """Extract unique Ex/Em labels from the metadata row and format as 502_540."""
    labels: list[str] = []
    seen: set[str] = set()

    for raw in metadata_row:
        text = str(raw).strip()
        match = EX_EM_RE.match(text)
        if not match:
            continue
        label = f"{match.group(1)}_{match.group(2)}"
        if label not in seen:
            seen.add(label)
            labels.append(label)

    if not labels:
        raise ValueError("Could not find any excitation/emission labels in the metadata row.")

    return labels


def read_plate_rows(path: str | Path) -> list[list[str]]:
    with open(path, "r", encoding="utf-16", newline="") as handle:
        return list(csv.reader(handle, delimiter="\t"))


def split_into_blocks(data_rows: list[list[str]]) -> list[list[list[str]]]:
    """
    Split the body of the plate-reader export into contiguous data blocks.

    Blank rows separate blocks. As a safety net, a new block also starts if
    time resets to 00:00:00 after data have already been collected.
    """
    blocks: list[list[list[str]]] = []
    current: list[list[str]] = []
    seen_any_time = False

    for row in data_rows:
        if not row or all(str(cell).strip() == "" for cell in row):
            if current:
                blocks.append(current)
                current = []
                seen_any_time = False
            continue

        time_value = str(row[0]).strip()
        if not TIME_RE.match(time_value):
            continue
        if seen_any_time and time_value == "00:00:00" and current:
            blocks.append(current)
            current = []
            seen_any_time = False

        current.append(row)
        if time_value:
            seen_any_time = True

    if current:
        blocks.append(current)

    return blocks


def parse_fluorophore_label(label: str) -> tuple[int | None, int | None]:
    match = re.match(r"^(\d+)_(\d+)$", str(label).strip())
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def parse_plate_reader(path: str | Path) -> pd.DataFrame:
    rows = read_plate_rows(path)
    if len(rows) < 4:
        raise ValueError("Plate-reader file is too short to parse.")

    metadata_row = rows[1]
    header_row = rows[2]
    channel_labels = extract_channel_labels(metadata_row)

    if len(header_row) < 3 or str(header_row[0]).strip() != "Time":
        raise ValueError("Unexpected plate-reader header row; expected 'Time' in the first column.")

    column_names = [str(c).strip() for c in header_row]
    well_columns = [c for c in column_names[2:] if WELL_RE.match(c)]
    if not well_columns:
        raise ValueError("No well columns were detected in the plate-reader header.")

    column_indices_by_name = {name: idx for idx, name in enumerate(column_names)}
    well_column_indices = [column_indices_by_name[well] for well in well_columns]

    blocks = split_into_blocks(rows[3:])
    if len(blocks) != len(channel_labels):
        raise ValueError(
            f"Found {len(blocks)} data blocks but {len(channel_labels)} channel labels. "
            "Please verify the plate-reader export structure."
        )

    tidy_records: list[dict[str, object]] = []
    for block_idx, block in enumerate(blocks):
        fluorophore = channel_labels[block_idx]
        excitation_nm, emission_nm = parse_fluorophore_label(fluorophore)

        for row in block:
            time_str = str(row[0]).strip()
            temp_str = str(row[1]).strip() if len(row) > 1 else ""
            for well, col_idx in zip(well_columns, well_column_indices):
                value = row[col_idx].strip() if col_idx < len(row) else ""
                if value == "":
                    continue
                tidy_records.append(
                    {
                        "time": time_str,
                        "temperature_c": temp_str,
                        "well": well,
                        "fluorophore": fluorophore,
                        "excitation_nm": excitation_nm,
                        "emission_nm": emission_nm,
                        "rfu": value,
                    }
                )

    plate_df = pd.DataFrame(tidy_records)
    if plate_df.empty:
        raise ValueError("No fluorescence values were parsed from the plate-reader file.")

    plate_df["temperature_c"] = pd.to_numeric(plate_df["temperature_c"], errors="coerce")
    plate_df["rfu"] = pd.to_numeric(plate_df["rfu"], errors="coerce")
    plate_df["time_seconds"] = pd.to_timedelta(plate_df["time"], errors="coerce").dt.total_seconds()
    plate_df["time_minutes"] = plate_df["time_seconds"] / 60.0

    return sort_tidy_rows(plate_df)


def sort_tidy_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["well", "fluorophore", "time_seconds"], kind="stable").reset_index(drop=True)


def is_diluent_column(column_name: str) -> bool:
    return any(part.strip() == "--" for part in str(column_name).split("_"))


def parse_key_csv(path: str | Path) -> pd.DataFrame:
    key_df = pd.read_csv(path)
    if "Well ID" not in key_df.columns:
        raise ValueError("Key CSV must contain a 'Well ID' column.")

    selected_columns = ["Well ID"] + [
        column for column in key_df.columns if column != "Well ID" and not is_diluent_column(column)
    ]
    parsed = key_df[selected_columns].copy()
    parsed = parsed.rename(columns={"Well ID": "well"})
    parsed["well"] = parsed["well"].astype(str).str.strip()
    parsed = parsed[parsed["well"] != ""]

    if parsed["well"].duplicated().any():
        duplicates = sorted(parsed.loc[parsed["well"].duplicated(), "well"].unique())
        raise ValueError(f"Key CSV contains duplicate Well ID values: {', '.join(duplicates)}")

    return parsed


def filter_complete_timepoints(plate_df: pd.DataFrame) -> TimepointFilterResult:
    active_wells = sorted(plate_df["well"].dropna().astype(str).unique())
    fluorophores = sorted(plate_df["fluorophore"].dropna().astype(str).unique())
    expected_count = len(active_wells) * len(fluorophores)

    if not active_wells or not fluorophores or expected_count == 0:
        return TimepointFilterResult(plate_df.copy(), [], active_wells)

    observed_counts = (
        plate_df[["time", "well", "fluorophore"]]
        .drop_duplicates()
        .groupby("time")
        .size()
    )

    dropped: list[dict[str, int | str]] = []
    complete_times: set[str] = set()
    for time_value, observed_count in observed_counts.items():
        observed_int = int(observed_count)
        if observed_int == expected_count:
            complete_times.add(str(time_value))
        else:
            dropped.append(
                {
                    "time": str(time_value),
                    "observed_count": observed_int,
                    "expected_count": expected_count,
                    "missing_count": expected_count - observed_int,
                }
            )

    filtered = plate_df[plate_df["time"].astype(str).isin(complete_times)].copy()
    if filtered.empty:
        raise ValueError("All plate-reader timepoints were incomplete; no rows remain after filtering.")

    return TimepointFilterResult(sort_tidy_rows(filtered), dropped, active_wells)


def merge_plate_and_key(plate_df: pd.DataFrame, key_df: pd.DataFrame) -> tuple[pd.DataFrame, MergeSummary]:
    data_wells = set(plate_df["well"].dropna().astype(str))
    key_wells = set(key_df["well"].dropna().astype(str))

    merged = plate_df.merge(key_df, on="well", how="left", validate="many_to_one")
    merged["is_keyed"] = merged["well"].astype(str).isin(key_wells)

    base_columns = [
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
    ]
    concentration_columns = [column for column in key_df.columns if column != "well"]
    merged = merged[base_columns + concentration_columns]
    merged = sort_tidy_rows(merged)

    summary = MergeSummary(
        keyed_wells=sorted(data_wells & key_wells),
        unkeyed_measured_wells=sorted(data_wells - key_wells),
        missing_key_wells=sorted(key_wells - data_wells),
    )
    return merged, summary


def discover_plate_file(experiment_dir: Path) -> Path:
    candidates = sorted(
        path
        for path in experiment_dir.iterdir()
        if path.is_file() and path.name.lower().endswith("_data.xls")
    )
    if not candidates:
        raise ValueError(
            f"No plate-reader data file matching {DEFAULT_PLATE_PATTERN!r} was found in {experiment_dir}."
        )
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise ValueError(
            "Multiple plate-reader data files were found. "
            f"Pass --plate-file to choose one. Candidates: {names}"
        )
    return candidates[0]


def resolve_optional_path(path: str | Path | None, experiment_dir: Path | None = None) -> Path | None:
    if path is None:
        return None
    resolved = Path(path)
    if resolved.exists() or resolved.is_absolute() or experiment_dir is None:
        return resolved
    experiment_relative = experiment_dir / resolved
    if experiment_relative.exists():
        return experiment_relative
    return resolved


def resolve_inputs(args: argparse.Namespace) -> ResolvedInputs:
    first_positional = Path(args.experiment_dir) if args.experiment_dir else None
    legacy_key_file = Path(args.legacy_key_file) if args.legacy_key_file else None

    if legacy_key_file is not None:
        if args.plate_file is not None or args.key_file is not None:
            raise ValueError("Do not combine legacy positional plate/key files with --plate-file or --key-file.")
        if first_positional is None:
            raise ValueError("Legacy mode requires both plate_file and key_file positional arguments.")
        plate_file = first_positional
        key_file = legacy_key_file
        experiment_dir = plate_file.resolve().parent
    else:
        experiment_dir = first_positional
        plate_file = resolve_optional_path(args.plate_file, experiment_dir)
        key_file = resolve_optional_path(args.key_file, experiment_dir)

        if experiment_dir is None:
            if plate_file is None or key_file is None:
                raise ValueError("Provide an experiment directory, or both --plate-file and --key-file.")
            experiment_dir = plate_file.resolve().parent
        else:
            if not experiment_dir.exists() or not experiment_dir.is_dir():
                raise ValueError(f"Experiment directory does not exist or is not a directory: {experiment_dir}")

        if key_file is None:
            key_file = experiment_dir / DEFAULT_KEY_FILENAME
        if plate_file is None:
            plate_file = discover_plate_file(experiment_dir)

    if not plate_file.exists() or not plate_file.is_file():
        raise ValueError(f"Plate-reader file does not exist or is not a file: {plate_file}")
    if not key_file.exists() or not key_file.is_file():
        raise ValueError(f"Key CSV does not exist or is not a file: {key_file}")

    output_file = Path(args.output) if args.output else experiment_dir / f"{plate_file.stem}_merged_tidy.csv"
    return ResolvedInputs(
        experiment_dir=experiment_dir,
        plate_file=plate_file,
        key_file=key_file,
        output_file=output_file,
    )


def build_merged_tidy_data(
    plate_file: str | Path,
    key_file: str | Path,
) -> tuple[pd.DataFrame, TimepointFilterResult, MergeSummary]:
    plate_df = parse_plate_reader(plate_file)
    filter_result = filter_complete_timepoints(plate_df)
    key_df = parse_key_csv(key_file)
    merged_df, merge_summary = merge_plate_and_key(filter_result.dataframe, key_df)
    return merged_df, filter_result, merge_summary


def default_output_path(plate_path: str | Path) -> Path:
    p = Path(plate_path)
    return p.with_name(f"{p.stem}_merged_tidy.csv")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge a plate-reader export with an experiment concentration_key.csv."
    )
    parser.add_argument(
        "experiment_dir",
        nargs="?",
        help=(
            "Experiment directory. Legacy mode also accepts plate_file here when a second "
            "positional key_file is supplied."
        ),
    )
    parser.add_argument(
        "legacy_key_file",
        nargs="?",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--plate-file",
        type=Path,
        default=None,
        help="Optional plate-reader export override. Defaults to the only *_data.xls file in the experiment dir.",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=None,
        help="Optional concentration key override. Defaults to concentration_key.csv in the experiment dir.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Path for the merged tidy CSV output. Defaults to <plate stem>_merged_tidy.csv.",
    )
    return parser


def _format_list(values: Iterable[str], *, limit: int = 24) -> str:
    items = list(values)
    if len(items) <= limit:
        return ", ".join(items)
    return ", ".join(items[:limit]) + f", ... ({len(items) - limit} more)"


def print_summary(
    inputs: ResolvedInputs,
    merged_df: pd.DataFrame,
    filter_result: TimepointFilterResult,
    merge_summary: MergeSummary,
) -> None:
    print(f"Experiment directory: {inputs.experiment_dir}")
    print(f"Plate-reader file: {inputs.plate_file}")
    print(f"Concentration key: {inputs.key_file}")
    print(f"Saved merged tidy data to: {inputs.output_file}")
    print(f"Rows written: {len(merged_df):,}")
    print(f"Active measured wells: {len(filter_result.active_wells)}")
    print(f"Keyed measured wells: {len(merge_summary.keyed_wells)}")
    print(f"Unkeyed measured wells: {len(merge_summary.unkeyed_measured_wells)}")
    print(f"Key wells missing from plate data: {len(merge_summary.missing_key_wells)}")
    print(f"Fluorophores found: {', '.join(sorted(merged_df['fluorophore'].dropna().unique()))}")

    if filter_result.dropped_timepoints:
        print("WARNING: Dropped incomplete timepoints:")
        for item in filter_result.dropped_timepoints:
            print(
                "  "
                f"{item['time']}: missing {item['missing_count']} of "
                f"{item['expected_count']} expected well/channel observations"
            )
    else:
        print("No incomplete timepoints were dropped.")

    if merge_summary.unkeyed_measured_wells:
        print("WARNING: Unkeyed measured wells are retained with is_keyed=False:")
        print(_format_list(merge_summary.unkeyed_measured_wells))

    if merge_summary.missing_key_wells:
        print("WARNING: The following key wells were not found in the plate data:")
        print(_format_list(merge_summary.missing_key_wells))


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        inputs = resolve_inputs(args)
        merged_df, filter_result, merge_summary = build_merged_tidy_data(
            inputs.plate_file,
            inputs.key_file,
        )
    except Exception as exc:  # pragma: no cover - CLI reporting
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    merged_df.to_csv(inputs.output_file, index=False)
    print_summary(inputs, merged_df, filter_result, merge_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
