"""Deterministic progress/slow-update behavior; timing gates live in the benchmark."""
import threading

import pytest
from shiboken6 import isValid
from PySide6.QtCore import QThread

from Model import ExperimentModel
from OptimizationJobs import ComputationControl, OptimizationCancelled, optimization_job_manager
from tests.test_optimization_jobs import real_editor, wait_for, manager, request_for
from tests.test_stock_optimizer_performance import _dense_target_model


def test_slow_threshold_is_one_shot_and_only_inside_optimizer():
    now, notices = [0.0], []
    control = ComputationControl(clock=lambda: now[0])
    control.slow_callback = lambda: notices.append(now[0])
    now[0] = 10
    control.check()
    assert not notices
    control.begin_optimizer()
    now[0] = 12.999
    control.check()
    assert not notices
    now[0] = 13
    control.check()
    control.end_optimizer()
    now[0] = 100
    control.check()
    assert notices == [13]


def test_slow_final_work_is_checked_on_exit():
    now, notices = [0.0], []
    control = ComputationControl(clock=lambda: now[0])
    control.slow_callback = lambda: notices.append(True)
    control.begin_optimizer()
    now[0] = 3
    control.end_optimizer()
    assert notices == [True]


def test_activity_mailbox_coalesces_and_phase_clears_it():
    control = ComputationControl()
    control.report("Preparing candidates")
    for _ in range(2000):
        control.activity("stock pairs considered", increment=1)
    assert control.activity_snapshot() == ("Preparing candidates", "stock pairs considered", 2000, None)
    control.report("Generating reactions")
    assert control.activity_snapshot() is None
    control.activity("reactions generated", completed=192, total=384)
    assert control.activity_snapshot()[-2:] == (192, 384)
    control.cancelled.set()
    with pytest.raises(OptimizationCancelled):
        control.activity("reactions generated", increment=1)
    assert control.activity_snapshot()[-2:] == (192, 384)


@pytest.mark.parametrize("automatic", [False, True])
def test_worker_slow_origin_and_main_thread_notice(qapp, manager, monkeypatch, automatic):
    notices, results = [], []
    model = _dense_target_model()
    def optimize(draft, **kwargs):
        control = draft._optimization_control
        control._clock = lambda: 3.0
        control._optimizer_started = 0.0
        control.check()
        return {"best": False}
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", optimize)
    manager.submit(model, request_for(model, automatic=automatic), results.append,
                   slow_optimizer=lambda: notices.append(QThread.currentThread()))
    wait_for(qapp, lambda: results)
    assert notices == ([QThread.currentThread()] if automatic else [])
    assert len(results) == 1


@pytest.mark.parametrize("stale", [False, True])
def test_live_slow_pause_and_cancel_keep_last_allocation(qapp, real_editor, monkeypatch, stale):
    editor = real_editor
    entered, release = threading.Event(), threading.Event()
    def optimize(draft, **kwargs):
        control = draft._optimization_control
        control._clock = lambda: 3.0
        control._optimizer_started = 0.0
        control.check()
        entered.set()
        assert release.wait(10)
        control.check()
        return {"best": False}
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", optimize)
    editor.auto_update_chk.setChecked(True)
    editor._auto_timer.stop()
    outcomes, continuations = [], []
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    editor._run_design_optimization_flow(automatic=True, on_complete=lambda: continuations.append(True))
    if stale:
        editor.model.metadata["replicates"] = 2
    try:
        wait_for(qapp, entered.is_set)
        ui = editor._optimization_ui
        assert editor._slow_auto_update_paused is (not stale)
        assert editor.auto_update_chk.isChecked() is stale
        assert optimization_job_manager().busy
        ui.cancel()
        ui.phase("Queued obsolete phase")
        ui.refresh()
        assert ui.dialog.labelText() == "Canceling…"
        assert ui.dialog.isVisible()
        release.set()
        wait_for(qapp, lambda: outcomes)
        assert ui.finished and (not isValid(ui.timer) or not ui.timer.isActive())
        assert not outcomes[0][0] and not continuations
        assert not editor.model.plans_per_option
        assert editor._design_optimization_dirty
        assert editor._slow_auto_update_paused is (not stale)
    finally:
        release.set()


def test_explicit_reenable_honored_until_design_replacement(real_editor):
    editor = real_editor
    editor.auto_update_chk.setChecked(True)
    editor._pause_slow_auto_update()
    assert editor._auto_update_preference
    assert not editor.auto_update_chk.isChecked()
    assert not editor.slow_auto_update_notice.isHidden()
    editor._mark_design_optimization_clean({"best": True})
    assert not editor.slow_auto_update_notice.isHidden()
    editor.auto_update_chk.setChecked(True)
    assert editor._slow_auto_update_override
    assert editor.slow_auto_update_notice.isHidden()
    editor._pause_slow_auto_update()
    assert editor.auto_update_chk.isChecked()
    editor._reset_auto_update_session()
    editor._pause_slow_auto_update()
    assert not editor.auto_update_chk.isChecked()
    editor._reset_auto_update_session()
    assert editor.auto_update_chk.isChecked()
    editor.auto_update_chk.setChecked(False)
    editor._reset_auto_update_session()
    assert not editor.auto_update_chk.isChecked()


