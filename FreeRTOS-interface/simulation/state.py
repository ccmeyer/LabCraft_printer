"""Configuration and state for the hardware-free application simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Mapping


SIMULATED_PORT = "SIMULATED"


_MOTION_COMMANDS = frozenset(
    {
        "ABSOLUTE_X",
        "ABSOLUTE_Y",
        "ABSOLUTE_Z",
        "ABSOLUTE_XY",
    }
)
_HOMING_COMMANDS = frozenset({"HOME_Z", "HOME_XY", "HOME_PR_BOTH"})
_GRIPPER_COMMANDS = frozenset({"OPEN_GRIPPER", "CLOSE_GRIPPER", "GRIPPER_OFF"})


def _normalized_duration_overrides(value) -> Mapping[str, int]:
    if value is None:
        items = ()
    elif isinstance(value, Mapping):
        items = value.items()
    else:
        items = value

    normalized: dict[str, int] = {}
    for command_type, duration_ms in items:
        key = str(command_type or "").strip().upper()
        if not key:
            raise ValueError("duration override command types must not be empty")
        duration = int(duration_ms)
        if duration < 0:
            raise ValueError("duration overrides must be non-negative")
        normalized[key] = duration
    return MappingProxyType(normalized)


@dataclass(frozen=True)
class SimulationTimingPolicy:
    """Simulated durations and their wall-clock acceleration policy."""

    speed_multiplier: float = 1.0
    connection_duration_ms: int = 10
    generic_duration_ms: int = 5
    motion_duration_ms: int = 25
    homing_phase_duration_ms: int = 50
    gripper_duration_ms: int = 10
    duration_overrides: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self):
        speed = float(self.speed_multiplier)
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("speed_multiplier must be finite and greater than zero")
        object.__setattr__(self, "speed_multiplier", speed)

        for name in (
            "connection_duration_ms",
            "generic_duration_ms",
            "motion_duration_ms",
            "homing_phase_duration_ms",
            "gripper_duration_ms",
        ):
            value = int(getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
            object.__setattr__(self, name, value)

        object.__setattr__(
            self,
            "duration_overrides",
            _normalized_duration_overrides(self.duration_overrides),
        )

    def simulated_duration_ms(
        self,
        command_type: str,
        param1: int = 0,
        param2: int = 0,
        param3: int = 0,
    ) -> int:
        del param3
        command = str(command_type or "").strip().upper()
        override = self.duration_overrides.get(command)
        if override is not None:
            return int(override)
        if command == "WAIT":
            return max(0, int(param1))
        if command in {"DISPENSE", "DISPENSE_PRINT", "DISPENSE_REFUEL"}:
            droplets = max(0, int(param1))
            rate_hz = max(1, int(param2))
            return max(1, int(math.ceil(1000.0 * droplets / rate_hz)))
        if command in _MOTION_COMMANDS:
            return self.motion_duration_ms
        if command in _HOMING_COMMANDS:
            return self.homing_phase_duration_ms
        if command in _GRIPPER_COMMANDS:
            return self.gripper_duration_ms
        return self.generic_duration_ms

    def wall_delay_ms(self, simulated_duration_ms: int) -> int:
        duration = max(0, int(simulated_duration_ms))
        return max(1, int(math.ceil(duration / self.speed_multiplier)))


@dataclass(frozen=True)
class SimulationFaultPlan:
    """Deterministic, instance-local failures used by simulator tests."""

    reject_command_types: frozenset[str] = field(default_factory=frozenset)
    fail_command_numbers: frozenset[int] = field(default_factory=frozenset)

    def __post_init__(self):
        rejected = frozenset(
            str(command or "").strip().upper()
            for command in self.reject_command_types
            if str(command or "").strip()
        )
        failed = frozenset(int(number) for number in self.fail_command_numbers)
        if any(number <= 0 for number in failed):
            raise ValueError("fail_command_numbers must contain only positive integers")
        object.__setattr__(self, "reject_command_types", rejected)
        object.__setattr__(self, "fail_command_numbers", failed)


@dataclass(frozen=True)
class SimulationConfig:
    timing: SimulationTimingPolicy = field(default_factory=SimulationTimingPolicy)
    faults: SimulationFaultPlan = field(default_factory=SimulationFaultPlan)
    max_inflight_commands: int = 4
    completed_history_limit: int = 100
    event_history_limit: int = 512

    def __post_init__(self):
        for name in (
            "max_inflight_commands",
            "completed_history_limit",
            "event_history_limit",
        ):
            value = int(getattr(self, name))
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")
            object.__setattr__(self, name, value)


@dataclass
class SimulatedMachineState:
    connected: bool = False
    motors_enabled: bool = False
    homed: bool = False

    x: int = 0
    y: int = 0
    z: int = 0
    p: int = 0
    r: int = 0
    target_x: int = 0
    target_y: int = 0
    target_z: int = 0
    target_p: int = 0
    target_r: int = 0

    current_print_pressure_raw: int = 0
    current_refuel_pressure_raw: int = 0
    target_print_pressure_raw: int = 0
    target_refuel_pressure_raw: int = 0
    regulating_print_pressure: bool = False
    regulating_refuel_pressure: bool = False
    print_pulse_width_us: int = 0
    refuel_pulse_width_us: int = 0
    dispense_frequency_hz: int = 20

    x_max_hz: int = 0
    y_max_hz: int = 0
    z_max_hz: int = 0
    x_accel: int = 0
    y_accel: int = 0
    z_accel: int = 0

    print_profile_enabled: bool = False
    deferred_gripper_refresh_enabled: bool = False
    gripper_open: bool = False
    gripper_active: bool = False

    current_command: int = 0
    last_completed: int = 0
    last_accepted: int = 0
    last_retired: int = 0
    command_depth: int = 0
    pause_after_seq32: int = 0
    pause_watermark_reached: bool = False
    transport_paused: bool = False
    simulated_elapsed_ms: int = 0

    def status_payload(self) -> dict:
        return {
            "X": self.x,
            "Y": self.y,
            "Z": self.z,
            "P": self.p,
            "R": self.r,
            "Tar_X": self.target_x,
            "Tar_Y": self.target_y,
            "Tar_Z": self.target_z,
            "Tar_P": self.target_p,
            "Tar_R": self.target_r,
            "Pressure_P": self.current_print_pressure_raw,
            "Pressure_R": self.current_refuel_pressure_raw,
            "Tar_print": self.target_print_pressure_raw,
            "Tar_refuel": self.target_refuel_pressure_raw,
            "print_active": self.regulating_print_pressure,
            "refuel_active": self.regulating_refuel_pressure,
            "Print_width": self.print_pulse_width_us,
            "Refuel_width": self.refuel_pulse_width_us,
            "Disp_freq": self.dispense_frequency_hz,
            "X_max_hz": self.x_max_hz,
            "Y_max_hz": self.y_max_hz,
            "Z_max_hz": self.z_max_hz,
            "X_accel": self.x_accel,
            "Y_accel": self.y_accel,
            "Z_accel": self.z_accel,
            "Current_command": self.current_command,
            "Last_completed": self.last_completed,
            "Last_accepted": self.last_accepted,
            "Last_retired": self.last_retired,
            "cmd_depth": self.command_depth,
            "Pause_after_seq32": self.pause_after_seq32,
            "Pause_watermark_reached": self.pause_watermark_reached,
            "Transport_paused": self.transport_paused,
            "Micros": self.simulated_elapsed_ms * 1000,
            # Simulator-only observability. The real Model safely ignores these.
            "Motors_enabled": self.motors_enabled,
            "Homed": self.homed,
            "Print_profile_enabled": self.print_profile_enabled,
            "Deferred_gripper_refresh_enabled": self.deferred_gripper_refresh_enabled,
            "Grip_open": self.gripper_open,
            "Grip_active": self.gripper_active,
            "Simulation_connected": self.connected,
        }
