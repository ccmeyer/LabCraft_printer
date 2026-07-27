import json
from pathlib import Path

import pytest

from tools.run_virtual_workflow import _parser
from tools.virtual_workflows.scenarios import (
    STRESS_WORKLOAD_ID,
    _create_prepared_fixture,
    fixture_well_ids,
    load_virtual_print_array_fixture,
)
from ExecutionPlan import load_execution_plan
from ExecutionProgressStore import execution_progress_storage_evidence


pytestmark = pytest.mark.virtual_workflow


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


def test_stress_scenario_source_stays_hardware_isolated():
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
