from types import SimpleNamespace

import Machine_FreeRTOS as mfr
from Machine_FreeRTOS import Machine


def _benign_startup_report(**overrides):
    report = {
        "summary": "Board restarted after software reset.",
        "reset_cause": 3,
        "reset_cause_name": "software",
        "flags": 5,
        "reset_flags_raw": 0x14000003,
        "pending": False,
        "sticky": True,
        "recovery_boot": True,
        "last_fault": 0,
        "last_fault_name": "none",
        "fault_context": None,
        "xy_motion_context": None,
        "active_command": 0,
        "boot_count": 48,
        "fault_count": 13,
        "watchdog_reset_count": 13,
        "watchdog_sticky_count": 48,
        "watchdog_raw_status": 0xA5,
        "uptime_ms": 987654,
    }
    report.update(overrides)
    return report


def _with_host_context(report, *, phase, classification):
    enriched = dict(report)
    enriched["host_context"] = {
        "connection_phase": phase,
        "classification": classification,
    }
    return enriched


def test_reset_report_classifier_accepts_exact_initial_recovery_signature():
    report = _benign_startup_report()

    assert (
        mfr.classify_reset_report_for_host(
            report,
            connection_phase=mfr.HOST_CONNECTION_PHASE_INITIAL,
        )
        == mfr.HOST_RESET_CLASSIFICATION_BENIGN_STARTUP
    )


def test_reset_report_classifier_rejects_later_and_unsafe_variants():
    base = _benign_startup_report()
    assert (
        mfr.classify_reset_report_for_host(
            base,
            connection_phase=mfr.HOST_CONNECTION_PHASE_ESTABLISHED,
        )
        == mfr.HOST_RESET_CLASSIFICATION_ACTIONABLE
    )

    unsafe_variants = [
        {"pending": True, "flags": 7},
        {"reset_cause": 4, "reset_cause_name": "iwdg"},
        {"last_fault": 1, "last_fault_name": "hardfault"},
        {"fault_context": {"pc": 0x08000000}},
        {"xy_motion_context": {"reason_name": "x_limit"}},
        {"active_command": 7},
        {"recovery_boot": False},
        {"reset_flags_raw": 0x1C000003},
        {"reset_flags_raw": "0x14000003"},
        {"flags": 4},
    ]
    for overrides in unsafe_variants:
        report = dict(base)
        report.update(overrides)
        assert (
            mfr.classify_reset_report_for_host(
                report,
                connection_phase=mfr.HOST_CONNECTION_PHASE_INITIAL,
            )
            == mfr.HOST_RESET_CLASSIFICATION_ACTIONABLE
        )

    malformed = dict(base)
    malformed.pop("last_fault")
    assert (
        mfr.classify_reset_report_for_host(
            malformed,
            connection_phase=mfr.HOST_CONNECTION_PHASE_INITIAL,
        )
        == mfr.HOST_RESET_CLASSIFICATION_ACTIONABLE
    )


def test_hello_phase_stays_initial_until_transport_has_been_ready(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    machine._write_frame = lambda _frame: None
    machine._start_ack_wait = lambda *args, **kwargs: None

    machine._send_hello()
    assert machine._hello_connection_phase == mfr.HOST_CONNECTION_PHASE_INITIAL

    machine._send_hello()
    assert machine._hello_connection_phase == mfr.HOST_CONNECTION_PHASE_INITIAL

    machine.ser = SimpleNamespace(name="COM_TEST")
    machine._start_mcu_response_watchdog = lambda: None
    machine.begin_execution_timer = lambda: None
    machine.pump_send_queue = lambda: None
    machine._on_hello_ack({"capabilities": mfr.REQUIRED_TRANSPORT_CAPS})

    assert machine._ever_transport_ready is True
    machine._send_hello()
    assert machine._hello_connection_phase == mfr.HOST_CONNECTION_PHASE_ESTABLISHED


def test_machine_on_reset_report_stores_clears_and_restarts_hello(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    seen = []
    recovery = []
    machine.reset_report_received.connect(seen.append)
    machine.command_queue.add_command("OPEN_GRIPPER", 0, 0, 0)
    machine._pending_acks[(0xF4, 7)] = {"timer": SimpleNamespace(stop=lambda: None, deleteLater=lambda: None)}
    machine.ser = SimpleNamespace(
        is_open=True,
        reset_input_buffer=lambda: (_ for _ in ()).throw(
            AssertionError("reset recovery must not flush the live reader")
        ),
    )
    machine._begin_recovery_handshake = lambda: recovery.append("hello")

    report = {
        "summary": "Board restarted after watchdog reset.",
        "reset_cause_name": "iwdg",
    }

    machine._on_reset_report(report)

    expected = _with_host_context(
        report,
        phase=mfr.HOST_CONNECTION_PHASE_ESTABLISHED,
        classification=mfr.HOST_RESET_CLASSIFICATION_ACTIONABLE,
    )
    assert machine._last_reset_report == expected
    assert seen == [expected]
    assert recovery == ["hello"]
    assert list(machine.command_queue.queue) == []
    assert machine._pending_acks == {}
