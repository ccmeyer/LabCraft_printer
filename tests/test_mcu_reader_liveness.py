"""No hardware: exercise the real parser, Qt delivery and production watchdog."""
import threading
import struct
import time
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt

import Machine_FreeRTOS as mfr
from tests.fakes.fake_serial import FakeSerialMain
from test_host_black_box_log import _make_machine, _read_single_snapshot
from test_serial_reader import _frame, _reset_report_payload


@pytest.mark.parametrize("fault", ["reset", "status"])
def test_ack_cannot_dispatch_before_later_received_fault(qapp, test_profile, tmp_path, fault):
    machine = _make_machine(qapp, test_profile, tmp_path)
    machine.ser = LiveSerial()
    reader = machine.reader = mfr.SerialReader(machine.ser)
    reader.ackReceived.connect(machine._on_any_ack, Qt.QueuedConnection)
    reader.resetReportReceived.connect(machine._on_reset_report, Qt.QueuedConnection)
    reader.status_received.connect(machine.update_status, Qt.QueuedConnection)
    machine._transport_ready = True
    machine._tx_paused = False
    machine.command_queue.add_command("ABSOLUTE_XY", 0, 0, 0)
    machine.send_command_to_board = Mock(return_value=False)
    seen = []
    def ack_callback():
        machine.pump_send_queue()
        seen.append(reader.receive_snapshot())
    machine._start_ack_wait(mfr.CLEAR_ACK, 7, 10000, on_ok=ack_callback, on_timeout=lambda: None)
    # Queue both callbacks before Qt is allowed to deliver either one.
    ack = mfr.SerialReader._parse_ack(bytes([mfr.CLEAR_ACK, 7, mfr.ACK_TLV_SEQ32, 4]) + struct.pack("<I", 7))
    reader.stamp_frame(ack, "ack")
    reader.ackReceived.emit(ack)
    if fault == "reset":
        report = reader._parse_reset_report(_reset_report_payload(0))
        reader.stamp_frame(report, "reset_report")
        reader.resetReportReceived.emit(report)
    else:
        status = {"Transport_paused": True, "cmd_depth": 0, "Current_command": 1,
                  "Last_accepted": 1, "Last_retired": 1, "Last_completed": 0}
        reader.stamp_frame(status, "status")
        reader.status_received.emit(status)
    machine._check_mcu_response_health()
    assert not machine._mcu_unresponsive_reported
    qapp.processEvents()
    assert seen and seen[0]["processed_count"] == 0
    assert reader.receive_snapshot()["processed_count"] == 2
    machine.send_command_to_board.assert_not_called()
    assert machine._tx_paused or not machine._transport_ready


