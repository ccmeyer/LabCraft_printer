from __future__ import annotations

import copy

from tools.virtual_workflows.assertions import (
    ActionSequenceExpectation,
    AssertionResult,
    ExecutionLifecycleExpectation,
    SoftStopResumeExpectation,
    cleanup_assertion,
    completed_terminal_reload_assertion,
    dispense_counts_reconciled_assertion,
    editor_artifacts_cleanup_assertion,
    editor_create_finalize_assertion,
    editor_create_rejected_assertion,
    editor_prepared_revision_failure_assertion,
    editor_sequence_exploration_assertions,
    exact_action_sequence_assertion,
    evaluate_assertion,
    experiment_finalization_rejected_no_mutation_assertion,
    multi_stock_artifacts_assertion,
    mixed_mode_lifecycle_assertions,
    regression_evidence_assertions,
    soft_stop_paused_assertions,
    synthetic_calibration_contract,
)

import pytest
from types import SimpleNamespace

from tools.virtual_workflows.exploration import (
    CAMPAIGN_ID,
    build_sequence_fixture,
)


def test_assertion_result_rejects_ambiguous_decision():
    try:
        AssertionResult("a", "b", "unknown", (), {})
    except ValueError as exc:
        assert "pass, fail, or incomplete" in str(exc)
    else:
        raise AssertionError("ambiguous assertion decision was accepted")


def test_completed_terminal_reload_requires_exact_read_only_fresh_session():
    snapshot = SimpleNamespace(
        plan_id="plan-1",
        plan_revision=5,
        plan_state="completed",
        eligibility_status="analysis_only",
        design_json="{}",
        design_sha256="design",
        plan_design_sha256="design",
        plan_json="{\"state\":\"completed\"}",
        plan_well_ids=("A2", "A1"),
        plan_assignments=(
            ("A2", "reaction-2"),
            ("A1", "reaction-1"),
        ),
        runtime_assignments=(
            ("A1", "reaction-1"),
            ("A2", "reaction-2"),
        ),
        history_json=("revision",),
        progress_plan_id="plan-1",
        progress_plan_revision=5,
        progress_targets=(("A1", 15),),
        total_added_droplets=15,
        completed_well_ids=("A1",),
        resume_present=True,
        resume_state="completed",
        resume_plan_id="plan-1",
        resume_plan_revision=5,
        resume_intent_count=0,
        calibration_present=True,
        calibration_record_count=2,
        manual_refuel_check_count=0,
        runtime_active=False,
        core_file_hashes={"execution_plan.json": "hash"},
    )
    comparison = {
        "checks": {"files_byte_identical": True},
        "failed_checks": [],
    }
    values = {
        "before": snapshot,
        "after": snapshot,
        "first_close": {
            "application_session_id": "app-1",
            "session_id": "session-1",
            "close_succeeded": True,
            "recorder": {"status": "closed"},
            "session_lock_present": False,
            "root_retained": True,
        },
        "second_launch": {
            "application_session_id": "app-2",
            "session_id": "session-1",
            "component_type": "ApplicationComponents",
            "view_type": "MainWindow",
            "machine_type": "SimulatedMachine",
            "hardware_access_allowed": False,
        },
        "loader": {
            "checks": {"completed": True},
            "activation_performed": False,
            "display_projection_performed": True,
            "runtime_assignments": {
                "A1": "reaction-1",
                "A2": "reaction-2",
            },
            "runtime_assignment_count": 2,
            "expected_assignment_count": 2,
            "runtime_assignments_sha256": "assignment-hash",
            "expected_assignments_sha256": "assignment-hash",
        },
        "directory_comparisons": {
            "after_close": comparison,
            "after_reload": comparison,
        },
    }

    passed = completed_terminal_reload_assertion(**values)
    failed = completed_terminal_reload_assertion(
        **{**values, "after": SimpleNamespace(**{
            **vars(snapshot), "plan_revision": 6,
        })}
    )

    assert passed.decision == "pass", passed.evidence
    assert failed.decision == "fail"
    assert "plan_identity_exact" in failed.evidence["failed_checks"]


