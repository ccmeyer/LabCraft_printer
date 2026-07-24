from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.run_virtual_workflow import _comparison_exit_code, _parser, main
from tools.virtual_workflows.compare import (
    ComparisonError,
    ComparisonIncompleteError,
    build_report_set,
    compare_report_sets,
    comparison_markdown,
    create_baseline_summary,
    load_report_set,
    write_baseline_summary,
    write_report_set,
)
from tools.virtual_workflows.report import (
    REPORT_SCHEMA_NAME,
    REPORT_SCHEMA_VERSION,
    validate_report_v1,
)


def _report(
    *,
    run_id: str,
    p95: float = 40.0,
    p99: float = 50.0,
    service_gap_maximum: float = 100.0,
    phase_p95: float = 20.0,
    duration_ms: float = 10_000.0,
    status: str = "pass",
    dirty: bool = False,
    injected: bool = False,
    python_version: str = "3.13.14",
) -> dict:
    report = {
        "schema_name": REPORT_SCHEMA_NAME,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "scenario_name": "virtual_print_array",
            "scenario_version": "1",
            "run_mode": "offscreen_windows_sil",
            "timing_policy": "simulated_command_durations_x1",
            "warmup_runs": 0,
            "measured_runs": 1,
            "started_at_utc": "2026-07-23T00:00:00Z",
            "ended_at_utc": "2026-07-23T00:00:10Z",
            "duration_ms": duration_ms,
        },
        "source": {
            "git_commit": "a" * 40,
            "git_short_commit": "a" * 12,
            "dirty_worktree": dirty,
            "git_error": None,
        },
        "environment": {
            "operating_system": "Windows",
            "os_release": "11",
            "architecture": "AMD64",
            "cpu_identifier": "test-cpu",
            "python_version": python_version,
            "python_implementation": "CPython",
            "python_executable": str(
                (Path.cwd() / "env" / "Scripts" / "python.exe").resolve()
            ),
            "qt": {
                "binding": "real",
                "pyside_version": "6.11.1",
                "qt_version": "6.11.1",
                "module_path": "C:/repo/env/Lib/site-packages/PySide6/__init__.py",
                "platform": "offscreen",
            },
        },
        "safety": {
            "simulation": True,
            "hardware_access_allowed": False,
            "hardware_interfaces": {
                "serial": False,
                "GPIO": False,
                "camera": False,
                "balance": False,
                "MCU": False,
                "firmware_update": False,
            },
            "simulated_port": "SIMULATED",
            "scenario_root": "C:/ignored/scenario-root",
            "root_containment_valid": True,
        },
        "workload": {
            "workload_id": "virtual_print_array_96_v1",
            "fixture_schema_version": 1,
            "plate_name": "shallow-384_well_plate",
            "plate_rows": 16,
            "plate_columns": 24,
            "well_ids": ["A1", "A2"],
            "stock_id": "Virtual Stock_1.00_x",
            "target_dispenses_per_well": 1,
            "expected_completion_count": 96,
            "speed_multiplier": 1.0,
            "timeout_seconds": 180.0,
        },
        "metrics": {
            "responsiveness": {
                "status": "measured",
                "values": {
                    "scheduling_lateness_ms": {
                        "p95": p95,
                        "p99": p99,
                        "maximum": max(p99, service_gap_maximum - 10.0),
                    },
                    "event_loop_gap_ms": {
                        "p95": p95 + 10.0,
                        "p99": p99 + 10.0,
                        "maximum": service_gap_maximum,
                    },
                    "phase_timings": {
                        "duration_by_name_ms": {
                            "controller.well_completion": {"p95": phase_p95},
                            "ui.well_plate_update": {"p95": phase_p95},
                            "persistence.write_progress": {"p95": phase_p95},
                            "persistence.complete_intent": {"p95": phase_p95},
                        }
                    },
                    "injected_stall_assessment": {
                        "requested": injected,
                        "requested_duration_ms": 300 if injected else 0,
                        "after_completion": 48,
                        "detected": injected,
                        "stack_captured": injected,
                        "decision": "detected" if injected else "not_requested",
                    },
                },
            },
            "workflow": {"status": "measured", "values": {}},
            "queue": {"status": "measured", "values": {}},
            "persistence": {"status": "measured", "values": {}},
            "resources": {"status": "partial", "values": {}},
        },
        "artifacts": {},
        "classification": {
            "status": status,
            "threshold_maturity": "informational",
            "reasons": ["synthetic test report"],
        },
        "limitations": [],
    }
    validate_report_v1(report)
    return report


