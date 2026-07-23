import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtTest

from simulation import (
    SIMULATED_PORT,
    SimulatedMachine,
    SimulationConfig,
    SimulationFaultPlan,
    SimulationTimingPolicy,
    make_simulated_machine_factory,
)


def _wait_until(qapp, predicate, *, timeout_ms=3000):
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        QtTest.QTest.qWait(1)
    qapp.processEvents()
    assert predicate(), "condition did not become true before timeout"


def _make_machine(qapp, test_profile, *, config=None):
    model = SimpleNamespace(
        machine_model=SimpleNamespace(get_dispense_frequency_hz=lambda: 20)
    )
    machine = SimulatedMachine(
        model,
        profile=test_profile,
        serial_factory=lambda: pytest.fail("serial factory was called"),
        refuel_camera_factory=lambda: pytest.fail("refuel camera factory was called"),
        droplet_camera_factory=lambda: pytest.fail("droplet camera factory was called"),
        log_reader_factory=lambda: pytest.fail("log reader factory was called"),
        config=config
        or SimulationConfig(
            timing=SimulationTimingPolicy(speed_multiplier=1000.0)
        ),
    )
    assert machine.connect_board(SIMULATED_PORT) is True
    _wait_until(qapp, lambda: machine.state.connected)
    return machine


def test_timing_policy_defaults_validation_and_duration_calculation():
    policy = SimulationTimingPolicy()

    assert policy.speed_multiplier == 1.0
    assert policy.connection_duration_ms == 10
    assert policy.generic_duration_ms == 5
    assert policy.motion_duration_ms == 25
    assert policy.homing_phase_duration_ms == 50
    assert policy.gripper_duration_ms == 10
    assert policy.simulated_duration_ms("WAIT", 42) == 42
    assert policy.simulated_duration_ms("DISPENSE", 3, 20) == 150
    assert policy.simulated_duration_ms("ABSOLUTE_X", 100) == 25
    assert policy.simulated_duration_ms("HOME_Z") == 50
    assert policy.wall_delay_ms(0) == 1

    accelerated = SimulationTimingPolicy(
        speed_multiplier=100.0,
        duration_overrides={"WAIT": 777},
    )
    assert accelerated.simulated_duration_ms("wait", 12) == 777
    assert accelerated.wall_delay_ms(777) == 8

    for value in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="speed_multiplier"):
            SimulationTimingPolicy(speed_multiplier=value)
    with pytest.raises(ValueError, match="greater than zero"):
        SimulationConfig(max_inflight_commands=0)
    with pytest.raises(ValueError, match="positive integers"):
        SimulationFaultPlan(fail_command_numbers={0})


def test_factory_is_explicit_and_preserves_configuration(test_profile):
    config = SimulationConfig(
        timing=SimulationTimingPolicy(speed_multiplier=321.0)
    )
    factory = make_simulated_machine_factory(config)
    model = SimpleNamespace(machine_model=SimpleNamespace())

    machine = factory(
        model,
        profile=test_profile,
        serial_factory=object(),
        refuel_camera_factory=object(),
        droplet_camera_factory=object(),
        log_reader_factory=object(),
    )

    assert isinstance(machine, SimulatedMachine)
    assert machine.config is config
    assert machine.state.connected is False


def test_lifecycle_order_lookahead_histories_and_single_drain(
    qapp,
    test_profile,
):
    config = SimulationConfig(
        timing=SimulationTimingPolicy(
            speed_multiplier=1000.0,
            duration_overrides={"WAIT": 5},
        ),
        completed_history_limit=3,
        event_history_limit=200,
    )
    machine = _make_machine(qapp, test_profile, config=config)
    drains = []
    machine.command_queue.commands_completed.connect(lambda: drains.append("done"))

    commands = [machine.wait_ms(10) for _ in range(6)]

    assert [command.command_number for command in commands] == [1, 2, 3, 4, 5, 6]
    assert commands[0].status == "Executing"
    assert [command.status for command in commands[1:4]] == [
        "Accepted",
        "Accepted",
        "Accepted",
    ]
    assert [command.status for command in commands[4:]] == ["Added", "Added"]

    _wait_until(qapp, machine.check_if_all_completed)

    assert drains == ["done"]
    assert [command.command_number for command in machine.command_queue.completed] == [
        4,
        5,
        6,
    ]
    for command in commands:
        events = [
            event["event"]
            for event in machine.command_event_history
            if event["command_number"] == command.command_number
        ]
        assert events == ["queued", "sent", "accepted", "executing", "completed"]
        assert command._handler_called is True


