"""Pure contracts and fixtures for calibration-storage SIL.

This module deliberately contains no Qt or application imports.  It defines
the reviewed fixture boundary used to characterize the current legacy writer
before a new authoritative calibration store is introduced.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


FIXTURE_SCHEMA_ID = "labcraft.calibration_storage_contract_fixture"
FIXTURE_SCHEMA_VERSION = 1
CATALOG_SCHEMA_ID = "labcraft.calibration_storage_contract_catalog"
CATALOG_SCHEMA_VERSION = 1
FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "virtual_workflows"
    / "fixtures"
    / "calibration_storage_contract"
)
CATALOG_PATH = FIXTURE_ROOT / "catalog_v1.json"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*_v[1-9][0-9]*$")
_ABSOLUTE_WINDOWS_RE = re.compile(r"^[A-Za-z]:[\\/]")
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
class CalibrationStorageContractError(ValueError):
    """Raised when a storage-contract fixture or projection is invalid."""


def _normalize_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CalibrationStorageContractError("non-finite JSON number")
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_json(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    scalar = getattr(value, "item", None)
    if callable(scalar):
        return _normalize_json(scalar())
    raise CalibrationStorageContractError(
        f"unsupported canonical JSON value: {type(value).__name__}"
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return the v1 finite, compact, sorted UTF-8 JSON representation."""

    return json.dumps(
        _normalize_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def semantic_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _walk_safe(value: Any, label: str = "fixture") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).lower()
            if any(part in key for part in _SENSITIVE_KEY_PARTS):
                raise CalibrationStorageContractError(
                    f"{label}.{raw_key} contains a sensitive key"
                )
            if "experiment_name" in key and not str(item).startswith("sil-"):
                raise CalibrationStorageContractError(
                    f"{label}.{raw_key} contains a residual experiment identity"
                )
            if "operator" in key and not str(item).startswith("sil-"):
                raise CalibrationStorageContractError(
                    f"{label}.{raw_key} contains a residual operator identity"
                )
            if (
                "source_path" in key or "absolute_path" in key
            ) and item != "sil-redacted-path":
                raise CalibrationStorageContractError(
                    f"{label}.{raw_key} contains a residual source path"
                )
            _walk_safe(item, f"{label}.{raw_key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk_safe(item, f"{label}[{index}]")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise CalibrationStorageContractError(f"{label} is non-finite")
    if isinstance(value, str):
        if _ABSOLUTE_WINDOWS_RE.match(value) or value.startswith("/"):
            raise CalibrationStorageContractError(f"{label} contains an absolute path")


def _large_trace(seed: int, sample_count: int) -> list[dict[str, Any]]:
    """Materialize a deterministic source-shaped online-stream trace."""

    if sample_count < 1 or sample_count > 20000:
        raise CalibrationStorageContractError("large trace sample_count is out of range")
    rows: list[dict[str, Any]] = []
    for index in range(sample_count):
        offset = ((index * 37 + seed * 17) % 1000) / 1000.0
        rows.append(
            {
                "sample_index": index,
                "delay_us": 200 + index * 5,
                "diameter_px": round(24.0 + offset * 3.0, 6),
                "centroid_px": [
                    round(320.0 + offset, 6),
                    round(240.0 - offset, 6),
                ],
                "foreground_fraction": round(0.15 + offset * 0.02, 8),
                "fit_residual": round((offset - 0.5) ** 2, 8),
            }
        )
    return rows


def materialize_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(dict(raw)))
    generator = payload.pop("_sil_generator", None)
    if generator is None:
        return payload
    if not isinstance(generator, Mapping) or generator.get("kind") != "online_stream_trace_v1":
        raise CalibrationStorageContractError("unsupported SIL payload generator")
    result = payload.setdefault("result", {})
    result["trace_samples"] = _large_trace(
        int(generator.get("seed", 1)),
        int(generator.get("sample_count", 0)),
    )
    minimum_bytes = int(generator.get("minimum_canonical_bytes", 0))
    if minimum_bytes and len(canonical_json_bytes(payload)) < minimum_bytes:
        raise CalibrationStorageContractError(
            "materialized online-stream payload is smaller than its oracle"
        )
    return payload


