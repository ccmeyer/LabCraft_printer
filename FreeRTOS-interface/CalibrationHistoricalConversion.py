"""Offline, additive conversion of historical calibration.json records.

This module is intentionally Qt-free.  It never rewrites calibration.json or
existing diagnostic recordings.  New canonical bundles remain inactive until
the migration manifest is durably marked completed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Callable, Mapping
import uuid

from CalibrationRecordingStore import (
    INDEX_SCHEMA_NAME,
    INDEX_SCHEMA_VERSION,
    LEGACY_REF_SCHEMA_NAME,
    LEGACY_REF_SCHEMA_VERSION,
    CalibrationRecordingStore,
    CalibrationStoreConflictError,
    CalibrationStoreCorruptionError,
    CalibrationStoreError,
    CalibrationStoreValidationError,
    canonical_json_bytes,
    semantic_sha256,
    stable_recording_id,
)
from CalibrationStorageContracts import build_terminal_summary, process_storage_contract


MANIFEST_SCHEMA_NAME = "labcraft.calibration_history_migration_manifest"
MANIFEST_SCHEMA_VERSION = 1
PROVENANCE_SCHEMA_NAME = "labcraft.calibration_recording.migration_provenance"
PROVENANCE_SCHEMA_VERSION = 1
MANIFEST_FILE_NAME = "calibration_history_migration.json"
MIGRATION_KIND = "historical_conversion"

_MIGRATION_NAMESPACE = uuid.UUID("b34420cb-d5a4-49fd-86ee-8dc6d46d0608")
_OUTCOMES = {"completed", "stopped", "error", "interrupted", "storage_error"}
_APPLICATION_PHASES = {
    "pressure_sweep_characterization",
    "droplet_recheck",
    "droplet_search",
    "online_stream_calibration",
}
_PHASE_PROCESS = {
    "head_prime": "HeadPrimeCalibrationProcess",
    "nozzle_position": "NozzlePositionCalibrationProcess",
    "nozzle_focus": "NozzleFocusCalibrationProcess",
    "droplet_emergence": "DropletEmergenceCalibrationProcess",
    "pressure_calibration": "PressureCalibrationProcess",
    "pre_breakup_morphology": "PreBreakupMorphologyCalibrationProcess",
    "pressure_scan": "PressureBandCalibrationProcess",
    "trajectory": "TrajectoryCalibrationProcess",
    "pressure_trajectory": "PressureTrajectoryCalibrationProcess",
    "pressure_sweep_characterization": "PressureSweepCharacterizationProcess",
    "droplet_recheck": "PressureSweepCharacterizationProcess",
    "droplet_search": "DropletSearchCalibrationProcess",
    "online_stream_calibration": "OnlineStreamCalibrationProcess",
}
_IDENTITY_FIELDS = (
    "printer_head_id",
    "stock_id",
    "reagent_name",
    "stock_solution",
    "concentration",
    "display_concentration",
    "units",
    "head_type",
)


class CalibrationHistoricalConversionError(RuntimeError):
    """Base error for offline historical conversion."""


class CalibrationHistoricalSourceError(CalibrationHistoricalConversionError):
    """Historical source data is invalid or changed during conversion."""


class CalibrationHistoricalConflictError(CalibrationHistoricalConversionError):
    """An existing generated identity contains different content."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationHistoricalSourceError(f"invalid {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise CalibrationHistoricalSourceError(f"{path.name} must contain an object")
    return value


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                dict(payload), handle, indent=2, sort_keys=True,
                ensure_ascii=False, allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_timestamp(value: Any) -> bool:
    text = _clean(value)
    if not text:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class MigrationEvidence:
    run_meta_relpath: str
    analysis_relpath: str
    analysis_line: int
    analysis_sha256: str
    recording_run_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_meta_relpath": self.run_meta_relpath,
            "analysis_relpath": self.analysis_relpath,
            "analysis_line": self.analysis_line,
            "analysis_sha256": self.analysis_sha256,
            "recording_run_id": self.recording_run_id,
        }


