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


def test_recover_after_board_reset_preserves_banner_and_clears_transient_state(qapp):
    machine_model = MachineModel()
    machine_model.machine_connected = True
    machine_model.motors_enabled = True
    machine_model.regulating_print_pressure = True
    machine_model.regulating_refuel_pressure = True
    machine_model.paused = True
    machine_model.machine_free = False
    machine_model.current_command_num = 7
    machine_model.last_completed_command_num = 3
    machine_model.motors_homed = True
    machine_model.current_location = "Home"
    machine_model.update_last_reset_report({"summary": "watchdog reset"})

    machine_model.recover_after_board_reset()

    assert machine_model.machine_connected is False
    assert machine_model.motors_enabled is False
    assert machine_model.regulating_print_pressure is False
    assert machine_model.regulating_refuel_pressure is False
    assert machine_model.paused is False
    assert machine_model.machine_free is True
    assert machine_model.current_command_num == 0
    assert machine_model.last_completed_command_num == 0
    assert machine_model.motors_homed is False
    assert machine_model.current_location == "Unknown"
    assert machine_model.last_reset_report_active is True
    assert machine_model.last_reset_summary == "watchdog reset"


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


def test_update_regulation_state_tracks_both_channels_and_emits_once(qapp):
    machine_model = MachineModel()
    emissions = []
    machine_model.regulation_state_changed.connect(lambda active: emissions.append(active))

    machine_model.update_regulation_state(1, 0)

    assert machine_model.regulating_print_pressure is True
    assert machine_model.regulating_refuel_pressure is False
    assert emissions == [True]

    machine_model.update_regulation_state(True, False)
    assert emissions == [True]


def test_dispense_frequency_defaults_and_updates(qapp):
    machine_model = MachineModel()
    emissions = []
    machine_model.printing_parameters_updated.connect(
        lambda: emissions.append(machine_model.get_dispense_frequency_hz())
    )

    assert machine_model.get_dispense_frequency_hz() == 20

    machine_model.update_dispense_frequency_hz(10)

    assert machine_model.get_dispense_frequency_hz() == 10
    assert emissions == [10]
