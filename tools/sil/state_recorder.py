"""Bounded, append-only state evidence for interactive SIL sessions."""

from __future__ import annotations

from collections import Counter, deque
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Mapping


EVENT_SCHEMA_ID = "labcraft.sil_state_event"
SNAPSHOT_SCHEMA_ID = "labcraft.sil_state_snapshot"
STATE_SCHEMA_VERSION = 1
RECORDER_VERSION = "milestone-2-v1"


class StateRecorderError(RuntimeError):
    """Raised after a state-evidence operation fails."""


@dataclass(frozen=True)
class StateRecorderConfigV1:
    """Validated limits for one application-session recorder."""

    in_memory_event_limit: int = 512
    flush_every_events: int = 1
    max_changed_fields: int = 64
    max_string_chars: int = 2048
    max_collection_entries: int = 100
    max_depth: int = 8

    def __post_init__(self) -> None:
        for name in (
            "in_memory_event_limit",
            "flush_every_events",
            "max_changed_fields",
            "max_string_chars",
            "max_collection_entries",
            "max_depth",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_truncation() -> dict[str, int]:
    return {
        "strings": 0,
        "characters_dropped": 0,
        "collections": 0,
        "entries_dropped": 0,
        "depth": 0,
        "non_finite_numbers": 0,
        "unsupported_values": 0,
    }


def _normalize(
    value: Any,
    *,
    config: StateRecorderConfigV1,
    truncation: dict[str, int],
    depth: int = 0,
) -> Any:
    """Return bounded JSON-safe data without traversing arbitrary objects."""

    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        truncation["non_finite_numbers"] += 1
        return None
    if isinstance(value, Enum):
        return _normalize(
            value.value,
            config=config,
            truncation=truncation,
            depth=depth,
        )
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, str):
        if len(value) <= config.max_string_chars:
            return value
        truncation["strings"] += 1
        truncation["characters_dropped"] += len(value) - config.max_string_chars
        return value[: config.max_string_chars]
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)

    if depth >= config.max_depth:
        truncation["depth"] += 1
        return "<max-depth>"

    if isinstance(value, Mapping):
        items = sorted(value.items(), key=lambda item: str(item[0]))
        if len(items) > config.max_collection_entries:
            truncation["collections"] += 1
            truncation["entries_dropped"] += (
                len(items) - config.max_collection_entries
            )
            items = items[: config.max_collection_entries]
        return {
            str(key): _normalize(
                item,
                config=config,
                truncation=truncation,
                depth=depth + 1,
            )
            for key, item in items
        }

    if isinstance(value, (list, tuple, set, frozenset, deque)):
        items = list(value)
        if isinstance(value, (set, frozenset)):
            items.sort(key=str)
        if len(items) > config.max_collection_entries:
            truncation["collections"] += 1
            truncation["entries_dropped"] += (
                len(items) - config.max_collection_entries
            )
            items = items[: config.max_collection_entries]
        return [
            _normalize(
                item,
                config=config,
                truncation=truncation,
                depth=depth + 1,
            )
            for item in items
        ]

    truncation["unsupported_values"] += 1
    text = f"<{type(value).__name__}>"
    return _normalize(
        text,
        config=config,
        truncation=truncation,
        depth=depth,
    )


def normalize_state_value(
    value: Any,
    config: StateRecorderConfigV1 | None = None,
) -> tuple[Any, dict[str, int]]:
    """Normalize a value and return explicit truncation evidence."""

    resolved_config = config or StateRecorderConfigV1()
    truncation = _empty_truncation()
    normalized = _normalize(
        value,
        config=resolved_config,
        truncation=truncation,
    )
    return normalized, truncation


def _atomic_write_json_once(path: Path, payload: Mapping[str, Any]) -> None:
    """Write one evidence snapshot atomically without retrying ambiguity."""

    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.stem}_",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        # Preserve a same-directory temporary file as failure evidence. The
        # caller marks the session failed and must not retry the write.
        raise


