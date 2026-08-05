"""Simulation-owned manual-refuel outcome bridge."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable


SIMULATED_MANUAL_REFUEL_PROVIDER_VERSION = "milestone-4b-v1"
SIMULATED_MANUAL_REFUEL_SOURCE = "sil_simulated_manual_refuel_check"
SIMULATED_MANUAL_REFUEL_OUTCOMES = frozenset(
    {"passed", "deferred", "failed", "unclear"}
)
SIMULATED_MANUAL_REFUEL_TRIAL_COUNT = 1
SIMULATED_MANUAL_REFUEL_DROPLET_COUNT = 5


def _canonical_notes(seed: int) -> str:
    return json.dumps(
        {
            "provider_version": SIMULATED_MANUAL_REFUEL_PROVIDER_VERSION,
            "seed": int(seed),
            "synthetic": True,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class SimulatedManualRefuelOutcomeAdapter:
    """Record explicit virtual operator outcomes through the application API."""

    def __init__(
        self,
        *,
        seed: int,
        model: Any,
        controller: Any,
        machine: Any,
        recorder: Any,
        snapshot_callback: Callable[..., Any] | None = None,
        failure_callback: Callable[[str], None] | None = None,
        status_changed_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.seed = int(seed)
        self.model = model
        self.controller = controller
        self.machine = machine
        self.recorder = recorder
        self.snapshot_callback = snapshot_callback
        self.failure_callback = failure_callback
        self.status_changed_callback = status_changed_callback
        self.last_outcome = None
        self._recording_failed = False
        self._signal_connected = False

        signal = getattr(
            getattr(model, "experiment_model", None),
            "manual_refuel_check_changed",
            None,
        )
        if signal is not None:
            signal.connect(self._on_manual_refuel_changed)
            self._signal_connected = True

    def set_status_changed_callback(
        self,
        callback: Callable[[str], None] | None,
    ) -> None:
        self.status_changed_callback = callback
        self._notify_status()

    def _notify_status(self) -> None:
        if callable(self.status_changed_callback):
            self.status_changed_callback(self.status_text())

    @staticmethod
    def _display_fingerprint(fingerprint: str) -> str:
        if not fingerprint:
            return "None"
        return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()

    def status_text(self) -> str:
        readiness = self.availability()
        current = readiness.get("current_record") or {}
        outcome = current.get("status") or (
            self.last_outcome.get("status")
            if isinstance(self.last_outcome, dict)
            else "None"
        )
        return (
            f"Readiness: {'Ready' if readiness.get('ok') else 'Not ready'} — "
            f"{readiness.get('message', '')}\n"
            f"Head / stock: {readiness.get('printer_head_id', 'None')} / "
            f"{readiness.get('stock_id', 'None')}\n"
            f"Calibration fingerprint SHA-256: "
            f"{self._display_fingerprint(readiness.get('calibration_fingerprint', ''))}\n"
            f"Preflight: {readiness.get('preflight_code', 'unavailable')}\n"
            f"Last outcome: {outcome}"
        )

    def availability(self) -> dict[str, Any]:
        if self._recording_failed:
            return {
                "ok": False,
                "code": "recording_failed",
                "message": (
                    "Manual-refuel persistence failed; retain this session and do not retry."
                ),
            }
        if self.recorder is None or not bool(getattr(self.recorder, "healthy", False)):
            return {
                "ok": False,
                "code": "recorder_unavailable",
                "message": "State evidence recording is unavailable.",
            }
        state = getattr(self.machine, "state", None)
        if not bool(getattr(state, "connected", False)):
            return {"ok": False, "code": "disconnected", "message": "Connect the simulator first."}
        if not bool(getattr(state, "motors_enabled", False)) or not bool(
            getattr(state, "homed", False)
        ):
            return {
                "ok": False,
                "code": "not_homed",
                "message": "Enable and home the simulator first.",
            }
        if not bool(getattr(state, "regulating_print_pressure", False)) or not bool(
            getattr(state, "regulating_refuel_pressure", False)
        ):
            return {
                "ok": False,
                "code": "pressure_not_regulated",
                "message": "Regulate both print and refuel pressure first.",
            }
        try:
            array_state = str(self.controller.get_array_run_state())
            queue_idle = bool(self.machine.check_if_all_completed())
        except Exception:
            array_state = "unavailable"
            queue_idle = False
        if array_state != "idle" or not queue_idle:
            return {
                "ok": False,
                "code": "application_busy",
                "message": "Manual-refuel recording requires an idle array and empty queue.",
            }

        experiment = getattr(self.model, "experiment_model", None)
        if experiment is None:
            return {
                "ok": False,
                "code": "context_unavailable",
                "message": "No experiment model is available.",
            }
        plan = experiment.get_execution_plan_snapshot()
        if plan is None or experiment.get_execution_plan_source() == "legacy_reconstruction":
            return {
                "ok": False,
                "code": "finalized_plan_required",
                "message": "Load or finalize an authoritative experiment first.",
            }
        try:
            printer_head = self.model.rack_model.get_gripper_printer_head()
        except Exception:
            printer_head = None
        if printer_head is None:
            return {
                "ok": False,
                "code": "context_unavailable",
                "message": "Load the exact virtual stream printer head first.",
            }
        resolver = getattr(experiment, "_resolve_applied_imaging_context", None)
        try:
            context = resolver(printer_head=printer_head) if callable(resolver) else None
        except Exception:
            context = None
        if not isinstance(context, dict):
            return {
                "ok": False,
                "code": "context_unavailable",
                "message": "The loaded head does not resolve to an experiment stock.",
            }
        printing_mode = str(context.get("printing_mode") or "").strip().lower()
        if printing_mode != "stream":
            return {
                "ok": False,
                "code": "stream_mode_required",
                "message": "A currently applied stream calibration is required.",
            }
        applied = experiment.get_applied_imaging_calibration(
            printer_head=printer_head
        )
        if not isinstance(applied, dict):
            return {
                "ok": False,
                "code": "applied_calibration_required",
                "message": "No applied stream calibration is available.",
            }
        applied_mode = str(
            applied.get("applied_printing_mode")
            or applied.get("printing_mode")
            or ""
        ).strip().lower()
        if applied_mode != "stream":
            return {
                "ok": False,
                "code": "applied_stream_required",
                "message": "The applied calibration is not a stream calibration.",
            }
        fingerprint_builder = getattr(
            experiment, "_manual_refuel_applied_fingerprint", None
        )
        fingerprint = (
            str(fingerprint_builder(applied) or "")
            if callable(fingerprint_builder)
            else ""
        )
        if not fingerprint:
            return {
                "ok": False,
                "code": "calibration_fingerprint_unavailable",
                "message": "The applied stream calibration fingerprint is unavailable.",
            }
        current_record = experiment.get_manual_refuel_check(
            printer_head=printer_head
        )
        preflight_getter = getattr(
            self.controller, "get_print_array_refuel_check_preflight", None
        )
        try:
            preflight = preflight_getter() if callable(preflight_getter) else {}
        except Exception:
            preflight = {}
        return {
            "ok": True,
            "code": "ready",
            "message": "Ready to record an explicit simulated manual-refuel outcome.",
            "printer_head": printer_head,
            "printer_head_id": str(context.get("printer_head_id") or ""),
            "stock_id": str(context.get("stock_id") or ""),
            "factor_name": str(context.get("factor_name") or ""),
            "option_name": context.get("option_name"),
            "is_fill": bool(context.get("is_fill")),
            "calibration_fingerprint": fingerprint,
            "applied_record": applied,
            "current_record": current_record,
            "preflight": preflight,
            "preflight_code": str((preflight or {}).get("code") or "unavailable"),
        }

    def _record_event(self, payload: dict[str, Any]) -> None:
        if self.recorder is None or not bool(getattr(self.recorder, "healthy", False)):
            raise RuntimeError("state recorder is unavailable")
        self.recorder.record_event(
            "simulated_manual_refuel_outcome_recorded",
            source_layer="sil_manual_refuel_adapter",
            payload=payload,
            simulated_elapsed_ms=getattr(
                getattr(self.machine, "state", None),
                "simulated_elapsed_ms",
                None,
            ),
        )

    def _latch_failure(self, reason: str) -> None:
        self._recording_failed = True
        if callable(self.failure_callback):
            self.failure_callback(reason)
        self._notify_status()

    def record_outcome(
        self,
        status: str,
        *,
        expected_calibration_fingerprint: str | None = None,
        operator_judgment: str = "simulated",
        trial_count: int | None = None,
        trial_droplet_count: int | None = None,
    ) -> dict[str, Any]:
        status = str(status or "").strip().lower()
        if status not in SIMULATED_MANUAL_REFUEL_OUTCOMES:
            return {
                "ok": False,
                "code": "unsupported_outcome",
                "message": (
                    "Simulated outcomes are limited to passed, deferred, failed, "
                    "or unclear."
                ),
            }
        operator_judgment = str(operator_judgment or "").strip().lower()
        if status == "deferred" and operator_judgment == "simulated":
            operator_judgment = "deferred"
        if not operator_judgment:
            return {
                "ok": False,
                "code": "invalid_operator_judgment",
                "message": "Operator judgment is required.",
            }
        if trial_count is None:
            trial_count = 0 if status == "deferred" else SIMULATED_MANUAL_REFUEL_TRIAL_COUNT
        if trial_droplet_count is None:
            trial_droplet_count = (
                0
                if status == "deferred"
                else SIMULATED_MANUAL_REFUEL_DROPLET_COUNT
            )
        if isinstance(trial_count, bool) or not isinstance(trial_count, int) or trial_count < 0:
            return {
                "ok": False,
                "code": "invalid_trial_count",
                "message": "Trial count must be a non-negative integer.",
            }
        if (
            isinstance(trial_droplet_count, bool)
            or not isinstance(trial_droplet_count, int)
            or trial_droplet_count < 0
        ):
            return {
                "ok": False,
                "code": "invalid_trial_droplet_count",
                "message": "Trial droplet count must be a non-negative integer.",
            }
        if status == "deferred" and (trial_count != 0 or trial_droplet_count != 0):
            return {
                "ok": False,
                "code": "invalid_deferred_trial_metadata",
                "message": "A deferred check must record zero completed trials and droplets.",
            }
        if status != "deferred" and (trial_count <= 0 or trial_droplet_count <= 0):
            return {
                "ok": False,
                "code": "trial_required",
                "message": "A completed paired trial is required for this outcome.",
            }
        readiness = self.availability()
        if not readiness.get("ok"):
            self._notify_status()
            return readiness
        fingerprint = readiness["calibration_fingerprint"]
        if (
            expected_calibration_fingerprint is not None
            and str(expected_calibration_fingerprint) != fingerprint
        ):
            return {
                "ok": False,
                "code": "stale_calibration_fingerprint",
                "message": "The applied stream calibration changed before outcome recording.",
                "expected_calibration_fingerprint": str(expected_calibration_fingerprint),
                "observed_calibration_fingerprint": fingerprint,
            }

        notes = _canonical_notes(self.seed)
        existing = readiness.get("current_record") or {}
        if (
            existing.get("status") == status
            and existing.get("source") == SIMULATED_MANUAL_REFUEL_SOURCE
            and existing.get("notes") == notes
            and existing.get("operator_judgment") == operator_judgment
            and existing.get("trial_count") == trial_count
            and existing.get("trial_droplet_count") == trial_droplet_count
            and existing.get("applied_calibration_fingerprint") == fingerprint
        ):
            self.last_outcome = dict(existing)
            self._notify_status()
            return {
                "ok": True,
                "code": "already_recorded",
                "message": f"Simulated manual-refuel outcome is already {status}.",
                "record": dict(existing),
            }

        before_preflight = dict(readiness.get("preflight") or {})
        recorder = getattr(
            self.controller, "record_manual_refuel_check_outcome", None
        )
        if not callable(recorder):
            failure = "manual-refuel outcome recording is unavailable"
            self._latch_failure(failure)
            return {"ok": False, "code": "recording_unavailable", "message": failure}
        try:
            record = recorder(
                status,
                SIMULATED_MANUAL_REFUEL_SOURCE,
                trial_droplet_count=trial_droplet_count,
                trial_count=trial_count,
                operator_judgment=operator_judgment,
                notes=notes,
            )
        except Exception as exc:
            record = {
                "ok": False,
                "code": "recording_failed",
                "message": str(exc),
            }
        if not isinstance(record, dict) or record.get("ok") is False:
            message = str(
                (record or {}).get("message")
                if isinstance(record, dict)
                else "invalid recording response"
            )
            reason = f"simulated manual-refuel persistence failed: {message}"
            self._latch_failure(reason)
            return {
                "ok": False,
                "code": "recording_failed",
                "message": reason,
                "record": record if isinstance(record, dict) else None,
            }

        try:
            after_preflight = self.controller.get_print_array_refuel_check_preflight()
            payload = {
                "status": status,
                "source": SIMULATED_MANUAL_REFUEL_SOURCE,
                "provider_version": SIMULATED_MANUAL_REFUEL_PROVIDER_VERSION,
                "seed": self.seed,
                "trial_count": trial_count,
                "trial_droplet_count": trial_droplet_count,
                "operator_judgment": operator_judgment,
                "printer_head_id": readiness["printer_head_id"],
                "stock_id": readiness["stock_id"],
                "factor_name": readiness["factor_name"],
                "option_name": readiness["option_name"],
                "is_fill": readiness["is_fill"],
                "calibration_fingerprint": fingerprint,
                "before_preflight": before_preflight,
                "after_preflight": dict(after_preflight or {}),
                "record": dict(record),
            }
            self._record_event(payload)
            if callable(self.snapshot_callback):
                self.snapshot_callback(
                    "simulated_manual_refuel_outcome_recorded",
                    include_persistence=True,
                )
        except Exception as exc:
            reason = f"simulated manual-refuel evidence failed after recording: {exc}"
            self._latch_failure(reason)
            return {
                "ok": False,
                "code": "evidence_recording_failed",
                "message": reason,
                "record": dict(record),
            }

        self.last_outcome = dict(record)
        self._notify_status()
        return {
            "ok": True,
            "code": "recorded",
            "message": f"Recorded simulated manual-refuel outcome: {status}.",
            "record": dict(record),
            "before_preflight": before_preflight,
            "after_preflight": dict(after_preflight or {}),
        }

    def record_deferred(
        self,
        *,
        expected_calibration_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        """Record the real post-Apply prompt's explicit defer decision."""

        return self.record_outcome(
            "deferred",
            expected_calibration_fingerprint=expected_calibration_fingerprint,
            operator_judgment="deferred",
            trial_count=0,
            trial_droplet_count=0,
        )

    def _on_manual_refuel_changed(self, record: Any) -> None:
        if isinstance(record, dict):
            self.last_outcome = dict(record)
        self._notify_status()

    def dispose(self) -> None:
        if not self._signal_connected:
            return
        signal = getattr(
            getattr(self.model, "experiment_model", None),
            "manual_refuel_check_changed",
            None,
        )
        try:
            signal.disconnect(self._on_manual_refuel_changed)
        except (RuntimeError, TypeError, AttributeError):
            pass
        self._signal_connected = False


__all__ = [
    "SIMULATED_MANUAL_REFUEL_PROVIDER_VERSION",
    "SIMULATED_MANUAL_REFUEL_SOURCE",
    "SIMULATED_MANUAL_REFUEL_OUTCOMES",
    "SimulatedManualRefuelOutcomeAdapter",
]
