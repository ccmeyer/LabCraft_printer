"""Bounded, observational memory qualification; no optimizer/GC policy changes."""
import ctypes
import gc
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import threading
import time

MIB = 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS = (("real_68", False), ("real_68", True), ("dense_384_10", True))


@lru_cache(maxsize=1)
def _windows_api():
    # ctypes caches POINTER types globally. Recreating these Structures on each
    # 100 ms sample would retain new types indefinitely in the supervisor.
    from ctypes import wintypes as w
    class Counters(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("faults", w.DWORD)] + [
            (n, ctypes.c_size_t) for n in ("peak_rss", "rss", "peak_paged", "paged",
            "peak_nonpaged", "nonpaged", "commit", "peak_commit", "private")]
    class Status(ctypes.Structure):
        _fields_ = [("length", w.DWORD), ("load", w.DWORD)] + [
            (n, ctypes.c_ulonglong) for n in ("total", "available", "total_page",
            "available_page", "total_virtual", "available_virtual", "extended")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(Counters), w.DWORD]
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(Status)]
    return kernel, psapi, Counters, Status


def memory_sample(pid):
    """OS counters, sampled outside the Qt process/GIL; no extra dependency."""
    if sys.platform == "win32":
        kernel, psapi, Counters, Status = _windows_api()
        handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            raise OSError(ctypes.get_last_error(), "Cannot inspect owned process memory")
        try:
            counters = Counters(); counters.cb = ctypes.sizeof(counters)
            status = Status(); status.length = ctypes.sizeof(status)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
                raise ctypes.WinError(ctypes.get_last_error())
            return dict(rss_bytes=counters.rss, peak_rss_bytes=counters.peak_rss,
                        private_bytes=counters.private, swap_bytes=None,
                        total_bytes=status.total, available_bytes=status.available)
        finally:
            kernel.CloseHandle(handle)
    if sys.platform.startswith("linux"):
        def fields(path):
            values = {}
            for line in Path(path).read_text().splitlines():
                key, _, value = line.partition(":")
                if value.strip().endswith(" kB"):
                    values[key] = int(value.split()[0]) * 1024
            return values
        process = fields(f"/proc/{pid}/status")
        host = fields("/proc/meminfo")
        return dict(rss_bytes=process["VmRSS"], peak_rss_bytes=process["VmHWM"],
                    private_bytes=None, swap_bytes=process.get("VmSwap", 0),
                    total_bytes=host["MemTotal"], available_bytes=host["MemAvailable"])
    raise RuntimeError("Memory qualification supports Windows and Linux only")


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    for attempt in range(50):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(.01)


def trend(values, *, absolute_tolerance, slope_tolerance):
    """A bounded growth screen, not a claim that an application is leak-free."""
    if len(values) < 6:
        return dict(status="inconclusive", samples=len(values))
    first, last = statistics.median(values[:3]), statistics.median(values[-3:])
    slopes = [(b-a)/(j-i) for i, a in enumerate(values) for j, b in enumerate(values) if j > i]
    slope = statistics.median(slopes)
    allowance = max(absolute_tolerance, first * .05)
    delta = last-first
    status = "growth_requires_review" if delta > allowance and slope > slope_tolerance else (
        "inconclusive" if delta > allowance else "stable_within_bound")
    return dict(status=status, samples=len(values), first_median=first, last_median=last,
                delta=delta, allowance=allowance, median_slope_per_round=slope)


def assess(endpoints):
    measured = [e for e in endpoints if not e["warmup"]]
    return dict(rss=trend([e["rss_bytes"] for e in measured],
                         absolute_tolerance=32*MIB, slope_tolerance=2*MIB),
                python_blocks=trend([e["python_allocated_blocks"] for e in measured],
                                    absolute_tolerance=10000, slope_tolerance=1000))


