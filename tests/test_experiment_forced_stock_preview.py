import copy
import gc
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from Model import (
    CURRENT_PROFILE,
    ExperimentModel,
    SingleStockPlan,
    StockSolutionManager,
    TwoStockPlan,
)


def _make_model(*, target_volume_nl=5000.0, final_volume_nl=5000.0, printed_volume_tolerance_nl=0.0):
    em = ExperimentModel(prof=CURRENT_PROFILE)
    em.set_metadata(
        target_reaction_volume_nL=float(target_volume_nl),
        printed_volume_tolerance_nL=float(printed_volume_tolerance_nl),
        final_reaction_volume_nL=float(final_volume_nl),
    )
    return em


def _single_plan_error_key(
    em,
    targets,
    plan,
    *,
    droplet_nl,
    final_volume_nl,
    starting_conc=0.0,
    units="mM",
):
    rows = [
        em._evaluate_single_forced_target(
            t_final=float(target),
            starting_conc=float(starting_conc),
            forced_stock_conc=float(plan.stock_concentration),
            droplet_nL=float(droplet_nl),
            final_volume_nL=float(final_volume_nl),
            units=units,
        )
        for target in targets
    ]
    worst = max(float(row["abs_error"]) for row in rows)
    mean = sum(float(row["abs_error"]) for row in rows) / len(rows)
    return (worst, mean, float(plan.stock_concentration), float(plan.max_volume_nL))


def _two_plan_error_key(
    em,
    targets,
    plan,
    *,
    droplet_nl,
    final_volume_nl,
    starting_conc=0.0,
    units="mM",
):
    rows = [
        em._evaluate_two_stock_target(
            t_final=float(target),
            starting_conc=float(starting_conc),
            stock_concentrations=tuple(float(v) for v in plan.stock_concs),
            droplet_nL=float(droplet_nl),
            final_volume_nL=float(final_volume_nl),
            units=units,
        )
        for target in targets
    ]
    worst = max(float(row["abs_error"]) for row in rows)
    mean = sum(float(row["abs_error"]) for row in rows) / len(rows)
    return (worst, mean, float(plan.conc_sum), float(plan.max_volume_nL))


def _build_single_stock_plan(
    em,
    targets,
    stock_concentration,
    *,
    droplet_nl,
    final_volume_nl,
    units="mM",
):
    delta = float(stock_concentration) * float(droplet_nl) / float(final_volume_nl)
    drops = {}
    max_volume_nl = 0.0
    for target in targets:
        row = em._evaluate_single_forced_target(
            t_final=float(target),
            starting_conc=0.0,
            forced_stock_conc=float(stock_concentration),
            droplet_nL=float(droplet_nl),
            final_volume_nL=float(final_volume_nl),
            units=units,
        )
        assert row["reachable"] is True
        droplets = int(row["droplets"])
        drops[float(target)] = droplets
        max_volume_nl = max(max_volume_nl, droplets * float(droplet_nl))
    return SingleStockPlan(
        delta_per_drop=float(delta),
        stock_concentration=float(stock_concentration),
        droplet_nL=float(droplet_nl),
        units=units,
        droplets_per_target=drops,
        max_volume_nL=float(max_volume_nl),
        lookup_quantum=1e-6,
        n_stocks=1,
    )


def _build_two_stock_plan(
    em,
    targets,
    stock_concentrations,
    *,
    droplet_nl,
    final_volume_nl,
    units="mM",
):
    c1, c2 = (float(stock_concentrations[0]), float(stock_concentrations[1]))
    d1 = c1 * float(droplet_nl) / float(final_volume_nl)
    d2 = c2 * float(droplet_nl) / float(final_volume_nl)
    drops = {}
    max_volume_nl = 0.0
    for target in targets:
        row = em._evaluate_two_stock_target(
            t_final=float(target),
            starting_conc=0.0,
            stock_concentrations=(c1, c2),
            droplet_nL=float(droplet_nl),
            final_volume_nL=float(final_volume_nl),
            units=units,
        )
        assert row["reachable"] is True
        ab = tuple(int(v) for v in row["droplets"])
        drops[float(target)] = ab
        max_volume_nl = max(max_volume_nl, (ab[0] + ab[1]) * float(droplet_nl))
    return TwoStockPlan(
        deltas=(float(d1), float(d2)),
        stock_concs=(c1, c2),
        droplet_nL=float(droplet_nl),
        units=units,
        droplets_per_target=drops,
        max_volume_nL=float(max_volume_nl),
        conc_sum=float(c1 + c2),
        n_stocks=2,
    )


def _make_resolution_reproduction_model(
    targets,
    *,
    allow_avoidable_grouping=False,
    printed_volume_nl=320.0,
    include_other=True,
    max_stock_conc=None,
):
    em = _make_model(
        target_volume_nl=printed_volume_nl,
        final_volume_nl=5000.0,
        printed_volume_tolerance_nl=0.0,
    )
    em.set_metadata(
        allow_avoidable_target_grouping=bool(allow_avoidable_grouping)
    )
    em.add_additive(
        "R",
        list(targets),
        "mM",
        10.0,
        max_stock_conc=max_stock_conc,
    )
    if include_other:
        em.add_additive("Other", [100.0], "mM", 10.0)
    return em


@pytest.mark.parametrize("targets", ([0.5, 1.0, 5.0, 20.0], [1.0, 2.0, 5.0, 20.0]))

def test_resolution_first_preserves_reported_target_levels(targets):
    em = _make_resolution_reproduction_model(targets)

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert result["best"] is True
    assert result["optimizer_strategy_used"] == "resolution_first"
    assert result["distinct_level_loss"] == 0
    assert result["collapsed_target_keys"] == []
    assert result["stock_allocation_states_evaluated"] > 0
    assert result["optimizer_seed_distinct_level_loss"] == 1
    assert result["optimizer_seed_worst_level_loss"] == 1
    assert result["optimizer_seed_rank"]["total_distinct_level_loss"] == 1
    assert result["optimizer_selected_rank"]["total_distinct_level_loss"] == 0
    assert result["stock_allocation_improved_seed"] is True
    assert result["stock_allocation_time_to_best_ms"] >= 0.0
    assert result["stock_allocation_stop_reason"] in {
        "search_exhausted",
        "zero_loss_polish_complete",
    }
    assert result["stock_allocation_work_units_evaluated"] <= result[
        "stock_allocation_work_limit"
    ]
    assert sum(result["stock_allocation_work_units_by_kind"].values()) == result[
        "stock_allocation_work_units_evaluated"
    ]
    preview = em.get_target_preview_map()[("R", None)]
    assert len({row["achieved_final"] for row in preview}) == len(targets)


@pytest.mark.parametrize("targets", ([0.5, 1.0, 5.0, 20.0], [1.0, 2.0, 5.0, 20.0]))
def test_grouping_opt_in_uses_concentration_first_seed_and_reports_collision(targets):
    em = _make_resolution_reproduction_model(
        targets,
        allow_avoidable_grouping=True,
    )

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert result["best"] is True
    assert result["optimizer_strategy_used"] == "concentration_first"
    assert result["stock_allocation_states_evaluated"] == 0
    assert result["distinct_level_loss"] == 1
    assert result["stock_allocation_improved_seed"] is False
    assert result["stock_allocation_time_to_best_ms"] is None
    assert result["stock_allocation_stop_reason"] == "grouping_allowed"
    assert result["optimizer_selected_rank"] == result["optimizer_seed_rank"]
    assert result["collapsed_target_keys"] == [("R", None)]
    issue = next(
        issue
        for issue in result["issues_by_key"][("R", None)]
        if issue["code"] == "collapsed_target_levels"
    )
    assert issue["lost_level_count"] == 1
    assert issue["collapsed_groups"][0]["requested_targets"] == list(targets[:2])
    assert issue["collapsed_groups"][0]["droplet_assignments"] == [1, 1]



def test_zero_loss_seed_skips_resolution_and_two_stock_enumeration(monkeypatch):
    em = _make_resolution_reproduction_model(
        [1.0, 2.0],
        printed_volume_nl=500.0,
        include_other=False,
    )
    original_single = em._enumerate_single_stock_candidates
    calls = {"single": 0, "two": 0}

    def count_single(*args, **kwargs):
        calls["single"] += 1
        return original_single(*args, **kwargs)

    def reject_two(*_args, **_kwargs):
        calls["two"] += 1
        raise AssertionError("two-stock candidates must remain lazy")

    monkeypatch.setattr(em, "_enumerate_single_stock_candidates", count_single)
    monkeypatch.setattr(em, "_enumerate_two_stock_candidates_with_meta", reject_two)

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=True,
    )

    assert result["best"] is True
    assert result["distinct_level_loss"] == 0
    assert result["stock_allocation_states_evaluated"] == 0
    assert result["stock_allocation_work_units_evaluated"] == 0
    assert result["stock_allocation_work_limit"] == 12000
    assert result["stock_allocation_work_units_by_kind"] == {
        "two_stock_probe": 0,
        "two_stock_pair": 0,
        "candidate_pool": 0,
        "global_search": 0,
    }
    assert result["stock_allocation_zero_loss_polish_work_limit"] == 256
    assert result["stock_allocation_zero_loss_polish_work_used"] == 0
    assert result["stock_allocation_elapsed_ms"] == pytest.approx(0.0)
    assert result["stock_allocation_limit_reasons"] == []
    assert result["stock_allocation_candidates_generated"] == 0
    assert result["stock_allocation_candidates_retained"] == 0
    assert result["stock_allocation_branches_pruned"] == 0
    assert result["stock_allocation_loss_tiers_evaluated"] == 0
    assert result["optimizer_seed_elapsed_ms"] >= 0.0
    assert result["optimizer_total_elapsed_ms"] >= result["optimizer_seed_elapsed_ms"]
    assert result["stock_allocation_stop_reason"] == "seed_zero_loss"
    assert result["stock_allocation_improved_seed"] is False
    assert result["stock_allocation_time_to_best_ms"] is None
    assert result["stock_allocation_time_budget_exceeded"] is False
    assert result["stock_allocation_time_budget_overshoot_ms"] == pytest.approx(0.0)
    assert result["stock_allocation_deadline_overshoot_ms"] == pytest.approx(0.0)
    assert calls == {"single": 1, "two": 0}



def test_two_stock_resolution_search_can_rescue_a_colliding_feasible_single_plan():
    single_model = _make_resolution_reproduction_model(
        [0.5, 1.0, 5.0, 20.0],
        printed_volume_nl=240.0,
        include_other=False,
        max_stock_conc=2000.0,
    )
    single_result = single_model.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=False,
    )
    assert single_result["best"] is True
    assert single_result["distinct_level_loss"] == 1
    assert single_model.plans_per_option[("R", None)]["n_stocks"] == 1

    two_model = _make_resolution_reproduction_model(
        [0.5, 1.0, 5.0, 20.0],
        printed_volume_nl=240.0,
        include_other=False,
        max_stock_conc=2000.0,
    )
    two_result = two_model.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=True,
    )
    assert two_result["best"] is True
    assert two_result["distinct_level_loss"] == 0
    assert two_result["stock_allocation_improved_seed"] is True
    assert two_result["stock_allocation_time_to_best_ms"] >= 0.0
    assert (
        two_result["stock_allocation_time_to_first_improvement_ms"]
        <= two_result["stock_allocation_time_to_best_ms"]
    )
    assert two_result["stock_allocation_deadline_overshoot_ms"] == pytest.approx(
        two_result["stock_allocation_time_budget_overshoot_ms"]
    )
    assert two_result["stock_allocation_stop_reason"] == "zero_loss_polish_complete"
    assert two_result["stock_allocation_zero_loss_polish_work_used"] == 256
    assert two_result["stock_allocation_work_units_evaluated"] == 314
    assert two_result["stock_allocation_work_units_by_kind"] == {
        "two_stock_probe": 56,
        "two_stock_pair": 180,
        "candidate_pool": 0,
        "global_search": 78,
    }
    assert two_result["two_stock_pairs_evaluated"] == 180
    assert two_result["two_stock_candidates_generated"] > 0
    assert two_result["two_stock_candidates_retained"] > 0
    assert two_result["two_stock_target_row_cache_reuses"] > 0
    plan = two_model.plans_per_option[("R", None)]
    assert plan["n_stocks"] == 2
    stocks_by_concentration = {
        float(stock["stock_concentration"]): stock
        for stock in plan["stocks"]
    }
    assert sorted(stocks_by_concentration) == pytest.approx([25.0, 2000.0])
    assert stocks_by_concentration[2000.0]["droplets_per_target"] == {
        0.5: 0,
        1.0: 0,
        5.0: 1,
        20.0: 5,
    }
    assert stocks_by_concentration[25.0]["droplets_per_target"] == {
        0.5: 10,
        1.0: 20,
        5.0: 20,
        20.0: 0,
    }
    assert len({
        row["achieved_final"]
        for row in two_model.get_target_preview_map()[("R", None)]
    }) == 4



def test_resolution_selection_is_independent_of_clock_speed_and_shape():
    class ScriptedClock:
        def __init__(self, increments):
            self.increments = tuple(float(value) for value in increments)
            self.index = 0
            self.value = 0.0

        def __call__(self):
            current = self.value
            increment = self.increments[min(self.index, len(self.increments) - 1)]
            self.index += 1
            self.value += increment
            return current

    def deterministic_evidence(model, result):
        payload = model.export_stock_allocation_reuse_payload(result)
        keys = (
            "optimizer_seed_rank",
            "optimizer_selected_rank",
            "stock_allocation_stop_reason",
            "stock_allocation_limit_reasons",
            "two_stock_search_limited_keys",
            "collapsed_target_keys",
            "stock_allocation_states_evaluated",
            "stock_allocation_work_units_evaluated",
            "stock_allocation_work_limit",
            "stock_allocation_work_units_by_kind",
            "stock_allocation_zero_loss_polish_work_limit",
            "stock_allocation_zero_loss_polish_work_used",
            "stock_allocation_candidates_generated",
            "stock_allocation_candidates_retained",
            "stock_allocation_candidates_pruned",
            "stock_allocation_candidates_deduplicated",
            "stock_allocation_candidates_dominated",
            "stock_allocation_branches_pruned",
            "stock_allocation_loss_tiers_evaluated",
            "two_stock_pairs_evaluated",
            "two_stock_target_evaluations",
            "two_stock_solver_iterations",
            "two_stock_candidates_generated",
            "two_stock_candidates_retained",
            "two_stock_candidates_deduplicated",
            "two_stock_target_row_cache_reuses",
        )
        return {
            "plan_fingerprint": payload["plan_fingerprint"],
            **{key: copy.deepcopy(result[key]) for key in keys},
        }

    clock_shapes = (
        (0.0,),
        (0.000001,),
        (0.100001,),
        (0.001, 0.2, 0.0001, 0.08),
    )
    for allow_two in (False, True):
        evidence = []
        time_flags = []
        for increments in clock_shapes:
            model = _make_resolution_reproduction_model(
                [0.5, 1.0, 5.0, 20.0],
                printed_volume_nl=240.0 if allow_two else 320.0,
                include_other=not allow_two,
                max_stock_conc=2000.0,
            )
            model._stock_optimizer_monotonic = ScriptedClock(increments)
            result = model.optimize_stock_solutions(
                quantum=0.1,
                max_refine=20 if allow_two else 60,
                two_max_refine=20 if allow_two else 40,
                allow_two=allow_two,
            )
            evidence.append(deterministic_evidence(model, result))
            time_flags.append(result["stock_allocation_time_budget_exceeded"])

        assert evidence[1:] == [evidence[0], evidence[0], evidence[0]]
        assert time_flags == [False, False, True, True]



