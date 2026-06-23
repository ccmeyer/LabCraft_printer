import json
import time
from types import SimpleNamespace

import Machine_FreeRTOS as mfr


class _DummySerial:
    is_open = True

    def reset_input_buffer(self):
        return None


class _DummyTimer:
    def stop(self):
        return None

    def deleteLater(self):
        return None


def _make_machine(qapp, test_profile, tmp_path):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile, black_box_log_dir=tmp_path)
    machine.ser = _DummySerial()
    machine.port = "COM9"
    machine._begin_recovery_handshake = lambda: None
    return machine


def _read_single_snapshot(tmp_path):
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_reset_report_writes_snapshot_before_recovery_clears_session_state(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    emitted = []
    machine.reset_report_received.connect(emitted.append)

    command = machine.command_queue.add_command("LED_ON", 1, 2, 3)
    host_rx_ns = time.monotonic_ns()
    machine.update_status(
        {
            "__host_rx_monotonic_ns": host_rx_ns,
            "Current_command": command.command_number,
            "Last_completed": 0,
            "Last_accepted": command.command_number,
            "Last_retired": 0,
            "cmd_depth": 1,
        }
    )

    ack_key = machine._ack_key(mfr.HELLO_ACK, 42)
    machine._pending_acks[ack_key] = {"timer": _DummyTimer(), "ok": lambda _ack: None, "to": lambda: None}
    machine._on_any_ack(
        {
            "ack_cmd": mfr.HELLO_ACK,
            "seq8": 1,
            "seq32": 42,
            "ack_result": None,
            "expected_seq32": None,
            "capabilities": mfr.REQUIRED_TRANSPORT_CAPS,
        }
    )

    report = {"summary": "Board restarted after watchdog reset.", "reset_cause_name": "iwdg"}

    machine._on_reset_report(report)

    snapshot = _read_single_snapshot(tmp_path)
    assert snapshot["schema_version"] == "host_black_box_v1"
    assert snapshot["reason"] == "reset_report"
    assert snapshot["last_reset_report"] == report
    assert snapshot["transport"]["port"] == "COM9"
    assert snapshot["transport"]["serial_open"] is True
    assert snapshot["transport"]["command_queue_depth"] == 1
    assert snapshot["commands"]["queued"][0]["command_type"] == "LED_ON"
    assert snapshot["commands"]["queued"][0]["param1"] == 1
    assert snapshot["status_history"][-1]["Current_command"] == command.command_number
    assert any(event["event"] == "queued" and event["request_id"] is None for event in snapshot["command_events"])
    assert any(event["kind"] == "ack" and event["payload"]["matched_pending"] for event in snapshot["black_box_events"])
    assert any(event["kind"] == "reset_report" for event in snapshot["black_box_events"])
    assert emitted == [report]
    assert len(machine.command_queue.queue) == 0


def test_abnormal_serial_reader_stop_writes_snapshot(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)

    machine._on_serial_reader_stopped(
        {
            "reason": "exception",
            "requested_stop": False,
            "exception_type": "OSError",
            "message": "device disconnected",
        }
    )

    snapshot = _read_single_snapshot(tmp_path)
    assert snapshot["reason"] == "serial_reader_stopped"
    assert snapshot["trigger"]["reason"] == "exception"
    assert any(event["kind"] == "serial_reader_stopped" for event in snapshot["black_box_events"])


def test_requested_serial_reader_stop_is_recorded_without_snapshot(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)

    machine._on_serial_reader_stopped({"reason": "requested_stop", "requested_stop": True})

    assert list(tmp_path.glob("*.json")) == []
    assert machine.black_box_recorder.recent_events()[-1]["kind"] == "serial_reader_stopped"


def test_black_box_log_write_failure_does_not_block_reset_recovery(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    emitted = []
    machine.reset_report_received.connect(emitted.append)
    machine.command_queue.add_command("LED_ON", 0, 0, 0)
    machine.black_box_recorder.write_snapshot = lambda _snapshot: {"path": None, "error": "disk unavailable"}

    report = {"summary": "Board restarted after power/brownout reset.", "reset_cause_name": "power"}

    machine._on_reset_report(report)

    assert emitted == [report]
    assert machine._last_black_box_log_result == {"path": None, "error": "disk unavailable"}
    assert len(machine.command_queue.queue) == 0
    assert any(event["kind"] == "black_box_log_write_failed" for event in machine.black_box_recorder.recent_events())
