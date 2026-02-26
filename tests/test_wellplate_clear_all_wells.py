def test_clear_all_wells_resets_excluded_wells_and_restores_availability(experiment_model_factory):
    model = experiment_model_factory()
    well_plate = model.well_plate

    total_wells = len(well_plate.get_all_wells())
    excluded = well_plate.get_all_wells()[0]
    well_plate.excluded_wells = {excluded}

    available_before = well_plate.get_available_wells()
    assert len(available_before) == total_wells - 1

    well_plate.clear_all_wells()

    assert well_plate.excluded_wells == set()
    available_after = well_plate.get_available_wells()
    assert len(available_after) == total_wells
