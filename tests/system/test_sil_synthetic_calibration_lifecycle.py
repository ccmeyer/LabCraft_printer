from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from CalibrationClasses.Model import CalibrationManager
from ExecutionCalibrationStore import load_execution_calibrations
from ExecutionPlan import load_execution_plan
from Model import Model
from tests.calibration_test_utils import SignalStub
from tools.sil.calibration_application import SyntheticCalibrationApplicationAdapter


class _Recorder:
    healthy = True

    def __init__(self):
        self.events = []

    def record_event(self, kind, **kwargs):
        self.events.append((kind, kwargs))


def _configure_single_stock_design(em):
    em.factors = []
    em.add_additive(
        "Virtual Calibration Stock",
        [1.0],
        "x",
        10.0,
        forced_stock_conc=10.0,
        printing_mode="droplet",
    )
    em.set_metadata(
        name="sil-m4a-single-stock",
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=24,
        target_reaction_volume_nL=2500.0,
        final_reaction_volume_nL=2500.0,
        printed_volume_tolerance_nL=50.0,
        fill_reagent_name="Water",
        fill_printing_mode="droplet",
        fill_droplet_volume_nL=10.0,
    )
    em.set_well_selection([f"A{column}" for column in range(1, 25)])
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()


def test_synthetic_droplet_result_revises_and_reloads_authoritative_bundle(
    experiment_model_factory,
    tmp_path,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_single_stock_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    prepared = em.get_execution_plan_snapshot()
    non_fill_stocks = [
        item for item in prepared.stocks if item.factor_name != "Water"
    ]
    assert len(non_fill_stocks) == 1
    assert len(prepared.wells) == 24
    stock = non_fill_stocks[0]

    head = SimpleNamespace(
        serial="virtual-head-m4a",
        printer_head_id="virtual-head-m4a",
        get_stock_id=lambda: stock.stock_id,
        get_printing_mode=lambda: "droplet",
    )
    model.machine_state_updated = SignalStub()
    model.rack_model = SimpleNamespace(get_gripper_printer_head=lambda: head)
    model.machine_model = SimpleNamespace(
        get_target_print_pressure=lambda: 1.2,
        get_print_pulse_width=lambda: 1400,
    )
    model.calibration_manager = CalibrationManager(model)
    model.calibration_manager.ensure_loaded = lambda: None
    model.calibration_manager.data = {"runs": []}

    machine = SimpleNamespace(
        state=SimpleNamespace(
            connected=True,
            motors_enabled=True,
            homed=True,
            regulating_print_pressure=True,
            simulated_elapsed_ms=50,
        ),
        check_if_all_completed=lambda: True,
    )
    controller = SimpleNamespace(get_array_run_state=lambda: "idle")
    recorder = _Recorder()
    adapter = SyntheticCalibrationApplicationAdapter(
        session_root=tmp_path,
        session_id="lifecycle-session",
        application_session_id="application-1",
        seed=25,
        model=model,
        controller=controller,
        machine=machine,
        recorder=recorder,
        open_dialog_callback=lambda _candidate_id: object(),
    )

    generation = adapter.generate_and_present_nominal_droplet()
    assert generation["ok"] is True
    result = adapter.current_result
    row = model.calibration_manager.get_characterization_summary_rows()[0]
    before_targets = {
        well.well_id: tuple(
            (dispense.stock_id, dispense.target_dispenses)
            for dispense in well.dispenses
        )
        for well in prepared.wells
    }

    em.apply_droplet_volume_for_option(
        result.factor_name,
        result.option_name,
        result.effective_volume_nL,
        write_keys_if_assigned=True,
        printing_mode=result.applied_printing_mode,
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": result.measured_volume_nL,
            "pw_us": result.pw_us,
            "pressure_psi": result.pressure_psi,
            "run_id": result.run_id,
            "phase": result.phase,
            "timestamp": result.timestamp,
            "source_row_fingerprint": row["source_row_fingerprint"],
            "original_printing_mode": result.original_printing_mode,
            "applied_printing_mode": result.applied_printing_mode,
        },
    )

    calibrated = em.get_execution_plan_snapshot()
    assert calibrated.plan_revision == prepared.plan_revision + 2
    calibrated_stock = next(
        item for item in calibrated.stocks if item.stock_id == stock.stock_id
    )
    assert calibrated_stock.printer_head_id == "virtual-head-m4a"
    assert calibrated_stock.effective_volume_nL == result.effective_volume_nL
    after_targets = {
        well.well_id: tuple(
            (dispense.stock_id, dispense.target_dispenses)
            for dispense in well.dispenses
        )
        for well in calibrated.wells
    }
    assert after_targets != before_targets

    persisted_plan = load_execution_plan(em.execution_plan_file_path)
    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    calibrations = load_execution_calibrations(em.execution_calibrations_file_path)
    assert persisted_plan == calibrated
    assert progress["plan_revision"] == calibrated.plan_revision
    assert calibrated_stock.calibration_record_key in calibrations.records
    persisted_record = calibrations.records[calibrated_stock.calibration_record_key]
    assert persisted_record.source_row_fingerprint == tuple(result.source_row_fingerprint)
    assert persisted_record.pressure_psi == result.pressure_psi
    assert persisted_record.pw_us == result.pw_us
    assert not Path(em.calibration_file_path).exists()
    assert "synthetic_calibration_applied" in [kind for kind, _payload in recorder.events]

    loaded = experiment_model_factory()
    loaded_em = loaded.experiment_model
    loaded_em.load_experiment(em.experiment_file_path, em.experiment_dir_path)
    eligibility = loaded.load_authoritative_execution_runtime()
    reloaded = loaded_em.get_execution_plan_snapshot()
    assert eligibility["status"] == "ready_to_start"
    assert reloaded == calibrated
    assert load_execution_calibrations(loaded_em.execution_calibrations_file_path) == calibrations
