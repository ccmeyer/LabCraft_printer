"""Canonical-first calibration update loading for offline developer tools."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


class CalibrationUpdateConflictError(ValueError):
    """Canonical and legacy projections disagree for the same recording."""


@dataclass(frozen=True)
class CalibrationUpdateLoad:
    rows: tuple[dict[str, Any], ...]
    source: str
    reader_state: str
    issues: tuple[str, ...] = ()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            text = raw.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row is not an object at {path}:{line_number}")
            rows.append(row)
    return rows


def _semantic_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _legacy_updates(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if str(row.get("kind") or "") == "calibration_data_updated"
        and isinstance(row.get("payload"), Mapping)
    ]


def load_calibration_updates(
    run_dir: str | Path,
    *,
    allow_legacy_fallback: bool = True,
) -> CalibrationUpdateLoad:
    """Load update envelopes, preferring canonical rows and checking parity.

    Canonical rows retain their stable identities. Legacy diagnostic rows are
    returned unchanged so existing callers can continue reading ``payload``.
    """

    directory = Path(run_dir).resolve()
    canonical = _jsonl(directory / "updates.jsonl")
    legacy = _legacy_updates(_jsonl(directory / "analysis.jsonl"))

    if canonical:
        for index, row in enumerate(canonical, 1):
            payload = row.get("payload")
            if not isinstance(payload, Mapping):
                raise ValueError(f"canonical update {index} has no object payload")
            if int(row.get("update_index") or 0) != index:
                raise ValueError("canonical update indexes are not gap-free")
            if str(row.get("payload_sha256") or "") != _semantic_hash(payload):
                raise ValueError(f"canonical update {index} payload hash mismatch")
        if legacy:
            canonical_hashes = [str(row["payload_sha256"]) for row in canonical]
            legacy_hashes = [_semantic_hash(dict(row["payload"])) for row in legacy]
            if canonical_hashes != legacy_hashes:
                raise CalibrationUpdateConflictError(
                    "canonical updates and legacy analysis projection conflict"
                )
            state = "matching_dual"
        else:
            state = "canonical_only"
        return CalibrationUpdateLoad(tuple(dict(row) for row in canonical), "canonical", state)

    if legacy and allow_legacy_fallback:
        return CalibrationUpdateLoad(tuple(legacy), "legacy", "legacy_only")
    return CalibrationUpdateLoad((), "none", "unavailable", ("no_calibration_updates",))


def update_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    return dict(payload) if isinstance(payload, Mapping) else {}


__all__ = [
    "CalibrationUpdateConflictError",
    "CalibrationUpdateLoad",
    "load_calibration_updates",
    "update_payload",
]
