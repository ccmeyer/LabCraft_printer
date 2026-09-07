"""Opt-in numerical acceleration experiment; never imported by the application."""
import argparse
import cProfile
import json
import os
from pathlib import Path
import pstats
import sys
import time
import copy
import hashlib
import statistics
import subprocess
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tests.conftest  # Simulated dependencies, no hardware composition.
from tests.test_stock_optimizer_performance import _dense_target_model
from tests.optimizer_qualification_cases import load_case, populate_model, require_external, REFINEMENT
from tests.optimizer_qualification_cases import allocation_evidence, assert_physical_allocation
from tools.optimizer_native_adapter import build_native, backend
from tools.optimizer_realistic_qualification import assert_outputs_equal
from Model import ExperimentModel
from OptimizationJobs import OptimizationJobManager, OptimizationRequest, input_fingerprint
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


def stable_result(result):
    result = copy.deepcopy(result)
    for key in list(result):
        if key.endswith("_ms") or key == "stock_allocation_time_budget_exceeded":
            del result[key]
    for key, issues in list(result.get("issues_by_key", {}).items()):
        issues = [item for item in issues if item.get("code") != "stock_allocation_performance_target_exceeded"]
        if issues:
            result["issues_by_key"][key] = issues
        else:
            del result["issues_by_key"][key]
    def strip_timing(value):
        if isinstance(value, dict):
            return {key: strip_timing(item) for key, item in value.items()
                    if not (isinstance(key, str) and (key.endswith("_ms") or key == "stock_allocation_time_budget_exceeded"))}
        if isinstance(value, list):
            return [strip_timing(item) for item in value]
        if isinstance(value, tuple):
            return tuple(strip_timing(item) for item in value)
        return value
    return strip_timing(result)


def workload(name):
    if name == "dense17":
        return _dense_target_model()
    return populate_model(load_case("dense_384_10"), True)


def compute(model):
    result = model.optimize_stock_solutions(**REFINEMENT, allow_two=True)
    if not result.get("best"):
        raise AssertionError("Workload did not produce a feasible allocation")
    model.validate_optimization_allocation(result)
    model.generate_experiment()
    return result


def profile(name, output):
    model = workload(name)
    profiler = cProfile.Profile()
    start = time.perf_counter()
    profiler.runcall(compute, model)
    profiler.dump_stats(str(output / (name + ".prof")))
    stats = pstats.Stats(profiler)
    rows = [dict(file=key[0], line=key[1], function=key[2], calls=value[1],
                 self_seconds=value[2], cumulative_seconds=value[3])
            for key, value in stats.stats.items()]
    evidence = dict(case=name, profiled_seconds=time.perf_counter() - start,
                    revision=subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
                    model_sha256=hashlib.sha256((ROOT / "FreeRTOS-interface/Model.py").read_bytes()).hexdigest(),
                    by_self=sorted(rows, key=lambda r: -r["self_seconds"])[:40],
                    by_cumulative=sorted(rows, key=lambda r: -r["cumulative_seconds"])[:40])
    (output / (name + "-profile.json")).write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence["by_self"][:12]), flush=True)


def pump(app, predicate, seconds=900):
    deadline = time.monotonic() + seconds
    while not predicate():
        app.processEvents()
        if time.monotonic() > deadline:
            raise TimeoutError("Experiment exceeded cooperative watchdog")
        time.sleep(.001)


def worker_call(app, name, native, cancel=None):
    owner = workload(name)
    before_inputs = owner.capture_optimization_inputs()
    before_outputs = owner.capture_optimization_outputs()
    manager = OptimizationJobManager()
    outcomes, beats, phases, cancelled = [], [], [], []
    entered = threading.Event()
    timer = QTimer()
    timer.setInterval(20)
    start = time.perf_counter()

    def request_cancel():
        if not cancelled:
            cancelled.append(time.perf_counter())
            manager.cancel()

    def beat():
        beats.append(time.perf_counter())
        if cancel == "solver" and entered.is_set():
            request_cancel()

    def phase(job_id, text):
        phases.append(dict(phase=text, elapsed_ms=(time.perf_counter()-start)*1000))
        if cancel == "early":
            request_cancel()

    def complete(outcome):
        try:
            assert input_fingerprint(owner.capture_optimization_inputs()) == input_fingerprint(before_inputs)
            if outcome.status == "succeeded":
                owner.install_optimization_outputs(outcome.computed, input_fingerprint(before_inputs))
        except Exception as exc:
            outcome.status, outcome.error = "failed", repr(exc)
        outcomes.append(outcome)

    manager.phase_changed.connect(phase)
    timer.timeout.connect(beat)
    timer.start()
    beats.append(start)
    with backend(native, entered) as telemetry:
        try:
            request = OptimizationRequest(owner.capture_optimization_inputs(), options={"allow_two": True})
            assert manager.submit(owner, request, complete, phase_changed=lambda text: None)
            pump(app, lambda: outcomes)
            end = time.perf_counter()
            beats.append(end)
            assert len(outcomes) == 1
            outcome = outcomes[0]
            if cancel:
                assert input_fingerprint(owner.capture_optimization_inputs()) == input_fingerprint(before_inputs)
                assert cancelled and outcome.status == "cancelled", outcome.error
                assert_outputs_equal(before_outputs, owner.capture_optimization_outputs())
            else:
                assert outcome.status == "succeeded", outcome.error
            evidence = dict(total_ms=(end-start)*1000, max_gap_ms=max(b-a for a,b in zip(beats, beats[1:]))*1000,
                            phases=phases, status=outcome.status, telemetry=dict(telemetry))
            if cancel:
                evidence.update(cancel_phase=cancel, cancel_ms=(end-cancelled[0])*1000,
                                solver_activity_observed=entered.is_set(), unchanged_outputs=True)
            return owner, outcome.result, evidence
        finally:
            timer.stop()
            manager.cancel()
            stopped = []
            manager.shutdown(lambda: stopped.append(True))
            # Never destroy/terminate a live QThread. If cooperative cancellation
            # is broken, leave the process alive for its owning supervisor.
            try:
                pump(app, lambda: stopped, seconds=10)
            except TimeoutError:
                print("BLOCKED: worker did not unwind; preserving live thread", flush=True)
                while not stopped:
                    app.processEvents()
                    time.sleep(.01)


