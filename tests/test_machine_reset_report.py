from types import SimpleNamespace

from Machine_FreeRTOS import Machine


def test_machine_on_reset_report_stores_and_emits(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    seen = []
    machine.reset_report_received.connect(seen.append)

    report = {
        "summary": "Board restarted after watchdog reset.",
        "reset_cause_name": "iwdg",
    }

    machine._on_reset_report(report)

    assert machine._last_reset_report == report
    assert seen == [report]
