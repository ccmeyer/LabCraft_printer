import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from AuthoritativeExecutionLoad import (
    build_execution_runtime_spec,
    inspect_authoritative_execution,
)
from ExecutionPlan import (
    ExecutionDispense,
    ExecutionPlan,
    ExecutionPlanState,
    ExecutionPlate,
    ExecutionStock,
    ExecutionVolumeBasis,
    ExecutionWell,
    ProgressExecutionReference,
    canonical_sha256,
    save_execution_plan,
)
from ExecutionPlanRevision import persist_immutable_revision
from ExecutionResumeStore import (
    add_pending_intent,
    load_execution_resume,
    new_resume_document,
    save_execution_resume,
)
from Model import Model
from test_execution_terminal_cache import _ready_completion


PLAN_ID = "f33cf5d6-2f38-4ca7-86fd-74f73baac81d"
NOW = "2026-07-17T12:00:00Z"


def _write_bundle(tmp_path: Path, *, added=0):
    design = {"schema_version": 2, "metadata": {"name": "frozen"}, "factors": []}
    stock = ExecutionStock(
        stock_id="PURE MM_1.11_x",
        factor_name="PURE MM",
        option_name=None,
        reagent_name="PURE MM",
        concentration=1.11,
        units="x",
        printing_mode="stream",
        intended_volume_nL=60.0,
        effective_volume_nL=143.59278258103592,
        printer_head_id=None,
        calibration_record_key=None,
    )
    plan = ExecutionPlan(
        plan_id=PLAN_ID,
        plan_revision=1,
        state=ExecutionPlanState.PREPARED,
        design_sha256=canonical_sha256(design),
        created_at_utc=NOW,
        updated_at_utc=NOW,
        locked_at_utc=None,
        lock_reason=None,
        plate=ExecutionPlate("plate", 8, 12),
        volume_basis=ExecutionVolumeBasis(2550.0, 2550.0, 50.0),
        stocks=(stock,),
        wells=(
            ExecutionWell(
                "A1",
                "R1",
                (ExecutionDispense(stock.stock_id, 16),),
                16 * stock.effective_volume_nL,
            ),
        ),
    )
    (tmp_path / "experiment_design.json").write_text(json.dumps(design), encoding="utf-8")
    save_execution_plan(tmp_path / "execution_plan.json", plan)
    persist_immutable_revision(tmp_path / "execution_plan_revisions", plan)
    progress = {
        "A1": {
            "reaction_id": "R1",
            "reagents": {
                stock.stock_id: {
                    "target_droplets": 16,
                    "added_droplets": added,
                }
            },
            "completed": added >= 16,
        },
        "__plate__": {"name": "plate", "rows": 8, "columns": 12, "schema_version": 1},
        "__execution__": ProgressExecutionReference(PLAN_ID, 1).to_dict(),
    }
    (tmp_path / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
    return design, plan


def _hashes(directory):
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }


def _complete_execution(experiment_model_factory):
    model, experiment = _ready_completion(experiment_model_factory)
    completed = experiment.try_complete_execution_plan()
    assert completed.state is ExecutionPlanState.COMPLETED
    return model, experiment, completed


def test_authoritative_inspection_is_nonmutating_and_builds_exact_runtime(tmp_path):
    design, plan = _write_bundle(tmp_path)
    before = _hashes(tmp_path)

    bundle = inspect_authoritative_execution(tmp_path, design)
    runtime = build_execution_runtime_spec(bundle)

    assert _hashes(tmp_path) == before
    assert bundle.valid
    assert bundle.eligibility.status == "ready_to_start"
    assert runtime.stocks[0].effective_volume_nL == 143.59278258103592
    assert runtime.wells[0].targets == {plan.stocks[0].stock_id: 16}
    assert runtime.wells[0].added == {plan.stocks[0].stock_id: 0}


def test_experiment_deserialization_does_not_mutate_caller_payload(
    experiment_model_factory,
):
    em = experiment_model_factory().experiment_model
    payload = {
        "schema_version": 2,
        "metadata": {
            "name": "caller-owned-design",
            "fill_droplet_volume_nL": 10.0,
        },
        "factors": [],
    }
    original = deepcopy(payload)

    em.from_dict(payload)

    assert payload == original
    assert em.metadata is not payload["metadata"]
    assert "well_selection" not in payload["metadata"]
    assert em.metadata["well_selection"] == {
        "mode": "start_offset",
        "included_wells": None,
    }


