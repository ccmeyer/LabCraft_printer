"""Reusable, bounded actions for hardware-isolated SIL scenarios."""

from __future__ import annotations

import json
import math
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping


PRINT_ARRAY_ACTION_IDS = frozenset(
    {
        "fixture.prepare_authoritative",
        "app.launch_simulated",
        "machine.connect_ready",
        "head.stage_virtual",
        "pressure.enable_regulation",
        "array.start_via_ui",
        "array.wait_for_completions",
        "array.wait_for_state",
        "artifact.capture_milestone",
        "validation.terminal_bundle",
        "scenario.teardown",
    }
)

PRINT_ARRAY_LIFECYCLE_ACTION_IDS = PRINT_ARRAY_ACTION_IDS | frozenset(
    {
        "array.request_soft_stop_via_ui",
        "array.observe_stopped_quiescence",
        "validation.paused_bundle",
    }
)

MULTI_STOCK_LIFECYCLE_ACTION_IDS = PRINT_ARRAY_ACTION_IDS | frozenset(
    {
        "validation.stock_pass_boundary",
    }
)

AUTHORITATIVE_RELOAD_ACTION_IDS = (
    PRINT_ARRAY_LIFECYCLE_ACTION_IDS
    | frozenset(
        {
            "app.close_simulated_session",
            "experiment.load_authoritative_via_ui",
            "experiment.activate_authoritative_via_ui",
            "validation.reload_boundary",
        }
    )
)

EDITOR_LIFECYCLE_ACTION_IDS = frozenset(
    {
        "app.launch_simulated",
        "editor.open_via_ui",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        "editor.optimize_generate_via_ui",
        "editor.finish_via_ui",
        "editor.rename_prepared_via_ui",
        "editor.edit_prepared_design_via_ui",
        "editor.regenerate_prepared_design_via_ui",
        "editor.refinalize_prepared_via_ui",
        "experiment.activate_authoritative",
        "execution.lock_for_printing",
        "editor.inspect_active_lock_via_ui",
        "editor.reject_in_place_edit_via_ui",
        "editor.create_editable_copy_via_ui",
        "editor.edit_copy_via_ui",
        "editor.finalize_copy_via_ui",
        "artifact.capture_milestone",
        "validation.prepared_bundle",
        "validation.refinalized_bundle",
        "experiment.reload_authoritative",
        "scenario.teardown",
    }
)
COMPOSED_SMOKE_ACTION_IDS = frozenset(
    {
        "app.launch_simulated",
        "machine.connect_via_ui",
        "machine.enable_motors_via_ui",
        "machine.home_via_ui",
        "machine.configure_print_settings_via_ui",
        "editor.open_via_ui",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        "editor.optimize_generate_via_ui",
        "editor.finish_via_ui",
        "head.set_volume_via_ui",
        "head.stage_via_ui",
        "calibration.open_via_ui",
        "calibration.generate_via_ui",
        "calibration.select_via_ui",
        "calibration.apply_via_ui",
        "pressure.enable_regulation_via_ui",
        "array.start_via_ui",
        "array.wait_for_completions",
        "artifact.capture_milestone",
        "scenario.teardown",
    }
)
COMPOSED_MULTI_STOCK_ACTION_IDS = COMPOSED_SMOKE_ACTION_IDS | frozenset(
    {
        "head.bind_identity",
        "head.return_via_ui",
        "validation.stock_pass_boundary",
    }
)
COMPOSED_SOFT_STOP_ACTION_IDS = COMPOSED_SMOKE_ACTION_IDS | frozenset(
    {
        "array.request_soft_stop_via_ui",
        "array.observe_stopped_quiescence",
        "array.resume_via_ui",
        "array.wait_for_state",
    }
)
ACTION_IDS = (
    AUTHORITATIVE_RELOAD_ACTION_IDS
    | MULTI_STOCK_LIFECYCLE_ACTION_IDS
    | EDITOR_LIFECYCLE_ACTION_IDS
    | COMPOSED_SMOKE_ACTION_IDS
    | COMPOSED_MULTI_STOCK_ACTION_IDS
    | COMPOSED_SOFT_STOP_ACTION_IDS
)


class InteractionSurface(str, Enum):
    """The application layer that one semantic action actually drives."""

    UI = "ui"
    CONTROLLER = "controller"
    MODEL = "model"
    SIMULATOR = "simulator"
    HARNESS = "harness"


ACTION_INTERACTION_SURFACES = {
    action_id: InteractionSurface.HARNESS for action_id in ACTION_IDS
}
ACTION_INTERACTION_SURFACES["head.bind_identity"] = InteractionSurface.MODEL
ACTION_INTERACTION_SURFACES.update(
    {
        "machine.connect_ready": InteractionSurface.SIMULATOR,
        "head.stage_virtual": InteractionSurface.MODEL,
        "pressure.enable_regulation": InteractionSurface.CONTROLLER,
        "array.start_via_ui": InteractionSurface.UI,
        "array.request_soft_stop_via_ui": InteractionSurface.UI,
        "array.resume_via_ui": InteractionSurface.UI,
        "experiment.load_authoritative_via_ui": InteractionSurface.UI,
        "experiment.activate_authoritative_via_ui": InteractionSurface.UI,
        "experiment.activate_authoritative": InteractionSurface.MODEL,
        "execution.lock_for_printing": InteractionSurface.MODEL,
        **{
            action_id: InteractionSurface.UI
            for action_id in EDITOR_LIFECYCLE_ACTION_IDS
            if action_id.startswith("editor.")
        },
        **{
            action_id: InteractionSurface.UI
            for action_id in COMPOSED_MULTI_STOCK_ACTION_IDS
            if action_id.endswith("_via_ui")
        },
    }
)


def _bounded_json_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 8:
        return "<maximum evidence depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key)[:200]: _bounded_json_value(item, depth=depth + 1)
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _bounded_json_value(item, depth=depth + 1)
            for item in list(value)[:100]
        ]
    return str(value)[:2000]


def _json_evidence(value: Mapping[str, Any] | None) -> dict[str, Any]:
    bounded = _bounded_json_value(dict(value or {}))
    assert isinstance(bounded, dict)
    json.dumps(bounded, allow_nan=False)
    return bounded


class ScenarioActionError(RuntimeError):
    """An explicit action failure with bounded diagnostic evidence."""

    def __init__(
        self,
        action_id: str,
        message: str,
        *,
        stage: str,
        evidence: Mapping[str, Any] | None = None,
    ):
        super().__init__(f"{action_id} {stage} failed: {message}")
        self.action_id = action_id
        self.stage = stage
        self.evidence = _json_evidence(evidence)


@dataclass(frozen=True)
class ScenarioDeadline:
    """One monotonic deadline shared by every action in a scenario."""

    timeout_seconds: float
    started_monotonic: float
    clock: Callable[[], float] = field(repr=False, compare=False)

    @classmethod
    def start(
        cls,
        timeout_seconds: float,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> "ScenarioDeadline":
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("scenario timeout must be finite and greater than zero")
        return cls(timeout, float(clock()), clock)

    @property
    def expires_monotonic(self) -> float:
        return self.started_monotonic + self.timeout_seconds

    def elapsed_seconds(self) -> float:
        return max(0.0, float(self.clock()) - self.started_monotonic)

    def remaining_seconds(self, local_timeout_seconds: float | None = None) -> float:
        remaining = max(0.0, self.expires_monotonic - float(self.clock()))
        if local_timeout_seconds is None:
            return remaining
        local = float(local_timeout_seconds)
        if not math.isfinite(local) or local <= 0:
            raise ValueError("action timeout must be finite and greater than zero")
        return min(remaining, local)


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    interaction_surface: str
    status: str
    started_monotonic_ns: int
    ended_monotonic_ns: int
    duration_ms: float
    evidence: Mapping[str, Any]
    failure_stage: str | None = None
    failure_type: str | None = None
    failure_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "interaction_surface": self.interaction_surface,
            "status": self.status,
            "started_monotonic_ns": self.started_monotonic_ns,
            "ended_monotonic_ns": self.ended_monotonic_ns,
            "duration_ms": self.duration_ms,
            "evidence": dict(self.evidence),
            "failure_stage": self.failure_stage,
            "failure_type": self.failure_type,
            "failure_message": self.failure_message,
        }


@dataclass(frozen=True)
class CleanupResult:
    name: str
    status: str
    failure_type: str | None = None
    failure_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "failure_type": self.failure_type,
            "failure_message": self.failure_message,
        }


@dataclass
class ScenarioContext:
    """All mutable test-owned state for exactly one composed SIL run."""

    scenario_id: str
    workload_id: str
    report_dir: Path
    scenario_root: Path
    screenshots_dir: Path
    timeout_seconds: float
    record_event: Callable[..., None]
    clock: Callable[[], float] = field(
        default=time.perf_counter,
        repr=False,
    )
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    deadline: ScenarioDeadline = field(init=False)
    action_results: list[dict[str, Any]] = field(default_factory=list)
    cleanup_results: list[dict[str, Any]] = field(default_factory=list)
    milestones: list[dict[str, Any]] = field(default_factory=list)
    dialogs: list[dict[str, Any]] = field(default_factory=list)
    unexpected_dialogs: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    screenshots: dict[str, Path] = field(default_factory=dict)
    array_states: list[str] = field(default_factory=lambda: ["idle"])
    closed: bool = False

    app: Any = None
    qt_core: Any = None
    components: Any = None
    dependencies: Any = None
    model: Any = None
    machine: Any = None
    controller: Any = None
    view: Any = None
    experiment_model: Any = None
    fixture_info: dict[str, Any] | None = None
    instrumentation: Any = None
    progress_observer: Any = None
    io_observer: Any = None
    probe: Any = None
    probe_started: bool = False
    dialog_timer: Any = None
    paint_filter: Any = None
    stdout_redirect: Any = None
    pressure_timer_active_after_teardown: bool | None = None
    application_session_id: str | None = None
    machine_cleanup: dict[str, Any] = field(
        default_factory=lambda: {
            "command_timer_active": None,
            "connection_timer_active": None,
            "deferred_timer_count": None,
        }
    )

    def __post_init__(self) -> None:
        self.report_dir = Path(self.report_dir).resolve()
        self.scenario_root = Path(self.scenario_root).resolve()
        self.screenshots_dir = Path(self.screenshots_dir).resolve()
        self.deadline = ScenarioDeadline.start(
            self.timeout_seconds,
            clock=self.clock,
        )

    def pump_events(self) -> None:
        if self.app is None:
            return
        if self.qt_core is None:
            self.app.processEvents()
            return
        self.app.processEvents(
            self.qt_core.QEventLoop.ProcessEventsFlag.AllEvents,
            10,
        )


