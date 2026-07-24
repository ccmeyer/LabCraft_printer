"""Scoped observation of progress snapshot construction and serialization."""

from __future__ import annotations

import contextlib
import time
from typing import Any, Callable, Iterable


def non_durable_progress_samples(
    total_samples_ms: Iterable[float],
    fsync_samples_ms: Iterable[float],
    replace_samples_ms: Iterable[float],
) -> list[float]:
    """Subtract observed durable-call time from aligned progress writes."""
    totals = [float(value) for value in total_samples_ms]
    fsyncs = [float(value) for value in fsync_samples_ms]
    replaces = [float(value) for value in replace_samples_ms]
    if not (len(totals) == len(fsyncs) == len(replaces)):
        raise ValueError(
            "progress, fsync, and replace samples must have matching counts"
        )
    return [
        max(0.0, total - fsync - replace)
        for total, fsync, replace in zip(totals, fsyncs, replaces)
    ]


class ProgressSnapshotObserver:
    """Time instance-local progress boundaries without changing I/O phases."""

    _METHODS = {
        "_build_progress_payload_from_runtime": "full_rebuild",
        "_build_cached_progress_payload": "cached_update",
        "_serialize_progress_payload": "serialization",
        "_atomic_write_progress_text": "atomic_write",
    }

    def __init__(self, experiment_model: Any) -> None:
        self.experiment_model = experiment_model
        self._installed = False
        self._originals: dict[str, Callable[..., Any]] = {}
        self._samples_ms: dict[str, list[float]] = {
            label: [] for label in self._METHODS.values()
        }
        self._serialized_size_bytes: list[int] = []

    def install(self) -> None:
        if self._installed:
            raise RuntimeError("progress snapshot observer is already installed")
        for method_name, label in self._METHODS.items():
            original = getattr(self.experiment_model, method_name, None)
            if not callable(original):
                continue
            self._originals[method_name] = original

            def observed(*args, _original=original, _label=label, **kwargs):
                started = time.perf_counter_ns()
                try:
                    result = _original(*args, **kwargs)
                    if _label == "serialization" and isinstance(result, str):
                        self._serialized_size_bytes.append(
                            len(result.encode("utf-8"))
                        )
                    return result
                finally:
                    self._samples_ms[_label].append(
                        (time.perf_counter_ns() - started) / 1_000_000.0
                    )

            setattr(self.experiment_model, method_name, observed)
        self._installed = True

    def restore(self) -> None:
        if not self._installed:
            return
        for method_name, original in self._originals.items():
            setattr(self.experiment_model, method_name, original)
        self._originals = {}
        self._installed = False

    @contextlib.contextmanager
    def installed(self):
        self.install()
        try:
            yield self
        finally:
            self.restore()

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode_counts": {
                "full_rebuild": len(self._samples_ms["full_rebuild"]),
                "cached_update": len(self._samples_ms["cached_update"]),
            },
            "duration_samples_ms": {
                key: list(values)
                for key, values in self._samples_ms.items()
            },
            "serialized_size_bytes": list(self._serialized_size_bytes),
            "observer_restored": not self._installed,
        }
