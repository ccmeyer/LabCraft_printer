from types import SimpleNamespace

from Machine_FreeRTOS import Machine


def test_machine_on_reset_report_stores_clears_and_restarts_hello(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    seen = []
    recovery = []
    machine.reset_report_received.connect(seen.append)
    machine.command_queue.add_command("OPEN_GRIPPER", 0, 0, 0)
    machine._pending_acks[(0xF4, 7)] = {"timer": SimpleNamespace(stop=lambda: None, deleteLater=lambda: None)}
    machine.ser = SimpleNamespace(is_open=True, reset_input_buffer=lambda: None)
    machine._begin_recovery_handshake = lambda: recovery.append("hello")

    report = {
        "summary": "Board restarted after watchdog reset.",
        "reset_cause_name": "iwdg",
    }

    machine._on_reset_report(report)

    assert machine._last_reset_report == report
    assert seen == [report]
    assert recovery == ["hello"]
    assert list(machine.command_queue.queue) == []
    assert machine._pending_acks == {}
