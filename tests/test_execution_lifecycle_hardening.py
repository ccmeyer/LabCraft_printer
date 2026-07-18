from dataclasses import replace

import pytest

from ExecutionPlan import ExecutionPlanState
from ExecutionPlanRevision import (
    build_locked_revision,
    build_terminal_revision,
    persist_immutable_revision,
    validate_revision_history,
)
from InitialExecutionPlan import build_initial_execution_plan


PLAN_ID = "f33cf5d6-2f38-4ca7-86fd-74f73baac81d"
NOW = "2026-07-17T12:00:00Z"


def _active_plan():
    design = {
        "metadata": {
            "target_reaction_volume_nL": 100.0,
            "final_reaction_volume_nL": 100.0,
            "printed_volume_tolerance_nL": 10.0,
            "fill_reagent_name": "Water",
            "fill_droplet_volume_nL": 10.0,
        },
        "factors": [{
            "name": "Mg", "kind": "additive",
            "options": [{"name": "Mg", "units": "mM", "droplet_nL": 10.0}],
        }],
    }
    prepared = build_initial_execution_plan(
        design_payload=design,
        plate_name="plate",
        plate_rows=8,
        plate_columns=12,
        stock_rows=[{
            "factor_name": "Mg", "option_name": "", "stock_concentration": 1.0,
            "units": "mM", "printing_mode": "droplet", "droplet_volume_nL": 10.0,
        }],
        assigned_wells=[{
            "well_id": "A1", "reaction_id": "R1",
            "target_dispenses": {"Mg_1.00_mM": 3},
        }],
        plan_id=PLAN_ID,
        timestamp_utc=NOW,
    )
    return prepared, build_locked_revision(
        prepared, reason="printing_started", timestamp_utc="2026-07-17T12:01:00Z"
    )


def test_completed_terminal_revision_requires_exact_targets_and_clean_intents():
    _prepared, active = _active_plan()
    with pytest.raises(ValueError, match="exactly equal"):
        build_terminal_revision(
            active,
            state="completed",
            added_counts_by_well={"A1": {"Mg_1.00_mM": 2}},
        )
    with pytest.raises(ValueError, match="pending"):
        build_terminal_revision(
            active,
            state="completed",
            added_counts_by_well={"A1": {"Mg_1.00_mM": 3}},
            has_pending_intents=True,
        )

    completed = build_terminal_revision(
        active,
        state=ExecutionPlanState.COMPLETED,
        added_counts_by_well={"A1": {"Mg_1.00_mM": 3}},
        timestamp_utc="2026-07-17T12:02:00Z",
    )
    assert completed.state is ExecutionPlanState.COMPLETED
    assert completed.stocks == active.stocks
    assert completed.wells == active.wells
    assert build_terminal_revision(
        completed,
        state="completed",
        added_counts_by_well={"A1": {"Mg_1.00_mM": 3}},
    ) is completed


def test_aborted_revision_preserves_facts_and_history_rejects_successor(tmp_path):
    prepared, active = _active_plan()
    aborted = build_terminal_revision(
        active,
        state="aborted",
        added_counts_by_well={"A1": {"Mg_1.00_mM": 1}},
        has_pending_intents=True,
        timestamp_utc="2026-07-17T12:02:00Z",
    )
    for plan in (prepared, active, aborted):
        persist_immutable_revision(tmp_path, plan)
    assert validate_revision_history(tmp_path, latest_plan=aborted)[-1] == aborted

    successor = replace(
        aborted,
        plan_revision=aborted.plan_revision + 1,
        updated_at_utc="2026-07-17T12:03:00Z",
    )
    persist_immutable_revision(tmp_path, successor)
    with pytest.raises(RuntimeError, match="cannot have successors"):
        validate_revision_history(tmp_path, latest_plan=successor)

