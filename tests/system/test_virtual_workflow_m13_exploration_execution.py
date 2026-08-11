from __future__ import annotations

import json

import pytest

from tools.virtual_workflows.journeys import (
    M13_EXPLORATION_WORKLOAD_ID,
    M13_LEGAL_REQUIRED_ASSERTIONS,
    M13_LEGAL_REQUIRED_SCREENSHOTS,
    JourneyRunConfig,
    run_exploration_sequence,
)
from tools.virtual_workflows.exploration_m13 import (
    M13_REJECTION_CASES,
    get_sequence,
)
from tools.virtual_workflows.report import validate_report_v1


@pytest.mark.sil_lifecycle
@pytest.mark.parametrize(
    "sequence_id,seed",
    (
        ("seed_13_legal_design_calibration_terminal", 13),
        ("seed_29_legal_refinalize_reload_terminal", 29),
    ),
)
def test_m13_legal_sequences_reach_exact_terminal_authority(
    qapp,
    tmp_path,
    sequence_id,
    seed,
):
    report = run_exploration_sequence(
        JourneyRunConfig(
            scenario_id=M13_EXPLORATION_WORKLOAD_ID,
            output_root=tmp_path / str(seed),
            visible=False,
            seed=seed,
            speed_multiplier=1000.0,
            timeout_seconds=270.0,
            run_id=f"m13-legal-{seed}",
        ),
        campaign_id=M13_EXPLORATION_WORKLOAD_ID,
        sequence_id=sequence_id,
    )
    validate_report_v1(report)
    workflow = report["metrics"]["workflow"]["values"]
    assert report["classification"]["status"] == "pass", json.dumps(
        {
            "reasons": report["classification"]["reasons"],
            "assertions": workflow["assertion_results"],
            "errors": workflow["errors"],
        },
        indent=2,
    )
    assert report["workload"]["sequence_id"] == sequence_id
    assert report["workload"]["expected_intent_count"] == 8
    assert report["workload"]["expected_droplets"] == 44
    assert workflow["completed_stock_well_count"] == 8
    assert workflow["action_count"] <= workflow["action_cap"] == 80
    assert set(report["artifacts"]["screenshots"]) == set(
        M13_LEGAL_REQUIRED_SCREENSHOTS
    )
    assert {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    } == {
        assertion_id: "pass" for assertion_id in M13_LEGAL_REQUIRED_ASSERTIONS
    }
    semantic = workflow["sequence_exploration"]
    assert semantic["sequence"]["sequence_id"] == sequence_id
    assert semantic["sequence"]["operation_count"] <= 18
    terminal = report["metrics"]["persistence"]["values"]["terminal"]
    assert terminal["terminal"]["plan_state"] == "completed"
    assert terminal["terminal"]["total_added_droplets"] == 44
    assert len(terminal["application_sessions"]) == 3
    assert all(terminal["checks"].values())


@pytest.mark.sil_lifecycle
@pytest.mark.parametrize(
    "sequence_id,seed",
    (
        ("seed_47_illegal_editor_recovery_terminal", 47),
        ("seed_83_illegal_calibration_recovery_terminal", 83),
        ("seed_131_illegal_identity_activation_recovery_terminal", 131),
        ("seed_197_illegal_progress_lock_recovery_terminal", 197),
    ),
)
def test_m13_illegal_sequences_reject_without_mutation_then_recover(
    qapp,
    tmp_path,
    sequence_id,
    seed,
):
    report = run_exploration_sequence(
        JourneyRunConfig(
            scenario_id=M13_EXPLORATION_WORKLOAD_ID,
            output_root=tmp_path / str(seed),
            visible=False,
            seed=seed,
            speed_multiplier=1000.0,
            timeout_seconds=270.0,
            run_id=f"m13-illegal-{seed}",
        ),
        campaign_id=M13_EXPLORATION_WORKLOAD_ID,
        sequence_id=sequence_id,
    )
    validate_report_v1(report)
    assert report["classification"]["status"] == "pass", json.dumps(
        report["classification"], indent=2
    )
    workflow = report["metrics"]["workflow"]["values"]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    sequence = get_sequence(sequence_id)
    rejected = tuple(
        step.operation_id
        for step in sequence.steps
        if step.operation_id in M13_REJECTION_CASES
    )
    assert rejected
    assert decisions["exploration.m13_illegal_recovery_exact"] == "pass"
    for operation_id in rejected:
        assertion_id = (
            "exploration.m13_rejection."
            + M13_REJECTION_CASES[operation_id]
        )
        assert decisions[assertion_id] == "pass"
    semantic = workflow["sequence_exploration"]["semantic_oracle"]
    assert set(semantic["rejections"]) == set(rejected)
    assert workflow["action_count"] <= workflow["action_cap"] == 80
    assert set(report["artifacts"]["screenshots"]) == set(
        M13_LEGAL_REQUIRED_SCREENSHOTS
    )
    terminal = report["metrics"]["persistence"]["values"]["terminal"]
    assert terminal["terminal"]["plan_state"] == "completed"
    assert terminal["terminal"]["total_added_droplets"] == 44
    assert all(terminal["checks"].values())
