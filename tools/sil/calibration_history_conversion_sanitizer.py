"""Create a reviewed historical-conversion fixture without changing sources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from tools.sil.calibration_storage_contract import file_sha256
from tools.sil.calibration_storage_sanitizer import _sanitize, write_new_fixture
from tools.sil.calibration_history_conversion_fixture import (
    SCHEMA_ID,
    SCHEMA_VERSION,
    validate_fixture,
)


class HistoricalConversionSanitizerError(ValueError):
    pass


def _selection(text: str) -> tuple[int, str, int]:
    parts = str(text).split(":")
    if len(parts) != 3:
        raise HistoricalConversionSanitizerError(
            "selectors must use RUN_INDEX:PHASE:STEP_INDEX"
        )
    try:
        return int(parts[0]), parts[1], int(parts[2])
    except ValueError as exc:
        raise HistoricalConversionSanitizerError("selector indexes must be integers") from exc


def build_fixture(
    source_path: str | Path,
    *,
    fixture_id: str,
    selectors: tuple[str, ...],
    recording_run_paths: tuple[str | Path, ...] = (),
) -> dict[str, Any]:
    source = Path(source_path).resolve()
    source_before = file_sha256(source)
    recording_paths = tuple(Path(path).resolve() for path in recording_run_paths)
    recording_before = {
        path.as_posix(): {
            child.name: file_sha256(child)
            for child in (path / "run_meta.json", path / "analysis.jsonl")
            if child.is_file()
        }
        for path in recording_paths
    }
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
        runs = list(document.get("runs") or ())
        cases = []
        for ordinal, selector_text in enumerate(selectors, 1):
            run_index, phase, step_index = _selection(selector_text)
            try:
                run = dict(runs[run_index])
                step = dict((run.get("steps") or {})[phase][step_index])
            except (IndexError, KeyError, TypeError, ValueError) as exc:
                raise HistoricalConversionSanitizerError(
                    f"selection does not resolve: {selector_text}"
                ) from exc
            payload_hash = json.dumps(step, sort_keys=True, default=str)
            evidence_matches = 0
            for run_path in recording_paths:
                analysis_path = run_path / "analysis.jsonl"
                if not analysis_path.is_file():
                    continue
                for raw in analysis_path.read_text(encoding="utf-8").splitlines():
                    if not raw.strip():
                        continue
                    row = json.loads(raw)
                    if row.get("kind") == "calibration_data_updated" and json.dumps(
                        row.get("payload"), sort_keys=True, default=str
                    ) == payload_hash:
                        evidence_matches += 1
            cases.append(
                {
                    "case_id": f"sanitized-{ordinal:02d}",
                    "phase": phase,
                    "outcome": str(run.get("outcome") or "completed"),
                    "evidence": (
                        "ambiguous" if evidence_matches > 1
                        else "unique" if evidence_matches == 1
                        else "none"
                    ),
                    "result": _sanitize(dict(step.get("result") or {}), key="result"),
                }
            )
        fixture = {
            "schema_id": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "fixture_id": str(fixture_id),
            "identity": {
                "printer_head_id": "sil-migration-head-1",
                "stock_id": "sil-migration-stock-1",
                "reagent_name": "SIL Migration Reagent",
                "stock_solution": "SIL Migration Reagent - 1.0 x",
                "concentration": "1.0",
                "units": "x",
            },
            "cases": cases,
            "expected_counts": {
                "source_step_count": len(cases),
                "convert_count": sum(case["evidence"] != "ambiguous" for case in cases),
                "already_canonical_count": 0,
                "already_generated_count": 0,
                "skipped_count": sum(case["evidence"] == "ambiguous" for case in cases),
                "conflict_count": 0,
                "generated_count": sum(case["evidence"] != "ambiguous" for case in cases),
            },
            "source_shape": "reviewed historical calibration selections",
            "source_sha256": source_before,
            "limitations": [
                "source identities, paths, notes, timestamps, and pixels are excluded",
                "storage shape only; no physical calibration-quality claim",
            ],
        }
        validate_fixture(fixture)
        encoded = json.dumps(fixture, sort_keys=True, allow_nan=False)
        for forbidden in (str(source.parent), "operator", "password", "api_token"):
            if forbidden and forbidden in encoded:
                raise HistoricalConversionSanitizerError(
                    "fixture contains a residual source identity or sensitive field"
                )
        return fixture
    finally:
        if file_sha256(source) != source_before:
            raise HistoricalConversionSanitizerError("calibration source changed")
        for path in recording_paths:
            observed = {
                child.name: file_sha256(child)
                for child in (path / "run_meta.json", path / "analysis.jsonl")
                if child.is_file()
            }
            if observed != recording_before[path.as_posix()]:
                raise HistoricalConversionSanitizerError("recording source changed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--select", action="append", required=True)
    parser.add_argument("--recording-run", type=Path, action="append", default=[])
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    fixture = build_fixture(
        args.source,
        fixture_id=args.fixture_id,
        selectors=tuple(args.select),
        recording_run_paths=tuple(args.recording_run),
    )
    target = write_new_fixture(args.output, fixture)
    print(f"Fixture: {target}")
    print(f"Source SHA-256: {fixture['source_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["HistoricalConversionSanitizerError", "build_fixture", "main"]
