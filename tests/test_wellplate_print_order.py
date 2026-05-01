from Model import ReactionComposition


def _assign_reactions(well_plate, well_ids):
    for idx, well_id in enumerate(well_ids):
        well_plate.get_well(well_id).assign_reaction(ReactionComposition(f"R{idx + 1}"))


def test_reaction_wells_keep_serpentine_order_by_default(experiment_model_factory):
    model = experiment_model_factory()
    well_plate = model.well_plate
    _assign_reactions(well_plate, ["A1", "A2", "B1", "B2"])

    ordered_ids = [
        well.well_id
        for well in well_plate.get_all_wells_with_reactions(fill_by="rows")
    ]

    assert ordered_ids == ["A1", "A2", "B2", "B1"]


def test_reaction_wells_can_use_row_major_print_order(experiment_model_factory):
    model = experiment_model_factory()
    well_plate = model.well_plate
    _assign_reactions(well_plate, ["A1", "A2", "B1", "B2"])

    ordered_ids = [
        well.well_id
        for well in well_plate.get_all_wells_with_reactions(fill_by="rows", serpentine=False)
    ]

    assert ordered_ids == ["A1", "A2", "B1", "B2"]
