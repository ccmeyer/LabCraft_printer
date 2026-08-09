from __future__ import annotations

import json
from dataclasses import replace

import pytest

from tools.run_virtual_workflow import main
from tools.virtual_workflows.exploration import (
    CAMPAIGN_ID as M8_CAMPAIGN_ID,
    catalog_sha256 as exploration_catalog_sha256,
    exploration_catalog,
    resolve_exploration_plan,
)
from tools.virtual_workflows.exploration_m13 import (
    CAMPAIGN_BUDGET,
    CAMPAIGN_ID,
    EXPECTED_CAMPAIGN_SHA256,
    EXPECTED_CATALOG_SHA256,
    EXPECTED_FIXTURE_PROJECTION_SHA256,
    EXPECTED_FROZEN_SET_SHA256,
    EXPECTED_OPERATION_CATALOG_SHA256,
    EXPECTED_ORACLE_LEDGER_SHA256,
    EXPECTED_SEQUENCE_SHA256,
    EXPECTED_STATE_MODEL_SHA256,
    FROZEN_SEEDS,
    FROZEN_SEQUENCES,
    MAX_DIAGNOSTIC_SEEDS,
    M13_REJECTION_CASES,
    M13ExplorationValidationError,
    OPERATIONS,
    PLAN_SCHEMA_VERSION,
    SEQUENCE_BUDGET,
    STATES,
    SequenceStep,
    campaign_sha256,
    catalog_sha256,
    generate_diagnostic_sequence,
    normalized_frozen_catalog,
    resolve_plan,
    sequence_ids,
    validate_sequence,
)


EXPECTED_SEQUENCE_IDS = (
    "seed_13_legal_design_calibration_terminal",
    "seed_29_legal_refinalize_reload_terminal",
    "seed_47_illegal_editor_recovery_terminal",
    "seed_83_illegal_calibration_recovery_terminal",
    "seed_131_illegal_identity_activation_recovery_terminal",
    "seed_197_illegal_progress_lock_recovery_terminal",
)


def test_frozen_contract_hashes_and_sequence_identities_are_literal():
    catalog = normalized_frozen_catalog()
    assert FROZEN_SEEDS == (13, 29, 47, 83, 131, 197)
    assert sequence_ids() == EXPECTED_SEQUENCE_IDS
    assert tuple(catalog["frozen_sequence_sha256"]) == EXPECTED_SEQUENCE_SHA256
    assert catalog["state_model_sha256"] == EXPECTED_STATE_MODEL_SHA256
    assert catalog["operation_catalog_sha256"] == EXPECTED_OPERATION_CATALOG_SHA256
    assert catalog["oracle_ledger_sha256"] == EXPECTED_ORACLE_LEDGER_SHA256
    assert catalog["frozen_set_sha256"] == EXPECTED_FROZEN_SET_SHA256
    assert catalog["fixture_projection_sha256"] == EXPECTED_FIXTURE_PROJECTION_SHA256
    assert catalog_sha256() == EXPECTED_CATALOG_SHA256
    assert campaign_sha256() == EXPECTED_CAMPAIGN_SHA256


def test_state_model_has_required_substates_and_no_incidental_ui_positions():
    state_ids = {item.state_id for item in STATES}
    assert state_ids == {
        "draft_valid",
        "draft_invalid",
        "draft_generated",
        "prepared_zero_progress",
        "calibration_available_unapplied",
        "calibration_selected_unapplied",
        "calibrated_zero_progress",
        "session_closed",
        "reloaded_inactive",
        "active_zero_progress",
        "progressed_locked",
        "terminal",
    }
    encoded = json.dumps([item.normalized() for item in STATES], sort_keys=True)
    for incidental in ("row_index", "list_index", "slot_position"):
        assert incidental not in encoded
    assert normalized_frozen_catalog()["state_model_version"] == "design-calibration-state-v1"


