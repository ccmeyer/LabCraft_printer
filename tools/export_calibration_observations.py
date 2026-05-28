#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.calibration_memory_analysis import export_observations_csv, _print_json


def main():
    parser = argparse.ArgumentParser(description="Export calibration-memory observations.jsonl files to a flat CSV.")
    parser.add_argument("--root", default="", help="CalibrationMemory root. Defaults to local/CalibrationMemory.")
    parser.add_argument("--out", default="", help="Output CSV path.")
    parser.add_argument("--run-id", action="append", default=[], help="Exact run id filter. Repeat or use comma-separated values.")
    parser.add_argument(
        "--observation-type",
        action="append",
        default=[],
        help="Exact observation_type filter. Repeat or use comma-separated values.",
    )
    parser.add_argument("--phase", action="append", default=[], help="Exact phase filter. Repeat or use comma-separated values.")
    parser.add_argument("--completed-only", action="store_true", help="Export only observations from completed runs.")
    args = parser.parse_args()

    payload = export_observations_csv(
        root=args.root or None,
        out_path=args.out or None,
        run_ids=args.run_id,
        observation_types=args.observation_type,
        phases=args.phase,
        completed_only=bool(args.completed_only),
    )
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
