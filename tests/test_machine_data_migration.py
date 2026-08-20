import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import MachineData
import MachineDataArchive
import MachineDataLock
import MachineDataMigration
from tests.machine_data_migration_helpers import (
    FIXED_TIME,
    MACHINE_UUID,
    MIGRATION_ID,
    fixed_clock,
    inspect_wrapper,
    machine_data_paths,
    migration_policy,
    target_identity,
    write_candidate,
    write_wrapper,
)


def _selection(path, kind=MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_LOCAL):
    return MachineDataMigration.CandidateSelection(kind, path, "synthetic candidate")


def test_historical_catalog_recognizes_both_reviewed_source_cohorts(tmp_path):
    catalog = MachineDataMigration.PresetFingerprintCatalog.load()

    matches = {}
    for cohort in ("v1.2.0-rc.6", "v1.3.0-rc.1"):
        wrapper, _local = write_wrapper(tmp_path / cohort, cohort=cohort)
        evidence = inspect_wrapper(wrapper)
        matches[cohort] = evidence.preset_matches
        assert evidence.camera_preset_match is True
        assert evidence.preset_like is True

    assert {cohort.cohort for cohort in catalog.cohorts} == {
        "v1.2.0-rc.6",
        "v1.3.0-rc.1",
    }
    assert matches == {
        "v1.2.0-rc.6": ("v1.2.0-rc.6",),
        "v1.3.0-rc.1": ("v1.3.0-rc.1",),
    }


def test_custom_camera_is_not_mistaken_for_historical_camera(tmp_path):
    wrapper, _local = write_wrapper(tmp_path, custom_camera=True)

    evidence = inspect_wrapper(wrapper)

    assert evidence.is_importable
    assert evidence.preset_like is False
    assert evidence.camera_preset_match is False
    assert evidence.safety_snapshot["locations"]["camera"] == {
        "X": 11040,
        "Y": 39636,
        "Z": 98052,
    }


@pytest.mark.parametrize(
    "kind",
    [
        MachineDataMigration.CandidateSourceKind.CURRENT_CHECKOUT_LOCAL,
        MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_LOCAL,
        MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_WRAPPER,
    ],
)
def test_directory_candidate_kinds_use_only_explicit_shallow_layout(tmp_path, kind):
    wrapper, local_root = write_wrapper(tmp_path, custom_camera=True)
    selected = {
        MachineDataMigration.CandidateSourceKind.CURRENT_CHECKOUT_LOCAL: wrapper,
        MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_LOCAL: local_root,
        MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_WRAPPER: wrapper,
    }[kind]

    evidence = MachineDataMigration.inspect_candidate(_selection(selected, kind))

    assert evidence.is_importable
    assert evidence.normalized_source == local_root.resolve()


def test_missing_recursive_and_ambiguous_directory_candidates_fail_closed(tmp_path):
    missing = MachineDataMigration.inspect_candidate(_selection(tmp_path / "missing"))
    nested_root = tmp_path / "nested-only"
    write_candidate(nested_root / "one" / "two", custom_camera=True)
    nested = MachineDataMigration.inspect_candidate(_selection(nested_root))
    wrapper, local_root = write_wrapper(tmp_path / "ambiguous", custom_camera=True)
    for filename in MachineDataMigration.REQUIRED_CONFIG_NAMES:
        (wrapper / filename).write_bytes((local_root / filename).read_bytes())
    ambiguous = MachineDataMigration.inspect_candidate(
        _selection(
            wrapper,
            MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_WRAPPER,
        )
    )

    assert not missing.is_importable
    assert not nested.is_importable
    assert not ambiguous.is_importable


def test_existing_canonical_is_inspection_only(tmp_path):
    machine_root = tmp_path / "canonical"
    write_candidate(machine_root / "config", custom_camera=True, calibration_memory=False)

    evidence = MachineDataMigration.inspect_candidate(
        _selection(
            machine_root,
            MachineDataMigration.CandidateSourceKind.EXISTING_CANONICAL,
        )
    )

    assert evidence.required_files
    assert evidence.is_importable is False
    assert "existing_canonical_inspection_only" in {
        issue.code for issue in evidence.issues
    }


