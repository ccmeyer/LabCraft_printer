import json
import time
from pathlib import Path

import pytest

from tools.virtual_workflows.actions import ACTION_IDS
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    SMOKE_WORKLOAD_ID,
    VirtualPrintArrayScenarioConfig,
    fixture_well_ids,
    load_virtual_print_array_fixture,
    run_virtual_print_array_scenario,
)


def test_smoke_fixture_contract_is_exact():
    fixture = load_virtual_print_array_fixture(
        scenario_id=SMOKE_WORKLOAD_ID
    )
    wells = fixture_well_ids(fixture)

    assert fixture["fixture_id"] == SMOKE_WORKLOAD_ID
    assert fixture["schema_version"] == 2
    assert fixture["plate"] == {
        "name": "shallow-384_well_plate",
        "rows": 16,
        "columns": 24,
        "included_rows": ["A"],
        "serpentine": True,
    }
    assert fixture["workload"] == {
        "target_dispenses_per_stock_per_well": 1,
        "well_count": 24,
        "stock_count": 1,
        "array_passes": 1,
        "completion_count": 24,
    }
    assert fixture["simulation"] == {
        "dispense_frequency_hz": 20,
        "lookahead_wells": 2,
        "staging_slot": 0,
    }
    assert len(fixture["stocks"]) == 1
    assert wells == tuple(f"A{column}" for column in range(1, 25))

    config = VirtualPrintArrayScenarioConfig(
        scenario_id=SMOKE_WORKLOAD_ID
    )
    assert config.inject_after_completion == 12
    assert VirtualPrintArrayScenarioConfig(
        scenario_id=SMOKE_WORKLOAD_ID,
        inject_after_completion=24,
    ).inject_after_completion == 24
    with pytest.raises(ValueError, match="inject_after_completion"):
        VirtualPrintArrayScenarioConfig(
            scenario_id=SMOKE_WORKLOAD_ID,
            inject_after_completion=25,
        )


