"""Frozen truth for the optimizer-driven 360-reaction SIL lifecycle.

The module is deliberately test-contract-only.  It imports no application
Model, View, Controller, optimizer, assignment, calibration, or execution
implementation.  Literal fixture data is expanded only by reaction, stock,
and well identity joins; list position is never an oracle key.
"""

from __future__ import annotations

import hashlib
import json
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.virtual_workflows.experiment_design_cases import (
    DesignExperimentInput,
    DesignOptimizationAttempt,
    DesignReagentInput,
    ExpectedDesignOutcome,
    ExpectedDesignReaction,
    ExpectedDesignStock,
    ExpectedStockWellCount,
    ExpectedWellAssignment,
    ExperimentDesignCase,
)
from tools.virtual_workflows.joined_interaction_cases import (
    JoinedCalibration,
    JoinedCheckpoint,
    JoinedCountOracle,
    JoinedStockWellCount,
)


OPTIMIZER_360_CASE_ID = "optimizer_360_calibration_reload_execution_v1"
OPTIMIZER_360_SCENARIO_NAME = "optimizer_360_calibration_reload_execution"
OPTIMIZER_360_CAPABILITY = (
    "execution.optimizer_360_calibration_reload_execution"
)
OPTIMIZER_360_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / f"{OPTIMIZER_360_CASE_ID}.json"
)

RANGE_A_STOCK_ID = "Range A_222.22_x"
RANGE_B_STOCK_ID = "Range B_100.00_x"
RANGE_C_STOCK_ID = "Range C_555.56_x"
RANGE_D_STOCK_ID = "Range D_20.00_x"
WATER_STOCK_ID = "Water_1.00_--"
OPTIMIZER_360_STOCK_IDS = (
    RANGE_A_STOCK_ID,
    RANGE_B_STOCK_ID,
    RANGE_C_STOCK_ID,
    RANGE_D_STOCK_ID,
    WATER_STOCK_ID,
)
OPTIMIZER_360_COUNT_CHECKPOINT_IDS = (
    "prepared",
    "range_a_calibrated",
    "range_b_calibrated",
    "range_c_calibrated",
    "range_d_calibrated",
    "all_stocks_calibrated",
)

EXPECTED_FIXTURE_SHA256 = (
    "d7f4de4aafeaf4a66751872d017d89393c263d48b5ffefa1b0e1690efaa10783"
)
EXPECTED_CASE_SHA256 = (
    "f238d4d90b822fdf52d4170b1f6fc1871b3d73f56df3aad543637f3e5d4078d8"
)
EXPECTED_REACTION_MULTISET_SHA256 = (
    "5acfa8580c581231275e2b6f17ec757d71df5dcc4696196e1c0f9b2176ee7afd"
)
EXPECTED_ACHIEVED_REACTION_MULTISET_SHA256 = (
    "418cf4a50cc0015c52b9b093a5df9096df98930dc0f58f42aa37c30830fe64f0"
)
EXPECTED_ASSIGNMENT_SHA256 = (
    "5f84bfd4cd7c2c0d4b289b6797c50feeab9739a65d56ac2fc3949da030ab3ed2"
)
EXPECTED_COUNT_ORACLE_SHA256 = (
    "3f86a60425d2c0d6abf0839d9f0fca16a41a6e398125053dd849d2e9b397458f"
)


class Optimizer360CaseError(ValueError):
    """Raised when the standalone Milestone 11A truth is malformed."""


