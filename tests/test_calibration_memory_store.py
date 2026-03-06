import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from CalibrationMemoryStore import CalibrationMemoryStore


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


def _make_dummy_model(tmp_path):
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
        get_save_root_directory=lambda: str(tmp_path / "droplet_imager_captures"),
        get_active_save_directory=lambda: str(tmp_path / "droplet_imager_captures" / "run_a"),
    )
    return SimpleNamespace(
        rack_model=rack_model,
        experiment_model=experiment_model,
        droplet_camera_model=droplet_camera_model,
        profile=SimpleNamespace(name="test-profile"),
    )


def test_calibration_memory_store_creates_run_summary_catalog_and_observations(tmp_path):
    model = _make_dummy_model(tmp_path)
    store = CalibrationMemoryStore(model=model, root_dir=str(tmp_path / "CalibrationMemory"))

    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    assert context["stock_id"] == "Water_0.00_--"
    assert context["reagent_id"] == "water"
    assert context["printer_head_id"] == "PH-001"
    assert context["identity_quality"]["reagent_id"] == "derived"

    paths = store.create_run(
        "run_test_001",
        context=context,
        notes="unit test",
        manager_meta={"source": "pytest"},
    )
    assert Path(paths["run_dir"]).exists()
    assert Path(paths["run_summary_path"]).exists()
    assert Path(paths["observations_path"]).exists()
    assert (Path(store.root_dir) / "schema.json").exists()

    observation = store.append_observation(
        "run_test_001",
        {
            "observation_type": "process_analysis",
            "context": context,
            "payload": {"kind": "characterization_frame", "volume_nL": 9.84},
            "artifact_refs": {"calibration_json_path": model.experiment_model.calibration_file_path},
        },
    )
    assert observation["run_id"] == "run_test_001"
    assert observation["schema_name"] == store.OBSERVATION_SCHEMA

    summary = store.write_run_summary(
        "run_test_001",
        {
            "context": context,
            "run_timing": {"started_at_utc": "2026-03-06T18:00:00Z", "ended_at_utc": None},
            "phase_counts": {"droplet_search": 1},
            "process_results": {
                "droplet_search": {
                    "step_count": 1,
                    "latest_result": {"mean_volume": 9.84, "cv_volume_percent": 4.2},
                }
            },
        },
    )
    assert summary["schema_name"] == store.RUN_SUMMARY_SCHEMA

    catalog_lines = Path(store.run_catalog_path).read_text(encoding="utf-8").strip().splitlines()
    assert len(catalog_lines) == 1
    catalog_entry = json.loads(catalog_lines[0])
    assert catalog_entry["run_id"] == "run_test_001"
    assert catalog_entry["context"]["stock_id"] == "Water_0.00_--"

    observations = [json.loads(line) for line in Path(paths["observations_path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(observations) == 1
    assert observations[0]["payload"]["volume_nL"] == 9.84

    run_summary = json.loads(Path(paths["run_summary_path"]).read_text(encoding="utf-8"))
    assert run_summary["process_results"]["droplet_search"]["latest_result"]["mean_volume"] == 9.84


def test_calibration_memory_atomic_write_preserves_previous_file_on_replace_failure(tmp_path, monkeypatch):
    store = CalibrationMemoryStore(root_dir=str(tmp_path / "CalibrationMemory"))
    target = tmp_path / "run_summary.json"
    baseline = {"name": "baseline"}
    target.write_text(json.dumps(baseline), encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("os.replace", _boom)

    with pytest.raises(OSError, match="replace failure"):
        store._write_json_atomic(str(target), {"name": "updated"})

    assert json.loads(target.read_text(encoding="utf-8")) == baseline
    assert list(target.parent.glob("._tmp_*")) == []
