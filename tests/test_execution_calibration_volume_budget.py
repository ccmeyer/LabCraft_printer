"""Regression from the attended 200 nL, four-stock calibration experiment."""
import json
import copy
import itertools
from pathlib import Path

import pytest
import pandas as pd

from ExecutionPlan import load_execution_plan
from ExecutionProgressStore import encode_execution_progress_v2
from test_execution_two_stock_workflow import _apply, _reload, _print, _counts, _files
from test_execution_fill_workflow import _apply_fill


MEASURED_VOLUME = 9.572595895181557


def _captured_execution(factory):
    fixture = json.loads((Path(__file__).parent / 'fixtures/calibration/four_stock_volume_regression.json').read_text())
    model = factory()
    em = model.experiment_model
    root = Path(em.experiment_dir_path)
    (root / 'experiment_design.json').write_text(json.dumps(fixture['design']))
    (root / 'execution_plan.json').write_text(json.dumps(fixture['plan']))
    revisions = root / 'execution_plan_revisions'
    revisions.mkdir()
    (revisions / 'revision_000001.json').write_text(json.dumps(fixture['plan']))
    plan = load_execution_plan(root / 'execution_plan.json')
    progress = {w.well_id: {'reaction_id': w.reaction_id, 'completed': False, 'reagents': {
        d.stock_id: {'target_droplets': d.target_dispenses, 'added_droplets': 0}
        for d in w.dispenses}} for w in plan.wells}
    (root / 'progress.json').write_text(json.dumps(encode_execution_progress_v2(plan, progress)))
    loaded = em.load_experiment(str(root / 'experiment_design.json'), str(root))
    assert loaded.valid, loaded.issues
    model.load_authoritative_execution_runtime()
    return model, em


def test_attended_four_stock_calibration_respects_volume(experiment_model_factory):
    model, em = _captured_execution(experiment_model_factory)
    before = em.get_execution_plan_snapshot()
    stock = next(s for s in before.stocks if s.stock_id == 'reagent-1_1111.11_mM')
    preview = em.preview_requantized_for_option(('reagent-1', None), MEASURED_VOLUME,
        calibrated_stock_id=stock.stock_id, printing_mode='droplet')
    assert preview['ok'], preview
    assert max(r['total_volume_nL'] for r in preview['volume_rows']) <= 250.0
    target100 = next(r for r in preview['rows'] if r['target_final'] == 100)
    assert target100['drops'] == (2, 0)
    _apply(em, stock, MEASURED_VOLUME, execution_context=preview['execution_context'])
    after = em.get_execution_plan_snapshot()
    assert max(w.expected_printed_volume_nL for w in after.wells) <= 250.0
    for old, new in zip(before.wells, after.wells):
        assert {d.stock_id: d.target_dispenses for d in old.dispenses if d.stock_id.startswith('reagent-2')} == {
            d.stock_id: d.target_dispenses for d in new.dispenses if d.stock_id.startswith('reagent-2')}
    actual_rows = {r['well_id']: r for r in preview['per_well_rows']}
    csv = pd.read_csv(em.concentration_key_file_path, index_col=0)
    stocks = {s.stock_id: s for s in after.stocks}
    for well in after.wells:
        amount = sum(d.target_dispenses * stocks[d.stock_id].effective_volume_nL
                     * stocks[d.stock_id].concentration for d in well.dispenses
                     if stocks[d.stock_id].factor_name == 'reagent-1')
        actual = amount / well.expected_printed_volume_nL
        row = actual_rows[well.well_id]
        assert row['achieved_final'] == pytest.approx(actual)
        assert row['error'] == pytest.approx(actual - row['target_final'])
        assert csv.loc[well.well_id, 'reagent-1_mM'] == pytest.approx(actual)
        assert sum(model.get_well_stock_final_concentration(well.well_id, sid)
                   for sid in stocks if sid.startswith('reagent-1')) == pytest.approx(actual)
    _, restored = _reload(experiment_model_factory, em)
    assert restored.get_execution_plan_snapshot() == after


