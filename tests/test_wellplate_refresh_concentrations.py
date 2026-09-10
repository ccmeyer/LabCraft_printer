"""No-hardware regression coverage for the dense plate display call path."""
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from Model import ExperimentModel
from View import WellPlateWidget
from tests.fakes import FakeSignal


@pytest.fixture
def dense_model(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    stocks = [NS(stock_id=f"S{i}", concentration=100.0, effective_volume_nL=10.0,
                 reagent_name=f"R{i}", factor_name=f"R{i}", units="mM")
              for i in range(10)]
    wells = []
    plan_wells = []
    for row in range(16):
        for col in range(24):
            well_id = f"{chr(65 + row)}{col + 1}"
            reaction = NS(get_target_droplets_for_stock=lambda _: 2,
                          check_stock_complete=lambda _: False)
            wells.append(NS(well_id=well_id, row_num=row, col=col + 1,
                            assigned_reaction=reaction))
            plan_wells.append(NS(well_id=well_id, dispenses=[
                NS(stock_id=s.stock_id, target_dispenses=2) for s in stocks]))
    em._execution_plan_snapshot = NS(
        stocks=stocks, wells=plan_wells,
        volume_basis=NS(final_reaction_volume_nL=500.0, target_printed_volume_nL=400.0),
    )
    em._execution_plan_source = "initial_finalization"
    em._execution_concentration_details = Mock(wraps=em._execution_concentration_details)
    by_id = {w.well_id: w for w in wells}
    model.well_plate = NS(
        get_all_wells=lambda: wells, get_well=by_id.get,
        get_plate_dimensions=lambda: (16, 24), get_num_rows=lambda: 16,
        get_num_cols=lambda: 24, get_current_plate_name=lambda: "384 well",
        iter_rows=lambda: iter("ABCDEFGHIJKLMNOP"),
        well_state_changed_signal=FakeSignal(), clear_all_wells_signal=FakeSignal(),
        plate_format_changed_signal=FakeSignal(), plate_summary_changed_signal=FakeSignal(),
    )
    model.reaction_collection = NS(is_empty=lambda: False, get_max_droplets=lambda _: 2)
    model.stock_solutions = NS(
        get_stock_solution_names=lambda: [s.stock_id for s in stocks],
        get_formatted_from_stock_id=lambda sid: sid,
        get_stock_by_id=lambda _: NS(units="mM"),
    )
    model.printer_head_manager = NS(get_printer_head_by_id=lambda _: NS(get_color=lambda: "blue"))
    model.rack_model = NS(gripper_printer_head=None, gripper_updated=FakeSignal())
    model.experiment_loaded = FakeSignal()
    return model


@pytest.fixture
def dense_widget(qapp, dense_model):
    main = NS(color_dict={name: "#333333" for name in ("darker_gray", "dark_blue", "dark_red")})
    controller = NS(array_state_changed=FakeSignal(),
                    get_loaded_array_control_state=lambda: {"state": "no_head"})
    widget = WellPlateWidget(main, dense_model, controller)
    yield widget
    widget.close()
    widget.deleteLater()


@pytest.mark.parametrize("event", ["load", "selection", "pickup_changed", "pickup_same", "all"])
def test_dense_plate_calculates_plan_once_per_refresh(dense_widget, event):
    widget = dense_widget
    model = widget.model
    calculator = model.experiment_model._execution_concentration_details
    calculator.reset_mock()
    if event == "load":
        model.experiment_loaded.emit()
    elif event == "selection":
        widget.reagent_selection.setCurrentIndex(1)
    elif event.startswith("pickup"):
        sid = "S1" if event == "pickup_changed" else "S0"
        model.rack_model.gripper_printer_head = NS(get_stock_id=lambda: sid)
        model.rack_model.gripper_updated.emit()
        assert widget.reagent_selection.currentData() == sid
    else:
        model.well_plate.well_state_changed_signal.emit("all")
    assert calculator.call_count == 1
    for row in widget.well_labels:
        for label in row:
            # 100 * 2 * 10 / (10 stocks * 2 * 10 + 100 nonprinted nL).
            assert "Final concentration: 6.6667 mM" in label.toolTip()
            assert "Target droplets: 2" in label.toolTip()


def test_single_well_update_stays_incremental(dense_widget, monkeypatch):
    widget = dense_widget
    model = widget.model
    monkeypatch.setattr(model, "get_well_stock_final_concentrations", Mock(side_effect=AssertionError("batch lookup")))
    monkeypatch.setattr(model.well_plate, "get_all_wells", Mock(side_effect=AssertionError("plate scan")))
    widget.well_labels[0][1].setToolTip("untouched")
    model.well_plate.get_well("A1").assigned_reaction.check_stock_complete = lambda _: True
    model.well_plate.well_state_changed_signal.emit("A1")
    assert "border: 1px solid white" in widget.well_labels[0][0].styleSheet()
    assert widget.well_labels[0][1].toolTip() == "untouched"


def test_empty_gripper_does_not_refresh_plate(dense_widget):
    model = dense_widget.model
    calculator = model.experiment_model._execution_concentration_details
    calculator.reset_mock()
    model.rack_model.gripper_updated.emit()
    calculator.assert_not_called()


def test_read_only_refresh_uses_display_heads_and_batched_concentrations(dense_widget, monkeypatch):
    widget = dense_widget
    model = widget.model
    monkeypatch.setattr(model, "is_read_only_experiment_view_active", lambda: True)
    monkeypatch.setattr(model, "get_read_only_experiment_display_heads", lambda: (
        NS(get_stock_id=lambda: "S0", get_color=lambda: "#224466"),
    ))
    monkeypatch.setattr(model.printer_head_manager, "get_printer_head_by_id",
                        Mock(side_effect=AssertionError("physical rack display")))
    calculator = model.experiment_model._execution_concentration_details
    calculator.reset_mock()
    widget.update_well_colors()
    calculator.assert_called_once()
    assert "#ff224466" in widget.well_labels[0][0].styleSheet()
    assert "Final concentration: 6.6667 mM" in widget.well_labels[0][0].toolTip()


def test_refresh_uses_new_plan_and_handles_unassigned_wells(dense_widget):
    widget = dense_widget
    model = widget.model
    plan = model.experiment_model.get_execution_plan_snapshot()
    revised = NS(**vars(plan))
    revised.stocks = [NS(**{**vars(s), "effective_volume_nL": 20.0}) for s in plan.stocks]
    model.experiment_model._execution_plan_snapshot = revised
    model.well_plate.get_well("A2").assigned_reaction = None
    widget.update_well_colors()
    assert "Final concentration: 8.0000 mM" in widget.well_labels[0][0].toolTip()
    assert "No reaction assigned" in widget.well_labels[0][1].toolTip()
    model.experiment_model._execution_plan_snapshot = plan
    widget.update_well_colors()
    assert "Final concentration: 6.6667 mM" in widget.well_labels[0][0].toolTip()


def test_failed_snapshot_preserves_display_and_updates(dense_widget):
    widget = dense_widget
    before = widget.well_labels[0][0].toolTip()
    widget.model.experiment_model._execution_concentration_details.side_effect = RuntimeError("invalid plan")
    with pytest.raises(RuntimeError, match="invalid plan"):
        widget.update_well_colors()
    assert widget.updatesEnabled()
    assert widget.well_labels[0][0].toolTip() == before


def test_batch_handles_missing_stock_well_and_undefined_volume(dense_model):
    model = dense_model
    assert model.get_well_stock_final_concentrations("absent", ["A1", "missing"]) == {
        "A1": 0.0, "missing": None,
    }
    plan = model.experiment_model.get_execution_plan_snapshot()
    plan.volume_basis.final_reaction_volume_nL = 400.0
    plan.wells[0].dispenses = []
    assert model.get_well_stock_final_concentrations("S0", ["A1"]) == {"A1": None}
    model.experiment_model._execution_concentration_details.reset_mock()
    assert model.get_well_stock_final_concentrations("S0", iter(())) == {}
    model.experiment_model._execution_concentration_details.assert_not_called()


@pytest.mark.parametrize("source", [None, "legacy_reconstruction"])
def test_batch_preserves_legacy_lookup(experiment_model_factory, source):
    model = experiment_model_factory()
    em = model.experiment_model
    em._execution_plan_snapshot = None if source is None else object()
    em._execution_plan_source = source
    em.metadata.update(final_reaction_volume_nL=500.0, fill_droplet_volume_nL=10.0)
    em._stock_rows_cache = [dict(factor_name="R", stock_concentration=100.0,
                                units="mM", droplet_volume_nL=20.0)]
    reagent = NS(get_target_droplets=lambda: 2,
                 stock_solution=NS(get_stock_concentration=lambda: 100.0))
    reaction = NS(get_all_reagents=lambda: {"R_100.00_mM": reagent})
    model.well_plate = NS(get_well={
        "A1": NS(get_assigned_reaction=lambda: reaction),
        "A2": NS(get_assigned_reaction=lambda: None),
    }.get)
    assert model.get_well_stock_final_concentrations("R_100.00_mM", ["A1", "A2", "missing"]) == {
        "A1": 8.0, "A2": None, "missing": None,
    }
    assert model.get_well_stock_final_concentrations("absent", ["A1"]) == {"A1": 0.0}


def test_batch_matches_calibrated_execution_after_revision(experiment_model_factory):
    from test_initial_execution_plan_integration import _configure_calibratable_two_stock_execution
    from test_execution_two_stock_workflow import _apply

    model = experiment_model_factory()
    em = _configure_calibratable_two_stock_execution(model)
    before = em.get_execution_plan_snapshot()
    stock = next(s for s in before.stocks if s.factor_name == "Signal")
    old = model.get_well_stock_final_concentrations(stock.stock_id, [w.well_id for w in before.wells])
    _apply(em, stock, 12.0)
    after = em.get_execution_plan_snapshot()
    assert after != before
    for selected in after.stocks:
        actual = model.get_well_stock_final_concentrations(selected.stock_id, (w.well_id for w in after.wells))
        assert actual == {w.well_id: model.get_well_stock_final_concentration(w.well_id, selected.stock_id)
                          for w in after.wells}
    # Earlier callers retain their snapshot; later refreshes read the new plan.
    previous_details = ExperimentModel._execution_concentration_details(em, before)
    assert old == {w.well_id: previous_details[w.well_id]["stock_contributions"].get(stock.stock_id, 0.0)
                  for w in before.wells}
