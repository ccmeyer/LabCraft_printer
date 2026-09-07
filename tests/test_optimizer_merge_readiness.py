"""Bounded checks for the import contract, feasibility and warning visibility."""
from fractions import Fraction
import hashlib

import pandas as pd
import pytest

from Model import ExperimentModel, printing_mode_default_ejection_volume_nl
from tests.optimizer_qualification_cases import Case, Reagent, load_case
from tests.test_optimization_jobs import real_editor, wait_for
from tools.optimizer_realistic_qualification import new_editor, new_wizard, close_owner


def minimum_single_stock_volumes(case, droplet_nl):
    """Independent lower bound under positive-count nearest-drop quantization.

    The smallest positive target must round to at least one drop, so the
    concentration delivered by a drop cannot exceed twice that target. Using
    this largest possible step gives a lower bound for every other target.
    These fixtures use zero starting concentration and levels for which the
    limiting tie cannot reduce any count. Fractions avoid floating-point ties.
    """
    minimum = {r.name: min(Fraction(str(t)) for t in r.targets if t > 0)
               for r in case.reagents}
    volumes = []
    for row in case.compositions():
        counts = [max(1, int(Fraction(str(t)) / (2 * minimum[name]) + Fraction(1, 2)))
                  if t > 0 else 0 for name, t in row.items()]
        volumes.append(sum(counts) * droplet_nl)
    return volumes


@pytest.mark.parametrize("column", ["droplet_volume_nL", "droplet_nL", "Ejection Volume nL"])
@pytest.mark.parametrize("mode", ["Droplet", "Stream"])
def test_unsupported_csv_volume_is_explicit_and_preserves_mode_default(column, mode):
    frame = pd.DataFrame([dict(reagent="Signal", stock_conc=1000, print_mode=mode,
                               **{column: 10})])
    parsed = ExperimentModel()._parse_import_max_stock_dataframe(frame)
    assert parsed["stocks"][0]["droplet_nL"] == printing_mode_default_ejection_volume_nl(mode)
    warnings = [i for i in parsed["issues"] if i["code"] == "unsupported_ejection_volume_column"]
    assert len(warnings) == 1 and warnings[0]["severity"] == "warning"
    assert column in warnings[0]["message"] and "recalculate" in warnings[0]["message"]


def test_empty_optional_volume_column_does_not_warn():
    parsed = ExperimentModel()._parse_import_max_stock_dataframe(pd.DataFrame([
        dict(reagent="Signal", stock_conc=1000, droplet_volume_nL=None)]))
    assert not parsed["issues"]


def test_legacy_fixtures_require_exact_external_bytes(tmp_path, monkeypatch):
    from tests import optimizer_qualification_cases as catalog
    data = b"reagent,stock_conc\nSignal,1000\n"
    monkeypatch.setitem(catalog.MANIFEST, "additional_files", {"sample.csv": hashlib.sha256(data).hexdigest()})
    path = tmp_path / "sample.csv"
    path.write_bytes(data)
    assert catalog.read_legacy_optimizer_csv("sample.csv", tmp_path).iloc[0].stock_conc == 1000
    path.write_bytes(b"modified recipe")
    with pytest.raises(ValueError, match="hash mismatch"):
        catalog.read_legacy_optimizer_csv("sample.csv", tmp_path)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        catalog.read_legacy_optimizer_csv("sample.csv", tmp_path)
    with pytest.raises(ValueError, match="Unknown optimizer fixture"):
        catalog.read_legacy_optimizer_csv("../sample.csv", tmp_path)
    with pytest.raises(ValueError, match="outside every Git worktree"):
        catalog.read_legacy_optimizer_csv("sample.csv", catalog.ROOT)


