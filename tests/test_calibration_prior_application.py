import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

import CalibrationClasses.Model as calibration_model
from CalibrationClasses.Model import CalibrationManager, PressureBandCalibrationProcess
from CalibrationMemoryStore import CalibrationMemoryStore


class _DummyStockSolution:
    def __init__(self, stock_id="Water_0.00_--", reagent_name="Water"):
        self._stock_id = stock_id
        self._reagent_name = reagent_name
        self._concentration = "0.00"
        self.units = "--"
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
        return self.display_name or self._reagent_name


class _DummyPrinterHead:
    def __init__(self, stock_solution):
        self._stock_solution = stock_solution
        self.serial = "PH-001"
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


class _DummyState:
    def __init__(self, *args, **kwargs):
        self.entered = SignalStub()

    def addTransition(self, *args, **kwargs):
        return None


class _DummyStateMachine:
    def __init__(self, *args, **kwargs):
        self.states = []
        self.initial = None

    def addState(self, state):
        self.states.append(state)

    def setInitialState(self, state):
        self.initial = state

    def start(self):
        return None

    def stop(self):
        return None


def _make_model(tmp_path, *, explicit_identity=True):
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    calibration_path = experiment_dir / "calibration.json"

    stock = _DummyStockSolution()
    printer_head = _DummyPrinterHead(stock)
    if explicit_identity:
        stock.reagent_id = "water"
        stock.display_name = "Water"
        stock.reagent_family = "aqueous"
        stock.glycerol_percent = 0.0
        stock.tags = ["baseline"]
        printer_head.printer_head_id = "nozzle_100um_h03"
        printer_head.head_type_id = "nozzle_100um"
        printer_head.display_name = "100 um H03"
        printer_head.nominal_nozzle_diameter_um = 100.0
        printer_head.identity_tags = ["baseline"]

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
        get_save_root_directory=lambda: str(tmp_path / "captures"),
        get_active_save_directory=lambda: str(tmp_path / "captures" / "run_a"),
    )
    machine_model = SimpleNamespace(
        get_current_position_dict=lambda: {"X": 10, "Y": 20, "Z": 30},
        get_print_pulse_width=lambda: 1500,
        get_refuel_pulse_width=lambda: 0,
        get_current_print_pressure=lambda: 1.20,
        get_current_refuel_pressure=lambda: 0.0,
        get_print_pressure_bounds=lambda: (0.3, 2.0),
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


def _seed_completed_run(store, run_id, context, *, pressure=1.61, pulse_width_us=1500, band=None, ended_at="2026-03-06T18:10:00Z"):
    paths = store.create_run(run_id, context=context, notes="seed prior")
    band = band or [pressure - 0.10, pressure + 0.10]
    store.write_run_summary(
        run_id,
        {
            "context": context,
            "run_status": "completed",
            "run_timing": {
                "started_at_utc": "2026-03-06T18:00:00Z",
                "ended_at_utc": ended_at,
            },
            "phase_counts": {
                "droplet_search": 1,
                "pressure_scan": 1,
            },
            "process_results": {
                "droplet_search": {
                    "step_count": 1,
                    "latest_settings": {"print_width": pulse_width_us, "print_pressure": pressure},
                    "latest_result": {
                        "pressure": pressure,
                        "mean_volume": 9.95,
                        "cv_volume_percent": 4.1,
                        "valid": True,
                        "print_pulse_width_us": pulse_width_us,
                        "delay_us": 4300,
                    },
                },
                "pressure_scan": {
                    "step_count": 1,
                    "latest_settings": {"print_width": pulse_width_us},
                    "latest_result": {
                        "pulse_width_us": pulse_width_us,
                        "primary_band": list(band),
                        "delay_us": 4300,
                    },
                },
            },
            "artifact_refs": {},
            "source_refs": paths,
            "authoritative_refs": {},
            "last_updated_at_utc": ended_at,
        },
    )


def _seed_head_type_only_run(store, run_id="head_type_only_run"):
    legacy_context = {
        "reagent_id": "water",
        "reagent_family": "aqueous",
        "head_type_id": "nozzle_100um",
        "nozzle_diameter_um": 100.0,
        "identity_quality": {
            "reagent_id": "derived",
            "printer_head_id": "missing",
            "head_type_id": "derived",
        },
    }
    _seed_completed_run(
        store,
        run_id,
        legacy_context,
        pressure=1.55,
        band=[1.45, 1.65],
    )


def test_runtime_config_defaults_to_advisory_and_off_skips_lookup(tmp_path):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    config = store.load_runtime_config()
    assert config["prior_application_mode"] == "advisory"
    assert config["memory_enabled"] is True
    assert config["observation_capture_level"] == "compact"

    store.set_prior_application_mode("off")
    manager = CalibrationManager(model)
    manager.begin_session(model.experiment_model.calibration_file_path, notes="mode off")

    runtime = manager.get_calibration_memory_prior_runtime_summary()
    assert runtime["mode"] == "off"
    assert runtime["looked_up"] is False
    assert runtime["lookup_skipped_reason"] == "mode_off"


def test_memory_disabled_overrides_seed_start_and_skips_lookup(tmp_path):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    store.set_prior_application_mode("seed_start")
    store.set_memory_enabled(False)
    manager = CalibrationManager(model)

    manager.begin_session(model.experiment_model.calibration_file_path, notes="memory disabled")
    kwargs = manager._prepare_calibration_memory_prior_application(PressureBandCalibrationProcess, {})

    runtime = manager.get_calibration_memory_prior_runtime_summary()
    assert kwargs == {}
    assert runtime["memory_enabled"] is False
    assert runtime["lookup_skipped_reason"] == "memory_disabled"
    assert runtime["rejected_reason"] == "memory_disabled"


def test_exact_pair_prior_qualifies_and_seeds_pressure_scan_start_only(tmp_path, monkeypatch):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    store.set_prior_application_mode("seed_start")
    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    _seed_completed_run(store, "exact_prior", context, pressure=1.62, band=[1.52, 1.70])

    manager = CalibrationManager(model)
    manager.begin_session(model.experiment_model.calibration_file_path, notes="seed exact pair")

    monkeypatch.setattr(calibration_model, "QState", _DummyState)
    monkeypatch.setattr(calibration_model, "QFinalState", _DummyState)
    monkeypatch.setattr(calibration_model, "QStateMachine", _DummyStateMachine)
    monkeypatch.setattr(
        PressureBandCalibrationProcess,
        "missing_requirements",
        staticmethod(lambda _cm, *a, **k: []),
    )

    kwargs = manager._prepare_calibration_memory_prior_application(PressureBandCalibrationProcess, {})
    assert kwargs["start_pressure"] == pytest.approx(1.62)
    assert manager.start_pressure == pytest.approx(0.8)

    proc = PressureBandCalibrationProcess(manager, model, **kwargs)
    assert proc.start_pressure == pytest.approx(1.62)

    runtime = manager.get_calibration_memory_prior_runtime_summary()
    assert runtime["qualified"] is True
    assert runtime["applied"] is True
    assert runtime["seed_process"] == "PressureBandCalibrationProcess"
    assert runtime["seed_values"]["start_pressure_psi"] == pytest.approx(1.62)


def test_grouped_prior_is_rejected_for_seed_start_policy(tmp_path):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    store.set_prior_application_mode("seed_start")
    _seed_head_type_only_run(store)

    manager = CalibrationManager(model)
    manager.begin_session(model.experiment_model.calibration_file_path, notes="reject grouped")

    kwargs = manager._prepare_calibration_memory_prior_application(PressureBandCalibrationProcess, {})
    runtime = manager.get_calibration_memory_prior_runtime_summary()

    assert "start_pressure" not in kwargs
    assert runtime["candidate_found"] is True
    assert runtime["qualified"] is False
    assert runtime["rejected_reason"] in {"aggregation_level_not_allowed", "identity_quality_too_weak"}


def test_prior_fallback_triggers_on_early_mismatch_and_disables_future_seed_attempts(tmp_path):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    store.set_prior_application_mode("seed_start")
    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    _seed_completed_run(store, "exact_prior", context, pressure=1.60, band=[1.50, 1.68])

    manager = CalibrationManager(model)
    manager.begin_session(model.experiment_model.calibration_file_path, notes="fallback test")
    kwargs = manager._prepare_calibration_memory_prior_application(PressureBandCalibrationProcess, {})
    seed_pressure = kwargs["start_pressure"]

    manager.record_calibration_memory_prior_probe(
        phase_name="pressure_scan",
        pressure_psi=seed_pressure,
        verdict="multiple",
        decision_reason="synthetic_mismatch",
        confidence=0.9,
    )
    runtime = manager.get_calibration_memory_prior_runtime_summary()
    assert runtime["fallback_triggered"] is True
    assert runtime["fallback_reason"] == "seed_pressure_inside_predicted_band_but_behavior_mismatched"

    second_kwargs = manager._prepare_calibration_memory_prior_application(PressureBandCalibrationProcess, {})
    assert "start_pressure" not in second_kwargs


def test_lookup_failures_do_not_block_seed_start_session(tmp_path, monkeypatch):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    store.set_prior_application_mode("seed_start")

    def _boom(*args, **kwargs):
        raise RuntimeError("forced lookup failure")

    monkeypatch.setattr(store, "get_best_prior", _boom)

    manager = CalibrationManager(model)
    manager.begin_session(model.experiment_model.calibration_file_path, notes="lookup failure")
    kwargs = manager._prepare_calibration_memory_prior_application(PressureBandCalibrationProcess, {})

    runtime = manager.get_calibration_memory_prior_runtime_summary()
    assert kwargs == {}
    assert runtime["looked_up"] is False
    assert runtime["lookup_skipped_reason"] == "lookup_error"
    assert Path(model.experiment_model.calibration_file_path).exists()


def test_run_summary_records_prior_application_and_usefulness(tmp_path):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    store.set_prior_application_mode("seed_start")
    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    _seed_completed_run(store, "exact_prior", context, pressure=1.61, band=[1.50, 1.70])

    manager = CalibrationManager(model)
    manager.begin_session(model.experiment_model.calibration_file_path, notes="summary logging")
    kwargs = manager._prepare_calibration_memory_prior_application(PressureBandCalibrationProcess, {})
    manager.record_calibration_memory_prior_probe(
        phase_name="pressure_scan",
        pressure_psi=kwargs["start_pressure"],
        verdict="single",
        decision_reason="seed_probe",
        confidence=0.92,
    )
    manager.activeCalibration = SimpleNamespace(phase_name="pressure_scan")
    manager.onCalibrationDataUpdated(
        {
            "result": {
                "pulse_width_us": 1500,
                "primary_band": [1.50, 1.70],
                "delay_us": 4300,
            }
        }
    )
    manager.end_session()

    calibration_json = json.loads(Path(model.experiment_model.calibration_file_path).read_text(encoding="utf-8"))
    run_id = calibration_json["runs"][0]["run_id"]
    summary_path = Path(store.get_run_paths(run_id)["run_summary_path"])
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["prior_application_mode"] == "seed_start"
    assert summary["prior_applied"] is True
    assert summary["prior_candidate"]["aggregation_level"] == "exact_pair"
    assert summary["prior_seed_values"]["start_pressure_psi"] == pytest.approx(1.61)
    assert summary["prior_fallback_triggered"] is False
    assert summary["prior_usefulness_summary"]["steps_until_first_single"] == 1
    assert summary["prior_usefulness_summary"]["usefulness_signal"] in {"likely_helpful", "possibly_helpful"}