def test_every_operation_is_oracle_admitted_and_covered_by_frozen_sequences():
    admitted = {item.operation_id for item in OPERATIONS}
    reached = {
        step.operation_id
        for sequence in FROZEN_SEQUENCES
        for step in sequence.steps
    }
    assert len(admitted) == 26
    assert reached == admitted
    assert all(item.oracle_id and item.oracle_owner for item in OPERATIONS)
    assert all(
        item.rejection_class and all(source == target for source, target in item.transitions)
        for item in OPERATIONS
        if item.expected_outcome == "rejected"
    )
    assert all(
        step.normalized(index)["oracle_id"]
        for sequence in FROZEN_SEQUENCES
        for index, step in enumerate(sequence.steps, 1)
    )


def test_every_rejected_operation_routes_to_one_exact_milestone_12_case():
    rejected = {
        item.operation_id
        for item in OPERATIONS
        if item.expected_outcome == "rejected"
    }
    assert set(M13_REJECTION_CASES) == rejected
    assert len(set(M13_REJECTION_CASES.values())) == len(rejected)
    assert M13_REJECTION_CASES["editor.attempt_progressed_edit_via_ui"] == (
        "active_execution_edit_rejected"
    )


def test_frozen_sequences_are_continuous_terminal_and_inside_exact_budgets():
    assert SEQUENCE_BUDGET.normalized() == {
        "semantic_operations": 18,
        "action_rows": 80,
        "sessions": 3,
        "session_rotations": 2,
        "screenshots": 4,
        "retained_files": 256,
        "retained_bytes": 48 * 1024 * 1024,
        "scenario_deadline_seconds": 270,
        "child_watchdog_seconds": 300,
        "reactions": 4,
        "executable_stocks": 2,
        "intents": 8,
        "droplets": 44,
    }
    assert CAMPAIGN_BUDGET.semantic_operations == 108
    assert CAMPAIGN_BUDGET.action_rows == 480
    assert CAMPAIGN_BUDGET.sessions == 18
    assert CAMPAIGN_BUDGET.session_rotations == 12
    assert CAMPAIGN_BUDGET.screenshots == 24
    assert CAMPAIGN_BUDGET.retained_files == 1600
    assert CAMPAIGN_BUDGET.retained_bytes == 320 * 1024 * 1024
    assert CAMPAIGN_BUDGET.scenario_deadline_seconds == 1800
    assert CAMPAIGN_BUDGET.reactions == 24
    assert CAMPAIGN_BUDGET.executable_stocks == 12
    assert CAMPAIGN_BUDGET.intents == 48
    assert CAMPAIGN_BUDGET.droplets == 264
    for sequence in FROZEN_SEQUENCES:
        validate_sequence(sequence)
        normalized = sequence.normalized()
        assert normalized["steps"][-1]["to_state"] == "terminal"
        assert normalized["operation_count"] <= 18
        assert normalized["projected_action_rows"] <= 48
        assert normalized["sessions"] <= 3
        assert normalized["session_rotations"] <= 2
        assert normalized["screenshots"] <= 4


def test_sequence_validation_rejects_discontinuity_and_budget_overrun():
    sequence = FROZEN_SEQUENCES[0]
    broken_step = replace(sequence.steps[0], from_state="terminal")
    with pytest.raises(M13ExplorationValidationError, match="continuity"):
        validate_sequence(replace(sequence, steps=(broken_step,) + sequence.steps[1:]))

    with pytest.raises(M13ExplorationValidationError, match="screenshots budget"):
        validate_sequence(replace(sequence, screenshots=5))

    progress = FROZEN_SEQUENCES[-1]
    repeated = (
        progress.steps[0],
        *(
            SequenceStep(
                "editor.attempt_progressed_edit_via_ui",
                "progressed_locked",
                "progressed_locked",
            )
            for _ in range(17)
        ),
        progress.steps[-1],
    )
    with pytest.raises(M13ExplorationValidationError, match="semantic_operations budget"):
        validate_sequence(replace(progress, steps=tuple(repeated)))


