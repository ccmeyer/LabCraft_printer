from dataclasses import replace

import pytest

from ExecutionPlan import ExecutionPlanState
from ExecutionPlanRevision import (
    build_calibrated_revision,
    build_locked_revision,
    build_printer_head_binding_revision,
    persist_immutable_revision,
    validate_revision_history,
)
from InitialExecutionPlan import build_initial_execution_plan


PLAN_ID = "f33cf5d6-2f38-4ca7-86fd-74f73baac81d"


def _prepared_plan():
    design = {
        "metadata": {
            "target_reaction_volume_nL": 2550.0,
            "final_reaction_volume_nL": 3000.0,
            "printed_volume_tolerance_nL": 50.0,
            "fill_reagent_name": "Water",
            "fill_droplet_volume_nL": 10.0,
        },
        "factors": [
            {
                "name": "PURE MM",
                "kind": "additive",
                "options": [{"name": "PURE MM", "units": "x", "droplet_nL": 140.0}],
            },
            {
                "name": "UTP",
                "kind": "choice",
                "options": [{"name": "UTP (dil)", "units": "nM", "droplet_nL": 10.5}],
            },
        ],
    }
    stocks = [
        {
            "factor_name": "PURE MM", "option_name": "", "stock_concentration": 1.0,
            "units": "x", "printing_mode": "stream", "droplet_volume_nL": 140.0,
        },
        {
            "factor_name": "UTP", "option_name": "UTP (dil)", "stock_concentration": 95000.0,
            "units": "nM", "printing_mode": "droplet", "droplet_volume_nL": 10.5,
        },
        {
            "factor_name": "Water", "option_name": "", "stock_concentration": 1.0,
            "units": "--", "printing_mode": "droplet", "droplet_volume_nL": 10.0,
        },
    ]
    wells = [{
        "well_id": "A1",
        "reaction_id": "R1",
        "target_dispenses": {
            "PURE MM_1.00_x": 16,
            "UTP (dil)_95000.00_nM": 25,
            "Water_1.00_--": 5,
        },
    }]
    return build_initial_execution_plan(
        design_payload=design,
        plate_name="plate",
        plate_rows=8,
        plate_columns=12,
        stock_rows=stocks,
        assigned_wells=wells,
        plan_id=PLAN_ID,
        timestamp_utc="2026-07-17T12:00:00Z",
    )


def test_lock_revision_changes_only_lifecycle_fields():
    prepared = _prepared_plan()
    active = build_locked_revision(
        prepared,
        reason="calibration_started",
        timestamp_utc="2026-07-17T12:01:00Z",
    )

    assert active.state is ExecutionPlanState.ACTIVE
    assert active.plan_revision == 2
    assert active.lock_reason == "calibration_started"
    assert active.locked_at_utc == "2026-07-17T12:01:00Z"
    assert active.stocks == prepared.stocks
    assert active.wells == prepared.wells
    assert build_locked_revision(active, reason="printing_started") is active


def test_calibrated_revision_can_exceed_design_optimization_limit():
    active = build_locked_revision(
        _prepared_plan(),
        reason="calibration_started",
        timestamp_utc="2026-07-17T12:01:00Z",
    )
    targets = {
        "A1": {
            "PURE MM_1.00_x": 16,
            "UTP (dil)_95000.00_nM": 25,
            "Water_1.00_--": 0,
        }
    }
    calibrated = build_calibrated_revision(
        active,
        stock_id="PURE MM_1.00_x",
        effective_volume_nL=143.59278258103592,
        printing_mode="stream",
        printer_head_id="head-1",
        calibration_record_key="d99ef420-efdc-5c07-a30f-3af3330e610d",
        target_counts_by_well=targets,
        timestamp_utc="2026-07-17T12:02:00Z",
    )

    well = calibrated.wells[0]
    assert well.expected_printed_volume_nL == pytest.approx(2559.9845212965747)
    assert well.expected_printed_volume_nL > calibrated.volume_basis.target_printed_volume_nL
    assert calibrated.plan_revision == 3
    assert calibrated.locked_at_utc == active.locked_at_utc
    assert calibrated.lock_reason == active.lock_reason


def test_printer_head_binding_revision_changes_only_one_unbound_stock():
    active = build_locked_revision(
        _prepared_plan(),
        reason="printing_started",
        timestamp_utc="2026-07-17T12:01:00Z",
    )

    bound = build_printer_head_binding_revision(
        active,
        stock_id="PURE MM_1.00_x",
        printer_head_id="head-1",
        timestamp_utc="2026-07-17T12:02:00Z",
    )

    assert bound.plan_revision == active.plan_revision + 1
    assert bound.wells == active.wells
    assert bound.locked_at_utc == active.locked_at_utc
    changed = [
        stock for stock in bound.stocks if stock.printer_head_id == "head-1"
    ]
    assert [stock.stock_id for stock in changed] == ["PURE MM_1.00_x"]
    assert build_printer_head_binding_revision(
        bound,
        stock_id="PURE MM_1.00_x",
        printer_head_id="head-1",
    ) is bound
    with pytest.raises(ValueError, match="different printer head"):
        build_printer_head_binding_revision(
            bound,
            stock_id="PURE MM_1.00_x",
            printer_head_id="head-2",
        )


def test_calibration_revision_may_retain_identical_target_counts(tmp_path):
    prepared = _prepared_plan()
    active = build_locked_revision(
        prepared,
        reason="calibration_started",
        timestamp_utc="2026-07-17T12:01:00Z",
    )
    stock = next(item for item in active.stocks if item.stock_id == "PURE MM_1.00_x")
    targets = {
        well.well_id: {
            dispense.stock_id: dispense.target_dispenses
            for dispense in well.dispenses
        }
        for well in active.wells
    }
    record_id = "d99ef420-efdc-5c07-a30f-3af3330e610d"
    calibrated = build_calibrated_revision(
        active,
        stock_id=stock.stock_id,
        effective_volume_nL=stock.effective_volume_nL,
        printing_mode=stock.printing_mode,
        printer_head_id="head-1",
        calibration_record_key=record_id,
        target_counts_by_well=targets,
        timestamp_utc="2026-07-17T12:02:00Z",
    )

    assert calibrated.wells == active.wells
    persist_immutable_revision(tmp_path, prepared)
    persist_immutable_revision(tmp_path, active)
    persist_immutable_revision(tmp_path, calibrated)
    assert validate_revision_history(
        tmp_path,
        latest_plan=calibrated,
        calibration_record_ids={record_id},
    ) == (prepared, active, calibrated)


def test_revision_history_is_immutable_contiguous_and_latest_mirrored(tmp_path):
    prepared = _prepared_plan()
    active = build_locked_revision(
        prepared,
        reason="printing_started",
        timestamp_utc="2026-07-17T12:01:00Z",
    )
    assert persist_immutable_revision(tmp_path, prepared) == "created"
    assert persist_immutable_revision(tmp_path, active) == "created"
    assert persist_immutable_revision(tmp_path, active) == "reused"
    assert validate_revision_history(tmp_path, latest_plan=active) == (prepared, active)

    with pytest.raises(RuntimeError, match="different content"):
        persist_immutable_revision(
            tmp_path,
            replace(active, updated_at_utc="2026-07-17T12:01:01Z"),
        )
