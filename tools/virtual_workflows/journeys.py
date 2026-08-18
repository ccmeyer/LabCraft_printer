"""Concise typed definitions for migrated SIL journeys."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from tools.virtual_workflows.actions import (
    capture_execution_preflight_boundary,
    capture_milestone,
    drive_execution_preflight_safeguard,
)
from tools.virtual_workflows.persistence_safeguards import (
    PERSISTENCE_SAFEGUARD_MATRIX_ID,
    get_persistence_safeguard_case,
    persistence_fixture_inventory,
    prepare_persistence_fault,
)
from tools.virtual_workflows.assertions import (
    AssertionResult,
    ExecutionLifecycleExpectation,
    calibration_assertion,
    cleanup_assertion,
    completed_terminal_reload_assertion,
    calibration_apply_fail_closed_assertion,
    calibrated_zero_progress_assertion,
    clean_joined_session_rotation_assertion,
    joined_remaining_calibrations_assertion,
    joined_terminal_execution_assertion,
    capture_editor_prepared_revision_snapshot,
    editor_artifacts_cleanup_assertion,
    editor_create_finalize_assertion,
    editor_create_rejected_assertion,
    editor_post_start_lock_copy_assertions,
    editor_prepared_bundle_assertions,
    editor_prepared_revision_assertions,
    editor_prepared_revision_failure_assertion,
    editor_prepared_reload_assertions,
    editor_sequence_exploration_assertions,
    experiment_design_case_oracle_assertion,
    experiment_finalization_rejected_no_mutation_assertion,
    experiment_prepared_runtime_reconstructed_assertion,
    machine_ready_assertion,
    matrix_case_assertions,
    m13_compact_prepared_assertion,
    m13_illegal_recovery_sequence_assertion,
    m13_legal_sequence_assertion,
    m13_rejection_continuity_assertion,
    mixed_mode_lifecycle_assertions,
    multi_stock_artifacts_assertion,
    multi_stock_prepared_assertion,
    execution_lifecycle_assertions,
    prepared_execution_assertion,
    post_completion_diagnostics_assertion,
    rack_head_assertion,
    real_application_assertion,
    randomized_joined_design_assertion,
    optimizer_360_design_assertion,
    simulation_identity_assertion,
    sustained_evidence_assertions,
    SoftStopResumeExpectation,
    DisconnectFailClosedExpectation,
    authoritative_reload_terminal_assertions,
    disconnect_fail_closed_assertions,
    dispense_counts_reconciled_assertion,
    soft_stop_paused_assertions,
    soft_stop_terminal_assertions,
    same_session_completed_projection_assertion,
    terminal_execution_assertion,
    two_reagent_isolation_assertion,
)
from tools.virtual_workflows.composition import (
    JourneyDefinition,
    JourneyExecutor,
    JourneyRuntime,
    replay_command,
)
from tools.virtual_workflows.execution_observer import ExecutionObserver
from tools.virtual_workflows.dispense_counts import capture_count_snapshot
from tools.virtual_workflows.authoritative_evidence import (
    capture_authoritative_bundle,
    merge_session_lifecycles,
)
from tools.virtual_workflows.editor_reporting import (
    EditorLifecycleReportSpec,
    build_editor_lifecycle_payload,
    create_finalize_report_spec,
    experiment_design_report_spec,
    prepared_revision_report_spec,
)
from tools.virtual_workflows.journey_phases import (
    CalibrationOnlySpec,
    PrecalibratedStockPassSpec,
    EditorPreparationSpec,
    PreparedEditorRevisionSpec,
    PostStartLockCopySpec,
    StockPassSpec,
    ManualRefuelCheckSpec,
    SoftStopResumeSpec,
    DisconnectFailClosedSpec,
    capture_completion_midpoint,
    head_identity_step,
    machine_startup_steps,
    run_editor_preparation,
    run_prepared_editor_revision,
    run_prepared_editor_sequence,
    run_post_start_lock_copy,
    run_stock_passes,
    run_stock_calibration_only,
    normalized_stock_pass_steps,
    run_soft_stop_resume,
    run_disconnect_fail_closed_boundary,
    run_authoritative_reload_resume_boundary,
    run_clean_authoritative_session_rotation_boundary,
    run_precalibrated_stock_passes,
)
from tools.virtual_workflows.page_drivers import (
    CalibrationDialogDriver,
    ExperimentLoaderDriver,
    MachineControlsDriver,
    RackDriver,
)
from tools.virtual_workflows.report import ComposedReportPayload
from tools.virtual_workflows.joined_interaction_cases import (
    DESIGN_A_STOCK_ID,
    JOINED_INTERACTION_CASE,
    JOINED_INTERACTION_CASE_ID,
    JOINED_INTERACTION_FIXTURE_PATH,
    joined_fixture_sha256,
)
from tools.virtual_workflows.optimizer_360_cases import (
    EXPECTED_ACHIEVED_REACTION_MULTISET_SHA256,
    EXPECTED_ASSIGNMENT_SHA256,
    EXPECTED_COUNT_ORACLE_SHA256,
    EXPECTED_FIXTURE_SHA256,
    EXPECTED_REACTION_MULTISET_SHA256,
    OPTIMIZER_360_CASE,
    OPTIMIZER_360_CASE_ID,
    OPTIMIZER_360_FIXTURE_PATH,
    RANGE_A_STOCK_ID,
)
from tools.virtual_workflows.m13_interaction_cases import (
    COMPACT_CASE as M13_COMPACT_CASE,
    REFINALIZED_COMPACT_CASE as M13_REFINALIZED_COMPACT_CASE,
    fixture_projection as m13_fixture_projection,
)
from tools.virtual_workflows.safeguards import (
    ExpectedSafeguardOutcome,
    capture_safeguard_boundary,
    safeguard_rejection_no_mutation_no_dispatch_assertion,
)
from tools.virtual_workflows.editor_safeguards import get_editor_safeguard_case
from tools.virtual_workflows.execution_preflight_safeguards import (
    get_execution_preflight_case,
)
from tools.virtual_workflows.calibration_storage_journeys import (
    AUTHORITATIVE_FUNCTIONAL_DEFINITION as CALIBRATION_STORAGE_AUTHORITATIVE_FUNCTIONAL_DEFINITION,
    AUTHORITATIVE_PERFORMANCE_DEFINITION as CALIBRATION_STORAGE_AUTHORITATIVE_PERFORMANCE_DEFINITION,
    FUNCTIONAL_DEFINITION as CALIBRATION_STORAGE_FUNCTIONAL_DEFINITION,
    PERFORMANCE_DEFINITION as CALIBRATION_STORAGE_PERFORMANCE_DEFINITION,
    PRIMARY_READER_FUNCTIONAL_DEFINITION as CALIBRATION_STORAGE_PRIMARY_READER_FUNCTIONAL_DEFINITION,
    PRIMARY_READER_PERFORMANCE_DEFINITION as CALIBRATION_STORAGE_PRIMARY_READER_PERFORMANCE_DEFINITION,
    NEW_STORE_ONLY_FUNCTIONAL_DEFINITION as CALIBRATION_STORAGE_NEW_STORE_ONLY_FUNCTIONAL_DEFINITION,
    SECONDARY_READER_FUNCTIONAL_DEFINITION as CALIBRATION_STORAGE_SECONDARY_READER_FUNCTIONAL_DEFINITION,
    SECONDARY_READER_PERFORMANCE_DEFINITION as CALIBRATION_STORAGE_SECONDARY_READER_PERFORMANCE_DEFINITION,
    SHADOW_FUNCTIONAL_DEFINITION as CALIBRATION_STORAGE_SHADOW_FUNCTIONAL_DEFINITION,
    SHADOW_PERFORMANCE_DEFINITION as CALIBRATION_STORAGE_SHADOW_PERFORMANCE_DEFINITION,
)
from tools.virtual_workflows.calibration_history_conversion_journey import (
    DEFINITION as CALIBRATION_STORAGE_HISTORICAL_CONVERSION_DEFINITION,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_WORKLOAD_ID = "virtual_print_array_24_v1"
REGRESSION_WORKLOAD_ID = "virtual_print_array_96_v1"
SMOKE_SCENARIO_NAME = "virtual_print_array"
SMOKE_SCENARIO_VERSION = "1"
EDITOR_WORKLOAD_ID = "experiment_editor_create_finalize_v1"
EDITOR_SCENARIO_NAME = "experiment_editor_create_finalize"
EDITOR_SCENARIO_VERSION = "1"
LEGACY_READ_ONLY_WORKLOAD_ID = "legacy_experiment_read_only_v1"
LEGACY_READ_ONLY_SCENARIO_NAME = "legacy_experiment_read_only"
LEGACY_READ_ONLY_SCENARIO_VERSION = "1"
EDITOR_REVISION_WORKLOAD_ID = "experiment_editor_prestart_rename_refinalize_v1"
EDITOR_REVISION_SCENARIO_NAME = "experiment_editor_prestart_rename_refinalize"
EDITOR_REVISION_SCENARIO_VERSION = "1"
MULTI_STOCK_WORKLOAD_ID = "print_array_multi_stock_24x2_v1"
MULTI_STOCK_SCENARIO_NAME = "print_array_multi_stock_head_exchange"
MULTI_STOCK_SCENARIO_VERSION = "1"
MIXED_MODE_WORKLOAD_ID = "print_array_mixed_mode_24x2_v1"
MIXED_MODE_SCENARIO_NAME = "print_array_mixed_droplet_stream"
MIXED_MODE_SCENARIO_VERSION = "1"
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
MATRIX_SCENARIO_NAME = "parameterized_calibration_matrix_case"
EXPERIMENT_DESIGN_MATRIX_SCENARIO_NAME = (
    "parameterized_experiment_design_matrix_case"
)
EDITOR_SAFEGUARD_MATRIX_SCENARIO_NAME = "parameterized_editor_safeguard_case"
EXECUTION_PREFLIGHT_MATRIX_SCENARIO_NAME = (
    "parameterized_execution_preflight_safeguard_case"
)
PERSISTENCE_SAFEGUARD_MATRIX_SCENARIO_NAME = (
    "parameterized_persistence_safeguard_case"
)
EXPLORATION_WORKLOAD_ID = "editor_prepared_guard_v1"
EXPLORATION_SCENARIO_NAME = "seeded_editor_prepared_guard"
M13_EXPLORATION_WORKLOAD_ID = "design_calibration_lifecycle_v1"
M13_EXPLORATION_SCENARIO_NAME = "seeded_design_calibration_lifecycle"
RANDOMIZED_CALIBRATION_WORKLOAD_ID = JOINED_INTERACTION_CASE_ID
RANDOMIZED_CALIBRATION_SCENARIO_NAME = "randomized_calibration_reload_execution"
RANDOMIZED_CALIBRATION_SCENARIO_VERSION = "1"
OPTIMIZER_360_WORKLOAD_ID = OPTIMIZER_360_CASE_ID
OPTIMIZER_360_SCENARIO_NAME = (
    OPTIMIZER_360_CASE.identity.scenario_name
)
OPTIMIZER_360_SCENARIO_VERSION = "1"

MATRIX_CASE_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "execution.matrix_case_parameters_applied",
    "execution.matrix_case_outcome_valid",
    "artifacts.required_present",
)

SMOKE_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "machine.normal_ui_ready",
    "experiment.prepared_bundle_valid",
    "execution.rack_head_associated",
    "execution.applied_calibration_valid",
    "execution.terminal_bundle_valid",
    "calibration.post_completion_diagnostics_available",
    "execution.same_session_completed_projection_exact",
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
LEGACY_READ_ONLY_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "experiment.legacy_read_only_exact",
    "analysis.legacy_plate_reader_ready",
    "experiment.legacy_editable_copy_fresh",
    "experiment.legacy_source_unchanged",
    "artifacts.required_present",
)
LEGACY_READ_ONLY_REQUIRED_UI_ACTIONS = frozenset(
    {
        "experiment.inspect_legacy_via_ui",
        "analysis.open_plate_reader_via_ui",
        "editor.create_editable_copy_via_ui",
    }
)
LEGACY_READ_ONLY_REQUIRED_SCREENSHOTS = frozenset(
    {
        "legacy_editor",
        "legacy_main",
        "legacy_plate_reader",
        "legacy_editable_copy",
    }
)
EXPERIMENT_DESIGN_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "experiment.editor_create_finalize",
    "experiment.design_case_oracle_exact",
    "experiment.prepared_runtime_reconstructed_exact",
    "artifacts.required_present",
)
JOINED_CALIBRATED_CHECKPOINT_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "experiment.editor_create_finalize",
    "experiment.randomized_joined_design_exact",
    "execution.calibrated_zero_progress_exact",
    "ui.fresh_application_session_constructed",
    "execution.first_session_teardown_clean",
    "execution.authoritative_reload_valid",
    "execution.authoritative_runtime_rehydrated",
    "execution.clean_session_rotation_exact",
    "execution.remaining_calibrations_exact",
    "execution.completed_terminal_reload_exact",
    "execution.randomized_calibration_terminal_exact",
)
RANDOMIZED_CALIBRATION_REQUIRED_ASSERTIONS = (
    *JOINED_CALIBRATED_CHECKPOINT_REQUIRED_ASSERTIONS,
    "artifacts.required_present",
)
OPTIMIZER_360_FIRST_CALIBRATION_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "experiment.editor_create_finalize",
    "experiment.optimizer_360_design_exact",
    "execution.calibrated_zero_progress_exact",
)
OPTIMIZER_360_CALIBRATION_CHAIN_REQUIRED_ASSERTIONS = (
    *OPTIMIZER_360_FIRST_CALIBRATION_REQUIRED_ASSERTIONS,
    "ui.fresh_application_session_constructed",
    "execution.first_session_teardown_clean",
    "execution.authoritative_reload_valid",
    "execution.authoritative_runtime_rehydrated",
    "execution.clean_session_rotation_exact",
    "execution.remaining_calibrations_exact",
)
OPTIMIZER_360_LIFECYCLE_REQUIRED_ASSERTIONS = (
    *OPTIMIZER_360_CALIBRATION_CHAIN_REQUIRED_ASSERTIONS,
    "execution.completed_terminal_reload_exact",
    "execution.randomized_calibration_terminal_exact",
)
OPTIMIZER_360_REQUIRED_ASSERTIONS = (
    *OPTIMIZER_360_LIFECYCLE_REQUIRED_ASSERTIONS,
    "artifacts.required_present",
)
EXPERIMENT_DESIGN_REJECTED_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "experiment.editor_create_rejected",
    "experiment.finalization_rejected_no_mutation",
    "artifacts.required_present",
)
EDITOR_SAFEGUARD_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "safeguard_rejection_no_mutation_no_dispatch",
    "artifacts.required_present",
)
EXECUTION_PREFLIGHT_SAFEGUARD_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "safeguard_rejection_no_mutation_no_dispatch",
    "artifacts.required_present",
)
PERSISTENCE_SAFEGUARD_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "safeguard_rejection_no_mutation_no_dispatch",
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
EXPLORATION_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "exploration.sequence_plan_applied",
    "exploration.expected_rejection_safe",
    "exploration.recovery_terminal_valid",
    "artifacts.required_present",
)
M13_LEGAL_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "experiment.editor_create_finalize",
    "experiment.design_case_oracle_exact",
    "exploration.m13_compact_prepared_exact",
    "execution.calibrated_zero_progress_exact",
    "ui.fresh_application_session_constructed",
    "execution.first_session_teardown_clean",
    "execution.authoritative_reload_valid",
    "execution.authoritative_runtime_rehydrated",
    "execution.clean_session_rotation_exact",
    "execution.remaining_calibrations_exact",
    "execution.completed_terminal_reload_exact",
    "execution.randomized_calibration_terminal_exact",
    "exploration.m13_legal_sequence_exact",
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
MIXED_MODE_REQUIRED_ASSERTIONS = (
    *MULTI_STOCK_REQUIRED_ASSERTIONS[:-1],
    "execution.dispense_counts_reconciled",
    "execution.mixed_mode_calibrations_valid",
    "execution.stream_manual_refuel_passed",
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
EXPERIMENT_DESIGN_REQUIRED_UI_ACTIONS = EDITOR_REQUIRED_UI_ACTIONS
JOINED_CALIBRATED_CHECKPOINT_REQUIRED_UI_ACTIONS = frozenset(
    {
        "editor.open_via_ui",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        "editor.optimize_generate_via_ui",
        "editor.finish_via_ui",
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
        "experiment.load_authoritative_via_ui",
        "experiment.activate_authoritative_via_ui",
        "head.return_via_ui",
        "array.start_via_ui",
        "experiment.inspect_completed_via_ui",
    }
)
RANDOMIZED_CALIBRATION_REQUIRED_UI_ACTIONS = (
    JOINED_CALIBRATED_CHECKPOINT_REQUIRED_UI_ACTIONS
)
EXPERIMENT_DESIGN_REJECTED_REQUIRED_UI_ACTIONS = frozenset(
    {
        "editor.open_via_ui",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        "editor.finish_via_ui",
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
MIXED_MODE_REQUIRED_UI_ACTIONS = MULTI_STOCK_REQUIRED_UI_ACTIONS | frozenset(
    {"manual_refuel.complete_check_via_ui"}
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
EXPERIMENT_DESIGN_REQUIRED_SCREENSHOTS = frozenset(
    {
        "editor_opened",
        "generated",
        "finalized",
        "prepared_reloaded",
        "validated",
    }
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
EXPLORATION_REQUIRED_SCREENSHOTS = frozenset(
    {"editor_opened", "generated", "initial_finalized", "reloaded", "validated"}
)
M13_LEGAL_REQUIRED_SCREENSHOTS = frozenset(
    {"prepared", "fresh_loaded", "fresh_activated", "terminal_reloaded"}
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
MIXED_MODE_REQUIRED_SCREENSHOTS = frozenset(
    {
        "editor_opened",
        "generated",
        "droplet_ready",
        "droplet_printing",
        "droplet_completed",
        "manual_refuel_passed",
        "stream_ready",
        "stream_printing",
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
RANDOMIZED_CALIBRATION_REQUIRED_SCREENSHOTS = frozenset(
    JOINED_INTERACTION_CASE.qualification.required_screenshots
)
OPTIMIZER_360_REQUIRED_SCREENSHOTS = frozenset(
    OPTIMIZER_360_CASE.qualification.required_screenshots
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
_RANDOMIZED_CALIBRATION_ACTIONS = (
    _COMMON_ACTIONS
    | RANDOMIZED_CALIBRATION_REQUIRED_UI_ACTIONS
    | frozenset(
        {
            "app.close_simulated_session",
            "head.bind_identity",
            "array.wait_for_completions",
            "validation.stock_pass_boundary",
        }
    )
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
        if self.scenario_id not in JOURNEY_DEFINITION_IDS | {
            M13_EXPLORATION_WORKLOAD_ID
        }:
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


def _exploration_fixture() -> tuple[dict[str, Any], Path]:
    from tools.virtual_workflows.exploration import build_sequence_fixture

    return build_sequence_fixture(EXPLORATION_WORKLOAD_ID, "seed_1_legal")


def _smoke_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(SMOKE_WORKLOAD_ID)


def _regression_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(REGRESSION_WORKLOAD_ID)


def _regression_profile(runtime: JourneyRuntime) -> Any:
    from tools.virtual_workflows.regression_evidence import RegressionEvidenceProfile

    return RegressionEvidenceProfile(runtime)


def _multi_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(MULTI_STOCK_WORKLOAD_ID)


def _mixed_mode_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(MIXED_MODE_WORKLOAD_ID)


def _stress_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(STRESS_WORKLOAD_ID)


def _soft_stop_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(SOFT_STOP_WORKLOAD_ID)


def _authoritative_reload_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(AUTHORITATIVE_RELOAD_WORKLOAD_ID)


def _disconnect_fixture() -> tuple[dict[str, Any], Path]:
    return _print_fixture(DISCONNECT_WORKLOAD_ID)


def _randomized_calibration_fixture() -> tuple[dict[str, Any], Path]:
    return (
        JOINED_INTERACTION_CASE.normalized(),
        JOINED_INTERACTION_FIXTURE_PATH,
    )


def _optimizer_360_fixture() -> tuple[dict[str, Any], Path]:
    return OPTIMIZER_360_CASE.normalized(), OPTIMIZER_360_FIXTURE_PATH


def _editor_fixture() -> tuple[dict[str, Any], Path]:
    from tools.virtual_workflows.editor_scenarios import (
        load_editor_create_finalize_fixture,
    )

    path = Path(__file__).resolve().parent / "fixtures" / f"{EDITOR_WORKLOAD_ID}.json"
    return load_editor_create_finalize_fixture(path), path


def _legacy_read_only_fixture() -> tuple[dict[str, Any], Path]:
    path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / f"{LEGACY_READ_ONLY_WORKLOAD_ID}.json"
    )
    return json.loads(path.read_text(encoding="utf-8")), path


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
    reagent_stocks = tuple(
        stock for stock in stocks if stock.get("stock_role") != "fill"
    )
    volume_field = (
        "prepared_droplet_volume_nL"
        if int(fixture["schema_version"]) >= 2
        else "droplet_volume_nL"
    )
    default_printed_volume = sum(
        float(stock[volume_field]) for stock in reagent_stocks
    )
    design_override = dict(
        fixture.get("lifecycle", {}).get("design") or {}
    )
    printed_volume = float(
        design_override.get("printed_volume_nL", default_printed_volume)
    )
    final_volume = float(
        design_override.get("final_volume_nL", printed_volume)
    )
    reagents = [
        {
            "stock_label": stock["factor_name"],
            "group": "Additive",
            "printing_mode": stock["printing_mode"],
            "starting_concentration": 0.0,
            "targets": [
                float(value) for value in stock.get(
                    "target_concentrations", [stock["target_concentration"]]
                )
            ],
            "units": stock["units"],
            "fixed_stock_concentration": float(stock["concentration"]),
            "droplet_volume_nL": float(stock["prepared_droplet_volume_nL"]),
        }
        for stock in reagent_stocks
    ]
    specification = {
        "experiment": {
            "name": fixture["fixture_id"],
            "plate_name": fixture["plate"]["name"],
            "replicates": int(
                design_override.get("replicates", len(expected_wells))
            ),
            "expected_reaction_count": int(
                design_override.get("expected_reaction_count", len(expected_wells))
            ),
            "expected_well_ids": list(expected_wells),
            "printed_volume_nL": printed_volume,
            "final_volume_nL": final_volume,
            "printed_volume_tolerance_nL": 0.0,
            "randomize_assignments": False,
            "allow_two_stock_solutions": False,
        },
    }
    for key in ("fill_printing_mode", "fill_droplet_volume_nL"):
        if key in design_override:
            specification["experiment"][key] = design_override[key]
    specification["reagent" if len(reagents) == 1 else "reagents"] = (
        reagents[0] if len(reagents) == 1 else reagents
    )
    return specification


def _prepared_target_dispenses(
    fixture: Mapping[str, Any],
) -> dict[Any, int] | None:
    oracle = dict(
        fixture.get("lifecycle", {}).get("dispense_count_oracle") or {}
    )
    if not oracle:
        return None
    if int(oracle.get("schema_version", 1)) == 2:
        rows: dict[tuple[str, str], int] = {}
        for group in oracle.get("count_groups") or ():
            for well_id in group.get("well_ids") or ():
                rows[(str(group["stock_id"]), str(well_id))] = int(
                    group["prepared_droplets"]
                )
        return rows
    return {
        str(oracle["stock_id"]): int(oracle["prepared_droplets_per_well"])
    }


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

    def record_completed_well(well_id) -> None:
        well_id = str(well_id)
        if well_id.strip().lower() == "all":
            return
        completed.append(well_id)

    context.model.well_plate.well_state_changed_signal.connect(
        record_completed_well
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
    matrix_case = fixture.get("lifecycle", {}).get("kind") == (
        "parameterized_calibration_matrix_case"
    )
    mixed_mode = (
        runtime.definition.registry_id == MIXED_MODE_WORKLOAD_ID and not matrix_case
    )
    manual_contract = dict(
        fixture.get("lifecycle", {}).get("manual_refuel_check") or {}
    )
    matrix_contracts = dict(
        fixture.get("lifecycle", {}).get("manual_refuel_checks") or {}
    )
    blocked_seen = False
    oracle = dict(fixture.get("lifecycle", {}).get("dispense_count_oracle") or {})
    matrix_terminal = str(
        fixture.get("lifecycle", {}).get("case", {}).get("expected_terminal")
        or ""
    )
    completion_by_stock: dict[str, int] = {}
    if int(oracle.get("schema_version", 1)) == 2:
        for group in oracle.get("count_groups") or ():
            stock_id = str(group.get("stock_id") or "")
            if int(group.get("requantized_droplets", 0) or 0) > 0:
                completion_by_stock[stock_id] = completion_by_stock.get(stock_id, 0) + len(
                    group.get("well_ids") or ()
                )
    cumulative_completion_count = 0
    for index, stock in enumerate(fixture["stocks"]):
        head = stock["printer_head"]
        stock_key = str(stock.get("matrix_stock_key") or "")
        matrix_manual = dict(matrix_contracts.get(stock_key) or {})
        matrix_blocked = bool(
            matrix_manual and matrix_manual.get("status") != "passed"
        )
        calibration_rejected = matrix_terminal == "calibration_apply_rejected"
        if blocked_seen:
            break
        is_last_configured = index == stock_count - 1
        will_complete_case = (
            is_last_configured and not matrix_blocked and not calibration_rejected
        )
        applied_pulse_width_us = int(head["print_pulse_width_us"])
        pulse_width_us = (
            STRESS_FIXED_CALIBRATION_PULSE_WIDTH_US
            if compact else int(
                stock.get("staging_print_pulse_width_us", applied_pulse_width_us)
            )
        )
        stock_id = _stock_id(stock)
        cumulative_completion_count += completion_by_stock.get(
            stock_id, well_count
        )
        calibration_mode = str(
            stock.get("calibration_mode") or stock["printing_mode"]
        )
        result.append(
            StockPassSpec(
                stock_id=stock_id,
                printer_head_id=str(head["printer_head_id"]),
                pulse_width_us=pulse_width_us,
                pressure_psi=float(head["print_pressure_psi"]),
                frequency_hz=int(fixture["simulation"]["dispense_frequency_hz"]),
                initial_volume_uL=float(head["initial_volume_uL"]),
                expected_volume_nL=(
                    response.predict_volume_nl(str(stock["printing_mode"]), pulse_width_us)
                    if compact else float(stock["droplet_volume_nL"])
                ),
                expected_completion_count=(
                    cumulative_completion_count
                    if completion_by_stock else well_count * (index + 1)
                ),
                expected_plan_state=("completed" if will_complete_case else "active"),
                ready_milestone=(
                    None if calibration_rejected else
                    f"pass_{index + 1}_ready" if matrix_case else
                    ("ready" if index == 0 else None) if compact
                    else ("stock_1_ready" if index == 0 else "stock_2_staged")
                ),
                printing_milestone=(
                    (
                        None
                        if matrix_blocked or calibration_rejected
                        else f"pass_{index + 1}_printing"
                    )
                    if matrix_case else
                    ("printing" if index == 0 else None) if compact
                    else ("stock_1_printing" if index == 0 else "stock_2_printing")
                ),
                completed_milestone=(
                    (
                        None if matrix_blocked or calibration_rejected else
                        "completed" if will_complete_case else f"pass_{index + 1}_completed"
                    ) if matrix_case else
                    ("mid_array" if index == stock_count // 2 - 1 else
                     "completed" if index == stock_count - 1 else None)
                    if compact else ("stock_1_completed" if index == 0 else "completed")
                ),
                staging_slot=(
                    int(fixture["simulation"].get("staging_slot", 0))
                    if compact else None
                ),
                start_dialog_titles=(
                    ("Start Print Array",)
                    if matrix_blocked else
                    ("Start Print Array", "Evaporation Plate Dock Check")
                    if index == 0
                    else ("Start Print Array",)
                ),
                bind_identity=True,
                enable_pressure_regulation=index == 0,
                return_head=True,
                detailed_evidence=True,
                include_frequency_evidence=False,
                no_progress_timeout_seconds=120.0 if compact else None,
                calibration_mode=calibration_mode,
                mode_switch_choice=(
                    "yes"
                    if calibration_mode != str(stock["printing_mode"])
                    else None
                ),
                apply_success_title=(
                    "Applied (Fill)"
                    if stock.get("stock_role") == "fill" else "Applied"
                ),
                require_refuel_regulation=(
                    str(stock["printing_mode"]) == "stream"
                ),
                expected_applied_pulse_width_us=applied_pulse_width_us,
                calibration_print_profile_id=(
                    str((stock.get("calibration_print_profile") or {}).get("id"))
                    if stock.get("calibration_print_profile") else None
                ),
                refuel_pulse_width_us=(
                    int(head["refuel_pulse_width_us"])
                    if "refuel_pulse_width_us" in head else None
                ),
                refuel_pressure_psi=(
                    float(head["refuel_pressure_psi"])
                    if "refuel_pressure_psi" in head else None
                ),
                manual_refuel_check=(
                    ManualRefuelCheckSpec(
                        trial_count=int(manual_contract["trial_count"]),
                        trial_droplet_count=int(
                            manual_contract["trial_droplet_count"]
                        ),
                        outcome=str(manual_contract["status"]),
                        operator_judgment=str(
                            manual_contract["operator_judgment"]
                        ),
                    )
                    if mixed_mode and str(stock["printing_mode"]) == "stream"
                    else (
                        ManualRefuelCheckSpec(
                            trial_count=int(matrix_manual["trial_count"]),
                            trial_droplet_count=int(
                                matrix_manual["trial_droplet_count"]
                            ),
                            outcome=str(matrix_manual["status"]),
                            operator_judgment=str(
                                matrix_manual["operator_judgment"]
                            ),
                            milestone=(
                                f"pass_{index + 1}_refuel_passed"
                                if matrix_manual.get("status") == "passed"
                                else None
                            ),
                        )
                        if matrix_case and matrix_manual else None
                    )
                ),
                expected_start_outcome=(
                    "calibration_apply_rejected"
                    if calibration_rejected
                    else "manual_refuel_cancelled"
                    if matrix_blocked
                    else "running"
                ),
                validate_pass_boundary=not matrix_blocked and not calibration_rejected,
                rejected_calibration_mode=(
                    str((stock.get("rejected_calibration") or {}).get("target_mode"))
                    if calibration_rejected else None
                ),
                rejected_calibration_pulse_width_us=(
                    int((stock.get("rejected_calibration") or {}).get("pulse_width_us"))
                    if calibration_rejected else None
                ),
                rejected_calibration_profile_id=(
                    str((stock.get("rejected_calibration") or {}).get("synthetic_profile_id"))
                    if calibration_rejected else None
                ),
                rejected_calibration_title=(
                    str((stock.get("rejected_calibration") or {}).get("expected_title"))
                    if calibration_rejected else None
                ),
                rejected_calibration_message_fragment=(
                    str((stock.get("rejected_calibration") or {}).get("expected_message_fragment"))
                    if calibration_rejected else None
                ),
                capture_isolation_boundary=bool(
                    stock.get("isolation_calibration")
                ),
            )
        )
        blocked_seen = blocked_seen or matrix_blocked or calibration_rejected
    if mixed_mode:
        result[0] = replace(
            result[0],
            ready_milestone="droplet_ready",
            printing_milestone="droplet_printing",
            completed_milestone="droplet_completed",
        )
        result[1] = replace(
            result[1],
            ready_milestone="stream_ready",
            printing_milestone="stream_printing",
            completed_milestone="completed",
        )
    return tuple(result)


def _run_post_completion_diagnostics(
    runtime: JourneyRuntime,
    stock_pass: StockPassSpec,
) -> None:
    """Exercise printer-head diagnostics after the terminal live boundary."""

    context = runtime.context
    machine = MachineControlsDriver(context)
    before = capture_authoritative_bundle(context)
    launch = machine.inspect_calibration_launch_state()
    from ExecutionCalibrationStore import load_execution_calibrations

    calibration_records = load_execution_calibrations(
        context.experiment_model.execution_calibrations_file_path
    ).records.values()
    applied_record = next(
        record
        for record in calibration_records
        if str(record.stock_id) == stock_pass.stock_id
    )
    expected_printer_head_id = str(applied_record.printer_head_id)
    dialog_state: dict[str, Any] = {}

    def open_calibration() -> Mapping[str, Any]:
        dialog = machine.open_calibration_dialog()
        dialog_state["dialog"] = dialog
        return {
            **launch,
            "window_title": str(dialog.windowTitle() or ""),
            "dialog_visible": bool(dialog.isVisible()),
        }

    runtime.harness.run_action(
        "calibration.open_via_ui",
        open_calibration,
    )
    calibration = CalibrationDialogDriver(
        context.app,
        dialog_state["dialog"],
        timeout_seconds=min(20.0, context.deadline.remaining_seconds()),
    )
    generated: dict[str, Any] = {}

    def generate() -> Mapping[str, Any]:
        result = calibration.generate_from_tab(stock_pass.calibration_mode)
        generated.update(result)
        return {
            "stock_id": stock_pass.stock_id,
            "result_fingerprint": result.get("synthetic_result_fingerprint"),
            "printing_mode": result.get("printing_mode"),
        }

    generated_evidence = runtime.harness.run_action(
        "calibration.generate_via_ui",
        generate,
    )["evidence"]
    preview: dict[str, Any] = {}

    def select_and_close() -> Mapping[str, Any]:
        selected = calibration.select_result(
            str(generated["synthetic_result_fingerprint"])
        )
        preview.update(
            json.loads(json.dumps(calibration.inspect_preview(), sort_keys=True))
        )
        calibration.close()
        return {
            "stock_id": stock_pass.stock_id,
            "result_fingerprint": selected.get(
                "synthetic_result_fingerprint"
            ),
            "dialog_visible_after": bool(
                dialog_state["dialog"].isVisible()
            ),
        }

    selected_evidence = runtime.harness.run_action(
        "calibration.select_via_ui",
        select_and_close,
    )["evidence"]
    after = capture_authoritative_bundle(context)
    plan = context.experiment_model.get_execution_plan_snapshot()
    read_only_getter = getattr(
        context.model, "is_read_only_experiment_view_active", None
    )
    boundary = {
        "plan_state": str(plan.state.value),
        "array_state": context.controller.get_array_run_state(),
        "queue_drained": bool(context.machine.check_if_all_completed()),
        "historical_read_only": bool(
            callable(read_only_getter) and read_only_getter()
        ),
        "dialog_visible_after": bool(dialog_state["dialog"].isVisible()),
        "unexpected_dialog_count": len(context.unexpected_dialogs),
        "error_count": len(context.errors),
    }
    assertion = post_completion_diagnostics_assertion(
        before=before,
        after=after,
        boundary=boundary,
        launch=launch,
        generated=generated_evidence,
        selected=selected_evidence,
        preview=preview,
        expected_stock_id=stock_pass.stock_id,
        expected_printer_head_id=expected_printer_head_id,
    )
    runtime.add_assertion(assertion)
    runtime.observations["post_completion_diagnostics"] = dict(
        assertion.evidence
    )


def _run_same_session_completed_projection(runtime: JourneyRuntime) -> None:
    """Display the just-completed execution read-only without rotating sessions."""

    context = runtime.context
    before = capture_authoritative_bundle(context)
    active_head = context.model.rack_model.get_gripper_printer_head()
    returned_head = None
    if active_head is not None:
        rack = RackDriver(context)
        unload_slots = [
            index
            for index, row in enumerate(context.view.rack_box.slot_widgets)
            if str(row[2].text() or "") == "Unload"
        ]
        if len(unload_slots) != 1:
            raise RuntimeError(
                "same-session completed projection requires exactly one "
                f"Unload control; observed {unload_slots}"
            )
        slot_index = unload_slots[0]
        returned_head = runtime.harness.run_action(
            "head.return_via_ui",
            lambda: (
                rack.unload(slot_index)
                or {
                    "slot": slot_index,
                    "stock_id": str(active_head.get_stock_id()),
                    "printer_head_id": str(active_head.printer_head_id),
                    "returned": True,
                }
            ),
        )["evidence"]
    driver = ExperimentLoaderDriver(context).inspect_same_session_completed_execution(
        expected_name=str(runtime.fixture.get("fixture_id") or ""),
        action_runner=runtime.harness.run_action,
    )
    driver["returned_head"] = dict(returned_head or {})
    after = capture_authoritative_bundle(context)
    assertion = same_session_completed_projection_assertion(
        before=before,
        after=after,
        driver=driver,
    )
    runtime.add_assertion(assertion)
    runtime.observations["same_session_completed_projection"] = dict(
        assertion.evidence
    )


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
    if profile is None:
        _run_post_completion_diagnostics(runtime, stock_pass)
        _run_same_session_completed_projection(runtime)


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


def _hash_legacy_fixture(directory: Path) -> dict[str, str]:
    source_names = {
        "experiment_design.json",
        "progress.json",
        "key.csv",
        "concentration_key.csv",
        "plate_reader_export.txt",
    }
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(directory.iterdir())
        if path.is_file() and path.name in source_names
    }


def _materialize_legacy_read_only_fixture(runtime: JourneyRuntime) -> tuple[Path, Path]:
    fixture = runtime.fixture
    directory = (
        Path(runtime.context.experiment_model.experiments_root)
        / fixture["experiment_name"]
    )
    directory.mkdir(parents=True, exist_ok=False)
    for name, payload in (
        ("experiment_design.json", fixture["experiment_design"]),
        ("progress.json", fixture["progress"]),
    ):
        (directory / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (directory / "key.csv").write_text(
        fixture["key_csv"], encoding="utf-8"
    )
    (directory / "concentration_key.csv").write_text(
        fixture["concentration_key_csv"], encoding="utf-8"
    )
    plate_reader_path = directory / "plate_reader_export.txt"
    rows = [
        ["##BLOCKS= 1"],
        [
            "Plate:", "Plate1", "1.3", "TimeFormat", "Kinetic",
            "Fluorescence", "FALSE", "Raw", "FALSE", "2", "600", "60",
            "", "", "", "1", "510 ", "1", "5", "96", "485 ",
            "Manual", "", "", "", "10", "High", "", "", "1", "16",
            "485 ", "", "",
        ],
        ["Time", "Temperature(C)", "A1", "A2"],
        ["00:00:00", "37", "10", "20"],
        ["00:01:00", "37", "11", "21"],
        [],
        ["~End"],
    ]
    with plate_reader_path.open("w", encoding="utf-16", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerows(rows)
    return directory, plate_reader_path


def _legacy_read_only_body(runtime: JourneyRuntime) -> None:
    context = runtime.context
    runtime.add_assertion(simulation_identity_assertion(context))
    runtime.add_assertion(real_application_assertion(context))
    directory, plate_reader_path = _materialize_legacy_read_only_fixture(runtime)
    source_before = _hash_legacy_fixture(directory)

    loader = ExperimentLoaderDriver(context).inspect_legacy_execution(
        directory,
        expected_name=str(runtime.fixture["experiment_name"]),
    )
    runtime.observations["legacy_loader"] = loader
    runtime.add_assertion(
        AssertionResult(
            "experiment.legacy_read_only_exact",
            "legacy_main",
            "pass" if all(loader["checks"].values()) else "fail",
            ("ui", "model", "simulator"),
            loader,
        )
    )

    analysis = ExperimentLoaderDriver(
        context
    ).validate_legacy_plate_reader_analysis(
        directory,
        plate_reader_path,
        action_runner=runtime.harness.run_action,
    )
    runtime.observations["legacy_analysis"] = analysis
    runtime.add_assertion(
        AssertionResult(
            "analysis.legacy_plate_reader_ready",
            "legacy_plate_reader",
            "pass"
            if analysis["paths_prefilled"]
            and analysis["preview_valid"]
            and analysis["preview_ok"]
            and not analysis["preview_errors"]
            else "fail",
            ("ui", "controller", "analysis"),
            analysis,
        )
    )

    copy_name = f"{runtime.fixture['experiment_name']}-editable-copy"
    editable_copy = ExperimentLoaderDriver(context).create_legacy_editable_copy(
        directory,
        copy_name=copy_name,
    )
    runtime.observations["legacy_editable_copy"] = editable_copy
    copy_checks = {
        key: bool(editable_copy[key])
        for key in (
            "name_dialog_handled",
            "controls_editable",
            "legacy_state_cleared",
            "progress_empty",
            "no_execution_plan",
            "no_resume_checkpoint",
        )
    }
    runtime.add_assertion(
        AssertionResult(
            "experiment.legacy_editable_copy_fresh",
            "legacy_editable_copy",
            "pass" if all(copy_checks.values()) else "fail",
            ("ui", "model", "persistence"),
            {**editable_copy, "checks": copy_checks},
        )
    )

    source_after = _hash_legacy_fixture(directory)
    source_evidence = {
        "source_unchanged": source_after == source_before,
        "before": source_before,
        "after": source_after,
        "derived_files": sorted(
            path.relative_to(directory).as_posix()
            for path in directory.iterdir()
            if path.is_file() and path.name not in source_before
        ),
    }
    runtime.observations["legacy_source"] = source_evidence
    runtime.add_assertion(
        AssertionResult(
            "experiment.legacy_source_unchanged",
            "legacy_plate_reader",
            "pass" if source_evidence["source_unchanged"] else "fail",
            ("persistence",),
            source_evidence,
        )
    )


def _record_experiment_design_rejection(
    runtime: JourneyRuntime,
    *,
    case: Any,
    case_payload: Mapping[str, Any],
    driver_evidence: Mapping[str, Any],
    editor_action_start: int,
) -> None:
    expected_terminal = case.expected.terminal
    runtime.add_assertion(
        editor_create_rejected_assertion(
            runtime.context,
            action_start=editor_action_start,
            action_end=len(runtime.context.action_results),
            generated_before_finalize=expected_terminal == "capacity_rejected",
        )
    )
    rejection_result = experiment_finalization_rejected_no_mutation_assertion(
        runtime.context,
        case=case_payload,
        driver_evidence=driver_evidence,
    )
    runtime.add_assertion(rejection_result)
    runtime.observations["experiment_design_rejection"] = dict(
        rejection_result.evidence
    )
    capture_milestone(
        runtime.context,
        "validated",
        evidence={
            "terminal": expected_terminal,
            "case_id": case.case_id,
            "failed_checks": rejection_result.evidence.get("failed_checks", []),
        },
    )


def _experiment_design_body(runtime: JourneyRuntime) -> None:
    from tools.virtual_workflows.experiment_design_cases import (
        editor_specification,
        get_experiment_design_case,
    )

    case_payload = dict(runtime.fixture["lifecycle"]["case"])
    case = get_experiment_design_case(case_payload["case_id"])
    expected_terminal = case.expected.terminal
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    runtime.add_assertion(real_application_assertion(runtime.context))
    well_plate = runtime.context.model.well_plate
    exclusions_before = sorted(
        str(getattr(value, "well_id", value))
        for value in set(getattr(well_plate, "excluded_wells", set()) or set())
    )
    if exclusions_before:
        raise RuntimeError(
            "experiment-design scenario did not start with empty exclusions: "
            f"{exclusions_before!r}"
        )
    expected_exclusions = sorted(case.experiment.excluded_well_ids)
    editor_action_start = len(runtime.context.action_results)
    driver_evidence = run_editor_preparation(
        runtime,
        EditorPreparationSpec(
            editor_specification(case),
            use_harness_action_runner=True,
        ),
    )
    runtime.observations["experiment_design_driver"] = driver_evidence
    runtime.observations["experiment_design_exclusions"] = dict(
        (driver_evidence.get("configured") or {}).get(
            "exclusion_precondition"
        )
        or {}
    )
    if expected_terminal != "prepared":
        _record_experiment_design_rejection(
            runtime,
            case=case,
            case_payload=case_payload,
            driver_evidence=driver_evidence,
            editor_action_start=editor_action_start,
        )
        return
    runtime.add_assertion(
        editor_create_finalize_assertion(
            runtime.context,
            action_start=editor_action_start,
            action_end=len(runtime.context.action_results),
            optimization_action_ids=tuple(
                "editor.optimize_generate_via_ui"
                if index == 0
                else "editor.regenerate_prepared_design_via_ui"
                for index, _attempt in enumerate(case.optimization_attempts)
            ),
            pre_configure_action_ids=(
                ("artifact.capture_milestone",)
                if expected_exclusions
                else ()
            ),
        )
    )
    capture_milestone(
        runtime.context,
        "finalized",
        evidence={"experiment_name": case.experiment.name},
    )
    oracle_result, prepared_snapshot = experiment_design_case_oracle_assertion(
        runtime.context,
        case=case_payload,
        driver_evidence=driver_evidence,
    )
    runtime.add_assertion(oracle_result)
    runtime.observations["experiment_design_prepared"] = dict(
        oracle_result.evidence
    )
    loader_evidence = runtime.harness.run_action(
        "experiment.load_authoritative_via_ui",
        lambda: ExperimentLoaderDriver(runtime.context).load_prepared_design(
            Path(prepared_snapshot.experiment_dir),
            expected_name=case.experiment.name,
            expected_plan_id=prepared_snapshot.plan_id,
            expected_plan_revision=prepared_snapshot.plan_revision,
            capture_milestone_name="prepared_reloaded",
        ),
    )["evidence"]
    runtime.observations["experiment_design_reload"] = loader_evidence
    runtime.add_assertion(
        experiment_prepared_runtime_reconstructed_assertion(
            runtime.context,
            case=case_payload,
            prepared_snapshot=prepared_snapshot,
            loader_evidence=loader_evidence,
        )
    )
    capture_milestone(
        runtime.context,
        "validated",
        evidence={
            "case_id": case.case_id,
            "array_state": runtime.context.controller.get_array_run_state(),
            "runtime_active": bool(
                runtime.context.experiment_model
                .is_authoritative_execution_runtime_active()
            ),
        },
    )


def _editor_safeguard_body(runtime: JourneyRuntime) -> None:
    from tools.virtual_workflows.editor_safeguards import (
        get_editor_safeguard_case,
    )

    lifecycle = dict(runtime.fixture["lifecycle"])
    case = get_editor_safeguard_case(lifecycle["case"]["case_id"])
    specification = dict(lifecycle["editor_safeguard_specification"])
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    runtime.add_assertion(real_application_assertion(runtime.context))
    driver = run_editor_preparation(
        runtime,
        EditorPreparationSpec(
            specification,
            use_harness_action_runner=True,
        ),
    )
    rejection = dict(driver.get("finalization_rejection") or {})
    before_values = rejection.get("before") or rejection.get(
        "execution_artifacts_before"
    )
    after_values = rejection.get("after") or rejection.get(
        "execution_artifacts_after"
    )
    if not isinstance(before_values, Mapping) or not isinstance(
        after_values, Mapping
    ):
        raise RuntimeError("editor safeguard omitted its exact action boundary")

    def boundary(values: Mapping[str, Any]):
        return capture_safeguard_boundary(
            persistence={
                "experiment_dir": values.get("experiment_dir"),
                "directory_inventory": values.get("directory_inventory", {}),
                "execution_artifacts": values.get("execution_artifacts", {}),
            },
            model=dict(values.get("model") or {}),
            lifecycle=dict(values.get("lifecycle") or {}),
            queue=dict(values.get("queue") or {}),
            dispatch=dict(values.get("dispatch") or {}),
        )

    before = boundary(before_values)
    after = boundary(after_values)
    warning = dict(rejection.get("warning") or {})
    issue_codes = tuple(str(value) for value in rejection.get("issue_codes", ()))
    observed_code = str(rejection.get("observed_code") or "")
    if not observed_code and case.expected.code in issue_codes:
        observed_code = case.expected.code
    elif not observed_code and len(issue_codes) == 1:
        observed_code = issue_codes[0]
    observed_workflow = (
        "draft_dirty"
        if bool(after_values.get("lifecycle", {}).get("dirty"))
        else "draft_generated"
    )
    observed = ExpectedSafeguardOutcome(
        outcome_kind=case.expected.outcome_kind,
        classification=case.expected.classification,
        code=observed_code,
        message=str(warning.get("text") or ""),
        ui_surface="dialog",
        ui_title=str(warning.get("title") or ""),
        selected_control="OK" if warning.get("dismissed") else None,
        workflow_state=observed_workflow,
        queue_state=str(after_values.get("queue", {}).get("array_state") or ""),
        runtime_active=bool(
            after_values.get("lifecycle", {}).get("runtime_active")
        ),
        activation_count=0,
    )
    result = safeguard_rejection_no_mutation_no_dispatch_assertion(
        case=case,
        before=before,
        after=after,
        observed=observed,
        checkpoint="after_editor_safeguard_rejection",
    )
    runtime.add_assertion(result)
    runtime.observations["editor_safeguard"] = {
        "case_id": case.case_id,
        "case_sha256": case.contract_sha256,
        "catalog_sha256": lifecycle["catalog_sha256"],
        "driver": driver,
        "oracle": dict(result.evidence),
    }
    capture_milestone(
        runtime.context,
        "validated",
        evidence={
            "case_id": case.case_id,
            "decision": result.decision,
            "failed_checks": result.evidence.get("failed_checks", []),
        },
    )


def _execution_preflight_safeguard_body(runtime: JourneyRuntime) -> None:
    from tools.virtual_workflows.execution_preflight_safeguards import (
        get_execution_preflight_case,
    )

    lifecycle = dict(runtime.fixture["lifecycle"])
    case = get_execution_preflight_case(lifecycle["case"]["case_id"])
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    runtime.add_assertion(real_application_assertion(runtime.context))
    driven = drive_execution_preflight_safeguard(runtime.context, case)

    def boundary(values: Mapping[str, Any]):
        return capture_safeguard_boundary(
            persistence=dict(values["persistence"]),
            model=dict(values["model"]),
            lifecycle=dict(values["lifecycle"]),
            queue=dict(values["queue"]),
            dispatch=dict(values["dispatch"]),
        )

    before = boundary(driven["before"])
    after = boundary(driven["after"])
    ui = dict(driven["ui"])
    observed = ExpectedSafeguardOutcome(
        outcome_kind=case.expected.outcome_kind,
        classification=case.expected.classification,
        code=case.expected.code,
        message=str(ui["message"]),
        ui_surface=case.expected.ui_surface,
        ui_title=ui.get("title"),
        selected_control=ui.get("selected_control"),
        workflow_state=case.expected.workflow_state,
        queue_state=str(driven["after"]["queue"]["array_state"]),
        runtime_active=bool(driven["after"]["lifecycle"]["runtime_active"]),
        activation_count=0,
    )
    result = safeguard_rejection_no_mutation_no_dispatch_assertion(
        case=case,
        before=before,
        after=after,
        observed=observed,
        checkpoint="after_execution_preflight_safeguard",
    )
    runtime.add_assertion(result)
    runtime.observations["execution_preflight_safeguard"] = {
        "case_id": case.case_id,
        "case_sha256": case.contract_sha256,
        "catalog_sha256": lifecycle["catalog_sha256"],
        "driver": driven,
        "oracle": dict(result.evidence),
    }
    capture_milestone(
        runtime.context,
        "validated",
        evidence={
            "case_id": case.case_id,
            "decision": result.decision,
            "failed_checks": result.evidence.get("failed_checks", []),
        },
    )


def _persistence_safeguard_body(runtime: JourneyRuntime) -> None:
    lifecycle = dict(runtime.fixture["lifecycle"])
    case = get_persistence_safeguard_case(lifecycle["case"]["case_id"])
    prepared = dict(runtime.observations["persistence_fault_prelaunch"])
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    runtime.add_assertion(real_application_assertion(runtime.context))
    driven = ExperimentLoaderDriver(runtime.context).load_rejected_authoritative_execution(
        prepared["faulted_root"],
        case=case,
    )

    source_current = persistence_fixture_inventory(Path(prepared["source_root"]))
    faulted_current = persistence_fixture_inventory(Path(prepared["faulted_root"]))
    if source_current != dict(prepared["source_inventory"]):
        raise RuntimeError("pristine persistence source changed after application launch")
    if faulted_current != dict(prepared["faulted_inventory"]):
        raise RuntimeError("faulted persistence copy changed after application launch")

    def boundary(values: Mapping[str, Any]):
        persistence = dict(values["persistence"])
        persistence.update(
            source_inventory=source_current,
            faulted_inventory=faulted_current,
            fault_manifest=dict(prepared["fault_manifest"]),
        )
        return capture_safeguard_boundary(
            persistence=persistence,
            model=dict(values["model"]),
            lifecycle=dict(values["lifecycle"]),
            queue=dict(values["queue"]),
            dispatch=dict(values["dispatch"]),
        )

    before = boundary(driven["before"])
    after = boundary(driven["after"])
    ui = dict(driven["ui"])
    observed = ExpectedSafeguardOutcome(
        outcome_kind=case.expected.outcome_kind,
        classification=str(driven["classification"]["classification"]),
        code=str(driven["classification"]["code"]),
        message=str(ui["message"]),
        ui_surface=case.expected.ui_surface,
        ui_title=None,
        selected_control=str(ui["selected_control"]),
        workflow_state=case.expected.workflow_state,
        queue_state=str(driven["after"]["queue"]["array_state"]),
        runtime_active=bool(driven["after"]["lifecycle"]["runtime_active"]),
        activation_count=0,
    )
    result = safeguard_rejection_no_mutation_no_dispatch_assertion(
        case=case,
        before=before,
        after=after,
        observed=observed,
        checkpoint="after_rejected_authoritative_activation",
    )
    runtime.add_assertion(result)
    runtime.observations["persistence_safeguard"] = {
        "case_id": case.case_id,
        "case_sha256": case.contract_sha256,
        "catalog_sha256": lifecycle["catalog_sha256"],
        "prelaunch": prepared,
        "driver": driven,
        "oracle": dict(result.evidence),
    }
    capture_milestone(
        runtime.context,
        "validated",
        evidence={
            "case_id": case.case_id,
            "decision": result.decision,
            "failed_checks": result.evidence.get("failed_checks", []),
            "source_preserved": True,
            "faulted_copy_preserved": True,
        },
    )


def run_optimizer_360_first_calibration_checkpoint(runtime: JourneyRuntime) -> None:
    """Drive the real editor/optimizer through Range A zero-progress Apply."""

    from tools.virtual_workflows.experiment_design_cases import editor_specification

    case = OPTIMIZER_360_CASE
    context = runtime.context
    runtime.add_assertion(simulation_identity_assertion(context))
    runtime.add_assertion(real_application_assertion(context))
    action_start = len(context.action_results)
    driver = run_editor_preparation(
        runtime,
        EditorPreparationSpec(
            editor_specification(case.design_case),
            use_harness_action_runner=True,
            capture_editor_milestones=False,
        ),
    )
    runtime.add_assertion(
        editor_create_finalize_assertion(
            context,
            action_start=action_start,
            action_end=len(context.action_results),
            optimization_action_ids=("editor.optimize_generate_via_ui",),
            capture_editor_milestones=False,
        )
    )
    capture_milestone(
        context,
        "optimizer_stocks_generated",
        evidence={
            "case_id": case.case_id,
            "random_seed": case.editor.random_seed,
            "fixed_stocks_blank": all(
                row.fixed_stock_concentration is None
                for row in case.design_case.reagents
            ),
        },
    )
    design_result, prepared = optimizer_360_design_assertion(
        context,
        case=case,
        driver_evidence=driver,
    )
    runtime.add_assertion(design_result)
    capture_milestone(
        context,
        "prepared_randomized",
        evidence={
            "plan_id": prepared.plan_id,
            "plan_revision": prepared.plan_revision,
            "assignment_sha256": case.design_case.expected.assignment_sha256(),
            "design_sha256": prepared.design_sha256,
            "core_file_hashes": prepared.core_file_hashes,
        },
    )
    runtime.observations["optimizer_360_calibration_lifecycle"] = {
        "prepared": dict(design_result.evidence)
    }

    runtime.run_steps(machine_startup_steps())
    observer = ExecutionObserver(
        context,
        experiment_dir=Path(prepared.experiment_dir),
        completed_count=lambda: 0,
        pass_context=lambda: {
            "stock_id": RANGE_A_STOCK_ID,
            "phase": "calibration_only",
        },
    )
    runtime.register_restorable("optimizer_360_calibration_execution", observer)
    observer.install()
    calibration = case.calibrations[0]
    boundary = run_stock_calibration_only(
        runtime,
        CalibrationOnlySpec(
            stock_id=calibration.stock_id,
            printer_head_id=calibration.printer_head_id,
            pulse_width_us=calibration.print_pulse_width_us,
            pressure_psi=2.0,
            frequency_hz=100,
            initial_volume_uL=100.0,
            expected_volume_nL=float(calibration.droplet_volume_nL),
        ),
    )
    runtime.restore_all()
    observer_snapshot = runtime.observations[
        "optimizer_360_calibration_execution_snapshot"
    ]
    calibrated_result, calibrated = calibrated_zero_progress_assertion(
        context,
        case=case,
        prepared_snapshot=prepared,
        calibration_evidence=boundary,
        observer=observer_snapshot,
        oracle_checkpoint_id="range_a_calibrated",
        legacy_evidence_names=False,
    )
    runtime.add_assertion(calibrated_result)
    capture_milestone(
        context,
        "range_a_calibrated",
        evidence={
            "plan_id": calibrated.plan_id,
            "plan_revision": calibrated.plan_revision,
            "stock_id": calibration.stock_id,
            "printer_head_id": calibration.printer_head_id,
            "total_added_droplets": calibrated.total_added_droplets,
            "core_file_hashes": calibrated.core_file_hashes,
        },
    )
    runtime.observations["optimizer_360_calibration_lifecycle"].update(
        {
            "range_a_calibrated": dict(calibrated_result.evidence),
        }
    )
    runtime.observations["optimizer_360_prepared_snapshot"] = prepared
    runtime.observations["optimizer_360_calibrated_snapshot"] = calibrated
    runtime.observations["optimizer_360_session_1_observer"] = observer_snapshot


def run_optimizer_360_calibration_chain(runtime: JourneyRuntime) -> None:
    """Continue the corrected optimizer case through all five calibrations."""

    run_optimizer_360_first_calibration_checkpoint(runtime)
    case = OPTIMIZER_360_CASE
    context = runtime.context
    calibrated = runtime.observations["optimizer_360_calibrated_snapshot"]
    first_observer = runtime.observations["optimizer_360_session_1_observer"]

    rotation = run_clean_authoritative_session_rotation_boundary(
        runtime,
        experiment_dir=calibrated.experiment_dir,
        expected_name=str(calibrated.metadata.get("name") or ""),
        completed_count=lambda: 0,
        pass_context=lambda: _current_pass_context(runtime),
        inspect_loaded=lambda: capture_count_snapshot(context),
        inspect_activated=lambda: capture_count_snapshot(context),
        observer_key="optimizer_360_session_2_execution",
    )
    second_observer = runtime.observations["execution_observer"].snapshot()
    fresh_result = clean_joined_session_rotation_assertion(
        context,
        case=case,
        rotation=rotation,
        first_session_observer=first_observer,
        second_session_observer=second_observer,
        oracle_checkpoint_id="range_a_calibrated",
    )
    runtime.add_assertion(fresh_result)
    runtime.observations["optimizer_360_calibration_lifecycle"][
        "clean_session_rotation"
    ] = dict(fresh_result.evidence)

    runtime.observations.update(
        {
            "expected_wells": tuple(case.editor.selected_well_ids),
            "expected_stock_ids": tuple(
                row.stock_id for row in case.execution_passes
            ),
            "completed_wells": [],
            "array_completions": [],
            "pass_boundaries": [],
            "head_staging": [],
            "returned_head_ids": [],
            "starvation_events": [],
            "current_pass": {"index": -1, "starting_count": 0, "stock_id": None},
        }
    )
    _connect_execution_signals(runtime, array_complete=True, machine_errors=True)
    _install_starvation_observer(runtime)
    runtime.run_steps(machine_startup_steps())

    remaining: list[Mapping[str, Any]] = []
    milestone_by_stock = {
        case.calibrations[1].stock_id: "range_b_calibrated",
        case.calibrations[2].stock_id: "range_c_calibrated",
        case.calibrations[3].stock_id: "range_d_calibrated",
        case.calibrations[4].stock_id: "all_stocks_calibrated",
    }
    for calibration in case.calibrations[1:]:
        evidence = run_stock_calibration_only(
            runtime,
            CalibrationOnlySpec(
                stock_id=calibration.stock_id,
                printer_head_id=calibration.printer_head_id,
                pulse_width_us=calibration.print_pulse_width_us,
                pressure_psi=2.0,
                frequency_hz=100,
                initial_volume_uL=100.0,
                expected_volume_nL=float(calibration.droplet_volume_nL),
                staging_slot=(calibration.order - 1) % 4,
                apply_success_title=(
                    "Applied (Fill)"
                    if calibration.reagent_name == "Water"
                    else "Applied"
                ),
                enable_pressure_regulation=calibration.order == 2,
                return_head=True,
            ),
        )
        remaining.append(evidence)
        current = context.experiment_model.get_execution_plan_snapshot()
        capture_milestone(
            context,
            milestone_by_stock[calibration.stock_id],
            evidence={
                "stock_id": calibration.stock_id,
                "printer_head_id": calibration.printer_head_id,
                "plan_revision": current.plan_revision,
            },
        )
    result, fully_calibrated = joined_remaining_calibrations_assertion(
        context,
        case=case,
        calibration_evidence=remaining,
    )
    runtime.add_assertion(result)
    runtime.observations["optimizer_360_calibration_lifecycle"][
        "remaining_calibrations"
    ] = dict(result.evidence)
    runtime.observations["optimizer_360_fully_calibrated_snapshot"] = (
        fully_calibrated
    )


def run_optimizer_360_full_lifecycle(runtime: JourneyRuntime) -> None:
    """Execute and terminally reload all 1,800 literal stock/well intents."""

    run_optimizer_360_calibration_chain(runtime)
    case = OPTIMIZER_360_CASE
    context = runtime.context
    calibrations_by_stock = {row.stock_id: row for row in case.calibrations}
    pass_specs = tuple(
        PrecalibratedStockPassSpec(
            stock_id=execution_pass.stock_id,
            printer_head_id=calibrations_by_stock[
                execution_pass.stock_id
            ].printer_head_id,
            pulse_width_us=calibrations_by_stock[
                execution_pass.stock_id
            ].print_pulse_width_us,
            pressure_psi=2.0,
            frequency_hz=100,
            initial_volume_uL=100.0,
            expected_volume_nL=float(
                calibrations_by_stock[execution_pass.stock_id].droplet_volume_nL
            ),
            expected_completion_count=execution_pass.cumulative_completion,
            expected_plan_state=(
                "completed"
                if execution_pass.order == len(case.execution_passes)
                else "active"
            ),
            completed_milestone=execution_pass.milestone,
            staging_slot=(execution_pass.order - 1) % 4,
            start_dialog_titles=(
                ("Start Print Array", "Evaporation Plate Dock Check")
                if execution_pass.order == 1
                else ("Start Print Array",)
            ),
        )
        for execution_pass in case.execution_passes
    )
    run_precalibrated_stock_passes(runtime, pass_specs)
    terminal_counts = capture_count_snapshot(context)
    capture_milestone(
        context,
        "completed",
        evidence={
            "completion_count": len(runtime.observations["completed_wells"]),
            "plan_revision": context.experiment_model
            .get_execution_plan_snapshot()
            .plan_revision,
            "expected_intents": case.terminal.expected_intents,
            "expected_droplets": case.terminal.expected_droplets,
        },
    )
    runtime.restore_all()
    session_2_observer = runtime.observations[
        "optimizer_360_session_2_execution_snapshot"
    ]
    _run_completed_terminal_reload(
        runtime,
        expected_name=case.editor.name,
    )
    terminal_result = joined_terminal_execution_assertion(
        context,
        case=case,
        terminal_counts=terminal_counts,
        terminal_reload=runtime.observations["completed_terminal_reload"],
        observer=session_2_observer,
        first_session_observer=runtime.observations[
            "optimizer_360_session_1_observer"
        ],
        pass_boundaries=runtime.observations["pass_boundaries"],
        starvation_events=runtime.observations["starvation_events"],
        application_sessions=runtime.harness.application_sessions,
    )
    runtime.add_assertion(terminal_result)
    runtime.observations["optimizer_360_calibration_lifecycle"]["terminal"] = (
        dict(terminal_result.evidence)
    )


def run_joined_calibrated_checkpoint(runtime: JourneyRuntime) -> None:
    """Drive the registered Milestone 11 lifecycle through terminal reload."""

    from tools.virtual_workflows.experiment_design_cases import (
        editor_specification,
        get_experiment_design_case,
    )
    case = JOINED_INTERACTION_CASE
    source = get_experiment_design_case(case.source.case_id)
    context = runtime.context
    runtime.add_assertion(simulation_identity_assertion(context))
    runtime.add_assertion(real_application_assertion(context))
    action_start = len(context.action_results)
    driver = run_editor_preparation(
        runtime,
        EditorPreparationSpec(
            editor_specification(source),
            use_harness_action_runner=True,
            capture_editor_milestones=False,
        ),
    )
    runtime.add_assertion(
        editor_create_finalize_assertion(
            context,
            action_start=action_start,
            action_end=len(context.action_results),
            optimization_action_ids=("editor.optimize_generate_via_ui",),
            capture_editor_milestones=False,
        )
    )
    capture_milestone(
        context,
        "design_generated",
        evidence={"case_id": source.case_id, "random_seed": source.experiment.random_seed},
    )
    design_result, prepared = randomized_joined_design_assertion(
        context,
        case=case,
        driver_evidence=driver,
    )
    runtime.add_assertion(design_result)
    capture_milestone(
        context,
        "prepared_randomized",
        evidence={
            "plan_id": prepared.plan_id,
            "plan_revision": prepared.plan_revision,
            "assignment_sha256": case.source.assignment_sha256,
        },
    )
    runtime.observations["randomized_calibration_lifecycle"] = {
        "prepared": dict(design_result.evidence)
    }

    runtime.run_steps(machine_startup_steps())
    observer = ExecutionObserver(
        context,
        experiment_dir=Path(prepared.experiment_dir),
        completed_count=lambda: 0,
        pass_context=lambda: {"stock_id": DESIGN_A_STOCK_ID, "phase": "calibration_only"},
    )
    runtime.register_restorable("joined_calibration_execution", observer)
    observer.install()
    calibration = case.calibrations[0]
    boundary = run_stock_calibration_only(
        runtime,
        CalibrationOnlySpec(
            stock_id=calibration.stock_id,
            printer_head_id=calibration.printer_head_id,
            pulse_width_us=calibration.print_pulse_width_us,
            pressure_psi=2.0,
            frequency_hz=100,
            initial_volume_uL=100.0,
            expected_volume_nL=float(calibration.droplet_volume_nL),
        ),
    )
    runtime.restore_all()
    observer_snapshot = runtime.observations["joined_calibration_execution_snapshot"]
    calibrated_result, calibrated = calibrated_zero_progress_assertion(
        context,
        case=case,
        prepared_snapshot=prepared,
        calibration_evidence=boundary,
        observer=observer_snapshot,
    )
    runtime.add_assertion(calibrated_result)
    capture_milestone(
        context,
        "calibrated_zero_progress",
        evidence={
            "plan_id": calibrated.plan_id,
            "plan_revision": calibrated.plan_revision,
            "stock_id": calibration.stock_id,
            "printer_head_id": calibration.printer_head_id,
            "total_added_droplets": calibrated.total_added_droplets,
        },
    )
    runtime.observations["randomized_calibration_lifecycle"][
        "calibrated_zero_progress"
    ] = dict(calibrated_result.evidence)

    rotation = run_clean_authoritative_session_rotation_boundary(
        runtime,
        experiment_dir=calibrated.experiment_dir,
        expected_name=str(calibrated.metadata.get("name") or ""),
        completed_count=lambda: 0,
        pass_context=lambda: _current_pass_context(runtime),
        inspect_loaded=lambda: capture_count_snapshot(context),
        inspect_activated=lambda: capture_count_snapshot(context),
        observer_key="joined_session_2_execution",
    )
    second_observer = runtime.observations["execution_observer"].snapshot()
    fresh_result = clean_joined_session_rotation_assertion(
        context,
        case=case,
        rotation=rotation,
        first_session_observer=observer_snapshot,
        second_session_observer=second_observer,
    )
    runtime.add_assertion(fresh_result)
    runtime.observations["randomized_calibration_lifecycle"][
        "clean_session_rotation"
    ] = dict(fresh_result.evidence)

    runtime.observations.update(
        {
            "expected_wells": tuple(case.editor.selected_well_ids),
            "expected_stock_ids": tuple(
                row.stock_id for row in case.execution_passes
            ),
            "completed_wells": [],
            "array_completions": [],
            "pass_boundaries": [],
            "head_staging": [],
            "returned_head_ids": [],
            "starvation_events": [],
            "current_pass": {"index": -1, "starting_count": 0, "stock_id": None},
        }
    )
    _connect_execution_signals(runtime, array_complete=True, machine_errors=True)
    _install_starvation_observer(runtime)
    runtime.run_steps(machine_startup_steps())

    remaining_calibrations: list[Mapping[str, Any]] = []
    for calibration_row in case.calibrations[1:]:
        remaining_calibrations.append(
            run_stock_calibration_only(
                runtime,
                CalibrationOnlySpec(
                    stock_id=calibration_row.stock_id,
                    printer_head_id=calibration_row.printer_head_id,
                    pulse_width_us=calibration_row.print_pulse_width_us,
                    pressure_psi=2.0,
                    frequency_hz=100,
                    initial_volume_uL=100.0,
                    expected_volume_nL=float(calibration_row.droplet_volume_nL),
                    apply_success_title=(
                        "Applied (Fill)"
                        if calibration_row.reagent_name == "Water"
                        else "Applied"
                    ),
                    enable_pressure_regulation=calibration_row.order == 2,
                    return_head=True,
                ),
            )
        )
    calibrated_result, fully_calibrated = joined_remaining_calibrations_assertion(
        context,
        case=case,
        calibration_evidence=remaining_calibrations,
    )
    runtime.add_assertion(calibrated_result)
    capture_milestone(
        context,
        "remaining_stocks_calibrated",
        evidence={
            "plan_id": fully_calibrated.plan_id,
            "plan_revision": fully_calibrated.plan_revision,
            "record_count": fully_calibrated.calibration_record_count,
            "total_added_droplets": fully_calibrated.total_added_droplets,
        },
    )

    calibrations_by_stock = {row.stock_id: row for row in case.calibrations}
    milestones = (
        "design_a_pass_complete",
        "design_b_pass_complete",
        "water_pass_complete",
    )
    pass_specs = tuple(
        PrecalibratedStockPassSpec(
            stock_id=execution_pass.stock_id,
            printer_head_id=calibrations_by_stock[
                execution_pass.stock_id
            ].printer_head_id,
            pulse_width_us=calibrations_by_stock[
                execution_pass.stock_id
            ].print_pulse_width_us,
            pressure_psi=2.0,
            frequency_hz=100,
            initial_volume_uL=100.0,
            expected_volume_nL=float(
                calibrations_by_stock[execution_pass.stock_id].droplet_volume_nL
            ),
            expected_completion_count=8 * execution_pass.order,
            expected_plan_state=(
                "completed"
                if execution_pass.order == len(case.execution_passes)
                else "active"
            ),
            completed_milestone=milestones[execution_pass.order - 1],
            start_dialog_titles=(
                ("Start Print Array", "Evaporation Plate Dock Check")
                if execution_pass.order == 1
                else ("Start Print Array",)
            ),
        )
        for execution_pass in case.execution_passes
    )
    run_precalibrated_stock_passes(runtime, pass_specs)
    terminal_counts = capture_count_snapshot(context)
    capture_milestone(
        context,
        "completed",
        evidence={
            "completion_count": len(runtime.observations["completed_wells"]),
            "plan_revision": context.experiment_model
            .get_execution_plan_snapshot()
            .plan_revision,
        },
    )
    runtime.restore_all()
    session_2_observer = runtime.observations[
        "joined_session_2_execution_snapshot"
    ]
    _run_completed_terminal_reload(
        runtime,
        expected_name=case.editor.experiment_name,
    )
    terminal_reload = runtime.observations["completed_terminal_reload"]
    terminal_result = joined_terminal_execution_assertion(
        context,
        case=case,
        terminal_counts=terminal_counts,
        terminal_reload=terminal_reload,
        observer=session_2_observer,
        first_session_observer=observer_snapshot,
        pass_boundaries=runtime.observations["pass_boundaries"],
        starvation_events=runtime.observations["starvation_events"],
        application_sessions=runtime.harness.application_sessions,
    )
    runtime.add_assertion(terminal_result)
    runtime.observations["randomized_calibration_lifecycle"].update(
        {
            "remaining_calibrations": dict(calibrated_result.evidence),
            "terminal": dict(terminal_result.evidence),
        }
    )


def _m13_boundary(
    runtime: JourneyRuntime,
    *,
    identity_keys: Mapping[str, Any],
    workflow_state: str,
):
    observed = capture_execution_preflight_boundary(
        runtime.context,
        identity_keys=identity_keys,
        workflow_state=workflow_state,
    )
    return capture_safeguard_boundary(
        persistence=observed["persistence"],
        model=observed["model"],
        lifecycle=observed["lifecycle"],
        queue=observed["queue"],
        dispatch=observed["dispatch"],
    )


def _m13_record_rejection(
    runtime: JourneyRuntime,
    *,
    operation_id: str,
    case: Any,
    shared_result: Any,
    outer_before: Any,
    outer_after: Any,
    driven: Mapping[str, Any],
) -> None:
    result = m13_rejection_continuity_assertion(
        operation_id=operation_id,
        case_id=case.case_id,
        shared_result=shared_result,
        outer_before=outer_before,
        outer_after=outer_after,
    )
    runtime.add_assertion(result)
    runtime.observations.setdefault("m13_rejections", {})[operation_id] = {
        "decision": result.decision,
        "assertion_id": result.assertion_id,
        "case_id": case.case_id,
        "case_sha256": case.contract_sha256,
        "shared_oracle": dict(shared_result.evidence),
        "outer_oracle": dict(result.evidence),
        "driver": dict(driven),
    }


def _m13_run_preflight_rejection(
    runtime: JourneyRuntime,
    *,
    operation_id: str,
    case_id: str,
    workflow_state: str,
) -> None:
    context = runtime.context
    case = get_execution_preflight_case(case_id)
    original_runtime = bool(
        context.experiment_model.is_authoritative_execution_runtime_active()
    )
    original_array_state = context.controller.get_array_run_state()
    outer_before = _m13_boundary(
        runtime,
        identity_keys=case.identity_keys,
        workflow_state=workflow_state,
    )
    driven = drive_execution_preflight_safeguard(
        context,
        case,
        capture_rejection_screenshot=False,
    )

    def boundary(values: Mapping[str, Any]):
        return capture_safeguard_boundary(
            persistence=dict(values["persistence"]),
            model=dict(values["model"]),
            lifecycle=dict(values["lifecycle"]),
            queue=dict(values["queue"]),
            dispatch=dict(values["dispatch"]),
        )

    ui = dict(driven["ui"])
    observed = ExpectedSafeguardOutcome(
        outcome_kind=case.expected.outcome_kind,
        classification=case.expected.classification,
        code=case.expected.code,
        message=str(ui["message"]),
        ui_surface=case.expected.ui_surface,
        ui_title=ui.get("title"),
        selected_control=ui.get("selected_control"),
        workflow_state=case.expected.workflow_state,
        queue_state=str(driven["after"]["queue"]["array_state"]),
        runtime_active=bool(driven["after"]["lifecycle"]["runtime_active"]),
        activation_count=0,
    )
    shared = safeguard_rejection_no_mutation_no_dispatch_assertion(
        case=case,
        before=boundary(driven["before"]),
        after=boundary(driven["after"]),
        observed=observed,
        checkpoint="after_m13_generated_rejection",
    )
    context.experiment_model._authoritative_runtime_active = original_runtime
    context.controller._set_array_run_state(original_array_state)
    context.view.well_plate_widget.update_start_print_array_button()
    context.app.processEvents()
    outer_after = _m13_boundary(
        runtime,
        identity_keys=case.identity_keys,
        workflow_state=workflow_state,
    )
    _m13_record_rejection(
        runtime,
        operation_id=operation_id,
        case=case,
        shared_result=shared,
        outer_before=outer_before,
        outer_after=outer_after,
        driven=driven,
    )


def _m13_run_editor_rejection(
    runtime: JourneyRuntime,
    *,
    operation_id: str,
    case_id: str,
) -> None:
    case = get_editor_safeguard_case(case_id)
    specification = dict(case.setup["specification"])
    # Reuse the Milestone 12 rich boundary projection so the generated
    # rejection is checked by the same persistence/model/lifecycle/queue/
    # dispatch oracle as its deterministic source case.
    specification["safeguard_boundary_sync"] = True
    driver = run_editor_preparation(
        runtime,
        EditorPreparationSpec(
            specification,
            use_harness_action_runner=True,
            capture_editor_milestones=False,
        ),
    )
    rejection = dict(driver.get("finalization_rejection") or {})
    before_values = rejection.get("before") or rejection.get(
        "execution_artifacts_before"
    )
    after_values = rejection.get("after") or rejection.get(
        "execution_artifacts_after"
    )
    if not isinstance(before_values, Mapping) or not isinstance(
        after_values, Mapping
    ):
        raise RuntimeError("M13 editor rejection omitted its exact boundary")

    def boundary(values: Mapping[str, Any]):
        return capture_safeguard_boundary(
            persistence={
                "experiment_dir": values.get("experiment_dir"),
                "directory_inventory": values.get("directory_inventory", {}),
                "execution_artifacts": values.get("execution_artifacts", {}),
            },
            model=dict(values.get("model") or {}),
            lifecycle=dict(values.get("lifecycle") or {}),
            queue=dict(values.get("queue") or {}),
            dispatch=dict(values.get("dispatch") or {}),
        )

    before = boundary(before_values)
    after = boundary(after_values)
    warning = dict(rejection.get("warning") or {})
    issue_codes = tuple(str(value) for value in rejection.get("issue_codes", ()))
    observed_code = str(rejection.get("observed_code") or "")
    if not observed_code and case.expected.code in issue_codes:
        observed_code = case.expected.code
    elif not observed_code and len(issue_codes) == 1:
        observed_code = issue_codes[0]
    observed = ExpectedSafeguardOutcome(
        outcome_kind=case.expected.outcome_kind,
        classification=case.expected.classification,
        code=observed_code,
        message=str(warning.get("text") or ""),
        ui_surface="dialog",
        ui_title=str(warning.get("title") or ""),
        selected_control="OK" if warning.get("dismissed") else None,
        workflow_state=(
            "draft_dirty"
            if bool(after_values.get("lifecycle", {}).get("dirty"))
            else "draft_generated"
        ),
        queue_state=str(after_values.get("queue", {}).get("array_state") or ""),
        runtime_active=bool(
            after_values.get("lifecycle", {}).get("runtime_active")
        ),
        activation_count=0,
    )
    shared = safeguard_rejection_no_mutation_no_dispatch_assertion(
        case=case,
        before=before,
        after=after,
        observed=observed,
        checkpoint="after_m13_generated_editor_rejection",
    )
    _m13_record_rejection(
        runtime,
        operation_id=operation_id,
        case=case,
        shared_result=shared,
        outer_before=before,
        outer_after=after,
        driven={"driver": driver},
    )


def run_m13_legal_sequence_lifecycle(runtime: JourneyRuntime) -> None:
    """Execute one compact generated sequence through terminal reload."""

    from tools.virtual_workflows.experiment_design_cases import editor_specification
    from tools.virtual_workflows.exploration_m13 import (
        get_sequence,
        sequence_from_normalized,
    )

    retained = runtime.fixture.get("normalized_sequence")
    sequence = (
        sequence_from_normalized(retained)
        if isinstance(retained, Mapping)
        else get_sequence(str(runtime.fixture["sequence_id"]))
    )
    supported_roles = {
        "legal_design_calibration_terminal",
        "legal_refinalize_reload_terminal",
        "illegal_editor_recovery_terminal",
        "illegal_calibration_recovery_terminal",
        "illegal_identity_activation_recovery_terminal",
        "illegal_progress_lock_recovery_terminal",
    }
    if sequence.role not in supported_roles:
        raise ValueError("unsupported Milestone 13 sequence role")
    context = runtime.context
    case = M13_COMPACT_CASE
    runtime.observations["m13_sequence"] = sequence
    runtime.observations["m13_case"] = case
    runtime.observations["m13_lifecycle"] = {}
    runtime.observations["m13_rejections"] = {}
    if sequence.role == "illegal_editor_recovery_terminal":
        _m13_run_editor_rejection(
            runtime,
            operation_id="editor.finalize_invalid_via_ui",
            case_id="printed_exceeds_final_finalize_rejected",
        )
        _m13_run_editor_rejection(
            runtime,
            operation_id="editor.optimize_one_stock_invalid_via_ui",
            case_id="one_stock_infeasible_finalize_rejected",
        )
    runtime.add_assertion(simulation_identity_assertion(context))
    runtime.add_assertion(real_application_assertion(context))
    action_start = len(context.action_results)
    driver = run_editor_preparation(
        runtime,
        EditorPreparationSpec(
            editor_specification(case.design_case),
            use_harness_action_runner=True,
            capture_editor_milestones=False,
        ),
    )
    runtime.add_assertion(
        editor_create_finalize_assertion(
            context,
            action_start=action_start,
            action_end=len(context.action_results),
            optimization_action_ids=("editor.optimize_generate_via_ui",),
            capture_editor_milestones=False,
        )
    )
    design_result, initial_prepared = experiment_design_case_oracle_assertion(
        context,
        case=case.design_case.normalized(),
        driver_evidence=driver,
    )
    runtime.add_assertion(design_result)
    revision_evidence: Mapping[str, Any] | None = None
    previous = None
    if sequence.role == "legal_refinalize_reload_terminal":
        previous = initial_prepared
        case = M13_REFINALIZED_COMPACT_CASE
        revision_evidence = run_prepared_editor_revision(
            runtime,
            PreparedEditorRevisionSpec(
                initial_name=M13_COMPACT_CASE.editor.experiment_name,
                renamed_name=case.editor.experiment_name,
                replicates=2,
                well_ids=tuple(case.editor.selected_well_ids),
                printed_volume_nL=100.0,
                final_volume_nL=100.0,
                fill_printing_mode="droplet",
                fill_droplet_volume_nL=9.0,
                reagent_printing_mode="droplet",
                reagent_targets=(0.9, 1.8),
                reagent_droplet_volume_nL=10.0,
            ),
            capture_milestones=False,
        )
    prepared_result, prepared = m13_compact_prepared_assertion(
        context,
        case=case,
        driver_evidence=driver,
        previous_snapshot=previous,
        revision_evidence=revision_evidence,
    )
    runtime.add_assertion(prepared_result)
    capture_milestone(
        context,
        "prepared",
        evidence={
            "sequence_id": sequence.sequence_id,
            "plan_id": prepared.plan_id,
            "plan_revision": prepared.plan_revision,
            "design_sha256": prepared.design_sha256,
        },
    )
    runtime.observations["m13_case"] = case
    runtime.observations["m13_lifecycle"]["prepared"] = dict(
        prepared_result.evidence
    )
    if sequence.role == "illegal_calibration_recovery_terminal":
        _m13_run_preflight_rejection(
            runtime,
            operation_id="calibration.attempt_mismatch_cancel_via_ui",
            case_id="calibration_head_mode_cancelled",
            workflow_state="prepared_zero_progress",
        )

    runtime.run_steps(machine_startup_steps())
    observer = ExecutionObserver(
        context,
        experiment_dir=Path(prepared.experiment_dir),
        completed_count=lambda: 0,
        pass_context=lambda: {
            "stock_id": case.calibrations[0].stock_id,
            "phase": "calibration_only",
        },
    )
    runtime.register_restorable("m13_session_1_execution", observer)
    observer.install()
    first_calibration = case.calibrations[0]
    first_boundary = run_stock_calibration_only(
        runtime,
        CalibrationOnlySpec(
            stock_id=first_calibration.stock_id,
            printer_head_id=first_calibration.printer_head_id,
            pulse_width_us=first_calibration.print_pulse_width_us,
            pressure_psi=2.0,
            frequency_hz=100,
            initial_volume_uL=100.0,
            expected_volume_nL=float(first_calibration.droplet_volume_nL),
        ),
    )
    runtime.restore_all()
    first_observer = runtime.observations["m13_session_1_execution_snapshot"]
    calibrated_result, calibrated = calibrated_zero_progress_assertion(
        context,
        case=case,
        prepared_snapshot=prepared,
        calibration_evidence=first_boundary,
        observer=first_observer,
        legacy_evidence_names=False,
    )
    runtime.add_assertion(calibrated_result)
    runtime.observations["m13_lifecycle"]["calibrated_zero_progress"] = dict(
        calibrated_result.evidence
    )

    rotation = run_clean_authoritative_session_rotation_boundary(
        runtime,
        experiment_dir=calibrated.experiment_dir,
        expected_name=case.editor.experiment_name,
        completed_count=lambda: 0,
        pass_context=lambda: _current_pass_context(runtime),
        inspect_loaded=lambda: capture_count_snapshot(context),
        inspect_activated=lambda: capture_count_snapshot(context),
        loaded_hook=(
            lambda current: _m13_run_preflight_rejection(
                current,
                operation_id="array.start_inactive_via_ui",
                case_id="inspected_not_activated_start_rejected",
                workflow_state="reloaded_inactive",
            )
            if sequence.role == "illegal_identity_activation_recovery_terminal"
            else None
        ),
        activated_hook=(
            lambda current: _m13_run_preflight_rejection(
                current,
                operation_id="array.start_wrong_identity_via_ui",
                case_id="wrong_printer_head_calibration_binding_rejected",
                workflow_state="active_zero_progress",
            )
            if sequence.role == "illegal_identity_activation_recovery_terminal"
            else None
        ),
        observer_key="m13_session_2_execution",
    )
    second_observer = runtime.observations["execution_observer"].snapshot()
    rotation_result = clean_joined_session_rotation_assertion(
        context,
        case=case,
        rotation=rotation,
        first_session_observer=first_observer,
        second_session_observer=second_observer,
    )
    runtime.add_assertion(rotation_result)
    runtime.observations["m13_lifecycle"]["clean_session_rotation"] = dict(
        rotation_result.evidence
    )

    runtime.observations.update(
        {
            "expected_wells": tuple(case.editor.selected_well_ids),
            "expected_stock_ids": tuple(row.stock_id for row in case.execution_passes),
            "completed_wells": [],
            "array_completions": [],
            "pass_boundaries": [],
            "head_staging": [],
            "returned_head_ids": [],
            "starvation_events": [],
            "current_pass": {"index": -1, "starting_count": 0, "stock_id": None},
        }
    )
    _connect_execution_signals(runtime, array_complete=True, machine_errors=True)
    _install_starvation_observer(runtime)
    runtime.run_steps(machine_startup_steps())

    remaining_evidence: list[Mapping[str, Any]] = []
    for calibration in case.calibrations[1:]:
        remaining_evidence.append(
            run_stock_calibration_only(
                runtime,
                CalibrationOnlySpec(
                    stock_id=calibration.stock_id,
                    printer_head_id=calibration.printer_head_id,
                    pulse_width_us=calibration.print_pulse_width_us,
                    pressure_psi=2.0,
                    frequency_hz=100,
                    initial_volume_uL=100.0,
                    expected_volume_nL=float(calibration.droplet_volume_nL),
                    apply_success_title="Applied (Fill)",
                    enable_pressure_regulation=True,
                    return_head=True,
                ),
            )
        )
    remaining_result, fully_calibrated = joined_remaining_calibrations_assertion(
        context,
        case=case,
        calibration_evidence=remaining_evidence,
    )
    runtime.add_assertion(remaining_result)
    runtime.observations["m13_lifecycle"]["remaining_calibrations"] = dict(
        remaining_result.evidence
    )

    calibrations_by_stock = {row.stock_id: row for row in case.calibrations}
    cumulative = 0
    pass_specs: list[PrecalibratedStockPassSpec] = []
    for execution_pass in case.execution_passes:
        cumulative += execution_pass.expected_intents
        calibration = calibrations_by_stock[execution_pass.stock_id]
        pass_specs.append(
            PrecalibratedStockPassSpec(
                stock_id=execution_pass.stock_id,
                printer_head_id=calibration.printer_head_id,
                pulse_width_us=calibration.print_pulse_width_us,
                pressure_psi=2.0,
                frequency_hz=100,
                initial_volume_uL=100.0,
                expected_volume_nL=float(calibration.droplet_volume_nL),
                expected_completion_count=cumulative,
                expected_plan_state=(
                    "completed"
                    if execution_pass.order == len(case.execution_passes)
                    else "active"
                ),
                completed_milestone=f"m13_pass_{execution_pass.order}_complete",
                start_dialog_titles=(
                    ("Start Print Array", "Evaporation Plate Dock Check")
                    if execution_pass.order == 1
                    else ("Start Print Array",)
                ),
                return_head=True,
                capture_completed_milestone=False,
            )
        )
    def after_m13_pass(
        current: JourneyRuntime,
        index: int,
        _spec: PrecalibratedStockPassSpec,
    ) -> None:
        if sequence.role != "illegal_progress_lock_recovery_terminal" or index != 0:
            return
        for operation_id, case_id in (
            (
                "editor.attempt_progressed_edit_via_ui",
                "active_execution_edit_rejected",
            ),
            (
                "calibration.attempt_progressed_apply_via_ui",
                "progressed_stock_recalibration_rejected",
            ),
            (
                "array.start_while_active_via_ui",
                "start_while_active_rejected",
            ),
            (
                "head.attempt_unsafe_exchange_via_ui",
                "head_exchange_at_invalid_boundary_rejected",
            ),
        ):
            _m13_run_preflight_rejection(
                current,
                operation_id=operation_id,
                case_id=case_id,
                workflow_state="progressed_locked",
            )

    run_precalibrated_stock_passes(
        runtime,
        tuple(pass_specs),
        after_pass=after_m13_pass,
    )
    terminal_counts = capture_count_snapshot(context)
    runtime.restore_all()
    session_2_observer = runtime.observations["m13_session_2_execution_snapshot"]
    _run_completed_terminal_reload(runtime, expected_name=case.editor.experiment_name)
    terminal_result = joined_terminal_execution_assertion(
        context,
        case=case,
        terminal_counts=terminal_counts,
        terminal_reload=runtime.observations["completed_terminal_reload"],
        observer=session_2_observer,
        first_session_observer=first_observer,
        pass_boundaries=runtime.observations["pass_boundaries"],
        starvation_events=runtime.observations["starvation_events"],
        application_sessions=runtime.harness.application_sessions,
    )
    runtime.add_assertion(terminal_result)
    runtime.observations["m13_lifecycle"]["terminal"] = dict(
        terminal_result.evidence
    )
    if sequence.role.startswith("legal_"):
        final_sequence_result = m13_legal_sequence_assertion(
            context,
            sequence=sequence,
            case=case,
            application_sessions=runtime.harness.application_sessions,
        )
    else:
        final_sequence_result = m13_illegal_recovery_sequence_assertion(
            context,
            sequence=sequence,
            case=case,
            rejection_evidence=runtime.observations["m13_rejections"],
            application_sessions=runtime.harness.application_sessions,
        )
    runtime.add_assertion(final_sequence_result)


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


def _exploration_body(runtime: JourneyRuntime) -> None:
    fixture = runtime.fixture
    experiment = fixture["experiment"]
    exploration = dict(fixture["exploration"])
    sequence = dict(exploration["sequence"])
    steps = [dict(step) for step in sequence["steps"]]
    modal_steps = [
        step
        for step in steps
        if step["action_id"] != "experiment.load_authoritative_via_ui"
    ]
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
    action_start = len(runtime.context.action_results)
    driver_evidence = run_prepared_editor_sequence(
        runtime,
        _editor_revision_spec(fixture),
        sequence_steps=modal_steps,
        intermediate_tolerance_nl=float(
            exploration["intermediate_printed_volume_tolerance_nL"]
        ),
    )
    _revision_results, refinalized = editor_prepared_revision_assertions(
        runtime.context,
        fixture=fixture,
        initial_snapshot=initial,
        action_start=action_start,
        action_end=len(runtime.context.action_results),
    )
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
    loader_evidence = {**dict(loader_evidence), "activation_performed": False}
    capture_milestone(
        runtime.context,
        "reloaded",
        evidence={
            key: loader_evidence[key]
            for key in ("plan_state", "eligibility_status")
        },
    )
    plan_result, rejection_result, recovery_result = (
        editor_sequence_exploration_assertions(
            runtime.context,
            exploration=exploration,
            driver_evidence=driver_evidence,
            refinalized_evidence=refinalized,
            loader_evidence=loader_evidence,
            action_start=action_start,
            action_end=len(runtime.context.action_results),
        )
    )
    for result in (plan_result, rejection_result, recovery_result):
        runtime.add_assertion(result)
    runtime.observations["sequence_exploration"] = {
        "campaign_id": exploration["campaign_id"],
        "generator_version": exploration["generator_version"],
        "catalog_sha256": exploration["catalog_sha256"],
        "sequence_sha256": exploration["sequence_sha256"],
        "sequence": sequence,
        "expected_outcomes": [step["expected_outcome"] for step in steps],
        "observed_transitions": list(driver_evidence["observed_transitions"])
        + [dict(plan_result.evidence["observed_transitions"][-1])],
        "rejection_evidence": list(driver_evidence["rejections"]),
        "before": dict(initial["before"]),
        "after": {
            key: refinalized.get(key)
            for key in (
                "experiment_dir",
                "plan_id",
                "plan_revision",
                "plan_state",
                "eligibility_status",
                "well_ids",
                "file_sha256",
                "audit_rows",
            )
        },
        "terminal_recovery": dict(recovery_result.evidence),
        "action_cap": int(exploration["maximum_actions"]),
        "projected_terminal_action_count": plan_result.evidence[
            "projected_terminal_action_count"
        ],
        "exact_replay": replay_command(
            runtime.harness,
            EXPLORATION_WORKLOAD_ID,
            selector_args=(
                "--exploration",
                EXPLORATION_WORKLOAD_ID,
                "--sequence",
                sequence["sequence_id"],
            ),
        ),
    }
    capture_milestone(
        runtime.context,
        "validated",
        evidence={
            "sequence_id": sequence["sequence_id"],
            "sequence_class": sequence["sequence_class"],
            "plan_state": loader_evidence["plan_state"],
            "eligibility_status": loader_evidence["eligibility_status"],
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


def _add_dispense_count_assertion(
    runtime: JourneyRuntime,
    *,
    matrix_case: bool,
    matrix_terminal: str,
    observer: Mapping[str, Any],
) -> None:
    if not (
        (matrix_case and matrix_terminal == "completed")
        or (
            not matrix_case
            and runtime.definition.registry_id == MIXED_MODE_WORKLOAD_ID
        )
    ):
        return
    runtime.add_assertion(
        dispense_counts_reconciled_assertion(
            runtime.context,
            prepared_snapshot=runtime.observations["prepared_count_snapshot"],
            calibration_transitions=runtime.observations.get(
                "calibration_count_transitions", []
            ),
            observer=observer,
            count_oracle=(
                runtime.fixture.get("lifecycle", {}).get(
                    "dispense_count_oracle"
                )
            ),
        )
    )


def _run_completed_terminal_reload(
    runtime: JourneyRuntime,
    *,
    expected_name: str | None = None,
) -> None:
    """Rotate sessions and display a completed bundle without activation."""

    from tools.virtual_workflows.authoritative_evidence import (
        compare_directories,
        snapshot_directory,
    )

    context = runtime.context
    before = capture_authoritative_bundle(context)
    experiment_dir = Path(before.experiment_dir)
    first_close = runtime.harness.close_application_session()["evidence"]
    after_close = compare_directories(
        before.directory, snapshot_directory(experiment_dir)
    ).to_dict()
    second_launch = runtime.harness.reopen_application_session()["evidence"]
    loader = ExperimentLoaderDriver(context).inspect_completed_execution(
        experiment_dir,
        expected_name=str(
            expected_name
            or runtime.fixture.get("fixture_id")
            or runtime.fixture.get("case_id")
            or ""
        ),
    )
    after = capture_authoritative_bundle(context)
    after_counts = capture_count_snapshot(context)
    after_reload = compare_directories(
        before.directory, snapshot_directory(experiment_dir)
    ).to_dict()
    assertion = completed_terminal_reload_assertion(
        before=before,
        after=after,
        first_close=first_close,
        second_launch=second_launch,
        loader=loader,
        directory_comparisons={
            "after_close": after_close,
            "after_reload": after_reload,
        },
    )
    runtime.add_assertion(assertion)
    if assertion.decision != "pass":
        raise RuntimeError(
            "completed terminal reload was not exact: "
            f"{assertion.evidence.get('failed_checks')}"
        )
    runtime.observations["completed_terminal_reload"] = {
        "before": before,
        "after": after,
        "after_counts": after_counts,
        "first_close": first_close,
        "second_launch": second_launch,
        "loader": loader,
        "directory_comparisons": {
            "after_close": after_close,
            "after_reload": after_reload,
        },
    }


def _install_fixture_print_profiles(context: Any, fixture: Mapping[str, Any]) -> None:
    existing = {
        str(item.get("id") or "")
        for item in context.model.print_profiles
        if isinstance(item, Mapping)
    }
    for stock in fixture["stocks"]:
        profile = stock.get("calibration_print_profile")
        if profile and str(profile["id"]) not in existing:
            context.model.print_profiles.append(dict(profile))
            existing.add(str(profile["id"]))


def _install_multi_observer(runtime: JourneyRuntime) -> None:
    context = runtime.context
    observer = ExecutionObserver(
        context,
        experiment_dir=Path(context.experiment_model.experiment_dir_path),
        completed_count=lambda: len(runtime.observations["completed_wells"]),
        pass_context=lambda: _current_pass_context(runtime),
    )
    runtime.register_restorable("execution", observer)
    observer.install()
    _install_starvation_observer(runtime)


def _add_requantization_boundary_assertions(
    runtime: JourneyRuntime,
    *,
    observer: Mapping[str, Any],
) -> None:
    fixture = runtime.fixture
    rejection_oracle = dict(
        fixture.get("lifecycle", {}).get("calibration_rejection_oracle") or {}
    )
    if rejection_oracle:
        runtime.add_assertion(
            calibration_apply_fail_closed_assertion(
                runtime.context,
                boundary=runtime.observations.get(
                    "calibration_rejection_boundary", {}
                ),
                observer=observer,
                oracle=rejection_oracle,
                action_results=runtime.context.action_results,
                pass_boundaries=runtime.observations["pass_boundaries"],
                completed_wells=runtime.observations["completed_wells"],
            )
        )
    isolation_oracle = dict(
        fixture.get("lifecycle", {}).get("two_reagent_isolation_oracle") or {}
    )
    if isolation_oracle:
        runtime.add_assertion(
            two_reagent_isolation_assertion(
                runtime.context,
                boundary=runtime.observations.get(
                    "two_reagent_isolation_boundary", {}
                ),
                observer=observer,
                oracle=isolation_oracle,
            )
        )


def _multi_body(runtime: JourneyRuntime) -> None:
    context, fixture = runtime.context, runtime.fixture
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
    _install_fixture_print_profiles(context, fixture)
    run_editor_preparation(
        runtime,
        EditorPreparationSpec(_editor_specification(fixture, expected_wells)),
    )
    prepared = multi_stock_prepared_assertion(
        context,
        expected_well_ids=expected_wells,
        expected_stock_ids=expected_stock_ids,
        require_stock_order=fixture.get("lifecycle", {}).get("kind")
        != "parameterized_calibration_matrix_case",
        expected_target_dispenses=_prepared_target_dispenses(fixture),
    )
    if prepared.decision != "pass":
        raise RuntimeError(f"prepared multi-stock bundle was invalid: {prepared.evidence}")
    runtime.observations["prepared_count_snapshot"] = capture_count_snapshot(context)
    pass_specs = _multi_passes(runtime)
    runtime.observations["expected_pulse_widths_us"] = tuple(
        spec.expected_applied_pulse_width_us or spec.pulse_width_us
        for spec in pass_specs
    )
    runtime.observations["expected_volumes_nL"] = tuple(spec.expected_volume_nL for spec in pass_specs)
    runtime.run_steps((head_identity_step(pass_specs),))
    if profile is None:
        _install_multi_observer(runtime)
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
    matrix_case = fixture.get("lifecycle", {}).get("kind") == "parameterized_calibration_matrix_case"
    matrix_terminal = str(
        fixture.get("lifecycle", {}).get("case", {}).get("expected_terminal") or ""
    )
    if not matrix_case or matrix_terminal == "completed":
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
    count_oracle = fixture.get("lifecycle", {}).get("dispense_count_oracle") or {}
    if bool(count_oracle.get("require_terminal_reload")):
        _run_completed_terminal_reload(runtime)
    _add_dispense_count_assertion(runtime, matrix_case=matrix_case, matrix_terminal=matrix_terminal, observer=snapshot)
    _add_requantization_boundary_assertions(runtime, observer=snapshot)
    if matrix_case:
        for assertion in matrix_case_assertions(
            context,
            fixture=fixture,
            completed_wells=runtime.observations["completed_wells"],
            pass_boundaries=runtime.observations["pass_boundaries"],
            head_staging=runtime.observations["head_staging"],
            manual_refuel_checks=runtime.observations.get(
                "manual_refuel_checks", []
            ),
            action_results=context.action_results,
            block_evidence=runtime.observations.get("matrix_block"),
        ):
            runtime.add_assertion(assertion)
    elif runtime.definition.registry_id == MIXED_MODE_WORKLOAD_ID:
        for assertion in mixed_mode_lifecycle_assertions(
            context,
            fixture=fixture,
            manual_refuel_checks=runtime.observations.get(
                "manual_refuel_checks", []
            ),
            action_results=context.action_results,
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
    current = runtime.observations.get("current_pass", {})
    if int(current.get("index", -1)) < 0:
        return None
    return {
        "pass_index": int(current["index"]) + 1,
        "stock_id": current.get("stock_id"),
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
            "post_completion_diagnostics": dict(
                runtime.observations.get("post_completion_diagnostics") or {}
            ),
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
                "same_session_completed_projection": dict(
                    runtime.observations.get(
                        "same_session_completed_projection"
                    )
                    or {}
                ),
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


def _legacy_read_only_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    loader = dict(runtime.observations.get("legacy_loader") or {})
    analysis = dict(runtime.observations.get("legacy_analysis") or {})
    editable_copy = dict(
        runtime.observations.get("legacy_editable_copy") or {}
    )
    source = dict(runtime.observations.get("legacy_source") or {})
    return ComposedReportPayload(
        workload={
            **_base_workload(runtime),
            "experiment_name": runtime.fixture["experiment_name"],
            "plate_name": runtime.fixture["plate_name"],
            "well_ids": ["A1", "A2"],
            "expected_completion_count": 1,
            "speed_multiplier": runtime.harness.config.speed_multiplier,
            "timeout_seconds": runtime.harness.config.timeout_seconds,
        },
        workflow_values={
            "loader": loader,
            "analysis": analysis,
            "editable_copy": editable_copy,
            "cleanup_results": [dict(teardown)],
        },
        persistence={
            "status": "measured",
            "values": source,
        },
        limitations=(
            "The workflow validates application behavior with simulated hardware; no physical commands are permitted.",
        ),
    )


def _experiment_design_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    return build_editor_lifecycle_payload(
        runtime,
        teardown,
        experiment_design_report_spec(
            runtime,
            base_workload=_base_workload(runtime),
            required_assertion_ids=runtime.definition.required_assertion_ids,
        ),
    )


def _editor_safeguard_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    lifecycle = dict(runtime.fixture["lifecycle"])
    case = dict(lifecycle["case"])
    observed = dict(runtime.observations.get("editor_safeguard") or {})
    return build_editor_lifecycle_payload(
        runtime,
        teardown,
        EditorLifecycleReportSpec(
            workload={
                **_base_workload(runtime),
                "case_id": case["case_id"],
                "experiment_name": runtime.fixture["experiment"]["name"],
                "plate_name": runtime.fixture["experiment"]["plate_name"],
                "expected_reaction_count": 0,
                "well_ids": [],
                "expected_editor_finalization_operations": 1,
                "speed_multiplier": runtime.harness.config.speed_multiplier,
                "timeout_seconds": runtime.harness.config.timeout_seconds,
            },
            required_assertion_ids=EDITOR_SAFEGUARD_REQUIRED_ASSERTIONS,
            persistence_values={
                "matrix_case": {
                    "matrix_id": lifecycle["matrix_id"],
                    "catalog_sha256": lifecycle["catalog_sha256"],
                    "case_sha256": lifecycle["case_sha256"],
                    "case": case,
                    "parameters": {
                        "configured": dict(
                            observed.get("driver", {}).get("configured") or {}
                        )
                    },
                    "outcome": dict(observed.get("oracle") or {}),
                },
                "safeguard_boundary": dict(observed.get("oracle") or {}),
            },
            limitations=(
                "This compact negative case stops immediately after its declared editor rejection.",
                "The simulator validates application-side UI, state, persistence, and dispatch boundaries; it does not validate firmware or physical hardware.",
                "All setup data belongs to the isolated scenario session; no user experiment directory is modified.",
            ),
        ),
    )


def _execution_preflight_safeguard_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    lifecycle = dict(runtime.fixture["lifecycle"])
    case = dict(lifecycle["case"])
    observed = dict(
        runtime.observations.get("execution_preflight_safeguard") or {}
    )
    return build_editor_lifecycle_payload(
        runtime,
        teardown,
        EditorLifecycleReportSpec(
            workload={
                **_base_workload(runtime),
                "case_id": case["case_id"],
                "experiment_name": runtime.fixture["experiment"]["name"],
                "plate_name": runtime.fixture["experiment"]["plate_name"],
                "expected_reaction_count": 0,
                "well_ids": [],
                "expected_editor_finalization_operations": 0,
                "speed_multiplier": runtime.harness.config.speed_multiplier,
                "timeout_seconds": runtime.harness.config.timeout_seconds,
            },
            required_assertion_ids=(
                EXECUTION_PREFLIGHT_SAFEGUARD_REQUIRED_ASSERTIONS
            ),
            persistence_values={
                "matrix_case": {
                    "matrix_id": lifecycle["matrix_id"],
                    "catalog_sha256": lifecycle["catalog_sha256"],
                    "case_sha256": lifecycle["case_sha256"],
                    "case": case,
                    "outcome": dict(observed.get("oracle") or {}),
                },
                "safeguard_boundary": dict(observed.get("oracle") or {}),
                "operator_ui": dict(observed.get("driver", {}).get("ui") or {}),
            },
            limitations=(
                "Each compact preflight case stops immediately after its declared operator-visible boundary.",
                "The cases validate application-side UI, typed state, persistence, and dispatch boundaries in host SIL; they do not validate firmware or physical hardware.",
                "All setup state belongs to the isolated scenario session; no user experiment directory is modified.",
            ),
        ),
    )


def _persistence_safeguard_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    lifecycle = dict(runtime.fixture["lifecycle"])
    case = dict(lifecycle["case"])
    observed = dict(runtime.observations.get("persistence_safeguard") or {})
    driver = dict(observed.get("driver") or {})
    return build_editor_lifecycle_payload(
        runtime,
        teardown,
        EditorLifecycleReportSpec(
            workload={
                **_base_workload(runtime),
                "case_id": case["case_id"],
                "experiment_name": runtime.fixture["experiment"]["name"],
                "plate_name": runtime.fixture["experiment"]["plate_name"],
                "expected_reaction_count": 0,
                "well_ids": [],
                "expected_editor_finalization_operations": 0,
                "speed_multiplier": runtime.harness.config.speed_multiplier,
                "timeout_seconds": runtime.harness.config.timeout_seconds,
            },
            required_assertion_ids=PERSISTENCE_SAFEGUARD_REQUIRED_ASSERTIONS,
            persistence_values={
                "matrix_case": {
                    "matrix_id": lifecycle["matrix_id"],
                    "catalog_sha256": lifecycle["catalog_sha256"],
                    "case_sha256": lifecycle["case_sha256"],
                    "case": case,
                    "outcome": dict(observed.get("oracle") or {}),
                },
                "safeguard_boundary": dict(observed.get("oracle") or {}),
                "prelaunch_fault": dict(observed.get("prelaunch") or {}),
                "persistence_classification": dict(driver.get("classification") or {}),
                "operator_ui": dict(driver.get("ui") or {}),
            },
            limitations=(
                "Each fault changes one file in a retained test-owned copy before application launch and stops after locked activation evidence.",
                "Missing-file errors retain the exact OS path in raw UI evidence and use a literal portable classification message in the shared typed oracle.",
                "The host SIL validates application persistence and UI boundaries; it does not validate firmware or physical hardware.",
            ),
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


def _exploration_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    exploration = dict(runtime.fixture["exploration"])
    sequence = dict(exploration["sequence"])
    evidence = _assertion_evidence(runtime)
    payload = build_editor_lifecycle_payload(
        runtime,
        teardown,
        EditorLifecycleReportSpec(
            workload={
                **_base_workload(runtime),
                "campaign_id": exploration["campaign_id"],
                "generator_version": exploration["generator_version"],
                "catalog_sha256": exploration["catalog_sha256"],
                "sequence_id": sequence["sequence_id"],
                "sequence_sha256": exploration["sequence_sha256"],
                "sequence_class": sequence["sequence_class"],
                "operation_count": len(sequence["steps"]),
                "maximum_action_count": exploration["maximum_actions"],
                "speed_multiplier": runtime.harness.config.speed_multiplier,
                "timeout_seconds": runtime.harness.config.timeout_seconds,
            },
            required_assertion_ids=EXPLORATION_REQUIRED_ASSERTIONS,
            persistence_values={
                "prepared_bundle": dict(
                    runtime.observations.get("prepared_revision_initial", {})
                    .get("prepared_bundle", {})
                ),
                "refinalized_bundle": dict(
                    runtime.observations.get("refinalized_bundle") or {}
                ),
                "rejection_safety": evidence.get(
                    "exploration.expected_rejection_safe", {}
                ),
            },
            limitations=(
                "This bounded campaign explores only the prepared-design editor activation guard.",
                "It does not connect the simulated machine, activate execution, print, or claim hardware coverage.",
                "Generated plan IDs, timestamps, paths, and identity-bearing artifact hashes may differ across replay.",
            ),
        ),
    )
    return replace(
        payload,
        workflow_values={
            **dict(payload.workflow_values),
            "sequence_exploration": dict(
                runtime.observations.get("sequence_exploration") or {}
            ),
        },
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
    matrix_case = fixture.get("lifecycle", {}).get("kind") == (
        "parameterized_calibration_matrix_case"
    )
    mixed_mode = runtime.definition.registry_id == MIXED_MODE_WORKLOAD_ID and not matrix_case
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
            "array_passes": int(
                fixture["workload"].get("array_passes", stock_count)
            ),
            "target_dispenses_per_well": int(
                fixture["workload"].get(
                    "target_dispenses_per_stock_per_well", 1
                )
            ),
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
                "queue_drained_at_terminal": bool(
                    multi.get("terminal", {}).get(
                        "queue_drained",
                        runtime.context.machine.check_if_all_completed(),
                    )
                ),
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
                **(
                    {
                        "dispense_count_evidence": evidence.get(
                            "execution.dispense_counts_reconciled", {}
                        )
                    }
                    if "execution.dispense_counts_reconciled" in evidence
                    else {}
                ),
                **(
                    {
                        "calibration_rejection_evidence": evidence.get(
                            "execution.calibration_apply_fail_closed", {}
                        )
                    }
                    if "execution.calibration_apply_fail_closed" in evidence
                    else {}
                ),
                **(
                    {
                        "two_reagent_isolation": evidence.get(
                            "execution.two_reagent_isolation_exact", {}
                        )
                    }
                    if "execution.two_reagent_isolation_exact" in evidence
                    else {}
                ),
                **(
                    {
                        "mixed_mode_lifecycle": {
                            "calibrations": evidence.get(
                                "execution.mixed_mode_calibrations_valid", {}
                            ),
                            "manual_refuel": evidence.get(
                                "execution.stream_manual_refuel_passed", {}
                            ),
                        }
                    }
                    if mixed_mode else {}
                ),
                **(
                    {
                        "matrix_case": {
                            "matrix_id": fixture["lifecycle"]["matrix_id"],
                            "catalog_sha256": fixture["lifecycle"]["catalog_sha256"],
                            "case_sha256": fixture["lifecycle"]["case_sha256"],
                            "case": dict(fixture["lifecycle"]["case"]),
                            "profile": dict(fixture["lifecycle"]["profile"]),
                            "parameters": evidence.get(
                                "execution.matrix_case_parameters_applied", {}
                            ),
                            "outcome": evidence.get(
                                "execution.matrix_case_outcome_valid", {}
                            ),
                        }
                    }
                    if matrix_case else {}
                ),
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
    status = "measured" if passed else "partial"
    intent_reconciliation = {
        "completed_count": terminal.get("intent_count"),
        "discarded_count": terminal.get("discarded_intent_count"),
        "begin_count": terminal.get("begin_intent_count"),
        "discard_batch_count": terminal.get("discard_batch_count"),
    }
    return ComposedReportPayload(
        workload={**_single_stock_workload(runtime)},
        workflow_status=status,
        workflow_values={
            "expected_well_count": len(expected),
            "completed_well_count": len(completed),
            "expected_stock_well_completion_count": len(expected),
            "completed_stock_well_count": len(completed),
            "completed_well_ids": list(completed),
            "well_update_count": len(completed),
            "array_states": list(runtime.context.array_states),
            "array_complete_count": len(
                observed.get("array_completions", [])
            ),
            "cleanup_results": [dict(teardown)],
        },
        queue={
            "status": status,
            "values": {
                "unexpected_starvation_count": len(
                    observed.get("starvation_events", [])
                ),
                "queue_drained_at_terminal": decisions.get(
                    "execution.terminal_bundle_valid"
                )
                == "pass",
            },
        },
        persistence={
            "status": status,
            "values": {
                "assertion_decisions": decisions,
                "soft_stop_resume": {
                    "request": request,
                    "stopped_checkpoint": paused,
                    "quiescence": quiescence,
                    "intent_reconciliation": intent_reconciliation,
                },
                "paused_boundary": paused,
                "quiescence": quiescence,
                "intent_durability": evidence.get(
                    "execution.intent_durability_exact", {}
                ),
                "terminal": terminal,
                "terminal_plan_state": terminal.get("terminal_plan_state"),
                "stock_well_completion_count": terminal.get(
                    "stock_well_completion_count"
                ),
                "intent_count": len(lifecycle.get("completions", [])),
                "discard_batch_count": len(
                    lifecycle.get("discard_batches", [])
                ),
                **_observer_persistence(observer),
            },
        },
        limitations=(
            "The soft-stop lifecycle uses an in-process simulator and normal Qt controls; it does not validate physical stopping distance.",
            "The simulator does not validate firmware, protocol framing, motion, pressure response, cameras, balance behavior, or droplet quality.",
            "Generated identities, timestamps, durations, paths, and calibration identities are not expected to be byte-identical across replay.",
        ),
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


def _randomized_calibration_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    case = JOINED_INTERACTION_CASE
    decisions = _decisions(runtime)
    evidence = _assertion_evidence(runtime)
    required = runtime.definition.required_assertion_ids
    passed = all(decisions.get(assertion_id) == "pass" for assertion_id in required)
    status = "measured" if passed else "partial"
    terminal = evidence.get("execution.randomized_calibration_terminal_exact", {})
    lifecycle = dict(
        runtime.observations.get("randomized_calibration_lifecycle") or {}
    )
    completed = list(runtime.observations.get("completed_wells") or ())
    return ComposedReportPayload(
        workload={
            **_base_workload(runtime),
            "case_id": case.case_id,
            "case_sha256": case.sha256(),
            "count_oracle_sha256": case.count_oracle_sha256(),
            "joined_fixture_sha256": joined_fixture_sha256(),
            "source_case_id": case.source.case_id,
            "source_case_sha256": case.source.case_sha256,
            "source_catalog_sha256": case.source.catalog_sha256,
            "source_assignment_sha256": case.source.assignment_sha256,
            "source_reaction_multiset_sha256": case.source.reaction_multiset_sha256,
            "design_randomization_seed": case.editor.random_seed,
            "plate_name": case.editor.plate_name,
            "well_ids": list(case.editor.selected_well_ids),
            "stock_ids": [row.stock_id for row in case.stocks],
            "stock_count": len(case.stocks),
            "array_passes": len(case.execution_passes),
            "expected_completion_count": case.terminal.expected_completed_wells,
            "expected_intent_count": case.terminal.expected_intents,
            "expected_droplets": case.terminal.expected_droplets,
            "action_cap": case.qualification.action_cap,
            "speed_multiplier": runtime.harness.config.speed_multiplier,
            "timeout_seconds": runtime.harness.config.timeout_seconds,
        },
        workflow_status=status,
        workflow_values={
            "expected_stock_well_completion_count": case.terminal.expected_completed_wells,
            "completed_stock_well_count": len(completed),
            "completed_well_ids": completed,
            "array_complete_count": len(runtime.observations.get("array_completions") or ()),
            "application_sessions": [dict(row) for row in runtime.harness.application_sessions],
            "cleanup_results": [dict(teardown)],
            "action_count": len(runtime.context.action_results),
            "action_cap": case.qualification.action_cap,
        },
        queue={
            "status": status,
            "values": {
                "unexpected_starvation_count": len(runtime.observations.get("starvation_events") or ()),
                "queue_drained_at_terminal": bool((terminal.get("checks") or {}).get("session_three_zero_dispatch")),
                "simulator_dispense_overflow_count": int(terminal.get("simulator_dispense_overflow_count", 0) or 0),
            },
        },
        persistence={
            "status": status,
            "values": {
                "assertion_decisions": decisions,
                "randomized_calibration_lifecycle": lifecycle,
                "terminal": terminal,
                "case_contract": {
                    "case_id": case.case_id,
                    "case_sha256": case.sha256(),
                    "count_oracle_sha256": case.count_oracle_sha256(),
                    "fixture_sha256": joined_fixture_sha256(),
                },
            },
        },
        limitations=(
            "The three application compositions share one in-process QApplication and retained SIL root; direct CLI and suite runs provide fresh operating-system processes.",
            "The simulator verifies application-side intent, persistence, and DISPENSE semantics, not firmware or protocol behavior.",
            "No physical motion, pressure response, calibration quality, camera, balance, collision, or droplet-quality claim is made.",
            "Generated plan IDs, record IDs, timestamps, paths, and command sequence identities may differ across replay.",
        ),
    )


def _m13_legal_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    from tools.virtual_workflows.exploration_m13 import (
        CAMPAIGN_ID,
        GENERATOR_VERSION,
        campaign_sha256,
        catalog_sha256,
        resolve_plan,
        sequence_sha256,
    )

    sequence = runtime.observations["m13_sequence"]
    case = runtime.observations["m13_case"]
    if sequence.seed_tier == "frozen":
        plan = resolve_plan(
            sequence_id=sequence.sequence_id,
            timeout_seconds=runtime.harness.config.timeout_seconds,
            execution_authorized=False,
        )
        sequence_row = plan["sequences"][0]
    else:
        sequence_row = {
            "order": 1,
            "sequence": sequence.normalized(),
            "sequence_sha256": sequence_sha256(sequence),
        }
    decisions = _decisions(runtime)
    evidence = _assertion_evidence(runtime)
    passed = all(
        decisions.get(assertion_id) == "pass"
        for assertion_id in runtime.definition.required_assertion_ids
        if assertion_id != "artifacts.required_present"
    )
    status = "measured" if passed else "partial"
    terminal = evidence.get("execution.randomized_calibration_terminal_exact", {})
    semantic = evidence.get("exploration.m13_legal_sequence_exact", {}) or evidence.get(
        "exploration.m13_illegal_recovery_exact", {}
    )
    return ComposedReportPayload(
        workload={
            **_base_workload(runtime),
            "campaign_id": CAMPAIGN_ID,
            "generator_version": GENERATOR_VERSION,
            "catalog_sha256": catalog_sha256(),
            "campaign_sha256": campaign_sha256(),
            "sequence_id": sequence.sequence_id,
            "sequence_sha256": sequence_row["sequence_sha256"],
            "case_id": case.case_id,
            "case_sha256": case.sha256(),
            "reaction_count": 4,
            "stock_count": 2,
            "expected_intent_count": 8,
            "expected_droplets": 44,
            "action_cap": 80,
            "screenshot_cap": 4,
            "speed_multiplier": runtime.harness.config.speed_multiplier,
            "timeout_seconds": runtime.harness.config.timeout_seconds,
        },
        workflow_status=status,
        workflow_values={
            "sequence_exploration": {
                "campaign_id": CAMPAIGN_ID,
                "generator_version": GENERATOR_VERSION,
                "catalog_sha256": catalog_sha256(),
                "campaign_sha256": campaign_sha256(),
                "seed_tier": sequence.seed_tier,
                "sequence": sequence_row["sequence"],
                "sequence_sha256": sequence_row["sequence_sha256"],
                "reached_transitions": list(sequence_row["sequence"]["steps"]),
                "semantic_oracle": dict(semantic),
            },
            "expected_stock_well_completion_count": 8,
            "completed_stock_well_count": len(
                runtime.observations.get("completed_wells") or ()
            ),
            "application_sessions": [
                dict(row) for row in runtime.harness.application_sessions
            ],
            "cleanup_results": [dict(teardown)],
            "action_count": len(runtime.context.action_results),
            "action_cap": 80,
            "screenshots": sorted(runtime.context.screenshots),
            "screenshot_cap": 4,
        },
        queue={
            "status": status,
            "values": {
                "queue_drained_at_terminal": bool(
                    (terminal.get("checks") or {}).get(
                        "session_three_zero_dispatch"
                    )
                ),
                "simulator_dispense_overflow_count": int(
                    terminal.get("simulator_dispense_overflow_count", 0) or 0
                ),
            },
        },
        persistence={
            "status": status,
            "values": {
                "assertion_decisions": decisions,
                "m13_lifecycle": dict(runtime.observations["m13_lifecycle"]),
                "terminal": terminal,
                "case_contract": {
                    "case_id": case.case_id,
                    "case_sha256": case.sha256(),
                    "design_case_sha256": case.design_case.sha256(),
                },
            },
        },
        limitations=(
            "Milestone 13 generated exploration supplements and does not replace deterministic Milestone 9-12 evidence.",
            "The simulator verifies application-side intent, persistence, and DISPENSE semantics, not firmware or protocol behavior.",
            "No physical motion, pressure response, calibration quality, camera, balance, collision, or droplet-quality claim is made.",
            "Generated runtime IDs, timestamps, paths, and command sequence identities may differ across exact replay.",
        ),
    )


def _optimizer_360_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    case = OPTIMIZER_360_CASE
    decisions = _decisions(runtime)
    evidence = _assertion_evidence(runtime)
    passed = all(
        decisions.get(assertion_id) == "pass"
        for assertion_id in runtime.definition.required_assertion_ids
    )
    status = "measured" if passed else "partial"
    terminal = evidence.get("execution.randomized_calibration_terminal_exact", {})
    lifecycle = dict(
        runtime.observations.get("optimizer_360_calibration_lifecycle") or {}
    )
    completed = list(runtime.observations.get("completed_wells") or ())
    return ComposedReportPayload(
        workload={
            **_base_workload(runtime),
            "case_id": case.case_id,
            "case_sha256": case.sha256(),
            "fixture_sha256": EXPECTED_FIXTURE_SHA256,
            "count_oracle_sha256": EXPECTED_COUNT_ORACLE_SHA256,
            "requested_reaction_multiset_sha256": (
                EXPECTED_REACTION_MULTISET_SHA256
            ),
            "achieved_reaction_multiset_sha256": (
                EXPECTED_ACHIEVED_REACTION_MULTISET_SHA256
            ),
            "assignment_sha256": EXPECTED_ASSIGNMENT_SHA256,
            "design_randomization_seed": case.editor.random_seed,
            "plate_name": case.editor.plate_name,
            "well_ids": list(case.editor.selected_well_ids),
            "excluded_well_ids": list(case.editor.excluded_well_ids),
            "stock_ids": [row.stock_id for row in case.stocks],
            "stock_count": len(case.stocks),
            "array_passes": len(case.execution_passes),
            "expected_completion_count": case.terminal.expected_completed_wells,
            "expected_intent_count": case.terminal.expected_intents,
            "expected_droplets": case.terminal.expected_droplets,
            "action_cap": case.qualification.action_cap,
            "simulator_evidence_cap": case.qualification.simulator_evidence_cap,
            "speed_multiplier": runtime.harness.config.speed_multiplier,
            "timeout_seconds": runtime.harness.config.timeout_seconds,
        },
        workflow_status=status,
        workflow_values={
            "expected_stock_well_completion_count": (
                case.terminal.expected_completed_wells
            ),
            "completed_stock_well_count": len(completed),
            "completed_well_ids": completed,
            "array_complete_count": len(
                runtime.observations.get("array_completions") or ()
            ),
            "application_sessions": [
                dict(row) for row in runtime.harness.application_sessions
            ],
            "cleanup_results": [dict(teardown)],
            "action_count": len(runtime.context.action_results),
            "action_cap": case.qualification.action_cap,
        },
        queue={
            "status": status,
            "values": {
                "unexpected_starvation_count": len(
                    runtime.observations.get("starvation_events") or ()
                ),
                "queue_drained_at_terminal": bool(
                    (terminal.get("checks") or {}).get(
                        "session_three_zero_dispatch"
                    )
                ),
                "simulator_dispense_overflow_count": int(
                    terminal.get("simulator_dispense_overflow_count", 0) or 0
                ),
            },
        },
        persistence={
            "status": status,
            "values": {
                "assertion_decisions": decisions,
                "optimizer_360_calibration_lifecycle": lifecycle,
                "terminal": terminal,
                "case_contract": {
                    "case_id": case.case_id,
                    "case_sha256": case.sha256(),
                    "fixture_sha256": EXPECTED_FIXTURE_SHA256,
                    "count_oracle_sha256": EXPECTED_COUNT_ORACLE_SHA256,
                },
            },
        },
        limitations=(
            "The three application compositions share one in-process QApplication; direct and replay invocations each start in a fresh operating-system process.",
            "The simulator verifies application-side intent, persistence, and DISPENSE semantics, not firmware or protocol behavior.",
            "No physical motion, pressure response, calibration quality, camera, balance, collision, or droplet-quality claim is made.",
            "Generated plan IDs, record IDs, timestamps, paths, and command sequence identities may differ across replay.",
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


def _experiment_design_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return editor_artifacts_cleanup_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(runtime.definition.required_screenshots),
        teardown=teardown,
    )


def _editor_safeguard_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return editor_artifacts_cleanup_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(runtime.definition.required_screenshots),
        teardown=teardown,
    )


def _execution_preflight_safeguard_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return editor_artifacts_cleanup_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(runtime.definition.required_screenshots),
        teardown=teardown,
    )


def _persistence_safeguard_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return editor_artifacts_cleanup_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(runtime.definition.required_screenshots),
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


def _exploration_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return editor_artifacts_cleanup_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(runtime.definition.required_screenshots),
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


def _randomized_calibration_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return multi_stock_artifacts_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(RANDOMIZED_CALIBRATION_REQUIRED_SCREENSHOTS),
        teardown=teardown,
    )


def _m13_legal_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return multi_stock_artifacts_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(M13_LEGAL_REQUIRED_SCREENSHOTS),
        teardown=teardown,
    )


def _optimizer_360_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return multi_stock_artifacts_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(OPTIMIZER_360_REQUIRED_SCREENSHOTS),
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


def _legacy_read_only_artifact(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> Any:
    return multi_stock_artifacts_assertion(
        screenshots=runtime.context.screenshots,
        required_screenshots=set(LEGACY_READ_ONLY_REQUIRED_SCREENSHOTS),
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


def _legacy_read_only_summary(
    report: Mapping[str, Any], runtime: JourneyRuntime
) -> str:
    passed = sum(
        row["decision"] == "pass"
        for row in runtime.harness.assertion_results
    )
    return (
        "Older experiment read-only view and plate-reader analysis\n"
        f"Status: {report['classification']['status']}\n"
        f"Assertions: {passed} / {len(LEGACY_READ_ONLY_REQUIRED_ASSERTIONS)}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _experiment_design_summary(
    report: Mapping[str, Any], runtime: JourneyRuntime
) -> str:
    passed = sum(
        row["decision"] == "pass"
        for row in runtime.harness.assertion_results
    )
    case_id = runtime.fixture["lifecycle"]["case"]["case_id"]
    return (
        "Milestone 10 experiment-design matrix case\n"
        f"Case: {case_id}\n"
        f"Status: {report['classification']['status']}\n"
        f"Assertions: {passed} / {len(runtime.definition.required_assertion_ids)}\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _editor_safeguard_summary(
    report: Mapping[str, Any], runtime: JourneyRuntime
) -> str:
    passed = sum(
        row["decision"] == "pass"
        for row in runtime.harness.assertion_results
    )
    case_id = runtime.fixture["lifecycle"]["case"]["case_id"]
    return (
        "Milestone 12 editor safeguard matrix case\n"
        f"Case: {case_id}\n"
        f"Status: {report['classification']['status']}\n"
        f"Assertions: {passed} / {len(EDITOR_SAFEGUARD_REQUIRED_ASSERTIONS)}\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _execution_preflight_safeguard_summary(
    report: Mapping[str, Any], runtime: JourneyRuntime
) -> str:
    passed = sum(
        row["decision"] == "pass"
        for row in runtime.harness.assertion_results
    )
    case_id = runtime.fixture["lifecycle"]["case"]["case_id"]
    return (
        "Milestone 12 execution-preflight safeguard matrix case\n"
        f"Case: {case_id}\n"
        f"Status: {report['classification']['status']}\n"
        f"Assertions: {passed} / "
        f"{len(EXECUTION_PREFLIGHT_SAFEGUARD_REQUIRED_ASSERTIONS)}\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _persistence_safeguard_summary(
    report: Mapping[str, Any], runtime: JourneyRuntime
) -> str:
    passed = sum(
        row["decision"] == "pass"
        for row in runtime.harness.assertion_results
    )
    case_id = runtime.fixture["lifecycle"]["case"]["case_id"]
    return (
        "Milestone 12 authoritative-persistence safeguard matrix case\n"
        f"Case: {case_id}\n"
        f"Status: {report['classification']['status']}\n"
        f"Assertions: {passed} / {len(PERSISTENCE_SAFEGUARD_REQUIRED_ASSERTIONS)}\n"
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


def _exploration_summary(
    report: Mapping[str, Any], runtime: JourneyRuntime
) -> str:
    sequence = runtime.fixture["exploration"]["sequence"]
    return (
        "Milestone 8 bounded prepared-editor sequence exploration\n"
        f"Sequence: {sequence['sequence_id']} ({sequence['sequence_class']})\n"
        f"Status: {report['classification']['status']}\n"
        f"Actions: {len(runtime.context.action_results)} / "
        f"{runtime.fixture['exploration']['maximum_actions']}\n"
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
    case = dict(runtime.fixture.get("lifecycle", {}).get("case") or {})
    expected = int(
        case.get("expected_completion_count", runtime.fixture["workload"]["completion_count"])
    )
    label = (
        f"Milestone 8 parameterized matrix case {case['case_id']}"
        if case else
        "Milestone 8 mixed droplet/stream"
        if runtime.definition.registry_id == MIXED_MODE_WORKLOAD_ID else
        "Milestone 7 composed " + str(len(runtime.fixture["stocks"])) + "-stock"
    )
    return (
        f"{label} lifecycle\n"
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


def _randomized_calibration_summary(
    report: Mapping[str, Any], runtime: JourneyRuntime
) -> str:
    terminal = runtime.observations["randomized_calibration_lifecycle"]["terminal"]
    return (
        "Milestone 11 randomized calibration/reload execution lifecycle\n"
        f"Status: {report['classification']['status']}\n"
        f"Intents: {len(terminal['intent_counts'])} / 24\n"
        f"Droplets: {terminal['terminal']['total_added_droplets']} / 80\n"
        f"Application sessions: {len(runtime.harness.application_sessions)}\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _m13_legal_summary(
    report: Mapping[str, Any], runtime: JourneyRuntime
) -> str:
    sequence = runtime.observations.get("m13_sequence")
    terminal = dict(runtime.observations.get("m13_lifecycle", {}).get("terminal") or {})
    return (
        "Milestone 13 compact legal design/calibration lifecycle\n"
        f"Sequence: {getattr(sequence, 'sequence_id', 'not_reached')}\n"
        f"Status: {report['classification']['status']}\n"
        f"Intents: {len(terminal.get('intent_counts') or ())} / 8\n"
        f"Droplets: {(terminal.get('terminal') or {}).get('total_added_droplets', 0)} / 44\n"
        f"Application sessions: {len(runtime.harness.application_sessions)}\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def _optimizer_360_summary(
    report: Mapping[str, Any], runtime: JourneyRuntime
) -> str:
    case = OPTIMIZER_360_CASE
    terminal = runtime.observations["optimizer_360_calibration_lifecycle"][
        "terminal"
    ]
    return (
        "Milestone 11A optimizer 360 calibration/reload execution lifecycle\n"
        f"Status: {report['classification']['status']}\n"
        f"Intents: {len(terminal['intent_counts'])} / {case.terminal.expected_intents}\n"
        f"Droplets: {terminal['terminal']['total_added_droplets']} / {case.terminal.expected_droplets}\n"
        f"Application sessions: {len(runtime.harness.application_sessions)}\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


SMOKE_DEFINITION = JourneyDefinition(
    registry_id=SMOKE_WORKLOAD_ID,
    scenario_name=SMOKE_SCENARIO_NAME,
    scenario_version=SMOKE_SCENARIO_VERSION,
    workload_id=SMOKE_WORKLOAD_ID,
    required_action_ids=(
        _COMMON_ACTIONS
        | _EDITOR_ACTIONS
        | _PRINT_ACTIONS
        | frozenset(
            {
                "experiment.inspect_completed_via_ui",
                "head.return_via_ui",
            }
        )
    ),
    required_ui_action_ids=(
        SMOKE_REQUIRED_UI_ACTIONS
        | frozenset(
            {
                "experiment.inspect_completed_via_ui",
                "head.return_via_ui",
            }
        )
    ),
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
LEGACY_READ_ONLY_DEFINITION = JourneyDefinition(
    registry_id=LEGACY_READ_ONLY_WORKLOAD_ID,
    scenario_name=LEGACY_READ_ONLY_SCENARIO_NAME,
    scenario_version=LEGACY_READ_ONLY_SCENARIO_VERSION,
    workload_id=LEGACY_READ_ONLY_WORKLOAD_ID,
    required_action_ids=frozenset(
        {
            "app.launch_simulated",
            "experiment.inspect_legacy_via_ui",
            "analysis.open_plate_reader_via_ui",
            "editor.create_editable_copy_via_ui",
            "artifact.capture_milestone",
            "scenario.teardown",
        }
    ),
    required_ui_action_ids=LEGACY_READ_ONLY_REQUIRED_UI_ACTIONS,
    required_assertion_ids=LEGACY_READ_ONLY_REQUIRED_ASSERTIONS,
    required_screenshots=LEGACY_READ_ONLY_REQUIRED_SCREENSHOTS,
    fixture_loader=_legacy_read_only_fixture,
    body=_legacy_read_only_body,
    artifact_assertion=_legacy_read_only_artifact,
    payload_builder=_legacy_read_only_payload,
    summary_builder=_legacy_read_only_summary,
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
EXPLORATION_DEFINITION = JourneyDefinition(
    registry_id=EXPLORATION_WORKLOAD_ID,
    scenario_name=EXPLORATION_SCENARIO_NAME,
    scenario_version="1",
    workload_id=EXPLORATION_WORKLOAD_ID,
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
    required_assertion_ids=EXPLORATION_REQUIRED_ASSERTIONS,
    required_screenshots=EXPLORATION_REQUIRED_SCREENSHOTS,
    fixture_loader=_exploration_fixture,
    body=_exploration_body,
    artifact_assertion=_exploration_artifact,
    payload_builder=_exploration_payload,
    summary_builder=_exploration_summary,
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
MIXED_MODE_DEFINITION = JourneyDefinition(
    registry_id=MIXED_MODE_WORKLOAD_ID,
    scenario_name=MIXED_MODE_SCENARIO_NAME,
    scenario_version=MIXED_MODE_SCENARIO_VERSION,
    workload_id=MIXED_MODE_WORKLOAD_ID,
    required_action_ids=(
        _COMMON_ACTIONS | _EDITOR_ACTIONS | _PRINT_ACTIONS
        | frozenset({
            "head.bind_identity", "head.return_via_ui",
            "manual_refuel.complete_check_via_ui",
            "validation.stock_pass_boundary",
        })
    ),
    required_ui_action_ids=MIXED_MODE_REQUIRED_UI_ACTIONS,
    required_assertion_ids=MIXED_MODE_REQUIRED_ASSERTIONS,
    required_screenshots=MIXED_MODE_REQUIRED_SCREENSHOTS,
    fixture_loader=_mixed_mode_fixture,
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
RANDOMIZED_CALIBRATION_DEFINITION = JourneyDefinition(
    registry_id=RANDOMIZED_CALIBRATION_WORKLOAD_ID,
    scenario_name=RANDOMIZED_CALIBRATION_SCENARIO_NAME,
    scenario_version=RANDOMIZED_CALIBRATION_SCENARIO_VERSION,
    workload_id=RANDOMIZED_CALIBRATION_WORKLOAD_ID,
    required_action_ids=_RANDOMIZED_CALIBRATION_ACTIONS,
    required_ui_action_ids=RANDOMIZED_CALIBRATION_REQUIRED_UI_ACTIONS,
    required_assertion_ids=RANDOMIZED_CALIBRATION_REQUIRED_ASSERTIONS,
    required_screenshots=RANDOMIZED_CALIBRATION_REQUIRED_SCREENSHOTS,
    fixture_loader=_randomized_calibration_fixture,
    body=run_joined_calibrated_checkpoint,
    artifact_assertion=_randomized_calibration_artifact,
    payload_builder=_randomized_calibration_payload,
    summary_builder=_randomized_calibration_summary,
)
OPTIMIZER_360_DEFINITION = JourneyDefinition(
    registry_id=OPTIMIZER_360_WORKLOAD_ID,
    scenario_name=OPTIMIZER_360_SCENARIO_NAME,
    scenario_version=OPTIMIZER_360_SCENARIO_VERSION,
    workload_id=OPTIMIZER_360_WORKLOAD_ID,
    required_action_ids=_RANDOMIZED_CALIBRATION_ACTIONS,
    required_ui_action_ids=RANDOMIZED_CALIBRATION_REQUIRED_UI_ACTIONS,
    required_assertion_ids=OPTIMIZER_360_REQUIRED_ASSERTIONS,
    required_screenshots=OPTIMIZER_360_REQUIRED_SCREENSHOTS,
    fixture_loader=_optimizer_360_fixture,
    body=run_optimizer_360_full_lifecycle,
    artifact_assertion=_optimizer_360_artifact,
    payload_builder=_optimizer_360_payload,
    summary_builder=_optimizer_360_summary,
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
        LEGACY_READ_ONLY_DEFINITION,
        EDITOR_REVISION_DEFINITION,
        EXPLORATION_DEFINITION,
        POST_START_LOCK_DEFINITION,
        MULTI_STOCK_DEFINITION,
        MIXED_MODE_DEFINITION,
        STRESS_DEFINITION,
        SOFT_STOP_DEFINITION,
        AUTHORITATIVE_RELOAD_DEFINITION,
        DISCONNECT_DEFINITION,
        RANDOMIZED_CALIBRATION_DEFINITION,
        OPTIMIZER_360_DEFINITION,
        CALIBRATION_STORAGE_FUNCTIONAL_DEFINITION,
        CALIBRATION_STORAGE_PERFORMANCE_DEFINITION,
        CALIBRATION_STORAGE_SHADOW_FUNCTIONAL_DEFINITION,
        CALIBRATION_STORAGE_SHADOW_PERFORMANCE_DEFINITION,
        CALIBRATION_STORAGE_AUTHORITATIVE_FUNCTIONAL_DEFINITION,
        CALIBRATION_STORAGE_AUTHORITATIVE_PERFORMANCE_DEFINITION,
        CALIBRATION_STORAGE_PRIMARY_READER_FUNCTIONAL_DEFINITION,
        CALIBRATION_STORAGE_PRIMARY_READER_PERFORMANCE_DEFINITION,
        CALIBRATION_STORAGE_NEW_STORE_ONLY_FUNCTIONAL_DEFINITION,
        CALIBRATION_STORAGE_SECONDARY_READER_FUNCTIONAL_DEFINITION,
        CALIBRATION_STORAGE_SECONDARY_READER_PERFORMANCE_DEFINITION,
        CALIBRATION_STORAGE_HISTORICAL_CONVERSION_DEFINITION,
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


def _run_parameterized_calibration_matrix_case(
    config: JourneyRunConfig,
    *,
    matrix_id: str,
    case_id: str,
    base_definition: JourneyDefinition,
) -> dict[str, Any]:
    """Run one typed matrix case through the shared multi-stock journey body."""

    from tools.virtual_workflows.matrices import build_case_fixture, get_matrix_case

    fixture_bundle = build_case_fixture(matrix_id, case_id)
    case = get_matrix_case(matrix_id, case_id)
    # Build pass specs without executing by using the fixture-derived case contract.
    fixture = fixture_bundle[0]
    # The action and screenshot contracts are derived from the same typed case data.
    dummy = type("MatrixPlanRuntime", (), {})()
    dummy.fixture = fixture
    dummy.definition = base_definition
    dummy.harness = type("Harness", (), {"config": config})()
    pass_specs = _multi_passes(dummy)
    steps = normalized_stock_pass_steps(pass_specs)
    observed_actions = {row["action_id"] for row in steps}
    requires_terminal_reload = bool(
        case.normalized().get("require_terminal_reload")
    )
    case_payload = case.normalized()
    expected_terminal = str(case_payload.get("expected_terminal") or "")
    requires_isolation = case_payload.get("case_kind") == "two_reagent_isolation"
    required_actions = (
        _COMMON_ACTIONS
        | _EDITOR_ACTIONS
        | frozenset({
            "machine.connect_via_ui",
            "machine.enable_motors_via_ui",
            "machine.home_via_ui",
        })
        | frozenset(observed_actions)
        | (
            frozenset({
                "app.close_simulated_session",
                "experiment.inspect_completed_via_ui",
            })
            if requires_terminal_reload else frozenset()
        )
    )
    non_ui = {
        "app.launch_simulated", "app.close_simulated_session",
        "artifact.capture_milestone", "scenario.teardown",
        "head.bind_identity", "array.wait_for_completions",
        "validation.stock_pass_boundary",
    }
    required_screenshots = {"editor_opened", "generated"}
    for spec in pass_specs:
        for name in (
            spec.ready_milestone,
            spec.printing_milestone,
            spec.completed_milestone,
            spec.manual_refuel_check.milestone
            if spec.manual_refuel_check is not None else None,
        ):
            if name:
                required_screenshots.add(name)
    if case.expected_terminal == "manual_refuel_cancelled":
        required_screenshots.add("manual_refuel_blocked")
    if expected_terminal == "calibration_apply_rejected":
        required_screenshots.add("calibration_apply_blocked")
    if requires_terminal_reload:
        required_screenshots.add("terminal_reloaded")
    if expected_terminal == "completed":
        required_assertions = (
            *MULTI_STOCK_REQUIRED_ASSERTIONS[:-1],
            "execution.dispense_counts_reconciled",
            *(
                ("execution.two_reagent_isolation_exact",)
                if requires_isolation else ()
            ),
            *MATRIX_CASE_REQUIRED_ASSERTIONS[2:],
        )
    elif expected_terminal == "calibration_apply_rejected":
        required_assertions = (
            *MATRIX_CASE_REQUIRED_ASSERTIONS[:2],
            "execution.calibration_apply_fail_closed",
            *MATRIX_CASE_REQUIRED_ASSERTIONS[2:],
        )
    else:
        required_assertions = MATRIX_CASE_REQUIRED_ASSERTIONS
    if requires_terminal_reload:
        required_assertions = (
            *required_assertions[:-2],
            "execution.completed_terminal_reload_exact",
            *required_assertions[-2:],
        )
    definition = replace(
        base_definition,
        scenario_name=MATRIX_SCENARIO_NAME,
        workload_id=matrix_id,
        required_action_ids=frozenset(required_actions),
        required_ui_action_ids=frozenset(required_actions - non_ui),
        required_assertion_ids=tuple(required_assertions),
        required_screenshots=frozenset(required_screenshots),
    )
    return JourneyExecutor().run(
        definition,
        config,
        fixture_bundle=fixture_bundle,
        replay_selector_args=("--matrix", matrix_id, "--case", case_id),
    )


def _run_mixed_mode_matrix_case(
    config: JourneyRunConfig,
    *,
    matrix_id: str,
    case_id: str,
) -> dict[str, Any]:
    return _run_parameterized_calibration_matrix_case(
        config,
        matrix_id=matrix_id,
        case_id=case_id,
        base_definition=MIXED_MODE_DEFINITION,
    )


def _run_requantization_matrix_case(
    config: JourneyRunConfig,
    *,
    matrix_id: str,
    case_id: str,
) -> dict[str, Any]:
    return _run_parameterized_calibration_matrix_case(
        config,
        matrix_id=matrix_id,
        case_id=case_id,
        base_definition=MULTI_STOCK_DEFINITION,
    )


def _run_experiment_design_matrix_case(
    config: JourneyRunConfig,
    *,
    matrix_id: str,
    case_id: str,
) -> dict[str, Any]:
    from tools.virtual_workflows.experiment_design_cases import (
        get_experiment_design_case,
    )
    from tools.virtual_workflows.matrices import build_case_fixture

    case = get_experiment_design_case(case_id)
    rejected = case.expected.terminal != "prepared"
    transition_actions = (
        frozenset({"editor.regenerate_prepared_design_via_ui"})
        if len(case.optimization_attempts) > 1
        else frozenset()
    )
    required_screenshots = set(EXPERIMENT_DESIGN_REQUIRED_SCREENSHOTS)
    if case.experiment.excluded_well_ids:
        required_screenshots.add("well_picker_configured")
    if rejected:
        required_screenshots = {
            "editor_opened",
            "finalization_rejected",
            "validated",
        }
        if case.expected.terminal == "capacity_rejected":
            required_screenshots.add("generated")
    required_actions = _COMMON_ACTIONS | _EDITOR_ACTIONS | transition_actions
    required_ui_actions = (
        EXPERIMENT_DESIGN_REQUIRED_UI_ACTIONS | transition_actions
    )
    required_assertions = EXPERIMENT_DESIGN_REQUIRED_ASSERTIONS
    if rejected:
        required_actions -= frozenset(
            {"experiment.load_authoritative_via_ui"}
        )
        required_ui_actions = set(
            EXPERIMENT_DESIGN_REJECTED_REQUIRED_UI_ACTIONS
        )
        if case.expected.terminal == "capacity_rejected":
            required_ui_actions.add("editor.optimize_generate_via_ui")
        else:
            required_actions -= frozenset(
                {"editor.optimize_generate_via_ui"}
            )
        required_assertions = EXPERIMENT_DESIGN_REJECTED_REQUIRED_ASSERTIONS
    definition = replace(
        EDITOR_DEFINITION,
        scenario_name=EXPERIMENT_DESIGN_MATRIX_SCENARIO_NAME,
        workload_id=matrix_id,
        required_action_ids=(
            required_actions
            | (
                frozenset()
                if rejected
                else frozenset({"experiment.load_authoritative_via_ui"})
            )
        ),
        required_ui_action_ids=frozenset(required_ui_actions),
        required_assertion_ids=required_assertions,
        required_screenshots=frozenset(required_screenshots),
        body=_experiment_design_body,
        artifact_assertion=_experiment_design_artifact,
        payload_builder=_experiment_design_payload,
        summary_builder=_experiment_design_summary,
    )
    return JourneyExecutor().run(
        definition,
        config,
        fixture_bundle=build_case_fixture(matrix_id, case_id),
        replay_selector_args=("--matrix", matrix_id, "--case", case_id),
    )


def _run_editor_safeguard_matrix_case(
    config: JourneyRunConfig,
    *,
    matrix_id: str,
    case_id: str,
) -> dict[str, Any]:
    from tools.virtual_workflows.editor_safeguards import (
        get_editor_safeguard_case,
    )
    from tools.virtual_workflows.matrices import build_case_fixture

    case = get_editor_safeguard_case(case_id)
    specification = dict(case.setup)["specification"]
    terminal = str(specification["expected"]["terminal"])
    ui_actions = {
        "editor.open_via_ui",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        case.operator_action_id,
    }
    screenshots = {"editor_opened", "finalization_rejected", "validated"}
    if specification["experiment"].get("excluded_well_ids"):
        screenshots.add("well_picker_configured")
    if terminal in {"capacity_rejected", "dirty_invalid_rejected"}:
        ui_actions.add("editor.optimize_generate_via_ui")
        screenshots.add("generated")
    definition = replace(
        EDITOR_DEFINITION,
        scenario_name=EDITOR_SAFEGUARD_MATRIX_SCENARIO_NAME,
        workload_id=matrix_id,
        required_action_ids=_COMMON_ACTIONS | frozenset(ui_actions),
        required_ui_action_ids=frozenset(ui_actions),
        required_assertion_ids=EDITOR_SAFEGUARD_REQUIRED_ASSERTIONS,
        required_screenshots=frozenset(screenshots),
        body=_editor_safeguard_body,
        artifact_assertion=_editor_safeguard_artifact,
        payload_builder=_editor_safeguard_payload,
        summary_builder=_editor_safeguard_summary,
    )
    return JourneyExecutor().run(
        definition,
        config,
        fixture_bundle=build_case_fixture(matrix_id, case_id),
        replay_selector_args=("--matrix", matrix_id, "--case", case_id),
    )


def _run_execution_preflight_safeguard_matrix_case(
    config: JourneyRunConfig,
    *,
    matrix_id: str,
    case_id: str,
) -> dict[str, Any]:
    from tools.virtual_workflows.execution_preflight_safeguards import (
        get_execution_preflight_case,
    )
    from tools.virtual_workflows.matrices import build_case_fixture

    case = get_execution_preflight_case(case_id)
    definition = replace(
        EDITOR_DEFINITION,
        scenario_name=EXECUTION_PREFLIGHT_MATRIX_SCENARIO_NAME,
        workload_id=matrix_id,
        required_action_ids=(
            _COMMON_ACTIONS
            | frozenset({case.operator_action_id, "artifact.capture_milestone"})
        ),
        required_ui_action_ids=frozenset({case.operator_action_id}),
        required_assertion_ids=(
            EXECUTION_PREFLIGHT_SAFEGUARD_REQUIRED_ASSERTIONS
        ),
        required_screenshots=frozenset(
            {"rejection_observed", "validated"}
        ),
        body=_execution_preflight_safeguard_body,
        artifact_assertion=_execution_preflight_safeguard_artifact,
        payload_builder=_execution_preflight_safeguard_payload,
        summary_builder=_execution_preflight_safeguard_summary,
    )
    return JourneyExecutor().run(
        definition,
        config,
        fixture_bundle=build_case_fixture(matrix_id, case_id),
        replay_selector_args=("--matrix", matrix_id, "--case", case_id),
    )


def _run_persistence_safeguard_matrix_case(
    config: JourneyRunConfig,
    *,
    matrix_id: str,
    case_id: str,
) -> dict[str, Any]:
    from tools.virtual_workflows.matrices import build_case_fixture

    case = get_persistence_safeguard_case(case_id)
    definition = replace(
        EDITOR_DEFINITION,
        scenario_name=PERSISTENCE_SAFEGUARD_MATRIX_SCENARIO_NAME,
        workload_id=matrix_id,
        required_action_ids=(
            _COMMON_ACTIONS
            | frozenset(
                {
                    case.operator_action_id,
                    "experiment.attempt_locked_activation_via_ui",
                    "artifact.capture_milestone",
                }
            )
        ),
        required_ui_action_ids=frozenset(
            {
                case.operator_action_id,
                "experiment.attempt_locked_activation_via_ui",
            }
        ),
        required_assertion_ids=PERSISTENCE_SAFEGUARD_REQUIRED_ASSERTIONS,
        required_screenshots=frozenset({"rejection_observed", "validated"}),
        body=_persistence_safeguard_body,
        artifact_assertion=_persistence_safeguard_artifact,
        payload_builder=_persistence_safeguard_payload,
        summary_builder=_persistence_safeguard_summary,
    )

    def prepare(runtime: JourneyRuntime) -> None:
        prepared = prepare_persistence_fault(case, runtime.harness.scenario_root)
        runtime.observations["persistence_fault_prelaunch"] = prepared.to_dict()

    return JourneyExecutor().run(
        definition,
        config,
        fixture_bundle=build_case_fixture(matrix_id, case_id),
        replay_selector_args=("--matrix", matrix_id, "--case", case_id),
        prelaunch_prepare=prepare,
    )


_MATRIX_JOURNEY_RUNNERS = {
    "calibration_requantization": _run_requantization_matrix_case,
    "editor_safeguards": _run_editor_safeguard_matrix_case,
    "execution_preflight_safeguards": (
        _run_execution_preflight_safeguard_matrix_case
    ),
    "persistence_safeguards": _run_persistence_safeguard_matrix_case,
    "experiment_design": _run_experiment_design_matrix_case,
    "mixed_mode_calibration": _run_mixed_mode_matrix_case,
}


def run_matrix_case(
    config: JourneyRunConfig,
    *,
    matrix_id: str,
    case_id: str,
) -> dict[str, Any]:
    """Validate and dispatch one registered matrix case by journey family."""

    from tools.virtual_workflows.matrices import get_matrix_definition

    definition = get_matrix_definition(matrix_id)
    if config.scenario_id != definition.base_scenario_id:
        raise ValueError(
            f"matrix {matrix_id!r} requires composed base "
            f"{definition.base_scenario_id!r}"
        )
    try:
        runner = _MATRIX_JOURNEY_RUNNERS[definition.journey_family]
    except KeyError as exc:
        raise ValueError(
            f"unsupported matrix journey family: {definition.journey_family!r}"
        ) from exc
    return runner(config, matrix_id=matrix_id, case_id=case_id)


def _m13_fixture_projection_for_sequence(sequence: Any):
    fixture, source = m13_fixture_projection(sequence.sequence_id)
    fixture["normalized_sequence"] = sequence.normalized()
    return fixture, source


def run_exploration_sequence(
    config: JourneyRunConfig,
    *,
    campaign_id: str,
    sequence_id: str,
    normalized_sequence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one generated editor sequence through the shared journey body."""

    if campaign_id == M13_EXPLORATION_WORKLOAD_ID:
        from tools.virtual_workflows.exploration_m13 import (
            M13_REJECTION_CASES,
            get_sequence,
            sequence_from_normalized,
        )

        sequence = (
            sequence_from_normalized(normalized_sequence)
            if normalized_sequence is not None
            else get_sequence(sequence_id)
        )
        if sequence.sequence_id != sequence_id:
            raise ValueError("retained normalized sequence identity drifted")
        rejected_operations = tuple(
            step.operation_id
            for step in sequence.steps
            if step.operation_id in M13_REJECTION_CASES
        )
        rejection_cases = tuple(
            (
                operation_id,
                get_editor_safeguard_case(M13_REJECTION_CASES[operation_id])
                if operation_id
                in {
                    "editor.finalize_invalid_via_ui",
                    "editor.optimize_one_stock_invalid_via_ui",
                }
                else get_execution_preflight_case(
                    M13_REJECTION_CASES[operation_id]
                ),
            )
            for operation_id in rejected_operations
        )
        revision_actions = (
            frozenset(
                {
                    "editor.rename_prepared_via_ui",
                    "editor.edit_prepared_design_via_ui",
                    "editor.regenerate_prepared_design_via_ui",
                    "editor.refinalize_prepared_via_ui",
                }
            )
            if sequence.role == "legal_refinalize_reload_terminal"
            else frozenset()
        )
        definition = JourneyDefinition(
            registry_id=M13_EXPLORATION_WORKLOAD_ID,
            scenario_name=M13_EXPLORATION_SCENARIO_NAME,
            scenario_version="1",
            workload_id=M13_EXPLORATION_WORKLOAD_ID,
            required_action_ids=(
                _RANDOMIZED_CALIBRATION_ACTIONS
                | revision_actions
                | frozenset(case.operator_action_id for _operation, case in rejection_cases)
            ),
            required_ui_action_ids=(
                RANDOMIZED_CALIBRATION_REQUIRED_UI_ACTIONS
                | revision_actions
                | frozenset(case.operator_action_id for _operation, case in rejection_cases)
            ),
            required_assertion_ids=(
                M13_LEGAL_REQUIRED_ASSERTIONS
                if not rejected_operations
                else (
                    *(
                        assertion_id
                        for assertion_id in M13_LEGAL_REQUIRED_ASSERTIONS
                        if assertion_id
                        not in {
                            "exploration.m13_legal_sequence_exact",
                            "artifacts.required_present",
                        }
                    ),
                    *(
                        f"exploration.m13_rejection.{case.case_id}"
                        for _operation, case in rejection_cases
                    ),
                    "exploration.m13_illegal_recovery_exact",
                    "artifacts.required_present",
                )
            ),
            required_screenshots=M13_LEGAL_REQUIRED_SCREENSHOTS,
            fixture_loader=lambda: _m13_fixture_projection_for_sequence(sequence),
            body=run_m13_legal_sequence_lifecycle,
            artifact_assertion=_m13_legal_artifact,
            payload_builder=_m13_legal_payload,
            summary_builder=_m13_legal_summary,
        )
        return JourneyExecutor().run(
            definition,
            config,
            fixture_bundle=_m13_fixture_projection_for_sequence(sequence),
            replay_selector_args=(
                "--exploration",
                campaign_id,
                "--sequence",
                sequence_id,
                *(
                    (
                        "--seed-tier",
                        "diagnostic",
                        "--diagnostic-seed",
                        str(sequence.seed),
                    )
                    if sequence.seed_tier == "diagnostic"
                    else ()
                ),
            ),
        )

    if config.scenario_id != EXPLORATION_WORKLOAD_ID:
        raise ValueError("exploration requires the prepared-guard composed base")
    from tools.virtual_workflows.exploration import build_sequence_fixture

    fixture_bundle = build_sequence_fixture(campaign_id, sequence_id)
    required_screenshots = set(EXPLORATION_REQUIRED_SCREENSHOTS)
    if fixture_bundle[0]["exploration"]["sequence"]["sequence_class"] == "illegal":
        required_screenshots.add("premature_refinalize_rejected")
    definition = replace(
        EXPLORATION_DEFINITION,
        required_screenshots=frozenset(required_screenshots),
    )
    return JourneyExecutor().run(
        definition,
        config,
        fixture_bundle=fixture_bundle,
        replay_selector_args=(
            "--exploration",
            campaign_id,
            "--sequence",
            sequence_id,
        ),
    )


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
    "EXPLORATION_WORKLOAD_ID",
    "EXPLORATION_REQUIRED_ASSERTIONS",
    "DISCONNECT_REQUIRED_ASSERTIONS",
    "DISCONNECT_REQUIRED_UI_ACTIONS",
    "DISCONNECT_WORKLOAD_ID",
    "AUTHORITATIVE_RELOAD_REQUIRED_ASSERTIONS",
    "AUTHORITATIVE_RELOAD_REQUIRED_UI_ACTIONS",
    "AUTHORITATIVE_RELOAD_WORKLOAD_ID",
    "JOURNEY_DEFINITIONS",
    "JOINED_CALIBRATED_CHECKPOINT_REQUIRED_ASSERTIONS",
    "JOINED_CALIBRATED_CHECKPOINT_REQUIRED_UI_ACTIONS",
    "OPTIMIZER_360_FIRST_CALIBRATION_REQUIRED_ASSERTIONS",
    "OPTIMIZER_360_CALIBRATION_CHAIN_REQUIRED_ASSERTIONS",
    "OPTIMIZER_360_LIFECYCLE_REQUIRED_ASSERTIONS",
    "OPTIMIZER_360_REQUIRED_ASSERTIONS",
    "OPTIMIZER_360_REQUIRED_SCREENSHOTS",
    "OPTIMIZER_360_WORKLOAD_ID",
    "JourneyRunConfig",
    "MULTI_STOCK_REQUIRED_ASSERTIONS",
    "MULTI_STOCK_REQUIRED_UI_ACTIONS",
    "MULTI_STOCK_WORKLOAD_ID",
    "MIXED_MODE_WORKLOAD_ID",
    "MIXED_MODE_REQUIRED_ASSERTIONS",
    "MIXED_MODE_REQUIRED_UI_ACTIONS",
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
    "run_matrix_case",
    "run_joined_calibrated_checkpoint",
    "run_optimizer_360_first_calibration_checkpoint",
    "run_optimizer_360_calibration_chain",
    "run_optimizer_360_full_lifecycle",
    "run_exploration_sequence",
    "run_editor_create_finalize_journey",
    "run_disconnect_fail_closed_24_journey",
    "run_multi_stock_24x2_journey",
    "run_soft_stop_resume_24_journey",
    "run_virtual_print_array_24_journey",
]
