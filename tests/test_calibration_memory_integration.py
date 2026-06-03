import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationMemoryStore import CalibrationMemoryStore
from CalibrationClasses.Model import BaseCalibrationProcess, CalibrationManager, OnlineStreamCalibrationProcess


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

    def get_display_stock_concentration(self):
        return self._concentration.rstrip("0").rstrip(".") if "." in self._concentration else self._concentration

    def get_stock_name(self):
        if self.units == "--":
            return self._reagent_name
        return f"{self._reagent_name} - {self.get_display_stock_concentration()} {self.units}"

    def get_display_stock_name(self):
        return self.get_stock_name()


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


def _set_loaded_stock(
    model,
    *,
    stock_id="Glycerol_10.00_mM",
    reagent_name="Glycerol",
    concentration="10.00",
    units="mM",
):
    stock = model.rack_model.get_gripper_printer_head().get_stock_solution()
    stock._stock_id = stock_id
    stock._reagent_name = reagent_name
    stock._concentration = concentration
    stock.units = units
    return stock


def _assert_glycerol_stock_fields(payload, *, concentration="10.00"):
    display_concentration = concentration.rstrip("0").rstrip(".")
    assert payload["stock_id"] == f"Glycerol_{concentration}_mM"
    assert payload["reagent_name"] == "Glycerol"
    assert payload["stock_solution"] == f"Glycerol - {display_concentration} mM"
    assert payload["concentration"] == concentration
    assert payload["display_concentration"] == display_concentration
    assert payload["units"] == "mM"
    assert payload["printer_head_id"] == "PH-001"
    assert payload["stock_identity"]["stock_id"] == f"Glycerol_{concentration}_mM"
    assert payload["stock_identity"]["stock_solution"] == f"Glycerol - {display_concentration} mM"


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


def _online_stream_result_payload(
    *,
    pressure: float = 1.62,
    pulse_width_us: int = 1500,
    applied_flow_start_offset_us: int = 700,
    learned_flow_start_offset_us: int = 850,
    applied_tail_start_offset_us: int = 3950,
    learned_tail_start_offset_us: int = 4100,
):
    return {
        "result": {
            "condition": {
                "print_pressure_psi": float(pressure),
                "print_pulse_width_us": int(pulse_width_us),
                "emergence_time_us": 3200,
                "stock_solution": "Water",
                "printer_head_id": "PH-001",
            },
            "priors": {
                "source": "default",
                "condition_match": "none",
                "applied_flow_start_offset_us": int(applied_flow_start_offset_us),
                "applied_flow_step_us": 57,
                "applied_flow_delay_count": 15,
                "applied_tail_start_offset_us": int(applied_tail_start_offset_us),
                "applied_tail_coarse_step_us": 100,
                "fallback_reason": "no_prior",
                "warnings": [],
            },
            "flow_phase": {
                "status": "captured",
                "plan": {
                    "delay_offsets_from_emergence_us": [
                        700,
                        757,
                        814,
                        871,
                        928,
                        985,
                        1042,
                        1099,
                        1156,
                        1213,
                        1270,
                        1327,
                        1384,
                        1441,
                        1498,
                    ],
                    "point_count": 15,
                },
                "fit_status": "ok",
                "flow_rate_nl_per_us": 0.0187,
                "flow_fit_delay_start_from_emergence_us": int(learned_flow_start_offset_us),
            },
            "tail_phase": {
                "status": "captured",
                "plan": {
                    "coarse_start_offset_us": int(applied_tail_start_offset_us),
                    "coarse_step_us": 100,
                },
                "tail_start_delay_from_emergence_us": int(learned_tail_start_offset_us),
            },
            "predicted_stream_duration_us": int(learned_tail_start_offset_us),
            "predicted_volume_nl": 72.6,
            "learned_flow_start_offset_us": int(learned_flow_start_offset_us),
            "learned_tail_start_offset_us": int(learned_tail_start_offset_us),
            "warnings": [],
        }
    }


