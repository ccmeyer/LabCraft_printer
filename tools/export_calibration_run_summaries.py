#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.calibration_memory_analysis import export_run_summaries_csv, _print_json


def main():
    parser = argparse.ArgumentParser(description="Export calibration-memory run summaries to a flat CSV.")
    parser.add_argument("--root", default="", help="CalibrationMemory root. Defaults to local/CalibrationMemory.")
    parser.add_argument("--out", default="", help="Output CSV path.")
    args = parser.parse_args()

    payload = export_run_summaries_csv(
        root=args.root or None,
        out_path=args.out or None,
    )
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