@pytest.mark.parametrize('fixed', [None, 0, 1])
@pytest.mark.parametrize('budget', [-10, 0, 10, 25, 75])
def test_bounded_search_matches_exhaustive_feasible_counts(fixed, budget):
    from Model import ExperimentModel
    for target in [0, 0.1, 1, 10, 100]:
        deltas, volumes, current = (53.1810883065642, 1.25), (MEASURED_VOLUME, 9), (2, 1)
        pair, _ = ExperimentModel._nearest_execution_pair(target, deltas, volumes, current,
                                                         fixed, volume_limit=budget)
        floor_volume = current[fixed] * volumes[fixed] if fixed is not None else 0
        allowance = max(budget, floor_volume)
        candidates = [(a, b) for a in range(12) for b in range(12)
                      if (fixed is None or (a, b)[fixed] == current[fixed])
                      and a*volumes[0]+b*volumes[1] <= allowance + 1e-9]
        def rank(p):
            return (abs(sum(p[i]*deltas[i] for i in range(2))-target),
                    sum(p[i]*volumes[i] for i in range(2)),
                    sum(abs(p[i]-current[i]) for i in range(2)), p)
        assert pair == min(candidates, key=rank)


@pytest.mark.parametrize('order', list(itertools.permutations(['high', 'low', 'fill'])))
@pytest.mark.parametrize('partial', [False, True])
def test_four_stock_order_fill_and_resume(experiment_model_factory, order, partial):
    _, em = _captured_execution(experiment_model_factory)
    em.ensure_execution_resume_checkpoint()
    ids = {'high': 'reagent-1_1111.11_mM', 'low': 'reagent-1_27.78_mM', 'fill': 'Water_1.00_--'}
    volumes = {'high': MEASURED_VOLUME, 'low': 8.6, 'fill': 9.2}
    printed = set()
    for role in order:
        before = em.get_execution_plan_snapshot()
        progress = copy.deepcopy(em.progress_data)
        stock = next(s for s in before.stocks if s.stock_id == ids[role])
        if role == 'fill':
            _apply_fill(em, volumes[role])
        else:
            preview = em.preview_requantized_for_option(('reagent-1', None), volumes[role],
                calibrated_stock_id=stock.stock_id, printing_mode='droplet')
            assert preview['ok'], preview
            _apply(em, stock, volumes[role], execution_context=preview['execution_context'])
        after = em.get_execution_plan_snapshot()
        assert max(w.expected_printed_volume_nL for w in after.wells) <= 250 + 1e-9
        for sid in printed - {ids['fill']}:
            assert _counts(before, sid) == _counts(after, sid)
        for old, new in zip(before.wells, after.wells):
            if progress[old.well_id]['reagents'].get(ids['fill'], {}).get('added_droplets', 0):
                assert _counts(before, ids['fill'])[old.well_id] == _counts(after, ids['fill'])[new.well_id]
        _print(em, stock.stock_id, partial=partial)
        printed.add(stock.stock_id)
        _, em = _reload(experiment_model_factory, em)
    # Calibrating the second reagent must reserve the first reagent's entire
    # committed contribution and any already-started fill allocation.
    for sid in ['reagent-2_444.44_mM', 'reagent-2_22.22_mM']:
        before = em.get_execution_plan_snapshot()
        stock = next(s for s in before.stocks if s.stock_id == sid)
        _apply(em, stock, 9.8)
        after = em.get_execution_plan_snapshot()
        for fixed in printed - {ids['fill']}:
            assert _counts(before, fixed) == _counts(after, fixed)
        _print(em, sid, partial=partial)
        if partial or sid != 'reagent-2_22.22_mM':
            _, em = _reload(experiment_model_factory, em)
        else:
            # Completed executions reopen for inspection, not another print.
            loaded = experiment_model_factory().experiment_model.load_experiment(
                em.experiment_file_path, em.experiment_dir_path)
            assert loaded.valid, loaded.issues


