from __future__ import annotations

import math
import statistics
import sys
import threading
import time
import traceback
from collections import deque
from contextlib import contextmanager
from numbers import Real
from typing import Any, Callable, Iterable, Mapping


DEFAULT_LATENCY_BANDS_MS = (25.0, 50.0, 100.0, 250.0, 1000.0)
_AUTO = object()


def _finite_values(values: Iterable[Real]) -> list[float]:
    result: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("metric samples must be real numbers")
        converted = float(value)
        if not math.isfinite(converted):
            raise ValueError("metric samples must be finite")
        result.append(converted)
    return result


def percentile(values: Iterable[Real], quantile: float) -> float:
    """Return a linearly interpolated quantile in the inclusive range 0..1."""
    if isinstance(quantile, bool) or not isinstance(quantile, Real):
        raise ValueError("quantile must be a real number between 0 and 1")
    q = float(quantile)
    if not math.isfinite(q) or q < 0.0 or q > 1.0:
        raise ValueError("quantile must be a real number between 0 and 1")
    ordered = sorted(_finite_values(values))
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def linear_slope(values: Iterable[Real]) -> float:
    """Return the least-squares slope against zero-based sample index."""
    samples = _finite_values(values)
    count = len(samples)
    if count < 2:
        return 0.0
    mean_x = (count - 1) / 2.0
    mean_y = statistics.fmean(samples)
    denominator = sum((index - mean_x) ** 2 for index in range(count))
    if denominator == 0:
        return 0.0
    return sum(
        (index - mean_x) * (value - mean_y)
        for index, value in enumerate(samples)
    ) / denominator


def summarize_samples(
    values: Iterable[Real],
    bands_ms: Iterable[Real] = DEFAULT_LATENCY_BANDS_MS,
) -> dict[str, Any]:
    """Summarize samples and count values strictly above each threshold band."""
    samples = _finite_values(values)
    bands = _finite_values(bands_ms)
    if any(value < 0 for value in bands):
        raise ValueError("threshold bands must be non-negative")
    if len(set(bands)) != len(bands):
        raise ValueError("threshold bands must be unique")
    bands.sort()
    if not samples:
        summary: dict[str, Any] = {
            "count": 0,
            "mean": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "maximum": 0.0,
            "linear_slope_per_sample": 0.0,
            "counts_strictly_above_ms": {
                _band_key(band): 0 for band in bands
            },
        }
        return summary
    return {
        "count": len(samples),
        "mean": statistics.fmean(samples),
        "p50": percentile(samples, 0.50),
        "p95": percentile(samples, 0.95),
        "p99": percentile(samples, 0.99),
        "maximum": max(samples),
        "linear_slope_per_sample": linear_slope(samples),
        "counts_strictly_above_ms": {
            _band_key(band): sum(sample > band for sample in samples)
            for band in bands
        },
    }


