import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from Model import ExperimentModel


class _SignalRecorder:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def test_refresh_runtime_after_plan_change_rebinds_keys_and_emits_well_refresh():
    stock_updated = _SignalRecorder()
    well_state_changed = _SignalRecorder()
    write_calls = []
    rebind_calls = []

    em = SimpleNamespace(
        _has_runtime_assignments=lambda: True,
        _rebind_runtime_assignments_to_current_plans=lambda: rebind_calls.append(True) or True,
        write_keys_now=lambda: write_calls.append(True),
        stock_updated=stock_updated,
        _runtime_well_plate=SimpleNamespace(well_state_changed_signal=well_state_changed),
    )
    em._refresh_runtime_after_plan_change = (
        ExperimentModel._refresh_runtime_after_plan_change.__get__(em, ExperimentModel)
    )

    refreshed = em._refresh_runtime_after_plan_change(write_keys_if_assigned=True)

    assert refreshed is True
    assert rebind_calls == [True]
    assert write_calls == [True]
    assert stock_updated.calls == [()]
    assert well_state_changed.calls == [("all",)]


def test_apply_droplet_volume_for_option_refreshes_runtime_after_apply():
    refresh_calls = []
    option = SimpleNamespace(
        name="glycerol",
        droplet_nL=10.0,
        units="mM",
        targets=[0.5],
        starting_conc=0.0,
    )
    factor = SimpleNamespace(name="glycerol", kind="additive", options=[option])
    stock = {
        "stock_concentration": 10.0,
        "droplet_volume_nL": 10.0,
        "units": "mM",
        "droplets_per_target": {},
    }
    stock_row = {
        "factor_name": "glycerol",
        "option_name": "",
        "stock_concentration": 10.0,
        "droplet_volume_nL": 10.0,
    }

    em = SimpleNamespace(
        plans_per_option={("glycerol", None): {"stocks": [stock], "n_stocks": 1}},
        factors=[factor],
        metadata={"final_reaction_volume_nL": 500.0},
        _stock_rows_cache=[stock_row],
        _normalize_target_key=lambda value: round(float(value), 6),
        _refresh_plan_preview_maps=lambda: None,
        generate_experiment=lambda: None,
        _refresh_runtime_after_plan_change=lambda **kwargs: refresh_calls.append(kwargs) or True,
        _last_worst_nonfill_volume_nL=0.0,
        unsaved_changes=False,
    )
    em._evaluate_single_forced_target = (
        ExperimentModel._evaluate_single_forced_target.__get__(em, ExperimentModel)
    )
    em.apply_droplet_volume_for_option = (
        ExperimentModel.apply_droplet_volume_for_option.__get__(em, ExperimentModel)
    )

    result = em.apply_droplet_volume_for_option("glycerol", None, 12.0, write_keys_if_assigned=False)

    assert refresh_calls == [{"write_keys_if_assigned": False}]
    assert option.droplet_nL == 12.0
    assert option.intended_droplet_nL == 10.0
    assert option.forced_stock_conc == 10.0
    assert stock["droplet_volume_nL"] == 12.0
    assert stock_row["droplet_volume_nL"] == 12.0
    assert em.unsaved_changes is True
    assert result["stock_row_updated"] is True
    assert result["saved_experiment"] is False


def test_apply_fill_droplet_volume_refreshes_runtime_after_apply():
    refresh_calls = []
    generate_calls = []

    em = SimpleNamespace(
        metadata={"fill_droplet_volume_nL": 10.0},
        preview_fill_requantized=lambda new_fill: {
            "total_drops_old": 50,
            "total_drops_new": 42,
            "total_drops_delta": -8,
        },
        generate_experiment=lambda: generate_calls.append(True),
        _refresh_runtime_after_plan_change=lambda **kwargs: refresh_calls.append(kwargs) or True,
        unsaved_changes=False,
    )
    em.apply_fill_droplet_volume = (
        ExperimentModel.apply_fill_droplet_volume.__get__(em, ExperimentModel)
    )

    result = em.apply_fill_droplet_volume(12.0, write_keys_if_assigned=True)

    assert generate_calls == [True]
    assert refresh_calls == [{"write_keys_if_assigned": True}]
    assert em.metadata["intended_fill_droplet_volume_nL"] == 10.0
    assert em.unsaved_changes is True
    assert result["new_fill_nL"] == 12.0
    assert result["total_drops_new"] == 42
    assert result["saved_experiment"] is False