def _record_action(
    context: ScenarioContext,
    *,
    action_id: str,
    interaction_surface: InteractionSurface,
    started_ns: int,
    status: str,
    evidence: Mapping[str, Any] | None = None,
    failure: BaseException | None = None,
    failure_stage: str | None = None,
) -> dict[str, Any]:
    ended_ns = time.perf_counter_ns()
    result = ActionResult(
        action_id=action_id,
        interaction_surface=interaction_surface.value,
        status=status,
        started_monotonic_ns=started_ns,
        ended_monotonic_ns=ended_ns,
        duration_ms=(ended_ns - started_ns) / 1_000_000.0,
        evidence=MappingProxyType(_json_evidence(evidence)),
        failure_stage=failure_stage,
        failure_type=type(failure).__name__ if failure is not None else None,
        failure_message=str(failure)[:2000] if failure is not None else None,
    ).to_dict()
    if context.application_session_id is not None:
        result["application_session_id"] = context.application_session_id
    context.action_results.append(result)
    context.record_event(
        "action_completed",
        action_id=action_id,
        interaction_surface=interaction_surface.value,
        status=status,
        duration_ms=result["duration_ms"],
        failure_stage=failure_stage,
        **(
            {"application_session_id": context.application_session_id}
            if context.application_session_id is not None
            else {}
        ),
    )
    return result


def execute_action(
    context: ScenarioContext,
    action_id: str,
    operation: Callable[[], Mapping[str, Any] | None],
    *,
    precondition: Callable[[], tuple[bool, str, Mapping[str, Any] | None]]
    | None = None,
    enforce_deadline: bool = True,
    interaction_surface: InteractionSurface | str | None = None,
) -> dict[str, Any]:
    """Execute one explicit Python action and append exactly one result."""

    if action_id not in ACTION_IDS:
        raise ValueError(f"unknown SIL action ID: {action_id!r}")
    if interaction_surface is None:
        surface = ACTION_INTERACTION_SURFACES[action_id]
    else:
        surface = InteractionSurface(interaction_surface)
    if context.closed:
        raise ScenarioActionError(
            action_id,
            "scenario context is already closed",
            stage="precondition",
        )
    started_ns = time.perf_counter_ns()
    context.record_event(
        "action_started",
        action_id=action_id,
        **(
            {"application_session_id": context.application_session_id}
            if context.application_session_id is not None
            else {}
        ),
    )
    try:
        if enforce_deadline and context.deadline.remaining_seconds() <= 0:
            raise ScenarioActionError(
                action_id,
                "scenario deadline is exhausted",
                stage="timeout",
                evidence={"elapsed_seconds": context.deadline.elapsed_seconds()},
            )
        if precondition is not None:
            passed, message, evidence = precondition()
            if not passed:
                raise ScenarioActionError(
                    action_id,
                    message,
                    stage="precondition",
                    evidence=evidence,
                )
        evidence = _json_evidence(operation())
    except Exception as exc:
        action_error = (
            exc
            if isinstance(exc, ScenarioActionError)
            else ScenarioActionError(
                action_id,
                str(exc),
                stage="operation",
                evidence={"exception_type": type(exc).__name__},
            )
        )
        _record_action(
            context,
            action_id=action_id,
            interaction_surface=surface,
            started_ns=started_ns,
            status="fail",
            evidence=action_error.evidence,
            failure=action_error,
            failure_stage=action_error.stage,
        )
        if action_error is exc:
            raise
        raise action_error from exc
    return _record_action(
        context,
        action_id=action_id,
        interaction_surface=surface,
        started_ns=started_ns,
        status="pass",
        evidence=evidence,
    )


def wait_until(
    context: ScenarioContext,
    predicate: Callable[[], bool],
    timeout_seconds: float,
    label: str,
    *,
    action_id: str,
    evidence: Callable[[], Mapping[str, Any]] | None = None,
) -> None:
    """Wait for a predicate without exceeding the scenario deadline."""

    allowed = context.deadline.remaining_seconds(timeout_seconds)
    if allowed <= 0:
        raise ScenarioActionError(
            action_id,
            f"timed out waiting for {label}",
            stage="timeout",
            evidence={
                "label": label,
                "elapsed_seconds": context.deadline.elapsed_seconds(),
                **dict(evidence() if evidence is not None else {}),
            },
        )
    local_deadline = context.clock() + allowed
    while context.clock() < local_deadline:
        context.pump_events()
        if predicate():
            return
        context.sleep(0.001)
    context.pump_events()
    if predicate():
        return
    raise ScenarioActionError(
        action_id,
        f"timed out waiting for {label}",
        stage="timeout",
        evidence={
            "label": label,
            "elapsed_seconds": context.deadline.elapsed_seconds(),
            **dict(evidence() if evidence is not None else {}),
        },
    )


def install_dialog_handler(
    context: ScenarioContext,
    expected_titles: tuple[str, ...],
) -> None:
    """Install the existing allowlisted modal-dialog automation."""

    if context.app is None or context.qt_core is None:
        raise RuntimeError("dialog handling requires a launched Qt application")
    if context.dialog_timer is not None:
        raise RuntimeError("dialog handling is already installed")
    from PySide6 import QtTest, QtWidgets

    handled_dialogs: set[int] = set()

    def inspect_dialogs() -> None:
        for widget in context.app.topLevelWidgets():
            if not isinstance(widget, QtWidgets.QMessageBox) or not widget.isVisible():
                continue
            identifier = id(widget)
            if identifier in handled_dialogs:
                continue
            handled_dialogs.add(identifier)
            entry = {
                "title": widget.windowTitle(),
                "text": widget.text(),
            }
            context.dialogs.append(entry)
            context.record_event("dialog", **entry)
            if entry["title"] in expected_titles:
                button = widget.button(QtWidgets.QMessageBox.StandardButton.Yes)
                if button is not None:
                    QtTest.QTest.mouseClick(
                        button,
                        context.qt_core.Qt.MouseButton.LeftButton,
                    )
                    continue
            context.unexpected_dialogs.append(entry)
            widget.reject()

    timer = context.qt_core.QTimer(context.app)
    timer.setInterval(5)
    timer.timeout.connect(inspect_dialogs)
    timer.start()
    context.dialog_timer = timer


