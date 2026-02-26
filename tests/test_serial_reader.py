import struct

import Machine_FreeRTOS as mfr


def _frame(payload: bytes) -> bytes:
    crc = mfr.crc16_x25(payload)
    return bytes([mfr.START_BYTE, len(payload)]) + payload + struct.pack("<H", crc)


class FakeSerial:
    def __init__(self, data: bytes):
        self._buf = bytearray(data)
        self.is_open = True

    def read(self, n: int) -> bytes:
        if not self._buf:
            self.is_open = False
            return b""
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def cancel_read(self):
        self.is_open = False


def test_serial_reader_emits_status_and_ack(qapp):
    status_payload = bytes(
        [
            mfr.CMD_STATUS,
            mfr.TAG_CURR_CMD,
            4,
            3,
            0,
            0,
            0,
            mfr.TAG_LAST_CMD,
            4,
            2,
            0,
            0,
            0,
        ]
    )
    ack_payload = bytes([mfr.HELLO_ACK, 0x01, mfr.Command.TAG_SEQ32, 4, 1, 0, 0, 0])
    serial_stream = _frame(status_payload) + _frame(ack_payload)

    fake_ser = FakeSerial(serial_stream)
    reader = mfr.SerialReader(fake_ser)
    statuses = []
    acks = []
    reader.status_received.connect(statuses.append)
    reader.ackReceived.connect(acks.append)

    reader.run()

    assert len(statuses) == 1
    assert statuses[0]["Current_command"] == 3
    assert statuses[0]["Last_completed"] == 2
    assert len(acks) == 1
    assert acks[0]["ack_cmd"] == mfr.HELLO_ACK
    assert acks[0]["seq32"] == 1


def test_serial_reader_rejects_bad_crc(qapp):
    payload = bytes([mfr.HELLO_ACK, 0x01, mfr.Command.TAG_SEQ32, 4, 1, 0, 0, 0])
    good = _frame(payload)
    bad = good[:-1] + bytes([good[-1] ^ 0xFF])
    fake_ser = FakeSerial(bad)

    reader = mfr.SerialReader(fake_ser)
    statuses = []
    acks = []
    reader.status_received.connect(statuses.append)
    reader.ackReceived.connect(acks.append)

    reader.run()

    assert statuses == []
    assert acks == []