def test_dispense_count_assertion_reconciles_every_required_layer(monkeypatch):
    count = {"stock_id": "stock-a", "well_id": "A1", "droplets": 3}

    def snapshot(revision, state, added):
        return {
            "plan_id": "plan-1",
            "plan_revision": revision,
            "plan_state": state,
            "plan_targets": [count],
            "progress_targets": [count],
            "progress_added": [{**count, "droplets": added}],
            "runtime_targets": [count],
            "runtime_captured": True,
        }

    preview = {
        "visible_table": {
            "headers": [
                "Target", "Achievable", "Error (%)", "Drops", "Δ/drop",
                "Printed nL (new)", "Δ printed nL",
            ],
            "rows": [["1", "1", "0.00%", "3", "1", "3 nL", "+0 nL"]],
            "row_count": 1,
            "column_count": 7,
        }
    }
    transition = {
        "stock_id": "stock-a",
        "preview": preview,
        "before": snapshot(1, "prepared", 0),
        "after": snapshot(2, "active", 0),
    }
    lifecycle = {
        "begins": [{
            "intent_id": "intent-1", "stock_id": "stock-a", "well_id": "A1",
            "commanded_droplets": 3,
        }],
        "attachments": [{"intent_id": "intent-1", "command_seq32": 7}],
        "simulator_dispenses": [{
            "command_seq32": 7, "command_type": "DISPENSE",
            "commanded_droplets": 3, "manual": False, "status": "Completed",
        }],
        "simulator_dispense_limit": 10_000,
        "simulator_dispense_overflow_count": 0,
    }
    from tools.virtual_workflows import assertions

    monkeypatch.setattr(
        assertions,
        "capture_count_snapshot",
        lambda _context, include_runtime=False: snapshot(3, "completed", 3),
    )
    result = dispense_counts_reconciled_assertion(
        SimpleNamespace(),
        prepared_snapshot=snapshot(1, "prepared", 0),
        calibration_transitions=[transition],
        observer={"restored": True, "lifecycle": lifecycle},
    )

    assert result.decision == "pass", result.evidence
    assert all(result.evidence["checks"].values())
    assert all(result.evidence["reconciliation"]["checks"].values())

    transition["after"]["progress_added"][0]["droplets"] = 1
    rejected = dispense_counts_reconciled_assertion(
        SimpleNamespace(),
        prepared_snapshot=snapshot(1, "prepared", 0),
        calibration_transitions=[transition],
        observer={"restored": True, "lifecycle": lifecycle},
    )
    assert rejected.decision == "fail"
    assert rejected.evidence["checks"]["calibration_progress_zero"] is False


