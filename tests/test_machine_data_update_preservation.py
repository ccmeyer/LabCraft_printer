import json
from pathlib import Path

import pytest

import MachineDataBootstrap
import MachineDataMigration
from MachineDataArchive import DurableFileOps, sha256_file
from MachineDataUpdate import (
    MachineDataUpdateError,
    TRANSITION_NONE,
    UPDATE_CONTRACT_NAME,
    UpdateTarget,
    begin_update_preservation,
    build_update_launch_binding,
    validate_or_enroll_deployment,
    verify_update_backup,
)
from MachineDataSchemaTransition import (
    SYNTHETIC_REFORMAT_TRANSITION_ID,
    complete_prepared_schema_transition,
)
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
SOURCE_COMMIT = "1" * 40
TARGET_COMMIT = "2" * 40
CONTRACT = {
    "preservation_contract": UPDATE_CONTRACT_NAME,
    "data_schema_version": 1,
    "transition": TRANSITION_NONE,
    "transition_id": None,
}


def _active_context(tmp_path):
    wrapper, _ = write_wrapper(
        tmp_path / "source", cohort="v1.3.0-rc.1", custom_camera=True
    )
    candidate = inspect_wrapper(wrapper)
    base, _ = machine_data_paths(tmp_path)
    bootstrap = MachineDataBootstrap.MachineDataBootstrap(
        base,
        app_version="v1.3.0-rc.2",
        app_commit=SOURCE_COMMIT,
        migration_policy=migration_policy(),
        clock=lambda: FIXED_TIME,
        uuid_factory=lambda: MIGRATION_ID,
    )
    context = bootstrap.bootstrap_from_candidate(
        MachineDataBootstrap.BootstrapSubmission(
            selection=MachineDataMigration.CandidateSelection(
                MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_WRAPPER,
                wrapper,
            ),
            machine_id=MACHINE_ID,
            machine_uuid=MACHINE_UUID,
            activation_id=ACTIVATION_ID,
            operator="Update Test",
            source_reason="Verified source",
            camera_confirmation=candidate.safety_snapshot["locations"]["camera"],
        )
    )
    validate_or_enroll_deployment(
        context.paths,
        context.active_machine,
        context.configuration_lock,
        app_version="v1.3.0-rc.2",
        app_commit=SOURCE_COMMIT,
        release_contract=CONTRACT,
        clock=lambda: FIXED_TIME,
    )
    return context


