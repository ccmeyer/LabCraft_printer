from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from CalibrationClasses.Model import CalibrationManager
from CalibrationPersistencePolicy import (
    LegacyWriterMode,
    load_calibration_storage_policy,
    new_experiment_policy,
)
from Model import CURRENT_PROFILE, ExperimentModel
from tests.calibration_test_utils import SignalStub


def _manager_model(tmp_path: Path):
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir(parents=True)
    calibration_path = experiment_dir / "calibration.json"
    experiment_model = SimpleNamespace(
        experiment_dir_path=str(experiment_dir),
        calibration_file_path=str(calibration_path),
        get_calibration_file_path=lambda: str(calibration_path),
    )
    return SimpleNamespace(
        machine_state_updated=SignalStub(),
        experiment_model=experiment_model,
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: None),
        machine_model=SimpleNamespace(),
        calibration_memory_store=None,
    )


def test_policy_schema_defaults_new_and_treats_missing_as_historical():
    assert (
        new_experiment_policy().legacy_writer_mode
        is LegacyWriterMode.CANONICAL_ONLY
    )
    historical = load_calibration_storage_policy(None)
    assert historical.legacy_writer_mode is LegacyWriterMode.LEGACY_COMPATIBLE
    invalid = load_calibration_storage_policy({"schema_name": "future"})
    assert invalid.legacy_writer_mode is LegacyWriterMode.LEGACY_COMPATIBLE
    assert invalid.warning


def test_fresh_experiment_persists_policy_without_seeding_calibration_json(tmp_path):
    model = ExperimentModel(prof=CURRENT_PROFILE, experiments_root=tmp_path)
    model.metadata["name"] = "canonical-only"

    model.initialize_experiment(base_dir=str(tmp_path))

    root = tmp_path / "canonical-only"
    document = json.loads((root / "experiment_design.json").read_text(encoding="utf-8"))
    assert document["calibration_storage"]["legacy_writer_mode"] == "canonical_only"
    assert not (root / "calibration.json").exists()
    assert not list(root.glob("calibration.json.*"))


def test_manager_suppresses_every_legacy_save_for_canonical_only_policy(tmp_path):
    model = _manager_model(tmp_path)
    manager = CalibrationManager(model)
    manager.update_calibration_file_path(model.experiment_model.calibration_file_path)
    manager.set_calibration_storage_policy(new_experiment_policy())

    manager.begin_session(model.experiment_model.calibration_file_path)
    manager.save_calibration_data(model.experiment_model.calibration_file_path)
    manager.end_session()

    path = Path(model.experiment_model.calibration_file_path)
    assert not path.exists()
    assert not list(path.parent.glob("calibration.json.*"))
    diagnostics = manager.get_legacy_calibration_writer_diagnostics()
    assert diagnostics["effective_enabled"] is False
    assert diagnostics["write_count"] == 0
    assert diagnostics["suppressed_write_count"] == 3


def test_historical_policy_keeps_existing_dual_writer(tmp_path):
    model = _manager_model(tmp_path)
    manager = CalibrationManager(model)
    manager.update_calibration_file_path(model.experiment_model.calibration_file_path)

    manager.begin_session(model.experiment_model.calibration_file_path)
    manager.end_session()

    path = Path(model.experiment_model.calibration_file_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert len(document["runs"]) == 1
    assert document["runs"][0]["outcome"] == "completed"
    assert manager.get_legacy_calibration_writer_diagnostics()["write_count"] == 2


@pytest.mark.parametrize(
    ("environment", "reason"),
    [
        ({"LABCRAFT_CALIBRATION_LEGACY_WRITER": "1"}, "legacy_writer_rollback"),
        ({"LABCRAFT_CALIBRATION_STORE_AUTHORITATIVE": "0"}, "authoritative_store_rollback"),
        ({"LABCRAFT_CALIBRATION_PRIMARY_READER": "legacy"}, "primary_legacy_reader"),
        ({"LABCRAFT_CALIBRATION_SECONDARY_READER": "legacy"}, "secondary_legacy_reader"),
    ],
)
def test_compatibility_modes_force_legacy_writer(
    tmp_path, monkeypatch, environment, reason
):
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    model = _manager_model(tmp_path)
    manager = CalibrationManager(model)
    manager.update_calibration_file_path(model.experiment_model.calibration_file_path)
    manager.set_calibration_storage_policy(new_experiment_policy())

    manager.begin_session(model.experiment_model.calibration_file_path)
    manager.end_session()

    diagnostics = manager.get_legacy_calibration_writer_diagnostics()
    assert diagnostics["effective_enabled"] is True
    assert diagnostics["effective_reason"] == reason
    assert Path(model.experiment_model.calibration_file_path).is_file()


def test_policy_cannot_change_during_active_session(tmp_path):
    model = _manager_model(tmp_path)
    manager = CalibrationManager(model)
    manager.update_calibration_file_path(model.experiment_model.calibration_file_path)
    manager.begin_session(model.experiment_model.calibration_file_path)

    with pytest.raises(RuntimeError, match="active session"):
        manager.set_calibration_storage_policy(new_experiment_policy())