@pytest.mark.parametrize(
    ("mutation", "issue_code"),
    [
        ("missing_settings", "missing_required_config"),
        ("malformed_locations", "invalid_required_config"),
        ("wrong_obstacles_type", "invalid_required_config"),
        ("missing_camera", "invalid_safety_snapshot"),
        ("boolean_camera_axis", "invalid_safety_snapshot"),
        ("partial_plate", "invalid_safety_snapshot"),
    ],
)
def test_invalid_required_or_safety_data_fails_closed(tmp_path, mutation, issue_code):
    local_root = write_candidate(tmp_path / "local", custom_camera=True)
    if mutation == "missing_settings":
        (local_root / "Settings.json").unlink()
    elif mutation == "malformed_locations":
        (local_root / "Locations.json").write_text("{ bad", encoding="utf-8")
    elif mutation == "wrong_obstacles_type":
        (local_root / "Obstacles.json").write_text("[]", encoding="utf-8")
    elif mutation == "missing_camera":
        locations = json.loads((local_root / "Locations.json").read_text())
        del locations["camera"]
        (local_root / "Locations.json").write_text(json.dumps(locations), encoding="utf-8")
    elif mutation == "boolean_camera_axis":
        locations = json.loads((local_root / "Locations.json").read_text())
        locations["camera"]["Y"] = True
        (local_root / "Locations.json").write_text(json.dumps(locations), encoding="utf-8")
    elif mutation == "partial_plate":
        plates = json.loads((local_root / "Plates.json").read_text())
        calibrated = next(plate for plate in plates if plate["calibrations"])
        del calibrated["calibrations"]["bottom_left"]
        (local_root / "Plates.json").write_text(json.dumps(plates), encoding="utf-8")

    evidence = MachineDataMigration.inspect_candidate(_selection(local_root))

    assert evidence.is_importable is False
    assert issue_code in {issue.code for issue in evidence.issues}


def test_optional_state_is_reported_without_seeding_and_known_calibration_is_classified(tmp_path):
    local_root = write_candidate(
        tmp_path / "local",
        custom_camera=True,
        calibration_memory=False,
        optics=True,
        regulator_optimization=True,
        extra_files={"support.log": "synthetic log\n"},
    )

    evidence = MachineDataMigration.inspect_candidate(_selection(local_root))

    assert evidence.is_importable
    assert evidence.calibration_memory_status == "absent"
    assert evidence.identity_status == "absent"
    assert "support.log" in evidence.unclassified_source_paths
    migratable = {item.relative_path for item in evidence.migratable_files}
    assert "calibration/droplet_imager_optics.json" in migratable
    assert "calibration/regulator_optimization/synthetic_run.json" in migratable
    assert not (local_root / "CalibrationMemory").exists()


def test_incomplete_calibration_memory_and_unassigned_identity_remain_visible(tmp_path):
    identity = target_identity().to_payload()
    identity["machine_id"] = MachineData.UNASSIGNED_MACHINE_ID
    local_root = write_candidate(
        tmp_path / "local", custom_camera=True, identity_payload=identity
    )
    (local_root / "CalibrationMemory" / "config.json").unlink()

    evidence = MachineDataMigration.inspect_candidate(_selection(local_root))

    assert evidence.is_importable
    assert evidence.calibration_memory_status == "present_incomplete"
    assert evidence.missing_calibration_memory_seed_files == ("config.json",)
    assert evidence.identity_status == "unassigned"


def test_empty_calibration_memory_directory_is_present_but_incomplete(tmp_path):
    local_root = write_candidate(
        tmp_path / "local", custom_camera=True, calibration_memory=False
    )
    (local_root / "CalibrationMemory").mkdir()

    evidence = MachineDataMigration.inspect_candidate(_selection(local_root))

    assert evidence.calibration_memory_status == "present_incomplete"
    assert set(evidence.missing_calibration_memory_seed_files) == set(
        MachineDataMigration.CALIBRATION_MEMORY_SEED_TYPES
    )


