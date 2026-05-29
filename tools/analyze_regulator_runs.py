#!/usr/bin/env python3
"""Analyze regulator optimization pressure trace runs and rank candidates."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from plot_pressure_traces import render_trace_file
from regulator_trace_analysis import RegulatorTraceAnalysisError, analyze_inputs, load_score_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze Stage 4 regulator optimization run folders or pressure trace JSON files."
    )
    parser.add_argument("inputs", nargs="+", help="Run folders, session/root folders, or *_trace_*.json files")
    parser.add_argument("--out-dir", help="Aggregate output directory")
    parser.add_argument("--score-config", help="JSON object with score weight overrides")
    parser.add_argument("--no-plots", action="store_true", help="Skip pressure trace PNG generation")
    parser.add_argument("--dpi", type=int, default=150, help="Plot DPI")
    parser.add_argument("--no-update-run-meta", action="store_true", help="Do not update run_meta.json output fields")
    args = parser.parse_args(argv)

    try:
        score_weights = load_score_config(args.score_config)
        result = analyze_inputs(
            args.inputs,
            output_dir=args.out_dir,
            score_weights=score_weights,
            make_plots=not args.no_plots,
            dpi=args.dpi,
            update_run_meta=not args.no_update_run_meta,
            plot_renderer=render_trace_file,
        )
    except (OSError, ValueError, RegulatorTraceAnalysisError) as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        return 2

    print(f"[ok] analyzed {len(result['runs'])} run(s)")
    print(f"     output: {result['output_dir']}")
    print(f"     ranking: {result['candidate_ranking_csv']}")
    print(f"     pulses: {result['all_pulses_csv']}")
    for row in result["ranking"]:
        score = row.get("score")
        score_text = "n/a" if score is None else f"{float(score):.3f}"
        rank = row.get("rank") or "unranked"
        print(
            "     "
            f"{rank}: candidate={row.get('candidate_profile_id') or 'unknown'} "
            f"run={row.get('run_id') or 'unknown'} score={score_text}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
