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