def _write_reports(
    root: Path,
    prefix: str,
    values: list[dict],
) -> list[Path]:
    paths: list[Path] = []
    for index, report in enumerate(values):
        path = root / f"{prefix}-{index}.json"
        path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        paths.append(path)
    return paths


def _report_set(
    root: Path,
    prefix: str,
    *,
    measured_values: list[dict] | None = None,
    warmup_value: dict | None = None,
    host_label: str = "windows-sil-primary-v1",
) -> dict:
    measured = measured_values or [
        _report(run_id=f"{prefix}-measured-{index}") for index in range(5)
    ]
    if warmup_value is None:
        warmup = copy.deepcopy(measured[0])
        warmup["run"]["run_id"] = f"{prefix}-warmup"
        warmup["metrics"]["responsiveness"]["values"]["scheduling_lateness_ms"].update(
            {"p95": 999, "p99": 999}
        )
    else:
        warmup = warmup_value
    measured_paths = _write_reports(root, f"{prefix}-measured", measured)
    warmup_paths = _write_reports(root, f"{prefix}-warmup", [warmup])
    return build_report_set(
        measured_paths,
        warmup_paths=warmup_paths,
        host_label=host_label,
    )


def _baseline(root: Path, *, maturity: str = "candidate") -> dict:
    return create_baseline_summary(
        _report_set(root, "baseline"),
        maturity=maturity,
    )


def test_build_report_set_preserves_run_boundaries_and_excludes_warmup(tmp_path):
    report_set = _report_set(tmp_path, "set")

    assert report_set["runs"]["warmup_count"] == 1
    assert report_set["runs"]["measured_count"] == 5
    metric = report_set["metrics"][
        "metrics.responsiveness.values.scheduling_lateness_ms.p95"
    ]
    assert metric["per_run"] == [40.0] * 5
    assert metric["distribution"]["median"] == 40.0
    assert all(len(item["sha256"]) == 64 for item in report_set["runs"]["measured"])
    assert report_set["noise"]["status"] == "acceptable"


def test_baseline_is_compact_clean_and_candidate_by_default(tmp_path):
    baseline = _baseline(tmp_path)

    assert baseline["threshold_maturity"] == "candidate"
    assert baseline["runs"]["warmup_count"] == 1
    assert baseline["runs"]["measured_count"] == 5
    metric = baseline["metrics"][
        "metrics.responsiveness.values.scheduling_lateness_ms.p95"
    ]
    assert "per_run" not in metric
    assert metric["distribution"]["median"] == 40.0
    assert baseline["source"] == {
        "git_commit": "a" * 40,
        "dirty_worktree": False,
    }
    assert (
        baseline["compatibility"]["environment"]["python_executable"]
        == "env/Scripts/python.exe"
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"dirty": True}, "clean worktrees"),
        ({"injected": True}, "injected stalls"),
    ],
)
def test_baseline_rejects_dirty_or_injected_runs(tmp_path, change, message):
    measured = [
        _report(run_id=f"run-{index}", **change) for index in range(5)
    ]
    report_set = _report_set(tmp_path, "rejected", measured_values=measured)

    with pytest.raises(ComparisonError, match=message):
        create_baseline_summary(report_set, maturity="candidate")


def test_baseline_requires_one_warmup_and_five_measured_runs(tmp_path):
    paths = _write_reports(
        tmp_path,
        "short",
        [_report(run_id=f"short-{index}") for index in range(4)],
    )
    report_set = build_report_set(paths, host_label="windows-sil-primary-v1")

    with pytest.raises(ComparisonIncompleteError, match="warm-up"):
        create_baseline_summary(report_set, maturity="candidate")


def test_unchanged_and_improved_candidates_pass(tmp_path):
    baseline = _baseline(tmp_path)
    unchanged = _report_set(tmp_path, "unchanged")
    improved = _report_set(
        tmp_path,
        "improved",
        measured_values=[
            _report(run_id=f"improved-{index}", p95=20, p99=25)
            for index in range(5)
        ],
    )

    assert compare_report_sets(baseline, unchanged)["classification"][
        "overall_status"
    ] == "pass"
    assert compare_report_sets(baseline, improved)["classification"][
        "overall_status"
    ] == "pass"


