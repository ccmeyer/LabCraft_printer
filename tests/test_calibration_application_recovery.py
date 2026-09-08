"""Recovery uses real application guards, publication, and calibration selection."""
from contextlib import contextmanager

import pytest
from PySide6 import QtWidgets

from test_execution_fill_workflow import _configure, _stock
from test_execution_two_stock_workflow import _apply, _files, _print, _reload, _counts
from test_initial_execution_plan_integration import _configure_calibratable_two_stock_execution


@contextmanager
def _dialog(em, monkeypatch, qapp, tmp_path, *, fill=False):
    from CalibrationClasses.View import DropletImagingDialog
    from test_droplet_imaging_summary_table import _build_dialog, _make_run, _select_visible_row
    selected = _stock(em, "Water" if fill else "Signal")
    runs = [_make_run("recovery-result", stock=selected.stock_id, sweep_entries=[{
        "timestamp": "2026-09-08T09:00:00Z", "pw_us": 1400, "pressure_psi": 0.8,
        "mean_nL": 11.0 if fill else 25.0, "cv_pct": 4.0, "valid": True,
    }])]
    for method in ("information", "warning", "critical"):
        monkeypatch.setattr(QtWidgets.QMessageBox, method, lambda *a, **kw: None)
    monkeypatch.setattr(DropletImagingDialog, "_apply_print_settings_for_applied_calibration",
                        lambda *a, **kw: {"ok": True})
    dialog, _ = _build_dialog(monkeypatch, qapp, tmp_path, runs,
        current_stock=selected.stock_id, active_run_id="recovery-result", experiment_model=em)
    head = dialog.model.rack_model.get_gripper_printer_head()
    head.get_reagent_name = lambda: selected.factor_name
    head.printer_head_id = "head-" + selected.stock_id
    try:
        _select_visible_row(dialog, 0)
        dialog._refresh_bridge_preview_from_selection()
        yield dialog
    finally:
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("reverse", [False, True])
def test_two_stock_no_fill_calibrate_print_resume(experiment_model_factory, reverse):
    em = _configure_calibratable_two_stock_execution(experiment_model_factory(), fill_volume=250.0)
    plan = em.get_execution_plan_snapshot()
    assert not any(s.units == "--" for s in plan.stocks)
    first, second = sorted(plan.stocks, key=lambda s: s.concentration, reverse=reverse)
    em.ensure_execution_resume_checkpoint()
    _apply(em, first, 12.0)
    _print(em, first.stock_id, partial=True)
    _, em = _reload(experiment_model_factory, em)
    before = em.get_execution_plan_snapshot()
    preview = em.preview_requantized_for_option(("Signal", None), 11.0, calibrated_stock_id=second.stock_id)
    assert preview["ok"], preview
    result = _apply(em, second, 11.0, execution_context=preview["execution_context"])
    assert result["volume_shortfall"] == preview["volume_shortfall"]
    assert not result["volume_shortfall"]["fill_available"]
    assert _counts(em.get_execution_plan_snapshot(), first.stock_id) == _counts(before, first.stock_id)
    assert {s.stock_id for s in em.get_execution_plan_snapshot().stocks} == {s.stock_id for s in before.stocks}
    _, em = _reload(experiment_model_factory, em)
    _print(em, first.stock_id)
    _print(em, second.stock_id)


@pytest.mark.parametrize("fill", [False, True])
@pytest.mark.parametrize("outcome", ["retry", "cancel", "repeat_failure", "progress", "selected_progress"])
def test_io_retry_is_bounded_and_rechecks_progress(experiment_model_factory, monkeypatch, qapp, tmp_path, fill, outcome):
    em = _configure(experiment_model_factory())
    _apply(em, _stock(em, "Signal"), 10.0)
    with _dialog(em, monkeypatch, qapp, tmp_path, fill=fill) as dialog:
        before, files = em.get_execution_plan_snapshot(), _files(em)
        original = em._write_execution_plan_exports
        attempts, prompts = [], []
        def fail(*args, **kwargs):
            attempts.append(1)
            original(*args, **kwargs)
            if len(attempts) == 1 or outcome == "repeat_failure":
                raise OSError("injected save failure")
        def answer(*args, **kwargs):
            prompts.append(1)
            assert _files(em) == files
            if outcome == "progress":
                _print(em, _stock(em, "Other").stock_id, partial=True)
            if outcome == "selected_progress":
                _print(em, _stock(em, "Water" if fill else "Signal").stock_id, partial=True)
            return QtWidgets.QMessageBox.Cancel if outcome == "cancel" else QtWidgets.QMessageBox.Retry
        monkeypatch.setattr(em, "_write_execution_plan_exports", fail)
        monkeypatch.setattr(QtWidgets.QMessageBox, "question", answer)
        dialog._apply_previewed_droplet_volume()
        assert len(prompts) == 1
        if outcome == "retry":
            assert len(attempts) == 2
            assert em.get_execution_plan_snapshot().plan_revision == before.plan_revision + 1
        else:
            assert len(attempts) == (2 if outcome == "repeat_failure" else 1)
            assert em.get_execution_plan_snapshot() == before
            if outcome not in {"progress", "selected_progress"}:
                assert _files(em) == files
            else:
                assert "Preview refreshed" in dialog.bridge_status_label.text()
        assert em.get_execution_plan_sync_error() is None


