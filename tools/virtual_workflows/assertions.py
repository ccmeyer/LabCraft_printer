"""Reusable read-only assertions for composed SIL journeys."""

from __future__ import annotations

from dataclasses import dataclass
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


__all__ = [
    "AssertionResult",
    "calibration_assertion",
    "cleanup_assertion",
    "evaluate_assertion",
    "machine_ready_assertion",
    "prepared_execution_assertion",
    "rack_head_assertion",
    "simulation_identity_assertion",
    "terminal_execution_assertion",
]