def test_declared_version_mismatch_is_a_warning_not_a_winner_rule(tmp_path):
    wrapper, _local = write_wrapper(tmp_path, cohort="v1.3.0-rc.1")
    (wrapper / "VERSION").write_text("v1.2.0-rc.6\n", encoding="utf-8")

    evidence = inspect_wrapper(wrapper)

    assert evidence.preset_matches == ("v1.3.0-rc.1",)
    assert evidence.declared_version_mismatch is True
    assert evidence.is_importable


def test_candidate_comparison_distinguishes_exact_optional_and_required_conflicts(tmp_path):
    first_root = write_candidate(tmp_path / "first", custom_camera=True)
    second_root = write_candidate(tmp_path / "second", custom_camera=True)
    third_root = write_candidate(
        tmp_path / "third",
        custom_camera=True,
        extra_files={"CalibrationMemory/runs/other.json": "{}\n"},
    )
    fourth_root = write_candidate(tmp_path / "fourth", custom_camera=True)
    settings = json.loads((fourth_root / "Settings.json").read_text())
    settings["RACK_SLOTS"] = 7
    (fourth_root / "Settings.json").write_text(json.dumps(settings), encoding="utf-8")

    candidates = [
        MachineDataMigration.inspect_candidate(_selection(root))
        for root in (first_root, second_root, third_root, fourth_root)
    ]
    comparison = MachineDataMigration.classify_candidates(candidates)
    relations = {
        (relation.first_candidate_id, relation.second_candidate_id): relation.classification
        for relation in comparison.relations
    }

    assert relations[(candidates[0].candidate_id, candidates[1].candidate_id)] == "exact_duplicate"
    assert (
        relations[(candidates[0].candidate_id, candidates[2].candidate_id)]
        == "config_duplicates_with_optional_conflict"
    )
    assert relations[(candidates[0].candidate_id, candidates[3].candidate_id)] == "conflict"


def test_full_directory_journey_preserves_source_and_publishes_inactive_exact_tree(tmp_path):
    wrapper, local_root = write_wrapper(
        tmp_path,
        custom_camera=True,
        optics=True,
        regulator_optimization=True,
        extra_files={"unknown/support.txt": "preserve me\n"},
    )
    source_before = {
        path.relative_to(local_root).as_posix(): path.read_bytes()
        for path in local_root.rglob("*")
        if path.is_file()
    }
    candidate = inspect_wrapper(wrapper)
    base, target_paths = machine_data_paths(tmp_path)
    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )
    identity = target_identity()

    with MachineDataLock.acquire_migration_lock(base, MACHINE_UUID) as lock:
        backup = MachineDataMigration.create_verified_backup(
            candidate,
            workspace=workspace,
            target_identity=identity,
            acquired_lock=lock,
            policy=migration_policy(),
            clock=fixed_clock,
        )
        with zipfile.ZipFile(backup.archive_path) as archive:
            assert "source/local/unknown/support.txt" in archive.namelist()
            assert "source/VERSION" in archive.namelist()
        result = MachineDataMigration.import_verified_candidate(
            candidate,
            backup,
            workspace=workspace,
            target_paths=target_paths,
            target_identity=identity,
            acquired_lock=lock,
            policy=migration_policy(),
            clock=fixed_clock,
        )

    assert result.state == MachineDataMigration.MigrationState.COPIED_UNVERIFIED
    assert result.receipt.activation_authorized is False
    assert result.receipt.source_verified is False
    assert result.receipt.calibration_verified is False
    receipt_payload = json.loads(target_paths.migration_receipt_path.read_text())
    assert receipt_payload["activation_authorized"] is False
    assert receipt_payload["source_verified"] is False
    assert receipt_payload["calibration_verified"] is False
    assert (target_paths.config_root / "Locations.json").read_bytes() == (
        local_root / "Locations.json"
    ).read_bytes()
    assert target_paths.droplet_imager_optics_path.exists()
    assert (
        target_paths.regulator_optimization_root / "synthetic_run.json"
    ).exists()
    assert not (target_paths.machine_root / "unknown" / "support.txt").exists()
    assert result.backup_archive_path.exists()
    assert not base.active_machine_path.exists()
    assert not workspace.root.exists()
    assert source_before == {
        path.relative_to(local_root).as_posix(): path.read_bytes()
        for path in local_root.rglob("*")
        if path.is_file()
    }


