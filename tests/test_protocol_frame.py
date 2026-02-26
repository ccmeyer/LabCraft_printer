import json
import struct
from pathlib import Path

import pytest

import Machine_FreeRTOS as mfr


VECTORS = json.loads((Path(__file__).parent / "fixtures" / "protocol_vectors.json").read_text())


@pytest.mark.parametrize("case", VECTORS["crc_cases"])
def test_crc16_x25_vectors(case):
    payload = bytes.fromhex(case["payload_hex"])
    expected_crc = int.from_bytes(bytes.fromhex(case["crc_hex_le"]), byteorder="little")
    assert mfr.crc16_x25(payload) == expected_crc


@pytest.mark.parametrize("case", VECTORS["frame_cases"])
def test_build_frame_vectors(case):
    frame = mfr.build_frame(case["cmd"], case["seq32"])
    assert frame.hex() == case["frame_hex"]


def test_command_builds_expected_tlvs_and_crc():
    cmd = mfr.Command(7, "DISPENSE", 5, 0, 0)
    frame = cmd.frame

    assert frame[0] == mfr.START_BYTE
    payload_len = frame[1]
    payload = frame[2 : 2 + payload_len]
    crc_tail = frame[-2:]

    assert payload[0] == mfr.CMD_MAP["DISPENSE"]
    assert payload[1] == 7  # seq8

    idx = 2
    parsed = {}
    while idx + 2 <= len(payload):
        tag = payload[idx]
        ln = payload[idx + 1]
        idx += 2
        parsed[tag] = payload[idx : idx + ln]
        idx += ln

    assert struct.unpack("<I", parsed[mfr.Command.TAG_SEQ32])[0] == 7
    assert struct.unpack("<I", parsed[mfr.Command.TAG_P1])[0] == 5
    assert struct.unpack("<I", parsed[mfr.Command.TAG_P2])[0] == 0
    assert struct.unpack("<I", parsed[mfr.Command.TAG_P3])[0] == 0

    expected_crc = mfr.crc16_x25(payload)
    assert int.from_bytes(crc_tail, byteorder="little") == expected_crc
