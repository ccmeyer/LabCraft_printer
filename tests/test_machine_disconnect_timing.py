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


def test_stop_log_thread_does_not_wait_after_reader_stop(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)

    class _SignalTracker:
        def disconnect(self, _slot):
            return None

    class _Reader:
        def __init__(self):
            self.stop_calls = 0
            self.lineReceived = _SignalTracker()
            self.statsUpdated = _SignalTracker()
            self.messageReceived = _SignalTracker()
            self.flashStateChanged = _SignalTracker()

        def stop(self):
            self.stop_calls += 1
            return True

        def wait(self, _timeout):
            raise AssertionError("Machine.stop_log_thread should not call reader.wait directly")

    reader = _Reader()
    machine.log_reader = reader

    machine.stop_log_thread()

    assert reader.stop_calls == 1
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

        def stop(self):
            assert self.lineReceived.disconnected == [machine.on_log_line_received]
            assert self.statsUpdated.disconnected == [machine.on_stats_updated]
            assert self.messageReceived.disconnected == [machine.on_log_message_received]
            assert self.flashStateChanged.disconnected == [machine.on_flash_state_changed]
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
            self.stop_calls = 0
            self.lineReceived = _SignalTracker()
            self.statsUpdated = _SignalTracker()
            self.messageReceived = _SignalTracker()
            self.flashStateChanged = _SignalTracker()

        def stop(self):
            self.stop_calls += 1
            return False

    reader = _Reader()
    machine.log_reader = reader

    machine.stop_log_thread()
    out = capsys.readouterr().out

    assert reader.stop_calls == 1
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
