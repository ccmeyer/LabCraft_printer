from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from tools.virtual_workflows.experiment_design_cases import (
    EXPERIMENT_DESIGN_BASE_SCENARIO_ID,
    EXPERIMENT_DESIGN_CASES,
    EXPERIMENT_DESIGN_JOURNEY_FAMILY,
    EXPERIMENT_DESIGN_MATRIX_ID,
    REFERENCE_FIXTURE_PATH,
    REFERENCE_FIXTURE_SHA256,
    REQUIRED_PAIRWISE_INTERACTIONS,
    DesignExperimentInput,
    ExperimentDesignCaseError,
    audit_pairwise_coverage,
    build_experiment_design_fixture,
    editor_specification,
    executable_experiment_design_cases,
    get_experiment_design_case,
    planned_catalog_sha256,
    validate_experiment_design_catalog,
)
from tools.virtual_workflows.matrices import MatrixDefinition, MatrixRegistry


EXPECTED_CASE_IDS = (
    "single_reagent_control",
    "multi_reagent_seed_4321",
    "one_stock_feasible",
    "two_stock_required",
    "custom_wells_with_exclusions",
    "multi_reagent_seed_1234",
    "exact_custom_capacity",
    "capacity_plus_one_rejected",
    "fixed_stock_exceeds_max_rejected",
)
EXPECTED_CASE_SHA256 = {
    "single_reagent_control": (
        "b0deaaf5af7b4391d3cc92de2b03b7729ba3ea6abf7b22d122f78b9ef347c033"
    ),
    "multi_reagent_seed_4321": (
        "5d2e7dff0ea9c2e0bcd1e3b218b39280aca57b745834024226fece850f110f51"
    ),
    "one_stock_feasible": (
        "30ee17fcd869f6c3989d39b50d7e484ed8de233e5af6fc1f2c47cfac40230e17"
    ),
    "two_stock_required": (
        "be49593fd1cf20fdce550fe350d6eca5b37c275a5c5373e69c616cc89def5c96"
    ),
    "custom_wells_with_exclusions": (
        "d7226b2e801489066516b46206274706a85749c4a73cfdfa4cc3df289f4391cf"
    ),
    "multi_reagent_seed_1234": (
        "795a80c456f8af02e1b759a95de96994cd8dc6fbb4a8ed640fe0ee2f7b385f29"
    ),
    "exact_custom_capacity": (
        "ddb0b20ba5722ce748fde01e17d589036d0d88b3117ae78130101f7bad7cc551"
    ),
    "capacity_plus_one_rejected": (
        "16af7c74a8e4d5840e24317b20996a1bc511a1d26641e5e4a5dce10b31fca21a"
    ),
    "fixed_stock_exceeds_max_rejected": (
        "6ca924d668e36b8b5b6dbd32bc9fcc965acb41b31f14af1723de243270174932"
    ),
}
EXPECTED_PLANNED_CATALOG_SHA256 = (
    "17c879cbe5963ea5ddcbcb8bf298f781784310534db5d91eebd9cb1e7b42d326"
)
EXPECTED_TEST_LOCAL_DEFINITION_SHA256 = (
    "aa58a764c644a69a37d3c7c4aa9ce788d43bb10bee25da606305d3bcb010cbc9"
)
EXPECTED_TEST_LOCAL_PLAN_SHA256 = (
    "71f416313e0e915c03e25abb92fffa7f2b80543ef12b3238d3f320894210081c"
)


def _definition() -> MatrixDefinition:
    return MatrixDefinition(
        matrix_id=EXPERIMENT_DESIGN_MATRIX_ID,
        base_scenario_id=EXPERIMENT_DESIGN_BASE_SCENARIO_ID,
        journey_family=EXPERIMENT_DESIGN_JOURNEY_FAMILY,
        platform="windows_sil",
        execution="manual_on_demand",
        cases=EXPERIMENT_DESIGN_CASES,
        catalog_metadata={"pairwise_audit": audit_pairwise_coverage()},
        fixture_builder=build_experiment_design_fixture,
    )


def test_catalog_freezes_nine_ordered_cases_hashes_and_pairwise_audit():
    validate_experiment_design_catalog()

    assert tuple(case.case_id for case in EXPERIMENT_DESIGN_CASES) == EXPECTED_CASE_IDS
    assert {case.case_id: case.sha256() for case in EXPERIMENT_DESIGN_CASES} == (
        EXPECTED_CASE_SHA256
    )
    assert planned_catalog_sha256() == EXPECTED_PLANNED_CATALOG_SHA256
    audit = audit_pairwise_coverage()
    assert audit["complete"] is True
    assert audit["uncovered"] == []
    assert audit["required_pair_count"] == len(REQUIRED_PAIRWISE_INTERACTIONS) == 14


