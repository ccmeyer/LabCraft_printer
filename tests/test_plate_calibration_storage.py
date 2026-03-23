import json
from types import SimpleNamespace

from PySide6.QtWidgets import QDialog

import View
from Model import LocationModel, WellPlate
from View import WellPlateWidget


class _AcceptedPlateCalibrationDialog:
    def __init__(self, main_window, model, controller):
        self.main_window = main_window
        self.model = model
        self.controller = controller

    def exec(self):
        return QDialog.Accepted


def _make_plate_data(initial_cals):
    return [{
        "name": "plate-a",
        "rows": 2,
        "columns": 2,
        "spacing": 10,
        "default": True,
        "calibrations": initial_cals,
    }]


def test_open_calibration_dialog_persists_plate_corners_without_touching_locations(tmp_path, monkeypatch):
    initial_cals = {
        "top_left": {"X": 100, "Y": 200, "Z": 300},
        "top_right": {"X": 100, "Y": 400, "Z": 300},
        "bottom_right": {"X": 300, "Y": 400, "Z": 300},
        "bottom_left": {"X": 300, "Y": 200, "Z": 300},
    }
    updated_cals = {
        "top_left": {"X": 110, "Y": 210, "Z": 310},
        "top_right": {"X": 110, "Y": 410, "Z": 310},
        "bottom_right": {"X": 310, "Y": 410, "Z": 310},
        "bottom_left": {"X": 310, "Y": 210, "Z": 310},
    }

    plates_tmp = tmp_path / "Plates.json"
    plates_tmp.write_text(json.dumps(_make_plate_data(initial_cals)), encoding="utf-8")

    locations_baseline = {
        "pause": {"X": 9000, "Y": 8000, "Z": 7000},
        "plate": {"X": 6000, "Y": 5000, "Z": 4000},
    }
    locations_tmp = tmp_path / "Locations.json"
    locations_tmp.write_text(json.dumps(locations_baseline), encoding="utf-8")
    obstacles_tmp = tmp_path / "Obstacles.json"
    obstacles_tmp.write_text(json.dumps({"boundaries": [], "obstacles": []}), encoding="utf-8")

    well_plate = WellPlate(_make_plate_data(initial_cals), str(plates_tmp))
    well_plate.temp_calibration_data = updated_cals.copy()

    location_model = LocationModel(
        json_file_path=str(locations_tmp),
        obstacle_path=str(obstacles_tmp),
    )
    location_model.load_locations()

    move_calls = []
    controller = SimpleNamespace(
        move_to_location=lambda *args, **kwargs: move_calls.append((args, kwargs))
    )

    widget = WellPlateWidget.__new__(WellPlateWidget)
    widget.main_window = SimpleNamespace(
        popup_message=lambda *args, **kwargs: None,
        popup_yes_no=lambda *args, **kwargs: QDialog.Accepted,
        _is_no_response=lambda response: False,
    )
    widget.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            motors_are_enabled=lambda: True,
            motors_are_homed=lambda: True,
        ),
        rack_model=SimpleNamespace(
            get_gripper_printer_head=lambda: SimpleNamespace(is_calibration_chip=lambda: True)
        ),
        well_plate=well_plate,
        location_model=location_model,
    )
    widget.controller = controller

    monkeypatch.setattr(View, "PlateCalibrationDialog", _AcceptedPlateCalibrationDialog)

    WellPlateWidget.open_calibration_dialog(widget)

    assert move_calls == [(("plate",), {"z_offset": 500})]
    assert well_plate.calibrations == updated_cals
    saved_plates = json.loads(plates_tmp.read_text(encoding="utf-8"))
    assert saved_plates[0]["calibrations"] == updated_cals
    assert json.loads(locations_tmp.read_text(encoding="utf-8")) == locations_baseline
