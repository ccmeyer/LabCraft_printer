import copy
import json
from pathlib import Path

import pytest

from FixedStock import parse_fixed_stock_text
from Model import AdditionalConditionSpec, ExperimentModel
from tests.test_experiment_forced_stock_preview import _make_model, _two_stock_applied_calibration


def make_pair(*, targets=(0.1, 5.15), choice=False, starting=0.0, budget=1000.0, pair=(5.0, 500.0)):
    model = _make_model(target_volume_nl=budget, final_volume_nl=1000.0)
    kwargs = dict(targets=list(targets), units="mM", droplet_nL=10.0,
                  starting_conc=starting, forced_stock_concs=pair)
    if choice:
        model.add_choice_option("Group", "R", **kwargs)
    else:
        model.add_additive("R", **kwargs)
    return model, ("Group", "R") if choice else ("R", None)


@pytest.mark.parametrize("text", ["5,", ",500", "5,,500", "5,10,500", "5,5", "5.001,5.002",
                                  "nan", "inf", "5,nan", "5,inf", "0,500", "-5,500", "abc"])
def test_fixed_pair_rejects_invalid_text(text):
    with pytest.raises(ValueError):
        parse_fixed_stock_text(text)


@pytest.mark.parametrize("text,expected", [("", (None, None)), ("5", (5.0, None)),
                                         (" 5, 5e2 ", (None, (500.0, 5.0))),
                                         ("500,5", (None, (500.0, 5.0)))])
def test_fixed_stock_parsing(text, expected):
    assert parse_fixed_stock_text(text) == expected


@pytest.mark.parametrize("pair", [(5.0,), (5.0, 10.0, 500.0), (5.0, 5.0),
                                 (5.001, 5.002), (float("inf"), 5.0), (0.0, 5.0)])
def test_fixed_pair_model_rejects_invalid_constraints(pair):
    with pytest.raises(ValueError):
        make_pair(pair=pair)


def test_fixed_pair_model_rejects_conflicting_scalar_constraint():
    model = _make_model()
    with pytest.raises(ValueError, match="either one fixed stock or a fixed pair"):
        model.add_additive("R", [0.1], "mM", 10.0,
                           forced_stock_conc=5.0, forced_stock_concs=(5.0, 500.0))
    assert not model.factors


@pytest.mark.parametrize("choice", [False, True])
@pytest.mark.parametrize("allow_two", [False, True])
def test_fixed_pair_uses_both_stocks_and_existing_nearest_solver(choice, allow_two):
    model, key = make_pair(targets=(0.0, 0.123, 5.15), choice=choice)
    result = model.optimize_stock_solutions(allow_two=allow_two)
    assert result["best"]
    model.validate_optimization_allocation(result)
    plan = model.plans_per_option[key]
    assert plan["n_stocks"] == 2
    assert [stock["stock_concentration"] for stock in plan["stocks"]] == [500.0, 5.0]
    rows = model.get_target_preview_map()[key]
    by_target = {row["requested_final"]: row for row in rows}
    assert by_target[0.0]["droplets"] == (0, 0)
    assert by_target[0.123]["achieved_final"] == pytest.approx(0.1)
    assert by_target[5.15]["droplets"] == (1, 3)
    assert all(row["plan_mode"] == "fixed" for row in rows)
    # Compare each mapping with every feasible count pair, independent of the solver.
    for row in rows:
        oracle = [(abs(5.0 * a + 0.05 * b - row["requested_final"]), a + b)
                  for a in range(101) for b in range(101 - a)]
        best_error = min(error for error, count in oracle)
        best_count = min(count for error, count in oracle if abs(error - best_error) < 1e-12)
        assert row["abs_error"] == pytest.approx(best_error)
        assert sum(row["droplets"]) == best_count
    model.generate_experiment()
    generated = list(model.iter_reaction_stock_droplets())
    mixed = next(items for items in generated if len(items) == 2)
    assert [(item[1], item[3]) for item in mixed] == [(500.0, 1), (5.0, 3)]


