import logging

import Machine_FreeRTOS as mfr


def test_parse_tlv_payload_logs_unknown_and_malformed_entries(caplog):
    # 0x99 unknown tag, then malformed declared length (0x10 length 4 but only 2 bytes remain)
    payload = bytes([0x99, 0x01, 0xAA, 0x10, 0x04, 0x01, 0x02])

    with caplog.at_level(logging.WARNING):
        data = mfr.parse_tlv_payload(payload)

    assert data == {}
    log_text = "\n".join(r.message for r in caplog.records)
    assert "Unknown TLV tag" in log_text
    assert "Malformed TLV payload" in log_text


def test_parse_tlv_payload_logs_length_mismatch(caplog):
    # TAG_CURR_CMD expects 4 bytes but we provide length 2
    payload = bytes([mfr.TAG_CURR_CMD, 0x02, 0x34, 0x12])

    with caplog.at_level(logging.WARNING):
        data = mfr.parse_tlv_payload(payload)

    assert data == {}
    log_text = "\n".join(r.message for r in caplog.records)
    assert "TLV length mismatch" in log_text
