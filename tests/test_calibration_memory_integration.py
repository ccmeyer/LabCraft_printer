import json
from pathlib import Path
from types import SimpleNamespace

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs(force=True)

from CalibrationMemoryStore import CalibrationMemoryStore
from CalibrationClasses.Model import BaseCalibrationProcess, CalibrationManager


class _DummyStockSolution:
    def __init__(self, stock_id="Water_0.00_--", reagent_name="Water", concentration="0.00", units="--"):
        self._stock_id = stock_id
        self._reagent_name = reagent_name
        self._concentration = concentration
        self.units = units

    def get_stock_id(self):
        return self._stock_id

    def get_reagent_name(self):
        return self._reagent_name

    def get_stock_concentration(self):
        return self._concentration


class _DummyPrinterHead:
    def __init__(self, stock_solution, serial="PH-001"):
        self._stock_solution = stock_solution
        self.serial = serial
        self.color = "Blue"
        self.calibration_chip = False

    def get_stock_solution(self):
        return self._stock_solution


def _make_model(tmp_path):
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    calibration_path = experiment_dir / "calibration.json"

    stock = _DummyStockSolution()
    printer_head = _DummyPrinterHead(stock)
    rack_model = SimpleNamespace(
        get_gripper_printer_head=lambda: printer_head,
        gripper_slot_number=2,
    )
    experiment_model = SimpleNamespace(
        experiment_dir_path=str(experiment_dir),
        calibration_file_path=str(calibration_path),
        get_calibration_file_path=lambda: str(calibration_path),
    )
    droplet_camera_model = SimpleNamespace(
        get_image_metadata=lambda: (1, 1000, 4300, 1, 30000),
        get_save_root_directory=lambda: str(tmp_path / "droplet_imager_captures"),
        get_active_save_directory=lambda: str(tmp_path / "droplet_imager_captures" / "run_a"),
    )
    machine_model = SimpleNamespace(
        get_current_position_dict=lambda: {"X": 10, "Y": 20, "Z": 30},
        get_print_pulse_width=lambda: 1500,
        get_refuel_pulse_width=lambda: 0,
        get_current_print_pressure=lambda: 1.62,
        get_current_refuel_pressure=lambda: 0.0,
    )
    model = SimpleNamespace(
        machine_state_updated=SignalStub(),
        rack_model=rack_model,
        experiment_model=experiment_model,
        droplet_camera_model=droplet_camera_model,
        machine_model=machine_model,
        profile=SimpleNamespace(name="test-profile"),
    )
    model.calibration_memory_store = CalibrationMemoryStore(
        model=model,
        root_dir=str(tmp_path / "CalibrationMemory"),
    )
    return model


def test_calibration_manager_writes_sidecar_summary_and_observations(tmp_path):
    model = _make_model(tmp_path)
    manager = CalibrationManager(model)

    calibration_path = model.experiment_model.calibration_file_path
    manager.begin_session(calibration_path, notes="integration test")
    manager.activeCalibration = SimpleNamespace(phase_name="droplet_search")

    process = BaseCalibrationProcess(manager, model)
    process.phase_name = "droplet_search"
    process._record_event("candidate_found", {"flash_delay_us": 4300})
    process._record_analysis({"kind": "characterization_frame", "volume_nL": 9.91})

    manager.onCalibrationDataUpdated(
        {
            "result": {
                "mean_volume": 9.91,
                "cv_volume_percent": 4.0,
                "valid": True,
            }
        }
    )

    run_id = manager._run_id
    run_dir = Path(model.calibration_memory_store.get_run_paths(run_id)["run_dir"])
    observations = [
        json.loads(line)
        for line in (run_dir / "observations.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["observation_type"] for row in observations} >= {"process_event", "process_analysis"}
    assert all(row["context"]["stock_id"] == "Water_0.00_--" for row in observations)

    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == run_id
    assert summary["context"]["stock_id"] == "Water_0.00_--"
    assert summary["process_results"]["droplet_search"]["latest_result"]["mean_volume"] == 9.91


def test_calibration_memory_failures_do_not_break_calibration(tmp_path, capsys, monkeypatch):
    model = _make_model(tmp_path)
    manager = CalibrationManager(model)

    store = model.calibration_memory_store

    def _boom(*args, **kwargs):
        raise RuntimeError("forced sidecar failure")

    monkeypatch.setattr(store, "create_run", _boom)
    manager.begin_session(model.experiment_model.calibration_file_path, notes="should continue")

    manager.activeCalibration = SimpleNamespace(phase_name="droplet_search")
    monkeypatch.setattr(store, "build_run_summary", _boom)
    manager.onCalibrationDataUpdated({"result": {"mean_volume": 10.01}})

    process = BaseCalibrationProcess(manager, model)
    process.phase_name = "droplet_search"
    monkeypatch.setattr(store, "append_observation_from_manager", _boom)
    process._record_event("still_running", {"value": 1})
    process._record_analysis({"kind": "test"})
    process._record_error("nonfatal", {"detail": True})

    captured = capsys.readouterr()
    assert "[CalibrationMemory]" in captured.out

    calibration_json = Path(model.experiment_model.calibration_file_path)
    assert calibration_json.exists()
    saved = json.loads(calibration_json.read_text(encoding="utf-8"))
    assert saved["runs"]
    assert saved["runs"][0]["steps"]["droplet_search"][0]["result"]["mean_volume"] == 10.01
