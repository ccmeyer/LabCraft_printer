"""User-paced typing and focus behavior with the real asynchronous dispatcher."""
import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QLineEdit, QProgressDialog, QVBoxLayout

from Model import ExperimentModel
from OptimizationJobs import optimization_job_manager
from tests.test_optimization_jobs import real_editor, wait_for


def begin_edit(qapp, editor):
    editor.show()
    editor.activateWindow()
    target = editor._reagent_cell_widget(0, editor.COL_TARGETS)
    target.setFocus()
    wait_for(qapp, target.hasFocus)
    editor.auto_update_chk.setChecked(True)
    editor._auto_timer.stop()
    target.selectAll()
    return target


def test_typing_pauses_defer_but_tab_commits_without_losing_focus(qapp, real_editor):
    editor = real_editor
    target = begin_edit(qapp, editor)
    outcomes = []
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    original_targets = list(editor.model.factors[0].options[0].targets)
    for text in ("0.5", ",", " 1, 5, 20"):
        QTest.keyClicks(target, text)
        QTest.qWait(450)
        assert target.hasFocus() and target.isEnabled()
        assert not optimization_job_manager().busy and not outcomes
        assert editor.model.factors[0].options[0].targets == original_targets
    assert target.text() == "0.5, 1, 5, 20"
    assert editor._design_optimization_dirty and editor._draft_is_dirty()
    QTest.keyClick(target, Qt.Key_Tab)
    next_input = qapp.focusWidget()
    assert isinstance(next_input, QLineEdit) and next_input is not target
    wait_for(qapp, lambda: outcomes)
    assert len(outcomes) == 1 and outcomes[0][0], outcomes
    assert next_input.hasFocus() and next_input.isEnabled()
    assert editor.model.factors[0].options[0].targets == [0.5, 1, 5, 20]


@pytest.mark.parametrize("action", ["explicit", "background"])
def test_commit_from_button_or_background(qapp, real_editor, action):
    editor = real_editor
    target = begin_edit(qapp, editor)
    QTest.keyClicks(target, "0.5, 1, 5, 20")
    outcomes = []
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    if action == "explicit":
        QTest.mouseClick(editor.run_btn, Qt.LeftButton)
    else:
        QTest.mouseClick(editor.stock_table_status_lbl, Qt.LeftButton)
    wait_for(qapp, lambda: outcomes)
    assert len(outcomes) == 1 and outcomes[0][0], outcomes
    QTest.qWait(450)
    assert len(outcomes) == 1 and not optimization_job_manager().busy


def test_incomplete_edit_is_not_published_and_invalid_commit_stays_dirty(qapp, real_editor):
    editor = real_editor
    target = begin_edit(qapp, editor)
    QTest.keyClicks(target, "0.5, 1e")
    QTest.qWait(450)
    assert target.hasFocus() and not optimization_job_manager().busy
    QTest.keyClicks(target, "1")
    fixed = editor._reagent_cell_widget(0, editor.COL_SET_STOCK)
    fixed.setFocus()
    QTest.keyClicks(fixed, "invalid")
    editor.run_btn.setFocus()
    QTest.qWait(450)
    assert not optimization_job_manager().busy
    assert not editor.model.plans_per_option
    assert editor._design_optimization_dirty
    assert "invalid" in editor.status_lbl.text().lower()


def test_typing_in_next_input_cancels_debounce(qapp, real_editor):
    editor = real_editor
    target = begin_edit(qapp, editor)
    QTest.keyClicks(target, "0.5, 1")
    editor.run_btn.setFocus()
    assert editor._auto_timer.isActive()
    target.setFocus()
    QTest.keyClicks(target, ", 5")
    QTest.qWait(450)
    assert not editor._auto_timer.isActive() and not optimization_job_manager().busy
    assert target.hasFocus()


def test_progress_footer_never_changes_editor_geometry(qapp, real_editor):
    editor = real_editor
    editor.show()
    qapp.processEvents()
    footer = editor._optimization_progress
    before = (editor.size(), editor.reagent_table.geometry(), footer.geometry())
    outcomes = []
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    editor._run_design_optimization_flow()
    qapp.processEvents()
    assert (editor.size(), editor.reagent_table.geometry(), footer.geometry()) == before
    wait_for(qapp, lambda: outcomes)
    assert (editor.size(), editor.reagent_table.geometry(), footer.geometry()) == before
    assert footer.isVisible() and not footer.cancel_button.isEnabled()


