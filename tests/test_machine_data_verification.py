import json
from dataclasses import replace

import pytest

import MachineData
import MachineDataArchive
import MachineDataLock
import MachineDataMigration
import MachineDataOwnership
import MachineDataVerification
from tests.machine_data_migration_helpers import (
    FIXED_TIME,
    MACHINE_ID,
    MACHINE_UUID,
    publish_candidate,
)


APP_VERSION = "v1.3.0-rc.2"
APP_COMMIT = "test-commit"
ACTIVATION_ID = "00000000-0000-0000-0000-000000000003"


def _verification(tmp_path):
    base, paths, identity, _candidate, _result = publish_candidate(tmp_path)
    published = MachineDataMigration.verify_published_migration(paths)
    policy = MachineDataOwnership.MachineDataOwnershipPolicy.load()
    ownership = policy.classify_all(published.receipt.unclassified_source_paths)
    camera = published.candidate.safety_snapshot["locations"]["camera"]
    verification = MachineDataVerification.create_machine_verification(
        paths=paths,
        identity=identity,
        published=published,
        ownership_decisions=ownership,
        operator="Test Operator",
        machine_id_confirmation=MACHINE_ID,
        source_reason="Preserved pre-update backup",
        camera_confirmation=camera,
        service_record_reference=None,
        app_version=APP_VERSION,
        app_commit=APP_COMMIT,
        clock=lambda: FIXED_TIME,
    )
    return base, paths, identity, published, verification


def _active_migration(tmp_path):
    base, paths, identity, published, verification = _verification(tmp_path)
    verification_sha, directory_synced = MachineDataVerification.write_machine_verification(
        paths, verification
    )
    receipt = MachineDataVerification.ActivationReceipt(
        activation_id=ACTIVATION_ID,
        migration_id=published.receipt.migration_id,
        machine_id=identity.machine_id,
        machine_uuid=identity.machine_uuid,
        migration_receipt_sha256=verification.migration_receipt_sha256,
        migration_tree_manifest_sha256=published.migration_tree_manifest_sha256,
        verification_sha256=verification_sha,
        backup_archive_sha256=published.receipt.backup_archive_sha256,
        ownership_policy_version=1,
        directory_sync_supported=directory_synced,
        created_at_utc=FIXED_TIME,
        app_version=APP_VERSION,
        app_commit=APP_COMMIT,
    )
    MachineDataVerification.write_activation_receipt(paths, receipt)
    return base, paths, identity, published, verification


def test_public_m2_phase_verifier_keeps_baseline_immutable(tmp_path):
    _base, paths, _identity, _candidate, _result = publish_candidate(tmp_path)

    exact = MachineDataMigration.verify_published_migration(paths)
    paths.verification_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(MachineDataMigration.MigrationRecoveryRequired):
        MachineDataMigration.verify_published_migration(paths)
    staged = MachineDataMigration.verify_published_migration(
        paths, phase=MachineDataMigration.PublishedMigrationPhase.ACTIVATION_STAGED
    )
    assert staged.receipt == exact.receipt
    assert staged.additional_paths == ("metadata/verification.json",)


def test_public_candidate_and_receipt_parsers_reject_authority_mutation(tmp_path):
    _base, paths, _identity, _candidate, _result = publish_candidate(tmp_path)
    candidate = MachineDataMigration.load_candidate_evidence(paths.candidate_evidence_path)
    payload = json.loads(paths.migration_receipt_path.read_text(encoding="utf-8"))
    payload["source_verified"] = True

    assert candidate.camera_preset_match is False
    with pytest.raises(MachineDataMigration.MigrationRecoveryRequired, match="cannot authorize"):
        MachineDataMigration.parse_migration_receipt(payload)


def test_configuration_lock_is_accepted_only_as_known_phase_file(tmp_path):
    _base, paths, _identity, _candidate, _result = publish_candidate(tmp_path)

    with MachineDataLock.acquire_configuration_lock(paths) as lock:
        lock.assert_owns(paths)
        with pytest.raises(MachineDataMigration.MigrationRecoveryRequired):
            MachineDataMigration.verify_published_migration(paths)
        staged = MachineDataMigration.verify_published_migration(
            paths, phase=MachineDataMigration.PublishedMigrationPhase.ACTIVATION_STAGED
        )
        assert staged.additional_paths == ("locks/configuration.lock",)