def test_progress_details_delayed_and_updates_coalesced(qapp, real_editor, monkeypatch):
    from View import _AsyncOptimizationUi
    import View
    editor = real_editor
    clock = [100.0]
    monkeypatch.setattr(View.time, "monotonic", lambda: clock[0])
    ui = _AsyncOptimizationUi(editor, [], lambda *_: None, lambda: None, lambda _: None)
    try:
        assert ui.timer.interval() == 500
        ui.phase("Preparing candidates")
        # Phase signals only update the mailbox, never repaint each candidate.
        assert ui.dialog.labelText() == "Updating…"
        clock[0] = 100.99
        ui.refresh()
        assert ui.dialog.labelText() == "Preparing candidates"
        monkeypatch.setattr(optimization_job_manager(), "activity_snapshot",
                            lambda owner: ("Preparing candidates", "stock pairs considered", 2400, None))
        clock[0] = 101
        ui.refresh()
        assert "2,400 stock pairs considered" in ui.dialog.labelText()
        assert "1 second elapsed" in ui.dialog.labelText()
        ui.phase("Generating reactions")
        ui.refresh()
        assert "stock pairs" not in ui.dialog.labelText()
    finally:
        ui.finish(None)


def test_generation_activity_total_is_actual_reactions():
    model = _dense_target_model()
    model.factors[0].options[0].targets = [0.5, 1, 5, 20]
    model.optimize_stock_solutions(allow_two=True)
    model._optimization_control = control = ComputationControl()
    control.report("Generating reactions")
    model.generate_experiment()
    assert control.activity_snapshot() == ("Generating reactions", "reactions generated", 4, 4)


@pytest.mark.parametrize("reuse", [False, True])
def test_slow_generation_does_not_pause_auto_updates(qapp, manager, monkeypatch, reuse):
    model = _dense_target_model()
    model.factors[0].options[0].targets = [0.5, 1, 5, 20]
    result = model.optimize_stock_solutions(allow_two=True)
    notices, outcomes = [], []
    original = ExperimentModel.generate_experiment
    def generate(draft):
        control = draft._optimization_control
        assert control._optimizer_started is None
        control._clock = lambda: 1e20
        control.check()
        original(draft)
    monkeypatch.setattr(ExperimentModel, "generate_experiment", generate)
    manager.submit(model, request_for(model, automatic=True, reuse_allocation=reuse,
                                    previous_result=result), outcomes.append,
                   slow_optimizer=lambda: notices.append(True))
    wait_for(qapp, lambda: outcomes)
    assert outcomes[0].status == "succeeded", outcomes[0].error
    assert not notices


@pytest.mark.parametrize("blocked", ["gripper", "execution"])
def test_new_interlock_rejects_slow_notice(qapp, real_editor, monkeypatch, blocked):
    editor = real_editor
    editor.auto_update_chk.setChecked(True)
    editor._auto_timer.stop()
    outcomes = []
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    def optimize(draft, **kwargs):
        control = draft._optimization_control
        control._clock = lambda: 3
        control._optimizer_started = 0
        control.check()
        return {"best": False}
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", optimize)
    editor._run_design_optimization_flow(automatic=True)
    name = "_gripper_edit_lock_is_active" if blocked == "gripper" else "_model_execution_is_read_only"
    monkeypatch.setattr(editor, name, lambda *args: True)
    wait_for(qapp, lambda: outcomes)
    assert not editor._slow_auto_update_paused
    assert not outcomes[0][0]


def test_failed_new_design_preserves_slow_pause(real_editor, monkeypatch):
    from View import QMessageBox
    editor = real_editor
    editor.auto_update_chk.setChecked(True)
    editor._pause_slow_auto_update()
    monkeypatch.setattr(editor, "_confirm_unsaved_changes", lambda *args: True)
    monkeypatch.setattr(editor, "_confirm_resume_ready_new_experiment", lambda: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    def fail():
        raise ValueError("injected reset failure")
    monkeypatch.setattr(editor.main_window, "start_new_experiment_session", fail, raising=False)
    editor._on_new_experiment()
    assert editor._slow_auto_update_paused
    assert not editor.auto_update_chk.isChecked()


def test_stopped_auto_timer_cannot_submit_again(real_editor, monkeypatch):
    editor = real_editor
    editor.auto_update_chk.setChecked(True)
    editor._pause_slow_auto_update()
    calls = []
    monkeypatch.setattr(editor, "_run_design_optimization_flow", lambda **kw: calls.append(kw))
    editor._recompute_silent()
    assert not calls
    editor.auto_update_chk.setChecked(True)
    editor._recompute_silent()
    assert calls[0]["automatic"]