def test_import_footer_is_reserved_before_calculation(qapp, real_editor):
    import pandas as pd
    from View import ExperimentImportWizard
    wizard = ExperimentImportWizard(real_editor.model, parent=real_editor,
                                    printed_volume_nL=240, final_volume_nL=5000, allow_two=True)
    wizard.load_design_dataframe(pd.DataFrame({"R mM": [0.5, 1, 5, 20]}))
    wizard.show()
    qapp.processEvents()
    footer = wizard._optimization_progress
    before = (wizard.size(), footer.geometry(), wizard.calculate_btn.geometry())
    outcomes = []
    wizard.optimization_finished.connect(lambda *args: outcomes.append(args))
    wizard._recompute_report()
    qapp.processEvents()
    assert (wizard.size(), footer.geometry(), wizard.calculate_btn.geometry()) == before
    wait_for(qapp, lambda: outcomes)
    assert outcomes[0][0], outcomes
    assert (wizard.size(), footer.geometry(), wizard.calculate_btn.geometry()) == before
    wizard.close()


def test_invalid_target_token_does_not_publish_partial_list(qapp, real_editor):
    editor = real_editor
    target = begin_edit(qapp, editor)
    QTest.keyClicks(target, "0.5, 1e")
    QTest.keyClick(target, Qt.Key_Tab)
    QTest.qWait(450)
    assert not editor.model.plans_per_option and editor._design_optimization_dirty
    assert "complete, nonnegative target" in editor.status_lbl.text()
    assert not optimization_job_manager().busy


def test_discard_close_consumes_deferred_update(qapp, real_editor):
    editor = real_editor
    target = begin_edit(qapp, editor)
    QTest.keyClicks(target, "0.5, 1")
    editor.run_btn.setFocus()
    assert editor._auto_timer.isActive()
    editor.reject()  # Fixture permits discard without an unsaved-changes prompt.
    QTest.qWait(450)
    assert not editor.isVisible() and not editor._auto_timer.isActive()
    assert not optimization_job_manager().busy


@pytest.mark.parametrize("failure", [False, True])
def test_save_action_from_input_waits_for_publication(qapp, real_editor, monkeypatch, failure):
    editor = real_editor
    target = begin_edit(qapp, editor)
    QTest.keyClicks(target, "0.5, 1, 5, 20")
    saved, outcomes = [], []
    def save(on_saved):
        assert not editor._design_optimization_dirty
        assert not editor.model._reactions_df.empty
        saved.append(True)
        if failure:
            raise RuntimeError("injected save failure")
        return True
    monkeypatch.setattr(editor, "_save_computed_design", save)
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    QTest.mouseClick(editor.save_btn, Qt.LeftButton)
    assert not saved
    wait_for(qapp, lambda: outcomes)
    QTest.qWait(450)
    assert saved == [True] and len(outcomes) == 1
    assert outcomes[0][0] is (not failure)
    assert not editor._auto_timer.isActive() and not optimization_job_manager().busy
    if failure:
        assert editor._draft_is_dirty()


def test_child_dialog_and_hidden_editor_do_not_commit_inputs(qapp, real_editor):
    editor = real_editor
    target = begin_edit(qapp, editor)
    QTest.keyClicks(target, "0.5, 1")
    other = QDialog(editor)
    other.setModal(True)
    layout = QVBoxLayout(other)
    other_edit = QLineEdit(other)
    layout.addWidget(other_edit)
    other.show()
    other.activateWindow()
    other_edit.setFocus()
    QTest.qWait(450)
    assert not optimization_job_manager().busy
    other.close()
    editor.activateWindow()
    target.setFocus()
    QTest.qWait(450)
    assert target.hasFocus() and not optimization_job_manager().busy
    editor.hide()
    QTest.qWait(450)
    assert not optimization_job_manager().busy


