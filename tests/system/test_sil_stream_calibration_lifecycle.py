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
from tools.sil.manual_refuel import SimulatedManualRefuelOutcomeAdapter


class _Recorder:
    healthy = True

    def __init__(self):
        self.events = []

    def record_event(self, kind, **kwargs):
        self.events.append((kind, kwargs))


def _configure_stream_transition_design(em):
    em.factors = []
    em.add_additive(
        "Virtual Stream Stock",
        [1.0],
        "x",
        9.0,
        forced_stock_conc=10.0,
        printing_mode="droplet",
    )
    em.set_metadata(
        name="sil-m4b-stream-transition",
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


def test_stream_transition_refuel_pass_and_reload_authoritative_bundle(
    experiment_model_factory,
    tmp_path,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_stream_transition_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    prepared = em.get_execution_plan_snapshot()
    stock = next(item for item in prepared.stocks if item.factor_name != "Water")
    assert stock.effective_volume_nL == 9.0
    assert stock.printing_mode == "droplet"

    mode = {"value": "droplet"}
    head = SimpleNamespace(
        serial="virtual-head-m4b",
        printer_head_id="virtual-head-m4b",
        get_stock_id=lambda: stock.stock_id,
        get_printing_mode=lambda: mode["value"],
        set_printing_mode=lambda value: mode.update(value=str(value)),
    )
    model.machine_state_updated = SignalStub()
    model.rack_model = SimpleNamespace(get_gripper_printer_head=lambda: head)
    model.machine_model = SimpleNamespace(
        get_target_print_pressure=lambda: 1.2,
        get_current_print_pressure=lambda: 1.2,
        get_print_pulse_width=lambda: 1400,
        get_target_refuel_pressure=lambda: 0.4,
        get_current_refuel_pressure=lambda: 0.4,
        get_refuel_pulse_width=lambda: 2400,
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
            regulating_refuel_pressure=True,
            simulated_elapsed_ms=50,
        ),
        check_if_all_completed=lambda: True,
    )
    recorder = _Recorder()

    def refuel_preflight():
        return em.validate_manual_refuel_check_for_print(
            printer_head=head,
            machine_model=model.machine_model,
        )

    def record_refuel(status, source, **kwargs):
        return em.record_manual_refuel_check_outcome(
            status=status,
            source=source,
            printer_head=head,
            machine_model=model.machine_model,
            **kwargs,
        )

    controller = SimpleNamespace(
        get_array_run_state=lambda: "idle",
        get_print_array_refuel_check_preflight=refuel_preflight,
        record_manual_refuel_check_outcome=record_refuel,
    )
    calibration = SyntheticCalibrationApplicationAdapter(
        session_root=tmp_path,
        session_id="stream-lifecycle",
        application_session_id="application-1",
        seed=1,
        model=model,
        controller=controller,
        machine=machine,
        recorder=recorder,
        open_dialog_callback=lambda _candidate_id: object(),
    )

    generated = calibration.generate_and_present("droplet_to_stream")
    assert generated["ok"] is True
    result = calibration.current_result
    assert result.source_volume_nL == 9.0
    assert result.target_volume_nL == 40.0
    assert result.measured_volume_nL == 40.0
    row = model.calibration_manager.get_characterization_summary_rows()[0]

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
    head.set_printing_mode("stream")
    required = refuel_preflight()
    assert required["code"] == "required_refuel_check"

    refuel = SimulatedManualRefuelOutcomeAdapter(
        seed=1,
        model=model,
        controller=controller,
        machine=machine,
        recorder=recorder,
    )
    passed = refuel.record_outcome("passed")
    assert passed["after_preflight"]["code"] == "passed_refuel_check"

    second_generation = calibration.generate_and_present("nominal_stream")
    assert second_generation["ok"] is True
    second_result = calibration.current_result
    second_row = model.calibration_manager.get_characterization_summary_rows()[0]
    em.apply_droplet_volume_for_option(
        second_result.factor_name,
        second_result.option_name,
        second_result.effective_volume_nL,
        write_keys_if_assigned=True,
        printing_mode=second_result.applied_printing_mode,
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": second_result.measured_volume_nL,
            "pw_us": second_result.pw_us,
            "pressure_psi": second_result.pressure_psi,
            "run_id": second_result.run_id,
            "phase": second_result.phase,
            "timestamp": second_result.timestamp,
            "source_row_fingerprint": second_row["source_row_fingerprint"],
            "original_printing_mode": second_result.original_printing_mode,
            "applied_printing_mode": second_result.applied_printing_mode,
        },
    )
    invalidated = em.get_manual_refuel_check(printer_head=head)
    assert invalidated["status"] == "required"
    assert invalidated["previous_status"] == "passed"
    assert refuel_preflight()["code"] == "required_refuel_check"
    second_pass = refuel.record_outcome("passed")
    assert second_pass["after_preflight"]["code"] == "passed_refuel_check"

    calibrated = em.get_execution_plan_snapshot()
    calibrated_stock = next(
        item for item in calibrated.stocks if item.stock_id == stock.stock_id
    )
    assert calibrated.plan_revision > prepared.plan_revision
    assert calibrated_stock.printing_mode == "stream"
    assert calibrated_stock.effective_volume_nL == 40.0

    persisted_plan = load_execution_plan(em.execution_plan_file_path)
    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    calibrations = load_execution_calibrations(em.execution_calibrations_file_path)
    assert persisted_plan == calibrated
    assert progress["plan_revision"] == calibrated.plan_revision
    assert len(calibrations.manual_refuel_checks) == 1
    refuel_record = next(iter(calibrations.manual_refuel_checks.values()))
    assert refuel_record["status"] == "passed"
    assert refuel_record["source"] == "sil_simulated_manual_refuel_check"
    assert json.loads(refuel_record["notes"])["provider_version"] == "milestone-4b-v1"

    loaded = experiment_model_factory()
    loaded_em = loaded.experiment_model
    loaded_em.load_experiment(em.experiment_file_path, em.experiment_dir_path)
    eligibility = loaded.load_authoritative_execution_runtime()
    reloaded = loaded_em.get_execution_plan_snapshot()
    reloaded_calibrations = load_execution_calibrations(
        loaded_em.execution_calibrations_file_path
    )
    assert eligibility["status"] == "ready_to_start"
    assert reloaded == calibrated
    assert reloaded_calibrations == calibrations
    assert next(iter(reloaded_calibrations.manual_refuel_checks.values()))[
        "status"
    ] == "passed"
    assert [kind for kind, _payload in recorder.events].count(
        "simulated_manual_refuel_outcome_recorded"
    ) == 2
