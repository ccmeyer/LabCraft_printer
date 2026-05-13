from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .analyzers import analyze_report
from .artifacts import RunArtifacts
from .manifest import QualificationManifest


QUALIFICATION_REPORT_SCHEMA = "qualification_report_v1"


def write_json_atomic(path: str | Path, payload: dict[str, Any]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".qualification_", suffix=".json", dir=str(out_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, out_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".qualification_", suffix=".csv", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _manifest_checks(raw_selftest: dict[str, Any], manifest: QualificationManifest) -> dict[str, Any]:
    observed = {
        int(row.get("test_id"))
        for row in raw_selftest.get("results", [])
        if row.get("test_id") is not None
    }
    expected = set(manifest.expected_test_ids)
    return {
        "expected_test_ids": sorted(expected),
        "observed_test_ids": sorted(observed),
        "missing_test_ids": sorted(expected - observed),
        "unexpected_test_ids": sorted(observed - expected),
        "enforced": bool(manifest.enforce_expected_test_ids),
    }


def normalize_report(
    raw_selftest: dict[str, Any],
    manifest: QualificationManifest,
    identity: dict[str, Any],
    artifacts: RunArtifacts,
    *,
    selftest_returncode: int = 0,
) -> dict[str, Any]:
    summary = dict(raw_selftest.get("summary") or {})
    aborted = bool(raw_selftest.get("aborted"))
    manifest_checks = _manifest_checks(raw_selftest, manifest)
    analysis = analyze_report(
        raw_selftest,
        manifest,
        manifest_checks,
        selftest_returncode=selftest_returncode,
    )
    verdict = dict(analysis.get("verdict") or {})
    overall_status = str(verdict.get("status") or analysis.get("status") or "fail")
    return {
        "schema_version": QUALIFICATION_REPORT_SCHEMA,
        "manifest": manifest.to_report_dict(),
        "machine": {
            "machine_id": identity.get("machine_id"),
            "machine_uuid": identity.get("machine_uuid"),
            "assigned_at": identity.get("assigned_at"),
            "notes": identity.get("notes", ""),
        },
        "run": {
            "run_dir": str(artifacts.run_dir),
            "raw_selftest_path": str(artifacts.raw_selftest_path),
            "report_path": str(artifacts.report_path),
            "summary_csv_path": str(artifacts.summary_csv_path),
            "selftest_returncode": int(selftest_returncode),
        },
        "overall_status": overall_status,
        "raw_summary": summary,
        "run_id": raw_selftest.get("run_id"),
        "profile": raw_selftest.get("profile"),
        "started_at": raw_selftest.get("started_at"),
        "finished_at": raw_selftest.get("finished_at"),
        "aborted": aborted,
        "manifest_checks": manifest_checks,
        "results": list(raw_selftest.get("results") or []),
        "host_checks": list(raw_selftest.get("host_checks") or []),
        "analysis": analysis,
        "verdict": verdict,
        "warnings": list(analysis.get("warnings") or []),
        "operator_notes": list(analysis.get("operator_notes") or []),
    }


def _analysis_item_by_result(report: dict[str, Any], item_kind: str, item_id: str, name: str) -> dict[str, Any]:
    for item in (report.get("analysis") or {}).get("items", []):
        if item.get("item_kind") != item_kind:
            continue
        if item_kind == "firmware_result" and str(item.get("test_id") or "") == item_id:
            return item
        if item_kind == "host_check" and str(item.get("name") or "") == name:
            return item
    return {}


def _common_summary_fields(report: dict[str, Any]) -> dict[str, str]:
    machine = report.get("machine", {})
    manifest = report.get("manifest", {})
    return {
        "report_schema_version": str(report.get("schema_version") or ""),
        "machine_id": str(machine.get("machine_id") or ""),
        "machine_uuid": str(machine.get("machine_uuid") or ""),
        "manifest_id": str(manifest.get("manifest_id") or ""),
        "manifest_profile": str(manifest.get("profile") or ""),
        "run_id": str(report.get("run_id") or ""),
        "profile": str(report.get("profile") or ""),
        "started_at": str(report.get("started_at") or ""),
        "finished_at": str(report.get("finished_at") or ""),
        "overall_status": str(report.get("overall_status") or ""),
    }


def _summary_rows(report: dict[str, Any]) -> list[dict[str, str]]:
    common = _common_summary_fields(report)
    rows: list[dict[str, str]] = []
    for item in report.get("results", []):
        item_id = str(item.get("test_id") or "")
        analysis_item = _analysis_item_by_result(report, "firmware_result", item_id, str(item.get("name") or ""))
        rows.append({
            **common,
            "item_kind": "firmware_result",
            "item_id": item_id,
            "name": str(item.get("name") or ""),
            "pass": str(bool(item.get("pass"))).lower(),
            "analysis_status": str(analysis_item.get("status") or ""),
            "failure_domain": str(analysis_item.get("failure_domain") or ""),
            "category": str(analysis_item.get("category") or ""),
            "metric_name": "",
            "metric_value": "",
            "threshold_maturity": "",
            "threshold_min": "",
            "threshold_max": "",
            "threshold_expected": "",
            "message": str(analysis_item.get("message") or ""),
            "payload_json": json.dumps(item.get("metrics") or {}, sort_keys=True, separators=(",", ":")),
        })
    for item in report.get("host_checks", []):
        analysis_item = _analysis_item_by_result(report, "host_check", "", str(item.get("name") or ""))
        rows.append({
            **common,
            "item_kind": "host_check",
            "item_id": "",
            "name": str(item.get("name") or ""),
            "pass": str(bool(item.get("pass"))).lower(),
            "analysis_status": str(analysis_item.get("status") or ""),
            "failure_domain": str(analysis_item.get("failure_domain") or ""),
            "category": "",
            "metric_name": "",
            "metric_value": "",
            "threshold_maturity": "",
            "threshold_min": "",
            "threshold_max": "",
            "threshold_expected": "",
            "message": str(analysis_item.get("message") or ""),
            "payload_json": json.dumps(item.get("details") or {}, sort_keys=True, separators=(",", ":")),
        })
    for item in (report.get("analysis") or {}).get("items", []):
        if item.get("item_kind") in {"firmware_result", "host_check"}:
            continue
        rows.append({
            **common,
            "item_kind": str(item.get("item_kind") or "analysis_issue"),
            "item_id": str(item.get("test_id") or ""),
            "name": str(item.get("name") or ""),
            "pass": str(item.get("status") != "fail").lower(),
            "analysis_status": str(item.get("status") or ""),
            "failure_domain": str(item.get("failure_domain") or ""),
            "category": str(item.get("category") or ""),
            "metric_name": "",
            "metric_value": "",
            "threshold_maturity": "",
            "threshold_min": "",
            "threshold_max": "",
            "threshold_expected": "",
            "message": str(item.get("message") or ""),
            "payload_json": json.dumps(item, sort_keys=True, separators=(",", ":")),
        })
    for item in (report.get("analysis") or {}).get("metric_evaluations", []):
        rows.append({
            **common,
            "item_kind": "analysis_metric",
            "item_id": str(item.get("test_id") or ""),
            "name": str(item.get("name") or ""),
            "pass": str(item.get("status") != "fail").lower(),
            "analysis_status": str(item.get("status") or ""),
            "failure_domain": str(item.get("failure_domain") or ""),
            "category": str(item.get("category") or ""),
            "metric_name": str(item.get("metric_name") or ""),
            "metric_value": str(item.get("metric_value") if item.get("metric_value") is not None else ""),
            "threshold_maturity": str(item.get("threshold_maturity") or ""),
            "threshold_min": str(item.get("threshold_min") if item.get("threshold_min") is not None else ""),
            "threshold_max": str(item.get("threshold_max") if item.get("threshold_max") is not None else ""),
            "threshold_expected": str(item.get("threshold_expected") if item.get("threshold_expected") is not None else ""),
            "message": str(item.get("message") or ""),
            "payload_json": json.dumps(item, sort_keys=True, separators=(",", ":")),
        })
    return rows


def write_summary_csv(path: str | Path, report: dict[str, Any]) -> None:
    out_path = Path(path)
    fieldnames = [
        "report_schema_version",
        "machine_id",
        "machine_uuid",
        "manifest_id",
        "manifest_profile",
        "run_id",
        "profile",
        "started_at",
        "finished_at",
        "overall_status",
        "item_kind",
        "item_id",
        "name",
        "pass",
        "analysis_status",
        "failure_domain",
        "category",
        "metric_name",
        "metric_value",
        "threshold_maturity",
        "threshold_min",
        "threshold_max",
        "threshold_expected",
        "message",
        "payload_json",
    ]
    rows = _summary_rows(report)
    with tempfile.TemporaryFile("w+", encoding="utf-8", newline="") as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        tmp.seek(0)
        text = tmp.read()
    _write_text_atomic(out_path, text)


def write_qualification_artifacts(
    raw_selftest: dict[str, Any],
    manifest: QualificationManifest,
    identity: dict[str, Any],
    artifacts: RunArtifacts,
    *,
    raw_source_path: str | Path | None = None,
    selftest_returncode: int = 0,
) -> dict[str, Any]:
    if raw_source_path is None:
        write_json_atomic(artifacts.raw_selftest_path, raw_selftest)
    else:
        source = Path(raw_source_path)
        if source.resolve() != artifacts.raw_selftest_path.resolve():
            shutil.copyfile(source, artifacts.raw_selftest_path)

    report = normalize_report(
        raw_selftest,
        manifest,
        identity,
        artifacts,
        selftest_returncode=selftest_returncode,
    )
    write_json_atomic(artifacts.report_path, report)
    write_summary_csv(artifacts.summary_csv_path, report)
    return report
