from __future__ import annotations

import copy

import pytest

from tools.virtual_workflows.assertions import (
    joined_terminal_lifecycle_reconciliation,
)
from tools.virtual_workflows.joined_interaction_cases import (
    JOINED_INTERACTION_CASE,
)


def _literal_terminal_lifecycle():
    case = JOINED_INTERACTION_CASE
    expected = case.oracle("all_stocks_calibrated").keyed()
    begins = []
    attachments = []
    simulator = []
    completions = []
    sequence = 0
    for execution_pass in case.execution_passes:
        for well_id in case.editor.selected_well_ids:
            sequence += 1
            intent_id = f"intent-{sequence:02d}"
            droplets = expected[(execution_pass.stock_id, well_id)]
            begins.append(
                {
                    "intent_id": intent_id,
                    "stock_id": execution_pass.stock_id,
                    "well_id": well_id,
                    "commanded_droplets": droplets,
                }
            )
            attachments.append(
                {"intent_id": intent_id, "command_seq32": sequence}
            )
            simulator.append(
                {
                    "command_seq32": sequence,
                    "command_type": "DISPENSE",
                    "status": "Completed",
                    "manual": False,
                    "commanded_droplets": droplets,
                }
            )
            completions.append(intent_id)
    lifecycle = {
        "begins": begins,
        "attachments": attachments,
        "completions": completions,
        "discard_batches": [],
        "simulator_dispenses": simulator,
        "simulator_dispense_overflow_count": 0,
        "pass_starts": [
            {"stock_id": row.stock_id} for row in case.execution_passes
        ],
    }
    boundaries = [
        {
            "stock_id": case.execution_passes[0].stock_id,
            "observed_completed_count": 8,
            "plan_state": "active",
        },
        {
            "stock_id": case.execution_passes[1].stock_id,
            "observed_completed_count": 16,
            "plan_state": "active",
        },
        {
            "stock_id": case.execution_passes[2].stock_id,
            "observed_completed_count": 24,
            "plan_state": "completed",
        },
    ]
    return lifecycle, boundaries


def _reconcile(lifecycle, boundaries):
    return joined_terminal_lifecycle_reconciliation(
        case=JOINED_INTERACTION_CASE,
        lifecycle=lifecycle,
        pass_boundaries=boundaries,
    )


def test_joined_terminal_lifecycle_reconciles_literal_keyed_oracle():
    lifecycle, boundaries = _literal_terminal_lifecycle()

    evidence = _reconcile(lifecycle, boundaries)

    assert all(evidence["checks"].values())
    assert len(evidence["intent_counts"]) == 24
    assert len(evidence["simulator_dispenses"]) == 24
    assert set(evidence["command_join_checks"].values()) == {True}


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    (
        ("wrong_count", "intent_pairs_and_counts_exact"),
        ("duplicate_attachment", "attachments_exact_once"),
        ("missing_command_sequence", "simulator_commands_exact_once"),
        ("failed_simulator_command", "simulator_commands_exact_once"),
        ("duplicate_completion", "completion_ids_exact_once"),
        ("pass_order", "pass_order_exact"),
        ("pass_boundary", "pass_boundaries_exact"),
        ("overflow", "no_discard_or_overflow"),
    ),
)
def test_joined_terminal_lifecycle_mutations_fail_closed(mutation, failed_check):
    lifecycle, boundaries = _literal_terminal_lifecycle()
    lifecycle = copy.deepcopy(lifecycle)
    boundaries = copy.deepcopy(boundaries)

    if mutation == "wrong_count":
        lifecycle["begins"][0]["commanded_droplets"] += 1
    elif mutation == "duplicate_attachment":
        lifecycle["attachments"][1]["command_seq32"] = 1
    elif mutation == "missing_command_sequence":
        lifecycle["attachments"][0]["command_seq32"] = None
    elif mutation == "failed_simulator_command":
        lifecycle["simulator_dispenses"][0]["status"] = "Failed"
    elif mutation == "duplicate_completion":
        lifecycle["completions"][0] = lifecycle["completions"][1]
    elif mutation == "pass_order":
        lifecycle["pass_starts"][0], lifecycle["pass_starts"][1] = (
            lifecycle["pass_starts"][1],
            lifecycle["pass_starts"][0],
        )
    elif mutation == "pass_boundary":
        boundaries[1]["observed_completed_count"] = 15
    elif mutation == "overflow":
        lifecycle["simulator_dispense_overflow_count"] = 1

    evidence = _reconcile(lifecycle, boundaries)

    assert evidence["checks"][failed_check] is False
