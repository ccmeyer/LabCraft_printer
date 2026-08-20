import copy
import json

import pytest

import MachineDataBootstrap
import MachineDataMigration
from MachineDataArchive import DurableFileOps
from MachineDataTransactions import (
    ConfigurationRecoveryRequired,
    ConfigurationTransactionError,
    ConfigurationValidationError,
)
from MachineDataVerification import SavedTargetAuthorizationRequest, build_target_snapshot
from tests.machine_data_migration_helpers import (
    FIXED_TIME,
    MACHINE_ID,
    MACHINE_UUID,
    MIGRATION_ID,
    inspect_wrapper,
    machine_data_paths,
    migration_policy,
    write_wrapper,
)


ACTIVATION_ID = "00000000-0000-0000-0000-000000000003"


def _bootstrap(base, *, uuid_values=()):
    values = iter(uuid_values)
    return MachineDataBootstrap.MachineDataBootstrap(
        base,
        app_version="v1.3.0-rc.2",
        app_commit="transaction-test",
        migration_policy=migration_policy(),
        clock=lambda: FIXED_TIME,
        uuid_factory=lambda: next(values),
    )


def _active_context(tmp_path):
    wrapper, _local = write_wrapper(
        tmp_path / "source", cohort="v1.3.0-rc.1", custom_camera=True
    )
    candidate = inspect_wrapper(wrapper)
    base, _paths = machine_data_paths(tmp_path)
    context = _bootstrap(base, uuid_values=(MIGRATION_ID,)).bootstrap_from_candidate(
        MachineDataBootstrap.BootstrapSubmission(
            selection=MachineDataMigration.CandidateSelection(
                MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_WRAPPER,
                wrapper,
                "transaction test source",
            ),
            machine_id=MACHINE_ID,
            machine_uuid=MACHINE_UUID,
            activation_id=ACTIVATION_ID,
            operator="Test Operator",
            source_reason="Preserved source",
            camera_confirmation=candidate.safety_snapshot["locations"]["camera"],
        )
    )
    return base, context


def _location_request(context, name, value):
    return SavedTargetAuthorizationRequest(
        machine_uuid=context.paths.machine_uuid,
        target_key=f"location:{name.casefold()}",
        target_kind="location",
        base_value=value,
        final_coordinates=value,
        workflow="test",
        offsets={},
    )


