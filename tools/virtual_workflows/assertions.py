"""Reusable read-only assertions for composed SIL journeys."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from collections import Counter


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
        targets = [
            int(target.target_dispenses)
            for well in plan.wells
            for target in well.dispenses
        ]
        expected_entries = len(expected_well_ids) * len(expected_stock_ids)
        evidence.update({
            "target_entry_count": len(targets),
            "target_dispense_count": sum(targets),
            "target_dispenses_per_entry": sorted(set(targets)),
        })
        return (
            len(observed_wells) == len(expected_well_ids)
            and set(observed_wells) == set(expected_well_ids)
            and observed_stock_ids == expected_stock_ids
            and len(targets) == expected_entries
            and sum(targets) == expected_entries
            and set(targets) == {1}
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
    boundary_counts = [
        len(expected_well_ids) * (index + 1) for index in range(stock_count)
    ]
    boundary_states = ["active"] * max(0, stock_count - 1) + ["completed"]
    expected_pairs = {
        (stock_id, well_id)
        for stock_id in expected_stock_ids
        for well_id in expected_well_ids
    }

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
    expected_volumes = expectation.expected_volumes_nL or tuple(
        response.predict_volume_nl(str(stock["printing_mode"]), expected_pulses[index])
        for index, stock in enumerate(fixture["stocks"])
    )
    settings = [
        {
            "print_pulse_width_us": int(expected_pulses[index]),
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
        == settings[index]["print_pulse_width_us"]
        and abs(
            float(head_staging[index].get("effective_print_pressure_psi", -1))
            - settings[index]["print_pressure_psi"]
        )
        < 0.01
        for index, stock_id in enumerate(expected_stock_ids)
    )

    observed = [well for well in completed_wells if well in set(expected_well_ids)]
    completion_ok = (
        len(observed) == expected_count
        and Counter(observed)
        == Counter({well: stock_count for well in expected_well_ids})
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
) -> AssertionResult:
    return exact_action_sequence_assertion(
        context,
        expectation=ActionSequenceExpectation(
            (
                "editor.open_via_ui",
                "artifact.capture_milestone",
                "editor.new_experiment_via_ui",
                "editor.configure_design_via_ui",
                "editor.optimize_generate_via_ui",
                "artifact.capture_milestone",
                "editor.finish_via_ui",
            ),
            ("ui", "harness", "ui", "ui", "ui", "harness", "ui"),
        ),
        start_index=action_start,
        end_index=action_end,
        assertion_id="experiment.editor_create_finalize",
        checkpoint="finalized",
        evidence_surface="ui",
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
    "cleanup_assertion",
    "evaluate_assertion",
    "editor_artifacts_cleanup_assertion",
    "editor_create_finalize_assertion",
    "editor_prepared_bundle_assertions",
    "editor_post_start_lock_copy_assertions",
    "editor_prepared_reload_assertions",
    "exact_action_sequence_assertion",
    "execution_lifecycle_assertions",
    "machine_ready_assertion",
    "multi_stock_artifacts_assertion",
    "multi_stock_prepared_assertion",
    "multi_stock_terminal_assertions",
    "mixed_mode_lifecycle_assertions",
    "prepared_execution_assertion",
    "rack_head_assertion",
    "real_application_assertion",
    "regression_evidence_assertions",
    "simulation_identity_assertion",
    "synthetic_calibration_contract",
    "terminal_execution_assertion",
]