class StateRecorder:
    """Own one application session's bounded memory tail and full JSONL."""

    def __init__(
        self,
        *,
        session_root: Path,
        session_id: str,
        application_session_id: str,
        config: StateRecorderConfigV1 | None = None,
        on_failure: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config or StateRecorderConfigV1()
        self.session_root = Path(session_root).resolve()
        self.session_id = str(session_id)
        self.application_session_id = str(application_session_id)
        self.artifact_dir = (
            self.session_root
            / "artifacts"
            / "state"
            / self.application_session_id
        ).resolve()
        if self.session_root not in self.artifact_dir.parents:
            raise ValueError("state recorder artifact path escaped session root")
        self.events_path = self.artifact_dir / "events.jsonl"
        self.latest_snapshot_path = self.artifact_dir / "latest_snapshot.json"
        self.terminal_snapshot_path = self.artifact_dir / "terminal_snapshot.json"
        self._on_failure = on_failure
        self._handle = None
        self._events: deque[dict[str, Any]] = deque(
            maxlen=self.config.in_memory_event_limit
        )
        self._event_counts: Counter[str] = Counter()
        self._evicted_counts: Counter[str] = Counter()
        self._truncation_totals: Counter[str] = Counter()
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._event_sequence = 0
        self._action_sequence = 0
        self._snapshot_sequence = 0
        self._events_since_flush = 0
        self._latest_snapshot: dict[str, Any] | None = None
        self._failure: str | None = None
        self._closed = False

        try:
            self.artifact_dir.mkdir(parents=True, exist_ok=False)
            self._handle = self.events_path.open(
                "x",
                encoding="utf-8",
                newline="\n",
            )
            self.record_event(
                "recorder_started",
                source_layer="session",
                payload={
                    "recorder_version": RECORDER_VERSION,
                    "config": asdict(self.config),
                },
            )
        except Exception as exc:
            self.fail(f"state recorder initialization failed: {exc}")

    @property
    def healthy(self) -> bool:
        return self._failure is None and not self._closed

    @property
    def failed(self) -> bool:
        return self._failure is not None

    def relative_path(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.session_root).as_posix()

    def artifact_map(self) -> dict[str, str]:
        return {
            "events": self.relative_path(self.events_path),
            "latest_snapshot": self.relative_path(self.latest_snapshot_path),
            "terminal_snapshot": self.relative_path(self.terminal_snapshot_path),
        }

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _notify(self, event: dict[str, Any]) -> None:
        for listener in list(self._listeners):
            try:
                listener(deepcopy(event))
            except Exception:
                # An inspector/listener is observational and cannot fail the
                # recorder or the application.
                continue

    def _ensure_writable(self) -> None:
        if self._closed:
            raise StateRecorderError("state recorder is closed")
        if self._failure is not None:
            raise StateRecorderError(self._failure)
        if self._handle is None:
            raise StateRecorderError("state recorder event file is unavailable")

    def fail(self, reason: str) -> None:
        text = str(reason).strip() or "unspecified state recorder failure"
        if self._failure is not None:
            return
        self._failure = text
        callback = self._on_failure
        if callback is not None:
            try:
                callback(text)
            except Exception:
                pass

    def _bounded_changes(
        self,
        value: Mapping[str, Any] | None,
        truncation: dict[str, int],
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        items = sorted(value.items(), key=lambda item: str(item[0]))
        if len(items) > self.config.max_changed_fields:
            truncation["collections"] += 1
            truncation["entries_dropped"] += (
                len(items) - self.config.max_changed_fields
            )
            items = items[: self.config.max_changed_fields]
        return {
            str(key): _normalize(
                item,
                config=self.config,
                truncation=truncation,
                depth=1,
            )
            for key, item in items
        }

    def record_event(
        self,
        event_kind: str,
        *,
        source_layer: str,
        payload: Any = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        correlation: Mapping[str, Any] | None = None,
        simulated_elapsed_ms: int | None = None,
        captured_at_utc: str | None = None,
        monotonic_ns: int | None = None,
    ) -> dict[str, Any]:
        self._ensure_writable()
        kind = str(event_kind or "").strip()
        layer = str(source_layer or "").strip()
        if not kind or not layer:
            raise ValueError("event_kind and source_layer must not be empty")

        truncation = _empty_truncation()
        normalized_payload = _normalize(
            payload,
            config=self.config,
            truncation=truncation,
        )
        normalized_correlation = _normalize(
            dict(correlation or {}),
            config=self.config,
            truncation=truncation,
        )
        self._event_sequence += 1
        event = {
            "schema_id": EVENT_SCHEMA_ID,
            "schema_version": STATE_SCHEMA_VERSION,
            "event_sequence": self._event_sequence,
            "captured_at_utc": captured_at_utc or _utc_now(),
            "monotonic_ns": int(monotonic_ns or time.perf_counter_ns()),
            "session_id": self.session_id,
            "application_session_id": self.application_session_id,
            "event_kind": kind,
            "source_layer": layer,
            "simulated_elapsed_ms": (
                None
                if simulated_elapsed_ms is None
                else int(simulated_elapsed_ms)
            ),
            "correlation": normalized_correlation,
            "before": self._bounded_changes(before, truncation),
            "after": self._bounded_changes(after, truncation),
            "payload": normalized_payload,
            "truncation": truncation,
        }
        line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
        try:
            self._handle.write(line)
            self._events_since_flush += 1
            if self._events_since_flush >= self.config.flush_every_events:
                self._handle.flush()
                self._events_since_flush = 0
        except Exception as exc:
            self.fail(f"state recorder append failed: {exc}")
            raise StateRecorderError(self._failure) from exc

        if len(self._events) == self._events.maxlen:
            oldest = self._events[0]
            self._evicted_counts[str(oldest.get("event_kind") or "unknown")] += 1
        self._events.append(event)
        self._event_counts[kind] += 1
        self._truncation_totals.update(truncation)
        self._notify(event)
        return deepcopy(event)

    def begin_action(
        self,
        action_kind: str,
        *,
        source_layer: str = "session",
        payload: Any = None,
    ) -> str:
        self._action_sequence += 1
        action_id = f"action-{self._action_sequence:06d}"
        self.record_event(
            "action_started",
            source_layer=source_layer,
            payload={"action_kind": str(action_kind), "details": payload},
            correlation={"action_id": action_id},
        )
        return action_id

    def complete_action(
        self,
        action_id: str,
        *,
        action_kind: str,
        outcome: str = "completed",
        source_layer: str = "session",
        payload: Any = None,
    ) -> dict[str, Any]:
        return self.record_event(
            "action_completed",
            source_layer=source_layer,
            payload={
                "action_kind": str(action_kind),
                "outcome": str(outcome),
                "details": payload,
            },
            correlation={"action_id": str(action_id)},
        )

    def record_snapshot(
        self,
        projection: Mapping[str, Any],
        *,
        reason: str,
        event_kind: str = "snapshot_exported",
        source_layer: str = "session",
        correlation: Mapping[str, Any] | None = None,
        simulated_elapsed_ms: int | None = None,
        persist: bool = True,
        terminal: bool = False,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._snapshot_sequence += 1
        snapshot_id = f"snapshot-{self._snapshot_sequence:06d}"
        normalized_projection, projection_truncation = normalize_state_value(
            dict(projection),
            self.config,
        )
        resolved_correlation = dict(correlation or {})
        resolved_correlation["snapshot_id"] = snapshot_id
        event = self.record_event(
            event_kind,
            source_layer=source_layer,
            payload={
                "reason": str(reason),
                "projection": normalized_projection,
                "snapshot_payload": dict(payload or {}),
                "projection_truncation": projection_truncation,
            },
            correlation=resolved_correlation,
            simulated_elapsed_ms=simulated_elapsed_ms,
        )
        snapshot = {
            "schema_id": SNAPSHOT_SCHEMA_ID,
            "schema_version": STATE_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "event_sequence": event["event_sequence"],
            "captured_at_utc": event["captured_at_utc"],
            "monotonic_ns": event["monotonic_ns"],
            "session_id": self.session_id,
            "application_session_id": self.application_session_id,
            "reason": str(reason),
            "correlation": resolved_correlation,
            "projection": normalized_projection,
            "truncation": projection_truncation,
        }
        self._latest_snapshot = snapshot
        if persist:
            destination = (
                self.terminal_snapshot_path if terminal else self.latest_snapshot_path
            )
            try:
                _atomic_write_json_once(destination, snapshot)
            except Exception as exc:
                self.fail(f"state snapshot write failed for {destination.name}: {exc}")
                raise StateRecorderError(self._failure) from exc
        return deepcopy(snapshot)

    def latest_snapshot(self) -> dict[str, Any] | None:
        return deepcopy(self._latest_snapshot)

    def memory_tail(self) -> list[dict[str, Any]]:
        return deepcopy(list(self._events))

    def health_snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "recorder_version": RECORDER_VERSION,
            "status": (
                "failed"
                if self._failure is not None
                else "closed"
                if self._closed
                else "healthy"
            ),
            "failure": self._failure,
            "event_count": int(sum(self._event_counts.values())),
            "event_counts": dict(sorted(self._event_counts.items())),
            "last_event_sequence": self._event_sequence,
            "retained_memory_count": len(self._events),
            "memory_limit": self.config.in_memory_event_limit,
            "evicted_memory_count": int(sum(self._evicted_counts.values())),
            "evicted_by_kind": dict(sorted(self._evicted_counts.items())),
            "truncation_totals": dict(sorted(self._truncation_totals.items())),
            "closed": self._closed,
        }

    def flush(self, *, durable: bool = False) -> None:
        self._ensure_writable()
        try:
            self._handle.flush()
            self._events_since_flush = 0
            if durable:
                os.fsync(self._handle.fileno())
        except Exception as exc:
            self.fail(f"state recorder flush failed: {exc}")
            raise StateRecorderError(self._failure) from exc

    def close(self) -> bool:
        if self._closed:
            return self._failure is None
        if self._failure is None:
            try:
                self.record_event(
                    "recorder_stopped",
                    source_layer="session",
                    payload={"status": "closed"},
                )
                self.flush(durable=True)
            except Exception:
                pass
        try:
            if self._handle is not None:
                self._handle.close()
        except Exception as exc:
            self.fail(f"state recorder close failed: {exc}")
        finally:
            self._handle = None
            self._closed = True
            self._listeners.clear()
        return self._failure is None
