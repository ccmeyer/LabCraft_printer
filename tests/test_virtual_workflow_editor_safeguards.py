from __future__ import annotations

from tools.virtual_workflows.editor_safeguards import (
    EDITOR_SAFEGUARD_BASE_SCENARIO_ID,
    EDITOR_SAFEGUARD_CATALOG_PATH,
    EDITOR_SAFEGUARD_MATRIX_ID,
    EXPECTED_CASE_IDS,
    build_editor_safeguard_fixture,
    editor_safeguard_catalog,
    get_editor_safeguard_case,
)
from tools.virtual_workflows.matrices import get_matrix_definition


EXPECTED_SOURCE_CATALOG_SHA256 = (
    "ec6732b7422beb66817535c9ae54406b9c2166f5e071bc15218c0f73109627a9"
)


def test_editor_safeguard_catalog_is_exact_and_separate_from_milestone_10():
    catalog = editor_safeguard_catalog()

    assert tuple(case.case_id for case in catalog.cases) == EXPECTED_CASE_IDS
    assert catalog.contract_sha256 == EXPECTED_SOURCE_CATALOG_SHA256
    assert EDITOR_SAFEGUARD_CATALOG_PATH.name == "editor_safeguards_v1.json"
    assert all(case.family == "editor" for case in catalog.cases)
    assert all(case.fault is None for case in catalog.cases)
    assert all(case.fresh_process_required for case in catalog.cases)


def test_editor_safeguard_literals_cover_every_declared_boundary():
    cases = {case.case_id: case for case in editor_safeguard_catalog().cases}

    assert {case.expected.code for case in cases.values()} == {
        "fixed_exceeds_max",
        "printed_exceeds_final_volume",
        "single_stock_volume_budget_exceeded",
        "insufficient_well_capacity",
        "explicit_well_assignment_invalid",
    }
    assert cases["invalid_uploaded_well_rejected"].expected.message.endswith(
        "G16."
    )
    assert cases["excluded_uploaded_well_rejected"].expected.message.endswith(
        "Excluded wells: A1."
    )
    assert (
        cases["capacity_plus_one_finalize_rejected"].expected.workflow_state
        == "draft_generated"
    )
    assert all(case.expected.queue_state == "idle" for case in cases.values())


def test_editor_safeguard_fixture_is_case_owned_and_matrix_fingerprint_ready():
    case = get_editor_safeguard_case("printed_exceeds_final_finalize_rejected")
    fixture, source = build_editor_safeguard_fixture(case)

    assert source == EDITOR_SAFEGUARD_CATALOG_PATH
    assert fixture["fixture_id"] == EDITOR_SAFEGUARD_BASE_SCENARIO_ID
    assert fixture["workload"]["completion_count"] == 0
    assert fixture["lifecycle"]["matrix_id"] == EDITOR_SAFEGUARD_MATRIX_ID
    assert fixture["lifecycle"]["case_sha256"] == case.contract_sha256
    assert fixture["lifecycle"]["editor_safeguard_specification"][
        "safeguard_boundary_sync"
    ] is True


def test_editor_safeguard_matrix_keeps_all_cases_directly_addressable():
    definition = get_matrix_definition(EDITOR_SAFEGUARD_MATRIX_ID)

    assert definition.base_scenario_id == EDITOR_SAFEGUARD_BASE_SCENARIO_ID
    assert definition.journey_family == "editor_safeguards"
    assert definition.case_ids() == EXPECTED_CASE_IDS
    assert definition.platform == "windows_sil"
