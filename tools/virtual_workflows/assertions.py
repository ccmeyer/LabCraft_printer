"""Reusable read-only assertions for composed SIL journeys."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Mapping

from collections import Counter

from tools.virtual_workflows.dispense_counts import (
    StockWellCount,
    capture_count_snapshot,
    intent_and_simulator_counts,
    normalize_stock_well_counts,
    project_single_stock_preview_counts,
    reconcile_stock_well_counts,
)


@dataclass(frozen=True)
class AssertionResult:
    assertion_id: str
    checkpoint: str
    decision: str
    observable_sources: tuple[str, ...]
    evidence: Mapping[str, Any]
    message: str | None = None

    def __post_init__(self) -> None:
        if self.decision not in {"pass", "fail", "incomplete"}:
            raise ValueError("assertion decision must be pass, fail, or incomplete")

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "checkpoint": self.checkpoint,
            "decision": self.decision,
            "observable_sources": list(self.observable_sources),
            "evidence": dict(self.evidence),
            "message": self.message,
        }


@dataclass(frozen=True)
class ExecutionLifecycleExpectation:
    """Typed expected design for reusable stock-pass terminal assertions."""

    fixture: Mapping[str, Any]
    expected_well_ids: tuple[str, ...]
    expected_stock_ids: tuple[str, ...]
    expected_pulse_widths_us: tuple[int, ...] = ()
    expected_volumes_nL: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not self.expected_well_ids or not self.expected_stock_ids:
            raise ValueError("execution lifecycle expectations must be non-empty")
        if len(set(self.expected_well_ids)) != len(self.expected_well_ids):
            raise ValueError("expected well IDs must be unique")
        if len(set(self.expected_stock_ids)) != len(self.expected_stock_ids):
            raise ValueError("expected stock IDs must be unique")
        for label, values in (
            ("pulse widths", self.expected_pulse_widths_us),
            ("volumes", self.expected_volumes_nL),
        ):
            if values and len(values) != len(self.expected_stock_ids):
                raise ValueError(f"expected {label} must match stock cardinality")


@dataclass(frozen=True)
class SoftStopResumeExpectation:
    experiment_dir: Path
    plan_id: str
    well_ids: tuple[str, ...]
    stock_ids: tuple[str, ...]
    target_dispenses_per_stock: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "experiment_dir", Path(self.experiment_dir))
        if not self.plan_id or not self.well_ids or not self.stock_ids:
            raise ValueError("soft-stop expectation identities must be non-empty")
        if self.target_dispenses_per_stock <= 0:
            raise ValueError("soft-stop target dispenses must be positive")

    def fixture_info(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in (
            "experiment_dir", "plan_id", "well_ids", "stock_ids",
            "target_dispenses_per_stock",
        )}


@dataclass(frozen=True)
class DisconnectFailClosedExpectation:
    completion_count: int
    canceled_intent_count: int

    def __post_init__(self) -> None:
        if self.completion_count <= 0 or self.canceled_intent_count <= 0:
            raise ValueError("disconnect expectation counts must be positive")


@dataclass(frozen=True)
class ActionSequenceExpectation:
    action_ids: tuple[str, ...]
    interaction_surfaces: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.action_ids or any(not str(value).strip() for value in self.action_ids):
            raise ValueError("action sequence IDs must be non-empty")
        if len(self.interaction_surfaces) != len(self.action_ids):
            raise ValueError("action sequence surfaces must align with action IDs")
        valid = {"ui", "controller", "model", "simulator", "harness"}
        if any(surface not in valid for surface in self.interaction_surfaces):
            raise ValueError("action sequence interaction surface is invalid")


def evaluate_assertion(
    assertion_id: str,
    checkpoint: str,
    observable_sources: tuple[str, ...],
    operation: Callable[[], tuple[bool, Mapping[str, Any]]],
) -> AssertionResult:
    """Evaluate without mutation; unavailable evidence is explicitly incomplete."""

    try:
        passed, evidence = operation()
    except Exception as exc:
        return AssertionResult(
            assertion_id=assertion_id,
            checkpoint=checkpoint,
            decision="incomplete",
            observable_sources=observable_sources,
            evidence={"exception_type": type(exc).__name__},
            message=str(exc),
        )
    return AssertionResult(
        assertion_id=assertion_id,
        checkpoint=checkpoint,
        decision="pass" if passed else "fail",
        observable_sources=observable_sources,
        evidence=dict(evidence),
        message=None if passed else "observable state did not satisfy the assertion",
    )


def _policy_assertion(
    assertion_id: str,
    checkpoint: str,
    evidence: Mapping[str, Any],
    check_names: tuple[str, ...],
    sources: tuple[str, ...],
) -> AssertionResult:
    checks = dict(evidence.get("checks") or {})
    selected = {name: bool(checks.get(name)) for name in check_names}
    passed = bool(selected) and all(selected.values())
    return AssertionResult(
        assertion_id, checkpoint, "pass" if passed else "fail", sources,
        evidence={"checks": selected, **dict(evidence)},
        message=None if passed else "lifecycle policy failed",
    )


def soft_stop_paused_assertions(
    context: Any,
    *,
    expectation: SoftStopResumeExpectation,
    request_evidence: Mapping[str, Any],
    completed_count: int,
    intent_lifecycle: Mapping[str, Any],
    quiescence: Mapping[str, Any],
) -> tuple[AssertionResult, ...]:
    """Evaluate the legacy oracle once and project the paused assertions."""

    from tools.virtual_workflows.scenarios import _validate_soft_stop_paused_scenario

    evidence = _validate_soft_stop_paused_scenario(
        experiment_model=context.experiment_model,
        fixture_info=expectation.fixture_info(),
        controller=context.controller,
        machine=context.machine,
        request_evidence=dict(request_evidence),
        completed_count=int(completed_count),
        errors=list(context.errors),
        unexpected_dialogs=list(context.unexpected_dialogs),
        intent_lifecycle=dict(intent_lifecycle),
    )
    quiescent = all((
        quiescence.get("starting_completion_count") == quiescence.get("ending_completion_count"),
        quiescence.get("starting_progress_count") == quiescence.get("ending_progress_count"),
        quiescence.get("simulator_queue_empty") is True,
    ))
    return (
        _policy_assertion("execution.soft_stop_requested", "stop_requested", evidence, ("request_trigger_exact",), ("ui", "controller")),
        _policy_assertion("execution.soft_stop_boundary_valid", "stopped", evidence, tuple(name for name in evidence["checks"] if name != "request_trigger_exact"), ("controller", "model", "simulator", "persistence")),
        AssertionResult("execution.stopped_boundary_quiescent", "stopped", "pass" if quiescent else "fail", ("controller", "model", "simulator"), dict(quiescence), None if quiescent else "paused execution advanced"),
    )


def soft_stop_terminal_assertions(
    context: Any,
    *,
    expectation: SoftStopResumeExpectation,
    completed_wells: list[str],
    array_complete_count: int,
    intent_lifecycle: Mapping[str, Any],
    paused_validation: Mapping[str, Any],
    quiescence: Mapping[str, Any],
    starvation_events: list[Mapping[str, Any]],
) -> tuple[AssertionResult, ...]:
    """Evaluate the shared terminal oracle and project its four assertions."""

    from tools.virtual_workflows.scenarios import _validate_soft_stop_completed_scenario

    evidence = _validate_soft_stop_completed_scenario(
        experiment_model=context.experiment_model,
        fixture_info=expectation.fixture_info(),
        well_updates=list(completed_wells),
        array_states=list(context.array_states),
        array_complete_count=int(array_complete_count),
        errors=list(context.errors),
        unexpected_dialogs=list(context.unexpected_dialogs),
        starvation_events=list(starvation_events),
        intent_lifecycle=dict(intent_lifecycle),
        paused_validation=dict(paused_validation),
        quiescence=dict(quiescence),
    )
    groups = (
        ("execution.resume_exactly_once", ("ui_resumed_once", "audit_lifecycle_ordered"), ("ui", "controller", "persistence")),
        ("execution.expected_completions", ("completed_pairs_exactly_once", "completion_count_exact", "well_updates_exact", "progress_targets_exact", "array_completed_once"), ("ui", "model", "persistence")),
        ("execution.intent_durability_exact", ("checkpoint_clean", "checkpoint_empty", "begun_intent_occurrences_reconcilable", "attachments_exact", "sequences_unique_monotonic", "terminal_intent_partition_exact", "discarded_pairs_reissued"), ("controller", "model", "persistence")),
    )
    projected = [
        _policy_assertion(assertion_id, "terminal", evidence, checks, sources)
        for assertion_id, checks, sources in groups
    ]
    grouped = {name for _, checks, _ in groups for name in checks}
    projected.append(_policy_assertion(
        "execution.terminal_bundle_valid", "terminal", evidence,
        tuple(name for name in evidence["checks"] if name not in grouped),
        ("controller", "model", "simulator", "persistence"),
    ))
    return tuple(projected)


def disconnect_fail_closed_assertions(
    context: Any,
    *,
    expectation: DisconnectFailClosedExpectation,
    request_evidence: Mapping[str, Any],
    completed_wells: list[str],
    array_complete_count: int,
    intent_lifecycle: Mapping[str, Any],
    quiescence: Mapping[str, Any],
    recovery: Mapping[str, Any],
) -> tuple[AssertionResult, ...]:
    """Project the exact request, cancellation, quiescence, and recovery contract."""

    begins = list(intent_lifecycle.get("begins") or [])
    attachments = list(intent_lifecycle.get("attachments") or [])
    completions = list(intent_lifecycle.get("completions") or [])
    discard_batches = list(intent_lifecycle.get("discard_batches") or [])
    discarded_ids = [
        intent_id
        for batch in discard_batches
        for intent_id in (batch.get("intent_ids") or [])
    ]
    eligibility = dict(recovery.get("eligibility") or {})

    request_checks = {
        "trigger_exact": request_evidence.get("trigger_count")
        == expectation.completion_count,
        "clicked_exact": request_evidence.get("clicked_count")
        == expectation.completion_count,
        "observed_exact": request_evidence.get("observed_count")
        == expectation.completion_count,
        "normal_ui_recovered": request_evidence.get("button_text_after") == "Connect"
        and request_evidence.get("button_enabled_after") is True,
    }
    boundary_checks = {
        "completion_count_exact": len(completed_wells) == expectation.completion_count,
        "completed_wells_unique": len(set(completed_wells)) == len(completed_wells),
        "array_not_completed": int(array_complete_count) == 0,
        "simulator_queue_empty": bool(context.machine.check_if_all_completed()),
        "model_disconnected": not context.model.machine_model.is_connected(),
        "simulator_disconnected": not context.machine.state.connected,
        "array_resume_ready": context.controller.get_array_run_state()
        == "resume_ready",
        "plan_remains_active": str(
            context.experiment_model.get_execution_plan_snapshot().state.value
        )
        == "active",
        "begins_partition_exact": len(begins)
        == expectation.completion_count + expectation.canceled_intent_count,
        "attachments_exact": len(attachments) == len(begins),
        "completions_exact": len(completions) == expectation.completion_count,
        "single_discard_batch": len(discard_batches) == 1,
        "canceled_intents_exact": len(discarded_ids)
        == expectation.canceled_intent_count,
        "terminal_intent_partition_exact": set(completions).isdisjoint(discarded_ids)
        and set(completions) | set(discarded_ids)
        == {row.get("intent_id") for row in begins},
        "no_errors": not context.errors,
        "no_unexpected_dialogs": not context.unexpected_dialogs,
    }
    quiescence_checks = {
        "completion_count_stable": quiescence.get("starting_completion_count")
        == quiescence.get("ending_completion_count")
        == expectation.completion_count,
        "progress_count_stable": quiescence.get("starting_progress_count")
        == quiescence.get("ending_progress_count")
        == expectation.completion_count,
        "queue_remains_empty": quiescence.get("simulator_queue_empty") is True,
        "array_remains_resume_ready": quiescence.get("array_state")
        == "resume_ready",
        "connection_remains_closed": quiescence.get("model_connected") is False
        and quiescence.get("simulator_connected") is False,
    }
    recovery_checks = {
        "eligibility_ready_to_resume": eligibility.get("status")
        == "ready_to_resume",
        "eligibility_can_resume": eligibility.get("can_resume_hardware") is True,
        "no_ambiguous_intents": eligibility.get("ambiguous_intent_ids") == [],
        "array_resume_ready": recovery.get("array_state") == "resume_ready",
        "plan_active": recovery.get("plan_state") == "active",
        "dock_check_required": "machine_disconnect"
        in (recovery.get("dock_check_reasons") or []),
        "motors_unhomed": recovery.get("motors_homed") is False,
    }
    groups = (
        (
            "execution.disconnect_requested",
            "disconnect_requested",
            request_checks,
            request_evidence,
            ("ui", "controller", "model", "simulator"),
        ),
        (
            "execution.disconnect_fail_closed",
            "disconnected",
            boundary_checks,
            {
                "completed_wells": list(completed_wells),
                "intent_lifecycle": dict(intent_lifecycle),
            },
            ("controller", "model", "simulator", "persistence"),
        ),
        (
            "execution.disconnected_boundary_quiescent",
            "recovery_ready",
            quiescence_checks,
            quiescence,
            ("controller", "model", "simulator", "persistence"),
        ),
        (
            "execution.disconnect_recovery_ready",
            "recovery_ready",
            recovery_checks,
            recovery,
            ("controller", "model", "persistence"),
        ),
    )
    return tuple(
        AssertionResult(
            assertion_id,
            checkpoint,
            "pass" if all(checks.values()) else "fail",
            sources,
            {"checks": checks, **dict(evidence)},
            None if all(checks.values()) else "disconnect lifecycle policy failed",
        )
        for assertion_id, checkpoint, checks, evidence, sources in groups
    )


def authoritative_first_session_paused_assertion(
    paused_results: tuple[AssertionResult, ...],
) -> AssertionResult:
    checks = {row.assertion_id: row.decision == "pass" for row in paused_results}
    return _policy_assertion(
        "execution.first_session_paused",
        "session_1_stopped",
        {"checks": checks, "assertions": [row.to_dict() for row in paused_results]},
        tuple(checks) if len(checks) == 3 else (*checks, "three_pause_assertions"),
        ("ui", "controller", "model", "simulator", "persistence"),
    )


def authoritative_session_rotation_assertions(
    *,
    first_close: Mapping[str, Any],
    second_launch: Mapping[str, Any],
    application_sessions: list[Mapping[str, Any]],
    files_byte_identical: bool,
) -> tuple[AssertionResult, AssertionResult]:
    close, launch = dict(first_close), dict(second_launch)
    first = dict(application_sessions[0]) if application_sessions else {}
    fresh_checks = {
        "two_application_sessions": len(application_sessions) == 2,
        "same_retained_session": first.get("session_id") == launch.get("session_id"),
        "fresh_application_identity": first.get("application_session_id") != launch.get("application_session_id"),
        "second_launch_passed": bool(launch.get("application_session_id")),
        "real_components_reconstructed": launch.get("component_type") == "ApplicationComponents" and launch.get("view_type") == "MainWindow",
        "simulator_reconstructed": launch.get("machine_type") == "SimulatedMachine" and launch.get("hardware_access_allowed") is False,
    }
    close_checks = {
        "close_succeeded": close.get("close_succeeded") is True,
        "recorder_closed": (close.get("recorder") or {}).get("status") == "closed",
        "session_lock_released": close.get("session_lock_present") is False,
        "root_retained": close.get("root_retained") is True,
        "authoritative_files_byte_identical": bool(files_byte_identical),
    }
    return (
        _policy_assertion(
            "ui.fresh_application_session_constructed", "session_2_launched",
            {"checks": fresh_checks, "application_sessions": application_sessions},
            tuple(fresh_checks), ("ui", "session", "harness"),
        ),
        _policy_assertion(
            "execution.first_session_teardown_clean", "session_1_closed",
            {"checks": close_checks, "close": close},
            tuple(close_checks), ("session", "persistence", "harness"),
        ),
    )


def authoritative_reload_boundary_assertions(
    *,
    loaded: Mapping[str, Any],
    activated: Mapping[str, Any],
) -> tuple[AssertionResult, AssertionResult]:
    return (
        _policy_assertion(
            "execution.authoritative_reload_valid", "session_2_loaded", loaded,
            tuple((loaded.get("checks") or {}).keys()),
            ("ui", "model", "persistence"),
        ),
        _policy_assertion(
            "execution.authoritative_runtime_rehydrated", "session_2_activated",
            activated,
            tuple((activated.get("checks") or {}).keys()),
            ("ui", "controller", "model", "persistence"),
        ),
    )


def authoritative_reload_terminal_assertions(
    context: Any,
    *,
    expectation: SoftStopResumeExpectation,
    completed_wells: list[str],
    array_complete_count: int,
    combined_lifecycle: Mapping[str, Any],
    session_2_lifecycle: Mapping[str, Any],
    session_1_completed_pairs: set[tuple[str, str]],
    paused_validation: Mapping[str, Any],
    quiescence: Mapping[str, Any],
    starvation_events: list[Mapping[str, Any]],
) -> tuple[AssertionResult, ...]:
    """Project the shared terminal oracle plus the cross-session no-replay rule."""

    by_id = {row.assertion_id: row for row in soft_stop_terminal_assertions(
        context,
        expectation=expectation,
        completed_wells=completed_wells,
        array_complete_count=array_complete_count,
        intent_lifecycle=combined_lifecycle,
        paused_validation=paused_validation,
        quiescence=quiescence,
        starvation_events=starvation_events,
    )}
    session_2_pairs = {
        (str(row.get("stock_id")), str(row.get("well_id")))
        for row in session_2_lifecycle.get("begins", ())
    }
    no_replay = not (session_1_completed_pairs & session_2_pairs)
    resume = by_id["execution.resume_exactly_once"]
    resume_evidence = {
        **dict(resume.evidence),
        "session_1_completed_pairs_not_replayed": no_replay,
        "session_1_completed_pairs": list(map(list, sorted(session_1_completed_pairs))),
        "session_2_begin_pairs": [list(pair) for pair in sorted(session_2_pairs)],
    }
    by_id["execution.resume_exactly_once"] = AssertionResult(
        "execution.reload_resume_exactly_once",
        resume.checkpoint,
        "pass" if resume.decision == "pass" and no_replay else "fail",
        resume.observable_sources,
        resume_evidence,
        None if resume.decision == "pass" and no_replay else
        "fresh application replayed completed work or resumed incorrectly",
    )
    return tuple(by_id[name] for name in (
        "execution.resume_exactly_once", "execution.expected_completions",
        "execution.intent_durability_exact", "execution.terminal_bundle_valid",
    ))


def simulation_identity_assertion(context: Any) -> AssertionResult:
    def inspect() -> tuple[bool, Mapping[str, Any]]:
        banner = getattr(context.view, "simulation_identity_banner", None)
        label = getattr(context.view, "simulation_identity_label", None)
        text = label.text() if label is not None else ""
        evidence = {
            "banner_present": banner is not None and label is not None,
            "banner_visible": bool(banner is not None and banner.isVisible()),
            "banner_text": text,
            "machine_type": type(context.machine).__name__,
        }
        return (
            evidence["banner_present"]
            and "SIMULATION" in text
            and "NO HARDWARE" in text
            and evidence["machine_type"] == "SimulatedMachine",
            evidence,
        )

    return evaluate_assertion(
        "sil.host_hardware_disabled",
        "launched",
        ("ui", "session"),
        inspect,
    )


def machine_ready_assertion(context: Any) -> AssertionResult:
    def inspect() -> tuple[bool, Mapping[str, Any]]:
        machine_model = context.model.machine_model
        evidence = {
            "connected": bool(machine_model.is_connected()),
            "motors_enabled": bool(machine_model.motors_are_enabled()),
            "motors_homed": bool(machine_model.motors_are_homed()),
            "queue_drained": bool(context.machine.check_if_all_completed()),
        }
        return all(evidence.values()), evidence

    return evaluate_assertion(
        "machine.normal_ui_ready",
        "machine_ready",
        ("model", "simulator"),
        inspect,
    )


def prepared_execution_assertion(context: Any, expected_wells: int) -> AssertionResult:
    def inspect() -> tuple[bool, Mapping[str, Any]]:
        plan = context.experiment_model.get_execution_plan_snapshot()
        evidence = {
            "plan_id": str(plan.plan_id),
            "plan_revision": int(plan.plan_revision),
            "plan_state": str(plan.state.value),
            "well_count": len(plan.wells),
            "stock_count": len(plan.stocks),
            "runtime_active": bool(
                context.experiment_model.is_authoritative_execution_runtime_active()
            ),
            "eligibility": (
                context.experiment_model.get_execution_resume_eligibility() or {}
            ).get("status"),
        }
        return (
            evidence["well_count"] == int(expected_wells)
            and evidence["stock_count"] == 1
            and evidence["plan_state"] == "prepared"
            and not evidence["runtime_active"],
            evidence,
        )

    return evaluate_assertion(
        "experiment.prepared_bundle_valid",
        "prepared",
        ("model", "persistence"),
        inspect,
    )


def multi_stock_prepared_assertion(
    context: Any,
    *,
    expected_well_ids: tuple[str, ...],
    expected_stock_ids: tuple[str, ...],
    require_stock_order: bool = True,
    expected_target_dispenses: Mapping[Any, int] | None = None,
) -> AssertionResult:
    def inspect() -> tuple[bool, Mapping[str, Any]]:
        plan = context.experiment_model.get_execution_plan_snapshot()
        observed_stock_ids = tuple(stock.stock_id for stock in plan.stocks)
        observed_wells = tuple(well.well_id for well in plan.wells)
        evidence = {
            "plan_id": str(plan.plan_id),
            "plan_revision": int(plan.plan_revision),
            "plan_state": str(plan.state.value),
            "well_ids": list(observed_wells),
            "stock_ids": list(observed_stock_ids),
            "runtime_active": bool(
                context.experiment_model.is_authoritative_execution_runtime_active()
            ),
        }
        target_rows = [
            (
                str(target.stock_id),
                str(well.well_id),
                int(target.target_dispenses),
            )
            for well in plan.wells
            for target in well.dispenses
        ]
        expected_by_stock = (
            {stock_id: 1 for stock_id in expected_stock_ids}
            if expected_target_dispenses is None
            else dict(expected_target_dispenses)
        )
        per_well = any(isinstance(key, tuple) for key in expected_by_stock)
        expected_rows = sorted(
            (
                stock_id,
                well_id,
                expected_by_stock.get((stock_id, well_id))
                if per_well else expected_by_stock.get(stock_id),
            )
            for well_id in expected_well_ids
            for stock_id in expected_stock_ids
            if (
                expected_by_stock.get((stock_id, well_id))
                if per_well else expected_by_stock.get(stock_id)
            ) != 0
        )
        expected_entries = len(expected_rows)
        evidence.update({
            "target_entry_count": len(target_rows),
            "target_dispense_count": sum(row[2] for row in target_rows),
            "target_dispenses_per_entry": sorted(
                {row[2] for row in target_rows}
            ),
            "expected_target_dispenses_by_stock": (
                None if per_well else expected_by_stock
            ),
            "expected_target_dispenses_by_stock_well": (
                [
                    {"stock_id": key[0], "well_id": key[1], "droplets": value}
                    for key, value in sorted(expected_by_stock.items())
                ] if per_well else None
            ),
        })
        return (
            len(observed_wells) == len(expected_well_ids)
            and set(observed_wells) == set(expected_well_ids)
            and (
                observed_stock_ids == expected_stock_ids
                if require_stock_order
                else set(observed_stock_ids) == set(expected_stock_ids)
            )
            and len(target_rows) == expected_entries
            and sorted(target_rows) == expected_rows
            and str(plan.state.value) == "prepared"
            and not evidence["runtime_active"],
            evidence,
        )

    return evaluate_assertion(
        "experiment.prepared_bundle_valid",
        "prepared",
        ("model", "persistence"),
        inspect,
    )


def execution_lifecycle_assertions(
    context: Any,
    *,
    expectation: ExecutionLifecycleExpectation,
    completed_wells: list[str],
    pass_boundaries: list[Mapping[str, Any]],
    head_staging: list[Mapping[str, Any]],
    starvation_events: list[Mapping[str, Any]],
    observer: Mapping[str, Any],
) -> tuple[AssertionResult, ...]:
    """Return cardinality-neutral read-only multi-stock execution assertions."""

    fixture = expectation.fixture
    expected_well_ids = expectation.expected_well_ids
    expected_stock_ids = expectation.expected_stock_ids

    from AuthoritativeExecutionLoad import inspect_authoritative_execution
    from ExecutionResumeStore import load_execution_resume

    plan = context.experiment_model.get_execution_plan_snapshot()
    resume = load_execution_resume(context.experiment_model.execution_resume_file_path)
    design_path = Path(context.experiment_model.experiment_file_path)
    import json

    design = json.loads(design_path.read_text(encoding="utf-8"))
    bundle = inspect_authoritative_execution(design_path.parent, design)
    lifecycle = dict(observer.get("lifecycle") or {})
    begins = list(lifecycle.get("begins") or [])
    attachments = list(lifecycle.get("attachments") or [])
    completions = list(lifecycle.get("completions") or [])
    discards = list(lifecycle.get("discard_batches") or [])
    progress = dict(observer.get("progress_snapshot") or {})
    durable = dict(observer.get("durable_io_samples_ms") or {})
    expected_count = int(fixture["workload"]["completion_count"])
    stock_count = len(expected_stock_ids)
    oracle = dict(fixture.get("lifecycle", {}).get("dispense_count_oracle") or {})
    positive_pairs_by_stock: dict[str, set[tuple[str, str]]] = {}
    if int(oracle.get("schema_version", 1)) == 2:
        for group in oracle.get("count_groups") or ():
            if int(group.get("requantized_droplets", 0) or 0) <= 0:
                continue
            stock_id = str(group.get("stock_id") or "")
            positive_pairs_by_stock.setdefault(stock_id, set()).update(
                (stock_id, str(well_id)) for well_id in group.get("well_ids") or ()
            )
    boundary_counts = []
    cumulative = 0
    for stock_id in expected_stock_ids:
        cumulative += len(
            positive_pairs_by_stock.get(
                stock_id,
                {(stock_id, well_id) for well_id in expected_well_ids},
            )
        )
        boundary_counts.append(cumulative)
    boundary_states = ["active"] * max(0, stock_count - 1) + ["completed"]
    expected_pairs = (
        set().union(*positive_pairs_by_stock.values())
        if positive_pairs_by_stock else {
            (stock_id, well_id)
            for stock_id in expected_stock_ids
            for well_id in expected_well_ids
        }
    )

    def result(
        assertion_id: str,
        checkpoint: str,
        passed: bool,
        evidence: Mapping[str, Any],
        sources: tuple[str, ...],
    ) -> AssertionResult:
        return AssertionResult(
            assertion_id,
            checkpoint,
            "pass" if passed else "fail",
            sources,
            dict(evidence),
            None if passed else "observable state did not satisfy the assertion",
        )

    expected_head_ids = [
        str(stock["printer_head"]["printer_head_id"])
        for stock in fixture["stocks"]
    ]
    exchange_evidence = {
        "head_identities": expected_head_ids,
        "head_staging": [dict(item) for item in head_staging],
        "pass_boundaries": [dict(item) for item in pass_boundaries],
    }
    exchange_ok = (
        len(head_staging) == stock_count
        and [row.get("printer_head_id") for row in head_staging]
        == expected_head_ids
        and all(row.get("array_state_before") == "idle" for row in head_staging)
        and all(row.get("queue_drained_before") is True for row in head_staging)
        and head_staging[0].get("returned_previous") is False
        and all(row.get("returned_previous") is True for row in head_staging[1:])
    )

    boundary_ok = (
        len(pass_boundaries) == stock_count
        and [row.get("observed_completed_count") for row in pass_boundaries]
        == boundary_counts
        and [row.get("plan_state") for row in pass_boundaries]
        == boundary_states
        and all(row.get("controller_state") == "idle" for row in pass_boundaries)
        and all(row.get("queue_drained") is True for row in pass_boundaries)
        and all(row.get("checkpoint_state") == "clean" for row in pass_boundaries)
        and all(row.get("outstanding_intent_count") == 0 for row in pass_boundaries)
    )

    from tools.sil.ejection_response import PulseAwareSyntheticEjectionModelV1
    response = PulseAwareSyntheticEjectionModelV1()
    expected_pulses = expectation.expected_pulse_widths_us or tuple(
        int(stock["printer_head"]["print_pulse_width_us"])
        for stock in fixture["stocks"]
    )
    staging_pulses = tuple(
        int(stock.get("staging_print_pulse_width_us", expected_pulses[index]))
        for index, stock in enumerate(fixture["stocks"])
    )
    expected_volumes = expectation.expected_volumes_nL or tuple(
        response.predict_volume_nl(str(stock["printing_mode"]), expected_pulses[index])
        for index, stock in enumerate(fixture["stocks"])
    )
    settings = [
        {
            "print_pulse_width_us": int(expected_pulses[index]),
            "staging_print_pulse_width_us": int(staging_pulses[index]),
            "fixture_print_pulse_width_us": int(stock["printer_head"]["print_pulse_width_us"]),
            "print_pressure_psi": float(stock["printer_head"]["print_pressure_psi"]),
            "prepared_volume_nL": float(stock["prepared_droplet_volume_nL"]),
            "fixture_design_volume_nL": float(stock["droplet_volume_nL"]),
            "effective_volume_nL": float(expected_volumes[index]),
        }
        for index, stock in enumerate(fixture["stocks"])
    ]
    plan_stocks = {stock.stock_id: stock for stock in plan.stocks}
    settings_ok = len(plan_stocks) == stock_count and len(head_staging) == stock_count and all(
        stock_id in plan_stocks
        and bool(plan_stocks[stock_id].calibration_record_key)
        and abs(
            float(plan_stocks[stock_id].effective_volume_nL)
            - settings[index]["effective_volume_nL"]
        )
        < 1e-6
        and head_staging[index].get("effective_print_pulse_width_us")
        == settings[index]["staging_print_pulse_width_us"]
        and abs(
            float(head_staging[index].get("effective_print_pressure_psi", -1))
            - settings[index]["print_pressure_psi"]
        )
        < 0.01
        for index, stock_id in enumerate(expected_stock_ids)
    )

    observed = [well for well in completed_wells if well in set(expected_well_ids)]
    expected_completed_wells = Counter(
        well_id for _stock_id, well_id in expected_pairs
    )
    completion_ok = (
        len(observed) == expected_count
        and Counter(observed) == expected_completed_wells
    )
    begin_ids = [row.get("intent_id") for row in begins]
    attach_ids = [row.get("intent_id") for row in attachments]
    sequences = [row.get("command_seq32") for row in attachments]
    intent_pairs = {
        (str(row.get("stock_id")), str(row.get("well_id"))) for row in begins
    }
    durability_ok = (
        len(begins) == len(attachments) == len(completions) == expected_count
        and not discards
        and len(set(begin_ids)) == expected_count
        and Counter(attach_ids) == Counter(begin_ids)
        and Counter(completions) == Counter(begin_ids)
        and len(set(sequences)) == expected_count
        and sequences == sorted(sequences)
        and intent_pairs == expected_pairs
        and progress.get("mode_counts")
        == {"full_rebuild": 0, "cached_update": expected_count}
        and len(durable.get("fsync", {}).get("persistence.save_resume", []))
        == expected_count * 3
        and len(
            durable.get("atomic_replace", {}).get("persistence.save_resume", [])
        )
        == expected_count * 3
        and len(durable.get("fsync", {}).get("persistence.write_progress", []))
        == expected_count
        and len(
            durable.get("atomic_replace", {}).get("persistence.write_progress", [])
        )
        == expected_count
        and observer.get("restored") is True
    )
    durability = {
        "begin_count": len(begins),
        "attachment_count": len(attachments),
        "completion_count": len(completions),
        "discard_batch_count": len(discards),
        "unique_command_sequence_count": len(set(sequences)),
        "progress_snapshot": progress,
        "observer_restored": observer.get("restored"),
    }

    completed_history = getattr(context.machine.command_queue, "completed", ())
    command_history = getattr(context.machine, "command_event_history", ())
    history = {
        "simulator_completed_history_count": len(completed_history),
        "simulator_completed_history_limit": getattr(completed_history, "maxlen", None),
        "simulator_event_history_count": len(command_history),
        "simulator_event_history_limit": getattr(command_history, "maxlen", None),
        "phase_retained_count": len(
            observer.get("phase_timings", {}).get("records", [])
        ),
        "phase_dropped_count": observer.get("phase_timings", {}).get(
            "dropped_records", 0
        ),
    }
    history_ok = (
        isinstance(history["simulator_completed_history_limit"], int)
        and history["simulator_completed_history_count"]
        <= history["simulator_completed_history_limit"]
        and isinstance(history["simulator_event_history_limit"], int)
        and history["simulator_event_history_count"]
        <= history["simulator_event_history_limit"]
        and history["phase_dropped_count"] == 0
    )
    terminal = {
        "plan_state": str(plan.state.value),
        "completion_count": len(intent_pairs),
        "pass_terminal_states": [row.get("plan_state") for row in pass_boundaries],
        "checkpoint_state": str(resume.state),
        "checkpoint_intent_count": len(resume.intents),
        "authoritative_bundle_valid": bool(bundle.valid),
        "queue_drained": bool(context.machine.check_if_all_completed()),
        "error_count": len(context.errors),
        "unexpected_dialog_count": len(context.unexpected_dialogs),
    }
    terminal_ok = (
        terminal["plan_state"] == "completed"
        and terminal["checkpoint_state"] == "clean"
        and terminal["checkpoint_intent_count"] == 0
        and terminal["authoritative_bundle_valid"]
        and terminal["queue_drained"]
        and terminal["error_count"] == 0
        and terminal["unexpected_dialog_count"] == 0
    )
    exchange_evidence.update(
        {
            "pass_settings": settings,
            "intent_reconciliation": durability,
            "event_history": history,
            "terminal": terminal,
        }
    )
    return (
        result("execution.multi_stock_head_exchange", "terminal", exchange_ok, exchange_evidence, ("ui", "model", "simulator")),
        result("execution.stock_pass_boundaries_valid", "terminal", boundary_ok, {"pass_boundaries": pass_boundaries}, ("controller", "persistence")),
        result("execution.stock_head_settings_match", "terminal", settings_ok, {"pass_settings": settings, "head_staging": head_staging}, ("ui", "model", "persistence")),
        result("execution.expected_completions", "terminal", completion_ok, {"expected_count": expected_count, "observed_count": len(observed), "completed_well_ids": observed}, ("ui", "model")),
        result("execution.no_queue_starvation", "terminal", not starvation_events, {"unexpected_starvation_events": starvation_events}, ("simulator", "controller")),
        result("execution.intent_durability_exact", "terminal", durability_ok, durability, ("model", "persistence")),
        result("execution.event_history_bounded", "terminal", history_ok, history, ("simulator", "harness")),
        result("execution.terminal_bundle_valid", "terminal", terminal_ok, terminal, ("controller", "model", "persistence")),
    )


def dispense_counts_reconciled_assertion(
    context: Any,
    *,
    prepared_snapshot: Mapping[str, Any],
    calibration_transitions: list[Mapping[str, Any]],
    observer: Mapping[str, Any],
    count_oracle: Mapping[str, Any] | None = None,
) -> AssertionResult:
    """Prove exact catalog-owned or self-consistent simulated dispense counts."""

    oracle_scope = (
        "calibration_requantization_v1_catalog_oracle"
        if count_oracle
        else "slice_9_2_internal_self_consistency"
    )

    required_layers = (
        "prepared_plan",
        "calibration_preview",
        "calibrated_plan",
        "zero_progress",
        "runtime",
        "intent",
        "simulator",
        "terminal_targets",
        "terminal_added",
    )
    expected_headers = [
        "Target",
        "Achievable",
        "Error (%)",
        "Drops",
        "Δ/drop",
        "Printed nL (new)",
        "Δ printed nL",
    ]

    try:
        if not calibration_transitions:
            raise ValueError("calibration count transitions are missing")
        transitions = [dict(item) for item in calibration_transitions]
        final_after = dict(transitions[-1].get("after") or {})
        final_counts = normalize_stock_well_counts(
            final_after.get("plan_targets") or (),
            label="final calibrated plan",
        )
        if not final_counts:
            raise ValueError("final calibrated plan counts are empty")

        oracle_payload = dict(count_oracle or {})
        oracle_evidence: dict[str, Any] | None = None
        prepared_expected = final_counts
        requantized_expected = final_counts
        oracle_schema = int(oracle_payload.get("schema_version", 0) or 0)
        preview_contracts: dict[str, dict[str, Any]] = {}
        if oracle_payload:
            if oracle_payload.get("source") != "calibration_requantization_v1_catalog":
                raise ValueError("catalog count oracle identity is invalid")
            if oracle_schema == 1:
                expected_oracle_keys = {
                    "schema_version", "source", "stock_id", "well_ids",
                    "prepared_droplets_per_well",
                    "requantized_droplets_per_well", "expected_count_delta",
                    "transition", "rounding_boundary_margin",
                }
                if set(oracle_payload) != expected_oracle_keys:
                    raise ValueError("catalog count oracle has an invalid shape")
                stock_id = str(oracle_payload.get("stock_id") or "").strip()
                well_ids = tuple(str(item or "").strip() for item in (
                    oracle_payload.get("well_ids") or ()
                ))
                prepared_count = oracle_payload.get("prepared_droplets_per_well")
                requantized_count = oracle_payload.get("requantized_droplets_per_well")
                if (
                    not stock_id or len(well_ids) != 24
                    or any(not well_id for well_id in well_ids)
                    or len(set(well_ids)) != len(well_ids)
                ):
                    raise ValueError("catalog count oracle identities are invalid")
                for label, value in (("prepared", prepared_count), ("requantized", requantized_count)):
                    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                        raise ValueError(f"catalog {label} count is invalid")
                expected_delta = requantized_count - prepared_count
                if oracle_payload.get("expected_count_delta") != expected_delta:
                    raise ValueError("catalog count oracle delta drifted")
                transition_deltas = {"idempotent": 0, "volume_increase": -1, "volume_decrease": 1}
                if transition_deltas.get(str(oracle_payload.get("transition") or "")) != expected_delta:
                    raise ValueError("catalog count oracle direction drifted")
                margin_payload = dict(oracle_payload.get("rounding_boundary_margin") or {})
                if set(margin_payload) != {"numerator", "denominator"}:
                    raise ValueError("catalog rounding margin has an invalid shape")
                margin = Fraction(margin_payload["numerator"], margin_payload["denominator"])
                if margin < Fraction(1, 3):
                    raise ValueError("catalog rounding margin is below the minimum")
                prepared_expected = tuple(
                    StockWellCount(stock_id, well_id, prepared_count) for well_id in well_ids
                )
                requantized_expected = tuple(
                    StockWellCount(stock_id, well_id, requantized_count) for well_id in well_ids
                )
                preview_contracts[stock_id] = {
                    "preview_kind": "target_rows",
                    "row_groups": (well_ids,),
                }
                oracle_evidence = {
                    **oracle_payload,
                    "prepared_count": prepared_count,
                    "requantized_count": requantized_count,
                    "count_delta": expected_delta,
                    "minimum_margin_satisfied": True,
                }
            elif oracle_schema == 2:
                expected_oracle_keys = {
                    "schema_version", "source", "primary_stock_id", "well_ids",
                    "count_groups", "calibration_steps", "require_terminal_reload",
                }
                if set(oracle_payload) != expected_oracle_keys:
                    raise ValueError("grouped catalog count oracle has an invalid shape")
                well_ids = tuple(str(item or "").strip() for item in oracle_payload.get("well_ids") or ())
                if len(well_ids) != 24 or len(set(well_ids)) != 24 or any(not item for item in well_ids):
                    raise ValueError("grouped catalog well identities are invalid")
                prepared_rows: list[StockWellCount] = []
                final_rows: list[StockWellCount] = []
                grouped_membership: set[tuple[str, str]] = set()
                row_groups: dict[str, list[tuple[int, tuple[str, ...]]]] = {}
                for raw_group in oracle_payload.get("count_groups") or ():
                    group = dict(raw_group)
                    stock_id = str(group.get("stock_id") or "").strip()
                    group_wells = tuple(str(item or "").strip() for item in group.get("well_ids") or ())
                    prepared_count = group.get("prepared_droplets")
                    final_count = group.get("requantized_droplets")
                    if not stock_id or not group_wells or len(set(group_wells)) != len(group_wells):
                        raise ValueError("grouped catalog identities are invalid")
                    for value in (prepared_count, final_count):
                        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                            raise ValueError("grouped catalog count is invalid")
                    rule = str(group.get("rounding_rule") or "")
                    if rule == "nearest_integer":
                        margin_payload = dict(group.get("rounding_boundary_margin") or {})
                        margin = Fraction(margin_payload.get("numerator"), margin_payload.get("denominator"))
                        if margin < Fraction(1, 3):
                            raise ValueError("grouped catalog margin is below the minimum")
                    elif rule == "nonnegative_clamp":
                        if prepared_count != 0 or final_count != 0 or "rounding_boundary_margin" in group:
                            raise ValueError("grouped clamped counts are invalid")
                    else:
                        raise ValueError("grouped catalog rounding rule is invalid")
                    for well_id in group_wells:
                        key = (stock_id, well_id)
                        if key in grouped_membership:
                            raise ValueError("grouped catalog membership overlaps")
                        grouped_membership.add(key)
                        if rule != "nonnegative_clamp":
                            prepared_rows.append(StockWellCount(stock_id, well_id, prepared_count))
                            final_rows.append(StockWellCount(stock_id, well_id, final_count))
                    preview_row = group.get("preview_row")
                    if preview_row is not None:
                        row_groups.setdefault(stock_id, []).append((int(preview_row), group_wells))
                prepared_expected = normalize_stock_well_counts(prepared_rows, label="grouped prepared oracle")
                requantized_expected = normalize_stock_well_counts(final_rows, label="grouped final oracle")
                steps = [dict(item) for item in oracle_payload.get("calibration_steps") or ()]
                if len(steps) != 2 or sum(bool(item.get("primary")) for item in steps) != 1:
                    raise ValueError("grouped catalog calibration steps are invalid")
                for step in steps:
                    stock_id = str(step.get("stock_id") or "")
                    kind = str(step.get("preview_kind") or "")
                    contract = {"preview_kind": kind}
                    if kind == "target_rows":
                        ordered = sorted(row_groups.get(stock_id, ()))
                        if [index for index, _wells in ordered] != list(range(len(ordered))):
                            raise ValueError("grouped preview rows are not contiguous")
                        contract["row_groups"] = tuple(wells for _index, wells in ordered)
                    elif kind != "fill_total":
                        raise ValueError("grouped preview kind is invalid")
                    preview_contracts[stock_id] = contract
                oracle_evidence = {
                    **oracle_payload,
                    "prepared_entry_count": len(prepared_expected),
                    "requantized_entry_count": len(requantized_expected),
                    "positive_intent_count": sum(row.droplets > 0 for row in requantized_expected),
                    "minimum_margin_satisfied": True,
                }
            else:
                raise ValueError("catalog count oracle schema is unsupported")
            if {
                (row.stock_id, row.well_id) for row in final_counts
            } != {
                (row.stock_id, row.well_id) for row in requantized_expected
            }:
                raise ValueError("catalog count oracle membership differs from plan")

        preview_counts: list[StockWellCount] = []
        transition_evidence: list[dict[str, Any]] = []
        prior_after: Mapping[str, Any] | None = None
        for index, transition in enumerate(transitions):
            stock_id = str(transition.get("stock_id") or "")
            before = dict(transition.get("before") or {})
            after = dict(transition.get("after") or {})
            preview = dict(transition.get("preview") or {})
            table = dict(preview.get("visible_table") or {})
            after_stock_counts = normalize_stock_well_counts(
                (
                    row
                    for row in after.get("plan_targets") or ()
                    if str(row.get("stock_id") or "") == stock_id
                ),
                label=f"calibration transition {index} stock counts",
            )
            if not after_stock_counts:
                raise ValueError(
                    f"calibration transition {index} has no stock counts"
                )
            if table.get("headers") != expected_headers:
                raise ValueError(
                    f"calibration transition {index} preview headers differ"
                )
            contract = preview_contracts.get(stock_id, {})
            preview_kind = str(contract.get("preview_kind") or "target_rows")
            if preview_kind == "target_rows":
                row_groups = contract.get("row_groups") or (
                    tuple(row.well_id for row in after_stock_counts),
                )
                projected = project_single_stock_preview_counts(
                    preview, stock_id=stock_id, well_ids_by_row=row_groups
                )
            elif preview_kind == "fill_total":
                rows = list(table.get("rows") or ())
                if table.get("row_count") != 1 or len(rows) != 1:
                    raise ValueError("fill preview requires one aggregate row")
                drops_column = list(table.get("headers") or ()).index("Drops")
                displayed = rows[0][drops_column]
                expected_total = sum(row.droplets for row in after_stock_counts)
                if str(displayed) != str(expected_total):
                    raise ValueError("fill preview aggregate count differs from oracle")
                projected = after_stock_counts
            else:
                raise ValueError("preview projection kind is unsupported")
            preview_counts.extend(projected)
            added = normalize_stock_well_counts(
                after.get("progress_added") or (),
                label=f"calibration transition {index} progress added",
            )
            calibrated_stock_added = tuple(
                row for row in added if row.stock_id == stock_id
            )
            if not calibrated_stock_added:
                raise ValueError(
                    f"calibration transition {index} has no stock progress"
                )
            revision_advanced = int(after.get("plan_revision", -1)) > int(
                before.get("plan_revision", -1)
            )
            chain_contiguous = prior_after is None or (
                before.get("plan_id") == prior_after.get("plan_id")
                and before.get("plan_revision") == prior_after.get("plan_revision")
                and before.get("plan_targets") == prior_after.get("plan_targets")
            )
            transition_evidence.append(
                {
                    "stock_id": stock_id,
                    "before_revision": before.get("plan_revision"),
                    "after_revision": after.get("plan_revision"),
                    "revision_advanced": revision_advanced,
                    "chain_contiguous": chain_contiguous,
                    "zero_progress": all(
                        row.droplets == 0 for row in calibrated_stock_added
                    ),
                    "preview": preview,
                }
            )
            prior_after = after

        lifecycle = dict(observer.get("lifecycle") or {})
        intent_counts, simulator_counts, command_join = intent_and_simulator_counts(
            lifecycle
        )
        terminal = capture_count_snapshot(context, include_runtime=False)
        observed = {
            "prepared_plan": prepared_snapshot.get("plan_targets") or (),
            "calibration_preview": preview_counts,
            "calibrated_plan": final_counts,
            "zero_progress": final_after.get("progress_targets") or (),
            "runtime": final_after.get("runtime_targets") or (),
            "intent": intent_counts,
            "simulator": simulator_counts,
            "terminal_targets": terminal.get("progress_targets") or (),
            "terminal_added": terminal.get("progress_added") or (),
        }
        expected = {
            name: (
                prepared_expected
                if name == "prepared_plan"
                else tuple(
                    row for row in requantized_expected if row.droplets > 0
                )
                if name in {"intent", "simulator"}
                else requantized_expected
            )
            for name in required_layers
        }
        reconciliation = reconcile_stock_well_counts(
            expected=expected,
            observed=observed,
            required_layers=required_layers,
        )
        checks = {
            "count_layers_exact": reconciliation.passed,
            "prepared_plan_id_matches": prepared_snapshot.get("plan_id")
            == final_after.get("plan_id"),
            "calibration_revisions_advance": all(
                row["revision_advanced"] for row in transition_evidence
            ),
            "calibration_chain_contiguous": all(
                row["chain_contiguous"] for row in transition_evidence
            ),
            "calibration_progress_zero": all(
                row["zero_progress"] for row in transition_evidence
            ),
            "terminal_plan_id_matches": terminal.get("plan_id")
            == final_after.get("plan_id"),
            "terminal_state_completed": terminal.get("plan_state") == "completed",
            "observer_restored": observer.get("restored") is True,
            "catalog_oracle_valid": bool(oracle_evidence) if count_oracle else True,
        }
        evidence = {
            "schema_version": 1,
            "oracle_scope": oracle_scope,
            "count_oracle": oracle_evidence,
            "checks": checks,
            "prepared": dict(prepared_snapshot),
            "calibration_transitions": transition_evidence,
            "calibrated": final_after,
            "terminal": terminal,
            "command_join": command_join,
            "reconciliation": reconciliation.to_dict(),
        }
        passed = all(checks.values())
        return AssertionResult(
            "execution.dispense_counts_reconciled",
            "terminal",
            "pass" if passed else "fail",
            ("ui", "model", "persistence", "simulator"),
            evidence,
            None if passed else "dispense-count evidence did not reconcile exactly",
        )
    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
        return AssertionResult(
            "execution.dispense_counts_reconciled",
            "terminal",
            "fail",
            ("ui", "model", "persistence", "simulator"),
            {
                "schema_version": 1,
                "oracle_scope": oracle_scope,
                "error": f"{type(exc).__name__}: {exc}",
            },
            "dispense-count evidence was incomplete or malformed",
        )


def calibration_apply_fail_closed_assertion(
    context: Any,
    *,
    boundary: Mapping[str, Any],
    observer: Mapping[str, Any],
    oracle: Mapping[str, Any],
    action_results: list[Mapping[str, Any]],
    pass_boundaries: list[Mapping[str, Any]],
    completed_wells: list[str],
) -> AssertionResult:
    """Prove a missing-fill Apply rejection is byte-identical and dispatch-free."""

    try:
        from tools.virtual_workflows.authoritative_evidence import compare_directories

        before = boundary["before_bundle"]
        after = boundary["after_bundle"]
        before_counts = dict(boundary.get("before_counts") or {})
        after_counts = dict(boundary.get("after_counts") or {})
        before_machine = dict(boundary.get("before_machine") or {})
        after_machine = dict(boundary.get("after_machine") or {})
        failure = dict(boundary.get("failure") or {})
        preview = dict(boundary.get("preview") or {})
        table = dict(preview.get("visible_table") or {})
        rows = list(table.get("rows") or ())
        headers = list(table.get("headers") or ())
        drops_column = headers.index("Drops")
        displayed_counts = [row[drops_column] for row in rows]
        directory = compare_directories(before.directory, after.directory).to_dict()
        lifecycle = dict(observer.get("lifecycle") or {})
        action_ids = [str(row.get("action_id") or "") for row in action_results]
        oracle_payload = dict(oracle)
        expected_keys = {
            "schema_version", "source", "stock_id", "well_ids",
            "accepted_calibration", "rejected_calibration", "count_oracle",
            "expected_plan_state", "expected_title", "expected_message_fragment",
            "expected_calibration_record_count", "expected_intent_count",
            "expected_simulator_dispense_count", "expected_pass_boundary_count",
            "expected_completion_count",
        }
        oracle_valid = (
            set(oracle_payload) == expected_keys
            and oracle_payload.get("schema_version") == 1
            and oracle_payload.get("source")
            == "calibration_requantization_v1_catalog"
            and len(oracle_payload.get("well_ids") or ()) == 24
            and len(set(oracle_payload.get("well_ids") or ())) == 24
            and dict(oracle_payload.get("count_oracle") or {}).get(
                "hypothetical_reagent_droplets"
            ) == 0
            and dict(oracle_payload.get("count_oracle") or {}).get(
                "hypothetical_missing_fill_droplets"
            ) == 1
        )
        bundle_checks = {
            "bundle_objects_equal": before == after,
            "plan_json_equal": before.plan_json == after.plan_json,
            "history_equal": before.history_json == after.history_json,
            "progress_equal": before_counts == after_counts,
            "eligibility_equal": before.eligibility_json == after.eligibility_json,
            "calibration_count_equal": before.calibration_record_count
            == after.calibration_record_count,
            "audit_equal": before.audit_rows_json == after.audit_rows_json,
            "key_rows_equal": before.key_rows_json == after.key_rows_json,
            "concentration_rows_equal": before.concentration_rows_json
            == after.concentration_rows_json,
            "files_byte_identical": directory["checks"]["files_byte_identical"],
        }
        dispatch_counts = {
            "begins": len(lifecycle.get("begins") or ()),
            "attachments": len(lifecycle.get("attachments") or ()),
            "completions": len(lifecycle.get("completions") or ()),
            "simulator_dispenses": len(lifecycle.get("simulator_dispenses") or ()),
        }
        checks = {
            "oracle_valid": oracle_valid,
            "authoritative_bundle_byte_identical": all(bundle_checks.values()),
            "machine_boundary_unchanged": before_machine == after_machine,
            "active_zero_progress": (
                before.plan_state == after.plan_state
                == oracle_payload.get("expected_plan_state")
                and before.total_added_droplets == after.total_added_droplets == 0
            ),
            "one_accepted_calibration_only": (
                before.calibration_record_count
                == after.calibration_record_count
                == oracle_payload.get("expected_calibration_record_count")
                and before.manual_refuel_check_count
                == after.manual_refuel_check_count == 0
            ),
            "preview_zero_exact": bool(rows)
            and all(str(value) == "0" for value in displayed_counts),
            "failure_dialog_exact": (
                boundary.get("handled_dialogs")
                == ["Apply calibration as mode switch?", oracle_payload.get("expected_title")]
                and failure.get("title") == oracle_payload.get("expected_title")
                and oracle_payload.get("expected_message_fragment")
                in str(failure.get("text") or "")
                and failure.get("icon") == "Critical"
            ),
            "zero_execution_dispatch": all(value == 0 for value in dispatch_counts.values())
            and action_ids.count("array.start_via_ui") == 0,
            "zero_completion_boundaries": (
                len(completed_wells)
                == oracle_payload.get("expected_completion_count")
                and len(pass_boundaries)
                == oracle_payload.get("expected_pass_boundary_count")
            ),
            "terminal_cleanup_safe": (
                context.controller.get_array_run_state() == "idle"
                and context.machine.check_if_all_completed()
                and context.model.rack_model.get_gripper_printer_head() is None
                and observer.get("restored") is True
            ),
        }
        evidence = {
            "schema_version": 1,
            "oracle": oracle_payload,
            "checks": checks,
            "bundle_checks": bundle_checks,
            "directory_comparison": directory,
            "plan": {
                "plan_id": before.plan_id,
                "plan_revision": before.plan_revision,
                "plan_state": before.plan_state,
                "lock_reason": before.plan_lock_reason,
                "history_count": len(before.history_json),
                "calibration_record_count": before.calibration_record_count,
                "total_added_droplets": before.total_added_droplets,
            },
            "preview": preview,
            "failure": failure,
            "handled_dialogs": list(boundary.get("handled_dialogs") or ()),
            "machine_boundary": before_machine,
            "dispatch_counts": dispatch_counts,
            "action_ids": action_ids,
        }
        passed = all(checks.values())
        return AssertionResult(
            "execution.calibration_apply_fail_closed",
            "terminal",
            "pass" if passed else "fail",
            ("ui", "controller", "model", "persistence", "simulator"),
            evidence,
            None if passed else "calibration rejection mutated state or dispatched work",
        )
    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
        return AssertionResult(
            "execution.calibration_apply_fail_closed",
            "terminal",
            "fail",
            ("ui", "controller", "model", "persistence", "simulator"),
            {"schema_version": 1, "error": f"{type(exc).__name__}: {exc}"},
            "calibration rejection evidence was incomplete or malformed",
        )


def two_reagent_isolation_assertion(
    context: Any,
    *,
    boundary: Mapping[str, Any],
    observer: Mapping[str, Any],
    oracle: Mapping[str, Any],
) -> AssertionResult:
    """Prove reagent-two requantization preserves completed reagent-one truth."""

    try:
        from tools.virtual_workflows.dispense_counts import (
            intent_and_simulator_counts,
            normalize_stock_well_counts,
        )

        before = boundary["before"]
        after = boundary["after"]
        transition = dict(boundary.get("count_transition") or {})
        count_before = dict(transition.get("before") or {})
        count_after = dict(transition.get("after") or {})
        oracle_payload = dict(oracle)
        expected_keys = {
            "schema_version", "source", "stock_ids", "primary_stock_id",
            "well_ids", "first_pass_completion_count", "expected_total_droplets",
        }
        stock_ids = tuple(oracle_payload.get("stock_ids") or ())
        primary = str(oracle_payload.get("primary_stock_id") or "")
        support = stock_ids[0] if len(stock_ids) == 2 else ""
        well_ids = tuple(oracle_payload.get("well_ids") or ())
        oracle_valid = (
            set(oracle_payload) == expected_keys
            and oracle_payload.get("schema_version") == 1
            and oracle_payload.get("source")
            == "calibration_requantization_v1_catalog"
            and len(stock_ids) == 2
            and primary == stock_ids[1]
            and len(well_ids) == len(set(well_ids)) == 24
            and oracle_payload.get("first_pass_completion_count") == 24
            and oracle_payload.get("expected_total_droplets") == 72
        )

        def rows_by_stock(raw: Any) -> dict[str, dict[str, int]]:
            rows = normalize_stock_well_counts(raw or (), label="isolation counts")
            output: dict[str, dict[str, int]] = {}
            for row in rows:
                output.setdefault(row.stock_id, {})[row.well_id] = row.droplets
            return output

        plan_before = rows_by_stock(count_before.get("plan_targets"))
        plan_after = rows_by_stock(count_after.get("plan_targets"))
        progress_before = rows_by_stock(count_before.get("progress_added"))
        progress_after = rows_by_stock(count_after.get("progress_added"))
        runtime_before = rows_by_stock(count_before.get("runtime_targets"))
        runtime_after = rows_by_stock(count_after.get("runtime_targets"))
        before_stocks = {
            str(stock_id): dict(item)
            for stock_id, item in dict(before.plan.get("stocks") or {}).items()
        }
        after_stocks = {
            str(stock_id): dict(item)
            for stock_id, item in dict(after.plan.get("stocks") or {}).items()
        }
        intent_rows, simulator_rows, command_join = intent_and_simulator_counts(
            dict(observer.get("lifecycle") or {})
        )
        intents = rows_by_stock(intent_rows)
        simulator = rows_by_stock(simulator_rows)
        expected_wells = set(well_ids)
        checks = {
            "oracle_valid": oracle_valid,
            "plan_identity_stable": (
                before.plan_id == after.plan_id
                and before.design_sha256 == after.design_sha256
                and before.plan_assignments == after.plan_assignments
                and before.plan_well_ids == after.plan_well_ids
            ),
            "revision_append_exact": (
                after.plan_revision == before.plan_revision + 1
                and len(after.history_json) == len(before.history_json) + 1
                and after.history_json[:-1] == before.history_json
                and after.history_matches_current
            ),
            "support_plan_unchanged": plan_before.get(support)
            == plan_after.get(support)
            == {well_id: 1 for well_id in well_ids},
            "support_progress_preserved": progress_before.get(support)
            == progress_after.get(support)
            == {well_id: 1 for well_id in well_ids},
            "support_runtime_unchanged": runtime_before.get(support)
            == runtime_after.get(support)
            == {well_id: 1 for well_id in well_ids},
            "support_stock_linkage_unchanged": before_stocks.get(support)
            == after_stocks.get(support),
            "primary_alone_retargeted": (
                plan_before.get(primary) == {well_id: 1 for well_id in well_ids}
                and plan_after.get(primary) == {well_id: 2 for well_id in well_ids}
                and runtime_before.get(primary) == {well_id: 1 for well_id in well_ids}
                and runtime_after.get(primary) == {well_id: 2 for well_id in well_ids}
            ),
            "primary_progress_zero_at_apply": progress_before.get(primary)
            == progress_after.get(primary)
            == {well_id: 0 for well_id in well_ids},
            "stock_membership_exact": set(before_stocks) == set(after_stocks)
            == set(stock_ids),
            "execution_exact_once": (
                set(intents) == set(simulator) == set(stock_ids)
                and set(intents.get(support, {})) == expected_wells
                and set(intents.get(primary, {})) == expected_wells
                and intents.get(support) == {well_id: 1 for well_id in well_ids}
                and intents.get(primary) == {well_id: 2 for well_id in well_ids}
                and simulator == intents
                and len(command_join.get("joined_commands") or ()) == 48
                and sum(row.droplets for row in intent_rows)
                == oracle_payload.get("expected_total_droplets")
            ),
            "terminal_completed": (
                context.experiment_model.get_execution_plan_snapshot().state.value
                == "completed"
                and observer.get("restored") is True
            ),
        }
        evidence = {
            "schema_version": 1,
            "oracle": oracle_payload,
            "checks": checks,
            "before": {
                "plan_id": before.plan_id,
                "plan_revision": before.plan_revision,
                "history_count": len(before.history_json),
                "total_added_droplets": before.total_added_droplets,
                "calibration_record_count": before.calibration_record_count,
            },
            "after": {
                "plan_id": after.plan_id,
                "plan_revision": after.plan_revision,
                "history_count": len(after.history_json),
                "total_added_droplets": after.total_added_droplets,
                "calibration_record_count": after.calibration_record_count,
            },
            "support_stock_id": support,
            "primary_stock_id": primary,
            "count_transition": transition,
            "command_join": command_join,
            "total_commanded_droplets": sum(row.droplets for row in intent_rows),
        }
        passed = all(checks.values())
        return AssertionResult(
            "execution.two_reagent_isolation_exact",
            "terminal",
            "pass" if passed else "fail",
            ("ui", "model", "persistence", "simulator"),
            evidence,
            None if passed else "two-reagent calibration isolation was not exact",
        )
    except (IndexError, KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
        return AssertionResult(
            "execution.two_reagent_isolation_exact",
            "terminal",
            "fail",
            ("ui", "model", "persistence", "simulator"),
            {"schema_version": 1, "error": f"{type(exc).__name__}: {exc}"},
            "two-reagent isolation evidence was incomplete or malformed",
        )


def multi_stock_terminal_assertions(
    context: Any,
    *,
    fixture: Mapping[str, Any],
    expected_well_ids: tuple[str, ...],
    expected_stock_ids: tuple[str, ...],
    completed_wells: list[str],
    pass_boundaries: list[Mapping[str, Any]],
    head_staging: list[Mapping[str, Any]],
    starvation_events: list[Mapping[str, Any]],
    observer: Mapping[str, Any],
) -> tuple[AssertionResult, ...]:
    """Compatibility wrapper for the Slice 2 public assertion helper."""

    return execution_lifecycle_assertions(
        context,
        expectation=ExecutionLifecycleExpectation(
            fixture=fixture,
            expected_well_ids=expected_well_ids,
            expected_stock_ids=expected_stock_ids,
        ),
        completed_wells=completed_wells,
        pass_boundaries=pass_boundaries,
        head_staging=head_staging,
        starvation_events=starvation_events,
        observer=observer,
    )


def mixed_mode_lifecycle_assertions(
    context: Any,
    *,
    fixture: Mapping[str, Any],
    manual_refuel_checks: list[Mapping[str, Any]],
    action_results: list[Mapping[str, Any]],
) -> tuple[AssertionResult, AssertionResult]:
    """Validate persisted mixed calibration identities and the stream gate."""

    from ExecutionCalibrationStore import load_execution_calibrations

    document = load_execution_calibrations(
        context.experiment_model.execution_calibrations_file_path
    )
    expected_stocks = list(fixture["stocks"])
    expected_by_id = {
        f"{stock['factor_name']}_{float(stock['concentration']):.2f}_{stock['units']}": stock
        for stock in expected_stocks
    }
    records = [record.to_dict() for record in document.records.values()]
    records_by_stock = {str(record["stock_id"]): record for record in records}
    calibration_rows = []
    calibration_ok = len(records) == len(expected_by_id)
    for stock_id, stock in expected_by_id.items():
        head = stock["printer_head"]
        record = records_by_stock.get(stock_id, {})
        row = {
            "stock_id": stock_id,
            "printer_head_id": record.get("printer_head_id"),
            "printing_mode": record.get("printing_mode"),
            "effective_volume_nL": record.get("effective_volume_nL"),
            "pw_us": record.get("pw_us"),
            "record_id": record.get("record_id"),
        }
        calibration_rows.append(row)
        calibration_ok = calibration_ok and (
            record.get("printer_head_id") == head["printer_head_id"]
            and record.get("printing_mode") == stock["printing_mode"]
            and record.get("applied_printing_mode") == stock["printing_mode"]
            and int(record.get("pw_us") or 0) == int(head["print_pulse_width_us"])
            and abs(
                float(record.get("effective_volume_nL") or -1)
                - float(stock["droplet_volume_nL"])
            ) < 1e-6
            and abs(
                float(record.get("applied_design_volume_nL") or -1)
                - float(stock["prepared_droplet_volume_nL"])
            ) < 1e-6
        )

    calibration_assertion = AssertionResult(
        "execution.mixed_mode_calibrations_valid",
        "terminal",
        "pass" if calibration_ok else "fail",
        ("ui", "model", "persistence"),
        {
            "expected_modes": [stock["printing_mode"] for stock in expected_stocks],
            "calibration_records": calibration_rows,
        },
        None if calibration_ok else "mixed calibration records did not match the fixture",
    )

    lifecycle = fixture["lifecycle"]["manual_refuel_check"]
    stream_stock = next(
        stock for stock in expected_stocks if stock["printing_mode"] == "stream"
    )
    stream_id = (
        f"{stream_stock['factor_name']}_{float(stream_stock['concentration']):.2f}_"
        f"{stream_stock['units']}"
    )
    stream_record = records_by_stock.get(stream_id, {})
    persisted_checks = list(document.manual_refuel_checks.values())
    persisted = dict(persisted_checks[0]) if len(persisted_checks) == 1 else {}
    driver_record = (
        dict(manual_refuel_checks[0].get("record") or {})
        if len(manual_refuel_checks) == 1 else {}
    )
    action_ids = [str(row.get("action_id") or "") for row in action_results]
    apply_indexes = [
        index for index, value in enumerate(action_ids)
        if value == "calibration.apply_via_ui"
    ]
    start_indexes = [
        index for index, value in enumerate(action_ids)
        if value == "array.start_via_ui"
    ]
    manual_indexes = [
        index for index, value in enumerate(action_ids)
        if value == "manual_refuel.complete_check_via_ui"
    ]
    ordering_ok = (
        len(apply_indexes) == 2
        and len(start_indexes) == 2
        and len(manual_indexes) == 1
        and apply_indexes[1] < manual_indexes[0] < start_indexes[1]
    )
    head = stream_stock["printer_head"]
    refuel_ok = (
        len(persisted_checks) == 1
        and len(manual_refuel_checks) == 1
        and persisted == driver_record
        and persisted.get("status") == lifecycle["status"]
        and persisted.get("source") == "sil_simulated_manual_refuel_check"
        and persisted.get("stock_id") == stream_id
        and persisted.get("printer_head_id") == head["printer_head_id"]
        and persisted.get("printing_mode") == "stream"
        and persisted.get("operator_judgment") == lifecycle["operator_judgment"]
        and int(persisted.get("trial_count") or 0) == lifecycle["trial_count"]
        and int(persisted.get("trial_droplet_count") or 0)
        == lifecycle["trial_droplet_count"]
        and int(persisted.get("print_pulse_width_us") or 0)
        == head["print_pulse_width_us"]
        and int(persisted.get("refuel_pulse_width_us") or 0)
        == head["refuel_pulse_width_us"]
        and abs(
            float(persisted.get("target_refuel_pressure_psi") or -1)
            - float(head["refuel_pressure_psi"])
        ) < 0.01
        and persisted.get("calibration_record_id") == stream_record.get("record_id")
        and bool(persisted.get("applied_calibration_fingerprint"))
        and ordering_ok
    )
    refuel_evidence = {
        "persisted_record": persisted,
        "driver_record_matched": persisted == driver_record,
        "action_order": {
            "stream_apply_index": apply_indexes[1] if len(apply_indexes) > 1 else None,
            "manual_refuel_index": manual_indexes[0] if manual_indexes else None,
            "stream_start_index": start_indexes[1] if len(start_indexes) > 1 else None,
            "valid": ordering_ok,
        },
    }
    refuel_assertion = AssertionResult(
        "execution.stream_manual_refuel_passed",
        "terminal",
        "pass" if refuel_ok else "fail",
        ("ui", "controller", "model", "persistence"),
        refuel_evidence,
        None if refuel_ok else "stream manual-refuel gate evidence was invalid",
    )
    return calibration_assertion, refuel_assertion


def matrix_case_assertions(
    context: Any,
    *,
    fixture: Mapping[str, Any],
    completed_wells: list[str],
    head_staging: list[Mapping[str, Any]],
    pass_boundaries: list[Mapping[str, Any]],
    manual_refuel_checks: list[Mapping[str, Any]],
    action_results: list[Mapping[str, Any]],
    block_evidence: Mapping[str, Any] | None,
) -> tuple[AssertionResult, AssertionResult]:
    """Validate one normalized matrix case, including expected safe cancellation."""

    from ExecutionCalibrationStore import load_execution_calibrations
    from ExecutionResumeStore import load_execution_resume

    lifecycle = dict(fixture["lifecycle"])
    case = dict(lifecycle["case"])
    profile = dict(lifecycle["profile"])
    matrix_id = str(lifecycle.get("matrix_id") or "")
    registered_case_valid = False
    registered_error: str | None = None
    try:
        from tools.virtual_workflows.matrices import (
            catalog_sha256,
            get_matrix_case,
            resolve_matrix_plan,
        )

        registered = get_matrix_case(matrix_id, str(case.get("case_id") or ""))
        registered_payload = dict(registered.normalized())
        registered_plan = resolve_matrix_plan(
            matrix_id,
            case_id=str(case.get("case_id") or ""),
        )
        registered_case_valid = (
            case == registered_payload
            and lifecycle.get("catalog_sha256") == catalog_sha256(matrix_id)
            and lifecycle.get("case_sha256")
            == registered_plan["cases"][0]["case_sha256"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        registered_error = f"{type(exc).__name__}: {exc}"
    expected_terminal = str(case["expected_terminal"])
    expected_count = int(case["expected_completion_count"])
    expected_stocks = list(fixture["stocks"])
    expected_by_id = {
        f"{stock['factor_name']}_{float(stock['concentration']):.2f}_{stock['units']}": stock
        for stock in expected_stocks
    }
    staged_ids = [str(row.get("stock_id") or "") for row in head_staging]
    expected_order = list(expected_by_id)
    document = load_execution_calibrations(
        context.experiment_model.execution_calibrations_file_path
    )
    records = [record.to_dict() for record in document.records.values()]
    records_by_stock = {str(record.get("stock_id")): record for record in records}
    calibration_rows: list[dict[str, Any]] = []
    calibration_ok = staged_ids == expected_order[: len(staged_ids)]
    for stock_id in staged_ids:
        stock = expected_by_id.get(stock_id, {})
        head = dict(stock.get("printer_head") or {})
        record = records_by_stock.get(stock_id, {})
        row = {
            "stock_id": stock_id,
            "printer_head_id": record.get("printer_head_id"),
            "printing_mode": record.get("printing_mode"),
            "pw_us": record.get("pw_us"),
            "effective_volume_nL": record.get("effective_volume_nL"),
        }
        calibration_rows.append(row)
        expected_mode = str(
            stock.get("calibration_mode") or stock.get("printing_mode") or ""
        )
        calibration_ok = calibration_ok and bool(stock) and (
            record.get("printer_head_id") == head.get("printer_head_id")
            and record.get("printing_mode") == expected_mode
            and int(record.get("pw_us") or 0)
            == int(head.get("print_pulse_width_us") or 0)
            and abs(
                float(record.get("effective_volume_nL") or -1)
                - float(stock.get("droplet_volume_nL") or -2)
            )
            < 1e-6
        )
    refuel_expected = sum(
        str(
            expected_by_id[stock_id].get("calibration_mode")
            or expected_by_id[stock_id]["printing_mode"]
        ) == "stream"
        for stock_id in staged_ids
    )
    plan = context.experiment_model.get_execution_plan_snapshot()
    count_oracle = dict(lifecycle.get("dispense_count_oracle") or {})
    rejection_oracle = dict(
        lifecycle.get("calibration_rejection_oracle") or {}
    )
    oracle_case_linked = True
    if count_oracle:
        if int(count_oracle.get("schema_version", 1)) == 2:
            oracle_case_linked = (
                count_oracle.get("source")
                == "calibration_requantization_v1_catalog"
                and set(count_oracle.get("well_ids") or ())
                == {well.well_id for well in plan.wells}
                and count_oracle.get("count_groups") == case.get("count_groups")
                and count_oracle.get("calibration_steps")
                == case.get("calibration_steps")
                and bool(count_oracle.get("require_terminal_reload"))
                == bool(case.get("require_terminal_reload"))
                and count_oracle.get("primary_stock_id") in expected_by_id
            )
        else:
            margin = dict(case.get("rounding_boundary_margin") or {})
            oracle_case_linked = (
                count_oracle.get("source")
                == "calibration_requantization_v1_catalog"
                and count_oracle.get("stock_id") in expected_by_id
                and len(tuple(count_oracle.get("well_ids") or ()))
                == len(plan.wells)
                and set(count_oracle.get("well_ids") or ())
                == {well.well_id for well in plan.wells}
                and count_oracle.get("prepared_droplets_per_well")
                == case.get("expected_prepared_droplets")
                and count_oracle.get("requantized_droplets_per_well")
                == case.get("expected_requantized_droplets")
                and count_oracle.get("expected_count_delta")
                == case.get("expected_count_delta")
                and count_oracle.get("transition") == case.get("transition")
                and count_oracle.get("rounding_boundary_margin") == margin
            )
    rejection_case_linked = True
    if rejection_oracle:
        rejection_case_linked = (
            case.get("case_kind") == "missing_fill_requantization"
            and rejection_oracle.get("source")
            == "calibration_requantization_v1_catalog"
            and rejection_oracle.get("stock_id") in expected_by_id
            and set(rejection_oracle.get("well_ids") or ())
            == {well.well_id for well in plan.wells}
            and rejection_oracle.get("accepted_calibration")
            == case.get("accepted_calibration")
            and rejection_oracle.get("rejected_calibration")
            == case.get("rejected_calibration")
            and rejection_oracle.get("count_oracle")
            == case.get("count_oracle")
            and rejection_oracle.get("expected_completion_count")
            == case.get("expected_completion_count")
        )
    if case.get("case_kind") in {
        "composite_requantization",
        "two_reagent_isolation",
    }:
        profile_ok = profile.get("calibration_steps") == case.get(
            "calibration_steps"
        )
    elif case.get("case_kind") == "missing_fill_requantization":
        profile_ok = (
            profile.get("accepted_calibration")
            == case.get("accepted_calibration")
            and profile.get("rejected_calibration")
            == case.get("rejected_calibration")
        )
    else:
        profile_ok = profile.get("profile_id") == case.get("profile_id")
    parameter_ok = (
        bool(matrix_id)
        and registered_case_valid
        and oracle_case_linked
        and rejection_case_linked
        and len(expected_stocks) >= 1
        and calibration_ok
        and len(records) == len(staged_ids)
        and len(manual_refuel_checks) == refuel_expected
        and profile_ok
    )
    parameter_evidence = {
        "matrix_id": lifecycle.get("matrix_id"),
        "catalog_sha256": lifecycle.get("catalog_sha256"),
        "case_sha256": lifecycle.get("case_sha256"),
        "case": case,
        "profile": profile,
        "expected_stock_order": expected_order,
        "staged_stock_order": staged_ids,
        "calibration_records": calibration_rows,
        "manual_refuel_check_count": len(manual_refuel_checks),
        "registered_case_valid": registered_case_valid,
        "registered_case_error": registered_error,
        "count_oracle_linked_to_case": oracle_case_linked,
        "calibration_rejection_oracle_linked_to_case": rejection_case_linked,
    }
    parameter_assertion = AssertionResult(
        "execution.matrix_case_parameters_applied",
        "terminal",
        "pass" if parameter_ok else "fail",
        ("ui", "model", "persistence"),
        parameter_evidence,
        None if parameter_ok else "matrix parameters were not applied exactly",
    )

    resume_path = Path(context.experiment_model.execution_resume_file_path)
    resume = load_execution_resume(resume_path) if resume_path.is_file() else None
    resume_state = str(resume.state) if resume is not None else "absent_clean"
    resume_intents = list(resume.intents) if resume is not None else []
    gripper_empty = context.model.rack_model.get_gripper_printer_head() is None
    action_ids = [str(row.get("action_id") or "") for row in action_results]
    block = dict(block_evidence or {})
    persisted_checks = [dict(item) for item in document.manual_refuel_checks.values()]
    blocked_check = next(
        (
            item
            for item in persisted_checks
            if item.get("stock_id") == block.get("stock_id")
            and item.get("printer_head_id") == block.get("printer_head_id")
        ),
        {},
    )
    expected_plan_state = (
        "completed" if expected_terminal == "completed" else "active"
    )
    common_ok = (
        len(completed_wells) == expected_count
        and str(plan.state.value) == expected_plan_state
        and context.controller.get_array_run_state() == "idle"
        and context.machine.check_if_all_completed()
        and resume_state in {"clean", "absent_clean"}
        and len(resume_intents) == 0
        and gripper_empty
        and not context.errors
        and not context.unexpected_dialogs
    )
    if expected_terminal == "completed":
        outcome_ok = (
            common_ok
            and not block
            and len(pass_boundaries) == len(expected_stocks)
            and all(item.get("status") == "passed" for item in persisted_checks)
        )
    elif expected_terminal == "manual_refuel_cancelled":
        dialog_titles = [str(row.get("title") or "") for row in block.get("dialogs", [])]
        expected_status = next(
            (
                item["status"]
                for item in case["refuel_outcomes"]
                if item["status"] != "passed"
            ),
            None,
        )
        expected_judgment = next(
            (
                item["operator_judgment"]
                for item in case["refuel_outcomes"]
                if item["status"] != "passed"
            ),
            None,
        )
        manual_indexes = [
            index for index, value in enumerate(action_ids)
            if value == "manual_refuel.complete_check_via_ui"
        ]
        start_indexes = [
            index for index, value in enumerate(action_ids)
            if value == "array.start_via_ui"
        ]
        outcome_ok = (
            common_ok
            and block.get("terminal") == "manual_refuel_cancelled"
            and block.get("cancelled") is True
            and block.get("completion_count_before")
            == block.get("completion_count_after") == expected_count
            and block.get("plan_state_before")
            == block.get("plan_state_after") == expected_plan_state
            and dialog_titles[-2:]
            == ["Start Print Array", "Manual Refuel Check Required"]
            and blocked_check.get("status") == expected_status
            and blocked_check.get("operator_judgment") == expected_judgment
            and blocked_check.get("source") == "sil_simulated_manual_refuel_check"
            and bool(blocked_check.get("applied_calibration_fingerprint"))
            and manual_indexes
            and start_indexes
            and manual_indexes[-1] < start_indexes[-1]
        )
    elif expected_terminal == "calibration_apply_rejected":
        outcome_ok = (
            common_ok
            and block.get("terminal") == "calibration_apply_rejected"
            and block.get("handled_dialogs")
            == ["Apply calibration as mode switch?", "Apply failed"]
            and block.get("failure", {}).get("title") == "Apply failed"
            and case.get("expected_warning_fragment")
            in str(block.get("failure", {}).get("text") or "")
            and len(pass_boundaries) == 0
            and action_ids.count("array.start_via_ui") == 0
            and len(persisted_checks) == 0
        )
    else:
        outcome_ok = False
    outcome_evidence = {
        "expected_terminal": expected_terminal,
        "expected_completion_count": expected_count,
        "observed_completion_count": len(completed_wells),
        "expected_plan_state": expected_plan_state,
        "observed_plan_state": str(plan.state.value),
        "block": block,
        "persisted_manual_refuel_checks": persisted_checks,
        "pass_boundaries": [dict(item) for item in pass_boundaries],
        "queue_drained": bool(context.machine.check_if_all_completed()),
        "checkpoint_state": resume_state,
        "checkpoint_intent_count": len(resume_intents),
        "gripper_empty": gripper_empty,
        "array_state": context.controller.get_array_run_state(),
    }
    outcome_assertion = AssertionResult(
        "execution.matrix_case_outcome_valid",
        "terminal",
        "pass" if outcome_ok else "fail",
        ("ui", "controller", "model", "persistence", "simulator"),
        outcome_evidence,
        None if outcome_ok else "matrix terminal outcome or safeguard was invalid",
    )
    return parameter_assertion, outcome_assertion


def multi_stock_artifacts_assertion(
    *,
    screenshots: Mapping[str, Path],
    required_screenshots: set[str],
    teardown: Mapping[str, Any],
) -> AssertionResult:
    def inspect() -> tuple[bool, Mapping[str, Any]]:
        cleanup = dict(teardown.get("evidence") or {})
        observed = set(screenshots)
        evidence = {
            "required_screenshots": sorted(required_screenshots),
            "observed_screenshots": sorted(observed),
            "nonempty": all(
                path.is_file() and path.stat().st_size > 0
                for path in screenshots.values()
            ),
            "close_succeeded": bool(cleanup.get("close_succeeded")),
            "session_lock_present": bool(cleanup.get("session_lock_present")),
        }
        return (
            observed == required_screenshots
            and evidence["nonempty"]
            and evidence["close_succeeded"]
            and not evidence["session_lock_present"],
            evidence,
        )

    return evaluate_assertion(
        "artifacts.required_present",
        "closed",
        ("harness", "session"),
        inspect,
    )


def rack_head_assertion(context: Any) -> AssertionResult:
    def inspect() -> tuple[bool, Mapping[str, Any]]:
        head = context.model.rack_model.get_gripper_printer_head()
        evidence = {
            "head_present": head is not None,
            "printer_head_id": (
                str(getattr(head, "printer_head_id", "") or "")
                if head is not None
                else None
            ),
            "stock_id": str(head.get_stock_id()) if head is not None else None,
            "volume_uL": (
                float(head.get_current_volume())
                if head is not None and head.get_current_volume() is not None
                else None
            ),
        }
        return (
            evidence["head_present"]
            and bool(evidence["printer_head_id"])
            and evidence["volume_uL"] is not None
            and evidence["volume_uL"] > 0,
            evidence,
        )

    return evaluate_assertion(
        "execution.rack_head_associated",
        "head_staged",
        ("model", "ui"),
        inspect,
    )


def calibration_assertion(
    context: Any,
    *,
    expected_volume_nL: float,
    expected_pulse_width_us: int,
    expected_pressure_psi: float,
) -> AssertionResult:
    def inspect() -> tuple[bool, Mapping[str, Any]]:
        plan = context.experiment_model.get_execution_plan_snapshot()
        stock = plan.stocks[0]
        machine_model = context.model.machine_model
        evidence = {
            "record_id": stock.calibration_record_key,
            "effective_volume_nL": float(stock.effective_volume_nL),
            "printing_mode": str(stock.printing_mode),
            "pulse_width_us": int(machine_model.get_print_pulse_width()),
            "target_pressure_psi": float(
                machine_model.get_target_print_pressure()
            ),
        }
        return (
            bool(evidence["record_id"])
            and abs(evidence["effective_volume_nL"] - expected_volume_nL) < 1e-6
            and evidence["printing_mode"] == "droplet"
            and evidence["pulse_width_us"] == int(expected_pulse_width_us)
            and abs(evidence["target_pressure_psi"] - expected_pressure_psi) < 0.01,
            evidence,
        )

    return evaluate_assertion(
        "execution.applied_calibration_valid",
        "calibrated",
        ("model", "simulator", "persistence"),
        inspect,
    )


def terminal_execution_assertion(
    context: Any,
    *,
    completed_wells: list[str],
    expected_well_ids: tuple[str, ...],
) -> AssertionResult:
    def inspect() -> tuple[bool, Mapping[str, Any]]:
        from ExecutionResumeStore import load_execution_resume

        plan = context.experiment_model.get_execution_plan_snapshot()
        resume = load_execution_resume(context.experiment_model.execution_resume_file_path)
        expected = list(expected_well_ids)
        observed = [well for well in completed_wells if well in set(expected)]
        evidence = {
            "plan_id": str(plan.plan_id),
            "plan_revision": int(plan.plan_revision),
            "plan_state": str(plan.state.value),
            "expected_completion_count": len(expected),
            "observed_completion_count": len(observed),
            "observed_well_ids": observed,
            "queue_drained": bool(context.machine.check_if_all_completed()),
            "checkpoint_state": str(resume.state),
            "checkpoint_intent_count": len(resume.intents),
            "unexpected_dialog_count": len(context.unexpected_dialogs),
            "error_count": len(context.errors),
        }
        return (
            evidence["plan_state"] == "completed"
            and observed == expected
            and evidence["queue_drained"]
            and evidence["checkpoint_state"] == "clean"
            and evidence["checkpoint_intent_count"] == 0
            and evidence["unexpected_dialog_count"] == 0
            and evidence["error_count"] == 0,
            evidence,
        )

    return evaluate_assertion(
        "execution.terminal_bundle_valid",
        "terminal",
        ("controller", "model", "simulator", "persistence"),
        inspect,
    )


def regression_evidence_assertions(
    *,
    expected_well_ids: tuple[str, ...],
    completed_well_ids: tuple[str, ...],
    snapshot: Mapping[str, Any],
) -> tuple[AssertionResult, ...]:
    """Evaluate reusable completion, durability, queue, and UI evidence."""

    expected_count = len(expected_well_ids)
    observer = snapshot["observer"]
    lifecycle = observer.get("lifecycle", {})
    begins = list(lifecycle.get("begins") or ())
    attachments = list(lifecycle.get("attachments") or ())
    completions = list(lifecycle.get("completions") or ())
    begin_ids = [row.get("intent_id") for row in begins]
    attach_ids = [row.get("intent_id") for row in attachments]
    progress = observer.get("progress_snapshot", {})
    authoritative_io = snapshot["authoritative_io"]
    durability_ok = (
        len(begins) == len(attachments) == len(completions) == expected_count
        and len(set(begin_ids)) == expected_count
        and Counter(attach_ids) == Counter(begin_ids)
        and Counter(completions) == Counter(begin_ids)
        and not lifecycle.get("discard_batches")
        and progress.get("mode_counts")
        == {"full_rebuild": 0, "cached_update": expected_count}
        and authoritative_io["resume_save_fsync_count"] == expected_count * 3
        and authoritative_io["resume_save_replace_count"] == expected_count * 3
        and observer.get("restored") is True
        and snapshot.get("calibration_contract", {}).get("valid") is True
    )
    responsiveness = snapshot["responsiveness"]
    phase_values = responsiveness.get("phase_timings", {}).get(
        "duration_by_name_ms", {}
    )
    required_phase_counts = {
        name: phase_values.get(name, {}).get("count", 0)
        for name in (
            "persistence.write_progress",
            "persistence.complete_intent",
            "controller.well_completion",
        )
    }
    metrics_ok = (
        responsiveness.get("scheduling_lateness_ms", {}).get("count", 0) > 0
        and responsiveness.get("event_loop_gap_ms", {}).get("count", 0) > 0
        and all(count == expected_count for count in required_phase_counts.values())
        and responsiveness.get("shutdown")
        == {"timer_active": False, "observer_thread_alive": False}
    )
    injected = snapshot["injected_stall_assessment"]

    def result(
        assertion_id: str,
        passed: bool,
        evidence: Mapping[str, Any],
        sources: tuple[str, ...],
    ) -> AssertionResult:
        return AssertionResult(
            assertion_id=assertion_id,
            checkpoint="terminal",
            decision="pass" if passed else "fail",
            observable_sources=sources,
            evidence=dict(evidence),
            message=(
                None
                if passed
                else "regression evidence did not satisfy the contract"
            ),
        )

    return (
        result(
            "execution.expected_completions",
            completed_well_ids == expected_well_ids,
            {
                "expected_count": expected_count,
                "observed_count": len(completed_well_ids),
                "completed_well_ids": list(completed_well_ids),
            },
            ("ui", "model"),
        ),
        result(
            "execution.no_queue_starvation",
            int(snapshot["queue"].get("unexpected_starvation_count", 0)) == 0,
            snapshot["queue"],
            ("simulator", "controller"),
        ),
        result(
            "execution.intent_durability_exact",
            durability_ok,
            {
                "begin_count": len(begins),
                "attachment_count": len(attachments),
                "completion_count": len(completions),
                "progress_snapshot": progress,
                "authoritative_io": authoritative_io,
                "observer_restored": observer.get("restored"),
                "calibration_contract": snapshot.get("calibration_contract", {}),
            },
            ("model", "persistence"),
        ),
        result(
            "ui.injected_stall_detected",
            injected.get("decision") in {"not_requested", "detected"},
            injected,
            ("ui", "harness"),
        ),
        result(
            "ui.responsiveness_metrics_present",
            metrics_ok,
            {
                "event_loop_gap_ms": responsiveness.get("event_loop_gap_ms"),
                "scheduling_lateness_ms": responsiveness.get(
                    "scheduling_lateness_ms"
                ),
                "required_phase_counts": required_phase_counts,
                "shutdown": responsiveness.get("shutdown"),
            },
            ("ui", "harness"),
        ),
    )


def sustained_evidence_assertions(
    *, snapshot: Mapping[str, Any], expected_count: int
) -> tuple[AssertionResult, ...]:
    """Evaluate the frozen stress thresholds without turning warnings into failures."""

    responsiveness = dict(snapshot.get("responsiveness") or {})
    event_gap = dict(responsiveness.get("event_loop_gap_ms") or {})
    scheduling = dict(responsiveness.get("scheduling_lateness_ms") or {})
    pressure = dict(
        (responsiveness.get("pressure_render_assessment") or {}).get(
            "active_render_interval_ms"
        ) or {}
    )
    metrics_present = (
        event_gap.get("count", 0) > 0
        and scheduling.get("count", 0) > 0
        and pressure.get("count", 0) > 0
        and responsiveness.get("shutdown")
        == {"timer_active": False, "observer_thread_alive": False}
    )
    fail_reasons = []
    if float(event_gap.get("maximum", 0.0)) > 1000.0:
        fail_reasons.append("event_loop_gap_over_1000_ms")
    if float(pressure.get("maximum", 0.0)) > 1000.0:
        fail_reasons.append("pressure_render_gap_over_1000_ms")
    if float(scheduling.get("p99", 0.0)) > 250.0:
        fail_reasons.append("scheduling_p99_over_250_ms")
    warning_reasons = []
    if not fail_reasons and float(event_gap.get("maximum", 0.0)) > 250.0:
        warning_reasons.append("event_loop_gap_over_250_ms")
    if not fail_reasons and float(pressure.get("maximum", 0.0)) > 250.0:
        warning_reasons.append("pressure_render_gap_over_250_ms")
    assessment = {
        "decision": "fail" if fail_reasons else "warning" if warning_reasons else "pass",
        "failure_reasons": fail_reasons,
        "warning_reasons": warning_reasons,
        "event_loop_gap_ms": event_gap,
        "scheduling_lateness_ms": scheduling,
        "pressure_render_interval_ms": pressure,
        "expected_completion_count": int(expected_count),
    }
    resources = dict(snapshot.get("resources") or {})
    resource_values = dict(resources.get("values") or {})
    growth = resource_values.get("rss_growth_bytes")
    ratio = resource_values.get("rss_growth_ratio")
    resource_warning = bool(
        growth is not None and ratio is not None
        and int(growth) > 100 * 1024 * 1024 and float(ratio) > 1.25
    )
    resource_evidence = {
        **resources,
        "growth_assessment": {
            "decision": "warning" if resource_warning else "pass",
            "threshold_bytes": 100 * 1024 * 1024,
            "threshold_ratio": 1.25,
        },
    }

    def result(assertion_id: str, passed: bool, evidence: Mapping[str, Any], sources: tuple[str, ...]) -> AssertionResult:
        return AssertionResult(
            assertion_id, "terminal", "pass" if passed else "fail", sources,
            dict(evidence), None if passed else "sustained evidence did not satisfy the frozen contract"
        )

    injected = dict(snapshot.get("injected_stall_assessment") or {})
    return (
        result("ui.injected_stall_detected", injected.get("decision") in {"not_requested", "detected"}, injected, ("ui", "harness")),
        result("ui.responsiveness_metrics_present", metrics_present, {**assessment, "shutdown": responsiveness.get("shutdown")}, ("ui", "harness")),
        result("ui.sustained_responsiveness_acceptable", metrics_present and not fail_reasons, assessment, ("ui", "harness")),
        result("resources.metrics_present", resources.get("status") in {"measured", "partial"} and resource_values.get("sample_count", 0) > 0, resource_evidence, ("harness",)),
    )


def synthetic_calibration_contract(
    fixture: Mapping[str, Any],
    action_results: list[Mapping[str, Any]],
    *,
    expected_pulse_widths_us: tuple[int, ...] = (),
) -> dict[str, Any]:
    """Project the selected normal-UI synthetic result without mutation."""

    def action_evidence(action_id: str) -> list[dict[str, Any]]:
        return [
            dict(row.get("evidence") or {})
            for row in action_results if row.get("action_id") == action_id
        ]

    selected_rows = action_evidence("calibration.select_via_ui")
    applied_rows = action_evidence("calibration.apply_via_ui")
    stocks = list(fixture.get("stocks") or [fixture["stock"]])
    from tools.sil.ejection_response import PulseAwareSyntheticEjectionModelV1
    model = PulseAwareSyntheticEjectionModelV1()
    contracts = []
    for index, stock in enumerate(stocks):
        selected = selected_rows[index] if index < len(selected_rows) else {}
        applied = applied_rows[index] if index < len(applied_rows) else {}
        preview = dict(applied.get("preview") or {}).get("payload") or {}
        head = stock.get("printer_head") or fixture.get("printer_head") or {}
        expected_pulse = (
            int(expected_pulse_widths_us[index])
            if index < len(expected_pulse_widths_us)
            else int(head["print_pulse_width_us"])
        )
        expected_measured = model.predict_volume_nl(
            stock["printing_mode"], expected_pulse
        )
        evidence = {
            "stock_id": (
                f"{stock['factor_name']}_{float(stock['concentration']):.2f}_{stock['units']}"
                if all(key in stock for key in ("factor_name", "concentration", "units"))
                else None
            ),
            "prepared_volume_nL": stock["prepared_droplet_volume_nL"],
            "fixture_design_volume_nL": stock["droplet_volume_nL"],
            "fixture_print_pulse_width_us": head["print_pulse_width_us"],
            "expected_synthetic_measured_volume_nL": expected_measured,
            "selected_source_volume_nL": selected.get("source_volume_nL"),
            "selected_measured_volume_nL": selected.get("mean_nL"),
            "selected_pulse_width_us": selected.get("pw_us"),
            "selected_pressure_psi": selected.get("pressure_psi"),
            "applied_volume_nL": preview.get("new_droplet_nL"),
        }
        evidence["valid"] = (
            float(selected.get("source_volume_nL", -1)) == float(stock["prepared_droplet_volume_nL"])
            and int(selected.get("pw_us", -1)) == expected_pulse
            and abs(float(selected.get("pressure_psi", -1)) - float(head["print_pressure_psi"])) <= 0.001
            and float(selected.get("mean_nL", -1)) == expected_measured
            and float(preview.get("new_droplet_nL", -1)) == expected_measured
        )
        contracts.append(evidence)
    if len(contracts) == 1:
        return contracts[0]
    return {"valid": len(contracts) == len(stocks) and all(row["valid"] for row in contracts),
            "stocks": contracts}


def cleanup_assertion(teardown: Mapping[str, Any]) -> AssertionResult:
    def inspect() -> tuple[bool, Mapping[str, Any]]:
        evidence = dict(teardown.get("evidence") or {})
        return (
            bool(evidence.get("close_succeeded"))
            and not bool(evidence.get("session_lock_present")),
            evidence,
        )

    return evaluate_assertion(
        "artifacts.cleanup_complete",
        "closed",
        ("harness", "session"),
        inspect,
    )


def completed_terminal_reload_assertion(
    *,
    before: Any,
    after: Any,
    first_close: Mapping[str, Any],
    second_launch: Mapping[str, Any],
    loader: Mapping[str, Any],
    directory_comparisons: Mapping[str, Mapping[str, Any]],
) -> AssertionResult:
    """Prove a completed bundle survives a fresh read-only UI session exactly."""

    def inspect() -> tuple[bool, Mapping[str, Any]]:
        close = dict(first_close)
        launch = dict(second_launch)
        loaded = dict(loader)
        comparisons = {
            str(name): dict(value)
            for name, value in directory_comparisons.items()
        }
        checks = {
            "first_session_closed": bool(close.get("close_succeeded"))
            and close.get("recorder", {}).get("status") == "closed"
            and not bool(close.get("session_lock_present"))
            and bool(close.get("root_retained")),
            "fresh_application_identity": str(close.get("application_session_id"))
            != str(launch.get("application_session_id")),
            "retained_session_identity": str(close.get("session_id"))
            == str(launch.get("session_id")),
            "real_components_reconstructed": launch.get("component_type")
            == "ApplicationComponents"
            and launch.get("view_type") == "MainWindow",
            "simulator_reconstructed": launch.get("machine_type")
            == "SimulatedMachine"
            and not bool(launch.get("hardware_access_allowed")),
            "ui_completed_read_only": all(
                bool(value) for value in dict(loaded.get("checks") or {}).values()
            )
            and not bool(loaded.get("activation_performed")),
            "plan_identity_exact": before.plan_id == after.plan_id
            and before.plan_revision == after.plan_revision,
            "completed_state_exact": before.plan_state == after.plan_state
            == "completed"
            and before.eligibility_status == after.eligibility_status
            == "analysis_only",
            "design_exact": before.design_json == after.design_json
            and before.design_sha256 == after.design_sha256
            and before.plan_design_sha256 == after.plan_design_sha256,
            "plan_exact": before.plan_json == after.plan_json,
            "well_assignments_exact": before.plan_well_ids == after.plan_well_ids
            and before.plan_assignments == after.plan_assignments,
            "runtime_projection_not_activated": not after.runtime_assignments,
            "revision_history_exact": before.history_json == after.history_json,
            "progress_exact": before.progress_plan_id == after.progress_plan_id
            and before.progress_plan_revision == after.progress_plan_revision
            and before.progress_targets == after.progress_targets
            and before.total_added_droplets == after.total_added_droplets
            and before.completed_well_ids == after.completed_well_ids,
            "resume_terminal_clean": before.resume_present == after.resume_present
            and before.resume_state == after.resume_state
            and before.resume_plan_id == after.resume_plan_id
            and before.resume_plan_revision == after.resume_plan_revision
            and before.resume_intent_count == after.resume_intent_count == 0,
            "calibration_linkage_exact": before.calibration_present
            == after.calibration_present
            and before.calibration_record_count == after.calibration_record_count
            and before.manual_refuel_check_count
            == after.manual_refuel_check_count,
            "reloaded_runtime_inactive": not after.runtime_active,
            "authoritative_hashes_exact": before.core_file_hashes
            == after.core_file_hashes,
            "files_unchanged_on_close": bool(
                comparisons.get("after_close", {})
                .get("checks", {})
                .get("files_byte_identical")
            ),
            "files_unchanged_on_reload": bool(
                comparisons.get("after_reload", {})
                .get("checks", {})
                .get("files_byte_identical")
            ),
        }
        evidence = {
            "checks": checks,
            "failed_checks": [name for name, passed in checks.items() if not passed],
            "before": {
                "plan_id": before.plan_id,
                "plan_revision": before.plan_revision,
                "plan_state": before.plan_state,
                "design_sha256": before.design_sha256,
                "core_file_hashes": before.core_file_hashes,
                "progress_targets": dict(before.progress_targets),
                "total_added_droplets": before.total_added_droplets,
                "completed_well_ids": list(before.completed_well_ids),
                "calibration_record_count": before.calibration_record_count,
            },
            "after": {
                "plan_id": after.plan_id,
                "plan_revision": after.plan_revision,
                "plan_state": after.plan_state,
                "design_sha256": after.design_sha256,
                "core_file_hashes": after.core_file_hashes,
                "progress_targets": dict(after.progress_targets),
                "total_added_droplets": after.total_added_droplets,
                "completed_well_ids": list(after.completed_well_ids),
                "calibration_record_count": after.calibration_record_count,
            },
            "first_close": close,
            "second_launch": launch,
            "loader": loaded,
            "directory_comparisons": comparisons,
        }
        return all(checks.values()), evidence

    return evaluate_assertion(
        "execution.completed_terminal_reload_exact",
        "terminal_reloaded",
        ("ui", "model", "persistence", "session", "simulator"),
        inspect,
    )


def real_application_assertion(context: Any) -> AssertionResult:
    def inspect() -> tuple[bool, Mapping[str, Any]]:
        evidence = {
            "component_type": type(context.components).__name__,
            "view_type": type(context.view).__name__,
            "view_visible": bool(context.view.isVisible()),
        }
        return (
            evidence["component_type"] == "ApplicationComponents"
            and evidence["view_type"] == "MainWindow"
            and evidence["view_visible"],
            evidence,
        )

    return evaluate_assertion(
        "ui.real_app_constructed",
        "launched",
        ("ui", "session"),
        inspect,
    )


def exact_action_sequence_assertion(
    context: Any,
    *,
    expectation: ActionSequenceExpectation,
    start_index: int,
    end_index: int | None,
    assertion_id: str,
    checkpoint: str,
    evidence_surface: str | None = None,
) -> AssertionResult:
    """Validate one explicit ledger window without subsequence matching."""

    def inspect() -> tuple[bool, Mapping[str, Any]]:
        rows = list(context.action_results[start_index:end_index])
        all_observed = [str(row.get("action_id")) for row in rows]
        all_surfaces = [str(row.get("interaction_surface")) for row in rows]
        all_statuses = [str(row.get("status")) for row in rows]
        required = list(expectation.action_ids)
        required_surfaces = list(expectation.interaction_surfaces)
        selected_rows = (
            [row for row in rows if row.get("interaction_surface") == evidence_surface]
            if evidence_surface is not None
            else rows
        )
        observed = [str(row.get("action_id")) for row in selected_rows]
        surfaces = [str(row.get("interaction_surface")) for row in selected_rows]
        statuses = [str(row.get("status")) for row in selected_rows]
        reported_required = [
            action_id
            for action_id, surface in zip(required, required_surfaces)
            if evidence_surface is None or surface == evidence_surface
        ]
        evidence = {
            "required_action_ids": reported_required,
            "observed_action_ids": observed,
            "interaction_surfaces": surfaces,
            "statuses": statuses,
        }
        return (
            all_observed == required
            and all_surfaces == required_surfaces
            and all_statuses == ["pass"] * len(required),
            evidence,
        )

    return evaluate_assertion(
        assertion_id,
        checkpoint,
        ("ui", "action_ledger"),
        inspect,
    )


def editor_create_finalize_assertion(
    context: Any,
    *,
    action_start: int = 0,
    action_end: int | None = None,
    optimization_action_ids: tuple[str, ...] = (
        "editor.optimize_generate_via_ui",
    ),
    pre_configure_action_ids: tuple[str, ...] = (),
    capture_editor_milestones: bool = True,
) -> AssertionResult:
    action_ids = (
        "editor.open_via_ui",
        *(("artifact.capture_milestone",) if capture_editor_milestones else ()),
        "editor.new_experiment_via_ui",
        *pre_configure_action_ids,
        "editor.configure_design_via_ui",
        *optimization_action_ids,
        *(("artifact.capture_milestone",) if capture_editor_milestones else ()),
        "editor.finish_via_ui",
    )
    return exact_action_sequence_assertion(
        context,
        expectation=ActionSequenceExpectation(
            action_ids,
            tuple(
                "harness" if action_id == "artifact.capture_milestone" else "ui"
                for action_id in action_ids
            ),
        ),
        start_index=action_start,
        end_index=action_end,
        assertion_id="experiment.editor_create_finalize",
        checkpoint="finalized",
        evidence_surface="ui",
    )


def editor_create_rejected_assertion(
    context: Any,
    *,
    action_start: int = 0,
    action_end: int | None = None,
    generated_before_finalize: bool,
) -> AssertionResult:
    action_ids = (
        "editor.open_via_ui",
        "artifact.capture_milestone",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        *(
            (
                "editor.optimize_generate_via_ui",
                "artifact.capture_milestone",
            )
            if generated_before_finalize
            else ()
        ),
        "artifact.capture_milestone",
        "editor.finish_via_ui",
    )
    return exact_action_sequence_assertion(
        context,
        expectation=ActionSequenceExpectation(
            action_ids,
            tuple(
                "harness" if action_id == "artifact.capture_milestone" else "ui"
                for action_id in action_ids
            ),
        ),
        start_index=action_start,
        end_index=action_end,
        assertion_id="experiment.editor_create_rejected",
        checkpoint="finalization_rejected",
        evidence_surface="ui",
    )


def experiment_finalization_rejected_no_mutation_assertion(
    context: Any,
    *,
    case: Mapping[str, Any],
    driver_evidence: Mapping[str, Any],
) -> AssertionResult:
    """Prove a real Finalize rejection left no authoritative execution state."""

    expected = dict(case["expected"])
    experiment = dict(case["experiment"])
    configured = dict(driver_evidence.get("configured") or {})
    generated = dict(driver_evidence.get("generated") or {})
    rejection = dict(driver_evidence.get("finalization_rejection") or {})
    warning = dict(rejection.get("warning") or {})
    before = dict(rejection.get("before") or {})
    after = dict(rejection.get("after") or {})
    before_artifacts = dict(before.get("execution_artifacts") or {})
    after_artifacts = dict(after.get("execution_artifacts") or {})
    expected_artifact_names = {
        "execution_plan.json",
        "execution_plan_revisions",
        "progress.json",
        "key.csv",
        "concentration_key.csv",
        "execution_resume.json",
    }
    required_absent_names = expected_artifact_names - {"progress.json"}
    combined_warning = " ".join(
        (str(warning.get("text") or ""), str(rejection.get("status") or ""))
    ).casefold()
    zero_dispatch_keys = (
        "intent_begin_count",
        "intent_attachment_count",
        "intent_completion_count",
        "simulator_dispense_count",
        "simulator_command_event_count",
    )
    expected_wells = list(experiment["selected_well_ids"])
    expected_generated = expected["terminal"] == "capacity_rejected"
    checks = {
        "terminal_exact": (
            driver_evidence.get("terminal") == expected["terminal"]
            and rejection.get("expected_terminal") == expected["terminal"]
            and rejection.get("observed_outcome") == "rejected"
        ),
        "configured_controls_exact": (
            configured.get("declared_well_ids") == expected_wells
            and configured.get("selected_well_ids") == expected_wells
            and configured.get("excluded_well_ids")
            == list(experiment.get("excluded_well_ids") or [])
            and configured.get("random_seed") == experiment["random_seed"]
            and configured.get("reagent_count") == len(case["reagents"])
        ),
        "generated_boundary_exact": (
            bool(generated) == expected_generated
            and (
                not expected_generated
                or generated.get("reaction_count") == expected["reaction_count"]
            )
        ),
        "reaction_count_exact": rejection.get("reaction_count_after")
        == expected["reaction_count"],
        "warning_title_exact": warning.get("title") == expected["dialog_title"],
        "warning_fragments_exact": all(
            str(fragment).casefold() in combined_warning
            for fragment in expected.get("message_fragments", ())
        ),
        "warning_interaction_exact": (
            warning.get("entered") is True
            and warning.get("dismissed") is True
            and warning.get("screenshot_captured") is True
            and rejection.get("activation_count") == 1
            and rejection.get("action_label") == "Finalize Design"
        ),
        "dialog_remained_unaccepted": (
            rejection.get("dialog_before", {}).get("visible") is True
            and rejection.get("dialog_after", {}).get("visible") is True
            and rejection.get("dialog_after", {}).get("apply_requested") is False
            and rejection.get("dialog_after", {}).get("result") != 1
        ),
        "dirty_boundary_exact": (
            rejection.get("dialog_before", {}).get("dirty")
            == (not expected_generated)
        ),
        "directory_byte_identical": (
            rejection.get("directory_unchanged") is True
            and before.get("directory_inventory")
            == after.get("directory_inventory")
        ),
        "execution_artifact_names_exact": (
            set(before_artifacts) == expected_artifact_names
            and set(after_artifacts) == expected_artifact_names
        ),
        "required_execution_artifacts_absent": (
            rejection.get("required_execution_artifacts_absent") is True
            and all(
                not before_artifacts.get(name, {}).get("exists")
                and not after_artifacts.get(name, {}).get("exists")
                for name in required_absent_names
            )
        ),
        "draft_progress_unchanged": (
            rejection.get("draft_progress_unchanged") is True
            and before_artifacts.get("progress.json")
            == after_artifacts.get("progress.json")
        ),
        "execution_artifacts_unchanged": (
            rejection.get("authoritative_execution_artifacts_unchanged") is True
            and before_artifacts == after_artifacts
        ),
        "runtime_inactive": (
            before.get("runtime_active") is False
            and after.get("runtime_active") is False
            and before.get("runtime_assignments") == {}
            and after.get("runtime_assignments") == {}
        ),
        "controller_idle": (
            before.get("array_state") == after.get("array_state") == "idle"
        ),
        "zero_dispatch": all(
            before.get(key) == after.get(key) == 0 for key in zero_dispatch_keys
        ),
        "driver_safe": rejection.get("safe") is True,
    }
    if expected["terminal"] == "capacity_rejected":
        checks["capacity_exact"] = (
            expected.get("capacity_required") == expected["reaction_count"]
            and expected.get("capacity_available") == len(expected_wells)
        )
    evidence = {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "case_id": case["case_id"],
        "terminal": expected["terminal"],
        "expected": expected,
        "configured": configured,
        "generated": generated,
        "rejection": rejection,
    }
    return evaluate_assertion(
        "experiment.finalization_rejected_no_mutation",
        "finalization_rejected",
        ("ui", "controller", "model", "persistence", "simulator"),
        lambda: (not evidence["failed_checks"], evidence),
    )


def editor_prepared_bundle_assertions(
    context: Any,
    *,
    expected_well_ids: tuple[str, ...],
) -> tuple[AssertionResult, AssertionResult]:
    from tools.virtual_workflows.authoritative_evidence import (
        capture_authoritative_bundle,
    )

    snapshot = capture_authoritative_bundle(context)
    return _prepared_bundle_results(snapshot, expected_well_ids=expected_well_ids)


def experiment_design_case_oracle_assertion(
    context: Any,
    *,
    case: Mapping[str, Any],
    driver_evidence: Mapping[str, Any],
) -> tuple[AssertionResult, Any]:
    """Compare a PREPARED authoritative bundle with independent literal truth."""

    from tools.virtual_workflows.authoritative_evidence import (
        capture_authoritative_bundle,
        experiment_design_projection,
    )

    snapshot = capture_authoritative_bundle(context)
    projection = experiment_design_projection(snapshot)
    expected = dict(case["expected"])
    experiment = dict(case["experiment"])
    expected_stocks = {
        str(row["stock_id"]): dict(row) for row in expected["stocks"]
    }
    observed_stocks = {
        str(row["stock_id"]): dict(row) for row in projection["stocks"]
    }
    stock_checks = {
        stock_id: (
            observed_stocks.get(stock_id, {}).get("reagent_name")
            == row["reagent_name"]
            and observed_stocks.get(stock_id, {}).get("units") == row["units"]
            and observed_stocks.get(stock_id, {}).get("printing_mode")
            == row["printing_mode"]
            and Decimal(
                observed_stocks.get(stock_id, {}).get("concentration", "NaN")
            )
            == Decimal(row["concentration"])
        )
        for stock_id, row in expected_stocks.items()
    }
    expected_assignments = {
        str(row["well_id"]): str(row["reaction_id"])
        for row in expected["assignments"]
    }
    observed_assignments = {
        str(row["well_id"]): str(row["reaction_id"])
        for row in projection["assignments"]
    }
    expected_counts = sorted(
        (
            str(row["stock_id"]),
            str(row["well_id"]),
            int(row["target_droplets"]),
        )
        for row in expected["stock_well_counts"]
    )
    observed_counts = sorted(
        (
            str(row["stock_id"]),
            str(row["well_id"]),
            int(row["target_droplets"]),
        )
        for row in projection["stock_well_counts"]
    )
    reaction_targets = {
        str(row["reaction_id"]): {
            str(item["reagent"]): Decimal(str(item["target"]))
            for item in row["targets"]
        }
        for row in expected["reactions"]
    }
    observed_concentrations = projection["concentration_rows"]
    concentration_checks: dict[str, bool] = {}
    for well_id, reaction_id in expected_assignments.items():
        row = dict(observed_concentrations.get(well_id) or {})
        for reagent, target in reaction_targets[reaction_id].items():
            total = sum(
                Decimal(str(value or "0"))
                for stock_id, value in row.items()
                if stock_id.startswith(f"{reagent}_")
            )
            concentration_checks[f"{well_id}:{reagent}"] = total == target
    expected_reaction_rows = {
        str(row["reaction_id"]): dict(row) for row in expected["reactions"]
    }

    def canonical_decimal(value: Decimal) -> str:
        if value == 0:
            return "0"
        return format(value.normalize(), "f")

    observed_reaction_multiset: list[dict[str, Any]] = []
    for well_id, reaction_id in sorted(observed_assignments.items()):
        expected_reaction = expected_reaction_rows.get(reaction_id)
        if expected_reaction is None:
            continue
        concentration_row = dict(observed_concentrations.get(well_id) or {})
        observed_reaction_multiset.append(
            {
                "replicate": int(expected_reaction["replicate"]),
                "targets": [
                    {
                        "reagent": str(target["reagent"]),
                        "target": canonical_decimal(
                            sum(
                                Decimal(str(value or "0"))
                                for stock_id, value in concentration_row.items()
                                if stock_id.startswith(
                                    f"{target['reagent']}_"
                                )
                            )
                        ),
                    }
                    for target in expected_reaction["targets"]
                ],
            }
        )
    def canonical_json(value: Any) -> str:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    observed_reaction_multiset.sort(key=canonical_json)
    observed_reaction_multiset_sha256 = hashlib.sha256(
        canonical_json(observed_reaction_multiset).encode("utf-8")
    ).hexdigest()
    observed_assignment_rows = [
        {"well_id": well_id, "reaction_id": reaction_id}
        for well_id, reaction_id in sorted(observed_assignments.items())
    ]
    observed_assignment_sha256 = hashlib.sha256(
        canonical_json(observed_assignment_rows).encode("utf-8")
    ).hexdigest()
    configured = dict(driver_evidence.get("configured") or {})
    picker_evidence = dict(configured.get("well_picker") or {})
    exclusion_precondition = dict(
        configured.get("exclusion_precondition") or {}
    )
    generated = dict(driver_evidence.get("generated") or {})
    expected_attempts = list(case.get("optimization_attempts") or [])
    observed_attempts = list(driver_evidence.get("optimization_attempts") or [])

    def optimization_attempt_matches(
        expected_attempt: Mapping[str, Any],
        observed_attempt: Mapping[str, Any],
    ) -> bool:
        expected_outcome = str(expected_attempt.get("expected_outcome") or "")
        if (
            bool(observed_attempt.get("allow_two_stock_solutions"))
            != bool(expected_attempt.get("allow_two_stock_solutions"))
            or str(observed_attempt.get("observed_outcome") or "")
            != expected_outcome
        ):
            return False
        if expected_outcome == "generated":
            return observed_attempt.get("dirty_after") is False
        warning = dict(observed_attempt.get("warning") or {})
        combined = " ".join(
            (
                str(warning.get("text") or ""),
                str(observed_attempt.get("status") or ""),
            )
        ).casefold()
        return (
            warning.get("title") == expected_attempt.get("expected_dialog_title")
            and bool(warning.get("entered"))
            and bool(warning.get("dismissed"))
            and all(
                str(fragment).casefold() in combined
                for fragment in expected_attempt.get(
                    "expected_message_fragments", ()
                )
            )
            and observed_attempt.get("dirty_after") is True
            and observed_attempt.get("dialog_open_after") is True
            and observed_attempt.get(
                "authoritative_execution_artifacts_unchanged"
            )
            is True
            and observed_attempt.get("execution_artifacts_before")
            == observed_attempt.get("execution_artifacts_after")
        )

    optimization_attempt_checks = [
        optimization_attempt_matches(expected_attempt, observed_attempt)
        for expected_attempt, observed_attempt in zip(
            expected_attempts, observed_attempts
        )
    ]
    expected_editor_stock_rows = len(expected_stocks) + int(
        not any(stock.get("role") == "fill" for stock in expected_stocks.values())
    )
    expected_excluded_wells = sorted(experiment.get("excluded_well_ids") or [])
    expected_declared_wells = list(experiment["selected_well_ids"])
    expected_printable_wells = [
        well_id
        for well_id in expected_declared_wells
        if well_id not in set(expected_excluded_wells)
    ]
    observed_excluded_wells = sorted(
        str(getattr(value, "well_id", value))
        for value in set(
            getattr(context.model.well_plate, "excluded_wells", set()) or set()
        )
    )
    metadata = snapshot.metadata
    checks = {
        "bundle_valid": snapshot.bundle_valid,
        "plan_prepared": snapshot.plan_state == "prepared",
        "ready_to_start": snapshot.eligibility_status == "ready_to_start",
        "runtime_inactive": not snapshot.runtime_active,
        "zero_progress": snapshot.total_added_droplets == 0,
        "resume_absent": not snapshot.resume_present,
        "case_terminal_prepared": expected["terminal"] == "prepared",
        "reaction_count_exact": len(observed_assignments)
        == int(expected["reaction_count"]),
        "stock_ids_exact": set(observed_stocks) == set(expected_stocks),
        "stock_fields_exact": all(stock_checks.values()),
        "assignments_exact": observed_assignments == expected_assignments,
        "reaction_multiset_hash_exact": observed_reaction_multiset_sha256
        == expected["reaction_multiset_sha256"],
        "assignment_hash_exact": observed_assignment_sha256
        == expected["assignment_sha256"],
        "excluded_state_exact": observed_excluded_wells
        == expected_excluded_wells,
        "excluded_wells_unassigned": not (
            set(observed_assignments) & set(expected_excluded_wells)
        ),
        "assigned_wells_printable": set(observed_assignments).issubset(
            set(expected_printable_wells)
        ),
        "stock_well_counts_exact": observed_counts == expected_counts,
        "concentrations_exact": all(concentration_checks.values()),
        "key_wells_exact": list(projection["key_rows"])
        == list(expected_assignments),
        "metadata_name_exact": metadata.get("name") == experiment["name"],
        "metadata_plate_exact": metadata.get("plate_name")
        == experiment["plate_name"],
        "metadata_replicates_exact": int(metadata.get("replicates", -1))
        == int(experiment["replicates"]),
        "metadata_randomize_exact": bool(
            metadata.get("randomize_assignments")
        )
        == bool(experiment["randomize_assignments"]),
        "metadata_seed_exact": metadata.get("random_seed")
        == experiment["random_seed"],
        "configured_controls_exact": (
            configured.get("declared_well_ids") == expected_declared_wells
            and configured.get("selected_well_ids") == expected_printable_wells
            and configured.get("excluded_well_ids") == expected_excluded_wells
            and picker_evidence.get("disabled_well_ids")
            == expected_excluded_wells
            and picker_evidence.get("rejected_disabled_well_ids")
            == expected_excluded_wells
            and picker_evidence.get("selected_well_ids")
            == expected_printable_wells
            and exclusion_precondition.get("before") == []
            and exclusion_precondition.get("applied")
            == expected_excluded_wells
            and exclusion_precondition.get("scenario_local") is True
            and configured.get("random_seed") == experiment["random_seed"]
            and configured.get("reagent_count") == len(case["reagents"])
            and bool(configured.get("allow_two_stock_solutions"))
            == bool(expected_attempts[0]["allow_two_stock_solutions"])
        ),
        "optimization_attempts_exact": (
            len(observed_attempts) == len(expected_attempts)
            and len(optimization_attempt_checks) == len(expected_attempts)
            and all(optimization_attempt_checks)
        ),
        "generated_evidence_exact": (
            generated.get("reaction_count") == expected["reaction_count"]
            and generated.get("stock_row_count") == expected_editor_stock_rows
            and bool(generated.get("allow_two_stock_solutions"))
            == bool(expected_attempts[-1]["allow_two_stock_solutions"])
        ),
    }
    evidence = {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "case_id": case["case_id"],
        "expected": expected,
        "observed": projection,
        "stock_checks": stock_checks,
        "concentration_checks": concentration_checks,
        "observed_reaction_multiset": observed_reaction_multiset,
        "observed_reaction_multiset_sha256": observed_reaction_multiset_sha256,
        "observed_assignment_sha256": observed_assignment_sha256,
        "observed_excluded_well_ids": observed_excluded_wells,
        "expected_printable_well_ids": expected_printable_wells,
        "optimization_attempt_checks": optimization_attempt_checks,
        "driver": dict(driver_evidence),
        "expected_editor_stock_row_count": expected_editor_stock_rows,
        "plan_id": snapshot.plan_id,
        "plan_revision": snapshot.plan_revision,
        "experiment_dir": snapshot.experiment_dir,
    }
    return (
        evaluate_assertion(
            "experiment.design_case_oracle_exact",
            "prepared",
            ("ui", "model", "persistence"),
            lambda: (not evidence["failed_checks"], evidence),
        ),
        snapshot,
    )


def experiment_prepared_runtime_reconstructed_assertion(
    context: Any,
    *,
    case: Mapping[str, Any],
    prepared_snapshot: Any,
    loader_evidence: Mapping[str, Any],
) -> AssertionResult:
    """Prove Qt reload reconstructs the exact saved assignments in memory."""

    from tools.virtual_workflows.authoritative_evidence import (
        capture_authoritative_bundle,
        compare_directories,
    )

    reloaded = capture_authoritative_bundle(context)
    expected_assignments = {
        str(row["well_id"]): str(row["reaction_id"])
        for row in case["expected"]["assignments"]
    }
    directory_comparison = compare_directories(
        prepared_snapshot.directory,
        reloaded.directory,
    ).to_dict()
    loaded = dict(loader_evidence)
    checks = {
        "reload_checks_pass": all(dict(loaded.get("checks") or {}).values()),
        "directory_byte_identical": not directory_comparison["changed_paths"],
        "plan_identity_unchanged": (
            reloaded.plan_id,
            reloaded.plan_revision,
        )
        == (prepared_snapshot.plan_id, prepared_snapshot.plan_revision),
        "plan_remains_prepared": reloaded.plan_state == "prepared",
        "eligibility_ready_to_start": reloaded.eligibility_status
        == "ready_to_start",
        "runtime_inactive": not reloaded.runtime_active,
        "resume_absent": not reloaded.resume_present,
        "zero_progress": reloaded.total_added_droplets == 0,
        "reconstructed_assignments_exact": reloaded.assignments
        == expected_assignments,
        "reconstructed_assignments_match_plan": reloaded.assignments
        == reloaded.expected_assignments,
        "prepared_assignments_unchanged": reloaded.assignments
        == prepared_snapshot.assignments,
        "controller_idle": context.controller.get_array_run_state() == "idle",
    }
    evidence = {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "loaded": loaded,
        "reconstructed": reloaded.prepared_evidence(),
        "changed_paths": directory_comparison["changed_paths"],
        "case_id": case["case_id"],
    }
    return evaluate_assertion(
        "experiment.prepared_runtime_reconstructed_exact",
        "reloaded",
        ("ui", "controller", "model", "persistence"),
        lambda: (not evidence["failed_checks"], evidence),
    )


def randomized_joined_design_assertion(
    context: Any,
    *,
    case: Any,
    driver_evidence: Mapping[str, Any],
) -> tuple[AssertionResult, Any]:
    """Join the real randomized editor output to the frozen singleton truth."""

    from tools.virtual_workflows.experiment_design_cases import (
        get_experiment_design_case,
    )
    from tools.virtual_workflows.joined_interaction_cases import (
        validate_source_compatibility,
    )

    source = get_experiment_design_case(case.source.case_id)
    base, snapshot = experiment_design_case_oracle_assertion(
        context,
        case=source.normalized(),
        driver_evidence=driver_evidence,
    )
    counts = capture_count_snapshot(context)
    expected = normalize_stock_well_counts(
        (
            StockWellCount(row.stock_id, row.well_id, row.target_droplets)
            for row in case.oracle("prepared").rows
        ),
        label="joined prepared literal",
    )
    plan = normalize_stock_well_counts(counts["plan_targets"], label="joined prepared plan")
    progress = normalize_stock_well_counts(counts["progress_targets"], label="joined prepared progress")
    runtime = normalize_stock_well_counts(counts["runtime_targets"], label="joined prepared runtime")
    compatibility = validate_source_compatibility(case)
    checks = {
        "source_compatibility_exact": compatibility["complete"] is True,
        "source_design_assertion_passed": base.decision == "pass",
        "plan_revision_one": snapshot.plan_revision == 1,
        "plan_prepared": snapshot.plan_state == "prepared",
        "plan_progress_reference_exact": (
            snapshot.progress_plan_id,
            snapshot.progress_plan_revision,
        ) == (snapshot.plan_id, 1),
        "resume_absent": not snapshot.resume_present,
        "runtime_inactive": not snapshot.runtime_active,
        "zero_progress": snapshot.total_added_droplets == 0,
        "literal_plan_counts_exact": plan == expected,
        "literal_progress_counts_exact": progress == expected,
        "literal_runtime_counts_exact": runtime == expected,
        "assignments_exact": snapshot.assignments
        == {row.well_id: row.reaction_id for row in case.assignments},
    }
    evidence = {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "case_id": case.case_id,
        "source": compatibility,
        "prepared": snapshot.prepared_evidence(),
        "counts": counts,
        "source_oracle": dict(base.evidence),
    }
    return (
        AssertionResult(
            "experiment.randomized_joined_design_exact",
            "prepared_randomized",
            "pass" if not evidence["failed_checks"] else "fail",
            ("ui", "model", "persistence"),
            evidence,
            None if not evidence["failed_checks"] else "randomized joined design was not exact",
        ),
        snapshot,
    )


def optimizer_360_design_assertion(
    context: Any,
    *,
    case: Any,
    driver_evidence: Mapping[str, Any],
) -> tuple[AssertionResult, Any]:
    """Join real editor/optimizer output to standalone literal 360 truth."""

    base, snapshot = experiment_design_case_oracle_assertion(
        context,
        case=case.achieved_design_oracle(),
        driver_evidence=driver_evidence,
    )
    counts = capture_count_snapshot(context)
    expected = normalize_stock_well_counts(
        (
            StockWellCount(row.stock_id, row.well_id, row.target_droplets)
            for row in case.oracle("prepared").rows
        ),
        label="optimizer 360 prepared literal",
    )
    observed = {
        name: normalize_stock_well_counts(
            counts[name], label=f"optimizer 360 prepared {name}"
        )
        for name in ("plan_targets", "progress_targets", "runtime_targets")
    }
    preview_rows = [
        dict(row)
        for rows in context.experiment_model.get_target_preview_map().values()
        for row in rows
    ]
    approximate_targets = sum(
        1
        for row in preview_rows
        if bool(row.get("reachable"))
        and abs(float(row.get("abs_error", 0.0))) > 1e-12
    )
    unreachable_targets = sum(
        1 for row in preview_rows if not bool(row.get("reachable"))
    )
    expected_stocks = {
        row.stock_id: row.concentration for row in case.stocks
    }
    plan_stocks = {
        row.stock_id: row
        for row in context.experiment_model.get_execution_plan_snapshot().stocks
    }
    observed_stocks = {
        stock_id: str(row.concentration) for stock_id, row in plan_stocks.items()
    }
    checks = {
        "design_oracle_passed": base.decision == "pass",
        "revision_one_prepared": snapshot.plan_revision == 1
        and snapshot.plan_state == "prepared",
        "design_plan_hash_join_exact": snapshot.plan_design_sha256
        == snapshot.design_sha256,
        "optimizer_one_stock_per_reagent": len(plan_stocks) == 5
        and set(plan_stocks) == set(expected_stocks),
        "optimized_concentrations_exact": all(
            stock_id in plan_stocks
            and Decimal(str(plan_stocks[stock_id].concentration))
            == Decimal(concentration)
            for stock_id, concentration in expected_stocks.items()
        ),
        "approximate_targets_exact": approximate_targets
        == case.optimizer_expectations.approximate_targets,
        "unreachable_targets_exact": unreachable_targets
        == case.optimizer_expectations.unreachable_targets,
        "literal_plan_counts_exact": observed["plan_targets"] == expected,
        "literal_progress_counts_exact": observed["progress_targets"] == expected,
        "literal_runtime_counts_exact": observed["runtime_targets"] == expected,
        "zero_progress": snapshot.total_added_droplets == 0,
        "runtime_inactive": not snapshot.runtime_active,
        "assignment_hash_exact": snapshot.assignments
        == {row.well_id: row.reaction_id for row in case.assignments},
        "action_cap_not_exceeded": len(context.action_results)
        <= case.qualification.action_cap,
    }
    evidence = {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "case_id": case.case_id,
        "prepared": snapshot.prepared_evidence(),
        "core_file_hashes": snapshot.core_file_hashes,
        "plan_design_sha256": snapshot.plan_design_sha256,
        "expected_stocks": expected_stocks,
        "observed_stocks": observed_stocks,
        "approximate_targets": approximate_targets,
        "unreachable_targets": unreachable_targets,
        "preview_row_count": len(preview_rows),
        "counts": counts,
        "design_oracle": dict(base.evidence),
    }
    return (
        AssertionResult(
            "experiment.optimizer_360_design_exact",
            "prepared_randomized",
            "pass" if not evidence["failed_checks"] else "fail",
            ("ui", "model", "persistence"),
            evidence,
            (
                None
                if not evidence["failed_checks"]
                else "optimizer 360 design was not exact: "
                + ", ".join(evidence["failed_checks"])
                + f"; expected_stocks={expected_stocks}"
                + f"; observed_stocks={observed_stocks}"
                + f"; approximate_targets={approximate_targets}"
                + f"; unreachable_targets={unreachable_targets}"
                + f"; design_oracle_failed={base.evidence.get('failed_checks')}"
            ),
        ),
        snapshot,
    )


def calibrated_zero_progress_assertion(
    context: Any,
    *,
    case: Any,
    prepared_snapshot: Any,
    calibration_evidence: Mapping[str, Any],
    observer: Mapping[str, Any],
    oracle_checkpoint_id: str = "calibrated_zero_progress",
    legacy_evidence_names: bool = True,
) -> tuple[AssertionResult, Any]:
    """Prove the boundary calibration changed counts but never executed them."""

    from ExecutionCalibrationStore import load_execution_calibrations
    from tools.virtual_workflows.authoritative_evidence import (
        capture_authoritative_bundle,
    )
    snapshot = capture_authoritative_bundle(context)
    counts = capture_count_snapshot(context)
    first_calibration = case.calibrations[0]
    calibrated_stock_id = first_calibration.stock_id
    expected = normalize_stock_well_counts(
        (
            StockWellCount(row.stock_id, row.well_id, row.target_droplets)
            for row in case.oracle(oracle_checkpoint_id).rows
        ),
        label="joined calibrated literal",
    )
    observed = {
        name: normalize_stock_well_counts(counts[name], label=f"joined calibrated {name}")
        for name in ("plan_targets", "progress_targets", "runtime_targets")
    }
    added = normalize_stock_well_counts(
        counts["progress_added"], label="joined calibrated added"
    )
    history = snapshot.history
    history_revisions = [int(item.get("plan_revision", 0)) for item in history]
    history_states = [str(item.get("state") or "") for item in history]
    document = load_execution_calibrations(
        context.experiment_model.execution_calibrations_file_path
    )
    records = [record.to_dict() for record in document.records.values()]
    record = records[0] if len(records) == 1 else {}
    plan_stocks = {stock.stock_id: stock for stock in context.experiment_model.get_execution_plan_snapshot().stocks}
    calibrated_stock = plan_stocks.get(calibrated_stock_id)
    other_stocks = [
        stock
        for stock_id, stock in plan_stocks.items()
        if stock_id != calibrated_stock_id
    ]
    lifecycle = dict(observer.get("lifecycle") or {})
    execution_collections = (
        "begins", "attachments", "completions", "discard_batches",
        "simulator_dispenses", "pass_starts", "terminal_transitions",
        "soft_stop_events",
    )
    transition = dict(calibration_evidence.get("count_transition") or {})
    expected_count_map = {
        (row.stock_id, row.well_id): row.droplets for row in expected
    }
    observed_count_maps = {
        name: {(row.stock_id, row.well_id): row.droplets for row in rows}
        for name, rows in observed.items()
    }
    count_differences = {
        name: [
            {
                "stock_id": stock_id,
                "well_id": well_id,
                "expected": expected_count,
                "observed": observed_count_maps[name].get((stock_id, well_id)),
            }
            for (stock_id, well_id), expected_count in expected_count_map.items()
            if observed_count_maps[name].get((stock_id, well_id)) != expected_count
        ]
        for name in observed
    }
    checks = {
        "plan_identity_unchanged": snapshot.plan_id == prepared_snapshot.plan_id,
        "design_identity_unchanged": snapshot.design_sha256 == prepared_snapshot.design_sha256,
        "revision_history_exact": history_revisions == [1, 2, 3],
        "revision_state_chain_exact": history_states == ["prepared", "active", "active"],
        "revision_three_active": snapshot.plan_revision == 3 and snapshot.plan_state == "active",
        "progress_reference_revision_three": (
            snapshot.progress_plan_id,
            snapshot.progress_plan_revision,
        ) == (snapshot.plan_id, 3),
        "resume_absent": not snapshot.resume_present,
        "eligibility_ready_to_start": snapshot.eligibility_status == "ready_to_start",
        "runtime_inactive": not snapshot.runtime_active,
        "literal_plan_counts_exact": observed["plan_targets"] == expected,
        "literal_progress_counts_exact": observed["progress_targets"] == expected,
        "literal_runtime_counts_exact": observed["runtime_targets"] == expected,
        "zero_added_progress": all(row.droplets == 0 for row in added)
        and snapshot.total_added_droplets == 0
        and not snapshot.completed_well_ids,
        (
            "single_design_a_calibration"
            if legacy_evidence_names
            else "single_first_stock_calibration"
        ): len(records) == 1
        and record.get("stock_id") == calibrated_stock_id,
        "calibration_head_exact": record.get("printer_head_id")
        == first_calibration.printer_head_id,
        "calibration_pulse_volume_exact": int(record.get("pw_us") or 0)
        == first_calibration.print_pulse_width_us
        and math.isclose(
            float(record.get("effective_volume_nL") or 0),
            float(first_calibration.droplet_volume_nL),
        ),
        "plan_calibration_join_exact": calibrated_stock is not None
        and calibrated_stock.printer_head_id == record.get("printer_head_id")
        and calibrated_stock.calibration_record_key == record.get("record_id")
        and math.isclose(
            float(calibrated_stock.effective_volume_nL),
            float(first_calibration.droplet_volume_nL),
        ),
        "other_stock_calibration_absent": all(
            stock.printer_head_id is None and stock.calibration_record_key is None
            for stock in other_stocks
        ),
        "transition_revisions_exact": (
            (transition.get("before") or {}).get("plan_revision"),
            (transition.get("after") or {}).get("plan_revision"),
        ) == (1, 3),
        "zero_execution_lifecycle": all(not lifecycle.get(name) for name in execution_collections)
        and int(lifecycle.get("simulator_dispense_overflow_count", 0) or 0) == 0,
        "controller_idle": context.controller.get_array_run_state() == "idle",
        "simulator_drained": context.machine.check_if_all_completed(),
        "action_cap_not_exceeded": len(context.action_results)
        <= case.qualification.action_cap,
    }
    evidence = {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "prepared": prepared_snapshot.prepared_evidence(),
        "calibrated": snapshot.prepared_evidence(),
        "history_revisions": history_revisions,
        "history_states": history_states,
        "counts": counts,
        "count_differences": count_differences,
        "calibration_record": record,
        "calibration_driver": dict(calibration_evidence),
        "execution_lifecycle": lifecycle,
    }
    return (
        AssertionResult(
            "execution.calibrated_zero_progress_exact",
            "calibrated_zero_progress",
            "pass" if not evidence["failed_checks"] else "fail",
            ("ui", "controller", "model", "persistence", "simulator"),
            evidence,
            (
                None
                if not evidence["failed_checks"]
                else "calibrated zero-progress boundary failed: "
                + ", ".join(evidence["failed_checks"])
                + f"; count_differences={count_differences}"
            ),
        ),
        snapshot,
    )


def clean_joined_session_rotation_assertion(
    context: Any,
    *,
    case: Any,
    rotation: Mapping[str, Any],
    first_session_observer: Mapping[str, Any],
    second_session_observer: Mapping[str, Any],
    oracle_checkpoint_id: str = "calibrated_zero_progress",
) -> AssertionResult:
    """Join a fresh clean-start activation to literal persisted case truth."""

    from ExecutionCalibrationStore import load_execution_calibrations
    source = rotation["source_bundle"]
    loaded = rotation["loaded_bundle"]
    activated = rotation["activated_bundle"]
    sessions = [dict(row) for row in rotation.get("application_sessions", ())]
    expected = normalize_stock_well_counts(
        (
            StockWellCount(row.stock_id, row.well_id, row.target_droplets)
            for row in case.oracle(oracle_checkpoint_id).rows
        ),
        label="joined fresh literal",
    )
    inspections = dict(rotation.get("inspections") or {})
    normalized_inspections = {
        checkpoint: {
            name: normalize_stock_well_counts(
                rows,
                label=f"joined {checkpoint} {name}",
            )
            for name, rows in dict(values).items()
            if name in {
                "plan_targets",
                "progress_targets",
                "runtime_targets",
                "progress_added",
            }
        }
        for checkpoint, values in inspections.items()
    }
    records = load_execution_calibrations(
        context.experiment_model.execution_calibrations_file_path
    ).records
    record_rows = [record.to_dict() for record in records.values()]
    record = record_rows[0] if len(record_rows) == 1 else {}
    stocks = {
        stock.stock_id: stock
        for stock in context.experiment_model.get_execution_plan_snapshot().stocks
    }
    first_calibration = case.calibrations[0]
    calibrated_stock = stocks.get(first_calibration.stock_id)
    calibrated_revision = first_calibration.output_revision
    lifecycle_keys = (
        "begins",
        "attachments",
        "completions",
        "discard_batches",
        "simulator_dispenses",
        "pass_starts",
        "terminal_transitions",
        "soft_stop_events",
    )
    lifecycle_1 = dict(first_session_observer.get("lifecycle") or {})
    lifecycle_2 = dict(second_session_observer.get("lifecycle") or {})
    loaded_counts = normalized_inspections.get("loaded", {})
    activated_counts = normalized_inspections.get("activated", {})
    checks = {
        "two_distinct_application_sessions": len(sessions) == 2
        and sessions[0].get("application_session_id")
        != sessions[1].get("application_session_id"),
        "same_retained_session_root": len(sessions) == 2
        and sessions[0].get("session_id") == sessions[1].get("session_id"),
        "first_recorder_closed": len(sessions) == 2
        and (sessions[0].get("recorder") or {}).get("status") == "closed",
        "first_lock_absent": (
            rotation.get("first_session_cleanup") or {}
        ).get("session_lock_present")
        is False,
        "close_files_byte_identical": bool(
            (rotation.get("between_sessions") or {}).get("byte_identical")
        ),
        "identity_constant_across_boundaries": (
            source.plan_id,
            source.plan_revision,
            source.design_sha256,
        )
        == (loaded.plan_id, loaded.plan_revision, loaded.design_sha256)
        == (activated.plan_id, activated.plan_revision, activated.design_sha256),
        "revision_three_active_exact": source.plan_revision
        == loaded.plan_revision
        == activated.plan_revision
        == calibrated_revision
        and source.plan_state == loaded.plan_state == activated.plan_state == "active",
        "assignments_exact": source.assignments
        == activated.assignments
        == source.expected_assignments
        == loaded.expected_assignments
        == activated.expected_assignments
        == {row.well_id: row.reaction_id for row in case.assignments},
        "history_exact": [int(row.get("plan_revision", 0)) for row in activated.history]
        == list(range(1, calibrated_revision + 1)),
        "loaded_inactive_ready_to_start": not loaded.runtime_active
        and loaded.eligibility_status == "ready_to_start"
        and not loaded.resume_present,
        "activated_runtime_ready_to_start": activated.runtime_active
        and activated.eligibility_status == "ready_to_start"
        and context.controller.get_array_run_state() == "idle",
        "activated_clean_resume_reference_exact": activated.resume_present
        and activated.resume_state == "clean"
        and (activated.resume_plan_id, activated.resume_plan_revision)
        == (activated.plan_id, calibrated_revision)
        and activated.resume_intent_count == 0,
        "progress_reference_exact": (
            source.progress_plan_id,
            source.progress_plan_revision,
        )
        == (source.plan_id, calibrated_revision)
        == (loaded.progress_plan_id, loaded.progress_plan_revision)
        == (activated.progress_plan_id, activated.progress_plan_revision),
        "loaded_literal_counts_exact": all(
            loaded_counts.get(name) == expected
            for name in ("plan_targets", "progress_targets")
        ),
        "activated_literal_counts_exact": all(
            activated_counts.get(name) == expected
            for name in ("plan_targets", "progress_targets", "runtime_targets")
        ),
        "zero_progress_across_rotation": source.total_added_droplets
        == loaded.total_added_droplets
        == activated.total_added_droplets
        == 0
        and all(
            row.droplets == 0
            for values in (loaded_counts, activated_counts)
            for row in values.get("progress_added", ())
        ),
        "calibration_head_join_exact": len(record_rows) == 1
        and record.get("stock_id") == first_calibration.stock_id
        and record.get("printer_head_id") == first_calibration.printer_head_id
        and calibrated_stock is not None
        and calibrated_stock.calibration_record_key == record.get("record_id")
        and calibrated_stock.printer_head_id == record.get("printer_head_id"),
        "first_session_zero_execution": all(
            not lifecycle_1.get(name) for name in lifecycle_keys
        ),
        "second_session_zero_execution": all(
            not lifecycle_2.get(name) for name in lifecycle_keys
        ),
        "simulator_drained": context.machine.check_if_all_completed(),
        "action_cap_not_exceeded": len(context.action_results)
        <= case.qualification.action_cap,
    }
    evidence = {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "application_sessions": sessions,
        "first_session_cleanup": dict(rotation.get("first_session_cleanup") or {}),
        "between_sessions": dict(rotation.get("between_sessions") or {}),
        "reload_boundaries": dict(rotation.get("reload_boundaries") or {}),
        "source": source.prepared_evidence(),
        "loaded": loaded.prepared_evidence(),
        "activated": activated.prepared_evidence(),
        "inspections": inspections,
        "calibration_record": record,
        "first_session_lifecycle": lifecycle_1,
        "second_session_lifecycle": lifecycle_2,
    }
    return AssertionResult(
        "execution.clean_session_rotation_exact",
        "fresh_activated",
        "pass" if not evidence["failed_checks"] else "fail",
        ("ui", "session", "model", "persistence", "simulator"),
        evidence,
        (
            None
            if not evidence["failed_checks"]
            else "clean joined session rotation failed: "
            + ", ".join(evidence["failed_checks"])
        ),
    )


def joined_remaining_calibrations_assertion(
    context: Any,
    *,
    case: Any,
    calibration_evidence: list[Mapping[str, Any]],
    oracle_checkpoint_id: str = "all_stocks_calibrated",
) -> tuple[AssertionResult, Any]:
    """Prove all joined calibrations and literal revision-5 counts by ID."""

    from ExecutionCalibrationStore import load_execution_calibrations
    from tools.virtual_workflows.authoritative_evidence import (
        capture_authoritative_bundle,
    )

    snapshot = capture_authoritative_bundle(context)
    counts = capture_count_snapshot(context)
    expected = normalize_stock_well_counts(
        (
            StockWellCount(row.stock_id, row.well_id, row.target_droplets)
            for row in case.oracle(oracle_checkpoint_id).rows
        ),
        label="joined all-calibrated literal",
    )
    observed = {
        name: normalize_stock_well_counts(
            counts[name], label=f"joined all-calibrated {name}"
        )
        for name in ("plan_targets", "progress_targets", "runtime_targets")
    }
    added = normalize_stock_well_counts(
        counts["progress_added"], label="joined all-calibrated added"
    )
    document = load_execution_calibrations(
        context.experiment_model.execution_calibrations_file_path
    )
    records = {
        record.stock_id: record.to_dict() for record in document.records.values()
    }
    calibrations = {row.stock_id: row for row in case.calibrations}
    plan_stocks = {
        stock.stock_id: stock
        for stock in context.experiment_model.get_execution_plan_snapshot().stocks
    }
    identity_checks = {
        stock_id: (
            stock_id in records
            and stock_id in plan_stocks
            and records[stock_id].get("printer_head_id")
            == calibration.printer_head_id
            and int(records[stock_id].get("pw_us") or 0)
            == calibration.print_pulse_width_us
            and math.isclose(
                float(records[stock_id].get("effective_volume_nL") or 0),
                float(calibration.droplet_volume_nL),
            )
            and plan_stocks[stock_id].printer_head_id
            == calibration.printer_head_id
            and plan_stocks[stock_id].calibration_record_key
            == records[stock_id].get("record_id")
        )
        for stock_id, calibration in calibrations.items()
    }
    final_revision = case.calibrations[-1].output_revision
    checks = {
        "revision_history_exact": [
            int(item.get("plan_revision", 0)) for item in snapshot.history
        ]
        == list(range(1, final_revision + 1)),
        "revision_five_active": snapshot.plan_revision == final_revision
        and snapshot.plan_state == "active",
        "progress_reference_revision_five": (
            snapshot.progress_plan_id,
            snapshot.progress_plan_revision,
        )
        == (snapshot.plan_id, final_revision),
        "resume_reference_revision_five": snapshot.resume_present
        and snapshot.resume_state == "clean"
        and (snapshot.resume_plan_id, snapshot.resume_plan_revision)
        == (snapshot.plan_id, final_revision)
        and snapshot.resume_intent_count == 0,
        "three_calibration_records": len(records) == len(case.calibrations)
        and set(records) == set(calibrations),
        "calibration_stock_head_record_joins": all(identity_checks.values()),
        "literal_plan_counts_exact": observed["plan_targets"] == expected,
        "literal_progress_counts_exact": observed["progress_targets"] == expected,
        "literal_runtime_counts_exact": observed["runtime_targets"] == expected,
        "zero_added_progress": all(row.droplets == 0 for row in added)
        and snapshot.total_added_droplets == 0,
        "remaining_calibration_order_exact": [
            str(row.get("stock_id")) for row in calibration_evidence
        ]
        == [row.stock_id for row in case.calibrations[1:]],
        "remaining_heads_returned": all(
            (row.get("return") or {}).get("returned") is True
            for row in calibration_evidence
        ),
        "controller_idle_and_drained": context.controller.get_array_run_state()
        == "idle"
        and context.machine.check_if_all_completed(),
        "action_cap_not_exceeded": len(context.action_results)
        <= case.qualification.action_cap,
    }
    evidence = {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "identity_checks": identity_checks,
        "bundle": snapshot.prepared_evidence(),
        "history_revisions": [
            int(item.get("plan_revision", 0)) for item in snapshot.history
        ],
        "counts": counts,
        "records": records,
        "calibrations": [dict(row) for row in calibration_evidence],
    }
    return (
        AssertionResult(
            "execution.remaining_calibrations_exact",
            "remaining_stocks_calibrated",
            "pass" if not evidence["failed_checks"] else "fail",
            ("ui", "controller", "model", "persistence", "simulator"),
            evidence,
            (
                None
                if not evidence["failed_checks"]
                else "remaining joined calibrations failed: "
                + ", ".join(evidence["failed_checks"])
            ),
        ),
        snapshot,
    )


def joined_terminal_lifecycle_reconciliation(
    *,
    case: Any,
    lifecycle: Mapping[str, Any],
    pass_boundaries: list[Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Reconcile literal stock/well intents to simulator commands exactly once."""

    expected = normalize_stock_well_counts(
        (
            StockWellCount(row.stock_id, row.well_id, row.target_droplets)
            for row in case.oracle("all_stocks_calibrated").rows
        ),
        label="joined lifecycle literal",
    )
    expected_map = {
        (row.stock_id, row.well_id): row.droplets for row in expected
    }
    begins = [dict(row) for row in lifecycle.get("begins", ())]
    attachments = [dict(row) for row in lifecycle.get("attachments", ())]
    completions = list(lifecycle.get("completions", ()))
    simulator = [dict(row) for row in lifecycle.get("simulator_dispenses", ())]
    begin_ids = [str(row.get("intent_id") or "") for row in begins]
    begins_by_id = {str(row.get("intent_id") or ""): row for row in begins}
    attachments_by_id = {
        str(row.get("intent_id") or ""): row for row in attachments
    }

    def command_sequence(row: Mapping[str, Any] | None) -> int | None:
        if row is None or row.get("command_seq32") is None:
            return None
        try:
            return int(row["command_seq32"])
        except (TypeError, ValueError):
            return None

    simulator_by_sequence = {
        sequence: row
        for row in simulator
        if (sequence := command_sequence(row)) is not None
    }
    observed_map = {
        (str(row.get("stock_id")), str(row.get("well_id"))): int(
            row.get("commanded_droplets", 0) or 0
        )
        for row in begins
    }
    command_join_checks: dict[str, bool] = {}
    for intent_id in begin_ids:
        attachment = attachments_by_id.get(intent_id)
        sequence = command_sequence(attachment)
        command = simulator_by_sequence.get(sequence)
        begin = begins_by_id.get(intent_id)
        command_join_checks[intent_id] = bool(
            attachment is not None
            and sequence is not None
            and command is not None
            and begin is not None
            and command.get("command_type") == "DISPENSE"
            and command.get("status") == "Completed"
            and not bool(command.get("manual"))
            and int(command.get("commanded_droplets", 0) or 0)
            == int(begin.get("commanded_droplets", 0) or 0)
        )
    expected_pass_ids = [row.stock_id for row in case.execution_passes]
    expected_intents = int(case.terminal.expected_intents)
    expected_droplets = int(case.terminal.expected_droplets)
    cumulative = 0
    expected_boundaries: list[tuple[str, int, str]] = []
    for execution_pass in case.execution_passes:
        cumulative = int(
            getattr(
                execution_pass,
                "cumulative_completion",
                cumulative + int(execution_pass.expected_intents),
            )
        )
        expected_boundaries.append(
            (
                execution_pass.stock_id,
                cumulative,
                (
                    "completed"
                    if execution_pass.order == len(case.execution_passes)
                    else "active"
                ),
            )
        )
    pass_starts = [
        str(row.get("stock_id") or "")
        for row in lifecycle.get("pass_starts", ())
    ]
    checks = {
        "intent_pairs_and_counts_exact": len(begins) == expected_intents
        and len(set(begin_ids)) == expected_intents
        and observed_map == expected_map,
        "attachments_exact_once": len(attachments) == expected_intents
        and len(attachments_by_id) == expected_intents
        and set(attachments_by_id) == set(begin_ids)
        and len(
            {
                sequence
                for row in attachments
                if (sequence := command_sequence(row)) is not None
            }
        )
        == expected_intents,
        "simulator_commands_exact_once": len(simulator) == expected_intents
        and len(simulator_by_sequence) == expected_intents
        and all(command_join_checks.values()),
        "completion_ids_exact_once": len(completions) == expected_intents
        and Counter(str(value) for value in completions) == Counter(begin_ids),
        "droplet_total_exact": sum(observed_map.values())
        == sum(
            int(row.get("commanded_droplets", 0) or 0) for row in simulator
        )
        == expected_droplets,
        "no_discard_or_overflow": not lifecycle.get("discard_batches")
        and int(lifecycle.get("simulator_dispense_overflow_count", 0) or 0) == 0,
        "pass_order_exact": pass_starts == expected_pass_ids,
        "pass_boundaries_exact": [
            (
                str(row.get("stock_id")),
                int(row.get("observed_completed_count", 0)),
                str(row.get("plan_state")),
            )
            for row in pass_boundaries
        ]
        == expected_boundaries,
    }
    return {
        "checks": checks,
        "expected_counts": [
            {"stock_id": row.stock_id, "well_id": row.well_id, "droplets": row.droplets}
            for row in expected
        ],
        "intent_counts": begins,
        "simulator_dispenses": simulator,
        "command_join_checks": command_join_checks,
        "pass_starts": pass_starts,
        "pass_boundaries": [dict(row) for row in pass_boundaries],
        "simulator_dispense_overflow_count": int(
            lifecycle.get("simulator_dispense_overflow_count", 0) or 0
        ),
    }


