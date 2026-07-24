from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from ExecutionPlan import ExecutionPlanState
from ExecutionProgressStore import has_positive_execution_progress
from LegacyExecutionPlan import (
    LegacyExecutionClassification,
    reconstruct_legacy_execution,
)


class ExecutionArtifactClassification(str, Enum):
    UNFINALIZED_DESIGN = "unfinalized_design"
    PREPARED_EXECUTION = "prepared_execution"
    RECORDED_LEGACY_EXECUTION = "recorded_legacy_execution"
    AUTHORITATIVE_EXECUTION = "authoritative_execution"
    INVALID_AUTHORITATIVE_EXECUTION = "invalid_authoritative_execution"


@dataclass(frozen=True)
class ExecutionArtifactPolicy:
    classification: ExecutionArtifactClassification
    has_recorded_droplets: bool
    can_clear_progress: bool
    can_reset_array_progress: bool
    reason: str
    issues: tuple[str, ...] = field(default_factory=tuple)


NEW_FORMAT_ARTIFACTS = (
    "execution_plan.json",
    "execution_plan_revisions",
    "execution_calibrations.json",
    "execution_resume.json",
    "legacy_migration.json",
)


def _load_design(directory: Path, design_payload: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if design_payload is not None:
        if not isinstance(design_payload, Mapping):
            raise ValueError("experiment_design.json must contain an object")
        return design_payload
    with (directory / "experiment_design.json").open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("experiment_design.json must contain an object")
    return payload


def _has_positive_progress(directory: Path) -> bool:
    path = directory / "progress.json"
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return False
    if not isinstance(payload, Mapping):
        return False
    try:
        if "schema_name" in payload or "schema_version" in payload:
            return has_positive_execution_progress(payload)
    except ValueError:
        return False
    for well_id, well in payload.items():
        if str(well_id).startswith("__") or not isinstance(well, Mapping):
            continue
        reagents = well.get("reagents")
        if not isinstance(reagents, Mapping):
            continue
        for details in reagents.values():
            if not isinstance(details, Mapping):
                continue
            try:
                if int(details.get("added_droplets", 0) or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def inspect_execution_artifacts(
    experiment_dir: str | Path,
    design_payload: Mapping[str, Any] | None = None,
) -> ExecutionArtifactPolicy:
    """Classify an experiment folder without changing it."""
    directory = Path(experiment_dir)
    positive = _has_positive_progress(directory)
    new_artifacts = [name for name in NEW_FORMAT_ARTIFACTS if (directory / name).exists()]
    if new_artifacts:
        try:
            design = _load_design(directory, design_payload)
            from AuthoritativeExecutionLoad import inspect_authoritative_execution

            bundle = inspect_authoritative_execution(directory, design)
            if not bundle.valid or bundle.plan is None:
                messages = tuple(issue.message for issue in bundle.issues)
                return ExecutionArtifactPolicy(
                    ExecutionArtifactClassification.INVALID_AUTHORITATIVE_EXECUTION,
                    positive,
                    False,
                    False,
                    "New-format execution artifacts are present but do not form a valid authoritative bundle.",
                    messages,
                )
            classification = (
                ExecutionArtifactClassification.PREPARED_EXECUTION
                if bundle.plan.state is ExecutionPlanState.PREPARED
                else ExecutionArtifactClassification.AUTHORITATIVE_EXECUTION
            )
            return ExecutionArtifactPolicy(
                classification,
                positive,
                False,
                False,
                "A finalized execution is immutable; create an editable copy instead.",
            )
        except Exception as exc:
            return ExecutionArtifactPolicy(
                ExecutionArtifactClassification.INVALID_AUTHORITATIVE_EXECUTION,
                positive,
                False,
                False,
                "New-format execution artifacts are incomplete or invalid.",
                (str(exc),),
            )

    try:
        design = _load_design(directory, design_payload)
        reconstruction = reconstruct_legacy_execution(directory, design)
    except Exception as exc:
        return ExecutionArtifactPolicy(
            ExecutionArtifactClassification.UNFINALIZED_DESIGN,
            positive,
            not positive,
            not positive,
            "Saved positive dispense counts cannot be erased." if positive else "No execution artifacts were found.",
            (str(exc),),
        )
    if reconstruction.classification is LegacyExecutionClassification.RECORDED_EXECUTION:
        return ExecutionArtifactPolicy(
            ExecutionArtifactClassification.RECORDED_LEGACY_EXECUTION,
            positive,
            False,
            False,
            "Recorded legacy execution evidence is immutable; create an editable copy instead.",
            tuple(issue.message for issue in reconstruction.issues),
        )
    return ExecutionArtifactPolicy(
        ExecutionArtifactClassification.UNFINALIZED_DESIGN,
        positive,
        not positive,
        not positive,
        "Saved positive dispense counts cannot be erased." if positive else "The design has no recorded execution evidence.",
    )
