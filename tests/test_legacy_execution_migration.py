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


REPORTED_SOURCE = (
    Path(__file__).parents[1]
    / "FreeRTOS-interface"
    / "Experiments"
    / "SW_experiment_load_error"
    / "Labcraft Files, Design will not load into screen preventing analysis"
)


def test_reported_legacy_execution_migrates_to_analysis_only_copy(tmp_path):
    before = hash_directory_files(REPORTED_SOURCE)
    destination = tmp_path / "migrated"

    result = migrate_legacy_execution_copy(
        REPORTED_SOURCE,
        destination,
        timestamp_utc="2026-07-17T12:00:00Z",
    )

    assert result.destination == destination.resolve()
    assert hash_directory_files(REPORTED_SOURCE) == before
    design_bytes = (destination / "experiment_design.json").read_bytes()
    assert design_bytes == (REPORTED_SOURCE / "experiment_design.json").read_bytes()
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


def test_migration_failure_or_collision_leaves_source_unchanged(tmp_path):
    before = hash_directory_files(REPORTED_SOURCE)
    collision = tmp_path / "exists"
    collision.mkdir()
    with pytest.raises(FileExistsError):
        migrate_legacy_execution_copy(REPORTED_SOURCE, collision)
    assert hash_directory_files(REPORTED_SOURCE) == before


def test_migration_cancellation_removes_only_staging(tmp_path):
    before = hash_directory_files(REPORTED_SOURCE)
    destination = tmp_path / "canceled"

    with pytest.raises(RuntimeError, match="canceled"):
        migrate_legacy_execution_copy(
            REPORTED_SOURCE,
            destination,
            cancel_check=lambda: True,
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(".canceled.staging-*"))
    assert hash_directory_files(REPORTED_SOURCE) == before
