import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from hardware.profile import CURRENT_PROFILE
from Model import ExperimentModel, Model


def _configure_design(em):
    em.factors = []
    em.add_additive("AuditAdditive", [0.5, 1.0], "mM", 10.0, starting_conc=0.2)
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


def _prepare_runtime_design(model):
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    return em


def _read_audit(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_update_all_paths_sets_experiment_audit_path(tmp_path):
    em = ExperimentModel(prof=CURRENT_PROFILE)
    em.experiment_dir_path = str(tmp_path / "experiment")

    em.update_all_paths()

    exp_dir = Path(em.experiment_dir_path)
    assert em.experiment_file_path == str(exp_dir / "experiment_design.json")
    assert em.progress_file_path == str(exp_dir / "progress.json")
    assert em.calibration_file_path == str(exp_dir / "calibration.json")
    assert em.experiment_audit_file_path == str(exp_dir / "experiment_audit.jsonl")


def test_initialize_experiment_sets_audit_path_without_logging(tmp_path):
    em = ExperimentModel(prof=CURRENT_PROFILE)
    em.metadata["name"] = "AuditInit"

    em.initialize_experiment(base_dir=str(tmp_path))

    audit_path = Path(em.experiment_audit_file_path)
    assert audit_path == Path(em.experiment_dir_path) / "experiment_audit.jsonl"
    assert Path(em.experiment_file_path).exists()
    assert Path(em.progress_file_path).exists()
    assert Path(em.calibration_file_path).exists()
    assert not audit_path.exists()


def test_load_experiment_from_model_appends_experiment_loaded_event(experiment_model_factory):
    model = experiment_model_factory()
    em = _prepare_runtime_design(model)

    Model.load_experiment_from_model(model, load_progress=False)

    audit_path = Path(em.experiment_audit_file_path)
    rows = _read_audit(audit_path)
    assert [row["event_type"] for row in rows] == ["experiment_loaded"]
    details = rows[0]["details"]
    assert details["load_progress"] is False
    assert details["progress_state"] == "created"
    assert details["reaction_count"] == em.get_number_of_reactions()
    assert details["assigned_well_count"] == em.get_number_of_reactions()
    assert details["initialized_experiment"] is False
    assert rows[0]["context"]["experiment_file_path"] == em.experiment_file_path
    assert rows[0]["context"]["progress_file_path"] == em.progress_file_path
    assert rows[0]["context"]["calibration_file_path"] == em.calibration_file_path


def test_reloaded_experiment_records_load_progress_true(experiment_model_factory):
    source_model = experiment_model_factory()
    source_em = _prepare_runtime_design(source_model)
    source_em.save_experiment()
    Model.load_experiment_from_model(source_model, load_progress=False)

    reloaded_model = experiment_model_factory()
    reloaded_em = reloaded_model.experiment_model
    reloaded_em.load_experiment(source_em.experiment_file_path, source_em.experiment_dir_path)

    Model.load_experiment_from_model(reloaded_model, load_progress=True)

    rows = _read_audit(Path(source_em.experiment_audit_file_path))
    assert rows[-1]["event_type"] == "experiment_loaded"
    assert rows[-1]["details"]["load_progress"] is True
    assert rows[-1]["details"]["progress_state"] == "loaded"
    assert rows[-1]["context"]["experiment_file_path"] == source_em.experiment_file_path


def test_audit_write_failure_does_not_block_runtime_load(experiment_model_factory):
    model = experiment_model_factory()
    em = _prepare_runtime_design(model)
    recorder = Mock(side_effect=RuntimeError("audit offline"))
    model.experiment_audit_log = SimpleNamespace(record=recorder)

    Model.load_experiment_from_model(model, load_progress=False)

    recorder.assert_called_once()
    assert Path(em.progress_file_path).exists()
    assert Path(em.key_file_path).exists()
    assert Path(em.concentration_key_file_path).exists()
