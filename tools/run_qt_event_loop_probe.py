#!/usr/bin/env python3
"""Run a hardware-isolated, offscreen Qt event-loop characterization."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tools.virtual_workflows.metrics import (
    DEFAULT_LATENCY_BANDS_MS,
    NamedPhaseRecorder,
    ProcessResourceSampler,
    QtEventLoopProbe,
    summarize_samples,
)
from tools.virtual_workflows.report import (
    REPORT_SCHEMA_NAME,
    REPORT_SCHEMA_VERSION,
    collect_environment_identity,
    write_report_atomic,
)


WORKLOAD_ID = "qt_event_loop_probe_v1"
SCENARIO_NAME = "qt_event_loop_probe"
SCENARIO_VERSION = "1"
DEFAULT_OUTPUT_ROOT = Path("verification_reports") / "virtual_workflows"
INITIAL_IDLE_MS = 200
BETWEEN_STALLS_MS = 200
FINAL_IDLE_MS = 300
DEFAULT_STALLS_MS = (50, 100, 250, 350)


class ProbeCorrectnessError(RuntimeError):
    """Raised when the real Qt probe misses known injected evidence."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_probe_iteration(
    app: Any,
    *,
    stalls_ms: tuple[int, ...],
    heartbeat_interval_ms: int,
    stack_capture_ms: float,
    observer_interval_ms: int,
    resource_interval_ms: int,
) -> dict[str, Any]:
    from PySide6.QtCore import QEventLoop, QTimer

    phases = NamedPhaseRecorder()
    resources = ProcessResourceSampler()
    probe = QtEventLoopProbe(
        heartbeat_interval_ms=heartbeat_interval_ms,
        stack_capture_ms=stack_capture_ms,
        observer_interval_ms=observer_interval_ms,
        resource_interval_ms=resource_interval_ms,
        phase_recorder=phases,
        resource_sampler=resources,
    )
    loop = QEventLoop()
    injected = []
    offset_ms = INITIAL_IDLE_MS

    def block_event_loop(name: str, duration_ms: int) -> None:
        with phases.phase(
            name,
            {
                "kind": "injected_qt_stall",
                "requested_duration_ms": duration_ms,
            },
        ):
            time.sleep(duration_ms / 1000.0)

    for index, duration_ms in enumerate(stalls_ms, start=1):
        phase_name = f"injected_stall_{index}_{duration_ms}ms"
        injected.append(
            {
                "phase_name": phase_name,
                "requested_duration_ms": duration_ms,
                "scheduled_offset_ms": offset_ms,
            }
        )
        offset_ms += duration_ms + BETWEEN_STALLS_MS

    def schedule_stall(index: int, delay_ms: int) -> None:
        if index >= len(injected):
            QTimer.singleShot(FINAL_IDLE_MS, loop.quit)
            return

        expected = injected[index]

        def run_stall() -> None:
            block_event_loop(
                expected["phase_name"],
                expected["requested_duration_ms"],
            )
            schedule_stall(index + 1, BETWEEN_STALLS_MS)

        QTimer.singleShot(delay_ms, run_stall)

    started_ns = time.perf_counter_ns()
    stop_error = None
    try:
        probe.start(app)
        schedule_stall(0, INITIAL_IDLE_MS)
        loop.exec()
    finally:
        try:
            probe.stop()
        except Exception as exc:
            stop_error = f"{type(exc).__name__}: {exc}"
    duration_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
    snapshot = probe.snapshot()
    resource_snapshot = resources.snapshot()

    checks = []
    missing = []
    for expected in injected:
        phase_name = expected["phase_name"]
        requested = expected["requested_duration_ms"]
        candidates = [
            event
            for event in snapshot["stall_events"]
            if (event.get("phase") or {}).get("name") == phase_name
        ]
        detected = bool(
            candidates
            and max(event["event_loop_gap_ms"] for event in candidates)
            >= requested * 0.60
        )
        check = {
            **expected,
            "detected": detected,
            "maximum_attributed_gap_ms": (
                max(event["event_loop_gap_ms"] for event in candidates)
                if candidates
                else None
            ),
        }
        checks.append(check)
        if not detected:
            missing.append(phase_name)

    stack_expected = [
        row["phase_name"]
        for row in injected
        if row["requested_duration_ms"]
        > stack_capture_ms + (2 * observer_interval_ms)
    ]
    captured_phases = {
        (capture.get("phase") or {}).get("name")
        for capture in snapshot["stack_captures"]
    }
    missing_stacks = [
        phase_name for phase_name in stack_expected if phase_name not in captured_phases
    ]
    if stop_error:
        missing.append(f"cleanup: {stop_error}")
    if snapshot["shutdown"]["timer_active"]:
        missing.append("cleanup: timer active")
    if snapshot["shutdown"]["observer_thread_alive"]:
        missing.append("cleanup: observer thread active")
    if missing_stacks:
        missing.extend(f"stack: {name}" for name in missing_stacks)
    if missing:
        observed = [
            {
                "gap_ms": event.get("event_loop_gap_ms"),
                "phase": (event.get("phase") or {}).get("name"),
            }
            for event in snapshot["stall_events"]
        ]
        raise ProbeCorrectnessError(
            "probe missed required evidence: "
            + ", ".join(missing)
            + f"; observed={observed}"
        )
    return {
        "duration_ms": duration_ms,
        "injected_stalls": injected,
        "injected_stall_checks": checks,
        "responsiveness": snapshot,
        "resources": resource_snapshot,
    }


