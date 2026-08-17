"""Pure helpers for grouping characterization results and their rechecks."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


_CANONICAL_REFERENCE_FIELDS = (
    "result_id",
    "result_sha256",
    "process_run_id",
    "update_id",
    "update_index",
    "update_payload_sha256",
    "row_ordinal",
)
_REFERENCE_FIELDS = (
    "run_id",
    "phase_key",
    "step_index",
    "pressure_index",
    "phase",
    "timestamp",
    "pw_us",
    "pressure_psi",
    "delay_us",
    "mean_volume_nL",
    "cv_pct",
    *_CANONICAL_REFERENCE_FIELDS,
)


def _safe_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _phase_key(row: Mapping[str, Any]) -> str:
    phase = str(row.get("source_phase_key") or row.get("phase") or "").strip().lower()
    return {
        "sweep": "pressure_sweep_characterization",
        "recheck": "droplet_recheck",
        "search": "droplet_search",
        "stream": "online_stream_calibration",
    }.get(phase, phase)


def is_recheck_row(row: Mapping[str, Any]) -> bool:
    return bool(
        str(row.get("phase") or "").strip().lower() == "recheck"
        or _phase_key(row) == "droplet_recheck"
        or row.get("recheck") is True
        or isinstance(row.get("recheck_source"), Mapping)
    )


def build_characterization_source_reference(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build a bounded reference that remains useful to legacy readers."""

    source = dict(row or {})
    reference = {
        "run_id": source.get("source_run_id") or source.get("run_id"),
        "phase_key": _phase_key(source),
        "step_index": _safe_int(source.get("source_step_index")),
        "pressure_index": _safe_int(source.get("source_pressure_index")),
        "phase": source.get("phase"),
        "timestamp": source.get("timestamp"),
        "pw_us": source.get("pw_us"),
        "pressure_psi": source.get("pressure_psi"),
        "delay_us": source.get("delay_us"),
        "mean_volume_nL": source.get("mean_nL"),
        "cv_pct": source.get("cv_pct"),
    }
    for field in _CANONICAL_REFERENCE_FIELDS:
        value = source.get(field)
        if value is not None:
            reference[field] = value
    return normalize_characterization_source_reference(reference)


