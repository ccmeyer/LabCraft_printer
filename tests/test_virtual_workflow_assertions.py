from __future__ import annotations

from tools.virtual_workflows.assertions import (
    ActionSequenceExpectation,
    AssertionResult,
    ExecutionLifecycleExpectation,
    SoftStopResumeExpectation,
    cleanup_assertion,
    editor_artifacts_cleanup_assertion,
    editor_prepared_revision_failure_assertion,
    exact_action_sequence_assertion,
    evaluate_assertion,
    multi_stock_artifacts_assertion,
    mixed_mode_lifecycle_assertions,
    regression_evidence_assertions,
    soft_stop_paused_assertions,
    synthetic_calibration_contract,
)

import pytest
from types import SimpleNamespace


def test_assertion_result_rejects_ambiguous_decision():
    try:
        AssertionResult("a", "b", "unknown", (), {})
    except ValueError as exc:
        assert "pass, fail, or incomplete" in str(exc)
    else:
        raise AssertionError("ambiguous assertion decision was accepted")


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
