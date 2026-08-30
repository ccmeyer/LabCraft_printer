import itertools

import pandas as pd
import pytest

from Model import CURRENT_PROFILE, ExperimentModel


_BENCHMARK_LEVEL_COUNTS = (6, 6, 6, 6, 6, 5, 5, 5)


def _benchmark_import_design():
    row_count = 88
    data = {"well": [f"W{row_index + 1}" for row_index in range(row_count)]}
    next_nonzero_row = 0
    for reagent_index, level_count in enumerate(_BENCHMARK_LEVEL_COUNTS):
        levels = (0.0, 0.5, 1.0, 5.0, 20.0, 21.0)[:level_count]
        values = [0.0] * row_count
        for level in levels[1:]:
            values[next_nonzero_row] = level
            next_nonzero_row += 1
        data[f"[Benchmark{reagent_index + 1}] mM"] = values
    return pd.DataFrame(data)


def _benchmark_stock_rows():
    return pd.DataFrame(
        {
            "reagent": [
                f"Benchmark{index + 1}"
                for index in range(len(_BENCHMARK_LEVEL_COUNTS))
            ],
            "stock_conc": [5000.0] * len(_BENCHMARK_LEVEL_COUNTS),
        }
    )


def _bnext_model(*, budget_nl=2000.0, allow_grouping=False, relax_stock_bounds=False):
    design = _benchmark_import_design()
    stock_rows = _benchmark_stock_rows()
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
        source_path="synthetic_optimizer_workload.csv",
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
    adversarial_levels = (0.2, 0.5, 1.0, 5.0, 10.0)
    reagent_names = [
        *[f"Benchmark{index}" for index in range(1, 9)],
        *[f"Extra{index}" for index in range(4)],
    ]
    data = {}
    next_nonzero_row = 0
    for reagent_index, reagent_name in enumerate(reagent_names):
        values = [0.0] * row_count
        if reagent_index < 4:
            for level in adversarial_levels:
                values[next_nonzero_row] = level
                next_nonzero_row += 1
        data[f"[{reagent_name}] mM"] = values
    design = pd.DataFrame(data)
    model = ExperimentModel(prof=CURRENT_PROFILE)
    model.set_metadata(
        target_reaction_volume_nL=270.0,
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

def test_adversarial_bnext_resolution_work_is_deterministically_bounded(budget_nl):
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

    repeated_model, _design = _bnext_model(
        budget_nl=budget_nl,
        allow_grouping=False,
        relax_stock_bounds=True,
    )
    repeated_result = repeated_model.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert seed_result["best"] is True
    assert resolution_result["best"] is True
    assert repeated_result["best"] is True
    assert resolution_result["stock_allocation_elapsed_ms"] <= 2000.0
    assert resolution_result["stock_allocation_work_units_evaluated"] <= (
        resolution_result["stock_allocation_work_limit"]
    )
    assert sum(
        resolution_result["stock_allocation_work_units_by_kind"].values()
    ) == resolution_result["stock_allocation_work_units_evaluated"]
    assert "time_budget" not in resolution_result["stock_allocation_limit_reasons"]
    assert resolution_result["stock_allocation_stop_reason"] in {
        "work_cap",
        "state_cap",
        "work_and_state_cap",
        "zero_loss_polish_complete",
        "search_exhausted",
        "seed_zero_loss",
    }
    assert resolution_result["stock_allocation_time_budget_exceeded"] is (
        resolution_result["stock_allocation_elapsed_ms"] > 75.0 + 1e-9
    )
    assert _public_result_rank(
        resolution_model, resolution_result
    ) <= _public_result_rank(seed_model, seed_result)

    stable_keys = (
        "optimizer_seed_rank",
        "optimizer_selected_rank",
        "stock_allocation_stop_reason",
        "stock_allocation_limit_reasons",
        "stock_allocation_work_units_evaluated",
        "stock_allocation_work_units_by_kind",
        "stock_allocation_zero_loss_polish_work_used",
        "stock_allocation_states_evaluated",
        "stock_allocation_candidates_generated",
        "stock_allocation_candidates_retained",
        "stock_allocation_candidates_pruned",
        "stock_allocation_candidates_deduplicated",
        "stock_allocation_candidates_dominated",
        "stock_allocation_branches_pruned",
        "stock_allocation_loss_tiers_evaluated",
    )
    assert {
        key: resolution_result[key]
        for key in stable_keys
    } == {
        key: repeated_result[key]
        for key in stable_keys
    }
    assert resolution_model.export_stock_allocation_reuse_payload(
        resolution_result
    )["plan_fingerprint"] == repeated_model.export_stock_allocation_reuse_payload(
        repeated_result
    )["plan_fingerprint"]


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



def test_384_row_increased_reagent_import_keeps_resolution_work_bounded():
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
    assert result["stock_allocation_elapsed_ms"] <= 2000.0
    assert result["stock_allocation_work_units_evaluated"] <= result[
        "stock_allocation_work_limit"
    ]
    assert sum(result["stock_allocation_work_units_by_kind"].values()) == result[
        "stock_allocation_work_units_evaluated"
    ]
    assert result["stock_allocation_candidates_generated"] > 0
    assert result["stock_allocation_candidates_retained"] <= result[
        "stock_allocation_candidates_generated"
    ]
    assert result["distinct_level_loss"] == 0
    assert result["stock_allocation_improved_seed"] is True
    assert result["stock_allocation_time_to_best_ms"] >= 0.0
    assert result["stock_allocation_stop_reason"] in {
        "search_exhausted",
        "zero_loss_polish_complete",
    }
    assert result["stock_allocation_search_limited"] is False
    assert result["stock_allocation_time_budget_exceeded"] is (
        result["stock_allocation_elapsed_ms"] > 75.0 + 1e-9
    )




def test_zero_loss_polish_uses_exact_deterministic_work_allowance(monkeypatch):
    def run(clock):
        model = ExperimentModel(prof=CURRENT_PROFILE)
        model.set_metadata(
            target_reaction_volume_nL=240.0,
            printed_volume_tolerance_nL=0.0,
            final_reaction_volume_nL=5000.0,
            allow_two_stock_solutions=True,
            allow_avoidable_target_grouping=False,
        )
        model.add_additive("R", [0.5, 1.0, 5.0, 20.0], "mM", 10.0)
        model.factors[0].options[0].max_stock_conc = 2000.0
        monkeypatch.setattr(model, "_stock_optimizer_monotonic", clock)
        result = model.optimize_stock_solutions(
            quantum=0.1,
            max_refine=20,
            two_max_refine=20,
            allow_two=True,
        )
        return model, result

    frozen_model, frozen_result = run(lambda: 0.0)

    calls = 0

    def slow_clock():
        nonlocal calls
        calls += 1
        return calls * 1.0

    slow_model, slow_result = run(slow_clock)

    for result in (frozen_result, slow_result):
        assert result["best"] is True
        assert result["distinct_level_loss"] == 0
        assert result["stock_allocation_stop_reason"] == (
            "zero_loss_polish_complete"
        )
        assert result["stock_allocation_limit_reasons"] == []
        assert result["stock_allocation_zero_loss_polish_work_limit"] == 256
        assert result["stock_allocation_zero_loss_polish_work_used"] == 256
        assert result["stock_allocation_time_to_best_ms"] is not None

    stable_keys = (
        "optimizer_seed_rank",
        "optimizer_selected_rank",
        "stock_allocation_stop_reason",
        "stock_allocation_work_units_evaluated",
        "stock_allocation_work_units_by_kind",
        "stock_allocation_zero_loss_polish_work_used",
        "stock_allocation_states_evaluated",
        "stock_allocation_candidates_generated",
        "stock_allocation_candidates_retained",
        "stock_allocation_branches_pruned",
        "two_stock_pairs_evaluated",
        "two_stock_candidates_generated",
        "two_stock_candidates_retained",
    )
    assert {
        key: frozen_result[key]
        for key in stable_keys
    } == {
        key: slow_result[key]
        for key in stable_keys
    }
    assert frozen_model.export_stock_allocation_reuse_payload(
        frozen_result
    )["plan_fingerprint"] == slow_model.export_stock_allocation_reuse_payload(
        slow_result
    )["plan_fingerprint"]
    assert frozen_result["stock_allocation_time_budget_exceeded"] is False
    assert slow_result["stock_allocation_time_budget_exceeded"] is True