@dataclass(frozen=True)
class ScriptedCalibrationCase:
    fixture_id: str
    process_id: str
    phase_name: str
    result_kind: str
    terminal_outcome: str
    error_message: str
    record_mode_enabled: bool
    capture_mode: str
    updates: tuple[dict[str, Any], ...]
    captures: tuple[dict[str, Any], ...]
    expected_summary_rows: tuple[dict[str, Any], ...]
    identity: Mapping[str, Any]

    @property
    def expected_update_hashes(self) -> tuple[str, ...]:
        return tuple(
            semantic_sha256({"phase": self.phase_name, "data": payload})
            for payload in self.updates
        )


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationStorageContractError(f"could not load {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CalibrationStorageContractError(f"{path} must contain a JSON object")
    return payload


def validate_fixture(payload: Mapping[str, Any], *, path: Path | None = None) -> None:
    label = str(path or "fixture")
    if payload.get("schema_id") != FIXTURE_SCHEMA_ID:
        raise CalibrationStorageContractError(f"{label} has the wrong schema_id")
    if payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise CalibrationStorageContractError(f"{label} has the wrong schema_version")
    fixture_id = str(payload.get("fixture_id") or "")
    if not _ID_RE.fullmatch(fixture_id):
        raise CalibrationStorageContractError(f"{label} has an invalid fixture_id")
    if not isinstance(payload.get("source_shape"), str) or not payload["source_shape"]:
        raise CalibrationStorageContractError(f"{label} is missing source_shape")
    limitations = payload.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise CalibrationStorageContractError(f"{label} requires limitations")
    processes = payload.get("processes")
    if not isinstance(processes, list) or not processes:
        raise CalibrationStorageContractError(f"{label} requires processes")
    seen: set[str] = set()
    for index, process in enumerate(processes):
        if not isinstance(process, dict):
            raise CalibrationStorageContractError(f"{label}.processes[{index}] must be an object")
        process_id = str(process.get("process_id") or "")
        if not process_id or process_id in seen:
            raise CalibrationStorageContractError(f"{label} has duplicate/empty process_id")
        seen.add(process_id)
        if process.get("terminal_outcome") not in {"completed", "stopped", "error"}:
            raise CalibrationStorageContractError(f"{label}.{process_id} has invalid outcome")
        if process.get("result_kind") not in {"calibration", "dataset", "operational", "none"}:
            raise CalibrationStorageContractError(f"{label}.{process_id} has invalid result_kind")
        updates = process.get("updates", [])
        if not isinstance(updates, list):
            raise CalibrationStorageContractError(f"{label}.{process_id}.updates must be a list")
        materialized = [materialize_payload(item) for item in updates]
        expected = process.get("expected_update_hashes")
        observed = [
            semantic_sha256({"phase": process.get("phase_name"), "data": item})
            for item in materialized
        ]
        if expected != observed:
            raise CalibrationStorageContractError(
                f"{label}.{process_id} update hash oracle drifted"
            )
        summary_rows = process.get("expected_summary_rows")
        if not isinstance(summary_rows, list):
            raise CalibrationStorageContractError(
                f"{label}.{process_id}.expected_summary_rows must be a list"
            )
    _walk_safe(payload, label)


def load_fixture(path: str | Path) -> tuple[dict[str, Any], tuple[ScriptedCalibrationCase, ...]]:
    fixture_path = Path(path).resolve()
    payload = _load_json_object(fixture_path)
    validate_fixture(payload, path=fixture_path)
    cases: list[ScriptedCalibrationCase] = []
    for process in payload["processes"]:
        cases.append(
            ScriptedCalibrationCase(
                fixture_id=str(payload["fixture_id"]),
                process_id=str(process["process_id"]),
                phase_name=str(process["phase_name"]),
                result_kind=str(process["result_kind"]),
                terminal_outcome=str(process["terminal_outcome"]),
                error_message=str(process.get("error_message") or ""),
                record_mode_enabled=bool(process.get("record_mode_enabled", True)),
                capture_mode=str(process.get("capture_mode") or "structured_only_proxy"),
                updates=tuple(materialize_payload(item) for item in process.get("updates", [])),
                captures=tuple(dict(item) for item in process.get("captures", [])),
                expected_summary_rows=tuple(
                    dict(item) for item in process.get("expected_summary_rows", [])
                ),
                identity=dict(process.get("identity") or payload.get("identity") or {}),
            )
        )
    return payload, tuple(cases)


def load_catalog(path: str | Path = CATALOG_PATH) -> tuple[dict[str, Any], tuple[ScriptedCalibrationCase, ...]]:
    catalog_path = Path(path).resolve()
    catalog = _load_json_object(catalog_path)
    if catalog.get("schema_id") != CATALOG_SCHEMA_ID or catalog.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise CalibrationStorageContractError("unsupported storage-contract catalog")
    if catalog.get("fixture_id") != "calibration_storage_contract_v1":
        raise CalibrationStorageContractError("catalog fixture_id drifted")
    expected_count = int((catalog.get("workload") or {}).get("completion_count", 0))
    refs = catalog.get("fixtures")
    if not isinstance(refs, list) or len(refs) != 7:
        raise CalibrationStorageContractError("catalog must reference seven fixtures")
    cases: list[ScriptedCalibrationCase] = []
    hashes: dict[str, str] = {}
    for ref in refs:
        if not isinstance(ref, dict):
            raise CalibrationStorageContractError("catalog fixture reference must be an object")
        relative = Path(str(ref.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise CalibrationStorageContractError("catalog fixture path escaped its root")
        fixture_path = (catalog_path.parent / relative).resolve()
        if catalog_path.parent not in fixture_path.parents:
            raise CalibrationStorageContractError("catalog fixture path escaped its root")
        fixture, fixture_cases = load_fixture(fixture_path)
        fixture_id = str(fixture["fixture_id"])
        if fixture_id != ref.get("fixture_id"):
            raise CalibrationStorageContractError("catalog fixture identity drifted")
        digest = semantic_sha256(fixture)
        if digest != ref.get("semantic_sha256"):
            raise CalibrationStorageContractError(f"catalog hash drifted for {fixture_id}")
        hashes[fixture_id] = digest
        cases.extend(fixture_cases)
    if len(cases) != expected_count:
        raise CalibrationStorageContractError("catalog process count drifted")
    if catalog.get("catalog_semantic_sha256") != semantic_sha256(
        {"fixture_hashes": hashes, "workload": catalog.get("workload")}
    ):
        raise CalibrationStorageContractError("catalog semantic hash drifted")
    _walk_safe(catalog, "catalog")
    return catalog, tuple(cases)


def normalized_legacy_step(step: Mapping[str, Any]) -> dict[str, Any]:
    """Project one legacy step onto stable fixture semantics."""

    projected = dict(step)
    phase = str(projected.pop("phase", ""))
    projected.pop("timestamp", None)
    projected.pop("settings", None)
    projected.pop("meta", None)
    return {"phase": phase, "data": projected}


def normalized_recorder_update(record: Mapping[str, Any]) -> dict[str, Any]:
    if record.get("kind") != "calibration_data_updated":
        raise CalibrationStorageContractError("recorder record is not a data update")
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        raise CalibrationStorageContractError("recorder update payload is missing")
    return normalized_legacy_step(payload)


def percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = min(1.0, max(0.0, float(fraction))) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def distribution(values: Iterable[float]) -> dict[str, Any]:
    rows = [float(value) for value in values]
    if not rows:
        return {"count": 0, "minimum": None, "median": None, "p95": None, "maximum": None}
    return {
        "count": len(rows),
        "minimum": min(rows),
        "median": percentile(rows, 0.5),
        "p95": percentile(rows, 0.95),
        "maximum": max(rows),
    }


__all__ = [
    "CATALOG_PATH",
    "CATALOG_SCHEMA_ID",
    "CalibrationStorageContractError",
    "FIXTURE_SCHEMA_ID",
    "ScriptedCalibrationCase",
    "canonical_json_bytes",
    "distribution",
    "file_sha256",
    "load_catalog",
    "load_fixture",
    "materialize_payload",
    "normalized_legacy_step",
    "normalized_recorder_update",
    "semantic_sha256",
    "validate_fixture",
]
