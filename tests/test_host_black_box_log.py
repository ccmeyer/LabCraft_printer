import json
import time
from types import SimpleNamespace

import Machine_FreeRTOS as mfr


class _DummySerial:
    def __init__(self):
        self.is_open = True
        self.close_calls = 0

    def reset_input_buffer(self):
        return None

    def close(self):
        self.close_calls += 1
        self.is_open = False


class _DummyTimer:
    def __init__(self):
        self.stop_calls = 0
        self.delete_calls = 0

    def stop(self):
        self.stop_calls += 1
        return None

    def deleteLater(self):
        self.delete_calls += 1
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


def test_orchestrator_stack_status_tlvs_decode_with_phase_name():
    payload = bytearray()
    payload.extend([mfr.TAG_ORCH_STACK_HWM, 2])
    payload.extend((0).to_bytes(2, "little"))
    payload.extend([mfr.TAG_ORCH_STACK_PHASE, 1, 4])
    payload.extend([mfr.TAG_ORCH_STACK_CMD, 4])
    payload.extend((182).to_bytes(4, "little"))

    decoded = mfr.parse_tlv_payload(bytes(payload))

    assert decoded["Orch_stack_hwm_words"] == 0
    assert decoded["Orch_stack_phase"] == 4
    assert decoded["Orch_stack_cmd"] == 182
    assert mfr.orch_stack_phase_name(decoded["Orch_stack_phase"]) == "abs_xy_wait_x"


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
            "Pressure_P": 2162,
            "Pressure_R": 1900,
            "Tar_print": 2162,
            "Tar_refuel": 1900,
            "X": 100,
            "Y": 200,
            "Z": 300,
            "Tar_X": 110,
            "Tar_Y": 210,
            "Tar_Z": 310,
            "Print_width": 1300,
            "Refuel_width": 3000,
            "Disp_freq": 10,
            "print_active": 1,
            "refuel_active": 1,
            "drop_total": 5,
            "drop_remain": 2,
            "Orch_stack_hwm_words": 0,
            "Orch_stack_phase": 4,
            "Orch_stack_cmd": command.command_number,
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

    machine._flash_state = {
        "flash_session_armed": False,
        "flash_fault_latched": True,
        "flash_fault_reason": "flash_ack_timeout",
    }

    report = {"summary": "Board restarted after watchdog reset.", "reset_cause_name": "iwdg"}

    machine._on_reset_report(report)

    snapshot = _read_single_snapshot(tmp_path)
    snapshot_history = machine.black_box_recorder.recent_snapshots()
    assert len(snapshot_history) == 1
    assert snapshot_history[0]["reason"] == "reset_report"
    assert snapshot_history[0]["session_id"] == machine.black_box_recorder.session_id
    assert snapshot["schema_version"] == "host_black_box_v1"
    assert snapshot["reason"] == "reset_report"
    assert snapshot["last_reset_report"] == report
    assert snapshot["flash_state"] == {
        "flash_session_armed": False,
        "flash_fault_latched": True,
        "flash_fault_reason": "flash_ack_timeout",
    }
    assert snapshot["transport"]["port"] == "COM9"
    assert snapshot["transport"]["serial_open"] is True
    assert snapshot["transport"]["command_queue_depth"] == 1
    assert snapshot["commands"]["queued"][0]["command_type"] == "LED_ON"
    assert snapshot["commands"]["queued"][0]["param1"] == 1
    assert snapshot["status_history"][-1]["Current_command"] == command.command_number
    assert snapshot["status_history"][-1]["Pressure_P"] == 2162
    assert snapshot["status_history"][-1]["Pressure_R"] == 1900
    assert snapshot["status_history"][-1]["Tar_print"] == 2162
    assert snapshot["status_history"][-1]["X"] == 100
    assert snapshot["status_history"][-1]["Tar_X"] == 110
    assert snapshot["status_history"][-1]["Print_width"] == 1300
    assert snapshot["status_history"][-1]["print_active"] == 1
    assert snapshot["status_history"][-1]["drop_remain"] == 2
    assert snapshot["status_history"][-1]["Orch_stack_hwm_words"] == 0
    assert snapshot["status_history"][-1]["Orch_stack_phase"] == 4
    assert snapshot["status_history"][-1]["Orch_stack_phase_name"] == "abs_xy_wait_x"
    assert snapshot["status_history"][-1]["Orch_stack_cmd"] == command.command_number
    assert snapshot["status_history"][-1]["Orch_phase"] == 4
    assert snapshot["status_history"][-1]["Orch_phase_name"] == "abs_xy_wait_x"
    assert snapshot["status_history"][-1]["Orch_cmd"] == command.command_number
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


