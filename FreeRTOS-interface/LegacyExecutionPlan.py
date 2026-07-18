from __future__ import annotations

import csv
import json
import math
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from ExecutionPlan import (
    ExecutionDispense,
    ExecutionPlan,
    ExecutionPlanState,
    ExecutionPlanValidationError,
    ExecutionPlate,
    ExecutionStock,
    ExecutionVolumeBasis,
    ExecutionWell,
    canonical_sha256,
)


class LegacyExecutionClassification(str, Enum):
    UNRUN_DESIGN = "unrun_design"
    RECORDED_EXECUTION = "recorded_execution"


@dataclass(frozen=True)
class LegacyReconstructionIssue:
    severity: str
    code: str
    message: str
    context: Mapping[str, Any]


@dataclass(frozen=True)
class LegacyExecutionReconstruction:
    classification: LegacyExecutionClassification
    plan: ExecutionPlan | None
    progress: Mapping[str, Any]
    issues: tuple[LegacyReconstructionIssue, ...]
    source_evidence: tuple[Mapping[str, Any], ...]

    @property
    def has_fatal_issues(self) -> bool:
        return any(issue.severity == "fatal" for issue in self.issues)


_KEY_VOLUME_RE = re.compile(
    r"^(?P<stock_id>.+)_(?P<volume>[+]?(?:\d+(?:\.\d*)?|\.\d+))nL$",
    re.IGNORECASE,
)
_WELL_ID_RE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
_LEGACY_PLAN_NAMESPACE = uuid.UUID("a6a0cfa0-92aa-58b8-b0f2-3354fc6a8215")


def _issue(
    issues: list[LegacyReconstructionIssue],
    severity: str,
    code: str,
    message: str,
    **context: Any,
) -> None:
    issues.append(
        LegacyReconstructionIssue(
            severity=severity,
            code=code,
            message=message,
            context=dict(context),
        )
    )


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _file_time(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _read_progress(
    experiment_dir: Path,
    issues: list[LegacyReconstructionIssue],
) -> tuple[dict[str, Any], bool]:
    path = experiment_dir / "progress.json"
    if not path.exists():
        return {}, False
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _issue(
            issues,
            "fatal",
            "progress_unreadable",
            "The recorded progress file could not be read.",
            path=str(path),
            error=str(exc),
        )
        return {}, True
    if not isinstance(payload, dict):
        _issue(
            issues,
            "fatal",
            "progress_invalid_root",
            "The recorded progress file must contain a JSON object.",
            path=str(path),
        )
        return {}, True
    return payload, False


def _read_audit(
    experiment_dir: Path,
    issues: list[LegacyReconstructionIssue],
) -> list[dict[str, Any]]:
    path = experiment_dir / "experiment_audit.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    _issue(
                        issues,
                        "warning",
                        "audit_line_unreadable",
                        "An audit-log line was ignored because it is not valid JSON.",
                        line_number=line_number,
                    )
                    continue
                if isinstance(event, dict) and isinstance(event.get("event_type"), str):
                    events.append(event)
                else:
                    _issue(
                        issues,
                        "warning",
                        "audit_event_invalid",
                        "An audit-log event was ignored because it has no valid event type.",
                        line_number=line_number,
                    )
    except (OSError, UnicodeError) as exc:
        _issue(
            issues,
            "warning",
            "audit_unreadable",
            "The audit log could not be read; other execution evidence will still be used.",
            path=str(path),
            error=str(exc),
        )
    return events


