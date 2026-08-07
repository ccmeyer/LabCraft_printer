"""Concise typed definitions for migrated SIL journeys."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tools.virtual_workflows.actions import capture_milestone
from tools.virtual_workflows.assertions import (
    ExecutionLifecycleExpectation,
    calibration_assertion,
    cleanup_assertion,
    editor_artifacts_cleanup_assertion,
    editor_create_finalize_assertion,
    editor_prepared_bundle_assertions,
    editor_prepared_reload_assertions,
    machine_ready_assertion,
    multi_stock_artifacts_assertion,
    multi_stock_prepared_assertion,
    execution_lifecycle_assertions,
    prepared_execution_assertion,
    rack_head_assertion,
    real_application_assertion,
    simulation_identity_assertion,
    terminal_execution_assertion,
)
from tools.virtual_workflows.composition import (
    JourneyDefinition,
    JourneyExecutor,
    JourneyRuntime,
)
from tools.virtual_workflows.execution_observer import ExecutionObserver
from tools.virtual_workflows.journey_phases import (
    EditorPreparationSpec,
    StockPassSpec,
    head_identity_step,
    machine_startup_steps,
    run_editor_preparation,
    run_stock_passes,
)
from tools.virtual_workflows.page_drivers import ExperimentLoaderDriver
from tools.virtual_workflows.report import ComposedReportPayload


REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_WORKLOAD_ID = "virtual_print_array_24_v1"
SMOKE_SCENARIO_NAME = "virtual_print_array"
SMOKE_SCENARIO_VERSION = "1"
EDITOR_WORKLOAD_ID = "experiment_editor_create_finalize_v1"
EDITOR_SCENARIO_NAME = "experiment_editor_create_finalize"
EDITOR_SCENARIO_VERSION = "1"
MULTI_STOCK_WORKLOAD_ID = "print_array_multi_stock_24x2_v1"
MULTI_STOCK_SCENARIO_NAME = "print_array_multi_stock_head_exchange"
MULTI_STOCK_SCENARIO_VERSION = "1"

SMOKE_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "machine.normal_ui_ready",
    "experiment.prepared_bundle_valid",
    "execution.rack_head_associated",
    "execution.applied_calibration_valid",
    "execution.terminal_bundle_valid",
    "artifacts.cleanup_complete",
)
EDITOR_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "experiment.editor_create_finalize",
    "experiment.prepared_bundle_valid",
    "experiment.prepared_reload_ready",
    "experiment.runtime_assignments_match",
    "experiment.key_files_consistent",
    "artifacts.required_present",
)
MULTI_STOCK_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "execution.multi_stock_head_exchange",
    "execution.stock_pass_boundaries_valid",
    "execution.stock_head_settings_match",
    "execution.expected_completions",
    "execution.no_queue_starvation",
    "execution.intent_durability_exact",
    "execution.event_history_bounded",
    "execution.terminal_bundle_valid",
    "artifacts.required_present",
)

SMOKE_REQUIRED_UI_ACTIONS = frozenset(
    {
        "machine.connect_via_ui",
        "machine.enable_motors_via_ui",
        "machine.home_via_ui",
        "machine.configure_print_settings_via_ui",
        "editor.open_via_ui",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        "editor.optimize_generate_via_ui",
        "editor.finish_via_ui",
        "head.set_volume_via_ui",
        "head.stage_via_ui",
        "pressure.enable_regulation_via_ui",
        "calibration.open_via_ui",
        "calibration.generate_via_ui",
        "calibration.select_via_ui",
        "calibration.apply_via_ui",
        "array.start_via_ui",
    }
)
EDITOR_REQUIRED_UI_ACTIONS = frozenset(
    {
        "editor.open_via_ui",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        "editor.optimize_generate_via_ui",
        "editor.finish_via_ui",
        "experiment.load_authoritative_via_ui",
    }
)
MULTI_STOCK_REQUIRED_UI_ACTIONS = SMOKE_REQUIRED_UI_ACTIONS | frozenset(
    {"head.return_via_ui"}
)
EDITOR_REQUIRED_SCREENSHOTS = frozenset(
    {"editor_opened", "generated", "finalized", "reloaded", "validated"}
)
MULTI_STOCK_REQUIRED_SCREENSHOTS = frozenset(
    {
        "editor_opened",
        "generated",
        "stock_1_ready",
        "stock_1_printing",
        "stock_1_completed",
        "stock_2_staged",
        "stock_2_printing",
        "completed",
    }
)

_COMMON_ACTIONS = frozenset(
    {"app.launch_simulated", "artifact.capture_milestone", "scenario.teardown"}
)
_EDITOR_ACTIONS = frozenset(
    {
        "editor.open_via_ui",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        "editor.optimize_generate_via_ui",
        "editor.finish_via_ui",
    }
)
_PRINT_ACTIONS = frozenset(
    {
        "machine.connect_via_ui",
        "machine.enable_motors_via_ui",
        "machine.home_via_ui",
        "machine.configure_print_settings_via_ui",
        "head.set_volume_via_ui",
        "head.stage_via_ui",
        "pressure.enable_regulation_via_ui",
        "calibration.open_via_ui",
        "calibration.generate_via_ui",
        "calibration.select_via_ui",
        "calibration.apply_via_ui",
        "array.start_via_ui",
        "array.wait_for_completions",
    }
)


@dataclass(frozen=True)
class JourneyRunConfig:
    scenario_id: str = SMOKE_WORKLOAD_ID
    output_root: Path = REPO_ROOT / "verification_reports" / "virtual_workflows"
    visible: bool = False
    seed: int = 1
    speed_multiplier: float = 1.0
    timeout_seconds: float = 180.0
    run_id: str | None = None

    def __post_init__(self) -> None:
        if self.scenario_id not in JOURNEY_DEFINITION_IDS:
            raise ValueError(f"unsupported composed journey: {self.scenario_id!r}")
        object.__setattr__(self, "output_root", Path(self.output_root).resolve())


def _print_fixture(workload_id: str) -> tuple[dict[str, Any], Path]:
    from tools.virtual_workflows.scenarios import load_virtual_print_array_fixture

    path = Path(__file__).resolve().parent / "fixtures" / f"{workload_id}.json"
    return load_virtual_print_array_fixture(path, scenario_id=workload_id), path


def _smoke_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(SMOKE_WORKLOAD_ID)


def _multi_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(MULTI_STOCK_WORKLOAD_ID)


def _editor_fixture() -> tuple[dict[str, Any], Path]:
    from tools.virtual_workflows.editor_scenarios import (
        load_editor_create_finalize_fixture,
    )

    path = Path(__file__).resolve().parent / "fixtures" / f"{EDITOR_WORKLOAD_ID}.json"
    return load_editor_create_finalize_fixture(path), path


def _well_ids(fixture: Mapping[str, Any]) -> tuple[str, ...]:
    from tools.virtual_workflows.scenarios import fixture_well_ids

    return fixture_well_ids(dict(fixture))


def _stock_id(stock: Mapping[str, Any]) -> str:
    return f"{stock['factor_name']}_{float(stock['concentration']):.2f}_{stock['units']}"


def _editor_specification(
    fixture: Mapping[str, Any], expected_wells: tuple[str, ...]
) -> dict[str, Any]:
    stocks = tuple(fixture["stocks"])
    printed_volume = sum(float(stock["droplet_volume_nL"]) for stock in stocks)
    reagents = [
        {
            "stock_label": stock["factor_name"],
            "group": "Additive",
            "printing_mode": stock["printing_mode"],
            "starting_concentration": 0.0,
            "targets": [float(stock["target_concentration"])],
            "units": stock["units"],
            "fixed_stock_concentration": float(stock["concentration"]),
            "droplet_volume_nL": float(stock["droplet_volume_nL"]),
        }
        for stock in stocks
    ]
    specification = {
        "experiment": {
            "name": fixture["fixture_id"],
            "plate_name": fixture["plate"]["name"],
            "replicates": len(expected_wells),
            "expected_well_ids": list(expected_wells),
            "printed_volume_nL": printed_volume,
            "final_volume_nL": printed_volume,
            "printed_volume_tolerance_nL": 0.0,
            "randomize_assignments": False,
            "allow_two_stock_solutions": False,
        },
    }
    specification["reagent" if len(reagents) == 1 else "reagents"] = (
        reagents[0] if len(reagents) == 1 else reagents
    )
    return specification


def _connect_execution_signals(
    runtime: JourneyRuntime,
    *,
    array_complete: bool,
    machine_errors: bool,
) -> None:
    context = runtime.context
    completed = runtime.observations.setdefault("completed_wells", [])
    context.model.well_plate.well_state_changed_signal.connect(
        lambda well_id: completed.append(str(well_id))
    )
    context.controller.array_state_changed.connect(
        lambda state: context.array_states.append(str(state))
    )
    context.controller.error_occurred_signal.connect(
        lambda *values: context.errors.append(
            {"source": "controller", "arguments": [str(value) for value in values]}
        )
    )
    if array_complete:
        completions = runtime.observations.setdefault("array_completions", [])
        context.controller.array_complete.connect(
            lambda: completions.append(len(completed))
        )
    if machine_errors:
        context.machine.error_occurred.connect(
            lambda *values: context.errors.append(
                {"source": "machine", "arguments": [str(value) for value in values]}
            )
        )


def _smoke_pass(runtime: JourneyRuntime) -> StockPassSpec:
    fixture = runtime.fixture
    stock = fixture["stocks"][0]
    head = stock["printer_head"]
    return StockPassSpec(
        stock_id=_stock_id(stock),
        printer_head_id=str(head["printer_head_id"]),
        pulse_width_us=int(head["print_pulse_width_us"]),
        pressure_psi=float(head["print_pressure_psi"]),
        frequency_hz=int(fixture["simulation"]["dispense_frequency_hz"]),
        initial_volume_uL=float(head["initial_volume_uL"]),
        expected_volume_nL=float(stock["droplet_volume_nL"]),
        expected_completion_count=len(_well_ids(fixture)),
        expected_plan_state="completed",
        ready_milestone="ready",
        printing_milestone="printing",
        completed_milestone="completed",
        staging_slot=int(fixture["simulation"]["staging_slot"]),
        enable_pressure_regulation=True,
    )


def _multi_passes(runtime: JourneyRuntime) -> tuple[StockPassSpec, ...]:
    fixture = runtime.fixture
    well_count = len(_well_ids(fixture))
    result = []
    for index, stock in enumerate(fixture["stocks"]):
        head = stock["printer_head"]
        result.append(
            StockPassSpec(
                stock_id=_stock_id(stock),
                printer_head_id=str(head["printer_head_id"]),
                pulse_width_us=int(head["print_pulse_width_us"]),
                pressure_psi=float(head["print_pressure_psi"]),
                frequency_hz=int(fixture["simulation"]["dispense_frequency_hz"]),
                initial_volume_uL=float(head["initial_volume_uL"]),
                expected_volume_nL=float(stock["droplet_volume_nL"]),
                expected_completion_count=well_count * (index + 1),
                expected_plan_state="active" if index == 0 else "completed",
                ready_milestone="stock_1_ready" if index == 0 else "stock_2_staged",
                printing_milestone=(
                    "stock_1_printing" if index == 0 else "stock_2_printing"
                ),
                completed_milestone="stock_1_completed" if index == 0 else "completed",
                start_dialog_titles=(
                    ("Start Print Array", "Evaporation Plate Dock Check")
                    if index == 0
                    else ("Start Print Array",)
                ),
                bind_identity=True,
                enable_pressure_regulation=index == 0,
                validate_pass_boundary=True,
                return_head=True,
                detailed_evidence=True,
                include_frequency_evidence=False,
            )
        )
    return tuple(result)


def _smoke_body(runtime: JourneyRuntime) -> None:
    expected_wells = _well_ids(runtime.fixture)
    runtime.observations["expected_wells"] = expected_wells
    _connect_execution_signals(runtime, array_complete=False, machine_errors=False)
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    runtime.run_steps(machine_startup_steps())
    runtime.add_assertion(machine_ready_assertion(runtime.context))
    run_editor_preparation(
        runtime,
        EditorPreparationSpec(
            _editor_specification(runtime.fixture, expected_wells),
            snapshot_finish=True,
        ),
    )
    runtime.add_assertion(
        prepared_execution_assertion(runtime.context, len(expected_wells))
    )
    stock_pass = _smoke_pass(runtime)
    run_stock_passes(runtime, (stock_pass,))
    runtime.add_assertion(rack_head_assertion(runtime.context))
    runtime.add_assertion(
        calibration_assertion(
            runtime.context,
            expected_volume_nL=stock_pass.expected_volume_nL,
            expected_pulse_width_us=stock_pass.pulse_width_us,
            expected_pressure_psi=stock_pass.pressure_psi,
        )
    )
    runtime.add_assertion(
        terminal_execution_assertion(
            runtime.context,
            completed_wells=runtime.observations["completed_wells"],
            expected_well_ids=expected_wells,
        )
    )


def _editor_body(runtime: JourneyRuntime) -> None:
    fixture = runtime.fixture
    expected_wells = tuple(fixture["experiment"]["expected_well_ids"])
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    runtime.add_assertion(real_application_assertion(runtime.context))
    run_editor_preparation(
        runtime,
        EditorPreparationSpec(fixture, use_harness_action_runner=True),
    )
    runtime.add_assertion(editor_create_finalize_assertion(runtime.context))
    capture_milestone(
        runtime.context,
        "finalized",
        evidence={"experiment_name": fixture["experiment"]["name"]},
    )
    bundle, keys = editor_prepared_bundle_assertions(
        runtime.context, expected_well_ids=expected_wells
    )
    runtime.add_assertion(bundle)
    prepared = dict(bundle.evidence)
    loader_evidence = runtime.harness.run_action(
        "experiment.load_authoritative_via_ui",
        lambda: ExperimentLoaderDriver(runtime.context).load_prepared_design(
            Path(prepared["experiment_dir"]),
            expected_name=fixture["experiment"]["name"],
            expected_plan_id=str(prepared["plan_id"]),
            expected_plan_revision=int(prepared["plan_revision"]),
        ),
    )["evidence"]
    capture_milestone(
        runtime.context,
        "reloaded",
        evidence={key: loader_evidence[key] for key in ("plan_state", "eligibility_status")},
    )
    reload_result, assignments = editor_prepared_reload_assertions(
        runtime.context,
        prepared_evidence=prepared,
        loader_evidence=loader_evidence,
    )
    for result in (reload_result, assignments, keys):
        runtime.add_assertion(result)
    capture_milestone(
        runtime.context,
        "validated",
        evidence={
            "plan_state": reload_result.evidence.get("plan_state"),
            "eligibility_status": reload_result.evidence.get("eligibility_status"),
            "assertion_count": len(EDITOR_REQUIRED_ASSERTIONS),
        },
    )


def _multi_body(runtime: JourneyRuntime) -> None:
    context = runtime.context
    fixture = runtime.fixture
    expected_wells = _well_ids(fixture)
    expected_stock_ids = tuple(_stock_id(stock) for stock in fixture["stocks"])
    runtime.observations.update(
        {
            "expected_wells": expected_wells,
            "expected_stock_ids": expected_stock_ids,
            "starvation_events": [],
            "current_pass": {"index": -1, "starting_count": 0, "stock_id": None},
        }
    )
    _connect_execution_signals(runtime, array_complete=True, machine_errors=True)
    runtime.add_assertion(simulation_identity_assertion(context))
    runtime.add_assertion(real_application_assertion(context))
    runtime.run_steps(machine_startup_steps())
    run_editor_preparation(
        runtime,
        EditorPreparationSpec(_editor_specification(fixture, expected_wells)),
    )
    prepared = multi_stock_prepared_assertion(
        context,
        expected_well_ids=expected_wells,
        expected_stock_ids=expected_stock_ids,
    )
    if prepared.decision != "pass":
        raise RuntimeError(f"prepared multi-stock bundle was invalid: {prepared.evidence}")
    pass_specs = _multi_passes(runtime)
    runtime.run_steps((head_identity_step(pass_specs),))
    observer = ExecutionObserver(
        context,
        experiment_dir=Path(context.experiment_model.experiment_dir_path),
        completed_count=lambda: len(runtime.observations["completed_wells"]),
        pass_context=lambda: _current_pass_context(runtime),
    )
    runtime.register_restorable("execution", observer)
    observer.install()
    _install_starvation_observer(runtime)
    run_stock_passes(runtime, pass_specs, bind_identities=False)
    runtime.restore_all()
    snapshot = runtime.observations["execution_snapshot"]
    for assertion in execution_lifecycle_assertions(
        context,
        expectation=ExecutionLifecycleExpectation(
            fixture=fixture,
            expected_well_ids=expected_wells,
            expected_stock_ids=expected_stock_ids,
        ),
        completed_wells=runtime.observations["completed_wells"],
        pass_boundaries=runtime.observations["pass_boundaries"],
        head_staging=runtime.observations["head_staging"],
        starvation_events=runtime.observations["starvation_events"],
        observer=snapshot,
    ):
        runtime.add_assertion(assertion)


def _current_pass_context(runtime: JourneyRuntime) -> Mapping[str, Any] | None:
    current = runtime.observations["current_pass"]
    if int(current["index"]) < 0:
        return None
    return {
        "pass_index": int(current["index"]) + 1,
        "stock_id": current["stock_id"],
    }


def _install_starvation_observer(runtime: JourneyRuntime) -> None:
    context = runtime.context

    def on_queue_drained() -> None:
        current = runtime.observations["current_pass"]
        completed = runtime.observations["completed_wells"]
        completed_in_pass = len(completed) - int(current["starting_count"])
        if (
            context.controller.get_array_run_state() == "running"
            and int(current["index"]) >= 0
            and completed_in_pass < len(runtime.observations["expected_wells"])
        ):
            runtime.observations["starvation_events"].append(
                {
                    "pass_index": int(current["index"]) + 1,
                    "stock_id": current["stock_id"],
                    "completed_in_pass": completed_in_pass,
                    "array_state": "running",
                }
            )

    context.machine.command_queue.commands_completed.connect(on_queue_drained)


def _decisions(runtime: JourneyRuntime) -> dict[str, str]:
    return {
        str(row.get("assertion_id")): str(row.get("decision"))
        for row in runtime.harness.assertion_results
    }


def _assertion_evidence(runtime: JourneyRuntime) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("assertion_id")): dict(row.get("evidence") or {})
        for row in runtime.harness.assertion_results
    }


def _base_workload(runtime: JourneyRuntime) -> dict[str, Any]:
    return {
        "workload_id": runtime.definition.workload_id,
        "fixture_schema_version": runtime.fixture["schema_version"],
        "fixture_path": runtime.fixture_path.relative_to(REPO_ROOT).as_posix(),
        "fixture_sha256": hashlib.sha256(runtime.fixture_path.read_bytes()).hexdigest(),
    }


def _smoke_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    fixture = runtime.fixture
    expected = runtime.observations["expected_wells"]
    completed = runtime.observations["completed_wells"]
    decisions = _decisions(runtime)
    evidence = _assertion_evidence(runtime)
    passed = all(decisions.get(item) == "pass" for item in SMOKE_REQUIRED_ASSERTIONS)
    workload = {
        **_base_workload(runtime),
        "plate_name": fixture["plate"]["name"],
        "plate_rows": fixture["plate"]["rows"],
        "plate_columns": fixture["plate"]["columns"],
        "well_ids": list(expected),
        "stock_count": 1,
        "array_passes": 1,
        "target_dispenses_per_well": 1,
        "expected_completion_count": len(expected),
        "speed_multiplier": runtime.harness.config.speed_multiplier,
        "timeout_seconds": runtime.harness.config.timeout_seconds,
    }
    return ComposedReportPayload(
        workload=workload,
        workflow_values={
            "expected_well_count": len(expected),
            "completed_well_count": len(completed),
            "expected_stock_well_completion_count": len(expected),
            "completed_stock_well_count": len(completed),
            "completed_well_ids": list(completed),
            "well_update_count": len(completed),
            "array_states": list(runtime.context.array_states),
            "cleanup_results": [dict(teardown)],
        },
        queue={
            "status": "measured",
            "values": {
                "queue_drained_at_terminal": bool(
                    evidence.get("execution.terminal_bundle_valid", {}).get(
                        "queue_drained"
                    )
                )
            },
        },
        persistence={
            "status": "measured" if passed else "partial",
            "values": {
                "assertion_decisions": decisions,
                "terminal": evidence.get("execution.terminal_bundle_valid", {}),
            },
        },
        limitations=(
            "The simulator verifies the application-facing contract, not firmware framing or ACK behavior.",
            "No physical motion, collision safety, pressure response, camera analysis, balance behavior, or droplet quality is modeled.",
            "Session-specific plan, printer-head, timestamp, and calibration identities are recorded but are not expected to be byte-identical across replay.",
        ),
    )


def _editor_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    fixture = runtime.fixture
    decisions = _decisions(runtime)
    evidence = _assertion_evidence(runtime)
    passed = all(decisions.get(item) == "pass" for item in EDITOR_REQUIRED_ASSERTIONS)
    return ComposedReportPayload(
        workload={
            **_base_workload(runtime),
            "experiment_name": fixture["experiment"]["name"],
            "plate_name": fixture["experiment"]["plate_name"],
            "expected_reaction_count": fixture["experiment"]["replicates"],
            "well_ids": list(fixture["experiment"]["expected_well_ids"]),
            "expected_editor_finalization_operations": fixture["workload"][
                "expected_editor_finalization_operations"
            ],
            "speed_multiplier": runtime.harness.config.speed_multiplier,
            "timeout_seconds": runtime.harness.config.timeout_seconds,
        },
        workflow_values={"cleanup_results": [dict(teardown)]},
        queue={"status": "not_applicable", "values": {"print_commands_executed": 0}},
        persistence={
            "status": "measured" if passed else "partial",
            "values": {
                "assertion_decisions": decisions,
                "prepared_bundle": evidence.get("experiment.prepared_bundle_valid", {}),
                "reload_activation": evidence.get("experiment.prepared_reload_ready", {}),
            },
        },
        limitations=(
            "The scenario validates the editor and authoritative application lifecycle without printing or connecting the simulated machine.",
            "The simulator does not validate firmware, protocol framing, motion, pressure, cameras, balance behavior, or droplet quality.",
            "Generated plan IDs, timestamps, durations, and session paths are not expected to be byte-identical across replay.",
        ),
    )


def _multi_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    fixture = runtime.fixture
    observations = runtime.observations
    expected = observations["expected_wells"]
    completed = [
        well for well in observations["completed_wells"] if well in set(expected)
    ]
    decisions = _decisions(runtime)
    evidence = _assertion_evidence(runtime)
    passed = all(
        decisions.get(item) == "pass" for item in MULTI_STOCK_REQUIRED_ASSERTIONS
    )
    multi = evidence.get("execution.multi_stock_head_exchange", {})
    observer = dict(observations.get("execution_snapshot") or {})
    progress = dict(observer.get("progress_snapshot") or {})
    durable = dict(observer.get("durable_io_samples_ms") or {})
    authoritative_io = {
        "resume_save_fsync_count": len(durable.get("fsync", {}).get("persistence.save_resume", [])),
        "resume_save_replace_count": len(durable.get("atomic_replace", {}).get("persistence.save_resume", [])),
        "progress_write_fsync_count": len(durable.get("fsync", {}).get("persistence.write_progress", [])),
        "progress_write_replace_count": len(durable.get("atomic_replace", {}).get("persistence.write_progress", [])),
        "read_opens": dict(observer.get("authoritative_reads") or {}),
        "observer_restored": bool(observer.get("restored")),
    }
    boundaries = observations.get("pass_boundaries", [])
    starvation = observations.get("starvation_events", [])
    return ComposedReportPayload(
        workload={
            **_base_workload(runtime),
            "plate_name": fixture["plate"]["name"],
            "plate_rows": fixture["plate"]["rows"],
            "plate_columns": fixture["plate"]["columns"],
            "well_ids": list(expected),
            "stock_count": 2,
            "array_passes": 2,
            "target_dispenses_per_well": 1,
            "expected_completion_count": 48,
            "speed_multiplier": runtime.harness.config.speed_multiplier,
            "timeout_seconds": runtime.harness.config.timeout_seconds,
        },
        workflow_status="measured" if passed else "partial",
        workflow_values={
            "expected_well_count": len(expected),
            "completed_well_count": len(set(completed)),
            "expected_stock_well_completion_count": 48,
            "completed_stock_well_count": len(completed),
            "completed_well_ids": completed,
            "well_update_count": len(completed),
            "array_states": list(runtime.context.array_states),
            "array_complete_count": len(observations.get("array_completions", [])),
            "pass_terminal_states": [row.get("plan_state") for row in boundaries],
            "stock_passes": [
                {**dict(row), "completed_well_updates": len(expected)}
                for row in boundaries
            ],
            "cleanup_results": [dict(teardown)],
        },
        queue={
            "status": "measured" if passed else "partial",
            "values": {
                "unexpected_starvation_count": len(starvation),
                "unexpected_starvation_events": list(starvation),
                "queue_drained_at_terminal": bool(multi.get("terminal", {}).get("queue_drained")),
                "simulator_cleanup": {
                    "command_timer_active": bool(getattr(runtime.context.machine, "_command_timer", None) and runtime.context.machine._command_timer.isActive()),
                    "connection_timer_active": bool(getattr(runtime.context.machine, "_connection_timer", None) and runtime.context.machine._connection_timer.isActive()),
                    "deferred_timer_count": len(getattr(runtime.context.machine, "_deferred_timers", ()) or ()),
                },
            },
        },
        persistence={
            "status": "measured" if passed else "partial",
            "values": {
                "assertion_decisions": decisions,
                "multi_stock_head_exchange": multi,
                "stock_well_completion_count": len(completed),
                "progress_snapshot": progress,
                "authoritative_io": authoritative_io,
            },
        },
        limitations=(
            "The two-stock lifecycle uses an in-process simulator and normal Qt controls; it does not validate physical head handling or output.",
            "The simulator does not validate firmware, protocol framing, motion, pressure response, cameras, balance behavior, or droplet quality.",
            "Generated plan IDs, timestamps, durations, paths, and calibration identities are not expected to be byte-identical across replay.",
        ),
    )


def _cleanup_artifact(runtime: JourneyRuntime, teardown: Mapping[str, Any]) -> Any:
    return cleanup_assertion(teardown)


def _editor_artifact(runtime: JourneyRuntime, teardown: Mapping[str, Any]) -> Any:
    return editor_artifacts_cleanup_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(EDITOR_REQUIRED_SCREENSHOTS),
        teardown=teardown,
    )


def _multi_artifact(runtime: JourneyRuntime, teardown: Mapping[str, Any]) -> Any:
    return multi_stock_artifacts_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(MULTI_STOCK_REQUIRED_SCREENSHOTS),
        teardown=teardown,
    )


def _smoke_summary(report: Mapping[str, Any], runtime: JourneyRuntime) -> str:
    values = report["metrics"]["workflow"]["values"]
    return (
        "Milestone 6 composed 24-well smoke\n"
        f"Status: {report['classification']['status']}\n"
        f"Completions: {values['completed_stock_well_count']} / {report['workload']['expected_completion_count']}\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _editor_summary(report: Mapping[str, Any], runtime: JourneyRuntime) -> str:
    passed = sum(row["decision"] == "pass" for row in runtime.harness.assertion_results)
    return (
        "Milestone 7 composed editor create/finalize/reload\n"
        f"Status: {report['classification']['status']}\n"
        f"Assertions: {passed} / {len(EDITOR_REQUIRED_ASSERTIONS)}\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _multi_summary(report: Mapping[str, Any], runtime: JourneyRuntime) -> str:
    return (
        "Milestone 7 composed two-stock 24x2 lifecycle\n"
        f"Status: {report['classification']['status']}\n"
        f"Completions: {len(runtime.observations['completed_wells'])} / 48\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


SMOKE_DEFINITION = JourneyDefinition(
    registry_id=SMOKE_WORKLOAD_ID,
    scenario_name=SMOKE_SCENARIO_NAME,
    scenario_version=SMOKE_SCENARIO_VERSION,
    workload_id=SMOKE_WORKLOAD_ID,
    required_action_ids=_COMMON_ACTIONS | _EDITOR_ACTIONS | _PRINT_ACTIONS,
    required_ui_action_ids=SMOKE_REQUIRED_UI_ACTIONS,
    required_assertion_ids=SMOKE_REQUIRED_ASSERTIONS,
    required_screenshots=frozenset({"editor_opened", "generated", "ready", "printing", "completed"}),
    fixture_loader=_smoke_fixture,
    body=_smoke_body,
    artifact_assertion=_cleanup_artifact,
    payload_builder=_smoke_payload,
    summary_builder=_smoke_summary,
)
EDITOR_DEFINITION = JourneyDefinition(
    registry_id=EDITOR_WORKLOAD_ID,
    scenario_name=EDITOR_SCENARIO_NAME,
    scenario_version=EDITOR_SCENARIO_VERSION,
    workload_id=EDITOR_WORKLOAD_ID,
    required_action_ids=_COMMON_ACTIONS | _EDITOR_ACTIONS | frozenset({"experiment.load_authoritative_via_ui"}),
    required_ui_action_ids=EDITOR_REQUIRED_UI_ACTIONS,
    required_assertion_ids=EDITOR_REQUIRED_ASSERTIONS,
    required_screenshots=EDITOR_REQUIRED_SCREENSHOTS,
    fixture_loader=_editor_fixture,
    body=_editor_body,
    artifact_assertion=_editor_artifact,
    payload_builder=_editor_payload,
    summary_builder=_editor_summary,
)
MULTI_STOCK_DEFINITION = JourneyDefinition(
    registry_id=MULTI_STOCK_WORKLOAD_ID,
    scenario_name=MULTI_STOCK_SCENARIO_NAME,
    scenario_version=MULTI_STOCK_SCENARIO_VERSION,
    workload_id=MULTI_STOCK_WORKLOAD_ID,
    required_action_ids=_COMMON_ACTIONS | _EDITOR_ACTIONS | _PRINT_ACTIONS | frozenset({"head.bind_identity", "head.return_via_ui", "validation.stock_pass_boundary"}),
    required_ui_action_ids=MULTI_STOCK_REQUIRED_UI_ACTIONS,
    required_assertion_ids=MULTI_STOCK_REQUIRED_ASSERTIONS,
    required_screenshots=MULTI_STOCK_REQUIRED_SCREENSHOTS,
    fixture_loader=_multi_fixture,
    body=_multi_body,
    artifact_assertion=_multi_artifact,
    payload_builder=_multi_payload,
    summary_builder=_multi_summary,
)

JOURNEY_DEFINITIONS = {
    definition.registry_id: definition
    for definition in (SMOKE_DEFINITION, EDITOR_DEFINITION, MULTI_STOCK_DEFINITION)
}
JOURNEY_DEFINITION_IDS = frozenset(JOURNEY_DEFINITIONS)


def get_journey_definition(scenario_id: str) -> JourneyDefinition:
    try:
        return JOURNEY_DEFINITIONS[str(scenario_id)]
    except KeyError as exc:
        raise ValueError(f"unsupported composed journey: {scenario_id!r}") from exc


def run_composed_journey(config: JourneyRunConfig) -> dict[str, Any]:
    return JourneyExecutor().run(get_journey_definition(config.scenario_id), config)


def run_virtual_print_array_24_journey(config: JourneyRunConfig) -> dict[str, Any]:
    return JourneyExecutor().run(SMOKE_DEFINITION, config)


def run_editor_create_finalize_journey(config: JourneyRunConfig) -> dict[str, Any]:
    return JourneyExecutor().run(EDITOR_DEFINITION, config)


def run_multi_stock_24x2_journey(config: JourneyRunConfig) -> dict[str, Any]:
    return JourneyExecutor().run(MULTI_STOCK_DEFINITION, config)


__all__ = [
    "EDITOR_WORKLOAD_ID",
    "JOURNEY_DEFINITIONS",
    "JourneyRunConfig",
    "MULTI_STOCK_REQUIRED_ASSERTIONS",
    "MULTI_STOCK_REQUIRED_UI_ACTIONS",
    "MULTI_STOCK_WORKLOAD_ID",
    "SMOKE_WORKLOAD_ID",
    "get_journey_definition",
    "run_composed_journey",
    "run_editor_create_finalize_journey",
    "run_multi_stock_24x2_journey",
    "run_virtual_print_array_24_journey",
]
