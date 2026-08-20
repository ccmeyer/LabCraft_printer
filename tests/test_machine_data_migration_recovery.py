import json

import pytest

import MachineData
import MachineDataLock
import MachineDataMigration
from tests.machine_data_migration_helpers import (
    MACHINE_UUID,
    MIGRATION_ID,
    fixed_clock,
    inspect_wrapper,
    machine_data_paths,
    migration_policy,
    target_identity,
    write_wrapper,
)


class FailOnceAt:
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint
        self.triggered = False

    def __call__(self, name, _path):
        if name == self.checkpoint and not self.triggered:
            self.triggered = True
            raise OSError(f"synthetic fault at {name}")


class FailNthAt:
    def __init__(self, checkpoint, occurrence):
        self.checkpoint = checkpoint
        self.occurrence = occurrence
        self.count = 0
        self.triggered = False

    def __call__(self, name, _path):
        if name == self.checkpoint:
            self.count += 1
            if self.count == self.occurrence:
                self.triggered = True
                raise OSError(f"synthetic fault at {name} occurrence {self.count}")


def _prepared_backup(tmp_path, *, io=None):
    wrapper, _local = write_wrapper(tmp_path, custom_camera=True)
    candidate = inspect_wrapper(wrapper)
    base, target_paths = machine_data_paths(tmp_path)
    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )
    identity = target_identity()
    lock = MachineDataLock.acquire_migration_lock(base, MACHINE_UUID)
    backup = MachineDataMigration.create_verified_backup(
        candidate,
        workspace=workspace,
        target_identity=identity,
        acquired_lock=lock,
        io=io,
        policy=migration_policy(),
        clock=fixed_clock,
    )
    return candidate, base, target_paths, workspace, identity, lock, backup


@pytest.mark.parametrize("fault_point", ["before_target_rename", "after_target_rename"])
def test_publication_fault_reconciles_without_overlay_or_active_pointer(tmp_path, fault_point):
    fault = FailOnceAt(fault_point)
    io = MachineDataMigration.MigrationFileOps(fault)
    candidate, base, target_paths, workspace, identity, lock, backup = _prepared_backup(
        tmp_path, io=io
    )
    try:
        with pytest.raises(MachineDataMigration.MigrationError) as error:
            MachineDataMigration.import_verified_candidate(
                candidate,
                backup,
                workspace=workspace,
                target_paths=target_paths,
                target_identity=identity,
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
                clock=fixed_clock,
            )
        assert error.value.code == "copy_failed"

        result = MachineDataMigration.reconcile_migration(
            workspace=workspace,
            target_paths=target_paths,
            acquired_lock=lock,
            io=io,
            policy=migration_policy(),
            clock=fixed_clock,
        )
    finally:
        lock.release()

    assert fault.triggered
    assert result.reconciled is True
    assert result.receipt.state == MachineDataMigration.MigrationState.COPIED_UNVERIFIED
    assert not base.active_machine_path.exists()
    assert not workspace.root.exists()


def test_backup_verified_state_resumes_stage_and_publication(tmp_path):
    candidate, base, target_paths, workspace, _identity, lock, _backup = _prepared_backup(
        tmp_path
    )
    try:
        journal = json.loads(workspace.journal_path.read_text())
        assert journal["state"] == "backup_verified"

        result = MachineDataMigration.reconcile_migration(
            workspace=workspace,
            target_paths=target_paths,
            acquired_lock=lock,
            policy=migration_policy(),
            clock=fixed_clock,
        )
    finally:
        lock.release()

    assert result.reconciled
    assert result.receipt.candidate_id == candidate.candidate_id
    assert target_paths.machine_root.exists()
    assert not base.active_machine_path.exists()


@pytest.mark.parametrize(
    "fault_point",
    [
        "before_backup_write",
        "before_backup_member",
        "after_backup_member",
        "before_backup_manifest",
        "after_backup_manifest",
        "after_backup_fsync",
        "after_backup_replace",
        "before_backup_verification",
        "after_backup_verification",
    ],
)
def test_backup_finalize_fault_is_idempotently_reentered(tmp_path, fault_point):
    wrapper, _local = write_wrapper(tmp_path, custom_camera=True)
    candidate = inspect_wrapper(wrapper)
    base, _target_paths = machine_data_paths(tmp_path)
    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )
    identity = target_identity()
    fault = FailOnceAt(fault_point)
    io = MachineDataMigration.MigrationFileOps(fault)

    with MachineDataLock.acquire_migration_lock(base, MACHINE_UUID) as lock:
        with pytest.raises(MachineDataMigration.MigrationError):
            MachineDataMigration.create_verified_backup(
                candidate,
                workspace=workspace,
                target_identity=identity,
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
                clock=fixed_clock,
            )
        backup = MachineDataMigration.create_verified_backup(
            candidate,
            workspace=workspace,
            target_identity=identity,
            acquired_lock=lock,
            io=io,
            policy=migration_policy(),
            clock=fixed_clock,
        )

    assert fault.triggered
    assert backup.archive_path.exists()
    assert json.loads(workspace.journal_path.read_text())["state"] == "backup_verified"


