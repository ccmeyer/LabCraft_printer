from __future__ import annotations

from types import SimpleNamespace

import pytest

from CalibrationRecordingStore import CaptureRetentionPolicy
from CalibrationStorageContracts import (
    PRODUCTION_PROCESS_NAMES,
    build_terminal_summary,
    process_storage_contract,
)


EXPECTED_PRODUCTION_PROCESSES = {
    "HeadPrimeCalibrationProcess",
    "NozzlePositionCalibrationProcess",
    "NozzleFocusCalibrationProcess",
    "DropletEmergenceCalibrationProcess",
    "PressureCalibrationProcess",
    "PreBreakupMorphologyCalibrationProcess",
    "PreBreakupDatasetAcquisitionProcess",
    "PressureBandCalibrationProcess",
    "TrajectoryCalibrationProcess",
    "PressureTrajectoryCalibrationProcess",
    "DropletSearchCalibrationProcess",
    "PressureSweepCharacterizationProcess",
    "OnlineStreamCalibrationProcess",
    "DropletTimecourseProcess",
}


def test_every_concrete_production_process_has_an_explicit_contract():
    assert PRODUCTION_PROCESS_NAMES == EXPECTED_PRODUCTION_PROCESSES
    contracts = {
        name: process_storage_contract(name) for name in PRODUCTION_PROCESS_NAMES
    }
    assert {contract.result_kind for contract in contracts.values()} == {
        "operational",
        "calibration",
        "dataset",
    }
    assert contracts["PreBreakupDatasetAcquisitionProcess"].minimum_capture_policy is CaptureRetentionPolicy.FULL
    assert contracts["DropletTimecourseProcess"].minimum_capture_policy is CaptureRetentionPolicy.FULL
    assert contracts["PressureSweepCharacterizationProcess"].application_eligible


def test_undeclared_process_is_rejected_before_start():
    with pytest.raises(ValueError, match="no canonical storage contract"):
        process_storage_contract("UnregisteredCalibrationProcess")


def test_characterization_adapter_is_bounded_and_application_eligible_only_when_completed():
    contract = process_storage_contract("PressureSweepCharacterizationProcess")
    run = SimpleNamespace(
        process_run_id="process-run-1",
        identity={"identity_quality": "stable"},
        updates=[
            {
                "update_id": "update-1",
                "update_index": 0,
                "legacy_source": {
                    "source_run_id": "session-1",
                    "source_phase_key": "pressure_sweep_characterization",
                    "source_step_index": 0,
                },
                "payload": {
                    "timestamp": "2026-08-15T00:00:00Z",
                    "result": {
                        "pressure_psi": 1.2,
                        "mean_nL": 9.5,
                        "raw_measurements": list(range(100)),
                    },
                },
            }
        ],
    )
    summary = build_terminal_summary(object(), contract, run, "completed")
    assert summary["application_eligible"] is True
    assert summary["rows"][0]["pressure_psi"] == 1.2
    assert "raw_measurements" not in summary["rows"][0]
    assert build_terminal_summary(object(), contract, run, "error")["application_eligible"] is False


def test_dataset_adapter_counts_frames_without_embedding_the_stream():
    contract = process_storage_contract("DropletTimecourseProcess")
    run = SimpleNamespace(
        process_run_id="dataset-run-1",
        identity={"identity_quality": "stable"},
        updates=[
            {
                "update_id": "dataset-update-1",
                "update_index": 0,
                "legacy_source": {},
                "payload": {
                    "result": {
                        "frames": [{"delay_us": value} for value in range(25)],
                        "manifest_relpath": "captures/timecourse_manifest.json",
                        "absolute_manifest": "C:/private/source.json",
                    }
                },
            }
        ],
    )
    summary = build_terminal_summary(object(), contract, run, "completed")
    assert summary["dataset_manifest"]["frame_count"] == 25
    assert summary["dataset_manifest"]["relative_references"] == {
        "manifest_relpath": "captures/timecourse_manifest.json"
    }
    assert "frames" not in summary["dataset_manifest"]