def test_verification_binds_all_targets_and_round_trips(tmp_path):
    _base, paths, _identity, _published, verification = _verification(tmp_path)

    digest, _directory_synced = MachineDataVerification.write_machine_verification(
        paths, verification
    )
    loaded = MachineDataVerification.load_machine_verification(paths.verification_path)

    assert loaded == verification
    assert len(digest) == 64
    assert "location:camera" in loaded.targets
    assert "rack:primary" in loaded.targets
    assert any(key.startswith("plate:") for key in loaded.targets)
    MachineDataVerification.validate_verification_against_files(paths, loaded)


def test_verification_parser_rejects_malformed_persisted_ownership_decision(tmp_path):
    _base, _paths, _identity, _published, verification = _verification(tmp_path)
    payload = verification.to_payload()
    payload["ownership_decisions"] = [
        {
            "relative_path": "update_logs/run.txt",
            "classification": "not-a-policy-value",
            "rule_id": "archive-update-logs-v1",
            "reason": "test",
            "canonical_destination": None,
        }
    ]

    with pytest.raises(
        MachineDataVerification.VerificationError,
        match="classification",
    ):
        MachineDataVerification.parse_machine_verification(payload)


def test_camera_confirmation_and_preset_service_rules_fail_closed(tmp_path):
    _base, paths, identity, _candidate, _result = publish_candidate(tmp_path)
    published = MachineDataMigration.verify_published_migration(paths)
    ownership = MachineDataOwnership.MachineDataOwnershipPolicy.load().classify_all(())

    with pytest.raises(MachineDataVerification.VerificationError, match="Camera confirmation"):
        MachineDataVerification.create_machine_verification(
            paths=paths,
            identity=identity,
            published=published,
            ownership_decisions=ownership,
            operator="Operator",
            machine_id_confirmation=MACHINE_ID,
            source_reason="backup",
            camera_confirmation={"X": 0, "Y": 0, "Z": 0},
            service_record_reference=None,
            app_version=APP_VERSION,
            app_commit=APP_COMMIT,
            clock=lambda: FIXED_TIME,
        )

    preset_root = tmp_path / "preset"
    _base, preset_paths, preset_identity, _candidate, _result = publish_candidate(
        preset_root, wrapper_kwargs={"custom_camera": False}
    )
    preset = MachineDataMigration.verify_published_migration(preset_paths)
    camera = preset.candidate.safety_snapshot["locations"]["camera"]
    with pytest.raises(MachineDataVerification.VerificationError, match="service evidence"):
        MachineDataVerification.create_machine_verification(
            paths=preset_paths,
            identity=preset_identity,
            published=preset,
            ownership_decisions=ownership,
            operator="Operator",
            machine_id_confirmation=MACHINE_ID,
            source_reason="backup",
            camera_confirmation=camera,
            service_record_reference=None,
            app_version=APP_VERSION,
            app_commit=APP_COMMIT,
            clock=lambda: FIXED_TIME,
        )


def test_saved_target_authorizer_blocks_file_and_value_changes(tmp_path):
    _base, paths, _identity, _published, verification = _verification(tmp_path)
    authorizer = MachineDataVerification.SavedTargetAuthorizer(paths, verification)
    camera = verification.targets["location:camera"]
    request = MachineDataVerification.SavedTargetAuthorizationRequest(
        machine_uuid=MACHINE_UUID,
        target_key="location:camera",
        target_kind="location",
        base_value=camera.value,
        final_coordinates=camera.value,
        workflow="test",
        offsets={},
        manual=True,
        override=True,
        ignore_safe_height=True,
    )

    assert authorizer.authorize(request).allowed is True
    changed = replace(request, base_value={"X": 1, "Y": 2, "Z": 3})
    assert authorizer.authorize(changed).reason_code == "target_value_changed"
    locations_path = paths.config_root / "Locations.json"
    locations = json.loads(locations_path.read_text(encoding="utf-8"))
    locations["pause"]["Y"] += 1
    locations_path.write_text(json.dumps(locations), encoding="utf-8")
    assert authorizer.authorize(request).reason_code == "source_file_changed"


