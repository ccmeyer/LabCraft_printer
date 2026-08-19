import pytest

import MachineDataArchive
import MachineDataBootstrap
import MachineDataMigration
from tests.machine_data_migration_helpers import (
    FIXED_TIME,
    MACHINE_ID,
    MACHINE_UUID,
    machine_data_paths,
    publish_candidate,
    write_wrapper,
)


ACTIVATION_ID = "00000000-0000-0000-0000-000000000003"


class InjectOnce:
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint
        self.triggered = False

    def __call__(self, name, _path):
        if name == self.checkpoint and not self.triggered:
            self.triggered = True
            raise OSError(f"injected {name}")


def _bootstrap(base, *, fault_hook=None):
    return MachineDataBootstrap.MachineDataBootstrap(
        base,
        app_version="v1.3.0-rc.2",
        app_commit="test-commit",
        clock=lambda: FIXED_TIME,
        uuid_factory=lambda: ACTIVATION_ID,
        io=MachineDataArchive.DurableFileOps(fault_hook=fault_hook),
    )


@pytest.mark.parametrize(
    "checkpoint",
    [
        "after_verification_replace",
        "after_activation_receipt_replace",
    ],
)
def test_activation_sidecar_interruptions_resume_without_rewriting_m2(tmp_path, checkpoint):
    base, paths, _identity, candidate, result = publish_candidate(tmp_path)
    m2_receipt_before = paths.migration_receipt_path.read_bytes()
    m2_manifest_before = paths.migration_tree_manifest_path.read_bytes()
    fault = InjectOnce(checkpoint)

    with pytest.raises(OSError, match="injected"):
        _bootstrap(base, fault_hook=fault).activate_published(
            MachineDataBootstrap.PublishedActivationSubmission(
                machine_uuid=MACHINE_UUID,
                activation_id=ACTIVATION_ID,
                operator="Operator",
                source_reason="preserved backup",
                camera_confirmation=candidate.safety_snapshot["locations"]["camera"],
            )
        )

    assert fault.triggered
    assert not base.active_machine_path.exists()
    assert paths.migration_receipt_path.read_bytes() == m2_receipt_before
    assert paths.migration_tree_manifest_path.read_bytes() == m2_manifest_before
    inspection = _bootstrap(base).inspect()
    assert inspection.state is MachineDataBootstrap.BootstrapState.ACTIVATION_RESUME_REQUIRED

    resumed = _bootstrap(base).activate_published(
        MachineDataBootstrap.PublishedActivationSubmission(
            machine_uuid=MACHINE_UUID,
            operator="Operator",
            source_reason="preserved backup",
            camera_confirmation=candidate.safety_snapshot["locations"]["camera"],
        )
    )
    try:
        assert resumed.active_machine.migration_id == result.receipt.migration_id
    finally:
        resumed.close()


def test_interrupt_after_pointer_replace_is_ready_not_remigrated(tmp_path):
    base, paths, _identity, candidate, _result = publish_candidate(tmp_path)
    fault = InjectOnce("after_active_machine_replace")

    with pytest.raises(OSError, match="injected"):
        _bootstrap(base, fault_hook=fault).activate_published(
            MachineDataBootstrap.PublishedActivationSubmission(
                machine_uuid=MACHINE_UUID,
                activation_id=ACTIVATION_ID,
                operator="Operator",
                source_reason="preserved backup",
                camera_confirmation=candidate.safety_snapshot["locations"]["camera"],
            )
        )

    assert base.active_machine_path.exists()
    assert _bootstrap(base).inspect().state is MachineDataBootstrap.BootstrapState.READY
    context = _bootstrap(base).open_ready()
    context.close()
    assert paths.migration_receipt_path.exists()


def test_partial_unknown_sidecar_never_gets_deleted_or_ignored(tmp_path):
    base, paths, _identity, _candidate, _result = publish_candidate(tmp_path)
    unknown = paths.metadata_root / "verification.partial"
    unknown.write_text("preserve evidence\n", encoding="utf-8")

    inspection = _bootstrap(base).inspect()

    assert inspection.state is MachineDataBootstrap.BootstrapState.RECOVERY_REQUIRED
    assert unknown.read_text(encoding="utf-8") == "preserve evidence\n"
    assert not base.active_machine_path.exists()


def test_identity_assignment_interruption_reuses_same_uuid_on_reselection(tmp_path):
    wrapper, _local = write_wrapper(tmp_path / "source", custom_camera=True)
    empty_base, _paths = machine_data_paths(tmp_path / "empty-base")
    selection = MachineDataMigration.CandidateSelection(
        MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_WRAPPER,
        wrapper,
        "pre-update backup",
    )
    candidate = MachineDataMigration.inspect_candidate(
        selection, clock=lambda: FIXED_TIME
    )
    ids = iter(
        (
            MACHINE_UUID,
            ACTIVATION_ID,
            "00000000-0000-0000-0000-000000000004",
        )
    )
    fault = InjectOnce("before_activation_journal_write")
    first = MachineDataBootstrap.MachineDataBootstrap(
        empty_base,
        app_version="v1.3.0-rc.2",
        app_commit="test-commit",
        clock=lambda: FIXED_TIME,
        uuid_factory=lambda: next(ids),
        io=MachineDataArchive.DurableFileOps(fault_hook=fault),
    )
    submission = MachineDataBootstrap.BootstrapSubmission(
        selection=selection,
        machine_id=MACHINE_ID,
        operator="Operator",
        source_reason="pre-update backup",
        camera_confirmation=candidate.safety_snapshot["locations"]["camera"],
    )

    with pytest.raises(OSError, match="injected"):
        first.bootstrap_from_candidate(submission)

    inspection = _bootstrap(empty_base).inspect()
    assert inspection.state is MachineDataBootstrap.BootstrapState.CANDIDATE_SELECTION_REQUIRED
    assert inspection.issues[0].code == "identity_assignment_resume"

    def unexpected_uuid():
        raise AssertionError("resume must reuse the durable identity and operation IDs")

    resumed_bootstrap = MachineDataBootstrap.MachineDataBootstrap(
        empty_base,
        app_version="v1.3.0-rc.2",
        app_commit="test-commit",
        clock=lambda: FIXED_TIME,
        uuid_factory=unexpected_uuid,
    )
    context = resumed_bootstrap.bootstrap_from_candidate(submission)
    try:
        assert context.identity.machine_uuid == MACHINE_UUID
        assert context.active_machine.activation_id == ACTIVATION_ID
        assert context.active_machine.migration_id == (
            "00000000-0000-0000-0000-000000000004"
        )
    finally:
        context.close()