def supervise(args, command):
    """Own one child. Sample it externally; cancel before process escalation."""
    output = Path(args.output)
    cancel = output.with_suffix(".cancel")
    if any(p.exists() for p in (output, cancel, output.with_suffix(".samples.jsonl"),
                                output.with_suffix(".process.json"), output.with_suffix(".worker.log"))):
        raise ValueError("Use a new external output path; existing evidence is preserved")
    output.parent.mkdir(parents=True, exist_ok=True)
    admission = memory_sample(os.getpid())
    floor = max(256*MIB, admission["total_bytes"] * .10)
    if admission["available_bytes"] < floor:
        write_json(output, dict(status="failed", complete=False, error="Insufficient memory headroom before launch", admission=admission))
        raise RuntimeError("Insufficient available memory for safe qualification admission")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen")
    cache = output.with_suffix(".runtime"); cache.mkdir()
    env.update(MPLCONFIGDIR=str(cache/"mpl"), XDG_CACHE_HOME=str(cache/"cache"),
               XDG_CONFIG_HOME=str(cache/"config"))
    kw = dict(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else dict(start_new_session=True)
    cleanup, reason, count = [], None, 0
    peak, sampled_peak, minimum, previous = 0, 0, admission["available_bytes"], None
    max_sample_gap, max_swap = 0., 0
    started = time.monotonic()
    handlers = {}
    def interrupt(*unused):
        raise KeyboardInterrupt()
    with output.with_suffix(".worker.log").open("w", encoding="utf-8") as log, output.with_suffix(".samples.jsonl").open("w", encoding="utf-8") as samples:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, **kw)
        try:
            for name in ("SIGTERM", "SIGHUP"):
                if hasattr(signal, name):
                    sig = getattr(signal, name); handlers[sig] = signal.signal(sig, interrupt)
            while process.poll() is None:
                try:
                    sample = memory_sample(process.pid)
                except (OSError, KeyError):
                    if process.poll() is not None:
                        break
                    raise
                now = time.monotonic()
                if previous is not None:
                    max_sample_gap = max(max_sample_gap, now-previous)
                previous = now
                sample["elapsed_seconds"] = now-started
                samples.write(json.dumps(sample)+"\n"); samples.flush(); count += 1
                peak = max(peak, sample["peak_rss_bytes"])
                sampled_peak = max(sampled_peak, sample["rss_bytes"])
                minimum = min(minimum, sample["available_bytes"])
                max_swap = max(max_swap, sample["swap_bytes"] or 0)
                if sample["available_bytes"] < floor:
                    reason = "Available memory crossed the headroom floor"
                    break
                if now-started > args.max_seconds:
                    reason = "Bounded campaign timeout"
                    break
                time.sleep(.1)
        except BaseException as exc:
            reason = f"Supervisor interrupted or failed: {type(exc).__name__}: {exc}"
        finally:
            if process.poll() is None:
                cancel.write_text(reason or "Cancel owned memory test", encoding="utf-8")
                cleanup.append("cooperative cancellation requested")
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    if os.name == "nt": process.terminate()
                    else: os.killpg(process.pid, signal.SIGTERM)
                    cleanup.append("terminated owned process after cancellation grace")
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        if os.name == "nt": process.kill()
                        else: os.killpg(process.pid, signal.SIGKILL)
                        cleanup.append("killed owned process after termination grace")
                        process.wait(timeout=5)
            for sig, handler in handlers.items(): signal.signal(sig, handler)
            record = dict(pid=process.pid, returncode=process.poll(), cleanup=cleanup, stop_reason=reason,
                          owned_process_exited=process.poll() is not None, elapsed_seconds=time.monotonic()-started,
                          samples=count, peak_rss_bytes=peak, sampled_peak_rss_bytes=sampled_peak,
                          minimum_available_bytes=minimum, total_bytes=admission["total_bytes"],
                          headroom_floor_bytes=floor, max_sample_gap_seconds=max_sample_gap, max_process_swap_bytes=max_swap)
            write_json(output.with_suffix(".process.json"), record)
    evidence = json.loads(output.read_text()) if output.exists() else {}
    evidence["supervisor"] = record
    expected_review = process.returncode == 1 and evidence.get("complete") and evidence.get("status") == "review_required"
    if reason or (process.returncode and not expected_review) or not evidence.get("complete"):
        evidence["status"] = "failed" if reason or process.returncode not in (0, 2) else "inconclusive"
    write_json(output, evidence)
    return 0 if evidence.get("status") == "passed" else 2 if evidence.get("status") == "inconclusive" else 1


