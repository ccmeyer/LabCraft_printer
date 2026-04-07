from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs(force=True)

from CalibrationClasses.Model import CalibrationManager
from CalibrationMemoryStore import CalibrationMemoryStore


class _DummyStockSolution:
    def __init__(self):
        self.reagent_id = "water"
        self.display_name = "Water"
        self.reagent_family = "aqueous"
        self.glycerol_percent = 0.0
        self.tags = ["baseline"]
        self.notes = ""

    def get_stock_id(self):
        return "Water_0.00_--"

    def get_reagent_name(self):
        return "Water"

    def get_stock_concentration(self):
        return "0.00"


class _DummyPrinterHead:
    def __init__(self, stock_solution):
        self._stock_solution = stock_solution
        self.serial = "PH-001"
        self.printer_head_id = "nozzle_100um_h03"
        self.head_type_id = "nozzle_100um"
        self.display_name = "100 um H03"
        self.nominal_nozzle_diameter_um = 100.0
        self.identity_tags = ["baseline"]
        self.identity_notes = ""
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
        get_current_print_pressure=lambda: 1.61,
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


def _write_online_stream_summary_run(
    store,
    *,
    run_id: str,
    context: dict,
    pressure: float = 1.61,
    pulse_width_us: int = 1500,
    applied_flow_start_offset_us: int = 700,
    learned_flow_start_offset_us: int | None = None,
    applied_tail_start_offset_us: int = 3950,
    learned_tail_start_offset_us: int | None = None,
):
    if learned_flow_start_offset_us is None:
        learned_flow_start_offset_us = int(applied_flow_start_offset_us)
    if learned_tail_start_offset_us is None:
        learned_tail_start_offset_us = int(applied_tail_start_offset_us)
    paths = store.create_run(run_id, context=context, notes=f"online-stream {run_id}")
    result = {
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
            "applied_flow_step_us": 200,
            "applied_flow_delay_count": 5,
            "applied_tail_start_offset_us": int(applied_tail_start_offset_us),
            "applied_tail_coarse_step_us": 100,
            "fallback_reason": "no_prior",
            "warnings": [],
        },
        "flow_phase": {
            "status": "captured",
            "plan": {
                "delay_offsets_from_emergence_us": [700, 900, 1100, 1300, 1500],
                "point_count": 5,
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
    }
    summary = {
        "context": context,
        "run_status": "completed",
        "run_timing": {
            "started_at_utc": "2026-04-01T10:00:00Z",
            "ended_at_utc": "2026-04-01T10:05:00Z",
        },
        "notes": f"online-stream {run_id}",
        "phase_counts": {
            "online_stream_calibration": 1,
        },
        "process_results": {
            "online_stream_calibration": {
                "step_count": 1,
                "latest_settings": {"print_width": int(pulse_width_us), "print_pressure": float(pressure)},
                "latest_result": result,
            }
        },
        "artifact_refs": {},
        "source_refs": paths,
        "authoritative_refs": {},
        "last_updated_at_utc": "2026-04-01T10:05:00Z",
    }
    summary["derived_metrics"] = store.aggregator.extract_run_features(summary)
    store.write_run_summary(run_id, summary)


def test_store_returns_exact_condition_online_stream_prior(tmp_path):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    _write_online_stream_summary_run(store, run_id="stream_run_01", context=context)

    prior = store.get_best_online_stream_prior(
        context,
        target_pulse_width_us=1500,
        target_print_pressure_psi=1.61,
    )

    assert prior["aggregation_level"] == "exact_pair"
    assert prior["pulse_match_type"] == "exact"
    assert prior["print_pressure_psi"] == 1.61
    assert prior["flow_start_offset_us"] == 700
    assert prior["tail_start_offset_us"] == 3950
    assert prior["source"] == "calibration_memory"
    assert prior["source_run_ids"] == ["stream_run_01"]


def test_store_prefers_learned_online_stream_timings_over_applied_seed_schedule(tmp_path):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    _write_online_stream_summary_run(
        store,
        run_id="stream_run_01",
        context=context,
        applied_flow_start_offset_us=700,
        learned_flow_start_offset_us=850,
        applied_tail_start_offset_us=3950,
        learned_tail_start_offset_us=4100,
    )

    prior = store.get_best_online_stream_prior(
        context,
        target_pulse_width_us=1500,
        target_print_pressure_psi=1.61,
    )

    assert prior["flow_start_offset_us"] == 850
    assert prior["tail_start_offset_us"] == 4100


def test_store_does_not_reuse_online_stream_prior_across_pressure_mismatch(tmp_path):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    _write_online_stream_summary_run(store, run_id="stream_run_01", context=context, pressure=1.61)

    prior = store.get_best_online_stream_prior(
        context,
        target_pulse_width_us=1500,
        target_print_pressure_psi=1.67,
    )

    assert prior is None


def test_manager_resolve_online_stream_prior_falls_back_on_malformed_candidate(tmp_path, monkeypatch):
    model = _make_model(tmp_path)
    manager = CalibrationManager(model)
    manager.begin_session(model.experiment_model.calibration_file_path, notes="malformed prior")

    monkeypatch.setattr(
        model.calibration_memory_store,
        "get_best_online_stream_prior",
        lambda *args, **kwargs: {
            "source": "calibration_memory",
            "condition_match": "exact",
            "flow_start_offset_us": 725,
        },
    )

    resolved = manager.resolve_online_stream_calibration_prior(
        condition={
            "print_pressure_psi": 1.61,
            "print_pulse_width_us": 1500,
            "emergence_time_us": 3200,
        }
    )

    assert resolved["normalized_prior"]["source"] == "default"
    assert resolved["result_priors"]["fallback_reason"] == "malformed_prior"
    manager.end_session()


def test_new_manager_instance_can_resolve_same_online_stream_prior(tmp_path):
    model = _make_model(tmp_path)
    store = model.calibration_memory_store
    context = store.context_builder.build(
        model=model,
        calibration_file_path=model.experiment_model.calibration_file_path,
    )
    _write_online_stream_summary_run(store, run_id="stream_run_01", context=context)

    manager_a = CalibrationManager(model)
    manager_a.begin_session(model.experiment_model.calibration_file_path, notes="manager a")
    first = manager_a.resolve_online_stream_calibration_prior(
        condition={"print_pressure_psi": 1.61, "print_pulse_width_us": 1500, "emergence_time_us": 3200}
    )
    manager_a.end_session()

    manager_b = CalibrationManager(model)
    manager_b.begin_session(model.experiment_model.calibration_file_path, notes="manager b")
    second = manager_b.resolve_online_stream_calibration_prior(
        condition={"print_pressure_psi": 1.61, "print_pulse_width_us": 1500, "emergence_time_us": 3200}
    )
    manager_b.end_session()

    assert first["result_priors"]["candidate_found"] is True
    assert second["result_priors"]["candidate_found"] is True
    assert second["result_priors"]["source"] == "calibration_memory"
    assert second["result_priors"]["applied_flow_start_offset_us"] == 700
