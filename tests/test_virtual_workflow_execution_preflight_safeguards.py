from __future__ import annotations

import hashlib

import pytest

from tools.virtual_workflows.execution_preflight_safeguards import (
    EXECUTION_PREFLIGHT_CATALOG_PATH,
    EXECUTION_PREFLIGHT_MATRIX_ID,
    EXPECTED_CASE_IDS,
    build_execution_preflight_fixture,
    execution_preflight_catalog,
    get_execution_preflight_case,
)
from tools.virtual_workflows.safeguards import SafeguardContractError


EXPECTED_SOURCE_CATALOG_SHA256 = (
    "66f7f4724e2ece43f525fdeddd60970b9ba992b5c9e2919fbe09d06eb15ff7d1"
)
EXPECTED_MATRIX_CATALOG_SHA256 = (
    "0a4169cfc5f844e25cc02c1af74ab9b26b01d82a9703470b85adfc0b0ed763c2"
)
EXPECTED_CATALOG_FILE_SHA256 = (
    "f35a6aa52104cfe182d2f2853f699993406bbe1af4a5eee4ea70cc5dcbcb94fd"
)


def test_execution_preflight_catalog_is_literal_ordered_and_durable_keyed():
    catalog = execution_preflight_catalog()
    assert tuple(case.case_id for case in catalog.cases) == EXPECTED_CASE_IDS
    assert catalog.contract_sha256 == EXPECTED_SOURCE_CATALOG_SHA256
    assert len(catalog.cases) == 17
    assert {case.family for case in catalog.cases} == {
        "calibration",
        "identity",
        "lifecycle",
    }
    assert all(case.direct_required for case in catalog.cases)
    assert all(case.manifest_required for case in catalog.cases)
    assert all(case.fresh_process_required for case in catalog.cases)
    assert all(
        set(case.identity_keys)
        >= {"design_id", "plan_id", "progress_id", "stock_ids", "printer_head_ids", "calibration_ids"}
        for case in catalog.cases
    )


def test_execution_preflight_catalog_file_and_matrix_hashes_are_frozen():
    from tools.virtual_workflows.matrices import catalog_sha256

    assert hashlib.sha256(
        EXECUTION_PREFLIGHT_CATALOG_PATH.read_bytes()
    ).hexdigest() == EXPECTED_CATALOG_FILE_SHA256
    assert catalog_sha256(EXECUTION_PREFLIGHT_MATRIX_ID) == (
        EXPECTED_MATRIX_CATALOG_SHA256
    )


@pytest.mark.parametrize("case_id", EXPECTED_CASE_IDS)
def test_execution_preflight_fixture_round_trip_is_case_owned(case_id):
    case = get_execution_preflight_case(case_id)
    fixture, source = build_execution_preflight_fixture(case)
    assert source == EXECUTION_PREFLIGHT_CATALOG_PATH
    assert fixture["lifecycle"]["case"] == case.to_dict()
    assert fixture["lifecycle"]["case_sha256"] == case.contract_sha256
    assert fixture["lifecycle"]["catalog_sha256"] == (
        EXPECTED_SOURCE_CATALOG_SHA256
    )
    assert fixture["workload"]["completion_count"] == 0


def test_unknown_execution_preflight_case_fails_closed():
    with pytest.raises(SafeguardContractError, match="unsupported"):
        get_execution_preflight_case("unknown")
