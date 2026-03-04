import json
from pathlib import Path
from types import SimpleNamespace

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import CalibrationManager


class _DummyProcess:
    phase_name = "nozzle_position"



def _dummy_model(tmp_path):
    return SimpleNamespace(
        machine_state_updated=SignalStub(),
        experiment_model=SimpleNamespace(
            experiment_dir_path=str(tmp_path),
            calibration_file_path=str(tmp_path / "calibration.json"),
            get_calibration_file_path=lambda: str(tmp_path / "calibration.json"),
        ),
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: None),
        droplet_camera_model=SimpleNamespace(get_image_metadata=lambda: (0, 0, 0, 0, 0)),
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: {"X": 0, "Y": 0, "Z": 0},
            get_print_pulse_width=lambda: 0,
            get_refuel_pulse_width=lambda: 0,
            get_current_print_pressure=lambda: 0.0,
            get_current_refuel_pressure=lambda: 0.0,
        ),
    )


def test_manager_submits_latest_process_verdict(tmp_path):
    model = _dummy_model(tmp_path)
    mgr = CalibrationManager(model)

    mgr._begin_process_recording(_DummyProcess())
    latest = mgr.get_latest_recording_directory()
    assert latest

    out = mgr.submit_latest_process_verdict(
        outcome="failed",
        failure_summary="nozzle not centered",
        suspected_cause="weak signal",
        notes="repeat under brighter lighting",
        submitted_by="unit-test",
    )
    assert out is not None

    verdict_path = Path(latest) / "verdict.json"
    assert verdict_path.exists()
    payload = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert payload["outcome"] == "failed"
    assert payload["failure_summary"] == "nozzle not centered"
    assert payload["suspected_cause"] == "weak signal"
