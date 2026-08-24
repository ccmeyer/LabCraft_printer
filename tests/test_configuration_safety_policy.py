import copy
import json
from pathlib import Path

import numpy as np
import pytest

from ConfigurationSafetyPolicy import (
    ConfigurationChangeGuard,
    ConfigurationSafetyError,
    load_configuration_change_policy,
    parse_configuration_change_policy,
    parse_guard_assessment,
    parse_safety_bounds,
)
from Model import Well, WellPlate


PRESETS = Path(__file__).resolve().parents[1] / "FreeRTOS-interface" / "Presets"


def _documents():
    return {
        filename: json.loads((PRESETS / filename).read_text(encoding="utf-8"))
        for filename in ("Locations.json", "Plates.json", "Settings.json", "Obstacles.json")
    }


def _guard():
    docs = _documents()
    return ConfigurationChangeGuard(
        load_configuration_change_policy(),
        parse_safety_bounds(docs["Obstacles.json"]),
    )


def test_tracked_policy_loads_with_stable_release_hash_and_all_strong_fallback():
    policy = load_configuration_change_policy()

    assert policy.policy_id == "labcraft-configuration-guard-v2"
    assert policy.raw_sha256 == "baecb5f39a6f1efa9fbd0adaa478f3fde44b56c4c24df89511f66b72b8d924c4"
    assert policy.schema_version == 2
    assert policy.confirmation_mode == "explicit_checkbox"
    assert policy.position_telemetry_max_age_ms == 2500
    assert dict(policy.warning_thresholds_steps) == {}
    assert policy.classify_location("Camera") == "camera"
    assert policy.is_pair_only_name("RACK_POSITION_left")
    assert policy.has_reserved_prefix("Slot-3")


def test_policy_rejects_duplicate_names_and_boolean_thresholds():
    path = Path(__file__).resolve().parents[1] / "FreeRTOS-interface" / "Policies" / "configuration_change_policy_v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["reserved_location_names"].append("CAMERA")
    with pytest.raises(ConfigurationSafetyError, match="duplicates"):
        parse_configuration_change_policy(payload, raw_sha256="0" * 64)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["warning_thresholds_steps"] = {"generic": {"X": True}}
    with pytest.raises(ConfigurationSafetyError, match="nonnegative integers"):
        parse_configuration_change_policy(payload, raw_sha256="0" * 64)


def test_v1_policy_and_assessment_remain_readable_without_changing_the_file():
    path = (
        Path(__file__).resolve().parents[1]
        / "FreeRTOS-interface"
        / "Policies"
        / "configuration_change_policy_v1.json"
    )
    policy = load_configuration_change_policy(path)
    docs = _documents()
    proposed = copy.deepcopy(docs["Locations.json"])
    proposed["camera"]["Y"] += 1
    assessment = ConfigurationChangeGuard(
        policy, parse_safety_bounds(docs["Obstacles.json"])
    ).assess(
        before_documents=docs,
        proposed_documents={"Locations.json": proposed},
        workflow="named_location_modify",
        target_keys=("camera",),
        hardware_profile="current",
    )

    assert policy.schema_version == 1
    assert policy.confirmation_mode == "typed_phrase"
    assert assessment["schema_version"] == 1
    assert assessment["required_confirmation_phrase"].endswith(
        assessment["proposal_sha256"][:12]
    )
    assert parse_guard_assessment(assessment) == assessment


def test_bounds_parser_is_strict_and_endpoint_check_is_global_only():
    bounds = parse_safety_bounds(_documents()["Obstacles.json"])
    assert bounds.require_endpoint({"X": -500, "Y": 0, "Z": 130000})["Z"] == 130000
    with pytest.raises(ConfigurationSafetyError, match="outside global bounds"):
        bounds.require_endpoint({"X": -501, "Y": 0, "Z": 0})

    malformed = _documents()["Obstacles.json"]
    malformed["boundaries"]["min"]["X"] = False
    with pytest.raises(ConfigurationSafetyError, match="integer"):
        parse_safety_bounds(malformed)


def test_real_384_well_plate_coordinates_are_builtin_integers_and_pass_guard():
    documents = _documents()
    well_plate = WellPlate(documents["Plates.json"], str(PRESETS / "Plates.json"))
    well_plate.set_plate_format("shallow-384_well_plate")

    coordinates = well_plate.get_well("F2").get_coordinates()
    directly_calculated = well_plate.get_well_coords(5, 1)

    assert coordinates == directly_calculated
    assert all(type(value) is int for value in coordinates.values())
    assert _guard().validate_endpoint(coordinates) == coordinates


def test_well_coordinate_normalization_accepts_exact_integral_values_without_truncation():
    well = Well("F2")

    well.assign_coordinates(np.int64(10), 20.0, np.float64(30.0))

    assert well.get_coordinates() == {"X": 10, "Y": 20, "Z": 30}
    assert all(type(value) is int for value in well.get_coordinates().values())


@pytest.mark.parametrize(
    "invalid",
    [1.5, np.float64(1.25), float("nan"), float("inf"), True, np.bool_(True)],
)
def test_well_coordinate_normalization_rejects_non_integral_values(invalid):
    well = Well("F2")

    with pytest.raises(ValueError, match="must be an integer"):
        well.assign_coordinates(invalid, 20, 30)


