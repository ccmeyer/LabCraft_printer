"""Fill allocations remain executable when later reagent measurements arrive."""
import copy
import itertools
from types import SimpleNamespace

import pandas as pd
import pytest

from ExecutionCalibrationStore import load_execution_calibrations
from Model import Model
from test_execution_two_stock_workflow import _apply, _counts, _files, _print, _reload
from test_initial_execution_plan_integration import _configure_calibratable_two_stock_execution


def _configure(model):
    em = model.experiment_model
    em.factors = []
    em.set_metadata(
        name="fill-order-calibration", randomize_assignments=False,
        start_row=0, start_col=0, replicates=2,
        target_reaction_volume_nL=100.0, final_reaction_volume_nL=1000.0,
        printed_volume_tolerance_nL=0.0, fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    em.add_additive("Signal", [0.4, 0.5], "mM", 10.0, forced_stock_conc=10.0)
    em.add_additive("Other", [0.1], "mM", 10.0, forced_stock_conc=10.0)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()
    Model.load_experiment_from_model(model, load_progress=False, finalize_execution_plan=True)
    em.ensure_execution_resume_checkpoint()
    return em


def _stock(em, name):
    return next(s for s in em.get_execution_plan_snapshot().stocks if s.factor_name == name)


def _apply_fill(em, volume, **extra):
    stock = _stock(em, "Water")
    return em.apply_fill_droplet_volume(volume, printing_mode="droplet", applied_calibration={
        "stock_id": stock.stock_id,
        "printer_head": SimpleNamespace(printer_head_id="head-" + stock.stock_id),
        "measured_volume_nL": volume, "run_id": "fill-" + str(volume), **extra,
    })


@pytest.mark.parametrize("volume", [25.0, 30.0])
@pytest.mark.parametrize("partial", [False, True])
def test_single_stock_preserves_started_fill_per_well(experiment_model_factory, volume, partial):
    em = _configure(experiment_model_factory())
    _apply_fill(em, 10.0)
    fill = _stock(em, "Water")
    _print(em, fill.stock_id, partial=partial)
    model, em = _reload(experiment_model_factory, em)
    before = em.get_execution_plan_snapshot()
    progress = copy.deepcopy(em.progress_data)
    selected = _stock(em, "Signal")
    preview = em.preview_requantized_for_option(("Signal", None), volume)
    assert preview["ok"], preview
    result = _apply(em, selected, volume, execution_context=preview["execution_context"])
    after = em.get_execution_plan_snapshot()
    assert result["volume_warning"] == preview["volume_warning"]
    assert preview["target_counts_by_well"] == {
        w.well_id: {d.stock_id: d.target_dispenses for d in w.dispenses} for w in after.wells
    }
    rows = {row["target_final"]: row for row in preview["rows"]}
    targets = {f"R{i+1}": spec["reaction"][("Signal", None)]
               for i, spec in enumerate(em._iter_reaction_run_specs())}
    csv = pd.read_csv(em.concentration_key_file_path, index_col=0)
    volumes = {s.stock_id: s.effective_volume_nL for s in after.stocks}
    for well in after.wells:
        counts = {d.stock_id: d.target_dispenses for d in well.dispenses}
        old_fill = _counts(before, fill.stock_id)[well.well_id]
        added = progress[well.well_id]["reagents"][fill.stock_id]["added_droplets"]
        nonfill = sum(n * volumes[sid] for sid, n in counts.items() if sid != fill.stock_id)
        expected_fill = old_fill if added else max(0, round((100.0 - nonfill) / 10.0))
        assert counts[fill.stock_id] == expected_fill
        assert em.progress_data[well.well_id]["reagents"][fill.stock_id]["added_droplets"] == added
        assert well.expected_printed_volume_nL == pytest.approx(nonfill + expected_fill * 10.0)
        achieved = counts[selected.stock_id] * volume * selected.concentration / 1000.0
        row = rows[targets[well.reaction_id]]
        assert row["achieved_final"] == pytest.approx(achieved)
        assert row["error"] == pytest.approx(achieved - targets[well.reaction_id])
        projected = well.expected_printed_volume_nL + 900.0
        actual = counts[selected.stock_id] * volume * selected.concentration / projected
        per_well = next(r for r in preview['per_well_rows'] if r['well_id'] == well.well_id)
        assert per_well['achieved_final'] == pytest.approx(actual)
        assert csv.loc[well.well_id, "Signal_mM"] == pytest.approx(actual)
        assert model.get_well_stock_final_concentration(well.well_id, selected.stock_id) == pytest.approx(actual)
    assert _counts(after, _stock(em, "Other").stock_id) == _counts(before, _stock(em, "Other").stock_id)
    _print(em, selected.stock_id)
    _print(em, fill.stock_id)
    _reload(experiment_model_factory, em)


@pytest.mark.parametrize("two_stock", [False, True])
@pytest.mark.parametrize("order", list(itertools.permutations(["A", "B", "fill"])))
def test_all_calibrate_print_orders_resume(experiment_model_factory, two_stock, order):
    em = (_configure_calibratable_two_stock_execution(experiment_model_factory())
          if two_stock else _configure(experiment_model_factory()))
    em.ensure_execution_resume_checkpoint()
    stocks = [s for s in em.get_execution_plan_snapshot().stocks if s.units != "--"]
    roles = {"A": stocks[0].stock_id, "B": stocks[1].stock_id,
             "fill": _stock(em, "Water").stock_id}
    printed = set()
    for role in order:
        before = em.get_execution_plan_snapshot()
        stock = next(s for s in before.stocks if s.stock_id == roles[role])
        if role == "fill":
            preview = em.preview_fill_requantized(11.0)
            assert preview["ok"], preview
            _apply_fill(em, 11.0, execution_context=preview["execution_context"])
        else:
            volume = 12.0 if two_stock else 25.0
            preview = em.preview_requantized_for_option(
                (stock.factor_name, stock.option_name), volume, calibrated_stock_id=stock.stock_id)
            assert preview["ok"], preview
            _apply(em, stock, volume, execution_context=preview["execution_context"])
        after = em.get_execution_plan_snapshot()
        for sid in printed:
            assert _counts(after, sid) == _counts(before, sid)
            assert next(s for s in after.stocks if s.stock_id == sid) == next(
                s for s in before.stocks if s.stock_id == sid)
        records = load_execution_calibrations(em.execution_calibrations_file_path)
        updated = next(s for s in after.stocks if s.stock_id == stock.stock_id)
        assert records.records[updated.calibration_record_key].stock_id == stock.stock_id
        _print(em, stock.stock_id)
        printed.add(stock.stock_id)
        if len(printed) < 3:
            _, em = _reload(experiment_model_factory, em)
        else:
            loaded = experiment_model_factory().experiment_model
            bundle = loaded.load_experiment(em.experiment_file_path, em.experiment_dir_path)
            assert bundle.valid, bundle.issues
            assert not bundle.eligibility.can_activate_runtime
            assert bundle.eligibility.reason == "No droplets remain."
    for row in em.progress_data.values():
        for details in row["reagents"].values():
            assert details["added_droplets"] == details["target_droplets"]


@pytest.mark.parametrize("selected_fill", [False, True])
@pytest.mark.parametrize("progress_on_selected", [False, True])
def test_stale_preview_refresh_and_selected_progress_guard(
    experiment_model_factory, selected_fill, progress_on_selected,
):
    em = _configure(experiment_model_factory())
    selected = _stock(em, "Water" if selected_fill else "Signal")
    def preview():
        return (em.preview_fill_requantized(11.0) if selected_fill
                else em.preview_requantized_for_option(("Signal", None), 25.0))
    def apply(context):
        return (_apply_fill(em, 11.0, execution_context=context) if selected_fill
                else _apply(em, selected, 25.0, execution_context=context))
    original = preview()
    sid = selected.stock_id if progress_on_selected else _stock(em, "Other").stock_id
    _print(em, sid, partial=True)
    files = _files(em)
    with pytest.raises(RuntimeError, match="changed after calibration preview"):
        apply(original["execution_context"])
    assert _files(em) == files
    if progress_on_selected:
        with pytest.raises(RuntimeError, match="already dispensed"):
            apply(None)
        assert _files(em) == files
    else:
        apply(preview()["execution_context"])


def test_repeated_measurements_keep_fill_and_allow_zero_reagent_drops(experiment_model_factory):
    em = _configure(experiment_model_factory())
    fill = _stock(em, "Water")
    _apply_fill(em, 12.0)
    _apply_fill(em, 11.0)
    _print(em, fill.stock_id, partial=True)
    before = em.get_execution_plan_snapshot()
    first_well = next(wid for wid, row in em.progress_data.items()
                      if row["reagents"][fill.stock_id]["added_droplets"] > 0)
    for volume in [25.0, 30.0, 250.0]:
        _apply(em, _stock(em, "Signal"), volume)
        assert _counts(em.get_execution_plan_snapshot(), fill.stock_id)[first_well] == _counts(before, fill.stock_id)[first_well]
    assert not any(_counts(em.get_execution_plan_snapshot(), _stock(em, "Signal").stock_id).values())
    _print(em, fill.stock_id)
    _reload(experiment_model_factory, em)


@pytest.mark.parametrize("boundary", ["_advance_authoritative_calibration_bundle",
                                      "_write_execution_plan_exports", "_apply_plan_targets_to_runtime"])
def test_single_stock_failure_recovery_preserves_fill(experiment_model_factory, monkeypatch, boundary):
    em = _configure(experiment_model_factory())
    _apply(em, _stock(em, "Signal"), 10.0)
    fill = _stock(em, "Water")
    _print(em, fill.stock_id, partial=True)
    _, em = _reload(experiment_model_factory, em)
    before = em.get_execution_plan_snapshot()
    progress = copy.deepcopy(em.progress_data)
    original = getattr(em, boundary)
    before_files = _files(em)
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("injected fill workflow failure")
    monkeypatch.setattr(em, boundary, fail)
    with pytest.raises(RuntimeError, match="injected fill workflow failure"):
        _apply(em, _stock(em, "Signal"), 25.0)
    if boundary == "_advance_authoritative_calibration_bundle":
        assert _files(em) == before_files
        assert em.get_execution_plan_snapshot() == before
        assert em.progress_data == progress
        assert em.get_execution_plan_sync_error() is None
    monkeypatch.setattr(em, boundary, original)
    _apply(em, _stock(em, "Signal"), 25.0)
    _, em = _reload(experiment_model_factory, em)
    for wid, row in progress.items():
        if row["reagents"][fill.stock_id]["added_droplets"]:
            assert _counts(em.get_execution_plan_snapshot(), fill.stock_id)[wid] == _counts(before, fill.stock_id)[wid]
        assert em.progress_data[wid]["reagents"][fill.stock_id]["added_droplets"] == row["reagents"][fill.stock_id]["added_droplets"]


@pytest.mark.parametrize("boundary", ["_calibrated_target_counts", "_advance_authoritative_calibration_bundle",
                                      "_guard_authoritative_calibration_files"])
def test_fill_progress_during_apply_retained_without_calibration_writes(experiment_model_factory, monkeypatch, boundary):
    em = _configure(experiment_model_factory())
    _apply(em, _stock(em, "Signal"), 10.0)
    _, em = _reload(experiment_model_factory, em)
    original = getattr(em, boundary)
    after_progress = {}
    def advance(*args, **kwargs):
        result = original(*args, **kwargs)
        _print(em, _stock(em, "Water").stock_id, partial=True)
        after_progress.update(_files(em))
        return result
    monkeypatch.setattr(em, boundary, advance)
    with pytest.raises(RuntimeError, match="changed after calibration preview|allocation already underway"):
        _apply(em, _stock(em, "Signal"), 25.0)
    assert _files(em) == after_progress
    monkeypatch.setattr(em, boundary, original)
    _apply(em, _stock(em, "Signal"), 25.0)


@pytest.mark.parametrize("selected_fill", [False, True])
@pytest.mark.parametrize("stale", [False, True])
def test_dialog_single_and_fill_preview_context(
    experiment_model_factory, monkeypatch, qapp, tmp_path, selected_fill, stale,
):
    from test_droplet_imaging_summary_table import _build_dialog, _make_run, _select_visible_row
    from CalibrationClasses.View import DropletImagingDialog
    from PySide6 import QtWidgets
    em = _configure(experiment_model_factory())
    selected = _stock(em, "Water" if selected_fill else "Signal")
    if not selected_fill:
        _print(em, _stock(em, "Water").stock_id, partial=True)
    volume = 11.0 if selected_fill else 25.0
    runs = [_make_run("fill-workflow", stock=selected.stock_id, sweep_entries=[{
        "timestamp": "2026-09-08T09:00:00Z", "pw_us": 1400, "pressure_psi": 0.8,
        "mean_nL": volume, "cv_pct": 4.0, "valid": True,
    }])]
    messages = []
    for method in ("information", "warning", "critical"):
        monkeypatch.setattr(QtWidgets.QMessageBox, method, lambda *a, **kw: messages.append(a[2]))
    # Only physical settings calls are excluded; eligibility through persistence stays real.
    monkeypatch.setattr(DropletImagingDialog, "_apply_print_settings_for_applied_calibration",
                        lambda *a, **kw: {"ok": True})
    dialog, _ = _build_dialog(monkeypatch, qapp, tmp_path, runs,
        current_stock=selected.stock_id, active_run_id="fill-workflow", experiment_model=em)
    head = dialog.model.rack_model.get_gripper_printer_head()
    head.get_reagent_name = lambda: selected.factor_name
    head.printer_head_id = "head-" + selected.stock_id
    try:
        _select_visible_row(dialog, 0)
        dialog._refresh_bridge_preview_from_selection()
        assert dialog.bridge_apply_btn.isEnabled()
        assert dialog._bridge_preview_payload["execution_context"]
        if stale:
            _print(em, _stock(em, "Other").stock_id, partial=True)
        before, files = em.get_execution_plan_snapshot(), _files(em)
        dialog._apply_previewed_droplet_volume()
        if stale:
            assert em.get_execution_plan_snapshot() == before
            assert _files(em) == files
            assert "changed after calibration preview" in dialog.bridge_status_label.text()
            assert dialog.bridge_apply_btn.isEnabled()
            assert dialog._bridge_preview_payload["execution_context"] == em._calibration_execution_context()
        else:
            assert _stock(em, selected.factor_name).effective_volume_nL == volume
            assert em.get_execution_plan_snapshot().plan_revision > before.plan_revision
    finally:
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()