def joined_terminal_execution_assertion(
    context: Any,
    *,
    case: Any,
    terminal_counts: Mapping[str, Any],
    terminal_reload: Mapping[str, Any],
    observer: Mapping[str, Any],
    first_session_observer: Mapping[str, Any],
    pass_boundaries: list[Mapping[str, Any]],
    starvation_events: list[Mapping[str, Any]],
    application_sessions: list[Mapping[str, Any]],
) -> AssertionResult:
    """Reconcile every joined command and persisted count exactly once."""

    from ExecutionCalibrationStore import load_execution_calibrations

    expected = normalize_stock_well_counts(
        (
            StockWellCount(row.stock_id, row.well_id, row.target_droplets)
            for row in case.oracle("all_stocks_calibrated").rows
        ),
        label="joined terminal literal",
    )
    normalized_terminal = {
        name: normalize_stock_well_counts(
            terminal_counts[name], label=f"joined terminal {name}"
        )
        for name in (
            "plan_targets",
            "progress_targets",
            "runtime_targets",
            "progress_added",
        )
    }
    after_counts_raw = dict(terminal_reload.get("after_counts") or {})
    normalized_reloaded = {
        name: normalize_stock_well_counts(
            after_counts_raw[name], label=f"joined reloaded {name}"
        )
        for name in ("plan_targets", "progress_targets", "progress_added")
    }
    lifecycle = dict(observer.get("lifecycle") or {})
    lifecycle_reconciliation = joined_terminal_lifecycle_reconciliation(
        case=case,
        lifecycle=lifecycle,
        pass_boundaries=pass_boundaries,
    )
    before = terminal_reload["before"]
    after = terminal_reload["after"]
    records = {
        record.stock_id: record.to_dict()
        for record in load_execution_calibrations(
            context.experiment_model.execution_calibrations_file_path
        ).records.values()
    }
    calibration_by_stock = {row.stock_id: row for row in case.calibrations}
    first_lifecycle = dict(first_session_observer.get("lifecycle") or {})
    zero_keys = (
        "begins",
        "attachments",
        "completions",
        "discard_batches",
        "simulator_dispenses",
        "pass_starts",
        "terminal_transitions",
        "soft_stop_events",
    )
    terminal_revision = int(
        getattr(
            case.terminal,
            "terminal_revision",
            case.calibrations[-1].output_revision + 1,
        )
    )
    expected_history = list(range(1, terminal_revision + 1))
    expected_sessions = int(case.terminal.application_sessions)
    checks = {
        "terminal_plan_progress_runtime_targets_exact": all(
            normalized_terminal[name] == expected
            for name in ("plan_targets", "progress_targets", "runtime_targets")
        ),
        "terminal_added_exact": normalized_terminal["progress_added"] == expected,
        "reloaded_plan_progress_added_exact": all(
            normalized_reloaded[name] == expected
            for name in ("plan_targets", "progress_targets", "progress_added")
        ),
        **dict(lifecycle_reconciliation["checks"]),
        "revision_history_one_through_six": [
            int(row.get("plan_revision", 0)) for row in after.history
        ]
        == expected_history,
        "terminal_revision_six_analysis_only": before.plan_revision
        == after.plan_revision
        == terminal_revision
        and before.plan_state == after.plan_state == "completed"
        and before.eligibility_status == after.eligibility_status == "analysis_only",
        "terminal_references_exact": (
            after.progress_plan_id,
            after.progress_plan_revision,
            after.resume_plan_id,
            after.resume_plan_revision,
        )
        == (
            after.plan_id,
            terminal_revision,
            after.plan_id,
            terminal_revision,
        ),
        "calibration_records_exact": set(records) == set(calibration_by_stock)
        and all(
            records[stock_id].get("printer_head_id") == row.printer_head_id
            and int(records[stock_id].get("pw_us", 0) or 0)
            == row.print_pulse_width_us
            and math.isclose(
                float(records[stock_id].get("effective_volume_nL", 0) or 0),
                float(row.droplet_volume_nL),
            )
            for stock_id, row in calibration_by_stock.items()
        ),
        "three_distinct_application_sessions": len(application_sessions)
        == expected_sessions
        and len(
            {
                str(row.get("application_session_id"))
                for row in application_sessions
            }
        )
        == expected_sessions,
        "session_one_zero_dispatch": all(
            not first_lifecycle.get(name) for name in zero_keys
        ),
        "session_three_zero_dispatch": not getattr(
            context.machine, "command_event_history", ()
        )
        and context.machine.check_if_all_completed()
        and not after.runtime_active,
        "no_starvation_or_errors": not starvation_events
        and not context.errors
        and not context.unexpected_dialogs,
        "action_cap_not_exceeded": len(context.action_results)
        <= case.qualification.action_cap,
    }
    evidence = {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        **{
            key: value
            for key, value in lifecycle_reconciliation.items()
            if key != "checks"
        },
        "application_sessions": [dict(row) for row in application_sessions],
        "terminal": {
            "plan_id": after.plan_id,
            "plan_revision": after.plan_revision,
            "plan_state": after.plan_state,
            "eligibility_status": after.eligibility_status,
            "total_added_droplets": after.total_added_droplets,
            "calibration_record_count": after.calibration_record_count,
        },
        "records": records,
        "starvation_events": [dict(row) for row in starvation_events],
    }
    return AssertionResult(
        "execution.randomized_calibration_terminal_exact",
        "terminal_reloaded",
        "pass" if not evidence["failed_checks"] else "fail",
        ("ui", "controller", "model", "persistence", "simulator", "session"),
        evidence,
        (
            None
            if not evidence["failed_checks"]
            else "joined terminal reconciliation failed: "
            + ", ".join(evidence["failed_checks"])
        ),
    )


