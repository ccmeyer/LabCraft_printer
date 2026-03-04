import json
from pathlib import Path

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import NozzlePositionChecklistStore


def test_nozzle_position_manifest_exists_and_validates():
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "FreeRTOS-interface"
        / "CalibrationClasses"
        / "test_images"
        / "NozzlePositionCalibrationProcess"
        / "checklist_manifest.v1.json"
    )
    assert manifest_path.exists()

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    NozzlePositionChecklistStore.validate_manifest(payload)

    assert payload["process_name"] == "NozzlePositionCalibrationProcess"
    assert len(payload["cases"]) == 18
    case_ids = {c["case_id"] for c in payload["cases"]}
    assert "NP_OK_CENTERED" in case_ids
    assert "NP_SEQ_NO_SIGNAL_TO_ABORT" in case_ids


def test_sequence_cases_have_step_replicate_requirements():
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "FreeRTOS-interface"
        / "CalibrationClasses"
        / "test_images"
        / "NozzlePositionCalibrationProcess"
        / "checklist_manifest.v1.json"
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    seq = next(c for c in payload["cases"] if c["case_id"] == "NP_SEQ_DELAY_SCAN_TO_SUCCESS")
    steps = {s["step_id"]: s for s in seq["steps"]}

    assert steps["bg_baseline"]["required"]["background"] == 1
    assert steps["bg_baseline"]["required"]["droplet"] == 0
    assert steps["dr_delay_scan_early_none"]["required"]["droplet"] == 3
