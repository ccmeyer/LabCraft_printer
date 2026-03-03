import json
from pathlib import Path

from Model import Model


def _configure_design(em):
    em.factors = []
    em.add_additive("AddA", [0.5], "mM", 10.0, starting_conc=0.2)
    em.set_metadata(randomize_assignments=False, start_row=0, start_col=0, replicates=1)


def test_progress_contains_plate_metadata_envelope(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    payload = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    plate = payload.get("__plate__", {})
    assert plate.get("name") == model.well_plate.get_current_plate_name()
    assert plate.get("rows") == model.well_plate.get_num_rows()
    assert plate.get("columns") == model.well_plate.get_num_cols()


def test_key_files_still_generate_with_plate_metadata_progress(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    assert Path(em.key_file_path).exists()
    assert Path(em.concentration_key_file_path).exists()