def state_digest(model):
    """Canonical values, excluding object identity and diagnostic timings."""
    import pandas as pd
    def normalize(value):
        if isinstance(value, pd.DataFrame):
            return ("dataframe", list(map(str, value.columns)), list(map(str, value.dtypes)),
                    normalize(value.index.tolist()), normalize(value.to_numpy().tolist()))
        if isinstance(value, dict):
            return [(repr(k), normalize(v)) for k, v in sorted(value.items(), key=lambda kv: repr(kv[0]))]
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        if hasattr(value, "item"):
            return normalize(value.item())
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise TypeError(f"Unexpected computation output: {type(value).__name__}")
    state = model.capture_optimization_outputs()
    state["calibration_history"] = model.applied_imaging_calibrations
    return hashlib.sha256(json.dumps(normalize(state), allow_nan=True).encode()).hexdigest()


def run_job(app, editor, action, *, cancel_phase=None, close_active=False, stop=lambda: False):
    from OptimizationJobs import optimization_job_manager
    from tools.optimizer_realistic_qualification import finish_input_events
    manager = optimization_job_manager()
    terminal, cancelled, phases = [], [], []
    before = state_digest(editor.model) if cancel_phase else None
    started = time.monotonic()
    def finished(ok, result): terminal.append((ok, result, time.monotonic()))
    def phase(job_id, name):
        phases.append(name)
        if cancel_phase == name and not cancelled:
            cancelled.append(time.monotonic())
            if close_active:
                editor._allow_close_without_prompt = True
                editor.close()
            else:
                editor._optimization_ui.cancel()
    editor.optimization_finished.connect(finished)
    manager.phase_changed.connect(phase)
    try:
        action()
        deadline = time.monotonic()+900
        while not terminal or manager.busy or (close_active and editor.isVisible()):
            app.processEvents()
            if stop() or time.monotonic() > deadline:
                manager.cancel(editor)
                raise RuntimeError("Memory campaign cancelled or interaction timed out")
            time.sleep(.001)
        finish_input_events()
        assert len(terminal) == 1, "Expected exactly one terminal notification"
        assert not editor._qualification_dialog_errors, editor._qualification_dialog_errors
        result = terminal[0][1]
        if cancel_phase:
            assert cancelled, f"Cancellation phase never observed: {cancel_phase}"
            assert not terminal[0][0], "Cancelled computation published success"
            assert state_digest(editor.model) == before, "Cancellation changed committed state/history"
        else:
            assert terminal[0][0], result
        return dict(duration_seconds=terminal[0][2]-started, phases=phases,
                    cancel_ms=(terminal[0][2]-cancelled[0])*1000 if cancelled else None,
                    result=result if not cancel_phase else None)
    finally:
        editor.optimization_finished.disconnect(finished)
        manager.phase_changed.disconnect(phase)


