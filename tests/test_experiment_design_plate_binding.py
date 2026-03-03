from Model import Model


def _configure_design(em):
    em.factors = []
    em.add_additive("AddA", [0.5, 1.0], "mM", 10.0, starting_conc=0.2)
    em.set_metadata(randomize_assignments=False, start_row=0, start_col=0, replicates=1)


def test_load_experiment_from_model_binds_current_plate_into_metadata(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()

    Model.load_experiment_from_model(model, load_progress=False)

    assert em.metadata["plate_name"] == model.well_plate.get_current_plate_name()
    assert em.metadata["plate_rows"] == model.well_plate.get_num_rows()
    assert em.metadata["plate_columns"] == model.well_plate.get_num_cols()
