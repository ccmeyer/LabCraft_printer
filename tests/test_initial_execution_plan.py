from dataclasses import replace

import pytest

from ExecutionPlan import ExecutionPlanState
from InitialExecutionPlan import (
    build_initial_execution_plan,
    initial_execution_content_matches,
)


PLAN_ID = "f33cf5d6-2f38-4ca7-86fd-74f73baac81d"
TIMESTAMP = "2026-07-17T12:00:00Z"


def _design():
    return {
        "metadata": {
            "name": "initial-plan",
            "target_reaction_volume_nL": 2500.0,
            "final_reaction_volume_nL": 3000.0,
            "printed_volume_tolerance_nL": 50.0,
            "fill_reagent_name": "Water",
            "fill_droplet_volume_nL": 10.0,
            "intended_fill_droplet_volume_nL": 9.0,
        },
        "factors": [
            {
                "name": "PURE_MM",
                "kind": "additive",
                "options": [
                    {
                        "name": "PURE_MM",
                        "units": "x",
                        "droplet_nL": 143.59278258103592,
                        "intended_droplet_nL": 60.0,
                    }
                ],
            },
            {
                "name": "UTP",
                "kind": "choice",
                "options": [
                    {"name": "UTP (dil)", "units": "nM", "droplet_nL": 10.5}
                ],
            },
        ],
    }


def _stock_rows():
    return [
        {
            "factor_name": "PURE_MM",
            "option_name": "",
            "stock_concentration": 1.11,
            "units": "x",
            "printing_mode": "stream",
            "droplet_volume_nL": 143.59278258103592,
        },
        {
            "factor_name": "UTP",
            "option_name": "UTP (dil)",
            "stock_concentration": 95000.0,
            "units": "nM",
            "printing_mode": "droplet",
            "droplet_volume_nL": 10.5,
        },
        {
            "factor_name": "Water",
            "option_name": "",
            "stock_concentration": 1.0,
            "units": "--",
            "printing_mode": "droplet",
            "droplet_volume_nL": 10.0,
        },
        {
            "factor_name": "Unused",
            "option_name": "",
            "stock_concentration": 2.0,
            "units": "mM",
            "printing_mode": "droplet",
            "droplet_volume_nL": 8.0,
        },
    ]


def _wells():
    return [
        {
            "well_id": "C3",
            "reaction_id": "R1",
            "target_dispenses": {
                "PURE_MM_1.11_x": 16,
                "UTP (dil)_95000.00_nM": 25,
                "Water_1.00_--": 3,
            },
        },
        {"well_id": "C4", "reaction_id": "R2", "target_dispenses": {}},
    ]


def _build(**overrides):
    kwargs = {
        "design_payload": _design(),
        "plate_name": "shallow-384_well_plate",
        "plate_rows": 16,
        "plate_columns": 24,
        "stock_rows": _stock_rows(),
        "assigned_wells": _wells(),
        "plan_id": PLAN_ID,
        "timestamp_utc": TIMESTAMP,
    }
    kwargs.update(overrides)
    return build_initial_execution_plan(**kwargs)


def test_builder_captures_exact_finalized_execution_facts():
    plan = _build()

    assert plan.state is ExecutionPlanState.PREPARED
    assert plan.plan_revision == 1
    assert plan.created_at_utc == plan.updated_at_utc == TIMESTAMP
    assert plan.locked_at_utc is None
    assert plan.lock_reason is None
    assert {stock.stock_id for stock in plan.stocks} == {
        "PURE_MM_1.11_x",
        "UTP (dil)_95000.00_nM",
        "Water_1.00_--",
    }
    pure = next(stock for stock in plan.stocks if stock.stock_id == "PURE_MM_1.11_x")
    utp = next(stock for stock in plan.stocks if stock.stock_id.startswith("UTP (dil)"))
    water = next(stock for stock in plan.stocks if stock.stock_id.startswith("Water_"))
    assert pure.reagent_name == "PURE_MM"
    assert pure.intended_volume_nL == 60.0
    assert pure.effective_volume_nL == 143.59278258103592
    assert utp.option_name == "UTP (dil)"
    assert utp.intended_volume_nL == 10.5
    assert water.intended_volume_nL == 9.0
    assert all(stock.printer_head_id is None for stock in plan.stocks)
    assert all(stock.calibration_record_key is None for stock in plan.stocks)
    assert len(plan.wells) == 2
    assert next(well for well in plan.wells if well.well_id == "C4").dispenses == ()
    expected = 16 * 143.59278258103592 + 25 * 10.5 + 3 * 10.0
    assert next(well for well in plan.wells if well.well_id == "C3").expected_printed_volume_nL == pytest.approx(expected)


def test_builder_is_deterministic_with_injected_identity_and_time():
    assert _build() == _build(stock_rows=reversed(_stock_rows()), assigned_wells=reversed(_wells()))


def test_initial_content_match_ignores_identity_and_timestamps_only():
    first = _build()
    retry = replace(
        first,
        plan_id="574f7c0a-a37f-42f8-aeb2-9cf8f239560b",
        created_at_utc="2026-07-17T13:00:00Z",
        updated_at_utc="2026-07-17T13:00:00Z",
    )

    assert initial_execution_content_matches(first, retry)
    assert not initial_execution_content_matches(
        first,
        replace(retry, design_sha256="b" * 64),
    )


def test_builder_rejects_missing_runtime_stock_mapping():
    rows = [row for row in _stock_rows() if row["factor_name"] != "UTP"]
    with pytest.raises(ValueError, match="absent from the exact stock plan"):
        _build(stock_rows=rows)


def test_builder_rejects_duplicate_formatted_stock_ids():
    rows = _stock_rows()
    rows.append(dict(rows[0]))
    with pytest.raises(ValueError, match="duplicate stock ID"):
        _build(stock_rows=rows)


def test_builder_rejects_ambiguous_design_mapping():
    design = _design()
    design["factors"][0]["options"].append(dict(design["factors"][0]["options"][0]))
    with pytest.raises(ValueError, match="maps to 2 design options"):
        _build(design_payload=design)


def test_builder_rejects_wells_outside_plate():
    wells = _wells()
    wells[0] = {**wells[0], "well_id": "Q1"}
    with pytest.raises(ValueError, match="outside the declared"):
        _build(assigned_wells=wells)