def test_dispense_count_assertion_uses_catalog_owned_requantization_oracle(
    monkeypatch,
):
    wells = [f"A{index}" for index in range(1, 25)]
    stock_id = "Virtual Requantization Stock_10.00_mM"

    def rows(count):
        return [
            {"stock_id": stock_id, "well_id": well_id, "droplets": count}
            for well_id in wells
        ]

    def snapshot(revision, state, count, added):
        return {
            "plan_id": "plan-r",
            "plan_revision": revision,
            "plan_state": state,
            "plan_targets": rows(count),
            "progress_targets": rows(count),
            "progress_added": rows(added),
            "runtime_targets": rows(count),
            "runtime_captured": True,
        }

    preview = {
        "visible_table": {
            "headers": [
                "Target", "Achievable", "Error (%)", "Drops", "\u0394/drop",
                "Printed nL (new)", "\u0394 printed nL",
            ],
            "rows": [["10", "10", "0.00%", "9", "1", "81 nL", "+1 nL"]],
            "row_count": 1,
            "column_count": 7,
        }
    }
    transition = {
        "stock_id": stock_id,
        "preview": preview,
        "before": snapshot(1, "prepared", 10, 0),
        "after": snapshot(2, "active", 9, 0),
    }
    begins = [
        {
            "intent_id": f"intent-{index}",
            "stock_id": stock_id,
            "well_id": well_id,
            "commanded_droplets": 9,
        }
        for index, well_id in enumerate(wells, 1)
    ]
    lifecycle = {
        "begins": begins,
        "attachments": [
            {"intent_id": row["intent_id"], "command_seq32": index}
            for index, row in enumerate(begins, 1)
        ],
        "simulator_dispenses": [
            {
                "command_seq32": index,
                "command_type": "DISPENSE",
                "commanded_droplets": 9,
                "manual": False,
                "status": "Completed",
            }
            for index in range(1, 25)
        ],
        "simulator_dispense_limit": 10_000,
        "simulator_dispense_overflow_count": 0,
    }
    oracle = {
        "schema_version": 1,
        "source": "calibration_requantization_v1_catalog",
        "stock_id": stock_id,
        "well_ids": wells,
        "prepared_droplets_per_well": 10,
        "requantized_droplets_per_well": 9,
        "expected_count_delta": -1,
        "transition": "volume_increase",
        "rounding_boundary_margin": {"numerator": 7, "denominator": 18},
    }
    from tools.virtual_workflows import assertions

    monkeypatch.setattr(
        assertions,
        "capture_count_snapshot",
        lambda _context, include_runtime=False: snapshot(3, "completed", 9, 9),
    )
    result = dispense_counts_reconciled_assertion(
        SimpleNamespace(),
        prepared_snapshot=snapshot(1, "prepared", 10, 0),
        calibration_transitions=[transition],
        observer={"restored": True, "lifecycle": lifecycle},
        count_oracle=oracle,
    )

    assert result.decision == "pass", result.evidence
    assert result.evidence["oracle_scope"] == (
        "calibration_requantization_v1_catalog_oracle"
    )
    assert result.evidence["count_oracle"]["count_delta"] == -1
    reconciliation = result.evidence["reconciliation"]
    assert {row["droplets"] for row in reconciliation["expected"]["prepared_plan"]} == {10}
    assert {row["droplets"] for row in reconciliation["expected"]["simulator"]} == {9}

    invalid = dict(oracle)
    invalid["expected_count_delta"] = 0
    rejected = dispense_counts_reconciled_assertion(
        SimpleNamespace(),
        prepared_snapshot=snapshot(1, "prepared", 10, 0),
        calibration_transitions=[transition],
        observer={"restored": True, "lifecycle": lifecycle},
        count_oracle=invalid,
    )
    assert rejected.decision == "fail"
    assert "delta drifted" in rejected.evidence["error"]


def test_editor_exploration_assertions_project_safe_recovery():
    fixture, _ = build_sequence_fixture(CAMPAIGN_ID, "seed_1_illegal")
    exploration = fixture["exploration"]
    steps = exploration["sequence"]["steps"]
    context = SimpleNamespace(
        action_results=[
            {
                "action_id": step["action_id"],
                "status": "pass",
                "interaction_surface": "ui",
            }
            for step in steps
        ],
        experiment_model=SimpleNamespace(
            is_authoritative_execution_runtime_active=lambda: False
        ),
        controller=SimpleNamespace(get_array_run_state=lambda: "idle"),
        machine=SimpleNamespace(check_if_all_completed=lambda: True),
        unexpected_dialogs=[],
        errors=[],
    )
    unchanged = {"plan_revision": 1, "runtime_active": False}
    modal = {
        "visible": True,
        "result": 0,
        "apply_requested": False,
        "finish_enabled": True,
    }
    driver = {
        "observed_transitions": [
            {
                **{key: step[key] for key in (
                    "ordinal", "action_id", "from_state", "to_state",
                    "expected_outcome", "edit_variant",
                )},
                "observed_outcome": step["expected_outcome"],
            }
            for step in steps[:-1]
        ],
        "rejections": [{
            "safe": True,
            "activation_count": 1,
            "warning": {
                "entered": True,
                "title": "Invalid volumes",
                "type": "QMessageBox",
                "dismissed": True,
            },
            "authoritative_state_unchanged": True,
            "before": unchanged,
            "after": unchanged,
            "dialog_before": modal,
            "dialog_after": modal,
        }],
    }
    results = editor_sequence_exploration_assertions(
        context,
        exploration=exploration,
        driver_evidence=driver,
        refinalized_evidence={"checks": {"plan_prepared": True}},
        loader_evidence={
            "plan_state": "prepared",
            "eligibility_status": "ready_to_start",
            "activation_performed": False,
        },
        action_start=0,
    )

    assert [result.assertion_id for result in results] == [
        "exploration.sequence_plan_applied",
        "exploration.expected_rejection_safe",
        "exploration.recovery_terminal_valid",
    ]
    assert {result.decision for result in results} == {"pass"}