def test_candidate_relative_regression_warns_and_explains_rule(tmp_path):
    baseline = _baseline(tmp_path)
    candidate = _report_set(
        tmp_path,
        "warning",
        measured_values=[
            _report(run_id=f"warning-{index}", p95=65, p99=80)
            for index in range(5)
        ],
    )

    comparison = compare_report_sets(baseline, candidate)

    assert comparison["classification"]["overall_status"] == "warning"
    primary = [
        rule
        for rule in comparison["rules"]
        if rule["category"] == "primary" and rule["rule_type"] == "relative"
    ]
    assert all(rule["regression"] for rule in primary)
    assert all(rule["effective_noise_floor_ms"] == 10 for rule in primary)
    assert _comparison_exit_code(comparison) == 0


def test_relative_ratio_below_absolute_noise_floor_passes(tmp_path):
    baseline_set = _report_set(
        tmp_path,
        "small-baseline",
        measured_values=[
            _report(run_id=f"base-{index}", p95=2, p99=3)
            for index in range(5)
        ],
    )
    baseline = create_baseline_summary(baseline_set, maturity="candidate")
    candidate = _report_set(
        tmp_path,
        "small-candidate",
        measured_values=[
            _report(run_id=f"candidate-{index}", p95=3, p99=4)
            for index in range(5)
        ],
    )

    comparison = compare_report_sets(baseline, candidate)

    assert comparison["classification"]["overall_status"] == "pass"


def test_secondary_regression_warns_even_for_acceptance_baseline(tmp_path):
    baseline = _baseline(tmp_path, maturity="acceptance")
    candidate = _report_set(
        tmp_path,
        "secondary",
        measured_values=[
            _report(run_id=f"secondary-{index}", phase_p95=40)
            for index in range(5)
        ],
    )

    comparison = compare_report_sets(baseline, candidate)

    assert comparison["classification"]["overall_status"] == "warning"
    assert _comparison_exit_code(comparison) == 0


def test_acceptance_relative_and_absolute_severe_regressions_fail(tmp_path):
    baseline = _baseline(tmp_path, maturity="acceptance")
    relative = _report_set(
        tmp_path,
        "relative-fail",
        measured_values=[
            _report(run_id=f"relative-{index}", p95=65, p99=80)
            for index in range(5)
        ],
    )
    severe = _report_set(
        tmp_path,
        "severe-fail",
        measured_values=[
            _report(
                run_id=f"severe-{index}",
                service_gap_maximum=1100,
                p99=50,
            )
            for index in range(5)
        ],
    )

    relative_result = compare_report_sets(baseline, relative)
    severe_result = compare_report_sets(baseline, severe)

    assert relative_result["classification"]["overall_status"] == "fail"
    assert severe_result["classification"]["overall_status"] == "fail"
    assert _comparison_exit_code(relative_result) == 4
    assert _comparison_exit_code(severe_result) == 4


def test_candidate_absolute_stall_is_warning_and_synthetic_is_visible(tmp_path):
    baseline = _baseline(tmp_path)
    candidate = _report_set(
        tmp_path,
        "injected",
        measured_values=[
            _report(
                run_id=f"injected-{index}",
                service_gap_maximum=400,
                injected=True,
            )
            for index in range(5)
        ],
    )

    comparison = compare_report_sets(baseline, candidate)

    assert comparison["classification"]["overall_status"] == "warning"
    assert any("synthetic" in reason for reason in comparison["classification"]["reasons"])


def test_dirty_candidate_is_allowed_but_prominently_labeled(tmp_path):
    baseline = _baseline(tmp_path)
    candidate = _report_set(
        tmp_path,
        "dirty-candidate",
        measured_values=[
            _report(run_id=f"dirty-{index}", dirty=True)
            for index in range(5)
        ],
    )

    comparison = compare_report_sets(baseline, candidate)

    assert comparison["classification"]["overall_status"] == "pass"
    assert any(
        "dirty worktree" in reason
        for reason in comparison["classification"]["reasons"]
    )


def test_noisy_candidate_is_explicitly_incomplete(tmp_path):
    baseline = _baseline(tmp_path)
    candidate = _report_set(
        tmp_path,
        "noisy",
        measured_values=[
            _report(run_id=f"noisy-{index}", p95=value, p99=value)
            for index, value in enumerate([10, 10, 10, 10, 100])
        ],
    )

    comparison = compare_report_sets(baseline, candidate)

    assert comparison["noise"]["status"] == "noisy"
    assert comparison["classification"]["overall_status"] == "incomplete"
    assert _comparison_exit_code(comparison) == 3