def validate_equal(reference, actual):
    expected_model, expected_result = reference
    model, result = actual
    expected, actual = stable_result(expected_result), stable_result(result)
    differences = {key: (expected.get(key), actual.get(key)) for key in set(expected) | set(actual)
                   if expected.get(key) != actual.get(key)}
    assert not differences, f"Non-timing result or work counters changed: {differences!r}"
    assert_outputs_equal(expected_model.capture_optimization_outputs(), model.capture_optimization_outputs())
    assert (expected_model.export_stock_allocation_reuse_payload(expected_result)["plan_fingerprint"] ==
            model.export_stock_allocation_reuse_payload(result)["plan_fingerprint"])


def run_experiment(args, output):
    native, build = build_native(output / "build")
    app = QApplication.instance() or QApplication([])
    evidence = dict(schema_version=1, revision=subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
                    source_hashes={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                   [Path(__file__), ROOT / "tools/optimizer_native_adapter.py", ROOT / "tools/native_optimizer_kernel.c", ROOT / "FreeRTOS-interface/Model.py"]},
                    build=build, repetitions=args.runs, cases={}, complete=False,
                    scope="Model complete-call and real Qt worker publication; excludes editor tables/import parsing")
    def save():
        (output / "results.json").write_text(json.dumps(evidence, indent=2))
    save()
    try:
        for name in args.case or ("dense17", "dense_384_10"):
            rows = evidence["cases"][name] = dict(python=[], native=[], cancellation=[])
            reference_model = workload(name)
            reference_result = compute(reference_model)
            reference = reference_model, reference_result
            rows["allocation"] = allocation_evidence(*reference)
            rows["plan_fingerprint"] = reference_model.export_stock_allocation_reuse_payload(reference_result)["plan_fingerprint"]
            rows["composition"] = load_case(name).describe() if name != "dense17" else {"reagents": 1, "targets": 17, "rows": 17}
            # Warm-up plus measured runs, alternating backend order to reduce drift.
            for trial in range(args.runs + 1):
                for label in (("python", "native") if trial % 2 == 0 else ("native", "python")):
                    module = native if label == "native" else None
                    model = workload(name)
                    with backend(module) as telemetry:
                        start = time.perf_counter()
                        result = compute(model)
                        elapsed = (time.perf_counter()-start)*1000
                        counters = dict(telemetry)
                    validate_equal(reference, (model, result))
                    assert not counters.get("fallback_calls"), "Native experiment unexpectedly used Python fallback"
                    if name != "dense17":
                        assert_physical_allocation(load_case(name), model)
                    owner, result, measurement = worker_call(app, name, module)
                    validate_equal(reference, (owner, result))
                    measurement.update(synchronous_ms=elapsed, synchronous_telemetry=counters, identical=True)
                    if trial:
                        rows[label].append(measurement)
                    else:
                        rows[label + "_warmup"] = measurement
                    save()
                    print(f"{name} {label} trial={trial} sync={elapsed:.0f}ms worker={measurement['total_ms']:.0f}ms identical", flush=True)
            for label, module in (("python", None), ("native", native)):
                for phase in ("early", "solver"):
                    for trial in range(args.runs):
                        _, _, measurement = worker_call(app, name, module, cancel=phase)
                        measurement.update(backend=label, trial=trial)
                        rows["cancellation"].append(measurement)
                        save()
            rows["summary"] = {label: dict(synchronous_median_ms=statistics.median(r["synchronous_ms"] for r in rows[label]),
                                                   synchronous_max_ms=max(r["synchronous_ms"] for r in rows[label]),
                                                   worker_median_ms=statistics.median(r["total_ms"] for r in rows[label]),
                                                   worker_max_ms=max(r["total_ms"] for r in rows[label]),
                                                   max_gap_ms=max(r["max_gap_ms"] for r in rows[label]),
                                                   max_cancel_ms=max(r["cancel_ms"] for r in rows["cancellation"] if r["backend"] == label))
                               for label in ("python", "native")}
            rows["gates_passed"] = all(s["max_gap_ms"] <= 250 and s["max_cancel_ms"] <= 1000 for s in rows["summary"].values())
            save()
        evidence["complete"] = True
    except BaseException as exc:
        evidence["error"] = repr(exc)
        raise
    finally:
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=("dense17", "dense_384_10"), action="append")
    parser.add_argument("--mode", choices=("profile", "compare"), default="profile")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    output = require_external(args.output)
    if output.exists() and any(output.iterdir()):
        parser.error("Use a fresh empty external output directory; previous evidence is preserved")
    output.mkdir(parents=True, exist_ok=True)
    if args.runs < 1:
        parser.error("--runs must be positive")
    if args.mode == "profile":
        for name in args.case or ("dense17", "dense_384_10"):
            profile(name, output)
    else:
        run_experiment(args, output)


if __name__ == "__main__":
    main()
