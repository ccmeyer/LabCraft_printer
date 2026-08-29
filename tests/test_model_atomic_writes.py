import json
from pathlib import Path

import pytest
import pandas as pd


def test_save_experiment_atomic_write_preserves_previous_file_on_replace_failure(
    experiment_model_factory, monkeypatch
):
    model = experiment_model_factory()
    em = model.experiment_model

    design_path = Path(em.experiment_file_path)
    baseline = {"name": "baseline", "replicates": 1}
    design_path.write_text(json.dumps(baseline), encoding="utf-8")

    original_replace = __import__("os").replace

    def _boom(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("os.replace", _boom)

    with pytest.raises(OSError, match="replace failure"):
        em.save_experiment()

    assert json.loads(design_path.read_text(encoding="utf-8")) == baseline
    tmp_files = list(design_path.parent.glob("._tmp_*.json"))
    assert tmp_files == []

    monkeypatch.setattr("os.replace", original_replace)


def test_create_progress_file_atomic_write_preserves_previous_file_on_replace_failure(
    experiment_model_factory, monkeypatch
):
    model = experiment_model_factory()
    em = model.experiment_model

    progress_path = Path(em.progress_file_path)
    baseline = {"A1": {"reaction_id": "R-1", "reagents": {}, "completed": False}}
    progress_path.write_text(json.dumps(baseline), encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("os.replace", _boom)

    with pytest.raises(OSError, match="replace failure"):
        em.create_progress_file()

    assert json.loads(progress_path.read_text(encoding="utf-8")) == baseline
    tmp_files = list(progress_path.parent.glob("._tmp_*.json"))
    assert tmp_files == []


@pytest.mark.parametrize("file_name", ["key.csv", "concentration_key.csv"])
def test_atomic_dataframe_csv_preserves_previous_file_on_replace_failure(
    experiment_model_factory,
    monkeypatch,
    file_name,
):
    model = experiment_model_factory()
    em = model.experiment_model
    path = Path(em.experiment_dir_path) / file_name
    baseline = b"Well ID,baseline\nA1,7\n"
    path.write_bytes(baseline)

    def _boom(*args, **kwargs):
        raise OSError("simulated CSV replace failure")

    monkeypatch.setattr("os.replace", _boom)

    with pytest.raises(OSError, match="CSV replace failure"):
        em._atomic_dataframe_csv(
            pd.DataFrame.from_dict({"A1": {"updated": 3}}, orient="index"),
            str(path),
        )

    assert path.read_bytes() == baseline
    assert list(path.parent.glob("._tmp_*.csv")) == []
