import json
from pathlib import Path
from types import SimpleNamespace

from Model import Model, ReactionComposition, Reagent, StockSolution


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


def _assigned_wells_by_reaction_order(well_plate):
    pairs = []
    for well in well_plate.get_all_wells():
        rxn = well.get_assigned_reaction()
        if rxn is not None:
            pairs.append((rxn.unique_id, well.well_id))
    return [
        well_id
        for _reaction_id, well_id in sorted(
            pairs,
            key=lambda item: int(item[0][1:]),
        )
    ]


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


def _first_assigned_reagent_named(well_plate, reagent_name, minimum_target=1):
    for well in well_plate.get_all_wells():
        rxn = well.get_assigned_reaction()
        if rxn is None:
            continue
        for sid, reagent in rxn.get_all_reagents().items():
            parsed_name = sid.rsplit("_", 2)[0]
            if parsed_name == reagent_name and reagent.get_target_droplets() >= minimum_target:
                return well, sid, reagent
    raise AssertionError(f"No assigned {reagent_name} reagent with target droplets")


def _prepare_saved_experiment(model):
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()
    Model.load_experiment_from_model(model, load_progress=False)
    return em


def _configure_stock_identity_design(em):
    em.factors = []
    em.add_additive("reagent_1", [0.0, 1.0], "mM", 9.1)
    em.set_metadata(
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=2000.0,
        final_reaction_volume_nL=2000.0,
        fill_reagent_name="Water",
        fill_printing_mode="stream",
        fill_droplet_volume_nL=60.0,
    )


def _configure_forced_stock_identity_design(em, forced_stock_conc):
    em.factors = []
    em.add_additive(
        "reagent_1",
        [0.0, 1.0],
        "mM",
        9.1,
        forced_stock_conc=forced_stock_conc,
    )
    em.set_metadata(
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=2000.0,
        final_reaction_volume_nL=2000.0,
        fill_reagent_name="Water",
        fill_printing_mode="stream",
        fill_droplet_volume_nL=60.0,
    )
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()


def _replace_progress_stock_id(payload, reagent_name, units, replacement_stock_id):
    replaced = False
    for well_id, entry in payload.items():
        if well_id == "__plate__":
            continue
        reagents = entry.get("reagents", {})
        for stock_id in list(reagents.keys()):
            try:
                parsed_name, _concentration, parsed_units = stock_id.rsplit("_", 2)
            except ValueError:
                continue
            if parsed_name == reagent_name and parsed_units == units:
                reagents[replacement_stock_id] = reagents.pop(stock_id)
                replaced = True
    assert replaced


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


