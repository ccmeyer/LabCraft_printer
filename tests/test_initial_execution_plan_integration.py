import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

import Model as model_module
from AuthoritativeExecutionLoad import inspect_authoritative_execution
from ExecutionPlan import ExecutionPlanState, canonical_sha256, load_execution_plan
from ExecutionPlanRevision import build_terminal_revision
from ExecutionProgressStore import (
    decode_execution_progress,
    serialize_execution_progress,
)
from ExecutionCalibrationStore import load_execution_calibrations
from ExecutionPlanRevision import validate_revision_history
from Model import CURRENT_PROFILE, ExperimentModel, Model


def _configure_design(em, *, randomize=False, seed=None):
    em.factors = []
    em.add_additive(
        "PURE_MM",
        [1.0],
        "x",
        60.0,
        forced_stock_conc=1.11,
        printing_mode="stream",
    )
    em.add_choice_group("UTP")
    em.add_choice_option(
        "UTP",
        "UTP (dil)",
        [0.0, 10000.0],
        "nM",
        10.5,
        forced_stock_conc=95000.0,
    )
    em.set_metadata(
        randomize_assignments=randomize,
        random_seed=seed,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=2500.0,
        final_reaction_volume_nL=2500.0,
        printed_volume_tolerance_nL=50.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()


def _configure_explicit_uploaded_design(em):
    em.set_metadata(
        name="explicit-upload-calibration",
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        printed_volume_tolerance_nL=50.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    em.set_uploaded_design_from_dataframe(
        pd.DataFrame(
            {
                "Well": ["A1", "B2"],
                "Signal (mM)": [0.4, 1.0],
            }
        )
    )
    em.factors[0].options[0].forced_stock_conc = 10.0
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()


def _configure_minimal_editor_design(em):
    em.factors = []
    em.add_additive(
        "Editor Stock",
        [1.0],
        "x",
        10.0,
        forced_stock_conc=1.0,
        printing_mode="droplet",
    )
    em.set_metadata(
        name="prepared-editor",
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=2,
        target_reaction_volume_nL=10.0,
        final_reaction_volume_nL=10.0,
        printed_volume_tolerance_nL=0.0,
        fill_reagent_name="Water",
        fill_printing_mode="droplet",
        fill_droplet_volume_nL=10.0,
    )
    em.set_well_selection(["A1", "A2"])
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()


def _configure_zero_fill_design(em):
    """Create a finalized design whose one dispense exactly fills each well."""
    em.factors = []
    em.add_additive(
        "reagent-1",
        [1.0],
        "mM",
        9.0,
        forced_stock_conc=1.0,
        printing_mode="droplet",
    )
    em.set_metadata(
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=2,
        target_reaction_volume_nL=9.0,
        final_reaction_volume_nL=9.0,
        printed_volume_tolerance_nL=50.0,
        fill_reagent_name="Water",
        fill_printing_mode="droplet",
        fill_droplet_volume_nL=9.0,
    )
    em.set_well_selection(["A1", "A2"])
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    assert em._fill_row_cache["total_droplets"] == 0
    em.save_experiment()


def _apply_stream_editor_revision(em):
    option = em.factors[0].options[0]
    option.targets = [0.5, 1.0]
    option.printing_mode = "stream"
    option.droplet_nL = 60.0
    em.set_metadata(
        name="prepared-editor-renamed",
        replicates=3,
        target_reaction_volume_nL=120.0,
        final_reaction_volume_nL=120.0,
        fill_printing_mode="stream",
        fill_droplet_volume_nL=60.0,
    )
    em.set_well_selection(["A1", "A2", "A3", "A4", "A5", "A6"])
    em._clear_design_derived_state()
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()


def _well_targets(plan):
    return {
        well.well_id: {
            dispense.stock_id: dispense.target_dispenses for dispense in well.dispenses
        }
        for well in plan.wells
    }


def _directory_bytes(directory):
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def test_fresh_finalization_writes_prepared_plan_before_linked_progress(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em, randomize=True, seed=17)
    design_payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))

    Model.load_experiment_from_model(
        model,
        load_progress=False,
        finalize_execution_plan=True,
    )

    plan = load_execution_plan(em.execution_plan_file_path)
    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    assert plan.state is ExecutionPlanState.PREPARED
    assert plan.plan_revision == 1
    assert plan.design_sha256 == canonical_sha256(design_payload)
    assert em.get_execution_plan_snapshot() == plan
    assert em.get_execution_plan_source() == "new_finalization"
    assert progress["schema_name"] == "labcraft.execution_progress"
    assert progress["schema_version"] == 2
    assert progress["plan_id"] == plan.plan_id
    assert progress["plan_revision"] == 1
    assert em.get_progress_execution_reference().plan_id == plan.plan_id
    assert set(em.return_progress_data()) == {well.well_id for well in plan.wells}
    assert em.get_progress_status()["well_count"] == len(plan.wells)
    decoded_progress = decode_execution_progress(plan, progress).progress_wells
    progress_wells = {
        well_id: {
            stock_id: int(counts["target_droplets"])
            for stock_id, counts in entry["reagents"].items()
        }
        for well_id, entry in decoded_progress.items()
    }
    assert progress_wells == _well_targets(plan)
    assert all(stock.printer_head_id is None for stock in plan.stocks)
    assert all(stock.calibration_record_key is None for stock in plan.stocks)
    revision_one = Path(
        em.execution_plan_revisions_dir_path,
        "revision_000001.json",
    )
    assert revision_one.exists()
    assert load_execution_plan(revision_one) == plan

    audit_rows = [
        json.loads(line)
        for line in Path(em.experiment_audit_file_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    details = audit_rows[-1]["details"]
    assert details["execution_plan_id"] == plan.plan_id
    assert details["execution_plan_revision"] == 1
    assert details["execution_plan_status"] == "created"


def test_valid_two_stock_editor_result_survives_runtime_projection_and_finalization(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    em.factors = []
    em.set_metadata(
        name="two-stock-finalization",
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=10.0,
        final_reaction_volume_nL=500.0,
        printed_volume_tolerance_nL=0.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
        allow_two_stock_solutions=True,
        allow_avoidable_target_grouping=True,
    )
    em.add_additive("Signal", [0.1, 0.2], "mM", 10.0)

    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=True,
    )
    assert result["best"] is True
    assert result["two_stock_keys"] == [("Signal", None)]
    em.generate_experiment()
    em.save_experiment()

    Model.load_experiment_from_model(
        model,
        load_progress=False,
        finalize_execution_plan=True,
    )

    plan = load_execution_plan(em.execution_plan_file_path)
    signal_stocks = [stock for stock in plan.stocks if stock.factor_name == "Signal"]
    assert len(signal_stocks) == 2
    assert len({stock.stock_id for stock in signal_stocks}) == 2
    assert {
        stock.stock_id
        for stock in model.stock_solutions.get_all_stock_solutions()
        if stock.reagent_name == "Signal"
    } == {stock.stock_id for stock in signal_stocks}
    assert all(
        any(
            dispense.stock_id == stock.stock_id
            for well in plan.wells
            for dispense in well.dispenses
        )
        for stock in signal_stocks
    )


def _configure_calibratable_two_stock_execution(model):
    em = model.experiment_model
    em.factors = []
    em.set_metadata(
        name="two-stock-calibration-application",
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=240.0,
        final_reaction_volume_nL=5000.0,
        printed_volume_tolerance_nL=0.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
        allow_two_stock_solutions=True,
        allow_avoidable_target_grouping=False,
    )
    em.add_additive("Signal", [0.5, 1.0, 5.0, 20.0], "mM", 10.0)
    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=True,
    )
    assert result["best"] is True
    assert result["two_stock_keys"] == [("Signal", None)]
    em.generate_experiment()
    em.save_experiment()
    Model.load_experiment_from_model(
        model,
        load_progress=False,
        finalize_execution_plan=True,
    )
    return em


def test_finalized_two_stock_calibration_requantizes_both_legs_atomically(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = _configure_calibratable_two_stock_execution(model)
    before = load_execution_plan(em.execution_plan_file_path)
    signal_stocks = sorted(
        (stock for stock in before.stocks if stock.factor_name == "Signal"),
        key=lambda stock: stock.concentration,
        reverse=True,
    )
    calibrated, companion = signal_stocks
    companion_before = companion
    old_counts = {
        well.well_id: {
            dispense.stock_id: dispense.target_dispenses
            for dispense in well.dispenses
        }
        for well in before.wells
    }

    result = em.apply_droplet_volume_for_option(
        "Signal",
        None,
        12.0,
        applied_calibration={
            "stock_id": calibrated.stock_id,
            "printer_head": SimpleNamespace(printer_head_id="two-stock-head-final"),
            "measured_volume_nL": 12.0,
            "pw_us": 1200,
            "pressure_psi": 0.8,
            "run_id": "two-stock-finalized-calibration",
            "phase": "synthetic_characterization",
        },
        printing_mode="droplet",
    )

    revised = load_execution_plan(em.execution_plan_file_path)
    revised_by_id = {stock.stock_id: stock for stock in revised.stocks}
    assert result["n_stocks"] == 2
    assert result["calibrated_stock_id"] == calibrated.stock_id
    assert result["companion_stock_id"] == companion.stock_id
    assert revised_by_id[calibrated.stock_id].effective_volume_nL == pytest.approx(12.0)
    assert revised_by_id[calibrated.stock_id].calibration_record_key is not None
    assert revised_by_id[companion.stock_id] == companion_before
    assert set(revised_by_id) == {stock.stock_id for stock in before.stocks}
    new_counts = {
        well.well_id: {
            dispense.stock_id: dispense.target_dispenses
            for dispense in well.dispenses
        }
        for well in revised.wells
    }
    assert any(
        old_counts[well_id].get(companion.stock_id, 0)
        != new_counts[well_id].get(companion.stock_id, 0)
        for well_id in old_counts
    )
    assert all(
        well.expected_printed_volume_nL
        <= revised.volume_basis.target_printed_volume_nL
        + revised.volume_basis.design_optimization_tolerance_nL
        + 1e-9
        for well in revised.wells
    )


@pytest.mark.parametrize("blocking_role", ["companion", "fill"])
def test_two_stock_calibration_application_blocks_affected_stock_progress(
    experiment_model_factory,
    blocking_role,
):
    model = experiment_model_factory()
    em = _configure_calibratable_two_stock_execution(model)
    active = em.lock_execution_plan("printing_started")
    signal_stocks = sorted(
        (stock for stock in active.stocks if stock.factor_name == "Signal"),
        key=lambda stock: stock.concentration,
        reverse=True,
    )
    calibrated, companion = signal_stocks
    fill_stock = next(
        stock
        for stock in active.stocks
        if stock.factor_name == em.get_fill_reagent_name() and stock.units == "--"
    )
    blocking_stock = companion if blocking_role == "companion" else fill_stock
    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    values = progress["added_droplets"][blocking_stock.stock_id]
    target_index = next(index for index, value in enumerate(values) if value is not None)
    values[target_index] = 1
    Path(em.progress_file_path).write_text(
        serialize_execution_progress(progress),
        encoding="utf-8",
    )
    em.read_progress_file(em.progress_file_path)

    eligibility = em.get_calibration_application_eligibility(
        stock_id=calibrated.stock_id
    )

    assert eligibility["ok"] is False
    assert eligibility["code"] == "affected_stock_progress"
    assert blocking_stock.stock_id in eligibility["affected_stock_ids"]
    assert eligibility["affected_stock_progress"][blocking_stock.stock_id] == 1


@pytest.mark.parametrize("activate", [False, True])
def test_stock_prep_sidecar_does_not_change_authoritative_execution(
    experiment_model_factory,
    activate,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(
        model,
        load_progress=False,
        finalize_execution_plan=True,
    )
    if activate:
        plan = em.lock_execution_plan("printing_started")
        assert plan.state is ExecutionPlanState.ACTIVE
    else:
        plan = em.get_execution_plan_snapshot()
        assert plan.state is ExecutionPlanState.PREPARED

    design_path = Path(em.experiment_file_path)
    design_before = design_path.read_bytes()
    design_payload = json.loads(design_before)
    identities_before, revisions_before = em._capture_authoritative_runtime_files()
    rows = em.get_stock_prep_rows()
    em.unsaved_changes = False

    em.save_stock_prep_worksheet(
        [
            {
                **row,
                "prep_volume_uL": float(row["total_volume_uL"]) + 30.0,
                "source_concentration": float(row["stock_concentration"]) * 2.0,
            }
            for row in rows
        ],
        dead_volume_extra_uL=20.0,
        calibration_extra_uL=10.0,
    )

    identities_after, revisions_after = em._capture_authoritative_runtime_files()
    assert Path(em.stock_prep_file_path).is_file()
    assert design_path.read_bytes() == design_before
    assert canonical_sha256(json.loads(design_path.read_bytes())) == plan.design_sha256
    assert identities_after == identities_before
    assert revisions_after == revisions_before
    assert em.unsaved_changes is False
    assert em.get_execution_plan_snapshot() == plan
    bundle = inspect_authoritative_execution(em.experiment_dir_path, design_payload)
    assert bundle.valid
    assert bundle.plan == plan


def test_prepared_name_only_rename_replaces_and_reloads_authoritative_bundle(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    original_dir = Path(em.experiment_dir_path)
    original_plan = load_execution_plan(em.execution_plan_file_path)
    stock_row = em.get_stock_prep_rows()[0]
    em.save_stock_prep_worksheet(
        [
            {
                **stock_row,
                "prep_volume_uL": float(stock_row["total_volume_uL"]) + 30.0,
                "source_concentration": float(stock_row["stock_concentration"]) * 2.0,
            }
        ],
        dead_volume_extra_uL=20.0,
        calibration_extra_uL=10.0,
    )

    em.metadata["name"] = "prepared-renamed"
    assert em.rename_experiment("prepared-renamed")
    Model.load_experiment_from_model(model, finalize_execution_plan=True)

    renamed_dir = original_dir.parent / "prepared-renamed"
    design = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    plan = load_execution_plan(em.execution_plan_file_path)
    bundle = inspect_authoritative_execution(renamed_dir, design)
    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    archived = (
        renamed_dir
        / "superseded_prepared_execution_plans"
        / original_plan.plan_id
    )

    assert not original_dir.exists()
    assert em.experiment_dir_path == str(renamed_dir)
    assert design["metadata"]["name"] == "prepared-renamed"
    assert plan.plan_id != original_plan.plan_id
    assert plan.state is ExecutionPlanState.PREPARED
    assert plan.design_sha256 == canonical_sha256(design)
    assert plan.stocks == original_plan.stocks
    assert plan.wells == original_plan.wells
    assert progress["plan_id"] == plan.plan_id
    assert progress["plan_revision"] == plan.plan_revision
    assert bundle.valid
    assert bundle.eligibility.status == "ready_to_start"
    assert bundle.history == (plan,)
    assert (
        load_execution_plan(archived / "prepared_plan_at_replacement.json")
        == original_plan
    )
    assert validate_revision_history(
        archived / "execution_plan_revisions",
        latest_plan=original_plan,
    ) == (original_plan,)
    assert not list(original_dir.parent.glob(".*.staging-*"))
    assert not list(original_dir.parent.glob(".*.rollback-*"))

    rebound_worksheet = em.load_stock_prep_worksheet(force=True)
    assert rebound_worksheet["plan_id"] == plan.plan_id
    assert list(rebound_worksheet["entries"]) == [stock_row["stock_id"]]
    em.save_stock_prep_worksheet(
        [
            {
                **em.get_stock_prep_rows()[0],
                **rebound_worksheet["entries"][stock_row["stock_id"]],
            }
        ],
        **rebound_worksheet["defaults"],
    )
    saved_worksheet = json.loads(
        Path(em.stock_prep_file_path).read_text(encoding="utf-8")
    )
    assert saved_worksheet["plan_id"] == plan.plan_id

    reloaded = ExperimentModel(prof=CURRENT_PROFILE)
    reloaded_bundle = reloaded.load_experiment(
        str(renamed_dir / "experiment_design.json"),
        str(renamed_dir),
    )
    assert reloaded_bundle.valid
    assert reloaded_bundle.plan == plan
    assert reloaded_bundle.eligibility.status == "ready_to_start"


def test_prepared_design_edit_replaces_plan_and_publishes_valid_bundle(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_minimal_editor_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    source = Path(em.experiment_dir_path)
    original_plan = load_execution_plan(em.execution_plan_file_path)

    _apply_stream_editor_revision(em)
    result = model.commit_prepared_experiment_design_from_editor(
        requested_name="prepared-editor-renamed"
    )

    destination = source.parent / "prepared-editor-renamed"
    design = json.loads(
        (destination / "experiment_design.json").read_text(encoding="utf-8")
    )
    plan = load_execution_plan(destination / "execution_plan.json")
    bundle = inspect_authoritative_execution(destination, design)
    archived = (
        destination
        / "superseded_prepared_execution_plans"
        / original_plan.plan_id
    )

    assert result["status"] == "replaced"
    assert not source.exists()
    assert plan.plan_id != original_plan.plan_id
    assert plan.plan_revision == 1
    assert plan.state is ExecutionPlanState.PREPARED
    assert plan.design_sha256 == canonical_sha256(design)
    assert [well.well_id for well in plan.wells] == [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
    ]
    assert {stock.printing_mode for stock in plan.stocks} == {"stream"}
    assert bundle.valid
    assert bundle.eligibility.status == "ready_to_start"
    assert bundle.resume is None
    assert all(
        int(details["added_droplets"]) == 0
        for well in bundle.progress_wells.values()
        for details in well["reagents"].values()
    )
    assert load_execution_plan(
        archived / "prepared_plan_at_replacement.json"
    ) == original_plan
    assert json.loads(
        (archived / "experiment_design_at_replacement.json").read_text(
            encoding="utf-8"
        )
    )["metadata"]["name"] == "prepared-editor"
    assert not list(source.parent.glob(".*.staging-*"))
    assert not list(source.parent.glob(".*.rollback-*"))


def test_disk_loaded_untouched_prepared_design_is_editable_and_replaceable(
    experiment_model_factory,
):
    source_model = experiment_model_factory()
    source_em = source_model.experiment_model
    _configure_minimal_editor_design(source_em)
    Model.load_experiment_from_model(source_model, finalize_execution_plan=True)
    original_plan = load_execution_plan(source_em.execution_plan_file_path)

    loaded = experiment_model_factory()
    loaded_em = loaded.experiment_model
    bundle = loaded_em.load_experiment(
        source_em.experiment_file_path,
        source_em.experiment_dir_path,
    )

    assert bundle.valid
    assert bundle.eligibility.status == "ready_to_start"
    assert not loaded_em.is_execution_design_locked()
    loaded_em.metadata["printed_volume_tolerance_nL"] = 1.0
    loaded_em._clear_design_derived_state()
    assert loaded_em.optimize_stock_solutions()["best"]
    loaded_em.generate_experiment()

    result = loaded.commit_prepared_experiment_design_from_editor(
        requested_name="prepared-editor"
    )
    replacement = load_execution_plan(loaded_em.execution_plan_file_path)

    assert result["status"] == "replaced"
    assert replacement.plan_id != original_plan.plan_id
    assert replacement.volume_basis.design_optimization_tolerance_nL == 1.0
    assert not loaded_em.is_execution_design_locked()


def test_prepared_replacement_failure_leaves_original_directory_byte_identical(
    experiment_model_factory,
    monkeypatch,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_minimal_editor_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    source = Path(em.experiment_dir_path)
    before = _directory_bytes(source)
    original_save = model_module.save_execution_plan

    em.metadata["printed_volume_tolerance_nL"] = 1.0
    em._clear_design_derived_state()
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()

    def fail_replacement(path, plan):
        if plan.plan_id != em.get_execution_plan_snapshot().plan_id:
            raise OSError("injected prepared replacement failure")
        return original_save(path, plan)

    monkeypatch.setattr(model_module, "save_execution_plan", fail_replacement)

    with pytest.raises(
        RuntimeError, match="injected prepared replacement failure"
    ):
        model.commit_prepared_experiment_design_from_editor(
            requested_name="prepared-editor"
        )

    assert _directory_bytes(source) == before
    assert Path(em.experiment_dir_path) == source
    assert not list(source.parent.glob(".*.staging-*"))
    assert not list(source.parent.glob(".*.rollback-*"))


@pytest.mark.parametrize("start_reason", ["calibration_started", "printing_started"])
def test_prepared_design_replacement_rejects_started_execution_without_mutation(
    experiment_model_factory,
    start_reason,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_minimal_editor_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    em.lock_execution_plan(start_reason)
    source = Path(em.experiment_dir_path)
    before = _directory_bytes(source)

    em.metadata["printed_volume_tolerance_nL"] = 1.0
    with pytest.raises(
        RuntimeError,
        match="active authoritative execution|untouched PREPARED",
    ):
        model.commit_prepared_experiment_design_from_editor(
            requested_name="prepared-editor"
        )

    assert _directory_bytes(source) == before
    assert Path(em.experiment_dir_path) == source
    assert not list(source.parent.glob(".*.staging-*"))
    assert not list(source.parent.glob(".*.rollback-*"))


@pytest.mark.parametrize("start_reason", ["calibration_started", "printing_started"])
def test_prepared_rename_rejects_started_execution_without_mutation(
    experiment_model_factory,
    start_reason,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    em.lock_execution_plan(start_reason)
    original_dir = Path(em.experiment_dir_path)
    before = _directory_bytes(original_dir)
    original_name = json.loads(
        Path(em.experiment_file_path).read_text(encoding="utf-8")
    )["metadata"]["name"]

    em.metadata["name"] = f"rejected-{start_reason}"
    with pytest.raises(RuntimeError, match="untouched PREPARED"):
        em.rename_experiment(f"rejected-{start_reason}")

    assert em.metadata["name"] == original_name
    assert Path(em.experiment_dir_path) == original_dir
    assert _directory_bytes(original_dir) == before
    assert not (original_dir.parent / f"rejected-{start_reason}").exists()
    assert not list(original_dir.parent.glob(".*.staging-*"))
    assert not list(original_dir.parent.glob(".*.rollback-*"))


def test_prepared_rename_rejects_progress_and_rolls_back_reconciliation_failure(
    experiment_model_factory,
    monkeypatch,
):
    progress_model = experiment_model_factory()
    progress_em = progress_model.experiment_model
    _configure_design(progress_em)
    Model.load_experiment_from_model(progress_model, finalize_execution_plan=True)
    progress_path = Path(progress_em.progress_file_path)
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    stock_values = next(iter(progress["added_droplets"].values()))
    target_index = next(index for index, value in enumerate(stock_values) if value is not None)
    stock_values[target_index] = 1
    progress_path.write_text(serialize_execution_progress(progress), encoding="utf-8")
    progress_dir = Path(progress_em.experiment_dir_path)
    progress_before = _directory_bytes(progress_dir)

    progress_em.metadata["name"] = "rejected-progress"
    with pytest.raises(
        RuntimeError,
        match="untouched PREPARED|cannot be renamed|printing progress",
    ):
        progress_em.rename_experiment("rejected-progress")

    assert _directory_bytes(progress_dir) == progress_before
    assert not (progress_dir.parent / "rejected-progress").exists()

    rollback_model = experiment_model_factory()
    rollback_em = rollback_model.experiment_model
    _configure_design(rollback_em)
    Model.load_experiment_from_model(rollback_model, finalize_execution_plan=True)
    rollback_dir = Path(rollback_em.experiment_dir_path)
    rollback_before = _directory_bytes(rollback_dir)
    rollback_name = json.loads(
        Path(rollback_em.experiment_file_path).read_text(encoding="utf-8")
    )["metadata"]["name"]
    monkeypatch.setattr(
        rollback_em,
        "_write_execution_plan_exports",
        Mock(side_effect=OSError("injected key reconciliation failure")),
    )

    rollback_em.metadata["name"] = "failed-reconciliation"
    with pytest.raises(OSError, match="injected key reconciliation failure"):
        rollback_em.rename_experiment("failed-reconciliation")

    assert rollback_em.metadata["name"] == rollback_name
    assert Path(rollback_em.experiment_dir_path) == rollback_dir
    assert _directory_bytes(rollback_dir) == rollback_before
    assert not (rollback_dir.parent / "failed-reconciliation").exists()
    assert not list(rollback_dir.parent.glob(".*.staging-*"))
    assert not list(rollback_dir.parent.glob(".*.rollback-*"))


def test_lock_and_calibration_revision_preserve_design_and_allow_tolerance_overrun(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    design_path = Path(em.experiment_file_path)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    design_bytes = design_path.read_bytes()
    prepared = load_execution_plan(em.execution_plan_file_path)

    active = em.lock_execution_plan(
        "calibration_started",
        timestamp_utc=prepared.created_at_utc,
    )
    assert active.plan_revision == 2
    assert active.state is ExecutionPlanState.ACTIVE
    assert design_path.read_bytes() == design_bytes
    pure = next(stock for stock in active.stocks if stock.factor_name == "PURE_MM")
    result = em.apply_execution_calibration(
        stock_id=pure.stock_id,
        new_effective_volume_nL=143.59278258103592,
        printing_mode="stream",
        printer_head_id="head-1",
        factor_name="PURE_MM",
        option_name=None,
        is_fill=False,
        calibration_payload={
            "measured_volume_nL": 143.59278258103592,
            "pw_us": 1400,
            "pressure_psi": 1.2,
            "run_id": "run-1",
            "phase": "pressure_sweep_characterization",
            "timestamp": "2026-07-17T12:00:00Z",
            "source_row_fingerprint": ("run-1", 1400, 1.2),
            "original_printing_mode": "stream",
        },
        timestamp_utc=prepared.created_at_utc,
    )

    calibrated = result["plan"]
    assert calibrated.plan_id == prepared.plan_id
    assert calibrated.plan_revision == 3
    assert calibrated.locked_at_utc == active.locked_at_utc
    assert calibrated.lock_reason == active.lock_reason
    assert max(well.expected_printed_volume_nL for well in calibrated.wells) == pytest.approx(
        2559.9845212965747
    )
    assert max(well.expected_printed_volume_nL for well in calibrated.wells) > 2550.0
    assert design_path.read_bytes() == design_bytes
    history = validate_revision_history(
        em.execution_plan_revisions_dir_path,
        latest_plan=calibrated,
    )
    assert [plan.plan_revision for plan in history] == [1, 2, 3]
    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    assert progress["plan_revision"] == 3
    document = load_execution_calibrations(em.execution_calibrations_file_path)
    calibrated_stock = next(
        stock for stock in calibrated.stocks if stock.stock_id == pure.stock_id
    )
    assert calibrated_stock.calibration_record_key in document.records
    assert document.manual_refuel_checks
    em.ensure_execution_resume_checkpoint()
    assert em._active_authoritative_execution_session is not None
    passed = em.record_manual_refuel_check_outcome(
        status="passed",
        source="focused-test",
        stock_id=pure.stock_id,
        printer_head_id="head-1",
        printing_mode="stream",
        factor_name="PURE_MM",
        option_name=None,
        is_fill=False,
        trial_droplet_count=20,
        trial_count=2,
        operator_judgment="stable",
        save=True,
    )
    runtime_session = em._guard_authoritative_runtime_session()
    assert runtime_session.bundle.calibrations is not None
    assert any(
        check["status"] == "passed"
        and check["applied_calibration_fingerprint"]
        == passed["applied_calibration_fingerprint"]
        for check in runtime_session.bundle.calibrations.manual_refuel_checks.values()
    )
    assert em._authoritative_execution_bundle is runtime_session.bundle
    assert design_path.read_bytes() == design_bytes
    updated_document = load_execution_calibrations(em.execution_calibrations_file_path)
    assert any(
        check["status"] == "passed"
        and check["calibration_record_id"] == calibrated_stock.calibration_record_key
        for check in updated_document.manual_refuel_checks.values()
    )

    revision_bytes = {
        path.name: path.read_bytes()
        for path in Path(em.execution_plan_revisions_dir_path).glob("revision_*.json")
    }
    retry = em.apply_execution_calibration(
        stock_id=pure.stock_id,
        new_effective_volume_nL=143.59278258103592,
        printing_mode="stream",
        printer_head_id="head-1",
        factor_name="PURE_MM",
        option_name=None,
        is_fill=False,
        calibration_payload={
            "measured_volume_nL": 143.59278258103592,
            "pw_us": 1400,
            "pressure_psi": 1.2,
            "run_id": "run-1",
            "phase": "pressure_sweep_characterization",
            "timestamp": "2026-07-17T12:00:00Z",
            "source_row_fingerprint": ("run-1", 1400, 1.2),
            "original_printing_mode": "stream",
        },
        timestamp_utc=prepared.created_at_utc,
    )
    assert retry["status"] == "reused"
    assert retry["plan"].plan_revision == 3
    assert revision_bytes == {
        path.name: path.read_bytes()
        for path in Path(em.execution_plan_revisions_dir_path).glob("revision_*.json")
    }
    assert design_path.read_bytes() == design_bytes


def test_calibration_revision_accepts_plan_with_no_required_fill_stock(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_zero_fill_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    prepared = load_execution_plan(em.execution_plan_file_path)

    assert len(prepared.stocks) == 1
    stock = prepared.stocks[0]
    assert stock.factor_name == "reagent-1"
    assert all(
        {dispense.stock_id: dispense.target_dispenses for dispense in well.dispenses}
        == {stock.stock_id: 1}
        for well in prepared.wells
    )

    result = em.apply_execution_calibration(
        stock_id=stock.stock_id,
        new_effective_volume_nL=9.0,
        printing_mode="droplet",
        printer_head_id="head-zero-fill",
        factor_name="reagent-1",
        option_name=None,
        is_fill=False,
        calibration_payload={
            "measured_volume_nL": 9.0,
            "pw_us": 1300,
            "pressure_psi": 0.6,
            "run_id": "zero-fill-run",
            "phase": "synthetic_characterization",
            "timestamp": "2000-01-01T00:00:00Z",
            "source_row_fingerprint": (
                "zero-fill-run",
                "synthetic_characterization",
                1300,
                0.6,
                "droplet",
                9.0,
            ),
            "original_printing_mode": "droplet",
        },
        timestamp_utc=prepared.created_at_utc,
    )

    calibrated = result["plan"]
    assert result["status"] == "created"
    assert calibrated.plan_revision == 3
    assert len(calibrated.stocks) == 1
    assert calibrated.stocks[0].calibration_record_key == result["record"]["record_id"]
    assert calibrated.stocks[0].effective_volume_nL == pytest.approx(9.0)
    assert all(well.expected_printed_volume_nL == pytest.approx(9.0) for well in calibrated.wells)
    assert all(
        {dispense.stock_id: dispense.target_dispenses for dispense in well.dispenses}
        == {stock.stock_id: 1}
        for well in calibrated.wells
    )
    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    assert progress["plan_id"] == calibrated.plan_id
    assert progress["plan_revision"] == calibrated.plan_revision
    document = load_execution_calibrations(em.execution_calibrations_file_path)
    assert set(document.records) == {result["record"]["record_id"]}


def test_calibration_revision_rejects_missing_fill_stock_when_fill_is_required(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_zero_fill_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    prepared = load_execution_plan(em.execution_plan_file_path)
    stock = prepared.stocks[0]
    active = em.lock_execution_plan(
        "calibration_started",
        timestamp_utc=prepared.created_at_utc,
    )
    before = _directory_bytes(Path(em.experiment_dir_path))

    with pytest.raises(
        RuntimeError,
        match="would require a fill stock that is absent",
    ):
        em.apply_execution_calibration(
            stock_id=stock.stock_id,
            new_effective_volume_nL=20.0,
            printing_mode="droplet",
            printer_head_id="head-zero-fill",
            factor_name="reagent-1",
            option_name=None,
            is_fill=False,
            calibration_payload={
                "measured_volume_nL": 20.0,
                "pw_us": 1800,
                "pressure_psi": 0.6,
                "original_printing_mode": "droplet",
            },
            timestamp_utc=active.updated_at_utc,
        )

    assert em.get_execution_plan_snapshot() == active
    assert _directory_bytes(Path(em.experiment_dir_path)) == before
    assert not Path(em.execution_calibrations_file_path).exists()


def test_calibration_rejects_stock_with_printed_progress_without_new_revision(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    active = em.lock_execution_plan("printing_started")
    pure = next(stock for stock in active.stocks if stock.factor_name == "PURE_MM")
    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    stock_values = progress["added_droplets"][pure.stock_id]
    target_index = next(index for index, value in enumerate(stock_values) if value is not None)
    stock_values[target_index] = 1
    Path(em.progress_file_path).write_text(
        serialize_execution_progress(progress),
        encoding="utf-8",
    )
    em.read_progress_file(em.progress_file_path)
    before_plan = Path(em.execution_plan_file_path).read_bytes()
    before_history = sorted(Path(em.execution_plan_revisions_dir_path).glob("revision_*.json"))

    with pytest.raises(RuntimeError, match="already dispensed"):
        em.apply_execution_calibration(
            stock_id=pure.stock_id,
            new_effective_volume_nL=143.59278258103592,
            printing_mode="stream",
            printer_head_id="head-1",
            factor_name="PURE_MM",
            option_name=None,
            is_fill=False,
            calibration_payload={"pw_us": 1400, "pressure_psi": 1.2},
        )

    assert Path(em.execution_plan_file_path).read_bytes() == before_plan
    assert sorted(Path(em.execution_plan_revisions_dir_path).glob("revision_*.json")) == before_history


def test_calibration_application_eligibility_allows_mutable_design(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)

    result = em.get_calibration_application_eligibility(stock_id="draft-stock")

    assert result == {
        "ok": True,
        "code": "mutable_design",
        "message": "This calibration result may be applied to the experiment design.",
        "stock_id": "draft-stock",
    }


@pytest.mark.parametrize(
    ("result_producing", "expected_code"),
    (
        (False, "normal_diagnostics"),
        (True, "mutable_design"),
    ),
)
def test_calibration_process_start_eligibility_without_plan_requires_no_lock(
    experiment_model_factory,
    result_producing,
    expected_code,
):
    model = experiment_model_factory()
    _configure_design(model.experiment_model)

    result = model.get_calibration_process_start_eligibility(
        result_producing=result_producing,
        stock_id="draft-stock",
    )

    assert result["ok"] is True
    assert result["code"] == expected_code
    assert result["requires_execution_lock"] is False
    assert result["diagnostic_only"] is False
    assert result["plan_state"] is None


@pytest.mark.parametrize(
    "activate",
    (False, True),
    ids=("prepared", "active"),
)
def test_result_process_requires_lock_for_live_nonterminal_execution(
    experiment_model_factory,
    activate,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    if activate:
        em.lock_execution_plan("printing_started")
    plan = em.get_execution_plan_snapshot()
    stock = plan.stocks[0]

    result = model.get_calibration_process_start_eligibility(
        result_producing=True,
        stock_id=stock.stock_id,
    )

    assert result["ok"] is True
    assert result["code"] == "execution_lock_required"
    assert result["requires_execution_lock"] is True
    assert result["diagnostic_only"] is False
    assert result["plan_state"] == ("active" if activate else "prepared")


def test_result_process_start_policy_keeps_missing_progress_and_runtime_fail_closed(
    experiment_model_factory,
    monkeypatch,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    stock = em.get_execution_plan_snapshot().stocks[0]

    missing_stock = model.get_calibration_process_start_eligibility(
        result_producing=True
    )
    assert missing_stock["ok"] is False
    assert missing_stock["code"] == "missing_stock_context"

    outside_plan = model.get_calibration_process_start_eligibility(
        result_producing=True,
        stock_id="outside-plan-stock",
    )
    assert outside_plan["ok"] is True
    assert outside_plan["diagnostic_only"] is True
    assert outside_plan["requires_diagnostic_confirmation"] is True
    assert outside_plan["application_eligibility_code"] == "stock_not_in_execution"

    monkeypatch.setattr(
        em,
        "_added_droplets_for_stock",
        Mock(side_effect=RuntimeError("corrupt progress")),
    )
    bad_progress = model.get_calibration_process_start_eligibility(
        result_producing=True,
        stock_id=stock.stock_id,
    )
    assert bad_progress["ok"] is False
    assert bad_progress["code"] == "progress_unavailable"
    assert bad_progress["requires_diagnostic_confirmation"] is False

    monkeypatch.setattr(em, "_added_droplets_for_stock", Mock(return_value=0))
    monkeypatch.setattr(
        em,
        "_validate_runtime_matches_execution_plan",
        Mock(side_effect=RuntimeError("runtime mismatch")),
    )
    bad_runtime = model.get_calibration_process_start_eligibility(
        result_producing=True,
        stock_id=stock.stock_id,
    )
    assert bad_runtime["ok"] is False
    assert bad_runtime["code"] == "runtime_unavailable"
    assert bad_runtime["requires_diagnostic_confirmation"] is False


def test_historical_and_inactive_persisted_executions_reject_calibration_start(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    em._execution_plan_source = "persisted_execution_plan"
    em._authoritative_runtime_active = False

    inactive = model.get_calibration_process_start_eligibility(result_producing=True)

    assert inactive["ok"] is False
    assert inactive["code"] == "inactive_persisted_execution"
    assert inactive["plan_state"] == "prepared"

    model._read_only_experiment_view_active = True
    for result_producing in (False, True):
        historical = model.get_calibration_process_start_eligibility(
            result_producing=result_producing
        )
        assert historical["ok"] is False
        assert historical["code"] == "historical_read_only"
        assert historical["requires_execution_lock"] is False


def test_calibration_application_eligibility_is_stock_specific_after_progress(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    active = em.lock_execution_plan("printing_started")
    printed_stock = next(stock for stock in active.stocks if stock.factor_name == "PURE_MM")
    unprinted_stock = next(stock for stock in active.stocks if stock.stock_id != printed_stock.stock_id)

    assert em.get_calibration_application_eligibility(
        stock_id=printed_stock.stock_id
    )["ok"] is True
    assert em.get_calibration_application_eligibility(
        stock_id=unprinted_stock.stock_id
    )["ok"] is True

    em._execution_plan_source = "persisted_execution_plan"
    em._execution_plan_reload_read_only = True
    em._authoritative_runtime_active = True
    activated = em.get_calibration_application_eligibility(
        stock_id=unprinted_stock.stock_id
    )
    assert activated["ok"] is True
    assert activated["code"] == "execution_stock_eligible"

    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    stock_values = progress["added_droplets"][printed_stock.stock_id]
    target_index = next(index for index, value in enumerate(stock_values) if value is not None)
    stock_values[target_index] = 1
    Path(em.progress_file_path).write_text(
        serialize_execution_progress(progress),
        encoding="utf-8",
    )
    em.read_progress_file(em.progress_file_path)

    printed = em.get_calibration_application_eligibility(
        stock_id=printed_stock.stock_id
    )
    unprinted = em.get_calibration_application_eligibility(
        stock_id=unprinted_stock.stock_id
    )

    assert printed["ok"] is False
    assert printed["code"] == "printed_progress"
    assert "already dispensed" in printed["message"]
    assert unprinted["ok"] is True
    assert unprinted["code"] == "execution_stock_eligible"

    diagnostic_start = model.get_calibration_process_start_eligibility(
        result_producing=True,
        stock_id=printed_stock.stock_id,
    )
    assert diagnostic_start["ok"] is True
    assert diagnostic_start["diagnostic_only"] is True
    assert diagnostic_start["requires_diagnostic_confirmation"] is True
    assert diagnostic_start["application_eligibility_code"] == "printed_progress"

    normal_start = model.get_calibration_process_start_eligibility(
        result_producing=True,
        stock_id=unprinted_stock.stock_id,
    )
    assert normal_start["ok"] is True
    assert normal_start["diagnostic_only"] is False
    assert normal_start["requires_diagnostic_confirmation"] is False


@pytest.mark.parametrize(
    ("terminal_state", "message_fragment"),
    (
        (ExecutionPlanState.COMPLETED, "experiment is complete"),
        (ExecutionPlanState.ABORTED, "execution was aborted"),
    ),
)
def test_terminal_execution_disables_apply_without_writing(
    experiment_model_factory,
    terminal_state,
    message_fragment,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    active = em.lock_execution_plan("printing_started")
    stock = active.stocks[0]
    terminal_counts = {
        well.well_id: {
            dispense.stock_id: (
                dispense.target_dispenses
                if terminal_state is ExecutionPlanState.COMPLETED
                else 0
            )
            for dispense in well.dispenses
        }
        for well in active.wells
    }
    terminal = build_terminal_revision(
        active,
        state=terminal_state,
        added_counts_by_well=terminal_counts,
        reason="test_terminal_calibration_eligibility",
    )
    em._execution_plan_snapshot = terminal
    em._last_authoritative_calibration_transition = "unchanged"
    before = _directory_bytes(Path(em.experiment_dir_path))

    process_eligibility = model.get_calibration_process_start_eligibility(
        result_producing=True,
        stock_id=stock.stock_id,
    )
    eligibility = em.get_calibration_application_eligibility(stock_id=stock.stock_id)

    assert process_eligibility["ok"] is True
    assert process_eligibility["code"] == "diagnostic_only_confirmation_required"
    assert process_eligibility["requires_execution_lock"] is False
    assert process_eligibility["diagnostic_only"] is True
    assert process_eligibility["requires_diagnostic_confirmation"] is True
    assert process_eligibility["application_eligibility_code"] == "terminal_execution"
    assert process_eligibility["plan_state"] == terminal_state.value
    assert eligibility["ok"] is False
    assert eligibility["code"] == "terminal_execution"
    assert message_fragment in eligibility["message"]
    with pytest.raises(RuntimeError, match=message_fragment):
        em.apply_execution_calibration(
            stock_id=stock.stock_id,
            new_effective_volume_nL=stock.effective_volume_nL,
            printing_mode=stock.printing_mode,
            printer_head_id="head-terminal",
            factor_name=stock.factor_name,
            option_name=stock.option_name,
            is_fill=stock.units == "--",
            calibration_payload={"pw_us": 1400, "pressure_psi": 1.2},
        )

    assert em._last_authoritative_calibration_transition == "unchanged"
    assert _directory_bytes(Path(em.experiment_dir_path)) == before


def test_lock_retry_repairs_progress_after_durable_revision_partial_failure(
    experiment_model_factory, monkeypatch
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    original_write_progress = em._write_progress_for_execution_plan
    calls = {"count": 0}

    def fail_once(plan):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("progress unavailable")
        return original_write_progress(plan)

    monkeypatch.setattr(em, "_write_progress_for_execution_plan", fail_once)
    with pytest.raises(RuntimeError, match="progress unavailable"):
        em.lock_execution_plan("printing_started")

    durable = load_execution_plan(em.execution_plan_file_path)
    assert durable.state is ExecutionPlanState.ACTIVE
    assert durable.plan_revision == 2
    revision_bytes = Path(
        em.execution_plan_revisions_dir_path,
        "revision_000002.json",
    ).read_bytes()
    assert em.get_execution_plan_sync_error()

    repaired = em.lock_execution_plan("printing_started")

    assert repaired == durable
    assert repaired.plan_revision == 2
    assert Path(
        em.execution_plan_revisions_dir_path,
        "revision_000002.json",
    ).read_bytes() == revision_bytes
    assert em.get_progress_execution_reference().plan_revision == 2
    assert em.get_execution_plan_sync_error() is None


def test_active_plan_reload_is_nonmutating_read_only_and_cannot_resume(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    active = em.lock_execution_plan("printing_started")
    experiment_dir = Path(em.experiment_dir_path)
    before = {
        path.relative_to(experiment_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in experiment_dir.rglob("*")
        if path.is_file()
    }

    loaded = ExperimentModel(prof=CURRENT_PROFILE)
    loaded.load_experiment(
        str(experiment_dir / "experiment_design.json"),
        str(experiment_dir),
    )

    after = {
        path.relative_to(experiment_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in experiment_dir.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert loaded.get_execution_plan_snapshot() == active
    assert loaded.get_execution_plan_source() == "persisted_execution_plan"
    assert loaded.is_execution_design_locked()
    assert loaded.get_execution_plan_sync_error() is None
    assert loaded.get_stock_table_rows(include_fill=True)
    with pytest.raises(RuntimeError, match="analysis only"):
        loaded.lock_execution_plan("printing_started")


def test_calibration_retry_reuses_committed_revision_after_export_failure(
    experiment_model_factory, monkeypatch
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    active = em.lock_execution_plan("calibration_started")
    pure = next(stock for stock in active.stocks if stock.factor_name == "PURE_MM")
    original_exports = em._write_execution_plan_exports
    calls = {"count": 0}

    def fail_once(plan, design_payload):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("key export unavailable")
        return original_exports(plan, design_payload)

    monkeypatch.setattr(em, "_write_execution_plan_exports", fail_once)
    kwargs = {
        "stock_id": pure.stock_id,
        "new_effective_volume_nL": 143.59278258103592,
        "printing_mode": "stream",
        "printer_head_id": "head-1",
        "factor_name": "PURE_MM",
        "option_name": None,
        "is_fill": False,
        "calibration_payload": {
            "measured_volume_nL": 143.59278258103592,
            "pw_us": 1400,
            "pressure_psi": 1.2,
            "run_id": "run-1",
            "phase": "pressure_sweep_characterization",
            "timestamp": "2026-07-17T12:00:00Z",
        },
    }
    with pytest.raises(RuntimeError, match="key export unavailable"):
        em.apply_execution_calibration(**kwargs)

    committed = load_execution_plan(em.execution_plan_file_path)
    assert committed.plan_revision == 3
    assert em.get_execution_plan_sync_error()
    revision_bytes = Path(
        em.execution_plan_revisions_dir_path,
        "revision_000003.json",
    ).read_bytes()

    retry = em.apply_execution_calibration(**kwargs)

    assert retry["status"] == "reused"
    assert retry["plan"] == committed
    assert Path(
        em.execution_plan_revisions_dir_path,
        "revision_000003.json",
    ).read_bytes() == revision_bytes
    assert em.get_execution_plan_sync_error() is None
    runtime_reaction = next(
        reaction
        for reaction in model.reaction_collection.get_all_reactions()
        if reaction.unique_id == committed.wells[0].reaction_id
    )
    committed_counts = {
        dispense.stock_id: dispense.target_dispenses
        for dispense in committed.wells[0].dispenses
    }
    assert {
        stock_id: reagent.get_target_droplets()
        for stock_id, reagent in runtime_reaction.get_all_reagents().items()
    } == committed_counts


def test_ordinary_runtime_load_does_not_write_plan_or_progress_link(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)

    Model.load_experiment_from_model(model, load_progress=False)

    assert not Path(em.execution_plan_file_path).exists()
    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    assert "__execution__" not in progress


def test_manual_well_assignments_are_captured_exactly(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    explicit = ["B2", "D4"]
    assert em.get_number_of_reactions() == len(explicit)
    em._uploaded_well_ids = explicit

    Model.load_experiment_from_model(model, finalize_execution_plan=True)

    plan = load_execution_plan(em.execution_plan_file_path)
    by_reaction = {
        well.reaction_id: well.well_id
        for well in plan.wells
    }
    assert [by_reaction[f"R{i + 1}"] for i in range(len(explicit))] == explicit


def test_explicit_uploaded_design_can_preview_and_apply_calibration(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_explicit_uploaded_design(em)

    Model.load_experiment_from_model(model, finalize_execution_plan=True)

    prepared = load_execution_plan(em.execution_plan_file_path)
    stock = next(item for item in prepared.stocks if item.factor_name == "Signal")
    assert em.metadata["replicates"] == 1
    assert "_original_replicates" not in em.metadata
    assert [well.well_id for well in prepared.wells] == ["A1", "B2"]

    projected = em.get_calibration_application_plan_for_key(("Signal", None))
    assert projected["source"] == "authoritative_execution_plan"
    prepared_counts_by_well = {
        well.well_id: next(
            dispense.target_dispenses
            for dispense in well.dispenses
            if dispense.stock_id == stock.stock_id
        )
        for well in prepared.wells
    }
    assert projected["stocks"][0]["droplets_per_target"] == {
        0.4: prepared_counts_by_well["A1"],
        1.0: prepared_counts_by_well["B2"],
    }

    preview = em.preview_requantized_for_option(("Signal", None), 12.0)
    assert preview["ok"] is True
    assert [row["drops"] for row in preview["rows"]] == [2, 4]

    result = em.apply_droplet_volume_for_option(
        "Signal",
        None,
        12.0,
        printing_mode="droplet",
        applied_calibration={
            "printer_head": SimpleNamespace(printer_head_id="explicit-head-1"),
            "measured_volume_nL": 12.0,
            "pw_us": 1300,
            "pressure_psi": 0.6,
            "run_id": "explicit-upload-run",
            "phase": "synthetic_characterization",
            "timestamp": "2000-01-01T00:00:00Z",
            "source_row_fingerprint": (
                "explicit-upload-run",
                "synthetic_characterization",
                1300,
                0.6,
                "droplet",
                12.0,
            ),
            "original_printing_mode": "droplet",
            "applied_printing_mode": "droplet",
        },
    )

    calibrated = load_execution_plan(em.execution_plan_file_path)
    assert result["execution_plan_revision"] == 3
    assert calibrated.plan_id == prepared.plan_id
    assert calibrated.plan_revision == 3
    calibrated_stock = next(
        item for item in calibrated.stocks if item.stock_id == stock.stock_id
    )
    assert calibrated_stock.effective_volume_nL == pytest.approx(12.0)
    counts_by_well = {
        well.well_id: next(
            dispense.target_dispenses
            for dispense in well.dispenses
            if dispense.stock_id == stock.stock_id
        )
        for well in calibrated.wells
    }
    assert counts_by_well == {"A1": 2, "B2": 4}


def test_sparse_explicit_uploaded_design_fill_preview_matches_committed_revision(
    experiment_model_factory,
    monkeypatch,
):
    model = experiment_model_factory()
    em = model.experiment_model
    well_ids = ["A1", "A6", "B3", "C9", "D2", "E11", "F5", "G8", "H12"]
    frame = pd.DataFrame(
        {
            "Well": well_ids,
            "Signal A (mM)": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
            "Signal B (mM)": [0.0, 0.2, 0.0, 0.4, 0.0, 0.6, 0.0, 0.8, 0.0],
            "Signal C (mM)": [0.5, 0.0, 0.4, 0.0, 0.3, 0.0, 0.2, 0.0, 0.1],
            "Signal D (mM)": [0.1] * len(well_ids),
        }
    )
    em.set_metadata(
        name="sparse-explicit-fill-calibration",
        randomize_assignments=False,
        replicates=1,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        printed_volume_tolerance_nL=50.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    em.set_uploaded_design_from_dataframe(frame)
    for factor in em.factors:
        factor.options[0].forced_stock_conc = 10.0
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()

    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    prepared = load_execution_plan(em.execution_plan_file_path)
    fill_stocks = [
        stock
        for stock in prepared.stocks
        if stock.factor_name == "Water" and stock.units == "--"
    ]
    assert len(fill_stocks) == 1
    fill_stock = fill_stocks[0]
    assert [well.well_id for well in prepared.wells] == well_ids

    monkeypatch.setattr(
        em,
        "generate_experiment",
        Mock(side_effect=AssertionError("finalized fill preview regenerated the design")),
    )
    monkeypatch.setattr(
        em,
        "_iter_reaction_run_specs",
        Mock(side_effect=AssertionError("finalized fill preview consulted mutable design inputs")),
    )
    preview = em.preview_fill_requantized(9.5)
    assert preview["ok"] is True
    assert list(preview["well_ids"]) == well_ids

    result = em.apply_fill_droplet_volume(
        9.5,
        printing_mode="droplet",
        applied_calibration={
            "printer_head": SimpleNamespace(printer_head_id="durable-fill-head"),
            "measured_volume_nL": 9.5,
            "pw_us": 1300,
            "pressure_psi": 0.6,
            "run_id": "sparse-fill-run",
            "phase": "pressure_sweep_characterization",
            "timestamp": "2026-08-25T00:00:00Z",
            "source_row_fingerprint": ("sparse-fill-run", 1300, 0.6, 9.5),
            "original_printing_mode": "droplet",
        },
    )

    calibrated = load_execution_plan(em.execution_plan_file_path)
    assert calibrated.plan_revision == prepared.plan_revision + 2
    assert [well.well_id for well in calibrated.wells] == well_ids
    committed_counts = {
        well.well_id: next(
            (
                dispense.target_dispenses
                for dispense in well.dispenses
                if dispense.stock_id == fill_stock.stock_id
            ),
            0,
        )
        for well in calibrated.wells
    }
    assert committed_counts == {
        well_id: counts.get(fill_stock.stock_id, 0)
        for well_id, counts in preview["target_counts_by_well"].items()
    }
    assert result["total_drops_new"] == preview["total_drops_new"]
    assert result["total_drops_old"] == preview["total_drops_old"]

    reloaded = ExperimentModel(prof=CURRENT_PROFILE)
    reloaded.load_experiment(
        em.experiment_file_path,
        em.experiment_dir_path,
    )
    assert reloaded.get_execution_plan_snapshot() == calibrated


def test_initialize_and_duplicate_do_not_create_execution_plan(
    tmp_path, experiment_model_factory
):
    initialized = ExperimentModel(prof=CURRENT_PROFILE)
    initialized.metadata["name"] = "initialized-only"
    initialized.initialize_experiment(base_dir=str(tmp_path))
    assert not Path(initialized.execution_plan_file_path).exists()

    source_model = experiment_model_factory()
    source = source_model.experiment_model
    _configure_design(source)
    duplicate_dir = tmp_path / "duplicate-only"
    source.duplicate_design_from(
        source.experiment_file_path,
        "duplicate-only",
        str(duplicate_dir),
    )
    assert not (duplicate_dir / "execution_plan.json").exists()


def test_identical_finalization_retry_reuses_plan_bytes_and_identity(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    plan_path = Path(em.execution_plan_file_path)
    before = plan_path.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()
    first_plan = load_execution_plan(plan_path)

    Model.load_experiment_from_model(model, finalize_execution_plan=True)

    assert hashlib.sha256(plan_path.read_bytes()).hexdigest() == before_hash
    assert load_execution_plan(plan_path).plan_id == first_plan.plan_id
    audit_rows = [
        json.loads(line)
        for line in Path(em.experiment_audit_file_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert audit_rows[-1]["details"]["execution_plan_status"] == "reused"


def test_plan_is_persisted_before_progress_and_keys(
    experiment_model_factory, monkeypatch
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    calls = []
    original_plan = em.create_or_reuse_initial_execution_plan
    original_progress = em.create_progress_file
    original_key = em.create_key_file
    original_concentration = em.create_concentration_key_file

    monkeypatch.setattr(
        em,
        "create_or_reuse_initial_execution_plan",
        lambda: (calls.append("plan"), original_plan())[1],
    )
    monkeypatch.setattr(
        em,
        "create_progress_file",
        lambda *args, **kwargs: (
            calls.append("progress"),
            original_progress(*args, **kwargs),
        )[1],
    )
    monkeypatch.setattr(
        em,
        "create_key_file",
        lambda *args, **kwargs: (calls.append("key"), original_key(*args, **kwargs))[1],
    )
    monkeypatch.setattr(
        em,
        "create_concentration_key_file",
        lambda *args, **kwargs: (
            calls.append("concentration"),
            original_concentration(*args, **kwargs),
        )[1],
    )

    Model.load_experiment_from_model(model, finalize_execution_plan=True)

    assert calls[:4] == ["plan", "progress", "key", "concentration"]


def test_conflicting_existing_plan_fails_closed_without_overwrite(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    plan_path = Path(em.execution_plan_file_path)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["design_sha256"] = "b" * 64
    plan_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    conflict_bytes = plan_path.read_bytes()
    progress_bytes = Path(em.progress_file_path).read_bytes()

    with pytest.raises(RuntimeError, match="does not match"):
        Model.load_experiment_from_model(model, finalize_execution_plan=True)

    assert plan_path.read_bytes() == conflict_bytes
    assert Path(em.progress_file_path).read_bytes() == progress_bytes
    assert em.get_execution_plan_finalization_error()
    assert model.reaction_collection.get_all_reactions() == []
    assert all(
        well.get_assigned_reaction() is None for well in model.well_plate.get_all_wells()
    )


def test_invalid_existing_plan_fails_closed_without_overwrite(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    plan_path = Path(em.execution_plan_file_path)
    invalid_bytes = b'{"schema_name":"not-an-execution-plan"}\n'
    plan_path.write_bytes(invalid_bytes)

    with pytest.raises(RuntimeError, match="execution_plan"):
        Model.load_experiment_from_model(model, finalize_execution_plan=True)

    assert plan_path.read_bytes() == invalid_bytes
    assert not Path(em.progress_file_path).exists()
    assert not Path(em.key_file_path).exists()
    assert not Path(em.concentration_key_file_path).exists()
    assert em.get_execution_plan_finalization_error()
    assert model.reaction_collection.get_all_reactions() == []


def test_plan_write_failure_creates_no_runtime_artifacts_or_success_signal(
    experiment_model_factory, monkeypatch
):
    model = experiment_model_factory()
    model.experiment_loaded = Mock()
    em = model.experiment_model
    _configure_design(em)

    def fail_write(_path, _plan):
        raise OSError("disk unavailable")

    monkeypatch.setattr(model_module, "save_execution_plan", fail_write)

    with pytest.raises(RuntimeError, match="disk unavailable"):
        Model.load_experiment_from_model(model, finalize_execution_plan=True)

    assert not Path(em.execution_plan_file_path).exists()
    assert not Path(em.progress_file_path).exists()
    assert not Path(em.key_file_path).exists()
    assert not Path(em.concentration_key_file_path).exists()
    model.experiment_loaded.emit.assert_not_called()
    assert em.get_execution_plan_finalization_error() == "disk unavailable"


def test_retry_after_key_failure_reuses_durable_plan_and_completes(
    experiment_model_factory, monkeypatch
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    original_create_key = em.create_key_file
    calls = {"count": 0}

    def fail_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("key unavailable")
        return original_create_key(*args, **kwargs)

    monkeypatch.setattr(em, "create_key_file", fail_once)
    with pytest.raises(RuntimeError, match="key unavailable"):
        Model.load_experiment_from_model(model, finalize_execution_plan=True)

    plan_path = Path(em.execution_plan_file_path)
    plan_bytes = plan_path.read_bytes()
    plan_id = load_execution_plan(plan_path).plan_id

    Model.load_experiment_from_model(model, finalize_execution_plan=True)

    assert plan_path.read_bytes() == plan_bytes
    assert load_execution_plan(plan_path).plan_id == plan_id
    assert Path(em.key_file_path).exists()
    assert Path(em.concentration_key_file_path).exists()
    assert em.get_execution_plan_finalization_error() is None
