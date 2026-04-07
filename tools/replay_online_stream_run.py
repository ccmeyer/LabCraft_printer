#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stream_analysis import online_replay as online_replay_mod  # noqa: E402


def _iter_run_dirs(runs_root: Path):
    for path in sorted(runs_root.iterdir()):
        if not path.is_dir():
            continue
        if (path / "frames.jsonl").exists():
            yield path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay recorded online-stream calibration runs.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-dir", type=Path, help="Single recorder run directory to replay.")
    group.add_argument("--runs-root", type=Path, help="Root directory containing multiple recorder run directories.")
    parser.add_argument("--write-report", type=Path, help="Optional JSON path for the replay report.")
    args = parser.parse_args(argv)

    if args.run_dir is not None:
        report = online_replay_mod.replay_online_stream_run(args.run_dir)
    else:
        runs_root = Path(args.runs_root).resolve()
        report = {
            "runs_root": str(runs_root),
            "runs": [
                online_replay_mod.replay_online_stream_run(run_dir)
                for run_dir in _iter_run_dirs(runs_root)
            ],
        }

    if args.write_report is not None:
        output_path = Path(args.write_report).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