def _applied_records(design_payload: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    root = design_payload.get("applied_imaging_calibrations")
    records = root.get("records") if isinstance(root, Mapping) else None
    if not isinstance(records, Mapping):
        return []
    return [
        (str(key), dict(value))
        for key, value in records.items()
        if isinstance(value, Mapping)
    ]


def _progress_wells(progress: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(well_id).strip().upper(): value
        for well_id, value in progress.items()
        if not str(well_id).startswith("__") and isinstance(value, Mapping)
    }


def _inspect_sources(
    experiment_dir: Path,
    design_payload: Mapping[str, Any],
) -> tuple[
    LegacyExecutionClassification,
    dict[str, Any],
    list[dict[str, Any]],
    list[tuple[str, dict[str, Any]]],
    list[LegacyReconstructionIssue],
    list[Mapping[str, Any]],
]:
    issues: list[LegacyReconstructionIssue] = []
    progress, progress_failed = _read_progress(experiment_dir, issues)
    audit_events = _read_audit(experiment_dir, issues)
    applied = _applied_records(design_payload)
    evidence: list[Mapping[str, Any]] = []

    if progress_failed:
        evidence.append({"source": "progress.json", "status": "unreadable"})

    positive_added = 0
    for well in _progress_wells(progress).values():
        reagents = well.get("reagents")
        if not isinstance(reagents, Mapping):
            continue
        for counts in reagents.values():
            if not isinstance(counts, Mapping):
                continue
            try:
                added = float(counts.get("added_droplets", 0) or 0)
            except (TypeError, ValueError):
                continue
            if math.isfinite(added) and added > 0:
                positive_added += 1
    if positive_added:
        evidence.append({"source": "progress.json", "positive_added_entries": positive_added})
    if applied:
        evidence.append({"source": "experiment_design.json", "applied_calibration_records": len(applied)})
    relevant_audit = [
        event
        for event in audit_events
        if str(event.get("event_type", "")).startswith(("calibration_process_", "print_array_"))
    ]
    if relevant_audit:
        evidence.append(
            {
                "source": "experiment_audit.jsonl",
                "relevant_event_count": len(relevant_audit),
                "event_types": sorted({str(event.get("event_type")) for event in relevant_audit}),
            }
        )

    classification = (
        LegacyExecutionClassification.RECORDED_EXECUTION
        if evidence
        else LegacyExecutionClassification.UNRUN_DESIGN
    )
    return classification, progress, audit_events, applied, issues, evidence


def inspect_legacy_execution(
    experiment_dir: str | os.PathLike[str],
    design_payload: Mapping[str, Any],
) -> LegacyExecutionReconstruction:
    classification, progress, _audit, _applied, issues, evidence = _inspect_sources(
        Path(experiment_dir), design_payload
    )
    return LegacyExecutionReconstruction(
        classification=classification,
        plan=None,
        progress=progress,
        issues=tuple(issues),
        source_evidence=tuple(evidence),
    )


def _parse_count(value: Any, *, location: str) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        raise ValueError(f"{location} must be a non-negative integer")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{location} must be numeric") from exc
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError(f"{location} must be a non-negative integer")
    return int(number)


def _parse_key(
    experiment_dir: Path,
    issues: list[LegacyReconstructionIssue],
    *,
    required: bool,
) -> tuple[dict[str, dict[str, int]], dict[str, float]]:
    path = experiment_dir / "key.csv"
    if not path.exists():
        return {}, {}
    wells: dict[str, dict[str, int]] = {}
    volumes: dict[str, float] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = list(reader.fieldnames or [])
            if not headers or headers[0].strip().lower() != "well id":
                raise ValueError("the first key column must be 'Well ID'")
            stock_headers: list[tuple[str, str]] = []
            for header in headers[1:]:
                match = _KEY_VOLUME_RE.fullmatch(str(header).strip())
                if match is None:
                    raise ValueError(f"key header {header!r} has no final '_<volume>nL' suffix")
                stock_id = match.group("stock_id")
                volume = float(match.group("volume"))
                if not math.isfinite(volume) or volume <= 0:
                    raise ValueError(f"key header {header!r} has an invalid dispense volume")
                if stock_id in volumes and not math.isclose(volumes[stock_id], volume):
                    raise ValueError(f"key contains conflicting columns for stock {stock_id!r}")
                volumes[stock_id] = volume
                stock_headers.append((header, stock_id))
            for row_number, row in enumerate(reader, start=2):
                well_id = str(row.get(headers[0], "") or "").strip().upper()
                if not well_id:
                    raise ValueError(f"key row {row_number} has no well ID")
                if well_id in wells:
                    raise ValueError(f"key contains duplicate well {well_id!r}")
                counts: dict[str, int] = {}
                for header, stock_id in stock_headers:
                    count = _parse_count(row.get(header), location=f"key row {row_number}, {header}")
                    if count:
                        counts[stock_id] = count
                wells[well_id] = counts
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        _issue(
            issues,
            "fatal" if required else "warning",
            "key_unreadable",
            "The legacy key could not be parsed into integral target counts.",
            path=str(path),
            error=str(exc),
        )
        return {}, {}
    return wells, volumes


def _parse_progress_targets(
    progress: Mapping[str, Any],
    issues: list[LegacyReconstructionIssue],
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]], dict[str, str]]:
    targets: dict[str, dict[str, int]] = {}
    added: dict[str, dict[str, int]] = {}
    reactions: dict[str, str] = {}
    for well_id, well in _progress_wells(progress).items():
        reaction_id = str(well.get("reaction_id") or "").strip()
        if not reaction_id:
            _issue(
                issues,
                "fatal",
                "progress_reaction_missing",
                "A recorded progress well has no reaction ID.",
                well_id=well_id,
            )
            continue
        reagents = well.get("reagents")
        if not isinstance(reagents, Mapping):
            _issue(
                issues,
                "fatal",
                "progress_reagents_invalid",
                "A recorded progress well has no valid reagent map.",
                well_id=well_id,
            )
            continue
        target_row: dict[str, int] = {}
        added_row: dict[str, int] = {}
        for stock_id, counts in reagents.items():
            stock_id = str(stock_id).strip()
            if not stock_id or not isinstance(counts, Mapping):
                _issue(
                    issues,
                    "fatal",
                    "progress_counts_invalid",
                    "A recorded progress reagent entry is invalid.",
                    well_id=well_id,
                    stock_id=stock_id,
                )
                continue
            try:
                target = _parse_count(
                    counts.get("target_droplets"),
                    location=f"progress {well_id}/{stock_id} target",
                )
                actual = _parse_count(
                    counts.get("added_droplets", 0),
                    location=f"progress {well_id}/{stock_id} added",
                )
            except ValueError as exc:
                _issue(
                    issues,
                    "fatal",
                    "progress_count_invalid",
                    str(exc),
                    well_id=well_id,
                    stock_id=stock_id,
                )
                continue
            if target:
                target_row[stock_id] = target
            if actual:
                added_row[stock_id] = actual
        targets[well_id] = target_row
        added[well_id] = added_row
        reactions[well_id] = reaction_id
    return targets, added, reactions