def test_camera_assessment_contains_exact_delta_policy_and_proposal_binding():
    docs = _documents()
    proposed = copy.deepcopy(docs["Locations.json"])
    proposed["camera"]["Y"] += 1234
    assessment = _guard().assess(
        before_documents=docs,
        proposed_documents={"Locations.json": proposed},
        workflow="named_location_modify",
        target_keys=("camera",),
        hardware_profile="current",
        governed_file_sha256={name: str(index) * 64 for index, name in enumerate(sorted(docs), 1)},
        preconditions={"captures": [{"trust_epoch": 5}]},
    )

    assert assessment["result"] == "strong_confirmation"
    assert assessment["target_class"] == "camera"
    assert assessment["changes"][0]["signed_delta"] == {"X": 0, "Y": 1234, "Z": 0}
    assert assessment["confirmation_mode"] == "explicit_checkbox"
    assert assessment["confirmation_version"] == 1
    assert (
        assessment["authorization_consequence"]
        == "verified_by_controlled_position_capture"
    )
    assert "camera" in assessment["required_acknowledgement"]
    assert "1234 steps" in assessment["required_acknowledgement"]
    assert parse_guard_assessment(assessment) == assessment


def test_plate_calibration_requires_atomic_pause_z_derivation():
    docs = _documents()
    plates = copy.deepcopy(docs["Plates.json"])
    active = next(plate for plate in plates if plate["default"])
    for point in active["calibrations"].values():
        point["Z"] += 25
    locations = copy.deepcopy(docs["Locations.json"])
    pause_name = next(name for name in locations if name.casefold() == "pause")
    original_pause = copy.deepcopy(locations[pause_name])
    locations[pause_name]["Z"] = active["calibrations"]["top_left"]["Z"]

    assessment = _guard().assess(
        before_documents=docs,
        proposed_documents={
            "Plates.json": plates,
            "Locations.json": locations,
        },
        workflow="plate_calibration",
        target_keys=(active["name"],),
        hardware_profile="current",
    )

    assert assessment["result"] != "reject"
    assert locations[pause_name]["X"] == original_pause["X"]
    assert locations[pause_name]["Y"] == original_pause["Y"]
    assert locations[pause_name]["Z"] == active["calibrations"]["top_left"]["Z"]
    assert "plate_pause_location_derived" in {
        check["code"] for check in assessment["hard_checks"]
    }
    assert any(change["target_key"] == pause_name for change in assessment["changes"])

    bad_locations = copy.deepcopy(locations)
    bad_locations[pause_name]["X"] += 1
    rejected = _guard().assess(
        before_documents=docs,
        proposed_documents={
            "Plates.json": plates,
            "Locations.json": bad_locations,
        },
        workflow="plate_calibration",
        target_keys=(active["name"],),
        hardware_profile="current",
    )
    assert rejected["result"] == "reject"
    assert "cannot change Pause X or Y" in rejected["hard_checks"][-1]["message"]

    missing = _guard().assess(
        before_documents=docs,
        proposed_documents={"Plates.json": plates},
        workflow="plate_calibration",
        target_keys=(active["name"],),
        hardware_profile="current",
    )
    assert missing["result"] == "reject"
    assert "must include the derived Pause" in missing["hard_checks"][-1]["message"]

    wrong_z = copy.deepcopy(locations)
    wrong_z[pause_name]["Z"] += 1
    rejected = _guard().assess(
        before_documents=docs,
        proposed_documents={
            "Plates.json": plates,
            "Locations.json": wrong_z,
        },
        workflow="plate_calibration",
        target_keys=(active["name"],),
        hardware_profile="current",
    )
    assert rejected["result"] == "reject"
    assert "must exactly match" in rejected["hard_checks"][-1]["message"]


def test_generic_editor_cannot_write_rack_pair_or_slot_namespace():
    docs = _documents()
    proposed = copy.deepcopy(docs["Locations.json"])
    proposed["rack_position_Left"]["Y"] += 1
    assessment = _guard().assess(
        before_documents=docs,
        proposed_documents={"Locations.json": proposed},
        workflow="named_location_modify",
        target_keys=("rack_position_Left",),
        hardware_profile="current",
    )
    assert assessment["result"] == "reject"

    proposed = copy.deepcopy(docs["Locations.json"])
    proposed["slot-0"] = {"X": 1, "Y": 1, "Z": 1}
    assessment = _guard().assess(
        before_documents=docs,
        proposed_documents={"Locations.json": proposed},
        workflow="named_location_add",
        target_keys=("slot-0",),
        hardware_profile="current",
    )
    assert assessment["result"] == "reject"


def test_rack_reversal_and_plate_self_intersection_are_hard_rejections():
    docs = _documents()
    rack = copy.deepcopy(docs["Locations.json"])
    rack["rack_position_Left"], rack["rack_position_Right"] = (
        rack["rack_position_Right"], rack["rack_position_Left"]
    )
    rack_assessment = _guard().assess(
        before_documents=docs,
        proposed_documents={"Locations.json": rack},
        workflow="rack_calibration",
        target_keys=("rack_position_Left", "rack_position_Right"),
        hardware_profile="current",
    )
    assert rack_assessment["result"] == "reject"

    plates = copy.deepcopy(docs["Plates.json"])
    active = next(plate for plate in plates if plate["default"])
    active["calibrations"]["top_right"], active["calibrations"]["bottom_right"] = (
        active["calibrations"]["bottom_right"], active["calibrations"]["top_right"]
    )
    plate_assessment = _guard().assess(
        before_documents=docs,
        proposed_documents={"Plates.json": plates},
        workflow="plate_calibration",
        target_keys=(active["name"],),
        hardware_profile="current",
    )
    assert plate_assessment["result"] == "reject"
