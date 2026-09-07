"""Real Qt routes and incremental evidence for opt-in optimizer qualification."""
import copy
import json
import os
from pathlib import Path
import statistics
import subprocess
import signal
import sys
import threading
import time

import pandas as pd
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from Model import ExperimentModel
from OptimizationJobs import input_fingerprint, optimization_job_manager
from View import ExperimentImportWizard
from tests.test_experiment_design_reagent_headtype_integration import _build_real_dialog
from tests.optimizer_qualification_cases import (
    CASE_IDS, ROOT, REFINEMENT, allocation_evidence, assert_physical_allocation, load_case, require_external,
)

_watchdog_path = None


def arm_watchdog(label):
    if _watchdog_path:
        save_evidence(_watchdog_path, {"started_monotonic": time.monotonic(), "interaction": label})


def disarm_watchdog():
    if _watchdog_path:
        save_evidence(_watchdog_path, {"started_monotonic": None})


def configure_watchdog(output):
    global _watchdog_path
    _watchdog_path = Path(output).with_suffix(".watchdog.json")
    request = Path(output).with_suffix(".cancel")
    # The supervisor writes this request only for its own child. Setting the
    # worker's cancellation event does not invoke UI methods from this thread.
    def watch():
        while not request.exists():
            time.sleep(.1)
        manager = getattr(QApplication.instance(), "_optimization_job_manager", None)
        if manager is not None:
            manager.cancel()
    threading.Thread(target=watch, daemon=True).start()


def supervise(args):
    """A hung Qt event loop cannot disable the external interaction watchdog."""
    output = require_external(args.output)
    checkpoint, cancel = output.with_suffix(".watchdog.json"), output.with_suffix(".cancel")
    if checkpoint.exists() or cancel.exists() or output.exists():
        raise ValueError("Use a unique evidence output path; prior evidence is never overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-B", str(ROOT / "tools/benchmark_optimizer_async.py"), *sys.argv[1:], "--worker"]
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    log = output.with_suffix(".worker.log").open("w", encoding="utf-8")
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, **kw)
    cleanup, timed_out = [], None
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    previous_handlers = {}
    for name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            sig = getattr(signal, name)
            previous_handlers[sig] = signal.signal(sig, interrupted)
    try:
        while process.poll() is None:
            if checkpoint.exists():
                state = json.loads(checkpoint.read_text())
                if state.get("started_monotonic") is not None and time.monotonic() - state["started_monotonic"] > 900:
                    timed_out = state
                    cancel.write_text("cancel owned qualification interaction", encoding="utf-8")
                    cleanup.append("cooperative cancellation requested")
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
                    break
            time.sleep(.25)
    finally:
        if process.poll() is None:
            cancel.write_text("cancel owned qualification interaction", encoding="utf-8")
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    process.terminate()
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                cleanup.append("terminated owned process/group after cancellation grace")
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    cleanup.append("killed owned process/group after termination grace")
                    process.wait(timeout=5)
        save_evidence(output.with_suffix(".process.json"), dict(pid=process.pid, returncode=process.returncode,
                      cleanup=cleanup, timeout=timed_out, owned_process_exited=process.poll() is not None))
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        log.close()
    if timed_out or process.returncode:
        evidence = json.loads(output.read_text()) if output.exists() else dict(schema_version=2, cases={}, blockers=[])
        if timed_out or not evidence.get("complete"):
            evidence.setdefault("blockers", []).append({"error": "Interaction timeout" if timed_out else "Qualification worker exited before completion", "detail": timed_out})
            evidence["complete"] = False
            save_evidence(output, evidence)
    return 1 if timed_out else process.returncode


def pump(app, predicate, timeout=900):
    deadline = time.monotonic() + timeout
    while not predicate():
        app.processEvents()
        if time.monotonic() >= deadline:
            optimization_job_manager().cancel()
            raise TimeoutError("15-minute qualification interaction watchdog expired")
        time.sleep(.001)


