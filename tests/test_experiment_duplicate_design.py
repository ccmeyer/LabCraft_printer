import json
from pathlib import Path

import pandas as pd
import pytest

from Model import CURRENT_PROFILE, ExperimentModel


def _configure_factor_design(model: ExperimentModel, *, name: str = "SourceExp"):
    model.add_additive("Mg", [0.0, 1.0], "mM", 10.0, starting_conc=0.0)
    model.set_metadata(
        name=name,
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=2,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    assert model.optimize_stock_solutions()["best"]
    model.generate_experiment()


def _write_source_artifacts(model: ExperimentModel, source_dir: Path):
    source_dir.mkdir()
    model.experiment_dir_path = str(source_dir)
    model.update_all_paths()
    model.applied_imaging_calibrations = {
        "schema_version": 1,
        "records": {
            "source-calibration": {
                "stock_id": "Mg_1.00_mM",
                "printer_head_id": "head-1",
            },
        },
    }
    model.manual_refuel_checks = {
        "schema_version": 1,
        "records": {
            "source-refuel-check": {
                "stock_id": "Mg_1.00_mM",
                "printer_head_id": "head-1",
                "status": "passed",
            },
        },
    }
    model.save_experiment()

    progress_payload = {
        "A1": {
            "reaction_id": "R1",
            "reagents": {
                "Mg_1.00_mM": {
                    "target_droplets": 5,
                    "added_droplets": 3,
                },
            },
            "completed": False,
        },
    }
    Path(model.progress_file_path).write_text(
        json.dumps(progress_payload, indent=2),
        encoding="utf-8",
    )
    Path(model.calibration_file_path).write_text(
        json.dumps({"runs": [{"run_id": "source-run"}]}, indent=2),
        encoding="utf-8",
    )
    recording_dir = source_dir / "calibration_recordings" / "NozzleFocus" / "run-1"
    recording_dir.mkdir(parents=True)
    (recording_dir / "capture.txt").write_text("source recording", encoding="utf-8")


def test_duplicate_design_from_source_creates_fresh_run_state(tmp_path):
    source_model = ExperimentModel(prof=CURRENT_PROFILE)
    _configure_factor_design(source_model)
    source_dir = tmp_path / "source"
    _write_source_artifacts(source_model, source_dir)

    source_design_path = source_dir / "experiment_design.json"
    source_progress_path = source_dir / "progress.json"
    source_calibration_path = source_dir / "calibration.json"
    source_design_before = source_design_path.read_text(encoding="utf-8")
    source_progress_before = source_progress_path.read_text(encoding="utf-8")
    source_calibration_before = source_calibration_path.read_text(encoding="utf-8")

    duplicate_model = ExperimentModel(prof=CURRENT_PROFILE)
    duplicate_dir = tmp_path / "SourceExp_replicate"

    assert duplicate_model.duplicate_design_from(
        str(source_design_path),
        "SourceExp_replicate",
        str(duplicate_dir),
    )

    assert source_design_path.read_text(encoding="utf-8") == source_design_before
    assert source_progress_path.read_text(encoding="utf-8") == source_progress_before
    assert source_calibration_path.read_text(encoding="utf-8") == source_calibration_before

    duplicate_design = json.loads((duplicate_dir / "experiment_design.json").read_text(encoding="utf-8"))
    assert duplicate_design["metadata"]["name"] == "SourceExp_replicate"
    assert duplicate_design["metadata"]["replicates"] == 2
    assert duplicate_design["applied_imaging_calibrations"] == {
        "schema_version": 1,
        "records": {},
    }
    assert duplicate_design["manual_refuel_checks"] == {
        "schema_version": 1,
        "records": {},
    }
    assert json.loads((duplicate_dir / "progress.json").read_text(encoding="utf-8")) == {}
    assert json.loads((duplicate_dir / "calibration.json").read_text(encoding="utf-8")) == {}
    assert not (duplicate_dir / "calibration_recordings").exists()
    assert not (duplicate_dir / "execution_plan.json").exists()
    assert not (duplicate_dir / "execution_resume.json").exists()
    assert not (duplicate_dir / "execution_calibrations.json").exists()

    status = duplicate_model.get_progress_status(str(duplicate_dir / "progress.json"))
    assert status["has_printed_progress"] is False
    assert status["total_added_droplets"] == 0
    assert duplicate_model.experiment_dir_path == str(duplicate_dir.resolve())
    assert duplicate_model.metadata["name"] == "SourceExp_replicate"
    assert len(duplicate_model.factors) == len(source_model.factors)


def test_duplicate_design_preserves_uploaded_design_and_well_ids(tmp_path):
    source_model = ExperimentModel(prof=CURRENT_PROFILE)
    source_model.set_metadata(
        name="UploadedSource",
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    source_model.set_uploaded_design_from_dataframe(
        pd.DataFrame(
            {
                "Well ID": ["A1", "A2"],
                "Mg mM": [0.0, 1.0],
            }
        ),
        units_default="mM",
        droplet_nL_default=10.0,
        source_path=str(tmp_path / "uploaded_source.csv"),
    )
    assert source_model.optimize_stock_solutions()["best"]
    source_model.generate_experiment()
    source_dir = tmp_path / "uploaded_source"
    _write_source_artifacts(source_model, source_dir)

    duplicate_model = ExperimentModel(prof=CURRENT_PROFILE)
    duplicate_dir = tmp_path / "UploadedSource_replicate"

    assert duplicate_model.duplicate_design_from(
        str(source_dir / "experiment_design.json"),
        "UploadedSource_replicate",
        str(duplicate_dir),
    )

    assert duplicate_model.has_uploaded_design()
    assert duplicate_model._uploaded_well_ids == ["A1", "A2"]
    uploaded_csv = duplicate_dir / "uploaded_design.csv"
    assert uploaded_csv.exists()

    uploaded_df = pd.read_csv(uploaded_csv)
    assert uploaded_df["Well ID"].tolist() == ["A1", "A2"]
    assert uploaded_df["Mg mM"].tolist() == [0.0, 1.0]

    duplicate_design = json.loads((duplicate_dir / "experiment_design.json").read_text(encoding="utf-8"))
    assert duplicate_design["uploaded_design"]["csv_filename"] == "uploaded_design.csv"
    assert duplicate_design["uploaded_design"]["well_ids"] == ["A1", "A2"]


def test_editable_copy_restores_intended_dispense_inputs(tmp_path):
    source = ExperimentModel(prof=CURRENT_PROFILE)
    _configure_factor_design(source)
    source.factors[0].options[0].intended_droplet_nL = 10.0
    source.factors[0].options[0].intended_printing_mode = "droplet"
    source.factors[0].options[0].droplet_nL = 11.25
    source.metadata["intended_fill_droplet_volume_nL"] = 9.0
    source.metadata["intended_fill_printing_mode"] = "droplet"
    source.metadata["fill_droplet_volume_nL"] = 10.5
    source_dir = tmp_path / "source_intended"
    _write_source_artifacts(source, source_dir)

    duplicate = ExperimentModel(prof=CURRENT_PROFILE)
    destination = tmp_path / "editable"
    duplicate.create_editable_design_copy(
        str(source_dir), str(destination), "Editable"
    )

    payload = json.loads((destination / "experiment_design.json").read_text(encoding="utf-8"))
    option = payload["factors"][0]["options"][0]
    assert option["droplet_nL"] == 10.0
    assert option["printing_mode"] == "droplet"
    assert "intended_droplet_nL" not in option
    assert payload["metadata"]["fill_droplet_volume_nL"] == 9.0
    assert "intended_fill_droplet_volume_nL" not in payload["metadata"]


def test_duplicate_optimization_failure_is_transactional(tmp_path, monkeypatch):
    source = ExperimentModel(prof=CURRENT_PROFILE)
    _configure_factor_design(source)
    source_dir = tmp_path / "source_failure"
    _write_source_artifacts(source, source_dir)
    destination = tmp_path / "must_not_exist"
    duplicate = ExperimentModel(prof=CURRENT_PROFILE)

    monkeypatch.setattr(
        ExperimentModel,
        "optimize_stock_solutions",
        lambda self, *args, **kwargs: {"best": None, "reason": "injected failure"},
    )
    with pytest.raises(RuntimeError, match="injected failure"):
        duplicate.duplicate_design_from(
            str(source_dir / "experiment_design.json"),
            "FailedCopy",
            str(destination),
        )

    assert not destination.exists()
    assert duplicate.experiment_dir_path is None


def test_duplicate_existing_destination_does_not_mutate_source(tmp_path):
    source = ExperimentModel(prof=CURRENT_PROFILE)
    _configure_factor_design(source)
    source_dir = tmp_path / "source_existing_destination"
    _write_source_artifacts(source, source_dir)
    source_before = {
        path.relative_to(source_dir): path.read_bytes()
        for path in source_dir.rglob("*")
        if path.is_file()
    }
    destination = tmp_path / "existing"
    destination.mkdir()
    duplicate = ExperimentModel(prof=CURRENT_PROFILE)

    with pytest.raises(FileExistsError, match="already exists"):
        duplicate.duplicate_design_from(
            str(source_dir / "experiment_design.json"),
            "Existing",
            str(destination),
        )

    assert {
        path.relative_to(source_dir): path.read_bytes()
        for path in source_dir.rglob("*")
        if path.is_file()
    } == source_before
    assert list(destination.iterdir()) == []
    assert duplicate.experiment_dir_path is None


def test_duplicate_missing_source_is_rejected_without_destination(tmp_path):
    duplicate = ExperimentModel(prof=CURRENT_PROFILE)
    destination = tmp_path / "must_not_exist"

    with pytest.raises(FileNotFoundError):
        duplicate.duplicate_design_from(
            str(tmp_path / "missing" / "experiment_design.json"),
            "Missing",
            str(destination),
        )

    assert not destination.exists()
    assert duplicate.experiment_dir_path is None


def test_copy_calibrations_compatibility_argument_is_rejected(tmp_path):
    model = ExperimentModel(prof=CURRENT_PROFILE)
    _configure_factor_design(model)
    with pytest.raises(ValueError, match="Calibration evidence cannot be copied"):
        model.duplicate_experiment("copy", str(tmp_path / "copy"), copy_calibrations=True)