def run_session(app, args, scenarios=None):
    """Keep one app/worker; reuse each editor, then close while active each round."""
    import copy
    import weakref
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid
    from OptimizationJobs import optimization_job_manager
    from tests.optimizer_qualification_cases import load_case, allocation_evidence, assert_physical_allocation
    from tools.optimizer_realistic_qualification import import_payload, new_editor, close_owner, finish_input_events
    output = Path(args.output)
    cancelled = output.with_suffix(".cancel")
    manager = optimization_job_manager()
    selected = scenarios or DEFAULT_SCENARIOS
    watcher_stopped = threading.Event()
    def watch_cancel():
        while not watcher_stopped.wait(.1):
            if cancelled.exists():
                manager.cancel()  # Sets the job's thread-safe Event; no UI calls.
    watcher = threading.Thread(target=watch_cancel, daemon=True)
    watcher.start()
    evidence = dict(schema_version=1, revision=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    worktree_status=subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True),
                    source_files={str(path.relative_to(ROOT)): hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
                                  for path in (Path(__file__), ROOT/"tools/benchmark_optimizer_memory.py",
                                               ROOT/"tests/optimizer_qualification_cases.py", ROOT/"tests/fixtures/optimizer_real_designs.json")},
                    pid=os.getpid(), warmups=args.warmups, rounds=args.rounds, complete=False, status="running",
                    endpoints=[], interactions=[], scenarios=[], gc_policy=dict(enabled=gc.isenabled(), thresholds=gc.get_threshold()),
                    memory_policy="No forced collection, tracing, allocator trimming or GC tuning; fixed cached input payloads only")
    baselines, cases, payloads, owners = {}, {}, {}, []
    editor = None
    def persist(): write_json(output, evidence)
    def stop(): return cancelled.exists()
    try:
        persist()
        for name, two in selected:
            case = cases.setdefault(name, load_case(name, args.fixture_root))
            payloads[(name, two)] = import_payload(app, case, two)
            evidence["scenarios"].append(dict(case=name, allow_two=two, coverage=case.describe()))
            if stop(): raise RuntimeError("Campaign cancelled during fixture preparation")
        worker_identity = id(manager._worker)
        for round_index in range(args.warmups+args.rounds):
            warmup = round_index < args.warmups
            for name, two in selected:
                case = cases[name]
                editor = new_editor(case, two)
                owners.append(weakref.ref(editor))
                apply = run_job(app, editor, lambda: editor._apply_uploaded_design_payload(copy.deepcopy(payloads[(name, two)])), stop=stop)
                del apply
                if not case.hashes:
                    for index, reagent in enumerate(case.reagents):
                        editor._reagent_cell_widget(index, editor.COL_DROPLET).setValue(reagent.droplet)
                finish_input_events()
                def recalculate():
                    editor._mark_design_optimization_dirty()
                    editor._run_design_optimization_flow()
                success = run_job(app, editor, recalculate, stop=stop)
                assert_physical_allocation(case, editor.model)
                digest = state_digest(editor.model)
                allocation = allocation_evidence(editor.model, success.pop("result"))
                current = (digest, allocation)
                assert current == baselines.setdefault((name, two), current), "Repeated calculation changed allocation/counts/work"
                cancellation = run_job(app, editor, recalculate, cancel_phase=(
                    "Preparing candidates" if name == "groups_import" else "Optimizing allocations"), stop=stop)
                closed = run_job(app, editor, recalculate, cancel_phase="Preparing candidates", close_active=True, stop=stop)
                close_owner(app, editor)
                editor = None
                assert id(manager._worker) == worker_identity, "Worker replaced during the session"
                evidence["interactions"].append(dict(round=round_index, warmup=warmup, case=name, allow_two=two,
                    success=success, cancellation=cancellation, close_active=closed, state_sha256=digest,
                    selected_rank=allocation["selected_rank"], two_stock_keys=allocation["two_stock_keys"]))
                persist()
                print(f"round {round_index+1}/{args.warmups+args.rounds} {name} two={two} complete", flush=True)
            # Same state at every endpoint: no editor open, inputs cached, worker idle.
            deadline = time.monotonic()+args.settle_seconds
            while time.monotonic() < deadline:
                finish_input_events()
                if stop(): raise RuntimeError("Memory campaign cancelled")
                time.sleep(.01)
            alive = sum(1 for ref in owners if ref() is not None and isValid(ref()))
            assert alive == 0, "Closed editor QObject survived deferred deletion"
            sample = memory_sample(os.getpid())
            sample.update(round=round_index, warmup=warmup, python_allocated_blocks=sys.getallocatedblocks(),
                          gc_counts=gc.get_count(), gc_stats=gc.get_stats(), live_closed_editors=alive)
            evidence["endpoints"].append(sample)
            owners.clear()
            assert gc.isenabled() == evidence["gc_policy"]["enabled"] and list(gc.get_threshold()) == list(evidence["gc_policy"]["thresholds"])
            persist()
        evidence["assessment"] = assess(evidence["endpoints"])
        states = [v["status"] for v in evidence["assessment"].values()]
        evidence["status"] = "passed" if all(s == "stable_within_bound" for s in states) else (
            "review_required" if "growth_requires_review" in states else "inconclusive")
        evidence["complete"] = True
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if editor is not None:
            close_owner(app, editor)
        stopped = []
        started = time.monotonic()
        manager.shutdown(lambda: stopped.append(True))
        while not stopped:
            app.processEvents()
            if time.monotonic()-started > 10:
                evidence["shutdown_error"] = "Worker did not stop within ten seconds"
                persist()
                # Supervisor handles an unresponsive process; never destroy a running QThread.
                while True: app.processEvents(); time.sleep(.01)
            time.sleep(.001)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        evidence["shutdown_ms"] = (time.monotonic()-started)*1000
        evidence["worker_stopped"] = manager._thread is None
        watcher_stopped.set()
        watcher.join(timeout=1)
        persist()
    return evidence