@pytest.mark.parametrize(
    ("work_limit", "expected_pairs", "expected_loss", "expected_improved"),
    (
        (1, 0, 1, False),
        (58, 1, 0, True),
    ),
)
def test_two_stock_work_cap_keeps_only_validated_results(
    monkeypatch,
    work_limit,
    expected_pairs,
    expected_loss,
    expected_improved,
):
    em = _make_resolution_reproduction_model(
        [0.5, 1.0, 5.0, 20.0],
        printed_volume_nl=240.0,
        include_other=False,
        max_stock_conc=2000.0,
    )
    monkeypatch.setattr(em, "MAX_STOCK_ALLOCATION_WORK_UNITS", work_limit)

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=True,
    )

    assert result["best"] is True
    assert result["two_stock_pairs_evaluated"] == expected_pairs
    assert result["distinct_level_loss"] == expected_loss
    assert result["stock_allocation_limit_reasons"] == ["work_cap"]
    assert result["two_stock_search_limited_keys"] == [("R", None)]
    assert result["stock_allocation_stop_reason"] == "work_cap"
    assert result["stock_allocation_improved_seed"] is expected_improved
    assert result["stock_allocation_work_units_evaluated"] == work_limit
    assert sum(result["stock_allocation_work_units_by_kind"].values()) == work_limit
    if expected_improved:
        assert result["stock_allocation_time_to_best_ms"] is not None
        assert (
            result["optimizer_selected_rank"]["total_distinct_level_loss"]
            < result["optimizer_seed_rank"]["total_distinct_level_loss"]
        )
        assert em.plans_per_option[("R", None)]["n_stocks"] == 2
    else:
        assert result["stock_allocation_time_to_best_ms"] is None
        assert result["optimizer_selected_rank"] == result["optimizer_seed_rank"]
        assert em.plans_per_option[("R", None)]["n_stocks"] == 1



def test_two_stock_resolution_repeats_exact_plan_and_work_evidence_twenty_times():
    expected_evidence = None
    for _attempt in range(20):
        em = _make_resolution_reproduction_model(
            [0.5, 1.0, 5.0, 20.0],
            printed_volume_nl=240.0,
            include_other=False,
            max_stock_conc=2000.0,
        )
        result = em.optimize_stock_solutions(
            quantum=0.1,
            max_refine=20,
            two_max_refine=20,
            allow_two=True,
        )
        plan = em.plans_per_option[("R", None)]
        stocks = {
            float(stock["stock_concentration"]): copy.deepcopy(
                stock["droplets_per_target"]
            )
            for stock in plan["stocks"]
        }
        evidence = {
            "plan_fingerprint": em.export_stock_allocation_reuse_payload(result)[
                "plan_fingerprint"
            ],
            "stocks": stocks,
            "seed_rank": copy.deepcopy(result["optimizer_seed_rank"]),
            "selected_rank": copy.deepcopy(result["optimizer_selected_rank"]),
            "stop_reason": result["stock_allocation_stop_reason"],
            "limit_reasons": copy.deepcopy(
                result["stock_allocation_limit_reasons"]
            ),
            "limited_keys": copy.deepcopy(
                result["two_stock_search_limited_keys"]
            ),
            "work_units": result["stock_allocation_work_units_evaluated"],
            "work_by_kind": copy.deepcopy(
                result["stock_allocation_work_units_by_kind"]
            ),
            "polish_units": result[
                "stock_allocation_zero_loss_polish_work_used"
            ],
            "states": result["stock_allocation_states_evaluated"],
            "pairs": result["two_stock_pairs_evaluated"],
            "target_evaluations": result["two_stock_target_evaluations"],
            "solver_iterations": result["two_stock_solver_iterations"],
            "generated": result["two_stock_candidates_generated"],
            "retained": result["two_stock_candidates_retained"],
            "deduplicated": result["two_stock_candidates_deduplicated"],
        }
        if expected_evidence is None:
            expected_evidence = evidence
        else:
            assert evidence == expected_evidence

    assert expected_evidence["stocks"] == {
        2000.0: {0.5: 0, 1.0: 0, 5.0: 1, 20.0: 5},
        25.0: {0.5: 10, 1.0: 20, 5.0: 20, 20.0: 0},
    }
    assert expected_evidence["stop_reason"] == "zero_loss_polish_complete"
    assert expected_evidence["work_units"] == 314
    assert expected_evidence["polish_units"] == 256


def test_resolution_key_order_is_semantically_canonical():
    def run(additive_order):
        em = _make_model(target_volume_nl=320.0)
        definitions = {
            "R": ([0.5, 1.0, 5.0, 20.0], 10.0),
            "Other": ([100.0], 10.0),
        }
        for name in additive_order:
            targets, droplet_nl = definitions[name]
            em.add_additive(name, targets, "mM", droplet_nl)
        result = em.optimize_stock_solutions(
            quantum=0.1,
            max_refine=60,
            two_max_refine=40,
            allow_two=False,
        )
        plans = {
            key: {
                "n_stocks": int(plan["n_stocks"]),
                "stocks": sorted(
                    (
                        float(stock["stock_concentration"]),
                        float(stock["delta_per_drop"]),
                        tuple(
                            sorted(
                                (
                                    float(target),
                                    int(drops),
                                )
                                for target, drops in stock[
                                    "droplets_per_target"
                                ].items()
                            )
                        ),
                    )
                    for stock in plan["stocks"]
                ),
            }
            for key, plan in em.plans_per_option.items()
        }
        return result, plans

    forward_result, forward_plans = run(("R", "Other"))
    reverse_result, reverse_plans = run(("Other", "R"))

    assert reverse_plans == forward_plans
    assert reverse_result["optimizer_seed_rank"] == forward_result[
        "optimizer_seed_rank"
    ]
    assert reverse_result["optimizer_selected_rank"] == forward_result[
        "optimizer_selected_rank"
    ]
    assert reverse_result["stock_allocation_work_units_evaluated"] == (
        forward_result["stock_allocation_work_units_evaluated"]
    )
    assert reverse_result["stock_allocation_work_units_by_kind"] == (
        forward_result["stock_allocation_work_units_by_kind"]
    )
    assert reverse_result["stock_allocation_stop_reason"] == forward_result[
        "stock_allocation_stop_reason"
    ]


@pytest.mark.parametrize(
    ("resolution_elapsed_seconds", "expected_warning"),
    (
        (0.074999, False),
        (0.075, False),
        (0.075000001, True),
    ),
)
def test_resolution_performance_target_boundary(
    resolution_elapsed_seconds,
    expected_warning,
):
    em = _make_resolution_reproduction_model([0.5, 1.0, 5.0, 20.0])
    readings = iter(
        (
            0.0,
            0.0,
            0.0,
            resolution_elapsed_seconds,
            resolution_elapsed_seconds,
            resolution_elapsed_seconds,
        )
    )
    em._stock_optimizer_monotonic = lambda: next(readings)

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert result["best"] is True
    assert result["stock_allocation_time_budget_exceeded"] is expected_warning
    expected_overshoot = max(
        0.0,
        resolution_elapsed_seconds * 1000.0 - 75.0,
    )
    assert result["stock_allocation_time_budget_overshoot_ms"] == pytest.approx(
        expected_overshoot
    )
    assert result["stock_allocation_deadline_overshoot_ms"] == pytest.approx(
        expected_overshoot
    )
    performance_issues = [
        issue
        for issue in result["issues_by_key"].get(
            ("__stock_allocation__", None),
            [],
        )
        if issue["code"] == "stock_allocation_performance_target_exceeded"
    ]
    assert bool(performance_issues) is expected_warning
    if expected_warning:
        assert performance_issues[0]["severity"] == "warning"
        assert performance_issues[0]["performance_target_ms"] == pytest.approx(
            75.0
        )


def test_optimizer_total_timing_excludes_stock_updated_subscribers():
    em = _make_resolution_reproduction_model([0.5, 1.0, 5.0, 20.0])

    class MutableClock:
        value = 0.0

        def __call__(self):
            return self.value

    clock = MutableClock()
    em._stock_optimizer_monotonic = clock
    em.stock_updated.connect(lambda: setattr(clock, "value", 10.0))

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert clock.value == pytest.approx(10.0)
    assert result["optimizer_total_elapsed_ms"] == pytest.approx(0.0)


def test_optimizer_does_not_change_process_gc_state():
    em = _make_resolution_reproduction_model([0.5, 1.0, 5.0, 20.0])
    gc_was_enabled = gc.isenabled()
    try:
        gc.disable()
        result = em.optimize_stock_solutions(
            quantum=0.1,
            max_refine=60,
            two_max_refine=40,
            allow_two=False,
        )
        assert result["best"] is True
        assert gc.isenabled() is False
    finally:
        if gc_was_enabled:
            gc.enable()

def _make_calibratable_two_stock_model():
    em = _make_resolution_reproduction_model(
        [0.5, 1.0, 5.0, 20.0],
        printed_volume_nl=240.0,
        include_other=False,
        max_stock_conc=2000.0,
    )
    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=True,
    )
    assert result["best"] is True
    plan = em._calibration_plan_with_stock_ids(("R", None))
    assert plan["n_stocks"] == 2
    return em, plan["stocks"][0]["stock_id"]


def _two_stock_applied_calibration(stock_id):
    return {
        "stock_id": stock_id,
        "printer_head": SimpleNamespace(printer_head_id="two-stock-head-1"),
        "measured_volume_nL": 12.0,
        "pw_us": 1200,
        "pressure_psi": 0.8,
        "run_id": "two-stock-calibration",
        "phase": "synthetic_characterization",
    }


def _calibrated_payload_plans(payload):
    plans = {}
    for raw_key, plan in payload['plans_per_option'].items():
        if isinstance(raw_key, tuple):
            key = raw_key
        else:
            decoded = json.loads(raw_key)
            key = (decoded[0], decoded[1])
        plans[key] = plan
    return plans


def _refresh_calibrated_payload_plan_fingerprint(model, payload):
    payload['plan_fingerprint'] = model._canonical_payload_sha256(
        model._stock_allocation_plan_document(
            _calibrated_payload_plans(payload),
            payload['stock_rows'],
        )
    )


def _make_over_threshold_calibrated_payload():
    em, calibrated_stock_id = _make_calibratable_two_stock_model()
    calibration = _two_stock_applied_calibration(calibrated_stock_id)
    calibration.update(
        measured_volume_nL=140.0,
        run_id='two-stock-invalid-reuse-source',
    )
    em.apply_droplet_volume_for_option(
        'R',
        None,
        140.0,
        write_keys_if_assigned=False,
        applied_calibration=calibration,
        printing_mode='stream',
    )
    payload = copy.deepcopy(
        em.calibrated_stock_allocation['allocation']
    )
    return em, calibrated_stock_id, payload


def test_two_stock_calibration_changes_only_selected_volume_and_joint_counts():
    em, calibrated_stock_id = _make_calibratable_two_stock_model()

    preview = em.preview_requantized_for_option(
        ("R", None),
        12.0,
        calibrated_stock_id=calibrated_stock_id,
        printing_mode="droplet",
    )

    assert preview["ok"] is True
    assert preview["old_effective_volumes_nL"] == pytest.approx((10.0, 10.0))
    assert preview["new_effective_volumes_nL"] == pytest.approx((12.0, 10.0))
    assert preview["old_distinct_level_loss"] == 0
    assert preview["new_distinct_level_loss"] == 0
    by_target = {row["target_final"]: row for row in preview["rows"]}
    assert by_target[5.0]["old_drops"] == (1, 20)
    assert by_target[5.0]["drops"] == (1, 4)
    assert by_target[20.0]["old_drops"] == (5, 0)
    assert by_target[20.0]["drops"] == (4, 16)

    applied = em.apply_droplet_volume_for_option(
        "R",
        None,
        12.0,
        write_keys_if_assigned=False,
        applied_calibration=_two_stock_applied_calibration(calibrated_stock_id),
        printing_mode="droplet",
    )

    assert applied["calibrated_stock_id"] == calibrated_stock_id
    assert applied["companion_effective_volume_nL"] == pytest.approx(10.0)
    assert applied["changed_target_count"] == 2
    stocks = em.plans_per_option[("R", None)]["stocks"]
    assert [stock["droplet_volume_nL"] for stock in stocks] == pytest.approx([12.0, 10.0])
    assert stocks[1]["droplets_per_target"][5.0] == 4
    assert em.calibrated_stock_allocation_status == {
        "active": True,
        "reason": "applied",
    }
    assert all(
        float(row["nonfill_volume_nL"])
        + int(row["fill_drops"])
        * float(em.metadata["fill_droplet_volume_nL"])
        <= float(em.metadata["target_reaction_volume_nL"])
        + float(em.metadata["printed_volume_tolerance_nL"])
        + 1e-9
        for row in em._reactions_df.to_dict("records")
    )

