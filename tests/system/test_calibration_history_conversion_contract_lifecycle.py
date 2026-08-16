from __future__ import annotations

import json

import pytest

from tools.virtual_workflows.calibration_history_conversion_journey import (
    ASSERTIONS,
    SCENARIO_ID,
)
from tools.virtual_workflows.registry import run_registered_scenario
from tools.virtual_workflows.report import validate_report_v1


@pytest.mark.sil_lifecycle
def test_historical_conversion_short_lifecycle(qapp, tmp_path):
    """Convert twelve compact records and prove fresh-reader use in one short run."""

    report = run_registered_scenario(
        SCENARIO_ID,
        output_root=tmp_path,
        speed_multiplier=1000.0,
        timeout_seconds=120.0,
        run_id="calibration-history-conversion-short-success",
        seed=1,
    )
    validate_report_v1(report)
    assert report["classification"]["status"] == "pass", json.dumps(
        report["classification"], indent=2
    )
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in report["metrics"]["workflow"]["values"]["assertion_results"]
    }
    assert decisions == {assertion_id: "pass" for assertion_id in ASSERTIONS}
    conversion = report["metrics"]["persistence"]["values"][
        "calibration_history_conversion"
    ]
    assert conversion["plan_counts"] == {
        "source_step_count": 12,
        "convert_count": 9,
        "already_canonical_count": 1,
        "already_generated_count": 0,
        "skipped_count": 2,
        "conflict_count": 0,
    }
    assert conversion["generated_count"] == 9
    assert conversion["reader_export"]["source_immutable"] is True
    assert conversion["reader_export"]["idempotent"] is True
    assert not any(report["safety"]["hardware_interfaces"].values())
