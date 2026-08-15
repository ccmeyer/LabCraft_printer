"""Durable per-process calibration storage.

Milestone 2 uses this store in shadow mode: callers may diagnose failures and
continue through the legacy writer, but artifacts produced here already obey
the canonical v1 update/result/index contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping
import uuid


UPDATE_SCHEMA_NAME = "labcraft.calibration_recording.update"
RESULT_SCHEMA_NAME = "labcraft.calibration_recording.result"
RUN_META_SCHEMA_NAME = "labcraft.calibration_recording.run_meta"
INDEX_SCHEMA_NAME = "labcraft.calibration_recording.index_event"
UPDATE_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1
RUN_META_SCHEMA_VERSION = 2
INDEX_SCHEMA_VERSION = 1
LEGACY_REF_SCHEMA_NAME = "labcraft.calibration_recording.legacy_ref"
LEGACY_REF_SCHEMA_VERSION = 1

_PROCESS_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_RESULT_KINDS = {"calibration", "dataset", "operational", "none"}
_OUTCOMES = {
    "completed",
    "stopped",
    "error",
    "interrupted",
    "storage_error",
}
_ID_NAMESPACE = uuid.UUID("987f756b-d794-4cc4-8f8b-42d42825b6d1")


class CaptureRetentionPolicy(IntEnum):
    """Ordered pixel-retention policy; structured persistence is always separate."""

    STRUCTURED_ONLY = 0
    KEY_EVIDENCE = 1
    FULL = 2

    @property
    def storage_name(self) -> str:
        return {
            type(self).STRUCTURED_ONLY: "structured_only",
            type(self).KEY_EVIDENCE: "key_evidence",
            type(self).FULL: "full",
        }[self]

    @classmethod
    def parse(cls, value: Any) -> "CaptureRetentionPolicy":
        if isinstance(value, cls):
            return value
        normalized = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "structured_only": cls.STRUCTURED_ONLY,
            "key_evidence": cls.KEY_EVIDENCE,
            "full": cls.FULL,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            raise CalibrationStoreValidationError(
                f"invalid capture retention policy: {value!r}"
            ) from exc


class CalibrationStoreError(RuntimeError):
    """Base class for canonical calibration-store failures."""


class CalibrationStoreValidationError(CalibrationStoreError, ValueError):
    """The caller supplied data outside the canonical schema."""


class CalibrationStoreConflictError(CalibrationStoreError):
    """A stable identity was reused for different canonical content."""


class CalibrationStoreCorruptionError(CalibrationStoreError):
    """Persisted canonical data is malformed or internally inconsistent."""


class CalibrationStoreDurabilityError(CalibrationStoreError, OSError):
    """A durable filesystem operation failed."""


def _normalize_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CalibrationStoreValidationError("non-finite JSON number")
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    scalar = getattr(value, "item", None)
    if callable(scalar):
        return _normalize_json(scalar())
    array = getattr(value, "tolist", None)
    if callable(array):
        return _normalize_json(array())
    raise CalibrationStoreValidationError(
        f"unsupported canonical JSON value: {type(value).__name__}"
    )


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _normalize_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def semantic_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_id(kind: str, process_run_id: str, ordinal: int | None = None) -> str:
    suffix = kind if ordinal is None else f"{kind}:{int(ordinal)}"
    value = uuid.uuid5(_ID_NAMESPACE, f"{process_run_id}:{suffix}")
    return f"{kind}_{value}"


def _ensure_safe_component(value: str, *, label: str) -> str:
    text = str(value or "").strip()
    if not text or not _PROCESS_NAME_RE.fullmatch(text):
        raise CalibrationStoreValidationError(f"invalid {label}: {value!r}")
    return text


def _ensure_contained(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise CalibrationStoreValidationError(f"{label} escaped its root: {path}")
    return resolved


def _identity_snapshot(identity: Mapping[str, Any] | None) -> dict[str, Any]:
    source = dict(identity or {})
    keys = (
        "printer_head_id",
        "stock_id",
        "reagent_name",
        "stock_solution",
        "concentration",
        "display_concentration",
        "units",
        "head_type",
    )
    result = {}
    for key in keys:
        value = source.get(key)
        if value is not None:
            value = _normalize_json(value)
            if isinstance(value, (dict, list)):
                raise CalibrationStoreValidationError(
                    f"identity field {key} must be scalar"
                )
        result[key] = value
    stable_count = sum(
        bool(str(result.get(key) or "").strip())
        for key in ("printer_head_id", "stock_id")
    )
    result["identity_quality"] = (
        "stable" if stable_count == 2 else "partial" if stable_count else "unknown"
    )
    return result


@dataclass
class CalibrationRunHandle:
    process_run_id: str
    calibration_session_id: str
    process_name: str
    phase_name: str
    result_kind: str
    capture_policy_requested: str
    capture_policy_effective: str
    identity: dict[str, Any]
    started_at_utc: str
    run_dir: Path
    updates_path: Path
    result_path: Path
    meta_path: Path
    index_path: Path
    updates: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    parity_checked_count: int = 0
    parity_matched_count: int = 0
    parity_mismatch_count: int = 0
    shadow_state: str = "healthy"
    finalized: bool = False
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class CanonicalUpdateV1:
    document: Mapping[str, Any]

    @property
    def update_id(self) -> str:
        return str(self.document["update_id"])

    @property
    def payload_sha256(self) -> str:
        return str(self.document["payload_sha256"])


@dataclass(frozen=True)
class TerminalResultV1:
    document: Mapping[str, Any]

    @property
    def result_id(self) -> str:
        return str(self.document["result_id"])


@dataclass(frozen=True)
class IndexEventV1:
    document: Mapping[str, Any]


@dataclass(frozen=True)
class ResultCommit:
    result: TerminalResultV1
    index_event: IndexEventV1 | None
    result_finalize_latency_ms: float
    index_latency_ms: float | None


class CalibrationRecordingStore:
    """Own canonical run bundles and a rebuildable experiment index."""

    def __init__(
        self,
        experiment_dir: str | Path,
        *,
        recordings_root: str | Path | None = None,
        index_path: str | Path | None = None,
        enabled: bool = True,
        clock: Callable[[], str] = utc_now,
        fault_hook: Callable[[str], None] | None = None,
    ):
        self.experiment_dir = Path(experiment_dir).expanduser().resolve()
        self.recordings_root = _ensure_contained(
            Path(recordings_root).expanduser()
            if recordings_root is not None
            else self.experiment_dir / "calibration_recordings",
            self.experiment_dir,
            label="recordings root",
        )
        self.index_path = _ensure_contained(
            Path(index_path).expanduser()
            if index_path is not None
            else self.experiment_dir / "calibration_index.jsonl",
            self.experiment_dir,
            label="index path",
        )
        self.enabled = bool(enabled)
        self._clock = clock
        self._fault_hook = fault_hook

    def _fault(self, stage: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(str(stage))

    def _atomic_json(self, path: Path, payload: Mapping[str, Any], *, stage: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = None
        temporary_name = None
        try:
            self._fault(f"{stage}.create_temp")
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                descriptor = None
                self._fault(f"{stage}.write")
                json.dump(
                    _normalize_json(payload),
                    handle,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                handle.write("\n")
                self._fault(f"{stage}.flush")
                handle.flush()
                self._fault(f"{stage}.fsync")
                os.fsync(handle.fileno())
            self._fault(f"{stage}.replace")
            os.replace(temporary_name, path)
            temporary_name = None
        except CalibrationStoreError:
            raise
        except Exception as exc:
            raise CalibrationStoreDurabilityError(f"{stage} failed: {exc}") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass

    def _append_jsonl(self, path: Path, payload: Mapping[str, Any], *, stage: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fault(f"{stage}.open")
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                self._fault(f"{stage}.write")
                handle.write(
                    json.dumps(
                        _normalize_json(payload),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    + "\n"
                )
                self._fault(f"{stage}.flush")
                handle.flush()
                self._fault(f"{stage}.fsync")
                os.fsync(handle.fileno())
        except CalibrationStoreError:
            raise
        except Exception as exc:
            raise CalibrationStoreDurabilityError(f"{stage} failed: {exc}") from exc

    def _commit_json_once(
        self, path: Path, payload: Mapping[str, Any], *, stage: str
    ) -> bool:
        """Commit immutable JSON, accepting an identical prior partial commit."""
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CalibrationStoreCorruptionError(
                    f"existing {path.name} is invalid: {exc}"
                ) from exc
            if canonical_json_bytes(existing) != canonical_json_bytes(payload):
                raise CalibrationStoreConflictError(
                    f"existing {path.name} conflicts with the requested commit"
                )
            return False
        self._atomic_json(path, payload, stage=stage)
        return True

    def _append_index_once(self, payload: Mapping[str, Any]) -> bool:
        event_id = str(payload.get("index_event_id") or "")
        rows, ignored_tail = self.read_jsonl(self.index_path)
        if ignored_tail:
            raise CalibrationStoreCorruptionError(
                "index has an incomplete trailing event; rebuild before append"
            )
        matches = [row for row in rows if str(row.get("index_event_id") or "") == event_id]
        if len(matches) > 1:
            raise CalibrationStoreCorruptionError(f"duplicate index event: {event_id}")
        if matches:
            if canonical_json_bytes(matches[0]) != canonical_json_bytes(payload):
                raise CalibrationStoreConflictError(
                    f"index event conflicts with the requested commit: {event_id}"
                )
            return False
        self._append_jsonl(self.index_path, payload, stage="index_append")
        return True

    def _meta_document(
        self,
        run: CalibrationRunHandle,
        *,
        outcome: str = "running",
        ended_at_utc: str | None = None,
        error_message: str = "",
        result: Mapping[str, Any] | None = None,
        recorder_summary: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        recorder = dict(recorder_summary or {})
        return {
            "schema_name": RUN_META_SCHEMA_NAME,
            "schema_version": RUN_META_SCHEMA_VERSION,
            "run_id": run.process_run_id,
            "process_run_id": run.process_run_id,
            "calibration_session_id": run.calibration_session_id,
            "process_name": run.process_name,
            "phase_name": run.phase_name,
            "result_kind": run.result_kind,
            "capture_policy_requested": run.capture_policy_requested,
            "capture_policy_effective": run.capture_policy_effective,
            "structured_persistence_required": True,
            "started_at_utc": run.started_at_utc,
            "ended_at_utc": ended_at_utc,
            "outcome": outcome,
            "error_message": str(error_message or ""),
            "identity": dict(run.identity),
            "canonical_update_count": len(run.updates),
            "result_id": (result or {}).get("result_id"),
            "result_sha256": (result or {}).get("result_sha256"),
            "canonical_storage_state": run.shadow_state,
            "canonical_storage_warning_count": len(run.warnings),
            "canonical_storage_warnings": list(run.warnings),
            "parity_checked_count": run.parity_checked_count,
            "parity_matched_count": run.parity_matched_count,
            "parity_mismatch_count": run.parity_mismatch_count,
            "recorder_warning_count": int(recorder.get("recorder_warning_count", 0)),
            "recorder_warnings": list(recorder.get("recorder_warnings") or []),
            "capture_write_failure_count": int(
                recorder.get("capture_write_failure_count", 0)
            ),
            "capture_write_failures": list(
                recorder.get("capture_write_failures") or []
            ),
            "pending_capture_write_count": int(
                recorder.get("pending_capture_write_count", 0)
            ),
            "capture_requested_count": int(
                recorder.get("capture_requested_count", 0)
            ),
            "capture_saved_count": int(recorder.get("capture_saved_count", 0)),
            "capture_omitted_count": int(recorder.get("capture_omitted_count", 0)),
            "capture_failed_count": int(recorder.get("capture_failed_count", 0)),
        }

    def start_run(
        self,
        *,
        calibration_session_id: str,
        process_name: str,
        phase_name: str,
        result_kind: str = "none",
        identity: Mapping[str, Any] | None = None,
        capture_policy_requested: str = "structured_only",
        capture_policy_effective: str | None = None,
        process_run_id: str | None = None,
        warnings: Iterable[Mapping[str, Any]] = (),
    ) -> CalibrationRunHandle:
        if not self.enabled:
            raise CalibrationStoreValidationError("canonical shadow store is disabled")
        session_id = str(calibration_session_id or "").strip()
        if not session_id:
            raise CalibrationStoreValidationError("calibration_session_id is required")
        process = _ensure_safe_component(process_name, label="process name")
        phase = str(phase_name or "").strip()
        if not phase:
            raise CalibrationStoreValidationError("phase_name is required")
        kind = str(result_kind or "none").strip().lower()
        if kind not in _RESULT_KINDS:
            raise CalibrationStoreValidationError(f"invalid result_kind: {kind}")
        requested_policy = CaptureRetentionPolicy.parse(
            capture_policy_requested or "structured_only"
        )
        effective_policy = CaptureRetentionPolicy.parse(
            capture_policy_effective or requested_policy.storage_name
        )
        if effective_policy < requested_policy:
            raise CalibrationStoreValidationError(
                "effective capture policy cannot be lower than the requested policy"
            )
        run_id = str(process_run_id or "").strip()
        if not run_id:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_id = f"run_{stamp}_{uuid.uuid4().hex[:8]}"
        if any(part in run_id for part in ("/", "\\", "..")):
            raise CalibrationStoreValidationError("process_run_id is not path-safe")
        run_dir = _ensure_contained(
            self.recordings_root / process / run_id,
            self.recordings_root,
            label="process run directory",
        )
        if run_dir.exists():
            raise CalibrationStoreConflictError(f"process run already exists: {run_id}")
        try:
            self._fault("start_run.mkdir")
            run_dir.mkdir(parents=True, exist_ok=False)
        except CalibrationStoreError:
            raise
        except Exception as exc:
            raise CalibrationStoreDurabilityError(
                f"could not create process run directory: {exc}"
            ) from exc
        updates_path = run_dir / "updates.jsonl"
        try:
            self._fault("start_run.updates_create")
            with updates_path.open("x", encoding="utf-8") as handle:
                handle.flush()
                os.fsync(handle.fileno())
        except CalibrationStoreError:
            raise
        except Exception as exc:
            raise CalibrationStoreDurabilityError(
                f"could not create updates.jsonl: {exc}"
            ) from exc
        run = CalibrationRunHandle(
            process_run_id=run_id,
            calibration_session_id=session_id,
            process_name=process,
            phase_name=phase,
            result_kind=kind,
            capture_policy_requested=requested_policy.storage_name,
            capture_policy_effective=effective_policy.storage_name,
            identity=_identity_snapshot(identity),
            started_at_utc=self._clock(),
            run_dir=run_dir,
            updates_path=updates_path,
            result_path=run_dir / "result.json",
            meta_path=run_dir / "run_meta.json",
            index_path=self.index_path,
            warnings=[dict(item) for item in warnings],
        )
        if run.warnings:
            run.shadow_state = "warning"
        self._atomic_json(
            run.meta_path,
            self._meta_document(run),
            stage="run_meta_start",
        )
        return run

    def append_update(
        self,
        run: CalibrationRunHandle,
        payload: Mapping[str, Any],
        *,
        phase_name: str | None = None,
        recorded_at_utc: str | None = None,
        legacy_source: Mapping[str, Any] | None = None,
        include_legacy_reference: bool = False,
    ) -> CanonicalUpdateV1:
        if run.finalized:
            raise CalibrationStoreConflictError("cannot append to a finalized run")
        normalized_payload = _normalize_json(dict(payload or {}))
        index = len(run.updates) + 1
        update_id = _stable_id("update", run.process_run_id, index)
        if include_legacy_reference:
            normalized_payload["canonical_storage_ref"] = {
                "schema_name": LEGACY_REF_SCHEMA_NAME,
                "schema_version": LEGACY_REF_SCHEMA_VERSION,
                "process_name": run.process_name,
                "process_run_id": run.process_run_id,
                "update_id": update_id,
                "update_index": index,
            }
        document = {
            "schema_name": UPDATE_SCHEMA_NAME,
            "schema_version": UPDATE_SCHEMA_VERSION,
            "update_id": update_id,
            "update_index": index,
            "recorded_at_utc": str(recorded_at_utc or self._clock()),
            "calibration_session_id": run.calibration_session_id,
            "process_run_id": run.process_run_id,
            "process_name": run.process_name,
            "phase_name": str(phase_name or run.phase_name),
            "payload_sha256": semantic_sha256(normalized_payload),
            "payload": normalized_payload,
        }
        if legacy_source is not None:
            document["legacy_source"] = _normalize_json(dict(legacy_source))
        self._append_jsonl(run.updates_path, document, stage="update_append")
        run.updates.append(document)
        return CanonicalUpdateV1(document)

    def record_parity(
        self,
        run: CalibrationRunHandle,
        *,
        update_id: str,
        legacy_payload: Mapping[str, Any],
    ) -> bool:
        matches = [row for row in run.updates if row.get("update_id") == update_id]
        if len(matches) != 1:
            raise CalibrationStoreConflictError(f"unknown update_id: {update_id}")
        run.parity_checked_count += 1
        observed = semantic_sha256(dict(legacy_payload))
        matched = observed == matches[0]["payload_sha256"]
        if matched:
            run.parity_matched_count += 1
        else:
            run.parity_mismatch_count += 1
            run.shadow_state = "warning"
            run.warnings.append(
                {
                    "kind": "legacy_parity_mismatch",
                    "update_id": update_id,
                    "canonical_payload_sha256": matches[0]["payload_sha256"],
                    "legacy_payload_sha256": observed,
                }
            )
        return matched

    def add_warning(
        self, run: CalibrationRunHandle, kind: str, **details: Any
    ) -> dict[str, Any]:
        warning = {"kind": str(kind), **_normalize_json(details)}
        run.warnings.append(warning)
        run.shadow_state = "warning"
        return warning

    @staticmethod
    def _updates_hash(updates: Iterable[Mapping[str, Any]]) -> str:
        return semantic_sha256(
            [
                {
                    "update_index": int(row["update_index"]),
                    "update_id": str(row["update_id"]),
                    "payload_sha256": str(row["payload_sha256"]),
                }
                for row in updates
            ]
        )

    def finalize_run(
        self,
        run: CalibrationRunHandle,
        *,
        outcome: str,
        error_message: str = "",
        summary_projection: Mapping[str, Any] | None = None,
        recorder_summary: Mapping[str, Any] | None = None,
    ) -> ResultCommit:
        if run.finalized and run.result is not None:
            result = TerminalResultV1(dict(run.result))
            return ResultCommit(result, None, 0.0, None)
        normalized_outcome = str(outcome or "error").strip().lower()
        if normalized_outcome not in _OUTCOMES:
            raise CalibrationStoreValidationError(
                f"invalid terminal outcome: {normalized_outcome}"
            )
        if (
            normalized_outcome == "completed"
            and run.result_kind == "calibration"
            and not run.updates
        ):
            normalized_outcome = "storage_error"
            self.add_warning(run, "completed_calibration_missing_update")
        if run.result is None:
            ended_at = self._clock()
            result_id = _stable_id("result", run.process_run_id)
            update_ids = [str(row["update_id"]) for row in run.updates]
            result_body = {
                "schema_name": RESULT_SCHEMA_NAME,
                "schema_version": RESULT_SCHEMA_VERSION,
                "result_id": result_id,
                "calibration_session_id": run.calibration_session_id,
                "process_run_id": run.process_run_id,
                "process_name": run.process_name,
                "phase_name": run.phase_name,
                "result_kind": run.result_kind,
                "outcome": normalized_outcome,
                "started_at_utc": run.started_at_utc,
                "ended_at_utc": ended_at,
                "identity": dict(run.identity),
                "capture_policy": run.capture_policy_effective,
                "update_count": len(run.updates),
                "update_ids": update_ids,
                "updates_sha256": self._updates_hash(run.updates),
                "final_update_id": update_ids[-1] if update_ids else None,
                "summary_projection": _normalize_json(dict(summary_projection or {})),
                "capture_evidence": _normalize_json(
                    {
                        key: (recorder_summary or {}).get(key, 0)
                        for key in (
                            "capture_requested_count",
                            "capture_saved_count",
                            "capture_omitted_count",
                            "capture_failed_count",
                            "pending_capture_write_count",
                        )
                    }
                ),
                "warnings": list(run.warnings),
            }
            result_document = {
                **result_body,
                "result_sha256": semantic_sha256(result_body),
            }
            run.result = result_document
        else:
            result_document = dict(run.result)
            if result_document.get("outcome") != normalized_outcome:
                raise CalibrationStoreConflictError(
                    "terminal retry changed the process outcome"
                )
            ended_at = str(result_document["ended_at_utc"])
            result_id = str(result_document["result_id"])
        result_started = time.perf_counter_ns()
        self._commit_json_once(
            run.result_path, result_document, stage="result_commit"
        )
        result_latency = (time.perf_counter_ns() - result_started) / 1_000_000.0
        relpath = run.result_path.relative_to(self.experiment_dir).as_posix()
        index_document = {
            "schema_name": INDEX_SCHEMA_NAME,
            "schema_version": INDEX_SCHEMA_VERSION,
            "event_kind": "result_committed",
            "index_event_id": _stable_id("index", run.process_run_id),
            "recorded_at_utc": ended_at,
            "calibration_session_id": run.calibration_session_id,
            "process_run_id": run.process_run_id,
            "result_id": result_id,
            "result_relpath": relpath,
            "result_sha256": result_document["result_sha256"],
            "process_name": run.process_name,
            "phase_name": run.phase_name,
            "result_kind": run.result_kind,
            "outcome": normalized_outcome,
            "identity_projection": dict(run.identity),
            "summary_projection": dict(result_document["summary_projection"]),
        }
        index_started = time.perf_counter_ns()
        self._append_index_once(index_document)
        index_latency = (time.perf_counter_ns() - index_started) / 1_000_000.0
        self._atomic_json(
            run.meta_path,
            self._meta_document(
                run,
                outcome=normalized_outcome,
                ended_at_utc=ended_at,
                error_message=error_message,
                result=result_document,
                recorder_summary=recorder_summary,
            ),
            stage="run_meta_finalize",
        )
        run.finalized = True
        return ResultCommit(
            TerminalResultV1(result_document),
            IndexEventV1(index_document),
            result_latency,
            index_latency,
        )

    @staticmethod
    def read_jsonl(
        path: str | Path, *, allow_incomplete_trailing_line: bool = False
    ) -> tuple[list[dict[str, Any]], bool]:
        source = Path(path)
        if not source.exists():
            return [], False
        raw = source.read_bytes()
        lines = raw.splitlines(keepends=True)
        rows: list[dict[str, Any]] = []
        ignored_tail = False
        for index, line in enumerate(lines):
            body = line.rstrip(b"\r\n")
            if not body.strip():
                continue
            try:
                value = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                is_incomplete_tail = index == len(lines) - 1 and not line.endswith(
                    (b"\n", b"\r")
                )
                if allow_incomplete_trailing_line and is_incomplete_tail:
                    ignored_tail = True
                    continue
                raise CalibrationStoreCorruptionError(
                    f"invalid JSONL at {source}:{index + 1}: {exc}"
                ) from exc
            if not isinstance(value, dict):
                raise CalibrationStoreCorruptionError(
                    f"JSONL row is not an object at {source}:{index + 1}"
                )
            rows.append(value)
        return rows, ignored_tail

    @classmethod
    def validate_run(cls, run_dir: str | Path) -> dict[str, Any]:
        directory = Path(run_dir).resolve()
        result_path = directory / "result.json"
        if not result_path.is_file():
            raise CalibrationStoreCorruptionError("terminal result is missing")
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CalibrationStoreCorruptionError(f"invalid result.json: {exc}") from exc
        if result.get("schema_name") != RESULT_SCHEMA_NAME:
            raise CalibrationStoreCorruptionError("result schema name is invalid")
        if result.get("schema_version") != RESULT_SCHEMA_VERSION:
            raise CalibrationStoreCorruptionError("result schema version is invalid")
        process_run_id = str(result.get("process_run_id") or "")
        if result.get("result_id") != _stable_id("result", process_run_id):
            raise CalibrationStoreCorruptionError("result identity is invalid")
        if result.get("result_kind") not in _RESULT_KINDS:
            raise CalibrationStoreCorruptionError("result kind is invalid")
        if result.get("outcome") not in _OUTCOMES:
            raise CalibrationStoreCorruptionError("result outcome is invalid")
        result_body = dict(result)
        expected_result_hash = str(result_body.pop("result_sha256", ""))
        if semantic_sha256(result_body) != expected_result_hash:
            raise CalibrationStoreCorruptionError("result hash mismatch")
        updates, ignored_tail = cls.read_jsonl(
            directory / "updates.jsonl", allow_incomplete_trailing_line=True
        )
        try:
            indexes = [int(row.get("update_index", 0)) for row in updates]
        except (TypeError, ValueError) as exc:
            raise CalibrationStoreCorruptionError("update index is invalid") from exc
        if indexes != list(range(1, len(updates) + 1)):
            raise CalibrationStoreCorruptionError("update indexes are not gap-free")
        seen = set()
        for row in updates:
            if (
                row.get("schema_name") != UPDATE_SCHEMA_NAME
                or row.get("schema_version") != UPDATE_SCHEMA_VERSION
            ):
                raise CalibrationStoreCorruptionError("update schema is invalid")
            if (
                str(row.get("process_run_id") or "") != process_run_id
                or row.get("calibration_session_id")
                != result.get("calibration_session_id")
                or row.get("process_name") != result.get("process_name")
            ):
                raise CalibrationStoreCorruptionError("update linkage is invalid")
            update_id = str(row.get("update_id") or "")
            if update_id != _stable_id("update", process_run_id, indexes[len(seen)]):
                raise CalibrationStoreCorruptionError("update identity is invalid")
            if update_id in seen:
                raise CalibrationStoreCorruptionError("duplicate update_id")
            seen.add(update_id)
            if semantic_sha256(row.get("payload")) != row.get("payload_sha256"):
                raise CalibrationStoreCorruptionError("update payload hash mismatch")
        if len(updates) != int(result.get("update_count", -1)):
            raise CalibrationStoreCorruptionError("result update_count mismatch")
        if [row.get("update_id") for row in updates] != result.get("update_ids"):
            raise CalibrationStoreCorruptionError("result update_ids mismatch")
        if cls._updates_hash(updates) != result.get("updates_sha256"):
            raise CalibrationStoreCorruptionError("result update chain hash mismatch")
        meta_path = directory / "run_meta.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CalibrationStoreCorruptionError(f"invalid run_meta.json: {exc}") from exc
        if (
            meta.get("schema_name") != RUN_META_SCHEMA_NAME
            or meta.get("schema_version") != RUN_META_SCHEMA_VERSION
        ):
            raise CalibrationStoreCorruptionError("run metadata schema is invalid")
        if (
            str(meta.get("process_run_id") or "") != process_run_id
            or meta.get("result_id") != result.get("result_id")
            or meta.get("result_sha256") != result.get("result_sha256")
            or meta.get("outcome") != result.get("outcome")
            or meta.get("canonical_update_count") != len(updates)
        ):
            raise CalibrationStoreCorruptionError("run metadata linkage is invalid")
        return {
            "result": result,
            "updates": updates,
            "run_meta": meta,
            "ignored_incomplete_trailing_update": ignored_tail,
        }

    def rebuild_index(self, *, output_path: str | Path | None = None) -> dict[str, Any]:
        destination = Path(output_path).resolve() if output_path else self.index_path
        _ensure_contained(destination, self.experiment_dir, label="rebuilt index")
        valid: list[dict[str, Any]] = []
        invalid: list[dict[str, str]] = []
        seen_results: dict[str, str] = {}
        pattern = self.recordings_root.glob("*/*/result.json")
        for result_path in sorted(pattern, key=lambda item: item.as_posix()):
            try:
                validated = self.validate_run(result_path.parent)
                result = validated["result"]
                result_id = str(result["result_id"])
                result_hash = str(result["result_sha256"])
                previous = seen_results.get(result_id)
                if previous is not None and previous != result_hash:
                    raise CalibrationStoreConflictError(
                        f"conflicting result identity: {result_id}"
                    )
                seen_results[result_id] = result_hash
                valid.append(
                    {
                        "schema_name": INDEX_SCHEMA_NAME,
                        "schema_version": INDEX_SCHEMA_VERSION,
                        "event_kind": "result_committed",
                        "index_event_id": _stable_id(
                            "index", str(result["process_run_id"])
                        ),
                        "recorded_at_utc": str(result["ended_at_utc"]),
                        "calibration_session_id": str(
                            result["calibration_session_id"]
                        ),
                        "process_run_id": str(result["process_run_id"]),
                        "result_id": result_id,
                        "result_relpath": result_path.relative_to(
                            self.experiment_dir
                        ).as_posix(),
                        "result_sha256": result_hash,
                        "process_name": str(result["process_name"]),
                        "phase_name": str(result["phase_name"]),
                        "result_kind": str(result["result_kind"]),
                        "outcome": str(result["outcome"]),
                        "identity_projection": dict(result.get("identity") or {}),
                        "summary_projection": dict(
                            result.get("summary_projection") or {}
                        ),
                    }
                )
            except CalibrationStoreError as exc:
                invalid.append(
                    {
                        "result_relpath": result_path.relative_to(
                            self.experiment_dir
                        ).as_posix(),
                        "error": str(exc),
                    }
                )
        valid.sort(key=lambda row: (row["recorded_at_utc"], row["result_id"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                for row in valid:
                    handle.write(
                        json.dumps(
                            row,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                            allow_nan=False,
                        )
                        + "\n"
                    )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
            temporary_name = None
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
        return {
            "index_path": str(destination),
            "valid_result_count": len(valid),
            "invalid_result_count": len(invalid),
            "invalid_results": invalid,
            "semantic_sha256": semantic_sha256(valid),
        }


__all__ = [
    "CaptureRetentionPolicy",
    "INDEX_SCHEMA_NAME",
    "LEGACY_REF_SCHEMA_NAME",
    "LEGACY_REF_SCHEMA_VERSION",
    "RESULT_SCHEMA_NAME",
    "RUN_META_SCHEMA_NAME",
    "UPDATE_SCHEMA_NAME",
    "CalibrationRecordingStore",
    "CalibrationRunHandle",
    "CalibrationStoreConflictError",
    "CalibrationStoreCorruptionError",
    "CalibrationStoreDurabilityError",
    "CalibrationStoreError",
    "CalibrationStoreValidationError",
    "CanonicalUpdateV1",
    "IndexEventV1",
    "ResultCommit",
    "TerminalResultV1",
    "canonical_json_bytes",
    "semantic_sha256",
]