def _seed_completed_online_stream_prior_run(
    store,
    *,
    run_id: str,
    context: dict,
    pressure: float = 1.61,
    pulse_width_us: int = 1500,
):
    paths = store.create_run(run_id, context=context, notes=f"seed {run_id}")
    summary = {
        "context": context,
        "run_status": "completed",
        "run_timing": {
            "started_at_utc": "2026-04-01T10:00:00Z",
            "ended_at_utc": "2026-04-01T10:05:00Z",
        },
        "notes": f"seed {run_id}",
        "phase_counts": {
            "online_stream_calibration": 1,
        },
        "process_results": {
            "online_stream_calibration": {
                "step_count": 1,
                "latest_settings": {"print_width": int(pulse_width_us), "print_pressure": float(pressure)},
                "latest_result": _online_stream_result_payload(
                    pressure=pressure,
                    pulse_width_us=pulse_width_us,
                )["result"],
            }
        },
        "artifact_refs": {},
        "source_refs": paths,
        "authoritative_refs": {},
        "last_updated_at_utc": "2026-04-01T10:05:00Z",
    }
    summary["derived_metrics"] = store.aggregator.extract_run_features(summary)
    store.write_run_summary(run_id, summary)


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


def test_calibration_json_run_metadata_records_stock_concentration(tmp_path):
    model = _make_model(tmp_path)
    _set_loaded_stock(model)
    manager = CalibrationManager(model)

    manager.begin_session(model.experiment_model.calibration_file_path, notes="stock identity")

    run = manager.data["runs"][-1]
    _assert_glycerol_stock_fields(run)
    saved = json.loads(Path(model.experiment_model.calibration_file_path).read_text(encoding="utf-8"))
    _assert_glycerol_stock_fields(saved["runs"][-1])


def test_process_recorder_meta_records_stock_concentration(tmp_path):
    model = _make_model(tmp_path)
    _set_loaded_stock(model)
    manager = CalibrationManager(model)
    manager.calibration_file_path = model.experiment_model.calibration_file_path

    meta = manager._build_recorder_meta()

    _assert_glycerol_stock_fields(meta)
    assert meta["calibration_file_path"] == model.experiment_model.calibration_file_path


def test_calibration_step_metadata_records_stock_concentration(tmp_path):
    model = _make_model(tmp_path)
    _set_loaded_stock(model)
    manager = CalibrationManager(model)
    manager.begin_session(model.experiment_model.calibration_file_path, notes="step identity")
    manager.activeCalibration = SimpleNamespace(phase_name="droplet_search")

    manager.onCalibrationDataUpdated({"result": {"mean_volume": 10.01}})

    step = manager.data["runs"][-1]["steps"]["droplet_search"][-1]
    _assert_glycerol_stock_fields(step["meta"])


def test_flat_measurement_rows_record_stock_concentration(tmp_path):
    model = _make_model(tmp_path)
    _set_loaded_stock(model)
    manager = CalibrationManager(model)
    manager.nozzle_center_image_position = [20, 30]
    run_obj = {"flat_measurements": []}

    manager._try_append_flat_rows_from_payload(
        run_obj,
        "droplet_search",
        {
            "timestamp": "2026-03-17T11:00:00Z",
            "settings": {"print_width": 1500, "print_pressure": 1.62},
            "result": {"droplet_volumes": [9.9, 10.1]},
        },
    )

    assert len(run_obj["flat_measurements"]) == 2
    _assert_glycerol_stock_fields(run_obj["flat_measurements"][0])


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


def test_pressure_sweep_summary_rows_preserve_droplet_search_invalid_reason(tmp_path):
    model = _make_model(tmp_path)
    manager = CalibrationManager(model)
    manager.ensure_loaded = lambda: None
    manager._safe_get_stock_solution = lambda: "Water"
    manager.data = {
        "runs": [
            {
                "run_id": "run_invalid_search",
                "stock_solution": "Water",
                "steps": {
                    "droplet_search": [
                        {
                            "timestamp": "2026-03-17T11:00:00Z",
                            "settings": {"print_width": 1500, "print_pressure": 1.62},
                            "result": {
                                "pressure": 1.62,
                                "mean_volume": 9.87,
                                "cv_volume_percent": 6.4,
                                "valid": False,
                                "invalid_reason": "char_invalid_ratio_exceeded",
                                "print_pulse_width_us": 1500,
                                "delay_us": 4300,
                            },
                        }
                    ]
                },
            }
        ]
    }

    rows = manager.get_pressure_sweep_summary_rows()

    assert len(rows) == 1
    assert rows[0]["phase"] == "search"
    assert rows[0]["invalid_reason"] == "char_invalid_ratio_exceeded"