def _canonical_json(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _identity(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise Optimizer360CaseError(f"{label} must be non-empty")
    return text


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise Optimizer360CaseError(f"{label} must be a positive integer")
    return value


def _keys(payload: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise Optimizer360CaseError(
            f"{label} keys differ: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


@dataclass(frozen=True)
class Optimizer360Identity:
    scenario_name: str
    capability: str
    experiment_name: str
    suite: str
    tier: str
    simulation_seed: int

    def __post_init__(self) -> None:
        for field in ("scenario_name", "capability", "experiment_name", "suite", "tier"):
            object.__setattr__(self, field, _identity(getattr(self, field), field))
        _positive_int(self.simulation_seed, "simulation seed")

    def normalized(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class Optimizer360CountMap:
    checkpoint_id: str
    non_fill_target_counts: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]
    water_by_reaction: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "checkpoint_id", _identity(self.checkpoint_id, "count checkpoint")
        )
        stock_ids = [stock_id for stock_id, _ in self.non_fill_target_counts]
        if len(stock_ids) != len(set(stock_ids)):
            raise Optimizer360CaseError("non-fill count-map stock IDs must be unique")
        for stock_id, rows in self.non_fill_target_counts:
            _identity(stock_id, "count-map stock")
            targets = [target for target, _ in rows]
            if len(targets) != len(set(targets)):
                raise Optimizer360CaseError("target count-map keys must be unique")
            for target, count in rows:
                _identity(target, "count-map target")
                _positive_int(count, "target count")
        reaction_ids = [reaction_id for reaction_id, _ in self.water_by_reaction]
        if len(reaction_ids) != len(set(reaction_ids)):
            raise Optimizer360CaseError("Water reaction keys must be unique")
        for reaction_id, count in self.water_by_reaction:
            _identity(reaction_id, "Water reaction")
            _positive_int(count, "Water count")

    def target_maps(self) -> dict[str, dict[str, int]]:
        return {
            stock_id: dict(rows)
            for stock_id, rows in self.non_fill_target_counts
        }

    def water_map(self) -> dict[str, int]:
        return dict(self.water_by_reaction)

    def normalized(self) -> dict[str, Any]:
        return {
            "non_fill_target_counts": {
                stock_id: dict(rows)
                for stock_id, rows in self.non_fill_target_counts
            },
            "water_by_reaction": dict(self.water_by_reaction),
        }


def _expand_count_rows(
    *,
    reactions: Sequence[ExpectedDesignReaction],
    assignments: Sequence[ExpectedWellAssignment],
    stocks: Sequence[ExpectedDesignStock],
    count_map: Optimizer360CountMap,
) -> tuple[JoinedStockWellCount, ...]:
    """Join compact literals by stable identities, never by list position."""

    target_maps = count_map.target_maps()
    water = count_map.water_map()
    reactions_by_id = {
        reaction.reaction_id: dict(reaction.targets) for reaction in reactions
    }
    stock_reagents = {
        stock.stock_id: stock.reagent_name
        for stock in stocks
        if stock.role == "non_fill"
    }
    rows: list[JoinedStockWellCount] = []
    for assignment in assignments:
        targets = reactions_by_id[assignment.reaction_id]
        for stock_id in OPTIMIZER_360_STOCK_IDS[:-1]:
            reagent_name = stock_reagents[stock_id]
            rows.append(
                JoinedStockWellCount(
                    stock_id,
                    assignment.well_id,
                    target_maps[stock_id][targets[reagent_name]],
                )
            )
        rows.append(
            JoinedStockWellCount(
                WATER_STOCK_ID,
                assignment.well_id,
                water[assignment.reaction_id],
            )
        )
    return tuple(rows)


@dataclass(frozen=True)
class Optimizer360ExecutionPass:
    order: int
    stock_id: str
    expected_intents: int
    expected_droplets: int
    cumulative_completion: int
    milestone: str

    def __post_init__(self) -> None:
        for field in (
            "order", "expected_intents", "expected_droplets", "cumulative_completion"
        ):
            _positive_int(getattr(self, field), field)
        object.__setattr__(self, "stock_id", _identity(self.stock_id, "pass stock"))
        object.__setattr__(self, "milestone", _identity(self.milestone, "pass milestone"))

    def normalized(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class Optimizer360Qualification:
    cli_seed: int
    action_cap: int
    simulator_evidence_cap: int
    offscreen_timeout_seconds: int
    visible_timeout_seconds: int
    visible_speed: int
    required_screenshots: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in (
            "cli_seed", "action_cap", "simulator_evidence_cap",
            "offscreen_timeout_seconds", "visible_timeout_seconds", "visible_speed",
        ):
            _positive_int(getattr(self, field), field)
        screenshots = tuple(
            _identity(value, "required screenshot") for value in self.required_screenshots
        )
        if len(screenshots) != len(set(screenshots)):
            raise Optimizer360CaseError("required screenshots must be unique")
        object.__setattr__(self, "required_screenshots", screenshots)

    def normalized(self) -> dict[str, Any]:
        return {
            **{
                name: getattr(self, name)
                for name in self.__dataclass_fields__
                if name != "required_screenshots"
            },
            "required_screenshots": list(self.required_screenshots),
        }


@dataclass(frozen=True)
class Optimizer360Expectations:
    approximate_targets: int
    unreachable_targets: int
    achieved_target_concentrations: tuple[
        tuple[str, tuple[tuple[str, str], ...]], ...
    ]

    def __post_init__(self) -> None:
        for field in ("approximate_targets", "unreachable_targets"):
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise Optimizer360CaseError(f"{field} must be a non-negative integer")
        reagents = [reagent for reagent, _ in self.achieved_target_concentrations]
        if len(reagents) != len(set(reagents)):
            raise Optimizer360CaseError("achieved-concentration reagents must be unique")
        for reagent, rows in self.achieved_target_concentrations:
            _identity(reagent, "achieved-concentration reagent")
            requested = [target for target, _ in rows]
            if len(requested) != len(set(requested)):
                raise Optimizer360CaseError("achieved-concentration targets must be unique")
            for target, achieved in rows:
                _identity(target, "requested concentration")
                _identity(achieved, "achieved concentration")

    def achieved_maps(self) -> dict[str, dict[str, str]]:
        return {
            reagent: dict(rows)
            for reagent, rows in self.achieved_target_concentrations
        }

    def normalized(self) -> dict[str, Any]:
        return {
            "approximate_targets": self.approximate_targets,
            "unreachable_targets": self.unreachable_targets,
            "achieved_target_concentrations": self.achieved_maps(),
        }


@dataclass(frozen=True)
class Optimizer360Terminal:
    expected_intents: int
    expected_droplets: int
    expected_completed_wells: int
    expected_completed_stocks: int
    application_sessions: int
    terminal_revision: int

    def __post_init__(self) -> None:
        for field in self.__dataclass_fields__:
            _positive_int(getattr(self, field), field)

    def normalized(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class Optimizer360Case:
    case_id: str
    schema_version: int
    identity: Optimizer360Identity
    design_case: ExperimentDesignCase
    calibrations: tuple[JoinedCalibration, ...]
    checkpoints: tuple[JoinedCheckpoint, ...]
    count_maps: tuple[Optimizer360CountMap, ...]
    aggregate_totals: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]
    optimizer_expectations: Optimizer360Expectations
    execution_passes: tuple[Optimizer360ExecutionPass, ...]
    qualification: Optimizer360Qualification
    terminal: Optimizer360Terminal

    @property
    def editor(self) -> DesignExperimentInput:
        return self.design_case.experiment

    @property
    def stocks(self) -> tuple[ExpectedDesignStock, ...]:
        return self.design_case.expected.stocks

    @property
    def assignments(self) -> tuple[ExpectedWellAssignment, ...]:
        return self.design_case.expected.assignments

    def count_map(self, checkpoint_id: str) -> Optimizer360CountMap:
        matches = [row for row in self.count_maps if row.checkpoint_id == checkpoint_id]
        if len(matches) != 1:
            raise Optimizer360CaseError(
                f"unknown or duplicate count checkpoint: {checkpoint_id}"
            )
        return matches[0]

    def oracle(self, checkpoint_id: str) -> JoinedCountOracle:
        """Expand compact truth solely through reaction/stock/well identities."""

        return JoinedCountOracle(
            checkpoint_id,
            _expand_count_rows(
                reactions=self.design_case.expected.reactions,
                assignments=self.assignments,
                stocks=self.stocks,
                count_map=self.count_map(checkpoint_id),
            ),
        )

    def aggregate(self, checkpoint_id: str) -> dict[str, int]:
        matches = [dict(rows) for name, rows in self.aggregate_totals if name == checkpoint_id]
        if len(matches) != 1:
            raise Optimizer360CaseError(f"unknown aggregate checkpoint: {checkpoint_id}")
        return matches[0]

    def achieved_design_oracle(self) -> dict[str, Any]:
        """Project requested reactions to literal nearest-achievable truth."""

        payload = copy.deepcopy(self.design_case.normalized())
        achieved = self.optimizer_expectations.achieved_maps()
        multiset: list[dict[str, Any]] = []
        for reaction in payload["expected"]["reactions"]:
            for target in reaction["targets"]:
                requested = str(target["target"])
                target["target"] = achieved[str(target["reagent"])][requested]
            multiset.append(
                {
                    "replicate": reaction["replicate"],
                    "targets": copy.deepcopy(reaction["targets"]),
                }
            )
        multiset.sort(key=_canonical_json)
        payload["expected"]["reaction_multiset_sha256"] = _sha256_json(multiset)
        payload["expected"]["assignments"].sort(key=lambda row: row["well_id"])
        payload["expected"]["assignment_sha256"] = _sha256_json(
            payload["expected"]["assignments"]
        )
        return payload

    def normalized(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "schema_version": self.schema_version,
            "identity": self.identity.normalized(),
            "design_case": self.design_case.normalized(),
            "calibrations": [row.normalized() for row in self.calibrations],
            "checkpoints": [row.normalized() for row in self.checkpoints],
            "count_maps": {
                row.checkpoint_id: row.normalized() for row in self.count_maps
            },
            "aggregate_totals": {
                checkpoint_id: dict(rows)
                for checkpoint_id, rows in self.aggregate_totals
            },
            "optimizer_expectations": self.optimizer_expectations.normalized(),
            "execution_passes": [row.normalized() for row in self.execution_passes],
            "qualification": self.qualification.normalized(),
            "terminal": self.terminal.normalized(),
        }

    def sha256(self) -> str:
        return _sha256_json(self.normalized())

    def count_oracle_sha256(self) -> str:
        return _sha256_json(
            [self.oracle(checkpoint_id).normalized() for checkpoint_id in OPTIMIZER_360_COUNT_CHECKPOINT_IDS]
        )


def _parse_case(payload: Mapping[str, Any]) -> Optimizer360Case:
    _keys(
        payload,
        {
            "case_id", "schema_version", "identity", "experiment", "reagents",
            "stocks", "reactions", "assignments", "calibrations", "checkpoints",
            "count_maps", "aggregate_totals", "optimizer_expectations",
            "execution_passes", "qualification",
            "terminal",
        },
        "fixture",
    )
    identity_payload = payload["identity"]
    experiment_payload = payload["experiment"]
    qualification_payload = payload["qualification"]
    terminal_payload = payload["terminal"]
    optimizer_payload = payload["optimizer_expectations"]
    _keys(identity_payload, set(Optimizer360Identity.__dataclass_fields__), "identity")
    _keys(
        experiment_payload,
        set(DesignExperimentInput.__dataclass_fields__) - {"name"},
        "experiment",
    )
    _keys(qualification_payload, set(Optimizer360Qualification.__dataclass_fields__), "qualification")
    _keys(terminal_payload, set(Optimizer360Terminal.__dataclass_fields__), "terminal")
    _keys(
        optimizer_payload,
        set(Optimizer360Expectations.__dataclass_fields__),
        "optimizer expectations",
    )

    experiment = DesignExperimentInput(
        **{
            **experiment_payload,
            "name": identity_payload["experiment_name"],
            "selected_well_ids": tuple(experiment_payload["selected_well_ids"]),
            "excluded_well_ids": tuple(experiment_payload["excluded_well_ids"]),
        }
    )
    reagents = tuple(
        DesignReagentInput(**{**row, "targets": tuple(row["targets"])})
        for row in payload["reagents"]
    )
    stocks = tuple(ExpectedDesignStock(**row) for row in payload["stocks"])
    reactions = tuple(
        ExpectedDesignReaction(
            reaction_id=row["reaction_id"],
            replicate=row["replicate"],
            targets=tuple(row["targets"].items()),
        )
        for row in payload["reactions"]
    )
    assignments = tuple(ExpectedWellAssignment(**row) for row in payload["assignments"])

    raw_count_maps = payload["count_maps"]
    count_maps = tuple(
        Optimizer360CountMap(
            checkpoint_id=checkpoint_id,
            non_fill_target_counts=tuple(
                (stock_id, tuple(target_rows.items()))
                for stock_id, target_rows in value["non_fill_target_counts"].items()
            ),
            water_by_reaction=tuple(value["water_by_reaction"].items()),
        )
        for checkpoint_id, value in raw_count_maps.items()
    )
    prepared_map = next(
        row for row in count_maps if row.checkpoint_id == "prepared"
    )
    prepared_counts = tuple(
        ExpectedStockWellCount(row.stock_id, row.well_id, row.target_droplets)
        for row in _expand_count_rows(
            reactions=reactions,
            assignments=assignments,
            stocks=stocks,
            count_map=prepared_map,
        )
    )
    design_case = ExperimentDesignCase(
        case_id=str(payload["case_id"]),
        experiment=experiment,
        reagents=reagents,
        optimization_attempts=(DesignOptimizationAttempt(False, "generated"),),
        expected=ExpectedDesignOutcome(
            terminal="prepared",
            reaction_count=360,
            stocks=stocks,
            reactions=reactions,
            assignments=assignments,
            stock_well_counts=prepared_counts,
        ),
        coverage_tags=frozenset({
            "reagents:multiple", "targets:multiple", "stock:optimized_one",
            "assignment:randomized", "replicates:one", "terminal:prepared",
        }),
    )
    case = Optimizer360Case(
        case_id=str(payload["case_id"]),
        schema_version=int(payload["schema_version"]),
        identity=Optimizer360Identity(**identity_payload),
        design_case=design_case,
        calibrations=tuple(JoinedCalibration(**row) for row in payload["calibrations"]),
        checkpoints=tuple(JoinedCheckpoint(**row) for row in payload["checkpoints"]),
        count_maps=count_maps,
        aggregate_totals=tuple(
            (checkpoint_id, tuple(rows.items()))
            for checkpoint_id, rows in payload["aggregate_totals"].items()
        ),
        optimizer_expectations=Optimizer360Expectations(
            approximate_targets=optimizer_payload["approximate_targets"],
            unreachable_targets=optimizer_payload["unreachable_targets"],
            achieved_target_concentrations=tuple(
                (reagent, tuple(rows.items()))
                for reagent, rows in optimizer_payload[
                    "achieved_target_concentrations"
                ].items()
            ),
        ),
        execution_passes=tuple(
            Optimizer360ExecutionPass(**row) for row in payload["execution_passes"]
        ),
        qualification=Optimizer360Qualification(**{
            **qualification_payload,
            "required_screenshots": tuple(qualification_payload["required_screenshots"]),
        }),
        terminal=Optimizer360Terminal(**terminal_payload),
    )
    validate_optimizer_360_case(case)
    return case


def validate_optimizer_360_case(case: Optimizer360Case) -> None:
    """Fail closed on identity, literal mappings, joins, totals, and hashes."""

    if case.case_id != OPTIMIZER_360_CASE_ID or case.schema_version != 1:
        raise Optimizer360CaseError("case identity or schema version drifted")
    if case.identity.normalized() != {
        "scenario_name": OPTIMIZER_360_SCENARIO_NAME,
        "capability": OPTIMIZER_360_CAPABILITY,
        "experiment_name": "sil-optimizer-360-calibration-v1",
        "suite": "host_stress",
        "tier": "stress",
        "simulation_seed": 1,
    }:
        raise Optimizer360CaseError("scenario/capability identity drifted")

    experiment = case.editor
    expected_wells = {f"{row}{column}" for row in "ABCDEFGHIJKLMNO" for column in range(1, 25)}
    if (
        experiment.plate_name != "shallow-384_well_plate"
        or experiment.replicates != 1
        or set(experiment.selected_well_ids) != expected_wells
        or len(experiment.selected_well_ids) != 360
        or any(well.startswith("P") for well in experiment.selected_well_ids)
        or experiment.excluded_well_ids
        or experiment.printed_volume_nL != "2000"
        or experiment.final_volume_nL != "2000"
        or experiment.printed_volume_tolerance_nL != "0"
        or experiment.randomize_assignments is not True
        or experiment.random_seed != 4321
        or experiment.allow_two_stock_solutions is not False
    ):
        raise Optimizer360CaseError("plate, volume, or randomization contract drifted")

    reagent_identity = tuple(
        (
            row.stock_label, row.targets, row.units, row.droplet_volume_nL,
            row.fixed_stock_concentration, row.max_stock_concentration,
        )
        for row in case.design_case.reagents
    )
    if reagent_identity != (
        ("Range A", ("1", "2", "3", "5", "8", "13", "21", "34", "55", "89"), "x", "9", None, "400"),
        ("Range B", ("0.5", "2", "4", "8"), "x", "9", None, "100"),
        ("Range C", ("100", "140", "190"), "x", "9", None, "1600"),
        ("Range D", ("0.1", "0.5", "2"), "x", "9", None, "20"),
    ):
        raise Optimizer360CaseError("optimizer reagent input contract drifted")
    stock_identity = tuple(
        (row.stock_id, row.reagent_name, row.concentration, row.units, row.role)
        for row in case.stocks
    )
    if stock_identity != (
        (RANGE_A_STOCK_ID, "Range A", "222.22222222222223", "x", "non_fill"),
        (RANGE_B_STOCK_ID, "Range B", "100", "x", "non_fill"),
        (RANGE_C_STOCK_ID, "Range C", "555.5555555555555", "x", "non_fill"),
        (RANGE_D_STOCK_ID, "Range D", "20", "x", "non_fill"),
        (WATER_STOCK_ID, "Water", "1", "--", "fill"),
    ):
        raise Optimizer360CaseError("optimized stock identity contract drifted")

    reactions = case.design_case.expected.reactions
    reaction_ids = tuple(row.reaction_id for row in reactions)
    reaction_members = {tuple(row.targets) for row in reactions}
    if (
        reaction_ids != tuple(f"R{index}" for index in range(1, 361))
        or len(reaction_members) != 360
        or dict(reactions[0].targets) != {"Range A": "1", "Range B": "0.5", "Range C": "100", "Range D": "0.1"}
        or dict(reactions[-1].targets) != {"Range A": "89", "Range B": "8", "Range C": "190", "Range D": "2"}
    ):
        raise Optimizer360CaseError("literal full-factorial reaction order drifted")
    assignment_pairs = tuple((row.well_id, row.reaction_id) for row in case.assignments)
    if (
        len(assignment_pairs) != 360
        or len(set(assignment_pairs)) != 360
        or {well for well, _ in assignment_pairs} != expected_wells
        or {reaction for _, reaction in assignment_pairs} != set(reaction_ids)
        or assignment_pairs[0] != ("A1", "R66")
        or assignment_pairs[-1] != ("A24", "R131")
    ):
        raise Optimizer360CaseError("literal randomized reaction-to-well mapping drifted")

    calibration_identity = tuple(
        (
            row.order, row.stock_id, row.reagent_name, row.printer_head_id,
            row.print_pulse_width_us, row.droplet_volume_nL,
            row.input_revision, row.output_revision,
        )
        for row in case.calibrations
    )
    if calibration_identity != (
        (1, RANGE_A_STOCK_ID, "Range A", "virtual-head-m11a-range-a-v1", 1400, "10.8", 2, 3),
        (2, RANGE_B_STOCK_ID, "Range B", "virtual-head-m11a-range-b-v1", 1500, "12.6", 3, 4),
        (3, RANGE_C_STOCK_ID, "Range C", "virtual-head-m11a-range-c-v1", 1600, "14.4", 4, 5),
        (4, RANGE_D_STOCK_ID, "Range D", "virtual-head-m11a-range-d-v1", 1700, "16.2", 5, 6),
        (5, WATER_STOCK_ID, "Water", "virtual-head-m11a-water-v1", 1800, "18", 6, 7),
    ):
        raise Optimizer360CaseError("calibration/head/revision joins drifted")
    if len({row.printer_head_id for row in case.calibrations}) != 5:
        raise Optimizer360CaseError("each execution stock requires a distinct head")

    if case.optimizer_expectations.normalized() != {
        "approximate_targets": 7,
        "unreachable_targets": 0,
        "achieved_target_concentrations": {
            "Range A": {target: target for target in ("1", "2", "3", "5", "8", "13", "21", "34", "55", "89")},
            "Range B": {"0.5": "0.45", "2": "1.8", "4": "4.05", "8": "8.1"},
            "Range C": {target: target for target in ("100", "140", "190")},
            "Range D": {"0.1": "0.09", "0.5": "0.54", "2": "1.98"},
        },
    }:
        raise Optimizer360CaseError("nearest-achievable optimizer truth drifted")

    checkpoint_identity = tuple(
        (
            row.checkpoint_id, row.session, row.phase, row.plan_revision,
            row.progress_reference_revision, row.resume_reference_revision,
            row.eligibility,
        )
        for row in case.checkpoints
    )
    if checkpoint_identity != (
        ("prepared", 1, "prepared", 1, 1, None, "calibration_required"),
        ("locked_for_range_a", 1, "calibration_locked", 2, 2, None, "calibration_required"),
        ("range_a_calibrated", 1, "calibrated", 3, 3, None, "ready_to_start"),
        ("fresh_loaded", 2, "calibrated", 3, 3, None, "ready_to_start"),
        ("fresh_activated", 2, "calibrated", 3, 3, 3, "active"),
        ("range_b_calibrated", 2, "calibrated", 4, 4, 4, "active"),
        ("range_c_calibrated", 2, "calibrated", 5, 5, 5, "active"),
        ("range_d_calibrated", 2, "calibrated", 6, 6, 6, "active"),
        ("all_stocks_calibrated", 2, "calibrated", 7, 7, 7, "active"),
        ("completed", 2, "completed", 8, 8, 8, "analysis_only"),
        ("terminal_reloaded", 3, "completed", 8, 8, 8, "analysis_only"),
    ):
        raise Optimizer360CaseError("session/revision/progress-reference chain drifted")

    if tuple(row.checkpoint_id for row in case.count_maps) != OPTIMIZER_360_COUNT_CHECKPOINT_IDS:
        raise Optimizer360CaseError("count checkpoint order drifted")
    expected_count_keys = {
        (stock_id, well_id)
        for stock_id in OPTIMIZER_360_STOCK_IDS
        for well_id in expected_wells
    }
    previous_maps: dict[str, dict[str, int]] | None = None
    changed_stocks = (
        None, RANGE_A_STOCK_ID, RANGE_B_STOCK_ID, RANGE_C_STOCK_ID,
        RANGE_D_STOCK_ID, WATER_STOCK_ID,
    )
    for checkpoint_id, changed_stock in zip(OPTIMIZER_360_COUNT_CHECKPOINT_IDS, changed_stocks):
        compact = case.count_map(checkpoint_id)
        if set(compact.target_maps()) != set(OPTIMIZER_360_STOCK_IDS[:-1]):
            raise Optimizer360CaseError("non-fill target maps must cover four stocks")
        if set(compact.water_map()) != set(reaction_ids):
            raise Optimizer360CaseError("Water map must be keyed by all 360 reactions")
        oracle = case.oracle(checkpoint_id)
        if len(oracle.rows) != 1800 or set(oracle.keyed()) != expected_count_keys:
            raise Optimizer360CaseError("expanded oracle must cover 1,800 stock/well keys")
        observed = {
            stock_id: sum(
                count for (candidate, _), count in oracle.keyed().items()
                if candidate == stock_id
            )
            for stock_id in OPTIMIZER_360_STOCK_IDS
        }
        observed["total_droplets"] = sum(observed.values())
        if observed != case.aggregate(checkpoint_id):
            raise Optimizer360CaseError(
                f"literal aggregate totals drifted at {checkpoint_id}"
            )
        current_maps = compact.target_maps()
        if previous_maps is not None:
            for stock_id in OPTIMIZER_360_STOCK_IDS[:-1]:
                if stock_id != changed_stock and current_maps[stock_id] != previous_maps[stock_id]:
                    raise Optimizer360CaseError(
                        f"unaffected stock map changed at {checkpoint_id}: {stock_id}"
                    )
        previous_maps = current_maps

    pass_identity = tuple(
        (
            row.order, row.stock_id, row.expected_intents, row.expected_droplets,
            row.cumulative_completion, row.milestone,
        )
        for row in case.execution_passes
    )
    if pass_identity != (
        (1, RANGE_A_STOCK_ID, 360, 6948, 360, "range_a_pass_complete"),
        (2, RANGE_B_STOCK_ID, 360, 2070, 720, "range_b_pass_complete"),
        (3, RANGE_C_STOCK_ID, 360, 12960, 1080, "range_c_pass_complete"),
        (4, RANGE_D_STOCK_ID, 360, 1920, 1440, "range_d_pass_complete"),
        (5, WATER_STOCK_ID, 360, 22310, 1800, "water_pass_complete"),
    ):
        raise Optimizer360CaseError("execution pass identity/boundary contract drifted")
    if case.terminal != Optimizer360Terminal(1800, 46208, 1800, 5, 3, 8):
        raise Optimizer360CaseError("terminal exact-once contract drifted")
    final = case.oracle("all_stocks_calibrated").keyed()
    if max(final.values()) > 1000 or min(final.values()) <= 0:
        raise Optimizer360CaseError("simulator command limits drifted")
    if (
        sum(row.expected_intents for row in case.execution_passes) != 1800
        or sum(row.expected_droplets for row in case.execution_passes) != 46208
    ):
        raise Optimizer360CaseError("pass totals differ from terminal truth")
    if case.qualification.normalized() != {
        "cli_seed": 1,
        "action_cap": 160,
        "simulator_evidence_cap": 10000,
        "offscreen_timeout_seconds": 600,
        "visible_timeout_seconds": 900,
        "visible_speed": 20,
        "required_screenshots": [
            "optimizer_stocks_generated", "prepared_randomized", "range_a_calibrated",
            "fresh_loaded", "fresh_activated", "range_b_calibrated",
            "range_c_calibrated", "range_d_calibrated", "all_stocks_calibrated",
            "range_a_pass_complete", "range_b_pass_complete", "range_c_pass_complete",
            "range_d_pass_complete", "water_pass_complete", "completed", "terminal_reloaded",
        ],
    }:
        raise Optimizer360CaseError("qualification/evidence retention contract drifted")

    frozen = {
        "fixture": EXPECTED_FIXTURE_SHA256,
        "case": EXPECTED_CASE_SHA256,
        "reaction": EXPECTED_REACTION_MULTISET_SHA256,
        "achieved_reaction": EXPECTED_ACHIEVED_REACTION_MULTISET_SHA256,
        "assignment": EXPECTED_ASSIGNMENT_SHA256,
        "count": EXPECTED_COUNT_ORACLE_SHA256,
    }
    if all(frozen.values()):
        observed_hashes = {
            "fixture": optimizer_360_fixture_sha256(),
            "case": case.sha256(),
            "reaction": case.design_case.expected.reaction_multiset_sha256(),
            "achieved_reaction": case.achieved_design_oracle()["expected"]["reaction_multiset_sha256"],
            "assignment": case.design_case.expected.assignment_sha256(),
            "count": case.count_oracle_sha256(),
        }
        if observed_hashes != frozen:
            raise Optimizer360CaseError(
                f"frozen fixture/case/oracle hashes drifted: {observed_hashes!r}"
            )


def load_optimizer_360_case(path: Path | None = None) -> Optimizer360Case:
    fixture_path = Path(path or OPTIMIZER_360_FIXTURE_PATH).resolve()
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Optimizer360CaseError(f"could not load optimizer 360 fixture: {exc}") from exc
    if not isinstance(payload, dict):
        raise Optimizer360CaseError("optimizer 360 fixture root must be an object")
    return _parse_case(payload)


def optimizer_360_fixture_sha256(path: Path | None = None) -> str:
    return hashlib.sha256(Path(path or OPTIMIZER_360_FIXTURE_PATH).read_bytes()).hexdigest()


OPTIMIZER_360_CASE = load_optimizer_360_case()


__all__ = [
    "EXPECTED_ACHIEVED_REACTION_MULTISET_SHA256", "EXPECTED_ASSIGNMENT_SHA256",
    "EXPECTED_CASE_SHA256",
    "EXPECTED_COUNT_ORACLE_SHA256", "EXPECTED_FIXTURE_SHA256",
    "EXPECTED_REACTION_MULTISET_SHA256", "OPTIMIZER_360_CAPABILITY",
    "OPTIMIZER_360_CASE", "OPTIMIZER_360_CASE_ID",
    "OPTIMIZER_360_COUNT_CHECKPOINT_IDS", "OPTIMIZER_360_FIXTURE_PATH",
    "OPTIMIZER_360_SCENARIO_NAME", "OPTIMIZER_360_STOCK_IDS",
    "Optimizer360Case", "Optimizer360CaseError", "Optimizer360CountMap",
    "Optimizer360ExecutionPass", "Optimizer360Identity",
    "Optimizer360Expectations", "Optimizer360Qualification",
    "Optimizer360Terminal", "RANGE_A_STOCK_ID",
    "RANGE_B_STOCK_ID", "RANGE_C_STOCK_ID", "RANGE_D_STOCK_ID",
    "WATER_STOCK_ID", "load_optimizer_360_case", "optimizer_360_fixture_sha256",
    "validate_optimizer_360_case",
]
