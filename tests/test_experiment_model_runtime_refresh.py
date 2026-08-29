import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from Model import (
    EJECTION_VOLUME_HARD_MAX_NL,
    EJECTION_VOLUME_HARD_MIN_NL,
    ExperimentModel,
    printing_mode_allowed_range_nl,
)


class _SignalRecorder:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def test_refresh_runtime_after_plan_change_rebinds_keys_and_emits_well_refresh():
    stock_updated = _SignalRecorder()
    well_state_changed = _SignalRecorder()
    write_calls = []
    rebind_calls = []

    em = SimpleNamespace(
        _has_runtime_assignments=lambda: True,
        _rebind_runtime_assignments_to_current_plans=lambda: rebind_calls.append(True) or True,
        write_keys_now=lambda: write_calls.append(True),
        stock_updated=stock_updated,
        _runtime_well_plate=SimpleNamespace(well_state_changed_signal=well_state_changed),
    )
    em._refresh_runtime_after_plan_change = (
        ExperimentModel._refresh_runtime_after_plan_change.__get__(em, ExperimentModel)
    )

    refreshed = em._refresh_runtime_after_plan_change(write_keys_if_assigned=True)

    assert refreshed is True
    assert rebind_calls == [True]
    assert write_calls == [True]
    assert stock_updated.calls == [()]
    assert well_state_changed.calls == [("all",)]


def test_apply_droplet_volume_for_option_without_assignments_skips_runtime_rebind():
    refresh_calls = []
    option = SimpleNamespace(
        name="glycerol",
        droplet_nL=10.0,
        units="mM",
        targets=[0.5],
        starting_conc=0.0,
    )
    factor = SimpleNamespace(name="glycerol", kind="additive", options=[option])
    stock = {
        "stock_concentration": 10.0,
        "droplet_volume_nL": 10.0,
        "units": "mM",
        "droplets_per_target": {},
    }
    stock_row = {
        "factor_name": "glycerol",
        "option_name": "",
        "stock_concentration": 10.0,
        "droplet_volume_nL": 10.0,
    }

    em = SimpleNamespace(
        plans_per_option={("glycerol", None): {"stocks": [stock], "n_stocks": 1}},
        factors=[factor],
        metadata={"final_reaction_volume_nL": 500.0},
        _stock_rows_cache=[stock_row],
        _normalize_target_key=lambda value: round(float(value), 6),
        _refresh_plan_preview_maps=lambda: None,
        generate_experiment=lambda: None,
        _refresh_runtime_after_plan_change=lambda **kwargs: refresh_calls.append(kwargs) or True,
        _last_worst_nonfill_volume_nL=0.0,
        unsaved_changes=False,
    )
    em._evaluate_single_forced_target = (
        ExperimentModel._evaluate_single_forced_target.__get__(em, ExperimentModel)
    )
    em.apply_droplet_volume_for_option = (
        ExperimentModel.apply_droplet_volume_for_option.__get__(em, ExperimentModel)
    )

    result = em.apply_droplet_volume_for_option("glycerol", None, 12.0, write_keys_if_assigned=False)

    assert refresh_calls == []
    assert option.droplet_nL == 12.0
    assert option.intended_droplet_nL == 10.0
    assert option.forced_stock_conc == 10.0
    assert stock["droplet_volume_nL"] == 12.0
    assert stock_row["droplet_volume_nL"] == 12.0
    assert em.unsaved_changes is True
    assert result["stock_row_updated"] is True
    assert result["saved_experiment"] is False


def test_apply_fill_droplet_volume_without_assignments_skips_runtime_rebind():
    refresh_calls = []
    generate_calls = []

    em = SimpleNamespace(
        metadata={"fill_droplet_volume_nL": 10.0},
        preview_fill_requantized=lambda new_fill: {
            "total_drops_old": 50,
            "total_drops_new": 42,
            "total_drops_delta": -8,
        },
        generate_experiment=lambda: generate_calls.append(True),
        _refresh_runtime_after_plan_change=lambda **kwargs: refresh_calls.append(kwargs) or True,
        unsaved_changes=False,
    )
    em.apply_fill_droplet_volume = (
        ExperimentModel.apply_fill_droplet_volume.__get__(em, ExperimentModel)
    )

    result = em.apply_fill_droplet_volume(12.0, write_keys_if_assigned=True)

    assert generate_calls == [True]
    assert refresh_calls == []
    assert em.metadata["intended_fill_droplet_volume_nL"] == 10.0
    assert em.unsaved_changes is True
    assert result["new_fill_nL"] == 12.0
    assert result["total_drops_new"] == 42
    assert result["saved_experiment"] is False


def test_printing_mode_volume_range_uses_shared_hard_envelope():
    assert EJECTION_VOLUME_HARD_MIN_NL == pytest.approx(1.0)
    assert EJECTION_VOLUME_HARD_MAX_NL == pytest.approx(250.0)
    assert printing_mode_allowed_range_nl("droplet") == (
        EJECTION_VOLUME_HARD_MIN_NL,
        EJECTION_VOLUME_HARD_MAX_NL,
    )
    assert printing_mode_allowed_range_nl("stream") == (
        EJECTION_VOLUME_HARD_MIN_NL,
        EJECTION_VOLUME_HARD_MAX_NL,
    )