def test_two_stock_stream_calibration_above_volume_threshold_warns_and_applies():
    em, calibrated_stock_id = _make_calibratable_two_stock_model()
    initial_calibration = _two_stock_applied_calibration(calibrated_stock_id)
    initial_calibration.update(
        measured_volume_nL=60.0,
        run_id="two-stock-stream-60",
    )
    initial = em.apply_droplet_volume_for_option(
        "R",
        None,
        60.0,
        write_keys_if_assigned=False,
        applied_calibration=initial_calibration,
        printing_mode="stream",
    )
    assert initial["new_droplet_nL"] == pytest.approx(60.0)

    preview = em.preview_requantized_for_option(
        ("R", None),
        140.0,
        calibrated_stock_id=calibrated_stock_id,
        printing_mode="stream",
    )

    assert preview["ok"] is True
    assert preview["old_effective_volumes_nL"][0] == pytest.approx(60.0)
    assert preview["pair_evaluations"] > 0
    warning = preview["volume_warning"]
    assert warning["code"] == "calibration_volume_tolerance_exceeded"
    assert warning["warning_threshold_nL"] == pytest.approx(240.0)
    assert warning["affected_row_count"] == len(warning["affected_rows"])
    assert warning["affected_row_count"] > 0
    assert warning["max_excess_nL"] > 0.0
    assert [row["row_id"] for row in warning["affected_rows"]] == sorted(
        row["row_id"] for row in warning["affected_rows"]
    )

    calibration = _two_stock_applied_calibration(calibrated_stock_id)
    calibration.update(
        measured_volume_nL=140.0,
        run_id="two-stock-stream-140",
    )
    applied = em.apply_droplet_volume_for_option(
        "R",
        None,
        140.0,
        write_keys_if_assigned=False,
        applied_calibration=calibration,
        printing_mode="stream",
    )

    assert applied["volume_warning"] == warning
    stocks = em.plans_per_option[("R", None)]["stocks"]
    assert stocks[0]["droplet_volume_nL"] == pytest.approx(140.0)
    assert stocks[1]["droplet_volume_nL"] == pytest.approx(10.0)
    generated = em._reactions_df.to_dict("records")
    assert any(
        int(row["fill_drops"]) == 0
        and float(row["nonfill_volume_nL"]) >= 240.0
        for row in generated
    )
    assert em._calibration_volume_warning_for_generated_reactions() == warning

def test_calibration_volume_warning_boundary_and_final_volume_context():
    em = ExperimentModel(prof=CURRENT_PROFILE)

    assert em._build_calibration_volume_warning(
        [
            {"row_id": "below", "total_volume_nL": 119.0},
            {"row_id": "exact", "total_volume_nL": 120.0},
            {"row_id": "epsilon", "total_volume_nL": 120.0 + 1e-9},
        ],
        target_printed_volume_nL=100.0,
        design_optimization_tolerance_nL=20.0,
        final_reaction_volume_nL=110.0,
    ) is None

    warning = em._build_calibration_volume_warning(
        [
            {
                "row_id": "A1",
                "well_id": "A1",
                "reaction_id": "R1",
                "total_volume_nL": 120.0 + 2e-9,
            },
            {
                "row_id": "A2",
                "well_id": "A2",
                "reaction_id": "R2",
                "total_volume_nL": 130.0,
            },
        ],
        target_printed_volume_nL=100.0,
        design_optimization_tolerance_nL=20.0,
        final_reaction_volume_nL=125.0,
    )

    assert warning["affected_row_count"] == 2
    assert warning["max_total_volume_nL"] == pytest.approx(130.0)
    assert warning["max_excess_nL"] == pytest.approx(10.0)
    assert [row["row_id"] for row in warning["affected_rows"]] == ["A1", "A2"]
    assert warning["affected_rows"][0]["exceeds_final_reaction_volume"] is False
    assert warning["affected_rows"][1]["exceeds_final_reaction_volume"] is True


def test_calibration_volume_warning_audit_failure_does_not_undo_mutable_apply():
    em, calibrated_stock_id = _make_calibratable_two_stock_model()

    def _fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit unavailable")

    em.set_calibration_manager(
        SimpleNamespace(
            model=SimpleNamespace(record_experiment_audit_event=_fail_audit)
        )
    )
    calibration = _two_stock_applied_calibration(calibrated_stock_id)
    calibration["measured_volume_nL"] = 140.0

    applied = em.apply_droplet_volume_for_option(
        "R",
        None,
        140.0,
        write_keys_if_assigned=False,
        applied_calibration=calibration,
        printing_mode="stream",
    )

    assert applied["volume_warning"]["affected_row_count"] > 0
    assert em.plans_per_option[("R", None)]["stocks"][0][
        "droplet_volume_nL"
    ] == pytest.approx(140.0)



def test_two_stock_calibration_can_select_the_companion_leg():
    em, _calibrated_stock_id = _make_calibratable_two_stock_model()
    plan = em._calibration_plan_with_stock_ids(("R", None))
    companion_stock_id = plan["stocks"][1]["stock_id"]

    applied = em.apply_droplet_volume_for_option(
        "R",
        None,
        11.0,
        write_keys_if_assigned=False,
        applied_calibration=_two_stock_applied_calibration(companion_stock_id),
        printing_mode="droplet",
    )

    assert applied["calibrated_stock_id"] == companion_stock_id
    assert applied["companion_effective_volume_nL"] == pytest.approx(10.0)
    assert [
        stock["droplet_volume_nL"]
        for stock in em.plans_per_option[("R", None)]["stocks"]
    ] == pytest.approx([10.0, 11.0])


def test_two_stock_calibrated_allocation_round_trips_without_reoptimization(monkeypatch):
    em, calibrated_stock_id = _make_calibratable_two_stock_model()
    em.apply_droplet_volume_for_option(
        "R",
        None,
        12.0,
        write_keys_if_assigned=False,
        applied_calibration=_two_stock_applied_calibration(calibrated_stock_id),
        printing_mode="droplet",
    )
    document = em.to_dict()

    restored = ExperimentModel(prof=CURRENT_PROFILE)
    restored.from_dict(document)
    assert restored.calibrated_stock_allocation_status == {
        "active": True,
        "reason": "restored",
    }
    assert [
        stock["droplet_volume_nL"]
        for stock in restored.plans_per_option[("R", None)]["stocks"]
    ] == pytest.approx([12.0, 10.0])
    restored.set_metadata(start_row=2, randomize_assignments=True, random_seed=91)

    monkeypatch.setattr(
        restored,
        "_enumerate_single_stock_candidates",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("calibrated allocation must be reused")
        ),
    )
    result = restored.optimize_stock_solutions(allow_two=True)
    assert result["best"] is True
    assert result["calibrated_stock_allocation_reused"] is True


def test_over_threshold_calibrated_allocation_restores_complete_result_without_search(
    monkeypatch,
    tmp_path,
):
    baseline, _baseline_stock_id = _make_calibratable_two_stock_model()
    normal_result_keys = set(baseline.optimize_stock_solutions(allow_two=True))

    em, calibrated_stock_id = _make_calibratable_two_stock_model()
    audit_events = []
    em.set_calibration_manager(
        SimpleNamespace(
            model=SimpleNamespace(
                record_experiment_audit_event=lambda *args, **kwargs: (
                    audit_events.append((args, kwargs))
                )
            )
        )
    )
    initial_calibration = _two_stock_applied_calibration(calibrated_stock_id)
    initial_calibration.update(
        measured_volume_nL=60.0,
        run_id='two-stock-stream-60-round-trip',
    )
    em.apply_droplet_volume_for_option(
        'R',
        None,
        60.0,
        write_keys_if_assigned=False,
        applied_calibration=initial_calibration,
        printing_mode='stream',
    )
    calibration = _two_stock_applied_calibration(calibrated_stock_id)
    calibration.update(
        measured_volume_nL=140.0,
        run_id='two-stock-stream-140-round-trip',
    )
    applied = em.apply_droplet_volume_for_option(
        'R',
        None,
        140.0,
        write_keys_if_assigned=False,
        applied_calibration=calibration,
        printing_mode='stream',
    )
    warning = copy.deepcopy(applied['volume_warning'])
    assert warning is not None
    audit_count_after_apply = len(audit_events)
    assert audit_count_after_apply > 0

    expected_plan = copy.deepcopy(em.plans_per_option)
    expected_reactions = em._reactions_df.to_dict('records')
    expected_records = copy.deepcopy(em.applied_imaging_calibrations)
    design_path = tmp_path / 'experiment_design.json'
    em._atomic_json_dump(str(design_path), em.to_dict())
    document = json.loads(design_path.read_text(encoding='utf-8'))

    restored = ExperimentModel(prof=CURRENT_PROFILE)
    restored.from_dict(document)

    assert restored.calibrated_stock_allocation_status == {
        'active': True,
        'reason': 'restored',
    }
    assert restored.plans_per_option == expected_plan
    assert restored._reactions_df.to_dict('records') == expected_reactions
    assert (
        restored._calibration_volume_warning_for_generated_reactions()
        == warning
    )

    def _unexpected_search(*_args, **_kwargs):
        raise AssertionError('calibrated allocation must be reused without search')

    monkeypatch.setattr(
        restored,
        '_enumerate_single_stock_candidates',
        _unexpected_search,
    )
    monkeypatch.setattr(
        restored,
        '_enumerate_two_stock_candidates_with_meta',
        _unexpected_search,
    )
    restored.set_calibration_manager(
        SimpleNamespace(
            model=SimpleNamespace(
                record_experiment_audit_event=lambda *args, **kwargs: (
                    audit_events.append((args, kwargs))
                )
            )
        )
    )
    result = restored.optimize_stock_solutions(allow_two=True)

    assert normal_result_keys <= set(result)
    assert result['best'] is True
    assert result['calibrated_stock_allocation_reused'] is True
    assert result['optimizer_strategy_used'] == 'calibration_requantization'
    assert result['stock_allocation_stop_reason'] == 'calibrated_plan_reused'
    assert result['optimizer_seed_rank'] == result['optimizer_selected_rank']
    assert result['distinct_level_loss'] == 0
    assert result['stocks'] == 2
    assert result['worst_nonfill_nL'] == pytest.approx(
        max(row['nonfill_volume_nL'] for row in expected_reactions)
    )
    assert result['volume_warning'] == warning
    assert result['stock_allocation_states_evaluated'] == 0
    assert result['two_stock_pairs_evaluated'] == 0
    assert result['stock_allocation_candidates_generated'] == 0
    assert result['optimizer_total_elapsed_ms'] == 0.0
    assert restored.plans_per_option == expected_plan
    assert restored.applied_imaging_calibrations == expected_records
    assert len(audit_events) == audit_count_after_apply
    reused_design_path = tmp_path / 'reused_experiment_design.json'
    restored._atomic_json_dump(str(reused_design_path), restored.to_dict())
    reused_document = json.loads(
        reused_design_path.read_text(encoding='utf-8')
    )
    assert (
        reused_document['calibrated_stock_allocation']
        == document['calibrated_stock_allocation']
    )


def test_calibrated_allocation_above_final_volume_restores_with_warning(tmp_path):
    em = _make_model(
        target_volume_nl=240.0,
        final_volume_nl=239.0,
        printed_volume_tolerance_nl=0.0,
    )
    em.add_additive(
        'R',
        [0.5, 1.0, 5.0, 20.0],
        'mM',
        10.0,
        max_stock_conc=2000.0,
    )
    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=True,
    )
    assert result['best'] is True
    plan = em._calibration_plan_with_stock_ids(('R', None))
    calibrated_stock_id = plan['stocks'][0]['stock_id']
    calibration = _two_stock_applied_calibration(calibrated_stock_id)
    calibration.update(
        measured_volume_nL=140.0,
        run_id='two-stock-above-final',
    )
    applied = em.apply_droplet_volume_for_option(
        'R',
        None,
        140.0,
        write_keys_if_assigned=False,
        applied_calibration=calibration,
        printing_mode='stream',
    )
    warning = applied['volume_warning']
    assert any(
        row['exceeds_final_reaction_volume']
        for row in warning['affected_rows']
    )

    design_path = tmp_path / 'above_final_design.json'
    em._atomic_json_dump(str(design_path), em.to_dict())
    restored = ExperimentModel(prof=CURRENT_PROFILE)
    restored.from_dict(
        json.loads(design_path.read_text(encoding='utf-8'))
    )

    assert restored.calibrated_stock_allocation_status == {
        'active': True,
        'reason': 'restored',
    }
    restored_warning = (
        restored._calibration_volume_warning_for_generated_reactions()
    )
    assert restored_warning == warning
    assert any(
        row['exceeds_final_reaction_volume']
        for row in restored_warning['affected_rows']
    )


def test_calibrated_reuse_requires_context_flag_and_matching_stock_identity():
    em, calibrated_stock_id, payload = _make_over_threshold_calibrated_payload()
    before_plan = copy.deepcopy(em.plans_per_option)

    generic = em.install_stock_allocation_reuse_payload(payload)
    missing_identity = em.install_stock_allocation_reuse_payload(
        payload,
        reuse_context='calibration',
    )
    mismatched_identity = em.install_stock_allocation_reuse_payload(
        payload,
        reuse_context='calibration',
        expected_calibrated_stock_id='R_not_the_calibrated_stock_mM',
    )
    missing_flag = copy.deepcopy(payload)
    missing_flag.pop('calibrated_independent_volumes')
    unauthenticated = em.install_stock_allocation_reuse_payload(
        missing_flag,
        reuse_context='calibration',
        expected_calibrated_stock_id=calibrated_stock_id,
    )

    assert generic == {
        'reused': False,
        'reason': 'calibrated_reuse_context_required',
    }
    assert missing_identity == {
        'reused': False,
        'reason': 'calibrated_stock_identity_required',
    }
    assert mismatched_identity['reused'] is False
    assert mismatched_identity['reason'] == 'stock_plan_validation_failed'
    assert 'identity does not match' in mismatched_identity['detail']
    assert unauthenticated == {
        'reused': False,
        'reason': 'calibrated_independent_volumes_required',
    }
    assert em.plans_per_option == before_plan


