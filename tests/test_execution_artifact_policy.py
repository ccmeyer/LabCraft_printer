import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Controller import Controller
from ExecutionArtifactPolicy import (
    ExecutionArtifactClassification,
    inspect_execution_artifacts,
)
from Model import CURRENT_PROFILE, ExperimentModel


def _recorded_legacy_folder(tmp_path: Path):
    model = ExperimentModel(prof=CURRENT_PROFILE)
    model.add_additive("Mg", [1.0], "mM", 10.0, forced_stock_conc=1.0)
    model.set_metadata(
        name="recorded",
        target_reaction_volume_nL=100.0,
        final_reaction_volume_nL=100.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    folder = tmp_path / "recorded"
    folder.mkdir()
    model.experiment_dir_path = str(folder)
    model.update_all_paths()
    model.save_experiment()
    progress = {
        "A1": {
            "reaction_id": "R1",
            "reagents": {
                "Mg_1.00_mM": {"target_droplets": 2, "added_droplets": 1}
            },
            "completed": False,
        },
        "__plate__": {"name": "plate", "rows": 8, "columns": 12, "schema_version": 1},
    }
    Path(model.progress_file_path).write_text(json.dumps(progress), encoding="utf-8")
    return model, folder


def test_recorded_legacy_progress_cannot_be_cleared_by_direct_model_api(tmp_path):
    model, folder = _recorded_legacy_folder(tmp_path)
    before = (folder / "progress.json").read_bytes()
    policy = inspect_execution_artifacts(folder)

    assert policy.classification is ExecutionArtifactClassification.RECORDED_LEGACY_EXECUTION
    assert not model.can_clear_progress_for_edit()
    assert not model.can_reset_array_progress()
    with pytest.raises(RuntimeError, match="cannot be deleted"):
        model.clear_progress_for_design_edit()
    assert (folder / "progress.json").read_bytes() == before


def test_controller_reset_guards_return_before_runtime_or_file_mutation():
    experiment_model = SimpleNamespace(can_reset_array_progress=lambda: False)
    well_plate = SimpleNamespace(
        reset_all_wells_for_stock=Mock(),
        reset_all_wells=Mock(),
    )
    rack = SimpleNamespace(get_gripper_printer_head=Mock())
    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(
        experiment_model=experiment_model,
        well_plate=well_plate,
        rack_model=rack,
    )
    controller.error_occurred_signal = SimpleNamespace(emit=Mock())

    assert Controller.reset_single_array(controller) is False
    assert Controller.reset_all_arrays(controller) is False
    rack.get_gripper_printer_head.assert_not_called()
    well_plate.reset_all_wells_for_stock.assert_not_called()
    well_plate.reset_all_wells.assert_not_called()