def _build_apply_droplet_volume_model(*, printing_mode="droplet", current_volume=10.0):
    option = SimpleNamespace(
        name="glycerol",
        droplet_nL=float(current_volume),
        units="mM",
        targets=[0.5],
        starting_conc=0.0,
        printing_mode=printing_mode,
    )
    factor = SimpleNamespace(name="glycerol", kind="additive", options=[option])
    stock = {
        "stock_concentration": 10.0,
        "droplet_volume_nL": float(current_volume),
        "units": "mM",
        "droplets_per_target": {},
    }

    em = SimpleNamespace(
        plans_per_option={("glycerol", None): {"stocks": [stock], "n_stocks": 1}},
        factors=[factor],
        metadata={"final_reaction_volume_nL": 500.0},
        _stock_rows_cache=[],
        _normalize_target_key=lambda value: round(float(value), 6),
        _refresh_plan_preview_maps=lambda: None,
        generate_experiment=lambda: None,
        _refresh_runtime_after_plan_change=lambda **kwargs: True,
        _last_worst_nonfill_volume_nL=0.0,
        unsaved_changes=False,
    )
    em._evaluate_single_forced_target = (
        ExperimentModel._evaluate_single_forced_target.__get__(em, ExperimentModel)
    )
    em.apply_droplet_volume_for_option = (
        ExperimentModel.apply_droplet_volume_for_option.__get__(em, ExperimentModel)
    )
    return em, option


@pytest.mark.parametrize(
    ("new_volume", "printing_mode"),
    [
        (60.0, "droplet"),
        (10.0, "stream"),
        (30.0, "stream"),
        (30.0, "droplet"),
    ],
)
def test_apply_droplet_volume_for_option_accepts_explicit_mode_inside_hard_envelope(
    new_volume,
    printing_mode,
):
    em, option = _build_apply_droplet_volume_model(printing_mode=printing_mode)

    result = em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        new_volume,
        write_keys_if_assigned=False,
        printing_mode=printing_mode,
    )

    assert option.droplet_nL == pytest.approx(new_volume)
    assert option.printing_mode == printing_mode
    assert result["new_droplet_nL"] == pytest.approx(new_volume)
    assert result["applied_printing_mode"] == printing_mode


@pytest.mark.parametrize(
    ("new_volume", "printing_mode", "match"),
    [
        ("not-a-number", "droplet", "must be numeric"),
        (0.0, "droplet", "outside the allowed range for droplet mode"),
        (-1.0, "stream", "outside the allowed range for stream mode"),
        (float("inf"), "stream", "outside the allowed range for stream mode"),
        (250.1, "stream", "outside the allowed range for stream mode"),
    ],
)
def test_apply_droplet_volume_for_option_rejects_values_outside_hard_envelope(
    new_volume,
    printing_mode,
    match,
):
    em, _option = _build_apply_droplet_volume_model(printing_mode=printing_mode)

    with pytest.raises(ValueError, match=match):
        em.apply_droplet_volume_for_option(
            "glycerol",
            None,
            new_volume,
            write_keys_if_assigned=False,
            printing_mode=printing_mode,
        )


@pytest.mark.parametrize(
    ("new_volume", "printing_mode"),
    [
        (10.0, "stream"),
        (30.0, "stream"),
        (30.0, "droplet"),
    ],
)
def test_apply_fill_droplet_volume_accepts_explicit_mode_inside_hard_envelope(
    new_volume,
    printing_mode,
):
    em = SimpleNamespace(
        metadata={"fill_droplet_volume_nL": 12.0, "fill_printing_mode": printing_mode},
        preview_fill_requantized=lambda new_fill: {
            "total_drops_old": 50,
            "total_drops_new": 42,
            "total_drops_delta": -8,
        },
        generate_experiment=lambda: None,
        _refresh_runtime_after_plan_change=lambda **kwargs: True,
        unsaved_changes=False,
    )
    em.apply_fill_droplet_volume = (
        ExperimentModel.apply_fill_droplet_volume.__get__(em, ExperimentModel)
    )

    result = em.apply_fill_droplet_volume(
        new_volume,
        write_keys_if_assigned=True,
        printing_mode=printing_mode,
    )

    assert em.metadata["fill_droplet_volume_nL"] == pytest.approx(new_volume)
    assert em.metadata["fill_printing_mode"] == printing_mode
    assert result["new_fill_nL"] == pytest.approx(new_volume)
    assert result["applied_printing_mode"] == printing_mode


@pytest.mark.parametrize(
    ("new_volume", "printing_mode", "match"),
    [
        ("not-a-number", "droplet", "must be numeric"),
        (0.0, "droplet", "outside the allowed range for droplet mode"),
        (-1.0, "stream", "outside the allowed range for stream mode"),
        (float("inf"), "stream", "outside the allowed range for stream mode"),
        (250.1, "stream", "outside the allowed range for stream mode"),
    ],
)
def test_apply_fill_droplet_volume_rejects_values_outside_hard_envelope(
    new_volume,
    printing_mode,
    match,
):
    em = SimpleNamespace(
        metadata={"fill_droplet_volume_nL": 60.0, "fill_printing_mode": printing_mode},
        preview_fill_requantized=lambda new_fill: {
            "total_drops_old": 50,
            "total_drops_new": 42,
            "total_drops_delta": -8,
        },
        generate_experiment=lambda: None,
        _refresh_runtime_after_plan_change=lambda **kwargs: True,
        unsaved_changes=False,
    )
    em.apply_fill_droplet_volume = (
        ExperimentModel.apply_fill_droplet_volume.__get__(em, ExperimentModel)
    )

    with pytest.raises(ValueError, match=match):
        em.apply_fill_droplet_volume(
            new_volume,
            write_keys_if_assigned=True,
            printing_mode=printing_mode,
        )


