import numpy as np

from Model import MachineModel


def test_machine_model_busy_free_from_command_numbers(qapp):
    machine_model = MachineModel()
    emissions = []
    machine_model.command_numbers_updated.connect(lambda: emissions.append(1))

    machine_model.update_command_numbers(5, 3)
    assert machine_model.machine_free is False

    machine_model.update_command_numbers(5, 5)
    assert machine_model.machine_free is True
    assert len(emissions) == 2


def test_disconnect_machine_resets_safety_state(qapp):
    machine_model = MachineModel()
    machine_model.machine_connected = True
    machine_model.motors_enabled = True
    machine_model.regulating_print_pressure = True
    machine_model.regulating_refuel_pressure = True
    machine_model.motors_homed = True
    machine_model.current_location = "Somewhere"

    machine_model.disconnect_machine()

    assert machine_model.machine_connected is False
    assert machine_model.motors_enabled is False
    assert machine_model.regulating_print_pressure is False
    assert machine_model.regulating_refuel_pressure is False
    assert machine_model.motors_homed is False
    assert machine_model.current_location == "Unknown"


def test_pressure_conversion_and_rolling_buffers(qapp):
    machine_model = MachineModel()
    initial = machine_model.print_pressure_readings.copy()

    machine_model.update_print_pressure(machine_model.psi_offset)
    assert machine_model.current_print_pressure == 0.0
    assert machine_model.print_pressure_readings[-1] == 0.0
    assert np.array_equal(machine_model.print_pressure_readings[:-1], initial[1:])

    machine_model.update_refuel_pressure(machine_model.psi_offset + machine_model.fss)
    assert machine_model.current_refuel_pressure == machine_model.psi_max
    assert machine_model.refuel_pressure_readings[-1] == machine_model.psi_max
