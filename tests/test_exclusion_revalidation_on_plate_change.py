from Model import WellPlate


def test_set_plate_format_prunes_invalid_exclusions(tmp_path):
    plate_data = [
        {"name": "large", "rows": 3, "columns": 3, "spacing": 10, "default": True, "calibrations": {}},
        {"name": "small", "rows": 1, "columns": 1, "spacing": 10, "default": False, "calibrations": {}},
    ]
    plates_tmp = tmp_path / "Plates.json"
    plates_tmp.write_text("[]", encoding="utf-8")

    wp = WellPlate(plate_data, str(plates_tmp))
    wp.excluded_wells = {"A1", "C3"}

    wp.set_plate_format("small")

    assert wp.excluded_wells == {"A1"}
