import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import MethodType

import pytest

from AuthoritativeExecutionLoad import (
    build_execution_runtime_spec,
    build_execution_runtime_spec_from_plan,
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
from Model import Model, PrinterHeadManager, RackModel
from test_execution_terminal_cache import _ready_completion


PLAN_ID = "f33cf5d6-2f38-4ca7-86fd-74f73baac81d"
NOW = "2026-07-17T12:00:00Z"


def _attach_test_rack(model):
    rack = RackModel(
        5,
        location_data={
            "rack_position_Left": {},
            "rack_position_Right": {},
        },
    )
    model.rack_model = rack
    model.printer_head_colors = {
        "one": "#e41a1c",
        "two": "#377eb8",
        "three": "#4daf4a",
        "four": "#984ea3",
        "five": "#ff7f00",
        "six": "#ffff33",
    }
    model.printer_head_manager = PrinterHeadManager(
        model.printer_head_colors,
        rack,
    )
    model.assign_printer_heads = MethodType(Model.assign_printer_heads, model)
    model._rack_runtime_plan_id = None
    model._recorded_audit_events = []

    def _record(event_type, summary, details=None, **_kwargs):
        model._recorded_audit_events.append(
            (event_type, summary, dict(details or {}))
        )

    model.record_experiment_audit_event = _record
    return model


def _configure_rack_order_design(model):
    em = model.experiment_model
    em.factors = []
    em.add_choice_group("Choice")
    em.add_choice_option(
        "Choice",
        "Alpha",
        [0.0, 1.0],
        "x",
        10.0,
        forced_stock_conc=10.0,
    )
    em.add_choice_option(
        "Choice",
        "Beta",
        [0.0, 1.0],
        "x",
        10.0,
        forced_stock_conc=10.0,
    )
    em.add_additive(
        "Zeta",
        [1.0],
        "x",
        10.0,
        forced_stock_conc=10.0,
    )
    em.add_additive(
        "Yankee",
        [1.0],
        "x",
        10.0,
        forced_stock_conc=10.0,
    )
    em.set_metadata(
        name="rack-order",
        target_reaction_volume_nL=100.0,
        final_reaction_volume_nL=100.0,
        printed_volume_tolerance_nL=0.0,
        fill_reagent_name="Aqua",
        fill_droplet_volume_nL=10.0,
    )
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()
    Model.load_experiment_from_model(model, finalize_execution_plan=True)
    return em.get_execution_plan_snapshot()


def _rack_stock_sequence(model):
    assigned = [
        slot.printer_head
        for slot in model.rack_model.get_all_slots()
        if slot.printer_head is not None
        and not slot.printer_head.is_calibration_chip()
    ]
    unassigned = [
        head
        for head in model.printer_head_manager.get_unassigned_printer_heads()
        if not head.is_calibration_chip()
    ]
    return tuple(head.get_stock_id() for head in assigned + unassigned)


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


def test_source_neutral_runtime_spec_preserves_recorded_over_target_and_defaults_missing(
    tmp_path,
):
    _design, plan = _write_bundle(tmp_path)
    stock_id = plan.stocks[0].stock_id

    recorded = build_execution_runtime_spec_from_plan(
        plan,
        {"A1": {"reagents": {stock_id: {"added_droplets": 19}}}},
    )
    missing = build_execution_runtime_spec_from_plan(plan, {})

    assert recorded.wells[0].targets[stock_id] == 16
    assert recorded.wells[0].added[stock_id] == 19
    assert missing.wells[0].added[stock_id] == 0


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


@pytest.mark.parametrize("with_progress", [False, True])
def test_same_session_activation_preserves_live_rack_objects_and_positions(
    experiment_model_factory,
    with_progress,
):
    model = _attach_test_rack(experiment_model_factory())
    plan = _configure_rack_order_design(model)
    em = model.experiment_model

    if with_progress:
        model.load_authoritative_execution_runtime()
        saved_well = next(
            well
            for well in plan.wells
            if any(item.target_dispenses > 0 for item in well.dispenses)
        )
        saved_dispense = next(
            item for item in saved_well.dispenses if item.target_dispenses > 0
        )
        intent_id = em.begin_execution_print_intent(
            well_id=saved_well.well_id,
            stock_id=saved_dispense.stock_id,
            commanded_droplets=1,
            printer_head_id="same-session-progress-head",
        )
        model.well_plate.get_well(saved_well.well_id).record_stock_print(
            saved_dispense.stock_id,
            1,
        )
        em.create_progress_file(execution_intent_id=intent_id)
        em.complete_execution_print_intent(intent_id)

    fill_stock_id = next(stock.stock_id for stock in plan.stocks if stock.units == "--")
    fill_head = model.printer_head_manager.get_printer_head_by_id(fill_stock_id)
    model.printer_head_manager.swap_printer_head(0, fill_head)
    model.rack_model.swap_printer_heads_between_slots(1, 3)
    model.rack_model.confirm_slot(0)
    model.rack_model.confirm_slot(1)
    fill_head.set_absolute_volume(37.5)

    slot_heads_before = tuple(
        slot.printer_head for slot in model.rack_model.get_all_slots()
    )
    confirmations_before = tuple(
        slot.confirmed for slot in model.rack_model.get_all_slots()
    )
    unassigned_before = tuple(
        model.printer_head_manager.get_unassigned_printer_heads()
    )
    identities_before = {
        id(head): head.printer_head_id
        for head in model.printer_head_manager.get_all_printer_heads()
    }

    em.load_experiment(em.experiment_file_path, em.experiment_dir_path)
    eligibility = model.load_authoritative_execution_runtime()

    assert eligibility["status"] == (
        "ready_to_resume" if with_progress else "ready_to_start"
    )
    assert tuple(
        slot.printer_head for slot in model.rack_model.get_all_slots()
    ) == slot_heads_before
    assert tuple(
        slot.confirmed for slot in model.rack_model.get_all_slots()
    ) == confirmations_before
    assert tuple(
        model.printer_head_manager.get_unassigned_printer_heads()
    ) == unassigned_before
    assert fill_head.get_current_volume() == 37.5
    assert {
        id(head): head.printer_head_id
        for head in model.printer_head_manager.get_all_printer_heads()
    } == identities_before
    assert model.printer_head_manager.get_assigned_printer_heads() == {
        index: head
        for index, head in enumerate(slot_heads_before)
        if head is not None
    }
    assert model.rack_model.expected_slot_printer_heads == list(slot_heads_before)
    assert model.rack_model.expected_gripper_printer_head is None
    assert model._rack_runtime_plan_id == plan.plan_id
    activation_details = model._recorded_audit_events[-1][2]
    assert activation_details["rack_assignment_mode"] == "same_session_preserved"
    assert activation_details["restored_assigned_head_count"] == 4
    assert activation_details["restored_unassigned_head_count"] == 1


def test_new_session_assignment_matches_initial_finalize_order(
    experiment_model_factory,
):
    source = _attach_test_rack(experiment_model_factory())
    plan = _configure_rack_order_design(source)
    initial_sequence = _rack_stock_sequence(source)

    loaded = _attach_test_rack(experiment_model_factory())
    loaded.experiment_model.load_experiment(
        source.experiment_model.experiment_file_path,
        source.experiment_model.experiment_dir_path,
    )
    loaded.load_authoritative_execution_runtime()

    fill_stock_id = next(stock.stock_id for stock in plan.stocks if stock.units == "--")
    assert _rack_stock_sequence(loaded) == initial_sequence
    assert initial_sequence[-1] == fill_stock_id
    assert [
        stock_id.split("_", 1)[0] for stock_id in initial_sequence
    ] == ["Zeta", "Yankee", "Alpha", "Beta", "Aqua"]
    assert loaded._recorded_audit_events[-1][2]["rack_assignment_mode"] == (
        "initial_finalize_order"
    )


def test_different_plan_uses_initial_finalize_order_not_live_layout(
    experiment_model_factory,
):
    live = _attach_test_rack(experiment_model_factory())
    live_plan = _configure_rack_order_design(live)
    target = _attach_test_rack(experiment_model_factory())
    target_plan = _configure_rack_order_design(target)
    target_sequence = _rack_stock_sequence(target)
    assert live_plan.plan_id != target_plan.plan_id

    fill_stock_id = next(
        stock.stock_id for stock in live_plan.stocks if stock.units == "--"
    )
    live_fill_head = live.printer_head_manager.get_printer_head_by_id(fill_stock_id)
    live.printer_head_manager.swap_printer_head(0, live_fill_head)
    assert live.rack_model.get_all_slots()[0].printer_head is live_fill_head

    live.experiment_model.load_experiment(
        target.experiment_model.experiment_file_path,
        target.experiment_model.experiment_dir_path,
    )
    live.load_authoritative_execution_runtime()

    assert _rack_stock_sequence(live) == target_sequence
    assert live.rack_model.get_all_slots()[0].printer_head is not live_fill_head
    assert live._rack_runtime_plan_id == target_plan.plan_id
    assert live._recorded_audit_events[-1][2]["rack_assignment_mode"] == (
        "initial_finalize_order"
    )


def test_explicit_runtime_clear_forgets_same_session_rack_ownership(
    experiment_model_factory,
):
    model = _attach_test_rack(experiment_model_factory())
    _configure_rack_order_design(model)
    assert model._rack_runtime_plan_id is not None

    Model.clear_experiment(model)

    assert model._rack_runtime_plan_id is None


def test_same_session_activation_with_occupied_gripper_fails_before_mutation(
    experiment_model_factory,
):
    model = _attach_test_rack(experiment_model_factory())
    plan = _configure_rack_order_design(model)
    em = model.experiment_model
    model.rack_model.confirm_slot(0)
    model.rack_model.transfer_to_gripper(0)
    em.load_experiment(em.experiment_file_path, em.experiment_dir_path)

    slots_before = tuple(
        (slot.printer_head, slot.confirmed, slot.locked)
        for slot in model.rack_model.get_all_slots()
    )
    gripper_before = model.rack_model.get_gripper_printer_head()
    heads_before = tuple(model.printer_head_manager.get_all_printer_heads())
    unassigned_before = tuple(
        model.printer_head_manager.get_unassigned_printer_heads()
    )
    resume_path = Path(em.execution_resume_file_path)
    assert not resume_path.exists()

    with pytest.raises(RuntimeError, match="gripper holds a printer head"):
        model.load_authoritative_execution_runtime()

    assert tuple(
        (slot.printer_head, slot.confirmed, slot.locked)
        for slot in model.rack_model.get_all_slots()
    ) == slots_before
    assert model.rack_model.get_gripper_printer_head() is gripper_before
    assert tuple(model.printer_head_manager.get_all_printer_heads()) == heads_before
    assert tuple(
        model.printer_head_manager.get_unassigned_printer_heads()
    ) == unassigned_before
    assert not resume_path.exists()
    assert model._rack_runtime_plan_id == plan.plan_id


def test_inconsistent_same_session_rack_fails_before_mutation(
    experiment_model_factory,
):
    model = _attach_test_rack(experiment_model_factory())
    plan = _configure_rack_order_design(model)
    em = model.experiment_model
    model.printer_head_manager.unassigned_printer_heads.clear()
    em.load_experiment(em.experiment_file_path, em.experiment_dir_path)

    slots_before = tuple(
        slot.printer_head for slot in model.rack_model.get_all_slots()
    )
    manager_heads_before = tuple(
        model.printer_head_manager.get_all_printer_heads()
    )
    resume_path = Path(em.execution_resume_file_path)
    assert not resume_path.exists()

    with pytest.raises(RuntimeError, match="assignment state is inconsistent"):
        model.load_authoritative_execution_runtime()

    assert tuple(
        slot.printer_head for slot in model.rack_model.get_all_slots()
    ) == slots_before
    assert tuple(
        model.printer_head_manager.get_all_printer_heads()
    ) == manager_heads_before
    assert model.printer_head_manager.get_unassigned_printer_heads() == []
    assert not resume_path.exists()
    assert model._rack_runtime_plan_id == plan.plan_id


def test_same_session_identity_change_unconfirms_only_affected_slot(
    experiment_model_factory,
    monkeypatch,
):
    model = _attach_test_rack(experiment_model_factory())
    _configure_rack_order_design(model)
    em = model.experiment_model
    model.rack_model.confirm_slot(0)
    model.rack_model.confirm_slot(1)
    affected_head = model.rack_model.get_all_slots()[0].printer_head
    unaffected_head = model.rack_model.get_all_slots()[1].printer_head
    affected_stock_id = affected_head.get_stock_id()
    original_builder = model._build_authoritative_runtime_projection

    def _build_with_changed_identity(bundle):
        projection = original_builder(bundle)
        projection.stock_specs[affected_stock_id] = replace(
            projection.stock_specs[affected_stock_id],
            printer_head_id="authoritative-replacement-head",
        )
        return projection

    monkeypatch.setattr(
        model,
        "_build_authoritative_runtime_projection",
        _build_with_changed_identity,
    )
    em.load_experiment(em.experiment_file_path, em.experiment_dir_path)

    model.load_authoritative_execution_runtime()

    slots = model.rack_model.get_all_slots()
    assert slots[0].printer_head is affected_head
    assert slots[1].printer_head is unaffected_head
    assert affected_head.printer_head_id == "authoritative-replacement-head"
    assert not slots[0].confirmed
    assert slots[1].confirmed


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