def test_randomized_cases_freeze_equal_multiset_and_distinct_assignments():
    seed_4321 = get_experiment_design_case("multi_reagent_seed_4321")
    seed_1234 = get_experiment_design_case("multi_reagent_seed_1234")

    assert seed_4321.experiment.random_seed == 4321
    assert seed_1234.experiment.random_seed == 1234
    assert (
        seed_4321.expected.reaction_multiset_sha256()
        == seed_1234.expected.reaction_multiset_sha256()
    )
    assert (
        seed_4321.expected.assignment_sha256()
        != seed_1234.expected.assignment_sha256()
    )
    assert [row.reaction_id for row in seed_4321.expected.assignments] == [
        "R8",
        "R6",
        "R3",
        "R2",
        "R7",
        "R4",
        "R1",
        "R5",
    ]
    assert [row.reaction_id for row in seed_1234.expected.assignments] == [
        "R2",
        "R4",
        "R3",
        "R5",
        "R6",
        "R7",
        "R1",
        "R8",
    ]


def test_formulation_and_rejection_oracles_are_literal_and_terminal_specific():
    one_stock = get_experiment_design_case("one_stock_feasible")
    two_stock = get_experiment_design_case("two_stock_required")
    capacity = get_experiment_design_case("capacity_plus_one_rejected")
    infeasible = get_experiment_design_case("fixed_stock_exceeds_max_rejected")

    assert [stock.concentration for stock in one_stock.expected.stocks] == ["5", "1"]
    assert [stock.concentration for stock in two_stock.expected.stocks] == ["5", "10"]
    assert [attempt.expected_outcome for attempt in two_stock.optimization_attempts] == [
        "rejected",
        "generated",
    ]
    assert (capacity.expected.capacity_required, capacity.expected.capacity_available) == (
        5,
        4,
    )
    assert capacity.expected.terminal == "capacity_rejected"
    assert infeasible.expected.terminal == "formulation_rejected"
    assert capacity.expected.stocks == infeasible.expected.stocks == ()
    assert capacity.expected.assignments == infeasible.expected.assignments == ()


def test_reference_fixture_is_sha_verified_and_transformed_only_in_memory():
    source_before = REFERENCE_FIXTURE_PATH.read_bytes()
    assert hashlib.sha256(source_before).hexdigest() == REFERENCE_FIXTURE_SHA256

    case = get_experiment_design_case("single_reagent_control")
    fixture, source = build_experiment_design_fixture(case)

    assert source == REFERENCE_FIXTURE_PATH.resolve()
    assert fixture["fixture_id"] == (
        "experiment_design_pairwise_v1__single_reagent_control"
    )
    assert fixture["lifecycle"]["case"] == case.normalized()
    assert fixture["lifecycle"]["case_sha256"] == EXPECTED_CASE_SHA256[case.case_id]
    assert fixture["lifecycle"]["planned_catalog_sha256"] == (
        EXPECTED_PLANNED_CATALOG_SHA256
    )
    assert "reagent" not in fixture
    assert len(fixture["reagents"]) == 1
    assert REFERENCE_FIXTURE_PATH.read_bytes() == source_before


def test_executable_prefix_and_editor_projection_are_additive_and_exact():
    cases = executable_experiment_design_cases()
    assert tuple(case.case_id for case in cases) == EXPECTED_CASE_IDS

    control = editor_specification(cases[0])
    randomized = editor_specification(cases[1])
    one_stock = editor_specification(cases[2])
    two_stock = editor_specification(cases[3])
    custom_wells = editor_specification(cases[4])
    seed_1234 = editor_specification(cases[5])
    exact_capacity = editor_specification(cases[6])
    capacity_rejected = editor_specification(cases[7])
    formulation_rejected = editor_specification(cases[8])

    assert control["experiment"]["selected_well_ids"] == ["A1"]
    assert control["experiment"]["expected_reaction_count"] == 1
    assert control["experiment"]["random_seed"] is None
    assert len(control["reagents"]) == 1
    assert randomized["experiment"]["random_seed"] == 4321
    assert randomized["experiment"]["randomize_assignments"] is True
    assert randomized["experiment"]["expected_reaction_count"] == 8
    assert len(randomized["reagents"]) == 2
    assert [row["fixed_stock_concentration"] for row in randomized["reagents"]] == [
        "10",
        "10",
    ]
    assert one_stock["optimization_attempts"] == [
        {
            "allow_two_stock_solutions": False,
            "expected_outcome": "generated",
            "expected_dialog_title": None,
            "expected_message_fragments": [],
        }
    ]
    assert [
        (attempt["allow_two_stock_solutions"], attempt["expected_outcome"])
        for attempt in two_stock["optimization_attempts"]
    ] == [(False, "rejected"), (True, "generated")]
    assert custom_wells["experiment"]["selected_well_ids"] == [
        "A1", "A2", "A3", "A4", "A5", "A6"
    ]
    assert custom_wells["experiment"]["excluded_well_ids"] == ["A2", "A5"]
    assert [
        row.target_droplets
        for row in cases[4].expected.stock_well_counts
        if row.stock_id == "Water_1.00_--"
    ] == [10, 9, 8]
    assert seed_1234["experiment"]["random_seed"] == 1234
    assert seed_1234["experiment"]["randomize_assignments"] is True
    assert [
        row.target_droplets
        for row in cases[5].expected.stock_well_counts
        if row.stock_id == "Water_1.00_--"
    ] == [7, 6, 8, 9, 7, 8, 9, 6]
    assert [
        row.target_droplets
        for row in cases[6].expected.stock_well_counts
        if row.stock_id == "Water_1.00_--"
    ] == [10, 9, 10, 9]
    assert exact_capacity["expected"]["terminal"] == "prepared"
    assert capacity_rejected["expected"] == {
        **cases[7].expected.normalized(),
    }
    assert capacity_rejected["expected"]["capacity_required"] == 5
    assert capacity_rejected["expected"]["capacity_available"] == 4
    assert formulation_rejected["expected"]["terminal"] == (
        "formulation_rejected"
    )
    assert formulation_rejected["expected"]["dialog_title"] == (
        "Could not update reactions and stock solutions"
    )


