"""Composed SIL journeys for the Milestone 1 calibration-storage baseline."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import time
from typing import Any, Mapping

from tools.sil.calibration_storage_contract import (
    CATALOG_PATH,
    ScriptedCalibrationCase,
    file_sha256,
    load_catalog,
    load_fixture,
    semantic_sha256,
)
from tools.sil.calibration_storage_process import (
    StorageContractRunner,
    StorageMetricsCollector,
    SyntheticStorageHead,
    file_inventory,
)
from tools.virtual_workflows.actions import InteractionSurface
from tools.virtual_workflows.assertions import (
    AssertionResult,
    cleanup_assertion,
    simulation_identity_assertion,
)
from tools.virtual_workflows.composition import JourneyDefinition, JourneyRuntime
from tools.virtual_workflows.metrics import ProcessResourceSampler
from tools.virtual_workflows.page_drivers import (
    CalibrationDialogDriver,
    ExperimentLoaderDriver,
    MachineControlsDriver,
)
from tools.virtual_workflows.report import ComposedReportPayload


REPO_ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "calibration_storage_contract_legacy_baseline_8x25_v1.json"
)
FUNCTIONAL_ID = "calibration_storage_contract_v1"
PERFORMANCE_ID = "calibration_storage_legacy_baseline_8x25_v1"
FUNCTIONAL_SCENARIO = "calibration_storage_contract"
PERFORMANCE_SCENARIO = "calibration_storage_legacy_baseline"

FUNCTIONAL_ACTIONS = frozenset(
    {
        "app.launch_simulated",
        "fixture.prepare_calibration_storage",
        "calibration.run_scripted_processes",
        "calibration.inspect_storage_artifacts",
        "experiment.activate_authoritative",
        "app.close_simulated_session",
        "experiment.load_authoritative_via_ui",
        "experiment.activate_authoritative_via_ui",
        "calibration.stage_persisted_selection",
        "calibration.open_via_ui",
        "calibration.select_via_ui",
        "calibration.apply_via_ui",
        "artifact.capture_milestone",
        "scenario.teardown",
    }
)
FUNCTIONAL_UI_ACTIONS = frozenset(
    {
        "experiment.load_authoritative_via_ui",
        "experiment.activate_authoritative_via_ui",
        "calibration.open_via_ui",
        "calibration.select_via_ui",
        "calibration.apply_via_ui",
    }
)
FUNCTIONAL_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "calibration.storage.fixture_parity",
    "calibration.storage.lifecycle_exact",
    "calibration.storage.summary_isolation",
    "calibration.storage.capture_policy_exact",
    "calibration.storage.fresh_reload_exact",
    "calibration.storage.ui_application_exact",
    "artifacts.cleanup_complete",
)
PERFORMANCE_ACTIONS = frozenset(
    {
        "app.launch_simulated",
        "fixture.prepare_calibration_storage",
        "calibration.run_scripted_processes",
        "calibration.inspect_storage_artifacts",
        "scenario.teardown",
    }
)
PERFORMANCE_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "calibration.storage.workload_counts_exact",
    "calibration.storage.metrics_complete",
    "calibration.storage.growth_recorded",
    "calibration.storage.key_evidence_probe_exact",
    "artifacts.cleanup_complete",
)


def _assertion(
    assertion_id: str,
    decision: bool,
    evidence: Mapping[str, Any],
    *,
    checkpoint: str,
    sources: tuple[str, ...],
) -> AssertionResult:
    return AssertionResult(
        assertion_id=assertion_id,
        checkpoint=checkpoint,
        decision="pass" if decision else "fail",
        observable_sources=sources,
        evidence=dict(evidence),
        message=None if decision else f"{assertion_id} contract did not match",
    )


def _functional_fixture() -> tuple[dict[str, Any], Path]:
    catalog, _cases = load_catalog(CATALOG_PATH)
    return catalog, CATALOG_PATH.resolve()


def _performance_fixture() -> tuple[dict[str, Any], Path]:
    payload = json.loads(PERFORMANCE_FIXTURE_PATH.read_text(encoding="utf-8"))
    workload = payload.get("workload") or {}
    if (
        payload.get("schema_id")
        != "labcraft.calibration_storage_performance_workload"
        or payload.get("schema_version") != 1
        or payload.get("fixture_id") != PERFORMANCE_ID
        or workload.get("completion_count") != 200
        or workload.get("expected_update_count") != 232
    ):
        raise ValueError("calibration-storage performance fixture drifted")
    return payload, PERFORMANCE_FIXTURE_PATH.resolve()


def _prepare_minimal_experiment(runtime: JourneyRuntime) -> dict[str, Any]:
    context = runtime.context
    experiment = context.experiment_model
    experiment.factors = []
    experiment.add_additive(
        "SIL Storage Reagent",
        [1.0],
        "x",
        10.0,
        forced_stock_conc=10.0,
        printing_mode="droplet",
    )
    experiment.set_metadata(
        name=f"{runtime.definition.workload_id}-experiment",
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=2,
        target_reaction_volume_nL=2500.0,
        final_reaction_volume_nL=2500.0,
        printed_volume_tolerance_nL=50.0,
        fill_reagent_name="Water",
        fill_printing_mode="droplet",
        fill_droplet_volume_nL=10.0,
    )
    experiment.set_well_selection(["A1", "A2"])
    optimized = experiment.optimize_stock_solutions()
    if not optimized.get("best"):
        raise RuntimeError("minimal storage-contract design did not optimize")
    experiment.generate_experiment()
    experiment.initialize_experiment(
        base_dir=str(Path(runtime.context.scenario_root) / "experiments")
    )
    context.model.load_experiment_from_model(finalize_execution_plan=True)
    context.model.machine_model.update_print_pulse_width(1400)
    context.model.machine_model.update_target_print_pressure(
        context.model.machine_model.convert_to_raw_pressure(1.2)
    )
    plan = experiment.get_execution_plan_snapshot()
    non_fill = [
        stock
        for stock in plan.stocks
        if str(stock.factor_name) != experiment.get_fill_reagent_name()
    ]
    if len(non_fill) != 1:
        raise RuntimeError("minimal storage-contract design must have one non-fill stock")
    stock = non_fill[0]
    identity = {
        "printer_head_id": "sil-storage-application-head",
        "stock_id": str(stock.stock_id),
        "reagent_name": "SIL Storage Reagent",
        "concentration": "10.0",
        "units": "x",
    }
    evidence = {
        "experiment_dir": str(Path(experiment.experiment_dir_path).resolve()),
        "experiment_name": experiment.metadata["name"],
        "calibration_file": str(Path(experiment.calibration_file_path).resolve()),
        "plan_id": str(plan.plan_id),
        "plan_revision": int(plan.plan_revision),
        "stock_identity": identity,
    }
    runtime.observations["prepared_experiment"] = evidence
    return evidence


def _summary_projection(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "source_run_id",
        "source_phase_key",
        "source_step_index",
        "source_pressure_index",
        "phase",
        "timestamp",
        "pw_us",
        "pressure_psi",
        "mean_nL",
        "cv_pct",
        "valid",
        "printing_mode",
    )
    projected = [{key: row.get(key) for key in fields} for row in rows]
    return sorted(
        projected,
        key=lambda row: (
            str(row.get("source_run_id") or ""),
            str(row.get("source_phase_key") or ""),
            int(row.get("source_step_index") or 0),
            -1
            if row.get("source_pressure_index") is None
            else int(row["source_pressure_index"]),
        ),
    )


def _summary_oracle_projection(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Remove only runtime identity/timing fields from current-reader rows."""

    fields = (
        "source_phase_key",
        "source_step_index",
        "source_pressure_index",
        "phase",
        "pw_us",
        "pressure_psi",
        "mean_nL",
        "cv_pct",
        "valid",
        "printing_mode",
    )
    return sorted(
        ({key: row.get(key) for key in fields} for row in rows),
        key=lambda row: (
            str(row.get("source_phase_key") or ""),
            int(row.get("source_step_index") or 0),
            -1
            if row.get("source_pressure_index") is None
            else int(row["source_pressure_index"]),
        ),
    )


