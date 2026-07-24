import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

import Model as model_module
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
    experiment_model.create_progress_file()
    experiment_model.complete_execution_print_intent(intent_id)
    return intent_id


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
        experiment_model.create_progress_file()

    assert progress_path.read_bytes() == disk_before
    assert json.dumps(session.progress_payload, sort_keys=True) == cached_before

    monkeypatch.setattr(experiment_model, "_write_progress_payload", original_write)
    experiment_model.create_progress_file()
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
