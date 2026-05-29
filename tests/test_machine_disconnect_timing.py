from types import SimpleNamespace

import Machine_FreeRTOS as mfr
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
        self.statsUpdated = _SignalTracker()
        self.messageReceived = _SignalTracker()
        self.flashStateChanged = _SignalTracker()


def test_on_goodbye_done_does_not_block_with_sleep(qapp, test_profile, monkeypatch):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    called = {"disconnect": 0, "reset": 0}

    def _no_sleep(_seconds):
        raise AssertionError("time.sleep should not be called in _on_goodbye_done")

    monkeypatch.setattr("Machine_FreeRTOS.time.sleep", _no_sleep)

    machine.ser = SimpleNamespace(
        reset_input_buffer=lambda: called.__setitem__("reset", called["reset"] + 1)
    )
    machine.disconnect_handler = lambda: called.__setitem__("disconnect", called["disconnect"] + 1)

    machine._on_goodbye_done()

    assert called["reset"] == 1
    assert called["disconnect"] == 1


def test_on_goodbye_done_still_disconnects_when_buffer_reset_fails(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    called = {"disconnect": 0}

    def _boom():
        raise RuntimeError("buffer reset failed")

    machine.ser = SimpleNamespace(reset_input_buffer=_boom)
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
            self.statsUpdated = _SignalTracker()
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
            self.statsUpdated = _SignalTracker()
            self.messageReceived = _SignalTracker()
            self.flashStateChanged = _SignalTracker()

        def request_stop(self):
            assert self.lineReceived.disconnected == [machine.on_log_line_received]
            assert self.statsUpdated.disconnected == [machine.on_stats_updated]
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
            self.statsUpdated = _SignalTracker()
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
    machine = Machine(SimpleNamespace(), profile=profile)

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
        def __init__(self, baud, serial_factory=None):
            self.baud = baud
            self.serial_factory = serial_factory
            self.lineReceived = _SignalTracker()
            self.statsUpdated = _SignalTracker()
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
            self.statsUpdated = _SignalTracker()
            self.messageReceived = _SignalTracker()
            self.flashStateChanged = _SignalTracker()
            self.wait_calls = 0

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


def test_disconnect_board_still_sends_goodbye(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    ser = _SerialForRelease()
    machine.ser = ser
    machine._start_ack_wait = lambda *args, **kwargs: None

    machine.disconnect_board()

    assert ser.writes
    assert ser.writes[0][2] == mfr.GOODBYE
