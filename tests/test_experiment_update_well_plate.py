import json
from pathlib import Path

from Model import Model, Reagent, StockSolution


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


def _first_assigned_reagent_with_target(well_plate, minimum_target=1):
    for well in well_plate.get_all_wells():
        rxn = well.get_assigned_reaction()
        if rxn is None:
            continue
        for sid, reagent in rxn.get_all_reagents().items():
            if reagent.get_target_droplets() >= minimum_target:
                return well, sid, reagent
    raise AssertionError("No assigned reaction reagent with target droplets")


def _prepare_saved_experiment(model):
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()
    Model.load_experiment_from_model(model, load_progress=False)
    return em


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


def test_reloaded_experiment_applies_saved_progress_to_runtime(experiment_model_factory):
    source_model = experiment_model_factory()
    source_em = _prepare_saved_experiment(source_model)

    well, sid, reagent = _first_assigned_reagent_with_target(source_model.well_plate, minimum_target=2)
    target = reagent.get_target_droplets()
    added = 1

    progress_path = Path(source_em.progress_file_path)
    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    payload[well.well_id]["reagents"][sid]["added_droplets"] = added
    progress_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    reloaded_model = experiment_model_factory()
    reloaded_em = reloaded_model.experiment_model
    reloaded_em.load_experiment(source_em.experiment_file_path, source_em.experiment_dir_path)
    Model.load_experiment_from_model(reloaded_model, load_progress=True)

    reloaded_well = reloaded_model.well_plate.get_well(well.well_id)
    runtime_reagent = reloaded_well.get_assigned_reaction().get_reagent_by_id(sid)
    assert runtime_reagent.added_droplets == added
    assert runtime_reagent.get_remaining_droplets() == target - added

    disk_payload = json.loads(progress_path.read_text(encoding="utf-8"))
    assert disk_payload[well.well_id]["reagents"][sid]["added_droplets"] == added


def test_load_progress_restores_saved_targets_when_regenerated_target_differs(
    experiment_model_factory,
):
    source_model = experiment_model_factory()
    source_em = _prepare_saved_experiment(source_model)

    well, sid, reagent = _first_assigned_reagent_with_target(source_model.well_plate)
    regenerated_target = reagent.get_target_droplets()
    saved_target = regenerated_target + 3
    saved_added = saved_target + 1

    progress_path = Path(source_em.progress_file_path)
    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    payload[well.well_id]["reagents"][sid]["target_droplets"] = saved_target
    payload[well.well_id]["reagents"][sid]["added_droplets"] = saved_added
    progress_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    reloaded_model = experiment_model_factory()
    reloaded_em = reloaded_model.experiment_model
    reloaded_em.load_experiment(source_em.experiment_file_path, source_em.experiment_dir_path)
    Model.load_experiment_from_model(reloaded_model, load_progress=True)

    reloaded_well = reloaded_model.well_plate.get_well(well.well_id)
    runtime_reagent = reloaded_well.get_assigned_reaction().get_reagent_by_id(sid)
    assert runtime_reagent.get_target_droplets() == saved_target
    assert runtime_reagent.added_droplets == saved_added
    assert runtime_reagent.get_remaining_droplets() == 0
    assert runtime_reagent.is_complete() is True
    assert any(
        warning["well_id"] == well.well_id
        and warning["stock_id"] == sid
        and warning["saved_target_droplets"] == saved_target
        and warning["runtime_target_droplets"] == regenerated_target
        for warning in reloaded_em._last_progress_load_warnings
    )


def test_explicit_fresh_load_overwrites_saved_progress(experiment_model_factory):
    source_model = experiment_model_factory()
    source_em = _prepare_saved_experiment(source_model)

    well, sid, _reagent = _first_assigned_reagent_with_target(source_model.well_plate)
    progress_path = Path(source_em.progress_file_path)
    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    payload[well.well_id]["reagents"][sid]["added_droplets"] = 1
    progress_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    reloaded_model = experiment_model_factory()
    reloaded_em = reloaded_model.experiment_model
    reloaded_em.load_experiment(source_em.experiment_file_path, source_em.experiment_dir_path)
    Model.load_experiment_from_model(reloaded_model, load_progress=False)

    reloaded_well = reloaded_model.well_plate.get_well(well.well_id)
    runtime_reagent = reloaded_well.get_assigned_reaction().get_reagent_by_id(sid)
    assert runtime_reagent.added_droplets == 0

    disk_payload = json.loads(progress_path.read_text(encoding="utf-8"))
    assert disk_payload[well.well_id]["reagents"][sid]["added_droplets"] == 0


def test_reagent_over_target_is_complete_and_has_no_remaining_droplets():
    stock = StockSolution("SolA_1.00_mM", "SolA", 1.0, "mM")
    reagent = Reagent(stock, 5)
    reagent.added_droplets = 7

    assert reagent.get_remaining_droplets() == 0
    assert reagent.is_complete() is True
