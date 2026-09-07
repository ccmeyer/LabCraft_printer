import copy
import json
from unittest.mock import Mock

from Model import CURRENT_PROFILE, ExperimentModel
from test_authoritative_execution_load import _hashes, _write_bundle
from test_experiment_design_reagent_headtype_integration import _build_real_dialog
from test_experiment_forced_stock_preview import _make_resolution_reproduction_model
from test_legacy_execution_reconstruction import (
    _directory_snapshot,
    _progress,
    _write_folder,
)


TARGETS = [0.5, 1.0, 5.0, 20.0]


def _legacy_resolution_model():
    source = _make_resolution_reproduction_model(
        TARGETS,
        allow_avoidable_grouping=True,
    )
    payload = copy.deepcopy(source.to_dict())
    payload["metadata"].pop("allow_avoidable_target_grouping", None)
    loaded = ExperimentModel(prof=CURRENT_PROFILE)
    loaded.from_dict(payload)
    return loaded


def test_inferred_legacy_policy_preserves_plan_fingerprint_and_counts_after_reload(
    tmp_path,
):
    model = _legacy_resolution_model()
    result = model.optimize_stock_solutions(allow_two=False)
    model.generate_experiment()

    assert result["optimizer_strategy_used"] == "concentration_first"
    assert result["stock_allocation_stop_reason"] == "grouping_allowed"
    assert result["distinct_level_loss"] == 1
    expected_plans = copy.deepcopy(model.plans_per_option)
    expected_reactions = model.get_reactions_dataframe().to_dict("records")
    expected_fingerprint = model.stock_allocation_input_fingerprint()

    experiment_dir = tmp_path / "legacy-resolution"
    experiment_dir.mkdir()
    model.experiment_dir_path = str(experiment_dir)
    model.update_all_paths()
    model.save_experiment()

    persisted = json.loads(
        (experiment_dir / "experiment_design.json").read_text(encoding="utf-8")
    )
    assert persisted["metadata"]["allow_avoidable_target_grouping"] is True

    reloaded = ExperimentModel(prof=CURRENT_PROFILE)
    reloaded.load_experiment(
        str(experiment_dir / "experiment_design.json"),
        str(experiment_dir),
    )
    reloaded_result = reloaded.optimize_stock_solutions(allow_two=False)
    reloaded.generate_experiment()

    assert reloaded.get_stock_allocation_resolution_policy()["source"] == "explicit"
    assert reloaded_result["optimizer_strategy_used"] == "concentration_first"
    assert reloaded.plans_per_option == expected_plans
    assert reloaded.get_reactions_dataframe().to_dict("records") == expected_reactions
    assert reloaded.stock_allocation_input_fingerprint() == expected_fingerprint


def test_clearing_inferred_grouping_explicitly_selects_resolution_first():
    model = _legacy_resolution_model()
    assert model.get_stock_allocation_resolution_policy()["inferred"] is True

    model.metadata["allow_avoidable_target_grouping"] = False
    result = model.optimize_stock_solutions(allow_two=False)

    assert model.get_stock_allocation_resolution_policy() == {
        "mode": "resolution_first",
        "source": "explicit",
        "allow_avoidable_target_grouping": False,
        "inferred": False,
    }
    assert result["optimizer_strategy_used"] == "resolution_first"
    assert result["distinct_level_loss"] == 0