def test_authoritative_load_hashes_exact_persisted_design_before_normalization(
    experiment_model_factory,
    tmp_path,
):
    design, plan = _write_bundle(tmp_path)
    design_path = tmp_path / "experiment_design.json"
    loaded = experiment_model_factory()
    before = _hashes(tmp_path)

    bundle = loaded.experiment_model.load_experiment(
        str(design_path),
        str(tmp_path),
    )

    assert bundle.valid
    assert bundle.eligibility.status == "ready_to_start"
    assert bundle.eligibility.can_activate_runtime
    assert canonical_sha256(design) == plan.design_sha256
    assert json.loads(design_path.read_text(encoding="utf-8")) == design
    assert _hashes(tmp_path) == before
    assert "well_selection" not in design["metadata"]
    assert loaded.experiment_model.metadata["well_selection"] == {
        "mode": "start_offset",
        "included_wells": None,
    }


def test_positive_progress_without_checkpoint_is_analysis_only(tmp_path):
    design, _ = _write_bundle(tmp_path, added=3)

    bundle = inspect_authoritative_execution(tmp_path, design)

    assert bundle.valid
    assert bundle.eligibility.status == "blocked_missing_checkpoint"
    assert not bundle.eligibility.can_activate_runtime
    assert not bundle.eligibility.can_resume_hardware


def test_pending_intent_is_repairable_only_when_progress_proves_completion(tmp_path):
    design, plan = _write_bundle(tmp_path, added=16)
    progress = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    wells = {key: value for key, value in progress.items() if not key.startswith("__")}
    document = new_resume_document(
        plan_id=plan.plan_id,
        plan_revision=plan.plan_revision,
        progress_wells={
            "A1": {
                **wells["A1"],
                "reagents": {
                    plan.stocks[0].stock_id: {
                        **wells["A1"]["reagents"][plan.stocks[0].stock_id],
                        "added_droplets": 0,
                    }
                },
                "completed": False,
            }
        },
        session_id="9cfe342a-2c86-4e50-906f-98e70f84de05",
        timestamp_utc=NOW,
    )
    document, intent = add_pending_intent(
        document,
        well_id="A1",
        reaction_id="R1",
        stock_id=plan.stocks[0].stock_id,
        baseline_added=0,
        commanded_droplets=16,
        printer_head_id="head-1",
        timestamp_utc=NOW,
    )
    save_execution_resume(tmp_path / "execution_resume.json", document)

    bundle = inspect_authoritative_execution(tmp_path, design)

    assert bundle.eligibility.status == "repairable_checkpoint"
    assert bundle.eligibility.repairable_intent_ids == (intent.intent_id,)


def test_unreflected_pending_intent_blocks_resume_as_ambiguous(tmp_path):
    design, plan = _write_bundle(tmp_path, added=0)
    progress = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    wells = {key: value for key, value in progress.items() if not key.startswith("__")}
    document = new_resume_document(
        plan_id=plan.plan_id,
        plan_revision=plan.plan_revision,
        progress_wells=wells,
        session_id="9cfe342a-2c86-4e50-906f-98e70f84de05",
        timestamp_utc=NOW,
    )
    document, intent = add_pending_intent(
        document,
        well_id="A1",
        reaction_id="R1",
        stock_id=plan.stocks[0].stock_id,
        baseline_added=0,
        commanded_droplets=16,
        printer_head_id="head-1",
        timestamp_utc=NOW,
    )
    save_execution_resume(tmp_path / "execution_resume.json", document)

    bundle = inspect_authoritative_execution(tmp_path, design)

    assert bundle.eligibility.status == "blocked_ambiguous_intent"
    assert bundle.eligibility.ambiguous_intent_ids == (intent.intent_id,)


