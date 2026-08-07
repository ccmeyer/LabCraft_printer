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

    def __post_init__(self) -> None:
        if not self.expected_well_ids or not self.expected_stock_ids:
            raise ValueError("execution lifecycle expectations must be non-empty")
        if len(set(self.expected_well_ids)) != len(self.expected_well_ids):
            raise ValueError("expected well IDs must be unique")
        if len(set(self.expected_stock_ids)) != len(self.expected_stock_ids):
            raise ValueError("expected stock IDs must be unique")


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
        return (
            len(observed_wells) == len(expected_well_ids)
            and set(observed_wells) == set(expected_well_ids)
            and observed_stock_ids == expected_stock_ids
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
    """Return the eight read-only execution assertions for the 24x2 journey."""

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
        len(head_staging) == 2
        and [row.get("printer_head_id") for row in head_staging]
        == expected_head_ids
        and all(row.get("array_state_before") == "idle" for row in head_staging)
        and all(row.get("queue_drained_before") is True for row in head_staging)
        and head_staging[0].get("returned_previous") is False
        and head_staging[1].get("returned_previous") is True
    )

    boundary_ok = (
        len(pass_boundaries) == 2
        and [row.get("observed_completed_count") for row in pass_boundaries]
        == [len(expected_well_ids), expected_count]
        and [row.get("plan_state") for row in pass_boundaries]
        == ["active", "completed"]
        and all(row.get("controller_state") == "idle" for row in pass_boundaries)
        and all(row.get("queue_drained") is True for row in pass_boundaries)
        and all(row.get("checkpoint_state") == "clean" for row in pass_boundaries)
        and all(row.get("outstanding_intent_count") == 0 for row in pass_boundaries)
    )

    settings = [
        {
            "print_pulse_width_us": int(stock["printer_head"]["print_pulse_width_us"]),
            "print_pressure_psi": float(stock["printer_head"]["print_pressure_psi"]),
            "effective_volume_nL": float(stock["droplet_volume_nL"]),
        }
        for stock in fixture["stocks"]
    ]
    plan_stocks = {stock.stock_id: stock for stock in plan.stocks}
    settings_ok = len(plan_stocks) == 2 and all(
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
        and Counter(observed) == Counter({well: 2 for well in expected_well_ids})
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
    "ExecutionLifecycleExpectation",
    "calibration_assertion",
    "cleanup_assertion",
    "evaluate_assertion",
    "editor_artifacts_cleanup_assertion",
    "editor_create_finalize_assertion",
    "editor_prepared_bundle_assertions",
    "editor_prepared_reload_assertions",
    "exact_action_sequence_assertion",
    "execution_lifecycle_assertions",
    "machine_ready_assertion",
    "multi_stock_artifacts_assertion",
    "multi_stock_prepared_assertion",
    "multi_stock_terminal_assertions",
    "prepared_execution_assertion",
    "rack_head_assertion",
    "real_application_assertion",
    "simulation_identity_assertion",
    "terminal_execution_assertion",
]
