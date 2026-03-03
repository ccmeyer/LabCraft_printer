import json
from pathlib import Path

from Model import Model


def _configure_design(em):
    em.factors = []
    em.add_additive("AddA", [0.5, 1.0], "mM", 10.0, starting_conc=0.2)
    em.add_choice_group("Choice")
    em.add_choice_option("Choice", "Opt1", [0.0, 0.5], "mM", 10.0, starting_conc=0.1)
    em.add_choice_option("Choice", "Opt2", [0.0, 0.5], "mM", 10.0, starting_conc=0.05)
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


def _assigned_well_ids(well_plate):
    return [w.well_id for w in well_plate.get_all_wells() if w.get_assigned_reaction() is not None]


def _first_assigned_reagent(well_plate):
    for well in well_plate.get_all_wells():
        rxn = well.get_assigned_reaction()
        if rxn is not None:
            sid, reagent = next(iter(rxn.get_all_reagents().items()))
            return well, sid, reagent
    raise AssertionError("No assigned reaction")


def test_update_well_plate_reassigns_without_wiping_exclusions(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    before_ids = _assigned_well_ids(model.well_plate)
    before_excluded = {"A1", "B1"}
    model.well_plate.excluded_wells = set(before_excluded)
    before_cal = dict(model.well_plate.calibrations)

    em.set_metadata(start_row=2, start_col=1)
    Model.update_well_plate(model)

    after_ids = _assigned_well_ids(model.well_plate)
    assert before_ids != after_ids
    assert model.well_plate.excluded_wells == before_excluded
    assert dict(model.well_plate.calibrations) == before_cal


def test_load_progress_applies_added_droplets(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    well, sid, _reagent = _first_assigned_reagent(model.well_plate)
    progress_path = Path(em.progress_file_path)
    data = json.loads(progress_path.read_text(encoding="utf-8"))
    data.pop("__plate__", None)
    data[well.well_id]["reagents"][sid]["added_droplets"] = 1
    progress_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    em.load_progress()
    runtime_reagent = well.get_assigned_reaction().get_reagent_by_id(sid)
    assert runtime_reagent.added_droplets == 1


def test_load_progress_skips_unknown_reagent_ids_gracefully(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    well, sid, _reagent = _first_assigned_reagent(model.well_plate)
    progress_path = Path(em.progress_file_path)
    data = json.loads(progress_path.read_text(encoding="utf-8"))
    data.pop("__plate__", None)
    data[well.well_id]["reagents"][sid]["added_droplets"] = 2
    data[well.well_id]["reagents"]["Unknown_1.00_mM"] = {
        "name": "Unknown",
        "concentration": 1.0,
        "units": "mM",
        "target_droplets": 1,
        "added_droplets": 99,
    }
    progress_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    em.load_progress()
    runtime_reagent = well.get_assigned_reaction().get_reagent_by_id(sid)
    assert runtime_reagent.added_droplets == 2
