from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from PySide6 import QtWidgets

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from ApplicationComposition import SIMULATION_RUNTIME_CONTEXT
from CalibrationClasses.Model import CalibrationManager
from CalibrationClasses.View import DropletImagingDialog
from Controller import Controller
from ExecutionCalibrationStore import load_execution_calibrations
from ExecutionPlan import load_execution_plan
from Model import Model
from tools.sil.calibration_application import SyntheticCalibrationApplicationAdapter
from tools.virtual_workflows.page_drivers import CalibrationDialogDriver


WELL_IDS = ["A1", "A6", "B3", "C9", "D2", "E11", "F5", "G8", "H12"]
DURABLE_HEAD_ID = "sil-fill-head-durable-v1"


class _Recorder:
    healthy = True

    def __init__(self):
        self.events = []

    def record_event(self, kind, **kwargs):
        self.events.append((kind, kwargs))


class _Rack:
    def __init__(self, head):
        self._head = head
        self.gripper_updated = SignalStub()

    def get_gripper_printer_head(self):
        return self._head

    def replace_head(self, head):
        self._head = head
        self.gripper_updated.emit()


class _Machine:
    def __init__(self):
        self.state = SimpleNamespace(
            connected=True,
            motors_enabled=True,
            homed=True,
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
            simulated_elapsed_ms=50,
        )

    def check_if_all_completed(self):
        return True


class _MachineModel:
    def __init__(self, machine):
        self._machine = machine
        self.machine_state_updated = SignalStub()
        self.pressure_updated = SignalStub()
        self.printing_parameters_updated = SignalStub()

    @property
    def machine_connected(self):
        return bool(self._machine.state.connected)

    def is_connected(self):
        return bool(self._machine.state.connected)

    def motors_are_homed(self):
        return bool(self._machine.state.homed)

    def get_print_pressure_bounds(self):
        return 0.1, 5.0

    def get_target_print_pressure(self):
        return 0.6

    def get_current_print_pressure(self):
        return 0.6

    def get_target_refuel_pressure(self):
        return 0.3

    def get_current_refuel_pressure(self):
        return 0.3

    def get_print_pulse_width(self):
        return 1300

    def get_refuel_pulse_width(self):
        return 3000

    def get_print_pressure_readings(self):
        return [0.6]

    def get_refuel_pressure_readings(self):
        return [0.3]


def _configure_sparse_uploaded_fill_design(experiment):
    frame = pd.DataFrame(
        {
            "Well": WELL_IDS,
            "Signal A (mM)": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
            "Signal B (mM)": [0.0, 0.2, 0.0, 0.4, 0.0, 0.6, 0.0, 0.8, 0.0],
            "Signal C (mM)": [0.5, 0.0, 0.4, 0.0, 0.3, 0.0, 0.2, 0.0, 0.1],
            "Signal D (mM)": [0.1] * len(WELL_IDS),
        }
    )
    experiment.set_metadata(
        name="sil-sparse-fill-calibration",
        randomize_assignments=False,
        replicates=1,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        printed_volume_tolerance_nL=50.0,
        fill_reagent_name="Water",
        fill_printing_mode="droplet",
        fill_droplet_volume_nL=10.0,
    )
    experiment.set_uploaded_design_from_dataframe(frame)
    for factor in experiment.factors:
        factor.options[0].forced_stock_conc = 10.0
    assert experiment.optimize_stock_solutions()["best"]
    experiment.generate_experiment()
    experiment.save_experiment()


def _fill_stock(plan):
    matching = [
        stock
        for stock in plan.stocks
        if stock.factor_name == "Water" and stock.units == "--"
    ]
    assert len(matching) == 1
    return matching[0]


def _head(stock, *, printer_head_id, serial, legacy_id):
    concentration = stock.concentration
    stock_solution = SimpleNamespace(
        stock_id=stock.stock_id,
        reagent_name=stock.factor_name,
        concentration=concentration,
        raw_concentration=concentration,
        units=stock.units,
        get_stock_id=lambda: stock.stock_id,
        get_reagent_name=lambda: stock.factor_name,
        get_stock_concentration=lambda: concentration,
        get_display_stock_concentration=lambda: concentration,
        get_stock_name=lambda: stock.factor_name,
        get_display_stock_name=lambda: stock.factor_name,
    )
    return SimpleNamespace(
        printer_head_id=printer_head_id,
        serial=serial,
        id=legacy_id,
        stock_solution=stock_solution,
        get_stock_solution=lambda: stock_solution,
        get_stock_id=lambda: stock.stock_id,
        get_reagent_name=lambda: stock.factor_name,
        get_stock_concentration=lambda: concentration,
        get_display_stock_concentration=lambda: concentration,
        get_stock_name=lambda: stock.factor_name,
        get_display_stock_name=lambda: stock.factor_name,
        get_printing_mode=lambda: "droplet",
    )