def test_calibrated_reuse_rejects_corruption_transactionally():
    mutation_names = (
        'out_of_envelope_volume',
        'persisted_out_of_envelope_volume',
        'nonfinite_volume',
        'invalid_count',
        'missing_mapping',
        'input_fingerprint',
        'plan_fingerprint',
    )
    for mutation_name in mutation_names:
        em, calibrated_stock_id, payload = _make_over_threshold_calibrated_payload()
        before_plan = copy.deepcopy(em.plans_per_option)
        before_rows = copy.deepcopy(em._stock_rows_cache)
        plan = next(iter(payload['plans_per_option'].values()))
        stock = plan['stocks'][0]
        concentration = float(stock['stock_concentration'])

        if mutation_name == 'persisted_out_of_envelope_volume':
            matching_row = next(
                row
                for row in payload['stock_rows']
                if float(row['stock_concentration']) == concentration
            )
            matching_row['droplet_volume_nL'] = 251.0
            _refresh_calibrated_payload_plan_fingerprint(em, payload)
        elif mutation_name in {'out_of_envelope_volume', 'nonfinite_volume'}:
            volume = (
                251.0
                if mutation_name == 'out_of_envelope_volume'
                else float('nan')
            )
            stock['droplet_volume_nL'] = volume
            stock['delta_per_drop'] = (
                concentration
                * volume
                / float(em.metadata['final_reaction_volume_nL'])
            )
            matching_row = next(
                row
                for row in payload['stock_rows']
                if float(row['stock_concentration']) == concentration
            )
            matching_row['droplet_volume_nL'] = volume
            matching_row['delta_per_drop'] = stock['delta_per_drop']
            _refresh_calibrated_payload_plan_fingerprint(em, payload)
        elif mutation_name == 'invalid_count':
            target = next(iter(stock['droplets_per_target']))
            stock['droplets_per_target'][target] = True
            _refresh_calibrated_payload_plan_fingerprint(em, payload)
        elif mutation_name == 'missing_mapping':
            target = next(iter(stock['droplets_per_target']))
            del stock['droplets_per_target'][target]
            _refresh_calibrated_payload_plan_fingerprint(em, payload)
        elif mutation_name == 'input_fingerprint':
            payload['input_fingerprint'] = 'invalid-input-fingerprint'
        else:
            payload['plan_fingerprint'] = 'invalid-plan-fingerprint'

        reused = em.install_stock_allocation_reuse_payload(
            payload,
            reuse_context='calibration',
            expected_calibrated_stock_id=calibrated_stock_id,
        )

        assert reused['reused'] is False, mutation_name
        assert em.plans_per_option == before_plan, mutation_name
        assert em._stock_rows_cache == before_rows, mutation_name


def test_calibrated_reuse_rejects_duplicate_runtime_stock_ids_transactionally():
    em, calibrated_stock_id, payload = _make_over_threshold_calibrated_payload()
    before_plan = copy.deepcopy(em.plans_per_option)
    before_rows = copy.deepcopy(em._stock_rows_cache)
    plan = next(iter(payload['plans_per_option'].values()))
    first, second = plan['stocks']
    targets = sorted(float(target) for target in first['droplets_per_target'])
    concentrations = (25.0, 25.001)
    final_volume = float(em.metadata['final_reaction_volume_nL'])

    for index, (stock, row, concentration) in enumerate(
        zip(plan['stocks'], payload['stock_rows'], concentrations)
    ):
        volume = float(stock['droplet_volume_nL'])
        delta = concentration * volume / final_volume
        stock['stock_concentration'] = concentration
        stock['delta_per_drop'] = delta
        stock['droplets_per_target'] = {
            target: (
                0
                if index == 0
                else max(0, int(round(target / delta)))
            )
            for target in targets
        }
        row['stock_concentration'] = concentration
        row['delta_per_drop'] = delta

    _refresh_calibrated_payload_plan_fingerprint(em, payload)
    reused = em.install_stock_allocation_reuse_payload(
        payload,
        reuse_context='calibration',
        expected_calibrated_stock_id=calibrated_stock_id,
    )

    assert reused['reused'] is False
    assert reused['reason'] == 'stock_plan_validation_failed'
    assert 'duplicate runtime stock IDs' in reused['detail']
    assert em.plans_per_option == before_plan
    assert em._stock_rows_cache == before_rows


def test_minimal_legacy_calibrated_result_is_normalized_to_complete_contract():
    baseline, _baseline_stock_id = _make_calibratable_two_stock_model()
    normal_result_keys = set(baseline.optimize_stock_solutions(allow_two=True))
    em, calibrated_stock_id, payload = _make_over_threshold_calibrated_payload()
    payload['plans_per_option'] = _calibrated_payload_plans(payload)
    payload['optimization_result'] = {
        'best': True,
        'optimizer_strategy_used': 'calibration_requantization',
    }

    reused = em.install_stock_allocation_reuse_payload(
        payload,
        reuse_context='calibration',
        expected_calibrated_stock_id=calibrated_stock_id,
    )

    assert reused['reused'] is True
    result = reused['result']
    assert normal_result_keys <= set(result)
    assert result['optimizer_seed_rank'] == result['optimizer_selected_rank']
    assert result['optimizer_total_elapsed_ms'] == 0.0
    assert result['volume_warning'] == reused['volume_warning']


def test_two_stock_calibrated_allocation_becomes_inactive_after_stock_input_change():
    em, calibrated_stock_id = _make_calibratable_two_stock_model()
    em.apply_droplet_volume_for_option(
        "R",
        None,
        12.0,
        write_keys_if_assigned=False,
        applied_calibration=_two_stock_applied_calibration(calibrated_stock_id),
        printing_mode="droplet",
    )
    record = next(iter(em.applied_imaging_calibrations["records"].values()))
    lookup = {
        "stock_id": record["stock_id"],
        "printer_head_id": record["printer_head_id"],
        "printing_mode": record["printing_mode"],
        "factor_name": record["factor_name"],
        "option_name": record["option_name"],
        "is_fill": record["is_fill"],
    }
    assert em.get_applied_imaging_calibration(**lookup) is not None

    em.factors[0].options[0].targets = [0.5, 1.0, 5.0, 10.0, 20.0]

    assert em.get_applied_imaging_calibration(**lookup) is None
    result = em.optimize_stock_solutions(allow_two=True)
    assert result["best"] is True
    assert em.calibrated_stock_allocation_status == {
        "active": False,
        "reason": "stock_input_fingerprint_mismatch",
    }


@pytest.mark.parametrize("failure_point", ["generate", "record"])
def test_two_stock_calibration_failure_restores_mutable_state(
    monkeypatch,
    failure_point,
):
    em, calibrated_stock_id = _make_calibratable_two_stock_model()
    before_plan = copy.deepcopy(em.plans_per_option)
    before_rows = copy.deepcopy(em._stock_rows_cache)
    before_records = copy.deepcopy(em.applied_imaging_calibrations)
    before_refuel = copy.deepcopy(em.manual_refuel_checks)
    before_allocation = copy.deepcopy(em.calibrated_stock_allocation)
    before_status = copy.deepcopy(em.calibrated_stock_allocation_status)
    before_reactions = em._reactions_df.copy(deep=True)
    before_preview = copy.deepcopy(em._target_preview_map)
    before_unreachable = copy.deepcopy(em._unreachable_preview_map)
    before_unsaved = em.unsaved_changes
    method_name = (
        "generate_experiment"
        if failure_point == "generate"
        else "record_applied_imaging_calibration"
    )
    original = getattr(em, method_name)

    def _fail_after(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError(f"injected two-stock {failure_point} failure")

    monkeypatch.setattr(em, method_name, _fail_after)
    calibration = _two_stock_applied_calibration(calibrated_stock_id)
    calibration["measured_volume_nL"] = 140.0

    with pytest.raises(
        RuntimeError,
        match=f"injected two-stock {failure_point} failure",
    ):
        em.apply_droplet_volume_for_option(
            "R",
            None,
            140.0,
            write_keys_if_assigned=False,
            applied_calibration=calibration,
            printing_mode="stream",
        )

    assert em.plans_per_option == before_plan
    assert em._stock_rows_cache == before_rows
    assert em.applied_imaging_calibrations == before_records
    assert em.manual_refuel_checks == before_refuel
    assert em.calibrated_stock_allocation == before_allocation
    assert em.calibrated_stock_allocation_status == before_status
    assert em._reactions_df.equals(before_reactions)
    assert em._target_preview_map == before_preview
    assert em._unreachable_preview_map == before_unreachable
    assert em.unsaved_changes is before_unsaved


def test_two_stock_calibration_pair_cap_fails_closed_without_mutating_preview():
    em, calibrated_stock_id = _make_calibratable_two_stock_model()
    before = copy.deepcopy(em.plans_per_option)

    capped = em._requantize_fixed_two_stock_group(
        ("R", None),
        calibrated_stock_id=calibrated_stock_id,
        new_effective_volume_nL=12.0,
        pair_evaluation_cap=1,
    )
    low_volume = em.preview_requantized_for_option(
        ("R", None),
        8.0,
        calibrated_stock_id=calibrated_stock_id,
    )

    assert capped["ok"] is False
    assert capped["code"] == "pair_evaluation_cap"
    assert low_volume["ok"] is True
    assert em.plans_per_option == before


def test_resolution_search_cap_is_deterministic_and_returns_best_validated_plan(monkeypatch):
    em = _make_resolution_reproduction_model([0.5, 1.0, 5.0, 20.0])
    monkeypatch.setattr(em, "MAX_STOCK_ALLOCATION_STATES", 1)

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert result["best"] is True
    assert result["stock_allocation_states_evaluated"] == 1
    assert result["stock_allocation_search_limited"] is True
    assert result["stock_allocation_limit_reasons"] == ["state_cap"]
    assert result["stock_allocation_stop_reason"] == "state_cap"
    assert result["stock_allocation_improved_seed"] is True
    assert result["distinct_level_loss"] == 0
    assert any(
        issue["code"] == "bounded_stock_allocation_search"
        for issues in result["issues_by_key"].values()
        for issue in issues
    )



def test_resolution_work_cap_during_candidate_pool_returns_untouched_seed(
    monkeypatch,
):
    em = _make_resolution_reproduction_model([0.5, 1.0, 5.0, 20.0])
    monkeypatch.setattr(em, "MAX_STOCK_ALLOCATION_WORK_UNITS", 1)

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert result["best"] is True
    assert result["distinct_level_loss"] == 1
    assert result["stock_allocation_states_evaluated"] == 0
    assert result["stock_allocation_candidates_generated"] == 1
    assert result["stock_allocation_candidates_retained"] == 0
    assert result["stock_allocation_work_units_evaluated"] == 1
    assert result["stock_allocation_work_units_by_kind"] == {
        "two_stock_probe": 0,
        "two_stock_pair": 0,
        "candidate_pool": 1,
        "global_search": 0,
    }
    assert result["stock_allocation_limit_reasons"] == ["work_cap"]
    assert result["optimizer_strategy_used"] == "resolution_first"
    assert result["stock_allocation_stop_reason"] == "work_cap"
    assert result["stock_allocation_improved_seed"] is False
    assert result["stock_allocation_time_to_best_ms"] is None
    bounded_issue = next(
        issue
        for issue in result["issues_by_key"][("__stock_allocation__", None)]
        if issue["code"] == "bounded_stock_allocation_search"
    )
    assert "deterministic work limit" in bounded_issue["message"]
    assert bounded_issue["improved_seed"] is False
    assert bounded_issue["stop_reason"] == "work_cap"


def test_resolution_tier_exhaustion_records_final_best_time(monkeypatch):
    em = _make_resolution_reproduction_model([0.5, 1.0, 5.0, 20.0])
    monkeypatch.setattr(em, "_stock_optimizer_monotonic", lambda: 0.0)

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert result["best"] is True
    assert result["distinct_level_loss"] == 0
    assert result["stock_allocation_stop_reason"] == "search_exhausted"
    assert result["stock_allocation_limit_reasons"] == []
    assert result["stock_allocation_improved_seed"] is True
    assert result["stock_allocation_time_to_best_ms"] == pytest.approx(0.0)



def test_resolution_work_cap_after_candidate_pool_returns_seed(monkeypatch):
    em = _make_resolution_reproduction_model([0.5, 1.0, 5.0, 20.0])
    monkeypatch.setattr(em, "MAX_STOCK_ALLOCATION_WORK_UNITS", 223)

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert result["best"] is True
    assert result["distinct_level_loss"] == 1
    assert result["stock_allocation_states_evaluated"] == 0
    assert result["stock_allocation_candidates_generated"] == 223
    assert result["stock_allocation_candidates_retained"] == 223
    assert result["stock_allocation_work_units_evaluated"] == 223
    assert result["stock_allocation_work_units_by_kind"]["candidate_pool"] == 223
    assert result["stock_allocation_work_units_by_kind"]["global_search"] == 0
    assert result["stock_allocation_limit_reasons"] == ["work_cap"]
    assert result["stock_allocation_stop_reason"] == "work_cap"
    assert result["stock_allocation_improved_seed"] is False



def test_resolution_work_cap_during_branching_returns_best_found(monkeypatch):
    em = _make_resolution_reproduction_model([0.5, 1.0, 5.0, 20.0])
    monkeypatch.setattr(em, "MAX_STOCK_ALLOCATION_WORK_UNITS", 230)

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert result["best"] is True
    assert result["distinct_level_loss"] == 0
    assert result["stock_allocation_states_evaluated"] == 1
    assert result["stock_allocation_work_units_evaluated"] == 230
    assert result["stock_allocation_work_units_by_kind"]["candidate_pool"] == 223
    assert result["stock_allocation_work_units_by_kind"]["global_search"] == 7
    assert result["stock_allocation_limit_reasons"] == ["work_cap"]
    assert result["stock_allocation_stop_reason"] == "work_cap"
    assert result["stock_allocation_improved_seed"] is True
    assert result["stock_allocation_time_to_best_ms"] is not None
    bounded_issue = next(
        issue
        for issue in result["issues_by_key"][("__stock_allocation__", None)]
        if issue["code"] == "bounded_stock_allocation_search"
    )
    assert "reduced grouped levels from 1 to 0" in bounded_issue["message"]
    assert "secondary optimality was not proven" in bounded_issue["message"]
    assert bounded_issue["improved_seed"] is True



def test_two_stock_clock_overrun_does_not_interrupt_pair_polishing(monkeypatch):
    em = _make_resolution_reproduction_model(
        [0.5, 1.0, 5.0, 20.0],
        printed_volume_nl=240.0,
        include_other=False,
        max_stock_conc=2000.0,
    )
    original_two = em._enumerate_two_stock_candidates_with_meta
    phase = {"zero_loss_candidate_validated": False}

    def fake_clock():
        return 1.0 if phase["zero_loss_candidate_validated"] else 0.0

    def track_validated_improvement(*args, **kwargs):
        original_callback = kwargs["candidate_callback"]

        def tracked_callback(plan):
            stop_requested = original_callback(plan)
            if int(plan.lost_levels) == 0:
                phase["zero_loss_candidate_validated"] = True
            return stop_requested

        kwargs["candidate_callback"] = tracked_callback
        return original_two(*args, **kwargs)

    monkeypatch.setattr(em, "_stock_optimizer_monotonic", fake_clock)
    monkeypatch.setattr(
        em,
        "_enumerate_two_stock_candidates_with_meta",
        track_validated_improvement,
    )

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=True,
    )

    assert result["best"] is True
    assert phase["zero_loss_candidate_validated"] is True
    assert result["distinct_level_loss"] == 0
    assert result["two_stock_pairs_evaluated"] == 180
    assert result["stock_allocation_limit_reasons"] == []
    assert result["two_stock_search_limited_keys"] == []
    assert result["stock_allocation_stop_reason"] == "zero_loss_polish_complete"
    assert result["stock_allocation_zero_loss_polish_work_used"] == 256
    assert result["stock_allocation_time_budget_exceeded"] is True
    assert result["stock_allocation_time_budget_overshoot_ms"] == pytest.approx(
        925.0
    )
    assert result["stock_allocation_deadline_overshoot_ms"] == pytest.approx(
        result["stock_allocation_time_budget_overshoot_ms"]
    )
    assert em.plans_per_option[("R", None)]["n_stocks"] == 2