def _configure_calibrated_volume_design(em, *, targets=None):
    em.factors = []
    em.add_additive(
        "glycerol",
        list(targets or [0.9]),
        "mM",
        10.0,
        forced_stock_conc=10.0,
        printing_mode="droplet",
    )
    em.set_metadata(
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()


def _attach_mutable_runtime(model):
    em = model.experiment_model
    model.stock_solutions, model.reaction_collection = (
        model.load_reactions_from_model()
    )
    model.well_plate.assign_reactions_to_wells(
        model.reaction_collection.get_all_reactions()
    )
    em.set_runtime_context(model.well_plate, model.reaction_collection)
    em.write_keys_now()
    return model.reaction_collection


def _runtime_reagent_state(collection):
    return [
        (
            reaction.unique_id,
            [
                (
                    stock_id,
                    reagent.target_droplets,
                    reagent.added_droplets,
                    reagent.completed,
                )
                for stock_id, reagent in sorted(
                    reaction.get_all_reagents().items()
                )
            ],
        )
        for reaction in collection.get_all_reactions()
    ]


def _mutable_calibration_state(em, collection):
    paths = (
        em.experiment_file_path,
        em.progress_file_path,
        em.key_file_path,
        em.concentration_key_file_path,
    )
    return {
        "design": copy.deepcopy(em.to_dict()),
        "plans": copy.deepcopy(em.plans_per_option),
        "stock_rows": copy.deepcopy(em._stock_rows_cache),
        "fill_row": copy.deepcopy(em._fill_row_cache),
        "preview": copy.deepcopy(em._target_preview_map),
        "unreachable": copy.deepcopy(em._unreachable_preview_map),
        "reactions": em._reactions_df.to_dict(orient="split"),
        "worst_nonfill": em._last_worst_nonfill_volume_nL,
        "applied": copy.deepcopy(em.applied_imaging_calibrations),
        "manual_refuel": copy.deepcopy(em.manual_refuel_checks),
        "calibrated_allocation": copy.deepcopy(em.calibrated_stock_allocation),
        "calibrated_status": copy.deepcopy(
            em.calibrated_stock_allocation_status
        ),
        "progress": copy.deepcopy(em.progress_data),
        "progress_reference": copy.deepcopy(
            em._progress_execution_reference
        ),
        "runtime": _runtime_reagent_state(collection),
        "unsaved_changes": em.unsaved_changes,
        "files": {
            path: (
                Path(path).exists(),
                Path(path).read_bytes() if Path(path).exists() else None,
            )
            for path in paths
        },
    }


def _first_option_payload(payload, factor_name):
    for factor in payload["factors"]:
        if factor["name"] == factor_name:
            return factor["options"][0]
    raise AssertionError(f"Factor {factor_name!r} not found")


def _first_saved_target(em, factor_name):
    stock = em.plans_per_option[(factor_name, None)]["stocks"][0]
    return next(iter(stock["droplets_per_target"].values()))


def _stock_id_for_design_row(em, factor_name, option_name=None):
    for row in em.get_stock_table_rows(include_fill=True):
        if row.get("factor_name") == factor_name and (row.get("option_name") or None) == option_name:
            return em._stock_row_base_id(row)
    raise AssertionError(f"Stock row for {factor_name!r}/{option_name!r} not found")


def _printer_head(stock_id, *, printer_head_id="head-1", printing_mode="droplet"):
    return SimpleNamespace(
        get_stock_id=lambda: stock_id,
        printer_head_id=printer_head_id,
        get_printing_mode=lambda: printing_mode,
    )


def _machine_model_for_calibration(
    *,
    pw_us=1450,
    pressure_psi=1.35,
    refuel_pw_us=2200,
    refuel_pressure_psi=0.30,
):
    return SimpleNamespace(
        get_print_pulse_width=lambda: pw_us,
        get_current_print_pressure=lambda: pressure_psi,
        get_target_print_pressure=lambda: pressure_psi,
        get_refuel_pulse_width=lambda: refuel_pw_us,
        get_current_refuel_pressure=lambda: refuel_pressure_psi,
        get_target_refuel_pressure=lambda: refuel_pressure_psi,
    )


def test_apply_droplet_volume_for_option_persists_effective_and_intended_volume(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)

    result = em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
    )

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    option = _first_option_payload(payload, "glycerol")
    assert option["droplet_nL"] == 30.0
    assert option["printing_mode"] == "droplet"
    assert option["intended_droplet_nL"] == 10.0
    assert option["forced_stock_conc"] == result["stock_concentration"]
    assert result["saved_experiment"] is True
    assert em.unsaved_changes is False


