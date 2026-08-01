"""Idempotent Qt signal observation for SIL state evidence."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable
import warnings

from PySide6 import QtCore

from .state_recorder import StateRecorder


class SimulationStateObserver(QtCore.QObject):
    """Observe existing signals without changing application behavior."""

    def __init__(
        self,
        *,
        recorder: StateRecorder,
        projector,
        machine,
        controller,
        model,
        on_failure: Callable[[str], None] | None = None,
        action_id_provider: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__()
        self.recorder = recorder
        self.projector = projector
        self.machine = machine
        self.controller = controller
        self.model = model
        self._on_failure = on_failure
        self._action_id_provider = action_id_provider
        self._connections: list[tuple[Any, Callable[..., Any]]] = []
        self._installed = False
        self._reconcile_scheduled = False
        self._pending_reasons: list[str] = []
        self._pending_include_persistence = False
        self._pending_persist = False
        self._last_simulator_state: dict[str, Any] | None = None
        self._last_command_id: str | None = None

    @property
    def installed(self) -> bool:
        return self._installed

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def _connect(self, owner: Any, signal_name: str, slot: Callable[..., Any]) -> None:
        signal = getattr(owner, signal_name, None)
        if signal is None or not hasattr(signal, "connect"):
            return
        signal.connect(slot)
        self._connections.append((signal, slot))

    def install(self) -> bool:
        if self._installed:
            return False
        if not self.recorder.healthy:
            return False

        self._connect(self.machine, "state_changed", self._on_simulator_state)
        self._connect(
            self.machine,
            "command_lifecycle_changed",
            self._on_command_lifecycle,
        )
        self._connect(
            self.machine,
            "machine_connected_signal",
            self._on_connection_changed,
        )
        self._connect(self.machine, "error_occurred", self._on_simulator_error)
        self._connect(self.machine, "simulation_faulted", self._on_simulator_fault)

        self._connect(
            self.controller,
            "array_state_changed",
            self._on_array_state_changed,
        )
        self._connect(
            self.controller,
            "error_occurred_signal",
            self._on_controller_error,
        )
        self._connect(
            self.controller,
            "transport_fault_ui_signal",
            self._on_controller_transport_fault,
        )

        self._connect(self.model, "experiment_loaded", self._on_experiment_loaded)
        machine_model = getattr(self.model, "machine_model", None)
        for signal_name in (
            "machine_state_updated",
            "motor_state_changed",
            "regulation_state_changed",
            "gripper_state_changed",
            "command_numbers_updated",
            "machine_paused",
            "home_status_signal",
            "printing_parameters_updated",
        ):
            self._connect(machine_model, signal_name, self._on_model_machine_changed)

        rack = getattr(self.model, "rack_model", None)
        self._connect(rack, "slot_updated", self._on_rack_changed)
        self._connect(rack, "gripper_updated", self._on_rack_changed)

        experiment = getattr(self.model, "experiment_model", None)
        self._connect(
            experiment,
            "applied_imaging_calibration_changed",
            self._on_calibration_changed,
        )
        self._connect(
            experiment,
            "manual_refuel_check_changed",
            self._on_refuel_changed,
        )

        self._installed = True
        self.schedule_reconciliation("observer_installed")
        return True

    def dispose(self) -> bool:
        if not self._installed and not self._connections:
            return False
        self._installed = False
        self._reconcile_scheduled = False
        self._pending_reasons.clear()
        for signal, slot in reversed(self._connections):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._connections.clear()
        return True

    def _simulated_elapsed_ms(self) -> int | None:
        try:
            return int(self.machine.state.simulated_elapsed_ms)
        except Exception:
            return None

    def _action_correlation(self) -> dict[str, str]:
        if self._action_id_provider is None:
            return {}
        try:
            action_id = self._action_id_provider()
        except Exception:
            action_id = None
        return {"action_id": action_id} if action_id else {}

    def _record(self, event_kind: str, source_layer: str, **kwargs: Any) -> bool:
        if not self._installed and event_kind != "observer_installed":
            return False
        try:
            self.recorder.record_event(
                event_kind,
                source_layer=source_layer,
                simulated_elapsed_ms=self._simulated_elapsed_ms(),
                **kwargs,
            )
            return True
        except Exception as exc:
            self._handle_failure(f"state observer could not record {event_kind}: {exc}")
            return False

    def _handle_failure(self, reason: str) -> None:
        if not self.recorder.failed:
            self.recorder.fail(reason)
        self.dispose()
        if self._on_failure is not None:
            try:
                self._on_failure(reason)
            except Exception:
                pass

    def schedule_reconciliation(
        self,
        reason: str,
        *,
        include_persistence: bool = False,
        persist: bool = False,
    ) -> None:
        if not self._installed:
            return
        reason_text = str(reason or "state_changed")
        if reason_text not in self._pending_reasons:
            self._pending_reasons.append(reason_text)
        self._pending_include_persistence = (
            self._pending_include_persistence or include_persistence
        )
        self._pending_persist = self._pending_persist or persist
        if self._reconcile_scheduled:
            return
        self._reconcile_scheduled = True
        QtCore.QTimer.singleShot(0, self._run_reconciliation)

    def _run_reconciliation(self) -> None:
        if not self._installed:
            return
        reasons = list(self._pending_reasons) or ["state_changed"]
        include_persistence = self._pending_include_persistence
        persist = self._pending_persist
        self._pending_reasons.clear()
        self._pending_include_persistence = False
        self._pending_persist = False
        self._reconcile_scheduled = False
        reason = "+".join(reasons)
        try:
            projection = self.projector.capture(
                reason=reason,
                include_persistence=include_persistence,
            )
            self.recorder.record_snapshot(
                projection,
                reason=reason,
                event_kind=("snapshot_exported" if persist else "projection_reconciled"),
                source_layer="observer",
                correlation=(
                    {"command_id": self._last_command_id}
                    if self._last_command_id
                    else self._action_correlation()
                ),
                simulated_elapsed_ms=self._simulated_elapsed_ms(),
                persist=persist,
            )
        except Exception as exc:
            self._handle_failure(f"cross-layer projection failed: {exc}")

    @staticmethod
    def _state_dict(state: Any) -> dict[str, Any]:
        if is_dataclass(state):
            return asdict(state)
        if isinstance(state, dict):
            return dict(state)
        return {"type": type(state).__name__}

    @QtCore.Slot(object)
    def _on_simulator_state(self, state: Any) -> None:
        current = self._state_dict(state)
        before = self._last_simulator_state
        changed_before = None
        changed_after = None
        if before is not None:
            keys = sorted(set(before) | set(current))
            changed = [key for key in keys if before.get(key) != current.get(key)]
            changed_before = {key: before.get(key) for key in changed}
            changed_after = {key: current.get(key) for key in changed}
        self._last_simulator_state = current
        correlation = (
            {"command_id": self._last_command_id}
            if self._last_command_id
            else self._action_correlation()
        )
        self._record(
            "simulator_state_changed",
            "simulator",
            before=changed_before,
            after=changed_after,
            payload={"changed_fields": sorted((changed_after or {}).keys())},
            correlation=correlation,
        )
        self.schedule_reconciliation("simulator_state_changed")

    @QtCore.Slot(dict)
    def _on_command_lifecycle(self, payload: dict[str, Any]) -> None:
        values = dict(payload or {})
        number = values.get("command_number")
        command_id = (
            f"{self.recorder.application_session_id}:command-{int(number):06d}"
            if number is not None
            else None
        )
        if command_id is not None:
            self._last_command_id = command_id
        correlation = {"command_id": command_id} if command_id else {}
        correlation.update(self._action_correlation())
        self._record(
            "simulator_command_lifecycle",
            "simulator",
            payload=values,
            correlation=correlation,
        )
        self.schedule_reconciliation("simulator_command_lifecycle")

    @QtCore.Slot(bool)
    def _on_connection_changed(self, connected: bool) -> None:
        self._record(
            "simulator_connection_changed",
            "simulator",
            payload={"connected": bool(connected)},
            correlation=self._action_correlation(),
        )
        self.schedule_reconciliation("connection_changed")

    @QtCore.Slot(str)
    def _on_simulator_error(self, message: str) -> None:
        self._record(
            "controller_error",
            "simulator",
            payload={"message": str(message)},
            correlation=self._action_correlation(),
        )
        self.schedule_reconciliation("simulator_error")

    @QtCore.Slot(object)
    def _on_simulator_fault(self, payload: Any) -> None:
        self._record(
            "simulator_fault",
            "simulator",
            payload=payload,
            correlation=(
                {"command_id": self._last_command_id}
                if self._last_command_id
                else self._action_correlation()
            ),
        )
        self.schedule_reconciliation("simulator_fault")

    @QtCore.Slot(str)
    def _on_array_state_changed(self, state: str) -> None:
        self._record(
            "controller_array_state_changed",
            "controller",
            payload={"array_state": str(state)},
        )
        self.schedule_reconciliation("array_state_changed")

    @QtCore.Slot(str, str)
    def _on_controller_error(self, title: str, message: str) -> None:
        self._record(
            "controller_error",
            "controller",
            payload={"title": str(title), "message": str(message)},
        )
        self.schedule_reconciliation("controller_error")

    @QtCore.Slot(object)
    def _on_controller_transport_fault(self, payload: Any) -> None:
        self._record(
            "controller_transport_fault",
            "controller",
            payload=payload,
        )
        self.schedule_reconciliation("controller_transport_fault")

    @QtCore.Slot()
    def _on_experiment_loaded(self) -> None:
        self._record("model_experiment_loaded", "experiment", payload={})
        self.schedule_reconciliation(
            "experiment_loaded",
            include_persistence=True,
            persist=True,
        )

    @QtCore.Slot()
    def _on_model_machine_changed(self, *args: Any) -> None:
        self._record(
            "model_machine_state_changed",
            "model",
            payload={"signal_values": list(args)},
            correlation=(
                {"command_id": self._last_command_id}
                if self._last_command_id
                else self._action_correlation()
            ),
        )
        self.schedule_reconciliation("model_machine_state_changed")

    @QtCore.Slot()
    def _on_rack_changed(self, *args: Any) -> None:
        self._record(
            "rack_state_changed",
            "rack_head",
            payload={"signal_values": list(args)},
        )
        self.schedule_reconciliation("rack_state_changed")

    @QtCore.Slot(object)
    def _on_calibration_changed(self, payload: Any) -> None:
        self._record(
            "calibration_state_changed",
            "calibration",
            payload=payload,
        )
        self.schedule_reconciliation(
            "calibration_state_changed",
            include_persistence=True,
        )

    @QtCore.Slot(object)
    def _on_refuel_changed(self, payload: Any) -> None:
        self._record(
            "refuel_check_changed",
            "refuel_check",
            payload=payload,
        )
        self.schedule_reconciliation(
            "refuel_check_changed",
            include_persistence=True,
        )
