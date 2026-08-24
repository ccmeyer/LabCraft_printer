from types import SimpleNamespace

import Machine_FreeRTOS as mfr
from simulation import SimulatedMachine, SimulationConfig


def _production_machine(test_profile):
    return mfr.Machine(SimpleNamespace(), profile=test_profile)


def _simulated_machine(test_profile):
    return SimulatedMachine(
        SimpleNamespace(machine_model=SimpleNamespace()),
        profile=test_profile,
        config=SimulationConfig(),
    )


def _queue_absolute_xy(machine):
    return machine.command_queue.add_command("ABSOLUTE_XY", -4, -722, 30000)


def test_production_and_simulation_active_command_snapshots_have_identical_shape(
    qapp,
    test_profile,
):
    production = _production_machine(test_profile)
    simulation = _simulated_machine(test_profile)
    production_command = _queue_absolute_xy(production)
    simulation_command = _queue_absolute_xy(simulation)

    expected = {
        "command_number": 1,
        "command_type": "ABSOLUTE_XY",
        "param1": -4,
        "param2": -722,
        "param3": 30000,
        "status": "Added",
    }
    assert production.get_active_command_snapshot(production_command.command_number) == expected
    assert simulation.get_active_command_snapshot(simulation_command.command_number) == expected


def test_active_command_snapshot_reflects_lifecycle_without_machine_traffic(
    qapp,
    test_profile,
):
    production = _production_machine(test_profile)
    simulation = _simulated_machine(test_profile)
    production_command = _queue_absolute_xy(production)
    simulation_command = _queue_absolute_xy(simulation)

    production_command.mark_as_executing()
    simulation.command_queue.transition(simulation_command, "executing", 10)

    assert production.get_active_command_snapshot(1)["status"] == "Executing"
    assert simulation.get_active_command_snapshot(1)["status"] == "Executing"


def test_terminal_unknown_and_invalid_commands_are_not_exposed_as_active(
    qapp,
    test_profile,
):
    production = _production_machine(test_profile)
    simulation = _simulated_machine(test_profile)
    production_command = _queue_absolute_xy(production)
    simulation_command = _queue_absolute_xy(simulation)
    production_command.mark_as_completed()
    simulation.command_queue.transition(simulation_command, "completed", 20)

    for machine in (production, simulation):
        assert machine.get_active_command_snapshot(1) is None
        assert machine.get_active_command_snapshot(999) is None
        assert machine.get_active_command_snapshot("not-a-sequence") is None
