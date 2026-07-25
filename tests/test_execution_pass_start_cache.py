import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import Model as model_module
from AuthoritativeExecutionLoad import inspect_authoritative_execution
from ExecutionPlan import ExecutionPlanState, load_execution_plan
from ExecutionPlanRevision import (
    build_locked_revision,
    build_printer_head_binding_revision,
    validate_revision_history,
    validate_revision_successor,
)
from ExecutionProgressStore import (
    decode_execution_progress,
    encode_execution_progress_v1,
    retarget_execution_progress_revision,
)
from Model import Model


def _configure_design(experiment_model):
    experiment_model.factors = []
    experiment_model.add_additive(
        "PASS_START_TEST",
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


def _prepared_execution(experiment_model_factory):
    model = experiment_model_factory()
    experiment = model.experiment_model
    _configure_design(experiment)
    Model.load_experiment_from_model(
        model,
        load_progress=False,
        finalize_execution_plan=True,
    )
    plan = experiment.get_execution_plan_snapshot()
    stock = next(
        stock
        for stock in plan.stocks
        if any(
            dispense.stock_id == stock.stock_id
            and dispense.target_dispenses > 0
            for well in plan.wells
            for dispense in well.dispenses
        )
    )
    head = SimpleNamespace(
        printer_head_id="pass-start-head",
        get_stock_id=lambda: stock.stock_id,
        get_printing_mode=lambda: stock.printing_mode,
    )
    return model, experiment, plan, stock, head


def _preflight_and_prepare(experiment, head):
    validation = experiment.validate_authoritative_print_context(head)
    assert validation == {
        "ok": True,
        "code": "authoritative_context_valid",
    }
    return experiment.prepare_authoritative_print_pass(
        stock_id=head.get_stock_id(),
        printer_head_id=head.printer_head_id,
    )


def test_fresh_pass_uses_one_inspection_and_incremental_successors(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment, prepared, _stock, head = _prepared_execution(
        experiment_model_factory
    )
    calls = {"inspect": 0}
    original_inspect = model_module.inspect_authoritative_execution

    def observed_inspect(*args, **kwargs):
        calls["inspect"] += 1
        return original_inspect(*args, **kwargs)

    monkeypatch.setattr(
        model_module,
        "inspect_authoritative_execution",
        observed_inspect,
    )
    validation = experiment.validate_authoritative_print_context(head)
    assert validation["ok"] is True
    assert calls["inspect"] == 1

    def forbidden_full_history(*_args, **_kwargs):
        raise AssertionError("pass preparation reread full revision history")

    monkeypatch.setattr(
        model_module,
        "validate_revision_history",
        forbidden_full_history,
    )
    result = experiment.prepare_authoritative_print_pass(
        stock_id=head.get_stock_id(),
        printer_head_id=head.printer_head_id,
    )

    assert calls["inspect"] == 1
    assert result["cache_path"] == "bootstrap_revision"
    assert [item["kind"] for item in result["created_revisions"]] == [
        "lock",
        "printer_head_binding",
    ]
    assert result["checkpoint_action"] == "created"
    assert result["starting_plan_revision"] == prepared.plan_revision
    assert result["final_plan_revision"] == prepared.plan_revision + 2
    assert experiment._active_authoritative_execution_session is not None
    assert experiment.get_execution_plan_snapshot().state is ExecutionPlanState.ACTIVE

    design = json.loads(
        Path(experiment.experiment_file_path).read_text(encoding="utf-8")
    )
    bundle = inspect_authoritative_execution(
        experiment.experiment_dir_path,
        design,
    )
    assert bundle.valid
    assert bundle.resume is not None
    assert bundle.resume.plan_revision == result["final_plan_revision"]


def test_repeated_bound_pass_is_guarded_noop_without_disk_loads_or_writes(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment, _prepared, _stock, head = _prepared_execution(
        experiment_model_factory
    )
    _preflight_and_prepare(experiment, head)
    paths = [
        Path(experiment.execution_plan_file_path),
        Path(experiment.progress_file_path),
        Path(experiment.execution_resume_file_path),
    ]
    before = {path: path.read_bytes() for path in paths}
    revision_names = tuple(
        path.name
        for path in sorted(
            Path(experiment.execution_plan_revisions_dir_path).glob(
                "revision_*.json"
            )
        )
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("guarded no-op attempted persistence or a disk reload")

    monkeypatch.setattr(model_module, "inspect_authoritative_execution", forbidden)
    monkeypatch.setattr(model_module, "load_execution_resume", forbidden)
    monkeypatch.setattr(model_module, "save_execution_resume", forbidden)
    monkeypatch.setattr(model_module, "save_execution_plan", forbidden)
    monkeypatch.setattr(experiment, "_atomic_write_text", forbidden)

    result = _preflight_and_prepare(experiment, head)

    assert result == {
        "cache_path": "cached_noop",
        "created_revisions": [],
        "checkpoint_action": "already_current",
        "starting_plan_revision": experiment.get_execution_plan_snapshot().plan_revision,
        "final_plan_revision": experiment.get_execution_plan_snapshot().plan_revision,
    }
    assert {path: path.read_bytes() for path in paths} == before
    assert tuple(
        path.name
        for path in sorted(
            Path(experiment.execution_plan_revisions_dir_path).glob(
                "revision_*.json"
            )
        )
    ) == revision_names


def test_preflight_external_replace_fails_closed_without_overwrite(
    experiment_model_factory,
):
    _model, experiment, _prepared, _stock, head = _prepared_execution(
        experiment_model_factory
    )
    assert experiment.validate_authoritative_print_context(head)["ok"] is True
    progress_path = Path(experiment.progress_file_path)
    before = progress_path.read_bytes()
    replacement = progress_path.with_name("external-progress.json")
    replacement.write_bytes(before)
    os.replace(replacement, progress_path)

    with pytest.raises(RuntimeError, match="changed after print preflight"):
        experiment.prepare_authoritative_print_pass(
            stock_id=head.get_stock_id(),
            printer_head_id=head.printer_head_id,
        )

    assert progress_path.read_bytes() == before
    assert experiment._active_authoritative_execution_session is None
    assert "Reload and explicitly reactivate" in (
        experiment.get_execution_plan_sync_error()
    )


def test_preflight_is_single_use_and_rejects_a_changed_head(
    experiment_model_factory,
):
    _model, experiment, _prepared, _stock, head = _prepared_execution(
        experiment_model_factory
    )
    assert experiment.validate_authoritative_print_context(head)["ok"] is True

    with pytest.raises(RuntimeError, match="loaded printer head changed"):
        experiment.prepare_authoritative_print_pass(
            stock_id=head.get_stock_id(),
            printer_head_id="different-head",
        )

    with pytest.raises(RuntimeError, match="preflight is missing or stale"):
        experiment.prepare_authoritative_print_pass(
            stock_id=head.get_stock_id(),
            printer_head_id=head.printer_head_id,
        )


def test_partial_cached_revision_commit_requires_explicit_repair(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment, prepared, _stock, head = _prepared_execution(
        experiment_model_factory
    )
    assert experiment.validate_authoritative_print_context(head)["ok"] is True
    original_write = experiment._write_authoritative_pass_current_plan

    def fail_current_plan(_candidate):
        raise OSError("current-plan unavailable")

    monkeypatch.setattr(
        experiment,
        "_write_authoritative_pass_current_plan",
        fail_current_plan,
    )
    with pytest.raises(RuntimeError, match="current-plan unavailable"):
        experiment.prepare_authoritative_print_pass(
            stock_id=head.get_stock_id(),
            printer_head_id=head.printer_head_id,
        )

    assert experiment._active_authoritative_execution_session is None
    assert load_execution_plan(experiment.execution_plan_file_path) == prepared
    durable_successor = load_execution_plan(
        Path(experiment.execution_plan_revisions_dir_path)
        / "revision_000002.json"
    )
    assert durable_successor.state is ExecutionPlanState.ACTIVE
    assert "current-plan unavailable" in experiment.get_execution_plan_sync_error()

    monkeypatch.setattr(
        experiment,
        "_write_authoritative_pass_current_plan",
        original_write,
    )
    repaired = experiment.lock_execution_plan("printing_started")
    assert repaired == durable_successor
    assert load_execution_plan(experiment.execution_plan_file_path) == repaired

    result = _preflight_and_prepare(experiment, head)
    assert [item["kind"] for item in result["created_revisions"]] == [
        "printer_head_binding"
    ]
    assert result["checkpoint_action"] == "created"


def test_successor_and_progress_retarget_share_full_validation_rules(
    experiment_model_factory,
):
    _model, experiment, prepared, stock, _head = _prepared_execution(
        experiment_model_factory
    )
    locked = build_locked_revision(
        prepared,
        reason="printing_started",
        timestamp_utc="2099-07-25T00:00:00Z",
    )
    bound = build_printer_head_binding_revision(
        locked,
        stock_id=stock.stock_id,
        printer_head_id="pass-start-head",
        timestamp_utc="2099-07-25T00:00:01Z",
    )
    history = validate_revision_successor((prepared,), locked)
    history = validate_revision_successor(history, bound)
    assert history == (prepared, locked, bound)

    progress_payload = json.loads(
        Path(experiment.progress_file_path).read_text(encoding="utf-8")
    )
    compact = retarget_execution_progress_revision(
        prepared,
        locked,
        progress_payload,
    )
    assert compact.reference.plan_revision == locked.plan_revision
    assert compact.progress_wells == decode_execution_progress(
        prepared,
        progress_payload,
    ).progress_wells

    legacy_payload = encode_execution_progress_v1(
        prepared,
        compact.progress_wells,
    )
    first_well = prepared.wells[0]
    first_stock = first_well.dispenses[0].stock_id
    legacy_payload[first_well.well_id]["reagents"][first_stock][
        "name"
    ] = "preserved metadata"
    legacy = retarget_execution_progress_revision(
        prepared,
        locked,
        legacy_payload,
    )
    assert legacy.payload[first_well.well_id]["reagents"][first_stock][
        "name"
    ] == "preserved metadata"
    assert legacy.reference.plan_revision == locked.plan_revision

    revision_dir = Path(experiment.execution_plan_revisions_dir_path)
    model_module.save_execution_plan(revision_dir / "revision_000002.json", locked)
    model_module.save_execution_plan(revision_dir / "revision_000003.json", bound)
    model_module.save_execution_plan(experiment.execution_plan_file_path, bound)
    assert validate_revision_history(
        revision_dir,
        latest_plan=bound,
    ) == history
