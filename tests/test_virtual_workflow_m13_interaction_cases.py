from __future__ import annotations

from dataclasses import replace

import pytest

from tools.virtual_workflows.m13_interaction_cases import (
    ASSIGNMENTS,
    COMPACT_CASE,
    DESIGN_CASE,
    EXPECTED_CASE_SHA256,
    EXPECTED_DESIGN_CASE_SHA256,
    EXPECTED_REFINALIZED_CASE_SHA256,
    EXPECTED_REFINALIZED_DESIGN_CASE_SHA256,
    REFINALIZED_COMPACT_CASE,
    REFINALIZED_DESIGN_CASE,
    fixture_projection,
    validate_compact_case,
)


def test_compact_case_hashes_and_literal_workload_are_frozen():
    assert COMPACT_CASE.sha256() == EXPECTED_CASE_SHA256
    assert DESIGN_CASE.sha256() == EXPECTED_DESIGN_CASE_SHA256
    assert REFINALIZED_COMPACT_CASE.sha256() == EXPECTED_REFINALIZED_CASE_SHA256
    assert REFINALIZED_DESIGN_CASE.sha256() == (
        EXPECTED_REFINALIZED_DESIGN_CASE_SHA256
    )
    assert tuple(
        (row.well_id, row.reaction_id) for row in COMPACT_CASE.assignments
    ) == ASSIGNMENTS
    assert [
        (row.stock_id, row.expected_intents, row.expected_droplets)
        for row in COMPACT_CASE.execution_passes
    ] == [
        ("Capacity A_10.00_x", 4, 6),
        ("Water_1.00_--", 4, 38),
    ]
    assert (
        COMPACT_CASE.terminal.expected_intents,
        COMPACT_CASE.terminal.expected_droplets,
        COMPACT_CASE.terminal.expected_completed_wells,
    ) == (8, 44, 8)


def test_compact_calibration_and_qualification_contracts_are_exact():
    assert [
        (row.stock_id, row.print_pulse_width_us, row.droplet_volume_nL)
        for row in COMPACT_CASE.calibrations
    ] == [
        ("Capacity A_10.00_x", 1300, "9"),
        ("Water_1.00_--", 1300, "9"),
    ]
    assert COMPACT_CASE.qualification.action_cap == 80
    assert COMPACT_CASE.qualification.required_screenshots == (
        "prepared",
        "fresh_loaded",
        "fresh_activated",
        "terminal_reloaded",
    )
    validate_compact_case()


def test_refinalization_changes_reagent_input_but_preserves_literal_outcome():
    assert DESIGN_CASE.reagents[0].targets == ("1", "2")
    assert REFINALIZED_DESIGN_CASE.reagents[0].targets == ("0.9", "1.8")
    assert REFINALIZED_DESIGN_CASE.expected == DESIGN_CASE.expected
    assert REFINALIZED_COMPACT_CASE.execution_passes == COMPACT_CASE.execution_passes
    assert REFINALIZED_COMPACT_CASE.terminal == COMPACT_CASE.terminal


def test_projection_is_in_memory_versioned_and_source_owned():
    projection, source = fixture_projection(
        "seed_13_legal_design_calibration_terminal"
    )
    assert projection["schema_version"] == 1
    assert projection["case_sha256"] == EXPECTED_CASE_SHA256
    assert projection["design_case_sha256"] == EXPECTED_DESIGN_CASE_SHA256
    assert source.name == "m13_interaction_cases.py"


def test_compact_case_rejects_budget_drift():
    changed = replace(
        COMPACT_CASE,
        qualification=replace(COMPACT_CASE.qualification, action_cap=79),
    )
    with pytest.raises(ValueError, match="qualification budget drifted"):
        validate_compact_case(changed)
