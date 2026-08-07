"""Read-only, JSON-safe evidence for authoritative execution lifecycles."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_value(value: str) -> Any:
    return json.loads(value)


@dataclass(frozen=True)
class FileEvidence:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class DirectoryEvidence:
    """Deterministic immutable inventory of one directory tree."""

    root: str
    files: tuple[FileEvidence, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.files)

    @property
    def hashes(self) -> dict[str, str]:
        return {item.path: item.sha256 for item in self.files}

    def rich_inventory(self) -> dict[str, dict[str, Any]]:
        return {
            item.path: {
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in self.files
        }

    def editor_projection(self) -> dict[str, Any]:
        return {"inventory": list(self.paths), "sha256": self.hashes}


@dataclass(frozen=True)
class ComparisonEvidence:
    checks: tuple[tuple[str, bool], ...]
    values_json: str = "{}"

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(name for name, passed in self.checks if not passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks": dict(self.checks),
            "failed_checks": list(self.failed_checks),
            **dict(_json_value(self.values_json)),
        }


@dataclass(frozen=True)
class AuthoritativeBundleSnapshot:
    """Immutable facts captured from one authoritative execution bundle."""

    experiment_dir: str
    design_path: str
    design_json: str
    design_sha256: str
    plan_json: str
    plan_id: str
    plan_revision: int
    plan_state: str
    plan_lock_reason: str | None
    plan_design_sha256: str
    plan_well_ids: tuple[str, ...]
    plan_assignments: tuple[tuple[str, str], ...]
    plan_stock_modes: tuple[str, ...]
    target_printed_volume_nl: float
    final_reaction_volume_nl: float
    history_json: tuple[str, ...]
    bundle_valid: bool
    eligibility_status: str
    eligibility_json: str
    progress_schema_version: int
    progress_plan_id: str
    progress_plan_revision: int
    progress_targets: tuple[tuple[str, int], ...]
    total_added_droplets: int
    completed_well_ids: tuple[str, ...]
    resume_present: bool
    resume_state: str | None
    resume_plan_id: str | None
    resume_plan_revision: int | None
    resume_intent_count: int
    calibration_present: bool
    calibration_record_count: int
    manual_refuel_check_count: int
    runtime_active: bool
    runtime_assignments: tuple[tuple[str, str], ...]
    key_rows_json: str
    concentration_rows_json: str
    audit_rows_json: str
    directory: DirectoryEvidence
    experiment_directories: tuple[str, ...]
    staging_directories: tuple[str, ...]
    current_plan_paths: tuple[str, ...]

    @property
    def design(self) -> dict[str, Any]:
        return dict(_json_value(self.design_json))

    @property
    def plan(self) -> dict[str, Any]:
        return dict(_json_value(self.plan_json))

    @property
    def history(self) -> list[dict[str, Any]]:
        return [dict(_json_value(value)) for value in self.history_json]

    @property
    def eligibility(self) -> dict[str, Any]:
        return dict(_json_value(self.eligibility_json))

    @property
    def key_rows(self) -> dict[str, dict[str, str]]:
        return dict(_json_value(self.key_rows_json))

    @property
    def concentration_rows(self) -> dict[str, dict[str, str]]:
        return dict(_json_value(self.concentration_rows_json))

    @property
    def audit_rows(self) -> list[dict[str, Any]]:
        return list(_json_value(self.audit_rows_json))

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self.design.get("metadata") or {})

    @property
    def factors(self) -> list[dict[str, Any]]:
        return list(self.design.get("factors") or [])

    @property
    def assignments(self) -> dict[str, str]:
        return dict(self.runtime_assignments)

    @property
    def expected_assignments(self) -> dict[str, str]:
        return dict(self.plan_assignments)

    @property
    def targets_by_well(self) -> dict[str, int]:
        return dict(self.progress_targets)

    @property
    def core_file_hashes(self) -> dict[str, str]:
        required = {
            "experiment_design.json",
            "execution_plan.json",
            "progress.json",
            "key.csv",
            "concentration_key.csv",
        }
        return {
            path: digest
            for path, digest in self.directory.hashes.items()
            if path in required or path.startswith("execution_plan_revisions/")
        }

    @property
    def history_matches_current(self) -> bool:
        return bool(self.history_json) and self.history_json[-1] == self.plan_json

    def prepared_evidence(self) -> dict[str, Any]:
        return {
            "experiment_dir": self.experiment_dir,
            "design_path": self.design_path,
            "plan_id": self.plan_id,
            "plan_revision": self.plan_revision,
            "plan_state": self.plan_state,
            "eligibility_status": self.eligibility_status,
            "well_ids": list(self.plan_well_ids),
            "runtime_assignments": self.assignments,
            "total_added_droplets": self.total_added_droplets,
            "resume_present": self.resume_present,
            "design_sha256": self.design_sha256,
        }


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv_rows(path: str | Path) -> dict[str, dict[str, str]]:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "Well ID" not in rows[0]:
        raise RuntimeError(f"{source.name} has no Well ID rows")
    return {
        str(row.pop("Well ID")): {
            str(key): str(value) for key, value in row.items()
        }
        for row in rows
    }


def read_audit_rows(path: str | Path | None) -> list[dict[str, Any]]:
    source = Path(path) if path else None
    if source is None or not source.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def runtime_assignments(model: Any) -> dict[str, str]:
    return {
        well.well_id: well.get_assigned_reaction().unique_id
        for well in model.well_plate.get_all_wells()
        if well.get_assigned_reaction() is not None
    }


def snapshot_directory(root: str | Path) -> DirectoryEvidence:
    directory = Path(root).resolve()
    files = tuple(
        FileEvidence(
            path=path.relative_to(directory).as_posix(),
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    )
    return DirectoryEvidence(root=str(directory), files=files)


def editor_directory_snapshot(root: str | Path) -> dict[str, Any]:
    return snapshot_directory(root).editor_projection()


def rich_file_inventory(root: str | Path) -> dict[str, dict[str, Any]]:
    return snapshot_directory(root).rich_inventory()


def read_model_audit_rows(experiment_model: Any) -> list[dict[str, Any]]:
    return read_audit_rows(
        getattr(experiment_model, "experiment_audit_file_path", None)
    )


def check_evidence(
    checks: Mapping[str, bool],
    **values: Any,
) -> dict[str, Any]:
    return ComparisonEvidence(
        checks=tuple((str(name), bool(passed)) for name, passed in checks.items()),
        values_json=_canonical_json(values),
    ).to_dict()


def compare_directories(
    before: DirectoryEvidence,
    after: DirectoryEvidence,
    *,
    allowed_changed_paths: Iterable[str] = (),
) -> ComparisonEvidence:
    before_rich = before.rich_inventory()
    after_rich = after.rich_inventory()
    all_paths = set(before_rich) | set(after_rich)
    changed = tuple(
        sorted(path for path in all_paths if before_rich.get(path) != after_rich.get(path))
    )
    allowed = frozenset(str(path) for path in allowed_changed_paths)
    disallowed = tuple(sorted(set(changed) - allowed))
    return ComparisonEvidence(
        checks=(
            ("inventory_unchanged", before.paths == after.paths),
            ("files_byte_identical", before.hashes == after.hashes),
            ("only_allowlisted_files_changed", not disallowed),
        ),
        values_json=_canonical_json(
            {
                "changed_paths": list(changed),
                "disallowed_changed_paths": list(disallowed),
            }
        ),
    )


def capture_authoritative_bundle(
    context: Any,
    *,
    experiments_root: str | Path | None = None,
) -> AuthoritativeBundleSnapshot:
    """Capture authoritative facts without activating or repairing execution."""

    from AuthoritativeExecutionLoad import inspect_authoritative_execution
    from ExecutionCalibrationStore import load_execution_calibrations
    from ExecutionPlan import canonical_sha256
    from ExecutionProgressStore import decode_execution_progress
    from ExecutionResumeStore import load_execution_resume

    experiment_model = context.experiment_model
    experiment_dir = Path(experiment_model.experiment_dir_path).resolve()
    design_path = Path(experiment_model.experiment_file_path).resolve()
    design = json.loads(design_path.read_text(encoding="utf-8"))
    plan = experiment_model.get_execution_plan_snapshot()
    bundle = inspect_authoritative_execution(experiment_dir, design)
    decoded = decode_execution_progress(plan, bundle.progress_payload)

    total_added = sum(
        int(details["added_droplets"])
        for well in decoded.progress_wells.values()
        for details in well["reagents"].values()
    )
    completed = tuple(
        well_id
        for well_id, details in decoded.progress_wells.items()
        if bool(details["completed"])
    )
    targets = tuple(
        (
            well_id,
            sum(
                int(details["target_droplets"])
                for details in entry["reagents"].values()
            ),
        )
        for well_id, entry in decoded.progress_wells.items()
    )

    resume_path = Path(experiment_model.execution_resume_file_path)
    resume = load_execution_resume(resume_path) if resume_path.is_file() else None
    calibration_path = experiment_dir / "execution_calibrations.json"
    calibration = (
        load_execution_calibrations(calibration_path)
        if calibration_path.is_file()
        else None
    )
    root = Path(experiments_root or experiment_dir.parent).resolve()
    directories = tuple(
        sorted(
            path.name
            for path in root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        )
    )
    staging = tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob(".*.staging-*")
            if path.is_dir()
        )
    )
    current_plans = tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("execution_plan.json")
            if "superseded_prepared_execution_plans" not in path.parts
        )
    )
    key_path = Path(experiment_model.key_file_path)
    concentration_path = Path(experiment_model.concentration_key_file_path)
    design_json = _canonical_json(design)
    plan_json = _canonical_json(plan.to_dict())
    eligibility = experiment_model.get_execution_resume_eligibility() or {
        "status": bundle.eligibility.status
    }
    return AuthoritativeBundleSnapshot(
        experiment_dir=str(experiment_dir),
        design_path=str(design_path),
        design_json=design_json,
        design_sha256=canonical_sha256(design),
        plan_json=plan_json,
        plan_id=str(plan.plan_id),
        plan_revision=int(plan.plan_revision),
        plan_state=str(plan.state.value),
        plan_lock_reason=plan.lock_reason,
        plan_design_sha256=str(plan.design_sha256),
        plan_well_ids=tuple(well.well_id for well in plan.wells),
        plan_assignments=tuple(
            (well.well_id, well.reaction_id) for well in plan.wells
        ),
        plan_stock_modes=tuple(stock.printing_mode for stock in plan.stocks),
        target_printed_volume_nl=float(
            plan.volume_basis.target_printed_volume_nL
        ),
        final_reaction_volume_nl=float(
            plan.volume_basis.final_reaction_volume_nL
        ),
        history_json=tuple(_canonical_json(item.to_dict()) for item in bundle.history),
        bundle_valid=bool(bundle.valid),
        eligibility_status=str(bundle.eligibility.status),
        eligibility_json=_canonical_json(eligibility),
        progress_schema_version=int(decoded.schema_version),
        progress_plan_id=str(decoded.reference.plan_id),
        progress_plan_revision=int(decoded.reference.plan_revision),
        progress_targets=targets,
        total_added_droplets=total_added,
        completed_well_ids=completed,
        resume_present=resume is not None,
        resume_state=str(resume.state) if resume is not None else None,
        resume_plan_id=str(resume.plan_id) if resume is not None else None,
        resume_plan_revision=(
            int(resume.plan_revision) if resume is not None else None
        ),
        resume_intent_count=len(resume.intents) if resume is not None else 0,
        calibration_present=calibration is not None,
        calibration_record_count=(len(calibration.records) if calibration else 0),
        manual_refuel_check_count=(
            len(calibration.manual_refuel_checks) if calibration else 0
        ),
        runtime_active=bool(
            experiment_model.is_authoritative_execution_runtime_active()
        ),
        runtime_assignments=tuple(sorted(runtime_assignments(context.model).items())),
        key_rows_json=_canonical_json(read_csv_rows(key_path)),
        concentration_rows_json=_canonical_json(read_csv_rows(concentration_path)),
        audit_rows_json=_canonical_json(
            read_audit_rows(experiment_model.experiment_audit_file_path)
        ),
        directory=snapshot_directory(experiment_dir),
        experiment_directories=directories,
        staging_directories=staging,
        current_plan_paths=current_plans,
    )


__all__ = [
    "AuthoritativeBundleSnapshot",
    "ComparisonEvidence",
    "DirectoryEvidence",
    "FileEvidence",
    "capture_authoritative_bundle",
    "check_evidence",
    "compare_directories",
    "editor_directory_snapshot",
    "read_audit_rows",
    "read_csv_rows",
    "read_model_audit_rows",
    "rich_file_inventory",
    "runtime_assignments",
    "sha256_file",
    "snapshot_directory",
]
