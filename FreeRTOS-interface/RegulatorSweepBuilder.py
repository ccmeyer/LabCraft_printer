from __future__ import annotations

import copy
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

from RegulatorCalibrationRunner import RegulatorCalibrationError, _trace_case_from_config
from RegulatorProfiles import (
    RECOVERY_BOUNDS,
    READY_BOUNDS,
    SLEW_BOUNDS,
    RegulatorProfileError,
    validate_document,
    validate_profile,
    write_json_atomic,
)


class RegulatorSweepError(ValueError):
    pass


SWEEP_STRATEGY_ONE_AT_A_TIME = "one_at_a_time"
SWEEP_STRATEGY_GRID = "grid"
SWEEP_STRATEGIES = frozenset({SWEEP_STRATEGY_ONE_AT_A_TIME, SWEEP_STRATEGY_GRID})
MAX_SWEEP_CANDIDATES = 12

_SWEEPABLE_BOUNDS = {
    "recovery": RECOVERY_BOUNDS,
    "slew": SLEW_BOUNDS,
    "ready": READY_BOUNDS,
}


@dataclass
class PreparedRegulatorSweep:
    mode: str
    baseline_profile_id: str
    mutated_channel: str
    strategy: str
    field_rows: list[dict[str, Any]]
    candidate_profile_ids: list[str]
    candidate_profiles: dict[str, dict[str, Any]]
    candidate_changes: list[dict[str, Any]]
    profile_document: dict[str, Any]
    manifest: dict[str, Any]


def sweepable_field_choices() -> list[dict[str, Any]]:
    choices = []
    for section in ("recovery", "slew", "ready"):
        for field, bounds in _SWEEPABLE_BOUNDS[section].items():
            choices.append(
                {
                    "field_path": f"{section}.{field}",
                    "label": f"{section}.{field}",
                    "section": section,
                    "field": field,
                    "min": int(bounds[0]),
                    "max": int(bounds[1]),
                }
            )
    return choices


def _string_or_empty(value: Any) -> str:
    return str(value or "").strip()


def _profile_document(profile_document: dict[str, Any] | None) -> dict[str, Any]:
    if profile_document is None:
        raise RegulatorSweepError("regulator profile document is not loaded")
    try:
        return validate_document(profile_document)
    except RegulatorProfileError as exc:
        raise RegulatorSweepError(str(exc)) from exc


def _strategy(config: dict[str, Any]) -> str:
    value = _string_or_empty(config.get("sweep_strategy") or config.get("strategy") or SWEEP_STRATEGY_ONE_AT_A_TIME)
    value = value.lower()
    if value not in SWEEP_STRATEGIES:
        raise RegulatorSweepError("sweep_strategy must be one_at_a_time or grid")
    return value


def _field_parts(field_path: Any) -> tuple[str, str]:
    text = _string_or_empty(field_path)
    parts = text.split(".")
    if len(parts) != 2:
        raise RegulatorSweepError(f"invalid sweep field path {text}")
    section, field = parts
    if section not in _SWEEPABLE_BOUNDS or field not in _SWEEPABLE_BOUNDS[section]:
        raise RegulatorSweepError(f"field {text} is not sweepable")
    return section, field


def _parse_values(raw_values: Any, field_path: str) -> list[int]:
    if isinstance(raw_values, str):
        items = [part.strip() for part in raw_values.replace(";", ",").split(",")]
    elif isinstance(raw_values, (list, tuple)):
        items = list(raw_values)
    else:
        raise RegulatorSweepError(f"values for {field_path} must be a list or comma-separated string")

    values: list[int] = []
    for item in items:
        if item == "":
            continue
        if isinstance(item, bool):
            raise RegulatorSweepError(f"values for {field_path} must be integers")
        try:
            value = int(item)
        except (TypeError, ValueError) as exc:
            raise RegulatorSweepError(f"values for {field_path} must be integers") from exc
        values.append(value)
    if not values:
        raise RegulatorSweepError(f"values for {field_path} cannot be empty")
    if len(values) != len(set(values)):
        raise RegulatorSweepError(f"values for {field_path} must not contain duplicates")
    return values


