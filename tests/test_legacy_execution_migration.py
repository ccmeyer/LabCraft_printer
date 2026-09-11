import hashlib
import json
from pathlib import Path

import pytest

from AuthoritativeExecutionLoad import inspect_authoritative_execution
from LegacyExecutionMigration import (
    LegacyMigrationManifest,
    hash_directory_files,
    load_legacy_migration_manifest,
    migrate_legacy_execution_copy,
)


from tests.legacy_execution_helpers import _write_folder, _progress


@pytest.fixture
def legacy_source(tmp_path):
    source = tmp_path / "legacy"
    _write_folder(source, progress=_progress())
    required = {"experiment_design.json", "progress.json", "key.csv", "concentration_key.csv"}
    assert required <= {path.name for path in source.iterdir() if path.is_file()}
    return source


def test_reported_legacy_execution_migrates_to_analysis_only_copy(tmp_path, legacy_source):
    before = hash_directory_files(legacy_source)
    destination = tmp_path / "migrated"

    result = migrate_legacy_execution_copy(
        legacy_source,
        destination,
        timestamp_utc="2026-07-17T12:00:00Z",
    )

    assert result.destination == destination.resolve()
    assert hash_directory_files(legacy_source) == before
    design_bytes = (destination / "experiment_design.json").read_bytes()
    assert design_bytes == (legacy_source / "experiment_design.json").read_bytes()
    design = json.loads(design_bytes)
    bundle = inspect_authoritative_execution(destination, design)
    assert bundle.valid
    assert bundle.eligibility.status == "analysis_only"
    assert not bundle.eligibility.can_activate_runtime
    assert not (destination / "execution_resume.json").exists()
    assert max(well.expected_printed_volume_nL for well in bundle.plan.wells) == pytest.approx(
        2559.9845212965747
    )
    manifest = load_legacy_migration_manifest(destination / "legacy_migration.json")
    assert manifest.hardware_policy == "analysis_only"
    assert manifest.source_file_sha256 == before


def test_migration_manifest_rejects_unknown_fields(tmp_path):
    payload = {
        "schema_name": "labcraft.legacy_execution_migration",
        "schema_version": 1,
        "plan_id": "f33cf5d6-2f38-4ca7-86fd-74f73baac81d",
        "source_folder_name": "legacy",
        "source_design_sha256": "a" * 64,
        "source_file_sha256": {"experiment_design.json": "b" * 64},
        "migrated_at_utc": "2026-07-17T12:00:00Z",
        "hardware_policy": "analysis_only",
        "warnings": [],
        "future": True,
    }
    with pytest.raises(ValueError, match="unknown field"):
        LegacyMigrationManifest.from_dict(payload)


def test_migration_failure_or_collision_leaves_source_unchanged(tmp_path, legacy_source):
    before = hash_directory_files(legacy_source)
    collision = tmp_path / "exists"
    collision.mkdir()
    with pytest.raises(FileExistsError):
        migrate_legacy_execution_copy(legacy_source, collision)
    assert hash_directory_files(legacy_source) == before


def test_migration_cancellation_removes_only_staging(tmp_path, legacy_source):
    before = hash_directory_files(legacy_source)
    destination = tmp_path / "canceled"

    with pytest.raises(RuntimeError, match="canceled"):
        migrate_legacy_execution_copy(
            legacy_source,
            destination,
            cancel_check=lambda: True,
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(".canceled.staging-*"))
    assert hash_directory_files(legacy_source) == before