def _band_key(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


class _BoundedBuffer:
    def __init__(self, max_items: int):
        if isinstance(max_items, bool) or int(max_items) < 1:
            raise ValueError("max_items must be at least one")
        self.max_items = int(max_items)
        self._items: deque[Any] = deque(maxlen=self.max_items)
        self._dropped = 0
        self._lock = threading.Lock()

    def append(self, value: Any) -> None:
        with self._lock:
            if len(self._items) == self.max_items:
                self._dropped += 1
            self._items.append(value)

    def snapshot(self) -> tuple[list[Any], int]:
        with self._lock:
            return list(self._items), self._dropped


class NamedPhaseRecorder:
    """Thread-safe nested monotonic phase recorder with bounded history."""

    def __init__(
        self,
        *,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
        max_records: int = 50_000,
    ):
        self._clock_ns = clock_ns
        self._records = _BoundedBuffer(max_records)
        self._active: dict[int, list[dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._next_id = 1

    @contextmanager
    def phase(
        self,
        name: str,
        metadata: Mapping[str, Any] | None = None,
    ):
        phase_name = str(name or "").strip()
        if not phase_name:
            raise ValueError("phase name must be non-empty")
        details = dict(metadata or {})
        thread_id = threading.get_ident()
        started_ns = int(self._clock_ns())
        with self._lock:
            phase_id = self._next_id
            self._next_id += 1
            stack = self._active.setdefault(thread_id, [])
            record = {
                "phase_id": phase_id,
                "name": phase_name,
                "metadata": details,
                "thread_id": thread_id,
                "depth": len(stack),
                "started_ns": started_ns,
            }
            stack.append(record)
        outcome = "ok"
        error_type = None
        try:
            yield record
        except BaseException as exc:
            outcome = "exception"
            error_type = type(exc).__name__
            raise
        finally:
            ended_ns = int(self._clock_ns())
            completed = {
                **record,
                "ended_ns": ended_ns,
                "duration_ms": max(0, ended_ns - started_ns) / 1_000_000.0,
                "outcome": outcome,
                "error_type": error_type,
            }
            with self._lock:
                stack = self._active.get(thread_id, [])
                for index in range(len(stack) - 1, -1, -1):
                    if stack[index]["phase_id"] == phase_id:
                        del stack[index]
                        break
                if not stack:
                    self._active.pop(thread_id, None)
            self._records.append(completed)

    def current_phase(self, thread_id: int | None = None) -> dict[str, Any] | None:
        target = threading.get_ident() if thread_id is None else int(thread_id)
        with self._lock:
            stack = self._active.get(target, [])
            return dict(stack[-1]) if stack else None

    def best_overlap(self, started_ns: int, ended_ns: int) -> dict[str, Any] | None:
        start = int(started_ns)
        end = int(ended_ns)
        if end < start:
            raise ValueError("phase overlap interval ends before it starts")
        records, _ = self._records.snapshot()
        now_ns = int(self._clock_ns())
        with self._lock:
            active = [
                {
                    **record,
                    "ended_ns": now_ns,
                    "duration_ms": max(0, now_ns - int(record["started_ns"]))
                    / 1_000_000.0,
                    "outcome": "active",
                    "error_type": None,
                }
                for stack in self._active.values()
                for record in stack
            ]
        best = None
        best_key = None
        for record in [*records, *active]:
            overlap_ns = max(
                0,
                min(end, int(record["ended_ns"]))
                - max(start, int(record["started_ns"])),
            )
            if overlap_ns <= 0:
                continue
            key = (overlap_ns, int(record.get("depth", 0)))
            if best_key is None or key > best_key:
                best_key = key
                best = {
                    **record,
                    "overlap_ms": overlap_ns / 1_000_000.0,
                }
        return best

    def snapshot(self) -> dict[str, Any]:
        records, dropped = self._records.snapshot()
        with self._lock:
            active = [
                dict(record)
                for stack in self._active.values()
                for record in stack
            ]
        by_name: dict[str, list[float]] = {}
        for record in records:
            by_name.setdefault(record["name"], []).append(record["duration_ms"])
        return {
            "records": records,
            "active": active,
            "dropped_records": dropped,
            "duration_by_name_ms": {
                name: summarize_samples(values, bands_ms=())
                for name, values in sorted(by_name.items())
            },
        }


class ProcessResourceSampler:
    """Best-effort process resource sampling with no mandatory psutil import."""

    def __init__(
        self,
        *,
        process: Any | None = None,
        psutil_module: Any = _AUTO,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
        max_samples: int = 100_000,
    ):
        self._clock_ns = clock_ns
        self._samples = _BoundedBuffer(max_samples)
        self._process = process
        self._psutil_module = psutil_module
        self._started = False
        self._baseline: dict[str, Any] | None = None
        self._errors: list[str] = []

    def _resolve_process(self) -> None:
        if self._process is not None:
            return
        module = self._psutil_module
        if module is _AUTO:
            try:
                import psutil as module
            except ImportError as exc:
                self._errors.append(f"psutil unavailable: {exc}")
                return
        if module is None:
            self._errors.append("psutil unavailable")
            return
        try:
            self._process = module.Process()
        except Exception as exc:
            self._errors.append(f"could not create psutil process: {exc}")

    @staticmethod
    def _number(value: Any) -> float | int | None:
        if isinstance(value, bool) or not isinstance(value, Real):
            return None
        converted = float(value)
        return converted if math.isfinite(converted) else None

    def _read(self) -> dict[str, Any] | None:
        if self._process is None:
            return None
        sample: dict[str, Any] = {"monotonic_ns": int(self._clock_ns())}
        try:
            cpu = self._process.cpu_times()
            user = self._number(getattr(cpu, "user", None))
            system = self._number(getattr(cpu, "system", None))
            sample["cpu_time_ms"] = (
                (float(user) + float(system)) * 1000.0
                if user is not None and system is not None
                else None
            )
        except Exception as exc:
            sample["cpu_time_ms"] = None
            self._errors.append(f"cpu_times unavailable: {exc}")
        try:
            memory = self._process.memory_info()
            rss = self._number(getattr(memory, "rss", None))
            sample["rss_bytes"] = int(rss) if rss is not None else None
        except Exception as exc:
            sample["rss_bytes"] = None
            self._errors.append(f"memory_info unavailable: {exc}")
        try:
            counters = self._process.io_counters()
            read_bytes = self._number(getattr(counters, "read_bytes", None))
            write_bytes = self._number(getattr(counters, "write_bytes", None))
            sample["read_bytes"] = (
                int(read_bytes) if read_bytes is not None else None
            )
            sample["write_bytes"] = (
                int(write_bytes) if write_bytes is not None else None
            )
        except Exception as exc:
            sample["read_bytes"] = None
            sample["write_bytes"] = None
            self._errors.append(f"io_counters unavailable: {exc}")
        try:
            threads = self._number(self._process.num_threads())
            sample["thread_count"] = int(threads) if threads is not None else None
        except Exception as exc:
            sample["thread_count"] = None
            self._errors.append(f"num_threads unavailable: {exc}")
        return sample

    def start(self) -> None:
        if self._started:
            raise RuntimeError("resource sampler is already running")
        self._resolve_process()
        self._started = True
        self._baseline = self._read()
        if self._baseline is not None:
            self._samples.append(self._baseline)

    def sample(self) -> dict[str, Any] | None:
        if not self._started:
            return None
        sample = self._read()
        if sample is not None:
            self._samples.append(sample)
        return sample

    def stop(self) -> None:
        if not self._started:
            return
        self.sample()
        self._started = False

    def snapshot(self) -> dict[str, Any]:
        samples, dropped = self._samples.snapshot()
        if not samples:
            return {
                "status": "not_available",
                "values": {
                    "availability_reasons": list(dict.fromkeys(self._errors)),
                    "sample_count": 0,
                    "dropped_samples": dropped,
                },
            }
        first = self._baseline or samples[0]
        last = samples[-1]

        def delta(key: str) -> float | int | None:
            before = first.get(key)
            after = last.get(key)
            if before is None or after is None:
                return None
            return max(0, after - before)

        rss_values = [
            int(sample["rss_bytes"])
            for sample in samples
            if sample.get("rss_bytes") is not None
        ]
        thread_values = [
            int(sample["thread_count"])
            for sample in samples
            if sample.get("thread_count") is not None
        ]
        values = {
            "sample_count": len(samples),
            "dropped_samples": dropped,
            "process_cpu_time_ms_delta": delta("cpu_time_ms"),
            "peak_rss_bytes": max(rss_values) if rss_values else None,
            "read_bytes_delta": delta("read_bytes"),
            "write_bytes_delta": delta("write_bytes"),
            "maximum_thread_count": max(thread_values) if thread_values else None,
            "availability_reasons": list(dict.fromkeys(self._errors)),
        }
        complete = all(
            values[key] is not None
            for key in (
                "process_cpu_time_ms_delta",
                "peak_rss_bytes",
                "read_bytes_delta",
                "write_bytes_delta",
                "maximum_thread_count",
            )
        )
        return {"status": "measured" if complete else "partial", "values": values}


class QtEventLoopProbe:
    """Measure Qt service gaps and capture main-thread evidence during stalls."""

    def __init__(
        self,
        *,
        heartbeat_interval_ms: int = 10,
        threshold_bands_ms: Iterable[Real] = DEFAULT_LATENCY_BANDS_MS,
        stack_capture_ms: float = 250.0,
        observer_interval_ms: int = 5,
        resource_interval_ms: int = 100,
        phase_recorder: NamedPhaseRecorder | None = None,
        resource_sampler: ProcessResourceSampler | None = None,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
        max_samples: int = 100_000,
        max_events: int = 10_000,
    ):
        for name, value in (
            ("heartbeat_interval_ms", heartbeat_interval_ms),
            ("observer_interval_ms", observer_interval_ms),
            ("resource_interval_ms", resource_interval_ms),
        ):
            if isinstance(value, bool) or int(value) < 1:
                raise ValueError(f"{name} must be at least one")
        if (
            isinstance(stack_capture_ms, bool)
            or not isinstance(stack_capture_ms, Real)
            or float(stack_capture_ms) <= 0
        ):
            raise ValueError("stack_capture_ms must be positive")
        self.heartbeat_interval_ms = int(heartbeat_interval_ms)
        self.threshold_bands_ms = tuple(
            sorted(_finite_values(threshold_bands_ms))
        )
        self.stack_capture_ms = float(stack_capture_ms)
        self.observer_interval_ms = int(observer_interval_ms)
        self.resource_interval_ms = int(resource_interval_ms)
        self.phase_recorder = phase_recorder or NamedPhaseRecorder(clock_ns=clock_ns)
        self.resource_sampler = resource_sampler or ProcessResourceSampler(
            clock_ns=clock_ns
        )
        self._clock_ns = clock_ns
        self._gaps = _BoundedBuffer(max_samples)
        self._lateness = _BoundedBuffer(max_samples)
        self._callback_cost = _BoundedBuffer(max_samples)
        self._stall_events = _BoundedBuffer(max_events)
        self._stack_captures = _BoundedBuffer(max_events)
        self._state_lock = threading.Lock()
        self._last_heartbeat_ns: int | None = None
        self._heartbeat_serial = 0
        self._captured_serial: int | None = None
        self._main_thread_id: int | None = None
        self._timer = None
        self._observer_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._observer_ready = threading.Event()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def observer_thread_alive(self) -> bool:
        return bool(self._observer_thread and self._observer_thread.is_alive())

    @property
    def timer_active(self) -> bool:
        timer = self._timer
        return bool(timer is not None and timer.isActive())

    def start(self, app: Any) -> None:
        if self._running:
            raise RuntimeError("Qt event-loop probe is already running")
        if app is None:
            raise ValueError("a QApplication instance is required")
        from PySide6.QtCore import Qt, QTimer

        self._main_thread_id = threading.get_ident()
        now_ns = int(self._clock_ns())
        with self._state_lock:
            self._last_heartbeat_ns = now_ns
            self._heartbeat_serial = 0
            self._captured_serial = None
        self.resource_sampler.start()
        timer = QTimer(app)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.setInterval(self.heartbeat_interval_ms)
        timer.timeout.connect(self.record_heartbeat)
        timer.start()
        self._timer = timer
        self._stop_event.clear()
        self._observer_ready.clear()
        self._running = True
        thread = threading.Thread(
            target=self._observe,
            name="VirtualWorkflowQtObserver",
            daemon=True,
        )
        self._observer_thread = thread
        thread.start()
        if not self._observer_ready.wait(timeout=1.0):
            self.stop()
            raise RuntimeError("Qt event-loop observer failed to start")

    def record_heartbeat(self, now_ns: int | None = None) -> float:
        callback_started_ns = int(self._clock_ns())
        observed_ns = callback_started_ns if now_ns is None else int(now_ns)
        with self._state_lock:
            previous_ns = self._last_heartbeat_ns
            self._last_heartbeat_ns = observed_ns
            self._heartbeat_serial += 1
            self._captured_serial = None
        if previous_ns is None:
            return 0.0
        gap_ms = max(0, observed_ns - previous_ns) / 1_000_000.0
        lateness_ms = max(0.0, gap_ms - self.heartbeat_interval_ms)
        self._gaps.append(gap_ms)
        self._lateness.append(lateness_ms)
        if self.threshold_bands_ms and gap_ms > self.threshold_bands_ms[0]:
            phase = self.phase_recorder.best_overlap(previous_ns, observed_ns)
            self._stall_events.append(
                {
                    "event_loop_gap_ms": gap_ms,
                    "scheduling_lateness_ms": lateness_ms,
                    "strictly_above_bands_ms": [
                        band for band in self.threshold_bands_ms if gap_ms > band
                    ],
                    "phase": phase,
                }
            )
        callback_cost_ms = max(
            0,
            int(self._clock_ns()) - callback_started_ns,
        ) / 1_000_000.0
        self._callback_cost.append(callback_cost_ms)
        return gap_ms

    def _observe(self) -> None:
        poll_seconds = self.observer_interval_ms / 1000.0
        resource_interval_ns = self.resource_interval_ms * 1_000_000
        next_resource_ns = int(self._clock_ns())
        self._observer_ready.set()
        while not self._stop_event.wait(poll_seconds):
            now_ns = int(self._clock_ns())
            if now_ns >= next_resource_ns:
                self.resource_sampler.sample()
                next_resource_ns = now_ns + resource_interval_ns
            with self._state_lock:
                last_ns = self._last_heartbeat_ns
                serial = self._heartbeat_serial
                already_captured = self._captured_serial == serial
                main_thread_id = self._main_thread_id
            if last_ns is None or already_captured or main_thread_id is None:
                continue
            stalled_ms = max(0, now_ns - last_ns) / 1_000_000.0
            if stalled_ms <= self.stack_capture_ms:
                continue
            frame = sys._current_frames().get(main_thread_id)
            stack_text = (
                "".join(traceback.format_stack(frame))
                if frame is not None
                else "No Python frame available.\n"
            )
            capture = {
                "captured_at_monotonic_ns": now_ns,
                "observed_gap_ms": stalled_ms,
                "phase": self.phase_recorder.current_phase(main_thread_id),
                "main_thread_id": main_thread_id,
                "stack": stack_text,
            }
            self._stack_captures.append(capture)
            with self._state_lock:
                if self._heartbeat_serial == serial:
                    self._captured_serial = serial

    def stop(self, timeout_s: float = 1.0) -> None:
        timer = self._timer
        if timer is not None:
            timer.stop()
            try:
                timer.timeout.disconnect(self.record_heartbeat)
            except (RuntimeError, TypeError):
                pass
        self._stop_event.set()
        thread = self._observer_thread
        if thread is not None:
            thread.join(timeout=max(0.0, float(timeout_s)))
        self.resource_sampler.stop()
        self._running = False
        errors = []
        if timer is not None and timer.isActive():
            errors.append("Qt heartbeat timer remained active")
        if thread is not None and thread.is_alive():
            errors.append("observer thread did not stop")
        if errors:
            raise RuntimeError("; ".join(errors))

    def snapshot(self) -> dict[str, Any]:
        gaps, dropped_gaps = self._gaps.snapshot()
        lateness, dropped_lateness = self._lateness.snapshot()
        callback_cost, dropped_callback_cost = self._callback_cost.snapshot()
        stall_events, dropped_events = self._stall_events.snapshot()
        stack_captures, dropped_stacks = self._stack_captures.snapshot()
        return {
            "heartbeat_interval_ms": self.heartbeat_interval_ms,
            "observer_interval_ms": self.observer_interval_ms,
            "stack_capture_threshold_ms": self.stack_capture_ms,
            "event_loop_gap_ms": summarize_samples(
                gaps,
                self.threshold_bands_ms,
            ),
            "scheduling_lateness_ms": summarize_samples(
                lateness,
                self.threshold_bands_ms,
            ),
            "probe_callback_cost_ms": summarize_samples(callback_cost, bands_ms=()),
            "raw_event_loop_gap_ms": gaps,
            "raw_scheduling_lateness_ms": lateness,
            "raw_probe_callback_cost_ms": callback_cost,
            "stall_events": stall_events,
            "stack_captures": stack_captures,
            "phase_timings": self.phase_recorder.snapshot(),
            "retention": {
                "dropped_gap_samples": dropped_gaps,
                "dropped_lateness_samples": dropped_lateness,
                "dropped_callback_cost_samples": dropped_callback_cost,
                "dropped_stall_events": dropped_events,
                "dropped_stack_captures": dropped_stacks,
            },
            "shutdown": {
                "timer_active": self.timer_active,
                "observer_thread_alive": self.observer_thread_alive,
            },
        }