def test_untouched_m3_store_does_not_create_history(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        assert context.configuration_state.has_history is False
        assert not context.paths.configuration_head_path.exists()
        assert not context.paths.configuration_events_root.exists()
    finally:
        context.close()


def test_named_location_transaction_backs_up_audits_and_revokes_only_change(tmp_path):
    base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        before = json.loads((context.paths.config_root / "Locations.json").read_text(encoding="utf-8"))
        camera_before = copy.deepcopy(before["camera"])
        unchanged_name = next(name for name in before if name.casefold() != "camera")
        unchanged_value = copy.deepcopy(before[unchanged_name])
        proposed = copy.deepcopy(before)
        proposed["camera"]["Y"] += 1234

        result = service.commit_documents(
            {"Locations.json": proposed},
            operator="Alice",
            reason="Camera physically recalibrated",
            workflow="named_location_modify",
        )

        assert result.status == "committed"
        assert result.state.sequence == 1
        assert context.paths.configuration_head_path.is_file()
        assert len(list(context.paths.configuration_events_root.glob("*.json"))) == 1
        manifest = context.paths.configuration_backups_root / result.transaction_id / "manifest.json"
        assert manifest.is_file()
        backup = manifest.parent / "before" / "config" / "Locations.json"
        assert backup.read_bytes() != (context.paths.config_root / "Locations.json").read_bytes()
        assert json.loads(backup.read_text(encoding="utf-8"))["camera"] == camera_before

        denied = service.saved_target_authorizer.authorize(
            _location_request(context, "camera", proposed["camera"])
        )
        allowed = service.saved_target_authorizer.authorize(
            _location_request(context, unchanged_name, unchanged_value)
        )
        assert denied.allowed is False
        assert denied.reason_code == "target_revoked"
        assert allowed.allowed is True
    finally:
        context.close()

    reopened = _bootstrap(base).open_ready()
    try:
        assert reopened.configuration_state.sequence == 1
        assert reopened.saved_target_authorizer.authorize(
            _location_request(reopened, "camera", proposed["camera"])
        ).allowed is False
    finally:
        reopened.close()


def test_exact_verification_and_restore_are_new_events(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        locations_path = context.paths.config_root / "Locations.json"
        before_bytes = locations_path.read_bytes()
        locations = json.loads(before_bytes.decode("utf-8"))
        before_camera = copy.deepcopy(locations["camera"])
        locations["camera"]["Y"] += 10
        changed = service.commit_documents(
            {"Locations.json": locations},
            operator="Alice",
            reason="Test change",
            workflow="named_location_modify",
        )
        verified = service.verify_targets(
            {"location:camera": locations["camera"]},
            operator="Bob",
            reason="Physically checked exact Camera coordinates",
        )
        assert verified.state.authorization["location:camera"]["state"] == "operator_verified"
        assert service.saved_target_authorizer.authorize(
            _location_request(context, "camera", locations["camera"])
        ).allowed is True

        restored = service.restore_transaction(
            changed.transaction_id,
            operator="Support",
            reason="Restore prior Camera calibration",
            machine_id_confirmation=MACHINE_ID,
        )
        current = json.loads(locations_path.read_text(encoding="utf-8"))
        assert current["camera"] == before_camera
        assert locations_path.read_bytes() == before_bytes
        assert restored.state.sequence == 3
        assert restored.state.authorization["location:camera"]["state"] == "revoked_pending_verification"
    finally:
        context.close()


def test_restore_records_raw_only_change_and_reinstates_noncanonical_bytes(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        locations_path = context.paths.config_root / "Locations.json"
        original_bytes = locations_path.read_bytes()
        original = json.loads(original_bytes.decode("utf-8"))

        changed_locations = copy.deepcopy(original)
        changed_locations["camera"]["Y"] += 11
        first_change = service.commit_documents(
            {"Locations.json": changed_locations},
            operator="Alice",
            reason="Create exact restore source",
            workflow="named_location_modify",
        )

        canonical_return = service.commit_documents(
            {"Locations.json": original},
            operator="Alice",
            reason="Return values through normal canonical serialization",
            workflow="named_location_modify",
        )
        assert canonical_return.state.sequence == 2
        assert json.loads(locations_path.read_text(encoding="utf-8")) == original
        assert locations_path.read_bytes() != original_bytes

        restored = service.restore_transaction(
            first_change.transaction_id,
            operator="Support",
            reason="Restore exact historical representation",
            machine_id_confirmation=MACHINE_ID,
        )

        assert restored.state.sequence == 3
        assert restored.changed_targets == ()
        assert locations_path.read_bytes() == original_bytes
        event = json.loads(
            next(
                context.paths.configuration_events_root.glob(
                    f"{restored.state.sequence:020d}-*.json"
                )
            ).read_text(encoding="utf-8")
        )
        assert event["event_type"] == "restore"
        assert event["restore_reference"] == first_change.transaction_id
        assert (
            event["config_before_sha256"]["Locations.json"]
            != event["config_after_sha256"]["Locations.json"]
        )
    finally:
        context.close()


def test_raw_only_settings_restore_does_not_create_false_target_changes(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        settings_path = context.paths.config_root / "Settings.json"
        original_bytes = settings_path.read_bytes()
        original = json.loads(original_bytes.decode("utf-8"))

        changed_settings = copy.deepcopy(original)
        changed_settings["SAFE_Z"] = int(changed_settings.get("SAFE_Z", 0)) + 1
        first_change = service.commit_documents(
            {"Settings.json": changed_settings},
            operator="Alice",
            reason="Create exact Settings restore source",
            workflow="settings_change",
        )
        service.commit_documents(
            {"Settings.json": original},
            operator="Alice",
            reason="Return Settings values canonically",
            workflow="settings_change",
        )
        authorization_before_restore = {
            key: copy.deepcopy(dict(value))
            for key, value in service.state.authorization.items()
        }
        assert settings_path.read_bytes() != original_bytes

        restored = service.restore_transaction(
            first_change.transaction_id,
            operator="Support",
            reason="Restore exact Settings representation",
            machine_id_confirmation=MACHINE_ID,
        )

        assert restored.changed_targets == ()
        assert {
            key: dict(value) for key, value in restored.state.authorization.items()
        } == authorization_before_restore
        assert settings_path.read_bytes() == original_bytes
    finally:
        context.close()


def test_multi_file_restore_reinstates_every_exact_backup_member(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        locations_path = context.paths.config_root / "Locations.json"
        settings_path = context.paths.config_root / "Settings.json"
        original_locations = locations_path.read_bytes()
        original_settings = settings_path.read_bytes()
        locations = json.loads(original_locations.decode("utf-8"))
        settings = json.loads(original_settings.decode("utf-8"))
        locations["camera"]["Y"] += 13
        settings["SAFE_Z"] = int(settings.get("SAFE_Z", 0)) + 1

        changed = service.commit_documents(
            {"Locations.json": locations, "Settings.json": settings},
            operator="Alice",
            reason="Create multi-file restore source",
            workflow="governed_configuration_import",
        )
        restored = service.restore_transaction(
            changed.transaction_id,
            operator="Support",
            reason="Restore both exact historical files",
            machine_id_confirmation=MACHINE_ID,
        )

        assert restored.state.sequence == 2
        assert set(restored.documents) == {"Locations.json", "Settings.json"}
        assert locations_path.read_bytes() == original_locations
        assert settings_path.read_bytes() == original_settings
    finally:
        context.close()


@pytest.mark.parametrize(
    ("checkpoint", "restore_completes"),
    [
        ("after_configuration_locations_fsync", False),
        ("after_configuration_locations_replace", True),
        ("after_configuration_event_fsync", True),
        ("after_configuration_head_replace", True),
    ],
)
def test_interrupted_exact_restore_reconciles_exact_bytes(
    tmp_path, checkpoint, restore_completes
):
    base, context = _active_context(tmp_path)
    locations_path = context.paths.config_root / "Locations.json"
    original_bytes = locations_path.read_bytes()
    changed_locations = json.loads(original_bytes.decode("utf-8"))
    changed_locations["camera"]["Y"] += 12
    changed = context.configuration_transactions.commit_documents(
        {"Locations.json": changed_locations},
        operator="Alice",
        reason="Create interrupted exact restore source",
        workflow="named_location_modify",
    )
    pre_restore_bytes = locations_path.read_bytes()
    observed_replacement = []

    def fault(name, path):
        if name == checkpoint:
            if name == "after_configuration_locations_replace":
                observed_replacement.append(path.read_bytes())
            raise RuntimeError(f"fault at {checkpoint}")

    context.configuration_transactions.io = DurableFileOps(fault_hook=fault)
    with pytest.raises(ConfigurationRecoveryRequired):
        context.configuration_transactions.restore_transaction(
            changed.transaction_id,
            operator="Support",
            reason="Interrupted exact restore",
            machine_id_confirmation=MACHINE_ID,
        )
    if observed_replacement:
        assert observed_replacement == [original_bytes]
    context.close()

    recovered = _bootstrap(base).open_ready()
    try:
        assert recovered.configuration_state.sequence == 2
        current_bytes = locations_path.read_bytes()
        assert current_bytes == (
            original_bytes if restore_completes else pre_restore_bytes
        )
        event = json.loads(
            next(
                recovered.paths.configuration_events_root.glob(
                    f"{recovered.configuration_state.sequence:020d}-*.json"
                )
            ).read_text(encoding="utf-8")
        )
        assert event["event_type"] == (
            "restore" if restore_completes else "recovery"
        )
        assert not list(recovered.paths.pending_transactions_root.glob("*"))
    finally:
        recovered.close()


def test_cancelled_attempt_changes_no_config_bytes(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        before = (context.paths.config_root / "Locations.json").read_bytes()
        result = context.configuration_transactions.record_attempt(
            event_type="cancelled",
            operator="Alice",
            reason="Operator cancelled before save",
            workflow="named_location_add",
            details={"stage": "confirmation"},
        )
        assert result.state.sequence == 1
        assert (context.paths.config_root / "Locations.json").read_bytes() == before
        assert not context.paths.configuration_backups_root.exists()
    finally:
        context.close()


def test_invalid_or_noop_proposal_does_not_create_history(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        locations = json.loads((context.paths.config_root / "Locations.json").read_text(encoding="utf-8"))
        with pytest.raises(ConfigurationValidationError, match="unchanged"):
            context.configuration_transactions.commit_documents(
                {"Locations.json": locations},
                operator="Alice",
                reason="No change",
                workflow="test",
            )
        assert not context.paths.configuration_head_path.exists()
    finally:
        context.close()


def test_untracked_config_edit_without_history_fails_closed(tmp_path):
    base, context = _active_context(tmp_path)
    path = context.paths.config_root / "Locations.json"
    context.close()
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["camera"]["Y"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert _bootstrap(base).inspect().state is MachineDataBootstrap.BootstrapState.RECOVERY_REQUIRED
    with pytest.raises(MachineDataBootstrap.BootstrapError):
        _bootstrap(base).open_ready()


def test_event_write_failure_restores_then_startup_records_recovery(tmp_path):
    base, context = _active_context(tmp_path)
    locations_path = context.paths.config_root / "Locations.json"
    before = locations_path.read_bytes()
    locations = json.loads(before.decode("utf-8"))
    locations["camera"]["Y"] += 99
    fired = False

    def fault(name, _path):
        nonlocal fired
        if name == "before_configuration_event_create" and not fired:
            fired = True
            raise RuntimeError("event storage unavailable")

    context.configuration_transactions.io = DurableFileOps(fault_hook=fault)
    with pytest.raises(ConfigurationRecoveryRequired):
        context.configuration_transactions.commit_documents(
            {"Locations.json": locations},
            operator="Alice",
            reason="Fault test",
            workflow="named_location_modify",
        )
    assert locations_path.read_bytes() == before
    context.close()

    assert _bootstrap(base).inspect().state is MachineDataBootstrap.BootstrapState.READY
    recovered = _bootstrap(base).open_ready()
    try:
        assert recovered.configuration_state.sequence == 1
        event_path = next(recovered.paths.configuration_events_root.glob("*.json"))
        event = json.loads(event_path.read_text(encoding="utf-8"))
        assert event["event_type"] == "recovery"
        assert event["outcome"] == "recovered_abort"
        assert locations_path.read_bytes() == before
        assert not any(recovered.paths.pending_transactions_root.iterdir())
    finally:
        recovered.close()


def test_all_after_interruption_finalizes_planned_commit_on_startup(tmp_path):
    base, context = _active_context(tmp_path)
    locations_path = context.paths.config_root / "Locations.json"
    locations = json.loads(locations_path.read_text(encoding="utf-8"))
    locations["camera"]["Y"] += 101

    def fault(name, _path):
        if name in {
            "before_configuration_event_create",
            "before_configuration_live_rollback_write",
        }:
            raise RuntimeError("simulated power loss")

    context.configuration_transactions.io = DurableFileOps(fault_hook=fault)
    with pytest.raises(ConfigurationRecoveryRequired):
        context.configuration_transactions.commit_documents(
            {"Locations.json": locations},
            operator="Alice",
            reason="Power-loss test",
            workflow="named_location_modify",
        )
    assert json.loads(locations_path.read_text(encoding="utf-8"))["camera"] == locations["camera"]
    context.close()

    recovered = _bootstrap(base).open_ready()
    try:
        assert recovered.configuration_state.sequence == 1
        event_path = next(recovered.paths.configuration_events_root.glob("*.json"))
        event = json.loads(event_path.read_text(encoding="utf-8"))
        assert event["event_type"] == "change"
        assert event["outcome"] == "committed"
        assert recovered.configuration_state.authorization["location:camera"]["state"] == "revoked_pending_verification"
    finally:
        recovered.close()


def test_event_written_head_failure_keeps_after_state_and_advances_head_on_startup(tmp_path):
    base, context = _active_context(tmp_path)
    locations_path = context.paths.config_root / "Locations.json"
    locations = json.loads(locations_path.read_text(encoding="utf-8"))
    locations["camera"]["Y"] += 202

    def fault(name, _path):
        if name == "before_configuration_head_write":
            raise RuntimeError("head storage unavailable")

    context.configuration_transactions.io = DurableFileOps(fault_hook=fault)
    with pytest.raises(ConfigurationRecoveryRequired):
        context.configuration_transactions.commit_documents(
            {"Locations.json": locations},
            operator="Alice",
            reason="Head failure test",
            workflow="named_location_modify",
        )
    assert json.loads(locations_path.read_text(encoding="utf-8"))["camera"] == locations["camera"]
    assert len(list(context.paths.configuration_events_root.glob("*.json"))) == 1
    context.close()

    recovered = _bootstrap(base).open_ready()
    try:
        assert recovered.configuration_state.sequence == 1
        assert recovered.paths.configuration_head_path.is_file()
        assert json.loads(locations_path.read_text(encoding="utf-8"))["camera"] == locations["camera"]
    finally:
        recovered.close()


@pytest.mark.parametrize(
    "checkpoint",
    [
        "before_configuration_backup_member_write",
        "after_configuration_backup_member_fsync",
        "after_configuration_backup_member_replace",
        "before_configuration_backup_manifest_write",
        "after_configuration_backup_manifest_fsync",
        "after_configuration_backup_manifest_replace",
        "before_configuration_proposed_write",
        "after_configuration_proposed_fsync",
        "after_configuration_proposed_replace",
        "before_configuration_journal_write",
        "after_configuration_journal_fsync",
        "after_configuration_journal_replace",
    ],
)
def test_precommit_preparation_failure_cleans_artifacts_and_changes_nothing(tmp_path, checkpoint):
    _base, context = _active_context(tmp_path)
    locations_path = context.paths.config_root / "Locations.json"
    before = locations_path.read_bytes()
    locations = json.loads(before.decode("utf-8"))
    locations["camera"]["Y"] += 303

    def fault(name, _path):
        if name == checkpoint:
            raise RuntimeError("pre-commit storage unavailable")

    context.configuration_transactions.io = DurableFileOps(fault_hook=fault)
    try:
        with pytest.raises(ConfigurationTransactionError, match="not changed"):
            context.configuration_transactions.commit_documents(
                {"Locations.json": locations},
                operator="Alice",
                reason="Preparation failure test",
                workflow="named_location_modify",
            )
        assert locations_path.read_bytes() == before
        assert not list(context.paths.configuration_events_root.glob("*.json"))
        assert not list(context.paths.configuration_backups_root.glob("*"))
        assert not list(context.paths.pending_transactions_root.glob("*"))
    finally:
        context.close()


def test_unreferenced_backup_file_fails_exact_inventory(tmp_path):
    base, context = _active_context(tmp_path)
    locations = json.loads(
        (context.paths.config_root / "Locations.json").read_text(encoding="utf-8")
    )
    locations["camera"]["Y"] += 404
    context.configuration_transactions.commit_documents(
        {"Locations.json": locations},
        operator="Alice",
        reason="Create referenced backup",
        workflow="named_location_modify",
    )
    rogue = context.paths.configuration_backups_root / "rogue.txt"
    rogue.write_text("not referenced", encoding="utf-8")
    context.close()

    assert _bootstrap(base).inspect().state is MachineDataBootstrap.BootstrapState.RECOVERY_REQUIRED
    with pytest.raises(MachineDataBootstrap.BootstrapError):
        _bootstrap(base).open_ready()


@pytest.mark.parametrize(
    "checkpoint",
    [
        "before_configuration_locations_write",
        "after_configuration_locations_fsync",
        "after_configuration_locations_replace",
        "before_configuration_event_create",
        "after_configuration_event_fsync",
        "before_configuration_head_write",
        "after_configuration_head_fsync",
        "after_configuration_head_replace",
    ],
)
def test_every_post_intent_fault_reconciles_to_one_exact_event(tmp_path, checkpoint):
    base, context = _active_context(tmp_path)
    locations = json.loads(
        (context.paths.config_root / "Locations.json").read_text(encoding="utf-8")
    )
    locations["camera"]["Y"] += 707
    fired = False

    def fault(name, _path):
        nonlocal fired
        if name == checkpoint and not fired:
            fired = True
            raise RuntimeError(f"fault at {checkpoint}")

    context.configuration_transactions.io = DurableFileOps(fault_hook=fault)
    with pytest.raises(ConfigurationRecoveryRequired):
        context.configuration_transactions.commit_documents(
            {"Locations.json": locations},
            operator="Alice",
            reason="Post-intent fault matrix",
            workflow="named_location_modify",
        )
    context.close()

    recovered = _bootstrap(base).open_ready()
    try:
        assert recovered.configuration_state.sequence == 1
        assert len(list(recovered.paths.configuration_events_root.glob("*.json"))) == 1
        assert not list(recovered.paths.pending_transactions_root.glob("*"))
        current = json.loads(
            (recovered.paths.config_root / "Locations.json").read_text(encoding="utf-8")
        )
        event = json.loads(
            next(recovered.paths.configuration_events_root.glob("*.json")).read_text(
                encoding="utf-8"
            )
        )
        if event["event_type"] == "change":
            assert current == locations
        else:
            assert event["event_type"] == "recovery"
            assert current != locations
    finally:
        recovered.close()


@pytest.mark.parametrize(
    "checkpoint", ["after_configuration_head_fsync", "after_configuration_head_replace"]
)
def test_second_event_with_stale_or_advanced_head_reconciles(tmp_path, checkpoint):
    base, context = _active_context(tmp_path)
    locations = json.loads(
        (context.paths.config_root / "Locations.json").read_text(encoding="utf-8")
    )
    locations["camera"]["Y"] += 1
    context.configuration_transactions.commit_documents(
        {"Locations.json": locations},
        operator="Alice",
        reason="First complete event",
        workflow="named_location_modify",
    )
    locations["camera"]["Y"] += 1

    def fault(name, _path):
        if name == checkpoint:
            raise RuntimeError("second-head interruption")

    context.configuration_transactions.io = DurableFileOps(fault_hook=fault)
    with pytest.raises(ConfigurationRecoveryRequired):
        context.configuration_transactions.commit_documents(
            {"Locations.json": locations},
            operator="Alice",
            reason="Second interrupted event",
            workflow="named_location_modify",
        )
    context.close()

    recovered = _bootstrap(base).open_ready()
    try:
        assert recovered.configuration_state.sequence == 2
        assert json.loads(
            (recovered.paths.config_root / "Locations.json").read_text(encoding="utf-8")
        ) == locations
        assert not list(recovered.paths.pending_transactions_root.glob("*"))
    finally:
        recovered.close()


def test_partial_multi_file_replace_restores_every_document_before_model_start(tmp_path):
    base, context = _active_context(tmp_path)
    locations_path = context.paths.config_root / "Locations.json"
    settings_path = context.paths.config_root / "Settings.json"
    before_locations = locations_path.read_bytes()
    before_settings = settings_path.read_bytes()
    locations = json.loads(before_locations.decode("utf-8"))
    settings = json.loads(before_settings.decode("utf-8"))
    locations["camera"]["Y"] += 808
    settings["SAFE_Z"] = int(settings.get("SAFE_Z", 0)) + 1

    def fault(name, _path):
        if name == "after_configuration_locations_replace":
            raise RuntimeError("power loss between governed files")

    context.configuration_transactions.io = DurableFileOps(fault_hook=fault)
    with pytest.raises(ConfigurationRecoveryRequired):
        context.configuration_transactions.commit_documents(
            {"Locations.json": locations, "Settings.json": settings},
            operator="Alice",
            reason="Multi-file recovery test",
            workflow="governed_configuration_import",
            event_type="import",
        )
    context.close()

    recovered = _bootstrap(base).open_ready()
    try:
        assert locations_path.read_bytes() == before_locations
        assert settings_path.read_bytes() == before_settings
        event = json.loads(
            next(recovered.paths.configuration_events_root.glob("*.json")).read_text(
                encoding="utf-8"
            )
        )
        assert event["event_type"] == "recovery"
        assert event["outcome"] == "recovered_abort"
    finally:
        recovered.close()


def test_import_is_restricted_to_governed_names_and_is_a_single_event(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        locations = json.loads(
            (context.paths.config_root / "Locations.json").read_text(encoding="utf-8")
        )
        locations["camera"]["Y"] += 505
        import_path = tmp_path / "reviewed-Locations.json"
        import_path.write_text(json.dumps(locations), encoding="utf-8")

        result = context.configuration_transactions.import_files(
            {"Locations.json": import_path},
            operator="Support",
            reason="Import reviewed calibration file",
        )
        assert result.event_type == "import"
        assert result.state.sequence == 1
        assert json.loads(
            (context.paths.config_root / "Locations.json").read_text(encoding="utf-8")
        ) == locations

        with pytest.raises(ConfigurationValidationError, match="Unsupported"):
            context.configuration_transactions.import_files(
                {"machine_identity.json": import_path},
                operator="Support",
                reason="Must not import identity",
            )
    finally:
        context.close()


def test_unreferenced_or_altered_pending_proposal_fails_closed(tmp_path):
    base, context = _active_context(tmp_path)
    locations = json.loads(
        (context.paths.config_root / "Locations.json").read_text(encoding="utf-8")
    )
    locations["camera"]["Y"] += 606

    def fault(name, _path):
        if name == "before_configuration_event_create":
            raise RuntimeError("leave a valid pending rollback journal")

    context.configuration_transactions.io = DurableFileOps(fault_hook=fault)
    with pytest.raises(ConfigurationRecoveryRequired):
        context.configuration_transactions.commit_documents(
            {"Locations.json": locations},
            operator="Alice",
            reason="Pending inventory test",
            workflow="named_location_modify",
        )
    pending_dir = next(context.paths.pending_transactions_root.iterdir())
    (pending_dir / "rogue.json").write_text("{}", encoding="utf-8")
    context.close()

    assert _bootstrap(base).inspect().state is MachineDataBootstrap.BootstrapState.RECOVERY_REQUIRED
    with pytest.raises(MachineDataBootstrap.BootstrapError):
        _bootstrap(base).open_ready()


def test_rack_pair_and_plate_quartet_each_commit_as_one_aggregate_event(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        locations = json.loads(
            (context.paths.config_root / "Locations.json").read_text(encoding="utf-8")
        )
        locations["rack_position_Left"]["Y"] += 10
        locations["rack_position_Right"]["Y"] += 20
        rack_result = service.commit_documents(
            {"Locations.json": locations},
            operator="Alice",
            reason="Recalibrate both rack anchors",
            workflow="rack_calibration",
        )
        assert rack_result.state.sequence == 1
        assert rack_result.state.authorization["rack:primary"]["state"] == "revoked_pending_verification"
        assert json.loads(
            (context.paths.config_root / "Locations.json").read_text(encoding="utf-8")
        )["rack_position_Right"] == locations["rack_position_Right"]

        plates = json.loads(
            (context.paths.config_root / "Plates.json").read_text(encoding="utf-8")
        )
        default_plate = next(plate for plate in plates if plate.get("default"))
        for index, corner in enumerate(
            ("top_left", "top_right", "bottom_right", "bottom_left"), start=1
        ):
            default_plate["calibrations"][corner]["X"] += index
        plate_result = service.commit_documents(
            {"Plates.json": plates},
            operator="Alice",
            reason="Recalibrate all four plate corners",
            workflow="plate_calibration",
        )
        assert plate_result.state.sequence == 2
        plate_keys = [key for key in plate_result.state.authorization if key.startswith("plate:")]
        assert plate_keys
        assert any(
            plate_result.state.authorization[key]["state"] == "revoked_pending_verification"
            for key in plate_keys
        )
        assert len(list(context.paths.configuration_events_root.glob("*.json"))) == 2
    finally:
        context.close()


def test_stale_snapshot_and_concurrent_writer_reject_before_mutation(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        locations_path = context.paths.config_root / "Locations.json"
        before = locations_path.read_bytes()
        locations = json.loads(before.decode("utf-8"))
        locations["camera"]["Y"] += 909
        stale = dict(service.state.config_sha256)
        stale["Locations.json"] = "0" * 64

        with pytest.raises(ConfigurationTransactionError, match="changed after"):
            service.commit_documents(
                {"Locations.json": locations},
                operator="Alice",
                reason="Stale proposal",
                workflow="named_location_modify",
                expected_config_sha256=stale,
            )
        assert locations_path.read_bytes() == before

        assert service._writer_mutex.acquire(blocking=False)
        try:
            with pytest.raises(ConfigurationTransactionError, match="already active"):
                service.commit_documents(
                    {"Locations.json": locations},
                    operator="Alice",
                    reason="Concurrent proposal",
                    workflow="named_location_modify",
                )
        finally:
            service._writer_mutex.release()
        assert locations_path.read_bytes() == before
        assert not context.paths.configuration_head_path.exists()
    finally:
        context.close()


def test_events_never_rewrite_migration_or_activation_evidence(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        immutable_before = {
            path.name: path.read_bytes() for path in context.paths.metadata_root.glob("*.json")
        }
        locations = json.loads(
            (context.paths.config_root / "Locations.json").read_text(encoding="utf-8")
        )
        locations["camera"]["Y"] += 1001
        context.configuration_transactions.commit_documents(
            {"Locations.json": locations},
            operator="Alice",
            reason="Immutable evidence test",
            workflow="named_location_modify",
        )
        immutable_after = {
            path.name: path.read_bytes() for path in context.paths.metadata_root.glob("*.json")
        }
        assert immutable_after == immutable_before
    finally:
        context.close()


def test_verification_method_policy_requires_supported_evidence(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        service = context.configuration_transactions
        values = {
            key: copy.deepcopy(value)
            for key, (_kind, _source, value) in build_target_snapshot(context.paths).items()
        }
        camera = values["location:camera"]
        with pytest.raises(ConfigurationValidationError, match="unsupported"):
            service.verify_targets(
                {"location:camera": camera},
                operator="Alice",
                reason="Invalid method",
                method="checkbox",
            )
        with pytest.raises(ConfigurationValidationError, match="requires its reference"):
            service.verify_targets(
                {"location:camera": camera},
                operator="Alice",
                reason="Missing service record",
                method="independent_service_record",
            )
    finally:
        context.close()


@pytest.mark.parametrize("tamper", ["event_extra_key", "head_hash", "unexpected_event"])
def test_history_schema_or_inventory_tampering_fails_closed(tmp_path, tamper):
    base, context = _active_context(tmp_path)
    locations = json.loads(
        (context.paths.config_root / "Locations.json").read_text(encoding="utf-8")
    )
    locations["camera"]["Y"] += 1111
    context.configuration_transactions.commit_documents(
        {"Locations.json": locations},
        operator="Alice",
        reason="Create history for tamper test",
        workflow="named_location_modify",
    )
    event_path = next(context.paths.configuration_events_root.glob("*.json"))
    if tamper == "event_extra_key":
        payload = json.loads(event_path.read_text(encoding="utf-8"))
        payload["unexpected"] = True
        event_path.write_text(json.dumps(payload), encoding="utf-8")
    elif tamper == "head_hash":
        payload = json.loads(context.paths.configuration_head_path.read_text(encoding="utf-8"))
        payload["latest_event_sha256"] = "0" * 64
        context.paths.configuration_head_path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        (context.paths.configuration_events_root / "unexpected.json").write_text(
            event_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    context.close()

    assert _bootstrap(base).inspect().state is MachineDataBootstrap.BootstrapState.RECOVERY_REQUIRED
    with pytest.raises(MachineDataBootstrap.BootstrapError):
        _bootstrap(base).open_ready()


def test_plate_geometry_change_revokes_plate_even_when_corners_are_unchanged(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        plates = json.loads(
            (context.paths.config_root / "Plates.json").read_text(encoding="utf-8")
        )
        plate = next(item for item in plates if item.get("default"))
        target_key = f"plate:{plate['name'].casefold()}"
        corners_before = copy.deepcopy(plate["calibrations"])
        plate["spacing"] = plate["spacing"] + 1

        result = context.configuration_transactions.commit_documents(
            {"Plates.json": plates},
            operator="Alice",
            reason="Reviewed plate geometry change",
            workflow="governed_configuration_import",
            event_type="import",
        )

        assert plate["calibrations"] == corners_before
        assert result.state.authorization[target_key]["state"] == "revoked_pending_verification"
        event = json.loads(
            next(context.paths.configuration_events_root.glob("*.json")).read_text(
                encoding="utf-8"
            )
        )
        dependency = next(
            change for change in event["changes"] if change.get("target_key") == target_key
        )
        assert dependency["dependency_changed"] is True
    finally:
        context.close()