def test_two_stock_enumeration_returns_complete_candidates_at_work_cap():
    em = _make_resolution_reproduction_model(
        [0.5, 1.0, 5.0, 20.0],
        printed_volume_nl=240.0,
        include_other=False,
        max_stock_conc=2000.0,
    )
    work_limit = 57
    work_used = 0
    work_by_kind = {
        "two_stock_probe": 0,
        "two_stock_pair": 0,
    }
    limit_reasons = set()
    diagnostics = {}

    def consume_work(kind, units=1):
        nonlocal work_used
        if work_used + int(units) > work_limit:
            return False
        work_used += int(units)
        work_by_kind[kind] += int(units)
        return True

    candidates, search_limited = em._enumerate_two_stock_candidates_with_meta(
        [0.5, 1.0, 5.0, 20.0],
        10.0,
        "mM",
        final_volume_nL=5000.0,
        volume_budget_nL=240.0,
        nominal_volume_budget_nL=240.0,
        max_refine=20,
        max_stock_conc=2000.0,
        resolution_first=True,
        consume_work=consume_work,
        limit_reasons=limit_reasons,
        diagnostics=diagnostics,
    )

    assert search_limited is True
    assert work_used == work_limit
    assert work_by_kind == {
        "two_stock_probe": 56,
        "two_stock_pair": 1,
    }
    assert limit_reasons == {"work_cap"}
    assert candidates
    assert diagnostics["two_stock_pairs_evaluated"] == 1
    assert diagnostics["two_stock_target_evaluations"] > 0
    assert diagnostics["two_stock_solver_iterations"] > 0
    assert diagnostics["two_stock_candidates_generated"] >= len(candidates)
    assert diagnostics["two_stock_candidates_retained"] == len(candidates)
    assert all(candidate.target_rows for candidate in candidates)


def test_resolution_search_exception_returns_untouched_seed(monkeypatch):
    em = _make_resolution_reproduction_model([0.5, 1.0, 5.0, 20.0])
    original = em._evaluate_plan_resolution
    calls = 0

    def fail_after_seed(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 2:
            raise RuntimeError("injected resolution search failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(em, "_evaluate_plan_resolution", fail_after_seed)

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert result["best"] is True
    assert result["optimizer_strategy_used"] == "legacy_fallback"
    assert result["stock_allocation_stop_reason"] == "legacy_fallback"
    assert result["stock_allocation_improved_seed"] is False
    assert result["stock_allocation_time_to_best_ms"] is None
    assert "injected resolution search failure" in result["optimizer_fallback_reason"]
    assert result["distinct_level_loss"] == 1
    plan = em.plans_per_option[("R", None)]
    assert plan["stocks"][0]["delta_per_drop"] == pytest.approx(0.952380952381)
    assert any(
        issue["code"] == "legacy_optimizer_fallback"
        for issues in result["issues_by_key"].values()
        for issue in issues
    )



def test_resolution_state_cap_is_independent_of_slow_clock(monkeypatch):
    em = _make_resolution_reproduction_model([0.5, 1.0, 5.0, 20.0])
    monkeypatch.setattr(em, "MAX_STOCK_ALLOCATION_STATES", 1)
    monkeypatch.setattr(em, "_stock_optimizer_monotonic", lambda: 1.0)

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=False,
    )

    assert result["best"] is True
    assert result["stock_allocation_limit_reasons"] == ["state_cap"]
    assert result["stock_allocation_stop_reason"] == "state_cap"
    assert result["stock_allocation_states_evaluated"] == 1
    assert result["stock_allocation_time_budget_exceeded"] is False


def test_locked_optimizer_result_reports_not_run_diagnostics(monkeypatch):
    em = _make_resolution_reproduction_model([0.5, 1.0])
    monkeypatch.setattr(em, "is_execution_design_locked", lambda: True)

    result = em.optimize_stock_solutions(allow_two=False)

    assert result["best"] is None
    assert result["optimizer_seed_rank"] is None
    assert result["optimizer_selected_rank"] is None
    assert result["stock_allocation_improved_seed"] is False
    assert result["stock_allocation_time_to_best_ms"] is None
    assert result["stock_allocation_stop_reason"] == "not_run"


def test_forced_stock_preview_accepts_nearest_achievable_targets():
    targets = [
        0.149, 0.192, 0.366, 0.553, 0.641, 0.737, 0.928, 1.122, 1.237,
        1.345, 1.447, 1.63, 1.713, 1.902, 2.029, 2.153, 2.271, 2.403, 2.51,
    ]
    em = _make_model()
    em.add_additive("AddA", targets, "mM", 12.0, forced_stock_conc=35.0)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)
    assert result["best"]

    preview = em.get_target_preview_map()[("AddA", None)]
    assert len(preview) == len(targets)
    assert em.get_unreachable_preview_map() == {}

    by_target = {row["requested_final"]: row for row in preview}
    assert by_target[0.149]["reachable"] is True
    assert by_target[0.149]["droplets"] == 2
    assert by_target[0.149]["achieved_final"] == pytest.approx(0.168)
    assert by_target[2.51]["droplets"] == 30
    assert by_target[2.51]["achieved_final"] == pytest.approx(2.52)

    plan = em.plans_per_option[("AddA", None)]
    assert plan["n_stocks"] == 1
    assert plan["stocks"][0]["quantum"] == pytest.approx(1e-6)


def test_forced_stock_preview_respects_starting_concentration():
    em = _make_model(target_volume_nl=1000.0, final_volume_nl=1000.0)
    em.add_additive("AddA", [0.5, 0.7], "mM", 10.0, starting_conc=0.5, forced_stock_conc=10.0)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=True)
    assert result["best"]

    preview = em.get_target_preview_map()[("AddA", None)]
    by_target = {row["requested_final"]: row for row in preview}

    assert by_target[0.5]["reachable"] is True
    assert by_target[0.5]["droplets"] == 0
    assert by_target[0.5]["achieved_final"] == pytest.approx(0.5)

    assert by_target[0.7]["reachable"] is True
    assert by_target[0.7]["requested_adjusted"] == pytest.approx(0.2)
    assert by_target[0.7]["achieved_adjusted"] == pytest.approx(0.2)


def test_forced_stock_helper_allows_half_step_midpoint():
    em = _make_model(target_volume_nl=10.0, final_volume_nl=10.0)

    row = em._evaluate_single_forced_target(
        t_final=1.5,
        starting_conc=0.0,
        forced_stock_conc=10.0,
        droplet_nL=1.0,
        final_volume_nL=10.0,
        units="mM",
    )

    assert row["delta_per_drop"] == pytest.approx(1.0)
    assert row["reachable"] is True
    assert row["droplets"] == 2
    assert row["abs_error"] == pytest.approx(0.5)
    assert row["reason"] == "nearest_achievable"


def test_forced_stock_preview_normalizes_target_keys_for_resolution():
    em = _make_model(target_volume_nl=1000.0, final_volume_nl=1000.0)
    target = 0.30000000000000004
    em.add_additive("AddA", [target], "mM", 10.0, starting_conc=0.1, forced_stock_conc=20.0)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=True)
    assert result["best"]

    plan = em.plans_per_option[("AddA", None)]
    stock = plan["stocks"][0]
    t_add = max(0.0, target - 0.1)
    drops, matched_key, unreachable, _nearest = em._resolve_drops_for_target(stock, t_add)

    assert drops == 1
    assert unreachable is False
    assert matched_key == pytest.approx(0.2)
    assert 0.2 in stock["droplets_per_target"]


def test_auto_paths_keep_optimizer_behavior_and_two_stock_enumeration():
    em = _make_model(target_volume_nl=500.0, final_volume_nl=500.0)
    em.add_additive("AddA", [0.5, 1.0], "mM", 10.0)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=True)
    assert result["best"]

    plan = em.plans_per_option[("AddA", None)]
    assert plan["stocks"][0]["quantum"] == pytest.approx(1e-6)
    preview = em.get_target_preview_map()[("AddA", None)]
    assert len(preview) == 2
    assert all(row["reachable"] for row in preview)
    assert em.get_unreachable_preview_map() == {}

    candidates = em._enumerate_two_stock_candidates(
        [0.1, 0.2],
        10.0,
        "mM",
        final_volume_nL=500.0,
        volume_budget_nL=500.0,
        quantum=0.1,
        max_refine=8,
    )
    assert any(
        candidate.droplets_per_target in (
            {0.1: (1, 0), 0.2: (0, 1)},
            {0.1: (0, 1), 0.2: (1, 0)},
        )
        for candidate in candidates
    )


def test_max_stock_bound_adds_physical_edge_single_stock_candidates():
    em = _make_model(target_volume_nl=500.0, final_volume_nl=500.0)
    candidates = em._enumerate_single_stock_candidates(
        [0.1, 0.2],
        10.0,
        "mM",
        final_volume_nL=500.0,
        max_refine=10,
        max_stock_conc=0.4,
    )
    assert candidates
    assert all(candidate.stock_concentration <= 0.4 + 1e-12 for candidate in candidates)


def test_max_stock_edge_candidate_handles_polyp_refine_cutoff():
    em = _make_model(target_volume_nl=6700.0, final_volume_nl=10000.0)
    candidates = em._enumerate_single_stock_candidates(
        [30.31, 59.6],
        10.0,
        "mM",
        final_volume_nL=10000.0,
        max_refine=60,
        max_stock_conc=500.0,
    )

    assert candidates
    assert all(candidate.stock_concentration <= 500.0 + 1e-12 for candidate in candidates)
    assert any(candidate.stock_concentration == pytest.approx(496.885245902, rel=1e-9) for candidate in candidates)


def test_bounded_auto_stock_prefers_lowest_error_candidate_under_selected_volume_limit():
    targets = [0.149, 0.192, 0.366, 0.553]
    droplet_nl = 12.0
    final_volume_nl = 5000.0
    max_stock_conc = 1.2

    em = _make_model(target_volume_nl=5000.0, final_volume_nl=final_volume_nl)
    candidates = em._enumerate_single_stock_candidates(
        targets,
        droplet_nl,
        "mM",
        final_volume_nL=final_volume_nl,
        max_refine=60,
        max_stock_conc=max_stock_conc,
    )
    assert candidates

    baseline = candidates[0]
    eligible = [
        candidate
        for candidate in candidates
        if candidate.max_volume_nL <= baseline.max_volume_nL + 1e-12
    ]
    expected = min(
        eligible,
        key=lambda candidate: _single_plan_error_key(
            em,
            targets,
            candidate,
            droplet_nl=droplet_nl,
            final_volume_nl=final_volume_nl,
        ),
    )
    baseline_key = _single_plan_error_key(
        em,
        targets,
        baseline,
        droplet_nl=droplet_nl,
        final_volume_nl=final_volume_nl,
    )
    expected_key = _single_plan_error_key(
        em,
        targets,
        expected,
        droplet_nl=droplet_nl,
        final_volume_nl=final_volume_nl,
    )

    assert expected.stock_concentration > baseline.stock_concentration
    assert expected_key[:2] < baseline_key[:2]

    em.add_additive("AddA", targets, "mM", droplet_nl, max_stock_conc=max_stock_conc)
    result = em.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)

    assert result["best"]
    plan = em.plans_per_option[("AddA", None)]
    assert plan["n_stocks"] == 1
    assert plan["stocks"][0]["stock_concentration"] == pytest.approx(expected.stock_concentration)

    preview = em.get_target_preview_map()[("AddA", None)]
    preview_worst = max(float(row["abs_error"]) for row in preview)
    preview_mean = sum(float(row["abs_error"]) for row in preview) / len(preview)
    assert preview_worst == pytest.approx(expected_key[0])
    assert preview_mean == pytest.approx(expected_key[1])


def test_two_stock_accuracy_refinement_prefers_lower_error_pair_at_same_volume(monkeypatch):
    targets = [0.31, 0.91, 1.21]
    droplet_nl = 10.0
    final_volume_nl = 500.0

    em = _make_model(target_volume_nl=20.0, final_volume_nl=final_volume_nl)
    em.add_additive("AddA", targets, "mM", droplet_nl)

    single_plan = _build_single_stock_plan(
        em,
        targets,
        15.0,
        droplet_nl=droplet_nl,
        final_volume_nl=final_volume_nl,
    )
    lower_conc_two = _build_two_stock_plan(
        em,
        targets,
        (14.0, 28.0),
        droplet_nl=droplet_nl,
        final_volume_nl=final_volume_nl,
    )
    better_error_two = _build_two_stock_plan(
        em,
        targets,
        (15.5, 30.0),
        droplet_nl=droplet_nl,
        final_volume_nl=final_volume_nl,
    )

    assert single_plan.max_volume_nL > 20.0
    assert lower_conc_two.max_volume_nL == pytest.approx(better_error_two.max_volume_nL)
    assert lower_conc_two.conc_sum < better_error_two.conc_sum
    assert _two_plan_error_key(
        em,
        targets,
        better_error_two,
        droplet_nl=droplet_nl,
        final_volume_nl=final_volume_nl,
    )[:2] < _two_plan_error_key(
        em,
        targets,
        lower_conc_two,
        droplet_nl=droplet_nl,
        final_volume_nl=final_volume_nl,
    )[:2]

    monkeypatch.setattr(
        em,
        "_enumerate_single_stock_candidates",
        lambda *args, **kwargs: [single_plan],
    )
    monkeypatch.setattr(
        em,
        "_enumerate_two_stock_candidates_with_meta",
        lambda *args, **kwargs: ([lower_conc_two, better_error_two], False),
    )

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=True)

    assert result["best"]
    assert ("AddA", None) in result["two_stock_keys"]
    assert result["worst_nonfill_nL"] == pytest.approx(better_error_two.max_volume_nL)

    plan = em.plans_per_option[("AddA", None)]
    assert plan["n_stocks"] == 2
    assert tuple(stock["stock_concentration"] for stock in plan["stocks"]) == pytest.approx(better_error_two.stock_concs)


