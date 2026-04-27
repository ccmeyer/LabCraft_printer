#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUMMARY_COLUMNS = [
    "run_id",
    "process_name",
    "phase_name",
    "started_at_utc",
    "ended_at_utc",
    "meta_outcome",
    "verdict",
    "review_status",
    "review_reasons",
    "error_messages",
    "event_error_count",
    "event_warning_count",
    "analysis_problem_count",
    "tool_error_count",
    "run_dir",
]

EXPECTED_JSONL_FILES = {"events.jsonl", "analysis.jsonl"}
PROBLEM_STATUS_VALUES = {
    "abort",
    "aborted",
    "cancelled",
    "canceled",
    "error",
    "fail",
    "failed",
    "failure",
    "invalid",
    "not_usable",
    "rejected",
    "timeout",
    "timed_out",
    "unusable",
}
PROBLEM_BOOL_SUFFIXES = (
    "_usable",
    "_valid",
    "_ok",
    "_pass",
)


@dataclass
class ToolIssue:
    kind: str
    message: str


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _add_unique(items: list[str], value: Any, *, limit: int = 30) -> None:
    text = _clean_text(value)
    if not text or text in items:
        return
    if len(items) < limit:
        items.append(text)


def _load_json_object(path: Path, *, required: bool = True) -> tuple[dict[str, Any], list[ToolIssue]]:
    if not path.exists():
        if required:
            return {}, [ToolIssue("missing", f"missing {path.name}")]
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, [ToolIssue("parse", f"malformed {path.name}: {exc}")]
    if not isinstance(data, dict):
        return {}, [ToolIssue("parse", f"malformed {path.name}: expected object")]
    return data, []


def _load_jsonl_rows(path: Path, *, required: bool = False) -> tuple[list[dict[str, Any]], list[ToolIssue]]:
    if not path.exists():
        if required:
            return [], [ToolIssue("missing", f"missing {path.name}")]
        return [], []

    rows: list[dict[str, Any]] = []
    issues: list[ToolIssue] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception as exc:
                issues.append(ToolIssue("parse", f"malformed {path.name}:{line_number}: {exc}"))
                continue
            if isinstance(item, dict):
                rows.append(item)
            else:
                issues.append(ToolIssue("parse", f"malformed {path.name}:{line_number}: expected object"))
    return rows, issues


