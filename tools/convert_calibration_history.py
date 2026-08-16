"""Dry-run, apply, resume, or validate one historical calibration conversion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
INTERFACE_ROOT = REPO_ROOT / "FreeRTOS-interface"
if str(INTERFACE_ROOT) not in sys.path:
    sys.path.insert(0, str(INTERFACE_ROOT))

from CalibrationHistoricalConversion import (  # noqa: E402
    CalibrationHistoricalConverter,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experiment-dir",
        type=Path,
        required=True,
        help="Exact experiment directory containing calibration.json.",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--apply", action="store_true", help="Apply the conversion plan.")
    modes.add_argument("--resume", action="store_true", help="Resume an interrupted apply.")
    modes.add_argument("--validate", action="store_true", help="Validate a completed conversion.")
    parser.add_argument(
        "--progress",
        choices=("text", "json", "none"),
        default="text",
        help="Progress output format (default: text).",
    )
    return parser


def _reject_broad_target(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    broad = {
        REPO_ROOT.resolve(),
        (REPO_ROOT / "FreeRTOS-interface" / "Experiments").resolve(),
        Path.home().resolve(),
        Path(resolved.anchor).resolve(),
    }
    if resolved in broad:
        raise ValueError(f"refusing broad conversion target: {resolved}")
    return resolved


def _progress_writer(mode: str):
    started = time.monotonic()

    def emit(stage: str, completed: int, total: int, details):
        if mode == "none":
            return
        row = {
            "stage": str(stage),
            "completed": int(completed),
            "total": int(total),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            **dict(details or {}),
        }
        if mode == "json":
            print("CALIBRATION_MIGRATION_PROGRESS " + json.dumps(row, sort_keys=True), flush=True)
        else:
            suffix = f" ({completed}/{total})" if total else ""
            detail = f" item={row['item_id']}" if row.get("item_id") else ""
            print(
                f"Calibration migration: {stage}{suffix}{detail} "
                f"elapsed={row['elapsed_seconds']:.3f}s",
                flush=True,
            )

    return emit


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    experiment_dir = _reject_broad_target(args.experiment_dir)
    converter = CalibrationHistoricalConverter(
        experiment_dir,
        progress_callback=_progress_writer(args.progress),
    )
    if args.apply:
        report = converter.apply()
    elif args.resume:
        report = converter.resume()
    elif args.validate:
        report = converter.validate()
    else:
        plan = converter.plan()
        report = {"mode": "dry_run", "writes_performed": 0, **plan.to_dict()}
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
