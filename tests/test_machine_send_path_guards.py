from types import SimpleNamespace

from Machine_FreeRTOS import Machine

from tests.fakes.fake_serial import FakeSerialMain


class _Cmd:
    def __init__(self):
        self.frame = b"\xAA\x00\xFF\xFF"

    def get_command(self):
        return "<FAKE>"


def test_write_frame_with_closed_serial_emits_error_without_crash(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    errors = []
    machine.error_occurred.connect(errors.append)

    ok = machine.send_command_to_board(_Cmd())
    assert ok is False
    assert errors

    machine.ser = FakeSerialMain()
    machine.ser.close()
    ok2 = machine.send_command_to_board(_Cmd())
    assert ok2 is False
    assert len(errors) >= 2
