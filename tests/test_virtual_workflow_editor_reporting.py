from __future__ import annotations

from types import SimpleNamespace

from tools.virtual_workflows.editor_reporting import (
    EditorLifecycleReportSpec,
    build_editor_lifecycle_payload,
    create_finalize_report_spec,
    experiment_design_report_spec,
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


def test_experiment_design_report_spec_adds_case_and_exact_evidence():
    case = {
        "case_id": "control",
        "experiment": {"name": "designed", "plate_name": "plate"},
        "expected": {
            "terminal": "prepared",
            "reaction_count": 1,
            "assignments": [{"well_id": "A1", "reaction_id": "R1"}],
        },
    }
    runtime = SimpleNamespace(
        fixture={
            "lifecycle": {
                "matrix_id": "design-matrix",
                "catalog_sha256": "catalog",
                "case_sha256": "case",
                "case": case,
            },
            "workload": {"expected_editor_finalization_operations": 1},
        },
        harness=SimpleNamespace(
            assertion_results=[
                {
                    "assertion_id": "experiment.design_case_oracle_exact",
                    "decision": "pass",
                    "evidence": {
                        "checks": {"exact": True},
                        "driver": {"configured": {"seed": 1}},
                    },
                },
                {
                    "assertion_id": (
                        "experiment.prepared_runtime_reconstructed_exact"
                    ),
                    "decision": "pass",
                    "evidence": {"checks": {"reloaded": True}},
                },
            ],
            config=SimpleNamespace(speed_multiplier=1000.0, timeout_seconds=90.0),
        ),
    )

    spec = experiment_design_report_spec(
        runtime,
        base_workload={"workload_id": "design-matrix"},
        required_assertion_ids=(
            "experiment.design_case_oracle_exact",
            "experiment.prepared_runtime_reconstructed_exact",
        ),
    )

    assert spec.persistence_values["matrix_case"]["case"] == case
    assert spec.persistence_values["matrix_case"]["parameters"] == {
        "configured": {"seed": 1},
        "generated": {},
    }
    assert spec.persistence_values["experiment_design_evidence"][
        "reload_activation"
    ]["checks"] == {"reloaded": True}


def test_experiment_design_report_spec_projects_rejected_terminal_evidence():
    case = {
        "case_id": "rejected",
        "experiment": {
            "name": "rejected-design",
            "plate_name": "plate",
            "selected_well_ids": ["A1"],
        },
        "expected": {
            "terminal": "formulation_rejected",
            "reaction_count": 1,
            "assignments": [],
        },
    }
    runtime = SimpleNamespace(
        fixture={
            "lifecycle": {
                "matrix_id": "design-matrix",
                "catalog_sha256": "catalog",
                "case_sha256": "case",
                "case": case,
            },
            "workload": {"expected_editor_finalization_operations": 0},
        },
        observations={
            "experiment_design_driver": {
                "configured": {"selected_well_ids": ["A1"]},
                "generated": {},
            }
        },
        harness=SimpleNamespace(
            assertion_results=[
                {
                    "assertion_id": (
                        "experiment.finalization_rejected_no_mutation"
                    ),
                    "decision": "pass",
                    "evidence": {"checks": {"no_mutation": True}},
                }
            ],
            config=SimpleNamespace(
                speed_multiplier=1000.0,
                timeout_seconds=90.0,
            ),
        ),
    )

    spec = experiment_design_report_spec(
        runtime,
        base_workload={"workload_id": "design-matrix"},
        required_assertion_ids=(
            "experiment.finalization_rejected_no_mutation",
        ),
    )

    assert spec.workload["well_ids"] == ["A1"]
    assert spec.persistence_values["matrix_case"]["outcome"] == {
        "terminal": "formulation_rejected",
        "oracle_checks": {"no_mutation": True},
        "runtime_checks": {},
    }
    assert spec.persistence_values["experiment_design_evidence"][
        "finalization_rejection"
    ]["checks"] == {"no_mutation": True}
