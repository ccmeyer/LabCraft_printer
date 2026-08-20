"""Qt-scheduled machine simulation for application-contract verification.

This module intentionally does not import the production Machine, protocol,
serial, camera, GPIO, balance, or firmware-update modules.
"""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from functools import partial
from typing import Any, Callable

from PySide6 import QtCore

from .state import (
    SIMULATED_PORT,
    SimulatedMachineState,
    SimulationConfig,
    SimulationFaultPlan,
)


_SUPPORTED_COMMAND_TYPES = frozenset(
    {
        "ENABLE_MOTORS",
        "DISABLE_MOTORS",
        "HOME_Z",
        "HOME_XY",
        "HOME_PR_BOTH",
        "REGULATE_PRESSURE_P",
        "REGULATE_PRESSURE_R",
        "DEREGULATE_PRESSURE_P",
        "DEREGULATE_PRESSURE_R",
        "ABSOLUTE_X",
        "ABSOLUTE_Y",
        "ABSOLUTE_Z",
        "ABSOLUTE_XY",
        "SET_AXIS_MAXSPEED",
        "SET_AXIS_ACCEL",
        "ABSOLUTE_PRESSURE_P",
        "ABSOLUTE_PRESSURE_R",
        "RELATIVE_PRESSURE_R",
        "SET_WIDTH_P",
        "SET_WIDTH_R",
        "ENABLE_PRINT_PROFILE",
        "DISABLE_PRINT_PROFILE",
        "WAIT",
        "DISPENSE",
        "DISPENSE_PRINT",
        "DISPENSE_REFUEL",
        "OPEN_GRIPPER",
        "CLOSE_GRIPPER",
        "GRIPPER_OFF",
    }
)


class _InertDropletCamera(QtCore.QObject):
    """Signal carrier required by Controller construction; performs no I/O."""

    image_captured_signal = QtCore.Signal(object)
    capture_completed_signal = QtCore.Signal(object)
    capture_failed_signal = QtCore.Signal(str)
    capture_phase_signal = QtCore.Signal(object)

    def get_latest_frame(self):
        return None

    def get_last_capture_result(self):
        return None


class SimulatedCommand:
    """Protocol-free command object with the Controller-used production fields."""

    _STATUS_BY_EVENT = {
        "queued": "Added",
        "sent": "Sent",
        "accepted": "Accepted",
        "executing": "Executing",
        "completed": "Completed",
        "canceled": "Canceled",
    }

    def __init__(
        self,
        command_number: int,
        command_type: str,
        param1: int,
        param2: int,
        param3: int,
        *,
        handler: Callable[..., Any] | None = None,
        kwargs: dict | None = None,
        trace_metadata: dict | None = None,
    ):
        self.command_number = int(command_number)
        self.command_type = str(command_type).upper()
        self.param1 = int(param1)
        self.param2 = int(param2)
        self.param3 = int(param3)
        self.handler = handler
        self.kwargs = dict(kwargs or {})
        self.trace_metadata = dict(trace_metadata or {})
        self.status = "Added"
        self.simulated_duration_ms = 0
        self.lifecycle_ms = {
            "queued": None,
            "sent": None,
            "accepted": None,
            "executing": None,
            "completed": None,
            "canceled": None,
        }
        self._handler_called = False

    def transition(self, event_name: str, simulated_time_ms: int) -> bool:
        event = str(event_name)
        if event not in self._STATUS_BY_EVENT:
            raise ValueError(f"Unknown simulated command event: {event}")
        if self.lifecycle_ms[event] is not None:
            return False
        if self.status in {"Completed", "Canceled"}:
            return False
        self.status = self._STATUS_BY_EVENT[event]
        self.lifecycle_ms[event] = int(simulated_time_ms)
        return True

    def execute_handler(self):
        if self._handler_called:
            return False
        self._handler_called = True
        if self.handler is not None:
            self.handler(**self.kwargs)
        return True

    def get_number(self):
        return self.command_number

    def get_command(self):
        return (
            f"<{self.command_type} {self.command_number} "
            f"{self.param1},{self.param2},{self.param3}>"
        )


