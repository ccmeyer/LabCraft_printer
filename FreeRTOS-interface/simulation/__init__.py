"""Explicit hardware-free machine implementation for application verification."""

from .machine import (
    SimulatedCommand,
    SimulatedCommandQueue,
    SimulatedMachine,
    make_simulated_machine_factory,
)
from .state import (
    SIMULATED_PORT,
    SimulatedMachineState,
    SimulationConfig,
    SimulationFaultPlan,
    SimulationTimingPolicy,
)

__all__ = [
    "SIMULATED_PORT",
    "SimulatedCommand",
    "SimulatedCommandQueue",
    "SimulatedMachine",
    "SimulatedMachineState",
    "SimulationConfig",
    "SimulationFaultPlan",
    "SimulationTimingPolicy",
    "make_simulated_machine_factory",
]