@pytest.mark.parametrize(
    "fault_point",
    ["before_journal_write", "after_journal_fsync", "after_journal_replace"],
)
def test_initial_journal_fault_is_idempotently_reentered(tmp_path, fault_point):
    wrapper, _local = write_wrapper(tmp_path, custom_camera=True)
    candidate = inspect_wrapper(wrapper)
    base, _target_paths = machine_data_paths(tmp_path)
    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )
    identity = target_identity()
    fault = FailOnceAt(fault_point)
    io = MachineDataMigration.MigrationFileOps(fault)

    with MachineDataLock.acquire_migration_lock(base, MACHINE_UUID) as lock:
        with pytest.raises(OSError):
            MachineDataMigration.create_verified_backup(
                candidate,
                workspace=workspace,
                target_identity=identity,
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
                clock=fixed_clock,
            )
        backup = MachineDataMigration.create_verified_backup(
            candidate,
            workspace=workspace,
            target_identity=identity,
            acquired_lock=lock,
            io=io,
            policy=migration_policy(),
            clock=fixed_clock,
        )

    assert fault.triggered
    assert backup.archive_path.exists()
    assert json.loads(workspace.journal_path.read_text())["state"] == "backup_verified"


def test_valid_stage_with_fault_after_manifest_replace_resumes_exactly(tmp_path):
    fault = FailOnceAt("after_staged_tree_manifest_replace")
    io = MachineDataMigration.MigrationFileOps(fault)
    candidate, base, target_paths, workspace, identity, lock, backup = _prepared_backup(
        tmp_path, io=io
    )
    try:
        with pytest.raises(MachineDataMigration.MigrationError) as error:
            MachineDataMigration.import_verified_candidate(
                candidate,
                backup,
                workspace=workspace,
                target_paths=target_paths,
                target_identity=identity,
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
                clock=fixed_clock,
            )
        assert error.value.code == "copy_failed"
        result = MachineDataMigration.import_verified_candidate(
            candidate,
            backup,
            workspace=workspace,
            target_paths=target_paths,
            target_identity=identity,
            acquired_lock=lock,
            io=io,
            policy=migration_policy(),
            clock=fixed_clock,
        )
    finally:
        lock.release()

    assert fault.triggered
    assert result.state == MachineDataMigration.MigrationState.COPIED_UNVERIFIED
    assert not base.active_machine_path.exists()


@pytest.mark.parametrize(
    "fault_point",
    [
        "before_staged_identity_write",
        "before_staged_candidate_evidence_write",
        "before_staged_backup_copy",
        "before_staged_receipt_write",
        "before_staged_tree_manifest_write",
    ],
)
def test_partial_ancillary_stage_fault_fails_closed(tmp_path, fault_point):
    fault = FailOnceAt(fault_point)
    io = MachineDataMigration.MigrationFileOps(fault)
    candidate, base, target_paths, workspace, identity, lock, backup = _prepared_backup(
        tmp_path, io=io
    )
    try:
        with pytest.raises(MachineDataMigration.MigrationError):
            MachineDataMigration.import_verified_candidate(
                candidate,
                backup,
                workspace=workspace,
                target_paths=target_paths,
                target_identity=identity,
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
                clock=fixed_clock,
            )
        with pytest.raises(MachineDataMigration.MigrationRecoveryRequired):
            MachineDataMigration.reconcile_migration(
                workspace=workspace,
                target_paths=target_paths,
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
                clock=fixed_clock,
            )
    finally:
        lock.release()

    assert fault.triggered
    assert workspace.staged_machine_root.exists()
    assert workspace.backup_path.exists()
    assert not target_paths.machine_root.exists()
    assert not base.active_machine_path.exists()


def test_fault_after_complete_stage_verification_resumes_exactly(tmp_path):
    fault = FailOnceAt("after_staged_copy_verification")
    io = MachineDataMigration.MigrationFileOps(fault)
    candidate, _base, target_paths, workspace, identity, lock, backup = _prepared_backup(
        tmp_path, io=io
    )
    try:
        with pytest.raises(MachineDataMigration.MigrationError):
            MachineDataMigration.import_verified_candidate(
                candidate,
                backup,
                workspace=workspace,
                target_paths=target_paths,
                target_identity=identity,
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
                clock=fixed_clock,
            )
        result = MachineDataMigration.import_verified_candidate(
            candidate,
            backup,
            workspace=workspace,
            target_paths=target_paths,
            target_identity=identity,
            acquired_lock=lock,
            io=io,
            policy=migration_policy(),
            clock=fixed_clock,
        )
    finally:
        lock.release()

    assert fault.triggered
    assert result.state == MachineDataMigration.MigrationState.COPIED_UNVERIFIED