def _run_functional_catalog(runtime: JourneyRuntime) -> dict[str, Any]:
    prepared = runtime.observations["prepared_experiment"]
    catalog, fixture_cases = load_catalog(runtime.fixture_path)
    metrics = StorageMetricsCollector()
    runner = StorageContractRunner(
        model=runtime.context.model,
        controller=runtime.context.controller,
        machine=runtime.context.machine,
        app=runtime.context.app,
        calibration_file_path=prepared["calibration_file"],
        timeout_seconds=runtime.harness.config.timeout_seconds,
        metrics=metrics,
    )
    runtime.register_restorable("calibration_storage_runner", runner)
    application_identity = dict(prepared["stock_identity"])
    executed: list[tuple[ScriptedCalibrationCase, dict[str, Any]]] = []
    for original in fixture_cases:
        case = (
            replace(original, identity=application_identity)
            if original.fixture_id == "legacy_parity_v1"
            else original
        )
        executed.append((case, runner.run_case(case).as_dict()))

    by_process = {case.process_id: evidence for case, evidence in executed}
    identities = {
        case.process_id: dict(case.identity)
        for case, _evidence in executed
    }
    head_a_rows = runner.characterization_rows(identities["head-a-sweep"])
    head_b_rows = runner.characterization_rows(identities["head-b-sweep"])
    failed_rows = runner.characterization_rows(identities["error-before-result"])
    application_rows = runner.characterization_rows(application_identity)
    target = by_process["legacy-parity-two-update"]
    target_coordinates = {
        "source_run_id": target["run_id"],
        "source_phase_key": "pressure_sweep_characterization",
        "source_step_index": 1,
        "source_pressure_index": 1,
    }
    target_rows = [
        row
        for row in application_rows
        if all(row.get(key) == value for key, value in target_coordinates.items())
    ]
    if len(target_rows) != 1:
        raise RuntimeError("legacy parity target row did not resolve uniquely")

    process_summary_rows = {}
    for case, process_evidence in executed:
        rows = runner.characterization_rows(case.identity)
        current_run_rows = [
            row
            for row in rows
            if row.get("source_run_id") == process_evidence["run_id"]
        ]
        process_summary_rows[case.process_id] = _summary_oracle_projection(
            current_run_rows
        )
    runner.characterization_rows(application_identity)

    capture_counts = {
        process_id: int(by_process[process_id]["capture_count"])
        for process_id in (
            "structured-only-proxy",
            "key-evidence-proxy",
            "full-proxy",
            "recorder-disabled-control",
        )
    }
    evidence = {
        "catalog_semantic_sha256": catalog["catalog_semantic_sha256"],
        "fixture_hashes": {
            row["fixture_id"]: row["semantic_sha256"]
            for row in catalog["fixtures"]
        },
        "process_count": len(executed),
        "successful_processes": sum(
            case.terminal_outcome == "completed" for case, _ in executed
        ),
        "stopped_processes": sum(
            case.terminal_outcome == "stopped" for case, _ in executed
        ),
        "error_processes": sum(
            case.terminal_outcome == "error" for case, _ in executed
        ),
        "update_count": sum(len(case.updates) for case, _ in executed),
        "processes": [evidence for _case, evidence in executed],
        "process_summary_rows": process_summary_rows,
        "expected_process_summary_rows": {
            case.process_id: list(case.expected_summary_rows)
            for case, _evidence in executed
        },
        "capture_counts": capture_counts,
        "capture_dimensions": sorted(
            {
                (capture["width"], capture["height"])
                for _case, process in executed
                for capture in process["captures"]
            }
        ),
        "head_a_run_ids": sorted(
            {str(row.get("source_run_id")) for row in head_a_rows}
        ),
        "head_b_run_ids": sorted(
            {str(row.get("source_run_id")) for row in head_b_rows}
        ),
        "head_a_expected_run_id": by_process["head-a-sweep"]["run_id"],
        "head_b_expected_run_id": by_process["head-b-sweep"]["run_id"],
        "failed_identity_summary_count": len(failed_rows),
        "application_summary": _summary_projection(application_rows),
        "target_coordinates": target_coordinates,
        "target_row": dict(target_rows[0]),
        "metrics": metrics.snapshot(),
        "calibration_sha256": file_sha256(prepared["calibration_file"]),
        "inventory": file_inventory(runtime.context.scenario_root),
    }
    runtime.observations["functional_storage"] = evidence
    return evidence