def test_qt_event_loop_remains_live_during_wait(qapp, test_profile):
    config = SimulationConfig(
        timing=SimulationTimingPolicy(speed_multiplier=1.0)
    )
    machine = _make_machine(qapp, test_profile, config=config)
    heartbeats = []
    completed = []
    heartbeat = QtCore.QTimer()
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda: heartbeats.append(time.monotonic()))
    heartbeat.start()

    machine.wait_ms(80, handler=lambda: completed.append("done"))
    _wait_until(qapp, lambda: bool(completed), timeout_ms=1000)
    heartbeat.stop()

    assert len(heartbeats) >= 3
    assert completed == ["done"]


def test_supported_commands_update_state_and_callbacks(qapp, test_profile):
    machine = _make_machine(qapp, test_profile)
    callbacks = []
    gripper_events = []
    home_events = []
    machine.gripper_closed.connect(lambda: gripper_events.append("closed"))
    machine.homing_completed.connect(lambda: home_events.append("home"))

    assert machine.enable_motors()
    assert machine.home_motors(handler=lambda: callbacks.append("homed"))
    assert machine.regulate_print_pressure()
    assert machine.regulate_refuel_pressure()
    assert machine.set_absolute_print_pressure(1.2)
    assert machine.set_absolute_refuel_pressure(0.3)
    assert machine.set_print_pulse_width(1400)
    assert machine.set_refuel_pulse_width(2200)
    assert machine.set_axis_maxspeed(0, 15000)
    assert machine.set_axis_accel(1, 12000)
    assert machine.set_absolute_XY(1234, 5678)
    assert machine.set_absolute_Z(4321)
    assert machine.enable_print_profile()
    assert machine.close_gripper()
    assert machine.print_droplets(4, handler=lambda: callbacks.append("dispensed"))

    _wait_until(qapp, machine.check_if_all_completed)

    assert machine.state.motors_enabled is True
    assert machine.state.homed is True
    assert (machine.state.x, machine.state.y, machine.state.z) == (1234, 5678, 4321)
    assert machine.state.regulating_print_pressure is True
    assert machine.state.regulating_refuel_pressure is True
    assert machine.convert_to_psi(machine.state.target_print_pressure_raw) == pytest.approx(
        1.2, abs=0.001
    )
    assert machine.convert_to_psi(machine.state.target_refuel_pressure_raw) == pytest.approx(
        0.3, abs=0.001
    )
    assert machine.state.print_pulse_width_us == 1400
    assert machine.state.refuel_pulse_width_us == 2200
    assert machine.state.x_max_hz == 15000
    assert machine.state.y_accel == 12000
    assert machine.state.print_profile_enabled is True
    assert machine.state.gripper_active is True
    assert callbacks == ["homed", "dispensed"]
    assert gripper_events == ["closed"]
    assert home_events == ["home"]


def test_completion_handler_can_extend_queue_and_runs_once(qapp, test_profile):
    machine = _make_machine(qapp, test_profile)
    callbacks = []
    drains = []
    machine.command_queue.commands_completed.connect(lambda: drains.append("done"))

    def _first_complete():
        callbacks.append("first")
        machine.wait_ms(3, handler=lambda: callbacks.append("second"))

    first = machine.wait_ms(3, handler=_first_complete)
    _wait_until(qapp, machine.check_if_all_completed)

    assert first._handler_called is True
    assert callbacks == ["first", "second"]
    assert drains == ["done"]