@pytest.mark.parametrize(
    "failure_point",
    [
        "generate",
        "record",
        "runtime",
        "progress",
        "key",
        "concentration",
        "design",
    ],
)
def test_mutable_single_stock_calibration_rolls_back_every_failure_boundary(
    experiment_model_factory,
    monkeypatch,
    qapp,
    failure_point,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em, targets=[0.9, 1.8])
    runtime = _attach_mutable_runtime(model)
    first_reagent = next(
        iter(runtime.get_all_reactions()[0].get_all_reagents().values())
    )
    first_reagent.added_droplets = 1
    first_reagent.completed = first_reagent.is_complete()
    em.write_keys_now()
    em.save_experiment()

    stock_id = _stock_id_for_design_row(em, "glycerol")
    head = _printer_head(
        stock_id,
        printer_head_id="transactional-stream-head",
        printing_mode="stream",
    )
    calibration = {
        "printer_head": head,
        "measured_volume_nL": 30.0,
        "run_id": f"transaction-{failure_point}",
    }

    audit_events = []
    em.set_calibration_manager(
        SimpleNamespace(
            model=SimpleNamespace(
                record_experiment_audit_event=lambda *args, **kwargs: (
                    audit_events.append((args, kwargs))
                )
            )
        )
    )
    emitted = {
        "experiment": [],
        "stock": [],
        "applied": [],
        "refuel": [],
        "well": [],
    }
    committed_views = []
    em.experiment_generated.connect(
        lambda *args: emitted["experiment"].append(args)
    )
    def _capture_committed_stock_state(*args):
        emitted["stock"].append(args)
        payload = json.loads(
            Path(em.experiment_file_path).read_text(encoding="utf-8")
        )
        committed_views.append(
            {
                "saved_volume": _first_option_payload(
                    payload,
                    "glycerol",
                )["droplet_nL"],
                "runtime": _runtime_reagent_state(runtime),
                "progress": json.loads(
                    Path(em.progress_file_path).read_text(encoding="utf-8")
                ),
                "key": Path(em.key_file_path).read_bytes(),
                "concentration": Path(
                    em.concentration_key_file_path
                ).read_bytes(),
            }
        )

    em.stock_updated.connect(_capture_committed_stock_state)
    em.applied_imaging_calibration_changed.connect(
        lambda *args: emitted["applied"].append(args)
    )
    em.manual_refuel_check_changed.connect(
        lambda *args: emitted["refuel"].append(args)
    )
    model.well_plate.well_state_changed_signal.connect(
        lambda *args: emitted["well"].append(args)
    )

    before = _mutable_calibration_state(em, runtime)
    target = em
    method_name = {
        "generate": "generate_experiment",
        "record": "record_applied_imaging_calibration",
        "progress": "create_progress_file",
        "key": "create_key_file",
        "concentration": "create_concentration_key_file",
        "design": "save_experiment",
    }.get(failure_point)
    if failure_point == "runtime":
        target = runtime
        method_name = "set_reaction_items_for_index"
    original = getattr(target, method_name)

    if failure_point == "runtime":
        calls = 0

        def _fail_runtime(index, items, **kwargs):
            nonlocal calls
            calls += 1
            result = original(index, items, **kwargs)
            if calls == 2:
                raise RuntimeError("injected runtime failure")
            return result

        replacement = _fail_runtime
    else:

        def _fail_after(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError(f"injected {failure_point} failure")

        replacement = _fail_after
    monkeypatch.setattr(target, method_name, replacement)

    with pytest.raises(RuntimeError, match=f"injected {failure_point} failure"):
        em.apply_droplet_volume_for_option(
            "glycerol",
            None,
            30.0,
            write_keys_if_assigned=True,
            applied_calibration=calibration,
            printing_mode="stream",
        )

    assert _mutable_calibration_state(em, runtime) == before
    assert emitted == {
        "experiment": [],
        "stock": [],
        "applied": [],
        "refuel": [],
        "well": [],
    }
    assert audit_events == []

    monkeypatch.setattr(target, method_name, original)
    result = em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=True,
        applied_calibration=calibration,
        printing_mode="stream",
    )

    assert result["saved_experiment"] is True
    assert len(emitted["experiment"]) == 1
    assert len(emitted["stock"]) == 1
    assert len(emitted["applied"]) == 1
    assert len(emitted["refuel"]) == 1
    assert emitted["well"] == [("all",)]
    assert len(committed_views) == 1
    assert committed_views[0]["saved_volume"] == pytest.approx(30.0)
    assert committed_views[0]["runtime"] == _runtime_reagent_state(runtime)
    assert committed_views[0]["progress"]
    assert b"30.0nL" in committed_views[0]["key"]
    assert committed_views[0]["concentration"]


def test_mutable_calibration_surfaces_incomplete_rollback(
    experiment_model_factory,
    monkeypatch,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    original_generate = em.generate_experiment

    def _fail_generate():
        original_generate()
        raise RuntimeError("injected calibration failure")

    def _fail_file_restore(_snapshots):
        raise RuntimeError("injected rollback failure")

    monkeypatch.setattr(em, "generate_experiment", _fail_generate)
    monkeypatch.setattr(
        ExperimentModel,
        "_restore_mutable_calibration_files",
        staticmethod(_fail_file_restore),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Mutable calibration failed and rollback was incomplete: "
            "files: injected rollback failure"
        ),
    ) as exc_info:
        em.apply_droplet_volume_for_option(
            "glycerol",
            None,
            30.0,
            write_keys_if_assigned=False,
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "injected calibration failure" in str(exc_info.value.__cause__)
    assert em.unsaved_changes is True


def test_mutable_calibration_without_key_write_still_rebinds_runtime(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em, targets=[0.9, 1.8])
    runtime = _attach_mutable_runtime(model)
    runtime_before = _runtime_reagent_state(runtime)
    derived_before = {
        path: Path(path).read_bytes()
        for path in (
            em.progress_file_path,
            em.key_file_path,
            em.concentration_key_file_path,
        )
    }

    result = em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
    )

    assert result["saved_experiment"] is True
    assert _runtime_reagent_state(runtime) != runtime_before
    assert {
        path: Path(path).read_bytes()
        for path in derived_before
    } == derived_before
    saved = json.loads(
        Path(em.experiment_file_path).read_text(encoding="utf-8")
    )
    assert _first_option_payload(saved, "glycerol")["droplet_nL"] == pytest.approx(
        30.0
    )


