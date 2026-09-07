"""Opt-in, no-hardware Qt responsiveness qualification. Writes external evidence."""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
import tests.conftest  # Explicit simulated test composition and Qt font setup.
from PySide6.QtCore import QTimer, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from OptimizationJobs import optimization_job_manager
from Model import ExperimentModel
from tests.test_stock_optimizer_performance import _dense_target_model, _bnext_model, _large_import_model
from tests.test_experiment_design_reagent_headtype_integration import _build_real_dialog
from View import ExperimentImportWizard


def four_targets():
    model = _dense_target_model()
    model.factors[0].options[0].targets = [0.5, 1, 5, 20]
    return model


def pump(app, predicate, timeout=120):
    deadline = time.monotonic() + timeout
    while not predicate():
        app.processEvents()
        if time.monotonic() > deadline:
            raise TimeoutError("Optimizer qualification exceeded its bounded timeout")
        time.sleep(0.001)


def prepare_editor(factory):
    editor = _build_real_dialog()
    model = factory()
    editor.model = model[0] if isinstance(model, tuple) else model
    editor.model.metadata["allow_two_stock_solutions"] = True
    editor._auto_timer.stop()
    editor._sync_controls_from_model(recompute=False)
    editor._load_factors_into_table()
    editor.auto_update_chk.setChecked(False)
    editor._auto_timer.stop()
    editor._mark_design_optimization_dirty()
    editor.show()
    QApplication.instance().processEvents()
    return editor


def measure(app, factory, *, cancel=False, automatic=False):
    editor = prepare_editor(factory)
    if automatic:
        editor.auto_update_chk.setChecked(True)
        editor._auto_timer.stop()
    outcomes, beats, phases = [], [], []
    editor.optimization_finished.connect(lambda ok, result: outcomes.append((ok, result)))
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: beats.append(time.monotonic()))
    timer.start()
    started = time.monotonic()
    beats.append(started)
    if automatic:
        editor._recompute_silent()
    else:
        editor._run_design_optimization_flow()
    snapshot = editor.model.capture_optimization_inputs()
    cancelled_at = []
    ui = getattr(editor, "_optimization_ui", None)
    if ui is not None:
        manager = optimization_job_manager()
        def phase(job_id, text):
            phases.append({"phase": text, "elapsed_ms": (time.monotonic() - started) * 1000})
            if cancel and not cancelled_at:
                cancelled_at.append(time.monotonic())
                ui.cancel()
        manager.phase_changed.connect(phase)
    try:
        pump(app, lambda: outcomes)
        ended = time.monotonic()
        beats.append(ended)
        timer.stop()
        if ui is not None:
            manager.phase_changed.disconnect(phase)
        elapsed_ms = (ended - started) * 1000
        gap_ms = max(b - a for a, b in zip(beats, beats[1:])) * 1000
        if cancel:
            assert cancelled_at and not outcomes[0][0], outcomes
            return {"cancel_ms": (ended - cancelled_at[0]) * 1000, "max_gap_ms": gap_ms}
        assert outcomes[0][0], outcomes
        if automatic and outcomes[0][1].get("optimizer_total_elapsed_ms", 0) >= 3000:
            assert editor._slow_auto_update_paused
            assert not editor.auto_update_chk.isChecked()
            assert not editor.slow_auto_update_notice.isHidden()
        baseline = ExperimentModel()
        baseline.restore_optimization_inputs(snapshot)
        baseline_started = time.monotonic()
        expected = baseline.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)
        baseline.generate_experiment()
        baseline_ms = (time.monotonic() - baseline_started) * 1000
        assert editor.model.plans_per_option == baseline.plans_per_option
        assert outcomes[0][1]["optimizer_selected_rank"] == expected["optimizer_selected_rank"]
        return {"total_ms": elapsed_ms, "synchronous_compute_ms": baseline_ms,
                "max_gap_ms": gap_ms, "phases": phases,
                "automatic": automatic, "auto_update_paused": editor._slow_auto_update_paused,
                "heartbeat_ms": [(beat - started) * 1000 for beat in beats],
                "rank": outcomes[0][1]["optimizer_selected_rank"]}
    finally:
        timer.stop()
        optimization_job_manager().cancel()
        pump(app, lambda: not optimization_job_manager().busy)
        editor._allow_close_without_prompt = True
        editor.close()
        editor.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


