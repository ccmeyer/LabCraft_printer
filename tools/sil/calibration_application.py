"""Simulation-owned bridge from synthetic calibration to the real application UI."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any, Callable

from .synthetic_calibration import (
    EJECTION_VOLUME_MIN_NL,
    MODE_BOUNDARY_NL,
    PRINT_PRESSURE_MAX_PSI,
    PRINT_PRESSURE_MIN_PSI,
    CalibrationGenerationRequestV1,
    SyntheticCalibrationProvider,
)


def _write_canonical_once(destination: Path, payload: bytes) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != payload:
            raise RuntimeError(
                f"existing synthetic calibration artifact differs: {destination}"
            )
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        # Preserve the same-directory temporary as failure evidence. The
        # session marks itself failed and must not retry this attempt.
        raise


class SyntheticCalibrationApplicationAdapter:
    """Generate, retain, present, and correlate one droplet candidate."""

    def __init__(
        self,
        *,
        session_root: Path,
        session_id: str,
        application_session_id: str,
        seed: int,
        model: Any,
        controller: Any,
        machine: Any,
        recorder: Any,
        open_dialog_callback: Callable[[str], Any],
        snapshot_callback: Callable[..., Any] | None = None,
        failure_callback: Callable[[str], None] | None = None,
        status_changed_callback: Callable[[str], None] | None = None,
        provider: SyntheticCalibrationProvider | None = None,
    ) -> None:
        self.session_root = Path(session_root).resolve()
        self.session_id = str(session_id)
        self.application_session_id = str(application_session_id)
        self.seed = int(seed)
        self.model = model
        self.controller = controller
        self.machine = machine
        self.recorder = recorder
        self.open_dialog_callback = open_dialog_callback
        self.snapshot_callback = snapshot_callback
        self.failure_callback = failure_callback
        self.status_changed_callback = status_changed_callback
        self.provider = provider or SyntheticCalibrationProvider()
        self.current_request = None
        self.current_result = None
        self.current_candidate = None
        self._applied_signal_connected = False
        self._application_state = "Not generated"
        self._evidence_persistence_failed = False

        signal = getattr(
            getattr(model, "experiment_model", None),
            "applied_imaging_calibration_changed",
            None,
        )
        if signal is not None:
            signal.connect(self._on_applied_calibration_changed)
            self._applied_signal_connected = True

    def set_status_changed_callback(
        self,
        callback: Callable[[str], None] | None,
    ) -> None:
        self.status_changed_callback = callback
        self._notify_status()

    def status_text(self) -> str:
        readiness = self.availability()
        readiness_label = "Ready" if readiness.get("ok") else "Not ready"
        fingerprint = (
            self.current_result.result_fingerprint
            if self.current_result is not None
            else "None"
        )
        return (
            f"Readiness: {readiness_label} — {readiness.get('message', '')}\n"
            f"Candidate: {fingerprint}\n"
            f"Apply: {self._application_state}"
        )

    def _notify_status(self) -> None:
        if callable(self.status_changed_callback):
            self.status_changed_callback(self.status_text())

    @property
    def manager(self):
        return self.model.calibration_manager

    def availability(self) -> dict[str, Any]:
        if self._evidence_persistence_failed:
            return {
                "ok": False,
                "code": "evidence_persistence_failed",
                "message": "Synthetic calibration evidence persistence failed; retain this session and do not retry.",
            }
        state = getattr(self.machine, "state", None)
        if not bool(getattr(state, "connected", False)):
            return {"ok": False, "code": "disconnected", "message": "Connect the simulator first."}
        if not bool(getattr(state, "motors_enabled", False)) or not bool(
            getattr(state, "homed", False)
        ):
            return {"ok": False, "code": "not_homed", "message": "Enable and home the simulator first."}
        if not bool(getattr(state, "regulating_print_pressure", False)):
            return {"ok": False, "code": "pressure_not_regulated", "message": "Regulate print pressure first."}
        array_state = str(self.controller.get_array_run_state())
        if array_state != "idle" or not bool(self.machine.check_if_all_completed()):
            return {
                "ok": False,
                "code": "application_busy",
                "message": "Synthetic calibration requires an idle array and empty simulator queue.",
            }
        experiment = self.model.experiment_model
        plan = experiment.get_execution_plan_snapshot()
        if plan is None or experiment.get_execution_plan_source() == "legacy_reconstruction":
            return {
                "ok": False,
                "code": "finalized_plan_required",
                "message": "Load or finalize an authoritative experiment first.",
            }
        try:
            fill_reagent_name = str(experiment.get_fill_reagent_name() or "")
        except (AttributeError, TypeError, ValueError):
            fill_reagent_name = ""
        non_fill_stocks = [
            stock
            for stock in plan.stocks
            if not fill_reagent_name
            or str(getattr(stock, "factor_name", "")) != fill_reagent_name
        ]
        if len(non_fill_stocks) != 1:
            return {
                "ok": False,
                "code": "single_stock_required",
                "message": (
                    "Milestone 4A requires exactly one non-fill execution stock; "
                    "a zero-target fill stock may also be present."
                ),
            }
        context = self.manager.get_characterization_application_context()
        if context is None:
            return {
                "ok": False,
                "code": "context_unavailable",
                "message": "Load the exact virtual printer head for one experiment stock.",
            }
        if context["printing_mode"] != "droplet":
            return {
                "ok": False,
                "code": "droplet_mode_required",
                "message": "Milestone 4A accepts droplet-mode stocks only.",
            }
        matching = [stock for stock in plan.stocks if stock.stock_id == context["stock_id"]]
        if len(matching) != 1:
            return {
                "ok": False,
                "code": "stock_identity_mismatch",
                "message": "The loaded head does not resolve to exactly one execution stock.",
            }
        stock = matching[0]
        stock_identity = {
            "factor_name": str(stock.factor_name),
            "option_name": str(stock.option_name or ""),
            "printing_mode": str(stock.printing_mode),
        }
        if any(context[key] != value for key, value in stock_identity.items()):
            return {
                "ok": False,
                "code": "design_identity_mismatch",
                "message": "The loaded head identity does not match the execution-plan stock.",
            }
        try:
            nominal = float(context["design_volume_nL"])
            pressure = float(self.model.machine_model.get_target_print_pressure())
            pulse_width = int(round(float(self.model.machine_model.get_print_pulse_width())))
        except (TypeError, ValueError) as exc:
            return {
                "ok": False,
                "code": "settings_unavailable",
                "message": f"Current calibration settings are unavailable: {exc}",
            }
        if not (EJECTION_VOLUME_MIN_NL <= nominal < MODE_BOUNDARY_NL):
            return {
                "ok": False,
                "code": "volume_out_of_range",
                "message": "The current design volume is outside droplet-mode bounds.",
            }
        if not (PRINT_PRESSURE_MIN_PSI <= pressure <= PRINT_PRESSURE_MAX_PSI):
            return {
                "ok": False,
                "code": "pressure_out_of_range",
                "message": "The regulated target pressure must be between 0.3 and 5.0 psi.",
            }
        if pulse_width <= 0:
            return {
                "ok": False,
                "code": "pulse_width_out_of_range",
                "message": "The print pulse width must be positive.",
            }
        return {
            "ok": True,
            "code": "ready",
            "message": "Ready to generate a synthetic droplet result.",
            "context": context,
            "stock": stock,
            "nominal_volume_nL": nominal,
            "pressure_psi": pressure,
            "pulse_width_us": pulse_width,
        }

    @staticmethod
    def _variation_fraction(nominal_volume_nl: float) -> float:
        low_room = max(0.0, (float(nominal_volume_nl) - EJECTION_VOLUME_MIN_NL) / float(nominal_volume_nl))
        high_room = max(
            0.0,
            ((MODE_BOUNDARY_NL - 1e-6) - float(nominal_volume_nl))
            / float(nominal_volume_nl),
        )
        return max(0.0, min(0.05, low_room, high_room))

    def _record_event(self, event_kind: str, payload: dict[str, Any]) -> None:
        if self.recorder is None or not self.recorder.healthy:
            raise RuntimeError("state recorder is unavailable")
        self.recorder.record_event(
            event_kind,
            source_layer="sil_calibration_adapter",
            payload=payload,
            simulated_elapsed_ms=getattr(self.machine.state, "simulated_elapsed_ms", None),
        )

    def generate_and_present_nominal_droplet(self) -> dict[str, Any]:
        readiness = self.availability()
        if not readiness.get("ok"):
            self._notify_status()
            return readiness
        context = readiness["context"]
        nominal = readiness["nominal_volume_nL"]
        request = CalibrationGenerationRequestV1(
            seed=self.seed,
            profile_id="nominal_droplet",
            virtual_run_id=(
                f"sil-m4a:{self.session_id}:{context['stock_id']}:"
                f"{context['printer_head_id']}"
            ),
            printer_head_id=context["printer_head_id"],
            stock_id=context["stock_id"],
            factor_name=context["factor_name"],
            option_name=context["option_name"] or None,
            is_fill=bool(context["is_fill"]),
            requested_mode="droplet",
            nominal_volume_nL=nominal,
            volume_variation_fraction=self._variation_fraction(nominal),
            pressure_bounds_psi=(readiness["pressure_psi"], readiness["pressure_psi"]),
            pulse_width_bounds_us=(readiness["pulse_width_us"], readiness["pulse_width_us"]),
        )
        result = self.provider.generate(request)
        result.validate_for_application()
        row = result.to_application_summary_row()
        artifact_dir = (
            self.session_root
            / "artifacts"
            / "synthetic-calibration"
            / self.application_session_id
            / result.result_fingerprint
        )
        request_path = artifact_dir / "request.json"
        result_path = artifact_dir / "result.json"
        try:
            _write_canonical_once(request_path, request.canonical_bytes())
            _write_canonical_once(result_path, result.canonical_bytes())
            self._record_event(
                "synthetic_calibration_generated",
                {
                    "profile_id": result.profile_id,
                    "provider_version": result.provider_version,
                    "seed": result.seed,
                    "request_fingerprint": result.request_fingerprint,
                    "result_fingerprint": result.result_fingerprint,
                    "source_row_fingerprint": list(result.source_row_fingerprint),
                    "printer_head_id": result.printer_head_id,
                    "stock_id": result.stock_id,
                    "factor_name": result.factor_name,
                    "option_name": result.option_name,
                    "is_fill": result.is_fill,
                    "request_artifact": request_path.relative_to(self.session_root).as_posix(),
                    "result_artifact": result_path.relative_to(self.session_root).as_posix(),
                    "synthetic_limitations": list(result.synthetic_limitations),
                },
            )
        except Exception as exc:
            self._evidence_persistence_failed = True
            self._application_state = "Evidence persistence failed"
            if callable(self.failure_callback):
                self.failure_callback(
                    f"synthetic calibration evidence persistence failed: {exc}"
                )
            failure = {
                "ok": False,
                "code": "evidence_persistence_failed",
                "message": f"Synthetic calibration evidence could not be retained: {exc}",
            }
            self._notify_status()
            return failure

        # Keep the package-level tools.sil API importable without application
        # path setup. The candidate type is only needed at the UI bridge.
        from CalibrationClasses.Model import TransientCharacterizationCandidate

        candidate = TransientCharacterizationCandidate(
            candidate_id=result.result_fingerprint,
            source_kind="sil_synthetic_calibration",
            summary_row=row,
            request_fingerprint=result.request_fingerprint,
            result_fingerprint=result.result_fingerprint,
            printer_head_id=result.printer_head_id,
            stock_id=result.stock_id,
            factor_name=result.factor_name,
            option_name=result.option_name,
            is_fill=result.is_fill,
            printing_mode=result.applied_printing_mode,
        )
        try:
            self.manager.set_transient_characterization_candidate(candidate)
            dialog = self.open_dialog_callback(candidate.candidate_id)
        except Exception as exc:
            self.manager.clear_transient_characterization_candidate(candidate.candidate_id)
            self._application_state = "Presentation failed"
            failure = {
                "ok": False,
                "code": "presentation_failed",
                "message": f"Could not present the synthetic calibration result: {exc}",
            }
            self._notify_status()
            return failure
        self.current_request = request
        self.current_result = result
        self.current_candidate = candidate
        self._application_state = "Awaiting Apply"
        self._notify_status()
        return {
            "ok": True,
            "code": "presented",
            "message": f"Synthetic result {result.result_fingerprint[:12]} is open.",
            "request_fingerprint": result.request_fingerprint,
            "result_fingerprint": result.result_fingerprint,
            "dialog": dialog,
        }

    def _on_applied_calibration_changed(self, record) -> None:
        result = self.current_result
        if result is None or not isinstance(record, dict):
            return
        if (
            str(record.get("stock_id") or "") != result.stock_id
            or str(record.get("printer_head_id") or "") != result.printer_head_id
            or tuple(record.get("source_row_fingerprint") or ())
            != tuple(result.source_row_fingerprint)
        ):
            return
        self._application_state = "Applied"
        self._notify_status()
        try:
            self._record_event(
                "synthetic_calibration_applied",
                {
                    "request_fingerprint": result.request_fingerprint,
                    "result_fingerprint": result.result_fingerprint,
                    "source_row_fingerprint": list(result.source_row_fingerprint),
                    "stock_id": result.stock_id,
                    "printer_head_id": result.printer_head_id,
                    "record": dict(record),
                },
            )
            if callable(self.snapshot_callback):
                self.snapshot_callback(
                    "synthetic_calibration_applied",
                    include_persistence=True,
                )
        except Exception as exc:
            if callable(self.failure_callback):
                self.failure_callback(f"synthetic calibration Apply evidence failed: {exc}")

    def dispose(self) -> None:
        if self._applied_signal_connected:
            signal = getattr(
                getattr(self.model, "experiment_model", None),
                "applied_imaging_calibration_changed",
                None,
            )
            try:
                signal.disconnect(self._on_applied_calibration_changed)
            except (RuntimeError, TypeError, AttributeError):
                pass
            self._applied_signal_connected = False
        candidate_id = (
            self.current_candidate.candidate_id
            if self.current_candidate is not None
            else None
        )
        self.manager.clear_transient_characterization_candidate(candidate_id)
