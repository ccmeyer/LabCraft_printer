from __future__ import annotations

import json
import math
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ExecutionPlan import canonical_sha256


SCHEMA_NAME = "labcraft.execution_calibrations"
SCHEMA_VERSION = 2
CALIBRATION_RECORD_NAMESPACE = uuid.UUID("54945835-c76e-4ccf-94c4-9fa9a78e034a")
PRINTING_MODES = {"droplet", "stream"}

CALIBRATION_FIELDS = {
    "record_id",
    "stock_id",
    "printer_head_id",
    "factor_name",
    "option_name",
    "is_fill",
    "measured_volume_nL",
    "effective_volume_nL",
    "pw_us",
    "pressure_psi",
    "run_id",
    "phase",
    "timestamp",
    "source_row_fingerprint",
    "original_printing_mode",
    "applied_printing_mode",
    "printing_mode",
    "applied_design_volume_nL",
    "recorded_at",
    "recorded_at_utc",
    "result_id",
    "result_sha256",
    "process_run_id",
    "update_id",
}
CALIBRATION_FIELDS_V1 = CALIBRATION_FIELDS - {
    "result_id", "result_sha256", "process_run_id", "update_id"
}

MANUAL_CHECK_FIELDS = {
    "status", "source", "stock_id", "printer_head_id", "printing_mode",
    "factor_name", "option_name", "is_fill", "calibration_record_id",
    "applied_calibration_fingerprint", "applied_calibration_record",
    "previous_status", "trial_droplet_count", "trial_count", "operator_judgment",
    "notes", "bypass_reason", "recorded_at", "print_pulse_width_us",
    "refuel_pulse_width_us", "print_pressure_psi", "current_print_pressure_psi",
    "target_print_pressure_psi", "refuel_pressure_psi", "current_refuel_pressure_psi",
    "target_refuel_pressure_psi",
}
MANUAL_CHECK_REQUIRED_FIELDS = {
    "status", "source", "stock_id", "printer_head_id", "printing_mode",
    "factor_name", "option_name", "is_fill", "calibration_record_id",
    "applied_calibration_fingerprint", "applied_calibration_record",
    "previous_status", "recorded_at",
}
MANUAL_CHECK_STATUSES = {
    "unknown", "required", "deferred", "passed", "failed", "unclear", "bypassed"
}


def _require_exact_fields(payload: Mapping[str, Any], expected: set[str], path: str) -> None:
    missing = expected - set(payload)
    unknown = set(payload) - expected
    if missing:
        raise ValueError(f"{path}: missing required field(s): {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{path}: unknown field(s): {', '.join(sorted(unknown))}")


def _canonical_uuid(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path}: must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{path}: must be a valid UUID") from exc
    if str(parsed) != value:
        raise ValueError(f"{path}: must use canonical UUID form")
    return value


def _optional_number(value: Any, path: str, *, positive: bool = False) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}: must be numeric or null")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f"{path}: must be finite" + (" and positive" if positive else ""))
    return number


def _optional_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{path}: must be a string or null")
    return value


