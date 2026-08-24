import copy
import json
from pathlib import Path

import pytest

from ConfigurationSafetyPolicy import (
    ConfigurationChangeGuard,
    load_configuration_change_policy,
)
from MachineDataTransactions import (
    ConfigurationConflictError,
    ConfigurationRecoveryRequired,
    ConfigurationValidationError,
    read_governed_documents,
)
from tests.test_machine_data_transactions import _active_context


PLATE_POINTS = ("top_left", "top_right", "bottom_right", "bottom_left")
RACK_POINTS = ("rack_position_Left", "rack_position_Right")


def _capture(workflow, name, point, machine_uuid, *, trust_epoch=7, labelled=True):
    capture = {
        "ready": True,
        "reason_codes": [],
        "machine_uuid": machine_uuid,
        "trust_epoch": trust_epoch,
        "captured_position": copy.deepcopy(point),
        "expected_position": copy.deepcopy(point),
        "position_reconciliation": {
            "state": "settled",
            "expected_position": copy.deepcopy(point),
            "reported_position": copy.deepcopy(point),
            "trust_epoch": trust_epoch,
        },
        "telemetry": {
            axis: {"generation": 4, "age_ms": 2.0, "value": point[axis]}
            for axis in ("X", "Y", "Z")
        },
        "captured_monotonic": 10.0,
        "telemetry_max_age_ms": 2500,
    }
    if labelled:
        capture.update(workflow=workflow, target_key=name)
    return capture


def _plate_proposal(
    context, *, offset=10, z_offset=0, labelled=True, guard=None
):
    service = context.configuration_transactions
    before = read_governed_documents(context.paths)
    proposed = copy.deepcopy(before["Plates.json"])
    plate = next(item for item in proposed if item.get("calibrations"))
    for point in plate["calibrations"].values():
        point["X"] += offset
        point["Z"] += z_offset
    captures = [
        _capture(
            "plate_calibration",
            name,
            plate["calibrations"][name],
            context.identity.machine_uuid,
            labelled=labelled,
        )
        for name in PLATE_POINTS
    ]
    state = service.refresh(allow_pending=False)
    active_guard = guard or context.configuration_safety_guard
    proposed_documents = {"Plates.json": proposed}
    if active_guard.policy.schema_version == 2:
        proposed_locations = copy.deepcopy(before["Locations.json"])
        pause_name = next(
            name for name in proposed_locations if str(name).casefold() == "pause"
        )
        proposed_locations[pause_name]["Z"] = plate["calibrations"]["top_left"]["Z"]
        proposed_documents["Locations.json"] = proposed_locations
    assessment = active_guard.assess(
        before_documents=before,
        proposed_documents=proposed_documents,
        workflow="plate_calibration",
        target_keys=(plate["name"],),
        hardware_profile="current",
        preconditions={"captures": captures},
        governed_file_sha256=state.config_sha256,
    )
    return before, proposed_documents, plate, state, assessment


def _commit_plate(service, proposed_documents, state, assessment):
    return service.commit_documents(
        proposed_documents,
        operator="Alice",
        reason="controlled plate calibration",
        workflow="plate_calibration",
        expected_config_sha256=state.config_sha256,
        guard_evidence=assessment,
    )