def test_execution_lifecycle_expectation_rejects_ambiguous_identity_sets():
    with pytest.raises(ValueError, match="well IDs must be unique"):
        ExecutionLifecycleExpectation({}, ("A1", "A1"), ("stock-1",))
    with pytest.raises(ValueError, match="stock IDs must be unique"):
        ExecutionLifecycleExpectation({}, ("A1",), ("stock-1", "stock-1"))


def test_soft_stop_paused_assertions_project_one_shared_oracle(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from tools.virtual_workflows import scenarios

    checks = {
        "request_trigger_exact": True,
        "completion_catchup_bounded": True,
        "plan_remains_active": True,
    }
    monkeypatch.setattr(
        scenarios,
        "_validate_soft_stop_paused_scenario",
        lambda **_values: {"checks": checks, "checkpoint_state": "paused"},
    )
    context = SimpleNamespace(
        experiment_model=object(),
        controller=object(),
        machine=object(),
        errors=[],
        unexpected_dialogs=[],
    )
    results = soft_stop_paused_assertions(
        context,
        expectation=SoftStopResumeExpectation(
            tmp_path, "plan", ("A1",), ("stock",), 1
        ),
        request_evidence={"trigger_count": 1},
        completed_count=2,
        intent_lifecycle={},
        quiescence={
            "starting_completion_count": 2,
            "ending_completion_count": 2,
            "starting_progress_count": 2,
            "ending_progress_count": 2,
            "simulator_queue_empty": True,
        },
    )

    assert [result.assertion_id for result in results] == [
        "execution.soft_stop_requested",
        "execution.soft_stop_boundary_valid",
        "execution.stopped_boundary_quiescent",
    ]
    assert {result.decision for result in results} == {"pass"}


def test_exact_action_sequence_uses_only_the_explicit_ledger_window():
    context = type(
        "Context",
        (),
        {
            "action_results": [
                {"action_id": "outside", "interaction_surface": "model", "status": "pass"},
                {"action_id": "first", "interaction_surface": "ui", "status": "pass"},
                {"action_id": "second", "interaction_surface": "ui", "status": "pass"},
                {"action_id": "outside", "interaction_surface": "model", "status": "pass"},
            ]
        },
    )()
    expectation = ActionSequenceExpectation(
        ("first", "second"), ("ui", "ui")
    )

    passed = exact_action_sequence_assertion(
        context,
        expectation=expectation,
        start_index=1,
        end_index=3,
        assertion_id="actions.exact",
        checkpoint="phase",
    )
    failed = exact_action_sequence_assertion(
        context,
        expectation=expectation,
        start_index=0,
        end_index=3,
        assertion_id="actions.exact",
        checkpoint="phase",
    )

    assert passed.decision == "pass"
    assert failed.decision == "fail"
    assert failed.evidence["observed_action_ids"] == [
        "outside",
        "first",
        "second",
    ]


def test_editor_create_finalize_sequence_adds_only_explicit_regeneration():
    action_ids = (
        "editor.open_via_ui",
        "artifact.capture_milestone",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        "editor.optimize_generate_via_ui",
        "editor.regenerate_prepared_design_via_ui",
        "artifact.capture_milestone",
        "editor.finish_via_ui",
    )
    context = SimpleNamespace(
        action_results=[
            {
                "action_id": action_id,
                "interaction_surface": (
                    "harness"
                    if action_id == "artifact.capture_milestone"
                    else "ui"
                ),
                "status": "pass",
            }
            for action_id in action_ids
        ]
    )

    legacy = editor_create_finalize_assertion(context)
    transitioned = editor_create_finalize_assertion(
        context,
        optimization_action_ids=(
            "editor.optimize_generate_via_ui",
            "editor.regenerate_prepared_design_via_ui",
        ),
    )
    picker_action_ids = (
        *action_ids[:3],
        "artifact.capture_milestone",
        *action_ids[3:],
    )
    picker_context = SimpleNamespace(
        action_results=[
            {
                "action_id": action_id,
                "interaction_surface": (
                    "harness"
                    if action_id == "artifact.capture_milestone"
                    else "ui"
                ),
                "status": "pass",
            }
            for action_id in picker_action_ids
        ]
    )
    picker = editor_create_finalize_assertion(
        picker_context,
        optimization_action_ids=(
            "editor.optimize_generate_via_ui",
            "editor.regenerate_prepared_design_via_ui",
        ),
        pre_configure_action_ids=("artifact.capture_milestone",),
    )

    assert legacy.decision == "fail"
    assert transitioned.decision == "pass"
    assert picker.decision == "pass"
    assert transitioned.evidence["observed_action_ids"] == [
        action_id
        for action_id in action_ids
        if action_id != "artifact.capture_milestone"
    ]


@pytest.mark.parametrize("generated_before_finalize", (False, True))
def test_editor_create_rejected_sequence_is_terminal_specific(
    generated_before_finalize,
):
    action_ids = [
        "editor.open_via_ui",
        "artifact.capture_milestone",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
    ]
    if generated_before_finalize:
        action_ids.extend(
            (
                "editor.optimize_generate_via_ui",
                "artifact.capture_milestone",
            )
        )
    action_ids.extend(
        ("artifact.capture_milestone", "editor.finish_via_ui")
    )
    context = SimpleNamespace(
        action_results=[
            {
                "action_id": action_id,
                "interaction_surface": (
                    "harness"
                    if action_id == "artifact.capture_milestone"
                    else "ui"
                ),
                "status": "pass",
            }
            for action_id in action_ids
        ]
    )

    result = editor_create_rejected_assertion(
        context,
        generated_before_finalize=generated_before_finalize,
    )

    assert result.decision == "pass"


def _rejected_finalization_fixture():
    artifact_names = (
        "execution_plan.json",
        "execution_plan_revisions",
        "progress.json",
        "key.csv",
        "concentration_key.csv",
        "execution_resume.json",
    )
    artifacts = {
        name: {"path": f"draft/{name}", "exists": False}
        for name in artifact_names
    }
    boundary = {
        "experiment_dir": "draft",
        "directory_inventory": {
            "experiment_design.json": {"sha256": "draft", "size_bytes": 1}
        },
        "execution_artifacts": artifacts,
        "runtime_active": False,
        "runtime_assignments": {},
        "array_state": "idle",
        "intent_begin_count": 0,
        "intent_attachment_count": 0,
        "intent_completion_count": 0,
        "simulator_dispense_count": 0,
        "simulator_command_event_count": 0,
    }
    boundary["execution_artifacts"]["progress.json"] = {
        "path": "Experiments/capacity/progress.json",
        "exists": True,
        "sha256": "draft-progress",
        "size_bytes": 32,
    }
    case = {
        "case_id": "capacity",
        "experiment": {
            "selected_well_ids": ["B1", "B2", "B3", "B4"],
            "excluded_well_ids": [],
            "random_seed": None,
        },
        "reagents": [{"stock_label": "Capacity A"}],
        "expected": {
            "terminal": "capacity_rejected",
            "reaction_count": 5,
            "dialog_title": "Insufficient Well Capacity",
            "message_fragments": ["Required reactions: 5", "Available wells", "4"],
            "capacity_required": 5,
            "capacity_available": 4,
        },
    }
    driver = {
        "terminal": "capacity_rejected",
        "configured": {
            "declared_well_ids": ["B1", "B2", "B3", "B4"],
            "selected_well_ids": ["B1", "B2", "B3", "B4"],
            "excluded_well_ids": [],
            "random_seed": None,
            "reagent_count": 1,
        },
        "generated": {"reaction_count": 5},
        "finalization_rejection": {
            "expected_terminal": "capacity_rejected",
            "observed_outcome": "rejected",
            "reaction_count_after": 5,
            "activation_count": 1,
            "action_label": "Finalize Design",
            "warning": {
                "entered": True,
                "title": "Insufficient Well Capacity",
                "text": "Required reactions: 5 Available wells: 4",
                "dismissed": True,
                "screenshot_captured": True,
            },
            "status": "",
            "dialog_before": {
                "visible": True,
                "result": 0,
                "apply_requested": False,
                "dirty": False,
            },
            "dialog_after": {
                "visible": True,
                "result": 0,
                "apply_requested": False,
                "dirty": False,
            },
            "before": copy.deepcopy(boundary),
            "after": copy.deepcopy(boundary),
            "directory_unchanged": True,
            "required_execution_artifacts_absent": True,
            "draft_progress_unchanged": True,
            "authoritative_execution_artifacts_unchanged": True,
            "safe": True,
        },
    }
    return case, driver


@pytest.mark.parametrize(
    "mutation",
    (
        "directory",
        "artifact",
        "warning",
        "dispatch",
        "accepted",
    ),
)
def test_rejected_finalization_assertion_fails_closed_on_evidence_drift(
    mutation,
):
    case, driver = _rejected_finalization_fixture()
    passing = experiment_finalization_rejected_no_mutation_assertion(
        SimpleNamespace(), case=case, driver_evidence=driver
    )
    assert passing.decision == "pass"

    changed = copy.deepcopy(driver)
    rejection = changed["finalization_rejection"]
    if mutation == "directory":
        rejection["after"]["directory_inventory"]["new.json"] = {
            "sha256": "new",
            "size_bytes": 1,
        }
    elif mutation == "artifact":
        rejection["after"]["execution_artifacts"]["progress.json"][
            "sha256"
        ] = "mutated-draft-progress"
    elif mutation == "warning":
        rejection["warning"]["title"] = "Wrong"
    elif mutation == "dispatch":
        rejection["after"]["intent_begin_count"] = 1
    else:
        rejection["dialog_after"]["result"] = 1

    result = experiment_finalization_rejected_no_mutation_assertion(
        SimpleNamespace(), case=case, driver_evidence=changed
    )
    assert result.decision == "fail"


def test_evaluate_assertion_records_pass_fail_and_incomplete():
    passed = evaluate_assertion("pass", "ready", ("ui",), lambda: (True, {"x": 1}))
    failed = evaluate_assertion("fail", "ready", ("model",), lambda: (False, {"x": 0}))

    def unavailable():
        raise LookupError("missing evidence")

    incomplete = evaluate_assertion("incomplete", "ready", (), unavailable)

    assert passed.decision == "pass"
    assert failed.decision == "fail"
    assert failed.message
    assert incomplete.decision == "incomplete"
    assert incomplete.evidence == {"exception_type": "LookupError"}


def test_cleanup_assertion_requires_close_and_removed_lock():
    assert cleanup_assertion(
        {"evidence": {"close_succeeded": True, "session_lock_present": False}}
    ).decision == "pass"
    assert cleanup_assertion(
        {"evidence": {"close_succeeded": True, "session_lock_present": True}}
    ).decision == "fail"


def test_regression_assertions_fail_closed_on_missing_responsiveness_metric():
    intent = {"intent_id": "intent-1"}
    snapshot = {
        "observer": {
            "restored": True,
            "lifecycle": {
                "begins": [intent],
                "attachments": [intent],
                "completions": ["intent-1"],
                "discard_batches": [],
            },
            "progress_snapshot": {
                "mode_counts": {"full_rebuild": 0, "cached_update": 1}
            },
        },
        "authoritative_io": {
            "resume_save_fsync_count": 3,
            "resume_save_replace_count": 3,
        },
        "queue": {"unexpected_starvation_count": 0},
        "calibration_contract": {"valid": True},
        "injected_stall_assessment": {"decision": "not_requested"},
        "responsiveness": {
            "scheduling_lateness_ms": {"count": 1},
            "event_loop_gap_ms": {"count": 1},
            "phase_timings": {
                "duration_by_name_ms": {
                    "persistence.write_progress": {"count": 1},
                    "persistence.complete_intent": {"count": 1},
                    "controller.well_completion": {"count": 1},
                }
            },
            "shutdown": {
                "timer_active": False,
                "observer_thread_alive": False,
            },
        },
    }

    passing = regression_evidence_assertions(
        expected_well_ids=("A1",),
        completed_well_ids=("A1",),
        snapshot=snapshot,
    )
    assert {result.decision for result in passing} == {"pass"}

    snapshot["responsiveness"]["event_loop_gap_ms"] = {"count": 0}
    failed = regression_evidence_assertions(
        expected_well_ids=("A1",),
        completed_well_ids=("A1",),
        snapshot=snapshot,
    )
    decision = {result.assertion_id: result.decision for result in failed}
    assert decision["ui.responsiveness_metrics_present"] == "fail"


def test_synthetic_calibration_contract_uses_the_pulse_aware_result():
    fixture = {
        "stock": {
            "printing_mode": "droplet",
            "prepared_droplet_volume_nL": 5.0,
            "droplet_volume_nL": 10.0,
        },
        "printer_head": {
            "print_pulse_width_us": 1300,
            "print_pressure_psi": 1.2,
        },
    }
    actions = [
        {
            "action_id": "calibration.select_via_ui",
            "evidence": {
                "source_volume_nL": 5.0,
                "mean_nL": 9.0,
                "pw_us": 1300,
                "pressure_psi": 1.2005,
            },
        },
        {
            "action_id": "calibration.apply_via_ui",
            "evidence": {
                "preview": {"payload": {"new_droplet_nL": 9.0}}
            },
        },
    ]

    evidence = synthetic_calibration_contract(fixture, actions)
    assert evidence["valid"] is True
    assert evidence["prepared_volume_nL"] == 5.0
    assert evidence["fixture_design_volume_nL"] == 10.0
    assert evidence["expected_synthetic_measured_volume_nL"] == 9.0


def test_editor_artifact_assertion_requires_exact_nonempty_screenshots_and_cleanup(
    tmp_path,
):
    screenshot = tmp_path / "finalized.png"
    screenshot.write_bytes(b"png")
    teardown = {
        "evidence": {"close_succeeded": True, "session_lock_present": False}
    }

    assert editor_artifacts_cleanup_assertion(
        screenshots={"finalized": screenshot},
        required_screenshots={"finalized"},
        teardown=teardown,
    ).decision == "pass"
    assert editor_artifacts_cleanup_assertion(
        screenshots={"finalized": screenshot},
        required_screenshots={"finalized", "validated"},
        teardown=teardown,
    ).decision == "fail"


def test_multi_stock_artifacts_require_exact_screenshots_and_removed_lock(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"png")
    second.write_bytes(b"png")
    result = multi_stock_artifacts_assertion(
        screenshots={"first": first, "second": second},
        required_screenshots={"first", "second"},
        teardown={
            "evidence": {
                "close_succeeded": True,
                "session_lock_present": False,
            }
        },
    )
    assert result.decision == "pass"


def test_mixed_mode_assertions_fail_closed_on_stale_driver_record(monkeypatch):
    import ExecutionCalibrationStore

    fixture = {
        "stocks": [
            {
                "factor_name": "Droplet", "concentration": 23.0, "units": "mM",
                "printing_mode": "droplet", "droplet_volume_nL": 9.0,
                "prepared_droplet_volume_nL": 9.0,
                "printer_head": {"printer_head_id": "head-d", "print_pulse_width_us": 1300},
            },
            {
                "factor_name": "Stream", "concentration": 23.0, "units": "mM",
                "printing_mode": "stream", "droplet_volume_nL": 60.0,
                "prepared_droplet_volume_nL": 60.0,
                "printer_head": {
                    "printer_head_id": "head-s", "print_pulse_width_us": 2500,
                    "refuel_pulse_width_us": 6000, "refuel_pressure_psi": 0.4,
                },
            },
        ],
        "lifecycle": {"manual_refuel_check": {
            "status": "passed", "operator_judgment": "stable",
            "trial_count": 2, "trial_droplet_count": 5,
        }},
    }
    records = {
        "drop": SimpleNamespace(to_dict=lambda: {
            "record_id": "drop", "stock_id": "Droplet_23.00_mM",
            "printer_head_id": "head-d", "printing_mode": "droplet",
            "applied_printing_mode": "droplet", "pw_us": 1300,
            "effective_volume_nL": 9.0, "applied_design_volume_nL": 9.0,
        }),
        "stream": SimpleNamespace(to_dict=lambda: {
            "record_id": "stream", "stock_id": "Stream_23.00_mM",
            "printer_head_id": "head-s", "printing_mode": "stream",
            "applied_printing_mode": "stream", "pw_us": 2500,
            "effective_volume_nL": 60.0, "applied_design_volume_nL": 60.0,
        }),
    }
    persisted = {
        "status": "passed", "source": "sil_simulated_manual_refuel_check",
        "stock_id": "Stream_23.00_mM", "printer_head_id": "head-s",
        "printing_mode": "stream", "operator_judgment": "stable",
        "trial_count": 2, "trial_droplet_count": 5,
        "print_pulse_width_us": 2500, "refuel_pulse_width_us": 6000,
        "target_refuel_pressure_psi": 0.4, "calibration_record_id": "stream",
        "applied_calibration_fingerprint": "current",
    }
    monkeypatch.setattr(
        ExecutionCalibrationStore,
        "load_execution_calibrations",
        lambda _path: SimpleNamespace(
            records=records, manual_refuel_checks={"check": persisted}
        ),
    )
    actions = [
        {"action_id": "calibration.apply_via_ui"},
        {"action_id": "array.start_via_ui"},
        {"action_id": "calibration.apply_via_ui"},
        {"action_id": "manual_refuel.complete_check_via_ui"},
        {"action_id": "array.start_via_ui"},
    ]
    stale = {**persisted, "applied_calibration_fingerprint": "stale"}

    calibration, refuel = mixed_mode_lifecycle_assertions(
        SimpleNamespace(experiment_model=SimpleNamespace(
            execution_calibrations_file_path="unused"
        )),
        fixture=fixture,
        manual_refuel_checks=[{"record": stale}],
        action_results=actions,
    )

    assert calibration.decision == "pass"
    assert refuel.decision == "fail"
    assert refuel.evidence["driver_record_matched"] is False


@pytest.mark.parametrize(
    ("action_id", "assertion_id"),
    [
        (
            "editor.rename_prepared_via_ui",
            "experiment.prepared_rename_refinalize",
        ),
        (
            "editor.refinalize_prepared_via_ui",
            "experiment.prepared_rename_refinalize",
        ),
        (
            "editor.edit_prepared_design_via_ui",
            "experiment.prepared_design_refinalize",
        ),
    ],
)
def test_editor_revision_failure_maps_to_stable_assertion(action_id, assertion_id):
    error = RuntimeError("synthetic failure")
    error.action_id = action_id

    result = editor_prepared_revision_failure_assertion(error)

    assert result.assertion_id == assertion_id
    assert result.decision == "fail"
    assert result.evidence["action_id"] == action_id