def test_mutable_single_stock_calibration_above_threshold_warns_and_applies(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    em.factors = []
    em.add_additive(
        "single-warning",
        [1.0],
        "mM",
        10.0,
        forced_stock_conc=2.5,
        printing_mode="droplet",
    )
    em.set_metadata(
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=200.0,
        final_reaction_volume_nL=500.0,
        printed_volume_tolerance_nL=0.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()
    stock_id = _stock_id_for_design_row(em, "single-warning")
    head = _printer_head(
        stock_id,
        printer_head_id="mutable-single-warning-head",
        printing_mode="stream",
    )

    preview = em.preview_requantized_for_option(
        ("single-warning", None),
        250.0,
        calibrated_stock_id=stock_id,
        printing_mode="stream",
    )

    assert preview["ok"] is True
    warning = preview["volume_warning"]
    assert warning["affected_row_count"] == 1
    assert warning["max_total_volume_nL"] == pytest.approx(250.0)

    result = em.apply_droplet_volume_for_option(
        "single-warning",
        None,
        250.0,
        write_keys_if_assigned=False,
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 250.0,
            "run_id": "mutable-single-warning",
        },
        printing_mode="stream",
    )

    assert result["volume_warning"] == warning
    assert em._reactions_df.iloc[0]["fill_drops"] == 0
    assert em._calibration_volume_warning_for_generated_reactions() == warning


def test_mutable_fill_calibration_above_final_volume_warns_and_applies(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    em.set_metadata(printed_volume_tolerance_nL=0.0)
    em.generate_experiment()
    em.save_experiment()
    fill_stock_id = _stock_id_for_design_row(em, "Water")
    head = _printer_head(
        fill_stock_id,
        printer_head_id="mutable-fill-warning-head",
        printing_mode="stream",
    )

    preview = em.preview_fill_requantized(250.0)

    assert preview["ok"] is True
    warning = preview["volume_warning"]
    assert warning["affected_row_count"] == 1
    assert warning["affected_rows"][0]["exceeds_final_reaction_volume"] is True

    result = em.apply_fill_droplet_volume(
        250.0,
        write_keys_if_assigned=False,
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 250.0,
            "run_id": "mutable-fill-warning",
        },
        printing_mode="stream",
    )

    assert result["volume_warning"] == warning
    assert em.metadata["fill_droplet_volume_nL"] == pytest.approx(250.0)
    assert em._calibration_volume_warning_for_generated_reactions() == warning

    glycerol_stock_id = _stock_id_for_design_row(em, "glycerol")
    glycerol_head = _printer_head(
        glycerol_stock_id,
        printer_head_id="mutable-stock-after-fill-warning-head",
        printing_mode="droplet",
    )
    reagent_preview = em.preview_requantized_for_option(
        ("glycerol", None),
        30.0,
        calibrated_stock_id=glycerol_stock_id,
        printing_mode="droplet",
    )
    assert reagent_preview["volume_warning"] is not None

    reagent_result = em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
        applied_calibration={
            "printer_head": glycerol_head,
            "measured_volume_nL": 30.0,
            "run_id": "mutable-stock-after-fill-warning",
        },
        printing_mode="droplet",
    )
    assert reagent_result["volume_warning"] == reagent_preview["volume_warning"]


@pytest.mark.parametrize("failure_point", ["generate", "record"])
def test_mutable_fill_calibration_rolls_back_staged_state(
    experiment_model_factory,
    monkeypatch,
    failure_point,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em, targets=[0.9, 1.8])
    runtime = _attach_mutable_runtime(model)
    em.save_experiment()
    fill_stock_id = _stock_id_for_design_row(em, "Water")
    calibration = {
        "printer_head": _printer_head(
            fill_stock_id,
            printer_head_id="transactional-fill-head",
            printing_mode="stream",
        ),
        "measured_volume_nL": 30.0,
        "run_id": f"fill-{failure_point}",
    }
    before = _mutable_calibration_state(em, runtime)

    method_name = (
        "generate_experiment"
        if failure_point == "generate"
        else "record_applied_imaging_calibration"
    )
    original = getattr(em, method_name)

    def _fail_after(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError(f"injected fill {failure_point} failure")

    monkeypatch.setattr(em, method_name, _fail_after)

    with pytest.raises(
        RuntimeError,
        match=f"injected fill {failure_point} failure",
    ):
        em.apply_fill_droplet_volume(
            30.0,
            write_keys_if_assigned=True,
            applied_calibration=calibration,
            printing_mode="stream",
        )

    assert _mutable_calibration_state(em, runtime) == before



def test_apply_droplet_volume_for_option_can_switch_printing_mode(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    stock_id = _stock_id_for_design_row(em, "glycerol")
    head = _printer_head(stock_id, printing_mode="stream")

    result = em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
        printing_mode="stream",
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 30.0,
            "pw_us": 1800,
            "pressure_psi": 1.80,
            "run_id": "stream-run",
            "phase": "stream",
            "timestamp": "2026-03-18T10:00:00Z",
            "source_row_fingerprint": ("stream-run", "stream", "2026-03-18T10:00:00Z", 1800, 1.80, 30.0),
        },
    )

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    option = _first_option_payload(payload, "glycerol")
    assert option["droplet_nL"] == 30.0
    assert option["printing_mode"] == "stream"
    assert option["intended_droplet_nL"] == 10.0
    assert option["intended_printing_mode"] == "droplet"
    assert result["original_printing_mode"] == "droplet"
    assert result["applied_printing_mode"] == "stream"

    record = em.get_applied_imaging_calibration(printer_head=head)
    assert record["printing_mode"] == "stream"
    assert record["original_printing_mode"] == "droplet"
    assert record["applied_printing_mode"] == "stream"
    assert record["run_id"] == "stream-run"

    reloaded_model = experiment_model_factory()
    reloaded = reloaded_model.experiment_model
    reloaded.load_experiment(em.experiment_file_path, em.experiment_dir_path)
    reloaded_option = reloaded.factors[0].options[0]
    assert reloaded_option.droplet_nL == 30.0
    assert reloaded_option.printing_mode == "stream"
    assert reloaded_option.intended_droplet_nL == 10.0
    assert reloaded_option.intended_printing_mode == "droplet"

    validation = reloaded.validate_applied_imaging_calibration_for_print(
        printer_head=head,
        machine_model=_machine_model_for_calibration(pw_us=1800, pressure_psi=1.80),
    )
    assert reloaded.is_read_only_legacy_execution()
    assert validation["ok"] is False
    assert validation["code"] == "context_unavailable"


