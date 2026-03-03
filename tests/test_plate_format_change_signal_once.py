from Model import WellPlate


def test_set_plate_format_emits_change_signal_once(tmp_path):
    plate_data = [
        {"name": "p1", "rows": 2, "columns": 2, "spacing": 10, "default": True, "calibrations": {}},
        {"name": "p2", "rows": 3, "columns": 3, "spacing": 10, "default": False, "calibrations": {}},
    ]
    plates_tmp = tmp_path / "Plates.json"
    plates_tmp.write_text("[]", encoding="utf-8")
    wp = WellPlate(plate_data, str(plates_tmp))

    calls = []
    wp.plate_format_changed_signal.connect(lambda: calls.append(1))

    wp.set_plate_format("p2")

    assert len(calls) == 1
