from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject

import Machine_FreeRTOS as mfr
from Controller import Controller
from Machine_FreeRTOS import Machine


class _SerialForRelease:
    def __init__(self):
        self.is_open = True
        self.writes = []
        self.close_calls = 0
        self.flush_calls = 0

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def flush(self):
        self.flush_calls += 1

    def close(self):
        self.close_calls += 1
        self.is_open = False


class _TimerForRelease:
    def __init__(self):
        self.stop_calls = 0
        self.delete_calls = 0

    def stop(self):
        self.stop_calls += 1

    def deleteLater(self):
        self.delete_calls += 1


class _ReaderForRelease:
    def __init__(self, *, stop_ok=True):
        self.stop_ok = stop_ok
        self.request_stop_calls = 0
        self.wait_for_stop_calls = []

    def request_stop(self):
        self.request_stop_calls += 1

    def wait_for_stop(self, timeout):
        self.wait_for_stop_calls.append(timeout)
        return self.stop_ok


class _SignalTracker:
    def __init__(self):
        self.disconnected = []

    def disconnect(self, slot):
        self.disconnected.append(slot)


class _LogReaderForRelease(_ReaderForRelease):
    def __init__(self, *, stop_ok=True):
        super().__init__(stop_ok=stop_ok)
        self.lineReceived = _SignalTracker()
        self.messageReceived = _SignalTracker()
        self.flashStateChanged = _SignalTracker()


def test_on_goodbye_done_does_not_block_with_sleep(qapp, test_profile, monkeypatch):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    called = {"disconnect": 0}

    def _no_sleep(_seconds):
        raise AssertionError("time.sleep should not be called in _on_goodbye_done")

    monkeypatch.setattr("Machine_FreeRTOS.time.sleep", _no_sleep)

    machine.ser = SimpleNamespace(
        reset_input_buffer=lambda: (_ for _ in ()).throw(
            AssertionError("goodbye must not flush the live reader")
        )
    )
    machine.disconnect_handler = lambda: called.__setitem__("disconnect", called["disconnect"] + 1)

    machine._on_goodbye_done()

    assert called["disconnect"] == 1


