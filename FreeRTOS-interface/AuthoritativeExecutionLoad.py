from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from ExecutionCalibrationStore import (
    ExecutionCalibrationDocument,
    load_execution_calibrations,
)
from ExecutionPlan import (
    ExecutionPlan,
    ExecutionPlanState,
    ProgressExecutionReference,
    canonical_sha256,
    load_execution_plan,
)
from ExecutionPlanRevision import validate_revision_history
from ExecutionResumeStore import (
    ExecutionResumeDocument,
    load_execution_resume,
    progress_fingerprint,
)
from LegacyExecutionMigration import (
    MANIFEST_FILE_NAME,
    LegacyMigrationManifest,
    load_legacy_migration_manifest,
)


@dataclass(frozen=True)
class AuthoritativeExecutionIssue:
    severity: str
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResumeEligibility:
    status: str
    can_activate_runtime: bool
    can_start_hardware: bool
    can_resume_hardware: bool
    reason: str
    repairable_intent_ids: tuple[str, ...] = ()
    ambiguous_intent_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionRuntimeStockSpec:
    stock_id: str
    reagent_name: str
    concentration: float
    units: str
    printing_mode: str
    effective_volume_nL: float
    printer_head_id: str | None


@dataclass(frozen=True)
class ExecutionRuntimeWellSpec:
    well_id: str
    reaction_id: str
    targets: dict[str, int]
    added: dict[str, int]


@dataclass(frozen=True)
class ExecutionRuntimeSpec:
    plate_name: str
    plate_rows: int
    plate_columns: int
    stocks: tuple[ExecutionRuntimeStockSpec, ...]
    wells: tuple[ExecutionRuntimeWellSpec, ...]


@dataclass(frozen=True)
class AuthoritativeExecutionBundle:
    plan: ExecutionPlan | None
    history: tuple[ExecutionPlan, ...]
    progress_payload: dict[str, Any]
    progress_wells: dict[str, Any]
    calibrations: ExecutionCalibrationDocument | None
    resume: ExecutionResumeDocument | None
    eligibility: ExecutionResumeEligibility
    issues: tuple[AuthoritativeExecutionIssue, ...]
    migration_manifest: LegacyMigrationManifest | None = None

    @property
    def valid(self) -> bool:
        return self.plan is not None and not any(
            issue.severity == "fatal" for issue in self.issues
        )


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _integral(value: Any, path: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not float(value).is_integer()
        or int(value) < 0
    ):
        raise ValueError(f"{path} must be a nonnegative integer")
    return int(value)


