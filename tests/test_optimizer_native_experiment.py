"""Small differential gate for the optional native experiment (no CI compiler required)."""
import math
import os
import random
import threading
from types import SimpleNamespace

import pytest

from Model import ExperimentModel, _StockAllocationDeadlineReached
from OptimizationJobs import OptimizationCancelled
from tools.optimizer_native_adapter import backend, build_native, make_solver


def test_comparison_ignores_nested_timing_but_retains_work():
    from tools.experiment_optimizer_native import stable_result
    def result(ms, work):
        return {"issues_by_key": {("x", None): [{"code": "bounded_stock_allocation_search", "elapsed_ms": ms, "work": work}]}}
    assert stable_result(result(1, 7)) == stable_result(result(9, 7))
    assert stable_result(result(1, 7)) != stable_result(result(1, 8))


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    if os.environ.get("LABCRAFT_NATIVE_EXPERIMENT") != "1":
        pytest.skip("Opt-in compiler lane: LABCRAFT_NATIVE_EXPERIMENT=1")
    return build_native(tmp_path_factory.mktemp("native-build"))[0]


def test_numerical_equivalence_and_iteration_counts(native):
    original = ExperimentModel._nearest_two_stock
    telemetry = {}
    solver = make_solver(original, native, telemetry)
    rng = random.Random(29171)
    inputs = [(t, a, b, n) for t in (0., -.1, .5, 1., 5., 20., 21.)
              for a,b in ((.1,.2),(.3,.3),(1.,2.),(.5,1e-5)) for n in (0,1,24,100,None)]
    inputs += [(rng.random()*30, 10**rng.uniform(-1,1), 10**rng.uniform(-2,1), rng.randrange(101)) for _ in range(3000)]
    for t, a, b, n in inputs:
        expected_counts, actual_counts = {}, {}
        expected = original(None, t, a, b, max_total_drops=n, diagnostics=expected_counts)
        actual = solver(None, t, a, b, max_total_drops=n, diagnostics=actual_counts)
        assert expected == actual, (t,a,b,n,expected,actual)
        assert expected_counts == actual_counts
    assert not telemetry.get("fallback_calls")


def test_callback_fallback_preserves_exact_boundary(native):
    calls = []
    solver = make_solver(ExperimentModel._nearest_two_stock, native)
    def stop():
        calls.append(True)
        return len(calls) == 3
    diagnostics = {}
    with pytest.raises(_StockAllocationDeadlineReached):
        solver(None, 5., .1, .2, deadline_reached=stop, diagnostics=diagnostics)
    assert len(calls) == 3
    assert diagnostics["two_stock_solver_iterations"] == 2


def test_cancellation_after_bounded_native_batch(native):
    class Control:
        def __init__(self):
            self.calls = 0
        def check(self):
            self.calls += 1
            if self.calls == 2:
                raise OptimizationCancelled()
    solver = make_solver(ExperimentModel._nearest_two_stock, native)
    diagnostics = {}
    with pytest.raises(OptimizationCancelled):
        solver(SimpleNamespace(_optimization_control=Control()), 1000., .1, .2, diagnostics=diagnostics)
    assert diagnostics["two_stock_solver_iterations"] == 256


def test_native_validation_and_adapter_restoration(native):
    for stop in (257, -1, 1000000001):
        with pytest.raises(ValueError):
            native.scan(1., .1, .2, 0, stop, -1, 0, 0, math.inf)
    original = ExperimentModel._nearest_two_stock
    with pytest.raises(RuntimeError):
        with backend(native):
            assert ExperimentModel._nearest_two_stock is not original
            raise RuntimeError("experiment failed")
    assert ExperimentModel._nearest_two_stock is original


def test_kernel_callable_from_worker_thread(native):
    # Thread interoperability; timed heartbeat/cancellation gates live in the harness.
    solver = make_solver(ExperimentModel._nearest_two_stock, native)
    done = threading.Event()
    result = []
    def work():
        result.append(solver(None, 20., .1, .2, max_total_drops=100))
        done.set()
    worker = threading.Thread(target=work)
    worker.start()
    assert done.wait(5)
    worker.join()
    assert result == [ExperimentModel._nearest_two_stock(None, 20., .1, .2, max_total_drops=100)]


@pytest.mark.parametrize("compiled", [False, True])
@pytest.mark.parametrize("phase", ["early", "solver"])
def test_experiment_cancel_route(qapp, native, compiled, phase):
    from tools.experiment_optimizer_native import worker_call
    _, _, evidence = worker_call(qapp, "dense17", native if compiled else None, cancel=phase)
    assert evidence["status"] == "cancelled"
    assert evidence["unchanged_outputs"]
    assert evidence["phases"]
    if phase == "solver":
        assert evidence["solver_activity_observed"]