def test_explicit_activation_reconstructs_finalized_runtime_without_optimizer(
    experiment_model_factory,
    monkeypatch,
):
    source = experiment_model_factory()
    em = source.experiment_model
    em.factors = []
    em.add_additive(
        "PURE MM",
        [1.0],
        "x",
        60.0,
        forced_stock_conc=1.11,
        printing_mode="stream",
    )
    em.set_metadata(
        target_reaction_volume_nL=2550.0,
        final_reaction_volume_nL=2550.0,
        printed_volume_tolerance_nL=50.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()
    Model.load_experiment_from_model(source, finalize_execution_plan=True)
    saved_plan = em.get_execution_plan_snapshot()

    loaded = experiment_model_factory()
    loaded_em = loaded.experiment_model
    monkeypatch.setattr(
        loaded_em,
        "optimize_stock_solutions",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("optimizer called")),
    )
    loaded_em.load_experiment(em.experiment_file_path, em.experiment_dir_path)
    assert not Path(loaded_em.execution_resume_file_path).exists()

    eligibility = loaded.load_authoritative_execution_runtime()

    assert eligibility["status"] == "ready_to_start"
    assert Path(loaded_em.execution_resume_file_path).is_file()
    assert loaded_em.is_authoritative_execution_runtime_active()
    assert loaded_em.is_execution_design_locked()
    assigned = {
        well.well_id: well.get_assigned_reaction().unique_id
        for well in loaded.well_plate.get_all_wells()
        if well.get_assigned_reaction() is not None
    }
    assert assigned == {
        well.well_id: well.reaction_id for well in saved_plan.wells
    }

    fill = next(stock for stock in saved_plan.stocks if stock.units == "--")
    first_well = saved_plan.wells[0]
    intent_id = loaded_em.begin_execution_print_intent(
        well_id=first_well.well_id,
        stock_id=fill.stock_id,
        commanded_droplets=1,
        printer_head_id="fill-head",
    )
    loaded_em.attach_execution_print_command(intent_id, 99)
    loaded.well_plate.get_well(first_well.well_id).record_stock_print(fill.stock_id, 1)
    loaded_em.create_progress_file()
    loaded_em.complete_execution_print_intent(intent_id)
    checkpoint = load_execution_resume(loaded_em.execution_resume_file_path)
    assert checkpoint.state == "clean"
    assert checkpoint.intents == ()

    canceled_intent_id = loaded_em.begin_execution_print_intent(
        well_id=first_well.well_id,
        stock_id=fill.stock_id,
        commanded_droplets=1,
        printer_head_id="fill-head",
    )
    loaded_em.attach_execution_print_command(canceled_intent_id, 100)
    loaded_em.discard_execution_print_intents([canceled_intent_id])
    checkpoint = load_execution_resume(loaded_em.execution_resume_file_path)
    assert checkpoint.state == "paused"
    assert checkpoint.intents == ()
    assert loaded_em.get_execution_resume_eligibility()["status"] == "ready_to_resume"

    design_bytes = Path(loaded_em.experiment_file_path).read_bytes()
    pure = next(stock for stock in saved_plan.stocks if stock.factor_name == "PURE MM")
    result = loaded_em.apply_execution_calibration(
        stock_id=pure.stock_id,
        new_effective_volume_nL=61.0,
        printing_mode=pure.printing_mode,
        printer_head_id="head-after-reload",
        factor_name=pure.factor_name,
        option_name=pure.option_name,
        is_fill=False,
        calibration_payload={
            "measured_volume_nL": 61.0,
            "pw_us": 1800,
            "pressure_psi": 1.8,
            "run_id": "reload-calibration",
            "phase": "verification",
            "timestamp": "2026-07-17T12:10:00Z",
            "source_row_fingerprint": ["reload-calibration", 61.0],
            "original_printing_mode": pure.printing_mode,
        },
    )
    assert result["plan"].plan_revision > saved_plan.plan_revision
    assert Path(loaded_em.experiment_file_path).read_bytes() == design_bytes


