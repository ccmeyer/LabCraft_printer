from types import SimpleNamespace

from Machine_FreeRTOS import Machine

from tests.fakes.fake_serial import FakeSerialMain


def test_clear_queue_timeout_keeps_tx_blocked_until_clear_status(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    machine.ser = FakeSerialMain()
    machine.command_queue.add_command("WAIT", 1, 0, 0)

    machine.clear_command_queue()
    machine._on_clear_ack(timed_out=True)

    assert machine._tx_paused is True
    assert machine._waiting_for_post_clear_status is True
    assert len(machine.command_queue.queue) == 0

    machine.update_status({"cmd_depth": 1, "Current_command": 9, "Last_completed": 8})
    assert machine._tx_paused is True

    machine.update_status({"cmd_depth": 0, "Current_command": 0, "Last_completed": 0})
    assert machine._tx_paused is False
