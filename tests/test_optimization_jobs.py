import copy
import json
import threading
import time
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pytest
from PySide6.QtCore import QObject, QThread

from Model import ExperimentModel
from OptimizationJobs import (
    ComputationControl, OptimizationCancelled, OptimizationJobManager,
    OptimizationRequest, _OptimizationWorker, input_fingerprint,
    optimization_job_manager,
)
from tests.test_stock_optimizer_performance import _dense_target_model, _bnext_model, _large_import_model


@pytest.mark.parametrize("change", ["none", "stream", "uploaded", "cancel", "source", "model", "gripper", "destination", "failure",
                                    "cancel_ready", "source_ready", "model_ready", "destination_ready", "close_ready", "calibration_ready", "file_failure"])
def test_editable_copy_worker_publication_is_guarded(qapp, real_editor, tmp_path, monkeypatch, change):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    from test_experiment_duplicate_design import _configure_factor_design

    editor = real_editor
    model = editor.model
    model.factors.clear()
    _configure_factor_design(model)
    if change == "stream":
        option = model.factors[0].options[0]
        option.printing_mode = "stream"
        option.droplet_nL = 250.0
        assert model.optimize_stock_solutions()["best"]
        model.generate_experiment()
    if change == "uploaded":
        model.set_uploaded_design_from_dataframe(
            pd.DataFrame({"Well ID": ["A1", "A2"], "Mg mM": [0.0, 1.0]}),
            units_default="mM", droplet_nL_default=10.0,
            source_path=str(tmp_path / "input.csv"),
        )
        model.optimize_stock_solutions()
        model.generate_experiment()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    model.experiment_dir_path = str(source_dir)
    model.update_all_paths()
    model.save_experiment()
    source_path = Path(model.experiment_file_path)
    original_bytes = source_path.read_bytes()
    document = json.loads(original_bytes)
    destination = tmp_path / "editable"
    original_optimizer = ExperimentModel.optimize_stock_solutions
    started = threading.Event()
    release = threading.Event()
    worker_threads = []
    outcomes = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: None)
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    ready, closed = [], []
    def copy_ready(_job_id, phase):
        if phase != "Copy ready":
            return
        ready.append(True)
        assert list(tmp_path.glob(".*.staging-*"))
        if change == "cancel_ready":
            editor._optimization_ui.cancel()
        elif change == "close_ready":
            editor._optimization_ui.close_when_finished(lambda: closed.append(True))
        elif change == "source_ready":
            source_path.write_bytes(original_bytes + b"\n")
        elif change == "model_ready":
            model.metadata["name"] = "changed after preparation"
        elif change == "destination_ready":
            destination.mkdir()
            (destination / "keep.txt").write_text("existing user data")
        elif change == "calibration_ready":
            def require_idle():
                raise RuntimeError("A calibration is active.")
            model._calibration_manager = SimpleNamespace(_require_idle_for_experiment_transition=require_idle)
    optimization_job_manager().phase_changed.connect(copy_ready)
    if change == "file_failure":
        original_save = ExperimentModel.save_experiment
        def fail_staging_save(draft):
            if ".staging-" in str(draft.experiment_dir_path):
                raise OSError("injected staged-file write failure")
            return original_save(draft)
        monkeypatch.setattr(ExperimentModel, "save_experiment", fail_staging_save)

    def held(draft, **kwargs):
        worker_threads.append(QThread.currentThread())
        started.set()
        while not release.wait(0.005):
            draft._optimization_checkpoint()
        if change == "failure":
            raise ValueError("injected copy optimization failure")
        return original_optimizer(draft, **kwargs)

    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", held)
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start()
    try:
        ok, pending = editor._start_duplicate_design_job(
            source_path, source_dir, "editable", destination, document,
        )
        assert not ok and pending["pending"]
        wait_for(qapp, lambda: started.is_set() and len(ticks) >= 3)
        assert not destination.exists()
        assert model.experiment_dir_path == str(source_dir)
        if change == "cancel":
            editor._optimization_ui.cancel()
        elif change == "source":
            document["metadata"]["name"] = "externally changed"
            source_path.write_text(json.dumps(document), encoding="utf-8")
        elif change == "model":
            model.metadata["name"] = "changed in memory"
        elif change == "gripper":
            monkeypatch.setattr(editor, "_gripper_edit_lock_is_active", lambda: True)
        elif change == "destination":
            destination.mkdir()
            (destination / "keep.txt").write_text("existing user data")
        release.set()
        wait_for(qapp, lambda: outcomes)
        assert worker_threads and all(thread != qapp.thread() for thread in worker_threads)
        assert len(worker_threads) == 1  # No search during save, validation or reload.
        if change in ("none", "stream", "uploaded"):
            assert outcomes[0][0], outcomes
            assert model.experiment_dir_path == str(destination)
            assert (destination / "experiment_design.json").exists()
            assert not model._reactions_df.empty
            assert not editor._design_optimization_dirty
            assert editor._last_optimization_result["best"]
            stocks = model.plans_per_option[("Mg", None)]["stocks"]
            assert all(s["printing_mode"] == ("stream" if change == "stream" else "droplet") for s in stocks)
            assert all(s["droplet_volume_nL"] == (250.0 if change == "stream" else 10.0) for s in stocks)
            if change == "uploaded":
                assert model._uploaded_well_ids == ["A1", "A2"]
                assert (destination / "uploaded_design.csv").exists()
        else:
            assert not outcomes[0][0], outcomes
            assert model.experiment_dir_path == str(source_dir)
            if change in {"destination", "destination_ready"}:
                assert (destination / "keep.txt").read_text() == "existing user data"
                assert len(list(destination.iterdir())) == 1
            else:
                assert not destination.exists()
        if change.endswith("_ready"):
            assert ready
        if change == "close_ready":
            wait_for(qapp, lambda: closed)
        if change not in {"source", "source_ready"}:
            assert source_path.read_bytes() == original_bytes
        assert not list(tmp_path.glob(".*.staging-*"))
    finally:
        if change == "calibration_ready":
            model._calibration_manager = None
        optimization_job_manager().phase_changed.disconnect(copy_ready)
        release.set()
        timer.stop()