def test_backup_manifest_records_safety_evidence_and_optional_firmware_as_package_only(tmp_path):
    wrapper, _local = write_wrapper(tmp_path, custom_camera=True)
    candidate = inspect_wrapper(wrapper)
    firmware = tmp_path / "LabCraft_firmware.bin"
    firmware.write_bytes(b"synthetic firmware package evidence")
    base, _target_paths = machine_data_paths(tmp_path)
    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )

    with MachineDataLock.acquire_migration_lock(base, MACHINE_UUID) as lock:
        backup = MachineDataMigration.create_verified_backup(
            candidate,
            workspace=workspace,
            target_identity=target_identity(),
            acquired_lock=lock,
            policy=migration_policy(),
            firmware_artifact=firmware,
            clock=fixed_clock,
        )

    assert backup.manifest["safety_snapshot"]["locations"]["camera"]["Y"] == 39636
    assert backup.manifest["firmware_artifact"]["evidence_kind"] == (
        "package_artifact_not_installed_firmware_proof"
    )
    with zipfile.ZipFile(backup.archive_path) as archive:
        assert "source/firmware/LabCraft_firmware.bin" in archive.namelist()


def test_source_change_during_backup_is_classified_and_never_published(tmp_path):
    wrapper, local_root = write_wrapper(tmp_path, custom_camera=True)
    candidate = inspect_wrapper(wrapper)
    base, target_paths = machine_data_paths(tmp_path)
    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )

    class MutateAtBackup:
        changed = False

        def __call__(self, name, _path):
            if name == "before_backup_write" and not self.changed:
                self.changed = True
                (local_root / "Locations.json").write_text("{}", encoding="utf-8")

    io = MachineDataMigration.MigrationFileOps(MutateAtBackup())
    with MachineDataLock.acquire_migration_lock(base, MACHINE_UUID) as lock:
        with pytest.raises(MachineDataMigration.MigrationError) as error:
            MachineDataMigration.create_verified_backup(
                candidate,
                workspace=workspace,
                target_identity=target_identity(),
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
            )

    assert error.value.code == "source_changed"
    assert not workspace.backup_path.exists()
    assert not target_paths.machine_root.exists()
    assert not base.active_machine_path.exists()


def test_verified_backup_changed_after_return_is_rejected_before_staging(tmp_path):
    wrapper, _local = write_wrapper(tmp_path, custom_camera=True)
    candidate = inspect_wrapper(wrapper)
    base, target_paths = machine_data_paths(tmp_path)
    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )
    identity = target_identity()

    with MachineDataLock.acquire_migration_lock(base, MACHINE_UUID) as lock:
        backup = MachineDataMigration.create_verified_backup(
            candidate,
            workspace=workspace,
            target_identity=identity,
            acquired_lock=lock,
            policy=migration_policy(),
        )
        backup.archive_path.write_bytes(backup.archive_path.read_bytes() + b"tamper")
        with pytest.raises(MachineDataMigration.MigrationRecoveryRequired):
            MachineDataMigration.import_verified_candidate(
                candidate,
                backup,
                workspace=workspace,
                target_paths=target_paths,
                target_identity=identity,
                acquired_lock=lock,
                policy=migration_policy(),
            )

    assert not workspace.staged_machine_root.exists()
    assert not target_paths.machine_root.exists()


def test_insufficient_space_fails_before_backup_or_target_write(tmp_path):
    wrapper, _local = write_wrapper(tmp_path, custom_camera=True)
    candidate = inspect_wrapper(wrapper)
    base, target_paths = machine_data_paths(tmp_path)
    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )

    class NoSpaceOps(MachineDataMigration.MigrationFileOps):
        def disk_usage(self, _path):
            return SimpleNamespace(total=1, used=1, free=0)

    with MachineDataLock.acquire_migration_lock(base, MACHINE_UUID) as lock:
        with pytest.raises(MachineDataMigration.MigrationError) as error:
            MachineDataMigration.create_verified_backup(
                candidate,
                workspace=workspace,
                target_identity=target_identity(),
                acquired_lock=lock,
                io=NoSpaceOps(),
                policy=migration_policy(),
            )

    assert error.value.code == "insufficient_space"
    assert not workspace.backup_path.exists()
    assert not target_paths.machine_root.exists()


