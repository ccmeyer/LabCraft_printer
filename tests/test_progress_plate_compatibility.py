import json
from pathlib import Path

import pytest

from Model import Model


def _configure_design(em):
    em.factors = []
    em.add_additive("AddA", [0.5, 1.0], "mM", 10.0, starting_conc=0.2)
    em.set_metadata(randomize_assignments=False, start_row=0, start_col=0, replicates=1)


def test_load_progress_rejects_plate_metadata_mismatch(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    p = Path(em.progress_file_path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["__plate__"]["name"] = "other-plate"
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="plate metadata does not match"):
        em.load_progress()


def test_progress_file_includes_plate_metadata(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    payload = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    assert "__plate__" in payload
    assert payload["__plate__"]["name"] == model.well_plate.get_current_plate_name()
