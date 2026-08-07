import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

import Model as model_module
from ExecutionCalibrationStore import (
    ExecutionCalibrationDocument,
    load_execution_calibrations,
    save_execution_calibrations,
)
from ExecutionPlanRevision import validate_revision_history
from ExecutionResumeStore import (
    load_execution_resume,
    progress_fingerprint,
    save_execution_resume,
    utc_now_text,
)
from Model import Model


def _configure_design(experiment_model):
    experiment_model.factors = []
    experiment_model.add_additive(
        "CACHE_TEST",
        [1.0],
        "x",
        10.0,
        forced_stock_conc=1.0,
    )
    experiment_model.set_metadata(
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=2,
        target_reaction_volume_nL=100.0,
        final_reaction_volume_nL=100.0,
        printed_volume_tolerance_nL=0.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    assert experiment_model.optimize_stock_solutions()["best"]
    experiment_model.generate_experiment()
    experiment_model.save_experiment()


def _active_runtime(experiment_model_factory):
    model = experiment_model_factory()
    experiment_model = model.experiment_model
    _configure_design(experiment_model)
    Model.load_experiment_from_model(
        model,
        load_progress=False,
        finalize_execution_plan=True,
    )
    plan = experiment_model.lock_execution_plan("printing_started")
    experiment_model.ensure_execution_resume_checkpoint()
    experiment_model._authoritative_runtime_active = True
    dispense = next(
        dispense
        for well in plan.wells
        for dispense in well.dispenses
        if dispense.target_dispenses > 0
    )
    well_spec = next(
        well
        for well in plan.wells
        if any(item.stock_id == dispense.stock_id for item in well.dispenses)
    )
    return model, experiment_model, well_spec, dispense


def _complete_one(model, experiment_model, well_spec, dispense, *, command=41):
    intent_id = experiment_model.begin_execution_print_intent(
        well_id=well_spec.well_id,
        stock_id=dispense.stock_id,
        commanded_droplets=1,
        printer_head_id="cache-test-head",
    )
    experiment_model.attach_execution_print_command(intent_id, command)
    model.well_plate.get_well(well_spec.well_id).record_stock_print(
        dispense.stock_id,
        1,
    )
    experiment_model.create_progress_file(execution_intent_id=intent_id)
    experiment_model.complete_execution_print_intent(intent_id)
    return intent_id


def _apply_cached_calibration(
    experiment_model,
    *,
    effective_volume_nL=9.0,
    run_id="cache-calibration-1",
    timestamp_utc="2099-08-07T12:00:00Z",
):
    plan = experiment_model.get_execution_plan_snapshot()
    stock = next(
        item
        for item in plan.stocks
        if item.units != "--"
    )
    return experiment_model.apply_execution_calibration(
        stock_id=stock.stock_id,
        new_effective_volume_nL=float(effective_volume_nL),
        printing_mode=stock.printing_mode,
        printer_head_id="cache-calibration-head",
        factor_name=stock.factor_name,
        option_name=stock.option_name,
        is_fill=False,
        calibration_payload={
            "measured_volume_nL": float(effective_volume_nL),
            "pw_us": 1200,
            "pressure_psi": 0.8,
            "run_id": run_id,
            "phase": "cache_test",
            "timestamp": timestamp_utc,
            "source_row_fingerprint": (
                run_id,
                1200,
                0.8,
                stock.printing_mode,
                float(effective_volume_nL),
            ),
            "original_printing_mode": stock.printing_mode,
        },
        timestamp_utc=timestamp_utc,
    )


def test_hot_path_uses_cache_and_preserves_four_durable_writes(
    experiment_model_factory,
    monkeypatch,
):
    model, experiment_model, well_spec, dispense = _active_runtime(
        experiment_model_factory
    )
    calls = {
        "inspect": 0,
        "load": 0,
        "save": 0,
        "guard": 0,
        "fsync": 0,
        "replace": 0,
    }
    original_inspect = model_module.inspect_authoritative_execution
    original_load = model_module.load_execution_resume
    original_save = model_module.save_execution_resume
    original_guard = experiment_model._guard_authoritative_runtime_session
    original_fsync = os.fsync
    original_replace = os.replace

    def observed_inspect(*args, **kwargs):
        calls["inspect"] += 1
        return original_inspect(*args, **kwargs)

    def observed_load(*args, **kwargs):
        calls["load"] += 1
        return original_load(*args, **kwargs)

    def observed_save(*args, **kwargs):
        calls["save"] += 1
        return original_save(*args, **kwargs)

    def observed_guard(*args, **kwargs):
        calls["guard"] += 1
        return original_guard(*args, **kwargs)

    def observed_fsync(*args, **kwargs):
        calls["fsync"] += 1
        return original_fsync(*args, **kwargs)

    def observed_replace(*args, **kwargs):
        calls["replace"] += 1
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(model_module, "inspect_authoritative_execution", observed_inspect)
    monkeypatch.setattr(model_module, "load_execution_resume", observed_load)
    monkeypatch.setattr(model_module, "save_execution_resume", observed_save)
    monkeypatch.setattr(
        experiment_model,
        "_guard_authoritative_runtime_session",
        observed_guard,
    )
    monkeypatch.setattr(os, "fsync", observed_fsync)
    monkeypatch.setattr(os, "replace", observed_replace)

    intent_id = _complete_one(model, experiment_model, well_spec, dispense)

    assert calls == {
        "inspect": 0,
        "load": 0,
        "save": 3,
        "guard": 4,
        "fsync": 4,
        "replace": 4,
    }
    checkpoint = load_execution_resume(experiment_model.execution_resume_file_path)
    assert intent_id
    assert checkpoint.intents == ()
    assert checkpoint.state == "clean"
    assert experiment_model.get_execution_resume_eligibility()["status"] in {
        "ready_to_resume",
        "complete",
    }


def test_active_plan_lock_uses_guarded_cache_without_recovery_or_writes(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment_model, _well_spec, _dispense = _active_runtime(
        experiment_model_factory
    )
    cached = experiment_model.get_execution_plan_snapshot()
    calls = {"guard": 0}
    original_guard = experiment_model._guard_authoritative_runtime_session

    def observed_guard():
        calls["guard"] += 1
        return original_guard()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("guarded ACTIVE lock used the recovery/write path")

    monkeypatch.setattr(
        experiment_model,
        "_guard_authoritative_runtime_session",
        observed_guard,
    )
    for method_name in (
        "_recover_persisted_execution_plan_for_transition",
        "_write_progress_for_execution_plan",
        "synchronize_execution_resume_revision",
    ):
        monkeypatch.setattr(experiment_model, method_name, unexpected)

    assert experiment_model.lock_execution_plan("calibration_started") is cached
    assert calls == {"guard": 1}


def test_calibration_revision_uses_guarded_successor_without_full_history_reload(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment_model, _well_spec, _dispense = _active_runtime(
        experiment_model_factory
    )
    starting_revision = experiment_model.get_execution_plan_snapshot().plan_revision
    calls = {"inspect": 0, "full_history": 0}

    def forbidden_inspect(*_args, **_kwargs):
        calls["inspect"] += 1
        raise AssertionError("cached calibration performed full bundle inspection")

    def forbidden_history(*_args, **_kwargs):
        calls["full_history"] += 1
        raise AssertionError("cached calibration reread immutable history")

    monkeypatch.setattr(model_module, "inspect_authoritative_execution", forbidden_inspect)
    monkeypatch.setattr(model_module, "validate_revision_history", forbidden_history)

    first = _apply_cached_calibration(experiment_model)
    second = _apply_cached_calibration(
        experiment_model,
        effective_volume_nL=8.5,
        run_id="cache-calibration-2",
        timestamp_utc="2099-08-07T12:01:00Z",
    )

    assert calls == {"inspect": 0, "full_history": 0}
    assert first["status"] == second["status"] == "created"
    assert second["plan"].plan_revision == starting_revision + 2
    session = experiment_model._guard_authoritative_runtime_session()
    assert session.bundle.plan == second["plan"]
    assert session.bundle.history[-2:] == (first["plan"], second["plan"])
    assert session.resume.plan_revision == second["plan"].plan_revision
    assert session.revision_names[-2:] == (
        f"revision_{starting_revision + 1:06d}.json",
        f"revision_{starting_revision + 2:06d}.json",
    )
    assert experiment_model._last_authoritative_calibration_transition == {
        "cache_path": "cached_revision",
        "starting_plan_revision": starting_revision + 1,
        "final_plan_revision": starting_revision + 2,
        "created_revision": f"revision_{starting_revision + 2:06d}.json",
        "full_validation_count": 0,
        "prior_revision_body_read_count": 0,
    }
    document = load_execution_calibrations(
        experiment_model.execution_calibrations_file_path
    )
    assert set(document.records) == {
        first["record"]["record_id"],
        second["record"]["record_id"],
    }


@pytest.mark.parametrize(
    "method_name",
    [
        "_write_authoritative_calibration_document",
        "_persist_authoritative_calibration_immutable_revision",
        "_write_authoritative_calibration_current_plan",
        "_write_authoritative_calibration_progress",
        "_write_authoritative_calibration_resume",
        "_write_execution_plan_exports",
        "_accept_authoritative_calibration_writes",
    ],
)
def test_calibration_partial_write_failure_invalidates_cache_and_full_retry_recovers(
    experiment_model_factory,
    monkeypatch,
    method_name,
):
    _model, experiment_model, _well_spec, _dispense = _active_runtime(
        experiment_model_factory
    )
    revision_dir = Path(experiment_model.execution_plan_revisions_dir_path)
    original = getattr(experiment_model, method_name)
    calls = {"count": 0}

    def fail_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError(f"{method_name} failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(experiment_model, method_name, fail_once)
    with pytest.raises(RuntimeError, match=f"{method_name} failed"):
        _apply_cached_calibration(experiment_model)

    immutable_after_failure = {
        path.name: path.read_bytes()
        for path in revision_dir.glob("revision_*.json")
    }
    assert experiment_model._active_authoritative_execution_session is None
    assert method_name in experiment_model.get_execution_plan_sync_error()

    recovered = _apply_cached_calibration(experiment_model)

    assert recovered["status"] in {"created", "reused"}
    assert experiment_model.get_execution_plan_sync_error() is None
    for name, payload in immutable_after_failure.items():
        assert (revision_dir / name).read_bytes() == payload
    history = validate_revision_history(
        revision_dir,
        latest_plan=recovered["plan"],
        calibration_record_ids=set(
            load_execution_calibrations(
                experiment_model.execution_calibrations_file_path
            ).records
        ),
    )
    assert history[-1] == recovered["plan"]


def test_active_plan_lock_with_sync_error_uses_existing_recovery_path(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment_model, _well_spec, _dispense = _active_runtime(
        experiment_model_factory
    )
    experiment_model.set_execution_plan_sync_error("repair required")
    monkeypatch.setattr(
        experiment_model,
        "_recover_persisted_execution_plan_for_transition",
        lambda _plan: (_ for _ in ()).throw(RuntimeError("recovery invoked")),
    )

    with pytest.raises(RuntimeError, match="recovery invoked"):
        experiment_model.lock_execution_plan("calibration_started")


@pytest.mark.parametrize(
    "mutation",
    ["replace", "in_place", "delete", "revision_addition"],
)
def test_active_plan_lock_fails_closed_on_external_change(
    experiment_model_factory,
    mutation,
):
    _model, experiment_model, _well_spec, _dispense = _active_runtime(
        experiment_model_factory
    )
    resume_path = Path(experiment_model.execution_resume_file_path)
    before = resume_path.read_bytes()

    if mutation == "replace":
        replacement = resume_path.with_name("external-lock-replacement.json")
        replacement.write_bytes(before)
        os.replace(replacement, resume_path)
    elif mutation == "in_place":
        payload = json.loads(before)
        payload["updated_at_utc"] = "2099-01-01T00:00:00Z"
        resume_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    elif mutation == "delete":
        resume_path.unlink()
    else:
        revision_dir = Path(experiment_model.execution_plan_revisions_dir_path)
        (revision_dir / "revision_999999.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed outside the active runtime"):
        experiment_model.lock_execution_plan("calibration_started")

    assert experiment_model._active_authoritative_execution_session is None
    assert "Reload and explicitly reactivate" in experiment_model.get_execution_plan_sync_error()


def test_explicit_activation_compacts_valid_legacy_completed_intents(
    experiment_model_factory,
):
    model, experiment_model, well_spec, dispense = _active_runtime(
        experiment_model_factory
    )
    intent_id = experiment_model.begin_execution_print_intent(
        well_id=well_spec.well_id,
        stock_id=dispense.stock_id,
        commanded_droplets=1,
        printer_head_id="cache-test-head",
    )
    experiment_model.attach_execution_print_command(intent_id, 41)
    model.well_plate.get_well(well_spec.well_id).record_stock_print(
        dispense.stock_id,
        1,
    )
    experiment_model.create_progress_file()

    resume_path = Path(experiment_model.execution_resume_file_path)
    pending = load_execution_resume(resume_path)
    timestamp = utc_now_text()
    legacy_completed = replace(
        pending,
        state="clean",
        active_stock_id=None,
        printer_head_id=None,
        progress_sha256=progress_fingerprint(experiment_model.progress_data),
        intents=(
            replace(
                pending.intents[0],
                status="completed",
                completed_at_utc=timestamp,
            ),
        ),
        updated_at_utc=timestamp,
    )
    save_execution_resume(resume_path, legacy_completed)

    inspected = model_module.inspect_authoritative_execution(
        experiment_model.experiment_dir_path,
        json.loads(
            Path(experiment_model.experiment_file_path).read_text(encoding="utf-8")
        ),
    )
    assert inspected.valid
    assert inspected.resume.intents[0].status == "completed"
    assert load_execution_resume(resume_path).intents[0].status == "completed"

    experiment_model.ensure_execution_resume_checkpoint()

    compacted = load_execution_resume(resume_path)
    assert compacted.state == "clean"
    assert compacted.intents == ()


@pytest.mark.parametrize(
    "mutation",
    ["replace", "in_place", "delete", "revision_addition"],
)
def test_external_authoritative_changes_fail_closed(
    experiment_model_factory,
    mutation,
):
    _model, experiment_model, well_spec, dispense = _active_runtime(
        experiment_model_factory
    )
    resume_path = Path(experiment_model.execution_resume_file_path)
    before = resume_path.read_bytes()

    if mutation == "replace":
        replacement = resume_path.with_name("external-replacement.json")
        replacement.write_bytes(before)
        os.replace(replacement, resume_path)
    elif mutation == "in_place":
        payload = json.loads(before)
        payload["updated_at_utc"] = "2099-01-01T00:00:00Z"
        resume_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    elif mutation == "delete":
        resume_path.unlink()
    else:
        revision_dir = Path(experiment_model.execution_plan_revisions_dir_path)
        (revision_dir / "revision_999999.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed outside the active runtime"):
        experiment_model.begin_execution_print_intent(
            well_id=well_spec.well_id,
            stock_id=dispense.stock_id,
            commanded_droplets=1,
            printer_head_id="cache-test-head",
        )

    assert experiment_model._active_authoritative_execution_session is None
    assert "Reload and explicitly reactivate" in experiment_model.get_execution_plan_sync_error()
    if mutation in {"replace", "revision_addition"}:
        assert resume_path.read_bytes() == before


def test_external_execution_calibration_change_fails_closed_without_overwrite(
    experiment_model_factory,
):
    _model, experiment_model, well_spec, dispense = _active_runtime(
        experiment_model_factory
    )
    calibration_path = Path(experiment_model.execution_calibrations_file_path)
    assert not calibration_path.exists()
    plan = experiment_model.get_execution_plan_snapshot()
    save_execution_calibrations(
        calibration_path,
        ExecutionCalibrationDocument(plan_id=plan.plan_id),
    )
    externally_changed = calibration_path.read_bytes()

    with pytest.raises(RuntimeError, match="execution_calibrations.json changed"):
        experiment_model.begin_execution_print_intent(
            well_id=well_spec.well_id,
            stock_id=dispense.stock_id,
            commanded_droplets=1,
            printer_head_id="cache-test-head",
        )

    assert experiment_model._active_authoritative_execution_session is None
    assert calibration_path.read_bytes() == externally_changed


def test_resume_save_failure_keeps_cache_retryable(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment_model, well_spec, dispense = _active_runtime(
        experiment_model_factory
    )
    resume_path = Path(experiment_model.execution_resume_file_path)
    before = resume_path.read_bytes()
    original_save = model_module.save_execution_resume

    monkeypatch.setattr(
        model_module,
        "save_execution_resume",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("save failed")),
    )
    with pytest.raises(OSError, match="save failed"):
        experiment_model.begin_execution_print_intent(
            well_id=well_spec.well_id,
            stock_id=dispense.stock_id,
            commanded_droplets=1,
            printer_head_id="cache-test-head",
        )

    assert resume_path.read_bytes() == before
    assert experiment_model._active_authoritative_execution_session is not None

    monkeypatch.setattr(model_module, "save_execution_resume", original_save)
    intent_id = experiment_model.begin_execution_print_intent(
        well_id=well_spec.well_id,
        stock_id=dispense.stock_id,
        commanded_droplets=1,
        printer_head_id="cache-test-head",
    )
    assert intent_id


def test_atomic_replace_failure_keeps_cache_retryable(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment_model, well_spec, dispense = _active_runtime(
        experiment_model_factory
    )
    resume_path = Path(experiment_model.execution_resume_file_path)
    before = resume_path.read_bytes()
    original_replace = os.replace

    monkeypatch.setattr(
        os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("replace failed")),
    )
    with pytest.raises(OSError, match="replace failed"):
        experiment_model.begin_execution_print_intent(
            well_id=well_spec.well_id,
            stock_id=dispense.stock_id,
            commanded_droplets=1,
            printer_head_id="cache-test-head",
        )

    assert resume_path.read_bytes() == before
    assert experiment_model._active_authoritative_execution_session is not None

    monkeypatch.setattr(os, "replace", original_replace)
    assert experiment_model.begin_execution_print_intent(
        well_id=well_spec.well_id,
        stock_id=dispense.stock_id,
        commanded_droplets=1,
        printer_head_id="cache-test-head",
    )


def test_progress_write_failure_does_not_advance_cached_progress(
    experiment_model_factory,
    monkeypatch,
):
    model, experiment_model, well_spec, dispense = _active_runtime(
        experiment_model_factory
    )
    intent_id = experiment_model.begin_execution_print_intent(
        well_id=well_spec.well_id,
        stock_id=dispense.stock_id,
        commanded_droplets=1,
        printer_head_id="cache-test-head",
    )
    experiment_model.attach_execution_print_command(intent_id, 77)
    model.well_plate.get_well(well_spec.well_id).record_stock_print(
        dispense.stock_id,
        1,
    )
    session = experiment_model._active_authoritative_execution_session
    cached_before = json.dumps(session.progress_payload, sort_keys=True)
    progress_path = Path(experiment_model.progress_file_path)
    disk_before = progress_path.read_bytes()
    original_write = experiment_model._write_progress_payload

    monkeypatch.setattr(
        experiment_model,
        "_write_progress_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("progress failed")),
    )
    with pytest.raises(OSError, match="progress failed"):
        experiment_model.create_progress_file(execution_intent_id=intent_id)

    assert progress_path.read_bytes() == disk_before
    assert json.dumps(session.progress_payload, sort_keys=True) == cached_before

    monkeypatch.setattr(experiment_model, "_write_progress_payload", original_write)
    experiment_model.create_progress_file(execution_intent_id=intent_id)
    experiment_model.complete_execution_print_intent(intent_id)
    assert experiment_model.get_execution_resume_eligibility()["status"] in {
        "ready_to_resume",
        "complete",
    }


def test_reset_invalidates_active_runtime_session(experiment_model_factory):
    _model, experiment_model, _well_spec, _dispense = _active_runtime(
        experiment_model_factory
    )
    assert experiment_model._active_authoritative_execution_session is not None

    experiment_model.reset_experiment_model()

    assert experiment_model._active_authoritative_execution_session is None