def _prepared_bundle_results(
    snapshot: Any,
    *,
    expected_well_ids: tuple[str, ...],
) -> tuple[AssertionResult, AssertionResult]:
    expected = list(expected_well_ids)
    bundle_checks = {
        "directory_name_matches": Path(snapshot.experiment_dir).name
        == snapshot.metadata.get("name"),
        "design_hash_matches": snapshot.plan_design_sha256
        == snapshot.design_sha256,
        "plan_revision_one": snapshot.plan_revision == 1,
        "plan_prepared": snapshot.plan_state == "prepared",
        "plan_wells_exact": list(snapshot.plan_well_ids) == expected,
        "history_exact": len(snapshot.history_json) == 1
        and snapshot.history_matches_current,
        "bundle_valid": snapshot.bundle_valid,
        "ready_to_start": snapshot.eligibility_status == "ready_to_start",
        "progress_schema_v2": snapshot.progress_schema_version == 2,
        "progress_reference_matches": snapshot.progress_plan_id
        == snapshot.plan_id
        and snapshot.progress_plan_revision == snapshot.plan_revision,
        "progress_zero": snapshot.total_added_droplets == 0
        and not snapshot.completed_well_ids,
        "resume_absent": not snapshot.resume_present,
        "runtime_assignments_match": snapshot.assignments
        == snapshot.expected_assignments,
        "calibration_history_absent": snapshot.calibration_record_count == 0
        and snapshot.manual_refuel_check_count == 0,
        "runtime_inactive": not snapshot.runtime_active,
    }
    bundle_evidence = {
        "checks": bundle_checks,
        "failed_checks": sorted(
            name for name, passed in bundle_checks.items() if not passed
        ),
        **snapshot.prepared_evidence(),
    }
    bundle_result = evaluate_assertion(
        "experiment.prepared_bundle_valid",
        "prepared",
        ("model", "persistence"),
        lambda: (not bundle_evidence["failed_checks"], bundle_evidence),
    )

    key_rows = snapshot.key_rows
    concentration_rows = snapshot.concentration_rows
    key_totals = {
        well_id: sum(int(float(value or 0)) for value in row.values())
        for well_id, row in key_rows.items()
    }
    concentration_values = {
        well_id: sum(float(value or 0) for value in row.values())
        for well_id, row in concentration_rows.items()
    }
    key_checks = {
        "key_wells_exact": list(key_rows) == expected,
        "concentration_wells_exact": list(concentration_rows) == expected,
        "key_targets_match": key_totals == snapshot.targets_by_well,
        "concentration_targets_match": all(
            math.isclose(value, 1.0, rel_tol=0.0, abs_tol=1e-9)
            for value in concentration_values.values()
        ),
    }
    key_evidence = {
        "checks": key_checks,
        "failed_checks": sorted(
            name for name, passed in key_checks.items() if not passed
        ),
        "key_rows": key_rows,
        "concentration_rows": concentration_rows,
    }
    key_result = evaluate_assertion(
        "experiment.key_files_consistent",
        "prepared",
        ("persistence",),
        lambda: (not key_evidence["failed_checks"], key_evidence),
    )
    return bundle_result, key_result


