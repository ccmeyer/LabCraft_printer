#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.calibration_memory_analysis import write_dataset_audit, _print_json


def main():
    parser = argparse.ArgumentParser(description="Audit calibration-memory run coverage, sparsity, and derived snapshot availability.")
    parser.add_argument("--root", default="", help="CalibrationMemory root. Defaults to FreeRTOS-interface/CalibrationMemory.")
    parser.add_argument("--json-out", default="", help="Audit JSON output path.")
    parser.add_argument("--md-out", default="", help="Audit markdown output path.")
    args = parser.parse_args()

    payload = write_dataset_audit(
        root=args.root or None,
        json_path=args.json_out or None,
        md_path=args.md_out or None,
    )
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