@pytest.mark.parametrize("choice", [False, True])
@pytest.mark.parametrize("targets", [(0.1, 0.2), (5.0, 10.0), (0.0,)])
def test_fixed_pair_preserves_unused_legs_after_recalculate_and_json_reload(choice, targets):
    model, key = make_pair(targets=targets, choice=choice)
    for attempt in range(3):
        result = model.optimize_stock_solutions(allow_two=False)
        assert result["best"]
        model.validate_optimization_allocation(result)
        model.generate_experiment()
        assert model.plans_per_option[key]["n_stocks"] == 2
        stocks = [row for row in model.get_stock_table_rows(include_fill=False)]
        assert len(stocks) == 2
        assert any(row["total_droplets"] == 0 for row in stocks)
        assert model.factors[0].options[0].forced_stock_concs == (500.0, 5.0)
        document = json.loads(json.dumps(model.to_dict()))
        model = ExperimentModel()
        model.from_dict(document)


def test_fixed_pair_handles_starting_concentration_and_additional_conditions():
    model, key = make_pair(targets=(0.5, 0.6), starting=0.5)
    model.set_additional_conditions([
        AdditionalConditionSpec("extra", {key: 5.65})
    ])
    assert model.optimize_stock_solutions(allow_two=False)["best"]
    rows = {row["requested_final"]: row for row in model.get_target_preview_map()[key]}
    assert rows[0.5]["droplets"] == (0, 0)
    assert rows[5.65]["droplets"] == (1, 3)
    assert rows[5.65]["achieved_final"] == pytest.approx(5.65)
    model.generate_experiment()
    assert len(list(model.iter_reaction_stock_droplets())) == 3


@pytest.mark.parametrize("choice", [False, True])
@pytest.mark.parametrize("allow_two", [False, True])
@pytest.mark.parametrize("grouping", [False, True])
def test_fixed_pair_survives_resolution_search_with_other_reagents(choice, allow_two, grouping):
    model, key = make_pair(targets=(0.101, 0.102), choice=choice)
    model.set_metadata(allow_avoidable_target_grouping=grouping)
    model.add_additive("Other", [0.2, 0.4], "mM", 10.0)
    result = model.optimize_stock_solutions(allow_two=allow_two)
    assert result["best"]
    model.validate_optimization_allocation(result)
    assert model.plans_per_option[key]["n_stocks"] == 2
    assert [stock["stock_concentration"] for stock in model.plans_per_option[key]["stocks"]] == [500.0, 5.0]


def test_fixed_pair_accepts_stream_ejection_and_printed_volume_tolerance():
    model, key = make_pair(targets=(25.75,), budget=190.0)
    model.set_metadata(printed_volume_tolerance_nL=10.0)
    option = model.factors[0].options[0]
    option.droplet_nL = 50.0
    option.printing_mode = "stream"
    result = model.optimize_stock_solutions(allow_two=False)
    assert result["best"]
    model.validate_optimization_allocation(result)
    assert model.get_target_preview_map()[key][0]["droplets"] == (1, 3)
    assert model.get_worst_nonfill_volume_nL() == pytest.approx(200.0)


def test_fixed_pair_uses_nearest_reachable_counts_within_tight_budget():
    model, key = make_pair(pair=(30.0, 20.0), targets=(0.4,), budget=10.0)
    result = model.optimize_stock_solutions(allow_two=False)
    assert result["best"]
    row = model.get_target_preview_map()[key][0]
    assert row["droplets"] == (1, 0)
    assert row["achieved_final"] == pytest.approx(0.3)
    assert row["reachable"]
    model.validate_optimization_allocation(result)


def test_uploaded_design_can_use_fixed_pair_with_automatic_search_disabled():
    import pandas as pd
    model = _make_model(target_volume_nl=1000.0, final_volume_nl=1000.0)
    model.set_uploaded_design_from_dataframe(
        pd.DataFrame({"Well ID": ["A1", "A2"], "R mM": [0.1, 5.15]}),
        units_default="mM", droplet_nL_default=10.0,
    )
    model.factors[0].options[0].forced_stock_concs = (500.0, 5.0)
    result = model.optimize_stock_solutions(allow_two=False)
    assert result["best"]
    model.validate_optimization_allocation(result)
    model.generate_experiment()
    assert model.plans_per_option[("R", None)]["n_stocks"] == 2
    assert len(list(model.iter_reaction_stock_droplets())) == 2


