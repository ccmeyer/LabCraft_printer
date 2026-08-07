"""Bounded, restorative execution evidence for composed SIL journeys."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from tools.virtual_workflows.metrics import NamedPhaseRecorder
from tools.virtual_workflows.persistence_io import PersistenceIoObserver
from tools.virtual_workflows.progress_snapshot import ProgressSnapshotObserver


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _command_evidence(command: Any) -> dict[str, Any]:
    return {
        "command_number": int(getattr(command, "command_number", 0) or 0),
        "command_type": str(getattr(command, "command_type", "") or ""),
        "status": str(getattr(command, "status", "") or ""),
    }


def _intent_evidence(intent: Any) -> dict[str, Any]:
    return {
        "intent_id": str(getattr(intent, "intent_id", "") or ""),
        "well_id": str(getattr(intent, "well_id", "") or ""),
        "stock_id": str(getattr(intent, "stock_id", "") or ""),
        "status": str(getattr(intent, "status", "") or ""),
        "command_seq32": getattr(intent, "command_seq32", None),
    }


def capture_execution_liveness_snapshot(
    context: Any,
    *,
    completed_count: int,
    target_count: int,
    stalled_seconds: float,
    pass_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture bounded state after a no-progress decision without repairing it."""

    controller = getattr(context, "controller", None)
    machine = getattr(context, "machine", None)
    experiment = getattr(context, "experiment_model", None)
    array_context = getattr(controller, "_array_context", None)
    array_context = array_context if isinstance(array_context, dict) else {}
    queued_wells = []
    for item in list(array_context.get("queued_wells") or ())[:2]:
        queued_wells.append(
            {
                key: item.get(key)
                for key in (
                    "well_id",
                    "target_droplets",
                    "dispense_seq32",
                    "execution_intent_id",
                )
            }
        )

    command_queue = getattr(machine, "command_queue", None)
    queue = list(getattr(command_queue, "queue", ()) or ())
    nonterminal = [
        command
        for command in queue
        if str(getattr(command, "status", "")) not in {"Completed", "Canceled"}
    ]
    status_counts: dict[str, int] = {}
    for command in queue:
        status = str(getattr(command, "status", "") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    timer = getattr(machine, "_command_timer", None)
    state = getattr(machine, "state", None)

    plan = None
    plan_error = None
    try:
        getter = getattr(experiment, "get_execution_plan_snapshot", None)
        plan = getter() if callable(getter) else None
    except Exception as exc:  # diagnostic capture must survive partial state
        plan_error = f"{type(exc).__name__}: {exc}"
    sync_error = None
    try:
        getter = getattr(experiment, "get_execution_plan_sync_error", None)
        sync_error = getter() if callable(getter) else None
    except Exception as exc:
        sync_error = f"{type(exc).__name__}: {exc}"

    checkpoint = {"available": False, "state": None, "pending_intents": []}
    checkpoint_path = getattr(experiment, "execution_resume_file_path", None)
    if checkpoint_path:
        try:
            from ExecutionResumeStore import load_execution_resume

            document = load_execution_resume(checkpoint_path)
            pending = [
                intent for intent in document.intents
                if str(getattr(intent, "status", "")) == "pending"
            ]
            checkpoint = {
                "available": True,
                "state": str(document.state),
                "pending_intent_count": len(pending),
                "pending_intents": [_intent_evidence(item) for item in pending[:4]],
            }
        except Exception as exc:
            checkpoint = {
                "available": False,
                "state": None,
                "pending_intents": [],
                "error": f"{type(exc).__name__}: {exc}",
            }

    active_head = None
    try:
        rack = getattr(getattr(context, "model", None), "rack_model", None)
        getter = getattr(rack, "get_gripper_printer_head", None)
        active_head = getter() if callable(getter) else None
    except Exception:
        active_head = None
    resolved_pass = dict(pass_context or {})
    if active_head is not None:
        resolved_pass.setdefault(
            "head_id", str(getattr(active_head, "printer_head_id", "") or "")
        )

    probe = getattr(context, "probe", None)
    probe_evidence: dict[str, Any] = {}
    try:
        snapshot = getattr(probe, "snapshot", None)
        if callable(snapshot):
            values = dict(snapshot() or {})
            probe_evidence = {
                key: values.get(key)
                for key in ("maximum_gap_ms", "latest_gap_ms", "current_phase")
                if key in values
            }
    except Exception as exc:
        probe_evidence = {"error": f"{type(exc).__name__}: {exc}"}

    return {
        "progress": {
            "target_count": int(target_count),
            "observed_count": int(completed_count),
            "last_progress_count": int(completed_count),
            "stalled_seconds": float(stalled_seconds),
        },
        "pass": resolved_pass,
        "controller": {
            "array_state": (
                controller.get_array_run_state()
                if callable(getattr(controller, "get_array_run_state", None))
                else None
            ),
            "finalize_reason": array_context.get("finalize_reason"),
            "current_barrier_seq32": array_context.get("current_barrier_seq32"),
            "queued_wells": queued_wells,
        },
        "simulator": {
            "connected": bool(getattr(state, "connected", False)),
            "transport_paused": bool(getattr(state, "transport_paused", False)),
            "sequence_paused": bool(getattr(machine, "_sequence_pause", False)),
            "completing": bool(getattr(machine, "_completing", False)),
            "command_timer_active": bool(
                callable(getattr(timer, "isActive", None)) and timer.isActive()
            ),
            "command_timer_remaining_ms": (
                int(timer.remainingTime())
                if callable(getattr(timer, "remainingTime", None)) else None
            ),
            "active_command": (
                _command_evidence(getattr(machine, "_active_command"))
                if getattr(machine, "_active_command", None) is not None else None
            ),
            "queue_depth": len(nonterminal),
            "queue_status_counts": status_counts,
            "nonterminal_commands": [
                _command_evidence(item) for item in nonterminal[:4]
            ],
            "counters": {
                name: int(getattr(state, name, 0) or 0)
                for name in (
                    "current_command",
                    "last_completed",
                    "last_accepted",
                    "last_retired",
                )
            },
        },
        "execution": {
            "plan_state": str(_enum_value(getattr(plan, "state", "")) or ""),
            "plan_revision": getattr(plan, "revision", None),
            "plan_error": plan_error,
            "sync_error": str(sync_error) if sync_error else None,
            "checkpoint": checkpoint,
        },
        "event_loop": probe_evidence,
    }


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


__all__ = ["ExecutionObserver", "capture_execution_liveness_snapshot"]
