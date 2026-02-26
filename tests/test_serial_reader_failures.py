import struct

import Machine_FreeRTOS as mfr

from tests.fakes.fake_serial import FakeSerialMain


def _frame(payload: bytes) -> bytes:
    crc = mfr.crc16_x25(payload)
    return bytes([mfr.START_BYTE, len(payload)]) + payload + struct.pack("<H", crc)


def test_serial_reader_ignores_malformed_ack_and_continues(qapp):
    malformed_ack = b""
    good_status = bytes(
        [
            mfr.CMD_STATUS,
            mfr.TAG_CURR_CMD,
            4,
            4,
            0,
            0,
            0,
            mfr.TAG_LAST_CMD,
            4,
            3,
            0,
            0,
            0,
        ]
    )
    stream = _frame(malformed_ack) + _frame(good_status)

    reader = mfr.SerialReader(FakeSerialMain(stream))
    statuses = []
    acks = []
    reader.status_received.connect(statuses.append)
    reader.ackReceived.connect(acks.append)

    reader.run()

    assert len(statuses) == 1
    assert statuses[0]["Current_command"] == 4
    assert statuses[0]["Last_completed"] == 3
    assert acks == []