def test_on_goodbye_done_disconnects_without_input_buffer_api(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    called = {"disconnect": 0}

    machine.ser = SimpleNamespace(is_open=True)
    machine.disconnect_handler = lambda: called.__setitem__("disconnect", called["disconnect"] + 1)

    machine._on_goodbye_done()

    assert called["disconnect"] == 1


def test_stop_log_thread_uses_reader_wait_for_stop_only(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)

    class _SignalTracker:
        def disconnect(self, _slot):
            return None

    class _Reader:
        def __init__(self):
            self.request_stop_calls = 0
            self.wait_for_stop_calls = []
            self.lineReceived = _SignalTracker()
            self.messageReceived = _SignalTracker()
            self.flashStateChanged = _SignalTracker()

        def request_stop(self):
            self.request_stop_calls += 1

        def wait_for_stop(self, timeout):
            self.wait_for_stop_calls.append(timeout)
            return True

        def wait(self, _timeout):
            raise AssertionError("Machine.stop_log_thread should not call reader.wait directly")

    reader = _Reader()
    machine.log_reader = reader

    machine.stop_log_thread()

    assert reader.request_stop_calls == 1
    assert reader.wait_for_stop_calls == [mfr.READER_STOP_FALLBACK_WAIT_MS]
    assert machine.log_reader is None


def test_stop_log_thread_disconnects_signals_before_stop(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)

    class _SignalTracker:
        def __init__(self):
            self.disconnected = []

        def disconnect(self, slot):
            self.disconnected.append(slot)

    class _Reader:
        def __init__(self):
            self.lineReceived = _SignalTracker()
            self.messageReceived = _SignalTracker()
            self.flashStateChanged = _SignalTracker()

        def request_stop(self):
            assert self.lineReceived.disconnected == [machine.on_log_line_received]
            assert self.messageReceived.disconnected == [machine.on_log_message_received]
            assert self.flashStateChanged.disconnected == [machine.on_flash_state_changed]

        def wait_for_stop(self, _timeout):
            return True

    reader = _Reader()
    machine.log_reader = reader

    machine.stop_log_thread()

    assert machine.log_reader is None


def test_stop_log_thread_keeps_reader_reference_when_reader_stop_fails(qapp, test_profile, capsys):
    machine = Machine(SimpleNamespace(), profile=test_profile)

    class _SignalTracker:
        def disconnect(self, _slot):
            return None

    class _Reader:
        def __init__(self):
            self.request_stop_calls = 0
            self.wait_for_stop_calls = []
            self.lineReceived = _SignalTracker()
            self.messageReceived = _SignalTracker()
            self.flashStateChanged = _SignalTracker()

        def request_stop(self):
            self.request_stop_calls += 1

        def wait_for_stop(self, timeout):
            self.wait_for_stop_calls.append(timeout)
            return False

    reader = _Reader()
    machine.log_reader = reader

    machine.stop_log_thread()
    out = capsys.readouterr().out

    assert reader.request_stop_calls == 1
    assert reader.wait_for_stop_calls == [mfr.READER_STOP_FALLBACK_WAIT_MS]
    assert machine.log_reader is reader
    assert "did not stop cleanly" in out


def test_begin_log_thread_replaces_stopped_reader_reference(qapp, monkeypatch):
    profile = SimpleNamespace(
        name="current",
        has_refuel_camera=False,
        has_droplet_camera=False,
        has_log_channel=True,
    )
    identity = SimpleNamespace(
        requested_path="COM_LOG",
        system_device="COM_LOG",
    )
    machine = Machine(
        SimpleNamespace(),
        profile=profile,
        machine_log_port="COM_LOG",
        serial_identity_resolver=lambda *_args, **_kwargs: identity,
    )

    class _SignalTracker:
        def __init__(self):
            self.connected = []

        def connect(self, slot):
            self.connected.append(slot)

    old_reader_calls = {"stop": 0}

    class _OldReader:
        def isRunning(self):
            return False

        def stop(self):
            old_reader_calls["stop"] += 1
            return True

    created = []

    class _NewReader:
        def __init__(self, baud, *, log_port, serial_factory=None):
            self.baud = baud
            self.log_port = log_port
            self.serial_factory = serial_factory
            self.lineReceived = _SignalTracker()
            self.messageReceived = _SignalTracker()
            self.flashStateChanged = _SignalTracker()
            self.start_calls = 0
            created.append(self)

        def start(self):
            self.start_calls += 1

    monkeypatch.setattr(mfr, "LogReader", _NewReader)
    machine.log_reader = _OldReader()

    machine.begin_log_thread()

    assert old_reader_calls["stop"] == 1
    assert len(created) == 1
    assert machine.log_reader is created[0]
    assert created[0].start_calls == 1


def test_begin_reader_thread_replaces_stopped_reader_reference(qapp, test_profile, monkeypatch):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    machine.ser = object()

    class _SignalTracker:
        def __init__(self):
            self.connected = []

        def connect(self, slot):
            self.connected.append(slot)

    old_reader_calls = {"stop": 0}

    class _OldReader:
        def isRunning(self):
            return False

        def stop(self):
            old_reader_calls["stop"] += 1
            return True

    created = []

    class _NewReader:
        def __init__(self, ser):
            self.ser = ser
            self.status_received = _SignalTracker()
            self.ackReceived = _SignalTracker()
            self.resetReportReceived = _SignalTracker()
            self.start_calls = 0
            created.append(self)

        def start(self):
            self.start_calls += 1

    monkeypatch.setattr(mfr, "SerialReader", _NewReader)
    machine.reader = _OldReader()

    machine.begin_reader_thread()

    assert old_reader_calls["stop"] == 1
    assert len(created) == 1
    assert machine.reader is created[0]
    assert created[0].start_calls == 1


def test_reset_board_requests_both_reader_stops_before_waiting(qapp, test_profile, capsys):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    events = []

    class _SignalTracker:
        def disconnect(self, _slot):
            events.append("log:disconnect")

    class _SerialReader:
        def request_stop(self):
            events.append("serial:request")

        def wait_for_stop(self, timeout):
            events.append(f"serial:wait:{timeout}")
            return True

    class _LogReader:
        def __init__(self):
            self.lineReceived = _SignalTracker()
            self.messageReceived = _SignalTracker()
            self.flashStateChanged = _SignalTracker()
            self.wait_calls = 0
            self.message_history = deque(
                [{"ts": 1.0, "text": "pre-reset XY fault", "level": None}],
                maxlen=2000,
            )

        def get_recent_messages(self):
            return list(self.message_history)

        def request_stop(self):
            events.append("log:request")

        def wait_for_stop(self, timeout):
            self.wait_calls += 1
            events.append(f"log:wait:{timeout}")
            return self.wait_calls > 1

    machine.reader = _SerialReader()
    machine.log_reader = _LogReader()

    machine.reset_board()
    out = capsys.readouterr().out

    first_wait_index = next(index for index, value in enumerate(events) if ":wait:" in value)
    assert events.index("serial:request") < first_wait_index
    assert events.index("log:request") < first_wait_index
    assert f"serial:wait:{mfr.SERIAL_READER_STOP_WAIT_MS}" in events
    assert f"log:wait:{mfr.LOG_READER_STOP_WAIT_MS}" in events
    assert f"log:wait:{mfr.READER_STOP_FALLBACK_WAIT_MS}" in events
    assert "Requesting serial and log reader shutdown..." in out
    assert "Log reader thread fast stop timed out" in out
    assert "Reader shutdown finished in" in out
    assert machine._pre_reset_mcu_log_history["capture_reason"] == "reset_board_teardown"
    assert machine._pre_reset_mcu_log_history["retained_count"] == 1
    assert machine._pre_reset_mcu_log_history["entries"][0]["text"] == "pre-reset XY fault"


def test_release_serial_for_external_owner_closes_without_goodbye_or_disconnect_signal(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    ser = _SerialForRelease()
    serial_reader = _ReaderForRelease()
    log_reader = _LogReaderForRelease()
    ack_timer = _TimerForRelease()
    disconnects = []
    machine.disconnect_complete_signal.connect(lambda: disconnects.append("disconnect"))
    machine.ser = ser
    machine.port = "COM7"
    machine.reader = serial_reader
    machine.log_reader = log_reader
    machine._transport_ready = True
    machine._tx_paused = False
    machine._pending_acks[(mfr.BYE_ACK, 1, -1)] = {"timer": ack_timer, "ok": None, "to": None}

    assert machine.release_serial_for_external_owner(reason="regulator_calibration") is True

    assert ser.writes == []
    assert ser.close_calls == 1
    assert ser.is_open is False
    assert machine.ser is None
    assert machine.reader is None
    assert machine.log_reader is None
    assert machine._pending_acks == {}
    assert ack_timer.stop_calls == 1
    assert ack_timer.delete_calls == 1
    assert serial_reader.request_stop_calls == 1
    assert log_reader.request_stop_calls == 1
    assert log_reader.lineReceived.disconnected == [machine.on_log_line_received]
    assert machine._transport_ready is False
    assert machine._tx_paused is True
    assert disconnects == []


def test_release_serial_for_external_owner_failure_keeps_serial_open(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    ser = _SerialForRelease()
    machine.ser = ser
    machine.reader = _ReaderForRelease(stop_ok=False)
    machine.log_reader = None
    machine._transport_ready = True
    machine._tx_paused = False

    assert machine.release_serial_for_external_owner(reason="regulator_calibration") is False

    assert ser.close_calls == 0
    assert ser.is_open is True
    assert machine.ser is ser
    assert machine._transport_ready is True
    assert machine._tx_paused is False
    assert machine._expected_serial_reader_stop_reason is None


def test_disconnect_board_still_sends_goodbye(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    ser = _SerialForRelease()
    machine.ser = ser
    machine._start_ack_wait = lambda *args, **kwargs: None

    machine.disconnect_board()

    assert ser.writes
    assert ser.writes[0][2] == mfr.GOODBYE


@pytest.mark.parametrize("cleanup_path", ["reset_mcu", "teardown_then_pending_reconnect"])
@pytest.mark.parametrize("shutdown_timeout", [False, True])
def test_controller_disconnect_after_timer_cleanup(
        qapp, test_profile, tmp_path, monkeypatch, cleanup_path, shutdown_timeout):
    from test_mcu_reader_liveness import (
        LiveSerial, _connect_queued_reader, _queue_reader_ack, _queue_reader_status,
    )

    # Retain real Controller reset/disconnect methods and its production teardown
    # signal wiring, with fake GPIO/serial and recorded Model notifications.
    gpio_reset = Mock()
    monkeypatch.setattr(mfr, "reset_board", gpio_reset)
    machine = Machine(SimpleNamespace(), profile=test_profile, black_box_log_dir=tmp_path)
    controller = Controller.__new__(Controller)
    QObject.__init__(controller)
    controller.machine = machine
    model_disconnect = Mock()
    controller.model = SimpleNamespace(machine_model=SimpleNamespace(disconnect_machine=model_disconnect))
    machine.disconnect_complete_signal.connect(controller.reset_board)
    serial = machine.ser = LiveSerial()
    machine.port = "COM9"
    machine._transport_ready = True
    machine._tx_paused = False
    machine.begin_execution_timer()

    def finish_shutdown(reader):
        seq = machine._goodbye_seq32
        for code in (mfr.BYE_ACK, mfr.BYE_DONE):
            if shutdown_timeout:
                machine._ack_timeout_by_key(machine._ack_key(code, seq, None))
            else:
                _queue_reader_ack(reader, code, seq)
                qapp.processEvents()

    if cleanup_path == "reset_mcu":
        controller.reset_mcu_board()
        gpio_reset.assert_called_once_with()
    else:
        reader = _connect_queued_reader(machine)
        controller.disconnect_machine()
        finish_shutdown(reader)
        model_disconnect.assert_called_once_with()
        assert not serial.is_open and machine.ser is None
        serial = LiveSerial()
        machine._serial_factory = lambda *args, **kwargs: serial
        machine.begin_reader_thread = lambda: _connect_queued_reader(machine)
        machine.connect_board("COM9")
        assert [frame[2] for frame in serial.writes] == [mfr.HELLO]
        assert any(key[0] == mfr.HELLO_ACK for key in machine._pending_acks)

    assert machine.execution_timer is None
    assert machine.ser is serial and serial.is_open
    reader = machine.reader or _connect_queued_reader(machine)
    for key in list(machine._pending_acks):
        if key[0] == mfr.HELLO_ACK:
            _queue_reader_ack(reader, mfr.HELLO_ACK, key[1], capabilities=mfr.REQUIRED_TRANSPORT_CAPS)
    machine.command_queue.add_command("ABSOLUTE_XY", 10, 20, 0)
    controller.disconnect_machine()
    assert machine._disconnect_in_progress and not machine._transport_ready
    assert machine.execution_timer is None
    _queue_reader_status(reader)
    qapp.processEvents()
    finish_shutdown(reader)
    expected = [mfr.GOODBYE] if cleanup_path == "reset_mcu" else [mfr.HELLO, mfr.GOODBYE]
    assert [frame[2] for frame in serial.writes] == expected
    assert not serial.is_open and machine.ser is None
    assert not machine._disconnect_in_progress and not machine._transport_ready
    assert not machine._pending_acks and not machine.command_queue.queue
    assert machine.execution_timer is None
    assert model_disconnect.called

    # Repeated cleanup with no timer/serial is harmless, and does not latch out
    # a subsequent connection. A completed HELLO must recreate the timer.
    machine.disconnect_handler()
    controller.disconnect_machine()
    fresh = LiveSerial()
    machine._serial_factory = lambda *args, **kwargs: fresh
    machine.begin_reader_thread = lambda: _connect_queued_reader(machine)
    machine.connect_board("COM9")
    assert machine.ser is fresh and machine.execution_timer is None
    key = next(key for key in machine._pending_acks if key[0] == mfr.HELLO_ACK)
    _queue_reader_ack(machine.reader, mfr.HELLO_ACK, key[1], capabilities=mfr.REQUIRED_TRANSPORT_CAPS)
    qapp.processEvents()
    assert machine.execution_timer is not None and machine.execution_timer.isActive()
    machine.command_queue.add_command("ABSOLUTE_XY", 30, 40, 0)
    _queue_reader_status(machine.reader)
    qapp.processEvents()
    assert [frame[2] for frame in fresh.writes] == [mfr.HELLO, mfr.CMD_MAP["ABSOLUTE_XY"]]
    machine.disconnect_handler()
    assert machine.execution_timer is None and machine.ser is None
