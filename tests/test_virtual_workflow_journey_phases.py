from __future__ import annotations

from collections import Counter

import pytest

from tools.virtual_workflows.composition import normalized_steps
from tools.virtual_workflows.journey_phases import (
    StockPassSpec,
    machine_startup_steps,
    normalized_stock_pass_steps,
)


def _stock(
    stock_id: str,
    head_id: str,
    *,
    completion_count: int,
    plan_state: str,
    first: bool,
) -> StockPassSpec:
    return StockPassSpec(
        stock_id=stock_id,
        printer_head_id=head_id,
        pulse_width_us=1300 if first else 1800,
        pressure_psi=1.2 if first else 1.5,
        frequency_hz=20,
        initial_volume_uL=1000.0,
        expected_volume_nL=9.0 if first else 18.0,
        expected_completion_count=completion_count,
        expected_plan_state=plan_state,
        ready_milestone="stock_1_ready" if first else "stock_2_staged",
        printing_milestone="stock_1_printing" if first else "stock_2_printing",
        completed_milestone="stock_1_completed" if first else "completed",
        start_dialog_titles=(
            ("Start Print Array", "Evaporation Plate Dock Check")
            if first
            else ("Start Print Array",)
        ),
        bind_identity=True,
        enable_pressure_regulation=first,
        validate_pass_boundary=True,
        return_head=True,
        detailed_evidence=True,
        include_frequency_evidence=False,
    )


def test_machine_startup_is_one_normalized_reusable_ui_phase():
    assert normalized_steps(machine_startup_steps()) == [
        {"action_id": "machine.connect_via_ui", "interaction_surface": "ui"},
        {
            "action_id": "machine.enable_motors_via_ui",
            "interaction_surface": "ui",
        },
        {"action_id": "machine.home_via_ui", "interaction_surface": "ui"},
    ]


def test_two_stock_plan_has_exact_repeated_groups_and_truthful_surfaces():
    specs = (
        _stock("stock-a", "head-a", completion_count=24, plan_state="active", first=True),
        _stock("stock-b", "head-b", completion_count=48, plan_state="completed", first=False),
    )

    plan = normalized_stock_pass_steps(specs)
    action_ids = [row["action_id"] for row in plan]

    assert action_ids.count("head.bind_identity") == 1
    for action_id in (
        "machine.configure_print_settings_via_ui",
        "head.set_volume_via_ui",
        "head.stage_via_ui",
        "calibration.open_via_ui",
        "calibration.generate_via_ui",
        "calibration.select_via_ui",
        "calibration.apply_via_ui",
        "array.start_via_ui",
        "array.wait_for_completions",
        "validation.stock_pass_boundary",
        "head.return_via_ui",
    ):
        assert action_ids.count(action_id) == 2
    assert action_ids.count("pressure.enable_regulation_via_ui") == 1
    assert next(row for row in plan if row["action_id"] == "head.bind_identity")[
        "interaction_surface"
    ] == "model"
    assert {
        row["interaction_surface"]
        for row in plan
        if row["action_id"] == "array.wait_for_completions"
    } == {"harness"}


def test_stock_values_and_order_vary_without_new_runner_code():
    first = _stock("stock-a", "head-a", completion_count=24, plan_state="active", first=True)
    second = _stock("stock-b", "head-b", completion_count=48, plan_state="completed", first=False)

    forward = normalized_stock_pass_steps((first, second))
    reverse = normalized_stock_pass_steps((second, first))

    assert [row["stock_id"] for row in forward if row["action_id"] == "head.stage_via_ui"] == [
        "stock-a",
        "stock-b",
    ]
    assert [row["stock_id"] for row in reverse if row["action_id"] == "head.stage_via_ui"] == [
        "stock-b",
        "stock-a",
    ]
    assert Counter(row["action_id"] for row in forward) == Counter(
        row["action_id"] for row in reverse
    )


def test_stock_pass_contract_rejects_invalid_boundary_values():
    with pytest.raises(ValueError, match="completion count"):
        StockPassSpec(
            stock_id="stock",
            printer_head_id="head",
            pulse_width_us=1300,
            pressure_psi=1.2,
            frequency_hz=20,
            initial_volume_uL=1000.0,
            expected_volume_nL=9.0,
            expected_completion_count=0,
            expected_plan_state="completed",
            ready_milestone="ready",
            printing_milestone="printing",
            completed_milestone="completed",
        )