def test_stream_calibration_marks_manual_refuel_check_required(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    head = _printer_head(_stock_id_for_design_row(em, "glycerol"), printing_mode="stream")

    em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
        printing_mode="stream",
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 30.0,
            "pw_us": 1800,
            "pressure_psi": 1.80,
            "run_id": "stream-run",
            "phase": "stream",
            "timestamp": "2026-03-18T10:00:00Z",
            "source_row_fingerprint": ("stream-run", "stream", "2026-03-18T10:00:00Z", 1800, 1.80, 30.0),
        },
    )

    record = em.get_manual_refuel_check(printer_head=head)
    assert record["status"] == "required"
    assert record["printing_mode"] == "stream"
    validation = em.validate_manual_refuel_check_for_print(
        printer_head=head,
        machine_model=_machine_model_for_calibration(pw_us=1800, pressure_psi=1.80),
    )
    assert validation["ok"] is False
    assert validation["code"] == "required_refuel_check"


def test_droplet_mode_calibration_does_not_require_manual_refuel_check(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    head = _printer_head(_stock_id_for_design_row(em, "glycerol"), printing_mode="droplet")

    em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        15.0,
        write_keys_if_assigned=False,
        printing_mode="droplet",
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 15.0,
            "pw_us": 1450,
            "pressure_psi": 1.35,
            "run_id": "droplet-run",
            "phase": "pressure_sweep_characterization",
            "timestamp": "2026-03-18T09:02:00Z",
            "source_row_fingerprint": ("droplet-run", "pressure_sweep", "2026-03-18T09:02:00Z", 1450, 1.35, 15.0),
        },
    )

    assert em.get_manual_refuel_check(printer_head=head) is None
    validation = em.validate_manual_refuel_check_for_print(
        printer_head=head,
        machine_model=_machine_model_for_calibration(),
    )
    assert validation["ok"] is True
    assert validation["code"] == "not_required"


def test_manual_refuel_pass_persists_and_revalidates_for_same_stream_calibration(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    head = _printer_head(_stock_id_for_design_row(em, "glycerol"), printing_mode="stream")
    calibration = {
        "printer_head": head,
        "measured_volume_nL": 30.0,
        "pw_us": 1800,
        "pressure_psi": 1.80,
        "run_id": "stream-run",
        "phase": "stream",
        "timestamp": "2026-03-18T10:00:00Z",
        "source_row_fingerprint": ("stream-run", "stream", "2026-03-18T10:00:00Z", 1800, 1.80, 30.0),
    }
    machine = _machine_model_for_calibration(
        pw_us=1800,
        pressure_psi=1.80,
        refuel_pw_us=2400,
        refuel_pressure_psi=0.42,
    )
    em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
        printing_mode="stream",
        applied_calibration=calibration,
    )

    passed = em.record_manual_refuel_check_outcome(
        printer_head=head,
        status="passed",
        source="manual_dialog",
        machine_model=machine,
        trial_droplet_count=20,
        trial_count=2,
        operator_judgment="stable",
    )
    assert passed["status"] == "passed"
    assert passed["print_pulse_width_us"] == 1800
    assert passed["refuel_pulse_width_us"] == 2400

    validation = em.validate_manual_refuel_check_for_print(
        printer_head=head,
        machine_model=machine,
    )
    assert validation["ok"] is True

    em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
        printing_mode="stream",
        applied_calibration=calibration,
    )
    assert em.get_manual_refuel_check(printer_head=head)["status"] == "passed"

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    assert payload["manual_refuel_checks"]["schema_version"] == 1
    reloaded_model = experiment_model_factory()
    reloaded = reloaded_model.experiment_model
    reloaded.load_experiment(em.experiment_file_path, em.experiment_dir_path)
    reloaded_validation = reloaded.validate_manual_refuel_check_for_print(
        printer_head=head,
        machine_model=machine,
    )
    assert reloaded.is_read_only_legacy_execution()
    assert reloaded_validation["ok"] is False
    assert reloaded_validation["code"] == "context_unavailable"