def test_stage_reads_verified_backup_not_mutated_live_source(tmp_path):
    wrapper, local_root = write_wrapper(tmp_path, custom_camera=True)
    candidate = inspect_wrapper(wrapper)
    original_locations = (local_root / "Locations.json").read_bytes()
    base, target_paths = machine_data_paths(tmp_path)
    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )
    identity = target_identity()

    with MachineDataLock.acquire_migration_lock(base, MACHINE_UUID) as lock:
        backup = MachineDataMigration.create_verified_backup(
            candidate,
            workspace=workspace,
            target_identity=identity,
            acquired_lock=lock,
            policy=migration_policy(),
            clock=fixed_clock,
        )
        changed = json.loads(original_locations)
        changed["camera"]["Y"] = 1
        (local_root / "Locations.json").write_text(json.dumps(changed), encoding="utf-8")
        MachineDataMigration.import_verified_candidate(
            candidate,
            backup,
            workspace=workspace,
            target_paths=target_paths,
            target_identity=identity,
            acquired_lock=lock,
            policy=migration_policy(),
            clock=fixed_clock,
        )

    assert (target_paths.config_root / "Locations.json").read_bytes() == original_locations


def test_assigned_legacy_identity_conflict_blocks_backup(tmp_path):
    identity = target_identity()
    conflicting = identity.to_payload()
    conflicting["machine_uuid"] = "00000000-0000-0000-0000-000000000099"
    local_root = write_candidate(
        tmp_path / "local", custom_camera=True, identity_payload=conflicting
    )
    candidate = MachineDataMigration.inspect_candidate(_selection(local_root))
    base, _target_paths = machine_data_paths(tmp_path)
    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )

    with MachineDataLock.acquire_migration_lock(base, MACHINE_UUID) as lock:
        with pytest.raises(MachineDataMigration.MigrationError) as error:
            MachineDataMigration.create_verified_backup(
                candidate,
                workspace=workspace,
                target_identity=identity,
                acquired_lock=lock,
                policy=migration_policy(),
            )

    assert error.value.code == "identity_conflict"
    assert not workspace.backup_path.exists()


def test_selected_zip_candidate_has_same_semantic_evidence_as_directory(tmp_path):
    local_root = write_candidate(tmp_path / "local", custom_camera=True)
    directory = MachineDataMigration.inspect_candidate(_selection(local_root))
    archive_path = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in local_root.rglob("*"):
            if path.is_file():
                archive.write(path, f"local/{path.relative_to(local_root).as_posix()}")
        archive.writestr("VERSION", "v1.3.0-rc.1\n")

    zipped = MachineDataMigration.inspect_candidate(
        _selection(
            archive_path,
            MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_ZIP,
        )
    )

    assert zipped.is_importable
    assert zipped.required_config_fingerprint == directory.required_config_fingerprint
    assert zipped.migratable_tree_fingerprint == directory.migratable_tree_fingerprint


def test_milestone_two_remains_disconnected_from_production():
    app_source = Path("FreeRTOS-interface/App.py").read_text(encoding="utf-8")
    composition_source = Path("FreeRTOS-interface/ApplicationComposition.py").read_text(
        encoding="utf-8"
    )
    migration_source = Path("FreeRTOS-interface/MachineDataMigration.py").read_text(
        encoding="utf-8"
    )

    assert "MachineDataMigration" not in app_source
    assert "MachineDataArchive" not in app_source
    assert "MachineDataLock" not in app_source
    assert "MachineDataMigration" not in composition_source
    assert ".active_machine_path" not in migration_source
    for forbidden in (
        "from App import",
        "from Model import",
        "from Controller import",
        "from View import",
        "Machine_FreeRTOS",
        "update_and_restart",
    ):
        assert forbidden not in migration_source
