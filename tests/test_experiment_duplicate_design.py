import json
from pathlib import Path

import pandas as pd

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
    assert json.loads((duplicate_dir / "progress.json").read_text(encoding="utf-8")) == {}
    assert json.loads((duplicate_dir / "calibration.json").read_text(encoding="utf-8")) == {}
    assert not (duplicate_dir / "calibration_recordings").exists()

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
