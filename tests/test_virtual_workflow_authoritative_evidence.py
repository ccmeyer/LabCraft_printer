from __future__ import annotations

import json

import pytest

from tools.virtual_workflows.authoritative_evidence import (
    check_evidence,
    clean_authoritative_activation_boundary,
    clean_authoritative_loaded_boundary,
    completed_stock_well_pairs,
    compare_directories,
    experiment_design_projection,
    merge_session_lifecycles,
    read_audit_rows,
    read_csv_rows,
    snapshot_directory,
)
from types import SimpleNamespace


def test_directory_snapshot_is_deterministic_and_read_only(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "b.txt").write_text("bravo", encoding="utf-8")
    (tmp_path / "nested" / "a.txt").write_text("alpha", encoding="utf-8")

    before = snapshot_directory(tmp_path)
    after = snapshot_directory(tmp_path)

    assert before == after
    assert before.paths == ("b.txt", "nested/a.txt")
    assert before.editor_projection() == {
        "inventory": ["b.txt", "nested/a.txt"],
        "sha256": before.hashes,
    }
    assert before.rich_inventory()["b.txt"]["size_bytes"] == 5


def test_directory_comparison_reports_exact_and_allowlisted_changes(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text("before", encoding="utf-8")
    before = snapshot_directory(tmp_path)
    path.write_text("after", encoding="utf-8")
    after = snapshot_directory(tmp_path)

    allowed = compare_directories(
        before, after, allowed_changed_paths=("progress.json",)
    ).to_dict()
    blocked = compare_directories(before, after).to_dict()

    assert allowed["checks"] == {
        "inventory_unchanged": True,
        "files_byte_identical": False,
        "only_allowlisted_files_changed": True,
    }
    assert allowed["changed_paths"] == ["progress.json"]
    assert blocked["failed_checks"] == [
        "files_byte_identical",
        "only_allowlisted_files_changed",
    ]


def _clean_boundary_snapshot(directory, **updates):
    values = {
        "directory": directory,
        "plan_id": "plan-1",
        "plan_revision": 3,
        "plan_state": "active",
        "design_sha256": "design-sha",
        "history_json": ("revision-1", "revision-2", "revision-3"),
        "progress_plan_id": "plan-1",
        "progress_plan_revision": 3,
        "calibration_record_count": 1,
        "eligibility_status": "ready_to_start",
        "runtime_active": False,
        "resume_present": False,
        "resume_state": None,
        "resume_plan_id": None,
        "resume_plan_revision": None,
        "resume_intent_count": 0,
        "total_added_droplets": 0,
        "completed_well_ids": (),
        "audit_rows": [],
        "eligibility": {"status": "ready_to_start"},
    }
    values.update(updates)
    return SimpleNamespace(**values)


def test_clean_authoritative_boundaries_accept_read_only_load_and_allowlisted_activation(
    tmp_path,
):
    (tmp_path / "execution_plan.json").write_text("plan", encoding="utf-8")
    (tmp_path / "experiment_audit.jsonl").write_text("", encoding="utf-8")
    source_directory = snapshot_directory(tmp_path)
    source = _clean_boundary_snapshot(source_directory)
    loaded = _clean_boundary_snapshot(source_directory)

    (tmp_path / "execution_resume.json").write_text("resume", encoding="utf-8")
    (tmp_path / "experiment_audit.jsonl").write_text("activated", encoding="utf-8")
    activated = _clean_boundary_snapshot(
        snapshot_directory(tmp_path),
        runtime_active=True,
        resume_present=True,
        resume_state="clean",
        resume_plan_id="plan-1",
        resume_plan_revision=3,
        audit_rows=[{"event_type": "authoritative_execution_activated"}],
    )

    loaded_evidence = clean_authoritative_loaded_boundary(source, loaded)
    activated_evidence = clean_authoritative_activation_boundary(
        source, loaded, activated
    )

    assert loaded_evidence["failed_checks"] == []
    assert activated_evidence["failed_checks"] == []
    assert set(activated_evidence["changed_paths"]) == {
        "execution_resume.json",
        "experiment_audit.jsonl",
    }


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    (
        ("loaded_runtime", "runtime_inactive"),
        ("duplicate_audit", "one_activation_audit_event"),
        ("stale_resume", "one_clean_resume_checkpoint"),
        ("nonzero_progress", "zero_progress"),
        ("disallowed_write", "only_allowlisted_files_changed"),
    ),
)
def test_clean_authoritative_boundaries_fail_closed(tmp_path, mutation, failed_check):
    (tmp_path / "execution_plan.json").write_text("plan", encoding="utf-8")
    (tmp_path / "experiment_audit.jsonl").write_text("", encoding="utf-8")
    before = snapshot_directory(tmp_path)
    source = _clean_boundary_snapshot(before)
    loaded = _clean_boundary_snapshot(
        before,
        runtime_active=mutation == "loaded_runtime",
    )
    if mutation == "loaded_runtime":
        assert failed_check in clean_authoritative_loaded_boundary(
            source, loaded
        )["failed_checks"]
        return

    (tmp_path / "execution_resume.json").write_text("resume", encoding="utf-8")
    (tmp_path / "experiment_audit.jsonl").write_text("activated", encoding="utf-8")
    if mutation == "disallowed_write":
        (tmp_path / "experiment_design.json").write_text("changed", encoding="utf-8")
    audit_rows = [{"event_type": "authoritative_execution_activated"}]
    if mutation == "duplicate_audit":
        audit_rows *= 2
    activated = _clean_boundary_snapshot(
        snapshot_directory(tmp_path),
        runtime_active=True,
        resume_present=True,
        resume_state="clean",
        resume_plan_id="stale" if mutation == "stale_resume" else "plan-1",
        resume_plan_revision=3,
        total_added_droplets=1 if mutation == "nonzero_progress" else 0,
        audit_rows=audit_rows,
    )

    evidence = clean_authoritative_activation_boundary(source, loaded, activated)

    assert failed_check in evidence["failed_checks"]


