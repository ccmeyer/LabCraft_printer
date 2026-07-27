import json
from pathlib import Path

import pytest

from tools.virtual_workflows.actions import ACTION_IDS
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


def test_scenario_config_requires_paired_pi_safety_evidence(tmp_path):
    with pytest.raises(ValueError, match="must be provided together"):
        VirtualPrintArrayScenarioConfig(
            pi_preflight_path=tmp_path / "preflight.json"
        )


@pytest.mark.sil_regression
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
    actions = report["metrics"]["workflow"]["values"]["action_results"]
    assert {item["action_id"] for item in actions} == ACTION_IDS
    assert {item["status"] for item in actions} == {"pass"}
    assert [
        item["name"]
        for item in report["metrics"]["workflow"]["values"][
            "lifecycle_milestones"
        ]
    ] == ["ready", "printing", "mid_array", "completed"]
    cleanup_results = report["metrics"]["workflow"]["values"]["cleanup_results"]
    assert len(cleanup_results) == 11
    assert {item["status"] for item in cleanup_results} == {"pass"}
    assert report["metrics"]["queue"]["values"]["unexpected_starvation_count"] == 0
    assert report["metrics"]["persistence"]["values"]["intent_count"] == 96
    assert (
        report["metrics"]["persistence"]["values"][
            "observed_completed_intent_count"
        ]
        == 96
    )
    assert (
        report["metrics"]["persistence"]["values"][
            "checkpoint_retained_intent_count"
        ]
        == 0
    )
    assert (
        report["metrics"]["persistence"]["values"][
            "checkpoint_pending_intent_count"
        ]
        == 0
    )
    assert (
        report["metrics"]["persistence"]["values"][
            "checkpoint_max_observed_intent_count"
        ]
        <= 2
    )
    assert report["metrics"]["persistence"]["values"]["terminal_plan_state"] == "completed"
    authoritative_io = report["metrics"]["persistence"]["values"]["authoritative_io"]
    assert authoritative_io["hot_path_read_count"] == 0
    assert authoritative_io["execution_resume_hot_path_disk_load_count"] == 0
    assert authoritative_io["resume_save_fsync_count"] == 96 * 3
    assert authoritative_io["resume_save_replace_count"] == 96 * 3
    assert authoritative_io["progress_write_fsync_count"] == 96
    assert authoritative_io["progress_write_replace_count"] == 96
    assert authoritative_io["observer_restored"] is True
    terminal = report["metrics"]["persistence"]["values"]["terminal_transition"]
    assert terminal["count"] == 1
    assert terminal["records"][0]["state"] == "completed"
    assert terminal["records"][0]["full_bundle_refresh_count"] == 1
    assert terminal["records"][0]["preparation"]["cache_path"] == "cached_completion"
    assert terminal["records"][0]["preparation"]["exports"] == "unchanged"
    assert terminal["records"][0]["io_delta"]["fsync_count"] == 4
    assert terminal["records"][0]["io_delta"]["replace_count"] == 4
    assert terminal["total_duration_ms"]["count"] == 1
    assert "terminal_transition.total" in terminal["inclusive_duration_by_name_ms"]
    terminal_reads = authoritative_io["read_opens"]["by_phase"][
        "terminal_transition.full_validation"
    ]
    assert terminal_reads["experiment_design.json"]["count"] == 1
    assert terminal_reads["execution_plan.json"]["count"] == 1
    assert terminal_reads["progress.json"]["count"] == 1
    assert terminal_reads["execution_resume.json"]["count"] == 1
    assert all(
        phase == "terminal_transition.full_validation"
        or not phase.startswith("terminal_transition.")
        for phase in authoritative_io["read_opens"]["by_phase"]
    )
    assert all(
        evidence["count"] == 1
        for name, evidence in terminal_reads.items()
        if name.startswith("execution_plan_revisions/")
    )
    snapshot = report["metrics"]["persistence"]["values"]["progress_snapshot"]
    assert snapshot["mode_counts"] == {
        "full_rebuild": 0,
        "cached_update": 96,
    }
    assert snapshot["duration_statistics_ms"]["serialization"]["count"] == 96
    assert snapshot["duration_statistics_ms"]["atomic_write"]["count"] == 96
    assert snapshot["serialized_size_statistics_bytes"]["count"] == 96
    assert snapshot["non_durable_write_ms"]["count"] == 96
    assert snapshot["observer_restored"] is True

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
    assert phases["persistence.guard_bundle"]["count"] == 96 * 4 + 2
    assert phases["persistence.save_resume"]["count"] == 96 * 3
    assert phases["persistence.reconcile_cache"]["count"] == 96 * 3
    pressure_render = phases["ui.pressure_render"]
    assert pressure_render["count"] > 0
    assert pressure_render["maximum"] >= pressure_render["p95"] >= 0
    pressure_assessment = report["metrics"]["responsiveness"]["values"][
        "pressure_render_assessment"
    ]
    assert pressure_assessment["render_count"] == pressure_render["count"]
    assert pressure_assessment["update_signal_count"] > pressure_render["count"]
    assert pressure_assessment["coalesced_update_count"] == (
        pressure_assessment["update_signal_count"] - pressure_render["count"]
    )
    assert 0 < pressure_assessment["render_to_signal_ratio"] < 1
    assert pressure_assessment["render_interval_ms"] == 100
    assert pressure_assessment["timer_active_after_teardown"] is False
    assert pressure_assessment["duration_ms"] == pressure_render

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
    summary = (report_dir / "summary.txt").read_text(encoding="utf-8")
    assert (
        f"Pressure renders: {pressure_render['count']}; "
        f"p95 {pressure_render['p95']} ms; "
        f"max {pressure_render['maximum']} ms"
    ) in summary
    assert (
        "Pressure updates coalesced: "
        f"{pressure_assessment['coalesced_update_count']}/"
        f"{pressure_assessment['update_signal_count']}; interval 100 ms"
    ) in summary
    assert not (report_dir / "failure_traceback.txt").exists()
    for relative in report["artifacts"]["screenshots"].values():
        screenshot = report_dir / relative
        assert screenshot.is_file()
        assert screenshot.stat().st_size > 0
    assert Path(report["safety"]["scenario_root"]).resolve().is_relative_to(
        tmp_path.resolve()
    )


@pytest.mark.sil_regression
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


@pytest.mark.sil_regression
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
    workflow = report["metrics"]["workflow"]["values"]
    assert any(
        item["status"] == "fail" and item["failure_stage"]
        for item in workflow["action_results"]
    )
    assert workflow["action_results"][-1]["action_id"] == "scenario.teardown"
    assert workflow["action_results"][-1]["status"] == "pass"
    assert {item["status"] for item in workflow["cleanup_results"]} == {"pass"}
    report_dir = _report_dir(report)
    assert (report_dir / "failure_traceback.txt").is_file()
    assert (report_dir / "screenshots" / "failure.png").is_file()
    assert (report_dir / "events.jsonl").is_file()
    validate_report_v1(report)


def test_scenario_source_has_no_production_machine_or_device_construction():
    tools_root = Path(__file__).resolve().parents[2] / "tools" / "virtual_workflows"
    source = "\n".join(
        (tools_root / name).read_text(encoding="utf-8")
        for name in ("scenarios.py", "actions.py")
    )

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
