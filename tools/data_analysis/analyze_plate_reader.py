#!/usr/bin/env python3
"""Generate endpoint statistics and plate heatmaps from merged plate-reader data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.data_analysis import associate_plate_reader_and_key as assoc  # noqa: E402
from tools.data_analysis import plate_reader_analysis as analysis  # noqa: E402


DEFAULT_MERGED_PATTERN = "*_merged_tidy.csv"


def discover_merged_tidy_csv(experiment_dir: Path) -> Path | None:
    candidates = sorted(
        path
        for path in experiment_dir.iterdir()
        if path.is_file() and path.name.lower().endswith("_merged_tidy.csv")
    )
    if not candidates:
        return None
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise ValueError(
            "Multiple merged tidy CSV files were found. "
            f"Pass --merged-csv to choose one. Candidates: {names}"
        )
    return candidates[0]


def build_merged_tidy_csv(experiment_dir: Path) -> Path:
    args = argparse.Namespace(
        experiment_dir=str(experiment_dir),
        legacy_key_file=None,
        plate_file=None,
        key_file=None,
        output=None,
    )
    inputs = assoc.resolve_inputs(args)
    merged_df, _filter_result, _merge_summary = assoc.build_merged_tidy_data(
        inputs.plate_file,
        inputs.key_file,
    )
    merged_df.to_csv(inputs.output_file, index=False)
    return inputs.output_file


def resolve_merged_tidy_csv(args: argparse.Namespace) -> tuple[Path, Path | None]:
    if args.experiment_dir is not None and args.merged_csv is not None:
        raise ValueError("Provide either an experiment directory or --merged-csv, not both.")
    if args.experiment_dir is None and args.merged_csv is None:
        raise ValueError("Provide an experiment directory or --merged-csv.")
    if args.refresh_merged and args.merged_csv is not None:
        raise ValueError("--refresh-merged is only valid with an experiment directory.")

    if args.merged_csv is not None:
        merged_csv = Path(args.merged_csv)
        if not merged_csv.exists() or not merged_csv.is_file():
            raise ValueError(f"Merged tidy CSV does not exist or is not a file: {merged_csv}")
        return merged_csv, None

    experiment_dir = assoc.resolve_experiment_dir(args.experiment_dir)
    if args.refresh_merged:
        return build_merged_tidy_csv(experiment_dir), experiment_dir

    merged_csv = discover_merged_tidy_csv(experiment_dir)
    if merged_csv is not None:
        return merged_csv, experiment_dir

    return build_merged_tidy_csv(experiment_dir), experiment_dir


def default_output_dir(merged_csv: Path, experiment_dir: Path | None) -> Path:
    if experiment_dir is not None:
        return experiment_dir / "plate_reader_analysis"
    return merged_csv.with_name(f"{merged_csv.stem}_analysis")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate endpoint replicate statistics and plate heatmaps from merged plate-reader data."
    )
    parser.add_argument(
        "experiment_dir",
        nargs="?",
        help=(
            "Experiment directory. Bare names and wildcards are resolved under "
            "FreeRTOS-interface/Experiments."
        ),
    )
    parser.add_argument(
        "--merged-csv",
        type=Path,
        default=None,
        help="Merged tidy CSV to analyze. Mutually exclusive with experiment_dir.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to <experiment>/plate_reader_analysis or <merged_csv_stem>_analysis.",
    )
    parser.add_argument(
        "--endpoint-last-n",
        type=int,
        default=3,
        help="Number of final timepoints to average for endpoint RFU. Defaults to 3.",
    )
    parser.add_argument(
        "--refresh-merged",
        action="store_true",
        help="Rebuild the merged tidy CSV before analysis. Only valid with an experiment directory.",
    )
    return parser


def print_summary(result: analysis.AnalysisResult, merged_csv: Path) -> None:
    print(f"Merged tidy data: {merged_csv}")
    print(f"Output directory: {result.output_dir}")
    print(f"Endpoint rows: {result.endpoint_rows}")
    print(f"Composition rows: {result.composition_rows}")
    print(f"Condition columns: {', '.join(result.condition_columns) if result.condition_columns else '(none)'}")
    print(f"Endpoint table: {result.endpoint_csv}")
    print(f"Composition summary: {result.composition_summary_csv}")
    print(f"Timecourse summary: {result.timecourse_summary_csv}")
    print(f"Absolute RFU heatmaps: {len(result.absolute_heatmap_pngs)}")
    print(f"Condition percent-difference heatmaps: {len(result.percent_difference_heatmap_pngs)}")
    print(f"Timecourse plots: {len(result.timecourse_plot_pngs)}")


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        merged_csv, experiment_dir = resolve_merged_tidy_csv(args)
        output_dir = args.output_dir or default_output_dir(merged_csv, experiment_dir)
        result = analysis.analyze_merged_tidy_csv(
            merged_csv,
            output_dir,
            endpoint_last_n=args.endpoint_last_n,
        )
    except Exception as exc:  # pragma: no cover - CLI reporting
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print_summary(result, merged_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
