from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REPORT_SCHEMA = "qualification_report_v1"

SYSTEM_CATEGORIES = {
    "protocol",
    "session",
    "status",
    "flash",
    "build",
    "memory",
    "crash",
    "watchdog",
    "safety",
    "runner",
    "run",
    "manifest",
}

SUBSYSTEMS = (
    "All",
    "System",
    "Motion",
    "Pressure",
    "Valves/Pulses",
    "Gripper",
    "Host Checks",
)


class QualificationReportError(ValueError):
    """Raised when a report cannot be loaded as qualification_report_v1."""


@dataclass(frozen=True)
class QualificationReportIndexEntry:
    report_path: Path
    run_dir: Path
    machine_id: str
    manifest_id: str
    manifest_name: str
    profile: str
    overall_status: str
    started_at: str
    finished_at: str
    run_id: str
    fixture_id: str
    result_count: int
    host_check_count: int
    warning_count: int
    modified_at: float

    @property
    def display_time(self) -> str:
        return self.started_at or self.run_dir.name

    @property
    def display_name(self) -> str:
        status = self.overall_status.upper() if self.overall_status else "UNKNOWN"
        manifest = self.manifest_id or "unknown_manifest"
        machine = self.machine_id or "unknown_machine"
        return f"{self.display_time}  |  {machine}  |  {manifest}  |  {status}"


@dataclass(frozen=True)
class QualificationResultRow:
    subsystem: str
    item_kind: str
    item_id: str
    name: str
    raw_pass: str
    analysis_status: str
    category: str
    failure_domain: str
    metric_summary: str
    message: str
    details: dict[str, Any]


def default_report_root(repo_root: str | Path) -> Path:
    return Path(repo_root) / "hil_reports"


def load_report(path: str | Path) -> dict[str, Any]:
    report_path = Path(path)
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise QualificationReportError(f"Invalid JSON report: {report_path}") from exc
    except OSError as exc:
        raise QualificationReportError(f"Could not read report: {report_path}") from exc

    if not isinstance(payload, dict):
        raise QualificationReportError(f"Report must be a JSON object: {report_path}")
    if payload.get("schema_version") != REPORT_SCHEMA:
        raise QualificationReportError(f"Unsupported report schema in {report_path}")
    return payload


def build_index_entry(report_path: str | Path, report: dict[str, Any]) -> QualificationReportIndexEntry:
    path = Path(report_path)
    machine = report.get("machine") if isinstance(report.get("machine"), dict) else {}
    manifest = report.get("manifest") if isinstance(report.get("manifest"), dict) else {}
    run = report.get("run") if isinstance(report.get("run"), dict) else {}
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    results = report.get("results") if isinstance(report.get("results"), list) else []
    host_checks = report.get("host_checks") if isinstance(report.get("host_checks"), list) else []
    run_dir = Path(run.get("run_dir") or path.parent)
    if not run_dir.is_absolute():
        run_dir = path.parent
    try:
        modified_at = path.stat().st_mtime
    except OSError:
        modified_at = 0.0

    return QualificationReportIndexEntry(
        report_path=path,
        run_dir=run_dir,
        machine_id=str(machine.get("machine_id") or ""),
        manifest_id=str(manifest.get("manifest_id") or ""),
        manifest_name=str(manifest.get("name") or ""),
        profile=str(report.get("profile") or manifest.get("profile") or ""),
        overall_status=str(report.get("overall_status") or ""),
        started_at=str(report.get("started_at") or ""),
        finished_at=str(report.get("finished_at") or ""),
        run_id=str(report.get("run_id") or ""),
        fixture_id=str(run.get("fixture_id") or ""),
        result_count=len(results),
        host_check_count=len(host_checks),
        warning_count=len(warnings),
        modified_at=modified_at,
    )


def discover_report_entries(root: str | Path) -> list[QualificationReportIndexEntry]:
    report_root = Path(root)
    if not report_root.exists():
        return []

    entries: list[QualificationReportIndexEntry] = []
    for report_path in report_root.rglob("report.json"):
        try:
            report = load_report(report_path)
            entries.append(build_index_entry(report_path, report))
        except QualificationReportError:
            continue
    entries.sort(key=lambda item: (item.started_at or "", item.modified_at), reverse=True)
    return entries


def artifact_paths(report: dict[str, Any], *, report_path: str | Path | None = None) -> list[tuple[str, str]]:
    run = report.get("run") if isinstance(report.get("run"), dict) else {}
    pairs = [
        ("Run folder", run.get("run_dir")),
        ("Report JSON", run.get("report_path")),
        ("Raw self-test JSON", run.get("raw_selftest_path")),
        ("Summary CSV", run.get("summary_csv_path")),
    ]
    if report_path is not None and not pairs[1][1]:
        pairs[1] = ("Report JSON", str(report_path))
    return [(label, str(value or "")) for label, value in pairs]


