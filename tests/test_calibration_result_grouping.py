from __future__ import annotations

import pytest

from CalibrationResultGrouping import (
    build_characterization_source_reference,
    characterization_candidate_rollup,
    characterization_result_set_options,
    enrich_characterization_result_sets,
)


def _row(
    process_run_id,
    update_id,
    *,
    timestamp,
    pressure,
    volume,
    phase="sweep",
    row_ordinal=0,
    valid=True,
    **extra,
):
    row = {
        "process_run_id": process_run_id,
        "update_id": update_id,
        "update_index": int(update_id.rsplit("-", 1)[-1]),
        "row_ordinal": row_ordinal,
        "result_id": f"result-{process_run_id}",
        "result_sha256": f"sha-{process_run_id}",
        "update_payload_sha256": f"sha-{update_id}",
        "source_run_id": "application-session",
        "source_phase_key": (
            "droplet_recheck" if phase == "recheck" else "pressure_sweep_characterization"
        ),
        "source_step_index": int(update_id.rsplit("-", 1)[-1]),
        "source_pressure_index": row_ordinal,
        "phase": phase,
        "phase_label": "Recheck" if phase == "recheck" else "Sweep",
        "timestamp": timestamp,
        "timestamp_display": timestamp,
        "pw_us": 1400,
        "pressure_psi": pressure,
        "mean_nL": volume,
        "cv_pct": 3.0,
        "valid": valid,
    }
    row.update(extra)
    return row


def test_process_runs_become_distinct_result_sets_with_latest_aliases():
    first = _row("sweep-a", "update-1", timestamp="2026-08-17T10:00:00Z", pressure=0.6, volume=9.5)
    second = _row("sweep-b", "update-2", timestamp="2026-08-17T11:00:00Z", pressure=0.6, volume=10.0)

    rows = enrich_characterization_result_sets([first, second])

    assert [row["result_set_no"] for row in rows] == [1, 2]
    assert [row["is_latest_result_set"] for row in rows] == [False, True]
    assert [row["run_no"] for row in rows] == [1, 2]
    assert [row["is_focus_run"] for row in rows] == [False, True]


def test_source_reference_keeps_canonical_and_legacy_identity_but_not_diagnostics():
    row = _row(
        "sweep-a",
        "update-1",
        timestamp="2026-08-17T10:00:00Z",
        pressure=0.6,
        volume=10.0,
        raw_images=["large"],
        measurements=list(range(100)),
    )

    reference = build_characterization_source_reference(row)

    assert reference["result_id"] == "result-sweep-a"
    assert reference["result_sha256"] == "sha-sweep-a"
    assert reference["process_run_id"] == "sweep-a"
    assert reference["update_id"] == "update-1"
    assert reference["phase_key"] == "pressure_sweep_characterization"
    assert reference["pressure_index"] == 0
    assert "raw_images" not in reference
    assert "measurements" not in reference


def test_rechecks_attach_to_exact_candidate_even_when_pressures_match():
    first = _row("sweep-a", "update-1", timestamp="2026-08-17T10:00:00Z", pressure=0.6, volume=9.5)
    second = _row("sweep-b", "update-2", timestamp="2026-08-17T11:00:00Z", pressure=0.6, volume=10.0)
    first_reference = build_characterization_source_reference(first)
    recheck = _row(
        "recheck-a",
        "update-3",
        timestamp="2026-08-17T11:05:00Z",
        pressure=0.6,
        volume=9.6,
        phase="recheck",
        recheck_source=first_reference,
        recheck_root_source=first_reference,
        reference_mean_volume_nL=9.5,
        volume_delta_nL=0.1,
        volume_delta_percent=100.0 * 0.1 / 9.5,
    )

    rows = enrich_characterization_result_sets([first, second, recheck])

    assert [row["process_run_id"] for row in rows] == [
        "sweep-a",
        "recheck-a",
        "sweep-b",
    ]
    parent, child = rows[:2]
    assert child["row_role"] == "recheck"
    assert child["candidate_key"] == parent["candidate_key"]
    assert child["result_set_key"] == parent["result_set_key"]
    assert child["result_set_no"] == 1
    assert child["recheck_no"] == 1