def await_outcome(app, outcomes):
    # A production callback exception can settle the worker without delivering
    # the owner's completion signal. Record that failure instead of waiting 15m.
    pump(app, lambda: bool(outcomes) or not optimization_job_manager().busy)
    assert outcomes, "Worker settled without UI completion (see Qt callback traceback)"


def close_owner(app, owner):
    optimization_job_manager().cancel(owner)
    pump(app, lambda: not optimization_job_manager().busy)
    owner._allow_close_without_prompt = True
    owner.close()
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def finish_input_events():
    # processEvents-only harnesses do not deliver DeferredDelete as a normal
    # app event loop does between user actions. Drain those before the next
    # simulated click, including the previous job's closed progress dialog.
    QApplication.instance().processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def observe_error_dialogs(owner):
    """Record and dismiss error dialogs in the unattended simulated lane."""
    owner._qualification_dialog_errors = []
    timer = QTimer(owner)
    timer.setInterval(20)
    def inspect():
        for dialog in QApplication.topLevelWidgets():
            if isinstance(dialog, QMessageBox) and dialog.isVisible():
                owner._qualification_dialog_errors.append(dialog.text())
                dialog.reject()
    timer.timeout.connect(inspect)
    timer.start()


def new_editor(case, allow_two):
    # Bind the actual computation model at construction so publication drives
    # the same stock/summary signal handlers as the application.
    editor = _build_real_dialog(ExperimentModel())
    editor._auto_timer.stop()
    editor.auto_update_chk.setChecked(False)
    editor.model.set_metadata(**case.metadata(allow_two))
    editor._sync_controls_from_model(recompute=False)
    editor._load_factors_into_table()
    editor.choice_groups = {r.group for r in case.reagents if r.group}
    if not case.imported:
        for r in case.reagents:
            editor._add_reagent_row(name=r.name, group=r.group or editor.GROUP_ADDITIVE,
                                   targets=", ".join(map(str, r.targets)), units=r.units,
                                   droplet_nL=r.droplet, forced_stock_conc=r.fixed,
                                   max_stock_conc=r.maximum, schedule_update=False)
    editor._auto_timer.stop()
    editor.show()
    observe_error_dialogs(editor)
    finish_input_events()
    return editor


def new_wizard(case, allow_two):
    model = ExperimentModel()
    model.set_metadata(**case.metadata(allow_two))
    wizard = ExperimentImportWizard(model, printed_volume_nL=case.printed,
                                    final_volume_nL=case.final,
                                    printed_volume_tolerance_nL=case.tolerance, allow_two=allow_two)
    wizard.load_design_dataframe(case.design)
    wizard.load_max_stock_dataframe(case.stock_frame)
    wizard.show()
    observe_error_dialogs(wizard)
    finish_input_events()
    return wizard


def import_payload(app, case, allow_two):
    arm_watchdog(case.name + "/import setup")
    wizard = new_wizard(case, allow_two)
    completed = []
    wizard.optimization_finished.connect(lambda *args: completed.append(args))
    try:
        wizard._recompute_report()
        await_outcome(app, completed)
        assert not wizard._qualification_dialog_errors, wizard._qualification_dialog_errors
        assert completed[0][0], completed
        assert wizard.report["ok"], wizard.report.get("issues")
        assert wizard.apply_btn.isEnabled()
        return wizard.get_apply_payload()
    finally:
        close_owner(app, wizard)
        disarm_watchdog()