def test_new_stream_calibration_marks_existing_manual_refuel_pass_required(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    head = _printer_head(_stock_id_for_design_row(em, "glycerol"), printing_mode="stream")
    machine = _machine_model_for_calibration(pw_us=1800, pressure_psi=1.80)

    em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
        printing_mode="stream",
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 30.0,
            "pw_us": 1800,
            "pressure_psi": 1.80,
            "run_id": "stream-run-1",
            "phase": "stream",
            "timestamp": "2026-03-18T10:00:00Z",
            "source_row_fingerprint": ("stream-run-1", "stream", "2026-03-18T10:00:00Z", 1800, 1.80, 30.0),
        },
    )
    em.record_manual_refuel_check_outcome(
        printer_head=head,
        status="passed",
        source="manual_dialog",
        machine_model=machine,
    )

    em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
        printing_mode="stream",
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 30.0,
            "pw_us": 1800,
            "pressure_psi": 1.80,
            "run_id": "stream-run-2",
            "phase": "stream",
            "timestamp": "2026-03-18T10:10:00Z",
            "source_row_fingerprint": ("stream-run-2", "stream", "2026-03-18T10:10:00Z", 1800, 1.80, 30.0),
        },
    )

    record = em.get_manual_refuel_check(printer_head=head)
    assert record["status"] == "required"
    assert record["previous_status"] == "passed"


@pytest.mark.parametrize(
    ("machine_kwargs", "expected_code"),
    [
        ({"pw_us": 1801}, "print_pulse_width_mismatch"),
        ({"pressure_psi": 1.90}, "print_pressure_mismatch"),
        ({"refuel_pw_us": 2401}, "refuel_pulse_width_mismatch"),
        ({"refuel_pressure_psi": 0.55}, "refuel_pressure_mismatch"),
    ],
)
def test_manual_refuel_pass_invalidates_when_settings_change(
    experiment_model_factory,
    machine_kwargs,
    expected_code,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    head = _printer_head(_stock_id_for_design_row(em, "glycerol"), printing_mode="stream")
    base_machine = _machine_model_for_calibration(
        pw_us=1800,
        pressure_psi=1.80,
        refuel_pw_us=2400,
        refuel_pressure_psi=0.42,
    )
    em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
        printing_mode="stream",
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 30.0,
            "pw_us": 1800,
            "pressure_psi": 1.80,
            "run_id": "stream-run",
            "phase": "stream",
            "timestamp": "2026-03-18T10:00:00Z",
            "source_row_fingerprint": ("stream-run", "stream", "2026-03-18T10:00:00Z", 1800, 1.80, 30.0),
        },
    )
    em.record_manual_refuel_check_outcome(
        printer_head=head,
        status="passed",
        source="manual_dialog",
        machine_model=base_machine,
    )

    values = {
        "pw_us": 1800,
        "pressure_psi": 1.80,
        "refuel_pw_us": 2400,
        "refuel_pressure_psi": 0.42,
    }
    values.update(machine_kwargs)
    validation = em.validate_manual_refuel_check_for_print(
        printer_head=head,
        machine_model=_machine_model_for_calibration(**values),
    )
    assert validation["ok"] is False
    assert validation["code"] == expected_code


@pytest.mark.parametrize("status", ["deferred", "failed", "unclear", "bypassed"])
def test_manual_refuel_non_passed_outcomes_block_preflight(
    experiment_model_factory,
    status,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    head = _printer_head(_stock_id_for_design_row(em, "glycerol"), printing_mode="stream")
    machine = _machine_model_for_calibration(pw_us=1800, pressure_psi=1.80)
    em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
        printing_mode="stream",
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 30.0,
            "pw_us": 1800,
            "pressure_psi": 1.80,
            "run_id": "stream-run",
            "phase": "stream",
            "timestamp": "2026-03-18T10:00:00Z",
            "source_row_fingerprint": ("stream-run", "stream", "2026-03-18T10:00:00Z", 1800, 1.80, 30.0),
        },
    )

    record = em.record_manual_refuel_check_outcome(
        printer_head=head,
        status=status,
        source="unit_test",
        machine_model=machine,
        bypass_reason="operator_bypass" if status == "bypassed" else None,
    )
    validation = em.validate_manual_refuel_check_for_print(
        printer_head=head,
        machine_model=machine,
    )
    assert record["status"] == status
    assert validation["ok"] is False
    assert validation["code"] == f"{status}_refuel_check"


def test_apply_fill_droplet_volume_persists_effective_and_intended_volume(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)

    result = em.apply_fill_droplet_volume(30.0, write_keys_if_assigned=False)

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    assert payload["metadata"]["fill_droplet_volume_nL"] == 30.0
    assert payload["metadata"]["fill_printing_mode"] == "droplet"
    assert payload["metadata"]["intended_fill_droplet_volume_nL"] == 10.0
    assert result["saved_experiment"] is True
    assert em.unsaved_changes is False


def test_apply_fill_droplet_volume_can_switch_printing_mode(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)

    result = em.apply_fill_droplet_volume(
        30.0,
        write_keys_if_assigned=False,
        printing_mode="stream",
    )

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    assert payload["metadata"]["fill_droplet_volume_nL"] == 30.0
    assert payload["metadata"]["fill_printing_mode"] == "stream"
    assert payload["metadata"]["intended_fill_droplet_volume_nL"] == 10.0
    assert payload["metadata"]["intended_fill_printing_mode"] == "droplet"
    assert result["original_printing_mode"] == "droplet"
    assert result["applied_printing_mode"] == "stream"

    reloaded_model = experiment_model_factory()
    reloaded = reloaded_model.experiment_model
    reloaded.load_experiment(em.experiment_file_path, em.experiment_dir_path)
    assert reloaded.metadata["fill_droplet_volume_nL"] == 30.0
    assert reloaded.metadata["fill_printing_mode"] == "stream"
    assert reloaded.metadata["intended_fill_droplet_volume_nL"] == 10.0
    assert reloaded.metadata["intended_fill_printing_mode"] == "droplet"


