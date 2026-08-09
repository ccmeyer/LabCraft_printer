from __future__ import annotations

import ast
import json
from dataclasses import replace

import pytest

from tools.virtual_workflows.experiment_design_cases import (
    EXPERIMENT_DESIGN_CASES,
    planned_catalog_sha256,
)
from tools.virtual_workflows.joined_interaction_cases import (
    JOINED_INTERACTION_CASE,
    joined_fixture_sha256,
)
from tools.virtual_workflows.optimizer_360_cases import (
    EXPECTED_ASSIGNMENT_SHA256,
    EXPECTED_CASE_SHA256,
    EXPECTED_COUNT_ORACLE_SHA256,
    EXPECTED_FIXTURE_SHA256,
    EXPECTED_REACTION_MULTISET_SHA256,
    OPTIMIZER_360_CASE,
    OPTIMIZER_360_CASE_ID,
    OPTIMIZER_360_FIXTURE_PATH,
    OPTIMIZER_360_STOCK_IDS,
    RANGE_A_STOCK_ID,
    RANGE_B_STOCK_ID,
    RANGE_C_STOCK_ID,
    RANGE_D_STOCK_ID,
    WATER_STOCK_ID,
    Optimizer360CaseError,
    load_optimizer_360_case,
    optimizer_360_fixture_sha256,
    validate_optimizer_360_case,
)


MILESTONE_10_CATALOG_SHA256 = (
    "15ec261cf19bec2f2758d76f8c8102d0d246eef02ff165a4bdb104b1a9e8dfcd"
)
MILESTONE_11_CASE_SHA256 = (
    "3081ebadd38a9e9de465f67e855ce63a471d7f9092e65e9f7881da1923d509cd"
)
MILESTONE_11_FIXTURE_SHA256 = (
    "bf9631efdf2e0ad04e2310b378330a87941d05c157d69a6c47b69b645dbbe118"
)


def test_literal_fixture_and_all_expanded_oracle_hashes_are_frozen():
    loaded = load_optimizer_360_case()

    assert loaded == OPTIMIZER_360_CASE
    assert loaded.case_id == OPTIMIZER_360_CASE_ID
    assert optimizer_360_fixture_sha256() == EXPECTED_FIXTURE_SHA256
    assert loaded.sha256() == EXPECTED_CASE_SHA256
    assert (
        loaded.design_case.expected.reaction_multiset_sha256()
        == EXPECTED_REACTION_MULTISET_SHA256
    )
    assert loaded.design_case.expected.assignment_sha256() == EXPECTED_ASSIGNMENT_SHA256
    assert loaded.count_oracle_sha256() == EXPECTED_COUNT_ORACLE_SHA256


def test_case_is_standalone_and_does_not_change_milestone_10_or_11_truth():
    assert len(EXPERIMENT_DESIGN_CASES) == 9
    assert OPTIMIZER_360_CASE_ID not in {row.case_id for row in EXPERIMENT_DESIGN_CASES}
    assert planned_catalog_sha256() == MILESTONE_10_CATALOG_SHA256
    assert JOINED_INTERACTION_CASE.sha256() == MILESTONE_11_CASE_SHA256
    assert joined_fixture_sha256() == MILESTONE_11_FIXTURE_SHA256


def test_oracle_module_has_no_production_or_expected_value_algorithm_imports():
    source_path = OPTIMIZER_360_FIXTURE_PATH.parent.parent / "optimizer_360_cases.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert not any(
        name.startswith(("FreeRTOS-interface", "Model", "Controller", "View"))
        for name in imported
    )
    assert "normalize_stock_well_counts" not in source
    assert "round(" not in source


def test_optimizer_inputs_reactions_assignment_and_row_p_exclusion_are_literal():
    case = OPTIMIZER_360_CASE
    reactions = case.design_case.expected.reactions
    assignments = case.assignments

    assert all(row.fixed_stock_concentration is None for row in case.design_case.reagents)
    assert [row.max_stock_concentration for row in case.design_case.reagents] == [
        "400", "100", "1600", "20"
    ]
    assert [row.concentration for row in case.stocks] == ["200", "100", "1000", "20", "1"]
    assert len(reactions) == len(assignments) == 360
    assert dict(reactions[0].targets) == {
        "Range A": "1", "Range B": "0.5", "Range C": "100", "Range D": "0.1"
    }
    assert dict(reactions[-1].targets) == {
        "Range A": "89", "Range B": "8", "Range C": "190", "Range D": "2"
    }
    assert [(row.well_id, row.reaction_id) for row in assignments[:4]] == [
        ("A1", "R66"), ("B1", "R136"), ("C1", "R163"), ("D1", "R155")
    ]
    assert not any(row.well_id.startswith("P") for row in assignments)
    assert {row.well_id for row in assignments} == {
        f"{letter}{column}"
        for letter in "ABCDEFGHIJKLMNO"
        for column in range(1, 25)
    }