def test_recheck_of_recheck_is_a_sibling_and_rollup_uses_original_candidate():
    parent = _row("sweep-a", "update-1", timestamp="2026-08-17T10:00:00Z", pressure=0.6, volume=10.0)
    parent_reference = build_characterization_source_reference(parent)
    first = _row(
        "recheck-a",
        "update-2",
        timestamp="2026-08-17T10:05:00Z",
        pressure=0.6,
        volume=9.9,
        phase="recheck",
        recheck_source=parent_reference,
        recheck_root_source=parent_reference,
        reference_mean_volume_nL=10.0,
        volume_delta_nL=-0.1,
    )
    first_reference = build_characterization_source_reference(first)
    second = _row(
        "recheck-b",
        "update-3",
        timestamp="2026-08-17T10:10:00Z",
        pressure=0.6,
        volume=10.2,
        phase="recheck",
        recheck_source=first_reference,
        recheck_root_source=parent_reference,
        reference_mean_volume_nL=10.0,
        volume_delta_nL=0.2,
    )

    rows = enrich_characterization_result_sets([second, parent, first])

    assert [row["row_role"] for row in rows] == ["candidate", "recheck", "recheck"]
    assert [row.get("recheck_no") for row in rows] == [None, 1, 2]
    assert len({row["candidate_key"] for row in rows}) == 1
    rollup = characterization_candidate_rollup(rows, rows[0]["candidate_key"])
    assert rollup["mean_volume_nL"] == pytest.approx((10.0 + 9.9 + 10.2) / 3.0)
    assert rollup["range_nL"] == pytest.approx(0.3)
    assert rollup["maximum_absolute_delta_nL"] == pytest.approx(0.2)
    assert rollup["maximum_absolute_delta_percent"] == pytest.approx(2.0)


def test_unresolved_recheck_is_not_attached_by_matching_pressure():
    parent = _row("sweep-a", "update-1", timestamp="2026-08-17T10:00:00Z", pressure=0.6, volume=10.0)
    recheck = _row(
        "recheck-a",
        "update-2",
        timestamp="2026-08-17T10:05:00Z",
        pressure=0.6,
        volume=10.1,
        phase="recheck",
        recheck_source={"process_run_id": "missing", "update_id": "missing"},
    )

    rows = enrich_characterization_result_sets([parent, recheck])

    assert rows[-1]["row_role"] == "unlinked_recheck"
    assert rows[-1]["result_set_no"] is None
    assert rows[-1]["result_set_label"] == "Unlinked rechecks"


def test_four_candidates_from_one_process_share_a_set_and_later_process_advances_latest():
    first_process = [
        _row(
            "sweep-a",
            "update-1",
            timestamp="2026-08-17T10:00:00Z",
            pressure=pressure,
            volume=volume,
            row_ordinal=ordinal,
        )
        for ordinal, (pressure, volume) in enumerate(
            ((0.55, 8.0), (0.60, 9.0), (0.65, 10.0), (0.70, 11.0))
        )
    ]
    later = _row(
        "sweep-b",
        "update-2",
        timestamp="2026-08-17T11:00:00Z",
        pressure=0.62,
        volume=9.8,
    )

    rows = enrich_characterization_result_sets(first_process + [later])

    assert {row["result_set_no"] for row in rows[:4]} == {1}
    assert all(not row["is_latest_result_set"] for row in rows[:4])
    assert rows[-1]["result_set_no"] == 2
    assert rows[-1]["is_latest_result_set"] is True


def test_canonical_candidate_accepts_an_exact_legacy_reference_from_older_recheck():
    candidate = _row(
        "sweep-a",
        "update-1",
        timestamp="2026-08-17T10:00:00Z",
        pressure=0.6,
        volume=10.0,
    )
    reference = {
        "run_id": candidate["source_run_id"],
        "phase_key": candidate["source_phase_key"],
        "step_index": candidate["source_step_index"],
        "pressure_index": candidate["source_pressure_index"],
    }
    recheck = _row(
        "recheck-a",
        "update-2",
        timestamp="2026-08-17T10:05:00Z",
        pressure=0.6,
        volume=10.1,
        phase="recheck",
        recheck_source=reference,
    )

    rows = enrich_characterization_result_sets([candidate, recheck])

    assert [row["row_role"] for row in rows] == ["candidate", "recheck"]
    assert rows[1]["candidate_key"] == rows[0]["candidate_key"]


def test_unlinked_rechecks_share_one_explicit_selector_group():
    unlinked = [
        _row(
            f"recheck-{ordinal}",
            f"update-{ordinal}",
            timestamp=f"2026-08-17T10:0{ordinal}:00Z",
            pressure=0.6,
            volume=10.0 + ordinal / 10,
            phase="recheck",
            recheck_source={"process_run_id": "missing", "update_id": f"missing-{ordinal}"},
        )
        for ordinal in (1, 2)
    ]

    rows = enrich_characterization_result_sets(unlinked)
    options = characterization_result_set_options(rows)

    assert {row["result_set_key"] for row in rows} == {"unlinked"}
    assert options == [
        {
            "result_set_key": "unlinked",
            "result_set_no": None,
            "result_set_label": "Unlinked rechecks",
            "timestamp": "2026-08-17T10:01:00Z",
            "timestamp_display": "2026-08-17T10:01:00Z",
            "phase_label": "Recheck",
            "is_latest_result_set": False,
        }
    ]