def measure_automatic(app, factory, *, cancel=False):
    return measure(app, factory, cancel=cancel, automatic=True)


def measure_import(app, factory, *, cancel=False):
    model = factory()
    model = model[0] if isinstance(model, tuple) else model
    rows = [spec["reaction"] for spec in model._iter_reaction_run_specs()]
    data = {}
    stocks = {}
    for factor in model.factors:
        option = factor.options[0]
        data[f"[{factor.name}] {option.units}"] = [row.get((factor.name, None), 0) for row in rows]
        stocks[factor.name] = option.max_stock_conc or 5000.0
    wizard = ExperimentImportWizard(
        model, printed_volume_nL=model.metadata["target_reaction_volume_nL"],
        final_volume_nL=model.metadata["final_reaction_volume_nL"], allow_two=True,
    )
    wizard.load_design_dataframe(pd.DataFrame(data))
    wizard._manual_max_stock_by_reagent = stocks
    wizard.show()
    app.processEvents()
    results, beats, cancelled_at, phases = [], [], [], []
    wizard.optimization_finished.connect(lambda *args: results.append(args))
    manager = optimization_job_manager()
    def phase(job_id, text):
        phases.append({"phase": text, "elapsed_ms": (time.monotonic() - started) * 1000})
        if cancel and not cancelled_at:
            cancelled_at.append(time.monotonic())
            wizard._optimization_ui.cancel()
    manager.phase_changed.connect(phase)
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: beats.append(time.monotonic()))
    timer.start()
    started = time.monotonic()
    beats.append(started)
    try:
        wizard._recompute_report()
        pump(app, lambda: results)
        ended = time.monotonic()
        beats.append(ended)
        timer.stop()
        gap = max(b - a for a, b in zip(beats, beats[1:])) * 1000
        if cancel:
            assert cancelled_at and not results[0][0]
            return {"cancel_ms": (ended - cancelled_at[0]) * 1000, "max_gap_ms": gap}
        assert results[0][0], results
        baseline_start = time.monotonic()
        expected = model.build_import_feasibility_report(**wizard._feasibility_job_options())
        baseline_ms = (time.monotonic() - baseline_start) * 1000
        assert wizard.report["stock_rows"] == expected["stock_rows"]
        return {"total_ms": (ended - started) * 1000, "synchronous_compute_ms": baseline_ms,
                "max_gap_ms": gap, "phases": phases,
                "heartbeat_ms": [(b - started) * 1000 for b in beats]}
    finally:
        timer.stop()
        manager.phase_changed.disconnect(phase)
        manager.cancel()
        pump(app, lambda: not manager.busy)
        wizard.close()
        wizard.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.is_relative_to(ROOT):
        parser.error("Evidence must be outside the repository")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    results = {}
    try:
        workloads = (
            ("88_rows", lambda: _bnext_model(budget_nl=300, relax_stock_bounds=True)),
            ("384_rows", _large_import_model),
            ("four_targets", four_targets), ("dense_17", _dense_target_model),
        )
        for name, factory, measurement in (
            [(name, factory, measure) for name, factory in workloads]
            + [("import_" + name, factory, measure_import) for name, factory in workloads]
            + [("automatic_dense_17", _dense_target_model, measure_automatic)]
        ):
            measurement(app, factory)
            runs = [measurement(app, factory) for _ in range(args.runs)]
            cancellations = [measurement(app, factory, cancel=True) for _ in range(args.runs)]
            summary = {
                "median_ms": statistics.median(r["total_ms"] for r in runs),
                "max_ms": max(r["total_ms"] for r in runs),
                "synchronous_median_ms": statistics.median(r["synchronous_compute_ms"] for r in runs),
                "max_gap_ms": max(r["max_gap_ms"] for r in runs + cancellations),
                "max_cancel_ms": max(r["cancel_ms"] for r in cancellations),
            }
            summary["passed"] = summary["max_gap_ms"] <= 250 and summary["max_cancel_ms"] <= 1000
            results[name] = {"summary": summary, "runs": runs, "cancellations": cancellations}
            print(name, json.dumps(summary), flush=True)
    finally:
        stopped = []
        optimization_job_manager().shutdown(lambda: stopped.append(True))
        pump(app, lambda: stopped)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if len(results) == 9 and all(r["summary"]["passed"] for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