def _functional_contract_assertions(runtime: JourneyRuntime) -> None:
    observed = runtime.observations["functional_storage"]
    process_rows = observed["processes"]
    parity_ok = all(
        row["update_hashes"] == row["legacy_update_hashes"]
        and (
            row["recorder_update_hashes"] == row["update_hashes"]
            if row["recording_dir"] is not None
            else row["recorder_update_hashes"] == ()
        )
        for row in process_rows
    ) and observed["process_summary_rows"] == observed[
        "expected_process_summary_rows"
    ]
    runtime.add_assertion(
        _assertion(
            "calibration.storage.fixture_parity",
            parity_ok,
            {
                "process_count": observed["process_count"],
                "catalog_semantic_sha256": observed["catalog_semantic_sha256"],
                "fixture_hashes": observed["fixture_hashes"],
                "summary_oracle_sha256": semantic_sha256(
                    observed["expected_process_summary_rows"]
                ),
            },
            checkpoint="current_writers",
            sources=("calibration.json", "analysis.jsonl", "fixture_catalog"),
        )
    )
    lifecycle_ok = (
        observed["process_count"] == 16
        and observed["successful_processes"] == 14
        and observed["stopped_processes"] == 1
        and observed["error_processes"] == 1
        and observed["update_count"] == 17
        and all(
            row["meta_outcome"] == row["terminal_outcome"]
            for row in process_rows
            if row["recording_dir"] is not None
        )
    )
    runtime.add_assertion(
        _assertion(
            "calibration.storage.lifecycle_exact",
            lifecycle_ok,
            {
                key: observed[key]
                for key in (
                    "process_count",
                    "successful_processes",
                    "stopped_processes",
                    "error_processes",
                    "update_count",
                )
            },
            checkpoint="current_writers",
            sources=("CalibrationManager", "run_meta.json"),
        )
    )
    isolation_ok = (
        observed["head_a_run_ids"] == [observed["head_a_expected_run_id"]]
        and observed["head_b_run_ids"] == [observed["head_b_expected_run_id"]]
        and observed["failed_identity_summary_count"] == 0
    )
    runtime.add_assertion(
        _assertion(
            "calibration.storage.summary_isolation",
            isolation_ok,
            {
                key: observed[key]
                for key in (
                    "head_a_run_ids",
                    "head_b_run_ids",
                    "head_a_expected_run_id",
                    "head_b_expected_run_id",
                    "failed_identity_summary_count",
                )
            },
            checkpoint="current_reader",
            sources=("CalibrationManager.get_characterization_summary_rows",),
        )
    )
    expected_captures = {
        "structured-only-proxy": 0,
        "key-evidence-proxy": 2,
        "full-proxy": 4,
        "recorder-disabled-control": 0,
    }
    capture_ok = (
        observed["capture_counts"] == expected_captures
        and observed["capture_dimensions"] == [(16, 12)]
        and next(
            row for row in process_rows
            if row["process_id"] == "recorder-disabled-control"
        )["recording_dir"]
        is None
    )
    runtime.add_assertion(
        _assertion(
            "calibration.storage.capture_policy_exact",
            capture_ok,
            {
                "counts": observed["capture_counts"],
                "dimensions": observed["capture_dimensions"],
                "compressed_bytes": {
                    row["process_id"]: row["capture_bytes"]
                    for row in process_rows
                    if row["process_id"] in expected_captures
                },
                "decoded_pixel_hashes": {
                    row["process_id"]: [
                        capture["decoded_pixel_sha256"]
                        for capture in row["captures"]
                    ]
                    for row in process_rows
                    if row["process_id"] in expected_captures
                },
            },
            checkpoint="capture_scaffolding",
            sources=("calibration_recordings/captures",),
        )
    )


