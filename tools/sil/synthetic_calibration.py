"""Deterministic synthetic calibration results for hardware-isolated SIL.

This module is deliberately pure.  It does not import Qt, the application
Model or Controller, hardware factories, or filesystem helpers.  Presentation
and application of generated results belong to later SIL milestones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import random
import re
from typing import Any, Mapping


CALIBRATION_REQUEST_SCHEMA_ID = "labcraft.sil_calibration_request"
CALIBRATION_RESULT_SCHEMA_ID = "labcraft.sil_calibration_result"
CALIBRATION_SCHEMA_VERSION = 1
SYNTHETIC_CALIBRATION_PROVIDER_VERSION = "milestone-3-v1"
PROFILE_VERSION = 1

PRINTING_MODES = frozenset({"droplet", "stream"})
MODE_BOUNDARY_NL = 40.0
EJECTION_VOLUME_MIN_NL = 1.0
EJECTION_VOLUME_MAX_NL = 250.0
PRINT_PRESSURE_MIN_PSI = 0.3
PRINT_PRESSURE_MAX_PSI = 5.0

SYNTHETIC_LIMITATIONS = (
    "no_camera_or_segmentation_evidence",
    "no_physical_ejection_or_volume_accuracy_evidence",
    "no_physical_pressure_response_or_refuel_evidence",
    "no_motion_collision_firmware_or_protocol_evidence",
)
SYNTHETIC_STREAM_WARNING = "synthetic_result_without_camera_evidence"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VIRTUAL_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)
_VIRTUAL_YEAR_SECONDS = 366 * 24 * 60 * 60

_REQUEST_FIELDS = {
    "schema_id",
    "schema_version",
    "provider_version",
    "profile_id",
    "profile_version",
    "seed",
    "virtual_run_id",
    "printer_head_id",
    "stock_id",
    "factor_name",
    "option_name",
    "is_fill",
    "requested_mode",
    "nominal_volume_nL",
    "volume_variation_fraction",
    "pressure_bounds_psi",
    "pulse_width_bounds_us",
}

_RESULT_FIELDS = _REQUEST_FIELDS | {
    "request_fingerprint",
    "result_fingerprint",
    "measured_volume_nL",
    "effective_volume_nL",
    "original_printing_mode",
    "applied_printing_mode",
    "pw_us",
    "pressure_psi",
    "run_id",
    "phase",
    "timestamp",
    "source_row_fingerprint",
    "application_valid",
    "validation_errors",
    "synthetic_limitations",
}


class CalibrationContractError(ValueError):
    """Raised when a synthetic-calibration schema or generation request fails."""


class CalibrationApplicationError(ValueError):
    """Raised when a generated result is not safe to present for application."""


def _canonical_json_bytes(payload: Any) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CalibrationContractError(
            f"payload cannot be canonically serialized: {exc}"
        ) from exc


def _canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _require_exact_fields(payload: Mapping[str, Any], expected: set[str], path: str) -> None:
    actual = set(payload)
    missing = expected - actual
    unknown = actual - expected
    if missing:
        raise CalibrationContractError(
            f"{path}: missing required field(s): {', '.join(sorted(missing))}"
        )
    if unknown:
        raise CalibrationContractError(
            f"{path}: unknown field(s): {', '.join(sorted(unknown))}"
        )


def _require_nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CalibrationContractError(f"{path}: must be a nonempty string")
    return value


def _require_optional_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _require_nonempty_string(value, path)


def _require_int(value: Any, path: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CalibrationContractError(f"{path}: must be an integer")
    if minimum is not None and value < minimum:
        raise CalibrationContractError(f"{path}: must be at least {minimum}")
    return value


def _require_finite_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalibrationContractError(f"{path}: must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise CalibrationContractError(f"{path}: must be finite")
    return number


def _require_optional_finite_number(value: Any, path: str) -> float | None:
    if value is None:
        return None
    return _require_finite_number(value, path)


def _require_pair(value: Any, path: str) -> tuple[Any, Any]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise CalibrationContractError(f"{path}: must contain exactly two values")
    return value[0], value[1]


def _require_sha256(value: Any, path: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise CalibrationContractError(f"{path}: must be a lowercase SHA-256 hex digest")
    return value


def _virtual_timestamp(request_fingerprint: str) -> str:
    seconds = int(request_fingerprint[:16], 16) % _VIRTUAL_YEAR_SECONDS
    value = _VIRTUAL_EPOCH + timedelta(seconds=seconds)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _volume_bounds(request: "CalibrationGenerationRequestV1") -> tuple[float, float]:
    delta = request.nominal_volume_nL * request.volume_variation_fraction
    return request.nominal_volume_nL - delta, request.nominal_volume_nL + delta


def _fingerprint_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 9)
    return str(value)


def _source_row_fingerprint(
    *,
    run_id: str,
    phase: str,
    timestamp: str,
    pw_us: int,
    pressure_psi: float,
    measured_volume_nL: float | None,
) -> tuple[Any, ...]:
    return tuple(
        _fingerprint_value(value)
        for value in (
            run_id,
            phase,
            timestamp,
            pw_us,
            pressure_psi,
            measured_volume_nL,
        )
    )


@dataclass(frozen=True)
class SyntheticCalibrationProfileV1:
    """Immutable identity and behavior declaration for one named profile."""

    profile_id: str
    profile_version: int
    volume_strategy: str
    required_requested_mode: str | None
    applied_mode: str | None
    expected_application_valid: bool
    description: str

    def __post_init__(self) -> None:
        _require_nonempty_string(self.profile_id, "profile.profile_id")
        _require_int(self.profile_version, "profile.profile_version", minimum=1)
        if self.volume_strategy not in {
            "sample",
            "low_boundary",
            "high_boundary",
            "outlier",
            "missing",
        }:
            raise CalibrationContractError("profile.volume_strategy: unsupported strategy")
        if self.required_requested_mode is not None and self.required_requested_mode not in PRINTING_MODES:
            raise CalibrationContractError(
                "profile.required_requested_mode: must be droplet, stream, or null"
            )
        if self.applied_mode is not None and self.applied_mode not in PRINTING_MODES:
            raise CalibrationContractError(
                "profile.applied_mode: must be droplet, stream, or null"
            )
        if not isinstance(self.expected_application_valid, bool):
            raise CalibrationContractError(
                "profile.expected_application_valid: must be boolean"
            )
        _require_nonempty_string(self.description, "profile.description")


_PROFILES = (
    SyntheticCalibrationProfileV1(
        "nominal_droplet", PROFILE_VERSION, "sample", "droplet", "droplet", True,
        "Bounded nominal droplet result below the droplet/stream boundary.",
    ),
    SyntheticCalibrationProfileV1(
        "nominal_stream", PROFILE_VERSION, "sample", "stream", "stream", True,
        "Bounded nominal stream result at or above the droplet/stream boundary.",
    ),
    SyntheticCalibrationProfileV1(
        "droplet_to_stream", PROFILE_VERSION, "sample", "droplet", "stream", True,
        "Explicit synthetic mode transition from droplet to stream.",
    ),
    SyntheticCalibrationProfileV1(
        "low_volume_boundary", PROFILE_VERSION, "low_boundary", None, None, True,
        "Exact inclusive lower bound of the requested volume interval.",
    ),
    SyntheticCalibrationProfileV1(
        "high_volume_boundary", PROFILE_VERSION, "high_boundary", None, None, True,
        "Exact inclusive upper bound of the requested volume interval.",
    ),
    SyntheticCalibrationProfileV1(
        "invalid_outlier", PROFILE_VERSION, "outlier", None, None, False,
        "Finite volume deliberately outside the requested volume interval.",
    ),
    SyntheticCalibrationProfileV1(
        "missing_measurement", PROFILE_VERSION, "missing", None, None, False,
        "Deliberately missing measured and effective volume.",
    ),
)
_PROFILE_REGISTRY = {(profile.profile_id, profile.profile_version): profile for profile in _PROFILES}


@dataclass(frozen=True)
class CalibrationGenerationRequestV1:
    """Strict input contract for one deterministic generation operation."""

    seed: int
    profile_id: str
    virtual_run_id: str
    printer_head_id: str
    stock_id: str
    factor_name: str
    option_name: str | None
    is_fill: bool
    requested_mode: str
    nominal_volume_nL: float
    volume_variation_fraction: float
    pressure_bounds_psi: tuple[float, float]
    pulse_width_bounds_us: tuple[int, int]
    provider_version: str = SYNTHETIC_CALIBRATION_PROVIDER_VERSION
    profile_version: int = PROFILE_VERSION
    schema_id: str = CALIBRATION_REQUEST_SCHEMA_ID
    schema_version: int = CALIBRATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_id != CALIBRATION_REQUEST_SCHEMA_ID:
            raise CalibrationContractError("request.schema_id: unsupported schema identity")
        if self.schema_version != CALIBRATION_SCHEMA_VERSION:
            raise CalibrationContractError("request.schema_version: unsupported schema version")
        if self.provider_version != SYNTHETIC_CALIBRATION_PROVIDER_VERSION:
            raise CalibrationContractError("request.provider_version: unsupported provider version")
        _require_int(self.profile_version, "request.profile_version", minimum=1)
        _require_nonempty_string(self.profile_id, "request.profile_id")
        seed = _require_int(self.seed, "request.seed", minimum=0)
        if seed > 2**63 - 1:
            raise CalibrationContractError("request.seed: must be between 0 and 2^63-1")
        for name in (
            "virtual_run_id",
            "printer_head_id",
            "stock_id",
            "factor_name",
        ):
            _require_nonempty_string(getattr(self, name), f"request.{name}")
        _require_optional_string(self.option_name, "request.option_name")
        if not isinstance(self.is_fill, bool):
            raise CalibrationContractError("request.is_fill: must be boolean")
        if self.requested_mode not in PRINTING_MODES:
            raise CalibrationContractError("request.requested_mode: must be droplet or stream")

        nominal = _require_finite_number(
            self.nominal_volume_nL, "request.nominal_volume_nL"
        )
        variation = _require_finite_number(
            self.volume_variation_fraction,
            "request.volume_variation_fraction",
        )
        if not EJECTION_VOLUME_MIN_NL <= nominal <= EJECTION_VOLUME_MAX_NL:
            raise CalibrationContractError(
                "request.nominal_volume_nL: must be between 1 and 250 nL"
            )
        if variation < 0.0 or variation >= 1.0:
            raise CalibrationContractError(
                "request.volume_variation_fraction: must be in [0, 1)"
            )
        object.__setattr__(self, "nominal_volume_nL", nominal)
        object.__setattr__(self, "volume_variation_fraction", variation)
        volume_lo, volume_hi = _volume_bounds(self)
        if volume_lo < EJECTION_VOLUME_MIN_NL or volume_hi > EJECTION_VOLUME_MAX_NL:
            raise CalibrationContractError(
                "request volume interval must remain within the 1-250 nL application envelope"
            )

        pressure_pair = _require_pair(
            self.pressure_bounds_psi, "request.pressure_bounds_psi"
        )
        pressure_bounds = tuple(
            _require_finite_number(value, f"request.pressure_bounds_psi[{index}]")
            for index, value in enumerate(pressure_pair)
        )
        if pressure_bounds[0] > pressure_bounds[1]:
            raise CalibrationContractError(
                "request.pressure_bounds_psi: lower bound must not exceed upper bound"
            )
        if (
            pressure_bounds[0] < PRINT_PRESSURE_MIN_PSI
            or pressure_bounds[1] > PRINT_PRESSURE_MAX_PSI
        ):
            raise CalibrationContractError(
                "request.pressure_bounds_psi: must remain within 0.3-5.0 psi"
            )
        object.__setattr__(self, "pressure_bounds_psi", pressure_bounds)

        pulse_pair = _require_pair(
            self.pulse_width_bounds_us, "request.pulse_width_bounds_us"
        )
        pulse_bounds = tuple(
            _require_int(value, f"request.pulse_width_bounds_us[{index}]", minimum=1)
            for index, value in enumerate(pulse_pair)
        )
        if pulse_bounds[0] > pulse_bounds[1]:
            raise CalibrationContractError(
                "request.pulse_width_bounds_us: lower bound must not exceed upper bound"
            )
        object.__setattr__(self, "pulse_width_bounds_us", pulse_bounds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "provider_version": self.provider_version,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "seed": self.seed,
            "virtual_run_id": self.virtual_run_id,
            "printer_head_id": self.printer_head_id,
            "stock_id": self.stock_id,
            "factor_name": self.factor_name,
            "option_name": self.option_name,
            "is_fill": self.is_fill,
            "requested_mode": self.requested_mode,
            "nominal_volume_nL": self.nominal_volume_nL,
            "volume_variation_fraction": self.volume_variation_fraction,
            "pressure_bounds_psi": list(self.pressure_bounds_psi),
            "pulse_width_bounds_us": list(self.pulse_width_bounds_us),
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, payload: Any) -> "CalibrationGenerationRequestV1":
        if not isinstance(payload, Mapping):
            raise CalibrationContractError("request: must be a JSON object")
        _require_exact_fields(payload, _REQUEST_FIELDS, "request")
        return cls(
            seed=payload["seed"],
            profile_id=payload["profile_id"],
            virtual_run_id=payload["virtual_run_id"],
            printer_head_id=payload["printer_head_id"],
            stock_id=payload["stock_id"],
            factor_name=payload["factor_name"],
            option_name=payload["option_name"],
            is_fill=payload["is_fill"],
            requested_mode=payload["requested_mode"],
            nominal_volume_nL=payload["nominal_volume_nL"],
            volume_variation_fraction=payload["volume_variation_fraction"],
            pressure_bounds_psi=payload["pressure_bounds_psi"],
            pulse_width_bounds_us=payload["pulse_width_bounds_us"],
            provider_version=payload["provider_version"],
            profile_version=payload["profile_version"],
            schema_id=payload["schema_id"],
            schema_version=payload["schema_version"],
        )


def _application_validation_errors(
    *,
    request: CalibrationGenerationRequestV1,
    profile: SyntheticCalibrationProfileV1,
    measured_volume_nL: float | None,
    effective_volume_nL: float | None,
    original_mode: str,
    applied_mode: str,
    pressure_psi: float,
    pw_us: int,
) -> tuple[str, ...]:
    errors: list[str] = []
    volume_lo, volume_hi = _volume_bounds(request)
    if measured_volume_nL is None:
        errors.append("missing_measurement")
    else:
        if not EJECTION_VOLUME_MIN_NL <= measured_volume_nL <= EJECTION_VOLUME_MAX_NL:
            errors.append("measured_volume_outside_application_envelope")
        if not volume_lo <= measured_volume_nL <= volume_hi:
            errors.append("measured_volume_outside_requested_bounds")
    if effective_volume_nL is None:
        errors.append("missing_effective_volume")
    elif measured_volume_nL is not None and not math.isclose(
        effective_volume_nL, measured_volume_nL, rel_tol=0.0, abs_tol=1e-9
    ):
        errors.append("effective_volume_mismatch")
    if original_mode != request.requested_mode:
        errors.append("original_mode_mismatch")
    expected_applied_mode = profile.applied_mode or request.requested_mode
    if applied_mode != expected_applied_mode:
        errors.append("applied_mode_mismatch")
    if measured_volume_nL is not None:
        if applied_mode == "droplet" and measured_volume_nL >= MODE_BOUNDARY_NL:
            errors.append("droplet_volume_not_below_mode_boundary")
        if applied_mode == "stream" and measured_volume_nL < MODE_BOUNDARY_NL:
            errors.append("stream_volume_below_mode_boundary")
    if not request.pressure_bounds_psi[0] <= pressure_psi <= request.pressure_bounds_psi[1]:
        errors.append("pressure_outside_requested_bounds")
    if not request.pulse_width_bounds_us[0] <= pw_us <= request.pulse_width_bounds_us[1]:
        errors.append("pulse_width_outside_requested_bounds")
    return tuple(errors)


@dataclass(frozen=True)
class CalibrationGenerationResultV1:
    """Self-contained deterministic result and synthetic provenance envelope."""

    request_fingerprint: str
    result_fingerprint: str
    provider_version: str
    profile_id: str
    profile_version: int
    seed: int
    virtual_run_id: str
    printer_head_id: str
    stock_id: str
    factor_name: str
    option_name: str | None
    is_fill: bool
    requested_mode: str
    nominal_volume_nL: float
    volume_variation_fraction: float
    pressure_bounds_psi: tuple[float, float]
    pulse_width_bounds_us: tuple[int, int]
    measured_volume_nL: float | None
    effective_volume_nL: float | None
    original_printing_mode: str
    applied_printing_mode: str
    pw_us: int
    pressure_psi: float
    run_id: str
    phase: str
    timestamp: str
    source_row_fingerprint: tuple[Any, ...]
    application_valid: bool
    validation_errors: tuple[str, ...]
    synthetic_limitations: tuple[str, ...]
    schema_id: str = CALIBRATION_RESULT_SCHEMA_ID
    schema_version: int = CALIBRATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_id != CALIBRATION_RESULT_SCHEMA_ID:
            raise CalibrationContractError("result.schema_id: unsupported schema identity")
        if self.schema_version != CALIBRATION_SCHEMA_VERSION:
            raise CalibrationContractError("result.schema_version: unsupported schema version")
        _require_sha256(self.request_fingerprint, "result.request_fingerprint")
        _require_sha256(self.result_fingerprint, "result.result_fingerprint")
        request = self.to_request()
        if request.fingerprint != self.request_fingerprint:
            raise CalibrationContractError(
                "result.request_fingerprint does not match the retained request inputs"
            )
        profile = _PROFILE_REGISTRY.get((self.profile_id, self.profile_version))
        if profile is None:
            raise CalibrationContractError("result profile identity is unsupported")
        measured = _require_optional_finite_number(
            self.measured_volume_nL, "result.measured_volume_nL"
        )
        effective = _require_optional_finite_number(
            self.effective_volume_nL, "result.effective_volume_nL"
        )
        pressure = _require_finite_number(self.pressure_psi, "result.pressure_psi")
        pulse = _require_int(self.pw_us, "result.pw_us", minimum=1)
        object.__setattr__(self, "measured_volume_nL", measured)
        object.__setattr__(self, "effective_volume_nL", effective)
        object.__setattr__(self, "pressure_psi", pressure)
        object.__setattr__(self, "pw_us", pulse)
        if self.original_printing_mode not in PRINTING_MODES:
            raise CalibrationContractError(
                "result.original_printing_mode: must be droplet or stream"
            )
        if self.applied_printing_mode not in PRINTING_MODES:
            raise CalibrationContractError(
                "result.applied_printing_mode: must be droplet or stream"
            )
        if self.run_id != self.virtual_run_id:
            raise CalibrationContractError("result.run_id must equal virtual_run_id")
        expected_phase = "stream" if self.applied_printing_mode == "stream" else "sweep"
        if self.phase != expected_phase:
            raise CalibrationContractError(
                f"result.phase must be {expected_phase!r} for the applied mode"
            )
        if self.timestamp != _virtual_timestamp(self.request_fingerprint):
            raise CalibrationContractError(
                "result.timestamp does not match the deterministic virtual timestamp"
            )
        expected_source_fingerprint = _source_row_fingerprint(
            run_id=self.run_id,
            phase=self.phase,
            timestamp=self.timestamp,
            pw_us=self.pw_us,
            pressure_psi=self.pressure_psi,
            measured_volume_nL=self.measured_volume_nL,
        )
        if tuple(self.source_row_fingerprint) != expected_source_fingerprint:
            raise CalibrationContractError(
                "result.source_row_fingerprint does not match the application row identity"
            )
        if not isinstance(self.application_valid, bool):
            raise CalibrationContractError("result.application_valid: must be boolean")
        if not isinstance(self.validation_errors, tuple) or any(
            not isinstance(item, str) or not item for item in self.validation_errors
        ):
            raise CalibrationContractError(
                "result.validation_errors: must be an array of nonempty strings"
            )
        if tuple(self.synthetic_limitations) != SYNTHETIC_LIMITATIONS:
            raise CalibrationContractError(
                "result.synthetic_limitations must equal the provider-v1 limitations"
            )
        expected_errors = _application_validation_errors(
            request=request,
            profile=profile,
            measured_volume_nL=self.measured_volume_nL,
            effective_volume_nL=self.effective_volume_nL,
            original_mode=self.original_printing_mode,
            applied_mode=self.applied_printing_mode,
            pressure_psi=self.pressure_psi,
            pw_us=self.pw_us,
        )
        if self.validation_errors != expected_errors:
            raise CalibrationContractError(
                "result.validation_errors do not match the application contract"
            )
        if self.application_valid != (not expected_errors):
            raise CalibrationContractError(
                "result.application_valid does not match validation_errors"
            )
        if self.application_valid != profile.expected_application_valid:
            raise CalibrationContractError(
                "result application validity does not match the selected profile"
            )
        fingerprint_payload = self.to_dict()
        fingerprint_payload.pop("result_fingerprint")
        if _canonical_sha256(fingerprint_payload) != self.result_fingerprint:
            raise CalibrationContractError(
                "result.result_fingerprint does not match the normalized result"
            )

    def to_request(self) -> CalibrationGenerationRequestV1:
        return CalibrationGenerationRequestV1(
            seed=self.seed,
            profile_id=self.profile_id,
            virtual_run_id=self.virtual_run_id,
            printer_head_id=self.printer_head_id,
            stock_id=self.stock_id,
            factor_name=self.factor_name,
            option_name=self.option_name,
            is_fill=self.is_fill,
            requested_mode=self.requested_mode,
            nominal_volume_nL=self.nominal_volume_nL,
            volume_variation_fraction=self.volume_variation_fraction,
            pressure_bounds_psi=self.pressure_bounds_psi,
            pulse_width_bounds_us=self.pulse_width_bounds_us,
            provider_version=self.provider_version,
            profile_version=self.profile_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "provider_version": self.provider_version,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "seed": self.seed,
            "virtual_run_id": self.virtual_run_id,
            "printer_head_id": self.printer_head_id,
            "stock_id": self.stock_id,
            "factor_name": self.factor_name,
            "option_name": self.option_name,
            "is_fill": self.is_fill,
            "requested_mode": self.requested_mode,
            "nominal_volume_nL": self.nominal_volume_nL,
            "volume_variation_fraction": self.volume_variation_fraction,
            "pressure_bounds_psi": list(self.pressure_bounds_psi),
            "pulse_width_bounds_us": list(self.pulse_width_bounds_us),
            "request_fingerprint": self.request_fingerprint,
            "result_fingerprint": self.result_fingerprint,
            "measured_volume_nL": self.measured_volume_nL,
            "effective_volume_nL": self.effective_volume_nL,
            "original_printing_mode": self.original_printing_mode,
            "applied_printing_mode": self.applied_printing_mode,
            "pw_us": self.pw_us,
            "pressure_psi": self.pressure_psi,
            "run_id": self.run_id,
            "phase": self.phase,
            "timestamp": self.timestamp,
            "source_row_fingerprint": list(self.source_row_fingerprint),
            "application_valid": self.application_valid,
            "validation_errors": list(self.validation_errors),
            "synthetic_limitations": list(self.synthetic_limitations),
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def validate_for_application(self) -> None:
        if not self.application_valid or self.validation_errors:
            detail = ", ".join(self.validation_errors) or "result is not application-valid"
            raise CalibrationApplicationError(
                f"synthetic calibration result cannot be applied: {detail}"
            )

    def to_application_summary_row(self) -> dict[str, Any]:
        self.validate_for_application()
        row = {
            "run_id": self.run_id,
            "run_no": 1,
            "phase": self.phase,
            "phase_label": "Stream" if self.phase == "stream" else "Sweep",
            "timestamp": self.timestamp,
            "timestamp_display": self.timestamp,
            "pw_us": self.pw_us,
            "pressure_psi": self.pressure_psi,
            "mean_nL": self.measured_volume_nL,
            "cv_pct": None,
            "valid": True,
            "invalid_reason": None,
            "is_focus_run": True,
            "printing_mode": self.applied_printing_mode,
            "source_row_fingerprint": list(self.source_row_fingerprint),
            "synthetic": True,
            "synthetic_request_fingerprint": self.request_fingerprint,
            "synthetic_result_fingerprint": self.result_fingerprint,
            "synthetic_limitations": list(self.synthetic_limitations),
        }
        if self.applied_printing_mode == "stream":
            row.update(
                {
                    "predicted_stream_duration_us": None,
                    "flow_fit_status": "synthetic",
                    "tail_phase_status": "captured",
                    "warnings": [SYNTHETIC_STREAM_WARNING],
                }
            )
        return row

    def to_application_calibration_step(self) -> dict[str, Any]:
        self.validate_for_application()
        settings = {
            "print_width": self.pw_us,
            "print_pressure": self.pressure_psi,
        }
        if self.applied_printing_mode == "stream":
            result = {
                "condition": {
                    "print_pressure_psi": self.pressure_psi,
                    "print_pulse_width_us": self.pw_us,
                },
                "priors": {},
                "flow_phase": {"status": "synthetic", "fit_status": "synthetic"},
                "tail_phase": {
                    "status": "captured",
                    "evidence_source": "synthetic",
                },
                "predicted_stream_duration_us": None,
                "predicted_volume_nl": self.measured_volume_nL,
                "learned_flow_start_offset_us": None,
                "learned_tail_start_offset_us": None,
                "warnings": [SYNTHETIC_STREAM_WARNING],
                "synthetic": True,
                "synthetic_result_fingerprint": self.result_fingerprint,
                "synthetic_limitations": list(self.synthetic_limitations),
            }
        else:
            result = {
                "pressures": [
                    {
                        "pressure": self.pressure_psi,
                        "mean_volume": self.measured_volume_nL,
                        "cv_volume_percent": None,
                        "valid": True,
                        "invalid_reason": None,
                    }
                ],
                "synthetic": True,
                "synthetic_result_fingerprint": self.result_fingerprint,
                "synthetic_limitations": list(self.synthetic_limitations),
            }
        return {"timestamp": self.timestamp, "settings": settings, "result": result}

    @classmethod
    def from_dict(cls, payload: Any) -> "CalibrationGenerationResultV1":
        if not isinstance(payload, Mapping):
            raise CalibrationContractError("result: must be a JSON object")
        _require_exact_fields(payload, _RESULT_FIELDS, "result")
        source_fingerprint = payload["source_row_fingerprint"]
        validation_errors = payload["validation_errors"]
        limitations = payload["synthetic_limitations"]
        if not isinstance(source_fingerprint, list):
            raise CalibrationContractError(
                "result.source_row_fingerprint: must be an array"
            )
        if not isinstance(validation_errors, list):
            raise CalibrationContractError("result.validation_errors: must be an array")
        if not isinstance(limitations, list):
            raise CalibrationContractError("result.synthetic_limitations: must be an array")
        return cls(
            request_fingerprint=payload["request_fingerprint"],
            result_fingerprint=payload["result_fingerprint"],
            provider_version=payload["provider_version"],
            profile_id=payload["profile_id"],
            profile_version=payload["profile_version"],
            seed=payload["seed"],
            virtual_run_id=payload["virtual_run_id"],
            printer_head_id=payload["printer_head_id"],
            stock_id=payload["stock_id"],
            factor_name=payload["factor_name"],
            option_name=payload["option_name"],
            is_fill=payload["is_fill"],
            requested_mode=payload["requested_mode"],
            nominal_volume_nL=payload["nominal_volume_nL"],
            volume_variation_fraction=payload["volume_variation_fraction"],
            pressure_bounds_psi=tuple(payload["pressure_bounds_psi"]),
            pulse_width_bounds_us=tuple(payload["pulse_width_bounds_us"]),
            measured_volume_nL=payload["measured_volume_nL"],
            effective_volume_nL=payload["effective_volume_nL"],
            original_printing_mode=payload["original_printing_mode"],
            applied_printing_mode=payload["applied_printing_mode"],
            pw_us=payload["pw_us"],
            pressure_psi=payload["pressure_psi"],
            run_id=payload["run_id"],
            phase=payload["phase"],
            timestamp=payload["timestamp"],
            source_row_fingerprint=tuple(source_fingerprint),
            application_valid=payload["application_valid"],
            validation_errors=tuple(validation_errors),
            synthetic_limitations=tuple(limitations),
            schema_id=payload["schema_id"],
            schema_version=payload["schema_version"],
        )


class SyntheticCalibrationProvider:
    """Pure deterministic provider backed by the frozen profile-v1 registry."""

    provider_version = SYNTHETIC_CALIBRATION_PROVIDER_VERSION

    def list_profiles(self) -> tuple[SyntheticCalibrationProfileV1, ...]:
        return _PROFILES

    def get_profile(self, profile_id: str, profile_version: int = PROFILE_VERSION) -> SyntheticCalibrationProfileV1:
        profile = _PROFILE_REGISTRY.get((profile_id, profile_version))
        if profile is None:
            raise CalibrationContractError(
                f"unsupported synthetic calibration profile: {profile_id!r} v{profile_version}"
            )
        return profile

    def generate(
        self, request: CalibrationGenerationRequestV1
    ) -> CalibrationGenerationResultV1:
        if not isinstance(request, CalibrationGenerationRequestV1):
            raise TypeError("request must be a CalibrationGenerationRequestV1")
        profile = self.get_profile(request.profile_id, request.profile_version)
        if (
            profile.required_requested_mode is not None
            and request.requested_mode != profile.required_requested_mode
        ):
            raise CalibrationContractError(
                f"profile {profile.profile_id!r} requires requested_mode "
                f"{profile.required_requested_mode!r}"
            )

        volume_lo, volume_hi = _volume_bounds(request)
        applied_mode = profile.applied_mode or request.requested_mode
        if profile.profile_id == "nominal_droplet" and volume_hi >= MODE_BOUNDARY_NL:
            raise CalibrationContractError(
                "nominal_droplet requires its full volume interval below 40 nL"
            )
        if profile.profile_id == "nominal_stream" and volume_lo < MODE_BOUNDARY_NL:
            raise CalibrationContractError(
                "nominal_stream requires its full volume interval at or above 40 nL"
            )
        if profile.profile_id == "droplet_to_stream" and volume_hi < MODE_BOUNDARY_NL:
            raise CalibrationContractError(
                "droplet_to_stream requires a volume interval that reaches 40 nL"
            )
        if profile.volume_strategy in {"low_boundary", "high_boundary"}:
            boundary_value = volume_lo if profile.volume_strategy == "low_boundary" else volume_hi
            if applied_mode == "droplet" and boundary_value >= MODE_BOUNDARY_NL:
                raise CalibrationContractError(
                    f"{profile.profile_id} produces a droplet result at or above 40 nL"
                )
            if applied_mode == "stream" and boundary_value < MODE_BOUNDARY_NL:
                raise CalibrationContractError(
                    f"{profile.profile_id} produces a stream result below 40 nL"
                )

        request_fingerprint = request.fingerprint
        rng = random.Random(int(request_fingerprint, 16))
        pressure_psi = round(
            rng.uniform(*request.pressure_bounds_psi),
            9,
        )
        pw_us = rng.randint(*request.pulse_width_bounds_us)

        if profile.volume_strategy == "missing":
            measured_volume_nL = None
        elif profile.volume_strategy == "low_boundary":
            measured_volume_nL = round(volume_lo, 9)
        elif profile.volume_strategy == "high_boundary":
            measured_volume_nL = round(volume_hi, 9)
        elif profile.volume_strategy == "outlier":
            increment = max(0.001, request.nominal_volume_nL * 0.01)
            measured_volume_nL = round(volume_hi + increment, 9)
        else:
            sample_lo = volume_lo
            if applied_mode == "stream":
                sample_lo = max(sample_lo, MODE_BOUNDARY_NL)
            measured_volume_nL = round(rng.uniform(sample_lo, volume_hi), 9)
        effective_volume_nL = measured_volume_nL
        phase = "stream" if applied_mode == "stream" else "sweep"
        timestamp = _virtual_timestamp(request_fingerprint)
        source_fingerprint = _source_row_fingerprint(
            run_id=request.virtual_run_id,
            phase=phase,
            timestamp=timestamp,
            pw_us=pw_us,
            pressure_psi=pressure_psi,
            measured_volume_nL=measured_volume_nL,
        )
        errors = _application_validation_errors(
            request=request,
            profile=profile,
            measured_volume_nL=measured_volume_nL,
            effective_volume_nL=effective_volume_nL,
            original_mode=request.requested_mode,
            applied_mode=applied_mode,
            pressure_psi=pressure_psi,
            pw_us=pw_us,
        )

        payload = {
            **request.to_dict(),
            "schema_id": CALIBRATION_RESULT_SCHEMA_ID,
            "request_fingerprint": request_fingerprint,
            "measured_volume_nL": measured_volume_nL,
            "effective_volume_nL": effective_volume_nL,
            "original_printing_mode": request.requested_mode,
            "applied_printing_mode": applied_mode,
            "pw_us": pw_us,
            "pressure_psi": pressure_psi,
            "run_id": request.virtual_run_id,
            "phase": phase,
            "timestamp": timestamp,
            "source_row_fingerprint": list(source_fingerprint),
            "application_valid": not errors,
            "validation_errors": list(errors),
            "synthetic_limitations": list(SYNTHETIC_LIMITATIONS),
        }
        payload["result_fingerprint"] = _canonical_sha256(payload)
        return CalibrationGenerationResultV1.from_dict(payload)


__all__ = [
    "CALIBRATION_REQUEST_SCHEMA_ID",
    "CALIBRATION_RESULT_SCHEMA_ID",
    "CALIBRATION_SCHEMA_VERSION",
    "SYNTHETIC_CALIBRATION_PROVIDER_VERSION",
    "CalibrationApplicationError",
    "CalibrationContractError",
    "CalibrationGenerationRequestV1",
    "CalibrationGenerationResultV1",
    "SyntheticCalibrationProfileV1",
    "SyntheticCalibrationProvider",
]
