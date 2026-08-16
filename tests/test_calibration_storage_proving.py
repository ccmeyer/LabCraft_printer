from __future__ import annotations

import json
from pathlib import Path

import pytest

from CalibrationRecordingStore import CalibrationRecordingStore
from tools.calibration_storage_proving import (
    ASSESSMENT_SCHEMA,
    ISSUE_LEDGER_SCHEMA,
    SNAPSHOT_SCHEMA,
    collect_snapshot,
    create_campaign,
    evaluate_campaign,
)


def _write_canonical_result(experiment: Path) -> None:
    store = CalibrationRecordingStore(
        experiment, clock=lambda: "2026-08-01T00:00:00Z"
    )
    run = store.start_run(
        calibration_session_id="session-proving",
        process_run_id="run_proving_0001",
        process_name="PressureSweepCharacterizationProcess",
        phase_name="pressure_sweep_characterization",
        result_kind="calibration",
        identity={"printer_head_id": "private-head", "stock_id": "private-stock"},
        capture_policy_requested="structured_only",
    )
    store.append_update(run, {"phase": run.phase_name, "result": {"pressure": 1.2}})
    store.finalize_run(
        run,
        outcome="completed",
        summary_projection={"application_eligible": True, "rows": []},
    )


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_proving_collector_validates_without_modifying_sources_and_redacts_ids(
    tmp_path, capsys
):
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    _write_canonical_result(experiment)
    tracked = {path: path.read_bytes() for path in experiment.rglob("*") if path.is_file()}
    campaign_path = tmp_path / "campaign.json"
    snapshot_path = tmp_path / "snapshot.json"
    create_campaign(
        campaign_id="m7-proving",
        source_commit="abc123",
        started_at_utc="2026-08-01T00:00:00Z",
        output=campaign_path,
    )

    snapshot = collect_snapshot(
        campaign_path=campaign_path,
        experiment_dirs=[experiment],
        observed_at_utc="2026-08-02T00:00:00Z",
        output=snapshot_path,
    )

    assert snapshot["completed_calibration_count"] == 1
    assert snapshot["observations"][0]["source_unchanged"] is True
    assert snapshot["observations"][0]["issues"] == []
    assert "private-head" not in snapshot_path.read_text(encoding="utf-8")
    assert "private-stock" not in snapshot_path.read_text(encoding="utf-8")
    assert tracked == {path: path.read_bytes() for path in tracked}
    assert "CALIBRATION_STORAGE_PROVING_PROGRESS" in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        collect_snapshot(
            campaign_path=campaign_path,
            experiment_dirs=[experiment],
            output=snapshot_path,
        )


def test_proving_evaluator_requires_duration_volume_heads_issues_and_two_pi_runs(
    tmp_path,
):
    campaign_path = tmp_path / "campaign.json"
    create_campaign(
        campaign_id="m7-proving",
        source_commit="abc123",
        started_at_utc="2026-08-01T00:00:00Z",
        output=campaign_path,
    )
    results = [
        {
            "result_id": f"result-{index}",
            "result_sha256": f"sha-{index}",
            "outcome": "completed",
            "result_kind": "calibration",
            "update_count": 1,
            "head_fingerprint": f"fingerprint-{index % 3}",
        }
        for index in range(20)
    ]
    snapshot_path = tmp_path / "snapshot.json"
    _write(
        snapshot_path,
        {
            "schema_name": SNAPSHOT_SCHEMA,
            "schema_version": 1,
            "campaign_id": "m7-proving",
            "source_commit": "abc123",
            "observed_at_utc": "2026-08-15T00:00:00Z",
            "observations": [
                {
                    "experiment": "experiment-001",
                    "source_unchanged": True,
                    "issues": [],
                    "results": results,
                }
            ],
        },
    )
    ledger_path = tmp_path / "issues.json"
    _write(
        ledger_path,
        {
            "schema_name": ISSUE_LEDGER_SCHEMA,
            "schema_version": 1,
            "campaign_id": "m7-proving",
            "issues": [],
        },
    )
    pi_paths = []
    for index in range(2):
        path = tmp_path / f"pi-{index}.json"
        _write(path, {"functional": {"status": "pass"}, "runs": {"measured_count": 1}})
        pi_paths.append(path)

    assessment = evaluate_campaign(
        campaign_path=campaign_path,
        snapshot_paths=[snapshot_path],
        issue_ledger_path=ledger_path,
        pi_report_sets=pi_paths,
        output=tmp_path / "assessment.json",
    )

    assert assessment["schema_name"] == ASSESSMENT_SCHEMA
    assert assessment["status"] == "pass"
    assert assessment["metrics"]["completed_calibration_count"] == 20
    assert assessment["metrics"]["distinct_head_count"] == 3
    assert assessment["heads"] == ["head-001", "head-002", "head-003"]
    assert assessment["limitations"]
