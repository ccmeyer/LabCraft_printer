import copy
import pytest
from PySide6.QtCore import QThread
import View

from Model import ExperimentModel
from OptimizationJobs import input_fingerprint, optimization_job_manager, OptimizationRequest
from tests.optimizer_qualification_cases import load_case
from tests.test_optimization_jobs import real_editor, wait_for
from tools.optimizer_realistic_qualification import new_editor, import_payload, close_owner, assert_outputs_equal


def test_qualification_editor_keeps_live_model_signal_bindings(qapp, real_editor):
    editor = new_editor(load_case("groups_import"), True)
    try:
        editor.model.experiment_generated.emit(17, 0.)
        assert editor.summary_total_reactions_value_lbl.text() == "17"
        editor._stock_table_refresh_scheduled = False
        editor.model.stock_updated.emit()
        assert editor._stock_table_refresh_scheduled
    finally:
        close_owner(qapp, editor)


@pytest.mark.parametrize("failure", ["cancel", "late_cancel", "prepare", "generate", "validate", "publish", "stale", "calibration", "interlock", "session"])
def test_rejected_import_apply_preserves_existing_design(qapp, real_editor, tmp_path, monkeypatch, failure):
    editor = new_editor(load_case("manual_groups"), True)
    outcomes = []
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    try:
        editor._run_design_optimization_flow()
        wait_for(qapp, lambda: outcomes)
        assert outcomes.pop()[0]
        payload = import_payload(qapp, load_case("groups_import"), True)
        before = editor.model.capture_optimization_inputs()
        outputs = editor.model.capture_optimization_outputs()
        history = copy.deepcopy(editor.model.applied_imaging_calibrations)
        path = tmp_path / "design.json"
        path.write_bytes(b"previous saved design")
        editor.model.experiment_file_path = str(path)
        def fail(*args, **kwargs):
            raise RuntimeError("injected import failure")
        if failure in ("prepare", "generate", "validate"):
            method = {"prepare": "prepare_import_application", "generate": "generate_experiment",
                      "validate": "validate_optimization_allocation"}[failure]
            monkeypatch.setattr(ExperimentModel, method, fail)
        if failure == "publish":
            original = ExperimentModel.__setattr__
            injected = []
            def broken(self, name, value):
                if self is editor.model and name == "_reactions_df" and not injected:
                    injected.append(True)
                    fail()
                original(self, name, value)
            monkeypatch.setattr(ExperimentModel, "__setattr__", broken)
        if failure == "late_cancel":
            original = View._AsyncOptimizationUi.finish
            def cancel_before_publish(self, outcome):
                self.cancel()
                return original(self, outcome)
            monkeypatch.setattr(View._AsyncOptimizationUi, "finish", cancel_before_publish)
        notifications = []
        editor.model.stock_updated.connect(lambda: notifications.append("stocks"))
        editor.model.experiment_generated.connect(lambda *_: notifications.append("reactions"))
        editor._apply_uploaded_design_payload(payload)
        # Submission must not replace committed inputs or allocations.
        assert input_fingerprint(editor.model.capture_optimization_inputs()) == input_fingerprint(before)
        if failure == "cancel":
            editor._optimization_ui.cancel()
        elif failure == "stale":
            editor.model.metadata["replicates"] = 2
            before["metadata"]["replicates"] = 2
        elif failure == "calibration":
            editor.model.applied_imaging_calibrations["external"] = {"value": 12}
            before["applied_imaging_calibrations"]["external"] = {"value": 12}
            history["external"] = {"value": 12}
        elif failure == "interlock":
            monkeypatch.setattr(editor, "_gripper_edit_lock_is_active", lambda: True)
        elif failure == "session":
            editor.model.experiment_file_path = "another-design.json"
        wait_for(qapp, lambda: outcomes)
        assert len(outcomes) == 1 and not outcomes[0][0]
        assert input_fingerprint(editor.model.capture_optimization_inputs()) == input_fingerprint(before)
        assert_outputs_equal(outputs, editor.model.capture_optimization_outputs())
        assert editor.model.applied_imaging_calibrations == history
        assert path.read_bytes() == b"previous saved design"
        assert not editor.model.has_uploaded_design()
        assert editor._design_optimization_dirty
        assert editor._optimization_ui is None
        assert not notifications
    finally:
        close_owner(qapp, editor)


def test_display_completion_holds_duplicate_and_shutdown_interlocks(qapp, real_editor, monkeypatch):
    editor = real_editor
    editor.model.factors[0].options[0].targets = [0.5, 1, 5, 20]
    editor._load_factors_into_table()
    service = optimization_job_manager()
    pending, outcomes, stopped = [], [], []
    restore = View._AsyncOptimizationUi._restore_after_publication
    monkeypatch.setattr(View._AsyncOptimizationUi, "_restore_after_publication",
                        lambda *args: pending.append(args))
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    editor._run_design_optimization_flow()
    wait_for(qapp, lambda: pending)
    assert service.busy and not outcomes
    assert editor._optimization_ui is not None
    assert not service.submit(editor, OptimizationRequest({}), lambda _: None)
    service.shutdown(lambda: stopped.append(True))
    assert not stopped
    restore(*pending.pop())
    wait_for(qapp, lambda: stopped)
    assert len(outcomes) == 1 and outcomes[0][0]
    assert not service.busy and editor._optimization_ui is None


@pytest.mark.parametrize("reuse", [True, False])
def test_import_apply_publishes_complete_worker_state(qapp, real_editor, monkeypatch, reuse):
    case = load_case("groups_import")
    payload = import_payload(qapp, case, True)
    if not reuse:
        payload.pop("stock_allocation_reuse_payload")
    editor = new_editor(load_case("manual_groups"), True)
    done, threads, published = [], [], []
    editor.optimization_finished.connect(lambda *args: done.append(args))
    main = QThread.currentThread()
    prepare = ExperimentModel.prepare_import_application
    def staged(self, *args):
        threads.append(QThread.currentThread())
        assert self is not editor.model
        assert self._runtime_well_plate is None and self._calibration_manager is None
        return prepare(self, *args)
    monkeypatch.setattr(ExperimentModel, "prepare_import_application", staged)
    editor.model.stock_updated.connect(lambda: published.append((QThread.currentThread(),
                                                                 editor.model.has_uploaded_design(),
                                                                 len(editor.model._reactions_df))))
    try:
        original_inputs = input_fingerprint(editor.model.capture_optimization_inputs())
        editor._apply_uploaded_design_payload(payload)
        assert input_fingerprint(editor.model.capture_optimization_inputs()) == original_inputs
        wait_for(qapp, lambda: done)
        assert len(done) == 1 and done[0][0], done
        assert threads and all(t != main for t in threads)
        assert published == [(main, True, 144)]
        expected = ExperimentModel()
        expected.restore_optimization_inputs(editor.model.capture_optimization_inputs())
        reused = prepare(expected, payload, editor.model.metadata)
        if not reused.get("reused"):
            expected.optimize_stock_solutions(quantum=.1, max_refine=60, two_max_refine=40, allow_two=True)
        expected.generate_experiment()
        assert_outputs_equal(expected.capture_optimization_outputs(), editor.model.capture_optimization_outputs())
        assert editor._uploaded_design_active
        assert not editor._stock_allocation_dirty
    finally:
        close_owner(qapp, editor)
