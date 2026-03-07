#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.calibration_memory_analysis import plot_trend_tables, _print_json


def main():
    parser = argparse.ArgumentParser(description="Build offline calibration-memory trend tables and plots.")
    parser.add_argument("--root", default="", help="CalibrationMemory root. Defaults to FreeRTOS-interface/CalibrationMemory.")
    parser.add_argument("--out-dir", default="", help="Output directory for plot CSVs, PNGs, and manifest.")
    parser.add_argument("--reagent", action="append", default=[], help="Reagent id filter. Repeat or use comma-separated values.")
    parser.add_argument("--head-type", action="append", default=[], help="Head type filter. Repeat or use comma-separated values.")
    args = parser.parse_args()

    payload = plot_trend_tables(
        root=args.root or None,
        out_dir=args.out_dir or None,
        reagent_ids=args.reagent,
        head_type_ids=args.head_type,
    )
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
