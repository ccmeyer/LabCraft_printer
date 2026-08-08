"""Independent typed truth for the curated experiment-design SIL matrix.

This module deliberately imports no application Model, View, optimizer,
assignment, or execution-plan implementation. Expected values are frozen data;
future journeys may compare application observations with them but must not
derive them from production behavior at assertion time.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


EXPERIMENT_DESIGN_MATRIX_ID = "experiment_design_pairwise_v1"
EXPERIMENT_DESIGN_BASE_SCENARIO_ID = "experiment_editor_create_finalize_v1"
EXPERIMENT_DESIGN_JOURNEY_FAMILY = "experiment_design"
EXPERIMENT_DESIGN_EXECUTABLE_CASE_IDS = (
    "single_reagent_control",
    "multi_reagent_seed_4321",
)
REFERENCE_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "experiment_editor_create_finalize_v1.json"
)
REFERENCE_FIXTURE_SHA256 = (
    "fc2bdf34fa5a7d8a9e851ace7a099aa8e05c61c2d0cd075b620d69937f8bfc45"
)


class ExperimentDesignCaseError(ValueError):
    """Raised when curated experiment-design truth is malformed or ambiguous."""


def _canonical_json(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _identity(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExperimentDesignCaseError(f"{label} must be non-empty")
    return text


def _decimal_text(
    value: Any,
    label: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> str:
    text = _identity(value, label)
    try:
        decimal = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ExperimentDesignCaseError(f"{label} must be a finite decimal") from exc
    if not decimal.is_finite():
        raise ExperimentDesignCaseError(f"{label} must be finite")
    if positive and decimal <= 0:
        raise ExperimentDesignCaseError(f"{label} must be positive")
    if nonnegative and decimal < 0:
        raise ExperimentDesignCaseError(f"{label} must be non-negative")
    return text


def _unique(values: Iterable[str], label: str) -> tuple[str, ...]:
    normalized = tuple(_identity(value, label) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ExperimentDesignCaseError(f"{label} values must be unique")
    return normalized


@dataclass(frozen=True)
class DesignExperimentInput:
    name: str
    plate_name: str
    replicates: int
    selected_well_ids: tuple[str, ...]
    excluded_well_ids: tuple[str, ...]
    printed_volume_nL: str
    final_volume_nL: str
    printed_volume_tolerance_nL: str = "0"
    randomize_assignments: bool = False
    random_seed: int | None = None
    allow_two_stock_solutions: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identity(self.name, "experiment name"))
        object.__setattr__(
            self, "plate_name", _identity(self.plate_name, "experiment plate")
        )
        if not isinstance(self.replicates, int) or isinstance(self.replicates, bool):
            raise ExperimentDesignCaseError("experiment replicates must be an integer")
        if self.replicates <= 0:
            raise ExperimentDesignCaseError("experiment replicates must be positive")
        wells = _unique(self.selected_well_ids, "selected well")
        excluded = _unique(self.excluded_well_ids, "excluded well")
        if not wells:
            raise ExperimentDesignCaseError("selected wells must be non-empty")
        if not set(excluded).issubset(wells):
            raise ExperimentDesignCaseError(
                "excluded wells must be members of the selected well set"
            )
        object.__setattr__(self, "selected_well_ids", wells)
        object.__setattr__(self, "excluded_well_ids", excluded)
        for field, label, positive, nonnegative in (
            ("printed_volume_nL", "printed volume", True, False),
            ("final_volume_nL", "final volume", True, False),
            ("printed_volume_tolerance_nL", "printed-volume tolerance", False, True),
        ):
            object.__setattr__(
                self,
                field,
                _decimal_text(
                    getattr(self, field),
                    label,
                    positive=positive,
                    nonnegative=nonnegative,
                ),
            )
        if not isinstance(self.randomize_assignments, bool):
            raise ExperimentDesignCaseError("randomize_assignments must be boolean")
        if not isinstance(self.allow_two_stock_solutions, bool):
            raise ExperimentDesignCaseError(
                "allow_two_stock_solutions must be boolean"
            )
        if self.randomize_assignments:
            if (
                not isinstance(self.random_seed, int)
                or isinstance(self.random_seed, bool)
                or self.random_seed < 0
            ):
                raise ExperimentDesignCaseError(
                    "randomized experiments require a non-negative integer seed"
                )
        elif self.random_seed is not None:
            raise ExperimentDesignCaseError(
                "non-randomized experiments may not retain a random seed"
            )

    def normalized(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "plate_name": self.plate_name,
            "replicates": self.replicates,
            "selected_well_ids": list(self.selected_well_ids),
            "excluded_well_ids": list(self.excluded_well_ids),
            "printed_volume_nL": self.printed_volume_nL,
            "final_volume_nL": self.final_volume_nL,
            "printed_volume_tolerance_nL": self.printed_volume_tolerance_nL,
            "randomize_assignments": self.randomize_assignments,
            "random_seed": self.random_seed,
            "allow_two_stock_solutions": self.allow_two_stock_solutions,
        }


@dataclass(frozen=True)
class DesignReagentInput:
    stock_label: str
    group: str
    printing_mode: str
    starting_concentration: str
    targets: tuple[str, ...]
    units: str
    droplet_volume_nL: str
    fixed_stock_concentration: str | None = None
    max_stock_concentration: str | None = None

    def __post_init__(self) -> None:
        for field, label in (
            ("stock_label", "reagent stock label"),
            ("group", "reagent group"),
            ("units", "reagent units"),
        ):
            object.__setattr__(self, field, _identity(getattr(self, field), label))
        if self.printing_mode not in {"droplet", "stream"}:
            raise ExperimentDesignCaseError("reagent printing mode is unsupported")
        object.__setattr__(
            self,
            "starting_concentration",
            _decimal_text(
                self.starting_concentration,
                "starting concentration",
                nonnegative=True,
            ),
        )
        targets = tuple(
            _decimal_text(value, "reagent target", nonnegative=True)
            for value in self.targets
        )
        if not targets or len(set(targets)) != len(targets):
            raise ExperimentDesignCaseError(
                "reagent targets must be non-empty and unique"
            )
        object.__setattr__(self, "targets", targets)
        object.__setattr__(
            self,
            "droplet_volume_nL",
            _decimal_text(self.droplet_volume_nL, "droplet volume", positive=True),
        )
        for field, label in (
            ("fixed_stock_concentration", "fixed stock concentration"),
            ("max_stock_concentration", "maximum stock concentration"),
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(
                    self,
                    field,
                    _decimal_text(value, label, positive=True),
                )

    def normalized(self) -> dict[str, Any]:
        return {
            "stock_label": self.stock_label,
            "group": self.group,
            "printing_mode": self.printing_mode,
            "starting_concentration": self.starting_concentration,
            "targets": list(self.targets),
            "units": self.units,
            "droplet_volume_nL": self.droplet_volume_nL,
            "fixed_stock_concentration": self.fixed_stock_concentration,
            "max_stock_concentration": self.max_stock_concentration,
        }


@dataclass(frozen=True)
class DesignOptimizationAttempt:
    allow_two_stock_solutions: bool
    expected_outcome: str
    expected_dialog_title: str | None = None
    expected_message_fragments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.allow_two_stock_solutions, bool):
            raise ExperimentDesignCaseError("optimization allow-two value is invalid")
        if self.expected_outcome not in {"generated", "rejected"}:
            raise ExperimentDesignCaseError("optimization outcome is unsupported")
        fragments = tuple(
            _identity(value, "optimization message fragment")
            for value in self.expected_message_fragments
        )
        object.__setattr__(self, "expected_message_fragments", fragments)
        if self.expected_outcome == "rejected":
            object.__setattr__(
                self,
                "expected_dialog_title",
                _identity(self.expected_dialog_title, "optimization dialog title"),
            )
            if not fragments:
                raise ExperimentDesignCaseError(
                    "rejected optimization requires a message fragment"
                )
        elif self.expected_dialog_title is not None or fragments:
            raise ExperimentDesignCaseError(
                "successful optimization may not define rejection evidence"
            )

    def normalized(self) -> dict[str, Any]:
        return {
            "allow_two_stock_solutions": self.allow_two_stock_solutions,
            "expected_outcome": self.expected_outcome,
            "expected_dialog_title": self.expected_dialog_title,
            "expected_message_fragments": list(self.expected_message_fragments),
        }


@dataclass(frozen=True)
class ExpectedDesignStock:
    stock_id: str
    reagent_name: str
    concentration: str
    units: str
    printing_mode: str = "droplet"
    role: str = "non_fill"

    def __post_init__(self) -> None:
        for field, label in (
            ("stock_id", "expected stock ID"),
            ("reagent_name", "expected stock reagent"),
            ("units", "expected stock units"),
        ):
            object.__setattr__(self, field, _identity(getattr(self, field), label))
        object.__setattr__(
            self,
            "concentration",
            _decimal_text(self.concentration, "expected stock concentration", positive=True),
        )
        if self.printing_mode not in {"droplet", "stream"}:
            raise ExperimentDesignCaseError("expected stock mode is unsupported")
        if self.role not in {"non_fill", "fill"}:
            raise ExperimentDesignCaseError("expected stock role is unsupported")

    def normalized(self) -> dict[str, Any]:
        return {
            "stock_id": self.stock_id,
            "reagent_name": self.reagent_name,
            "concentration": self.concentration,
            "units": self.units,
            "printing_mode": self.printing_mode,
            "role": self.role,
        }


@dataclass(frozen=True)
class ExpectedDesignReaction:
    reaction_id: str
    replicate: int
    targets: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reaction_id", _identity(self.reaction_id, "reaction ID")
        )
        if not isinstance(self.replicate, int) or isinstance(self.replicate, bool):
            raise ExperimentDesignCaseError("reaction replicate must be an integer")
        if self.replicate <= 0:
            raise ExperimentDesignCaseError("reaction replicate must be positive")
        normalized: list[tuple[str, str]] = []
        for reagent, value in self.targets:
            normalized.append(
                (
                    _identity(reagent, "reaction reagent"),
                    _decimal_text(value, "reaction target", nonnegative=True),
                )
            )
        if not normalized or len({name for name, _ in normalized}) != len(normalized):
            raise ExperimentDesignCaseError(
                "reaction targets must identify unique non-empty reagents"
            )
        object.__setattr__(self, "targets", tuple(sorted(normalized)))

    def normalized(self) -> dict[str, Any]:
        return {
            "reaction_id": self.reaction_id,
            "replicate": self.replicate,
            "targets": [
                {"reagent": reagent, "target": target}
                for reagent, target in self.targets
            ],
        }

    def multiset_member(self) -> dict[str, Any]:
        return {
            "replicate": self.replicate,
            "targets": [
                {"reagent": reagent, "target": target}
                for reagent, target in self.targets
            ],
        }


@dataclass(frozen=True)
class ExpectedWellAssignment:
    well_id: str
    reaction_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "well_id", _identity(self.well_id, "assignment well"))
        object.__setattr__(
            self,
            "reaction_id",
            _identity(self.reaction_id, "assignment reaction"),
        )

    def normalized(self) -> dict[str, str]:
        return {"well_id": self.well_id, "reaction_id": self.reaction_id}


@dataclass(frozen=True)
class ExpectedStockWellCount:
    stock_id: str
    well_id: str
    target_droplets: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_id", _identity(self.stock_id, "count stock"))
        object.__setattr__(self, "well_id", _identity(self.well_id, "count well"))
        if (
            not isinstance(self.target_droplets, int)
            or isinstance(self.target_droplets, bool)
            or self.target_droplets <= 0
        ):
            raise ExperimentDesignCaseError(
                "expected target droplets must be a positive integer"
            )

    def normalized(self) -> dict[str, Any]:
        return {
            "stock_id": self.stock_id,
            "well_id": self.well_id,
            "target_droplets": self.target_droplets,
        }


@dataclass(frozen=True)
class ExpectedDesignOutcome:
    terminal: str
    reaction_count: int
    stocks: tuple[ExpectedDesignStock, ...] = ()
    reactions: tuple[ExpectedDesignReaction, ...] = ()
    assignments: tuple[ExpectedWellAssignment, ...] = ()
    stock_well_counts: tuple[ExpectedStockWellCount, ...] = ()
    capacity_required: int | None = None
    capacity_available: int | None = None
    dialog_title: str | None = None
    message_fragments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.terminal not in {
            "prepared",
            "capacity_rejected",
            "formulation_rejected",
        }:
            raise ExperimentDesignCaseError("design terminal is unsupported")
        if (
            not isinstance(self.reaction_count, int)
            or isinstance(self.reaction_count, bool)
            or self.reaction_count <= 0
        ):
            raise ExperimentDesignCaseError(
                "expected reaction count must be a positive integer"
            )
        for label, values, key in (
            ("expected stock", self.stocks, lambda item: item.stock_id),
            ("expected reaction", self.reactions, lambda item: item.reaction_id),
            ("expected assignment", self.assignments, lambda item: item.well_id),
            (
                "expected count",
                self.stock_well_counts,
                lambda item: (item.stock_id, item.well_id),
            ),
        ):
            keys = [key(item) for item in values]
            if len(set(keys)) != len(keys):
                raise ExperimentDesignCaseError(f"{label} identities must be unique")
        fragments = tuple(
            _identity(value, "expected message fragment")
            for value in self.message_fragments
        )
        object.__setattr__(self, "message_fragments", fragments)
        if self.terminal == "prepared":
            if len(self.reactions) != self.reaction_count:
                raise ExperimentDesignCaseError(
                    "prepared reaction cardinality differs from its oracle"
                )
            if len(self.assignments) != self.reaction_count:
                raise ExperimentDesignCaseError(
                    "prepared assignment cardinality differs from its oracle"
                )
            if not self.stocks or not self.stock_well_counts:
                raise ExperimentDesignCaseError(
                    "prepared outcomes require stock and count truth"
                )
            if self.dialog_title is not None or fragments:
                raise ExperimentDesignCaseError(
                    "prepared outcomes may not define terminal warning evidence"
                )
        else:
            if self.stocks or self.reactions or self.assignments or self.stock_well_counts:
                raise ExperimentDesignCaseError(
                    "rejected outcomes may not claim authoritative design output"
                )
            object.__setattr__(
                self,
                "dialog_title",
                _identity(self.dialog_title, "rejection dialog title"),
            )
            if not fragments:
                raise ExperimentDesignCaseError(
                    "rejected outcomes require message evidence"
                )
        if (self.capacity_required is None) != (self.capacity_available is None):
            raise ExperimentDesignCaseError(
                "capacity required and available must be provided together"
            )
        for value in (self.capacity_required, self.capacity_available):
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ExperimentDesignCaseError("capacity values must be non-negative")
        if self.terminal == "capacity_rejected" and not (
            self.capacity_required is not None
            and self.capacity_available is not None
            and self.capacity_required > self.capacity_available
        ):
            raise ExperimentDesignCaseError(
                "capacity rejection requires required greater than available"
            )

    def reaction_multiset_sha256(self) -> str | None:
        if not self.reactions:
            return None
        rows = sorted(
            (reaction.multiset_member() for reaction in self.reactions),
            key=_canonical_json,
        )
        return _sha256_json(rows)

    def assignment_sha256(self) -> str | None:
        if not self.assignments:
            return None
        return _sha256_json([item.normalized() for item in self.assignments])

    def normalized(self) -> dict[str, Any]:
        return {
            "terminal": self.terminal,
            "reaction_count": self.reaction_count,
            "stocks": [value.normalized() for value in self.stocks],
            "reactions": [value.normalized() for value in self.reactions],
            "reaction_multiset_sha256": self.reaction_multiset_sha256(),
            "assignments": [value.normalized() for value in self.assignments],
            "assignment_sha256": self.assignment_sha256(),
            "stock_well_counts": [
                value.normalized() for value in self.stock_well_counts
            ],
            "capacity_required": self.capacity_required,
            "capacity_available": self.capacity_available,
            "dialog_title": self.dialog_title,
            "message_fragments": list(self.message_fragments),
        }


@dataclass(frozen=True)
class ExperimentDesignCase:
    case_id: str
    experiment: DesignExperimentInput
    reagents: tuple[DesignReagentInput, ...]
    optimization_attempts: tuple[DesignOptimizationAttempt, ...]
    expected: ExpectedDesignOutcome
    coverage_tags: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _identity(self.case_id, "case ID"))
        if not self.reagents:
            raise ExperimentDesignCaseError("design case requires a reagent")
        reagent_names = [item.stock_label for item in self.reagents]
        if len(set(reagent_names)) != len(reagent_names):
            raise ExperimentDesignCaseError("design reagent labels must be unique")
        if not self.optimization_attempts:
            raise ExperimentDesignCaseError(
                "design case requires an optimization attempt"
            )
        tags = frozenset(_identity(value, "coverage tag") for value in self.coverage_tags)
        unknown = sorted(tags - RECOGNIZED_COVERAGE_TAGS)
        if unknown:
            raise ExperimentDesignCaseError(
                f"design case contains unknown coverage tags: {unknown}"
            )
        object.__setattr__(self, "coverage_tags", tags)
        if self.expected.terminal == "prepared":
            if self.optimization_attempts[-1].expected_outcome != "generated":
                raise ExperimentDesignCaseError(
                    "prepared case must end with a generated optimization"
                )
            assigned_wells = {row.well_id for row in self.expected.assignments}
            allowed_wells = set(self.experiment.selected_well_ids) - set(
                self.experiment.excluded_well_ids
            )
            if not assigned_wells.issubset(allowed_wells):
                raise ExperimentDesignCaseError(
                    "expected assignments include unavailable wells"
                )
            reaction_ids = {row.reaction_id for row in self.expected.reactions}
            if {row.reaction_id for row in self.expected.assignments} != reaction_ids:
                raise ExperimentDesignCaseError(
                    "expected assignments do not cover every reaction exactly"
                )
            stock_ids = {row.stock_id for row in self.expected.stocks}
            if any(
                row.stock_id not in stock_ids or row.well_id not in assigned_wells
                for row in self.expected.stock_well_counts
            ):
                raise ExperimentDesignCaseError(
                    "expected count rows differ from stock/well membership"
                )
        elif self.optimization_attempts[-1].expected_outcome != "rejected" and (
            self.expected.terminal == "formulation_rejected"
        ):
            raise ExperimentDesignCaseError(
                "formulation rejection must end with a rejected optimization"
            )

    def normalized(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "experiment": self.experiment.normalized(),
            "reagents": [value.normalized() for value in self.reagents],
            "optimization_attempts": [
                value.normalized() for value in self.optimization_attempts
            ],
            "expected": self.expected.normalized(),
            "coverage_tags": sorted(self.coverage_tags),
        }

    def sha256(self) -> str:
        return _sha256_json(self.normalized())


RECOGNIZED_COVERAGE_TAGS = frozenset(
    {
        "reagents:single",
        "reagents:multiple",
        "targets:single",
        "targets:multiple",
        "stock:fixed_one",
        "stock:optimized_one",
        "stock:optimized_two",
        "stock:fixed_exceeds_max",
        "assignment:natural",
        "assignment:randomized",
        "assignment:custom",
        "wells:excluded",
        "capacity:below",
        "capacity:exact",
        "capacity:over",
        "replicates:one",
        "replicates:multiple",
        "terminal:prepared",
        "terminal:capacity_rejected",
        "terminal:formulation_rejected",
        "transition:one_rejected_two_succeeds",
        "comparison:same_seed_replay",
        "comparison:different_seed",
        "evidence:reload_runtime",
        "evidence:no_authoritative_mutation",
    }
)

REQUIRED_PAIRWISE_INTERACTIONS: tuple[tuple[str, str], ...] = (
    ("reagents:multiple", "targets:multiple"),
    ("reagents:multiple", "assignment:randomized"),
    ("targets:multiple", "replicates:multiple"),
    ("stock:optimized_one", "terminal:prepared"),
    ("stock:optimized_two", "terminal:prepared"),
    ("stock:optimized_two", "transition:one_rejected_two_succeeds"),
    ("assignment:custom", "wells:excluded"),
    ("assignment:custom", "capacity:exact"),
    ("assignment:custom", "capacity:over"),
    ("assignment:randomized", "comparison:same_seed_replay"),
    ("assignment:randomized", "comparison:different_seed"),
    ("terminal:capacity_rejected", "evidence:no_authoritative_mutation"),
    ("terminal:formulation_rejected", "evidence:no_authoritative_mutation"),
    ("terminal:prepared", "evidence:reload_runtime"),
)


def _reaction(
    reaction_id: str,
    replicate: int,
    **targets: str,
) -> ExpectedDesignReaction:
    return ExpectedDesignReaction(
        reaction_id=reaction_id,
        replicate=replicate,
        targets=tuple(targets.items()),
    )


def _assignment(well_id: str, reaction_id: str) -> ExpectedWellAssignment:
    return ExpectedWellAssignment(well_id, reaction_id)


def _count(stock_id: str, well_id: str, droplets: int) -> ExpectedStockWellCount:
    return ExpectedStockWellCount(stock_id, well_id, droplets)


CONTROL_STOCK_ID = "Control A_1.00_x"
DESIGN_A_STOCK_ID = "Design A_10.00_x"
DESIGN_B_STOCK_ID = "Design B_10.00_x"
FEASIBILITY_5_STOCK_ID = "Feasibility A_5.00_mM"
FEASIBILITY_10_STOCK_ID = "Feasibility A_10.00_mM"
WELL_STOCK_ID = "Well A_10.00_x"
CAPACITY_STOCK_ID = "Capacity A_10.00_x"
FILL_STOCK_ID = "Water_1.00_--"


_MULTI_REACTIONS = (
    _reaction("R1", 1, **{"Design A": "1", "Design B": "1"}),
    _reaction("R2", 1, **{"Design A": "1", "Design B": "3"}),
    _reaction("R3", 1, **{"Design A": "2", "Design B": "1"}),
    _reaction("R4", 1, **{"Design A": "2", "Design B": "3"}),
    _reaction("R5", 2, **{"Design A": "1", "Design B": "1"}),
    _reaction("R6", 2, **{"Design A": "1", "Design B": "3"}),
    _reaction("R7", 2, **{"Design A": "2", "Design B": "1"}),
    _reaction("R8", 2, **{"Design A": "2", "Design B": "3"}),
)

_MULTI_STOCKS = (
    ExpectedDesignStock(DESIGN_A_STOCK_ID, "Design A", "10", "x"),
    ExpectedDesignStock(DESIGN_B_STOCK_ID, "Design B", "10", "x"),
    ExpectedDesignStock(FILL_STOCK_ID, "Water", "1", "--", role="fill"),
)


def _multi_counts(rows: tuple[tuple[str, int, int, int], ...]) -> tuple[ExpectedStockWellCount, ...]:
    values: list[ExpectedStockWellCount] = []
    for well_id, count_a, count_b, fill_count in rows:
        values.extend(
            (
                _count(DESIGN_A_STOCK_ID, well_id, count_a),
                _count(DESIGN_B_STOCK_ID, well_id, count_b),
                _count(FILL_STOCK_ID, well_id, fill_count),
            )
        )
    return tuple(values)


EXPERIMENT_DESIGN_CASES: tuple[ExperimentDesignCase, ...] = (
    ExperimentDesignCase(
        case_id="single_reagent_control",
        experiment=DesignExperimentInput(
            name="sil-design-single-reagent-control",
            plate_name="shallow-384_well_plate",
            replicates=1,
            selected_well_ids=("A1",),
            excluded_well_ids=(),
            printed_volume_nL="10",
            final_volume_nL="10",
        ),
        reagents=(
            DesignReagentInput(
                "Control A", "Additive", "droplet", "0", ("1",), "x", "10", "1"
            ),
        ),
        optimization_attempts=(DesignOptimizationAttempt(False, "generated"),),
        expected=ExpectedDesignOutcome(
            terminal="prepared",
            reaction_count=1,
            stocks=(ExpectedDesignStock(CONTROL_STOCK_ID, "Control A", "1", "x"),),
            reactions=(_reaction("R1", 1, **{"Control A": "1"}),),
            assignments=(_assignment("A1", "R1"),),
            stock_well_counts=(_count(CONTROL_STOCK_ID, "A1", 1),),
        ),
        coverage_tags=frozenset(
            {
                "reagents:single", "targets:single", "stock:fixed_one",
                "assignment:natural", "capacity:below", "replicates:one",
                "terminal:prepared", "evidence:reload_runtime",
            }
        ),
    ),
    ExperimentDesignCase(
        case_id="multi_reagent_seed_4321",
        experiment=DesignExperimentInput(
            name="sil-design-multi-reagent-seed-4321",
            plate_name="shallow-384_well_plate",
            replicates=2,
            selected_well_ids=("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"),
            excluded_well_ids=(),
            printed_volume_nL="100",
            final_volume_nL="100",
            randomize_assignments=True,
            random_seed=4321,
        ),
        reagents=(
            DesignReagentInput("Design A", "Additive", "droplet", "0", ("1", "2"), "x", "10", "10"),
            DesignReagentInput("Design B", "Additive", "droplet", "0", ("1", "3"), "x", "10", "10"),
        ),
        optimization_attempts=(DesignOptimizationAttempt(False, "generated"),),
        expected=ExpectedDesignOutcome(
            terminal="prepared",
            reaction_count=8,
            stocks=_MULTI_STOCKS,
            reactions=_MULTI_REACTIONS,
            assignments=tuple(
                _assignment(well, reaction)
                for well, reaction in zip(
                    ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"),
                    ("R8", "R6", "R3", "R2", "R7", "R4", "R1", "R5"),
                )
            ),
            stock_well_counts=_multi_counts(
                (
                    ("A1", 2, 3, 6), ("A2", 1, 3, 7),
                    ("A3", 2, 1, 8), ("A4", 1, 3, 7),
                    ("A5", 2, 1, 8), ("A6", 2, 3, 6),
                    ("A7", 1, 1, 9), ("A8", 1, 1, 9),
                )
            ),
        ),
        coverage_tags=frozenset(
            {
                "reagents:multiple", "targets:multiple", "stock:fixed_one",
                "assignment:randomized", "capacity:below", "replicates:multiple",
                "terminal:prepared", "comparison:same_seed_replay",
                "comparison:different_seed", "evidence:reload_runtime",
            }
        ),
    ),
    ExperimentDesignCase(
        case_id="one_stock_feasible",
        experiment=DesignExperimentInput(
            name="sil-design-one-stock-feasible",
            plate_name="shallow-384_well_plate",
            replicates=1,
            selected_well_ids=("A1", "A2"),
            excluded_well_ids=(),
            printed_volume_nL="20",
            final_volume_nL="500",
        ),
        reagents=(
            DesignReagentInput("Feasibility A", "Additive", "droplet", "0", ("0.1", "0.2"), "mM", "10"),
        ),
        optimization_attempts=(DesignOptimizationAttempt(False, "generated"),),
        expected=ExpectedDesignOutcome(
            terminal="prepared",
            reaction_count=2,
            stocks=(
                ExpectedDesignStock(FEASIBILITY_5_STOCK_ID, "Feasibility A", "5", "mM"),
                ExpectedDesignStock(FILL_STOCK_ID, "Water", "1", "--", role="fill"),
            ),
            reactions=(
                _reaction("R1", 1, **{"Feasibility A": "0.1"}),
                _reaction("R2", 1, **{"Feasibility A": "0.2"}),
            ),
            assignments=(_assignment("A1", "R1"), _assignment("A2", "R2")),
            stock_well_counts=(
                _count(FEASIBILITY_5_STOCK_ID, "A1", 1),
                _count(FILL_STOCK_ID, "A1", 1),
                _count(FEASIBILITY_5_STOCK_ID, "A2", 2),
            ),
        ),
        coverage_tags=frozenset(
            {
                "reagents:single", "targets:multiple", "stock:optimized_one",
                "assignment:natural", "capacity:below", "replicates:one",
                "terminal:prepared", "evidence:reload_runtime",
            }
        ),
    ),
    ExperimentDesignCase(
        case_id="two_stock_required",
        experiment=DesignExperimentInput(
            name="sil-design-two-stock-required",
            plate_name="shallow-384_well_plate",
            replicates=1,
            selected_well_ids=("A1", "A2"),
            excluded_well_ids=(),
            printed_volume_nL="10",
            final_volume_nL="500",
            allow_two_stock_solutions=True,
        ),
        reagents=(
            DesignReagentInput("Feasibility A", "Additive", "droplet", "0", ("0.1", "0.2"), "mM", "10"),
        ),
        optimization_attempts=(
            DesignOptimizationAttempt(
                False,
                "rejected",
                "Optimization failed",
                ("Enable two-stock mode",),
            ),
            DesignOptimizationAttempt(True, "generated"),
        ),
        expected=ExpectedDesignOutcome(
            terminal="prepared",
            reaction_count=2,
            stocks=(
                ExpectedDesignStock(FEASIBILITY_5_STOCK_ID, "Feasibility A", "5", "mM"),
                ExpectedDesignStock(FEASIBILITY_10_STOCK_ID, "Feasibility A", "10", "mM"),
            ),
            reactions=(
                _reaction("R1", 1, **{"Feasibility A": "0.1"}),
                _reaction("R2", 1, **{"Feasibility A": "0.2"}),
            ),
            assignments=(_assignment("A1", "R1"), _assignment("A2", "R2")),
            stock_well_counts=(
                _count(FEASIBILITY_5_STOCK_ID, "A1", 1),
                _count(FEASIBILITY_10_STOCK_ID, "A2", 1),
            ),
        ),
        coverage_tags=frozenset(
            {
                "reagents:single", "targets:multiple", "stock:optimized_two",
                "assignment:natural", "capacity:below", "replicates:one",
                "terminal:prepared", "transition:one_rejected_two_succeeds",
                "evidence:reload_runtime",
            }
        ),
    ),
    ExperimentDesignCase(
        case_id="custom_wells_with_exclusions",
        experiment=DesignExperimentInput(
            name="sil-design-custom-wells-exclusions",
            plate_name="shallow-384_well_plate",
            replicates=1,
            selected_well_ids=("A1", "A2", "A3", "A4", "A5", "A6"),
            excluded_well_ids=("A2", "A5"),
            printed_volume_nL="100",
            final_volume_nL="100",
        ),
        reagents=(
            DesignReagentInput("Well A", "Additive", "droplet", "0", ("1", "2", "3"), "x", "10", "10"),
        ),
        optimization_attempts=(DesignOptimizationAttempt(False, "generated"),),
        expected=ExpectedDesignOutcome(
            terminal="prepared",
            reaction_count=3,
            stocks=(
                ExpectedDesignStock(WELL_STOCK_ID, "Well A", "10", "x"),
                ExpectedDesignStock(FILL_STOCK_ID, "Water", "1", "--", role="fill"),
            ),
            reactions=(
                _reaction("R1", 1, **{"Well A": "1"}),
                _reaction("R2", 1, **{"Well A": "2"}),
                _reaction("R3", 1, **{"Well A": "3"}),
            ),
            assignments=(
                _assignment("A1", "R1"),
                _assignment("A3", "R2"),
                _assignment("A4", "R3"),
            ),
            stock_well_counts=(
                _count(WELL_STOCK_ID, "A1", 1), _count(FILL_STOCK_ID, "A1", 9),
                _count(WELL_STOCK_ID, "A3", 2), _count(FILL_STOCK_ID, "A3", 8),
                _count(WELL_STOCK_ID, "A4", 3), _count(FILL_STOCK_ID, "A4", 7),
            ),
        ),
        coverage_tags=frozenset(
            {
                "reagents:single", "targets:multiple", "stock:fixed_one",
                "assignment:custom", "wells:excluded", "capacity:below",
                "replicates:one", "terminal:prepared", "evidence:reload_runtime",
            }
        ),
    ),
    ExperimentDesignCase(
        case_id="multi_reagent_seed_1234",
        experiment=DesignExperimentInput(
            name="sil-design-multi-reagent-seed-1234",
            plate_name="shallow-384_well_plate",
            replicates=2,
            selected_well_ids=("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"),
            excluded_well_ids=(),
            printed_volume_nL="100",
            final_volume_nL="100",
            randomize_assignments=True,
            random_seed=1234,
        ),
        reagents=(
            DesignReagentInput("Design A", "Additive", "droplet", "0", ("1", "2"), "x", "10", "10"),
            DesignReagentInput("Design B", "Additive", "droplet", "0", ("1", "3"), "x", "10", "10"),
        ),
        optimization_attempts=(DesignOptimizationAttempt(False, "generated"),),
        expected=ExpectedDesignOutcome(
            terminal="prepared",
            reaction_count=8,
            stocks=_MULTI_STOCKS,
            reactions=_MULTI_REACTIONS,
            assignments=tuple(
                _assignment(well, reaction)
                for well, reaction in zip(
                    ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"),
                    ("R2", "R4", "R3", "R5", "R6", "R7", "R1", "R8"),
                )
            ),
            stock_well_counts=_multi_counts(
                (
                    ("A1", 1, 3, 6), ("A2", 2, 3, 5),
                    ("A3", 2, 1, 7), ("A4", 1, 1, 8),
                    ("A5", 1, 3, 6), ("A6", 2, 1, 7),
                    ("A7", 1, 1, 8), ("A8", 2, 3, 5),
                )
            ),
        ),
        coverage_tags=frozenset(
            {
                "reagents:multiple", "targets:multiple", "stock:fixed_one",
                "assignment:randomized", "capacity:below", "replicates:multiple",
                "terminal:prepared", "comparison:same_seed_replay",
                "comparison:different_seed", "evidence:reload_runtime",
            }
        ),
    ),
    ExperimentDesignCase(
        case_id="exact_custom_capacity",
        experiment=DesignExperimentInput(
            name="sil-design-exact-custom-capacity",
            plate_name="shallow-384_well_plate",
            replicates=2,
            selected_well_ids=("B1", "B2", "B3", "B4"),
            excluded_well_ids=(),
            printed_volume_nL="100",
            final_volume_nL="100",
        ),
        reagents=(
            DesignReagentInput("Capacity A", "Additive", "droplet", "0", ("1", "2"), "x", "10", "10"),
        ),
        optimization_attempts=(DesignOptimizationAttempt(False, "generated"),),
        expected=ExpectedDesignOutcome(
            terminal="prepared",
            reaction_count=4,
            stocks=(
                ExpectedDesignStock(CAPACITY_STOCK_ID, "Capacity A", "10", "x"),
                ExpectedDesignStock(FILL_STOCK_ID, "Water", "1", "--", role="fill"),
            ),
            reactions=(
                _reaction("R1", 1, **{"Capacity A": "1"}),
                _reaction("R2", 1, **{"Capacity A": "2"}),
                _reaction("R3", 2, **{"Capacity A": "1"}),
                _reaction("R4", 2, **{"Capacity A": "2"}),
            ),
            assignments=tuple(
                _assignment(well, reaction)
                for well, reaction in zip(
                    ("B1", "B2", "B3", "B4"),
                    ("R1", "R2", "R3", "R4"),
                )
            ),
            stock_well_counts=(
                _count(CAPACITY_STOCK_ID, "B1", 1), _count(FILL_STOCK_ID, "B1", 9),
                _count(CAPACITY_STOCK_ID, "B2", 2), _count(FILL_STOCK_ID, "B2", 8),
                _count(CAPACITY_STOCK_ID, "B3", 1), _count(FILL_STOCK_ID, "B3", 9),
                _count(CAPACITY_STOCK_ID, "B4", 2), _count(FILL_STOCK_ID, "B4", 8),
            ),
            capacity_required=4,
            capacity_available=4,
        ),
        coverage_tags=frozenset(
            {
                "reagents:single", "targets:multiple", "stock:fixed_one",
                "assignment:custom", "capacity:exact", "replicates:multiple",
                "terminal:prepared", "evidence:reload_runtime",
            }
        ),
    ),
    ExperimentDesignCase(
        case_id="capacity_plus_one_rejected",
        experiment=DesignExperimentInput(
            name="sil-design-capacity-plus-one",
            plate_name="shallow-384_well_plate",
            replicates=5,
            selected_well_ids=("B1", "B2", "B3", "B4"),
            excluded_well_ids=(),
            printed_volume_nL="100",
            final_volume_nL="100",
        ),
        reagents=(
            DesignReagentInput("Capacity A", "Additive", "droplet", "0", ("1",), "x", "10", "10"),
        ),
        optimization_attempts=(DesignOptimizationAttempt(False, "generated"),),
        expected=ExpectedDesignOutcome(
            terminal="capacity_rejected",
            reaction_count=5,
            capacity_required=5,
            capacity_available=4,
            dialog_title="Insufficient Well Capacity",
            message_fragments=("Required reactions: 5", "Available wells", "4"),
        ),
        coverage_tags=frozenset(
            {
                "reagents:single", "targets:single", "stock:fixed_one",
                "assignment:custom", "capacity:over", "replicates:multiple",
                "terminal:capacity_rejected", "evidence:no_authoritative_mutation",
            }
        ),
    ),
    ExperimentDesignCase(
        case_id="fixed_stock_exceeds_max_rejected",
        experiment=DesignExperimentInput(
            name="sil-design-fixed-stock-exceeds-max",
            plate_name="shallow-384_well_plate",
            replicates=1,
            selected_well_ids=("C1",),
            excluded_well_ids=(),
            printed_volume_nL="100",
            final_volume_nL="500",
        ),
        reagents=(
            DesignReagentInput(
                "Infeasible A", "Additive", "droplet", "0", ("1",), "mM", "10", "35", "20"
            ),
        ),
        optimization_attempts=(
            DesignOptimizationAttempt(
                False,
                "rejected",
                "Optimization failed",
                ("exceeds max stock",),
            ),
        ),
        expected=ExpectedDesignOutcome(
            terminal="formulation_rejected",
            reaction_count=1,
            dialog_title="Optimization failed",
            message_fragments=("exceeds max stock",),
        ),
        coverage_tags=frozenset(
            {
                "reagents:single", "targets:single", "stock:fixed_exceeds_max",
                "assignment:natural", "capacity:below", "replicates:one",
                "terminal:formulation_rejected", "evidence:no_authoritative_mutation",
            }
        ),
    ),
)


def get_experiment_design_case(case_id: str) -> ExperimentDesignCase:
    matches = [case for case in EXPERIMENT_DESIGN_CASES if case.case_id == str(case_id)]
    if len(matches) != 1:
        raise ExperimentDesignCaseError(
            f"unsupported experiment-design case: {case_id!r}"
        )
    return matches[0]


def audit_pairwise_coverage(
    cases: Sequence[ExperimentDesignCase] = EXPERIMENT_DESIGN_CASES,
) -> dict[str, Any]:
    rows = []
    uncovered = []
    for left, right in REQUIRED_PAIRWISE_INTERACTIONS:
        covering = [
            case.case_id
            for case in cases
            if {left, right}.issubset(case.coverage_tags)
        ]
        row = {"left": left, "right": right, "case_ids": covering}
        rows.append(row)
        if not covering:
            uncovered.append({"left": left, "right": right})
    return {
        "case_count": len(cases),
        "required_pair_count": len(REQUIRED_PAIRWISE_INTERACTIONS),
        "pairs": rows,
        "uncovered": uncovered,
        "complete": not uncovered,
    }


def validate_experiment_design_catalog(
    cases: Sequence[ExperimentDesignCase] = EXPERIMENT_DESIGN_CASES,
) -> None:
    cases = tuple(cases)
    if len(cases) != 9:
        raise ExperimentDesignCaseError("experiment-design catalog must contain nine cases")
    case_ids = [case.case_id for case in cases]
    expected_ids = [
        "single_reagent_control",
        "multi_reagent_seed_4321",
        "one_stock_feasible",
        "two_stock_required",
        "custom_wells_with_exclusions",
        "multi_reagent_seed_1234",
        "exact_custom_capacity",
        "capacity_plus_one_rejected",
        "fixed_stock_exceeds_max_rejected",
    ]
    if case_ids != expected_ids or len(set(case_ids)) != len(case_ids):
        raise ExperimentDesignCaseError("experiment-design case order or identity drifted")
    normalized = [case.normalized() for case in cases]
    if _canonical_json(normalized) != _canonical_json(
        [case.normalized() for case in cases]
    ):
        raise ExperimentDesignCaseError("experiment-design catalog is not deterministic")
    audit = audit_pairwise_coverage(cases)
    if not audit["complete"]:
        raise ExperimentDesignCaseError(
            f"experiment-design pairwise coverage is incomplete: {audit['uncovered']}"
        )
    by_id = {case.case_id: case for case in cases}
    seed_a = by_id["multi_reagent_seed_4321"]
    seed_b = by_id["multi_reagent_seed_1234"]
    if (
        seed_a.expected.reaction_multiset_sha256()
        != seed_b.expected.reaction_multiset_sha256()
        or seed_a.expected.assignment_sha256()
        == seed_b.expected.assignment_sha256()
        or seed_a.experiment.random_seed == seed_b.experiment.random_seed
    ):
        raise ExperimentDesignCaseError(
            "randomized comparison cases do not prove equal multisets and distinct assignments"
        )


def normalized_planned_catalog() -> dict[str, Any]:
    return {
        "matrix_id": EXPERIMENT_DESIGN_MATRIX_ID,
        "base_scenario_id": EXPERIMENT_DESIGN_BASE_SCENARIO_ID,
        "journey_family": EXPERIMENT_DESIGN_JOURNEY_FAMILY,
        "pairwise_audit": audit_pairwise_coverage(),
        "cases": [case.normalized() for case in EXPERIMENT_DESIGN_CASES],
    }


def planned_catalog_sha256() -> str:
    return _sha256_json(normalized_planned_catalog())


def executable_experiment_design_cases() -> tuple[ExperimentDesignCase, ...]:
    """Return the reviewed executable prefix without changing case truth."""

    return tuple(
        get_experiment_design_case(case_id)
        for case_id in EXPERIMENT_DESIGN_EXECUTABLE_CASE_IDS
    )


def editor_specification(case: ExperimentDesignCase) -> dict[str, Any]:
    """Project typed inputs to the normal editor driver's additive contract."""

    if case.expected.terminal != "prepared":
        raise ExperimentDesignCaseError(
            "rejected experiment-design cases require the negative driver"
        )
    experiment = case.experiment.normalized()
    experiment["expected_reaction_count"] = case.expected.reaction_count
    return {
        "experiment": experiment,
        "reagents": [reagent.normalized() for reagent in case.reagents],
    }