@pytest.mark.parametrize("mode,volume", [("droplet", 10.04), ("stream", 249.04)])
def test_loading_unrun_design_searches_only_in_worker(qapp, real_editor, tmp_path, monkeypatch, mode, volume):
    from test_experiment_duplicate_design import _configure_factor_design
    source = ExperimentModel()
    _configure_factor_design(source)
    source.factors[0].options[0].droplet_nL = volume
    source.factors[0].options[0].printing_mode = mode
    source.metadata["final_reaction_volume_nL"] = 500.04
    source.experiment_dir_path = str(tmp_path)
    source.update_all_paths()
    source.save_experiment()
    before = Path(source.experiment_file_path).read_bytes()
    synchronous = ExperimentModel()
    synchronous.load_experiment(source.experiment_file_path, str(tmp_path))
    threads, outcomes = [], []
    original = ExperimentModel.optimize_stock_solutions

    def tracked(model, **kwargs):
        threads.append(QThread.currentThread())
        return original(model, **kwargs)

    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", tracked)
    editor = real_editor
    editor.auto_update_chk.setChecked(False)
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    ok, pending = editor._load_selected_design(str(tmp_path), source.experiment_file_path)
    assert not ok and pending["pending"]
    wait_for(qapp, lambda: outcomes)
    assert outcomes[0][0], outcomes
    assert threads and all(thread != qapp.thread() for thread in threads)
    assert Path(source.experiment_file_path).read_bytes() == before
    assert not editor.model._reactions_df.empty
    assert editor.model.factors == synchronous.factors
    assert editor.model.metadata == synchronous.metadata
    assert editor.model.plans_per_option == synchronous.plans_per_option
    pd.testing.assert_frame_equal(editor.model._reactions_df, synchronous._reactions_df)


