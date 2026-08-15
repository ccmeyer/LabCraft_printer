"""Explicit offline repair for calibration_index.jsonl."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
INTERFACE_ROOT = REPO_ROOT / "FreeRTOS-interface"
if str(INTERFACE_ROOT) not in sys.path:
    sys.path.insert(0, str(INTERFACE_ROOT))

from CalibrationRecordingReader import repair_calibration_index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or explicitly apply a canonical calibration-index rebuild."
    )
    parser.add_argument(
        "--experiment-dir",
        type=Path,
        required=True,
        help="Exact experiment directory containing calibration_recordings.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Atomically replace the index after validation (default is dry-run).",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    report = repair_calibration_index(args.experiment_dir, apply=args.apply)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
