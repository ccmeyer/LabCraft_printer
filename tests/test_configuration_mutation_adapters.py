import copy
import json

import pytest

from Model import LocationModel, RackModel, WellPlate


RACK_LOCATIONS = {
    "rack_position_Left": {"X": 0, "Y": 0, "Z": 1000},
    "rack_position_Right": {"X": 0, "Y": 6000, "Z": 1000},
}


def _plates():
    return [
        {
            "name": "plate-a",
            "rows": 2,
            "columns": 2,
            "spacing": 10,
            "default": True,
            "calibrations": {
                "top_left": {"X": 100, "Y": 200, "Z": 300},
                "top_right": {"X": 100, "Y": 400, "Z": 300},
                "bottom_right": {"X": 300, "Y": 400, "Z": 300},
                "bottom_left": {"X": 300, "Y": 200, "Z": 300},
            },
        }
    ]


def test_canonical_location_model_rejects_every_direct_mutation_and_write(tmp_path):
    locations_path = tmp_path / "Locations.json"
    obstacles_path = tmp_path / "Obstacles.json"
    original = {"camera": {"X": 10, "Y": 20, "Z": 30}}
    locations_path.write_text(json.dumps(original), encoding="utf-8")
    obstacles_path.write_text(
        json.dumps({"boundaries": [], "obstacles": []}), encoding="utf-8"
    )
    model = LocationModel(str(locations_path), str(obstacles_path))
    model.load_locations()
    model.canonical_transaction_required = True

    operations = (
        lambda: model.add_location("new", 1, 2, 3),
        lambda: model.update_location("camera", 1, 2, 3),
        lambda: model.update_location_coords("camera", {"X": 1, "Y": 2, "Z": 3}),
        lambda: model.remove_location("camera"),
        model.save_locations,
    )
    for operation in operations:
        with pytest.raises(RuntimeError, match="Canonical"):
            operation()

    assert model.get_all_locations() == original
    assert json.loads(locations_path.read_text(encoding="utf-8")) == original


def test_canonical_rack_model_rejects_precommit_activation():
    model = RackModel(5, location_data=copy.deepcopy(RACK_LOCATIONS))
    before = copy.deepcopy(model.calibrations)
    model.temp_calibration_data = {
        "rack_position_Left": {"X": 1, "Y": 2, "Z": 3},
        "rack_position_Right": {"X": 4, "Y": 5, "Z": 6},
    }
    model.canonical_transaction_required = True

    with pytest.raises(RuntimeError, match="Canonical"):
        model.store_calibrations()
    with pytest.raises(RuntimeError, match="Canonical"):
        model.update_calibration_data()

    assert model.calibrations == before


def test_plate_proposal_is_complete_and_canonical_direct_writes_are_closed(tmp_path):
    path = tmp_path / "Plates.json"
    original = _plates()
    path.write_text(json.dumps(original), encoding="utf-8")
    model = WellPlate(copy.deepcopy(original), str(path))
    proposed_corners = {
        name: {axis: value + 1 for axis, value in coordinates.items()}
        for name, coordinates in original[0]["calibrations"].items()
    }
    model.temp_calibration_data = proposed_corners

    proposed = model.proposed_calibration_document()
    assert proposed[0]["calibrations"] == proposed_corners
    assert model.calibrations == original[0]["calibrations"]

    model.canonical_transaction_required = True
    for operation in (
        model.store_calibrations,
        model.update_calibration_data,
        model.save_calibrations_to_file,
    ):
        with pytest.raises(RuntimeError, match="Canonical"):
            operation()

    assert model.calibrations == original[0]["calibrations"]
    assert json.loads(path.read_text(encoding="utf-8")) == original