def test_pressure_sweep_summary_rows_separate_stock_concentrations(tmp_path):
    model = _make_model(tmp_path)
    _set_loaded_stock(model, concentration="10.00", stock_id="Glycerol_10.00_mM")
    manager = CalibrationManager(model)
    manager.ensure_loaded = lambda: None

    def _run(stock_id, concentration, mean_volume):
        display_concentration = concentration.rstrip("0").rstrip(".")
        stock_solution = f"Glycerol - {display_concentration} mM"
        stock_identity = {
            "stock_id": stock_id,
            "reagent_name": "Glycerol",
            "stock_solution": stock_solution,
            "concentration": concentration,
            "display_concentration": display_concentration,
            "units": "mM",
            "printer_head_id": "PH-001",
        }
        return {
            **stock_identity,
            "stock_identity": dict(stock_identity),
            "run_id": stock_id,
            "steps": {
                "droplet_search": [
                    {
                        "timestamp": "2026-03-17T11:00:00Z",
                        "settings": {"print_width": 1500, "print_pressure": 1.62},
                        "result": {
                            "pressure": 1.62,
                            "mean_volume": mean_volume,
                            "cv_volume_percent": 4.0,
                            "valid": True,
                        },
                    }
                ]
            },
        }

    manager.data = {
        "runs": [
            _run("Glycerol_10.00_mM", "10.00", 10.0),
            _run("Glycerol_20.00_mM", "20.00", 20.0),
        ]
    }

    rows = manager.get_pressure_sweep_summary_rows()
    assert [row["mean_nL"] for row in rows] == [10.0]

    _set_loaded_stock(model, concentration="20.00", stock_id="Glycerol_20.00_mM")
    rows = manager.get_pressure_sweep_summary_rows()
    assert [row["mean_nL"] for row in rows] == [20.0]


def test_emit_readiness_reports_pressure_sweep_prereqs_for_manual_characterization(tmp_path):
    model = _make_model(tmp_path)
    manager = CalibrationManager(model)
    captured = []
    manager.readinessChanged.connect(lambda readiness: captured.append(readiness))

    manager._emit_readiness()

    assert captured
    droplet_characterization = captured[-1]["droplet_characterization"]
    assert droplet_characterization["ready"] is False
    assert "Source nozzle center machine coordinates" in droplet_characterization["missing"]
    assert "Source nozzle center image coordinates" in droplet_characterization["missing"]
    assert "Source emergence time" in droplet_characterization["missing"]
    assert "Source droplet trajectory" in droplet_characterization["missing"]


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


