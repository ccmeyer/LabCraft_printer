"""Simulation-owned bridge from synthetic calibration to the real application UI."""

from __future__ import annotations

import json
import os
import math
from pathlib import Path
import tempfile
from typing import Any, Callable

from .synthetic_calibration import (
    EJECTION_VOLUME_MIN_NL,
    EJECTION_VOLUME_MAX_NL,
    MODE_BOUNDARY_NL,
    PRINT_PRESSURE_MAX_PSI,
    PRINT_PRESSURE_MIN_PSI,
    CalibrationGenerationRequestV3,
    CALIBRATION_SCHEMA_VERSION_V3,
    SyntheticCalibrationProvider,
    deserialize_calibration_request,
    deserialize_calibration_result,
)
from .ejection_response import PulseAwareSyntheticEjectionModelV1


APPLICATION_PROFILE_IDS = frozenset(
    {
        "nominal_droplet",
        "droplet_to_stream",
        "nominal_stream",
        "stream_to_droplet",
    }
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
    """Generate, retain, present, and correlate one synthetic candidate."""

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
        self._history_signature = None
        self._history_error = None
        self._history_validation_failed = False
        self._artifact_requests_by_fingerprint = {}
        self._artifact_results_by_fingerprint = {}
        self._artifact_results_by_source = {}

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
        profile_id = (
            self.current_result.profile_id
            if self.current_result is not None
            else "nominal_droplet"
        )
        readiness = self.availability(profile_id)
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

    @staticmethod
    def _record_payload_matches_result(payload, result) -> bool:
        try:
            return bool(
                tuple(payload.get("source_row_fingerprint") or ())
                == tuple(result.source_row_fingerprint)
                and str(payload.get("stock_id") or "") == result.stock_id
                and str(payload.get("printer_head_id") or "")
                == result.printer_head_id
                and str(payload.get("factor_name") or "") == result.factor_name
                and (payload.get("option_name") or None)
                == (result.option_name or None)
                and bool(payload.get("is_fill")) == bool(result.is_fill)
                and str(payload.get("original_printing_mode") or "")
                == result.original_printing_mode
                and str(payload.get("applied_printing_mode") or "")
                == result.applied_printing_mode
                and math.isclose(
                    float(payload.get("effective_volume_nL")),
                    float(result.effective_volume_nL),
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                and math.isclose(
                    float(payload.get("pressure_psi")),
                    float(result.pressure_psi),
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                and int(payload.get("pw_us")) == int(result.pw_us)
            )
        except (TypeError, ValueError):
            return False

    @classmethod
    def _record_matches_result(cls, record, result) -> bool:
        return cls._record_payload_matches_result(record.to_dict(), result)

    def _refresh_historical_candidates(self, *, force=False) -> None:
        experiment = getattr(self.model, "experiment_model", None)
        path_value = getattr(experiment, "execution_calibrations_file_path", None)
        path = Path(path_value).resolve() if path_value else None
        if path is None:
            if self._history_signature is not None:
                self.manager.clear_historical_characterization_candidates()
            self._history_signature = None
            self._history_error = None
            self._artifact_requests_by_fingerprint = {}
            self._artifact_results_by_fingerprint = {}
            self._artifact_results_by_source = {}
            return
        artifact_root = self.session_root / "artifacts" / "synthetic-calibration"
        result_paths = (
            sorted(artifact_root.glob("*/*/result.json"))
            if artifact_root.is_dir()
            else []
        )
        artifact_signature = []
        for result_path in result_paths:
            request_path = result_path.with_name("request.json")
            result_stat = result_path.stat()
            request_stat = request_path.stat() if request_path.is_file() else None
            artifact_signature.append(
                (
                    result_path.relative_to(self.session_root).as_posix(),
                    result_stat.st_mtime_ns,
                    result_stat.st_size,
                    request_stat.st_mtime_ns if request_stat is not None else None,
                    request_stat.st_size if request_stat is not None else None,
                )
            )
        if path.is_file():
            stat = path.stat()
            sidecar_signature = (str(path), stat.st_mtime_ns, stat.st_size)
        else:
            sidecar_signature = (str(path), None, None)
        signature = (
            sidecar_signature,
            tuple(artifact_signature),
            id(self.manager),
        )
        if not force and signature == self._history_signature:
            return

        try:
            from CalibrationClasses.Model import TransientCharacterizationCandidate
            from ExecutionCalibrationStore import load_execution_calibrations

            artifact_requests = {}
            artifact_results = {}
            artifact_results_by_source = {}
            for result_path in result_paths:
                request_path = result_path.with_name("request.json")
                if not request_path.is_file():
                    raise RuntimeError(
                        f"synthetic calibration request artifact is missing: {request_path}"
                    )
                request_raw = request_path.read_bytes()
                result_raw = result_path.read_bytes()
                request = deserialize_calibration_request(
                    json.loads(request_raw.decode("utf-8"))
                )
                result = deserialize_calibration_result(
                    json.loads(result_raw.decode("utf-8"))
                )
                if request_raw != request.canonical_bytes():
                    raise RuntimeError(
                        f"synthetic calibration request is not canonical: {request_path}"
                    )
                if result_raw != result.canonical_bytes():
                    raise RuntimeError(
                        f"synthetic calibration result is not canonical: {result_path}"
                    )
                if request.fingerprint != result.request_fingerprint:
                    raise RuntimeError(
                        f"synthetic calibration artifact pair does not match: {result_path.parent}"
                    )
                result_id = result.result_fingerprint
                previous_result = artifact_results.get(result_id)
                previous_request = artifact_requests.get(result_id)
                if previous_result is not None:
                    if (
                        previous_result.canonical_bytes() != result.canonical_bytes()
                        or previous_request.canonical_bytes() != request.canonical_bytes()
                    ):
                        raise RuntimeError(
                            "duplicate result fingerprint has conflicting retained evidence"
                        )
                    continue
                source_key = tuple(result.source_row_fingerprint)
                previous_source = artifact_results_by_source.get(source_key)
                if (
                    previous_source is not None
                    and previous_source.result_fingerprint != result_id
                ):
                    raise RuntimeError(
                        "multiple retained results claim the same source-row fingerprint"
                    )
                artifact_requests[result_id] = request
                artifact_results[result_id] = result
                artifact_results_by_source[source_key] = result

            records = {}
            if path.is_file():
                records = load_execution_calibrations(str(path)).records
            applied_records = {}
            for record_id, record in sorted(records.items()):
                source_key = tuple(record.source_row_fingerprint or ())
                result = artifact_results_by_source.get(source_key)
                if result is None:
                    continue
                if not self._record_matches_result(record, result):
                    raise RuntimeError(
                        f"execution calibration {record_id} does not match retained synthetic evidence"
                    )
                previous_record = applied_records.get(result.result_fingerprint)
                if previous_record is not None and previous_record[0] != str(record_id):
                    raise RuntimeError(
                        "multiple execution calibrations claim one synthetic result fingerprint"
                    )
                applied_records[result.result_fingerprint] = (str(record_id), record)

            candidates = []
            for result_id, result in sorted(artifact_results.items()):
                applied = applied_records.get(result_id)
                record_id, record = applied if applied is not None else (None, None)
                row = result.to_application_summary_row()
                row.update(
                    {
                        "original_printing_mode": result.original_printing_mode,
                        "applied_printing_mode": result.applied_printing_mode,
                        "application_record_state": (
                            "applied_history" if record is not None else "generated_unapplied"
                        ),
                    }
                )
                if record is not None:
                    row.update(
                        {
                            "execution_calibration_record_id": record_id,
                            "recorded_at_utc": record.recorded_at_utc,
                        }
                    )
                candidates.append(
                    TransientCharacterizationCandidate(
                        candidate_id=result.result_fingerprint,
                        source_kind=(
                            "sil_synthetic_calibration_history"
                            if record is not None
                            else "sil_synthetic_calibration_generated_history"
                        ),
                        summary_row=row,
                        request_fingerprint=result.request_fingerprint,
                        result_fingerprint=result.result_fingerprint,
                        printer_head_id=result.printer_head_id,
                        stock_id=result.stock_id,
                        factor_name=result.factor_name,
                        option_name=result.option_name,
                        is_fill=result.is_fill,
                        printing_mode=result.applied_printing_mode,
                        requested_printing_mode=result.original_printing_mode,
                        application_allowed=(
                            int(getattr(result, "schema_version", 0))
                            == CALIBRATION_SCHEMA_VERSION_V3
                        ),
                        application_block_reason=(
                            None
                            if int(getattr(result, "schema_version", 0))
                            == CALIBRATION_SCHEMA_VERSION_V3
                            else (
                                "This pre-Milestone-4D synthetic result is retained "
                                "as read-only evidence because it has no pulse-response provenance."
                            )
                        ),
                        application_record_state=(
                            "applied_history" if record is not None else "generated_unapplied"
                        ),
                    )
                )
            self.manager.set_historical_characterization_candidates(candidates)
            self._artifact_requests_by_fingerprint = artifact_requests
            self._artifact_results_by_fingerprint = artifact_results
            self._artifact_results_by_source = artifact_results_by_source
            self._history_signature = signature
            self._history_error = None
            self._history_validation_failed = False
        except Exception as exc:
            self._history_error = str(exc)
            self._history_validation_failed = True
            self._application_state = "History validation failed"
            self._artifact_requests_by_fingerprint = {}
            self._artifact_results_by_fingerprint = {}
            self._artifact_results_by_source = {}
            self.manager.clear_transient_characterization_candidate()
            self.manager.clear_historical_characterization_candidates()
            if callable(self.failure_callback):
                self.failure_callback(
                    f"synthetic calibration history validation failed: {exc}"
                )
            raise

    def availability(self, profile_id: str = "nominal_droplet") -> dict[str, Any]:
        profile_id = str(profile_id or "").strip()
        if profile_id not in APPLICATION_PROFILE_IDS:
            return {
                "ok": False,
                "code": "unsupported_profile",
                "message": "That synthetic calibration profile is not available in the application UI.",
            }
        if self._history_validation_failed:
            return {
                "ok": False,
                "code": "history_validation_failed",
                "message": (
                    "Retained synthetic calibration history validation failed; "
                    "retain this session and do not retry."
                ),
            }
        try:
            self._refresh_historical_candidates()
        except Exception:
            return {
                "ok": False,
                "code": "history_validation_failed",
                "message": (
                    "Retained synthetic calibration history could not be validated: "
                    f"{self._history_error}"
                ),
            }
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
        context = self.manager.get_characterization_application_context()
        if context is None:
            return {
                "ok": False,
                "code": "context_unavailable",
                "message": "Load the exact virtual printer head for one experiment stock.",
            }
        requested_mode = (
            "stream"
            if profile_id in {"nominal_stream", "stream_to_droplet"}
            else "droplet"
        )
        if context["printing_mode"] != requested_mode:
            return {
                "ok": False,
                "code": f"{requested_mode}_mode_required",
                "message": (
                    f"Profile {profile_id} requires a {requested_mode}-mode stock."
                ),
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
        if profile_id == "nominal_droplet":
            volume_valid = EJECTION_VOLUME_MIN_NL <= nominal < MODE_BOUNDARY_NL
            volume_message = "The current design volume is outside droplet-mode bounds."
        elif profile_id == "droplet_to_stream":
            volume_valid = EJECTION_VOLUME_MIN_NL <= nominal < MODE_BOUNDARY_NL
            volume_message = (
                "Droplet-to-stream generation requires a droplet design volume "
                "of at least 1 nL and below 40 nL."
            )
        elif profile_id == "nominal_stream":
            volume_valid = MODE_BOUNDARY_NL <= nominal <= EJECTION_VOLUME_MAX_NL
            volume_message = "The current design volume is outside stream-mode bounds."
        else:
            volume_valid = MODE_BOUNDARY_NL <= nominal <= EJECTION_VOLUME_MAX_NL
            volume_message = (
                "Stream-to-droplet generation requires a stream design volume "
                "between 40 and 250 nL."
            )
        if not volume_valid:
            return {
                "ok": False,
                "code": "volume_out_of_range",
                "message": volume_message,
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
        applied_mode = "stream" if profile_id in {
            "droplet_to_stream",
            "nominal_stream",
        } else "droplet"
        response_model = PulseAwareSyntheticEjectionModelV1()
        pulse_range = response_model.pulse_width_range_us(applied_mode)
        matching_profiles = []
        for candidate in list(getattr(self.model, "print_profiles", []) or []):
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("mode") or "").strip().lower() != applied_mode:
                continue
            if response_model.supports(applied_mode, candidate.get("print_pulse_width")):
                matching_profiles.append(dict(candidate))
        if not response_model.supports(applied_mode, pulse_width):
            return {
                "ok": False,
                "correctable": True,
                "code": "synthetic_pulse_width_out_of_range",
                "message": (
                    f"Current print pulse width is {pulse_width} us; "
                    f"{applied_mode.title()} synthetic calibration requires "
                    f"{pulse_range[0]}-{pulse_range[1]} us."
                ),
                "profile_id": profile_id,
                "requested_mode": requested_mode,
                "applied_mode": applied_mode,
                "head_mode": requested_mode,
                "current_print_pulse_width_us": pulse_width,
                "expected_print_pulse_width_us": response_model.default_pulse_width_us(applied_mode),
                "minimum_print_pulse_width_us": pulse_range[0],
                "maximum_print_pulse_width_us": pulse_range[1],
                "matching_profiles": matching_profiles,
            }
        predicted_volume = response_model.predict_volume_nl(applied_mode, pulse_width)
        return {
            "ok": True,
            "code": "ready",
            "message": (
                f"Ready: {pulse_width} us predicts {predicted_volume:.3f} nL "
                f"{applied_mode.title()}."
            ),
            "context": context,
            "stock": stock,
            "profile_id": profile_id,
            "requested_mode": requested_mode,
            "applied_mode": applied_mode,
            "nominal_volume_nL": nominal,
            "predicted_volume_nL": predicted_volume,
            "pressure_psi": pressure,
            "pulse_width_us": pulse_width,
            "minimum_print_pulse_width_us": pulse_range[0],
            "maximum_print_pulse_width_us": pulse_range[1],
            "matching_profiles": matching_profiles,
        }

    def calibration_settings_preflight(self, profile_id: str) -> dict[str, Any]:
        """Return simulation-only pulse readiness and profile correction choices."""

        return dict(self.availability(profile_id) or {})

    def _record_event(self, event_kind: str, payload: dict[str, Any]) -> None:
        if self.recorder is None or not self.recorder.healthy:
            raise RuntimeError("state recorder is unavailable")
        self.recorder.record_event(
            event_kind,
            source_layer="sil_calibration_adapter",
            payload=payload,
            simulated_elapsed_ms=getattr(self.machine.state, "simulated_elapsed_ms", None),
        )

    def generate(self, profile_id: str) -> dict[str, Any]:
        """Generate, retain, and register a candidate without opening a dialog."""
        profile_id = str(profile_id or "").strip()
        readiness = self.availability(profile_id)
        if not readiness.get("ok"):
            self._notify_status()
            return readiness
        context = readiness["context"]
        nominal = readiness["nominal_volume_nL"]
        request = CalibrationGenerationRequestV3(
            seed=self.seed,
            profile_id=profile_id,
            virtual_run_id=(
                f"sil-m4d-v1:{profile_id}:{self.session_id}:"
                f"{context['stock_id']}:{context['printer_head_id']}"
            ),
            printer_head_id=context["printer_head_id"],
            stock_id=context["stock_id"],
            factor_name=context["factor_name"],
            option_name=context["option_name"] or None,
            is_fill=bool(context["is_fill"]),
            requested_mode=readiness["requested_mode"],
            source_volume_nL=nominal,
            print_pressure_psi=readiness["pressure_psi"],
            print_pulse_width_us=readiness["pulse_width_us"],
        )
        result = self.provider.generate(request)
        result.validate_for_application()
        row = result.to_application_summary_row()
        row["original_printing_mode"] = result.original_printing_mode
        row["applied_printing_mode"] = result.applied_printing_mode
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
                    "profile_version": result.profile_version,
                    "provider_version": result.provider_version,
                    "schema_version": result.schema_version,
                    "seed": result.seed,
                    "request_fingerprint": result.request_fingerprint,
                    "result_fingerprint": result.result_fingerprint,
                    "source_row_fingerprint": list(result.source_row_fingerprint),
                    "printer_head_id": result.printer_head_id,
                    "stock_id": result.stock_id,
                    "factor_name": result.factor_name,
                    "option_name": result.option_name,
                    "is_fill": result.is_fill,
                    "source_volume_nL": getattr(result, "source_volume_nL", None),
                    "target_volume_nL": getattr(result, "target_volume_nL", None),
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

        try:
            self._refresh_historical_candidates(force=True)
        except Exception as exc:
            failure = {
                "ok": False,
                "code": "history_validation_failed",
                "message": (
                    "Synthetic calibration evidence could not be validated for "
                    f"presentation: {exc}"
                ),
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
            requested_printing_mode=result.original_printing_mode,
            application_record_state="pending_apply",
        )
        try:
            self.manager.set_transient_characterization_candidate(candidate)
        except Exception as exc:
            self.manager.clear_transient_characterization_candidate(candidate.candidate_id)
            self._application_state = "Registration failed"
            failure = {
                "ok": False,
                "code": "registration_failed",
                "message": f"Could not register the synthetic calibration result: {exc}",
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
            "code": "generated",
            "message": f"Synthetic result {result.result_fingerprint[:12]} is ready.",
            "request_fingerprint": result.request_fingerprint,
            "result_fingerprint": result.result_fingerprint,
            "candidate_id": candidate.candidate_id,
        }

    def generate_and_present(self, profile_id: str) -> dict[str, Any]:
        generated = self.generate(profile_id)
        if not generated.get("ok"):
            return generated
        candidate_id = str(generated["candidate_id"])
        try:
            dialog = self.open_dialog_callback(candidate_id)
        except Exception as exc:
            self.manager.clear_transient_characterization_candidate(candidate_id)
            self._application_state = "Presentation failed"
            failure = {
                "ok": False,
                "code": "presentation_failed",
                "message": f"Could not present the synthetic calibration result: {exc}",
            }
            self._notify_status()
            return failure
        return {
            **generated,
            "code": "presented",
            "message": f"Synthetic result {generated['result_fingerprint'][:12]} is open.",
            "dialog": dialog,
        }

    def generate_and_present_nominal_droplet(self) -> dict[str, Any]:
        return self.generate_and_present("nominal_droplet")

    def _on_applied_calibration_changed(self, record) -> None:
        if not isinstance(record, dict):
            return
        source_key = tuple(record.get("source_row_fingerprint") or ())
        result = self._artifact_results_by_source.get(source_key)
        if result is None or not self._record_payload_matches_result(record, result):
            return
        self.current_request = self._artifact_requests_by_fingerprint.get(
            result.result_fingerprint
        )
        self.current_result = result
        self.manager.clear_transient_characterization_candidate(
            result.result_fingerprint
        )
        if (
            self.current_candidate is not None
            and self.current_candidate.candidate_id == result.result_fingerprint
        ):
            self.current_candidate = None
        self._application_state = "Applied"
        try:
            self._refresh_historical_candidates(force=True)
        except Exception:
            self._notify_status()
            return
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
        self.manager.clear_historical_characterization_candidates()