def _utc_timestamp(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{path}: must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{path}: must be a valid ISO-8601 UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{path}: must use UTC")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True)
class ExecutionCalibrationRecord:
    record_id: str
    stock_id: str
    printer_head_id: str
    factor_name: str
    option_name: str | None
    is_fill: bool
    measured_volume_nL: float | None
    effective_volume_nL: float
    pw_us: int | None
    pressure_psi: float | None
    run_id: str | None
    phase: str | None
    timestamp: str | None
    source_row_fingerprint: tuple[Any, ...] | None
    original_printing_mode: str
    applied_printing_mode: str
    printing_mode: str
    applied_design_volume_nL: float
    recorded_at: str
    recorded_at_utc: str
    result_id: str | None = None
    result_sha256: str | None = None
    process_run_id: str | None = None
    update_id: str | None = None

    def __post_init__(self) -> None:
        _canonical_uuid(self.record_id, "calibration.record_id")
        for field_name in ("stock_id", "printer_head_id", "factor_name", "recorded_at_utc"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"calibration.{field_name}: must be a nonempty string")
        _utc_timestamp(self.recorded_at_utc, "calibration.recorded_at_utc")
        _utc_timestamp(self.recorded_at, "calibration.recorded_at")
        if self.recorded_at != self.recorded_at_utc:
            raise ValueError("calibration.recorded_at must equal recorded_at_utc")
        if self.option_name is not None and not isinstance(self.option_name, str):
            raise ValueError("calibration.option_name: must be a string or null")
        if not isinstance(self.is_fill, bool):
            raise ValueError("calibration.is_fill: must be boolean")
        object.__setattr__(self, "measured_volume_nL", _optional_number(self.measured_volume_nL, "calibration.measured_volume_nL", positive=True))
        effective = _optional_number(self.effective_volume_nL, "calibration.effective_volume_nL", positive=True)
        object.__setattr__(self, "effective_volume_nL", effective)
        if self.pw_us is not None and (isinstance(self.pw_us, bool) or not isinstance(self.pw_us, int) or self.pw_us <= 0):
            raise ValueError("calibration.pw_us: must be a positive integer or null")
        object.__setattr__(self, "pressure_psi", _optional_number(self.pressure_psi, "calibration.pressure_psi"))
        for name in ("run_id", "phase", "timestamp"):
            object.__setattr__(self, name, _optional_string(getattr(self, name), f"calibration.{name}"))
        for name in ("result_id", "result_sha256", "process_run_id", "update_id"):
            object.__setattr__(self, name, _optional_string(getattr(self, name), f"calibration.{name}"))
        if self.result_sha256 is not None and (
            len(self.result_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.result_sha256)
        ):
            raise ValueError("calibration.result_sha256: must be a lowercase SHA-256 or null")
        if self.source_row_fingerprint is not None and not isinstance(self.source_row_fingerprint, tuple):
            raise ValueError("calibration.source_row_fingerprint: must be an array or null")
        for name in ("original_printing_mode", "applied_printing_mode", "printing_mode"):
            if getattr(self, name) not in PRINTING_MODES:
                raise ValueError(f"calibration.{name}: must be droplet or stream")
        if self.printing_mode != self.applied_printing_mode:
            raise ValueError("calibration.printing_mode must equal applied_printing_mode")
        applied_volume = _optional_number(
            self.applied_design_volume_nL,
            "calibration.applied_design_volume_nL",
            positive=True,
        )
        object.__setattr__(self, "applied_design_volume_nL", applied_volume)
        if not math.isclose(applied_volume, effective, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(
                "calibration.applied_design_volume_nL must equal effective_volume_nL"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "stock_id": self.stock_id,
            "printer_head_id": self.printer_head_id,
            "factor_name": self.factor_name,
            "option_name": self.option_name,
            "is_fill": self.is_fill,
            "measured_volume_nL": self.measured_volume_nL,
            "effective_volume_nL": self.effective_volume_nL,
            "pw_us": self.pw_us,
            "pressure_psi": self.pressure_psi,
            "run_id": self.run_id,
            "phase": self.phase,
            "timestamp": self.timestamp,
            "source_row_fingerprint": list(self.source_row_fingerprint) if self.source_row_fingerprint is not None else None,
            "original_printing_mode": self.original_printing_mode,
            "applied_printing_mode": self.applied_printing_mode,
            "printing_mode": self.printing_mode,
            "applied_design_volume_nL": self.applied_design_volume_nL,
            "recorded_at": self.recorded_at,
            "recorded_at_utc": self.recorded_at_utc,
            "result_id": self.result_id,
            "result_sha256": self.result_sha256,
            "process_run_id": self.process_run_id,
            "update_id": self.update_id,
        }

    @classmethod
    def from_dict(cls, payload: Any, *, schema_version: int = SCHEMA_VERSION) -> "ExecutionCalibrationRecord":
        if not isinstance(payload, Mapping):
            raise ValueError("calibration record must be an object")
        expected = CALIBRATION_FIELDS_V1 if int(schema_version) == 1 else CALIBRATION_FIELDS
        _require_exact_fields(payload, expected, "calibration record")
        fingerprint = payload["source_row_fingerprint"]
        if fingerprint is not None and not isinstance(fingerprint, list):
            raise ValueError("calibration.source_row_fingerprint: must be an array or null")
        normalized = dict(payload)
        if int(schema_version) == 1:
            normalized.update({
                "result_id": None,
                "result_sha256": None,
                "process_run_id": None,
                "update_id": None,
            })
        return cls(
            **{
                **normalized,
                "source_row_fingerprint": tuple(fingerprint) if fingerprint is not None else None,
            }
        )


def deterministic_calibration_record_id(plan_id: str, payload: Mapping[str, Any]) -> str:
    identity = {
        key: payload.get(key)
        for key in (
            "stock_id", "printer_head_id", "factor_name", "option_name", "is_fill",
            "measured_volume_nL", "effective_volume_nL", "pw_us", "pressure_psi",
            "run_id", "phase", "timestamp", "source_row_fingerprint",
            "original_printing_mode", "applied_printing_mode",
        )
    }
    return str(uuid.uuid5(CALIBRATION_RECORD_NAMESPACE, f"{plan_id}:{canonical_sha256(identity)}"))


@dataclass
class ExecutionCalibrationDocument:
    plan_id: str
    records: dict[str, ExecutionCalibrationRecord] = field(default_factory=dict)
    manual_refuel_checks: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _canonical_uuid(self.plan_id, "execution_calibrations.plan_id")
        for key, record in self.records.items():
            if key != record.record_id:
                raise ValueError("Calibration record key must equal record_id.")
            expected_id = deterministic_calibration_record_id(
                self.plan_id,
                record.to_dict(),
            )
            if record.record_id != expected_id:
                raise ValueError(
                    "Calibration record ID does not match its deterministic execution identity."
                )
        for key, record in self.manual_refuel_checks.items():
            if not isinstance(key, str) or not key or not isinstance(record, dict):
                raise ValueError("Manual-refuel checks must be keyed objects.")
            unknown = set(record) - MANUAL_CHECK_FIELDS
            missing = MANUAL_CHECK_REQUIRED_FIELDS - set(record)
            if missing:
                raise ValueError(
                    f"manual_refuel_checks.{key}: missing required field(s): {', '.join(sorted(missing))}"
                )
            if unknown:
                raise ValueError(
                    f"manual_refuel_checks.{key}: unknown field(s): {', '.join(sorted(unknown))}"
                )
            path = f"manual_refuel_checks.{key}"
            if record.get("status") not in MANUAL_CHECK_STATUSES:
                raise ValueError(f"{path}.status: invalid manual-refuel status")
            if record.get("previous_status") not in MANUAL_CHECK_STATUSES:
                raise ValueError(f"{path}.previous_status: invalid manual-refuel status")
            for name in ("source", "stock_id", "printer_head_id", "factor_name"):
                if not isinstance(record.get(name), str) or not record[name]:
                    raise ValueError(f"{path}.{name}: must be a nonempty string")
            if record.get("printing_mode") not in PRINTING_MODES:
                raise ValueError(f"{path}.printing_mode: must be droplet or stream")
            if not isinstance(record.get("option_name"), str):
                raise ValueError(f"{path}.option_name: must be a string")
            if not isinstance(record.get("is_fill"), bool):
                raise ValueError(f"{path}.is_fill: must be boolean")
            _canonical_uuid(record.get("calibration_record_id"), f"{path}.calibration_record_id")
            calibration_record_id = record["calibration_record_id"]
            calibration_record = self.records.get(calibration_record_id)
            if calibration_record is None:
                raise ValueError(f"{path}.calibration_record_id: references a missing record")
            if (
                calibration_record.stock_id != record.get("stock_id")
                or calibration_record.printer_head_id != record.get("printer_head_id")
            ):
                raise ValueError(
                    f"{path}.calibration_record_id: stock or printer-head identity differs"
                )
            _utc_timestamp(record.get("recorded_at"), f"{path}.recorded_at")
            if not isinstance(record.get("applied_calibration_fingerprint"), str):
                raise ValueError(f"{path}.applied_calibration_fingerprint: must be a string")
            if record.get("applied_calibration_record") is not None and not isinstance(
                record.get("applied_calibration_record"), Mapping
            ):
                raise ValueError(f"{path}.applied_calibration_record: must be an object or null")
            for name in ("trial_droplet_count", "trial_count", "print_pulse_width_us", "refuel_pulse_width_us"):
                value = record.get(name)
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, int) or value < 0
                ):
                    raise ValueError(f"{path}.{name}: must be a nonnegative integer or null")
            for name in (
                "print_pressure_psi", "current_print_pressure_psi", "target_print_pressure_psi",
                "refuel_pressure_psi", "current_refuel_pressure_psi", "target_refuel_pressure_psi",
            ):
                _optional_number(record.get(name), f"{path}.{name}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "records": {key: value.to_dict() for key, value in sorted(self.records.items())},
            "manual_refuel_checks": {
                key: value for key, value in sorted(self.manual_refuel_checks.items())
            },
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "ExecutionCalibrationDocument":
        if not isinstance(payload, Mapping):
            raise ValueError("execution_calibrations.json must contain an object")
        _require_exact_fields(
            payload,
            {"schema_name", "schema_version", "plan_id", "records", "manual_refuel_checks"},
            "execution_calibrations",
        )
        if payload["schema_name"] != SCHEMA_NAME or payload["schema_version"] not in {1, SCHEMA_VERSION}:
            raise ValueError("Unsupported execution-calibration schema name or version.")
        if not isinstance(payload["records"], Mapping) or not isinstance(payload["manual_refuel_checks"], Mapping):
            raise ValueError("Execution-calibration records and manual checks must be objects.")
        return cls(
            plan_id=payload["plan_id"],
            records={
                str(key): ExecutionCalibrationRecord.from_dict(
                    value, schema_version=int(payload["schema_version"])
                )
                for key, value in payload["records"].items()
            },
            manual_refuel_checks={
                str(key): dict(value) if isinstance(value, Mapping) else value
                for key, value in payload["manual_refuel_checks"].items()
            },
        )


def load_execution_calibrations(path: str | Path) -> ExecutionCalibrationDocument:
    with Path(path).open("r", encoding="utf-8") as handle:
        return ExecutionCalibrationDocument.from_dict(
            json.load(handle, object_pairs_hook=_reject_duplicate_keys)
        )


def save_execution_calibrations(path: str | Path, document: ExecutionCalibrationDocument) -> None:
    payload = document.to_dict()
    ExecutionCalibrationDocument.from_dict(payload)
    output = Path(path)
    if not output.parent.is_dir():
        raise OSError(f"Execution-calibration parent directory does not exist: {output.parent}")
    fd, temporary = tempfile.mkstemp(prefix="._tmp_", suffix=".json", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