def normalize_characterization_source_reference(
    reference: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Drop diagnostic payloads and retain only bounded source-identity fields."""

    source = dict(reference or {})
    return {
        key: source[key]
        for key in _REFERENCE_FIELDS
        if key in source and source[key] is not None
    }


def characterization_row_identity_key(row: Mapping[str, Any]) -> str:
    """Return an exact stable identity for a projected characterization row."""

    row = dict(row or {})
    process_run_id = str(row.get("process_run_id") or "")
    update_id = str(row.get("update_id") or "")
    if process_run_id and update_id:
        ordinal = _safe_int(row.get("row_ordinal")) or 0
        return f"canonical:{process_run_id}:{update_id}:{ordinal}"

    synthetic_id = str(
        row.get("synthetic_result_fingerprint")
        or row.get("synthetic_candidate_id")
        or ""
    )
    if synthetic_id:
        return f"synthetic:{synthetic_id}"

    run_id = str(row.get("source_run_id") or row.get("run_id") or "")
    phase_key = _phase_key(row)
    step_index = _safe_int(row.get("source_step_index"))
    pressure_index = _safe_int(row.get("source_pressure_index"))
    if run_id and phase_key and step_index is not None:
        return (
            f"legacy:{run_id}:{phase_key}:{step_index}:"
            f"{pressure_index if pressure_index is not None else ''}"
        )

    return ":".join(
        (
            "fallback",
            run_id,
            phase_key,
            str(row.get("timestamp") or ""),
            str(row.get("pw_us") or ""),
            str(row.get("pressure_psi") or ""),
        )
    )


def _legacy_row_identity_key(row: Mapping[str, Any]) -> str:
    run_id = str(row.get("source_run_id") or row.get("run_id") or "")
    phase_key = _phase_key(row)
    step_index = _safe_int(row.get("source_step_index"))
    pressure_index = _safe_int(row.get("source_pressure_index"))
    if not (run_id and phase_key and step_index is not None):
        return ""
    return (
        f"legacy:{run_id}:{phase_key}:{step_index}:"
        f"{pressure_index if pressure_index is not None else ''}"
    )


def characterization_reference_identity_key(reference: Mapping[str, Any] | None) -> str:
    reference = dict(reference or {})
    process_run_id = str(reference.get("process_run_id") or "")
    update_id = str(reference.get("update_id") or "")
    if process_run_id and update_id:
        ordinal = _safe_int(reference.get("row_ordinal")) or 0
        return f"canonical:{process_run_id}:{update_id}:{ordinal}"

    run_id = str(reference.get("run_id") or reference.get("source_run_id") or "")
    phase_key = str(
        reference.get("phase_key") or reference.get("source_phase_key") or ""
    ).strip().lower()
    phase_key = {
        "sweep": "pressure_sweep_characterization",
        "recheck": "droplet_recheck",
        "search": "droplet_search",
        "stream": "online_stream_calibration",
    }.get(phase_key, phase_key)
    step_index = _safe_int(
        reference.get("step_index", reference.get("source_step_index"))
    )
    pressure_index = _safe_int(
        reference.get("pressure_index", reference.get("source_pressure_index"))
    )
    if run_id and phase_key and step_index is not None:
        return (
            f"legacy:{run_id}:{phase_key}:{step_index}:"
            f"{pressure_index if pressure_index is not None else ''}"
        )
    return ""


def _top_level_set_key(row: Mapping[str, Any], identity_key: str) -> str:
    process_run_id = str(row.get("process_run_id") or "")
    if process_run_id:
        return f"process:{process_run_id}"
    synthetic_id = str(
        row.get("synthetic_result_fingerprint")
        or row.get("synthetic_candidate_id")
        or ""
    )
    if synthetic_id:
        return f"synthetic:{synthetic_id}"
    run_id = str(row.get("source_run_id") or row.get("run_id") or "")
    if run_id:
        phase_key = _phase_key(row)
        step_index = _safe_int(row.get("source_step_index"))
        if phase_key and step_index is not None:
            return f"legacy:{run_id}:{phase_key}:{step_index}"
        return f"legacy:{run_id}"
    return f"row:{identity_key}"


def _chronology_key(row: Mapping[str, Any], ordinal: int) -> tuple[Any, ...]:
    return (
        str(row.get("timestamp") or ""),
        _safe_int(row.get("update_index")) or 0,
        _safe_int(row.get("row_ordinal")) or 0,
        ordinal,
    )


def _candidate_order_key(row: Mapping[str, Any], ordinal: int) -> tuple[Any, ...]:
    def numeric(value: Any) -> tuple[int, float]:
        try:
            return (0, float(value))
        except (TypeError, ValueError):
            return (1, 0.0)

    return (
        numeric(row.get("pw_us")),
        numeric(row.get("pressure_psi")),
        _chronology_key(row, ordinal),
    )


def enrich_characterization_result_sets(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach deterministic result-set and parent/recheck presentation metadata."""

    enriched = [dict(row or {}) for row in rows]
    identities: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(enriched):
        own_key = characterization_row_identity_key(row)
        row["row_identity_key"] = own_key
        identities[own_key].append(index)
        legacy_key = _legacy_row_identity_key(row)
        if legacy_key and legacy_key != own_key:
            identities[legacy_key].append(index)

    def resolve_reference(reference: Mapping[str, Any] | None, seen: set[int]) -> int | None:
        key = characterization_reference_identity_key(reference)
        matches = identities.get(key, []) if key else []
        if len(matches) != 1:
            return None
        index = matches[0]
        if index in seen:
            return None
        row = enriched[index]
        if not is_recheck_row(row):
            return index
        next_reference = row.get("recheck_root_source") or row.get("recheck_source")
        return resolve_reference(next_reference, seen | {index})

    root_indices: list[int] = []
    unlinked_indices: list[int] = []
    for index, row in enumerate(enriched):
        if is_recheck_row(row):
            continue
        row["row_role"] = "candidate"
        row["candidate_key"] = row["row_identity_key"]
        row["parent_candidate_key"] = None
        row["result_set_key"] = _top_level_set_key(
            row, row["row_identity_key"]
        )
        root_indices.append(index)

    for index, row in enumerate(enriched):
        if not is_recheck_row(row):
            continue
        root_index = resolve_reference(row.get("recheck_root_source"), {index})
        if root_index is None:
            root_index = resolve_reference(row.get("recheck_source"), {index})
        if root_index is None:
            row["row_role"] = "unlinked_recheck"
            row["candidate_key"] = row["row_identity_key"]
            row["parent_candidate_key"] = None
            row["result_set_key"] = "unlinked"
            unlinked_indices.append(index)
            continue

        root = enriched[root_index]
        row["row_role"] = "recheck"
        row["candidate_key"] = root["row_identity_key"]
        row["parent_candidate_key"] = root["row_identity_key"]
        row["result_set_key"] = root["result_set_key"]

    set_first_rows: dict[str, tuple[tuple[Any, ...], int]] = {}
    for index in root_indices:
        row = enriched[index]
        key = str(row["result_set_key"])
        chronology = _chronology_key(row, index)
        current = set_first_rows.get(key)
        if current is None or chronology < current[0]:
            set_first_rows[key] = (chronology, index)
    ordered_sets = sorted(set_first_rows, key=lambda key: (set_first_rows[key][0], key))
    set_numbers = {key: ordinal + 1 for ordinal, key in enumerate(ordered_sets)}
    latest_key = ordered_sets[-1] if ordered_sets else None

    children: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(enriched):
        if row.get("row_role") == "recheck":
            children[str(row.get("candidate_key") or "")].append(index)
    for candidate_key, indices in children.items():
        indices.sort(key=lambda index: _chronology_key(enriched[index], index))
        for ordinal, index in enumerate(indices, 1):
            enriched[index]["recheck_no"] = ordinal

    for row in enriched:
        set_key = str(row.get("result_set_key") or "")
        set_no = set_numbers.get(set_key)
        row["result_set_no"] = set_no
        row["is_latest_result_set"] = bool(set_key and set_key == latest_key)
        row["run_no"] = set_no
        row["is_focus_run"] = bool(row["is_latest_result_set"])
        if row.get("row_role") == "unlinked_recheck":
            row["result_set_label"] = "Unlinked rechecks"
        elif set_no is not None:
            row["result_set_label"] = f"Set {set_no}"

    root_by_key = {
        str(enriched[index]["row_identity_key"]): enriched[index]
        for index in root_indices
    }
    for row in enriched:
        root = root_by_key.get(str(row.get("candidate_key") or ""), row)
        row["candidate_sort_anchor"] = {
            "applied_marker": root.get("applied_marker"),
            "result_set_no": root.get("result_set_no"),
            "phase_label": root.get("phase_label"),
            "timestamp_display": root.get("timestamp_display"),
            "timestamp": root.get("timestamp"),
            "pw_us": root.get("pw_us"),
            "pressure_psi": root.get("pressure_psi"),
            "mean_nL": root.get("mean_nL"),
            "cv_pct": root.get("cv_pct"),
            "valid": root.get("valid"),
        }

    ordered: list[dict[str, Any]] = []
    for set_key in ordered_sets:
        candidates = [
            index
            for index in root_indices
            if str(enriched[index].get("result_set_key") or "") == set_key
        ]
        candidates.sort(key=lambda index: _candidate_order_key(enriched[index], index))
        for index in candidates:
            root = enriched[index]
            ordered.append(root)
            ordered.extend(
                enriched[child_index]
                for child_index in children.get(str(root["row_identity_key"]), [])
            )

    unlinked_indices.sort(key=lambda index: _chronology_key(enriched[index], index))
    ordered.extend(enriched[index] for index in unlinked_indices)
    return ordered


def characterization_result_set_options(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return newest-first selector options for already-enriched rows."""

    options: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("result_set_key") or "")
        if not key or key in options:
            continue
        options[key] = {
            "result_set_key": key,
            "result_set_no": row.get("result_set_no"),
            "result_set_label": row.get("result_set_label") or "Unlinked rechecks",
            "timestamp": row.get("timestamp"),
            "timestamp_display": row.get("timestamp_display"),
            "phase_label": row.get("phase_label"),
            "is_latest_result_set": bool(row.get("is_latest_result_set")),
        }
    return sorted(
        options.values(),
        key=lambda item: (
            item.get("result_set_no") is not None,
            item.get("result_set_no") or -1,
            str(item.get("timestamp") or ""),
        ),
        reverse=True,
    )


def characterization_candidate_rollup(
    rows: Iterable[Mapping[str, Any]], candidate_key: str | None
) -> dict[str, Any]:
    group = [
        dict(row or {})
        for row in rows
        if str((row or {}).get("candidate_key") or "") == str(candidate_key or "")
    ]
    if not group:
        return {}
    parent = next((row for row in group if row.get("row_role") == "candidate"), None)
    rechecks = [row for row in group if row.get("row_role") == "recheck"]
    usable = []
    excluded = 0
    for row in ([parent] if parent else []) + rechecks:
        if not row or row.get("valid") is not True:
            excluded += 1
            continue
        try:
            usable.append(float(row.get("mean_nL")))
        except (TypeError, ValueError):
            excluded += 1
    result = {
        "candidate_volume_nL": parent.get("mean_nL") if parent else None,
        "recheck_volumes_nL": [row.get("mean_nL") for row in rechecks],
        "round_count": len(group),
        "recheck_count": len(rechecks),
        "usable_round_count": len(usable),
        "excluded_round_count": excluded,
        "mean_volume_nL": None,
        "range_nL": None,
        "maximum_absolute_delta_nL": None,
        "maximum_absolute_delta_percent": None,
    }
    if usable:
        result["mean_volume_nL"] = sum(usable) / len(usable)
        result["range_nL"] = max(usable) - min(usable)
    try:
        reference = float(parent.get("mean_nL")) if parent else None
    except (TypeError, ValueError):
        reference = None
    deltas = []
    for row in rechecks:
        try:
            deltas.append(abs(float(row.get("mean_nL")) - float(reference)))
        except (TypeError, ValueError):
            continue
    if deltas:
        maximum = max(deltas)
        result["maximum_absolute_delta_nL"] = maximum
        if reference is not None and abs(reference) > 1e-9:
            result["maximum_absolute_delta_percent"] = maximum / abs(reference) * 100.0
    return result


__all__ = [
    "build_characterization_source_reference",
    "characterization_candidate_rollup",
    "characterization_reference_identity_key",
    "characterization_result_set_options",
    "characterization_row_identity_key",
    "enrich_characterization_result_sets",
    "is_recheck_row",
    "normalize_characterization_source_reference",
]