def measure(app, case, allow_two, route, *, payload=None, cancel=None, automatic=False):
    arm_watchdog(f"{case.name}/{allow_two}/{route}/{cancel or 'complete'}")
    owner = new_wizard(case, allow_two) if route == "import" else new_editor(case, allow_two)
    manager = optimization_job_manager()
    outcomes, beats, phases, activity, cancelled_at = [], [], [], [], []
    ui_work = []
    # Attribute pauses to actual UI stages, including synchronous Apply setup
    # and publication. These timings are diagnostic, not optimizer decisions.
    def observe_method(target, name):
        original = getattr(target, name, None)
        if original is None:
            return
        def measured(*args, **kwargs):
            begin = time.monotonic()
            try:
                return original(*args, **kwargs)
            finally:
                if len(ui_work) < 256:
                    ui_work.append(dict(method=name, elapsed_ms=(begin-started)*1000,
                                        duration_ms=(time.monotonic()-begin)*1000))
        setattr(target, name, measured)
    for name in ("_apply_uploaded_design_payload", "_load_factors_into_table",
                 "_populate_composition_table", "_populate_stock_table",
                 "_refresh_stock_table", "_update_summary_labels"):
        observe_method(owner, name)
    for name in ("install_import_application", "install_optimization_outputs"):
        observe_method(owner.model, name)
    owner.optimization_finished.connect(lambda *args: outcomes.append(args))
    before = owner.model.capture_optimization_outputs()
    history = copy.deepcopy(owner.model.applied_imaging_calibrations)
    timer = QTimer()
    timer.setInterval(20)
    def cancel_now(observed):
        if cancelled_at or getattr(owner, "_optimization_ui", None) is None:
            return
        cancelled_at.append(time.monotonic())
        activity.append({"cancel_phase": observed})
        owner._optimization_ui.cancel()
    def beat():
        beats.append(time.monotonic())
        snapshot = manager.activity_snapshot(owner)
        if snapshot and (not activity or activity[-1].get("activity") != list(snapshot)):
            # Bounded sampling, not a worker callback per candidate.
            if len(activity) < 1000:
                activity.append({"activity": list(snapshot), "elapsed_ms": (beats[-1]-started)*1000})
        if cancel == "activity" and snapshot and snapshot[2] > 0 and snapshot[1] in {
                "stock pairs considered", "candidates filtered", "single-stock candidates considered"}:
            cancel_now(snapshot[1])
    def phase(job_id, value):
        phases.append({"phase": value, "elapsed_ms": (time.monotonic()-started)*1000})
        if cancel == "early":
            cancel_now(value)
    manager.phase_changed.connect(phase)
    started = time.monotonic()
    beats.append(started)
    timer.timeout.connect(beat)
    timer.start()
    try:
        if route == "import":
            snapshot = owner.model.capture_optimization_inputs()
            options = copy.deepcopy(owner._feasibility_job_options())
            owner._recompute_report()
        else:
            apply_failed = False
            if case.imported:
                owner._apply_uploaded_design_payload(copy.deepcopy(payload))
                await_outcome(app, outcomes)
                apply_failed = not outcomes[-1][0]
                if not apply_failed:
                    before = owner.model.capture_optimization_outputs()
                    assert_physical_allocation(case, owner.model)
                    if not case.hashes:
                        for index, reagent in enumerate(case.reagents):
                            owner._reagent_cell_widget(index, owner.COL_DROPLET).setValue(reagent.droplet)
                            if reagent.fixed is not None:
                                owner._reagent_cell_widget(index, owner.COL_SET_STOCK).setText(str(reagent.fixed))
                    outcomes.clear()
                    finish_input_events()
            if not apply_failed:
                owner._mark_design_optimization_dirty()
                if automatic:
                    owner.auto_update_chk.setChecked(True)
                    owner._auto_timer.stop()
                    owner._recompute_silent()
                else:
                    owner._run_design_optimization_flow()
            snapshot = owner.model.capture_optimization_inputs()
        await_outcome(app, outcomes)
        ended = time.monotonic()
        beats.append(ended)
        timer.stop()
        measurement = dict(total_ms=(ended-started)*1000,
                           max_gap_ms=max(b-a for a,b in zip(beats, beats[1:]))*1000,
                           phases=phases, activity=activity, ui_work=ui_work,
                           heartbeat_ms=[(b-started)*1000 for b in beats],
                           input_fingerprint=input_fingerprint(snapshot),
                           allow_two=allow_two, route=route, automatic=automatic,
                           auto_update_paused=bool(getattr(owner, "_slow_auto_update_paused", False)))
        measurement["actual_metadata"] = copy.deepcopy(owner.model.metadata)
        if cancel:
            measurement["cancellation_exercised"] = bool(cancelled_at)
            if cancelled_at:
                measurement["cancel_ms"] = (ended-cancelled_at[0])*1000
                assert not outcomes[0][0], "Cancellation published success"
                try:
                    assert_outputs_equal(before, owner.model.capture_optimization_outputs())
                except AssertionError as exc:
                    raise AssertionError(f"Cancellation changed committed outputs: {exc}") from exc
                assert owner.model.applied_imaging_calibrations == history
                return measurement
            # A short job may finish before a candidate phase is observable.
            measurement["not_exercised_reason"] = "No candidate/filter activity observed before completion"
            return measurement
        assert outcomes[0][0], outcomes
        assert not owner._qualification_dialog_errors, owner._qualification_dialog_errors
        baseline = ExperimentModel()
        baseline.restore_optimization_inputs(snapshot)
        begin_sync = time.monotonic()
        if route == "import":
            expected = baseline.build_import_feasibility_report(**options)
            measurement["synchronous_compute_ms"] = (time.monotonic()-begin_sync)*1000
            for key in ("ok", "stock_rows", "composition_rows", "reagent_specs", "stock_settings_by_reagent",
                        "max_stock_by_reagent", "stock_allocation_input_fingerprint"):
                assert owner.report[key] == expected[key], f"Import report differs: {key}"
            assert owner.report["ok"], owner.report.get("issues")
            allocation = owner.report["stock_allocation_reuse_payload"]
            for key in ("plans_per_option", "stock_rows", "plan_fingerprint", "input_fingerprint"):
                assert allocation[key] == expected["stock_allocation_reuse_payload"][key], key
            result = allocation["optimization_result"]
            measurement["allocation"] = dict(plan_fingerprint=allocation["plan_fingerprint"],
                selected_rank=result.get("optimizer_selected_rank"),
                work={k:v for k,v in result.items() if "work_units" in k},
                two_stock_keys=[list(k) for k,p in allocation["plans_per_option"].items() if p["n_stocks"] == 2])
            actual_volumes = {k:v["droplet_nL"] for k,v in owner.report["stock_settings_by_reagent"].items()}
            measurement["actual_ejection_volumes_nL"] = actual_volumes
            if not case.hashes and any(v != 10 for v in actual_volumes.values()):
                measurement["input_limitation"] = "Wizard uses mode-default ejection volume; requested 10 nL is not supported"
            if case.name == "real_25":
                assert owner.report["max_stock_by_reagent"]["[PolyP]"] == 500.
                assert owner.report["max_stock_by_reagent"]["[Amino Acids]"] == 6.
            if case.name == "real_68":
                assert all(r.get("status") == "OK" for r in owner.report["composition_rows"])
            if case.name == "real_60" and not allow_two:
                row = next(r for r in owner.report["composition_rows"] if "G13" in r.get("wells", []))
                assert row["status"] == "Near budget"
                assert row["selected_plan_required_volume_nL"] == 10140.
        else:
            result = baseline.optimize_stock_solutions(**REFINEMENT, allow_two=allow_two)
            measurement["synchronous_compute_ms"] = (time.monotonic()-begin_sync)*1000
            assert result.get("best"), result.get("reason")
            baseline.generate_experiment()
            measurement["synchronous_compute_ms"] = (time.monotonic()-begin_sync)*1000
            assert_outputs_equal(owner.model.capture_optimization_outputs(), baseline.capture_optimization_outputs())
            measurement["allocation"] = allocation_evidence(owner.model, outcomes[0][1])
            assert measurement["allocation"] == allocation_evidence(baseline, result)
            assert_physical_allocation(case, owner.model)
            if not case.imported:
                assert not owner.model.has_uploaded_design(), "Manual route became an upload"
            if case.name == "three_pairs" and allow_two:
                assert len(measurement["allocation"]["two_stock_keys"]) == 3
                assert measurement["allocation"]["rank"][0] == 0
            if automatic and result.get("optimizer_total_elapsed_ms", 0) >= 3000:
                assert owner._slow_auto_update_paused
        measurement["validation_ms"] = (time.monotonic()-begin_sync)*1000 - measurement["synchronous_compute_ms"]
        return measurement
    except Exception as exc:
        if "measurement" in locals():
            measurement["validation_error"] = str(exc) or type(exc).__name__
            return measurement
        raise
    finally:
        timer.stop()
        manager.phase_changed.disconnect(phase)
        close_owner(app, owner)
        disarm_watchdog()


