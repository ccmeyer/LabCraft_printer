"""Operator-order calibration through finalized runtime and durable print intents."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pandas as pd

from AuthoritativeExecutionLoad import inspect_authoritative_execution
from Model import Model
from ExecutionCalibrationStore import load_execution_calibrations
from test_initial_execution_plan_integration import (
    _configure_calibratable_two_stock_execution,
    _configure_choice_two_stock_execution,
)


def _apply(em, stock, volume, *, mode="droplet", **extra):
    return em.apply_droplet_volume_for_option(
        stock.factor_name, stock.option_name, volume, printing_mode=mode,
        applied_calibration={
            "stock_id": stock.stock_id,
            "printer_head": SimpleNamespace(printer_head_id="head-" + stock.stock_id),
            "measured_volume_nL": volume, "run_id": "measurement-" + str(volume),
            **extra,
        },
    )


def _print(em, stock_id, *, partial=False):
    """Simulate command completion using the same intent/progress path as printing."""
    for well in em._runtime_well_plate.get_all_wells():
        reaction = well.get_assigned_reaction()
        if reaction is None:
            continue
        reagent = reaction.get_all_reagents().get(stock_id)
        if reagent is None:
            continue
        remaining = reagent.target_droplets - reagent.added_droplets
        if remaining <= 0:
            continue
        count = 1 if partial else remaining
        intent = em.begin_execution_print_intent(
            well_id=well.well_id, stock_id=stock_id,
            commanded_droplets=count, printer_head_id="head-" + stock_id,
        )
        reagent.added_droplets += count
        reagent.completed = reagent.is_complete()
        em.create_progress_file(execution_intent_id=intent)
        em.complete_execution_print_intent(intent)
        if partial:
            break


def _counts(plan, stock_id):
    return {w.well_id: next((d.target_dispenses for d in w.dispenses
                            if d.stock_id == stock_id), 0) for w in plan.wells}


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("reload", [False, True])
def test_calibrate_print_calibrate_print(experiment_model_factory, reverse, partial, reload):
    model = experiment_model_factory()
    em = _configure_calibratable_two_stock_execution(model)
    stocks = sorted((s for s in em.get_execution_plan_snapshot().stocks
                     if s.factor_name == "Signal"), key=lambda s: s.concentration,
                    reverse=reverse)
    first, second = stocks
    em.ensure_execution_resume_checkpoint()
    _apply(em, first, 12.0)
    _print(em, first.stock_id, partial=partial)
    if reload:
        model, em = _reload(experiment_model_factory, em)
    before = em.get_execution_plan_snapshot()
    progress = copy.deepcopy(em.return_progress_data())
    assert em.get_calibration_application_eligibility(stock_id=second.stock_id)["ok"]
    preview = em.preview_requantized_for_option(
        ("Signal", None), 11.0, calibrated_stock_id=second.stock_id,
        printing_mode="droplet",
    )
    assert preview["ok"], preview
    result = _apply(em, second, 11.0, execution_context=preview["execution_context"])
    after = em.get_execution_plan_snapshot()
    assert result["requantization_mode"] == "constrained"
    _assert_reporting(model, preview, second)
    assert _counts(after, first.stock_id) == _counts(before, first.stock_id)
    assert next(s for s in after.stocks if s.stock_id == first.stock_id) == next(
        s for s in before.stocks if s.stock_id == first.stock_id)
    for well_id, row in em._well_entries_from_progress_payload(progress).items():
        for sid, details in row["reagents"].items():
            assert em.progress_data[well_id]["reagents"].get(sid, {}).get(
                "added_droplets", 0) == details["added_droplets"]
    _print(em, first.stock_id)
    _print(em, second.stock_id)
    if reload:
        model, em = _reload(experiment_model_factory, em)
    bundle = inspect_authoritative_execution(
        em.experiment_dir_path, json.loads(Path(em.experiment_file_path).read_text()))
    assert bundle.valid, bundle.issues
    for well in after.wells:
        for sid in (first.stock_id, second.stock_id):
            details = em.progress_data[well.well_id]["reagents"].get(sid)
            if details:
                assert details["added_droplets"] == details["target_droplets"]


def _reload(factory, em):
    model = factory()
    loaded = model.experiment_model
    bundle = loaded.load_experiment(em.experiment_file_path, em.experiment_dir_path)
    assert bundle.valid, bundle.issues
    model.load_authoritative_execution_runtime()
    return model, loaded


def _assert_reporting(model, preview, selected):
    em = model.experiment_model
    plan = em.get_execution_plan_snapshot()
    lookup = {s.stock_id: s for s in plan.stocks}
    reactions = {f"R{i+1}": spec["reaction"]
                 for i, spec in enumerate(em._iter_reaction_run_specs())}
    key = (selected.factor_name, selected.option_name)
    preview_rows = {r["target_final"]: r for r in preview["rows"]}
    csv = pd.read_csv(em.concentration_key_file_path, index_col=0)
    records = load_execution_calibrations(em.execution_calibrations_file_path)
    for stock in plan.stocks:
        if stock.calibration_record_key:
            record = records.records[stock.calibration_record_key]
            assert record.stock_id == stock.stock_id
            assert record.effective_volume_nL == stock.effective_volume_nL
    for well in plan.wells:
        expected_volume = sum(d.target_dispenses * lookup[d.stock_id].effective_volume_nL
                              for d in well.dispenses)
        assert well.expected_printed_volume_nL == pytest.approx(expected_volume)
        if key not in reactions[well.reaction_id]:
            continue
        row = preview_rows[reactions[well.reaction_id][key]]
        counts = {d.stock_id: d.target_dispenses for d in well.dispenses}
        assert tuple(counts.get(sid, 0) for sid in preview["stock_ids"]) == row["drops"]
        achieved = row["starting"] + sum(
            counts.get(sid, 0) * lookup[sid].effective_volume_nL * lookup[sid].concentration
            / plan.volume_basis.final_reaction_volume_nL for sid in preview["stock_ids"])
        assert row["achieved_final"] == pytest.approx(achieved)
        assert row["error"] == pytest.approx(achieved - row["target_final"])
        projected = expected_volume + max(0, plan.volume_basis.final_reaction_volume_nL
                                         - plan.volume_basis.target_printed_volume_nL)
        actual = achieved * plan.volume_basis.final_reaction_volume_nL / projected
        per_well = next(r for r in preview['per_well_rows'] if r['well_id'] == well.well_id)
        assert per_well['achieved_final'] == pytest.approx(actual)
        assert per_well['error'] == pytest.approx(actual - row['target_final'])
        assert csv.loc[well.well_id, f"{selected.reagent_name}_{selected.units}"] == pytest.approx(actual)
        for sid in preview["stock_ids"]:
            assert model.get_well_stock_final_concentration(well.well_id, sid) == pytest.approx(
                counts.get(sid, 0) * lookup[sid].effective_volume_nL * lookup[sid].concentration
                / projected)
        volume_row = next(r for r in preview["volume_rows"] if r["well_id"] == well.well_id)
        assert volume_row["total_volume_nL"] == pytest.approx(expected_volume)


@pytest.mark.parametrize("fill_progress", ["unprinted", "partial", "complete"])
@pytest.mark.parametrize("choice", [False, True])
def test_fill_choice_replicates_and_additional_conditions(experiment_model_factory, fill_progress, choice):
    model = experiment_model_factory()
    if choice:
        em = _configure_choice_two_stock_execution(model, replicates=2)
        option = "Signal A"
    else:
        em = _configure_calibratable_two_stock_execution(model, base_replicates=2,
            include_other=True,
            additional_conditions=[{"label": "Extra low", "replicates": 2,
                                    "targets": {("Signal", None): 0.3}}])
        option = None
    stocks = [s for s in em.get_execution_plan_snapshot().stocks
              if s.factor_name == "Signal" and s.option_name == option]
    first, second = stocks
    em.ensure_execution_resume_checkpoint()
    _apply(em, first, 12.0)
    _print(em, first.stock_id, partial=True)
    fill = next(s for s in em.get_execution_plan_snapshot().stocks if s.units == "--")
    if fill_progress != "unprinted":
        _print(em, fill.stock_id, partial=fill_progress == "partial")
    before = em.get_execution_plan_snapshot()
    progress = copy.deepcopy(em.return_progress_data())
    preview = em.preview_requantized_for_option(("Signal", option), 40.0,
        calibrated_stock_id=second.stock_id, printing_mode="droplet")
    assert preview["ok"], preview
    _apply(em, second, 40.0)
    after = em.get_execution_plan_snapshot()
    _assert_reporting(model, preview, second)
    for old, new in zip(before.wells, after.wells):
        old_counts = {d.stock_id: d.target_dispenses for d in old.dispenses}
        new_counts = {d.stock_id: d.target_dispenses for d in new.dispenses}
        for sid in old_counts:
            if sid not in (second.stock_id, fill.stock_id) or progress[old.well_id]["reagents"][sid]["added_droplets"]:
                assert new_counts.get(sid, 0) == old_counts[sid]
    _reload(experiment_model_factory, em)


def test_pending_or_unsaved_runtime_progress_blocks_calibration(experiment_model_factory):
    em = _configure_calibratable_two_stock_execution(experiment_model_factory())
    em.ensure_execution_resume_checkpoint()
    first, second = [s for s in em.get_execution_plan_snapshot().stocks if s.factor_name == "Signal"]
    _apply(em, first, 12.0)
    well = next(w for w in em._runtime_well_plate.get_all_wells()
                if w.get_assigned_reaction() and first.stock_id in w.get_assigned_reaction().get_all_reagents()
                and w.get_assigned_reaction().get_all_reagents()[first.stock_id].target_droplets > 0)
    em.begin_execution_print_intent(well_id=well.well_id, stock_id=first.stock_id,
        commanded_droplets=1, printer_head_id="head-" + first.stock_id)
    before = _files(em)
    with pytest.raises(RuntimeError, match="pending print commands"):
        _apply(em, second, 11.0)
    assert _files(em) == before
    well.get_assigned_reaction().get_all_reagents()[first.stock_id].added_droplets = 1
    with pytest.raises(RuntimeError, match="differs from the durable checkpoint"):
        _apply(em, second, 11.0)
    assert _files(em) == before


def test_fixed_overshoot_and_zero_additional_drops_are_valid(experiment_model_factory):
    em = _configure_calibratable_two_stock_execution(experiment_model_factory())
    em.ensure_execution_resume_checkpoint()
    low, high = sorted((s for s in em.get_execution_plan_snapshot().stocks if s.factor_name == "Signal"),
                       key=lambda s: s.concentration)
    _apply(em, low, 12.0)
    _print(em, low.stock_id)
    preview = em.preview_requantized_for_option(("Signal", None), 40.0,
        calibrated_stock_id=high.stock_id, printing_mode="droplet")
    assert preview["ok"]
    row = next(r for r in preview["rows"] if r["target_final"] == 1.0)
    assert row["achieved_final"] > row["target_final"]
    assert row["drops"][preview["calibrated_stock_index"]] == 0
    before = _counts(em.get_execution_plan_snapshot(), low.stock_id)
    _apply(em, high, 40.0)
    assert _counts(em.get_execution_plan_snapshot(), low.stock_id) == before
    _reload(experiment_model_factory, em)


def test_grouped_targets_and_repeated_calibration(experiment_model_factory):
    em = _configure_choice_two_stock_execution(experiment_model_factory())
    em.ensure_execution_resume_checkpoint()
    low, high = sorted((s for s in em.get_execution_plan_snapshot().stocks if s.option_name == "Signal A"),
                       key=lambda s: s.concentration)
    # Both valid large measurements make the smallest targets round to zero.
    _apply(em, high, 40.0)
    preview = em.preview_requantized_for_option(("Signal", "Signal A"), 140.0,
        calibrated_stock_id=low.stock_id, printing_mode="stream")
    assert preview["ok"]
    assert preview["new_distinct_level_loss"] > preview["old_distinct_level_loss"]
    _apply(em, low, 140.0, mode="stream")
    # Recalibration remains supported until this selected stock starts printing.
    _apply(em, low, 139.0, mode="stream")
    _reload(experiment_model_factory, em)


@pytest.mark.parametrize("volume", [0.0, -1.0, 0.5, 251.0, float("nan"), float("inf")])
def test_invalid_measurements_preserve_state(experiment_model_factory, volume):
    em = _configure_calibratable_two_stock_execution(experiment_model_factory())
    em.ensure_execution_resume_checkpoint()
    first = next(s for s in em.get_execution_plan_snapshot().stocks if s.factor_name == "Signal")
    _apply(em, first, 12.0)
    before = _files(em)
    preview = em.preview_requantized_for_option(("Signal", None), volume,
        calibrated_stock_id=first.stock_id, printing_mode="droplet")
    assert not preview["ok"]
    with pytest.raises((RuntimeError, ValueError)):
        _apply(em, first, volume)
    assert _files(em) == before


@pytest.mark.parametrize("boundary", ["_calibrated_two_stock_target_counts", "_advance_authoritative_calibration_bundle",
                                       "_guard_authoritative_calibration_files"])
def test_progress_during_calculation_is_not_overwritten(experiment_model_factory, monkeypatch, boundary):
    em = _configure_calibratable_two_stock_execution(experiment_model_factory())
    em.ensure_execution_resume_checkpoint()
    first, second = [s for s in em.get_execution_plan_snapshot().stocks if s.factor_name == "Signal"]
    _apply(em, first, 12.0)
    original = getattr(em, boundary)
    after_progress = {}
    def advance(*args, **kwargs):
        result = original(*args, **kwargs)
        _print(em, first.stock_id, partial=True)
        after_progress.update(_files(em))
        return result
    monkeypatch.setattr(em, boundary, advance)
    with pytest.raises(RuntimeError, match="changed after calibration preview|after it dispensed"):
        _apply(em, second, 11.0)
    assert _files(em) == after_progress


@pytest.mark.parametrize("fixed", [None, 0, 1])
def test_nearest_pair_matches_exhaustive_integer_search(fixed):
    from Model import ExperimentModel
    for deltas in [(1.0, 3.0), (0.5, 2.0), (7.0, 1.0)]:
        for target in [0, 0.1, 0.5, 1, 2, 5.5, 12.5]:
            current, volumes = (2, 1), (12, 10)
            pair, _ = ExperimentModel._nearest_execution_pair(target, deltas, volumes, current, fixed)
            candidates = [(a, b) for a in range(30) for b in range(30)
                          if fixed is None or (a, b)[fixed] == current[fixed]]
            def rank(p):
                return (abs(sum(p[i] * deltas[i] for i in range(2)) - target),
                        sum(p[i] * volumes[i] for i in range(2)),
                        sum(abs(p[i] - current[i]) for i in range(2)), p)
            assert pair == min(candidates, key=rank)


@pytest.mark.parametrize("stale", [False, True])
def test_real_dialog_preview_apply_uses_execution_progress(
    experiment_model_factory, monkeypatch, qapp, tmp_path, stale,
):
    from test_droplet_imaging_summary_table import _build_dialog, _make_run, _select_visible_row
    from CalibrationClasses.View import DropletImagingDialog
    from PySide6 import QtWidgets
    em = _configure_calibratable_two_stock_execution(experiment_model_factory())
    em.ensure_execution_resume_checkpoint()
    first, second = [s for s in em.get_execution_plan_snapshot().stocks if s.factor_name == "Signal"]
    _apply(em, first, 12.0)
    _print(em, first.stock_id, partial=True)
    runs = [_make_run("execution-result", stock=second.stock_id, sweep_entries=[{
        "timestamp": "2026-09-08T09:00:00Z", "pw_us": 1400, "pressure_psi": 0.8,
        "mean_nL": 11.0, "cv_pct": 4.0, "valid": True,
    }])]
    messages = []
    for method in ("information", "warning", "critical"):
        monkeypatch.setattr(QtWidgets.QMessageBox, method, lambda *args, **kw: messages.append(args[2]))
    # Printing-settings hardware calls are outside this test's authority. All
    # eligibility, numerical, record, execution and publication paths stay real.
    monkeypatch.setattr(DropletImagingDialog, "_apply_print_settings_for_applied_calibration",
                        lambda *a, **kw: {"ok": True})
    dialog, manager = _build_dialog(monkeypatch, qapp, tmp_path, runs,
        current_stock=second.stock_id, active_run_id="execution-result", experiment_model=em)
    head = dialog.model.rack_model.get_gripper_printer_head()
    head.get_reagent_name = lambda: "Signal"
    head.printer_head_id = "head-" + second.stock_id
    try:
        _select_visible_row(dialog, 0)
        dialog._refresh_bridge_preview_from_selection()
        assert dialog.bridge_apply_btn.isEnabled()
        assert dialog._bridge_preview_payload["execution_context"]
        if stale:
            _print(em, first.stock_id, partial=True)
        before = em.get_execution_plan_snapshot()
        files = _files(em)
        dialog._apply_previewed_droplet_volume()
        if stale:
            assert em.get_execution_plan_snapshot() == before
            assert _files(em) == files
            assert "changed after calibration preview" in dialog.bridge_status_label.text()
            assert dialog.bridge_apply_btn.isEnabled()
            assert dialog._bridge_preview_payload["execution_context"] == em._calibration_execution_context()
        else:
            assert em.get_execution_plan_snapshot().plan_revision == before.plan_revision + 1
            assert any("kept its committed counts and progress" in message for message in messages)
    finally:
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("role", ["selected", "companion", "fill"])
def test_progress_after_preview_rejects_without_changes(experiment_model_factory, role):
    em = _configure_calibratable_two_stock_execution(experiment_model_factory())
    em.ensure_execution_resume_checkpoint()
    first, second = [s for s in em.get_execution_plan_snapshot().stocks if s.factor_name == "Signal"]
    _apply(em, first, 12.0)
    preview = em.preview_requantized_for_option(("Signal", None), 11.0,
        calibrated_stock_id=second.stock_id, printing_mode="droplet")
    sid = {"selected": second.stock_id, "companion": first.stock_id,
           "fill": next(s.stock_id for s in em.get_execution_plan_snapshot().stocks if s.units == "--")}[role]
    _print(em, sid, partial=True)
    before = _files(em)
    with pytest.raises(RuntimeError, match="changed after calibration preview"):
        _apply(em, second, 11.0, execution_context=preview["execution_context"])
    assert _files(em) == before
    if role == "selected":
        with pytest.raises(RuntimeError, match="already dispensed"):
            _apply(em, second, 11.0)
        assert _files(em) == before


def _files(em):
    return {str(p.relative_to(em.experiment_dir_path)): p.read_bytes()
            for p in Path(em.experiment_dir_path).rglob("*") if p.is_file()}


@pytest.mark.parametrize("boundary", [
    "_advance_authoritative_calibration_bundle", "_write_authoritative_calibration_document",
    "_persist_authoritative_calibration_immutable_revision", "_write_authoritative_calibration_current_plan",
    "_write_authoritative_calibration_progress", "_write_authoritative_calibration_resume",
    "_write_execution_plan_exports", "_install_authoritative_calibration_bundle",
    "_project_reconstructed_execution_plan", "_apply_plan_targets_to_runtime",
])
def test_constrained_publication_rolls_back(experiment_model_factory, monkeypatch, boundary):
    em = _configure_calibratable_two_stock_execution(experiment_model_factory())
    em.ensure_execution_resume_checkpoint()
    first, second = [s for s in em.get_execution_plan_snapshot().stocks if s.factor_name == "Signal"]
    _apply(em, first, 12.0)
    _print(em, first.stock_id, partial=True)
    before_files = _files(em)
    before_plan = em.get_execution_plan_snapshot()
    before_progress = copy.deepcopy(em.progress_data)
    before_runtime = em._build_progress_payload_from_runtime()
    original = getattr(em, boundary)
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("injected publication failure")
    monkeypatch.setattr(em, boundary, fail)
    with pytest.raises(RuntimeError, match="injected publication failure"):
        _apply(em, second, 11.0)
    assert _files(em) == before_files
    assert em.get_execution_plan_snapshot() == before_plan
    assert em.progress_data == before_progress
    assert em._build_progress_payload_from_runtime() == before_runtime
    monkeypatch.setattr(em, boundary, original)
    _apply(em, second, 11.0)
    _reload(experiment_model_factory, em)
