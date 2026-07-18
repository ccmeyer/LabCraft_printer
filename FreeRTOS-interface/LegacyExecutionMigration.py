from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ExecutionCalibrationStore import (
    ExecutionCalibrationDocument,
    ExecutionCalibrationRecord,
    MANUAL_CHECK_FIELDS,
    deterministic_calibration_record_id,
    save_execution_calibrations,
)
from ExecutionPlan import ProgressExecutionReference, save_execution_plan
from ExecutionPlanRevision import persist_immutable_revision
from LegacyExecutionPlan import (
    LegacyExecutionClassification,
    reconstruct_legacy_execution,
)


SCHEMA_NAME = "labcraft.legacy_execution_migration"
SCHEMA_VERSION = 1
HARDWARE_POLICY = "analysis_only"
MANIFEST_FILE_NAME = "legacy_migration.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NEW_FORMAT_NAMES = {
    "execution_plan.json",
    "execution_plan_revisions",
    "execution_calibrations.json",
    "execution_resume.json",
    MANIFEST_FILE_NAME,
}


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_utc(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{path}: must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{path}: invalid UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{path}: must use UTC")
    return value


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True)
class LegacyMigrationWarning:
    code: str
    message: str

    def __post_init__(self) -> None:
        for name in ("code", "message"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"migration warning {name} must be a nonempty trimmed string")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}

    @classmethod
    def from_dict(cls, payload: Any) -> "LegacyMigrationWarning":
        if not isinstance(payload, Mapping) or set(payload) != {"code", "message"}:
            raise ValueError("migration warnings must contain exactly code and message")
        return cls(code=payload["code"], message=payload["message"])


