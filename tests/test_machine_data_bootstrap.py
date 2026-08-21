import json

import pytest

import MachineDataBootstrap
import MachineDataMigration
from tests.machine_data_migration_helpers import (
    FIXED_TIME,
    MACHINE_ID,
    MACHINE_UUID,
    MIGRATION_ID,
    inspect_wrapper,
    machine_data_paths,
    migration_policy,
    publish_candidate,
    write_wrapper,
)


ACTIVATION_ID = "00000000-0000-0000-0000-000000000003"


def _bootstrap(base, *, uuid_values=()):
    values = iter(uuid_values)
    return MachineDataBootstrap.MachineDataBootstrap(
        base,
        app_version="v1.3.0-rc.2",
        app_commit="test-commit",
        migration_policy=migration_policy(),
        clock=lambda: FIXED_TIME,
        uuid_factory=lambda: next(values),
    )


def test_development_bootstrap_explicitly_disables_release_deployment_gate(tmp_path):
    base, _paths = machine_data_paths(tmp_path)
    bootstrap = MachineDataBootstrap.MachineDataBootstrap(
        base,
        app_version="v1.3.0-rc.4",
        app_commit="development-commit",
        release_contract={
            "preservation_contract": "labcraft.machine_data_update.v1",
            "data_schema_version": 1,
            "transition": "none",
            "transition_id": None,
        },
        deployment_gate_enabled=False,
    )

    assert bootstrap.deployment_gate_enabled is False
    assert bootstrap.release_contract is None


@pytest.mark.parametrize("cohort", ("v1.2.0-rc.6", "v1.3.0-rc.1"))
def test_first_start_migrates_activates_and_reuses_from_second_checkout(
    tmp_path, cohort
):
    wrapper, _local = write_wrapper(
        tmp_path / "source", cohort=cohort, custom_camera=True
    )
    candidate = inspect_wrapper(wrapper)
    base, _unused_paths = machine_data_paths(tmp_path)
    bootstrap = _bootstrap(base, uuid_values=(MIGRATION_ID,))
    camera = candidate.safety_snapshot["locations"]["camera"]

    context = bootstrap.bootstrap_from_candidate(
        MachineDataBootstrap.BootstrapSubmission(
            selection=MachineDataMigration.CandidateSelection(
                MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_WRAPPER,
                wrapper,
                "preserved source",
            ),
            machine_id=MACHINE_ID,
            machine_uuid=MACHINE_UUID,
            activation_id=ACTIVATION_ID,
            operator="Test Operator",
            source_reason="Preserved pre-update local",
            camera_confirmation=camera,
        )
    )
    try:
        assert context.active_machine.authorizes_production
        assert context.paths.config_root.parent == context.paths.machine_root
        assert context.settings["HARDWARE_PROFILE"] == "current"
        assert bootstrap.inspect().state is MachineDataBootstrap.BootstrapState.READY
        assert not (
            base.activation_work_root / MACHINE_UUID / ACTIVATION_ID
        ).exists()
        with pytest.raises(MachineDataBootstrap.BootstrapError, match="lock"):
            bootstrap.open_ready()
    finally:
        context.close()

    second_checkout = _bootstrap(base)
    reused = second_checkout.open_ready()
    try:
        assert reused.paths.machine_uuid == MACHINE_UUID
        assert reused.active_machine == context.active_machine
    finally:
        reused.close()


def test_completed_m2_workspace_absence_can_resume_activation(tmp_path):
    base, paths, _identity, candidate, _result = publish_candidate(tmp_path)
    assert not (base.root / "migration_work" / MACHINE_UUID / MIGRATION_ID).exists()
    bootstrap = _bootstrap(base)
    inspection = bootstrap.inspect()
    assert inspection.state is MachineDataBootstrap.BootstrapState.MIGRATION_RESUME_REQUIRED

    context = bootstrap.activate_published(
        MachineDataBootstrap.PublishedActivationSubmission(
            machine_uuid=MACHINE_UUID,
            activation_id=ACTIVATION_ID,
            operator="Test Operator",
            source_reason="Published M2 source",
            camera_confirmation=candidate.safety_snapshot["locations"]["camera"],
        )
    )
    try:
        assert context.paths == paths
        assert bootstrap.inspect().state is MachineDataBootstrap.BootstrapState.READY
    finally:
        context.close()


def test_unclassified_source_blocks_activation_without_deleting_publication(tmp_path):
    wrapper, _local = write_wrapper(
        tmp_path / "source",
        custom_camera=True,
        extra_files={"mystery/camera_override.json": "{}\n"},
    )
    candidate = inspect_wrapper(wrapper)
    base, _unused = machine_data_paths(tmp_path)
    bootstrap = _bootstrap(base, uuid_values=(MIGRATION_ID,))

    with pytest.raises(MachineDataBootstrap.BootstrapError, match="Unreviewed"):
        bootstrap.bootstrap_from_candidate(
            MachineDataBootstrap.BootstrapSubmission(
                selection=MachineDataMigration.CandidateSelection(
                    MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_WRAPPER,
                    wrapper,
                ),
                machine_id=MACHINE_ID,
                machine_uuid=MACHINE_UUID,
                activation_id=ACTIVATION_ID,
                operator="Operator",
                source_reason="backup",
                camera_confirmation=candidate.safety_snapshot["locations"]["camera"],
            )
        )

    paths = MachineDataBootstrap.build_machine_data_paths(base, MACHINE_UUID)
    assert paths.machine_root.exists()
    assert not base.active_machine_path.exists()
    assert bootstrap.inspect().state is MachineDataBootstrap.BootstrapState.MIGRATION_RESUME_REQUIRED


def test_active_binding_tamper_requires_recovery(tmp_path):
    base, _paths, _identity, candidate, _result = publish_candidate(tmp_path)
    bootstrap = _bootstrap(base)
    context = bootstrap.activate_published(
        MachineDataBootstrap.PublishedActivationSubmission(
            machine_uuid=MACHINE_UUID,
            activation_id=ACTIVATION_ID,
            operator="Operator",
            source_reason="backup",
            camera_confirmation=candidate.safety_snapshot["locations"]["camera"],
        )
    )
    context.close()
    payload = json.loads(base.active_machine_path.read_text(encoding="utf-8"))
    payload["activation_receipt_sha256"] = "0" * 64
    base.active_machine_path.write_text(json.dumps(payload), encoding="utf-8")

    inspection = bootstrap.inspect()
    assert inspection.state is MachineDataBootstrap.BootstrapState.RECOVERY_REQUIRED
    with pytest.raises(MachineDataBootstrap.BootstrapError, match="bindings"):
        bootstrap.open_ready()


def test_version1_pointer_never_authorizes_production(tmp_path):
    base, _paths = machine_data_paths(tmp_path)
    base.root.mkdir(parents=True)
    base.active_machine_path.write_text(
        json.dumps(
            {
                "schema_name": "labcraft.active_machine",
                "schema_version": 1,
                "machine_id": MACHINE_ID,
                "machine_uuid": MACHINE_UUID,
                "selected_at_utc": FIXED_TIME,
                "selection_source": "migration",
            }
        ),
        encoding="utf-8",
    )

    assert _bootstrap(base).inspect().state is MachineDataBootstrap.BootstrapState.RECOVERY_REQUIRED
