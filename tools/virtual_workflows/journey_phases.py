"""Reusable typed phases for composed SIL journeys."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tools.virtual_workflows.actions import (
    InteractionSurface,
    ScenarioActionError,
    capture_milestone,
    disconnect_machine_via_ui,
    observe_disconnected_quiescence,
    observe_stopped_quiescence,
    request_soft_stop_via_ui,
    resume_array_via_ui,
    wait_for_array_state,
    wait_for_completions,
)
from tools.virtual_workflows.composition import JourneyRuntime, SemanticStep
from tools.virtual_workflows.dispense_counts import capture_count_snapshot
from tools.virtual_workflows.page_drivers import (
    ArrayDriver,
    CalibrationDialogDriver,
    ExperimentEditorDriver,
    ExperimentLoaderDriver,
    MachineControlsDriver,
    ManualRefuelCheckDriver,
    RackDriver,
)


@dataclass(frozen=True)
class MachineStartupSpec:
    connect: bool = True
    enable_motors: bool = True
    home: bool = True


@dataclass(frozen=True)
class EditorPreparationSpec:
    specification: Mapping[str, Any]
    use_harness_action_runner: bool = False
    snapshot_finish: bool = False
    capture_editor_milestones: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.specification, Mapping):
            raise ValueError("editor specification must be a mapping")


@dataclass(frozen=True)
class PreparedEditorRevisionSpec:
    initial_name: str
    renamed_name: str
    replicates: int
    well_ids: tuple[str, ...]
    printed_volume_nL: float
    final_volume_nL: float
    fill_printing_mode: str
    fill_droplet_volume_nL: float
    reagent_printing_mode: str
    reagent_targets: tuple[float, ...]
    reagent_droplet_volume_nL: float

    def __post_init__(self) -> None:
        if not self.initial_name.strip() or not self.renamed_name.strip():
            raise ValueError("prepared revision names must be non-empty")
        if self.initial_name == self.renamed_name:
            raise ValueError("prepared revision must change the experiment name")
        if self.replicates <= 0:
            raise ValueError("prepared revision replicates must be positive")
        if not self.well_ids or any(not value.strip() for value in self.well_ids):
            raise ValueError("prepared revision wells must be non-empty")
        if len(set(self.well_ids)) != len(self.well_ids):
            raise ValueError("prepared revision wells must be unique")
        for label, value in (
            ("printed volume", self.printed_volume_nL),
            ("final volume", self.final_volume_nL),
            ("fill droplet volume", self.fill_droplet_volume_nL),
            ("reagent droplet volume", self.reagent_droplet_volume_nL),
        ):
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"prepared revision {label} must be positive")
        if self.fill_printing_mode not in {"droplet", "stream"}:
            raise ValueError("prepared revision fill mode is unsupported")
        if self.reagent_printing_mode not in {"droplet", "stream"}:
            raise ValueError("prepared revision reagent mode is unsupported")
        if not self.reagent_targets or any(
            not math.isfinite(float(value)) or float(value) < 0
            for value in self.reagent_targets
        ):
            raise ValueError("prepared revision targets must be non-negative")

    def experiment_values(self) -> dict[str, Any]:
        return {
            "refinalized_replicates": self.replicates,
            "refinalized_expected_well_ids": list(self.well_ids),
            "refinalized_printed_volume_nL": self.printed_volume_nL,
            "refinalized_final_volume_nL": self.final_volume_nL,
            "refinalized_fill_printing_mode": self.fill_printing_mode,
            "refinalized_fill_droplet_volume_nL": self.fill_droplet_volume_nL,
        }

    def reagent_values(self) -> dict[str, Any]:
        return {
            "refinalized_printing_mode": self.reagent_printing_mode,
            "refinalized_targets": list(self.reagent_targets),
            "refinalized_droplet_volume_nL": self.reagent_droplet_volume_nL,
        }


@dataclass(frozen=True)
class PostStartLockCopySpec:
    source_dir: Path
    source_name: str
    copy_name: str
    copy_tolerance_nl: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_dir", Path(self.source_dir).resolve())
        if not self.source_name.strip() or not self.copy_name.strip():
            raise ValueError("post-start source and copy names must be non-empty")
        if self.source_name == self.copy_name:
            raise ValueError("post-start editable copy must have a distinct name")
        if not math.isfinite(self.copy_tolerance_nl) or self.copy_tolerance_nl < 0:
            raise ValueError("post-start copy tolerance must be finite and non-negative")


@dataclass(frozen=True)
class ManualRefuelCheckSpec:
    trial_count: int = 2
    trial_droplet_count: int = 5
    outcome: str = "passed"
    operator_judgment: str = "stable"
    milestone: str | None = "manual_refuel_passed"

    def __post_init__(self) -> None:
        if self.trial_count <= 0 or self.trial_droplet_count <= 0:
            raise ValueError("manual-refuel trial counts must be positive")
        valid = {
            ("passed", "stable"),
            ("failed", "level_rose"),
            ("failed", "level_fell"),
            ("unclear", "unclear"),
        }
        if (self.outcome, self.operator_judgment) not in valid:
            raise ValueError("manual-refuel outcome and judgment are unsupported")
        if self.milestone is not None and not self.milestone:
            raise ValueError("manual-refuel milestone must be non-empty")


@dataclass(frozen=True)
class StockPassSpec:
    stock_id: str
    printer_head_id: str
    pulse_width_us: int
    pressure_psi: float
    frequency_hz: int
    initial_volume_uL: float
    expected_volume_nL: float
    expected_completion_count: int
    expected_plan_state: str
    ready_milestone: str | None
    printing_milestone: str | None
    completed_milestone: str | None
    staging_slot: int | None = None
    start_dialog_titles: tuple[str, ...] = (
        "Start Print Array",
        "Evaporation Plate Dock Check",
    )
    bind_identity: bool = False
    enable_pressure_regulation: bool = False
    validate_pass_boundary: bool = False
    return_head: bool = False
    detailed_evidence: bool = False
    include_frequency_evidence: bool = True
    no_progress_timeout_seconds: float | None = None
    await_terminal_boundary: bool = True
    calibration_mode: str = "droplet"
    mode_switch_choice: str | None = None
    apply_success_title: str = "Applied"
    require_refuel_regulation: bool = False
    expected_applied_pulse_width_us: int | None = None
    calibration_print_profile_id: str | None = None
    refuel_pulse_width_us: int | None = None
    refuel_pressure_psi: float | None = None
    manual_refuel_check: ManualRefuelCheckSpec | None = None
    expected_start_outcome: str = "running"
    rejected_calibration_mode: str | None = None
    rejected_calibration_pulse_width_us: int | None = None
    rejected_calibration_profile_id: str | None = None
    rejected_calibration_title: str | None = None
    rejected_calibration_message_fragment: str | None = None
    capture_isolation_boundary: bool = False

    def __post_init__(self) -> None:
        if not self.stock_id or not self.printer_head_id:
            raise ValueError("stock and printer-head IDs must be non-empty")
        if self.pulse_width_us <= 0 or self.frequency_hz <= 0:
            raise ValueError("pulse width and frequency must be positive")
        if self.pressure_psi <= 0 or self.initial_volume_uL <= 0:
            raise ValueError("pressure and initial volume must be positive")
        if self.expected_volume_nL <= 0 or self.expected_completion_count <= 0:
            raise ValueError("expected volume and completion count must be positive")
        if self.expected_plan_state not in {"active", "completed"}:
            raise ValueError("expected plan state must be active or completed")
        if self.staging_slot is not None and self.staging_slot < 0:
            raise ValueError("staging slot must be non-negative")
        if not self.start_dialog_titles:
            raise ValueError("at least one start dialog is required")
        if any(value is not None and not value for value in (
            self.ready_milestone, self.printing_milestone, self.completed_milestone
        )):
            raise ValueError("stock-pass milestone names must be non-empty when present")
        if not self.await_terminal_boundary and (
            self.validate_pass_boundary
            or self.return_head
            or self.completed_milestone is not None
        ):
            raise ValueError(
                "interrupted stock passes cannot validate, return, or capture a terminal boundary"
            )
        if (
            self.no_progress_timeout_seconds is not None
            and (
                not math.isfinite(float(self.no_progress_timeout_seconds))
                or float(self.no_progress_timeout_seconds) <= 0
            )
        ):
            raise ValueError("no-progress timeout must be finite and positive")
        if self.calibration_mode not in {"droplet", "stream"}:
            raise ValueError("calibration mode must be droplet or stream")
        if self.mode_switch_choice not in {None, "yes", "no"}:
            raise ValueError("mode-switch choice must be yes, no, or None")
        if not self.apply_success_title:
            raise ValueError("Apply success title must be non-empty")
        if self.refuel_pulse_width_us is not None and self.refuel_pulse_width_us <= 0:
            raise ValueError("refuel pulse width must be positive")
        if (
            self.expected_applied_pulse_width_us is not None
            and self.expected_applied_pulse_width_us <= 0
        ):
            raise ValueError("expected applied pulse width must be positive")
        if self.refuel_pressure_psi is not None and self.refuel_pressure_psi <= 0:
            raise ValueError("refuel pressure must be positive")
        if self.manual_refuel_check is not None and (
            self.calibration_mode != "stream"
            or self.refuel_pulse_width_us is None
            or self.refuel_pressure_psi is None
        ):
            raise ValueError(
                "manual-refuel checks require stream mode and both refuel settings"
            )
        if self.expected_start_outcome not in {
            "running",
            "manual_refuel_cancelled",
            "calibration_apply_rejected",
        }:
            raise ValueError("stock-pass start outcome is unsupported")
        if self.expected_start_outcome == "manual_refuel_cancelled" and (
            self.manual_refuel_check is None
            or self.manual_refuel_check.outcome == "passed"
        ):
            raise ValueError(
                "manual-refuel cancellation requires a non-passed stream check"
            )
        if self.expected_start_outcome == "manual_refuel_cancelled" and (
            self.printing_milestone is not None
            or self.completed_milestone is not None
            or self.validate_pass_boundary
        ):
            raise ValueError(
                "a cancelled pass cannot print, complete, or validate a pass boundary"
            )
        rejection_values = (
            self.rejected_calibration_mode,
            self.rejected_calibration_pulse_width_us,
            self.rejected_calibration_profile_id,
            self.rejected_calibration_title,
            self.rejected_calibration_message_fragment,
        )
        if self.expected_start_outcome == "calibration_apply_rejected":
            if any(value in (None, "") for value in rejection_values):
                raise ValueError(
                    "calibration rejection requires a complete rejected calibration"
                )
            if self.rejected_calibration_mode not in {"droplet", "stream"}:
                raise ValueError("rejected calibration mode is unsupported")
            if int(self.rejected_calibration_pulse_width_us or 0) <= 0:
                raise ValueError("rejected calibration pulse width must be positive")
            if (
                self.printing_milestone is not None
                or self.completed_milestone is not None
                or self.validate_pass_boundary
            ):
                raise ValueError(
                    "a rejected calibration cannot print or validate a pass boundary"
                )
        elif any(value is not None for value in rejection_values):
            raise ValueError(
                "rejected calibration fields require calibration_apply_rejected"
            )


@dataclass(frozen=True)
class CalibrationOnlySpec:
    """One real calibration boundary that cannot start array execution."""

    stock_id: str
    printer_head_id: str
    pulse_width_us: int
    pressure_psi: float
    frequency_hz: int
    initial_volume_uL: float
    expected_volume_nL: float
    staging_slot: int | None = None
    calibration_mode: str = "droplet"
    calibration_print_profile_id: str | None = None
    apply_success_title: str = "Applied"
    bind_identity: bool = True
    enable_pressure_regulation: bool = True
    return_head: bool = False
    detailed_evidence: bool = True
    include_frequency_evidence: bool = True
    refuel_pulse_width_us: int | None = None
    refuel_pressure_psi: float | None = None

    def __post_init__(self) -> None:
        if not self.stock_id or not self.printer_head_id:
            raise ValueError("calibration-only stock and head IDs must be non-empty")
        if self.pulse_width_us <= 0 or self.frequency_hz <= 0:
            raise ValueError("calibration-only pulse and frequency must be positive")
        if self.pressure_psi <= 0 or self.initial_volume_uL <= 0:
            raise ValueError("calibration-only pressure and volume must be positive")
        if self.expected_volume_nL <= 0:
            raise ValueError("calibration-only expected volume must be positive")
        if self.staging_slot is not None and self.staging_slot < 0:
            raise ValueError("calibration-only staging slot must be non-negative")
        if self.calibration_mode not in {"droplet", "stream"}:
            raise ValueError("calibration-only mode must be droplet or stream")
        if not self.apply_success_title:
            raise ValueError("calibration-only Apply title must be non-empty")
        if self.refuel_pulse_width_us is not None or self.refuel_pressure_psi is not None:
            raise ValueError("calibration-only phase does not support refuel behavior")


@dataclass(frozen=True)
class PrecalibratedStockPassSpec:
    """One stock pass that must reuse an already-persisted calibration."""

    stock_id: str
    printer_head_id: str
    pulse_width_us: int
    pressure_psi: float
    frequency_hz: int
    initial_volume_uL: float
    expected_volume_nL: float
    expected_completion_count: int
    expected_plan_state: str
    completed_milestone: str
    staging_slot: int | None = None
    start_dialog_titles: tuple[str, ...] = ("Start Print Array",)
    bind_identity: bool = False
    return_head: bool = True
    detailed_evidence: bool = True
    include_frequency_evidence: bool = True
    calibration_mode: str = "droplet"
    refuel_pulse_width_us: int | None = None
    refuel_pressure_psi: float | None = None
    capture_completed_milestone: bool = True

    def __post_init__(self) -> None:
        if not self.stock_id or not self.printer_head_id:
            raise ValueError("precalibrated stock and head IDs must be non-empty")
        if self.pulse_width_us <= 0 or self.frequency_hz <= 0:
            raise ValueError("precalibrated pulse and frequency must be positive")
        if self.pressure_psi <= 0 or self.initial_volume_uL <= 0:
            raise ValueError("precalibrated pressure and volume must be positive")
        if self.expected_volume_nL <= 0 or self.expected_completion_count <= 0:
            raise ValueError("precalibrated expected volume/count must be positive")
        if self.expected_plan_state not in {"active", "completed"}:
            raise ValueError("precalibrated plan state must be active or completed")
        if not self.completed_milestone or not self.start_dialog_titles:
            raise ValueError("precalibrated milestones/dialogs must be non-empty")
        if self.staging_slot is not None and self.staging_slot < 0:
            raise ValueError("precalibrated staging slot must be non-negative")
        if self.calibration_mode != "droplet":
            raise ValueError("precalibrated joined passes must remain droplet mode")
        if self.refuel_pulse_width_us is not None or self.refuel_pressure_psi is not None:
            raise ValueError("precalibrated joined passes do not support refuel")


@dataclass(frozen=True)
class SoftStopResumeSpec:
    request_after_completion_count: int
    maximum_completion_catchup: int
    quiescence_observation_ms: int
    timeout_seconds: float = 20.0
    stop_requested_milestone: str = "stop_requested"
    stopped_milestone: str = "stopped"
    resumed_milestone: str = "resumed"

    def __post_init__(self) -> None:
        positive = {
            "trigger count": self.request_after_completion_count,
            "catchup": self.maximum_completion_catchup,
            "quiescence window": self.quiescence_observation_ms,
            "timeout": self.timeout_seconds,
        }
        invalid = next((name for name, value in positive.items() if value <= 0), None)
        if invalid:
            raise ValueError(f"soft-stop {invalid} must be positive")
        if any(
            not str(value).strip()
            for value in (
                self.stop_requested_milestone,
                self.stopped_milestone,
                self.resumed_milestone,
            )
        ):
            raise ValueError("soft-stop milestone names must be non-empty")


@dataclass(frozen=True)
class DisconnectFailClosedSpec:
    disconnect_after_completion_count: int
    expected_canceled_intent_count: int
    quiescence_observation_ms: int
    timeout_seconds: float = 20.0
    disconnected_milestone: str = "disconnected"
    recovery_milestone: str = "recovery_ready"

    def __post_init__(self) -> None:
        if self.disconnect_after_completion_count <= 0:
            raise ValueError("disconnect trigger count must be positive")
        if self.expected_canceled_intent_count <= 0:
            raise ValueError("disconnect canceled-intent count must be positive")
        if self.quiescence_observation_ms <= 0 or self.timeout_seconds <= 0:
            raise ValueError("disconnect quiescence and timeout must be positive")
        if not self.disconnected_milestone or not self.recovery_milestone:
            raise ValueError("disconnect milestone names must be non-empty")


def machine_startup_steps(
    spec: MachineStartupSpec = MachineStartupSpec(),
) -> tuple[SemanticStep, ...]:
    steps: list[SemanticStep] = []
    if spec.connect:
        steps.append(
            SemanticStep(
                "machine.connect_via_ui",
                InteractionSurface.UI,
                lambda runtime: MachineControlsDriver(runtime.context).connect()
                or {"port": "SIMULATED"},
            )
        )
    if spec.enable_motors:
        steps.append(
            SemanticStep(
                "machine.enable_motors_via_ui",
                InteractionSurface.UI,
                lambda runtime: MachineControlsDriver(
                    runtime.context
                ).enable_motors()
                or {"motors_enabled": True},
            )
        )
    if spec.home:
        steps.append(
            SemanticStep(
                "machine.home_via_ui",
                InteractionSurface.UI,
                lambda runtime: MachineControlsDriver(runtime.context).home_motors()
                or {"motors_homed": True},
            )
        )
    return tuple(steps)


def run_editor_preparation(
    runtime: JourneyRuntime,
    spec: EditorPreparationSpec,
) -> dict[str, Any]:
    runner = runtime.harness.run_action if spec.use_harness_action_runner else None
    result = ExperimentEditorDriver(
        runtime.context,
        action_runner=runner,
    ).create_and_finalize(
        dict(spec.specification),
        capture_editor_milestones=spec.capture_editor_milestones,
    )
    runtime.harness.assert_no_unexpected_dialog()
    if spec.snapshot_finish:
        runtime.harness.session.snapshot(
            "action:editor.finish_via_ui",
            include_persistence=True,
            correlation={"action_id": "editor.finish_via_ui"},
        )
    return dict(result)


def normalized_prepared_revision_steps(
    spec: PreparedEditorRevisionSpec,
) -> list[dict[str, Any]]:
    """Return the ledger plan and typed values without constructing Qt objects."""

    return [
        {
            "action_id": action_id,
            "interaction_surface": "ui",
            "initial_name": spec.initial_name,
            "renamed_name": spec.renamed_name,
            "well_ids": list(spec.well_ids),
            "replicates": spec.replicates,
        }
        for action_id in (
            "editor.open_via_ui",
            "editor.rename_prepared_via_ui",
            "editor.edit_prepared_design_via_ui",
            "editor.regenerate_prepared_design_via_ui",
            "editor.refinalize_prepared_via_ui",
        )
    ]


def run_prepared_editor_revision(
    runtime: JourneyRuntime,
    spec: PreparedEditorRevisionSpec,
    *,
    capture_milestones: bool = True,
) -> dict[str, Any]:
    result = ExperimentEditorDriver(
        runtime.context,
        action_runner=runtime.harness.run_action,
    ).revise_prepared_design(
        initial_name=spec.initial_name,
        renamed_name=spec.renamed_name,
        experiment=spec.experiment_values(),
        reagent=spec.reagent_values(),
        capture_milestones=capture_milestones,
    )
    runtime.harness.assert_no_unexpected_dialog()
    return dict(result)


def run_prepared_editor_sequence(
    runtime: JourneyRuntime,
    spec: PreparedEditorRevisionSpec,
    *,
    sequence_steps: Sequence[Mapping[str, Any]],
    intermediate_tolerance_nl: float,
) -> dict[str, Any]:
    """Run one generated sequence through the reusable prepared editor."""

    result = ExperimentEditorDriver(
        runtime.context,
        action_runner=runtime.harness.run_action,
    ).run_prepared_sequence(
        initial_name=spec.initial_name,
        renamed_name=spec.renamed_name,
        experiment=spec.experiment_values(),
        reagent=spec.reagent_values(),
        sequence_steps=sequence_steps,
        intermediate_tolerance_nl=intermediate_tolerance_nl,
    )
    runtime.harness.assert_no_unexpected_dialog()
    return dict(result)


def run_post_start_lock_copy(
    runtime: JourneyRuntime,
    spec: PostStartLockCopySpec,
    *,
    source_design: Mapping[str, Any],
    expected_well_ids: Sequence[str],
) -> dict[str, Any]:
    """Cross the Model lock boundary, then drive the normal editor copy UI."""

    def activate(current: JourneyRuntime) -> Mapping[str, Any]:
        eligibility = current.context.model.load_authoritative_execution_runtime()
        runtime_active = bool(current.context.experiment_model
                              .is_authoritative_execution_runtime_active())
        if eligibility.get("status") != "ready_to_start" or not runtime_active:
            raise RuntimeError("authoritative source activation was not ready_to_start")
        return {"eligibility_status": eligibility.get("status"),
                "runtime_active": runtime_active}

    def lock(current: JourneyRuntime) -> Mapping[str, Any]:
        plan = current.context.experiment_model.lock_execution_plan("printing_started")
        if plan is None:
            raise RuntimeError("printing-start lock returned no execution plan")
        return {
            "plan_id": str(plan.plan_id),
            "plan_revision": int(plan.plan_revision),
            "plan_state": str(plan.state.value),
            "lock_reason": plan.lock_reason,
        }

    activation, locked = runtime.run_steps(
        (
            SemanticStep("experiment.activate_authoritative",
                         InteractionSurface.MODEL, activate),
            SemanticStep("execution.lock_for_printing",
                         InteractionSurface.MODEL, lock),
        )
    )
    from tools.virtual_workflows.authoritative_evidence import (
        capture_authoritative_bundle,
        post_start_copy_boundary_evidence,
        post_start_source_lock_evidence,
        snapshot_directory,
    )

    source_snapshot = capture_authoritative_bundle(runtime.context)
    source_locked = post_start_source_lock_evidence(
        source_snapshot,
        source_design=source_design,
        activation=activation["evidence"],
        lock=locked["evidence"],
    )
    if source_locked["failed_checks"]:
        raise RuntimeError(
            "post-start source lock checks failed: "
            + ", ".join(source_locked["failed_checks"])
        )
    capture_milestone(
        runtime.context,
        "source_locked",
        evidence={"plan_state": source_snapshot.plan_state,
                  "plan_revision": source_snapshot.plan_revision,
                  "lock_reason": source_snapshot.plan_lock_reason},
    )
    editor = ExperimentEditorDriver(
        runtime.context,
        action_runner=runtime.harness.run_action,
    ).inspect_lock_and_create_editable_copy(
        source_dir=spec.source_dir,
        source_name=spec.source_name,
        copy_name=spec.copy_name,
        copy_tolerance_nl=spec.copy_tolerance_nl,
    )
    runtime.harness.assert_no_unexpected_dialog()
    copy_snapshot = capture_authoritative_bundle(runtime.context)
    copy_finalized, source_after_copy = post_start_copy_boundary_evidence(
        source_snapshot,
        copy_snapshot,
        source_after=snapshot_directory(source_snapshot.experiment_dir),
        copy_name=spec.copy_name,
        copy_tolerance_nl=spec.copy_tolerance_nl,
        expected_well_ids=expected_well_ids,
    )
    return {
        "editor": dict(editor),
        "source_snapshot": source_snapshot,
        "copy_snapshot": copy_snapshot,
        "source_locked": source_locked,
        "copy_finalized": copy_finalized,
        "source_after_copy": source_after_copy,
    }


def bind_head_identities(
    runtime: JourneyRuntime,
    pass_specs: Sequence[
        StockPassSpec | CalibrationOnlySpec | PrecalibratedStockPassSpec
    ],
) -> Mapping[str, Any]:
    rack = RackDriver(runtime.context)
    bindings: list[dict[str, Any]] = []
    for spec in pass_specs:
        slot = rack.assigned_slot_for_stock(spec.stock_id)
        if slot is not None:
            head = runtime.context.model.rack_model.slots[slot].printer_head
        else:
            candidates = [
                head for head in runtime.context.model.printer_head_manager.printer_heads
                if str(head.get_stock_id()) == str(spec.stock_id)
            ]
            if len(candidates) != 1:
                raise RuntimeError(
                    f"expected one printer head for stock {spec.stock_id!r}; observed {len(candidates)}"
                )
            head = candidates[0]
        metadata = dict(head.get_identity_metadata())
        metadata["printer_head_id"] = spec.printer_head_id
        head.set_identity_metadata(**metadata)
        bindings.append(
            {
                "slot": slot,
                "stock_id": spec.stock_id,
                "printer_head_id": spec.printer_head_id,
            }
        )
    return {"bindings": bindings}


def head_identity_step(
    pass_specs: Sequence[
        StockPassSpec | CalibrationOnlySpec | PrecalibratedStockPassSpec
    ],
) -> SemanticStep:
    frozen = tuple(pass_specs)
    return SemanticStep(
        "head.bind_identity",
        InteractionSurface.MODEL,
        lambda runtime: bind_head_identities(runtime, frozen),
    )


def normalized_stock_pass_steps(
    pass_specs: Sequence[StockPassSpec],
) -> list[dict[str, Any]]:
    """Return a serializable plan without constructing Qt/application objects."""

    normalized: list[dict[str, Any]] = []
    if any(spec.bind_identity for spec in pass_specs):
        normalized.append(
            {
                "action_id": "head.bind_identity",
                "interaction_surface": "model",
            }
        )
    pressure_enabled = False
    for index, spec in enumerate(pass_specs):
        action_ids = [
            "machine.configure_print_settings_via_ui",
            "head.set_volume_via_ui",
            "head.stage_via_ui",
        ]
        if spec.enable_pressure_regulation and not pressure_enabled:
            action_ids.append("pressure.enable_regulation_via_ui")
            pressure_enabled = True
        action_ids.extend(
            [
                "calibration.open_via_ui",
                "calibration.generate_via_ui",
                "calibration.select_via_ui",
                "calibration.apply_via_ui",
            ]
        )
        if spec.expected_start_outcome == "calibration_apply_rejected":
            action_ids.extend(
                [
                    "machine.configure_print_settings_via_ui",
                    "calibration.generate_via_ui",
                    "calibration.select_via_ui",
                    "calibration.apply_via_ui",
                    "artifact.capture_milestone",
                ]
            )
        else:
            action_ids.append("array.start_via_ui")
        if spec.manual_refuel_check is not None:
            action_ids.insert(
                action_ids.index("array.start_via_ui"),
                "manual_refuel.complete_check_via_ui",
            )
        if spec.await_terminal_boundary and spec.expected_start_outcome == "running":
            action_ids.append("array.wait_for_completions")
        if spec.ready_milestone:
            action_ids.insert(action_ids.index("array.start_via_ui"), "artifact.capture_milestone")
        if spec.printing_milestone:
            if "array.wait_for_completions" in action_ids:
                action_ids.insert(
                    action_ids.index("array.wait_for_completions"),
                    "artifact.capture_milestone",
                )
            else:
                action_ids.append("artifact.capture_milestone")
        if spec.validate_pass_boundary and spec.expected_start_outcome == "running":
            action_ids.append("validation.stock_pass_boundary")
        if spec.completed_milestone:
            action_ids.append("artifact.capture_milestone")
        if spec.return_head:
            action_ids.append("head.return_via_ui")
        normalized.extend(
            {
                "action_id": action_id,
                "interaction_surface": (
                    "harness"
                    if action_id.startswith(("artifact.", "array.wait", "validation."))
                    else "ui"
                ),
                "pass_index": index + 1,
                "stock_id": spec.stock_id,
            }
            for action_id in action_ids
        )
    return normalized


def normalized_calibration_only_steps(
    spec: CalibrationOnlySpec,
) -> list[dict[str, str]]:
    """Return the bounded calibration-only ledger without constructing Qt."""

    action_ids = []
    if spec.bind_identity:
        action_ids.append("head.bind_identity")
    action_ids.extend([
        "machine.configure_print_settings_via_ui",
        "head.set_volume_via_ui",
        "head.stage_via_ui",
    ])
    if spec.enable_pressure_regulation:
        action_ids.append("pressure.enable_regulation_via_ui")
    action_ids.extend([
        "calibration.open_via_ui",
        "calibration.generate_via_ui",
        "calibration.select_via_ui",
        "calibration.apply_via_ui",
    ])
    if spec.return_head:
        action_ids.append("head.return_via_ui")
    return [
        {
            "action_id": action_id,
            "interaction_surface": "model" if action_id == "head.bind_identity" else "ui",
        }
        for action_id in action_ids
    ]


def normalized_precalibrated_stock_pass_steps(
    pass_specs: Sequence[PrecalibratedStockPassSpec],
) -> list[dict[str, Any]]:
    """Return the exact action ledger for already-calibrated stock passes."""

    specs = tuple(pass_specs)
    normalized: list[dict[str, Any]] = []
    if any(spec.bind_identity for spec in specs):
        normalized.append(
            {"action_id": "head.bind_identity", "interaction_surface": "model"}
        )
    harness_actions = {
        "array.wait_for_completions",
        "validation.stock_pass_boundary",
        "artifact.capture_milestone",
    }
    for index, spec in enumerate(specs):
        action_ids = [
            "machine.configure_print_settings_via_ui",
            "head.set_volume_via_ui",
            "head.stage_via_ui",
            "array.start_via_ui",
            "array.wait_for_completions",
        ]
        if spec.return_head and spec.expected_plan_state == "completed":
            action_ids.append("head.return_via_ui")
        action_ids.extend(
            ("validation.stock_pass_boundary", "artifact.capture_milestone")
        )
        if spec.return_head and spec.expected_plan_state != "completed":
            action_ids.append("head.return_via_ui")
        normalized.extend(
            {
                "action_id": action_id,
                "interaction_surface": (
                    "harness" if action_id in harness_actions else "ui"
                ),
                "pass_index": index + 1,
                "stock_id": spec.stock_id,
            }
            for action_id in action_ids
        )
    return normalized


def normalized_soft_stop_resume_steps(
    spec: SoftStopResumeSpec,
) -> list[dict[str, Any]]:
    """Return the stable stop/resume action window without constructing Qt."""

    action_ids = (
        "array.request_soft_stop_via_ui", "artifact.capture_milestone",
        "array.wait_for_state", "artifact.capture_milestone",
        "array.observe_stopped_quiescence", "array.resume_via_ui",
        "artifact.capture_milestone",
    )
    return [
        {
            "action_id": action_id,
            "interaction_surface": (
                "ui" if action_id in {
                    "array.request_soft_stop_via_ui", "array.resume_via_ui"
                } else "harness"
            ),
            "request_after_completion_count": spec.request_after_completion_count,
        }
        for action_id in action_ids
    ]


def normalized_disconnect_fail_closed_steps(
    spec: DisconnectFailClosedSpec,
) -> list[dict[str, Any]]:
    """Return the stable disconnect/recovery action window without Qt."""

    action_ids = (
        "machine.disconnect_via_ui",
        "artifact.capture_milestone",
        "array.observe_disconnected_quiescence",
        "artifact.capture_milestone",
    )
    return [
        {
            "action_id": action_id,
            "interaction_surface": (
                "ui" if action_id == "machine.disconnect_via_ui" else "harness"
            ),
            "disconnect_after_completion_count": (
                spec.disconnect_after_completion_count
            ),
        }
        for action_id in action_ids
    ]


def run_soft_stop_resume(
    runtime: JourneyRuntime,
    spec: SoftStopResumeSpec,
    *,
    paused_callback: Callable[[JourneyRuntime], Any] | None = None,
) -> Mapping[str, Any]:
    """Exercise and observe one paused boundary, then resume through the UI."""

    evidence = dict(run_soft_stop_boundary(runtime, spec))
    if paused_callback is not None:
        paused_callback(runtime)
    evidence["resume"] = resume_soft_stopped_array(
        runtime, milestone_name=spec.resumed_milestone
    )
    return evidence


def run_soft_stop_boundary(
    runtime: JourneyRuntime,
    spec: SoftStopResumeSpec,
) -> Mapping[str, Any]:
    """Request a bounded stop and retain paused/quiescence evidence."""

    context, observed = runtime.context, runtime.observations
    completed = observed["completed_wells"]
    request = request_soft_stop_via_ui(
        context,
        completed_count=lambda: len(completed),
        trigger_count=spec.request_after_completion_count,
        timeout_seconds=spec.timeout_seconds,
    )
    request_evidence = dict(request.get("evidence") or {})
    request_evidence["maximum_completion_catchup"] = spec.maximum_completion_catchup
    request_evidence["array_control"] = ArrayDriver(context).inspect_control(
        expected_text="Stop Pending",
        expected_enabled=False,
    )
    observed["soft_stop_request"] = request_evidence
    capture_milestone(
        context, spec.stop_requested_milestone, evidence=request_evidence
    )
    wait_for_array_state(
        context,
        state="resume_ready",
        timeout_seconds=spec.timeout_seconds,
        label="soft-stop resume-ready boundary",
    )
    observed["paused_execution_snapshot"] = observed["execution_observer"].snapshot()
    capture_milestone(
        context,
        spec.stopped_milestone,
        evidence={
            "completed_count": len(completed),
            "array_state": context.controller.get_array_run_state(),
            "array_control": ArrayDriver(context).inspect_control(
                expected_text="Resume Print",
                expected_enabled=True,
            ),
        },
    )
    quiescence_row = observe_stopped_quiescence(
        context,
        completed_count=lambda: len(completed),
        progress_count=lambda: sum(
            int(reagent.get("added_droplets", 0))
            for well in (context.experiment_model.progress_data or {}).values()
            for reagent in (well.get("reagents") or {}).values()
        ),
        observation_ms=spec.quiescence_observation_ms,
    )
    quiescence = dict(quiescence_row.get("evidence") or {})
    observed["stopped_quiescence"] = quiescence
    return {"request": request_evidence, "quiescence": quiescence}


def run_disconnect_fail_closed_boundary(
    runtime: JourneyRuntime,
    spec: DisconnectFailClosedSpec,
) -> Mapping[str, Any]:
    """Disconnect at one exact completion and retain recovery evidence."""

    context, observed = runtime.context, runtime.observations
    completed = observed["completed_wells"]
    result = disconnect_machine_via_ui(
        context,
        completed_count=lambda: len(completed),
        trigger_count=spec.disconnect_after_completion_count,
        timeout_seconds=spec.timeout_seconds,
    )
    request = dict(result.get("evidence") or {})
    request["expected_canceled_intent_count"] = (
        spec.expected_canceled_intent_count
    )
    observed["disconnect_request"] = request
    capture_milestone(
        context,
        spec.disconnected_milestone,
        evidence={
            "completed_count": len(completed),
            "array_state": context.controller.get_array_run_state(),
            "simulator_connected": bool(context.machine.state.connected),
        },
    )
    quiescence_result = observe_disconnected_quiescence(
        context,
        completed_count=lambda: len(completed),
        progress_count=lambda: sum(
            int(reagent.get("added_droplets", 0))
            for well in (context.experiment_model.progress_data or {}).values()
            for reagent in (well.get("reagents") or {}).values()
        ),
        observation_ms=spec.quiescence_observation_ms,
    )
    quiescence = dict(quiescence_result.get("evidence") or {})
    observed["disconnected_quiescence"] = quiescence
    recovery = {
        "array_state": context.controller.get_array_run_state(),
        "plan_state": context.experiment_model.get_execution_plan_snapshot().state.value,
        "eligibility": context.experiment_model.get_execution_resume_eligibility(),
        "dock_check_reasons": context.controller._get_evap_plate_dock_check_reasons(),
        "model_connected": bool(context.model.machine_model.is_connected()),
        "simulator_connected": bool(context.machine.state.connected),
        "motors_homed": bool(context.model.machine_model.motors_are_homed()),
    }
    observed["disconnect_recovery"] = recovery
    capture_milestone(
        context,
        spec.recovery_milestone,
        evidence=recovery,
    )
    return {"request": request, "quiescence": quiescence, "recovery": recovery}


def resume_soft_stopped_array(
    runtime: JourneyRuntime,
    *,
    milestone_name: str = "resumed",
) -> Mapping[str, Any]:
    """Resume an already validated paused boundary through the normal UI."""

    context = runtime.context
    resume = resume_array_via_ui(context)
    evidence = dict(resume.get("evidence") or {})
    runtime.observations["resume_evidence"] = evidence
    capture_milestone(
        context,
        milestone_name,
        evidence={
            "array_state": context.controller.get_array_run_state(),
            "array_control": ArrayDriver(context).inspect_control(
                expected_text="Stop After Well",
                expected_enabled=True,
            ),
        },
    )
    return evidence


def _stage_stock_head(
    runtime: JourneyRuntime,
    spec: StockPassSpec | CalibrationOnlySpec | PrecalibratedStockPassSpec,
    *,
    index: int,
    head_staging: list[dict[str, Any]],
    returned_head_ids: list[str],
    persisted: bool = False,
) -> tuple[MachineControlsDriver, RackDriver, int, list[dict[str, Any]]]:
    """Configure, fill, and stage a stock head through shared UI mechanics."""

    context = runtime.context
    machine = MachineControlsDriver(context)
    rack = RackDriver(context)
    assigned_slot = rack.assigned_slot_for_stock(spec.stock_id)
    slot = assigned_slot if assigned_slot is not None else spec.staging_slot
    if slot is None:
        raise RuntimeError(f"stock {spec.stock_id!r} is unassigned and has no staging slot")
    slot = int(slot)

    def configure(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        machine.configure_print_settings(
            pulse_width_us=spec.pulse_width_us,
            pressure_psi=spec.pressure_psi,
            frequency_hz=spec.frequency_hz,
            refuel_pulse_width_us=spec.refuel_pulse_width_us,
            refuel_pressure_psi=spec.refuel_pressure_psi,
        )
        evidence = {
            "pulse_width_us": spec.pulse_width_us,
            "pressure_psi": spec.pressure_psi,
            "calibration_mode": spec.calibration_mode,
        }
        if spec.refuel_pulse_width_us is not None:
            evidence["refuel_pulse_width_us"] = spec.refuel_pulse_width_us
        if spec.refuel_pressure_psi is not None:
            evidence["refuel_pressure_psi"] = spec.refuel_pressure_psi
        if persisted or spec.include_frequency_evidence:
            evidence["frequency_hz"] = spec.frequency_hz
        return evidence

    def set_volume(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        swap = None
        if rack.assigned_slot_for_stock(spec.stock_id) is None:
            swap = rack.swap_unassigned_head(slot, spec.stock_id)
        rack.set_slot_volume(slot, spec.initial_volume_uL)
        return {"slot": slot, "volume_uL": spec.initial_volume_uL, "swap": swap}

    def stage(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        state_before = context.controller.get_array_run_state()
        drained_before = bool(context.machine.check_if_all_completed())
        rack.confirm_and_load(slot)
        head = context.model.rack_model.get_gripper_printer_head()
        if persisted or not spec.detailed_evidence:
            return {
                "slot": slot,
                "stock_id": str(head.get_stock_id()),
                **({"printer_head_id": str(head.printer_head_id),
                    "persisted_calibration_reused": True} if persisted else {}),
            }
        evidence = {
            "pass_index": index + 1,
            "slot": slot,
            "stock_id": spec.stock_id,
            "printer_head_id": str(head.printer_head_id),
            "array_state_before": state_before,
            "queue_drained_before": drained_before,
            "returned_previous": index > 0 and len(returned_head_ids) >= index,
            "requested_print_pulse_width_us": spec.pulse_width_us,
            "effective_print_pulse_width_us": int(
                context.model.machine_model.get_print_pulse_width()
            ),
            "requested_print_pressure_psi": spec.pressure_psi,
            "effective_print_pressure_psi": float(
                context.model.machine_model.get_target_print_pressure()
            ),
            "queue_drained_after": bool(context.machine.check_if_all_completed()),
        }
        head_staging.append(evidence)
        return evidence

    rows = runtime.run_steps(
        (
            SemanticStep(
                "machine.configure_print_settings_via_ui",
                InteractionSurface.UI,
                configure,
            ),
            SemanticStep("head.set_volume_via_ui", InteractionSurface.UI, set_volume),
            SemanticStep("head.stage_via_ui", InteractionSurface.UI, stage),
        )
    )
    return machine, rack, slot, rows


def run_stock_calibration_only(
    runtime: JourneyRuntime,
    spec: CalibrationOnlySpec,
) -> Mapping[str, Any]:
    """Stage and calibrate one head through real UI without array execution."""

    if spec.bind_identity:
        runtime.run_steps((head_identity_step((spec,)),))
    machine, rack, slot, staging_rows = _stage_stock_head(
        runtime,
        spec,
        index=0,
        head_staging=[],
        returned_head_ids=[],
    )
    if spec.enable_pressure_regulation:
        runtime.run_steps(
            (
                SemanticStep(
                    "pressure.enable_regulation_via_ui",
                    InteractionSurface.UI,
                    lambda _runtime: machine.enable_pressure_regulation()
                    or {"regulating_print_pressure": True},
                ),
            )
        )
    dialog_state: dict[str, Any] = {}

    def open_calibration(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        dialog_state["dialog"] = machine.open_calibration_dialog()
        return {"window_title": dialog_state["dialog"].windowTitle()}

    runtime.run_steps(
        (
            SemanticStep(
                "calibration.open_via_ui",
                InteractionSurface.UI,
                open_calibration,
            ),
        )
    )
    driver = CalibrationDialogDriver(
        runtime.context.app,
        dialog_state["dialog"],
        timeout_seconds=min(20.0, runtime.context.deadline.remaining_seconds()),
    )
    generated: dict[str, Any] = {}
    selected: dict[str, Any] = {}
    transition: dict[str, Any] = {}

    def generate(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        generated.update(
            driver.generate_from_tab(
                spec.calibration_mode,
                print_profile_id=spec.calibration_print_profile_id,
            )
        )
        return {
            "stock_id": spec.stock_id,
            "result_fingerprint": generated.get("synthetic_result_fingerprint"),
            "printing_mode": generated.get("printing_mode"),
        }

    def select(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        selected.update(
            driver.select_result(str(generated["synthetic_result_fingerprint"]))
        )
        return {
            "stock_id": spec.stock_id,
            "result_fingerprint": selected.get("synthetic_result_fingerprint"),
        }

    def apply(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        before = capture_count_snapshot(runtime.context)
        before_plan = runtime.context.experiment_model.get_execution_plan_snapshot()
        before_effective_volumes = {
            row.stock_id: float(row.effective_volume_nL)
            for row in before_plan.stocks
        }
        preview = driver.inspect_preview()
        handled = driver.apply_selected(expected_title=spec.apply_success_title)
        driver.close()
        after = capture_count_snapshot(runtime.context)
        after_plan = runtime.context.experiment_model.get_execution_plan_snapshot()
        after_effective_volumes = {
            row.stock_id: float(row.effective_volume_nL)
            for row in after_plan.stocks
        }
        transition.update(
            {
                "stock_id": spec.stock_id,
                "printer_head_id": spec.printer_head_id,
                "expected_volume_nL": spec.expected_volume_nL,
                "preview": preview,
                "handled_dialogs": handled,
                "before": before,
                "after": after,
                "before_effective_volumes_nL": before_effective_volumes,
                "after_effective_volumes_nL": after_effective_volumes,
            }
        )
        return dict(transition)

    runtime.run_steps(
        (
            SemanticStep("calibration.generate_via_ui", InteractionSurface.UI, generate),
            SemanticStep("calibration.select_via_ui", InteractionSurface.UI, select),
            SemanticStep("calibration.apply_via_ui", InteractionSurface.UI, apply),
        )
    )
    rack.wait_until(
        lambda: runtime.context.machine.check_if_all_completed(),
        "calibration-only simulator drain boundary",
        timeout_seconds=min(20.0, runtime.context.deadline.remaining_seconds()),
    )
    returned: Mapping[str, Any] | None = None
    if spec.return_head:
        def return_head(_runtime: JourneyRuntime) -> Mapping[str, Any]:
            rack.wait_until(
                lambda: runtime.context.controller.get_array_run_state() == "idle"
                and runtime.context.machine.check_if_all_completed(),
                "idle drained calibration-only return boundary",
                timeout_seconds=min(
                    20.0, runtime.context.deadline.remaining_seconds()
                ),
            )
            active = runtime.context.model.rack_model.get_gripper_printer_head()
            if active is None or str(active.get_stock_id()) != spec.stock_id:
                raise RuntimeError("calibration-only return stock identity drifted")
            rack.unload(slot)
            return {
                "slot": slot,
                "stock_id": spec.stock_id,
                "printer_head_id": str(active.printer_head_id),
                "returned": True,
            }

        returned = runtime.run_steps(
            (
                SemanticStep(
                    "head.return_via_ui",
                    InteractionSurface.UI,
                    return_head,
                ),
            )
        )[0]["evidence"]
    runtime.harness.assert_no_unexpected_dialog()
    evidence = {
        "slot": slot,
        "stock_id": spec.stock_id,
        "printer_head_id": spec.printer_head_id,
        "staging_actions": [dict(row) for row in staging_rows],
        "generated": generated,
        "selected": selected,
        "count_transition": transition,
        "queue_drained": bool(runtime.context.machine.check_if_all_completed()),
        "return": dict(returned or {}),
    }
    runtime.observations.setdefault("calibration_count_transitions", []).append(
        dict(transition)
    )
    runtime.observations["calibration_only"] = evidence
    return evidence


def run_progressed_paired_calibration_guard(
    runtime: JourneyRuntime,
    spec: CalibrationOnlySpec,
) -> Mapping[str, Any]:
    """Record a real diagnostic result and prove paired Apply is unavailable."""

    from tools.virtual_workflows.authoritative_evidence import (
        capture_authoritative_bundle,
    )

    if spec.bind_identity:
        runtime.run_steps((head_identity_step((spec,)),))
    machine, _rack, _slot, staging = _stage_stock_head(
        runtime,
        spec,
        index=0,
        head_staging=[],
        returned_head_ids=[],
    )
    dialog_state: dict[str, Any] = {}

    def open_calibration(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        dialog_state["dialog"] = machine.open_calibration_dialog()
        return {"window_title": dialog_state["dialog"].windowTitle()}

    runtime.run_steps(
        (
            SemanticStep(
                "calibration.open_via_ui",
                InteractionSurface.UI,
                open_calibration,
            ),
        )
    )
    driver = CalibrationDialogDriver(
        runtime.context.app,
        dialog_state["dialog"],
        timeout_seconds=min(20.0, runtime.context.deadline.remaining_seconds()),
    )
    generated: dict[str, Any] = {}
    before_bundle = capture_authoritative_bundle(runtime.context)
    before_counts = capture_count_snapshot(runtime.context)
    before_dispatch = {
        "begins": len(runtime.context.instrumentation.intent_begins),
        "attachments": len(runtime.context.instrumentation.intent_attachments),
        "completions": len(runtime.context.instrumentation.intent_completions),
    }
    summary_rows_before = int(driver.dialog.summary_table_model.rowCount())

    def generate(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        generated.update(
            driver.generate_from_tab(
                spec.calibration_mode,
                print_profile_id=spec.calibration_print_profile_id,
                diagnostic_confirmation="record",
            )
        )
        return {
            "result_fingerprint": generated.get("synthetic_result_fingerprint"),
            "diagnostic_confirmation": "record",
        }

    def select(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        return driver.select_result(
            str(generated["synthetic_result_fingerprint"])
        )

    runtime.run_steps(
        (
            SemanticStep(
                "calibration.generate_via_ui",
                InteractionSurface.UI,
                generate,
            ),
            SemanticStep(
                "calibration.select_via_ui",
                InteractionSurface.UI,
                select,
            ),
        )
    )

    boundary: dict[str, Any] = {}

    def inspect_blocked_apply(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        from PySide6 import QtCore, QtTest

        state = driver.inspect_apply_state()
        before_click = capture_count_snapshot(runtime.context)
        QtTest.QTest.mouseClick(
            driver.dialog.bridge_apply_btn,
            QtCore.Qt.MouseButton.LeftButton,
        )
        runtime.context.app.processEvents()
        after_click = capture_count_snapshot(runtime.context)
        boundary.update(
            {
                "apply_state": state,
                "before_click": before_click,
                "after_click": after_click,
            }
        )
        return dict(boundary)

    runtime.run_steps(
        (
            SemanticStep(
                "calibration.apply_progressed_stock_via_ui",
                InteractionSurface.UI,
                inspect_blocked_apply,
            ),
        )
    )
    driver.close()
    after_bundle = capture_authoritative_bundle(runtime.context)
    after_counts = capture_count_snapshot(runtime.context)
    after_dispatch = {
        "begins": len(runtime.context.instrumentation.intent_begins),
        "attachments": len(runtime.context.instrumentation.intent_attachments),
        "completions": len(runtime.context.instrumentation.intent_completions),
    }
    evidence = {
        "stock_id": spec.stock_id,
        "printer_head_id": spec.printer_head_id,
        "staging_actions": [dict(row) for row in staging],
        "generated": generated,
        "summary_rows_before": summary_rows_before,
        "summary_rows_after": int(driver.dialog.summary_table_model.rowCount()),
        "before_bundle": before_bundle,
        "after_bundle": after_bundle,
        "before_counts": before_counts,
        "after_counts": after_counts,
        "before_dispatch": before_dispatch,
        "after_dispatch": after_dispatch,
        **boundary,
    }
    runtime.observations["paired_progress_guard"] = evidence
    return evidence


def _expected_completed_array_control_text(
    *,
    expected_plan_state: str,
    head_returned: bool,
) -> str:
    """Return the disabled array-control label at a completed pass boundary."""

    if not head_returned:
        return "Array Complete"
    if str(expected_plan_state) == "completed":
        return "Experiment Complete"
    return "Start Array"


def run_precalibrated_stock_passes(
    runtime: JourneyRuntime,
    pass_specs: Sequence[PrecalibratedStockPassSpec],
    *,
    after_pass: Callable[[JourneyRuntime, int, PrecalibratedStockPassSpec], Any]
    | None = None,
) -> None:
    """Execute explicit stock-ID passes without reopening calibration."""

    from PySide6 import QtWidgets

    specs = tuple(pass_specs)
    if not specs:
        raise ValueError("at least one precalibrated stock pass is required")
    if any(spec.bind_identity for spec in specs):
        runtime.run_steps((head_identity_step(specs),))

    observations = runtime.observations
    completed_wells = observations.setdefault("completed_wells", [])
    pass_boundaries = observations.setdefault("pass_boundaries", [])
    head_staging = observations.setdefault("head_staging", [])
    returned_head_ids = observations.setdefault("returned_head_ids", [])
    current_pass = observations.setdefault(
        "current_pass", {"index": -1, "starting_count": 0, "stock_id": None}
    )

    for index, spec in enumerate(specs):
        current_pass.update(
            {
                "index": index,
                "starting_count": len(completed_wells),
                "stock_id": spec.stock_id,
            }
        )
        _machine, rack, slot, _rows = _stage_stock_head(
            runtime,
            spec,
            index=index,
            head_staging=head_staging,
            returned_head_ids=returned_head_ids,
        )
        expected_dialogs = [
            (title, QtWidgets.QMessageBox.StandardButton.Yes)
            for title in spec.start_dialog_titles
        ]
        array = ArrayDriver(runtime.context)
        runtime.run_steps(
            (
                SemanticStep(
                    "array.start_via_ui",
                    InteractionSurface.UI,
                    lambda _runtime, dialogs=expected_dialogs: {
                        "dialogs": array.start(dialogs)
                    },
                ),
                SemanticStep(
                    "array.wait_for_completions",
                    InteractionSurface.HARNESS,
                    lambda _runtime, current=spec: wait_for_execution_boundary(
                        runtime,
                        expected_count=current.expected_completion_count,
                        expected_plan_state=current.expected_plan_state,
                        strict=True,
                    ),
                ),
            )
        )

        def return_active_head(_runtime: JourneyRuntime) -> Mapping[str, Any]:
            active = runtime.context.model.rack_model.get_gripper_printer_head()
            if active is None:
                raise RuntimeError("precalibrated stock-pass head is absent")
            if (
                str(active.get_stock_id()) != spec.stock_id
                or str(active.printer_head_id) != spec.printer_head_id
            ):
                raise RuntimeError("precalibrated stock-pass return identity drifted")
            array_control = array.inspect_control(
                expected_text="Array Complete",
                expected_enabled=False,
            )
            rack.unload(slot)
            returned_head_ids.append(spec.printer_head_id)
            return {
                "slot": slot,
                "stock_id": spec.stock_id,
                "printer_head_id": spec.printer_head_id,
                "array_state_before": runtime.context.controller.get_array_run_state(),
                "queue_drained_before": bool(
                    runtime.context.machine.check_if_all_completed()
                ),
                "array_control_before_return": array_control,
                "returned": True,
            }

        returned_before_validation = (
            spec.return_head and spec.expected_plan_state == "completed"
        )
        if returned_before_validation:
            runtime.run_steps(
                (
                    SemanticStep(
                        "head.return_via_ui",
                        InteractionSurface.UI,
                        return_active_head,
                    ),
                )
            )
        runtime.run_steps(
            (
                SemanticStep(
                    "validation.stock_pass_boundary",
                    InteractionSurface.HARNESS,
                    lambda _runtime, current=spec, current_index=index: (
                        validate_stock_pass_boundary(
                            runtime,
                            current,
                            index=current_index,
                            pass_boundaries=pass_boundaries,
                        )
                    ),
                ),
            )
        )
        if spec.capture_completed_milestone:
            array_control = array.inspect_control(
                expected_text=_expected_completed_array_control_text(
                    expected_plan_state=spec.expected_plan_state,
                    head_returned=returned_before_validation,
                ),
                expected_enabled=False,
            )
            capture_milestone(
                runtime.context,
                spec.completed_milestone,
                evidence={
                    "stock_id": spec.stock_id,
                    "printer_head_id": spec.printer_head_id,
                    "completion_count": spec.expected_completion_count,
                    "array_control": array_control,
                },
            )
        if after_pass is not None:
            after_pass(runtime, index, spec)
        if spec.return_head and not returned_before_validation:
            runtime.run_steps(
                (
                    SemanticStep(
                        "head.return_via_ui",
                        InteractionSurface.UI,
                        return_active_head,
                    ),
                )
            )


def prepare_persisted_head_for_resume(
    runtime: JourneyRuntime,
    spec: StockPassSpec,
) -> Mapping[str, Any]:
    """Restage a persisted calibrated head without generating a new result."""

    machine, _rack, slot, rows = _stage_stock_head(
        runtime, spec, index=0, head_staging=[], returned_head_ids=[], persisted=True
    )
    rows.extend(runtime.run_steps((SemanticStep(
        "pressure.enable_regulation_via_ui",
        InteractionSurface.UI,
        lambda _runtime: machine.enable_pressure_regulation()
        or {"regulating_print_pressure": True},
    ),)))
    return {
        "slot": slot,
        "actions": [dict(row) for row in rows],
        "persisted_calibration_reused": True,
    }


def run_authoritative_reload_resume_boundary(
    runtime: JourneyRuntime,
    *,
    stock_spec: StockPassSpec,
    soft_stop_spec: SoftStopResumeSpec,
    expectation: Any,
    expected_name: str,
    rebind_execution_signals: Callable[[], None],
    install_starvation_observer: Callable[[], None],
) -> Mapping[str, Any]:
    """Pause, rotate application sessions, reload, restage, and resume."""

    from tools.virtual_workflows.assertions import (
        authoritative_first_session_paused_assertion,
        authoritative_reload_boundary_assertions,
        authoritative_session_rotation_assertions,
        soft_stop_paused_assertions,
    )
    from tools.virtual_workflows.authoritative_evidence import (
        authoritative_loaded_boundary,
        authoritative_reload_boundaries,
        capture_authoritative_bundle,
        completed_stock_well_pairs,
        compare_directories,
        snapshot_directory,
    )
    from tools.virtual_workflows.execution_observer import ExecutionObserver

    context = runtime.context
    run_soft_stop_boundary(runtime, soft_stop_spec)
    paused_results = soft_stop_paused_assertions(
        context,
        expectation=expectation,
        request_evidence=runtime.observations["soft_stop_request"],
        completed_count=len(runtime.observations["completed_wells"]),
        intent_lifecycle=runtime.observations["paused_execution_snapshot"][
            "lifecycle"
        ],
        quiescence=runtime.observations["stopped_quiescence"],
    )
    runtime.observations["paused_validation"] = dict(paused_results[1].evidence)
    paused_assertion = authoritative_first_session_paused_assertion(paused_results)
    paused_bundle = capture_authoritative_bundle(context)
    runtime.restore_all()
    first_snapshot = runtime.observations["session_1_execution_snapshot"]
    lifecycle_1 = dict(first_snapshot["lifecycle"])
    completed_pairs = completed_stock_well_pairs(lifecycle_1)

    first_close = runtime.harness.close_application_session()["evidence"]
    close_comparison = compare_directories(
        paused_bundle.directory,
        snapshot_directory(paused_bundle.experiment_dir),
    ).to_dict()
    second_launch = runtime.harness.reopen_application_session()["evidence"]
    fresh, teardown = authoritative_session_rotation_assertions(
        first_close=first_close,
        second_launch=second_launch,
        application_sessions=runtime.harness.application_sessions,
        files_byte_identical=close_comparison["checks"]["files_byte_identical"],
    )
    for result in (fresh, paused_assertion, teardown):
        runtime.add_assertion(result)

    rebind_execution_signals()
    second_observer = ExecutionObserver(
        context,
        experiment_dir=expectation.experiment_dir,
        completed_count=lambda: len(runtime.observations["completed_wells"]),
        pass_context=lambda: _active_pass_context(runtime),
    )
    runtime.observations["execution_observer"] = second_observer
    runtime.register_restorable("session_2_execution", second_observer)
    second_observer.install()
    install_starvation_observer()
    boundaries: dict[str, Any] = {}
    loaded_snapshot: dict[str, Any] = {}

    def validate_loaded() -> Mapping[str, Any]:
        loaded = capture_authoritative_bundle(context)
        loaded_snapshot["value"] = loaded
        evidence = authoritative_loaded_boundary(paused_bundle, loaded)
        if evidence["failed_checks"]:
            raise RuntimeError("authoritative load boundary is invalid")
        boundaries["loaded"] = evidence
        return evidence

    def validate_activated() -> Mapping[str, Any]:
        loaded, activated = authoritative_reload_boundaries(
            paused_bundle,
            loaded_snapshot["value"],
            capture_authoritative_bundle(context),
            completed_pair_count=len(completed_pairs),
        )
        if loaded["failed_checks"] or activated["failed_checks"]:
            raise RuntimeError("authoritative activation boundary is invalid")
        boundaries.update({"loaded": loaded, "activated": activated})
        return activated

    editor = ExperimentLoaderDriver(context).load_authoritative_execution(
        expectation.experiment_dir,
        expected_name=expected_name,
        before_activation=validate_loaded,
        after_activation=validate_activated,
    )
    capture_milestone(context, "session_2_activated", evidence=editor["activated"])
    for result in authoritative_reload_boundary_assertions(
        loaded=boundaries["loaded"], activated=boundaries["activated"]
    ):
        runtime.add_assertion(result)
    runtime.run_steps(machine_startup_steps())
    resume_head = prepare_persisted_head_for_resume(runtime, stock_spec)
    resume_soft_stopped_array(
        runtime, milestone_name=soft_stop_spec.resumed_milestone
    )
    evidence = {
        "session_1_bundle": paused_bundle,
        "session_1_lifecycle": lifecycle_1,
        "session_1_completed_pairs": completed_pairs,
        "session_1_cleanup": first_close,
        "reload_boundaries": boundaries,
        "resume_head": resume_head,
        "between_sessions": {
            **close_comparison,
            "byte_identical": close_comparison["checks"]["files_byte_identical"],
        },
    }
    runtime.observations.update(evidence)
    return evidence


def run_clean_authoritative_session_rotation_boundary(
    runtime: JourneyRuntime,
    *,
    experiment_dir: str | Path,
    expected_name: str,
    completed_count: Callable[[], int],
    pass_context: Callable[[], Mapping[str, Any] | None],
    inspect_loaded: Callable[[], Mapping[str, Any]] | None = None,
    inspect_activated: Callable[[], Mapping[str, Any]] | None = None,
    loaded_hook: Callable[[JourneyRuntime], Any] | None = None,
    activated_hook: Callable[[JourneyRuntime], Any] | None = None,
    observer_key: str = "session_2_execution",
) -> Mapping[str, Any]:
    """Rotate and explicitly activate a clean authoritative start boundary."""

    from tools.virtual_workflows.assertions import (
        authoritative_reload_boundary_assertions,
        authoritative_session_rotation_assertions,
    )
    from tools.virtual_workflows.authoritative_evidence import (
        capture_authoritative_bundle,
        clean_authoritative_loaded_boundary,
        clean_authoritative_rotation_boundaries,
        compare_directories,
        snapshot_directory,
    )
    from tools.virtual_workflows.execution_observer import ExecutionObserver

    context = runtime.context
    source = capture_authoritative_bundle(context)
    runtime.restore_all()
    first_close = runtime.harness.close_application_session()["evidence"]
    close_comparison = compare_directories(
        source.directory,
        snapshot_directory(source.experiment_dir),
    ).to_dict()
    second_launch = runtime.harness.reopen_application_session()["evidence"]
    fresh, teardown = authoritative_session_rotation_assertions(
        first_close=first_close,
        second_launch=second_launch,
        application_sessions=runtime.harness.application_sessions,
        files_byte_identical=close_comparison["checks"]["files_byte_identical"],
    )
    runtime.add_assertion(fresh)
    runtime.add_assertion(teardown)

    observer = ExecutionObserver(
        context,
        experiment_dir=Path(experiment_dir).resolve(),
        completed_count=completed_count,
        pass_context=pass_context,
    )
    runtime.observations["execution_observer"] = observer
    runtime.register_restorable(observer_key, observer)
    observer.install()

    boundaries: dict[str, Any] = {}
    snapshots: dict[str, Any] = {}
    inspections: dict[str, Mapping[str, Any]] = {}

    def validate_loaded() -> Mapping[str, Any]:
        loaded = capture_authoritative_bundle(context)
        snapshots["loaded"] = loaded
        evidence = clean_authoritative_loaded_boundary(source, loaded)
        if evidence["failed_checks"]:
            raise RuntimeError(
                "clean authoritative load boundary is invalid: "
                + ", ".join(evidence["failed_checks"])
            )
        boundaries["loaded"] = evidence
        if inspect_loaded is not None:
            inspections["loaded"] = dict(inspect_loaded())
        if loaded_hook is not None:
            loaded_hook(runtime)
        return evidence

    def validate_activated() -> Mapping[str, Any]:
        activated = capture_authoritative_bundle(context)
        snapshots["activated"] = activated
        loaded, activation = clean_authoritative_rotation_boundaries(
            source,
            snapshots["loaded"],
            activated,
        )
        if loaded["failed_checks"] or activation["failed_checks"]:
            raise RuntimeError(
                "clean authoritative activation boundary is invalid: "
                + ", ".join((*loaded["failed_checks"], *activation["failed_checks"]))
            )
        boundaries.update({"loaded": loaded, "activated": activation})
        if inspect_activated is not None:
            inspections["activated"] = dict(inspect_activated())
        if activated_hook is not None:
            activated_hook(runtime)
        return activation

    editor = ExperimentLoaderDriver(context).load_authoritative_execution(
        Path(experiment_dir).resolve(),
        expected_name=expected_name,
        before_activation=validate_loaded,
        after_activation=validate_activated,
        expected_eligibility_status="ready_to_start",
        expected_array_state="idle",
        loaded_milestone_name="fresh_loaded",
    )
    capture_milestone(context, "fresh_activated", evidence=editor["activated"])
    for result in authoritative_reload_boundary_assertions(
        loaded=boundaries["loaded"],
        activated=boundaries["activated"],
    ):
        runtime.add_assertion(result)

    evidence = {
        "source_bundle": source,
        "loaded_bundle": snapshots["loaded"],
        "activated_bundle": snapshots["activated"],
        "first_session_cleanup": first_close,
        "second_session_launch": second_launch,
        "application_sessions": [
            dict(row) for row in runtime.harness.application_sessions
        ],
        "between_sessions": {
            **close_comparison,
            "byte_identical": close_comparison["checks"]["files_byte_identical"],
        },
        "reload_boundaries": boundaries,
        "inspections": inspections,
        "editor": editor,
        "observer_key": observer_key,
    }
    runtime.observations["clean_session_rotation"] = evidence
    return evidence


def _active_pass_context(runtime: JourneyRuntime) -> Mapping[str, Any] | None:
    current = runtime.observations.get("current_pass", {})
    if int(current.get("index", -1)) < 0:
        return None
    return {
        "pass_index": int(current["index"]) + 1,
        "stock_id": current.get("stock_id"),
    }


def run_stock_passes(
    runtime: JourneyRuntime,
    pass_specs: Sequence[StockPassSpec],
    *,
    bind_identities: bool = True,
    active_phase: Callable[[JourneyRuntime, StockPassSpec], Any] | None = None,
) -> Mapping[str, Any] | None:
    """Execute ordered head passes through existing page drivers and QTest."""

    specs = tuple(pass_specs)
    if bind_identities and any(spec.bind_identity for spec in specs):
        runtime.run_steps((head_identity_step(specs),))

    observations = runtime.observations
    completed_wells = observations.setdefault("completed_wells", [])
    pass_boundaries = observations.setdefault("pass_boundaries", [])
    head_staging = observations.setdefault("head_staging", [])
    returned_head_ids = observations.setdefault("returned_head_ids", [])
    current_pass = observations.setdefault(
        "current_pass", {"index": -1, "starting_count": 0, "stock_id": None}
    )
    pressure_enabled = False

    for index, spec in enumerate(specs):
        current_pass.update(
            {
                "index": index,
                "starting_count": len(completed_wells),
                "stock_id": spec.stock_id,
            }
        )
        result = _run_stock_pass(
            runtime,
            spec,
            index=index,
            pressure_enabled=pressure_enabled,
            pass_boundaries=pass_boundaries,
            head_staging=head_staging,
            returned_head_ids=returned_head_ids,
            active_phase=active_phase,
        )
        pressure_enabled = pressure_enabled or spec.enable_pressure_regulation
        if result is not None and result.get("terminal") == "manual_refuel_cancelled":
            return result
    return None


def capture_completion_midpoint(
    runtime: JourneyRuntime,
    completion_count: int,
    *,
    milestone: str = "mid_array",
) -> Mapping[str, Any]:
    """Wait through the harness, then capture one named completion midpoint."""

    if completion_count < 1:
        raise ValueError("completion midpoint must be positive")
    from tools.virtual_workflows.actions import wait_for_completions

    wait_for_completions(
        runtime.context,
        completed_count=lambda: len(runtime.observations["completed_wells"]),
        target_count=completion_count,
        timeout_seconds=min(30.0, runtime.context.deadline.remaining_seconds()),
        label=f"{milestone} completion",
    )
    return capture_milestone(
        runtime.context,
        milestone,
        evidence={
            "completion_count": len(runtime.observations["completed_wells"])
        },
    )


def _run_stock_pass(
    runtime: JourneyRuntime,
    spec: StockPassSpec,
    *,
    index: int,
    pressure_enabled: bool,
    pass_boundaries: list[dict[str, Any]],
    head_staging: list[dict[str, Any]],
    returned_head_ids: list[str],
    active_phase: Callable[[JourneyRuntime, StockPassSpec], Any] | None,
) -> Mapping[str, Any] | None:
    context = runtime.context
    machine, rack, slot, _rows = _stage_stock_head(
        runtime,
        spec,
        index=index,
        head_staging=head_staging,
        returned_head_ids=returned_head_ids,
    )
    if spec.enable_pressure_regulation and not pressure_enabled:
        runtime.run_steps(
            (
                SemanticStep(
                    "pressure.enable_regulation_via_ui",
                    InteractionSurface.UI,
                    lambda _runtime: machine.enable_pressure_regulation(
                        require_refuel=(
                            spec.manual_refuel_check is not None
                            or spec.require_refuel_regulation
                        )
                    )
                    or {"regulating_print_pressure": True},
                ),
            )
        )

    dialog_state: dict[str, Any] = {}
    generated: dict[str, Any] = {}

    def open_calibration(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        dialog_state["dialog"] = machine.open_calibration_dialog()
        return {"window_title": dialog_state["dialog"].windowTitle()}

    returned_before_boundary = False

    def return_active_head(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        rack.wait_until(
            lambda: context.controller.get_array_run_state() == "idle"
            and context.machine.check_if_all_completed(),
            "idle drained stock-pass return boundary",
            timeout_seconds=min(20.0, context.deadline.remaining_seconds()),
        )
        active = context.model.rack_model.get_gripper_printer_head()
        head_id = str(active.printer_head_id)
        stock_id = str(active.get_stock_id())
        state_before = context.controller.get_array_run_state()
        drained_before = bool(context.machine.check_if_all_completed())
        array_control = None
        if spec.expected_start_outcome == "running":
            array_control = ArrayDriver(context).inspect_control(
                expected_text="Array Complete",
                expected_enabled=False,
            )
        rack.unload(slot)
        returned_head_ids.append(head_id)
        evidence = {
            "slot": slot, "stock_id": stock_id, "printer_head_id": head_id,
            "array_state_before": state_before,
            "queue_drained_before": drained_before, "returned": True,
        }
        if array_control is not None:
            evidence["array_control_before_return"] = array_control
        return evidence

    runtime.run_steps(
        (
            SemanticStep(
                "calibration.open_via_ui",
                InteractionSurface.UI,
                open_calibration,
            ),
        )
    )
    calibration = CalibrationDialogDriver(
        context.app,
        dialog_state["dialog"],
        timeout_seconds=min(20.0, context.deadline.remaining_seconds()),
    )

    def generate(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        generated.update(calibration.generate_from_tab(
            spec.calibration_mode,
            print_profile_id=spec.calibration_print_profile_id,
        ))
        evidence = {
            "result_fingerprint": generated.get("synthetic_result_fingerprint")
        }
        if spec.detailed_evidence:
            evidence["stock_id"] = spec.stock_id
        else:
            evidence["printing_mode"] = generated.get("printing_mode")
        return evidence

    def select(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        return calibration.select_result(
            str(generated["synthetic_result_fingerprint"])
        )

    def apply(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        authoritative_before = None
        if spec.capture_isolation_boundary:
            from tools.virtual_workflows.authoritative_evidence import (
                capture_authoritative_bundle,
            )

            authoritative_before = capture_authoritative_bundle(context)
        before = capture_count_snapshot(context)
        preview = calibration.inspect_preview()
        handled = calibration.apply_selected(
            expected_title=(
                None if spec.manual_refuel_check is not None
                else spec.apply_success_title
            ),
            mode_switch_choice=spec.mode_switch_choice,
            manual_refuel_choice=(
                "yes" if spec.manual_refuel_check is not None else None
            ),
        )
        if (
            spec.manual_refuel_check is None
            and spec.expected_start_outcome != "calibration_apply_rejected"
        ):
            calibration.close()
        after = capture_count_snapshot(context)
        authoritative_after = None
        if spec.capture_isolation_boundary:
            authoritative_after = capture_authoritative_bundle(context)
        transition = {
            "stock_id": spec.stock_id,
            "preview": preview,
            "before": before,
            "after": after,
        }
        runtime.observations.setdefault(
            "calibration_count_transitions", []
        ).append(transition)
        if spec.capture_isolation_boundary:
            runtime.observations["two_reagent_isolation_boundary"] = {
                "stock_id": spec.stock_id,
                "before": authoritative_before,
                "after": authoritative_after,
                "count_transition": transition,
            }
        evidence = {
            "preview": preview,
            "handled_dialogs": handled,
            "count_transition": transition,
        }
        if spec.detailed_evidence:
            evidence = {"stock_id": spec.stock_id, **evidence}
        return evidence

    runtime.run_steps(
        (
            SemanticStep(
                "calibration.generate_via_ui",
                InteractionSurface.UI,
                generate,
            ),
            SemanticStep(
                "calibration.select_via_ui",
                InteractionSurface.UI,
                select,
            ),
            SemanticStep(
                "calibration.apply_via_ui",
                InteractionSurface.UI,
                apply,
            ),
        )
    )
    if spec.expected_start_outcome == "calibration_apply_rejected":
        rejected_generated: dict[str, Any] = {}
        rejected_selected: dict[str, Any] = {}
        boundary: dict[str, Any] = {}

        def configure_rejected(_runtime: JourneyRuntime) -> Mapping[str, Any]:
            machine.configure_print_settings(
                pulse_width_us=int(spec.rejected_calibration_pulse_width_us),
                pressure_psi=spec.pressure_psi,
                frequency_hz=spec.frequency_hz,
            )
            return {
                "pulse_width_us": int(spec.rejected_calibration_pulse_width_us),
                "pressure_psi": spec.pressure_psi,
                "target_mode": spec.rejected_calibration_mode,
            }

        def generate_rejected(_runtime: JourneyRuntime) -> Mapping[str, Any]:
            rejected_generated.update(
                calibration.generate_from_tab(
                    str(spec.rejected_calibration_mode),
                    print_profile_id=spec.calibration_print_profile_id,
                )
            )
            run_id_parts = str(rejected_generated.get("run_id") or "").split(":")
            if (
                len(run_id_parts) < 2
                or run_id_parts[1] != str(spec.rejected_calibration_profile_id)
            ):
                raise RuntimeError("rejected calibration profile drifted")
            return {
                "stock_id": spec.stock_id,
                "result_fingerprint": rejected_generated.get(
                    "synthetic_result_fingerprint"
                ),
                "printing_mode": rejected_generated.get("printing_mode"),
            }

        def select_rejected(_runtime: JourneyRuntime) -> Mapping[str, Any]:
            rejected_selected.update(
                calibration.select_result(
                    str(rejected_generated["synthetic_result_fingerprint"])
                )
            )
            return dict(rejected_selected)

        def machine_boundary() -> dict[str, Any]:
            plan = context.experiment_model.get_execution_plan_snapshot()
            active = context.model.rack_model.get_gripper_printer_head()
            return {
                "array_state": str(context.controller.get_array_run_state()),
                "queue_drained": bool(context.machine.check_if_all_completed()),
                "print_pulse_width_us": int(
                    context.model.machine_model.get_print_pulse_width()
                ),
                "print_pressure_psi": float(
                    context.model.machine_model.get_target_print_pressure()
                ),
                "stock_id": (
                    str(active.get_stock_id()) if active is not None else None
                ),
                "printer_head_id": (
                    str(active.printer_head_id) if active is not None else None
                ),
                "plan_stock_modes": [stock.printing_mode for stock in plan.stocks],
            }

        def apply_rejected(_runtime: JourneyRuntime) -> Mapping[str, Any]:
            from tools.virtual_workflows.authoritative_evidence import (
                capture_authoritative_bundle,
            )

            preview = calibration.inspect_preview()
            before_bundle = capture_authoritative_bundle(context)
            before_counts = capture_count_snapshot(context)
            before_machine = machine_boundary()
            handled = calibration.apply_expected_failure(
                expected_title=str(spec.rejected_calibration_title),
                expected_message_fragment=str(
                    spec.rejected_calibration_message_fragment
                ),
                mode_switch_choice="yes",
                capture_modal=lambda evidence: capture_milestone(
                    context,
                    "calibration_apply_blocked",
                    evidence=evidence,
                ),
            )
            after_bundle = capture_authoritative_bundle(context)
            after_counts = capture_count_snapshot(context)
            after_machine = machine_boundary()
            calibration.close(confirm_without_applied=True)
            boundary.update(
                {
                    "terminal": "calibration_apply_rejected",
                    "stock_id": spec.stock_id,
                    "printer_head_id": spec.printer_head_id,
                    "preview": preview,
                    "handled_dialogs": handled["handled_dialogs"],
                    "failure": handled["failure"],
                    "before_bundle": before_bundle,
                    "after_bundle": after_bundle,
                    "before_counts": before_counts,
                    "after_counts": after_counts,
                    "before_machine": before_machine,
                    "after_machine": after_machine,
                }
            )
            return {
                "terminal": boundary["terminal"],
                "stock_id": spec.stock_id,
                "preview": preview,
                "handled_dialogs": handled["handled_dialogs"],
                "failure": handled["failure"],
            }

        runtime.run_steps(
            (
                SemanticStep(
                    "machine.configure_print_settings_via_ui",
                    InteractionSurface.UI,
                    configure_rejected,
                ),
                SemanticStep(
                    "calibration.generate_via_ui",
                    InteractionSurface.UI,
                    generate_rejected,
                ),
                SemanticStep(
                    "calibration.select_via_ui",
                    InteractionSurface.UI,
                    select_rejected,
                ),
                SemanticStep(
                    "calibration.apply_via_ui",
                    InteractionSurface.UI,
                    apply_rejected,
                ),
            )
        )
        runtime.observations["calibration_rejection_boundary"] = boundary
        runtime.observations["matrix_block"] = {
            "terminal": boundary["terminal"],
            "stock_id": boundary["stock_id"],
            "printer_head_id": boundary["printer_head_id"],
            "preview": boundary["preview"],
            "handled_dialogs": boundary["handled_dialogs"],
            "failure": boundary["failure"],
        }
        if spec.return_head:
            runtime.run_steps(
                (
                    SemanticStep(
                        "head.return_via_ui",
                        InteractionSurface.UI,
                        return_active_head,
                    ),
                )
            )
        return dict(runtime.observations["matrix_block"])
    if spec.manual_refuel_check is not None:
        manual_spec = spec.manual_refuel_check

        def complete_manual_refuel(_runtime: JourneyRuntime) -> Mapping[str, Any]:
            driver = ManualRefuelCheckDriver(context)
            evidence = driver.complete_after_calibration_close(
                calibration,
                stock_id=spec.stock_id,
                printer_head_id=spec.printer_head_id,
                trial_count=manual_spec.trial_count,
                trial_droplet_count=manual_spec.trial_droplet_count,
                outcome=manual_spec.outcome,
                operator_judgment=manual_spec.operator_judgment,
                capture_passed=(
                    lambda record: capture_milestone(
                        context,
                        manual_spec.milestone,
                        evidence={
                            "stock_id": spec.stock_id,
                            "printer_head_id": spec.printer_head_id,
                            "status": record.get("status"),
                        },
                    )
                    if manual_spec.milestone
                    else None
                ),
            )
            runtime.observations.setdefault("manual_refuel_checks", []).append(
                dict(evidence)
            )
            return evidence

        runtime.run_steps(
            (
                SemanticStep(
                    "manual_refuel.complete_check_via_ui",
                    InteractionSurface.UI,
                    complete_manual_refuel,
                ),
            )
        )
    if spec.ready_milestone:
        evidence = {
            "array_control": ArrayDriver(context).inspect_control(
                expected_text="Start Array",
                expected_enabled=True,
            )
        }
        if spec.detailed_evidence:
            evidence.update(
                {
                    "stock_id": spec.stock_id,
                    "printer_head_id": spec.printer_head_id,
                }
            )
        capture_milestone(
            context, spec.ready_milestone,
            evidence=evidence,
        )

    from PySide6 import QtWidgets

    expected_dialogs = [
        (title, QtWidgets.QMessageBox.StandardButton.Yes)
        for title in spec.start_dialog_titles
    ]
    array = ArrayDriver(context)
    if spec.expected_start_outcome == "manual_refuel_cancelled":
        starting_count = len(runtime.observations["completed_wells"])
        before_plan = context.experiment_model.get_execution_plan_snapshot()
        result = runtime.run_steps(
            (
                SemanticStep(
                    "array.start_via_ui",
                    InteractionSurface.UI,
                    lambda _runtime: array.start_and_cancel_manual_refuel_guard(
                        expected_dialogs,
                        completion_count=lambda: len(
                            runtime.observations["completed_wells"]
                        ),
                    ),
                ),
            )
        )[0]
        evidence = {
            "terminal": "manual_refuel_cancelled",
            "pass_index": index + 1,
            "stock_id": spec.stock_id,
            "printer_head_id": spec.printer_head_id,
            "starting_completion_count": starting_count,
            "observed_completion_count": len(runtime.observations["completed_wells"]),
            "plan_state_before": str(before_plan.state.value),
            **dict(result.get("evidence") or {}),
        }
        runtime.observations["matrix_block"] = dict(evidence)
        capture_milestone(
            context,
            "manual_refuel_blocked",
            evidence=evidence,
        )
        if spec.return_head:
            runtime.run_steps(
                (
                    SemanticStep(
                        "head.return_via_ui",
                        InteractionSurface.UI,
                        return_active_head,
                    ),
                )
            )
        return evidence
    runtime.run_steps(
        (
            SemanticStep(
                "array.start_via_ui",
                InteractionSurface.UI,
                lambda _runtime: {"dialogs": array.start(expected_dialogs)},
            ),
        )
    )
    if spec.printing_milestone:
        evidence = {
            "array_control": array.inspect_control(
                expected_text="Stop After Well",
                expected_enabled=True,
            )
        }
        if spec.detailed_evidence:
            evidence["stock_id"] = spec.stock_id
        capture_milestone(
            context, spec.printing_milestone,
            evidence=evidence,
        )
    if active_phase is not None:
        active_phase(runtime, spec)
    if not spec.await_terminal_boundary:
        return None
    if spec.return_head and spec.expected_plan_state == "completed":
        from tools.virtual_workflows.execution_observer import (
            capture_execution_liveness_snapshot,
        )

        wait_for_completions(
            context,
            completed_count=lambda: len(runtime.observations["completed_wells"]),
            target_count=spec.expected_completion_count,
            timeout_seconds=context.deadline.remaining_seconds(),
            label="final stock-pass completion",
            no_progress_timeout_seconds=spec.no_progress_timeout_seconds,
            no_progress_evidence=lambda observed, stalled: (
                capture_execution_liveness_snapshot(
                    context,
                    completed_count=observed,
                    target_count=spec.expected_completion_count,
                    stalled_seconds=stalled,
                    pass_context={
                        "pass_index": index + 1,
                        "stock_id": spec.stock_id,
                        "head_id": spec.printer_head_id,
                    },
                )
            ),
        )
        runtime.run_steps((SemanticStep(
            "head.return_via_ui", InteractionSurface.UI, return_active_head
        ),))
        returned_before_boundary = True
    runtime.run_steps(
        (
            SemanticStep(
                "array.wait_for_completions",
                InteractionSurface.HARNESS,
                lambda _runtime: wait_for_execution_boundary(
                    runtime,
                    expected_count=spec.expected_completion_count,
                    expected_plan_state=spec.expected_plan_state,
                    strict=spec.validate_pass_boundary,
                    no_progress_timeout_seconds=spec.no_progress_timeout_seconds,
                ),
            ),
        )
    )
    if spec.validate_pass_boundary:
        runtime.run_steps(
            (
                SemanticStep(
                    "validation.stock_pass_boundary",
                    InteractionSurface.HARNESS,
                    lambda _runtime: validate_stock_pass_boundary(
                        runtime,
                        spec,
                        index=index,
                        pass_boundaries=pass_boundaries,
                    ),
                ),
            )
        )
    if spec.completed_milestone:
        array_control = ArrayDriver(context).inspect_control(
            expected_text=_expected_completed_array_control_text(
                expected_plan_state=spec.expected_plan_state,
                head_returned=returned_before_boundary,
            ),
            expected_enabled=False,
        )
        evidence = {"array_control": array_control}
        if spec.detailed_evidence:
            evidence.update(
                {
                    "stock_id": spec.stock_id,
                    "completion_count": spec.expected_completion_count,
                }
            )
        capture_milestone(
            context, spec.completed_milestone,
            evidence=evidence,
        )

    if spec.return_head and not returned_before_boundary:
        runtime.run_steps(
            (
                SemanticStep(
                    "head.return_via_ui",
                    InteractionSurface.UI,
                    return_active_head,
                ),
            )
        )
    return None


def wait_for_execution_boundary(
    runtime: JourneyRuntime,
    *,
    expected_count: int,
    expected_plan_state: str,
    strict: bool,
    no_progress_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    context = runtime.context
    completed_wells = runtime.observations["completed_wells"]
    deadline = context.clock() + context.deadline.remaining_seconds()
    last_progress_count = len(completed_wells)
    last_progress_at = context.clock()

    def visible_progress_settled() -> bool:
        guide = context.view.experiment_task_list
        current_stock_id = str(
            (runtime.observations.get("current_pass") or {}).get("stock_id") or ""
        )
        plan = context.experiment_model.get_execution_plan_snapshot()
        pass_well_count = sum(
            1
            for well in plan.wells
            if any(
                dispense.stock_id == current_stock_id
                and int(dispense.target_dispenses) > 0
                for dispense in well.dispenses
            )
        )
        if pass_well_count <= 0:
            pass_well_count = len(runtime.observations.get("expected_wells", ()))
        expected_text = f"{pass_well_count}/{pass_well_count} wells"
        return any(
            expected_text in str(section.get("button").text())
            for section in getattr(guide, "_sections", {}).values()
            if section.get("button") is not None
        )

    while context.clock() < deadline:
        context.pump_events()
        observed_count = len(completed_wells)
        if observed_count > last_progress_count:
            last_progress_count = observed_count
            last_progress_at = context.clock()
        stalled_seconds = context.clock() - last_progress_at
        if (
            no_progress_timeout_seconds is not None
            and observed_count < int(expected_count)
            and stalled_seconds >= float(no_progress_timeout_seconds)
        ):
            from tools.virtual_workflows.execution_observer import (
                capture_execution_liveness_snapshot,
            )

            current_pass = dict(runtime.observations.get("current_pass") or {})
            raise ScenarioActionError(
                "array.wait_for_completions",
                "no progress while waiting for stock-pass execution boundary",
                stage="no_progress",
                evidence={
                    "target_count": int(expected_count),
                    "observed_count": observed_count,
                    "last_progress_count": last_progress_count,
                    "stalled_seconds": stalled_seconds,
                    "liveness": capture_execution_liveness_snapshot(
                        context,
                        completed_count=observed_count,
                        target_count=expected_count,
                        stalled_seconds=stalled_seconds,
                        pass_context={
                            "pass_index": int(current_pass.get("index", -1)) + 1,
                            "stock_id": current_pass.get("stock_id"),
                        },
                    ),
                },
            )
        plan = context.experiment_model.get_execution_plan_snapshot()
        if (
            len(completed_wells) == int(expected_count)
            and str(plan.state.value) == str(expected_plan_state)
            and context.machine.check_if_all_completed()
            and (not strict or context.controller.get_array_run_state() == "idle")
            and visible_progress_settled()
        ):
            if strict:
                return {
                    "observed_completed_count": len(completed_wells),
                    "plan_state": str(plan.state.value),
                    "controller_state": "idle",
                    "queue_drained": True,
                }
            return {
                "completed_count": len(completed_wells),
                "plan_state": str(plan.state.value),
                "queue_drained": True,
            }
        if len(completed_wells) > int(expected_count):
            raise RuntimeError(
                f"execution boundary overshot {expected_count}: "
                f"{len(completed_wells)}"
            )
        context.sleep(0.001)
    raise RuntimeError(
        f"execution boundary did not settle at {expected_count} / "
        f"{expected_plan_state}"
    )


def validate_stock_pass_boundary(
    runtime: JourneyRuntime,
    spec: StockPassSpec | PrecalibratedStockPassSpec,
    *,
    index: int,
    pass_boundaries: list[dict[str, Any]],
) -> Mapping[str, Any]:
    from ExecutionResumeStore import load_execution_resume

    context = runtime.context
    completed_wells = runtime.observations["completed_wells"]
    plan = context.experiment_model.get_execution_plan_snapshot()
    resume = load_execution_resume(context.experiment_model.execution_resume_file_path)
    active = context.model.rack_model.get_gripper_printer_head()
    evidence = {
        "pass_index": index + 1,
        "stock_id": spec.stock_id,
        "printer_head_id": spec.printer_head_id,
        "expected_completed_count": spec.expected_completion_count,
        "observed_completed_count": len(completed_wells),
        "controller_state": context.controller.get_array_run_state(),
        "queue_drained": bool(context.machine.check_if_all_completed()),
        "expected_plan_state": spec.expected_plan_state,
        "plan_state": str(plan.state.value),
        "active_stock_id": str(active.get_stock_id()) if active is not None else None,
        "active_printer_head_id": str(active.printer_head_id) if active is not None else None,
        "checkpoint_state": str(resume.state),
        "outstanding_intent_count": len(resume.intents),
    }
    if not all(
        (
            evidence["observed_completed_count"] == spec.expected_completion_count,
            evidence["controller_state"] == "idle",
            evidence["queue_drained"],
            evidence["plan_state"] == spec.expected_plan_state,
            (
                evidence["active_stock_id"] == spec.stock_id
                and evidence["active_printer_head_id"] == spec.printer_head_id
            ) if spec.expected_plan_state != "completed" else active is None,
            evidence["checkpoint_state"] == "clean",
            evidence["outstanding_intent_count"] == 0,
        )
    ):
        raise RuntimeError(f"invalid stock pass boundary: {evidence}")
    pass_boundaries.append(dict(evidence))
    return evidence


__all__ = [
    "CalibrationOnlySpec",
    "PrecalibratedStockPassSpec",
    "DisconnectFailClosedSpec",
    "EditorPreparationSpec",
    "MachineStartupSpec",
    "PostStartLockCopySpec",
    "PreparedEditorRevisionSpec",
    "StockPassSpec",
    "SoftStopResumeSpec",
    "bind_head_identities",
    "capture_completion_midpoint",
    "head_identity_step",
    "machine_startup_steps",
    "normalized_stock_pass_steps",
    "normalized_calibration_only_steps",
    "normalized_precalibrated_stock_pass_steps",
    "normalized_soft_stop_resume_steps",
    "normalized_disconnect_fail_closed_steps",
    "run_editor_preparation",
    "run_post_start_lock_copy",
    "run_prepared_editor_revision",
    "run_prepared_editor_sequence",
    "run_soft_stop_boundary",
    "run_disconnect_fail_closed_boundary",
    "resume_soft_stopped_array",
    "prepare_persisted_head_for_resume",
    "run_authoritative_reload_resume_boundary",
    "run_clean_authoritative_session_rotation_boundary",
    "run_stock_passes",
    "run_stock_calibration_only",
    "run_progressed_paired_calibration_guard",
    "run_precalibrated_stock_passes",
    "run_soft_stop_resume",
    "validate_stock_pass_boundary",
    "wait_for_execution_boundary",
]