def test_update_well_plate_uses_custom_well_selection_for_auto_assignment(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    selected = [
        "C1", "A1", "B2", "D1",
        "A2", "B1", "C2", "D2",
        "A3", "B3", "C3", "D3",
    ]
    em.set_metadata(start_row=999, start_col=999)
    em.set_well_selection(selected)
    expected_ids = [
        well.well_id
        for well in model.well_plate.zigzag_order(
            [model.well_plate.get_well(wid) for wid in model.well_plate.normalize_included_wells(selected)],
            fill_by="columns",
        )
    ][:em.get_number_of_reactions()]

    Model.update_well_plate(model)

    assert _assigned_wells_by_reaction_order(model.well_plate) == expected_ids


def test_update_well_plate_manual_assignments_override_printable_wells(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()

    explicit = [f"B{i + 1}" for i in range(em.get_number_of_reactions())]
    em._uploaded_well_ids = explicit
    em.set_well_selection(["A1"])
    Model.load_experiment_from_model(model, load_progress=False)

    em.set_well_selection(["A2"])
    Model.update_well_plate(model)

    assert _assigned_wells_by_reaction_order(model.well_plate) == explicit


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


def test_progress_status_treats_zero_added_file_as_unstarted(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    status = em.get_progress_status()

    assert status["exists"] is True
    assert status["readable"] is True
    assert status["has_printed_progress"] is False
    assert status["total_added_droplets"] == 0


def test_progress_status_detects_added_droplets_and_clear_resets_file(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    well, sid, _reagent = _first_assigned_reagent_with_target(model.well_plate)
    progress_path = Path(em.progress_file_path)
    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    payload[well.well_id]["reagents"][sid]["added_droplets"] = 2
    progress_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    status = em.get_progress_status()
    before_clear = em.clear_progress_for_design_edit()

    assert status["has_printed_progress"] is True
    assert status["total_added_droplets"] == 2
    assert before_clear["has_printed_progress"] is True
    assert json.loads(progress_path.read_text(encoding="utf-8")) == {}
    assert em.progress_data == {}


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


def test_load_progress_infers_saved_stock_concentration_before_runtime_build(
    experiment_model_factory,
):
    source_model = experiment_model_factory()
    source_em = source_model.experiment_model
    _configure_stock_identity_design(source_em)
    assert source_em.optimize_stock_solutions()["best"]
    source_em.generate_experiment()
    source_em.save_experiment()
    Model.load_experiment_from_model(source_model, load_progress=False)

    well, original_sid, original_reagent = _first_assigned_reagent_named(
        source_model.well_plate,
        "reagent_1",
    )
    saved_sid = "reagent_1_4.08_mM"
    assert original_sid != saved_sid

    progress_path = Path(source_em.progress_file_path)
    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    _replace_progress_stock_id(payload, "reagent_1", "mM", saved_sid)
    saved_target = original_reagent.get_target_droplets() + 1
    payload[well.well_id]["reagents"][saved_sid]["target_droplets"] = saved_target
    payload[well.well_id]["reagents"][saved_sid]["added_droplets"] = saved_target
    progress_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    reloaded_model = experiment_model_factory()
    reloaded_em = reloaded_model.experiment_model
    reloaded_em.load_experiment(source_em.experiment_file_path, source_em.experiment_dir_path)
    assert reloaded_em.factors[0].options[0].forced_stock_conc is None

    Model.load_experiment_from_model(reloaded_model, load_progress=True)

    reloaded_well = reloaded_model.well_plate.get_well(well.well_id)
    runtime_reagent = reloaded_well.get_assigned_reaction().get_reagent_by_id(saved_sid)
    assert runtime_reagent.get_target_droplets() == saved_target
    assert runtime_reagent.added_droplets == saved_target
    assert reloaded_em.factors[0].options[0].forced_stock_conc == 4.08

    design_payload = json.loads(Path(reloaded_em.experiment_file_path).read_text(encoding="utf-8"))
    reagent_option = next(
        factor["options"][0]
        for factor in design_payload["factors"]
        if factor["name"] == "reagent_1"
    )
    assert reagent_option["forced_stock_conc"] == 4.08


def test_load_progress_maps_changed_stock_id_by_unique_reagent_identity(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = _prepare_saved_experiment(model)

    well, sid, reagent = _first_assigned_reagent_with_target(model.well_plate)
    reagent_name, concentration, units = sid.rsplit("_", 2)
    saved_sid = f"{reagent_name}_{float(concentration) + 1.0:.2f}_{units}"
    progress_path = Path(em.progress_file_path)
    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    payload[well.well_id]["reagents"][saved_sid] = payload[well.well_id]["reagents"].pop(sid)
    payload[well.well_id]["reagents"][saved_sid]["added_droplets"] = 1
    progress_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    em.load_progress()

    runtime_reagent = well.get_assigned_reaction().get_reagent_by_id(sid)
    assert runtime_reagent.added_droplets == 1
    assert any(
        warning["code"] == "progress_stock_id_mapped"
        and warning["stock_id"] == saved_sid
        and warning["runtime_stock_id"] == sid
        for warning in em._last_progress_load_warnings
    )


def test_load_progress_ambiguous_stock_id_fallback_does_not_apply(tmp_path, experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    stock_a = StockSolution("Mix_1.00_mM", "Mix", 1.0, "mM")
    stock_b = StockSolution("Mix_2.00_mM", "Mix", 2.0, "mM")
    rxn = ReactionComposition("R1")
    rxn.add_reagent(stock_a, 5)
    rxn.add_reagent(stock_b, 6)
    well = SimpleNamespace(get_assigned_reaction=lambda: rxn)
    em._runtime_well_plate = SimpleNamespace(get_well=lambda well_id: well if well_id == "A1" else None)
    em.progress_file_path = str(tmp_path / "progress.json")
    Path(em.progress_file_path).write_text(
        json.dumps(
            {
                "A1": {
                    "reaction_id": "R1",
                    "reagents": {
                        "Mix_1.50_mM": {
                            "target_droplets": 9,
                            "added_droplets": 9,
                        }
                    },
                    "completed": False,
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    em.load_progress()

    assert rxn.get_reagent_by_id("Mix_1.00_mM").added_droplets == 0
    assert rxn.get_reagent_by_id("Mix_2.00_mM").added_droplets == 0
    assert any(
        warning["code"] == "progress_stock_id_ambiguous"
        and warning["stock_id"] == "Mix_1.50_mM"
        for warning in em._last_progress_load_warnings
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


def test_fresh_finish_after_unstarted_progress_keeps_edited_fixed_stock(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_forced_stock_identity_design(em, 4.08)
    Model.load_experiment_from_model(model, load_progress=False)
    assert em.get_progress_status()["has_printed_progress"] is False

    _configure_forced_stock_identity_design(em, 5.0)
    Model.load_experiment_from_model(model, load_progress=False)

    assert em.factors[0].options[0].forced_stock_conc == 5.0
    design_payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    reagent_option = next(
        factor["options"][0]
        for factor in design_payload["factors"]
        if factor["name"] == "reagent_1"
    )
    assert reagent_option["forced_stock_conc"] == 5.0

    progress_payload = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    progress_stock_ids = {
        stock_id
        for well_id, entry in progress_payload.items()
        if well_id != "__plate__"
        for stock_id in entry.get("reagents", {})
    }
    assert "reagent_1_5.00_mM" in progress_stock_ids
    assert "reagent_1_4.08_mM" not in progress_stock_ids


def test_reagent_over_target_is_complete_and_has_no_remaining_droplets():
    stock = StockSolution("SolA_1.00_mM", "SolA", 1.0, "mM")
    reagent = Reagent(stock, 5)
    reagent.added_droplets = 7

    assert reagent.get_remaining_droplets() == 0
    assert reagent.is_complete() is True