def _install_calibration_context(model, head):
    machine = _Machine()
    rack = _Rack(head)
    model.machine_state_updated = SignalStub()
    model.rack_model = rack
    model.machine_model = _MachineModel(machine)
    model.print_profiles = []
    model.droplet_camera_model = SimpleNamespace(
        flash_duration=1000,
        flash_delay=2000,
        num_droplets=1,
        exposure_time=5000,
        droplet_image_updated=SignalStub(),
        flash_signal=SignalStub(),
        flash_fault_latched=False,
    )
    model.refuel_camera_model = None
    model.calibration_manager = CalibrationManager(model)
    model.calibration_manager.ensure_loaded = lambda: None
    model.calibration_manager.data = {"runs": []}
    return machine, rack


def _adapter(*, root, model, machine, application_session_id, recorder=None):
    recorder = recorder or _Recorder()
    controller = SimpleNamespace(get_array_run_state=lambda: "idle")
    return SyntheticCalibrationApplicationAdapter(
        session_root=root,
        session_id="fill-calibration-lifecycle",
        application_session_id=application_session_id,
        seed=25,
        model=model,
        controller=controller,
        machine=machine,
        recorder=recorder,
        open_dialog_callback=lambda _candidate_id: object(),
    )


def _applied_calibration_payload(result, row, head):
    return {
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
    }


@pytest.mark.sil_lifecycle
def test_sparse_fill_apply_survives_reload_and_head_reconstruction(
    experiment_model_factory,
    tmp_path,
):
    model = experiment_model_factory()
    experiment = model.experiment_model
    _configure_sparse_uploaded_fill_design(experiment)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    prepared = experiment.get_execution_plan_snapshot()
    fill_stock = _fill_stock(prepared)
    assert [well.well_id for well in prepared.wells] == WELL_IDS

    head = _head(
        fill_stock,
        printer_head_id=DURABLE_HEAD_ID,
        serial="conflicting-serial-before-reload",
        legacy_id="conflicting-legacy-id-before-reload",
    )
    machine, _rack = _install_calibration_context(model, head)
    recorder = _Recorder()
    adapter = _adapter(
        root=tmp_path / "sil-session",
        model=model,
        machine=machine,
        application_session_id="application-1",
        recorder=recorder,
    )

    generated = adapter.generate("nominal_droplet")
    assert generated["ok"] is True
    result = adapter.current_result
    assert result.is_fill is True
    assert result.printer_head_id == DURABLE_HEAD_ID
    row = next(
        item
        for item in model.calibration_manager.get_characterization_summary_rows()
        if item.get("synthetic_result_fingerprint") == result.result_fingerprint
    )
    preview = experiment.preview_fill_requantized(result.effective_volume_nL)
    assert preview["ok"] is True
    assert list(preview["well_ids"]) == WELL_IDS

    applied = experiment.apply_fill_droplet_volume(
        result.effective_volume_nL,
        printing_mode=result.applied_printing_mode,
        applied_calibration=_applied_calibration_payload(result, row, head),
    )
    calibrated = load_execution_plan(experiment.execution_plan_file_path)
    calibrated_fill = _fill_stock(calibrated)
    committed_counts = {
        well.well_id: next(
            (
                dispense.target_dispenses
                for dispense in well.dispenses
                if dispense.stock_id == fill_stock.stock_id
            ),
            0,
        )
        for well in calibrated.wells
    }

    assert calibrated.plan_revision == prepared.plan_revision + 2
    assert applied["execution_plan_revision"] == calibrated.plan_revision
    assert [well.well_id for well in calibrated.wells] == WELL_IDS
    assert committed_counts == {
        well_id: counts.get(fill_stock.stock_id, 0)
        for well_id, counts in preview["target_counts_by_well"].items()
    }
    assert applied["total_drops_old"] == preview["total_drops_old"]
    assert applied["total_drops_new"] == preview["total_drops_new"]
    assert calibrated_fill.printer_head_id == DURABLE_HEAD_ID
    assert calibrated_fill.effective_volume_nL == pytest.approx(
        result.effective_volume_nL
    )

    calibrations = load_execution_calibrations(
        experiment.execution_calibrations_file_path
    )
    assert len(calibrations.records) == 1
    record = calibrations.records[calibrated_fill.calibration_record_key]
    assert record.printer_head_id == DURABLE_HEAD_ID
    assert record.source_row_fingerprint == tuple(result.source_row_fingerprint)
    assert [kind for kind, _payload in recorder.events] == [
        "synthetic_calibration_generated",
        "synthetic_calibration_applied",
    ]

    reloaded_model = experiment_model_factory()
    reloaded_experiment = reloaded_model.experiment_model
    reloaded_experiment.load_experiment(
        experiment.experiment_file_path,
        experiment.experiment_dir_path,
    )
    eligibility = reloaded_model.load_authoritative_execution_runtime()
    assert eligibility["status"] == "ready_to_start"
    assert reloaded_experiment.get_execution_plan_snapshot() == calibrated

    reconstructed_head = _head(
        calibrated_fill,
        printer_head_id=DURABLE_HEAD_ID,
        serial="different-serial-after-reload",
        legacy_id="different-legacy-id-after-reload",
    )
    reopened_machine, reopened_rack = _install_calibration_context(
        reloaded_model,
        reconstructed_head,
    )
    reopened_adapter = _adapter(
        root=tmp_path / "sil-session",
        model=reloaded_model,
        machine=reopened_machine,
        application_session_id="application-2",
    )
    assert reopened_adapter.availability("nominal_droplet")["ok"] is True
    historical_rows = (
        reloaded_model.calibration_manager.get_characterization_summary_rows()
    )
    historical = next(
        item
        for item in historical_rows
        if item.get("synthetic_result_fingerprint") == result.result_fingerprint
    )
    assert historical["application_record_state"] == "applied_history"
    assert reloaded_model.calibration_manager.resolve_characterization_selection(
        historical
    )["ok"] is True

    different_head = _head(
        calibrated_fill,
        printer_head_id="sil-fill-head-genuinely-different",
        serial="conflicting-serial-before-reload",
        legacy_id="conflicting-legacy-id-before-reload",
    )
    reopened_rack.replace_head(different_head)
    assert reloaded_model.calibration_manager.get_characterization_summary_rows() == []
    rejected = reloaded_model.calibration_manager.resolve_characterization_selection(
        historical
    )
    assert rejected["ok"] is False
    assert rejected["code"] == "identity_mismatch"