def _walk_json(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _event_message(event: dict[str, Any]) -> str:
    payload = event.get("payload")
    messages: list[str] = []
    if isinstance(payload, dict):
        for key in ("error_message", "message", "reason"):
            _add_unique(messages, payload.get(key), limit=3)
    if not messages:
        _add_unique(messages, event.get("event_type"), limit=1)
    return "; ".join(messages)


def _scan_events(run_dir: Path) -> tuple[int, int, list[str], list[ToolIssue]]:
    rows, issues = _load_jsonl_rows(run_dir / "events.jsonl", required=True)
    error_count = 0
    warning_count = 0
    messages: list[str] = []

    for event in rows:
        level = _clean_text(event.get("level")).lower()
        event_type = _clean_text(event.get("event_type")).lower()
        is_error = level == "error" or event_type == "error"
        is_warning = level == "warning" or "warning" in event_type or event_type.endswith("_failed")
        if is_error:
            error_count += 1
            _add_unique(messages, _event_message(event))
        elif is_warning:
            warning_count += 1
            _add_unique(messages, _event_message(event))

        payload = event.get("payload")
        if isinstance(payload, dict):
            _add_unique(messages, payload.get("error_message"))

    return error_count, warning_count, messages, issues


def _analysis_problem_messages(row: dict[str, Any], *, source_name: str) -> list[str]:
    messages: list[str] = []
    for key, value in _walk_json(row):
        key_l = key.lower()
        if key_l == "error_message":
            _add_unique(messages, f"{source_name}: {value}")
        elif key_l == "failure_reason":
            _add_unique(messages, f"{source_name}: {value}")
        elif key_l == "warnings" and isinstance(value, list) and value:
            _add_unique(messages, f"{source_name}: warnings={json.dumps(value, sort_keys=True)}")
        elif key_l == "status" and _clean_text(value).lower() in PROBLEM_STATUS_VALUES:
            _add_unique(messages, f"{source_name}: status={value}")
        elif isinstance(value, bool) and value is False:
            if key_l.endswith(PROBLEM_BOOL_SUFFIXES):
                _add_unique(messages, f"{source_name}: {key}=false")
    return messages


def _scan_analysis_jsonl(run_dir: Path) -> tuple[int, list[str], list[ToolIssue]]:
    issues: list[ToolIssue] = []
    problem_count = 0
    messages: list[str] = []

    jsonl_paths = sorted(run_dir.glob("*.jsonl"), key=lambda path: path.name)
    expected_missing = sorted(EXPECTED_JSONL_FILES - {path.name for path in jsonl_paths})
    for filename in expected_missing:
        if filename == "events.jsonl":
            continue
        issues.append(ToolIssue("missing", f"missing {filename}"))

    for path in jsonl_paths:
        if path.name == "events.jsonl":
            continue
        rows, path_issues = _load_jsonl_rows(path)
        issues.extend(path_issues)
        for row in rows:
            row_messages = _analysis_problem_messages(row, source_name=path.name)
            if row_messages:
                problem_count += 1
                for message in row_messages:
                    _add_unique(messages, message)

    return problem_count, messages, issues


def _discover_run_dirs(recordings_root: Path) -> list[Path]:
    run_dirs: set[Path] = set()
    for meta_path in recordings_root.glob("*/*/run_meta.json"):
        run_dirs.add(meta_path.parent)
    if recordings_root.exists():
        for process_dir in recordings_root.iterdir():
            if not process_dir.is_dir():
                continue
            for run_dir in process_dir.iterdir():
                if run_dir.is_dir() and (
                    run_dir.name.startswith("run_")
                    or (run_dir / "verdict.json").exists()
                    or (run_dir / "events.jsonl").exists()
                    or (run_dir / "analysis.jsonl").exists()
                ):
                    run_dirs.add(run_dir)
    return sorted(run_dirs, key=lambda path: (path.parent.name, path.name))


def _summarize_run(run_dir: Path) -> tuple[dict[str, Any], int]:
    issues: list[ToolIssue] = []
    messages: list[str] = []
    review_reasons: list[str] = []

    meta, meta_issues = _load_json_object(run_dir / "run_meta.json", required=True)
    verdict, verdict_issues = _load_json_object(run_dir / "verdict.json", required=True)
    issues.extend(meta_issues)
    issues.extend(verdict_issues)

    event_error_count, event_warning_count, event_messages, event_issues = _scan_events(run_dir)
    analysis_problem_count, analysis_messages, analysis_issues = _scan_analysis_jsonl(run_dir)
    issues.extend(event_issues)
    issues.extend(analysis_issues)

    for issue in issues:
        _add_unique(messages, issue.message)
    for message in event_messages + analysis_messages:
        _add_unique(messages, message)

    run_id = _clean_text(meta.get("run_id")) or _clean_text(verdict.get("run_id")) or run_dir.name
    process_name = _clean_text(meta.get("process_name")) or _clean_text(verdict.get("process_name")) or run_dir.parent.name
    phase_name = _clean_text(meta.get("phase_name")) or _clean_text(verdict.get("phase_name"))
    meta_outcome = _clean_text(meta.get("outcome")) or "unknown"
    verdict_outcome = _clean_text(verdict.get("outcome")) or "unknown"

    if verdict_outcome.lower() != "success":
        _add_unique(review_reasons, f"verdict_{verdict_outcome.lower() or 'unknown'}")
    if meta_outcome.lower() != "completed":
        _add_unique(review_reasons, f"meta_outcome_{meta_outcome.lower() or 'unknown'}")
    if event_error_count:
        _add_unique(review_reasons, "event_errors")
    if event_warning_count:
        _add_unique(review_reasons, "event_warnings")
    if analysis_problem_count:
        _add_unique(review_reasons, "analysis_problems")

    recorder_warning_count = int(meta.get("recorder_warning_count") or 0)
    capture_write_failure_count = int(meta.get("capture_write_failure_count") or 0)
    if recorder_warning_count:
        _add_unique(review_reasons, "recorder_warnings")
        _add_unique(messages, f"recorder_warning_count={recorder_warning_count}")
    if capture_write_failure_count:
        _add_unique(review_reasons, "capture_write_failures")
        _add_unique(messages, f"capture_write_failure_count={capture_write_failure_count}")

    for failure in meta.get("capture_write_failures") or []:
        if isinstance(failure, dict):
            _add_unique(messages, failure.get("error_message"))
    for warning in meta.get("recorder_warnings") or []:
        if isinstance(warning, dict):
            _add_unique(messages, warning.get("kind") or warning.get("message") or warning.get("error_message"))

    if verdict_outcome.lower() != "success":
        _add_unique(messages, verdict.get("failure_summary"))
        _add_unique(messages, verdict.get("suspected_cause"))

    tool_error_count = len(issues)
    parse_error_count = sum(1 for issue in issues if issue.kind == "parse")
    if tool_error_count:
        _add_unique(review_reasons, "tool_errors")

    review_status = "needs_review" if review_reasons else "ok"
    row = {
        "run_id": run_id,
        "process_name": process_name,
        "phase_name": phase_name,
        "started_at_utc": _clean_text(meta.get("started_at_utc")),
        "ended_at_utc": _clean_text(meta.get("ended_at_utc")),
        "meta_outcome": meta_outcome,
        "verdict": verdict_outcome,
        "review_status": review_status,
        "review_reasons": "; ".join(review_reasons),
        "error_messages": "; ".join(messages),
        "event_error_count": int(event_error_count),
        "event_warning_count": int(event_warning_count),
        "analysis_problem_count": int(analysis_problem_count),
        "tool_error_count": int(tool_error_count),
        "run_dir": str(run_dir),
    }
    return row, parse_error_count


def resolve_recordings_root(
    experiment_dir: str | Path | None = None,
    *,
    recordings_root: str | Path | None = None,
) -> Path:
    if recordings_root:
        return Path(recordings_root).resolve()
    if not experiment_dir:
        raise ValueError("Provide experiment_dir or recordings_root.")
    return (Path(experiment_dir) / "calibration_recordings").resolve()


def default_output_path(
    experiment_dir: str | Path | None = None,
    *,
    recordings_root: str | Path | None = None,
) -> Path:
    if experiment_dir:
        return (Path(experiment_dir) / "calibration_recordings_summary.csv").resolve()
    root = resolve_recordings_root(recordings_root=recordings_root)
    return (root.parent / "calibration_recordings_summary.csv").resolve()


def build_calibration_recording_summary_rows(
    experiment_dir: str | Path | None = None,
    *,
    recordings_root: str | Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    root = resolve_recordings_root(experiment_dir, recordings_root=recordings_root)
    rows: list[dict[str, Any]] = []
    parse_error_count = 0

    if not root.exists():
        raise FileNotFoundError(f"calibration_recordings root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"calibration_recordings root is not a directory: {root}")

    for run_dir in _discover_run_dirs(root):
        row, row_parse_errors = _summarize_run(run_dir)
        rows.append(row)
        parse_error_count += int(row_parse_errors)

    rows.sort(
        key=lambda row: (
            _clean_text(row.get("started_at_utc")),
            _clean_text(row.get("process_name")),
            _clean_text(row.get("run_id")),
        )
    )
    stats = {
        "row_count": int(len(rows)),
        "needs_review_count": int(sum(1 for row in rows if row.get("review_status") == "needs_review")),
        "parse_error_count": int(parse_error_count),
        "tool_error_count": int(sum(int(row.get("tool_error_count") or 0) for row in rows)),
    }
    return rows, stats


def export_calibration_recording_summary(
    experiment_dir: str | Path | None = None,
    *,
    recordings_root: str | Path | None = None,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    rows, stats = build_calibration_recording_summary_rows(
        experiment_dir,
        recordings_root=recordings_root,
    )
    output = Path(out_path).resolve() if out_path else default_output_path(
        experiment_dir,
        recordings_root=recordings_root,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return {
        "output_path": str(output),
        **stats,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a flat CSV summary of calibration_recordings runs for an experiment."
    )
    parser.add_argument(
        "experiment_dir",
        nargs="?",
        help="Experiment directory containing calibration_recordings/.",
    )
    parser.add_argument(
        "--recordings-root",
        default="",
        help="Standalone calibration_recordings directory to scan.",
    )
    parser.add_argument("--out", default="", help="Output CSV path.")
    args = parser.parse_args(argv)

    if not args.experiment_dir and not args.recordings_root:
        parser.error("Provide an experiment_dir or --recordings-root.")

    result = export_calibration_recording_summary(
        args.experiment_dir or None,
        recordings_root=args.recordings_root or None,
        out_path=args.out or None,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
