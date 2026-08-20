import copy
import json
from pathlib import Path

import pytest

from ConfigurationSafetyPolicy import (
    ConfigurationChangeGuard,
    ConfigurationSafetyError,
    load_configuration_change_policy,
    parse_configuration_change_policy,
    parse_guard_assessment,
    parse_safety_bounds,
)


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

    assert policy.policy_id == "labcraft-rc2-configuration-guard-v1"
    assert policy.raw_sha256 == "7f724af4b2e88ab3d46d774f38bb6be8cdd6b82240027e04785bc80b9cfa4274"
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


def test_bounds_parser_is_strict_and_endpoint_check_is_global_only():
    bounds = parse_safety_bounds(_documents()["Obstacles.json"])
    assert bounds.require_endpoint({"X": -500, "Y": 0, "Z": 130000})["Z"] == 130000
    with pytest.raises(ConfigurationSafetyError, match="outside global bounds"):
        bounds.require_endpoint({"X": -501, "Y": 0, "Z": 0})

    malformed = _documents()["Obstacles.json"]
    malformed["boundaries"]["min"]["X"] = False
    with pytest.raises(ConfigurationSafetyError, match="integer"):
        parse_safety_bounds(malformed)


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
    assert assessment["required_confirmation_phrase"].endswith(assessment["proposal_sha256"][:12])
    assert parse_guard_assessment(assessment) == assessment


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
