"""Concise typed definitions for migrated SIL journeys."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from tools.virtual_workflows.actions import capture_milestone
from tools.virtual_workflows.assertions import (
    ExecutionLifecycleExpectation,
    calibration_assertion,
    cleanup_assertion,
    capture_editor_prepared_revision_snapshot,
    editor_artifacts_cleanup_assertion,
    editor_create_finalize_assertion,
    editor_post_start_lock_copy_assertions,
    editor_prepared_bundle_assertions,
    editor_prepared_revision_assertions,
    editor_prepared_revision_failure_assertion,
    editor_prepared_reload_assertions,
    machine_ready_assertion,
    multi_stock_artifacts_assertion,
    multi_stock_prepared_assertion,
    execution_lifecycle_assertions,
    prepared_execution_assertion,
    rack_head_assertion,
    real_application_assertion,
    simulation_identity_assertion,
    sustained_evidence_assertions,
    SoftStopResumeExpectation,
    DisconnectFailClosedExpectation,
    authoritative_reload_terminal_assertions,
    disconnect_fail_closed_assertions,
    soft_stop_paused_assertions,
    soft_stop_terminal_assertions,
    terminal_execution_assertion,
)
from tools.virtual_workflows.composition import (
    JourneyDefinition,
    JourneyExecutor,
    JourneyRuntime,
)
from tools.virtual_workflows.execution_observer import ExecutionObserver
from tools.virtual_workflows.authoritative_evidence import (
    capture_authoritative_bundle,
    merge_session_lifecycles,
)
from tools.virtual_workflows.editor_reporting import (
    EditorLifecycleReportSpec,
    build_editor_lifecycle_payload,
    create_finalize_report_spec,
    prepared_revision_report_spec,
)
from tools.virtual_workflows.journey_phases import (
    EditorPreparationSpec,
    PreparedEditorRevisionSpec,
    PostStartLockCopySpec,
    StockPassSpec,
    SoftStopResumeSpec,
    DisconnectFailClosedSpec,
    capture_completion_midpoint,
    head_identity_step,
    machine_startup_steps,
    run_editor_preparation,
    run_prepared_editor_revision,
    run_post_start_lock_copy,
    run_stock_passes,
    run_soft_stop_resume,
    run_disconnect_fail_closed_boundary,
    run_authoritative_reload_resume_boundary,
)
from tools.virtual_workflows.page_drivers import ExperimentLoaderDriver
from tools.virtual_workflows.report import ComposedReportPayload


REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_WORKLOAD_ID = "virtual_print_array_24_v1"
REGRESSION_WORKLOAD_ID = "virtual_print_array_96_v1"
SMOKE_SCENARIO_NAME = "virtual_print_array"
SMOKE_SCENARIO_VERSION = "1"
EDITOR_WORKLOAD_ID = "experiment_editor_create_finalize_v1"
EDITOR_SCENARIO_NAME = "experiment_editor_create_finalize"
EDITOR_SCENARIO_VERSION = "1"
EDITOR_REVISION_WORKLOAD_ID = "experiment_editor_prestart_rename_refinalize_v1"
EDITOR_REVISION_SCENARIO_NAME = "experiment_editor_prestart_rename_refinalize"
EDITOR_REVISION_SCENARIO_VERSION = "1"
MULTI_STOCK_WORKLOAD_ID = "print_array_multi_stock_24x2_v1"
MULTI_STOCK_SCENARIO_NAME = "print_array_multi_stock_head_exchange"
MULTI_STOCK_SCENARIO_VERSION = "1"
STRESS_WORKLOAD_ID = "virtual_print_array_384x10_v1"
STRESS_FIXED_CALIBRATION_PULSE_WIDTH_US = 1355
SOFT_STOP_WORKLOAD_ID = "print_array_soft_stop_resume_24_v1"
SOFT_STOP_SCENARIO_NAME = "print_array_soft_stop_resume"
SOFT_STOP_SCENARIO_VERSION = "1"
AUTHORITATIVE_RELOAD_WORKLOAD_ID = "authoritative_reload_resume_24_v1"
AUTHORITATIVE_RELOAD_SCENARIO_NAME = "authoritative_reload_resume"
AUTHORITATIVE_RELOAD_SCENARIO_VERSION = "1"
POST_START_LOCK_WORKLOAD_ID = "experiment_editor_post_start_lock_v1"
DISCONNECT_WORKLOAD_ID = "print_array_disconnect_mid_array_24_v1"
DISCONNECT_SCENARIO_NAME = "print_array_disconnect_fail_closed"

SMOKE_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "machine.normal_ui_ready",
    "experiment.prepared_bundle_valid",
    "execution.rack_head_associated",
    "execution.applied_calibration_valid",
    "execution.terminal_bundle_valid",
    "artifacts.cleanup_complete",
)
REGRESSION_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "sil.pi_evidence_valid",
    "ui.real_app_constructed",
    "execution.expected_completions",
    "execution.no_queue_starvation",
    "execution.intent_durability_exact",
    "execution.terminal_bundle_valid",
    "artifacts.required_present",
    "ui.injected_stall_detected",
    "ui.responsiveness_metrics_present",
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
EDITOR_REVISION_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "experiment.prepared_rename_refinalize",
    "experiment.prepared_design_refinalize",
    "experiment.renamed_artifacts_unique",
    "experiment.refinalized_bundle_valid",
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
STRESS_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled", "sil.pi_evidence_valid",
    "ui.real_app_constructed", "execution.multi_stock_head_exchange",
    "execution.stock_pass_boundaries_valid", "execution.stock_head_settings_match",
    "execution.expected_completions", "execution.no_queue_starvation",
    "execution.intent_durability_exact", "execution.event_history_bounded",
    "execution.terminal_bundle_valid", "artifacts.required_present",
    "ui.injected_stall_detected", "ui.responsiveness_metrics_present",
    "ui.sustained_responsiveness_acceptable", "resources.metrics_present",
)
SOFT_STOP_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "execution.soft_stop_requested",
    "execution.soft_stop_boundary_valid",
    "execution.stopped_boundary_quiescent",
    "execution.resume_exactly_once",
    "execution.expected_completions",
    "execution.intent_durability_exact",
    "execution.terminal_bundle_valid",
    "artifacts.required_present",
)
AUTHORITATIVE_RELOAD_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "ui.fresh_application_session_constructed",
    "execution.first_session_paused",
    "execution.first_session_teardown_clean",
    "execution.authoritative_reload_valid",
    "execution.authoritative_runtime_rehydrated",
    "execution.reload_resume_exactly_once",
    "execution.expected_completions",
    "execution.intent_durability_exact",
    "execution.terminal_bundle_valid",
    "artifacts.required_present",
)
POST_START_LOCK_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled", "ui.real_app_constructed",
    "experiment.active_edit_lock", "experiment.in_place_edit_rejected",
    "experiment.source_bundle_immutable", "experiment.editable_copy_created",
    "experiment.editable_copy_fresh_execution",
    "experiment.editable_copy_editable", "artifacts.required_present",
)
DISCONNECT_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "execution.disconnect_requested",
    "execution.disconnect_fail_closed",
    "execution.disconnected_boundary_quiescent",
    "execution.disconnect_recovery_ready",
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
EDITOR_REVISION_REQUIRED_UI_ACTIONS = EDITOR_REQUIRED_UI_ACTIONS | frozenset(
    {
        "editor.rename_prepared_via_ui",
        "editor.edit_prepared_design_via_ui",
        "editor.regenerate_prepared_design_via_ui",
        "editor.refinalize_prepared_via_ui",
    }
)
MULTI_STOCK_REQUIRED_UI_ACTIONS = SMOKE_REQUIRED_UI_ACTIONS | frozenset(
    {"head.return_via_ui"}
)
SOFT_STOP_REQUIRED_UI_ACTIONS = SMOKE_REQUIRED_UI_ACTIONS | frozenset(
    {"array.request_soft_stop_via_ui", "array.resume_via_ui"}
)
AUTHORITATIVE_RELOAD_REQUIRED_UI_ACTIONS = SOFT_STOP_REQUIRED_UI_ACTIONS | frozenset({
    "experiment.load_authoritative_via_ui", "experiment.activate_authoritative_via_ui"})
DISCONNECT_REQUIRED_UI_ACTIONS = SMOKE_REQUIRED_UI_ACTIONS | frozenset(
    {"machine.disconnect_via_ui"}
)
POST_START_LOCK_REQUIRED_UI_ACTIONS = EDITOR_REQUIRED_UI_ACTIONS | frozenset(
    {
        "editor.inspect_active_lock_via_ui",
        "editor.reject_in_place_edit_via_ui",
        "editor.create_editable_copy_via_ui",
        "editor.edit_copy_via_ui",
        "editor.finalize_copy_via_ui",
    }
)
EDITOR_REQUIRED_SCREENSHOTS = frozenset(
    {"editor_opened", "generated", "finalized", "reloaded", "validated"}
)
EDITOR_REVISION_REQUIRED_SCREENSHOTS = frozenset(
    {
        "editor_opened",
        "generated",
        "initial_finalized",
        "rename_editor_opened",
        "renamed",
        "prepared_design_edited",
        "regenerated",
        "refinalized",
        "reloaded",
        "validated",
    }
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
STRESS_REQUIRED_SCREENSHOTS = frozenset(
    {"editor_opened", "generated", "ready", "printing", "mid_array", "completed"}
)
SOFT_STOP_REQUIRED_SCREENSHOTS = frozenset(
    {
        "editor_opened",
        "generated",
        "ready",
        "printing",
        "stop_requested",
        "stopped",
        "resumed",
        "completed",
    }
)
AUTHORITATIVE_RELOAD_REQUIRED_SCREENSHOTS = frozenset({
    "session_1_ready", "session_1_printing", "session_1_stop_requested",
    "session_1_stopped", "session_2_loaded", "session_2_activated",
    "session_2_resumed", "completed",
})
POST_START_LOCK_REQUIRED_SCREENSHOTS = frozenset({
    "editor_opened", "generated", "initial_finalized", "source_locked",
    "locked_editor_opened", "in_place_edit_rejected", "editable_copy_created",
    "copy_edited", "copy_finalized", "validated",
})
DISCONNECT_REQUIRED_SCREENSHOTS = frozenset(
    {
        "editor_opened", "generated", "ready", "printing",
        "disconnected", "recovery_ready",
    }
)

_COMMON_ACTIONS = frozenset(
    {"app.launch_simulated", "artifact.capture_milestone", "scenario.teardown"}
)
_AUTHORITATIVE_RELOAD_ACTIONS = frozenset({
    "app.close_simulated_session", "array.request_soft_stop_via_ui",
    "array.wait_for_state", "array.observe_stopped_quiescence",
    "experiment.load_authoritative_via_ui",
    "experiment.activate_authoritative_via_ui", "array.resume_via_ui",
})
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
    inject_ui_stall_ms: int = 0
    inject_after_completion: int = 48
    pi_preflight_path: Path | None = None
    pi_hardware_proof_path: Path | None = None

    def __post_init__(self) -> None:
        if self.scenario_id not in JOURNEY_DEFINITION_IDS:
            raise ValueError(f"unsupported composed journey: {self.scenario_id!r}")
        object.__setattr__(self, "output_root", Path(self.output_root).resolve())
        if self.inject_ui_stall_ms < 0:
            raise ValueError("inject_ui_stall_ms must be non-negative")
        if self.inject_after_completion < 1:
            raise ValueError("inject_after_completion must be positive")
        maximum_injection = {
            REGRESSION_WORKLOAD_ID: 96,
            STRESS_WORKLOAD_ID: 3840,
        }.get(self.scenario_id)
        if maximum_injection is not None and self.inject_after_completion > maximum_injection:
            workload_label = (
                "96-well workload"
                if self.scenario_id == REGRESSION_WORKLOAD_ID
                else "workload completion count"
            )
            raise ValueError(
                f"inject_after_completion cannot exceed the {workload_label}"
            )
        if (self.pi_preflight_path is None) != (
            self.pi_hardware_proof_path is None
        ):
            raise ValueError(
                "pi_preflight_path and pi_hardware_proof_path must be provided together"
            )
        for name in ("pi_preflight_path", "pi_hardware_proof_path"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, Path(value).resolve())


def _print_fixture(workload_id: str) -> tuple[dict[str, Any], Path]:
    from tools.virtual_workflows.scenarios import load_virtual_print_array_fixture

    path = Path(__file__).resolve().parent / "fixtures" / f"{workload_id}.json"
    return load_virtual_print_array_fixture(path, scenario_id=workload_id), path


def _smoke_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(SMOKE_WORKLOAD_ID)


def _regression_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(REGRESSION_WORKLOAD_ID)


def _regression_profile(runtime: JourneyRuntime) -> Any:
    from tools.virtual_workflows.regression_evidence import RegressionEvidenceProfile

    return RegressionEvidenceProfile(runtime)


def _multi_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(MULTI_STOCK_WORKLOAD_ID)


def _stress_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(STRESS_WORKLOAD_ID)


def _soft_stop_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(SOFT_STOP_WORKLOAD_ID)


def _authoritative_reload_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(AUTHORITATIVE_RELOAD_WORKLOAD_ID)


def _disconnect_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(DISCONNECT_WORKLOAD_ID)


def _editor_fixture() -> tuple[dict[str, Any], Path]:
    from tools.virtual_workflows.editor_scenarios import (
        load_editor_create_finalize_fixture,
    )

    path = Path(__file__).resolve().parent / "fixtures" / f"{EDITOR_WORKLOAD_ID}.json"
    return load_editor_create_finalize_fixture(path), path


def _editor_revision_fixture() -> tuple[dict[str, Any], Path]:
    from tools.virtual_workflows.editor_scenarios import (
        load_editor_prestart_rename_refinalize_fixture,
    )

    path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / f"{EDITOR_REVISION_WORKLOAD_ID}.json"
    )
    return load_editor_prestart_rename_refinalize_fixture(path), path


def _post_start_lock_fixture() -> tuple[dict[str, Any], Path]:
    from tools.virtual_workflows.editor_scenarios import (
        load_editor_post_start_lock_fixture,
    )

    path = Path(__file__).resolve().parent / "fixtures" / (
        f"{POST_START_LOCK_WORKLOAD_ID}.json"
    )
    return load_editor_post_start_lock_fixture(path), path


def _well_ids(fixture: Mapping[str, Any]) -> tuple[str, ...]:
    from tools.virtual_workflows.scenarios import fixture_well_ids

    return fixture_well_ids(dict(fixture))


def _stock_id(stock: Mapping[str, Any]) -> str:
    return f"{stock['factor_name']}_{float(stock['concentration']):.2f}_{stock['units']}"


def _fixture_stocks(fixture: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    if int(fixture["schema_version"]) == 1:
        return (
            {
                **dict(fixture["stock"]),
                "target_concentration": float(fixture["stock"]["concentration"]),
                "printer_head": dict(fixture["printer_head"]),
            },
        )
    return tuple(dict(stock) for stock in fixture["stocks"])


def _editor_specification(
    fixture: Mapping[str, Any], expected_wells: tuple[str, ...]
) -> dict[str, Any]:
    stocks = _fixture_stocks(fixture)
    volume_field = (
        "prepared_droplet_volume_nL"
        if int(fixture["schema_version"]) >= 2
        else "droplet_volume_nL"
    )
    printed_volume = sum(float(stock[volume_field]) for stock in stocks)
    reagents = [
        {
            "stock_label": stock["factor_name"],
            "group": "Additive",
            "printing_mode": stock["printing_mode"],
            "starting_concentration": 0.0,
            "targets": [float(stock["target_concentration"])],
            "units": stock["units"],
            "fixed_stock_concentration": float(stock["concentration"]),
            "droplet_volume_nL": float(stock["prepared_droplet_volume_nL"]),
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


def _editor_revision_initial_specification(
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    experiment = fixture["experiment"]
    reagent = fixture["reagent"]
    return {
        "experiment": {
            "name": experiment["initial_name"],
            "plate_name": experiment["plate_name"],
            "replicates": experiment["initial_replicates"],
            "expected_well_ids": list(experiment["initial_expected_well_ids"]),
            "printed_volume_nL": experiment["initial_printed_volume_nL"],
            "final_volume_nL": experiment["initial_final_volume_nL"],
            "printed_volume_tolerance_nL": experiment[
                "printed_volume_tolerance_nL"
            ],
            "randomize_assignments": experiment["randomize_assignments"],
            "allow_two_stock_solutions": experiment[
                "allow_two_stock_solutions"
            ],
            "fill_printing_mode": experiment["initial_fill_printing_mode"],
            "fill_droplet_volume_nL": experiment[
                "initial_fill_droplet_volume_nL"
            ],
        },
        "reagent": {
            "stock_label": reagent["stock_label"],
            "group": reagent["group"],
            "printing_mode": reagent["initial_printing_mode"],
            "starting_concentration": reagent["starting_concentration"],
            "targets": list(reagent["initial_targets"]),
            "units": reagent["units"],
            "fixed_stock_concentration": reagent["fixed_stock_concentration"],
            "droplet_volume_nL": reagent["initial_droplet_volume_nL"],
        },
    }


def _editor_revision_spec(
    fixture: Mapping[str, Any],
) -> PreparedEditorRevisionSpec:
    experiment = fixture["experiment"]
    reagent = fixture["reagent"]
    return PreparedEditorRevisionSpec(
        initial_name=experiment["initial_name"],
        renamed_name=experiment["renamed_name"],
        replicates=int(experiment["refinalized_replicates"]),
        well_ids=tuple(experiment["refinalized_expected_well_ids"]),
        printed_volume_nL=float(experiment["refinalized_printed_volume_nL"]),
        final_volume_nL=float(experiment["refinalized_final_volume_nL"]),
        fill_printing_mode=str(experiment["refinalized_fill_printing_mode"]),
        fill_droplet_volume_nL=float(
            experiment["refinalized_fill_droplet_volume_nL"]
        ),
        reagent_printing_mode=str(reagent["refinalized_printing_mode"]),
        reagent_targets=tuple(float(value) for value in reagent["refinalized_targets"]),
        reagent_droplet_volume_nL=float(
            reagent["refinalized_droplet_volume_nL"]
        ),
    )


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
    stock = _fixture_stocks(fixture)[0]
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
        staging_slot=int(fixture["simulation"].get("staging_slot", 0)),
        enable_pressure_regulation=True,
    )


def _soft_stop_spec(runtime: JourneyRuntime) -> SoftStopResumeSpec:
    lifecycle = runtime.fixture["lifecycle"]
    return SoftStopResumeSpec(
        request_after_completion_count=int(
            lifecycle["request_after_completion_count"]
        ),
        maximum_completion_catchup=int(lifecycle["maximum_completion_catchup"]),
        quiescence_observation_ms=int(lifecycle["quiescence_observation_ms"]),
        timeout_seconds=min(20.0, runtime.context.deadline.remaining_seconds()),
    )


def _disconnect_spec(runtime: JourneyRuntime) -> DisconnectFailClosedSpec:
    lifecycle = runtime.fixture["lifecycle"]
    return DisconnectFailClosedSpec(
        disconnect_after_completion_count=int(
            lifecycle["disconnect_after_completion_count"]
        ),
        expected_canceled_intent_count=int(
            lifecycle["expected_canceled_intent_count"]
        ),
        quiescence_observation_ms=int(lifecycle["quiescence_observation_ms"]),
        timeout_seconds=min(20.0, runtime.context.deadline.remaining_seconds()),
    )


def _multi_passes(runtime: JourneyRuntime) -> tuple[StockPassSpec, ...]:
    fixture = runtime.fixture
    well_count = len(_well_ids(fixture))
    stock_count = len(fixture["stocks"])
    compact = runtime.definition.registry_id == STRESS_WORKLOAD_ID
    from tools.sil.ejection_response import PulseAwareSyntheticEjectionModelV1
    response = PulseAwareSyntheticEjectionModelV1()
    result = []
    for index, stock in enumerate(fixture["stocks"]):
        head = stock["printer_head"]
        pulse_width_us = (
            STRESS_FIXED_CALIBRATION_PULSE_WIDTH_US
            if compact else int(head["print_pulse_width_us"])
        )
        result.append(
            StockPassSpec(
                stock_id=_stock_id(stock),
                printer_head_id=str(head["printer_head_id"]),
                pulse_width_us=pulse_width_us,
                pressure_psi=float(head["print_pressure_psi"]),
                frequency_hz=int(fixture["simulation"]["dispense_frequency_hz"]),
                initial_volume_uL=float(head["initial_volume_uL"]),
                expected_volume_nL=(
                    response.predict_volume_nl(str(stock["printing_mode"]), pulse_width_us)
                    if compact else float(stock["droplet_volume_nL"])
                ),
                expected_completion_count=well_count * (index + 1),
                expected_plan_state=("completed" if index == stock_count - 1 else "active"),
                ready_milestone=(
                    ("ready" if index == 0 else None) if compact
                    else ("stock_1_ready" if index == 0 else "stock_2_staged")
                ),
                printing_milestone=(
                    ("printing" if index == 0 else None) if compact
                    else ("stock_1_printing" if index == 0 else "stock_2_printing")
                ),
                completed_milestone=(
                    ("mid_array" if index == stock_count // 2 - 1 else
                     "completed" if index == stock_count - 1 else None)
                    if compact else ("stock_1_completed" if index == 0 else "completed")
                ),
                staging_slot=(
                    int(fixture["simulation"].get("staging_slot", 0))
                    if compact else None
                ),
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
                no_progress_timeout_seconds=120.0 if compact else None,
            )
        )
    return tuple(result)


def _smoke_body(runtime: JourneyRuntime) -> None:
    expected_wells = _well_ids(runtime.fixture)
    runtime.observations["expected_wells"] = expected_wells
    _connect_execution_signals(runtime, array_complete=True, machine_errors=False)
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    profile = None
    if runtime.definition.evidence_profile_factory is not None:
        profile = runtime.definition.evidence_profile_factory(runtime)
        runtime.observations["evidence_profile"] = profile
        runtime.add_assertion(profile.pi_assertion())
        runtime.add_assertion(real_application_assertion(runtime.context))
    runtime.run_steps(machine_startup_steps())
    if profile is None:
        runtime.add_assertion(machine_ready_assertion(runtime.context))
    run_editor_preparation(
        runtime,
        EditorPreparationSpec(
            _editor_specification(runtime.fixture, expected_wells),
            snapshot_finish=True,
        ),
    )
    if profile is None:
        runtime.add_assertion(
            prepared_execution_assertion(runtime.context, len(expected_wells))
        )
    else:
        profile.install()
        runtime.register_restorable("regression", profile)
    stock_pass = _smoke_pass(runtime)
    midpoint = runtime.definition.midpoint_completion_count

    def midpoint_phase(_runtime: JourneyRuntime, _spec: StockPassSpec) -> None:
        capture_completion_midpoint(runtime, int(midpoint))

    run_stock_passes(
        runtime,
        (stock_pass,),
        active_phase=midpoint_phase if midpoint is not None else None,
    )
    if profile is None:
        runtime.add_assertion(rack_head_assertion(runtime.context))
        runtime.add_assertion(
            calibration_assertion(
                runtime.context,
                expected_volume_nL=stock_pass.expected_volume_nL,
                expected_pulse_width_us=stock_pass.pulse_width_us,
                expected_pressure_psi=stock_pass.pressure_psi,
            )
        )
    else:
        runtime.restore_all()
        for assertion in profile.terminal_assertions():
            runtime.add_assertion(assertion)
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
    editor_action_start = len(runtime.context.action_results)
    run_editor_preparation(
        runtime,
        EditorPreparationSpec(fixture, use_harness_action_runner=True),
    )
    runtime.add_assertion(
        editor_create_finalize_assertion(
            runtime.context,
            action_start=editor_action_start,
            action_end=len(runtime.context.action_results),
        )
    )
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


def _editor_revision_body(runtime: JourneyRuntime) -> None:
    fixture = runtime.fixture
    experiment = fixture["experiment"]
    initial_wells = tuple(experiment["initial_expected_well_ids"])
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    runtime.add_assertion(real_application_assertion(runtime.context))
    run_editor_preparation(
        runtime,
        EditorPreparationSpec(
            _editor_revision_initial_specification(fixture),
            use_harness_action_runner=True,
        ),
    )
    capture_milestone(
        runtime.context,
        "initial_finalized",
        evidence={"experiment_name": experiment["initial_name"]},
    )
    initial = capture_editor_prepared_revision_snapshot(
        runtime.context,
        expected_well_ids=initial_wells,
    )
    runtime.observations["prepared_revision_initial"] = initial
    revision_action_start = len(runtime.context.action_results)
    try:
        run_prepared_editor_revision(runtime, _editor_revision_spec(fixture))
    except BaseException as exc:
        runtime.add_assertion(
            editor_prepared_revision_failure_assertion(exc),
            required=False,
        )
        raise
    revision_results, refinalized = editor_prepared_revision_assertions(
        runtime.context,
        fixture=fixture,
        initial_snapshot=initial,
        action_start=revision_action_start,
        action_end=len(runtime.context.action_results),
    )
    results = {result.assertion_id: result for result in revision_results}
    for assertion_id in EDITOR_REVISION_REQUIRED_ASSERTIONS[2:6]:
        runtime.add_assertion(results[assertion_id])
    runtime.observations["refinalized_bundle"] = refinalized
    loader_evidence = runtime.harness.run_action(
        "experiment.load_authoritative_via_ui",
        lambda: ExperimentLoaderDriver(runtime.context).load_prepared_design(
            Path(refinalized["experiment_dir"]),
            expected_name=experiment["renamed_name"],
            expected_plan_id=str(refinalized["plan_id"]),
            expected_plan_revision=int(refinalized["plan_revision"]),
        ),
    )["evidence"]
    capture_milestone(
        runtime.context,
        "reloaded",
        evidence={
            key: loader_evidence[key]
            for key in ("plan_state", "eligibility_status")
        },
    )
    reload_result, assignments = editor_prepared_reload_assertions(
        runtime.context,
        prepared_evidence=refinalized,
        loader_evidence=loader_evidence,
    )
    runtime.observations["reload_activation"] = dict(reload_result.evidence)
    for result in (reload_result, assignments, results["experiment.key_files_consistent"]):
        runtime.add_assertion(result)
    capture_milestone(
        runtime.context,
        "validated",
        evidence={
            "plan_state": reload_result.evidence.get("plan_state"),
            "eligibility_status": reload_result.evidence.get(
                "eligibility_status"
            ),
            "assertion_count": len(EDITOR_REVISION_REQUIRED_ASSERTIONS),
        },
    )


def _post_start_lock_body(runtime: JourneyRuntime) -> None:
    from tools.virtual_workflows.editor_scenarios import _initial_design_fixture

    context = runtime.context
    fixture = runtime.fixture
    experiment = fixture["experiment"]
    expected_wells = tuple(experiment["expected_well_ids"])
    runtime.add_assertion(simulation_identity_assertion(context))
    runtime.add_assertion(real_application_assertion(context))
    run_editor_preparation(
        runtime,
        EditorPreparationSpec(
            _initial_design_fixture(fixture),
            use_harness_action_runner=True,
        ),
    )
    capture_milestone(
        context,
        "initial_finalized",
        evidence={"experiment_name": experiment["source_name"]},
    )
    source_before_lock = capture_authoritative_bundle(context)
    boundary = run_post_start_lock_copy(
        runtime,
        PostStartLockCopySpec(
            source_dir=Path(source_before_lock.experiment_dir),
            source_name=experiment["source_name"],
            copy_name=experiment["copy_name"],
            copy_tolerance_nl=float(
                experiment["copy_printed_volume_tolerance_nL"]
            ),
        ),
        source_design=source_before_lock.design,
        expected_well_ids=expected_wells,
    )
    copy_snapshot = boundary["copy_snapshot"]
    prepared = copy_snapshot.prepared_evidence()
    loader_evidence = runtime.harness.run_action(
        "experiment.load_authoritative_via_ui",
        lambda: ExperimentLoaderDriver(context).load_prepared_design(
            Path(copy_snapshot.experiment_dir),
            expected_name=experiment["copy_name"],
            expected_plan_id=copy_snapshot.plan_id,
            expected_plan_revision=copy_snapshot.plan_revision,
        ),
    )["evidence"]
    reload_result, _assignments = editor_prepared_reload_assertions(
        context,
        prepared_evidence=prepared,
        loader_evidence=loader_evidence,
    )
    if reload_result.decision != "pass":
        raise RuntimeError(f"prepared copy reload failed: {reload_result.evidence}")
    boundary["copy_finalized"]["checks"]["prepared_reload_valid"] = True
    runtime.observations["post_start_edit_boundary"] = {
        "source_locked": boundary["source_locked"],
        "locked_editor": boundary["editor"]["lock_matrix"],
        "editable_copy_before_finalize": boundary["editor"][
            "copy_before_finalize"
        ],
        "editable_copy_after_finalize": boundary["copy_finalized"],
        "source_after_copy": boundary["source_after_copy"],
    }
    runtime.observations["prepared_copy_reload"] = dict(loader_evidence)
    for assertion in editor_post_start_lock_copy_assertions(
        source_locked=boundary["source_locked"],
        editor_boundary=boundary["editor"],
        copy_finalized=boundary["copy_finalized"],
        source_after_copy=boundary["source_after_copy"],
    ):
        runtime.add_assertion(assertion)
    capture_milestone(
        context,
        "validated",
        evidence={
            "source_plan_state": "ACTIVE",
            "copy_plan_state": copy_snapshot.plan_state.upper(),
            "assertion_count": len(POST_START_LOCK_REQUIRED_ASSERTIONS),
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
    profile = None
    if runtime.definition.evidence_profile_factory is not None:
        profile = runtime.definition.evidence_profile_factory(runtime)
        runtime.observations["evidence_profile"] = profile
        runtime.add_assertion(profile.pi_assertion())
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
    runtime.observations["expected_pulse_widths_us"] = tuple(
        spec.pulse_width_us for spec in pass_specs
    )
    runtime.observations["expected_volumes_nL"] = tuple(
        spec.expected_volume_nL for spec in pass_specs
    )
    runtime.run_steps((head_identity_step(pass_specs),))
    if profile is None:
        observer = ExecutionObserver(
            context,
            experiment_dir=Path(context.experiment_model.experiment_dir_path),
            completed_count=lambda: len(runtime.observations["completed_wells"]),
            pass_context=lambda: _current_pass_context(runtime),
        )
        runtime.register_restorable("execution", observer)
        observer.install()
        _install_starvation_observer(runtime)
    else:
        runtime.register_restorable("sustained_evidence", profile)
        profile.install()
    run_stock_passes(runtime, pass_specs, bind_identities=False)
    runtime.restore_all()
    if profile is None:
        snapshot = runtime.observations["execution_snapshot"]
        starvation_events = runtime.observations["starvation_events"]
    else:
        profile_snapshot = profile.snapshot()
        runtime.observations["sustained_evidence_snapshot"] = profile_snapshot
        snapshot = dict(profile_snapshot["observer"])
        runtime.observations["execution_snapshot"] = snapshot
        starvation_events = list(profile_snapshot["queue"]["unexpected_starvation_events"])
    for assertion in execution_lifecycle_assertions(
        context,
        expectation=ExecutionLifecycleExpectation(
            fixture=fixture,
            expected_well_ids=expected_wells,
            expected_stock_ids=expected_stock_ids,
            expected_pulse_widths_us=tuple(
                runtime.observations["expected_pulse_widths_us"]
            ),
            expected_volumes_nL=tuple(
                runtime.observations["expected_volumes_nL"]
            ),
        ),
        completed_wells=runtime.observations["completed_wells"],
        pass_boundaries=runtime.observations["pass_boundaries"],
        head_staging=runtime.observations["head_staging"],
        starvation_events=starvation_events,
        observer=snapshot,
    ):
        runtime.add_assertion(assertion)
    if profile is not None:
        for assertion in sustained_evidence_assertions(
            snapshot=profile_snapshot,
            expected_count=int(fixture["workload"]["completion_count"]),
        ):
            runtime.add_assertion(assertion)


def _soft_stop_body(runtime: JourneyRuntime) -> None:
    context = runtime.context
    fixture = runtime.fixture
    expected_wells = _well_ids(fixture)
    stock_ids = tuple(_stock_id(stock) for stock in fixture["stocks"])
    runtime.observations.update(
        {
            "expected_wells": expected_wells,
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
    plan = context.experiment_model.get_execution_plan_snapshot()
    expectation = SoftStopResumeExpectation(
        experiment_dir=Path(context.experiment_model.experiment_dir_path),
        plan_id=str(plan.plan_id),
        well_ids=expected_wells,
        stock_ids=stock_ids,
        target_dispenses_per_stock=int(
            fixture["workload"]["target_dispenses_per_stock_per_well"]
        ),
    )
    observer = ExecutionObserver(
        context,
        experiment_dir=expectation.experiment_dir,
        completed_count=lambda: len(runtime.observations["completed_wells"]),
        pass_context=lambda: _current_pass_context(runtime),
    )
    runtime.observations["execution_observer"] = observer
    runtime.register_restorable("execution", observer)
    observer.install()
    _install_starvation_observer(runtime)

    def validate_paused(_runtime: JourneyRuntime) -> None:
        paused_snapshot = runtime.observations["paused_execution_snapshot"]
        results = soft_stop_paused_assertions(
            context,
            expectation=expectation,
            request_evidence=runtime.observations["soft_stop_request"],
            completed_count=len(runtime.observations["completed_wells"]),
            intent_lifecycle=paused_snapshot["lifecycle"],
            quiescence=runtime.observations["stopped_quiescence"],
        )
        runtime.observations["paused_validation"] = dict(results[1].evidence)
        for result in results:
            runtime.add_assertion(result)

    run_stock_passes(
        runtime,
        (_smoke_pass(runtime),),
        active_phase=lambda _runtime, _spec: run_soft_stop_resume(
            runtime,
            _soft_stop_spec(runtime),
            paused_callback=validate_paused,
        ),
    )
    runtime.restore_all()
    terminal_snapshot = runtime.observations["execution_snapshot"]
    for result in soft_stop_terminal_assertions(
        context,
        expectation=expectation,
        completed_wells=runtime.observations["completed_wells"],
        array_complete_count=len(runtime.observations["array_completions"]),
        intent_lifecycle=terminal_snapshot["lifecycle"],
        paused_validation=runtime.observations["paused_validation"],
        quiescence=runtime.observations["stopped_quiescence"],
        starvation_events=runtime.observations["starvation_events"],
    ):
        runtime.add_assertion(result)


def _disconnect_body(runtime: JourneyRuntime) -> None:
    context, fixture = runtime.context, runtime.fixture
    expected_wells = _well_ids(fixture)
    runtime.observations.update(
        {
            "expected_wells": expected_wells,
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
    observer = ExecutionObserver(
        context,
        experiment_dir=Path(context.experiment_model.experiment_dir_path),
        completed_count=lambda: len(runtime.observations["completed_wells"]),
        pass_context=lambda: _current_pass_context(runtime),
    )
    runtime.observations["execution_observer"] = observer
    runtime.register_restorable("execution", observer)
    observer.install()

    interrupted_pass = replace(
        _smoke_pass(runtime),
        expected_plan_state="active",
        completed_milestone=None,
        await_terminal_boundary=False,
    )
    run_stock_passes(
        runtime,
        (interrupted_pass,),
        active_phase=lambda _runtime, _spec: run_disconnect_fail_closed_boundary(
            runtime, _disconnect_spec(runtime)
        ),
    )
    runtime.restore_all()
    snapshot = observer.snapshot()
    runtime.observations["execution_snapshot"] = snapshot
    lifecycle = dict(snapshot.get("lifecycle") or {})
    lifecycle_spec = _disconnect_spec(runtime)
    for result in disconnect_fail_closed_assertions(
        context,
        expectation=DisconnectFailClosedExpectation(
            completion_count=lifecycle_spec.disconnect_after_completion_count,
            canceled_intent_count=lifecycle_spec.expected_canceled_intent_count,
        ),
        request_evidence=runtime.observations["disconnect_request"],
        completed_wells=runtime.observations["completed_wells"],
        array_complete_count=len(runtime.observations.get("array_completions", [])),
        intent_lifecycle=lifecycle,
        quiescence=runtime.observations["disconnected_quiescence"],
        recovery=runtime.observations["disconnect_recovery"],
    ):
        runtime.add_assertion(result)


def _authoritative_reload_body(runtime: JourneyRuntime) -> None:
    context, fixture = runtime.context, runtime.fixture
    expected_wells = _well_ids(fixture)
    stock_ids = tuple(_stock_id(stock) for stock in fixture["stocks"])
    runtime.observations.update(
        {
            "expected_wells": expected_wells,
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
        EditorPreparationSpec(
            _editor_specification(fixture, expected_wells),
            capture_editor_milestones=False,
        ),
    )
    plan = context.experiment_model.get_execution_plan_snapshot()
    expectation = SoftStopResumeExpectation(
        experiment_dir=Path(context.experiment_model.experiment_dir_path),
        plan_id=str(plan.plan_id),
        well_ids=expected_wells,
        stock_ids=stock_ids,
        target_dispenses_per_stock=int(
            fixture["workload"]["target_dispenses_per_stock_per_well"]
        ),
    )
    first_observer = ExecutionObserver(
        context,
        experiment_dir=expectation.experiment_dir,
        completed_count=lambda: len(runtime.observations["completed_wells"]),
        pass_context=lambda: _current_pass_context(runtime),
    )
    runtime.observations["execution_observer"] = first_observer
    runtime.register_restorable("session_1_execution", first_observer)
    first_observer.install()
    _install_starvation_observer(runtime)

    stop_spec = replace(
        _soft_stop_spec(runtime),
        stop_requested_milestone="session_1_stop_requested",
        stopped_milestone="session_1_stopped",
        resumed_milestone="session_2_resumed",
    )

    def rotate_and_resume(_runtime: JourneyRuntime, spec: StockPassSpec) -> None:
        run_authoritative_reload_resume_boundary(
            runtime,
            stock_spec=spec,
            soft_stop_spec=stop_spec,
            expectation=expectation,
            expected_name=AUTHORITATIVE_RELOAD_WORKLOAD_ID,
            rebind_execution_signals=lambda: _connect_execution_signals(
                runtime, array_complete=True, machine_errors=True
            ),
            install_starvation_observer=lambda: _install_starvation_observer(
                runtime
            ),
        )

    first_pass = replace(
        _smoke_pass(runtime),
        ready_milestone="session_1_ready",
        printing_milestone="session_1_printing",
    )
    run_stock_passes(runtime, (first_pass,), active_phase=rotate_and_resume)
    runtime.restore_all()
    session_2 = runtime.observations["session_2_execution_snapshot"]
    combined = merge_session_lifecycles(
        (
            ("session_1", runtime.observations["session_1_lifecycle"]),
            ("session_2", session_2["lifecycle"]),
        )
    )
    runtime.observations.update(
        {"execution_snapshot": session_2, "combined_lifecycle": combined}
    )
    for result in authoritative_reload_terminal_assertions(
        context,
        expectation=expectation,
        completed_wells=runtime.observations["completed_wells"],
        array_complete_count=len(runtime.observations["array_completions"]),
        combined_lifecycle=combined,
        session_2_lifecycle=session_2["lifecycle"],
        session_1_completed_pairs=runtime.observations[
            "session_1_completed_pairs"
        ],
        paused_validation=runtime.observations["paused_validation"],
        quiescence=runtime.observations["stopped_quiescence"],
        starvation_events=runtime.observations["starvation_events"],
    ):
        runtime.add_assertion(result)


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


def _observer_persistence(observer: Mapping[str, Any]) -> dict[str, Any]:
    durable = dict(observer.get("durable_io_samples_ms") or {})

    def count(kind: str, phase: str) -> int:
        return len(durable.get(kind, {}).get(phase, []))

    return {
        "progress_snapshot": dict(observer.get("progress_snapshot") or {}),
        "authoritative_io": {
            "resume_save_fsync_count": count("fsync", "persistence.save_resume"),
            "resume_save_replace_count": count(
                "atomic_replace", "persistence.save_resume"
            ),
            "progress_write_fsync_count": count(
                "fsync", "persistence.write_progress"
            ),
            "progress_write_replace_count": count(
                "atomic_replace", "persistence.write_progress"
            ),
            "read_opens": dict(observer.get("authoritative_reads") or {}),
            "observer_restored": bool(observer.get("restored")),
        },
    }


def _regression_persistence_values(
    snapshot: Mapping[str, Any],
    *,
    decisions: Mapping[str, str],
    terminal: Mapping[str, Any],
) -> dict[str, Any]:
    observer = snapshot["observer"]
    lifecycle = observer["lifecycle"]
    observations = list(lifecycle.get("checkpoint_observations") or ())
    attachments = list(lifecycle.get("attachments") or ())
    transitions = list(lifecycle.get("terminal_transitions") or ())
    return {
        "assertion_decisions": dict(decisions),
        "terminal": dict(terminal),
        "intent_count": len(lifecycle.get("completions") or ()),
        "stock_well_completion_count": len(lifecycle.get("begins") or ()),
        "stock_pass_count": 1,
        "observed_completed_intent_count": len(
            lifecycle.get("completions") or ()
        ),
        "checkpoint_retained_intent_count": int(
            terminal.get("checkpoint_intent_count", 0)
        ),
        "checkpoint_pending_intent_count": int(
            terminal.get("checkpoint_intent_count", 0)
        ),
        "checkpoint_max_observed_intent_count": max(
            (
                int(item.get("retained_intent_count", 0))
                for item in observations
            ),
            default=0,
        ),
        "checkpoint_observations": observations,
        "intent_command_sequences": [
            item.get("command_seq32") for item in attachments
        ],
        "terminal_plan_state": terminal.get("plan_state"),
        "terminal_plan_revision": terminal.get("plan_revision"),
        "phase_timings": observer["phase_timings"],
        "terminal_transition": {
            "count": len(transitions),
            "records": transitions,
        },
        "authoritative_io": snapshot["authoritative_io"],
        "progress_snapshot": observer["progress_snapshot"],
    }


def _smoke_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    fixture = runtime.fixture
    expected = runtime.observations["expected_wells"]
    completed = runtime.observations["completed_wells"]
    decisions = _decisions(runtime)
    evidence = _assertion_evidence(runtime)
    required = runtime.definition.required_assertion_ids
    passed = all(decisions.get(item) == "pass" for item in required)
    stocks = _fixture_stocks(fixture)
    workload = {
        **_base_workload(runtime),
        "plate_name": fixture["plate"]["name"],
        "plate_rows": fixture["plate"]["rows"],
        "plate_columns": fixture["plate"]["columns"],
        "well_ids": list(expected),
        "stock_id": _stock_id(stocks[0]),
        "stock_ids": [_stock_id(stock) for stock in stocks],
        "stock_count": 1,
        "array_passes": 1,
        "target_dispenses_per_well": 1,
        "expected_completion_count": len(expected),
        "speed_multiplier": runtime.harness.config.speed_multiplier,
        "timeout_seconds": runtime.harness.config.timeout_seconds,
    }
    profile_snapshot = runtime.observations.get("regression_snapshot")
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
            "array_complete_count": len(runtime.observations.get("array_completions", ())),
            "cleanup_results": [dict(teardown)],
        },
        queue=(
            {"status": "measured", "values": profile_snapshot["queue"]}
            if profile_snapshot is not None
            else {
            "status": "measured",
            "values": {
                "queue_drained_at_terminal": bool(
                    evidence.get("execution.terminal_bundle_valid", {}).get(
                        "queue_drained"
                    )
                )
            },
        }),
        persistence=(
            {
                "status": "measured" if passed else "partial",
                "values": _regression_persistence_values(
                    profile_snapshot,
                    decisions=decisions,
                    terminal=evidence.get(
                        "execution.terminal_bundle_valid", {}
                    ),
                ),
            }
            if profile_snapshot is not None
            else {
            "status": "measured" if passed else "partial",
            "values": {
                "assertion_decisions": decisions,
                "terminal": evidence.get("execution.terminal_bundle_valid", {}),
            },
        }),
        responsiveness=(
            {"status": "measured", "values": profile_snapshot["responsiveness"]}
            if profile_snapshot is not None
            else {"status": "not_applicable", "values": {}}
        ),
        resources=(
            profile_snapshot["resources"]
            if profile_snapshot is not None
            else {"status": "not_applicable", "values": {}}
        ),
        limitations=(
            "The simulator verifies the application-facing contract, not firmware framing or ACK behavior.",
            "No physical motion, collision safety, pressure response, camera analysis, balance behavior, or droplet quality is modeled.",
            "Session-specific plan, printer-head, timestamp, and calibration identities are recorded but are not expected to be byte-identical across replay.",
        ),
    )


def _editor_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    return build_editor_lifecycle_payload(
        runtime,
        teardown,
        create_finalize_report_spec(
            runtime,
            base_workload=_base_workload(runtime),
            required_assertion_ids=EDITOR_REQUIRED_ASSERTIONS,
        ),
    )


def _editor_revision_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    return build_editor_lifecycle_payload(
        runtime,
        teardown,
        prepared_revision_report_spec(
            runtime,
            base_workload=_base_workload(runtime),
            required_assertion_ids=EDITOR_REVISION_REQUIRED_ASSERTIONS,
        ),
    )


def _post_start_lock_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    experiment = runtime.fixture["experiment"]
    workload = runtime.fixture["workload"]
    return build_editor_lifecycle_payload(
        runtime,
        teardown,
        EditorLifecycleReportSpec(
            workload={
                **_base_workload(runtime),
                **workload,
                "operation_count": workload["expected_editor_finalization_operations"],
                "experiment_name": experiment["source_name"],
                "copy_experiment_name": experiment["copy_name"],
                "plate_name": experiment["plate_name"],
                "expected_reaction_count": experiment["replicates"],
                "well_ids": list(experiment["expected_well_ids"]),
                "speed_multiplier": runtime.harness.config.speed_multiplier,
                "timeout_seconds": runtime.harness.config.timeout_seconds,
            },
            required_assertion_ids=POST_START_LOCK_REQUIRED_ASSERTIONS,
            persistence_values={
                "post_start_edit_boundary": dict(
                    runtime.observations.get("post_start_edit_boundary") or {}
                ),
                "reload_activation": dict(
                    runtime.observations.get("prepared_copy_reload") or {}
                ),
            },
            limitations=(
                "The zero-progress authoritative activation and printing-start lock are direct Model actions, not UI coverage or a print command.",
                "The scenario validates the editor lifecycle without connecting the simulated machine or printing.",
                "The simulator does not validate firmware, protocol framing, motion, pressure, cameras, balance behavior, or droplet quality.",
                "Generated plan IDs, timestamps, durations, paths, and identity-bearing hashes are not expected to be byte-identical across replay.",
            ),
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
        decisions.get(item) == "pass" for item in runtime.definition.required_assertion_ids
    )
    stock_count = len(fixture["stocks"])
    expected_count = int(fixture["workload"]["completion_count"])
    multi = evidence.get("execution.multi_stock_head_exchange", {})
    observer = dict(observations.get("execution_snapshot") or {})
    observer_persistence = _observer_persistence(observer)
    boundaries = observations.get("pass_boundaries", [])
    profile = dict(observations.get("sustained_evidence_snapshot") or {})
    starvation = (
        profile.get("queue", {}).get("unexpected_starvation_events", [])
        if profile else observations.get("starvation_events", [])
    )
    sustained = evidence.get("ui.sustained_responsiveness_acceptable", {})
    resource_evidence = evidence.get("resources.metrics_present", {})
    warning_reasons = list(sustained.get("warning_reasons") or [])
    growth = dict(resource_evidence.get("growth_assessment") or {})
    if growth.get("decision") == "warning":
        warning_reasons.append("rss_growth_over_100_mib_and_1_25_ratio")
    return ComposedReportPayload(
        workload={
            **_base_workload(runtime),
            "plate_name": fixture["plate"]["name"],
            "plate_rows": fixture["plate"]["rows"],
            "plate_columns": fixture["plate"]["columns"],
            "well_ids": list(expected),
            "stock_count": stock_count,
            "array_passes": stock_count,
            "target_dispenses_per_well": 1,
            "expected_completion_count": expected_count,
            "speed_multiplier": runtime.harness.config.speed_multiplier,
            "timeout_seconds": runtime.harness.config.timeout_seconds,
        },
        workflow_status="measured" if passed else "partial",
        workflow_values={
            "expected_well_count": len(expected),
            "completed_well_count": len(set(completed)),
            "expected_stock_well_completion_count": expected_count,
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
                **observer_persistence,
            },
        },
        responsiveness=(
            {"status": "measured", "values": dict(profile.get("responsiveness") or {})}
            if profile else {"status": "not_applicable", "values": {}}
        ),
        resources=(
            dict(profile.get("resources") or {"status": "not_available", "values": {}})
            if profile else {"status": "not_applicable", "values": {}}
        ),
        classification={
            "status": "warning" if warning_reasons else "pass",
            "reasons": warning_reasons,
        } if profile else None,
        limitations=(
            "The multi-stock lifecycle uses an in-process simulator and normal Qt controls; it does not validate physical head handling or output.",
            "The simulator does not validate firmware, protocol framing, motion, pressure response, cameras, balance behavior, or droplet quality.",
            "Generated plan IDs, timestamps, durations, paths, and calibration identities are not expected to be byte-identical across replay.",
        ),
    )


def _soft_stop_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    fixture = runtime.fixture
    observed = runtime.observations
    expected, completed = observed["expected_wells"], observed["completed_wells"]
    decisions = _decisions(runtime)
    evidence = _assertion_evidence(runtime)
    observer = dict(observed.get("execution_snapshot") or {})
    lifecycle = dict(observer.get("lifecycle") or {})
    request = observed.get("soft_stop_request", {})
    paused = observed.get("paused_validation", {})
    quiescence = observed.get("stopped_quiescence", {})
    terminal = evidence.get("execution.terminal_bundle_valid", {})
    passed = all(
        decisions.get(item) == "pass" for item in SOFT_STOP_REQUIRED_ASSERTIONS
    )


def _disconnect_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    observed = runtime.observations
    expected, completed = observed["expected_wells"], observed["completed_wells"]
    decisions = _decisions(runtime)
    snapshot = dict(observed.get("execution_snapshot") or {})
    lifecycle = dict(snapshot.get("lifecycle") or {})
    passed = all(
        decisions.get(item) == "pass" for item in DISCONNECT_REQUIRED_ASSERTIONS
    )
    status = "measured" if passed else "partial"
    return ComposedReportPayload(
        workload=_single_stock_workload(runtime),
        workflow_status=status,
        workflow_values={
            "expected_well_count": len(expected),
            "completed_well_count": len(completed),
            "expected_stock_well_completion_count": len(expected),
            "completed_stock_well_count": len(completed),
            "completed_well_ids": list(completed),
            "well_update_count": len(completed),
            "array_states": list(runtime.context.array_states),
            "array_complete_count": len(observed.get("array_completions", [])),
            "expected_outcome": "disconnect_fail_closed",
            "cleanup_results": [dict(teardown)],
        },
        queue={
            "status": status,
            "values": {
                "queue_drained_at_terminal": bool(
                    runtime.context.machine.check_if_all_completed()
                ),
                "simulator_connected_at_terminal": bool(
                    runtime.context.machine.state.connected
                ),
            },
        },
        persistence={
            "status": status,
            "values": {
                "assertion_decisions": decisions,
                "disconnect_fail_closed": {
                    "request": dict(observed.get("disconnect_request") or {}),
                    "quiescence": dict(
                        observed.get("disconnected_quiescence") or {}
                    ),
                    "recovery": dict(observed.get("disconnect_recovery") or {}),
                    "intent_reconciliation": {
                        "begin_count": len(lifecycle.get("begins") or []),
                        "completion_count": len(
                            lifecycle.get("completions") or []
                        ),
                        "discard_batches": list(
                            lifecycle.get("discard_batches") or []
                        ),
                    },
                },
                **_observer_persistence(snapshot),
            },
        },
        limitations=(
            "The disconnect lifecycle validates only the in-process simulated machine boundary and normal Qt controls.",
            "It does not validate serial framing, ACK/status loss, MCU reset, firmware recovery, physical motion, pressure response, or hardware output.",
            "Only confirmed simulated queue cancellation permits canceled intent discard; physical or unconfirmed disconnects remain ambiguous.",
        ),
    )
    status = "measured" if passed else "partial"
    intent_reconciliation = {
        "completed_count": terminal.get("intent_count"),
        "discarded_count": terminal.get("discarded_intent_count"),
        "begin_count": terminal.get("begin_intent_count"),
        "discard_batch_count": terminal.get("discard_batch_count"),
    }
    return ComposedReportPayload(
        workload={
            **_single_stock_workload(runtime),
        },
        workflow_status=status,
        workflow_values={"expected_well_count": len(expected), "completed_well_count": len(completed), "expected_stock_well_completion_count": len(expected), "completed_stock_well_count": len(completed), "completed_well_ids": list(completed), "well_update_count": len(completed), "array_states": list(runtime.context.array_states), "array_complete_count": len(observed.get("array_completions", [])), "cleanup_results": [dict(teardown)]},
        queue={"status": status, "values": {"unexpected_starvation_count": len(observed.get("starvation_events", [])), "queue_drained_at_terminal": decisions.get("execution.terminal_bundle_valid") == "pass"}},
        persistence={"status": status, "values": {"assertion_decisions": decisions, "soft_stop_resume": {"request": request, "stopped_checkpoint": paused, "quiescence": quiescence, "intent_reconciliation": intent_reconciliation}, "paused_boundary": paused, "quiescence": quiescence, "intent_durability": evidence.get("execution.intent_durability_exact", {}), "terminal": terminal, "terminal_plan_state": terminal.get("terminal_plan_state"), "stock_well_completion_count": terminal.get("stock_well_completion_count"), "intent_count": len(lifecycle.get("completions", [])), "discard_batch_count": len(lifecycle.get("discard_batches", [])), **_observer_persistence(observer)}},
        limitations=(
            "The soft-stop lifecycle uses an in-process simulator and normal Qt controls; it does not validate physical stopping distance.",
            "The simulator does not validate firmware, protocol framing, motion, pressure response, cameras, balance behavior, or droplet quality.",
            "Generated identities, timestamps, durations, paths, and calibration identities are not expected to be byte-identical across replay.",
        ),
    )


def _authoritative_reload_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    observed = runtime.observations
    expected, completed = observed["expected_wells"], observed["completed_wells"]
    decisions = _decisions(runtime)
    evidence = _assertion_evidence(runtime)
    passed = all(decisions.get(item) == "pass" for item in AUTHORITATIVE_RELOAD_REQUIRED_ASSERTIONS)
    status = "measured" if passed else "partial"
    return ComposedReportPayload(
        workload=_single_stock_workload(runtime),
        workflow_status=status,
        workflow_values={
            "expected_well_count": len(expected),
            "completed_well_count": len(completed),
            "expected_stock_well_completion_count": len(expected),
            "completed_stock_well_count": len(completed),
            "completed_well_ids": list(completed),
            "well_update_count": len(completed),
            "array_states": list(runtime.context.array_states),
            "array_complete_count": len(observed.get("array_completions", [])),
            "application_sessions": list(map(dict, runtime.harness.application_sessions)),
            "cleanup_results": [dict(teardown)],
        },
        queue={
            "status": status,
            "values": {
                "unexpected_starvation_count": len(observed.get("starvation_events", [])),
                "queue_drained_at_terminal": decisions.get("execution.terminal_bundle_valid") == "pass",
            },
        },
        persistence={"status": status, "values": _authoritative_reload_persistence(
            runtime, decisions=decisions, evidence=evidence
        )},
        limitations=(
            "The two fresh application compositions share one in-process QApplication and retained SIL root; this is not an OS-process restart test.",
            "The simulator does not validate firmware, protocol framing, motion, pressure response, cameras, balance behavior, or droplet quality.",
            "Generated identities, timestamps, durations, paths, and identity-bearing hashes are not expected to be byte-identical across replay.",
        ),
    )


def _single_stock_workload(runtime: JourneyRuntime) -> dict[str, Any]:
    fixture, expected = runtime.fixture, runtime.observations["expected_wells"]
    return {
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


def _authoritative_reload_persistence(
    runtime: JourneyRuntime, *, decisions: Mapping[str, str],
    evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    observed = runtime.observations
    boundaries = observed.get("reload_boundaries", {})
    terminal = evidence.get("execution.terminal_bundle_valid", {})
    return {
        "assertion_decisions": dict(decisions),
        "authoritative_reload_resume": {
            "session_1_paused": observed.get("paused_validation", {}),
            "session_1_cleanup": observed.get("session_1_cleanup", {}),
            "between_sessions": observed.get("between_sessions", {}),
            "session_2_loaded": boundaries.get("loaded", {}),
            "session_2_activation": boundaries.get("activated", {}),
            "resume_reconciliation": evidence.get("execution.reload_resume_exactly_once", {}),
            "terminal": {
                "plan_state": terminal.get("terminal_plan_state"),
                "completion_count": terminal.get("stock_well_completion_count"),
                "checks": terminal.get("checks", {}),
            },
        },
        "intent_durability": evidence.get("execution.intent_durability_exact", {}),
        **_observer_persistence(dict(observed.get("execution_snapshot") or {})),
    }


def _cleanup_artifact(runtime: JourneyRuntime, teardown: Mapping[str, Any]) -> Any:
    return cleanup_assertion(teardown)


def _editor_artifact(runtime: JourneyRuntime, teardown: Mapping[str, Any]) -> Any:
    return editor_artifacts_cleanup_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(EDITOR_REQUIRED_SCREENSHOTS),
        teardown=teardown,
    )


def _editor_revision_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return editor_artifacts_cleanup_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(EDITOR_REVISION_REQUIRED_SCREENSHOTS),
        teardown=teardown,
    )


def _post_start_lock_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return editor_artifacts_cleanup_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(POST_START_LOCK_REQUIRED_SCREENSHOTS),
        teardown=teardown,
    )


def _multi_artifact(runtime: JourneyRuntime, teardown: Mapping[str, Any]) -> Any:
    return multi_stock_artifacts_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(runtime.definition.required_screenshots),
        teardown=teardown,
    )


def _soft_stop_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return multi_stock_artifacts_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(SOFT_STOP_REQUIRED_SCREENSHOTS),
        teardown=teardown,
    )


def _disconnect_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return multi_stock_artifacts_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(DISCONNECT_REQUIRED_SCREENSHOTS),
        teardown=teardown,
    )


def _authoritative_reload_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return multi_stock_artifacts_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(AUTHORITATIVE_RELOAD_REQUIRED_SCREENSHOTS),
        teardown=teardown,
    )


def _regression_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return multi_stock_artifacts_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(runtime.definition.required_screenshots),
        teardown=teardown,
    )


def _smoke_summary(report: Mapping[str, Any], runtime: JourneyRuntime) -> str:
    values = report["metrics"]["workflow"]["values"]
    return (
        f"Composed one-stock {len(runtime.observations['expected_wells'])}-well journey\n"
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


def _editor_revision_summary(
    report: Mapping[str, Any], runtime: JourneyRuntime
) -> str:
    passed = sum(
        row["decision"] == "pass" for row in runtime.harness.assertion_results
    )
    return (
        "Milestone 7 composed prepared editor rename/refinalize/reload\n"
        f"Status: {report['classification']['status']}\n"
        f"Assertions: {passed} / {len(EDITOR_REVISION_REQUIRED_ASSERTIONS)}\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _post_start_lock_summary(report: Mapping[str, Any], runtime: JourneyRuntime) -> str:
    passed = sum(row["decision"] == "pass"
                 for row in runtime.harness.assertion_results)
    return (
        "Milestone 7 composed post-start lock/editable-copy lifecycle\n"
        f"Status: {report['classification']['status']}\n"
        f"Assertions: {passed} / {len(POST_START_LOCK_REQUIRED_ASSERTIONS)}\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _multi_summary(report: Mapping[str, Any], runtime: JourneyRuntime) -> str:
    expected = int(runtime.fixture["workload"]["completion_count"])
    return (
        f"Milestone 7 composed {len(runtime.fixture['stocks'])}-stock lifecycle\n"
        f"Status: {report['classification']['status']}\n"
        f"Completions: {len(runtime.observations['completed_wells'])} / {expected}\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _soft_stop_summary(report: Mapping[str, Any], runtime: JourneyRuntime) -> str:
    return (
        "Milestone 7 composed 24-well soft-stop/resume lifecycle\n"
        f"Status: {report['classification']['status']}\n"
        f"Completions: {len(runtime.observations['completed_wells'])} / 24\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _disconnect_summary(report: Mapping[str, Any], runtime: JourneyRuntime) -> str:
    return (
        "Milestone 7 composed mid-array disconnect fail-closed lifecycle\n"
        f"Status: {report['classification']['status']}\n"
        f"Durable completions before disconnect: {len(runtime.observations['completed_wells'])} / 24\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _authoritative_reload_summary(
    report: Mapping[str, Any], runtime: JourneyRuntime
) -> str:
    return (
        "Milestone 7 composed authoritative reload/resume lifecycle\n"
        f"Status: {report['classification']['status']}\n"
        f"Completions: {len(runtime.observations['completed_wells'])} / 24\n"
        f"Application sessions: {len(runtime.harness.application_sessions)}\n"
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
REGRESSION_DEFINITION = JourneyDefinition(
    registry_id=REGRESSION_WORKLOAD_ID,
    scenario_name=SMOKE_SCENARIO_NAME,
    scenario_version=SMOKE_SCENARIO_VERSION,
    workload_id=REGRESSION_WORKLOAD_ID,
    required_action_ids=_COMMON_ACTIONS | _EDITOR_ACTIONS | _PRINT_ACTIONS,
    required_ui_action_ids=SMOKE_REQUIRED_UI_ACTIONS,
    required_assertion_ids=REGRESSION_REQUIRED_ASSERTIONS,
    required_screenshots=frozenset(
        {"editor_opened", "generated", "ready", "printing", "mid_array", "completed"}
    ),
    fixture_loader=_regression_fixture,
    body=_smoke_body,
    artifact_assertion=_regression_artifact,
    payload_builder=_smoke_payload,
    summary_builder=_smoke_summary,
    evidence_profile_factory=_regression_profile,
    midpoint_completion_count=48,
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
EDITOR_REVISION_DEFINITION = JourneyDefinition(
    registry_id=EDITOR_REVISION_WORKLOAD_ID,
    scenario_name=EDITOR_REVISION_SCENARIO_NAME,
    scenario_version=EDITOR_REVISION_SCENARIO_VERSION,
    workload_id=EDITOR_REVISION_WORKLOAD_ID,
    required_action_ids=(
        _COMMON_ACTIONS
        | _EDITOR_ACTIONS
        | frozenset(
            {
                "editor.rename_prepared_via_ui",
                "editor.edit_prepared_design_via_ui",
                "editor.regenerate_prepared_design_via_ui",
                "editor.refinalize_prepared_via_ui",
                "experiment.load_authoritative_via_ui",
            }
        )
    ),
    required_ui_action_ids=EDITOR_REVISION_REQUIRED_UI_ACTIONS,
    required_assertion_ids=EDITOR_REVISION_REQUIRED_ASSERTIONS,
    required_screenshots=EDITOR_REVISION_REQUIRED_SCREENSHOTS,
    fixture_loader=_editor_revision_fixture,
    body=_editor_revision_body,
    artifact_assertion=_editor_revision_artifact,
    payload_builder=_editor_revision_payload,
    summary_builder=_editor_revision_summary,
)
POST_START_LOCK_DEFINITION = JourneyDefinition(
    registry_id=POST_START_LOCK_WORKLOAD_ID,
    scenario_name="experiment_editor_post_start_lock",
    scenario_version="1",
    workload_id=POST_START_LOCK_WORKLOAD_ID,
    required_action_ids=(
        _COMMON_ACTIONS
        | _EDITOR_ACTIONS
        | frozenset(
            {
                "experiment.activate_authoritative",
                "execution.lock_for_printing",
                "editor.inspect_active_lock_via_ui",
                "editor.reject_in_place_edit_via_ui",
                "editor.create_editable_copy_via_ui",
                "editor.edit_copy_via_ui",
                "editor.finalize_copy_via_ui",
                "experiment.load_authoritative_via_ui",
            }
        )
    ),
    required_ui_action_ids=POST_START_LOCK_REQUIRED_UI_ACTIONS,
    required_assertion_ids=POST_START_LOCK_REQUIRED_ASSERTIONS,
    required_screenshots=POST_START_LOCK_REQUIRED_SCREENSHOTS,
    fixture_loader=_post_start_lock_fixture,
    body=_post_start_lock_body,
    artifact_assertion=_post_start_lock_artifact,
    payload_builder=_post_start_lock_payload,
    summary_builder=_post_start_lock_summary,
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
STRESS_DEFINITION = JourneyDefinition(
    registry_id=STRESS_WORKLOAD_ID,
    scenario_name=SMOKE_SCENARIO_NAME,
    scenario_version=SMOKE_SCENARIO_VERSION,
    workload_id=STRESS_WORKLOAD_ID,
    required_action_ids=(
        _COMMON_ACTIONS | _EDITOR_ACTIONS | _PRINT_ACTIONS
        | frozenset({"head.bind_identity", "head.return_via_ui", "validation.stock_pass_boundary"})
    ),
    required_ui_action_ids=MULTI_STOCK_REQUIRED_UI_ACTIONS,
    required_assertion_ids=STRESS_REQUIRED_ASSERTIONS,
    required_screenshots=STRESS_REQUIRED_SCREENSHOTS,
    fixture_loader=_stress_fixture,
    body=_multi_body,
    artifact_assertion=_multi_artifact,
    payload_builder=_multi_payload,
    summary_builder=_multi_summary,
    evidence_profile_factory=_regression_profile,
    midpoint_completion_count=1920,
)
SOFT_STOP_DEFINITION = JourneyDefinition(
    registry_id=SOFT_STOP_WORKLOAD_ID,
    scenario_name=SOFT_STOP_SCENARIO_NAME,
    scenario_version=SOFT_STOP_SCENARIO_VERSION,
    workload_id=SOFT_STOP_WORKLOAD_ID,
    required_action_ids=(
        _COMMON_ACTIONS
        | _EDITOR_ACTIONS
        | _PRINT_ACTIONS
        | frozenset(
            {
                "array.request_soft_stop_via_ui",
                "array.wait_for_state",
                "array.observe_stopped_quiescence",
                "array.resume_via_ui",
            }
        )
    ),
    required_ui_action_ids=SOFT_STOP_REQUIRED_UI_ACTIONS,
    required_assertion_ids=SOFT_STOP_REQUIRED_ASSERTIONS,
    required_screenshots=SOFT_STOP_REQUIRED_SCREENSHOTS,
    fixture_loader=_soft_stop_fixture,
    body=_soft_stop_body,
    artifact_assertion=_soft_stop_artifact,
    payload_builder=_soft_stop_payload,
    summary_builder=_soft_stop_summary,
)
AUTHORITATIVE_RELOAD_DEFINITION = JourneyDefinition(
    registry_id=AUTHORITATIVE_RELOAD_WORKLOAD_ID,
    scenario_name=AUTHORITATIVE_RELOAD_SCENARIO_NAME,
    scenario_version=AUTHORITATIVE_RELOAD_SCENARIO_VERSION,
    workload_id=AUTHORITATIVE_RELOAD_WORKLOAD_ID,
    required_action_ids=(
        _COMMON_ACTIONS | _EDITOR_ACTIONS | _PRINT_ACTIONS
        | _AUTHORITATIVE_RELOAD_ACTIONS
    ),
    required_ui_action_ids=AUTHORITATIVE_RELOAD_REQUIRED_UI_ACTIONS,
    required_assertion_ids=AUTHORITATIVE_RELOAD_REQUIRED_ASSERTIONS,
    required_screenshots=AUTHORITATIVE_RELOAD_REQUIRED_SCREENSHOTS,
    fixture_loader=_authoritative_reload_fixture,
    body=_authoritative_reload_body,
    artifact_assertion=_authoritative_reload_artifact,
    payload_builder=_authoritative_reload_payload,
    summary_builder=_authoritative_reload_summary,
)
DISCONNECT_DEFINITION = JourneyDefinition(
    registry_id=DISCONNECT_WORKLOAD_ID,
    scenario_name=DISCONNECT_SCENARIO_NAME,
    scenario_version="1",
    workload_id=DISCONNECT_WORKLOAD_ID,
    required_action_ids=(
        _COMMON_ACTIONS
        | _EDITOR_ACTIONS
        | (_PRINT_ACTIONS - frozenset({"array.wait_for_completions"}))
        | frozenset(
            {
                "machine.disconnect_via_ui",
                "array.observe_disconnected_quiescence",
            }
        )
    ),
    required_ui_action_ids=DISCONNECT_REQUIRED_UI_ACTIONS,
    required_assertion_ids=DISCONNECT_REQUIRED_ASSERTIONS,
    required_screenshots=DISCONNECT_REQUIRED_SCREENSHOTS,
    fixture_loader=_disconnect_fixture,
    body=_disconnect_body,
    artifact_assertion=_disconnect_artifact,
    payload_builder=_disconnect_payload,
    summary_builder=_disconnect_summary,
)

JOURNEY_DEFINITIONS = {
    definition.registry_id: definition
    for definition in (
        SMOKE_DEFINITION,
        REGRESSION_DEFINITION,
        EDITOR_DEFINITION,
        EDITOR_REVISION_DEFINITION,
        POST_START_LOCK_DEFINITION,
        MULTI_STOCK_DEFINITION,
        STRESS_DEFINITION,
        SOFT_STOP_DEFINITION,
        AUTHORITATIVE_RELOAD_DEFINITION,
        DISCONNECT_DEFINITION,
    )
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


def run_soft_stop_resume_24_journey(config: JourneyRunConfig) -> dict[str, Any]:
    return JourneyExecutor().run(SOFT_STOP_DEFINITION, config)


def run_disconnect_fail_closed_24_journey(
    config: JourneyRunConfig,
) -> dict[str, Any]:
    return JourneyExecutor().run(DISCONNECT_DEFINITION, config)


__all__ = [
    "EDITOR_WORKLOAD_ID",
    "DISCONNECT_REQUIRED_ASSERTIONS",
    "DISCONNECT_REQUIRED_UI_ACTIONS",
    "DISCONNECT_WORKLOAD_ID",
    "AUTHORITATIVE_RELOAD_REQUIRED_ASSERTIONS",
    "AUTHORITATIVE_RELOAD_REQUIRED_UI_ACTIONS",
    "AUTHORITATIVE_RELOAD_WORKLOAD_ID",
    "JOURNEY_DEFINITIONS",
    "JourneyRunConfig",
    "MULTI_STOCK_REQUIRED_ASSERTIONS",
    "MULTI_STOCK_REQUIRED_UI_ACTIONS",
    "MULTI_STOCK_WORKLOAD_ID",
    "STRESS_REQUIRED_ASSERTIONS",
    "STRESS_REQUIRED_SCREENSHOTS",
    "STRESS_WORKLOAD_ID",
    "POST_START_LOCK_REQUIRED_ASSERTIONS",
    "POST_START_LOCK_REQUIRED_SCREENSHOTS",
    "POST_START_LOCK_REQUIRED_UI_ACTIONS",
    "POST_START_LOCK_WORKLOAD_ID",
    "SMOKE_WORKLOAD_ID",
    "SOFT_STOP_REQUIRED_ASSERTIONS",
    "SOFT_STOP_REQUIRED_UI_ACTIONS",
    "SOFT_STOP_WORKLOAD_ID",
    "get_journey_definition",
    "run_composed_journey",
    "run_editor_create_finalize_journey",
    "run_disconnect_fail_closed_24_journey",
    "run_multi_stock_24x2_journey",
    "run_soft_stop_resume_24_journey",
    "run_virtual_print_array_24_journey",
]