class SimulatedCommandQueue(QtCore.QObject):
    queue_updated = QtCore.Signal()
    commands_completed = QtCore.Signal()

    def __init__(
        self,
        *,
        max_inflight_commands: int,
        completed_history_limit: int,
        event_callback: Callable[[SimulatedCommand, str], None] | None = None,
    ):
        super().__init__()
        self.queue = deque()
        self.completed = deque(maxlen=int(completed_history_limit))
        self.command_number = 0
        self.max_inflight_commands = int(max_inflight_commands)
        self._event_callback = event_callback

    def _emit_event(self, command: SimulatedCommand, event_name: str):
        if callable(self._event_callback):
            self._event_callback(command, event_name)
        self.queue_updated.emit()

    def add_command(
        self,
        command_type,
        param1,
        param2,
        param3,
        handler=None,
        kwargs=None,
        trace_metadata=None,
    ) -> SimulatedCommand:
        self.command_number += 1
        command = SimulatedCommand(
            self.command_number,
            command_type,
            param1,
            param2,
            param3,
            handler=handler,
            kwargs=kwargs,
            trace_metadata=trace_metadata,
        )
        self.queue.append(command)
        return command

    def transition(
        self,
        command: SimulatedCommand,
        event_name: str,
        simulated_time_ms: int,
    ) -> bool:
        changed = command.transition(event_name, simulated_time_ms)
        if changed:
            self._emit_event(command, event_name)
        return changed

    def get_inflight_command_count(self) -> int:
        return sum(
            command.status in {"Sent", "Accepted", "Executing"}
            for command in self.queue
        )

    def trim_terminal_commands(self):
        while self.queue and self.queue[0].status in {"Completed", "Canceled"}:
            self.completed.append(self.queue.popleft())

    def clear_queue(self, *, reset_counter=True):
        self.queue.clear()
        self.completed.clear()
        if reset_counter:
            self.command_number = 0
        self.queue_updated.emit()