def _stage_fresh_selection(runtime: JourneyRuntime) -> dict[str, Any]:
    prepared = runtime.observations["prepared_experiment"]
    machine = runtime.context.machine
    machine.state.connected = True
    machine.state.motors_enabled = True
    machine.state.homed = True
    machine.state.regulating_print_pressure = True
    pressure_raw = int(machine.convert_to_raw_pressure(1.2))
    machine.state.current_print_pressure_raw = pressure_raw
    machine.state.target_print_pressure_raw = pressure_raw
    machine.state.print_pulse_width_us = 1400
    machine._emit_status()
    machine.machine_connected_signal.emit(True)
    head = SyntheticStorageHead(prepared["stock_identity"])
    rack = runtime.context.model.rack_model
    rack.gripper_printer_head = head
    rack.gripper_slot_number = None
    sync = getattr(rack, "sync_expected_to_actual", None)
    if callable(sync):
        sync()
    signal = getattr(rack, "gripper_updated", None)
    if signal is not None:
        signal.emit()
    runtime.context.app.processEvents()
    readiness = runtime.harness.session.calibration_adapter.availability(
        "nominal_droplet"
    )
    if not readiness.get("ok"):
        raise RuntimeError(f"persisted calibration selection is not ready: {readiness}")
    return {
        "ready": True,
        "readiness_code": readiness.get("code"),
        "stock_identity": dict(prepared["stock_identity"]),
        "command_event_count": len(machine.command_event_history),
    }


def _inspect_applied_record(
    runtime: JourneyRuntime,
    selected: Mapping[str, Any],
    source_row_fingerprint: Any,
) -> dict[str, Any]:
    from ExecutionCalibrationStore import load_execution_calibrations

    experiment = runtime.context.experiment_model
    plan = experiment.get_execution_plan_snapshot()
    stock_id = runtime.observations["prepared_experiment"]["stock_identity"]["stock_id"]
    stock = next(item for item in plan.stocks if item.stock_id == stock_id)
    document = load_execution_calibrations(experiment.execution_calibrations_file_path)
    record = document.records[stock.calibration_record_key]
    record_payload = record.to_dict()
    expected = {
        "run_id": selected.get("source_run_id"),
        "phase": selected.get("phase"),
        "timestamp": selected.get("timestamp"),
        "source_row_fingerprint": list(source_row_fingerprint or ()),
    }
    command_types = sorted(
        {
            str(event.get("command_type"))
            for event in runtime.context.machine.command_event_history
        }
    )
    return {
        "record": record_payload,
        "expected_source": expected,
        "matches_source": all(record_payload.get(key) == value for key, value in expected.items()),
        "plan_revision": int(plan.plan_revision),
        "command_types": command_types,
        "settings_only_commands": set(command_types)
        <= {"SET_WIDTH_P", "ABSOLUTE_PRESSURE_P"},
        "no_dispense_or_motion": not any(
            command.startswith(("DISPENSE", "ABSOLUTE_X", "ABSOLUTE_Y", "ABSOLUTE_Z", "HOME_"))
            for command in command_types
        ),
    }