def test_save_optimizer_keeps_simulated_mcu_communication_live(qapp, real_editor, test_profile, tmp_path, monkeypatch):
    import Machine_FreeRTOS as mfr
    from test_mcu_reader_liveness import LiveSerial
    from test_serial_reader import _frame
    from test_host_black_box_log import _make_machine
    from test_experiment_duplicate_design import _configure_factor_design

    editor = real_editor
    editor.model.factors.clear()
    _configure_factor_design(editor.model)
    editor.model.experiment_dir_path = str(tmp_path / "SourceExp")
    Path(editor.model.experiment_dir_path).mkdir()
    editor.model.update_all_paths()
    editor._sync_controls_from_model(recompute=False)
    editor._load_factors_into_table()
    editor._mark_design_optimization_dirty()
    machine = _make_machine(qapp, test_profile, tmp_path / "black-box")
    machine.ser = LiveSerial()
    reader = machine.reader = mfr.SerialReader(machine.ser)
    reader.status_received.connect(machine.update_status)
    machine._transport_ready = True
    machine._start_mcu_response_watchdog()
    lost = []
    machine.serial_connection_lost.connect(lost.append)
    stop_feed = threading.Event()
    def feed():
        while not stop_feed.wait(0.015):
            machine.ser.append_inbound(_frame(bytes([mfr.CMD_STATUS])))
    feeder = threading.Thread(target=feed)
    original = ExperimentModel.optimize_stock_solutions
    release = threading.Event()
    def held(draft, **kwargs):
        while not release.wait(0.005):
            draft._optimization_checkpoint()
        return original(draft, **kwargs)
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", held)
    outcomes = []
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    try:
        reader.start()
        feeder.start()
        wait_for(qapp, lambda: len(machine.status_history) >= 2)
        editor._on_save_design()
        # Hold optimization longer than the production MCU timeout while Qt and
        # the actual serial parser continue servicing simulated traffic.
        deadline = time.monotonic() + 2.7
        wait_for(qapp, lambda: time.monotonic() >= deadline)
        assert not outcomes and not lost and machine._transport_ready
        assert len(machine.status_history) > 10
        release.set()
        wait_for(qapp, lambda: outcomes)
        assert outcomes[0][0], outcomes
        assert Path(editor.model.experiment_file_path).exists()
        assert not lost and not machine.ser.writes
    finally:
        release.set()
        stop_feed.set()
        feeder.join(5)
        reader.request_stop()
        assert reader.wait(5000)
        machine._stop_mcu_response_watchdog()


def test_large_editable_copy_keeps_heartbeat_through_publication(qapp, real_editor, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    editor, rows = real_editor, 10000
    model = editor.model
    model.factors.clear()
    model.set_metadata(name="LargeSource", replicates=1, randomize_assignments=False,
                       target_reaction_volume_nL=500.0, final_reaction_volume_nL=1000.0,
                       allow_two_stock_solutions=False)
    model.set_uploaded_design_from_dataframe(
        pd.DataFrame({f"R{i} mM": [1.0] * rows for i in range(12)}),
        units_default="mM", droplet_nL_default=10.0,
    )
    for factor in model.factors:
        factor.options[0].forced_stock_conc = 100.0
    source = tmp_path / "large-source"
    source.mkdir()
    model.experiment_dir_path = str(source)
    model.update_all_paths()
    model.save_experiment()
    source_path = Path(model.experiment_file_path)
    original_bytes = source_path.read_bytes()
    document = json.loads(original_bytes)
    destination = tmp_path / "large-copy"
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: None)
    computations, publications, outcomes = [], [], []
    for name in ("optimize_stock_solutions", "install_stock_allocation_reuse_payload", "generate_experiment"):
        original = getattr(ExperimentModel, name)
        def tracked(self, *args, _name=name, _original=original, **kwargs):
            computations.append((_name, QThread.currentThread()))
            return _original(self, *args, **kwargs)
        monkeypatch.setattr(ExperimentModel, name, tracked)
    original_publish = model.publish_editable_copy
    def publish(prepared):
        started = time.monotonic()
        result = original_publish(prepared)
        publications.append(time.monotonic() - started)
        return result
    monkeypatch.setattr(model, "publish_editable_copy", publish)
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    beats = [time.monotonic()]
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: beats.append(time.monotonic()))
    timer.start()
    try:
        editor._start_duplicate_design_job(source_path, source, "LargeCopy", destination, document)
        startup_elapsed = time.monotonic() - beats[0]
        wait_for(qapp, lambda: outcomes, timeout=60)
        # Include final publication, display restoration and the next heartbeat.
        count = len(beats)
        wait_for(qapp, lambda: len(beats) > count)
        assert outcomes[0][0], outcomes
        assert len(model._reactions_df) == rows
        assert all(thread != qapp.thread() for _, thread in computations), computations
        assert [name for name, _ in computations].count("generate_experiment") == 1
        assert [name for name, _ in computations].count("install_stock_allocation_reuse_payload") == 1
        assert source_path.read_bytes() == original_bytes
        assert not list(tmp_path.glob(".*.staging-*"))
        max_gap = max(b - a for a, b in zip(beats, beats[1:]))
        print(f"Copy startup: {startup_elapsed:.3f}s; publication: {publications[0]:.3f}s; maximum heartbeat gap: {max_gap:.3f}s")
        assert max_gap < 0.250
    finally:
        timer.stop()