def _parse_stock_id(stock_id: str) -> tuple[str, float, str]:
    try:
        reagent, concentration_text, units = stock_id.rsplit("_", 2)
    except ValueError as exc:
        raise ValueError(f"stock ID {stock_id!r} does not contain reagent, concentration, and units") from exc
    reagent = reagent.strip()
    units = units.strip()
    try:
        concentration = float(concentration_text)
    except ValueError as exc:
        raise ValueError(f"stock ID {stock_id!r} has a non-numeric concentration") from exc
    if not reagent or not units or not math.isfinite(concentration) or concentration < 0:
        raise ValueError(f"stock ID {stock_id!r} is invalid")
    return reagent, concentration, units


def _option_candidates(
    design_payload: Mapping[str, Any], reagent: str, units: str
) -> list[tuple[str, str | None, Mapping[str, Any]]]:
    candidates: list[tuple[str, str | None, Mapping[str, Any]]] = []
    factors = design_payload.get("factors")
    if not isinstance(factors, list):
        return candidates
    for raw_factor in factors:
        if not isinstance(raw_factor, Mapping):
            continue
        factor_name = str(raw_factor.get("name") or "").strip()
        kind = str(raw_factor.get("kind") or "").strip()
        options = raw_factor.get("options")
        if not isinstance(options, list):
            continue
        for raw_option in options:
            if not isinstance(raw_option, Mapping):
                continue
            option_name = str(raw_option.get("name") or "").strip()
            option_units = str(raw_option.get("units") or "").strip()
            name_matches = option_name == reagent or (kind == "additive" and factor_name == reagent)
            if name_matches and option_units == units:
                candidates.append(
                    (factor_name or reagent, None if kind == "additive" else option_name, raw_option)
                )
    return candidates


