from __future__ import annotations

import json

import pytest
from PySide6.QtCore import Qt

from CalibrationClasses.View import (
    CharacterizationSummaryProxyModel,
    CharacterizationSummaryTableModel,
)
from CalibrationResultGrouping import (
    build_characterization_source_reference,
    enrich_characterization_result_sets,
)


SCENARIO_ID = "calibration_result_set_rechecks_v1"


def _candidate(process_run_id, update_id, timestamp, pressure, volume, ordinal=0):
    return {
        "result_id": f"result-{process_run_id}",
        "result_sha256": f"sha-result-{process_run_id}",
        "process_run_id": process_run_id,
        "update_id": update_id,
        "update_index": 0,
        "update_payload_sha256": f"sha-{update_id}",
        "row_ordinal": ordinal,
        "source_run_id": "session-1",
        "source_phase_key": "pressure_sweep_characterization",
        "source_step_index": 0 if process_run_id == "sweep-a" else 1,
        "source_pressure_index": ordinal,
        "phase": "sweep",
        "phase_label": "Sweep",
        "timestamp": timestamp,
        "timestamp_display": timestamp,
        "pw_us": 1400,
        "pressure_psi": pressure,
        "mean_nL": volume,
        "cv_pct": 2.5,
        "valid": True,
        "application_eligible": True,
    }


def _visible(model, proxy):
    return [
        model.raw_row_at(proxy.mapToSource(proxy.index(index, 0)).row())
        for index in range(proxy.rowCount())
    ]


@pytest.mark.sil_lifecycle
def test_calibration_result_set_rechecks(tmp_path, qapp):
    first_candidates = [
        _candidate(
            "sweep-a",
            "update-sweep-a",
            "2026-08-17T10:00:00Z",
            pressure,
            volume,
            ordinal,
        )
        for ordinal, (pressure, volume) in enumerate(
            ((0.58, 9.4), (0.62, 10.0), (0.66, 10.7), (0.70, 11.2))
        )
    ]
    second_candidate = _candidate(
        "sweep-b",
        "update-sweep-b",
        "2026-08-17T11:00:00Z",
        0.64,
        10.2,
    )
    selected_candidate = first_candidates[1]
    root_reference = build_characterization_source_reference(selected_candidate)
    first_recheck = {
        **selected_candidate,
        "result_id": "result-recheck-a",
        "result_sha256": "sha-result-recheck-a",
        "process_run_id": "recheck-a",
        "update_id": "update-recheck-a",
        "update_payload_sha256": "sha-update-recheck-a",
        "source_phase_key": "droplet_recheck",
        "source_step_index": 2,
        "source_pressure_index": 0,
        "phase": "recheck",
        "phase_label": "Recheck",
        "timestamp": "2026-08-17T10:05:00Z",
        "timestamp_display": "2026-08-17T10:05:00Z",
        "mean_nL": 9.9,
        "volume_delta_nL": -0.1,
        "volume_delta_percent": -1.0,
        "recheck_source": root_reference,
        "recheck_root_source": root_reference,
        "row_state": "in_progress",
        "application_eligible": False,
    }

    scripted_rows = first_candidates + [second_candidate, first_recheck]
    in_progress = enrich_characterization_result_sets(scripted_rows)
    assert [row["row_role"] for row in in_progress if row["candidate_key"] == in_progress[1]["candidate_key"]] == [
        "candidate",
        "recheck",
    ]
    print(
        "SIL_PROGRESS "
        + json.dumps(
            {
                "scenario_id": SCENARIO_ID,
                "stage": "recheck_1_in_progress",
                "sets": 2,
                "rows": len(in_progress),
            },
            sort_keys=True,
        ),
        flush=True,
    )

    first_recheck["row_state"] = "committed"
    first_recheck["application_eligible"] = True
    direct_reference = build_characterization_source_reference(first_recheck)
    second_recheck = {
        **first_recheck,
        "result_id": "result-recheck-b",
        "result_sha256": "sha-result-recheck-b",
        "process_run_id": "recheck-b",
        "update_id": "update-recheck-b",
        "update_payload_sha256": "sha-update-recheck-b",
        "source_step_index": 3,
        "timestamp": "2026-08-17T10:10:00Z",
        "timestamp_display": "2026-08-17T10:10:00Z",
        "mean_nL": 10.1,
        "volume_delta_nL": 0.1,
        "volume_delta_percent": 1.0,
        "recheck_source": direct_reference,
        "recheck_root_source": root_reference,
    }
    committed = enrich_characterization_result_sets(
        first_candidates + [second_candidate, first_recheck, second_recheck]
    )

    candidate_key = next(
        row["candidate_key"]
        for row in committed
        if row["process_run_id"] == "sweep-a" and row["row_ordinal"] == 1
    )
    confirmation_group = [
        row for row in committed if row["candidate_key"] == candidate_key
    ]
    assert [row["row_role"] for row in confirmation_group] == [
        "candidate",
        "recheck",
        "recheck",
    ]
    assert [row.get("recheck_no") for row in confirmation_group] == [None, 1, 2]
    assert {row["result_set_no"] for row in confirmation_group} == {1}

    model = CharacterizationSummaryTableModel(include_recorded=True)
    proxy = CharacterizationSummaryProxyModel()
    proxy.setSourceModel(model)
    model.set_rows(committed)
    proxy.setResultSetFilter(confirmation_group[0]["result_set_key"])
    proxy.sort(model.column_index("mean_nL"), Qt.DescendingOrder)
    qapp.processEvents()
    assert [row["row_role"] for row in _visible(model, proxy) if row["candidate_key"] == candidate_key] == [
        "candidate",
        "recheck",
        "recheck",
    ]

    snapshot_path = tmp_path / "result_sets.json"
    snapshot_path.write_text(json.dumps(committed, sort_keys=True), encoding="utf-8")
    reloaded = enrich_characterization_result_sets(
        json.loads(snapshot_path.read_text(encoding="utf-8"))
    )
    assert [row["row_identity_key"] for row in reloaded] == [
        row["row_identity_key"] for row in committed
    ]
    assert [row.get("recheck_no") for row in reloaded] == [
        row.get("recheck_no") for row in committed
    ]

    hardware_activity = {
        "camera": 0,
        "motion": 0,
        "pressure": 0,
        "dispense": 0,
        "serial": 0,
        "gpio": 0,
        "firmware": 0,
        "physical_ports": 0,
    }
    print(
        "SIL_PROGRESS "
        + json.dumps(
            {
                "scenario_id": SCENARIO_ID,
                "stage": "fresh_reload_complete",
                "sets": 2,
                "candidate_rows": 5,
                "recheck_rows": 2,
                "hardware_activity": hardware_activity,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    assert hardware_activity == {key: 0 for key in hardware_activity}