def test_wizard_shows_effective_volume_and_preserves_it_through_apply(qapp, real_editor):
    case = load_case("groups_import")
    wizard = new_wizard(case, True)
    editor = new_editor(case, True)
    try:
        outcomes = []
        wizard.optimization_finished.connect(lambda *args: outcomes.append(args))
        wizard._recompute_report()
        wait_for(qapp, lambda: outcomes)
        assert outcomes[0][0] and wizard.report["ok"]
        assert any(i["code"] == "unsupported_ejection_volume_column" for i in wizard.report["issues"])
        assert "not imported" in wizard.status_lbl.text()
        assert all(float(wizard.stock_table.item(i, 3).text()) == 9
                   for i in range(wizard.stock_table.rowCount()))
        assert wizard.apply_btn.isEnabled()
        original_report = wizard.report
        wizard.report = {**original_report, "issues": [*original_report["issues"],
                         {"severity": "error", "message": "Selected allocation exceeds the volume budget."}]}
        wizard._update_status()
        assert wizard.status_lbl.text().index("exceeds the volume") < wizard.status_lbl.text().index("not imported")
        wizard.report = original_report
        applied = []
        editor.optimization_finished.connect(lambda *args: applied.append(args))
        editor._apply_uploaded_design_payload(wizard.get_apply_payload())
        wait_for(qapp, lambda: applied)
        assert applied[0][0]
        assert all(o.droplet_nL == 9 for f in editor.model.factors for o in f.options)
        assert all(editor._reagent_cell_widget(i, editor.COL_DROPLET).value() == 9
                   for i in range(editor._reagent_row_count()))
    finally:
        close_owner(qapp, wizard)
        close_owner(qapp, editor)


def test_dense_single_stock_failure_has_independent_volume_lower_bound():
    case = load_case("dense_384_10")
    lower = minimum_single_stock_volumes(case, 9)
    worst = max(range(len(lower)), key=lower.__getitem__)
    assert case.design.Well.iloc[worst] == "M22"
    assert lower[worst] == 1251 > case.printed
    assert max(minimum_single_stock_volumes(case, 10)) == 1390 > case.printed
    report = ExperimentModel().build_import_feasibility_report(
        case.design, max_stock_df=case.stock_frame, printed_volume_nL=case.printed,
        printed_volume_tolerance_nL=0, final_volume_nL=case.final, allow_two=False)
    assert not report["ok"] and report["stock_allocation_reuse_payload"] is None
    failure = next(i for i in report["issues"] if i["code"] == "selected_plan_volume_budget_exceeded")
    assert failure["required_volume_nL"] >= lower[worst]
    assert failure["allowed_volume_nL"] == 1000


def test_concrete_limiting_single_stock_counts_attain_lower_bound():
    case = load_case("dense_384_10")
    lower = minimum_single_stock_volumes(case, 9)
    # Just below the largest step that keeps the smallest positive target
    # nonzero. This witness fits the stock bounds but cannot fit the budget.
    concentrations = {r.name: 2 * min(r.targets) * case.final / 9 * (1 - 1e-8)
                      for r in case.reagents}
    assert all(concentrations[r.name] <= r.maximum for r in case.reagents)
    actual = []
    model = ExperimentModel()
    for row in case.compositions():
        evaluations = [model._evaluate_single_forced_target(
            t_final=t, starting_conc=0, forced_stock_conc=concentrations[name],
            droplet_nL=9, final_volume_nL=case.final, units="mM") for name, t in row.items()]
        assert all(e["reachable"] and e["droplets"] > 0 for e in evaluations)
        actual.append(sum(e["droplets"] * 9 for e in evaluations))
    assert actual == lower


def test_grouped_target_warning_and_achieved_preview_survive_draft_save(qapp, real_editor, tmp_path):
    case = Case("ApproximationCheck", [Reagent("Signal", (.5, .55), fixed=250)], printed=240)
    editor = new_editor(case, False)
    try:
        outcomes = []
        editor.optimization_finished.connect(lambda *args: outcomes.append(args))
        editor._run_design_optimization_flow()
        wait_for(qapp, lambda: outcomes)
        assert outcomes[0][0]
        target = editor._reagent_cell_widget(0, editor.COL_TARGETS)
        tooltip = target.toolTip()
        assert "0.55" in tooltip and "0.5" in tooltip and "collapsed" in tooltip.lower()
        assert "group" in editor.status_lbl.text().lower()
        before = editor.model.get_target_preview_map()
        editor.model.experiments_root = str(tmp_path)
        saved = []
        editor._on_save_design(on_saved=lambda: saved.append(True))
        wait_for(qapp, lambda: saved)
        loaded = ExperimentModel()
        loaded.load_experiment(editor.model.experiment_file_path, editor.model.experiment_dir_path)
        assert loaded.get_target_preview_map() == before
        assert target.toolTip() == tooltip
    finally:
        close_owner(qapp, editor)
