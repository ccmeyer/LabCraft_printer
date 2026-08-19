import json
import stat
import zipfile
from pathlib import Path

import pytest

import MachineDataArchive
import MachineDataMigration
from tests.machine_data_migration_helpers import write_candidate


def _zip_tree(source, destination, *, prefix="local"):
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(Path(source).rglob("*")):
            if path.is_file():
                relative = path.relative_to(source).as_posix()
                archive.write(path, f"{prefix}/{relative}" if prefix else relative)
        version_path = (
            f"{prefix.removesuffix('/local')}/VERSION"
            if prefix.endswith("/local")
            else "VERSION"
        )
        archive.writestr(version_path, "v1.3.0-rc.1\n")


def test_semantic_hash_ignores_json_formatting_but_raw_hash_does_not(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text('{"b": 2, "a": 1}\n', encoding="utf-8")
    second.write_text('{\n  "a": 1,\n  "b": 2\n}\n', encoding="utf-8")

    first_raw, _ = MachineDataArchive.sha256_file(first)
    second_raw, _ = MachineDataArchive.sha256_file(second)

    assert first_raw != second_raw
    assert MachineDataArchive.semantic_json_sha256(json.loads(first.read_text())) == (
        MachineDataArchive.semantic_json_sha256(json.loads(second.read_text()))
    )


@pytest.mark.parametrize("member", ["../escape", "/absolute", "C:/drive", "a\\b"])
def test_hostile_zip_paths_are_rejected_before_capture(tmp_path, member):
    archive_path = tmp_path / "hostile.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(member, "bad")

    with pytest.raises(MachineDataArchive.ArchiveSafetyError):
        MachineDataArchive.discover_zip_source(
            archive_path,
            required_names=MachineDataMigration.REQUIRED_CONFIG_NAMES,
            policy=MachineDataArchive.ArchivePolicy(),
        )


def test_case_colliding_zip_members_are_rejected_on_every_os(tmp_path):
    archive_path = tmp_path / "collision.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("local/Locations.json", "{}")
        archive.writestr("local/locations.JSON", "{}")

    with pytest.raises(MachineDataArchive.ArchiveSafetyError, match="colliding"):
        MachineDataArchive.discover_zip_source(
            archive_path,
            required_names=MachineDataMigration.REQUIRED_CONFIG_NAMES,
            policy=MachineDataArchive.ArchivePolicy(),
        )


def test_duplicate_zip_member_is_rejected(tmp_path):
    archive_path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("local/Settings.json", "{}")
        with pytest.warns(UserWarning):
            archive.writestr("local/Settings.json", "{}")

    with pytest.raises(MachineDataArchive.ArchiveSafetyError, match="Duplicate"):
        MachineDataArchive.discover_zip_source(
            archive_path,
            required_names=MachineDataMigration.REQUIRED_CONFIG_NAMES,
            policy=MachineDataArchive.ArchivePolicy(),
        )


def test_zip_symlink_mode_is_rejected(tmp_path):
    archive_path = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("local/link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, "../outside")

    with pytest.raises(MachineDataArchive.ArchiveSafetyError, match="special"):
        MachineDataArchive.discover_zip_source(
            archive_path,
            required_names=MachineDataMigration.REQUIRED_CONFIG_NAMES,
            policy=MachineDataArchive.ArchivePolicy(),
        )


def test_unsupported_zip_compression_is_rejected(tmp_path):
    archive_path = tmp_path / "unsupported.zip"
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_BZIP2) as archive:
            archive.writestr("local/Settings.json", "{}")
    except RuntimeError:
        pytest.skip("BZIP2 ZIP support is unavailable in this interpreter.")

    with pytest.raises(MachineDataArchive.ArchiveSafetyError, match="compression"):
        MachineDataArchive.discover_zip_source(
            archive_path,
            required_names=MachineDataMigration.REQUIRED_CONFIG_NAMES,
            policy=MachineDataArchive.ArchivePolicy(),
        )


def test_zip_size_and_compression_ratio_policy_is_enforced(tmp_path):
    archive_path = tmp_path / "large.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("local/Settings.json", "x" * 4096)

    with pytest.raises(MachineDataArchive.ArchiveLimitError):
        MachineDataArchive.discover_zip_source(
            archive_path,
            required_names=MachineDataMigration.REQUIRED_CONFIG_NAMES,
            policy=MachineDataArchive.ArchivePolicy(
                max_files=10,
                max_member_bytes=10_000,
                max_total_bytes=10_000,
                max_compression_ratio=2,
            ),
        )


def test_directory_file_count_and_total_size_limits_are_enforced(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.txt").write_text("1234", encoding="utf-8")
    (source / "two.txt").write_text("5678", encoding="utf-8")
    locator = MachineDataArchive.SourceLocator(
        "directory", source, local_root=source
    )

    with pytest.raises(MachineDataArchive.ArchiveLimitError):
        MachineDataArchive.capture_source(
            locator,
            MachineDataArchive.ArchivePolicy(
                max_files=1,
                max_member_bytes=100,
                max_total_bytes=100,
            ),
        )
    with pytest.raises(MachineDataArchive.ArchiveLimitError):
        MachineDataArchive.capture_source(
            locator,
            MachineDataArchive.ArchivePolicy(
                max_files=10,
                max_member_bytes=100,
                max_total_bytes=7,
            ),
        )


def test_supported_local_zip_captures_nested_files_without_extracting(tmp_path):
    local_root = write_candidate(
        tmp_path / "source",
        custom_camera=True,
        extra_files={"nested/diagnostic.txt": "synthetic"},
    )
    archive_path = tmp_path / "selected.zip"
    _zip_tree(local_root, archive_path)

    locator = MachineDataArchive.discover_zip_source(
        archive_path,
        required_names=MachineDataMigration.REQUIRED_CONFIG_NAMES,
        policy=MachineDataArchive.ArchivePolicy(),
    )
    snapshot = MachineDataArchive.capture_source(
        locator, MachineDataArchive.ArchivePolicy()
    )

    assert locator.zip_local_prefix == "local"
    assert "CalibrationMemory/schema.json" in {
        member.relative_path for member in snapshot.local_members
    }
    assert "nested/diagnostic.txt" in {
        member.relative_path for member in snapshot.local_members
    }
    assert snapshot.version_member is not None
    assert not (tmp_path / "local").exists()


def test_supported_single_wrapper_zip_is_normalized(tmp_path):
    local_root = write_candidate(tmp_path / "source", custom_camera=True)
    archive_path = tmp_path / "wrapper.zip"
    _zip_tree(local_root, archive_path, prefix="backup/local")

    locator = MachineDataArchive.discover_zip_source(
        archive_path,
        required_names=MachineDataMigration.REQUIRED_CONFIG_NAMES,
        policy=MachineDataArchive.ArchivePolicy(),
    )

    assert locator.zip_local_prefix == "backup/local"


def test_zip_with_multiple_candidates_is_ambiguous(tmp_path):
    first = write_candidate(tmp_path / "first", custom_camera=True)
    second = write_candidate(tmp_path / "second", custom_camera=True)
    archive_path = tmp_path / "ambiguous.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for prefix, source in (("one/local", first), ("two/local", second)):
            for path in source.rglob("*"):
                if path.is_file():
                    archive.write(path, f"{prefix}/{path.relative_to(source).as_posix()}")

    with pytest.raises(MachineDataArchive.ArchiveSafetyError, match="exactly one"):
        MachineDataArchive.discover_zip_source(
            archive_path,
            required_names=MachineDataMigration.REQUIRED_CONFIG_NAMES,
            policy=MachineDataArchive.ArchivePolicy(),
        )


def test_truncated_zip_is_rejected(tmp_path):
    local_root = write_candidate(tmp_path / "source", custom_camera=True)
    archive_path = tmp_path / "truncated.zip"
    _zip_tree(local_root, archive_path)
    data = archive_path.read_bytes()
    archive_path.write_bytes(data[:-40])

    with pytest.raises(MachineDataArchive.ArchiveSafetyError):
        MachineDataArchive.discover_zip_source(
            archive_path,
            required_names=MachineDataMigration.REQUIRED_CONFIG_NAMES,
            policy=MachineDataArchive.ArchivePolicy(),
        )


def test_directory_symlink_is_rejected_when_supported(tmp_path):
    source = write_candidate(tmp_path / "source", custom_camera=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = source / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable for this account.")

    locator = MachineDataArchive.SourceLocator(
        "directory", source, local_root=source
    )
    with pytest.raises(MachineDataArchive.ArchiveSafetyError, match="link"):
        MachineDataArchive.capture_source(
            locator, MachineDataArchive.ArchivePolicy()
        )


def test_archive_module_has_no_qt_mvc_updater_or_hardware_imports():
    source = Path("FreeRTOS-interface/MachineDataArchive.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "PySide",
        "from App import",
        "from Model import",
        "from Controller import",
        "from View import",
        "update_and_restart",
        "Machine_FreeRTOS",
    ):
        assert forbidden not in source
