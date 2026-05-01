import time
from types import SimpleNamespace

from Machine_FreeRTOS import Machine


def test_clear_queue_timeout_keeps_tx_blocked_until_clear_status(qapp, test_profile, fake_serial_main):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    machine.ser = fake_serial_main
    machine.command_queue.add_command("WAIT", 1, 0, 0)

    machine.clear_command_queue()
    machine._on_clear_ack(timed_out=True)

    assert machine._tx_paused is True
    assert machine._waiting_for_post_clear_status is True
    assert len(machine.command_queue.queue) == 0

    machine.update_status({"cmd_depth": 1, "Current_command": 9, "Last_completed": 8})
    assert machine._tx_paused is True

    machine.update_status(
        {
            "cmd_depth": 0,
            "Current_command": 9,
            "Last_completed": 8,
            "Last_retired": 9,
        }
    )
    assert machine._tx_paused is False


def test_clear_queue_handler_fires_after_status_confirmation(qapp, test_profile, fake_serial_main):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    machine.ser = fake_serial_main
    payloads = []

    machine.clear_command_queue(handler=lambda payload: payloads.append(dict(payload or {})))
    machine._on_clear_ack(timed_out=False)

    assert payloads == []

    machine.update_status(
        {
            "cmd_depth": 0,
            "Current_command": 9,
            "Last_completed": 8,
            "Last_retired": 9,
        }
    )

    assert payloads == [
        {
            "ack_received": True,
            "ack_timed_out": False,
            "status_confirmed": True,
            "status_timed_out": False,
        }
    ]


def test_clear_queue_confirmation_realigns_host_command_counter(qapp, test_profile, fake_serial_main):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    machine.ser = fake_serial_main
    for idx in range(12):
        machine.command_queue.add_command("WAIT", idx + 1, 0, 0)

    machine.clear_command_queue()
    machine._on_clear_ack(timed_out=False)
    assert machine.command_queue.command_number == 12

    machine.update_status(
        {
            "cmd_depth": 0,
            "Current_command": 7,
            "Last_completed": 6,
            "Last_retired": 7,
        }
    )

    assert machine.command_queue.command_number == 7
    next_command = machine.wait_ms(10)
    assert next_command.command_number == 8


def test_clear_queue_handler_reports_late_status_confirmation_after_ack_timeout(qapp, test_profile, fake_serial_main):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    machine.ser = fake_serial_main
    payloads = []

    machine.clear_command_queue(handler=lambda payload: payloads.append(dict(payload or {})))
    machine._on_clear_ack(timed_out=True)

    assert payloads == []

    machine.update_status(
        {
            "cmd_depth": 0,
            "Current_command": 9,
            "Last_completed": 8,
            "Last_retired": 9,
        }
    )

    assert payloads == [
        {
            "ack_received": False,
            "ack_timed_out": True,
            "status_confirmed": True,
            "status_timed_out": False,
        }
    ]


def test_clear_queue_handler_reports_unconfirmed_clear_after_status_timeout(qapp, test_profile, fake_serial_main):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    machine.ser = fake_serial_main
    payloads = []

    machine.clear_command_queue(handler=lambda payload: payloads.append(dict(payload or {})))
    machine._on_clear_ack(timed_out=True)
    machine._wait_for_clear_status_deadline = time.time() - 1

    machine.update_status(
        {
            "cmd_depth": 1,
            "Current_command": 9,
            "Last_completed": 8,
            "Last_retired": 9,
        }
    )

    assert payloads == [
        {
            "ack_received": False,
            "ack_timed_out": True,
            "status_confirmed": False,
            "status_timed_out": True,
        }
    ]


def test_global_accel_helpers_fail_fast_with_clear_error(qapp, test_profile, fake_serial_main):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    machine.ser = fake_serial_main
    errors = []
    machine.error_occurred.connect(errors.append)

    assert machine.change_acceleration(16000) is False
    assert machine.reset_acceleration() is False

    assert "CHANGE_ACCEL is not supported" in errors[0]
    assert "RESET_ACCEL is not supported" in errors[1]
