import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from Controller import Controller
from ConfigurationSafetyPolicy import ConfigurationSafetyError
from MachineDataTransactions import (
    ConfigurationConflictError,
    ConfigurationRecoveryRequired,
    ConfigurationValidationError,
    read_governed_documents,
)
from tests.test_machine_data_transactions import _active_context


class _Signal:
    def __init__(self):
        self.events = []

    def emit(self, *args):
        self.events.append(args)


class _Machine:
    def __init__(self):
        self.calls = []

    def set_absolute_XY(self, x, y, **kwargs):
        self.calls.append((x, y))
        return True


def _position_capture(workflow, name, point, machine_uuid, *, trust_epoch=7):
    return {
        "workflow": workflow,
        "target_key": name,
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


def test_v2_guard_confirmation_requires_exact_hash_checkbox_and_version(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        before = read_governed_documents(context.paths)
        locations = copy.deepcopy(before["Locations.json"])
        locations["camera"]["Y"] += 25
        assessment = context.configuration_safety_guard.assess(
            before_documents=before,
            proposed_documents={"Locations.json": locations},
            workflow="named_location_modify",
            target_keys=("camera",),
            hardware_profile="current",
        )
        controller = Controller.__new__(Controller)

        rejected = (
            {},
            {
                "proposal_sha256": "0" * 64,
                "acknowledged": True,
                "acknowledgement_version": assessment["confirmation_version"],
            },
            {
                "proposal_sha256": assessment["proposal_sha256"],
                "acknowledged": False,
                "acknowledgement_version": assessment["confirmation_version"],
            },
            {
                "proposal_sha256": assessment["proposal_sha256"],
                "acknowledged": True,
                "acknowledgement_version": assessment["confirmation_version"] + 1,
            },
        )
        for confirmation in rejected:
            with pytest.raises(ConfigurationSafetyError):
                controller._validate_guard_confirmation(assessment, confirmation)

        assert controller._validate_guard_confirmation(
            assessment,
            {
                "proposal_sha256": assessment["proposal_sha256"],
                "acknowledged": True,
                "acknowledgement_version": assessment["confirmation_version"],
            },
        ) == assessment
    finally:
        context.close()


def test_production_transaction_requires_hash_bound_guard_evidence(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        before = read_governed_documents(context.paths)
        locations = copy.deepcopy(before["Locations.json"])
        locations["camera"]["Y"] += 25
        with pytest.raises(ConfigurationValidationError, match="requires configuration guard evidence"):
            service.commit_documents(
                {"Locations.json": locations},
                operator="Alice",
                reason="test",
                workflow="named_location_modify",
            )

        state = service.refresh(allow_pending=False)
        assessment = context.configuration_safety_guard.assess(
            before_documents=before,
            proposed_documents={"Locations.json": locations},
            workflow="named_location_modify",
            target_keys=("camera",),
            hardware_profile="current",
            preconditions={
                "captures": [
                    _position_capture(
                        "named_location_modify",
                        "camera",
                        locations["camera"],
                        context.identity.machine_uuid,
                    )
                ]
            },
            governed_file_sha256=state.config_sha256,
        )
        result = service.commit_documents(
            {"Locations.json": locations},
            operator="Alice",
            reason="test guarded camera change",
            workflow="named_location_modify",
            expected_config_sha256=state.config_sha256,
            guard_evidence=assessment,
        )
        event = json.loads((context.paths.machine_root / result.state.latest_event_path).read_text(encoding="utf-8"))
        assert event["changes"][-1]["guard_assessment"]["proposal_sha256"] == assessment["proposal_sha256"]
        authorization = result.state.authorization["location:camera"]
        assert authorization["state"] == "operator_verified"
        assert authorization["verification_method"] == "controlled_position_capture"
    finally:
        context.close()


def test_current_generic_location_verification_uses_internal_value_and_checkbox(
    tmp_path,
):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        before = read_governed_documents(context.paths)
        changed = copy.deepcopy(before["Locations.json"])
        changed["camera"]["Y"] += 25
        changed_result = service.commit_documents(
            {"Locations.json": changed},
            operator="Alice",
            reason="simulate previously imported location",
            workflow="test_setup",
        )
        assert (
            changed_result.state.authorization["location:camera"]["state"]
            == "revoked_pending_verification"
        )
        errors = _Signal()
        controller = Controller.__new__(Controller)
        controller.configuration_transactions = service
        controller.configuration_safety_guard = context.configuration_safety_guard
        controller.error_occurred_signal = errors
        controller._configuration_recovery_required = False
        controller.model = SimpleNamespace(
            well_plate=SimpleNamespace(
                get_current_plate_name=lambda: before["Settings.json"][
                    "DEFAULT_PLATE"
                ]
            )
        )
        snapshot = controller.configuration_target_verification_snapshot(
            "location:camera"
        )

        assert snapshot["value"] == changed["camera"]
        assert snapshot["verification_route"] == "location_verification"
        assert controller.verify_current_configuration_target(
            snapshot,
            operator="Alice",
            acknowledged=False,
            acknowledgement_version=1,
        ) is False

        result = controller.verify_current_configuration_target(
            snapshot,
            operator="Alice",
            acknowledged=True,
            acknowledgement_version=1,
        )
        authorization = result.state.authorization["location:camera"]
        assert authorization["state"] == "operator_verified"
        assert authorization["verification_method"] == "physical_check"
        event = json.loads(
            (context.paths.machine_root / result.state.latest_event_path).read_text(
                encoding="utf-8"
            )
        )
        assert event["reason"] == "Operator physically verified the displayed current target."
        assert errors.events[0][0] == "Configuration Verification Failed"
    finally:
        context.close()


def test_current_location_verification_rejects_a_stale_displayed_value(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        before = read_governed_documents(context.paths)
        changed = copy.deepcopy(before["Locations.json"])
        changed["camera"]["Y"] += 25
        service.commit_documents(
            {"Locations.json": changed},
            operator="Alice",
            reason="first imported value",
            workflow="test_setup",
        )
        controller = Controller.__new__(Controller)
        controller.configuration_transactions = service
        controller.configuration_safety_guard = context.configuration_safety_guard
        controller.error_occurred_signal = _Signal()
        controller._configuration_recovery_required = False
        controller.model = SimpleNamespace(
            well_plate=SimpleNamespace(
                get_current_plate_name=lambda: before["Settings.json"][
                    "DEFAULT_PLATE"
                ]
            )
        )
        stale = controller.configuration_target_verification_snapshot(
            "location:camera"
        )
        later = copy.deepcopy(changed)
        later["camera"]["Y"] += 1
        service.commit_documents(
            {"Locations.json": later},
            operator="Alice",
            reason="later imported value",
            workflow="test_setup",
        )

        assert controller.verify_current_configuration_target(
            stale,
            operator="Alice",
            acknowledged=True,
            acknowledgement_version=1,
        ) is False
        assert service.refresh(allow_pending=False).authorization[
            "location:camera"
        ]["state"] == "revoked_pending_verification"
        assert "changed while its verification dialog was open" in (
            controller.error_occurred_signal.events[-1][1]
        )
    finally:
        context.close()


@pytest.mark.parametrize(
    ("target_kind", "expected_route"),
    (("plate", "plate_calibration"), ("rack", "rack_calibration")),
)
def test_calibration_targets_cannot_use_generic_checkbox_verification(
    tmp_path, target_kind, expected_route
):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        before = read_governed_documents(context.paths)
        if target_kind == "plate":
            proposed = copy.deepcopy(before["Plates.json"])
            plate = next(item for item in proposed if item["default"])
            for point in plate["calibrations"].values():
                point["X"] += 10
            service.commit_documents(
                {"Plates.json": proposed},
                operator="Alice",
                reason="simulate pending plate",
                workflow="test_setup",
            )
            target_key = f"plate:{plate['name'].casefold()}"
        else:
            proposed = copy.deepcopy(before["Locations.json"])
            for name in ("rack_position_Left", "rack_position_Right"):
                proposed[name]["X"] += 10
            service.commit_documents(
                {"Locations.json": proposed},
                operator="Alice",
                reason="simulate pending rack",
                workflow="test_setup",
            )
            target_key = "rack:primary"
        controller = Controller.__new__(Controller)
        controller.configuration_transactions = service
        controller.configuration_safety_guard = context.configuration_safety_guard
        controller.error_occurred_signal = _Signal()
        controller._configuration_recovery_required = False
        controller.model = SimpleNamespace(
            well_plate=SimpleNamespace(
                get_current_plate_name=lambda: before["Settings.json"][
                    "DEFAULT_PLATE"
                ]
            )
        )
        snapshot = controller.configuration_target_verification_snapshot(target_key)

        assert snapshot["verification_route"] == expected_route
        assert controller.verify_current_configuration_target(
            snapshot,
            operator="Alice",
            acknowledged=True,
            acknowledgement_version=1,
        ) is False
        assert "must be verified by their calibration workflow" in (
            controller.error_occurred_signal.events[-1][1]
        )
        assert service.refresh(allow_pending=False).authorization[target_key][
            "state"
        ] == "revoked_pending_verification"
    finally:
        context.close()


def test_coordinate_import_and_exact_restore_require_and_preserve_guard_evidence(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        original_bytes = (context.paths.config_root / "Locations.json").read_bytes()
        before = read_governed_documents(context.paths)
        imported = copy.deepcopy(before["Locations.json"])
        imported["camera"]["Y"] += 40
        imported["qualification-unverified"] = copy.deepcopy(imported["camera"])
        state = service.refresh(allow_pending=False)
        import_assessment = context.configuration_safety_guard.assess(
            before_documents=before,
            proposed_documents={"Locations.json": imported},
            workflow="governed_configuration_import",
            target_keys=("Locations.json",),
            hardware_profile="current",
            governed_file_sha256=state.config_sha256,
        )
        imported_result = service.commit_documents(
            {"Locations.json": imported},
            operator="Alice",
            reason="reviewed coordinate import",
            workflow="governed_configuration_import",
            event_type="import",
            expected_config_sha256=state.config_sha256,
            guard_evidence=import_assessment,
        )

        controller = Controller.__new__(Controller)
        controller.configuration_transactions = service
        controller.configuration_safety_guard = context.configuration_safety_guard
        controller.profile = SimpleNamespace(name="current")
        controller.error_occurred_signal = _Signal()
        controller._configuration_capture_evidence = {}
        controller._install_committed_configuration = lambda result: True
        restore_proposal = controller.prepare_configuration_restore(
            imported_result.transaction_id,
            machine_id_confirmation=context.identity.machine_id,
        )
        restore_assessment = restore_proposal["assessment"]
        restore_precondition = restore_assessment["preconditions"]["restore"]
        removed = next(
            change
            for change in restore_assessment["changes"]
            if change["target_key"] == "qualification-unverified"
        )
        assert removed["proposed"] is None
        assert restore_assessment["result"] == "strong_confirmation"
        restored = controller.commit_guarded_configuration_proposal(
            restore_proposal,
            operator="Alice",
            reason="exact guarded restore",
            confirmation={
                "proposal_sha256": restore_assessment["proposal_sha256"],
                "acknowledged": True,
                "acknowledgement_version": restore_assessment["confirmation_version"],
            },
        )

        assert (context.paths.config_root / "Locations.json").read_bytes() == original_bytes
        restore_event = json.loads(
            (context.paths.machine_root / restored.state.latest_event_path).read_text(encoding="utf-8")
        )
        assert restore_event["workflow"] == "configuration_restore"
        assert restore_event["changes"][-1]["guard_assessment"]["result"] == "strong_confirmation"
        assert (
            restore_event["changes"][-1]["guard_assessment"]["preconditions"]["restore"]
            == restore_precondition
        )
    finally:
        context.close()


def test_import_deletion_remains_rejected_and_restore_requires_bound_backup(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        before = read_governed_documents(context.paths)
        deleting_import = copy.deepcopy(before["Locations.json"])
        deleting_import.pop("camera")
        state = service.refresh(allow_pending=False)

        import_assessment = context.configuration_safety_guard.assess(
            before_documents=before,
            proposed_documents={"Locations.json": deleting_import},
            workflow="governed_configuration_import",
            target_keys=("Locations.json",),
            hardware_profile="current",
            governed_file_sha256=state.config_sha256,
        )
        assert import_assessment["result"] == "reject"
        assert "Coordinate import cannot remove saved locations: camera" in next(
            check["message"]
            for check in import_assessment["hard_checks"]
            if check["passed"] is False
        )

        missing_evidence = context.configuration_safety_guard.assess(
            before_documents=before,
            proposed_documents={"Locations.json": deleting_import},
            workflow="configuration_restore",
            target_keys=("Locations.json",),
            hardware_profile="current",
            governed_file_sha256=state.config_sha256,
        )
        assert missing_evidence["result"] == "reject"
        assert "lacks verified backup evidence" in next(
            check["message"]
            for check in missing_evidence["hard_checks"]
            if check["passed"] is False
        )
    finally:
        context.close()


def test_exact_restore_can_remove_plate_calibration_added_by_source_transaction(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        plates_path = context.paths.config_root / "Plates.json"
        original_bytes = plates_path.read_bytes()
        before = read_governed_documents(context.paths)
        imported_plates = copy.deepcopy(before["Plates.json"])
        calibrated = next(plate for plate in imported_plates if plate.get("calibrations"))
        added_plate = copy.deepcopy(calibrated)
        added_plate["name"] = "qualification-plate"
        added_plate["default"] = False
        imported_plates.append(added_plate)
        state = service.refresh(allow_pending=False)
        import_assessment = context.configuration_safety_guard.assess(
            before_documents=before,
            proposed_documents={"Plates.json": imported_plates},
            workflow="governed_configuration_import",
            target_keys=("Plates.json",),
            hardware_profile="current",
            governed_file_sha256=state.config_sha256,
        )
        added = service.commit_documents(
            {"Plates.json": imported_plates},
            operator="Alice",
            reason="add disposable plate calibration",
            workflow="governed_configuration_import",
            event_type="import",
            expected_config_sha256=state.config_sha256,
            guard_evidence=import_assessment,
        )

        proposal, restore_precondition = service.read_restore_preview(
            added.transaction_id
        )
        restore_state = service.refresh(allow_pending=False)
        assessment = context.configuration_safety_guard.assess(
            before_documents=read_governed_documents(context.paths),
            proposed_documents=proposal,
            workflow="configuration_restore",
            target_keys=("Plates.json",),
            hardware_profile="current",
            preconditions={"captures": [], "restore": restore_precondition},
            governed_file_sha256=restore_state.config_sha256,
        )
        removals = [change for change in assessment["changes"] if change["proposed"] is None]
        assert {change["target_key"] for change in removals} == {
            "top_left",
            "top_right",
            "bottom_right",
            "bottom_left",
        }
        assert assessment["result"] == "strong_confirmation"

        restored = service.restore_transaction(
            added.transaction_id,
            operator="Alice",
            reason="restore exact pre-plate bytes",
            machine_id_confirmation=context.identity.machine_id,
            expected_config_sha256=restore_state.config_sha256,
            guard_evidence=assessment,
        )
        assert plates_path.read_bytes() == original_bytes
        assert "plate:qualification-plate" not in restored.state.authorization
        assert not list(context.paths.pending_transactions_root.glob("*"))
    finally:
        context.close()


def test_restore_commit_rejects_preview_bound_to_different_manifest(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        original = read_governed_documents(context.paths)
        changed = copy.deepcopy(original["Locations.json"])
        changed["camera"]["Y"] += 40
        state = service.refresh(allow_pending=False)
        change_assessment = context.configuration_safety_guard.assess(
            before_documents=original,
            proposed_documents={"Locations.json": changed},
            workflow="governed_configuration_import",
            target_keys=("Locations.json",),
            hardware_profile="current",
            governed_file_sha256=state.config_sha256,
        )
        changed_result = service.commit_documents(
            {"Locations.json": changed},
            operator="Alice",
            reason="create restore source",
            workflow="governed_configuration_import",
            event_type="import",
            expected_config_sha256=state.config_sha256,
            guard_evidence=change_assessment,
        )
        proposed, restore_precondition = service.read_restore_preview(
            changed_result.transaction_id
        )
        forged_precondition = copy.deepcopy(restore_precondition)
        forged_precondition["backup_manifest"]["raw_sha256"] = "0" * 64
        restore_state = service.refresh(allow_pending=False)
        forged_assessment = context.configuration_safety_guard.assess(
            before_documents=read_governed_documents(context.paths),
            proposed_documents=proposed,
            workflow="configuration_restore",
            target_keys=("Locations.json",),
            hardware_profile="current",
            preconditions={"captures": [], "restore": forged_precondition},
            governed_file_sha256=restore_state.config_sha256,
        )
        assert forged_assessment["result"] == "strong_confirmation"

        with pytest.raises(
            ConfigurationConflictError,
            match="selected backup differs from the verified restore preview",
        ):
            service.restore_transaction(
                changed_result.transaction_id,
                operator="Alice",
                reason="must reject forged manifest binding",
                machine_id_confirmation=context.identity.machine_id,
                expected_config_sha256=restore_state.config_sha256,
                guard_evidence=forged_assessment,
            )
        assert service.refresh(allow_pending=False).sequence == 1
    finally:
        context.close()


def test_restore_commit_reopens_and_rejects_tampered_backup_after_preview(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        service.require_configuration_guard_evidence = True
        before = read_governed_documents(context.paths)
        changed = copy.deepcopy(before["Locations.json"])
        changed["camera"]["Y"] += 41
        state = service.refresh(allow_pending=False)
        change_assessment = context.configuration_safety_guard.assess(
            before_documents=before,
            proposed_documents={"Locations.json": changed},
            workflow="governed_configuration_import",
            target_keys=("Locations.json",),
            hardware_profile="current",
            governed_file_sha256=state.config_sha256,
        )
        changed_result = service.commit_documents(
            {"Locations.json": changed},
            operator="Alice",
            reason="create tamper restore source",
            workflow="governed_configuration_import",
            event_type="import",
            expected_config_sha256=state.config_sha256,
            guard_evidence=change_assessment,
        )
        proposed, restore_precondition = service.read_restore_preview(
            changed_result.transaction_id
        )
        restore_state = service.refresh(allow_pending=False)
        restore_assessment = context.configuration_safety_guard.assess(
            before_documents=read_governed_documents(context.paths),
            proposed_documents=proposed,
            workflow="configuration_restore",
            target_keys=("Locations.json",),
            hardware_profile="current",
            preconditions={"captures": [], "restore": restore_precondition},
            governed_file_sha256=restore_state.config_sha256,
        )
        current_bytes = (context.paths.config_root / "Locations.json").read_bytes()
        manifest_path = (
            context.paths.configuration_backups_root
            / changed_result.transaction_id
            / "manifest.json"
        )
        manifest_path.write_bytes(manifest_path.read_bytes() + b" ")

        with pytest.raises(ConfigurationRecoveryRequired, match="hash differs from event"):
            service.restore_transaction(
                changed_result.transaction_id,
                operator="Alice",
                reason="must reject backup changed after preview",
                machine_id_confirmation=context.identity.machine_id,
                expected_config_sha256=restore_state.config_sha256,
                guard_evidence=restore_assessment,
            )
        assert (context.paths.config_root / "Locations.json").read_bytes() == current_bytes
    finally:
        context.close()


def test_override_cannot_bypass_global_endpoint_bounds():
    from ConfigurationSafetyPolicy import ConfigurationChangeGuard, load_configuration_change_policy, parse_safety_bounds

    controller = Controller.__new__(Controller)
    controller.expected_position = {"X": 500, "Y": 500, "Z": 500}
    controller.configuration_safety_guard = ConfigurationChangeGuard(
        load_configuration_change_policy(),
        parse_safety_bounds({
            "boundaries": {"min": {"X": 0, "Y": 0, "Z": 0}, "max": {"X": 1000, "Y": 1000, "Z": 1000}},
            "obstacles": [],
        }),
    )
    controller.machine = _Machine()
    controller.error_occurred_signal = _Signal()

    assert Controller.set_absolute_XY(controller, 1001, 500, override=True) is False
    assert controller.machine.calls == []
    assert controller.expected_position == {"X": 500, "Y": 500, "Z": 500}
    assert controller.error_occurred_signal.events[0][0] == "Motion Endpoint Rejected"


def test_production_controller_capture_preview_commit_and_trust_epoch_recheck(qapp, tmp_path):
    import ApplicationComposition as composition
    from hardware.profile import CURRENT_PROFILE
    from tests.test_safe_application_construction import _safe_machine_factory

    _base, context = _active_context(tmp_path)
    context.configuration_transactions.require_configuration_guard_evidence = True
    dependencies = replace(
        composition.production_dependencies(context),
        machine_factory=_safe_machine_factory,
    )
    components = composition.build_application_components(CURRENT_PROFILE, dependencies)
    try:
        controller = components.controller
        # Intentional rejection below must not open the real modal MainWindow
        # error dialog in this headless integration test.
        controller.error_occurred_signal.disconnect()
        errors = []
        controller.error_occurred_signal.connect(
            lambda title, message: errors.append((title, message))
        )
        machine_model = components.model.machine_model
        camera = components.model.location_model.get_location_dict("camera")
        captured = {"X": camera["X"], "Y": camera["Y"] + 250, "Z": camera["Z"]}

        machine_model.connect_machine()
        machine_model.motors_enabled = True
        machine_model.handle_home_complete()
        machine_model.update_reported_position(captured)
        controller.update_expected_with_current()

        proposal = controller.prepare_named_location_change("camera", require_existing=True)
        assessment = proposal["assessment"]
        assert assessment["result"] == "strong_confirmation"
        assert assessment["changes"][0]["signed_delta"]["Y"] == 250

        confirmation = {
            "proposal_sha256": assessment["proposal_sha256"],
            "acknowledged": True,
            "acknowledgement_version": assessment["confirmation_version"],
        }
        machine_model.reset_home_status()
        assert controller.commit_guarded_configuration_proposal(
            proposal,
            operator="Alice",
            reason="Camera calibration test",
            confirmation=confirmation,
        ) is False
        assert context.configuration_transactions.refresh(allow_pending=False).sequence == 0

        machine_model.motors_enabled = True
        machine_model.handle_home_complete()
        machine_model.update_reported_position(captured)
        controller.update_expected_with_current()
        proposal = controller.prepare_named_location_change("camera", require_existing=True)
        assessment = proposal["assessment"]
        confirmation.update(
            proposal_sha256=assessment["proposal_sha256"],
            acknowledgement_version=assessment["confirmation_version"],
        )
        result = controller.commit_guarded_configuration_proposal(
            proposal,
            operator="Alice",
            reason="Camera calibration test",
            confirmation=confirmation,
        )
        assert result is not False, errors
        assert result.state.authorization["location:camera"]["state"] == "operator_verified"
        assert (
            result.state.authorization["location:camera"]["verification_method"]
            == "controlled_position_capture"
        )
        assert components.model.location_model.get_location_dict("camera") == captured
    finally:
        assert components.close() is True