def test_duplicate_normalizes_missing_policy_and_retains_session_provenance(tmp_path):
    source = _legacy_resolution_model()
    assert source.optimize_stock_solutions(allow_two=False)["best"]
    source.generate_experiment()
    expected_plans = copy.deepcopy(source.plans_per_option)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source.experiment_dir_path = str(source_dir)
    source.update_all_paths()
    source.save_experiment()
    source_path = source_dir / "experiment_design.json"
    source_document = json.loads(source_path.read_text(encoding="utf-8"))
    source_document["metadata"].pop("allow_avoidable_target_grouping")
    source_path.write_text(
        json.dumps(source_document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    source_bytes = source_path.read_bytes()

    duplicate = ExperimentModel(prof=CURRENT_PROFILE)
    destination = tmp_path / "duplicate"
    assert duplicate.duplicate_design_from(
        str(source_path),
        "duplicate",
        str(destination),
    )

    duplicated_document = json.loads(
        (destination / "experiment_design.json").read_text(encoding="utf-8")
    )
    assert source_path.read_bytes() == source_bytes
    assert duplicated_document["metadata"]["allow_avoidable_target_grouping"] is True
    assert duplicate.get_stock_allocation_resolution_policy()["inferred"] is True
    assert duplicate.plans_per_option == expected_plans


def test_authoritative_missing_policy_projects_frozen_plan_without_optimizer(
    experiment_model_factory,
    monkeypatch,
    tmp_path,
):
    design, plan = _write_bundle(tmp_path)
    loaded = experiment_model_factory()
    before = _hashes(tmp_path)
    optimize = Mock(side_effect=AssertionError("authoritative load must not optimize"))
    monkeypatch.setattr(loaded.experiment_model, "optimize_stock_solutions", optimize)

    bundle = loaded.experiment_model.load_experiment(
        str(tmp_path / "experiment_design.json"),
        str(tmp_path),
    )

    assert "allow_avoidable_target_grouping" not in design["metadata"]
    assert bundle.valid
    assert optimize.call_count == 0
    assert loaded.experiment_model.get_stock_allocation_resolution_policy()["inferred"]
    stock_row = next(
        row
        for row in loaded.experiment_model.get_stock_table_rows(include_fill=False)
        if row["factor_name"] == plan.stocks[0].factor_name
    )
    assert stock_row["total_droplets"] == 16
    assert _hashes(tmp_path) == before


def test_recorded_missing_policy_reconstructs_without_optimizer_or_writes(
    monkeypatch,
    tmp_path,
):
    directory = tmp_path / "recorded"
    _write_folder(directory, progress=_progress())
    before = _directory_snapshot(directory)
    model = ExperimentModel(prof=CURRENT_PROFILE)
    optimize = Mock(side_effect=AssertionError("recorded load must not optimize"))
    monkeypatch.setattr(model, "optimize_stock_solutions", optimize)

    model.load_experiment(
        str(directory / "experiment_design.json"),
        str(directory),
    )

    assert optimize.call_count == 0
    assert model.get_stock_allocation_resolution_policy()["inferred"] is True
    assert _directory_snapshot(directory) == before


def test_editor_discloses_inferred_policy_as_nonblocking_information(qapp):
    dialog = _build_real_dialog()
    payload = copy.deepcopy(dialog.model.to_dict())
    payload["metadata"].pop("allow_avoidable_target_grouping")
    dialog.model.from_dict(payload)
    dialog._sync_controls_from_model(recompute=False)

    dialog._set_status("Design loaded.", severity="success")

    information = dialog.LEGACY_RESOLUTION_POLICY_INFORMATION
    assert dialog.allow_avoidable_grouping_chk.isChecked() is True
    assert dialog.allow_avoidable_grouping_chk.isEnabled() is True
    assert dialog.run_btn.isEnabled() is True
    assert information in dialog.status_lbl.text()
    assert "\u2018Allow avoidable target-level grouping\u2019" in dialog.status_lbl.text()
    assert dialog._status_severity == "info"
    assert dialog.status_heading_lbl.text() == "Status"

    dialog.allow_avoidable_grouping_chk.setChecked(False)
    dialog._auto_timer.stop()
    dialog._update_metadata_from_controls()
    dialog._set_status("Reactions updated.", severity="success")

    assert dialog.model.get_stock_allocation_resolution_policy()["inferred"] is False
    assert information not in dialog.status_lbl.text()
    assert dialog._status_severity == "success"
    dialog.close()


def test_execution_lock_status_takes_precedence_over_legacy_policy_information(qapp):
    dialog = _build_real_dialog()
    payload = copy.deepcopy(dialog.model.to_dict())
    payload["metadata"].pop("allow_avoidable_target_grouping")
    dialog.model.from_dict(payload)
    dialog._sync_controls_from_model(recompute=False)
    dialog.model._execution_plan_reload_read_only = True
    dialog._apply_execution_edit_lock_state()

    dialog._set_status("Execution is locked.", severity="warning")

    assert dialog.LEGACY_RESOLUTION_POLICY_INFORMATION not in dialog.status_lbl.text()
    assert dialog._status_severity == "warning"
    assert dialog.allow_avoidable_grouping_chk.isEnabled() is False
    dialog.close()
