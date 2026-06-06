import pytest
import random
from unittest.mock import Mock

from Model import Model


def _configure_design_basic(em):
    em.factors = []
    em.add_additive("AddA", [0.5, 1.0], "mM", 10.0, starting_conc=0.2)
    em.add_choice_group("Choice")
    em.add_choice_option("Choice", "Opt1", [0.0, 0.5], "mM", 10.0, starting_conc=0.1)
    em.add_choice_option("Choice", "Opt2", [0.0, 0.5], "mM", 10.0, starting_conc=0.05)
    em.set_metadata(
        randomize_assignments=False,
        random_seed=None,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )


def _well_to_reaction_map(well_plate):
    out = {}
    for well in well_plate.get_all_wells():
        rxn = well.get_assigned_reaction()
        if rxn is not None:
            out[well.well_id] = rxn.unique_id
    return out


def _assigned_wells_by_reaction_order(well_plate):
    assigned = _well_to_reaction_map(well_plate)
    return [
        well_id
        for well_id, reaction_id in sorted(
            assigned.items(),
            key=lambda item: int(item[1][1:]),
        )
    ]


def test_auto_assignment_maps_reactions_to_expected_wells(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design_basic(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()

    expected_n = em.get_number_of_reactions()
    expected_wells = model.well_plate.get_available_wells(
        fill_by="columns",
        start_row=em.get_start_row(),
        start_col=em.get_start_col(),
    )[:expected_n]
    expected_ids = [w.well_id for w in expected_wells]

    Model.load_experiment_from_model(model, load_progress=False)

    assigned = _well_to_reaction_map(model.well_plate)
    assert len(assigned) == expected_n
    assert list(assigned.keys()) == expected_ids


def test_auto_assignment_uses_custom_well_selection_and_ignores_start_offset(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design_basic(em)
    em.set_metadata(start_row=999, start_col=999)
    selected = [
        "C1", "A1", "B2", "D1",
        "A2", "B1", "C2", "D2",
        "A3", "B3", "C3", "D3",
    ]
    em.set_well_selection(selected)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()

    expected_n = em.get_number_of_reactions()
    expected_ids = [
        well.well_id
        for well in model.well_plate.get_available_wells(
            fill_by="columns",
            included_wells=selected,
        )
    ][:expected_n]

    Model.load_experiment_from_model(model, load_progress=False)

    assert _assigned_wells_by_reaction_order(model.well_plate) == expected_ids


def test_auto_assignment_custom_well_selection_respects_exclusions(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    em.factors = []
    em.add_additive("AddA", [0.1, 0.2], "mM", 10.0)
    em.set_metadata(randomize_assignments=False, start_row=0, start_col=0, replicates=1)
    em.set_well_selection(["A1", "A2"])
    model.well_plate.excluded_wells.add("A1")
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()

    with pytest.raises(ValueError, match="Not enough available wells"):
        Model.load_experiment_from_model(model, load_progress=False)


def test_auto_assignment_invalid_custom_selection_fails_before_clearing_experiment(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design_basic(em)
    em.set_well_selection(["Z99"])
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    model.clear_experiment = Mock()

    with pytest.raises(ValueError, match="Included well selection is invalid"):
        Model.load_experiment_from_model(model, load_progress=False)

    model.clear_experiment.assert_not_called()


def test_auto_assignment_respects_random_seed_when_enabled(experiment_model_factory):
    def build_mapping(seed):
        model = experiment_model_factory()
        em = model.experiment_model
        em.factors = []
        em.add_additive("AddA", [0.1, 0.2, 0.3, 0.4], "mM", 10.0, starting_conc=0.0)
        em.add_choice_group("Choice")
        em.add_choice_option("Choice", "Opt1", [0.0, 0.5, 1.0], "mM", 10.0, starting_conc=0.0)
        em.add_choice_option("Choice", "Opt2", [0.0, 0.5, 1.0], "mM", 10.0, starting_conc=0.0)
        em.set_metadata(randomize_assignments=True, random_seed=seed, start_row=0, start_col=0, replicates=1)
        assert em.optimize_stock_solutions()["best"]
        em.generate_experiment()
        Model.load_experiment_from_model(model, load_progress=False)
        return _well_to_reaction_map(model.well_plate)

    map_a = build_mapping(1234)
    map_b = build_mapping(1234)
    map_c = build_mapping(4321)

    assert map_a == map_b
    assert map_a != map_c


def test_auto_assignment_fails_when_reactions_exceed_available_wells(experiment_model_factory):
    tiny_plate = [
        {
            "name": "tiny-1x1",
            "rows": 1,
            "columns": 1,
            "spacing": 10,
            "default": True,
            "calibrations": {},
        }
    ]
    model = experiment_model_factory(plate_data_override=tiny_plate)
    em = model.experiment_model
    em.factors = []
    em.add_additive("AddA", [0.1, 0.2], "mM", 10.0)
    em.set_metadata(randomize_assignments=False, start_row=0, start_col=0, replicates=1)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()

    with pytest.raises(ValueError, match="Not enough available wells"):
        Model.load_experiment_from_model(model, load_progress=False)


def test_load_experiment_randomization_does_not_mutate_global_rng(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    em.factors = []
    em.add_additive("AddA", [0.1, 0.2, 0.3], "mM", 10.0, starting_conc=0.0)
    em.add_choice_group("Choice")
    em.add_choice_option("Choice", "Opt1", [0.0, 0.5], "mM", 10.0, starting_conc=0.0)
    em.add_choice_option("Choice", "Opt2", [0.0, 0.5], "mM", 10.0, starting_conc=0.0)
    em.set_metadata(randomize_assignments=True, random_seed=1234, start_row=0, start_col=0, replicates=1)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()

    random.seed(2026)
    expected_rng = random.Random(2026)
    pre_actual = [random.random() for _ in range(3)]
    pre_expected = [expected_rng.random() for _ in range(3)]
    assert pre_actual == pytest.approx(pre_expected, abs=1e-12)

    Model.load_experiment_from_model(model, load_progress=False)

    post_actual = [random.random() for _ in range(3)]
    post_expected = [expected_rng.random() for _ in range(3)]
    assert post_actual == pytest.approx(post_expected, abs=1e-12)
