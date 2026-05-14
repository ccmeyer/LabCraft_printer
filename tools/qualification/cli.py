from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .identity import DEFAULT_IDENTITY_PATH
from .runner import DEFAULT_MANIFEST_REF, SelfTestInvoker, default_selftest_invoker, run_qualification


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a LabCraft qualification manifest through the existing self-test runner."
    )
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST_REF)
    parser.add_argument("--port", default="/dev/ttyAMA0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--machine-id", default=None)
    parser.add_argument("--identity-path", default=str(DEFAULT_IDENTITY_PATH))
    parser.add_argument("--output-root", default=str(Path("hil_reports") / "qualification"))
    parser.add_argument("--timeout-ms", type=int, default=None)
    parser.add_argument("--run-selftest-path", default=None)
    parser.add_argument(
        "--raw-report",
        default=None,
        help="Normalize an existing raw self-test JSON report instead of launching hardware self-test.",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, invoker: SelfTestInvoker | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_qualification(
        manifest_ref=args.manifest,
        port=args.port,
        baud=args.baud,
        machine_id=args.machine_id,
        identity_path=args.identity_path,
        output_root=args.output_root,
        timeout_ms=args.timeout_ms,
        run_selftest_path=args.run_selftest_path,
        raw_report_path=args.raw_report,
        invoker=invoker if invoker is not None else default_selftest_invoker,
    )
    print(f"Wrote qualification report: {result.report_path}")
    print(f"Wrote qualification summary: {result.summary_csv_path}")
    return int(result.returncode)
