import pandas as pd

from Model import WellPlate


def test_well_ids_support_more_than_26_rows(tmp_path):
    plate_data = [{
        "name": "1536-32x48",
        "rows": 32,
        "columns": 48,
        "spacing": 4.5,
        "default": True,
        "calibrations": {},
    }]
    plates_tmp = tmp_path / "Plates.json"
    plates_tmp.write_text("[]", encoding="utf-8")
    wp = WellPlate(plate_data, str(plates_tmp))

    assert wp.get_well("A1") is not None
    assert wp.get_well("Z1") is not None
    assert wp.get_well("AA1") is not None
    assert wp.get_well("AF48") is not None

    af1 = wp.get_well("AF1")
    assert af1.row_num == 31


def test_assign_coordinates_supports_rows_after_z(tmp_path):
    plate_data = [{
        "name": "1536-32x48",
        "rows": 32,
        "columns": 48,
        "spacing": 4.5,
        "default": True,
        "calibrations": {},
    }]
    plates_tmp = tmp_path / "Plates.json"
    plates_tmp.write_text("[]", encoding="utf-8")
    wp = WellPlate(plate_data, str(plates_tmp))

    wp.assign_well_coordinates_by_row_col(31, 47, 1.0, 2.0, 3.0)
    assert wp.get_well("AF48").get_coordinates() == {"X": 1.0, "Y": 2.0, "Z": 3.0}

    coords_df = pd.DataFrame([
        {"row": 26, "column": 0, "X": 10.0, "Y": 11.0, "Z": 12.0},  # AA1
        {"row": 31, "column": 47, "X": 20.0, "Y": 21.0, "Z": 22.0},  # AF48
    ])
    wp.assign_all_well_coordinates(coords_df)

    assert wp.get_well("AA1").get_coordinates() == {"X": 10.0, "Y": 11.0, "Z": 12.0}
    assert wp.get_well("AF48").get_coordinates() == {"X": 20.0, "Y": 21.0, "Z": 22.0}
