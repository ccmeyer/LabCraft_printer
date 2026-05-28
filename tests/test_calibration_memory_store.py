import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import LocalConfig
from CalibrationMemoryStore import CalibrationMemoryStore


class _DummyStockSolution:
    def __init__(self, stock_id="Water_0.00_--", reagent_name="Water", concentration="0.00", units="--"):
        self._stock_id = stock_id
        self._reagent_name = reagent_name
        self._concentration = concentration
        self.units = units
        self.reagent_id = None
        self.display_name = None
        self.reagent_family = None
        self.glycerol_percent = None
        self.tags = []
        self.notes = ""

    def get_stock_id(self):
        return self._stock_id

    def get_reagent_name(self):
        return self._reagent_name

    def get_stock_concentration(self):
        return self._concentration

    def get_stock_name(self):
        return self._reagent_name

    def set_reagent_identity(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _DummyPrinterHead:
    def __init__(self, stock_solution, serial="PH-001"):
        self._stock_solution = stock_solution
        self.serial = serial
        self.color = "Blue"
        self.calibration_chip = False
        self.printer_head_id = None
        self.head_type_id = None
        self.display_name = None
        self.nominal_nozzle_diameter_um = None
        self.measured_nozzle_diameter_um = None
        self.manufacturer_batch = None
        self.identity_tags = []
        self.identity_notes = ""

    def get_stock_solution(self):
        return self._stock_solution

    def set_identity_metadata(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


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


def _configure_local_calibration_memory(monkeypatch, tmp_path):
    template_root = tmp_path / "FreeRTOS-interface" / "CalibrationMemory"
    local_dir = tmp_path / "local"
    entities_dir = template_root / "entities"
    entities_dir.mkdir(parents=True)
    local_dir.mkdir()
    (template_root / "schema.json").write_text(
        json.dumps({"schema_family": "labcraft.calibration_memory", "schema_version": 1}, indent=2),
        encoding="utf-8",
    )
    (template_root / "config.json").write_text(
        json.dumps(
            {
                "schema_name": "labcraft.calibration_memory.runtime_config",
                "schema_version": 1,
                "memory_enabled": True,
                "observation_capture_level": "compact",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (entities_dir / "reagents.json").write_text(
        json.dumps(
            {
                "schema_name": "labcraft.calibration_memory.reagents_registry",
                "schema_version": 1,
                "items": [
                    {
                        "reagent_id": "water",
                        "display_name": "Water",
                        "aliases": ["water", "Water"],
                        "reagent_family": "aqueous",
                        "glycerol_percent": 0.0,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (entities_dir / "printer_head_types.json").write_text(
        json.dumps(
            {
                "schema_name": "labcraft.calibration_memory.printer_head_types_registry",
                "schema_version": 1,
                "items": [
                    {
                        "head_type_id": "nozzle_100um",
                        "display_name": "100 um nozzle",
                        "nominal_nozzle_diameter_um": 100.0,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (entities_dir / "printer_heads.json").write_text(
        json.dumps(
            {
                "schema_name": "labcraft.calibration_memory.printer_heads_registry",
                "schema_version": 1,
                "items": [
                    {
                        "printer_head_id": "PH-001",
                        "head_type_id": "nozzle_100um",
                        "display_name": "100 um H01",
                        "nominal_nozzle_diameter_um": 100.0,
                        "aliases": ["PH-001"],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(LocalConfig, "CALIBRATION_MEMORY_TEMPLATE_DIR", template_root)
    monkeypatch.setattr(LocalConfig, "LOCAL_DIR", local_dir)
    return template_root, local_dir / "CalibrationMemory"


def test_calibration_memory_store_default_root_uses_local_config(monkeypatch, tmp_path):
    _template_root, local_root = _configure_local_calibration_memory(monkeypatch, tmp_path)

    store = CalibrationMemoryStore()
    store.ensure_initialized()

    assert Path(store.root_dir) == local_root.resolve()
    assert (local_root / "config.json").exists()
    assert (local_root / "entities" / "reagents.json").exists()
    assert not (local_root / "analysis").exists()


def test_runtime_config_updates_local_config_not_template(monkeypatch, tmp_path):
    template_root, local_root = _configure_local_calibration_memory(monkeypatch, tmp_path)
    template_config_path = template_root / "config.json"
    template_before = template_config_path.read_text(encoding="utf-8")

    store = CalibrationMemoryStore()
    store.set_memory_enabled(False)

    assert json.loads((local_root / "config.json").read_text(encoding="utf-8"))["memory_enabled"] is False
    assert template_config_path.read_text(encoding="utf-8") == template_before


def test_completed_run_and_aggregation_write_under_local_root(monkeypatch, tmp_path):
    template_root, local_root = _configure_local_calibration_memory(monkeypatch, tmp_path)
    model = _make_dummy_model(tmp_path)
    store = CalibrationMemoryStore(model=model)
    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    store.create_run("run_local_001", context=context, notes="local root")

    store.write_run_summary(
        "run_local_001",
        {
            "context": context,
            "run_status": "completed",
            "run_timing": {
                "started_at_utc": "2026-03-06T18:00:00Z",
                "ended_at_utc": "2026-03-06T18:10:00Z",
            },
            "phase_counts": {"droplet_search": 1},
            "process_results": {
                "droplet_search": {
                    "step_count": 1,
                    "latest_settings": {"print_width": 1500},
                    "latest_result": {
                        "pressure": 1.6,
                        "mean_volume": 9.8,
                        "cv_volume_percent": 4.1,
                        "valid": True,
                        "print_pulse_width_us": 1500,
                    },
                }
            },
        },
    )
    store.refresh_derived_memory()

    assert (local_root / "runs" / "run_local_001" / "run_summary.json").exists()
    assert (local_root / "indices" / "run_catalog.jsonl").exists()
    assert (local_root / "indices" / "recommendation_index.json").exists()
    assert not (template_root / "runs").exists()
    assert not (template_root / "indices").exists()


def test_calibration_memory_store_creates_run_summary_catalog_and_observations(tmp_path):
    model = _make_dummy_model(tmp_path)
    store = CalibrationMemoryStore(model=model, root_dir=str(tmp_path / "CalibrationMemory"))
    config = store.load_runtime_config()
    assert config["memory_enabled"] is True
    assert config["observation_capture_level"] == "compact"

    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    assert context["stock_id"] == "Water_0.00_--"
    assert context["reagent_id"] == "water"
    assert context["printer_head_id"] == "PH-001"
    assert context["reagent_family"] == "aqueous"
    assert context["identity_quality"]["reagent_id"] == "inferred"
    assert context["identity_quality"]["printer_head_id"] == "explicit"
    assert (Path(store.root_dir) / "entities" / "reagents.json").exists()

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
    assert observations[0]["context"]["stock_id"] == "Water_0.00_--"

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


def test_context_builder_prefers_explicit_runtime_identity_metadata(tmp_path):
    model = _make_dummy_model(tmp_path)
    stock = model.rack_model.get_gripper_printer_head().get_stock_solution()
    stock.set_reagent_identity(
        reagent_id="glycerol_25pct",
        display_name="25% Glycerol",
        reagent_family="aqueous_glycerol",
        glycerol_percent=25.0,
        tags=["baseline_study"],
    )
    printer_head = model.rack_model.get_gripper_printer_head()
    printer_head.set_identity_metadata(
        printer_head_id="nozzle_100um_h03",
        head_type_id="nozzle_100um",
        display_name="100 um H03",
        nominal_nozzle_diameter_um=100.0,
        measured_nozzle_diameter_um=101.2,
        manufacturer_batch="batch-a",
        tags=["baseline_study"],
    )

    store = CalibrationMemoryStore(model=model, root_dir=str(tmp_path / "CalibrationMemory"))
    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )

    assert context["reagent_id"] == "glycerol_25pct"
    assert context["reagent_display_name"] == "25% Glycerol"
    assert context["identity_quality"]["reagent_id"] == "explicit"
    assert context["printer_head_id"] == "nozzle_100um_h03"
    assert context["head_type_id"] == "nozzle_100um"
    assert context["nominal_nozzle_diameter_um"] == 100.0
    assert context["measured_nozzle_diameter_um"] == 101.2
    assert context["identity_quality"]["printer_head_id"] == "explicit"
    assert context["identity_quality"]["head_type_id"] == "explicit"


def test_completed_summary_write_still_succeeds_if_snapshot_refresh_fails(tmp_path, monkeypatch):
    model = _make_dummy_model(tmp_path)
    store = CalibrationMemoryStore(model=model, root_dir=str(tmp_path / "CalibrationMemory"))
    built_context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    store.create_run("run_complete", context=built_context, notes="refresh failure")

    summary = store.write_run_summary(
        "run_complete",
        {
            "context": built_context,
            "run_status": "completed",
            "run_timing": {
                "started_at_utc": "2026-03-06T18:00:00Z",
                "ended_at_utc": "2026-03-06T18:10:00Z",
            },
            "phase_counts": {
                "droplet_search": 1,
            },
            "process_results": {
                "droplet_search": {
                    "step_count": 1,
                    "latest_settings": {"print_width": 1500},
                    "latest_result": {
                        "pressure": 1.6,
                        "mean_volume": 9.8,
                        "cv_volume_percent": 4.1,
                        "valid": True,
                        "print_pulse_width_us": 1500,
                    },
                }
            },
        },
    )

    assert summary["run_id"] == "run_complete"
    saved = json.loads(Path(store.get_run_paths("run_complete")["run_summary_path"]).read_text(encoding="utf-8"))
    assert saved["run_status"] == "completed"
    assert store.is_derived_memory_dirty() is True

    def _boom():
        raise RuntimeError("snapshot rebuild failed")

    monkeypatch.setattr(store.aggregator, "rebuild", _boom)
    with pytest.raises(RuntimeError, match="snapshot rebuild failed"):
        store.refresh_derived_memory()
    assert store.is_derived_memory_dirty() is True
