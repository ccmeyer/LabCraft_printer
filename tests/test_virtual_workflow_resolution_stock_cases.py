from __future__ import annotations

import json

from tools.virtual_workflows.experiment_design_cases import frozen_text_sha256
from tools.virtual_workflows.journeys import get_journey_definition
from tools.virtual_workflows.registry import get_registered_scenario
from tools.virtual_workflows.resolution_stock_cases import (
    EXPECTED_CASE_SHA256,
    EXPECTED_FIXTURE_SHA256,
    IMPORT_CASE_ID,
    PROGRESS_GUARD_CASE_ID,
    SINGLE_CASE,
    SINGLE_CASE_ID,
    SINGLE_FIXTURE_PATH,
    TWO_STOCK_CASE,
    TWO_STOCK_CASE_ID,
    TWO_STOCK_FIXTURE_PATH,
    load_auxiliary_fixture,
)


def test_resolution_stock_fixtures_and_normalized_hashes_are_frozen():
    for case, path in (
        (SINGLE_CASE, SINGLE_FIXTURE_PATH),
        (TWO_STOCK_CASE, TWO_STOCK_FIXTURE_PATH),
    ):
        assert frozen_text_sha256(path) == EXPECTED_FIXTURE_SHA256[case.case_id]
        assert case.sha256() == EXPECTED_CASE_SHA256[case.case_id]
        assert len(case.count_oracle_sha256()) == 64
        assert case.optimizer_expectations.seed_rank.total_distinct_level_loss == 1
        assert case.optimizer_expectations.selected_rank.total_distinct_level_loss == 0
        assert len({stock.stock_id for stock in case.stocks}) == len(case.stocks)
        assert sum(
            row.expected_intents for row in case.execution_passes
        ) == case.terminal.expected_intents
        assert sum(
            row.expected_droplets for row in case.execution_passes
        ) == case.terminal.expected_droplets


def test_resolution_stock_literal_counts_and_revisions_are_exact():
    single = {
        (row.stock_id, row.well_id): row.target_droplets
        for row in SINGLE_CASE.oracle("all_stocks_calibrated").rows
    }
    assert [single[("R_322.58_mM", f"A{index}")] for index in range(1, 5)] == [
        1,
        2,
        8,
        31,
    ]
    assert [single.get(("Water_1.00_--", f"A{index}"), 0) for index in range(1, 5)] == [
        30,
        29,
        23,
        0,
    ]
    paired = {
        (row.stock_id, row.well_id): row.target_droplets
        for row in TWO_STOCK_CASE.oracle("all_stocks_calibrated").rows
    }
    fill_calibrated = {
        (row.stock_id, row.well_id): row.target_droplets
        for row in TWO_STOCK_CASE.oracle("fill_calibrated").rows
    }
    assert [
        fill_calibrated[("Water_1.00_--", f"A{index}")]
        for index in range(1, 5)
    ] == [13, 3, 18, 3]
    assert [paired.get(("Signal_2000.00_mM", f"A{index}"), 0) for index in range(1, 5)] == [0, 0, 1, 4]
    assert [paired[("Signal_25.00_mM", f"A{index}")] for index in range(1, 5)] == [9, 18, 4, 15]
    assert [paired[("Water_1.00_--", f"A{index}")] for index in range(1, 5)] == [14, 4, 18, 2]
    assert [row.output_revision for row in SINGLE_CASE.calibrations] == [3, 4, 5]
    assert [row.output_revision for row in TWO_STOCK_CASE.calibrations] == [3, 4, 5]
    assert SINGLE_CASE.terminal.terminal_revision == 6
    assert TWO_STOCK_CASE.terminal.terminal_revision == 6


def test_resolution_stock_auxiliary_fixtures_and_registration_are_consistent():
    for case_id in (PROGRESS_GUARD_CASE_ID, IMPORT_CASE_ID):
        payload, path = load_auxiliary_fixture(case_id)
        assert payload["fixture_id"] == case_id
        assert frozen_text_sha256(path) == EXPECTED_FIXTURE_SHA256[case_id]
    for case_id in (
        SINGLE_CASE_ID,
        TWO_STOCK_CASE_ID,
        PROGRESS_GUARD_CASE_ID,
        IMPORT_CASE_ID,
    ):
        registered = get_registered_scenario(case_id)
        journey = get_journey_definition(case_id)
        assert registered.registry_id == journey.registry_id == case_id
        assert registered.workload_id == journey.workload_id == case_id
        assert registered.fixture_path.resolve() == journey.fixture_loader()[1].resolve()


def test_two_stock_import_csv_truth_is_literal_and_parseable():
    fixture, path = load_auxiliary_fixture(IMPORT_CASE_ID)
    root = path.parent
    design = (root / fixture["design_csv"]).read_text(encoding="utf-8")
    maximum = (root / fixture["max_stock_csv"]).read_text(encoding="utf-8")
    assert design.replace("\r\n", "\n") == "Well,R mM\nA1,0.1\nA2,0.2\n"
    assert maximum.replace("\r\n", "\n") == "reagent,stock_conc,units\nR,10,mM\n"
    assert json.loads(json.dumps(fixture["expected_target_mappings"])) == {
        "R_10.00_mM": {"0.1": 0, "0.2": 1},
        "R_5.00_mM": {"0.1": 1, "0.2": 0},
    }