def test_immediate_pause_finishes_active_then_resume_continues(qapp, test_profile):
    config = SimulationConfig(
        timing=SimulationTimingPolicy(
            speed_multiplier=1.0,
            duration_overrides={"WAIT": 30},
        )
    )
    machine = _make_machine(qapp, test_profile, config=config)
    completed = []
    for number in range(3):
        machine.wait_ms(5, handler=lambda n=number: completed.append(n))

    assert machine.pause_commands() is True
    _wait_until(qapp, lambda: machine.state.last_completed == 1)
    QtTest.QTest.qWait(50)
    qapp.processEvents()

    assert completed == [0]
    assert machine.get_remaining_commands() == 2
    assert machine.state.transport_paused is True

    assert machine.resume_commands() is True
    _wait_until(qapp, machine.check_if_all_completed)
    assert completed == [0, 1, 2]


def test_sequence_pause_prevents_start_until_released(qapp, test_profile):
    machine = _make_machine(qapp, test_profile)
    completed = []

    machine.set_sequence_pause(True)
    command = machine.wait_ms(5, handler=lambda: completed.append("done"))
    QtTest.QTest.qWait(10)
    qapp.processEvents()
    assert command.status == "Accepted"
    assert completed == []

    machine.set_sequence_pause(False)
    _wait_until(qapp, machine.check_if_all_completed)
    assert completed == ["done"]


def test_pause_after_barrier_stops_and_stale_barrier_fails(
    qapp,
    test_profile,
):
    machine = _make_machine(qapp, test_profile)
    completed = []
    successes = []
    failures = []
    commands = [
        machine.wait_ms(5, handler=lambda n=number: completed.append(n))
        for number in range(3)
    ]

    assert machine.request_pause_after_seq32(
        commands[1].command_number,
        on_success=successes.append,
        on_failure=failures.append,
    )
    _wait_until(
        qapp,
        lambda: machine.state.pause_watermark_reached
        and machine.state.transport_paused,
    )

    assert completed == [0, 1]
    assert machine.get_remaining_commands() == 1
    assert successes == [
        {
            "barrier_seq32": commands[1].command_number,
            "status_confirmed": True,
        }
    ]
    assert failures == []

    machine.resume_commands()
    _wait_until(qapp, machine.check_if_all_completed)
    assert completed == [0, 1, 2]

    assert machine.request_pause_after_seq32(
        commands[0].command_number,
        on_failure=failures.append,
    )
    _wait_until(qapp, lambda: bool(failures))
    assert failures[-1]["reason"] == "ack_rejected"
    assert failures[-1]["ack_result"] == "watermark_rejected"


def test_clear_cancels_without_handlers_and_confirms_once(qapp, test_profile):
    config = SimulationConfig(
        timing=SimulationTimingPolicy(
            speed_multiplier=1.0,
            duration_overrides={"WAIT": 100},
        )
    )
    machine = _make_machine(qapp, test_profile, config=config)
    command_callbacks = []
    clear_callbacks = []
    drains = []
    machine.command_queue.commands_completed.connect(lambda: drains.append("done"))
    commands = [
        machine.wait_ms(10, handler=lambda n=number: command_callbacks.append(n))
        for number in range(3)
    ]

    assert machine.clear_command_queue(handler=clear_callbacks.append) is True
    _wait_until(qapp, lambda: bool(clear_callbacks))
    QtTest.QTest.qWait(120)
    qapp.processEvents()

    assert command_callbacks == []
    assert [command.status for command in commands] == [
        "Canceled",
        "Canceled",
        "Canceled",
    ]
    assert clear_callbacks == [
        {
            "ack_received": True,
            "ack_timed_out": False,
            "status_confirmed": True,
            "status_timed_out": False,
        }
    ]
    assert drains == []
    assert machine.command_queue.command_number == 3
    assert machine.get_remaining_commands() == 0