def _functional_body(runtime: JourneyRuntime) -> None:
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    runtime.harness.run_action(
        "fixture.prepare_calibration_storage",
        lambda: _prepare_minimal_experiment(runtime),
        surface=InteractionSurface.MODEL,
    )
    runtime.harness.run_action(
        "calibration.run_scripted_processes",
        lambda: _run_functional_catalog(runtime),
        surface=InteractionSurface.MODEL,
    )
    runtime.harness.run_action(
        "calibration.inspect_storage_artifacts",
        lambda: {"status": "validated"},
        surface=InteractionSurface.HARNESS,
    )
    _functional_contract_assertions(runtime)
    before_summary = runtime.observations["functional_storage"]["application_summary"]
    experiment_dir = Path(runtime.observations["prepared_experiment"]["experiment_dir"])
    from PySide6 import QtCore, QtWidgets

    QtWidgets.QApplication.setAttribute(
        QtCore.Qt.ApplicationAttribute.AA_DontUseNativeDialogs,
        True,
    )
    runtime.restore_all()
    runtime.harness.run_action(
        "experiment.activate_authoritative",
        lambda: runtime.context.model.load_authoritative_execution_runtime(),
        surface=InteractionSurface.MODEL,
    )
    runtime.harness.close_application_session()
    runtime.harness.reopen_application_session()
    prepared = runtime.observations["prepared_experiment"]
    load_started = time.perf_counter_ns()
    reload_evidence = ExperimentLoaderDriver(
        runtime.context
    ).load_authoritative_execution(
        experiment_dir,
        expected_name=prepared["experiment_name"],
        expected_eligibility_status="ready_to_start",
        expected_array_state="idle",
        loaded_milestone_name="storage_session_2_loaded",
    )
    fresh_reload_ms = (time.perf_counter_ns() - load_started) / 1_000_000.0
    runtime.harness.run_action(
        "calibration.stage_persisted_selection",
        lambda: _stage_fresh_selection(runtime),
        surface=InteractionSurface.HARNESS,
    )
    manager = runtime.context.model.calibration_manager
    try:
        raw_after_summary = manager.get_characterization_summary_rows()
        after_summary = _summary_projection(raw_after_summary)
    except Exception as exc:
        raise RuntimeError(
            "fresh calibration summary reload failed after staging persisted identity"
        ) from exc
    fresh_ok = after_summary == before_summary
    runtime.add_assertion(
        _assertion(
            "calibration.storage.fresh_reload_exact",
            fresh_ok,
            {
                "before_semantic_sha256": semantic_sha256(before_summary),
                "after_semantic_sha256": semantic_sha256(after_summary),
                "row_count": len(after_summary),
                "fresh_reload_latency_ms": fresh_reload_ms,
                "loader": reload_evidence,
            },
            checkpoint="fresh_application",
            sources=("ExperimentLoaderDriver", "CalibrationManager"),
        )
    )

    def open_calibration_dialog() -> dict[str, Any]:
        try:
            dialog = MachineControlsDriver(runtime.context).open_calibration_dialog()
            return {"visible": bool(dialog.isVisible())}
        except Exception as exc:
            raise RuntimeError(
                "persisted calibration dialog failed to open after summary reload"
            ) from exc

    runtime.harness.run_action(
        "calibration.open_via_ui",
        open_calibration_dialog,
        surface=InteractionSurface.UI,
    )
    dialog = runtime.context.view.pressure_box._droplet_imager_dialog
    driver = CalibrationDialogDriver(runtime.context.app, dialog)
    coordinates = runtime.observations["functional_storage"]["target_coordinates"]
    selected = runtime.harness.run_action(
        "calibration.select_via_ui",
        lambda: driver.select_persisted_result(**coordinates),
        surface=InteractionSurface.UI,
    )["evidence"]
    preview = driver.inspect_preview()
    apply_dialogs = runtime.harness.run_action(
        "calibration.apply_via_ui",
        lambda: {"dialogs": driver.apply_selected(expected_title="Applied")},
        surface=InteractionSurface.UI,
    )["evidence"]
    applied = _inspect_applied_record(
        runtime,
        selected,
        preview.get("payload", {}).get("source_row_fingerprint"),
    )
    driver.close()
    application_ok = (
        bool(preview.get("apply_enabled"))
        and apply_dialogs["dialogs"] == ["Applied"]
        and applied["matches_source"]
        and applied["settings_only_commands"]
        and applied["no_dispense_or_motion"]
    )
    runtime.observations["fresh_application"] = {
        "summary": after_summary,
        "reload_latency_ms": fresh_reload_ms,
        "selected": dict(selected),
        "preview": preview,
        "apply": apply_dialogs,
        "applied": applied,
    }
    runtime.add_assertion(
        _assertion(
            "calibration.storage.ui_application_exact",
            application_ok,
            runtime.observations["fresh_application"],
            checkpoint="ui_application",
            sources=(
                "CalibrationDialogDriver",
                "Controller",
                "execution_calibrations.json",
                "SimulatedMachine.command_event_history",
            ),
        )
    )