def test_destroyed_copy_owner_discards_prepared_files(qapp, manager, tmp_path):
    from PySide6.QtCore import QCoreApplication, QEvent
    from test_experiment_duplicate_design import _configure_factor_design
    model = ExperimentModel()
    _configure_factor_design(model)
    source = tmp_path / "source"
    source.mkdir()
    model.experiment_dir_path = str(source)
    model.update_all_paths()
    model.save_experiment()
    source_path = Path(model.experiment_file_path)
    before = source_path.read_bytes()
    document = json.loads(before)
    destination = tmp_path / "copy"
    owner, results, ready = QObject(), [], []
    def phase_changed(_job_id, phase):
        if phase == "Copy ready":
            assert list(tmp_path.glob(".*.staging-*"))
            ready.append(True)
            owner.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    manager.phase_changed.connect(phase_changed)
    request = OptimizationRequest({"legacy_mode": model.legacy_mode}, kind="duplicate", options={
        "source_json": json.dumps(document), "new_name": "Copy",
        "source_path": str(source_path), "destination": str(destination),
        "source_fingerprint": model._canonical_payload_sha256(document),
    })
    assert manager.submit(owner, request, results.append, phase_changed=lambda _: None)
    wait_for(qapp, lambda: not manager.busy)
    assert ready and not results
    assert not destination.exists()
    assert not list(tmp_path.glob(".*.staging-*"))
    assert source_path.read_bytes() == before


def wait_for(qapp, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        qapp.processEvents()
        assert time.monotonic() < deadline, "Qt operation did not complete"
        time.sleep(0.002)
    qapp.processEvents()


@pytest.fixture
def manager(qapp):
    service = OptimizationJobManager()
    yield service
    stopped = []
    service.shutdown(lambda: stopped.append(True))
    wait_for(qapp, lambda: stopped)


def request_for(model, **options):
    return OptimizationRequest(model.capture_optimization_inputs(), options={"allow_two": True, **options})


@pytest.mark.parametrize("factory", [
    _dense_target_model,
    lambda: _bnext_model(budget_nl=300, relax_stock_bounds=True),
    _large_import_model,
])
def test_worker_matches_synchronous_plan_and_generated_rows(qapp, manager, factory):
    model = factory()
    if isinstance(model, tuple):
        model = model[0]
    request = request_for(model)
    before = input_fingerprint(request.snapshot)
    results = []
    assert manager.submit(model, request, results.append)
    wait_for(qapp, lambda: results)
    outcome = results[0]
    assert outcome.status == "succeeded", outcome.error
    assert input_fingerprint(model.capture_optimization_inputs()) == before
    result = model.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)
    model.generate_experiment()
    assert outcome.result["optimizer_selected_rank"] == result["optimizer_selected_rank"]
    assert outcome.result["stock_allocation_work_units_by_kind"] == result["stock_allocation_work_units_by_kind"]
    assert outcome.computed["plans_per_option"] == model.plans_per_option
    pd.testing.assert_frame_equal(outcome.computed["_reactions_df"], model._reactions_df)


def test_worker_thread_isolated_and_publication_on_main_thread(qapp, manager, monkeypatch):
    model = _dense_target_model()
    main = QThread.currentThread()
    threads = []
    original = ExperimentModel.optimize_stock_solutions
    def run(self, **kwargs):
        threads.append(QThread.currentThread())
        assert self is not model
        assert self.thread() == QThread.currentThread()
        assert self._calibration_manager is None
        assert self.experiment_file_path is None
        assert self._runtime_well_plate is None
        return original(self, **kwargs)
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", run)
    request = request_for(model)
    results = []
    def completed(outcome):
        assert QThread.currentThread() == main
        model.install_optimization_outputs(outcome.computed, input_fingerprint(request.snapshot))
        results.append(outcome)
    signals = []
    model.stock_updated.connect(lambda: signals.append((QThread.currentThread(), bool(model._reactions_df.empty))))
    assert manager.submit(model, request, completed)
    wait_for(qapp, lambda: results)
    assert threads[0] != main
    assert signals == [(main, False)]


