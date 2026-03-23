from Model import WellPlate


def test_get_plate_reference_coords_returns_copy_of_top_left(tmp_path):
    plate_data = [{
        "name": "plate-a",
        "rows": 2,
        "columns": 2,
        "spacing": 10,
        "default": True,
        "calibrations": {
            "top_left": {"X": 10, "Y": 20, "Z": 30},
        },
    }]
    plates_tmp = tmp_path / "Plates.json"
    plates_tmp.write_text("[]", encoding="utf-8")

    wp = WellPlate(plate_data, str(plates_tmp))

    coords = wp.get_plate_reference_coords()

    assert coords == {"X": 10, "Y": 20, "Z": 30}
    coords["X"] = 999
    assert wp.calibrations["top_left"]["X"] == 10


def test_get_plate_reference_coords_returns_none_when_top_left_is_invalid(tmp_path):
    invalid_cases = [
        {},
        {"top_left": None},
        {"top_left": {"X": 10, "Y": 20}},
        {"top_left": {"X": 10, "Y": 20, "Z": "bad"}},
    ]
    plates_tmp = tmp_path / "Plates.json"
    plates_tmp.write_text("[]", encoding="utf-8")

    for calibrations in invalid_cases:
        plate_data = [{
            "name": "plate-a",
            "rows": 2,
            "columns": 2,
            "spacing": 10,
            "default": True,
            "calibrations": calibrations,
        }]
        wp = WellPlate(plate_data, str(plates_tmp))
        assert wp.get_plate_reference_coords() is None
