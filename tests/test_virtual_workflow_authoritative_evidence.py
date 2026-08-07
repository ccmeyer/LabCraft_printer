from __future__ import annotations

import json

import pytest

from tools.virtual_workflows.authoritative_evidence import (
    check_evidence,
    compare_directories,
    read_audit_rows,
    read_csv_rows,
    snapshot_directory,
)


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
