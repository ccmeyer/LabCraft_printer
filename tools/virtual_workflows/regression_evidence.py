"""Optional regression-grade evidence for composed print-array journeys."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from tools.virtual_workflows.assertions import (
    AssertionResult,
    regression_evidence_assertions,
    synthetic_calibration_contract,
)
from tools.virtual_workflows.execution_observer import ExecutionObserver
from tools.virtual_workflows.metrics import (
    NamedPhaseRecorder,
    ProcessResourceSampler,
    QtEventLoopProbe,
    summarize_samples,
)
from tools.virtual_workflows.progress_snapshot import non_durable_progress_samples


def active_pressure_render_intervals_ms(
    samples: list[Mapping[str, Any]],
) -> tuple[list[float], int]:
    """Return only adjacent render intervals within one active stock pass."""

    intervals: list[float] = []
    excluded_boundaries = 0
    for left, right in zip(samples, samples[1:]):
        if left.get("pass_index") != right.get("pass_index"):
            excluded_boundaries += 1
            continue
        intervals.append(
            (int(right["timestamp_ns"]) - int(left["timestamp_ns"]))
            / 1_000_000.0
        )
    return intervals, excluded_boundaries


def _result(
    assertion_id: str,
    passed: bool,
    evidence: Mapping[str, Any],
    sources: tuple[str, ...],
    *,
    checkpoint: str = "terminal",
) -> AssertionResult:
    return AssertionResult(
        assertion_id=assertion_id,
        checkpoint=checkpoint,
        decision="pass" if passed else "fail",
        observable_sources=sources,
        evidence=dict(evidence),
        message=None if passed else "regression evidence did not satisfy the contract",
    )


class RegressionEvidenceProfile:
    """Install, snapshot, and restore optional 96-well diagnostics."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.context = runtime.context
        self.config = runtime.harness.config
        expected_count = int(
            runtime.fixture.get("workload", {}).get(
                "completion_count", len(runtime.observations["expected_wells"])
            )
        )
        self.expected_count = expected_count
        self.phases = NamedPhaseRecorder(max_records=max(50_000, expected_count * 24))
        self.resources = ProcessResourceSampler(max_samples=100_000)
        self.probe = QtEventLoopProbe(
            heartbeat_interval_ms=10,
            stack_capture_ms=250.0,
            observer_interval_ms=5,
            resource_interval_ms=100,
            phase_recorder=self.phases,
            resource_sampler=self.resources,
        )
        self.observer: ExecutionObserver | None = None
        self.command_lifecycle_counts: Counter[str] = Counter()
        self.command_event_count = 0
        self.minimum_queue_depth: int | None = None
        self.maximum_queue_depth: int | None = None
        self.starvation_events: list[dict[str, Any]] = []
        self.pressure_update_signal_count = 0
        self.pressure_render_samples: list[dict[str, int]] = []
        self.paint_event_count = 0
        self._paint_filter: Any = None
        self._connections: list[tuple[Any, Any]] = []
        self._installed = False
        self._restored = False
        self._snapshot: dict[str, Any] | None = None
        self.pi_evidence = self._validate_pi_evidence()

    def _validate_pi_evidence(self) -> dict[str, Any]:
        preflight_path = self.config.pi_preflight_path
        proof_path = self.config.pi_hardware_proof_path
        if preflight_path is None and proof_path is None:
            return {"applicable": False, "validated": True}
        if preflight_path is None or proof_path is None:
            raise ValueError("Pi preflight and hardware proof must be provided together")

        from tools.virtual_workflows.pi_sil import (
            load_and_validate_pi_evidence,
            pi_report_identity,
        )
        from tools.virtual_workflows.report import collect_environment_identity

        identity = collect_environment_identity(Path(__file__).resolve().parents[2])
        qt_platform = str(identity["environment"]["qt"].get("platform") or "")
        preflight, proof = load_and_validate_pi_evidence(
            preflight_path,
            proof_path,
            expected_qt_platform=qt_platform,
        )
        if identity["source"].get("git_commit") != preflight.get("source_commit"):
            raise ValueError("Pi SIL preflight source commit does not match the scenario source")
        for field in (
            "operating_system",
            "architecture",
            "python_version",
            "python_executable",
        ):
            if identity["environment"].get(field) != preflight.get(field):
                raise ValueError(f"Pi SIL preflight {field} does not match the scenario process")
        environment, safety = pi_report_identity(preflight, proof, proof_path)
        self.runtime.harness.report_identity = {
            "run_mode": f"{qt_platform}_pi_sil",
            "target_pi": environment,
            "pi_sil": safety,
        }
        return {
            "applicable": True,
            "validated": True,
            "preflight_path": str(Path(preflight_path).resolve()),
            "hardware_proof_path": str(Path(proof_path).resolve()),
            "environment": environment,
            "safety": safety,
        }

    def pi_assertion(self) -> AssertionResult:
        return _result(
            "sil.pi_evidence_valid",
            bool(self.pi_evidence.get("validated")),
            self.pi_evidence,
            ("harness",),
            checkpoint="startup",
        )

    def _connect(self, signal: Any, slot: Any) -> None:
        signal.connect(slot)
        self._connections.append((signal, slot))

    def install(self) -> None:
        if self._installed:
            raise RuntimeError("regression evidence profile is already installed")
        context = self.context
        completed = self.runtime.observations["completed_wells"]
        experiment_dir = Path(context.experiment_model.experiment_dir_path)

        def pressure_rendered() -> None:
            if context.controller.get_array_run_state() == "running":
                current_pass = self.runtime.observations.get("current_pass") or {}
                self.pressure_render_samples.append(
                    {
                        "timestamp_ns": time.perf_counter_ns(),
                        "pass_index": int(current_pass.get("index", -1)),
                    }
                )

        self.observer = ExecutionObserver(
            context,
            experiment_dir=experiment_dir,
            completed_count=lambda: len(completed),
            phase_recorder=self.phases,
            inject_ms=self.config.inject_ui_stall_ms,
            inject_after_completion=self.config.inject_after_completion,
            pressure_rendered=pressure_rendered,
            pass_context=lambda: {
                "pass_index": int(self.runtime.observations.get("current_pass", {}).get("index", -1)) + 1,
                "stock_id": self.runtime.observations.get("current_pass", {}).get("stock_id"),
            } if int(self.runtime.observations.get("current_pass", {}).get("index", -1)) >= 0 else None,
            max_phase_records=max(50_000, self.expected_count * 24),
        )
        self.observer.install()

        def on_command(payload: Mapping[str, Any]) -> None:
            item = dict(payload)
            self.command_event_count += 1
            self.command_lifecycle_counts[str(item.get("event"))] += 1
            depth = int(item.get("queue_depth", 0))
            self.minimum_queue_depth = (
                depth if self.minimum_queue_depth is None else min(self.minimum_queue_depth, depth)
            )
            self.maximum_queue_depth = (
                depth if self.maximum_queue_depth is None else max(self.maximum_queue_depth, depth)
            )

        def on_queue_drained() -> None:
            state = context.controller.get_array_run_state()
            if state == "running" and len(completed) < self.expected_count:
                self.starvation_events.append(
                    {
                        "completed_count": len(completed),
                        "array_state": state,
                    }
                )

        def on_pressure_update() -> None:
            self.pressure_update_signal_count += 1

        self._connect(context.machine.command_lifecycle_changed, on_command)
        self._connect(context.machine.command_queue.commands_completed, on_queue_drained)
        self._connect(context.model.machine_model.pressure_updated, on_pressure_update)

        from PySide6 import QtCore, QtWidgets

        profile = self

        class PaintFilter(QtCore.QObject):
            def eventFilter(self, watched, event):
                if event.type() == QtCore.QEvent.Type.Paint:
                    root = context.view.well_plate_widget
                    if watched is root or (
                        isinstance(watched, QtWidgets.QWidget)
                        and root.isAncestorOf(watched)
                    ):
                        profile.paint_event_count += 1
                return False

        self._paint_filter = PaintFilter(context.app)
        context.app.installEventFilter(self._paint_filter)
        self.probe.start(context.app)
        context.probe = self.probe
        context.probe_started = True
        self._installed = True

    def restore(self) -> None:
        if self._restored:
            return
        errors: list[BaseException] = []
        try:
            self.probe.stop()
        except BaseException as exc:
            errors.append(exc)
        if self.observer is not None:
            try:
                self.observer.restore()
            except BaseException as exc:
                errors.append(exc)
        for signal, slot in reversed(self._connections):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._connections.clear()
        if self._paint_filter is not None:
            try:
                self.context.app.removeEventFilter(self._paint_filter)
            except (RuntimeError, TypeError):
                pass
        self._restored = True
        self._installed = False
        self._snapshot = self._build_snapshot()
        self._write_stall_stacks(self._snapshot["responsiveness"])
        if errors:
            raise RuntimeError(
                "regression evidence restoration failed: "
                + "; ".join(str(error) for error in errors)
            )

    def _write_stall_stacks(self, responsiveness: Mapping[str, Any]) -> None:
        captures = responsiveness.get("stack_captures", ())
        lines: list[str] = []
        for index, capture in enumerate(captures, start=1):
            phase = (capture.get("phase") or {}).get("name") or "unattributed"
            lines.extend((f"=== capture {index}: {phase} ===", str(capture.get("stack") or "")))
        (self.runtime.harness.report_dir / "stall_stacks.txt").write_text(
            "\n".join(lines) + ("\n" if lines else ""),
            encoding="utf-8",
        )

    def _build_snapshot(self) -> dict[str, Any]:
        observer = self.observer.snapshot() if self.observer is not None else {}
        responsiveness = self.probe.snapshot()
        progress = dict(observer.get("progress_snapshot") or {})
        durable = dict(observer.get("durable_io_samples_ms") or {})
        records = responsiveness.get("phase_timings", {}).get("records", ())
        progress_total = [
            float(row["duration_ms"])
            for row in records
            if row.get("name") == "persistence.write_progress"
        ]
        fsync = durable.get("fsync", {}).get("persistence.write_progress", [])
        replace = durable.get("atomic_replace", {}).get("persistence.write_progress", [])
        try:
            progress["non_durable_write_samples_ms"] = non_durable_progress_samples(
                progress_total, fsync, replace
            )
        except ValueError as exc:
            progress["non_durable_write_samples_ms"] = []
            progress["sample_alignment_error"] = str(exc)
        progress["duration_statistics_ms"] = {
            name: summarize_samples(samples, bands_ms=())
            for name, samples in progress.get("duration_samples_ms", {}).items()
        }
        progress["serialized_size_statistics_bytes"] = summarize_samples(
            progress.get("serialized_size_bytes", ()), bands_ms=()
        )
        progress["non_durable_write_ms"] = summarize_samples(
            progress.get("non_durable_write_samples_ms", ()), bands_ms=()
        )

        phase_values = responsiveness.get("phase_timings", {}).get(
            "duration_by_name_ms", {}
        )
        reads = dict(observer.get("authoritative_reads") or {})
        hot_phases = {
            "persistence.begin_intent",
            "persistence.attach_sequence",
            "persistence.write_progress",
            "persistence.complete_intent",
            "persistence.guard_bundle",
            "persistence.save_resume",
            "persistence.reconcile_cache",
        }
        hot_reads = sum(
            int(values.get("count", 0))
            for phase, paths in reads.get("by_phase", {}).items()
            if phase in hot_phases
            for values in paths.values()
        )

        def durable_count(operation: str, phase: str) -> int:
            return len(durable.get(operation, {}).get(phase, ()))

        authoritative_io = {
            "read_opens": reads,
            "hot_path_read_count": hot_reads,
            "execution_resume_hot_path_disk_load_count": sum(
                int(values.get("count", 0))
                for phase, paths in reads.get("by_phase", {}).items()
                if phase in hot_phases
                for path, values in paths.items()
                if path == "execution_resume.json"
            ),
            "resume_save_fsync_count": durable_count("fsync", "persistence.save_resume"),
            "resume_save_replace_count": durable_count("atomic_replace", "persistence.save_resume"),
            "progress_write_fsync_count": durable_count("fsync", "persistence.write_progress"),
            "progress_write_replace_count": durable_count("atomic_replace", "persistence.write_progress"),
            "observer_restored": bool(reads.get("observer_restored")),
        }
        injected_events = [
            row
            for row in responsiveness.get("stall_events", ())
            if (row.get("phase") or {}).get("name") == "injected_ui_stall"
        ]
        injected_stacks = [
            row
            for row in responsiveness.get("stack_captures", ())
            if (row.get("phase") or {}).get("name") == "injected_ui_stall"
        ]
        requested = self.config.inject_ui_stall_ms > 0
        detected = bool(
            injected_events
            and max(float(row.get("event_loop_gap_ms", 0.0)) for row in injected_events)
            >= self.config.inject_ui_stall_ms * 0.60
        )
        injected = {
            "requested": requested,
            "requested_duration_ms": self.config.inject_ui_stall_ms,
            "after_completion": self.config.inject_after_completion,
            "detected": detected,
            "stack_captured": bool(injected_stacks),
            "decision": (
                "detected" if requested and detected and injected_stacks
                else "missing" if requested else "not_requested"
            ),
        }
        pressure = phase_values.get("ui.pressure_render", {})
        intervals, excluded_boundaries = active_pressure_render_intervals_ms(
            self.pressure_render_samples
        )
        responsiveness["well_plate_paint_event_count"] = self.paint_event_count
        responsiveness["pressure_render_assessment"] = {
            "update_signal_count": self.pressure_update_signal_count,
            "render_count": int(pressure.get("count", 0)),
            "coalesced_update_count": max(
                0, self.pressure_update_signal_count - int(pressure.get("count", 0))
            ),
            "render_interval_ms": int(
                self.context.view.pressure_box._pressure_render_timer.interval()
            ),
            "timer_active_after_teardown": False,
            "excluded_inactive_pass_boundary_count": excluded_boundaries,
            "duration_ms": pressure,
            "active_render_interval_ms": summarize_samples(
                intervals, bands_ms=(250.0, 1000.0)
            ),
        }
        responsiveness["injected_stall_assessment"] = injected
        return {
            "installed": self._installed,
            "restored": self._restored,
            "observer": {**observer, "progress_snapshot": progress},
            "responsiveness": responsiveness,
            "resources": self.resources.snapshot(),
            "authoritative_io": authoritative_io,
            "queue": {
                "lifecycle_event_count": self.command_event_count,
                "lifecycle_counts": dict(sorted(self.command_lifecycle_counts.items())),
                "minimum_queue_depth": self.minimum_queue_depth or 0,
                "maximum_queue_depth": self.maximum_queue_depth or 0,
                "unexpected_starvation_count": len(self.starvation_events),
                "unexpected_starvation_events": list(self.starvation_events),
            },
            "injected_stall_assessment": injected,
            "calibration_contract": synthetic_calibration_contract(
                self.runtime.fixture,
                self.context.action_results,
                expected_pulse_widths_us=tuple(
                    self.runtime.observations.get("expected_pulse_widths_us", ())
                ),
            ),
            "pi_evidence": dict(self.pi_evidence),
        }

    def snapshot(self) -> dict[str, Any]:
        return dict(self._snapshot or self._build_snapshot())

    def terminal_assertions(self) -> tuple[AssertionResult, ...]:
        return regression_evidence_assertions(
            expected_well_ids=tuple(self.runtime.observations["expected_wells"]),
            completed_well_ids=tuple(
                self.runtime.observations["completed_wells"]
            ),
            snapshot=self.snapshot(),
        )


__all__ = ["RegressionEvidenceProfile"]