def _aggregate_responsiveness(runs: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = [
        sample
        for run in runs
        for sample in run["responsiveness"]["raw_event_loop_gap_ms"]
    ]
    lateness = [
        sample
        for run in runs
        for sample in run["responsiveness"]["raw_scheduling_lateness_ms"]
    ]
    callback_cost = [
        sample
        for run in runs
        for sample in run["responsiveness"]["raw_probe_callback_cost_ms"]
    ]
    stall_events = [
        {**event, "run_index": run["run_index"]}
        for run in runs
        for event in run["responsiveness"]["stall_events"]
    ]
    stack_captures = [
        {**capture, "run_index": run["run_index"]}
        for run in runs
        for capture in run["responsiveness"]["stack_captures"]
    ]
    return {
        "heartbeat_interval_ms": runs[0]["responsiveness"]["heartbeat_interval_ms"],
        "observer_interval_ms": runs[0]["responsiveness"]["observer_interval_ms"],
        "stack_capture_threshold_ms": runs[0]["responsiveness"][
            "stack_capture_threshold_ms"
        ],
        "threshold_bands_ms": list(DEFAULT_LATENCY_BANDS_MS),
        "event_loop_gap_ms": summarize_samples(gaps),
        "scheduling_lateness_ms": summarize_samples(lateness),
        "probe_callback_cost_ms": summarize_samples(callback_cost, bands_ms=()),
        "stall_events": stall_events,
        "stack_captures": stack_captures,
        "injected_stall_checks": [
            {**check, "run_index": run["run_index"]}
            for run in runs
            for check in run["injected_stall_checks"]
        ],
        "runs": runs,
    }


def _aggregate_resources(runs: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots = [run["resources"] for run in runs]
    statuses = {snapshot["status"] for snapshot in snapshots}
    if statuses == {"measured"}:
        status = "measured"
    elif statuses == {"not_available"}:
        status = "not_available"
    else:
        status = "partial"
    cpu_values = [
        snapshot["values"]["process_cpu_time_ms_delta"]
        for snapshot in snapshots
        if snapshot["values"].get("process_cpu_time_ms_delta") is not None
    ]
    rss_values = [
        snapshot["values"]["peak_rss_bytes"]
        for snapshot in snapshots
        if snapshot["values"].get("peak_rss_bytes") is not None
    ]
    return {
        "status": status,
        "values": {
            "process_cpu_time_ms_delta": summarize_samples(
                cpu_values,
                bands_ms=(),
            ),
            "peak_rss_bytes": max(rss_values) if rss_values else None,
            "runs": snapshots,
        },
    }


def _base_report(
    *,
    identity: dict[str, dict[str, Any]],
    started_at: str,
    warmup_runs: int,
    measured_runs: int,
    stalls_ms: tuple[int, ...],
    heartbeat_interval_ms: int,
    stack_capture_ms: float,
    observer_interval_ms: int,
    resource_interval_ms: int,
) -> dict[str, Any]:
    return {
        "schema_name": REPORT_SCHEMA_NAME,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "run_id": str(uuid.uuid4()),
            "scenario_name": SCENARIO_NAME,
            "scenario_version": SCENARIO_VERSION,
            "run_mode": "windows_sil"
            if identity["environment"]["operating_system"] == "Windows"
            else "host_sil",
            "timing_policy": "real_qt_offscreen_injected_stalls",
            "warmup_runs": warmup_runs,
            "measured_runs": measured_runs,
            "started_at_utc": started_at,
            "ended_at_utc": started_at,
            "duration_ms": 0.0,
        },
        "source": identity["source"],
        "environment": identity["environment"],
        "safety": {
            "simulation": True,
            "hardware_access_allowed": False,
            "construction_path": (
                "QApplication + QEventLoop + QtEventLoopProbe; no application, "
                "Controller, machine, transport, or device construction"
            ),
            "hardware_interfaces": {
                "serial": False,
                "gpio": False,
                "camera": False,
                "balance": False,
                "mcu": False,
                "firmware_update": False,
            },
        },
        "workload": {
            "workload_id": WORKLOAD_ID,
            "qt_platform": os.environ.get("QT_QPA_PLATFORM"),
            "heartbeat_interval_ms": heartbeat_interval_ms,
            "stack_capture_threshold_ms": stack_capture_ms,
            "observer_interval_ms": observer_interval_ms,
            "resource_interval_ms": resource_interval_ms,
            "injected_stalls_ms": list(stalls_ms),
            "initial_idle_ms": INITIAL_IDLE_MS,
            "between_stalls_ms": BETWEEN_STALLS_MS,
            "final_idle_ms": FINAL_IDLE_MS,
        },
        "metrics": {
            "responsiveness": {"status": "not_available", "values": {}},
            "workflow": {"status": "not_applicable", "values": {}},
            "queue": {"status": "not_applicable", "values": {}},
            "persistence": {"status": "not_applicable", "values": {}},
            "resources": {"status": "not_available", "values": {}},
        },
        "artifacts": {
            "report_json": "report.json",
            "summary_text": "summary.txt",
            "stall_stacks_text": "stall_stacks.txt",
        },
        "classification": {
            "status": "pass",
            "threshold_maturity": "informational",
            "reasons": ["all injected Qt stalls were detected and attributed"],
        },
        "limitations": [
            "Offscreen Qt does not measure compositor or GPU rendering behavior.",
            "Injected time.sleep callbacks validate detection but do not reproduce application work.",
            "No application widgets, Controller, command queue, transport, MCU, or hardware are exercised.",
            "A pass validates the probe and cleanup; it is not a responsiveness acceptance threshold.",
        ],
    }


def _write_stack_artifact(path: Path, report: dict[str, Any]) -> None:
    captures = report["metrics"]["responsiveness"]["values"].get(
        "stack_captures",
        [],
    )
    lines = ["LabCraft virtual workflow Qt stall stacks"]
    if not captures:
        lines.append("No stack captures were recorded.")
    for index, capture in enumerate(captures, start=1):
        phase = (capture.get("phase") or {}).get("name")
        lines.extend(
            [
                "",
                f"=== Capture {index} run={capture.get('run_index')} "
                f"phase={phase} gap_ms={capture.get('observed_gap_ms')} ===",
                str(capture.get("stack") or "No Python frame available."),
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_summary(path: Path, report: dict[str, Any]) -> None:
    responsive = report["metrics"]["responsiveness"]["values"]
    lines = [
        "LabCraft Qt event-loop probe",
        f"Classification: {report['classification']['status']} "
        f"({report['classification']['threshold_maturity']})",
        f"Run ID: {report['run']['run_id']}",
        f"Commit: {report['source'].get('git_commit') or 'unavailable'}",
        f"Dirty worktree: {report['source'].get('dirty_worktree')}",
        f"Qt: {report['environment']['qt'].get('pyside_version')} / "
        f"{report['environment']['qt'].get('qt_version')} "
        f"({report['environment']['qt'].get('binding')})",
    ]
    if responsive:
        gap = responsive["event_loop_gap_ms"]
        overhead = responsive["probe_callback_cost_ms"]
        lines.extend(
            [
                f"Measured runs: {report['run']['measured_runs']}",
                f"Event-loop gap p50/p95/p99/max ms: "
                f"{gap['p50']:.3f} / {gap['p95']:.3f} / "
                f"{gap['p99']:.3f} / {gap['maximum']:.3f}",
                f"Probe callback p50/p95/max ms: "
                f"{overhead['p50']:.4f} / {overhead['p95']:.4f} / "
                f"{overhead['maximum']:.4f}",
                f"Attributed stall events: {len(responsive['stall_events'])}",
                f"Stack captures: {len(responsive['stack_captures'])}",
            ]
        )
    for reason in report["classification"]["reasons"]:
        lines.append(f"Reason: {reason}")
    lines.append("This report is informational and does not establish acceptance.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_probe(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    warmup_runs: int = 1,
    measured_runs: int = 5,
    stalls_ms: tuple[int, ...] = DEFAULT_STALLS_MS,
    heartbeat_interval_ms: int = 10,
    stack_capture_ms: float = 250.0,
    observer_interval_ms: int = 5,
    resource_interval_ms: int = 100,
) -> tuple[int, Path]:
    if warmup_runs < 0 or measured_runs < 1:
        raise ValueError("warmup runs must be non-negative and measured runs positive")
    if not stalls_ms or any(
        isinstance(value, bool) or int(value) < 1 for value in stalls_ms
    ):
        raise ValueError("injected stall durations must be positive integers")
    stalls_ms = tuple(int(value) for value in stalls_ms)
    identity = collect_environment_identity(REPO_ROOT)
    started_at = _utc_now()
    stamp = (
        started_at.replace("-", "")
        .replace(":", "")
        .replace(".", "")
        .replace("+0000", "Z")
    )
    short_commit = identity["source"].get("git_short_commit") or "nogit"
    run_dir = Path(output_root).resolve() / WORKLOAD_ID / f"{stamp}_{short_commit}"
    run_dir.mkdir(parents=True, exist_ok=False)
    report = _base_report(
        identity=identity,
        started_at=started_at,
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
        stalls_ms=stalls_ms,
        heartbeat_interval_ms=heartbeat_interval_ms,
        stack_capture_ms=stack_capture_ms,
        observer_interval_ms=observer_interval_ms,
        resource_interval_ms=resource_interval_ms,
    )
    overall_started = time.perf_counter_ns()
    measured: list[dict[str, Any]] = []
    exit_code = 0

    try:
        if identity["environment"]["qt"]["binding"] != "real":
            raise RuntimeError(
                "real PySide6 is required for the Qt event-loop probe; "
                f"found {identity['environment']['qt']['binding']}"
            )
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        for index in range(warmup_runs + measured_runs):
            result = _run_probe_iteration(
                app,
                stalls_ms=stalls_ms,
                heartbeat_interval_ms=heartbeat_interval_ms,
                stack_capture_ms=stack_capture_ms,
                observer_interval_ms=observer_interval_ms,
                resource_interval_ms=resource_interval_ms,
            )
            if index >= warmup_runs:
                result["run_index"] = index - warmup_runs + 1
                measured.append(result)
        report["metrics"]["responsiveness"] = {
            "status": "measured",
            "values": _aggregate_responsiveness(measured),
        }
        report["metrics"]["resources"] = _aggregate_resources(measured)
    except ProbeCorrectnessError as exc:
        exit_code = 2
        report["classification"] = {
            "status": "fail",
            "threshold_maturity": "informational",
            "reasons": [f"{type(exc).__name__}: {exc}"],
        }
        report["artifacts"]["failure_traceback"] = "failure_traceback.txt"
        (run_dir / "failure_traceback.txt").write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )
    except Exception as exc:
        exit_code = 3
        report["classification"] = {
            "status": "fail",
            "threshold_maturity": "informational",
            "reasons": [f"{type(exc).__name__}: {exc}"],
        }
        report["artifacts"]["failure_traceback"] = "failure_traceback.txt"
        (run_dir / "failure_traceback.txt").write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )
    finally:
        report["run"]["ended_at_utc"] = _utc_now()
        report["run"]["duration_ms"] = (
            time.perf_counter_ns() - overall_started
        ) / 1_000_000.0

    report_path = run_dir / "report.json"
    try:
        write_report_atomic(report_path, report)
        _write_summary(run_dir / "summary.txt", report)
        _write_stack_artifact(run_dir / "stall_stacks.txt", report)
    except Exception:
        (run_dir / "reporting_failure.txt").write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )
        return 3, report_path
    return exit_code, report_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run an offscreen Qt event-loop probe with deliberate stalls and "
            "no application or hardware construction."
        )
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--measured-runs", type=int, default=5)
    parser.add_argument(
        "--inject-stall-ms",
        type=int,
        nargs="+",
        default=list(DEFAULT_STALLS_MS),
    )
    parser.add_argument("--heartbeat-ms", type=int, default=10)
    parser.add_argument("--stack-capture-ms", type=float, default=250.0)
    parser.add_argument("--observer-ms", type=int, default=5)
    parser.add_argument("--resource-ms", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        exit_code, report_path = run_probe(
            output_root=args.output_root,
            warmup_runs=args.warmup_runs,
            measured_runs=args.measured_runs,
            stalls_ms=tuple(args.inject_stall_ms),
            heartbeat_interval_ms=args.heartbeat_ms,
            stack_capture_ms=args.stack_capture_ms,
            observer_interval_ms=args.observer_ms,
            resource_interval_ms=args.resource_ms,
        )
    except (OSError, ValueError) as exc:
        print(f"Qt probe setup failed: {exc}", file=sys.stderr)
        return 3
    print(report_path)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