def prepare_authoritative_fixture(
    context: ScenarioContext,
    operation: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    def run() -> Mapping[str, Any]:
        evidence = dict(operation())
        if context.dependencies is None or context.fixture_info is None:
            raise RuntimeError("fixture preparation did not populate the context")
        return evidence

    return execute_action(context, "fixture.prepare_authoritative", run)


def launch_simulated_application(
    context: ScenarioContext,
    operation: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    def run() -> Mapping[str, Any]:
        evidence = dict(operation())
        required = (
            context.app,
            context.components,
            context.model,
            context.machine,
            context.controller,
            context.view,
            context.experiment_model,
        )
        if any(value is None for value in required):
            raise RuntimeError("application launch did not populate the context")
        return evidence

    return execute_action(context, "app.launch_simulated", run)


def connect_machine_ready(
    context: ScenarioContext,
    *,
    simulated_port: str,
    dispense_frequency_hz: int,
) -> dict[str, Any]:
    def precondition():
        return (
            all(
                value is not None
                for value in (context.app, context.model, context.machine, context.controller)
            ),
            "machine readiness requires launched application components",
            None,
        )

    def run() -> Mapping[str, Any]:
        if simulated_port != "SIMULATED":
            raise RuntimeError("hardware-isolated actions require the SIMULATED port")
        if context.machine.connect_board(simulated_port) is False:
            raise RuntimeError("simulator rejected the sentinel port")
        wait_until(
            context,
            lambda: context.model.machine_model.is_connected(),
            5.0,
            "simulated connection",
            action_id="machine.connect_ready",
        )
        context.controller.toggle_motors()
        context.controller.home_machine()
        context.controller.set_dispense_frequency_hz(int(dispense_frequency_hz))
        wait_until(
            context,
            context.machine.check_if_all_completed,
            10.0,
            "machine readiness",
            action_id="machine.connect_ready",
        )
        wait_until(
            context,
            lambda: (
                context.model.machine_model.motors_are_enabled()
                and context.model.machine_model.motors_are_homed()
            ),
            5.0,
            "ready model state",
            action_id="machine.connect_ready",
        )
        return {
            "port": simulated_port,
            "dispense_frequency_hz": int(dispense_frequency_hz),
        }

    return execute_action(
        context,
        "machine.connect_ready",
        run,
        precondition=precondition,
    )


def stage_virtual_head(
    context: ScenarioContext,
    *,
    stock_index: int,
    stock_specs: tuple[dict[str, Any], ...],
    calibrated_heads: Mapping[str, Any],
    staging_slot: int,
    stock_id_for: Callable[[Mapping[str, Any]], str],
) -> tuple[str, dict[str, Any]]:
    selected: dict[str, Any] = {}

    def precondition():
        if context.controller is None or context.machine is None or context.model is None:
            return False, "virtual head staging requires launched components", None
        state = context.controller.get_array_run_state()
        drained = bool(context.machine.check_if_all_completed())
        return (
            state in {"idle", "resume_ready"} and drained,
            "virtual head exchange requires an idle array or resume-ready "
            "array and empty command queue",
            {"array_state": state, "queue_drained": drained},
        )

    def run() -> Mapping[str, Any]:
        stock = stock_specs[int(stock_index)]
        stock_id = stock_id_for(stock)
        target_head = calibrated_heads[stock_id]
        rack = context.model.rack_model
        array_state_before = context.controller.get_array_run_state()
        queue_drained_before = bool(context.machine.check_if_all_completed())
        if array_state_before not in {"idle", "resume_ready"} or not queue_drained_before:
            raise RuntimeError(
                "virtual head exchange lost its idle/drained precondition"
            )
        previous_head = rack.get_gripper_printer_head()
        previous_head_id = (
            str(getattr(previous_head, "printer_head_id", "") or "")
            if previous_head is not None
            else None
        )
        previous_stock_id = (
            str(previous_head.get_stock_id())
            if previous_head is not None
            else None
        )
        previous_origin_slot = rack.gripper_slot_number
        returned_previous = False
        suppression = (
            context.instrumentation.suppress_phases(
                "ui.well_plate_update",
                "ui.well_plate_rebuild",
                "persistence.guard_bundle",
            )
            if context.instrumentation is not None
            else nullcontext()
        )
        with suppression:
            if rack.get_gripper_printer_head() is not None:
                origin = rack.gripper_slot_number
                if origin is None:
                    raise RuntimeError("gripper head has no virtual origin slot")
                rack.transfer_from_gripper(origin)
                if rack.get_gripper_printer_head() is not None:
                    raise RuntimeError("could not return the previous virtual head")
                returned_previous = True
            for slot_index, slot in enumerate(rack.slots):
                if slot.printer_head is target_head:
                    rack.update_slot_with_printer_head(slot_index, None)
            rack.update_slot_with_printer_head(int(staging_slot), target_head)
            rack.confirm_slot(int(staging_slot))
            rack.transfer_to_gripper(int(staging_slot))
        active = rack.get_gripper_printer_head()
        if active is not target_head or active.get_stock_id() != stock_id:
            raise RuntimeError(f"virtual head exchange failed for {stock_id}")
        head = stock["printer_head"]
        context.controller.set_print_pulse_width(
            int(head["print_pulse_width_us"]),
            update_model=True,
        )
        context.controller.set_absolute_print_pressure(
            float(head["print_pressure_psi"])
        )
        wait_until(
            context,
            context.machine.check_if_all_completed,
            10.0,
            f"stock {int(stock_index) + 1} print settings",
            action_id="head.stage_virtual",
        )
        queue_drained_after = bool(context.machine.check_if_all_completed())
        effective_pulse_width = int(
            context.model.machine_model.get_print_pulse_width()
        )
        effective_pressure = float(
            context.model.machine_model.get_target_print_pressure()
        )
        requested_pulse_width = int(head["print_pulse_width_us"])
        requested_pressure = float(head["print_pressure_psi"])
        if (
            effective_pulse_width != requested_pulse_width
            or not math.isclose(
                effective_pressure,
                requested_pressure,
                rel_tol=0.0,
                abs_tol=0.01,
            )
            or not queue_drained_after
        ):
            raise RuntimeError(
                "virtual head print settings or post-stage queue state did not "
                f"match: pulse={effective_pulse_width}/{requested_pulse_width}, "
                f"pressure={effective_pressure}/{requested_pressure}, "
                f"queue_drained={queue_drained_after}"
            )
        context.record_event(
            "virtual_head_exchange",
            pass_index=int(stock_index) + 1,
            stock_id=stock_id,
            printer_head_id=head["printer_head_id"],
            staging_slot=int(staging_slot),
            previous_printer_head_id=previous_head_id,
            returned_previous=returned_previous,
        )
        selected.update({"stock_id": stock_id, "head": head})
        return {
            "pass_index": int(stock_index) + 1,
            "stock_id": stock_id,
            "printer_head_id": head["printer_head_id"],
            "staging_slot": int(staging_slot),
            "array_state_before": array_state_before,
            "queue_drained_before": queue_drained_before,
            "previous_stock_id": previous_stock_id,
            "previous_printer_head_id": previous_head_id,
            "previous_origin_slot": previous_origin_slot,
            "returned_previous": returned_previous,
            "requested_print_pulse_width_us": requested_pulse_width,
            "effective_print_pulse_width_us": effective_pulse_width,
            "requested_print_pressure_psi": requested_pressure,
            "effective_print_pressure_psi": effective_pressure,
            "queue_drained_after": queue_drained_after,
        }

    execute_action(
        context,
        "head.stage_virtual",
        run,
        precondition=precondition,
    )
    return str(selected["stock_id"]), dict(selected["head"])


def validate_stock_pass_boundary(
    context: ScenarioContext,
    *,
    pass_index: int,
    stock_id: str,
    printer_head_id: str,
    expected_completed_count: int,
    observed_completed_count: Callable[[], int],
    expected_plan_state: str,
) -> dict[str, Any]:
    """Validate one idle, durable stock-pass boundary before any exchange."""

    def precondition():
        return (
            context.controller is not None
            and context.machine is not None
            and context.model is not None
            and context.experiment_model is not None,
            "stock-pass validation requires launched components",
            None,
        )

    def run() -> Mapping[str, Any]:
        from ExecutionResumeStore import load_execution_resume

        controller_state = context.controller.get_array_run_state()
        queue_drained = bool(context.machine.check_if_all_completed())
        completed_count = int(observed_completed_count())
        plan = context.experiment_model.get_execution_plan_snapshot()
        plan_state = str(plan.state.value)
        rack = context.model.rack_model
        active_head = rack.get_gripper_printer_head()
        active_stock_id = (
            str(active_head.get_stock_id())
            if active_head is not None
            else None
        )
        active_head_id = (
            str(getattr(active_head, "printer_head_id", "") or "")
            if active_head is not None
            else None
        )
        resume = load_execution_resume(
            context.experiment_model.execution_resume_file_path
        )
        outstanding_intent_count = len(resume.intents)
        evidence = {
            "pass_index": int(pass_index),
            "stock_id": str(stock_id),
            "printer_head_id": str(printer_head_id),
            "expected_completed_count": int(expected_completed_count),
            "observed_completed_count": completed_count,
            "controller_state": controller_state,
            "queue_drained": queue_drained,
            "expected_plan_state": str(expected_plan_state),
            "plan_state": plan_state,
            "active_stock_id": active_stock_id,
            "active_printer_head_id": active_head_id,
            "checkpoint_state": str(resume.state),
            "outstanding_intent_count": outstanding_intent_count,
        }
        if not all(
            (
                controller_state == "idle",
                queue_drained,
                completed_count == int(expected_completed_count),
                plan_state == str(expected_plan_state),
                active_stock_id == str(stock_id),
                active_head_id == str(printer_head_id),
                str(resume.state) == "clean",
                outstanding_intent_count == 0,
            )
        ):
            raise ScenarioActionError(
                "validation.stock_pass_boundary",
                "stock pass boundary is not idle, durable, or correctly associated",
                stage="operation",
                evidence=evidence,
            )
        return evidence

    return execute_action(
        context,
        "validation.stock_pass_boundary",
        run,
        precondition=precondition,
    )


def enable_pressure_regulation(context: ScenarioContext) -> dict[str, Any]:
    def precondition():
        return (
            context.controller is not None and context.model is not None,
            "pressure regulation requires launched application components",
            None,
        )

    def run() -> Mapping[str, Any]:
        context.controller.toggle_regulation()
        wait_until(
            context,
            lambda: context.model.machine_model.regulating_print_pressure,
            5.0,
            "print-pressure regulation",
            action_id="pressure.enable_regulation",
        )
        return {"regulating_print_pressure": True}

    return execute_action(
        context,
        "pressure.enable_regulation",
        run,
        precondition=precondition,
    )


def start_array_via_ui(
    context: ScenarioContext,
    *,
    expected_running_count: int,
) -> dict[str, Any]:
    def precondition():
        return (
            context.view is not None
            and context.controller is not None
            and context.app is not None,
            "array start requires a launched application",
            None,
        )

    def run() -> Mapping[str, Any]:
        from tools.virtual_workflows.page_drivers import ArrayDriver

        button = context.view.well_plate_widget.start_print_array_button
        wait_until(
            context,
            lambda: button.isVisible() and button.isEnabled(),
            5.0,
            "array start control",
            action_id="array.start_via_ui",
            evidence=lambda: {
                "visible": bool(button.isVisible()),
                "enabled": bool(button.isEnabled()),
            },
        )
        wait_until(
            context,
            context.controller.check_if_all_completed,
            5.0,
            "array start command queue",
            action_id="array.start_via_ui",
            evidence=lambda: {
                "queue_drained": bool(
                    context.controller.check_if_all_completed()
                ),
            },
        )
        ArrayDriver(context).click_start()
        wait_until(
            context,
            lambda: (
                context.array_states.count("running") >= expected_running_count
                or bool(context.errors)
            ),
            10.0,
            "array running state",
            action_id="array.start_via_ui",
            evidence=lambda: {
                "array_states": list(context.array_states),
                "errors": list(context.errors),
            },
        )
        if context.errors:
            raise RuntimeError(f"array start emitted an error: {context.errors[-1]}")
        return {
            "expected_running_count": int(expected_running_count),
            "observed_running_count": context.array_states.count("running"),
        }

    return execute_action(
        context,
        "array.start_via_ui",
        run,
        precondition=precondition,
    )


def wait_for_completions(
    context: ScenarioContext,
    *,
    completed_count: Callable[[], int],
    target_count: int,
    timeout_seconds: float,
    label: str,
) -> dict[str, Any]:
    def run() -> Mapping[str, Any]:
        wait_until(
            context,
            lambda: completed_count() >= int(target_count) or bool(context.errors),
            timeout_seconds,
            label,
            action_id="array.wait_for_completions",
            evidence=lambda: {
                "target_count": int(target_count),
                "observed_count": int(completed_count()),
                "errors": list(context.errors),
            },
        )
        if context.errors:
            raise RuntimeError(f"array execution emitted an error: {context.errors[-1]}")
        return {
            "target_count": int(target_count),
            "observed_count": int(completed_count()),
        }

    return execute_action(context, "array.wait_for_completions", run)


def wait_for_array_state(
    context: ScenarioContext,
    *,
    state: str,
    timeout_seconds: float,
    label: str,
) -> dict[str, Any]:
    def precondition():
        return (
            context.controller is not None,
            "array-state wait requires a Controller",
            None,
        )

    def run() -> Mapping[str, Any]:
        wait_until(
            context,
            lambda: context.controller.get_array_run_state() == state,
            timeout_seconds,
            label,
            action_id="array.wait_for_state",
            evidence=lambda: {
                "expected_state": state,
                "observed_state": context.controller.get_array_run_state(),
            },
        )
        return {"state": state}

    return execute_action(
        context,
        "array.wait_for_state",
        run,
        precondition=precondition,
    )


def request_soft_stop_via_ui(
    context: ScenarioContext,
    *,
    completed_count: Callable[[], int],
    trigger_count: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Queue the real soft-stop click on the exact observed completion."""

    def precondition():
        state = (
            context.controller.get_array_run_state()
            if context.controller is not None
            else None
        )
        return (
            context.view is not None
            and context.controller is not None
            and context.model is not None
            and context.app is not None
            and context.qt_core is not None
            and state == "running",
            "soft stop requires a running real UI workflow"
            if state == "running"
            else "soft stop requires array state running",
            {"array_state": state},
        )

    def run() -> Mapping[str, Any]:
        from tools.virtual_workflows.page_drivers import ArrayDriver

        button = context.view.well_plate_widget.start_print_array_button
        driver = ArrayDriver(context)
        observed: dict[str, Any] = {
            "trigger_count": int(trigger_count),
            "click_queued": False,
            "clicked_count": None,
            "button_text_before": None,
        }

        def queue_click(*_args: Any) -> None:
            count = int(completed_count())
            if observed["click_queued"] or count < int(trigger_count):
                return
            if count != int(trigger_count):
                observed["overshoot_count"] = count
                return
            observed["click_queued"] = True

            def click() -> None:
                observed["clicked_count"] = int(completed_count())
                try:
                    observed.update(driver.request_soft_stop())
                except RuntimeError:
                    observed["invalid_control"] = {
                        "text": button.text(),
                        "enabled": bool(button.isEnabled()),
                    }

            context.qt_core.QTimer.singleShot(0, click)

        signal = context.model.well_plate.well_state_changed_signal
        signal.connect(queue_click)
        try:
            queue_click()
            wait_until(
                context,
                lambda: (
                    context.controller.get_array_run_state() == "stop_requested"
                    or bool(context.errors)
                    or "overshoot_count" in observed
                    or "invalid_control" in observed
                ),
                timeout_seconds,
                f"soft-stop request at completion {int(trigger_count)}",
                action_id="array.request_soft_stop_via_ui",
                evidence=lambda: {
                    **observed,
                    "observed_count": int(completed_count()),
                    "array_state": context.controller.get_array_run_state(),
                    "button_text": button.text(),
                    "button_enabled": bool(button.isEnabled()),
                },
            )
        finally:
            try:
                signal.disconnect(queue_click)
            except (RuntimeError, TypeError):
                pass
        if context.errors:
            raise RuntimeError(f"soft stop emitted an error: {context.errors[-1]}")
        if "overshoot_count" in observed:
            raise RuntimeError(
                "soft-stop trigger was not serviced at the exact completion"
            )
        if "invalid_control" in observed:
            raise RuntimeError("soft-stop control was not in its running state")
        array_context = dict(getattr(context.controller, "_array_context", {}) or {})
        barrier = int(array_context.get("soft_stop_barrier_seq32") or 0)
        if (
            observed["clicked_count"] != int(trigger_count)
            or button.text() != "Stop Pending"
            or button.isEnabled()
            or barrier <= 0
        ):
            raise RuntimeError("soft-stop request did not establish its UI/barrier state")
        return {
            **observed,
            "observed_count": int(completed_count()),
            "array_state": context.controller.get_array_run_state(),
            "button_text_after": button.text(),
            "button_enabled_after": bool(button.isEnabled()),
            "pause_barrier_seq32": barrier,
        }

    return execute_action(
        context,
        "array.request_soft_stop_via_ui",
        run,
        precondition=precondition,
    )


def resume_array_via_ui(context: ScenarioContext) -> dict[str, Any]:
    """Resume a paused array through the normal Qt control."""

    def precondition():
        state = (
            context.controller.get_array_run_state()
            if context.controller is not None
            else None
        )
        return (
            context.view is not None
            and context.controller is not None
            and context.app is not None
            and state == "resume_ready",
            "array resume requires resume_ready",
            {"array_state": state},
        )

    def run() -> Mapping[str, Any]:
        from tools.virtual_workflows.page_drivers import ArrayDriver

        return ArrayDriver(context).resume()

    return execute_action(
        context,
        "array.resume_via_ui",
        run,
        precondition=precondition,
    )


def observe_stopped_quiescence(
    context: ScenarioContext,
    *,
    completed_count: Callable[[], int],
    progress_count: Callable[[], int],
    observation_ms: int,
) -> dict[str, Any]:
    """Pump Qt for a bounded paused window and prove no work advances."""

    def precondition():
        state = (
            context.controller.get_array_run_state()
            if context.controller is not None
            else None
        )
        return (
            context.controller is not None
            and context.machine is not None
            and state == "resume_ready",
            "quiescence observation requires resume_ready",
            {"array_state": state},
        )

    def run() -> Mapping[str, Any]:
        starting_completions = int(completed_count())
        starting_progress = int(progress_count())
        duration_seconds = int(observation_ms) / 1000.0
        if duration_seconds <= 0:
            raise RuntimeError("quiescence observation must be positive")
        allowed = context.deadline.remaining_seconds(duration_seconds + 1.0)
        if allowed < duration_seconds:
            raise ScenarioActionError(
                "array.observe_stopped_quiescence",
                "scenario deadline cannot contain the quiescence window",
                stage="timeout",
            )
        started = context.clock()
        while context.clock() - started < duration_seconds:
            context.pump_events()
            if (
                int(completed_count()) != starting_completions
                or int(progress_count()) != starting_progress
                or context.controller.get_array_run_state() != "resume_ready"
                or not context.machine.check_if_all_completed()
            ):
                raise RuntimeError("paused workflow advanced during quiescence")
            context.sleep(0.001)
        return {
            "observation_ms": int(observation_ms),
            "starting_completion_count": starting_completions,
            "ending_completion_count": int(completed_count()),
            "starting_progress_count": starting_progress,
            "ending_progress_count": int(progress_count()),
            "array_state": context.controller.get_array_run_state(),
            "simulator_queue_empty": bool(context.machine.check_if_all_completed()),
        }

    return execute_action(
        context,
        "array.observe_stopped_quiescence",
        run,
        precondition=precondition,
    )


def capture_milestone(
    context: ScenarioContext,
    name: str,
    *,
    evidence: Mapping[str, Any] | None = None,
    widget: Any | None = None,
) -> dict[str, Any]:
    def precondition():
        return (
            widget is not None or context.view is not None,
            "milestone capture requires a launched view",
            {"milestone": name},
        )

    def run() -> Mapping[str, Any]:
        if not name or name in context.screenshots:
            raise RuntimeError(f"milestone name is invalid or duplicated: {name!r}")
        path = (context.screenshots_dir / f"{name}.png").resolve()
        if context.screenshots_dir not in path.parents:
            raise RuntimeError("milestone screenshot escaped the screenshot directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        image = (widget if widget is not None else context.view).grab()
        if image.isNull() or not image.save(str(path), "PNG"):
            raise RuntimeError(f"could not capture screenshot {path.name}")
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"screenshot {path.name} is empty")
        context.screenshots[name] = path
        relative = path.relative_to(context.report_dir).as_posix()
        milestone = {
            "name": name,
            "screenshot": relative,
            "evidence": _json_evidence(evidence),
        }
        context.milestones.append(milestone)
        context.record_event("milestone", name=name, **dict(evidence or {}))
        return milestone

    return execute_action(
        context,
        "artifact.capture_milestone",
        run,
        precondition=precondition,
    )


def _ensure_editor_deadline(
    context: ScenarioContext,
    action_id: str,
    stage: str,
) -> None:
    if context.deadline.remaining_seconds() <= 0:
        raise ScenarioActionError(
            action_id,
            "scenario deadline is exhausted",
            stage="timeout",
            evidence={
                "editor_stage": stage,
                "elapsed_seconds": context.deadline.elapsed_seconds(),
            },
        )


def _qt_replace_text(QtCore: Any, QtTest: Any, widget: Any, value: Any) -> None:
    widget.setFocus()
    QtTest.QTest.mouseClick(widget, QtCore.Qt.MouseButton.LeftButton)
    QtTest.QTest.keyClick(
        widget,
        QtCore.Qt.Key.Key_A,
        QtCore.Qt.KeyboardModifier.ControlModifier,
    )
    QtTest.QTest.keyClicks(widget, str(value))


def _qt_set_spin_value(
    QtCore: Any,
    QtTest: Any,
    widget: Any,
    value: int | float,
) -> None:
    line_edit = widget.lineEdit()
    _qt_replace_text(QtCore, QtTest, line_edit, value)
    QtTest.QTest.keyClick(line_edit, QtCore.Qt.Key.Key_Tab)
    observed = float(widget.value())
    expected = float(value)
    if not math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-9):
        raise RuntimeError(
            f"spin control retained {observed!r}; expected {expected!r}"
        )


def _qt_select_combo_text(
    QtCore: Any,
    QtTest: Any,
    widget: Any,
    text: str,
) -> None:
    index = int(widget.findText(str(text)))
    if index < 0:
        requested = str(text).casefold()
        index = next(
            (
                candidate
                for candidate in range(widget.count())
                if widget.itemText(candidate).casefold() == requested
            ),
            -1,
        )
    if index < 0:
        raise RuntimeError(f"combo option is unavailable: {text!r}")
    widget.setFocus()
    QtTest.QTest.keyClick(widget, QtCore.Qt.Key.Key_Home)
    for _ in range(index):
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key.Key_Down)
    QtTest.QTest.keyClick(widget, QtCore.Qt.Key.Key_Tab)
    if widget.currentText().casefold() != str(text).casefold():
        raise RuntimeError(
            f"combo retained {widget.currentText()!r}; expected {text!r}"
        )


def drive_editor_create_finalize(
    context: ScenarioContext,
    specification: Mapping[str, Any],
    *,
    action_runner: Callable[..., dict[str, Any]] | None = None,
    capture_editor_milestones: bool = True,
) -> dict[str, Any]:
    """Drive the real modal experiment editor through bounded QTest interaction."""

    if context.app is None or context.qt_core is None or context.view is None:
        raise RuntimeError("editor automation requires a launched Qt application")

    from PySide6 import QtTest, QtWidgets
    from View import ExperimentDesignDialog, WellSelectionDialog

    QtCore = context.qt_core
    button = context.view.well_plate_widget.design_experiment_button
    if not button.isEnabled():
        raise ScenarioActionError(
            "editor.open_via_ui",
            "Experiment Editor button is disabled",
            stage="precondition",
        )

    state: dict[str, Any] = {
        "entered": False,
        "finished": False,
        "error": None,
        "dialog": None,
    }
    driver_timer = QtCore.QTimer(context.app)
    driver_timer.setInterval(5)

    def run_action(
        action_id: str,
        operation: Callable[[], Mapping[str, Any] | None],
        *,
        precondition: Callable[
            [], tuple[bool, str, Mapping[str, Any] | None]
        ]
        | None = None,
        allowed_dialogs: tuple[Any, ...] = (),
    ) -> dict[str, Any]:
        if action_runner is not None:
            return action_runner(
                action_id,
                operation,
                precondition=precondition,
                allowed_dialogs=allowed_dialogs,
            )
        return execute_action(
            context,
            action_id,
            operation,
            precondition=precondition,
        )

    def click(widget: Any) -> None:
        QtTest.QTest.mouseClick(widget, QtCore.Qt.MouseButton.LeftButton)
        context.app.processEvents()

    def toggle_checkbox(widget: Any) -> None:
        widget.setFocus()
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key.Key_Space)
        context.app.processEvents()

    def select_printable_wells(
        dialog: Any,
        well_ids: list[str],
    ) -> None:
        selection_state: dict[str, Any] = {"entered": False, "error": None}

        def drive_selection() -> None:
            selection_state["entered"] = True
            active = context.app.activeModalWidget()
            try:
                if not isinstance(active, WellSelectionDialog):
                    title = active.windowTitle() if active is not None else None
                    if isinstance(active, QtWidgets.QDialog):
                        active.reject()
                    raise RuntimeError(
                        "unexpected printable-wells modal: "
                        f"{type(active).__name__ if active is not None else None} "
                        f"{title!r}"
                    )
                click(active.clear_btn)
                for well_id in well_ids:
                    row_label = "".join(
                        character
                        for character in well_id
                        if character.isalpha()
                    ).upper()
                    column_text = "".join(
                        character
                        for character in well_id
                        if character.isdigit()
                    )
                    row = 0
                    for character in row_label:
                        row = row * 26 + (ord(character) - ord("A") + 1)
                    row -= 1
                    column = int(column_text) - 1
                    QtTest.QTest.mouseClick(
                        active.grid,
                        QtCore.Qt.MouseButton.LeftButton,
                        pos=active.grid._cell_rect(row, column).center(),
                    )
                observed = active.selected_well_ids()
                if observed != well_ids:
                    raise RuntimeError(
                        f"printable wells retained {observed!r}; "
                        f"expected {well_ids!r}"
                    )
                click(active.ok_btn)
            except BaseException as exc:
                selection_state["error"] = exc
                if isinstance(active, QtWidgets.QDialog) and active.isVisible():
                    active.reject()

        QtCore.QTimer.singleShot(0, drive_selection)
        QtTest.QTest.mouseClick(
            dialog.well_selection_btn,
            QtCore.Qt.MouseButton.LeftButton,
        )
        if selection_state["error"] is not None:
            raise selection_state["error"]
        if not selection_state["entered"]:
            raise RuntimeError("Printable Wells dialog did not open")
        selected = dialog.model.get_auto_assignment_included_wells()
        if list(selected or []) != well_ids:
            raise RuntimeError(
                f"editor retained printable wells {selected!r}; "
                f"expected {well_ids!r}"
            )

    def run_driver() -> None:
        if state["entered"]:
            return
        state["entered"] = True
        driver_timer.stop()
        active = context.app.activeModalWidget()
        try:
            if not isinstance(active, ExperimentDesignDialog):
                title = active.windowTitle() if active is not None else None
                if isinstance(active, QtWidgets.QDialog):
                    active.reject()
                run_action(
                    "editor.open_via_ui",
                    lambda: {},
                    precondition=lambda: (
                        False,
                        "unexpected active modal while opening the editor",
                        {
                            "modal_type": (
                                type(active).__name__
                                if active is not None
                                else None
                            ),
                            "modal_title": title,
                        },
                    ),
                )
            dialog = active
            state["dialog"] = dialog
            run_action(
                "editor.open_via_ui",
                lambda: {
                    "dialog_type": type(dialog).__name__,
                    "window_title": dialog.windowTitle(),
                },
                allowed_dialogs=(dialog,),
            )
            if capture_editor_milestones:
                capture_milestone(
                    context,
                    "editor_opened",
                    evidence={"window_title": dialog.windowTitle()},
                    widget=dialog,
                )

            run_action(
                "editor.new_experiment_via_ui",
                lambda: (
                    click(dialog.new_btn)
                    or {
                        "experiment_dir": getattr(
                            dialog.model, "experiment_dir_path", None
                        ),
                        "factor_count": len(dialog.model.factors),
                    }
                ),
                allowed_dialogs=(dialog,),
            )

            experiment = specification["experiment"]
            reagents = specification.get("reagents")
            if reagents is None:
                reagents = [specification["reagent"]]
            reagents = list(reagents)
            if not reagents:
                raise RuntimeError("editor specification requires a reagent")

            def configure() -> Mapping[str, Any]:
                if dialog.auto_update_chk.isChecked():
                    toggle_checkbox(dialog.auto_update_chk)
                if dialog.auto_update_chk.isChecked():
                    raise RuntimeError("auto update could not be disabled")
                _qt_replace_text(
                    QtCore,
                    QtTest,
                    dialog.exp_name_edit,
                    experiment["name"],
                )
                _qt_set_spin_value(
                    QtCore, QtTest, dialog.rep_spin, experiment["replicates"]
                )
                _qt_set_spin_value(
                    QtCore,
                    QtTest,
                    dialog.v_spin,
                    experiment["printed_volume_nL"],
                )
                _qt_set_spin_value(
                    QtCore,
                    QtTest,
                    dialog.final_v_spin,
                    experiment["final_volume_nL"],
                )
                _qt_set_spin_value(
                    QtCore,
                    QtTest,
                    dialog.volume_tolerance_spin,
                    experiment["printed_volume_tolerance_nL"],
                )
                _qt_select_combo_text(
                    QtCore,
                    QtTest,
                    dialog.plate_format_combo,
                    experiment["plate_name"],
                )
                select_printable_wells(
                    dialog,
                    list(experiment["expected_well_ids"]),
                )
                for checkbox, expected in (
                    (
                        dialog.allow_two_chk,
                        experiment["allow_two_stock_solutions"],
                    ),
                    (dialog.randomize_chk, experiment["randomize_assignments"]),
                ):
                    if bool(checkbox.isChecked()) != bool(expected):
                        toggle_checkbox(checkbox)
                    if bool(checkbox.isChecked()) != bool(expected):
                        raise RuntimeError("checkbox did not retain requested state")
                for row, reagent in enumerate(reagents):
                    click(dialog.add_reagent_btn)
                    if dialog._reagent_row_count() != row + 1:
                        raise RuntimeError(
                            "editor did not create the requested reagent row"
                        )
                    _qt_replace_text(
                        QtCore,
                        QtTest,
                        dialog._reagent_cell_widget(row, dialog.COL_STOCK_LABEL),
                        reagent["stock_label"],
                    )
                    _qt_select_combo_text(
                        QtCore,
                        QtTest,
                        dialog._reagent_cell_widget(row, dialog.COL_GROUP),
                        reagent["group"],
                    )
                    _qt_select_combo_text(
                        QtCore,
                        QtTest,
                        dialog._reagent_cell_widget(row, dialog.COL_MODE),
                        reagent["printing_mode"],
                    )
                    _qt_set_spin_value(
                        QtCore,
                        QtTest,
                        dialog._reagent_cell_widget(row, dialog.COL_STARTING),
                        reagent["starting_concentration"],
                    )
                    _qt_replace_text(
                        QtCore,
                        QtTest,
                        dialog._reagent_cell_widget(row, dialog.COL_TARGETS),
                        ", ".join(str(value) for value in reagent["targets"]),
                    )
                    _qt_replace_text(
                        QtCore,
                        QtTest,
                        dialog._reagent_cell_widget(row, dialog.COL_UNITS),
                        reagent["units"],
                    )
                    _qt_replace_text(
                        QtCore,
                        QtTest,
                        dialog._reagent_cell_widget(row, dialog.COL_SET_STOCK),
                        reagent["fixed_stock_concentration"],
                    )
                    _qt_set_spin_value(
                        QtCore,
                        QtTest,
                        dialog._reagent_cell_widget(row, dialog.COL_DROPLET),
                        reagent["droplet_volume_nL"],
                    )
                _ensure_editor_deadline(
                    context, "editor.configure_design_via_ui", "configured"
                )
                return {
                    "experiment_name": dialog.exp_name_edit.text(),
                    "plate_name": dialog.plate_format_combo.currentText(),
                    "reagent_count": dialog._reagent_row_count(),
                    "auto_update": dialog.auto_update_chk.isChecked(),
                }

            run_action(
                "editor.configure_design_via_ui",
                configure,
                allowed_dialogs=(dialog,),
            )

            def generate() -> Mapping[str, Any]:
                click(dialog.run_btn)
                _ensure_editor_deadline(
                    context, "editor.optimize_generate_via_ui", "generated"
                )
                if dialog._design_optimization_dirty:
                    raise RuntimeError("generated design remained dirty")
                reaction_count = int(dialog.model.get_number_of_reactions())
                if reaction_count != int(experiment["replicates"]):
                    raise RuntimeError(
                        "generated reaction count did not match replicates"
                    )
                return {
                    "reaction_count": reaction_count,
                    "stock_row_count": dialog.stock_table.rowCount(),
                    "status": dialog.status_lbl.text(),
                }

            run_action(
                "editor.optimize_generate_via_ui",
                generate,
                allowed_dialogs=(dialog,),
            )
            if capture_editor_milestones:
                capture_milestone(
                    context,
                    "generated",
                    evidence={
                        "reaction_count": dialog.model.get_number_of_reactions()
                    },
                    widget=dialog,
                )

            def finish() -> Mapping[str, Any]:
                action_label = str(dialog.finish_btn.text() or "")
                if action_label != "Finalize Design":
                    raise RuntimeError(
                        f"editable design exposed {action_label!r}; "
                        "expected 'Finalize Design'"
                    )
                click(dialog.finish_btn)
                _ensure_editor_deadline(
                    context, "editor.finish_via_ui", "finalized"
                )
                if dialog.result() != QtWidgets.QDialog.DialogCode.Accepted:
                    raise RuntimeError(
                        "editor did not accept after Finalize Design"
                    )
                return {
                    "dialog_result": int(dialog.result()),
                    "apply_requested": bool(dialog._apply_requested),
                    "action_label": action_label,
                }

            run_action("editor.finish_via_ui", finish)
            state["finished"] = True
        except BaseException as exc:
            state["error"] = exc
            if isinstance(active, QtWidgets.QDialog) and active.isVisible():
                active.reject()

    driver_timer.timeout.connect(run_driver)
    driver_timer.start()
    try:
        QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
    finally:
        driver_timer.stop()
        driver_timer.deleteLater()
    if state["error"] is not None:
        raise state["error"]
    if not state["entered"]:
        raise ScenarioActionError(
            "editor.open_via_ui",
            "the modal editor did not open",
            stage="timeout",
        )
    if not state["finished"]:
        raise ScenarioActionError(
            "editor.finish_via_ui",
            "the modal editor did not finish",
            stage="operation",
        )
    return {
        "dialog_type": type(state["dialog"]).__name__,
        "finalized": True,
    }


def drive_editor_prestart_rename_refinalize(
    context: ScenarioContext,
    *,
    initial_name: str,
    renamed_name: str,
    experiment: Mapping[str, Any],
    reagent: Mapping[str, Any],
    action_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reopen and materially revise a prepared design through real Qt controls."""

    if context.app is None or context.qt_core is None or context.view is None:
        raise RuntimeError("editor automation requires a launched Qt application")

    from PySide6 import QtTest, QtWidgets
    from View import ExperimentDesignDialog, WellSelectionDialog

    QtCore = context.qt_core
    button = context.view.well_plate_widget.design_experiment_button
    if not button.isEnabled():
        raise ScenarioActionError(
            "editor.open_via_ui",
            "Experiment Editor button is disabled",
            stage="precondition",
        )

    state: dict[str, Any] = {
        "entered": False,
        "finished": False,
        "error": None,
        "dialog": None,
        "before": None,
        "after": None,
    }
    driver_timer = QtCore.QTimer(context.app)
    driver_timer.setInterval(5)

    def run_action(
        action_id: str,
        operation: Callable[[], Mapping[str, Any] | None],
        *,
        precondition: Callable[
            [], tuple[bool, str, Mapping[str, Any] | None]
        ]
        | None = None,
        allowed_dialogs: tuple[Any, ...] = (),
    ) -> dict[str, Any]:
        if action_runner is not None:
            return action_runner(
                action_id,
                operation,
                precondition=precondition,
                allowed_dialogs=allowed_dialogs,
            )
        return execute_action(
            context,
            action_id,
            operation,
            precondition=precondition,
        )

    def click(widget: Any) -> None:
        QtTest.QTest.mouseClick(widget, QtCore.Qt.MouseButton.LeftButton)
        context.app.processEvents()

    def toggle_checkbox(widget: Any) -> None:
        widget.setFocus()
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key.Key_Space)
        context.app.processEvents()

    def design_surface(dialog: Any) -> dict[str, Any]:
        reagent_rows: list[dict[str, Any]] = []
        for row in range(dialog._reagent_row_count()):
            values: dict[str, Any] = {}
            for column in range(dialog.COL_DELETE):
                widget = dialog._reagent_cell_widget(row, column)
                if isinstance(widget, QtWidgets.QLineEdit):
                    value: Any = widget.text()
                elif isinstance(widget, QtWidgets.QComboBox):
                    value = widget.currentText()
                elif isinstance(
                    widget,
                    (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox),
                ):
                    value = widget.value()
                elif isinstance(widget, QtWidgets.QCheckBox):
                    value = widget.isChecked()
                elif isinstance(widget, QtWidgets.QLabel):
                    value = widget.text()
                else:
                    value = None
                values[str(column)] = value
            reagent_rows.append(values)
        return {
            "replicates": dialog.rep_spin.value(),
            "printed_volume_nL": dialog.v_spin.value(),
            "final_volume_nL": dialog.final_v_spin.value(),
            "printed_volume_tolerance_nL": dialog.volume_tolerance_spin.value(),
            "plate_name": dialog.plate_format_combo.currentText(),
            "allow_two_stock_solutions": dialog.allow_two_chk.isChecked(),
            "randomize_assignments": dialog.randomize_chk.isChecked(),
            "well_ids": list(
                dialog.model.get_auto_assignment_included_wells() or []
            ),
            "reagent_rows": reagent_rows,
        }

    def select_printable_wells(dialog: Any, well_ids: list[str]) -> None:
        selection_state: dict[str, Any] = {"entered": False, "error": None}

        def drive_selection() -> None:
            selection_state["entered"] = True
            active = context.app.activeModalWidget()
            try:
                if not isinstance(active, WellSelectionDialog):
                    title = active.windowTitle() if active is not None else None
                    if isinstance(active, QtWidgets.QDialog):
                        active.reject()
                    raise RuntimeError(
                        "unexpected printable-wells modal while editing prepared "
                        f"design: {type(active).__name__ if active is not None else None} "
                        f"{title!r}"
                    )
                click(active.clear_btn)
                for well_id in well_ids:
                    row_label = "".join(
                        character
                        for character in well_id
                        if character.isalpha()
                    ).upper()
                    column_text = "".join(
                        character
                        for character in well_id
                        if character.isdigit()
                    )
                    row = 0
                    for character in row_label:
                        row = row * 26 + (ord(character) - ord("A") + 1)
                    row -= 1
                    column = int(column_text) - 1
                    QtTest.QTest.mouseClick(
                        active.grid,
                        QtCore.Qt.MouseButton.LeftButton,
                        pos=active.grid._cell_rect(row, column).center(),
                    )
                observed = active.selected_well_ids()
                if observed != well_ids:
                    raise RuntimeError(
                        f"printable wells retained {observed!r}; "
                        f"expected {well_ids!r}"
                    )
                click(active.ok_btn)
            except BaseException as exc:
                selection_state["error"] = exc
                if isinstance(active, QtWidgets.QDialog) and active.isVisible():
                    active.reject()

        QtCore.QTimer.singleShot(0, drive_selection)
        QtTest.QTest.mouseClick(
            dialog.well_selection_btn,
            QtCore.Qt.MouseButton.LeftButton,
        )
        if selection_state["error"] is not None:
            raise selection_state["error"]
        if not selection_state["entered"]:
            raise RuntimeError("Printable Wells dialog did not open")
        observed = list(
            dialog.model.get_auto_assignment_included_wells() or []
        )
        if observed != well_ids:
            raise RuntimeError(
                f"editor retained printable wells {observed!r}; "
                f"expected {well_ids!r}"
            )

    def run_driver() -> None:
        if state["entered"]:
            return
        state["entered"] = True
        driver_timer.stop()
        active = context.app.activeModalWidget()
        try:
            if not isinstance(active, ExperimentDesignDialog):
                title = active.windowTitle() if active is not None else None
                if isinstance(active, QtWidgets.QDialog):
                    active.reject()
                run_action(
                    "editor.open_via_ui",
                    lambda: {},
                    precondition=lambda: (
                        False,
                        "unexpected active modal while reopening prepared editor",
                        {
                            "modal_type": (
                                type(active).__name__
                                if active is not None
                                else None
                            ),
                            "modal_title": title,
                        },
                    ),
                )
            dialog = active
            state["dialog"] = dialog
            run_action(
                "editor.open_via_ui",
                lambda: {
                    "dialog_type": type(dialog).__name__,
                    "window_title": dialog.windowTitle(),
                    "prepared_reopen": True,
                    "action_label": str(dialog.finish_btn.text() or ""),
                },
                allowed_dialogs=(dialog,),
            )
            capture_milestone(
                context,
                "rename_editor_opened",
                evidence={
                    "experiment_name": dialog.exp_name_edit.text(),
                    "editable": (
                        dialog.exp_name_edit.isEnabled()
                        and not dialog.exp_name_edit.isReadOnly()
                    ),
                },
                widget=dialog,
            )

            def rename() -> Mapping[str, Any]:
                _ensure_editor_deadline(
                    context, "editor.rename_prepared_via_ui", "rename"
                )
                if (
                    not dialog.exp_name_edit.isEnabled()
                    or dialog.exp_name_edit.isReadOnly()
                ):
                    raise RuntimeError(
                        "prepared experiment name control is not editable"
                    )
                if dialog.exp_name_edit.text() != initial_name:
                    raise RuntimeError(
                        "prepared editor did not reopen with the initial name"
                    )
                if dialog.finish_btn.text() != "Finalize Design":
                    raise RuntimeError(
                        "prepared design did not expose Finalize Design before edits"
                    )
                if dialog.auto_update_chk.isChecked():
                    toggle_checkbox(dialog.auto_update_chk)
                if dialog.auto_update_chk.isChecked():
                    raise RuntimeError("auto update could not be disabled")
                before = design_surface(dialog)
                _qt_replace_text(
                    QtCore,
                    QtTest,
                    dialog.exp_name_edit,
                    renamed_name,
                )
                QtTest.QTest.keyClick(
                    dialog.exp_name_edit,
                    QtCore.Qt.Key.Key_Tab,
                )
                context.app.processEvents()
                after = design_surface(dialog)
                if dialog.exp_name_edit.text() != renamed_name:
                    raise RuntimeError("experiment name edit was not retained")
                if after != before:
                    raise RuntimeError(
                        "a non-name editor control changed during prepared rename"
                    )
                state["before"] = before
                state["after"] = after
                return {
                    "initial_name": initial_name,
                    "renamed_name": renamed_name,
                    "non_name_controls_unchanged": True,
                    "action_label": str(dialog.finish_btn.text() or ""),
                }

            run_action(
                "editor.rename_prepared_via_ui",
                rename,
                allowed_dialogs=(dialog,),
            )
            capture_milestone(
                context,
                "renamed",
                evidence={
                    "initial_name": initial_name,
                    "renamed_name": renamed_name,
                    "non_name_controls_unchanged": True,
                },
                widget=dialog,
            )

            def edit_prepared_design() -> Mapping[str, Any]:
                _ensure_editor_deadline(
                    context,
                    "editor.edit_prepared_design_via_ui",
                    "prepared_design_edited",
                )
                _qt_set_spin_value(
                    QtCore,
                    QtTest,
                    dialog.rep_spin,
                    experiment["refinalized_replicates"],
                )
                _qt_set_spin_value(
                    QtCore,
                    QtTest,
                    dialog.v_spin,
                    experiment["refinalized_printed_volume_nL"],
                )
                _qt_set_spin_value(
                    QtCore,
                    QtTest,
                    dialog.final_v_spin,
                    experiment["refinalized_final_volume_nL"],
                )
                select_printable_wells(
                    dialog,
                    list(experiment["refinalized_expected_well_ids"]),
                )
                _qt_select_combo_text(
                    QtCore,
                    QtTest,
                    dialog.fill_mode_combo,
                    experiment["refinalized_fill_printing_mode"],
                )
                _qt_set_spin_value(
                    QtCore,
                    QtTest,
                    dialog.fill_dv_spin,
                    experiment["refinalized_fill_droplet_volume_nL"],
                )
                if dialog._reagent_row_count() != 1:
                    raise RuntimeError(
                        "prepared editor did not retain exactly one reagent"
                    )
                row = 0
                _qt_select_combo_text(
                    QtCore,
                    QtTest,
                    dialog._reagent_cell_widget(row, dialog.COL_MODE),
                    reagent["refinalized_printing_mode"],
                )
                _qt_replace_text(
                    QtCore,
                    QtTest,
                    dialog._reagent_cell_widget(row, dialog.COL_TARGETS),
                    ", ".join(
                        str(value)
                        for value in reagent["refinalized_targets"]
                    ),
                )
                _qt_set_spin_value(
                    QtCore,
                    QtTest,
                    dialog._reagent_cell_widget(row, dialog.COL_DROPLET),
                    reagent["refinalized_droplet_volume_nL"],
                )
                context.app.processEvents()
                after = design_surface(dialog)
                state["after_edit"] = after
                return {
                    "replicates": after["replicates"],
                    "well_ids": after["well_ids"],
                    "printed_volume_nL": after["printed_volume_nL"],
                    "final_volume_nL": after["final_volume_nL"],
                    "fill_printing_mode": dialog.fill_mode_combo.currentText(),
                    "fill_droplet_volume_nL": dialog.fill_dv_spin.value(),
                    "reagent_printing_mode": dialog._reagent_cell_widget(
                        row, dialog.COL_MODE
                    ).currentText(),
                    "reagent_targets": dialog._reagent_cell_widget(
                        row, dialog.COL_TARGETS
                    ).text(),
                    "reagent_droplet_volume_nL": dialog._reagent_cell_widget(
                        row, dialog.COL_DROPLET
                    ).value(),
                }

            edit_evidence = run_action(
                "editor.edit_prepared_design_via_ui",
                edit_prepared_design,
                allowed_dialogs=(dialog,),
            )
            capture_milestone(
                context,
                "prepared_design_edited",
                evidence=edit_evidence,
                widget=dialog,
            )

            def regenerate() -> Mapping[str, Any]:
                click(dialog.run_btn)
                _ensure_editor_deadline(
                    context,
                    "editor.regenerate_prepared_design_via_ui",
                    "regenerated",
                )
                if dialog._design_optimization_dirty:
                    raise RuntimeError(
                        "regenerated prepared design remained dirty"
                    )
                reaction_count = int(dialog.model.get_number_of_reactions())
                if reaction_count != len(
                    experiment["refinalized_expected_well_ids"]
                ):
                    raise RuntimeError(
                        "regenerated reaction count did not match expected wells"
                    )
                return {
                    "reaction_count": reaction_count,
                    "stock_row_count": dialog.stock_table.rowCount(),
                    "status": dialog.status_lbl.text(),
                }

            regeneration_evidence = run_action(
                "editor.regenerate_prepared_design_via_ui",
                regenerate,
                allowed_dialogs=(dialog,),
            )
            capture_milestone(
                context,
                "regenerated",
                evidence=regeneration_evidence,
                widget=dialog,
            )

            def refinalize() -> Mapping[str, Any]:
                action_label = str(dialog.finish_btn.text() or "")
                if action_label != "Finalize Design":
                    raise RuntimeError(
                        "prepared design did not retain Finalize Design after edits"
                    )
                click(dialog.finish_btn)
                _ensure_editor_deadline(
                    context,
                    "editor.refinalize_prepared_via_ui",
                    "refinalized",
                )
                if dialog.result() != QtWidgets.QDialog.DialogCode.Accepted:
                    raise RuntimeError(
                        "prepared editor did not accept after Finalize Design"
                    )
                return {
                    "dialog_result": int(dialog.result()),
                    "apply_requested": bool(dialog._apply_requested),
                    "action_label": action_label,
                    "unexpected_dialog_count": len(
                        context.unexpected_dialogs
                    ),
                }

            run_action(
                "editor.refinalize_prepared_via_ui",
                refinalize,
            )
            capture_milestone(
                context,
                "refinalized",
                evidence={"experiment_name": renamed_name},
                widget=dialog,
            )
            state["finished"] = True
        except BaseException as exc:
            state["error"] = exc
            try:
                if "failure" not in context.screenshots:
                    capture_failure_screenshot(context, widget=active)
            except Exception:
                pass
            if isinstance(active, QtWidgets.QDialog) and active.isVisible():
                active.reject()

    driver_timer.timeout.connect(run_driver)
    driver_timer.start()
    try:
        QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
    finally:
        driver_timer.stop()
        driver_timer.deleteLater()
    if state["error"] is not None:
        raise state["error"]
    if not state["entered"]:
        raise ScenarioActionError(
            "editor.open_via_ui",
            "the prepared editor did not open",
            stage="timeout",
        )
    if not state["finished"]:
        raise ScenarioActionError(
            "editor.refinalize_prepared_via_ui",
            "the prepared editor did not finish",
            stage="operation",
        )
    return {
        "dialog_type": type(state["dialog"]).__name__,
        "initial_name": initial_name,
        "renamed_name": renamed_name,
        "non_name_controls_unchanged": state["before"] == state["after"],
        "prepared_design_changed": state.get("after_edit") != state["after"],
        "refinalized": True,
    }


def activate_authoritative_execution(
    context: ScenarioContext,
    operation: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    """Activate a prepared authoritative execution without starting printing."""

    return execute_action(
        context,
        "experiment.activate_authoritative",
        operation,
    )


def drive_authoritative_reload_via_editor(
    context: ScenarioContext,
    *,
    experiment_dir: Path,
    expected_name: str,
    before_activation: Callable[[], Mapping[str, Any]] | None = None,
    after_activation: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Load and activate a paused execution through the shared page driver."""

    from tools.virtual_workflows.page_drivers import ExperimentLoaderDriver

    return ExperimentLoaderDriver(context).load_authoritative_execution(
        experiment_dir,
        expected_name=expected_name,
        before_activation=before_activation,
        after_activation=after_activation,
    )

def validate_reload_boundary(
    context: ScenarioContext,
    operation: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    return execute_action(context, "validation.reload_boundary", operation)


def lock_execution_for_printing(
    context: ScenarioContext,
    operation: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    """Cross the durable printing-start lock boundary without a print command."""

    return execute_action(
        context,
        "execution.lock_for_printing",
        operation,
    )


def drive_editor_post_start_lock_and_copy(
    context: ScenarioContext,
    *,
    source_dir: Path,
    source_name: str,
    copy_name: str,
    copy_tolerance_nl: float,
    action_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compatibility delegate for the shared Experiment Editor page driver."""

    from tools.virtual_workflows.page_drivers import ExperimentEditorDriver

    return ExperimentEditorDriver(
        context,
        action_runner=action_runner,
    ).inspect_lock_and_create_editable_copy(
        source_dir=source_dir,
        source_name=source_name,
        copy_name=copy_name,
        copy_tolerance_nl=copy_tolerance_nl,
    )

def validate_prepared_bundle(
    context: ScenarioContext,
    validator: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    validation: dict[str, Any] = {}

    def run() -> Mapping[str, Any]:
        validation.update(dict(validator()))
        return {
            "plan_state": validation.get("plan_state"),
            "eligibility_status": validation.get("eligibility_status"),
        }

    execute_action(context, "validation.prepared_bundle", run)
    return validation


def validate_refinalized_bundle(
    context: ScenarioContext,
    validator: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    validation: dict[str, Any] = {}

    def run() -> Mapping[str, Any]:
        validation.update(dict(validator()))
        return {
            "plan_state": validation.get("plan_state"),
            "eligibility_status": validation.get("eligibility_status"),
            "renamed_name": validation.get("renamed_name"),
        }

    execute_action(context, "validation.refinalized_bundle", run)
    return validation


def reload_authoritative_experiment(
    context: ScenarioContext,
    operation: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    return execute_action(
        context,
        "experiment.reload_authoritative",
        operation,
    )


def capture_failure_screenshot(
    context: ScenarioContext,
    *,
    widget: Any | None = None,
) -> Path:
    """Best-effort failure artifact capture outside the ordinary action stream."""

    if widget is None and context.view is None:
        raise RuntimeError("failure screenshot requires a launched view")
    path = (context.screenshots_dir / "failure.png").resolve()
    if context.screenshots_dir not in path.parents:
        raise RuntimeError("failure screenshot escaped the screenshot directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    image = (widget if widget is not None else context.view).grab()
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError("could not capture screenshot failure.png")
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("screenshot failure.png is empty")
    context.screenshots["failure"] = path
    return path


def validate_terminal_bundle(
    context: ScenarioContext,
    validator: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    validation: dict[str, Any] = {}

    def run() -> Mapping[str, Any]:
        validation.update(dict(validator()))
        return {
            "terminal_plan_state": validation.get("terminal_plan_state"),
            "completed_well_count": validation.get("completed_well_count"),
        }

    execute_action(context, "validation.terminal_bundle", run)
    return validation


def validate_paused_bundle(
    context: ScenarioContext,
    validator: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    validation: dict[str, Any] = {}

    def run() -> Mapping[str, Any]:
        validation.update(dict(validator()))
        return {
            "plan_state": validation.get("plan_state"),
            "checkpoint_state": validation.get("checkpoint_state"),
            "eligibility_status": validation.get("eligibility_status"),
            "completed_count": validation.get("completed_count"),
        }

    execute_action(context, "validation.paused_bundle", run)
    return validation


def _cleanup_step(
    context: ScenarioContext,
    name: str,
    operation: Callable[[], None],
) -> None:
    try:
        operation()
    except Exception as exc:
        result = CleanupResult(
            name=name,
            status="fail",
            failure_type=type(exc).__name__,
            failure_message=str(exc)[:2000],
        ).to_dict()
    else:
        result = CleanupResult(name=name, status="pass").to_dict()
    context.cleanup_results.append(result)


def _cleanup_application_resources(
    context: ScenarioContext,
    *,
    prefix: str | None,
) -> dict[str, Any]:
    """Attempt every application-owned cleanup phase without closing the run."""

    started_at = len(context.cleanup_results)

    def phase(name: str) -> str:
        return f"{prefix}.{name}" if prefix else name

    if context.stdout_redirect is not None:
        redirect = context.stdout_redirect
        _cleanup_step(
            context,
            phase("stdout_redirect"),
            lambda: redirect.__exit__(None, None, None),
        )
        context.stdout_redirect = None
    else:
        _cleanup_step(context, phase("stdout_redirect"), lambda: None)

    _cleanup_step(
        context,
        phase("dialog_timer"),
        lambda: context.dialog_timer.stop()
        if context.dialog_timer is not None
        else None,
    )

    def remove_filter() -> None:
        if context.app is None or context.paint_filter is None:
            return
        try:
            context.app.removeEventFilter(context.paint_filter)
        except RuntimeError:
            return

    _cleanup_step(context, phase("paint_event_filter"), remove_filter)
    _cleanup_step(
        context,
        phase("instrumentation"),
        lambda: context.instrumentation.restore()
        if context.instrumentation is not None
        else None,
    )
    _cleanup_step(
        context,
        phase("progress_observer"),
        lambda: context.progress_observer.restore()
        if context.progress_observer is not None
        else None,
    )
    _cleanup_step(
        context,
        phase("persistence_io_observer"),
        lambda: context.io_observer.restore()
        if context.io_observer is not None
        else None,
    )
    _cleanup_step(
        context,
        phase("event_loop_probe"),
        lambda: context.probe.stop()
        if context.probe_started and context.probe is not None
        else None,
    )

    machine = context.machine
    _cleanup_step(
        context,
        phase("machine_disconnect"),
        lambda: machine.disconnect_board() if machine is not None else None,
    )
    machine_cleanup = {
        "command_timer_active": bool(
            machine is not None
            and getattr(machine, "_command_timer", None)
            and machine._command_timer.isActive()
        ),
        "connection_timer_active": bool(
            machine is not None
            and getattr(machine, "_connection_timer", None)
            and machine._connection_timer.isActive()
        ),
        "deferred_timer_count": len(
            getattr(machine, "_deferred_timers", set())
            if machine is not None
            else set()
        ),
    }
    context.machine_cleanup = machine_cleanup
    components = context.components
    _cleanup_step(
        context,
        phase("components"),
        lambda: components.close() if components is not None else None,
    )

    def process_deferred_deletes() -> None:
        if context.app is None:
            return
        context.app.processEvents()
        if context.qt_core is None:
            return
        try:
            context.app.sendPostedEvents(
                None,
                context.qt_core.QEvent.Type.DeferredDelete,
            )
            context.app.processEvents()
        except (AttributeError, RuntimeError):
            return

    _cleanup_step(
        context,
        phase("deferred_qt_deletes"),
        process_deferred_deletes,
    )

    pressure_timer_active = False

    def inspect_pressure_timer() -> None:
        nonlocal pressure_timer_active
        if components is None:
            return
        try:
            pressure_timer_active = bool(
                components.view.pressure_box._pressure_render_timer.isActive()
            )
        except RuntimeError:
            pressure_timer_active = False
        if pressure_timer_active:
            raise RuntimeError("pressure render timer remained active after teardown")

    _cleanup_step(
        context,
        phase("pressure_render_timer"),
        inspect_pressure_timer,
    )
    context.pressure_timer_active_after_teardown = pressure_timer_active
    results = context.cleanup_results[started_at:]
    failures = [result for result in results if result["status"] == "fail"]
    evidence = {
        "cleanup_phase_count": len(results),
        "cleanup_results": list(results),
        "machine_cleanup": machine_cleanup,
        "pressure_timer_active": pressure_timer_active,
    }
    if failures:
        raise ScenarioActionError(
            "app.close_simulated_session" if prefix else "scenario.teardown",
            f"{len(failures)} cleanup phase(s) failed",
            stage="cleanup",
            evidence={**evidence, "failures": failures},
        )
    return evidence


def close_simulated_session(
    context: ScenarioContext,
    *,
    session_id: str,
) -> dict[str, Any]:
    """Close one composed application while retaining the scenario context."""

    if not session_id:
        raise ValueError("session_id must be nonempty")

    def run() -> Mapping[str, Any]:
        evidence = _cleanup_application_resources(
            context,
            prefix=session_id,
        )
        for name in (
            "components",
            "dependencies",
            "model",
            "machine",
            "controller",
            "view",
            "experiment_model",
            "instrumentation",
            "progress_observer",
            "io_observer",
            "dialog_timer",
            "paint_filter",
            "stdout_redirect",
        ):
            setattr(context, name, None)
        context.probe_started = False
        return evidence

    def precondition():
        return (
            context.components is not None,
            "application session is not active",
            {"session_id": session_id},
        )

    return execute_action(
        context,
        "app.close_simulated_session",
        run,
        precondition=precondition,
    )


def teardown_scenario(context: ScenarioContext) -> dict[str, Any]:
    """Run the exact cleanup contract once, attempting every phase."""

    if context.closed:
        existing = [
            result
            for result in context.action_results
            if result["action_id"] == "scenario.teardown"
        ]
        return existing[-1] if existing else {}

    try:
        return execute_action(
            context,
            "scenario.teardown",
            lambda: _cleanup_application_resources(context, prefix=None),
            enforce_deadline=False,
        )
    finally:
        context.closed = True


__all__ = [
    "COMPOSED_MULTI_STOCK_ACTION_IDS",
    "COMPOSED_SOFT_STOP_ACTION_IDS",
    "ACTION_INTERACTION_SURFACES",
    "ACTION_IDS",
    "AUTHORITATIVE_RELOAD_ACTION_IDS",
    "COMPOSED_SMOKE_ACTION_IDS",
    "EDITOR_LIFECYCLE_ACTION_IDS",
    "InteractionSurface",
    "MULTI_STOCK_LIFECYCLE_ACTION_IDS",
    "PRINT_ARRAY_ACTION_IDS",
    "PRINT_ARRAY_LIFECYCLE_ACTION_IDS",
    "ActionResult",
    "CleanupResult",
    "ScenarioActionError",
    "ScenarioContext",
    "ScenarioDeadline",
    "capture_failure_screenshot",
    "capture_milestone",
    "close_simulated_session",
    "connect_machine_ready",
    "activate_authoritative_execution",
    "drive_authoritative_reload_via_editor",
    "drive_editor_create_finalize",
    "drive_editor_post_start_lock_and_copy",
    "drive_editor_prestart_rename_refinalize",
    "enable_pressure_regulation",
    "execute_action",
    "install_dialog_handler",
    "launch_simulated_application",
    "prepare_authoritative_fixture",
    "request_soft_stop_via_ui",
    "resume_array_via_ui",
    "reload_authoritative_experiment",
    "lock_execution_for_printing",
    "stage_virtual_head",
    "start_array_via_ui",
    "observe_stopped_quiescence",
    "teardown_scenario",
    "validate_prepared_bundle",
    "validate_paused_bundle",
    "validate_reload_boundary",
    "validate_refinalized_bundle",
    "validate_terminal_bundle",
    "validate_stock_pass_boundary",
    "wait_for_array_state",
    "wait_for_completions",
    "wait_until",
]
