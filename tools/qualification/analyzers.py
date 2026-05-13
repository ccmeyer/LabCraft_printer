from __future__ import annotations

from typing import Any

from .manifest import QualificationManifest


ANALYSIS_SCHEMA = "qualification_analysis_v1"

_MATURITY_SEVERITY = {
    "informational": "info",
    "candidate": "warning",
    "acceptance": "error",
}

_DEFAULT_DOMAIN_BY_CATEGORY = {
    "protocol": "infrastructure",
    "session": "infrastructure",
    "status": "infrastructure",
    "flash": "infrastructure",
    "build": "infrastructure",
    "memory": "infrastructure",
    "crash": "infrastructure",
    "watchdog": "infrastructure",
    "motion": "machine_performance",
    "pressure": "machine_performance",
    "valve": "machine_performance",
    "pulse": "machine_performance",
    "safety": "machine_performance",
}


def _is_error(item: dict[str, Any]) -> bool:
    return item.get("severity") == "error" or item.get("status") == "fail"


def _is_warning(item: dict[str, Any]) -> bool:
    return item.get("severity") == "warning" or item.get("status") == "warning"


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _manifest_rule(manifest: QualificationManifest, test_id: Any) -> dict[str, Any]:
    if test_id is None:
        return {}
    try:
        key = str(int(test_id))
    except (TypeError, ValueError):
        key = str(test_id)
    value = manifest.analysis_rules.get(key, {})
    return dict(value) if isinstance(value, dict) else {}


def _category_and_domain(rule: dict[str, Any]) -> tuple[str, str]:
    category = str(rule.get("category") or "unknown")
    domain = str(rule.get("failure_domain") or _DEFAULT_DOMAIN_BY_CATEGORY.get(category) or "raw_firmware_failure")
    return category, domain


def _message_threshold(metric_name: str, value: Any, rule: dict[str, Any]) -> str:
    parts = [f"{metric_name}={value!r}"]
    if "min" in rule:
        parts.append(f"min={rule['min']!r}")
    if "max" in rule:
        parts.append(f"max={rule['max']!r}")
    if "equals" in rule:
        parts.append(f"equals={rule['equals']!r}")
    return ", ".join(parts)


def _metric_outside_threshold(value: Any, rule: dict[str, Any]) -> bool:
    if "equals" in rule:
        return value != rule.get("equals")
    numeric = _coerce_float(value)
    if numeric is None:
        return True
    min_value = _coerce_float(rule.get("min")) if "min" in rule else None
    max_value = _coerce_float(rule.get("max")) if "max" in rule else None
    if min_value is not None and numeric < min_value:
        return True
    if max_value is not None and numeric > max_value:
        return True
    return False


def _metric_evaluation(
    *,
    row: dict[str, Any],
    rule: dict[str, Any],
    metric_name: str,
    metric_rule: dict[str, Any],
) -> dict[str, Any]:
    metrics = row.get("metrics") or {}
    category, domain = _category_and_domain(rule)
    maturity = str(metric_rule.get("maturity", "informational")).lower()
    severity = _MATURITY_SEVERITY.get(maturity, "warning")
    test_id = row.get("test_id")
    test_name = row.get("name")
    base = {
        "item_kind": "metric",
        "test_id": test_id,
        "name": test_name,
        "category": category,
        "failure_domain": domain,
        "metric_name": metric_name,
        "threshold_maturity": maturity,
        "threshold_min": metric_rule.get("min"),
        "threshold_max": metric_rule.get("max"),
        "threshold_expected": metric_rule.get("equals"),
        "message": "",
    }
    if metric_name not in metrics:
        status = "fail" if severity == "error" else "warning"
        return {
            **base,
            "metric_value": None,
            "status": status,
            "severity": severity,
            "message": f"Metric '{metric_name}' is missing from test {test_id}.",
        }

    value = metrics.get(metric_name)
    outside = _metric_outside_threshold(value, metric_rule)
    if outside and severity == "error":
        status = "fail"
        message = f"Acceptance metric outside threshold: {_message_threshold(metric_name, value, metric_rule)}."
    elif outside and severity == "warning":
        status = "warning"
        message = f"Candidate metric outside threshold: {_message_threshold(metric_name, value, metric_rule)}."
    elif outside:
        status = "pass"
        message = f"Informational metric outside candidate bounds only: {_message_threshold(metric_name, value, metric_rule)}."
    else:
        status = "pass"
        message = f"Metric within threshold: {_message_threshold(metric_name, value, metric_rule)}."
    return {
        **base,
        "metric_value": value,
        "status": status,
        "severity": severity if status != "pass" else "info",
        "message": message,
    }