def test_diagnostic_seeds_are_deterministic_explicit_and_gate_isolated():
    first = generate_diagnostic_sequence(1).normalized()
    assert first == generate_diagnostic_sequence(1).normalized()
    assert first["seed_tier"] == "diagnostic"
    assert first["sequence_id"].startswith("diagnostic_seed_1_")
    frozen_hash = catalog_sha256()
    plan = resolve_plan(seed_tier="diagnostic", diagnostic_seeds=(1, 101))
    assert plan["release_gate_affected"] is False
    assert plan["sequence_count"] == 2
    assert catalog_sha256() == frozen_hash
    with pytest.raises(M13ExplorationValidationError, match="requires an explicit"):
        resolve_plan(seed_tier="diagnostic")
    with pytest.raises(M13ExplorationValidationError, match="unique-seed cap"):
        resolve_plan(
            seed_tier="diagnostic",
            diagnostic_seeds=tuple(range(MAX_DIAGNOSTIC_SEEDS + 1)),
        )
    with pytest.raises(M13ExplorationValidationError, match="non-negative"):
        generate_diagnostic_sequence(-1)


def test_v2_plans_are_hash_identified_and_execution_authorization_is_explicit():
    plan = resolve_exploration_plan(
        CAMPAIGN_ID,
        sequence_id=EXPECTED_SEQUENCE_IDS[0],
        timeout_seconds=270,
        execution_authorized=False,
    )
    assert plan["schema_version"] == PLAN_SCHEMA_VERSION
    assert plan["campaign"]["catalog_sha256"] == EXPECTED_CATALOG_SHA256
    assert plan["campaign"]["campaign_sha256"] == EXPECTED_CAMPAIGN_SHA256
    assert plan["seed_tier"] == "frozen"
    assert plan["sequence_count"] == 1
    assert plan["execution_authorized"] is False
    assert plan["release_gate_affected"] is True
    authorized = resolve_plan(execution_authorized=True)
    assert authorized["execution_authorized"] is True
    assert authorized["sequence_count"] == 6
    with pytest.raises(M13ExplorationValidationError, match="exceeds the frozen"):
        resolve_plan(timeout_seconds=271)


def test_cli_lists_both_campaigns_and_plans_frozen_and_diagnostic(capsys):
    assert main(["--list", "explorations"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in listing["campaigns"]] == [M8_CAMPAIGN_ID, CAMPAIGN_ID]

    assert main(["--exploration", CAMPAIGN_ID, "--dry-run"]) == 0
    frozen = json.loads(capsys.readouterr().out)
    assert frozen["sequence_count"] == 6
    assert frozen["execution_authorized"] is False

    assert main([
        "--exploration", CAMPAIGN_ID,
        "--seed-tier", "diagnostic",
        "--diagnostic-seed", "1",
        "--dry-run",
    ]) == 0
    diagnostic = json.loads(capsys.readouterr().out)
    assert diagnostic["seed_tier"] == "diagnostic"
    assert diagnostic["release_gate_affected"] is False


def test_cli_rejects_m13_seed_tier_misuse_before_qt():
    with pytest.raises(SystemExit) as exc_info:
        main(["--exploration", CAMPAIGN_ID, "--seed-tier", "diagnostic", "--dry-run"])
    assert exc_info.value.code == 2
    with pytest.raises(SystemExit) as exc_info:
        main([
            "--exploration", M8_CAMPAIGN_ID,
            "--seed-tier", "diagnostic",
            "--diagnostic-seed", "1",
            "--dry-run",
        ])
    assert exc_info.value.code == 2


def test_m8_campaign_hash_and_plan_schema_remain_frozen():
    assert exploration_catalog_sha256() == (
        "7cfb5efa7e36175504a2fa04a6483add993f6db13d25bdd183dcd0d6809925e8"
    )
    plan = resolve_exploration_plan(
        M8_CAMPAIGN_ID,
        sequence_id="seed_7_legal",
        execution_authorized=False,
    )
    assert plan["schema_version"] == 1
    assert plan["sequences"][0]["sequence"]["seed"] == 7
    assert plan["campaign"]["catalog_sha256"] == exploration_catalog_sha256()
