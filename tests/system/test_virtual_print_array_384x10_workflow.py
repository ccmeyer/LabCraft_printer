import json
from pathlib import Path

import pytest

from tools.run_virtual_workflow import _parser
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    STRESS_WORKLOAD_ID,
    VirtualPrintArrayScenarioConfig,
    _create_prepared_fixture,
    fixture_well_ids,
    load_virtual_print_array_fixture,
    run_virtual_print_array_scenario,
)
from ExecutionPlan import load_execution_plan
from ExecutionProgressStore import execution_progress_storage_evidence


pytestmark = pytest.mark.virtual_workflow


def _reduced_fixture(tmp_path: Path) -> Path:
    fixture = load_virtual_print_array_fixture(
        scenario_id=STRESS_WORKLOAD_ID
    )
    fixture["plate"]["included_rows"] = ["A"]
    fixture["stocks"] = fixture["stocks"][:2]
    for stock in fixture["stocks"]:
        stock["concentration"] = 2.0
    fixture["workload"] = {
        "target_dispenses_per_stock_per_well": 1,
        "well_count": 24,
        "stock_count": 2,
        "array_passes": 2,
        "completion_count": 48,
    }
    path = tmp_path / "reduced-384x10-fixture.json"
    path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    return path


def test_tracked_384x10_fixture_is_exact_and_serpentine():
    fixture = load_virtual_print_array_fixture(
        scenario_id=STRESS_WORKLOAD_ID
    )
    wells = fixture_well_ids(fixture)

    assert fixture["fixture_id"] == STRESS_WORKLOAD_ID
    assert fixture["schema_version"] == 2
    assert fixture["plate"]["included_rows"] == list("ABCDEFGHIJKLMNOP")
    assert len(wells) == len(set(wells)) == 384
    assert wells[:24] == tuple(f"A{column}" for column in range(1, 25))
    assert wells[24:48] == tuple(f"B{column}" for column in range(24, 0, -1))
    assert wells[-24:] == tuple(f"P{column}" for column in range(24, 0, -1))
    assert fixture["workload"] == {
        "target_dispenses_per_stock_per_well": 1,
        "well_count": 384,
        "stock_count": 10,
        "array_passes": 10,
        "completion_count": 3840,
    }
    stock_ids = {
        (
            stock["factor_name"],
            stock["concentration"],
            stock["units"],
        )
        for stock in fixture["stocks"]
    }
    head_ids = {
        stock["printer_head"]["printer_head_id"]
        for stock in fixture["stocks"]
    }
    assert len(stock_ids) == len(head_ids) == 10


def test_cli_exposes_stress_scenario_and_single_report_set():
    args = _parser().parse_args(
        [
            "--scenario",
            STRESS_WORKLOAD_ID,
            "--emit-report-set",
            "--host-label",
            "pi5-sil-384x10-v1",
        ]
    )

    assert args.scenario == STRESS_WORKLOAD_ID
    assert args.emit_report_set is True
    assert args.warmup_runs == 0
    assert args.measured_runs == 1


def test_full_384x10_compact_progress_is_bounded(tmp_path):
    fixture = load_virtual_print_array_fixture(
        scenario_id=STRESS_WORKLOAD_ID
    )
    prepared = _create_prepared_fixture(tmp_path / "experiment", fixture)
    plan = load_execution_plan(
        Path(prepared["experiment_dir"]) / "execution_plan.json"
    )
    payload = json.loads(
        (Path(prepared["experiment_dir"]) / "progress.json").read_text(
            encoding="utf-8"
        )
    )

    evidence = execution_progress_storage_evidence(plan, payload)

    assert evidence["schema_version"] == 2
    assert evidence["encoded_size_bytes"] <= 20_000
    assert evidence["size_reduction_fraction"] >= 0.95


