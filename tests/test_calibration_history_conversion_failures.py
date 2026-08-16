from __future__ import annotations

import json

import pytest

from CalibrationHistoricalConversion import (
    CalibrationHistoricalConflictError,
    CalibrationHistoricalConverter,
    CalibrationHistoricalSourceError,
)
from tests.calibration_history_conversion_helpers import experiment


def test_interrupted_bundle_publish_resumes_without_duplicate_index(tmp_path):
    root = experiment(tmp_path)

    def fault(stage):
        if stage == "after_bundle_publish":
            raise RuntimeError("injected interruption")

    with pytest.raises(RuntimeError, match="injected interruption"):
        CalibrationHistoricalConverter(root, fault_hook=fault).apply()
    manifest = json.loads(
        (root / "calibration_history_migration.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "interrupted"

    report = CalibrationHistoricalConverter(root).resume()
    assert report["status"] == "valid"
    index_lines = (
        root / "calibration_index.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert len(index_lines) == 1


def test_apply_requires_resume_for_incomplete_manifest(tmp_path):
    root = experiment(tmp_path)
    plan = CalibrationHistoricalConverter(root).plan()
    (root / "calibration_history_migration.json").write_text(
        json.dumps(
            {
                "schema_name": "labcraft.calibration_history_migration_manifest",
                "schema_version": 1,
                "manifest_id": plan.manifest_id,
                "status": "interrupted",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CalibrationHistoricalConflictError, match="--resume"):
        CalibrationHistoricalConverter(root).apply()


def test_resume_refuses_changed_source(tmp_path):
    root = experiment(tmp_path)

    def fault(stage):
        if stage == "after_bundle_publish":
            raise RuntimeError("stop")

    with pytest.raises(RuntimeError):
        CalibrationHistoricalConverter(root, fault_hook=fault).apply()
    document = json.loads((root / "calibration.json").read_text(encoding="utf-8"))
    document["runs"][0]["notes"] = "changed"
    (root / "calibration.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(
        (CalibrationHistoricalConflictError, CalibrationHistoricalSourceError),
        match="different source snapshot|changed",
    ):
        CalibrationHistoricalConverter(root).resume()