def _validate_progress(plan: ExecutionPlan, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("progress.json must contain an object")
    reference = ProgressExecutionReference.from_dict(payload.get("__execution__"))
    if reference.plan_id != plan.plan_id or reference.plan_revision != plan.plan_revision:
        raise ValueError("progress.json does not reference the latest execution plan")
    plate = payload.get("__plate__")
    if not isinstance(plate, dict) or (
        plate.get("name") != plan.plate.name
        or _integral(plate.get("rows"), "progress.__plate__.rows") != plan.plate.rows
        or _integral(plate.get("columns"), "progress.__plate__.columns") != plan.plate.columns
    ):
        raise ValueError("progress.json plate metadata differs from the execution plan")
    wells = {str(key): value for key, value in payload.items() if not str(key).startswith("__")}
    if set(wells) != {well.well_id for well in plan.wells}:
        raise ValueError("progress.json well identities differ from the execution plan")
    reaction_ids = [well.reaction_id for well in plan.wells]
    if len(reaction_ids) != len(set(reaction_ids)):
        raise ValueError("Authoritative runtime loading requires unique reaction IDs")
    for well in plan.wells:
        entry = wells[well.well_id]
        if not isinstance(entry, dict) or set(entry) != {"reaction_id", "reagents", "completed"}:
            raise ValueError(f"progress well fields are invalid at {well.well_id}")
        if entry.get("reaction_id") != well.reaction_id:
            raise ValueError(f"progress reaction identity differs at {well.well_id}")
        reagents = entry.get("reagents")
        targets = {item.stock_id: item.target_dispenses for item in well.dispenses}
        if not isinstance(reagents, dict) or set(reagents) != set(targets):
            raise ValueError(f"progress stock identities differ at {well.well_id}")
        for stock_id, target in targets.items():
            details = reagents[stock_id]
            allowed_reagent_fields = {
                "target_droplets", "added_droplets", "name", "concentration", "units"
            }
            if (
                not isinstance(details, dict)
                or not {"target_droplets", "added_droplets"}.issubset(details)
                or set(details) - allowed_reagent_fields
            ):
                raise ValueError(f"progress reagent is invalid at {well.well_id}/{stock_id}")
            if _integral(details.get("target_droplets"), "target_droplets") != target:
                raise ValueError(f"progress target differs at {well.well_id}/{stock_id}")
            added = _integral(details.get("added_droplets", 0), "added_droplets")
            if added > target:
                raise ValueError(f"progress added count exceeds target at {well.well_id}/{stock_id}")
        completed = entry.get("completed")
        if not isinstance(completed, bool) or completed != all(
            _integral(details.get("added_droplets", 0), "added_droplets")
            >= targets[stock_id]
            for stock_id, details in reagents.items()
        ):
            raise ValueError(f"progress completion flag differs at {well.well_id}")
    return wells


def _progress_added(progress_wells: Mapping[str, Any], well_id: str, stock_id: str) -> int:
    return int(progress_wells[well_id]["reagents"][stock_id].get("added_droplets", 0) or 0)


def _eligibility(
    plan: ExecutionPlan,
    progress_wells: dict[str, Any],
    resume: ExecutionResumeDocument | None,
) -> ExecutionResumeEligibility:
    total_added = sum(
        int(details.get("added_droplets", 0) or 0)
        for well in progress_wells.values()
        for details in (well.get("reagents") or {}).values()
    )
    remaining = sum(
        max(
            0,
            int(details.get("target_droplets", 0) or 0)
            - int(details.get("added_droplets", 0) or 0),
        )
        for well in progress_wells.values()
        for details in (well.get("reagents") or {}).values()
    )
    if plan.state in {ExecutionPlanState.COMPLETED, ExecutionPlanState.ABORTED}:
        return ExecutionResumeEligibility(
            "analysis_only", False, False, False,
            f"Execution plan state is {plan.state.value}.",
        )
    if resume is None:
        if remaining == 0:
            return ExecutionResumeEligibility("complete", False, False, False, "No droplets remain.")
        if total_added == 0:
            return ExecutionResumeEligibility(
                "ready_to_start", True, True, False,
                "No progress has been printed; a clean checkpoint can be created on activation.",
            )
        return ExecutionResumeEligibility(
            "blocked_missing_checkpoint", False, False, False,
            "Positive progress exists without durable command-boundary evidence.",
        )
    if resume.plan_id != plan.plan_id or resume.plan_revision != plan.plan_revision:
        return ExecutionResumeEligibility(
            "blocked_checkpoint_reference", False, False, False,
            "Resume checkpoint references a different plan revision.",
        )
    pending = [intent for intent in resume.intents if intent.status == "pending"]
    repairable = []
    ambiguous = []
    for intent in pending:
        added = _progress_added(progress_wells, intent.well_id, intent.stock_id)
        if added >= intent.baseline_added + intent.commanded_droplets:
            repairable.append(intent.intent_id)
        else:
            ambiguous.append(intent.intent_id)
    if ambiguous:
        return ExecutionResumeEligibility(
            "blocked_ambiguous_intent", False, False, False,
            "One or more queued print intents cannot be proven complete.",
            tuple(repairable), tuple(ambiguous),
        )
    if repairable:
        return ExecutionResumeEligibility(
            "repairable_checkpoint", True, False, False,
            "Progress proves all pending intents completed; explicit activation can repair the checkpoint.",
            tuple(repairable), (),
        )
    if resume.progress_sha256 != progress_fingerprint(progress_wells):
        return ExecutionResumeEligibility(
            "blocked_checkpoint_progress", False, False, False,
            "Resume checkpoint progress fingerprint differs from progress.json.",
        )
    if remaining == 0:
        return ExecutionResumeEligibility("complete", False, False, False, "No droplets remain.")
    if total_added > 0:
        return ExecutionResumeEligibility(
            "ready_to_resume", True, False, True, "Execution is at a clean resume boundary."
        )
    return ExecutionResumeEligibility(
        "ready_to_start", True, True, False, "Execution is at a clean start boundary."
    )


def _validate_resume_contents(
    plan: ExecutionPlan,
    progress_wells: Mapping[str, Any],
    resume: ExecutionResumeDocument,
) -> None:
    well_lookup = {well.well_id: well for well in plan.wells}
    stock_ids = {stock.stock_id for stock in plan.stocks}
    for intent in resume.intents:
        well = well_lookup.get(intent.well_id)
        if well is None or well.reaction_id != intent.reaction_id:
            raise ValueError("execution_resume.json references an unknown well/reaction")
        targets = {item.stock_id: item.target_dispenses for item in well.dispenses}
        if intent.stock_id not in stock_ids or intent.stock_id not in targets:
            raise ValueError("execution_resume.json references an unknown well stock")
        if intent.baseline_added + intent.commanded_droplets > targets[intent.stock_id]:
            raise ValueError("execution_resume.json intent exceeds the frozen target")
        added = _progress_added(progress_wells, intent.well_id, intent.stock_id)
        if intent.status == "completed" and added < (
            intent.baseline_added + intent.commanded_droplets
        ):
            raise ValueError("completed execution intent is not reflected in progress.json")


def inspect_authoritative_execution(
    experiment_dir: str | os.PathLike[str],
    design_payload: Mapping[str, Any],
    *,
    plate_catalog: Mapping[str, tuple[int, int]] | None = None,
) -> AuthoritativeExecutionBundle:
    directory = Path(experiment_dir)
    issues: list[AuthoritativeExecutionIssue] = []
    plan = None
    history: tuple[ExecutionPlan, ...] = ()
    progress_payload: dict[str, Any] = {}
    progress_wells: dict[str, Any] = {}
    calibrations = None
    resume = None
    migration_manifest = None
    try:
        plan = load_execution_plan(directory / "execution_plan.json")
        if canonical_sha256(design_payload) != plan.design_sha256:
            raise ValueError("experiment_design.json does not match the execution-plan design hash")
        migration_path = directory / MANIFEST_FILE_NAME
        if migration_path.exists():
            migration_manifest = load_legacy_migration_manifest(migration_path)
            if migration_manifest.plan_id != plan.plan_id:
                raise ValueError("legacy_migration.json references a different plan")
            if migration_manifest.source_design_sha256 != plan.design_sha256:
                raise ValueError("legacy_migration.json design hash differs from the copied design")
        progress_payload = _load_json(directory / "progress.json")
        progress_wells = _validate_progress(plan, progress_payload)
        calibration_path = directory / "execution_calibrations.json"
        if calibration_path.exists():
            calibrations = load_execution_calibrations(calibration_path)
            if calibrations.plan_id != plan.plan_id:
                raise ValueError("execution_calibrations.json references a different plan")
        calibration_ids = set(calibrations.records) if calibrations is not None else set()
        history = validate_revision_history(
            directory / "execution_plan_revisions",
            latest_plan=plan,
            allow_nonprepared_initial=migration_manifest is not None,
            calibration_record_ids=calibration_ids,
        )
        if not history:
            raise ValueError("immutable execution-plan history is missing")
        referenced = {
            stock.calibration_record_key
            for revision in history
            for stock in revision.stocks
            if stock.calibration_record_key is not None
        }
        if referenced and calibrations is None:
            raise ValueError("execution calibration sidecar is missing")
        if calibrations is not None and referenced - set(calibrations.records):
            raise ValueError("execution plan references missing calibration records")
        if calibrations is not None:
            manual_references = {
                record.get("calibration_record_id")
                for record in calibrations.manual_refuel_checks.values()
            }
            if set(calibrations.records) - referenced - manual_references:
                raise ValueError("execution_calibrations.json contains an unreferenced calibration record")
        resume_path = directory / "execution_resume.json"
        if resume_path.exists():
            resume = load_execution_resume(resume_path)
            _validate_resume_contents(plan, progress_wells, resume)
        if plate_catalog is not None:
            dimensions = plate_catalog.get(plan.plate.name)
            if dimensions != (plan.plate.rows, plan.plate.columns):
                raise ValueError("current plate catalog does not match the saved execution plate")
    except Exception as exc:
        issues.append(
            AuthoritativeExecutionIssue("fatal", "authoritative_bundle_invalid", str(exc), {})
        )
    eligibility = (
        ExecutionResumeEligibility(
            "analysis_only", False, False, False,
            "This migrated legacy execution is permanently analysis-only.",
        )
        if plan is not None and not issues and migration_manifest is not None
        else _eligibility(plan, progress_wells, resume)
        if plan is not None and not issues
        else ExecutionResumeEligibility(
            "blocked", False, False, False,
            issues[0].message if issues else "Execution bundle is unavailable.",
        )
    )
    return AuthoritativeExecutionBundle(
        plan=plan,
        history=history,
        progress_payload=progress_payload,
        progress_wells=progress_wells,
        calibrations=calibrations,
        resume=resume,
        eligibility=eligibility,
        issues=tuple(issues),
        migration_manifest=migration_manifest,
    )


def reconcile_authoritative_execution_runtime(
    bundle: AuthoritativeExecutionBundle,
    *,
    progress_payload: Mapping[str, Any],
    resume: ExecutionResumeDocument,
) -> AuthoritativeExecutionBundle:
    """Revalidate mutable runtime state without rereading immutable bundle files."""
    if not bundle.valid or bundle.plan is None:
        raise ValueError("A valid authoritative execution bundle is required.")
    if bundle.migration_manifest is not None:
        raise ValueError("Migrated legacy executions cannot activate a mutable runtime.")
    progress_wells = _validate_progress(bundle.plan, progress_payload)
    _validate_resume_contents(bundle.plan, progress_wells, resume)
    eligibility = _eligibility(bundle.plan, progress_wells, resume)
    return replace(
        bundle,
        progress_payload=dict(progress_payload),
        progress_wells=progress_wells,
        resume=resume,
        eligibility=eligibility,
    )


def build_execution_runtime_spec(bundle: AuthoritativeExecutionBundle) -> ExecutionRuntimeSpec:
    if not bundle.valid or bundle.plan is None:
        raise ValueError("A valid authoritative execution bundle is required.")
    plan = bundle.plan
    stocks = tuple(
        ExecutionRuntimeStockSpec(
            stock_id=stock.stock_id,
            reagent_name=stock.reagent_name,
            concentration=stock.concentration,
            units=stock.units,
            printing_mode=stock.printing_mode,
            effective_volume_nL=stock.effective_volume_nL,
            printer_head_id=stock.printer_head_id,
        )
        for stock in plan.stocks
    )
    wells = []
    for well in plan.wells:
        progress_reagents = bundle.progress_wells[well.well_id]["reagents"]
        wells.append(
            ExecutionRuntimeWellSpec(
                well_id=well.well_id,
                reaction_id=well.reaction_id,
                targets={item.stock_id: item.target_dispenses for item in well.dispenses},
                added={
                    item.stock_id: int(progress_reagents[item.stock_id].get("added_droplets", 0) or 0)
                    for item in well.dispenses
                },
            )
        )
    return ExecutionRuntimeSpec(
        plate_name=plan.plate.name,
        plate_rows=plan.plate.rows,
        plate_columns=plan.plate.columns,
        stocks=stocks,
        wells=tuple(wells),
    )
