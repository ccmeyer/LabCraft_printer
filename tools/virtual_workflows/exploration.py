"""Typed deterministic plans for bounded prepared-editor exploration."""

from __future__ import annotations

import copy
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tools.virtual_workflows.editor_scenarios import (
    RENAME_FIXTURE_PATH,
    load_editor_prestart_rename_refinalize_fixture,
)


CAMPAIGN_ID = "editor_prepared_guard_v1"
GENERATOR_VERSION = "editor-prepared-guard-v1"
EXPLORATION_PLAN_SCHEMA_NAME = "labcraft.virtual_workflow_exploration_plan"
EXPLORATION_SCHEMA_VERSION = 1
FIXED_SEEDS = (1, 7, 19, 42, 101)
MAX_ACTIONS = 25
BASE_SCENARIO_ID = "experiment_editor_prestart_rename_refinalize_v1"


class ExplorationValidationError(ValueError):
    """Raised when a generated campaign or selection violates its contract."""


@dataclass(frozen=True)
class SequenceStep:
    action_id: str
    from_state: str
    to_state: str
    expected_outcome: str = "accepted"
    edit_variant: str | None = None

    def __post_init__(self) -> None:
        allowed_actions = {
            "editor.open_via_ui",
            "editor.rename_prepared_via_ui",
            "editor.edit_prepared_design_via_ui",
            "editor.regenerate_prepared_design_via_ui",
            "editor.refinalize_prepared_via_ui",
            "experiment.load_authoritative_via_ui",
        }
        if self.action_id not in allowed_actions:
            raise ExplorationValidationError("exploration action is unsupported")
        if self.expected_outcome not in {"accepted", "rejected_invalid"}:
            raise ExplorationValidationError("exploration outcome is unsupported")
        if self.edit_variant not in {
            None,
            "intermediate",
            "intermediate_invalid",
            "intermediate_recovery",
            "final",
            "final_invalid",
        }:
            raise ExplorationValidationError("exploration edit variant is unsupported")
        if not self.from_state or not self.to_state:
            raise ExplorationValidationError("exploration states must be non-empty")

    def normalized(self, ordinal: int) -> dict[str, Any]:
        return {
            "ordinal": ordinal,
            "action_id": self.action_id,
            "interaction_surface": "ui",
            "from_state": self.from_state,
            "to_state": self.to_state,
            "expected_outcome": self.expected_outcome,
            "edit_variant": self.edit_variant,
        }


@dataclass(frozen=True)
class ExplorationSequence:
    sequence_id: str
    seed: int
    sequence_class: str
    rename_first: bool
    edit_cycles: int
    steps: tuple[SequenceStep, ...]

    def __post_init__(self) -> None:
        if self.sequence_class not in {"legal", "illegal"}:
            raise ExplorationValidationError("sequence class is unsupported")
        if self.sequence_id != f"seed_{self.seed}_{self.sequence_class}":
            raise ExplorationValidationError("sequence ID disagrees with its seed/class")
        if self.seed not in FIXED_SEEDS or self.edit_cycles not in {1, 2}:
            raise ExplorationValidationError("sequence seed or edit count is unsupported")
        rejection_count = sum(
            step.expected_outcome == "rejected_invalid" for step in self.steps
        )
        if rejection_count != (1 if self.sequence_class == "illegal" else 0):
            raise ExplorationValidationError("sequence rejection cardinality drifted")
        if len(self.steps) > MAX_ACTIONS:
            raise ExplorationValidationError("sequence exceeds the action cap")
        if not self.steps or self.steps[-1].to_state != "prepared_reloaded_inactive":
            raise ExplorationValidationError("sequence terminal state drifted")
        for previous, current in zip(self.steps, self.steps[1:]):
            if previous.to_state != current.from_state:
                raise ExplorationValidationError("sequence transitions are discontinuous")

    def normalized(self) -> dict[str, Any]:
        return {
            "sequence_id": self.sequence_id,
            "seed": self.seed,
            "sequence_class": self.sequence_class,
            "rename_first": self.rename_first,
            "edit_cycles": self.edit_cycles,
            "step_count": len(self.steps),
            "steps": [step.normalized(index) for index, step in enumerate(self.steps, 1)],
        }


