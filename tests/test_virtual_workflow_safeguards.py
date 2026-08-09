from __future__ import annotations

import json

import pytest

from tools.virtual_workflows.safeguards import (
    ExpectedSafeguardOutcome,
    PersistenceFaultSpec,
    SafeguardBoundarySnapshot,
    SafeguardCase,
    SafeguardCatalog,
    SafeguardContractError,
    capture_safeguard_boundary,
    load_safeguard_catalog,
    safeguard_rejection_no_mutation_no_dispatch_assertion,
)


def _outcome(**overrides):
    values = {
        "outcome_kind": "typed_rejection",
        "classification": "blocked",
        "code": "literal_guard_code",
        "message": "The requested action is blocked.",
        "ui_surface": "dialog",
        "ui_title": "Action blocked",
        "selected_control": "Cancel",
        "workflow_state": "draft",
        "queue_state": "idle",
        "runtime_active": False,
        "activation_count": 0,
    }
    values.update(overrides)
    return ExpectedSafeguardOutcome(**values)


def _case(**overrides):
    values = {
        "case_id": "editor_literal_guard_v1",
        "family": "editor",
        "fixture_id": "compact_editor_fixture_v1",
        "operator_action_id": "finish_design",
        "operator_action_label": "Finish design",
        "invalid_invariant": "printed volume exceeds final volume",
        "expected": _outcome(),
        "identity_keys": {
            "design_id": "design-1",
            "stock_ids": {"stock-a": "stock-a"},
            "printer_head_ids": {"head-a": "head-a"},
            "calibration_ids": {"cal-a": "cal-a"},
            "plan_id": "plan-1",
            "progress_id": "progress-1",
        },
        "setup": {"driver": "editor", "printed_volume_nL": 100},
    }
    values.update(overrides)
    return SafeguardCase(**values)


def _snapshot(**overrides):
    values = {
        "persistence": {"files": {"design.json": "sha-design"}},
        "model": {"design_id": "design-1", "revision": 1},
        "lifecycle": {"state": "draft", "runtime_active": False},
        "queue": {"state": "idle", "items": []},
        "dispatch": {
            "machine_intents": 0,
            "commands": 0,
            "completions": 0,
            "drops": 0,
        },
    }
    values.update(overrides)
    return capture_safeguard_boundary(**values)


def test_case_contract_is_literal_round_trippable_and_stably_hashed(tmp_path):
    case = _case()
    catalog = SafeguardCatalog((case,))
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog.to_dict(), indent=2), encoding="utf-8")

    loaded = load_safeguard_catalog(path)

    assert loaded.to_dict() == catalog.to_dict()
    assert loaded.contract_sha256 == catalog.contract_sha256
    assert loaded.cases[0].contract_sha256 == case.contract_sha256
    assert len(case.contract_sha256) == 64


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"family": "unknown"}, "family"),
        ({"case_id": ""}, "case_id"),
        ({"direct_required": False}, "directly"),
        ({"manifest_required": False}, "manifest"),
        ({"identity_keys": {"row_index": 0}}, "positional"),
        ({"identity_keys": {"stocks": [{"position": 1}]}}, "positional"),
    ],
)
def test_case_rejects_ambiguous_or_positional_contracts(overrides, message):
    with pytest.raises(SafeguardContractError, match=message):
        _case(**overrides)


def test_outcome_requires_exact_operator_ui_and_no_new_activation():
    with pytest.raises(SafeguardContractError, match="exact UI title"):
        _outcome(ui_title=None)
    assert _outcome(runtime_active=True).runtime_active is True
    with pytest.raises(SafeguardContractError, match="cannot activate"):
        _outcome(activation_count=1)


@pytest.mark.parametrize(
    "relative_path",
    ["../user-experiment/design.json", "/absolute/design.json", "C:/data/file.json"],
)
def test_fault_spec_rejects_paths_outside_case_owned_copy(relative_path):
    with pytest.raises(SafeguardContractError, match="relative|inside"):
        PersistenceFaultSpec(
            relative_path=relative_path,
            operation="replace_json_value",
            phase="prelaunch",
            original_sha256="a" * 64,
            faulted_sha256="b" * 64,
        )


def test_fault_spec_requires_distinct_predeclared_hashes():
    with pytest.raises(SafeguardContractError, match="must differ"):
        PersistenceFaultSpec(
            relative_path="case/execution_plan.json",
            operation="replace_json_value",
            phase="between_sessions",
            original_sha256="a" * 64,
            faulted_sha256="a" * 64,
        )


def test_boundary_snapshot_requires_all_dispatch_counters():
    with pytest.raises(SafeguardContractError, match="missing counters"):
        SafeguardBoundarySnapshot(
            persistence={},
            model={},
            lifecycle={},
            queue={},
            dispatch={"commands": 0},
        )


def test_shared_oracle_passes_exact_rejection_and_unchanged_boundary():
    case = _case()
    before = _snapshot()
    after = _snapshot()

    result = safeguard_rejection_no_mutation_no_dispatch_assertion(
        case=case,
        before=before,
        after=after,
        observed=case.expected,
        checkpoint="after_finish_rejected",
    )

    assert result.decision == "pass"
    assert result.message is None
    assert result.evidence["failed_checks"] == []
    assert result.evidence["before_sha256"] == result.evidence["after_sha256"]
    assert result.to_dict()["assertion_id"] == (
        "safeguard_rejection_no_mutation_no_dispatch"
    )


@pytest.mark.parametrize(
    ("section", "replacement", "failed_check"),
    [
        ("persistence", {"files": {"design.json": "changed"}}, "persistence_unchanged"),
        ("model", {"design_id": "design-1", "revision": 2}, "model_unchanged"),
        ("lifecycle", {"state": "finalized", "runtime_active": False}, "lifecycle_unchanged"),
        ("queue", {"state": "queued", "items": ["intent-1"]}, "queue_unchanged"),
        (
            "dispatch",
            {"machine_intents": 1, "commands": 0, "completions": 0, "drops": 0},
            "dispatch_unchanged",
        ),
    ],
)
def test_shared_oracle_fails_each_mutated_boundary_section(
    section, replacement, failed_check
):
    case = _case()
    result = safeguard_rejection_no_mutation_no_dispatch_assertion(
        case=case,
        before=_snapshot(),
        after=_snapshot(**{section: replacement}),
        observed=case.expected,
        checkpoint="after_rejection",
    )

    assert result.decision == "fail"
    assert failed_check in result.evidence["failed_checks"]


def test_shared_oracle_fails_ui_code_and_accidental_activation_drift():
    case = _case()
    observed = _outcome(
        code="wrong_code",
        message="Different message",
        workflow_state="activated",
    )
    result = safeguard_rejection_no_mutation_no_dispatch_assertion(
        case=case,
        before=_snapshot(),
        after=_snapshot(),
        observed=observed,
        checkpoint="after_rejection",
    )

    assert result.decision == "fail"
    assert set(result.evidence["failed_checks"]) >= {
        "outcome_exact",
        "typed_classification_exact",
        "operator_ui_exact",
        "safe_workflow_exact",
    }


def test_snapshot_is_detached_from_mutable_driver_evidence():
    source = {"files": {"design.json": "original"}}
    snapshot = _snapshot(persistence=source)

    source["files"]["design.json"] = "mutated later"

    assert snapshot.persistence["files"]["design.json"] == "original"
