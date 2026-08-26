import itertools
from pathlib import Path

import pandas as pd
import pytest

from Model import CURRENT_PROFILE, ExperimentModel


BNEXT_DIR = (
    Path(__file__).resolve().parents[1]
    / "FreeRTOS-interface"
    / "Experiments"
    / "bnext_260824_csvs"
)


def _bnext_model(*, budget_nl=2000.0, allow_grouping=False, relax_stock_bounds=False):
    design = pd.read_csv(BNEXT_DIR / "260824_labcraft_input.csv")
    stock_rows = pd.read_csv(BNEXT_DIR / "260824_labcraft_reagents.csv")
    stock_by_name = {
        str(row.reagent).strip().casefold(): float(row.stock_conc)
        for row in stock_rows.itertuples(index=False)
    }

    model = ExperimentModel(prof=CURRENT_PROFILE)
    model.set_metadata(
        target_reaction_volume_nL=float(budget_nl),
        printed_volume_tolerance_nL=0.0 if budget_nl < 2000.0 else 50.0,
        final_reaction_volume_nL=2000.0,
        allow_two_stock_solutions=False,
        allow_avoidable_target_grouping=bool(allow_grouping),
    )
    model.set_uploaded_design_from_dataframe(
        design,
        units_default="",
        droplet_nL_default=9.0,
        starting_conc_default=0.0,
        source_path="260824_labcraft_input.csv",
    )
    for factor in model.factors:
        if not factor.options:
            continue
        reagent_name = factor.name.strip().strip("[]").casefold()
        factor.options[0].max_stock_conc = (
            None if relax_stock_bounds else stock_by_name[reagent_name]
        )
    return model, design


def _public_result_rank(model, result):
    previews = model.get_target_preview_map()
    losses = [
        model._summarize_target_resolution_rows(rows)["lost_level_count"]
        for rows in previews.values()
    ]
    errors = [
        abs(float(row.get("abs_error", 0.0) or 0.0))
        for rows in previews.values()
        for row in rows
    ]
    return (
        int(sum(losses)),
        int(max(losses, default=0)),
        int(result["stocks"] - len(previews)),
        float(max(errors, default=0.0)),
        float(sum(errors) / len(errors)) if errors else 0.0,
        float(result["sum_conc"]),
        float(result["worst_nonfill_nL"]),
    )


def _large_import_model():
    row_count = 384
    reagent_count = 12
    base_design = pd.read_csv(BNEXT_DIR / "260824_labcraft_input.csv").drop(
        columns=["well"]
    )
    design = pd.concat([base_design] * 5, ignore_index=True).iloc[:row_count].copy()
    for reagent_index in range(4):
        design.loc[:, f"[Extra{reagent_index}] mM"] = 1.0
    model = ExperimentModel(prof=CURRENT_PROFILE)
    model.set_metadata(
        target_reaction_volume_nL=650.0,
        printed_volume_tolerance_nL=0.0,
        final_reaction_volume_nL=2000.0,
        allow_two_stock_solutions=False,
        allow_avoidable_target_grouping=False,
    )
    model.set_uploaded_design_from_dataframe(
        design,
        units_default="mM",
        droplet_nL_default=9.0,
        starting_conc_default=0.0,
        source_path="synthetic_384.csv",
    )
    for factor in model.factors:
        factor.options[0].max_stock_conc = None
    return model, row_count, reagent_count


def test_bnext_import_zero_loss_uses_structural_early_exit():
    resolution_model, design = _bnext_model()
    resolution_result = resolution_model.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    grouping_model, _design = _bnext_model(allow_grouping=True)
    grouping_result = grouping_model.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert len(design) == 88
    assert len(resolution_model.factors) == 8
    assert sum(
        len(set(option.targets))
        for factor in resolution_model.factors
        for option in factor.options
    ) == 45
    assert resolution_result["best"] is True
    assert resolution_result["distinct_level_loss"] == 0
    assert resolution_result["stock_allocation_states_evaluated"] == 0
    assert resolution_result["stock_allocation_elapsed_ms"] == pytest.approx(0.0)
    assert resolution_result["stock_allocation_candidates_generated"] == 0
    assert resolution_result["stock_allocation_limit_reasons"] == []
    assert resolution_result["stock_allocation_stop_reason"] == "seed_zero_loss"
    assert resolution_result["stock_allocation_improved_seed"] is False
    assert resolution_result["stock_allocation_time_to_best_ms"] is None
    assert resolution_result["optimizer_seed_rank"] == resolution_result[
        "optimizer_selected_rank"
    ]
    assert _public_result_rank(resolution_model, resolution_result) == pytest.approx(
        _public_result_rank(grouping_model, grouping_result)
    )