def test_changed_plate_calibration_is_atomically_verified(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        _before, proposed_documents, plate, state, assessment = _plate_proposal(context)

        result = _commit_plate(service, proposed_documents, state, assessment)

        key = f"plate:{plate['name'].casefold()}"
        authorization = result.state.authorization[key]
        assert authorization["state"] == "verified_by_controlled_calibration"
        assert authorization["verification_method"] == "controlled_calibration"
        assert authorization["verified_by"] == "Alice"
        assert authorization["evidence_reference"] == result.state.latest_event_path
        event = json.loads(
            (context.paths.machine_root / result.state.latest_event_path).read_text(
                encoding="utf-8"
            )
        )
        assert event["authorization_after"][key] == authorization
        pause_authorization = result.state.authorization["location:pause"]
        assert pause_authorization["state"] == "verified_by_controlled_calibration"
        locations = read_governed_documents(context.paths)["Locations.json"]
        pause_name = next(name for name in locations if name.casefold() == "pause")
        assert locations[pause_name]["Z"] == plate["calibrations"]["top_left"]["Z"]
        assert any(
            change.get("controlled_calibration", {}).get("primary_target_key") == key
            for change in event["changes"]
        )
    finally:
        context.close()


def test_changed_rack_calibration_verifies_primary_and_both_anchors(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        before = read_governed_documents(context.paths)
        proposed = copy.deepcopy(before["Locations.json"])
        for name in RACK_POINTS:
            proposed[name]["X"] += 10
        captures = [
            _capture(
                "rack_calibration",
                name,
                proposed[name],
                context.identity.machine_uuid,
            )
            for name in RACK_POINTS
        ]
        state = service.refresh(allow_pending=False)
        assessment = context.configuration_safety_guard.assess(
            before_documents=before,
            proposed_documents={"Locations.json": proposed},
            workflow="rack_calibration",
            target_keys=RACK_POINTS,
            hardware_profile="current",
            preconditions={"captures": captures},
            governed_file_sha256=state.config_sha256,
        )

        result = service.commit_documents(
            {"Locations.json": proposed},
            operator="Alice",
            reason="controlled rack calibration",
            workflow="rack_calibration",
            expected_config_sha256=state.config_sha256,
            guard_evidence=assessment,
        )

        for key in (
            "rack:primary",
            "location:rack_position_left",
            "location:rack_position_right",
        ):
            assert (
                result.state.authorization[key]["state"]
                == "verified_by_controlled_calibration"
            )
    finally:
        context.close()


def test_plate_top_left_z_atomically_updates_only_pause_z(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        before, proposed_documents, plate, state, assessment = _plate_proposal(
            context,
            offset=0,
            z_offset=25,
        )
        prior_locations = before["Locations.json"]
        pause_name = next(
            name for name in prior_locations if name.casefold() == "pause"
        )

        result = _commit_plate(
            service, proposed_documents, state, assessment
        )
        current_locations = read_governed_documents(context.paths)["Locations.json"]

        assert current_locations[pause_name]["X"] == prior_locations[pause_name]["X"]
        assert current_locations[pause_name]["Y"] == prior_locations[pause_name]["Y"]
        assert (
            current_locations[pause_name]["Z"]
            == plate["calibrations"]["top_left"]["Z"]
        )
        assert {
            name: value
            for name, value in current_locations.items()
            if name != pause_name
        } == {
            name: value
            for name, value in prior_locations.items()
            if name != pause_name
        }
        assert (
            result.state.authorization["location:pause"]["state"]
            == "verified_by_controlled_calibration"
        )
    finally:
        context.close()


@pytest.mark.parametrize(
    ("workflow", "target_name"),
    (
        ("named_location_modify", "camera"),
        ("named_location_add", "operator-checkpoint"),
    ),
)
def test_live_named_location_capture_is_atomically_verified(
    tmp_path, workflow, target_name
):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        before = read_governed_documents(context.paths)
        proposed = copy.deepcopy(before["Locations.json"])
        if workflow == "named_location_modify":
            proposed[target_name]["Y"] += 10
        else:
            proposed[target_name] = {"X": 12000, "Y": 13000, "Z": 14000}
        state = service.refresh(allow_pending=False)
        assessment = context.configuration_safety_guard.assess(
            before_documents=before,
            proposed_documents={"Locations.json": proposed},
            workflow=workflow,
            target_keys=(target_name,),
            hardware_profile="current",
            preconditions={
                "captures": [
                    _capture(
                        workflow,
                        target_name,
                        proposed[target_name],
                        context.identity.machine_uuid,
                    )
                ]
            },
            governed_file_sha256=state.config_sha256,
        )

        result = service.commit_documents(
            {"Locations.json": proposed},
            operator="Alice",
            reason="save live captured location",
            workflow=workflow,
            expected_config_sha256=state.config_sha256,
            guard_evidence=assessment,
        )

        key = f"location:{target_name.casefold()}"
        authorization = result.state.authorization[key]
        assert authorization["state"] == "operator_verified"
        assert authorization["verification_method"] == "controlled_position_capture"
        assert authorization["verified_by"] == "Alice"
        assert authorization["evidence_reference"] == result.state.latest_event_path
    finally:
        context.close()


def test_unchanged_live_location_capture_refreshes_verification_without_config_write(
    tmp_path,
):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        before = read_governed_documents(context.paths)
        state = service.refresh(allow_pending=False)
        point = before["Locations.json"]["camera"]
        assessment = context.configuration_safety_guard.assess(
            before_documents=before,
            proposed_documents={"Locations.json": before["Locations.json"]},
            workflow="named_location_modify",
            target_keys=("camera",),
            hardware_profile="current",
            preconditions={
                "captures": [
                    _capture(
                        "named_location_modify",
                        "camera",
                        point,
                        context.identity.machine_uuid,
                    )
                ]
            },
            governed_file_sha256=state.config_sha256,
        )
        locations_path = context.paths.config_root / "Locations.json"
        original = locations_path.read_bytes()

        result = service.commit_documents(
            {"Locations.json": before["Locations.json"]},
            operator="Alice",
            reason="reconfirm live captured location",
            workflow="named_location_modify",
            expected_config_sha256=state.config_sha256,
            guard_evidence=assessment,
        )

        assert result.event_type == "verification"
        assert result.message == "Unchanged named location reverified and audited."
        assert locations_path.read_bytes() == original
        assert result.state.authorization["location:camera"]["state"] == "operator_verified"
    finally:
        context.close()


def test_named_location_capture_with_incomplete_evidence_is_rejected_atomically(
    tmp_path,
):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        before = read_governed_documents(context.paths)
        proposed = copy.deepcopy(before["Locations.json"])
        proposed["camera"]["Y"] += 10
        state = service.refresh(allow_pending=False)
        assessment = context.configuration_safety_guard.assess(
            before_documents=before,
            proposed_documents={"Locations.json": proposed},
            workflow="named_location_modify",
            target_keys=("camera",),
            hardware_profile="current",
            preconditions={"captures": []},
            governed_file_sha256=state.config_sha256,
        )
        original = (context.paths.config_root / "Locations.json").read_bytes()

        with pytest.raises(
            ConfigurationValidationError,
            match="requires one capture record",
        ):
            service.commit_documents(
                {"Locations.json": proposed},
                operator="Alice",
                reason="missing live capture",
                workflow="named_location_modify",
                expected_config_sha256=state.config_sha256,
                guard_evidence=assessment,
            )

        assert (context.paths.config_root / "Locations.json").read_bytes() == original
        assert service.refresh(allow_pending=False).sequence == 0
    finally:
        context.close()


def test_named_location_workflow_string_without_guarded_capture_remains_revoked(
    tmp_path,
):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        before = read_governed_documents(context.paths)
        proposed = copy.deepcopy(before["Locations.json"])
        proposed["camera"]["Y"] += 10

        result = service.commit_documents(
            {"Locations.json": proposed},
            operator="Alice",
            reason="workflow label is not evidence",
            workflow="named_location_modify",
        )

        assert (
            result.state.authorization["location:camera"]["state"]
            == "revoked_pending_verification"
        )
    finally:
        context.close()


def test_unchanged_plate_calibration_refreshes_verification_without_writing_config(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        before, proposed_documents, plate, state, assessment = _plate_proposal(
            context, offset=0
        )
        path = context.paths.config_root / "Plates.json"
        original = path.read_bytes()

        result = _commit_plate(service, proposed_documents, state, assessment)

        assert result.event_type == "verification"
        assert result.message == "Unchanged calibration reverified and audited."
        assert path.read_bytes() == original
        assert result.state.sequence == 1
        assert (
            result.state.authorization[f"plate:{plate['name'].casefold()}"]["state"]
            == "verified_by_controlled_calibration"
        )
    finally:
        context.close()


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("missing_axis", "lacks Z telemetry"),
        ("stale_axis", "Z telemetry is stale"),
        ("cross_machine", "belongs to another machine"),
        ("trust_changed", "do not share one trust epoch"),
        ("value_mismatch", "differs from the committed calibration"),
    ),
)
def test_invalid_controlled_evidence_rejects_with_bytes_and_history_unchanged(
    tmp_path, case, message
):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        _before, proposed_documents, _plate, state, assessment = _plate_proposal(context)
        capture = assessment["preconditions"]["captures"][2]
        if case == "missing_axis":
            capture["telemetry"].pop("Z")
        elif case == "stale_axis":
            capture["telemetry"]["Z"]["age_ms"] = 2501
        elif case == "cross_machine":
            capture["machine_uuid"] = "00000000-0000-0000-0000-000000000999"
        elif case == "trust_changed":
            capture["trust_epoch"] += 1
            capture["position_reconciliation"]["trust_epoch"] += 1
        else:
            capture["captured_position"]["X"] += 1
            capture["expected_position"]["X"] += 1
            capture["position_reconciliation"]["expected_position"]["X"] += 1
            capture["position_reconciliation"]["reported_position"]["X"] += 1
            capture["telemetry"]["X"]["value"] += 1
        original = (context.paths.config_root / "Plates.json").read_bytes()

        with pytest.raises(ConfigurationValidationError, match=message):
            _commit_plate(service, proposed_documents, state, assessment)

        assert (context.paths.config_root / "Plates.json").read_bytes() == original
        assert service.refresh(allow_pending=False).sequence == 0
    finally:
        context.close()


def test_workflow_name_without_controlled_evidence_remains_revoked(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        _before, proposed_documents, plate, state, _assessment = _plate_proposal(context)

        result = service.commit_documents(
            proposed_documents,
            operator="Alice",
            reason="spoofed workflow string",
            workflow="plate_calibration",
            expected_config_sha256=state.config_sha256,
        )

        assert (
            result.state.authorization[f"plate:{plate['name'].casefold()}"]["state"]
            == "revoked_pending_verification"
        )
    finally:
        context.close()


def test_legacy_calibration_event_can_be_promoted_once_without_changing_bytes(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        legacy_policy = load_configuration_change_policy(
            Path(__file__).resolve().parents[1]
            / "FreeRTOS-interface"
            / "Policies"
            / "configuration_change_policy_v1.json"
        )
        legacy_guard = ConfigurationChangeGuard(
            legacy_policy, context.configuration_safety_guard.bounds
        )
        service.configuration_safety_guard = legacy_guard
        _before, proposed_documents, plate, state, assessment = _plate_proposal(
            context, labelled=False, guard=legacy_guard
        )
        source = _commit_plate(service, proposed_documents, state, assessment)
        key = f"plate:{plate['name'].casefold()}"
        assert source.state.authorization[key]["state"] == "revoked_pending_verification"
        original = (context.paths.config_root / "Plates.json").read_bytes()

        candidates = service.controlled_calibration_promotion_candidates()
        assert candidates[key]["source_event_id"] == source.event_id
        assert candidates[key]["integrity"] == "verified"
        promoted = service.promote_controlled_calibration(
            key,
            source.event_id,
            operator="Bob",
            reason="review existing controlled plate calibration",
        )

        assert (context.paths.config_root / "Plates.json").read_bytes() == original
        assert promoted.event_type == "verification"
        assert promoted.state.authorization[key]["state"] == "verified_by_controlled_calibration"
        assert promoted.state.authorization[key]["evidence_reference"] == source.state.latest_event_path
        assert service.controlled_calibration_promotion_candidates() == {}
        with pytest.raises(ConfigurationConflictError, match="no longer eligible"):
            service.promote_controlled_calibration(
                key,
                source.event_id,
                operator="Bob",
                reason="replay",
            )
    finally:
        context.close()


def test_damaged_history_blocks_controlled_calibration_promotion(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        legacy_policy = load_configuration_change_policy(
            Path(__file__).resolve().parents[1]
            / "FreeRTOS-interface"
            / "Policies"
            / "configuration_change_policy_v1.json"
        )
        legacy_guard = ConfigurationChangeGuard(
            legacy_policy, context.configuration_safety_guard.bounds
        )
        service.configuration_safety_guard = legacy_guard
        _before, proposed_documents, _plate, state, assessment = _plate_proposal(
            context, labelled=False, guard=legacy_guard
        )
        source = _commit_plate(service, proposed_documents, state, assessment)
        source_path = context.paths.machine_root / source.state.latest_event_path
        source_path.write_bytes(source_path.read_bytes() + b" ")

        with pytest.raises(ConfigurationRecoveryRequired):
            service.controlled_calibration_promotion_candidates()
    finally:
        context.close()


def test_historical_promotion_rejects_a_source_after_later_target_change(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        legacy_policy = load_configuration_change_policy(
            Path(__file__).resolve().parents[1]
            / "FreeRTOS-interface"
            / "Policies"
            / "configuration_change_policy_v1.json"
        )
        legacy_guard = ConfigurationChangeGuard(
            legacy_policy, context.configuration_safety_guard.bounds
        )
        service.configuration_safety_guard = legacy_guard
        _before, proposed_documents, plate, state, assessment = _plate_proposal(
            context, labelled=False, guard=legacy_guard
        )
        source = _commit_plate(service, proposed_documents, state, assessment)
        key = f"plate:{plate['name'].casefold()}"

        service.record_attempt(
            event_type="rejected",
            operator="Alice",
            reason="later rejected capture does not change target",
            workflow="plate_calibration",
            details={"target_key": "top_left", "stage": "capture"},
        )
        assert service.controlled_calibration_promotion_candidates()[key][
            "source_event_id"
        ] == source.event_id

        current = read_governed_documents(context.paths)
        later = copy.deepcopy(current["Plates.json"])
        changed_plate = next(item for item in later if item["name"] == plate["name"])
        for point in changed_plate["calibrations"].values():
            point["X"] += 1
        current_state = service.refresh(allow_pending=False)
        service.commit_documents(
            {"Plates.json": later},
            operator="Alice",
            reason="later target change",
            workflow="plate_calibration",
            expected_config_sha256=current_state.config_sha256,
        )

        assert key not in service.controlled_calibration_promotion_candidates()
    finally:
        context.close()