def _props(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _status_rank(status: str) -> int:
    value = str(status or "").lower()
    if value == "fail":
        return 3
    if value == "warning":
        return 2
    if value == "pass":
        return 1
    return 0


def _merge_status(statuses: Iterable[str]) -> str:
    best = ""
    for status in statuses:
        if _status_rank(status) > _status_rank(best):
            best = str(status or "")
    return best or "unknown"


def _truth_text(value: Any) -> str:
    if value is None:
        return ""
    return "pass" if bool(value) else "fail"


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def summarize_mapping(mapping: dict[str, Any], *, limit: int = 6) -> str:
    if not mapping:
        return ""
    parts: list[str] = []
    for idx, (key, value) in enumerate(mapping.items()):
        if idx >= limit:
            parts.append(f"+{len(mapping) - limit} more")
            break
        parts.append(f"{key}={_format_value(value)}")
    return ", ".join(parts)


def _analysis_lookup(report: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
    items = analysis.get("items") if isinstance(analysis.get("items"), list) else []
    firmware: dict[str, dict[str, Any]] = {}
    host: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("item_kind") == "firmware_result":
            firmware[str(item.get("test_id") or "")] = item
        elif item.get("item_kind") == "host_check":
            host[str(item.get("name") or "")] = item
    return firmware, host


def _metric_evaluations_by_test(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
    evaluations = analysis.get("metric_evaluations") if isinstance(analysis.get("metric_evaluations"), list) else []
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in evaluations:
        if isinstance(item, dict):
            out[str(item.get("test_id") or "")].append(item)
    return out


def _fallback_category(item_id: str, name: str) -> str:
    low = str(name or "").lower()
    if "gripper" in low or "seal" in low:
        return "gripper"
    if "pressure" in low or "regulator" in low:
        return "pressure"
    if "valve" in low or "pulse" in low:
        return "pulse"
    if "motion" in low or "home" in low or "move" in low or "axis" in low:
        return "motion"

    try:
        test_id = int(item_id)
    except (TypeError, ValueError):
        return "system"
    if 2100 <= test_id <= 2399:
        return "pressure"
    if 2400 <= test_id <= 2499:
        return "pulse"
    if 2500 <= test_id <= 2599:
        return "gripper"
    if 2000 <= test_id <= 2099:
        return "motion"
    return "system"


def subsystem_for(category: str, item_kind: str = "") -> str:
    if item_kind == "host_check":
        return "Host Checks"
    value = str(category or "").lower()
    if value == "motion":
        return "Motion"
    if value == "pressure":
        return "Pressure"
    if value in {"valve", "pulse"}:
        return "Valves/Pulses"
    if value == "gripper":
        return "Gripper"
    if value in SYSTEM_CATEGORIES or not value:
        return "System"
    return "System"


def _metric_messages(evaluations: list[dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    for item in evaluations:
        status = str(item.get("status") or "").lower()
        if status in {"warning", "fail"}:
            message = str(item.get("message") or "").strip()
            if message:
                messages.append(message)
    return messages


def _metric_failure_domain(evaluations: list[dict[str, Any]]) -> str:
    for item in evaluations:
        status = str(item.get("status") or "").lower()
        domain = str(item.get("failure_domain") or "")
        if status in {"warning", "fail"} and domain and domain != "none":
            return domain
    return ""


def normalize_result_rows(report: dict[str, Any]) -> list[QualificationResultRow]:
    firmware_analysis, host_analysis = _analysis_lookup(report)
    metric_evals = _metric_evaluations_by_test(report)
    rows: list[QualificationResultRow] = []

    for result in report.get("results") or []:
        if not isinstance(result, dict):
            continue
        item_id = str(result.get("test_id") or "")
        name = str(result.get("name") or "")
        analysis = firmware_analysis.get(item_id, {})
        evaluations = metric_evals.get(item_id, [])
        status = _merge_status([str(analysis.get("status") or "")] + [str(e.get("status") or "") for e in evaluations])
        category = str(analysis.get("category") or _fallback_category(item_id, name))
        messages = _metric_messages(evaluations)
        message = "; ".join(messages) or str(analysis.get("message") or "")
        analysis_domain = str(analysis.get("failure_domain") or "")
        metric_domain = _metric_failure_domain(evaluations)
        failure_domain = metric_domain if metric_domain and analysis_domain in {"", "none"} else analysis_domain
        metrics = _props(result.get("metrics"))
        rows.append(
            QualificationResultRow(
                subsystem=subsystem_for(category),
                item_kind="firmware_result",
                item_id=item_id,
                name=name,
                raw_pass=_truth_text(result.get("pass")),
                analysis_status=status,
                category=category,
                failure_domain=failure_domain,
                metric_summary=summarize_mapping(metrics),
                message=message,
                details={
                    "result": result,
                    "analysis": analysis,
                    "metric_evaluations": evaluations,
                },
            )
        )

    for check in report.get("host_checks") or []:
        if not isinstance(check, dict):
            continue
        name = str(check.get("name") or "")
        analysis = host_analysis.get(name, {})
        details = _props(check.get("details"))
        rows.append(
            QualificationResultRow(
                subsystem="Host Checks",
                item_kind="host_check",
                item_id="",
                name=name,
                raw_pass=_truth_text(check.get("pass")),
                analysis_status=str(analysis.get("status") or ("pass" if check.get("pass") else "fail")),
                category="host",
                failure_domain=str(analysis.get("failure_domain") or ""),
                metric_summary=summarize_mapping(details),
                message=str(analysis.get("message") or ""),
                details={"host_check": check, "analysis": analysis},
            )
        )

    represented = {("firmware_result", row.item_id) for row in rows if row.item_kind == "firmware_result"}
    represented.update(("host_check", row.name) for row in rows if row.item_kind == "host_check")
    analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
    for item in analysis.get("items") or []:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("item_kind") or ""), str(item.get("test_id") or item.get("name") or ""))
        if key in represented or item.get("item_kind") in {"firmware_result", "host_check"}:
            continue
        item_kind = str(item.get("item_kind") or "analysis")
        category = str(item.get("category") or item_kind)
        rows.append(
            QualificationResultRow(
                subsystem=subsystem_for(category),
                item_kind=item_kind,
                item_id=str(item.get("test_id") or ""),
                name=str(item.get("name") or item_kind),
                raw_pass="",
                analysis_status=str(item.get("status") or ""),
                category=category,
                failure_domain=str(item.get("failure_domain") or ""),
                metric_summary="",
                message=str(item.get("message") or ""),
                details={"analysis": item},
            )
        )

    return rows