def _operator_notes(manifest: QualificationManifest) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    for fixture in manifest.fixtures:
        note = fixture.get("operator_note")
        if note:
            notes.append({
                "fixture_id": fixture.get("fixture_id"),
                "required_for": list(fixture.get("required_for") or []),
                "message": str(note),
            })
    return notes


def analyze_report(
    raw_selftest: dict[str, Any],
    manifest: QualificationManifest,
    manifest_checks: dict[str, Any],
    *,
    selftest_returncode: int = 0,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    metric_evaluations: list[dict[str, Any]] = []

    if int(selftest_returncode) != 0:
        items.append({
            "item_kind": "runner",
            "status": "fail",
            "severity": "error",
            "failure_domain": "infrastructure",
            "message": f"Self-test runner exited with return code {int(selftest_returncode)}.",
        })

    if bool(raw_selftest.get("aborted")):
        items.append({
            "item_kind": "run",
            "status": "fail",
            "severity": "error",
            "failure_domain": "infrastructure",
            "message": "Raw self-test report is marked aborted.",
        })

    summary_failed = int((raw_selftest.get("summary") or {}).get("failed") or 0)
    failed_result_rows = [row for row in raw_selftest.get("results") or [] if not bool(row.get("pass"))]
    if summary_failed > 0 and not failed_result_rows:
        items.append({
            "item_kind": "raw_summary",
            "status": "fail",
            "severity": "error",
            "failure_domain": "raw_firmware_failure",
            "message": f"Raw self-test summary reports {summary_failed} failure(s), but no failed result rows were present.",
        })

    missing_ids = list(manifest_checks.get("missing_test_ids") or [])
    if missing_ids:
        severity = "error" if manifest.enforce_expected_test_ids else "warning"
        items.append({
            "item_kind": "manifest_check",
            "status": "fail" if severity == "error" else "warning",
            "severity": severity,
            "failure_domain": "infrastructure",
            "message": f"Missing expected self-test IDs: {missing_ids}.",
            "missing_test_ids": missing_ids,
        })

    unexpected_ids = list(manifest_checks.get("unexpected_test_ids") or [])
    if unexpected_ids:
        items.append({
            "item_kind": "manifest_check",
            "status": "warning",
            "severity": "warning",
            "failure_domain": "infrastructure",
            "message": f"Unexpected self-test IDs were observed: {unexpected_ids}.",
            "unexpected_test_ids": unexpected_ids,
        })

    for row in raw_selftest.get("results") or []:
        rule = _manifest_rule(manifest, row.get("test_id"))
        category, domain = _category_and_domain(rule)
        passed = bool(row.get("pass"))
        firmware_item = {
            "item_kind": "firmware_result",
            "test_id": row.get("test_id"),
            "name": row.get("name"),
            "category": category,
            "status": "pass" if passed else "fail",
            "severity": "info" if passed else "error",
            "failure_domain": "none" if passed else domain,
            "message": "Raw firmware result passed." if passed else "Raw firmware result failed.",
        }
        items.append(firmware_item)

        metrics = rule.get("metrics") or {}
        if isinstance(metrics, dict):
            for metric_name, metric_rule in metrics.items():
                if isinstance(metric_rule, dict):
                    metric_evaluations.append(
                        _metric_evaluation(
                            row=row,
                            rule=rule,
                            metric_name=str(metric_name),
                            metric_rule=metric_rule,
                        )
                    )

    for row in raw_selftest.get("host_checks") or []:
        passed = bool(row.get("pass"))
        items.append({
            "item_kind": "host_check",
            "name": row.get("name"),
            "status": "pass" if passed else "fail",
            "severity": "info" if passed else "error",
            "failure_domain": "none" if passed else "infrastructure",
            "message": "Host check passed." if passed else "Host check failed.",
        })

    all_records = items + metric_evaluations
    error_count = sum(1 for item in all_records if _is_error(item))
    warning_count = sum(1 for item in all_records if _is_warning(item))
    status = "fail" if error_count else "pass"
    warnings = [
        {
            "failure_domain": item.get("failure_domain"),
            "message": item.get("message"),
            "item_kind": item.get("item_kind"),
            "test_id": item.get("test_id"),
            "name": item.get("name"),
        }
        for item in all_records
        if _is_warning(item)
    ]
    verdict = {
        "status": status,
        "blocking_issue_count": error_count,
        "warning_count": warning_count,
        "reason": "No blocking analyzer issues." if status == "pass" else "One or more blocking analyzer issues were found.",
    }
    return {
        "schema_version": ANALYSIS_SCHEMA,
        "status": status,
        "items": items,
        "metric_evaluations": metric_evaluations,
        "summary": {
            "item_count": len(items),
            "metric_evaluation_count": len(metric_evaluations),
            "blocking_issue_count": error_count,
            "warning_count": warning_count,
        },
        "verdict": verdict,
        "warnings": warnings,
        "operator_notes": _operator_notes(manifest),
    }
