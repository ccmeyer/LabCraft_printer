"""Literal compact execution truth for Milestone 13 generated exploration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

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
    JoinedAssignment,
    JoinedCalibration,
    JoinedCountOracle,
    JoinedEditorInput,
    JoinedExecutionPass,
    JoinedQualification,
    JoinedStock,
    JoinedStockWellCount,
    JoinedTerminalOracle,
)


CASE_ID = "m13_compact_randomized_capacity_v1"
CAPACITY_STOCK_ID = "Capacity A_10.00_x"
WATER_STOCK_ID = "Water_1.00_--"
WELL_IDS = ("B1", "B2", "B3", "B4")
ASSIGNMENTS = (("B1", "R4"), ("B2", "R2"), ("B3", "R1"), ("B4", "R3"))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


DESIGN_CASE = ExperimentDesignCase(
    case_id=CASE_ID,
    experiment=DesignExperimentInput(
        name="sil-m13-compact-randomized-capacity",
        plate_name="shallow-384_well_plate",
        replicates=2,
        selected_well_ids=WELL_IDS,
        excluded_well_ids=(),
        printed_volume_nL="100",
        final_volume_nL="100",
        randomize_assignments=True,
        random_seed=4321,
        allow_two_stock_solutions=True,
    ),
    reagents=(
        DesignReagentInput(
            "Capacity A",
            "Additive",
            "droplet",
            "0",
            ("1", "2"),
            "x",
            "10",
            "10",
        ),
    ),
    optimization_attempts=(DesignOptimizationAttempt(True, "generated"),),
    expected=ExpectedDesignOutcome(
        terminal="prepared",
        reaction_count=4,
        stocks=(
            ExpectedDesignStock(CAPACITY_STOCK_ID, "Capacity A", "10", "x"),
            ExpectedDesignStock(WATER_STOCK_ID, "Water", "1", "--", role="fill"),
        ),
        reactions=(
            ExpectedDesignReaction("R1", 1, (("Capacity A", "1"),)),
            ExpectedDesignReaction("R2", 1, (("Capacity A", "2"),)),
            ExpectedDesignReaction("R3", 2, (("Capacity A", "1"),)),
            ExpectedDesignReaction("R4", 2, (("Capacity A", "2"),)),
        ),
        assignments=tuple(ExpectedWellAssignment(*row) for row in ASSIGNMENTS),
        stock_well_counts=(
            ExpectedStockWellCount(CAPACITY_STOCK_ID, "B1", 2),
            ExpectedStockWellCount(WATER_STOCK_ID, "B1", 9),
            ExpectedStockWellCount(CAPACITY_STOCK_ID, "B2", 2),
            ExpectedStockWellCount(WATER_STOCK_ID, "B2", 9),
            ExpectedStockWellCount(CAPACITY_STOCK_ID, "B3", 1),
            ExpectedStockWellCount(WATER_STOCK_ID, "B3", 10),
            ExpectedStockWellCount(CAPACITY_STOCK_ID, "B4", 1),
            ExpectedStockWellCount(WATER_STOCK_ID, "B4", 10),
        ),
    ),
    coverage_tags=frozenset(
        {
            "reagents:single",
            "targets:multiple",
            "stock:fixed_one",
            "assignment:randomized",
            "capacity:exact",
            "replicates:multiple",
            "terminal:prepared",
            "comparison:same_seed_replay",
            "evidence:reload_runtime",
        }
    ),
)


_COUNT_ROWS = tuple(
    JoinedStockWellCount(row.stock_id, row.well_id, row.target_droplets)
    for row in DESIGN_CASE.expected.stock_well_counts
)


@dataclass(frozen=True)
class M13CompactInteractionCase:
    case_id: str
    design_case: ExperimentDesignCase
    editor: JoinedEditorInput
    stocks: tuple[JoinedStock, ...]
    assignments: tuple[JoinedAssignment, ...]
    calibrations: tuple[JoinedCalibration, ...]
    count_oracles: tuple[JoinedCountOracle, ...]
    execution_passes: tuple[JoinedExecutionPass, ...]
    qualification: JoinedQualification
    terminal: JoinedTerminalOracle

    def oracle(self, checkpoint_id: str) -> JoinedCountOracle:
        matches = [row for row in self.count_oracles if row.checkpoint_id == checkpoint_id]
        if len(matches) != 1:
            raise ValueError(f"unknown compact count oracle: {checkpoint_id!r}")
        return matches[0]

    def normalized(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "design_case": self.design_case.normalized(),
            "editor": self.editor.normalized(),
            "stocks": [row.normalized() for row in self.stocks],
            "assignments": [row.normalized() for row in self.assignments],
            "calibrations": [row.normalized() for row in self.calibrations],
            "count_oracles": {
                row.checkpoint_id: [item.normalized() for item in row.rows]
                for row in self.count_oracles
            },
            "execution_passes": [row.normalized() for row in self.execution_passes],
            "qualification": self.qualification.normalized(),
            "terminal": self.terminal.normalized(),
        }

    def sha256(self) -> str:
        return _sha256_json(self.normalized())


COMPACT_CASE = M13CompactInteractionCase(
    case_id=CASE_ID,
    design_case=DESIGN_CASE,
    editor=JoinedEditorInput(
        experiment_name=DESIGN_CASE.experiment.name,
        plate_name=DESIGN_CASE.experiment.plate_name,
        replicates=DESIGN_CASE.experiment.replicates,
        selected_well_ids=WELL_IDS,
        printed_volume_nL=DESIGN_CASE.experiment.printed_volume_nL,
        final_volume_nL=DESIGN_CASE.experiment.final_volume_nL,
        randomize_assignments=True,
        random_seed=4321,
    ),
    stocks=(
        JoinedStock(CAPACITY_STOCK_ID, "Capacity A", "non_fill"),
        JoinedStock(WATER_STOCK_ID, "Water", "fill"),
    ),
    assignments=tuple(JoinedAssignment(*row) for row in ASSIGNMENTS),
    calibrations=(
        JoinedCalibration(
            1,
            CAPACITY_STOCK_ID,
            "Capacity A",
            "virtual-head-m13-capacity-v1",
            1300,
            "9",
            2,
            3,
        ),
        JoinedCalibration(
            2,
            WATER_STOCK_ID,
            "Water",
            "virtual-head-m13-water-v1",
            1300,
            "9",
            3,
            4,
        ),
    ),
    count_oracles=tuple(
        JoinedCountOracle(checkpoint, _COUNT_ROWS)
        for checkpoint in (
            "prepared",
            "calibrated_zero_progress",
            "all_stocks_calibrated",
        )
    ),
    execution_passes=(
        JoinedExecutionPass(1, CAPACITY_STOCK_ID, 4, 6),
        JoinedExecutionPass(2, WATER_STOCK_ID, 4, 38),
    ),
    qualification=JoinedQualification(
        cli_seed=13,
        action_cap=80,
        offscreen_timeout_seconds=270,
        visible_timeout_seconds=270,
        visible_speed=20,
        required_screenshots=(
            "prepared",
            "fresh_loaded",
            "fresh_activated",
            "terminal_reloaded",
        ),
    ),
    terminal=JoinedTerminalOracle(8, 44, 8, 2, 3),
)

REFINALIZED_DESIGN_CASE = replace(
    DESIGN_CASE,
    experiment=replace(
        DESIGN_CASE.experiment,
        name="sil-m13-compact-randomized-capacity-refinalized",
    ),
    reagents=(
        replace(DESIGN_CASE.reagents[0], targets=("0.9", "1.8")),
    ),
)
REFINALIZED_COMPACT_CASE = replace(
    COMPACT_CASE,
    design_case=REFINALIZED_DESIGN_CASE,
    editor=replace(
        COMPACT_CASE.editor,
        experiment_name=REFINALIZED_DESIGN_CASE.experiment.name,
    ),
)


def validate_compact_case(case: M13CompactInteractionCase = COMPACT_CASE) -> None:
    if case.case_id != CASE_ID or case.design_case.expected.reaction_count != 4:
        raise ValueError("compact case identity/reaction count drifted")
    if tuple(row.well_id for row in case.assignments) != WELL_IDS:
        raise ValueError("compact case well identity drifted")
    if tuple((row.well_id, row.reaction_id) for row in case.assignments) != ASSIGNMENTS:
        raise ValueError("compact literal randomized assignments drifted")
    expected_keys = {(row.stock_id, row.well_id) for row in _COUNT_ROWS}
    if len(expected_keys) != 8:
        raise ValueError("compact count key cardinality drifted")
    for checkpoint in ("prepared", "calibrated_zero_progress", "all_stocks_calibrated"):
        if set(case.oracle(checkpoint).keyed()) != expected_keys:
            raise ValueError("compact count oracle key set drifted")
    if sum(row.expected_intents for row in case.execution_passes) != 8:
        raise ValueError("compact intent total drifted")
    if sum(row.expected_droplets for row in case.execution_passes) != 44:
        raise ValueError("compact droplet total drifted")
    final = case.oracle("all_stocks_calibrated").keyed()
    for execution_pass in case.execution_passes:
        if sum(value for (stock_id, _), value in final.items() if stock_id == execution_pass.stock_id) != execution_pass.expected_droplets:
            raise ValueError("compact pass droplet total drifted")
    if case.qualification.action_cap != 80 or len(case.qualification.required_screenshots) != 4:
        raise ValueError("compact qualification budget drifted")


EXPECTED_CASE_SHA256 = "46d6c60efd32bf4671c631f80e75bace7312698eaea40d3fa32ef598a682aa25"
EXPECTED_DESIGN_CASE_SHA256 = "48a35b0b3dde09f480becab480c0bd814ce723a5ba1d182831a9dd22977f723e"
EXPECTED_REFINALIZED_CASE_SHA256 = "c44570843ef88c6842948c90a87d2e83aff94de2ed4297f5a62214266a096851"
EXPECTED_REFINALIZED_DESIGN_CASE_SHA256 = "53eb5d4b71deba808363ed9d0494afc6c2ad5af6e6f303d9e1b1538b0269bb01"

validate_compact_case()
if COMPACT_CASE.sha256() != EXPECTED_CASE_SHA256:
    raise ValueError("reviewed compact case SHA-256 drifted")
if DESIGN_CASE.sha256() != EXPECTED_DESIGN_CASE_SHA256:
    raise ValueError("reviewed compact design SHA-256 drifted")
if REFINALIZED_COMPACT_CASE.sha256() != EXPECTED_REFINALIZED_CASE_SHA256:
    raise ValueError("reviewed refinalized compact case SHA-256 drifted")
if REFINALIZED_DESIGN_CASE.sha256() != EXPECTED_REFINALIZED_DESIGN_CASE_SHA256:
    raise ValueError("reviewed refinalized compact design SHA-256 drifted")


def fixture_projection(sequence_id: str) -> tuple[dict[str, Any], Path]:
    """Return an in-memory fixture projection; no authoritative file is mutated."""

    from tools.virtual_workflows.experiment_design_cases import editor_specification

    return (
        {
            "schema_version": 1,
            "fixture_id": f"{CASE_ID}__{sequence_id}",
            "case": COMPACT_CASE.normalized(),
            "specification": editor_specification(DESIGN_CASE),
            "sequence_id": sequence_id,
            "case_sha256": EXPECTED_CASE_SHA256,
            "design_case_sha256": EXPECTED_DESIGN_CASE_SHA256,
        },
        Path(__file__).resolve(),
    )


__all__ = [
    "ASSIGNMENTS",
    "CAPACITY_STOCK_ID",
    "CASE_ID",
    "COMPACT_CASE",
    "DESIGN_CASE",
    "EXPECTED_CASE_SHA256",
    "EXPECTED_DESIGN_CASE_SHA256",
    "EXPECTED_REFINALIZED_CASE_SHA256",
    "EXPECTED_REFINALIZED_DESIGN_CASE_SHA256",
    "REFINALIZED_COMPACT_CASE",
    "REFINALIZED_DESIGN_CASE",
    "WATER_STOCK_ID",
    "WELL_IDS",
    "fixture_projection",
    "validate_compact_case",
]
