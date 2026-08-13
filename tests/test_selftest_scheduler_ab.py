import pytest

from tools.compare_selftest_scheduler_ab import compare_reports
from tools.qualification.analyzers import analyze_report
from tools.qualification.manifest import load_manifest
from tools.qualification.report import _manifest_checks


def _report(mode: int, *, pg: int, pa: int = 5, watchdog_count: int = 0):
    expected = load_manifest(
        "selftest_scheduler_no_yield_v1" if mode == 0
        else "selftest_scheduler_cooperative_v1"
    ).expected_test_ids
    results = [
        {"test_id": test_id, "name": f"test_{test_id}", "pass": True, "metrics": {}}
        for test_id in expected
        if test_id not in (1041, 1043, 1044)
    ]
    results.extend([
        {"test_id": 1041, "name": "crash_record_retained_safe", "pass": True,
         "metrics": {"boot": 1, "fault_ct": watchdog_count, "wdg_ct": watchdog_count}},
        {"test_id": 1044, "name": "pressure_wdg_context_safe", "pass": True,
         "metrics": {"v": 0, "h": 0, "r": 0, "x": 0, "sf": 0}},
        {"test_id": 1043, "name": "selftest_scheduler_safe", "pass": True,
         "metrics": {"sm": mode, "rf": 29, "yc": 0 if mode == 0 else 29,
                     "txm": 20, "txt": 500, "pg": pg, "pa": pa, "ph": 1,
                     "pha": 2, "se": 0, "re": 0, "bc": 0,
                     "h": 0, "r": 0, "x": 0, "hw": 100, "sf": 0}},
    ])
    return {
        "profile": "SAFE", "aborted": False,
        "summary": {"total": 30, "passed": 30, "failed": 0},
        "results": results,
        "host_checks": [
            {"name": "selftest_progress_watchdog", "pass": True},
            *([{"name": "selftest_scheduler_status_cadence", "pass": True}]
              if mode == 1 else []),
        ],
        "startup_reset_report": None, "reset_report": None,
    }


def test_counterbalanced_comparison_confirms_repeated_a_lateness_with_clean_b():
    reports = [
        _report(0, pg=300), _report(1, pg=20), _report(1, pg=21),
        _report(0, pg=310), _report(0, pg=320), _report(1, pg=22),
    ]
    comparison = compare_reports(reports)
    assert comparison["order_valid"] is True
    assert comparison["all_b_strict"] is True
    assert comparison["late_a_count"] == 3
    assert comparison["classification"] == "selftest_starvation_confirmed"


def test_comparison_rejects_wrong_order():
    reports = [_report(1, pg=10) for _ in range(6)]
    comparison = compare_reports(reports)
    assert comparison["order_valid"] is False
    assert comparison["classification"] == "invalid_order"


def test_pressure_i2c_context_from_next_startup_is_attributed_to_previous_b_arm():
    reports = [
        _report(0, pg=20), _report(1, pg=20), _report(1, pg=20),
        _report(0, pg=20), _report(0, pg=20), _report(1, pg=20),
    ]
    reports[2]["startup_reset_report"] = {
        "last_fault": 9, "watchdog_late_task": 4, "active_command": 250,
    }
    retained = next(row for row in reports[2]["results"] if row["test_id"] == 1044)
    retained["metrics"].update({"v": 1, "ph": 3, "pha": 300, "re": 1})
    comparison = compare_reports(reports)
    assert comparison["arms"][1]["watchdog_reset_attributed"] is True
    assert comparison["classification"] == "pressure_i2c_stall_indicated"


def test_final_safe_closes_delayed_reset_attribution_for_last_b_arm():
    reports = [
        _report(0, pg=20), _report(1, pg=20), _report(1, pg=20),
        _report(0, pg=20), _report(0, pg=20), _report(1, pg=20),
    ]
    final_safe = _report(1, pg=20, watchdog_count=1)
    final_safe["startup_reset_report"] = {
        "last_fault": 9, "watchdog_late_task": 4, "active_command": 250,
    }
    comparison = compare_reports(reports, final_safe=final_safe)
    assert comparison["arms"][-1]["watchdog_reset_attributed"] is True
    assert comparison["all_b_strict"] is False


@pytest.mark.parametrize(
    ("metric", "value"),
    (("sm", 0), ("rf", 28), ("yc", 28), ("pg", 126), ("pa", 126),
     ("se", 1), ("re", 1), ("bc", 1), ("h", 1), ("r", 1), ("x", 1),
     ("hw", 4294967295), ("sf", 1)),
)
def test_cooperative_manifest_rejects_strict_gate_violations(metric, value):
    manifest = load_manifest("selftest_scheduler_cooperative_v1")
    raw = _report(1, pg=20)
    scheduler = next(row for row in raw["results"] if row["test_id"] == 1043)
    scheduler["metrics"][metric] = value
    checks = _manifest_checks(raw, manifest)
    analysis = analyze_report(raw, manifest, checks, selftest_returncode=0)
    assert analysis["status"] == "fail"


def test_cooperative_manifest_accepts_complete_strict_evidence():
    manifest = load_manifest("selftest_scheduler_cooperative_v1")
    raw = _report(1, pg=20)
    analysis = analyze_report(raw, manifest, _manifest_checks(raw, manifest), selftest_returncode=0)
    assert analysis["status"] == "pass"


@pytest.mark.parametrize(
    "host_check_name",
    ("selftest_progress_watchdog", "selftest_scheduler_status_cadence"),
)
def test_cooperative_manifest_rejects_missing_required_host_check(host_check_name):
    manifest = load_manifest("selftest_scheduler_cooperative_v1")
    raw = _report(1, pg=20)
    raw["host_checks"] = [
        row for row in raw["host_checks"] if row["name"] != host_check_name
    ]
    analysis = analyze_report(raw, manifest, _manifest_checks(raw, manifest), selftest_returncode=0)
    assert analysis["status"] == "fail"


@pytest.mark.parametrize(
    "host_check_name",
    ("selftest_progress_watchdog", "selftest_scheduler_status_cadence"),
)
def test_comparison_rejects_b_arm_with_failed_host_check(host_check_name):
    reports = [
        _report(0, pg=20), _report(1, pg=20), _report(1, pg=20),
        _report(0, pg=20), _report(0, pg=20), _report(1, pg=20),
    ]
    check = next(
        row for row in reports[1]["host_checks"]
        if row["name"] == host_check_name
    )
    check["pass"] = False
    comparison = compare_reports(reports)
    assert comparison["arms"][1]["strict_pass"] is False
    assert comparison["all_b_strict"] is False


def test_comparison_rejects_b_arm_with_unknown_stack_headroom():
    reports = [
        _report(0, pg=20), _report(1, pg=20), _report(1, pg=20),
        _report(0, pg=20), _report(0, pg=20), _report(1, pg=20),
    ]
    scheduler = next(
        row for row in reports[1]["results"] if row["test_id"] == 1043
    )
    scheduler["metrics"]["hw"] = 0xFFFFFFFF
    comparison = compare_reports(reports)
    assert comparison["arms"][1]["strict_pass"] is False
    assert comparison["all_b_strict"] is False
