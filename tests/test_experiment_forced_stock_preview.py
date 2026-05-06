import pandas as pd
import pytest

from Model import CURRENT_PROFILE, ExperimentModel, SingleStockPlan, TwoStockPlan


def _make_model(*, target_volume_nl=5000.0, final_volume_nl=5000.0):
    em = ExperimentModel(prof=CURRENT_PROFILE)
    em.set_metadata(
        target_reaction_volume_nL=float(target_volume_nl),
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


def test_forced_stock_preview_accepts_nearest_achievable_targets():
    targets = [
        0.001, 0.149, 0.192, 0.366, 0.553, 0.641, 0.737, 0.928, 1.122, 1.237,
        1.345, 1.447, 1.63, 1.713, 1.902, 2.029, 2.153, 2.271, 2.403, 2.51,
    ]
    em = _make_model()
    em.add_additive("AddA", targets, "mM", 12.0, forced_stock_conc=35.0)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)
    assert result["best"]

    preview = em.get_target_preview_map()[("AddA", None)]
    assert len(preview) == len(targets)
    assert em.get_unreachable_preview_map() == {("AddA", None): [0.001]}

    by_target = {row["requested_final"]: row for row in preview}
    assert by_target[0.001]["reachable"] is False
    assert by_target[0.001]["reason"] == "rounds_to_zero_drops"
    assert by_target[0.149]["reachable"] is True
    assert by_target[0.149]["droplets"] == 2
    assert by_target[0.149]["achieved_final"] == pytest.approx(0.168)
    assert by_target[2.51]["droplets"] == 30
    assert by_target[2.51]["achieved_final"] == pytest.approx(2.52)

    plan = em.plans_per_option[("AddA", None)]
    assert plan["n_stocks"] == 1
    assert plan["stocks"][0]["quantum"] == pytest.approx(1e-6)


def test_forced_stock_preview_respects_starting_concentration_and_zero_drop_guard():
    em = _make_model(target_volume_nl=1000.0, final_volume_nl=1000.0)
    em.add_additive("AddA", [0.5, 0.54, 0.7], "mM", 10.0, starting_conc=0.5, forced_stock_conc=10.0)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=True)
    assert result["best"]

    preview = em.get_target_preview_map()[("AddA", None)]
    by_target = {row["requested_final"]: row for row in preview}

    assert by_target[0.5]["reachable"] is True
    assert by_target[0.5]["droplets"] == 0
    assert by_target[0.5]["achieved_final"] == pytest.approx(0.5)

    assert by_target[0.54]["reachable"] is False
    assert by_target[0.54]["reason"] == "rounds_to_zero_drops"
    assert by_target[0.54]["achieved_final"] == pytest.approx(0.5)

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


def test_max_stock_bound_filters_single_stock_candidates():
    em = _make_model(target_volume_nl=500.0, final_volume_nl=500.0)
    candidates = em._enumerate_single_stock_candidates(
        [0.1, 0.2],
        10.0,
        "mM",
        final_volume_nL=500.0,
        max_refine=10,
        max_stock_conc=0.4,
    )
    assert candidates == []


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
    em.add_additive("AddA", [0.001, 0.149], "mM", 12.0, forced_stock_conc=35.0)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Fixed-stock plans should skip accuracy refinement scoring")

    monkeypatch.setattr(em, "_score_single_stock_plan", fail_if_called)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=True)

    assert result["best"]
    plan = em.plans_per_option[("AddA", None)]
    assert plan["stocks"][0]["stock_concentration"] == pytest.approx(35.0)
    issues = result["issues_by_key"][("AddA", None)]
    assert any(issue["field"] == "fixed_stock" and issue["code"] == "fixed_unreachable_targets" for issue in issues)


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
    assert em.plans_per_option[("AddA", None)]["n_stocks"] == 2


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
    assert any(issue["field"] == "max_stock" and issue["code"] == "max_stock_no_single_plan" for issue in issues)


def test_fixed_stock_issue_payload_reports_unreachable_targets():
    em = _make_model(target_volume_nl=1000.0, final_volume_nl=1000.0)
    em.add_additive("AddA", [0.001, 0.149], "mM", 12.0, forced_stock_conc=35.0)

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert result["best"]
    issues = result["issues_by_key"][("AddA", None)]
    assert any(issue["field"] == "fixed_stock" and issue["code"] == "fixed_unreachable_targets" for issue in issues)


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


def test_uploaded_design_with_allow_two_skips_two_stock_search_when_single_stock_suffices(monkeypatch):
    em = _make_model(target_volume_nl=500.0, final_volume_nl=500.0)
    df = pd.DataFrame(
        {
            "well_id": [f"A{i + 1}" for i in range(20)],
            "pmix mg/ml": [round(0.05 * (i + 1), 3) for i in range(20)],
            "ribosome uM": [round(0.07 * (i + 1), 3) for i in range(20)],
            "trna ug/ul": [round(0.09 * (i + 1), 3) for i in range(20)],
            "magnesium_acetate mM": [round(0.11 * (i + 1), 3) for i in range(20)],
        }
    )
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
    assert "Selected stock plan exceeds" in issue["message"]


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