@pytest.mark.parametrize('boundary', ['_apply_plan_targets_to_runtime', '_write_authoritative_calibration_current_plan'])
def test_four_stock_publication_failure_rolls_back(experiment_model_factory, monkeypatch, boundary):
    _, em = _captured_execution(experiment_model_factory)
    em.ensure_execution_resume_checkpoint()
    stock = next(s for s in em.get_execution_plan_snapshot().stocks if s.stock_id == 'reagent-1_1111.11_mM')
    _apply(em, stock, 9.0)
    before = em.get_execution_plan_snapshot()
    files = _files(em)
    stock = next(s for s in before.stocks if s.stock_id == 'reagent-1_1111.11_mM')
    original = getattr(em, boundary)
    calls = 0
    def fail_once(*args, **kw):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError('injected publication failure')
        return original(*args, **kw)
    monkeypatch.setattr(em, boundary, fail_once)
    with pytest.raises(RuntimeError, match='injected'):
        _apply(em, stock, MEASURED_VOLUME)
    assert em.get_execution_plan_snapshot() == before
    assert _files(em) == files


@pytest.mark.parametrize('stale,upgrade', [(False, False), (True, False), (False, True)])
def test_attended_case_real_dialog_preview_and_apply(experiment_model_factory, monkeypatch, qapp, tmp_path, stale, upgrade):
    import Model as module
    from test_droplet_imaging_summary_table import _build_dialog, _make_run, _select_visible_row
    from CalibrationClasses.View import DropletImagingDialog
    from PySide6 import QtWidgets
    _, em = _captured_execution(experiment_model_factory)
    em.ensure_execution_resume_checkpoint()
    sid = 'reagent-1_1111.11_mM'
    runs = [_make_run('volume-budget', stock=sid, sweep_entries=[{
        'timestamp': '2026-09-08T18:10:10Z', 'pw_us': 1300, 'pressure_psi': 0.578,
        'mean_nL': MEASURED_VOLUME, 'cv_pct': 4.0, 'valid': True}])]
    for method in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QtWidgets.QMessageBox, method, lambda *a, **kw: None)
    # Only hardware print-setting dispatch is excluded. UI worker/selection,
    # preview, eligibility, persistence and execution revision guards are real.
    monkeypatch.setattr(DropletImagingDialog, '_apply_print_settings_for_applied_calibration',
                        lambda *a, **kw: {'ok': True})
    dialog, _ = _build_dialog(monkeypatch, qapp, tmp_path, runs,
        current_stock=sid, active_run_id='volume-budget', experiment_model=em)
    head = dialog.model.rack_model.get_gripper_printer_head()
    head.get_reagent_name = lambda: 'reagent-1'
    head.printer_head_id = 'head-' + sid
    try:
        _select_visible_row(dialog, 0)
        dialog._refresh_bridge_preview_from_selection()
        assert dialog.bridge_apply_btn.isEnabled()
        assert dialog.bridge_table.rowCount() == 98
        assert 'projected final volume' in dialog.bridge_table.item(1, 1).toolTip()
        if upgrade:
            solver = module.ExperimentModel._nearest_execution_pair
            with monkeypatch.context() as legacy:
                legacy.setattr(module, 'EXECUTION_CALIBRATION_ALLOCATION_POLICY', None)
                legacy.setattr(module.ExperimentModel, '_nearest_execution_pair', staticmethod(
                    lambda target, deltas, volumes, current, fixed_index=None, **kw:
                        solver(target, deltas, volumes, current, fixed_index)))
                dialog._refresh_bridge_preview_from_selection()
                dialog._apply_previewed_droplet_volume()
            assert max(w.expected_printed_volume_nL for w in em.get_execution_plan_snapshot().wells) > 800
            dialog._refresh_bridge_preview_from_selection()
            assert dialog.bridge_apply_btn.isEnabled()
        if stale:
            _print(em, 'reagent-1_27.78_mM', partial=True)
        before = em.get_execution_plan_snapshot()
        files = _files(em)
        dialog._apply_previewed_droplet_volume()
        if stale:
            assert em.get_execution_plan_snapshot() == before
            assert _files(em) == files
            assert 'changed after calibration preview' in dialog.bridge_status_label.text()
        else:
            assert em.get_execution_plan_snapshot().plan_revision > before.plan_revision
            assert max(w.expected_printed_volume_nL for w in em.get_execution_plan_snapshot().wells) <= 250
            dialog._refresh_bridge_preview_from_selection()
            assert not dialog.bridge_apply_btn.isEnabled()
    finally:
        dialog.reject()