def build_experiment_design_fixture(
    case: ExperimentDesignCase,
) -> tuple[dict[str, Any], Path]:
    """Derive one future matrix fixture from the unchanged tracked reference."""

    source = REFERENCE_FIXTURE_PATH.resolve()
    source_bytes = source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != REFERENCE_FIXTURE_SHA256:
        raise ExperimentDesignCaseError("editor reference fixture hash drifted")
    payload = json.loads(source_bytes.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ExperimentDesignCaseError("editor reference fixture is not an object")
    fixture = copy.deepcopy(payload)
    fixture["fixture_id"] = f"{EXPERIMENT_DESIGN_MATRIX_ID}__{case.case_id}"
    fixture["experiment"] = {
        **case.experiment.normalized(),
        "expected_reaction_count": case.expected.reaction_count,
    }
    fixture.pop("reagent", None)
    fixture["reagents"] = [reagent.normalized() for reagent in case.reagents]
    fixture["workload"] = {
        "completion_count": 0,
        "expected_editor_finalization_operations": (
            1 if case.expected.terminal == "prepared" else 0
        ),
    }
    fixture["lifecycle"] = {
        "kind": "parameterized_experiment_design_matrix_case",
        "matrix_id": EXPERIMENT_DESIGN_MATRIX_ID,
        "case": case.normalized(),
        "case_sha256": case.sha256(),
        "planned_catalog_sha256": planned_catalog_sha256(),
    }
    return fixture, source


validate_experiment_design_catalog()


__all__ = [
    "DesignExperimentInput",
    "DesignOptimizationAttempt",
    "DesignReagentInput",
    "EXPERIMENT_DESIGN_BASE_SCENARIO_ID",
    "EXPERIMENT_DESIGN_CASES",
    "EXPERIMENT_DESIGN_EXECUTABLE_CASE_IDS",
    "EXPERIMENT_DESIGN_JOURNEY_FAMILY",
    "EXPERIMENT_DESIGN_MATRIX_ID",
    "ExpectedDesignOutcome",
    "ExpectedDesignReaction",
    "ExpectedDesignStock",
    "ExpectedStockWellCount",
    "ExpectedWellAssignment",
    "ExperimentDesignCase",
    "ExperimentDesignCaseError",
    "RECOGNIZED_COVERAGE_TAGS",
    "REFERENCE_FIXTURE_PATH",
    "REFERENCE_FIXTURE_SHA256",
    "REQUIRED_PAIRWISE_INTERACTIONS",
    "audit_pairwise_coverage",
    "build_experiment_design_fixture",
    "editor_specification",
    "executable_experiment_design_cases",
    "get_experiment_design_case",
    "normalized_planned_catalog",
    "planned_catalog_sha256",
    "validate_experiment_design_catalog",
]
