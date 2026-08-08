from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.virtual_workflows.dispense_counts import (
    StockWellCount,
    intent_and_simulator_counts,
    normalize_stock_well_counts,
    plan_target_counts,
    project_single_stock_preview_counts,
    reconcile_stock_well_counts,
    runtime_target_counts,
)


def _rows(*values):
    return tuple(StockWellCount(*value) for value in values)


def test_plan_and_runtime_counts_are_stock_well_sorted():
    plan = SimpleNamespace(
        wells=(
            SimpleNamespace(
                well_id="B1",
                dispenses=(SimpleNamespace(stock_id="stock-b", target_dispenses=3),),
            ),
            SimpleNamespace(
                well_id="A1",
                dispenses=(
                    SimpleNamespace(stock_id="stock-b", target_dispenses=2),
                    SimpleNamespace(stock_id="stock-a", target_dispenses=1),
                ),
            ),
        )
    )
    reagents = {
        "stock-b": SimpleNamespace(get_target_droplets=lambda: 2),
        "stock-a": SimpleNamespace(get_target_droplets=lambda: 1),
    }
    reaction = SimpleNamespace(get_all_reagents=lambda: reagents)
    wells = [
        SimpleNamespace(
            well_id="A1", get_assigned_reaction=lambda: reaction
        )
    ]
    context = SimpleNamespace(
        model=SimpleNamespace(
            well_plate=SimpleNamespace(get_all_wells=lambda: wells)
        )
    )

    assert plan_target_counts(plan) == _rows(
        ("stock-a", "A1", 1),
        ("stock-b", "A1", 2),
        ("stock-b", "B1", 3),
    )
    assert runtime_target_counts(context) == _rows(
        ("stock-a", "A1", 1),
        ("stock-b", "A1", 2),
    )


def test_preview_projection_uses_exact_visible_single_stock_drop_cells():
    preview = {
        "visible_table": {
            "headers": ["Target", "Drops"],
            "rows": [["1.00", "3"], ["2.00", "4"]],
            "row_count": 2,
            "column_count": 2,
        }
    }

    assert project_single_stock_preview_counts(
        preview,
        stock_id="stock-a",
        well_ids_by_row=(("A1", "A2"), ("B1",)),
    ) == _rows(
        ("stock-a", "A1", 3),
        ("stock-a", "A2", 3),
        ("stock-a", "B1", 4),
    )


@pytest.mark.parametrize("drops", [None, True, -1, "1+2", "(1,2) = 3"])
def test_preview_projection_rejects_non_single_stock_integer_cells(drops):
    preview = {
        "visible_table": {
            "headers": ["Drops"],
            "rows": [[drops]],
            "row_count": 1,
            "column_count": 1,
        }
    }
    with pytest.raises(ValueError, match="single-stock integer"):
        project_single_stock_preview_counts(
            preview,
            stock_id="stock-a",
            well_ids_by_row=(("A1",),),
        )


def test_intents_join_exactly_to_completed_simulator_dispenses():
    lifecycle = {
        "begins": [
            {
                "intent_id": "i-2", "stock_id": "stock-b", "well_id": "A1",
                "commanded_droplets": 4,
            },
            {
                "intent_id": "i-1", "stock_id": "stock-a", "well_id": "A1",
                "commanded_droplets": 3,
            },
        ],
        "attachments": [
            {"intent_id": "i-1", "command_seq32": 10},
            {"intent_id": "i-2", "command_seq32": 11},
        ],
        "simulator_dispenses": [
            {
                "command_seq32": 9, "command_type": "DISPENSE",
                "commanded_droplets": 50, "manual": True, "status": "Completed",
            },
            {
                "command_seq32": 10, "command_type": "DISPENSE",
                "commanded_droplets": 3, "manual": False, "status": "Completed",
            },
            {
                "command_seq32": 11, "command_type": "DISPENSE",
                "commanded_droplets": 4, "manual": False, "status": "Completed",
            },
        ],
        "simulator_dispense_limit": 10_000,
        "simulator_dispense_overflow_count": 0,
    }

    intents, simulator, evidence = intent_and_simulator_counts(lifecycle)

    expected = _rows(("stock-a", "A1", 3), ("stock-b", "A1", 4))
    assert intents == simulator == expected
    assert evidence["unattached_dispenses"] == [lifecycle["simulator_dispenses"][0]]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value["attachments"].append(dict(value["attachments"][0])), "duplicate command attachment"),
        (lambda value: value["simulator_dispenses"][0].update(command_type="WAIT"), "not DISPENSE"),
        (lambda value: value["simulator_dispenses"][0].update(status="Accepted"), "not completed"),
        (lambda value: value.update(simulator_dispense_overflow_count=1), "overflowed"),
    ],
)
def test_intent_simulator_join_rejects_ambiguous_or_incomplete_evidence(change, message):
    lifecycle = {
        "begins": [{
            "intent_id": "i-1", "stock_id": "stock-a", "well_id": "A1",
            "commanded_droplets": 3,
        }],
        "attachments": [{"intent_id": "i-1", "command_seq32": 10}],
        "simulator_dispenses": [{
            "command_seq32": 10, "command_type": "DISPENSE",
            "commanded_droplets": 3, "manual": False, "status": "Completed",
        }],
        "simulator_dispense_overflow_count": 0,
    }
    change(lifecycle)
    with pytest.raises(ValueError, match=message):
        intent_and_simulator_counts(lifecycle)


def test_reconciliation_requires_exact_layers_identities_and_counts():
    expected = _rows(("stock-a", "A1", 3))
    matched = reconcile_stock_well_counts(
        expected={"plan": expected, "simulator": expected},
        observed={"plan": expected, "simulator": expected},
        required_layers=("plan", "simulator"),
    )
    mismatched = reconcile_stock_well_counts(
        expected={"plan": expected, "simulator": expected},
        observed={
            "plan": expected,
            "simulator": _rows(("stock-a", "A1", 2)),
        },
        required_layers=("plan", "simulator"),
    )

    assert matched.passed is True
    assert mismatched.passed is False
    assert mismatched.checks == {"plan": True, "simulator": False}


def test_reconciliation_rejects_duplicate_invalid_and_missing_layers():
    with pytest.raises(ValueError, match="duplicate stock/well"):
        normalize_stock_well_counts(
            [
                {"stock_id": "stock-a", "well_id": "A1", "droplets": 1},
                {"stock_id": "stock-a", "well_id": "A1", "droplets": 2},
            ],
            label="duplicate",
        )
    with pytest.raises(ValueError, match="non-negative integer"):
        StockWellCount("stock-a", "A1", True)
    with pytest.raises(ValueError, match="exactly match"):
        reconcile_stock_well_counts(
            expected={"plan": _rows(("stock-a", "A1", 1))},
            observed={"plan": _rows(("stock-a", "A1", 1))},
            required_layers=("plan", "simulator"),
        )