def test_projected_reporting_accounts_for_starting_amount_and_empty_wells(experiment_model_factory):
    from dataclasses import replace
    model, em = _captured_execution(experiment_model_factory)
    plan = em.get_execution_plan_snapshot()
    # Reporting is a pure calculation on the supplied plan, with explicit
    # nonprinted liquid and background amount; no history is rewritten.
    em.factors[0].options[0].starting_conc = 2.0
    with_background = replace(plan, volume_basis=replace(plan.volume_basis, final_reaction_volume_nL=1000.0))
    row = em._execution_concentration_details(with_background)['A2']
    assert row['projected_final_volume_nL'] == pytest.approx(998.0)
    assert row['concentrations']['reagent-1_mM'] == pytest.approx((20000 + 2*1000)/998)
    empty = replace(plan, wells=tuple(replace(w, dispenses=(), expected_printed_volume_nL=0) for w in plan.wells))
    detail = em._execution_concentration_details(empty)['A2']
    assert detail['concentration_defined'] is False
    assert pd.isna(em._execution_concentration_dataframe(empty).loc['A2', 'reagent-1_mM'])


def test_reapply_legacy_result_repairs_allocation_without_rewriting_history(experiment_model_factory, monkeypatch):
    import Model as module
    from ExecutionCalibrationStore import load_execution_calibrations
    _, em = _captured_execution(experiment_model_factory)
    stock = next(s for s in em.get_execution_plan_snapshot().stocks if s.stock_id == 'reagent-1_1111.11_mM')
    solver = module.ExperimentModel._nearest_execution_pair
    # Seed the pre-fix numerical policy through actual Apply and persistence.
    # No identity, revision, progress, publication or storage guard is stubbed.
    with monkeypatch.context() as legacy:
        legacy.setattr(module, 'EXECUTION_CALIBRATION_ALLOCATION_POLICY', None)
        legacy.setattr(module.ExperimentModel, '_nearest_execution_pair', staticmethod(
            lambda target, deltas, volumes, current, fixed_index=None, **kw:
                solver(target, deltas, volumes, current, fixed_index)))
        _apply(em, stock, MEASURED_VOLUME)
    old = em.get_execution_plan_snapshot()
    assert max(w.expected_printed_volume_nL for w in old.wells) == pytest.approx(873)
    old_records = load_execution_calibrations(em.execution_calibrations_file_path).records
    revisions = {p.name: p.read_bytes() for p in Path(em.execution_plan_revisions_dir_path).glob('*.json')}
    _apply(em, stock, MEASURED_VOLUME)
    corrected = em.get_execution_plan_snapshot()
    assert corrected.plan_revision == old.plan_revision + 1
    assert max(w.expected_printed_volume_nL for w in corrected.wells) <= 250
    new_records = load_execution_calibrations(em.execution_calibrations_file_path).records
    assert all(new_records[key] == record for key, record in old_records.items())
    assert all((Path(em.execution_plan_revisions_dir_path)/name).read_bytes() == data for name, data in revisions.items())
    assert len(new_records) == len(old_records) + 1
    _apply(em, stock, MEASURED_VOLUME)
    assert em.get_execution_plan_snapshot() == corrected
    _, restored = _reload(experiment_model_factory, em)
    assert restored.get_execution_plan_snapshot() == corrected
