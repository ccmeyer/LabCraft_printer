from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


EXPECTED_MODES = (0, 1, 1, 0, 0, 1)


def _result(report: dict[str, Any], test_id: int) -> dict[str, Any]:
    for row in report.get("results") or []:
        if int(row.get("test_id", -1)) == test_id:
            return row
    return {}


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _host_check_pass(report: dict[str, Any], name: str) -> bool:
    return any(
        str(row.get("name")) == name and bool(row.get("pass"))
        for row in report.get("host_checks") or []
    )


def compare_reports(
    reports: Sequence[dict[str, Any]],
    sources: Sequence[str] | None = None,
    *,
    final_safe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(reports) != len(EXPECTED_MODES):
        raise ValueError("exactly six reports are required in A-B, B-A, A-B order")
    source_names = list(sources or [f"arm_{index + 1}" for index in range(6)])
    arms: list[dict[str, Any]] = []
    for index, (report, expected_mode) in enumerate(zip(reports, EXPECTED_MODES)):
        scheduler = _result(report, 1043)
        retained = _result(report, 1044)
        crash = _result(report, 1041)
        metrics = dict(scheduler.get("metrics") or {})
        retained_metrics = dict(retained.get("metrics") or {})
        crash_metrics = dict(crash.get("metrics") or {})
        observed_mode = _integer(metrics.get("sm"), -1)
        summary = dict(report.get("summary") or {})
        arms.append({
            "arm": index + 1,
            "label": "A" if expected_mode == 0 else "B",
            "source": source_names[index],
            "expected_mode": expected_mode,
            "observed_mode": observed_mode,
            "order_valid": observed_mode == expected_mode,
            "complete": not bool(report.get("aborted")) and _integer(summary.get("total")) == 30,
            "passed": _integer(summary.get("passed")),
            "failed": _integer(summary.get("failed")),
            "rf": _integer(metrics.get("rf"), -1),
            "yc": _integer(metrics.get("yc"), -1),
            "pg": _integer(metrics.get("pg"), -1),
            "pa": _integer(metrics.get("pa"), -1),
            "txm": _integer(metrics.get("txm"), -1),
            "txt": _integer(metrics.get("txt"), -1),
            "phase": _integer(metrics.get("ph"), -1),
            "phase_age": _integer(metrics.get("pha"), -1),
            "select_errors": _integer(metrics.get("se"), -1),
            "read_errors": _integer(metrics.get("re"), -1),
            "recoveries": _integer(metrics.get("bc"), -1),
            "stack_headroom": _integer(metrics.get("hw"), -1),
            "saturated": _integer(metrics.get("sf"), 1),
            "progress_watchdog_pass": _host_check_pass(report, "selftest_progress_watchdog"),
            "status_cadence_pass": _host_check_pass(report, "selftest_scheduler_status_cadence"),
            "retained_valid": _integer(retained_metrics.get("v"), 0),
            "retained_phase": _integer(retained_metrics.get("ph"), -1),
            "retained_phase_age": _integer(retained_metrics.get("pha"), -1),
            "retained_select_errors": _integer(retained_metrics.get("se"), 0),
            "retained_read_errors": _integer(retained_metrics.get("re"), 0),
            "retained_recoveries": _integer(retained_metrics.get("bc"), 0),
            "boot": _integer(crash_metrics.get("boot"), -1),
            "fault_count": _integer(crash_metrics.get("fault_ct"), -1),
            "watchdog_count": _integer(crash_metrics.get("wdg_ct"), -1),
            "direct_reset": report.get("reset_report") is not None,
            "watchdog_reset_attributed": report.get("reset_report") is not None,
        })

    # A startup pressure-watchdog report or counter increase belongs to the
    # preceding arm, because it is observed during the next HELLO.
    for index in range(1, len(arms)):
        startup = reports[index].get("startup_reset_report") or {}
        pressure_watchdog_startup = (
            _integer(startup.get("last_fault"), -1) == 9
            and _integer(startup.get("watchdog_late_task"), -1) == 4
            and _integer(startup.get("active_command"), -1) == 250
        )
        counter_increased = (
            arms[index - 1]["watchdog_count"] >= 0
            and arms[index]["watchdog_count"] > arms[index - 1]["watchdog_count"]
        )
        if pressure_watchdog_startup or counter_increased:
            arms[index - 1]["watchdog_reset_attributed"] = True
        if pressure_watchdog_startup and arms[index]["retained_valid"] == 1:
            for key in (
                "retained_valid", "retained_phase", "retained_phase_age",
                "retained_select_errors", "retained_read_errors", "retained_recoveries",
            ):
                arms[index - 1][key] = arms[index][key]

    if final_safe is not None:
        startup = final_safe.get("startup_reset_report") or {}
        final_crash = _result(final_safe, 1041)
        final_context = _result(final_safe, 1044)
        final_crash_metrics = dict(final_crash.get("metrics") or {})
        final_context_metrics = dict(final_context.get("metrics") or {})
        pressure_watchdog_startup = (
            _integer(startup.get("last_fault"), -1) == 9
            and _integer(startup.get("watchdog_late_task"), -1) == 4
            and _integer(startup.get("active_command"), -1) == 250
        )
        counter_increased = (
            arms[-1]["watchdog_count"] >= 0
            and _integer(final_crash_metrics.get("wdg_ct"), -1) > arms[-1]["watchdog_count"]
        )
        if pressure_watchdog_startup or counter_increased or final_safe.get("reset_report") is not None:
            arms[-1]["watchdog_reset_attributed"] = True
        if pressure_watchdog_startup and _integer(final_context_metrics.get("v"), 0) == 1:
            mapping = {
                "retained_valid": "v", "retained_phase": "ph",
                "retained_phase_age": "pha", "retained_select_errors": "se",
                "retained_read_errors": "re", "retained_recoveries": "bc",
            }
            for arm_key, metric_key in mapping.items():
                arms[-1][arm_key] = _integer(final_context_metrics.get(metric_key), 0)

    for arm in arms:
        if arm["label"] == "B":
            arm["strict_pass"] = (
                arm["order_valid"]
                and arm["complete"]
                and arm["failed"] == 0
                and arm["rf"] == 29
                and arm["yc"] == 29
                and 0 <= arm["pg"] <= 125
                and 0 <= arm["pa"] <= 125
                and arm["select_errors"] == 0
                and arm["read_errors"] == 0
                and arm["recoveries"] == 0
                and 1 <= arm["stack_headroom"] < 0xFFFFFFFF
                and arm["saturated"] == 0
                and arm["progress_watchdog_pass"]
                and arm["status_cadence_pass"]
                and not arm["watchdog_reset_attributed"]
            )
            arm["late"] = arm["pg"] >= 250 or arm["watchdog_reset_attributed"]
        else:
            arm["strict_pass"] = None
            arm["late"] = arm["pg"] >= 250 or arm["watchdog_reset_attributed"]

    a_arms = [arm for arm in arms if arm["label"] == "A"]
    b_arms = [arm for arm in arms if arm["label"] == "B"]
    all_b_strict = all(bool(arm["strict_pass"]) for arm in b_arms)
    late_a_count = sum(1 for arm in a_arms if arm["late"])
    b_sensor_stall = any(
        arm["watchdog_reset_attributed"]
        and arm["retained_valid"] == 1
        and arm["retained_phase"] in (2, 3, 4, 5)
        and arm["retained_phase_age"] >= 250
        and (arm["retained_select_errors"] > 0 or arm["retained_read_errors"] > 0 or arm["retained_recoveries"] > 0)
        for arm in b_arms
    )
    order_valid = all(arm["order_valid"] for arm in arms)
    if not order_valid:
        classification = "invalid_order"
    elif b_sensor_stall:
        classification = "pressure_i2c_stall_indicated"
    elif all_b_strict and late_a_count >= 2:
        classification = "selftest_starvation_confirmed"
    elif all_b_strict and late_a_count == 0:
        classification = "inconclusive_both_clean"
    else:
        classification = "mixed_or_incomplete"

    return {
        "schema_version": "selftest_scheduler_ab_v1",
        "expected_order": ["A", "B", "B", "A", "A", "B"],
        "order_valid": order_valid,
        "all_b_strict": all_b_strict,
        "late_a_count": late_a_count,
        "classification": classification,
        "arms": arms,
    }


def _markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "| Arm | Mode | Complete | pg ms | pa ms | tx max/total ms | I2C S/R/B | Host WDG/status | WDT reset | B strict |",
        "|---:|:---:|:---:|---:|---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for arm in comparison["arms"]:
        strict = "-" if arm["strict_pass"] is None else ("yes" if arm["strict_pass"] else "no")
        lines.append(
            f"| {arm['arm']} | {arm['label']} | {'yes' if arm['complete'] else 'no'} | "
            f"{arm['pg']} | {arm['pa']} | {arm['txm']}/{arm['txt']} | "
            f"{arm['select_errors']}/{arm['read_errors']}/{arm['recoveries']} | "
            f"{'yes' if arm['progress_watchdog_pass'] else 'no'}/"
            f"{'yes' if arm['status_cadence_pass'] else 'no'} | "
            f"{'yes' if arm['watchdog_reset_attributed'] else 'no'} | {strict} |"
        )
    lines.extend(["", f"Classification: `{comparison['classification']}`", ""])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare six self-test scheduler A/B reports.")
    parser.add_argument("reports", nargs=6, help="Reports in A-B, B-A, A-B order.")
    parser.add_argument("--out", required=True, help="Output comparison JSON path.")
    parser.add_argument("--final-safe", default=None, help="Optional final SAFE report used to close the last B arm.")
    args = parser.parse_args(argv)
    paths = [Path(value) for value in args.reports]
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    final_safe = None
    if args.final_safe:
        final_safe = json.loads(Path(args.final_safe).read_text(encoding="utf-8"))
    comparison = compare_reports(
        reports,
        [str(path) for path in paths],
        final_safe=final_safe,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    out_path.with_suffix(".md").write_text(_markdown(comparison), encoding="utf-8")
    print(f"Wrote scheduler A/B comparison: {out_path}")
    return 0 if comparison["order_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