def test_spinbox_editing_and_auto_off_keep_inputs_pending(qapp, real_editor):
    editor = real_editor
    begin_edit(qapp, editor)
    spin = editor.final_v_spin
    spin.setFocus()
    spin.selectAll()
    QTest.keyClicks(spin, "5000")
    QTest.qWait(450)
    assert spin.hasFocus() and not optimization_job_manager().busy
    editor.auto_update_chk.setChecked(False)
    editor.run_btn.setFocus()
    QTest.qWait(450)
    assert editor._design_optimization_dirty and not optimization_job_manager().busy


def test_inline_progress_cancel_does_not_restart_or_run_continuation(qapp, real_editor, monkeypatch):
    editor = real_editor
    target = begin_edit(qapp, editor)
    QTest.keyClicks(target, "0.5, 1, 5, 20")
    entered, release = threading.Event(), threading.Event()
    def optimize(draft, **kwargs):
        entered.set()
        assert release.wait(10)
        draft._optimization_control.check()
        return {"best": False}
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", optimize)
    outcomes, continued = [], []
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    editor._run_design_optimization_flow(on_complete=lambda: continued.append(True))
    try:
        wait_for(qapp, entered.is_set)
        ui = editor._optimization_ui
        assert ui.progress.isVisible() and not ui.progress.isWindow()
        assert not any(w.isVisible() for w in editor.findChildren(QProgressDialog))
        assert qapp.activeWindow() is editor
        assert not target.isEnabled()
        QTest.mouseClick(ui.progress.cancel_button, Qt.LeftButton)
        assert ui.progress.label.text() == "Canceling…"
        release.set()
        wait_for(qapp, lambda: outcomes)
        QTest.qWait(450)
        assert len(outcomes) == 1 and not outcomes[0][0] and not continued
        assert editor._design_optimization_dirty and target.isEnabled()
        assert not editor._auto_timer.isActive() and not optimization_job_manager().busy
    finally:
        release.set()


@pytest.mark.parametrize("commit_while_busy", [False, True])
def test_auto_edit_supersedes_and_only_latest_committed_fields_publish(
    qapp, real_editor, monkeypatch, commit_while_busy,
):
    editor = real_editor
    target = begin_edit(qapp, editor)
    entered, release = threading.Event(), threading.Event()
    original = ExperimentModel.optimize_stock_solutions
    calls, outcomes = [], []
    def optimize(draft, **kwargs):
        calls.append(draft.factors[0].options[0].units)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
        return original(draft, **kwargs)
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", optimize)
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    QTest.keyClicks(target, "0.5, 1, 5, 20")
    QTest.keyClick(target, Qt.Key_Tab)
    units = qapp.focusWidget()
    try:
        wait_for(qapp, entered.is_set)
        assert units.hasFocus() and units.isEnabled()
        assert not editor.save_btn.isEnabled() and not editor.finish_btn.isEnabled()
        units.selectAll()
        QTest.keyClicks(units, "uM")
        assert editor._optimization_ui.superseded
        if commit_while_busy:
            QTest.keyClick(units, Qt.Key_Tab)
            QTest.qWait(450)
            assert len(calls) == 1
        release.set()
        wait_for(qapp, lambda: outcomes)
        assert not outcomes[0][0] and outcomes[0][1]["status"] == "superseded"
        if not commit_while_busy:
            QTest.qWait(450)
            assert len(calls) == 1 and not editor.model.plans_per_option
            assert units.hasFocus()
            QTest.keyClick(units, Qt.Key_Tab)
        wait_for(qapp, lambda: len(outcomes) == 2)
        assert outcomes[1][0], outcomes
        assert calls == ["mM", "uM"]
        assert editor.model.factors[0].options[0].units == "uM"
        assert not editor._design_optimization_dirty
    finally:
        release.set()


