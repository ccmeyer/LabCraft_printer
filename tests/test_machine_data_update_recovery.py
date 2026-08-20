import json

import pytest

from MachineData import require_authorized_active_machine
from MachineDataBootstrap import BootstrapState, MachineDataBootstrap
from MachineDataCompatibility import (
    LegacyCompatibilityError,
    create_legacy_compatibility_export,
    load_compatibility_catalog,
    resolve_legacy_session,
)
from MachineDataLock import acquire_configuration_lock
from MachineDataUpdate import UpdateTarget, begin_update_preservation, build_update_launch_binding
from tests.test_machine_data_update_preservation import CONTRACT, SOURCE_COMMIT, _active_context


def _completed_legacy_session(tmp_path, request_id: str):
    repo = tmp_path / "checkout"
    repo.mkdir()
    context = _active_context(tmp_path)
    base = context.paths.base
    paths = context.paths
    binding = build_update_launch_binding(
        context,
        source_app_version="v1.3.0-rc.2",
        source_commit=SOURCE_COMMIT,
        request_id=request_id,
    )
    context.close()
    profile = next(item for item in load_compatibility_catalog().profiles if item.tag == "v1.3.0-rc.1")
    target = UpdateTarget(
        operation="rollback",
        version=profile.tag,
        tag=profile.tag,
        commit=profile.commit_sha,
        update_source="online",
        release_manifest_sha256=profile.release_manifest_sha256,
        machine_data_contract=CONTRACT,
    )
    prepared = begin_update_preservation(binding, target, repo_root=repo)
    create_legacy_compatibility_export(
        prepared,
        repo_root=repo,
        operator="Support Operator",
        reason="Legacy return recovery test",
        machine_id_confirmation=binding.machine_id,
        service_record_reference="CASE-RECOVERY",
        firmware_attestation="Reviewed firmware pairing",
    )
    prepared.record_git_result(
        before_commit=SOURCE_COMMIT,
        after_commit=profile.commit_sha,
        command=("git", "reset", "--hard", profile.tag),
    )
    prepared.verify_after()
    prepared.authorize_relaunch()
    prepared.close()
    return repo, base, paths


def test_exact_legacy_return_reauthorizes_without_copying_canonical_data(tmp_path):
    _repo, base, paths = _completed_legacy_session(
        tmp_path,
        "00000000-0000-0000-0000-000000000084",
    )
    before = (paths.config_root / "Locations.json").read_bytes()
    bootstrap = MachineDataBootstrap(
        base,
        app_version="v1.3.0-rc.2",
        app_commit=SOURCE_COMMIT,
        release_contract=CONTRACT,
    )

    assert bootstrap.inspect().state is BootstrapState.READY
    context = bootstrap.open_ready()
    try:
        assert not paths.legacy_session_path.exists()
        assert (paths.config_root / "Locations.json").read_bytes() == before
        assert context.deployment_anchor["authorization_kind"] == "legacy_return_unchanged"
    finally:
        context.close()


def test_legacy_camera_change_blocks_before_authorized_context(tmp_path):
    repo, base, paths = _completed_legacy_session(
        tmp_path,
        "00000000-0000-0000-0000-000000000083",
    )
    canonical_before = (paths.config_root / "Locations.json").read_bytes()
    legacy_locations_path = repo / "local" / "Locations.json"
    legacy = json.loads(legacy_locations_path.read_text(encoding="utf-8"))
    camera_key = next(key for key in legacy if key.casefold() == "camera")
    legacy[camera_key]["Y"] += 5000
    legacy_locations_path.write_text(json.dumps(legacy), encoding="utf-8")

    inspection = MachineDataBootstrap(
        base,
        app_version="v1.3.0-rc.2",
        app_commit=SOURCE_COMMIT,
        release_contract=CONTRACT,
    ).inspect()

    assert inspection.state is BootstrapState.RECOVERY_REQUIRED
    assert "Legacy checkout-local data differs" in inspection.issues[0].message
    assert (paths.config_root / "Locations.json").read_bytes() == canonical_before


def test_explicit_keep_canonical_backs_up_conflict_and_reauthorizes(tmp_path):
    repo, _base, paths = _completed_legacy_session(
        tmp_path,
        "00000000-0000-0000-0000-000000000082",
    )
    canonical_before = (paths.config_root / "Locations.json").read_bytes()
    legacy_locations_path = repo / "local" / "Locations.json"
    legacy = json.loads(legacy_locations_path.read_text(encoding="utf-8"))
    camera_key = next(key for key in legacy if key.casefold() == "camera")
    legacy[camera_key]["Y"] += 5000
    legacy_locations_path.write_text(json.dumps(legacy), encoding="utf-8")
    active = require_authorized_active_machine(
        json.loads(paths.base.active_machine_path.read_text(encoding="utf-8"))
    )
    lock = acquire_configuration_lock(paths)
    try:
        with pytest.raises(LegacyCompatibilityError, match="explicit resolution"):
            resolve_legacy_session(
                paths,
                active,
                lock,
                app_version="v1.3.0-rc.2",
                app_commit=SOURCE_COMMIT,
                release_contract=CONTRACT,
            )
        anchor = resolve_legacy_session(
            paths,
            active,
            lock,
            app_version="v1.3.0-rc.2",
            app_commit=SOURCE_COMMIT,
            release_contract=CONTRACT,
            keep_canonical=True,
            operator="Support Operator",
            reason="Retain verified canonical coordinates",
            service_record_reference="CASE-KEEP-CANONICAL",
        )
    finally:
        lock.release()

    transaction = paths.update_transactions_root / "00000000-0000-0000-0000-000000000082"
    assert (transaction / "backup" / "legacy_return_local.zip").is_file()
    assert (transaction / "legacy" / "comparison.json").is_file()
    assert (transaction / "legacy" / "resolution.json").is_file()
    assert anchor["authorization_kind"] == "keep_canonical"
    assert (paths.config_root / "Locations.json").read_bytes() == canonical_before