def _field_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_rows = config.get("sweep_fields") or config.get("field_rows") or []
    if not isinstance(raw_rows, (list, tuple)):
        raise RegulatorSweepError("sweep_fields must be a list")
    rows = []
    seen = set()
    for row in raw_rows:
        if not isinstance(row, dict):
            raise RegulatorSweepError("each sweep field row must be an object")
        field_path = _string_or_empty(row.get("field_path") or row.get("field"))
        section, field = _field_parts(field_path)
        if field_path in seen:
            raise RegulatorSweepError(f"duplicate sweep field {field_path}")
        seen.add(field_path)
        values = _parse_values(row.get("values"), field_path)
        min_value, max_value = _SWEEPABLE_BOUNDS[section][field]
        for value in values:
            if value < min_value or value > max_value:
                raise RegulatorSweepError(f"{field_path} value {value} is outside {min_value}..{max_value}")
        rows.append(
            {
                "field_path": field_path,
                "section": section,
                "field": field,
                "values": values,
                "min": int(min_value),
                "max": int(max_value),
            }
        )
    if not rows:
        raise RegulatorSweepError("at least one sweep field is required")
    return rows


def _candidate_prefix(config: dict[str, Any], baseline_profile_id: str) -> str:
    prefix = _string_or_empty(config.get("candidate_prefix") or f"{baseline_profile_id}_sweep")
    if not prefix:
        raise RegulatorSweepError("candidate_prefix cannot be empty")
    return prefix