def _prepared(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    context = _active_context(tmp_path)
    binding = build_update_launch_binding(
        context,
        source_app_version="v1.3.0-rc.2",
        source_commit=SOURCE_COMMIT,
        request_id="00000000-0000-0000-0000-000000000099",
    )
    paths = context.paths
    context.close()
    target = UpdateTarget(
        operation="update",
        version="v1.3.0-rc.3",
        tag="v1.3.0-rc.3",
        commit=TARGET_COMMIT,
        update_source="online",
        release_manifest_sha256="3" * 64,
        machine_data_contract=CONTRACT,
    )
    return repo, paths, begin_update_preservation(binding, target, repo_root=repo)


def test_verified_backup_precedes_git_and_authorizes_exact_relaunch(tmp_path):
    _repo, paths, prepared = _prepared(tmp_path)
    try:
        assert prepared.archive_path.is_file()
        archive_sha, manifest = verify_update_backup(prepared.archive_path)
        assert archive_sha == prepared.archive_sha256
        assert manifest["snapshot"]["fingerprint"] == prepared.snapshot.fingerprint
        assert (prepared.transaction_root / "03_backup_verification.json").is_file()

        prepared.record_git_result(
            before_commit=SOURCE_COMMIT,
            after_commit=TARGET_COMMIT,
            command=("git", "merge", "--ff-only", "v1.3.0-rc.3"),
        )
        prepared.verify_after()
        terminal = prepared.authorize_relaunch()
        assert terminal.is_file()
        latest = json.loads(paths.latest_update_result_path.read_text(encoding="utf-8"))
        assert latest["relaunch_authorized"] is True
        anchor = json.loads(paths.deployment_anchor_path.read_text(encoding="utf-8"))
        assert anchor["app_commit"] == TARGET_COMMIT
        assert anchor["update_id"] == prepared.update_id
    finally:
        prepared.close()


def test_no_schema_post_check_rejects_one_camera_byte_change(tmp_path):
    _repo, paths, prepared = _prepared(tmp_path)
    try:
        prepared.record_git_result(
            before_commit=SOURCE_COMMIT,
            after_commit=TARGET_COMMIT,
            command=("git", "merge"),
        )
        locations_path = paths.config_root / "Locations.json"
        locations = json.loads(locations_path.read_text(encoding="utf-8"))
        camera_key = next(key for key in locations if key.casefold() == "camera")
        locations[camera_key]["Y"] += 1
        locations_path.write_text(json.dumps(locations), encoding="utf-8")
        with pytest.raises(MachineDataUpdateError, match="machine data failed"):
            prepared.verify_after()
        prepared.fail("post-check failed", recovery_required=True)
        latest = json.loads(paths.latest_update_result_path.read_text(encoding="utf-8"))
        assert latest["recovery_required"] is True
        assert latest["relaunch_authorized"] is False
    finally:
        prepared.close()


def test_active_pointer_binding_change_blocks_before_transaction(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    context = _active_context(tmp_path)
    binding = build_update_launch_binding(
        context,
        source_app_version="v1.3.0-rc.2",
        source_commit=SOURCE_COMMIT,
    )
    paths = context.paths
    context.close()
    pointer = json.loads(paths.base.active_machine_path.read_text(encoding="utf-8"))
    pointer["selected_at_utc"] = "2026-08-21T00:00:00Z"
    paths.base.active_machine_path.write_text(json.dumps(pointer), encoding="utf-8")
    target = UpdateTarget(
        operation="update",
        version="v1.3.0-rc.3",
        tag="v1.3.0-rc.3",
        commit=TARGET_COMMIT,
        update_source="online",
        release_manifest_sha256="3" * 64,
        machine_data_contract=CONTRACT,
    )
    with pytest.raises(MachineDataUpdateError, match="pointer hash"):
        begin_update_preservation(binding, target, repo_root=repo)
    assert not paths.update_transactions_root.exists()


def test_backup_failure_records_no_git_stage_and_releases_locks(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    context = _active_context(tmp_path)
    binding = build_update_launch_binding(
        context,
        source_app_version="v1.3.0-rc.2",
        source_commit=SOURCE_COMMIT,
        request_id="00000000-0000-0000-0000-000000000098",
    )
    paths = context.paths
    context.close()
    target = UpdateTarget(
        operation="update",
        version="v1.3.0-rc.3",
        tag="v1.3.0-rc.3",
        commit=TARGET_COMMIT,
        update_source="online",
        release_manifest_sha256="3" * 64,
        machine_data_contract=CONTRACT,
    )

    def fail_backup(name, _path):
        if name == "before_update_backup_write":
            raise OSError("simulated backup failure")

    with pytest.raises(OSError, match="simulated backup"):
        begin_update_preservation(
            binding,
            target,
            repo_root=repo,
            io=DurableFileOps(fault_hook=fail_backup),
        )
    transaction = paths.update_transactions_root / binding.request_id
    assert not (transaction / "04_git_result.json").exists()
    # A subsequent attempt with a new request proves both locks were released.
    retry_binding = build_update_launch_binding(
        type("Context", (), {
            "paths": paths,
            "active_machine": context.active_machine,
            "identity": context.identity,
        })(),
        source_app_version="v1.3.0-rc.2",
        source_commit=SOURCE_COMMIT,
        request_id="00000000-0000-0000-0000-000000000097",
    )
    retry = begin_update_preservation(retry_binding, target, repo_root=repo)
    retry.fail("test close")
    retry.close()


def test_declared_target_transition_is_hardware_free_audited_and_authorized(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    context = _active_context(tmp_path)
    binding = build_update_launch_binding(
        context,
        source_app_version="v1.3.0-rc.2",
        source_commit=SOURCE_COMMIT,
        request_id="00000000-0000-0000-0000-000000000096",
    )
    paths = context.paths
    context.close()
    transition_contract = {
        **CONTRACT,
        "transition": "bootstrap_recovery",
        "transition_id": SYNTHETIC_REFORMAT_TRANSITION_ID,
    }
    target = UpdateTarget(
        operation="update",
        version="v1.3.0-rc.3",
        tag="v1.3.0-rc.3",
        commit=TARGET_COMMIT,
        update_source="online",
        release_manifest_sha256="3" * 64,
        machine_data_contract=transition_contract,
    )
    before_bytes = (paths.config_root / "Locations.json").read_bytes()
    prepared = begin_update_preservation(binding, target, repo_root=repo)
    try:
        prepared.record_git_result(
            before_commit=SOURCE_COMMIT,
            after_commit=TARGET_COMMIT,
            command=("git", "merge", "--ff-only", target.tag),
        )
        prepared.verify_after()
        terminal = complete_prepared_schema_transition(prepared)
        assert terminal.is_file()
        assert (prepared.transaction_root / "05b_schema_transition_verification.json").is_file()
        assert (paths.config_root / "Locations.json").read_bytes() != before_bytes
        assert json.loads((paths.config_root / "Locations.json").read_text(encoding="utf-8")) == json.loads(
            before_bytes.decode("utf-8")
        )
        anchor = json.loads(paths.deployment_anchor_path.read_text(encoding="utf-8"))
        assert anchor["authorization_kind"] == "schema_transition"
        assert anchor["app_commit"] == TARGET_COMMIT
    finally:
        prepared.close()


def test_unknown_target_transition_remains_recovery_only(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    context = _active_context(tmp_path)
    binding = build_update_launch_binding(
        context,
        source_app_version="v1.3.0-rc.2",
        source_commit=SOURCE_COMMIT,
        request_id="00000000-0000-0000-0000-000000000095",
    )
    paths = context.paths
    context.close()
    target = UpdateTarget(
        operation="update",
        version="v1.3.0-rc.3",
        tag="v1.3.0-rc.3",
        commit=TARGET_COMMIT,
        update_source="online",
        release_manifest_sha256="3" * 64,
        machine_data_contract={
            **CONTRACT,
            "transition": "bootstrap_recovery",
            "transition_id": "unregistered.transition.v1",
        },
    )
    prepared = begin_update_preservation(binding, target, repo_root=repo)
    try:
        prepared.record_git_result(
            before_commit=SOURCE_COMMIT,
            after_commit=TARGET_COMMIT,
            command=("git", "merge", "--ff-only", target.tag),
        )
        prepared.verify_after()
        with pytest.raises(MachineDataUpdateError, match="No reviewed target-side adapter"):
            complete_prepared_schema_transition(prepared)
        prepared.fail("adapter missing", recovery_required=True)
        latest = json.loads(paths.latest_update_result_path.read_text(encoding="utf-8"))
        assert latest["relaunch_authorized"] is False
        assert latest["recovery_required"] is True
    finally:
        prepared.close()