def test_every_checkpoint_expands_to_identity_keyed_counts_and_literal_totals():
    case = OPTIMIZER_360_CASE
    expected_totals = {
        "prepared": (8316, 2610, 10320, 3120, 47634, 72000),
        "range_a_calibrated": (6948, 2610, 10320, 3120, 47634, 70632),
        "range_b_calibrated": (6948, 1890, 10320, 3120, 47535, 69813),
        "range_c_calibrated": (6948, 1890, 6480, 3120, 47535, 65973),
        "range_d_calibrated": (6948, 1890, 6480, 1800, 47407, 64525),
        "all_stocks_calibrated": (6948, 1890, 6480, 1800, 23706, 40824),
    }
    expected_keys = {
        (stock_id, assignment.well_id)
        for stock_id in OPTIMIZER_360_STOCK_IDS
        for assignment in case.assignments
    }

    for checkpoint_id, totals in expected_totals.items():
        keyed = case.oracle(checkpoint_id).keyed()
        assert len(keyed) == 1800
        assert set(keyed) == expected_keys
        aggregate = case.aggregate(checkpoint_id)
        assert tuple(aggregate[stock_id] for stock_id in OPTIMIZER_360_STOCK_IDS) + (
            aggregate["total_droplets"],
        ) == totals

    prepared = case.count_map("prepared").target_maps()
    final = case.count_map("all_stocks_calibrated").target_maps()
    assert list(prepared[RANGE_A_STOCK_ID].values()) == [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]
    assert list(final[RANGE_A_STOCK_ID].values()) == [1, 2, 2, 4, 7, 11, 18, 28, 46, 74]
    assert list(final[RANGE_B_STOCK_ID].values()) == [1, 3, 6, 11]
    assert list(final[RANGE_C_STOCK_ID].values()) == [12, 18, 24]
    assert list(final[RANGE_D_STOCK_ID].values()) == [1, 3, 11]


def test_five_calibrations_passes_revisions_and_terminal_exact_once_are_literal():
    case = OPTIMIZER_360_CASE

    assert [row.stock_id for row in case.calibrations] == list(OPTIMIZER_360_STOCK_IDS)
    assert [row.print_pulse_width_us for row in case.calibrations] == [1400, 1500, 1600, 1700, 1800]
    assert [row.droplet_volume_nL for row in case.calibrations] == ["10.8", "12.6", "14.4", "16.2", "18"]
    assert len({row.printer_head_id for row in case.calibrations}) == 5
    assert [row.output_revision for row in case.calibrations] == [3, 4, 5, 6, 7]
    assert [row.cumulative_completion for row in case.execution_passes] == [
        360, 720, 1080, 1440, 1800
    ]
    assert [row.expected_droplets for row in case.execution_passes] == [
        6948, 1890, 6480, 1800, 23706
    ]
    assert case.terminal.expected_intents == 1800
    assert case.terminal.expected_droplets == 40824
    assert case.terminal.terminal_revision == 8


@pytest.mark.parametrize(
    "changed",
    [
        replace(
            OPTIMIZER_360_CASE,
            identity=replace(OPTIMIZER_360_CASE.identity, simulation_seed=2),
        ),
        replace(
            OPTIMIZER_360_CASE,
            calibrations=(
                replace(OPTIMIZER_360_CASE.calibrations[0], printer_head_id="wrong"),
            ) + OPTIMIZER_360_CASE.calibrations[1:],
        ),
        replace(
            OPTIMIZER_360_CASE,
            execution_passes=(
                replace(OPTIMIZER_360_CASE.execution_passes[0], expected_intents=359),
            ) + OPTIMIZER_360_CASE.execution_passes[1:],
        ),
        replace(
            OPTIMIZER_360_CASE,
            terminal=replace(OPTIMIZER_360_CASE.terminal, expected_droplets=40823),
        ),
    ],
)
def test_identity_head_pass_and_terminal_drift_fail_closed(changed):
    with pytest.raises(Optimizer360CaseError):
        validate_optimizer_360_case(changed)


def test_fixture_loader_rejects_extra_contract_fields(tmp_path):
    payload = json.loads(OPTIMIZER_360_FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    changed = tmp_path / "optimizer-360-extra.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Optimizer360CaseError, match="extra"):
        load_optimizer_360_case(changed)