def test_replaced_connection_ignores_queued_status_ack_reset_and_stop(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    old = machine.reader = mfr.SerialReader(machine.ser)
    old.status_received.connect(machine.update_status, Qt.QueuedConnection)
    old.ackReceived.connect(machine._on_any_ack, Qt.QueuedConnection)
    old.resetReportReceived.connect(machine._on_reset_report, Qt.QueuedConnection)
    old.readerStopped.connect(machine._on_serial_reader_stopped, Qt.QueuedConnection)
    callback = Mock()
    machine._start_ack_wait(mfr.CLEAR_ACK, 7, 10000, on_ok=callback, on_timeout=lambda: None)
    status = {"old_connection": True}
    ack = old._parse_ack(bytes([mfr.CLEAR_ACK, 7, mfr.ACK_TLV_SEQ32, 4]) + struct.pack("<I", 7))
    report = old._parse_reset_report(_reset_report_payload(0))
    for frame, kind, signal in [(status, "status", old.status_received),
                                (ack, "ack", old.ackReceived), (report, "reset_report", old.resetReportReceived)]:
        old.stamp_frame(frame, kind)
        signal.emit(frame)
    old.readerStopped.emit(old._reader_stop_info("read_error"))
    # Same serial object deliberately reused: generation, not port identity,
    # must keep old callbacks out of the new session.
    fresh = machine.reader = mfr.SerialReader(machine.ser)
    fresh.status_received.connect(machine.update_status, Qt.QueuedConnection)
    resets, lost, statuses = [], [], []
    machine.reset_report_received.connect(resets.append)
    machine.serial_connection_lost.connect(lost.append)
    machine.status_updated.connect(statuses.append)
    machine._transport_ready = True
    machine._tx_paused = False
    current = {"new_connection": True}
    fresh.stamp_frame(current, "status")
    fresh.status_received.emit(current)
    qapp.processEvents()
    assert not resets and not lost
    assert statuses == [current]
    callback.assert_not_called()
    assert fresh.receive_snapshot()["processed_count"] == 1
    assert old.receive_snapshot()["processed_count"] == 0
    machine._cancel_pending_acks()


def test_reentrant_callback_cannot_advance_past_unfinished_frame(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    reader = machine.reader = mfr.SerialReader(machine.ser)
    first, second = {}, {}
    reader.stamp_frame(first, "status")
    reader.stamp_frame(second, "status")
    reader.complete_frame(2)
    assert reader.receive_snapshot()["processed_count"] == 0
    reader.complete_frame(1)
    assert reader.receive_snapshot()["processed_count"] == 2


def test_failed_callback_keeps_dispatch_blocked_after_later_status(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    reader = machine.reader = mfr.SerialReader(machine.ser)
    machine._transport_ready = True
    machine._tx_paused = False
    machine.command_queue.add_command("LED_ON", 0, 0, 0)
    machine.send_command_to_board = Mock(return_value=False)
    def failed():
        raise ValueError("injected handler failure")
    machine._start_ack_wait(mfr.CLEAR_ACK, 7, 10000, on_ok=failed, on_timeout=lambda: None)
    ack = {"ack_cmd": mfr.CLEAR_ACK, "seq32": 7, "seq8": 7}
    reader.stamp_frame(ack, "ack")
    with pytest.raises(ValueError, match="injected handler"):
        machine._on_any_ack(ack)
    status = {}
    reader.stamp_frame(status, "status")
    machine.update_status(status)
    machine.pump_send_queue()
    assert reader.receive_snapshot()["delivery_failed"]
    assert reader.receive_snapshot()["processed_count"] == 0
    assert not reader._completed_frames
    machine.send_command_to_board.assert_not_called()


class LiveSerial(FakeSerialMain):
    """Keep an idle port open until the owner stops it, as pyserial does."""
    def read(self, n):
        with self._lock:
            data = bytes(self._buf[:n])
            del self._buf[:n]
        if not data:
            time.sleep(0.001)
        return data


def test_reader_frames_prevent_false_loss_during_blocked_gui(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    machine.ser = LiveSerial(_frame(bytes([mfr.CMD_STATUS])))
    reader = machine.reader = mfr.SerialReader(machine.ser)
    reader.status_received.connect(machine.update_status, Qt.QueuedConnection)
    received = threading.Event()
    reader.status_received.connect(lambda _: received.set(), Qt.DirectConnection)
    lost = []
    machine.serial_connection_lost.connect(lost.append)
    machine._transport_ready = True
    machine._tx_paused = False
    machine._last_mcu_rx_monotonic_ns = time.monotonic_ns() - 3_000_000_000
    machine.command_queue.add_command("LED_ON", 0, 0, 0)
    machine.send_command_to_board = Mock(return_value=False)
    try:
        reader.start()
        # Do not process Qt events: reception must be visible before delivery.
        assert received.wait(5)
        machine._check_mcu_response_health()
        assert not lost and machine._transport_ready
        assert not machine.status_history
        machine.pump_send_queue()
        machine.send_command_to_board.assert_not_called()
        state = machine._black_box_transport_state()
        assert state["response_observation"]["receive_source"] == "serial_reader"
        assert state["response_observation"]["main_thread_frame_age_ms"] >= 2500
        assert state["last_mcu_rx_age_ms"] < 2500
        assert any(e["kind"] == "mcu_frame_delivery_delayed"
                   for e in machine.black_box_recorder.recent_events())
        qapp.processEvents()
        machine.pump_send_queue()
        assert machine.send_command_to_board.called
        assert machine.status_history
    finally:
        reader.request_stop()
        assert reader.wait(5000)


@pytest.mark.parametrize("kind", ["status", "ack", "reset_report"])
def test_valid_frames_record_reception_before_delivery(qapp, fake_serial_main, kind):
    payload = {"status": bytes([mfr.CMD_STATUS]), "ack": bytes([mfr.HELLO_ACK, 1]),
               "reset_report": _reset_report_payload(0)}[kind]
    fake_serial_main.append_inbound(_frame(payload))
    reader = mfr.SerialReader(fake_serial_main)
    seen = []
    signal = {"status": reader.status_received, "ack": reader.ackReceived,
              "reset_report": reader.resetReportReceived}[kind]
    signal.connect(lambda data: seen.append((data, reader.receive_snapshot())))
    reader.run()
    assert len(seen) == 1
    data, snapshot = seen[0]
    assert snapshot["kind"] == kind and snapshot["frame_count"] == 1
    assert data["__host_rx_monotonic_ns"] == snapshot["monotonic_ns"]


def test_stale_queued_status_cannot_mask_real_silence(qapp, test_profile, tmp_path, monkeypatch):
    machine = _make_machine(qapp, test_profile, tmp_path)
    machine.ser = FakeSerialMain(_frame(bytes([mfr.CMD_STATUS])))
    reader = machine.reader = mfr.SerialReader(machine.ser)
    statuses = []
    reader.status_received.connect(statuses.append)
    now = time.monotonic_ns()
    with monkeypatch.context() as patch:
        patch.setattr(mfr.time, "monotonic_ns", lambda: now - 3_000_000_000)
        reader.run()
    machine.ser.is_open = True
    machine._transport_ready = True
    machine._tx_paused = False
    machine.send_command_to_board = Mock(return_value=False)
    machine.command_queue.add_command("LED_ON", 0, 0, 0)
    machine.update_status(statuses[0])  # Delivered now, received three seconds ago.
    machine.pump_send_queue()
    machine.send_command_to_board.assert_not_called()
    lost = []
    machine.serial_connection_lost.connect(lost.append)
    machine._check_mcu_response_health(now_ns=now)
    assert len(lost) == 1 and lost[0]["reason"] == "mcu_unresponsive"
    assert machine._tx_paused and not machine._transport_ready
    assert not machine.command_queue.queue
    assert machine.ser.is_open and not machine.ser.writes
    observation = _read_single_snapshot(tmp_path)["trigger"]
    assert observation["last_frame_age_ms"] == 3000
    assert observation["main_thread_frame_age_ms"] < 2500


@pytest.mark.parametrize("inbound", [b"", b"garbage", _frame(bytes([mfr.CMD_STATUS]))[:-1] + b"\xff"])
def test_missing_or_corrupt_frames_do_not_extend_connection_grace(qapp, test_profile, tmp_path, inbound):
    machine = _make_machine(qapp, test_profile, tmp_path)
    machine.ser = FakeSerialMain(inbound)
    machine.reader = mfr.SerialReader(machine.ser)
    machine.reader.run()
    assert machine.reader.receive_snapshot()["frame_count"] == 0
    machine.ser.is_open = True
    machine._transport_ready = True
    now = time.monotonic_ns()
    machine._transport_ready_monotonic_ns = now - 3_000_000_000
    machine._mark_mcu_rx("status")  # Late callback cannot refresh an actual reader.
    machine._check_mcu_response_health(now_ns=now)
    assert machine._mcu_unresponsive_reported


def test_new_reader_does_not_inherit_previous_connection_health(qapp, test_profile, tmp_path):
    machine = _make_machine(qapp, test_profile, tmp_path)
    old_reader = machine.reader = mfr.SerialReader(machine.ser)
    old_reader._record_valid_frame("status")
    machine.reader = mfr.SerialReader(machine.ser)
    now = time.monotonic_ns()
    machine._transport_ready = True
    machine._transport_ready_monotonic_ns = now - 3_000_000_000
    machine._check_mcu_response_health(now_ns=now)
    assert machine._mcu_unresponsive_reported


def test_snapshot_carries_reader_and_separately_timestamped_ui_stall(qapp, test_profile, tmp_path, monkeypatch):
    machine = _make_machine(qapp, test_profile, tmp_path)
    now = time.monotonic_ns()
    stall = {"monotonic_ns": now - 2_000_000_000, "thread_dump": "MainThread: saving", "truncated": False}
    monkeypatch.setattr(qapp, "_labcraft_ui_heartbeat", {"last": (now - 1_000_000_000) / 1e9, "last_stall": stall}, raising=False)
    machine.reader = mfr.SerialReader(machine.ser)
    snapshot = machine._build_black_box_snapshot("mcu_unresponsive")
    assert snapshot["last_ui_stall"] == stall
    assert snapshot["transport"]["response_observation"]["qt_heartbeat_age_ms"] >= 1000
    assert snapshot["transport"]["response_observation"]["reader_receive"]["frame_count"] == 0
