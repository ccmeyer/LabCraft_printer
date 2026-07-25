import json
import os
from pathlib import Path

import pytest

import Model as model_module
from AuthoritativeExecutionLoad import (
    inspect_authoritative_execution,
    reconcile_authoritative_execution_runtime,
)
from ExecutionPlan import ExecutionPlanState
from ExecutionProgressStore import (
    copy_execution_progress_payload,
    copy_progress_wells_update,
    decode_execution_progress,
)
from ExecutionResumeStore import synchronize_checkpoint
from test_execution_pass_start_cache import (
    _preflight_and_prepare,
    _prepared_execution,
)


def _complete_cached_progress(experiment) -> None:
    session = experiment._guard_authoritative_runtime_session()
    plan = session.bundle.plan
    payload = session.progress_payload
    progress_wells = session.bundle.progress_wells
    for well in plan.wells:
        for dispense in well.dispenses:
            payload = copy_execution_progress_payload(
                plan,
                payload,
                well_id=well.well_id,
                stock_id=dispense.stock_id,
                added_droplets=dispense.target_dispenses,
            )
            progress_wells = copy_progress_wells_update(
                progress_wells,
                well_id=well.well_id,
                stock_id=dispense.stock_id,
                added_droplets=dispense.target_dispenses,
            )
    experiment._write_authoritative_transition_progress(payload)
    experiment._accept_authoritative_runtime_write("progress.json")
    session.progress_payload = payload
    session.bundle = reconcile_authoritative_execution_runtime(
        session.bundle,
        progress_payload=payload,
        progress_wells=progress_wells,
        resume=session.resume,
    )
    experiment._authoritative_execution_bundle = session.bundle
    experiment.progress_data = dict(progress_wells)
    updated_resume = synchronize_checkpoint(
        session.resume,
        plan_revision=plan.plan_revision,
        progress_wells=progress_wells,
    )
    experiment._save_active_execution_resume(updated_resume)


def _ready_completion(experiment_model_factory):
    model, experiment, _prepared, _stock, head = _prepared_execution(
        experiment_model_factory
    )
    _preflight_and_prepare(experiment, head)
    _complete_cached_progress(experiment)
    return model, experiment


