"""External native build and scoped adapter for the opt-in experiment only."""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import sys


def build_native(directory):
    from setuptools import Distribution, Extension
    from tests.optimizer_qualification_cases import require_external
    directory = require_external(directory)
    directory.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name("native_optimizer_kernel.c")
    flags = ["/O2", "/fp:strict"] if os.name == "nt" else ["-O3", "-ffp-contract=off", "-fno-fast-math"]
    distribution = Distribution({"name": "optimizer-native-experiment", "ext_modules": [
        Extension("_optimizer_native_experiment", [str(source)], extra_compile_args=flags)]})
    command = distribution.get_command_obj("build_ext")
    command.build_lib = str(directory)
    command.build_temp = str(directory / "objects")
    command.ensure_finalized()
    command.run()
    path = Path(command.get_ext_fullpath("_optimizer_native_experiment"))
    evidence = dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    binary_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    binary=str(path), python=sys.version, platform=platform.platform(),
                    flags=flags, compiler=command.compiler.compiler_type)
    (directory / "build.json").write_text(json.dumps(evidence, indent=2))
    spec = importlib.util.spec_from_file_location("_optimizer_native_experiment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, evidence


def make_solver(original, native, telemetry=None, entered=None):
    telemetry = telemetry if telemetry is not None else {}

    def solve(self, t_add, d1, d2, *, max_total_drops=None, deadline_reached=None, diagnostics=None):
        telemetry["calls"] = telemetry.get("calls", 0) + 1
        if entered is not None and telemetry["calls"] >= 1000:
            entered.set()
        # Preserve arbitrary callback semantics exactly; benchmark optimizer calls
        # do not supply this legacy callback. Out-of-range data uses the reference.
        if (deadline_reached is not None or not all(math.isfinite(x) for x in (t_add, d1, d2))
                or d1 <= 0 or d2 <= 0 or abs(t_add / d1) > 1e9 or abs(t_add / d2) > 1e9
                or (max_total_drops is not None and abs(int(max_total_drops)) > 1e9)):
            telemetry["fallback_calls"] = telemetry.get("fallback_calls", 0) + 1
            return original(self, t_add, d1, d2, max_total_drops=max_total_drops,
                            deadline_reached=deadline_reached, diagnostics=diagnostics)
        limit = -1 if max_total_drops is None else max(0, int(max_total_drops))
        a_max = int(round(t_add / d1)) + 6
        if limit >= 0:
            a_max = min(a_max, limit)
        if a_max + 1 > 1000000000:
            telemetry["fallback_calls"] = telemetry.get("fallback_calls", 0) + 1
            return original(self, t_add, d1, d2, max_total_drops=max_total_drops,
                            diagnostics=diagnostics)
        best = (0, 0, float("inf"))
        control = getattr(self, "_optimization_control", None)
        for start in range(0, max(0, a_max + 1), 256):
            if control is not None:
                control.check()
            stop = min(start + 256, a_max + 1)
            best = native.scan(t_add, d1, d2, start, stop, limit, *best)
            if diagnostics is not None:
                diagnostics["two_stock_solver_iterations"] = int(diagnostics.get("two_stock_solver_iterations", 0)) + stop - start
            telemetry["batches"] = telemetry.get("batches", 0) + 1
            if control is not None:
                control.check()
        return best
    return solve


@contextmanager
def backend(native=None, entered=None):
    from Model import ExperimentModel
    original = ExperimentModel._nearest_two_stock
    telemetry = {}
    if native is not None:
        replacement = make_solver(original, native, telemetry, entered)
    else:
        def replacement(self, *args, **kwargs):
            telemetry["calls"] = telemetry.get("calls", 0) + 1
            if entered is not None and telemetry["calls"] >= 1000:
                entered.set()
            return original(self, *args, **kwargs)
    ExperimentModel._nearest_two_stock = replacement
    try:
        yield telemetry
    finally:
        ExperimentModel._nearest_two_stock = original
