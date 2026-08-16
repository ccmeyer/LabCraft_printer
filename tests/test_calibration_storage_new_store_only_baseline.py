from __future__ import annotations

import json
from pathlib import Path


BASELINE = (
    Path(__file__).resolve().parent
    / "performance"
    / "baselines"
    / "calibration_storage_new_store_only_pi5_v1.json"
)


def test_new_store_only_pi_candidate_baseline_is_complete_and_conservative():
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert payload["schema_name"] == (
        "labcraft.calibration_storage.new_store_only_pi_baseline"
    )
    assert payload["schema_version"] == 1
    assert payload["status"] == "candidate_single_sample"
    assert payload["source"]["dirty_worktree"] is False
    assert len(payload["source"]["measured_report_sha256"]) == 64
    assert len(payload["source"]["report_set_sha256"]) == 64

    workload = payload["workload"]
    assert workload["process_count"] == 16
    assert workload["update_count"] == 17
    assert workload["canonical_result_count"] == 16
    assert workload["warmup_runs"] == 0
    assert workload["measured_runs"] == 1

    correctness = payload["correctness"]
    assert correctness["classification"] == "pass"
    assert correctness["canonical_only_main_experiment"] is True
    assert correctness["calibration_json_created"] is False
    assert correctness["legacy_write_count"] == 0
    assert correctness["historical_canary_dual_write"] is True
    assert correctness["rollback_canary_dual_write"] is True
    assert correctness["integrity_failures"] == 0

    observed = payload["observed"]
    limits = payload["candidate_upper_limits"]
    for metric, upper_limit in limits.items():
        assert metric in observed
        assert observed[metric] > 0
        assert upper_limit >= observed[metric] * 1.24
