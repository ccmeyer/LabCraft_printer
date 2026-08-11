from __future__ import annotations

from collections import Counter

import pytest

from tools.virtual_workflows.harness import (
    AutomationHarness,
    AutomationHarnessConfig,
)
from tools.virtual_workflows.page_drivers import (
    MachineControlsDriver,
    RackDriver,
)


def _seed_rack_heads(context):
    """Model-only test setup; this is not recorded as UI interaction coverage."""

    model = context.model
    stock_manager = model.stock_solutions
    head_manager = model.printer_head_manager
    stock_ids = []
    for index in range(1, 11):
        reagent = f"Rack Check Stock {index:02d}"
        stock_manager.add_stock_solution(reagent, 10.0, "x")
        stock = stock_manager.get_stock_solution(reagent, 10.0, "x")
        stock_ids.append(stock.get_stock_id())
    head_manager.create_printer_heads(stock_manager)

    heads = {
        str(head.get_stock_id()): head
        for head in head_manager.printer_heads
        if not head.is_calibration_chip()
    }
    assert set(heads) == set(stock_ids)
    for index, stock_id in enumerate(stock_ids, start=1):
        heads[stock_id].set_identity_metadata(
            printer_head_id=f"rack-check-head-{index:02d}"
        )
    for slot_index in range(4):
        assert head_manager.assign_printer_head_to_slot(slot_index) is True
    context.view.rack_box.update_all_slots()
    context.pump_events()
    return stock_ids, heads


def _assert_repopulated_rack(context) -> None:
    unassigned_labels = [
        head.get_display_stock_name()
        for head in context.model.printer_head_manager.get_unassigned_printer_heads()
    ]
    assert len(unassigned_labels) == 6
    assert len(set(unassigned_labels)) == 6
    for _label, _volume, _button, combo in context.view.rack_box.slot_widgets:
        options = [combo.itemText(index) for index in range(combo.count())]
        counts = Counter(options)
        assert combo.currentText() == "Swap"
        assert not combo.view().isVisible()
        assert all(counts[label] == 1 for label in unassigned_labels)


@pytest.mark.sil_lifecycle
def test_real_rack_cycles_six_heads_without_printing(qapp, tmp_path):
    harness = AutomationHarness(
        AutomationHarnessConfig(
            scenario_id="focused_visible_rack_swap",
            workload_id="focused_visible_rack_swap",
            output_root=tmp_path,
            visible=True,
            seed=1,
            speed_multiplier=1000.0,
            timeout_seconds=30.0,
            run_id="focused-visible-rack-swap",
        )
    )
    teardown = None
    try:
        harness.start()
        context = harness.context
        MachineControlsDriver(context).connect()
        stock_ids, heads = _seed_rack_heads(context)
        rack = RackDriver(context)

        assert context.controller.get_array_run_state() == "idle"
        assert context.model.rack_model.get_gripper_printer_head() is None
        assert context.machine.check_if_all_completed()
        assert [
            slot.printer_head for slot in context.model.rack_model.slots[:4]
        ] == [heads[stock_id] for stock_id in stock_ids[:4]]

        previous = heads[stock_ids[0]]
        evidence = []
        for stock_id in stock_ids[4:]:
            target = heads[stock_id]
            evidence.append(rack.swap_unassigned_head(0, stock_id))
            unassigned = (
                context.model.printer_head_manager.get_unassigned_printer_heads()
            )
            assert context.model.rack_model.slots[0].printer_head is target
            assert sum(head is target for head in unassigned) == 0
            assert sum(head is previous for head in unassigned) == 1
            assert context.model.rack_model.get_gripper_printer_head() is None
            assert context.controller.get_array_run_state() == "idle"
            assert context.machine.check_if_all_completed()
            harness.assert_no_unexpected_dialog()
            _assert_repopulated_rack(context)
            previous = target

        assert [row["printer_head_id"] for row in evidence] == [
            f"rack-check-head-{index:02d}" for index in range(5, 11)
        ]
        assert [row["replaced_printer_head_id"] for row in evidence] == [
            "rack-check-head-01",
            *[f"rack-check-head-{index:02d}" for index in range(5, 10)],
        ]
        assert context.model.rack_model.slots[0].printer_head is heads[stock_ids[9]]
        assert not any(
            row.get("action_id", "").startswith("array.")
            for row in context.action_results
        )
    finally:
        teardown = harness.close()

    assert teardown["status"] == "pass"
    assert teardown["evidence"]["close_succeeded"] is True
