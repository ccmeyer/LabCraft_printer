from __future__ import annotations

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


def _configure_stream_design(experiment):
    experiment.factors = []
    experiment.add_additive(
        "Virtual Reverse Transition Stock",
        [1.0],
        "x",
        40.0,
        forced_stock_conc=10.0,
        printing_mode="stream",
    )
    experiment.set_metadata(
        name="sil-m4c-reverse-transition",
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
    experiment.set_well_selection([f"A{column}" for column in range(1, 25)])
    assert experiment.optimize_stock_solutions()["best"]
    experiment.generate_experiment()
    experiment.save_experiment()


def test_stream_to_droplet_apply_and_reload_authoritative_bundle(
    experiment_model_factory,
    tmp_path,
):
    model = experiment_model_factory()
    experiment = model.experiment_model
    _configure_stream_design(experiment)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    prepared = experiment.get_execution_plan_snapshot()
    stock = next(item for item in prepared.stocks if item.factor_name != "Water")
    assert stock.printing_mode == "stream"
    assert stock.effective_volume_nL == 40.0

    mode = {"value": "stream"}
    head = SimpleNamespace(
        serial="virtual-head-m4c",
        printer_head_id="virtual-head-m4c",
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
            simulated_elapsed_ms=75,
        ),
        check_if_all_completed=lambda: True,
    )
    recorder = _Recorder()
    controller = SimpleNamespace(get_array_run_state=lambda: "idle")
    adapter = SyntheticCalibrationApplicationAdapter(
        session_root=tmp_path,
        session_id="normal-ui-convergence",
        application_session_id="application-1",
        seed=1,
        model=model,
        controller=controller,
        machine=machine,
        recorder=recorder,
        open_dialog_callback=lambda _candidate_id: object(),
    )

    generated = adapter.generate("stream_to_droplet")
    assert generated["ok"] is True
    result = adapter.current_result
    assert result.original_printing_mode == "stream"
    assert result.applied_printing_mode == "droplet"
    assert result.measured_volume_nL == 38.0
    row = model.calibration_manager.get_characterization_summary_rows()[0]

    experiment.apply_droplet_volume_for_option(
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
    head.set_printing_mode("droplet")

    calibrated = experiment.get_execution_plan_snapshot()
    calibrated_stock = next(
        item for item in calibrated.stocks if item.stock_id == stock.stock_id
    )
    assert calibrated.plan_revision > prepared.plan_revision
    assert calibrated_stock.printing_mode == "droplet"
    assert calibrated_stock.effective_volume_nL == 38.0
    assert experiment.validate_manual_refuel_check_for_print(
        printer_head=head,
        machine_model=model.machine_model,
    )["code"] == "not_required"
    assert load_execution_plan(experiment.execution_plan_file_path) == calibrated
    calibrations = load_execution_calibrations(
        experiment.execution_calibrations_file_path
    )
    assert len(calibrations.records) == 1

    loaded = experiment_model_factory()
    loaded_experiment = loaded.experiment_model
    loaded_experiment.load_experiment(
        experiment.experiment_file_path,
        experiment.experiment_dir_path,
    )
    eligibility = loaded.load_authoritative_execution_runtime()
    assert eligibility["status"] == "ready_to_start"
    assert loaded_experiment.get_execution_plan_snapshot() == calibrated
    assert load_execution_calibrations(
        loaded_experiment.execution_calibrations_file_path
    ) == calibrations
    projected_plan = loaded_experiment.get_calibration_application_plan_for_key(
        (stock.factor_name, stock.option_name)
    )
    assert projected_plan["source"] == "authoritative_execution_plan"
    assert projected_plan["stocks"][0]["droplet_volume_nL"] == 38.0
    reloaded_preview = loaded_experiment.preview_requantized_for_option(
        (stock.factor_name, stock.option_name),
        37.5,
    )
    assert reloaded_preview["ok"] is True
    assert reloaded_preview["n_stocks"] == 1

    reloaded_mode = {"value": "droplet"}
    reloaded_head = SimpleNamespace(
        serial="virtual-head-m4c",
        printer_head_id="virtual-head-m4c",
        get_stock_id=lambda: stock.stock_id,
        get_printing_mode=lambda: reloaded_mode["value"],
    )
    bridge_model = SimpleNamespace(
        machine_state_updated=SignalStub(),
        rack_model=SimpleNamespace(
            get_gripper_printer_head=lambda: reloaded_head
        ),
        experiment_model=loaded_experiment,
    )
    bridge_model.machine_model = SimpleNamespace(
        get_target_print_pressure=lambda: 1.2,
        get_print_pulse_width=lambda: 1400,
    )
    bridge_model.calibration_manager = CalibrationManager(bridge_model)
    bridge_model.calibration_manager.ensure_loaded = lambda: None
    bridge_model.calibration_manager.data = {"runs": []}
    reopened_adapter = SyntheticCalibrationApplicationAdapter(
        session_root=tmp_path,
        session_id="normal-ui-convergence",
        application_session_id="application-2",
        seed=1,
        model=bridge_model,
        controller=SimpleNamespace(get_array_run_state=lambda: "idle"),
        machine=SimpleNamespace(
            state=SimpleNamespace(
                connected=True,
                motors_enabled=True,
                homed=True,
                regulating_print_pressure=True,
                simulated_elapsed_ms=100,
            ),
            check_if_all_completed=lambda: True,
        ),
        recorder=_Recorder(),
        open_dialog_callback=lambda _candidate_id: object(),
    )

    reopened_adapter.availability("nominal_droplet")
    historical_rows = (
        bridge_model.calibration_manager.get_characterization_summary_rows()
    )
    assert len(historical_rows) == 1
    assert historical_rows[0]["application_record_state"] == "applied_history"
    assert historical_rows[0]["synthetic_result_fingerprint"] == result.result_fingerprint
    assert [kind for kind, _payload in recorder.events] == [
        "synthetic_calibration_generated",
        "synthetic_calibration_applied",
    ]
