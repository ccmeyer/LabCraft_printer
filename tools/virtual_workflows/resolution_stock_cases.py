"""Independent literal truth for resolution-first and paired-stock SIL.

This catalog deliberately imports no application optimizer, editor, calibration,
or execution implementation.  The JSON fixtures are the reviewed oracle; the
helpers below only validate identities and project those literals into the
existing composed-journey contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
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
    frozen_text_sha256,
)
from tools.virtual_workflows.joined_interaction_cases import (
    JoinedCalibration,
    JoinedCountOracle,
    JoinedStockWellCount,
)
from tools.virtual_workflows.optimizer_360_cases import (
    Optimizer360ExecutionPass,
    Optimizer360Identity,
    Optimizer360Qualification,
    Optimizer360Terminal,
)


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"
SINGLE_CASE_ID = "resolution_first_single_stock_terminal_v1"
TWO_STOCK_CASE_ID = "same_reagent_two_stock_calibration_terminal_v1"
PROGRESS_GUARD_CASE_ID = "same_reagent_two_stock_progress_guard_v1"
IMPORT_CASE_ID = "two_stock_csv_import_prepare_reload_v1"

SINGLE_FIXTURE_PATH = FIXTURE_ROOT / f"{SINGLE_CASE_ID}.json"
TWO_STOCK_FIXTURE_PATH = FIXTURE_ROOT / f"{TWO_STOCK_CASE_ID}.json"
PROGRESS_GUARD_FIXTURE_PATH = FIXTURE_ROOT / f"{PROGRESS_GUARD_CASE_ID}.json"
IMPORT_FIXTURE_PATH = FIXTURE_ROOT / f"{IMPORT_CASE_ID}.json"

# Filled from the normalized reviewed fixtures.  These constants are checked at
# import so fixture edits cannot silently rewrite the test oracle.
EXPECTED_FIXTURE_SHA256: Mapping[str, str] = {
    SINGLE_CASE_ID: "03a787d44a2d100a36c81d26bb685610f80412fbddffe2548a93a5c9a736e342",
    TWO_STOCK_CASE_ID: "f192748b45783cde552f70a666e2968ac48e3adcd312860a40bab1d20bf19292",
    PROGRESS_GUARD_CASE_ID: "f037bda7adbc777dd5a1d1b49250e668048f61eef2884b979123cf668bc6d66c",
    IMPORT_CASE_ID: "303f6ecadad083822634a8b2f1a6cf0fb9d05b51a1cadd8f40e657ec20c89262",
}
EXPECTED_CASE_SHA256: Mapping[str, str] = {
    SINGLE_CASE_ID: "b6e5a2abb157f8104347e8a6d9abe0c987dfd6c4d1fa999345c6b04b3866622c",
    TWO_STOCK_CASE_ID: "758e09ea983663d4454fcd8e21d5a70619b8557e76817791ec2be9801e69b2b6",
}


class ResolutionStockCaseError(ValueError):
    """Raised when independent stock-resolution truth is malformed."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResolutionStockCaseError(f"could not load {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResolutionStockCaseError(f"{path.name} must contain a JSON object")
    return value


@dataclass(frozen=True)
class ResolutionRank:
    total_distinct_level_loss: int
    worst_reagent_level_loss: int
    stock_solution_count: int
    worst_abs_error: float
    mean_abs_error: float
    concentration_burden: float
    printed_volume_nL: float

    def __post_init__(self) -> None:
        for name in (
            "total_distinct_level_loss",
            "worst_reagent_level_loss",
            "stock_solution_count",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ResolutionStockCaseError(f"{name} must be a non-negative integer")
        for name in (
            "worst_abs_error",
            "mean_abs_error",
            "concentration_burden",
            "printed_volume_nL",
        ):
            if float(getattr(self, name)) < 0:
                raise ResolutionStockCaseError(f"{name} must be non-negative")

    def normalized(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class OptimizerExpectation:
    strategy: str
    seed_rank: ResolutionRank
    selected_rank: ResolutionRank
    improved_seed: bool
    allowed_stop_reasons: tuple[str, ...]
    maximum_time_to_best_ms: float
    maximum_resolution_elapsed_ms: float
    maximum_states: int
    maximum_pairs: int

    def normalized(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "seed_rank": self.seed_rank.normalized(),
            "selected_rank": self.selected_rank.normalized(),
            "improved_seed": self.improved_seed,
            "allowed_stop_reasons": list(self.allowed_stop_reasons),
            "maximum_time_to_best_ms": self.maximum_time_to_best_ms,
            "maximum_resolution_elapsed_ms": self.maximum_resolution_elapsed_ms,
            "maximum_states": self.maximum_states,
            "maximum_pairs": self.maximum_pairs,
        }


@dataclass(frozen=True)
class ResolutionStockCase:
    case_id: str
    schema_version: int
    identity: Optimizer360Identity
    design_case: ExperimentDesignCase
    calibrations: tuple[JoinedCalibration, ...]
    count_maps: tuple[tuple[str, tuple[JoinedStockWellCount, ...]], ...]
    optimizer_expectations: OptimizerExpectation
    execution_passes: tuple[Optimizer360ExecutionPass, ...]
    qualification: Optimizer360Qualification
    terminal: Optimizer360Terminal
    raw_fixture: Mapping[str, Any]

    @property
    def editor(self) -> DesignExperimentInput:
        return self.design_case.experiment

    @property
    def stocks(self) -> tuple[ExpectedDesignStock, ...]:
        return self.design_case.expected.stocks

    @property
    def assignments(self) -> tuple[ExpectedWellAssignment, ...]:
        return self.design_case.expected.assignments

    def oracle(self, checkpoint_id: str) -> JoinedCountOracle:
        matches = [rows for name, rows in self.count_maps if name == checkpoint_id]
        if len(matches) != 1:
            raise ResolutionStockCaseError(f"unknown count checkpoint {checkpoint_id!r}")
        return JoinedCountOracle(checkpoint_id, matches[0])

    def editor_specification(self) -> dict[str, Any]:
        experiment = dict(self.raw_fixture["experiment"])
        experiment["name"] = self.editor.name
        experiment["expected_reaction_count"] = self.design_case.expected.reaction_count
        return {
            "experiment": experiment,
            "reagents": [row.normalized() for row in self.design_case.reagents],
            "optimization_attempts": [
                row.normalized() for row in self.design_case.optimization_attempts
            ],
            "expected": self.design_case.expected.normalized(),
        }

    def normalized(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "schema_version": self.schema_version,
            "identity": self.identity.normalized(),
            "design_case": self.design_case.normalized(),
            "calibrations": [row.normalized() for row in self.calibrations],
            "count_maps": {
                name: [row.normalized() for row in rows]
                for name, rows in self.count_maps
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
            [JoinedCountOracle(name, rows).normalized() for name, rows in self.count_maps]
        )


def _parse_case(path: Path) -> ResolutionStockCase:
    payload = _read_object(path)
    case_id = str(payload.get("case_id") or "")
    experiment_payload = dict(payload["experiment"])
    allow_grouping = experiment_payload.pop("allow_avoidable_target_grouping")
    experiment_payload.pop("fill_droplet_volume_nL", None)
    if allow_grouping is not False:
        raise ResolutionStockCaseError("resolution SIL requires grouping disabled")
    experiment = DesignExperimentInput(
        **{
            **experiment_payload,
            "selected_well_ids": tuple(experiment_payload["selected_well_ids"]),
            "excluded_well_ids": tuple(experiment_payload["excluded_well_ids"]),
            "name": payload["identity"]["experiment_name"],
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
    count_maps = tuple(
        (
            checkpoint,
            tuple(JoinedStockWellCount(**row) for row in rows),
        )
        for checkpoint, rows in payload["count_maps"].items()
    )
    prepared_rows = dict(count_maps)["prepared"]
    design_case = ExperimentDesignCase(
        case_id=case_id,
        experiment=experiment,
        reagents=reagents,
        optimization_attempts=(
            DesignOptimizationAttempt(experiment.allow_two_stock_solutions, "generated"),
        ),
        expected=ExpectedDesignOutcome(
            terminal="prepared",
            reaction_count=len(reactions),
            stocks=stocks,
            reactions=reactions,
            assignments=assignments,
            stock_well_counts=tuple(
                ExpectedStockWellCount(row.stock_id, row.well_id, row.target_droplets)
                for row in prepared_rows
            ),
        ),
        coverage_tags=frozenset(
            {
                "targets:multiple",
                "assignment:natural",
                "replicates:one",
                "terminal:prepared",
                "stock:optimized_two"
                if experiment.allow_two_stock_solutions
                else "stock:optimized_one",
                "reagents:single" if len(reagents) == 1 else "reagents:multiple",
            }
        ),
    )
    optimizer = payload["optimizer_expectations"]
    case = ResolutionStockCase(
        case_id=case_id,
        schema_version=int(payload["schema_version"]),
        identity=Optimizer360Identity(**payload["identity"]),
        design_case=design_case,
        calibrations=tuple(JoinedCalibration(**row) for row in payload["calibrations"]),
        count_maps=count_maps,
        optimizer_expectations=OptimizerExpectation(
            strategy=str(optimizer["strategy"]),
            seed_rank=ResolutionRank(**optimizer["seed_rank"]),
            selected_rank=ResolutionRank(**optimizer["selected_rank"]),
            improved_seed=bool(optimizer["improved_seed"]),
            allowed_stop_reasons=tuple(optimizer["allowed_stop_reasons"]),
            maximum_time_to_best_ms=float(optimizer["maximum_time_to_best_ms"]),
            maximum_resolution_elapsed_ms=float(
                optimizer["maximum_resolution_elapsed_ms"]
            ),
            maximum_states=int(optimizer["maximum_states"]),
            maximum_pairs=int(optimizer["maximum_pairs"]),
        ),
        execution_passes=tuple(
            Optimizer360ExecutionPass(**row) for row in payload["execution_passes"]
        ),
        qualification=Optimizer360Qualification(
            **{
                **payload["qualification"],
                "required_screenshots": tuple(
                    payload["qualification"]["required_screenshots"]
                ),
            }
        ),
        terminal=Optimizer360Terminal(**payload["terminal"]),
        raw_fixture=payload,
    )
    validate_case(case, path)
    return case


def validate_case(case: ResolutionStockCase, path: Path) -> None:
    if case.schema_version != 1 or case.case_id != path.stem:
        raise ResolutionStockCaseError("case identity or version drifted")
    if len({row.stock_id for row in case.stocks}) != len(case.stocks):
        raise ResolutionStockCaseError("runtime stock IDs must be unique")
    if len({row.printer_head_id for row in case.calibrations}) != len(case.calibrations):
        raise ResolutionStockCaseError("calibration head identities must be unique")
    if {row.stock_id for row in case.calibrations} != {
        row.stock_id for row in case.stocks
    }:
        raise ResolutionStockCaseError("every stock requires one calibration identity")
    expected_keys = {
        (row.stock_id, row.well_id)
        for row in case.oracle("all_stocks_calibrated").rows
    }
    if len(expected_keys) != case.terminal.expected_intents:
        raise ResolutionStockCaseError("terminal intent count differs from literal counts")
    if sum(row.target_droplets for row in case.oracle("all_stocks_calibrated").rows) != (
        case.terminal.expected_droplets
    ):
        raise ResolutionStockCaseError("terminal droplet total differs from literal counts")
    if sum(row.expected_intents for row in case.execution_passes) != (
        case.terminal.expected_intents
    ) or sum(row.expected_droplets for row in case.execution_passes) != (
        case.terminal.expected_droplets
    ):
        raise ResolutionStockCaseError("execution-pass totals differ from terminal truth")
    if [row.output_revision for row in case.calibrations] != list(
        range(3, 3 + len(case.calibrations))
    ) or case.terminal.terminal_revision != case.calibrations[-1].output_revision + 1:
        raise ResolutionStockCaseError("revision sequence drifted")
    if case.optimizer_expectations.seed_rank.total_distinct_level_loss != 1:
        raise ResolutionStockCaseError("frozen seed must lose exactly one level")
    if case.optimizer_expectations.selected_rank.total_distinct_level_loss != 0:
        raise ResolutionStockCaseError("selected resolution-first plan must lose no levels")
    frozen_fixture = EXPECTED_FIXTURE_SHA256.get(case.case_id)
    frozen_case = EXPECTED_CASE_SHA256.get(case.case_id)
    observed = (frozen_text_sha256(path), case.sha256())
    if frozen_fixture and observed[0] != frozen_fixture:
        raise ResolutionStockCaseError(f"fixture hash drifted for {case.case_id}: {observed[0]}")
    if frozen_case and observed[1] != frozen_case:
        raise ResolutionStockCaseError(f"case hash drifted for {case.case_id}: {observed[1]}")


def load_resolution_stock_case(case_id: str) -> ResolutionStockCase:
    paths = {SINGLE_CASE_ID: SINGLE_FIXTURE_PATH, TWO_STOCK_CASE_ID: TWO_STOCK_FIXTURE_PATH}
    try:
        return _parse_case(paths[str(case_id)])
    except KeyError as exc:
        raise ResolutionStockCaseError(f"unknown resolution stock case {case_id!r}") from exc


def load_auxiliary_fixture(case_id: str) -> tuple[dict[str, Any], Path]:
    paths = {
        PROGRESS_GUARD_CASE_ID: PROGRESS_GUARD_FIXTURE_PATH,
        IMPORT_CASE_ID: IMPORT_FIXTURE_PATH,
    }
    try:
        path = paths[str(case_id)]
    except KeyError as exc:
        raise ResolutionStockCaseError(f"unknown auxiliary case {case_id!r}") from exc
    payload = _read_object(path)
    if str(payload.get("fixture_id")) != str(case_id) or payload.get("schema_version") != 1:
        raise ResolutionStockCaseError("auxiliary fixture identity or version drifted")
    frozen = EXPECTED_FIXTURE_SHA256.get(str(case_id))
    if frozen and frozen_text_sha256(path) != frozen:
        raise ResolutionStockCaseError(f"fixture hash drifted for {case_id}")
    return payload, path


SINGLE_CASE = load_resolution_stock_case(SINGLE_CASE_ID)
TWO_STOCK_CASE = load_resolution_stock_case(TWO_STOCK_CASE_ID)


__all__ = [
    "EXPECTED_CASE_SHA256",
    "EXPECTED_FIXTURE_SHA256",
    "FIXTURE_ROOT",
    "IMPORT_CASE_ID",
    "IMPORT_FIXTURE_PATH",
    "PROGRESS_GUARD_CASE_ID",
    "PROGRESS_GUARD_FIXTURE_PATH",
    "ResolutionRank",
    "ResolutionStockCase",
    "ResolutionStockCaseError",
    "SINGLE_CASE",
    "SINGLE_CASE_ID",
    "SINGLE_FIXTURE_PATH",
    "TWO_STOCK_CASE",
    "TWO_STOCK_CASE_ID",
    "TWO_STOCK_FIXTURE_PATH",
    "load_auxiliary_fixture",
    "load_resolution_stock_case",
    "validate_case",
]
