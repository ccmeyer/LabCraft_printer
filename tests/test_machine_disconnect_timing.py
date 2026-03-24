from types import SimpleNamespace

import Machine_FreeRTOS as mfr
from Machine_FreeRTOS import Machine


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
        def __init__(self, baud, parent=None, log_port="/dev/ttyUSB0", history_len=360, serial_factory=None):
            self.baud = baud
            self.parent = parent
            self.log_port = log_port
            self.history_len = history_len
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
    monkeypatch.setattr(mfr, "resolve_log_port", lambda control_port, configured_log_port=None: "COM9")
    machine.log_reader = _OldReader()
    machine.port = "COM4"

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
