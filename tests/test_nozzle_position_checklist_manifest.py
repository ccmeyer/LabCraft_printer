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
    assert len(payload["cases"]) == 17
    case_ids = {c["case_id"] for c in payload["cases"]}
    assert "NP_OK_CENTERED" in case_ids
    assert "NP_FAIL_NO_SIGNAL_PRESSURE_LOW" in case_ids
    assert "NP_FAIL_NONE_FLASH_DELAY_TOO_SHORT" in case_ids
    assert all(not cid.startswith("NP_SEQ_") for cid in case_ids)


def test_atomic_cases_use_single_default_step_and_required_counts():
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "FreeRTOS-interface"
        / "CalibrationClasses"
        / "test_images"
        / "NozzlePositionCalibrationProcess"
        / "checklist_manifest.v1.json"
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for case in payload["cases"]:
        assert len(case["steps"]) == 1
        step = case["steps"][0]
        assert step["step_id"] == "default"
        assert step["required"]["background"] == 1
        assert step["required"]["droplet"] == 3