@dataclass
class MigrationItem:
    item_id: str
    disposition: str
    reason: str
    source_run_id: str
    source_run_index: int
    source_phase_key: str
    source_step_index: int
    source_payload_sha256: str
    timestamp: str | None
    outcome: str | None
    process_name: str | None
    process_run_id: str | None
    identity: dict[str, Any]
    payload: dict[str, Any] = field(repr=False)
    evidence: MigrationEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        value = {
            "item_id": self.item_id,
            "disposition": self.disposition,
            "reason": self.reason,
            "source_run_id": self.source_run_id,
            "source_run_index": self.source_run_index,
            "source_phase_key": self.source_phase_key,
            "source_step_index": self.source_step_index,
            "source_payload_sha256": self.source_payload_sha256,
            "timestamp": self.timestamp,
            "outcome": self.outcome,
            "process_name": self.process_name,
            "process_run_id": self.process_run_id,
            "identity": dict(self.identity),
            "recording_evidence": self.evidence.to_dict() if self.evidence else None,
        }
        return value


@dataclass(frozen=True)
class MigrationPlan:
    manifest_id: str
    experiment_dir: str
    calibration_sha256: str
    source_files: Mapping[str, str]
    items: tuple[MigrationItem, ...]
    recording_scan_count: int
    recording_issue_count: int

    @property
    def counts(self) -> dict[str, int]:
        values: dict[str, int] = {}
        for item in self.items:
            values[item.disposition] = values.get(item.disposition, 0) + 1
        return {
            "source_step_count": len(self.items),
            "convert_count": values.get("convert", 0),
            "already_canonical_count": values.get("already_canonical", 0),
            "already_generated_count": values.get("already_generated", 0),
            "skipped_count": values.get("skipped", 0),
            "conflict_count": values.get("conflict", 0),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "experiment_dir": self.experiment_dir,
            "calibration_sha256": self.calibration_sha256,
            "source_files": dict(self.source_files),
            "recording_scan_count": self.recording_scan_count,
            "recording_issue_count": self.recording_issue_count,
            "counts": self.counts,
            "items": [item.to_dict() for item in self.items],
        }


ProgressCallback = Callable[[str, int, int, Mapping[str, Any]], None]
FaultHook = Callable[[str], None]


