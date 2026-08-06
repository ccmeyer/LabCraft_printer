"""Reusable read-only assertions for composed SIL journeys."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


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


def editor_create_finalize_assertion(context: Any) -> AssertionResult:
    required = (
        "editor.open_via_ui",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        "editor.optimize_generate_via_ui",
        "editor.finish_via_ui",
    )

    def inspect() -> tuple[bool, Mapping[str, Any]]:
        rows = [
            row for row in context.action_results
            if row.get("action_id") in required
        ]
        observed = [str(row.get("action_id")) for row in rows]
        surfaces = [str(row.get("interaction_surface")) for row in rows]
        statuses = [str(row.get("status")) for row in rows]
        evidence = {
            "required_action_ids": list(required),
            "observed_action_ids": observed,
            "interaction_surfaces": surfaces,
            "statuses": statuses,
        }
        return (
            observed == list(required)
            and surfaces == ["ui"] * len(required)
            and statuses == ["pass"] * len(required),
            evidence,
        )

    return evaluate_assertion(
        "experiment.editor_create_finalize",
        "finalized",
        ("ui", "action_ledger"),
        inspect,
    )


def editor_prepared_bundle_assertions(
    context: Any,
    *,
    expected_well_ids: tuple[str, ...],
) -> tuple[AssertionResult, AssertionResult]:
    import csv
    import json
    import math

    def csv_rows(path: Path) -> dict[str, dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows or "Well ID" not in rows[0]:
            raise RuntimeError(f"{path.name} has no Well ID rows")
        return {
            str(row.pop("Well ID")): {
                str(key): str(value) for key, value in row.items()
            }
            for row in rows
        }

    def inspect_bundle() -> tuple[bool, Mapping[str, Any]]:
        from AuthoritativeExecutionLoad import inspect_authoritative_execution
        from ExecutionCalibrationStore import load_execution_calibrations
        from ExecutionPlan import canonical_sha256
        from ExecutionProgressStore import decode_execution_progress

        model = context.experiment_model
        experiment_dir = Path(model.experiment_dir_path).resolve()
        design_path = Path(model.experiment_file_path).resolve()
        design = json.loads(design_path.read_text(encoding="utf-8"))
        plan = model.get_execution_plan_snapshot()
        bundle = inspect_authoritative_execution(experiment_dir, design)
        decoded = decode_execution_progress(plan, bundle.progress_payload)
        assignments = {
            well.well_id: well.get_assigned_reaction().unique_id
            for well in context.model.well_plate.get_all_wells()
            if well.get_assigned_reaction() is not None
        }
        plan_wells = [well.well_id for well in plan.wells]
        expected_assignments = {
            well.well_id: well.reaction_id for well in plan.wells
        }
        total_added = sum(
            int(details["added_droplets"])
            for well in decoded.progress_wells.values()
            for details in well["reagents"].values()
        )
        calibration_path = experiment_dir / "execution_calibrations.json"
        calibration_empty = True
        if calibration_path.exists():
            calibration = load_execution_calibrations(calibration_path)
            calibration_empty = (
                not calibration.records and not calibration.manual_refuel_checks
            )
        resume_path = Path(model.execution_resume_file_path)
        checks = {
            "directory_name_matches": experiment_dir.name
            == design.get("metadata", {}).get("name"),
            "design_hash_matches": plan.design_sha256 == canonical_sha256(design),
            "plan_revision_one": int(plan.plan_revision) == 1,
            "plan_prepared": str(plan.state.value) == "prepared",
            "plan_wells_exact": plan_wells == list(expected_well_ids),
            "history_exact": len(bundle.history) == 1 and bundle.history[0] == plan,
            "bundle_valid": bool(bundle.valid),
            "ready_to_start": bundle.eligibility.status == "ready_to_start",
            "progress_schema_v2": decoded.schema_version == 2,
            "progress_reference_matches": decoded.reference.plan_id
            == plan.plan_id
            and decoded.reference.plan_revision == plan.plan_revision,
            "progress_zero": total_added == 0 and all(
                not bool(well["completed"])
                for well in decoded.progress_wells.values()
            ),
            "resume_absent": not resume_path.exists(),
            "runtime_assignments_match": assignments == expected_assignments,
            "calibration_history_absent": calibration_empty,
            "runtime_inactive": not bool(
                model.is_authoritative_execution_runtime_active()
            ),
        }
        evidence = {
            "checks": checks,
            "failed_checks": sorted(
                name for name, passed in checks.items() if not passed
            ),
            "experiment_dir": str(experiment_dir),
            "design_path": str(design_path),
            "plan_id": str(plan.plan_id),
            "plan_revision": int(plan.plan_revision),
            "plan_state": str(plan.state.value),
            "eligibility_status": bundle.eligibility.status,
            "well_ids": plan_wells,
            "runtime_assignments": assignments,
            "total_added_droplets": total_added,
            "resume_present": resume_path.exists(),
            "design_sha256": canonical_sha256(design),
        }
        return not evidence["failed_checks"], evidence

    bundle_result = evaluate_assertion(
        "experiment.prepared_bundle_valid",
        "prepared",
        ("model", "persistence"),
        inspect_bundle,
    )

    def inspect_keys() -> tuple[bool, Mapping[str, Any]]:
        from AuthoritativeExecutionLoad import inspect_authoritative_execution
        from ExecutionProgressStore import decode_execution_progress

        model = context.experiment_model
        plan = model.get_execution_plan_snapshot()
        experiment_dir = Path(model.experiment_dir_path).resolve()
        design = json.loads(
            Path(model.experiment_file_path).read_text(encoding="utf-8")
        )
        bundle = inspect_authoritative_execution(experiment_dir, design)
        decoded = decode_execution_progress(plan, bundle.progress_payload)
        key_rows = csv_rows(Path(model.key_file_path))
        concentration_rows = csv_rows(Path(model.concentration_key_file_path))
        target_by_well = {
            well_id: sum(
                int(details["target_droplets"])
                for details in entry["reagents"].values()
            )
            for well_id, entry in decoded.progress_wells.items()
        }
        key_totals = {
            well_id: sum(int(float(value or 0)) for value in row.values())
            for well_id, row in key_rows.items()
        }
        concentration_values = {
            well_id: sum(float(value or 0) for value in row.values())
            for well_id, row in concentration_rows.items()
        }
        checks = {
            "key_wells_exact": list(key_rows) == list(expected_well_ids),
            "concentration_wells_exact": list(concentration_rows)
            == list(expected_well_ids),
            "key_targets_match": key_totals == target_by_well,
            "concentration_targets_match": all(
                math.isclose(value, 1.0, rel_tol=0.0, abs_tol=1e-9)
                for value in concentration_values.values()
            ),
        }
        evidence = {
            "checks": checks,
            "failed_checks": sorted(
                name for name, passed in checks.items() if not passed
            ),
            "key_rows": key_rows,
            "concentration_rows": concentration_rows,
        }
        return not evidence["failed_checks"], evidence

    key_result = evaluate_assertion(
        "experiment.key_files_consistent",
        "prepared",
        ("persistence",),
        inspect_keys,
    )
    return bundle_result, key_result


def editor_prepared_reload_assertions(
    context: Any,
    *,
    prepared_evidence: Mapping[str, Any],
    loader_evidence: Mapping[str, Any],
) -> tuple[AssertionResult, AssertionResult]:
    def inspect_reload() -> tuple[bool, Mapping[str, Any]]:
        plan = context.experiment_model.get_execution_plan_snapshot()
        resume_path = Path(context.experiment_model.execution_resume_file_path)
        evidence = {
            **dict(loader_evidence),
            "plan_id": str(plan.plan_id),
            "plan_revision": int(plan.plan_revision),
            "plan_state": str(plan.state.value),
            "resume_present": resume_path.exists(),
            "runtime_active": bool(
                context.experiment_model.is_authoritative_execution_runtime_active()
            ),
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
        assignments = {
            well.well_id: well.get_assigned_reaction().unique_id
            for well in context.model.well_plate.get_all_wells()
            if well.get_assigned_reaction() is not None
        }
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
    "AssertionResult",
    "calibration_assertion",
    "cleanup_assertion",
    "evaluate_assertion",
    "editor_artifacts_cleanup_assertion",
    "editor_create_finalize_assertion",
    "editor_prepared_bundle_assertions",
    "editor_prepared_reload_assertions",
    "machine_ready_assertion",
    "prepared_execution_assertion",
    "rack_head_assertion",
    "real_application_assertion",
    "simulation_identity_assertion",
    "terminal_execution_assertion",
]
