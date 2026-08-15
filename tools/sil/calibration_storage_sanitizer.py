"""Developer CLI for creating reviewed calibration-storage SIL fixtures.

The input is always treated as read-only.  The command writes one new fixture
and refuses to replace any existing destination.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .calibration_storage_contract import (
    FIXTURE_SCHEMA_ID,
    FIXTURE_SCHEMA_VERSION,
    file_sha256,
    materialize_payload,
    semantic_sha256,
    validate_fixture,
)


_DROP_KEYS = {
    "notes",
    "operator",
    "operator_name",
    "image",
    "image_bytes",
    "raw_image",
    "absolute_path",
    "source_path",
}
_IDENTITY_REPLACEMENTS = {
    "printer_head_id": "sil-head-01",
    "serial": "sil-head-01",
    "stock_id": "sil-stock-01",
    "stock_solution": "SIL Reagent - 1.0 x",
    "reagent_name": "SIL Reagent",
    "experiment_id": "sil-experiment-v1",
    "experiment_name": "sil-experiment-v1",
    "run_id": "sil-source-run-v1",
    "timestamp": "2000-01-01T00:00:00Z",
    "started_at": "2000-01-01T00:00:00Z",
    "ended_at": "2000-01-01T00:00:01Z",
}
_PATH_RE = re.compile(r"(?:^[A-Za-z]:[\\/]|^/(?:home|Users|var|tmp)/)")


class SanitizerError(ValueError):
    """Raised when a source selection cannot become a safe fixture."""


def _identity_replacement(key: str) -> str | None:
    lowered = str(key).lower()
    if lowered in _IDENTITY_REPLACEMENTS:
        return _IDENTITY_REPLACEMENTS[lowered]
    if "operator" in lowered:
        return "sil-operator"
    if "experiment" in lowered and lowered.endswith(("id", "name")):
        return "sil-experiment-v1"
    if lowered in {"head_id", "head_serial", "printer_head_serial"} or lowered.endswith(
        "printer_head_id"
    ):
        return "sil-head-01"
    if lowered in {"stock_name", "stock_solution"} or lowered.endswith("stock_id"):
        return "sil-stock-01"
    if lowered in {"reagent", "reagent_name"} or lowered.endswith("reagent_id"):
        return "SIL Reagent"
    if lowered == "run_id" or lowered.endswith("_run_id"):
        return "sil-source-run-v1"
    if lowered in {"timestamp", "started_at", "ended_at", "recorded_at"} or lowered.endswith(
        ("_timestamp", "_at_utc")
    ):
        return "2000-01-01T00:00:00Z"
    if "path" in lowered:
        return "sil-redacted-path"
    return None


def _source_identity_values(value: Any) -> set[str]:
    identities: set[str] = set()
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            if _identity_replacement(str(child_key)) is not None and isinstance(
                child_value, str
            ) and len(child_value) >= 4:
                identities.add(child_value)
            identities.update(_source_identity_values(child_value))
    elif isinstance(value, list):
        for item in value:
            identities.update(_source_identity_values(item))
    return identities


def _sanitize(value: Any, *, key: str = "") -> Any:
    lowered = str(key).lower()
    if lowered in _DROP_KEYS:
        return None
    replacement = _identity_replacement(lowered)
    if replacement is not None:
        return replacement
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for child_key, child_value in value.items():
            if str(child_key).lower() in _DROP_KEYS:
                continue
            sanitized = _sanitize(child_value, key=str(child_key))
            if sanitized is not None:
                out[str(child_key)] = sanitized
        return out
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and (_PATH_RE.search(value) or value.startswith("/")):
        return "sil-redacted-path"
    return copy.deepcopy(value)


def _select_step(
    source: Mapping[str, Any], *, run_index: int, phase: str, step_index: int
) -> Mapping[str, Any]:
    runs = source.get("runs")
    if not isinstance(runs, list) or not 0 <= run_index < len(runs):
        raise SanitizerError("run index is outside the source document")
    steps = (runs[run_index].get("steps") or {}).get(phase)
    if not isinstance(steps, list) or not 0 <= step_index < len(steps):
        raise SanitizerError("phase/step selection is outside the source document")
    step = steps[step_index]
    if not isinstance(step, Mapping):
        raise SanitizerError("selected calibration step is not an object")
    return step


def build_sanitized_fixture(
    source_path: str | Path,
    *,
    fixture_id: str,
    run_index: int,
    phase: str,
    step_indexes: tuple[int, ...],
    process_id: str,
) -> dict[str, Any]:
    source_file = Path(source_path).resolve()
    before = file_sha256(source_file)
    try:
        try:
            source = json.loads(source_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SanitizerError(f"could not read source calibration data: {exc}") from exc
        if not isinstance(source, Mapping):
            raise SanitizerError("source calibration data must be an object")
        updates: list[dict[str, Any]] = []
        residual_candidates: set[str] = set()
        for index in step_indexes:
            selected = dict(
                _select_step(
                    source,
                    run_index=run_index,
                    phase=phase,
                    step_index=index,
                )
            )
            residual_candidates.update(_source_identity_values(selected))
            for envelope_key in ("timestamp", "settings", "meta", "phase"):
                selected.pop(envelope_key, None)
            updates.append(dict(_sanitize(selected)))
        process = {
            "process_id": str(process_id),
            "phase_name": str(phase),
            "result_kind": "calibration",
            "terminal_outcome": "completed",
            "error_message": "",
            "record_mode_enabled": True,
            "capture_mode": "structured_only_proxy",
            "updates": updates,
            "captures": [],
            "expected_summary_rows": [],
            "expected_update_hashes": [
                semantic_sha256({"phase": phase, "data": materialize_payload(item)})
                for item in updates
            ],
        }
        fixture = {
            "schema_id": FIXTURE_SCHEMA_ID,
            "schema_version": FIXTURE_SCHEMA_VERSION,
            "fixture_id": str(fixture_id),
            "source_shape": f"legacy calibration run/phase projection: {phase}",
            "source_semantic_sha256": semantic_sha256(
                {"phase": phase, "updates": updates}
            ),
            "identity": {
                "printer_head_id": "sil-head-01",
                "stock_id": "sil-stock-01",
                "reagent_name": "SIL Reagent",
                "concentration": "1.0",
                "units": "x",
            },
            "processes": [process],
            "limitations": [
                "payload shape only; no camera, image-analysis, physical-quality, firmware, or protocol claim",
                "source identities, paths, notes, timestamps, and raw pixels removed",
            ],
        }
        validate_fixture(fixture)
        encoded = json.dumps(fixture, sort_keys=True, allow_nan=False)
        residual = sorted(value for value in residual_candidates if value in encoded)
        if residual:
            raise SanitizerError("residual source identities remain in fixture")
        return fixture
    finally:
        after = file_sha256(source_file)
        if after != before:
            raise SanitizerError("source calibration file changed while sanitizing")


def write_new_fixture(destination: str | Path, fixture: Mapping[str, Any]) -> Path:
    target = Path(destination).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite fixture: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(fixture), handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--process-id", required=True)
    parser.add_argument("--run-index", type=int, required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--step-index", type=int, action="append", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    fixture = build_sanitized_fixture(
        args.source,
        fixture_id=args.fixture_id,
        run_index=args.run_index,
        phase=args.phase,
        step_indexes=tuple(args.step_index),
        process_id=args.process_id,
    )
    target = write_new_fixture(args.output, fixture)
    print(f"Fixture: {target}")
    print(f"Semantic SHA-256: {semantic_sha256(fixture)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SanitizerError", "build_sanitized_fixture", "main", "write_new_fixture"]
