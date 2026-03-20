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