def _canonical_json(value: Mapping[str, Any] | list[Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Mapping[str, Any] | list[Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _state(*, dirty: bool, generated: bool, renamed: bool) -> str:
    design = "dirty" if dirty else "generated" if generated else "clean"
    return f"prepared_open_{design}_{'renamed' if renamed else 'original'}"


def generate_sequence(seed: int, sequence_class: str) -> ExplorationSequence:
    rng = random.Random(int(seed))
    rename_first = rng.choice((False, True))
    edit_cycles = rng.choice((1, 2))
    sequence_id = f"seed_{int(seed)}_{sequence_class}"
    steps: list[SequenceStep] = []
    state = "prepared_closed_original"

    def add(action_id: str, target: str, **values: Any) -> None:
        nonlocal state
        steps.append(SequenceStep(action_id, state, target, **values))
        state = target

    add("editor.open_via_ui", _state(dirty=False, generated=False, renamed=False))
    renamed = False
    if rename_first:
        renamed = True
        add("editor.rename_prepared_via_ui", _state(dirty=False, generated=False, renamed=True))
    add(
        "editor.edit_prepared_design_via_ui",
        _state(dirty=True, generated=False, renamed=renamed),
        edit_variant=(
            "intermediate_invalid"
            if sequence_class == "illegal" and edit_cycles == 2
            else "final_invalid"
            if sequence_class == "illegal"
            else "intermediate"
            if edit_cycles == 2
            else "final"
        ),
    )
    if not rename_first:
        renamed = True
        add("editor.rename_prepared_via_ui", _state(dirty=True, generated=False, renamed=True))
    if sequence_class == "illegal":
        add(
            "editor.refinalize_prepared_via_ui",
            state,
            expected_outcome="rejected_invalid",
        )
        add(
            "editor.edit_prepared_design_via_ui",
            _state(dirty=True, generated=False, renamed=True),
            edit_variant=(
                "intermediate_recovery" if edit_cycles == 2 else "final"
            ),
        )
    add(
        "editor.regenerate_prepared_design_via_ui",
        _state(dirty=False, generated=True, renamed=True),
    )
    if edit_cycles == 2:
        add(
            "editor.edit_prepared_design_via_ui",
            _state(dirty=True, generated=False, renamed=True),
            edit_variant="final",
        )
        add(
            "editor.regenerate_prepared_design_via_ui",
            _state(dirty=False, generated=True, renamed=True),
        )
    add("editor.refinalize_prepared_via_ui", "prepared_closed_refinalized")
    add("experiment.load_authoritative_via_ui", "prepared_reloaded_inactive")
    return ExplorationSequence(
        sequence_id,
        int(seed),
        sequence_class,
        rename_first,
        edit_cycles,
        tuple(steps),
    )


SEQUENCES = tuple(
    generate_sequence(seed, sequence_class)
    for seed in FIXED_SEEDS
    for sequence_class in ("legal", "illegal")
)


def _validate_catalog() -> None:
    if len(SEQUENCES) != 10 or len({item.sequence_id for item in SEQUENCES}) != 10:
        raise ExplorationValidationError("campaign must contain ten unique sequences")
    if {item.rename_first for item in SEQUENCES} != {False, True}:
        raise ExplorationValidationError("campaign rename-order coverage drifted")
    if {item.edit_cycles for item in SEQUENCES} != {1, 2}:
        raise ExplorationValidationError("campaign edit-cycle coverage drifted")


_validate_catalog()


def sequence_ids(campaign_id: str = CAMPAIGN_ID) -> tuple[str, ...]:
    from tools.virtual_workflows import exploration_m13

    if campaign_id == exploration_m13.CAMPAIGN_ID:
        return exploration_m13.sequence_ids()
    if campaign_id != CAMPAIGN_ID:
        raise ExplorationValidationError(f"unsupported campaign: {campaign_id!r}")
    return tuple(item.sequence_id for item in SEQUENCES)


def get_sequence(campaign_id: str, sequence_id: str) -> ExplorationSequence:
    from tools.virtual_workflows import exploration_m13

    if campaign_id == exploration_m13.CAMPAIGN_ID:
        return exploration_m13.get_sequence(sequence_id)  # type: ignore[return-value]
    if campaign_id != CAMPAIGN_ID:
        raise ExplorationValidationError(f"unsupported campaign: {campaign_id!r}")
    matches = [item for item in SEQUENCES if item.sequence_id == sequence_id]
    if len(matches) != 1:
        raise ExplorationValidationError(f"unsupported sequence: {sequence_id!r}")
    return matches[0]


def normalized_catalog(campaign_id: str = CAMPAIGN_ID) -> dict[str, Any]:
    from tools.virtual_workflows import exploration_m13

    if campaign_id == exploration_m13.CAMPAIGN_ID:
        return exploration_m13.normalized_frozen_catalog()
    if campaign_id != CAMPAIGN_ID:
        raise ExplorationValidationError(f"unsupported campaign: {campaign_id!r}")
    return {
        "campaign_id": CAMPAIGN_ID,
        "generator_version": GENERATOR_VERSION,
        "base_scenario_id": BASE_SCENARIO_ID,
        "fixed_seeds": list(FIXED_SEEDS),
        "maximum_actions": MAX_ACTIONS,
        "sequences": [item.normalized() for item in SEQUENCES],
    }


def catalog_sha256(campaign_id: str = CAMPAIGN_ID) -> str:
    from tools.virtual_workflows import exploration_m13

    if campaign_id == exploration_m13.CAMPAIGN_ID:
        return exploration_m13.catalog_sha256()
    return _sha256_json(normalized_catalog(campaign_id))


def resolve_exploration_plan(
    campaign_id: str,
    *,
    sequence_id: str | None = None,
    timeout_seconds: float = 60.0,
    execution_authorized: bool = True,
    seed_tier: str = "frozen",
    diagnostic_seeds: tuple[int, ...] = (),
) -> dict[str, Any]:
    from tools.virtual_workflows import exploration_m13

    if campaign_id == exploration_m13.CAMPAIGN_ID:
        return exploration_m13.resolve_plan(
            sequence_id=sequence_id,
            timeout_seconds=timeout_seconds,
            execution_authorized=execution_authorized,
            seed_tier=seed_tier,
            diagnostic_seeds=diagnostic_seeds,
        )
    if campaign_id != CAMPAIGN_ID:
        raise ExplorationValidationError(f"unsupported campaign: {campaign_id!r}")
    if seed_tier != "frozen" or diagnostic_seeds:
        raise ExplorationValidationError(
            "Milestone 8 exploration does not support diagnostic seed tiers"
        )
    selected = (get_sequence(campaign_id, sequence_id),) if sequence_id else SEQUENCES
    return {
        "schema_name": EXPLORATION_PLAN_SCHEMA_NAME,
        "schema_version": EXPLORATION_SCHEMA_VERSION,
        "campaign": {
            "id": CAMPAIGN_ID,
            "generator_version": GENERATOR_VERSION,
            "catalog_sha256": catalog_sha256(),
            "base_scenario_id": BASE_SCENARIO_ID,
        },
        "platform": "windows_sil",
        "timeout_seconds": float(timeout_seconds),
        "sequence_count": len(selected),
        "sequences": [
            {
                "order": index,
                "sequence": item.normalized(),
                "sequence_sha256": _sha256_json(item.normalized()),
            }
            for index, item in enumerate(selected, 1)
        ],
        "execution_authorized": bool(execution_authorized),
    }


def build_sequence_fixture(
    campaign_id: str, sequence_id: str
) -> tuple[dict[str, Any], Path]:
    from tools.virtual_workflows import exploration_m13

    if campaign_id == exploration_m13.CAMPAIGN_ID:
        raise ExplorationValidationError(
            "Milestone 13 generated fixtures are unavailable in Slice 13.1"
        )
    sequence = get_sequence(campaign_id, sequence_id)
    fixture = copy.deepcopy(load_editor_prestart_rename_refinalize_fixture())
    fixture["fixture_id"] = f"{campaign_id}__{sequence_id}"
    fixture["exploration"] = {
        "campaign_id": campaign_id,
        "generator_version": GENERATOR_VERSION,
        "catalog_sha256": catalog_sha256(),
        "sequence": sequence.normalized(),
        "sequence_sha256": _sha256_json(sequence.normalized()),
        "intermediate_printed_volume_tolerance_nL": 1.0,
        "maximum_actions": MAX_ACTIONS,
    }
    return fixture, Path(RENAME_FIXTURE_PATH).resolve()


def exploration_catalog() -> dict[str, Any]:
    from tools.virtual_workflows.exploration_m13 import catalog_descriptor

    return {
        "schema_name": "labcraft.virtual_workflow_exploration_catalog",
        "schema_version": EXPLORATION_SCHEMA_VERSION,
        "campaigns": [
            {
                "id": CAMPAIGN_ID,
                "generator_version": GENERATOR_VERSION,
                "fixed_seeds": list(FIXED_SEEDS),
                "sequence_ids": list(sequence_ids()),
                "sequence_count": len(SEQUENCES),
                "maximum_actions": MAX_ACTIONS,
                "catalog_sha256": catalog_sha256(),
                "platform": "windows_sil",
                "execution": "manual_on_demand",
            },
            catalog_descriptor(),
        ],
    }


__all__ = [
    "BASE_SCENARIO_ID",
    "CAMPAIGN_ID",
    "EXPLORATION_PLAN_SCHEMA_NAME",
    "EXPLORATION_SCHEMA_VERSION",
    "FIXED_SEEDS",
    "GENERATOR_VERSION",
    "MAX_ACTIONS",
    "SEQUENCES",
    "ExplorationSequence",
    "ExplorationValidationError",
    "SequenceStep",
    "build_sequence_fixture",
    "catalog_sha256",
    "exploration_catalog",
    "generate_sequence",
    "get_sequence",
    "normalized_catalog",
    "resolve_exploration_plan",
    "sequence_ids",
]