def _build_performance_cases() -> tuple[ScriptedCalibrationCase, ...]:
    _droplet_fixture, droplet_cases = load_fixture(
        CATALOG_PATH.parent / "droplet_sequence_nominal_v1.json"
    )
    _stream_fixture, stream_cases = load_fixture(
        CATALOG_PATH.parent / "online_stream_large_multi_update_v1.json"
    )
    small = droplet_cases[0]
    large = stream_cases[0]
    cases: list[ScriptedCalibrationCase] = []
    for head_index in range(1, 9):
        identity = {
            "printer_head_id": f"sil-performance-head-{head_index:02d}",
            "stock_id": f"sil-performance-stock-{head_index:02d}",
            "reagent_name": f"SIL Performance Reagent {head_index:02d}",
            "concentration": f"{head_index}.0",
            "units": "x",
        }
        for process_index in range(1, 25):
            cases.append(
                replace(
                    small,
                    fixture_id=PERFORMANCE_ID,
                    process_id=f"head-{head_index:02d}-run-{process_index:02d}",
                    identity=identity,
                    record_mode_enabled=True,
                    capture_mode="structured_only_proxy",
                    captures=(),
                )
            )
        cases.append(
            replace(
                large,
                fixture_id=PERFORMANCE_ID,
                process_id=f"head-{head_index:02d}-run-25-large",
                identity=identity,
                record_mode_enabled=True,
                capture_mode="structured_only_proxy",
                captures=(),
            )
        )
    return tuple(cases)


def _run_performance_workload(runtime: JourneyRuntime) -> dict[str, Any]:
    prepared = runtime.observations["prepared_experiment"]
    cases = _build_performance_cases()
    metrics = StorageMetricsCollector()
    resources = ProcessResourceSampler()
    resources.start()
    runner = StorageContractRunner(
        model=runtime.context.model,
        controller=runtime.context.controller,
        machine=runtime.context.machine,
        app=runtime.context.app,
        calibration_file_path=prepared["calibration_file"],
        timeout_seconds=runtime.harness.config.timeout_seconds,
        metrics=metrics,
    )
    runtime.register_restorable("calibration_storage_performance_runner", runner)
    evidence = []
    for index, case in enumerate(cases, start=1):
        evidence.append(runner.run_case(case).as_dict())
        if index % 25 == 0:
            resources.sample()

    calibration_path = Path(prepared["calibration_file"])
    reload_started = time.perf_counter_ns()
    runner.manager.load_calibration_data(str(calibration_path))
    metrics.fresh_reload_latency_ms.append(
        (time.perf_counter_ns() - reload_started) / 1_000_000.0
    )
    for head_index in range(1, 9):
        runner.characterization_rows(
            {
                "printer_head_id": f"sil-performance-head-{head_index:02d}",
                "stock_id": f"sil-performance-stock-{head_index:02d}",
                "reagent_name": f"SIL Performance Reagent {head_index:02d}",
                "concentration": f"{head_index}.0",
                "units": "x",
            }
        )
    resources.stop()

    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    workload_run_count = len(calibration.get("runs") or [])
    workload_update_count = sum(
        len(steps)
        for run in calibration.get("runs") or []
        for steps in (run.get("steps") or {}).values()
    )
    recording_capture_count = sum(int(row["capture_count"]) for row in evidence)

    _capture_fixture, capture_cases = load_fixture(
        CATALOG_PATH.parent / "capture_policy_v1.json"
    )
    probe_case = replace(
        next(case for case in capture_cases if case.process_id == "key-evidence-proxy"),
        fixture_id=PERFORMANCE_ID,
        process_id="key-evidence-drain-probe",
        identity=cases[-1].identity,
    )
    probe_path = Path(runtime.context.scenario_root) / "storage-probe" / "calibration.json"
    probe_path.parent.mkdir(parents=True, exist_ok=True)
    probe_runner = StorageContractRunner(
        model=runtime.context.model,
        controller=runtime.context.controller,
        machine=runtime.context.machine,
        app=runtime.context.app,
        calibration_file_path=probe_path,
        timeout_seconds=runtime.harness.config.timeout_seconds,
    )
    probe = probe_runner.run_case(probe_case).as_dict()
    probe_runner.restore()

    snapshot = {
        "workload_hash": semantic_sha256(
            {
                "fixture": runtime.fixture,
                "case_hashes": [
                    list(case.expected_update_hashes) for case in cases
                ],
            }
        ),
        "fixture_sha256": file_sha256(runtime.fixture_path),
        "process_run_count": len(evidence),
        "legacy_run_envelope_count": workload_run_count,
        "update_count": workload_update_count,
        "recording_count": sum(row["recording_dir"] is not None for row in evidence),
        "workload_capture_count": recording_capture_count,
        "key_evidence_probe": probe,
        "metrics": metrics.snapshot(),
        "resources": resources.snapshot(),
        "artifact_growth": {
            "calibration_json_bytes": calibration_path.stat().st_size,
            "scenario_total_bytes": sum(
                path.stat().st_size
                for path in Path(runtime.context.scenario_root).rglob("*")
                if path.is_file()
            ),
            "inventory": file_inventory(runtime.context.scenario_root),
        },
    }
    runtime.observations["performance_storage"] = snapshot
    return snapshot