def test_reloading_after_calibrated_volume_apply_uses_saved_effective_counts(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    original_target = _first_saved_target(em, "glycerol")
    original_stock_concentration = em.plans_per_option[("glycerol", None)]["stocks"][0]["stock_concentration"]

    em.apply_droplet_volume_for_option("glycerol", None, 15.0, write_keys_if_assigned=False)
    calibrated_target = _first_saved_target(em, "glycerol")
    calibrated_stock_concentration = em.plans_per_option[("glycerol", None)]["stocks"][0]["stock_concentration"]
    assert calibrated_target != original_target
    assert calibrated_stock_concentration == original_stock_concentration

    reloaded_model = experiment_model_factory()
    reloaded = reloaded_model.experiment_model
    reloaded.load_experiment(em.experiment_file_path, em.experiment_dir_path)

    assert reloaded.factors[0].options[0].droplet_nL == 15.0
    assert reloaded.factors[0].options[0].intended_droplet_nL == 10.0
    assert reloaded.factors[0].options[0].forced_stock_conc == calibrated_stock_concentration
    assert _first_saved_target(reloaded, "glycerol") == calibrated_target


def test_applied_imaging_calibration_records_serialize_through_save_and_load(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    head = _printer_head(_stock_id_for_design_row(em, "glycerol"))
    emitted_records = []
    em.applied_imaging_calibration_changed.connect(lambda record: emitted_records.append(dict(record)))

    result = em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        15.0,
        write_keys_if_assigned=False,
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 15.0,
            "pw_us": 1450,
            "pressure_psi": 1.35,
            "run_id": "run-2",
            "phase": "pressure_sweep_characterization",
            "timestamp": "2026-03-18T09:02:00Z",
            "source_row_fingerprint": ("run-2", "pressure_sweep", "2026-03-18T09:02:00Z", 1450, 1.35, 15.0),
        },
    )

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    applied = payload["applied_imaging_calibrations"]
    assert applied["schema_version"] == 1
    record = next(iter(applied["records"].values()))
    assert record["stock_id"] == head.get_stock_id()
    assert record["printer_head_id"] == "head-1"
    assert record["applied_design_volume_nL"] == 15.0
    assert record["measured_volume_nL"] == 15.0
    assert record["pw_us"] == 1450
    assert record["pressure_psi"] == 1.35
    assert result["applied_imaging_calibration_recorded"] is True
    assert len(emitted_records) == 1
    assert emitted_records[0]["stock_id"] == head.get_stock_id()
    assert emitted_records[0]["run_id"] == "run-2"

    reloaded_model = experiment_model_factory()
    reloaded = reloaded_model.experiment_model
    reloaded.load_experiment(em.experiment_file_path, em.experiment_dir_path)

    validation = reloaded.validate_applied_imaging_calibration_for_print(
        printer_head=head,
        machine_model=_machine_model_for_calibration(),
    )
    assert reloaded.is_read_only_legacy_execution()
    assert validation["ok"] is False
    assert validation["code"] == "context_unavailable"
    assert validation["record"] is None


def test_apply_fill_droplet_volume_records_applied_imaging_calibration(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    head = _printer_head(_stock_id_for_design_row(em, "Water"), printer_head_id="fill-head")

    result = em.apply_fill_droplet_volume(
        12.0,
        write_keys_if_assigned=False,
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 12.0,
            "pw_us": 1500,
            "pressure_psi": 1.10,
            "run_id": "fill-run",
            "phase": "pressure_sweep_characterization",
            "timestamp": "2026-03-18T09:05:00Z",
            "source_row_fingerprint": ("fill-run", "pressure_sweep", "2026-03-18T09:05:00Z", 1500, 1.10, 12.0),
        },
    )

    record = em.get_applied_imaging_calibration(printer_head=head)
    assert result["applied_imaging_calibration_recorded"] is True
    assert record["is_fill"] is True
    assert record["factor_name"] == "Water"
    assert record["applied_design_volume_nL"] == 12.0
    assert record["printer_head_id"] == "fill-head"


def test_changing_design_volume_after_apply_invalidates_print_readiness(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    head = _printer_head(_stock_id_for_design_row(em, "glycerol"))
    em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        15.0,
        write_keys_if_assigned=False,
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 15.0,
            "pw_us": 1450,
            "pressure_psi": 1.35,
            "run_id": "run-2",
            "phase": "pressure_sweep_characterization",
            "timestamp": "2026-03-18T09:02:00Z",
            "source_row_fingerprint": ("run-2", "pressure_sweep", "2026-03-18T09:02:00Z", 1450, 1.35, 15.0),
        },
    )

    em.apply_droplet_volume_for_option("glycerol", None, 14.0, write_keys_if_assigned=False)

    validation = em.validate_applied_imaging_calibration_for_print(
        printer_head=head,
        machine_model=_machine_model_for_calibration(),
    )
    assert validation["ok"] is False
    assert "stale" in validation["message"]