def test_unclean_serial_loss_after_established_session_emits_and_clears_state(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    lost_reports = []
    connected_states = []
    machine.serial_connection_lost.connect(lost_reports.append)
    machine.machine_connected_signal.connect(connected_states.append)
    command = machine.command_queue.add_command("LED_ON", 1, 2, 3)
    ack_timer = _DummyTimer()
    machine._pending_acks[(123, 456, -1)] = {"timer": ack_timer, "ok": None, "to": None}
    machine._transport_ready = True
    machine._tx_paused = False

    machine._on_serial_reader_stopped({"reason": "serial_closed", "requested_stop": False})

    assert connected_states == [False]
    assert len(lost_reports) == 1
    report = lost_reports[0]
    assert report["reason"] == "serial_closed"
    assert report["port"] == "COM9"
    assert report["black_box_log_path"]
    assert report["black_box_log_error"] is None
    assert machine.ser is None
    assert machine.port is None
    assert machine.reader is None
    assert machine._transport_ready is False
    assert machine._tx_paused is True
    assert len(machine.command_queue.queue) == 0
    assert machine._pending_acks == {}
    assert ack_timer.stop_calls == 1
    assert ack_timer.delete_calls == 1

    snapshot = _read_single_snapshot(tmp_path)
    assert snapshot["transport"]["command_queue_depth"] == 1
    assert snapshot["commands"]["queued"][0]["command_number"] == command.command_number


def test_serial_closed_before_hello_snapshots_without_connection_loss(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    lost_reports = []
    connected_states = []
    machine.serial_connection_lost.connect(lost_reports.append)
    machine.machine_connected_signal.connect(connected_states.append)
    machine._transport_ready = False

    machine._on_serial_reader_stopped({"reason": "serial_closed", "requested_stop": False})

    snapshot = _read_single_snapshot(tmp_path)
    assert snapshot["reason"] == "serial_reader_stopped"
    assert lost_reports == []
    assert connected_states == []


def test_requested_serial_reader_stop_is_recorded_without_snapshot(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    lost_reports = []
    machine.serial_connection_lost.connect(lost_reports.append)

    machine._on_serial_reader_stopped({"reason": "requested_stop", "requested_stop": True})

    assert list(tmp_path.glob("*.json")) == []
    assert lost_reports == []
    assert machine.black_box_recorder.recent_events()[-1]["kind"] == "serial_reader_stopped"


def test_expected_serial_close_is_recorded_without_loss_popup(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    lost_reports = []
    machine.serial_connection_lost.connect(lost_reports.append)

    machine.disconnect_handler()
    machine._on_serial_reader_stopped({"reason": "serial_closed", "requested_stop": False})

    assert list(tmp_path.glob("*.json")) == []
    assert lost_reports == []
    assert any(
        event["kind"] == "serial_reader_stop_expected"
        for event in machine.black_box_recorder.recent_events()
    )


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


def test_unclean_serial_loss_with_log_write_failure_still_emits_and_clears(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    lost_reports = []
    machine.serial_connection_lost.connect(lost_reports.append)
    machine._transport_ready = True
    machine.command_queue.add_command("LED_ON", 0, 0, 0)
    machine.black_box_recorder.write_snapshot = lambda _snapshot: {"path": None, "error": "disk unavailable"}

    machine._on_serial_reader_stopped(
        {
            "reason": "exception",
            "requested_stop": False,
            "exception_type": "OSError",
            "message": "device disconnected",
        }
    )

    assert len(lost_reports) == 1
    assert lost_reports[0]["black_box_log_path"] is None
    assert lost_reports[0]["black_box_log_error"] == "disk unavailable"
    assert "OSError" in lost_reports[0]["summary"]
    assert len(machine.command_queue.queue) == 0


def test_mcu_unresponsive_after_established_session_emits_and_preserves_serial(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    lost_reports = []
    connected_states = []
    machine.serial_connection_lost.connect(lost_reports.append)
    machine.machine_connected_signal.connect(connected_states.append)
    command = machine.command_queue.add_command("LED_ON", 1, 2, 3)
    ack_timer = _DummyTimer()
    machine._pending_acks[(mfr.CMD_QUEUE_ACK, command.command_number, -1)] = {
        "timer": ack_timer,
        "ok": None,
        "to": None,
    }
    now_ns = time.monotonic_ns()
    machine._transport_ready = True
    machine._tx_paused = False
    machine._last_mcu_rx_monotonic_ns = now_ns - 3_000_000_000
    machine._last_mcu_rx_kind = "status"

    machine._check_mcu_response_health(now_ns=now_ns)

    assert connected_states == [False]
    assert len(lost_reports) == 1
    report = lost_reports[0]
    assert report["reason"] == "mcu_unresponsive"
    assert report["trigger_reason"] == "no_mcu_frames"
    assert report["black_box_reason"] == "mcu_unresponsive"
    assert report["black_box_log_path"]
    assert "no valid frames received" in report["summary"]
    assert machine.ser is not None
    assert machine.ser.is_open is True
    assert machine.port == "COM9"
    assert machine.reader is None
    assert machine._transport_ready is False
    assert machine._tx_paused is True
    assert len(machine.command_queue.queue) == 0
    assert machine._pending_acks == {}
    assert ack_timer.stop_calls == 1
    assert ack_timer.delete_calls == 1

    snapshot = _read_single_snapshot(tmp_path)
    assert snapshot["reason"] == "mcu_unresponsive"
    assert snapshot["transport"]["serial_open"] is True
    assert snapshot["transport"]["command_queue_depth"] == 1
    assert snapshot["commands"]["queued"][0]["command_number"] == command.command_number
    assert any(event["kind"] == "mcu_unresponsive" for event in snapshot["black_box_events"])


def test_recent_status_prevents_mcu_unresponsive_detection(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    lost_reports = []
    machine.serial_connection_lost.connect(lost_reports.append)
    old_ns = time.monotonic_ns() - 3_000_000_000
    machine._transport_ready = True
    machine._last_mcu_rx_monotonic_ns = old_ns
    machine._last_mcu_rx_kind = "status"

    machine.update_status({"Current_command": 0, "Last_completed": 0, "cmd_depth": 0})
    now_ns = machine._last_mcu_rx_monotonic_ns + 1_000_000_000
    machine._check_mcu_response_health(now_ns=now_ns)

    assert lost_reports == []
    assert list(tmp_path.glob("*.json")) == []
    assert machine._transport_ready is True


def test_reset_report_after_mcu_unresponsive_still_writes_reset_snapshot(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    lost_reports = []
    reset_reports = []
    machine.serial_connection_lost.connect(lost_reports.append)
    machine.reset_report_received.connect(reset_reports.append)
    now_ns = time.monotonic_ns()
    machine._transport_ready = True
    machine._last_mcu_rx_monotonic_ns = now_ns - 3_000_000_000

    machine._check_mcu_response_health(now_ns=now_ns)
    report = {"summary": "Board restarted after external reset pin event.", "reset_cause_name": "pin_reset"}
    machine._on_reset_report(report)

    snapshots = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(tmp_path.glob("*.json"))
    ]
    assert [item["reason"] for item in snapshots] == ["mcu_unresponsive", "reset_report"]
    assert lost_reports[0]["reason"] == "mcu_unresponsive"
    assert reset_reports == [report]


def test_mcu_unresponsive_write_failure_still_emits_and_clears(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    lost_reports = []
    machine.serial_connection_lost.connect(lost_reports.append)
    machine._transport_ready = True
    machine.command_queue.add_command("LED_ON", 0, 0, 0)
    machine.black_box_recorder.write_snapshot = lambda _snapshot: {"path": None, "error": "disk unavailable"}
    now_ns = time.monotonic_ns()
    machine._last_mcu_rx_monotonic_ns = now_ns - 3_000_000_000

    machine._check_mcu_response_health(now_ns=now_ns)

    assert len(lost_reports) == 1
    assert lost_reports[0]["black_box_log_path"] is None
    assert lost_reports[0]["black_box_log_error"] == "disk unavailable"
    assert len(machine.command_queue.queue) == 0
    assert any(event["kind"] == "black_box_log_write_failed" for event in machine.black_box_recorder.recent_events())
