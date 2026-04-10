#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stream_analysis import dataset as dataset_mod  # noqa: E402
from tools.stream_analysis import online_report as online_report_mod  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate an offline report for archived online-stream calibration experiments."
    )
    parser.add_argument(
        "--experiment-root",
        required=True,
        type=Path,
        help="Experiment directory, stream_metadata.csv, process root, or run directory.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Optional output directory. Defaults to <experiment>/analysis/online_stream_report.",
    )
    parser.add_argument(
        "--run-id",
        help="Optional Dataset name filter to generate a report for a single run.",
    )
    args = parser.parse_args(argv)

    payload = online_report_mod.export_online_stream_experiment_report(
        args.experiment_root,
        output_root=args.output_root,
        run_id=args.run_id,
    )
    dataset_mod._print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