def test_cached_completion_writes_once_then_performs_one_full_validation(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment = _ready_completion(experiment_model_factory)
    starting = experiment.get_execution_plan_snapshot()
    starting_payload = dict(
        experiment._active_authoritative_execution_session.progress_payload
    )
    export_paths = (
        Path(experiment.key_file_path),
        Path(experiment.concentration_key_file_path),
    )
    export_bytes = {
        path: path.read_bytes()
        for path in export_paths
        if path.is_file()
    }
    events = []
    original_inspect = model_module.inspect_authoritative_execution

    def observed_inspect(*args, **kwargs):
        events.append("full_validation")
        return original_inspect(*args, **kwargs)

    monkeypatch.setattr(
        model_module,
        "inspect_authoritative_execution",
        observed_inspect,
    )
    monkeypatch.setattr(
        model_module,
        "load_execution_resume",
        lambda *_args, **_kwargs: pytest.fail(
            "cached completion loaded execution_resume.json before commit"
        ),
    )
    monkeypatch.setattr(
        experiment,
        "_recover_persisted_execution_plan_for_transition",
        lambda *_args, **_kwargs: pytest.fail(
            "cached completion entered disk recovery"
        ),
    )
    monkeypatch.setattr(
        experiment,
        "_write_execution_plan_exports",
        lambda *_args, **_kwargs: pytest.fail(
            "terminal completion rewrote CSV exports"
        ),
    )
    for method_name, event_name in (
        (
            "_persist_authoritative_terminal_immutable_revision",
            "immutable_revision",
        ),
        ("_write_authoritative_terminal_current_plan", "current_plan"),
        ("_write_authoritative_terminal_progress", "progress"),
        ("_write_authoritative_terminal_resume", "resume"),
    ):
        original = getattr(experiment, method_name)

        def observed(*args, _original=original, _event=event_name, **kwargs):
            events.append(_event)
            return _original(*args, **kwargs)

        monkeypatch.setattr(experiment, method_name, observed)

    completed = experiment.try_complete_execution_plan()

    assert completed.state is ExecutionPlanState.COMPLETED
    assert completed.plan_revision == starting.plan_revision + 1
    assert events == [
        "immutable_revision",
        "current_plan",
        "progress",
        "resume",
        "full_validation",
    ]
    assert experiment._last_authoritative_terminal_transition == {
        "cache_path": "cached_completion",
        "starting_plan_revision": starting.plan_revision,
        "final_plan_revision": completed.plan_revision,
        "created_revision": f"revision_{completed.plan_revision:06d}.json",
        "full_validation_count": 1,
        "exports": "unchanged",
    }
    assert experiment.is_authoritative_execution_runtime_active() is False
    assert experiment._active_authoritative_execution_session is None
    assert {
        path: path.read_bytes()
        for path in export_bytes
    } == export_bytes

    design = json.loads(
        Path(experiment.experiment_file_path).read_text(encoding="utf-8")
    )
    bundle = inspect_authoritative_execution(
        experiment.experiment_dir_path,
        design,
    )
    assert bundle.valid
    assert bundle.plan == completed
    assert bundle.resume.plan_revision == completed.plan_revision
    assert bundle.eligibility.status == "analysis_only"
    assert bundle.progress_wells == decode_execution_progress(
        completed,
        bundle.progress_payload,
    ).progress_wells
    expected_payload = dict(starting_payload)
    if "plan_revision" in expected_payload:
        expected_payload["plan_revision"] = completed.plan_revision
    else:
        reference = dict(expected_payload["__execution__"])
        reference["plan_revision"] = completed.plan_revision
        expected_payload["__execution__"] = reference
    assert bundle.progress_payload == expected_payload


@pytest.mark.parametrize(
    "mutation",
    ("replace", "in_place", "delete", "revision_addition"),
)
def test_cached_completion_rejects_external_changes_before_writing(
    experiment_model_factory,
    mutation,
):
    _model, experiment = _ready_completion(experiment_model_factory)
    plan = experiment.get_execution_plan_snapshot()
    revision_directory = Path(experiment.execution_plan_revisions_dir_path)
    revision_names = {
        path.name for path in revision_directory.glob("revision_*.json")
    }
    progress_path = Path(experiment.progress_file_path)
    if mutation == "replace":
        replacement = progress_path.with_name("external-progress.json")
        replacement.write_bytes(progress_path.read_bytes())
        os.replace(replacement, progress_path)
    elif mutation == "in_place":
        progress_path.write_bytes(progress_path.read_bytes() + b" ")
    elif mutation == "delete":
        progress_path.unlink()
    else:
        (revision_directory / "revision_999999.json").write_text(
            "{}",
            encoding="utf-8",
        )

    with pytest.raises(RuntimeError, match="changed outside the active runtime"):
        experiment.try_complete_execution_plan()

    assert experiment.get_execution_plan_snapshot() == plan
    assert experiment._active_authoritative_execution_session is None
    assert {
        path.name for path in revision_directory.glob("revision_*.json")
    } - {"revision_999999.json"} == revision_names


@pytest.mark.parametrize(
    "failing_method",
    (
        "_persist_authoritative_terminal_immutable_revision",
        "_write_authoritative_terminal_current_plan",
        "_write_authoritative_terminal_progress",
        "_write_authoritative_terminal_resume",
        "_accept_authoritative_terminal_writes",
        "_refresh_authoritative_execution_bundle",
    ),
)
def test_cached_completion_failure_never_exposes_terminal_runtime_state(
    experiment_model_factory,
    monkeypatch,
    failing_method,
):
    _model, experiment = _ready_completion(experiment_model_factory)
    starting = experiment.get_execution_plan_snapshot()
    original = getattr(experiment, failing_method)

    def fail(*_args, **_kwargs):
        raise OSError(f"injected {failing_method} failure")

    monkeypatch.setattr(experiment, failing_method, fail)
    with pytest.raises(OSError, match="injected"):
        experiment.try_complete_execution_plan()

    assert experiment.get_execution_plan_snapshot() == starting
    assert experiment.is_authoritative_execution_runtime_active() is False
    assert experiment._active_authoritative_execution_session is None
    assert failing_method in experiment.get_execution_plan_sync_error()

    monkeypatch.setattr(experiment, failing_method, original)
    repaired = experiment.transition_execution_plan_terminal(
        ExecutionPlanState.COMPLETED,
        "explicit_terminal_repair",
    )
    assert repaired.state is ExecutionPlanState.COMPLETED
    design = json.loads(
        Path(experiment.experiment_file_path).read_text(encoding="utf-8")
    )
    repaired_bundle = inspect_authoritative_execution(
        experiment.experiment_dir_path,
        design,
    )
    assert repaired_bundle.valid
    assert repaired_bundle.plan == repaired


def test_hard_abort_does_not_use_cached_completion_path(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment, _prepared, _stock, head = _prepared_execution(
        experiment_model_factory
    )
    _preflight_and_prepare(experiment, head)
    monkeypatch.setattr(
        experiment,
        "_complete_authoritative_execution_cached",
        lambda *_args, **_kwargs: pytest.fail(
            "hard abort used the completion-only cache path"
        ),
    )

    aborted = experiment.transition_execution_plan_terminal(
        ExecutionPlanState.ABORTED,
        "test_abort",
    )

    assert aborted.state is ExecutionPlanState.ABORTED