def test_accuracy_refinement_skips_fixed_stock_plans(monkeypatch):
    em = _make_model(target_volume_nl=1000.0, final_volume_nl=1000.0)
    em.add_additive("AddA", [0.42, 0.84], "mM", 12.0, forced_stock_conc=35.0)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Fixed-stock plans should skip accuracy refinement scoring")

    monkeypatch.setattr(em, "_score_single_stock_plan", fail_if_called)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=True)

    assert result["best"]
    plan = em.plans_per_option[("AddA", None)]
    assert plan["stocks"][0]["stock_concentration"] == pytest.approx(35.0)
    assert result["issues_by_key"] == {}


def test_accuracy_refinement_does_not_increase_single_stock_volume_demand():
    targets = [0.149, 0.192, 0.366, 0.553]
    droplet_nl = 12.0
    final_volume_nl = 5000.0
    max_stock_conc = 1.2

    em = _make_model(target_volume_nl=5000.0, final_volume_nl=final_volume_nl)
    candidates = em._enumerate_single_stock_candidates(
        targets,
        droplet_nl,
        "mM",
        final_volume_nL=final_volume_nl,
        max_refine=60,
        max_stock_conc=max_stock_conc,
    )
    baseline = candidates[0]

    em.add_additive("AddA", targets, "mM", droplet_nl, max_stock_conc=max_stock_conc)
    result = em.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)

    assert result["best"]
    preview = em.get_target_preview_map()[("AddA", None)]
    max_printed_nl = max(int(row["droplets"]) for row in preview) * droplet_nl
    assert max_printed_nl <= baseline.max_volume_nL + 1e-12
    assert result["worst_nonfill_nL"] <= baseline.max_volume_nL + 1e-12
    assert result["worst_nonfill_nL"] <= 5000.0 + 1e-12


def test_two_stock_toggle_can_unlock_volume_budget_limited_design():
    em = _make_model(target_volume_nl=10.0, final_volume_nl=500.0)
    em.add_additive("AddA", [0.1, 0.2], "mM", 10.0)

    single_only = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)
    assert not single_only.get("best")
    assert "Enable two-stock mode" in single_only["reason"]

    with_two = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=True)
    assert with_two["best"]
    assert ("AddA", None) in with_two["two_stock_keys"]
    plan = em.plans_per_option[("AddA", None)]
    assert plan["n_stocks"] == 2
    assert tuple(sorted(stock["stock_concentration"] for stock in plan["stocks"])) == pytest.approx((5.0, 10.0))

    preview = em.get_target_preview_map()[("AddA", None)]
    assert [row["achieved_final"] for row in preview] == pytest.approx([0.1, 0.2])
    assert [row["abs_error"] for row in preview] == pytest.approx([0.0, 0.0], abs=1e-12)


def test_two_stock_enumeration_retains_exact_accuracy_winner_within_bounds():
    em = _make_model(target_volume_nl=10.0, final_volume_nl=500.0)

    candidates, pair_limit_hit = em._enumerate_two_stock_candidates_with_meta(
        [0.1, 0.2],
        10.0,
        "mM",
        final_volume_nL=500.0,
        volume_budget_nL=10.0,
        quantum=0.1,
        max_refine=20,
        max_pairs=12000,
        max_stock_conc=10.0,
    )

    assert pair_limit_hit is False
    assert len(candidates) <= 12000
    assert all(max(candidate.stock_concs) <= 10.0 + 1e-12 for candidate in candidates)
    assert all(
        set(candidate.target_rows) == set(candidate.droplets_per_target)
        and all(
            row["reachable"] is True
            and row["droplets"] == candidate.droplets_per_target[target]
            and row["printed_volume_nL"]
            == pytest.approx(
                sum(candidate.droplets_per_target[target])
                * candidate.droplet_nL
            )
            for target, row in candidate.target_rows.items()
        )
        for candidate in candidates
    )
    assert any(
        tuple(sorted(candidate.stock_concs)) == pytest.approx((5.0, 10.0))
        and _two_plan_error_key(
            em,
            [0.1, 0.2],
            candidate,
            droplet_nl=10.0,
            final_volume_nl=500.0,
        )[:2]
        == pytest.approx((0.0, 0.0), abs=1e-12)
        for candidate in candidates
    )


def test_bounded_two_stock_solver_uses_reachable_one_drop_alternative():
    em = _make_model(target_volume_nl=1.0, final_volume_nl=1.0)

    row = em._evaluate_two_stock_target(
        t_final=0.4,
        starting_conc=0.0,
        stock_concentrations=(0.3, 0.2),
        droplet_nL=1.0,
        final_volume_nL=1.0,
        units="mM",
        max_total_drops=1,
    )

    assert row["reachable"] is True
    assert row["droplets"] == (1, 0)
    assert row["achieved_final"] == pytest.approx(0.3)
    assert row["abs_error"] == pytest.approx(0.1)


def test_bounded_two_stock_solver_matches_small_brute_force_oracle():
    em = _make_model(target_volume_nl=1.0, final_volume_nl=1.0)

    for d1 in (0.1, 0.2, 0.3, 0.5):
        for d2 in (0.1, 0.2, 0.4):
            for target in (0.1, 0.25, 0.4, 0.75, 1.0):
                for drop_limit in range(1, 6):
                    actual_a, actual_b, actual_error = em._nearest_two_stock(
                        target,
                        d1,
                        d2,
                        max_total_drops=drop_limit,
                    )
                    oracle = []
                    for a in range(drop_limit + 1):
                        for b in range(drop_limit - a + 1):
                            oracle.append(
                                (
                                    abs(a * d1 + b * d2 - target),
                                    a + b,
                                    a,
                                    b,
                                )
                            )
                    best_error = min(row[0] for row in oracle)
                    best_total = min(
                        row[1]
                        for row in oracle
                        if abs(row[0] - best_error) <= 1e-12
                    )

                    assert actual_error == pytest.approx(best_error, abs=1e-12)
                    assert actual_a + actual_b == best_total
                    assert actual_a + actual_b <= drop_limit


def test_two_stock_plan_can_use_printed_volume_tolerance():
    em = _make_model(
        target_volume_nl=10.0,
        final_volume_nl=500.0,
        printed_volume_tolerance_nl=2.0,
    )
    em.set_metadata(allow_avoidable_target_grouping=True)
    em.add_additive(
        "R",
        [0.001, 0.21],
        "mM",
        1.0,
        max_stock_conc=10.0,
    )

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=True,
    )

    assert result["best"] is True
    assert result["effective_printed_volume_limit_nL"] == pytest.approx(12.0)
    assert result["worst_nonfill_nL"] == pytest.approx(11.0)
    assert result["two_stock_keys"] == [("R", None)]
    assert em.plans_per_option[("R", None)]["n_stocks"] == 2


def test_fixed_stock_above_max_stock_is_rejected():
    em = _make_model()
    em.add_additive("AddA", [0.1, 0.2], "mM", 10.0, forced_stock_conc=35.0, max_stock_conc=20.0)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert not result.get("best")
    assert "Fixed stock" in result["reason"]
    assert "exceeds max stock" in result["reason"]
    issues = result["issues_by_key"][("AddA", None)]
    assert {issue["field"] for issue in issues} == {"fixed_stock", "max_stock"}
    assert all(issue["code"] == "fixed_exceeds_max" for issue in issues)


def test_max_stock_issue_payload_reports_no_single_plan():
    em = _make_model(target_volume_nl=100.0, final_volume_nl=500.0)
    em.add_additive("AddA", [5.0, 10.0], "mM", 10.0, max_stock_conc=0.5)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert not result.get("best")
    issues = result["issues_by_key"][("AddA", None)]
    assert any(issue["field"] == "max_stock" and issue["code"] == "single_stock_volume_budget_exceeded" for issue in issues)


def test_fixed_stock_issue_payload_reports_unreachable_targets():
    em = _make_model(target_volume_nl=1000.0, final_volume_nl=1000.0)
    em.add_additive("AddA", [0.001, 0.149], "mM", 12.0, forced_stock_conc=35.0)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert not result.get("best")
    issues = result["issues_by_key"][("AddA", None)]
    assert any(issue["field"] == "fixed_stock" and issue["code"] == "fixed_unreachable_targets" for issue in issues)
    assert em.plans_per_option == {}
    assert em.get_stock_table_rows(include_fill=False) == []


def test_unreachable_fixed_stock_fails_closed_before_reaction_generation():
    em = _make_model(target_volume_nl=500.0, final_volume_nl=500.0)
    em.add_additive(
        "Tiny",
        [0.01, 0.2],
        "mM",
        10.0,
        forced_stock_conc=10.0,
    )

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=True,
    )

    assert not result.get("best")
    issue = next(
        issue
        for issue in result["issues_by_key"][("Tiny", None)]
        if issue["code"] == "fixed_unreachable_targets"
    )
    assert issue["unreachable_targets"] == [0.01]
    assert em.plans_per_option == {}
    with pytest.raises(ValueError, match="No stock plan exists"):
        em.generate_experiment()


def test_generation_and_runtime_iteration_reject_missing_target_mapping():
    em = _make_model(target_volume_nl=500.0, final_volume_nl=500.0)
    em.add_additive("Signal", [0.2], "mM", 10.0, forced_stock_conc=10.0)
    assert em.optimize_stock_solutions(allow_two=False)["best"]
    em.plans_per_option[("Signal", None)]["stocks"][0][
        "droplets_per_target"
    ] = {}

    with pytest.raises(ValueError, match="No reachable droplet mapping"):
        em.generate_experiment()
    with pytest.raises(ValueError, match="No reachable droplet mapping"):
        list(em.iter_reaction_stock_droplets())


def test_optimizer_rejects_two_stocks_with_colliding_runtime_ids():
    em = _make_model(target_volume_nl=10.0, final_volume_nl=500.0)
    em.set_metadata(allow_avoidable_target_grouping=True)
    em.add_additive(
        "Tiny",
        [0.0001, 0.0002],
        "mM",
        10.0,
        max_stock_conc=0.01,
    )

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=True,
    )

    assert not result.get("best")
    issue = result["issues_by_key"][("__stock_identity__", None)][0]
    assert issue["code"] == "duplicate_runtime_stock_id"
    assert issue["stock_id"] == "Tiny_0.01_mM"
    assert em.plans_per_option == {}


def test_stock_solution_manager_rejects_duplicate_runtime_id():
    manager = StockSolutionManager()
    manager.add_stock_solution("Tiny", 0.01, "mM")

    with pytest.raises(ValueError, match="Duplicate runtime stock ID"):
        manager.add_stock_solution("Tiny", 0.005, "mM")

    stocks = list(manager.get_all_stock_solutions())
    assert len(stocks) == 1
    assert float(stocks[0].concentration) == pytest.approx(0.01)


def test_fixed_stock_issue_payload_reports_volume_budget_context():
    em = _make_model(target_volume_nl=100.0, final_volume_nl=500.0)
    em.add_additive("AddA", [5.0, 10.0], "mM", 10.0, forced_stock_conc=1.0)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert not result.get("best")
    issue = next(
        issue
        for issue in result["issues_by_key"][("AddA", None)]
        if issue["code"] == "fixed_volume_budget_exceeded"
    )
    assert issue["field"] == "fixed_stock"
    assert issue["required_volume_nL"] > issue["allowed_volume_nL"]


def test_design_round_trips_allow_two_and_max_stock_settings():
    em = _make_model()
    em.set_metadata(allow_two_stock_solutions=True)
    em.add_additive("AddA", [0.1, 0.2], "mM", 10.0, max_stock_conc=12.5)

    payload = em.to_dict()

    restored = _make_model()
    restored.from_dict(payload)

    assert restored.metadata["allow_two_stock_solutions"] is True
    assert restored.factors[0].options[0].max_stock_conc == pytest.approx(12.5)


def test_uploaded_design_with_allow_two_skips_two_stock_search_when_seed_suffices(monkeypatch):
    df = pd.DataFrame(
        {
            "well_id": [f"A{i + 1}" for i in range(20)],
            "pmix mg/ml": [0.05] * 20,
            "ribosome uM": [0.07] * 20,
            "trna ug/ul": [0.09] * 20,
            "magnesium_acetate mM": [0.11] * 20,
        }
    )
    em = _make_model(target_volume_nl=500.0, final_volume_nl=500.0)
    em.set_uploaded_design_from_dataframe(
        df,
        units_default="",
        droplet_nL_default=10.0,
        starting_conc_default=0.0,
    )

    calls: list[tuple] = []

    def unexpected_two_stock(*args, **kwargs):
        calls.append((args, kwargs))
        return [], False

    monkeypatch.setattr(em, "_enumerate_two_stock_candidates_with_meta", unexpected_two_stock)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)

    assert result["best"]
    assert result["optimizer_seed_distinct_level_loss"] == 0
    assert result["distinct_level_loss"] == 0
    assert calls == []
    assert result["two_stock_keys"] == []
    assert result["two_stock_search_limited_keys"] == []


def test_uploaded_design_reports_max_stock_volume_budget_contributors():
    em = _make_model(target_volume_nl=700.0, final_volume_nl=1000.0)
    df = pd.DataFrame(
        {
            "well_id": ["A1"],
            "Reagent A mM": [4.0],
            "Reagent B mM": [4.0],
        }
    )
    em.set_uploaded_design_from_dataframe(
        df,
        units_default="",
        droplet_nL_default=10.0,
        starting_conc_default=0.0,
    )
    for factor in em.factors:
        factor.options[0].max_stock_conc = 10.0

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert not result.get("best")
    issue = result["issues_by_key"][("__uploaded_design__", None)][0]
    assert issue["code"] == "max_stock_volume_budget_exceeded"
    assert issue["field"] == "volume_budget"
    assert issue["row_label"] == "well A1"
    assert issue["required_volume_nL"] == pytest.approx(800.0)
    assert issue["allowed_volume_nL"] == pytest.approx(700.0)
    assert [row["label"] for row in issue["contributors"]] == ["Reagent A", "Reagent B"]
    assert "Largest contributors at max stock" in issue["message"]


def test_uploaded_design_volume_budget_uses_actual_rows_not_independent_factor_maxima():
    em = _make_model(target_volume_nl=600.0, final_volume_nl=1000.0)
    df = pd.DataFrame(
        {
            "well_id": ["A1", "A2"],
            "Reagent A mM": [5.0, 0.0],
            "Reagent B mM": [0.0, 5.0],
        }
    )
    em.set_uploaded_design_from_dataframe(
        df,
        units_default="",
        droplet_nL_default=10.0,
        starting_conc_default=0.0,
    )
    for factor in em.factors:
        factor.options[0].max_stock_conc = 10.0

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=False)

    assert result["best"]
    assert result["worst_nonfill_nL"] <= 600.0
    assert result["issues_by_key"] == {}