class CalibrationHistoricalConverter:
    """Plan, apply, resume, and validate one explicit historical experiment."""

    def __init__(
        self,
        experiment_dir: str | Path,
        *,
        progress_callback: ProgressCallback | None = None,
        fault_hook: FaultHook | None = None,
    ):
        self.experiment_dir = Path(experiment_dir).expanduser().resolve()
        self.calibration_path = self.experiment_dir / "calibration.json"
        self.recordings_root = self.experiment_dir / "calibration_recordings"
        self.index_path = self.experiment_dir / "calibration_index.jsonl"
        self.manifest_path = self.experiment_dir / MANIFEST_FILE_NAME
        self._progress_callback = progress_callback
        self._fault_hook = fault_hook
        self._last_progress_at = time.monotonic()
        if not self.experiment_dir.is_dir():
            raise CalibrationHistoricalSourceError(
                f"experiment directory does not exist: {self.experiment_dir}"
            )
        if not self.calibration_path.is_file():
            raise CalibrationHistoricalSourceError(
                f"calibration.json not found in: {self.experiment_dir}"
            )

    def _progress(
        self, stage: str, completed: int, total: int, **details: Any
    ) -> None:
        self._last_progress_at = time.monotonic()
        if self._progress_callback is not None:
            self._progress_callback(stage, completed, total, details)

    def _fault(self, stage: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(stage)

    def _relative(self, path: Path) -> str:
        resolved = path.resolve()
        if self.experiment_dir not in resolved.parents:
            raise CalibrationHistoricalSourceError(
                f"source path escaped experiment: {path}"
            )
        return resolved.relative_to(self.experiment_dir).as_posix()

    def _index_events(self) -> list[dict[str, Any]]:
        events, ignored_tail = CalibrationRecordingStore.read_jsonl(self.index_path)
        if ignored_tail:
            raise CalibrationHistoricalSourceError(
                "canonical index has an incomplete trailing event; repair it explicitly"
            )
        seen_events: set[str] = set()
        seen_results: set[str] = set()
        for ordinal, event in enumerate(events, 1):
            if (
                event.get("schema_name") != INDEX_SCHEMA_NAME
                or event.get("schema_version") != INDEX_SCHEMA_VERSION
                or event.get("event_kind") != "result_committed"
            ):
                raise CalibrationHistoricalSourceError(
                    f"invalid canonical index event at line {ordinal}"
                )
            event_id = str(event.get("index_event_id") or "")
            result_id = str(event.get("result_id") or "")
            if not event_id or event_id in seen_events:
                raise CalibrationHistoricalSourceError(
                    f"missing or duplicate canonical index event at line {ordinal}"
                )
            if not result_id or result_id in seen_results:
                raise CalibrationHistoricalSourceError(
                    f"missing or duplicate canonical result at line {ordinal}"
                )
            seen_events.add(event_id)
            seen_results.add(result_id)
        return events

    def _scan_recording_evidence(
        self,
    ) -> tuple[dict[tuple[str, str, str], list[MigrationEvidence]], dict[str, str], set[str], int]:
        candidates: dict[tuple[str, str, str], list[MigrationEvidence]] = {}
        source_hashes: dict[str, str] = {}
        invalid_phases: set[str] = set()
        run_meta_paths = sorted(self.recordings_root.glob("*/*/run_meta.json"))
        self._progress("inventory", 0, len(run_meta_paths))
        for ordinal, meta_path in enumerate(run_meta_paths, 1):
            try:
                meta = _read_json(meta_path)
            except CalibrationHistoricalSourceError:
                self._progress("inventory", ordinal, len(run_meta_paths))
                continue
            provenance = dict(meta.get("provenance") or {})
            if provenance.get("kind") == MIGRATION_KIND:
                self._progress("inventory", ordinal, len(run_meta_paths))
                continue
            analysis_path = meta_path.parent / "analysis.jsonl"
            if not analysis_path.is_file():
                self._progress("inventory", ordinal, len(run_meta_paths))
                continue
            phase_hint = str(meta.get("phase_name") or "").strip()
            meta_rel = self._relative(meta_path)
            analysis_rel = self._relative(analysis_path)
            source_hashes[meta_rel] = file_sha256(meta_path)
            analysis_hash = file_sha256(analysis_path)
            source_hashes[analysis_rel] = analysis_hash
            try:
                with analysis_path.open("r", encoding="utf-8") as handle:
                    for line_number, raw in enumerate(handle, 1):
                        if not raw.strip():
                            continue
                        row = json.loads(raw)
                        if not isinstance(row, dict) or row.get("kind") != "calibration_data_updated":
                            continue
                        payload = row.get("payload")
                        if not isinstance(payload, dict):
                            continue
                        phase = str(row.get("phase") or payload.get("phase") or phase_hint).strip()
                        session_id = str((payload.get("meta") or {}).get("run_id") or "").strip()
                        if not session_id or not phase:
                            continue
                        key = (session_id, phase, semantic_sha256(payload))
                        candidates.setdefault(key, []).append(
                            MigrationEvidence(
                                run_meta_relpath=meta_rel,
                                analysis_relpath=analysis_rel,
                                analysis_line=line_number,
                                analysis_sha256=analysis_hash,
                                recording_run_id=str(meta.get("run_id") or meta_path.parent.name),
                            )
                        )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                if phase_hint:
                    invalid_phases.add(phase_hint)
            self._progress("inventory", ordinal, len(run_meta_paths))
        return candidates, source_hashes, invalid_phases, len(run_meta_paths)

    @staticmethod
    def _identity(run: Mapping[str, Any], payload: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
        meta = dict(payload.get("meta") or {})
        identity: dict[str, Any] = {}
        for field_name in _IDENTITY_FIELDS:
            run_value = _clean(run.get(field_name))
            meta_value = _clean(meta.get(field_name))
            if run_value and meta_value and run_value != meta_value:
                return {}, f"identity_conflict:{field_name}"
            identity[field_name] = run_value or meta_value
        return identity, None

    def _existing_reference_state(
        self, payload: Mapping[str, Any], source_hash: str
    ) -> tuple[str, str]:
        reference = dict(payload.get("canonical_storage_ref") or {})
        if not reference:
            return "", ""
        if (
            reference.get("schema_name") != LEGACY_REF_SCHEMA_NAME
            or reference.get("schema_version") != LEGACY_REF_SCHEMA_VERSION
        ):
            return "conflict", "invalid_existing_canonical_reference"
        process_name = str(reference.get("process_name") or "")
        process_run_id = str(reference.get("process_run_id") or "")
        update_id = str(reference.get("update_id") or "")
        run_dir = self.recordings_root / process_name / process_run_id
        try:
            validated = CalibrationRecordingStore.validate_run(run_dir)
            matches = [row for row in validated["updates"] if row.get("update_id") == update_id]
            if len(matches) != 1 or matches[0].get("payload_sha256") != source_hash:
                raise CalibrationStoreCorruptionError("referenced update does not match")
        except (OSError, CalibrationStoreError) as exc:
            return "conflict", f"invalid_existing_canonical_reference:{exc}"
        return "already_canonical", "valid_existing_canonical_reference"

    def plan(self) -> MigrationPlan:
        calibration_hash = file_sha256(self.calibration_path)
        document = _read_json(self.calibration_path)
        runs = document.get("runs")
        if not isinstance(runs, list):
            raise CalibrationHistoricalSourceError("calibration.json runs must be a list")
        self._index_events()
        evidence, evidence_hashes, invalid_phases, recording_scan_count = (
            self._scan_recording_evidence()
        )
        manifest_id = "calibration-history-" + calibration_hash[:24]
        source_files = {"calibration.json": calibration_hash, **evidence_hashes}
        seen_run_ids: dict[str, int] = {}
        for run in runs:
            if isinstance(run, Mapping):
                run_id = str(run.get("run_id") or "").strip()
                if run_id:
                    seen_run_ids[run_id] = seen_run_ids.get(run_id, 0) + 1
        raw_steps = sum(
            len(steps or ())
            for run in runs if isinstance(run, Mapping)
            for steps in dict(run.get("steps") or {}).values()
            if isinstance(steps, list)
        )
        items: list[MigrationItem] = []
        self._progress("plan", 0, raw_steps)
        completed = 0
        for run_index, raw_run in enumerate(runs):
            if not isinstance(raw_run, Mapping):
                continue
            run = dict(raw_run)
            run_id = str(run.get("run_id") or "").strip()
            outcome = str(run.get("outcome") or "").strip().lower()
            steps_by_phase = dict(run.get("steps") or {})
            for phase, raw_phase_steps in steps_by_phase.items():
                if not isinstance(raw_phase_steps, list):
                    continue
                phase_key = str(phase)
                for step_index, raw_step in enumerate(raw_phase_steps):
                    completed += 1
                    payload = dict(raw_step) if isinstance(raw_step, Mapping) else {}
                    payload_hash = semantic_sha256(payload)
                    item_id = f"run-{run_index}:phase-{phase_key}:step-{step_index}"
                    process_name = _PHASE_PROCESS.get(phase_key)
                    timestamp = _clean(payload.get("timestamp"))
                    identity, identity_error = self._identity(run, payload)
                    disposition = "convert"
                    reason = "eligible"
                    evidence_item = None
                    if not isinstance(raw_step, Mapping):
                        disposition, reason = "skipped", "step_not_object"
                    elif not run_id:
                        disposition, reason = "skipped", "missing_source_run_id"
                    elif seen_run_ids.get(run_id, 0) != 1:
                        disposition, reason = "skipped", "ambiguous_source_run_id"
                    elif process_name is None:
                        disposition, reason = "skipped", "unsupported_phase"
                    elif outcome not in _OUTCOMES:
                        disposition, reason = "skipped", "terminal_outcome_unknown"
                    elif not _is_timestamp(timestamp):
                        disposition, reason = "skipped", "timestamp_invalid"
                    elif identity_error:
                        disposition, reason = "skipped", identity_error
                    elif phase_key in _APPLICATION_PHASES and not (
                        _clean(identity.get("printer_head_id"))
                        and _clean(identity.get("stock_id"))
                    ):
                        disposition, reason = "skipped", "stable_application_identity_missing"
                    else:
                        reference_state, reference_reason = self._existing_reference_state(
                            payload, payload_hash
                        )
                        if reference_state:
                            disposition, reason = reference_state, reference_reason
                    candidate_key = (run_id, phase_key, payload_hash)
                    candidates = evidence.get(candidate_key, [])
                    if disposition == "convert":
                        if phase_key in invalid_phases:
                            disposition, reason = "skipped", "recording_evidence_invalid"
                        elif len(candidates) > 1:
                            disposition, reason = "skipped", "recording_link_ambiguous"
                        elif len(candidates) == 1:
                            evidence_item = candidates[0]
                            reason = "eligible_unique_recording_link"
                        else:
                            reason = "eligible_without_recording"
                    run_identity = (
                        f"{calibration_hash}:{run_id}:{phase_key}:{step_index}:{payload_hash}"
                    )
                    process_run_id = (
                        "migration_" + str(uuid.uuid5(_MIGRATION_NAMESPACE, run_identity))
                        if disposition == "convert"
                        else None
                    )
                    if process_run_id and process_name:
                        target = self.recordings_root / process_name / process_run_id
                        if target.exists():
                            try:
                                validated = CalibrationRecordingStore.validate_run(target)
                                result_provenance = dict(validated["result"].get("provenance") or {})
                                if (
                                    result_provenance.get("manifest_id") != manifest_id
                                    or result_provenance.get("item_id") != item_id
                                    or len(validated["updates"]) != 1
                                    or validated["updates"][0].get("payload_sha256") != payload_hash
                                ):
                                    raise CalibrationStoreConflictError("generated bundle differs")
                                disposition, reason = "already_generated", "identical_generated_bundle"
                            except CalibrationStoreError as exc:
                                disposition, reason = "conflict", f"generated_target_conflict:{exc}"
                    items.append(
                        MigrationItem(
                            item_id=item_id,
                            disposition=disposition,
                            reason=reason,
                            source_run_id=run_id,
                            source_run_index=run_index,
                            source_phase_key=phase_key,
                            source_step_index=step_index,
                            source_payload_sha256=payload_hash,
                            timestamp=timestamp,
                            outcome=outcome or None,
                            process_name=process_name,
                            process_run_id=process_run_id,
                            identity=identity,
                            payload=payload,
                            evidence=evidence_item,
                        )
                    )
                    self._progress("plan", completed, raw_steps, item_id=item_id)
        return MigrationPlan(
            manifest_id=manifest_id,
            experiment_dir=str(self.experiment_dir),
            calibration_sha256=calibration_hash,
            source_files=source_files,
            items=tuple(items),
            recording_scan_count=recording_scan_count,
            recording_issue_count=len(invalid_phases),
        )

    def _provenance(self, plan: MigrationPlan, item: MigrationItem) -> dict[str, Any]:
        return {
            "schema_name": PROVENANCE_SCHEMA_NAME,
            "schema_version": PROVENANCE_SCHEMA_VERSION,
            "kind": MIGRATION_KIND,
            "manifest_id": plan.manifest_id,
            "manifest_relpath": MANIFEST_FILE_NAME,
            "item_id": item.item_id,
            "source_calibration_relpath": "calibration.json",
            "source_calibration_sha256": plan.calibration_sha256,
            "source_run_id": item.source_run_id,
            "source_run_index": item.source_run_index,
            "source_phase_key": item.source_phase_key,
            "source_step_index": item.source_step_index,
            "source_payload_sha256": item.source_payload_sha256,
            "recording_evidence": item.evidence.to_dict() if item.evidence else None,
        }

    def _build_bundle(
        self, plan: MigrationPlan, item: MigrationItem
    ) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        assert item.process_name and item.process_run_id and item.timestamp and item.outcome
        temporary_root = Path(
            tempfile.mkdtemp(prefix=".calibration-history-migration-", dir=self.experiment_dir)
        )
        provenance = self._provenance(plan, item)
        try:
            store = CalibrationRecordingStore(
                temporary_root, clock=lambda: str(item.timestamp)
            )
            contract = process_storage_contract(item.process_name)
            run = store.start_run(
                calibration_session_id=item.source_run_id,
                process_name=item.process_name,
                phase_name=item.source_phase_key,
                result_kind=contract.result_kind,
                identity=item.identity,
                capture_policy_requested="structured_only",
                capture_policy_effective="structured_only",
                process_run_id=item.process_run_id,
                warnings=(
                    {
                        "kind": "historical_conversion",
                        "manifest_id": plan.manifest_id,
                        "item_id": item.item_id,
                    },
                ),
                provenance=provenance,
            )
            update = store.append_update(
                run,
                item.payload,
                phase_name=item.source_phase_key,
                recorded_at_utc=item.timestamp,
                legacy_source={
                    "source_run_id": item.source_run_id,
                    "source_phase_key": item.source_phase_key,
                    "source_step_index": item.source_step_index,
                },
            )
            if update.payload_sha256 != item.source_payload_sha256:
                raise CalibrationHistoricalConflictError(
                    f"canonical payload changed for {item.item_id}"
                )
            if not store.record_parity(
                run, update_id=update.update_id, legacy_payload=item.payload
            ):
                raise CalibrationHistoricalConflictError(
                    f"legacy parity failed for {item.item_id}"
                )
            summary = build_terminal_summary(item.process_name, contract, run, item.outcome)
            summary["provenance"] = {
                "kind": MIGRATION_KIND,
                "manifest_id": plan.manifest_id,
                "item_id": item.item_id,
            }
            commit = store.finalize_run(
                run,
                outcome=item.outcome,
                summary_projection=summary,
                recorder_summary={},
            )
            (run.run_dir / "events.jsonl").write_text("", encoding="utf-8")
            (run.run_dir / "analysis.jsonl").write_text("", encoding="utf-8")
            _atomic_json(
                run.run_dir / "verdict.json",
                {
                    "schema_version": 2,
                    "run_id": item.process_run_id,
                    "process_name": item.process_name,
                    "phase_name": item.source_phase_key,
                    "outcome": "success" if item.outcome == "completed" else item.outcome,
                    "failure_summary": "",
                    "suspected_cause": "",
                    "notes": "Generated by historical calibration conversion.",
                    "submitted_by": "migration",
                    "submitted_at_utc": item.timestamp,
                    "provenance": provenance,
                },
            )
            CalibrationRecordingStore.validate_run(run.run_dir)
            return temporary_root, dict(commit.result.document), dict(commit.index_event.document)
        except Exception:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise

    def _manifest_base(self, plan: MigrationPlan) -> dict[str, Any]:
        return {
            "schema_name": MANIFEST_SCHEMA_NAME,
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "manifest_id": plan.manifest_id,
            "status": "running",
            "created_at_utc": utc_now(),
            "completed_at_utc": None,
            "experiment_dir_name": self.experiment_dir.name,
            "source_files_before": dict(plan.source_files),
            "source_files_after": {},
            "source_unchanged": False,
            "counts": dict(plan.counts),
            "recording_scan_count": plan.recording_scan_count,
            "recording_issue_count": plan.recording_issue_count,
            "index_sha256_before": file_sha256(self.index_path) if self.index_path.is_file() else None,
            "index_sha256_after": None,
            "items": [item.to_dict() for item in plan.items],
            "generated": [],
            "errors": [],
        }

    def _rehash_sources(self, expected: Mapping[str, str]) -> dict[str, str]:
        observed: dict[str, str] = {}
        for relpath, expected_hash in expected.items():
            path = (self.experiment_dir / relpath).resolve()
            if self.experiment_dir not in path.parents or not path.is_file():
                raise CalibrationHistoricalSourceError(
                    f"historical source disappeared: {relpath}"
                )
            observed_hash = file_sha256(path)
            observed[relpath] = observed_hash
            if observed_hash != expected_hash:
                raise CalibrationHistoricalSourceError(
                    f"historical source changed during conversion: {relpath}"
                )
        return observed

    @staticmethod
    def _generated_record(
        experiment_dir: Path,
        item: MigrationItem,
        result: Mapping[str, Any],
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        run_dir = experiment_dir / str(event["result_relpath"])
        run_dir = run_dir.parent
        hashes = {
            path.name: file_sha256(path)
            for path in sorted(run_dir.iterdir(), key=lambda candidate: candidate.name)
            if path.is_file()
        }
        return {
            "item_id": item.item_id,
            "process_run_id": item.process_run_id,
            "result_id": result["result_id"],
            "result_sha256": result["result_sha256"],
            "result_relpath": event["result_relpath"],
            "index_event_id": event["index_event_id"],
            "file_sha256": hashes,
        }

    def apply(self, *, resume: bool = False) -> dict[str, Any]:
        if self.manifest_path.is_file():
            existing = _read_json(self.manifest_path)
            if existing.get("status") == "completed":
                return self.validate()
            if not resume:
                raise CalibrationHistoricalConflictError(
                    "an incomplete conversion exists; rerun with --resume"
                )
        plan = self.plan()
        if plan.counts["conflict_count"]:
            raise CalibrationHistoricalConflictError(
                "conversion plan contains generated or canonical conflicts"
            )
        if self.manifest_path.is_file():
            manifest = _read_json(self.manifest_path)
            if manifest.get("manifest_id") != plan.manifest_id:
                raise CalibrationHistoricalConflictError(
                    "incomplete manifest belongs to a different source snapshot"
                )
        else:
            manifest = self._manifest_base(plan)
            _atomic_json(self.manifest_path, manifest)
        generated_by_item = {
            str(row.get("item_id")): dict(row)
            for row in manifest.get("generated", [])
            if isinstance(row, Mapping)
        }
        index_events: dict[str, dict[str, Any]] = {}
        convertible = [
            item for item in plan.items
            if item.disposition in {"convert", "already_generated"}
        ]
        self._progress("bundle_commit", 0, len(convertible))
        try:
            for ordinal, item in enumerate(convertible, 1):
                assert item.process_name and item.process_run_id
                target_dir = self.recordings_root / item.process_name / item.process_run_id
                if target_dir.exists():
                    validated = CalibrationRecordingStore.validate_run(target_dir)
                    result = dict(validated["result"])
                    event = self._event_for_result(result, target_dir)
                else:
                    temporary_root, result, event = self._build_bundle(plan, item)
                    temporary_dir = (
                        temporary_root / "calibration_recordings" /
                        item.process_name / item.process_run_id
                    )
                    target_dir.parent.mkdir(parents=True, exist_ok=True)
                    self._fault("before_bundle_publish")
                    os.replace(temporary_dir, target_dir)
                    self._fault("after_bundle_publish")
                    shutil.rmtree(temporary_root, ignore_errors=True)
                index_events[item.item_id] = event
                generated_by_item[item.item_id] = self._generated_record(
                    self.experiment_dir, item, result, event
                )
                manifest["generated"] = [
                    generated_by_item[key] for key in sorted(generated_by_item)
                ]
                _atomic_json(self.manifest_path, manifest)
                self._progress("bundle_commit", ordinal, len(convertible), item_id=item.item_id)
            observed_sources = self._rehash_sources(plan.source_files)
            self._fault("after_source_rehash")
            target_store = CalibrationRecordingStore(self.experiment_dir)
            self._progress("index_commit", 0, len(index_events))
            for ordinal, item_id in enumerate(sorted(index_events), 1):
                target_store.commit_index_event(index_events[item_id])
                self._fault("after_index_commit")
                self._progress("index_commit", ordinal, len(index_events), item_id=item_id)
            manifest["source_files_after"] = observed_sources
            manifest["source_unchanged"] = observed_sources == dict(plan.source_files)
            manifest["index_sha256_after"] = (
                file_sha256(self.index_path) if self.index_path.is_file() else None
            )
            manifest["status"] = "completed"
            manifest["completed_at_utc"] = utc_now()
            self._fault("before_manifest_complete")
            _atomic_json(self.manifest_path, manifest)
            self._fault("after_manifest_complete")
            return self.validate()
        except Exception as exc:
            manifest["status"] = "interrupted"
            manifest.setdefault("errors", []).append(
                {"recorded_at_utc": utc_now(), "message": str(exc)}
            )
            try:
                _atomic_json(self.manifest_path, manifest)
            except Exception:
                pass
            raise

    def resume(self) -> dict[str, Any]:
        return self.apply(resume=True)

    def _event_for_result(
        self, result: Mapping[str, Any], run_dir: Path
    ) -> dict[str, Any]:
        return {
            "schema_name": INDEX_SCHEMA_NAME,
            "schema_version": INDEX_SCHEMA_VERSION,
            "event_kind": "result_committed",
            "index_event_id": stable_recording_id(
                "index", str(result["process_run_id"])
            ),
            "recorded_at_utc": str(result["ended_at_utc"]),
            "calibration_session_id": str(result["calibration_session_id"]),
            "process_run_id": str(result["process_run_id"]),
            "result_id": str(result["result_id"]),
            "result_relpath": (run_dir / "result.json").relative_to(
                self.experiment_dir
            ).as_posix(),
            "result_sha256": str(result["result_sha256"]),
            "process_name": str(result["process_name"]),
            "phase_name": str(result["phase_name"]),
            "result_kind": str(result["result_kind"]),
            "outcome": str(result["outcome"]),
            "identity_projection": dict(result.get("identity") or {}),
            "summary_projection": dict(result.get("summary_projection") or {}),
            "provenance": dict(result.get("provenance") or {}),
        }

    def validate(self) -> dict[str, Any]:
        if not self.manifest_path.is_file():
            raise CalibrationHistoricalSourceError("conversion manifest is missing")
        manifest = _read_json(self.manifest_path)
        if (
            manifest.get("schema_name") != MANIFEST_SCHEMA_NAME
            or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
            or manifest.get("status") != "completed"
        ):
            raise CalibrationHistoricalSourceError(
                "conversion manifest is not complete"
            )
        self._progress("validate", 0, len(manifest.get("generated") or []))
        observed_sources = self._rehash_sources(
            dict(manifest.get("source_files_before") or {})
        )
        events = self._index_events()
        by_result = {
            str(event.get("result_id")): event for event in events
        }
        generated = list(manifest.get("generated") or [])
        for ordinal, row in enumerate(generated, 1):
            result_path = self.experiment_dir / str(row.get("result_relpath") or "")
            validated = CalibrationRecordingStore.validate_run(result_path.parent)
            result = dict(validated["result"])
            if (
                result.get("result_id") != row.get("result_id")
                or result.get("result_sha256") != row.get("result_sha256")
                or len(validated.get("updates") or []) != 1
            ):
                raise CalibrationHistoricalConflictError(
                    f"generated bundle changed: {row.get('item_id')}"
                )
            event = by_result.get(str(result.get("result_id")))
            if (
                event is None
                or event.get("result_sha256") != result.get("result_sha256")
                or event.get("index_event_id") != row.get("index_event_id")
            ):
                raise CalibrationHistoricalConflictError(
                    f"generated result is not committed exactly once: {row.get('item_id')}"
                )
            expected_hashes = dict(row.get("file_sha256") or {})
            for filename, expected_hash in expected_hashes.items():
                if file_sha256(result_path.parent / filename) != expected_hash:
                    raise CalibrationHistoricalConflictError(
                        f"generated file changed: {row.get('item_id')}:{filename}"
                    )
            self._progress("validate", ordinal, len(generated), item_id=row.get("item_id"))
        return {
            "status": "valid",
            "manifest_path": str(self.manifest_path),
            "manifest_id": manifest["manifest_id"],
            "source_unchanged": observed_sources
            == dict(manifest.get("source_files_before") or {}),
            "counts": dict(manifest.get("counts") or {}),
            "generated_count": len(generated),
            "index_event_count": len(events),
            "manifest_sha256": file_sha256(self.manifest_path),
        }


__all__ = [
    "MANIFEST_FILE_NAME",
    "MANIFEST_SCHEMA_NAME",
    "MANIFEST_SCHEMA_VERSION",
    "MIGRATION_KIND",
    "PROVENANCE_SCHEMA_NAME",
    "PROVENANCE_SCHEMA_VERSION",
    "CalibrationHistoricalConflictError",
    "CalibrationHistoricalConversionError",
    "CalibrationHistoricalConverter",
    "CalibrationHistoricalSourceError",
    "MigrationEvidence",
    "MigrationItem",
    "MigrationPlan",
    "file_sha256",
]