def test_test_local_definition_resolves_generic_selector_contracts():
    definition = _definition()
    registry = MatrixRegistry((definition,))

    full_plan = registry.resolve_plan(
        EXPERIMENT_DESIGN_MATRIX_ID,
        seed=9,
        timeout_seconds=12,
        execution_authorized=False,
    )
    selected = registry.resolve_plan(
        EXPERIMENT_DESIGN_MATRIX_ID,
        case_id="two_stock_required",
        seed=9,
        timeout_seconds=12,
        execution_authorized=False,
    )

    assert full_plan["case_count"] == 9
    assert [row["case"]["case_id"] for row in full_plan["cases"]] == list(
        EXPECTED_CASE_IDS
    )
    assert selected["case_count"] == 1
    assert selected["cases"][0]["case_sha256"] == EXPECTED_CASE_SHA256[
        "two_stock_required"
    ]
    assert definition.catalog_metadata["pairwise_audit"]["complete"] is True
    assert definition.catalog_sha256() == EXPECTED_TEST_LOCAL_DEFINITION_SHA256
    assert hashlib.sha256(
        json.dumps(
            full_plan,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest() == EXPECTED_TEST_LOCAL_PLAN_SHA256
    fixture, source = definition.build_case_fixture("two_stock_required")
    assert source == REFERENCE_FIXTURE_PATH.resolve()
    assert fixture["lifecycle"]["matrix_id"] == EXPERIMENT_DESIGN_MATRIX_ID


@pytest.mark.parametrize(
    ("experiment", "match"),
    [
        (
            DesignExperimentInput(
                "valid",
                "plate",
                1,
                ("A1",),
                (),
                "10",
                "10",
            ),
            "non-randomized experiments",
        ),
        (
            DesignExperimentInput(
                "valid",
                "plate",
                1,
                ("A1",),
                (),
                "10",
                "10",
                randomize_assignments=True,
                random_seed=1,
            ),
            "non-negative integer seed",
        ),
    ],
)
def test_experiment_input_rejects_seed_contract_drift(experiment, match):
    kwargs = (
        {"random_seed": 1}
        if experiment.random_seed is None
        else {"random_seed": -1}
    )
    with pytest.raises(ExperimentDesignCaseError, match=match):
        replace(experiment, **kwargs)


def test_catalog_validator_rejects_pairwise_and_randomization_drift():
    seed_1234 = get_experiment_design_case("multi_reagent_seed_1234")
    without_pairs = tuple(
        replace(
            case,
            coverage_tags=case.coverage_tags - {"evidence:reload_runtime"},
        )
        for case in EXPERIMENT_DESIGN_CASES
    )
    with pytest.raises(ExperimentDesignCaseError, match="pairwise coverage"):
        validate_experiment_design_catalog(without_pairs)

    same_assignment = replace(
        seed_1234,
        expected=replace(
            seed_1234.expected,
            assignments=get_experiment_design_case(
                "multi_reagent_seed_4321"
            ).expected.assignments,
        ),
    )
    changed = tuple(
        same_assignment if case.case_id == seed_1234.case_id else case
        for case in EXPERIMENT_DESIGN_CASES
    )
    with pytest.raises(ExperimentDesignCaseError, match="randomized comparison"):
        validate_experiment_design_catalog(changed)


def test_oracle_module_has_no_production_algorithm_imports():
    source = REFERENCE_FIXTURE_PATH.parents[1] / "experiment_design_cases.py"
    text = source.read_text(encoding="utf-8")

    forbidden = (
        "from Model",
        "import Model",
        "from View",
        "import View",
        "optimize_stock_solutions",
        "generate_experiment",
        "assign_reactions_to_wells",
    )
    assert not any(value in text for value in forbidden)
    json.loads(json.dumps([case.normalized() for case in EXPERIMENT_DESIGN_CASES]))
