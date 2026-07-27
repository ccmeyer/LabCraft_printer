#!/usr/bin/env python3
"""Run a real-UI virtual workflow without constructing physical hardware."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.virtual_workflows.registry import (  # noqa: E402
    DEFAULT_SCENARIO_ID,
    registered_scenario_ids,
    run_registered_scenario,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the versioned real-UI print-array workflow through the "
            "explicit in-process simulator."
        )
    )
    parser.add_argument(
        "--scenario",
        choices=registered_scenario_ids(),
        default=DEFAULT_SCENARIO_ID,
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
    parser.add_argument(
        "--qt-platform",
        choices=("offscreen", "minimal"),
        default="offscreen",
        help="Headless Qt platform selected before importing PySide6.",
    )
    parser.add_argument(
        "--target-pi",
        action="store_true",
        help="Require validated Pi preflight and private-device safety proof.",
    )
    parser.add_argument(
        "--pi-preflight",
        type=Path,
        help="Validated Pi SIL preflight JSON (required with --target-pi).",
    )
    parser.add_argument(
        "--pi-hardware-proof",
        type=Path,
        help="Validated traced hardware-isolation proof (required with --target-pi).",
    )
    parser.add_argument("--inject-ui-stall-ms", type=int, default=0)
    parser.add_argument("--inject-after-completion", type=int, default=48)
    parser.add_argument(
        "--warmup-runs",
        type=int,
        default=0,
        help="Scenario runs retained but excluded from comparison statistics.",
    )
    parser.add_argument(
        "--measured-runs",
        type=int,
        default=1,
        help="Scenario runs included as distinct comparison samples.",
    )
    parser.add_argument(
        "--host-label",
        help="Stable, non-secret label required for repeated/comparison evidence.",
    )
    parser.add_argument(
        "--emit-report-set",
        action="store_true",
        help=(
            "Write a report set even for one measured run. This is intended "
            "for opt-in stress evidence, not accepted baseline creation."
        ),
    )
    parser.add_argument(
        "--accept-baseline",
        type=Path,
        help="Write a compact tracked baseline summary from repeated clean runs.",
    )
    parser.add_argument(
        "--replace-accepted-baseline",
        action="store_true",
        help="Explicitly permit replacement of an existing baseline summary.",
    )
    parser.add_argument(
        "--threshold-maturity",
        choices=("candidate", "acceptance"),
        default="candidate",
        help="Classification maturity stored in a newly accepted baseline.",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASELINE", "CANDIDATE"),
        type=Path,
        help="Compare an existing baseline summary and candidate report set.",
    )
    return parser


def _comparison_exit_code(comparison: dict[str, object]) -> int:
    classification = comparison["classification"]
    assert isinstance(classification, dict)
    if classification["functional_status"] == "fail":
        return 2
    if classification["overall_status"] == "incomplete":
        return 3
    if classification["overall_status"] == "fail":
        return 4
    return 0


def _run_set_summary(report_set: dict[str, object]) -> str:
    runs = report_set["runs"]
    functional = report_set["functional"]
    noise = report_set["noise"]
    source = report_set["source_summary"]
    synthetic = report_set["synthetic"]
    assert isinstance(runs, dict)
    assert isinstance(functional, dict)
    assert isinstance(noise, dict)
    assert isinstance(source, dict)
    assert isinstance(synthetic, dict)
    lines = [
        "Virtual workflow report set",
        f"Host label: {report_set['host_label']}",
        f"Warm-up runs: {runs['warmup_count']}",
        f"Measured runs: {runs['measured_count']}",
        f"Functional status: {functional['status']}",
        f"Noise status: {noise['status']}",
        f"Dirty worktree present: {source['any_dirty_worktree']}",
        f"Measured injected stalls: {synthetic['measured_injected_count']}",
    ]
    noisy = noise.get("noisy_primary_metrics") or []
    if noisy:
        lines.append("Noisy primary metrics: " + ", ".join(noisy))
    return "\n".join(lines) + "\n"


def _report_path(report: dict[str, object]) -> Path:
    safety = report["safety"]
    assert isinstance(safety, dict)
    return Path(str(safety["scenario_root"])).resolve().parent / "report.json"


def _report_set_directory(
    output_root: Path, report_set: dict[str, object]
) -> Path:
    compatibility = report_set["compatibility"]
    assert isinstance(compatibility, dict)
    workload = compatibility["workload"]
    assert isinstance(workload, dict)
    sources = report_set["source_summary"]
    assert isinstance(sources, dict)
    source_rows = sources["sources"]
    assert isinstance(source_rows, list)
    commit = "unknown"
    if source_rows and isinstance(source_rows[0], dict):
        commit = str(source_rows[0].get("git_commit") or "unknown")[:12]
    stamp = (
        datetime.now(timezone.utc)
        .strftime("%Y%m%dT%H%M%S%fZ")
    )
    return (
        output_root
        / str(workload["workload_id"])
        / f"{stamp}_{commit}_report_set"
    ).resolve()


def _compare_existing(args: argparse.Namespace) -> int:
    from tools.virtual_workflows.compare import (
        compare_report_sets,
        load_baseline_summary,
        load_report_set,
        write_comparison,
        write_comparison_markdown,
    )

    baseline_path, candidate_path = args.compare
    baseline = load_baseline_summary(baseline_path)
    candidate = load_report_set(candidate_path)
    comparison = compare_report_sets(baseline, candidate)
    destination = candidate_path.resolve().parent
    comparison_path = write_comparison(
        destination / "comparison.json",
        comparison,
        replace=True,
    )
    markdown_path = write_comparison_markdown(
        destination / "comparison.md",
        comparison,
        replace=True,
    )
    print(markdown_path.read_text(encoding="utf-8"), end="")
    print(f"Comparison JSON: {comparison_path}")
    print(f"Comparison Markdown: {markdown_path}")
    return _comparison_exit_code(comparison)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.warmup_runs < 0 or args.measured_runs < 1:
        parser.error("--warmup-runs must be >= 0 and --measured-runs must be >= 1")
    if args.replace_accepted_baseline and args.accept_baseline is None:
        parser.error("--replace-accepted-baseline requires --accept-baseline")
    if args.visible and args.qt_platform != "offscreen":
        parser.error("--visible and an explicit non-default --qt-platform conflict")
    if args.target_pi and args.visible:
        parser.error("--target-pi is headless and cannot be combined with --visible")
    pi_evidence = (args.pi_preflight, args.pi_hardware_proof)
    if args.target_pi and any(value is None for value in pi_evidence):
        parser.error(
            "--target-pi requires --pi-preflight and --pi-hardware-proof"
        )
    if not args.target_pi and any(value is not None for value in pi_evidence):
        parser.error(
            "--pi-preflight and --pi-hardware-proof require --target-pi"
        )
    if args.compare is not None:
        if args.accept_baseline is not None:
            parser.error("--compare and --accept-baseline are mutually exclusive")
        try:
            return _compare_existing(args)
        except Exception as exc:
            print(
                f"Virtual workflow comparison failed: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 3

    repeated = (
        args.emit_report_set
        or args.warmup_runs > 0
        or args.measured_runs > 1
    )
    if (repeated or args.accept_baseline is not None) and not args.host_label:
        parser.error(
            "--host-label is required for repeated runs or baseline creation"
        )
    if args.accept_baseline is not None and (
        args.warmup_runs < 1 or args.measured_runs < 5
    ):
        parser.error(
            "--accept-baseline requires at least one warm-up and five measured runs"
        )
    if not args.visible:
        os.environ["QT_QPA_PLATFORM"] = args.qt_platform

    try:
        if args.target_pi:
            from tools.virtual_workflows.pi_sil import (
                load_and_validate_pi_evidence,
            )

            load_and_validate_pi_evidence(
                args.pi_preflight,
                args.pi_hardware_proof,
                expected_qt_platform=args.qt_platform,
            )
        from tools.virtual_workflows.compare import (
            build_report_set,
            create_baseline_summary,
            write_baseline_summary,
            write_report_set,
        )
        from tools.virtual_workflows.scenarios import (
            VirtualWorkflowScenarioError,
        )

        def run_once() -> dict[str, object]:
            return run_registered_scenario(
                args.scenario,
                output_root=args.output_root,
                visible=args.visible,
                speed_multiplier=args.speed_multiplier,
                timeout_seconds=args.timeout_seconds,
                inject_ui_stall_ms=args.inject_ui_stall_ms,
                inject_after_completion=args.inject_after_completion,
                pi_preflight_path=args.pi_preflight,
                pi_hardware_proof_path=args.pi_hardware_proof,
            )

        if not repeated and args.accept_baseline is None:
            report = run_once()
            report_dir = _report_path(report).parent
            print((report_dir / "summary.txt").read_text(encoding="utf-8"), end="")
            print(f"Report: {report_dir / 'report.json'}")
            return 0 if report["classification"]["status"] != "fail" else 2

        warmup_paths: list[Path] = []
        measured_paths: list[Path] = []
        for index in range(args.warmup_runs):
            print(f"Starting warm-up run {index + 1}/{args.warmup_runs}...")
            report = run_once()
            path = _report_path(report)
            warmup_paths.append(path)
            print(f"Warm-up report: {path}")
            if report["classification"]["status"] == "fail":
                print("Warm-up run failed; measured collection was not started.")
                return 2
        for index in range(args.measured_runs):
            print(f"Starting measured run {index + 1}/{args.measured_runs}...")
            report = run_once()
            path = _report_path(report)
            measured_paths.append(path)
            print(f"Measured report: {path}")
            if report["classification"]["status"] == "fail":
                print("Measured run failed; collection stopped.")
                return 2

        report_set = build_report_set(
            measured_paths,
            warmup_paths=warmup_paths,
            host_label=args.host_label,
        )
        set_dir = _report_set_directory(args.output_root, report_set)
        set_path = write_report_set(set_dir / "report_set.json", report_set)
        summary_path = set_dir / "summary.txt"
        summary_path.write_text(_run_set_summary(report_set), encoding="utf-8")
        print(summary_path.read_text(encoding="utf-8"), end="")
        print(f"Report set: {set_path}")

        if args.accept_baseline is not None:
            baseline = create_baseline_summary(
                report_set,
                maturity=args.threshold_maturity,
            )
            baseline_path = write_baseline_summary(
                args.accept_baseline,
                baseline,
                replace=args.replace_accepted_baseline,
            )
            print(f"Baseline summary: {baseline_path.resolve()}")
        return 0
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

if __name__ == "__main__":
    raise SystemExit(main())
