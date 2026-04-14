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
    parser.add_argument(
        "--density-g-per-ml",
        type=float,
        default=1.0,
        help="Gravimetric fluid density in g/mL used to convert mg to nL. Defaults to 1.0.",
    )
    parser.add_argument(
        "--correction-mode",
        choices=["none", "chroma_edge_v2", "runtime_rgb_fix"],
        default="none",
        help=(
            "Optional replay correction mode. Use runtime_rgb_fix to recompute from saved images "
            "with the corrected runtime path."
        ),
    )
    parser.add_argument(
        "--settling-aware-fit",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Enable or disable the conservative settling-aware late-window flow-fit rule when "
            "the report is recomputed. Defaults to the runtime/replay default."
        ),
    )
    parser.add_argument(
        "--tail-settling-rule",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Enable or disable the settling-aware tail-start rule when the report is recomputed. "
            "Defaults to the runtime/replay default."
        ),
    )
    args = parser.parse_args(argv)

    payload = online_report_mod.export_online_stream_experiment_report(
        args.experiment_root,
        output_root=args.output_root,
        run_id=args.run_id,
        density_g_per_ml=args.density_g_per_ml,
        correction_mode=(None if args.correction_mode == "none" else args.correction_mode),
        settling_aware_fit_enabled=args.settling_aware_fit,
        tail_settling_rule_enabled=args.tail_settling_rule,
    )
    dataset_mod._print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
