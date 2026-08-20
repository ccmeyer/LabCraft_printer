import json

import pytest

from MachineDataCompatibility import (
    LegacyCompatibilityError,
    compare_legacy_session,
    create_legacy_compatibility_export,
    load_compatibility_catalog,
)
from MachineDataUpdate import UpdateTarget, begin_update_preservation, build_update_launch_binding
from tests.test_machine_data_update_preservation import (
    CONTRACT,
    SOURCE_COMMIT,
    _active_context,
)


def test_catalog_binds_all_supported_exact_legacy_tags():
    catalog = load_compatibility_catalog()
    by_tag = {profile.tag: profile for profile in catalog.profiles}
    assert set(by_tag) == {"v1.2.0-rc.6", "v1.2.0", "v1.3.0-rc.1"}
    assert all(len(profile.commit_sha) == 40 for profile in by_tag.values())
    with pytest.raises(LegacyCompatibilityError, match="No exact reviewed"):
        catalog.match(tag="v1.1.17", commit_sha="0" * 40, release_manifest_sha256="0" * 64)


def test_exact_legacy_export_activates_local_and_detects_camera_change(tmp_path):
    repo = tmp_path / "checkout"
    repo.mkdir()
    old_local = repo / "local"
    old_local.mkdir()
    (old_local / "old-diagnostic.txt").write_text("preserve me", encoding="utf-8")

    context = _active_context(tmp_path)
    binding = build_update_launch_binding(
        context,
        source_app_version="v1.3.0-rc.2",
        source_commit=SOURCE_COMMIT,
        request_id="00000000-0000-0000-0000-000000000096",
    )
    paths = context.paths
    context.close()
    profile = next(item for item in load_compatibility_catalog().profiles if item.tag == "v1.2.0")
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
    try:
        result = create_legacy_compatibility_export(
            prepared,
            repo_root=repo,
            operator="Support Operator",
            reason="Controlled compatibility qualification",
            machine_id_confirmation=binding.machine_id,
            service_record_reference="CASE-123",
            firmware_attestation="Reviewed paired firmware deployment record",
        )
        assert result.existing_local_backup_path.is_file()
        assert (repo / "local" / "Locations.json").read_bytes() == (
            paths.config_root / "Locations.json"
        ).read_bytes()
        assert not (repo / "local" / "old-diagnostic.txt").exists()
        assert compare_legacy_session(paths).unchanged is True

        locations_path = repo / "local" / "Locations.json"
        locations = json.loads(locations_path.read_text(encoding="utf-8"))
        camera_key = next(key for key in locations if key.casefold() == "camera")
        locations[camera_key]["Y"] += 10000
        locations_path.write_text(json.dumps(locations), encoding="utf-8")
        comparison = compare_legacy_session(paths)
        assert comparison.unchanged is False
        difference = next(item for item in comparison.differences if item["relative_path"] == "Locations.json")
        assert difference["kind"] == "changed"
    finally:
        prepared.fail("qualification stops before Git")
        prepared.close()


def test_legacy_export_requires_firmware_attestation_before_local_swap(tmp_path):
    repo = tmp_path / "checkout"
    repo.mkdir()
    context = _active_context(tmp_path)
    binding = build_update_launch_binding(
        context,
        source_app_version="v1.3.0-rc.2",
        source_commit=SOURCE_COMMIT,
        request_id="00000000-0000-0000-0000-000000000095",
    )
    context.close()
    profile = next(item for item in load_compatibility_catalog().profiles if item.tag == "v1.2.0-rc.6")
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
    try:
        with pytest.raises(LegacyCompatibilityError, match="firmware-pairing"):
            create_legacy_compatibility_export(
                prepared,
                repo_root=repo,
                operator="Support Operator",
                reason="Test",
                machine_id_confirmation=binding.machine_id,
                service_record_reference="CASE-124",
                firmware_attestation="",
            )
        assert not (repo / "local").exists()
    finally:
        prepared.fail("expected qualification failure")
        prepared.close()