def test_fault_after_target_verification_reconciles_without_recopy(tmp_path):
    fault = FailOnceAt("after_target_verification")
    io = MachineDataMigration.MigrationFileOps(fault)
    candidate, _base, target_paths, workspace, identity, lock, backup = _prepared_backup(
        tmp_path, io=io
    )
    try:
        with pytest.raises(OSError):
            MachineDataMigration.import_verified_candidate(
                candidate,
                backup,
                workspace=workspace,
                target_paths=target_paths,
                target_identity=identity,
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
                clock=fixed_clock,
            )
        result = MachineDataMigration.reconcile_migration(
            workspace=workspace,
            target_paths=target_paths,
            acquired_lock=lock,
            io=io,
            policy=migration_policy(),
            clock=fixed_clock,
        )
    finally:
        lock.release()

    assert fault.triggered
    assert result.reconciled
    assert target_paths.machine_root.exists()


def test_partial_stage_fault_fails_closed_and_preserves_evidence(tmp_path):
    fault = FailOnceAt("before_staged_member_write")
    io = MachineDataMigration.MigrationFileOps(fault)
    candidate, base, target_paths, workspace, identity, lock, backup = _prepared_backup(
        tmp_path, io=io
    )
    try:
        with pytest.raises(MachineDataMigration.MigrationError):
            MachineDataMigration.import_verified_candidate(
                candidate,
                backup,
                workspace=workspace,
                target_paths=target_paths,
                target_identity=identity,
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
                clock=fixed_clock,
            )
        with pytest.raises(MachineDataMigration.MigrationRecoveryRequired):
            MachineDataMigration.import_verified_candidate(
                candidate,
                backup,
                workspace=workspace,
                target_paths=target_paths,
                target_identity=identity,
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
                clock=fixed_clock,
            )
    finally:
        lock.release()

    assert workspace.staged_machine_root.exists()
    assert workspace.backup_path.exists()
    assert not target_paths.machine_root.exists()
    assert not base.active_machine_path.exists()


@pytest.mark.parametrize("journal_occurrence", [4, 5])
def test_late_journal_fault_reconciles_from_exact_stage_or_target(tmp_path, journal_occurrence):
    fault = FailNthAt("after_journal_replace", journal_occurrence)
    io = MachineDataMigration.MigrationFileOps(fault)
    candidate, _base, target_paths, workspace, identity, lock, backup = _prepared_backup(
        tmp_path, io=io
    )
    try:
        with pytest.raises(OSError):
            MachineDataMigration.import_verified_candidate(
                candidate,
                backup,
                workspace=workspace,
                target_paths=target_paths,
                target_identity=identity,
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
                clock=fixed_clock,
            )
        result = MachineDataMigration.reconcile_migration(
            workspace=workspace,
            target_paths=target_paths,
            acquired_lock=lock,
            io=io,
            policy=migration_policy(),
            clock=fixed_clock,
        )
    finally:
        lock.release()

    assert fault.triggered
    assert result.reconciled
    assert target_paths.machine_root.exists()
    assert not workspace.root.exists()


@pytest.mark.parametrize("fault_point", ["before_workspace_cleanup", "after_workspace_cleanup"])
def test_workspace_cleanup_fault_leaves_exact_target_reconcilable(tmp_path, fault_point):
    fault = FailOnceAt(fault_point)
    io = MachineDataMigration.MigrationFileOps(fault)
    candidate, _base, target_paths, workspace, identity, lock, backup = _prepared_backup(
        tmp_path, io=io
    )
    try:
        with pytest.raises(OSError):
            MachineDataMigration.import_verified_candidate(
                candidate,
                backup,
                workspace=workspace,
                target_paths=target_paths,
                target_identity=identity,
                acquired_lock=lock,
                io=io,
                policy=migration_policy(),
                clock=fixed_clock,
            )
        result = MachineDataMigration.reconcile_migration(
            workspace=workspace,
            target_paths=target_paths,
            acquired_lock=lock,
            io=io,
            policy=migration_policy(),
            clock=fixed_clock,
        )
    finally:
        lock.release()

    assert fault.triggered
    assert result.reconciled
    assert target_paths.machine_root.exists()
    assert not workspace.root.exists()


def test_malformed_journal_transition_is_recovery_required_without_mutation(tmp_path):
    _candidate, base, target_paths, workspace, _identity, lock, _backup = _prepared_backup(
        tmp_path
    )
    payload = json.loads(workspace.journal_path.read_text())
    payload["state"] = "copied_unverified"
    workspace.journal_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        with pytest.raises(MachineDataMigration.MigrationRecoveryRequired):
            MachineDataMigration.reconcile_migration(
                workspace=workspace,
                target_paths=target_paths,
                acquired_lock=lock,
                policy=migration_policy(),
            )
    finally:
        lock.release()

    assert workspace.backup_path.exists()
    assert not target_paths.machine_root.exists()
    assert not base.active_machine_path.exists()