def test_completed_execution_view_projects_exact_finished_runtime_without_writes(
    experiment_model_factory,
    monkeypatch,
):
    _source, source_experiment, completed = _complete_execution(
        experiment_model_factory
    )
    loaded = experiment_model_factory()
    loaded_experiment = loaded.experiment_model
    loaded_experiment.load_experiment(
        source_experiment.experiment_file_path,
        source_experiment.experiment_dir_path,
    )
    before = _hashes(Path(source_experiment.experiment_dir_path))

    monkeypatch.setattr(
        loaded_experiment,
        "ensure_execution_resume_checkpoint",
        lambda: pytest.fail("completed viewing created or repaired a checkpoint"),
    )
    monkeypatch.setattr(
        loaded_experiment,
        "_write_execution_plan_exports",
        lambda *_args, **_kwargs: pytest.fail("completed viewing rewrote exports"),
    )
    monkeypatch.setattr(
        loaded,
        "record_experiment_audit_event",
        lambda *_args, **_kwargs: pytest.fail("completed viewing wrote an audit event"),
    )
    monkeypatch.setattr(
        loaded,
        "assign_printer_heads",
        lambda: pytest.fail("completed viewing assigned printer heads to the rack"),
    )

    eligibility = loaded.load_completed_execution_view()

    assert eligibility == {
        "status": "analysis_only",
        "can_activate_runtime": False,
        "can_start_hardware": False,
        "can_resume_hardware": False,
        "reason": eligibility["reason"],
        "repairable_intent_ids": [],
        "ambiguous_intent_ids": [],
    }
    assert loaded.is_completed_execution_view_active()
    assert loaded_experiment.can_view_completed_execution()
    assert not loaded_experiment.is_authoritative_execution_runtime_active()
    assert loaded_experiment._active_authoritative_execution_session is None
    assert not loaded_experiment.uses_durable_execution_checkpoint()
    assert _hashes(Path(source_experiment.experiment_dir_path)) == before

    stock_ids = {
        stock.stock_id for stock in loaded.stock_solutions.get_all_stock_solutions()
    }
    assert stock_ids == {stock.stock_id for stock in completed.stocks}
    assert {
        head.get_stock_id() for head in loaded.get_completed_execution_display_heads()
    } == stock_ids
    for saved_well in completed.wells:
        reaction = loaded.well_plate.get_well(
            saved_well.well_id
        ).get_assigned_reaction()
        assert reaction.unique_id == saved_well.reaction_id
        assert reaction.get_all_target_droplets() == {
            dispense.stock_id: dispense.target_dispenses
            for dispense in saved_well.dispenses
        }
        for dispense in saved_well.dispenses:
            reagent = reaction.get_reagent_by_id(dispense.stock_id)
            assert reagent.added_droplets == dispense.target_dispenses
            assert reagent.completed
        assert reaction.check_all_complete()


def test_completed_execution_view_rejects_aborted_terminal_bundle(
    experiment_model_factory,
    monkeypatch,
):
    _source, source_experiment, _completed = _complete_execution(
        experiment_model_factory
    )
    loaded = experiment_model_factory()
    loaded_experiment = loaded.experiment_model
    loaded_experiment.load_experiment(
        source_experiment.experiment_file_path,
        source_experiment.experiment_dir_path,
    )
    completed_bundle = loaded_experiment.get_authoritative_execution_bundle()
    aborted_bundle = replace(
        completed_bundle,
        plan=replace(completed_bundle.plan, state=ExecutionPlanState.ABORTED),
    )

    def refresh_aborted():
        loaded_experiment._authoritative_execution_bundle = aborted_bundle
        return aborted_bundle

    monkeypatch.setattr(
        loaded_experiment,
        "_refresh_authoritative_execution_bundle",
        refresh_aborted,
    )

    with pytest.raises(RuntimeError, match="Only a valid completed execution"):
        loaded.load_completed_execution_view()

    assert not loaded.is_completed_execution_view_active()
    assert not loaded_experiment.can_view_completed_execution()
    assert not loaded_experiment.is_authoritative_execution_runtime_active()


def test_completed_execution_projection_failure_preserves_live_runtime(
    experiment_model_factory,
    monkeypatch,
):
    _source, source_experiment, _completed = _complete_execution(
        experiment_model_factory
    )
    loaded = experiment_model_factory()
    loaded_experiment = loaded.experiment_model
    loaded_experiment.load_experiment(
        source_experiment.experiment_file_path,
        source_experiment.experiment_dir_path,
    )
    stock_manager_before = loaded.stock_solutions
    reactions_before = loaded.reaction_collection
    assignments_before = {
        well.well_id: well.get_assigned_reaction()
        for well in loaded.well_plate.get_all_wells()
    }
    monkeypatch.setattr(
        loaded,
        "_build_authoritative_runtime_projection",
        lambda _bundle: (_ for _ in ()).throw(RuntimeError("projection failed")),
    )

    with pytest.raises(RuntimeError, match="projection failed"):
        loaded.load_completed_execution_view()

    assert loaded.stock_solutions is stock_manager_before
    assert loaded.reaction_collection is reactions_before
    assert {
        well.well_id: well.get_assigned_reaction()
        for well in loaded.well_plate.get_all_wells()
    } == assignments_before
    assert not loaded.is_completed_execution_view_active()
    assert not loaded_experiment.is_authoritative_execution_runtime_active()
