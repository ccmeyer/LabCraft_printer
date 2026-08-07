"""Bounded, restorative execution evidence for composed SIL journeys."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from tools.virtual_workflows.metrics import NamedPhaseRecorder
from tools.virtual_workflows.persistence_io import PersistenceIoObserver
from tools.virtual_workflows.progress_snapshot import ProgressSnapshotObserver


class ExecutionObserver:
    """Observe authoritative execution without advancing or repairing it."""

    def __init__(
        self,
        context: Any,
        *,
        experiment_dir: str | Path,
        completed_count: Callable[[], int],
        pass_context: Callable[[], Mapping[str, Any] | None] | None = None,
        phase_recorder: NamedPhaseRecorder | None = None,
        inject_ms: int = 0,
        inject_after_completion: int = 1,
        pressure_rendered: Callable[[], None] | None = None,
        max_phase_records: int = 50_000,
    ) -> None:
        self.context = context
        self.phases = phase_recorder or NamedPhaseRecorder(
            max_records=max_phase_records
        )
        self.io = PersistenceIoObserver(experiment_dir)
        self.progress = ProgressSnapshotObserver(context.experiment_model)
        self.completed_count = completed_count
        self.pass_context = pass_context or (lambda: None)
        self.inject_ms = int(inject_ms)
        self.inject_after_completion = int(inject_after_completion)
        self.pressure_rendered = pressure_rendered
        self.instrumentation: Any = None
        self._installed = False
        self._restored = False

    def install(self) -> None:
        if self._installed:
            raise RuntimeError("execution observer is already installed")
        from tools.virtual_workflows.scenarios import _install_instrumentation

        self.instrumentation = _install_instrumentation(
            self.phases,
            experiment_model=self.context.experiment_model,
            controller=self.context.controller,
            well_plate_widget=self.context.view.well_plate_widget,
            pressure_plot_widget=self.context.view.pressure_box,
            experiment_task_list=self.context.view.experiment_task_list,
            inject_ms=self.inject_ms,
            inject_after_completion=self.inject_after_completion,
            completed_count=self.completed_count,
            io_observer=self.io,
            pressure_rendered=self.pressure_rendered,
            pass_context=lambda: dict(self.pass_context() or {}),
        )
        try:
            self.progress.install()
            self.io.install()
        except BaseException:
            self.restore()
            raise
        self.context.instrumentation = self.instrumentation
        self.context.io_observer = self.io
        self.context.progress_observer = self.progress
        self._installed = True

    def restore(self) -> None:
        if self._restored:
            return
        errors: list[BaseException] = []
        for item in (self.progress, self.io, self.instrumentation):
            if item is None:
                continue
            try:
                item.restore()
            except BaseException as exc:  # restoration must attempt every hook
                errors.append(exc)
        self._restored = True
        self._installed = False
        if errors:
            raise RuntimeError(
                "execution observer restoration failed: "
                + "; ".join(str(error) for error in errors)
            )

    def snapshot(self) -> dict[str, Any]:
        lifecycle = (
            self.instrumentation.lifecycle_snapshot()
            if self.instrumentation is not None
            else {
                "begins": [],
                "attachments": [],
                "completions": [],
                "discard_batches": [],
                "checkpoint_observations": [],
                "pass_starts": [],
                "terminal_transitions": [],
                "soft_stop_events": [],
            }
        )
        phase_snapshot = self.phases.snapshot()
        progress = self.progress.snapshot()
        reads = self.io.read_snapshot()
        durable = self.io.snapshot()
        return {
            "installed": self._installed,
            "restored": self._restored,
            "lifecycle": lifecycle,
            "phase_timings": phase_snapshot,
            "progress_snapshot": progress,
            "authoritative_reads": reads,
            "durable_io_samples_ms": durable,
            "authoritative_io_totals": self.io.totals(),
        }


__all__ = ["ExecutionObserver"]