def test_fixed_pair_reuse_requires_exact_pair_and_fingerprint():
    model, key = make_pair()
    result = model.optimize_stock_solutions(allow_two=False)
    payload = model.export_stock_allocation_reuse_payload(result)
    assert model.install_stock_allocation_reuse_payload(payload)["reused"]
    before = copy.deepcopy(model.plans_per_option)
    option = model.factors[0].options[0]
    fingerprint = model.stock_allocation_input_fingerprint()
    option.forced_stock_concs = (400.0, 5.0)
    assert model.stock_allocation_input_fingerprint() != fingerprint
    assert not model.install_stock_allocation_reuse_payload(payload)["reused"]
    # Even a payload claiming the new inputs must pass the exact-stock validator.
    payload["input_fingerprint"] = model.stock_allocation_input_fingerprint()
    reused = model.install_stock_allocation_reuse_payload(payload)
    assert not reused["reused"]
    assert "fixed stock" in reused["detail"]
    assert model.plans_per_option == before


@pytest.mark.parametrize("choice", [False, True])
@pytest.mark.parametrize("failure", ["max", "zero", "volume", "combined_volume"])
def test_fixed_pair_rejection_retains_last_valid_outputs(choice, failure):
    model, key = make_pair(choice=choice)
    assert model.optimize_stock_solutions(allow_two=False)["best"]
    before = copy.deepcopy(model.plans_per_option)
    option = model.factors[0].options[0]
    if failure == "max":
        option.max_stock_conc = 100.0
    elif failure == "zero":
        option.targets = [0.001]
    elif failure == "volume":
        model.set_metadata(target_reaction_volume_nL=10.0)
    else:
        model.set_metadata(target_reaction_volume_nL=40.0)
        model.add_additive("Other", [1.0], "mM", 10.0, forced_stock_conc=100.0)
    result = model.optimize_stock_solutions(allow_two=False)
    assert not result["best"]
    assert model.plans_per_option == before
    if failure != "combined_volume":
        assert result["issues_by_key"][key][0]["field"] == "fixed_stock"


def test_fixed_pair_calibration_preserves_concentrations_and_reuses_on_reload():
    model, key = make_pair(targets=(0.1, 5.15))
    assert model.optimize_stock_solutions(allow_two=False)["best"]
    model.generate_experiment()
    stock_id = model._calibration_plan_with_stock_ids(key)["stocks"][1]["stock_id"]
    calibration = _two_stock_applied_calibration(stock_id)
    model.apply_droplet_volume_for_option("R", None, 12.0, write_keys_if_assigned=False,
                                         applied_calibration=calibration, printing_mode="droplet")
    assert model.factors[0].options[0].forced_stock_concs == (500.0, 5.0)
    document = json.loads(json.dumps(model.to_dict()))
    restored = ExperimentModel()
    restored.from_dict(document)
    assert restored.optimize_stock_solutions(allow_two=False)["best"]
    assert restored.plans_per_option[key] == model.plans_per_option[key]


def test_legacy_progress_override_cannot_replace_fixed_pair_with_used_leg(monkeypatch):
    model, key = make_pair(targets=(0.1,))
    assert model.optimize_stock_solutions(allow_two=False)["best"]
    monkeypatch.setattr(model, "return_progress_data", lambda: {
        "A1": {"reagents": {"R_5.00_mM": {"added_droplets": 1}}}
    })
    result = model._apply_progress_stock_concentration_overrides_for_resume()
    assert not result["applied"]
    assert model.factors[0].options[0].forced_stock_concs == (500.0, 5.0)
    assert model.factors[0].options[0].forced_stock_conc is None


@pytest.mark.parametrize("text", ["5,", "5,500,1000", "5,5", "5.001,5.002", "5,inf", "nan", "inf"])
def test_fixed_pair_ui_rejects_invalid_input_and_retains_results(qapp, text):
    from tests.test_experiment_design_stock_input_validation import _build_dialog
    dialog, fixed, _ = _build_dialog(fixed_text=text)
    ok, result = dialog._run_design_optimization_flow()
    assert not ok
    assert dialog.model.optimize_calls == 0
    assert "last valid stock solutions" in dialog.stock_table_status_lbl.text()
    dialog.close()


