#!/usr/bin/env python3
"""Run a real-UI virtual workflow without constructing physical hardware."""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.virtual_workflows.registry import (  # noqa: E402
    DEFAULT_SCENARIO_ID,
    ManifestValidationError,
    get_registered_scenario,
    registered_scenario_ids,
    run_registered_scenario,
)
from tools.virtual_workflows.selection import (  # noqa: E402
    SelectionError,
    SelectionRequest,
    build_catalog,
    deterministic_json,
    discover_changed_paths,
    recommend_changed_paths,
    resolve_selection,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the versioned real-UI print-array workflow through the "
            "explicit in-process simulator."
        )
    )
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument(
        "--scenario",
        choices=registered_scenario_ids(),
        default=DEFAULT_SCENARIO_ID,
    )
    selector.add_argument(
        "--suite",
        help="Plan or execute a validated manifest suite.",
    )
    selector.add_argument(
        "--capability",
        help="Plan or execute a covered/partial capability.",
    )
    selector.add_argument(
        "--matrix",
        help="Plan or execute a validated typed parameter matrix.",
    )
    selector.add_argument(
        "--list",
        dest="list_section",
        choices=("all", "suites", "capabilities", "matrices"),
        help="Print a read-only manifest catalog and exit.",
    )
    selector.add_argument(
        "--recommend-changed",
        action="store_true",
        help="Recommend affected scenarios without executing them.",
    )
    selector.add_argument(
        "--coverage-from",
        action="append",
        default=[],
        type=Path,
        metavar="AGGREGATE",
        help=(
            "Evaluate one retained aggregate against the capability manifest; "
            "repeat to provide additional explicit evidence."
        ),
    )
    parser.add_argument(
        "--changed-path",
        action="append",
        default=[],
        type=Path,
        help=(
            "Explicit changed path for --recommend-changed; repeatable and "
            "overrides Git discovery."
        ),
    )
    parser.add_argument(
        "--case",
        help="Run exactly one case from the selected --matrix.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print a deterministic selection plan without execution.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "verification_reports" / "virtual_workflows",
    )
    parser.add_argument("--speed-multiplier", type=float, default=1.0)
    parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="Deterministic simulation seed retained in composed-journey evidence.",
    )
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


def _option_was_supplied(argv: list[str], option: str) -> bool:
    return any(
        value == option or value.startswith(option + "=") for value in argv
    )


def _planning_request(
    args: argparse.Namespace, raw_argv: list[str]
) -> SelectionRequest:
    if args.suite is not None:
        kind, selector_id = "suite", args.suite
    elif args.capability is not None:
        kind, selector_id = "capability", args.capability
    else:
        kind, selector_id = "scenario", args.scenario
    timeout_override = (
        args.timeout_seconds
        if _option_was_supplied(raw_argv, "--timeout-seconds")
        else None
    )
    pi_evidence = (
        ("preflight", "hardware_proof") if args.target_pi else ()
    )
    return SelectionRequest(
        kind=kind,
        selector_id=selector_id,
        platform="pi_sil" if args.target_pi else "windows_sil",
        seed=args.seed,
        timeout_override=timeout_override,
        pi_evidence=pi_evidence,
    )


def _aggregate_replay_command(
    args: argparse.Namespace,
    raw_argv: list[str],
    output_root: Path,
) -> tuple[str, ...]:
    selector_option = "--suite" if args.suite is not None else "--capability"
    selector_id = args.suite if args.suite is not None else args.capability
    command = [
        r".\env\Scripts\python.exe",
        r"tools\run_virtual_workflow.py",
        selector_option,
        str(selector_id),
        "--output-root",
        str(output_root),
        "--seed",
        str(args.seed),
        "--speed-multiplier",
        f"{args.speed_multiplier:g}",
    ]
    if _option_was_supplied(raw_argv, "--timeout-seconds"):
        command.extend(["--timeout-seconds", str(args.timeout_seconds)])
    if args.visible:
        command.append("--visible")
    else:
        command.extend(["--qt-platform", args.qt_platform])
    return tuple(command)