def _calibration_for_stock(
    applied: list[tuple[str, dict[str, Any]]], stock_id: str
) -> tuple[str | None, dict[str, Any] | None]:
    matches = [(key, record) for key, record in applied if str(record.get("stock_id") or "") == stock_id]
    if not matches:
        return None, None
    matches.sort(
        key=lambda item: (
            _as_utc(item[1].get("recorded_at")) or _as_utc(item[1].get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
            item[0],
        )
    )
    return matches[-1]


def _plate_from_sources(
    progress: Mapping[str, Any],
    design_payload: Mapping[str, Any],
    issues: list[LegacyReconstructionIssue],
) -> ExecutionPlate | None:
    metadata = design_payload.get("metadata") if isinstance(design_payload.get("metadata"), Mapping) else {}
    design_values = (
        metadata.get("plate_name"),
        metadata.get("plate_rows"),
        metadata.get("plate_columns"),
    )
    progress_plate = progress.get("__plate__")
    if isinstance(progress_plate, Mapping):
        progress_values = (
            progress_plate.get("name"),
            progress_plate.get("rows"),
            progress_plate.get("columns"),
        )
        if all(value is not None for value in design_values) and progress_values != design_values:
            _issue(
                issues,
                "warning",
                "plate_metadata_mismatch",
                "Progress plate metadata differs from the design; progress metadata was used.",
                progress=dict(progress_plate),
                design={"name": design_values[0], "rows": design_values[1], "columns": design_values[2]},
            )
        chosen = progress_values
    else:
        chosen = design_values
    try:
        return ExecutionPlate(name=str(chosen[0]), rows=int(chosen[1]), columns=int(chosen[2]))
    except (TypeError, ValueError, ExecutionPlanValidationError) as exc:
        _issue(
            issues,
            "fatal",
            "plate_metadata_invalid",
            "No valid recorded plate identity is available.",
            error=str(exc),
        )
        return None


def _well_row_number(row_text: str) -> int:
    value = 0
    for char in row_text:
        value = value * 26 + ord(char) - ord("A") + 1
    return value


def _validate_well_identity(well_id: str, plate: ExecutionPlate) -> bool:
    match = _WELL_ID_RE.fullmatch(well_id)
    return bool(
        match
        and _well_row_number(match.group(1)) <= plate.rows
        and int(match.group(2)) <= plate.columns
    )


def _lifecycle_state(
    progress_targets: Mapping[str, Mapping[str, int]],
    progress_added: Mapping[str, Mapping[str, int]],
    audit_events: list[dict[str, Any]],
) -> ExecutionPlanState:
    if progress_targets and any(progress_targets.values()):
        complete = all(
            int(progress_added.get(well_id, {}).get(stock_id, 0)) >= int(target)
            for well_id, row in progress_targets.items()
            for stock_id, target in row.items()
        )
        if complete:
            return ExecutionPlanState.COMPLETED
    relevant = [
        event
        for event in audit_events
        if str(event.get("event_type", ""))
        in {"print_array_aborted", "print_array_completed"}
    ]
    relevant.sort(key=lambda event: _as_utc(event.get("timestamp_utc")) or datetime.min.replace(tzinfo=timezone.utc))
    if relevant and str(relevant[-1].get("event_type")) == "print_array_aborted":
        return ExecutionPlanState.ABORTED
    return ExecutionPlanState.ACTIVE


def _timestamps(
    experiment_dir: Path,
    audit_events: list[dict[str, Any]],
    applied: list[tuple[str, dict[str, Any]]],
) -> tuple[str, str, str, str]:
    relevant_audit = [
        event
        for event in audit_events
        if str(event.get("event_type", "")).startswith(("calibration_process_", "print_array_"))
    ]
    event_times = [
        timestamp
        for event in audit_events
        if (timestamp := _as_utc(event.get("timestamp_utc"))) is not None
    ]
    lock_times = [
        timestamp
        for event in relevant_audit
        if (timestamp := _as_utc(event.get("timestamp_utc"))) is not None
    ]
    calibration_times = [
        timestamp
        for _key, record in applied
        for timestamp in (_as_utc(record.get("recorded_at")) or _as_utc(record.get("timestamp")),)
        if timestamp is not None
    ]
    file_times = [
        timestamp
        for filename in ("experiment_design.json", "progress.json", "key.csv", "experiment_audit.jsonl")
        if (timestamp := _file_time(experiment_dir / filename)) is not None
    ]
    semantic_times = event_times + calibration_times
    now = datetime.now(timezone.utc)
    fallback_times = file_times or [now]
    created = min(semantic_times) if semantic_times else min(fallback_times)
    locked = (
        min(lock_times + calibration_times)
        if (lock_times or calibration_times)
        else min(fallback_times)
    )
    updated = max(semantic_times) if semantic_times else max(fallback_times)
    if locked < created:
        created = locked
    if updated < locked:
        updated = locked

    event_types = {str(event.get("event_type", "")) for event in relevant_audit}
    if any(event_type.startswith("print_array_") for event_type in event_types):
        reason = "legacy_printing_started"
    elif applied or any(event_type.startswith("calibration_process_") for event_type in event_types):
        reason = "legacy_calibration_started"
    else:
        reason = "legacy_execution_evidence"
    return _utc_text(created), _utc_text(updated), _utc_text(locked), reason


def reconstruct_legacy_execution(
    experiment_dir: str | os.PathLike[str],
    design_payload: Mapping[str, Any],
) -> LegacyExecutionReconstruction:
    directory = Path(experiment_dir)
    classification, progress, audit_events, applied, issues, evidence = _inspect_sources(
        directory, design_payload
    )
    if classification is LegacyExecutionClassification.UNRUN_DESIGN:
        return LegacyExecutionReconstruction(
            classification=classification,
            plan=None,
            progress=progress,
            issues=tuple(issues),
            source_evidence=tuple(evidence),
        )

    progress_targets, progress_added, reaction_ids = _parse_progress_targets(progress, issues)
    key_targets, key_volumes = _parse_key(
        directory,
        issues,
        required=not bool(progress_targets),
    )
    if progress_targets:
        target_wells = progress_targets
        for well_id in sorted(set(progress_targets) | set(key_targets)):
            if key_targets and progress_targets.get(well_id, {}) != key_targets.get(well_id, {}):
                _issue(
                    issues,
                    "warning",
                    "progress_key_target_mismatch",
                    "Progress and key targets differ; recorded progress targets were used.",
                    well_id=well_id,
                    progress_targets=dict(progress_targets.get(well_id, {})),
                    key_targets=dict(key_targets.get(well_id, {})),
                )
    else:
        target_wells = key_targets
        reaction_ids = {well_id: f"legacy_{well_id}" for well_id in key_targets}
        if target_wells:
            _issue(
                issues,
                "warning",
                "reaction_ids_reconstructed",
                "Progress contained no well entries; deterministic analysis-only reaction IDs were reconstructed from the key.",
            )

    if not target_wells:
        _issue(
            issues,
            "fatal",
            "targets_unavailable",
            "No progress or key targets are available for the recorded execution.",
        )

    plate = _plate_from_sources(progress, design_payload, issues)
    if plate is not None:
        for well_id in target_wells:
            if not _validate_well_identity(well_id, plate):
                _issue(
                    issues,
                    "fatal",
                    "well_identity_invalid",
                    "A recorded well is outside the saved plate or has an invalid identity.",
                    well_id=well_id,
                    plate={"name": plate.name, "rows": plate.rows, "columns": plate.columns},
                )

    stock_ids = sorted({stock_id for row in target_wells.values() for stock_id in row})
    metadata = design_payload.get("metadata") if isinstance(design_payload.get("metadata"), Mapping) else {}
    fill_name = str(metadata.get("fill_reagent_name") or "Water").strip()
    stocks: list[ExecutionStock] = []
    stock_lookup: dict[str, ExecutionStock] = {}
    for stock_id in stock_ids:
        try:
            reagent, parsed_concentration, units = _parse_stock_id(stock_id)
        except ValueError as exc:
            _issue(issues, "fatal", "stock_id_invalid", str(exc), stock_id=stock_id)
            continue

        is_fill = reagent == fill_name and units == "--"
        candidates = [] if is_fill else _option_candidates(design_payload, reagent, units)
        if len(candidates) > 1:
            _issue(
                issues,
                "warning",
                "stock_factor_mapping_ambiguous",
                "A stock matches multiple design options; its reagent name is used as the analysis display fallback.",
                stock_id=stock_id,
                candidates=[{"factor": factor, "option": option} for factor, option, _raw in candidates],
            )
            candidates = []
        if candidates:
            factor_name, option_name, raw_option = candidates[0]
            exact_concentration = raw_option.get("forced_stock_conc")
            if exact_concentration is None:
                concentration = parsed_concentration
                _issue(
                    issues,
                    "warning",
                    "stock_concentration_from_id",
                    "No exact persisted stock concentration was found; the rounded concentration encoded in the stock ID was used.",
                    stock_id=stock_id,
                )
            else:
                concentration = float(exact_concentration)
            volume_value = raw_option.get("droplet_nL")
            intended_value = raw_option.get("intended_droplet_nL")
            printing_mode = str(raw_option.get("printing_mode") or "droplet").strip().lower()
        elif is_fill:
            factor_name, option_name = fill_name, None
            concentration = parsed_concentration
            volume_value = metadata.get("fill_droplet_volume_nL")
            intended_value = metadata.get("intended_fill_droplet_volume_nL")
            printing_mode = str(metadata.get("fill_printing_mode") or "droplet").strip().lower()
        else:
            factor_name, option_name = reagent, None
            concentration = parsed_concentration
            volume_value = None
            intended_value = None
            printing_mode = "droplet"
            _issue(
                issues,
                "warning",
                "stock_factor_mapping_unavailable",
                "A stock could not be mapped uniquely to a design factor; its reagent name is used for analysis.",
                stock_id=stock_id,
            )
            _issue(
                issues,
                "warning",
                "stock_concentration_from_id",
                "No exact persisted stock concentration was found; the rounded concentration encoded in the stock ID was used.",
                stock_id=stock_id,
            )

        if volume_value is None:
            volume_value = key_volumes.get(stock_id)
            if volume_value is not None:
                _issue(
                    issues,
                    "warning",
                    "dispense_volume_from_key_header",
                    "No exact persisted dispense volume was found; the rounded key-header value was used.",
                    stock_id=stock_id,
                    volume_nL=volume_value,
                )
        try:
            effective_volume = float(volume_value)
            if not math.isfinite(effective_volume) or effective_volume <= 0:
                raise ValueError
        except (TypeError, ValueError):
            _issue(
                issues,
                "fatal",
                "dispense_volume_unavailable",
                "No valid effective dispense volume is available for a recorded stock.",
                stock_id=stock_id,
            )
            continue
        if printing_mode not in {"droplet", "stream"}:
            printing_mode = "stream" if effective_volume >= 40.0 else "droplet"
            _issue(
                issues,
                "warning",
                "printing_mode_inferred",
                "The saved printing mode was invalid; it was inferred from the effective dispense volume for analysis.",
                stock_id=stock_id,
                printing_mode=printing_mode,
            )

        record_key, record = _calibration_for_stock(applied, stock_id)
        try:
            stock = ExecutionStock(
                stock_id=stock_id,
                factor_name=factor_name,
                option_name=option_name,
                reagent_name=reagent,
                concentration=float(concentration),
                units=units,
                printing_mode=printing_mode,
                intended_volume_nL=(float(intended_value) if intended_value is not None else None),
                effective_volume_nL=effective_volume,
                printer_head_id=(str(record.get("printer_head_id")) if record and record.get("printer_head_id") else None),
                calibration_record_key=record_key,
            )
        except (ExecutionPlanValidationError, TypeError, ValueError) as exc:
            _issue(
                issues,
                "fatal",
                "stock_metadata_invalid",
                "A recorded stock has invalid persisted metadata.",
                stock_id=stock_id,
                error=str(exc),
            )
            continue
        stocks.append(stock)
        stock_lookup[stock_id] = stock

    wells: list[ExecutionWell] = []
    if plate is not None:
        for well_id, target_row in sorted(target_wells.items()):
            dispenses = tuple(
                ExecutionDispense(stock_id=stock_id, target_dispenses=int(count))
                for stock_id, count in sorted(target_row.items())
                if int(count) > 0 and stock_id in stock_lookup
            )
            expected = sum(
                dispense.target_dispenses * stock_lookup[dispense.stock_id].effective_volume_nL
                for dispense in dispenses
            )
            try:
                wells.append(
                    ExecutionWell(
                        well_id=well_id,
                        reaction_id=reaction_ids.get(well_id, f"legacy_{well_id}"),
                        dispenses=dispenses,
                        expected_printed_volume_nL=expected,
                    )
                )
            except ExecutionPlanValidationError as exc:
                _issue(
                    issues,
                    "fatal",
                    "well_plan_invalid",
                    "A recorded well could not form a valid execution-plan entry.",
                    well_id=well_id,
                    error=str(exc),
                )

    if any(issue.severity == "fatal" for issue in issues):
        return LegacyExecutionReconstruction(
            classification=classification,
            plan=None,
            progress=progress,
            issues=tuple(issues),
            source_evidence=tuple(evidence),
        )

    design_hash = canonical_sha256(design_payload)
    created, updated, locked, lock_reason = _timestamps(directory, audit_events, applied)
    state = _lifecycle_state(progress_targets, progress_added, audit_events)
    try:
        volume_basis = ExecutionVolumeBasis(
            target_printed_volume_nL=float(metadata.get("target_reaction_volume_nL")),
            final_reaction_volume_nL=float(
                metadata.get("final_reaction_volume_nL", metadata.get("target_reaction_volume_nL"))
            ),
            design_optimization_tolerance_nL=float(metadata.get("printed_volume_tolerance_nL", 0.0)),
        )
    except (ExecutionPlanValidationError, TypeError, ValueError) as exc:
        _issue(
            issues,
            "fatal",
            "volume_basis_invalid",
            "The saved design has no valid reaction-volume basis for reconstruction.",
            error=str(exc),
        )
        return LegacyExecutionReconstruction(
            classification=classification,
            plan=None,
            progress=progress,
            issues=tuple(issues),
            source_evidence=tuple(evidence),
        )
    identity = {
        "design_sha256": design_hash,
        "plate": {"name": plate.name, "rows": plate.rows, "columns": plate.columns},
        "stocks": [
            {
                "stock_id": stock.stock_id,
                "factor_name": stock.factor_name,
                "option_name": stock.option_name,
                "reagent_name": stock.reagent_name,
                "concentration": stock.concentration,
                "units": stock.units,
                "printing_mode": stock.printing_mode,
                "intended_volume_nL": stock.intended_volume_nL,
                "effective_volume_nL": stock.effective_volume_nL,
                "printer_head_id": stock.printer_head_id,
                "calibration_record_key": stock.calibration_record_key,
            }
            for stock in sorted(stocks, key=lambda item: item.stock_id)
        ],
        "wells": [
            {
                "well_id": well.well_id,
                "reaction_id": well.reaction_id,
                "targets": {
                    dispense.stock_id: dispense.target_dispenses for dispense in well.dispenses
                },
            }
            for well in sorted(wells, key=lambda item: item.well_id)
        ],
    }
    plan_id = str(uuid.uuid5(_LEGACY_PLAN_NAMESPACE, canonical_sha256(identity)))
    try:
        plan = ExecutionPlan(
            plan_id=plan_id,
            plan_revision=1,
            state=state,
            design_sha256=design_hash,
            created_at_utc=created,
            updated_at_utc=updated,
            locked_at_utc=locked,
            lock_reason=lock_reason,
            plate=plate,
            volume_basis=volume_basis,
            stocks=tuple(stocks),
            wells=tuple(wells),
        )
    except (ExecutionPlanValidationError, TypeError, ValueError) as exc:
        _issue(
            issues,
            "fatal",
            "execution_plan_invalid",
            "The recorded artifacts could not form a valid execution plan.",
            error=str(exc),
        )
        plan = None

    return LegacyExecutionReconstruction(
        classification=classification,
        plan=plan,
        progress=progress,
        issues=tuple(issues),
        source_evidence=tuple(evidence),
    )
