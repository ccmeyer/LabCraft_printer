import json
import pytest

from Model import Model


def _stub_model():
    m = Model.__new__(Model)
    return m


def test_load_all_plate_data_rejects_duplicate_names(tmp_path):
    p = tmp_path / "Plates.json"
    p.write_text(json.dumps([
        {"name": "p", "rows": 1, "columns": 1, "spacing": 10, "default": True, "calibrations": {}},
        {"name": "p", "rows": 2, "columns": 2, "spacing": 10, "default": False, "calibrations": {}},
    ]), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate plate name"):
        Model.load_all_plate_data(_stub_model(), str(p))


def test_load_all_plate_data_requires_single_default(tmp_path):
    p = tmp_path / "Plates.json"
    p.write_text(json.dumps([
        {"name": "p1", "rows": 1, "columns": 1, "spacing": 10, "default": False, "calibrations": {}},
        {"name": "p2", "rows": 2, "columns": 2, "spacing": 10, "default": False, "calibrations": {}},
    ]), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one default"):
        Model.load_all_plate_data(_stub_model(), str(p))