def test_uploaded_design_selected_plan_volume_budget_issue_reports_row_context():
    em = _make_model(target_volume_nl=550.0, final_volume_nl=1000.0)
    df = pd.DataFrame(
        {
            "well_id": ["B3"],
            "Reagent A mM": [5.0],
            "Reagent B mM": [5.0],
        }
    )
    em.set_uploaded_design_from_dataframe(
        df,
        units_default="",
        droplet_nL_default=10.0,
        starting_conc_default=0.0,
    )
    for factor in em.factors:
        factor.options[0].forced_stock_conc = 10.0
        factor.options[0].max_stock_conc = 20.0

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert not result.get("best")
    issue = result["issues_by_key"][("__uploaded_design__", None)][0]
    assert issue["code"] == "selected_plan_volume_budget_exceeded"
    assert issue["field"] == "volume_budget"
    assert issue["row_label"] == "well B3"
    assert issue["required_volume_nL"] == pytest.approx(1000.0)
    assert issue["allowed_volume_nL"] == pytest.approx(550.0)
    assert {row["label"] for row in issue["contributors"]} == {"Reagent A", "Reagent B"}
    assert all(row["volume_nL"] == pytest.approx(500.0) for row in issue["contributors"])
    assert "Selected stock plan exceeds" in issue["message"]


def test_printed_volume_tolerance_does_not_relax_stock_choice():
    em = _make_model(
        target_volume_nl=500.0,
        final_volume_nl=1000.0,
        printed_volume_tolerance_nl=10.0,
    )
    df = pd.DataFrame({"well_id": ["A1"], "Reagent A mM": [5.0]})
    em.set_uploaded_design_from_dataframe(
        df,
        units_default="",
        droplet_nL_default=10.0,
        starting_conc_default=0.0,
    )
    em.factors[0].options[0].max_stock_conc = 10.0

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=False)

    assert result.get("best")
    assert result["worst_nonfill_nL"] == pytest.approx(500.0)
    assert result["issues_by_key"] == {}
    stock_rows = em.get_stock_table_rows(include_fill=False)
    assert stock_rows[0]["stock_concentration"] == pytest.approx(10.0)


def test_uploaded_design_selected_plan_overage_within_tolerance_warns():
    em = _make_model(
        target_volume_nl=950.0,
        final_volume_nl=1000.0,
        printed_volume_tolerance_nl=50.0,
    )
    df = pd.DataFrame(
        {
            "well_id": ["B3"],
            "Reagent A mM": [5.0],
            "Reagent B mM": [5.0],
        }
    )
    em.set_uploaded_design_from_dataframe(
        df,
        units_default="",
        droplet_nL_default=10.0,
        starting_conc_default=0.0,
    )
    for factor in em.factors:
        factor.options[0].forced_stock_conc = 10.0
        factor.options[0].max_stock_conc = 20.0

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert result.get("best")
    assert result["worst_nonfill_nL"] == pytest.approx(1000.0)
    issues = result["issues_by_key"][("__uploaded_design__", None)]
    issue = next(row for row in issues if row["code"] == "selected_plan_volume_budget_within_tolerance")
    assert issue["severity"] == "warning"
    assert issue["row_label"] == "well B3"
    assert issue["required_volume_nL"] == pytest.approx(1000.0)
    assert issue["allowed_volume_nL"] == pytest.approx(950.0)
    assert issue["effective_allowed_volume_nL"] == pytest.approx(1000.0)
    assert issue["printed_volume_tolerance_nL"] == pytest.approx(50.0)
    assert issue["overage_nL"] == pytest.approx(50.0)
    assert {row["label"] for row in issue["contributors"]} == {"Reagent A", "Reagent B"}


def test_uploaded_design_selected_plan_overage_without_tolerance_fails():
    em = _make_model(
        target_volume_nl=950.0,
        final_volume_nl=1000.0,
        printed_volume_tolerance_nl=0.0,
    )
    df = pd.DataFrame(
        {
            "well_id": ["B3"],
            "Reagent A mM": [5.0],
            "Reagent B mM": [5.0],
        }
    )
    em.set_uploaded_design_from_dataframe(
        df,
        units_default="",
        droplet_nL_default=10.0,
        starting_conc_default=0.0,
    )
    for factor in em.factors:
        factor.options[0].forced_stock_conc = 10.0
        factor.options[0].max_stock_conc = 20.0

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert not result.get("best")
    issue = result["issues_by_key"][("__uploaded_design__", None)][0]
    assert issue["code"] == "selected_plan_volume_budget_exceeded"
    assert issue["required_volume_nL"] == pytest.approx(1000.0)
    assert issue["effective_allowed_volume_nL"] == pytest.approx(950.0)


def test_uploaded_design_printed_volume_tolerance_extends_final_volume_acceptance():
    em = _make_model(
        target_volume_nl=990.0,
        final_volume_nl=1000.0,
        printed_volume_tolerance_nl=50.0,
    )
    df = pd.DataFrame(
        {
            "well_id": ["B3"],
            "Reagent A mM": [5.0],
            "Reagent B mM": [5.1],
        }
    )
    em.set_uploaded_design_from_dataframe(
        df,
        units_default="",
        droplet_nL_default=10.0,
        starting_conc_default=0.0,
    )
    for factor in em.factors:
        factor.options[0].forced_stock_conc = 10.0
        factor.options[0].max_stock_conc = 20.0

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert result.get("best")
    assert result["effective_printed_volume_limit_nL"] == pytest.approx(1040.0)
    issue = result["issues_by_key"][("__uploaded_design__", None)][0]
    assert issue["code"] == "selected_plan_volume_budget_within_tolerance"
    assert issue["severity"] == "warning"
    assert issue["required_volume_nL"] == pytest.approx(1010.0)
    assert issue["allowed_volume_nL"] == pytest.approx(990.0)
    assert issue["effective_allowed_volume_nL"] == pytest.approx(1040.0)


def test_uploaded_accuracy_refinement_preserves_exact_row_feasibility():
    em = _make_model(target_volume_nl=30.0, final_volume_nl=500.0)
    em.set_metadata(
        allow_avoidable_target_grouping=True,
        allow_two_stock_solutions=True,
    )
    em.set_uploaded_design_from_dataframe(
        pd.DataFrame(
            {
                "A mM": [0.1, 0.2, 0.3],
                "B mM": [0.3, 0.5, 0.4],
            }
        ),
        units_default="",
        droplet_nL_default=10.0,
        starting_conc_default=0.0,
    )

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=60,
        two_max_refine=40,
        allow_two=True,
    )

    assert result["best"] is True
    assert result["worst_nonfill_nL"] == pytest.approx(30.0)
    stocks = {
        row["factor_name"]: row["stock_concentration"]
        for row in em.get_stock_table_rows(include_fill=False)
    }
    assert stocks == pytest.approx({"A": 7.5, "B": 15.0})
    em.generate_experiment()
    assert em.get_reactions_dataframe()["nonfill_volume_nL"].tolist() == pytest.approx(
        [20.0, 30.0, 30.0]
    )


def test_import_feasibility_report_flags_missing_max_stock():
    em = _make_model(target_volume_nl=500.0, final_volume_nl=1000.0)
    df = pd.DataFrame({"well_id": ["A1"], "Reagent A mM": [1.0], "Reagent B mM": [2.0]})
    max_df = pd.DataFrame({"reagent": ["Reagent A"], "stock_conc": [10.0], "units": ["mM"]})

    report = em.build_import_feasibility_report(
        df,
        max_stock_df=max_df,
        printed_volume_nL=500.0,
        final_volume_nL=1000.0,
    )

    assert any(issue["code"] == "missing_max_stock" and issue["reagent"] == "Reagent B" for issue in report["issues"])
    assert report["stock_rows"][1]["status"] == "Missing max stock"
    assert report["composition_rows"][0]["status"] == "Missing max stock"


def _two_stock_import_report():
    model = _make_model(target_volume_nl=9.0, final_volume_nl=450.0)
    design = pd.DataFrame({"R mM": [0.1, 0.2]})
    stocks = pd.DataFrame(
        {"reagent": ["R"], "stock_conc": [10.0], "units": ["mM"]}
    )
    report = model.build_import_feasibility_report(
        design,
        max_stock_df=stocks,
        printed_volume_nL=9.0,
        printed_volume_tolerance_nL=0.0,
        final_volume_nL=450.0,
        allow_two=True,
    )
    return design, report


def _build_two_stock_import_target(design):
    model = _make_model(target_volume_nl=9.0, final_volume_nl=450.0)
    model.set_metadata(allow_two_stock_solutions=True)
    model.set_uploaded_design_from_dataframe(
        design,
        units_default="",
        droplet_nL_default=9.0,
        starting_conc_default=0.0,
    )
    model.factors[0].options[0].max_stock_conc = 10.0
    return model


def test_import_feasibility_report_exposes_both_two_stock_legs_and_mappings():
    _design, report = _two_stock_import_report()

    assert report["ok"] is True
    assert [row["stock_leg_label"] for row in report["stock_rows"]] == [
        "Stock 1 of 2",
        "Stock 2 of 2",
    ]
    assert [row["ideal_stock_conc"] for row in report["stock_rows"]] == pytest.approx(
        [10.0, 5.0]
    )
    assert report["stock_rows"][0]["droplets_per_target"] == {0.1: 0, 0.2: 1}
    assert report["stock_rows"][1]["droplets_per_target"] == {0.1: 1, 0.2: 0}
    payload = report["stock_allocation_reuse_payload"]
    plan = payload["plans_per_option"][("R", None)]
    assert plan["n_stocks"] == 2
    assert plan["stocks"][0]["droplets_per_target"] == {0.1: 0, 0.2: 1}
    assert plan["stocks"][1]["droplets_per_target"] == {0.1: 1, 0.2: 0}


def test_unchanged_import_reuses_exactly_validated_two_stock_plan(monkeypatch):
    design, report = _two_stock_import_report()
    target = _build_two_stock_import_target(design)

    reused = target.install_stock_allocation_reuse_payload(
        report["stock_allocation_reuse_payload"]
    )
    monkeypatch.setattr(
        target,
        "optimize_stock_solutions",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("an unchanged import must not run the optimizer again")
        ),
    )
    target.generate_experiment()

    assert reused["reused"] is True
    assert reused["result"]["stock_allocation_reused_import_plan"] is True
    assert target.plans_per_option[("R", None)]["n_stocks"] == 2
    assert target.get_reactions_dataframe()["nonfill_volume_nL"].tolist() == pytest.approx(
        [9.0, 9.0]
    )


def test_import_reuse_still_rejects_exact_row_volume_above_design_limit():
    design, report = _two_stock_import_report()
    target = _build_two_stock_import_target(design)
    target.set_metadata(
        target_reaction_volume_nL=8.0,
        printed_volume_tolerance_nL=0.0,
    )
    payload = copy.deepcopy(report['stock_allocation_reuse_payload'])
    payload['input_fingerprint'] = target.stock_allocation_input_fingerprint()

    reused = target.install_stock_allocation_reuse_payload(payload)

    assert reused['reused'] is False
    assert reused['reason'] == 'stock_plan_validation_failed'
    assert 'exact row-volume limit' in reused['detail']
    assert target.plans_per_option == {}


def test_import_reuse_fingerprint_excludes_layout_and_counts_but_covers_stock_inputs():
    design, report = _two_stock_import_report()
    target = _build_two_stock_import_target(design)
    baseline = report["stock_allocation_input_fingerprint"]

    target.set_metadata(
        name="Renamed",
        replicates=7,
        randomize_assignments=True,
        random_seed=1234,
        start_col=4,
        start_row=3,
        fill_reagent_name="Buffer",
        fill_droplet_volume_nL=60.0,
    )
    assert target.stock_allocation_input_fingerprint() == baseline

    target.factors[0].options[0].max_stock_conc = 9.0
    assert target.stock_allocation_input_fingerprint() != baseline


def test_import_reuse_fingerprint_mismatch_preserves_existing_plan():
    design, report = _two_stock_import_report()
    target = _build_two_stock_import_target(design)
    target.plans_per_option[("sentinel", None)] = {"n_stocks": 1, "stocks": []}
    target.factors[0].options[0].max_stock_conc = 9.0

    reused = target.install_stock_allocation_reuse_payload(
        report["stock_allocation_reuse_payload"]
    )

    assert reused == {
        "reused": False,
        "reason": "stock_input_fingerprint_mismatch",
    }
    assert ("sentinel", None) in target.plans_per_option


def test_import_reuse_exact_validation_rejects_missing_mapping_and_restores_state():
    design, report = _two_stock_import_report()
    target = _build_two_stock_import_target(design)
    target.plans_per_option[("sentinel", None)] = {"n_stocks": 1, "stocks": []}
    payload = copy.deepcopy(report["stock_allocation_reuse_payload"])
    del payload["plans_per_option"][("R", None)]["stocks"][1][
        "droplets_per_target"
    ][0.1]
    payload["plan_fingerprint"] = target._canonical_payload_sha256(
        target._stock_allocation_plan_document(
            payload["plans_per_option"], payload["stock_rows"]
        )
    )

    reused = target.install_stock_allocation_reuse_payload(payload)

    assert reused["reused"] is False
    assert reused["reason"] == "stock_plan_validation_failed"
    assert "cannot reach every target" in reused["detail"]
    assert target.plans_per_option == {
        ("sentinel", None): {"n_stocks": 1, "stocks": []}
    }


def test_import_feasibility_report_marks_selected_overage_as_near_budget():
    em = _make_model(target_volume_nl=958.0, final_volume_nl=1008.0)
    df = pd.DataFrame({"well_id": ["B3"], "Reagent A mM": [5.0], "Reagent B mM": [5.0]})
    max_df = pd.DataFrame(
        {
            "reagent": ["Reagent A", "Reagent B"],
            "stock_conc": [10.0, 10.0],
            "units": ["mM", "mM"],
        }
    )

    report = em.build_import_feasibility_report(
        df,
        max_stock_df=max_df,
        printed_volume_nL=958.0,
        printed_volume_tolerance_nL=50.0,
        final_volume_nL=1008.0,
    )

    assert report["ok"] is True
    assert report["effective_printed_volume_limit_nL"] == pytest.approx(1008.0)
    row = report["composition_rows"][0]
    assert row["status"] == "Near budget"
    assert row["selected_plan_required_volume_nL"] == pytest.approx(1008.0)
    assert row["selected_plan_overage_nL"] == pytest.approx(50.0)
    assert row["selected_plan_contributors"]
    assert any(issue["code"] == "selected_plan_volume_budget_within_tolerance" for issue in report["issues"])