def test_duplicate_and_cancel_before_publication(qapp, manager, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def held(self, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"best": None}
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", held)
    owner = _dense_target_model()
    results = []
    assert manager.submit(owner, request_for(owner), results.append)
    wait_for(qapp, entered.is_set)
    assert not manager.submit(owner, request_for(owner), results.append)
    manager.cancel(owner)
    release.set()
    wait_for(qapp, lambda: results)
    assert [r.status for r in results] == ["cancelled"]
    assert not owner.plans_per_option


@pytest.mark.parametrize("phase", ["Preparing candidates", "Optimizing allocations"])
def test_cancel_escapes_optimizer_fallback(phase):
    model = _dense_target_model()
    control = ComputationControl()
    control.phase_callback = lambda current: control.cancelled.set() if current == phase else None
    model._optimization_control = control
    with pytest.raises(OptimizationCancelled):
        model.optimize_stock_solutions(allow_two=True)
    assert not model.plans_per_option


def test_stale_and_incomplete_publication_rejected():
    model = _dense_target_model()
    fingerprint = input_fingerprint(model.capture_optimization_inputs())
    computed = model.capture_optimization_outputs()
    model.metadata["replicates"] = 2
    with pytest.raises(ValueError, match="changed"):
        model.install_optimization_outputs(computed, fingerprint)
    fingerprint = input_fingerprint(model.capture_optimization_inputs())
    with pytest.raises(ValueError, match="Incomplete"):
        model.install_optimization_outputs({}, fingerprint)


def test_snapshot_owns_nested_input_data():
    model = _dense_target_model()
    snapshot = model.capture_optimization_inputs()
    snapshot["factors"][0].options[0].targets.append(123.0)
    assert 123.0 not in model.factors[0].options[0].targets


def test_computation_failure_is_terminal_and_does_not_publish(qapp, manager, monkeypatch):
    model = _dense_target_model()
    def fail(*args, **kwargs):
        raise ValueError("injected failure")
    monkeypatch.setattr(ExperimentModel, "generate_experiment", fail)
    results = []
    assert manager.submit(model, request_for(model), results.append)
    wait_for(qapp, lambda: results)
    assert results[0].status == "failed"
    assert results[0].error == "injected failure"
    assert not model.plans_per_option


@pytest.fixture
def real_editor(qapp):
    from tests.test_experiment_design_reagent_headtype_integration import _build_real_dialog
    dialog = _build_real_dialog(_dense_target_model())
    dialog._auto_timer.stop()
    dialog._sync_controls_from_model(recompute=False)
    dialog._load_factors_into_table()
    dialog.auto_update_chk.setChecked(False)
    dialog._auto_timer.stop()
    dialog._mark_design_optimization_dirty()
    yield dialog
    service = optimization_job_manager()
    service.cancel()
    wait_for(qapp, lambda: not service.busy)
    dialog._allow_close_without_prompt = True
    dialog.close()
    stopped = []
    service.shutdown(lambda: stopped.append(True))
    wait_for(qapp, lambda: stopped)
    qapp.removeEventFilter(service)
    qapp._optimization_job_manager = None
    service.deleteLater()


def test_real_editor_async_publication_and_paused_inputs(qapp, real_editor):
    dialog = real_editor
    outcomes = []
    dialog.optimization_finished.connect(lambda ok, result: outcomes.append((ok, result)))
    ok, pending = dialog._run_design_optimization_flow()
    assert not ok and pending["pending"]
    assert not outcomes
    assert not dialog.v_spin.isEnabled()
    assert not dialog.reagent_table.isEnabled()
    wait_for(qapp, lambda: outcomes)
    assert outcomes[0][0], outcomes
    assert not dialog._design_optimization_dirty
    assert dialog.v_spin.isEnabled()
    assert not dialog.model._reactions_df.empty


def test_real_editor_cancel_clears_pending_save(qapp, real_editor):
    dialog = real_editor
    completed = []
    outcomes = []
    dialog.optimization_finished.connect(lambda *args: outcomes.append(args))
    dialog._run_design_optimization_flow(on_complete=lambda: completed.append(True))
    dialog._optimization_ui.cancel()
    wait_for(qapp, lambda: outcomes)
    assert not outcomes[0][0]
    assert not completed
    assert not dialog.model.plans_per_option
    assert dialog._design_optimization_dirty


def test_real_editor_rejects_inconsistent_single_stock_counts_before_publication(
    qapp, real_editor, monkeypatch, tmp_path,
):
    editor = real_editor
    editor.model.factors.clear()
    editor.model.set_metadata(
        target_reaction_volume_nL=100.0, final_reaction_volume_nL=1000.0,
        printed_volume_tolerance_nL=0.0,
    )
    editor.model.add_additive("Signal", [1.0], "mM", 10.0, forced_stock_conc=50.0)
    editor._sync_controls_from_model(recompute=False)
    editor._load_factors_into_table()
    outcomes, continuations, notifications = [], [], []
    editor.optimization_finished.connect(lambda *args: outcomes.append(args))
    editor._run_design_optimization_flow()
    wait_for(qapp, lambda: outcomes)
    assert outcomes.pop()[0]
    before = editor.model.capture_optimization_outputs()
    history = copy.deepcopy(editor.model.applied_imaging_calibrations)
    path = tmp_path / "design.json"
    path.write_bytes(b"previous saved design")
    editor.model.experiment_file_path = str(path)
    original = ExperimentModel.optimize_stock_solutions
    def corrupt(draft, **kwargs):
        result = original(draft, **kwargs)
        stock = draft.plans_per_option[("Signal", None)]["stocks"][0]
        assert stock["droplets_per_target"][1.0] == 2
        stock["droplets_per_target"][1.0] = 1
        return result
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", corrupt)
    editor.model.stock_updated.connect(lambda: notifications.append("stocks"))
    editor.model.experiment_generated.connect(lambda *_: notifications.append("reactions"))
    editor._mark_design_optimization_dirty()
    editor._run_design_optimization_flow(on_complete=lambda: continuations.append(True))
    wait_for(qapp, lambda: outcomes)

    assert len(outcomes) == 1 and not outcomes[0][0]
    assert "validation" in outcomes[0][1]["reason"].lower()
    assert not notifications and not continuations
    assert editor._design_optimization_dirty
    assert editor.model.applied_imaging_calibrations == history
    assert path.read_bytes() == b"previous saved design"
    after = editor.model.capture_optimization_outputs()
    for name, value in before.items():
        if isinstance(value, pd.DataFrame):
            pd.testing.assert_frame_equal(after[name], value)
        else:
            assert after[name] == value, name


def test_real_editor_rejects_external_changes(qapp, real_editor):
    dialog = real_editor
    outcomes = []
    dialog.optimization_finished.connect(lambda *args: outcomes.append(args))
    dialog._run_design_optimization_flow()
    dialog.model.metadata["replicates"] = 2
    wait_for(qapp, lambda: outcomes)
    assert not outcomes[0][0]
    assert "changed" in outcomes[0][1]["reason"]
    assert not dialog.model.plans_per_option


@pytest.mark.parametrize("reuse", [False, True])
def test_calibrated_allocation_and_history_survive_worker(qapp, manager, reuse):
    from tests.test_experiment_forced_stock_preview import (
        _make_calibratable_two_stock_model, _two_stock_applied_calibration,
    )
    model, stock_id = _make_calibratable_two_stock_model()
    model.apply_droplet_volume_for_option(
        "R", None, 12.0, write_keys_if_assigned=False,
        applied_calibration=_two_stock_applied_calibration(stock_id), printing_mode="droplet",
    )
    before = copy.deepcopy(model.applied_imaging_calibrations)
    results = []
    request = request_for(model, reuse_allocation=reuse, previous_result={"best": True})
    assert manager.submit(model, request, results.append)
    wait_for(qapp, lambda: results)
    assert results[0].status == "succeeded", results[0].error
    model.install_optimization_outputs(results[0].computed, input_fingerprint(request.snapshot))
    assert model.applied_imaging_calibrations == before
    assert model.calibrated_stock_allocation["active"]
    assert [s["droplet_volume_nL"] for s in model.plans_per_option[("R", None)]["stocks"]] == [12, 10]


def test_choice_fixed_and_additional_conditions(qapp, manager):
    model = _dense_target_model()
    model.factors.clear()
    model.add_choice_group("Signal")
    model.add_choice_option("Signal", "A", [0, 0.5, 1, 5, 20], "mM", 10, max_stock_conc=2000)
    model.add_choice_option("Signal", "B", [1], "mM", 10, max_stock_conc=2000)
    model.add_additive("Other", [0.01], "mM", 10, forced_stock_conc=5)
    model.set_additional_conditions([{"label": "control", "targets": {("Signal", "B"): 0.5}, "replicates": 2}])
    results = []
    assert manager.submit(model, request_for(model), results.append)
    wait_for(qapp, lambda: results)
    assert results[0].status == "succeeded", results[0].error
    model.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)
    model.generate_experiment()
    assert results[0].computed["plans_per_option"] == model.plans_per_option
    pd.testing.assert_frame_equal(results[0].computed["_reactions_df"], model._reactions_df)