class SimulatedMachine(QtCore.QObject):
    """Safe, deterministic implementation of the app-facing Machine contract."""

    status_updated = QtCore.Signal(dict)
    command_sent = QtCore.Signal(dict)
    error_occurred = QtCore.Signal(str)
    homing_completed = QtCore.Signal()
    gripper_open = QtCore.Signal()
    gripper_closed = QtCore.Signal()
    gripper_on_signal = QtCore.Signal()
    gripper_off_signal = QtCore.Signal()
    disconnect_complete_signal = QtCore.Signal()
    machine_connected_signal = QtCore.Signal(bool)
    reset_report_received = QtCore.Signal(dict)
    serial_connection_lost = QtCore.Signal(dict)
    transport_faulted = QtCore.Signal(dict)
    all_calibration_droplets_printed = QtCore.Signal()
    require_gripper_confirmation = QtCore.Signal(str)
    log_message_received = QtCore.Signal(str)
    flash_state_updated = QtCore.Signal(object)

    command_lifecycle_changed = QtCore.Signal(dict)
    state_changed = QtCore.Signal(object)
    simulation_faulted = QtCore.Signal(dict)

    def __init__(
        self,
        model,
        *,
        profile,
        serial_factory=None,
        refuel_camera_factory=None,
        droplet_camera_factory=None,
        log_reader_factory=None,
        config: SimulationConfig | None = None,
    ):
        super().__init__()
        self.model = model
        self.profile = profile
        self.config = config or SimulationConfig()
        # Retain identities for inspection only. These rejecting factories are
        # deliberately never invoked.
        self.dependency_factories = {
            "serial_factory": serial_factory,
            "refuel_camera_factory": refuel_camera_factory,
            "droplet_camera_factory": droplet_camera_factory,
            "log_reader_factory": log_reader_factory,
        }

        self.state = SimulatedMachineState()
        self.fss = 13107
        self.psi_offset = 1638
        self.psi_max = 15
        self.ser = None
        self.port = None
        self.reader = None
        self.balance = None
        self.balance_droplets = []
        self.droplet_camera = _InertDropletCamera(self)
        self.refuel_camera = None

        self.command_event_history = deque(maxlen=self.config.event_history_limit)
        self.command_queue = SimulatedCommandQueue(
            max_inflight_commands=self.config.max_inflight_commands,
            completed_history_limit=self.config.completed_history_limit,
            event_callback=self._record_command_event,
        )
        self._faults = self.config.faults
        self._active_command: SimulatedCommand | None = None
        self._sequence_pause = False
        self._completing = False
        self._drain_emitted = True
        self._suppress_drain_once = False
        self._pause_after_request: dict | None = None
        self._deferred_timers: set[QtCore.QTimer] = set()

        self._command_timer = QtCore.QTimer(self)
        self._command_timer.setSingleShot(True)
        self._command_timer.timeout.connect(self._complete_active_command)
        self._connection_timer = QtCore.QTimer(self)
        self._connection_timer.setSingleShot(True)
        self._connection_timer.timeout.connect(self._finish_connection)

    def _record_command_event(self, command: SimulatedCommand, event_name: str):
        payload = {
            "command_number": command.command_number,
            "command_type": command.command_type,
            "event": str(event_name),
            "simulated_time_ms": self.state.simulated_elapsed_ms,
            "queue_depth": self._nonterminal_depth(),
        }
        self.command_event_history.append(payload)
        self.command_lifecycle_changed.emit(dict(payload))

    def _defer(self, callback: Callable[[], None]):
        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)
        self._deferred_timers.add(timer)

        def _run():
            self._deferred_timers.discard(timer)
            try:
                callback()
            finally:
                timer.deleteLater()

        timer.timeout.connect(_run)
        timer.start(1)

    def _emit_error(self, message: str):
        text = f"Simulation: {str(message)}"
        self.error_occurred.emit(text)
        return False

    def _unsupported(self, action: str):
        return self._emit_error(
            f"{action} is unsupported by the in-process simulated machine"
        )

    def _nonterminal_depth(self) -> int:
        return sum(
            command.status not in {"Completed", "Canceled"}
            for command in self.command_queue.queue
        )

    def _refresh_command_state(self):
        self.state.command_depth = self._nonterminal_depth()
        if self._active_command is not None and self._active_command.status == "Executing":
            self.state.current_command = self._active_command.command_number
        else:
            self.state.current_command = self.state.last_retired

    def _emit_status(self):
        self._refresh_command_state()
        payload = self.state.status_payload()
        self.status_updated.emit(dict(payload))
        self.state_changed.emit(replace(self.state))

    def _command_payload(self, command: SimulatedCommand) -> dict:
        return {
            "command_number": command.command_number,
            "command_type": command.command_type,
            "param1": command.param1,
            "param2": command.param2,
            "param3": command.param3,
            "simulated_duration_ms": command.simulated_duration_ms,
        }

    def connect_board(self, port=SIMULATED_PORT):
        if str(port or "").strip().upper() != SIMULATED_PORT:
            return self._emit_error(
                f"only the {SIMULATED_PORT!r} sentinel port is accepted; "
                f"physical-looking port {port!r} was rejected"
            )
        if self.state.connected:
            return True
        self.port = SIMULATED_PORT
        delay = self.config.timing.wall_delay_ms(
            self.config.timing.connection_duration_ms
        )
        self._connection_timer.start(delay)
        return True

    def _finish_connection(self):
        self.state.connected = True
        self.state.pause_after_seq32 = 0
        self.state.pause_watermark_reached = False
        self.state.transport_paused = False
        self._emit_status()
        self.machine_connected_signal.emit(True)
        self._pump()

    def disconnect_board(self, error=False):
        del error
        self._connection_timer.stop()
        self._cancel_all_commands(clear_history=True, reset_counter=True)
        self._reset_runtime_state()
        self.port = None
        self.machine_connected_signal.emit(False)
        self.disconnect_complete_signal.emit()
        return True

    def reset_board(self):
        self._connection_timer.stop()
        self._cancel_all_commands(clear_history=True, reset_counter=True)
        self._reset_runtime_state()
        self.port = None
        return True

    def _reset_runtime_state(self):
        self.state = SimulatedMachineState()
        self._sequence_pause = False
        self._pause_after_request = None
        self._drain_emitted = True
        self._suppress_drain_once = False
        self._emit_status()

    def configure_faults(self, faults: SimulationFaultPlan):
        if not isinstance(faults, SimulationFaultPlan):
            raise TypeError("faults must be a SimulationFaultPlan")
        if not self.check_if_all_completed() or self._command_timer.isActive():
            return self._emit_error("fault configuration can change only while idle")
        self._faults = faults
        return True

    def reset_faults(self):
        return self.configure_faults(SimulationFaultPlan())

    def add_command_to_queue(
        self,
        command_type,
        param1,
        param2,
        param3,
        handler=None,
        kwargs=None,
        manual=False,
        trace_metadata=None,
    ):
        del manual
        command_name = str(command_type or "").strip().upper()
        if not self.state.connected:
            return self._emit_error(f"cannot queue {command_name}: simulator is disconnected")
        if command_name not in _SUPPORTED_COMMAND_TYPES:
            return self._unsupported(f"command {command_name or '<empty>'}")
        if command_name in self._faults.reject_command_types:
            return self._emit_error(
                f"command {command_name} was rejected by the configured fault plan"
            )

        command = self.command_queue.add_command(
            command_name,
            param1,
            param2,
            param3,
            handler=handler,
            kwargs=kwargs,
            trace_metadata=trace_metadata,
        )
        command.simulated_duration_ms = self.config.timing.simulated_duration_ms(
            command.command_type,
            command.param1,
            command.param2,
            command.param3,
        )
        self._drain_emitted = False
        self.command_queue.transition(
            command,
            "queued",
            self.state.simulated_elapsed_ms,
        )
        self._fill_acceptance_window()
        self._pump()
        return command

    def _fill_acceptance_window(self):
        for command in self.command_queue.queue:
            if (
                self.command_queue.get_inflight_command_count()
                >= self.command_queue.max_inflight_commands
            ):
                break
            if command.status != "Added":
                continue
            if self.command_queue.transition(
                command, "sent", self.state.simulated_elapsed_ms
            ):
                self.command_sent.emit(self._command_payload(command))
            if self.command_queue.transition(
                command, "accepted", self.state.simulated_elapsed_ms
            ):
                self.state.last_accepted = command.command_number
        self._emit_status()

    def _pump(self):
        if self._completing or self._active_command is not None:
            return
        if (
            not self.state.connected
            or self.state.transport_paused
            or self._sequence_pause
        ):
            return
        command = next(
            (
                queued
                for queued in self.command_queue.queue
                if queued.status == "Accepted"
            ),
            None,
        )
        if command is None:
            self._maybe_emit_successful_drain()
            return

        self._active_command = command
        self.command_queue.transition(
            command,
            "executing",
            self.state.simulated_elapsed_ms,
        )
        self.state.current_command = command.command_number
        self._emit_status()
        self._command_timer.start(
            self.config.timing.wall_delay_ms(command.simulated_duration_ms)
        )

    def _complete_active_command(self):
        command = self._active_command
        if command is None or command.status != "Executing":
            return
        self._active_command = None
        self._completing = True
        self.state.simulated_elapsed_ms += command.simulated_duration_ms

        if command.command_number in self._faults.fail_command_numbers:
            self._fail_execution(command)
            self._completing = False
            return

        self._apply_command_state(command)
        self.command_queue.transition(
            command,
            "completed",
            self.state.simulated_elapsed_ms,
        )
        self.state.last_completed = command.command_number
        self.state.last_retired = command.command_number

        pause_request = None
        if (
            self._pause_after_request is not None
            and command.command_number >= self._pause_after_request["barrier_seq32"]
        ):
            pause_request = self._pause_after_request
            self._pause_after_request = None
            self.state.transport_paused = True
            self.state.pause_watermark_reached = True

        # Production command-number processing runs the completion handler
        # before Controller.handle_status_update evaluates a reached watermark.
        # Match that ordering so saved well progress is authoritative before
        # the Controller clears lookahead.
        if pause_request is None:
            self._emit_status()

        handler_failed = False
        try:
            command.execute_handler()
        except Exception as exc:
            handler_failed = True
            self._emit_error(
                f"completion handler for command {command.command_number} failed: {exc}"
            )

        if pause_request is not None:
            self._emit_status()

        if pause_request is not None:
            callback = pause_request.get("on_success")
            if callable(callback):
                callback(
                    {
                        "barrier_seq32": pause_request["barrier_seq32"],
                        "status_confirmed": True,
                    }
                )

        self.command_queue.trim_terminal_commands()
        self._completing = False

        if handler_failed:
            self._cancel_all_commands(clear_history=False, reset_counter=False)
            self.simulation_faulted.emit(
                {
                    "reason": "completion_handler_failed",
                    "command_number": command.command_number,
                }
            )
            return

        self._fill_acceptance_window()
        self._pump()

    def _apply_command_state(self, command: SimulatedCommand):
        command_type = command.command_type
        p1, p2 = command.param1, command.param2

        if command_type == "ENABLE_MOTORS":
            self.state.motors_enabled = True
        elif command_type == "DISABLE_MOTORS":
            self.state.motors_enabled = False
            self.state.regulating_print_pressure = False
            self.state.regulating_refuel_pressure = False
            self.state.gripper_active = False
        elif command_type == "HOME_Z":
            self.state.z = self.state.target_z = 500
            self.state.homed = False
        elif command_type == "HOME_XY":
            self.state.x = self.state.target_x = 500
            self.state.y = self.state.target_y = 500
            self.state.homed = False
        elif command_type == "HOME_PR_BOTH":
            self.state.p = self.state.target_p = 0
            self.state.r = self.state.target_r = 0
            self.state.homed = True
            self.homing_completed.emit()
        elif command_type == "REGULATE_PRESSURE_P":
            self.state.regulating_print_pressure = True
        elif command_type == "REGULATE_PRESSURE_R":
            self.state.regulating_refuel_pressure = True
        elif command_type == "DEREGULATE_PRESSURE_P":
            self.state.regulating_print_pressure = False
        elif command_type == "DEREGULATE_PRESSURE_R":
            self.state.regulating_refuel_pressure = False
        elif command_type == "ABSOLUTE_X":
            self.state.x = self.state.target_x = p1
        elif command_type == "ABSOLUTE_Y":
            self.state.y = self.state.target_y = p1
        elif command_type == "ABSOLUTE_Z":
            self.state.z = self.state.target_z = p1
        elif command_type == "ABSOLUTE_XY":
            self.state.x = self.state.target_x = p1
            self.state.y = self.state.target_y = p2
        elif command_type == "SET_AXIS_MAXSPEED":
            attr = ("x_max_hz", "y_max_hz", "z_max_hz")[p1]
            setattr(self.state, attr, p2)
        elif command_type == "SET_AXIS_ACCEL":
            attr = ("x_accel", "y_accel", "z_accel")[p1]
            setattr(self.state, attr, p2)
        elif command_type == "ABSOLUTE_PRESSURE_P":
            self.state.current_print_pressure_raw = p1
            self.state.target_print_pressure_raw = p1
        elif command_type == "ABSOLUTE_PRESSURE_R":
            self.state.current_refuel_pressure_raw = p1
            self.state.target_refuel_pressure_raw = p1
        elif command_type == "RELATIVE_PRESSURE_R":
            direction = 1 if int(p1) == 1 else -1
            updated = self.state.target_refuel_pressure_raw + direction * int(p2)
            updated = min(max(updated, self.psi_offset), 10376)
            self.state.current_refuel_pressure_raw = updated
            self.state.target_refuel_pressure_raw = updated
        elif command_type == "SET_WIDTH_P":
            self.state.print_pulse_width_us = p1
        elif command_type == "SET_WIDTH_R":
            self.state.refuel_pulse_width_us = p1
        elif command_type == "ENABLE_PRINT_PROFILE":
            self.state.print_profile_enabled = True
            self.state.deferred_gripper_refresh_enabled = p1 == 1
        elif command_type == "DISABLE_PRINT_PROFILE":
            self.state.print_profile_enabled = False
            self.state.deferred_gripper_refresh_enabled = False
        elif command_type in {"DISPENSE", "DISPENSE_PRINT", "DISPENSE_REFUEL"}:
            self.state.dispense_frequency_hz = max(1, p2)
        elif command_type == "OPEN_GRIPPER":
            self.state.gripper_open = True
            self.state.gripper_active = True
            self.gripper_open.emit()
        elif command_type == "CLOSE_GRIPPER":
            self.state.gripper_open = False
            self.state.gripper_active = True
            self.gripper_closed.emit()
        elif command_type == "GRIPPER_OFF":
            self.state.gripper_active = False
            self.gripper_off_signal.emit()

    def _fail_execution(self, command: SimulatedCommand):
        message = (
            f"configured execution failure at command {command.command_number} "
            f"({command.command_type})"
        )
        self._emit_error(message)
        self._cancel_all_commands(clear_history=False, reset_counter=False)
        payload = {
            "reason": "configured_execution_failure",
            "command_number": command.command_number,
            "command_type": command.command_type,
        }
        self.simulation_faulted.emit(dict(payload))

    def _cancel_all_commands(self, *, clear_history: bool, reset_counter: bool):
        self._command_timer.stop()
        self._active_command = None
        self._pause_after_request = None
        self._suppress_drain_once = True
        highest_retired = self.state.last_retired
        for command in list(self.command_queue.queue):
            if command.status not in {"Completed", "Canceled"}:
                self.command_queue.transition(
                    command,
                    "canceled",
                    self.state.simulated_elapsed_ms,
                )
                highest_retired = max(highest_retired, command.command_number)
        self.state.last_retired = highest_retired
        self.state.current_command = highest_retired
        self.state.command_depth = 0
        self.command_queue.trim_terminal_commands()
        if clear_history:
            self.command_queue.clear_queue(reset_counter=reset_counter)
        else:
            if reset_counter:
                self.command_queue.command_number = 0
            self.command_queue.queue_updated.emit()
        self._emit_status()

    def _maybe_emit_successful_drain(self):
        if self._suppress_drain_once:
            self._suppress_drain_once = False
            return
        if self._nonterminal_depth() == 0 and not self._drain_emitted:
            self._drain_emitted = True
            self.command_queue.commands_completed.emit()

    def check_if_all_completed(self):
        return self._nonterminal_depth() == 0 and self._active_command is None

    def get_remaining_commands(self):
        return self._nonterminal_depth()

    def update_command_numbers(
        self,
        current_command,
        last_completed,
        last_accepted=None,
        last_retired=None,
    ):
        # The simulator is the authoritative source of these counters. The real
        # Controller feeds its Model values back through this production-shaped
        # method; returning the current values keeps that feedback idempotent.
        del current_command, last_completed, last_accepted, last_retired
        return (
            self.state.current_command,
            self.state.last_completed,
            self.state.last_accepted,
            self.state.last_retired,
        )

    def send_next_command(self):
        self._pump()

    def set_sequence_pause(self, paused: bool):
        self._sequence_pause = bool(paused)
        if not self._sequence_pause:
            self._pump()
        return True

    def pause_commands(self):
        self.state.transport_paused = True
        self.state.pause_watermark_reached = False
        self._emit_status()
        return True

    def pause_machine(self):
        return self.pause_commands()

    def resume_commands(self):
        watermark_already_reached = bool(self.state.pause_watermark_reached)
        self.state.transport_paused = False
        if watermark_already_reached:
            self._pause_after_request = None
            self.state.pause_after_seq32 = 0
            self.state.pause_watermark_reached = False
        elif self._pause_after_request is None:
            self.state.pause_after_seq32 = 0
            self.state.pause_watermark_reached = False
        self._emit_status()
        self._pump()
        return True

    def request_pause_after_seq32(
        self,
        barrier_seq32,
        on_success=None,
        on_failure=None,
    ):
        try:
            barrier = int(barrier_seq32)
        except (TypeError, ValueError):
            barrier = 0
        if barrier <= 0:
            if callable(on_failure):
                self._defer(
                    lambda: on_failure(
                        {
                            "reason": "invalid_barrier",
                            "barrier_seq32": barrier,
                        }
                    )
                )
            return False

        pending_numbers = {
            command.command_number
            for command in self.command_queue.queue
            if command.status not in {"Completed", "Canceled"}
        }
        if barrier <= self.state.last_retired or barrier not in pending_numbers:
            if callable(on_failure):
                self._defer(
                    lambda: on_failure(
                        {
                            "reason": "ack_rejected",
                            "ack_result": "watermark_rejected",
                            "barrier_seq32": barrier,
                        }
                    )
                )
            return True

        self._pause_after_request = {
            "barrier_seq32": barrier,
            "on_success": on_success,
            "on_failure": on_failure,
        }
        self.state.pause_after_seq32 = barrier
        self.state.pause_watermark_reached = False
        self._emit_status()
        return True

    def clear_command_queue(self, handler=None):
        last_completed = self.state.last_completed
        self._cancel_all_commands(clear_history=True, reset_counter=False)
        self.state.last_completed = last_completed
        self.state.pause_after_seq32 = 0
        self.state.pause_watermark_reached = False
        self.state.transport_paused = False
        self._emit_status()
        result = {
            "ack_received": True,
            "ack_timed_out": False,
            "status_confirmed": True,
            "status_timed_out": False,
        }
        if callable(handler):
            self._defer(lambda: handler(dict(result)))
        return True

    def _check_axis(self, axis_idx):
        try:
            axis = int(axis_idx)
        except (TypeError, ValueError):
            return None
        return axis if axis in (0, 1, 2) else None

    def _queue(
        self,
        command_type,
        param1=0,
        param2=0,
        param3=0,
        *,
        handler=None,
        kwargs=None,
        manual=False,
        trace_metadata=None,
    ):
        return self.add_command_to_queue(
            command_type,
            param1,
            param2,
            param3,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
            trace_metadata=trace_metadata,
        )

    def enable_motors(self, handler=None, kwargs=None, manual=False):
        return self._queue(
            "ENABLE_MOTORS", handler=handler, kwargs=kwargs, manual=manual
        )

    def disable_motors(self, handler=None, kwargs=None, manual=False):
        return self._queue(
            "DISABLE_MOTORS", handler=handler, kwargs=kwargs, manual=manual
        )

    def home_motors(self, handler=None, kwargs=None, manual=False):
        first = self._queue("HOME_Z", manual=manual)
        second = self._queue("HOME_XY", manual=manual)
        third = self._queue(
            "HOME_PR_BOTH",
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )
        return bool(first and second and third)

    def home_regulators(self, handler=None, kwargs=None, manual=False):
        return self._queue(
            "HOME_PR_BOTH",
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def regulate_print_pressure(self, handler=None, kwargs=None, manual=False):
        return self._queue(
            "REGULATE_PRESSURE_P",
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def regulate_refuel_pressure(self, handler=None, kwargs=None, manual=False):
        return self._queue(
            "REGULATE_PRESSURE_R",
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def deregulate_print_pressure(self, handler=None, kwargs=None, manual=False):
        return self._queue(
            "DEREGULATE_PRESSURE_P",
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def deregulate_refuel_pressure(self, handler=None, kwargs=None, manual=False):
        return self._queue(
            "DEREGULATE_PRESSURE_R",
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def set_absolute_XY(self, x, y, handler=None, kwargs=None, manual=False):
        try:
            x_value = int(x)
            y_value = int(y)
        except (TypeError, ValueError):
            return self._emit_error("absolute XY coordinates must be integers")
        return self._queue(
            "ABSOLUTE_XY",
            x_value,
            y_value,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def set_absolute_X(self, x, handler=None, kwargs=None, manual=False):
        try:
            x_value = int(x)
        except (TypeError, ValueError):
            return self._emit_error("absolute X coordinate must be an integer")
        return self._queue(
            "ABSOLUTE_X",
            x_value,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def set_absolute_Y(self, y, handler=None, kwargs=None, manual=False):
        try:
            y_value = int(y)
        except (TypeError, ValueError):
            return self._emit_error("absolute Y coordinate must be an integer")
        return self._queue(
            "ABSOLUTE_Y",
            y_value,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def set_absolute_Z(self, z, handler=None, kwargs=None, manual=False):
        try:
            z_value = int(z)
        except (TypeError, ValueError):
            return self._emit_error("absolute Z coordinate must be an integer")
        return self._queue(
            "ABSOLUTE_Z",
            z_value,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def set_axis_maxspeed(self, axis_idx, max_speed):
        axis = self._check_axis(axis_idx)
        try:
            speed = int(max_speed)
        except (TypeError, ValueError):
            speed = -1
        if axis is None or speed < 0:
            return self._emit_error("axis max-speed parameters are out of range")
        return self._queue("SET_AXIS_MAXSPEED", axis, speed)

    def set_axis_accel(
        self,
        axis_idx,
        accel,
        handler=None,
        kwargs=None,
        manual=False,
    ):
        axis = self._check_axis(axis_idx)
        try:
            acceleration = int(accel)
        except (TypeError, ValueError):
            acceleration = -1
        if axis is None or acceleration < 0:
            return self._emit_error("axis acceleration parameters are out of range")
        return self._queue(
            "SET_AXIS_ACCEL",
            axis,
            acceleration,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def convert_to_raw_pressure(self, psi):
        return int(round((float(psi) / self.psi_max) * self.fss + self.psi_offset))

    def convert_to_psi(self, pressure):
        return round(
            ((float(pressure) - self.psi_offset) / self.fss) * self.psi_max,
            4,
        )

    def set_absolute_print_pressure(
        self,
        psi,
        handler=None,
        kwargs=None,
        manual=False,
        trace_metadata=None,
    ):
        try:
            raw_pressure = self.convert_to_raw_pressure(psi)
        except (TypeError, ValueError, OverflowError):
            return self._emit_error("absolute print pressure must be numeric")
        if not 0 <= raw_pressure <= 10376:
            return self._emit_error("absolute print pressure is out of range")
        return self._queue(
            "ABSOLUTE_PRESSURE_P",
            raw_pressure,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
            trace_metadata=trace_metadata,
        )

    def set_absolute_refuel_pressure(
        self,
        psi,
        handler=None,
        kwargs=None,
        manual=False,
        trace_metadata=None,
    ):
        try:
            raw_pressure = self.convert_to_raw_pressure(psi)
        except (TypeError, ValueError, OverflowError):
            return self._emit_error("absolute refuel pressure must be numeric")
        if not self.psi_offset <= raw_pressure <= 10376:
            return self._emit_error("absolute refuel pressure is out of range")
        return self._queue(
            "ABSOLUTE_PRESSURE_R",
            raw_pressure,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
            trace_metadata=trace_metadata,
        )

    def set_print_pulse_width(
        self,
        pulse_width,
        handler=None,
        kwargs=None,
        manual=False,
        trace_metadata=None,
    ):
        try:
            width = int(pulse_width)
        except (TypeError, ValueError):
            width = -1
        if not 100 <= width <= 10000:
            return self._emit_error("print pulse width must be between 100 and 10000 us")
        return self._queue(
            "SET_WIDTH_P",
            width,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
            trace_metadata=trace_metadata,
        )

    def set_refuel_pulse_width(
        self,
        pulse_width,
        handler=None,
        kwargs=None,
        manual=False,
        trace_metadata=None,
    ):
        try:
            width = int(pulse_width)
        except (TypeError, ValueError):
            width = -1
        if not 100 <= width <= 10000:
            return self._emit_error("refuel pulse width must be between 100 and 10000 us")
        return self._queue(
            "SET_WIDTH_R",
            width,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
            trace_metadata=trace_metadata,
        )

    def enable_print_profile(
        self,
        handler=None,
        kwargs=None,
        manual=False,
        *,
        deferred_gripper_refresh=False,
    ):
        return self._queue(
            "ENABLE_PRINT_PROFILE",
            1 if bool(deferred_gripper_refresh) else 0,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def disable_print_profile(self, handler=None, kwargs=None, manual=False):
        return self._queue(
            "DISABLE_PRINT_PROFILE",
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def enter_print_mode(self, handler=None, kwargs=None, manual=False):
        return self.enable_print_profile(handler, kwargs, manual)

    def exit_print_mode(self, handler=None, kwargs=None, manual=False):
        return self.disable_print_profile(handler, kwargs, manual)

    def wait_ms(self, ms, handler=None, kwargs=None, manual=False):
        try:
            duration = int(ms)
        except (TypeError, ValueError):
            duration = -1
        if not 1 <= duration <= 600000:
            return self._emit_error("wait duration must be between 1 and 600000 ms")
        return self._queue(
            "WAIT",
            duration,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def wait_command(self, handler=None, kwargs=None, manual=False):
        return self.wait_ms(
            200,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def _get_dispense_rate_hz(self):
        machine_model = getattr(self.model, "machine_model", None)
        getter = getattr(machine_model, "get_dispense_frequency_hz", None)
        try:
            rate = getter() if callable(getter) else 20
        except Exception:
            rate = 20
        return max(1, int(rate))

    def print_droplets(
        self,
        droplet_count,
        handler=None,
        kwargs=None,
        manual=False,
    ):
        try:
            droplets = int(droplet_count)
        except (TypeError, ValueError):
            droplets = -1
        if not 1 <= droplets <= 1000:
            return self._emit_error("droplet count must be between 1 and 1000")
        return self._queue(
            "DISPENSE",
            droplets,
            self._get_dispense_rate_hz(),
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def open_gripper(self, handler=None, kwargs=None, manual=False):
        return self._queue(
            "OPEN_GRIPPER",
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def close_gripper(self, handler=None, kwargs=None, manual=False):
        return self._queue(
            "CLOSE_GRIPPER",
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def gripper_off(self, handler=None, kwargs=None, manual=False):
        return self._queue(
            "GRIPPER_OFF",
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def confirm_gripper_ready(self):
        return True

    # Explicitly unsupported application actions. Controller simulation guards
    # should reject these before they reach the machine; these methods are the
    # fail-visible backstop for direct calls.
    def set_relative_X(self, *args, **kwargs):
        return self._unsupported("relative X motion")

    def set_relative_Y(self, *args, **kwargs):
        return self._unsupported("relative Y motion")

    def set_relative_Z(self, *args, **kwargs):
        return self._unsupported("relative Z motion")

    def set_relative_print_pressure(self, *args, **kwargs):
        return self._unsupported("relative print pressure")

    def set_relative_refuel_pressure(
        self,
        psi,
        handler=None,
        kwargs=None,
        manual=False,
    ):
        try:
            raw_delta = self.convert_to_raw_pressure(psi) - self.psi_offset
        except (TypeError, ValueError, OverflowError):
            return self._emit_error("relative refuel pressure must be numeric")
        if not -2185 <= raw_delta <= 2185:
            return self._emit_error("relative refuel pressure is out of range")
        sign = 1 if raw_delta >= 0 else 0
        return self._queue(
            "RELATIVE_PRESSURE_R",
            sign,
            abs(raw_delta),
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def start_refuel_camera(self):
        return self._unsupported("refuel camera")

    def capture_refuel_image(self):
        return self._unsupported("refuel camera capture")

    def stop_refuel_camera(self):
        return self._unsupported("refuel camera")

    def refuel_led_on(self):
        return self._unsupported("refuel camera LED")

    def refuel_led_off(self):
        return self._unsupported("refuel camera LED")

    def start_droplet_camera(self):
        return self._unsupported("droplet camera")

    def capture_droplet_image(self, *args, **kwargs):
        return self._unsupported("droplet camera capture")

    def stop_droplet_camera(self):
        return self._unsupported("droplet camera")

    def start_read_camera(self, *args, **kwargs):
        return self._unsupported("read camera")

    def stop_read_camera(self, *args, **kwargs):
        return self._unsupported("read camera")

    def connect_balance(self, *args, **kwargs):
        return self._unsupported("balance connection")

    def disconnect_balance(self, *args, **kwargs):
        return self._unsupported("balance connection")

    def reset_mcu_board(self):
        return self._unsupported("MCU reset")

    def update_firmware(self, *args, **kwargs):
        return self._unsupported("firmware update")

    def print_calibration_droplets(self, *args, **kwargs):
        return self._unsupported("calibration dispensing")

    def _queue_single_valve_dispense(
        self,
        command_type,
        droplet_count,
        *,
        handler=None,
        kwargs=None,
        manual=False,
    ):
        try:
            droplets = int(droplet_count)
        except (TypeError, ValueError):
            droplets = -1
        if not 1 <= droplets <= 1000:
            return self._emit_error("droplet count must be between 1 and 1000")
        return self._queue(
            command_type,
            droplets,
            self._get_dispense_rate_hz(),
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def print_only(
        self,
        droplet_count,
        handler=None,
        kwargs=None,
        manual=False,
    ):
        return self._queue_single_valve_dispense(
            "DISPENSE_PRINT",
            droplet_count,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def refuel_only(
        self,
        droplet_count,
        handler=None,
        kwargs=None,
        manual=False,
    ):
        return self._queue_single_valve_dispense(
            "DISPENSE_REFUEL",
            droplet_count,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )


def make_simulated_machine_factory(config: SimulationConfig | None = None):
    """Return the explicit safe factory accepted by simulation_dependencies."""

    resolved_config = config or SimulationConfig()
    if not isinstance(resolved_config, SimulationConfig):
        raise TypeError("config must be a SimulationConfig")
    return partial(SimulatedMachine, config=resolved_config)
