#!/usr/bin/env python3
"""Run a real-UI virtual workflow without constructing physical hardware."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the versioned real-UI print-array workflow through the "
            "explicit in-process simulator."
        )
    )
    parser.add_argument(
        "--scenario",
        choices=("virtual_print_array_96_v1",),
        default="virtual_print_array_96_v1",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "verification_reports" / "virtual_workflows",
    )
    parser.add_argument("--speed-multiplier", type=float, default=1.0)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Show the real window using the caller's Qt platform selection.",
    )
    parser.add_argument("--inject-ui-stall-ms", type=int, default=0)
    parser.add_argument("--inject-after-completion", type=int, default=48)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.visible:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    try:
        from tools.virtual_workflows.scenarios import (
            VirtualPrintArrayScenarioConfig,
            VirtualWorkflowScenarioError,
            run_virtual_print_array_scenario,
        )

        report = run_virtual_print_array_scenario(
            VirtualPrintArrayScenarioConfig(
                output_root=args.output_root,
                visible=args.visible,
                speed_multiplier=args.speed_multiplier,
                timeout_seconds=args.timeout_seconds,
                inject_ui_stall_ms=args.inject_ui_stall_ms,
                inject_after_completion=args.inject_after_completion,
            )
        )
    except VirtualWorkflowScenarioError as exc:
        print(f"Virtual workflow setup failed: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(
            f"Virtual workflow reporting/environment failure: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 3

    report_dir = Path(report["safety"]["scenario_root"]).parent
    print((report_dir / "summary.txt").read_text(encoding="utf-8"), end="")
    print(f"Report: {report_dir / 'report.json'}")
    return 0 if report["classification"]["status"] != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