def _performance_body(runtime: JourneyRuntime) -> None:
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    runtime.harness.run_action(
        "fixture.prepare_calibration_storage",
        lambda: _prepare_minimal_experiment(runtime),
        surface=InteractionSurface.MODEL,
    )
    runtime.harness.run_action(
        "calibration.run_scripted_processes",
        lambda: _run_performance_workload(runtime),
        surface=InteractionSurface.MODEL,
    )
    observed = runtime.observations["performance_storage"]
    runtime.harness.run_action(
        "calibration.inspect_storage_artifacts",
        lambda: {
            "fixture_sha256": observed["fixture_sha256"],
            "workload_hash": observed["workload_hash"],
        },
        surface=InteractionSurface.HARNESS,
    )
    counts = {
        key: observed[key]
        for key in (
            "process_run_count",
            "update_count",
            "recording_count",
            "workload_capture_count",
        )
    }
    runtime.add_assertion(
        _assertion(
            "calibration.storage.workload_counts_exact",
            counts
            == {
                "process_run_count": 200,
                "update_count": 232,
                "recording_count": 200,
                "workload_capture_count": 0,
            },
            counts,
            checkpoint="stress_terminal",
            sources=("calibration.json", "calibration_recordings"),
        )
    )
    metrics = observed["metrics"]
    metric_names = (
        "update_latency_ms",
        "process_finalize_latency_ms",
        "history_load_latency_ms",
        "fresh_reload_latency_ms",
        "calibration_rewrite_latency_ms",
        "recorder_append_latency_ms",
    )
    metrics_ok = all((metrics[name] or {}).get("count", 0) > 0 for name in metric_names)
    runtime.add_assertion(
        _assertion(
            "calibration.storage.metrics_complete",
            metrics_ok,
            metrics,
            checkpoint="stress_terminal",
            sources=("StorageMetricsCollector",),
        )
    )
    growth = observed["artifact_growth"]
    resources = observed["resources"]
    growth_ok = (
        growth["calibration_json_bytes"] > 0
        and growth["scenario_total_bytes"] >= growth["calibration_json_bytes"]
        and resources.get("status") in {"measured", "partial"}
        and resources.get("values", {}).get("peak_rss_bytes") is not None
    )
    runtime.add_assertion(
        _assertion(
            "calibration.storage.growth_recorded",
            growth_ok,
            {"artifact_growth": growth, "resources": resources},
            checkpoint="stress_terminal",
            sources=("filesystem", "ProcessResourceSampler"),
        )
    )
    probe = observed["key_evidence_probe"]
    probe_ok = (
        probe["capture_count"] == 2
        and all(
            capture["width"] == 16 and capture["height"] == 12
            for capture in probe["captures"]
        )
        and probe["meta_outcome"] == "completed"
    )
    runtime.add_assertion(
        _assertion(
            "calibration.storage.key_evidence_probe_exact",
            probe_ok,
            probe,
            checkpoint="recorder_drain_probe",
            sources=("calibration_recordings/captures", "run_meta.json"),
        )
    )


