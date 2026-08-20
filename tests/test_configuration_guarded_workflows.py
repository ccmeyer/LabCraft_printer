import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from Controller import Controller
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
        assert result.state.authorization["location:camera"]["state"] == "revoked_pending_verification"
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
                "typed_phrase": restore_assessment["required_confirmation_phrase"],
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
        machine_model = components.model.machine_model
        camera = components.model.location_model.get_location_dict("camera")
        captured = {"X": camera["X"], "Y": camera["Y"] + 250, "Z": camera["Z"]}

        machine_model.connect_machine()
        machine_model.motors_enabled = True
        machine_model.handle_home_complete()
        machine_model.update_reported_position(captured)
        controller.expected_position = copy.deepcopy(captured)

        proposal = controller.prepare_named_location_change("camera", require_existing=True)
        assessment = proposal["assessment"]
        assert assessment["result"] == "strong_confirmation"
        assert assessment["changes"][0]["signed_delta"]["Y"] == 250

        confirmation = {
            "proposal_sha256": assessment["proposal_sha256"],
            "acknowledged": True,
            "typed_phrase": assessment["required_confirmation_phrase"],
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
        controller.expected_position = copy.deepcopy(captured)
        proposal = controller.prepare_named_location_change("camera", require_existing=True)
        assessment = proposal["assessment"]
        confirmation.update(
            proposal_sha256=assessment["proposal_sha256"],
            typed_phrase=assessment["required_confirmation_phrase"],
        )
        result = controller.commit_guarded_configuration_proposal(
            proposal,
            operator="Alice",
            reason="Camera calibration test",
            confirmation=confirmation,
        )
        assert result.state.authorization["location:camera"]["state"] == "revoked_pending_verification"
        assert components.model.location_model.get_location_dict("camera") == captured
    finally:
        assert components.close() is True
