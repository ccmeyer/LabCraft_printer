from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .campaign import DEFAULT_CAMPAIGN_REF, QualificationRunner, load_campaign, run_campaign
from .identity import DEFAULT_IDENTITY_PATH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a LabCraft qualification campaign made of existing qualification manifests."
    )
    parser.add_argument("--campaign", default=DEFAULT_CAMPAIGN_REF)
    parser.add_argument("--port", default="/dev/ttyAMA0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--machine-id", default=None)
    parser.add_argument("--identity-path", default=str(DEFAULT_IDENTITY_PATH))
    parser.add_argument("--campaign-output-root", default=str(Path("hil_reports") / "qualification_campaigns"))
    parser.add_argument("--suite-output-root", default=str(Path("hil_reports") / "qualification"))
    parser.add_argument("--operator-prompts", action="store_true")
    parser.add_argument("--progress-jsonl", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--run-selftest-path", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _print_dry_run(campaign_ref: str) -> None:
    campaign = load_campaign(campaign_ref)
    print(f"Campaign: {campaign.name} ({campaign.campaign_id})")
    print(f"Requires operator prompts: {'yes' if campaign.requires_operator_prompts else 'no'}")
    for step in campaign.steps:
        timeout = step.timeout_ms if step.timeout_ms is not None else "default"
        print(
            f"{step.index}. {step.manifest_id} | fixture={step.fixture_id or 'none'} "
            f"| timeout_ms={timeout} | operator_gated={'yes' if step.requires_operator_prompts else 'no'}"
        )


def main(argv: Sequence[str] | None = None, *, qualification_runner: QualificationRunner | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run:
        _print_dry_run(args.campaign)
        return 0
    kwargs = {}
    if qualification_runner is not None:
        kwargs["qualification_runner"] = qualification_runner
    result = run_campaign(
        campaign_ref=args.campaign,
        port=args.port,
        baud=args.baud,
        machine_id=args.machine_id,
        identity_path=args.identity_path,
        campaign_output_root=args.campaign_output_root,
        suite_output_root=args.suite_output_root,
        operator_prompts=args.operator_prompts,
        progress_jsonl=args.progress_jsonl,
        continue_on_failure=args.continue_on_failure,
        run_selftest_path=args.run_selftest_path,
        **kwargs,
    )
    print(f"Wrote campaign report: {result.report_path}")
    print(f"Wrote campaign summary: {result.summary_csv_path}")
    return int(result.returncode)
