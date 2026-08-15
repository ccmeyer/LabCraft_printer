from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from AuthoritativeExecutionLoad import inspect_authoritative_execution
from tools.virtual_workflows.persistence_safeguards import (
    EXPECTED_CASE_IDS,
    PERSISTENCE_SAFEGUARD_CATALOG_PATH,
    PERSISTENCE_SAFEGUARD_MATRIX_ID,
    get_persistence_safeguard_case,
    persistence_fixture_inventory,
    persistence_safeguard_catalog,
    prepare_persistence_fault,
)
from tools.virtual_workflows.safeguards import SafeguardContractError


EXPECTED_SOURCE_CATALOG_SHA256 = (
    "b902df545b585a05a167dbee3fd96b73194c4269a157de711a120eaa2a4d6c93"
)
EXPECTED_MATRIX_CATALOG_SHA256 = (
    "80303a3256d0707b9bbf5deab2a0dc39c71a50f58fb6f3d5620cedd551bcb496"
)
EXPECTED_CATALOG_FILE_SHA256 = (
    "b5f4422a16197c87ea9dd78c3eed3f8e2ea3d87f44517ff9d18b18525c7cd61f"
)


def _session_root(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "session.json").write_text("{}", encoding="utf-8")
    return root


def test_persistence_catalog_is_literal_ordered_and_frozen():
    from tools.virtual_workflows.matrices import catalog_sha256

    catalog = persistence_safeguard_catalog()
    assert tuple(case.case_id for case in catalog.cases) == EXPECTED_CASE_IDS
    assert catalog.contract_sha256 == EXPECTED_SOURCE_CATALOG_SHA256
    assert catalog_sha256(PERSISTENCE_SAFEGUARD_MATRIX_ID) == (
        EXPECTED_MATRIX_CATALOG_SHA256
    )
    assert hashlib.sha256(PERSISTENCE_SAFEGUARD_CATALOG_PATH.read_bytes()).hexdigest() == (
        EXPECTED_CATALOG_FILE_SHA256
    )
    assert all(case.family == "persistence" for case in catalog.cases)
    assert all(case.fresh_process_required and case.replay_required for case in catalog.cases)
    assert sum(case.visible_required for case in catalog.cases) == 3


@pytest.mark.parametrize("case_id", EXPECTED_CASE_IDS)
def test_fault_builder_changes_one_contained_target_and_preserves_source(
    tmp_path, case_id
):
    case = get_persistence_safeguard_case(case_id)
    prepared = prepare_persistence_fault(case, _session_root(tmp_path, case_id))
    source_after = persistence_fixture_inventory(prepared.source_root)
    faulted_after = persistence_fixture_inventory(prepared.faulted_root)
    assert source_after == dict(prepared.source_inventory)
    assert faulted_after == dict(prepared.faulted_inventory)
    assert prepared.source_root != prepared.faulted_root
    assert prepared.source_root.is_relative_to(tmp_path)
    assert prepared.faulted_root.is_relative_to(tmp_path)
    assert prepared.fault_manifest["application_launched"] is False
    assert prepared.fault_manifest["mutation_count"] == 1
    assert prepared.fault_manifest["changed_paths"] == [case.fault.relative_path]
    assert prepared.fault_manifest_path.is_file()
    assert json.loads(prepared.fault_manifest_path.read_text(encoding="utf-8")) == (
        dict(prepared.fault_manifest)
    )


@pytest.mark.parametrize("case_id", EXPECTED_CASE_IDS)
def test_faulted_copy_has_exact_production_classification(tmp_path, case_id):
    case = get_persistence_safeguard_case(case_id)
    prepared = prepare_persistence_fault(case, _session_root(tmp_path, case_id))
    design = json.loads(
        (prepared.faulted_root / "experiment_design.json").read_text(encoding="utf-8")
    )
    bundle = inspect_authoritative_execution(prepared.faulted_root, design)
    if bundle.issues:
        assert bundle.issues[0].code == case.expected.code
        raw_message = bundle.issues[0].message
        if case_id == "incomplete_authoritative_bundle_invalid":
            assert "No such file or directory" in raw_message
            assert "progress.json" in raw_message
        else:
            assert raw_message == case.setup["technical_message"]
    else:
        assert bundle.eligibility.status == case.expected.classification
        assert bundle.eligibility.reason == case.setup["technical_message"]
        assert not bundle.eligibility.can_activate_runtime


def test_fault_builder_rejects_uninitialized_or_reused_roots(tmp_path):
    case = get_persistence_safeguard_case(EXPECTED_CASE_IDS[0])
    with pytest.raises(SafeguardContractError, match="initialized SIL"):
        prepare_persistence_fault(case, tmp_path / "missing")
    root = _session_root(tmp_path, "initialized")
    prepare_persistence_fault(case, root)
    with pytest.raises(SafeguardContractError, match="already exists"):
        prepare_persistence_fault(case, root)


def test_unknown_persistence_case_fails_closed():
    with pytest.raises(SafeguardContractError, match="unsupported"):
        get_persistence_safeguard_case("unknown")
