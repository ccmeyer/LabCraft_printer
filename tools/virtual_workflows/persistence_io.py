"""Scoped observation of real persistence I/O for virtual-workflow evidence."""

from __future__ import annotations

import builtins
import contextlib
import io
import os
import time
from pathlib import Path
from typing import Any


class PersistenceIoObserver:
    """Observe selected file reads and durable calls without suppressing them."""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self.root = Path(root).resolve() if root is not None else None
        self._active_phase: str | None = None
        self._installed = False
        self._originals: dict[str, Any] = {}
        self._samples_ms: dict[str, dict[str, list[float]]] = {
            "fsync": {},
            "atomic_replace": {},
        }
        self._read_counts: dict[str, dict[str, int]] = {}
        self._read_size_bytes: dict[str, dict[str, int]] = {}
        self._totals: dict[str, int] = {
            "read_open_count": 0,
            "read_bytes": 0,
            "revision_read_count": 0,
            "revision_read_bytes": 0,
            "fsync_count": 0,
            "replace_count": 0,
        }

    @contextlib.contextmanager
    def phase(self, name: str):
        previous = self._active_phase
        self._active_phase = str(name)
        try:
            yield
        finally:
            self._active_phase = previous

    def _relative_path(self, value: Any) -> str | None:
        if isinstance(value, int):
            return None
        try:
            path = Path(value).resolve()
        except (OSError, TypeError, ValueError):
            return None
        if self.root is None:
            return str(path)
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return None

    def _record_read(self, value: Any, handle: Any) -> None:
        relative = self._relative_path(value)
        if relative is None:
            return
        phase = self._active_phase or "unattributed"
        self._read_counts.setdefault(phase, {})[relative] = (
            self._read_counts.setdefault(phase, {}).get(relative, 0) + 1
        )
        try:
            size = int(os.fstat(handle.fileno()).st_size)
        except (AttributeError, OSError, ValueError):
            size = 0
        self._read_size_bytes.setdefault(phase, {})[relative] = (
            self._read_size_bytes.setdefault(phase, {}).get(relative, 0) + size
        )
        self._totals["read_open_count"] += 1
        self._totals["read_bytes"] += size
        if relative.startswith("execution_plan_revisions/"):
            self._totals["revision_read_count"] += 1
            self._totals["revision_read_bytes"] += size

    def _record_duration(self, operation: str, elapsed_ms: float) -> None:
        phase = self._active_phase
        if phase is None:
            return
        self._samples_ms[operation].setdefault(phase, []).append(float(elapsed_ms))
        counter = "fsync_count" if operation == "fsync" else "replace_count"
        self._totals[counter] += 1

    def install(self) -> None:
        if self._installed:
            raise RuntimeError("persistence I/O observer is already installed")
        original_builtin_open = builtins.open
        original_io_open = io.open
        original_fsync = os.fsync
        original_replace = os.replace
        self._originals = {
            "builtin_open": original_builtin_open,
            "io_open": original_io_open,
            "fsync": original_fsync,
            "replace": original_replace,
        }

        def observed_builtin_open(file, mode="r", *args, **kwargs):
            handle = original_builtin_open(file, mode, *args, **kwargs)
            if "r" in str(mode) and "+" not in str(mode):
                self._record_read(file, handle)
            return handle

        def observed_io_open(file, mode="r", *args, **kwargs):
            handle = original_io_open(file, mode, *args, **kwargs)
            if "r" in str(mode) and "+" not in str(mode):
                self._record_read(file, handle)
            return handle

        def observed_fsync(fd):
            started = time.perf_counter_ns()
            try:
                return original_fsync(fd)
            finally:
                self._record_duration(
                    "fsync",
                    (time.perf_counter_ns() - started) / 1_000_000.0,
                )

        def observed_replace(source, destination):
            started = time.perf_counter_ns()
            try:
                return original_replace(source, destination)
            finally:
                self._record_duration(
                    "atomic_replace",
                    (time.perf_counter_ns() - started) / 1_000_000.0,
                )

        builtins.open = observed_builtin_open
        io.open = observed_io_open
        os.fsync = observed_fsync
        os.replace = observed_replace
        self._installed = True

    def restore(self) -> None:
        if not self._installed:
            return
        builtins.open = self._originals["builtin_open"]
        io.open = self._originals["io_open"]
        os.fsync = self._originals["fsync"]
        os.replace = self._originals["replace"]
        self._originals = {}
        self._installed = False

    @contextlib.contextmanager
    def installed(self):
        self.install()
        try:
            yield self
        finally:
            self.restore()

    def snapshot(self) -> dict[str, dict[str, list[float]]]:
        return {
            operation: {
                phase: list(values)
                for phase, values in sorted(by_phase.items())
            }
            for operation, by_phase in self._samples_ms.items()
        }

    def totals(self) -> dict[str, int]:
        """Return cumulative counters without copying retained raw samples."""
        return dict(self._totals)

    def read_snapshot(self) -> dict[str, Any]:
        by_phase = {
            phase: {
                path: {
                    "count": count,
                    "observed_file_size_bytes": self._read_size_bytes.get(phase, {}).get(
                        path,
                        0,
                    ),
                }
                for path, count in sorted(paths.items())
            }
            for phase, paths in sorted(self._read_counts.items())
        }
        by_path: dict[str, dict[str, int]] = {}
        for phase, paths in by_phase.items():
            for path, values in paths.items():
                aggregate = by_path.setdefault(
                    path,
                    {"count": 0, "observed_file_size_bytes": 0},
                )
                aggregate["count"] += int(values["count"])
                aggregate["observed_file_size_bytes"] += int(
                    values["observed_file_size_bytes"]
                )
        return {
            "by_phase": by_phase,
            "by_path": dict(sorted(by_path.items())),
            "total_count": sum(item["count"] for item in by_path.values()),
            "observer_restored": not self._installed,
        }