def test_import_feasibility_report_blocks_volume_overage_beyond_tolerance():
    em = _make_model(target_volume_nl=949.0, final_volume_nl=1000.0)
    df = pd.DataFrame({"well_id": ["B3"], "Reagent A mM": [5.0], "Reagent B mM": [5.0]})
    max_df = pd.DataFrame(
        {
            "reagent": ["Reagent A", "Reagent B"],
            "stock_conc": [10.0, 10.0],
            "units": ["mM", "mM"],
        }
    )

    report = em.build_import_feasibility_report(
        df,
        max_stock_df=max_df,
        printed_volume_nL=949.0,
        printed_volume_tolerance_nL=50.0,
        final_volume_nL=1000.0,
    )

    assert report["ok"] is False
    assert report["effective_printed_volume_limit_nL"] == pytest.approx(999.0)
    assert report["composition_rows"][0]["status"] == "Volume impossible"
    assert any(issue["severity"] == "error" for issue in report["issues"])


def test_import_max_stock_parser_accepts_labcraft_reagents_csv():
    em = _make_model(target_volume_nl=6700.0, final_volume_nl=10000.0)
    max_df = pd.read_csv("FreeRTOS-interface/Experiments/bnext_large_design/reagents.csv")

    payload = em._parse_import_max_stock_dataframe(max_df)

    assert not any(issue.get("reagent") == "water" for issue in payload["issues"])
    stocks_by_name = {row["name"]: row for row in payload["stocks"]}
    assert stocks_by_name["polyp"]["stock_conc"] == pytest.approx(500.0)
    assert stocks_by_name["trna"]["units"] == "ug/ul"
    assert "amino_acids" in stocks_by_name["aas"]["tokens"]
    assert "polyphosphate" in stocks_by_name["polyp"]["tokens"]


def test_import_max_stock_parser_reads_print_modes_from_reagents_csv():
    em = _make_model(target_volume_nl=5827.0, final_volume_nl=10000.0)
    max_df = pd.read_csv("FreeRTOS-interface/Experiments/bnext_260513_rep2/reagents.csv")

    payload = em._parse_import_max_stock_dataframe(max_df)

    stocks_by_name = {row["name"]: row for row in payload["stocks"]}
    assert stocks_by_name["polyp"]["printing_mode"] == "stream"
    assert stocks_by_name["polyp"]["droplet_nL"] == pytest.approx(60.0)
    assert stocks_by_name["hepes"]["printing_mode"] == "droplet"
    assert stocks_by_name["hepes"]["droplet_nL"] == pytest.approx(9.0)
    assert stocks_by_name["tcep"]["printing_mode"] == "droplet"


def test_import_max_stock_parser_warns_for_invalid_print_mode():
    em = _make_model(target_volume_nl=500.0, final_volume_nl=1000.0)
    max_df = pd.DataFrame(
        {
            "reagent": ["Reagent A", "Reagent B"],
            "stock_conc": [10.0, 20.0],
            "units": ["mM", "mM"],
            "print_mode": ["BadMode", ""],
        }
    )

    payload = em._parse_import_max_stock_dataframe(max_df)

    stocks_by_name = {row["name"]: row for row in payload["stocks"]}
    assert stocks_by_name["Reagent A"]["printing_mode"] == "droplet"
    assert stocks_by_name["Reagent A"]["droplet_nL"] == pytest.approx(9.0)
    assert stocks_by_name["Reagent B"]["printing_mode"] == "droplet"
    assert any(
        issue["code"] == "invalid_print_mode" and issue["reagent"] == "Reagent A"
        for issue in payload["issues"]
    )


def test_import_feasibility_report_uses_imported_stream_mode_and_canonical_matching():
    em = _make_model(target_volume_nl=6700.0, final_volume_nl=10000.0)
    design = pd.DataFrame({"well_id": ["A1"], "[PolyP] mM": [30.0]})
    max_df = pd.DataFrame(
        {
            "reagent": ["polyp"],
            "reagent_canonical_name": ["PolyP"],
            "stock_conc": [500.0],
            "units": ["mM"],
            "print_mode": ["Stream"],
        }
    )

    report = em.build_import_feasibility_report(
        design,
        max_stock_df=max_df,
        printed_volume_nL=6700.0,
        final_volume_nL=10000.0,
        allow_two=False,
    )

    row = report["stock_rows"][0]
    assert report["max_stock_by_reagent"]["[PolyP]"] == pytest.approx(500.0)
    assert row["matched_stock_name"] == "polyp"
    assert row["printing_mode"] == "stream"
    assert row["droplet_nL"] == pytest.approx(60.0)
    assert row["delta_per_drop"] == pytest.approx(row["ideal_stock_conc"] * 60.0 / 10000.0)
    assert report["stock_settings_by_reagent"]["[PolyP]"]["printing_mode"] == "stream"
    assert report["stock_settings_by_reagent"]["[PolyP]"]["droplet_nL"] == pytest.approx(60.0)


def test_bnext_260513_refinement_preserves_nominal_fit_when_available():
    design = pd.read_csv("FreeRTOS-interface/Experiments/bnext_260513/samples_titration_labcraft.csv")
    max_df = pd.read_csv("FreeRTOS-interface/Experiments/bnext_260513/reagents.csv")

    def report_for(tolerance_nl: float) -> dict:
        em = _make_model(target_volume_nl=5827.0, final_volume_nl=10000.0)
        return em.build_import_feasibility_report(
            design,
            max_stock_df=max_df,
            printed_volume_nL=5827.0,
            printed_volume_tolerance_nL=float(tolerance_nl),
            final_volume_nL=10000.0,
            allow_two=False,
        )

    report_50 = report_for(50.0)
    report_100 = report_for(100.0)
    for report in (report_50, report_100):
        assert report["ok"] is True
        assert not any(
            issue.get("code") == "selected_plan_volume_budget_within_tolerance"
            for issue in report["issues"]
        )
        assert all(
            row.get("status") == "OK" for row in report["composition_rows"]
        )

    stocks_50 = {
        row["reagent"]: row["ideal_stock_conc"]
        for row in report_50["stock_rows"]
    }
    stocks_100 = {
        row["reagent"]: row["ideal_stock_conc"]
        for row in report_100["stock_rows"]
    }
    assert stocks_100 == pytest.approx(stocks_50)


def test_bnext_basis_rep1_total_volume_tolerance_accepts_stream_quantization_overage():
    design = pd.read_csv(
        "FreeRTOS-interface/Experiments/bnext_basis_rep1/LABCRAFT_intermediate-mix-volume-fractions.csv"
    )
    max_df = pd.read_csv("FreeRTOS-interface/Experiments/bnext_basis_rep1/reagents_intermediate_info.csv")
    em = _make_model(target_volume_nl=10000.0, final_volume_nl=10000.0)

    report = em.build_import_feasibility_report(
        design,
        max_stock_df=max_df,
        printed_volume_nL=10000.0,
        printed_volume_tolerance_nL=150.0,
        final_volume_nL=10000.0,
        allow_two=False,
    )

    assert report["ok"] is True
    assert report["effective_printed_volume_limit_nL"] == pytest.approx(10150.0)
    g13_rows = [row for row in report["composition_rows"] if "G13" in row.get("wells", [])]
    assert len(g13_rows) == 1
    assert g13_rows[0]["status"] == "Near budget"
    assert g13_rows[0]["selected_plan_required_volume_nL"] == pytest.approx(10140.0)
    assert g13_rows[0]["selected_plan_overage_nL"] == pytest.approx(140.0)
    assert "K12" in g13_rows[0]["wells"]
    issue = next(
        issue
        for issue in report["issues"]
        if issue.get("code") == "selected_plan_volume_budget_within_tolerance"
    )
    assert issue["row_label"] == "well G13"
    assert issue["required_volume_nL"] == pytest.approx(10140.0)
    assert issue["effective_allowed_volume_nL"] == pytest.approx(10150.0)


def test_import_feasibility_report_accepts_labcraft_reagents_csv_for_bnext_design():
    design = pd.read_csv("FreeRTOS-interface/Experiments/bnext_large_design/samples_titration_labcraft.csv")
    max_df = pd.read_csv("FreeRTOS-interface/Experiments/bnext_large_design/reagents.csv")
    em = _make_model(target_volume_nl=6700.0, final_volume_nl=10000.0)

    report = em.build_import_feasibility_report(
        design,
        max_stock_df=max_df,
        printed_volume_nL=6700.0,
        final_volume_nL=10000.0,
        allow_two=False,
    )

    assert not any(issue.get("code") == "missing_max_stock" for issue in report["issues"])
    assert not any(issue.get("severity") == "error" for issue in report["issues"])
    assert not any(issue.get("reagent") == "water" for issue in report["issues"])
    assert report["max_stock_by_reagent"]["[PolyP]"] == pytest.approx(500.0)
    assert report["max_stock_by_reagent"]["[Amino Acids]"] == pytest.approx(6.0)


def test_bnext_large_design_polyp_500_mm_is_single_stock_feasible():
    design = pd.read_csv("FreeRTOS-interface/Experiments/bnext_large_design/samples_titration_labcraft.csv")
    stocks = pd.read_csv("FreeRTOS-interface/Experiments/bnext_large_design/stock_solutions.csv")

    em = ExperimentModel(prof=CURRENT_PROFILE)
    report = em.build_import_feasibility_report(
        design,
        max_stock_df=stocks,
        printed_volume_nL=6700.0,
        final_volume_nL=10000.0,
        allow_two=False,
    )

    assert not any(issue.get("severity") == "error" for issue in report["issues"])

    em.set_metadata(
        target_reaction_volume_nL=6700.0,
        final_reaction_volume_nL=10000.0,
        allow_two_stock_solutions=False,
    )
    em.set_uploaded_design_from_dataframe(
        design,
        units_default="",
        droplet_nL_default=10.0,
        starting_conc_default=0.0,
        source_path="samples_titration_labcraft.csv",
    )
    max_stock_by_reagent = report["max_stock_by_reagent"]
    for factor in em.factors:
        if factor.options and factor.name in max_stock_by_reagent:
            factor.options[0].max_stock_conc = max_stock_by_reagent[factor.name]

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=False)

    assert result.get("best")
    poly_rows = [
        row
        for row in em.get_stock_table_rows(include_fill=False)
        if row.get("factor_name") == "[PolyP]"
    ]
    assert poly_rows
    assert poly_rows[0]["stock_concentration"] <= 500.0 + 1e-12


def test_import_feasibility_report_surfaces_draft_optimizer_errors(monkeypatch):
    def fail_optimizer(self, *args, **kwargs):
        return {
            "best": None,
            "reason": "No feasible single-stock plan for additive 'Reagent A'.",
            "issues_by_key": {
                ("Reagent A", None): [
                    {
                        "field": "max_stock",
                        "severity": "error",
                        "code": "max_stock_no_single_plan",
                        "message": "Max stock 10 mM cannot support a single-stock plan for additive 'Reagent A'.",
                        "max_stock_conc": 10.0,
                    }
                ]
            },
        }

    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", fail_optimizer)
    em = _make_model(target_volume_nl=500.0, final_volume_nl=1000.0)
    df = pd.DataFrame({"well_id": ["A1"], "Reagent A mM": [1.0]})
    max_df = pd.DataFrame({"reagent": ["Reagent A"], "stock_conc": [10.0], "units": ["mM"]})

    report = em.build_import_feasibility_report(
        df,
        max_stock_df=max_df,
        printed_volume_nL=500.0,
        final_volume_nL=1000.0,
    )

    assert report["ok"] is False
    assert any(
        issue["code"] == "max_stock_no_single_plan" and issue["reagent"] == "Reagent A"
        for issue in report["issues"]
    )
    assert report["stock_rows"][0]["status"] == "Stock plan impossible"
    assert "single-stock plan" in report["stock_rows"][0]["recommendation"]


def test_import_feasibility_report_flags_unit_mismatch():
    em = _make_model(target_volume_nl=500.0, final_volume_nl=1000.0)
    df = pd.DataFrame({"well_id": ["A1"], "Reagent A mM": [1.0]})
    max_df = pd.DataFrame({"reagent": ["Reagent A"], "stock_conc": [10.0], "units": ["uM"]})

    report = em.build_import_feasibility_report(
        df,
        max_stock_df=max_df,
        printed_volume_nL=500.0,
        final_volume_nL=1000.0,
    )

    assert any(issue["code"] == "unit_mismatch" for issue in report["issues"])
    assert report["stock_rows"][0]["status"] == "Unit mismatch"
    assert report["composition_rows"][0]["status"] == "Unit mismatch"


def test_import_feasibility_report_collapses_duplicate_compositions():
    em = _make_model(target_volume_nl=500.0, final_volume_nl=1000.0)
    df = pd.DataFrame(
        {
            "well_id": ["A1", "A2", "B1"],
            "Reagent A mM": [1.0, 1.0, 2.0],
            "Reagent B mM": [2.0, 2.0, 3.0],
        }
    )
    max_df = pd.DataFrame(
        {
            "reagent": ["Reagent A", "Reagent B"],
            "stock_conc": [10.0, 10.0],
            "units": ["mM", "mM"],
        }
    )

    report = em.build_import_feasibility_report(
        df,
        max_stock_df=max_df,
        printed_volume_nL=500.0,
        final_volume_nL=1000.0,
    )

    assert len(report["composition_rows"]) == 2
    first = report["composition_rows"][0]
    assert first["count"] == 2
    assert first["wells"] == ["A1", "A2"]
    assert first["total_required_volume_nL"] == pytest.approx(300.0)


def test_two_stock_enumeration_honors_pair_cap(monkeypatch):
    em = _make_model(target_volume_nl=500.0, final_volume_nl=500.0)
    monkeypatch.setattr(
        em,
        "_candidate_single_stock_deltas",
        lambda *args, **kwargs: [float(i) for i in range(1, 11)],
    )

    evaluations: list[tuple] = []

    def unreachable_two_stock(*args, **kwargs):
        evaluations.append((args, kwargs))
        return {"reachable": False}

    monkeypatch.setattr(em, "_evaluate_two_stock_target", unreachable_two_stock)

    candidates, pair_limit_hit = em._enumerate_two_stock_candidates_with_meta(
        [1.0],
        10.0,
        "mM",
        final_volume_nL=500.0,
        volume_budget_nL=500.0,
        max_pairs=25,
    )

    assert candidates == []
    assert pair_limit_hit is True
    assert len(evaluations) == 25
