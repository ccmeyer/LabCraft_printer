import json
from pathlib import Path

from Model import Model


def _configure_design(em):
    em.factors = []
    em.add_additive("AddA", [0.5, 1.0], "mM", 10.0, starting_conc=0.2)
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


def test_read_progress_file_handles_invalid_json_with_safe_fallback(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    progress_path = Path(em.progress_file_path)
    progress_path.write_text("{not-valid-json", encoding="utf-8")

    em.read_progress_file(str(progress_path))
    assert em.progress_data == {}
    assert em.return_progress_data() == {}


def test_return_progress_data_handles_missing_file_with_safe_fallback(experiment_model_factory, tmp_path):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    missing_path = tmp_path / "missing_progress.json"
    assert not missing_path.exists()
    em.progress_file_path = str(missing_path)
    assert em.return_progress_data() == {}