def test_disconnect_cancels_timer_and_resets_session(qapp, test_profile):
    config = SimulationConfig(
        timing=SimulationTimingPolicy(
            speed_multiplier=1.0,
            duration_overrides={"WAIT": 100},
        )
    )
    machine = _make_machine(qapp, test_profile, config=config)
    completed = []
    command = machine.wait_ms(10, handler=lambda: completed.append("done"))

    assert machine.disconnect_board() is True
    QtTest.QTest.qWait(120)
    qapp.processEvents()

    assert command.status == "Canceled"
    assert completed == []
    assert machine.state.connected is False
    assert machine.command_queue.command_number == 0
    assert machine._command_timer.isActive() is False

    assert machine.connect_board(SIMULATED_PORT)
    _wait_until(qapp, lambda: machine.state.connected)
    next_command = machine.wait_ms(1)
    assert next_command.command_number == 1
    _wait_until(qapp, machine.check_if_all_completed)


def test_fault_plans_are_idle_only_instance_local_and_resettable(
    qapp,
    test_profile,
):
    machine = _make_machine(qapp, test_profile)
    other = _make_machine(qapp, test_profile)
    errors = []
    faults = []
    machine.error_occurred.connect(errors.append)
    machine.simulation_faulted.connect(faults.append)

    assert machine.configure_faults(
        SimulationFaultPlan(
            reject_command_types={"WAIT"},
            fail_command_numbers={2},
        )
    )
    assert machine.wait_ms(1) is False
    assert other.wait_ms(1)
    _wait_until(qapp, other.check_if_all_completed)

    assert machine.configure_faults(
        SimulationFaultPlan(fail_command_numbers={1})
    )
    failed = machine.print_droplets(1)
    assert machine.configure_faults(SimulationFaultPlan()) is False
    _wait_until(qapp, machine.check_if_all_completed)

    assert failed.status == "Canceled"
    assert faults[-1]["reason"] == "configured_execution_failure"
    assert errors
    assert machine.reset_faults() is True
    assert machine.wait_ms(1)
    _wait_until(qapp, machine.check_if_all_completed)


def test_unsupported_actions_and_physical_ports_fail_without_mutation(
    qapp,
    test_profile,
):
    model = SimpleNamespace(
        machine_model=SimpleNamespace(get_dispense_frequency_hz=lambda: 20)
    )
    machine = SimulatedMachine(model, profile=test_profile)
    errors = []
    machine.error_occurred.connect(errors.append)

    assert machine.connect_board("COM7") is False
    assert machine.state.connected is False
    assert machine.command_queue.command_number == 0

    assert machine.connect_board(SIMULATED_PORT)
    _wait_until(qapp, lambda: machine.state.connected)
    before = machine.state.status_payload()
    assert machine.set_relative_X(5) is False
    assert machine.start_droplet_camera() is False
    assert machine.add_command_to_queue("RAW_FRAME", 1, 2, 3) is False
    assert machine.set_absolute_X("not-an-integer") is False
    assert machine.set_print_pulse_width(None) is False

    assert machine.state.status_payload() == before
    assert machine.command_queue.command_number == 0
    assert len(errors) == 6
    assert all(message.startswith("Simulation:") for message in errors)


def test_simulator_import_does_not_load_hardware_or_protocol_modules():
    repo_root = Path(__file__).resolve().parents[1]
    ui_root = repo_root / "FreeRTOS-interface"
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(ui_root)!r})\n"
        "import simulation\n"
        "forbidden = {'Machine_FreeRTOS', 'serial', 'serial.tools', "
        "'RPi', 'RPi.GPIO', 'gpiozero'}\n"
        "loaded = sorted(name for name in forbidden if name in sys.modules)\n"
        "raise SystemExit('loaded forbidden modules: ' + repr(loaded) if loaded else 0)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    source = (ui_root / "simulation" / "machine.py").read_text(encoding="utf-8")
    assert "from Machine_FreeRTOS" not in source
    assert "import Machine_FreeRTOS" not in source
    assert "import serial" not in source