def test_import_job_matches_report_and_cancellation_escapes(qapp, manager):
    from tests.test_stock_optimizer_performance import _benchmark_import_design, _benchmark_stock_rows
    model = _dense_target_model()
    options = dict(df=_benchmark_import_design(), max_stock_df=_benchmark_stock_rows(),
                   allow_two=True, printed_volume_nL=300, final_volume_nL=2000)
    results = []
    request = OptimizationRequest(model.capture_optimization_inputs(), kind="import", options=options)
    assert manager.submit(model, request, results.append)
    wait_for(qapp, lambda: results)
    assert results[0].status == "succeeded"
    expected = model.build_import_feasibility_report(**options)
    assert results[0].result["stock_rows"] == expected["stock_rows"]
    control = ComputationControl()
    control.phase_callback = lambda phase: control.cancelled.set()
    model._optimization_control = control
    with pytest.raises(OptimizationCancelled):
        model.build_import_feasibility_report(**options)


def test_publication_failure_rolls_back_every_output(monkeypatch):
    model = _dense_target_model()
    snapshot = model.capture_optimization_outputs()
    computed = copy.deepcopy(snapshot)
    computed["_stock_rows_cache"] = [{"injected": True}]
    original = ExperimentModel.__setattr__
    failed = []
    def fail_once(self, name, value):
        if self is model and name == "_reactions_df" and not failed:
            failed.append(True)
            raise RuntimeError("installation failure")
        original(self, name, value)
    fingerprint = input_fingerprint(model.capture_optimization_inputs())
    monkeypatch.setattr(ExperimentModel, "__setattr__", fail_once)
    with pytest.raises(RuntimeError, match="installation failure"):
        model.install_optimization_outputs(computed, fingerprint)
    assert model._stock_rows_cache == snapshot["_stock_rows_cache"]
    assert model.plans_per_option == snapshot["plans_per_option"]
    pd.testing.assert_frame_equal(model._reactions_df, snapshot["_reactions_df"])