def capture_editor_prepared_revision_snapshot(
    context: Any,
    *,
    expected_well_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Capture one validated untouched PREPARED bundle without mutating it."""

    from tools.virtual_workflows.authoritative_evidence import (
        capture_authoritative_bundle,
    )

    snapshot = capture_authoritative_bundle(context)
    bundle_result, key_result = _prepared_bundle_results(
        snapshot, expected_well_ids=expected_well_ids
    )
    if bundle_result.decision != "pass" or key_result.decision != "pass":
        raise RuntimeError(
            "initial prepared editor bundle was invalid: "
            f"bundle={bundle_result.evidence}, keys={key_result.evidence}"
        )
    prepared = {
        **dict(bundle_result.evidence),
        **dict(key_result.evidence),
    }
    before = {
        "experiment_dir": snapshot.experiment_dir,
        "metadata_name": snapshot.metadata.get("name"),
        "plan_id": snapshot.plan_id,
        "plan_revision": snapshot.plan_revision,
        "plan_design_sha256": snapshot.plan_design_sha256,
        "resume_present": snapshot.resume_present,
        "runtime_assignments": snapshot.assignments,
        "file_sha256": snapshot.core_file_hashes,
        "audit_rows": snapshot.audit_rows,
    }
    return {
        "prepared_bundle": prepared,
        "before": before,
        "authoritative_snapshot": snapshot,
    }


def editor_prepared_revision_assertions(
    context: Any,
    *,
    fixture: Mapping[str, Any],
    initial_snapshot: Mapping[str, Any],
    action_start: int,
    action_end: int | None = None,
) -> tuple[tuple[AssertionResult, ...], dict[str, Any]]:
    """Validate a renamed/refinalized PREPARED bundle through read-only reads."""

    from tools.virtual_workflows.authoritative_evidence import (
        capture_authoritative_bundle,
        snapshot_directory,
    )

    experiment = fixture["experiment"]
    reagent = fixture["reagent"]
    initial = initial_snapshot["authoritative_snapshot"]
    before = dict(initial_snapshot["before"])
    initial_dir = Path(before["experiment_dir"]).resolve()
    after = capture_authoritative_bundle(
        context, experiments_root=initial_dir.parent
    )
    experiment_dir = Path(after.experiment_dir)
    design_path = Path(after.design_path)
    design = after.design
    expected_wells = list(experiment["refinalized_expected_well_ids"])
    plan_wells = list(after.plan_well_ids)
    assignments = after.assignments
    expected_assignments = after.expected_assignments
    key_rows = after.key_rows
    concentration_rows = after.concentration_rows
    key_totals = {
        well_id: sum(int(float(value or 0)) for value in row.values())
        for well_id, row in key_rows.items()
    }
    concentration_values = {
        well_id: sum(
            float(value or 0)
            for column, value in row.items()
            if column.startswith(f"{reagent['stock_label']}_")
        )
        for well_id, row in concentration_rows.items()
    }
    expected_concentrations = sorted(
        float(target)
        for target in reagent["refinalized_targets"]
        for _ in range(int(experiment["refinalized_replicates"]))
    )
    observed_concentrations = sorted(concentration_values.values())
    metadata = design.get("metadata", {})
    factors = design.get("factors", [])
    reagent_option = (
        factors[0].get("options", [{}])[0] if len(factors) == 1 else {}
    )
    calibration_empty = after.calibration_record_count == 0 and (
        after.manual_refuel_check_count == 0
    )
    experiment_directories = list(after.experiment_directories)
    staging_directories = list(after.staging_directories)
    current_plan_paths = list(after.current_plan_paths)
    audit_rows = after.audit_rows
    file_sha256 = after.core_file_hashes
    archived_root = (
        experiment_dir
        / "superseded_prepared_execution_plans"
        / initial.plan_id
    )
    archived_plan_path = archived_root / "prepared_plan_at_replacement.json"
    archived_design_path = archived_root / "experiment_design_at_replacement.json"
    inspection_hashes = snapshot_directory(experiment_dir).hashes
    inspection_file_sha256 = {
        path: inspection_hashes[path] for path in file_sha256
    }
    revision_ui_ids = (
        "editor.open_via_ui",
        "editor.rename_prepared_via_ui",
        "editor.edit_prepared_design_via_ui",
        "editor.regenerate_prepared_design_via_ui",
        "editor.refinalize_prepared_via_ui",
    )
    revision_ids = tuple(
        value
        for action_id in revision_ui_ids
        for value in (action_id, "artifact.capture_milestone")
    )
    revision_surfaces = tuple(
        value
        for _action_id in revision_ui_ids
        for value in ("ui", "harness")
    )
    action_result = exact_action_sequence_assertion(
        context,
        expectation=ActionSequenceExpectation(revision_ids, revision_surfaces),
        start_index=action_start,
        end_index=action_end,
        assertion_id="experiment.prepared_rename_refinalize",
        checkpoint="refinalized",
        evidence_surface="ui",
    )
    action_evidence = action_result.evidence
    archived_plan_json = (
        json.dumps(
            json.loads(archived_plan_path.read_text(encoding="utf-8")),
            sort_keys=True,
            separators=(",", ":"),
        )
        if archived_plan_path.is_file()
        else None
    )
    archived_design_json = (
        json.dumps(
            json.loads(archived_design_path.read_text(encoding="utf-8")),
            sort_keys=True,
            separators=(",", ":"),
        )
        if archived_design_path.is_file()
        else None
    )
    checks = {
        "revision_actions_exact": action_evidence["observed_action_ids"]
        == list(revision_ui_ids),
        "revision_actions_ui": action_evidence["interaction_surfaces"]
        == ["ui"] * len(revision_ui_ids),
        "revision_actions_passed": action_evidence["statuses"]
        == ["pass"] * len(revision_ui_ids),
        "old_directory_absent": not initial_dir.exists(),
        "renamed_directory_present": experiment_dir.is_dir(),
        "directory_name_matches": experiment_dir.name == experiment["renamed_name"],
        "metadata_name_matches": metadata.get("name") == experiment["renamed_name"],
        "replicates_updated": metadata.get("replicates")
        == experiment["refinalized_replicates"],
        "printed_volume_updated": math.isclose(
            float(metadata.get("target_reaction_volume_nL", -1)),
            float(experiment["refinalized_printed_volume_nL"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        ),
        "final_volume_updated": math.isclose(
            float(metadata.get("final_reaction_volume_nL", -1)),
            float(experiment["refinalized_final_volume_nL"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        ),
        "fill_mode_updated": metadata.get("fill_printing_mode")
        == experiment["refinalized_fill_printing_mode"],
        "fill_droplet_updated": math.isclose(
            float(metadata.get("fill_droplet_volume_nL", -1)),
            float(experiment["refinalized_fill_droplet_volume_nL"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        ),
        "reagent_mode_updated": reagent_option.get("printing_mode")
        == reagent["refinalized_printing_mode"],
        "reagent_targets_updated": reagent_option.get("targets")
        == reagent["refinalized_targets"],
        "reagent_droplet_updated": math.isclose(
            float(reagent_option.get("droplet_nL", -1)),
            float(reagent["refinalized_droplet_volume_nL"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        ),
        "bundle_valid": after.bundle_valid,
        "design_hash_matches": after.plan_design_sha256 == after.design_sha256,
        "fresh_plan_identity": after.plan_id != initial.plan_id,
        "plan_revision_one": after.plan_revision == 1,
        "plan_prepared": after.plan_state == "prepared",
        "plan_volume_basis_updated": math.isclose(
            after.target_printed_volume_nl,
            float(experiment["refinalized_printed_volume_nL"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        ) and math.isclose(
            after.final_reaction_volume_nl,
            float(experiment["refinalized_final_volume_nL"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        ),
        "plan_modes_updated": set(after.plan_stock_modes)
        == {reagent["refinalized_printing_mode"]},
        "plan_wells_exact": plan_wells == expected_wells,
        "history_current_matches": after.history_matches_current,
        "ready_to_start": after.eligibility_status == "ready_to_start",
        "progress_reference_matches": after.progress_plan_id == after.plan_id
        and after.progress_plan_revision == after.plan_revision,
        "progress_zero": after.total_added_droplets == 0
        and not after.completed_well_ids,
        "resume_absent": not after.resume_present,
        "runtime_inactive": not after.runtime_active,
        "key_wells_exact": list(key_rows) == expected_wells,
        "concentration_wells_exact": list(concentration_rows) == expected_wells,
        "key_targets_match": key_totals == after.targets_by_well,
        "concentration_targets_match": len(observed_concentrations)
        == len(expected_concentrations)
        and all(
            math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-9)
            for observed, expected in zip(
                observed_concentrations, expected_concentrations
            )
        ),
        "runtime_assignments_match_plan": assignments == expected_assignments,
        "runtime_assignments_replaced": assignments
        != before["runtime_assignments"],
        "original_plan_archived": archived_plan_json == initial.plan_json,
        "original_design_archived": archived_design_json == initial.design_json,
        "calibration_history_absent": calibration_empty,
        "printing_history_absent": after.total_added_droplets == 0,
        "inspection_read_only": inspection_file_sha256 == file_sha256,
        "single_experiment_directory": experiment_directories
        == [experiment["renamed_name"]],
        "no_staging_directories": not staging_directories,
        "single_current_plan": current_plan_paths
        == [f"{experiment['renamed_name']}/execution_plan.json"],
        "audit_retained_and_advanced": len(audit_rows)
        > len(before["audit_rows"]),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    evidence = {
        "checks": checks,
        "failed_checks": failed_checks,
        "experiment_dir": str(experiment_dir),
        "design_path": str(design_path),
        "initial_name": experiment["initial_name"],
        "renamed_name": experiment["renamed_name"],
        "previous_plan_id": initial.plan_id,
        "plan_id": after.plan_id,
        "plan_revision": after.plan_revision,
        "plan_state": after.plan_state,
        "eligibility_status": after.eligibility_status,
        "history_count": len(after.history_json),
        "well_ids": plan_wells,
        "runtime_assignments": assignments,
        "runtime_assignments_before": dict(before["runtime_assignments"]),
        "key_rows": key_rows,
        "concentration_rows": concentration_rows,
        "total_added_droplets": after.total_added_droplets,
        "experiment_directories": experiment_directories,
        "staging_directories": staging_directories,
        "current_plan_paths": current_plan_paths,
        "file_sha256": file_sha256,
        "audit_rows": audit_rows,
        "superseded_prepared_execution": {
            "directory": str(archived_root),
            "plan_path": str(archived_plan_path),
            "design_path": str(archived_design_path),
        },
    }
    groups = {
        "experiment.prepared_rename_refinalize": (
            "revision_actions_exact",
            "revision_actions_ui",
            "revision_actions_passed",
            "old_directory_absent",
            "renamed_directory_present",
            "directory_name_matches",
            "metadata_name_matches",
            "fresh_plan_identity",
        ),
        "experiment.prepared_design_refinalize": (
            "replicates_updated",
            "printed_volume_updated",
            "final_volume_updated",
            "fill_mode_updated",
            "fill_droplet_updated",
            "reagent_mode_updated",
            "reagent_targets_updated",
            "reagent_droplet_updated",
            "plan_volume_basis_updated",
            "plan_modes_updated",
            "plan_wells_exact",
            "runtime_assignments_replaced",
            "original_plan_archived",
            "original_design_archived",
        ),
        "experiment.renamed_artifacts_unique": (
            "single_experiment_directory",
            "no_staging_directories",
            "single_current_plan",
            "audit_retained_and_advanced",
        ),
        "experiment.refinalized_bundle_valid": (
            "bundle_valid",
            "design_hash_matches",
            "plan_revision_one",
            "plan_prepared",
            "history_current_matches",
            "ready_to_start",
            "progress_reference_matches",
            "progress_zero",
            "resume_absent",
            "runtime_inactive",
            "runtime_assignments_match_plan",
            "calibration_history_absent",
            "printing_history_absent",
            "inspection_read_only",
        ),
        "experiment.key_files_consistent": (
            "key_wells_exact",
            "concentration_wells_exact",
            "key_targets_match",
            "concentration_targets_match",
        ),
    }
    results = tuple(
        evaluate_assertion(
            assertion_id,
            "refinalized",
            ("ui", "model", "persistence"),
            lambda names=names: (
                all(checks[name] for name in names),
                {
                    "checks": {name: checks[name] for name in names},
                    "failed_checks": [name for name in names if not checks[name]],
                    "plan_id": after.plan_id,
                    "plan_state": after.plan_state,
                    "experiment_dir": str(experiment_dir),
                },
            ),
        )
        for assertion_id, names in groups.items()
    )
    return results, evidence


def editor_prepared_revision_failure_assertion(exc: BaseException) -> AssertionResult:
    action_id = str(getattr(exc, "action_id", "") or "")
    assertion_id = (
        "experiment.prepared_design_refinalize"
        if action_id in {
            "editor.edit_prepared_design_via_ui",
            "editor.regenerate_prepared_design_via_ui",
        }
        else "experiment.prepared_rename_refinalize"
    )
    return AssertionResult(
        assertion_id=assertion_id,
        checkpoint="prepared_revision_failed",
        decision="fail",
        observable_sources=("ui", "action_ledger"),
        evidence={
            "action_id": action_id or None,
            "failure_type": type(exc).__name__,
            "failure_message": str(exc)[:2000],
            "action_evidence": dict(getattr(exc, "evidence", {}) or {}),
        },
        message=str(exc)[:2000],
    )


def editor_prepared_reload_assertions(
    context: Any,
    *,
    prepared_evidence: Mapping[str, Any],
    loader_evidence: Mapping[str, Any],
) -> tuple[AssertionResult, AssertionResult]:
    from tools.virtual_workflows.authoritative_evidence import (
        capture_authoritative_bundle,
    )

    snapshot = capture_authoritative_bundle(context)

    def inspect_reload() -> tuple[bool, Mapping[str, Any]]:
        evidence = {
            **dict(loader_evidence),
            "plan_id": snapshot.plan_id,
            "plan_revision": snapshot.plan_revision,
            "plan_state": snapshot.plan_state,
            "resume_present": snapshot.resume_present,
            "runtime_active": snapshot.runtime_active,
            "activation_performed": False,
        }
        passed = (
            evidence["plan_id"] == str(prepared_evidence.get("plan_id"))
            and evidence["plan_revision"]
            == int(prepared_evidence.get("plan_revision", -1))
            and evidence["plan_state"] == "prepared"
            and evidence.get("eligibility_status") == "ready_to_start"
            and not evidence["resume_present"]
            and not evidence["runtime_active"]
        )
        return passed, evidence

    reload_result = evaluate_assertion(
        "experiment.prepared_reload_ready",
        "reloaded",
        ("ui", "model", "persistence"),
        inspect_reload,
    )

    def inspect_assignments() -> tuple[bool, Mapping[str, Any]]:
        assignments = snapshot.assignments
        before = dict(prepared_evidence.get("runtime_assignments") or {})
        return assignments == before, {"before": before, "after": assignments}

    assignments_result = evaluate_assertion(
        "experiment.runtime_assignments_match",
        "reloaded",
        ("model",),
        inspect_assignments,
    )
    return reload_result, assignments_result


def editor_sequence_exploration_assertions(
    context: Any,
    *,
    exploration: Mapping[str, Any],
    driver_evidence: Mapping[str, Any],
    refinalized_evidence: Mapping[str, Any],
    loader_evidence: Mapping[str, Any],
    action_start: int,
    action_end: int | None = None,
) -> tuple[AssertionResult, AssertionResult, AssertionResult]:
    """Validate a generated editor plan, rejection, and terminal recovery."""

    sequence = dict(exploration["sequence"])
    planned_steps = [dict(step) for step in sequence["steps"]]
    observed_transitions = [
        dict(step) for step in driver_evidence.get("observed_transitions", [])
    ]
    observed_transitions.append(
        {
            "ordinal": int(planned_steps[-1]["ordinal"]),
            "action_id": "experiment.load_authoritative_via_ui",
            "from_state": str(planned_steps[-1]["from_state"]),
            "to_state": str(planned_steps[-1]["to_state"]),
            "expected_outcome": "accepted",
            "observed_outcome": "accepted",
            "edit_variant": None,
        }
    )
    relevant_ids = {str(step["action_id"]) for step in planned_steps}
    end = len(context.action_results) if action_end is None else action_end
    ledger = [
        dict(result)
        for result in context.action_results[action_start:end]
        if result.get("action_id") in relevant_ids
    ]
    planned_action_ids = [str(step["action_id"]) for step in planned_steps]
    observed_action_ids = [str(result.get("action_id")) for result in ledger]
    transition_checks = {
        "action_ids_exact": observed_action_ids == planned_action_ids,
        "actions_passed": all(result.get("status") == "pass" for result in ledger),
        "actions_use_ui": all(
            result.get("interaction_surface") == "ui" for result in ledger
        ),
        "transition_count_exact": len(observed_transitions) == len(planned_steps),
        "transition_actions_exact": [
            step.get("action_id") for step in observed_transitions
        ] == planned_action_ids,
        "transition_states_exact": all(
            observed.get("from_state") == planned.get("from_state")
            and observed.get("to_state") == planned.get("to_state")
            for observed, planned in zip(observed_transitions, planned_steps)
        ),
        "transition_outcomes_exact": all(
            observed.get("observed_outcome") == planned.get("expected_outcome")
            for observed, planned in zip(observed_transitions, planned_steps)
        ),
        "transition_variants_exact": all(
            observed.get("edit_variant") == planned.get("edit_variant")
            for observed, planned in zip(observed_transitions, planned_steps)
        ),
        # The body adds one final evidence capture and teardown adds one action.
        "action_cap_respected": len(context.action_results) + 2
        <= int(exploration["maximum_actions"]),
    }
    plan_evidence = {
        "checks": transition_checks,
        "failed_checks": sorted(
            key for key, passed in transition_checks.items() if not passed
        ),
        "campaign_id": exploration["campaign_id"],
        "generator_version": exploration["generator_version"],
        "catalog_sha256": exploration["catalog_sha256"],
        "sequence_sha256": exploration["sequence_sha256"],
        "sequence": sequence,
        "observed_transitions": observed_transitions,
        "observed_action_ids": observed_action_ids,
        "action_count_at_assertion": len(context.action_results),
        "projected_terminal_action_count": len(context.action_results) + 2,
    }
    plan_result = evaluate_assertion(
        "exploration.sequence_plan_applied",
        "sequence_complete",
        ("ui", "action_ledger"),
        lambda: (not plan_evidence["failed_checks"], plan_evidence),
    )

    rejections = [dict(value) for value in driver_evidence.get("rejections", [])]
    expected_rejections = 1 if sequence["sequence_class"] == "illegal" else 0
    rejection_checks = {
        "rejection_count_exact": len(rejections) == expected_rejections,
        "safe_evidence_exact": all(value.get("safe") is True for value in rejections),
        "single_finalize_activation": all(
            int(value.get("activation_count", -1)) == 1 for value in rejections
        ),
        "invalid_volume_dialog_handled": all(
            (value.get("warning") or {}).get("entered") is True
            and (value.get("warning") or {}).get("title") == "Invalid volumes"
            and (value.get("warning") or {}).get("type") == "QMessageBox"
            and (value.get("warning") or {}).get("dismissed") is True
            for value in rejections
        ),
        "authoritative_unchanged": all(
            value.get("authoritative_state_unchanged") is True
            and value.get("before") == value.get("after")
            for value in rejections
        ),
        "dialog_retained": all(
            value.get("dialog_after") == value.get("dialog_before")
            and bool((value.get("dialog_after") or {}).get("visible"))
            for value in rejections
        ),
    }
    rejection_evidence = {
        "checks": rejection_checks,
        "failed_checks": sorted(
            key for key, passed in rejection_checks.items() if not passed
        ),
        "sequence_class": sequence["sequence_class"],
        "expected_rejection_count": expected_rejections,
        "rejections": rejections,
    }
    rejection_result = evaluate_assertion(
        "exploration.expected_rejection_safe",
        "rejection_observed" if expected_rejections else "legal_sequence",
        ("ui", "model", "persistence"),
        lambda: (not rejection_evidence["failed_checks"], rejection_evidence),
    )

    final_checks = {
        key: value
        for key, value in dict(refinalized_evidence.get("checks") or {}).items()
        if not key.startswith("revision_actions_")
    }
    recovery_checks = {
        "refinalized_checks_pass": bool(final_checks)
        and all(final_checks.values()),
        "prepared": loader_evidence.get("plan_state") == "prepared",
        "ready_to_start": loader_evidence.get("eligibility_status")
        == "ready_to_start",
        "activation_absent": loader_evidence.get("activation_performed") is False,
        "runtime_inactive": not context.experiment_model.is_authoritative_execution_runtime_active(),
        "array_idle": context.controller.get_array_run_state() == "idle",
        "queue_drained": context.machine.check_if_all_completed(),
        "no_unexpected_dialogs": not context.unexpected_dialogs,
        "no_errors": not context.errors,
    }
    recovery_evidence = {
        "checks": recovery_checks,
        "failed_checks": sorted(
            key for key, passed in recovery_checks.items() if not passed
        ),
        "plan_id": refinalized_evidence.get("plan_id"),
        "plan_revision": refinalized_evidence.get("plan_revision"),
        "well_ids": refinalized_evidence.get("well_ids"),
        "loader": dict(loader_evidence),
    }
    recovery_result = evaluate_assertion(
        "exploration.recovery_terminal_valid",
        "reloaded",
        ("ui", "model", "persistence", "simulator"),
        lambda: (not recovery_evidence["failed_checks"], recovery_evidence),
    )
    return plan_result, rejection_result, recovery_result


def editor_post_start_lock_copy_assertions(
    *,
    source_locked: Mapping[str, Any],
    editor_boundary: Mapping[str, Any],
    copy_finalized: Mapping[str, Any],
    source_after_copy: Mapping[str, Any],
) -> tuple[AssertionResult, ...]:
    """Project the six post-start lock/copy decisions from immutable evidence."""

    locked = dict(source_locked.get("checks") or {})
    matrix = dict(editor_boundary.get("lock_matrix") or {})
    rejection = dict(editor_boundary.get("in_place_rejection") or {})
    before = dict(editor_boundary.get("copy_before_finalize") or {})
    copied = dict(copy_finalized.get("checks") or {})
    policies = (
        ("experiment.active_edit_lock", "source_locked", ("model", "persistence", "ui"),
         {**locked, "ui_locked": matrix.get("all_mutating_controls_locked"),
          "copy_enabled": matrix.get("editable_copy_enabled"),
          "copy_guidance": matrix.get("actionable_lock_guidance")},
         {"source_locked": dict(source_locked), "control_matrix": matrix}),
        ("experiment.in_place_edit_rejected", "in_place_edit_rejected", ("ui",),
         rejection, {"rejection": rejection, "control_matrix": matrix}),
        ("experiment.source_bundle_immutable", "copy_finalized", ("persistence",),
         {key: source_after_copy.get(key) for key in
          ("inventory_unchanged", "files_byte_identical")}, dict(source_after_copy)),
        ("experiment.editable_copy_created", "editable_copy_created",
         ("ui", "persistence"),
         {"controls_editable": before.get("controls_editable"),
          **{key: copied.get(key) for key in
             ("copy_directory_distinct", "copy_directory_name", "copy_metadata_name")}},
         {"copy_before_finalize": before, "copy_checks": copied}),
        ("experiment.editable_copy_fresh_execution", "copy_finalized",
         ("persistence", "model"),
         {key: copied.get(key) for key in (
             "copy_bundle_valid", "copy_prepared", "copy_revision_one",
             "copy_ready_to_start", "copy_plan_distinct", "copy_history_fresh",
             "copy_zero_progress", "copy_resume_absent", "copy_calibration_absent",
             "copy_runtime_inactive", "prepared_reload_valid")},
         dict(copy_finalized)),
        ("experiment.editable_copy_editable", "copy_finalized",
         ("ui", "persistence"),
         {"controls_editable": before.get("controls_editable"),
          **{key: copied.get(key) for key in (
              "copy_tolerance_changed", "copy_semantics_match_source",
              "copy_wells_exact", "copy_key_wells_exact",
              "copy_concentration_wells_exact")}},
         {"copy_before_finalize": before, "copy_checks": copied}),
    )
    return tuple(
        AssertionResult(
            assertion_id, checkpoint,
            "pass" if checks and all(value is True for value in checks.values()) else "fail",
            sources, evidence,
            None if checks and all(value is True for value in checks.values())
            else "post-start editor boundary policy failed",
        )
        for assertion_id, checkpoint, sources, checks, evidence in policies
    )


def editor_artifacts_cleanup_assertion(
    *,
    screenshots: Mapping[str, Path],
    required_screenshots: set[str],
    teardown: Mapping[str, Any],
) -> AssertionResult:
    def inspect() -> tuple[bool, Mapping[str, Any]]:
        cleanup = dict(teardown.get("evidence") or {})
        names = set(screenshots)
        files_valid = all(
            Path(path).is_file() and Path(path).stat().st_size > 0
            for path in screenshots.values()
        )
        evidence = {
            "screenshot_names": sorted(names),
            "required_screenshot_names": sorted(required_screenshots),
            "screenshot_files_valid": files_valid,
            "cleanup": cleanup,
        }
        passed = (
            names == required_screenshots
            and files_valid
            and bool(cleanup.get("close_succeeded"))
            and not bool(cleanup.get("session_lock_present"))
        )
        return passed, evidence

    return evaluate_assertion(
        "artifacts.required_present",
        "closed",
        ("harness", "session", "artifacts"),
        inspect,
    )


__all__ = [
    "ActionSequenceExpectation",
    "AssertionResult",
    "authoritative_first_session_paused_assertion",
    "authoritative_reload_boundary_assertions",
    "authoritative_reload_terminal_assertions",
    "authoritative_session_rotation_assertions",
    "ExecutionLifecycleExpectation",
    "calibration_assertion",
    "calibration_apply_fail_closed_assertion",
    "calibrated_zero_progress_assertion",
    "clean_joined_session_rotation_assertion",
    "joined_remaining_calibrations_assertion",
    "joined_terminal_lifecycle_reconciliation",
    "joined_terminal_execution_assertion",
    "cleanup_assertion",
    "evaluate_assertion",
    "editor_artifacts_cleanup_assertion",
    "editor_create_finalize_assertion",
    "editor_create_rejected_assertion",
    "editor_prepared_bundle_assertions",
    "experiment_design_case_oracle_assertion",
    "experiment_finalization_rejected_no_mutation_assertion",
    "experiment_prepared_runtime_reconstructed_assertion",
    "editor_post_start_lock_copy_assertions",
    "dispense_counts_reconciled_assertion",
    "editor_prepared_reload_assertions",
    "exact_action_sequence_assertion",
    "execution_lifecycle_assertions",
    "machine_ready_assertion",
    "multi_stock_artifacts_assertion",
    "multi_stock_prepared_assertion",
    "multi_stock_terminal_assertions",
    "mixed_mode_lifecycle_assertions",
    "matrix_case_assertions",
    "prepared_execution_assertion",
    "rack_head_assertion",
    "real_application_assertion",
    "randomized_joined_design_assertion",
    "optimizer_360_design_assertion",
    "regression_evidence_assertions",
    "simulation_identity_assertion",
    "synthetic_calibration_contract",
    "terminal_execution_assertion",
    "two_reagent_isolation_assertion",
]
