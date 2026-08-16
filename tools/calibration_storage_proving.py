#!/usr/bin/env python3
"""Read-only operational evidence collector for calibration writer retirement.

The collector never repairs, converts, or rewrites an experiment.  It hashes every
source file it opens before and after validation and writes only to an explicit new
report path supplied by the operator.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
INTERFACE_ROOT = REPO_ROOT / "FreeRTOS-interface"
if str(INTERFACE_ROOT) not in sys.path:
    sys.path.insert(0, str(INTERFACE_ROOT))

from CalibrationRecordingStore import (  # noqa: E402
    CalibrationRecordingStore,
    CalibrationStoreError,
)


CAMPAIGN_SCHEMA = "labcraft.calibration_storage.proving_campaign"
SNAPSHOT_SCHEMA = "labcraft.calibration_storage.proving_snapshot"
ASSESSMENT_SCHEMA = "labcraft.calibration_storage.proving_assessment"
ISSUE_LEDGER_SCHEMA = "labcraft.calibration_storage.proving_issue_ledger"
SCHEMA_VERSION = 1
MINIMUM_PROVING_DAYS = 14
MINIMUM_COMPLETED_CALIBRATIONS = 20
MINIMUM_HEADS = 3
MINIMUM_PI_REPORT_SETS = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(str(value or "unknown").encode("utf-8")).hexdigest()


def _progress(kind: str, **fields: Any) -> None:
    print(
        "CALIBRATION_STORAGE_PROVING_PROGRESS "
        + json.dumps({"kind": kind, **fields}, sort_keys=True),
        flush=True,
    )


def _load(path: str | Path, schema: str) -> dict[str, Any]:
    source = Path(path).resolve()
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_name") != schema:
        raise ValueError(f"{source} is not a {schema} document")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{source} has an unsupported schema version")
    return value


def _write_new(path: str | Path, value: dict[str, Any]) -> Path:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return destination


def create_campaign(
    *, campaign_id: str, source_commit: str, output: str | Path,
    started_at_utc: str | None = None,
) -> dict[str, Any]:
    document = {
        "schema_name": CAMPAIGN_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "campaign_id": str(campaign_id).strip(),
        "source_commit": str(source_commit).strip(),
        "started_at_utc": started_at_utc or _utc_now(),
        "requirements": {
            "minimum_days": MINIMUM_PROVING_DAYS,
            "minimum_completed_calibrations": MINIMUM_COMPLETED_CALIBRATIONS,
            "minimum_distinct_heads": MINIMUM_HEADS,
            "minimum_pi_report_sets": MINIMUM_PI_REPORT_SETS,
        },
    }
    if not document["campaign_id"] or not document["source_commit"]:
        raise ValueError("campaign-id and source-commit are required")
    _parse_utc(document["started_at_utc"])
    _write_new(output, document)
    _progress("campaign_created", campaign_id=document["campaign_id"])
    return document


def _contained_result(experiment: Path, relpath: Any) -> Path:
    result = (experiment / str(relpath or "")).resolve()
    if experiment != result and experiment not in result.parents:
        raise ValueError("index result path escapes the experiment directory")
    if result.name != "result.json":
        raise ValueError("index result path is not a result.json file")
    return result


def _manifest(paths: Iterable[Path], root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(set(paths), key=lambda item: item.as_posix())
        if path.is_file()
    }


def collect_snapshot(
    *, campaign_path: str | Path, experiment_dirs: Iterable[str | Path],
    output: str | Path, observed_at_utc: str | None = None,
) -> dict[str, Any]:
    campaign = _load(campaign_path, CAMPAIGN_SCHEMA)
    directories = [Path(item).resolve() for item in experiment_dirs]
    if not directories:
        raise ValueError("at least one explicit experiment directory is required")
    observations: list[dict[str, Any]] = []
    all_results: list[dict[str, Any]] = []
    for ordinal, experiment in enumerate(directories, 1):
        if not experiment.is_dir():
            raise ValueError(f"experiment directory does not exist: {experiment}")
        label = f"experiment-{ordinal:03d}"
        _progress("experiment_started", experiment=label, ordinal=ordinal, total=len(directories))
        index_path = experiment / "calibration_index.jsonl"
        source_paths = [index_path]
        legacy_path = experiment / "calibration.json"
        if legacy_path.is_file():
            source_paths.append(legacy_path)
        issues: list[dict[str, str]] = []
        results: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        if not index_path.is_file():
            issues.append({"code": "missing_index", "message": "calibration_index.jsonl is missing"})
        try:
            events, ignored_tail = CalibrationRecordingStore.read_jsonl(
                index_path, allow_incomplete_trailing_line=True
            )
            if ignored_tail:
                issues.append({"code": "incomplete_index_tail", "message": "index has an incomplete trailing row"})
            for event_ordinal, event in enumerate(events, 1):
                try:
                    result_path = _contained_result(experiment, event.get("result_relpath"))
                    run_dir = result_path.parent
                    source_paths.extend(
                        [result_path, run_dir / "updates.jsonl", run_dir / "run_meta.json"]
                    )
                except ValueError as exc:
                    issues.append({"code": "invalid_terminal_bundle", "message": f"index row {event_ordinal}: {exc}"})
        except (OSError, ValueError, CalibrationStoreError) as exc:
            issues.append({"code": "invalid_or_missing_index", "message": str(exc)})
        before = _manifest(source_paths, experiment)
        for event_ordinal, event in enumerate(events, 1):
            try:
                result_path = _contained_result(experiment, event.get("result_relpath"))
                run_dir = result_path.parent
                validated = CalibrationRecordingStore.validate_run(run_dir)
                result = dict(validated["result"])
                if (
                    result.get("result_id") != event.get("result_id")
                    or result.get("result_sha256") != event.get("result_sha256")
                ):
                    raise ValueError("index identity/hash does not match result")
                identity = dict(result.get("identity") or {})
                row = {
                    "result_id": str(result.get("result_id") or ""),
                    "result_sha256": str(result.get("result_sha256") or ""),
                    "outcome": str(result.get("outcome") or ""),
                    "result_kind": str(result.get("result_kind") or ""),
                    "update_count": int(result.get("update_count") or 0),
                    "head_fingerprint": _fingerprint(identity.get("printer_head_id")),
                }
                results.append(row)
                all_results.append(row)
            except (OSError, ValueError, CalibrationStoreError) as exc:
                issue = {"code": "invalid_terminal_bundle", "message": f"index row {event_ordinal}: {exc}"}
                if issue not in issues:
                    issues.append(issue)
        after = _manifest(source_paths, experiment)
        observations.append(
            {
                "experiment": label,
                "source_manifest_before": before,
                "source_manifest_after": after,
                "source_unchanged": before == after,
                "legacy_document_present": legacy_path.is_file(),
                "results": results,
                "issues": issues,
            }
        )
        _progress("experiment_complete", experiment=label, results=len(results), issues=len(issues))
    observed = observed_at_utc or _utc_now()
    _parse_utc(observed)
    document = {
        "schema_name": SNAPSHOT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "campaign_id": campaign["campaign_id"],
        "source_commit": campaign["source_commit"],
        "observed_at_utc": observed,
        "experiment_count": len(observations),
        "result_count": len(all_results),
        "completed_calibration_count": sum(
            row["outcome"] == "completed" and row["result_kind"] == "calibration"
            for row in all_results
        ),
        "storage_error_count": sum(row["outcome"] == "storage_error" for row in all_results),
        "head_fingerprints": sorted({row["head_fingerprint"] for row in all_results}),
        "observations": observations,
    }
    _write_new(output, document)
    _progress("snapshot_written", results=len(all_results), output=Path(output).name)
    return document


def _pi_report_set_passes(path: str | Path) -> tuple[bool, str]:
    source = Path(path).resolve()
    value = json.loads(source.read_text(encoding="utf-8"))
    functional = str((value.get("functional") or {}).get("status") or "")
    measured = int((value.get("runs") or {}).get("measured_count") or 0)
    if functional != "pass" or measured < 1:
        return False, f"{source.name}: functional={functional or 'missing'}, measured={measured}"
    return True, source.name


def evaluate_campaign(
    *, campaign_path: str | Path, snapshot_paths: Iterable[str | Path],
    issue_ledger_path: str | Path, pi_report_sets: Iterable[str | Path],
    output: str | Path,
) -> dict[str, Any]:
    campaign = _load(campaign_path, CAMPAIGN_SCHEMA)
    snapshots = [_load(path, SNAPSHOT_SCHEMA) for path in snapshot_paths]
    if not snapshots:
        raise ValueError("at least one snapshot is required")
    ledger = _load(issue_ledger_path, ISSUE_LEDGER_SCHEMA)
    if ledger.get("campaign_id") != campaign["campaign_id"]:
        raise ValueError("issue ledger campaign identity does not match")
    pi_checks = [_pi_report_set_passes(path) for path in pi_report_sets]
    latest = max(_parse_utc(row["observed_at_utc"]) for row in snapshots)
    duration_days = (latest - _parse_utc(campaign["started_at_utc"])).total_seconds() / 86400
    unique_results: dict[str, dict[str, Any]] = {}
    source_unchanged = True
    integrity_issue_count = 0
    for snapshot in snapshots:
        if snapshot.get("campaign_id") != campaign["campaign_id"]:
            raise ValueError("snapshot campaign identity does not match")
        for observation in snapshot.get("observations") or []:
            source_unchanged &= bool(observation.get("source_unchanged"))
            integrity_issue_count += len(observation.get("issues") or [])
            for row in observation.get("results") or []:
                result_id = str(row.get("result_id") or "")
                prior = unique_results.get(result_id)
                if prior is not None and prior.get("result_sha256") != row.get("result_sha256"):
                    integrity_issue_count += 1
                unique_results[result_id] = dict(row)
    completed = [
        row for row in unique_results.values()
        if row.get("outcome") == "completed" and row.get("result_kind") == "calibration"
    ]
    heads = sorted({str(row.get("head_fingerprint")) for row in completed})
    open_issues = [row for row in ledger.get("issues") or [] if row.get("status") != "resolved"]
    storage_errors = sum(row.get("outcome") == "storage_error" for row in unique_results.values())
    checks = {
        "duration": duration_days >= MINIMUM_PROVING_DAYS,
        "completed_calibrations": len(completed) >= MINIMUM_COMPLETED_CALIBRATIONS,
        "distinct_heads": len(heads) >= MINIMUM_HEADS,
        "source_immutability": source_unchanged,
        "integrity": integrity_issue_count == 0 and storage_errors == 0,
        "issue_ledger": len(open_issues) == 0,
        "pi_qualifications": len(pi_checks) >= MINIMUM_PI_REPORT_SETS and all(ok for ok, _ in pi_checks),
    }
    document = {
        "schema_name": ASSESSMENT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "campaign_id": campaign["campaign_id"],
        "status": "pass" if all(checks.values()) else "incomplete",
        "checks": checks,
        "metrics": {
            "duration_days": round(duration_days, 6),
            "completed_calibration_count": len(completed),
            "distinct_head_count": len(heads),
            "integrity_issue_count": integrity_issue_count,
            "storage_error_count": storage_errors,
            "open_issue_count": len(open_issues),
            "pi_report_set_count": len(pi_checks),
        },
        "heads": [f"head-{index:03d}" for index, _ in enumerate(heads, 1)],
        "pi_report_sets": [{"status": "pass" if ok else "fail", "label": label} for ok, label in pi_checks],
        "limitations": [
            "This evidence validates calibration storage integrity, not image-analysis correctness.",
            "Release tagging and offline release bundles are outside this workflow.",
        ],
    }
    _write_new(output, document)
    _progress("assessment_written", status=document["status"], **document["metrics"])
    return document


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create a new proving campaign")
    init.add_argument("--campaign-id", required=True)
    init.add_argument("--source-commit", required=True)
    init.add_argument("--started-at-utc")
    init.add_argument("--output", required=True)
    collect = sub.add_parser("collect", help="collect a read-only experiment snapshot")
    collect.add_argument("--campaign", required=True)
    collect.add_argument("--experiment-dir", action="append", required=True)
    collect.add_argument("--observed-at-utc")
    collect.add_argument("--output", required=True)
    evaluate = sub.add_parser("evaluate", help="evaluate proving-period gates")
    evaluate.add_argument("--campaign", required=True)
    evaluate.add_argument("--snapshot", action="append", required=True)
    evaluate.add_argument("--issue-ledger", required=True)
    evaluate.add_argument("--pi-report-set", action="append", required=True)
    evaluate.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "init":
        create_campaign(
            campaign_id=args.campaign_id, source_commit=args.source_commit,
            started_at_utc=args.started_at_utc, output=args.output,
        )
    elif args.command == "collect":
        collect_snapshot(
            campaign_path=args.campaign, experiment_dirs=args.experiment_dir,
            observed_at_utc=args.observed_at_utc, output=args.output,
        )
    else:
        result = evaluate_campaign(
            campaign_path=args.campaign, snapshot_paths=args.snapshot,
            issue_ledger_path=args.issue_ledger, pi_report_sets=args.pi_report_set,
            output=args.output,
        )
        return 0 if result["status"] == "pass" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
