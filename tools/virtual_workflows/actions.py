"""Reusable, bounded actions for hardware-isolated SIL scenarios."""

from __future__ import annotations

import json
import math
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping


ACTION_IDS = frozenset(
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
    started_ns: int,
    status: str,
    evidence: Mapping[str, Any] | None = None,
    failure: BaseException | None = None,
    failure_stage: str | None = None,
) -> dict[str, Any]:
    ended_ns = time.perf_counter_ns()
    result = ActionResult(
        action_id=action_id,
        status=status,
        started_monotonic_ns=started_ns,
        ended_monotonic_ns=ended_ns,
        duration_ms=(ended_ns - started_ns) / 1_000_000.0,
        evidence=MappingProxyType(_json_evidence(evidence)),
        failure_stage=failure_stage,
        failure_type=type(failure).__name__ if failure is not None else None,
        failure_message=str(failure)[:2000] if failure is not None else None,
    ).to_dict()
    context.action_results.append(result)
    context.record_event(
        "action_completed",
        action_id=action_id,
        status=status,
        duration_ms=result["duration_ms"],
        failure_stage=failure_stage,
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
) -> dict[str, Any]:
    """Execute one explicit Python action and append exactly one result."""

    if action_id not in ACTION_IDS:
        raise ValueError(f"unknown SIL action ID: {action_id!r}")
    if context.closed:
        raise ScenarioActionError(
            action_id,
            "scenario context is already closed",
            stage="precondition",
        )
    started_ns = time.perf_counter_ns()
    context.record_event("action_started", action_id=action_id)
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
            state == "idle" and drained,
            "virtual head exchange requires an idle array and empty command queue",
            {"array_state": state, "queue_drained": drained},
        )

    def run() -> Mapping[str, Any]:
        stock = stock_specs[int(stock_index)]
        stock_id = stock_id_for(stock)
        target_head = calibrated_heads[stock_id]
        rack = context.model.rack_model
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
        context.record_event(
            "virtual_head_exchange",
            pass_index=int(stock_index) + 1,
            stock_id=stock_id,
            printer_head_id=head["printer_head_id"],
            staging_slot=int(staging_slot),
        )
        selected.update({"stock_id": stock_id, "head": head})
        return {
            "pass_index": int(stock_index) + 1,
            "stock_id": stock_id,
            "printer_head_id": head["printer_head_id"],
            "staging_slot": int(staging_slot),
        }

    execute_action(
        context,
        "head.stage_virtual",
        run,
        precondition=precondition,
    )
    return str(selected["stock_id"]), dict(selected["head"])


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
        from PySide6 import QtTest

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
        context.view.activateWindow()
        button.setFocus()
        context.app.processEvents()
        QtTest.QTest.mouseClick(
            button,
            context.qt_core.Qt.MouseButton.LeftButton,
        )
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


def capture_milestone(
    context: ScenarioContext,
    name: str,
    *,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    def precondition():
        return (
            context.view is not None,
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
        image = context.view.grab()
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


def capture_failure_screenshot(context: ScenarioContext) -> Path:
    """Best-effort failure artifact capture outside the ordinary action stream."""

    if context.view is None:
        raise RuntimeError("failure screenshot requires a launched view")
    path = (context.screenshots_dir / "failure.png").resolve()
    if context.screenshots_dir not in path.parents:
        raise RuntimeError("failure screenshot escaped the screenshot directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    image = context.view.grab()
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


def teardown_scenario(context: ScenarioContext) -> dict[str, Any]:
    """Run the exact cleanup contract once, attempting every phase."""

    if context.closed:
        existing = [
            result
            for result in context.action_results
            if result["action_id"] == "scenario.teardown"
        ]
        return existing[-1] if existing else {}

    def run() -> Mapping[str, Any]:
        if context.stdout_redirect is not None:
            redirect = context.stdout_redirect
            _cleanup_step(
                context,
                "stdout_redirect",
                lambda: redirect.__exit__(None, None, None),
            )
            context.stdout_redirect = None
        else:
            _cleanup_step(context, "stdout_redirect", lambda: None)

        _cleanup_step(
            context,
            "dialog_timer",
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

        _cleanup_step(context, "paint_event_filter", remove_filter)
        _cleanup_step(
            context,
            "instrumentation",
            lambda: context.instrumentation.restore()
            if context.instrumentation is not None
            else None,
        )
        _cleanup_step(
            context,
            "progress_observer",
            lambda: context.progress_observer.restore()
            if context.progress_observer is not None
            else None,
        )
        _cleanup_step(
            context,
            "persistence_io_observer",
            lambda: context.io_observer.restore()
            if context.io_observer is not None
            else None,
        )
        _cleanup_step(
            context,
            "event_loop_probe",
            lambda: context.probe.stop()
            if context.probe_started and context.probe is not None
            else None,
        )

        machine = context.machine
        _cleanup_step(
            context,
            "machine_disconnect",
            lambda: machine.disconnect_board() if machine is not None else None,
        )
        context.machine_cleanup = {
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
        _cleanup_step(
            context,
            "components",
            lambda: context.components.close()
            if context.components is not None
            else None,
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

        _cleanup_step(context, "deferred_qt_deletes", process_deferred_deletes)

        def inspect_pressure_timer() -> None:
            if context.components is None:
                context.pressure_timer_active_after_teardown = False
                return
            try:
                context.pressure_timer_active_after_teardown = bool(
                    context.components.view.pressure_box._pressure_render_timer.isActive()
                )
            except RuntimeError:
                context.pressure_timer_active_after_teardown = False
            if context.pressure_timer_active_after_teardown:
                raise RuntimeError("pressure render timer remained active after teardown")

        _cleanup_step(context, "pressure_render_timer", inspect_pressure_timer)
        failures = [
            result for result in context.cleanup_results if result["status"] == "fail"
        ]
        if failures:
            raise ScenarioActionError(
                "scenario.teardown",
                f"{len(failures)} cleanup phase(s) failed",
                stage="cleanup",
                evidence={"failures": failures},
            )
        return {
            "cleanup_phase_count": len(context.cleanup_results),
            "machine_cleanup": context.machine_cleanup,
            "pressure_timer_active": context.pressure_timer_active_after_teardown,
        }

    try:
        return execute_action(
            context,
            "scenario.teardown",
            run,
            enforce_deadline=False,
        )
    finally:
        context.closed = True


__all__ = [
    "ACTION_IDS",
    "ActionResult",
    "CleanupResult",
    "ScenarioActionError",
    "ScenarioContext",
    "ScenarioDeadline",
    "capture_failure_screenshot",
    "capture_milestone",
    "connect_machine_ready",
    "enable_pressure_regulation",
    "execute_action",
    "install_dialog_handler",
    "launch_simulated_application",
    "prepare_authoritative_fixture",
    "stage_virtual_head",
    "start_array_via_ui",
    "teardown_scenario",
    "validate_terminal_bundle",
    "wait_for_array_state",
    "wait_for_completions",
    "wait_until",
]
