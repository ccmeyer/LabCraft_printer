"""Literal Milestone 12 editor safeguard catalog and fixture builder."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from tools.virtual_workflows.safeguards import (
    SafeguardCase,
    SafeguardCatalog,
    SafeguardContractError,
    load_safeguard_catalog,
)


EDITOR_SAFEGUARD_MATRIX_ID = "editor_safeguards_v1"
EDITOR_SAFEGUARD_BASE_SCENARIO_ID = "experiment_editor_create_finalize_v1"
EDITOR_SAFEGUARD_JOURNEY_FAMILY = "editor_safeguards"
EDITOR_SAFEGUARD_CATALOG_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "editor_safeguards_v1.json"
)
EDITOR_REFERENCE_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "experiment_editor_create_finalize_v1.json"
)

EXPECTED_CASE_IDS = (
    "impossible_fixed_target_finalize_rejected",
    "printed_exceeds_final_finalize_rejected",
    "one_stock_infeasible_finalize_rejected",
    "two_stock_infeasible_finalize_rejected",
    "capacity_plus_one_finalize_rejected",
    "invalid_uploaded_well_rejected",
    "excluded_uploaded_well_rejected",
    "dirty_invalid_finalize_rejected",
)


def editor_safeguard_catalog() -> SafeguardCatalog:
    catalog = load_safeguard_catalog(EDITOR_SAFEGUARD_CATALOG_PATH)
    ids = tuple(case.case_id for case in catalog.cases)
    if ids != EXPECTED_CASE_IDS:
        raise SafeguardContractError("editor safeguard case order or identity drifted")
    if any(case.family != "editor" for case in catalog.cases):
        raise SafeguardContractError("editor safeguard catalog contains another family")
    for case in catalog.cases:
        setup = dict(case.setup)
        if setup.get("driver") != "editor_safeguard":
            raise SafeguardContractError(
                f"editor safeguard {case.case_id!r} has an unsupported driver"
            )
        specification = setup.get("specification")
        if not isinstance(specification, dict):
            # Frozen mappings implement Mapping rather than dict.
            from collections.abc import Mapping

            if not isinstance(specification, Mapping):
                raise SafeguardContractError(
                    f"editor safeguard {case.case_id!r} has no specification"
                )
    return catalog


def editor_safeguard_cases() -> tuple[SafeguardCase, ...]:
    return editor_safeguard_catalog().cases


def get_editor_safeguard_case(case_id: str) -> SafeguardCase:
    matches = [
        case for case in editor_safeguard_cases() if case.case_id == str(case_id)
    ]
    if len(matches) != 1:
        raise SafeguardContractError(f"unsupported editor safeguard: {case_id!r}")
    return matches[0]


def build_editor_safeguard_fixture(
    case: SafeguardCase,
) -> tuple[dict[str, Any], Path]:
    if case.family != "editor":
        raise SafeguardContractError("editor fixture builder received another family")
    base = json.loads(EDITOR_REFERENCE_FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture = copy.deepcopy(base)
    setup = json.loads(json.dumps(case.to_dict()["setup"]))
    specification = setup["specification"]
    specification["safeguard_boundary_sync"] = True
    fixture["fixture_id"] = EDITOR_SAFEGUARD_BASE_SCENARIO_ID
    fixture["experiment"] = copy.deepcopy(specification["experiment"])
    fixture["reagent"] = copy.deepcopy(specification["reagents"][0])
    fixture["lifecycle"] = {
        "matrix_id": EDITOR_SAFEGUARD_MATRIX_ID,
        "catalog_sha256": editor_safeguard_catalog().contract_sha256,
        "case_sha256": case.contract_sha256,
        "case": case.to_dict(),
        "editor_safeguard_specification": specification,
    }
    fixture["workload"] = {
        "completion_count": 0,
        "expected_editor_finalization_operations": 1,
    }
    return fixture, EDITOR_SAFEGUARD_CATALOG_PATH


__all__ = [
    "EDITOR_SAFEGUARD_BASE_SCENARIO_ID",
    "EDITOR_SAFEGUARD_CATALOG_PATH",
    "EDITOR_SAFEGUARD_JOURNEY_FAMILY",
    "EDITOR_SAFEGUARD_MATRIX_ID",
    "EXPECTED_CASE_IDS",
    "build_editor_safeguard_fixture",
    "editor_safeguard_cases",
    "editor_safeguard_catalog",
    "get_editor_safeguard_case",
]
