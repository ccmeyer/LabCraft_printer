from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from CalibrationHistoricalConversion import (
    CalibrationHistoricalConverter,
    file_sha256,
)
from CalibrationRecordingReader import CalibrationRecordingReader


def _step(*, run_id="legacy-session-1", mean_volume=10.0):
    return {
        "timestamp": "2025-01-02T03:04:05Z",
        "settings": {"print_width": 1400, "print_pressure": 1.2},
        "meta": {
            "run_id": run_id,
            "printer_head_id": "head-1",
            "stock_id": "stock-1",
        },
        "phase": "pressure_sweep_characterization",
        "result": {
            "pressures": [
                {
                    "pressure": 1.2,
                    "mean_volume": mean_volume,
                    "cv_volume_percent": 3.0,
                    "valid": True,
                }
            ]
        },
    }


def _experiment(tmp_path: Path, *, steps=None, outcome="completed") -> Path:
    root = tmp_path / "historical-experiment"
    root.mkdir()
    document = {
        "schema_version": 1,
        "runs": [
            {
                "run_id": "legacy-session-1",
                "started_at": "2025-01-02T03:00:00Z",
                "ended_at": "2025-01-02T03:05:00Z",
                "outcome": outcome,
                "printer_head_id": "head-1",
                "stock_id": "stock-1",
                "reagent_name": "Synthetic Reagent",
                "steps": {
                    "pressure_sweep_characterization": steps or [_step()],
                },
            }
        ],
    }
    (root / "calibration.json").write_text(
        json.dumps(document, indent=2), encoding="utf-8"
    )
    return root


def _recording(root: Path, name: str, payload: dict) -> None:
    run_dir = root / "calibration_recordings" / "PressureSweepCharacterizationProcess" / name
    run_dir.mkdir(parents=True)
    (run_dir / "run_meta.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": name,
                "process_name": "PressureSweepCharacterizationProcess",
                "phase_name": "pressure_sweep_characterization",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "analysis.jsonl").write_text(
        json.dumps(
            {
                "kind": "calibration_data_updated",
                "phase": "pressure_sweep_characterization",
                "payload": payload,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _tree_hashes(root: Path):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_plan_is_read_only_and_accepts_missing_recording(tmp_path):
    root = _experiment(tmp_path)
    before = _tree_hashes(root)
    plan = CalibrationHistoricalConverter(root).plan()
    assert plan.counts == {
        "source_step_count": 1,
        "convert_count": 1,
        "already_canonical_count": 0,
        "already_generated_count": 0,
        "skipped_count": 0,
        "conflict_count": 0,
    }
    assert plan.items[0].reason == "eligible_without_recording"
    assert _tree_hashes(root) == before


def test_apply_is_idempotent_and_reader_reconciles_without_rewriting_legacy(tmp_path):
    root = _experiment(tmp_path)
    legacy_hash = file_sha256(root / "calibration.json")
    converter = CalibrationHistoricalConverter(root)
    report = converter.apply()
    assert report["status"] == "valid"
    assert report["generated_count"] == 1
    assert report["source_unchanged"] is True
    assert file_sha256(root / "calibration.json") == legacy_hash

    reader = CalibrationRecordingReader(root)
    snapshot = reader.history_snapshot()
    assert len(snapshot.rows) == 1
    assert snapshot.rows[0]["reader_state"] == "matching_dual"
    resolved = reader.resolve_selection(snapshot.rows[0])
    assert resolved["ok"] is True
    assert resolved["bundle"]["update"]["payload_sha256"] == snapshot.rows[0][
        "update_payload_sha256"
    ]

    after_first = _tree_hashes(root)
    second = converter.apply()
    assert second["manifest_sha256"] == report["manifest_sha256"]
    assert _tree_hashes(root) == after_first
    assert CalibrationRecordingReader(root, include_migrated=False).history_snapshot().rows[
        0
    ]["reader_state"] == "legacy_only"


def test_unique_recording_is_provenance_and_duplicate_recording_is_skipped(tmp_path):
    root = _experiment(tmp_path, steps=[_step(), _step(mean_volume=11.0)])
    _recording(root, "legacy-recording-1", _step())
    _recording(root, "duplicate-a", _step(mean_volume=11.0))
    _recording(root, "duplicate-b", _step(mean_volume=11.0))
    plan = CalibrationHistoricalConverter(root).plan()
    assert plan.items[0].reason == "eligible_unique_recording_link"
    assert plan.items[0].evidence is not None
    assert plan.items[1].disposition == "skipped"
    assert plan.items[1].reason == "recording_link_ambiguous"


def test_stopped_step_is_durable_but_not_in_application_history(tmp_path):
    root = _experiment(tmp_path, outcome="stopped")
    report = CalibrationHistoricalConverter(root).apply()
    assert report["generated_count"] == 1
    assert CalibrationRecordingReader(root).history_snapshot().rows == ()


def test_legacy_mutation_after_conversion_becomes_parity_conflict(tmp_path):
    root = _experiment(tmp_path)
    CalibrationHistoricalConverter(root).apply()
    document = json.loads((root / "calibration.json").read_text(encoding="utf-8"))
    document["runs"][0]["steps"]["pressure_sweep_characterization"][0]["result"][
        "pressures"
    ][0]["mean_volume"] = 99.0
    (root / "calibration.json").write_text(json.dumps(document), encoding="utf-8")
    snapshot = CalibrationRecordingReader(root).history_snapshot()
    canonical = next(row for row in snapshot.rows if row.get("result_id"))
    assert canonical["reader_state"] == "parity_conflict"
    assert canonical["blocked"] is True

@pytest.fixture
def historical_experiment_factory():
    return _experiment
