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


def _plate_proposal(context, *, offset=10, labelled=True, guard=None):
    service = context.configuration_transactions
    before = read_governed_documents(context.paths)
    proposed = copy.deepcopy(before["Plates.json"])
    plate = next(item for item in proposed if item.get("calibrations"))
    for point in plate["calibrations"].values():
        point["X"] += offset
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
    assessment = active_guard.assess(
        before_documents=before,
        proposed_documents={"Plates.json": proposed},
        workflow="plate_calibration",
        target_keys=(plate["name"],),
        hardware_profile="current",
        preconditions={"captures": captures},
        governed_file_sha256=state.config_sha256,
    )
    return before, proposed, plate, state, assessment


def _commit_plate(service, proposed, state, assessment):
    return service.commit_documents(
        {"Plates.json": proposed},
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
        _before, proposed, plate, state, assessment = _plate_proposal(context)

        result = _commit_plate(service, proposed, state, assessment)

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


def test_unchanged_plate_calibration_refreshes_verification_without_writing_config(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        before, proposed, plate, state, assessment = _plate_proposal(
            context, offset=0
        )
        path = context.paths.config_root / "Plates.json"
        original = path.read_bytes()

        result = _commit_plate(service, proposed, state, assessment)

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
        _before, proposed, _plate, state, assessment = _plate_proposal(context)
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
            _commit_plate(service, proposed, state, assessment)

        assert (context.paths.config_root / "Plates.json").read_bytes() == original
        assert service.refresh(allow_pending=False).sequence == 0
    finally:
        context.close()


def test_workflow_name_without_controlled_evidence_remains_revoked(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        _before, proposed, plate, state, _assessment = _plate_proposal(context)

        result = service.commit_documents(
            {"Plates.json": proposed},
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
        _before, proposed, plate, state, assessment = _plate_proposal(
            context, labelled=False, guard=legacy_guard
        )
        source = _commit_plate(service, proposed, state, assessment)
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
        _before, proposed, _plate, state, assessment = _plate_proposal(
            context, labelled=False, guard=legacy_guard
        )
        source = _commit_plate(service, proposed, state, assessment)
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
        _before, proposed, plate, state, assessment = _plate_proposal(
            context, labelled=False, guard=legacy_guard
        )
        source = _commit_plate(service, proposed, state, assessment)
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
