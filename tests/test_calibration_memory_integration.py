import json
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def _seed_completed_prior_run(store, run_id, context, *, pressure=1.61, pulse_width_us=1500):
    paths = store.create_run(run_id, context=context, notes="seed prior")
    store.write_run_summary(
        run_id,
        {
            "context": context,
            "run_status": "completed",
            "run_timing": {
                "started_at_utc": "2026-03-06T18:00:00Z",
                "ended_at_utc": "2026-03-06T18:10:00Z",
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
                        "primary_band": [pressure - 0.10, pressure + 0.10],
                        "delay_us": 4300,
                    },
                },
            },
            "artifact_refs": {},
            "source_refs": paths,
            "authoritative_refs": {},
            "last_updated_at_utc": "2026-03-06T18:10:00Z",
        },
    )


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
    manager.end_session()
    run_dir = Path(model.calibration_memory_store.get_run_paths(run_id)["run_dir"])
    observations = [
        json.loads(line)
        for line in (run_dir / "observations.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    observation_types = {row["observation_type"] for row in observations}
    assert "process_analysis" in observation_types
    assert "process_event" not in observation_types
    assert all(row["context"]["stock_id"] == "Water_0.00_--" for row in observations)
    assert all("current_position" in (row.get("settings") or {}) for row in observations)

    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == run_id
    assert summary["context"]["stock_id"] == "Water_0.00_--"
    assert summary["process_results"]["droplet_search"]["latest_result"]["mean_volume"] == 9.91
    assert summary["memory_enabled"] is True
    assert summary["observation_capture_level"] == "compact"


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


def test_begin_session_records_advisory_prior_without_changing_behavior(tmp_path):
    model = _make_model(tmp_path)
    printer_head = model.rack_model.get_gripper_printer_head()
    stock = printer_head.get_stock_solution()
    stock.reagent_id = "water"
    stock.display_name = "Water"
    stock.reagent_family = "aqueous"
    stock.glycerol_percent = 0.0
    stock.tags = ["baseline"]
    stock.notes = ""
    printer_head.printer_head_id = "nozzle_100um_h03"
    printer_head.head_type_id = "nozzle_100um"
    printer_head.display_name = "100 um H03"
    printer_head.nominal_nozzle_diameter_um = 100.0
    printer_head.identity_tags = ["baseline"]
    printer_head.identity_notes = ""

    store = model.calibration_memory_store
    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    paths = store.create_run("prior_run", context=context, notes="seed prior")
    store.write_run_summary(
        "prior_run",
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
                        "pressure": 1.61,
                        "mean_volume": 9.95,
                        "cv_volume_percent": 4.1,
                        "valid": True,
                        "print_pulse_width_us": 1500,
                        "delay_us": 4300,
                    },
                }
            },
            "artifact_refs": {},
            "source_refs": paths,
            "authoritative_refs": {},
            "last_updated_at_utc": "2026-03-06T18:10:00Z",
        },
    )

    manager = CalibrationManager(model)
    manager.begin_session(model.experiment_model.calibration_file_path, notes="advisory test")

    run_id = manager._run_id
    run_dir = Path(store.get_run_paths(run_id)["run_dir"])
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    observations = [
        json.loads(line)
        for line in (run_dir / "observations.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert summary["advisory_prior"]["aggregation_level"] == "exact_pair"
    assert summary["advisory_prior"]["advisory_only"] is True
    assert manager._calibration_memory_prior_candidate["recommended_pressure_psi"] == pytest.approx(1.61)
    assert any(row["observation_type"] == "advisory_prior_lookup" for row in observations)


def test_memory_disabled_skips_sidecar_run_lookup_and_observations(tmp_path):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    store.set_memory_enabled(False)
    store.set_prior_application_mode("seed_start")
    manager = CalibrationManager(model)

    manager.begin_session(model.experiment_model.calibration_file_path, notes="memory disabled")
    manager.activeCalibration = SimpleNamespace(phase_name="droplet_search")
    process = BaseCalibrationProcess(manager, model)
    process.phase_name = "droplet_search"
    process._record_event("candidate_found", {"flash_delay_us": 4300})
    process._record_analysis({"kind": "characterization_frame", "volume_nL": 9.91})
    manager.onCalibrationDataUpdated({"result": {"mean_volume": 9.91}})

    runtime = manager.get_calibration_memory_prior_runtime_summary()
    assert runtime["memory_enabled"] is False
    assert runtime["lookup_skipped_reason"] in {None, "memory_disabled"}
    assert list(Path(store.runs_dir).glob("*")) == []
    manager.end_session()


def test_verbose_capture_level_restores_process_event_mirroring(tmp_path):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    store.set_observation_capture_level("verbose")
    manager = CalibrationManager(model)

    manager.begin_session(model.experiment_model.calibration_file_path, notes="verbose")
    manager.activeCalibration = SimpleNamespace(phase_name="droplet_search")
    process = BaseCalibrationProcess(manager, model)
    process.phase_name = "droplet_search"
    process._record_event("candidate_found", {"flash_delay_us": 4300})
    process._record_analysis({"kind": "characterization_frame", "volume_nL": 9.91})
    manager.end_session()

    run_dir = Path(store.get_run_paths(manager.data["runs"][-1]["run_id"])["run_dir"])
    observations = [
        json.loads(line)
        for line in (run_dir / "observations.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    observation_types = {row["observation_type"] for row in observations}
    assert "process_event" in observation_types
    assert "process_analysis" in observation_types


def test_on_calibration_data_updated_does_not_rewrite_sidecar_summary_each_step(tmp_path, monkeypatch):
    model = _make_model(tmp_path)
    manager = CalibrationManager(model)
    store = model.calibration_memory_store

    manager.begin_session(model.experiment_model.calibration_file_path, notes="summary cadence")
    manager.activeCalibration = SimpleNamespace(phase_name="droplet_search")

    calls = []

    def _counting_write(run_id, payload):
        calls.append((run_id, payload))
        return payload

    monkeypatch.setattr(store, "write_run_summary", _counting_write)
    manager.onCalibrationDataUpdated({"result": {"mean_volume": 10.01}})

    assert calls == []


def test_ui_recommendation_events_are_flushed_into_sidecar_run(tmp_path):
    model = _make_model(tmp_path)
    printer_head = model.rack_model.get_gripper_printer_head()
    stock = printer_head.get_stock_solution()
    stock.reagent_id = "water"
    stock.display_name = "Water"
    stock.reagent_family = "aqueous"
    stock.glycerol_percent = 0.0
    printer_head.printer_head_id = "nozzle_100um_h03"
    printer_head.head_type_id = "nozzle_100um"
    printer_head.display_name = "100 um H03"
    printer_head.nominal_nozzle_diameter_um = 100.0

    store = model.calibration_memory_store
    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    _seed_completed_prior_run(store, "ui_prior", context)

    manager = CalibrationManager(model)
    preview = manager.preview_calibration_memory_recommendation(
        target_pulse_width_us=1500,
        target_volume_nl=10.0,
    )
    assert preview["candidate_found"] is True

    manager.record_calibration_memory_ui_interaction(
        "shown",
        preview,
        extra={"visible_in_dialog": True},
    )
    manager.record_calibration_memory_ui_interaction(
        "applied",
        preview,
        extra={
            "seeded_start_pressure_psi": 1.61,
            "seeded_pulse_width_us": 1500,
        },
    )

    manager.begin_session(model.experiment_model.calibration_file_path, notes="ui recommendation")
    manager.end_session()

    run_dir = Path(store.get_run_paths(manager.data["runs"][-1]["run_id"])["run_dir"])
    observations = [
        json.loads(line)
        for line in (run_dir / "observations.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))

    assert any(row["observation_type"] == "ui_recommendation_shown" for row in observations)
    assert any(row["observation_type"] == "ui_recommendation_applied" for row in observations)
    ui_summary = summary["ui_recommendation"]
    assert ui_summary["shown"] is True
    assert ui_summary["applied"] is True
    assert ui_summary["aggregation_level"] == "exact_pair"
    assert ui_summary["confidence"] == pytest.approx(
        preview["prior"]["recommendation_confidence_adjusted"]
    )