@pytest.mark.parametrize("budget_nl", [300.0, 450.0, 600.0])
def test_adversarial_bnext_resolution_work_is_wall_clock_bounded(budget_nl):
    seed_model, _design = _bnext_model(
        budget_nl=budget_nl,
        allow_grouping=True,
        relax_stock_bounds=True,
    )
    seed_result = seed_model.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    resolution_model, _design = _bnext_model(
        budget_nl=budget_nl,
        allow_grouping=False,
        relax_stock_bounds=True,
    )
    resolution_result = resolution_model.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert seed_result["best"] is True
    assert resolution_result["best"] is True
    assert resolution_result["stock_allocation_elapsed_ms"] <= 100.0
    assert _public_result_rank(
        resolution_model, resolution_result
    ) <= _public_result_rank(seed_model, seed_result)
    if resolution_result["stock_allocation_search_limited"]:
        assert "time_budget" in resolution_result["stock_allocation_limit_reasons"]
        assert resolution_result["stock_allocation_stop_reason"] == "time_budget"
    assert resolution_result["stock_allocation_time_budget_ms"] == pytest.approx(75.0)


def test_resolution_selection_matches_small_brute_force_oracle():
    model = ExperimentModel(prof=CURRENT_PROFILE)
    model.set_metadata(
        target_reaction_volume_nL=320.0,
        printed_volume_tolerance_nL=0.0,
        final_reaction_volume_nL=5000.0,
        allow_two_stock_solutions=False,
        allow_avoidable_target_grouping=False,
    )
    model.add_additive("R", [0.5, 1.0, 5.0, 20.0], "mM", 10.0)
    model.add_additive("Other", [100.0], "mM", 10.0)

    candidates_by_key = {}
    for factor in model.factors:
        option = factor.options[0]
        candidates_by_key[(factor.name, None)] = model._enumerate_single_stock_candidates(
            option.targets,
            option.droplet_nL,
            option.units,
            final_volume_nL=5000.0,
            max_refine=60,
            max_stock_conc=option.max_stock_conc,
        )

    oracle_rank = None
    for plans in itertools.product(*candidates_by_key.values()):
        if sum(float(plan.max_volume_nL) for plan in plans) > 320.0 + 1e-6:
            continue
        scores = []
        for (key, plan) in zip(candidates_by_key, plans):
            option = model._get_option_for_key(key)
            score, _rows, _summary = model._evaluate_plan_resolution(
                option,
                plan,
                final_volume_nL=5000.0,
                targets_final=option.targets,
            )
            scores.append(score)
        target_count = sum(score.target_count for score in scores)
        error_sum = sum(score.error_sum for score in scores)
        rank = (
            sum(score.lost_levels for score in scores),
            max(score.lost_levels for score in scores),
            sum(max(0, score.n_stocks - 1) for score in scores),
            max(score.worst_abs_error for score in scores),
            error_sum / target_count,
            sum(score.concentration_burden for score in scores),
            sum(float(plan.max_volume_nL) for plan in plans),
        )
        if oracle_rank is None or rank < oracle_rank:
            oracle_rank = rank

    result = model.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert result["best"] is True
    selected_rank = _public_result_rank(model, result)
    assert selected_rank[:3] == oracle_rank[:3]
    assert selected_rank[3:] == pytest.approx(oracle_rank[3:])
    assert result["optimizer_seed_rank"]["total_distinct_level_loss"] == 1
    assert result["optimizer_selected_rank"]["total_distinct_level_loss"] == 0
    assert result["stock_allocation_improved_seed"] is True
    assert result["stock_allocation_time_to_best_ms"] is not None


def test_384_row_increased_reagent_import_keeps_resolution_phase_bounded():
    model, row_count, reagent_count = _large_import_model()

    result = model.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=False,
    )

    assert len(model._uploaded_reactions) == row_count
    assert len(model.factors) == reagent_count
    assert result["best"] is True
    assert result["stock_allocation_elapsed_ms"] <= 100.0
    assert result["stock_allocation_candidates_generated"] > 0
    assert result["stock_allocation_candidates_retained"] <= result[
        "stock_allocation_candidates_generated"
    ]
    assert result["distinct_level_loss"] == 0
    assert result["stock_allocation_improved_seed"] is True
    assert result["stock_allocation_time_to_best_ms"] < 75.0
    assert result["stock_allocation_stop_reason"] == "zero_loss_polish_complete"
    assert result["stock_allocation_search_limited"] is False


def test_zero_loss_polish_uses_only_ten_ms_of_remaining_fake_clock(monkeypatch):
    model, _row_count, _reagent_count = _large_import_model()
    monkeypatch.setattr(model, "MAX_STOCK_ALLOCATION_SECONDS", 1.0)
    calls = 0

    def fake_clock():
        nonlocal calls
        calls += 1
        return calls * 0.001

    monkeypatch.setattr(model, "_stock_optimizer_monotonic", fake_clock)

    result = model.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=False,
    )

    assert result["best"] is True
    assert result["distinct_level_loss"] == 0
    assert result["stock_allocation_stop_reason"] == "zero_loss_polish_complete"
    assert result["stock_allocation_limit_reasons"] == []
    assert result["stock_allocation_time_to_best_ms"] is not None
    assert (
        result["stock_allocation_elapsed_ms"]
        - result["stock_allocation_time_to_best_ms"]
    ) <= 20.0
