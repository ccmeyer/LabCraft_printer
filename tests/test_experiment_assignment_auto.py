import pytest

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