@pytest.mark.parametrize("action", ["cancel", "close", "auto_off"])
def test_superseded_pending_work_can_be_abandoned(qapp, real_editor, monkeypatch, action):
    editor = real_editor
    target = begin_edit(qapp, editor)
    entered, release = threading.Event(), threading.Event()
    calls, outcomes = [], []
    def optimize(draft, **kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(10)
        draft._optimization_control.check()
        return {"best": False}
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", optimize)
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    QTest.keyClicks(target, "0.5, 1, 5, 20")
    QTest.keyClick(target, Qt.Key_Tab)
    try:
        wait_for(qapp, entered.is_set)
        units = qapp.focusWidget()
        QTest.keyClicks(units, "changed")
        QTest.keyClick(units, Qt.Key_Tab)
        if action == "cancel":
            QTest.mouseClick(editor._optimization_progress.cancel_button, Qt.LeftButton)
        elif action == "close":
            editor.close()
        else:
            editor.auto_update_chk.setChecked(False)
        release.set()
        wait_for(qapp, lambda: outcomes and not optimization_job_manager().busy)
        QTest.qWait(450)
        assert calls == [True] and len(outcomes) == 1 and not outcomes[0][0]
        assert editor._design_optimization_dirty
        assert not editor._auto_timer.isActive()
    finally:
        release.set()


@pytest.mark.parametrize("change", ["raw_text", "revision"])
def test_last_moment_editor_change_rejected_before_publication(qapp, real_editor, monkeypatch, change):
    import View
    editor = real_editor
    target = begin_edit(qapp, editor)
    QTest.keyClicks(target, "0.5, 1, 5, 20")
    original = View._AsyncOptimizationUi.finish
    def finish(ui, outcome):
        if change == "raw_text":
            target.setText("0.5, 2")  # No textEdited signal.
        else:
            editor._mark_design_optimization_dirty()
        original(ui, outcome)
    monkeypatch.setattr(View._AsyncOptimizationUi, "finish", finish)
    outcomes = []
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    editor._run_design_optimization_flow(automatic=True)
    wait_for(qapp, lambda: outcomes)
    assert not outcomes[0][0] and "editor inputs changed" in outcomes[0][1]["reason"].lower()
    assert not editor.model.plans_per_option and editor._design_optimization_dirty


def test_superseded_auto_preserves_committed_outputs_history_and_files(qapp, real_editor, monkeypatch, tmp_path):
    import copy
    from tools.optimizer_realistic_qualification import assert_outputs_equal
    editor = real_editor
    editor.model.factors[0].options[0].targets = [0.5, 1, 5, 20]
    editor._load_factors_into_table()
    outcomes = []
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    editor._run_design_optimization_flow()
    wait_for(qapp, lambda: outcomes)
    assert outcomes.pop()[0]
    previous = editor.model.capture_optimization_outputs()
    history = copy.deepcopy(editor.model.applied_imaging_calibrations)
    saved = tmp_path / "experiment_design.json"
    saved.write_bytes(b"previous saved design")
    editor.model.experiment_file_path = str(saved)
    target = begin_edit(qapp, editor)
    entered, release = threading.Event(), threading.Event()
    def optimize(draft, **kwargs):
        entered.set()
        assert release.wait(10)
        draft._optimization_control.check()
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", optimize)
    notifications = []
    editor.model.stock_updated.connect(lambda: notifications.append(True))
    QTest.keyClicks(target, "0.5, 1, 5, 21")
    QTest.keyClick(target, Qt.Key_Tab)
    try:
        wait_for(qapp, entered.is_set)
        QTest.keyClicks(qapp.focusWidget(), "changed")
        release.set()
        wait_for(qapp, lambda: outcomes)
        assert not outcomes[0][0]
        assert_outputs_equal(previous, editor.model.capture_optimization_outputs())
        assert editor.model.applied_imaging_calibrations == history
        assert saved.read_bytes() == b"previous saved design" and not notifications
    finally:
        release.set()


def test_count_only_auto_retains_allocation_shortcut(qapp, real_editor, monkeypatch):
    editor = real_editor
    editor.model.factors[0].options[0].targets = [0.5, 1, 5, 20]
    editor._load_factors_into_table()
    outcomes = []
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    editor._run_design_optimization_flow()
    wait_for(qapp, lambda: outcomes)
    assert outcomes.pop()[0]
    def unexpected(*args, **kwargs):
        raise AssertionError("Count-only update reran the optimizer")
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", unexpected)
    editor.show()
    editor.activateWindow()
    editor.rep_spin.setFocus()
    editor.auto_update_chk.setChecked(True)
    editor.rep_spin.setValue(2)
    QTest.keyClick(editor.rep_spin, Qt.Key_Tab)
    wait_for(qapp, lambda: outcomes)
    assert outcomes[0][0] and outcomes[0][1]["stock_allocation_reused"]
    assert len(editor.model._reactions_df) == 8
