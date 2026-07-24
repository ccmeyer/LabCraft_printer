from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
for candidate in (REPO_ROOT, UI_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from Model import ExperimentModel, Model
from ExecutionProgressStore import (
    decode_execution_progress,
    detect_execution_progress_schema,
    encode_execution_progress_v1,
    serialize_execution_progress,
)
from tools.virtual_workflows.progress_snapshot import (
    ProgressSnapshotObserver,
    non_durable_progress_samples,
)


def test_progress_serializer_preserves_json_dump_indent_four_bytes():
    model = ExperimentModel.__new__(ExperimentModel)
    payload = {
        "A1": {
            "reaction_id": "rxn-1",
            "reagents": {
                "stock-1": {
                    "target_droplets": 3,
                    "added_droplets": 1,
                }
            },
            "completed": False,
        },
        "__plate__": {
            "name": "shallow-384_well_plate",
            "rows": 16,
            "columns": 24,
            "schema_version": 1,
        },
    }
    expected = io.StringIO()
    json.dump(
        payload,
        expected,
        indent=4,
        default=model.convert_to_serializable,
    )

    assert model._serialize_progress_payload(payload) == expected.getvalue()


def test_progress_observer_records_boundaries_and_restores_methods():
    class FakeExperiment:
        def _build_progress_payload_from_runtime(self):
            return {"A1": {}}

        def _serialize_progress_payload(self, payload):
            return json.dumps(payload, indent=4)

        def _atomic_write_progress_text(self, serialized):
            return len(serialized)

    experiment = FakeExperiment()
    originals = {
        name: getattr(experiment, name)
        for name in (
            "_build_progress_payload_from_runtime",
            "_serialize_progress_payload",
            "_atomic_write_progress_text",
        )
    }
    observer = ProgressSnapshotObserver(experiment)
    with observer.installed():
        payload = experiment._build_progress_payload_from_runtime()
        serialized = experiment._serialize_progress_payload(payload)
        experiment._atomic_write_progress_text(serialized)
        assert not observer.snapshot()["observer_restored"]

    snapshot = observer.snapshot()
    assert snapshot["mode_counts"] == {
        "full_rebuild": 1,
        "cached_update": 0,
    }
    assert len(snapshot["duration_samples_ms"]["serialization"]) == 1
    assert len(snapshot["duration_samples_ms"]["atomic_write"]) == 1
    assert snapshot["serialized_size_bytes"] == [len(serialized.encode("utf-8"))]
    assert snapshot["observer_restored"]
    for name, original in originals.items():
        assert getattr(experiment, name) == original


def test_progress_observer_restores_after_failure():
    experiment = SimpleNamespace(
        _serialize_progress_payload=lambda _payload: (_ for _ in ()).throw(
            RuntimeError("serialize failed")
        )
    )
    original = experiment._serialize_progress_payload
    observer = ProgressSnapshotObserver(experiment)

    with pytest.raises(RuntimeError, match="serialize failed"):
        with observer.installed():
            experiment._serialize_progress_payload({})

    assert experiment._serialize_progress_payload is original
    assert observer.snapshot()["observer_restored"]
    assert len(observer.snapshot()["duration_samples_ms"]["serialization"]) == 1


def test_non_durable_progress_samples_require_aligned_calls():
    assert non_durable_progress_samples(
        [10.0, 20.0],
        [2.0, 3.0],
        [1.0, 2.0],
    ) == [7.0, 15.0]
    with pytest.raises(ValueError, match="matching counts"):
        non_durable_progress_samples([1.0], [], [0.1])


def _configure_authoritative_design(experiment_model):
    experiment_model.factors = []
    experiment_model.add_additive(
        "PROGRESS_CACHE_TEST",
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


def _active_authoritative_runtime(experiment_model_factory):
    model = experiment_model_factory()
    experiment = model.experiment_model
    _configure_authoritative_design(experiment)
    Model.load_experiment_from_model(
        model,
        load_progress=False,
        finalize_execution_plan=True,
    )
    plan = experiment.lock_execution_plan("printing_started")
    experiment.ensure_execution_resume_checkpoint()
    experiment._authoritative_runtime_active = True
    well_spec = next(
        well
        for well in plan.wells
        if any(item.target_dispenses > 0 for item in well.dispenses)
    )
    dispense = next(
        item for item in well_spec.dispenses if item.target_dispenses > 0
    )
    return model, experiment, well_spec, dispense


def _pending_completion(experiment_model_factory):
    model, experiment, well_spec, dispense = _active_authoritative_runtime(
        experiment_model_factory
    )
    intent_id = experiment.begin_execution_print_intent(
        well_id=well_spec.well_id,
        stock_id=dispense.stock_id,
        commanded_droplets=1,
        printer_head_id="progress-cache-head",
    )
    experiment.attach_execution_print_command(intent_id, 51)
    model.well_plate.get_well(well_spec.well_id).record_stock_print(
        dispense.stock_id,
        1,
    )
    return model, experiment, well_spec, dispense, intent_id


def _replace_with_v1(experiment, plan, *, positive=False):
    wells = experiment.return_progress_data()
    if positive:
        for well in plan.wells:
            for dispense in well.dispenses:
                if dispense.target_dispenses > 0:
                    wells[well.well_id]["reagents"][dispense.stock_id][
                        "added_droplets"
                    ] = 1
                    wells[well.well_id]["completed"] = all(
                        details["added_droplets"]
                        >= details["target_droplets"]
                        for details in wells[well.well_id][
                            "reagents"
                        ].values()
                    )
                    break
            else:
                continue
            break
    payload = encode_execution_progress_v1(plan, wells)
    Path(experiment.progress_file_path).write_text(
        serialize_execution_progress(payload),
        encoding="utf-8",
    )
    experiment.progress_data = decode_execution_progress(
        plan, payload
    ).progress_wells
    return payload


def test_zero_v1_without_resume_is_eligible_for_v2_adoption(
    experiment_model_factory,
):
    _model, experiment, _well, _dispense = _active_authoritative_runtime(
        experiment_model_factory
    )
    Path(experiment.execution_resume_file_path).unlink()
    plan = experiment.get_execution_plan_snapshot()
    _replace_with_v1(experiment, plan)

    payload = experiment._write_progress_for_execution_plan(plan)

    assert detect_execution_progress_schema(payload) == 2


def test_positive_v1_remains_v1_without_resume(experiment_model_factory):
    model = experiment_model_factory()
    experiment = model.experiment_model
    _configure_authoritative_design(experiment)
    Model.load_experiment_from_model(
        model,
        load_progress=False,
        finalize_execution_plan=True,
    )
    plan = experiment.get_execution_plan_snapshot()
    _replace_with_v1(experiment, plan, positive=True)

    rebuilt = experiment._build_progress_payload_from_runtime()
    payload = experiment._write_progress_for_execution_plan(plan)

    assert detect_execution_progress_schema(rebuilt) == 1
    assert detect_execution_progress_schema(payload) == 1


def test_zero_v1_with_resume_remains_v1(experiment_model_factory):
    _model, experiment, _well, _dispense = _active_authoritative_runtime(
        experiment_model_factory
    )
    plan = experiment.get_execution_plan_snapshot()
    _replace_with_v1(experiment, plan)

    payload = experiment._write_progress_for_execution_plan(plan)

    assert detect_execution_progress_schema(payload) == 1


def test_cached_candidate_matches_full_rebuild_without_mutating_cache(
    experiment_model_factory,
):
    _model, experiment, well_spec, dispense, intent_id = _pending_completion(
        experiment_model_factory
    )
    session = experiment._active_authoritative_execution_session
    plan = session.bundle.plan
    cached_payload = session.progress_payload
    cached_well = decode_execution_progress(
        plan, cached_payload
    ).progress_wells[well_spec.well_id]
    cached_reagents = cached_well["reagents"]
    cached_reagent = cached_reagents[dispense.stock_id]

    candidate = experiment._build_cached_progress_payload(intent_id)
    rebuilt = experiment._build_progress_payload_from_runtime()

    def completion_projection(payload):
        return decode_execution_progress(plan, payload).progress_wells

    assert completion_projection(candidate) == completion_projection(rebuilt)
    assert session.progress_payload is cached_payload
    assert candidate is not cached_payload
    assert candidate["added_droplets"] is not cached_payload["added_droplets"]
    assert (
        candidate["added_droplets"][dispense.stock_id]
        is not cached_payload["added_droplets"][dispense.stock_id]
    )
    assert cached_reagent["added_droplets"] == 0


def test_authoritative_cached_write_never_enumerates_all_wells(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment, well_spec, dispense, intent_id = _pending_completion(
        experiment_model_factory
    )
    monkeypatch.setattr(
        experiment._runtime_well_plate,
        "get_all_wells",
        lambda: (_ for _ in ()).throw(
            AssertionError("authoritative completion enumerated all wells")
        ),
    )

    experiment.create_progress_file(execution_intent_id=intent_id)

    session = experiment._active_authoritative_execution_session
    assert decode_execution_progress(
        session.bundle.plan,
        session.progress_payload,
    ).progress_wells[well_spec.well_id]["reagents"][dispense.stock_id][
        "added_droplets"
    ] == 1


def test_argument_free_progress_write_retains_full_rebuild(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment, _well_spec, _dispense = _active_authoritative_runtime(
        experiment_model_factory
    )
    calls = 0
    original = experiment._build_progress_payload_from_runtime

    def observed():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(experiment, "_build_progress_payload_from_runtime", observed)
    experiment.create_progress_file()

    assert calls == 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("unknown_intent", "missing or duplicated"),
        ("cache_baseline", "baseline"),
        ("live_count", "live reagent count"),
        ("target_overflow", "exceed"),
    ),
)
def test_cached_progress_validation_fails_closed(
    experiment_model_factory,
    mutation,
    message,
):
    _model, experiment, well_spec, dispense, intent_id = _pending_completion(
        experiment_model_factory
    )
    session = experiment._active_authoritative_execution_session
    disk_before = Path(experiment.progress_file_path).read_bytes()
    payload_before = json.dumps(session.progress_payload, sort_keys=True)
    candidate_intent_id = intent_id

    if mutation == "unknown_intent":
        candidate_intent_id = "00000000-0000-0000-0000-000000000000"
    elif mutation == "cache_baseline":
        well_index = session.progress_payload["well_order"].index(
            well_spec.well_id
        )
        session.progress_payload["added_droplets"][dispense.stock_id][
            well_index
        ] = 2
    elif mutation == "live_count":
        reaction = (
            experiment._runtime_well_plate.get_well(well_spec.well_id)
            .get_assigned_reaction()
        )
        reaction.get_all_reagents()[dispense.stock_id].added_droplets = 0
    elif mutation == "target_overflow":
        intent = session.resume.intents[0]
        from dataclasses import replace

        session.resume = replace(
            session.resume,
            intents=(
                replace(
                    intent,
                    commanded_droplets=dispense.target_dispenses + 1,
                ),
            ),
        )

    with pytest.raises(RuntimeError, match=message):
        experiment.create_progress_file(
            execution_intent_id=candidate_intent_id,
        )

    assert Path(experiment.progress_file_path).read_bytes() == disk_before
    if mutation != "cache_baseline":
        assert json.dumps(session.progress_payload, sort_keys=True) == payload_before
    assert session.resume.intents[0].status == "pending"


@pytest.mark.parametrize("failure_boundary", ("serialization", "fsync", "replace"))
def test_cached_write_failure_does_not_advance_coherent_state(
    experiment_model_factory,
    monkeypatch,
    failure_boundary,
):
    _model, experiment, _well_spec, _dispense, intent_id = _pending_completion(
        experiment_model_factory
    )
    session = experiment._active_authoritative_execution_session
    disk_before = Path(experiment.progress_file_path).read_bytes()
    payload_before = json.dumps(session.progress_payload, sort_keys=True)
    progress_before = json.dumps(experiment.progress_data, sort_keys=True)

    if failure_boundary == "serialization":
        monkeypatch.setattr(
            experiment,
            "_serialize_progress_payload",
            lambda _payload: (_ for _ in ()).throw(
                OSError("serialization failed")
            ),
        )
    elif failure_boundary == "fsync":
        import os

        monkeypatch.setattr(
            os,
            "fsync",
            lambda _fd: (_ for _ in ()).throw(OSError("fsync failed")),
        )
    else:
        import os

        monkeypatch.setattr(
            os,
            "replace",
            lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
        )

    with pytest.raises(OSError, match="failed"):
        experiment.create_progress_file(execution_intent_id=intent_id)

    assert Path(experiment.progress_file_path).read_bytes() == disk_before
    assert json.dumps(session.progress_payload, sort_keys=True) == payload_before
    assert json.dumps(experiment.progress_data, sort_keys=True) == progress_before
    assert session.resume.intents[0].status == "pending"


def test_post_write_identity_failure_invalidates_session_without_cache_advance(
    experiment_model_factory,
    monkeypatch,
):
    _model, experiment, _well_spec, _dispense, intent_id = _pending_completion(
        experiment_model_factory
    )
    session = experiment._active_authoritative_execution_session
    payload_before = json.dumps(session.progress_payload, sort_keys=True)
    original_replace = __import__("os").replace

    def replace_then_change_revision(source, destination):
        result = original_replace(source, destination)
        revision_dir = Path(experiment.experiment_dir_path) / (
            "execution_plan_revisions"
        )
        (revision_dir / "revision_unexpected.json").write_text(
            "{}",
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(__import__("os"), "replace", replace_then_change_revision)

    with pytest.raises(RuntimeError, match="revision history changed"):
        experiment.create_progress_file(execution_intent_id=intent_id)

    assert experiment._active_authoritative_execution_session is None
    assert json.dumps(session.progress_payload, sort_keys=True) == payload_before
