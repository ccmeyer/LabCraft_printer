import json
import time
from collections import Counter
from pathlib import Path

import pytest

from tools.virtual_workflows.actions import COMPOSED_SMOKE_ACTION_IDS
from tools.virtual_workflows.journeys import (
    SMOKE_REQUIRED_ASSERTIONS,
    SMOKE_REQUIRED_UI_ACTIONS,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1
from tools.virtual_workflows.scenarios import (
    SMOKE_WORKLOAD_ID,
    fixture_well_ids,
    load_virtual_print_array_fixture,
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

    assert fixture["stocks"][0]["prepared_droplet_volume_nL"] == 9.0
    assert fixture["stocks"][0]["droplet_volume_nL"] == 9.0


@pytest.mark.sil_smoke
def test_standard_smoke_completes_with_required_evidence(qapp, tmp_path):
    started = time.perf_counter()
    report = run_registered_scenario(
        SMOKE_WORKLOAD_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        run_id="standard-smoke",
        seed=7,
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
    assert report["run"]["seed"] == 7
    assert report["run"]["replay_command"][-1] == "60.0"

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
    scenario_root = Path(safety["scenario_root"]).resolve()
    report_dir = Path(safety["report_dir"]).resolve()
    assert not scenario_root.is_relative_to(Path.cwd().resolve())
    assert report_dir.is_relative_to(tmp_path.resolve())
    assert scenario_root.is_dir()

    workflow = report["metrics"]["workflow"]["values"]
    launch = next(
        item
        for item in workflow["action_results"]
        if item["action_id"] == "app.launch_simulated"
    )
    font = launch["evidence"]["font_rendering"]
    assert font["status"] == "pass"
    assert font["raw_font_valid"] is True
    assert font["sample_glyphs_renderable"] is True
    assert workflow["completed_well_count"] == 24
    assert workflow["completed_stock_well_count"] == 24
    assert workflow["completed_well_ids"] == expected_wells
    assert workflow["well_update_count"] == 24
    assert workflow["errors"] == []
    assert workflow["unexpected_dialogs"] == []
    assert [item["title"] for item in workflow["dialogs"]] == [
        "Start Print Array",
        "Evaporation Plate Dock Check",
    ]
    assert {
        item["action_id"] for item in workflow["action_results"]
    } == COMPOSED_SMOKE_ACTION_IDS | {
        "experiment.inspect_completed_via_ui",
        "head.return_via_ui",
    }
    assert {item["status"] for item in workflow["action_results"]} == {"pass"}
    action_counts = Counter(
        item["action_id"] for item in workflow["action_results"]
    )
    assert action_counts["calibration.open_via_ui"] == 2
    assert action_counts["calibration.generate_via_ui"] == 2
    assert action_counts["calibration.select_via_ui"] == 2
    assert action_counts["calibration.apply_via_ui"] == 1
    assert action_counts["editor.open_via_ui"] == 2
    assert action_counts["experiment.inspect_completed_via_ui"] == 1
    assert action_counts["head.return_via_ui"] == 1
    surfaces = {
        item["action_id"]: item["interaction_surface"]
        for item in workflow["action_results"]
        if item["action_id"] in SMOKE_REQUIRED_UI_ACTIONS
    }
    assert surfaces == {action_id: "ui" for action_id in SMOKE_REQUIRED_UI_ACTIONS}
    assert [item["name"] for item in workflow["lifecycle_milestones"]] == [
        "editor_opened",
        "generated",
        "ready",
        "printing",
        "completed",
    ]
    decisions = {
        item["assertion_id"]: item["decision"]
        for item in workflow["assertion_results"]
    }
    assert decisions == {item: "pass" for item in SMOKE_REQUIRED_ASSERTIONS}

    diagnostics = workflow["post_completion_diagnostics"]
    assert diagnostics["failed_checks"] == []
    assert all(diagnostics["checks"].values())
    assert diagnostics["boundary"]["plan_state"] == "completed"
    assert diagnostics["launch"]["button_enabled"] is True
    assert diagnostics["preview"]["preview_rows"] > 0
    assert diagnostics["preview"]["load_selected_enabled"] is True
    assert diagnostics["preview"]["apply_state"] == "unavailable"
    assert diagnostics["preview"]["apply_enabled"] is False
    assert diagnostics["before"] == diagnostics["after"]

    launch = next(
        item
        for item in workflow["action_results"]
        if item["action_id"] == "app.launch_simulated"
    )
    queue = report["metrics"]["queue"]["values"]
    assert queue["queue_drained_at_terminal"] is True

    persistence = report["metrics"]["persistence"]["values"]
    assert persistence["terminal"]["plan_state"] == "completed"
    assert persistence["terminal"]["checkpoint_intent_count"] == 0
    projection = persistence["same_session_completed_projection"]
    assert projection["failed_checks"] == []
    assert all(projection["checks"].values())
    assert projection["before"]["plan_state"] == "completed"
    assert projection["after"]["runtime_active"] is False
    assert projection["before"]["runtime_assignments"] == projection["after"][
        "runtime_assignments"
    ]
    assert projection["before"]["core_file_hashes"] == projection["after"][
        "core_file_hashes"
    ]
    assert projection["driver"]["editor"]["direct_read_only_launch"] is True
    assert projection["driver"]["editor"]["saved_progress_prompt_absent"] is True
    assert projection["driver"]["inspection"]["launch"] == {
        "direct_read_only": True,
        "saved_progress_prompt_absent": True,
        "unexpected_dialog": {},
    }
    assert projection["driver"]["inspection"]["unexpected_result_dialog"] == {}

    assert json.loads(
        (report_dir / "report.json").read_text(encoding="utf-8")
    ) == report
    for name in (
        "report.json",
        "summary.txt",
        "events.jsonl",
        "action_ledger.json",
        "assertion_ledger.json",
        "evidence_manifest.json",
    ):
        assert (report_dir / name).is_file()
    assert not (report_dir / "failure_traceback.txt").exists()
    assert set(report["artifacts"]["screenshots"]) == {
        "editor_opened",
        "generated",
        "ready",
        "printing",
        "completed",
    }
    for relative in report["artifacts"]["screenshots"].values():
        screenshot = report_dir / relative
        assert screenshot.is_file()
        assert screenshot.stat().st_size > 0

    evidence_manifest = json.loads(
        (report_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert "evidence_manifest.json" in evidence_manifest["excluded"]
    assert {item["path"] for item in evidence_manifest["files"]} >= {
        "report.json",
        "summary.txt",
        "events.jsonl",
        "action_ledger.json",
        "assertion_ledger.json",
    }