def test_experiment_design_projection_preserves_exact_positive_counts(tmp_path):
    (tmp_path / "execution_plan.json").write_text("{}", encoding="utf-8")
    snapshot = SimpleNamespace(
        plan={
            "stocks": {
                "A_10.00_x": {
                    "reagent_name": "A",
                    "concentration": 10,
                    "units": "x",
                    "printing_mode": "droplet",
                }
            },
            "wells": {
                "A1": {
                    "reaction_id": "R1",
                    "reagents": {
                        "A_10.00_x": {"target_dispenses": 2},
                        "unused": {"target_dispenses": 0},
                    },
                }
            },
        },
        assignments={"A1": "R1"},
        key_rows={"A1": {"A_10.00_x_10.0nL": "2"}},
        concentration_rows={"A1": {"A_x": "2.0"}},
        directory=snapshot_directory(tmp_path),
    )

    projection = experiment_design_projection(snapshot)

    assert projection["assignments"] == [
        {"well_id": "A1", "reaction_id": "R1"}
    ]
    assert projection["stock_well_counts"] == [
        {"stock_id": "A_10.00_x", "well_id": "A1", "target_droplets": 2}
    ]
    assert projection["runtime_assignments"] == {"A1": "R1"}


def test_shared_csv_and_audit_readers_fail_closed(tmp_path):
    csv_path = tmp_path / "key.csv"
    csv_path.write_text("Well ID,Stock\nA1,2\n", encoding="utf-8")
    assert read_csv_rows(csv_path) == {"A1": {"Stock": "2"}}

    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text(
        json.dumps({"event_type": "prepared"}) + "\n",
        encoding="utf-8",
    )
    assert read_audit_rows(audit_path) == [{"event_type": "prepared"}]
    assert read_audit_rows(tmp_path / "missing.jsonl") == []

    csv_path.write_text("Stock\n2\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no Well ID rows"):
        read_csv_rows(csv_path)

    audit_path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        read_audit_rows(audit_path)


def test_check_evidence_orders_failures_and_copies_values():
    evidence = check_evidence(
        {"first": True, "second": False},
        plan_id="plan-1",
    )
    assert evidence == {
        "checks": {"first": True, "second": False},
        "failed_checks": ["second"],
        "plan_id": "plan-1",
    }


def test_merge_session_lifecycles_combines_events_and_bounded_metadata():
    first_begin = {
        "intent_id": "intent-1",
        "stock_id": "stock-1",
        "well_id": "A1",
    }
    second_begin = {
        "intent_id": "intent-2",
        "stock_id": "stock-1",
        "well_id": "A2",
    }

    merged = merge_session_lifecycles(
        (
            (
                "session-1",
                {
                    "begins": [first_begin],
                    "completions": ["intent-1"],
                    "simulator_dispense_limit": 10_000,
                    "simulator_dispense_overflow_count": 1,
                },
            ),
            (
                "session-2",
                {
                    "begins": [second_begin],
                    "completions": ["intent-2"],
                    "simulator_dispense_limit": 10_000,
                    "simulator_dispense_overflow_count": 2,
                },
            ),
        )
    )

    assert merged["begins"] == [
        {**first_begin, "application_session_id": "session-1"},
        {**second_begin, "application_session_id": "session-2"},
    ]
    assert merged["completions"] == ["intent-1", "intent-2"]
    assert merged["simulator_dispense_limit"] == 20_000
    assert merged["simulator_dispense_overflow_count"] == 3
    assert "application_session_id" not in first_begin
    assert completed_stock_well_pairs(merged) == {
        ("stock-1", "A1"),
        ("stock-1", "A2"),
    }


def test_merge_session_lifecycles_accepts_legacy_event_only_snapshots():
    assert merge_session_lifecycles(
        (
            ("session-1", {"completions": ["intent-1"]}),
            ("session-2", {"completions": ("intent-2",)}),
        )
    ) == {"completions": ["intent-1", "intent-2"]}


@pytest.mark.parametrize(
    ("sessions", "error", "message"),
    (
        (
            (
                ("session-1", {
                    "simulator_dispense_limit": 10_000,
                    "simulator_dispense_overflow_count": 0,
                }),
                ("session-2", {"begins": []}),
            ),
            ValueError,
            "missing bounded metadata",
        ),
        (
            (("session-1", {
                "simulator_dispense_limit": True,
                "simulator_dispense_overflow_count": 0,
            }),),
            TypeError,
            "must be an integer",
        ),
        (
            (("session-1", {
                "simulator_dispense_limit": 0,
                "simulator_dispense_overflow_count": 0,
            }),),
            ValueError,
            "must be at least 1",
        ),
        (
            (("session-1", {
                "simulator_dispense_limit": 10_000,
                "simulator_dispense_overflow_count": -1,
            }),),
            ValueError,
            "must be at least 0",
        ),
        (
            (("session-1", {"unknown_scalar": 1}),),
            TypeError,
            "must be a list or tuple",
        ),
    ),
)
def test_merge_session_lifecycles_rejects_malformed_metadata(
    sessions, error, message
):
    with pytest.raises(error, match=message):
        merge_session_lifecycles(sessions)