@pytest.mark.parametrize("answer", ["yes", "no", "became_busy", "progress"])
def test_saved_execution_activation_is_available_in_dialog(experiment_model_factory, monkeypatch, qapp, tmp_path, answer):
    original = _configure(experiment_model_factory())
    _apply(original, _stock(original, "Signal"), 10.0)
    model = experiment_model_factory()
    em = model.experiment_model
    bundle = em.load_experiment(original.experiment_file_path, original.experiment_dir_path)
    assert bundle.valid and bundle.eligibility.can_activate_runtime
    with _dialog(em, monkeypatch, qapp, tmp_path) as dialog:
        state = {"value": "idle"}
        dialog.controller.get_array_run_state = lambda: state["value"]
        dialog.controller.check_if_all_completed = lambda: True
        calls = []
        after_progress = {}
        def activate():
            calls.append(1)
            return model.load_authoritative_execution_runtime()
        dialog.main_window.activate_authoritative_execution = activate
        def confirm(*args, **kwargs):
            if answer == "became_busy":
                state["value"] = "running"
            if answer == "progress":
                _print(original, _stock(original, "Other").stock_id, partial=True)
                after_progress.update(_files(em))
            return QtWidgets.QMessageBox.No if answer == "no" else QtWidgets.QMessageBox.Yes
        monkeypatch.setattr(QtWidgets.QMessageBox, "question", confirm)
        files = _files(em)
        dialog._recover_calibration_application()
        assert len(calls) == (1 if answer == "yes" else 0)
        if answer == "yes":
            assert dialog.bridge_apply_btn.isEnabled()
            assert em.is_authoritative_execution_runtime_active()
        else:
            assert _files(em) == (after_progress if answer == "progress" else files)


def test_refresh_after_pending_print_completes(experiment_model_factory, monkeypatch, qapp, tmp_path):
    em = _configure(experiment_model_factory())
    _apply(em, _stock(em, "Signal"), 10.0)
    with _dialog(em, monkeypatch, qapp, tmp_path) as dialog:
        stock = _stock(em, "Other")
        well = em.get_execution_plan_snapshot().wells[0]
        intent = em.begin_execution_print_intent(well_id=well.well_id, stock_id=stock.stock_id,
            commanded_droplets=1, printer_head_id="head-" + stock.stock_id)
        files = _files(em)
        dialog._recover_calibration_application()
        assert not dialog.bridge_apply_btn.isEnabled()
        assert _files(em) == files
        assert "pending print" in dialog.bridge_status_label.text()
        runtime = em._runtime_well_plate.get_well(well.well_id).get_assigned_reaction()
        reagent = runtime.get_all_reagents()[stock.stock_id]
        reagent.added_droplets += 1
        reagent.completed = reagent.is_complete()
        em.create_progress_file(execution_intent_id=intent)
        em.complete_execution_print_intent(intent)
        dialog._recover_calibration_application()
        assert dialog.bridge_apply_btn.isEnabled()
        dialog._apply_previewed_droplet_volume()
        assert _stock(em, "Signal").effective_volume_nL == 25.0


def test_incomplete_rollback_does_not_offer_retry(experiment_model_factory, monkeypatch, qapp, tmp_path):
    em = _configure(experiment_model_factory())
    _apply(em, _stock(em, "Signal"), 10.0)
    with _dialog(em, monkeypatch, qapp, tmp_path) as dialog:
        def fail(*args, **kwargs):
            raise OSError("injected persistent storage failure")
        monkeypatch.setattr(em, "_write_execution_plan_exports", fail)
        monkeypatch.setattr(em, "_restore_mutable_calibration_files", fail)
        prompts = []
        monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *a, **kw: prompts.append(1))
        dialog._apply_previewed_droplet_volume()
        assert not prompts
        assert em.get_execution_plan_sync_error()
        assert em._active_authoritative_execution_session is None
        assert "rollback was incomplete" in dialog.bridge_status_label.text()


def test_activation_never_discards_unsaved_live_prints(experiment_model_factory):
    em = _configure(experiment_model_factory())
    _apply(em, _stock(em, "Signal"), 10.0)
    sid = _stock(em, "Other").stock_id
    well = em._runtime_well_plate.get_all_wells()[0]
    reagent = well.get_assigned_reaction().get_all_reagents()[sid]
    reagent.added_droplets = 1
    files = _files(em)
    with pytest.raises(RuntimeError, match="cannot discard"):
        em.calibration_activation_context()
    assert _files(em) == files
    assert reagent.added_droplets == 1


def test_retry_cannot_apply_to_experiment_replaced_during_prompt(
    experiment_model_factory, monkeypatch, qapp, tmp_path,
):
    original = _configure(experiment_model_factory())
    replacement = _configure(experiment_model_factory())
    _apply(original, _stock(original, "Signal"), 10.0)
    with _dialog(original, monkeypatch, qapp, tmp_path) as dialog:
        before = _files(original), _files(replacement)
        write = original._write_execution_plan_exports
        attempts = []

        def fail_once(*args, **kwargs):
            attempts.append(1)
            write(*args, **kwargs)
            if len(attempts) == 1:
                raise OSError("injected save failure")

        def switch_experiment(*args, **kwargs):
            dialog.model.experiment_model = replacement
            return QtWidgets.QMessageBox.Retry

        monkeypatch.setattr(original, "_write_execution_plan_exports", fail_once)
        monkeypatch.setattr(QtWidgets.QMessageBox, "question", switch_experiment)
        dialog._apply_previewed_droplet_volume()
        assert attempts == [1]
        assert (_files(original), _files(replacement)) == before
        assert "changed" in dialog.bridge_status_label.text().lower()