@pytest.mark.sil_smoke
def test_standard_smoke_completes_with_required_evidence(qapp, tmp_path):
    started = time.perf_counter()
    report = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            scenario_id=SMOKE_WORKLOAD_ID,
            output_root=tmp_path,
            speed_multiplier=1000.0,
            timeout_seconds=60.0,
            run_id="standard-smoke",
        )
    )
    elapsed_seconds = time.perf_counter() - started
    validate_report_v1(report)

    assert elapsed_seconds < 30
    assert report["run"]["duration_ms"] < 30_000
    assert report["classification"]["status"] == "pass", json.dumps(
        {
            "classification": report["classification"],
            "errors": report["metrics"]["workflow"]["values"]["errors"],
            "failed_actions": [
                item
                for item in report["metrics"]["workflow"]["values"]["action_results"]
                if item["status"] == "fail"
            ],
        },
        indent=2,
    )
    assert report["run"]["scenario_name"] == "virtual_print_array"
    assert report["run"]["scenario_version"] == "1"

    expected_wells = [f"A{column}" for column in range(1, 25)]
    workload = report["workload"]
    assert workload["workload_id"] == SMOKE_WORKLOAD_ID
    assert workload["plate_rows"] == 16
    assert workload["plate_columns"] == 24
    assert workload["well_ids"] == expected_wells
    assert workload["stock_count"] == 1
    assert workload["expected_completion_count"] == 24

    safety = report["safety"]
    assert safety["simulation"] is True
    assert safety["hardware_access_allowed"] is False
    assert safety["simulated_port"] == "SIMULATED"
    assert not any(safety["hardware_interfaces"].values())
    assert safety["root_containment_valid"] is True
    assert Path(safety["scenario_root"]).resolve().is_relative_to(
        tmp_path.resolve()
    )

    workflow = report["metrics"]["workflow"]["values"]
    assert workflow["completed_well_count"] == 24
    assert workflow["completed_stock_well_count"] == 24
    assert workflow["completed_well_ids"] == expected_wells
    assert workflow["well_update_count"] == 24
    assert workflow["array_complete_count"] == 1
    assert workflow["errors"] == []
    assert workflow["unexpected_dialogs"] == []
    assert [item["title"] for item in workflow["dialogs"]] == [
        "Start Print Array",
        "Evaporation Plate Dock Check",
    ]
    assert {item["action_id"] for item in workflow["action_results"]} == ACTION_IDS
    assert {item["status"] for item in workflow["action_results"]} == {"pass"}
    assert [item["name"] for item in workflow["lifecycle_milestones"]] == [
        "ready",
        "printing",
        "mid_array",
        "completed",
    ]
    assert len(workflow["cleanup_results"]) == 11
    assert {item["status"] for item in workflow["cleanup_results"]} == {"pass"}

    launch = next(
        item
        for item in workflow["action_results"]
        if item["action_id"] == "app.launch_simulated"
    )
    banner = launch["evidence"]["simulation_banner"]
    assert {
        key: banner[key]
        for key in ("present", "visible", "object_name")
    } == {
        "present": True,
        "visible": True,
        "object_name": "simulationIdentityBanner",
    }
    assert "SIMULATION" in banner["text"]
    assert "NO HARDWARE CONNECTED" in banner["text"]
    assert launch["evidence"]["plate_widget"] == {
        "rows": 16,
        "columns": 24,
        "well_label_count": 384,
    }

    queue = report["metrics"]["queue"]["values"]
    assert queue["unexpected_starvation_count"] == 0
    assert queue["simulator_cleanup"] == {
        "command_timer_active": False,
        "connection_timer_active": False,
        "deferred_timer_count": 0,
    }

    persistence = report["metrics"]["persistence"]["values"]
    assert persistence["intent_count"] == 24
    assert persistence["stock_well_completion_count"] == 24
    assert persistence["observed_completed_intent_count"] == 24
    assert persistence["checkpoint_retained_intent_count"] == 0
    assert persistence["checkpoint_pending_intent_count"] == 0
    assert persistence["checkpoint_max_observed_intent_count"] <= 2
    assert persistence["terminal_plan_state"] == "completed"
    authoritative_io = persistence["authoritative_io"]
    assert authoritative_io["hot_path_read_count"] == 0
    assert authoritative_io["execution_resume_hot_path_disk_load_count"] == 0
    assert authoritative_io["resume_save_fsync_count"] == 72
    assert authoritative_io["resume_save_replace_count"] == 72
    assert authoritative_io["progress_write_fsync_count"] == 24
    assert authoritative_io["progress_write_replace_count"] == 24
    assert authoritative_io["observer_restored"] is True
    snapshot = persistence["progress_snapshot"]
    assert snapshot["mode_counts"] == {
        "full_rebuild": 0,
        "cached_update": 24,
    }
    assert snapshot["observer_restored"] is True

    responsiveness = report["metrics"]["responsiveness"]["values"]
    assert responsiveness["shutdown"] == {
        "timer_active": False,
        "observer_thread_alive": False,
    }
    assert responsiveness["pressure_render_assessment"][
        "timer_active_after_teardown"
    ] is False

    report_dir = Path(safety["scenario_root"]).parent
    assert json.loads(
        (report_dir / "report.json").read_text(encoding="utf-8")
    ) == report
    for name in (
        "report.json",
        "summary.txt",
        "events.jsonl",
        "stall_stacks.txt",
        "application_stdout.log",
    ):
        assert (report_dir / name).is_file()
    assert not (report_dir / "failure_traceback.txt").exists()
    assert set(report["artifacts"]["screenshots"]) == {
        "ready",
        "printing",
        "mid_array",
        "completed",
    }
    for relative in report["artifacts"]["screenshots"].values():
        screenshot = report_dir / relative
        assert screenshot.is_file()
        assert screenshot.stat().st_size > 0