def test_reduced_multi_stock_scenario_uses_real_ui_and_durable_order(
    qapp,
    tmp_path,
):
    fixture_path = _reduced_fixture(tmp_path)
    report = run_virtual_print_array_scenario(
        VirtualPrintArrayScenarioConfig(
            scenario_id=STRESS_WORKLOAD_ID,
            fixture_path=fixture_path,
            output_root=tmp_path / "reports",
            speed_multiplier=1000.0,
            timeout_seconds=90.0,
            run_id="reduced-384x10",
        )
    )
    validate_report_v1(report)

    assert report["classification"]["status"] in {
        "pass",
        "warning",
    }, {
        "classification": report["classification"],
        "errors": report["metrics"]["workflow"]["values"]["errors"],
    }
    assert report["workload"]["workload_id"] == STRESS_WORKLOAD_ID
    assert report["workload"]["stock_count"] == 2
    assert report["workload"]["expected_completion_count"] == 48

    workflow = report["metrics"]["workflow"]["values"]
    assert workflow["completed_well_count"] == 24
    assert workflow["completed_stock_well_count"] == 48
    assert workflow["well_update_count"] == 48
    assert workflow["array_complete_count"] == 2
    assert workflow["pass_terminal_states"] == ["active", "completed"]
    assert [item["completed_well_updates"] for item in workflow["stock_passes"]] == [
        24,
        24,
    ]
    assert workflow["errors"] == []
    assert workflow["unexpected_dialogs"] == []

    persistence = report["metrics"]["persistence"]["values"]
    assert persistence["intent_count"] == 48
    assert persistence["stock_well_completion_count"] == 48
    assert persistence["checkpoint_max_observed_intent_count"] <= 2
    assert persistence["checkpoint_retained_intent_count"] == 0
    assert persistence["terminal_plan_state"] == "completed"
    assert persistence["progress_snapshot"]["mode_counts"] == {
        "full_rebuild": 0,
        "cached_update": 48,
    }
    assert persistence["progress_snapshot"]["serialized_size_statistics_bytes"][
        "count"
    ] == 48
    assert persistence["progress_format"]["schema_version"] == 2
    assert persistence["progress_format"]["size_reduction_fraction"] >= 0.95

    authoritative_io = persistence["authoritative_io"]
    assert authoritative_io["hot_path_read_count"] == 0
    assert authoritative_io["execution_resume_hot_path_disk_load_count"] == 0
    assert authoritative_io["guard_count"] == 48 * 4 + 4
    assert authoritative_io["resume_save_fsync_count"] == 48 * 3
    assert authoritative_io["resume_save_replace_count"] == 48 * 3
    assert authoritative_io["progress_write_fsync_count"] == 48
    assert authoritative_io["progress_write_replace_count"] == 48

    phases = persistence["phase_timings"]["duration_by_name_ms"]
    assert phases["controller.well_completion"]["count"] == 48
    assert phases["ui.well_plate_update"]["count"] == 48
    assert phases["persistence.guard_bundle"]["count"] == 48 * 4 + 4
    pass_start = persistence["pass_start"]
    assert pass_start["count"] == 2
    assert [item["pass_index"] for item in pass_start["records"]] == [1, 2]
    assert pass_start["total_duration_ms"]["count"] == 2
    assert "pass_start.total" in pass_start["inclusive_duration_by_name_ms"]
    assert "pass_start.total" in pass_start[
        "exclusive_phase_evidence"
    ]["summary_ms"]
    assert pass_start["records"][0]["io_delta"]["revision_read_count"] == 0
    assert pass_start["records"][0]["full_bundle_refresh_count"] == 0
    assert pass_start["records"][0]["preparation"]["cache_path"] == "cached_noop"
    assert pass_start["records"][1]["io_delta"]["revision_read_count"] == 0
    assert pass_start["records"][1]["full_bundle_refresh_count"] == 0
    assert pass_start["records"][1]["preparation"]["cache_path"] == "cached_noop"

    queue = report["metrics"]["queue"]["values"]
    assert queue["unexpected_starvation_count"] == 0
    assert queue["event_trace_retention"]["counts"]["virtual_head_exchange"] == 2
    assert queue["simulator_cleanup"] == {
        "command_timer_active": False,
        "connection_timer_active": False,
        "deferred_timer_count": 0,
    }

    stress = report["metrics"]["responsiveness"]["values"]["stress_assessment"]
    assert stress["applicable"] is True
    assert stress["decision"] in {"responsive", "warning"}
    assert report["metrics"]["responsiveness"]["values"][
        "pressure_render_assessment"
    ]["active_render_interval_ms"]["count"] > 0

    report_dir = Path(report["safety"]["scenario_root"]).parent
    assert (report_dir / "report.json").is_file()
    assert (report_dir / "events.jsonl").is_file()
    assert not (report_dir / "failure_traceback.txt").exists()


def test_stress_scenario_source_stays_hardware_isolated():
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
