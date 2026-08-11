from __future__ import annotations

import pytest

from tools.virtual_workflows.exploration_m13 import (
    CAMPAIGN_BUDGET,
    resolve_plan,
)
from tools.virtual_workflows.exploration_runner_m13 import (
    M13ExplorationRunConfig,
    execute_m13_exploration,
    load_m13_aggregate,
)


@pytest.mark.sil_lifecycle
def test_m13_frozen_campaign_runs_fresh_children_with_complete_semantic_coverage(
    tmp_path,
):
    plan = resolve_plan(
        timeout_seconds=270,
        execution_authorized=True,
    )
    result = execute_m13_exploration(
        M13ExplorationRunConfig(
            plan=plan,
            output_root=tmp_path,
            speed_multiplier=1000.0,
            qt_platform="offscreen",
            replay_command=(
                r".\env\Scripts\python.exe",
                r"tools\run_virtual_workflow.py",
                "--exploration",
                "design_calibration_lifecycle_v1",
            ),
        )
    )
    aggregate = result.aggregate
    assert result.exit_code == 0
    assert aggregate["classification"]["status"] == "pass"
    assert aggregate["release_gate"] == {"affected": True, "status": "pass"}
    assert aggregate["semantic_coverage"]["status"] == "complete"
    assert aggregate["original_failures"]["failure_count"] == 0
    assert len(aggregate["children"]) == 6
    assert all(child["outcome"] == "pass" for child in aggregate["children"])
    assert all(
        child["process"]["pid"] != aggregate["run"]["parent_pid"]
        for child in aggregate["children"]
    )
    assert aggregate["budgets"]["observed"]["action_rows"] <= (
        CAMPAIGN_BUDGET.action_rows
    )
    assert aggregate["budgets"]["observed"]["sessions"] == 18
    assert aggregate["budgets"]["observed"]["screenshots"] == 24
    assert all(aggregate["budgets"]["checks"].values())
    assert load_m13_aggregate(result.aggregate_path) == aggregate