def test_shutdown_cancels_and_drains_without_blocking(qapp, manager, monkeypatch):
    entered = threading.Event()
    def wait_for_cancel(self, **kwargs):
        entered.set()
        assert self._optimization_control.cancelled.wait(5)
        self._optimization_checkpoint()
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", wait_for_cancel)
    owner = _dense_target_model()
    results, stopped = [], []
    assert manager.submit(owner, request_for(owner), results.append)
    wait_for(qapp, entered.is_set)
    manager.shutdown(lambda: stopped.append(True))
    assert not stopped
    wait_for(qapp, lambda: stopped)
    assert [r.status for r in results] == ["cancelled"]
    assert manager._thread is None


def test_real_import_wizard_publishes_current_report(qapp, real_editor):
    from View import ExperimentImportWizard
    wizard = ExperimentImportWizard(real_editor.model, parent=real_editor,
                                    printed_volume_nL=240, final_volume_nL=5000, allow_two=True)
    wizard.load_design_dataframe(pd.DataFrame({"[A] mM": [0.5, 1, 5, 20]}))
    outcomes = []
    wizard.optimization_finished.connect(lambda *args: outcomes.append(args))
    wizard._recompute_report()
    assert not wizard.apply_btn.isEnabled()
    assert not wizard.printed_volume_spin.isEnabled()
    wait_for(qapp, lambda: outcomes)
    assert outcomes[0][0], outcomes
    assert wizard.report is not None and not wizard._report_dirty
    assert wizard.printed_volume_spin.isEnabled()
    wizard.close()


def test_closing_editor_cancels_job_before_destroying_ui(qapp, real_editor):
    editor = real_editor
    finished = []
    editor.optimization_finished.connect(lambda *args: finished.append(args))
    editor.show()
    editor._run_design_optimization_flow()
    editor.close()
    assert editor._optimization_ui is not None
    wait_for(qapp, lambda: finished and editor._optimization_ui is None)
    assert not finished[0][0]
    wait_for(qapp, lambda: not editor.isVisible())


