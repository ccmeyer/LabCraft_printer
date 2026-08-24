import json
from types import SimpleNamespace

from PySide6.QtWidgets import QDialog

import View
from Model import LocationModel, WellPlate
from View import WellPlateWidget


def _make_plate_data(initial_cals):
    return [{
        "name": "plate-a",
        "rows": 2,
        "columns": 2,
        "spacing": 10,
        "default": True,
        "calibrations": initial_cals,
    }]


def test_open_calibration_dialog_uses_guarded_entry_without_generic_plate_move(tmp_path):
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
    location_model = LocationModel(
        json_file_path=str(locations_tmp),
        obstacle_path=str(obstacles_tmp),
    )
    location_model.load_locations()

    entry_calls = []
    controller = SimpleNamespace(
        plate_calibration_entry_preflight=lambda: {
            "allowed": True,
            "verified": True,
            "target_key": "plate:plate-a",
        },
        begin_plate_calibration_entry=lambda **kwargs: entry_calls.append(kwargs) or {
            "session_token": "session-1",
            "state": "staging",
        },
    )

    widget = WellPlateWidget.__new__(WellPlateWidget)
    widget.main_window = SimpleNamespace(
        popup_message=lambda *args, **kwargs: None,
        popup_choice=lambda *args, **kwargs: "Cancel",
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
    widget._plate_calibration_session_token = None
    widget._plate_calibration_dialog = None
    widget.calibration_button = SimpleNamespace(
        setEnabled=lambda _value: None,
        setText=lambda _value: None,
    )

    assert WellPlateWidget.open_calibration_dialog(widget) is True

    assert entry_calls == [{"manual_first": False}]
    assert widget._plate_calibration_session_token == "session-1"
    assert well_plate.calibrations == initial_cals
    saved_plates = json.loads(plates_tmp.read_text(encoding="utf-8"))
    assert saved_plates[0]["calibrations"] == initial_cals
    assert json.loads(locations_tmp.read_text(encoding="utf-8")) == locations_baseline


def test_historical_calibration_review_issues_no_motion_and_requires_new_launch():
    calls = []
    widget = WellPlateWidget.__new__(WellPlateWidget)
    widget._plate_calibration_session_token = None
    widget._plate_calibration_dialog = None
    widget.model = SimpleNamespace()
    widget.controller = SimpleNamespace(
        plate_calibration_entry_preflight=lambda: {
            "allowed": True,
            "verified": False,
            "target_key": "plate:plate-a",
            "historical_candidate": {"source_event_id": "event-1"},
        },
        begin_plate_calibration_entry=lambda **kwargs: calls.append(
            ("motion", kwargs)
        ),
    )
    widget.main_window = SimpleNamespace(
        popup_choice=lambda *args, **kwargs: "Review Existing Calibration",
        review_configuration_target=lambda target: calls.append(("review", target)),
        popup_message=lambda *args, **kwargs: calls.append(("message", args)),
    )

    result = WellPlateWidget.open_calibration_dialog(widget)

    assert result is False
    assert calls[0] == ("review", "plate:plate-a")
    assert not any(call[0] == "motion" for call in calls)
    assert widget._plate_calibration_session_token is None


def test_well_plate_calibration_save_updates_local_copy_without_touching_preset(tmp_path):
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
    preset_path = tmp_path / "Presets" / "Plates.json"
    local_path = tmp_path / "local" / "Plates.json"
    preset_path.parent.mkdir()
    local_path.parent.mkdir()
    preset_text = json.dumps(_make_plate_data(initial_cals), indent=2)
    preset_path.write_text(preset_text, encoding="utf-8")
    local_path.write_text(json.dumps(_make_plate_data(initial_cals), indent=2), encoding="utf-8")

    well_plate = WellPlate(json.loads(local_path.read_text(encoding="utf-8")), str(local_path))
    well_plate.temp_calibration_data = updated_cals.copy()

    well_plate.update_calibration_data()

    assert json.loads(local_path.read_text(encoding="utf-8"))[0]["calibrations"] == updated_cals
    assert preset_path.read_text(encoding="utf-8") == preset_text


def test_location_save_updates_local_copy_without_touching_preset(tmp_path):
    preset_path = tmp_path / "Presets" / "Locations.json"
    local_path = tmp_path / "local" / "Locations.json"
    obstacles_path = tmp_path / "local" / "Obstacles.json"
    preset_path.parent.mkdir()
    local_path.parent.mkdir()
    preset_payload = {"pause": {"X": 1, "Y": 2, "Z": 3}}
    local_payload = {"pause": {"X": 10, "Y": 20, "Z": 30}}
    preset_text = json.dumps(preset_payload, indent=2)
    preset_path.write_text(preset_text, encoding="utf-8")
    local_path.write_text(json.dumps(local_payload, indent=2), encoding="utf-8")
    obstacles_path.write_text(json.dumps({"boundaries": [], "obstacles": []}), encoding="utf-8")

    location_model = LocationModel(
        json_file_path=str(local_path),
        obstacle_path=str(obstacles_path),
    )
    location_model.load_locations()
    location_model.update_location("pause", 40, 50, 60)
    location_model.save_locations()

    assert json.loads(local_path.read_text(encoding="utf-8"))["pause"] == {"X": 40, "Y": 50, "Z": 60}
    assert preset_path.read_text(encoding="utf-8") == preset_text