def test_fixed_pair_ui_builds_reloads_and_duplicates_pair(qapp):
    from tests.test_experiment_design_reagent_headtype_integration import _build_real_dialog
    model, key = make_pair()
    dialog = _build_real_dialog(model)
    dialog.auto_update_chk.setChecked(False)
    try:
        edit = dialog._reagent_cell_widget(0, dialog.COL_SET_STOCK)
        assert parse_fixed_stock_text(edit.text()) == (None, (500.0, 5.0))
        assert not dialog.allow_two_chk.isChecked()
        edit.setText("5, 500")
        assert not dialog._collect_raw_stock_input_issues()
        dialog._rebuild_model_from_table()
        assert dialog.model.factors[0].options[0].forced_stock_concs == (500.0, 5.0)
        result = dialog.model.optimize_stock_solutions(allow_two=False)
        assert result["best"]
        dialog.model.validate_optimization_allocation(result)
        rows = dialog.model.get_target_preview_map()[key]
        assert "2 fixed stocks" in dialog._build_target_preview_tooltip(rows)
        dialog._duplicate_reagent_row(0)
        assert parse_fixed_stock_text(dialog._reagent_cell_widget(1, dialog.COL_SET_STOCK).text()) == (None, (500.0, 5.0))
        edit.setText("5,")
        dialog._duplicate_reagent_row(0)
        assert dialog._reagent_cell_widget(1, dialog.COL_SET_STOCK).text() == "5,"
    finally:
        dialog.close()


def test_fixed_pair_saved_design_and_editable_copy_keep_unused_stock(tmp_path):
    model, key = make_pair(targets=(0.1, 0.2))
    assert model.optimize_stock_solutions(allow_two=False)["best"]
    model.generate_experiment()
    source = tmp_path / "source"
    source.mkdir()
    model.experiment_dir_path = str(source)
    model.update_all_paths()
    model.save_experiment()
    design_path = Path(model.experiment_file_path)
    before = design_path.read_bytes()
    restored = ExperimentModel()
    restored.load_experiment(str(design_path), str(source))
    assert restored.factors[0].options[0].forced_stock_concs == (500.0, 5.0)
    assert restored.plans_per_option[key]["n_stocks"] == 2
    assert restored.duplicate_design_from(str(design_path), "Pair copy", str(tmp_path / "copy"))
    assert restored.plans_per_option[key]["n_stocks"] == 2
    assert restored.factors[0].options[0].forced_stock_concs == (500.0, 5.0)
    assert design_path.read_bytes() == before


@pytest.mark.parametrize("targets", [(0.1, 5.15), (0.1, 0.2)])
def test_fixed_pair_worker_preserves_pair_and_rejects_stale_publication(qapp, targets):
    from OptimizationJobs import OptimizationJobManager, OptimizationRequest
    from tests.test_optimization_jobs import wait_for
    model, key = make_pair(targets=targets)
    service = OptimizationJobManager()
    outcomes = []
    fingerprint = model.optimization_inputs_fingerprint()
    try:
        request = OptimizationRequest(model.capture_optimization_inputs(), options={"allow_two": False})
        assert service.submit(model, request, outcomes.append)
        wait_for(qapp, lambda: outcomes)
        outcome = outcomes[0]
        assert outcome.status == "succeeded", outcome.error
        assert not model.plans_per_option
        model.install_optimization_outputs(outcome.computed, fingerprint)
        assert model.plans_per_option[key]["n_stocks"] == 2
        assert model.factors[0].options[0].forced_stock_concs == (500.0, 5.0)
        model.factors[0].options[0].forced_stock_concs = (400.0, 5.0)
        with pytest.raises(ValueError, match="changed"):
            model.install_optimization_outputs(outcome.computed, fingerprint)
    finally:
        stopped = []
        service.shutdown(lambda: stopped.append(True))
        wait_for(qapp, lambda: stopped)


def test_fixed_pair_cancellation_interrupts_solver_without_publishing(monkeypatch):
    from OptimizationJobs import OptimizationCancelled
    model, key = make_pair()
    assert model.optimize_stock_solutions(allow_two=False)["best"]
    before = copy.deepcopy(model.plans_per_option)
    original = model._nearest_two_stock

    def cancel_in_solver(*args, **kwargs):
        def cancel():
            raise OptimizationCancelled()
        kwargs["deadline_reached"] = cancel
        return original(*args, **kwargs)

    monkeypatch.setattr(model, "_nearest_two_stock", cancel_in_solver)
    with pytest.raises(OptimizationCancelled):
        model.optimize_stock_solutions(allow_two=False)
    assert model.plans_per_option == before