def test_online_stream_manager_lifecycle_auto_closes_completed_session_and_reuses_learned_prior(tmp_path, monkeypatch):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    manager = CalibrationManager(model)

    class _OwnedOnlineStreamStub:
        phase_name = "online_stream_calibration"
        owns_calibration_memory_session = True
        supports_operator_verdict = False

        @staticmethod
        def missing_requirements(cm):
            return []

        def __init__(self, calibration_manager, model, *args, **kwargs):
            self.calibration_manager = calibration_manager
            self.model = model

    monkeypatch.setattr(manager, "start_active_calibration", lambda: None)
    monkeypatch.setattr(manager, "_record_stream_capture_process_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "_complete_stream_capture_queue_success", lambda: None)
    monkeypatch.setattr(manager, "_emit_readiness", lambda: None)

    started = manager._try_start_process(_OwnedOnlineStreamStub)

    assert started is True
    first_run_id = manager._run_id
    manager.onCalibrationDataUpdated(_online_stream_result_payload())
    manager.onCalibrationCompleted()

    assert manager._run_id is None
    assert manager._run_idx is None

    run_dir = Path(store.get_run_paths(first_run_id)["run_dir"])
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["run_status"] == "completed"

    manager_b = CalibrationManager(model)
    manager_b.begin_session(model.experiment_model.calibration_file_path, notes="reuse learned prior")
    resolved = manager_b.resolve_online_stream_calibration_prior(
        condition={"print_pressure_psi": 1.62, "print_pulse_width_us": 1500, "emergence_time_us": 3200}
    )
    manager_b.end_session()

    assert resolved["result_priors"]["candidate_found"] is True
    assert resolved["result_priors"]["applied_flow_start_offset_us"] == 850
    assert resolved["result_priors"]["applied_tail_start_offset_us"] == 4100
    assert resolved["result_priors"]["source_run_ids"] == [first_run_id]


def test_online_stream_stopped_session_is_closed_and_not_reused_as_prior(tmp_path, monkeypatch):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    manager = CalibrationManager(model)

    class _OwnedOnlineStreamStub:
        phase_name = "online_stream_calibration"
        owns_calibration_memory_session = True
        supports_operator_verdict = False

        @staticmethod
        def missing_requirements(cm):
            return []

        def __init__(self, calibration_manager, model, *args, **kwargs):
            self.calibration_manager = calibration_manager
            self.model = model

    monkeypatch.setattr(manager, "start_active_calibration", lambda: None)
    monkeypatch.setattr(manager, "_record_stream_capture_process_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "_emit_readiness", lambda: None)

    started = manager._try_start_process(_OwnedOnlineStreamStub)
    assert started is True
    stopped_run_id = manager._run_id
    manager.onCalibrationError("Calibration terminated by user")

    stopped_summary = json.loads(
        Path(store.get_run_paths(stopped_run_id)["run_dir"], "run_summary.json").read_text(encoding="utf-8")
    )
    assert stopped_summary["run_status"] == "stopped"

    manager_b = CalibrationManager(model)
    monkeypatch.setattr(manager_b, "start_active_calibration", lambda: None)
    monkeypatch.setattr(manager_b, "_record_stream_capture_process_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager_b, "_complete_stream_capture_queue_success", lambda: None)
    monkeypatch.setattr(manager_b, "_emit_readiness", lambda: None)

    started = manager_b._try_start_process(_OwnedOnlineStreamStub)
    assert started is True
    completed_run_id = manager_b._run_id
    manager_b.onCalibrationDataUpdated(
        _online_stream_result_payload(
            learned_flow_start_offset_us=900,
            learned_tail_start_offset_us=4200,
        )
    )
    manager_b.onCalibrationCompleted()

    manager_c = CalibrationManager(model)
    manager_c.begin_session(model.experiment_model.calibration_file_path, notes="after stopped + completed")
    resolved = manager_c.resolve_online_stream_calibration_prior(
        condition={"print_pressure_psi": 1.62, "print_pulse_width_us": 1500, "emergence_time_us": 3200}
    )
    manager_c.end_session()

    assert resolved["result_priors"]["candidate_found"] is True
    assert resolved["result_priors"]["applied_flow_start_offset_us"] == 900
    assert resolved["result_priors"]["applied_tail_start_offset_us"] == 4200
    assert resolved["result_priors"]["source_run_ids"] == [completed_run_id]


def test_online_stream_auto_started_session_preserves_prior_runtime_in_summary(tmp_path, monkeypatch):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    _seed_completed_online_stream_prior_run(
        store,
        run_id="seed_online_stream",
        context=context,
    )

    manager = CalibrationManager(model)
    monkeypatch.setattr(manager, "start_active_calibration", lambda: None)
    monkeypatch.setattr(manager, "_record_stream_capture_process_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "_complete_stream_capture_queue_success", lambda: None)
    monkeypatch.setattr(manager, "_emit_readiness", lambda: None)
    monkeypatch.setattr(manager, "_process_missing", lambda proc_cls, *args, **kwargs: [])

    def _fake_online_stream_init(self, calibration_manager, model, *args, **kwargs):
        self.calibration_manager = calibration_manager
        self.model = model
        self.phase_name = "online_stream_calibration"
        calibration_manager.resolve_online_stream_calibration_prior(
            condition={"print_pressure_psi": 1.61, "print_pulse_width_us": 1500, "emergence_time_us": 3200}
        )

    monkeypatch.setattr(OnlineStreamCalibrationProcess, "__init__", _fake_online_stream_init)

    started = manager._try_start_process(OnlineStreamCalibrationProcess)
    assert started is True
    run_id = manager._run_id
    manager.onCalibrationDataUpdated(_online_stream_result_payload(pressure=1.61))
    manager.onCalibrationCompleted()

    run_dir = Path(store.get_run_paths(run_id)["run_dir"])
    observations = [
        json.loads(line)
        for line in (run_dir / "observations.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))

    observation_types = {row["observation_type"] for row in observations}
    assert "online_stream_prior_lookup" in observation_types
    assert "online_stream_prior_applied" in observation_types
    assert summary["online_stream_prior_lookup_performed"] is True
    assert summary["online_stream_prior_candidate_found"] is True
    assert summary["online_stream_prior_applied"] is True
    assert summary["online_stream_prior_applied_prior"]["source"] == "calibration_memory"
