"""Reusable typed phases for composed SIL journeys."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.virtual_workflows.actions import InteractionSurface, capture_milestone
from tools.virtual_workflows.composition import JourneyRuntime, SemanticStep
from tools.virtual_workflows.page_drivers import (
    ArrayDriver,
    CalibrationDialogDriver,
    ExperimentEditorDriver,
    MachineControlsDriver,
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
    ready_milestone: str
    printing_milestone: str
    completed_milestone: str
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
        if any(
            not value
            for value in (
                self.ready_milestone,
                self.printing_milestone,
                self.completed_milestone,
            )
        ):
            raise ValueError("stock-pass milestone names must be non-empty")


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
    ).create_and_finalize(dict(spec.specification))
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
) -> dict[str, Any]:
    result = ExperimentEditorDriver(
        runtime.context,
        action_runner=runtime.harness.run_action,
    ).revise_prepared_design(
        initial_name=spec.initial_name,
        renamed_name=spec.renamed_name,
        experiment=spec.experiment_values(),
        reagent=spec.reagent_values(),
    )
    runtime.harness.assert_no_unexpected_dialog()
    return dict(result)


def bind_head_identities(
    runtime: JourneyRuntime,
    pass_specs: Sequence[StockPassSpec],
) -> Mapping[str, Any]:
    rack = RackDriver(runtime.context)
    bindings: list[dict[str, Any]] = []
    for spec in pass_specs:
        slot = rack.find_slot_for_stock(spec.stock_id)
        head = runtime.context.model.rack_model.slots[slot].printer_head
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
    pass_specs: Sequence[StockPassSpec],
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
                "artifact.capture_milestone",
                "array.start_via_ui",
                "artifact.capture_milestone",
                "array.wait_for_completions",
            ]
        )
        if spec.validate_pass_boundary:
            action_ids.append("validation.stock_pass_boundary")
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


def run_stock_passes(
    runtime: JourneyRuntime,
    pass_specs: Sequence[StockPassSpec],
    *,
    bind_identities: bool = True,
) -> None:
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
        _run_stock_pass(
            runtime,
            spec,
            index=index,
            pressure_enabled=pressure_enabled,
            pass_boundaries=pass_boundaries,
            head_staging=head_staging,
            returned_head_ids=returned_head_ids,
        )
        pressure_enabled = pressure_enabled or spec.enable_pressure_regulation


def _run_stock_pass(
    runtime: JourneyRuntime,
    spec: StockPassSpec,
    *,
    index: int,
    pressure_enabled: bool,
    pass_boundaries: list[dict[str, Any]],
    head_staging: list[dict[str, Any]],
    returned_head_ids: list[str],
) -> None:
    context = runtime.context
    machine = MachineControlsDriver(context)
    rack = RackDriver(context)
    slot = (
        int(spec.staging_slot)
        if spec.staging_slot is not None
        else rack.find_slot_for_stock(spec.stock_id)
    )

    def configure(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        machine.configure_print_settings(
            pulse_width_us=spec.pulse_width_us,
            pressure_psi=spec.pressure_psi,
            frequency_hz=spec.frequency_hz,
        )
        evidence = {
            "pulse_width_us": spec.pulse_width_us,
            "pressure_psi": spec.pressure_psi,
        }
        if spec.include_frequency_evidence:
            evidence["frequency_hz"] = spec.frequency_hz
        return evidence

    def set_volume(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        rack.set_slot_volume(slot, spec.initial_volume_uL)
        return {"slot": slot, "volume_uL": spec.initial_volume_uL}

    def load_head(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        if not spec.detailed_evidence:
            rack.confirm_and_load(slot)
            return {
                "slot": slot,
                "stock_id": context.model.rack_model.get_gripper_printer_head().get_stock_id(),
            }
        state_before = context.controller.get_array_run_state()
        drained_before = bool(context.machine.check_if_all_completed())
        rack.confirm_and_load(slot)
        active = context.model.rack_model.get_gripper_printer_head()
        evidence = {
            "pass_index": index + 1,
            "slot": slot,
            "stock_id": spec.stock_id,
            "printer_head_id": str(active.printer_head_id),
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

    runtime.run_steps(
        (
            SemanticStep(
                "machine.configure_print_settings_via_ui",
                InteractionSurface.UI,
                configure,
            ),
            SemanticStep(
                "head.set_volume_via_ui",
                InteractionSurface.UI,
                set_volume,
            ),
            SemanticStep("head.stage_via_ui", InteractionSurface.UI, load_head),
        )
    )
    if spec.enable_pressure_regulation and not pressure_enabled:
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
    generated: dict[str, Any] = {}

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
    calibration = CalibrationDialogDriver(
        context.app,
        dialog_state["dialog"],
        timeout_seconds=min(20.0, context.deadline.remaining_seconds()),
    )

    def generate(_runtime: JourneyRuntime) -> Mapping[str, Any]:
        generated.update(calibration.generate_from_tab("droplet"))
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
        preview = calibration.inspect_preview()
        handled = calibration.apply_selected(expected_title="Applied")
        calibration.close()
        evidence = {"preview": preview, "handled_dialogs": handled}
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
    capture_milestone(
        context,
        spec.ready_milestone,
        evidence={
            "stock_id": spec.stock_id,
            "printer_head_id": spec.printer_head_id,
        }
        if spec.detailed_evidence
        else None,
    )

    from PySide6 import QtWidgets

    expected_dialogs = [
        (title, QtWidgets.QMessageBox.StandardButton.Yes)
        for title in spec.start_dialog_titles
    ]
    array = ArrayDriver(context)
    runtime.run_steps(
        (
            SemanticStep(
                "array.start_via_ui",
                InteractionSurface.UI,
                lambda _runtime: {"dialogs": array.start(expected_dialogs)},
            ),
        )
    )
    capture_milestone(
        context,
        spec.printing_milestone,
        evidence={"stock_id": spec.stock_id} if spec.detailed_evidence else None,
    )
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
    capture_milestone(
        context,
        spec.completed_milestone,
        evidence={
            "stock_id": spec.stock_id,
            "completion_count": spec.expected_completion_count,
        }
        if spec.detailed_evidence
        else None,
    )

    if spec.return_head:
        def return_head(_runtime: JourneyRuntime) -> Mapping[str, Any]:
            active = context.model.rack_model.get_gripper_printer_head()
            head_id = str(active.printer_head_id)
            stock_id = str(active.get_stock_id())
            state_before = context.controller.get_array_run_state()
            drained_before = bool(context.machine.check_if_all_completed())
            rack.unload(slot)
            returned_head_ids.append(head_id)
            return {
                "slot": slot,
                "stock_id": stock_id,
                "printer_head_id": head_id,
                "array_state_before": state_before,
                "queue_drained_before": drained_before,
                "returned": True,
            }

        runtime.run_steps(
            (
                SemanticStep(
                    "head.return_via_ui",
                    InteractionSurface.UI,
                    return_head,
                ),
            )
        )


def wait_for_execution_boundary(
    runtime: JourneyRuntime,
    *,
    expected_count: int,
    expected_plan_state: str,
    strict: bool,
) -> dict[str, Any]:
    context = runtime.context
    completed_wells = runtime.observations["completed_wells"]
    deadline = context.clock() + context.deadline.remaining_seconds()
    while context.clock() < deadline:
        context.pump_events()
        plan = context.experiment_model.get_execution_plan_snapshot()
        if (
            len(completed_wells) == int(expected_count)
            and str(plan.state.value) == str(expected_plan_state)
            and context.machine.check_if_all_completed()
            and (not strict or context.controller.get_array_run_state() == "idle")
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
    spec: StockPassSpec,
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
        "active_stock_id": str(active.get_stock_id()),
        "active_printer_head_id": str(active.printer_head_id),
        "checkpoint_state": str(resume.state),
        "outstanding_intent_count": len(resume.intents),
    }
    if not all(
        (
            evidence["observed_completed_count"] == spec.expected_completion_count,
            evidence["controller_state"] == "idle",
            evidence["queue_drained"],
            evidence["plan_state"] == spec.expected_plan_state,
            evidence["active_stock_id"] == spec.stock_id,
            evidence["active_printer_head_id"] == spec.printer_head_id,
            evidence["checkpoint_state"] == "clean",
            evidence["outstanding_intent_count"] == 0,
        )
    ):
        raise RuntimeError(f"invalid stock pass boundary: {evidence}")
    pass_boundaries.append(dict(evidence))
    return evidence


__all__ = [
    "EditorPreparationSpec",
    "MachineStartupSpec",
    "StockPassSpec",
    "bind_head_identities",
    "head_identity_step",
    "machine_startup_steps",
    "normalized_stock_pass_steps",
    "run_editor_preparation",
    "run_stock_passes",
    "validate_stock_pass_boundary",
    "wait_for_execution_boundary",
]
