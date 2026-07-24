import json
from pathlib import Path

import pytest

from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    WORKLOAD_ID,
    VirtualPrintArrayScenarioConfig,
    fixture_well_ids,
    load_virtual_print_array_fixture,
    run_virtual_print_array_scenario,
)


def _report_dir(report):
    return Path(report["safety"]["scenario_root"]).parent


def test_fixture_contract_is_exact_and_serpentine():
    fixture = load_virtual_print_array_fixture()
    wells = fixture_well_ids(fixture)

    assert fixture["fixture_id"] == WORKLOAD_ID
    assert fixture["plate"] == {
        "name": "shallow-384_well_plate",
        "rows": 16,
        "columns": 24,
        "included_rows": ["A", "B", "C", "D"],
        "serpentine": True,
    }
    assert fixture["workload"] == {
        "target_dispenses_per_well": 1,
        "completion_count": 96,
    }
    assert len(wells) == len(set(wells)) == 96
    assert wells[:24] == tuple(f"A{column}" for column in range(1, 25))
    assert wells[24:48] == tuple(f"B{column}" for column in range(24, 0, -1))
    assert wells[48:72] == tuple(f"C{column}" for column in range(1, 25))
    assert wells[72:] == tuple(f"D{column}" for column in range(24, 0, -1))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("speed_multiplier", 0, "speed_multiplier"),
        ("timeout_seconds", 0, "timeout_seconds"),
        ("inject_ui_stall_ms", -1, "inject_ui_stall_ms"),
        ("inject_after_completion", 97, "inject_after_completion"),
    ],
)
def test_scenario_config_rejects_invalid_controls(field, value, message):
    values = {field: value}
    with pytest.raises(ValueError, match=message):
        VirtualPrintArrayScenarioConfig(**values)


def test_real_ui_print_array_completes_and_writes_inspectable_report(qapp, tmp_path):
    report = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            output_root=tmp_path,
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
            run_id="focused-normal",
        )
    )
    validate_report_v1(report)

    assert report["classification"] == {
        "status": "pass",
        "threshold_maturity": "informational",
        "reasons": [
            "All functional, persistence, UI, and simulation-safety invariants passed."
        ],
    }
    assert report["workload"]["workload_id"] == WORKLOAD_ID
    assert report["metrics"]["workflow"]["values"]["completed_well_count"] == 96
    assert report["metrics"]["workflow"]["values"]["array_complete_count"] == 1
    assert [
        item["title"]
        for item in report["metrics"]["workflow"]["values"]["dialogs"]
    ] == ["Start Print Array", "Evaporation Plate Dock Check"]
    assert report["metrics"]["workflow"]["values"]["unexpected_dialogs"] == []
    assert report["metrics"]["workflow"]["values"]["errors"] == []
    assert report["metrics"]["queue"]["values"]["unexpected_starvation_count"] == 0
    assert report["metrics"]["persistence"]["values"]["intent_count"] == 96
    assert report["metrics"]["persistence"]["values"]["terminal_plan_state"] == "completed"

    phases = report["metrics"]["persistence"]["values"]["phase_timings"][
        "duration_by_name_ms"
    ]
    for phase in (
        "persistence.begin_intent",
        "persistence.attach_sequence",
        "persistence.write_progress",
        "persistence.complete_intent",
        "controller.well_completion",
        "ui.well_plate_update",
    ):
        assert phases[phase]["count"] == 96

    cleanup = report["metrics"]["queue"]["values"]["simulator_cleanup"]
    assert cleanup == {
        "command_timer_active": False,
        "connection_timer_active": False,
        "deferred_timer_count": 0,
    }
    assert report["metrics"]["responsiveness"]["values"]["shutdown"] == {
        "timer_active": False,
        "observer_thread_alive": False,
    }

    report_dir = _report_dir(report)
    on_disk = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    assert on_disk == report
    for name in (
        "report.json",
        "summary.txt",
        "events.jsonl",
        "stall_stacks.txt",
    ):
        assert (report_dir / name).is_file()
    assert not (report_dir / "failure_traceback.txt").exists()
    for relative in report["artifacts"]["screenshots"].values():
        screenshot = report_dir / relative
        assert screenshot.is_file()
        assert screenshot.stat().st_size > 0
    assert Path(report["safety"]["scenario_root"]).resolve().is_relative_to(
        tmp_path.resolve()
    )


def test_injected_ui_stall_is_detected_attributed_and_captures_stack(qapp, tmp_path):
    report = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            output_root=tmp_path,
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
            inject_ui_stall_ms=300,
            inject_after_completion=48,
            run_id="focused-injected",
        )
    )

    assert report["classification"]["status"] == "pass"
    assessment = report["metrics"]["responsiveness"]["values"][
        "injected_stall_assessment"
    ]
    assert assessment == {
        "requested": True,
        "requested_duration_ms": 300,
        "after_completion": 48,
        "detected": True,
        "stack_captured": True,
        "decision": "detected",
    }
    stalls = report["metrics"]["responsiveness"]["values"]["stall_events"]
    assert any((event.get("phase") or {}).get("name") == "injected_ui_stall" for event in stalls)
    captures = report["metrics"]["responsiveness"]["values"]["stack_captures"]
    assert any(
        (capture.get("phase") or {}).get("name") == "injected_ui_stall"
        for capture in captures
    )
    assert "injected_ui_stall" in (
        _report_dir(report) / "stall_stacks.txt"
    ).read_text(encoding="utf-8")


def test_timeout_failure_retains_diagnostics_and_failure_screenshot(qapp, tmp_path):
    report = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            output_root=tmp_path,
            speed_multiplier=1.0,
            timeout_seconds=0.1,
            run_id="focused-timeout",
        )
    )

    assert report["classification"]["status"] == "fail"
    assert report["classification"]["threshold_maturity"] == "informational"
    assert report["metrics"]["workflow"]["values"]["completed_well_count"] < 96
    report_dir = _report_dir(report)
    assert (report_dir / "failure_traceback.txt").is_file()
    assert (report_dir / "screenshots" / "failure.png").is_file()
    assert (report_dir / "events.jsonl").is_file()
    validate_report_v1(report)


def test_scenario_source_has_no_production_machine_or_device_construction():
    source = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "virtual_workflows"
        / "scenarios.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "Machine_FreeRTOS",
        "serial.Serial",
        "RefuelCamera(",
        "DropletCamera(",
        "Balance(",
        "DfuUpdateWorker(",
        "GPIO.",
    ):
        assert forbidden not in source
    assert "simulation_dependencies(" in source
    assert "make_simulated_machine_factory(" in source
    assert "SIMULATED_PORT" in source