def test_activation_receipt_and_v2_pointer_bind_exact_hashes(tmp_path):
    _base, paths, identity, published, verification = _verification(tmp_path)
    verification_sha, directory_synced = MachineDataVerification.write_machine_verification(
        paths, verification
    )
    receipt = MachineDataVerification.ActivationReceipt(
        activation_id=ACTIVATION_ID,
        migration_id=published.receipt.migration_id,
        machine_id=identity.machine_id,
        machine_uuid=identity.machine_uuid,
        migration_receipt_sha256=verification.migration_receipt_sha256,
        migration_tree_manifest_sha256=published.migration_tree_manifest_sha256,
        verification_sha256=verification_sha,
        backup_archive_sha256=published.receipt.backup_archive_sha256,
        ownership_policy_version=1,
        directory_sync_supported=directory_synced,
        created_at_utc=FIXED_TIME,
        app_version=APP_VERSION,
        app_commit=APP_COMMIT,
    )
    activation_sha = MachineDataVerification.write_activation_receipt(paths, receipt)
    active = MachineData.ActiveMachine(
        machine_id=MACHINE_ID,
        machine_uuid=MACHINE_UUID,
        selected_at_utc=FIXED_TIME,
        selection_source="migration",
        activation_id=ACTIVATION_ID,
        migration_id=published.receipt.migration_id,
        activation_receipt_sha256=activation_sha,
    )

    parsed = MachineData.require_authorized_active_machine(active.to_payload())
    assert parsed == active
    with pytest.raises(MachineData.ActiveMachineError, match="diagnostic-only"):
        MachineData.require_authorized_active_machine(
            MachineData.ActiveMachine(
                MACHINE_ID, MACHINE_UUID, FIXED_TIME, "migration"
            ).to_payload()
        )
    final = MachineDataMigration.verify_published_migration(
        paths, phase=MachineDataMigration.PublishedMigrationPhase.ACTIVE
    )
    assert set(final.additional_paths) == {
        "metadata/activation_receipt.json",
        "metadata/verification.json",
    }


def test_active_runtime_calibration_files_may_change_without_weakening_config(tmp_path):
    _base, paths, _identity, _published, _verification = _active_migration(tmp_path)

    runtime_config = paths.calibration_memory_root / "config.json"
    config_payload = json.loads(runtime_config.read_text(encoding="utf-8"))
    config_payload["updated_at_utc"] = "2026-08-20T17:32:32Z"
    runtime_config.write_text(json.dumps(config_payload, indent=2) + "\n", encoding="utf-8")

    reagents = paths.calibration_memory_root / "entities" / "reagents.json"
    reagent_payload = json.loads(reagents.read_text(encoding="utf-8"))
    reagent_payload["updated_at_utc"] = "2026-08-20T17:32:32Z"
    reagents.write_text(json.dumps(reagent_payload, indent=2) + "\n", encoding="utf-8")

    new_run = paths.calibration_memory_root / "runs" / "post-activation.json"
    new_run.parent.mkdir(parents=True, exist_ok=True)
    new_run.write_text('{"status":"complete"}\n', encoding="utf-8")
    optics = paths.calibration_root / "droplet_imager_optics.json"
    optics.parent.mkdir(parents=True, exist_ok=True)
    optics.write_text('{"pixel_to_step":1.5}\n', encoding="utf-8")

    verified = MachineDataMigration.verify_published_migration(
        paths, phase=MachineDataMigration.PublishedMigrationPhase.ACTIVE
    )
    assert "CalibrationMemory/runs/post-activation.json" in verified.additional_paths
    assert "calibration/droplet_imager_optics.json" in verified.additional_paths

    locations = paths.config_root / "Locations.json"
    locations.write_bytes(locations.read_bytes() + b"\n")
    with pytest.raises(
        MachineDataMigration.MigrationRecoveryRequired,
        match="immutable manifest",
    ):
        MachineDataMigration.verify_published_migration(
            paths, phase=MachineDataMigration.PublishedMigrationPhase.ACTIVE
        )


def test_active_runtime_calibration_schema_and_required_seed_files_remain_protected(tmp_path):
    _base, paths, _identity, _published, _verification = _active_migration(tmp_path)

    schema = paths.calibration_memory_root / "schema.json"
    schema_before = schema.read_bytes()
    schema.write_bytes(schema.read_bytes() + b"\n")
    with pytest.raises(
        MachineDataMigration.MigrationRecoveryRequired,
        match="immutable manifest",
    ):
        MachineDataMigration.verify_published_migration(
            paths, phase=MachineDataMigration.PublishedMigrationPhase.ACTIVE
        )

    # Restore the immutable schema, then prove a required mutable seed cannot
    # simply disappear even though its contents are allowed to evolve.
    schema.write_bytes(schema_before)
    (paths.calibration_memory_root / "entities" / "reagents.json").unlink()
    with pytest.raises(
        MachineDataMigration.MigrationRecoveryRequired,
        match="CalibrationMemory baseline is invalid",
    ):
        MachineDataMigration.verify_published_migration(
            paths, phase=MachineDataMigration.PublishedMigrationPhase.ACTIVE
        )