@dataclass(frozen=True)
class LegacyMigrationManifest:
    plan_id: str
    source_folder_name: str
    source_design_sha256: str
    source_file_sha256: dict[str, str]
    migrated_at_utc: str
    hardware_policy: str = HARDWARE_POLICY
    warnings: tuple[LegacyMigrationWarning, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.plan_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("legacy_migration.plan_id must be a UUID") from exc
        if str(parsed) != self.plan_id:
            raise ValueError("legacy_migration.plan_id must use canonical UUID form")
        if not isinstance(self.source_folder_name, str) or not self.source_folder_name.strip():
            raise ValueError("legacy_migration.source_folder_name must be nonempty")
        if not isinstance(self.source_design_sha256, str) or not _SHA256_RE.fullmatch(self.source_design_sha256):
            raise ValueError("legacy_migration.source_design_sha256 must be a SHA-256 digest")
        if not isinstance(self.source_file_sha256, dict) or not self.source_file_sha256:
            raise ValueError("legacy_migration.source_file_sha256 must be a nonempty object")
        normalized: dict[str, str] = {}
        for path, digest in self.source_file_sha256.items():
            if not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts:
                raise ValueError("legacy_migration source paths must be safe relative paths")
            if path in normalized:
                raise ValueError("legacy_migration contains a duplicate source path")
            if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
                raise ValueError(f"legacy_migration source hash is invalid for {path!r}")
            normalized[path] = digest
        object.__setattr__(self, "source_file_sha256", normalized)
        _require_utc(self.migrated_at_utc, "legacy_migration.migrated_at_utc")
        if self.hardware_policy != HARDWARE_POLICY:
            raise ValueError("legacy_migration.hardware_policy must be analysis_only")
        warnings = tuple(self.warnings)
        if any(not isinstance(item, LegacyMigrationWarning) for item in warnings):
            raise ValueError("legacy_migration.warnings must contain warning objects")
        object.__setattr__(self, "warnings", warnings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "source_folder_name": self.source_folder_name,
            "source_design_sha256": self.source_design_sha256,
            "source_file_sha256": dict(sorted(self.source_file_sha256.items())),
            "migrated_at_utc": self.migrated_at_utc,
            "hardware_policy": self.hardware_policy,
            "warnings": [item.to_dict() for item in self.warnings],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "LegacyMigrationManifest":
        fields = {
            "schema_name", "schema_version", "plan_id", "source_folder_name",
            "source_design_sha256", "source_file_sha256", "migrated_at_utc",
            "hardware_policy", "warnings",
        }
        if not isinstance(payload, Mapping):
            raise ValueError("legacy_migration.json must contain an object")
        missing = fields - set(payload)
        unknown = set(payload) - fields
        if missing:
            raise ValueError(f"legacy_migration.json missing field(s): {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(f"legacy_migration.json unknown field(s): {', '.join(sorted(unknown))}")
        if payload["schema_name"] != SCHEMA_NAME or payload["schema_version"] != SCHEMA_VERSION:
            raise ValueError("unsupported legacy-migration schema")
        if not isinstance(payload["warnings"], list):
            raise ValueError("legacy_migration.warnings must be an array")
        return cls(
            plan_id=payload["plan_id"],
            source_folder_name=payload["source_folder_name"],
            source_design_sha256=payload["source_design_sha256"],
            source_file_sha256=dict(payload["source_file_sha256"]),
            migrated_at_utc=payload["migrated_at_utc"],
            hardware_policy=payload["hardware_policy"],
            warnings=tuple(LegacyMigrationWarning.from_dict(item) for item in payload["warnings"]),
        )


@dataclass(frozen=True)
class LegacyMigrationResult:
    destination: Path
    manifest: LegacyMigrationManifest
    plan: Any


def load_legacy_migration_manifest(path: str | Path) -> LegacyMigrationManifest:
    with Path(path).open("r", encoding="utf-8") as handle:
        return LegacyMigrationManifest.from_dict(
            json.load(handle, object_pairs_hook=_reject_duplicates)
        )


def save_legacy_migration_manifest(path: str | Path, manifest: LegacyMigrationManifest) -> None:
    payload = manifest.to_dict()
    LegacyMigrationManifest.from_dict(payload)
    output = Path(path)
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


def hash_directory_files(directory: str | Path) -> dict[str, str]:
    root = Path(directory)
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def default_migration_destination(source_dir: str | Path, timestamp: datetime | None = None) -> Path:
    source = Path(source_dir)
    stamp = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return source.with_name(f"{source.name}-migrated-{stamp}")


def _check_cancel(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise RuntimeError("Legacy migration was canceled.")


def _normalized_utc(value: Any, fallback: str) -> str:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    return fallback


def _convert_legacy_calibrations(
    design: Mapping[str, Any], plan: Any, migrated_at: str
) -> tuple[Any, ExecutionCalibrationDocument | None, list[LegacyMigrationWarning]]:
    raw_container = design.get("applied_imaging_calibrations")
    raw_records = raw_container.get("records", {}) if isinstance(raw_container, Mapping) else {}
    if not isinstance(raw_records, Mapping):
        raw_records = {}
    records: dict[str, ExecutionCalibrationRecord] = {}
    stock_record_ids: dict[str, str] = {}
    warnings: list[LegacyMigrationWarning] = []
    revised_stocks = []
    for stock in plan.stocks:
        legacy_key = stock.calibration_record_key
        raw = raw_records.get(legacy_key) if legacy_key is not None else None
        head_id = stock.printer_head_id or (raw.get("printer_head_id") if isinstance(raw, Mapping) else None)
        if legacy_key is None:
            revised_stocks.append(stock)
            continue
        if not isinstance(raw, Mapping) or not head_id:
            revised_stocks.append(replace(stock, calibration_record_key=None))
            warnings.append(LegacyMigrationWarning(
                "legacy_calibration_not_convertible",
                f"Calibration evidence for stock {stock.stock_id} was incomplete and was not granted authority.",
            ))
            continue
        applied_mode = str(raw.get("applied_printing_mode") or raw.get("printing_mode") or stock.printing_mode)
        original_mode = str(raw.get("original_printing_mode") or applied_mode)
        if applied_mode not in {"droplet", "stream"} or original_mode not in {"droplet", "stream"}:
            revised_stocks.append(replace(stock, calibration_record_key=None))
            warnings.append(LegacyMigrationWarning(
                "legacy_calibration_not_convertible",
                f"Calibration evidence for stock {stock.stock_id} used an unsupported printing mode.",
            ))
            continue
        fingerprint = raw.get("source_row_fingerprint")
        if fingerprint is not None and not isinstance(fingerprint, (list, tuple)):
            fingerprint = None
        identity = {
            "stock_id": stock.stock_id,
            "printer_head_id": str(head_id),
            "factor_name": stock.factor_name,
            "option_name": stock.option_name,
            "is_fill": stock.units == "--",
            "measured_volume_nL": raw.get("measured_volume_nL"),
            "effective_volume_nL": stock.effective_volume_nL,
            "pw_us": int(round(float(raw["pw_us"]))) if raw.get("pw_us") not in (None, "") else None,
            "pressure_psi": float(raw["pressure_psi"]) if raw.get("pressure_psi") not in (None, "") else None,
            "run_id": None if raw.get("run_id") in (None, "") else str(raw.get("run_id")),
            "phase": None if raw.get("phase") in (None, "") else str(raw.get("phase")),
            "timestamp": None if raw.get("timestamp") in (None, "") else str(raw.get("timestamp")),
            "source_row_fingerprint": list(fingerprint) if fingerprint is not None else None,
            "original_printing_mode": original_mode,
            "applied_printing_mode": applied_mode,
        }
        try:
            record_id = deterministic_calibration_record_id(plan.plan_id, identity)
            recorded_at = _normalized_utc(raw.get("recorded_at"), migrated_at)
            record = ExecutionCalibrationRecord(
                record_id=record_id,
                stock_id=stock.stock_id,
                printer_head_id=str(head_id),
                factor_name=stock.factor_name,
                option_name=stock.option_name,
                is_fill=stock.units == "--",
                measured_volume_nL=(float(raw["measured_volume_nL"]) if raw.get("measured_volume_nL") not in (None, "") else None),
                effective_volume_nL=stock.effective_volume_nL,
                pw_us=identity["pw_us"],
                pressure_psi=identity["pressure_psi"],
                run_id=identity["run_id"],
                phase=identity["phase"],
                timestamp=identity["timestamp"],
                source_row_fingerprint=tuple(fingerprint) if fingerprint is not None else None,
                original_printing_mode=original_mode,
                applied_printing_mode=applied_mode,
                printing_mode=applied_mode,
                applied_design_volume_nL=stock.effective_volume_nL,
                recorded_at=recorded_at,
                recorded_at_utc=recorded_at,
            )
        except Exception:
            revised_stocks.append(replace(stock, calibration_record_key=None))
            warnings.append(LegacyMigrationWarning(
                "legacy_calibration_not_convertible",
                f"Calibration evidence for stock {stock.stock_id} could not be normalized safely.",
            ))
            continue
        records[record.record_id] = record
        stock_record_ids[stock.stock_id] = record.record_id
        revised_stocks.append(replace(
            stock,
            printer_head_id=record.printer_head_id,
            calibration_record_key=record.record_id,
        ))

    revised_plan = replace(plan, stocks=tuple(revised_stocks))
    if not records:
        return revised_plan, None, warnings

    manual_container = design.get("manual_refuel_checks")
    manual_raw = manual_container.get("records", {}) if isinstance(manual_container, Mapping) else {}
    if not isinstance(manual_raw, Mapping):
        manual_raw = {}
    manual: dict[str, dict[str, Any]] = {}
    allowed_status = {"unknown", "required", "deferred", "passed", "failed", "unclear", "bypassed"}
    for key, raw in manual_raw.items():
        if not isinstance(raw, Mapping):
            continue
        stock_id = str(raw.get("stock_id") or "")
        record_id = stock_record_ids.get(stock_id)
        record = records.get(record_id or "")
        if record is None or str(raw.get("printer_head_id") or record.printer_head_id) != record.printer_head_id:
            warnings.append(LegacyMigrationWarning(
                "legacy_manual_check_not_convertible",
                f"Manual-refuel evidence {key!s} did not reference a converted calibration record.",
            ))
            continue
        status = str(raw.get("status") or "unknown").lower()
        previous = str(raw.get("previous_status") or "unknown").lower()
        candidate: dict[str, Any] = {
            "status": status if status in allowed_status else "unknown",
            "source": str(raw.get("source") or "legacy_migration"),
            "stock_id": stock_id,
            "printer_head_id": record.printer_head_id,
            "printing_mode": record.printing_mode,
            "factor_name": record.factor_name,
            "option_name": record.option_name or "",
            "is_fill": record.is_fill,
            "calibration_record_id": record.record_id,
            "applied_calibration_fingerprint": str(raw.get("applied_calibration_fingerprint") or record.record_id),
            "applied_calibration_record": record.to_dict(),
            "previous_status": previous if previous in allowed_status else "unknown",
            "recorded_at": _normalized_utc(raw.get("recorded_at"), migrated_at),
        }
        for name in MANUAL_CHECK_FIELDS - set(candidate):
            if name in raw:
                candidate[name] = raw[name]
        try:
            probe = ExecutionCalibrationDocument(plan_id=plan.plan_id, records=records, manual_refuel_checks={str(key): candidate})
            manual[str(key)] = probe.manual_refuel_checks[str(key)]
        except Exception:
            warnings.append(LegacyMigrationWarning(
                "legacy_manual_check_not_convertible",
                f"Manual-refuel evidence {key!s} could not be normalized safely.",
            ))
    return revised_plan, ExecutionCalibrationDocument(plan.plan_id, records, manual), warnings


def migrate_legacy_execution_copy(
    source_dir: str | Path,
    destination: str | Path | None = None,
    *,
    timestamp_utc: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> LegacyMigrationResult:
    source = Path(source_dir).resolve()
    target = Path(destination).resolve() if destination is not None else default_migration_destination(source).resolve()
    if source == target:
        raise ValueError("Legacy migration requires a separate destination folder.")
    if source in target.parents:
        raise ValueError("Legacy migration destination must not be inside the source folder.")
    if target.exists():
        raise FileExistsError(f"Migration destination already exists: {target}")
    if not source.is_dir():
        raise FileNotFoundError(source)
    partial = sorted(name for name in _NEW_FORMAT_NAMES if (source / name).exists())
    if partial:
        raise RuntimeError(
            "Legacy migration refuses sources containing new-format artifacts: " + ", ".join(partial)
        )
    design_path = source / "experiment_design.json"
    with design_path.open("r", encoding="utf-8") as handle:
        design = json.load(handle)
    reconstruction = reconstruct_legacy_execution(source, design)
    if (
        reconstruction.classification is not LegacyExecutionClassification.RECORDED_EXECUTION
        or reconstruction.plan is None
        or any(issue.severity == "fatal" for issue in reconstruction.issues)
    ):
        raise RuntimeError("The recorded legacy execution could not be reconstructed without fatal errors.")

    before_hashes = hash_directory_files(source)
    migrated_at = timestamp_utc or utc_now_text()
    _require_utc(migrated_at, "migration timestamp")
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=parent)).resolve()
    if staging.parent != parent.resolve():
        raise RuntimeError("Migration staging directory escaped the destination parent.")
    try:
        _check_cancel(cancel_check)
        shutil.copytree(source, staging, dirs_exist_ok=True, copy_function=shutil.copy2)
        _check_cancel(cancel_check)

        plan, sidecar, conversion_warnings = _convert_legacy_calibrations(
            design, reconstruction.plan, migrated_at
        )
        save_execution_plan(staging / "execution_plan.json", plan)
        persist_immutable_revision(staging / "execution_plan_revisions", plan)
        if sidecar is not None:
            save_execution_calibrations(staging / "execution_calibrations.json", sidecar)

        source_progress = reconstruction.progress if isinstance(reconstruction.progress, Mapping) else {}
        progress: dict[str, Any] = {}
        for well in plan.wells:
            original = source_progress.get(well.well_id, {})
            original_reagents = original.get("reagents", {}) if isinstance(original, Mapping) else {}
            reagents = {}
            for dispense in well.dispenses:
                raw = original_reagents.get(dispense.stock_id, {}) if isinstance(original_reagents, Mapping) else {}
                try:
                    added = int(raw.get("added_droplets", 0) or 0) if isinstance(raw, Mapping) else 0
                except (TypeError, ValueError):
                    added = 0
                added = min(max(0, added), dispense.target_dispenses)
                reagents[dispense.stock_id] = {
                    "target_droplets": dispense.target_dispenses,
                    "added_droplets": added,
                }
            progress[well.well_id] = {
                "reaction_id": well.reaction_id,
                "reagents": reagents,
                "completed": all(
                    item["added_droplets"] >= item["target_droplets"]
                    for item in reagents.values()
                ),
            }
        progress["__plate__"] = {
            "name": plan.plate.name,
            "rows": plan.plate.rows,
            "columns": plan.plate.columns,
            "schema_version": 1,
        }
        progress["__execution__"] = ProgressExecutionReference(
            plan.plan_id, plan.plan_revision
        ).to_dict()
        progress_path = staging / "progress.json"
        fd, temporary = tempfile.mkstemp(prefix="._tmp_", suffix=".json", dir=staging)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(progress, handle, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, progress_path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

        warnings = [
            LegacyMigrationWarning(issue.code, issue.message)
            for issue in reconstruction.issues
            if issue.severity == "warning"
        ] + conversion_warnings
        manifest = LegacyMigrationManifest(
            plan_id=plan.plan_id,
            source_folder_name=source.name,
            source_design_sha256=plan.design_sha256,
            source_file_sha256=before_hashes,
            migrated_at_utc=migrated_at,
            warnings=tuple(warnings),
        )
        save_legacy_migration_manifest(staging / MANIFEST_FILE_NAME, manifest)
        _check_cancel(cancel_check)
        if hash_directory_files(source) != before_hashes:
            raise RuntimeError("The legacy source changed while it was being migrated.")

        from AuthoritativeExecutionLoad import inspect_authoritative_execution

        bundle = inspect_authoritative_execution(staging, design)
        if not bundle.valid or bundle.eligibility.status != "analysis_only":
            details = "; ".join(issue.message for issue in bundle.issues)
            raise RuntimeError(f"Migrated execution failed authoritative validation: {details}")
        os.replace(staging, target)
        return LegacyMigrationResult(target, manifest, plan)
    except Exception:
        if staging.exists() and staging.parent == parent.resolve():
            shutil.rmtree(staging)
        raise
