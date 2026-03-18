import Machine_FreeRTOS as mfr


def test_status_parser_maps_dispense_frequency_tag():
    payload = bytes([mfr.TAG_DISP_FREQ, 2, 0x34, 0x12])

    data = mfr.parse_tlv_payload(payload)

    assert data["Disp_freq"] == 0x1234


def test_status_parser_maps_regulator_activity_tags():
    payload = bytes(
        [
            mfr.TAG_ACTIVE_P, 2, 0x01, 0x00,
            mfr.TAG_ACTIVE_R, 2, 0x00, 0x00,
        ]
    )

    data = mfr.parse_tlv_payload(payload)

    assert data["print_active"] == 1
    assert data["refuel_active"] == 0