def _artifact_assertion(runtime: JourneyRuntime, teardown: Mapping[str, Any]) -> AssertionResult:
    return cleanup_assertion(teardown)


def _base_workload(runtime: JourneyRuntime) -> dict[str, Any]:
    return {
        "workload_id": runtime.definition.workload_id,
        "fixture_schema_version": runtime.fixture["schema_version"],
        "fixture_path": runtime.fixture_path.relative_to(REPO_ROOT).as_posix(),
        "fixture_sha256": file_sha256(runtime.fixture_path),
        "speed_multiplier": runtime.harness.config.speed_multiplier,
        "timeout_seconds": runtime.harness.config.timeout_seconds,
    }


def _functional_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    observed = runtime.observations.get("functional_storage") or {}
    fresh = runtime.observations.get("fresh_application") or {}
    metrics = dict(observed.get("metrics") or {})
    if fresh.get("reload_latency_ms") is not None:
        metrics["fresh_reload_latency_ms"] = {
            "count": 1,
            "minimum": fresh["reload_latency_ms"],
            "median": fresh["reload_latency_ms"],
            "p95": fresh["reload_latency_ms"],
            "maximum": fresh["reload_latency_ms"],
        }
    return ComposedReportPayload(
        workload={
            **_base_workload(runtime),
            **dict(runtime.fixture.get("workload") or {}),
        },
        workflow_values={
            "process_count": observed.get("process_count", 0),
            "application_sessions": len(runtime.harness.application_sessions),
            "cleanup_results": [dict(teardown)],
        },
        persistence={
            "status": "measured",
            "values": {
                "calibration_storage": {
                    **dict(observed),
                    "fresh_application": dict(fresh),
                    "metrics": metrics,
                }
            },
        },
        limitations=(
            "The scenario verifies current application storage and reader behavior only; it does not change or endorse the legacy schema.",
            "Capture policies are deterministic proxies and do not exercise camera acquisition or image analysis.",
            "No physical motion, dispense, pressure response, serial, GPIO, balance, firmware, or device-protocol claim is made.",
        ),
    )


def _performance_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    observed = dict(runtime.observations.get("performance_storage") or {})
    return ComposedReportPayload(
        workload={
            **_base_workload(runtime),
            **dict(runtime.fixture.get("workload") or {}),
            "workload_hash": observed.get("workload_hash"),
        },
        workflow_values={
            "process_run_count": observed.get("process_run_count", 0),
            "update_count": observed.get("update_count", 0),
            "cleanup_results": [dict(teardown)],
        },
        persistence={
            "status": "measured",
            "values": {"calibration_storage": observed},
        },
        resources=dict(observed.get("resources") or {"status": "not_available", "values": {}}),
        limitations=(
            "This is a current-writer characterization workload, not an acceptance threshold for the Milestone 2 store.",
            "Result finalization and index latency are explicitly unavailable until Milestone 2.",
            "No physical hardware, camera, image analysis, firmware, motion, dispense, or protocol behavior is exercised.",
        ),
    )


def _summary(report: Mapping[str, Any], runtime: JourneyRuntime) -> str:
    return (
        f"Calibration storage SIL: {runtime.definition.workload_id}\n"
        f"Status: {report['classification']['status']}\n"
        f"Application sessions: {len(runtime.harness.application_sessions)}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


FUNCTIONAL_DEFINITION = JourneyDefinition(
    registry_id=FUNCTIONAL_ID,
    scenario_name=FUNCTIONAL_SCENARIO,
    scenario_version="1",
    workload_id=FUNCTIONAL_ID,
    required_action_ids=FUNCTIONAL_ACTIONS,
    required_ui_action_ids=FUNCTIONAL_UI_ACTIONS,
    required_assertion_ids=FUNCTIONAL_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_functional_fixture,
    body=_functional_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_functional_payload,
    summary_builder=_summary,
)

PERFORMANCE_DEFINITION = JourneyDefinition(
    registry_id=PERFORMANCE_ID,
    scenario_name=PERFORMANCE_SCENARIO,
    scenario_version="1",
    workload_id=PERFORMANCE_ID,
    required_action_ids=PERFORMANCE_ACTIONS,
    required_ui_action_ids=frozenset(),
    required_assertion_ids=PERFORMANCE_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_performance_fixture,
    body=_performance_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_performance_payload,
    summary_builder=_summary,
)


__all__ = [
    "FUNCTIONAL_DEFINITION",
    "FUNCTIONAL_ID",
    "PERFORMANCE_DEFINITION",
    "PERFORMANCE_ID",
]