def _candidate_specs(strategy: str, rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    specs: list[list[dict[str, Any]]] = []
    if strategy == SWEEP_STRATEGY_ONE_AT_A_TIME:
        for row in rows:
            for value in row["values"]:
                specs.append([dict(row, value=value)])
    else:
        for combo in product(*[row["values"] for row in rows]):
            specs.append([dict(row, value=value) for row, value in zip(rows, combo)])
    if not (1 <= len(specs) <= MAX_SWEEP_CANDIDATES):
        raise RegulatorSweepError(f"sweep must generate 1 to {MAX_SWEEP_CANDIDATES} candidates")
    return specs


def _trace_case(config: dict[str, Any]):
    try:
        return _trace_case_from_config(config)
    except RegulatorCalibrationError as exc:
        raise RegulatorSweepError(str(exc)) from exc


def _mutated_channel(config: dict[str, Any], trace_case) -> str:
    requested = _string_or_empty(config.get("mutated_channel") or config.get("channel")).lower()
    channels = tuple(trace_case.channels)
    if not requested and len(channels) == 1:
        requested = channels[0]
    if requested not in {"print", "refuel"}:
        raise RegulatorSweepError("mutated_channel must be print or refuel")
    if requested not in channels:
        raise RegulatorSweepError("mutated_channel must be included in the selected trace case")
    return requested


def _apply_spec(profile: dict[str, Any], channel: str, spec: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes = []
    for item in spec:
        section = item["section"]
        field = item["field"]
        field_path = item["field_path"]
        value = int(item["value"])
        baseline_value = profile[channel][section][field]
        if baseline_value == value:
            raise RegulatorSweepError(f"{field_path} value {value} matches the baseline")
        profile[channel][section][field] = value
        changes.append(
            {
                "channel": channel,
                "field_path": field_path,
                "baseline_value": baseline_value,
                "value": value,
            }
        )
    return changes


def _notes_for_changes(changes: list[dict[str, Any]]) -> str:
    return ", ".join(
        f"{change['channel']}.{change['field_path']}={change['value']}"
        for change in changes
    )


def prepare_regulator_sweep(
    config: dict[str, Any],
    *,
    profile_document: dict[str, Any] | None,
) -> PreparedRegulatorSweep:
    config = dict(config or {})
    if not bool(config.get("calibrated_head_confirmed")):
        raise RegulatorSweepError("Confirm that a calibrated printer head is installed before starting.")
    document = _profile_document(profile_document)
    mode = _string_or_empty(config.get("mode")).lower()
    if mode not in {"droplet", "stream"}:
        raise RegulatorSweepError("mode must be droplet or stream")

    baseline_profile_id = _string_or_empty(config.get("baseline_profile_id")) or _string_or_empty(
        document.get("active_profiles", {}).get(mode)
    )
    if not baseline_profile_id:
        raise RegulatorSweepError(f"active baseline profile for {mode} is required")
    profiles = document.get("profiles", {})
    if baseline_profile_id not in profiles:
        raise RegulatorSweepError(f"profile {baseline_profile_id} does not exist")
    baseline_profile = validate_profile(profiles[baseline_profile_id], profile_id=baseline_profile_id)
    if baseline_profile.get("mode") != mode:
        raise RegulatorSweepError(f"profile {baseline_profile_id} mode does not match {mode}")

    trace_case = _trace_case(config)
    channel = _mutated_channel(config, trace_case)
    strategy = _strategy(config)
    rows = _field_rows(config)
    specs = _candidate_specs(strategy, rows)
    prefix = _candidate_prefix(config, baseline_profile_id)

    generated_document = copy.deepcopy(document)
    generated_profiles: dict[str, dict[str, Any]] = {}
    candidate_changes: list[dict[str, Any]] = []
    candidate_ids: list[str] = []
    fingerprints = set()
    for index, spec in enumerate(specs, start=1):
        profile_id = f"{prefix}_{index:03d}"
        if profile_id in generated_document["profiles"]:
            raise RegulatorSweepError(f"generated profile ID {profile_id} already exists")
        candidate = copy.deepcopy(baseline_profile)
        candidate["profile_id"] = profile_id
        changes = _apply_spec(candidate, channel, spec)
        fingerprint = tuple((change["channel"], change["field_path"], change["value"]) for change in changes)
        if fingerprint in fingerprints:
            raise RegulatorSweepError("duplicate generated profiles are not allowed")
        fingerprints.add(fingerprint)
        candidate["description"] = f"Sweep candidate {index} from {baseline_profile_id}"
        candidate["source"] = {
            "kind": "calibration_candidate",
            "run_id": None,
            "promoted_at_utc": None,
            "operator": _string_or_empty(config.get("operator")) or None,
            "notes": _notes_for_changes(changes),
        }
        candidate = validate_profile(candidate, profile_id=profile_id)
        generated_document["profiles"][profile_id] = candidate
        generated_profiles[profile_id] = copy.deepcopy(candidate)
        candidate_ids.append(profile_id)
        candidate_changes.append({"profile_id": profile_id, "changes": changes})

    generated_document = validate_document(generated_document)
    manifest = {
        "schema_version": 1,
        "baseline_profile_id": baseline_profile_id,
        "mode": mode,
        "mutated_channel": channel,
        "strategy": strategy,
        "trace_case_id": trace_case.test_id,
        "field_rows": copy.deepcopy(rows),
        "generated_profile_count": len(candidate_ids),
        "generated_candidate_ids": list(candidate_ids),
        "candidates": copy.deepcopy(candidate_changes),
    }
    return PreparedRegulatorSweep(
        mode=mode,
        baseline_profile_id=baseline_profile_id,
        mutated_channel=channel,
        strategy=strategy,
        field_rows=copy.deepcopy(rows),
        candidate_profile_ids=list(candidate_ids),
        candidate_profiles=generated_profiles,
        candidate_changes=candidate_changes,
        profile_document=generated_document,
        manifest=manifest,
    )


def write_sweep_artifacts(prepared_sweep: PreparedRegulatorSweep, session_dir: str | Path) -> dict[str, Any]:
    session_dir = Path(session_dir)
    sweep_manifest_path = session_dir / "sweep_manifest.json"
    sweep_profiles_path = session_dir / "sweep_profiles.json"
    write_json_atomic(sweep_manifest_path, prepared_sweep.manifest)
    write_json_atomic(
        sweep_profiles_path,
        {
            "schema_version": 1,
            "baseline_profile_id": prepared_sweep.baseline_profile_id,
            "generated_candidate_ids": list(prepared_sweep.candidate_profile_ids),
            "profiles": copy.deepcopy(prepared_sweep.candidate_profiles),
            "profile_document": copy.deepcopy(prepared_sweep.profile_document),
        },
    )
    sweep_block = copy.deepcopy(prepared_sweep.manifest)
    sweep_block["sweep_manifest_json"] = sweep_manifest_path.name
    sweep_block["sweep_profiles_json"] = sweep_profiles_path.name
    return sweep_block