def test_owner_deleted_during_computation_is_not_called(qapp, manager, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from PySide6.QtCore import QCoreApplication, QEvent
    entered, release = threading.Event(), threading.Event()
    def held(self, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"best": None}
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", held)
    owner, results = QWidget(), []
    assert manager.submit(owner, request_for(_dense_target_model()), results.append)
    wait_for(qapp, entered.is_set)
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    release.set()
    wait_for(qapp, lambda: not manager.busy)
    assert not results


def test_application_quit_drains_worker():
    root = Path(__file__).resolve().parents[1]
    code = '''
import tests.conftest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from Model import ExperimentModel
from OptimizationJobs import optimization_job_manager, OptimizationRequest
app = QApplication([])
model = ExperimentModel()
def running(self, **kwargs):
    while True:
        self._optimization_checkpoint()
ExperimentModel.optimize_stock_solutions = running
manager = optimization_job_manager()
results = []
manager.submit(model, OptimizationRequest(model.capture_optimization_inputs(), options={"allow_two": True}), results.append)
QTimer.singleShot(30, app.quit)
app.exec()
assert manager._thread is None
assert len(results) == 1 and results[0].status == "cancelled"
'''
    result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", code], cwd=root, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_compact_pair_signature_preserves_original_deduplication():
    import inspect
    import textwrap
    import Model
    source = textwrap.dedent(inspect.getsource(ExperimentModel._enumerate_two_stock_candidates_with_meta))
    original = "tuple(sorted((round(float(target), 12), int(drops[0]), int(drops[1])) for target, drops in drops_map.items()))"
    source = source.replace("tuple(drops_map[target] for target in xs)", original)
    namespace = {}
    exec(source, vars(Model), namespace)
    legacy = namespace["_enumerate_two_stock_candidates_with_meta"]
    model = _dense_target_model()
    options = dict(targets=[0, 0.25, 0.5, 1, 5, 20], droplet_nL=10, units="mM",
                   final_volume_nL=5000, volume_budget_nL=240, max_refine=20, max_pairs=1200)
    new_diagnostics, old_diagnostics = {}, {}
    new, new_limited = model._enumerate_two_stock_candidates_with_meta(**options, diagnostics=new_diagnostics)
    old, old_limited = legacy(model, **options, diagnostics=old_diagnostics)
    assert new_limited == old_limited
    assert new_diagnostics == old_diagnostics
    assert new == old


def test_completed_search_releases_candidates_without_full_gc(monkeypatch):
    import gc
    import weakref
    references = []
    original = ExperimentModel._enumerate_two_stock_candidates_with_meta
    def tracked(self, *args, **kwargs):
        plans, limited = original(self, *args, **kwargs)
        references.extend(weakref.ref(plan) for plan in plans)
        return plans, limited
    monkeypatch.setattr(ExperimentModel, "_enumerate_two_stock_candidates_with_meta", tracked)
    enabled = gc.isenabled()
    gc.disable()
    try:
        model = _dense_target_model()
        result = model.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)
        assert result["best"] and references
        assert all(reference() is None for reference in references)
    finally:
        if enabled:
            gc.enable()


def test_worker_validation_failure_does_not_publish(qapp, manager, monkeypatch):
    model = _dense_target_model()
    model.factors[0].options[0].targets = [0.5, 1, 5, 20]
    monkeypatch.setattr(ExperimentModel, "install_stock_allocation_reuse_payload",
                        lambda *args, **kwargs: {"reused": False, "reason": "injected mapping failure"})
    outcomes = []
    assert manager.submit(model, request_for(model), outcomes.append)
    wait_for(qapp, lambda: outcomes)
    assert len(outcomes) == 1 and outcomes[0].status == "failed"
    assert "injected mapping failure" in outcomes[0].error
    assert not outcomes[0].computed and not model.plans_per_option


@pytest.mark.parametrize("phase", ["Preparing candidates", "Exploring two-stock allocations",
                                  "Optimizing allocations", "Validating allocation", "Generating reactions"])
def test_cancel_at_worker_phase_has_one_terminal_outcome(qapp, manager, monkeypatch, phase):
    entered, release = threading.Event(), threading.Event()
    original = ComputationControl.report
    def held(self, current):
        original(self, current)
        if current == phase:
            entered.set()
            assert release.wait(5)
            self.check()
    monkeypatch.setattr(ComputationControl, "report", held)
    model = _dense_target_model()
    before = input_fingerprint(model.capture_optimization_inputs())
    outcomes = []
    assert manager.submit(model, request_for(model), outcomes.append)
    wait_for(qapp, entered.is_set)
    manager.cancel(model)
    release.set()
    wait_for(qapp, lambda: outcomes)
    assert [outcome.status for outcome in outcomes] == ["cancelled"]
    assert not outcomes[0].computed
    assert input_fingerprint(model.capture_optimization_inputs()) == before


def test_dispatch_follows_pending_ui_events(qapp, manager, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent
    delivered = threading.Event()
    class UiReceiver(QObject):
        def event(self, event):
            if event.type() == QEvent.User:
                delivered.set()
                return True
            return super().event(event)
    receiver = UiReceiver()
    def compute(self, **kwargs):
        assert delivered.is_set()
        return {"best": None}
    monkeypatch.setattr(ExperimentModel, "optimize_stock_solutions", compute)
    model, outcomes = _dense_target_model(), []
    assert manager.submit(model, request_for(model), outcomes.append)
    QCoreApplication.postEvent(receiver, QEvent(QEvent.User))
    wait_for(qapp, lambda: outcomes)
    assert outcomes[0].status == "succeeded", outcomes[0].error
