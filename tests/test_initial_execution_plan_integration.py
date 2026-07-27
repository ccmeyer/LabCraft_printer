import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import Model as model_module
from AuthoritativeExecutionLoad import inspect_authoritative_execution
from ExecutionPlan import ExecutionPlanState, canonical_sha256, load_execution_plan
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


def test_prepared_name_only_rename_replaces_and_reloads_authoritative_bundle(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    original_dir = Path(em.experiment_dir_path)
    original_plan = load_execution_plan(em.execution_plan_file_path)

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

    reloaded = ExperimentModel(prof=CURRENT_PROFILE)
    reloaded_bundle = reloaded.load_experiment(
        str(renamed_dir / "experiment_design.json"),
        str(renamed_dir),
    )
    assert reloaded_bundle.valid
    assert reloaded_bundle.plan == plan
    assert reloaded_bundle.eligibility.status == "ready_to_start"


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
    em.record_manual_refuel_check_outcome(
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