def _matrix_replay_command(
    args: argparse.Namespace,
    output_root: Path,
) -> tuple[str, ...]:
    command = [
        r".\env\Scripts\python.exe",
        r"tools\run_virtual_workflow.py",
        "--matrix",
        str(args.matrix),
    ]
    if args.case is not None:
        command.extend(["--case", str(args.case)])
    command.extend(
        [
            "--output-root",
            str(output_root),
            "--seed",
            str(args.seed),
            "--speed-multiplier",
            f"{args.speed_multiplier:g}",
            "--timeout-seconds",
            str(float(args.timeout_seconds)),
        ]
    )
    if args.visible:
        command.append("--visible")
    else:
        command.extend(["--qt-platform", args.qt_platform])
    return tuple(command)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_aggregate_option_conflicts(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    raw_argv: list[str],
) -> None:
    if (
        args.target_pi
        or args.pi_preflight is not None
        or args.pi_hardware_proof is not None
    ):
        parser.error("Pi suite execution is deferred to Milestone 8 Slice 7")
    conflicts = []
    if args.inject_ui_stall_ms != 0 or args.inject_after_completion != 48:
        conflicts.append("fault injection")
    if args.warmup_runs != 0 or args.measured_runs != 1:
        conflicts.append("run repetition")
    if args.host_label is not None:
        conflicts.append("--host-label")
    if args.emit_report_set:
        conflicts.append("--emit-report-set")
    if args.accept_baseline is not None or args.replace_accepted_baseline:
        conflicts.append("baseline creation")
    if _option_was_supplied(raw_argv, "--threshold-maturity"):
        conflicts.append("--threshold-maturity")
    if args.compare is not None:
        conflicts.append("--compare")
    if conflicts:
        parser.error(
            "suite/capability/matrix execution does not support: "
            + ", ".join(conflicts)
        )


def _reject_coverage_option_conflicts(
    parser: argparse.ArgumentParser, raw_argv: list[str]
) -> None:
    allowed = {"--coverage-from", "--output-root"}
    supplied = {
        value.split("=", 1)[0]
        for value in raw_argv
        if value.startswith("--")
    }
    conflicts = sorted(supplied - allowed)
    if conflicts:
        parser.error(
            "coverage evaluation accepts only --coverage-from and "
            "--output-root; unsupported: " + ", ".join(conflicts)
        )


