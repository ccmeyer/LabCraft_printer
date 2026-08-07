from __future__ import annotations

from types import SimpleNamespace

from tools.virtual_workflows.editor_reporting import (
    EditorLifecycleReportSpec,
    build_editor_lifecycle_payload,
    create_finalize_report_spec,
    prepared_revision_report_spec,
)


def _runtime(*, decisions=("pass", "pass")):
    assertion_ids = ("required.one", "required.two")
    rows = [
        {
            "assertion_id": assertion_id,
            "decision": decision,
            "evidence": {"assertion_id": assertion_id},
        }
        for assertion_id, decision in zip(assertion_ids, decisions)
    ]
    fixture = {
        "experiment": {
            "name": "created",
            "initial_name": "initial",
            "renamed_name": "renamed",
            "plate_name": "plate",
            "replicates": 2,
            "expected_well_ids": ["A1", "A2"],
            "refinalized_replicates": 3,
            "refinalized_expected_well_ids": ["A1", "A2", "A3"],
        },
        "workload": {
            "expected_editor_finalization_operations": 2,
            "expected_rename_operations": 1,
        },
    }
    return SimpleNamespace(
        fixture=fixture,
        harness=SimpleNamespace(
            assertion_results=rows,
            config=SimpleNamespace(speed_multiplier=1.0, timeout_seconds=60.0),
        ),
        observations={
            "prepared_revision_initial": {
                "before": {"plan_id": "old"},
                "prepared_bundle": {"plan_state": "prepared"},
            },
            "refinalized_bundle": {
                "experiment_dir": "renamed",
                "renamed_name": "renamed",
                "plan_id": "new",
                "plan_revision": 1,
                "file_sha256": {},
                "audit_rows": [],
            },
            "reload_activation": {"activation_performed": False},
        },
    ), assertion_ids


def test_common_editor_payload_sets_status_cleanup_and_zero_print_queue():
    runtime, assertion_ids = _runtime()
    spec = EditorLifecycleReportSpec(
        workload={"workload_id": "editor"},
        required_assertion_ids=assertion_ids,
        persistence_values={"bundle": {"valid": True}},
        limitations=("bounded",),
    )
    payload = build_editor_lifecycle_payload(
        runtime, {"status": "pass"}, spec
    )

    assert payload.workflow_status == "measured"
    assert payload.workflow_values == {
        "cleanup_results": [{"status": "pass"}]
    }
    assert payload.queue["values"] == {"print_commands_executed": 0}
    assert payload.persistence["values"]["assertion_decisions"] == {
        "required.one": "pass",
        "required.two": "pass",
    }


def test_common_editor_payload_is_partial_when_required_assertion_fails():
    runtime, assertion_ids = _runtime(decisions=("pass", "fail"))
    payload = build_editor_lifecycle_payload(
        runtime,
        {},
        EditorLifecycleReportSpec(
            workload={"workload_id": "editor"},
            required_assertion_ids=assertion_ids,
            persistence_values={},
            limitations=(),
        ),
    )
    assert payload.workflow_status == "partial"
    assert payload.persistence["status"] == "partial"


def test_editor_report_specs_preserve_lifecycle_specific_values():
    runtime, assertion_ids = _runtime()
    base = {"workload_id": "editor", "fixture_sha256": "abc"}

    created = create_finalize_report_spec(
        runtime,
        base_workload=base,
        required_assertion_ids=assertion_ids,
    )
    revised = prepared_revision_report_spec(
        runtime,
        base_workload=base,
        required_assertion_ids=assertion_ids,
    )

    assert created.workload["experiment_name"] == "created"
    assert created.workload["well_ids"] == ["A1", "A2"]
    assert revised.workload["renamed_experiment_name"] == "renamed"
    assert revised.persistence_values["rename_refinalization"] == {
        "before": {"plan_id": "old"},
        "after": {
            "experiment_dir": "renamed",
            "renamed_name": "renamed",
            "plan_id": "new",
            "plan_revision": 1,
            "file_sha256": {},
            "audit_rows": [],
        },
    }
