import Machine_FreeRTOS as mfr
from tests.fakes import FakeSerialFactory


def test_parse_flash_safety_log_event_recognizes_expected_lines():
    assert mfr.parse_flash_safety_log_event("FLASH_ARMED") == {"kind": "armed"}
    assert mfr.parse_flash_safety_log_event("FLASH_FAULT reason=line_high_on_arm") == {
        "kind": "fault",
        "reason": "line_high_on_arm",
    }
    assert mfr.parse_flash_safety_log_event("FLASH_DISARMED reason=shutdown") == {
        "kind": "disarmed",
        "reason": "shutdown",
    }
    assert mfr.parse_flash_safety_log_event("not a flash line") is None


def test_apply_flash_safety_log_event_tracks_fault_until_explicit_stop():
    state = mfr.default_flash_safety_state()

    state = mfr.apply_flash_safety_log_event(state, {"kind": "armed"})
    assert state == {
        "flash_session_armed": True,
        "flash_fault_latched": False,
        "flash_fault_reason": "",
    }

    state = mfr.apply_flash_safety_log_event(
        state,
        {"kind": "fault", "reason": "retrigger_while_high"},
    )
    assert state == {
        "flash_session_armed": False,
        "flash_fault_latched": True,
        "flash_fault_reason": "retrigger_while_high",
    }

    state = mfr.apply_flash_safety_log_event(state, {"kind": "disarmed", "reason": "fault"})
    assert state == {
        "flash_session_armed": False,
        "flash_fault_latched": True,
        "flash_fault_reason": "retrigger_while_high",
    }

    state = mfr.apply_flash_safety_log_event(state, {"kind": "disarmed", "reason": "stop"})
    assert state == {
        "flash_session_armed": False,
        "flash_fault_latched": False,
        "flash_fault_reason": "",
    }


def test_log_reader_emits_flash_state_updates_from_log_lines(qapp):
    class _LineSerial:
        def __init__(self, lines):
            self._lines = [f"{line}\n".encode("ascii") for line in lines]
            self.is_open = True

        def read_until(self, expected=b"\n", size=1024):
            if not self._lines:
                self.is_open = False
                return b""
            return self._lines.pop(0)

        def cancel_read(self):
            self.is_open = False

        def close(self):
            self.is_open = False

    reader = mfr.LogReader(serial_factory=lambda *_args, **_kwargs: _LineSerial([
        "FLASH_ARMED",
        "FLASH_FAULT reason=line_stuck_high",
        "FLASH_DISARMED reason=fault",
        "FLASH_DISARMED reason=stop",
    ]))
    states = []
    reader.flashStateChanged.connect(states.append)

    reader.run()

    assert states == [
        {
            "flash_session_armed": True,
            "flash_fault_latched": False,
            "flash_fault_reason": "",
        },
        {
            "flash_session_armed": False,
            "flash_fault_latched": True,
            "flash_fault_reason": "line_stuck_high",
        },
        {
            "flash_session_armed": False,
            "flash_fault_latched": True,
            "flash_fault_reason": "line_stuck_high",
        },
        {
            "flash_session_armed": False,
            "flash_fault_latched": False,
            "flash_fault_reason": "",
        },
    ]


def test_log_reader_stop_closes_port_and_waits_once_when_cancel_read_is_ineffective(qapp):
    class _Serial:
        def __init__(self):
            self.is_open = True
            self.cancel_calls = 0
            self.close_calls = 0

        def cancel_read(self):
            self.cancel_calls += 1

        def close(self):
            self.close_calls += 1
            self.is_open = False

    class _TestLogReader(mfr.LogReader):
        def __init__(self, ser):
            self.wait_calls = []
            self.interrupt_calls = 0
            super().__init__(serial_factory=lambda *_args, **_kwargs: ser)

        def requestInterruption(self):
            self.interrupt_calls += 1

        def wait(self, timeout):
            self.wait_calls.append(timeout)
            return True

    ser = _Serial()
    reader = _TestLogReader(ser)

    stopped = reader.stop()

    assert stopped is True
    assert reader.interrupt_calls == 1
    assert reader.wait_calls == [mfr.LOG_READER_STOP_WAIT_MS]
    assert ser.cancel_calls == 1
    assert ser.close_calls == 1
    assert ser.is_open is False


def test_log_reader_stop_tolerates_cancel_and_close_errors(qapp):
    class _Serial:
        def __init__(self):
            self.is_open = True
            self.cancel_calls = 0
            self.close_calls = 0

        def cancel_read(self):
            self.cancel_calls += 1
            raise RuntimeError("cancel_read failed")

        def close(self):
            self.close_calls += 1
            raise RuntimeError("close failed")

    class _TestLogReader(mfr.LogReader):
        def __init__(self, ser):
            self.wait_calls = []
            self.interrupt_calls = 0
            super().__init__(serial_factory=lambda *_args, **_kwargs: ser)

        def requestInterruption(self):
            self.interrupt_calls += 1

        def wait(self, timeout):
            self.wait_calls.append(timeout)
            return False

    ser = _Serial()
    reader = _TestLogReader(ser)

    stopped = reader.stop()

    assert stopped is False
    assert reader.interrupt_calls == 1
    assert reader.wait_calls == [mfr.LOG_READER_STOP_WAIT_MS]
    assert ser.cancel_calls == 1
    assert ser.close_calls == 1