def test_incompatible_environment_lists_exact_difference(tmp_path):
    baseline = _baseline(tmp_path)
    candidate = _report_set(
        tmp_path,
        "python-change",
        measured_values=[
            _report(run_id=f"python-{index}", python_version="3.14.0")
            for index in range(5)
        ],
    )

    comparison = compare_report_sets(baseline, candidate)

    assert comparison["compatibility"]["status"] == "incompatible"
    assert (
        "environment.python_version"
        in comparison["compatibility"]["differences"]
    )
    assert comparison["classification"]["overall_status"] == "incomplete"


def test_functional_failure_precedes_performance_classification(tmp_path):
    baseline = _baseline(tmp_path)
    reports = [_report(run_id=f"failed-{index}") for index in range(5)]
    reports[2]["classification"]["status"] = "fail"
    candidate = _report_set(tmp_path, "functional", measured_values=reports)

    comparison = compare_report_sets(baseline, candidate)

    assert comparison["functional"]["status"] == "fail"
    assert comparison["classification"]["functional_status"] == "fail"
    assert comparison["classification"]["performance_status"] == "not_evaluated"
    assert _comparison_exit_code(comparison) == 2


def test_missing_required_metric_is_explicitly_incomplete(tmp_path):
    report = _report(run_id="missing")
    del report["metrics"]["responsiveness"]["values"]["scheduling_lateness_ms"]["p99"]
    paths = _write_reports(tmp_path, "missing", [report])

    with pytest.raises(ComparisonIncompleteError, match="p99"):
        build_report_set(paths, host_label="windows-sil-primary-v1")


def test_report_hash_tampering_is_rejected(tmp_path):
    report_set = _report_set(tmp_path, "tamper")
    set_path = write_report_set(tmp_path / "report_set.json", report_set)
    raw_path = Path(report_set["runs"]["measured"][0]["path"])
    raw_path.write_text(raw_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ComparisonError, match="hash mismatch"):
        load_report_set(set_path)


def test_baseline_writer_refuses_silent_overwrite(tmp_path):
    baseline = _baseline(tmp_path)
    path = tmp_path / "baseline.json"
    write_baseline_summary(path, baseline)

    with pytest.raises(ComparisonError, match="refusing to overwrite"):
        write_baseline_summary(path, baseline)

    write_baseline_summary(path, baseline, replace=True)
    assert json.loads(path.read_text(encoding="utf-8"))["baseline_id"]


def test_comparison_markdown_contains_classification_and_rules(tmp_path):
    baseline = _baseline(tmp_path)
    candidate = _report_set(tmp_path, "markdown")
    text = comparison_markdown(compare_report_sets(baseline, candidate))

    assert "# Virtual Workflow Comparison" in text
    assert "Threshold maturity: `candidate`" in text
    assert "scheduling_lateness_ms.p95" in text
    assert "| 250.000 | pass |" in text


def test_cli_defaults_preserve_single_run_and_exit_mapping():
    args = _parser().parse_args([])

    assert args.warmup_runs == 0
    assert args.measured_runs == 1
    assert args.host_label is None
    assert args.compare is None
    assert _comparison_exit_code(
        {
            "classification": {
                "functional_status": "pass",
                "overall_status": "pass",
            }
        }
    ) == 0


def test_cli_repeated_collection_builds_one_report_set(
    tmp_path, monkeypatch, capsys
):
    from tools.virtual_workflows import scenarios

    reports = [
        _report(run_id=f"cli-{index}")
        for index in range(6)
    ]
    index = 0

    def fake_run(_config):
        nonlocal index
        report = reports[index]
        report_dir = tmp_path / f"raw-{index}"
        scenario_root = report_dir / "scenario-root"
        scenario_root.mkdir(parents=True)
        report["safety"]["scenario_root"] = str(scenario_root)
        (report_dir / "report.json").write_text(
            json.dumps(report, sort_keys=True),
            encoding="utf-8",
        )
        (report_dir / "summary.txt").write_text("synthetic\n", encoding="utf-8")
        index += 1
        return report

    monkeypatch.setattr(scenarios, "run_virtual_print_array_scenario", fake_run)

    exit_code = main(
        [
            "--output-root",
            str(tmp_path / "sets"),
            "--warmup-runs",
            "1",
            "--measured-runs",
            "5",
            "--host-label",
            "windows-sil-primary-v1",
        ]
    )

    assert exit_code == 0
    report_sets = list((tmp_path / "sets").rglob("report_set.json"))
    assert len(report_sets) == 1
    payload = load_report_set(report_sets[0])
    assert payload["runs"]["warmup_count"] == 1
    assert payload["runs"]["measured_count"] == 5
    assert "Report set:" in capsys.readouterr().out