@pytest.mark.sil_lifecycle
def test_open_fill_dialog_recovers_apply_after_interruption_and_reconnect(
    experiment_model_factory,
    monkeypatch,
    qapp,
    tmp_path,
):
    model = experiment_model_factory()
    experiment = model.experiment_model
    _configure_sparse_uploaded_fill_design(experiment)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    prepared = experiment.get_execution_plan_snapshot()
    fill_stock = _fill_stock(prepared)
    initial_head = _head(
        fill_stock,
        printer_head_id=DURABLE_HEAD_ID,
        serial="dialog-serial-before-reconnect",
        legacy_id="dialog-legacy-id-before-reconnect",
    )
    machine, rack = _install_calibration_context(model, initial_head)

    capture_state = {
        "pending_active": False,
        "dirty_shutdown": False,
        "last_result_status": None,
        "last_result_reason": "",
        "last_result_dirty_shutdown": False,
    }
    interruption_events = []
    physical_calls = []

    def cancel_pending_capture(reason, *, emit_capture_failed=True, recover=True):
        interruption_events.append(
            (
                "capture",
                str(reason),
                bool(emit_capture_failed),
                bool(recover),
            )
        )
        capture_state["pending_active"] = False
        return True

    controller = SimpleNamespace(
        model=model,
        machine=machine,
        machine_workflow_interrupted_signal=SignalStub(),
        transport_fault_ui_signal=SignalStub(),
        error_occurred_signal=SignalStub(),
        get_array_run_state=lambda: "idle",
        get_droplet_capture_ui_state=lambda: dict(capture_state),
        cancel_pending_droplet_capture=cancel_pending_capture,
        start_droplet_camera=lambda: physical_calls.append("start_droplet_camera"),
        stop_droplet_camera=lambda: physical_calls.append("stop_droplet_camera"),
        start_read_camera=lambda: physical_calls.append("start_read_camera"),
        stop_read_camera=lambda: physical_calls.append("stop_read_camera"),
        set_droplet_capture_profile=lambda *_args, **_kwargs: physical_calls.append(
            "set_droplet_capture_profile"
        ),
        set_command_dispatch_interval=lambda *_args, **_kwargs: physical_calls.append(
            "set_command_dispatch_interval"
        ),
        disable_print_profile=lambda *_args, **_kwargs: physical_calls.append(
            "disable_print_profile"
        ),
    )
    real_interrupt = model.calibration_manager.interrupt_machine_workflow

    def record_manager_interrupt(reason):
        interruption_events.append(("manager", str(reason)))
        return real_interrupt(reason)

    model.calibration_manager.interrupt_machine_workflow = record_manager_interrupt
    controller.machine_workflow_interrupted_signal.connect(
        lambda payload: Controller._on_droplet_calibration_workflow_interrupted(
            controller,
            payload,
        )
    )
    adapter = SyntheticCalibrationApplicationAdapter(
        session_root=tmp_path / "dialog-sil-session",
        session_id="fill-dialog-reconnect",
        application_session_id="application-1",
        seed=25,
        model=model,
        controller=controller,
        machine=machine,
        recorder=_Recorder(),
        open_dialog_callback=lambda _candidate_id: object(),
    )
    generated = adapter.generate("nominal_droplet")
    assert generated["ok"] is True
    result = adapter.current_result
    expected_preview = experiment.preview_fill_requantized(
        result.effective_volume_nL
    )
    assert expected_preview["ok"] is True

    monkeypatch.setattr(
        DropletImagingDialog,
        "refresh_calibration_memory_recommendation",
        lambda self, *args, **kwargs: None,
    )
    main_window = QtWidgets.QWidget()
    main_window.color_dict = {}
    main_window.runtime_context = SIMULATION_RUNTIME_CONTEXT
    dialog = DropletImagingDialog(
        main_window,
        model,
        controller,
        simulation_workflow_mode=True,
        synthetic_generation_callback=adapter.generate,
        synthetic_availability_callback=adapter.availability,
    )
    dialog.activate_session(mode="calibration")
    dialog.open()
    driver = CalibrationDialogDriver(qapp, dialog)
    driver.select_result(result.result_fingerprint)
    ready = driver.inspect_preview()
    selected_before = dict(dialog._selected_summary_row()[1] or {})

    assert ready["payload"]["is_fill"] is True
    assert ready["payload"]["new_fill_nL"] == pytest.approx(
        result.effective_volume_nL
    )
    assert ready["visible_table"]["rows"][0][3] == str(
        expected_preview["total_drops_new"]
    )
    assert ready["apply_enabled"] is True
    assert ready["apply_state"] == "ready"
    assert selected_before["synthetic_result_fingerprint"] == result.result_fingerprint

    capture_state["pending_active"] = True
    machine.state.connected = False
    model.machine_model.machine_state_updated.emit()
    controller.machine_workflow_interrupted_signal.emit(
        {"reason": "serial_connection_lost", "notify_user": False}
    )
    driver.wait_until(
        lambda: not driver.inspect_preview()["apply_enabled"],
        "fill Apply to become unavailable after interruption",
    )
    interrupted = driver.inspect_preview()
    assert interruption_events[:2] == [
        ("capture", "serial_connection_lost", False, False),
        ("manager", "serial_connection_lost"),
    ]
    assert model.calibration_manager.is_idle() is True
    assert interrupted["apply_state"] == "unavailable"
    disconnected_selection = dict(dialog._selected_summary_row()[1] or {})
    assert disconnected_selection[
        "synthetic_result_fingerprint"
    ] == result.result_fingerprint
    assert disconnected_selection["_historical_candidate_id"] == (
        result.result_fingerprint
    )
    assert dialog._selected_result_action_block_state()["code"] == (
        "machine_disconnected"
    )

    reconstructed_head = _head(
        fill_stock,
        printer_head_id=DURABLE_HEAD_ID,
        serial="dialog-serial-after-reconnect",
        legacy_id="dialog-legacy-id-after-reconnect",
    )
    machine.state.connected = True
    model.machine_model.machine_state_updated.emit()
    rack.replace_head(reconstructed_head)
    driver.wait_until(
        lambda: driver.inspect_preview()["apply_enabled"],
        "fill Apply readiness to recover without reselection",
    )
    reconnected = driver.inspect_preview()
    selected_after = dict(dialog._selected_summary_row()[1] or {})
    assert selected_after["synthetic_result_fingerprint"] == result.result_fingerprint
    assert dialog._selected_result_action_block_state() is None
    assert reconnected["payload"]["is_fill"] is True
    assert reconnected["payload"]["new_fill_nL"] == pytest.approx(
        result.effective_volume_nL
    )
    assert reconnected["apply_state"] == "ready"

    different_head = _head(
        fill_stock,
        printer_head_id="sil-fill-head-genuinely-different",
        serial="dialog-serial-before-reconnect",
        legacy_id="dialog-legacy-id-before-reconnect",
    )
    rack.replace_head(different_head)
    driver.wait_until(
        lambda: not driver.inspect_preview()["apply_enabled"],
        "fill Apply rejection for a different durable head",
    )
    rejected = driver.inspect_preview()
    assert rejected["apply_state"] == "unavailable"
    assert "no longer matches" in rejected["status"].lower()
    assert physical_calls == []

    dialog.deactivate_session(reason="test_complete")
    dialog.shutdown()
    adapter.dispose()