def assert_outputs_equal(left, right):
    assert set(left) == set(right)
    for key in left:
        if isinstance(left[key], pd.DataFrame):
            pd.testing.assert_frame_equal(left[key], right[key])
        else:
            assert left[key] == right[key], key


def save_evidence(path, evidence):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    # Windows readers can briefly hold the destination without delete sharing.
    # Keep the previous complete JSON intact and retry the atomic replacement.
    for attempt in range(50):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(.01)


def summarize(runs, cancellations):
    all_runs = runs + cancellations
    return dict(median_ms=statistics.median(r["total_ms"] for r in runs),
                max_ms=max(r["total_ms"] for r in runs),
                synchronous_median_ms=(statistics.median(r["synchronous_compute_ms"] for r in runs
                                           if "synchronous_compute_ms" in r)
                                       if any("synchronous_compute_ms" in r for r in runs) else None),
                max_gap_ms=max(r["max_gap_ms"] for r in all_runs),
                max_cancel_ms=max((r.get("cancel_ms", 0) for r in cancellations), default=0))


def run_suite(app, args):
    revision = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    evidence = dict(schema_version=2, revision=revision, suite="realistic", runs=args.runs,
                    cases={}, blockers=[], complete=False)
    import hashlib
    evidence["source_files"] = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
        for path in (ROOT/"tools/benchmark_optimizer_async.py", Path(__file__),
                     ROOT/"tests/optimizer_qualification_cases.py",
                     ROOT/"tests/fixtures/optimizer_real_designs.json")}
    selected = args.case or list(CASE_IDS)
    evidence["selected_case_ids"] = selected
    evidence["full_matrix"] = set(selected) == set(CASE_IDS)
    evidence["timing_repetitions_sufficient"] = args.runs >= 5
    unknown = set(selected) - set(CASE_IDS)
    if unknown:
        evidence["blockers"].append({"error": f"Unknown cases: {sorted(unknown)}", "stage": "case selection"})
        save_evidence(args.output, evidence)
        return 1
    # Resolve every requested external fixture before starting any calculations.
    save_evidence(args.output, evidence)
    try:
        cases = [load_case(name, args.fixture_root) for name in selected]
    except Exception as exc:
        evidence["blockers"].append({"error": str(exc), "stage": "fixture verification"})
        save_evidence(args.output, evidence)
        return 1
    for case in cases:
        payloads = {}
        for allow_two in (False, True):
            mode = "two" if allow_two else "single"
            for route in (("import", "editor") if case.imported else ("editor",)):
                key = f"{case.name}/{mode}/{route}"
                record = dict(coverage=case.describe(), runs=[], cancellations=[], status="running")
                evidence["cases"][key] = record
                save_evidence(args.output, evidence)
                try:
                    if case.imported and route == "editor":
                        payloads[mode] = import_payload(app, case, allow_two)
                    kw = dict(payload=payloads.get(mode))
                    record["warmup"] = measure(app, case, allow_two, route, **kw)
                    for _ in range(args.runs):
                        record["runs"].append(measure(app, case, allow_two, route, **kw))
                        save_evidence(args.output, evidence)
                    for _ in range(args.runs):
                        record["cancellations"].append(measure(app, case, allow_two, route, cancel="early", **kw))
                        save_evidence(args.output, evidence)
                    if max(r["total_ms"] for r in record["runs"]) >= 1000:
                        for _ in range(args.runs):
                            record["cancellations"].append(measure(app, case, allow_two, route, cancel="activity", **kw))
                            save_evidence(args.output, evidence)
                    record["summary"] = summarize(record["runs"], record["cancellations"])
                    errors = sorted({r["validation_error"] for r in [record["warmup"]] + record["runs"] + record["cancellations"] if r.get("validation_error")})
                    if record["summary"]["max_gap_ms"] > 250 or record["summary"]["max_cancel_ms"] > 1000:
                        errors.append("Responsiveness gate exceeded (250 ms heartbeat / 1000 ms cancellation)")
                    if any(r.get("input_limitation") for r in record["runs"]):
                        errors.append(next(r["input_limitation"] for r in record["runs"] if r.get("input_limitation")))
                    if errors:
                        raise AssertionError("; ".join(errors))
                    record["status"] = "passed"
                except Exception as exc:
                    record["status"] = "blocked"
                    record["error"] = str(exc) or type(exc).__name__
                    evidence["blockers"].append({"case": key, "error": record["error"]})
                print(key, record["status"], record.get("summary", record.get("error")), flush=True)
                save_evidence(args.output, evidence)
        # Compare full ranks only for successful allocations in both modes.
        for route in (("import", "editor") if case.imported else ("editor",)):
            a, b = (evidence["cases"][f"{case.name}/{mode}/{route}"] for mode in ("single", "two"))
            if a["runs"] and b["runs"] and all("allocation" in r["runs"][0] for r in (a,b)):
                ra, rb = a["runs"][0]["allocation"], b["runs"][0]["allocation"]
                ranks = (ra.get("rank") or list(ra["selected_rank"].values()),
                         rb.get("rank") or list(rb["selected_rank"].values()))
                if tuple(ranks[1]) > tuple(ranks[0]):
                    evidence["blockers"].append({"case": case.name, "error": "Two-stock allocation worsened single-stock rank"})
        if case.name == "dense_384_10":
            key = f"{case.name}/two/automatic"
            record = dict(coverage=case.describe(), runs=[], cancellations=[], status="running")
            evidence["cases"][key] = record
            try:
                payload = payloads.get("two") or import_payload(app, case, True)
                record["warmup"] = measure(app, case, True, "editor", payload=payload, automatic=True)
                record["runs"] = [measure(app, case, True, "editor", payload=payload, automatic=True) for _ in range(args.runs)]
                record["cancellations"] = [measure(app, case, True, "editor", payload=payload, automatic=True, cancel="early") for _ in range(args.runs)]
                record["summary"] = summarize(record["runs"], record["cancellations"])
                assert not any(r.get("validation_error") for r in record["runs"] + record["cancellations"]), "Automatic interaction correctness failed"
                assert record["summary"]["max_gap_ms"] <= 250 and record["summary"]["max_cancel_ms"] <= 1000
                record["status"] = "passed"
            except Exception as exc:
                record.update(status="blocked", error=str(exc) or type(exc).__name__)
                evidence["blockers"].append({"case":key,"error":record["error"]})
            save_evidence(args.output, evidence)
    evidence["complete"] = True
    evidence["qualified"] = not evidence["blockers"] and evidence["full_matrix"] and evidence["timing_repetitions_sufficient"]
    save_evidence(args.output, evidence)
    return 1 if evidence["blockers"] else 0
