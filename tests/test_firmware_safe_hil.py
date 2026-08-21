from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "firmware_safe_hil.py"
SPEC = importlib.util.spec_from_file_location("firmware_safe_hil", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
safe_hil = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(safe_hil)


def _safe_report() -> dict:
    results = []
    for test_id in sorted(safe_hil.SAFE_TEST_IDS):
        metrics = {"observed": 1}
        if test_id == 1007:
            metrics = {
                "skipped_no_flash_task": 1,
                "cycles_started": 0,
                "cycles_timeout": 0,
                "ext_delta": 0,
                "flash_ack_delta": 0,
                "flash_task_wake_delta": 0,
                "flash_task_done_delta": 0,
                "ft_acc_delta": 0,
                "ft_ign_dis_delta": 0,
            }
        results.append(
            {"test_id": test_id, "name": f"safe-{test_id}", "pass": True, "metrics": metrics}
        )
    for test_id, metric in sorted(safe_hil.GATED_ACTUATION_METRICS.items()):
        results.append(
            {
                "test_id": test_id,
                "name": f"gated-{test_id}",
                "pass": True,
                "metrics": {
                    "profile": "SAFE",
                    "executed": 0,
                    "fixture_required": 1,
                    metric: 0,
                    "gate": "safe_only",
                },
            }
        )
    return {
        "run_id": "test-run",
        "profile": "SAFE",
        "aborted": False,
        "summary": {"total": 30, "passed": 30, "failed": 0},
        "results": results,
    }


def test_accepts_exact_plain_safe_inventory() -> None:
    evidence = safe_hil.validate_safe_report(_safe_report())
    assert evidence["status"] == "passed"
    assert evidence["result_count"] == 30
    assert evidence["flash_non_actuation_contract"] == "no_flash_task_zero_dispatch"


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"profile": "FULL"}, "not exactly SAFE"),
        ({"aborted": True}, "aborted"),
        ({"summary": {"total": 30, "passed": 29, "failed": 1}}, "summary"),
    ],
)
def test_rejects_nonpassing_envelope(update: dict, message: str) -> None:
    report = _safe_report()
    report.update(update)
    with pytest.raises(safe_hil.SafeHilValidationError, match=message):
        safe_hil.validate_safe_report(report)


def test_rejects_extra_selected_test() -> None:
    report = _safe_report()
    report["results"].append(
        {"test_id": 2030, "name": "selector", "pass": True, "metrics": {}}
    )
    report["summary"] = {"total": 31, "passed": 31, "failed": 0}
    with pytest.raises(safe_hil.SafeHilValidationError, match=r"extra=\[2030\]"):
        safe_hil.validate_safe_report(report)


def test_rejects_motion_gate_that_executed() -> None:
    report = _safe_report()
    result = next(row for row in report["results"] if row["test_id"] == 2001)
    result["metrics"]["executed"] = 1
    with pytest.raises(safe_hil.SafeHilValidationError, match="executed"):
        safe_hil.validate_safe_report(report)


def test_rejects_flash_output_armed() -> None:
    report = _safe_report()
    result = next(row for row in report["results"] if row["test_id"] == 1007)
    result["metrics"].update(
        {
            "skipped_no_flash_task": 0,
            "ft_rel_to_delta": 0,
            "ft_ack_to_delta": 0,
            "ft_print_to_delta": 0,
            "flash_session_armed": 0,
            "flash_fault_latched": 0,
        }
    )
    result["metrics"]["flash_output_armed"] = 1
    with pytest.raises(safe_hil.SafeHilValidationError, match="flash_output_armed"):
        safe_hil.validate_safe_report(report)


def test_present_flash_task_requires_explicit_disarm_fields() -> None:
    report = _safe_report()
    result = next(row for row in report["results"] if row["test_id"] == 1007)
    result["metrics"]["skipped_no_flash_task"] = 0
    with pytest.raises(safe_hil.SafeHilValidationError, match="ft_rel_to_delta"):
        safe_hil.validate_safe_report(report)


def test_load_seals_report_hash(tmp_path: Path) -> None:
    report = tmp_path / "safe.json"
    report.write_text(json.dumps(_safe_report()), encoding="utf-8")
    evidence = safe_hil.load_and_validate_safe_report(report)
    assert evidence["report_path"] == str(report.resolve())
    assert len(evidence["report_sha256"]) == 64


def test_current_source_contract_is_non_actuating() -> None:
    evidence = safe_hil.validate_safe_source_contract(Path(__file__).parents[1])
    assert evidence["status"] == "passed"
    assert evidence["gated_actuation_test_ids"] == sorted(
        safe_hil.GATED_ACTUATION_METRICS
    )