def _coverage_replay_command(
    aggregate_paths: list[Path], output_root: Path
) -> tuple[str, ...]:
    command = [
        r".\env\Scripts\python.exe",
        r"tools\run_virtual_workflow.py",
    ]
    for path in aggregate_paths:
        command.extend(["--coverage-from", str(path.resolve())])
    command.extend(["--output-root", str(output_root.resolve())])
    return tuple(command)


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
    if safety.get("report_dir"):
        return Path(str(safety["report_dir"])).resolve() / "report.json"
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
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(raw_argv)
    coverage_mode = bool(args.coverage_from)
    if args.case is not None and args.matrix is None:
        parser.error("--case requires --matrix")
    if coverage_mode:
        _reject_coverage_option_conflicts(parser, raw_argv)
    if args.changed_path and not args.recommend_changed:
        parser.error("--changed-path requires --recommend-changed")
    if args.dry_run and (args.list_section or args.recommend_changed):
        parser.error("--dry-run cannot be combined with listing or recommendations")
    planning_mode = bool(
        args.dry_run or args.list_section or args.recommend_changed
    )
    if planning_mode and args.compare is not None:
        parser.error("planning modes cannot be combined with --compare")

    try:
        if args.list_section:
            if args.list_section == "matrices":
                from tools.virtual_workflows.matrices import matrix_catalog

                print(deterministic_json(matrix_catalog()), end="")
                return 0
            print(deterministic_json(build_catalog(args.list_section)), end="")
            return 0
        if args.recommend_changed:
            changed_paths = (
                tuple(args.changed_path)
                if args.changed_path
                else discover_changed_paths(REPO_ROOT)
            )
            print(
                deterministic_json(recommend_changed_paths(changed_paths)),
                end="",
            )
            return 0
    except (ManifestValidationError, SelectionError) as exc:
        parser.error(str(exc))

    if coverage_mode:
        coverage_output_root = (
            args.output_root
            if _option_was_supplied(raw_argv, "--output-root")
            else REPO_ROOT / "verification_reports" / "suites"
        )
        try:
            from tools.virtual_workflows.coverage import (
                CoverageRunConfig,
                execute_coverage_evaluation,
            )

            result = execute_coverage_evaluation(
                CoverageRunConfig(
                    aggregate_paths=tuple(args.coverage_from),
                    output_root=coverage_output_root,
                    replay_command=_coverage_replay_command(
                        args.coverage_from, coverage_output_root
                    ),
                )
            )
            print(result.summary_path.read_text(encoding="utf-8"), end="")
            print(f"Coverage: {result.evaluation_path}")
            print(f"Coverage SHA-256: {_file_sha256(result.evaluation_path)}")
            return result.exit_code
        except Exception as exc:
            print(
                "SIL capability coverage evaluation failed: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 3

    if args.warmup_runs < 0 or args.measured_runs < 1:
        parser.error("--warmup-runs must be >= 0 and --measured-runs must be >= 1")
    if args.replace_accepted_baseline and args.accept_baseline is None:
        parser.error("--replace-accepted-baseline requires --accept-baseline")
    if args.visible and args.qt_platform != "offscreen":
        parser.error("--visible and an explicit non-default --qt-platform conflict")
    if args.target_pi and args.visible:
        parser.error("--target-pi is headless and cannot be combined with --visible")
    aggregate_execution = (
        not args.dry_run
        and (args.suite is not None or args.capability is not None)
    )
    matrix_execution = not args.dry_run and args.matrix is not None
    if aggregate_execution:
        _reject_aggregate_option_conflicts(parser, args, raw_argv)
    if matrix_execution:
        _reject_aggregate_option_conflicts(parser, args, raw_argv)
    pi_evidence = (args.pi_preflight, args.pi_hardware_proof)
    if args.target_pi and any(value is None for value in pi_evidence):
        parser.error(
            "--target-pi requires --pi-preflight and --pi-hardware-proof"
        )
    if not args.target_pi and any(value is not None for value in pi_evidence):
        parser.error(
            "--pi-preflight and --pi-hardware-proof require --target-pi"
        )
    if args.dry_run:
        try:
            if args.matrix is not None:
                if args.target_pi:
                    parser.error("parameter matrices are Windows SIL only")
                from tools.virtual_workflows.matrices import resolve_matrix_plan

                plan = resolve_matrix_plan(
                    args.matrix,
                    case_id=args.case,
                    seed=args.seed,
                    timeout_seconds=args.timeout_seconds,
                    execution_authorized=False,
                )
                print(deterministic_json(plan), end="")
                return 0
            if args.target_pi:
                from tools.virtual_workflows.pi_sil import (
                    load_and_validate_pi_evidence,
                )

                load_and_validate_pi_evidence(
                    args.pi_preflight,
                    args.pi_hardware_proof,
                    expected_qt_platform=args.qt_platform,
                )
            plan = resolve_selection(_planning_request(args, raw_argv))
            print(deterministic_json(plan), end="")
            return 0
        except SelectionError as exc:
            parser.error(str(exc))
        except Exception as exc:
            parser.error(
                f"selection evidence validation failed: "
                f"{type(exc).__name__}: {exc}"
            )

    if aggregate_execution:
        aggregate_output_root = (
            args.output_root
            if _option_was_supplied(raw_argv, "--output-root")
            else REPO_ROOT / "verification_reports" / "suites"
        )
        if not math.isfinite(args.speed_multiplier) or args.speed_multiplier <= 0:
            parser.error("--speed-multiplier must be finite and greater than zero")
        try:
            plan = resolve_selection(_planning_request(args, raw_argv))
        except (ManifestValidationError, SelectionError) as exc:
            parser.error(str(exc))
        try:
            from tools.virtual_workflows.suite_runner import (
                AggregateRunConfig,
                execute_host_selection,
            )

            result = execute_host_selection(
                AggregateRunConfig(
                    plan=plan,
                    output_root=aggregate_output_root,
                    speed_multiplier=args.speed_multiplier,
                    visible=args.visible,
                    qt_platform=args.qt_platform,
                    replay_command=_aggregate_replay_command(
                        args, raw_argv, aggregate_output_root
                    ),
                )
            )
            print(result.summary_path.read_text(encoding="utf-8"), end="")
            print(f"Aggregate: {result.aggregate_path}")
            print(f"Aggregate SHA-256: {_file_sha256(result.aggregate_path)}")
            return result.exit_code
        except Exception as exc:
            print(
                "Virtual workflow aggregate failed: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 3

    if matrix_execution:
        if args.target_pi:
            parser.error("parameter matrices are Windows SIL only")
        if not math.isfinite(args.speed_multiplier) or args.speed_multiplier <= 0:
            parser.error("--speed-multiplier must be finite and greater than zero")
        matrix_output_root = (
            args.output_root
            if _option_was_supplied(raw_argv, "--output-root")
            else REPO_ROOT / "verification_reports" / "matrices"
        )
        try:
            from tools.virtual_workflows.matrices import resolve_matrix_plan

            if args.case is None:
                from tools.virtual_workflows.matrix_runner import (
                    MatrixRunConfig,
                    execute_matrix,
                )

                plan = resolve_matrix_plan(
                    args.matrix,
                    seed=args.seed,
                    timeout_seconds=args.timeout_seconds,
                )
                result = execute_matrix(
                    MatrixRunConfig(
                        plan=plan,
                        output_root=matrix_output_root,
                        speed_multiplier=args.speed_multiplier,
                        visible=args.visible,
                        qt_platform=args.qt_platform,
                        replay_command=_matrix_replay_command(
                            args, matrix_output_root
                        ),
                    )
                )
                print(result.summary_path.read_text(encoding="utf-8"), end="")
                print(f"Matrix aggregate: {result.aggregate_path}")
                print(f"Matrix aggregate SHA-256: {_file_sha256(result.aggregate_path)}")
                return result.exit_code

            if not args.visible:
                os.environ["QT_QPA_PLATFORM"] = args.qt_platform
            from tools.virtual_workflows.qt_font_environment import (
                configure_sil_qt_font_environment,
            )
            configure_sil_qt_font_environment(
                qt_platform=(None if args.visible else args.qt_platform)
            )
            from tools.virtual_workflows.journeys import (
                JourneyRunConfig,
                MIXED_MODE_WORKLOAD_ID,
                run_matrix_case,
            )
            report = run_matrix_case(
                JourneyRunConfig(
                    scenario_id=MIXED_MODE_WORKLOAD_ID,
                    output_root=matrix_output_root,
                    visible=args.visible,
                    seed=args.seed,
                    speed_multiplier=args.speed_multiplier,
                    timeout_seconds=args.timeout_seconds,
                ),
                matrix_id=args.matrix,
                case_id=args.case,
            )
            report_path = _report_path(report)
            print(report_path.with_name("summary.txt").read_text(encoding="utf-8"), end="")
            print(f"Report: {report_path}")
            return 0 if report["classification"]["status"] != "fail" else 2
        except Exception as exc:
            print(
                "Virtual workflow matrix failed: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 3

    scenario_definition = get_registered_scenario(args.scenario)
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
    if not scenario_definition.supports_pi_evidence and (
        args.target_pi or any(value is not None for value in pi_evidence)
    ):
        parser.error(
            f"--scenario {args.scenario} does not support Pi evidence"
        )
    if not scenario_definition.supports_injected_stall and (
        args.inject_ui_stall_ms != 0
        or args.inject_after_completion != 48
    ):
        parser.error(
            f"--scenario {args.scenario} does not support injected-stall controls"
        )
    if not scenario_definition.supports_report_sets and (
        repeated or args.accept_baseline is not None
    ):
        parser.error(
            f"--scenario {args.scenario} supports one direct run only; "
            "report sets, repetition, and baseline creation are unavailable"
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
        from tools.virtual_workflows.qt_font_environment import (
            configure_sil_qt_font_environment,
        )

        configure_sil_qt_font_environment(
            qt_platform=(None if args.visible else args.qt_platform),
        )
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
                seed=args.seed,
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
