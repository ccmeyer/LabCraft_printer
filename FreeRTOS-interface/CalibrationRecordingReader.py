"""Qt-free primary reader for canonical calibration recordings.

Routine history reads are intentionally limited to calibration_index.jsonl and
calibration.json. Terminal bundles are opened only when a selection is resolved
or when explicit index repair is requested.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from CalibrationRecordingStore import (
    INDEX_SCHEMA_NAME,
    INDEX_SCHEMA_VERSION,
    LEGACY_REF_SCHEMA_NAME,
    LEGACY_REF_SCHEMA_VERSION,
    CalibrationRecordingStore,
    CalibrationStoreCorruptionError,
    canonical_json_bytes,
    semantic_sha256,
)
from CalibrationStorageContracts import (
    SUMMARY_PROJECTION_SCHEMA_NAME,
    SUMMARY_PROJECTION_SCHEMA_VERSION,
    materialize_characterization_rows,
)


class CalibrationReaderState(str, Enum):
    CANONICAL_ONLY = "canonical_only"
    LEGACY_ONLY = "legacy_only"
    MATCHING_DUAL = "matching_dual"
    CANONICAL_INVALID_LEGACY_FALLBACK = "canonical_invalid_legacy_fallback"
    PARITY_CONFLICT = "parity_conflict"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CalibrationReaderIssue:
    code: str
    message: str
    state: CalibrationReaderState
    process_run_id: str | None = None
    result_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "reader_state": self.state.value,
            "process_run_id": self.process_run_id,
            "result_id": self.result_id,
        }


@dataclass(frozen=True)
class CalibrationHistorySnapshot:
    rows: tuple[Mapping[str, Any], ...]
    issues: tuple[CalibrationReaderIssue, ...]
    diagnostics: Mapping[str, Any]


@dataclass(frozen=True)
class CalibrationSessionSnapshot:
    """Immutable secondary-reader view of one calibration session."""

    calibration_session_id: str
    reader_state: CalibrationReaderState
    result_refs: tuple[Mapping[str, Any], ...]
    phase_payloads: Mapping[str, tuple[Mapping[str, Any], ...]]
    issues: tuple[CalibrationReaderIssue, ...]
    diagnostics: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibration_session_id": self.calibration_session_id,
            "reader_state": self.reader_state.value,
            "result_refs": _thaw(self.result_refs),
            "phase_payloads": _thaw(self.phase_payloads),
            "issues": [issue.to_dict() for issue in self.issues],
            "diagnostics": _thaw(self.diagnostics),
        }


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, "") or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _authority_marked(run: Mapping[str, Any]) -> bool:
    return bool((run.get("canonical_storage") or {}).get("structured_persistence_required"))


def _legacy_step_rows(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    phases = (
        "pressure_sweep_characterization",
        "droplet_recheck",
        "droplet_search",
        "online_stream_calibration",
    )
    for run_ordinal, run in enumerate(list(document.get("runs") or [])):
        if not isinstance(run, Mapping):
            continue
        run_id = str(run.get("run_id") or "")
        for phase_key in phases:
            for step_ordinal, step in enumerate(list((run.get("steps") or {}).get(phase_key) or [])):
                if not isinstance(step, Mapping):
                    continue
                source = {
                    "source_run_id": run_id,
                    "source_phase_key": phase_key,
                    "source_step_index": step_ordinal,
                }
                reference = dict(step.get("canonical_storage_ref") or {})
                process_run_id = reference.get("process_run_id")
                update_id = reference.get("update_id")
                update_index = _safe_int(reference.get("update_index"))
                projected = materialize_characterization_rows(
                    step,
                    source,
                    process_run_id=str(process_run_id) if process_run_id else None,
                    update_id=str(update_id) if update_id else None,
                    update_index=update_index,
                    update_payload_sha256=semantic_sha256(step),
                )
                for row in projected:
                    row.update({
                        "run_id": run_id,
                        "calibration_session_id": run_id,
                        "legacy_run_ordinal": run_ordinal,
                        "legacy_authority_marked": _authority_marked(run),
                        "legacy_payload_sha256": semantic_sha256(step),
                        "legacy_reference_valid": bool(
                            reference.get("schema_name") == LEGACY_REF_SCHEMA_NAME
                            and _safe_int(reference.get("schema_version")) == LEGACY_REF_SCHEMA_VERSION
                            and process_run_id
                            and update_id
                            and update_index
                        ),
                        "canonical_identity": {
                            key: run.get(key)
                            for key in (
                                "printer_head_id", "stock_id", "reagent_name",
                                "stock_solution", "concentration",
                                "display_concentration", "units", "head_type",
                            )
                        },
                    })
                    rows.append(row)
    return rows


def _selection_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    if row.get("result_id") and row.get("update_id"):
        return (
            "canonical",
            str(row.get("result_id")),
            str(row.get("update_id")),
            _safe_int(row.get("row_ordinal")),
            _safe_int(row.get("source_pressure_index")),
        )
    return (
        "legacy",
        str(row.get("source_run_id") or row.get("run_id") or ""),
        str(row.get("source_phase_key") or ""),
        _safe_int(row.get("source_step_index")),
        _safe_int(row.get("source_pressure_index")),
    )


def _application_fingerprint(row: Mapping[str, Any]) -> str:
    fields = (
        "result_id", "result_sha256", "process_run_id", "update_id",
        "update_index", "update_payload_sha256", "row_ordinal",
        "source_run_id", "source_phase_key", "source_step_index",
        "source_pressure_index", "timestamp", "pw_us", "pressure_psi",
        "mean_nL", "valid", "printing_mode", "delay_us", "target_xyz",
    )
    return semantic_sha256({key: _thaw(row.get(key)) for key in fields})


class CalibrationRecordingReader:
    """Read compact history and resolve exact persisted calibration selections."""

    def __init__(
        self,
        experiment_dir: str | Path,
        *,
        primary: str = "canonical",
        allow_legacy_fallback: bool = True,
        include_migrated: bool | None = None,
    ):
        self.experiment_dir = Path(experiment_dir).expanduser().resolve()
        self.recordings_root = (self.experiment_dir / "calibration_recordings").resolve()
        self.index_path = (self.experiment_dir / "calibration_index.jsonl").resolve()
        self.legacy_path = (self.experiment_dir / "calibration.json").resolve()
        normalized = str(primary or "canonical").strip().lower()
        if normalized not in {"canonical", "legacy"}:
            raise ValueError("primary reader must be canonical or legacy")
        self.primary = normalized
        self.allow_legacy_fallback = bool(allow_legacy_fallback)
        self.include_migrated = (
            str(os.environ.get("LABCRAFT_CALIBRATION_MIGRATED_RESULTS", "1")).strip()
            != "0"
            if include_migrated is None
            else bool(include_migrated)
        )
        self.migration_manifest_path = (
            self.experiment_dir / "calibration_history_migration.json"
        ).resolve()
        self._history_cache_revision: Any = None
        self._history_cache: CalibrationHistorySnapshot | None = None

    def _legacy_document(self) -> dict[str, Any]:
        if not self.legacy_path.is_file():
            return {"schema_version": 1, "runs": []}
        try:
            value = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CalibrationStoreCorruptionError(f"invalid calibration.json: {exc}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("runs", []), list):
            raise CalibrationStoreCorruptionError("calibration.json has an invalid root")
        return value

    def _index_events(self) -> list[dict[str, Any]]:
        events, ignored_tail = CalibrationRecordingStore.read_jsonl(self.index_path)
        if ignored_tail:
            raise CalibrationStoreCorruptionError("canonical index has an incomplete tail")
        seen_events: dict[str, bytes] = {}
        seen_results: dict[str, str] = {}
        for ordinal, event in enumerate(events, 1):
            if (
                event.get("schema_name") != INDEX_SCHEMA_NAME
                or _safe_int(event.get("schema_version")) != INDEX_SCHEMA_VERSION
                or event.get("event_kind") != "result_committed"
            ):
                raise CalibrationStoreCorruptionError(f"invalid index event at line {ordinal}")
            event_id = str(event.get("index_event_id") or "")
            result_id = str(event.get("result_id") or "")
            result_hash = str(event.get("result_sha256") or "")
            run_id = str(event.get("process_run_id") or "")
            if not event_id or not result_id or not run_id or len(result_hash) != 64:
                raise CalibrationStoreCorruptionError(f"incomplete index identity at line {ordinal}")
            encoded = canonical_json_bytes(event)
            if event_id in seen_events:
                raise CalibrationStoreCorruptionError(f"duplicate index event {event_id}")
            if result_id in seen_results:
                raise CalibrationStoreCorruptionError(f"duplicate result identity {result_id}")
            seen_events[event_id] = encoded
            seen_results[result_id] = result_hash
        return [event for event in events if self._migration_event_available(event)]

    def _migration_manifest(self) -> dict[str, Any]:
        if not self.migration_manifest_path.is_file():
            return {}
        try:
            value = json.loads(self.migration_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        return dict(value) if isinstance(value, dict) else {}

    def _migration_event_available(self, event: Mapping[str, Any]) -> bool:
        provenance = dict(event.get("provenance") or {})
        if provenance.get("kind") != "historical_conversion":
            return True
        if not self.include_migrated:
            return False
        manifest = self._migration_manifest()
        if (
            manifest.get("schema_name")
            != "labcraft.calibration_history_migration_manifest"
            or manifest.get("schema_version") != 1
            or manifest.get("status") != "completed"
            or manifest.get("manifest_id") != provenance.get("manifest_id")
        ):
            return False
        matches = [
            row
            for row in list(manifest.get("generated") or ())
            if isinstance(row, Mapping)
            and row.get("item_id") == provenance.get("item_id")
            and row.get("result_id") == event.get("result_id")
            and row.get("result_sha256") == event.get("result_sha256")
        ]
        return len(matches) == 1

    def _migrated_nonapplicable_coordinates(self) -> set[tuple[str, str, int | None]]:
        if not self.include_migrated:
            return set()
        manifest = self._migration_manifest()
        if manifest.get("status") != "completed":
            return set()
        generated_ids = {
            str(row.get("item_id") or "")
            for row in list(manifest.get("generated") or ())
            if isinstance(row, Mapping)
        }
        return {
            (
                str(row.get("source_run_id") or ""),
                str(row.get("source_phase_key") or ""),
                _safe_int(row.get("source_step_index")),
            )
            for row in list(manifest.get("items") or ())
            if isinstance(row, Mapping)
            and str(row.get("item_id") or "") in generated_ids
            and str(row.get("outcome") or "") != "completed"
        }

    @staticmethod
    def _canonical_projection_rows(event: Mapping[str, Any]) -> list[dict[str, Any]]:
        projection = dict(event.get("summary_projection") or {})
        if not projection.get("application_eligible"):
            return []
        if (
            projection.get("schema_name") != SUMMARY_PROJECTION_SCHEMA_NAME
            or _safe_int(projection.get("schema_version")) != SUMMARY_PROJECTION_SCHEMA_VERSION
        ):
            return []
        rows = []
        for ordinal, projected in enumerate(list(projection.get("rows") or [])):
            if not isinstance(projected, Mapping):
                continue
            row = dict(projected)
            row.update({
                "result_id": str(event.get("result_id") or ""),
                "result_sha256": str(event.get("result_sha256") or ""),
                "process_run_id": str(event.get("process_run_id") or ""),
                "calibration_session_id": str(event.get("calibration_session_id") or ""),
                "row_ordinal": _safe_int(row.get("row_ordinal")) if row.get("row_ordinal") is not None else ordinal,
                "canonical_result_relpath": str(event.get("result_relpath") or ""),
                "canonical_identity": dict(event.get("identity_projection") or {}),
            })
            rows.append(row)
        return rows

    def history_snapshot(
        self,
        *,
        legacy_document: Mapping[str, Any] | None = None,
        cache_revision: Any = None,
    ) -> CalibrationHistorySnapshot:
        if (
            cache_revision is not None
            and self._history_cache is not None
            and cache_revision == self._history_cache_revision
        ):
            return self._history_cache
        issues: list[CalibrationReaderIssue] = []
        try:
            if legacy_document is None:
                legacy = self._legacy_document()
            elif not isinstance(legacy_document, Mapping) or not isinstance(
                legacy_document.get("runs", []), list
            ):
                raise CalibrationStoreCorruptionError(
                    "in-memory calibration document has an invalid root"
                )
            else:
                legacy = legacy_document
            legacy_rows = _legacy_step_rows(legacy)
        except CalibrationStoreCorruptionError as exc:
            legacy_rows = []
            issues.append(CalibrationReaderIssue("legacy_corrupt", str(exc), CalibrationReaderState.UNAVAILABLE))

        if self.primary == "legacy":
            rows = []
            for row in legacy_rows:
                item = dict(row)
                item["reader_state"] = CalibrationReaderState.LEGACY_ONLY.value
                item["selection_fingerprint"] = _application_fingerprint(item)
                rows.append(item)
            snapshot = self._snapshot(
                rows, issues, index_events=0, legacy_rows=len(legacy_rows)
            )
            return self._remember_snapshot(snapshot, cache_revision)

        try:
            events = self._index_events()
            index_error = None
        except CalibrationStoreCorruptionError as exc:
            events = []
            index_error = exc
            issues.append(CalibrationReaderIssue("index_invalid", str(exc), CalibrationReaderState.UNAVAILABLE))

        legacy_by_update: dict[str, list[dict[str, Any]]] = {}
        legacy_by_coordinate: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for row in legacy_rows:
            update_id = str(row.get("update_id") or "")
            if update_id:
                legacy_by_update.setdefault(update_id, []).append(row)
            coordinate = (
                str(row.get("source_run_id") or ""),
                str(row.get("source_phase_key") or ""),
                _safe_int(row.get("source_step_index")),
                _safe_int(row.get("source_pressure_index")),
            )
            legacy_by_coordinate.setdefault(coordinate, []).append(row)

        rows: list[dict[str, Any]] = []
        consumed_legacy: set[int] = set()
        for event in events:
            if event.get("outcome") != "completed" or event.get("result_kind") != "calibration":
                continue
            canonical_rows = self._canonical_projection_rows(event)
            if not canonical_rows:
                # Milestone 3 compatibility: materialize the matching referenced legacy step.
                candidate_legacy = [
                    item for item in legacy_rows
                    if str(item.get("process_run_id") or "") == str(event.get("process_run_id") or "")
                ]
                for legacy_row in candidate_legacy:
                    canonical = dict(legacy_row)
                    canonical.update({
                        "result_id": str(event.get("result_id") or ""),
                        "result_sha256": str(event.get("result_sha256") or ""),
                        "calibration_session_id": str(event.get("calibration_session_id") or canonical.get("source_run_id") or ""),
                        "canonical_result_relpath": str(event.get("result_relpath") or ""),
                        "canonical_identity": dict(event.get("identity_projection") or {}),
                    })
                    canonical_rows.append(canonical)

            for canonical in canonical_rows:
                update_id = str(canonical.get("update_id") or "")
                matches = legacy_by_update.get(update_id, [])
                matched = next((item for item in matches if _safe_int(item.get("source_pressure_index")) == _safe_int(canonical.get("source_pressure_index"))), None)
                projection_provenance = dict(
                    (event.get("summary_projection") or {}).get("provenance") or {}
                )
                if (
                    matched is None
                    and projection_provenance.get("kind") == "historical_conversion"
                ):
                    coordinate = (
                        str(canonical.get("source_run_id") or ""),
                        str(canonical.get("source_phase_key") or ""),
                        _safe_int(canonical.get("source_step_index")),
                        _safe_int(canonical.get("source_pressure_index")),
                    )
                    coordinate_matches = legacy_by_coordinate.get(coordinate, [])
                    if len(coordinate_matches) == 1:
                        matched = coordinate_matches[0]
                state = CalibrationReaderState.CANONICAL_ONLY
                if matched is not None:
                    consumed_legacy.add(id(matched))
                    expected_hash = str(canonical.get("update_payload_sha256") or "")
                    observed_hash = str(matched.get("legacy_payload_sha256") or "")
                    if expected_hash and expected_hash != observed_hash:
                        state = CalibrationReaderState.PARITY_CONFLICT
                        issues.append(CalibrationReaderIssue(
                            "parity_conflict",
                            "Canonical and legacy calibration payloads disagree.",
                            state,
                            str(event.get("process_run_id") or ""),
                            str(event.get("result_id") or ""),
                        ))
                    else:
                        state = CalibrationReaderState.MATCHING_DUAL
                        for key in ("source_run_id", "source_phase_key", "source_step_index", "source_pressure_index"):
                            canonical.setdefault(key, matched.get(key))
                canonical["reader_state"] = state.value
                canonical["blocked"] = state is CalibrationReaderState.PARITY_CONFLICT
                canonical["selection_fingerprint"] = _application_fingerprint(canonical)
                rows.append(canonical)

        nonapplicable_coordinates = self._migrated_nonapplicable_coordinates()
        for legacy_row in legacy_rows:
            if id(legacy_row) in consumed_legacy:
                continue
            if (
                str(legacy_row.get("source_run_id") or ""),
                str(legacy_row.get("source_phase_key") or ""),
                _safe_int(legacy_row.get("source_step_index")),
            ) in nonapplicable_coordinates:
                continue
            item = dict(legacy_row)
            if item.get("legacy_authority_marked"):
                state = CalibrationReaderState.UNAVAILABLE
                item["blocked"] = True
                message = "Authority-marked calibration is missing a valid committed index result."
                issues.append(CalibrationReaderIssue(
                    "authority_canonical_unavailable", message, state,
                    str(item.get("process_run_id") or "") or None,
                ))
            elif self.allow_legacy_fallback:
                state = (
                    CalibrationReaderState.CANONICAL_INVALID_LEGACY_FALLBACK
                    if index_error is not None or item.get("legacy_reference_valid")
                    else CalibrationReaderState.LEGACY_ONLY
                )
                item["blocked"] = False
            else:
                state = CalibrationReaderState.UNAVAILABLE
                item["blocked"] = True
                issues.append(CalibrationReaderIssue(
                    "legacy_fallback_disabled",
                    "Legacy calibration fallback is disabled.",
                    state,
                    str(item.get("process_run_id") or "") or None,
                ))
            item["reader_state"] = state.value
            item["selection_fingerprint"] = _application_fingerprint(item)
            rows.append(item)
        snapshot = self._snapshot(
            rows, issues, index_events=len(events), legacy_rows=len(legacy_rows)
        )
        return self._remember_snapshot(snapshot, cache_revision)

    def _remember_snapshot(self, snapshot, cache_revision):
        if cache_revision is not None:
            self._history_cache_revision = cache_revision
            self._history_cache = snapshot
        return snapshot

    def _snapshot(self, rows, issues, *, index_events: int, legacy_rows: int):
        diagnostics = {
            "primary": self.primary,
            "legacy_fallback_enabled": self.allow_legacy_fallback,
            "migrated_results_enabled": self.include_migrated,
            "index_path": str(self.index_path),
            "index_event_count": int(index_events),
            "legacy_row_count": int(legacy_rows),
            "row_count": len(rows),
            "issue_count": len(issues),
            "routine_result_bundle_reads": 0,
            "routine_recursive_scans": 0,
        }
        return CalibrationHistorySnapshot(
            tuple(_freeze(dict(row)) for row in rows),
            tuple(issues),
            _freeze(diagnostics),
        )

    def resolve_selection(
        self,
        selected_row: Mapping[str, Any],
        *,
        expected_identity: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = self.history_snapshot()
        key = _selection_key(selected_row)
        matches = [row for row in snapshot.rows if _selection_key(row) == key]
        if len(matches) != 1:
            legacy_key = (
                "legacy",
                str(selected_row.get("source_run_id") or selected_row.get("run_id") or ""),
                str(selected_row.get("source_phase_key") or ""),
                _safe_int(selected_row.get("source_step_index")),
                _safe_int(selected_row.get("source_pressure_index")),
            )
            blocked_legacy = [
                row for row in snapshot.rows
                if _selection_key(row) == legacy_key and row.get("blocked")
            ]
            if len(blocked_legacy) == 1:
                return {
                    "ok": False,
                    "code": "canonical_storage_unavailable",
                    "message": "The authority-marked canonical calibration is no longer committed in the index.",
                    "row": _thaw(blocked_legacy[0]),
                }
            return {"ok": False, "code": "selection_changed", "message": "The selected calibration is no longer uniquely available."}
        fresh = _thaw(matches[0])
        if fresh.get("selection_fingerprint") != selected_row.get("selection_fingerprint"):
            return {"ok": False, "code": "selection_changed", "message": "The selected calibration changed after it was displayed."}
        state = str(fresh.get("reader_state") or "")
        if fresh.get("blocked") or state in {CalibrationReaderState.PARITY_CONFLICT.value, CalibrationReaderState.UNAVAILABLE.value}:
            return {"ok": False, "code": state or "unavailable", "message": "The selected calibration is blocked by storage integrity checks.", "row": fresh}
        if state in {CalibrationReaderState.LEGACY_ONLY.value, CalibrationReaderState.CANONICAL_INVALID_LEGACY_FALLBACK.value}:
            return {"ok": True, "code": state, "message": "", "row": fresh, "bundle": None}

        relpath = Path(str(fresh.get("canonical_result_relpath") or ""))
        result_path = (self.experiment_dir / relpath).resolve()
        if self.experiment_dir not in result_path.parents or result_path.name != "result.json":
            return {"ok": False, "code": "path_escape", "message": "The canonical result path is outside the experiment."}
        try:
            validated = CalibrationRecordingStore.validate_run(result_path.parent)
            result = dict(validated["result"])
            meta = dict(validated.get("run_meta") or {})
            provenance = dict(result.get("provenance") or {})
            if provenance.get("kind") == "historical_conversion":
                matching_event = {
                    "result_id": result.get("result_id"),
                    "result_sha256": result.get("result_sha256"),
                    "provenance": provenance,
                }
                if not self._migration_event_available(matching_event):
                    raise CalibrationStoreCorruptionError(
                        "historical conversion manifest does not validate the result"
                    )
            if result.get("result_id") != fresh.get("result_id") or result.get("result_sha256") != fresh.get("result_sha256"):
                raise CalibrationStoreCorruptionError("result identity or hash changed")
            update_matches = [item for item in validated["updates"] if item.get("update_id") == fresh.get("update_id")]
            if len(update_matches) != 1:
                raise CalibrationStoreCorruptionError("selected update does not resolve uniquely")
            update = dict(update_matches[0])
            if fresh.get("update_payload_sha256") and update.get("payload_sha256") != fresh.get("update_payload_sha256"):
                raise CalibrationStoreCorruptionError("selected update hash changed")
            if (
                result.get("outcome") != "completed"
                or result.get("result_kind") != "calibration"
                or not bool((result.get("summary_projection") or {}).get("application_eligible"))
                or int(meta.get("parity_mismatch_count") or 0) != 0
                or int(meta.get("parity_checked_count") or 0) != int(meta.get("parity_matched_count") or 0)
            ):
                raise CalibrationStoreCorruptionError("canonical result is not application eligible")
            events = self._index_events()
            committed = [event for event in events if event.get("result_id") == result.get("result_id") and event.get("result_sha256") == result.get("result_sha256")]
            if len(committed) != 1:
                raise CalibrationStoreCorruptionError("result is not committed exactly once in the index")
            if expected_identity:
                observed = dict(result.get("identity") or {})
                for field in ("printer_head_id", "stock_id"):
                    expected = str(expected_identity.get(field) or "")
                    if expected and str(observed.get(field) or "") != expected:
                        raise CalibrationStoreCorruptionError(f"{field} no longer matches the loaded context")
        except (OSError, ValueError, CalibrationStoreCorruptionError) as exc:
            return {"ok": False, "code": "canonical_storage_unavailable", "message": f"Canonical calibration validation failed: {exc}"}
        return {"ok": True, "code": state, "message": "", "row": fresh, "bundle": {"result": result, "update": update, "run_meta": meta}}

    def rebuild_index(self, *, output_path: str | Path) -> dict[str, Any]:
        store = CalibrationRecordingStore(self.experiment_dir)
        return store.rebuild_index(output_path=output_path)

    def session_phase_payloads(
        self, calibration_session_id: str, phase_names: Iterable[str]
    ) -> list[dict[str, Any]]:
        """Load bounded prerequisite/recheck payloads from exact indexed bundles."""

        wanted = {str(item) for item in phase_names}
        payloads: list[dict[str, Any]] = []
        for event in self._index_events():
            if (
                str(event.get("calibration_session_id") or "") != str(calibration_session_id)
                or str(event.get("phase_name") or "") not in wanted
                or event.get("outcome") != "completed"
            ):
                continue
            result_path = (self.experiment_dir / str(event.get("result_relpath") or "")).resolve()
            if self.experiment_dir not in result_path.parents:
                raise CalibrationStoreCorruptionError("indexed result path escaped experiment")
            validated = CalibrationRecordingStore.validate_run(result_path.parent)
            result = dict(validated["result"])
            if result.get("result_id") != event.get("result_id") or result.get("result_sha256") != event.get("result_sha256"):
                raise CalibrationStoreCorruptionError("indexed result identity changed")
            payloads.extend(dict(update.get("payload") or {}) for update in validated["updates"])
        return payloads

    def resolve_session(
        self,
        calibration_session_id: str,
        *,
        expected_result_refs: Iterable[Mapping[str, Any]] | None = None,
        expected_identity: Mapping[str, Any] | None = None,
        legacy_run_id: str | None = None,
        legacy_run_index: int | None = None,
    ) -> CalibrationSessionSnapshot:
        """Resolve one session for secondary consumers without directory scans."""

        session_id = str(calibration_session_id or legacy_run_id or "").strip()
        requested_refs = [dict(item) for item in (expected_result_refs or ())]
        expected_by_result = {
            str(item.get("result_id") or ""): item
            for item in requested_refs
            if str(item.get("result_id") or "")
        }
        issues: list[CalibrationReaderIssue] = []
        result_refs: list[dict[str, Any]] = []
        phase_payloads: dict[str, list[dict[str, Any]]] = {}
        canonical_error: Exception | None = None
        index_event_count = 0
        bundle_read_count = 0
        migrated_updates: list[dict[str, Any]] = []

        try:
            events = self._index_events()
            matching = [
                dict(event)
                for event in events
                if str(event.get("calibration_session_id") or "") == session_id
            ]
            if expected_by_result:
                matching = [
                    event
                    for event in matching
                    if str(event.get("result_id") or "") in expected_by_result
                ]
                observed_ids = {str(event.get("result_id") or "") for event in matching}
                missing = sorted(set(expected_by_result) - observed_ids)
                if missing:
                    raise CalibrationStoreCorruptionError(
                        "referenced canonical results are missing from the index: "
                        + ", ".join(missing)
                    )
            index_event_count = len(matching)
            if not matching:
                raise CalibrationStoreCorruptionError(
                    f"canonical session is not committed: {session_id}"
                )
            for event in matching:
                relpath = Path(str(event.get("result_relpath") or ""))
                result_path = (self.experiment_dir / relpath).resolve()
                if (
                    self.experiment_dir not in result_path.parents
                    or result_path.name != "result.json"
                ):
                    raise CalibrationStoreCorruptionError(
                        "indexed result path escaped the experiment"
                    )
                validated = CalibrationRecordingStore.validate_run(result_path.parent)
                bundle_read_count += 1
                result = dict(validated["result"])
                meta = dict(validated.get("run_meta") or {})
                if (
                    result.get("result_id") != event.get("result_id")
                    or result.get("result_sha256") != event.get("result_sha256")
                    or result.get("calibration_session_id") != session_id
                ):
                    raise CalibrationStoreCorruptionError(
                        "indexed session result identity changed"
                    )
                expected = expected_by_result.get(str(result.get("result_id") or ""))
                if expected:
                    for field in ("process_run_id", "result_sha256"):
                        wanted = str(expected.get(field) or "")
                        if wanted and str(result.get(field) or "") != wanted:
                            raise CalibrationStoreCorruptionError(
                                f"referenced canonical {field} changed"
                            )
                if expected_identity:
                    observed_identity = dict(result.get("identity") or {})
                    for field in ("printer_head_id", "stock_id"):
                        wanted = str(expected_identity.get(field) or "")
                        if wanted and str(observed_identity.get(field) or "") != wanted:
                            raise CalibrationStoreCorruptionError(
                                f"canonical session {field} does not match"
                            )
                if int(meta.get("parity_mismatch_count") or 0) != 0:
                    raise CalibrationStoreCorruptionError(
                        "canonical session contains a parity mismatch"
                    )
                updates = [dict(item) for item in validated.get("updates") or ()]
                if dict(result.get("provenance") or {}).get("kind") == "historical_conversion":
                    migrated_updates.extend(updates)
                phase_name = str(result.get("phase_name") or event.get("phase_name") or "")
                if str(result.get("outcome") or "") == "completed":
                    phase_payloads.setdefault(phase_name, []).extend(
                        dict(update.get("payload") or {}) for update in updates
                    )
                result_refs.append(
                    {
                        "calibration_session_id": session_id,
                        "process_run_id": str(result.get("process_run_id") or ""),
                        "result_id": str(result.get("result_id") or ""),
                        "result_sha256": str(result.get("result_sha256") or ""),
                        "result_relpath": relpath.as_posix(),
                        "phase_name": phase_name,
                        "result_kind": str(result.get("result_kind") or ""),
                        "outcome": str(result.get("outcome") or ""),
                        "update_ids": [str(item.get("update_id") or "") for item in updates],
                    }
                )
        except (OSError, ValueError, CalibrationStoreCorruptionError) as exc:
            canonical_error = exc

        legacy_document: dict[str, Any] = {"runs": []}
        legacy_error: Exception | None = None
        try:
            legacy_document = self._legacy_document()
        except (OSError, ValueError, CalibrationStoreCorruptionError) as exc:
            legacy_error = exc
        runs = list(legacy_document.get("runs") or [])
        legacy_run = None
        wanted_legacy_id = str(legacy_run_id or session_id or "")
        if wanted_legacy_id:
            legacy_run = next(
                (
                    dict(run)
                    for run in reversed(runs)
                    if isinstance(run, Mapping)
                    and str(run.get("run_id") or "") == wanted_legacy_id
                ),
                None,
            )
        if legacy_run is None and legacy_run_index is not None:
            try:
                index = int(legacy_run_index)
                if 0 <= index < len(runs) and isinstance(runs[index], Mapping):
                    legacy_run = dict(runs[index])
            except (TypeError, ValueError):
                pass

        authority_marked = bool(legacy_run and _authority_marked(legacy_run))
        if canonical_error is None and legacy_run is not None and migrated_updates:
            try:
                legacy_steps = dict(legacy_run.get("steps") or {})
                for update in migrated_updates:
                    source = dict(update.get("legacy_source") or {})
                    phase = str(source.get("source_phase_key") or "")
                    step_index = _safe_int(source.get("source_step_index"))
                    phase_steps = list(legacy_steps.get(phase) or ())
                    if step_index is None or not 0 <= step_index < len(phase_steps):
                        raise CalibrationStoreCorruptionError(
                            "migrated update source coordinates no longer resolve"
                        )
                    if semantic_sha256(phase_steps[step_index]) != update.get(
                        "payload_sha256"
                    ):
                        raise CalibrationStoreCorruptionError(
                            "migrated update no longer matches calibration.json"
                        )
            except (TypeError, ValueError, CalibrationStoreCorruptionError) as exc:
                canonical_error = exc
        if canonical_error is None:
            state = CalibrationReaderState.CANONICAL_ONLY
            if legacy_run is not None:
                legacy_refs = {
                    str((step.get("canonical_storage_ref") or {}).get("update_id") or ""):
                    semantic_sha256(step)
                    for steps in dict(legacy_run.get("steps") or {}).values()
                    for step in list(steps or ())
                    if isinstance(step, Mapping)
                }
                canonical_updates = {
                    str(update_id)
                    for ref in result_refs
                    for update_id in list(ref.get("update_ids") or ())
                    if str(update_id)
                }
                if authority_marked and canonical_updates != set(legacy_refs):
                    state = CalibrationReaderState.PARITY_CONFLICT
                    issues.append(
                        CalibrationReaderIssue(
                            code="session_parity_conflict",
                            message="Canonical and legacy session update identities differ.",
                            state=state,
                        )
                    )
                    result_refs = []
                    phase_payloads = {}
                else:
                    state = CalibrationReaderState.MATCHING_DUAL
        elif legacy_run is not None and not authority_marked and self.allow_legacy_fallback:
            state = (
                CalibrationReaderState.LEGACY_ONLY
                if not self.index_path.exists()
                else CalibrationReaderState.CANONICAL_INVALID_LEGACY_FALLBACK
            )
            result_refs = []
            phase_payloads = {
                str(phase): [dict(step) for step in list(steps or ()) if isinstance(step, Mapping)]
                for phase, steps in dict(legacy_run.get("steps") or {}).items()
            }
            issues.append(
                CalibrationReaderIssue(
                    code="legacy_session_fallback",
                    message=str(canonical_error),
                    state=state,
                )
            )
        else:
            state = CalibrationReaderState.UNAVAILABLE
            issues.append(
                CalibrationReaderIssue(
                    code=(
                        "authority_marked_session_invalid"
                        if authority_marked
                        else "session_unavailable"
                    ),
                    message=str(canonical_error or legacy_error or "session unavailable"),
                    state=state,
                )
            )
            result_refs = []
            phase_payloads = {}

        result_refs.sort(
            key=lambda item: (
                str(item.get("phase_name") or ""),
                str(item.get("process_run_id") or ""),
            )
        )
        return CalibrationSessionSnapshot(
            calibration_session_id=session_id,
            reader_state=state,
            result_refs=tuple(_freeze(item) for item in result_refs),
            phase_payloads=_freeze(
                {key: tuple(_freeze(item) for item in value) for key, value in phase_payloads.items()}
            ),
            issues=tuple(issues),
            diagnostics=_freeze(
                {
                    "index_event_count": index_event_count,
                    "bundle_read_count": bundle_read_count,
                    "legacy_run_found": legacy_run is not None,
                    "calibration_json_reads": int(self.legacy_path.is_file()),
                    "recursive_scans": 0,
                }
            ),
        )


def repair_calibration_index(
    experiment_dir: str | Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or atomically apply an explicit canonical-index repair."""

    root = Path(experiment_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"experiment directory does not exist: {root}")
    index_path = root / "calibration_index.jsonl"
    descriptor, temporary_name = tempfile.mkstemp(prefix="calibration-index-rebuild-", suffix=".jsonl", dir=root)
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    store = CalibrationRecordingStore(root)
    try:
        report = store.rebuild_index(output_path=temporary)
        rebuilt_bytes = temporary.read_bytes()
        response = {
            **report,
            "experiment_dir": str(root),
            "index_path": str(index_path),
            "apply": bool(apply),
            "changed": (not index_path.exists() or index_path.read_bytes() != rebuilt_bytes),
            "backup_path": None,
        }
        if not apply:
            return response
        if int(report.get("invalid_result_count") or 0) != 0:
            raise CalibrationStoreCorruptionError(
                "refusing to apply an index rebuild with invalid canonical bundles"
            )
        if index_path.exists():
            old_bytes = index_path.read_bytes()
            backup = index_path.with_name(
                f"{index_path.name}.{hashlib.sha256(old_bytes).hexdigest()}.bak"
            )
            if not backup.exists():
                shutil.copyfile(index_path, backup)
            elif backup.read_bytes() != old_bytes:
                raise CalibrationStoreCorruptionError("existing index backup conflicts")
            response["backup_path"] = str(backup)
        os.replace(temporary, index_path)
        temporary = None
        return response
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


__all__ = [
    "CalibrationSessionSnapshot",
    "CalibrationHistorySnapshot",
    "CalibrationReaderIssue",
    "CalibrationReaderState",
    "CalibrationRecordingReader",
    "repair_calibration_index",
]