def test_published_target_tampering_requires_recovery_and_is_not_repaired(tmp_path):
    candidate, _base, target_paths, workspace, identity, lock, backup = _prepared_backup(
        tmp_path
    )
    try:
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
    finally:
        lock.release()
    locations = target_paths.config_root / "Locations.json"
    tampered = locations.read_bytes() + b"\n"
    locations.write_bytes(tampered)

    with MachineDataLock.acquire_migration_lock(
        target_paths.base, MACHINE_UUID
    ) as second_lock:
        with pytest.raises(MachineDataMigration.MigrationRecoveryRequired):
            MachineDataMigration.reconcile_migration(
                workspace=workspace,
                target_paths=target_paths,
                acquired_lock=second_lock,
                policy=migration_policy(),
            )

    assert locations.read_bytes() == tampered


def test_existing_unrelated_target_is_never_overlaid(tmp_path):
    wrapper, _local = write_wrapper(tmp_path, custom_camera=True)
    candidate = inspect_wrapper(wrapper)
    base, target_paths = machine_data_paths(tmp_path)
    target_paths.machine_root.mkdir(parents=True)
    marker = target_paths.machine_root / "do-not-overwrite.txt"
    marker.write_text("keep", encoding="utf-8")
    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )

    with MachineDataLock.acquire_migration_lock(base, MACHINE_UUID) as lock:
        with pytest.raises(MachineDataMigration.MigrationRecoveryRequired):
            MachineDataMigration.reconcile_migration(
                workspace=workspace,
                target_paths=target_paths,
                acquired_lock=lock,
                policy=migration_policy(),
            )

    assert marker.read_text(encoding="utf-8") == "keep"


def test_illegal_state_regression_is_rejected():
    with pytest.raises(MachineDataMigration.MigrationRecoveryRequired):
        MachineDataMigration.validate_state_transition(
            MachineDataMigration.MigrationState.BACKUP_VERIFIED,
            MachineDataMigration.MigrationState.SOURCE_VALIDATED,
        )


def test_workspace_paths_are_uuid_scoped_contained_and_side_effect_free(tmp_path):
    base, _target_paths = machine_data_paths(tmp_path)

    workspace = MachineDataMigration.build_migration_workspace_paths(
        base, MACHINE_UUID, MIGRATION_ID
    )

    assert workspace.root == (
        base.root / "migration_work" / MACHINE_UUID / MIGRATION_ID
    ).resolve()
    assert workspace.journal_path == workspace.root / "journal.json"
    assert workspace.backup_path == workspace.root / "source_backup.zip"
    assert workspace.staged_machine_root == workspace.root / "staged_machine"
    assert not base.root.exists()


def test_same_uuid_lock_contends_immediately_and_different_uuid_is_independent(tmp_path):
    base, _target_paths = machine_data_paths(tmp_path)
    other_uuid = "00000000-0000-0000-0000-000000000099"

    first = MachineDataLock.acquire_migration_lock(base, MACHINE_UUID)
    try:
        with pytest.raises(MachineDataLock.MigrationLockUnavailable):
            MachineDataLock.acquire_migration_lock(base, MACHINE_UUID)
        other = MachineDataLock.acquire_migration_lock(base, other_uuid)
        other.release()
    finally:
        first.release()


def test_lock_release_on_context_exception_allows_reacquisition(tmp_path):
    base, _target_paths = machine_data_paths(tmp_path)

    with pytest.raises(RuntimeError):
        with MachineDataLock.acquire_migration_lock(base, MACHINE_UUID):
            raise RuntimeError("synthetic")

    second = MachineDataLock.acquire_migration_lock(base, MACHINE_UUID)
    second.release()


def test_receipt_parser_rejects_any_activation_flag(tmp_path):
    candidate, _base, target_paths, workspace, identity, lock, backup = _prepared_backup(
        tmp_path
    )
    try:
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
    finally:
        lock.release()
    receipt_path = target_paths.migration_receipt_path
    payload = json.loads(receipt_path.read_text())
    payload["activation_authorized"] = True
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    with MachineDataLock.acquire_migration_lock(
        target_paths.base, MACHINE_UUID
    ) as second_lock:
        with pytest.raises(MachineDataMigration.MigrationRecoveryRequired):
            MachineDataMigration.reconcile_migration(
                workspace=workspace,
                target_paths=target_paths,
                acquired_lock=second_lock,
                policy=migration_policy(),
            )

    assert result.receipt.activation_authorized is False
