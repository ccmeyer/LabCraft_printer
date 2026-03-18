import pandas as pd
import pytest

from Model import CURRENT_PROFILE, ExperimentModel


def _make_model(*, target_volume_nl=5000.0, final_volume_nl=5000.0):
    em = ExperimentModel(prof=CURRENT_PROFILE)
    em.set_metadata(
        target_reaction_volume_nL=float(target_volume_nl),
        final_reaction_volume_nL=float(final_volume_nl),
    )
    return em


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
