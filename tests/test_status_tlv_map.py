import Machine_FreeRTOS as mfr


def test_status_parser_maps_dispense_frequency_tag():
    payload = bytes([mfr.TAG_DISP_FREQ, 2, 0x34, 0x12])

    data = mfr.parse_tlv_payload(payload)

    assert data["Disp_freq"] == 0x1234
