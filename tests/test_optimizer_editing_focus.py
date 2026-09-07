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


def test_typing_pauses_commas_and_tab_do_not_submit(qapp, real_editor):
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
    QTest.qWait(450)
    assert next_input.hasFocus() and not outcomes
    # Leave the input area, allowing one complete automatic calculation.
    editor.run_btn.setFocus()
    wait_for(qapp, lambda: outcomes)
    assert len(outcomes) == 1 and outcomes[0][0], outcomes
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


def test_returning_to_inputs_cancels_debounce(qapp, real_editor):
    editor = real_editor
    target = begin_edit(qapp, editor)
    QTest.keyClicks(target, "0.5, 1")
    editor.run_btn.setFocus()
    assert editor._auto_timer.isActive()
    target.setFocus()
    QTest.qWait(450)
    assert not editor._auto_timer.isActive() and not optimization_job_manager().busy
    assert target.hasFocus()


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
