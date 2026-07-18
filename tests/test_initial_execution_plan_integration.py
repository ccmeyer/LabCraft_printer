import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import Model as model_module
from ExecutionPlan import ExecutionPlanState, canonical_sha256, load_execution_plan
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


def _well_targets(plan):
    return {
        well.well_id: {
            dispense.stock_id: dispense.target_dispenses for dispense in well.dispenses
        }
        for well in plan.wells
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
    assert progress["__execution__"] == {
        "schema_version": 1,
        "plan_id": plan.plan_id,
        "plan_revision": 1,
    }
    assert em.get_progress_execution_reference().plan_id == plan.plan_id
    assert set(em.return_progress_data()) == {well.well_id for well in plan.wells}
    assert em.get_progress_status()["well_count"] == len(plan.wells)
    progress_wells = {
        well_id: {
            stock_id: int(counts["target_droplets"])
            for stock_id, counts in entry["reagents"].items()
        }
        for well_id, entry in progress.items()
        if not well_id.startswith("__")
    }
    assert progress_wells == _well_targets(plan)
    assert all(stock.printer_head_id is None for stock in plan.stocks)
    assert all(stock.calibration_record_key is None for stock in plan.stocks)

    audit_rows = [
        json.loads(line)
        for line in Path(em.experiment_audit_file_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    details = audit_rows[-1]["details"]
    assert details["execution_plan_id"] == plan.plan_id
    assert details["execution_plan_revision"] == 1
    assert details["execution_plan_status"] == "created"


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