def test_apply_droplet_volume_for_option_rejects_volume_outside_printing_mode_range():
    option = SimpleNamespace(
        name="glycerol",
        droplet_nL=10.0,
        units="mM",
        targets=[0.5],
        starting_conc=0.0,
        printing_mode="droplet",
    )
    factor = SimpleNamespace(name="glycerol", kind="additive", options=[option])
    stock = {
        "stock_concentration": 10.0,
        "droplet_volume_nL": 10.0,
        "units": "mM",
        "droplets_per_target": {},
    }

    em = SimpleNamespace(
        plans_per_option={("glycerol", None): {"stocks": [stock], "n_stocks": 1}},
        factors=[factor],
        metadata={"final_reaction_volume_nL": 500.0},
        _stock_rows_cache=[],
        _normalize_target_key=lambda value: round(float(value), 6),
        _refresh_plan_preview_maps=lambda: None,
        generate_experiment=lambda: None,
        _refresh_runtime_after_plan_change=lambda **kwargs: True,
        _last_worst_nonfill_volume_nL=0.0,
        unsaved_changes=False,
    )
    em._evaluate_single_forced_target = (
        ExperimentModel._evaluate_single_forced_target.__get__(em, ExperimentModel)
    )
    em.apply_droplet_volume_for_option = (
        ExperimentModel.apply_droplet_volume_for_option.__get__(em, ExperimentModel)
    )

    with pytest.raises(ValueError, match="outside the allowed range for droplet mode"):
        em.apply_droplet_volume_for_option("glycerol", None, 60.0, write_keys_if_assigned=False)


def test_apply_fill_droplet_volume_rejects_volume_outside_fill_printing_mode_range():
    em = SimpleNamespace(
        metadata={"fill_droplet_volume_nL": 60.0, "fill_printing_mode": "stream"},
        preview_fill_requantized=lambda new_fill: {
            "total_drops_old": 50,
            "total_drops_new": 42,
            "total_drops_delta": -8,
        },
        generate_experiment=lambda: None,
        _refresh_runtime_after_plan_change=lambda **kwargs: True,
        unsaved_changes=False,
    )
    em.apply_fill_droplet_volume = (
        ExperimentModel.apply_fill_droplet_volume.__get__(em, ExperimentModel)
    )

    with pytest.raises(ValueError, match="outside the allowed range for stream mode"):
        em.apply_fill_droplet_volume(10.0, write_keys_if_assigned=True)


def _configure_calibrated_volume_design(em):
    em.factors = []
    em.add_additive(
        "glycerol",
        [0.9],
        "mM",
        10.0,
        forced_stock_conc=10.0,
        printing_mode="droplet",
    )
    em.set_metadata(
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()


def _first_option_payload(payload, factor_name):
    for factor in payload["factors"]:
        if factor["name"] == factor_name:
            return factor["options"][0]
    raise AssertionError(f"Factor {factor_name!r} not found")


def _first_saved_target(em, factor_name):
    stock = em.plans_per_option[(factor_name, None)]["stocks"][0]
    return next(iter(stock["droplets_per_target"].values()))


def test_apply_droplet_volume_for_option_persists_effective_and_intended_volume(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)

    result = em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        15.0,
        write_keys_if_assigned=False,
    )

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    option = _first_option_payload(payload, "glycerol")
    assert option["droplet_nL"] == 15.0
    assert option["intended_droplet_nL"] == 10.0
    assert option["forced_stock_conc"] == result["stock_concentration"]
    assert result["saved_experiment"] is True
    assert em.unsaved_changes is False


def test_apply_fill_droplet_volume_persists_effective_and_intended_volume(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)

    result = em.apply_fill_droplet_volume(12.0, write_keys_if_assigned=False)

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    assert payload["metadata"]["fill_droplet_volume_nL"] == 12.0
    assert payload["metadata"]["intended_fill_droplet_volume_nL"] == 10.0
    assert result["saved_experiment"] is True
    assert em.unsaved_changes is False


def test_reloading_after_calibrated_volume_apply_uses_saved_effective_counts(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    original_target = _first_saved_target(em, "glycerol")
    original_stock_concentration = em.plans_per_option[("glycerol", None)]["stocks"][0]["stock_concentration"]

    em.apply_droplet_volume_for_option("glycerol", None, 15.0, write_keys_if_assigned=False)
    calibrated_target = _first_saved_target(em, "glycerol")
    calibrated_stock_concentration = em.plans_per_option[("glycerol", None)]["stocks"][0]["stock_concentration"]
    assert calibrated_target != original_target
    assert calibrated_stock_concentration == original_stock_concentration

    reloaded_model = experiment_model_factory()
    reloaded = reloaded_model.experiment_model
    reloaded.load_experiment(em.experiment_file_path, em.experiment_dir_path)

    assert reloaded.factors[0].options[0].droplet_nL == 15.0
    assert reloaded.factors[0].options[0].intended_droplet_nL == 10.0
    assert reloaded.factors[0].options[0].forced_stock_conc == calibrated_stock_concentration
    assert _first_saved_target(reloaded, "glycerol") == calibrated_target
